#!/usr/bin/env python3
import json
import os
from pathlib import Path

REVIEWERS = ["architecture", "typescript", "races", "security_performance", "styling", "simplicity", "playbooks"]


def load(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def yn(v):
    return "yes" if v in (True, "yes", "true", "1", 1) else "no"


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


def main():
    review = Path(os.environ["ARTIFACTS_DIR"]) / "review"
    routing = load(review / "routing-normalized.json")
    surface = load_surface(review)
    classification = load(review / "classification.json")
    files = surface.get("files") or []
    risks = surface.get("risk_markers") or {}
    diff_type = classification.get("diff_type")

    out = dict(routing)
    decisions = []
    if routing.get("full_review") != "yes":
        out["budget_applied"] = "no"
    else:
        ts_files = [f for f in files if str(f.get("path", "")).endswith((".ts", ".tsx"))]
        style_files = [f for f in files if str(f.get("path", "")).endswith((".css", ".scss", ".sass", ".less"))]
        paths = [f.get("path", "") for f in files]
        signals = {s for f in files for s in (f.get("signals") or [])}
        tags = {t for f in files for t in (f.get("tags") or [])}
        wanted = {r: "no" for r in REVIEWERS}
        if routing.get("playbooks") == "yes" and (diff_type in {"api_sdk", "shared_ui", "forms_modals", "routing_auth_permissions", "deps_config"} or tags or signals):
            wanted["playbooks"] = "yes"
            decisions.append("playbooks=yes: matched diff type/tags/signals")
        if routing.get("typescript") == "yes" and ts_files and (signals or risks.get("api_sdk") or risks.get("query_cache")):
            wanted["typescript"] = "yes"
            decisions.append("typescript=yes: TS files with data/API/signature signals")
        if routing.get("architecture") == "yes" and ("public_api" in tags or "shared_ui" in tags or any(p.startswith("packages/") or "/shared/" in p or "/components/" in p for p in paths)):
            wanted["architecture"] = "yes"
            decisions.append("architecture=yes: public/shared/package boundary surface")
        if routing.get("styling") == "yes" and style_files:
            wanted["styling"] = "yes"
            decisions.append("styling=yes: style files changed")
        if routing.get("races") == "yes" and ({"forms", "modals", "async_effects"} & tags or {"refetch_changed"} & signals):
            wanted["races"] = "yes"
            decisions.append("races=yes: lifecycle/async signals")
        if routing.get("security_performance") == "yes" and (risks.get("deps_config") or "auth_permissions" in tags):
            wanted["security_performance"] = "yes"
            decisions.append("security_performance=yes: deps/auth risk")
        if routing.get("simplicity") == "yes" and ("exports_changed" in signals or "options_signature_changed" in signals):
            wanted["simplicity"] = "yes"
            decisions.append("simplicity=yes: abstraction/signature change")

        # Never allow full_review=yes with zero reviewers.
        if not any(v == "yes" for v in wanted.values()):
            for fallback in ["playbooks", "typescript"]:
                if routing.get(fallback) == "yes":
                    wanted[fallback] = "yes"
                    decisions.append(f"{fallback}=yes: fallback reviewer budget")
                    break
        for key, value in wanted.items():
            out[key] = value
        out["budget_applied"] = "yes"

    budget = {
        "schema_version": 1,
        "original": {k: routing.get(k) for k in ["full_review", *REVIEWERS]},
        "budgeted": {k: out.get(k) for k in ["full_review", *REVIEWERS]},
        "decisions": decisions,
    }
    (review / "reviewer-budget.json").write_text(json.dumps(budget, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (review / "routing-normalized.json").write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, separators=(",",":")))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
