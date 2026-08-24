#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["pytest"]
# ///
"""Tests for fdw_elaborate.py — gathering, validation, the approval gate, and id minting."""

import json
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "fdw_elaborate.py"
SECTIONS = ["Need", "Rules", "Requirements", "Out of scope", "Assumptions",
            "Open questions", "Contradictions", "Missing information"]


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
    root = tmp_path / "discovery"
    fdir = root / "phases" / "phase-1" / "features" / "F-001-academy"
    (fdir / "design").mkdir(parents=True)
    (root / "registry.json").write_text(json.dumps({
        "current_phase": "phase-1", "phases": ["phase-1"],
        "features": [{"id": "F-001", "title": "Academy", "slug": "academy", "phase": "phase-1",
                      "status": "design-approved", "flags": [], "size": None,
                      "depends_on": ["F-002"], "overlaps": ["F-002"],
                      "open_questions": {"critical": 1, "non-critical": 1}}],
    }))
    (fdir / "feature.json").write_text(json.dumps({
        "id": "F-001", "title": "Academy", "status": "design-approved", "summary": "Learning area.",
        "questions": [
            {"id": "F-001-Q-01", "text": "Which Events parts are reused?", "criticality": "critical",
             "owner": "client", "status": "open"},
            {"id": "F-001-Q-02", "text": "Copy for the empty list?", "criticality": "non-critical",
             "owner": "internal", "status": "open"},
            {"id": "F-001-Q-03", "text": "Certificate export?", "criticality": "critical",
             "owner": "client", "status": "resolved", "answer": "Yes, PDF."},
        ],
    }))
    (fdir / "signal.md").write_text(
        "# Academy — Signal\n\n- Academy has certification and course pages.\n"
        "  - anchor: `2026-08-22-academy#t=18:24`\n  - quote: > certification, trainings\n"
    )
    (fdir / "design" / "ux-notes.md").write_text(
        "# Academy — UX Notes\n\n## Screens\n\n- **S1 — Course list** — where a learner finds a course\n\n"
        "## Assumptions\n\n"
        "- **A1** (S1) — a course is publishable before sessions exist. _Status: confirmed_\n"
        "- **A2** (S1) — courses are newest first. _Status: unconfirmed_\n\n"
        f"## Corrections\n\n- {date.today().isoformat()} — S1 — added an empty state\n"
    )
    (fdir / "design" / "empty-state.md").write_text(
        "# Academy\n\n## Gaps found\n\n- **G1** (S1) — no create-course entry point.\n")
    return root


def write_spec(store, *, requirements=None, stub_sections=(), size="M", open_questions=None,
               missing_information="None outstanding."):
    """A complete spec unless the test asks for a hole in it."""
    fdir = store / "phases/phase-1/features/F-001-academy"
    reqs = requirements if requirements is not None else [
        "- A course can be published before any sessions exist. [from: A1]",
        "- Course pages carry Overview, Sessions and Certification tabs. [src: 2026-08-22-academy#t=18:24]",
    ]
    parts = [
        "# Academy — Spec\n",
        f"**Feature:** F-001 · **Phase:** phase-1 · **Status:** draft",
        f"**Size:** {size}",
        "**Depends on:** F-002\n",
    ]
    filler = {
        "Need": "**Problem.** Learners have nowhere to train.\n\n**Outcome.** They can enrol and be certified.",
        "Rules": "- Only administrators publish a course.",
        "Requirements": "\n".join(reqs),
        "Out of scope": "- Payment for courses.",
        "Assumptions": "- A course is publishable before sessions exist (confirmed by the client).",
        "Open questions": open_questions if open_questions is not None else (
            "- **[F-001-Q-01]** **critical** (client) — Which Events parts are reused?\n"
            "- **[F-001-Q-02]** **non-critical** (internal) — Copy for the empty list?"),
        "Contradictions": "None found.",
        "Missing information": missing_information,
    }
    for name in SECTIONS:
        body = "_Not written yet._" if name in stub_sections else filler[name]
        parts.append(f"## {name}\n\n{body}\n")
    (fdir / "spec.md").write_text("\n".join(parts), encoding="utf-8")
    return fdir / "spec.md"


