---
title: 'Module Plan — BA Feature Discovery Workflow'
status: 'complete'
module_name: 'Feature Discovery Workflow'
module_code: 'fdw'
module_description: 'Turns raw client input (call transcripts, WBS, PRDs, any sales handoff) into design-validated, client-approved feature specs, assembled per delivery phase and handed to bmad-prd.'
architecture: 'BA agent front door + discrete workflow skills'
standalone: true
expands_module: ''
skills_planned:
  - fdw-agent-ba
  - fdw-intake
  - fdw-design
  - fdw-client-packet
  - fdw-elaborate
  - fdw-consistency
  - fdw-handoff
  - fdw-phase
  - fdw-status
config_variables:
  - discovery_folder
  - client_name
  - prototype_output_path
  - component_library_path
  - prototype_stack
  - client_facing_language
  - figma_enabled
  - prd_handoff_skill
created: '2026-08-22'
updated: '2026-08-22'
---

# Module Plan

## Vision

<!-- Drafted Phase 1 — to be confirmed with user -->

A BMad module that automates the working method a BA (Vadim) arrived at by hand on a live outsourcing
engagement, and hardens it into repeatable workflows so no rules/templates have to be re-typed per project.

**The method, as practiced today (from the 2026-08-22 call):**

1. Client input arrives — mostly call transcripts, but also whatever sales hands over.
2. AI parses it: "here's what you agreed on, here are candidate new features."
3. **Design first, not docs.** The BA immediately says "draw me this" — a working visual prototype.
   The AI produces screens plus its own assumptions about how it should behave.
4. BA walks the screens, gives 2–3 rounds of corrections ("wrong date input", "field missing").
   The AI records corrections into UX notes alongside the prototype.
5. Screens go to the client. **The client is always visual** — until you show pictures you argue for
   weeks and still ship the wrong thing.
6. Once the design is approved: "now write me the spec for this feature." The spec is written
   *post-factum* from the agreed visual.
7. The spec is a **sandbox** — editing it touches nothing downstream. It carries open questions
   (critical / non-critical), contradictions, feedback, missing info.
8. When enough specs are approved, they get selected (1, 2, 3 … 8) and packed into a PRD.
9. PRD goes to development.

**Why it beats classic BMad for this context:** classic BMad writes the PRD first and derives design from
it. This is outsourcing — there is a paying client who must be *sold* the solution, and a paying client
signs off on pictures, not on FR-18. So the flow is inverted: requirements are *discovered through the
visual*, and the written record is produced once reality is agreed.

**The pain being solved:** it's all manual and unstructured. Every project re-teaches the AI the rules,
templates, folder conventions, and definitions. Nothing is standardized, state lives in chat, and
decisions made along the way evaporate.

## Architecture

**Decided in Phase 1 (rationale to be expanded in Phase 3):** one conversational BA agent (`fdw-agent-ba`)
as the front door — it knows project state and routes — backed by discrete workflow skills for each stage.
Rationale: preserves the low-ceremony "just talk to it" feel Vadim works in today, while making every stage
standardized, independently runnable, and headless-capable so nothing has to be re-explained per project.

**PRD boundary:** the module prepares a phase bundle (approved specs, designs, decisions, resolved
questions) and invokes `bmad-prd` Create with those paths as source documents. bmad-core owns PRD
authoring; this module owns the quality of its inputs. A pre-flight blocker report runs before handoff and
warns (does not refuse) — this makes Vadim's own success metric visible at exactly the moment he measures it.

**Design output:** code prototype is the primary path (HTML/React reusing the project's component library,
as proven in the transcript). Figma MCP is wired as optional import/export, not the critical path.

### Decisions Locked (Phases 1–2)

| Decision | Choice | Why |
| --- | --- | --- |
| Module identity | `fdw` — Feature Discovery Workflow | Names the actual job: discovering features from raw client input. Continuity with the earlier attempt's naming. |
| Shape | BA agent front door + discrete workflow skills | Keeps Vadim's low-ceremony conversational feel; makes each stage standardized, independently runnable, and headless-capable. |
| Design output | Code prototype primary, Figma MCP optional | Proven in the transcript; component reuse is what made output quality jump. Figma stays available but off the critical path. |
| PRD boundary | Prepare bundle → invoke `bmad-prd` Create | bmad-core owns PRD authoring and its reviewer gate; this module owns input quality. Satisfies requirement 4 with no forking. |
| Blocker gate | Pre-flight report at handoff, **warns, does not refuse** | Surfaces Vadim's own success metric at the moment he measures it, without blocking a BA who knowingly accepts risk. |
| Change absorption | Reopen spec + change record + downstream-impact flag | The spec exists *because* it is cheap to change. Preserve that, but never silently — the audit trail is what protects an outsourcing engagement. |
| As-built baseline | Maintained, refreshed at each phase handoff | Answers the EasyPay "keep patching one PRD" failure and Ostap's mid-term-memory gap. Phase N+1 reads it instead of loading N old specs. |
| Language | Any input language in, English artifacts out | Matches `document_output_language: English`. Intake owns Ukrainian/mixed/noisy-ASR normalization. `client_facing_language` exists as config for future clients. |
| Deployment | Per client project repo, state in `{discovery_folder}` | Prototypes need the project's component library next to them; phase folders match Ostap's "phase 1.2 → folder 1.2" ask. |

### Feature Lifecycle

Every feature in the registry carries exactly one status. This is the module's spine — "is phase 1 done?"
becomes a registry query rather than something the BA holds in his head.

```
candidate → sliced → designing → client-review → design-approved
          → speccing → spec-approved → handed-off → shipped
```

Orthogonal flags: `changed` (reopened after approval — carries a change record), `deferred` (moved to a
later phase), `dropped` (explicitly out of scope, kept for the audit trail).

Rules every skill must honor:

- Only `design-approved` features may enter `speccing`. The design gate is real — it is what the client signed.
- Only `spec-approved` features may enter a handoff bundle.
- A feature entering `changed` records what changed, the source, and whether its design is invalidated and
  whether it was already handed to dev. If already handed off, the change is scoped to the next phase by default.
- No skill may advance a status it did not do the work for.

### Memory Architecture

**Pattern: on-disk indexed project state store as the shared memory, plus light personal memory for the one agent.**

This module inverts the usual BMad memory question. There is a single agent, so there is no cross-agent
sharing problem — but there *is* the problem Ostap named in the call: BMad's short-term (chat) and long-term
(PRD, architecture) tiers leave a hole where sprint-level reasoning dies, and naive long-term memory blows
the context window ("if we have 10 PRDs and it pulls all 10 every time, the context is finished").

So the durable memory here is not agent memory. It is a versioned, indexed **state store on disk** that every
skill reads and writes:

```
{discovery_folder}/                    # default {output_folder}/discovery/
  registry.json         # THE INDEX — small enough to load in full, every time
  decisions.md          # mid-term memory: why X over Y. Append-only. Survives phase boundaries.
  questions.md          # derived rollup of every open question across all features
  glossary.md           # normalized domain terminology — defence against noisy ASR and multi-source drift
  as-built.md           # rolling baseline of what has actually shipped
  sources/
    index.json          # every ingested input: hash, date, type, features touched
    {date}-{slug}.md    # normalized source + extraction log with provenance anchors
  phases/
    phase-1/
      phase.json        # scope, dates, status, feature ids, carry-over from prior phase
      features/
        F-001-{slug}/
          feature.json  # id, title, status, size, deps, overlaps, provenance refs
          signal.md     # evidence extracted for this feature, every line source-anchored
          design/
            prototype/      # runnable HTML/React
            ux-notes.md     # AI assumptions + BA correction log
            empty-state.md  # cold-start walkthrough findings
          spec.md       # the elaboration doc — THE SANDBOX
          questions.md  # feature-local open questions, critical / non-critical
          changes.md    # change records opened after approval
      client-packets/
        {date}-{slug}.html
      handoff/
        bundle.yaml
        blocker-report.html
        next-call-agenda.md
    phase-2/ ...
```

**Loading discipline — this is the whole point.** On activation the agent loads `registry.json`, the
`questions.md` rollup, and the tail of `decisions.md`. Bounded, small, always. It loads a *feature folder*
only when working that feature. Source documents are never pulled wholesale into the parent context —
skills subagent-extract them, the same rule `bmad-prd` applies.

**Personal memory** lives at `{project-root}/_bmad/memory/fdw-agent-ba/` and is about the BA, not the project:
how he likes specs written, phrasing preferences, question types he always wants asked, plus a daily log.
It travels with him between client engagements; the state store does not.

### Memory Contract

