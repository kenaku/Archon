#!/usr/bin/env python3
import json
import os
import re
import subprocess
from pathlib import Path


def run(args):
    p = subprocess.run(args, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return p.stdout


def parse_env(path: Path) -> dict:
    env = {}
    if not path.exists():
        return env
    for line in path.read_text(errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        v = v.strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in "'\"":
            v = v[1:-1]
        env[k] = v
    return env


def parse_numstat(text: str):
    additions = deletions = 0
    by_file = {}
    for line in text.splitlines():
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        file_additions = 0 if parts[0] == "-" else int(parts[0])
        file_deletions = 0 if parts[1] == "-" else int(parts[1])
        additions += file_additions
        deletions += file_deletions
        by_file[parts[2]] = {"additions": file_additions, "deletions": file_deletions}
    return additions, deletions, by_file


def parse_hunks(diff_u0: str):
    hunks = []
    current_file = None
    change_type = "modified"
    file_re = re.compile(r"^\+\+\+ b/(.*)$")
    hunk_re = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
    for line in diff_u0.splitlines():
        if line.startswith("diff --git "):
            current_file = None
            change_type = "modified"
        elif line.startswith("new file mode"):
            change_type = "added"
        elif line.startswith("deleted file mode"):
            change_type = "deleted"
        else:
            file_match = file_re.match(line)
            if file_match:
                current_file = file_match.group(1)
                if current_file == "/dev/null":
                    current_file = None
                continue
            hunk_match = hunk_re.match(line)
            if hunk_match and current_file:
                hunks.append({
                    "file": current_file,
                    "old_start": int(hunk_match.group(1)),
                    "old_lines": int(hunk_match.group(2) or "1"),
                    "new_start": int(hunk_match.group(3)),
                    "new_lines": int(hunk_match.group(4) or "1"),
                    "change_type": change_type,
                })
    return hunks


def categorize(files):
    cats = {"source": [], "tests": [], "styles": [], "docs": [], "config": [], "deps": [], "generated": []}
    for f in files:
        low = f.lower()
        name = Path(f).name
        if re.search(r"generated|__generated__|\.gen\.|openapi|schema", low):
            cats["generated"].append(f)
        elif re.search(r"(test|spec)\.(ts|tsx|js|jsx)$|/__tests__/", low):
            cats["tests"].append(f)
        elif low.endswith((".css", ".scss", ".sass", ".less")):
            cats["styles"].append(f)
        elif low.endswith((".md", ".mdx", ".rst")) or low.startswith("docs/"):
            cats["docs"].append(f)
        elif name in {"package.json", "pnpm-lock.yaml", "yarn.lock", "package-lock.json"}:
            cats["deps"].append(f)
        elif low.endswith((".json", ".yaml", ".yml", ".toml", ".config.ts", ".config.js")):
            cats["config"].append(f)
        else:
            cats["source"].append(f)
    return cats


def grep_changed(files, pattern):
    regex = re.compile(pattern, re.I)
    hits = []
    for f in files:
        p = Path(f)
        if not p.exists() or not p.is_file():
            continue
        if regex.search(p.read_text(errors="replace")):
            hits.append(f)
    return hits


def risk_markers(files, diff_text):
    joined = "\n".join(files) + "\n" + diff_text
    return {
        "api_sdk": bool(re.search(r"api/|sdk|axios|fetch|request|client|Api\b", joined, re.I)),
        "auth_permissions": bool(re.search(r"auth|permission|company|tenant|access|role", joined, re.I)),
        "routing": bool(re.search(r"route|router|page|navigate|redirect", joined, re.I)),
        "query_cache": bool(re.search(r"queryKey|invalidate|cache|stale|gcTime|refetch|data[-_ ]?fetch", joined, re.I)),
        "forms": bool(re.search(r"form|formik|react-hook-form|zod|yup", joined, re.I)),
        "modals": bool(re.search(r"modal|dialog|drawer", joined, re.I)),
        "shared_ui": bool(re.search(r"shared/ui|components|ui/|design-system", joined, re.I)),
        "public_api": bool(re.search(r"export\s+(const|function|type|interface)|index\.ts|public-api", joined)),
        "async_effects": bool(re.search(r"useEffect|async|await|Promise|setTimeout|setInterval|AbortController|poll", joined, re.I)),
        "deps_config": any(Path(f).name in {"package.json", "pnpm-lock.yaml"} for f in files),
    }


def parse_name_status(text: str):
    statuses = {}
    added = []
    deleted = []
    renamed = []
    for line in text.splitlines():
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        status = parts[0]
        if status.startswith("R") and len(parts) >= 3:
            statuses[parts[2]] = "renamed"
            renamed.append({"from": parts[1], "to": parts[2]})
        else:
            code = status[0]
            path = parts[1]
            value = {"A": "added", "D": "deleted", "M": "modified"}.get(code, status)
            statuses[path] = value
            if code == "A":
                added.append(path)
            elif code == "D":
                deleted.append(path)
    return statuses, added, deleted, renamed


def hunks_by_file(hunks):
    by_file = {}
    for hunk in hunks:
        by_file.setdefault(hunk["file"], []).append(hunk)
    return by_file


def relative_imports(files):
    pat = re.compile(r"from ['\"](\.\./\.\.|\.\./\.\./|\.\./\.\./\.\./)|import\(['\"]\.\./\.\.")
    hits = []
    for f in files:
        p = Path(f)
        if not p.exists() or not p.is_file():
            continue
        for line_no, line in enumerate(p.read_text(errors="replace").splitlines(), 1):
            if pat.search(line):
                hits.append(f"{f}:{line_no}: {line.strip()[:180]}")
                break
    return hits


def sibling_summary(files):
    out = []
    for f in files:
        p = Path(f)
        if not p.parent.exists():
            continue
        siblings = sorted(str(x) for x in p.parent.iterdir() if x.is_file() and str(x) != f)[:8]
        if siblings:
            out.append((f, siblings))
    return out[:20]


def file_tags(path: str, text: str):
    joined = f"{path}\n{text}"
    tag_patterns = {
        "api_sdk": r"api/|sdk|axios|fetch|request|client|Api\b",
        "query_cache": r"queryKey|invalidate|cache|stale|gcTime|refetch|data[-_ ]?fetch",
        "auth_permissions": r"auth|permission|company|tenant|access|role",
        "routing": r"route|router|page|navigate|redirect",
        "forms": r"form|formik|react-hook-form|zod|yup",
        "modals": r"modal|dialog|drawer|useConfirmModal",
        "shared_ui": r"shared/ui|components|ui/|design-system",
        "public_api": r"export\s+(const|function|type|interface)|index\.ts|public-api",
        "async_effects": r"useEffect|async|await|Promise|setTimeout|setInterval|AbortController|poll",
    }
    return [tag for tag, pattern in tag_patterns.items() if re.search(pattern, joined, re.I)]


def file_signals(path: str, diff_text: str):
    signals = []
    checks = {
        "data_fetch_removed": r"^-.*(query|fetch|request|cache|client)",
        "data_fetch_added": r"^\+.*(query|fetch|request|cache|client)",
        "query_key_changed": r"^[+-].*queryKey",
        "fetcher_changed": r"^[+-].*(fetcher|queryFn)",
        "select_changed": r"^[+-].*\bselect\b",
        "retry_changed": r"^[+-].*\bretry\b",
        "stale_or_gc_changed": r"^[+-].*(staleTime|gcTime)",
        "refetch_changed": r"^[+-].*refetch",
        "exports_changed": r"^[+-]\s*export\s+",
        "options_signature_changed": r"^[+-].*(UseQueryOptions|options\?:|\.\.\.options)",
        "test_related": r"(test|spec)\.(ts|tsx|js|jsx)$|/__tests__/",
    }
    for name, pattern in checks.items():
        if re.search(pattern, diff_text, re.M):
            signals.append(name)
    return signals


def diff_by_file(diff_text: str):
    result = {}
    current = None
    buf = []
    for line in diff_text.splitlines():
        if line.startswith("diff --git "):
            if current:
                result[current] = "\n".join(buf)
            buf = [line]
            parts = line.split()
            current = parts[3][2:] if len(parts) >= 4 and parts[3].startswith("b/") else None
        else:
            buf.append(line)
    if current:
        result[current] = "\n".join(buf)
    return result


def main():
    artifacts = Path(os.environ.get("ARTIFACTS_DIR", ".artifacts"))
    review = artifacts / "review"
    review.mkdir(parents=True, exist_ok=True)
    env = parse_env(review / "target.env")
    if not env:
        print("surface: target missing; target.env not found")
        return 2

    base = env.get("BASE_REF") or "origin/master"
    head = env.get("HEAD_REF") or "HEAD"
    target_label = env.get("TARGET_LABEL", "target")
    target_url = env.get("TARGET_URL", "")
    project = env.get("PROJECT_FULL_PATH", "")

    changed_files = [x for x in run(["git", "diff", "--name-only", f"{base}...HEAD"]).splitlines() if x]
    name_status = run(["git", "diff", "--name-status", f"{base}...HEAD"])
    numstat = run(["git", "diff", "--numstat", f"{base}...HEAD"])
    diff_u0 = run(["git", "diff", "-U0", "--unified=0", f"{base}...HEAD"])
    diff_full = run(["git", "diff", "--unified=8", f"{base}...HEAD", "--", *changed_files[:80]]) if changed_files else ""

    additions, deletions, numstat_by_file = parse_numstat(numstat)
    hunks = parse_hunks(diff_u0)
    hunk_map = hunks_by_file(hunks)
    status_map, added_files, deleted_files, renamed_files = parse_name_status(name_status)
    per_file_diff = diff_by_file(diff_full)
    cats = categorize(changed_files)
    risks = risk_markers(changed_files, diff_full)
    size_warning = len(changed_files) > 30 or additions + deletions > 700
    head_sha = run(["git", "rev-parse", "HEAD"]).strip()
    base_sha = run(["git", "rev-parse", base]).strip()
    behind_raw = run(["git", "rev-list", "--count", f"HEAD..{base}"]).strip()
    behind = int(behind_raw) if behind_raw.isdigit() else 0

    rel_import_hits = relative_imports(changed_files)
    files = []
    for path in changed_files:
        diff_for_file = per_file_diff.get(path, "")
        stats = numstat_by_file.get(path, {"additions": 0, "deletions": 0})
        files.append({
            "path": path,
            "status": status_map.get(path, "modified"),
            "additions": stats["additions"],
            "deletions": stats["deletions"],
            "tags": file_tags(path, diff_for_file),
            "signals": file_signals(path, diff_for_file),
            "hunks": hunk_map.get(path, []),
        })

    surface_json = {
        "target": {
            "label": target_label,
            "url": target_url,
            "project": project,
            "base_ref": base,
            "base_sha": base_sha,
            "head_ref": head,
            "head_sha": head_sha,
        },
        "summary": {
            "changed_files_count": len(changed_files),
            "additions": additions,
            "deletions": deletions,
            "hunks_count": len(hunks),
            "categories": {key: len(value) for key, value in cats.items()},
            "tests_changed": len(cats["tests"]),
            "size_warning": size_warning,
            "ci_status": "not_checked",
            "gitlab_state_checked": False,
        },
        "risk_markers": risks,
        "pre_review": {
            "draft": False,
            "conflicts": False,
            "ci_status": "not_checked",
            "behind_base": behind,
            "size_warning": size_warning,
        },
        "files": files,
        "mechanical": {
            "relative_parent_imports": rel_import_hits,
            "added_files": added_files,
            "deleted_files": deleted_files,
            "renamed_files": renamed_files,
            "test_files_changed": cats["tests"],
        },
        "review_contract": {
            "rule": "findings must be on changed hunks, caused by changed contracts, newly exposed by this MR, or made worse by this MR",
            "hunks_location": "surface.json files[].hunks",
            "gitlab_state_checked": False,
            "ci_checked": False,
        },
    }

    surface_summary_json = {
        "schema_version": 1,
        "target": surface_json["target"],
        "summary": surface_json["summary"],
        "risk_markers": surface_json["risk_markers"],
        "pre_review": surface_json["pre_review"],
        "mechanical_counts": {
            "relative_parent_imports": len(rel_import_hits),
            "added_files": len(added_files),
            "deleted_files": len(deleted_files),
            "renamed_files": len(renamed_files),
            "test_files_changed": len(cats["tests"]),
        },
        "review_contract": {
            **surface_json["review_contract"],
            "hunks_location": "surface-hunks.json hunks_by_file",
        },
    }
    surface_files_json = {
        "schema_version": 1,
        "target": surface_json["target"],
        "summary": surface_json["summary"],
        "files": [
            {
                "path": f["path"],
                "status": f["status"],
                "additions": f["additions"],
                "deletions": f["deletions"],
                "tags": f["tags"],
                "signals": f["signals"],
                "hunks_count": len(f.get("hunks") or []),
            }
            for f in files
        ],
    }
    surface_hunks_json = {
        "schema_version": 1,
        "target": surface_json["target"],
        "hunks_by_file": {path: hunk_map.get(path, []) for path in changed_files},
    }
    surface_mechanical_json = {
        "schema_version": 1,
        "target": surface_json["target"],
        "mechanical": surface_json["mechanical"],
    }

    (review / "surface.json").write_text(json.dumps(surface_json, separators=(",", ":")))
    (review / "surface-summary.json").write_text(json.dumps(surface_summary_json, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    (review / "surface-files.json").write_text(json.dumps(surface_files_json, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    (review / "surface-hunks.json").write_text(json.dumps(surface_hunks_json, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    (review / "surface-mechanical.json").write_text(json.dumps(surface_mechanical_json, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    for stale_name in ["surface.md", "changed-hunks.json", "changed-files.txt"]:
        stale_path = review / stale_name
        if stale_path.exists():
            stale_path.unlink()
    active = ",".join(k for k, v in risks.items() if v) or "none"
    print(f"surface: {len(changed_files)} files, +{additions}/-{deletions}, {len(hunks)} hunks")
    print(f"risk: {active}")
    print("artifacts: review/surface.json, review/surface-summary.json, review/surface-files.json, review/surface-hunks.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
