#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Builds the client review packet: gathers what the client needs to see, then renders it —
refusing to render if internal vocabulary leaked into a document a paying client will read.

Writing the client-facing prose is judgment and stays in the prompt. This script assembles the
inputs, enforces the vocabulary rule, and renders a self-contained page.
"""

from __future__ import annotations

import argparse
import base64
import html
import json
import mimetypes
import re
import sys
from datetime import date
from pathlib import Path
from typing import Any

# Vocabulary that must never reach a client. Each pattern carries the plain-language
# replacement to reach for, because "don't use jargon" is not actionable at 11pm.
FORBIDDEN: list[tuple[str, str, str]] = [
    (r"\bF-\d{3}\b", "feature id", "name the feature in words"),
    (r"\b[AGS]\d+\b", "internal reference id", "say the thing itself, not its id"),
    (r"\bFR-?\d+\b", "requirement id", "describe the requirement in a sentence"),
    (r"\bfdw-[a-z-]+\b", "internal tool name", "remove it — the client does not run our tooling"),
    (r"\bphase-\d[\d.]*\b", "internal phase label", "say 'this stage of the work' or name the date"),
    (r"\b(?:XS|XL|[SML])\s*(?:-|–)?\s*(?:size|effort|t-shirt)\b", "effort sizing", "remove it — sizing is ours, not theirs"),
    (r"\b(?:spec|specced|elaboration doc|backlog|sprint|epic|user stor(?:y|ies))\b", "delivery jargon", "say what it means for them"),
    (r"\b(?:registry|handoff|discovery store|signal\.md|ux-notes)\b", "internal artifact", "remove it"),
    (r"\bstory points?\b", "estimation jargon", "remove it"),
    (r"\bnon-critical\b|\bcriticality\b", "internal triage vocabulary", "say 'when you have a moment' or 'we need this to proceed'"),
    (r"\bunconfirmed\b", "internal assumption status", "phrase it as a question to them"),
]

REQUIRED = ("headline", "intro", "sections", "next_steps")


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


def slugify(text: str, limit: int = 48) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return (slug[:limit].rstrip("-")) or "feature"


def locate(root: Path, feature_id: str) -> tuple[Path, dict[str, Any]]:
    registry = read_json(root / "registry.json")
    if registry is None:
        die([f"No discovery store at {root}. Run fdw-intake first."])
    entry = next((f for f in registry.get("features", []) if f["id"] == feature_id), None)
    if entry is None:
        die([f"No feature '{feature_id}'. Known: {[f['id'] for f in registry.get('features', [])]}"])
    return root / "phases" / entry["phase"] / "features" / f"{entry['id']}-{entry['slug']}", entry


# ---------------------------------------------------------------- gather


def cmd_gather(args: argparse.Namespace) -> None:
    root = Path(args.root).resolve()
    fdir, entry = locate(root, args.id)
    record = read_json(fdir / "feature.json", {})
    design = fdir / "design"

    screens: list[str] = []
    assumptions: list[dict[str, str]] = []
    corrections: list[str] = []
    notes = design / "ux-notes.md"
    if notes.exists():
        text = notes.read_text(encoding="utf-8")
        screens = [
            f"{sid} — {title.strip()}"
            for sid, title in re.findall(r"^\s*-\s+\*\*(S\d+)\s+—\s+([^*]+?)\*\*", text, re.M)
        ]
        for match in re.finditer(r"^\s*-\s+\*\*(A\d+)\*\*\s*(?:\(([^)]*)\))?\s*—\s*(.+)$", text, re.M):
            aid, screen, body = match.group(1), match.group(2) or "", match.group(3)
            status = "unconfirmed"
            if "_Status:" in body:
                body, _, tail = body.partition("_Status:")
                status = tail.strip(" _.").lower() or status
            assumptions.append({"id": aid, "screen": screen, "text": body.strip(" ._"), "status": status})
        corrections = re.findall(r"^\s*-\s+(\d{4}-\d{2}-\d{2}\s+—\s+.+)$", text, re.M)

    gaps: list[str] = []
    empty = design / "empty-state.md"
    if empty.exists():
        gaps = [
            f"{gid} — {body.strip()}"
            for gid, body in re.findall(r"^\s*-\s+\*\*(G\d+)\*\*[^—]*—\s*(.+)$", empty.read_text(encoding="utf-8"), re.M)
        ]

    proto = design / "prototype"
    prototype_files = sorted(str(p.relative_to(fdir)) for p in proto.rglob("*") if p.is_file()) if proto.is_dir() else []

    client_questions = [
        {"id": q["id"], "text": q["text"], "criticality": q.get("criticality", "critical")}
        for q in record.get("questions", [])
        if q.get("status", "open") == "open" and q.get("owner") == "client"
    ]

    packets_dir = root / "phases" / entry["phase"] / "client-packets"
    prior = sorted(p.name for p in packets_dir.glob("*.html")) if packets_dir.is_dir() else []

    unconfirmed = [a for a in assumptions if a["status"] == "unconfirmed"]
    problems = []
    if not prototype_files:
        problems.append(f"{entry['id']}: no prototype to show. Run fdw-design before building a packet.")
    if entry["status"] not in {"client-review", "design-approved", "designing"}:
        problems.append(
            f"{entry['id']}: status is '{entry['status']}'. A packet is what you send at client-review; "
            f"run fdw-design's check and advance the feature first."
        )
    if problems:
        die(problems, feature=entry["id"], status=entry["status"])

    emit(
        {
            "feature": entry["id"],
            "title": entry["title"],
            "phase": entry["phase"],
            "status": entry["status"],
            "summary": record.get("summary", ""),
            "screens": screens,
            "assumptions": assumptions,
            "unconfirmed_assumptions": len(unconfirmed),
            "corrections": corrections,
            "empty_state_gaps": gaps,
            "client_questions": client_questions,
            "prototype_files": prototype_files,
            "prior_packets": prior,
            "packets_dir": str(packets_dir.relative_to(root)),
        }
    )


# ---------------------------------------------------------------- vocabulary gate


def scan_vocabulary(content: dict[str, Any]) -> list[str]:
    """Walk every string that will be rendered and report internal vocabulary. Keys that are
    never rendered are exempt: `ref` carries question ids into the sidecar map, and `_`-prefixed
    keys are authoring notes."""
    problems: list[str] = []

    def walk(node: Any, path: str) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key == "ref" or key.startswith("_"):
                    continue
                walk(value, f"{path}.{key}" if path else key)
        elif isinstance(node, list):
            for i, value in enumerate(node):
                walk(value, f"{path}[{i}]")
        elif isinstance(node, str):
            for pattern, label, fix in FORBIDDEN:
                for hit in re.findall(pattern, node, re.I):
                    text = hit if isinstance(hit, str) else hit[0]
                    problems.append(
                        f"{path}: '{text}' is {label} and must not reach a client — {fix}."
                    )

    walk(content, "")
    return problems


def cmd_render(args: argparse.Namespace) -> None:
    root = Path(args.root).resolve()
    fdir, entry = locate(root, args.id)
    content = read_json(Path(args.content).resolve())
    if content is None:
        die([f"No packet content at {args.content}."])

    missing = [f for f in REQUIRED if not content.get(f)]
    if missing:
        die([f"Packet content is missing {missing}. See assets/packet.example.json for the shape."])

    problems = scan_vocabulary(content)
    if problems and not args.allow_jargon:
        die(
            problems + [
                "This document goes to a paying client. Rewrite the flagged text in their language; "
                "--allow-jargon exists only for an internal preview."
            ],
            leaked=len(problems),
        )

    images: dict[str, str] = {}
    for pair in args.screenshot or []:
        label, _, path = pair.partition("=")
        file = Path(path).expanduser().resolve()
        if not file.exists():
            die([f"Screenshot not found: {file}"])
        mime = mimetypes.guess_type(file.name)[0] or "image/png"
        images[label.strip()] = f"data:{mime};base64," + base64.b64encode(file.read_bytes()).decode()

    stamp = args.date or date.today().isoformat()
    slug = slugify(content.get("headline") or entry["title"])
    out_dir = root / "phases" / entry["phase"] / "client-packets"
    out_dir.mkdir(parents=True, exist_ok=True)
    page = out_dir / f"{stamp}-{slug}.html"
    page.write_text(render(content, images, stamp, args.client), encoding="utf-8")

    # Question ids must map answers back to features but must never appear in the packet.
    mapping = {
        "feature": entry["id"],
        "packet": page.name,
        "date": stamp,
        "questions": [
            {"ref": q.get("ref"), "asked": q.get("question")}
            for q in content.get("questions", [])
            if q.get("ref")
        ],
    }
    map_file = out_dir / f"{stamp}-{slug}.map.json"
    map_file.write_text(json.dumps(mapping, indent=2, ensure_ascii=False), encoding="utf-8")

    emit(
        {
            "feature": entry["id"],
            "packet": str(page.relative_to(root)),
            "map": str(map_file.relative_to(root)),
            "questions_asked": len(mapping["questions"]),
            "screenshots": len(images),
            "jargon_allowed": bool(args.allow_jargon),
            "send": "The .map.json is internal — send the .html only.",
        }
    )


# ---------------------------------------------------------------- render


def esc(text: Any) -> str:
    return html.escape(str(text if text is not None else ""))


CSS = """
*{box-sizing:border-box}
:root{--bg:#fbfbf9;--panel:#fff;--ink:#1c1c19;--muted:#6a6a62;--line:#e4e4dd;--accent:#2f5d8a;--soft:#f0f0ea}
@media(prefers-color-scheme:dark){:root{--bg:#17181b;--panel:#1f2126;--ink:#eaeae5;--muted:#9b9b93;--line:#32353b;--accent:#82abd6;--soft:#272a2f}}
body{margin:0;padding:28px 20px;background:var(--bg);color:var(--ink);
 font:16px/1.65 ui-serif,Georgia,'Times New Roman',serif}
.wrap{max-width:760px;margin:0 auto}
h1{font-size:27px;line-height:1.25;margin:0 0 6px}
.meta{color:var(--muted);font-size:14px;margin-bottom:26px;
 font-family:ui-sans-serif,-apple-system,'Segoe UI',sans-serif}
.intro{font-size:18px;line-height:1.6}
h2{font-size:13px;text-transform:uppercase;letter-spacing:.09em;color:var(--muted);
 margin:34px 0 12px;font-weight:600;font-family:ui-sans-serif,-apple-system,sans-serif}
.screen{background:var(--panel);border:1px solid var(--line);border-radius:10px;
 padding:18px 20px;margin-bottom:14px}
.screen h3{margin:0 0 8px;font-size:19px}
.screen p{margin:0 0 10px}
.screen p:last-child{margin-bottom:0}
.label{font-family:ui-sans-serif,-apple-system,sans-serif;font-size:12px;
 text-transform:uppercase;letter-spacing:.06em;color:var(--muted);margin-bottom:2px}
img{max-width:100%;border-radius:7px;border:1px solid var(--line);margin:12px 0 4px;display:block}
ol,ul{padding-left:22px}
li{margin-bottom:11px}
.ask{background:var(--soft);border-left:3px solid var(--accent);border-radius:0 8px 8px 0;
 padding:14px 18px;margin-bottom:12px}
.ask .q{font-weight:600}
.ask .c{color:var(--muted);font-size:15px;margin-top:5px}
.assume{border-bottom:1px solid var(--line);padding:12px 0}
.assume:last-child{border-bottom:none}
.assume .w{color:var(--muted);font-size:15px;margin-top:4px}
.next{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:18px 20px;margin-top:12px}
footer{margin-top:36px;padding-top:16px;border-top:1px solid var(--line);
 color:var(--muted);font-size:13px;font-family:ui-sans-serif,sans-serif}
@media(max-width:600px){body{padding:18px 14px}h1{font-size:23px}.intro{font-size:17px}}
"""


def render(content: dict[str, Any], images: dict[str, str], stamp: str, client: str | None) -> str:
    out = [
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>",
        "<meta name='viewport' content='width=device-width,initial-scale=1'>",
        f"<title>{esc(content['headline'])}</title><style>{CSS}</style></head><body><div class='wrap'>",
        f"<h1>{esc(content['headline'])}</h1>",
        f"<div class='meta'>{esc(client) + ' · ' if client else ''}{esc(stamp)}</div>",
        f"<div class='intro'>{esc(content['intro'])}</div>",
    ]

    if content.get("sections"):
        out.append("<h2>What we're proposing</h2>")
        for section in content["sections"]:
            out.append("<div class='screen'>")
            out.append(f"<h3>{esc(section.get('screen', ''))}</h3>")
            if section.get("screen") in images:
                out.append(f"<img alt='{esc(section['screen'])}' src='{images[section['screen']]}'>")
            if section.get("what_you_see"):
                out.append(f"<div class='label'>What you see</div><p>{esc(section['what_you_see'])}</p>")
            if section.get("how_it_works"):
                out.append(f"<div class='label'>How it works</div><p>{esc(section['how_it_works'])}</p>")
            out.append("</div>")

    if content.get("assumptions"):
        out.append("<h2>Things we've assumed — please confirm</h2>")
        for item in content["assumptions"]:
            out.append(
                f"<div class='assume'><div>{esc(item.get('we_assumed', ''))}</div>"
                + (f"<div class='w'>{esc(item['why_it_matters'])}</div>" if item.get("why_it_matters") else "")
                + "</div>"
            )

    if content.get("questions"):
        out.append("<h2>What we need from you</h2>")
        for i, item in enumerate(content["questions"], 1):
            out.append(
                f"<div class='ask'><div class='q'>{i}. {esc(item.get('question', ''))}</div>"
                + (f"<div class='c'>{esc(item['context'])}</div>" if item.get("context") else "")
                + "</div>"
            )

    out.append(f"<h2>Next steps</h2><div class='next'>{esc(content['next_steps'])}</div>")
    if content.get("how_to_view"):
        out.append(f"<footer>{esc(content['how_to_view'])}</footer>")
    out.append("</div></body></html>")
    return "\n".join(out)


# ---------------------------------------------------------------- cli


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Build the client review packet")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("gather", help="everything the packet is written from")
    p.add_argument("--root", required=True)
    p.add_argument("--id", required=True)
    p.set_defaults(func=cmd_gather)

    p = sub.add_parser("render", help="render the packet, refusing if internal vocabulary leaked")
    p.add_argument("--root", required=True)
    p.add_argument("--id", required=True)
    p.add_argument("--content", required=True, help="packet content JSON; see assets/packet.example.json")
    p.add_argument("--screenshot", action="append", help="Screen name=path.png, embedded as a data URI")
    p.add_argument("--client", default=None, help="client name for the header")
    p.add_argument("--date", default=None)
    p.add_argument("--allow-jargon", action="store_true", help="internal preview only; never for a client send")
    p.set_defaults(func=cmd_render)

    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