| File | Purpose | Written by | Read by |
| --- | --- | --- | --- |
| `registry.json` | The index. Per feature: id, title, slug, phase, status, size, deps, overlaps, paths, open-question counts, last updated. The contract between every skill. | intake, design, client-packet, spec, consistency, handoff, phase | all skills, agent on activation |
| `decisions.md` | Mid-term memory. One append-only line per decision: what, why, alternatives rejected, source. Never pruned, never rewritten. Crosses phase boundaries intact. | all skills | agent (tail on activation), handoff (bundled to PRD), phase (carry-over) |
| `questions.md` | Derived rollup of feature-local open questions: id, feature, criticality, owner (client / internal / dev), age, status. Regenerated, never hand-edited. | consistency, intake, spec | agent on activation, status, handoff blocker report, client-packet |
| `glossary.md` | Canonical domain terms with aliases seen in sources. Keeps a Ukrainian call, an English WBS, and a legacy PRD talking about the same thing. | intake, consistency | intake, spec, client-packet, consistency |
| `as-built.md` | What has actually shipped, per phase. Refreshed at handoff. | handoff | design (reproduce-as-is mode), spec, intake (dedupe against shipped features), agent |
| `sources/index.json` | Every ingested input with hash, date, type, and which features it touched. Enables re-ingest detection and provenance lookup. | intake | intake, consistency, spec |
| `phases/{n}/phase.json` | Phase scope, status, dates, feature ids, carry-over from prior phase, exit criteria. | phase, handoff | all skills, agent |
| `features/{id}/feature.json` | Per-feature record mirroring its registry entry plus full provenance refs. Registry is the index; this is the record. | intake, design, spec, consistency | design, client-packet, spec, handoff |
| `features/{id}/signal.md` | Extracted evidence, every line anchored to source + quote + timestamp. | intake | design, spec |
| `features/{id}/spec.md` | The elaboration doc. **Sandbox** — editing it must ripple nowhere until approved. | spec | handoff, consistency, client-packet |
| `features/{id}/changes.md` | Change records after approval: what changed, source, downstream impact, resolution. | spec, intake | handoff, consistency, agent |
| `_bmad/memory/fdw-agent-ba/` | The BA's own preferences and daily log. Portable across engagements. | agent | agent |

**Consistency rule:** no skill may leave the registry disagreeing with the feature folders. A skill that
writes a feature folder updates the registry in the same run, or it has failed.

### Cross-Agent Patterns

There is one agent, so the interesting pattern is agent↔workflow, not agent↔agent.

- **The agent is the router, not a gatekeeper.** `fdw-agent-ba` is the front door — it reads state, answers
  "where are we / what's blocking / what's next," and invokes the right workflow. But every workflow is also
  directly invocable and headless-capable. The BA who knows what he wants should never have to go through
  a conversation to get it. (He works from his phone on walks; ceremony is a tax.)
- **`registry.json` is the contract.** Workflows do not pass state to each other in conversation. They read
  the registry, do their work, and write it back. This is what makes the pipeline resumable after a context
  compaction, a new session, or a two-week gap — the failure mode Ostap described as memory dying with the chat.
- **`fdw-consistency` is a service, not a stage.** It is invoked by `fdw-intake` after slicing, by
  `fdw-handoff` before bundling, and by the BA on demand. It never advances a feature's status — it reports
  and annotates relations (overlaps, deps) so other skills can act.
- **`fdw-handoff` calls `fdw-phase`** to close phase N and open N+1 after a successful bundle. Phase
  transition is one operation, not two things the BA must remember to do in order.
- **Outward handoff to bmad-core:** `fdw-handoff` invokes `bmad-prd` with Create intent, passing bundle
  paths as source documents. It does not attempt to author or post-process the PRD.

## Skills

Nine skills: one agent front door plus eight workflows. The module's `fdw-setup` skill is **not** listed
here — it is generated by **Create Module (CM)** once these are built; its extensions are specified under
*Setup Extensions* below.

Every brief below is written to be handed to the Agent Builder or Workflow Builder with **zero conversation
context**. Shared conventions all skills inherit:

- `{discovery_folder}` defaults to `{output_folder}/discovery/`. Layout is defined in *Memory Architecture*.
- Feature ids are `F-NNN`, minted by `fdw-intake`, never reused, never renumbered. Folder names are
  `F-NNN-{slug}`.
- Any skill that writes a feature folder updates `registry.json` in the same run.
- Any skill that makes a non-obvious call appends one line to `decisions.md`.
- Source documents are subagent-extracted, never loaded wholesale into the parent context.
- All artifacts are written in `{document_output_language}` (English) regardless of input language.

---

### fdw-agent-ba

**Type:** agent

**Persona:** A senior business analyst who has run discovery on outsourced engagements for a decade. Direct,
unceremonious, allergic to process theatre. Speaks in the BA's own vocabulary — features, specs, blockers,
phases — not in framework nouns. Assumes the BA is competent and busy, often on a phone, often mid-walk.
Never asks a question it could answer by reading the registry. Opens with state, not with pleasantries:
"Phase 1: 9 features, 3 specced, 2 blocked on the client. Events feedback is still open and Academy is
waiting on it."

**Core Outcome:** The BA can open a session cold — after a week away, a new machine, a blown context — and
know within one exchange exactly where the engagement stands and what the next useful action is, then take
it without explaining anything.

**The Non-Negotiable:** Never fabricate state. Everything it reports comes from `registry.json`,
`questions.md`, `decisions.md`, or a feature folder it actually read. If state is missing or inconsistent,
it says so and offers to run `fdw-consistency` — it does not paper over the gap with a plausible summary.

**Capabilities:**

| Capability | Outcome | Inputs | Outputs |
| --- | --- | --- | --- |
| Orient | BA knows engagement state in one exchange | registry, questions rollup, decisions tail, current phase.json | Spoken summary: phase progress, blocked features, what's next |
| Route | The right workflow runs with the right arguments, without the BA naming it | Natural-language intent ("new call came in", "draw the sessions thing", "we're done with phase 1") | Invocation of `fdw-intake` / `fdw-design` / `fdw-elaborate` / `fdw-client-packet` / `fdw-consistency` / `fdw-handoff` / `fdw-phase` / `fdw-status` |
| Answer state questions | No registry spelunking by hand | "What's blocking phase 1?", "Which features overlap?", "What did we decide about session recurrence?" | Direct answer with source citation (feature id, decision line, source doc) |
| Quick edits | Small corrections without a full workflow run | "Bump Academy to XL", "defer notifications to phase 2", "that question's answered, client said yes" | Registry / feature.json / questions.md update + decisions line |
| Next-action recommendation | The BA is never idle wondering what to do | Full state | Ranked shortlist with reasoning — usually "close these 2 client questions, then Events design can proceed" |
| Preference capture | The module gets more like this BA over time | Correction patterns observed in session | Append to personal memory (`_bmad/memory/fdw-agent-ba/`) |

**Memory:** On activation reads `registry.json` (full), `questions.md` (full rollup), tail of `decisions.md`
(last ~40 lines), current `phase.json`, and personal memory. Loads a feature folder only when that feature
is the subject. Writes: personal memory daily log tagged `fdw-agent-ba`, plus registry/questions/decisions
edits from Quick edits.

**Init Responsibility:** On first run in a project, detect whether `{discovery_folder}` exists. If not, tell
the BA the module isn't initialized and offer to run `fdw-setup`. Never scaffold state itself — that is
setup's job, and silently creating a half-store is how state stores rot.

**Activation Modes:** Interactive primarily. Should degrade gracefully to terse output when the BA is
clearly on a phone (short messages, no formatting requests).

**Tool Dependencies:** None directly — it invokes the module's workflows.

**Design Notes:** Build this **last**. Its activation contract depends on the final shapes of
`registry.json` and `questions.md`, and its routing depends on all eight workflows existing. Resist making
it a gate: the BA must always be able to bypass it and call a workflow directly. The single riskiest failure
mode is an agent that summarizes state it hasn't read — the non-negotiable exists to kill that.

**Relationships:** Front door to all eight workflows. Never writes specs, designs, or bundles itself.

---

### fdw-intake

**Type:** workflow

**Purpose:** Turn any document the BA receives — call transcript, WBS, existing PRD, sales handoff, email
thread, screenshot pack, or a mix — into source-anchored feature entries in the registry, correctly sliced,
deduped against what already exists, and assigned to a phase.

**The Non-Negotiable:** Every extracted requirement carries provenance — source file, quote, and timestamp
or location. A requirement with no traceable origin does not get written. This is scope control on a paid
engagement, and it is what makes contradiction detection possible at all.

**Capabilities:**

