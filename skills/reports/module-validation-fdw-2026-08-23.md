# Module Validation — Feature Discovery Workflow (fdw)

**Date:** 2026-08-23 · **Verdict:** ready for use · **Structural findings:** 0

## Structure

`uv run scripts/validate-module.py skills/` returns zero findings at every severity.

- Setup skill: `fdw-setup`
- Skills: 9 (`fdw-agent-ba`, `fdw-client-packet`, `fdw-consistency`, `fdw-design`, `fdw-elaborate`,
  `fdw-handoff`, `fdw-intake`, `fdw-phase`, `fdw-status`)
- Capabilities registered: 16, across all 10 skills including setup
- No orphan CSV rows, no unregistered skills, no duplicate menu codes, no broken ordering references
- `skills/reports/` correctly ignored — it holds no `SKILL.md`, so it is not treated as a skill

## Agent roster

One agent. Every field in `module.yaml:agents[]` matches the agent's own `customize.toml` `[agent]`
block with no drift: `code=ba`, `name=Vadim`, `title=Business Analyst`, `icon=🧭`, description
identical. The code `ba` resolves to `fdw-agent-ba` with the module prefix and `agent-` stripped,
matching the bmm convention (`bmad-agent-analyst` → `analyst`).

## Quality findings — all fixed during validation

Three capabilities were documented in a SKILL.md but had no help entry, so a user asking for them
by name would have found nothing:

| Fixed | Skill | Capability | Why it mattered |
| --- | --- | --- | --- |
| `[CF]` | `fdw-client-packet` | Record Client Feedback | The skill's own description says "and records what comes back", and it has dedicated *Record what comes back* and *Sign-off* sections. "The client came back on Academy" is a stated trigger phrase. |
| `[AC]` | `fdw-elaborate` | Absorb a Change Record | The *When something changes after approval* flow is the only route by which a post-approval contradiction reaches an approved spec. Unregistered, the sandbox rule had no discoverable entry point. |
| `[PR]` | `fdw-phase` | Phase Report | "Show me the phases" is a stated trigger phrase and the skill has a dedicated *Report* section. |

Also corrected: the pre-flight description now leads with a verb (*Report what would ship…*),
consistent with the other fifteen, and the pipeline chain was rewired so
`packet → feedback → elaborate` rather than `packet → elaborate`, which now reflects that a spec is
written after the client has actually responded.

## Known non-findings

Two things look like defects and are not.

**Validator reports `module_name: Vadim`.** `validate-module.py` parses module.yaml with a flat
line-scanner that cannot see nesting, so the agent roster's `name: Vadim` overwrites the top-level
`name`. Verified against PyYAML — which is what `merge-config.py`, the script that actually writes
config, uses — the module name reads correctly as `Feature Discovery Workflow`. Cosmetic, upstream,
affects no check.

**`fdw-setup` carries 11 path findings and 4 script findings.** These come from the module-builder's
own setup-skill template (`./assets/`-style paths, no `scripts/tests/`, no PEP 723 headers on the
three merge scripts). The shipped `bmad-bmb-setup` produces byte-identical counts against the same
linters, so this is template convention, not a defect in this module. Diverging would put `fdw-setup`
out of step with every other BMad setup skill.

One genuine template defect *was* fixed: the scaffolder emitted `name: "fdw-setup"` quoted, which
fails `quick_validate`'s hyphen-case check. `bmad-bmb-setup` ships it unquoted. Worth reporting
upstream — `assets/setup-skill-template/SKILL.md:2` has `name: "{setup-skill-name}"`.

## Setup extensions added by hand

The generated setup skill is generic; five module-specific steps were added under *Prepare the
Module*, plus a closing step that points at real work instead of a settings summary:

1. Initialize the discovery store via `fdw_state.py init` — creates the registry, the prose files, and phase-1
2. Confirm the shared state CLI resolves from every skill, and fail loudly if it does not
3. Detect the prototype environment and back-fill `component_library_path` / `prototype_stack`
4. Check dependencies (`bmad-prd`, Node, Figma MCP) and report without blocking
5. Seed the glossary from what is already visible in the repo

## Distribution

`bmad install` finds this module already — its scanner walks the project root for a `module.yaml`
and lands on `skills/fdw-setup/assets/module.yaml`. Verified by running the installer's own
`CustomHandler.findCustomContent` against the project; it returns that one path and nothing else.

`.claude-plugin/marketplace.json` was added for the Claude Code plugin marketplace, which is a
different channel. `bmad install` does not read it — the scanner skips dot-directories outright.
Both files are correct; they just serve different installers.

## Verdict

**Validation complete.** The module is structurally sound, its roster is accurate, every documented
capability is registered, and all 215 tests pass. Ready for use.
