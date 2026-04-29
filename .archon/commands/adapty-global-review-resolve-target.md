---
description: Resolve a required full GitLab merge request URL into exact local base and head refs.
argument-hint: <full GitLab merge request URL> [dry-run|no-gitlab-comments|draft-only]
---

# Resolve Adapty Review Target

Workflow: `$WORKFLOW_ID`
Request: `$ARGUMENTS`
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

## Task

Resolve the user target exactly. The target must be a full GitLab merge request URL.

Default mode posts GitLab review output. Set `POST_GITLAB_COMMENTS=yes` unless the user explicitly includes `dry-run`, `no-gitlab-comments`, or `draft-only` in the workflow request.

Read only:

- `docs/index.md`
- `docs/workflow.md`
- workflow-owned target rules in this command
- workflow-owned target and diff rules in this command

## Required URL Shape

Accepted:

```text
https://<gitlab-host>/<group>/<project>/-/merge_requests/<iid>
```

Rejected:

- bare MR iid
- branch name
- SHA
- commit range
- local dirty state
- incomplete GitLab URL

If the request does not contain a full GitLab MR URL, stop. Write a blocking question to `$ARTIFACTS_DIR/review/target.json`: ask the user for the full GitLab merge request URL.

## Rules

- Parse GitLab host, project full path, and MR IID from the URL.
- This workflow currently supports only the Adapty frontend repository: `adapty/adapty-dashboard-interface`.
- If the URL project full path is not `adapty/adapty-dashboard-interface`, stop. Write this error to `$ARTIFACTS_DIR/review/target.json`: `This flow currently works only with the Adapty frontend repository (adapty-dashboard-interface).`
- Do not use `glab`, GitLab API, `git ls-remote`, or broad remote ref discovery in this node.
- Verify the current git remote `origin` points to the same GitLab project full path. If it does not, stop and write the mismatch to `$ARTIFACTS_DIR/review/target.json`.
- Fetch only exact MR ref: `git fetch origin "merge-requests/<MR_IID>/head:mr/<MR_IID>"`.
- Use `origin/master` as the base for this Adapty frontend workflow unless the command already has a locally recorded target branch artifact. Do not query GitLab just to discover the target branch.
- Compute merge-base with `git merge-base origin/master mr/<MR_IID>`.
- Set `MR_TARGET_BRANCH='master'`, `HEAD_REF='mr/<MR_IID>'`, and `BASE_REF='<merge-base-sha>'` in `target.env`.
- After `target.env` is written, switch the current isolated workflow worktree to the resolved MR head with `git switch --detach "mr/<MR_IID>"`.
- Verify checkout by recording `git rev-parse HEAD` and `git branch --show-current` in `target.json`. A detached empty branch name is expected.
- Never silently review current branch when the URL cannot be resolved exactly.
- Post GitLab comments by default. Set `POST_GITLAB_COMMENTS=yes` when the request does not mention posting mode.
- If the request says `dry-run`, `no-gitlab-comments`, or `draft-only`, set `POST_GITLAB_COMMENTS=no`.

## Output Artifacts

Create `$ARTIFACTS_DIR/review/` if it does not exist.

Create `$ARTIFACTS_DIR/review/target.env`:

```sh
TARGET_KIND=mr
TARGET_URL='full GitLab MR URL'
GITLAB_HOST='host from URL'
PROJECT_FULL_PATH='group/project from URL'
TARGET_LABEL='human readable MR target'
BASE_REF='base commit'
HEAD_REF='head ref/commit'
MR_IID='iid'
MR_TARGET_BRANCH='branch'
POST_GITLAB_COMMENTS=yes|no
```

Create `$ARTIFACTS_DIR/review/target.json` with compact JSON containing:

- target summary
- exact base merge-base
- exact fetched MR head ref
- checkout result for the current isolated workflow worktree
- changed-file command that downstream nodes should use
- any unresolved ambiguity

Print only one human line: `Review started: MR !<iid> in adapty-dashboard-interface, checkout <short_sha>, GitLab comments: <yes|no>.`
