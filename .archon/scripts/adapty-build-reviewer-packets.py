#!/usr/bin/env python3
import json
import os
import re
import subprocess
from pathlib import Path

REVIEWERS = ["architecture", "typescript", "races", "security_performance", "styling", "simplicity", "playbooks"]

LENS = {
    "architecture": {
        "contract_docs": ["docs/frontend/architecture.md", "docs/frontend/public-api.md"],
        "checklist": [
            "FSD layer or slice ownership is crossed by changed imports/exports.",
            "Public API/barrel/export changes create caller or package-boundary risk.",
            "Business ownership moves into shared UI or reusable package code.",
            "A new abstraction duplicates an existing layer contract.",
        ],
        "tags": {"public_api", "shared_ui", "api_sdk"},
        "signals": {"exports_changed", "options_signature_changed"},
        "path_re": r"(^packages/|/shared/|/ui/|index\.ts$|public-api|components/)",
    },
    "typescript": {
        "contract_docs": ["docs/frontend/typescript.md", "docs/frontend/react-patterns.md", "docs/frontend/constants.md"],
        "checklist": [
            "Changed TS/React contract preserves return type, nullability, options, and generics.",
            "Changed data-fetching contract preserves options, keys, transforms, and execution conditions.",
            "No unsafe widening, casts, or hidden runtime shape changes were introduced.",
            "Constants and keys preserve caller-visible semantics.",
        ],
        "tags": {"query_cache", "api_sdk", "public_api"},
        "signals": {"query_hook_removed", "query_factory_added", "query_key_changed", "fetcher_changed", "select_changed", "retry_changed", "stale_or_gc_changed", "refetch_changed", "options_signature_changed"},
        "path_re": r"\.(ts|tsx)$",
    },
    "races": {
        "contract_docs": ["docs/frontend/react-patterns.md", "docs/frontend/forms.md", "docs/frontend/modals.md"],
        "checklist": [
            "Async ordering, enabled flags, refetch, or stale closures did not change silently.",
            "Form/modal close/reset/loading lifecycle is preserved.",
            "Cache updates and request completion cannot expose stale UI state.",
            "Candidate must include concrete event order, not a generic async concern.",
        ],
        "tags": {"async_effects", "forms", "modals"},
        "signals": {"refetch_changed", "query_key_changed", "fetcher_changed", "select_changed"},
        "path_re": r"\.(ts|tsx)$",
    },
    "security_performance": {
        "contract_docs": ["docs/api-reference.md", "docs/frontend/react-patterns.md"],
        "checklist": [
            "Auth, company, tenant, role, or permission scoping is not widened.",
            "Query keys and cache scopes do not leak data across tenants or contexts.",
            "Runtime dependency and render/request cost are not meaningfully increased.",
            "Candidate must describe concrete mechanism and impact.",
        ],
        "tags": {"auth_permissions", "deps_config", "routing"},
        "signals": {"query_key_changed", "fetcher_changed", "stale_or_gc_changed", "retry_changed"},
        "path_re": r"(package\.json|pnpm-lock\.yaml|\.(ts|tsx)$)",
    },
    "styling": {
        "contract_docs": ["docs/frontend/styling.md"],
        "checklist": [
            "CSS module/token/variant/responsive/dark-theme contract is preserved.",
            "Shared UI styling changes do not break existing callers.",
            "Candidate must name exact class/token/variant/state.",
        ],
        "tags": {"shared_ui"},
        "signals": set(),
        "path_re": r"\.(css|scss|sass|less|tsx)$",
    },
    "simplicity": {
        "contract_docs": ["docs/frontend/architecture.md", "docs/frontend/public-api.md", "docs/frontend/react-patterns.md"],
        "checklist": [
            "New abstraction removes real duplication instead of adding indirection.",
            "Repeated changed pattern should be represented consistently across files.",
            "Maintenance concern must have concrete cost and MR causality hypothesis.",
        ],
        "tags": {"query_cache", "public_api", "shared_ui", "api_sdk"},
        "signals": {"query_factory_added", "exports_changed", "options_signature_changed"},
        "path_re": r"\.(ts|tsx)$",
    },
    "playbooks": {
        "contract_docs": ["docs/playbooks/index.md"],
        "checklist": [
            "Use docs/playbooks/index.md as the router for canonical playbooks.",
            "Read a specific docs/playbooks/*.md only when the changed hunks match that playbook's documented touchpoints or subject.",
            "Report only violations of an applicable docs/playbooks rule; do not run a broad semantic review.",
            "If no docs/playbooks playbook applies to the changed hunks, emit zero candidates.",
        ],
        "tags": {"query_cache", "api_sdk", "public_api", "shared_ui", "forms", "modals", "routing", "auth_permissions", "deps_config"},
        "signals": {"query_hook_removed", "query_factory_added", "query_key_changed", "fetcher_changed", "select_changed", "retry_changed", "stale_or_gc_changed", "refetch_changed", "exports_changed", "options_signature_changed"},
        "path_re": r".*",
    },
}

