#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["pytest"]
# ///
"""Tests for fdw_handoff.py — eligibility, the blocker report, the bundle, and as-built."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "fdw_handoff.py"


def run(*args, expect_ok=True):
    result = subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True)
    payload = json.loads(result.stdout)
    if expect_ok:
        assert payload.get("ok") is True, payload
    else:
        assert payload.get("ok") is False, payload
        assert result.returncode == 1
    return payload


def spec(fid, reqs):
    body = "\n".join(f"- **[{fid}-R-{i:02d}]** {r} [from: A1]" for i, r in enumerate(reqs, 1))
    return f"# Spec\n\n**Status:** approved\n**Size:** M\n\n## Requirements\n\n{body}\n"


@pytest.fixture
def store(tmp_path):
    root = tmp_path / "discovery"
    features = [
        {"id": "F-001", "title": "Events agenda", "slug": "events-agenda", "phase": "phase-1",
         "status": "spec-approved", "flags": [], "size": "M", "depends_on": []},
        {"id": "F-002", "title": "Academy", "slug": "academy", "phase": "phase-1",
         "status": "spec-approved", "flags": [], "size": "XL", "depends_on": ["F-001"]},
        {"id": "F-003", "title": "Billing", "slug": "billing", "phase": "phase-1",
         "status": "designing", "flags": [], "size": "L", "depends_on": []},
    ]
    (root).mkdir()
    (root / "registry.json").write_text(json.dumps({
        "current_phase": "phase-1", "phases": ["phase-0", "phase-1"], "features": features}))
    (root / "decisions.md").write_text("# Decisions\n")
    (root / "glossary.md").write_text("# Glossary\n")
    questions = {
        "F-001": [{"id": "F-001-Q-01", "text": "Timezone?", "criticality": "critical",
                   "owner": "client", "status": "open"}],
        "F-002": [{"id": "F-002-Q-01", "text": "Copy?", "criticality": "non-critical",
                   "owner": "internal", "status": "open"},
                  {"id": "F-002-Q-02", "text": "Done", "criticality": "critical",
                   "owner": "client", "status": "resolved"}],
        "F-003": [{"id": "F-003-Q-01", "text": "Which gateway?", "criticality": "critical",
                   "owner": "client", "status": "open"}],
    }
    for f in features:
        fdir = root / "phases/phase-1/features" / f"{f['id']}-{f['slug']}"
        (fdir / "design").mkdir(parents=True)
        (fdir / "feature.json").write_text(json.dumps({
            **f, "summary": f"{f['title']} summary", "questions": questions[f["id"]]}))
        (fdir / "design" / "ux-notes.md").write_text("# ux\n")
    (root / "phases/phase-1/features/F-001-events-agenda/spec.md").write_text(
        spec("F-001", ["Agenda blocks size to content.", "Sessions appear on a calendar."]))
    (root / "phases/phase-1/features/F-002-academy/spec.md").write_text(
        spec("F-002", ["Courses carry tabs."]))
    (root / "phases/phase-0").mkdir(parents=True)
    (root / "phases/phase-0/phase.json").write_text(json.dumps({
        "phase": "phase-0", "status": "closed", "blocker_count_at_handoff": 6}))
    (root / "phases/phase-1/phase.json").write_text(json.dumps({
        "phase": "phase-1", "status": "open", "blocker_count_at_handoff": None, "prd_path": None}))
    return root


# ---------------------------------------------------------------- pre-flight


def test_preflight_separates_eligible_from_everything_else(store):
    out = run("preflight", "--root", str(store), "--phase", "phase-1")
    assert [f["id"] for f in out["eligible"]] == ["F-001", "F-002"]
    assert out["not_eligible"][0]["id"] == "F-003"
    assert "'designing'" in out["not_eligible"][0]["why"]


def test_preflight_counts_only_blockers_that_would_actually_travel(store):
    out = run("preflight", "--root", str(store), "--phase", "phase-1")
    assert [b["id"] for b in out["critical_blockers"]] == ["F-001-Q-01"], \
        "F-003 is not in the bundle, and F-002-Q-02 is resolved"
    assert out["minor_open"] == 1
    assert out["requirements_total"] == 3


def test_preflight_reports_and_never_refuses_but_says_bundle_will(store):
    """The report is what the BA runs to decide, so it always exits 0 — and die() would return
    before the --out HTML is written, silently dropping the artifact they asked for."""
    out = run("preflight", "--root", str(store), "--phase", "phase-1")
    assert out["ok"] is True and out["blocks_bundle"] is True
    assert "bundle will refuse" in out["verdict"]


def test_preflight_sees_questions_the_ledger_never_heard_of(store):
    """Independent of the ledger: a spec still carrying unfiled question bullets means the count
    is understating the blockers, whatever the count says."""
    spec = store / "phases/phase-1/features/F-002-academy/spec.md"
    spec.write_text(spec.read_text() + "\n## Open questions\n\n- **critical** (client) — Never filed.\n")
    out = run("preflight", "--root", str(store), "--phase", "phase-1")
    assert out["unfiled_questions"][0]["feature"] == "F-002"
    assert "fdw-elaborate questions" in out["unfiled_questions"][0]["detail"]


# ---------------------------------------------------------------- the bundle gate


def test_bundling_refuses_while_a_critical_blocker_would_travel(store):
    """The failure this reverses: a PRD was generated carrying eleven open questions."""
    payload = run("bundle", "--root", str(store), "--phase", "phase-1", expect_ok=False)
    joined = " ".join(payload["errors"])
    assert "F-001-Q-01" in joined and "would travel into the PRD" in joined
    assert payload["clean_features"] == ["F-002"]
    assert "--id F-002" in joined, "name the better exit first"
    assert not (store / "phases/phase-1/handoff").exists(), "a refusal writes nothing"


def test_the_clean_features_can_be_bundled_without_any_override(store):
    out = run("bundle", "--root", str(store), "--phase", "phase-1", "--id", "F-002")
    assert out["features"] == ["F-002"]


def test_the_override_is_available_and_recorded_where_it_survives(store):
    out = run("bundle", "--root", str(store), "--phase", "phase-1",
              "--accept-open-blockers", "--reason", "client call is next week")
    manifest = json.loads((store / out["bundle"]).read_text())
    assert manifest["accepted_blockers"] == ["F-001-Q-01"]
    assert manifest["override_reason"] == "client call is next week"


def test_a_question_raised_after_approval_still_stops_the_bundle(store):
    """Only a bundle-time gate catches this: the spec gate never runs again."""
    fdir = store / "phases/phase-1/features/F-002-academy"
    record = json.loads((fdir / "feature.json").read_text())
    record["questions"].append({"id": "F-002-Q-09", "text": "Late contradiction", "status": "open",
                                "criticality": "critical", "owner": "client"})
    (fdir / "feature.json").write_text(json.dumps(record))
    payload = run("bundle", "--root", str(store), "--phase", "phase-1", "--id", "F-002",
                  expect_ok=False)
    assert "F-002-Q-09" in " ".join(payload["errors"])


def test_preflight_flags_a_dependency_left_out_of_the_bundle(store):
    out = run("preflight", "--root", str(store), "--phase", "phase-1", "--id", "F-002")
    assert out["dependency_gaps"][0]["depends_on"] == "F-001"


def test_a_dependency_inside_the_bundle_is_not_a_gap(store):
    out = run("preflight", "--root", str(store), "--phase", "phase-1")
    assert out["dependency_gaps"] == []


def test_preflight_carries_the_trend_from_earlier_phases(store):
    assert run("preflight", "--root", str(store), "--phase", "phase-1")["trend"] == [
        {"phase": "phase-0", "blockers": 6}]


def test_preflight_report_is_self_contained_and_says_the_bundle_refuses(tmp_path, store):
    out_html = tmp_path / "pre.html"
    run("preflight", "--root", str(store), "--phase", "phase-1", "--out", str(out_html))
    page = out_html.read_text()
    assert "never refuses" in page and "Bundling does refuse" in page
    assert "Timezone?" in page
    assert "prefers-color-scheme" in page
    for absent in ("http://", "https://", "<script"):
        assert absent not in page


def test_a_clean_preflight_says_so_rather_than_showing_an_empty_table(tmp_path, store):
    fdir = store / "phases/phase-1/features/F-001-events-agenda"
    record = json.loads((fdir / "feature.json").read_text())
    record["questions"][0]["status"] = "resolved"
    (fdir / "feature.json").write_text(json.dumps(record))
    out_html = tmp_path / "pre.html"
    run("preflight", "--root", str(store), "--phase", "phase-1", "--out", str(out_html))
    assert "which is the whole point of the spec gate" in out_html.read_text()


def test_unknown_phase_lists_the_real_ones(store):
    assert "phase-1" in run("preflight", "--root", str(store), "--phase", "phase-9",
                            expect_ok=False)["errors"][0]


# ---------------------------------------------------------------- the eligibility rule


def test_only_an_approved_spec_enters_a_bundle(store):
    payload = run("bundle", "--root", str(store), "--phase", "phase-1", "--id", "F-003", expect_ok=False)
    assert "contract with development" in " ".join(payload["errors"])


def test_bundling_a_phase_with_nothing_approved_names_the_fix(tmp_path, store):
    registry = json.loads((store / "registry.json").read_text())
    for f in registry["features"]:
        f["status"] = "speccing"
    (store / "registry.json").write_text(json.dumps(registry))
    payload = run("bundle", "--root", str(store), "--phase", "phase-1", expect_ok=False)
    assert "fdw-elaborate" in payload["errors"][0]


def test_a_status_without_a_spec_file_is_caught(store):
    (store / "phases/phase-1/features/F-002-academy/spec.md").unlink()
    payload = run("bundle", "--root", str(store), "--phase", "phase-1", expect_ok=False)
    assert "no spec.md" in payload["errors"][0]


# ---------------------------------------------------------------- the bundle


def test_bundle_lists_paths_rather_than_flattening_the_specs(store):
    out = run("bundle", "--root", str(store), "--phase", "phase-1", "--accept-open-blockers")
    manifest = json.loads((store / out["bundle"]).read_text())
    assert manifest["requirements_total"] == 3
    assert manifest["features"][0]["requirements"] == ["F-001-R-01", "F-001-R-02"]
    assert any(s.endswith("F-001-events-agenda/spec.md") for s in manifest["source_documents"])
    assert any(s.endswith("ux-notes.md") for s in manifest["source_documents"])
    assert "decisions.md" in manifest["source_documents"]
    assert all(isinstance(s, str) for s in out["source_documents"])


def test_bundle_orders_by_dependency(store):
    assert run("bundle", "--root", str(store), "--phase", "phase-1", "--accept-open-blockers")["features"] == ["F-001", "F-002"]


def test_the_readme_orients_a_reader_with_no_context(store):
    out = run("bundle", "--root", str(store), "--phase", "phase-1", "--accept-open-blockers")
    readme = (store / out["readme"]).read_text()
    assert "specs are the source of truth" in readme
    assert "F-001 — Events agenda" in readme and "F-002 — Academy" in readme
    assert "Build order" in readme and "F-001 → F-002" in readme
    assert "provenance" in readme


def test_the_readme_flags_blockers_travelling_into_the_prd(store):
    out = run("bundle", "--root", str(store), "--phase", "phase-1", "--accept-open-blockers")
    readme = (store / out["readme"]).read_text()
    assert "Open blockers travelling into the PRD" in readme and "F-001-Q-01" in readme
    assert out["critical_blockers"] == ["F-001-Q-01"]


def test_a_clean_bundle_says_every_blocker_was_closed(store):
    fdir = store / "phases/phase-1/features/F-001-events-agenda"
    record = json.loads((fdir / "feature.json").read_text())
    record["questions"][0]["status"] = "resolved"
    (fdir / "feature.json").write_text(json.dumps(record))
    out = run("bundle", "--root", str(store), "--phase", "phase-1", "--accept-open-blockers")
    assert "closed before the specs were approved" in (store / out["readme"]).read_text()


def test_the_next_call_agenda_asks_only_the_client_and_leads_with_blockers(store):
    out = run("bundle", "--root", str(store), "--phase", "phase-1", "--accept-open-blockers")
    agenda = (store / out["agenda"]).read_text()
    assert "Timezone?" in agenda and "Which gateway?" in agenda, \
        "the agenda covers the whole phase, not just the bundle — the client still owes us both"
    assert "Copy?" not in agenda, "an internal question is not the client's to answer"
    assert agenda.index("Blocking") < agenda.index("Timezone?")


def test_partial_handoff_is_supported(store):
    out = run("bundle", "--root", str(store), "--phase", "phase-1", "--id", "F-001", "--accept-open-blockers")
    assert out["features"] == ["F-001"]
    assert json.loads((store / out["bundle"]).read_text())["requirements_total"] == 2


# ---------------------------------------------------------------- as-built


def test_as_built_records_what_shipped_with_its_requirement_ids(store):
    registry = json.loads((store / "registry.json").read_text())
    registry["features"][0]["status"] = "handed-off"
    (store / "registry.json").write_text(json.dumps(registry))
    out = run("as-built", "--root", str(store), "--phase", "phase-1")
    text = (store / out["as_built"]).read_text()
    assert "## phase-1" in text
    assert "`F-001-R-01` Agenda blocks size to content." in text
    assert "Academy" not in text, "only handed-off features are as-built"


def test_as_built_refuses_before_anything_shipped(store):
    payload = run("as-built", "--root", str(store), "--phase", "phase-1", expect_ok=False)
    assert "nothing to record as built" in payload["errors"][0]


def test_as_built_refuses_to_duplicate_a_phase_section(store):
    registry = json.loads((store / "registry.json").read_text())
    registry["features"][0]["status"] = "handed-off"
    (store / "registry.json").write_text(json.dumps(registry))
    run("as-built", "--root", str(store), "--phase", "phase-1")
    payload = run("as-built", "--root", str(store), "--phase", "phase-1", expect_ok=False)
    assert "already has a 'phase-1' section" in payload["errors"][0]


def test_as_built_drops_the_nothing_shipped_placeholder(store):
    (store / "as-built.md").write_text("# As-Built Baseline\n\n_Nothing shipped yet._\n")
    registry = json.loads((store / "registry.json").read_text())
    registry["features"][0]["status"] = "handed-off"
    (store / "registry.json").write_text(json.dumps(registry))
    run("as-built", "--root", str(store), "--phase", "phase-1")
    assert "_Nothing shipped yet._" not in (store / "as-built.md").read_text()


def test_bundling_never_changes_feature_state(store):
    watched = [store / "registry.json"] + list((store / "phases/phase-1/features").rglob("feature.json"))
    before = {p: p.read_bytes() for p in watched}
    run("bundle", "--root", str(store), "--phase", "phase-1", "--accept-open-blockers")
    assert {p: p.read_bytes() for p in watched} == before, \
        "advancing features to handed-off goes through the shared CLI"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))


def test_a_dependency_already_shipped_in_an_earlier_phase_is_not_a_gap(store):
    """Cross-phase dependencies are the normal shape of phased delivery. Looking them up only
    inside the target phase reports every one of them as missing."""
    registry = json.loads((store / "registry.json").read_text())
    registry["features"][0].update({"phase": "phase-0", "status": "handed-off"})
    (store / "registry.json").write_text(json.dumps(registry))
    out = run("preflight", "--root", str(store), "--phase", "phase-1", "--id", "F-002")
    assert out["dependency_gaps"] == []


def test_a_dependency_still_in_flight_elsewhere_is_named_with_its_phase(store):
    registry = json.loads((store / "registry.json").read_text())
    registry["features"][0].update({"phase": "phase-0", "status": "designing"})
    (store / "registry.json").write_text(json.dumps(registry))
    out = run("preflight", "--root", str(store), "--phase", "phase-1", "--id", "F-002")
    assert "phase-0" in out["dependency_gaps"][0]["detail"]
    assert "'designing'" in out["dependency_gaps"][0]["detail"]


def test_a_dependency_that_does_not_exist_at_all_is_distinguished(store):
    registry = json.loads((store / "registry.json").read_text())
    registry["features"][1]["depends_on"] = ["F-999"]
    (store / "registry.json").write_text(json.dumps(registry))
    out = run("preflight", "--root", str(store), "--phase", "phase-1", "--id", "F-002")
    assert "not in the registry at all" in out["dependency_gaps"][0]["detail"]
