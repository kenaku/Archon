---
description: Produce the final Adapty evidence review report.
argument-hint: (reads final assessment and compact review artifacts)
---

# Final Report

Workflow: `$WORKFLOW_ID`
Artifacts: `$ARTIFACTS_DIR`

## User-Visible Output Policy

`$ARTIFACTS_DIR/review/final-report.md` is the only human-readable final report artifact.
Stdout must be the same markdown body as `$ARTIFACTS_DIR/review/final-report.md`; do not add extra narration.

## Workflow Context Policy

Do not load repository skills. Stay inside the current checkout and explicit artifact paths.
Never search from `/.archon/workspaces`, `/srv/archon-data/workspaces`, a workspace root, or `worktrees/archon`.

## Load

Read only:

- `$ARTIFACTS_DIR/review/target.env`
- `$ARTIFACTS_DIR/review/merge-readiness-final.json`
- `$ARTIFACTS_DIR/review/fanout-failure.json` if present
- `$ARTIFACTS_DIR/review/ownership-summary.json` if present
- `$ARTIFACTS_DIR/review/validated-findings.json` if present

Do not read `surface.json`, reviewer markdown, or internal markdown mirrors.

## Build Final Report

Create `$ARTIFACTS_DIR/review/` if it does not exist.
This workflow only accepts GitLab MR URL targets. If `TARGET_KIND` is not `mr`, stop and report invalid target.

Write `$ARTIFACTS_DIR/review/final-report.md`.
This is the single human-readable final report for GitLab and chat.
The comment must include:

- Title: `Adapty evidence review`.
- Verdict, readiness score, confidence, and path taken.
- Compact table with MR type/diff type if available, checks, reviewers, ownership gate, proof, confirmed findings, blockers.
- One short recommendation: `Ready to merge`, `Ready with notes`, `Needs fixes before merge`, `Blocked`, or `Needs human attention`.
- If full review ran but no candidate passed ownership, say proof was skipped because ownership gate rejected all candidates.
- State that blockers come only from validated findings.
- Do not include incidental or ownership-rejected observations in blockers.
- If the final assessment reports a workflow contract failure, make the overview recommendation `Needs human attention`, not ready.
- Footer: `review by adapty-review archon workflow`.

## GitLab Side Effects

Do not call GitLab APIs from this node.
Do not run shell commands.
The deterministic workflow node after this one posts `final-report.md` when `POST_GITLAB_COMMENTS=yes`.

## Chat Output

After writing the file, print the exact `final-report.md` content to stdout. Do not print raw JSON, API responses, or extra narration around it.
