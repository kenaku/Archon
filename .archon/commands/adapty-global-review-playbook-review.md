---
description: Review an Adapty MR against diff-type playbooks using compact reviewer packet JSON.
argument-hint: (reads reviewer packet)
---

# Playbook Review JSON

Workflow: `$WORKFLOW_ID`
Artifacts: `$ARTIFACTS_DIR`

## User-Visible Output Policy

Write findings only to JSON artifacts under `$ARTIFACTS_DIR/review`.
Keep stdout to one short line. Do not narrate progress.

## Workflow Context Policy

Do not load or invoke repository skills. Do not read `.agents/skills/*`, `.codex/skills/*`, or any skill `SKILL.md`.
Stay inside the current checkout and explicit artifact paths.
Never search from `/.archon/workspaces`, `/srv/archon-data/workspaces`, a workspace root, or `worktrees/archon`.
Do not use Agent, Task, subagent, or delegation tools.

## Load

Read first:

- `$ARTIFACTS_DIR/review/reviewer-inputs/reviewer-input-playbooks.json`
- `docs/playbooks/index.md`

Then read only a specific `docs/playbooks/*.md` file referenced by the index when its subject or touchpoints match the changed hunks in the packet.

Do not read `surface.json`, reviewer markdown, broad artifact directories, or other reviewer inputs.
The packet already contains the changed files, focused diff excerpts, import deltas, tags, and signals needed for scope.
Allowed tools in this node are Read and Write only. Do not use Bash, Grep, Glob, find, ls, git diff, or package-discovery commands here.
You may Read only packet files, source files named in the packet when a hunk is ambiguous, `docs/playbooks/index.md`, and specific docs referenced from that index.

## Mission

Check changed hunks against the canonical docs in `docs/playbooks`.
This is not a general review lens. Do not review TypeScript quality, races, API design, cache behavior, forms, modals, or public API changes unless a concrete `docs/playbooks/*.md` document applies to the changed hunk.

Process:

1. Read `docs/playbooks/index.md`.
2. Decide from the changed file paths and focused diff excerpts whether any listed playbook applies.
3. If no listed playbook applies, write valid JSON with empty `candidates` and `incidental_observations`, then print `Reviewer playbooks: 0 candidates, 0 incidental.`
4. If a playbook applies, read only that playbook doc and check only its documented rules/touchpoints against the changed hunks.

A candidate is valid only when all are true:

- a specific `docs/playbooks/*.md` document applies;
- a changed hunk violates a rule from that document;
- the evidence points to the changed hunk, not surrounding unchanged code;
- the observation is not already just a generic TypeScript/race/API-design concern.

Final ownership is proven later by ownership gate.

## Output JSON

Write `$ARTIFACTS_DIR/review/reviewer-findings-playbooks.json`:

```json
{
  "schema_version": 1,
  "reviewer": "playbooks",
  "status": "completed",
  "candidates": [
    {
      "severity_hypothesis": "P1|P2|P3",
      "title": "short title",
      "file": "relative/path.ts",
      "line": 123,
      "claim_type": "query_key_scope|export_collision|nullability|race|effect_dependency|api_contract|ui_state|type_safety|other",
      "symbol": "optional exact symbol",
      "claim": "one sentence",
      "causality_hypothesis": "one sentence, not proven",
      "evidence": ["compact evidence bullet"],
      "ownership_check": {"base_head_focus":"exact comparison needed", "suggested_commands":["git diff $BASE_REF...HEAD -- relative/path.ts"]},
      "proof_plan": "one sentence",
      "likely_check_command": "optional narrow command"
    }
  ],
  "incidental_observations": [
    {"title":"short", "file":"relative/path.ts", "reason":"pre-existing or outside MR boundary"}
  ]
}
```

Rules:

- Keep only concrete violations of a specific `docs/playbooks/*.md` rule.
- Do not invent broad playbooks from tags such as api_sdk, query_cache, forms, modals, routing, or public_api.
- Candidate must be on changed hunk data and cite the applicable playbook id/path in evidence.
- If no docs/playbooks document applies, output zero candidates.
- If it appears pre-existing or outside MR boundary, put it in `incidental_observations`.
- Keep evidence compact; no markdown tables or long code snippets.

Also write `$ARTIFACTS_DIR/review/reviewer-summary-playbooks.json`:
`{"reviewer":"playbooks","artifact":"reviewer-findings-playbooks.json","status":"completed","findings":<candidate_count>,"incidental_observations":<n>}`

Print exactly: `Reviewer playbooks: <n> candidates, <n> incidental.`


Strict output and candidate budget:
- Do not write progress narration to stdout. Never write phrases like "Now let me", "I have enough", or "I will".
- The final stdout response must be exactly the requested one-line `Reviewer ...` summary and nothing else.
- Emit at most 5 candidates. Put weaker, compatibility-only, or tech-debt-only observations into `incidental_observations`.
