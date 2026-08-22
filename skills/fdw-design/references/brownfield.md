# Reproducing What Exists, and Working From Figma

Two conditional branches of `fdw-design`. Load this when the feature extends a system that already
ships, or when the engagement has designs in Figma. Neither applies to a greenfield feature drawn
from a call transcript.

Paths here follow the parent skill's conventions: `{state-cli}` is
`uv run {skill-root}/../fdw-intake/scripts/fdw_state.py`, `{design-cli}` is
`uv run {skill-root}/scripts/fdw_design.py`, and the design folder is
`{discovery_folder}/phases/<phase>/features/<F-NNN-slug>/design/`.

## Reproduce-as-is, then extend

When the feature changes something that already exists, **reproduce current behaviour first and
layer the new work on top of the reproduction.** Do not draw the target state directly.

This costs an extra pass and repays it twice over. The BA can point at the difference instead of
describing it, and the client sees their own product rather than a redesign they never asked for —
which is the difference between "yes, and change this" and a conversation about why everything moved.

Sources for the current state, in the order worth trying:

1. **`as-built.md`** in the discovery store — what previous phases actually shipped. Refreshed by
   `fdw-handoff` at each phase close, so on a project this module has been running it is the
   cheapest and most reliable source.
2. **The running application or its repo** — the real components, routes and states. Most accurate,
   and it feeds the component inventory at the same time.
3. **Screenshots from the BA or the client** — normal when the system is not in this repo. Ask for
   the states that matter, not just the default one: the populated screen, the empty one, and
   whatever the complaint is about.

Reproduce faithfully, including the parts that are wrong. A reproduction that quietly fixes things
destroys the comparison the BA needs, and the "fix" is often the thing the client asked to keep.

Record the reproduction in `ux-notes.md` under Screens, marking which screens are as-is and which
are new. `fdw-elaborate` needs that line: a requirement describing existing behaviour is not a
requirement for development, it is context.

When the feature is a set of fixes to something existing — the common case for client feedback —
the as-is reproduction *is* the baseline for every correction, and each fix becomes a correction
entry naming what was wrong and what it became.

## Figma

Only when `figma_enabled` is set in config. The Figma MCP is off the critical path by design: this
module discovers requirements through a code prototype because that is what proved fast, and a
design tool in the loop slows the correction cycle down.

Two directions, both optional:

**Import.** The client already has designs and expects them honoured. Pull the frames for context
before drawing, treat them as source material like any other input, and record in `ux-notes.md`
which screens follow an existing design. A prototype that contradicts a design the client already
approved will cost a conversation.

**Export.** Approved screens go back to Figma so a designer can take them further, or because the
client works there. Export after `check` passes, never before — exporting a design still in the
correction loop puts an unfinished state in front of people who will treat it as final.

If the MCP is unavailable or unauthenticated, say so once and carry on with the code prototype.
Figma is never a blocker; the prototype is the deliverable.