MAX_FILES_PER_PACKET = 18
MAX_EXCERPT_FILES_PER_PACKET = 5
MAX_EXCERPT_LINES_PER_FILE = 20
MAX_FOCUSED_LINES_PER_FILE = 28
MAX_LINE_CHARS = 170
MAX_SYMBOLS_PER_FILE = 6
MAX_SYMBOLS_PER_PACKET = 14
MAX_CALLERS_PER_SYMBOL = 4
MAX_REFERENCE_LINES = 16

FOCUS_RE = re.compile(
    r"(import |export | from ['\"]|function |const |let |return |throw |catch |async |await |enabled|select|retry|cache|key|fetch|effect|mutation|invalidat|refetch|stale|loading|error|success|settled|as unknown| as [A-ZI])",
    re.IGNORECASE,
)



def normalize_signals(signals):
    normalized = []
    for signal in signals:
        lowered = str(signal).lower()
        if "query" in lowered and "removed" in lowered and "hook" not in lowered:
            normalized.append("query_hook_removed")
        elif "query" in lowered and "added" in lowered and "factory" not in lowered:
            normalized.append("query_factory_added")
        else:
            normalized.append(signal)
    return normalized


def caller_roots(selected_paths):
    roots = []
    for path in selected_paths:
        parts = Path(path).parts
        candidates = []
        if len(parts) >= 3:
            candidates.append(str(Path(*parts[:3])))
        if len(parts) >= 2:
            candidates.append(str(Path(*parts[:2])))
        if parts:
            candidates.append(parts[0])
        for candidate in candidates:
            if Path(candidate).exists():
                if candidate not in roots:
                    roots.append(candidate)
                break
    return roots or ["."]