def close_all_questions(store):
    """Approval now refuses on any open question, not only the critical ones."""
    fdir = store / "phases/phase-1/features/F-001-academy"
    record = json.loads((fdir / "feature.json").read_text())
    for q in record["questions"]:
        q["status"] = "resolved"
    (fdir / "feature.json").write_text(json.dumps(record))


# ---------------------------------------------------------------- gather


def test_gather_refuses_before_the_client_approved_the_design(store):
    registry = json.loads((store / "registry.json").read_text())
    registry["features"][0]["status"] = "designing"
    (store / "registry.json").write_text(json.dumps(registry))
    payload = run("gather", "--root", str(store), "--id", "F-001", expect_ok=False)
    assert "that ordering is the method" in " ".join(payload["errors"])


def test_gather_collects_the_design_record_and_the_evidence(store):
    out = run("gather", "--root", str(store), "--id", "F-001")
    assert out["screens"] == ["S1 — Course list"]
    assert [(a["id"], a["status"]) for a in out["assumptions"]] == [("A1", "confirmed"), ("A2", "unconfirmed")]
    assert out["signal_anchors"] == ["2026-08-22-academy#t=18:24"]
    assert out["empty_state_gaps"] == ["G1 — no create-course entry point."]
    assert len(out["corrections"]) == 1
    assert [q["id"] for q in out["open_questions"]] == ["F-001-Q-01", "F-001-Q-02"]
    assert out["depends_on"] == ["F-002"]
    assert out["spec_exists"] is False


# ---------------------------------------------------------------- scaffold and check


def test_scaffold_writes_every_required_section_as_a_stub(store):
    run("scaffold", "--root", str(store), "--id", "F-001")
    text = (store / "phases/phase-1/features/F-001-academy/spec.md").read_text()
    for name in SECTIONS:
        assert f"## {name}" in text
    assert "SANDBOX" in text


def test_scaffold_never_overwrites_a_written_spec(store):
    write_spec(store)
    out = run("scaffold", "--root", str(store), "--id", "F-001")
    assert out["already_present"] is True
    assert "Learners have nowhere to train" in (store / out["spec"]).read_text()


def test_check_passes_a_complete_spec(store):
    write_spec(store)
    out = run("check", "--root", str(store), "--id", "F-001")
    assert out["structurally_ready"] is True
    assert out["requirements"] == 2
    assert out["numbered"] == 0, "ids are minted at approval, not while drafting"
    assert out["critical_open"] == ["F-001-Q-01"]


def test_a_stub_section_blocks_because_none_is_still_an_answer(store):
    write_spec(store, stub_sections=("Contradictions",))
    payload = run("check", "--root", str(store), "--id", "F-001", expect_ok=False)
    assert any("'none' is an answer worth writing down" in e for e in payload["errors"])


def test_a_requirement_without_provenance_is_refused(store):
    write_spec(store, requirements=["- Courses can be archived."])
    payload = run("check", "--root", str(store), "--id", "F-001", expect_ok=False)
    joined = " ".join(payload["errors"])
    assert "no provenance" in joined
    assert "[src:" in joined and "[from:" in joined


def test_design_derived_provenance_is_valid_because_the_client_signed_the_design(store):
    write_spec(store, requirements=["- A course is publishable before sessions exist. [from: A1]"])
    assert run("check", "--root", str(store), "--id", "F-001")["structurally_ready"] is True


def test_a_spec_with_no_requirements_is_not_a_spec(store):
    write_spec(store, requirements=["_None yet._"])
    payload = run("check", "--root", str(store), "--id", "F-001", expect_ok=False)
    assert any("nothing to build" in e for e in payload["errors"])


def test_size_must_be_set_because_it_drives_scope_and_order(store):
    write_spec(store, size="—")
    payload = run("check", "--root", str(store), "--id", "F-001", expect_ok=False)
    assert any("drives phase scope and build order" in e for e in payload["errors"])


def test_check_without_a_spec_names_the_scaffold_command(store):
    payload = run("check", "--root", str(store), "--id", "F-001", expect_ok=False)
    assert "scaffold" in payload["errors"][0]


