---
name: Quick edit
description: Apply a small correction to state without a full workflow run
code: QE
added: build
type: prompt
---

# Quick edit

"Bump Academy to XL." "Defer notifications to phase 2." "That question's answered — client said yes."

These are corrections, not work. Running a whole workflow for them is the ceremony this agent exists
to spare him. Apply them directly and confirm in one line.

## What you can do here

Everything goes through the shared state CLI, which is the only thing in the module that writes
feature state — so the registry and the feature folders can never drift apart:

```
uv run {project-root}/.claude/skills/fdw-intake/scripts/fdw_state.py <command> --root {discovery_folder}
```

- **Size, flags, dependencies, overlaps** — `feature-set --id F-003 --size XL --by fdw-agent-ba --note "…"`
- **A question he raises in passing** — `question-add --id F-003 --text "…" --criticality critical
  --owner client --source "…"`. Filing a question is recording a fact, not inventing a requirement,
  so it is his to do here — but it is a blocker the moment it lands, and if the feature is already
  spec-approved say so: handoff will refuse to bundle while a critical one is open.
- **An answered question** — `question-close --question-id F-003-Q-01 --answer "…" --source "…" --quote "…"`
  Use his words as the quote when he gave them; a paraphrase is weaker evidence but still better
  than nothing.
- **Moving a feature between phases** — `phase-move --id F-003 --to phase-2 --reason "…"`
- **Advancing a status** — only when the work genuinely happened and only one stage at a time. The
  CLI refuses a forward move that skips a gate, and that refusal is correct; do not reach for
  `--force` on his behalf.

Always pass `--by fdw-agent-ba` and a `--note`. Six weeks from now "why is this XL" has an answer
only if someone wrote one.

## What is not a quick edit

Route these, do not do them:

- Writing or changing a spec → `fdw-elaborate`. The spec is its sandbox, and it mints the ids.
- Anything touching a design or a prototype → `fdw-design`.
- Anything a client sees → `fdw-client-packet`.
- Ingesting a document, however short → `fdw-intake`. A requirement typed in by hand has no
  provenance, and a requirement without provenance is exactly what this module refuses to produce.
- Deciding a contradiction or an overlap is real → `fdw-consistency`.

The line is simple: a quick edit corrects a fact that is already recorded. Anything that would
*create* a requirement, a document, or a client-facing artifact belongs to the skill that owns it.

## Confirm and move on

One line back: what changed, and anything it knocked over.

> Academy is XL now. That puts phase-2 at 21 points, which is more than phase-1 shipped.

If the CLI refuses — a skipped gate, a stranded dependency, a question already closed — read out
what it said rather than working around it. Those refusals are the module's gates, and every one of
them is protecting something that costs real money to get wrong.
