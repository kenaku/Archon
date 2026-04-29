---
description: Classify one GitLab merge request from compact mechanical facts.
argument-hint: (reads $ARTIFACTS_DIR/mr-intake/facts.json)
---

# MR Intake Classify

Artifacts: `$ARTIFACTS_DIR`

## Output Policy

Do all reading and writing silently.
Do not narrate progress, tool use, or file operations.
When using Read or Write, call the tool directly with no assistant text before or after the tool call.
Any assistant message before the final stdout line is a contract violation.
Print exactly one final line and nothing else:

`MR intake: <size_class>, <change_kind>, risk <risk>, complexity <complexity>.`

Forbidden stdout phrases:

- `I'll read`
- `I'll now`
- `Now I'll`
- `I will`

## Mission

Classify a GitLab merge request for a reviewer-facing first-pass summary.

This is not a code review. Do not prove bugs. Do not route internal reviewer agents. Do not suggest reviewer lenses.

## Load

Read exactly:

- `$ARTIFACTS_DIR/mr-intake/facts.json`

Do not read repository files. Do not run shell commands. Do not fetch GitLab again.

## Interpretation Rules

The facts file is intentionally mechanical. It contains paths, statuses, line counts, hunk counts, MR metadata, and GitLab diff-limit flags.

Use the MR title, description excerpt, labels, branch names, changed paths, statuses, file sizes, directory spread, and extensions to infer semantic classification.

Avoid project-specific assumptions. If a path or extension is ambiguous, say so as uncertainty instead of inventing a precise subsystem.

Treat MR title, description, labels, and branch names as author-provided claims, not verified evidence.

- `primary_purpose` may summarize author intent from title/description.
- `affected_areas` may infer broad areas from paths and author text.
- `notable_facts` must contain only mechanical facts from `stats`, `files`, `limits`, or MR state.
- `notable_facts` must not include details taken from `mr.title`, `mr.description_excerpt`, labels, or branch names.
- `uncertainties` must describe classification uncertainty only. Do not speculate about concrete bugs, runtime behavior, or implementation defects.
- `reviewer_summary` must be a first-pass classification summary, not a review finding.
- Do not mention specific defects, casts, side effects, or behavior changes unless they are directly present as mechanical path/status/stat facts.
- Do not state that claims from the MR description are verified.
- Keep GitLab collapsed/too-large diff flags only in debug JSON. Never mention them in Markdown.
- If `mr.description_excerpt` is empty, do not infer details from the missing description.

## Classification Fields

`size_class`:

- `empty`: no changed files
- `trivial`: very small, usually <= 1 file and <= 10 changed lines
- `small`: localized, usually <= 3 files and <= 100 changed lines
- `medium`: meaningful but reviewable in one pass
- `large`: broad, many files, many hunks, or multiple areas
- `huge`: very broad or likely hard to review safely as one MR

`change_kind`:

- `empty`
- `docs_only`
- `tests_only`
- `config_only`
- `generated_only`
- `source_only`
- `mixed`
- `unclear`

`risk`:

- `low`: obvious docs/tests/mechanical or very local low-impact change
- `medium`: normal source/config change needing standard human review
- `high`: broad, public/runtime/data/deploy/security-looking, deleted/renamed-heavy, or GitLab diff limits present
- `unknown`: facts insufficient

`complexity`:

- `simple`: very localized or mechanically obvious
- `standard`: normal review complexity
- `broad`: multiple areas, many moving parts, or broad refactor
- `hard`: unusually difficult to review safely

## Output

Write GitLab-ready Markdown to:

- `$ARTIFACTS_DIR/mr-intake/summary.md`

Also write the same content and structured fields to debug JSON:

- `$ARTIFACTS_DIR/mr-intake/classification.json`

Markdown requirements:

- Suitable as a GitLab MR comment.
- Concise: target 5-9 lines.
- No reviewer-agent routing.
- No internal workflow details.
- No raw JSON.
- Separate mechanical facts from author claims.
- Do not present author claims as verified facts.
- Do not include a "Mechanical facts" section.
- Do not include a top-level title like `MR intake classification`.
- Do not include section titles except `Likely affected areas`.
- Do not mention additions, deletions, file counts, extension counts, hunk counts, collapsed files, too-large files, or GitLab diff limits in Markdown.
- Do not use these words in Markdown: `files`, `deleted`, `collapsed`, `diff limits`, `too large`, `hunks`, `additions`, `deletions`.
- Use compact badges for size, complexity, and risk.
- Emoji belongs to the value/state, not to the label.
- Make affected areas the main content.
- Do not include a `Reviewer note` section.
- Do not include notes/uncertainty in Markdown.
- Do not include generic caveats like "runtime impact not visible from diff" or "individual semantics not verifiable".
- Do not mention GitLab collapsed/too-large diff flags in Markdown. Keep those only in debug JSON.

Badge emoji:

- Size: `🟢 Small`, `🟡 Medium`, `🔴 Large`, `🟣 Huge`
- Complexity: `🟢 Simple`, `🟡 Standard`, `🔴 Broad`, `🟣 Hard`
- Risk: `🟢 Low`, `🟡 Medium`, `🔴 High`, `🟣 Unknown`

Markdown shape:

```markdown
<One short summary sentence, no label.>

**Size:** 🔴 Large · **Complexity:** 🔴 Broad · **Risk:** 🟡 Medium

**Likely affected areas**
- ...
```

Debug JSON schema:

```json
{
  "schema_version": 1,
  "size_class": "medium",
  "change_kind": "mixed",
  "risk": "medium",
  "complexity": "standard",
  "primary_purpose": "Short inferred purpose of the MR.",
  "affected_areas": ["short human-readable area"],
  "notable_facts": ["fact grounded in facts.json"],
  "uncertainties": ["what cannot be known from compact facts"],
  "reviewer_summary": "One short paragraph suitable for a merge request comment."
}
```

Requirements:

- Use only Markdown in `summary.md`.
- Use only JSON in debug `classification.json`.
- Keep `affected_areas` to at most 6 items.
- Keep `notable_facts` to at most 6 items.
- Keep `uncertainties` to at most 4 items.
- `reviewer_summary` must be concise and MR-facing.
- No internal routing fields.
- No `suggested_lenses`.
- No markdown file.

The final stdout line must use complexity, not review depth:

`MR intake: <size_class>, <change_kind>, risk <risk>, complexity <complexity>.`