def load_json(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def load_surface(review):
    summary_path = review / "surface-summary.json"
    files_path = review / "surface-files.json"
    hunks_path = review / "surface-hunks.json"
    if summary_path.exists() and files_path.exists() and hunks_path.exists():
        summary_doc = load_json(summary_path)
        files_doc = load_json(files_path)
        hunks_doc = load_json(hunks_path)
        hunks_by_file = hunks_doc.get("hunks_by_file") or {}
        files = []
        for item in files_doc.get("files") or []:
            enriched = dict(item)
            enriched["hunks"] = hunks_by_file.get(item.get("path", ""), [])
            files.append(enriched)
        return {
            "target": summary_doc.get("target", {}),
            "summary": summary_doc.get("summary", {}),
            "risk_markers": summary_doc.get("risk_markers", {}),
            "files": files,
        }
    return load_json(review / "surface.json")


def run(args, timeout=20):
    try:
        p = subprocess.run(args, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
        return p.stdout
    except Exception:
        return ""


def read_head(path):
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""


def read_base(base_ref, path):
    return run(["git", "show", f"{base_ref}:{path}"], timeout=10)


def trim_line(line, limit=MAX_LINE_CHARS):
    line = line.replace("\t", "    ")
    if len(line) > limit:
        return line[:limit] + " ..."
    return line


def changed_excerpt(base_ref, path):
    diff = run(["git", "diff", "--unified=2", f"{base_ref}...HEAD", "--", path])
    lines = []
    for line in diff.splitlines():
        if line.startswith(("diff --git", "index ", "--- ", "+++ ")):
            continue
        if line.startswith("@@") or line.startswith("+") or line.startswith("-"):
            lines.append(trim_line(line))
        if len(lines) >= MAX_EXCERPT_LINES_PER_FILE:
            lines.append("... excerpt truncated ...")
            break
    return lines


def focused_diff_excerpt(base_ref, path):
    diff = run(["git", "diff", "--unified=3", f"{base_ref}...HEAD", "--", path])
    lines = []
    pending_hunk = None
    keep_next_context = 0
    for line in diff.splitlines():
        if line.startswith(("diff --git", "index ", "--- ", "+++ ")):
            continue
        is_change = line.startswith(("+", "-")) and not line.startswith(("+++", "---"))
        is_hunk = line.startswith("@@")
        if is_hunk:
            pending_hunk = trim_line(line)
            keep_next_context = 0
            continue
        hit = bool(FOCUS_RE.search(line))
        if is_change and hit:
            if pending_hunk:
                if not lines or lines[-1] != pending_hunk:
                    lines.append(pending_hunk)
                pending_hunk = None
            lines.append(trim_line(line))
            keep_next_context = 1
        elif keep_next_context and line.startswith(" ") and FOCUS_RE.search(line):
            lines.append(trim_line(line))
            keep_next_context -= 1
        if len(lines) >= MAX_FOCUSED_LINES_PER_FILE:
            lines.append("... focused excerpt truncated ...")
            break
    return lines


def import_lines(text):
    out = []
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("import ") or re.search(r"\bfrom ['\"]", line):
            out.append(line)
    return out


def import_delta(base_ref, path):
    base_imports = import_lines(read_base(base_ref, path))
    head_imports = import_lines(read_head(path))
    base_set = set(base_imports)
    head_set = set(head_imports)
    added = [line for line in head_imports if line not in base_set]
    removed = [line for line in base_imports if line not in head_set]
    return {"added": added[:20], "removed": removed[:20]}


def extract_symbols_from_text(text):
    patterns = [
        r"\bexport\s+(?:async\s+)?function\s+([A-Za-z_$][\w$]*)",
        r"\bexport\s+const\s+([A-Za-z_$][\w$]*)",
        r"\bexport\s+let\s+([A-Za-z_$][\w$]*)",
        r"\bexport\s+class\s+([A-Za-z_$][\w$]*)",
        r"\bconst\s+([A-Za-z_$][\w$]*(?:Query|Options|Config|Mutation|Request|Response))\s*=",
        r"\bfunction\s+(use[A-Z][A-Za-z0-9_$]*)\s*\(",
        r"\bconst\s+(use[A-Z][A-Za-z0-9_$]*)\s*=",
    ]
    ignored = {"queryFn", "select", "enabled", "options", "params", "response", "data"}
    symbols = []
    for pattern in patterns:
        for match in re.finditer(pattern, text):
            symbol = match.group(1)
            if symbol not in ignored and symbol not in symbols:
                symbols.append(symbol)
    return symbols


def extract_symbols(path):
    text = read_head(path)
    return extract_symbols_from_text(text)[:MAX_SYMBOLS_PER_FILE]


CALLER_CACHE = {}


def caller_hits(symbols, selected_paths):
    selected = set(selected_paths)
    wanted = []
    for symbol in symbols[:MAX_SYMBOLS_PER_PACKET]:
        if symbol not in wanted:
            wanted.append(symbol)
    missing = [symbol for symbol in wanted if symbol not in CALLER_CACHE]
    for symbol in missing:
        CALLER_CACHE[symbol] = []
    if missing:
        roots = caller_roots(selected_paths)
        patterns = {symbol: re.compile(r"\b" + re.escape(symbol) + r"\b") for symbol in missing}
        for root in roots:
            for dirpath, dirnames, filenames in os.walk(root):
                dirnames[:] = [d for d in dirnames if d not in {"node_modules", ".git", "dist", "build", ".next"}]
                for filename in filenames:
                    if not filename.endswith((".ts", ".tsx")):
                        continue
                    path = os.path.join(dirpath, filename)
                    try:
                        with open(path, encoding="utf-8", errors="replace") as fh:
                            for lineno, line in enumerate(fh, start=1):
                                if not any(symbol in line for symbol in missing):
                                    continue
                                text = line.strip()
                                for symbol, pattern in patterns.items():
                                    if len(CALLER_CACHE[symbol]) >= MAX_CALLERS_PER_SYMBOL * 3:
                                        continue
                                    if pattern.search(line):
                                        CALLER_CACHE[symbol].append({"file": path, "line": lineno, "text": trim_line(text, 130)})
                    except Exception:
                        continue
    result = {}
    for symbol in wanted:
        hits = []
        for hit in CALLER_CACHE.get(symbol, []):
            path = hit.get("file", "")
            if path in selected:
                continue
            hits.append(hit)
            if len(hits) >= MAX_CALLERS_PER_SYMBOL:
                break
        if hits:
            result[symbol] = hits
    return result


CALLSITE_FACT_CACHE = {}
MAX_CALLSITE_FACTS_PER_SYMBOL = 12


def line_number_at(text, index):
    return text.count("\n", 0, index) + 1


def extract_call_text(text, open_paren_index, max_chars=1200):
    depth = 0
    quote = None
    escape = False
    end = min(len(text), open_paren_index + max_chars)
    for i in range(open_paren_index, end):
        ch = text[i]
        if quote:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == quote:
                quote = None
            continue
        if ch in {"'", '"', "`"}:
            quote = ch
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return text[open_paren_index : i + 1]
    return text[open_paren_index:end]


def split_top_level_args(call_text):
    inner = call_text[1:-1] if call_text.startswith("(") and call_text.endswith(")") else call_text
    args = []
    start = 0
    depth = 0
    quote = None
    escape = False
    for i, ch in enumerate(inner):
        if quote:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == quote:
                quote = None
            continue
        if ch in {"'", '"', "`"}:
            quote = ch
        elif ch in "([{":
            depth += 1
        elif ch in ")}]" and depth:
            depth -= 1
        elif ch == "," and depth == 0:
            args.append(inner[start:i].strip())
            start = i + 1
    tail = inner[start:].strip()
    if tail:
        args.append(tail)
    return args


def classify_arg(arg):
    compact = re.sub(r"\s+", " ", (arg or "").strip())
    if not compact:
        return "absent"
    if compact in {"true", "false"}:
        return "boolean_literal"
    if compact.startswith("{"):
        return "object_literal"
    if compact.startswith("["):
        return "array_literal"
    if re.match(r"^[A-Za-z_$][\w$]*$", compact):
        return "identifier"
    if "=>" in compact or compact.startswith("function"):
        return "function"
    return "expression"


def callsite_facts(symbols, selected_paths):
    wanted = []
    for symbol in symbols[:MAX_SYMBOLS_PER_PACKET]:
        if symbol not in wanted:
            wanted.append(symbol)
    missing = [symbol for symbol in wanted if symbol not in CALLSITE_FACT_CACHE]
    for symbol in missing:
        CALLSITE_FACT_CACHE[symbol] = {"complete": True, "call_count": 0, "callers": []}
    if missing:
        roots = caller_roots(selected_paths)
        patterns = {symbol: re.compile(r"(?<![A-Za-z0-9_$])" + re.escape(symbol) + r"(?![A-Za-z0-9_$])\s*\(") for symbol in missing}
        for root in roots:
            for dirpath, dirnames, filenames in os.walk(root):
                dirnames[:] = [d for d in dirnames if d not in {"node_modules", ".git", "dist", "build", ".next"}]
                for filename in filenames:
                    if not filename.endswith((".ts", ".tsx")):
                        continue
                    path = os.path.join(dirpath, filename)
                    try:
                        text = Path(path).read_text(encoding="utf-8", errors="replace")
                    except Exception:
                        for symbol in missing:
                            CALLSITE_FACT_CACHE[symbol]["complete"] = False
                        continue
                    for symbol, pattern in patterns.items():
                        facts = CALLSITE_FACT_CACHE[symbol]
                        for match in pattern.finditer(text):
                            # Ignore declarations like "const foo = (" and "function foo(" by checking nearby prefix.
                            prefix = text[max(0, match.start() - 40):match.start()]
                            if re.search(r"(function\s+|const\s+|let\s+|var\s+|export\s+const\s+)$", prefix):
                                continue
                            call_text = extract_call_text(text, match.end() - 1)
                            args = split_top_level_args(call_text)
                            second_kind = classify_arg(args[1] if len(args) > 1 else "")
                            facts["call_count"] += 1
                            if len(facts["callers"]) < MAX_CALLSITE_FACTS_PER_SYMBOL:
                                snippet = trim_line(re.sub(r"\s+", " ", f"{symbol}{call_text}"), 180)
                                facts["callers"].append({
                                    "file": path,
                                    "line": line_number_at(text, match.start()),
                                    "arg_count": len(args),
                                    "second_arg_kind": second_kind,
                                    "snippet": snippet,
                                })
    return {symbol: CALLSITE_FACT_CACHE[symbol] for symbol in wanted if CALLSITE_FACT_CACHE.get(symbol, {}).get("call_count")}

def compact_hunks(hunks):
    compact = []
    for h in hunks[:8]:
        if not isinstance(h, dict):
            continue
        item = {}
        for key in ["old_start", "old_lines", "new_start", "new_lines", "header"]:
            if key in h:
                item[key] = h[key]
        if not item and "new_range" in h:
            item["new_range"] = h.get("new_range")
        if item:
            compact.append(item)
    return compact

def relevance(file_obj, lens_name):
    cfg = LENS[lens_name]
    path = file_obj.get("path", "")
    tags = set(file_obj.get("tags") or [])
    signals = set(file_obj.get("signals") or [])
    score = 0
    reasons = []
    if re.search(cfg["path_re"], path):
        score += 1
        reasons.append("path")
    hit_tags = sorted(tags & cfg["tags"])
    if hit_tags:
        score += 2
        reasons.append("tags:" + ",".join(hit_tags))
    hit_signals = sorted(signals & cfg["signals"])
    if hit_signals:
        score += 3
        reasons.append("signals:" + ",".join(hit_signals))
    if len(Path(path).parts) > 2 and Path(path).parts[0] in {"packages", "libs", "modules"}:
        score += 4
        reasons.append("package_boundary")
    if "/shared/" in path or "/components/" in path:
        score += 3
        reasons.append("shared_or_component_path")
    if lens_name == "typescript" and path.endswith((".ts", ".tsx")):
        score += 2
    if lens_name == "playbooks" and (tags or signals):
        score += 1
    return score, reasons


def main():
    artifacts = Path(os.environ["ARTIFACTS_DIR"])
    review = artifacts / "review"
    surface = load_surface(review)
    classification = load_json(review / "classification.json")
    routing = load_json(review / "routing-normalized.json")
    base_ref = surface.get("target", {}).get("base_ref") or "origin/master"
    files = surface.get("files") or []
    summary = surface.get("summary") or {}
    risk_markers = surface.get("risk_markers") or {}
    packet_dir = review / "reviewer-inputs"
    packet_dir.mkdir(parents=True, exist_ok=True)
    packet_summary = {"schema_version": 1, "packets": {}}

    for lens_name in REVIEWERS:
        routed = routing.get(lens_name) == "yes"
        ranked = []
        if routed:
            for f in files:
                score, reasons = relevance(f, lens_name)
                if score > 0:
                    ranked.append((score, reasons, f))
        ranked.sort(key=lambda item: (-item[0], item[2].get("path", "")))
        selected = ranked[:MAX_FILES_PER_PACKET]
        selected_paths = [f.get("path") for _, _, f in selected if f.get("path")]
        packet_files = []
        all_symbols = []
        for index, (score, reasons, f) in enumerate(selected):
            path = f.get("path")
            tags = f.get("tags") or []
            signals = normalize_signals(f.get("signals") or [])
            symbols = extract_symbols(path) if path else []
            for symbol in symbols:
                if symbol not in all_symbols:
                    all_symbols.append(symbol)
            item = {
                "path": path,
                "status": f.get("status"),
                "additions": f.get("additions"),
                "deletions": f.get("deletions"),
                "tags": tags,
                "signals": signals,
                "hunk_refs": compact_hunks(f.get("hunks") or []),
                "symbols": symbols,
                "relevance": {"score": score, "reasons": reasons},
                "focused_diff_excerpt": focused_diff_excerpt(base_ref, path) if path else [],
                "import_delta": import_delta(base_ref, path) if path else {"added": [], "removed": []},
            }
            packet_files.append(item)

        if lens_name == "playbooks":
            precomputed_context = {}
        elif lens_name == "typescript":
            precomputed_context = {
                "callsite_facts": callsite_facts(all_symbols, selected_paths),
            }
        else:
            precomputed_context = {
                "symbol_callers": caller_hits(all_symbols, selected_paths),
            }
        cfg = LENS[lens_name]
        packet = {
            "schema_version": 2,
            "reviewer": lens_name,
            "target": surface.get("target", {}),
            "classification": {
                "complexity": classification.get("complexity"),
                "diff_type": classification.get("diff_type"),
                "full_review": classification.get("full_review"),
                "rationale": classification.get("rationale", {}),
            },
            "routing": {"enabled": routing.get(lens_name), "full_review": routing.get("full_review")},
            "summary": summary,
            "risk_markers": risk_markers,
            "contract_docs": cfg["contract_docs"],
            "checklist": cfg["checklist"],
            "precomputed_context": precomputed_context,
            "rules": [
                "This packet is the primary input; do not read surface.json.",
                "Use focused_diff_excerpt and import_delta before reading any source file.",
                "For playbooks, use docs/playbooks/index.md and only specifically applicable docs/playbooks/*.md; do not use generic reviewer heuristics as playbooks.",
                "Do not use Bash/Grep/Glob/find/ls/git/package discovery in this reviewer node; reviewer context is precomputed here.",
                "You may use Read only for files named in this packet or listed contract docs when the packet is contradictory or missing a critical detail.",
                "Create candidate observations, not final ownership or proof verdicts.",
                "If a concern is pre-existing or outside MR boundary, put it in incidental_observations.",
            ],
            "files": packet_files,
        }
        out = packet_dir / f"reviewer-input-{lens_name}.json"
        out.write_text(json.dumps(packet, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
        packet_summary["packets"][lens_name] = {
            "artifact": f"reviewer-inputs/{out.name}",
            "files": len(packet_files),
            "bytes": out.stat().st_size,
            "routed": routing.get(lens_name),
            "schema_version": 2,
            "symbols": len(all_symbols[:MAX_SYMBOLS_PER_PACKET]),
            "caller_symbol_hits": len(precomputed_context.get("symbol_callers", {})),
            "callsite_fact_symbols": len(precomputed_context.get("callsite_facts", {})),
        }

    (review / "reviewer-input-summary.json").write_text(json.dumps(packet_summary, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    active = ", ".join(f"{k}:{v['files']}" for k, v in packet_summary["packets"].items() if v.get("routed") == "yes") or "none"
    print(f"Reviewer packets: {active}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
