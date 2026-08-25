#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Renders the fdw discovery store as a dashboard. Read-only: this script has no write
path into the store, so the view can never become the place a fact lives.

Prints a JSON summary to stdout. With --out, also writes a self-contained HTML dashboard.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

LIFECYCLE = [
    "candidate",
    "sliced",
    "designing",
    "client-review",
    "design-approved",
    "speccing",
    "spec-approved",
    "handed-off",
    "shipped",
]
STATUS_LABEL = {
    "candidate": "Candidate",
    "sliced": "Sliced",
    "designing": "Designing",
    "client-review": "With client",
    "design-approved": "Design approved",
    "speccing": "Speccing",
    "spec-approved": "Spec approved",
    "handed-off": "Handed off",
    "shipped": "Shipped",
}
OWNER_LABEL = {"client": "Client", "internal": "Internal", "dev": "Dev"}
SIZES = ["XS", "S", "M", "L", "XL"]
DONE = {"handed-off", "shipped"}


def phase_key(label: str) -> tuple[int, ...]:
    """Sort phases by numeric label, not by position in the registry list. A brownfield store
    starts at whatever phase the project is really on, so insertion order is not chronology.
    Mirrors the helper in fdw_state.py; five lines are cheaper than a cross-skill import."""
    nums = re.findall(r"\d+", label or "")
    return tuple(int(n) for n in nums) or (0,)



def die(message: str) -> None:
    print(json.dumps({"ok": False, "errors": [message]}, indent=2))
    sys.exit(1)


def read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return default


def days_since(stamp: str | None) -> int | None:
    if not stamp:
        return None
    try:
        return (date.today() - date.fromisoformat(str(stamp)[:10])).days
    except ValueError:
        return None


# ---------------------------------------------------------------- gather


def collect(root: Path, phase_filter: str | None) -> dict[str, Any]:
    registry = read_json(root / "registry.json")
    if registry is None:
        die(f"No discovery store at {root}. Run fdw-intake on a source document to create one.")

    unreadable: list[str] = []
    board: list[dict[str, Any]] = []
    blockers: list[dict[str, Any]] = []

    for feature in registry.get("features", []):
        if phase_filter and feature.get("phase") != phase_filter:
            continue
        fdir = root / "phases" / feature["phase"] / "features" / f"{feature['id']}-{feature['slug']}"
        record = read_json(fdir / "feature.json")
        if record is None:
            unreadable.append(feature["id"])
            record = {}
        open_q = [q for q in record.get("questions", []) if q.get("status", "open") == "open"]
        entry = {
            "id": feature["id"],
            "title": feature["title"],
            "status": feature.get("status", "candidate"),
            "phase": feature.get("phase"),
            "size": feature.get("size"),
            "flags": feature.get("flags", []),
            "depends_on": feature.get("depends_on", []),
            "overlaps": feature.get("overlaps", []),
            "summary": record.get("summary", ""),
            "critical": sum(1 for q in open_q if q.get("criticality") == "critical"),
            "non_critical": sum(1 for q in open_q if q.get("criticality") != "critical"),
            "updated": feature.get("updated"),
            "stale_days": days_since(feature.get("updated")),
            "has_design": (fdir / "design").exists() and any((fdir / "design").iterdir())
            if (fdir / "design").exists()
            else False,
            "has_spec": (fdir / "spec.md").exists(),
            # A count, not a boolean: the file existing was true forever once one change had ever
            # been raised, so the dashboard said "changes" on a feature with nothing open.
            "open_changes": len([c for c in record.get("changes", [])
                                 if c.get("status", "open") == "open"]),
            "delivered_changes": len([c for c in record.get("changes", [])
                                      if c.get("outcome") == "delivered"]),
            "has_changes": any(c.get("status", "open") == "open"
                               for c in record.get("changes", [])),
        }
        board.append(entry)
        for question in open_q:
            blockers.append(
                {
                    "id": question.get("id"),
                    "feature_id": feature["id"],
                    "feature_title": feature["title"],
                    "text": question.get("text", ""),
                    "criticality": question.get("criticality", "critical"),
                    "owner": question.get("owner", "client"),
                    "raised": question.get("raised"),
                    "age_days": days_since(question.get("raised")),
                }
            )

    phases = []
    for name in sorted(registry.get("phases", []), key=phase_key):
        record = read_json(root / "phases" / name / "phase.json", {})
        members = [f for f in board if f["phase"] == name]
        phases.append(
            {
                "phase": name,
                "status": record.get("status", "open"),
                "opened": record.get("opened"),
                "closed": record.get("closed"),
                "exit_criteria": record.get("exit_criteria", []),
                "prd_path": record.get("prd_path"),
                "blocker_count_at_handoff": record.get("blocker_count_at_handoff"),
                "features": len(members),
                "done": sum(1 for f in members if f["status"] in DONE),
                "critical_open": sum(f["critical"] for f in members),
            }
        )

    sources = read_json(root / "sources" / "index.json", {}).get("sources", [])
    activity = [
        {"date": s.get("ingested") or s.get("date"), "kind": "source", "text": f"Ingested {s.get('title') or s.get('source_id')}"}
        for s in sources[-8:]
    ]
    decisions_file = root / "decisions.md"
    if decisions_file.exists():
        lines = [ln.strip() for ln in decisions_file.read_text(encoding="utf-8").splitlines() if ln.strip().startswith("- ")]
        for line in lines[-10:]:
            match = re.match(r"^-\s+(\d{4}-\d{2}-\d{2})\s+·\s+(\w+)\s+·\s+(.*)$", line)
            if match:
                activity.append({"date": match.group(1), "kind": match.group(2), "text": match.group(3)})
            else:
                activity.append({"date": None, "kind": "note", "text": line[2:]})
    activity.sort(key=lambda a: (a["date"] or "0000-00-00"), reverse=True)

    return {
        "registry": registry,
        "board": board,
        "blockers": blockers,
        "phases": phases,
        "activity": activity[:12],
        "unreadable": unreadable,
        "sources": len(sources),
    }


