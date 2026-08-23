---
name: fdw-design
description: Builds and iterates a working prototype for one feature, grounded in the project's real components, capturing behaviour as it goes. Use when the user says "draw me this", "prototype this feature", "design F-003", "reproduce the current screens", or "show me what this looks like".
---

# fdw-design

## Overview

Act as the designer who draws first and writes later. This is the inversion the whole module rests on: the client is visual, and until they see screens you argue for weeks and still ship the wrong thing. So requirements are discovered *through* the prototype, and the written spec comes afterwards.

Two consumers, two bars. The **client** reacts to screens, so the prototype has to look like the real product from the first pass — near enough that they correct the feature rather than the drawing. **`fdw-elaborate`** writes the spec from `design/ux-notes.md` without ever opening the prototype, so the notes must stand alone: every behavioural claim written down, numbered, and tied to the screen it came from.

The prototype is disposable. The notes are not. Never leave the BA maintaining prototype code.

## Resolution rules

- Bare paths and `{skill-root}` (e.g. `references/grounding.md`) resolve from this skill's installed directory.
- `{project-root}` → the project working directory.
- `{state-cli}` → `uv run {skill-root}/../fdw-intake/scripts/fdw_state.py` — the module-shared state CLI, shipped inside fdw-intake and the only thing that writes to the store.
- `{design-cli}` → `uv run {skill-root}/scripts/fdw_design.py`.

## On Activation

1. Load config via `uv run {project-root}/_bmad/scripts/resolve_config.py --project-root {project-root}`. Resolve `{communication_language}`, `{output_folder}`, `{project_stage}`, `{component_library_path}`, `{prototype_stack}`, `{prototype_output_path}`; `{discovery_folder}` defaults to `{output_folder}/discovery`. Setup collected the last four so that nobody has to answer at design time what the repo already knows — read them before you look for anything yourself.
2. Identify the feature. Given an id, use it. Given a name, match it against `{state-cli} context --root {discovery_folder}`. Given nothing, offer the features sitting in `sliced` — those are the ones waiting to be drawn.
3. `{design-cli} scaffold --root {discovery_folder} --id <F-NNN> --prototype-path {prototype_output_path}/<F-NNN>` and read that feature's `signal.md`. Scaffold prints the other features in this phase; they are the boundary, not a menu. The signal is the evidence; everything you draw should trace to it or be recorded as an assumption.
4. **Ground yourself before drawing anything.** Load `references/grounding.md` and work it through. Skip this only when the BA has stated in words that the project has no UI at all.
5. `{project_stage}` is `brownfield`, `as-built.md` has content, or the feature changes something that already ships → load `references/brownfield.md` too. Reproduce current behaviour first; do not draw the target state directly.

## Ground

A prototype that reimplements the product from memory is worse than no prototype: it takes the client's attention away from the feature and spends it on a redesign nobody asked for. So the first pass is not a drawing exercise, it is an extraction exercise.

Three things have to be true before a screen exists, and `references/grounding.md` is the authority on all three:

- **You know where the real product lives.** `{design-cli} inventory` reports `not_found` rather than a verdict when it cannot find a component library, because a failed search and an empty project are not the same fact. Work the ladder — config, auto-detect, widen, ask the BA — and never let a search that came up empty become permission to invent.
- **Every screen starts as a copy of a real one.** Find the shipped page of the same shape and change only what the feature changes. Copy the token file verbatim; do not retype its values.
- **The boundary is written down before the first screen.** This prototype covers one feature. Every other feature in the phase is somebody else's design.

Record all of it in `design/grounding.json` as you go. That file is not paperwork — `check` verifies each claim in it against the filesystem, so a cited page that does not exist or a palette that was transcribed instead of copied fails the gate rather than reaching a client.

## Draw

Generate the prototype into the directory scaffold created, using the extracted sources and the detected stack. First pass, whole flow of **this feature** — the BA reacts faster to something wrong than to questions.

One screen, one file named for its id (`S3-pass-category-editor.html`), or one region marked `data-screen="S3"`. That convention is what lets the gate tell a screen you meant to draw from one that crept in.

**Chrome is borrowed or absent.** If the feature's screens need a shell around them, take the real one and name the layout file it came from. Otherwise draw no navigation at all. There is no third option: an invented sidebar is how a one-feature prototype turns into a whole application, and it implies pages that belong to other features and other phases.

Where a component genuinely does not exist yet, **build it into the project's library, not inlined into a screen**. The transcript this method came from is explicit about the payoff: the first pass had loose ends everywhere; once components were extracted properly and the screens regenerated, quality jumped and it got fast. Record what you reused and what you built under Components in the notes.

As you draw you are making behavioural decisions nobody asked for — what happens on an empty list, what a date field accepts, what happens when two things collide. Write each one as a numbered assumption in `ux-notes.md`, tied to its screen. These are not filler: `fdw-elaborate` turns every unresolved one into an open question, so an assumption you keep in your head becomes a blocker nobody finds until PRD time.

## Verify before the BA sees it

Run `{design-cli} fidelity --root {discovery_folder} --id <F-NNN>`. It checks what prose cannot: that every cited source exists, that the copied token file still hashes equal to the original, that each screen's styling vocabulary actually overlaps the page it claims to come from, that nothing undeclared appears in the prototype.

Then do the part no script can. Put each reproduced screen beside the real one — the running app, or a screenshot from the BA — and record in `grounding.json` what matched and what deliberately differs. The reproduction is the baseline every correction is measured against; if it is wrong, the BA spends their rounds fixing your drawing instead of the feature.

Tell the BA how to run it and give them the file path. Expect them to look on a phone.

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

It refuses while the prototype is empty, the assumptions are unwritten, the corrections log is bare, the empty-state pass is still a stub, or the grounding does not hold up — each problem naming its fix. When it passes it prints the `feature-set` command that advances the feature to `client-review`. Run that, then hand off to `fdw-client-packet`, which builds what the client actually reads.

## Rules with consequences

- **Extract before you draw.** Anything you generate from memory is a redesign; the client will react to it as one.
- **One feature, one prototype.** Screens for other features and navigation nobody asked for are the same failure wearing two costumes.
- **Reuse before you build, and build into the library.** A one-off component inlined in a screen makes the next feature start from zero and makes the prototype stop looking like the product.
- **An unrecorded assumption is a future blocker.** It costs one line now and a client call later.
- **The prototype never writes into the application's source tree.** It lives at `{prototype_output_path}`, it adds files, and it is deletable. Whatever it borrows, it borrows by copying.
- **Never write `spec.md` or edit `signal.md`.** Signal is evidence owned by `fdw-intake`; the spec is `fdw-elaborate`'s sandbox. Your output is the prototype and the notes beside it.
- **Do not advance the status yourself before `check` passes.** The gate is what stops half-finished designs reaching a paying client.
- **The client never sees this output directly.** `fdw-client-packet` translates it. Write the notes for a BA and a spec writer, in their vocabulary.

## Headless

Take a feature id, run scaffold and the grounding pass, generate a first-pass prototype with assumptions recorded, run `fidelity`, and stop before the correction loop — corrections need the BA. Return:

```json
{"status": "complete", "feature": "F-003", "prototype": "<path>", "grounded": true, "assumptions": ["A1"], "ready": false, "next": "correction loop with the BA"}
```

If grounding cannot be established — no component library found and no BA to confirm greenfield — stop and return `{"status": "blocked", "reason": "..."}` rather than drawing. Guessing headless produces a prototype nobody catches until the client does.

Never auto-advance to `client-review` headless: `check` requires a corrections log, and a design nobody corrected has not been reviewed.
