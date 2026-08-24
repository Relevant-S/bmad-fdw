#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Deterministic support for fdw-elaborate: gathering what the spec is written from,
scaffolding it, validating provenance and structure, and minting stable requirement ids
at approval.

Writing the spec is judgment and stays in the prompt. This script never invents content —
it collects, checks, and numbers.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path
from typing import Any

SIZES = ["XS", "S", "M", "L", "XL"]
LIFECYCLE = [
    "candidate", "sliced", "designing", "client-review", "design-approved",
    "speccing", "spec-approved", "handed-off", "shipped",
]

SPEC_LOCKED = {"spec-approved", "handed-off", "shipped"}
SECTIONS = [
    "Need", "Rules", "Requirements", "Out of scope",
    "Assumptions", "Open questions", "Contradictions", "Missing information",
]
STUB = "_Not written yet._"

REQ_LINE = re.compile(r"^\s*-\s+(?:\*\*\[(?P<id>[A-Z0-9-]+-R-\d+)\]\*\*\s+)?(?P<body>.+?)\s*$")
PROV = re.compile(r"\[(?:src|from):\s*[^\]]+\]")
# Id first, exactly as requirements carry theirs — an id at the end of a line is the one that gets
# lost when the BA edits the end of the line. The dash is permissive and only the two structural
# tokens are English; the question itself is written in whatever language the engagement runs in.
Q_LINE = re.compile(
    r"^\s*-\s+(?:\*\*\[(?P<id>[A-Z0-9-]+-Q-\d+)\]\*\*\s+)?"
    r"\*\*(?P<criticality>critical|non-critical)\*\*\s*"
    r"\((?P<owner>client|internal|dev)\)\s*[—–-]{1,2}\s*(?P<text>.+?)\s*$",
    re.I,
)
QUESTION_SECTIONS = {"Open questions": "open questions", "Missing information": "missing information"}
HEADER_SIZE = re.compile(r"^\*\*Size:\*\*\s*(.+?)\s*$", re.M)
# Status sits inline in the header row alongside Feature and Phase, not on its own line.
HEADER_STATUS = re.compile(r"(\*\*Status:\*\*\s*)([^\n·]+)")


def emit(payload: dict[str, Any]) -> None:
    payload.setdefault("ok", True)
    print(json.dumps(payload, indent=2, ensure_ascii=False))


def die(errors: list[str], **extra: Any) -> None:
    print(json.dumps({"ok": False, "errors": errors, **extra}, indent=2, ensure_ascii=False))
    sys.exit(1)


def read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return default


def locate(root: Path, feature_id: str) -> tuple[Path, dict[str, Any], dict[str, Any]]:
    registry = read_json(root / "registry.json")
    if registry is None:
        die([f"No discovery store at {root}. Run fdw-intake first."])
    entry = next((f for f in registry.get("features", []) if f["id"] == feature_id), None)
    if entry is None:
        die([f"No feature '{feature_id}'. Known: {[f['id'] for f in registry.get('features', [])]}"])
    fdir = root / "phases" / entry["phase"] / "features" / f"{entry['id']}-{entry['slug']}"
    return fdir, entry, read_json(fdir / "feature.json", {})


def section_bodies(text: str) -> dict[str, str]:
    """Map top-level heading -> its body, so checks can ask whether a section was filled in."""
    out: dict[str, str] = {}
    current = None
    buffer: list[str] = []
    for line in text.splitlines():
        match = re.match(r"^##\s+(.+?)\s*$", line)
        if match:
            if current:
                out[current] = "\n".join(buffer).strip()
            current, buffer = match.group(1), []
        elif current:
            buffer.append(line)
    if current:
        out[current] = "\n".join(buffer).strip()
    return out


def requirement_lines(text: str) -> list[tuple[int, str, str | None]]:
    """(line number, body, existing id) for every bullet under ## Requirements."""
    lines = text.splitlines()
    out: list[tuple[int, str, str | None]] = []
    inside = False
    for i, line in enumerate(lines):
        if re.match(r"^##\s+", line):
            inside = re.match(r"^##\s+Requirements\s*$", line) is not None
            continue
        if not inside or not line.strip().startswith("- "):
            continue
        match = REQ_LINE.match(line)
        if match:
            out.append((i, match.group("body"), match.group("id")))
    return out


