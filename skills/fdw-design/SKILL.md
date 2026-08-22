---
name: fdw-design
description: Builds and iterates a working prototype for one feature, capturing behaviour as it goes. Use when the user says "draw me this", "prototype this feature", "design F-003", "reproduce the current screens", or "show me what this looks like".
---

# fdw-design

## Overview

Act as the designer who draws first and writes later. This is the inversion the whole module rests on: the client is visual, and until they see screens you argue for weeks and still ship the wrong thing. So requirements are discovered *through* the prototype, and the written spec comes afterwards.

Two consumers, two bars. The **client** reacts to screens, so the prototype has to look like the real product from the first pass — which means reusing the project's actual components, not generic boxes. **`fdw-elaborate`** writes the spec from `design/ux-notes.md` without ever opening the prototype, so the notes must stand alone: every behavioural claim written down, numbered, and tied to the screen it came from.

The prototype is disposable. The notes are not. Never leave the BA maintaining prototype code.

## Resolution rules

- Bare paths and `{skill-root}` (e.g. `references/brownfield.md`) resolve from this skill's installed directory.
- `{project-root}` → the project working directory.
- `{state-cli}` → `uv run {project-root}/_bmad/fdw/scripts/fdw_state.py`, the module-shared state CLI — the only thing that writes to the store.
- `{design-cli}` → `uv run {skill-root}/scripts/fdw_design.py`.

## On Activation

1. Load config via `uv run {project-root}/_bmad/scripts/resolve_config.py --project-root {project-root}`. Resolve `{communication_language}`, `{output_folder}`; `{discovery_folder}` defaults to `{output_folder}/discovery`.
2. Identify the feature. Given an id, use it. Given a name, match it against `{state-cli} context --root {discovery_folder}`. Given nothing, offer the features sitting in `sliced` — those are the ones waiting to be drawn.
3. `{design-cli} scaffold --root {discovery_folder} --id <F-NNN>` and read that feature's `signal.md`. The signal is the evidence; everything you draw should trace to it or be recorded as an assumption.
4. `{design-cli} inventory --project {project-root}` — what components exist and what stack they are in. If it reports `greenfield`, say so: the prototype will establish the component library rather than reuse one.
5. Reproducing something that already exists, or working from Figma? Load `references/brownfield.md`.

## Draw

Generate a runnable prototype into `design/prototype/` using the inventoried components and the detected stack. First pass, whole flow — the BA reacts faster to something wrong than to questions.

Where a component is missing, **build it into the project's library, not inlined into a screen**. The transcript this method came from is explicit about the payoff: the first pass had loose ends everywhere; once components were extracted properly and the screens regenerated, quality jumped and it got fast. Record what you reused and what you built under Components in the notes.

As you draw you are making behavioural decisions nobody asked for — what happens on an empty list, what a date field accepts, what happens when two things collide. Write each one as a numbered assumption in `ux-notes.md`, tied to its screen. These are not filler: `fdw-elaborate` turns every unresolved one into an open question, so an assumption you keep in your head becomes a blocker nobody finds until PRD time.

Tell the BA how to run it, and give them the file path. Expect them to look on a phone.

## Correct

The BA walks the screens and tells you what is wrong — "that date input takes a range, not a single day", "this block is missing a field", "the content is squashed". Two or three rounds usually reaches it.

**Log every correction with its date and screen.** A correction is a requirement nobody had written down; the log is what `fdw-elaborate` reads to find the requirements that were never stated anywhere else. Applying a correction without recording it loses the requirement.

Work in short async turns. The BA may hand you a round from a phone on a walk and come back an hour later.

## Walk the empty state

**Required, not optional.** Once the screens exist, throw away the seeded data and narrate the cold start: you just opened this, nothing exists, no history — show how the very first one gets created.

This is the highest-value move in the method and it was discovered by accident. Asked this question, the model that had just produced confident screens answered *"ah, I goofed, I'm missing something here"* — and only then produced a real elaboration. The happy path hides the gaps; the empty case surfaces them.

Write the narrative and each gap as **G1**, **G2** … in `design/empty-state.md`, and fix the prototype. A gap found here costs one prototype edit; the same gap found at PRD time costs a client conversation.

## Ready for the client

Scan the screens yourself first for obvious mistakes — wrong labels, dead controls, states that cannot be reached. Nothing half-broken goes to a client; it costs credibility that the design was supposed to buy.

Then:

```
{design-cli} check --root {discovery_folder} --id <F-NNN>
```

It refuses while the prototype is empty, the assumptions are unwritten, the corrections log is bare, or the empty-state pass is still a stub — each problem naming its fix. When it passes it prints the `feature-set` command that advances the feature to `client-review`. Run that, then hand off to `fdw-client-packet`, which builds what the client actually reads.

## Rules with consequences

- **Reuse before you build, and build into the library.** A one-off component inlined in a screen makes the next feature start from zero and makes the prototype stop looking like the product.
- **An unrecorded assumption is a future blocker.** It costs one line now and a client call later.
- **Never write `spec.md` or edit `signal.md`.** Signal is evidence owned by `fdw-intake`; the spec is `fdw-elaborate`'s sandbox. Your output is the prototype and the notes beside it.
- **Do not advance the status yourself before `check` passes.** The gate is what stops half-finished designs reaching a paying client.
- **The client never sees this output directly.** `fdw-client-packet` translates it. Write the notes for a BA and a spec writer, in their vocabulary.

## Headless

Take a feature id, run scaffold and inventory, generate a first-pass prototype with assumptions recorded, and stop before the correction loop — corrections need the BA. Return:

```json
{"status": "complete", "feature": "F-003", "prototype": "<path>", "assumptions": ["A1"], "ready": false, "next": "correction loop with the BA"}
```

Never auto-advance to `client-review` headless: `check` requires a corrections log, and a design nobody corrected has not been reviewed.
