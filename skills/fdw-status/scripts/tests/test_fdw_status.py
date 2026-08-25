#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["pytest"]
# ///
"""Tests for fdw_status.py — the read-only discovery dashboard."""

import json
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "fdw_status.py"


def run(*args, expect_ok=True):
    result = subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True)
    if args and args[0] == "--digest-only" or "--digest-only" in args:
        if expect_ok and result.returncode == 0:
            return result.stdout.strip()
    payload = json.loads(result.stdout)
    if expect_ok:
        assert payload.get("ok") is True, payload
    else:
        assert payload.get("ok") is False, payload
        assert result.returncode == 1
    return payload


def ago(days):
    return (date.today() - timedelta(days=days)).isoformat()


def feature(fid, title, slug, status="sliced", phase="phase-1", **extra):
    base = {
        "id": fid, "title": title, "slug": slug, "phase": phase, "status": status,
        "flags": [], "size": None, "depends_on": [], "overlaps": [],
        "open_questions": {"critical": 0, "non-critical": 0}, "updated": ago(1),
    }
    base.update(extra)
    return base


@pytest.fixture
def store(tmp_path):
    """A store rich enough to reach every panel: dependencies, an overlap, a flag,
    a closed phase carrying a handoff blocker count, and questions of differing age."""
    root = tmp_path / "discovery"
    features = [
        feature("F-001", "Events agenda layout", "events-agenda-layout", status="spec-approved",
                size="M", open_questions={"critical": 0, "non-critical": 0}),
        feature("F-002", "Academy", "academy", status="designing", size="XL",
                depends_on=["F-001"], overlaps=["F-001"], flags=["changed"],
                open_questions={"critical": 2, "non-critical": 1}),
        feature("F-003", "Certification export", "certification-export", status="candidate",
                depends_on=["F-002"], open_questions={"critical": 1, "non-critical": 0}),
        feature("F-100", "Legacy import", "legacy-import", status="shipped", phase="phase-0"),
    ]
    (root / "sources").mkdir(parents=True)
    (root / "registry.json").write_text(json.dumps({
        "contract_version": 1, "current_phase": "phase-1", "next_feature_seq": 4,
        "phases": ["phase-0", "phase-1"], "features": features,
    }))
    (root / "sources" / "index.json").write_text(json.dumps({"sources": [
        {"source_id": "2026-01-05-kickoff", "title": "Kickoff call", "ingested": ago(20)},
        {"source_id": "2026-02-02-academy", "title": "Academy scoping", "ingested": ago(3)},
    ]}))
    (root / "decisions.md").write_text(
        "# Decisions\n\n"
        f"- {ago(3)} · decision · Academy sequenced after Events feedback · source: 2026-02-02-academy\n"
        f"- {ago(3)} · deferred · Certification tracking → phase-2 · out of scope · source: 2026-02-02-academy\n"
    )
    questions = {
        "F-002": [
            {"id": "F-002-Q-01", "text": "Which Events parts are reused?", "criticality": "critical",
             "owner": "client", "status": "open", "raised": ago(19)},
            {"id": "F-002-Q-02", "text": "What tabs per course page?", "criticality": "critical",
             "owner": "client", "status": "open", "raised": ago(2)},
            {"id": "F-002-Q-03", "text": "Preferred empty-state copy?", "criticality": "non-critical",
             "owner": "internal", "status": "open", "raised": ago(2)},
            {"id": "F-002-Q-04", "text": "Answered already", "criticality": "critical",
             "owner": "client", "status": "resolved", "raised": ago(9)},
        ],
        "F-003": [
            {"id": "F-003-Q-01", "text": "Which certificate format?", "criticality": "critical",
             "owner": "dev", "status": "open", "raised": ago(1)},
        ],
    }
    for f in features:
        fdir = root / "phases" / f["phase"] / "features" / f"{f['id']}-{f['slug']}"
        (fdir / "design").mkdir(parents=True)
        record = dict(f, summary=f"{f['title']} summary", aliases=[], sources=[],
                      questions=questions.get(f["id"], []))
        (fdir / "feature.json").write_text(json.dumps(record))
        (fdir / "signal.md").write_text("# signal\n")
    (root / "phases/phase-1/features/F-001-events-agenda-layout/spec.md").write_text("# spec\n")
    # An open change lives in the ledger; changes.md is only the rendered view of it.
    record = json.loads((root / "phases/phase-1/features/F-002-academy/feature.json").read_text())
    record["changes"] = [{"id": "F-002-C-01", "text": "Overlap allowed.", "status": "open",
                          "route": "in-flight"}]
    (root / "phases/phase-1/features/F-002-academy/feature.json").write_text(json.dumps(record))
    (root / "phases/phase-1/features/F-002-academy/changes.md").write_text("# changes\n")
    (root / "phases/phase-1/features/F-002-academy/design/ux-notes.md").write_text("# ux\n")
    (root / "phases/phase-0/phase.json").write_text(json.dumps({
        "phase": "phase-0", "status": "closed", "exit_criteria": [], "features": ["F-100"],
        "blocker_count_at_handoff": 6, "prd_path": "_bmad-output/prd/prd-phase-0.md",
    }))
    (root / "phases/phase-1/phase.json").write_text(json.dumps({
        "phase": "phase-1", "status": "open",
        "exit_criteria": ["Every feature spec-approved", "Zero critical blockers"],
        "features": ["F-001", "F-002", "F-003"], "blocker_count_at_handoff": None, "prd_path": None,
    }))
    return root


