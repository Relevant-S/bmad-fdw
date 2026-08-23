#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Cross-feature audit for the fdw discovery store.

Everything decidable is decided here: dependency cycles, build order, phase-fit violations,
glossary alias drift, orphan sources, and the question rollup. Everything semantic — is this
really a contradiction, is this really the same feature twice — is handed to the prompt as
ranked candidates. The script never edits a spec and never advances a status.
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
STOPWORDS = {
    "a", "an", "and", "any", "are", "as", "at", "be", "been", "before", "but", "by", "can",
    "cannot", "course", "do", "does", "each", "every", "for", "from", "has", "have", "how",
    "in", "into", "is", "it", "its", "not", "of", "on", "once", "only", "or", "own", "so",
    "than", "that", "the", "their", "them", "then", "there", "these", "they", "this", "to",
    "up", "was", "we", "what", "when", "where", "which", "who", "will", "with", "without",
    "you", "your", "must", "should", "may", "all", "no", "if", "after",
}
WORD = re.compile(r"[a-zA-Z][a-zA-Z-]{2,}")
REQ = re.compile(r"^\s*-\s+(?:\*\*\[(?P<id>[A-Z0-9-]+-R-\d+)\]\*\*\s+)?(?P<body>.+?)\s*$")


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


def terms(text: str) -> set[str]:
    return {w.lower() for w in WORD.findall(text or "") if w.lower() not in STOPWORDS}


def feature_dir(root: Path, entry: dict[str, Any]) -> Path:
    return root / "phases" / entry["phase"] / "features" / f"{entry['id']}-{entry['slug']}"


def requirements_of(text: str) -> list[dict[str, str]]:
    out, inside = [], False
    for line in text.splitlines():
        if re.match(r"^##\s+", line):
            inside = re.match(r"^##\s+Requirements\s*$", line) is not None
            continue
        if not inside or not line.strip().startswith("- "):
            continue
        match = REQ.match(line)
        if match and match.group("body").strip() not in {"_Not written yet._"}:
            out.append({"id": match.group("id") or "", "text": match.group("body")})
    return out


# ---------------------------------------------------------------- load


def load(root: Path, scope_phase: str | None, scope_id: str | None) -> dict[str, Any]:
    registry = read_json(root / "registry.json")
    if registry is None:
        die([f"No discovery store at {root}. Run fdw-intake first."])

    features = []
    for entry in registry.get("features", []):
        fdir = feature_dir(root, entry)
        record = read_json(fdir / "feature.json", {})
        spec_path = fdir / "spec.md"
        spec = spec_path.read_text(encoding="utf-8") if spec_path.exists() else ""
        signal_path = fdir / "signal.md"
        signal = signal_path.read_text(encoding="utf-8") if signal_path.exists() else ""
        features.append({
            "id": entry["id"], "title": entry["title"], "slug": entry["slug"],
            "phase": entry["phase"], "status": entry["status"], "flags": entry.get("flags", []),
            "size": entry.get("size"), "depends_on": entry.get("depends_on", []),
            "overlaps": entry.get("overlaps", []),
            "summary": record.get("summary", ""), "aliases": record.get("aliases", []),
            "questions": record.get("questions", []),
            "sources": record.get("sources", []),
            "has_spec": bool(spec), "requirements": requirements_of(spec),
            "signal_terms": terms(signal),
            "terms": terms(f"{entry['title']} {record.get('summary', '')} "
                           + " ".join(r["text"] for r in requirements_of(spec))),
        })

    in_scope = [
        f for f in features
        if (scope_id is None or f["id"] == scope_id) and (scope_phase is None or f["phase"] == scope_phase)
    ]
    if scope_id and not in_scope:
        die([f"No feature '{scope_id}' in the store."])

    glossary: list[dict[str, Any]] = []
    gpath = root / "glossary.md"
    if gpath.exists():
        for line in gpath.read_text(encoding="utf-8").splitlines():
            match = re.match(r"^-\s+\*\*(.+?)\*\*\s*(?:\((.*?)\))?\s*—\s*(.*)$", line.strip())
            if match:
                glossary.append({
                    "term": match.group(1),
                    "aliases": [a.strip() for a in (match.group(2) or "").split(",") if a.strip()],
                })

    return {
        "registry": registry, "features": features, "scope": in_scope,
        "glossary": glossary,
        "sources": read_json(root / "sources" / "index.json", {}).get("sources", []),
    }


