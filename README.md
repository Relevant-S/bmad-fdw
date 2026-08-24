# Feature Discovery Workflow (fdw)

A toolkit for business analysts working with clients. It takes the messy things a client gives you — a recording of a call, a spreadsheet of work items, an old requirements document, whatever sales forwarded — and turns them into clear, approved feature specifications, ready to hand to developers.

You do not need to be a developer to use it. You type in plain English. It does the filing.

---

## 1. What this is, and the problem it solves

### The problem

You get on a call with a client. They describe what they want. You take notes.

Then it happens again next week, and they contradict themselves. A spreadsheet arrives from sales with different wording for the same thing. Three months later a developer asks "who asked for this?" and nobody can say. At the end, you write a big requirements document, and half the things in it were never really agreed.

Two things go wrong over and over:

1. **The written document comes too early.** You describe the feature in words, the client nods, and then you build it and they say "that's not what I meant." Clients cannot picture a paragraph. They can react to a screen.
2. **The reasoning disappears.** Decisions get made on calls and lost. Nobody remembers why a thing works the way it does, so it gets re-argued.

### What this does instead

It turns the usual order around. **You show the client pictures first, get their agreement, and write the specification afterwards.**

The full path looks like this:

```
messy client input  →  a list of features  →  a working prototype
                    →  client says yes  →  a written spec
                    →  a requirements document for developers
```

And it keeps a record. Every single requirement it writes down can be traced back to the moment someone actually asked for it — the exact sentence, from the exact call, on the exact date. When a client says "we never asked for that," you can show them.

### What you get out of it

- **Features, separated out.** One transcript that rambles across five topics becomes five clearly-separated features.
- **Prototypes** the client can look at and react to, built to look like their real product.
- **A review document** for the client, written in their language, with no internal jargon in it.
- **A specification per feature**, with every requirement traceable to its source.
- **A requirements document (PRD)** per delivery phase, handed to the developers.
- **A record of every decision**, that survives from one phase to the next.

### One term you will see everywhere

A **feature** is one deliverable thing — "Course list", "Certification", "Session scheduling". Each one gets an ID like `F-001` and its own folder. That ID never changes, even if the feature moves to a later phase. That is how nothing gets lost.

---

## 2. Installation

### Before you start

You need two things on your computer:

| Thing | What it is | How to check |
| --- | --- | --- |
| **Node.js** | Runs the installer | Type `node --version` in a terminal |
| **uv** | Runs the toolkit's Python parts | Type `uv --version` in a terminal |

If `uv` is missing, the simplest fix is to ask your AI assistant: *"install and set up uv for me."*

### Installing

Open a terminal, go to the folder for your client project, and type:

```
npx bmad-method install
```

You will be asked a series of questions. Here is what to answer:

1. **Install to this directory?** → **Yes** (make sure it is the right client project)
2. **How would you like to proceed?** → **Install** (or **Modify BMAD Installation** if BMAD is already there)
3. **Select official modules to install** → keep **BMad Method** selected. That one is required — this toolkit hands its finished work over to it.
4. **Do you want to install custom or community modules (Git URL or local path)?** → **Yes**
5. **Git URL or local path** → paste:

   ```
   https://github.com/Relevant-S/bmad-fdw
   ```

6. You will see a warning: **UNVERIFIED MODULE: This module has not been reviewed by the BMad team.** This is expected. It appears for anything not published by BMAD themselves. Continue.
7. It will find **Feature Discovery Workflow v1.0.0**. Confirm.

### After installing

Run the setup once:

> **"setup Feature Discovery Workflow"**

It will ask you a handful of questions — where to keep your files, what the client is called, and so on. Every question has a sensible default, so *"accept all defaults"* is a perfectly good answer the first time.

One question is worth reading properly: **"Is this a new build, or a project already partway through delivery?"**

