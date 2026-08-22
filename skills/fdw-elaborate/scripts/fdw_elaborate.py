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
     Owner is client, internal or dev. Approval refuses while any critical question is open. -->

{stub}

## Contradictions

<!-- Where two sources or two stakeholders said different things, with both sides quoted.
     Empty is a valid answer; "none found" is better than silence. -->

{stub}

## Missing information

<!-- What you need and do not have. Distinct from an open question: nobody has been asked yet. -->

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

    changes = (fdir / "changes.md").read_text(encoding="utf-8") if (fdir / "changes.md").exists() else ""
    open_changes = [b.strip().splitlines()[0] for b in changes.split("\n## ")[1:] if "resolution: OPEN" in b]

    return {
        "feature": entry["id"], "entry": entry, "fdir": fdir, "spec": spec, "text": text,
        "requirements": requirements, "size": size, "problems": problems,
        "open_questions": open_q, "critical_open": critical, "open_changes": open_changes,
    }


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

    if state["critical_open"] and not args.accept_open_blockers:
        listed = ", ".join(f"{q['id']} ({q.get('owner', '?')})" for q in state["critical_open"])
        problems.append(
            f"{entry['id']}: {len(state['critical_open'])} critical question(s) still open — {listed}. "
            f"A blocker that survives approval survives into the PRD, which is the number this module "
            f"exists to drive to zero. Close them, or pass --accept-open-blockers to approve anyway "
            f"and have it recorded."
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
    if args.accept_open_blockers and state["critical_open"]:
        note = "\n".join(
            f"- {q['id']} ({q.get('owner', '?')}) — {q.get('text', '')}" for q in state["critical_open"]
        )
        updated += (
            f"\n\n## Approved with open blockers\n\nApproved {stamp} while these critical questions "
            f"were still open. They travel into the phase PRD unresolved:\n\n{note}\n"
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
            "approved_with_open_blockers": [q["id"] for q in state["critical_open"]] if args.accept_open_blockers else [],
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