def question_lines(text: str) -> tuple[list[dict[str, Any]], list[str]]:
    """Every question bullet under either question section, plus the lines that did not parse.

    Unparseable bullets are returned, never skipped: a question quietly dropped on the floor is
    exactly the failure this whole path exists to stop."""
    found: list[dict[str, Any]] = []
    bad: list[str] = []
    section: str | None = None
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        heading = re.match(r"^##\s+(.+?)\s*$", line)
        if heading:
            section = heading.group(1) if heading.group(1) in QUESTION_SECTIONS else None
            i += 1
            continue
        if not section or not line.strip().startswith("- "):
            i += 1
            continue
        match = Q_LINE.match(line)
        if not match:
            bad.append(f"line {i + 1}: {line.strip()[:90]}")
            i += 1
            continue
        # A question long enough to matter wraps. Everything up to the next bullet, blank line or
        # heading is still the same question, and a ledger entry cut off mid-sentence is useless.
        body = [match.group("text").strip()]
        j = i + 1
        while j < len(lines):
            nxt = lines[j]
            if not nxt.strip() or nxt.strip().startswith("- ") or nxt.startswith("#") \
                    or nxt.strip().startswith("<!--"):
                break
            body.append(nxt.strip())
            j += 1
        found.append({
            "line": i,
            "last_line": j - 1,
            "id": match.group("id"),
            "text": " ".join(body),
            "criticality": match.group("criticality").lower(),
            "owner": match.group("owner").lower(),
            "section": section,
            "origin": QUESTION_SECTIONS[section],
        })
        i = j
    return found, bad


def reconcile(root: Path, entry: dict[str, Any], record: dict[str, Any],
              text: str) -> dict[str, Any]:
    """Cross-reference the spec's question prose against the ledger every gate actually reads."""
    bullets, unparsed = question_lines(text)
    ledger = {q.get("id"): q for q in record.get("questions", [])}
    open_ids = {q["id"] for q in record.get("questions", []) if q.get("status", "open") == "open"}
    in_prose = {b["id"] for b in bullets if b["id"]}

    return {
        "bullets": bullets,
        "unparsed": unparsed,
        "to_mint": [b for b in bullets if not b["id"]],
        "orphan_in_prose": sorted(i for i in in_prose if i not in ledger),
        "missing_from_prose": sorted(open_ids - in_prose),
        "resolved_still_in_prose": sorted(
            i for i in in_prose if i in ledger and ledger[i].get("status") == "resolved"),
        "triage_drift": [
            {"id": b["id"], "spec": f"{b['criticality']}/{b['owner']}",
             "ledger": f"{ledger[b['id']].get('criticality')}/{ledger[b['id']].get('owner')}"}
            for b in bullets if b["id"] in ledger
            and (b["criticality"] != ledger[b["id"]].get("criticality")
                 or b["owner"] != ledger[b["id"]].get("owner"))
        ],
    }


def reconcile_problems(fid: str, state: dict[str, Any], root: Path) -> list[str]:
    """The two that must block, and they are not bypassable. An id in the prose that the ledger
    has never heard of is an unknown blocker being hidden, not a known one being accepted."""
    problems: list[str] = []
    for line in state["unparsed"]:
        problems.append(
            f"{fid}: a bullet under a question section does not parse — {line}. Shape is "
            f"`- **critical** (client) — the question`. A bullet nobody can read is a question "
            f"nobody counts.")
    if state["to_mint"]:
        problems.append(
            f"{fid}: {len(state['to_mint'])} question(s) are written in the spec but not in the "
            f"ledger. Prose is not counted by anything — approval, the pre-flight report and the "
            f"phase's own blocker count all read the ledger. Run: "
            f"uv run {Path(__file__).resolve()} questions --root {root} --id {fid}")
    if state["orphan_in_prose"]:
        problems.append(
            f"{fid}: the spec claims {', '.join(state['orphan_in_prose'])}, which the ledger has "
            f"never heard of. Re-run `questions` — it emits the command that files them.")
    return problems


# ---------------------------------------------------------------- gather


