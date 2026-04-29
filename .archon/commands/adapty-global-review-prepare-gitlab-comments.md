---
description: Prepare GitLab inline comment JSONL payloads for validated findings.
argument-hint: (reads validated findings and target artifacts)
---

# Prepare GitLab Comments

Workflow: `$WORKFLOW_ID`
Artifacts: `$ARTIFACTS_DIR`

## User-Visible Output Policy

Write only `$ARTIFACTS_DIR/review/gitlab-comments.jsonl`.
Keep stdout to one short line. Do not narrate progress.

## Workflow Context Policy

Do not load repository skills. Stay inside the current checkout and explicit artifact paths.
Never search from `/.archon/workspaces`, `/srv/archon-data/workspaces`, a workspace root, or `worktrees/archon`.

## Load

Read only:

- `$ARTIFACTS_DIR/review/target.env`
- `$ARTIFACTS_DIR/review/merge-readiness-final.json`
- `$ARTIFACTS_DIR/review/validated-findings.json`

Do not read `surface.json`, reviewer markdown, or internal markdown mirrors.

## Build Comments

Create `$ARTIFACTS_DIR/review/` if it does not exist.
This workflow only accepts GitLab MR URL targets. If `TARGET_KIND` is not `mr`, stop and report invalid target.

For each `validated-findings.json.confirmed_findings[]`:

- Attach to the finding `file` and `line` when possible.
- Do not create comments for ownership-rejected, proof-rejected, incidental, or unknown candidates.
- Body must use the exact markdown layout below.
- Keep each section concise, but preserve blank lines between sections.
- Use inline backticks for symbols, function names, component names, props, paths, short code fragments, and literal values.
- Do not use markdown tables, lists, blockquotes, or fenced code blocks.
- Do not collapse all sections into one paragraph.
- Footer: `review by adapty-review archon workflow`.

Markdown body template:

```markdown
[<severity label>] <id> · <title>

**Problem:** <specific failure mode and impact. Use `code` spans for symbols.>

**MR causality:** <why this MR introduced or exposed the issue.>

**Ownership proof:** <changed file/hunk/callsite evidence, or short proof summary.>

**Evidence:** <concrete evidence from validated finding/proof. Use `code` spans for symbols.>

**Why it matters:** <user/runtime/maintenance impact.>

**Fix direction:** <actionable fix.>

**Test direction:** <focused regression test/check.>

_review by adapty-review archon workflow_
```

Severity label mapping:

- `P1` => `Critical`
- `P2` => `Major`
- `P3` => `Minor`
- otherwise use the raw severity.

Write `$ARTIFACTS_DIR/review/gitlab-comments.jsonl` with one JSON payload per line.
Each JSON line must contain only:

```json
{"id":"C-1","severity":"P2","title":"short","file":"relative/path.tsx","line":123,"note":"markdown body"}
```

Do not write markdown draft files, API response files, post payload directories, or posting status artifacts.
Do not call GitLab APIs in this node. Posting is handled by the deterministic `post_gitlab_comments` workflow node.

Print exactly: `GitLab comments: <n> drafted.`
