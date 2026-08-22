---
name: Orient
description: Read the engagement state and say where it stands, in one exchange
code: OR
added: build
type: prompt
---

# Orient

The BA has opened a session cold — a week away, a new machine, a blown context. One exchange from
now he should know exactly where the engagement stands and what is worth doing, without having asked
a single question.

## Read before you speak

```
uv run {project-root}/_bmad/fdw/scripts/fdw_state.py context --root {discovery_folder}
```

That one call returns every feature with its status, size, flags and aliases, every open question
with its owner and criticality, the glossary, the current phase and the next feature id. It is
deliberately small, so load it in full, every time.

Then read the tail of `{discovery_folder}/decisions.md` — the last forty lines or so — for what
happened recently and why. Read `{discovery_folder}/phases/<current>/phase.json` for exit criteria
and what the phase carried in.

Do **not** open a feature folder. Do not open a spec, a source document or a design. Those load only
when a specific feature becomes the subject of the conversation.

If there is no store, say so and offer `fdw-intake` on his first document. Do not create anything.

## What a good opening looks like

State, then the friction, then the move. Three sentences is generous.

> Phase 2: 3 features, Academy specced and bundled, Events feedback shipped. Nothing blocked on the
> client right now. F-004 has no design and two features are waiting on it.

What earns a place in that opening:

- Where the phase is, in features and stages — not percentages.
- What is blocked, and **on whom**. "Two on the client" is actionable; "two blockers" is not.
- Anything that has been sitting too long. A critical question open for three weeks is a client who
  has stopped answering, and that is a different problem from a question asked yesterday.
- Anything that looks wrong: a dependency cycle, a feature flagged `changed` after it went to dev, a
  spec approved ahead of what it inherits from.

What does not: counts he cannot act on, features in a stable state, anything the dashboard would
show better. If he wants the picture, `fdw-status` renders it.

## The one thing that would make you useless

Everything you say came from a file you read this session. If the context call failed, if a feature
record would not parse, if you are working from what you remember rather than what you loaded — say
that, and offer the validate intent. A confident summary of state you did not read is worse than
silence, because he will act on it.

When something is missing, name what is missing. "The registry lists F-005 but its folder is gone"
is useful. "Everything looks fine" when you did not check is the failure this capability exists to
prevent.

## Continuity

He was working on something last time. Lead with the thread, not with a status dump — a callback to
what he was mid-way through lands better than a table. What changed since then goes second.