def state_cli() -> str:
    """The shared state CLI ships inside fdw-intake, a sibling of this skill once installed.
    Resolve a real path so the command printed here is one the caller can actually paste."""
    sibling = Path(__file__).resolve().parents[2] / "fdw-intake" / "scripts" / "fdw_state.py"
    return f"uv run {sibling}" if sibling.exists() else \
        "uv run {skill-root}/../fdw-intake/scripts/fdw_state.py"


def walk_to(root: Path, entry: dict[str, Any], target: str, by: str, note: str = "",
            final_extra: str = "") -> list[str]:
    """feature-set refuses a forward move that skips a gate, so emit every step rather than a
    single command the caller would watch fail."""
    here = LIFECYCLE.index(entry["status"]) if entry["status"] in LIFECYCLE else LIFECYCLE.index(target)
    want = LIFECYCLE.index(target)
    if here >= want:
        return []
    steps = []
    for stage in LIFECYCLE[here + 1:want + 1]:
        cmd = f"{state_cli()} feature-set --root {root} --id {entry['id']} --status {stage} --by {by}"
        if stage == target:
            cmd += final_extra
            if note:
                cmd += f' --note "{note}"'
        steps.append(cmd)
    return steps


def cmd_gather(args: argparse.Namespace) -> None:
    root = Path(args.root).resolve()
    fdir, entry, record = locate(root, args.id)

    if entry["status"] not in {"design-approved", "speccing", "spec-approved", "handed-off", "shipped"}:
        die(
            [
                f"{entry['id']}: status is '{entry['status']}'. A spec is written from a design the client "
                f"has actually approved — that ordering is the method. Finish fdw-design and fdw-client-packet first."
            ],
            feature=entry["id"], status=entry["status"],
        )

    design = fdir / "design"
    notes = (design / "ux-notes.md").read_text(encoding="utf-8") if (design / "ux-notes.md").exists() else ""
    assumptions = []
    for match in re.finditer(r"^\s*-\s+\*\*(A\d+)\*\*\s*(?:\(([^)]*)\))?\s*—\s*(.+)$", notes, re.M):
        body, status = match.group(3), "unconfirmed"
        if "_Status:" in body:
            body, _, tail = body.partition("_Status:")
            status = tail.strip(" _.").lower() or status
        assumptions.append({"id": match.group(1), "screen": match.group(2) or "",
                            "text": body.strip(" ._"), "status": status})
    corrections = re.findall(r"^\s*-\s+(\d{4}-\d{2}-\d{2}\s+—\s+.+)$", notes, re.M)
    screens = [f"{s} — {t.strip()}" for s, t in re.findall(r"^\s*-\s+\*\*(S\d+)\s+—\s+([^*]+?)\*\*", notes, re.M)]

    empty = design / "empty-state.md"
    gaps = re.findall(r"^\s*-\s+\*\*(G\d+)\*\*[^—]*—\s*(.+)$", empty.read_text(encoding="utf-8"), re.M) if empty.exists() else []

    signal = (fdir / "signal.md").read_text(encoding="utf-8") if (fdir / "signal.md").exists() else ""
    anchors = re.findall(r"anchor:\s*`([^`]+)`", signal)

    changes_text = (fdir / "changes.md").read_text(encoding="utf-8") if (fdir / "changes.md").exists() else ""
    open_changes = [
        block.strip().splitlines()[0]
        for block in changes_text.split("\n## ")[1:]
        if "resolution: OPEN" in block
    ]

    emit(
        {
            "feature": entry["id"],
            "title": entry["title"],
            "phase": entry["phase"],
            "status": entry["status"],
            "summary": record.get("summary", ""),
            "size": entry.get("size"),
            "depends_on": entry.get("depends_on", []),
            "overlaps": entry.get("overlaps", []),
            "spec_locked": entry["status"] in SPEC_LOCKED,
            "screens": screens,
            "assumptions": assumptions,
            "corrections": corrections,
            "empty_state_gaps": [f"{g} — {b.strip()}" for g, b in gaps],
            "signal_anchors": sorted(set(anchors)),
            "signal_path": str((fdir / "signal.md").relative_to(root)) if signal else None,
            "open_questions": [q for q in record.get("questions", []) if q.get("status", "open") == "open"],
            "resolved_questions": [q for q in record.get("questions", []) if q.get("status") == "resolved"],
            "open_changes": open_changes,
            "spec_exists": (fdir / "spec.md").exists(),
            "spec_path": str((fdir / "spec.md").relative_to(root)),
        }
    )