# ---------------------------------------------------------------- refusal and degradation


def test_missing_store_names_the_command_that_creates_one(tmp_path):
    payload = run("--root", str(tmp_path / "nope"), expect_ok=False)
    assert "fdw-intake" in payload["errors"][0]


def test_empty_store_renders_rather_than_failing(tmp_path):
    root = tmp_path / "discovery"
    root.mkdir()
    (root / "registry.json").write_text(json.dumps({"current_phase": "phase-1", "phases": [], "features": []}))
    summary = run("--root", str(root), "--out", str(tmp_path / "s.html"))
    assert summary["totals"]["features"] == 0
    assert "empty" in summary["digest"].lower()
    assert (tmp_path / "s.html").exists()


def test_unreadable_feature_record_is_surfaced_not_swallowed(tmp_path, store):
    (store / "phases/phase-1/features/F-002-academy/feature.json").unlink()
    summary = run("--root", str(store))
    assert summary["unreadable"] == ["F-002"]
    assert "validate" in summary["digest"]


# ---------------------------------------------------------------- counting


def test_only_open_questions_count_as_blockers(store):
    summary = run("--root", str(store))
    ids = {b["id"] for b in summary["blockers"]}
    assert "F-002-Q-04" not in ids, "a resolved question is not a blocker"
    assert summary["totals"]["open_questions"] == 4
    assert summary["totals"]["critical_blockers"] == 3


def test_blockers_sort_critical_first_then_oldest(store):
    blockers = run("--root", str(store))["blockers"]
    assert [b["criticality"] for b in blockers] == ["critical", "critical", "critical", "non-critical"]
    assert blockers[0]["id"] == "F-002-Q-01"
    assert blockers[0]["age_days"] >= 19


def test_totals_count_every_phase_unless_filtered(store):
    assert run("--root", str(store))["totals"]["features"] == 4
    filtered = run("--root", str(store), "--phase", "phase-1")
    assert filtered["totals"]["features"] == 3
    assert all(f["phase"] == "phase-1" for f in filtered["board"])


def test_artifact_presence_is_detected_from_the_folder(store):
    board = {f["id"]: f for f in run("--root", str(store))["board"]}
    assert board["F-001"]["has_spec"] is True
    assert board["F-002"]["has_spec"] is False
    assert board["F-002"]["has_changes"] is True
    assert board["F-002"]["open_changes"] == 1
    assert board["F-001"]["has_changes"] is False
    assert board["F-002"]["has_design"] is True
    assert board["F-001"]["has_design"] is False, "an empty design folder is not a design"


