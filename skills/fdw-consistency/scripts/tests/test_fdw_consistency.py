#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["pytest"]
# ///
"""Tests for fdw_consistency.py — decidable findings, ranked candidates, rollup, report."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "fdw_consistency.py"


def run(*args, expect_ok=True):
    result = subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True)
    payload = json.loads(result.stdout)
    if expect_ok:
        assert payload.get("ok") is True, payload
    else:
        assert payload.get("ok") is False, payload
        assert result.returncode == 1
    return payload


def spec_with(requirements):
    body = "\n".join(f"- {r}" for r in requirements)
    return (
        "# Spec\n\n**Feature:** X · **Status:** approved\n**Size:** M\n\n"
        f"## Need\n\nsomething\n\n## Requirements\n\n{body}\n\n## Out of scope\n\nnothing\n"
    )


@pytest.fixture
def store(tmp_path):
    """Two phases, a fully specced feature and a thin one, an overlap edge, and a glossary."""
    root = tmp_path / "discovery"
    (root / "sources").mkdir(parents=True)
    features = [
        {"id": "F-001", "title": "Academy", "slug": "academy", "phase": "phase-1",
         "status": "spec-approved", "flags": [], "size": "XL",
         "depends_on": ["F-002"], "overlaps": ["F-002"]},
        {"id": "F-002", "title": "Events agenda", "slug": "events-agenda", "phase": "phase-1",
         "status": "designing", "flags": [], "size": "M", "depends_on": [], "overlaps": ["F-001"]},
        {"id": "F-003", "title": "Billing", "slug": "billing", "phase": "phase-2",
         "status": "sliced", "flags": [], "size": "L", "depends_on": [], "overlaps": []},
    ]
    (root / "registry.json").write_text(json.dumps({
        "current_phase": "phase-1", "phases": ["phase-1", "phase-2"], "features": features}))
    (root / "sources" / "index.json").write_text(json.dumps({"sources": [
        {"source_id": "2026-01-05-kickoff", "features_touched": ["F-001", "F-002"]},
    ]}))
    (root / "glossary.md").write_text(
        "# Glossary\n\n- **session** (спєсія, sesija) — a dated occurrence learners attend\n")
    questions = {
        "F-001": [{"id": "F-001-Q-01", "text": "Which parts are reused?", "criticality": "critical",
                   "owner": "client", "status": "open", "raised": "2026-01-05"},
                  {"id": "F-001-Q-02", "text": "Copy?", "criticality": "non-critical",
                   "owner": "internal", "status": "open", "raised": "2026-01-06"},
                  {"id": "F-001-Q-03", "text": "Done", "criticality": "critical",
                   "owner": "client", "status": "resolved"}],
        "F-002": [{"id": "F-002-Q-01", "text": "Which timezone?", "criticality": "critical",
                   "owner": "dev", "status": "open", "raised": "2026-01-07"}],
        "F-003": [],
    }
    for f in features:
        fdir = root / "phases" / f["phase"] / "features" / f"{f['id']}-{f['slug']}"
        fdir.mkdir(parents=True)
        (fdir / "feature.json").write_text(json.dumps({
            **f, "summary": f"{f['title']} summary", "aliases": [],
            "sources": ["2026-01-05-kickoff"], "questions": questions[f["id"]]}))
        (fdir / "signal.md").write_text("# signal\n- evidence about sessions and agenda\n")
    academy = root / "phases/phase-1/features/F-001-academy"
    (academy / "spec.md").write_text(spec_with([
        "**[F-001-R-01]** A session appears on the agenda calendar with a start time. [from: A1]",
        "**[F-001-R-02]** Agenda content sizes to fit instead of being clipped. [from: A2]",
        "**[F-001-R-03]** A learner enrols on a course before any session exists. [from: A3]",
    ]))
    (root / "phases/phase-1/features/F-002-events-agenda/spec.md").write_text(spec_with([
        "**[F-002-R-01]** A session appears on the agenda calendar with a start time. [from: A1]",
        "**[F-002-R-02]** Agenda content is clipped to the calendar row height. [from: A4]",
    ]))
    return root


def edit_registry(store, fn):
    registry = json.loads((store / "registry.json").read_text())
    fn(registry)
    (store / "registry.json").write_text(json.dumps(registry))


def kinds(payload):
    return [f["kind"] for f in payload["hard_findings"]]


# ---------------------------------------------------------------- decidable findings


def test_no_store_names_the_fix(tmp_path):
    payload = run("scan", "--root", str(tmp_path / "nope"), expect_ok=False)
    assert "fdw-intake" in payload["errors"][0]


def test_dependency_cycle_is_reported_with_every_member(store):
    edit_registry(store, lambda r: r["features"][1].update({"depends_on": ["F-001"]}))
    finding = next(f for f in run("scan", "--root", str(store))["hard_findings"]
                   if f["kind"] == "dependency-cycle")
    assert set(finding["features"]) == {"F-001", "F-002"}
    assert finding["severity"] == "high"


def test_a_dependency_on_a_later_phase_is_caught(store):
    edit_registry(store, lambda r: r["features"][0].update({"depends_on": ["F-003"]}))
    finding = next(f for f in run("scan", "--root", str(store))["hard_findings"]
                   if f["kind"] == "backward-dependency")
    assert "ships later" in finding["detail"]


def test_a_dependency_on_a_deferred_feature_is_caught(store):
    edit_registry(store, lambda r: r["features"][1].update({"flags": ["deferred"]}))
    assert "depends-on-deferred" in kinds(run("scan", "--root", str(store)))


def test_an_approved_spec_waiting_on_an_unspecced_dependency_is_caught(store):
    finding = next(f for f in run("scan", "--root", str(store))["hard_findings"]
                   if f["kind"] == "dependency-not-ready")
    assert finding["features"] == ["F-001", "F-002"]
    assert "hand development a gap" in finding["detail"]


def test_missing_spec_on_an_advanced_feature_is_caught(store):
    (store / "phases/phase-1/features/F-001-academy/spec.md").unlink()
    assert "missing-spec" in kinds(run("scan", "--root", str(store)))


def test_glossary_alias_used_instead_of_the_settled_term(store):
    path = store / "phases/phase-2/features/F-003-billing/spec.md"
    path.write_text(spec_with(["**[F-003-R-01]** Each sesija is invoiced separately. [from: A1]"]))
    finding = next(f for f in run("scan", "--root", str(store))["hard_findings"]
                   if f["kind"] == "terminology-drift")
    assert "sesija" in finding["detail"] and "session" in finding["detail"]


def test_a_source_that_touched_nothing_is_flagged(store):
    (store / "sources" / "index.json").write_text(json.dumps({"sources": [
        {"source_id": "2026-02-01-status", "features_touched": []}]}))
    assert "orphan-source" in kinds(run("scan", "--root", str(store)))


def test_a_source_recorded_as_carrying_nothing_is_not_flagged(store):
    (store / "sources" / "index.json").write_text(json.dumps({"sources": [
        {"source_id": "2026-02-01-status", "features_touched": [], "outcome": "no-new-signal"}]}))
    assert "orphan-source" not in kinds(run("scan", "--root", str(store)))


# ---------------------------------------------------------------- candidates for judgment


def test_a_thin_feature_still_surfaces_against_a_fully_specced_one(store):
    """The canonical case: 'Academy repeats 90% of Events' where only one side is written up.
    Jaccard's union denominator buries this; the overlap coefficient does not."""
    top = run("scan", "--root", str(store))["overlap_candidates"][0]
    assert top["pair"] == ["F-001", "F-002"]
    assert top["similarity"] > 0.3
    assert top["already_linked"] is True


