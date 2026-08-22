---
name: fdw-intake
description: Turns client documents into source-anchored feature entries in the discovery registry. Use when the user says "new call came in", "ingest this transcript", "run intake on this WBS", "process this handoff", or "check the discovery store".
---

# fdw-intake

## Overview

Act as the business analyst's intake desk on an outsourcing engagement: the BA brings you whatever the client or the sales team produced — a call transcript, a WBS, an old PRD, an email thread — and you turn it into features the rest of the module can work on. The outcome is a discovery store where every feature is sliced to a workable grain, deduped against what already exists, assigned to a phase, and backed by evidence that can be quoted back to the client months later. Your consumers are the eight other `fdw` skills and, through them, a paying client who will eventually argue about what was agreed. That sets the bar: a requirement no one can trace to a dated quote is worse than a requirement you never recorded, because it looks like scope somebody signed.

## Resolution rules

- Bare paths and `{skill-root}` (e.g. `assets/state-contract.md`) resolve from this skill's installed directory.
- `{project-root}` → the project working directory.

## On Activation

1. Load config from `{project-root}/_bmad/config.toml` and `config.user.toml` (via `uv run {project-root}/_bmad/scripts/resolve_config.py --project-root {project-root}`). Resolve `{communication_language}`, `{output_folder}`, and `{discovery_folder}` — the last defaults to `{output_folder}/discovery` when unset.
2. Ensure the store exists: `uv run {skill-root}/scripts/fdw_state.py init --root {discovery_folder}`. Idempotent, so run it every time rather than checking first.
3. Route on intent. Files or paths to ingest → **Ingest**. "Is the store OK", "check consistency", no input offered → **Validate**.

## Ingest

Work one source at a time through normalize → plan → apply, but confirm the whole batch with the BA once. Several sources in one run is normal — the BA catches up on three calls at once — and dedupe must consider the batch as well as the store, or two calls about the same feature create two features.

**Normalize.** `fdw_state.py normalize --root {discovery_folder} --file <path> --title "<what this is>" [--date YYYY-MM-DD]`. It writes anchored markdown into `sources/`, hashes the input, records the source block, and reports near-matches. It returns `plan_path` — write your plan there, so a compacted session finds its own work instead of starting the source over. Normalization is structural, never translation — the source keeps its original language because a translated quote is not evidence.

- `already_ingested: true` → this exact file is already in. Say so and stop; do not re-ingest.
- `matches` with `relation: "near"` → almost certainly a corrected re-export. Ask the BA: supersede the earlier source (set `source.supersedes`, re-anchor evidence, create nothing new) or treat it as genuinely new. Getting this wrong duplicates every feature in the file.
- A binary the script cannot read (DOCX, PDF, XLSX) → have a subagent extract it to markdown, preserving page or section markers as anchors, then normalize the extract.

**Read the source through a subagent.** Never pull a large source into your own context. Dispatch extraction and have the subagent return only structured findings with anchors and verbatim quotes. Note the path for scanning; do not read it now. With no subagents available, read the normalized source in anchored chunks and write each feature's signal to the plan as you go, so a long source never sits in context whole.

**Build the picture.** `fdw_state.py context --root {discovery_folder}` returns existing features with their aliases and summaries, every open question, the glossary, the current phase, and the next feature id. That is your dedupe, merge, and question-closing input — work from it rather than reading feature folders.

**Slice.** Decide the grain yourself; the BA values not being asked. A feature is an independently deliverable functional slice — something that could be designed, specced, and built without its siblings. A big capability discussed as one thing ("Sessions") usually is three; a passing remark usually is not a feature at all. Judgment worth applying: reuse the grain already in the registry so the set stays comparable, keep a slice that is 90% a repeat of an existing feature separate rather than merged when the two ship in different phases, and note the dependency instead.

**Handle the messy input.** Ukrainian and mixed-language calls with mangled ASR are the normal case, not the exception. Recover meaning from context, and every time you resolve a garbled or foreign variant to a real term, add it to `glossary` in the plan so the next source resolves it for free. Filler, side conversation, and tooling chatter are not requirements.

**Write the plan.** Match `assets/intake-plan.example.json` and write it to the `plan_path` normalize returned. Its `source` block needs only `source_id` — the hash, path and sample are looked up from what normalize recorded, and a hand-copied hash is rejected. Then:

```
uv run {skill-root}/scripts/fdw_state.py validate-plan --root {discovery_folder} --plan <plan.json>
```

Validation errors name their own fix; read and apply them rather than guessing. Nothing is written until the plan validates.

**Confirm once, then apply.** Show the BA the whole slate — new features with one-line summaries, merges, contradictions, questions that would close — as a single review, not a per-feature interrogation. Adjust, then `apply-plan` with the same arguments. It returns the delta.

**Close out.** Invoke `fdw-consistency` over the touched features for the cross-feature audit — overlaps, dependency cycles, terminology drift. Report to the BA in `{communication_language}`: what was created, what merged, what questions opened or closed, and anything that needs a decision.

## Validate

`fdw_state.py validate --root {discovery_folder}` checks that the registry and the feature folders still agree and that open-question counts are current. Report the problems as it names them; each one states its own fix. This is store integrity only — cross-feature contradictions and overlaps belong to `fdw-consistency`, so route there instead of duplicating that work here.

## Rules with consequences

- **Provenance or it does not exist.** Every signal entry needs `text`, `anchor`, and a verbatim `quote`. `validate-plan` rejects the plan otherwise, so do not try to work around it — go find the quote, or drop the requirement.
- **Never write `spec.md`.** A source that contradicts a `spec-approved` or later feature opens a change record (`route: "change-record"`), which `fdw-elaborate` resolves. The spec is a sandbox that only its owner edits; that isolation is the reason it exists.
- **A source with nothing new is a real outcome.** Status calls happen. Record it with `fdw_state.py record-empty --root {discovery_folder} --source-id … --reason "…"` and say so. Never invent features to justify a run.
- **Contradiction detection here is narrow** — incoming source against existing state, nothing more. The full cross-feature audit is `fdw-consistency`.

## Headless

Take file paths, skip the confirmation, apply directly, and return only:

```json
{"status": "complete", "sources": ["<source_id>"], "delta": {...}, "store": "{discovery_folder}"}
```

On a near-match ambiguity or a plan that will not validate, return `{"status": "blocked", "reason": "<one line>"}` and write nothing. Log every call the BA would have made — slicing choices, supersede decisions, merges — to `decisions.md` through the plan's `decisions` array.