# ---------------------------------------------------------------- scaffold


TEMPLATE = """# {title} — Spec

<!-- SANDBOX. Editing this file ripples nowhere. It becomes an input to the phase PRD only
     once it is approved, which is what lets a contradicting requirement arriving tomorrow be
     cheap to absorb here and expensive to absorb downstream. -->

**Feature:** {id} · **Phase:** {phase} · **Status:** draft
**Size:** —
**Depends on:** {depends}

## Need

**Problem.** {stub}

**Outcome.** {stub}

## Rules

<!-- Constraints that hold across the whole feature: permissions, states that cannot coexist,
     things the business will not allow. Not screen-level behaviour — that is a requirement. -->

{stub}

## Requirements

<!-- One bullet each, testable, in the client's terms. Every line carries provenance:
       [src: <source-id>#t=MM:SS]  evidence from an ingested document
       [from: A2]                  behaviour agreed through the design and signed off
     A line with neither fails validation. Ids are minted at approval — do not write them.
     Shape:  - A course can be published before any sessions exist. [from: A1] -->

{stub}

## Out of scope

<!-- What a reader might reasonably assume is included and is not. This section prevents
     more argument than any other. -->

{stub}

## Assumptions

<!-- Carried from the design notes, plus anything you assumed while writing this.
     A confirmed assumption belongs here as a statement; an unconfirmed one belongs
     in Open questions as well. -->

{stub}

## Open questions

<!-- Shape:  - **critical** (client) — Can two sessions occupy the same room?
     Owner is client, internal or dev. **critical** and (owner) stay in English even when the
     question does not — they are what the parser reads. Approval refuses while ANY question here
     is still open, and `questions` files each one in the ledger every gate downstream counts. -->

{stub}

## Contradictions

<!-- Where two sources or two stakeholders said different things, with both sides quoted.
     Empty is a valid answer; "none found" is better than silence. -->

{stub}

## Missing information

<!-- What you need and do not have. Distinct from an open question only in that nobody has been
     asked yet — it still gates approval, because a gap you cannot fill is a gap development hits.
     Same shape, and default these to non-critical unless the build genuinely stops without them:
       - **non-critical** (client) — the real seven-row rules table for the new categories -->

{stub}
"""


def cmd_scaffold(args: argparse.Namespace) -> None:
    root = Path(args.root).resolve()
    fdir, entry, _ = locate(root, args.id)
    spec = fdir / "spec.md"
    if spec.exists():
        emit({"feature": entry["id"], "spec": str(spec.relative_to(root)), "already_present": True})
        return
    spec.parent.mkdir(parents=True, exist_ok=True)
    spec.write_text(
        TEMPLATE.format(
            title=entry["title"], id=entry["id"], phase=entry["phase"],
            depends=", ".join(entry.get("depends_on", [])) or "—", stub=STUB,
        ),
        encoding="utf-8",
    )
    emit({
        "feature": entry["id"],
        "spec": str(spec.relative_to(root)),
        "already_present": False,
        "next": walk_to(root, entry, "speccing", "fdw-elaborate"),
        "why": "Marking the feature 'speccing' now is what makes approval a single step later.",
    })


# ---------------------------------------------------------------- check


