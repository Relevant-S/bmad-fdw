#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Scope planning and reporting for fdw-phase.

Phase mechanics — opening, moving, closing — are feature state and live in the shared CLI so
the registry and the folders can never disagree. This script does the two things around them:
works out what could go in the next phase and what has to travel together, and renders the
arc of the engagement across phases.
"""

from __future__ import annotations

import argparse
import html
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any

LIFECYCLE = [
    "candidate", "sliced", "designing", "client-review", "design-approved",
    "speccing", "spec-approved", "handed-off", "shipped",
]
TERMINAL = {"handed-off", "shipped"}
SIZE_WEIGHT = {"XS": 1, "S": 2, "M": 3, "L": 5, "XL": 8}


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


def load(root: Path) -> dict[str, Any]:
    registry = read_json(root / "registry.json")
    if registry is None:
        die([f"No discovery store at {root}. Run fdw-intake first."])
    features = []
    for entry in registry.get("features", []):
        fdir = root / "phases" / entry["phase"] / "features" / f"{entry['id']}-{entry['slug']}"
        record = read_json(fdir / "feature.json", {})
        open_q = [q for q in record.get("questions", []) if q.get("status", "open") == "open"]
        features.append({
            **{k: entry.get(k) for k in ("id", "title", "slug", "phase", "status", "size")},
            "flags": entry.get("flags", []),
            "depends_on": entry.get("depends_on", []),
            "overlaps": entry.get("overlaps", []),
            "summary": record.get("summary", ""),
            "critical_open": sum(1 for q in open_q if q.get("criticality") == "critical"),
            "open": len(open_q),
            "has_spec": (fdir / "spec.md").exists(),
        })
    phases = []
    for name in registry.get("phases", []):
        record = read_json(root / "phases" / name / "phase.json", {}) or {}
        members = [f for f in features if f["phase"] == name]
        phases.append({
            "phase": name,
            "status": record.get("status", "open"),
            "opened": record.get("opened"), "closed": record.get("closed"),
            "exit_criteria": record.get("exit_criteria", []),
            "prd_path": record.get("prd_path"),
            "blocker_count_at_handoff": record.get("blocker_count_at_handoff"),
            "carried_over": record.get("carried_over", {}),
            "members": members,
        })
    return {"registry": registry, "features": features, "phases": phases}


def clusters(features: list[dict[str, Any]], ids: set[str]) -> list[list[str]]:
    """Connected components over depends_on and overlaps, restricted to the candidate set.
    Features in one component move together or the move strands something."""
    parent = {fid: fid for fid in ids}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    for feature in features:
        if feature["id"] not in ids:
            continue
        for other in feature["depends_on"] + feature["overlaps"]:
            if other in ids:
                union(feature["id"], other)
    groups: dict[str, list[str]] = {}
    for fid in ids:
        groups.setdefault(find(fid), []).append(fid)
    return sorted((sorted(g) for g in groups.values()), key=lambda g: (-len(g), g[0]))


def cmd_plan(args: argparse.Namespace) -> None:
    root = Path(args.root).resolve()
    data = load(root)
    current = data["registry"].get("current_phase")
    by_id = {f["id"]: f for f in data["features"]}

    # Candidates are what has not shipped and is not already finished in an open phase.
    candidates = [
        f for f in data["features"]
        if f["status"] not in TERMINAL and "dropped" not in f["flags"]
    ]
    ids = {f["id"] for f in candidates}

    current_members = [f for f in data["features"] if f["phase"] == current]
    unfinished = [f["id"] for f in current_members
                  if f["status"] not in TERMINAL and not ({"deferred", "dropped"} & set(f["flags"]))]

    enriched = []
    for feature in candidates:
        deps = [{"id": d, "phase": by_id[d]["phase"], "status": by_id[d]["status"]}
                for d in feature["depends_on"] if d in by_id]
        enriched.append({
            **{k: feature[k] for k in ("id", "title", "phase", "status", "size", "flags", "summary")},
            "critical_open": feature["critical_open"],
            "has_spec": feature["has_spec"],
            "depends_on": deps,
            "overlaps": feature["overlaps"],
            "weight": SIZE_WEIGHT.get(feature["size"] or "", None),
            "blocked_by": [d["id"] for d in deps if d["status"] not in TERMINAL],
        })
    enriched.sort(key=lambda f: (LIFECYCLE.index(f["status"]), f["id"]))

    groups = clusters(data["features"], ids)
    sized = [f for f in enriched if f["weight"]]
    emit({
        "current_phase": current,
        "target_phase": args.target,
        "current_phase_closable": not unfinished,
        "current_unfinished": unfinished,
        "candidates": enriched,
        "move_together": [g for g in groups if len(g) > 1],
        "size_rollup": {
            "sized": len(sized), "unsized": len(enriched) - len(sized),
            "weight": sum(f["weight"] for f in sized),
            "by_size": {s: sum(1 for f in enriched if f["size"] == s) for s in SIZE_WEIGHT},
        },
        "carried_into_current": next(
            (p["carried_over"] for p in data["phases"] if p["phase"] == current), {}),
        "phases": [{k: p[k] for k in ("phase", "status", "blocker_count_at_handoff", "prd_path")}
                   for p in data["phases"]],
        "note": (
            "Nothing to plan: every feature has shipped or been dropped."
            if not enriched else
            f"{len(enriched)} feature(s) could move. Anything in move_together travels as a unit "
            f"or the move strands a dependency."
        ),
    })


# ---------------------------------------------------------------- report


CSS = """
*{box-sizing:border-box}
:root{--bg:#f8f8f6;--panel:#fff;--ink:#1c1c19;--muted:#6a6a62;--line:#e4e4dd;
 --ok:#3f7a4a;--warn:#a8712a;--crit:#b4423a;--soft:#f0f0ea;--accent:#2f5d8a}
@media(prefers-color-scheme:dark){:root{--bg:#16171a;--panel:#1e2024;--ink:#e9e9e4;--muted:#9a9a92;
 --line:#31343a;--ok:#7fb98a;--warn:#d6a15c;--crit:#e0776d;--soft:#272a2f;--accent:#7fa8d4}}
body{margin:0;padding:22px 18px;background:var(--bg);color:var(--ink);
 font:15px/1.6 ui-sans-serif,-apple-system,'Segoe UI',Roboto,sans-serif}
.wrap{max-width:920px;margin:0 auto}
h1{font-size:22px;margin:0 0 4px}
.sub{color:var(--muted);font-size:13px;margin-bottom:20px}
.phase{background:var(--panel);border:1px solid var(--line);border-radius:9px;
 padding:16px 18px;margin-bottom:14px}
.phase.closed{opacity:.92}
.ph{display:flex;justify-content:space-between;align-items:baseline;gap:10px;flex-wrap:wrap}
.ph h2{font-size:18px;margin:0;text-transform:none;letter-spacing:0;color:var(--ink)}
.chip{display:inline-block;font-size:11px;text-transform:uppercase;letter-spacing:.05em;
 padding:2px 9px;border-radius:999px;background:var(--soft);color:var(--muted)}
.chip.open{background:var(--accent);color:#fff}
.chip.closed{background:var(--ok);color:#fff}
.chip.crit{background:var(--crit);color:#fff}
.dates{color:var(--muted);font-size:13px}
.bar{height:7px;background:var(--soft);border-radius:4px;overflow:hidden;margin:11px 0 8px}
.bar span{display:block;height:100%;background:var(--ok)}
table{width:100%;border-collapse:collapse;font-size:14px;margin-top:8px}
th{text-align:left;font-size:11px;text-transform:uppercase;letter-spacing:.05em;color:var(--muted);
 padding:6px 8px;border-bottom:1px solid var(--line)}
td{padding:6px 8px;border-bottom:1px solid var(--line)}
tr:last-child td{border-bottom:none}
.id{font-family:ui-monospace,Menlo,monospace;font-size:12px;color:var(--muted)}
.crit{color:var(--crit);font-weight:600}
.meta{color:var(--muted);font-size:13px;margin-top:9px}
.carry{background:var(--soft);border-radius:7px;padding:10px 13px;margin-top:11px;font-size:14px}
.trend{display:flex;gap:14px;align-items:flex-end;height:90px;padding:12px 0}
.tcol{display:flex;flex-direction:column;align-items:center;gap:5px;font-size:12px;color:var(--muted)}
.tbar{width:34px;background:var(--crit);border-radius:3px 3px 0 0;min-height:3px}
@media(max-width:600px){body{padding:14px 12px}th:nth-child(3),td:nth-child(3){display:none}}
"""


def esc(x: Any) -> str:
    return html.escape(str(x if x is not None else ""))


def cmd_report(args: argparse.Namespace) -> None:
    root = Path(args.root).resolve()
    data = load(root)
    out = [
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>",
        "<meta name='viewport' content='width=device-width,initial-scale=1'>",
        "<title>Phase report</title>", f"<style>{CSS}</style></head><body><div class='wrap'>",
        "<h1>Phase report</h1>",
        f"<div class='sub'>{len(data['phases'])} phase(s) · {len(data['features'])} feature(s) · "
        f"current {esc(data['registry'].get('current_phase'))} · {date.today().isoformat()}</div>",
    ]

    trend = [p for p in data["phases"] if p["blocker_count_at_handoff"] is not None]
    if len(trend) > 1:
        peak = max(p["blocker_count_at_handoff"] for p in trend) or 1
        out.append("<h2 style='font-size:13px;text-transform:uppercase;letter-spacing:.07em;"
                   "color:var(--muted);margin:6px 0 0'>Blockers surviving to handoff</h2><div class='trend'>")
        for p in trend:
            height = int(70 * p["blocker_count_at_handoff"] / peak)
            out.append(f"<div class='tcol'><div>{p['blocker_count_at_handoff']}</div>"
                       f"<div class='tbar' style='height:{max(height, 3)}px'></div>"
                       f"<div>{esc(p['phase'])}</div></div>")
        out.append("</div>")

    for phase in data["phases"]:
        members = phase["members"]
        done = sum(1 for f in members if f["status"] in TERMINAL)
        deferred = [f for f in members if "deferred" in f["flags"]]
        crit = sum(f["critical_open"] for f in members)
        pct = int(100 * done / len(members)) if members else 0
        out.append(f"<div class='phase {esc(phase['status'])}'>")
        out.append(
            f"<div class='ph'><h2>{esc(phase['phase'])} "
            f"<span class='chip {esc(phase['status'])}'>{esc(phase['status'])}</span>"
            + (f" <span class='chip crit'>{crit} critical open</span>" if crit else "")
            + f"</h2><span class='dates'>{esc(phase['opened'] or '—')}"
            + (f" → {esc(phase['closed'])}" if phase["closed"] else " → open")
            + "</span></div>"
        )
        out.append(f"<div class='bar'><span style='width:{pct}%'></span></div>")
        out.append(f"<div class='meta'>{done}/{len(members)} handed off"
                   + (f" · {len(deferred)} deferred out" if deferred else "")
                   + (f" · {phase['blocker_count_at_handoff']} blocker(s) at handoff"
                      if phase["blocker_count_at_handoff"] is not None else "")
                   + (f" · PRD: {esc(phase['prd_path'])}" if phase["prd_path"] else "")
                   + "</div>")

        if phase["exit_criteria"]:
            out.append("<div class='meta'>Exit criteria: "
                       + "; ".join(esc(c) for c in phase["exit_criteria"]) + "</div>")

        carried = phase.get("carried_over") or {}
        if carried.get("questions") or carried.get("features") or carried.get("changes"):
            bits = []
            if carried.get("features"):
                bits.append(f"{len(carried['features'])} deferred feature(s)")
            if carried.get("questions"):
                bits.append(f"{len(carried['questions'])} open question(s)")
            if carried.get("changes"):
                bits.append(f"{len(carried['changes'])} open change record(s)")
            out.append(f"<div class='carry'><strong>Carried in from "
                       f"{esc(carried.get('from') or 'the previous phase')}:</strong> "
                       + ", ".join(bits) + "</div>")

        if members:
            out.append("<table><tr><th>Feature</th><th>Stage</th><th>Size</th><th>Open</th></tr>")
            for f in sorted(members, key=lambda x: (LIFECYCLE.index(x["status"]), x["id"])):
                flags = "".join(f" <span class='chip'>{esc(fl)}</span>" for fl in f["flags"])
                openq = (f"<span class='crit'>{f['critical_open']} critical</span>"
                         if f["critical_open"] else ("—" if not f["open"] else f"{f['open']} minor"))
                out.append(
                    f"<tr><td><span class='id'>{esc(f['id'])}</span> {esc(f['title'])}{flags}</td>"
                    f"<td>{esc(f['status'])}</td><td>{esc(f['size'] or '—')}</td><td>{openq}</td></tr>")
            out.append("</table>")
        else:
            out.append("<div class='meta'>No features in this phase yet.</div>")
        out.append("</div>")

    out.append("</div></body></html>")
    target = Path(args.out).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(out), encoding="utf-8")
    emit({"report": str(target), "phases": len(data["phases"]), "features": len(data["features"]),
          "trend": [{"phase": p["phase"], "blockers": p["blocker_count_at_handoff"]} for p in trend]})


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Scope planning and reporting for fdw-phase")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("plan", help="what could go in the next phase, and what has to travel together")
    p.add_argument("--root", required=True)
    p.add_argument("--target", default=None, help="the phase being scoped")
    p.set_defaults(func=cmd_plan)

    p = sub.add_parser("report", help="the engagement's arc across every phase")
    p.add_argument("--root", required=True)
    p.add_argument("--out", required=True)
    p.set_defaults(func=cmd_report)

    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