# ---------------------------------------------------------------- decidable findings


def hard_findings(root: Path, data: dict[str, Any]) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    by_id = {f["id"]: f for f in data["features"]}

    # Dependency cycles.
    placed: set[str] = set()
    pending = {f["id"]: [d for d in f["depends_on"] if d in by_id] for f in data["features"]}
    while True:
        layer = [fid for fid, deps in pending.items()
                 if fid not in placed and all(d in placed for d in deps)]
        if not layer:
            break
        placed.update(layer)
    stuck = sorted(set(pending) - placed)
    if stuck:
        found.append({
            "kind": "dependency-cycle", "severity": "high", "features": stuck,
            "detail": f"These features depend on each other in a loop: {', '.join(stuck)}. "
                      f"Nothing in the loop can be built first, so one edge is wrong.",
        })

    for feature in data["scope"]:
        for dep in feature["depends_on"]:
            target = by_id.get(dep)
            if target is None:
                found.append({
                    "kind": "missing-dependency", "severity": "high", "features": [feature["id"]],
                    "detail": f"{feature['id']} depends on '{dep}', which is not in the registry.",
                })
                continue
            if phase_key(target["phase"]) > phase_key(feature["phase"]):
                found.append({
                    "kind": "backward-dependency", "severity": "high",
                    "features": [feature["id"], dep],
                    "detail": f"{feature['id']} is in {feature['phase']} but depends on {dep} in "
                              f"{target['phase']}, which ships later. Move one of them or drop the edge.",
                })
            if "deferred" in target["flags"] or "dropped" in target["flags"]:
                found.append({
                    "kind": "depends-on-deferred", "severity": "high",
                    "features": [feature["id"], dep],
                    "detail": f"{feature['id']} depends on {dep}, which is flagged "
                              f"{[f for f in target['flags'] if f in ('deferred', 'dropped')]}.",
                })

    # A spec-approved feature whose dependency has not been specced cannot be safely bundled.
    for feature in data["scope"]:
        if feature["status"] != "spec-approved":
            continue
        for dep in feature["depends_on"]:
            target = by_id.get(dep)
            if target and LIFECYCLE.index(target["status"]) < LIFECYCLE.index("spec-approved"):
                found.append({
                    "kind": "dependency-not-ready", "severity": "medium",
                    "features": [feature["id"], dep],
                    "detail": f"{feature['id']} is spec-approved but depends on {dep}, which is only "
                              f"'{target['status']}'. Bundling it would hand development a gap.",
                })

    # Glossary alias drift: a spec using a variant the glossary already resolved.
    for feature in data["scope"]:
        if not feature["has_spec"]:
            continue
        body = " ".join(r["text"] for r in feature["requirements"]).lower()
        for term in data["glossary"]:
            for alias in term["aliases"]:
                if alias.lower() and alias.lower() in body and term["term"].lower() not in body:
                    found.append({
                        "kind": "terminology-drift", "severity": "low",
                        "features": [feature["id"]],
                        "detail": f"{feature['id']} uses '{alias}' where the glossary settled on "
                                  f"'{term['term']}'. One term per concept, or the PRD reads like two products.",
                    })

    # Evidence that never became a spec.
    for feature in data["scope"]:
        if feature["signal_terms"] and not feature["has_spec"] and feature["status"] in {
            "design-approved", "speccing", "spec-approved", "handed-off"
        }:
            found.append({
                "kind": "missing-spec", "severity": "high", "features": [feature["id"]],
                "detail": f"{feature['id']} is '{feature['status']}' but has no spec.md.",
            })

    for source in data["sources"]:
        if source.get("outcome") == "no-new-signal":
            continue
        if not source.get("features_touched"):
            found.append({
                "kind": "orphan-source", "severity": "medium", "features": [],
                "detail": f"Source '{source['source_id']}' was ingested but touched no feature. "
                          f"Either it carried nothing, which should have been recorded as such, "
                          f"or something was missed.",
            })
    return found


# ---------------------------------------------------------------- candidates for judgment


