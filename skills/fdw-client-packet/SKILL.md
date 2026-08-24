---
name: fdw-client-packet
description: Builds the review document a client reads and signs off on, and records what comes back. Use when the user says "send this to the client", "build the client packet", "prepare the review", or "the client came back on Academy".
---

# fdw-client-packet

## Overview

Act as the person who writes the document that gets the work approved. This is not a status report — it is the artifact the engagement is sold on, and the only one a paying client actually reads. Everything upstream exists to make it possible: the prototype gave you screens, the design notes gave you the behaviour, and now someone outside your company has to look at it and say yes.

Your reader is busy, non-technical, often on a phone, and has no idea how you work. They must be able to understand what is being proposed, spot what is wrong, answer what you asked, and say yes — without a call, and without you chasing them. That sets the bar, and it is the reason for the one rule this skill will not bend: **not a single internal term reaches them.** No feature ids, no assumption ids, no sizing, no delivery jargon. `render` refuses when any of it leaks, because "F-001 is XL, A2 unconfirmed" in front of a client destroys exactly the credibility the design bought.

The packet travels as one file, it reaches nothing on the network, and the client's reply comes back inside it.

## Resolution rules

- Bare paths and `{skill-root}` (e.g. `assets/packet.example.json`) resolve from this skill's installed directory.
- `{project-root}` → the project working directory.
- `{state-cli}` → `uv run {skill-root}/../fdw-intake/scripts/fdw_state.py` — shipped inside fdw-intake and the only thing that writes feature state.
- `{packet-cli}` → `uv run {skill-root}/scripts/fdw_packet.py`.
- `{capture-cli}` → `uv run {skill-root}/scripts/fdw_capture.py`.

## On Activation

1. Load config via `uv run {project-root}/_bmad/scripts/resolve_config.py --project-root {project-root}`. Resolve `{communication_language}`, `{output_folder}`, `{client_name}`, and `{client_facing_language}` (default English); `{discovery_folder}` defaults to `{output_folder}/discovery`.
2. `{packet-cli} gather --root {discovery_folder} --id <F-NNN>`. It refuses if there is no prototype or the design has not reached `client-review` — in either case the answer is `fdw-design`, not a packet.
3. Feedback coming back rather than going out? Skip to **Record what comes back**.

## Capture the screens

```
{capture-cli} shots --root {discovery_folder} --id <F-NNN>
```

This is the only way screens get into a packet. It serves the prototype over loopback and drives whichever Chromium-family browser is already on the machine through the DevTools protocol — nothing to install, and no dependence on which browser automation this particular BA happens to have. Two BAs on the same feature get the same pictures, which is the whole point: the packet is a client-facing deliverable, not a local artefact.

What it captures is not a judgment call. `grounding.json` declares the feature's screens and `fdw-design` has already refused to let an undeclared one exist, so the capture list and the feature boundary are the same list. Every screen, in order, at 1280×900 and twice that in pixels, full page rather than the visible window. Screens sharing a file are clipped to their own region; a screen with a file to itself is taken whole, so a borrowed shell stays in the picture.

If it reports no browser, pass `--browser` or set `CHROME_PATH`. If there is genuinely none, carry on: the packet still renders and describes the screens instead. Say that to the client in `how_to_view` — offer the walkthrough. Never imply pictures that are not there.

## Write it

The gather output is internal material in internal language. Translating it is the work. Write the content JSON to match `assets/packet.example.json`, in `{client_facing_language}`:

**What we're proposing** — one section per screen. Two beats each: what you see, and how it works. Describe behaviour, not implementation. The client is deciding whether this is their product, not reviewing your architecture. Name each section the way the client would name that screen; capture attaches images by that name.

**Things we've assumed** — every unconfirmed assumption from the design notes, rewritten as a statement they can agree or disagree with, plus one line on what changes if they say no. This is the highest-value section: it converts guesses you would otherwise discover were wrong at build time into a yes or a no this week.

**What we need from you** — the client-owned open questions, and only those. Carry each question's internal id in its `ref` field; it goes to a sidecar map so answers can be recorded later and never appears in the document. Be ruthless: a packet asking fifteen questions gets none of them answered — and every question you ask is one that must be answered before sign-off. Ask what genuinely blocks progress and leave the rest for the next round.

Open with why they are looking at this and when it happened, and close with what happens next. Say plainly that nothing is built yet — that is what makes it cheap for them to object, and objections now are the entire point.

## Render and send

```
{packet-cli} render --root {discovery_folder} --id <F-NNN> --content <content.json> \
  --shots <manifest from capture> --client "{client_name}"
```