| Capability | Outcome | Inputs | Outputs |
| --- | --- | --- | --- |
| Normalize input | Any format and any language becomes clean, English, structured source text | File path(s) or pasted content: JSON transcript, DOCX, PDF, MD, XLSX WBS, existing PRD, email | `sources/{date}-{slug}.md` — normalized text with stable anchors; entry in `sources/index.json` |
| Handle noisy ASR and mixed language | Ukrainian/English call transcripts with mangled ASR become usable without losing meaning | Raw transcript | Normalized source + new/updated `glossary.md` entries mapping garbled variants to canonical terms |
| Detect input granularity | The module knows whether it received one feature, several, or a whole project | Normalized source | Classification + extraction strategy chosen, logged to decisions |
| Extract feature candidates | Every discussed capability surfaces as a candidate, with evidence | Normalized source, registry, glossary | Candidate list with provenance-anchored evidence per candidate |
| Slice into features | Big blobs become independent, self-contained functional features at a sane grain | Candidate list, existing feature grain in registry | Proposed slices with rationale; BA confirms or adjusts in one pass |
| Dedupe and merge | The same feature described in a transcript and a WBS becomes one feature, not two | Candidates, registry, `as-built.md` | Merge decisions; existing features get new evidence appended to `signal.md` rather than duplicated |
| Detect contradictions | New input that conflicts with a prior source or an approved spec surfaces immediately, with both sides quoted | Candidates, existing signals and specs | Contradiction entries in feature `questions.md` and/or a change record via `fdw-elaborate` |
| Auto-close open questions | Answers given on a call close the questions that prompted them, without the BA re-reading his own agenda | Normalized source, `questions.md` | Questions marked resolved with the answering quote attached; decisions line per closure |
| Assign phase | New features land in the right phase instead of a pile | Slices, current phase scope, `phase.json` | Phase assignment per feature; out-of-scope items marked `deferred` to a later phase |
| Write state | Registry and feature folders reflect the new input | All of the above | `F-NNN` folders with `feature.json` + `signal.md`, updated `registry.json`, appended `decisions.md` |

**Design Notes:**
- **Re-ingest safety.** Hash every source. Re-ingesting the same file must be idempotent — this will happen,
  because transcripts get re-exported.
- The auto-close capability is what makes the open-questions loop actually close. It pairs with
  `fdw-handoff`'s next-call agenda: the module asks the questions, the call answers them, intake closes them.
- Slicing is **proposed, then confirmed** — the transcript shows the BA values the AI deciding the split
  ("it decides on its own how to break it up"), but a wrong grain is expensive, so one confirmation pass is
  cheap insurance. Confirmation must be a single batched review, not a per-feature interrogation.
- Never touch `spec.md` directly. Contradictions with an approved spec route through `fdw-elaborate`'s change flow
  so the sandbox rule and the change record hold.

**Activation Modes:** Both. Headless takes file paths and returns the registry delta as JSON.

**Tool Dependencies:** Document readers for DOCX/PDF/XLSX. Subagent extraction for large sources.

**Relationships:** Entry point of the pipeline. Invokes `fdw-consistency` after writing. Feeds `fdw-design`.

---

### fdw-design

**Type:** workflow

**Purpose:** Produce and iterate a working visual prototype for one feature, reusing the project's real
component library, and capture the behavioural assumptions and BA corrections alongside it. This is where
requirements are actually discovered — the written spec comes after.

**The Non-Negotiable:** The prototype must reuse the project's existing components, and where components are
missing it builds them properly into the library rather than inlining one-offs. The transcript is explicit
that this is what took output from "loose ends everywhere" to fast and good.

**Capabilities:**

| Capability | Outcome | Inputs | Outputs |
| --- | --- | --- | --- |
| Grounding | Prototypes look like the real product from the first pass because they are cloned from it | `component_library_path`, project repo, its parent and siblings | Fidelity kit: stack, components, token files, ranked reference pages, run commands — recorded in `design/grounding.json` |
| Fidelity verification | An ungrounded prototype is caught by a check, not by the client | `grounding.json`, prototype, cited sources | Pass/fail per rule: cited paths exist, token file hashes equal, styling vocabulary overlaps its source, comparison recorded |
| Boundary enforcement | One feature stays one feature | Registry siblings, declared screens, prototype contents | Undeclared screens and invented chrome fail the gate |
| Generate prototype | The BA has screens to react to within one turn | `signal.md`, feature.json, component inventory, `as-built.md` | Runnable prototype under `design/prototype/` |
| Record assumptions | The AI's behavioural guesses are visible and challengeable, not buried in code | Generation run | `design/ux-notes.md` — numbered assumptions, each linked to the screen it affects |
| Correction loop | 2–3 rounds take the prototype to "ideal", as observed in practice | BA comments ("wrong date input", "field missing", "blocks are squashed, needs sections") | Updated prototype + correction log appended to `ux-notes.md` |
| **Empty-state walkthrough** | Gaps the happy path hides get caught before the client sees anything | Prototype, feature.json | `design/empty-state.md` — cold-start narrative ("you just opened it, nothing exists, show me how it gets populated") + gaps found + prototype updates |
| Reproduce-as-is mode | Brownfield features extend reality instead of a fantasy | `as-built.md`, existing app/repo, optional screenshots | Faithful reproduction of current behaviour, then the new feature layered on top |
| Figma bridge *(optional)* | Existing client designs are honored; approved screens can go back to Figma | Figma MCP, `figma_enabled` | Imported design context, or exported frames |
| Internal review scan | Obvious mistakes never reach the client | Prototype, ux-notes | Defect list; BA fixes before status advances |
| Advance status | The pipeline knows this design is ready to show | All of the above | Feature status → `client-review`; registry updated |

**Design Notes:**
- Prototype-first is the module's core inversion and its commercial rationale: the client is visual, and
  until they see pictures you argue for weeks and still ship the wrong thing.
- The empty-state walkthrough is promoted from an accident to a required pass. In the transcript this single
  question made the AI find its own gap and only then produce a proper elaboration.
- `ux-notes.md` is the primary input to `fdw-elaborate`. Treat it as a first-class artifact, not scratch — the
  spec is written *from* it.
- The prototype is disposable; the notes are not. Do not let the BA end up maintaining prototype code.
- Support short async turns. The BA gives corrections from his phone and comes back later.

**Activation Modes:** Both. Headless generates a first pass and reports the path.

**Tool Dependencies:** Node/pnpm to run the prototype. Figma MCP when `figma_enabled`.

**Relationships:** After `fdw-intake`. Before `fdw-client-packet`. Gates `fdw-elaborate` — a feature cannot be
specced until its design is approved.

---

### fdw-client-packet

**Type:** workflow

**Purpose:** Produce the artifact the client actually reads and signs off on — screens plus plain-language
description plus the specific questions we need them to answer — and fold their feedback back into state.

**The Non-Negotiable:** Zero internal vocabulary. No feature ids, no sizes, no assumption numbers, no
"FR-", no BMad nouns. If the client has to decode it, the packet has failed at the one thing it is for.

**Capabilities:**

| Capability | Outcome | Inputs | Outputs |
| --- | --- | --- | --- |
| Assemble packet | The client gets one self-contained thing to review | Prototype screens, ux-notes (translated to plain language), feature.json | Self-contained HTML packet under the feature's own `client-packets/`, readable on a phone |
| Surface client questions | The client answers exactly what we need, nothing more | Feature `questions.md` filtered to `owner: client` | Numbered question block in the packet, each tied to the screen it concerns |
| Show what's assumed | Silent assumptions become explicit sign-off items | `ux-notes.md` assumptions | "We assumed X — correct?" list in client language |
| Capture feedback | Client comments become state, not an unread email | Client's reply (any form: email, transcript, annotated doc) | Feedback recorded to feature folder; answered questions closed; contradictions raised |
| Sign-off | Approval is a recorded event with a date and a source | Client approval | Feature status → `design-approved`; decisions line with the approving quote and date |

**Design Notes:**
- This is a **sold** artifact, not a report. It is the moment the engagement is defended, which is why it is
  separate from `fdw-design` rather than a mode of it.
- Publishable as a shareable HTML artifact — the BA reviews and forwards from his phone.
- `client_facing_language` config exists for engagements where English isn't the client's working language.
  Defaults to English per the current decision.
- Client feedback frequently arrives as another call transcript. When it does, the BA should be able to
  route it through `fdw-intake` instead, which already knows how to close questions from a source. This
  skill's capture capability handles the lighter cases (email, inline comments).

**Activation Modes:** Both.

**Tool Dependencies:** None beyond HTML generation.

**Relationships:** After `fdw-design`. Its sign-off is the gate `fdw-elaborate` checks.

---

### fdw-elaborate

**Type:** workflow

**Purpose:** Write the feature elaboration spec — Vadim's "спєка" — from the approved design and the
source-anchored signal. A simplified, flexible PRD-shaped document scoped to exactly one feature.

**The Non-Negotiable:** **The spec is a sandbox.** Writing or editing `spec.md` must ripple nowhere —
not into a PRD, not into another feature, not into anything downstream. Only `spec-approved` status makes it
eligible as PRD input. This isolation is the reason the artifact exists; the BA built it deliberately
because "the PRD gets polluted" as everyone changes their mind.

**Capabilities:**

