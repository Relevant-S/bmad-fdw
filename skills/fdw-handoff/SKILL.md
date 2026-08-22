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
- `{state-cli}` → `uv run {project-root}/_bmad/fdw/scripts/fdw_state.py` — the only thing that writes feature state.
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

**This warns; it never refuses.** A BA who ships with a known open question is making a legitimate call, and the number is recorded either way. Your job is to make sure the call is made with open eyes: name the blockers, say who owes the answer, and ask whether to chase them or proceed. If the trend is rising rather than falling, say that out loud — it is the clearest signal the method is not working on this engagement.

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
{handoff-cli} as-built --root {discovery_folder} --phase <phase>
{state-cli} phase-close --root {discovery_folder} --phase <phase> --prd-path <prd path>
{state-cli} phase-open  --root {discovery_folder} --phase <next> --from <phase> --exit-criterion "…"
```

`as-built` appends what shipped, with requirement ids, to the rolling baseline — that is what the next phase gets specced against instead of a pile of old specs. `phase-close` refuses while features are neither handed off nor explicitly deferred or dropped; deferring is `fdw-phase`'s job, so route there rather than forcing.

Then hand the BA `next-call-agenda.md`. It lists what the client still owes, blocking questions first — and when those answers come back as a transcript, `fdw-intake` closes the questions against the client's own words. That loop is what drives the blocker count down, so ending a handoff without giving them the agenda wastes the mechanism.

## Rules with consequences

- **Only `spec-approved` enters a bundle.** "It's basically done" is how development inherits an argument.
- **The blocker report warns; you do not.** Present the number and the names, let the BA decide, and never quietly proceed past a rising count.
- **Never write the PRD yourself.** bmad-core owns PRD authoring and its reviewer gate; this module owns the quality of the inputs.
- **Never advance a feature to `handed-off` before the PRD exists.** The status means development has it, and a status that lies breaks every downstream check.
- **Hand over paths, not a flattened document.** The extraction is `bmad-prd`'s job and it does it better with structure intact.

## Headless

Run pre-flight and bundle, return the paths and the counts, and stop before invoking the PRD skill and before advancing any status. Handing work to development is not an inference to make on someone's behalf.

```json
{"status": "complete", "phase": "phase-1", "bundle": "<path>", "readme": "<path>", "agenda": "<path>",
 "features": ["F-001"], "requirements": 10, "critical_blockers": [], "handed_off": false}
```