The page carries a reply built in: agree or not-quite on each assumption, an answer box under each question, a name, and one *are these screens right* control. Answers save in the client's own browser as they type, so a reply half-written on a phone survives a closed tab. Finishing produces a block they copy into an email — or download, if they prefer attachments — alongside a plain-language summary of what they are sending.

The reply travels labelled `q1`, `a2`. **No internal id is ever in the client's hands**, not even inside the block; the `.map.json` beside the packet is the join table, and it is internal.

If the vocabulary gate fires, rewrite the flagged text. Do not reach for `--allow-jargon`; it exists for an internal preview, not for anything leaving the building. `--no-reply` renders a read-only copy for an archive.

The packet lands in `client-packets/` inside the feature's own folder, beside its design and its spec — everything about one feature in one place. Give the BA that `.html` path. Tell them to send that one file, that the `.map.json` beside it is internal, and — worth saying out loud to the client — that the page submits nothing anywhere on its own.

## Record what comes back

**The reply the packet produced** — one per person who answered:

```
{packet-cli} sync --root {discovery_folder} --id <F-NNN> --response reply-sasha.txt --response reply-ines.txt
```

Give it every reply at once. It reads them whether they arrive as the pasted block, the downloaded file, or that block buried in an email with the client's own words around it; files them beside the packet so every quote is traceable to something on disk; and prints exactly what to run.

Read what it gives back before running anything:

- **Answered** — one person answered, or several said the same thing. The `question-close` command comes with the client's own words as the quote.
- **Conflicts** — two people answered the same question differently. It refuses to close those and names both. Take it back to the client or make the call with the BA; a script that picked one would be inventing a client decision, which is the one thing this module never does.
- **Corrections** — an assumption they disagreed with. That is not a closed question, it is a requirement nobody had written down: send it to `fdw-design` so the prototype and the notes stay true.
- **Blocked by** — why sign-off is not being offered yet.

- **Unanswered assumptions** — they asked for a verdict and got none. Silence is not agreement, so sign-off is withheld and each one is named. A comment with no verdict is `unclear`, which is not confirmation either.

**Anything that did not come back through the packet** — a reply email in prose, a call transcript, an annotated file — route through `fdw-intake`, which anchors every statement to its source and can auto-close the questions this packet asked. Do not hand-transcribe it here; that throws away the provenance. A single sentence in conversation can go straight to `{state-cli} question-close` with the source and quote.

## A second round, when the spec turns up new questions

Writing the spec surfaces questions only the client can answer — and by then the one client-facing step is behind you. Rather than re-opening an approved design, send a short second packet:

```
{packet-cli} gather --root {discovery_folder} --id <F-NNN> --follow-up
```

`--follow-up` accepts a feature at `speccing` or `spec-approved`. Write a much shorter packet: the questions and nothing else, with one line reminding them what they already signed off. Render and sync exactly as before — a second packet on the same day gets its own filename rather than overwriting the one they already have.

`sync` will not offer sign-off on a follow-up round; the feature is already past that gate and moving it back would quietly un-approve the spec. It records the answers and points you at `fdw-elaborate check`.

## Sign-off

Approval is an event with a date and a source, not a feeling. `sync` emits the `feature-set --status design-approved` command only when every question the packet asked has an answer, nothing is in conflict, and somebody actually said yes. When it withholds it, the reason is in `blocked_by` — fix that rather than working around it. A spec written on an unanswered blocker just moves the blocker downstream.

## Rules with consequences

- **The client never sees an internal term.** Enforced by the gate; do not work around it. The reply block obeys it too.
- **Screens come from the capture harness.** A screenshot taken some other way is one another BA cannot reproduce, and the packet stops being a deliverable and starts being a local artefact.
- **Only client-owned questions go in the packet.** Internal and dev questions are not theirs to answer and make the document look unfinished.
- **Send the `.html`, never the `.map.json`.** The map exists to route answers back and contains the ids the packet exists to hide.
- **Never resolve a conflict on the client's behalf.** Two stakeholders disagreeing is information, not noise.
- **Silence is never agreement.** An assumption they skipped is a guess still standing, and it will turn into rework at the same price as one they never saw.
- **This skill writes no feature state directly.** Sign-off and answers go through `{state-cli}`, so the registry and the feature folder can never disagree.

## Headless

Take a feature id and a content JSON, capture, render, and return the paths. Never record sign-off headless — approval is the client's act, and inferring it from an absent objection is how a project ships something nobody agreed to. `sync` is safe headless: it writes no feature state and returns the commands rather than running them.

```json
{"status": "complete", "feature": "F-001", "packet": "<path>", "map": "<path>", "questions_asked": 2, "screenshots": 4}
```