- **New build** (the default) — setup creates your working folder and opens phase 1. Done.
- **Already in flight** — it asks which phase the project is actually on, and whether you have anything describing what is already live. See *[Starting on a project that is already running](#starting-on-a-project-that-is-already-running)*.

Either way, you can start immediately after setup finishes.

---

## 3. The workflow, start to finish

Here is the whole path, with what you actually type.

```mermaid
flowchart TD
    A["Client input<br/>transcript · WBS · old PRD · email"] --> B["INTAKE<br/>split into features"]
    B --> C["DESIGN<br/>build a prototype"]
    C --> D["CLIENT PACKET<br/>they review and sign off"]
    D -->|"changes wanted"| C
    D -->|"approved"| E["ELABORATE<br/>write the spec"]
    E --> F["CONSISTENCY<br/>do the features agree?"]
    F --> G["HANDOFF<br/>bundle + PRD for developers"]
    G --> H["PHASE<br/>close this one, open the next"]
    H -.->|"next phase"| B
```

### Step 1 — Intake: get it into the system

**You type:**

> "New call came in. Here's the transcript: `docs/calls/academy-2026-08-22.json`"

**What comes back:** it reads the file, pulls out the features being discussed, and shows you a list.

> I found three features in this call:
> - **Academy** — certification, trainings and course pages
> - **Events agenda layout** — blocks are squashed, needs sections
> - **Session list improvements** — client feedback on Events
>
> Shall I record these?

You say yes, or you correct it. It writes each feature into its own folder, along with the exact quotes that justify it.

The file does not need to be tidy. It handles recordings in any language, including messy automatic transcriptions.

### Step 2 — Design: show them a picture

**You type:**

> "Draw me the Academy feature"

**What comes back:** a working prototype — real screens, built using your project's actual look and feel. Along with it, a list of the assumptions it had to make.

> Built two screens: Course list and Course page.
> Three things I assumed, which nobody has confirmed:
> 1. A course can be published before any dates are scheduled
> 2. Certification only unlocks when every session is complete
> 3. Courses are listed newest first

You walk the screens and correct them:

> "The date field should take a range, not one day. And the tabs are squashed."

It fixes them, and — importantly — **writes down what you corrected**. Those corrections are requirements nobody had written down yet. That is where a lot of the real detail comes from.

Then it does one more thing automatically: it walks through the screens as if nothing exists yet. No courses, no data, empty. This catches the steps everybody forgets, like "how does the very first course get created?"

### Step 3 — Client packet: get sign-off

**You type:**

> "Send it to the client"

**What comes back:** a single self-contained web page you can email. It has the screens, a plain-language description, the assumptions phrased as questions they can answer, and a short list of what you need from them.

It will **refuse** to include any internal wording — no feature IDs, no sizing, no words like "spec" or "backlog". If any of that has crept in, it tells you which sentence to rewrite.

When the client replies:

> "The client came back on Academy — they're happy, but certification needs a downloadable PDF."

It records their answer, in their words, and marks the design approved.

### Step 4 — Elaborate: now write it down

**You type:**

> "Write the spec for Academy"

**What comes back:** the full written specification. What the problem is, the rules, every requirement, what is deliberately out of scope, what is assumed, and what is still unanswered.

Every requirement carries a note saying where it came from — either a quote from a call, or a design decision the client signed off on.

When you are happy:

> "Approve the spec"

It will **stop you** if any critical question is still unanswered, and tell you which ones. That is deliberate. An unanswered question at this stage becomes an expensive problem later.

Once approved, each requirement gets a permanent ID like `F-001-R-03`, which never changes.

### Step 5 — Consistency: do the features agree with each other?

**You type:**

> "Do these features conflict?"

**What comes back:** a report. Two features that contradict each other. Two features that are secretly the same feature. Features that depend on each other, and therefore the order they should be built in.

> Academy repeats most of the Events agenda. Don't merge them — Academy adds enrolment and certification that Events has no concept of. But build Events first, because Academy inherits its agenda.

### Step 6 — Handoff: give it to the developers

**You type:**

> "We're done with phase 1, make the PRD"

**What comes back:** first, a check. How many unanswered questions would go to the developers? Which features are not ready? What is missing?

> 4 features ready, 12 requirements, 0 unanswered critical questions.

Then it packages everything up and produces the requirements document (PRD) that developers work from.

It also writes you an **agenda for your next client call** — the questions still outstanding. When you have that call and feed the recording back in, those questions get closed automatically. The loop closes itself.

### Step 7 — Phase: move on to the next round

**You type:**

> "Close phase 1 and scope phase 2"

Everything unfinished carries forward. Nothing is lost. See section 6.

### If you would rather not remember any of this

Just type:

> **"Talk to Vadim"**

Vadim is the assistant built into this toolkit. He reads where everything stands and tells you what to do next. You can describe what you want in your own words and he picks the right tool.

---

## 4. The tools, one by one

There are nine. You rarely need to remember their names — describing what you want usually works.

---

### `fdw-setup` — install and configure

**What it does.** Sets the toolkit up in a project. Asks where to keep files, what the client is called, and where your project's design components live. Creates your working folder and opens phase 1.

**When to use it.** Once, after installing. Again if you want to change a setting.

**Say:** *"setup Feature Discovery Workflow"* · *"configure fdw"*

**Writes:** your settings, and an empty working folder ready to use.

**Example.** You run it, accept the defaults, and it replies that the discovery folder is created and phase 1 is open.

---

### `fdw-agent-ba` — Vadim, your starting point

**What it does.** Reads everything and tells you where you stand. Routes you to the right tool without you naming it. Makes small corrections on the spot.

**When to use it.** When you sit down and cannot remember where you left off. Or when you do not want to think about which tool you need.

**Say:** *"talk to Vadim"* · *"where are we"* · *"what's blocking"* · *"what should I do next"*

**Reads:** the feature list, open questions, recent decisions.
**Writes:** small corrections, and notes about how you like to work.

**Example.**

> **You:** where are we
>
> **Vadim:** Phase 2: 3 features, Academy specced and bundled, Events feedback shipped. Nothing blocked on the client. F-004 has no design and two features are waiting on it.

He never guesses. If he has not read something, he says so.

---

### `fdw-intake` — get client input into the system

**What it does.** Reads any document and pulls out the features. Splits one messy file into separate features. Recognises when a feature already exists and adds to it instead of duplicating. Notices when new input contradicts something you already recorded. Closes questions that the new document answers.

**When to use it.** Every time anything arrives — a call recording, a spreadsheet, an email, an old requirements document.

**Say:** *"new call came in"* · *"ingest this transcript"* · *"run intake on this WBS"* · *"process this handoff"* · *"check the discovery store"*

**Reads:** the file you give it, plus what is already recorded.
**Writes:** a folder per feature, with the evidence and quotes behind it.

**Example.** You hand it a 30-minute call recording. It comes back with three features, twelve pieces of evidence with timestamps, and five questions the client needs to answer.

---

### `fdw-design` — build the prototype

**What it does.** Builds working screens for one feature, using your project's real components so it looks like the actual product. Records every assumption it makes. Takes your corrections and logs them. Walks the empty starting state to find missing steps.

**When to use it.** After intake, before you talk to the client again. This is the step that saves the most time.

**Say:** *"draw me this"* · *"prototype this feature"* · *"design F-003"* · *"reproduce the current screens"* · *"show me what this looks like"*

**Reads:** the evidence for the feature, and your project's real code.
**Writes:** the prototype, the assumptions, the corrections log, the empty-state findings, and a record of where each screen was copied from.

**Example.** You ask for the Academy screens. Two rounds of corrections later they are right, and the empty-state walk has found three steps nobody had thought about.

**How it gets the look right.** On a product that already exists, it does not draw from imagination. It finds your application, finds the page most like the one it needs, and copies that as the starting point — the same colours, the same spacing, the same table style, because they are the same file. Then it changes only the part your feature changes.

Before you see anything, it checks its own work: every screen has to name the real file it came from, and that file has to exist. If it drifted into inventing its own look, the check fails and it starts again. You should be correcting the feature, not the drawing.

**It stays inside one feature.** One run, one feature. It will not build the rest of your app around it, and it will not invent a navigation menu — if the screens need a frame around them, it borrows your real one. Anything it draws that belongs to a different feature is treated as a mistake and blocked.

**If it cannot find your application**, it will ask you where it lives rather than guessing. Tell it once and it remembers. It only starts from a blank page if you tell it there is genuinely nothing there yet.

---

### `fdw-client-packet` — the document the client signs

**What it does.** Builds a single web page for the client: pictures of the screens, a plain description, the assumptions as yes/no questions, and what you need from them. The client answers in the page itself and sends the answers back. Then it reads those answers in and records the sign-off.

**When to use it.** When the prototype is ready to show. And again when they reply.

**Say:** *"send this to the client"* · *"build the client packet"* · *"prepare the review"* · *"the client came back on Academy"*

**Reads:** the prototype and the assumptions.
**Writes:** the client page, the screenshots, and their recorded answers and approval.

**Example.** It produces one file you can email. It refuses to send anything containing internal wording, and tells you exactly which sentence to change.

**The pictures.** It takes the screenshots itself, using a browser you already have — you never take them by hand. Every screen in the feature, always the same size, always the whole page rather than just the top of it. Two people building the same packet get the same pictures. If there is no suitable browser on your machine it says so, and the packet describes the screens instead of showing them.

**How the client replies.** Under each question there is an answer box; next to each assumption, *That's right* / *Not quite*. At the end they type their name and say whether the screens are right. Their answers save as they type, so they can start on a phone and finish later.

When they press **Finish**, the page gives them a block of text to copy into their reply email — or a file to download if they prefer attachments. It also shows them, in plain words, exactly what they are sending. The page never sends anything anywhere by itself, which is worth saying to them: it is safe to open and it is not tracking them.

**Several people can answer.** Send the same file to as many stakeholders as you like. Each one replies separately, and you feed all their replies in together. You get one merged picture with each answer attributed to whoever gave it.

**When two people disagree**, it will not choose for you. It shows you both answers side by side and leaves that question open. Guessing which stakeholder to believe is exactly the mistake that ends up in a spec.

**Sign-off is not offered until it is real** — every question you asked has an answer, nothing is in conflict, and someone actually said yes. If it is holding back, it tells you which of those is missing.

---

### `fdw-elaborate` — write the specification

**What it does.** Writes the full spec for one feature from the approved design. Sizes it. Records what depends on what. Sorts the open questions into "must answer" and "can wait". Locks the requirement IDs when you approve.

**When to use it.** After the client has approved the design. Not before — that ordering is the whole point.

**Say:** *"write the spec"* · *"elaborate F-003"* · *"спєка"* · *"now describe this properly"* · *"approve the spec"*

**Reads:** the approved design, the corrections log, the original evidence.
**Writes:** the specification.

**Example.** Ten requirements for Academy. Two trace back to quotes from the call; eight trace back to design decisions the client signed off. Approving is blocked until two client questions are answered.

**Note.** Until you approve it, the spec is a scratchpad. Change your mind freely — nothing downstream is affected. That is deliberate.

---

### `fdw-consistency` — check the features against each other

**What it does.** Finds contradictions between features, spots two features that are really one, works out the build order, catches the same thing being called three different names.

**When to use it.** After intake adds new features. Before any handoff. Any time you are unsure whether things hang together.

**Say:** *"check consistency"* · *"do these features conflict"* · *"run the audit"* · *"what order should we build these"*

**Reads:** every feature and spec.
**Writes:** a report, plus the recorded relationships between features.

**Example.** It reports that Academy repeats most of Events, recommends building Events first, and notices that Academy was approved ahead of the two features it depends on.

---

### `fdw-phase` — manage delivery rounds

**What it does.** Decides what goes in the next phase. Moves features between phases without losing anything. Closes a phase and opens the next one, carrying unfinished work across.

**When to use it.** When scoping a round of work, when something slips, and at the end of every phase.

**Say:** *"scope phase 2"* · *"move this to the next phase"* · *"close phase 1"* · *"are we done with this phase"* · *"show me the phases"*

**Reads:** every feature, its size, and what depends on what.
**Writes:** phase records, and a report of the whole engagement.

**Example.** It proposes phase 2, notes that two features must move together because they depend on each other, and warns you that phase 1 cannot close yet because one feature is unfinished.

---

### `fdw-handoff` — give it to the developers

**What it does.** Checks what is ready. Counts the unanswered questions that would reach developers. Bundles the approved specs. Produces the requirements document. Writes the agenda for your next client call.

**When to use it.** At the end of a phase.

**Say:** *"hand off phase 1"* · *"we're done, make the PRD"* · *"bundle these specs"* · *"run the pre-flight"*

**Reads:** every approved spec in the phase.
**Writes:** the bundle, the PRD, and the next call's agenda.

**Example.** Pre-flight says 4 features, 12 requirements, 0 unanswered critical questions. It bundles them and produces the PRD. It will warn you loudly about unanswered questions, but it will not stop you — that call is yours.

---

## 5. Where your documents live

Everything goes in one folder, by default `_bmad-output/discovery/` inside your project.

```
discovery/
├── registry.json         The master list of every feature and where it stands
├── decisions.md          Why things are the way they are. Never deleted.
├── questions.md          Every open question, grouped by who owes the answer
├── glossary.md           Your project's vocabulary
├── as-built.md           What has actually shipped so far
│
├── sources/              Every document you fed in, kept exactly as received
│
└── phases/
    ├── phase-1/
    │   ├── features/
    │   │   └── F-001-academy/
    │   │       ├── signal.md      The evidence and quotes behind this feature
    │   │       ├── design/        The prototype and the design notes
    │   │       ├── spec.md        ← the specification
    │   │       └── changes.md     Changes raised after approval
    │   ├── client-packets/        ← the pages you sent the client
    │   └── handoff/               ← the bundle and the next call's agenda
    └── phase-2/
```

### The three files you will actually open

| File | What it is for |
| --- | --- |
| `spec.md` inside a feature folder | The specification. This is the main output. |
| `client-packets/*.html` | What you emailed the client. Open it in a browser. |
| `decisions.md` | Why anything is the way it is. Search this when someone asks. |

### The one file not to edit

`registry.json` is the master index. The toolkit keeps it in step with the folders automatically. If you edit it by hand they can fall out of step. If you think they have, say *"check the discovery store"* and it will tell you exactly what is wrong.

### How a feature moves along

Each feature has a status showing how far it has got:

```
candidate → sliced → designing → client-review → design-approved
          → speccing → spec-approved → handed-off → shipped
```

You do not need to memorise this. Two rules are worth knowing, because the toolkit enforces them:

- **A spec cannot be written until the client has approved the design.**
- **A feature cannot go to developers until its spec is approved.**

---

## 6. How phases work

A **phase** is one round of delivery — a chunk of work the client buys, developers build, and ships. Then you start the next one.

### Phase 1

Setup opens phase 1 for you. Everything you take in lands there by default. You work through the features, hand them over, and close it.

### Starting on a project that is already running

Most real work is not a fresh start. You get handed a project that has been going for months and is on its third round of delivery.

Tell setup it is **already in flight**, and it asks two things.

**Which phase is the project actually on?** Answer in whatever form is natural — `3`, `phase-3`, or a fractional one like `2.1` if you are mid-way through a split phase. That becomes your starting phase, instead of phase 1.

**Is there anything describing what already exists?** A previous requirements document, a handover note, or just a couple of sentences typed into the chat. Any of those work, and "nothing" is a fine answer too.

Whatever you give it goes into the **as-built baseline** — the record of what is already live. That is what the prototype tool reads when you ask it to rebuild an existing screen, and what the spec tool checks so it does not re-specify something that already exists.

**What it will not do is invent the earlier phases.** If you start at phase 3, phases 1 and 2 simply are not in the system. That is deliberate. This toolkit's firmest rule is that it never reports anything it has not actually read, and creating two empty "completed" phases it knows nothing about would break that — and would make the unanswered-question trend meaningless, which is the one number worth watching.

So the phase history starts where you started. What came before lives in the as-built baseline, clearly marked as something you told it rather than something it verified.

Everything else behaves normally. Open phase 4 next, or go back and add phase 2 later if you need to — it always works out which phase comes before which from the number itself, not the order you created them in.

### Handing over and moving on

When phase 1 is done:

1. **Anything slipping to later, mark it now** — *"move Academy to phase 2"*. Do this **before** closing, or the reason it slipped will not carry across.
2. **Close phase 1** — it records how many questions were still unanswered, and links the PRD.
3. **Open phase 2** — everything unfinished comes with it.

### What carries across

- **Unanswered questions.** Still open, still assigned to whoever owes the answer.
- **Deferred features.** They **move**, keeping their ID, their evidence, their prototype, their spec, and the client's sign-off. Nothing is recreated from scratch.
- **Open change requests.** Things raised after a spec was approved.
- **The decisions log.** Every "why", from the beginning.
- **What has shipped.** So phase 2 features are written against what actually exists, not against a pile of old documents.

That is why a feature deferred from phase 1 to phase 2 still knows, months later, that the client approved its screens in August.

### Sub-phases

If you split a round, `phase-2.1` works exactly the same way.

### The number worth watching

Every time you close a phase it records **how many critical questions were still unanswered** at handoff. Watch that number across phases. If it is falling, this is working. If it is rising, questions are not getting chased and the phase reports will show it.

---

## 7. Troubleshooting and FAQ

### "No discovery store" / "Run fdw-intake first"

The working folder does not exist yet. Either run setup, or just feed it your first document — intake creates the folder itself.

### "moving sliced → client-review skips designing"

You are trying to jump a step. Each stage is a gate. Do the missing step first, or, if the work genuinely happened elsewhere, say so and it will let you past while recording that you skipped.

### It refuses to approve my spec

There are unanswered critical questions. It will name them and say who owes each answer. Chase them, or approve anyway with *"approve it, I accept the open blockers"* — it records what was let through.

This refusal is the most valuable thing the toolkit does. Every question you close here is one that does not become a problem for developers.

### It refuses to build the client packet

Internal wording has crept in — a feature ID, a size, a word like "spec" or "sprint". It names the exact sentence and suggests a plain-language replacement. Fix that sentence and try again.

### "requirement has no provenance"

A requirement has been written that cannot be traced back to anything. Either find where it came from, or remove it. This one is not negotiable — an untraceable requirement is the thing that causes arguments with clients later.

### My transcript is in another language

Fine. It handles any language, including rough automatic transcriptions. It writes your documents in English but keeps the original quotes exactly as spoken, because a translated quote is not evidence.

### It cannot read my file

Word documents and PDFs cannot be read directly. Save as plain text or Markdown first, or paste the contents in.

### I fed in the same transcript twice

It notices and stops. If it is a *corrected* version of a file you already used, it spots that too and asks whether it replaces the earlier one — say yes, or you will get every feature twice.

### The prototype will not run

You need Node.js installed to run prototypes. Without it they are still generated, you just cannot click through them. You can still send the client packet.

### The prototype does not look like our product

Say *"check the grounding"*. It will tell you which screens are not traceable to a real file in your codebase, and rebuild those from the real thing. The usual cause is that it never found your application — see the next entry.

### It says it cannot find my components

The module looks in your project folder, then one level up, then in the folders beside it. That covers the common setup where the documentation lives in one folder and the application in another. If it still cannot find it, just tell it the path. It saves the answer, so you only say it once.

Do not let it carry on without an answer on a project that already exists. It will draw something that looks like a redesign, and your client will react to the redesign instead of the feature.

### It generated screens for a different feature

That should now be blocked before you ever see it. If it happens, say *"check the grounding"* — the extra screens are reported by name and removed. Each run covers exactly one feature.

### It says it cannot capture the screenshots

It needs Chrome, Chromium, Edge or Brave on your machine — any one of them. If you have one but it cannot find it, tell it where: set `CHROME_PATH` to the browser, or just say where it is and it will use that.

You can still send the packet without pictures. It will describe the screens and offer the client a walkthrough instead. Say that to them plainly rather than letting them wonder where the images went.

### The client replied but nothing was recorded

Their answers only come back if they used the Finish button and sent you the block it produced. If they just wrote you an email in their own words instead, that is fine — say *"the client came back on Academy"* and hand over the email. It gets read in the same way, and every answer keeps a trace back to what they actually wrote.

### Two stakeholders gave different answers

That is reported, not resolved. You will see both answers with names against them, and that question stays open. Go back to them and get one answer — or make the call yourself and record it. Nothing will quietly pick one for you.

### Figma is not responding

Figma is optional and off by default. The prototype is the main path. Carry on without it.

### My phase history looks incomplete

If you started on a project already in flight, the earlier phases are genuinely not there, on purpose. What shipped before is in `as-built.md`, not in the phase list. Nothing is broken.

### The numbers look wrong

Say *"check the discovery store"*. It compares the master list against the folders and tells you exactly what disagrees.

---

### FAQ

**Do I need to know how to code?**
No. You type in plain English. The prototypes are built for you.

**Do I have to use all nine tools?**
No. Intake and elaborate are the core. Everything else is there when you need it.

**Can I skip the prototype and go straight to the spec?**
It will stop you, and that is on purpose. Writing the spec first is the failure this whole approach exists to fix. If you truly need to, say so and it will let you past.

**We're already halfway through a project. Can I still use this?**
Yes — that is the "already in flight" option at setup. You start at the phase the project is really on, and tell it what already exists. See section 6.

**I told setup phase 1 but we're actually on phase 3.**
Run setup again and choose "already in flight". If you have already taken features in, do not re-run setup — say *"open phase 3"* and then *"move these to phase 3"* instead.

**Can I run more than one client project?**
Yes. Install it separately in each project folder. Each keeps its own records.

**What if the client changes their mind after approving?**
That is expected. It opens a change record, notes whether the design is now wrong, and — if developers already have it — flags it for the next phase rather than quietly rewriting something being built.

**Where does the final requirements document go?**
Into your normal BMAD output folder, produced by BMad Method's own PRD tool. This toolkit prepares the inputs; that tool writes the document.

**Something is stuck and I do not know what.**
Ask Vadim: *"what's blocking?"*

---

## Getting help

- Ask Vadim first — *"talk to Vadim"* — he can usually see what is wrong.
- Run *"check the discovery store"* if the numbers look off.
- Issues: [github.com/Relevant-S/bmad-fdw](https://github.com/Relevant-S/bmad-fdw)

Built on [BMAD Method](https://bmadcode.com/).
