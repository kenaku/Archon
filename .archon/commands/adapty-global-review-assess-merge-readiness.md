---
description: Decide Adapty MR merge readiness and route fast path versus full evidence review.
argument-hint: (reads classification and surface artifacts)
---

# Assess Merge Readiness (Sliced Surface)

Workflow: `$WORKFLOW_ID`
Artifacts: `$ARTIFACTS_DIR`


## User-Visible Output Policy

Write complete findings, evidence, logs, and long explanations only to the required files under `$ARTIFACTS_DIR`.
Keep the final stdout response for this node short because chat adapters may relay it to the user.
Do not narrate progress, tool use, or context gathering. Never write phrases like "I will", "I am checking", "Now let me", or "I have enough context".
The final chat/stdout response must be the only user-visible text from this node. Do all tool use silently; write artifacts before responding.
Do not paste JSON artifacts, markdown artifacts, check logs, changed hunk data, or long evidence blocks into stdout.
Stdout should be at most 3 short lines unless this command explicitly says it is the final user report.

## Workflow Context Policy

Do not load or invoke repository skills during this workflow. In particular, do not read `.agents/skills/adapty-review/*`, `.codex/skills/*`, or any skill `SKILL.md`. This Archon workflow owns the review procedure. Use only the artifacts listed in this command, the changed files, persona files explicitly named by the workflow, and docs explicitly named by this command.

## Workspace Boundary Policy

Stay inside the current checkout and the explicit artifact paths listed in this command.
Never search from `/.archon/workspaces`, `/srv/archon-data/workspaces`, a workspace root, or `worktrees/archon`.
Never read files from another thread worktree. Those files may belong to unrelated workflow runs.
Do not use broad commands such as `find /.archon/workspaces`, `find /srv/archon-data`, or `find ..` to discover review inputs.
If a file is not at an explicit `$ARTIFACTS_DIR/...` path or a relative path in the current checkout, treat it as unavailable and say so briefly.
Prefer exact paths from this command and small scoped searches under `apps/`, `packages/`, `docs/`, or changed files only.

## Load

Read:

- `$ARTIFACTS_DIR/review/surface-summary.json`
- `$ARTIFACTS_DIR/review/surface-files.json`
- `$ARTIFACTS_DIR/review/classification.json`
- `$ARTIFACTS_DIR/review/target.env`

Do not read `$ARTIFACTS_DIR/review/surface.json`; it is a raw audit artifact, not an LLM input for this node.

## Mission

Make the first merge-readiness decision and produce the actual routing booleans for the rest of the workflow.

This node does not perform deep review. It decides whether the MR can use a fast path or needs the full evidence review.

## GitLab State Policy

Use GitLab metadata only as informational context. Do not lower readiness, set `blocked`, or add merge blockers because of GitLab-only state, including:

- branch behind target branch / needs rebase
- unresolved discussions or blocking discussions
- GitLab detailed merge status
- GitLab conflict flags
- draft state
- GitLab CI status

This workflow reviews code evidence only. GitLab process/readiness is handled outside this workflow.

## Fast Path Rules

Set `fast_path: yes` and `full_review: no` only when all are true:

- The MR is `trivial` or `small`.
- The diff is `empty`, `docs_only`, `copy_i18n`, low-risk `tests_only`, or a very localized low-risk `source_small`.
- The surface summary and file slice have no critical code risk markers: auth, permissions, routing gates, SDK/API contracts, public exports, package boundaries, async request ordering, forms, modals, dependency/runtime changes, generated source changes, or broad refactor.
- The classification does not require more than one reviewer lens.
- The MR can be assessed with metadata plus minimal checks.

For fast path:

- Keep reviewer booleans `no`.
- Keep `playbooks: no` unless a playbook is the only needed validation for a safe low-risk category.
- Run only minimal checks that materially increase confidence:
  - `docs_only` and `empty`: normally no checks.
  - `copy_i18n`: normally `run_lint: yes`, no unit/build.
  - `tests_only`: `run_lint: yes`, `run_unit: yes`.
  - localized `source_small`: at least `run_lint: yes`; add `run_unit` or `run_build` only if the changed surface needs it.

## Full Review Rules

Set `fast_path: no` and `full_review: yes` when:

- The MR is `medium` or `large`.
- The diff touches risky areas listed above.
- The classifier selected multiple reviewer lenses.
- A human would reasonably expect proof-backed findings before saying merge is safe.

For full review, start from `classification.json` routing and adjust conservatively.

## Merge Score

Return:

- `readiness_score`: 0-100, where 90+ means ready, 70-89 means ready with notes or needs review, below 70 means blocked or likely needs fixes.
- `confidence`: 0-1, confidence in this preliminary assessment.
- `risk`: `low`, `medium`, or `high`.
- `verdict`:
  - `ready_to_merge`: safe fast path with no known blockers.
  - `ready_with_notes`: likely safe but with minor caveats.
  - `needs_review`: full review required before confidence is enough.
  - `needs_fixes`: clear problem or failing check is already visible.
  - `blocked`: target invalid, missing required local metadata/artifacts, confirmed P0/P1 evidence, or failed required local check mapped to changed code.
  - `needs_human_attention`: cannot classify safely.

## Output

Create `$ARTIFACTS_DIR/review/` if it does not exist.

Write the JSON to:

- `$ARTIFACTS_DIR/review/merge-readiness-preliminary.json`

Do not write a markdown summary.

Write compact JSON only to `$ARTIFACTS_DIR/review/merge-readiness-preliminary.json`. Do not paste JSON in stdout/chat.

The JSON schema is fixed. Use exactly this top-level shape. Do not add a `routing` object. Do not duplicate reviewer or check booleans at the top level.

```json
{
  "verdict": "needs_review",
  "readiness_score": 74,
  "confidence": 0.82,
  "risk": "medium",
  "fast_path": false,
  "full_review": true,
  "checks": {
    "run_lint": true,
    "run_unit": true,
    "run_build": true
  },
  "reviewers": {
    "architecture": false,
    "typescript": true,
    "races": false,
    "security_performance": false,
    "styling": true,
    "simplicity": false,
    "playbooks": true
  },
  "routing_rationale": "Localized TSX and CSS Modules changes need TypeScript and styling review before merge confidence is high enough.",
  "fast_path_blockers": ["medium source change"],
  "preliminary_notes": ["No blockers confirmed before reviewer fanout."]
}
```

Required keys:

- `verdict`, `readiness_score`, `confidence`, `risk`, `fast_path`, `full_review`, `checks`, `reviewers`, `routing_rationale`, `fast_path_blockers`, `preliminary_notes`
- every `checks` key shown above
- every `reviewers` key shown above

Use JSON booleans for `fast_path`, `full_review`, every check, and every reviewer.

Print only one human line: `First assessment: <verdict>, score <n>, risk <risk>, path: <fast path|full review>.`
