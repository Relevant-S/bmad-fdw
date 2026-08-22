---
name: fdw-client-packet
description: Builds the review document a client reads and signs off on, and records what comes back. Use when the user says "send this to the client", "build the client packet", "prepare the review", or "the client came back on Academy".
---

# fdw-client-packet

## Overview

Act as the person who writes the document that gets the work approved. This is not a status report — it is the artifact the engagement is sold on, and the only one a paying client actually reads. Everything upstream exists to make it possible: the prototype gave you screens, the design notes gave you the behaviour, and now someone outside your company has to look at it and say yes.

Your reader is busy, non-technical, often on a phone, and has no idea how you work. They must be able to understand what is being proposed, spot what is wrong, and know exactly what is being asked of them — without a call. That sets the bar, and it is the reason for the one rule this skill will not bend: **not a single internal term reaches them.** No feature ids, no assumption ids, no sizing, no delivery jargon. `render` refuses when any of it leaks, because "F-001 is XL, A2 unconfirmed" in front of a client destroys exactly the credibility the design bought.

## Resolution rules

- Bare paths and `{skill-root}` (e.g. `assets/packet.example.json`) resolve from this skill's installed directory.
- `{project-root}` → the project working directory.
- `{state-cli}` → `uv run {project-root}/_bmad/fdw/scripts/fdw_state.py` — the only thing that writes feature state.
- `{packet-cli}` → `uv run {skill-root}/scripts/fdw_packet.py`.

## On Activation

1. Load config via `uv run {project-root}/_bmad/scripts/resolve_config.py --project-root {project-root}`. Resolve `{communication_language}`, `{output_folder}`, `{client_name}`, and `{client_facing_language}` (default English); `{discovery_folder}` defaults to `{output_folder}/discovery`.
2. `{packet-cli} gather --root {discovery_folder} --id <F-NNN>`. It refuses if there is no prototype or the design has not reached `client-review` — in either case the answer is `fdw-design`, not a packet.
3. Feedback coming back rather than going out? Skip to **Record what comes back**.

## Write it

The gather output is internal material in internal language. Translating it is the work. Write the content JSON to match `assets/packet.example.json`, in `{client_facing_language}`:

**What we're proposing** — one section per screen. Two beats each: what you see, and how it works. Describe behaviour, not implementation. The client is deciding whether this is their product, not reviewing your architecture.

**Things we've assumed** — every unconfirmed assumption from the design notes, rewritten as a statement they can agree or disagree with, plus one line on what changes if they say no. This is the highest-value section: it converts guesses you would otherwise discover were wrong at build time into a yes or a no this week.

**What we need from you** — the client-owned open questions, and only those. Carry each question's internal id in its `ref` field; it goes to a sidecar map so answers can be recorded later and never appears in the document. Be ruthless: a packet asking fifteen questions gets none of them answered. Ask what genuinely blocks progress and leave the rest for the next round.

Open with why they are looking at this and when it happened, and close with what happens next. Say plainly that nothing is built yet — that is what makes it cheap for them to object, and objections now are the entire point.

## Render and send

```
{packet-cli} render --root {discovery_folder} --id <F-NNN> --content <content.json> --client "{client_name}"
```

Add `--screenshot "Course list=/path/shot.png"` per screen when the BA has images; they embed so the page travels as one file. Without them the packet describes the screens and offers a walkthrough — say so rather than pretending there are pictures.

If the vocabulary gate fires, rewrite the flagged text. Do not reach for `--allow-jargon`; it exists for an internal preview, not for anything leaving the building.

Give the BA the `.html` path and tell them the `.map.json` beside it is internal.

## Record what comes back

Feedback arrives in two shapes and they take different paths.

**A document** — a reply email, a call transcript, an annotated file. Route it through `fdw-intake`, which anchors every statement to its source and can auto-close the questions this packet asked. Do not hand-transcribe it here; that throws away the provenance.

**A sentence in conversation** — "they're happy, but sessions can't overlap". Close the question directly:

```
{state-cli} question-close --root {discovery_folder} --question-id <id from the map> --answer "…" --source "<packet name>" --quote "<their words, if you have them>"
```

Anything that contradicts what the design already assumed is not a closed question, it is a correction — send it back to `fdw-design` so the prototype and the notes stay true.

## Sign-off

Approval is an event with a date and a source, not a feeling. When the client has actually said yes:

```
{state-cli} feature-set --root {discovery_folder} --id <F-NNN> --status design-approved --by fdw-client-packet --note "approved by <who> on <date> via <packet>"
```

That unlocks `fdw-elaborate`. Do not advance on silence, and do not advance while a question the packet called blocking is still open — a spec written on an unanswered blocker just moves it downstream.

## Rules with consequences

- **The client never sees an internal term.** Enforced by the gate; do not work around it.
- **Only client-owned questions go in the packet.** Internal and dev questions are not theirs to answer and make the document look unfinished.
- **Send the `.html`, never the `.map.json`.** The map exists to route answers back and contains the ids the packet exists to hide.
- **This skill writes no feature state directly.** Sign-off and answers go through `{state-cli}`, so the registry and the feature folder can never disagree.

## Headless

Take a feature id and a content JSON, render, and return the paths. Never record sign-off headless — approval is the client's act, and inferring it from an absent objection is how a project ships something nobody agreed to.

```json
{"status": "complete", "feature": "F-001", "packet": "<path>", "map": "<path>", "questions_asked": 2}
```