# ---------------------------------------------------------------- build order


def test_build_order_layers_by_dependency(store):
    layers = [[i["id"] for i in layer] for layer in run("--root", str(store))["build_order"]]
    assert layers[0] == ["F-001", "F-100"]
    assert layers[1] == ["F-002"]
    assert layers[2] == ["F-003"]


def test_dependency_cycle_is_reported_not_resolved(tmp_path, store):
    registry = json.loads((store / "registry.json").read_text())
    for f in registry["features"]:
        if f["id"] == "F-001":
            f["depends_on"] = ["F-003"]
    (store / "registry.json").write_text(json.dumps(registry))
    summary = run("--root", str(store))
    assert set(summary["cycles"]) == {"F-001", "F-002", "F-003"}
    assert "fdw-consistency" in summary["digest"]


def test_overlaps_are_reported_once_per_pair(store):
    assert run("--root", str(store))["overlaps"] == [["F-001", "F-002"]]


def test_mermaid_carries_edges_for_contexts_that_render_it(store):
    graph = run("--root", str(store))["mermaid"]
    assert "F001 --> F002" in graph
    assert "overlaps" in graph


# ---------------------------------------------------------------- phases and digest


def test_phase_progress_and_handoff_trend(store):
    phases = {p["phase"]: p for p in run("--root", str(store))["phases"]}
    assert phases["phase-0"]["done"] == 1 and phases["phase-0"]["features"] == 1
    assert phases["phase-1"]["critical_open"] == 3
    assert phases["phase-1"]["exit_criteria"][1] == "Zero critical blockers"
    assert run("--root", str(store))["trend"] == [{"phase": "phase-0", "blockers_at_handoff": 6}]


def test_digest_leads_with_what_the_ba_must_act_on(store):
    digest = run("--root", str(store))["digest"]
    assert "3 critical blocker" in digest
    assert "on client" in digest
    assert "19 days" in digest
    assert "ready to bundle: F-001" in digest


def test_digest_only_prints_one_line_of_plain_text(store):
    out = subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(store), "--digest-only"],
        capture_output=True, text=True,
    )
    assert out.returncode == 0
    assert not out.stdout.strip().startswith("{")
    assert "critical blocker" in out.stdout


# ---------------------------------------------------------------- rendering and read-only


def test_html_is_self_contained_and_theme_aware(tmp_path, store):
    out = tmp_path / "dash.html"
    run("--root", str(store), "--out", str(out))
    page = out.read_text()
    assert "prefers-color-scheme" in page
    assert "width=device-width" in page
    for absent in ("http://", "https://", "<script"):
        assert absent not in page, f"dashboard must be self-contained; found {absent}"
    assert "Academy" in page and "Build order" in page and "buildable now" in page


def test_titles_and_questions_are_html_escaped(tmp_path, store):
    registry = json.loads((store / "registry.json").read_text())
    registry["features"][1]["title"] = "Academy <script>alert(1)</script>"
    (store / "registry.json").write_text(json.dumps(registry))
    out = tmp_path / "dash.html"
    run("--root", str(store), "--out", str(out))
    page = out.read_text()
    assert "<script>alert(1)</script>" not in page
    assert "&lt;script&gt;" in page


def test_running_the_dashboard_never_writes_to_the_store(tmp_path, store):
    before = {p: p.read_bytes() for p in sorted(store.rglob("*")) if p.is_file()}
    run("--root", str(store), "--out", str(tmp_path / "dash.html"))
    after = {p: p.read_bytes() for p in sorted(store.rglob("*")) if p.is_file()}
    assert before == after, "fdw-status is derived; it must never write to the store"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))


def test_digest_does_not_label_a_multi_phase_count_with_one_phase(store):
    """Naming the current phase while counting every phase misstates where the work is."""
    digest = run("--root", str(store))["digest"]
    assert digest.startswith("2 phases (current phase-1)")
    assert run("--root", str(store), "--phase", "phase-1")["digest"].startswith("phase-1:")
