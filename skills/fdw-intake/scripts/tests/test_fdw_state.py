#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["pytest"]
# ///
"""Tests for fdw_state.py — the fdw discovery state store."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "fdw_state.py"
TRANSCRIPT = [
    {"sentence": "We need session management.", "startTime": "10:05", "speaker_name": "Client"},
    {"sentence": "Sessions have a start time.", "startTime": "10:07", "speaker_name": "Client"},
    {"sentence": "Can sessions overlap?", "startTime": "10:20", "speaker_name": "BA"},
]


def run(*args, expect_ok=True):
    result = subprocess.run(
        [sys.executable, str(SCRIPT), *args], capture_output=True, text=True
    )
    payload = json.loads(result.stdout)
    if expect_ok:
        assert payload.get("ok") is True, payload
    else:
        assert payload.get("ok") is False, payload
        assert result.returncode == 1
    return payload


@pytest.fixture
def root(tmp_path):
    store = tmp_path / "discovery"
    run("init", "--root", str(store))
    return store


@pytest.fixture
def source(tmp_path, root):
    path = tmp_path / "call.json"
    path.write_text(json.dumps(TRANSCRIPT), encoding="utf-8")
    return run("normalize", "--root", str(root), "--file", str(path), "--title", "Kickoff", "--date", "2026-01-05")


def plan_for(source, **overrides):
    plan = {
        "source": {
            "source_id": source["source_id"],
            "sha256": source["sha256"],
            "path": source["path"],
            "title": "Kickoff",
            "date": "2026-01-05",
            "kind": source["kind"],
            "sample": source["sample"],
        },
        "new_features": [
            {
                "title": "Session management",
                "slug": "session-management",
                "phase": "phase-1",
                "summary": "Create and schedule sessions.",
                "aliases": ["sessions"],
                "signal": [
                    {
                        "text": "A session carries a start time.",
                        "anchor": f"{source['source_id']}#t=10:07",
                        "quote": "Sessions have a start time.",
                        "speaker": "Client",
                    }
                ],
                "questions": [
                    {"text": "Can sessions overlap?", "criticality": "critical", "owner": "client"}
                ],
            }
        ],
    }
    plan.update(overrides)
    return plan


def write_plan(tmp_path, plan, name="plan.json"):
    path = tmp_path / name
    path.write_text(json.dumps(plan), encoding="utf-8")
    return str(path)


# ---------------------------------------------------------------- init


def test_init_is_idempotent(tmp_path):
    store = tmp_path / "discovery"
    first = run("init", "--root", str(store))
    assert first["created"]
    second = run("init", "--root", str(store))
    assert second["created"] == []
    assert second["already_present"] is True


def test_init_seeds_registry_and_phase_one(root):
    registry = json.loads((root / "registry.json").read_text())
    assert registry["current_phase"] == "phase-1"
    assert registry["next_feature_seq"] == 1
    assert registry["features"] == []
    assert (root / "phases" / "phase-1" / "phase.json").exists()


# ---------------------------------------------------------------- normalize


def test_normalize_groups_transcript_into_speaker_turns(source, root):
    assert source["kind"] == "transcript"
    assert source["anchor_kind"] == "t"
    assert source["anchor_count"] == 2  # Client turn, then BA turn
    text = (root / source["path"]).read_text()
    assert "## [[t=10:05]] Client" in text
    assert "## [[t=10:20]] BA" in text


def test_normalize_preserves_original_language_verbatim(tmp_path, root):
    path = tmp_path / "ua.json"
    path.write_text(
        json.dumps([{"sentence": "Нам потрібні сесії.", "startTime": "01:00", "speaker_name": "Клієнт"}]),
        encoding="utf-8",
    )
    out = run("normalize", "--root", str(root), "--file", str(path), "--title", "UA call")
    assert "Нам потрібні сесії." in (root / out["path"]).read_text()


def test_normalize_falls_back_to_line_anchors_for_prose(tmp_path, root):
    path = tmp_path / "wbs.md"
    path.write_text("\n".join(f"line {i}" for i in range(50)), encoding="utf-8")
    out = run("normalize", "--root", str(root), "--file", str(path), "--title", "WBS")
    assert out["anchor_kind"] == "L"
    assert "## [[L=1]]" in (root / out["path"]).read_text()


def test_normalize_rejects_binary_with_a_recoverable_fix(tmp_path, root):
    path = tmp_path / "brief.docx"
    path.write_bytes(b"PK\x03\x04binary")
    payload = run("normalize", "--root", str(root), "--file", str(path), expect_ok=False)
    assert payload["recoverable"] is True
    assert "subagent" in " ".join(payload["errors"])


def test_normalize_detects_near_identical_re_export(tmp_path, root, source):
    write = write_plan(tmp_path, plan_for(source))
    run("apply-plan", "--root", str(root), "--plan", write)
    corrected = tmp_path / "call-v2.json"
    revised = list(TRANSCRIPT)
    revised[2] = {"sentence": "Can sessions overlap at all?", "startTime": "10:20", "speaker_name": "BA"}
    corrected.write_text(json.dumps(revised), encoding="utf-8")
    out = run("normalize", "--root", str(root), "--file", str(corrected), "--title", "Kickoff v2")
    assert out["already_ingested"] is False
    assert out["matches"], "a corrected re-export must surface as a near match, not slip through as new"
    assert out["matches"][0]["relation"] == "near"


def test_normalize_flags_byte_identical_re_ingest(tmp_path, root, source):
    run("apply-plan", "--root", str(root), "--plan", write_plan(tmp_path, plan_for(source)))
    again = tmp_path / "call.json"
    out = run("normalize", "--root", str(root), "--file", str(again), "--title", "Kickoff", "--date", "2026-01-05")
    assert out["already_ingested"] is True


# ---------------------------------------------------------------- provenance enforcement


@pytest.mark.parametrize("missing", ["text", "anchor", "quote"])
def test_signal_without_full_provenance_is_rejected(tmp_path, root, source, missing):
    plan = plan_for(source)
    del plan["new_features"][0]["signal"][0][missing]
    payload = run("validate-plan", "--root", str(root), "--plan", write_plan(tmp_path, plan), expect_ok=False)
    assert any(missing in err for err in payload["errors"])


def test_malformed_anchor_is_rejected_with_the_correct_shape(tmp_path, root, source):
    plan = plan_for(source)
    plan["new_features"][0]["signal"][0]["anchor"] = "somewhere in the call"
    payload = run("validate-plan", "--root", str(root), "--plan", write_plan(tmp_path, plan), expect_ok=False)
    assert any("#t=MM:SS" in err for err in payload["errors"])


def test_feature_with_no_signal_at_all_is_rejected(tmp_path, root, source):
    plan = plan_for(source)
    plan["new_features"][0]["signal"] = []
    payload = run("validate-plan", "--root", str(root), "--plan", write_plan(tmp_path, plan), expect_ok=False)
    assert any("no evidence" in err for err in payload["errors"])


def test_empty_plan_is_rejected_and_points_at_record_empty(tmp_path, root, source):
    plan = plan_for(source)
    plan["new_features"] = []
    payload = run("validate-plan", "--root", str(root), "--plan", write_plan(tmp_path, plan), expect_ok=False)
    assert any("--empty" in err for err in payload["errors"])


def test_question_needs_criticality_and_owner(tmp_path, root, source):
    plan = plan_for(source)
    plan["new_features"][0]["questions"][0] = {"text": "Who approves?"}
    payload = run("validate-plan", "--root", str(root), "--plan", write_plan(tmp_path, plan), expect_ok=False)
    joined = " ".join(payload["errors"])
    assert "criticality" in joined and "owner" in joined


# ---------------------------------------------------------------- apply


def test_apply_creates_feature_folder_registry_entry_and_signal(tmp_path, root, source):
    out = run("apply-plan", "--root", str(root), "--plan", write_plan(tmp_path, plan_for(source)))
    created = out["delta"]["created"][0]
    assert created["id"] == "F-001"
    fdir = root / created["path"]
    assert (fdir / "feature.json").exists()
    assert (fdir / "signal.md").exists()
    signal = (fdir / "signal.md").read_text()
    assert "anchor:" in signal and "quote:" in signal
    registry = json.loads((root / "registry.json").read_text())
    assert registry["features"][0]["status"] == "sliced"
    assert registry["next_feature_seq"] == 2
    assert registry["features"][0]["open_questions"] == {"critical": 1, "non-critical": 0}


def test_ids_are_never_reused(tmp_path, root, source):
    run("apply-plan", "--root", str(root), "--plan", write_plan(tmp_path, plan_for(source)))
    second = plan_for(source)
    second["new_features"][0]["title"] = "Room booking"
    second["new_features"][0]["slug"] = "room-booking"
    out = run("apply-plan", "--root", str(root), "--plan", write_plan(tmp_path, second, "p2.json"))
    assert out["delta"]["created"][0]["id"] == "F-002"


def test_duplicate_slug_is_rejected_and_points_at_merges(tmp_path, root, source):
    run("apply-plan", "--root", str(root), "--plan", write_plan(tmp_path, plan_for(source)))
    payload = run(
        "validate-plan", "--root", str(root), "--plan", write_plan(tmp_path, plan_for(source), "dup.json"),
        expect_ok=False,
    )
    assert any("merges" in err for err in payload["errors"])


def test_merge_appends_evidence_without_creating_a_feature(tmp_path, root, source):
    run("apply-plan", "--root", str(root), "--plan", write_plan(tmp_path, plan_for(source)))
    merge_plan = plan_for(source)
    merge_plan["new_features"] = []
    merge_plan["merges"] = [
        {
            "feature_id": "F-001",
            "aliases_add": ["scheduling"],
            "signal": [
                {
                    "text": "A session belongs to a room.",
                    "anchor": f"{source['source_id']}#t=10:05",
                    "quote": "We need session management.",
                }
            ],
            "questions": [],
        }
    ]
    out = run("apply-plan", "--root", str(root), "--plan", write_plan(tmp_path, merge_plan, "m.json"))
    assert out["delta"]["created"] == []
    assert out["delta"]["merged"][0]["id"] == "F-001"
    registry = json.loads((root / "registry.json").read_text())
    assert len(registry["features"]) == 1
    fdir = root / "phases/phase-1/features/F-001-session-management"
    assert "belongs to a room" in (fdir / "signal.md").read_text()
    assert "scheduling" in json.loads((fdir / "feature.json").read_text())["aliases"]


def test_question_closes_against_the_answering_quote(tmp_path, root, source):
    run("apply-plan", "--root", str(root), "--plan", write_plan(tmp_path, plan_for(source)))
    closing = plan_for(source)
    closing["new_features"] = []
    closing["question_closures"] = [
        {
            "question_id": "F-001-Q-01",
            "answer": "No, sessions cannot overlap.",
            "anchor": f"{source['source_id']}#t=10:20",
            "quote": "Can sessions overlap?",
        }
    ]
    run("apply-plan", "--root", str(root), "--plan", write_plan(tmp_path, closing, "c.json"))
    record = json.loads((root / "phases/phase-1/features/F-001-session-management/feature.json").read_text())
    question = record["questions"][0]
    assert question["status"] == "resolved"
    assert question["answer_quote"] == "Can sessions overlap?"
    registry = json.loads((root / "registry.json").read_text())
    assert registry["features"][0]["open_questions"]["critical"] == 0


def test_closing_an_unknown_question_is_rejected(tmp_path, root, source):
    run("apply-plan", "--root", str(root), "--plan", write_plan(tmp_path, plan_for(source)))
    bad = plan_for(source)
    bad["new_features"] = []
    bad["question_closures"] = [
        {"question_id": "F-009-Q-99", "answer": "x", "anchor": f"{source['source_id']}#t=10:20", "quote": "y"}
    ]
    payload = run("validate-plan", "--root", str(root), "--plan", write_plan(tmp_path, bad, "bad.json"), expect_ok=False)
    assert any("not an open question" in err for err in payload["errors"])


# ---------------------------------------------------------------- the sandbox rule


def _approve(root, feature_id="F-001"):
    registry = json.loads((root / "registry.json").read_text())
    for feature in registry["features"]:
        if feature["id"] == feature_id:
            feature["status"] = "spec-approved"
    (root / "registry.json").write_text(json.dumps(registry, indent=2))
    fdir = root / "phases/phase-1/features/F-001-session-management"
    record = json.loads((fdir / "feature.json").read_text())
    record["status"] = "spec-approved"
    (fdir / "feature.json").write_text(json.dumps(record, indent=2))


def test_contradiction_against_an_approved_spec_must_route_to_a_change_record(tmp_path, root, source):
    run("apply-plan", "--root", str(root), "--plan", write_plan(tmp_path, plan_for(source)))
    _approve(root)
    plan = plan_for(source)
    plan["new_features"] = []
    plan["contradictions"] = [
        {
            "feature_id": "F-001",
            "text": "Sessions may now overlap.",
            "anchor": f"{source['source_id']}#t=10:20",
            "quote": "Can sessions overlap?",
        }
    ]
    payload = run("validate-plan", "--root", str(root), "--plan", write_plan(tmp_path, plan, "x.json"), expect_ok=False)
    assert any("change-record" in err for err in payload["errors"])


def test_routed_contradiction_writes_changes_md_and_never_touches_spec(tmp_path, root, source):
    run("apply-plan", "--root", str(root), "--plan", write_plan(tmp_path, plan_for(source)))
    _approve(root)
    fdir = root / "phases/phase-1/features/F-001-session-management"
    (fdir / "spec.md").write_text("# Approved spec\nSessions cannot overlap.\n", encoding="utf-8")
    before = (fdir / "spec.md").read_text()
    plan = plan_for(source)
    plan["new_features"] = []
    plan["contradictions"] = [
        {
            "feature_id": "F-001",
            "text": "Sessions may now overlap.",
            "anchor": f"{source['source_id']}#t=10:20",
            "quote": "Can sessions overlap?",
            "route": "change-record",
            "design_invalidated": True,
        }
    ]
    out = run("apply-plan", "--root", str(root), "--plan", write_plan(tmp_path, plan, "x.json"))
    assert out["delta"]["contradictions"][0]["locked"] is True
    assert (fdir / "spec.md").read_text() == before, "intake must never edit an approved spec"

    # The record is the ledger; changes.md is the reading surface rendered from it.
    record = json.loads((fdir / "feature.json").read_text())
    change = record["changes"][0]
    assert change["id"] == "F-001-C-01"
    assert change["text"] == "Sessions may now overlap."
    assert change["route"] == "in-flight"
    assert change["status_when_raised"] == "spec-approved"
    assert change["design_invalidated"] == "true"
    assert change["status"] == "open"
    assert out["delta"]["changes"][0]["change_id"] == "F-001-C-01"

    # One fact, one ledger: the locked path no longer also raises a question about it.
    assert not [q for q in record["questions"] if "Sessions may now overlap" in q["text"]]

    assert "Sessions may now overlap." in (fdir / "changes.md").read_text()
    registry = json.loads((root / "registry.json").read_text())
    assert "changed" in registry["features"][0]["flags"]
    assert registry["features"][0]["open_changes"] == {"in-flight": 1, "delivered": 0}


def test_contradiction_before_approval_stays_an_open_question(tmp_path, root, source):
    run("apply-plan", "--root", str(root), "--plan", write_plan(tmp_path, plan_for(source)))
    plan = plan_for(source)
    plan["new_features"] = []
    plan["contradictions"] = [
        {
            "feature_id": "F-001",
            "text": "Start time is optional after all.",
            "anchor": f"{source['source_id']}#t=10:07",
            "quote": "Sessions have a start time.",
            "criticality": "critical",
            "owner": "client",
        }
    ]
    out = run("apply-plan", "--root", str(root), "--plan", write_plan(tmp_path, plan, "x.json"))
    assert out["delta"]["contradictions"][0]["locked"] is False
    fdir = root / "phases/phase-1/features/F-001-session-management"
    assert not (fdir / "changes.md").exists()
    record = json.loads((fdir / "feature.json").read_text())
    assert any("Contradiction:" in q["text"] for q in record["questions"])


# ---------------------------------------------------------------- context and validate


def test_context_gives_the_model_what_it_needs_without_reading_files(tmp_path, root, source):
    run("apply-plan", "--root", str(root), "--plan", write_plan(tmp_path, plan_for(source)))
    ctx = run("context", "--root", str(root))
    assert ctx["next_feature_id"] == "F-002"
    assert ctx["current_phase"] == "phase-1"
    feature = ctx["features"][0]
    assert feature["aliases"] == ["sessions"]
    assert feature["spec_locked"] is False
    assert ctx["open_questions"][0]["feature_id"] == "F-001"
    assert ctx["ingested_sources"][0]["source_id"] == source["source_id"]


def test_context_marks_approved_features_as_spec_locked(tmp_path, root, source):
    run("apply-plan", "--root", str(root), "--plan", write_plan(tmp_path, plan_for(source)))
    _approve(root)
    assert run("context", "--root", str(root))["features"][0]["spec_locked"] is True


def test_validate_passes_on_a_healthy_store(tmp_path, root, source):
    run("apply-plan", "--root", str(root), "--plan", write_plan(tmp_path, plan_for(source)))
    assert run("validate", "--root", str(root))["healthy"] is True


def test_validate_catches_a_registry_pointing_at_a_missing_folder(tmp_path, root, source):
    run("apply-plan", "--root", str(root), "--plan", write_plan(tmp_path, plan_for(source)))
    import shutil

    shutil.rmtree(root / "phases/phase-1/features/F-001-session-management")
    payload = run("validate", "--root", str(root), expect_ok=False)
    assert any("does not exist" in err for err in payload["errors"])


def test_validate_catches_a_stale_open_question_count(tmp_path, root, source):
    run("apply-plan", "--root", str(root), "--plan", write_plan(tmp_path, plan_for(source)))
    registry = json.loads((root / "registry.json").read_text())
    registry["features"][0]["open_questions"] = {"critical": 9, "non-critical": 0}
    (root / "registry.json").write_text(json.dumps(registry, indent=2))
    payload = run("validate", "--root", str(root), expect_ok=False)
    assert any("stale" in err for err in payload["errors"])


def test_context_refuses_without_a_store(tmp_path):
    payload = run("context", "--root", str(tmp_path / "nope"), expect_ok=False)
    assert any("init" in err for err in payload["errors"])


def test_record_empty_logs_the_outcome_without_inventing_features(tmp_path, root, source):
    out = run(
        "record-empty",
        "--root", str(root),
        "--source-id", source["source_id"],
        "--reason", "Status call, no new requirements.",
    )
    assert out["outcome"] == "no-new-signal"
    assert json.loads((root / "registry.json").read_text())["features"] == []
    assert "no new features" in (root / "decisions.md").read_text()


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))


# ---------------------------------------------------------------- source block is looked up, not transcribed


def test_plan_needs_only_a_source_id(tmp_path, root, source):
    plan = plan_for(source)
    plan["source"] = {"source_id": source["source_id"]}
    out = run("apply-plan", "--root", str(root), "--plan", write_plan(tmp_path, plan))
    assert out["delta"]["created"][0]["id"] == "F-001"
    recorded = json.loads((root / "sources" / "index.json").read_text())["sources"][0]
    assert recorded["sha256"] == source["sha256"]
    assert recorded["path"] == source["path"]


def test_a_hand_copied_wrong_hash_is_caught(tmp_path, root, source):
    plan = plan_for(source)
    plan["source"]["sha256"] = "0" * 64
    payload = run("validate-plan", "--root", str(root), "--plan", write_plan(tmp_path, plan), expect_ok=False)
    assert any("does not match what normalize recorded" in err for err in payload["errors"])


def test_unknown_source_id_names_the_command_that_fixes_it(tmp_path, root):
    plan = {"source": {"source_id": "never-normalized"}, "new_features": []}
    payload = run("validate-plan", "--root", str(root), "--plan", write_plan(tmp_path, plan), expect_ok=False)
    assert any("normalize" in err for err in payload["errors"])


def test_normalize_names_the_plan_path_and_apply_clears_the_scratch(tmp_path, root, source):
    assert source["plan_path"].endswith(f"{source['source_id']}.plan.json")
    pending = root / "sources" / ".pending"
    assert (pending / f"{source['source_id']}.source.json").exists()
    run("apply-plan", "--root", str(root), "--plan", write_plan(tmp_path, plan_for(source)))
    assert not list(pending.glob(f"{source['source_id']}.*"))


# ---------------------------------------------------------------- feature-set gates


@pytest.fixture
def one_feature(tmp_path, root, source):
    run("apply-plan", "--root", str(root), "--plan", write_plan(tmp_path, plan_for(source)))
    return "F-001"


def test_advancing_one_stage_at_a_time_is_allowed(root, one_feature):
    out = run("feature-set", "--root", str(root), "--id", one_feature, "--status", "designing")
    assert out["status"] == "designing"
    registry = json.loads((root / "registry.json").read_text())
    assert registry["features"][0]["status"] == "designing"
    record = json.loads((root / "phases/phase-1/features/F-001-session-management/feature.json").read_text())
    assert record["status"] == "designing"


def test_skipping_a_gate_is_refused_and_names_the_missing_stage(root, one_feature):
    payload = run("feature-set", "--root", str(root), "--id", one_feature,
                  "--status", "spec-approved", expect_ok=False)
    joined = " ".join(payload["errors"])
    assert "skips" in joined and "designing" in joined


def test_a_forced_skip_is_allowed_but_logged_as_an_override(root, one_feature):
    run("feature-set", "--root", str(root), "--id", one_feature, "--status", "spec-approved",
        "--force", "--note", "specced offline during the workshop")
    assert json.loads((root / "registry.json").read_text())["features"][0]["status"] == "spec-approved"
    decisions = (root / "decisions.md").read_text()
    assert "override" in decisions and "skipping" in decisions


def test_going_backwards_is_always_allowed(root, one_feature):
    run("feature-set", "--root", str(root), "--id", one_feature, "--status", "designing")
    run("feature-set", "--root", str(root), "--id", one_feature, "--status", "client-review")
    out = run("feature-set", "--root", str(root), "--id", one_feature, "--status", "designing")
    assert out["status"] == "designing"
    assert "override" not in (root / "decisions.md").read_text()


def test_size_flags_and_dependencies_update_both_files(tmp_path, root, source, one_feature):
    second = plan_for(source)
    second["new_features"][0].update({"title": "Room booking", "slug": "room-booking"})
    run("apply-plan", "--root", str(root), "--plan", write_plan(tmp_path, second, "p2.json"))
    out = run("feature-set", "--root", str(root), "--id", "F-002", "--size", "XL",
              "--add-flag", "changed", "--depends-on", "F-001", "--note", "blocked on sessions")
    assert "size None → XL" in out["changed"]
    registry = {f["id"]: f for f in json.loads((root / "registry.json").read_text())["features"]}
    assert registry["F-002"]["size"] == "XL"
    assert registry["F-002"]["depends_on"] == ["F-001"]
    assert "changed" in registry["F-002"]["flags"]
    assert "blocked on sessions" in (root / "decisions.md").read_text()


def test_unknown_flag_and_self_dependency_are_refused(root, one_feature):
    assert any("not a known flag" in e for e in
               run("feature-set", "--root", str(root), "--id", one_feature,
                   "--add-flag", "urgent", expect_ok=False)["errors"])
    assert any("cannot depend on itself" in e for e in
               run("feature-set", "--root", str(root), "--id", one_feature,
                   "--depends-on", one_feature, expect_ok=False)["errors"])


def test_unknown_feature_lists_what_exists(root, one_feature):
    payload = run("feature-set", "--root", str(root), "--id", "F-404", "--status", "designing", expect_ok=False)
    assert "F-001" in payload["errors"][0]


# ---------------------------------------------------------------- question-add (raised outside intake)

FEATURE_JSON = "phases/phase-1/features/F-001-session-management/feature.json"


def add(root, **kw):
    args = ["question-add", "--root", str(root), "--id", "F-001",
            "--source", kw.pop("source", "spec F-001 open questions")]
    for flag, value in kw.pop("flags", {}).items():
        args += [flag, value]
    return run(*args, **kw)


def test_a_question_found_while_speccing_reaches_the_ledger(root, one_feature):
    """Until this existed, a question could only be born inside apply-plan — so everything the BA
    found while writing the spec was invisible to approval, pre-flight and the phase blocker count."""
    out = add(root, flags={"--text": "What precedence order?", "--criticality": "non-critical",
                           "--owner": "client"})
    assert out["added"] == ["F-001-Q-02"]
    record = json.loads((root / FEATURE_JSON).read_text())
    raised = record["questions"][-1]
    assert raised["status"] == "open" and raised["owner"] == "client"
    assert raised["raised_by"] == "spec F-001 open questions"


def test_the_registry_mirror_is_updated_so_validate_stays_clean(root, one_feature):
    """The registry keeps a denormalised count and validate fails the whole store on drift."""
    add(root, flags={"--text": "What precedence order?", "--criticality": "non-critical",
                     "--owner": "client"})
    counts = json.loads((root / "registry.json").read_text())["features"][0]["open_questions"]
    assert counts == {"critical": 1, "non-critical": 1}
    assert run("validate", "--root", str(root))["healthy"] is True


def test_supplying_the_id_makes_a_re_run_a_no_op(root, one_feature):
    """The spec carries the minted id, so syncing twice must not breed a second copy."""
    add(root, flags={"--text": "What precedence order?", "--criticality": "non-critical",
                     "--owner": "client"})
    again = add(root, flags={"--question-id": "F-001-Q-02", "--text": "What precedence order?",
                             "--criticality": "non-critical", "--owner": "client"})
    assert again["added"] == [] and again["already_present"] == ["F-001-Q-02"]
    assert len(json.loads((root / FEATURE_JSON).read_text())["questions"]) == 2


def test_reusing_an_id_for_different_wording_is_refused(root, one_feature):
    add(root, flags={"--text": "What precedence order?", "--criticality": "non-critical",
                     "--owner": "client"})
    payload = add(root, expect_ok=False,
                  flags={"--question-id": "F-001-Q-02", "--text": "Something else entirely",
                         "--criticality": "non-critical", "--owner": "client"})
    assert "already exists with different wording" in " ".join(payload["errors"])


def test_the_same_question_asked_twice_is_refused_unless_you_insist(root, one_feature):
    add(root, flags={"--text": "What precedence order?", "--criticality": "non-critical",
                     "--owner": "client"})
    payload = add(root, expect_ok=False,
                  flags={"--text": "what precedence order", "--criticality": "critical",
                         "--owner": "dev"})
    assert "already open with the same wording" in " ".join(payload["errors"])
    out = run("question-add", "--root", str(root), "--id", "F-001", "--source", "x",
              "--text", "what precedence order", "--criticality", "critical", "--owner", "dev",
              "--allow-duplicate")
    assert out["added"] == ["F-001-Q-03"]


def test_ids_come_from_the_highest_in_use_not_the_count(root, one_feature):
    """Once a caller may supply an id the list can carry gaps, and length-plus-one walks straight
    into an id that is already taken."""
    add(root, flags={"--question-id": "F-001-Q-09", "--text": "gap probe",
                     "--criticality": "non-critical", "--owner": "dev"})
    out = add(root, flags={"--text": "after the gap", "--criticality": "non-critical",
                           "--owner": "dev"})
    assert out["added"] == ["F-001-Q-10"]
    ids = [q["id"] for q in json.loads((root / FEATURE_JSON).read_text())["questions"]]
    assert len(ids) == len(set(ids))


def test_a_bad_entry_writes_nothing_at_all(tmp_path, root, one_feature):
    batch = tmp_path / "batch.json"
    batch.write_text(json.dumps({"feature": "F-001", "source": "spec F-001",
                                 "questions": [
                                     {"text": "fine", "criticality": "critical", "owner": "dev"},
                                     {"text": "bad", "criticality": "urgent", "owner": "dev"}]}))
    payload = run("question-add", "--root", str(root), "--from", str(batch), expect_ok=False)
    assert "criticality must be one of" in " ".join(payload["errors"])
    assert payload["hint"] == "Nothing was written."
    assert len(json.loads((root / FEATURE_JSON).read_text())["questions"]) == 1


def test_a_batch_lands_as_one_write_with_a_line_each(tmp_path, root, one_feature):
    """The bridge mints several at once and the prose may be in any language — one JSON file
    beats eight shell commands carrying em dashes and apostrophes."""
    batch = tmp_path / "batch.json"
    batch.write_text(json.dumps({"feature": "F-001", "source": "spec F-001 · missing information",
                                 "questions": [
                                     {"text": "The real seven-row rules table — who owns it?",
                                      "criticality": "non-critical", "owner": "client"},
                                     {"text": "Registration volumes for the migration",
                                      "criticality": "non-critical", "owner": "dev"}]}), encoding="utf-8")
    out = run("question-add", "--root", str(root), "--from", str(batch))
    assert out["added"] == ["F-001-Q-02", "F-001-Q-03"]
    trail = (root / "decisions.md").read_text()
    assert trail.count("raised (") == 2
    assert "missing information" in trail
    assert run("validate", "--root", str(root))["healthy"] is True


def test_a_question_needs_a_source_because_a_guess_is_not_evidence(root, one_feature):
    payload = run("question-add", "--root", str(root), "--id", "F-001", "--text", "x",
                  "--criticality", "critical", "--owner", "dev", expect_ok=False)
    assert "--source is required" in " ".join(payload["errors"])


def test_raising_against_an_approved_spec_works_but_warns(root, one_feature):
    """A late blocker is exactly the case only a bundle-time gate catches, so it must be sayable."""
    for stage in ("designing", "client-review", "design-approved", "speccing", "spec-approved"):
        run("feature-set", "--root", str(root), "--id", "F-001", "--status", stage)
    out = add(root, flags={"--text": "New contradiction from the latest call",
                           "--criticality": "critical", "--owner": "client"})
    assert out["added"] == ["F-001-Q-02"]
    assert any("refuse to bundle" in w for w in out["warnings"])


def test_an_unknown_feature_lists_what_exists(root, one_feature):
    payload = run("question-add", "--root", str(root), "--id", "F-404", "--source", "x",
                  "--text", "x", "--criticality", "critical", "--owner", "dev", expect_ok=False)
    assert "F-001" in payload["errors"][0]


# ---------------------------------------------------------------- question-close (non-document answers)


def test_question_close_records_answer_and_source(root, one_feature):
    run("question-close", "--root", str(root), "--question-id", "F-001-Q-01",
        "--answer", "No, sessions cannot overlap.", "--source", "client review packet 2026-03-01",
        "--quote", "One room, one session at a time.")
    record = json.loads((root / "phases/phase-1/features/F-001-session-management/feature.json").read_text())
    q = record["questions"][0]
    assert q["status"] == "resolved"
    assert q["answer_source"] == "client review packet 2026-03-01"
    assert q["answer_quote"] == "One room, one session at a time."
    assert json.loads((root / "registry.json").read_text())["features"][0]["open_questions"]["critical"] == 0
    assert "F-001-Q-01 answered" in (root / "decisions.md").read_text()


def test_question_close_works_without_a_quote(root, one_feature):
    run("question-close", "--root", str(root), "--question-id", "F-001-Q-01",
        "--answer", "Confirmed on the call.", "--source", "client sign-off")
    record = json.loads((root / "phases/phase-1/features/F-001-session-management/feature.json").read_text())
    assert record["questions"][0]["status"] == "resolved"


def test_closing_an_already_closed_question_is_refused(root, one_feature):
    run("question-close", "--root", str(root), "--question-id", "F-001-Q-01",
        "--answer", "yes", "--source", "client")
    payload = run("question-close", "--root", str(root), "--question-id", "F-001-Q-01",
                  "--answer", "yes again", "--source", "client", expect_ok=False)
    assert "not an open question" in payload["errors"][0]


def test_overlap_is_recorded_on_both_features(tmp_path, root, source, one_feature):
    second = plan_for(source)
    second["new_features"][0].update({"title": "Academy", "slug": "academy"})
    run("apply-plan", "--root", str(root), "--plan", write_plan(tmp_path, second, "p2.json"))
    out = run("feature-set", "--root", str(root), "--id", "F-002", "--overlaps", "F-001",
              "--note", "Academy repeats most of sessions")
    assert "overlaps F-001 (both ways)" in out["changed"]
    registry = {f["id"]: f for f in json.loads((root / "registry.json").read_text())["features"]}
    assert registry["F-002"]["overlaps"] == ["F-001"]
    assert registry["F-001"]["overlaps"] == ["F-002"], "a one-sided edge is a graph everyone has to guess at"
    peer = json.loads((root / "phases/phase-1/features/F-001-session-management/feature.json").read_text())
    assert peer["overlaps"] == ["F-002"]


def test_self_overlap_is_refused(root, one_feature):
    payload = run("feature-set", "--root", str(root), "--id", one_feature,
                  "--overlaps", one_feature, expect_ok=False)
    assert "cannot overlap itself" in payload["errors"][0]


# ---------------------------------------------------------------- phases


@pytest.fixture
def two_features(tmp_path, root, source):
    run("apply-plan", "--root", str(root), "--plan", write_plan(tmp_path, plan_for(source)))
    second = plan_for(source)
    second["new_features"][0].update({"title": "Academy", "slug": "academy"})
    run("apply-plan", "--root", str(root), "--plan", write_plan(tmp_path, second, "p2.json"))
    return root


def test_phase_open_carries_forward_what_the_last_phase_left(root, two_features):
    run("feature-set", "--root", str(root), "--id", "F-002", "--add-flag", "deferred")
    out = run("phase-open", "--root", str(root), "--phase", "phase-2", "--from", "phase-1",
              "--exit-criterion", "Every feature spec-approved")
    carried = out["carried_over"]
    assert carried["from"] == "phase-1"
    assert {q["feature"] for q in carried["questions"]} == {"F-001", "F-002"}
    assert [f["id"] for f in carried["features"]] == ["F-002"]
    assert out["current_phase"] == "phase-2"
    record = json.loads((root / "phases/phase-2/phase.json").read_text())
    assert record["exit_criteria"] == ["Every feature spec-approved"]


def test_phase_open_carries_open_change_records(root, two_features):
    run("feature-set", "--root", str(root), "--id", "F-001", "--status", "designing", "--by", "t")
    run("feature-set", "--root", str(root), "--id", "F-001", "--status", "client-review", "--by", "t")
    run("feature-set", "--root", str(root), "--id", "F-001", "--status", "design-approved", "--by", "t")
    run("feature-set", "--root", str(root), "--id", "F-001", "--status", "speccing", "--by", "t")
    run("feature-set", "--root", str(root), "--id", "F-001", "--status", "spec-approved", "--by", "t")
    run("change-add", "--root", str(root), "--id", "F-001", "--text", "Overlap is allowed now.",
        "--source", "call with the client")
    out = run("phase-open", "--root", str(root), "--phase", "phase-2", "--from", "phase-1")
    carried = out["carried_over"]["changes"]
    assert [c["change_id"] for c in carried] == ["F-001-C-01"]
    assert carried[0]["feature"] == "F-001"
    assert carried[0]["route"] == "in-flight"


def test_a_change_scheduled_to_a_phase_surfaces_when_that_phase_opens(root, two_features):
    for stage in ("designing", "client-review", "design-approved", "speccing", "spec-approved"):
        run("feature-set", "--root", str(root), "--id", "F-001", "--status", stage, "--by", "t")
    run("change-add", "--root", str(root), "--id", "F-001", "--text", "Bigger than this phase.",
        "--source", "call")
    run("change-close", "--root", str(root), "--change-id", "F-001-C-01",
        "--resolution", "too big for phase-1", "--outcome", "scheduled", "--scheduled-to", "phase-2")
    out = run("phase-open", "--root", str(root), "--phase", "phase-2", "--from", "phase-1")
    assert [c["change_id"] for c in out["carried_over"]["changes"]] == ["F-001-C-01"]


def test_a_second_phase_cannot_be_opened_twice(root, two_features):
    run("phase-open", "--root", str(root), "--phase", "phase-2")
    assert "already exists" in run("phase-open", "--root", str(root), "--phase", "phase-2",
                                   expect_ok=False)["errors"][0]


def test_moving_a_feature_keeps_its_id_and_everything_under_it(root, two_features):
    run("phase-open", "--root", str(root), "--phase", "phase-2", "--keep-current")
    old_dir = root / "phases/phase-1/features/F-002-academy"
    (old_dir / "spec.md").write_text("# Academy spec\n")
    out = run("phase-move", "--root", str(root), "--id", "F-002", "--to", "phase-2",
              "--reason", "client deferred it")
    assert out["moved"] is True and "deferred" in out["flags"]
    new_dir = root / "phases/phase-2/features/F-002-academy"
    assert not old_dir.exists()
    assert (new_dir / "spec.md").read_text() == "# Academy spec\n"
    assert (new_dir / "signal.md").exists(), "accumulated evidence travels with the feature"
    registry = {f["id"]: f for f in json.loads((root / "registry.json").read_text())["features"]}
    assert registry["F-002"]["phase"] == "phase-2"
    assert json.loads((new_dir / "feature.json").read_text())["phase"] == "phase-2"
    assert json.loads((root / "phases/phase-2/phase.json").read_text())["features"] == ["F-002"]
    assert json.loads((root / "phases/phase-1/phase.json").read_text())["features"] == ["F-001"]


def test_moving_back_clears_the_deferred_flag(root, two_features):
    run("phase-open", "--root", str(root), "--phase", "phase-2", "--keep-current")
    run("phase-move", "--root", str(root), "--id", "F-002", "--to", "phase-2")
    out = run("phase-move", "--root", str(root), "--id", "F-002", "--to", "phase-1")
    assert "deferred" not in out["flags"]


def test_a_move_that_would_strand_a_dependency_is_refused(root, two_features):
    run("feature-set", "--root", str(root), "--id", "F-001", "--depends-on", "F-002")
    run("phase-open", "--root", str(root), "--phase", "phase-2", "--keep-current")
    payload = run("phase-move", "--root", str(root), "--id", "F-002", "--to", "phase-2", expect_ok=False)
    joined = " ".join(payload["errors"])
    assert "F-001 depends on F-002" in joined or "depends on F-002" in joined
    assert "--force" in joined


def test_a_stranding_move_can_be_forced_and_is_recorded(root, two_features):
    run("feature-set", "--root", str(root), "--id", "F-001", "--depends-on", "F-002")
    run("phase-open", "--root", str(root), "--phase", "phase-2", "--keep-current")
    out = run("phase-move", "--root", str(root), "--id", "F-002", "--to", "phase-2", "--force")
    assert out["violations_accepted"]


def test_closing_a_phase_with_unfinished_work_is_refused_and_names_it(root, two_features):
    payload = run("phase-close", "--root", str(root), "--phase", "phase-1", expect_ok=False)
    joined = " ".join(payload["errors"])
    assert "F-001" in joined and "F-002" in joined
    assert "defer them" in joined


def test_closing_records_the_blocker_count_which_is_the_modules_own_metric(root, two_features):
    for fid in ("F-001", "F-002"):
        for stage in ("designing", "client-review", "design-approved", "speccing",
                      "spec-approved", "handed-off"):
            run("feature-set", "--root", str(root), "--id", fid, "--status", stage)
    out = run("phase-close", "--root", str(root), "--phase", "phase-1", "--prd-path", "_bmad-output/prd.md")
    assert out["blocker_count_at_handoff"] == 2, "one open critical question per feature"
    assert set(out["blockers"]) == {"F-001-Q-01", "F-002-Q-01"}
    record = json.loads((root / "phases/phase-1/phase.json").read_text())
    assert record["status"] == "closed" and record["prd_path"] == "_bmad-output/prd.md"


def test_a_deferred_feature_does_not_block_the_close(root, two_features):
    for stage in ("designing", "client-review", "design-approved", "speccing", "spec-approved", "handed-off"):
        run("feature-set", "--root", str(root), "--id", "F-001", "--status", stage)
    run("feature-set", "--root", str(root), "--id", "F-002", "--add-flag", "deferred")
    assert run("phase-close", "--root", str(root), "--phase", "phase-1")["features"] == 2


def test_a_closed_phase_cannot_be_closed_again(root, two_features):
    run("feature-set", "--root", str(root), "--id", "F-001", "--add-flag", "dropped")
    run("feature-set", "--root", str(root), "--id", "F-002", "--add-flag", "dropped")
    run("phase-close", "--root", str(root), "--phase", "phase-1")
    assert "already closed" in run("phase-close", "--root", str(root), "--phase", "phase-1",
                                   expect_ok=False)["errors"][0]


def test_the_store_stays_consistent_across_a_phase_move(root, two_features):
    run("phase-open", "--root", str(root), "--phase", "phase-2", "--keep-current")
    run("phase-move", "--root", str(root), "--id", "F-002", "--to", "phase-2")
    assert run("validate", "--root", str(root))["healthy"] is True


# ---------------------------------------------------------------- brownfield starting phase


def test_greenfield_init_is_untouched(tmp_path):
    out = run("init", "--root", str(tmp_path / "d"))
    assert out["current_phase"] == "phase-1" and out["phases"] == ["phase-1"]


@pytest.mark.parametrize("start", ["phase-3", "phase-2.1", "phase-10"])
def test_a_store_can_start_at_any_phase(tmp_path, start):
    root = tmp_path / "d"
    out = run("init", "--root", str(root), "--phase", start)
    assert out["current_phase"] == start
    assert out["phases"] == [start]
    assert (root / "phases" / start / "phase.json").exists()
    assert run("validate", "--root", str(root))["healthy"] is True


def test_earlier_phases_are_not_invented(tmp_path):
    """The module never fabricates history it has no evidence for. Prior work belongs in
    as-built.md, not in empty phase records that would poison the blocker trend."""
    root = tmp_path / "d"
    run("init", "--root", str(root), "--phase", "phase-3")
    assert sorted(p.name for p in (root / "phases").iterdir()) == ["phase-3"]
    assert json.loads((root / "registry.json").read_text())["phases"] == ["phase-3"]


def test_phases_stay_in_chronological_order_however_they_are_opened(tmp_path):
    root = tmp_path / "d"
    run("init", "--root", str(root), "--phase", "phase-3")
    run("phase-open", "--root", str(root), "--phase", "phase-10", "--keep-current")
    run("phase-open", "--root", str(root), "--phase", "phase-3.1", "--keep-current")
    out = run("phase-open", "--root", str(root), "--phase", "phase-2", "--keep-current")
    assert out["phase"] == "phase-2"
    phases = json.loads((root / "registry.json").read_text())["phases"]
    assert phases == ["phase-2", "phase-3", "phase-3.1", "phase-10"], \
        "position in the list is chronology; append order is not"


def test_move_direction_is_judged_by_label_not_list_position(tmp_path, root, source):
    """With a brownfield store the phases list can be built out of order, so a move that
    strands a dependency has to be caught from the labels themselves."""
    run("apply-plan", "--root", str(root), "--plan", write_plan(tmp_path, plan_for(source)))
    second = plan_for(source)
    second["new_features"][0].update({"title": "Academy", "slug": "academy"})
    run("apply-plan", "--root", str(root), "--plan", write_plan(tmp_path, second, "p2.json"))
    run("feature-set", "--root", str(root), "--id", "F-001", "--depends-on", "F-002")
    run("phase-open", "--root", str(root), "--phase", "phase-0.5", "--keep-current")
    run("phase-open", "--root", str(root), "--phase", "phase-2", "--keep-current")
    # F-001 depends on F-002; pushing F-002 later than F-001 must be refused.
    payload = run("phase-move", "--root", str(root), "--id", "F-002", "--to", "phase-2", expect_ok=False)
    assert "depends on F-002" in " ".join(payload["errors"])
    # Pulling F-002 earlier is fine.
    assert run("phase-move", "--root", str(root), "--id", "F-002", "--to", "phase-0.5")["moved"] is True


# ---------------------------------------------------------------- as-built seeding


def test_as_built_seed_records_prior_work_as_context(tmp_path, root):
    note = tmp_path / "prior.md"
    note.write_text("### Events\n\nAgenda, sessions and attendance shipped in phases 1 and 2.\n")
    out = run("as-built-seed", "--root", str(root), "--file", str(note),
              "--phase", "phase-3", "--source", "docs/prd-phase-2.md")
    text = (root / out["as_built"]).read_text()
    assert "## Before phase-3" in text
    assert "Agenda, sessions and attendance shipped" in text
    assert "docs/prd-phase-2.md" in text
    assert "not as verified requirements" in text, \
        "seeded content is the BA's word, not something this module verified"
    assert "seeded as-built baseline" in (root / "decisions.md").read_text()


def test_as_built_seed_accepts_inline_text(root):
    run("as-built-seed", "--root", str(root), "--text", "Login and billing already exist.")
    assert "Login and billing already exist." in (root / "as-built.md").read_text()


def test_as_built_seed_needs_something_to_record(root):
    assert "Nothing to record" in run("as-built-seed", "--root", str(root), expect_ok=False)["errors"][0]


def test_as_built_seed_refuses_to_clobber_a_real_baseline(root):
    run("as-built-seed", "--root", str(root), "--text", "First baseline.")
    payload = run("as-built-seed", "--root", str(root), "--text", "Second.", expect_ok=False)
    assert "already describes shipped work" in payload["errors"][0]
    assert "First baseline." in (root / "as-built.md").read_text()


def test_as_built_seed_can_prepend_with_force(root):
    run("as-built-seed", "--root", str(root), "--text", "First baseline.")
    run("as-built-seed", "--root", str(root), "--text", "Newer baseline.", "--force")
    text = (root / "as-built.md").read_text()
    assert "Newer baseline." in text and "First baseline." in text


def test_as_built_seed_needs_a_store(tmp_path):
    payload = run("as-built-seed", "--root", str(tmp_path / "nope"), "--text", "x", expect_ok=False)
    assert "init" in payload["errors"][0]


# ---------------------------------------------------------------- change records


def _locked(root, status="spec-approved"):
    for stage in ("designing", "client-review", "design-approved", "speccing", "spec-approved"):
        run("feature-set", "--root", str(root), "--id", "F-001", "--status", stage, "--by", "t")
        if stage == status:
            return
    if status == "handed-off":
        run("feature-set", "--root", str(root), "--id", "F-001", "--status", "handed-off", "--by", "t")


def test_change_add_below_spec_approved_is_refused_and_names_question_add(root, two_features):
    payload = run("change-add", "--root", str(root), "--id", "F-001", "--text", "x",
                  "--source", "call", expect_ok=False)
    assert "question-add" in payload["errors"][0]


def test_a_change_raised_after_handoff_routes_to_delivered(root, two_features):
    _locked(root, "handed-off")
    out = run("change-add", "--root", str(root), "--id", "F-001", "--text", "Urgent fix.",
              "--source", "call")
    assert out["routes"]["F-001-C-01"] == "delivered"
    assert any("build-brief" in w for w in out["warnings"])


def test_the_route_is_frozen_at_raise_time(root, two_features):
    """A change the BA agreed to absorb must not become somebody else's work because the phase
    moved on underneath it."""
    _locked(root)
    run("change-add", "--root", str(root), "--id", "F-001", "--text", "Absorb this.",
        "--source", "call")
    run("feature-set", "--root", str(root), "--id", "F-001", "--status", "handed-off", "--by", "t")
    record = json.loads((root / "phases/phase-1/features/F-001-session-management/feature.json").read_text())
    assert record["changes"][0]["route"] == "in-flight"
    assert record["changes"][0]["status_when_raised"] == "spec-approved"


def test_change_ids_come_from_the_highest_in_use(root, two_features):
    _locked(root)
    run("change-add", "--root", str(root), "--id", "F-001", "--text", "a", "--source", "s",
        "--change-id", "F-001-C-09")
    out = run("change-add", "--root", str(root), "--id", "F-001", "--text", "b", "--source", "s")
    assert out["added"] == ["F-001-C-10"], "length-plus-one would collide with C-09"


def test_a_bad_batch_entry_writes_nothing_at_all(root, two_features, tmp_path):
    _locked(root)
    batch = tmp_path / "b.json"
    batch.write_text(json.dumps({"feature": "F-001", "source": "call", "changes": [
        {"text": "fine"}, {"text": "", "criticality": "urgent"}]}))
    run("change-add", "--root", str(root), "--from", str(batch), expect_ok=False)
    record = json.loads((root / "phases/phase-1/features/F-001-session-management/feature.json").read_text())
    assert record.get("changes", []) == []


def test_an_ingested_source_needs_an_anchor_and_a_quote(root, two_features):
    _locked(root)
    payload = run("change-add", "--root", str(root), "--id", "F-001", "--text", "x",
                  "--source", "2026-08-25-call", expect_ok=False)
    assert "anchored or it is hearsay" in payload["errors"][0]


def test_change_close_needs_a_named_record(root, two_features):
    _locked(root)
    run("change-add", "--root", str(root), "--id", "F-001", "--text", "a", "--source", "s")
    payload = run("change-close", "--root", str(root), "--change-id", "F-001-C-99",
                  "--resolution", "x", "--absorbed-by", "F-001-R-01", expect_ok=False)
    assert "No change" in payload["errors"][0]


def test_the_changed_flag_clears_only_when_the_last_change_closes(root, two_features):
    _locked(root)
    run("change-add", "--root", str(root), "--id", "F-001", "--text", "a", "--source", "s")
    run("change-add", "--root", str(root), "--id", "F-001", "--text", "b", "--source", "s")
    out = run("change-close", "--root", str(root), "--change-id", "F-001-C-01",
              "--resolution", "done", "--absorbed-by", "F-001-R-01")
    assert "changed" in out["flags"], "one closed, one still open"
    out = run("change-close", "--root", str(root), "--change-id", "F-001-C-02",
              "--resolution", "done", "--absorbed-by", "F-001-R-01")
    assert "changed" not in out["flags"]


def test_scheduled_needs_a_destination(root, two_features):
    _locked(root)
    run("change-add", "--root", str(root), "--id", "F-001", "--text", "a", "--source", "s")
    payload = run("change-close", "--root", str(root), "--change-id", "F-001-C-01",
                  "--resolution", "later", "--outcome", "scheduled", expect_ok=False)
    assert "--scheduled-to" in payload["errors"][0]


def test_validate_catches_a_duplicate_change_id(root, two_features):
    _locked(root)
    run("change-add", "--root", str(root), "--id", "F-001", "--text", "a", "--source", "s")
    fdir = root / "phases/phase-1/features/F-001-session-management"
    record = json.loads((fdir / "feature.json").read_text())
    record["changes"].append(dict(record["changes"][0]))
    (fdir / "feature.json").write_text(json.dumps(record))
    payload = run("validate", "--root", str(root), expect_ok=False)
    assert any("duplicate change id" in p for p in payload["problems"])


def test_changes_md_is_regenerated_from_the_ledger(root, two_features):
    _locked(root)
    run("change-add", "--root", str(root), "--id", "F-001", "--text", "a", "--source", "s")
    changes = root / "phases/phase-1/features/F-001-session-management/changes.md"
    changes.write_text("hand-edited nonsense\n")
    run("change-add", "--root", str(root), "--id", "F-001", "--text", "b", "--source", "s")
    text = changes.read_text()
    assert "hand-edited nonsense" not in text, "derived files are rewritten, not merged"
    assert "F-001-C-01" in text and "F-001-C-02" in text


def test_a_change_may_be_raised_against_a_feature_in_a_closed_phase(root, two_features):
    """Case 2 is exactly this. Gating writes into a closed phase uniformly would break it."""
    _locked(root, "handed-off")
    phase = root / "phases/phase-1/phase.json"
    record = json.loads(phase.read_text())
    record["status"] = "closed"
    phase.write_text(json.dumps(record))
    out = run("change-add", "--root", str(root), "--id", "F-001", "--text", "Urgent.", "--source", "s")
    assert out["routes"]["F-001-C-01"] == "delivered"


def test_a_feature_cannot_be_moved_into_a_closed_phase(root, two_features):
    run("phase-open", "--root", str(root), "--phase", "phase-2")
    phase = root / "phases/phase-2/phase.json"
    record = json.loads(phase.read_text())
    record["status"] = "closed"
    phase.write_text(json.dumps(record))
    payload = run("phase-move", "--root", str(root), "--id", "F-001", "--to", "phase-2",
                  "--reason", "x", expect_ok=False)
    assert "closed" in payload["errors"][0]
