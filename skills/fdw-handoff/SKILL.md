---
name: fdw-handoff
description: Bundles a phase's approved specs and drives bmad-prd to produce the phase PRD. Use when the user says "hand off phase 1", "we're done, make the PRD", "bundle these specs", or "run the pre-flight".
---

# fdw-handoff

## Overview

Act as the person who closes a phase out and hands development a contract. Everything upstream was discovery; this is the moment it becomes something a team commits to and a client is billed for.

Two consumers. **`bmad-prd`** turns your bundle into the phase PRD, and it was built to read source documents by path — so your job is to hand it clean, complete, path-addressable inputs, not to write the PRD yourself. **The BA** has to be able to defend what shipped six months later, which is why the bundle carries the decisions log and every requirement's provenance rather than just a list of features.

The bar is one rule and one number. **Only a `spec-approved` feature enters a bundle** — enforced in the script, no exceptions, because the bundle is a contract. And every handoff records how many critical questions were still open at that moment. That number is the module's own evaluation criterion, and the whole method is judged on whether it falls across phases.

## Resolution rules

- Bare paths and `{skill-root}` resolve from this skill's installed directory.
- `{project-root}` → the project working directory.
- `{state-cli}` → `uv run {skill-root}/../fdw-intake/scripts/fdw_state.py` — shipped inside fdw-intake and the only thing that writes feature state.
- `{handoff-cli}` → `uv run {skill-root}/scripts/fdw_handoff.py`.

## On Activation

1. Load config via `uv run {project-root}/_bmad/scripts/resolve_config.py --project-root {project-root}`. Resolve `{communication_language}`, `{output_folder}`, and `{prd_handoff_skill}` (default `bmad-prd`); `{discovery_folder}` defaults to `{output_folder}/discovery`.
2. Identify the phase — the current one unless the BA names another.
3. Run `fdw-consistency` over the phase first. Bundling a set that contradicts itself hands development the argument instead of the answer.

## Pre-flight

```
{handoff-cli} preflight --root {discovery_folder} --phase <phase> --out {output_folder}/fdw-preflight.html
```

It reports what would go, what is not eligible and why, which critical blockers would travel into the PRD unresolved, dependencies left outside the bundle, and the blocker count against previous phases.

**The report never refuses — it is what you run to decide. Bundling does.** `bundle` stops while a critical question is open, because bundling is the moment blockers actually travel and it is the last gate anything passes: a question raised after a spec was approved never goes through the spec gate again. Two ways forward, and name the better one first — bundle the clean features with `--id`, or pass `--accept-open-blockers --reason "…"` to hand off knowingly, which writes the accepted ids into `bundle.json` and into `BUNDLE.md` where the next reader will find them.

Your job is to make sure the call is made with open eyes: name the blockers, say who owes the answer, and ask whether to chase them or proceed. If the trend is rising rather than falling, say that out loud — it is the clearest signal the method is not working on this engagement.

## Bundle

```
{handoff-cli} bundle --root {discovery_folder} --phase <phase> [--id F-NNN …]
```

Omit `--id` for everything eligible; name ids for a partial handoff, which is legitimate — a phase can ship in waves. It writes `handoff/bundle.json`, `handoff/BUNDLE.md`, and `handoff/next-call-agenda.md`.

`BUNDLE.md` is what orients a reader with zero context, and `bundle.json.source_documents` is the ordered list of paths to hand onward. **Do not flatten the specs into one document.** `bmad-prd` subagent-extracts source documents; pre-merging them destroys the structure it reads and blows out context for no gain.

## Hand it to bmad-prd

Invoke `{prd_handoff_skill}` with **Create** intent. Give it the bundle README as the brain dump and the rest of `source_documents` as existing input documents, by path:

> Create a PRD for `<phase>` of `<project>`. The discovery work is complete and lives in these documents — read `handoff/BUNDLE.md` first for orientation, then the feature specs it points at. Every requirement in those specs carries provenance and a stable id (`F-001-R-03`); preserve those ids in the PRD so a requirement stays traceable to the call it came from. Source documents: `<paths>`.

Let it own the PRD. Do not post-process its output, do not re-order its sections, and do not re-write requirements it phrased differently — it has its own reviewer gate, and forking that is how a module drifts away from bmad-core.