| Capability | Outcome | Inputs | Outputs |
| --- | --- | --- | --- |
| Draft spec | A complete, reviewable elaboration of one feature | `signal.md`, `design/ux-notes.md`, `empty-state.md`, prototype, `as-built.md`, glossary | `spec.md` with: need (problem, outcome) → rules → requirements → out-of-scope → assumptions → open questions → contradictions → feedback → missing info |
| Provenance-anchor requirements | Every requirement can be traced to who asked for it and when | signal provenance | Source reference on each requirement line |
| Size the feature | Effort is visible before commitment | Requirements, deps, component gaps | XS / S / M / L / XL with the reasoning recorded |
| Order and dependencies | Build sequence is derived, not guessed | Registry, overlaps, as-built | `depends_on` / `blocks` edges written to feature.json and registry |
| Split oversized specs | A feature that turned out to be three features becomes three specs | Draft spec | Proposed split into independent functional slices; new `F-NNN` entries on confirmation |
| Open-questions triage | Blockers are visible and owned long before PRD time | Draft spec | Feature `questions.md`: each question tagged critical / non-critical and owned by client / internal / dev |
| Resolve questions | The spec converges | BA answers, or answers arriving via `fdw-intake` | Questions closed with the answer and its source; spec updated |
| Reopen with change record | Post-approval change is absorbed without silently rewriting history | New contradicting input, feature status | Status → `changed`; `changes.md` entry with what/source/why; downstream-impact flags (design invalidated? already handed to dev? → default-scope to next phase) |
| Approve | The spec becomes PRD-eligible | BA approval | Status → `spec-approved`; requirement IDs minted stable at this moment; decisions line |

**Design Notes:**
- **Requirement IDs are minted at approval, not at draft.** The BA deliberately avoids `FR-18`-style IDs in
  the draft because churn makes them meaningless. But PRD assembly needs traceability. Minting stable
  per-feature ids (`F-007-R-03`) exactly at approval gets both.
- **Named `fdw-elaborate`, not `fdw-spec`, on purpose.** bmad-core ships `bmad-spec`, which is an entirely
  different artifact — a five-field machine kernel (Why / Capabilities / Constraints / Non-goals / Success
  signal) for downstream automation. This skill writes a client-facing elaboration doc. The distinct name
  prevents a builder from inheriting `bmad-spec`'s template or vocabulary. The verb is also the BA's own —
  the original artifact he described was literally called `ElaborationDoc`. **The output file stays
  `spec.md`**, because "спєка" is what he calls it out loud and that is the word he should keep seeing.
- The spec is written **after** the design is approved, never before. That ordering is the method.
- Ideal end state: by the time a spec is approved, every critical blocker in it is closed. That is the
  metric `fdw-handoff` measures.

**Activation Modes:** Both.

**Tool Dependencies:** None.

**Relationships:** Requires `design-approved`. Invoked by `fdw-intake` for the change-record path. Feeds
`fdw-consistency` and `fdw-handoff`.

---

### fdw-consistency

**Type:** workflow

**Purpose:** Keep the feature set honest against itself. This is requirement 2's real content: splitting a
document into features is easy, keeping the slices consistent with each other is the hard part.

**The Non-Negotiable:** Reports and annotates; never advances a feature's status. It is a service other
skills call, not a stage in the pipeline.

**Capabilities:**

| Capability | Outcome | Inputs | Outputs |
| --- | --- | --- | --- |
| Contradiction audit | Two specs that disagree get caught before dev does | All specs and signals in scope | Contradiction list with both sides quoted and sourced; entries added to feature `questions.md` |
| Overlap detection | "Academy is 90% Events" becomes a graph edge, not tribal knowledge | Specs, signals, registry | `overlaps` edges with similarity rationale; reuse suggestions ("spec Academy against the approved Events spec") |
| Dependency and ordering | Build order is computed from real edges | `depends_on` / `blocks` edges | Ordered build sequence; cycle detection with the offending loop named |
| Terminology drift | The same concept stops having three names across five features | Specs, `glossary.md` | Drift report; glossary updates |
| Coverage gaps | Requirements discussed in a source but never landing in any spec get caught | `sources/`, signals, specs | Orphan-evidence list |
| Phase-fit check | Phase scope is achievable and self-contained | `phase.json`, sizes, deps | Warnings: dependency crossing a phase boundary backwards, size blowout, feature depending on something deferred |
| Rollup questions | One place to see everything blocking | Feature-local `questions.md` | Regenerated top-level `questions.md` |
| Report | The BA sees it all at once | All of the above | HTML consistency report; registry annotations |

**Design Notes:**
- The Academy/Events case from the transcript is the canonical test: overlap detected → Events feedback
  ordered first → Academy built on top → possibly two separate PRDs. If the skill can't produce that
  conclusion from that input, it isn't finished.
- Runs against a scope: one feature, one phase, or everything. Full-project runs should subagent-fan-out per
  feature pair rather than loading every spec into one context.
- Never edits `spec.md`. It raises questions; `fdw-elaborate` resolves them.

**Activation Modes:** Both. Headless returns findings as JSON.

**Tool Dependencies:** None.

**Relationships:** Called by `fdw-intake` after slicing and by `fdw-handoff` before bundling. Invocable on
demand by the BA.

---

### fdw-handoff

**Type:** workflow

**Purpose:** Close out a phase — select approved specs, prove they are ready, bundle them, and drive
`bmad-prd` to produce that phase's PRD. This is requirement 4.

**The Non-Negotiable:** Only `spec-approved` features enter a bundle. No exceptions, no "it's basically
done." The bundle is a contract with development.

**Capabilities:**

| Capability | Outcome | Inputs | Outputs |
| --- | --- | --- | --- |
| Select scope | The BA picks what ships, from a list that's already been validated | Registry filtered to `spec-approved` in the phase | Confirmed selection ("specs 1, 2, 3 … 8"), recorded |
| Pre-flight blocker report | Vadim's own success metric, shown at the moment he measures it | `questions.md`, selected specs, `changes.md` | HTML report: unresolved critical blockers by feature and owner, count vs. previous phases as a trend. **Warns, does not refuse.** |
| Assemble bundle | bmad-prd gets clean, complete, path-addressable inputs | Selected specs, designs, ux-notes, decisions, resolved questions, glossary, as-built | `handoff/bundle.yaml` manifest + a bundle README orienting a reader with no context |
| Invoke bmad-prd | The phase PRD gets produced by bmad-core, not by a fork | Bundle paths | `bmad-prd` Create invoked with bundle paths as source documents; resulting PRD path recorded in `phase.json` |
| Refresh as-built | Phase N+1 can be specced against reality instead of memory | Shipped specs, prior `as-built.md` | Updated `as-built.md` |
| Next-call agenda | Unresolved client questions become the agenda for the next call | `questions.md` filtered to `owner: client` | `handoff/next-call-agenda.md` — grouped by feature, criticality first |
| Close and open phase | Phase transition is one operation | Phase state | Calls `fdw-phase`: features → `handed-off`, phase closed, next phase opened with carry-over |

**Design Notes:**
- The blocker report is the module's built-in evaluation criterion. Track the count over phases — a module
  that works drives it toward zero. Worth persisting the number in `phase.json` so the trend is real data.
- `bmad-prd` Create binds its own run folder and subagent-extracts source documents. Do not pre-flatten the
  bundle into one giant document — hand it paths and let it extract. Record the resulting PRD path back into
  `phase.json` so the link survives.
- The next-call agenda is the loop-closer: it feeds the next client call, whose transcript feeds
  `fdw-intake`, which auto-closes the questions it asked.
- Partial handoff is legitimate. A phase can hand off in waves; `phase.json` tracks which features went in
  which bundle.

**Activation Modes:** Both.

**Tool Dependencies:** `bmad-prd` (bmad-core, present in this install).

**Relationships:** Terminal stage of a phase. Calls `fdw-consistency` before bundling and `fdw-phase` after.

---

### fdw-phase

**Type:** workflow

**Purpose:** Own the phase lifecycle so that phased delivery is native rather than a folder-naming
convention. This is requirement 3.

**The Non-Negotiable:** Crossing a phase boundary must lose nothing. Unresolved questions, deferred features,
open change records, decisions, and the as-built baseline all carry forward. A new phase starts informed,
never blank.

**Capabilities:**

| Capability | Outcome | Inputs | Outputs |
| --- | --- | --- | --- |
| Initialize phase 1 | First run has a real scope, not an empty folder | Available features, BA priorities | `phases/phase-1/phase.json` with scope, exit criteria, feature ids |
| Propose phase scope | Scope is derived from dependencies, size, and priority rather than guessed | Registry, sizes, deps, overlaps, client priority | Proposed feature set with rationale and a size rollup; BA confirms or adjusts |
| Move features between phases | Rescoping mid-flight is a supported action, not a manual file shuffle | Feature ids, target phase | Features moved, `deferred` flags set, dependency violations flagged, registry and both `phase.json` files updated |
| Close phase | A closed phase is a finished, auditable record | Phase state | Phase status → closed; final feature statuses; blocker count and PRD path recorded |
| Open next phase | Phase N+1 starts with everything phase N knew | Prior `phase.json`, unresolved questions, deferred features, `as-built.md`, `decisions.md` | New `phases/phase-{n+1}/` with carry-over manifest: what's inherited and why |
| Phase report | The engagement's arc is visible | All phases | Per-phase summary: scope, delivered, deferred, blockers at handoff, PRD produced |

**Design Notes:**
- Phase numbering supports sub-phases (`phase-2.1`) — the transcript references "phase 2.1", so the scheme
  must not assume integers. Folder names follow Ostap's ask directly: phase 1.2 → `phases/phase-1.2/`.
- A feature deferred from phase 1 keeps its `F-NNN` id and its accumulated signal, design, and spec. It
  moves; it is not re-created. Continuity of id is what makes state consistent across phases.
