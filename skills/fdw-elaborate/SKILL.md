---
name: fdw-elaborate
description: Writes the per-feature spec from an approved design and its source evidence. Use when the user says "write the spec", "elaborate F-003", "спєка", "now describe this properly", or "approve the spec".
---

# fdw-elaborate

## Overview

Act as the analyst who writes it all down *after* the picture is agreed. The prototype settled what the thing is and the client signed the screens; your job is the record — one feature, described so a developer who was in none of the calls can build it, and so anyone can find out who asked for each line and when.

The document is deliberately PRD-shaped but simpler and looser, because it is a **sandbox**: editing it ripples nowhere until it is approved. That isolation is the entire reason it exists. The full PRD gets polluted as everyone talks and changes their mind; a contradicting requirement arriving tomorrow is cheap to absorb here and expensive to absorb downstream.

Two consumers set the bar. **Development**, through the phase PRD, needs requirements that are testable and unambiguous. **The engagement** needs every requirement traceable to a dated quote or a signed-off design decision — on a fixed-price contract that traceability is the difference between absorbing a change and billing it.

## Resolution rules

- Bare paths and `{skill-root}` resolve from this skill's installed directory.
- `{project-root}` → the project working directory.
- `{state-cli}` → `uv run {skill-root}/../fdw-intake/scripts/fdw_state.py` — shipped inside fdw-intake and the only thing that writes feature state.
- `{spec-cli}` → `uv run {skill-root}/scripts/fdw_elaborate.py`.

## On Activation

1. Load config via `uv run {project-root}/_bmad/scripts/resolve_config.py --project-root {project-root}`. Resolve `{communication_language}` and `{output_folder}`; `{discovery_folder}` defaults to `{output_folder}/discovery`.
2. `{spec-cli} gather --root {discovery_folder} --id <F-NNN>`. It refuses unless the client has approved the design — writing the spec first is the ordering this method deliberately inverted.
3. `{spec-cli} scaffold --root {discovery_folder} --id <F-NNN>` if no spec exists yet. It never overwrites one.

## Write the spec

Everything you need is in the gather output. Work from it rather than re-reading the feature folder.

**Requirements come from three places, and the second is the one people miss.** The signal gives you what the client asked for. The **corrections log** in the design notes gives you what they asked for *without knowing it* — every correction the BA made to the prototype is a requirement nobody had written down, and it is the richest seam in the whole method. The **empty-state gaps** give you the steps the happy path hid.

Every requirement carries provenance inline, in one of two shapes:

- `[src: 2026-08-22-academy#t=18:24]` — evidence from an ingested document
- `[from: A2]` — behaviour that came out of the design and was signed off with the screens

Design-derived is the common case here and is not second-class: the client approved that screen. A requirement with neither shape fails validation, and the fix is to go find where it came from — not to invent a citation.

**Confirmed assumptions become statements. Unconfirmed ones become open questions.** Do not quietly promote a guess into a requirement; that is precisely the blocker that surfaces at PRD time.

Fill every section. `Contradictions: none found` is a real answer and takes a second; leaving it blank tells a reader nothing about whether anyone looked. Out of scope prevents more argument than any other section — write what a reasonable person would assume is included and is not.

Set **Size** (XS–XL) with the reasoning in a line, and record dependencies. Both feed phase scoping and build order downstream.

If the feature turns out to be three features, say so and record the intended delivery slices in the spec — but re-slicing the registry belongs to `fdw-intake`, which holds the source evidence. Route it there rather than splitting here.

## File the questions, then close what you can

Every open question gets a criticality and an owner, written into the spec in the shape the sections show: `- **critical** (client) — the question`. **Critical** means development cannot start without it; everything else is non-critical. Owner is `client`, `internal`, or `dev` — who actually has to answer it. `## Missing information` takes the same shape, because a gap nobody has asked about yet still stops the same build; default those to non-critical unless the build genuinely stops without them.

**Prose is counted by nothing.** The ledger in `feature.json` is what approval, the pre-flight report, the phase's own blocker count and the dashboard all read, and a question that lives only in `spec.md` is invisible to every one of them. So:

```
{spec-cli} questions --root {discovery_folder} --id <F-NNN>
```

It stamps an id into each unfiled bullet — the same way requirements get theirs — and prints one command that files them. Run that command. `check` and `approve` both refuse until spec and ledger agree, and `--accept-open-blockers` does **not** get you past that: accepting a blocker you can name is a decision, hiding one nobody has recorded is not.

It also reports where the two have drifted: a question deleted from the spec but still open in the ledger (`--reconcile` writes it back), one already answered but still listed, and a criticality or owner the two disagree on. It resolves none of them — renaming a question means closing it and raising a new one, because ids never change meaning.

Then close what you can. An answer that arrived in a document goes through `fdw-intake`, which anchors it. One that arrived in conversation goes through `{state-cli} question-close`. A question only the client can answer, found now rather than at design time, goes back to them — `fdw-client-packet` has a `--follow-up` round for exactly this.

## Approve

```
{spec-cli} check --root {discovery_folder} --id <F-NNN>     # structure and provenance
{spec-cli} approve --root {discovery_folder} --id <F-NNN>   # mints ids, marks it approved
```

Approve **refuses while any question is open** — not only the critical ones — and names each with its criticality and owner. This is the gate the whole module is measured on: a question this spec still asks is a question the phase PRD will ask, and driving that count to zero is the point. The bar is deliberately at every question, because the eight that reached a real PRD unresolved were every one of them marked non-critical.

`--accept-open-blockers` exists for the case where the BA knowingly proceeds — it records what it let through, in the spec and in the log. Reach for it as a decision, never as a way past the message; and it will not move a spec whose questions were never filed in the first place.

Approval mints stable requirement ids (`F-001-R-01`) in document order. Drafts stay unnumbered on purpose so they can churn freely; once minted, ids never move — a requirement inserted later gets the next number rather than shifting everything below it. Then run the `feature-set` command the tool prints, which advances the feature to `spec-approved` and makes it eligible for a handoff bundle.

## When something changes after approval

New input that contradicts an approved spec arrives as a **change record** in `changes.md`, written by `fdw-intake` — which never edits an approved spec itself. Absorb it: update the requirements, then

```
{spec-cli} close-change --root {discovery_folder} --id <F-NNN> --resolution "absorbed as R-04; …"
```

If the feature was already handed to development, the change belongs to the next phase by default. Say so plainly rather than quietly rewriting something a team is already building.

## Rules with consequences

- **The spec is a sandbox until it is approved.** Nothing downstream reads it before then, and nothing you do here touches another feature.
- **Never edit `signal.md` or the registry.** Signal is evidence owned by `fdw-intake`; state goes through `{state-cli}`.
- **Never write a requirement you cannot source.** Validation enforces it, and the traceability is what protects the engagement.
- **Only a client-approved design gets specced.** The gather step enforces the ordering; do not work around it by scaffolding directly.

## Headless

Take a feature id, draft from the gather output, and run `check`. Return the result and stop — never approve headless. Approval is a judgment about whether open blockers are acceptable, and only the BA can make it.

```json
{"status": "complete", "feature": "F-001", "spec": "<path>", "requirements": 7, "critical_open": ["F-001-Q-01"], "approved": false}
```