# ---------------------------------------------------------------- derive


def build_order(board: list[dict[str, Any]]) -> tuple[list[list[str]], list[str]]:
    """Topological layers over depends_on. Layer 0 is buildable now. Returns
    (layers, cycle_members) — a cycle is reported, not resolved; that is fdw-consistency's call."""
    ids = {f["id"] for f in board}
    deps = {f["id"]: [d for d in f["depends_on"] if d in ids] for f in board}
    layers: list[list[str]] = []
    placed: set[str] = set()
    while len(placed) < len(ids):
        layer = sorted(fid for fid in ids if fid not in placed and all(d in placed for d in deps[fid]))
        if not layer:
            return layers, sorted(ids - placed)
        layers.append(layer)
        placed.update(layer)
    return layers, []


def mermaid(board: list[dict[str, Any]]) -> str:
    ids = {f["id"] for f in board}
    lines = ["graph LR"]
    for feature in board:
        lines.append(f'  {feature["id"].replace("-", "")}["{feature["id"]} {feature["title"]}"]')
    for feature in board:
        for dep in feature["depends_on"]:
            if dep in ids:
                lines.append(f'  {dep.replace("-", "")} --> {feature["id"].replace("-", "")}')
    for a, b in overlap_pairs(board):
        lines.append(f'  {a.replace("-", "")} -.overlaps.- {b.replace("-", "")}')
    return "\n".join(lines)


def overlap_pairs(board: list[dict[str, Any]]) -> list[tuple[str, str]]:
    """Overlap is symmetric but is usually recorded on one side only, so pair by
    sorted tuple rather than trusting both features to declare each other."""
    ids = {f["id"] for f in board}
    pairs = {
        tuple(sorted((f["id"], other)))
        for f in board
        for other in f["overlaps"]
        if other in ids and other != f["id"]
    }
    return sorted(pairs)