# ---------------------------------------------------------------- the approval gate


def test_approval_refuses_while_any_question_is_open(store):
    """Not just the critical ones. Every question in the epp spec that reached the PRD was marked
    non-critical, so a critical-only gate would have let that PRD through unchanged."""
    write_spec(store)
    payload = run("approve", "--root", str(store), "--id", "F-001", expect_ok=False)
    joined = " ".join(payload["errors"])
    assert "F-001-Q-01 (critical · client)" in joined
    assert "F-001-Q-02 (non-critical · internal)" in joined
    assert "2 question(s) still open (1 critical)" in joined
    assert "drive to zero" in joined


def test_approval_refuses_on_a_non_critical_question_alone(store):
    write_spec(store)
    fdir = store / "phases/phase-1/features/F-001-academy"
    record = json.loads((fdir / "feature.json").read_text())
    record["questions"][0]["status"] = "resolved"
    (fdir / "feature.json").write_text(json.dumps(record))
    payload = run("approve", "--root", str(store), "--id", "F-001", expect_ok=False)
    assert "1 question(s) still open (0 critical)" in " ".join(payload["errors"])


def test_approval_succeeds_once_blockers_are_closed_and_mints_ids(store):
    write_spec(store)
    close_all_questions(store)
    out = run("approve", "--root", str(store), "--id", "F-001")
    assert out["minted"] == ["F-001-R-01", "F-001-R-02"]
    text = (store / out["spec"]).read_text()
    assert "**[F-001-R-01]** A course can be published" in text
    assert f"**Status:** approved {date.today().isoformat()}" in text
    assert any("--size M" in step for step in out["next"])


def test_reapproval_preserves_ids_and_only_numbers_what_is_new(store):
    write_spec(store)
    close_all_questions(store)
    run("approve", "--root", str(store), "--id", "F-001")
    spec = store / "phases/phase-1/features/F-001-academy/spec.md"
    text = spec.read_text().replace(
        "- **[F-001-R-02]**",
        "- A learner can withdraw from a course. [from: A2]\n- **[F-001-R-02]**", 1)
    spec.write_text(text)
    out = run("approve", "--root", str(store), "--id", "F-001")
    assert out["minted"] == ["F-001-R-03"], "existing ids must never shift when a line is inserted"
    assert set(out["preserved"]) == {"F-001-R-01", "F-001-R-02"}
    final = spec.read_text()
    assert "**[F-001-R-01]** A course can be published" in final
    assert "**[F-001-R-03]** A learner can withdraw" in final


def test_the_override_is_available_and_records_what_it_let_through(store):
    write_spec(store)
    out = run("approve", "--root", str(store), "--id", "F-001", "--accept-open-blockers")
    assert out["approved_with_open_blockers"] == ["F-001-Q-01", "F-001-Q-02"]
    text = (store / out["spec"]).read_text()
    assert "## Approved with open blockers" in text
    assert "travel into the phase PRD unresolved" in text
    # critical first, and each one says which it is, so the section does not imply all are critical
    assert text.index("F-001-Q-01 (critical") < text.index("F-001-Q-02 (non-critical")


def test_approval_refuses_while_a_change_record_is_open(store):
    write_spec(store)
    close_all_questions(store)
    (store / "phases/phase-1/features/F-001-academy/changes.md").write_text(
        "\n## 2026-08-25 — change raised by client-call\n\n- what: sessions may overlap\n"
        "- resolution: OPEN — route through fdw-elaborate. Intake never edits an approved spec.\n")
    payload = run("approve", "--root", str(store), "--id", "F-001", expect_ok=False)
    assert any("unresolved change record" in e for e in payload["errors"])


def test_a_structurally_broken_spec_cannot_be_approved(store):
    write_spec(store, requirements=["- Courses can be archived."])
    close_all_questions(store)
    payload = run("approve", "--root", str(store), "--id", "F-001", expect_ok=False)
    assert any("no provenance" in e for e in payload["errors"])


# ---------------------------------------------------------------- change records