def inspect(root: Path, feature_id: str) -> dict[str, Any]:
    fdir, entry, record = locate(root, feature_id)
    spec = fdir / "spec.md"
    if not spec.exists():
        die([f"{entry['id']}: no spec.md yet. Run: fdw_elaborate.py scaffold --root {root} --id {entry['id']}"])
    text = spec.read_text(encoding="utf-8")
    bodies = section_bodies(text)
    problems: list[str] = []

    for name in SECTIONS:
        if name not in bodies:
            problems.append(f"{entry['id']}: spec is missing the '## {name}' section.")
        elif STUB in bodies[name]:
            problems.append(
                f"{entry['id']}: '## {name}' is still a stub. Every section earns an answer, and "
                f"'none' is an answer worth writing down."
            )

    questions_state = reconcile(root, entry, record, text)
    problems.extend(reconcile_problems(entry["id"], questions_state, root))

    requirements = requirement_lines(text)
    if not requirements:
        problems.append(f"{entry['id']}: no requirements. A spec with nothing to build is not a spec.")
    unsourced = [body for _, body, _ in requirements if not PROV.search(body)]
    for body in unsourced:
        problems.append(
            f"{entry['id']}: requirement has no provenance — \"{body[:70]}\". Add [src: <anchor>] for "
            f"evidence from a document, or [from: A<n>] for behaviour agreed through the design."
        )

    size_match = HEADER_SIZE.search(text)
    size = size_match.group(1).strip() if size_match else "—"
    if size not in SIZES:
        problems.append(f"{entry['id']}: Size is '{size}'. Set it to one of {SIZES} — sizing drives phase scope and build order.")

    open_q = [q for q in record.get("questions", []) if q.get("status", "open") == "open"]
    critical = [q for q in open_q if q.get("criticality") == "critical"]
    questions_state["open_ledger"] = open_q

    changes = (fdir / "changes.md").read_text(encoding="utf-8") if (fdir / "changes.md").exists() else ""
    open_changes = [b.strip().splitlines()[0] for b in changes.split("\n## ")[1:] if "resolution: OPEN" in b]

    return {
        "feature": entry["id"], "entry": entry, "fdir": fdir, "spec": spec, "text": text,
        "requirements": requirements, "size": size, "problems": problems,
        "open_questions": open_q, "critical_open": critical, "open_changes": open_changes,
        "questions_state": questions_state,
    }


