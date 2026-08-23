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
        changes = (fdir / "changes.md").read_text(encoding="utf-8") if (fdir / "changes.md").exists() else ""
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
            "open_changes": changes.count("resolution: OPEN"),
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
    changes = [{"feature": f["id"], "open": f["open_changes"]} for f in eligible if f["open_changes"]]

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
            f"{len(eligible)} feature(s) ready, {len(critical)} critical blocker(s) would travel into the PRD."
        ),
        "warns_only": True,
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
        "<div class='note'>This report warns; it does not block. Handing off with open blockers is a "
        "decision the BA is allowed to make — the count is recorded on the phase either way.</div>",
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
        (f"{len(blockers)} critical question(s) are still open and travel into the PRD unresolved."
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
    if marker in text:
        die([f"as-built.md already has a '{args.phase}' section. Remove it first if you mean to regenerate."])

    stamp = args.date or date.today().isoformat()
    lines = [text.rstrip(), "", marker, "",
             f"_Shipped {stamp}"
             + (f" · PRD `{data['phase_record'].get('prd_path')}`" if data["phase_record"].get("prd_path") else "")
             + "_", ""]
    for feature in sorted(shipped, key=lambda f: f["id"]):
        lines.append(f"### {feature['title']} (`{feature['id']}`)")
        lines.append("")
        lines.append(feature["summary"] or "_No summary recorded._")
        lines.append("")
        for req in feature["requirements"]:
            lines.append(f"- `{req['id']}` {req['text']}")
        if not feature["requirements"]:
            lines.append("- _No approved requirements recorded._")
        lines.append("")
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
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
    p.set_defaults(func=cmd_bundle)

    p = sub.add_parser("as-built", help="append what this phase shipped to the rolling baseline")
    p.add_argument("--root", required=True)
    p.add_argument("--phase", required=True)
    p.add_argument("--date", default=None)
    p.set_defaults(func=cmd_as_built)

    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