def digest(data: dict[str, Any], derived: dict[str, Any]) -> str:
    board, blockers = data["board"], data["blockers"]
    registry = data["registry"]
    if not board:
        return "Discovery store is empty. Run fdw-intake on a source document to get started."
    by_status: dict[str, int] = {}
    for feature in board:
        by_status[feature["status"]] = by_status.get(feature["status"], 0) + 1
    # Label honestly: naming the current phase while counting every phase reads as a
    # per-phase count and quietly misstates where the work is.
    phases_seen = {f["phase"] for f in board}
    scope_label = (
        next(iter(phases_seen)) if len(phases_seen) == 1
        else f"{len(phases_seen)} phases (current {registry.get('current_phase', 'phase-1')})"
    )
    parts = [
        f"{scope_label}: {len(board)} features — "
        + ", ".join(f"{n} {STATUS_LABEL.get(s, s).lower()}" for s, n in
                    sorted(by_status.items(), key=lambda kv: LIFECYCLE.index(kv[0]) if kv[0] in LIFECYCLE else 99))
    ]
    critical = [b for b in blockers if b["criticality"] == "critical"]
    if critical:
        owners: dict[str, int] = {}
        for blocker in critical:
            owners[blocker["owner"]] = owners.get(blocker["owner"], 0) + 1
        parts.append(
            f"{len(critical)} critical blocker{'s' if len(critical) != 1 else ''} open ("
            + ", ".join(f"{n} on {OWNER_LABEL.get(o, o).lower()}" for o, n in sorted(owners.items()))
            + ")"
        )
        oldest = max((b for b in critical if b["age_days"] is not None), key=lambda b: b["age_days"], default=None)
        if oldest and oldest["age_days"] and oldest["age_days"] > 7:
            parts.append(f"oldest has been open {oldest['age_days']} days ({oldest['feature_title']})")
    else:
        parts.append("no critical blockers open")
    ready = [f["id"] for f in board if f["status"] == "spec-approved"]
    if ready:
        parts.append(f"{len(ready)} ready to bundle: {', '.join(ready)}")
    if derived["cycles"]:
        parts.append(f"dependency cycle involving {', '.join(derived['cycles'])} — run fdw-consistency")
    if data["unreadable"]:
        parts.append(f"{len(data['unreadable'])} feature record(s) unreadable — run fdw-intake's validate intent")
    return ". ".join(parts) + "."


def summarize(root: Path, phase_filter: str | None) -> dict[str, Any]:
    data = collect(root, phase_filter)
    board = data["board"]
    layers, cycles = build_order(board)
    by_id = {f["id"]: f for f in board}
    derived = {
        "layers": [
            [{"id": fid, "title": by_id[fid]["title"], "status": by_id[fid]["status"], "size": by_id[fid]["size"]}
             for fid in layer]
            for layer in layers
        ],
        "cycles": cycles,
    }
    overlaps = overlap_pairs(board)
    counts: dict[str, int] = {status: 0 for status in LIFECYCLE}
    sizes: dict[str, int] = {size: 0 for size in SIZES}
    for feature in board:
        counts[feature["status"]] = counts.get(feature["status"], 0) + 1
        if feature["size"] in sizes:
            sizes[feature["size"]] += 1

    return {
        "ok": True,
        "root": str(root),
        "generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "current_phase": data["registry"].get("current_phase"),
        "phase_filter": phase_filter,
        "totals": {
            "features": len(board),
            "sources": data["sources"],
            "by_status": counts,
            "by_size": sizes,
            "flagged": sum(1 for f in board if f["flags"]),
            "critical_blockers": sum(1 for b in data["blockers"] if b["criticality"] == "critical"),
            "open_questions": len(data["blockers"]),
        },
        "board": board,
        "blockers": sorted(
            data["blockers"],
            key=lambda b: (b["criticality"] != "critical", -(b["age_days"] or 0)),
        ),
        "phases": data["phases"],
        "build_order": derived["layers"],
        "cycles": cycles,
        "overlaps": [list(pair) for pair in overlaps],
        "trend": [
            {"phase": p["phase"], "blockers_at_handoff": p["blocker_count_at_handoff"]}
            for p in data["phases"]
            if p["blocker_count_at_handoff"] is not None
        ],
        "activity": data["activity"],
        "unreadable": data["unreadable"],
        "digest": digest(data, derived),
    }


