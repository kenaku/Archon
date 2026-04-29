#!/usr/bin/env python3
import json
import os
import re
import subprocess
from pathlib import Path

MAX_HITS = 80
SEARCH_ROOTS = ("packages", "src", "lib", "apps")
SKIP_DIRS = {".git", "node_modules", "dist", "build", "coverage", ".next", ".nuxt", ".svelte-kit", "artifacts", "logs"}

command_count = 0


def run(args):
    global command_count
    command_count += 1
    proc = subprocess.run(args, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return proc.returncode, proc.stdout, proc.stderr


def load_json(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def load_env(path):
    out = {}
    if not path.exists():
        return out
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not raw or raw.lstrip().startswith("#") or "=" not in raw:
            continue
        key, value = raw.split("=", 1)
        out[key.strip()] = value.strip().strip('"').strip("'")
    return out


def safe_rel_path(value):
    if not isinstance(value, str) or not value:
        return ""
    path = value.strip()
    if path.startswith("/") or ".." in Path(path).parts:
        return ""
    return path


def safe_int(value):
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def ref_exists(ref):
    code, _, _ = run(["git", "rev-parse", "--verify", f"{ref}^{{commit}}"])
    return code == 0


def git_show(ref, path):
    if not path:
        return ""
    code, out, _ = run(["git", "show", f"{ref}:{path}"])
    return out if code == 0 else ""


def read_head_file(head_ref, path):
    if head_ref and head_ref != "HEAD" and ref_exists(head_ref):
        return git_show(head_ref, path)
    p = Path(path)
    if p.exists() and p.is_file():
        return p.read_text(encoding="utf-8", errors="replace")
    return git_show("HEAD", path)


def git_diff(base_ref, head_ref, path, unified=20):
    if not path:
        return "", "diff_missing_path", []
    headish = head_ref if head_ref and head_ref != "HEAD" and ref_exists(head_ref) else "HEAD"
    cmd = ["git", "diff", f"--unified={unified}", f"{base_ref}...{headish}", "--", path]
    code, out, err = run(cmd)
    if code != 0 and headish != "HEAD":
        cmd = ["git", "diff", f"--unified={unified}", f"{base_ref}...HEAD", "--", path]
        code, out, err = run(cmd)
    if code != 0:
        return "", (err or "git diff failed").strip()[:240], [" ".join(cmd)]
    return out, "", [" ".join(cmd)]


def available_search_roots():
    roots = [r for r in SEARCH_ROOTS if Path(r).is_dir()]
    return roots or ["."]


def git_grep(pattern, roots=None, max_hits=MAX_HITS, include_ext=(".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".py", ".rb", ".go", ".rs", ".java", ".kt", ".swift", ".vue", ".svelte")):
    roots = roots or available_search_roots()
    hits = []
    for root in roots:
        if len(hits) >= max_hits:
            break
        code, out, _ = run(["git", "grep", "-n", "-I", "-E", pattern, "--", root])
        if code not in (0, 1):
            continue
        for line in out.splitlines():
            file = line.split(":", 1)[0]
            parts = set(Path(file).parts)
            if parts & SKIP_DIRS:
                continue
            if include_ext and not any(file.endswith(ext) for ext in include_ext):
                continue
            hits.append(line[:260])
            if len(hits) >= max_hits:
                break
    return hits


def normalize(text):
    return re.sub(r"\s+", " ", (text or "").strip())


def split_lines_window(text, line, radius=80):
    lines = text.splitlines()
    if not isinstance(line, int) or line <= 0:
        return text
    start = max(0, line - radius - 1)
    end = min(len(lines), line + radius)
    return "\n".join(lines[start:end])


def terms(text):
    return list(dict.fromkeys(re.findall(r"[A-Za-z_][A-Za-z0-9_.$-]{2,}", text or "")))


def flat_literals(text):
    out = []
    for match in re.findall(r"`([^`]{2,100})`|'([^']{2,100})'|\"([^\"]{2,100})\"", text or ""):
        value = next((x for x in match if x), "")
        if value and value not in out:
            out.append(value)
    return out


def candidate_text(candidate):
    ownership_check = candidate.get("ownership_check") if isinstance(candidate.get("ownership_check"), dict) else {}
    parts = [
        candidate.get("title") or "",
        candidate.get("claim") or "",
        candidate.get("symbol") or "",
        candidate.get("causality_hypothesis") or "",
        ownership_check.get("base_head_focus") or "",
        " ".join(ownership_check.get("suggested_commands") or []),
    ]
    return "\n".join(str(p) for p in parts if p)


def find_symbol(candidate):
    explicit = candidate.get("symbol")
    if isinstance(explicit, str) and explicit:
        return explicit.split(".")[-1]
    text = candidate_text(candidate)
    for token in terms(text):
        if token.startswith(("use", "get", "set", "create")) or token.endswith(("Query", "Mutation", "Options", "Client")):
            return token.split(".")[-1]
    return ""


def same_line_calls_for_terms(verbs, terms_):
    pats = []
    for term in terms_:
        escaped = re.escape(term)
        verb = r"(?:" + "|".join(re.escape(v) for v in verbs) + r")"
        pats.append(verb + r"[^\n]*" + escaped + r"|" + escaped + r"[^\n]*" + verb)
    hits = []
    for pat in pats:
        hits.extend(git_grep(pat, max_hits=MAX_HITS - len(hits)))
        if len(hits) >= MAX_HITS:
            break
    return list(dict.fromkeys(hits))[:MAX_HITS]


def direct_reexport(symbol, old_source):
    if not symbol or not old_source:
        return []
    hits = git_grep(re.escape(symbol), roots=[r for r in ("packages", "src", "lib", "apps") if Path(r).is_dir()], max_hits=200)
    out = []
    export_re = re.compile(r"export\s*\{[\s\S]*?\}\s*from\s*['\"]" + re.escape(old_source) + r"['\"]")
    star_re = re.compile(r"export\s*\*\s*from\s*['\"]" + re.escape(old_source) + r"['\"]")
    for hit in hits:
        file = hit.split(":", 1)[0]
        path = Path(file)
        if not path.exists() or path.is_dir():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if symbol in text and old_source in text and (export_re.search(text) or star_re.search(text)):
            out.append(hit)
    return list(dict.fromkeys(out))[:20]


def callable_factory_facts(factory_name):
    if not factory_name:
        return False, []
    hits = []
    for pat in (r"Object[.]assign[[:space:]]*[(]", r"const[[:space:]]+useHook\b|function[[:space:]]+useHook\b"):
        hits.extend(git_grep(pat, roots=[r for r in ("packages", "src", "lib", "apps") if Path(r).is_dir()], max_hits=200))
    by_file = {}
    for hit in hits:
        file = hit.split(":", 1)[0]
        by_file.setdefault(file, []).append(hit)
    ok_hits = []
    for file, file_hits in by_file.items():
        joined = "\n".join(file_hits)
        if "Object.assign" in joined and "useHook" in joined:
            ok_hits.extend(file_hits)
    return bool(ok_hits), ok_hits[:12]


def call_option_merge_facts():
    hits = []
    for pat in (r"\.\.\.base[A-Za-z0-9_]*[^\n]*\.\.\.call[A-Za-z0-9_]*", r"\.\.\.call[A-Za-z0-9_]*[^\n]*\.\.\.base[A-Za-z0-9_]*", r"callTopLevel|baseTopLevel"):
        hits.extend(git_grep(pat, roots=available_search_roots(), max_hits=MAX_HITS))
    joined = "\n".join(hits)
    return bool(re.search(r"call[A-Za-z0-9_]*", joined) and re.search(r"base[A-Za-z0-9_]*", joined)), list(dict.fromkeys(hits))[:16]


def callback_compat_facts(callback_name):
    if not callback_name:
        return False, []
    escaped = re.escape(callback_name)
    hits = []
    for pat in (escaped, r"status\s*===\s*['\"](?:error|success)['\"]", r"use[A-Za-z0-9_]*Callbacks"):
        hits.extend(git_grep(pat, roots=available_search_roots(), max_hits=MAX_HITS))
    joined = "\n".join(hits)
    supported = callback_name in joined and ("Callbacks" in joined or re.search(r"status\s*===\s*['\"](?:error|success)['\"]", joined))
    return bool(supported), list(dict.fromkeys(hits))[:20]


def guard_has_return(window, var_name):
    pat = re.compile(r"if\s*\(\s*!\s*" + re.escape(var_name) + r"\s*\)\s*\{(?P<body>.*?)\}", re.S)
    for match in pat.finditer(window):
        if re.search(r"\breturn\b", match.group("body")):
            return True, normalize(match.group(0))[:220]
    return False, ""


def classify_from_hard_facts(hard_rejects, diff_presence):
    if any(item["kind"] == "no_mr_evidence" for item in hard_rejects):
        return "no_mr_evidence", "high"
    if hard_rejects:
        return "hard_reject", "high"
    if diff_presence == "file_not_changed":
        return "no_mr_evidence", "high"
    return "needs_llm", "medium"


def analyze(candidate, base_ref, head_ref):
    cid = candidate.get("id") or candidate.get("candidate_id") or "unknown"
    path = safe_rel_path(candidate.get("file"))
    line = safe_int(candidate.get("line"))
    title = candidate.get("title") or candidate.get("claim") or ""
    text = candidate_text(candidate)
    low = text.lower()
    result = {
        "candidate_id": cid,
        "file": path,
        "line": line,
        "symbol": candidate.get("symbol") or find_symbol(candidate),
        "title": title,
        "deterministic_verdict": "needs_llm",
        "ownership_hint": "needs_llm",
        "confidence": "medium",
        "diff_presence": "unknown",
        "hard_rejects": [],
        "facts": [],
        "commands": [],
    }
    if not path:
        result["diff_presence"] = "missing_file_path"
        result["deterministic_verdict"] = "hard_reject"
        result["ownership_hint"] = "no_mr_evidence"
        result["confidence"] = "high"
        result["hard_rejects"].append({"kind": "missing_file_path", "reason": "candidate has no safe relative file path"})
        return result

    headish = head_ref if head_ref and head_ref != "HEAD" and ref_exists(head_ref) else "HEAD"
    diff, diff_error, diff_commands = git_diff(base_ref, headish, path, unified=20)
    result["commands"].extend(diff_commands)
    if diff_error:
        result["diff_presence"] = "diff_error"
        result["facts"].append({"kind": "diff_error", "reason": diff_error})
    elif diff.strip():
        result["diff_presence"] = "file_changed"
    else:
        result["diff_presence"] = "file_not_changed"
        result["hard_rejects"].append({"kind": "no_mr_evidence", "reason": "candidate file has no diff in this MR"})

    head_text = read_head_file(headish, path)
    base_text = git_show(base_ref, path)
    if headish != "HEAD" and head_text:
        result["commands"].append(f"git show {headish}:{path}")
    if base_text:
        result["commands"].append(f"git show {base_ref}:{path}")
    window = split_lines_window(head_text, line, radius=80)
    result["facts"].append({"kind": "diff_locality", "value": result["diff_presence"]})

    removed_claim = re.search(r"\b(removed|lost|loses|dropped|absent|lacks|missing|does not include|silently dropped)\b", low)
    if removed_claim:
        names = [x for x in flat_literals(text) + terms(text) if len(x) >= 4]
        present = []
        stop = {"removed", "dropped", "absent", "missing", "claim", "query", "return", "returns", "caller", "callers", "changed", "changes", "candidate", "file", "line"}
        for name in names:
            if name.lower() in stop:
                continue
            if name in window or name in head_text:
                present.append(name)
        if present:
            result["facts"].append({"kind": "claimed_removed_terms_present_in_head", "terms": present[:12]})
            strong = [x for x in present if x in {"select", "refetchOnMount", "enabled", "return"} or re.match(r"[A-Za-z_][A-Za-z0-9_]*\(", x)]
            if strong:
                result["hard_rejects"].append({
                    "kind": "claim_contradicted_by_head_presence",
                    "reason": "claim says behavior/option was removed, but a named term is present in head near the candidate",
                    "terms": strong[:8],
                })

    if "select" in low and re.search(r"removed|absent|dropped|missing", low) and re.search(r"\bselect\b|sort[A-Za-z0-9_]*", window):
        result["hard_rejects"].append({"kind": "transform_preserved", "reason": "claimed removed transform term exists in the head candidate window"})

    if "refetchonmount" in low and re.search(r"dropped|absent|missing|does not include|silently", low) and "refetchOnMount" in window:
        result["hard_rejects"].append({"kind": "option_preserved", "reason": "claimed removed option appears in the head candidate window"})

    if "enabled" in low and re.search(r"removed|lose|lost|suppress|guard", low):
        hits = []
        for pat in (r"enabled\s*:", r"Boolean\([^\n]*\)\s*&&\s*enabled"):
            hits.extend(git_grep(pat, max_hits=40))
        prefix = "/".join(path.split("/")[: max(1, len(path.split("/")) - 2)])
        related = [h for h in hits if h.startswith(prefix) or Path(h.split(":", 1)[0]).parent == Path(path).parent]
        result["facts"].append({"kind": "enabled_guard_hits", "hits": related[:8]})
        if related:
            result["hard_rejects"].append({"kind": "enabled_guard_preserved", "reason": "enabled guard or option still exists in related head code", "hits": related[:4]})

    if re.search(r"invalidateQueries|invalidation|bust|orphan", text, re.I):
        caps = [x for x in dict.fromkeys(re.findall(r"\b[A-Z][A-Z0-9_]{3,}\b", text)) if x not in {"BASE_REF", "HEAD", "HEAD_REF"}]
        hits = same_line_calls_for_terms(["invalidateQueries", "refetchQueries", "setQueryData"], caps)
        result["facts"].append({"kind": "invalidation_hits_for_claim_terms", "terms": caps, "hits": hits[:20]})
        if caps and not hits:
            result["hard_rejects"].append({"kind": "no_invalidation_callers", "reason": "no invalidate/refetch/setQueryData callers found for claimed key or prefix terms"})

    if "import source changed" in low or "separate" in low and "client" in low or "direct re-export" in low:
        symbol = find_symbol(candidate)
        package_sources = re.findall(r"@[A-Za-z0-9_.-]+/[A-Za-z0-9_./-]+", text)
        instead_match = re.search(r"instead of\s+(@[A-Za-z0-9_.-]+/[A-Za-z0-9_./-]+)", text, re.I)
        old_source = instead_match.group(1) if instead_match else (package_sources[-1] if len(package_sources) >= 2 else (package_sources[0] if package_sources else ""))
        hits = direct_reexport(symbol, old_source) if old_source else []
        result["facts"].append({"kind": "import_equivalence_hits", "symbol": symbol, "old_source": old_source, "hits": hits[:12]})
        if hits:
            result["hard_rejects"].append({"kind": "direct_reexport_equivalent", "reason": "new import package directly re-exports the claimed symbol from the old package", "hits": hits[:4]})

    if re.search(r"zero-arg|call signature|call contract|breaking[^\n]*call", low):
        symbol = find_symbol(candidate)
        callable_ok, impl_hits = callable_factory_facts("createQuery" if "createquery" in low else "")
        caller_hits = git_grep(re.escape(symbol) + r"\s*\(\s*\)", max_hits=40) if symbol else []
        result["facts"].append({"kind": "callable_factory_check", "callable": callable_ok, "symbol": symbol, "zero_arg_callers": caller_hits[:8], "impl_hits": impl_hits[:8]})
        if callable_ok and caller_hits:
            result["hard_rejects"].append({"kind": "factory_is_callable", "reason": "factory implementation returns a callable hook/function and zero-argument call sites exist", "hits": impl_hits[:4] + caller_hits[:4]})

    callback_match = re.search(r"\b(on[A-Z][A-Za-z0-9_]*)\b", text)
    if callback_match and re.search(r"support|removed|v5|silently|never fires|callback", low):
        callback = callback_match.group(1)
        supported, hits = callback_compat_facts(callback)
        result["facts"].append({"kind": "callback_compat_hits", "callback": callback, "supported": supported, "hits": hits[:12]})
        if supported:
            result["hard_rejects"].append({"kind": "callback_compat_present", "reason": f"helper code contains compatibility handling for {callback}", "hits": hits[:6]})

    if "override" in low and re.search(r"option|options|refetchonmount|enabled", low):
        merged, hits = call_option_merge_facts()
        result["facts"].append({"kind": "call_options_merge_hits", "merged": merged, "hits": hits[:12]})
        if merged:
            result["hard_rejects"].append({"kind": "call_options_override_supported", "reason": "helper code merges call-level options with base options", "hits": hits[:6]})

    if re.search(r"null dereference|lacks a return|missing return|fall.*through", low):
        var = "error" if "error" in low else "value"
        ok, snippet = guard_has_return(window, var)
        result["facts"].append({"kind": "guard_return_check", "var": var, "has_return": ok, "snippet": snippet})
        if ok:
            result["hard_rejects"].append({"kind": "guard_has_return", "reason": f"if (!{var}) guard contains return before later access", "snippet": snippet})

    if "isinitialloading" in low and "isloading" in low:
        hits = []
        for pat in (r"isLoading\s*=\s*isPending\s*&&\s*isFetching", r"isLoading\s*:\s*[^\n]*isPending[^\n]*isFetching", r"with[A-Za-z0-9_]*Loading[A-Za-z0-9_]*"):
            hits.extend(git_grep(pat, max_hits=50))
        joined = "\n".join(hits)
        result["facts"].append({"kind": "loading_semantics_hits", "hits": list(dict.fromkeys(hits))[:12]})
        if "isPending" in joined and "isFetching" in joined:
            result["hard_rejects"].append({"kind": "loading_semantics_adapter_found", "reason": "adapter defines isLoading from isPending and isFetching, contradicting the broad refetch-loading claim", "hits": list(dict.fromkeys(hits))[:6]})

    hint, confidence = classify_from_hard_facts(result["hard_rejects"], result["diff_presence"])
    result["ownership_hint"] = hint
    result["confidence"] = confidence
    result["deterministic_verdict"] = "hard_reject" if hint in {"hard_reject", "no_mr_evidence"} else "needs_llm"
    result["facts"] = result["facts"][:16]
    result["commands"] = list(dict.fromkeys(result["commands"]))[:20]
    return result


def main():
    artifacts = Path(os.environ["ARTIFACTS_DIR"])
    review = artifacts / "review"
    env = load_env(review / "target.env")
    base_ref = env.get("BASE_REF") or env.get("TARGET_BRANCH") or "origin/master"
    head_ref = env.get("HEAD_REF") or "HEAD"
    candidates_doc = load_json(review / "candidates.json")
    candidates = candidates_doc.get("candidates") or []
    results = [analyze(candidate, base_ref, head_ref) for candidate in candidates]
    counts = {}
    verdict_counts = {}
    for result in results:
        counts[result["ownership_hint"]] = counts.get(result["ownership_hint"], 0) + 1
        verdict_counts[result["deterministic_verdict"]] = verdict_counts.get(result["deterministic_verdict"], 0) + 1
    doc = {
        "schema_version": 2,
        "base_ref": base_ref,
        "head_ref": head_ref,
        "input_candidates": len(candidates),
        "hint_counts": counts,
        "deterministic_verdict_counts": verdict_counts,
        "pass_hint_values": [],
        "command_count": command_count,
        "results": results,
    }
    out = review / "ownership-precheck.json"
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    print(f"Ownership precheck: {len(candidates)} candidates, {counts}, commands: {command_count}")


if __name__ == "__main__":
    main()
