# Agent Instructions

Keep changes to Archon platform source rare and deliberate.

## Adapty Archon Topology

There are two separate repositories. Do not mix them.

- Platform source: `/Users/kenaku/dev/archon` locally, `/opt/archon` on the server.
  GitHub: `adaptyteam/archon`.
- Workflow/runtime source: `/Users/kenaku/adapty/archon-workflows` locally, `/srv/archon-data` on the server.
  GitHub: `adaptyteam/archon-workflows`.

The server mounts `/srv/archon-data` into the Archon container as `/.archon`.
The platform repository must not own workflow files. Do not edit `/opt/archon/.archon`
or add `.archon` content to this repository.

## Before Editing

For any Archon-related work, use the `archon` skill first. Read the relevant guide
or reference before changing workflow behavior, workflow files, command files,
scripts, Docker/runtime setup, or server configuration.

Before editing platform source, first check whether the goal can be solved in:

- the `archon` skill;
- `archon-workflows`;
- server/runtime configuration;
- workflow, command, script, or asset files outside the platform repo.

If a platform source change is still needed, ask the user before editing unless the
user explicitly requested that platform source change in the current turn.

## Branch And PR Rule

All changes must go through a branch and PR. This applies to both platform and
workflow repositories, even for tiny fixes.

Before making changes, report:

- repository path;
- current branch;
- dirty status;
- target GitHub repository;
- whether the change is platform or workflow/runtime work.

Do not mix workflow migration, server deployment, and platform source fixes in one
step unless the user explicitly approves that scope.

## Server-First Work

Server-first development is allowed when webhooks, runtime mounts, Docker behavior,
or external integrations make local testing impractical.

If a change starts on the server:

1. Create a branch in the correct server repository.
2. Edit only that repository.
3. Test on the server.
4. Commit and push the branch.
5. Open a PR and share the GitHub URL.
6. Sync the matching local repository from Git.

The server is a valid development surface, but GitHub is the source of truth.

## Local-First Work

If a change starts locally:

1. Create a branch in the correct local repository.
2. Edit only that repository.
3. Run focused checks.
4. Commit and push the branch.
5. Open a PR and share the GitHub URL.
6. Deploy or pull on the server only after the user approves the rollout step.

## Sync Expectations

After a PR is merged:

- `/opt/archon` should match the chosen `adaptyteam/archon` branch.
- `/srv/archon-data` should match `adaptyteam/archon-workflows`.
- local mirrors should be pulled to the same Git state.
- leftover untracked backup files should be reported, not silently deleted.
