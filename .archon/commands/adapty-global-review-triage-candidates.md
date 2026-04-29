---
description: Normalize JSON reviewer candidate observations into compact candidate JSON for ownership proof.
argument-hint: (reads reviewer JSON artifacts)
---

# Triage Candidate Findings JSON

Workflow: `$WORKFLOW_ID`
Artifacts: `$ARTIFACTS_DIR`

## User-Visible Output Policy

Write complete findings, evidence, logs, and long explanations only to files under `$ARTIFACTS_DIR/review`.
Keep stdout short. Do not narrate progress or paste artifact contents into stdout.
Print exactly one compact line at the end.

## Workflow Context Policy

Do not load or invoke repository skills. Stay inside the current checkout and explicit artifact paths.
Never search from `/.archon/workspaces`, `/srv/archon-data/workspaces`, a workspace root, or `worktrees/archon`.

## Load

Read only:

- `$ARTIFACTS_DIR/review/routing-normalized.json`
- `$ARTIFACTS_DIR/review/merge-readiness-preliminary.json`
- `$ARTIFACTS_DIR/review/reviewer-input-summary.json`
- all files matching `$ARTIFACTS_DIR/review/reviewer-summary-*.json`
- only reviewer JSON artifacts named by those summary JSON files

Do not read `surface.json`.
Do not read reviewer markdown. This workflow expects reviewer JSON artifacts.
Do not read proof, final, GitLab, or previous-run artifacts.

## Mission

This node is a normalizer and dedupe stage, not proof.
It merges reviewer JSON candidate observations into the existing compact `candidates.json` contract for ownership gate.
It must not confirm MR ownership and must not produce final findings.

## Triage Rules

- Merge duplicate observations by root cause.
- Drop pure taste, vague speculation, and observations with no concrete file path.
- Keep only observations that could plausibly be MR-owned or need explicit ownership proof.
- If reviewer JSON marks an item as pre-existing/incidental, keep it only in `incidental_observations`.
- If reviewer artifacts conflict about ownership, create a candidate with `ownership_status: "disputed"`.
- Otherwise set `ownership_status: "unchecked"`.
- Every candidate must include a narrow `ownership_check` telling the next stage exactly what to compare in base vs head.
- Keep text compact. Prefer symbols, paths, and short claims over prose.

## Candidate JSON Contract

Write `$ARTIFACTS_DIR/review/candidates.json` as:

```json
{
  "schema_version": 1,
  "candidates": [
    {
      "id": "C-1",
      "severity_hypothesis": "P1|P2|P3",
      "title": "short title",
      "file": "relative/path.ts",
      "line": 123,
      "claim_type": "query_key_scope|export_collision|nullability|race|effect_dependency|api_contract|ui_state|type_safety|other",
      "symbol": "optional exact function/hook/key/prop name",
      "claim": "one sentence",
      "causality_hypothesis": "one sentence, not proven",
      "ownership_status": "unchecked|disputed",
      "ownership_check": {
        "base_head_focus": "what exact behavior/key/export/dependency/side effect to compare",
        "suggested_commands": ["git diff $BASE_REF...HEAD -- relative/path.ts", "git show $BASE_REF:relative/path.ts"]
      },
      "proof_plan": "one sentence for proving bug/impact after ownership passes",
      "likely_check_command": "optional narrow command",
      "source_reviewers": ["typescript"]
    }
  ],
  "incidental_observations": [
    {"title":"short", "file":"relative/path.ts", "reason":"pre-existing or outside MR boundary", "source_reviewers":["..."]}
  ]
}
```

Use an empty `candidates` array when nothing survives.
Do not include reviewer prose, long code snippets, or markdown tables inside JSON fields.

Do not write markdown mirrors or reviewer summary markdown.
Write `$ARTIFACTS_DIR/review/candidate-summary.json` with `kept_candidates`, `incidental_observations`, `needs_ownership_gate`, `needs_proof`, and `reason`.
Set `needs_ownership_gate` and `needs_proof` to `yes` only when `kept_candidates > 0`.

Print exactly: `Triage: <n> candidates, <n> incidental observations, ownership gate: <yes|no>.`


Additional rules:

- `reviewer-findings-detectors.json` is a deterministic candidate source. Treat `source_reviewers:["detectors"]` as normal reviewer evidence, then still dedupe and ownership-gate it.
- Drop compatibility-only or tech-debt-only claims unless they identify a concrete behavior, package-boundary, type-safety, or public API contract risk.
- Do not keep compatibility-only or deprecation-only claims unless the candidate identifies concrete behavior loss, contract violation, type-safety risk, or package-boundary risk beyond intended compatibility syntax.
- Prefer fewer high-signal candidates over broad coverage. If two candidates are same root cause, merge them.
