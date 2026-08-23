# Grounding a Prototype in a Product That Already Exists

Load this before drawing anything. It is the difference between a prototype the client corrects
and a prototype the client argues with.

Paths follow the parent skill's conventions: `{design-cli}` is `uv run {skill-root}/scripts/fdw_design.py`,
and the design folder is `{discovery_folder}/phases/<phase>/features/<F-NNN-slug>/design/`.

Everything you establish here goes into `design/grounding.json`, and `{design-cli} check` verifies
each entry against the filesystem. Write it as you work rather than at the end — a claim you cannot
support is a signal to go find the source, not a field to fill in.

## 1. Find the real product

`{design-cli} inventory --project {project-root} --path {component_library_path}` — pass `--path`
whenever config has it, because setup already answered this question and re-deriving it is how the
wrong answer gets in.

The command searches the project, then its parent, then its siblings. That widening matters more
than it looks: BMad is routinely installed in a `docs/` directory with the application beside it in
`app/`, and a search that never leaves the project root reports a shipping product as having no
components at all.

When it reports `verdict: "not_found"`, that is a failed search, **not a finding**. Work down the
ladder until you reach a fact:

1. Read `component_library_path` from config.
2. Re-run with `--path` pointed at what config says.
3. Ask the BA where the application lives, and write the answer back to config so the next feature
   does not ask again.
4. Only if the BA states in words that this project has no UI yet: set `mode` to `greenfield` and
   name them in `greenfield_confirmed_by`.

Never take an empty search result as licence to invent. On a project that already ships, the cost
of that mistake is not a rough prototype — it is a client looking at a redesign of their own product
and wondering what you have been doing.

## 2. Take the fidelity kit, not a list of names

`inventory` returns five things. Knowing that a `DataTable` component exists tells you nothing about
what a page in this product looks like; these do:

| | What it is | What it is for |
| --- | --- | --- |
| `stack` | framework, styling system, package manager, how to run each app | Deciding what the prototype is written in, and how the BA opens it |
| `component_root` + `components` | the library and its exports | Which primitives exist, so you reach for one before writing one |
| `tokens` | the files that define colour, type and spacing | Copied verbatim into the prototype |
| `reference_pages` | real pages, tagged by archetype — list, form, dialog, detail, empty | The page you clone |
| `run_commands` | how to start each app in the tree | Putting the prototype beside the real thing |

Read the top reference pages. One of them is almost certainly the same shape as the screen you are
about to draw, and it carries the shell, the spacing, the table style, the button placement and the
empty state already correct — none of which any list of component names conveys.

## 3. Clone, then change

The rule that replaces "generate a prototype":

> **Do not generate a page. Take the nearest real page of the same archetype and change only what
> the feature changes.**

It works on any stack because it does not know what the stack is. It is also what a contractor
joining the codebase does on their first day, for the same reason: the existing page already encodes
a hundred decisions nobody wrote down.

- **Match the screen to an archetype** — a list, a detail view, a form in a dialog, a wizard step —
  and pull the highest-ranked reference page for it.
- **Start from its actual markup and its actual class vocabulary.** Not your recollection of how
  that framework is usually written. The check measures how much of your styling vocabulary appears
  in the page you cited, precisely because a competent reimplementation reads identically to a clone
  in prose and looks nothing like it on screen.
- **Copy the token file; never retype its values.** `{"source": "...", "copied_to": "prototype/tokens.css"}`
  must hash equal to the original. A transcribed palette produces the trap failure of this whole
  step: correct colours, wrong everything else, and a client who cannot say why it feels off.
- **Do not hand-author a second stylesheet.** If the project has a styling system, the prototype
  uses it. A `<style>` block rebuilding what already exists is the same reimplementation moved
  somewhere the eye does not check.
- **Reach for a real component before writing one.** If one is genuinely missing, build it into the
  project's library shape and record it under Components in the notes.

Record each screen as it lands:

```json
{"id": "S1", "kind": "as-is", "file": "prototype/S1-ticket-types.html",
 "source": "apps/admin/src/features/events/ticket-types/EventTicketTypesTab.tsx"}
```

`kind` is `as-is` for a reproduction of shipped behaviour and `new` for something the feature adds.
`fdw-elaborate` needs that distinction: a requirement describing existing behaviour is context, not
work for development.

## 4. Hold the boundary

You are drawing one feature. Everything else in the phase belongs to another design, and `scaffold`
prints the list so you have it in front of you.

- **One screen, one file named for its id**, or one region marked `data-screen="S3"`. This is what
  makes the boundary checkable: the gate compares the screens present in the prototype against the
  screens declared in the notes, and anything undeclared fails.
- **Chrome is borrowed or absent.** Set `chrome.origin` to `borrowed` and name the real layout file,
  or to `none` and draw no navigation. There is deliberately no third option. Invented chrome is the
  specific mechanism by which a one-feature prototype becomes a whole application: a nav bar needs
  entries, entries imply pages, and now the client is reviewing six features nobody scoped.
- **A screen you want but cannot justify from this feature's `signal.md` is a different feature.**
  Say so to the BA and let `fdw-intake` handle it; do not quietly draw it.

## 5. Verify against the real thing

`{design-cli} fidelity --root {discovery_folder} --id <F-NNN>` covers what can be measured:

- every cited path exists — app root, component root, token sources, each screen's source;
- the copied token file is byte-identical to its original;
- each screen's styling vocabulary overlaps the page it claims to come from;
- no screen appears that no note declares, and no declared screen is missing;
- chrome is borrowed from a real file, or absent;
- the prototype has not hand-authored a stylesheet the project already has.

Then do the part no script can reach. **Put each `as-is` screen beside the real one** — the running
app via `run_commands`, or a screenshot from the BA — and record the result:

```json
{"screen": "S1", "reference": "docs/screenshots/ticket-types.png",
 "verdict": "differs", "differences": "row actions are icon buttons in the real app, not text links"}
```

Required for every `as-is` screen, and the reason is practical rather than procedural: the
reproduction is the baseline every correction is measured against. If it is wrong, the BA spends
their two or three rounds correcting your drawing instead of the feature, and the client sees a
product they do not recognise.

Fix what differs, or say why the difference is deliberate. Either is fine. Not looking is not.
