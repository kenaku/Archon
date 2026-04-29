---
description: Produce final Adapty MR merge-readiness assessment after ownership gate and proof.
argument-hint: (reads compact review artifacts)
---

# Final Merge Assessment

Workflow: `$WORKFLOW_ID`
Artifacts: `$ARTIFACTS_DIR`

## User-Visible Output Policy

Write full assessment only to files under `$ARTIFACTS_DIR/review`.
Keep stdout to one short line. Do not narrate progress or paste JSON/logs into stdout.

## Workflow Context Policy

Do not load repository skills. Stay inside the current checkout and explicit artifact paths.
Never search from `/.archon/workspaces`, `/srv/archon-data/workspaces`, a workspace root, or `worktrees/archon`.

## Load

Read only:

- `$ARTIFACTS_DIR/review/target.env`
- `$ARTIFACTS_DIR/review/classification.json`
- `$ARTIFACTS_DIR/review/routing-normalized.json`
- `$ARTIFACTS_DIR/review/reviewer-budget.json` if present
- `$ARTIFACTS_DIR/review/reviewer-summary-architecture.json` if present
- `$ARTIFACTS_DIR/review/reviewer-summary-typescript.json` if present
- `$ARTIFACTS_DIR/review/reviewer-summary-races.json` if present
- `$ARTIFACTS_DIR/review/reviewer-summary-security-performance.json` if present
- `$ARTIFACTS_DIR/review/reviewer-summary-styling.json` if present
- `$ARTIFACTS_DIR/review/reviewer-summary-simplicity.json` if present
- `$ARTIFACTS_DIR/review/reviewer-summary-playbooks.json` if present
- `$ARTIFACTS_DIR/review/merge-readiness-preliminary.json`
- `$ARTIFACTS_DIR/review/fanout-failure.json` if present
- `$ARTIFACTS_DIR/review/candidate-summary.json` if present
- `$ARTIFACTS_DIR/review/ownership-summary.json` if present
- `$ARTIFACTS_DIR/review/ownership-gate.json` if present
- `$ARTIFACTS_DIR/review/validated-findings.json` if present
- `$ARTIFACTS_DIR/review/proof-rejected-findings.json` if present
- `$ARTIFACTS_DIR/review/proof-changes.json` if present
- `$ARTIFACTS_DIR/checks/post-proof-checks.log` only if proof changed files

Do not read `$ARTIFACTS_DIR/review/surface.json`.
Do not read reviewer markdown or internal markdown mirrors for verdict computation.

## Mission

Create the final merge-readiness view for the MR.
Only `validated-findings.json.confirmed_findings` may produce code blockers. Workflow contract failures must produce `needs_human_attention` or `blocked`, never `ready_*`.
Ownership-rejected, proof-rejected, incidental, or unknown candidates must not become blockers.

Fail-closed rules:

- If `fanout-failure.json` exists, verdict must be `needs_human_attention` or `blocked`, score below 60, and no ready recommendation.
- If full review was routed but `candidate-summary.json` is missing, verdict must be `needs_human_attention` or `blocked`.
- If `ownership-summary.json.status == "invalid_upstream"`, verdict must be `needs_human_attention` or `blocked`.
- Do not reinterpret missing candidates after an upstream failure as zero findings.

This node must work for:

- fast path: no fan-out reviewers or proof;
- full path with zero candidates after triage;
- full path with candidates but zero ownership-passed candidates;
- full path with ownership-passed candidates and proof.

## GitLab State Policy

Ignore GitLab-only state when computing verdict, score, blockers, and recommendation: branch behind, unresolved discussions, detailed merge status, conflicts, draft state, and CI status.
Mention such state only in an informational section if useful.

## Scoring

Start from the preliminary score, then adjust only for validated findings and proof/check results:

- Confirmed P0/P1 finding: verdict `blocked` or `needs_fixes`, score below 60.
- Confirmed P2 finding: verdict `needs_fixes` unless fixed and checks passed.
- Post-proof `pnpm check:changed` failure after proof edits: verdict `blocked`.
- No confirmed findings and required checks passed: `ready_to_merge` or `ready_with_notes`.
- `candidate-summary.needs_ownership_gate == "no"` means ownership/proof artifacts may be absent.
- `ownership-summary.needs_proof == "no"` means proof artifacts may be absent because no candidate passed ownership.

Use confidence honestly: 0.90-1.00 strong, 0.75-0.89 likely, below 0.75 needs human attention.

## Output

In `merge-readiness-final.json`, `reviewers_run` must reflect reviewers that actually completed. Prefer reviewer-summary files with `status: completed`. If summaries are unavailable, use `reviewer-budget.json.budgeted` entries whose value is exactly `yes`. Do not use the preliminary `reviewers` object or unbudgeted routing fields for `reviewers_run`.

Write `$ARTIFACTS_DIR/review/merge-readiness-final.json` as compact JSON.
It must include at least: `verdict`, `readiness_score`, `confidence`, `path`, `confirmed_findings`, `merge_blockers`, `ownership_gate`, `proof`, and `residual_risks`.

Do not write a markdown mirror here. The only human-readable final report is `final-report.md`, produced by the next node from this JSON.

Print exactly: `Final assessment: <verdict>, score <n>, blockers: <none|n>.`
