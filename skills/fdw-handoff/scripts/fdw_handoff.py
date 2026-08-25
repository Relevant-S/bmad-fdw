#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Phase handoff: the pre-flight blocker report, the bundle bmad-prd reads, the next call's
agenda, and the as-built refresh.

The eligibility rule is enforced here rather than trusted to prose: only a spec-approved
feature enters a bundle. The blocker report warns and never refuses — a BA who knowingly
ships with an open question is making a call, and the number is recorded either way.
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
from datetime import date
from pathlib import Path
from typing import Any

LIFECYCLE = [
    "candidate", "sliced", "designing", "client-review", "design-approved",
    "speccing", "spec-approved", "handed-off", "shipped",
]
ELIGIBLE = "spec-approved"
REQ = re.compile(r"^\s*-\s+\*\*\[(?P<id>[A-Z0-9-]+-R-\d+)\]\*\*\s+(?P<body>.+?)\s*$", re.M)
# A question bullet that never got an id: written in the spec, counted by nothing.
UNFILED_Q = re.compile(r"^\s*-\s+\*\*(?:critical|non-critical)\*\*\s*\((?:client|internal|dev)\)", re.M | re.I)


AMENDED_MARK = re.compile(r"\s*_\(amended\s+\d{4}-\d{2}-\d{2}[^)]*\)_\s*$")
SUPERSEDED_MARK = re.compile(r"\s*_\(superseded\s+\d{4}-\d{2}-\d{2}[^)]*\)_\s*$")


