#!/usr/bin/env python3
import json
import os
import re
import subprocess
from pathlib import Path


def run(args):
    proc = subprocess.run(args, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return proc.stdout if proc.returncode == 0 else ""


def load(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def load_surface(review):
    summary_path = review / "surface-summary.json"
    files_path = review / "surface-files.json"
    if summary_path.exists() and files_path.exists():
        summary_doc = load(summary_path)
        files_doc = load(files_path)
        return {
            "target": summary_doc.get("target", {}),
            "summary": summary_doc.get("summary", {}),
            "risk_markers": summary_doc.get("risk_markers", {}),
            "files": files_doc.get("files") or [],
        }
    return load(review / "surface.json")


def make_candidate(sev, title, file, line, claim_type, symbol, claim, focus, proof):
    return {
        "severity_hypothesis": sev,
        "title": title,
        "file": file,
        "line": line,
        "claim_type": claim_type,
        "symbol": symbol,
        "claim": claim,
        "causality_hypothesis": "Deterministic detector matched a generic changed-line risk pattern; ownership gate must verify base vs head.",
        "evidence": ["generic detector hit; exact ownership still unchecked"],
        "ownership_check": {
            "base_head_focus": focus,
            "suggested_commands": [f"git diff $BASE_REF...HEAD -- {file}", f"git show $BASE_REF:{file}"],
        },
        "proof_plan": proof,
        "likely_check_command": "",
    }


def added_lines(diff_text):
    head_line = None
    out = []
    hunk_re = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")
    for raw in diff_text.splitlines():
        m = hunk_re.match(raw)
        if m:
            head_line = int(m.group(1))
            continue
        if head_line is None or raw.startswith("+++") or raw.startswith("---"):
            continue
        if raw.startswith("+"):
            out.append((head_line, raw[1:]))
            head_line += 1
        elif raw.startswith("-"):
            continue
        elif raw.startswith(" "):
            head_line += 1
    return out


def first_match(lines, patterns):
    for line_no, line in lines:
        for pattern in patterns:
            if re.search(pattern, line):
                return line_no, line.strip(), pattern
    return None


def main():
    review = Path(os.environ["ARTIFACTS_DIR"]) / "review"
    surface = load_surface(review)
    base_ref = surface.get("target", {}).get("base_ref") or "origin/master"
    files = [f.get("path", "") for f in surface.get("files") or []]
    candidates = []
    incidental = []
    seen_roots = set()

    detectors = [
        {
            "key": "double_cast",
            "severity": "P3",
            "title": "changed code adds a double type assertion",
            "claim_type": "type_safety",
            "patterns": [r"\bas\s+unknown\s+as\b", r"\bas\s+any\s+as\b"],
            "claim": "Changed code adds a double type assertion that may hide a real type mismatch.",
            "focus": "Compare whether the double assertion or equivalent type escape is new in this MR.",
            "proof": "Verify the source and target types and whether the assertion can mask a real runtime or API contract mismatch.",
        },
        {
            "key": "suppression",
            "severity": "P3",
            "title": "changed code adds a static-analysis suppression",
            "claim_type": "type_safety",
            "patterns": [r"@ts-ignore", r"@ts-expect-error", r"eslint-disable"],
            "claim": "Changed code adds a compiler or lint suppression that may hide a concrete defect.",
            "focus": "Compare whether the suppression is new and what diagnostic or rule it bypasses.",
            "proof": "Verify the suppressed diagnostic/rule and whether it hides a real correctness issue.",
        },
        {
            "key": "non_null",
            "severity": "P3",
            "title": "changed code adds a non-null assertion",
            "claim_type": "nullability",
            "patterns": [r"[A-Za-z0-9_\])}]!\.[A-Za-z_]", r"[A-Za-z0-9_\])}]!\["],
            "claim": "Changed code adds a non-null assertion on a value that may still be nullable.",
            "focus": "Compare whether the non-null assertion is new and whether base had a guard or different nullable contract.",
            "proof": "Verify the nullable source and whether the asserted value can be absent on a reachable path.",
        },
        {
            "key": "public_manifest_dependency",
            "severity": "P3",
            "title": "package manifest adds a runtime dependency",
            "claim_type": "api_contract",
            "patterns": [r"^\s*\"[^\"]+\"\s*:\s*\"[~^]?\d"],
            "claim": "A package manifest adds a runtime dependency; verify package boundary and runtime ownership implications.",
            "focus": "Compare manifest dependency additions and whether code in the package now depends on a new runtime boundary.",
            "proof": "Verify whether the new dependency is appropriate for this package's public/runtime contract.",
            "file_suffix": "package.json",
        },
    ]

    for path in files:
        if not path or not Path(path).exists():
            continue
        if not path.endswith((".ts", ".tsx", ".js", ".jsx", ".json")):
            continue
        diff = run(["git", "diff", "--unified=0", f"{base_ref}...HEAD", "--", path])
        if not diff.strip():
            continue
        lines = added_lines(diff)
        for detector in detectors:
            if detector.get("file_suffix") and not path.endswith(detector["file_suffix"]):
                continue
            hit = first_match(lines, detector["patterns"])
            if not hit:
                continue
            line_no, line_text, _ = hit
            root = (detector["key"], path)
            if root in seen_roots:
                continue
            seen_roots.add(root)
            candidates.append(make_candidate(
                detector["severity"],
                detector["title"],
                path,
                line_no,
                detector["claim_type"],
                "",
                detector["claim"],
                detector["focus"],
                detector["proof"],
            ))
            candidates[-1]["evidence"].append(f"added line matches generic {detector['key']} risk pattern")
            if len(candidates) >= 8:
                break
        if len(candidates) >= 8:
            break

    for i, candidate in enumerate(candidates, 1):
        candidate["id"] = f"D-{i}"
        candidate["source_reviewers"] = ["detectors"]

    out = {
        "schema_version": 1,
        "candidates": candidates,
        "incidental_observations": incidental,
        "summary": {
            "detectors": "generic_changed_line_risk_patterns",
            "candidate_count": len(candidates),
        },
    }
    out_path = review / "reviewer-findings-detectors.json"
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    print(f"Detector findings: {len(candidates)} candidates.")


if __name__ == "__main__":
    main()
