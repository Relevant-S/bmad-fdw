---
name: fdw-status
description: Renders the discovery store as a dashboard and reads out what it means. Use when the user says "where are we", "what's blocking", "show me the status", "discovery dashboard", or "what should I do next".
---

# fdw-status

## Overview

Act as the analyst who reads the board for a busy BA — often on a phone, often after a week away. The outcome is two things at once: a self-contained HTML dashboard of the whole engagement, and a short spoken read of what it means. The consumer is a BA who has thirty seconds and needs to know what to do next, and sometimes a client-side stakeholder who will be shown the same page. That sets the bar: the numbers come from the store and are never estimated, and the read has to end in an action, not a summary.

`fdw_status.py` computes everything countable — counts, ages, build order, trends, the digest line. You do not recompute any of it. Your contribution is the judgment a script cannot reach: what the shape of the numbers means, what is quietly going wrong, and what the BA should do in the next hour.

## Resolution rules

- Bare paths and `{skill-root}` (e.g. `scripts/fdw_status.py`) resolve from this skill's installed directory.
- `{project-root}` → the project working directory.

## On Activation

1. Load config via `uv run {project-root}/_bmad/scripts/resolve_config.py --project-root {project-root}`. Resolve `{communication_language}` and `{output_folder}`; `{discovery_folder}` defaults to `{output_folder}/discovery` when unset.
2. Run the dashboard:

```
uv run {skill-root}/scripts/fdw_status.py --root {discovery_folder} --out {output_folder}/fdw-status.html
```

If it reports no store, say so and offer to run `fdw-intake` on a source document. Do not create anything — this skill only ever reads.

## Read it back

The JSON carries a `digest` line. **Do not repeat it** — the BA can read it on the page. Say the things it cannot:

- **What the shape means.** Six features sitting in `client-review` for three weeks is a client who has stopped responding, not a pipeline in progress. Everything bunched at `sliced` means design has not started. One feature blocking four others is the only thing that matters this week.
- **The one next action.** Name it concretely — which questions to chase, which feature to design next, whether a phase is ready to hand off. Rank by what unblocks the most.
- **What looks wrong.** A dependency cycle, an unreadable record, a critical question older than everything around it, a feature flagged `changed` after it was handed to dev.

Then answer whatever the BA actually asked. Give the path to the HTML file, and offer to publish it as a shareable artifact when the host supports one — that page is what gets forwarded.

Ad-hoc questions about state are answered from this same JSON. Load a feature folder only when the question is about that feature's content rather than its position.

## Rules with consequences

- **Derived, never authoritative.** Nothing is true because it appears here. If the dashboard and a feature folder disagree, the folder wins and the store needs `fdw-intake`'s validate intent. The script has no write path into the store, so keep it that way.
- **Never estimate a number.** Every count comes from the JSON. If something is not in there, say it is not tracked rather than inferring it.
- **Ordering is not adjudication.** `build_order` and `cycles` are computed from recorded edges. A cycle gets reported and routed to `fdw-consistency`; do not decide which dependency to break.
- **`--phase` narrows the board, not the totals question.** When the BA asks about one phase, filter; when they ask "where are we", show everything, because a feature deferred out of this phase is still theirs.

## Headless

Return the JSON summary unchanged plus the HTML path. Skip the spoken read — the caller wants data, not narration. `--digest-only` prints the one-line text digest for a status message or a bad connection.