def test_close_change_records_the_resolution(store):
    (store / "phases/phase-1/features/F-001-academy/changes.md").write_text(
        "\n## 2026-08-25 — change raised by client-call\n\n- what: sessions may overlap\n"
        "- resolution: OPEN — route through fdw-elaborate. Intake never edits an approved spec.\n")
    out = run("close-change", "--root", str(store), "--id", "F-001",
              "--resolution", "absorbed as R-04; overlapping sessions now permitted per room")
    assert out["remaining_open"] == 0
    text = (store / out["changes"]).read_text()
    assert "absorbed as R-04" in text
    assert "resolution: OPEN" not in text


def test_close_change_with_nothing_open_says_so(store):
    payload = run("close-change", "--root", str(store), "--id", "F-001",
                  "--resolution", "x", expect_ok=False)
    assert "no change record" in payload["errors"][0]


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))


# ---------------------------------------------------------------- advancing without hitting a gate


def test_scaffold_points_at_marking_the_feature_speccing(store):
    steps = run("scaffold", "--root", str(store), "--id", "F-001")["next"]
    assert len(steps) == 1 and "--status speccing" in steps[0]


def test_approve_walks_every_gate_from_where_the_feature_is(store):
    """A single spec-approved command would be refused from design-approved."""
    write_spec(store)
    close_all_questions(store)
    steps = run("approve", "--root", str(store), "--id", "F-001")["next"]
    assert [s.split("--status ")[1].split(" ")[0] for s in steps] == ["speccing", "spec-approved"]
    assert "--size M" in steps[-1]


def test_approve_from_speccing_is_a_single_step(store):
    registry = json.loads((store / "registry.json").read_text())
    registry["features"][0]["status"] = "speccing"
    (store / "registry.json").write_text(json.dumps(registry))
    write_spec(store)
    close_all_questions(store)
    steps = run("approve", "--root", str(store), "--id", "F-001")["next"]
    assert len(steps) == 1 and "--status spec-approved" in steps[0]


# ---------------------------------------------------------------- the spec-to-ledger bridge

STATE = Path(__file__).resolve().parents[3] / "fdw-intake" / "scripts" / "fdw_state.py"


def state(*args, expect_ok=True):
    """expect_ok=None when the call's success is not what the test is about."""
    result = subprocess.run([sys.executable, str(STATE), *args], capture_output=True, text=True)
    payload = json.loads(result.stdout)
    if expect_ok is not None:
        assert payload.get("ok") is expect_ok, payload
    return payload


def ledger(store):
    fdir = store / "phases/phase-1/features/F-001-academy"
    return {q["id"]: q for q in json.loads((fdir / "feature.json").read_text())["questions"]}


def test_a_question_written_only_in_prose_is_minted_and_filed(store):
    """The defect: prose is counted by nothing. Eight questions reached a real PRD this way."""
    write_spec(store, open_questions="- **critical** (client) — Which precedence order?")
    out = run("questions", "--root", str(store), "--id", "F-001")
    assert out["minted"] == ["F-001-Q-04"]
    spec = (store / "phases/phase-1/features/F-001-academy/spec.md").read_text()
    assert "- **[F-001-Q-04]** **critical** (client) — Which precedence order?" in spec
    assert out["run"] and "question-add" in out["run"][0]

    state(*out["run"][0].split()[3:])
    assert "F-001-Q-04" in ledger(store)
    again = run("questions", "--root", str(store), "--id", "F-001")
    assert again["minted"] == [] and again["run"] == []


def test_missing_information_is_filed_too_under_its_own_origin(store):
    """Four of the eleven questions in the real PRD came from this section."""
    write_spec(store, missing_information="- **non-critical** (client) — The real rules table.")
    out = run("questions", "--root", str(store), "--id", "F-001")
    assert out["minted"] == ["F-001-Q-04"]
    state(*out["run"][-1].split()[3:])
    assert ledger(store)["F-001-Q-04"]["raised_by"].endswith("missing information")


def test_check_and_approve_both_refuse_until_the_prose_is_filed(store):
    write_spec(store, open_questions="- **critical** (client) — Which precedence order?")
    for command in ("check", "approve"):
        payload = run(command, "--root", str(store), "--id", "F-001", expect_ok=False)
        assert "not in the ledger" in " ".join(payload["errors"])