def test_an_existing_overlap_edge_always_surfaces_however_low_it_scores(store):
    edit_registry(store, lambda r: r["features"][2].update({"overlaps": ["F-001"]}))
    edit_registry(store, lambda r: r["features"][0].update({"overlaps": ["F-002", "F-003"]}))
    pairs = {tuple(c["pair"]) for c in run("scan", "--root", str(store), "--similarity", "0.99")["overlap_candidates"]}
    assert ("F-001", "F-003") in pairs


def test_requirement_pairs_pair_across_features_only(store):
    pairs = run("scan", "--root", str(store))["requirement_candidates"]
    assert pairs, "the two agenda requirements should be offered for comparison"
    assert all(p["a"]["feature"] != p["b"]["feature"] for p in pairs)
    top = pairs[0]
    assert {top["a"]["id"], top["b"]["id"]} == {"F-001-R-01", "F-002-R-01"}


def test_the_contradicting_agenda_requirements_are_offered_for_judgment(store):
    pairs = run("scan", "--root", str(store))["requirement_candidates"]
    assert any({p["a"]["id"], p["b"]["id"]} == {"F-001-R-02", "F-002-R-02"} for p in pairs), \
        "'sizes to fit' vs 'is clipped' must reach the model to be judged a contradiction"


def test_dropped_candidates_are_reported_rather_than_silently_truncated(store):
    out = run("scan", "--root", str(store), "--max-pairs", "1")
    assert out["requirement_candidates_dropped"] > 0
    assert "not listed" in out["note"] and "--max-pairs" in out["note"]


def test_scope_can_be_narrowed_to_a_phase_or_a_feature(store):
    assert run("scan", "--root", str(store), "--phase", "phase-1")["scope"]["features"] == 2
    assert run("scan", "--root", str(store), "--id", "F-001")["scope"]["features"] == 1
    assert run("scan", "--root", str(store), "--id", "F-404", expect_ok=False)


def test_scan_never_writes_to_the_store(store):
    before = {p: p.read_bytes() for p in sorted(store.rglob("*")) if p.is_file()}
    run("scan", "--root", str(store))
    assert {p: p.read_bytes() for p in sorted(store.rglob("*")) if p.is_file()} == before


# ---------------------------------------------------------------- rollup


