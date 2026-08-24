---
name: fdw-setup
description: Sets up Feature Discovery Workflow module in a project. Use when the user requests to 'install fdw module', 'configure Feature Discovery Workflow', or 'setup Feature Discovery Workflow'.
---

# Module Setup

## Overview

Installs and configures a BMad module into a project. Module identity (name, code, version) comes from `./assets/module.yaml`. Collects user preferences and writes them to three files:

- **`{project-root}/_bmad/config.yaml`** — shared project config: core settings at root (e.g. `output_folder`, `document_output_language`) plus a section per module with metadata and module-specific values. User-only keys (`user_name`, `communication_language`) are **never** written here.
- **`{project-root}/_bmad/config.user.yaml`** — personal settings intended to be gitignored: `user_name`, `communication_language`, and any module variable marked `user_setting: true` in `./assets/module.yaml`. These values live exclusively here.
- **`{project-root}/_bmad/module-help.csv`** — registers module capabilities for the help system.

Both config scripts use an anti-zombie pattern — existing entries for this module are removed before writing fresh ones, so stale values never persist.

`{project-root}` is a **literal token** in config _values_ (the data written into the files above) — never substitute it there. It signals to the consuming LLM that the value is relative to the project root, not the skill root. **This does not apply to the filesystem path _arguments_ passed to the scripts below** (the `--*-path`, `--*-dir`, and `--target` arguments): those are real paths, so you **must** resolve `{project-root}` to the actual project root before running, or the scripts will write to a literal `{project-root}/` directory under the skill folder. The scripts reject an unresolved token with an error.

## On Activation

1. Read `./assets/module.yaml` for module metadata and variable definitions (the `code` field is the module identifier)
2. Check if `{project-root}/_bmad/config.yaml` exists — if a section matching the module's code is already present, inform the user this is an update
3. Check for per-module configuration at `{project-root}/_bmad/fdw/config.yaml` and `{project-root}/_bmad/core/config.yaml`. If either file exists:
   - If `{project-root}/_bmad/config.yaml` does **not** yet have a section for this module: this is a **fresh install**. Inform the user that installer config was detected and values will be consolidated into the new format.
   - If `{project-root}/_bmad/config.yaml` **already** has a section for this module: this is a **legacy migration**. Inform the user that legacy per-module config was found alongside existing config, and legacy values will be used as fallback defaults.
   - In both cases, per-module config files and directories will be cleaned up after setup.

If the user provides arguments (e.g. `accept all defaults`, `--headless`, or inline values like `user name is BMad, I speak Swahili`), map any provided values to config keys, use defaults for the rest, and skip interactive prompting. Still display the full confirmation summary at the end.

## Collect Configuration

Ask the user for values. Show defaults in brackets. Present all values together so the user can respond once with only the values they want to change (e.g. "change language to Swahili, rest are fine"). Never tell the user to "press enter" or "leave blank" — in a chat interface they must type something to respond.

**Default priority** (highest wins): existing new config values > legacy config values > `./assets/module.yaml` defaults. When legacy configs exist, read them and use matching values as defaults instead of `module.yaml` defaults. Only keys that match the current schema are carried forward — changed or removed keys are ignored.

**Core config** (only if no core keys exist yet): `user_name` (default: BMad), `communication_language` and `document_output_language` (default: English — ask as a single language question, both keys get the same answer), `output_folder` (default: `{project-root}/_bmad-output`). Of these, `user_name` and `communication_language` are written exclusively to `config.user.yaml`. The rest go to `config.yaml` at root and are shared across all modules.

**Module config**: Read each variable in `./assets/module.yaml` that has a `prompt` field. Ask using that prompt with its default value (or legacy value if available).

## Write Files

Write a temp JSON file with the collected answers structured as `{"core": {...}, "module": {...}}` (omit `core` if it already exists). Values inside this JSON keep the literal `{project-root}` token. Then run both scripts — they can run in parallel since they write to different files.

In the commands below, replace `{project-root}` in every path argument with the actual project root (e.g. `/home/me/myapp`) before running — these are filesystem paths, not config values.

```bash
uv run ./scripts/merge-config.py --config-path "{project-root}/_bmad/config.yaml" --user-config-path "{project-root}/_bmad/config.user.yaml" --module-yaml ./assets/module.yaml --answers {temp-file} --legacy-dir "{project-root}/_bmad"
uv run ./scripts/merge-help-csv.py --target "{project-root}/_bmad/module-help.csv" --source ./assets/module-help.csv --legacy-dir "{project-root}/_bmad" --module-code fdw
```