def overlap_candidates(scope: list[dict[str, Any]], floor: float, cap: int) -> tuple[list[dict[str, Any]], int]:
    pairs = []
    for i, a in enumerate(scope):
        for b in scope[i + 1:]:
            if not a["terms"] or not b["terms"]:
                continue
            shared = a["terms"] & b["terms"]
            # Overlap coefficient, not Jaccard. One feature is often fully specced while the
            # other is barely described, and Jaccard's union denominator buries exactly the
            # case that matters: "this new feature repeats most of that existing one".
            smaller = min(len(a["terms"]), len(b["terms"]))
            score = len(shared) / smaller if smaller else 0.0
            alias_hit = bool({t.lower() for t in a["aliases"]} & b["terms"]
                             or {t.lower() for t in b["aliases"]} & a["terms"])
            linked = b["id"] in a["overlaps"] or a["id"] in b["overlaps"]
            if score >= floor or alias_hit or linked:
                pairs.append({
                    "pair": [a["id"], b["id"]],
                    "titles": [a["title"], b["title"]],
                    "similarity": round(score, 3),
                    "shared_terms": sorted(shared)[:14],
                    "already_linked": linked,
                    "same_phase": a["phase"] == b["phase"],
                })
    pairs.sort(key=lambda p: -p["similarity"])
    return pairs[:cap], max(0, len(pairs) - cap)


def requirement_candidates(scope: list[dict[str, Any]], cap: int) -> tuple[list[dict[str, Any]], int]:
    """Cross-feature requirement pairs sharing enough significant terms to be worth a read."""
    flat = [
        {"feature": f["id"], "id": r["id"] or "(unnumbered)", "text": r["text"], "terms": terms(r["text"])}
        for f in scope for r in f["requirements"]
    ]
    pairs = []
    for i, a in enumerate(flat):
        for b in flat[i + 1:]:
            if a["feature"] == b["feature"]:
                continue
            shared = a["terms"] & b["terms"]
            if len(shared) >= 3:
                pairs.append({
                    "a": {"feature": a["feature"], "id": a["id"], "text": a["text"]},
                    "b": {"feature": b["feature"], "id": b["id"], "text": b["text"]},
                    "shared_terms": sorted(shared)[:10],
                    "weight": len(shared),
                })
    pairs.sort(key=lambda p: -p["weight"])
    return pairs[:cap], max(0, len(pairs) - cap)


def cmd_scan(args: argparse.Namespace) -> None:
    root = Path(args.root).resolve()
    data = load(root, args.phase, args.id)
    scope = data["scope"]
    overlaps, overlaps_dropped = overlap_candidates(scope, args.similarity, args.max_pairs)
    reqs, reqs_dropped = requirement_candidates(scope, args.max_pairs)

    open_q = [
        {**q, "feature_id": f["id"], "feature_title": f["title"]}
        for f in scope for q in f["questions"] if q.get("status", "open") == "open"
    ]

    emit({
        "root": str(root),
        "scope": {"phase": args.phase, "feature": args.id, "features": len(scope)},
        "features": [
            {k: f[k] for k in ("id", "title", "phase", "status", "size", "flags",
                               "depends_on", "overlaps", "summary", "has_spec")}
            | {"requirements": len(f["requirements"])}
            for f in scope
        ],
        "hard_findings": hard_findings(root, data),
        "overlap_candidates": overlaps,
        "overlap_candidates_dropped": overlaps_dropped,
        "requirement_candidates": reqs,
        "requirement_candidates_dropped": reqs_dropped,
        "open_questions": open_q,
        "glossary": data["glossary"],
        "note": (
            f"{overlaps_dropped} overlap and {reqs_dropped} requirement pairs were ranked lower and "
            f"not listed. Raise --max-pairs to see them."
            if overlaps_dropped or reqs_dropped else "All candidate pairs are listed."
        ),
    })


# ---------------------------------------------------------------- questions rollup


