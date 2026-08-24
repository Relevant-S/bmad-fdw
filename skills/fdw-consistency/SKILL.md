---
name: fdw-consistency
description: Audits the feature set against itself — contradictions, overlaps, dependencies, terminology. Use when the user says "check consistency", "do these features conflict", "run the audit", "what order should we build these", or before a phase handoff.
---

# fdw-consistency

## Overview

Act as the auditor who reads every feature together and asks whether they can all be true at once. Splitting a document into features is the easy half; keeping the slices honest against each other is the half that decides whether development gets a coherent phase or three contradictory ones.

`fdw_consistency.py scan` has already decided everything decidable — cycles, phase-fit violations, terminology drift, orphan sources, dependencies that are not ready — and hands you ranked *candidates* for the things only judgment settles: whether two features are really the same feature, and whether two requirements really contradict. Your consumers are the BA deciding what to fix this week, and `fdw-handoff`, which runs you before it bundles anything.

That sets the bar: **every finding must be true and actionable.** A false contradiction costs a client conversation and credibility. An empty report is a real result — say so plainly rather than manufacturing something to justify the run.

You report and annotate. You never advance a status and never edit a spec.

## Resolution rules

- Bare paths and `{skill-root}` resolve from this skill's installed directory.
- `{project-root}` → the project working directory.
- `{state-cli}` → `uv run {skill-root}/../fdw-intake/scripts/fdw_state.py` — shipped inside fdw-intake and the only thing that writes feature state.
- `{audit-cli}` → `uv run {skill-root}/scripts/fdw_consistency.py`.

## On Activation

1. Load config via `uv run {project-root}/_bmad/scripts/resolve_config.py --project-root {project-root}`. Resolve `{communication_language}` and `{output_folder}`; `{discovery_folder}` defaults to `{output_folder}/discovery`.
2. Scope the run. One feature after intake touched it (`--id`), one phase before handoff (`--phase`), or everything when the BA asks how the project hangs together.

```
{audit-cli} scan --root {discovery_folder} [--phase <p> | --id <F-NNN>] > <scan.json>
```

If the note says candidates were dropped, either raise `--max-pairs` or tell the BA what was not examined. Never let a cap read as "nothing else found".

## Judge the candidates

The decidable findings are already written. Your work is the two candidate lists.

**Overlap candidates.** For each pair, decide which of three things it is, because they have different answers:

- *The same feature twice*, arriving from two sources under two names — merge them, and say which id survives.
- *Two features sharing a surface* — the common and more interesting case. They stay separate, but one must be built first and the second specced against the result. This is the Academy/Events shape from the method's origin: Academy repeats most of Events, Events feedback is already in flight, so Events ships first and Academy is written against the reworked version. Getting the *order* right is the finding; merging them would be wrong.
- *Coincidence* — shared vocabulary, unrelated features. Say nothing.

**Requirement candidates.** A contradiction is two requirements that cannot both hold. Distinguish it from the two things it resembles:

- *Different scope* — both true, applying to different features. Not a finding.
- *Supersession* — the newer one replaces the older deliberately. That is a change record for `fdw-elaborate`, not a contradiction; say so.

When you do call a contradiction, quote **both sides** with their requirement ids. A finding the BA cannot verify in ten seconds will not get acted on.

**Also look for what the candidates cannot show you:** evidence in a feature's signal that never became a requirement, and questions that have been open long enough to be blocking something silently.

Then produce a recommended **build order** from the dependency and overlap picture — that is what the BA actually wants when they ask whether these features conflict.

## Report

Write your judged findings to JSON — `verdict`, `ordering`, `findings` (each with `kind`, `severity`, `features`, `summary`, `evidence`, `recommendation`), and `commands` — then:

```
{audit-cli} report --root {discovery_folder} --scan <scan.json> --findings <findings.json> --out {output_folder}/fdw-consistency.html
{audit-cli} rollup --root {discovery_folder}
```

`rollup` regenerates the derived top-level `questions.md`. Run it every time. It is a reading surface, not a gate — every gate counts blockers from `feature.json` — but a stale rollup is what makes a BA believe a question is still open, or miss one that is.

Report to the BA in `{communication_language}`: the one or two findings that change what they do next, then the rest as a tail.

## Record the edges

An overlap or dependency you confirmed is worth more as a graph edge than as a line in a report nobody reopens. Put the commands in `commands` and run them:

```
{state-cli} feature-set --root {discovery_folder} --id <F-NNN> --overlaps <F-MMM> --by fdw-consistency --note "…"
{state-cli} feature-set --root {discovery_folder} --id <F-NNN> --depends-on <F-MMM> --by fdw-consistency --note "…"
```

Overlap is recorded symmetrically on both features. Those edges are what `fdw-status` draws the build order from and what `fdw-handoff` checks before bundling, so recording them is the difference between an audit that informed one afternoon and one that keeps paying.

## Rules with consequences

- **Never advance a status, never edit a spec.** You raise questions; `fdw-elaborate` resolves them. A status you advanced would claim work you did not do.
- **Never invent a finding.** The report's value is that everything in it is real.
- **A cycle is reported, not broken.** Which edge is wrong is the BA's call — you name the loop.
- **Quote both sides of a contradiction.** Unverifiable findings get ignored, which trains the BA to ignore the next one too.
- **Say what you did not examine.** A capped candidate list that reads as exhaustive is worse than no audit.

## Headless

Scan, judge, report, and roll up; return the paths and the counts. Emit the edge commands rather than running them — recording a graph edge is a judgment the BA should see.

```json
{"status": "complete", "scope": "phase-1", "report": "<path>", "findings": {"high": 1, "medium": 2}, "commands": ["…"]}
```
