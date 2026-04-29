---
description: Build compact diff surface for Adapty review.
argument-hint: (reads target artifacts)
---

# Build Review Surface

Workflow: `$WORKFLOW_ID`
Artifacts: `$ARTIFACTS_DIR`


## User-Visible Output Policy

Write complete findings, evidence, logs, and long explanations only to the required files under `$ARTIFACTS_DIR`.
Keep the final stdout response for this node short because chat adapters may relay it to the user.
Do not narrate progress, tool use, or context gathering. Never write phrases like "I will", "I am checking", "Now let me", or "I have enough context".
The final chat/stdout response must be the only user-visible text from this node. Do all tool use silently; write artifacts before responding.
Do not paste JSON artifacts, artifact payloads, check logs, changed hunk data, or long evidence blocks into stdout.
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

- `$ARTIFACTS_DIR/review/target.env`
- `$ARTIFACTS_DIR/review/target.json`
- workflow-owned target and diff rules in this command

Do not load frontend docs or playbooks in this node. This node owns facts about the diff, not review contracts.
Do not run `glab`, GitLab API calls, `git branch -r --contains`, or broad remote discovery. Use only `target.env` and local git diff commands.

The workflow checked out the current isolated worktree to `HEAD_REF` before this node. Prefer reading files from the filesystem for current target content. Use `git diff "$BASE_REF"...HEAD` for the MR diff. Use `git show "$BASE_REF:path"` only when base-side content is required.

## Build Surface

Create `$ARTIFACTS_DIR/review/` if it does not exist.
If `$ARTIFACTS_DIR/review/target.env` does not exist, stop and report the blocking target question from `$ARTIFACTS_DIR/review/target.json`.

Collect:

- changed file list
- diff stat
- Pre-review status from local git facts only: changed file count, additions/deletions, behind-base count when cheap from local refs, and size warning. Do not call `glab`, GitLab API, or remote discovery here. GitLab process state is outside this workflow.
- file categories: source, tests, styles, docs, config, deps/package files, generated files
- risk markers: API/SDK, auth/permissions, routing, query/cache, forms, modals, shared UI, public exports/barrels, dependency/config, async effects
- compact diff with `-U30` from `$BASE_REF...HEAD`
- changed hunk ranges with `git diff -U0 --unified=0` or equivalent structured parsing
- suspicious relative-parent imports
- stale references for renamed or deleted identifiers when visible in diff
- sibling files for newly created hooks/components/helpers with business logic

Do not paste huge full files. Read full context only for high-risk or candidate files.

## Output Artifacts

Write only `$ARTIFACTS_DIR/review/surface.json` as the review surface. Do not write a markdown surface sidecar.

- target
- base/head
- pre-review status table
- changed files
- file categories
- risk markers
- diff stat
- compact diff excerpts
- changed hunk ranges used for reviewer candidate focus
- risky files
- mechanical-pass results
- reviewer routing facts only; do not include doc excerpts

Do not write separate changed-file or hunk sidecars. Store changed files and hunk ranges inside `surface.json`.

```json
[
  {
    "file": "apps/web/path/file.tsx",
    "old_start": 10,
    "old_lines": 2,
    "new_start": 10,
    "new_lines": 4,
    "change_type": "modified"
  }
]
```

Use `surface.json` `files[].hunks` as reviewer candidate focus. Final MR ownership is not proven from `surface.json`; it is proven later by the ownership gate with base-vs-head checks.

Write `$ARTIFACTS_DIR/review/surface.json` with:

```json
{
  "changed_files_count": 0,
  "additions": 0,
  "deletions": 0,
  "categories": {
    "source": [],
    "tests": [],
    "styles": [],
    "docs": [],
    "config": [],
    "deps": [],
    "generated": []
  },
  "risk_markers": {
    "api_sdk": false,
    "auth_permissions": false,
    "routing": false,
    "query_cache": false,
    "forms": false,
    "modals": false,
    "shared_ui": false,
    "public_api": false,
    "async_effects": false,
    "deps_config": false
  },
  "pre_review": {
    "draft": false,
    "conflicts": false,
    "ci_status": "not_checked",
    "behind_base": 0,
    "size_warning": false
  },
  "responsibility_boundary": {
    "hunks_location": "surface.json files[].hunks",
    "rule": "reviewer observations should focus on changed hunk data or plausible changed contracts; final ownership is proven by ownership-gate base-vs-head checks"
  }
}
```

Print only one human line: `Review surface: <files> files, <risk> risk.`