def _write_atomic(path: Path, text: str) -> None:
    """as-built.md is what every later phase is specced against; a torn write here is the worst
    single loss in the store."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def phase_key(label: str) -> tuple[int, ...]:
    """Sort phases by numeric label, not by position in the registry list. A brownfield store
    starts at whatever phase the project is really on, so insertion order is not chronology.
    Mirrors the helper in fdw_state.py; five lines are cheaper than a cross-skill import."""
    nums = re.findall(r"\d+", label or "")
    return tuple(int(n) for n in nums) or (0,)



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


def esc(x: Any) -> str:
    return html.escape(str(x if x is not None else ""))


def load(root: Path, phase: str) -> dict[str, Any]:
    registry = read_json(root / "registry.json")
    if registry is None:
        die([f"No discovery store at {root}. Run fdw-intake first."])
    if phase not in registry.get("phases", []):
        die([f"No phase '{phase}'. Known: {registry.get('phases', [])}"])

    # Dependencies routinely point at earlier phases — that is the normal shape of phased
    # delivery — so readiness has to be looked up across the whole registry, not just this phase.
    everywhere = {
        f["id"]: {"id": f["id"], "title": f["title"], "phase": f["phase"], "status": f["status"]}
        for f in registry.get("features", [])
    }

    features = []
    for entry in registry.get("features", []):
        if entry["phase"] != phase:
            continue
        fdir = root / "phases" / phase / "features" / f"{entry['id']}-{entry['slug']}"
        record = read_json(fdir / "feature.json", {})
        spec = (fdir / "spec.md").read_text(encoding="utf-8") if (fdir / "spec.md").exists() else ""

        open_q = [q for q in record.get("questions", []) if q.get("status", "open") == "open"]
        features.append({
            **{k: entry.get(k) for k in ("id", "title", "slug", "phase", "status", "size")},
            "flags": entry.get("flags", []), "depends_on": entry.get("depends_on", []),
            "summary": record.get("summary", ""),
            "dir": fdir,
            "spec_path": (fdir / "spec.md") if spec else None,
            "requirements": [{"id": m.group("id"), "text": m.group("body")} for m in REQ.finditer(spec)],
            "open_questions": open_q,
            "critical_open": [q for q in open_q if q.get("criticality") == "critical"],
            "changes": record.get("changes", []),
            "open_changes": [c for c in record.get("changes", [])
                             if c.get("status", "open") == "open"
                             and c.get("route") != "delivered"],
            "open_delivered": [c for c in record.get("changes", [])
                               if c.get("status", "open") == "open"
                               and c.get("route") == "delivered"],
            "design_dir": (fdir / "design") if (fdir / "design").exists() else None,
        })
    return {
        "registry": registry,
        "phase": phase,
        "phase_record": read_json(root / "phases" / phase / "phase.json", {}) or {},
        "features": features,
        "everywhere": everywhere,
    }


def select(data: dict[str, Any], ids: list[str] | None) -> tuple[list[dict], list[dict]]:
    pool = data["features"] if not ids else [f for f in data["features"] if f["id"] in ids]
    if ids:
        missing = set(ids) - {f["id"] for f in pool}
        if missing:
            die([f"Not in {data['phase']}: {sorted(missing)}. "
                 f"Present: {[f['id'] for f in data['features']]}"])
    eligible = [f for f in pool if f["status"] == ELIGIBLE]
    blocked = [f for f in pool if f["status"] != ELIGIBLE]
    return eligible, blocked


def trend(root: Path, registry: dict[str, Any], upto: str) -> list[dict[str, Any]]:
    out = []
    for name in sorted(registry.get("phases", []), key=phase_key):
        if phase_key(name) > phase_key(upto):
            break
        record = read_json(root / "phases" / name / "phase.json", {}) or {}
        if record.get("blocker_count_at_handoff") is not None:
            out.append({"phase": name, "blockers": record["blocker_count_at_handoff"]})
    return out


# ---------------------------------------------------------------- pre-flight


def cmd_preflight(args: argparse.Namespace) -> None:
    root = Path(args.root).resolve()
    data = load(root, args.phase)
    eligible, blocked = select(data, args.id)

    critical = [
        {"id": q["id"], "feature": f["id"], "feature_title": f["title"],
         "owner": q.get("owner", "?"), "text": q.get("text", "")}
        for f in eligible for q in f["critical_open"]
    ]
    minor = sum(len(f["open_questions"]) - len(f["critical_open"]) for f in eligible)
    # Named, not counted: a table saying "F-001 · 2" tells the BA nothing they can act on.
    changes = [
        {"feature": f["id"], "change_id": c["id"], "text": c.get("text", ""),
         "route": c.get("route"), "design_invalidated": c.get("design_invalidated")}
        for f in eligible for c in f["open_changes"]
    ]

    everywhere = data["everywhere"]
    selected = {f["id"] for f in eligible}
    gaps = []
    for feature in eligible:
        for dep in feature["depends_on"]:
            if dep in selected:
                continue
            target = everywhere.get(dep)
            if target is None:
                gaps.append({
                    "feature": feature["id"], "depends_on": dep,
                    "detail": f"{feature['id']} depends on {dep}, which is not in the registry at all.",
                })
            elif LIFECYCLE.index(target["status"]) < LIFECYCLE.index("handed-off"):
                gaps.append({
                    "feature": feature["id"], "depends_on": dep,
                    "detail": f"{feature['id']} depends on {dep} ({target['phase']}, "
                              f"'{target['status']}'), which is neither in this bundle nor already "
                              f"handed off.",
                })

    # Independent of the ledger: if a bundled spec still carries question bullets with no id, the
    # bridge was never run and the ledger is understating the blockers, whatever the count says.
    unfiled = []
    for feature in eligible:
        if not feature["spec_path"]:
            continue
        text = feature["spec_path"].read_text(encoding="utf-8")
        loose = len(UNFILED_Q.findall(text))
        if loose:
            unfiled.append({"feature": feature["id"], "bullets": loose,
                            "detail": f"{feature['id']}: {loose} question bullet(s) in the spec carry "
                                      f"no id, so nothing counts them. Run fdw-elaborate questions."})

    history = trend(root, data["registry"], args.phase)
    payload = {
        "phase": args.phase,
        "eligible": [{"id": f["id"], "title": f["title"], "size": f["size"],
                      "requirements": len(f["requirements"])} for f in eligible],
        "not_eligible": [{"id": f["id"], "title": f["title"], "status": f["status"],
                          "why": f"only a '{ELIGIBLE}' feature can be bundled; this one is '{f['status']}'"}
                         for f in blocked],
        "critical_blockers": critical,
        "minor_open": minor,
        "open_change_records": changes,
        "dependency_gaps": gaps,
        "requirements_total": sum(len(f["requirements"]) for f in eligible),
        "trend": history,
        "verdict": (
            "Nothing eligible to bundle." if not eligible else
            f"{len(eligible)} feature(s) ready, {len(critical)} critical blocker(s) would travel "
            f"into the PRD — bundle will refuse unless you pass --accept-open-blockers."
            if critical else f"{len(eligible)} feature(s) ready, no critical blockers."
        ),
        # This command is the report the BA runs to decide, so it always exits 0 — the refusal is
        # on bundle, which is where blockers would actually travel.
        "blocks_bundle": bool(critical),
        "unfiled_questions": unfiled,
    }

    if args.out:
        target = Path(args.out).resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(render_preflight(payload), encoding="utf-8")
        payload["report"] = str(target)
    emit(payload)


CSS = """
*{box-sizing:border-box}
:root{--bg:#f8f8f6;--panel:#fff;--ink:#1c1c19;--muted:#6a6a62;--line:#e4e4dd;
 --crit:#b4423a;--ok:#3f7a4a;--warn:#a8712a;--soft:#f0f0ea}
@media(prefers-color-scheme:dark){:root{--bg:#16171a;--panel:#1e2024;--ink:#e9e9e4;--muted:#9a9a92;
 --line:#31343a;--crit:#e0776d;--ok:#7fb98a;--warn:#d6a15c;--soft:#272a2f}}
body{margin:0;padding:22px 18px;background:var(--bg);color:var(--ink);
 font:15px/1.6 ui-sans-serif,-apple-system,'Segoe UI',Roboto,sans-serif}
.wrap{max-width:900px;margin:0 auto}
h1{font-size:22px;margin:0 0 4px}
.sub{color:var(--muted);font-size:13px;margin-bottom:18px}
.verdict{background:var(--panel);border:1px solid var(--line);border-radius:8px;
 padding:15px 17px;margin-bottom:8px;font-size:16px}
.verdict.clean{border-left:3px solid var(--ok)}
.verdict.warn{border-left:3px solid var(--crit)}
.note{color:var(--muted);font-size:13px;margin-bottom:20px}
h2{font-size:13px;text-transform:uppercase;letter-spacing:.07em;color:var(--muted);
 margin:26px 0 10px;font-weight:600}
table{width:100%;border-collapse:collapse;font-size:14px;background:var(--panel);
 border:1px solid var(--line);border-radius:8px;overflow:hidden}
th{text-align:left;font-size:11px;text-transform:uppercase;letter-spacing:.05em;color:var(--muted);
 padding:8px 11px;border-bottom:1px solid var(--line)}
td{padding:8px 11px;border-bottom:1px solid var(--line)}
tr:last-child td{border-bottom:none}
.id{font-family:ui-monospace,Menlo,monospace;font-size:12px;color:var(--muted)}
.chip{display:inline-block;font-size:11px;padding:1px 8px;border-radius:999px;background:var(--soft)}
.chip.crit{background:var(--crit);color:#fff}
.empty{background:var(--panel);border:1px solid var(--line);border-radius:8px;
 padding:14px 16px;color:var(--muted)}
.trend{display:flex;gap:16px;align-items:flex-end;height:96px;padding:10px 0}
.tcol{display:flex;flex-direction:column;align-items:center;gap:5px;font-size:12px;color:var(--muted)}
.tbar{width:36px;background:var(--crit);border-radius:3px 3px 0 0;min-height:3px}
.tbar.zero{background:var(--ok)}
@media(max-width:600px){body{padding:14px 12px}}
"""


def render_preflight(p: dict[str, Any]) -> str:
    crit = p["critical_blockers"]
    out = [
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>",
        "<meta name='viewport' content='width=device-width,initial-scale=1'>",
        f"<title>Pre-flight — {esc(p['phase'])}</title><style>{CSS}</style></head><body><div class='wrap'>",
        f"<h1>Handoff pre-flight — {esc(p['phase'])}</h1>",
        f"<div class='sub'>{len(p['eligible'])} feature(s) · {p['requirements_total']} requirement(s) · "
        f"{date.today().isoformat()}</div>",
        f"<div class='verdict {'warn' if crit else 'clean'}'>{esc(p['verdict'])}</div>",
        "<div class='note'>This report never refuses — it is what you run to decide. "
        "<b>Bundling does refuse</b> while a critical question is open: bundle the clean features "
        "with <code>--id</code>, or pass <code>--accept-open-blockers --reason \"…\"</code> to hand "
        "off knowingly. Either way the count is recorded on the phase.</div>",
    ]

    out.append("<h2>Critical blockers that would travel into the PRD</h2>")
    if crit:
        out.append("<table><tr><th>Question</th><th>Owner</th><th>Feature</th></tr>")
        for b in crit:
            out.append(f"<tr><td>{esc(b['text'])}</td><td><span class='chip crit'>{esc(b['owner'])}</span></td>"
                       f"<td class='id'>{esc(b['feature'])} {esc(b['feature_title'])}</td></tr>")
        out.append("</table>")
    else:
        out.append("<div class='empty'>None. Every critical question in this bundle was closed before approval — "
                   "which is the whole point of the spec gate.</div>")

    if p["dependency_gaps"]:
        out.append("<h2>Dependencies not in the bundle</h2><table><tr><th>Gap</th></tr>")
        for g in p["dependency_gaps"]:
            out.append(f"<tr><td>{esc(g['detail'])}</td></tr>")
        out.append("</table>")

    if p["open_change_records"]:
        out.append("<h2>Unresolved change records</h2><table><tr><th>Feature</th><th>Open</th></tr>")
        for c in p["open_change_records"]:
            out.append(f"<tr><td class='id'>{esc(c['feature'])}</td><td>{c['open']}</td></tr>")
        out.append("</table>")

    if p["not_eligible"]:
        out.append("<h2>Not going in</h2><table><tr><th>Feature</th><th>Why</th></tr>")
        for f in p["not_eligible"]:
            out.append(f"<tr><td class='id'>{esc(f['id'])} {esc(f['title'])}</td><td>{esc(f['why'])}</td></tr>")
        out.append("</table>")

    if len(p["trend"]) > 1:
        peak = max(t["blockers"] for t in p["trend"]) or 1
        out.append("<h2>Blockers surviving to handoff, by phase</h2><div class='trend'>")
        for t in p["trend"]:
            height = int(72 * t["blockers"] / peak)
            zero = " zero" if t["blockers"] == 0 else ""
            out.append(f"<div class='tcol'><div>{t['blockers']}</div>"
                       f"<div class='tbar{zero}' style='height:{max(height, 3)}px'></div>"
                       f"<div>{esc(t['phase'])}</div></div>")
        out.append(f"<div class='tcol'><div>{len(crit)}</div>"
                   f"<div class='tbar{' zero' if not crit else ''}' "
                   f"style='height:{max(int(72 * len(crit) / peak), 3)}px'></div>"
                   f"<div>{esc(p['phase'])} (now)</div></div>")
        out.append("</div>")

    out.append("</div></body></html>")
    return "\n".join(out)


# ---------------------------------------------------------------- bundle


def cmd_bundle(args: argparse.Namespace) -> None:
    root = Path(args.root).resolve()
    data = load(root, args.phase)
    eligible, blocked = select(data, args.id)

    if args.id and blocked:
        die(
            [f"{f['id']} is '{f['status']}', not '{ELIGIBLE}'. Only an approved spec enters a bundle — "
             f"the bundle is a contract with development." for f in blocked],
            not_eligible=[f["id"] for f in blocked],
        )
    if not eligible:
        die([f"Nothing in {args.phase} is '{ELIGIBLE}'. Approve at least one spec with fdw-elaborate first."])

    missing_spec = [f["id"] for f in eligible if not f["spec_path"]]
    if missing_spec:
        die([f"{fid}: status says spec-approved but there is no spec.md." for fid in missing_spec])

    # The gate lives here rather than in preflight: preflight is a report the BA runs precisely to
    # see the blockers, and a question raised after approval never passes through the spec gate
    # again — bundling is the last moment anything can catch it.
    travelling = [(f, q) for f in eligible for q in f["critical_open"]]
    if travelling and not args.accept_open_blockers:
        listed = ", ".join(f"{q['id']} ({f['id']} · {q.get('owner', '?')})" for f, q in travelling)
        clean = [f["id"] for f in eligible if not f["critical_open"]]
        die(
            [
                f"{args.phase}: {len(travelling)} critical question(s) would travel into the PRD "
                f"unresolved — {listed}. A blocker that reaches the PRD is what this module exists "
                f"to prevent, and {args.phase} would record it as its own score.",
                (f"Bundle only what is clean with --id {' --id '.join(clean)}, or"
                 if clean else "Close them, or") +
                " pass --accept-open-blockers --reason \"…\" to hand off knowingly; the accepted "
                "ids are written into bundle.json and BUNDLE.md.",
            ],
            phase=args.phase,
            critical_blockers=[q["id"] for _, q in travelling],
            minor_open=sum(len(f["open_questions"]) - len(f["critical_open"]) for f in eligible),
            clean_features=clean,
        )

    # A change record is a contradiction the spec has not absorbed yet. Bundling it hands
    # development a document that is already known to be wrong — a different failure from an
    # open question, which merely hands them one nobody has answered.
    changing = [(f, c) for f in eligible for c in f["open_changes"]]
    if changing and not args.accept_open_blockers:
        listed = ", ".join(f"{c['id']} ({f['id']})" for f, c in changing)
        clean = [f["id"] for f in eligible if not f["open_changes"]]
        die(
            [
                f"{args.phase}: {len(changing)} open change record(s) would travel into the PRD — "
                f"{listed}. The store records a change these specs do not say yet.",
                (f"Absorb them with fdw-elaborate revise, bundle only what is clean with "
                 f"--id {' --id '.join(clean)}, or" if clean else "Absorb them, or") +
                " pass --accept-open-blockers --reason \"…\" to hand off knowingly.",
            ],
            phase=args.phase,
            open_change_records=[c["id"] for _, c in changing],
            clean_features=clean,
        )

    out_dir = root / "phases" / args.phase / "handoff"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = args.date or date.today().isoformat()

    order = sorted(eligible, key=lambda f: (len(f["depends_on"]), f["id"]))
    sources: list[str] = []
    manifest_features = []
    for feature in order:
        rel_spec = feature["spec_path"].relative_to(root)
        sources.append(str(rel_spec))
        notes = feature["design_dir"] / "ux-notes.md" if feature["design_dir"] else None
        if notes and notes.exists():
            sources.append(str(notes.relative_to(root)))
        manifest_features.append({
            "id": feature["id"], "title": feature["title"], "size": feature["size"],
            "summary": feature["summary"], "depends_on": feature["depends_on"],
            "requirements": [r["id"] for r in feature["requirements"]],
            "spec": str(rel_spec),
            "ux_notes": str(notes.relative_to(root)) if notes and notes.exists() else None,
            "critical_open": [q["id"] for q in feature["critical_open"]],
        })

    for extra in ("decisions.md", "glossary.md", "as-built.md"):
        if (root / extra).exists():
            sources.append(extra)

    readme = out_dir / "BUNDLE.md"
    manifest = {
        "contract_version": 1,
        "phase": args.phase,
        "assembled": stamp,
        "features": manifest_features,
        "requirements_total": sum(len(f["requirements"]) for f in eligible),
        "critical_blockers": [q["id"] for f in eligible for q in f["critical_open"]],
        "accepted_blockers": ([q["id"] for _, q in travelling] if args.accept_open_blockers else []),
        "accepted_changes": ([c["id"] for _, c in changing] if args.accept_open_blockers else []),
        "override_reason": (args.reason if args.accept_open_blockers else None),
        "readme": str(readme.relative_to(root)),
        "source_documents": [str(readme.relative_to(root))] + sources,
    }
    (out_dir / "bundle.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
                                         encoding="utf-8")

    lines = [
        f"# {args.phase} handoff bundle",
        "",
        f"Assembled {stamp}. {len(eligible)} feature(s), {manifest['requirements_total']} approved requirements.",
        "",
        "This bundle is the input to the phase PRD. Every feature in it has an approved spec, and every",
        "requirement in those specs carries provenance — either an anchor into a source document or a",
        "reference to a design decision the client signed off. **The specs are the source of truth**;",
        "this file only orients a reader who has never seen the engagement.",
        "",
        "## What is in this phase",
        "",
    ]
    for feature in order:
        deps = f" · depends on {', '.join(feature['depends_on'])}" if feature["depends_on"] else ""
        lines.append(f"### {feature['id']} — {feature['title']}")
        lines.append("")
        lines.append(f"{feature['summary'] or '_No summary recorded._'}")
        lines.append("")
        lines.append(f"Size {feature['size'] or '—'} · {len(feature['requirements'])} requirements{deps}")
        lines.append("")
        lines.append(f"Spec: `{feature['spec_path'].relative_to(root)}`")
        if feature["critical_open"]:
            lines.append("")
            lines.append(f"> **Open blockers travelling into the PRD:** "
                         + ", ".join(q["id"] for q in feature["critical_open"]))
        lines.append("")

    blockers = [q for f in eligible for q in f["critical_open"]]
    lines += [
        "## Build order",
        "",
        "Derived from recorded dependencies: " + " → ".join(f["id"] for f in order),
        "",
        "## State of the questions",
        "",
        (f"**Handed off with {len(blockers)} critical question(s) still open**"
         + (f" — {args.reason}." if args.reason else ".")
         + " They travel into the PRD unresolved: "
         + ", ".join(f"{q['id']} ({q.get('owner', '?')})" for q in blockers)
         + ". Answering them is the first thing this phase owes."
         if blockers else
         "No critical questions are open. Every blocker was closed before the specs were approved."),
        "",
        "## Also included",
        "",
        "- `decisions.md` — why things are the way they are, including rejected alternatives",
        "- `glossary.md` — canonical terms and the variants seen in sources",
        "- `as-built.md` — what previous phases already shipped",
        "",
    ]
    readme.write_text("\n".join(lines), encoding="utf-8")

    # The next call's agenda: what the client still owes us, which the next transcript closes.
    client_q = [
        (f, q) for f in data["features"] for q in f["open_questions"] if q.get("owner") == "client"
    ]
    agenda = out_dir / "next-call-agenda.md"
    alines = [f"# Next call — {args.phase}", "",
              f"Generated {stamp}. {len(client_q)} question(s) only the client can answer.", ""]
    if not client_q:
        alines.append("Nothing outstanding on the client side.")
    for level in ("critical", "non-critical"):
        block = [(f, q) for f, q in client_q if q.get("criticality") == level]
        if not block:
            continue
        alines += [f"## {'Blocking' if level == 'critical' else 'Worth asking'}", ""]
        for feature, question in block:
            alines.append(f"- **{feature['title']}** — {question.get('text', '')}  \n  _`{question['id']}`_")
        alines.append("")
    agenda.write_text("\n".join(alines), encoding="utf-8")

    emit({
        "phase": args.phase,
        "bundle": str((out_dir / "bundle.json").relative_to(root)),
        "readme": str(readme.relative_to(root)),
        "agenda": str(agenda.relative_to(root)),
        "features": [f["id"] for f in order],
        "requirements": manifest["requirements_total"],
        "critical_blockers": [q["id"] for q in blockers],
        "source_documents": [str(root / s) for s in manifest["source_documents"]],
        "next": "Invoke bmad-prd with Create intent, passing source_documents as existing input paths.",
    })


# ---------------------------------------------------------------- build brief


_TERM_RE = re.compile(r"[^\W\d_]{3,}", re.UNICODE)
_STOP = {"the", "and", "for", "with", "that", "this", "from", "are", "not", "can", "has", "its",
         "into", "when", "which", "each", "per", "any", "all", "one", "two", "must", "still"}


def _terms(text: str) -> set[str]:
    return {w.casefold() for w in _TERM_RE.findall(str(text))} - _STOP


def _relevant(lines: list[str], change_text: str, keep: int) -> tuple[list[str], int]:
    """The requirements a change plausibly touches, most relevant first.

    A large feature's full as-built dump is 30+ lines and blows bmad-build's whole token budget
    before the change is even described. Ranking keeps the brief self-contained about the part
    that matters; the count of what was left out is reported rather than silently dropped."""
    wanted = _terms(change_text)
    scored = sorted(lines, key=lambda l: -len(wanted & _terms(l)))
    hits = [l for l in scored if wanted & _terms(l)]
    chosen = hits[:keep] if hits else scored[:keep]
    # Preserve document order: requirement ids read as a sequence, not a ranking.
    chosen = [l for l in lines if l in set(chosen)]
    return chosen, len(lines) - len(chosen)


def _as_built_lines(root: Path, phase: str, fid: str) -> list[str]:
    """The delivered requirement lines for one feature, read from as-built rather than the spec.

    This is what makes the brief self-contained: a build agent that has never seen the discovery
    store gets the behaviour that actually shipped, not the discovery history behind it."""
    path = root / "as-built.md"
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8")
    if f"## {phase}" not in text:
        return []
    section = text.split(f"## {phase}", 1)[1]
    nxt = re.search(r"^## ", section, re.M)
    if nxt:
        section = section[:nxt.start()]
    block, found = [], False
    for line in section.splitlines():
        if line.startswith("### "):
            found = f"`{fid}`" in line
            continue
        if found and line.strip().startswith(f"- `{fid}-R-"):
            block.append(line.strip())
    return block


def cmd_build_brief(args: argparse.Namespace) -> None:
    """Write a self-contained intent file for bmad-build.

    Deliberately NOT a bmad-build spec: that template carries a Code Map and a task list this
    module has no basis to fill in, and step-01 routes a file with `status:` frontmatter as a
    resumable spec. An intent file is the sanctioned handshake, and bmad-build's own planning
    step does the codebase work fdw cannot."""
    root = Path(args.root).resolve()
    registry = read_json(root / "registry.json")
    if registry is None:
        die([f"No discovery store at {root}."])
    fid = args.change_id.rsplit("-C-", 1)[0]
    entry = next((f for f in registry.get("features", []) if f["id"] == fid), None)
    if entry is None:
        die([f"'{args.change_id}' does not name a known feature."])
    fdir = root / "phases" / entry["phase"] / "features" / f"{entry['id']}-{entry['slug']}"
    record = read_json(fdir / "feature.json", {})
    change = next((c for c in record.get("changes", []) if c.get("id") == args.change_id), None)
    if change is None:
        die([f"No change '{args.change_id}' on {fid}."])
    if entry["status"] not in {"handed-off", "shipped"}:
        die([f"{fid} is '{entry['status']}' — it has not been handed to development, so there is "
             f"nothing shipped to change. Absorb it into the spec with fdw-elaborate revise."])
    if change.get("route") != "delivered":
        die([f"{args.change_id} is an in-flight change against a spec that is still the BA's. "
             f"Run fdw-elaborate revise — reopening the spec is cheaper than a side build."])
    if change.get("status", "open") != "open":
        die([f"{args.change_id} is already '{change['status']}'."])

    phase_record = read_json(root / "phases" / entry["phase"] / "phase.json", {}) or {}
    warnings = []
    if phase_record.get("status") == "open" and phase_record.get("prd_path"):
        warnings.append(
            f"{entry['phase']} is still open and its PRD exists at "
            f"`{phase_record['prd_path']}`. If the team has not built this yet, amending that PRD "
            f"through bmad-prd is cheaper than a side-channel build and keeps one source of truth.")

    shipped = _as_built_lines(root, entry["phase"], fid)
    spec_text = (fdir / "spec.md").read_text(encoding="utf-8") if (fdir / "spec.md").exists() else ""
    if not shipped:
        shipped = [f"- `{m.group('id')}` {m.group('body')}" for m in REQ.finditer(spec_text)
                   if not SUPERSEDED_MARK.search(m.group("body"))]
    grounding = read_json(fdir / "design" / "grounding.json", {}) or {}
    sources = sorted({str(sc.get("source")) for sc in grounding.get("screens", []) if sc.get("source")})
    siblings = [f["id"] for f in registry.get("features", [])
                if f["phase"] == entry["phase"] and f["id"] != fid]

    stamp = args.date or date.today().isoformat()
    lines = [
        "---",
        f"feature: {fid}",
        f"change: {change['id']}",
        f"type: {args.type}",
        f"discovery_store: {root}",
        "---",
        "",
        f"# {entry['title']} — {change['id']}",
        "",
        "## What changed",
        "",
        change.get("text", ""),
        "",
    ]
    if change.get("quote"):
        lines += [f"> {change['quote']}", ""]
    if change.get("anchor"):
        lines += [f"Source: `{change['anchor']}` · raised {change.get('raised', '?')} by "
                  f"{change.get('raised_by', '?')}", ""]
    shown, omitted = _relevant(shipped, change.get("text", ""), args.max_requirements)
    lines += ["## What exists today", "",
              f"{record.get('summary', '') or entry['title']}", ""]
    lines += shown or ["- _No delivered requirements recorded._"]
    if omitted:
        lines += ["", f"_{omitted} further delivered requirement(s) for {fid} are not listed here "
                      f"because they do not touch this change. The full set is in "
                      f"`as-built.md`, section `{entry['phase']}`._"]
    lines += ["", "## What must be true after", "",
              "- " + change.get("text", ""), ""]
    lines += ["## Do not change", "",
              "- Any behaviour not named above.",
              f"- Anything belonging to {', '.join(siblings) if siblings else 'another feature'} — "
              f"they are separate features in the same phase.", ""]
    if sources:
        lines += ["## Where this lives", "",
                  "The prototype for this feature was cloned from these real files:", ""]
        lines += [f"- `{src}`" for src in sources]
        lines += [""]
    else:
        lines += ["## Where this lives", "",
                  "_Unknown — no grounding recorded. Investigate before changing anything._", ""]
    lines += ["---", "",
              f"When this ships, close the record so as-built stays true:", "",
              "```",
              f"uv run {Path(__file__).resolve().parents[2]}/fdw-intake/scripts/fdw_state.py "
              f"change-close --root {root} --change-id {change['id']} \\",
              f'  --resolution "…" --outcome delivered --delivered-in "<PR or build>"',
              "```", ""]

    out = Path(args.out) if args.out else (fdir / "builds" / f"{stamp}-{change['id']}.md")
    out.parent.mkdir(parents=True, exist_ok=True)
    body = "\n".join(lines)
    out.write_text(body, encoding="utf-8")

    # bmad-build targets 900-1300 tokens and treats 1600 as the context-rot threshold. This brief
    # becomes input to that spec, so it has to leave room.
    estimate = int(len(body.split()) * 1.35)
    if estimate > 1600:
        warnings.append(f"The brief is roughly {estimate} tokens, above bmad-build's 1600 "
                        f"threshold. 'What exists today' carries {len(shown)} requirement lines — "
                        f"lower --max-requirements, or split the change.")
    if omitted:
        warnings.append(f"{omitted} of {fid}'s {len(shipped)} delivered requirements are not in "
                        f"the brief — they share no vocabulary with the change. Raise "
                        f"--max-requirements if the build needs more context.")

    emit({"feature": fid, "change": change["id"], "brief": str(out.relative_to(root)),
          "estimated_tokens": estimate, "delivered_requirements": len(shipped),
          "requirements_shown": len(shown), "requirements_omitted": omitted,
          "grounding_sources": sources, "warnings": warnings,
          "next": f"Run /bmad-build against {out} — it is an intent file, not a spec, so "
                  f"bmad-build does its own planning."})


# ---------------------------------------------------------------- as-built


def cmd_as_built(args: argparse.Namespace) -> None:
    """Append what this phase shipped to the rolling baseline, so the next phase is specced
    against reality instead of against a pile of old specs."""
    root = Path(args.root).resolve()
    data = load(root, args.phase)
    shipped = [f for f in data["features"] if f["status"] in {"handed-off", "shipped"}]
    if not shipped:
        die([f"Nothing in {args.phase} has been handed off yet; there is nothing to record as built."])

    path = root / "as-built.md"
    text = path.read_text(encoding="utf-8") if path.exists() else "# As-Built Baseline\n"
    text = text.replace("\n_Nothing shipped yet._\n", "\n")
    marker = f"## {args.phase}"
    if marker in text and not args.rebuild:
        die([f"as-built.md already has a '{args.phase}' section. Pass --rebuild to regenerate it "
             f"from the current specs — that is how a change to delivered work lands here."])

    stamp = args.date or date.today().isoformat()
    # A rebuild must not restamp the ship date: the phase shipped when it shipped, and the whole
    # point of this file is that it says what actually happened.
    if marker in text and not args.date:
        prior = re.search(rf"^## {re.escape(args.phase)}\s*\n+_Shipped (\d{{4}}-\d{{2}}-\d{{2}})",
                          text, re.M)
        if prior:
            stamp = prior.group(1)
    prd = args.prd_path or data["phase_record"].get("prd_path")

    # Which requirements a change touched, and what they said before it did. A change absorbed
    # into the spec but not yet delivered means the spec is ahead of reality, and this file is
    # the one place that has to state what actually shipped rather than what is planned.
    amended: dict[str, dict[str, Any]] = {}
    for feature in shipped:
        for change in feature.get("changes", []):
            for rid in change.get("absorbed_by", []):
                amended[rid] = change
            for rid in [r.get("id") for r in change.get("supersedes", []) if isinstance(r, dict)]:
                amended[rid] = change

    landed = [c for f in shipped for c in f.get("changes", []) if c.get("outcome") == "delivered"]
    pending = [c for f in shipped for c in f.get("changes", []) if c.get("outcome") == "absorbed"]

    head = [marker, "",
            f"_Shipped {stamp}" + (f" · PRD `{prd}`" if prd else "") + "_"]
    if landed:
        head.append("")
        head.append("_Amended " + ", ".join(
            f"{c.get('resolved', '?')} · `{c['id']}`" for c in sorted(landed, key=lambda c: c["id"])) + "_")
    block = head + [""]
    for feature in sorted(shipped, key=lambda f: f["id"]):
        block.append(f"### {feature['title']} (`{feature['id']}`)")
        block.append("")
        block.append(feature["summary"] or "_No summary recorded._")
        block.append("")
        for req in feature["requirements"]:
            body = SUPERSEDED_MARK.sub("", AMENDED_MARK.sub("", req["text"])).rstrip()
            change = amended.get(req["id"])
            if change is None:
                block.append(f"- `{req['id']}` {body}")
            elif change.get("outcome") == "delivered":
                block.append(f"- `{req['id']}` {body} _(amended {change.get('resolved', '?')} · "
                             f"`{change['id']}`)_")
            else:
                # Absorbed but not delivered: the shipped truth is what it said before.
                block.append(f"- `{req['id']}` {body} _(a change is absorbed into the spec but "
                             f"has not shipped — `{change['id']}`)_")
        if not feature["requirements"]:
            block.append("- _No approved requirements recorded._")
        block.append("")

    if marker in text:
        before, rest = text.split(marker, 1)
        after = ""
        nxt = re.search(r"^## ", rest, re.M)
        if nxt:
            after = rest[nxt.start():]
        lines = [before.rstrip(), ""] + block + ([after.rstrip()] if after else [])
    else:
        lines = [text.rstrip(), ""] + block
    _write_atomic(path, "\n".join(lines).rstrip() + "\n")
    emit({"as_built": str(path.relative_to(root)), "phase": args.phase,
          "features": [f["id"] for f in shipped],
          "requirements": sum(len(f["requirements"]) for f in shipped)})


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Phase handoff for the fdw discovery store")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("preflight", help="what would go, what is blocked, and what it costs")
    p.add_argument("--root", required=True)
    p.add_argument("--phase", required=True)
    p.add_argument("--id", action="append", help="limit to specific features")
    p.add_argument("--out", default=None, help="also write the HTML blocker report here")
    p.set_defaults(func=cmd_preflight)

    p = sub.add_parser("bundle", help="assemble the bundle bmad-prd reads")
    p.add_argument("--root", required=True)
    p.add_argument("--phase", required=True)
    p.add_argument("--id", action="append", help="bundle only these; omit for every eligible feature")
    p.add_argument("--date", default=None)
    p.add_argument("--accept-open-blockers", dest="accept_open_blockers", action="store_true",
                   help="bundle even though critical questions are open; recorded in the bundle")
    p.add_argument("--reason", default=None, help="why, when overriding")
    p.set_defaults(func=cmd_bundle)

    p = sub.add_parser("as-built", help="append what this phase shipped to the rolling baseline")
    p.add_argument("--root", required=True)
    p.add_argument("--phase", required=True)
    p.add_argument("--date", default=None)
    p.add_argument("--rebuild", action="store_true",
                   help="regenerate this phase's section from the current specs")
    p.add_argument("--prd-path", dest="prd_path", default=None,
                   help="override; phase.json only carries it once phase-close has run")
    p.set_defaults(func=cmd_as_built)

    p = sub.add_parser("build-brief", help="intent file for bmad-build: an urgent change to delivered work")
    p.add_argument("--root", required=True)
    p.add_argument("--change-id", dest="change_id", required=True)
    p.add_argument("--type", default="bugfix", choices=["feature", "bugfix", "refactor", "chore"])
    p.add_argument("--date", default=None)
    p.add_argument("--out", default=None)
    p.add_argument("--max-requirements", dest="max_requirements", type=int, default=8,
                   help="how much delivered context to carry; what is dropped is reported")
    p.set_defaults(func=cmd_build_brief)

    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
