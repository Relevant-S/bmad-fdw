#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["pytest"]
# ///
"""Tests for fdw_phase.py — scope planning and the phase report."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "fdw_phase.py"


def run(*args, expect_ok=True):
    result = subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True)
    payload = json.loads(result.stdout)
    if expect_ok:
        assert payload.get("ok") is True, payload
    else:
        assert payload.get("ok") is False, payload
        assert result.returncode == 1
    return payload


@pytest.fixture
def store(tmp_path):
    """A shipped phase-1 and an open phase-2 carrying work forward."""
    root = tmp_path / "discovery"
    features = [
        {"id": "F-001", "title": "Events agenda", "slug": "events-agenda", "phase": "phase-1",
         "status": "handed-off", "flags": [], "size": "M", "depends_on": [], "overlaps": []},
        {"id": "F-002", "title": "Academy", "slug": "academy", "phase": "phase-2",
         "status": "sliced", "flags": ["deferred"], "size": "XL",
         "depends_on": ["F-001"], "overlaps": ["F-003"]},
        {"id": "F-003", "title": "Certification", "slug": "certification", "phase": "phase-2",
         "status": "sliced", "flags": [], "size": "L", "depends_on": ["F-002"], "overlaps": ["F-002"]},
        {"id": "F-004", "title": "Billing", "slug": "billing", "phase": "phase-2",
         "status": "candidate", "flags": [], "size": None, "depends_on": [], "overlaps": []},
    ]
    (root).mkdir()
    (root / "registry.json").write_text(json.dumps({
        "current_phase": "phase-2", "phases": ["phase-1", "phase-2"], "features": features}))
    questions = {
        "F-002": [{"id": "F-002-Q-01", "criticality": "critical", "owner": "client", "status": "open",
                   "text": "Which parts of Events are reused?"},
                  {"id": "F-002-Q-02", "criticality": "non-critical", "owner": "internal", "status": "open",
                   "text": "Copy?"}],
        "F-003": [{"id": "F-003-Q-01", "criticality": "critical", "owner": "dev", "status": "open",
                   "text": "Certificate format?"}],
    }
    for f in features:
        fdir = root / "phases" / f["phase"] / "features" / f"{f['id']}-{f['slug']}"
        fdir.mkdir(parents=True)
        (fdir / "feature.json").write_text(json.dumps({
            **f, "summary": f"{f['title']} summary", "questions": questions.get(f["id"], [])}))
    (root / "phases/phase-1/phase.json").write_text(json.dumps({
        "phase": "phase-1", "status": "closed", "opened": "2026-01-05", "closed": "2026-03-01",
        "exit_criteria": ["Every feature spec-approved"], "features": ["F-001"],
        "blocker_count_at_handoff": 6, "prd_path": "_bmad-output/prd/prd-phase-1.md",
        "carried_over": {}}))
    (root / "phases/phase-2/phase.json").write_text(json.dumps({
        "phase": "phase-2", "status": "open", "opened": "2026-03-02", "closed": None,
        "exit_criteria": ["Zero critical blockers at handoff"],
        "features": ["F-002", "F-003", "F-004"], "blocker_count_at_handoff": 2,
        "prd_path": None,
        "carried_over": {"from": "phase-1",
                         "questions": [{"id": "F-002-Q-01", "feature": "F-002"}],
                         "features": [{"id": "F-002", "title": "Academy"}],
                         "changes": ["F-002"]}}))
    return root


# ---------------------------------------------------------------- plan


def test_plan_refuses_without_a_store(tmp_path):
    assert "fdw-intake" in run("plan", "--root", str(tmp_path / "no"), expect_ok=False)["errors"][0]


def test_plan_lists_only_what_has_not_shipped(store):
    out = run("plan", "--root", str(store))
    assert [c["id"] for c in out["candidates"]] == ["F-004", "F-002", "F-003"]
    assert "F-001" not in [c["id"] for c in out["candidates"]], "a handed-off feature is not a candidate"


def test_plan_reports_whether_the_current_phase_can_close(store):
    out = run("plan", "--root", str(store))
    assert out["current_phase"] == "phase-2"
    assert out["current_phase_closable"] is False
    assert set(out["current_unfinished"]) == {"F-003", "F-004"}, "a deferred feature does not block a close"


def test_features_that_must_travel_together_are_grouped(store):
    groups = run("plan", "--root", str(store))["move_together"]
    assert groups == [["F-002", "F-003"]], "they depend on and overlap each other"


def test_dependencies_carry_their_phase_and_readiness(store):
    academy = next(c for c in run("plan", "--root", str(store))["candidates"] if c["id"] == "F-002")
    assert academy["depends_on"] == [{"id": "F-001", "phase": "phase-1", "status": "handed-off"}]
    assert academy["blocked_by"] == [], "a handed-off dependency does not block"
    cert = next(c for c in run("plan", "--root", str(store))["candidates"] if c["id"] == "F-003")
    assert cert["blocked_by"] == ["F-002"]


def test_size_rollup_counts_the_unsized_rather_than_guessing(store):
    rollup = run("plan", "--root", str(store))["size_rollup"]
    assert rollup["sized"] == 2 and rollup["unsized"] == 1
    assert rollup["weight"] == 13
    assert rollup["by_size"]["XL"] == 1 and rollup["by_size"]["L"] == 1


def test_plan_surfaces_what_was_carried_into_the_current_phase(store):
    carried = run("plan", "--root", str(store))["carried_into_current"]
    assert carried["from"] == "phase-1"
    assert carried["changes"] == ["F-002"]


def test_plan_says_so_when_there_is_nothing_left(store):
    registry = json.loads((store / "registry.json").read_text())
    for f in registry["features"]:
        f["status"] = "shipped"
    (store / "registry.json").write_text(json.dumps(registry))
    assert "every feature has shipped" in run("plan", "--root", str(store))["note"].lower()


def test_plan_never_writes_to_the_store(store):
    before = {p: p.read_bytes() for p in sorted(store.rglob("*")) if p.is_file()}
    run("plan", "--root", str(store))
    assert {p: p.read_bytes() for p in sorted(store.rglob("*")) if p.is_file()} == before


# ---------------------------------------------------------------- report


def test_report_shows_every_phase_with_its_carry_over(tmp_path, store):
    out_html = tmp_path / "phases.html"
    out = run("report", "--root", str(store), "--out", str(out_html))
    assert out["phases"] == 2
    page = out_html.read_text()
    assert "phase-1" in page and "phase-2" in page
    assert "Carried in from" in page and "1 open change record(s)" in page
    assert "prd-phase-1.md" in page
    assert "Zero critical blockers at handoff" in page


def test_report_charts_the_blocker_trend_across_phases(tmp_path, store):
    out = run("report", "--root", str(store), "--out", str(tmp_path / "p.html"))
    assert out["trend"] == [{"phase": "phase-1", "blockers": 6}, {"phase": "phase-2", "blockers": 2}]
    assert "Blockers surviving to handoff" in (tmp_path / "p.html").read_text()


def test_report_is_self_contained_and_escapes_titles(tmp_path, store):
    registry = json.loads((store / "registry.json").read_text())
    registry["features"][1]["title"] = "Academy <script>alert(1)</script>"
    (store / "registry.json").write_text(json.dumps(registry))
    out_html = tmp_path / "p.html"
    run("report", "--root", str(store), "--out", str(out_html))
    page = out_html.read_text()
    assert "<script>alert(1)</script>" not in page and "&lt;script&gt;" in page
    assert "prefers-color-scheme" in page and "width=device-width" in page
    for absent in ("http://", "https://", "<script src"):
        assert absent not in page


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