- Exit criteria are explicit in `phase.json` so "are we done with phase 1?" is a check, not a judgment call.

**Activation Modes:** Both.

**Tool Dependencies:** None.

**Relationships:** Called by `fdw-setup` on init and by `fdw-handoff` at close. Invocable directly for
rescoping.

---

### fdw-status

**Type:** workflow

**Purpose:** Make the whole engagement legible at a glance — for the BA on his phone, and for anyone else
who needs to know where discovery stands.

**The Non-Negotiable:** Derived, never authoritative. It reads state and renders it. It must never be the
place a fact lives.

**Capabilities:**

| Capability | Outcome | Inputs | Outputs |
| --- | --- | --- | --- |
| Pipeline board | Every feature's position in the lifecycle is visible at once | Registry | HTML board: features × lifecycle stage, colour-coded, phone-legible |
| Blocker view | What's stuck and who owns it | `questions.md` | Blockers grouped by owner (client / internal / dev), criticality first, with age |
| Phase progress | "Are we done with phase 1?" answered visually | `phase.json`, registry, exit criteria | Progress against exit criteria, size rollup, remaining work |
| Dependency and overlap graph | Build order and reuse opportunities are seen, not read | Registry edges | Rendered graph (Mermaid) |
| Blocker trend | Evidence the method is working | Historical blocker counts in `phase.json` | Trend chart across phases |
| Activity feed | What happened since last time | `decisions.md`, sources index | Recent decisions, ingested sources, status changes |
| Text digest | Usable in a message or on a bad connection | All of the above | Terse plaintext summary |

**Design Notes:**
- Publishable as a shareable artifact. Build it early — the moment there is a registry, a dashboard makes
  every subsequent skill easier to develop and debug, and it validates the registry schema by consuming it.
- Read-only. Zero writes to state.

**Activation Modes:** Both.

**Tool Dependencies:** None.

**Relationships:** Reads everything, writes nothing.

## Configuration

Collected by `fdw-setup` (generated by CM). Every skill must have a working fallback if a value is unset —
a missing config value degrades behaviour, it never blocks a run.

| Variable | Prompt | Default | Result Template | User Setting |
| --- | --- | --- | --- | --- |
| `discovery_folder` | Where should discovery state live? | `{output_folder}/discovery` | `{project-root}/...` path | No |
| `client_name` | What's the client called? (used in client-facing packets) | project name | string | No |
| `prototype_output_path` | Where should generated prototypes be written? | `{project-root}/prototypes` | path | No |
| `component_library_path` | Where are the project's reusable UI components? (auto-detected if blank) | auto-detect | path | No |
| `prototype_stack` | What should prototypes be built in? | auto-detect from repo, else `html+tailwind` | one of `react+tailwind`, `vue+tailwind`, `html+tailwind`, `next` | No |
| `client_facing_language` | What language do client-facing packets go out in? | `English` | language name | Yes |
| `figma_enabled` | Use the Figma MCP for design import/export? | `false` | boolean | Yes |
| `prd_handoff_skill` | Which skill produces the phase PRD? | `bmad-prd` | skill name | Yes |

Notes:

- `client_facing_language` exists even though the current decision is English everywhere. It costs one line
  and makes a Ukrainian-facing engagement a config change rather than a rebuild.
- `prd_handoff_skill` is configurable so an org with its own PRD skill isn't forced onto `bmad-prd`.
- Phase state is **not** config. Current phase lives in `registry.json` / `phase.json`, because it changes
  during normal operation and config is not a place for moving state.

## External Dependencies

| Dependency | Needed by | Required? | Setup handling |
| --- | --- | --- | --- |
| `bmad-prd` (bmad-core) | `fdw-handoff` | Required | Verify present. Confirmed installed in this environment. |
| Node + a package manager (pnpm detected here) | `fdw-design` | Required for running prototypes | Check availability; warn if absent — prototypes can still be generated, just not run |
| Figma MCP (`mcp__plugin_figma_figma`, present in this install) | `fdw-design`, optionally `fdw-client-packet` | Optional | Only when `figma_enabled`; verify the MCP responds and guide auth if not |
| `uv` | shared BMad scripts (`resolve_config.py`, `memlog.py`) | Required | Already in use by this install |
| Document readers — DOCX / PDF / XLSX | `fdw-intake` | Required in practice | Sales handoffs are rarely markdown. Verify a reader path exists; fall back to asking the BA to convert |

No paid external services. Nothing leaves the machine except through tools the user already has connected.

## UI and Visualization

Four HTML surfaces, all self-contained and publishable as shareable artifacts. This matters more than usual
here: the BA reviews and forwards from his phone, and one of these artifacts is what the client signs.

| Surface | Produced by | Audience | Content |
| --- | --- | --- | --- |
| **Pipeline dashboard** | `fdw-status` | BA | Features × lifecycle board, blockers by owner, phase progress vs. exit criteria, dependency/overlap graph (Mermaid), blocker trend across phases, activity feed |
| **Client review packet** | `fdw-client-packet` | **The client** | Screens, plain-language behaviour description, explicit assumptions to confirm, numbered questions. Zero internal vocabulary. This is the sold artifact. |
| **Consistency report** | `fdw-consistency` | BA | Contradictions with both sides quoted, overlaps with reuse suggestions, dependency cycles, terminology drift, coverage gaps, phase-fit warnings |
| **Pre-flight blocker report** | `fdw-handoff` | BA (and internally, delivery) | Unresolved critical blockers by feature and owner, count vs. previous phases |

Shared requirements: mobile-legible, self-contained (no external assets), theme-aware, and every number on
them traceable to a file in the state store.

The prototypes themselves are a fifth surface but are a work product of `fdw-design`, not a module UI.

## Setup Extensions

Beyond collecting the config table, `fdw-setup` must:

1. **Verify the shared state CLI resolves** at `{skill-root}/../fdw-intake/scripts/fdw_state.py` from
   each installed skill. It ships inside `fdw-intake`; nothing needs installing, but a layout where
   skills are not flat siblings would break every skill at once and is worth failing loudly on.
2. **Scaffold the state store** — create `{discovery_folder}/` with `registry.json` (empty but schema-valid),
   `decisions.md`, `questions.md`, `glossary.md`, `as-built.md`, `sources/index.json`, and `phases/`.
   A half-created store is worse than none; this must be atomic and idempotent.
3. **Initialize phase 1** by calling `fdw-phase` — first init scopes phase 1, per requirement 3.
4. **Detect the prototype environment** — find the component library, infer the stack from the repo,
   populate `prototype_stack` and `component_library_path` so the BA doesn't have to answer questions the
   repo can answer.
5. **Verify dependencies** — `bmad-prd` present, Node available, Figma MCP responding if `figma_enabled`.
   Report what's missing without blocking setup.
6. **Seed the glossary** from the project name and any existing PRD or README found in the repo, so the very
   first intake has terminology to anchor to.
7. ~~Remove broken `fdw-*` symlinks~~ — dropped. This was housekeeping for the aborted attempt,
   which is long cleaned up; on a fresh install there are no broken links, and the generated
   `cleanup-legacy.py` already verifies a skill exists before removing anything.
8. **Offer a first-run walkthrough** — "point me at your first document and I'll run intake" is a far better
   ending to setup than "configuration saved."

Item 7 is specific to this repo; keep it guarded so it never fires destructively elsewhere.

## Integration

**Standalone.** The module delivers value with nothing else installed: raw client input in, source-anchored
feature specs and client-approved designs out, plus a dashboard that makes an engagement legible. Every stage
before handoff is self-contained.

**Where it meets bmad-core:**

- `bmad-prd` — the phase-end target. `fdw-handoff` invokes Create intent with bundle paths as source
  documents. bmad-core owns PRD authoring, its reviewer gate, and its validation rubric; this module owns the
  quality of what goes in. If `bmad-prd` is absent, handoff still produces the bundle and tells the BA what
  to do with it.
- `bmad-spec` — **not** used, despite the name. It distills a five-field machine kernel for downstream
  automation; `fdw-elaborate` writes a client-facing elaboration doc. Different artifacts, different audiences.
  A future integration could feed an approved `fdw` spec into `bmad-spec` to produce the kernel for story
  breakdown, but that is downstream of the PRD and out of scope here.
- `bmad-create-epics-and-stories` — natural next step after the phase PRD exists. Out of scope; the module
  stops at the PRD handoff by design.
- `bmad-ux` / `bmad-agent-ux-designer` — adjacent to `fdw-design`. Check for reusable prompt material during
  build, but do not depend on them: `fdw-design`'s job is prototype-first requirement discovery with
  component reuse, which is a different act from UX specification.
- `bmad-document-project` — useful for bootstrapping `as-built.md` on a brownfield engagement where the
  module arrives mid-project. Worth wiring as an optional setup path.

**Where it deliberately does not integrate:** the module stops at PRD handoff. Epics, stories, sprints, and
development are bmad-core's territory. The seam is the phase bundle, and keeping that seam clean is what
lets bmad-core's future long-term-memory work land underneath this module rather than conflict with it.

## Creative Use Cases