If `{prd_handoff_skill}` is unavailable, stop at the bundle and tell the BA exactly what to run. The bundle is the deliverable; the PRD is what someone else makes from it.

Record the resulting PRD path — it goes onto the phase at close, and it is the link between a shipped phase and the document development worked from.

## Close the phase and open the next

In this order, because each step reads what the previous one wrote:

```
{state-cli} feature-set --root {discovery_folder} --id <F-NNN> --status handed-off --by fdw-handoff --note "bundled into <phase> PRD"
{state-cli} phase-close --root {discovery_folder} --phase <phase> --prd-path <prd path>
{handoff-cli} as-built --root {discovery_folder} --phase <phase>
{state-cli} phase-open  --root {discovery_folder} --phase <next> --from <phase> --exit-criterion "…"
```

`as-built` runs **after** `phase-close`, not before: the PRD path it cites is written by `phase-close`, so running it first left every baseline with no reference to the document it describes.

`as-built` appends what shipped, with requirement ids, to the rolling baseline — that is what the next phase gets specced against instead of a pile of old specs. `phase-close` refuses while features are neither handed off nor explicitly deferred or dropped; deferring is `fdw-phase`'s job, so route there rather than forcing.

Re-run it with `--rebuild` whenever a change lands on delivered work; it regenerates that phase's section from the current specs, keeping the original ship date and marking each amended requirement with the change that moved it.

## An urgent change to something already delivered

A feature shipped, the client needs it changed, and it cannot wait for the phase you are speccing now. That is not a new feature and not a spec revision:

```
{handoff-cli} build-brief --root {discovery_folder} --change-id <F-NNN-C-NN>
```

It writes a self-contained intent file and the BA runs `/bmad-build` against it. **Not a PRD** — `bmad-prd` is a phase-scoping instrument and its facilitated discovery is the ceremony the urgency rules out; `bmad-build` is built for exactly one user-facing goal and its own router points express work here.

The brief carries only the delivered requirements the change actually touches, and says how many it left out and where the rest are — a full baseline dump for a large feature spends the build agent's whole context before the change is described. It also carries the real files the prototype was cloned from, which is the most useful thing this module knows about a codebase it does not own.

Do **not** write the bmad-build spec yourself, for the same reason you do not write the PRD: that step exists to investigate the code, and this module has no basis for it.

When it ships, `fdw-elaborate absorb --outcome delivered --delivered-in "<PR>"` amends the spec, then `as-built --rebuild` makes the baseline true again. The feature never leaves `handed-off`.

Then hand the BA `next-call-agenda.md`. It lists what the client still owes, blocking questions first — and when those answers come back as a transcript, `fdw-intake` closes the questions against the client's own words. That loop is what drives the blocker count down, so ending a handoff without giving them the agenda wastes the mechanism.

## Rules with consequences

- **Only `spec-approved` enters a bundle.** "It's basically done" is how development inherits an argument.
- **The report warns; the bundle refuses.** Present the number and the names, let the BA decide between bundling what is clean and overriding deliberately, and never reach for the override on their behalf or quietly proceed past a rising count.
- **An open change record refuses a bundle, for a sharper reason than a question does.** An open question is something nobody has answered; an open change is something the store already knows the spec gets wrong. Handing that to development is shipping a document you know is false.
- **A delivered change never blocks a phase.** It ships beside it. Holding a phase for work that has already missed it is the failure this path exists to prevent.
- **Never write the PRD yourself.** bmad-core owns PRD authoring and its reviewer gate; this module owns the quality of the inputs.
- **Never advance a feature to `handed-off` before the PRD exists.** The status means development has it, and a status that lies breaks every downstream check.
- **Hand over paths, not a flattened document.** The extraction is `bmad-prd`'s job and it does it better with structure intact.

## Headless

Run pre-flight and bundle, return the paths and the counts, and stop before invoking the PRD skill and before advancing any status. Handing work to development is not an inference to make on someone's behalf.

```json
{"status": "complete", "phase": "phase-1", "bundle": "<path>", "readme": "<path>", "agenda": "<path>",
 "features": ["F-001"], "requirements": 10, "critical_blockers": [], "handed_off": false}
```
