---
description: Prove MR ownership for compact candidate findings with base-vs-head checks.
argument-hint: (reads candidates.json and target.env)
---

# Ownership Gate

Workflow: `$WORKFLOW_ID`
Artifacts: `$ARTIFACTS_DIR`

## User-Visible Output Policy

Write detailed evidence only to files under `$ARTIFACTS_DIR/review`.
Keep stdout to one short line. Do not narrate progress.

## Workflow Context Policy

Do not load repository skills. Stay inside the current checkout and `$ARTIFACTS_DIR`.
Never search from `/.archon/workspaces`, `/srv/archon-data/workspaces`, a workspace root, or `worktrees/archon`.
Do not read reviewer markdown, `surface.json`, final report artifacts, GitLab artifacts, or broad artifact directories.

## Load

Read only:

- `$ARTIFACTS_DIR/review/target.env`
- `$ARTIFACTS_DIR/review/candidates.json`
- `$ARTIFACTS_DIR/review/ownership-precheck.json` after you generate it

The current worktree is already checked out at MR head.
Use `BASE_REF` from `target.env`. Use `HEAD_REF` from `target.env` or `HEAD`.

## Mission

This node answers two cheap gate questions per candidate:

1. Is the claimed problem owned by this MR?
2. Is the candidate's causal premise contradicted or preserved by narrow base-vs-head/static facts already named by the candidate?

It does not prove severity, impact, or fix direction. It may reject candidates whose own ownership check shows the claim does not match head code or behavior was preserved.

## Deterministic Precheck

Before reasoning, run exactly:

```bash
ARTIFACTS_DIR="$ARTIFACTS_DIR" .archon/scripts/adapty-ownership-precheck.py
```

Then read `$ARTIFACTS_DIR/review/ownership-precheck.json`.
Use it as the primary source for deterministic hard facts: diff presence, compact base/head observations, hard-reject evidence, and unresolved candidates.
Do not repeat broad repository searches. For candidates with `deterministic_verdict: "hard_reject"`, classify as `not_reproduced` or `pre_existing` unless the candidate text contains a specific contradiction to the hard fact. For candidates with `ownership_hint: "no_mr_evidence"`, classify as `pre_existing` or `unknown`.
Only run extra narrow commands from the candidate's own `ownership_check.suggested_commands`, or equivalent narrow `git diff` / `git show`, for `deterministic_verdict: "needs_llm"` candidates or to resolve a direct contradiction in a hard-reject fact.

Precheck fields:

- `deterministic_verdict: "hard_reject"`: deterministic static facts contradict the candidate's causal premise or show no MR evidence; normally reject before proof.
- `deterministic_verdict: "needs_llm"`: deterministic facts are insufficient; do the narrow semantic ownership check.
- `hard_rejects[]`: concrete evidence kinds and short supporting hits/snippets. Cite these in `reason`, `base_observation`, or `head_observation`.
- `facts[]`: compact non-verdict facts that may help resolve the candidate without broad searches.
- `ownership_hint`: `hard_reject`, `no_mr_evidence`, or `needs_llm`. Pass-like hints must not be used as final verdicts.

## Required Check

For every candidate, start from the matching `ownership-precheck.json.results[]` entry.
Precheck can be decisive for `hard_reject` or `no_mr_evidence` when the hard fact answers the candidate's causal premise.
Use precheck hard-reject facts directly when they answer the candidate's causal premise. For unresolved candidates, run or inspect only the narrowest base-vs-head/static comparison needed by `ownership_check`:

- `git diff "$BASE_REF"...HEAD -- <file>` for changed hunks;
- `git show "$BASE_REF:<file>"` compared to the current file for semantic behavior;
- `git blame "$BASE_REF" -- <file>` only when needed.

Import and dependency ownership rule:
- For candidates about a package/runtime import boundary, classify ownership from changed file-level imports, changed runtime usage, changed call sites, or changed public contracts.
- If base used one runtime API/module and head uses a different API/module in the candidate file, the import-boundary behavior may be `introduced` or `worsened` even when a manifest already listed the dependency.
- Package manifests can support impact assessment, but manifest presence alone cannot prove the candidate is pre-existing.

Classify ownership as exactly one of:

- `introduced`: the issue was absent in base and added by this MR;
- `worsened`: base had a related issue, but this MR made impact/scope worse;
- `newly_exposed`: base had latent behavior, but this MR added usage that exposes it;
- `pre_existing`: same relevant behavior already existed in base;
- `not_reproduced`: the candidate claim does not match head code;
- `unknown`: ownership cannot be determined from the available comparison.

Only `introduced`, `worsened`, and `newly_exposed` may proceed to proof.
Candidates whose changed code is MR-owned but whose causal premise is contradicted by deterministic hard facts must be classified as `not_reproduced`, not passed to proof.
`unknown` must not proceed to proof as a confirmed-review candidate; put it in rejected output with missing evidence.

## Output Contract

Write `$ARTIFACTS_DIR/review/ownership-gate.json`:

```json
{
  "schema_version": 1,
  "base_ref": "sha-or-ref",
  "head_ref": "sha-or-ref",
  "results": [
    {
      "candidate_id": "C-1",
      "ownership": "introduced|worsened|newly_exposed|pre_existing|not_reproduced|unknown",
      "file": "relative/path.ts",
      "line": 123,
      "symbol": "optional",
      "reason": "short reason",
      "precheck_hint": "hard_reject|no_mr_evidence|needs_llm",
      "deterministic_verdict": "hard_reject|needs_llm",
      "commands": ["exact command(s) or precheck artifact used"],
      "base_observation": "short, no long code quote",
      "head_observation": "short, no long code quote"
    }
  ]
}
```

Write `$ARTIFACTS_DIR/review/ownership-passed-candidates.json` with the same candidate objects from `candidates.json`, enriched with their ownership result, only for `introduced`, `worsened`, or `newly_exposed`.

Write `$ARTIFACTS_DIR/review/ownership-rejected-candidates.json` with candidates classified as `pre_existing`, `not_reproduced`, or `unknown`.

For summary counts, `rejected` excludes `unknown`. `rejected + unknown + passed` must equal `input_candidates`.

Write `$ARTIFACTS_DIR/review/ownership-summary.json`:

```json
{
  "input_candidates": 0,
  "passed": 0,
  "rejected": 0,
  "unknown": 0,
  "needs_proof": "no"
}
```

Set `needs_proof` to `yes` only when `passed > 0`.

Do not write a markdown mirror.

Print exactly: `Ownership gate: <passed> passed, <rejected> rejected, <unknown> unknown, proof: <yes|no>.`