def test_the_override_cannot_hide_a_question_the_ledger_never_heard_of(store):
    """--accept-open-blockers accepts KNOWN blockers. A prose id with no ledger entry is an
    unknown one, and letting it through is the whole failure this change exists to stop."""
    write_spec(store, open_questions="- **[F-001-Q-77]** **critical** (client) — Never filed.")
    payload = run("approve", "--root", str(store), "--id", "F-001",
                  "--accept-open-blockers", expect_ok=False)
    assert "F-001-Q-77" in " ".join(payload["errors"])


def test_a_bullet_nobody_can_parse_is_named_not_skipped(store):
    """A question silently dropped on the floor is the bug class being fixed."""
    write_spec(store, open_questions="- we should probably ask about the ordering")
    payload = run("check", "--root", str(store), "--id", "F-001", expect_ok=False)
    joined = " ".join(payload["errors"])
    assert "does not parse" in joined and "ordering" in joined


def test_a_question_deleted_from_the_spec_is_reported_and_can_be_restored(store):
    write_spec(store, open_questions="- **[F-001-Q-01]** **critical** (client) — Which parts?")
    out = run("questions", "--root", str(store), "--id", "F-001")
    assert out["missing_from_prose"] == ["F-001-Q-02"]
    restored = run("questions", "--root", str(store), "--id", "F-001", "--reconcile")
    assert restored["restored"] == ["F-001-Q-02"]
    spec = (store / "phases/phase-1/features/F-001-academy/spec.md").read_text()
    assert "**[F-001-Q-02]** **non-critical** (internal) — Copy for the empty list?" in spec
    assert run("questions", "--root", str(store), "--id", "F-001")["missing_from_prose"] == []


def test_a_resolved_question_still_in_the_spec_is_reported(store):
    write_spec(store, open_questions=(
        "- **[F-001-Q-01]** **critical** (client) — Which parts?\n"
        "- **[F-001-Q-02]** **non-critical** (internal) — Copy?\n"
        "- **[F-001-Q-03]** **critical** (client) — Certificate export?"))
    out = run("questions", "--root", str(store), "--id", "F-001")
    assert out["resolved_still_in_prose"] == ["F-001-Q-03"]


def test_triage_disagreement_is_reported_never_silently_resolved(store):
    write_spec(store, open_questions=(
        "- **[F-001-Q-01]** **non-critical** (dev) — Which parts?\n"
        "- **[F-001-Q-02]** **non-critical** (internal) — Copy?"))
    out = run("questions", "--root", str(store), "--id", "F-001")
    assert out["triage_drift"] == [
        {"id": "F-001-Q-01", "spec": "non-critical/dev", "ledger": "critical/client"}]
    assert ledger(store)["F-001-Q-01"]["criticality"] == "critical", "nothing may be rewritten"


def test_the_full_loop_keeps_the_registry_mirror_honest(store):
    """The registry keeps a denormalised count that validate fails the whole store on."""
    write_spec(store, open_questions="- **critical** (dev) — How does migration resolve?")
    out = run("questions", "--root", str(store), "--id", "F-001")
    state(*out["run"][0].split()[3:])
    report = state("validate", "--root", str(store), expect_ok=None)
    problems = report.get("problems", []) + report.get("errors", [])
    assert not any("open_questions count is stale" in p for p in problems), problems


def test_a_question_that_wraps_across_lines_is_filed_whole(store):
    """Real specs wrap. A ledger entry cut off mid-sentence is useless to the person answering it."""
    write_spec(store, open_questions=(
        "- **critical** (client) — Should a person's account record several kinds of person\n"
        "  permanently, or is per-event categorisation on the registration enough?"))
    out = run("questions", "--root", str(store), "--id", "F-001")
    state(*out["run"][0].split()[3:])
    text = ledger(store)["F-001-Q-04"]["text"]
    assert text.endswith("on the registration enough?")
    spec = (store / "phases/phase-1/features/F-001-academy/spec.md").read_text()
    assert "permanently, or is per-event" in spec
    assert run("questions", "--root", str(store), "--id", "F-001")["minted"] == []