def test_rollup_regenerates_questions_grouped_by_owner(store):
    out = run("rollup", "--root", str(store))
    assert out["open"] == 3 and out["critical"] == 2
    assert out["by_owner"] == {"client": 1, "internal": 1, "dev": 1}
    text = (store / "questions.md").read_text()
    assert "## Client" in text and "## Dev" in text
    assert "F-001-Q-03" not in text, "a resolved question is not open"
    assert text.index("F-001-Q-01") < text.index("F-001-Q-02"), "critical first"


def test_rollup_is_idempotent_and_says_so_when_nothing_is_open(store):
    for fid, slug, phase in [("F-001", "academy", "phase-1"), ("F-002", "events-agenda", "phase-1")]:
        path = store / "phases" / phase / "features" / f"{fid}-{slug}" / "feature.json"
        record = json.loads(path.read_text())
        for q in record["questions"]:
            q["status"] = "resolved"
        path.write_text(json.dumps(record))
    run("rollup", "--root", str(store))
    first = (store / "questions.md").read_text()
    run("rollup", "--root", str(store))
    assert (store / "questions.md").read_text() == first
    assert "Every question raised so far has been answered" in first


# ---------------------------------------------------------------- report


def test_report_merges_decidable_and_judged_findings(tmp_path, store):
    scan = tmp_path / "scan.json"
    scan.write_text(json.dumps(run("scan", "--root", str(store))))
    judged = tmp_path / "findings.json"
    judged.write_text(json.dumps({
        "verdict": "Academy repeats most of Events and must follow it.",
        "ordering": ["F-002", "F-001"],
        "commands": ["fdw_state.py feature-set --id F-001 --depends-on F-002"],
        "findings": [{
            "kind": "contradiction", "severity": "high", "features": ["F-001", "F-002"],
            "summary": "Agenda sizing disagrees between the two specs.",
            "evidence": [{"ref": "F-001-R-02", "text": "sizes to fit"},
                         {"ref": "F-002-R-02", "text": "is clipped"}],
            "recommendation": "Apply the Events rework first, then respec Academy against it.",
        }],
    }))
    out_html = tmp_path / "audit.html"
    out = run("report", "--root", str(store), "--scan", str(scan),
              "--findings", str(judged), "--out", str(out_html))
    assert out["by_severity"]["high"] == 1
    page = out_html.read_text()
    assert "Agenda sizing disagrees" in page
    assert "dependency-not-ready" in page, "decidable findings appear alongside judged ones"
    assert "F-001-R-02" in page and "Apply the Events rework first" in page
    assert "prefers-color-scheme" in page
    for absent in ("http://", "https://", "<script"):
        assert absent not in page


def test_report_works_with_no_judged_findings(tmp_path, store):
    scan = tmp_path / "scan.json"
    scan.write_text(json.dumps(run("scan", "--root", str(store))))
    out = run("report", "--root", str(store), "--scan", str(scan), "--out", str(tmp_path / "a.html"))
    assert out["findings"] >= 1


def test_report_escapes_finding_text(tmp_path, store):
    scan = tmp_path / "scan.json"
    scan.write_text(json.dumps(run("scan", "--root", str(store))))
    judged = tmp_path / "f.json"
    judged.write_text(json.dumps({"findings": [
        {"kind": "x", "severity": "low", "summary": "<script>alert(1)</script>"}]}))
    out_html = tmp_path / "a.html"
    run("report", "--root", str(store), "--scan", str(scan), "--findings", str(judged), "--out", str(out_html))
    assert "<script>alert(1)</script>" not in out_html.read_text()


def test_report_without_a_scan_names_the_command(tmp_path, store):
    payload = run("report", "--root", str(store), "--scan", str(tmp_path / "missing.json"),
                  "--out", str(tmp_path / "a.html"), expect_ok=False)
    assert "scan" in payload["errors"][0]


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))


def test_phase_direction_is_judged_by_label_not_registry_position(store):
    """A brownfield store's phases list can be built out of order. Comparing by position
    would call a dependency on an earlier phase 'backwards' and miss the real violation."""
    edit_registry(store, lambda r: r.update({"phases": ["phase-2", "phase-1"]}))
    # F-001 (phase-1) depending on F-003 (phase-2) is a genuine backward dependency.
    edit_registry(store, lambda r: r["features"][0].update({"depends_on": ["F-003"]}))
    finding = next(f for f in run("scan", "--root", str(store))["hard_findings"]
                   if f["kind"] == "backward-dependency")
    assert "ships later" in finding["detail"]


def test_a_dependency_on_a_genuinely_earlier_phase_is_not_flagged(store):
    edit_registry(store, lambda r: r.update({"phases": ["phase-2", "phase-1"]}))
    edit_registry(store, lambda r: r["features"][2].update({"depends_on": ["F-001"]}))
    kinds_found = [f["kind"] for f in run("scan", "--root", str(store))["hard_findings"]]
    assert "backward-dependency" not in kinds_found, \
        "phase-2 depending on phase-1 is the normal shape of phased delivery"
