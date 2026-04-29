---
description: Prove or disprove ownership-passed Adapty review candidates with concrete checks.
argument-hint: (reads ownership-passed candidates)
---

# Prove Findings

Workflow: `$WORKFLOW_ID`
Artifacts: `$ARTIFACTS_DIR`

## User-Visible Output Policy

Write complete findings, evidence, logs, and long explanations only to files under `$ARTIFACTS_DIR/review`.
Keep stdout to one short line. Do not narrate progress or paste artifacts into stdout.

## Workflow Context Policy

Do not load or invoke repository skills. This Archon workflow owns the review procedure.
Stay inside the current checkout and the explicit artifact paths listed here.
Never search from `/.archon/workspaces`, `/srv/archon-data/workspaces`, a workspace root, or `worktrees/archon`.

## Load

Read only:

- `$ARTIFACTS_DIR/review/target.env`
- `$ARTIFACTS_DIR/review/ownership-passed-candidates.json`
- `$ARTIFACTS_DIR/review/ownership-gate.json`
- `$ARTIFACTS_DIR/review/ownership-summary.json`
- `$ARTIFACTS_DIR/checks/post-proof-checks.log` only if proof changed files

Do not read `$ARTIFACTS_DIR/review/surface.json`.
Do not read reviewer markdown.
Do not read internal markdown mirrors. If `ownership-passed-candidates.json` is missing, fail closed with zero confirmed findings.

## Mission

Ownership was already gated before this node.
This node proves only whether ownership-passed candidates are real, material bugs or review findings.
Do not re-open ownership-rejected candidates.
Do not confirm a finding whose ownership result is not `introduced`, `worsened`, or `newly_exposed`.

For each ownership-passed candidate:

- Open the exact file and line in head.
- Read the ownership result and reuse its commands/reason in evidence.
- Verify the code path, type path, data path, or UI state path claimed by the candidate.
- For type issues, run the narrowest relevant TypeScript or build command. Use `$ARTIFACTS_DIR/bin/frontend-docker-exec` for pnpm/node commands.
- For testable logic bugs, add or update a focused regression test only when it is practical and materially improves proof. Run it through `$ARTIFACTS_DIR/bin/frontend-docker-exec`.
- If a minimal proof fix is obvious, apply it only after recording the failing test/check, then rerun the same command and record the passing result.
- If evidence does not hold, reject the candidate.
- Do not keep weak claims as findings.

## Output Contract

Write `$ARTIFACTS_DIR/review/validated-findings.json`:

```json
{
  "schema_version": 1,
  "confirmed_findings": [
    {
      "id": "C-1",
      "severity": "P1|P2|P3",
      "title": "short title",
      "file": "relative/path.ts",
      "line": 123,
      "claim_type": "...",
      "ownership": "introduced|worsened|newly_exposed",
      "mr_causality": "short proven causality",
      "problem": "short problem statement",
      "evidence": "short evidence summary",
      "proof_commands": ["exact commands run or inspections performed"],
      "fix_direction": "short",
      "test_direction": "short",
      "fix_status": "not fixed|proof fix applied|needs human fix"
    }
  ]
}
```

Write `$ARTIFACTS_DIR/review/proof-rejected-findings.json` with ownership-passed candidates that failed bug/impact proof.

Do not write markdown mirrors.

Write `$ARTIFACTS_DIR/review/proof-changes.json` with:

```json
{
  "schema_version": 1,
  "files_modified": [],
  "commands_run": [],
  "change_kind": "none|proof_only|viable_fix_material",
  "post_proof_checks_required": false
}
```

Print exactly: `Proof: <n> confirmed, <n> rejected, changed files: <yes|no>.`