def cmd_questions(args: argparse.Namespace) -> None:
    """File the spec's questions into the ledger, and report where the two have drifted.

    The spec is this skill's sandbox so the ids are stamped into it here; the ledger belongs to the
    state CLI, so what comes back is the command that writes there. Between the two there is a
    window where the prose carries an id the ledger lacks — which is exactly `orphan_in_prose`, and
    re-running closes it, because question-add on a supplied id is a no-op."""
    root = Path(args.root).resolve()
    fdir, entry, record = locate(root, args.id)
    spec = fdir / "spec.md"
    if not spec.exists():
        die([f"{entry['id']}: no spec.md yet. Run scaffold first."])
    text = spec.read_text(encoding="utf-8")
    state = reconcile(root, entry, record, text)

    used = [int(m.group(1)) for q in record.get("questions", [])
            if (m := re.match(rf"^{re.escape(entry['id'])}-Q-(\d+)$", str(q.get("id", ""))))]
    used += [int(b["id"].rsplit("-", 1)[1]) for b in state["bullets"] if b["id"]]
    next_n = max(used, default=0) + 1

    lines = text.splitlines()
    minted: list[dict[str, Any]] = []
    for bullet in state["to_mint"]:
        qid = f"{entry['id']}-Q-{next_n:02d}"
        next_n += 1
        raw = lines[bullet["line"]]
        indent = raw[: len(raw) - len(raw.lstrip())]
        lines[bullet["line"]] = (
            f"{indent}- **[{qid}]** **{bullet['criticality']}** ({bullet['owner']}) — {bullet['text']}")
        for extra in range(bullet["line"] + 1, bullet.get("last_line", bullet["line"]) + 1):
            lines[extra] = None  # the wrapped remainder now lives on the stamped line
        minted.append({"id": qid, "text": bullet["text"], "criticality": bullet["criticality"],
                       "owner": bullet["owner"], "origin": bullet["origin"]})

    if args.reconcile and state["missing_from_prose"]:
        by_id = {q["id"]: q for q in record.get("questions", [])}
        restored = [
            f"- **[{qid}]** **{by_id[qid].get('criticality', 'critical')}** "
            f"({by_id[qid].get('owner', 'client')}) — {by_id[qid].get('text', '')}"
            for qid in state["missing_from_prose"]
        ]
        out: list[str] = []
        for line in lines:
            out.append(line)
            if re.match(r"^##\s+Open questions\s*$", line):
                out.append("")
                out.extend(restored)
        lines = out

    if minted or (args.reconcile and state["missing_from_prose"]):
        spec.write_text("\n".join(l for l in lines if l is not None) + "\n", encoding="utf-8")

    # Everything the ledger still lacks, including ids stamped by an earlier run whose command was
    # never executed — so a half-finished sync heals itself rather than sitting there.
    ledger_ids = {q.get("id") for q in record.get("questions", [])}
    pending = list(minted) + [
        {"id": b["id"], "text": b["text"], "criticality": b["criticality"], "owner": b["owner"],
         "origin": b["origin"]}
        for b in state["bullets"] if b["id"] and b["id"] not in ledger_ids
    ]
    seen: set[str] = set()
    pending = [q for q in pending if not (q["id"] in seen or seen.add(q["id"]))]

    batch_file = fdir / ".questions-add.json"
    commands: list[str] = []
    if pending:
        for origin in ("open questions", "missing information"):
            group = [q for q in pending if q["origin"] == origin]
            if not group:
                continue
            target = fdir / f".questions-add-{origin.split()[0]}.json"
            target.write_text(json.dumps(
                {"feature": entry["id"], "source": f"spec {entry['id']} · {origin}",
                 "questions": [{k: q[k] for k in ("id", "text", "criticality", "owner")}
                               for q in group]},
                indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            commands.append(f"{state_cli()} question-add --root {root} --from {target}")
    elif batch_file.exists():
        batch_file.unlink()

    emit({
        "feature": entry["id"],
        "minted": [q["id"] for q in minted],
        "pending": [q["id"] for q in pending],
        "in_sync": len(state["bullets"]) - len(pending),
        "orphan_in_prose": state["orphan_in_prose"],
        "missing_from_prose": state["missing_from_prose"],
        "resolved_still_in_prose": state["resolved_still_in_prose"],
        "triage_drift": state["triage_drift"],
        "unparsed": state["unparsed"],
        "restored": state["missing_from_prose"] if args.reconcile else [],
        "run": commands,
        "note": ("The spec now carries these ids. They are not in the ledger until you run the "
                 "command above, and check and approve will refuse until you do."
                 if commands else "Spec and ledger agree."),
    })


def cmd_check(args: argparse.Namespace) -> None:
    state = inspect(Path(args.root).resolve(), args.id)
    payload = {
        "feature": state["feature"],
        "status": state["entry"]["status"],
        "size": state["size"],
        "requirements": len(state["requirements"]),
        "numbered": sum(1 for _, _, rid in state["requirements"] if rid),
        "critical_open": [q["id"] for q in state["critical_open"]],
        "open_questions": len(state["open_questions"]),
        "open_changes": state["open_changes"],
        "unminted": len(state["questions_state"]["to_mint"]),
        "orphan_in_prose": state["questions_state"]["orphan_in_prose"],
        "missing_from_prose": state["questions_state"]["missing_from_prose"],
        "problems": state["problems"],
        "structurally_ready": not state["problems"],
    }
    if state["problems"]:
        die(state["problems"], **payload)
    emit(payload)


# ---------------------------------------------------------------- approve


def cmd_approve(args: argparse.Namespace) -> None:
    root = Path(args.root).resolve()
    state = inspect(root, args.id)
    entry, text = state["entry"], state["text"]
    problems = list(state["problems"])

    if state["open_changes"] and not args.accept_open_blockers:
        problems.append(
            f"{entry['id']}: {len(state['open_changes'])} unresolved change record(s) in changes.md. "
            f"Absorb the change into the spec and close the record before approving."
        )

    if state["open_questions"] and not args.accept_open_blockers:
        listed = "; ".join(
            f"{q['id']} ({q.get('criticality', '?')} · {q.get('owner', '?')}) {q.get('text', '')[:60]}"
            for q in state["open_questions"]
        )
        problems.append(
            f"{entry['id']}: {len(state['open_questions'])} question(s) still open "
            f"({len(state['critical_open'])} critical) — {listed}. A question this spec still asks is "
            f"a question the phase PRD will ask. Close them — fdw-intake for an answer that arrived "
            f"in a document, question-close for one that arrived in conversation — or pass "
            f"--accept-open-blockers to approve anyway and have it recorded. That count is what this "
            f"module exists to drive to zero."
        )

    if problems:
        die(problems, feature=entry["id"])

    # Ids are minted here and never renumbered. Existing ids survive re-approval; only new
    # requirements get the next number, so a spec that gains a line does not shift the rest.
    lines = text.splitlines()
    used = {rid for _, _, rid in state["requirements"] if rid}
    next_n = max((int(rid.rsplit("-", 1)[1]) for rid in used), default=0) + 1
    minted: list[str] = []
    for index, body, rid in state["requirements"]:
        if rid:
            continue
        new_id = f"{entry['id']}-R-{next_n:02d}"
        next_n += 1
        indent = lines[index][: len(lines[index]) - len(lines[index].lstrip())]
        lines[index] = f"{indent}- **[{new_id}]** {body}"
        minted.append(new_id)

    stamp = date.today().isoformat()
    updated = "\n".join(lines)
    if HEADER_STATUS.search(updated):
        updated = HEADER_STATUS.sub(lambda m: f"{m.group(1)}approved {stamp}", updated, count=1)
    if args.accept_open_blockers and state["open_questions"]:
        note = "\n".join(
            f"- {q['id']} ({q.get('criticality', '?')} · {q.get('owner', '?')}) — {q.get('text', '')}"
            for q in sorted(state["open_questions"],
                            key=lambda q: q.get("criticality") != "critical")
        )
        updated += (
            f"\n\n## Approved with open blockers\n\nApproved {stamp} while these questions were "
            f"still open. They travel into the phase PRD unresolved:\n\n{note}\n"
        )
    state["spec"].write_text(updated + ("\n" if not updated.endswith("\n") else ""), encoding="utf-8")

    emit(
        {
            "feature": entry["id"],
            "spec": str(state["spec"].relative_to(root)),
            "requirements": len(state["requirements"]),
            "minted": minted,
            "preserved": sorted(used),
            "size": state["size"],
            "approved_with_open_blockers": [q["id"] for q in state["open_questions"]] if args.accept_open_blockers else [],
            "next": walk_to(
                root, entry, "spec-approved", "fdw-elaborate",
                note=f"spec approved with {len(state['requirements'])} requirements",
                final_extra=f" --size {state['size']}",
            ),
        }
    )


# ---------------------------------------------------------------- change records


def cmd_close_change(args: argparse.Namespace) -> None:
    root = Path(args.root).resolve()
    fdir, entry, _ = locate(root, args.id)
    changes = fdir / "changes.md"
    if not changes.exists():
        die([f"{entry['id']}: no changes.md — there is no change record to close."])
    text = changes.read_text(encoding="utf-8")
    if "resolution: OPEN" not in text:
        die([f"{entry['id']}: every change record is already closed."])
    stamp = date.today().isoformat()
    updated = text.replace(
        "- resolution: OPEN — route through fdw-elaborate. Intake never edits an approved spec.",
        f"- resolution: {stamp} — {args.resolution}",
        1,
    )
    changes.write_text(updated, encoding="utf-8")
    remaining = updated.count("resolution: OPEN")
    emit({"feature": entry["id"], "closed": 1, "remaining_open": remaining,
          "changes": str(changes.relative_to(root))})


# ---------------------------------------------------------------- cli


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Deterministic support for fdw-elaborate")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("gather", help="everything the spec is written from")
    p.add_argument("--root", required=True)
    p.add_argument("--id", required=True)
    p.set_defaults(func=cmd_gather)

    p = sub.add_parser("scaffold", help="create spec.md from the template")
    p.add_argument("--root", required=True)
    p.add_argument("--id", required=True)
    p.set_defaults(func=cmd_scaffold)

    p = sub.add_parser("questions", help="file the spec's questions into the ledger and report drift")
    p.add_argument("--root", required=True)
    p.add_argument("--id", required=True)
    p.add_argument("--reconcile", action="store_true",
                   help="also write ledger questions the spec has lost back into it")
    p.set_defaults(func=cmd_questions)

    p = sub.add_parser("check", help="structure and provenance; each problem names its fix")
    p.add_argument("--root", required=True)
    p.add_argument("--id", required=True)
    p.set_defaults(func=cmd_check)

    p = sub.add_parser("approve", help="mint stable requirement ids and mark the spec approved")
    p.add_argument("--root", required=True)
    p.add_argument("--id", required=True)
    p.add_argument("--accept-open-blockers", action="store_true", dest="accept_open_blockers",
                   help="approve with critical questions still open; recorded in the spec and the log")
    p.set_defaults(func=cmd_approve)

    p = sub.add_parser("close-change", help="record how a change raised against an approved spec was absorbed")
    p.add_argument("--root", required=True)
    p.add_argument("--id", required=True)
    p.add_argument("--resolution", required=True)
    p.set_defaults(func=cmd_close_change)

    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