def cmd_rollup(args: argparse.Namespace) -> None:
    """Regenerate the derived top-level questions.md. The contract declares this file derived
    and owned here, so it is rewritten wholesale rather than merged."""
    root = Path(args.root).resolve()
    data = load(root, None, None)
    rows = [
        {**q, "feature_id": f["id"], "feature_title": f["title"], "phase": f["phase"]}
        for f in data["features"] for q in f["questions"] if q.get("status", "open") == "open"
    ]
    rows.sort(key=lambda q: (q.get("criticality") != "critical", q.get("owner", ""), q.get("raised") or ""))

    lines = [
        "# Open Questions", "",
        "Derived rollup — regenerated by fdw-consistency. Do not hand-edit.", "",
        f"_{len(rows)} open · {sum(1 for r in rows if r.get('criticality') == 'critical')} critical · "
        f"generated {date.today().isoformat()}_", "",
    ]
    if not rows:
        lines += ["Nothing open. Every question raised so far has been answered.", ""]
    for owner in ("client", "internal", "dev"):
        block = [r for r in rows if r.get("owner") == owner]
        if not block:
            continue
        lines += [f"## {owner.title()}", ""]
        for row in block:
            mark = "**critical**" if row.get("criticality") == "critical" else "minor"
            lines.append(
                f"- {mark} · `{row['id']}` · {row['feature_id']} {row['feature_title']} "
                f"({row['phase']}) — {row.get('text', '')}"
            )
        lines.append("")
    (root / "questions.md").write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    emit({"questions": str((root / "questions.md").relative_to(root)), "open": len(rows),
          "critical": sum(1 for r in rows if r.get("criticality") == "critical"),
          "by_owner": {o: sum(1 for r in rows if r.get("owner") == o) for o in ("client", "internal", "dev")}})


# ---------------------------------------------------------------- report


SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}
CSS = """
*{box-sizing:border-box}
:root{--bg:#f8f8f6;--panel:#fff;--ink:#1c1c19;--muted:#6a6a62;--line:#e4e4dd;
 --high:#b4423a;--med:#a8712a;--low:#5a7d94;--soft:#f0f0ea}
@media(prefers-color-scheme:dark){:root{--bg:#16171a;--panel:#1e2024;--ink:#e9e9e4;--muted:#9a9a92;
 --line:#31343a;--high:#e0776d;--med:#d6a15c;--low:#8fb0c4;--soft:#272a2f}}
body{margin:0;padding:22px 18px;background:var(--bg);color:var(--ink);
 font:15px/1.6 ui-sans-serif,-apple-system,'Segoe UI',Roboto,sans-serif}
.wrap{max-width:940px;margin:0 auto}
h1{font-size:22px;margin:0 0 4px}
.sub{color:var(--muted);font-size:13px;margin-bottom:18px}
.verdict{background:var(--panel);border:1px solid var(--line);border-left:3px solid var(--low);
 border-radius:8px;padding:14px 16px;margin-bottom:20px}
h2{font-size:13px;text-transform:uppercase;letter-spacing:.07em;color:var(--muted);
 margin:26px 0 10px;font-weight:600}
.f{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:14px 16px;margin-bottom:10px}
.f.high{border-left:3px solid var(--high)}
.f.medium{border-left:3px solid var(--med)}
.f.low{border-left:3px solid var(--low)}
.tag{display:inline-block;font-size:11px;text-transform:uppercase;letter-spacing:.05em;
 padding:1px 8px;border-radius:999px;background:var(--soft);color:var(--muted);margin-right:6px}
.tag.high{background:var(--high);color:#fff}
.tag.medium{background:var(--med);color:#fff}
.ttl{font-weight:600;margin:6px 0 6px}
.ev{background:var(--soft);border-radius:6px;padding:9px 12px;margin:8px 0;font-size:14px}
.ev code{font-size:12px;color:var(--muted)}
.rec{font-size:14px;color:var(--muted);margin-top:8px}
.rec b{color:var(--ink);font-weight:600}
.order{display:flex;gap:8px;flex-wrap:wrap;align-items:center;padding:10px 0}
.chip{background:var(--soft);border-radius:999px;padding:3px 11px;font-size:13px}
.empty{color:var(--muted);padding:14px 16px;background:var(--panel);border:1px solid var(--line);border-radius:8px}
@media(max-width:600px){body{padding:14px 12px}}
"""


def esc(x: Any) -> str:
    return html.escape(str(x if x is not None else ""))