Both scripts output JSON to stdout with results. If either exits non-zero, surface the error and stop. The scripts automatically read legacy config values as fallback defaults, then delete the legacy files after a successful merge. Check `legacy_configs_deleted` and `legacy_csvs_deleted` in the output to confirm cleanup.

Run `./scripts/merge-config.py --help` or `./scripts/merge-help-csv.py --help` for full usage.

## Create Output Directories

After writing config, create any output directories that were configured. For filesystem operations only (such as creating directories), resolve the `{project-root}` token to the actual project root and create each path-type value from `config.yaml` that does not yet exist — this includes `output_folder` and any module variable whose value starts with `{project-root}/`. The paths stored in the config files must continue to use the literal `{project-root}` token; only the directories on disk should use the resolved paths. Use `mkdir -p` or equivalent to create the full path.

## Prepare the Module

Config alone does not make this module usable. The steps below follow in order — one of them is
brownfield-only and is skipped for a new build. Resolve `{project-root}` and `{discovery_folder}` to
real paths for all of them.

### Initialize the discovery store

**Greenfield** (`project_stage` is `greenfield`, the default) — nothing to decide:

```bash
uv run "{project-root}/.claude/skills/fdw-intake/scripts/fdw_state.py" init --root "{discovery_folder}"
```

Idempotent. It creates `registry.json`, the decisions, questions, glossary and as-built files,
`sources/`, and **phase-1** — so the BA has a phase to scope into from the first minute. It also
copies the state contract in as `CONTRACT.md`, which makes the store self-describing.

**Brownfield** (`project_stage` is `brownfield`) — two extra questions first, because a project
already in flight does not start at phase 1 and a store that claims otherwise is wrong from
the first minute.

Ask, in the BA's own terms:

> Which phase is the project actually on? Fractional labels are fine — `2.1` if you are mid-way
> through a split second phase.

Accept `3`, `phase-3`, `2.1`, `phase-2.1` and normalise to `phase-<label>`. Then pass it through:

```bash
uv run "{project-root}/.claude/skills/fdw-intake/scripts/fdw_state.py" init --root "{discovery_folder}" --phase "phase-2.1"
```

The store now knows about exactly one phase — the one the project is on. **Earlier phases are not
created, and that is deliberate.** This module's hardest rule is that it never reports state it did
not read, and inventing two closed phases with no features, no dates and no blocker counts would
break it in the most damaging place: the blocker-count trend across phases is how the whole method
is judged, and seeding it with fabricated zeroes makes it meaningless. Ordering still works —
`fdw-phase` and `fdw-consistency` compare phases by their label, not by position in a list — so
opening `phase-4` later, or even backfilling `phase-2`, sorts correctly.

Say this out loud to the BA, in one line, so the absence does not look like a bug:

> Started at phase-2.1. Earlier phases are not in the store — what already shipped goes in the
> as-built baseline instead, which is the next question.

### Record what already exists (brownfield only)

Skip entirely for greenfield.

A brownfield BA is not starting from nothing, and the module should not pretend otherwise. Ask:

> Do you have anything describing what is already live? A previous PRD, a handover note, or just
> tell me in a couple of sentences.

Three ways this goes, and all of them are fine:

- **They point at a document.** Read it and write a short baseline from it — what exists, in
  features, not in implementation detail. Keep it to what a BA would need to know before speccing
  the next thing.
- **They describe it in the chat.** Use their words.
- **They have nothing.** Say that is fine and move on. The baseline fills in at the first handoff.

Then file it:

```bash
uv run "{project-root}/.claude/skills/fdw-intake/scripts/fdw_state.py" as-built-seed \
  --root "{discovery_folder}" --file <your-summary.md> --phase "phase-2.1" --source "docs/prd-phase-2.md"
```

Use `--text "..."` instead of `--file` when they dictated it. The command stamps the section as
recorded at setup and explicitly not verified by this module, which matters: everything else in the
store traces to a quote or a signed-off design, and this does not. It refuses to overwrite a
baseline that already has content.

That baseline is what `fdw-design` reads for reproduce-as-is mode and what `fdw-elaborate` specs the
next phase against, so five sentences here save an argument later.

**If either command fails, stop and say so.** Every other skill in the module writes through that
CLI, and a half-created store is worse than none.

### Confirm the shared state CLI resolves from every skill