Beyond the primary loop — things the architecture makes possible almost for free:

- **The closing loop.** `fdw-handoff` emits the next call's agenda from unresolved client questions → the BA
  asks them → the transcript comes back through `fdw-intake` → the questions auto-close against the client's
  own quoted words. Discovery becomes a converging process with a measurable convergence rate, instead of an
  open-ended conversation.
- **Scope-creep evidence.** Every requirement is provenance-anchored. "When did this become in scope?" is a
  query, and the answer is a dated quote from the client's own call. On a fixed-price engagement this is the
  difference between absorbing a change and billing it.
- **Estimation rollup.** Sizes plus the dependency graph already exist. A phase-level XS→XL rollup is nearly
  free and turns discovery output into something sales can price. Worth considering for v2.
- **Sales handoff acceptance.** Run `fdw-intake` on whatever sales signed and immediately get the list of
  questions nobody asked. Turns a vague handoff into a concrete gap list on day one of the engagement.
- **Brownfield archaeology.** Reproduce-as-is mode plus `as-built.md` means the module can be pointed at an
  existing undocumented system and used to *recover* a feature registry — the reverse-engineering path Vadim
  described on EasyPay, but structured this time.
- **Second-opinion pass.** `fdw-consistency` run adversarially across a *finished* PRD from another source,
  to find contradictions and coverage gaps before development starts.
- **Onboarding a second BA.** The state store is the engagement. A new BA reads the dashboard and the
  decisions log and is current in an hour — which is the whole answer to "the reasoning died with the sprint."
- **Method evaluation.** The blocker trend across phases is real evidence about whether design-first
  discovery actually works. Vadim named the metric himself; the module can prove or disprove his method.

## Ideas Captured

### Source material

- `docs/ba-skills-discussion.json` — Ukrainian call transcript, 2026-08-22, 10:05–32:05.
  Speakers: Ostap Dribniuk (tech lead / AI enablement — wants the module), Vadim Struk (the BA whose
  method is being captured), Oleksii Rudiuk (minor).
- Ostap's framing brief accompanying the `/bmad-module-builder` invocation.

### The BA's method — verbatim details worth preserving

- **The spec document ("спєка").** Started life as an `ElaborationDoc` the AI proposed — "a rough draft
  where you describe one feature." Vadim then told it: go look at the EasyPay project, compare with the
  spec format we already have, see what's good and what isn't. It produced a hybrid. That hybrid is the
  target artifact.
- **Observed spec structure:** general description / need (problem, outcome) → rules → requirements
  (what it consists of: certification, trainings, course pages, tabs, what happens on each) → comments
  the AI leaves for itself → **open questions, marked critical / non-critical** → contradictions →
  feedback → absent/missing info.