def cmd_report(args: argparse.Namespace) -> None:
    root = Path(args.root).resolve()
    scan = read_json(Path(args.scan).resolve())
    if scan is None:
        die([f"No scan output at {args.scan}. Run: fdw_consistency.py scan --root {root} > scan.json"])
    judged = read_json(Path(args.findings).resolve(), {}) if args.findings else {}

    findings = list(scan.get("hard_findings", [])) + list(judged.get("findings", []))
    findings.sort(key=lambda f: SEVERITY_ORDER.get(f.get("severity", "low"), 3))

    out = [
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>",
        "<meta name='viewport' content='width=device-width,initial-scale=1'>",
        "<title>Consistency audit</title>", f"<style>{CSS}</style></head><body><div class='wrap'>",
        "<h1>Consistency audit</h1>",
        f"<div class='sub'>{esc(scan['scope']['features'])} features in scope"
        + (f" · {esc(scan['scope']['phase'])}" if scan["scope"].get("phase") else "")
        + f" · {len(findings)} finding{'s' if len(findings) != 1 else ''}"
        + f" · {date.today().isoformat()}</div>",
    ]
    if judged.get("verdict"):
        out.append(f"<div class='verdict'>{esc(judged['verdict'])}</div>")

    if judged.get("ordering"):
        out.append("<h2>Recommended build order</h2><div class='order'>")
        out.append(" <span class='chip'>→</span> ".join(f"<span class='chip'>{esc(x)}</span>"
                                                        for x in judged["ordering"]))
        out.append("</div>")

    out.append("<h2>Findings</h2>")
    if not findings:
        out.append("<div class='empty'>Nothing inconsistent found in this scope.</div>")
    for finding in findings:
        sev = finding.get("severity", "low")
        out.append(f"<div class='f {esc(sev)}'>")
        out.append(f"<span class='tag {esc(sev)}'>{esc(sev)}</span>"
                   f"<span class='tag'>{esc(finding.get('kind', 'finding'))}</span>"
                   + "".join(f"<span class='tag'>{esc(f)}</span>" for f in finding.get("features", [])))
        out.append(f"<div class='ttl'>{esc(finding.get('summary') or finding.get('detail', ''))}</div>")
        if finding.get("summary") and finding.get("detail"):
            out.append(f"<div>{esc(finding['detail'])}</div>")
        for item in finding.get("evidence", []):
            out.append(f"<div class='ev'><code>{esc(item.get('ref', ''))}</code> — {esc(item.get('text', ''))}</div>")
        if finding.get("recommendation"):
            out.append(f"<div class='rec'><b>Do this:</b> {esc(finding['recommendation'])}</div>")
        out.append("</div>")

    if judged.get("commands"):
        out.append("<h2>Edges to record</h2><div class='f low'>")
        for cmd in judged["commands"]:
            out.append(f"<div class='ev'><code>{esc(cmd)}</code></div>")
        out.append("</div>")

    if scan.get("note") and "not listed" in scan["note"]:
        out.append(f"<h2>Coverage</h2><div class='empty'>{esc(scan['note'])}</div>")

    out.append("</div></body></html>")
    target = Path(args.out).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(out), encoding="utf-8")

    counts: dict[str, int] = {}
    for finding in findings:
        counts[finding.get("severity", "low")] = counts.get(finding.get("severity", "low"), 0) + 1
    emit({"report": str(target), "findings": len(findings), "by_severity": counts,
          "commands": judged.get("commands", [])})


# ---------------------------------------------------------------- cli


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Cross-feature audit for the fdw discovery store")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("scan", help="decidable findings plus ranked candidates for judgment")
    p.add_argument("--root", required=True)
    p.add_argument("--phase", default=None, help="limit to one phase")
    p.add_argument("--id", default=None, help="limit to one feature")
    p.add_argument("--similarity", type=float, default=0.18, help="overlap candidate floor")
    p.add_argument("--max-pairs", type=int, default=40, dest="max_pairs")
    p.set_defaults(func=cmd_scan)

    p = sub.add_parser("rollup", help="regenerate the derived top-level questions.md")
    p.add_argument("--root", required=True)
    p.set_defaults(func=cmd_rollup)

    p = sub.add_parser("report", help="render the audit report from a scan and the judged findings")
    p.add_argument("--root", required=True)
    p.add_argument("--scan", required=True)
    p.add_argument("--findings", default=None)
    p.add_argument("--out", required=True)
    p.set_defaults(func=cmd_report)

    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
