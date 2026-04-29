---
description: Classify an Adapty MR review surface and choose conditional checks and reviewer nodes.
argument-hint: (reads surface artifacts)
---

# Classify Review (Sliced Surface)

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
- workflow-owned routing rules in this command

Do not read `$ARTIFACTS_DIR/review/surface.json`; it is a raw audit artifact, not an LLM input for this node.

## Mission

Classify the MR and select the smallest useful set of checks and reviewer nodes.

This is a routing node. Do not review code deeply here.
Use `surface-summary.json` for target, counts, risk markers, and categories. Use `surface-files.json` for changed-file paths, statuses, tags, signals, and hunk counts. Do not inspect full hunks here.

## Complexity

- `trivial`: empty diff, typo/copy-only, formatting-only, one-line non-code change.
- `small`: 1-3 files, simple localized change, no cross-slice or async behavior.
- `medium`: 4-10 files, meaningful logic/UI changes, tests or docs may need review.
- `large`: 10+ files, architectural changes, new subsystem, public API, SDK/API/auth/query/form/modal/routing changes, or broad refactor.

## Diff Type

Pick one:

- `empty`
- `docs_only`
- `config_only`
- `tests_only`
- `style_only`
- `types_only`
- `source_small`
- `source_mixed`
- `api_sdk`
- `forms_modals`
- `routing_auth_permissions`
- `shared_ui`
- `deps_config`
- `generated`
- `copy_i18n`

## Check Routing

- `run_lint: yes` for source, tests, style, config, deps, or shared UI changes.
- `run_unit: yes` when source logic, hooks, components, tests, forms, modals, routing, SDK/API, auth, permissions, or query/cache behavior changed.
- `run_build: yes` when source, public API, package boundary, deps/config, SDK/API, routing/auth, shared UI, or build-affecting files changed.
- For `docs_only`, normally all checks are `no`.
- For `style_only`, normally `run_lint: yes`, `run_unit: no`, `run_build: yes` only if shared components/layout/build imports changed.
- For `tests_only`, normally `run_lint: yes`, `run_unit: yes`, `run_build: no`.

## Reviewer Routing

- `architecture: yes` for FSD layers, slice ownership, public exports, barrels, deep imports, shared components/hooks, duplicated business ownership, or package boundary changes.
- `typescript: yes` for TS/TSX source changes, props/hooks/API shapes, unsafe casts, constants, tests that assert typed contracts, or any build/type risk.
- `races: yes` for async effects, request ordering, stale closures, forms, modals, toasts, navigation, optimistic/cache flows.
- `security_performance: yes` for auth, permissions, routing gates, storage, analytics, SDK calls, data fetching, render hot paths, dependency/runtime cost.
- `styling: yes` for CSS Modules, tokens, variants, responsive states, dark theme, style composition, or shared UI layout.
- `simplicity: yes` for duplicated orchestration, weak abstractions, over-configured APIs, unclear helper extraction, or needless complexity.
- `playbooks: yes` whenever the diff matches any known playbook type: style-only, tests-only, types-only, API/SDK, forms/modals, routing/auth/permissions/feature flags, shared UI/public API, deps/config, generated files, copy/i18n.

Skip all reviewer nodes for `empty`, `docs_only`, and low-risk `config_only` unless the diff changes workflow/review rules that need architecture or docs-aware review.

For tiny source changes, choose 1-2 reviewers max.
For medium changes, choose 2-4 reviewers.
For large/high-risk changes, choose all relevant reviewers.

## Output

Write compact JSON only to `$ARTIFACTS_DIR/review/classification.json`. Do not paste JSON in stdout/chat.

The JSON schema is fixed. Use exactly this top-level shape. Do not add a `routing` object. Do not duplicate reviewer or check booleans at the top level.

```json
{
  "complexity": "medium",
  "diff_type": "source_mixed",
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
  "rationale": {
    "complexity": "4 TSX/CSS files with user-visible UI behavior.",
    "diff_type": "source and CSS module changes.",
    "checks": "Lint and build cover changed source/style contracts.",
    "reviewers": "TypeScript and styling are the relevant lenses."
  }
}
```

Required keys:

- `complexity`, `diff_type`, `full_review`, `checks`, `reviewers`, `rationale`
- every `checks` key shown above
- every `reviewers` key shown above

Use JSON booleans for `full_review`, every check, and every reviewer.

Print only one human line: `Classification: <complexity>, <diff type>; full review: <yes|no>.`