That same script is the module's only writer, and it ships inside `fdw-intake`. Sibling skills reach
it at `{skill-root}/../fdw-intake/scripts/fdw_state.py`, which assumes installed skills are flat
siblings. Verify the file exists at `{project-root}/.claude/skills/fdw-intake/scripts/fdw_state.py`.

If it does not, fail loudly rather than continuing — on a layout where skills are not siblings,
every fdw skill breaks at once, and the symptom (a missing CLI six steps into a real engagement) is
far more expensive than the diagnosis here.

### Detect the prototype environment

Only when `prototype_stack` is `auto` or `component_library_path` is blank:

```bash
uv run "{project-root}/.claude/skills/fdw-design/scripts/fdw_design.py" inventory --project "{project-root}"
```

Write the detected `component_root` into `component_library_path` and the detected framework and
styling into `prototype_stack`, so the BA never answers a question the repo could answer. Answering
it *here* is worth the minute: `fdw-design` reads these values before it looks for anything itself,
and a prototype that cannot find the real components is one that invents its own.

A `verdict: "not_found"` result is a failed search, not a finding. The command widens past the
project root to its parent and siblings — the common case is BMad installed in a `docs/` directory
with the application beside it — so if it still found nothing, ask the BA outright where the
application lives and put that answer in `component_library_path`. Only leave both values blank when
the BA confirms there is no UI yet, and say plainly that the first prototype will therefore establish
the component library rather than reuse one. On a `brownfield` project, blank values are a problem to
resolve now, not a default to accept.

### Check what the module depends on

Report what is missing; do not block on any of it.

- **`bmad-prd`** (or whatever `prd_handoff_skill` names) — needed only at phase end. Without it,
  `fdw-handoff` still produces the bundle and tells the BA what to run.
- **Node and a package manager** — needed to *run* prototypes. Without them `fdw-design` still
  generates one; it just cannot be served.
- **A Chromium-family browser** — Chrome, Chromium, Edge or Brave, which `fdw-client-packet` drives
  to capture the prototype screens. Check for one and report the path; if none is found, say that
  `CHROME_PATH` points at it, and that without it packets describe the screens instead of showing
  them. This is the one dependency the client actually sees the absence of.
- **The Figma MCP** — only when `figma_enabled` is true. If it does not respond, say so once; the
  code prototype is the critical path and Figma is optional by design.

### Seed the glossary

Add any product vocabulary already visible in the repo — the project name, headings from an existing
README or PRD — to `{discovery_folder}/glossary.md` in the format the contract defines:

```
- **term** (alias, alias) — what it means
```

This is small but it pays immediately: the first intake resolves those terms instead of inventing
its own, which matters most when the source is a noisy transcript in another language.

## Cleanup Legacy Directories

After both merge scripts complete successfully, remove the installer's package directories. Skills and agents in these directories are already installed at `.claude/skills/` — the `_bmad/` directory should only contain config files.

As with the merge scripts, replace `{project-root}` in the `--bmad-dir` and `--skills-dir` path arguments with the actual project root before running.

```bash
uv run ./scripts/cleanup-legacy.py --bmad-dir "{project-root}/_bmad" --module-code fdw --also-remove _config --skills-dir "{project-root}/.claude/skills"
```

The script verifies that every skill in the legacy directories exists at `.claude/skills/` before removing anything. Directories without skills (like `_config/`) are removed directly. If the script exits non-zero, surface the error and stop. Missing directories (already cleaned by a prior run) are not errors — the script is idempotent.

Check `directories_removed` and `files_removed_count` in the JSON output for the confirmation step. Run `./scripts/cleanup-legacy.py --help` for full usage.

## Confirm

Use the script JSON output to display what was written — config values set (written to `config.yaml` at root for core, module section for module values), user settings written to `config.user.yaml` (`user_keys` in result), help entries added, fresh install vs update. If legacy files were deleted, mention the migration. If legacy directories were removed, report the count and list (e.g. "Cleaned up 106 installer package files from bmb/, core/, \_config/ — skills are installed at .claude/skills/"). Then display the `module_greeting` from `./assets/module.yaml` to the user.

## Point at the First Real Step

Do not end on a configuration summary. Offer the next actual move:

> Point me at whatever the client or sales gave you — a call transcript, a WBS, an old PRD — and
> I will run intake on it. Or say "talk to Vadim" and he will work out which step you want.

If the BA has a document ready, run `fdw-intake` on it now rather than ending the session.

## Outcome

Once the user's `user_name` and `communication_language` are known (from collected input, arguments, or existing config), use them consistently for the remainder of the session: address the user by their configured name and communicate in their configured `communication_language`.
