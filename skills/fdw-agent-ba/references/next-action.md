---
name: Next action
description: Say what to do next, ranked by what unblocks the most
code: NA
added: build
type: prompt
---

# Next action

He asked what to do next, or he is idle and you can see the answer. Give him one thing to do, not a
list to triage.

## What makes something the next action

Rank by **what unblocks the most**, not by what is nearly finished:

- A feature four others depend on beats a feature that is 90% done and blocks nothing.
- A question the client owes beats internal work, because the client's clock is not yours — chase it
  today and it might come back this week.
- A design gate blocking three specs beats a spec you could polish.
- Anything that will contradict itself later beats anything merely unfinished. A feature approved
  ahead of what it inherits from is a defect that gets more expensive every day it sits.

The shape of the answer is one concrete move and the reason it is first:

> Chase the two client questions on Events — Academy can't be specced until they're answered, and
> they've been open eleven days.

Not a ranked list of five things. If the second and third matter, they are one clause at the end.

## Read the shape, not just the counts

The interesting signals are patterns, and they need saying out loud:

- Several features sitting in `client-review` for weeks is a client who has stopped responding. That
  is a relationship problem, not a pipeline problem, and the answer is a phone call.
- Everything bunched at `sliced` means design has not started, and the whole phase is further out
  than the feature count suggests.
- A rising blocker count across phases means the spec gate is not doing its job — say that plainly,
  because the entire method is judged on that number falling.
- Nothing blocked and specs approved means the answer is `fdw-handoff`, and you should say so rather
  than waiting to be asked.

## Then offer to do it

Do not stop at the recommendation. Name the workflow you would run and offer to run it now. He said
"what next" because he wants to get on with it, not because he wanted advice.

## When there is nothing

Say so in one line. "Nothing's blocked, three specs are approved, phase-2 is ready to hand off." An
invented next action wastes the trust the real ones earn.