# ---------------------------------------------------------------- render


def esc(text: Any) -> str:
    return html.escape(str(text if text is not None else ""))


CSS = """
*{box-sizing:border-box}
:root{
  --bg:#f7f7f5;--panel:#fff;--ink:#1b1b18;--muted:#6b6b63;--line:#e3e3dd;
  --crit:#b4423a;--warn:#a8712a;--ok:#3f7a4a;--accent:#2f5d8a;--chip:#efefe9;
}
@media (prefers-color-scheme:dark){:root{
  --bg:#16171a;--panel:#1e2024;--ink:#e9e9e4;--muted:#9a9a92;--line:#31343a;
  --crit:#e0776d;--warn:#d6a15c;--ok:#7fb98a;--accent:#7fa8d4;--chip:#282b30;
}}
body{margin:0;padding:20px;background:var(--bg);color:var(--ink);
  font:15px/1.55 ui-sans-serif,-apple-system,'Segoe UI',Roboto,sans-serif}
.wrap{max-width:1080px;margin:0 auto}
h1{font-size:22px;margin:0 0 2px}
h2{font-size:14px;text-transform:uppercase;letter-spacing:.07em;color:var(--muted);
  margin:28px 0 10px;font-weight:600}
.sub{color:var(--muted);font-size:13px;margin-bottom:18px}
.digest{background:var(--panel);border:1px solid var(--line);border-left:3px solid var(--accent);
  border-radius:8px;padding:14px 16px;font-size:15px}
.cards{display:flex;flex-wrap:wrap;gap:10px;margin-top:14px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:8px;
  padding:10px 14px;min-width:104px;flex:1 1 104px}
.card .n{font-size:24px;font-weight:650;line-height:1.1}
.card .l{font-size:12px;color:var(--muted)}
.crit .n{color:var(--crit)}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:8px;overflow:hidden}
table{width:100%;border-collapse:collapse;font-size:14px}
th{text-align:left;font-size:11px;text-transform:uppercase;letter-spacing:.06em;
  color:var(--muted);padding:9px 12px;border-bottom:1px solid var(--line);font-weight:600}
td{padding:9px 12px;border-bottom:1px solid var(--line);vertical-align:top}
tr:last-child td{border-bottom:none}
.id{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:12px;color:var(--muted);white-space:nowrap}
.chip{display:inline-block;padding:1px 8px;border-radius:999px;background:var(--chip);
  font-size:11px;white-space:nowrap}
.chip.crit{background:var(--crit);color:#fff}
.chip.flag{background:var(--warn);color:#fff}
.chip.done{background:var(--ok);color:#fff}
.muted{color:var(--muted)}
.q{font-size:14px}
.layer{display:flex;gap:8px;align-items:flex-start;padding:9px 12px;border-bottom:1px solid var(--line)}
.layer:last-child{border-bottom:none}
.layer .n{font-size:11px;color:var(--muted);min-width:64px;padding-top:3px}
.layer .items{display:flex;flex-wrap:wrap;gap:6px}
.bar{height:6px;background:var(--chip);border-radius:3px;overflow:hidden;margin-top:6px}
.bar span{display:block;height:100%;background:var(--ok)}
.empty{padding:16px;color:var(--muted);font-size:14px}
@media(max-width:620px){
  body{padding:12px}
  th:nth-child(4),td:nth-child(4){display:none}
  .card{min-width:calc(50% - 5px)}
}
"""


