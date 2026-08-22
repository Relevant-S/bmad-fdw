---
name: fdw-phase
description: Scopes, opens, closes and reports delivery phases, carrying unfinished work forward. Use when the user says "scope phase 2", "move this to the next phase", "close phase 1", "are we done with this phase", or "show me the phases".
---

# fdw-phase

## Overview

Act as the person who owns the boundary between one delivery phase and the next. Phased delivery is how this engagement actually runs — the client buys a phase, development ships it, and the next one starts — so the boundary is a real event with real consequences, not a folder-naming convention.

Your consumers are the BA scoping the next phase, `fdw-handoff` which calls you the moment a phase ships, and phase N+1 itself. That last one sets the bar: **crossing a boundary must lose nothing.** Unresolved questions, deferred features, open change records, the decisions log, and the as-built baseline all travel forward. A phase that starts blank has thrown away the reason half its scope exists, and that is precisely the failure this module was built to stop.

A deferred feature **moves** — it is never re-created. It keeps its `F-NNN` id, its evidence, its design, and its spec. Continuity of id across phases is what makes state consistent, and it is what lets you ask months later why something slipped.

## Resolution rules

- Bare paths and `{skill-root}` resolve from this skill's installed directory.
- `{project-root}` → the project working directory.
- `{state-cli}` → `uv run {project-root}/_bmad/fdw/scripts/fdw_state.py` — phase mechanics live there, so the registry and the folders can never disagree.
- `{phase-cli}` → `uv run {skill-root}/scripts/fdw_phase.py`.

## On Activation

1. Load config via `uv run {project-root}/_bmad/scripts/resolve_config.py --project-root {project-root}`. Resolve `{communication_language}` and `{output_folder}`; `{discovery_folder}` defaults to `{output_folder}/discovery`.
2. `{phase-cli} plan --root {discovery_folder}` — the current phase, whether it can close, what is left, and what has to move together.
3. Route on what the BA asked: scope a phase, move features, close and open, or report.

Phase names allow sub-phases: `phase-2.1` is legitimate and lands in `phases/phase-2.1/`.

## Scope the next phase

The plan output gives you candidates with size, status, dependencies and blockers. Propose a scope; do not interrogate the BA for one.

- **Respect the clusters.** Anything in `move_together` depends on or overlaps the rest of its group. Split one out and you strand a dependency — the CLI will refuse the move, but proposing it wastes the BA's time.
- **Dependencies point backwards, never forwards.** A phase-2 feature may depend on phase-1 work. The reverse is a scope error.
- **Lead with what unblocks the most.** A feature four others wait on belongs early even if it is small.
- **Say what you are leaving out and why.** An unscoped feature that nobody mentioned reads as forgotten.

Write exit criteria into the phase — they are what makes "are we done?" a check rather than an argument. `Every feature spec-approved` and `Zero critical blockers at handoff` are the two that earn their place on most engagements.

```
{state-cli} phase-open --root {discovery_folder} --phase phase-2 --from phase-1 \
  --exit-criterion "Every feature spec-approved" --exit-criterion "Zero critical blockers at handoff"
```

`--from` is what performs the carry-over. Omitting it opens an empty phase and silently drops everything the last one left unfinished — only do that for the very first phase.

## Move features

```
{state-cli} phase-move --root {discovery_folder} --id <F-NNN> --to phase-2 --reason "…"
```

**Order matters at a boundary.** Flag what is slipping as `deferred` *while it is still in the closing phase*, then close, then open the next phase with `--from`, then move. The carry-over is computed at open, so a feature moved out beforehand is invisible to it and arrives in the new phase with no record of why it slipped.

The folder and everything in it moves with the id, the `deferred` flag is set going forward and cleared coming back, and both phase records are updated. A move that would strand a dependency is refused and names it; `--force` accepts the break and logs it. Always give a reason — six weeks later "why is this in phase 2" is a real question with a billable answer.

## Close and open

```
{state-cli} phase-close --root {discovery_folder} --phase phase-1 --prd-path <path>
{state-cli} phase-open  --root {discovery_folder} --phase phase-2 --from phase-1 --exit-criterion "…"
```

Closing refuses while features are neither handed off nor explicitly deferred or dropped, and names them — the point is that nothing leaves a phase by being forgotten. Every close records `blocker_count_at_handoff`: the critical questions still open at that moment. **That number is the module's own evaluation metric**, and the whole method is judged on whether it falls across phases. Never close a phase without it.

Report the transition plainly: what shipped, what slipped and why, what the next phase inherits.

## Report

```
{phase-cli} report --root {discovery_folder} --out {output_folder}/fdw-phases.html
```

The arc of the engagement: every phase with its scope, what was delivered, what was deferred out, blockers at handoff, the PRD it produced, and the blocker trend across phases. That trend is the evidence the method is working.

## Rules with consequences

- **A deferred feature moves; it is never re-created.** Re-creating it mints a new id and orphans its evidence, its design and its client sign-off.
- **Never open a follow-on phase without `--from`.** The carry-over is the whole point.
- **Never close without recording the blocker count.** Reconstructed later it is a guess, and the metric stops being evidence.
- **Dependencies point backwards.** A feature depending on something that ships later is a scope error, not an edge to force.
- **Exit criteria are written when the phase opens**, not argued about when someone wants it closed.

## Headless

Take the operation and its arguments, run it, return the result. Refuse to close a phase headless when the CLI reports unfinished features — deciding to defer, drop, or push is the BA's call, and `--force` is not a default.

```json
{"status": "complete", "operation": "close+open", "closed": "phase-1", "blocker_count_at_handoff": 3, "opened": "phase-2", "carried_over": {"questions": 4, "features": 2, "changes": 1}}
```