- **No FR IDs at spec level.** In a PRD it'd be "FR-18: you can do X." The spec deliberately stays looser.
  *(Open design question: introduce stable per-feature requirement IDs anyway so PRD assembly is
  traceable? Vadim's reason for avoiding them is churn — the answer may be "IDs, but scoped to the
  feature, minted at approval time.")*
- **The spec is explicitly a sandbox.** "This is my sandbox until I approve it." Updating it must not
  ripple into the PRD or anything else. Only on approval does it become PRD input. This isolation is a
  hard requirement, not an implementation detail.
- **Why the spec exists at all:** the PRD gets polluted ("засмічується") as everyone talks and changes
  their mind. The spec is the same structure as a PRD but simplified and flexible — a contradicting
  requirement arriving tomorrow is cheap to absorb here and expensive to absorb in a PRD.
- **Auto-splitting.** Give it a big feature ("Sessions") and it decides on its own how far to split it
  into separate specs — into "more or less independent, self-contained functional features."
- **Sizing.** Specs get sized XS → XL by effort required. The AI assigns the size and determines the
  **order** the specs should be built in.
- **Dependency reasoning across features.** Real example: the Academy feature is ~90% a repeat of Events.
  Feedback on Events just landed. So: implement the Events feedback first, *then* build Academy on top of
  it — possibly as two separate PRDs. Close all feedback first, then move on. The module must be able to
  reason about this kind of overlap and sequencing.
- **The prototype loop.** Asked it to reproduce an existing page in frontend code, reuse the project's
  components, and build missing components where needed. First pass "had loose ends everywhere"; after it
  extracted and built proper custom components and regenerated the pages, quality jumped and it got very
  fast. Pattern: **reproduce as-is first, then build new features on top of the reproduction.**
- **Real correction example:** agenda blocks were pinned to a calendar time-table so every block had a
  static height and the content inside got squashed. Told it to rework → it introduced sections. "Two or
  three comments to bring it to ideal."
- **The flow-from-scratch trick.** After the main screens existed, Vadim asked: "now draw the flow from
  zero — you've just opened it, there are no sessions, no sections, show me how you'd populate it."
  The AI replied "ah, I goofed, I'm missing something here" — and only *then* produced a proper
  elaboration. **Empty-state / cold-start walkthrough is a deliberate gap-finding technique.** Worth
  making a first-class step, not a happy accident.
- **Mobile / async working style.** Vadim ran a round of this from his phone on a walk — gave the task,
  came back, reviewed on the phone, gave two corrections. The module shouldn't assume a desk session.
- **Client review gate.** Before the client sees anything: scan the screens for obvious mistakes. If clean
  → send to the client, they read it and come back with comments. If those are fine → "now describe this
  with specs."
- **Vadim's own success criterion:** how many unresolved blocker questions surface *at PRD-assembly time*.
  Ideally zero — every blocker should have been closed at spec level. That is the metric this module
  should be built to move, and it should measure it.
- **State of play:** Vadim has not yet produced a single PRD with this method. He is mid-flight. The
  module is being built from a method that is proven convenient but not yet proven end-to-end.

### The memory argument (Ostap) — why folder/state design matters here

- Three tiers: **short-term** = the chat (dies with the chat). **Long-term** = what's written down —
  PRD, architecture. **Mid-term** = the reasoning inside a sprint — "while we developed the sprint we made
  decisions, we argued why we used this and not that, we dropped it and it was all forgotten."
- BMad's original design used only short + long term and hit a wall at "the sprint ends, now what?"
- Long-term memory needs indexing, not bulk loading: "if we have 10 PRDs and it pulls all 10 every time,
  the context is finished."
- Ostap prototyped a wiki-approach project to keep an updated state index; the BMad team say a future
  version will ship long-term memory plus Jira/Confluence integrations and a reworked UI/UX module.
- **Consequence for this module:** it must carry its own durable, indexed state — a registry that is cheap
  to load, per-feature folders that are loaded on demand, and a decision log that survives phase
  boundaries. Nothing important may live only in chat.

### Ostap's explicit asks

- Structure and standardize the method so it runs on workflows — no re-typing rules and templates per run.
- Inputs are declared and understood by the module; the working procedure is fixed.
- Wire up design tooling (Figma MCP was named) so design generation isn't ad-hoc.
- **Folder discipline by phase:** "we're working with phase 1.2 → folder 1.2, dump it there." Cleaner for
  humans, and the AI can navigate the folders and orient itself instead of guessing.
- Context is **outsourcing**: there is a client to sell to. Not an internal project with no human on it.
- Inspiration: Anthropic's record-your-screen-and-get-a-skill feature. Same intent here — take how the BA
  actually works and turn it into a workflow.

### Requirements added in the brief (beyond the transcript)

1. **Inputs are open-ended** — call transcript, WBS, existing PRD, or any document sales passes along.
2. **Any input granularity** — one file may describe one feature, several features, or a whole project.
   The module splits it feature by feature and keeps the resulting features consistent with each other.
3. **Phased delivery is native.** First init scopes phase 1. When every phase-1 feature is specced and
   handed to dev, the BA moves to phase 2 scope inside the same module, with state and context consistent
   across phases.
4. **Phase-end handoff to bmad-core** — the documents this module generates feed `bmad-prd` to produce
   that phase's PRD.

### Early architectural instincts (to be tested in Phase 3)

- A **feature registry** as the single cheap-to-load index: id, title, phase, status, size, dependencies,
  overlap links, paths to its design and spec. This is the answer to Ostap's "don't load 10 PRDs."
- A **feature lifecycle** as explicit status: `candidate → sliced → designed → client-approved → specced →
  spec-approved → handed-off`. Every skill reads and advances it. Makes "am I done with phase 1?" a query,
  not a memory exercise.
- A **decisions log** as the mid-term memory Ostap says BMad drops on the floor — carried across phases.
- **Cross-feature consistency** as its own capability, not a side effect: contradiction detection between
  specs, duplicate-functionality detection (Academy ≈ Events), dependency/ordering graph, phase-fit check.
- **Empty-state walkthrough** promoted to a named gap-finding step in the design loop.
- **Open-questions ledger** aggregated across features, so "what's blocking phase 1?" is one view — and so
  Vadim's success metric (blockers surviving to PRD time) is actually measurable.
- Reproduce-as-is-then-extend as a supported prototype mode for brownfield engagements (EasyPay-style).
- Client-facing review packet as a distinct artifact from internal design notes — different audience,
  different content, and it's what gets *sold*.

### Existing bmad-core surface this module must sit alongside (verified in this install)

- `bmad-prd` — create / update / validate a PRD. Create intent asks for a brain dump *plus existing input
  documents by path*, subagent-extracts them, and binds a run folder. **This is the phase-end handoff
  target**: hand it the phase's approved specs + designs as source paths.
- `bmad-spec` — a *different* thing despite the name: distills intent into a five-field SPEC kernel
  (Why, Capabilities, Constraints, Non-goals, Success signal) for machine consumption downstream.
  Our feature spec is a client-facing elaboration doc, not this kernel. **Naming must not collide.**
- `bmad-agent-analyst`, `bmad-ux`, `bmad-agent-ux-designer`, `bmad-create-epics-and-stories`,
  `bmad-document-project` — adjacent; check for overlap before duplicating.

### Contract amendment made during the fdw-intake build (2026-08-22)

Machine-owned state is **JSON**, not YAML: `registry.json`, `feature.json`, `sources/index.json`,
`phase.json`. The runtime has no PyYAML, and YAML's implicit typing would coerce feature ids, statuses
and dates in precisely the files where that is most dangerous. All prose files are unchanged and stay
markdown. The canonical contract now lives at `skills/fdw-intake/assets/state-contract.md` and is copied
into every store as `CONTRACT.md` at init, so the state store describes itself. Build the remaining
eight skills against that file.

### Contract amendment made during the fdw-design build (2026-08-22)

The shared state CLI lives at **`skills/fdw-intake/scripts/fdw_state.py`** — inside the skill that
owns the contract, so the two ship together. Every other skill reaches it as
`{skill-root}/../fdw-intake/scripts/fdw_state.py`, since installed skills land as flat siblings, and
none bundles a copy.

It briefly lived at `{project-root}/_bmad/fdw/scripts/` during the fdw-design build, mirroring how
BMad ships `memlog.py`. That was wrong for a *module*: the installer only ships the `skills/` tree,
so `_bmad/fdw/` would never have reached a target machine and every skill would have resolved a
missing CLI. A neutral `skills/fdw-shared/` was rejected too — a top-level directory with no
SKILL.md either fails to ship (if the installer enumerates skills by SKILL.md) or registers as a
tenth skill (if it enumerates directories). Living inside a real skill has neither failure mode.

The CLI gained **`feature-set`**, which every downstream skill uses to advance a feature. The
lifecycle gates are enforced there: a forward move cannot skip a stage (`sliced → spec-approved` is
refused and names the stage that has to happen first), backward moves are always allowed because
rework is normal, and `--force` lands in `decisions.md` as an override.

`design/ux-notes.md` is a **contract, not scratch**. `fdw-elaborate` reads it as its primary input
without opening the prototype, so it carries numbered screens `S1..Sn`, assumptions `A1..An` tied to
screens, and an append-only dated corrections log. `design/empty-state.md` carries gaps `G1..Gn`.
The spec cites those ids, which is what makes a requirement traceable back to the screen that
produced it.

### Housekeeping found in the repo

- A previous aborted attempt used module code `fdw` ("fdw-agent-ba, fdw-client-packet, fdw-design,
  fdw-intake, fdw-prd, fdw-setup, fdw-spec, fdw-status"). Only **broken symlinks** in `.claude/skills/`
  and empty `_bmad/fdw/scripts/tests/` dirs survive — the `skills/` payload was deleted, git has no
  commits, so nothing is recoverable. Notable: that attempt converged on nearly the same decomposition.
  These stale symlinks should be cleaned up before or during build.

## Build Roadmap

Ordered by dependency and by earliest usable value. The registry schema is the foundation — it is defined by
the first skill built and consumed by the second, which is deliberate: schema mistakes surface immediately
rather than after six skills have baked them in.

| # | Skill | Builder | Why here |
| --- | --- | --- | --- |
| 1 | `fdw-intake` | Workflow Builder | Nothing exists until features are in the registry. This skill defines `registry.json`, `feature.json`, `signal.md`, and the provenance format — the contracts everything else depends on. Highest-risk, highest-leverage, so it goes first. |
| 2 | `fdw-status` | Workflow Builder | Cheap, read-only, and it validates the registry schema by consuming it. From here on, every subsequent skill is debuggable by looking at a dashboard instead of reading YAML. |
| 3 | `fdw-design` | Workflow Builder | The method's core inversion. Needs `signal.md` from intake. Deliver it early — it is where the BA feels the difference first. |
| 4 | `fdw-client-packet` | Workflow Builder | Completes the design→client→approval gate that `fdw-elaborate` depends on. Short, and it makes the design loop end somewhere real. |
| 5 | `fdw-elaborate` | Workflow Builder | The payload artifact. Requires approved designs to exist, so it lands after the gate is closeable. |
| 6 | `fdw-consistency` | Workflow Builder | Needs several specs to be meaningful. Build once there is real material to audit — testing it against fabricated specs proves nothing. |
| 7 | `fdw-phase` | Workflow Builder | Phase mechanics are only exercisable once a phase has content worth closing. |
| 8 | `fdw-handoff` | Workflow Builder | Terminal stage; depends on 5, 6, and 7. |
| 9 | `fdw-agent-ba` | Agent Builder | **Last.** Its activation contract depends on the final registry and questions shapes, and its routing needs all eight workflows to exist. |
| 10 | Module scaffold | **Create Module (CM)** | Generates `fdw-setup` and the module infrastructure. Then hand-add the Setup Extensions listed above. |
| 11 | Validation | **Validate Module (VM)** | Confirm every skill is registered, entries are accurate, structure is sound. |

### Build status — 2026-08-22

All nine skills are built, tested and symlinked into `.claude/skills/`. 215 tests pass across the
module. Every skill was evaluated end to end against the real transcript-derived store rather than a
fixture, and each eval found at least one defect that the unit tests had not.

| # | Skill | Tests | Notes |
| --- | --- | --- | --- |
| 1 | `fdw-intake` | 59 | Defines the contract, and ships the shared state CLI every other skill calls. |
| 2 | `fdw-status` | 19 | Read-only by construction. |
| 3 | `fdw-design` | 18 | Templates rewritten so boilerplate cannot satisfy the gate. |
| 4 | `fdw-client-packet` | 28 | Vocabulary gate refuses internal terms in a client document. |
| 5 | `fdw-elaborate` | 22 | Mints stable requirement ids at approval; refuses on open blockers. |
| 6 | `fdw-consistency` | 22 | Overlap scoring switched to the overlap coefficient. |
| 7 | `fdw-phase` | 12 | Phase mechanics live in the shared CLI. |
| 8 | `fdw-handoff` | 27 | Cross-phase dependency lookup fixed during the eval. |
| 9 | `fdw-agent-ba` | 9 | Memory agent, named Vadim, four internal capabilities. |

**Packaging complete (2026-08-23).** CM scaffolded `fdw-setup` with `module.yaml` (8 config
variables, one-agent roster) and a 16-capability `module-help.csv`; the five Setup Extensions above
were hand-added. VM returns zero structural findings. Full report:
`skills/reports/module-validation-fdw-2026-08-23.md`.

**Distribution (2026-08-23).** Two separate channels, which are easy to confuse:

- **`bmad install`** discovers a custom module by recursively scanning the project root for a
  `module.yaml`, skipping any dot-directory plus `node_modules`, `dist`, `build`, `.git`, `bmad`,
  `src/`, `tools/` and `test/`. Ours sits at `skills/fdw-setup/assets/module.yaml`, so the module has
  been discoverable since CM ran — verified by calling the installer's own `CustomHandler.findCustomContent`
  against this project, which returns exactly that one path. **`.claude-plugin/` is never read by
  `bmad install`**: the scanner skips directories beginning with a dot, and `marketplace.json` is not
  a filename it looks for.
- **The Claude Code plugin marketplace** reads `.claude-plugin/marketplace.json`. That file now exists
  at the repo root, registering all ten skills against the `Relevant-S/bmad-fdw` remote, following the
  schema `scaffold-standalone-module.py` emits with `skills` extended to a list for a multi-skill module.

`license` is deliberately empty. The repo declares ISC in a default `package.json`, which is npm
boilerplate rather than a decision anyone made, and choosing a licence is not a call to make on
someone's behalf. Fill it before publishing.

**Validation milestone — build this test into the process.** After step 5, run the whole chain on the real
`docs/ba-skills-discussion.json` plus a real client artifact, and check the two things the transcript says
matter: (a) does the Academy≈Events overlap get detected and correctly ordered, and (b) how many critical
blockers survive to `fdw-handoff`. Vadim named the second one as his own criterion. If the module can't move
that number, it hasn't earned the switch from his manual method.


### Grounding pattern added to fdw-design (2026-08-23)

Run on a real brownfield engagement, `fdw-design` produced a prototype that shared the client's palette
and nothing else: a single hand-written HTML file, 914 lines, 25 transcribed hex values, zero real
components, and an invented navigation shell implying five features nobody had scoped. The notes were
good — screens correctly marked as-is, real source files cited — which is what made it worth diagnosing
rather than regenerating. Six causes, all in the skill:

1. **Config was write-only.** Setup collected `component_library_path`, `prototype_stack`,
   `prototype_output_path` and `project_stage`; no skill read any of them at design time.
2. **A failed search reported itself as a verdict.** `inventory` searched a fixed candidate list under
   the project root, found nothing because the application was a sibling directory, and returned
   `greenfield: true` — which the skill described as "a normal answer, not a failure".
3. **The inventory was too thin to ground anything.** A list of component names, no tokens, no layout
   convention, no example of how a page in this product is composed. Stack detection read only the root
   manifest, so every monorepo reported no framework.
4. **The skill contained an unresolved contradiction** — reuse the real components, *and* produce
   something the BA can open by double-clicking on a phone. The model resolved it silently toward
   portability and rebuilt every primitive from memory.
5. **The gate could not see fidelity.** It counted files, assumption ids, dated corrections and gaps.
   All four passed. Nothing anywhere compared the output to the real product.
6. **Nothing stated the boundary**, so the model supplied one. Drawing a screen needs something around
   it; with no rule, it built the surroundings.

The fix is a pattern, not a special case, and it is deliberately stack-agnostic — every rule keys off
what the project turns out to have rather than off any named framework:

- **A discovery ladder that cannot end in a guess.** Config first, then auto-detect, then widen to the
  parent and siblings (BMad in `docs/` with the app beside it is the common case, not a quirk), then ask
  the BA. `inventory` now returns `verdict: "not_found"` and never claims greenfield; greenfield is a
  state the BA confirms by name in `grounding.json`.
- **The fidelity kit instead of a name list** — stack with per-app run commands, components, token
  source files, and real pages ranked by archetype (list, form, dialog, detail, empty). The reference
  page is the highest-value item: it carries shell, spacing, table style and empty state already correct.
- **Clone, then change.** Take the nearest real page of the same archetype and change only what the
  feature changes. Copy the token file verbatim; retyping it is what produces right colours and wrong
  everything else.
- **`design/grounding.json`**, a machine-checked record of where each screen came from. `check` verifies
  every claim against the filesystem: cited paths exist, the copied token file hashes equal to its
  original, each screen's styling vocabulary overlaps the page it cites, no undeclared screen is present,
  chrome is borrowed from a named layout file or absent. Against the failing artifact the overlap metric
  scored 1.6% on all three cited sources and counted 103 hand-authored CSS rules.
- **The contradiction is resolved by ranking.** Fidelity outranks portability; phone review is served by
  running the real app beside the prototype, not by degrading the artifact.
- **The prototype never writes into the application's source tree** (decided with the user). It lives at
  `prototype_output_path`, adds files only, and is deletable — so grounding is achieved by extraction,
  never by importing across a build boundary.

Where a project has no shared class vocabulary at all — CSS modules, styled-components — the overlap
metric reports `null` rather than a score, and the required side-by-side comparison carries the weight.
A check that cannot measure says so instead of passing.

`references/grounding.md` is the authority; `references/brownfield.md` now loads on a signal
(`project_stage`, a non-empty `as-built.md`, or a feature that changes shipped behaviour) rather than on
the model's judgement, which is why the reproduce-as-is discipline was optional in practice.

### Capture and the response loop added to fdw-client-packet (2026-08-24)

Two defects in how a good packet got produced, reported from a real engagement.

**Capture was improvised.** The script accepted `--screenshot label=path.png` and had no opinion on
where the PNGs came from, so the run reached for whichever browser-automation MCP happened to be
installed locally. A BA without it gets a different packet or none — unacceptable for the one
artifact a paying client actually sees.

The fix is a capture harness that ships with the module, `scripts/fdw_capture.py`, with no
dependency the BA has to install:

- **Served, not opened.** The prototype goes over loopback HTTP from the stdlib, because `file://`
  resolves relative assets differently and would quietly produce a different packet.
- **Whatever browser is already there.** Chrome, Chromium, Edge or Brave, found through a documented
  search order with `CHROME_PATH` as the override, driven over the DevTools protocol through a
  WebSocket client written out in ~60 lines of stdlib. No npm, no MCP, no third-party package.
- **The capture list is not a judgment call.** `grounding.json` declares the feature's screens and
  `fdw-design` already refuses to let an undeclared one exist, so the capture list and the feature
  boundary are the same list. Screens sharing a file are clipped to their own region; a screen with a
  file to itself is taken whole, so a borrowed shell stays in the picture.
- **Fixed optics** — 1280×900, device scale factor 2, `captureBeyondViewport` so a long screen is
  captured whole rather than cropped at the fold.
- **No browser is a stated outcome**, not a silent one: the packet still renders and describes the
  screens, and the skill must say so rather than implying pictures exist.

**There was no defined way for the client to respond.** Two mechanisms were weighed — a reply built
into the HTML packet, and a Figma node published through the Figma MCP with a comment sync. Figma
wins parallel commenting decisively and loses everything else:

| | HTML packet | Figma node |
| --- | --- | --- |
| BA setup | none — it is the file already being sent | account, MCP configured and authenticated, a file per engagement |
| Non-technical client | reads as a document, answers inline | a designer's canvas, sign-in required to comment |
| Parallel stakeholders | each replies separately, merged on ingest | live and shared |
| Response fidelity | every answer arrives bound to its question | free text at canvas coordinates, bound to nothing |
| When unavailable | cannot be — it is the artifact | breaks at the client, mid-review |

Two things decided it. Figma would have reintroduced the exact defect being fixed in the capture
half — a leg of the workflow depending on whichever MCP happens to be installed — except on the
client's side of the engagement, where it cannot be recovered. And a comment pinned to a canvas
needs an LLM judgment call to become "this question is answered", which throws away the provenance
the whole module is built on.

The round trip, chosen and built:

- **Out.** The packet carries agree/not-quite per assumption, an answer box per question, a name, and
  one *are these screens right* control. Answers persist in the client's own browser as they type.
  Finishing produces a copyable block — copy-paste into an email removes the attachment barrier
  entirely — plus a plain-language summary of what they are sending. The page reaches nothing on the
  network and submits nothing on its own.
- **Opaque tokens.** The reply travels labelled `q1`, `a2`. No internal id is ever in the client's
  hands, not even inside the block. The `.map.json` sidecar, already internal-only, becomes the join
  table.
- **In.** `sync` takes one reply per stakeholder — pasted block, downloaded file, or that block buried
  in an email — files them beside the packet so every quote traces to something on disk, and emits
  `question-close` commands carrying the client's own words as the quote.
- **Conflicts are reported, never resolved.** Two stakeholders answering differently leaves the
  question open with both answers named. A script picking one would be inventing a client decision.
- **Disagreed assumptions are corrections**, routed back to `fdw-design`, not closed questions.
- **Sign-off is withheld** until every question asked has an answer, nothing is in conflict, and
  somebody actually said yes. Silence is not sign-off, and one *not yet* holds the feature.
- **`sync` writes no feature state**, in keeping with the single-writer rule; it emits the commands.

One defect found in build and worth remembering: the reply script's `join('\n')` was written into a
non-raw Python string, so the rendered page carried a real newline inside a JS string literal — a
syntax error that kills the whole reply block silently, in the client's browser, where nothing
upstream would ever notice. The loop is now tested against a real headless browser end to end: fill
the form, click Finish, read the block, sync it back.

### Layout correction: packets moved into the feature folder (2026-08-24)

Packets were written to `phases/<phase>/client-packets/`, a flat folder at the root of the phase.
Asked to justify it, there is no justification. A packet is built from a single feature entry —
`gather`, `render` and `sync` all take one `--id`, the output path was derived from that entry's own
phase, and the sidecar map records one feature. It was never a multi-feature artifact.

The flat folder came from this plan's own layout sketch, placed beside `handoff/` by symmetry.
`handoff/` genuinely is phase-level: it bundles every feature in the phase. `client-packets/` copied
that shape without having that property, and the result split one feature's artifacts across two
locations while its design and spec sat together in a third.

Packets now live at `phases/<phase>/features/<F-NNN-slug>/client-packets/`, with the id map and the
filed replies beside them. Two things were preserved rather than dropped:

- **The phase-wide view.** `gather` still reports every packet sent in the phase, now as
  `packets_this_phase` gathered by glob, alongside this feature's own `prior_packets`. The useful
  question — what has this client already been sent — did not depend on the flat folder.
- **Stores built before the move.** `sync` reads the feature folder first and the old phase-level
  folder second. A client who has already been sent a packet is owed a working reply path, and a
  layout correction is not a reason to strand one.

Found alongside it: `gather` hardcoded the prototype at `design/prototype` while `fdw_design` and
`fdw_capture` both resolve `prototype_dir` from `grounding.json`. Any feature whose design put the
prototype elsewhere was reported as having no prototype at all, and the packet refused to build.
All three now resolve it the same way.

**Next steps:**

1. Build each skill using **Build an Agent (BA)** or **Build a Workflow (BW)** — share this plan document as context
2. When all skills are built, return to **Create Module (CM)** to scaffold the module infrastructure