def render_html(s: dict[str, Any]) -> str:
    t = s["totals"]
    out = [
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>",
        "<meta name='viewport' content='width=device-width,initial-scale=1'>",
        f"<title>Discovery status — {esc(s['current_phase'])}</title>",
        f"<style>{CSS}</style></head><body><div class='wrap'>",
        "<h1>Discovery status</h1>",
        f"<div class='sub'>{esc(s['current_phase'])}"
        + (f" · filtered to {esc(s['phase_filter'])}" if s["phase_filter"] else "")
        + f" · {t['sources']} source{'s' if t['sources'] != 1 else ''} ingested · generated {esc(s['generated'])}</div>",
        f"<div class='digest'>{esc(s['digest'])}</div>",
        "<div class='cards'>",
        f"<div class='card'><div class='n'>{t['features']}</div><div class='l'>Features</div></div>",
        f"<div class='card crit'><div class='n'>{t['critical_blockers']}</div><div class='l'>Critical blockers</div></div>",
        f"<div class='card'><div class='n'>{t['open_questions']}</div><div class='l'>Open questions</div></div>",
        f"<div class='card'><div class='n'>{t['by_status'].get('spec-approved', 0)}</div><div class='l'>Ready to bundle</div></div>",
        f"<div class='card'><div class='n'>{t['flagged']}</div><div class='l'>Flagged</div></div>",
        "</div>",
    ]

    out.append("<h2>Pipeline</h2><div class='panel'>")
    if s["board"]:
        out.append("<table><tr><th>Feature</th><th>Stage</th><th>Open</th><th>Artifacts</th></tr>")
        for f in sorted(s["board"], key=lambda x: (LIFECYCLE.index(x["status"]) if x["status"] in LIFECYCLE else 99, x["id"])):
            flags = "".join(f"<span class='chip flag'>{esc(fl)}</span> " for fl in f["flags"])
            stage_cls = "done" if f["status"] in DONE else ""
            q = []
            if f["critical"]:
                q.append(f"<span class='chip crit'>{f['critical']} critical</span>")
            if f["non_critical"]:
                q.append(f"<span class='chip'>{f['non_critical']} minor</span>")
            artifacts = " ".join(
                f"<span class='chip'>{name}</span>"
                for name, present in (("design", f["has_design"]), ("spec", f["has_spec"]),
                                      (f"{f['open_changes']} open change(s)" if f["open_changes"]
                                       else "changes", f["has_changes"]))
                if present
            )
            size = f"<span class='chip'>{esc(f['size'])}</span> " if f["size"] else ""
            out.append(
                f"<tr><td><span class='id'>{esc(f['id'])}</span> {esc(f['title'])} {size}{flags}"
                + (f"<div class='muted' style='font-size:13px'>{esc(f['summary'])}</div>" if f["summary"] else "")
                + f"</td><td><span class='chip {stage_cls}'>{esc(STATUS_LABEL.get(f['status'], f['status']))}</span></td>"
                + f"<td>{' '.join(q) or '<span class=muted>—</span>'}</td><td>{artifacts or '<span class=muted>—</span>'}</td></tr>"
            )
        out.append("</table>")
    else:
        out.append("<div class='empty'>No features yet. Run fdw-intake on a source document.</div>")
    out.append("</div>")

    out.append("<h2>Blockers by owner</h2><div class='panel'>")
    if s["blockers"]:
        out.append("<table><tr><th>Question</th><th>Owner</th><th>Age</th><th>Feature</th></tr>")
        for b in s["blockers"]:
            crit = "<span class='chip crit'>critical</span> " if b["criticality"] == "critical" else ""
            age = f"{b['age_days']}d" if b["age_days"] is not None else "—"
            out.append(
                f"<tr><td class='q'>{crit}{esc(b['text'])}</td>"
                f"<td><span class='chip'>{esc(OWNER_LABEL.get(b['owner'], b['owner']))}</span></td>"
                f"<td class='muted'>{age}</td>"
                f"<td class='muted'><span class='id'>{esc(b['feature_id'])}</span> {esc(b['feature_title'])}</td></tr>"
            )
        out.append("</table>")
    else:
        out.append("<div class='empty'>Nothing open. Every question raised so far has been answered.</div>")
    out.append("</div>")

    out.append("<h2>Build order</h2><div class='panel'>")
    if s["build_order"]:
        for i, layer in enumerate(s["build_order"]):
            items = " ".join(
                f"<span class='chip'>{esc(item['id'])} {esc(item['title'])}</span>" for item in layer
            )
            label = "buildable now" if i == 0 else f"after wave {i}"
            out.append(f"<div class='layer'><div class='n'>{esc(label)}</div><div class='items'>{items}</div></div>")
    else:
        out.append("<div class='empty'>No features to order.</div>")
    if s["cycles"]:
        out.append(
            f"<div class='empty' style='color:var(--crit)'>Dependency cycle involving "
            f"{esc(', '.join(s['cycles']))} — run fdw-consistency.</div>"
        )
    if s["overlaps"]:
        pairs = ", ".join(f"{esc(a)} ↔ {esc(b)}" for a, b in s["overlaps"])
        out.append(f"<div class='empty'>Overlapping features: {pairs}</div>")
    out.append("</div>")

    out.append("<h2>Phases</h2><div class='panel'><table><tr><th>Phase</th><th>Progress</th><th>Critical open</th><th>PRD</th></tr>")
    for p in s["phases"]:
        pct = int(100 * p["done"] / p["features"]) if p["features"] else 0
        out.append(
            f"<tr><td><strong>{esc(p['phase'])}</strong> <span class='chip'>{esc(p['status'])}</span>"
            + ("".join(f"<div class='muted' style='font-size:13px'>{esc(c)}</div>" for c in p["exit_criteria"]))
            + f"</td><td>{p['done']}/{p['features']} handed off<div class='bar'><span style='width:{pct}%'></span></div></td>"
            + f"<td>{p['critical_open']}</td>"
            + f"<td class='muted'>{esc(p['prd_path']) if p['prd_path'] else '—'}</td></tr>"
        )
    out.append("</table></div>")

    if s["trend"]:
        out.append("<h2>Blockers surviving to handoff</h2><div class='panel'><table><tr><th>Phase</th><th>Count</th></tr>")
        for row in s["trend"]:
            out.append(f"<tr><td>{esc(row['phase'])}</td><td>{row['blockers_at_handoff']}</td></tr>")
        out.append("</table></div>")

    out.append("<h2>Recent activity</h2><div class='panel'>")
    if s["activity"]:
        out.append("<table><tr><th>Date</th><th>What</th></tr>")
        for a in s["activity"]:
            out.append(f"<tr><td class='muted id'>{esc(a['date'] or '—')}</td><td>{esc(a['text'])}</td></tr>")
        out.append("</table>")
    else:
        out.append("<div class='empty'>Nothing recorded yet.</div>")
    out.append("</div>")

    if s["unreadable"]:
        out.append(
            f"<h2>Store health</h2><div class='panel'><div class='empty' style='color:var(--crit)'>"
            f"Unreadable feature records: {esc(', '.join(s['unreadable']))}. "
            f"Run fdw-intake's validate intent.</div></div>"
        )

    out.append("</div></body></html>")
    return "\n".join(out)


# ---------------------------------------------------------------- cli


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Render the fdw discovery store as a dashboard")
    parser.add_argument("--root", required=True, help="discovery store root")
    parser.add_argument("--phase", default=None, help="limit the board to one phase")
    parser.add_argument("--out", default=None, help="write a self-contained HTML dashboard here")
    parser.add_argument("--digest-only", action="store_true", help="print the one-paragraph text digest and nothing else")
    args = parser.parse_args(argv)

    summary = summarize(Path(args.root).resolve(), args.phase)

    if args.digest_only:
        print(summary["digest"])
        return

    if args.out:
        out = Path(args.out).resolve()
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(render_html(summary), encoding="utf-8")
        summary["html"] = str(out)

    summary["mermaid"] = mermaid(summary["board"])
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
