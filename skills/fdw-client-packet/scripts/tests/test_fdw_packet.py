#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["pytest"]
# ///
"""Tests for fdw_packet.py — gathering, the vocabulary gate, and rendering the client packet."""

import base64
import json
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "fdw_packet.py"
EXAMPLE = Path(__file__).resolve().parents[2] / "assets" / "packet.example.json"

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


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
    (fdir / "design" / "prototype").mkdir(parents=True)
    (fdir / "design" / "prototype" / "CourseList.tsx").write_text("export default function CourseList(){}\n")
    (root / "registry.json").write_text(json.dumps({
        "current_phase": "phase-1", "phases": ["phase-1"],
        "features": [{"id": "F-001", "title": "Academy", "slug": "academy",
                      "phase": "phase-1", "status": "client-review", "flags": []}],
    }))
    (fdir / "feature.json").write_text(json.dumps({
        "id": "F-001", "title": "Academy", "status": "client-review", "summary": "Learning area.",
        "questions": [
            {"id": "F-001-Q-01", "text": "Which Events parts are reused?", "criticality": "critical",
             "owner": "client", "status": "open"},
            {"id": "F-001-Q-02", "text": "Preferred empty-state copy?", "criticality": "non-critical",
             "owner": "internal", "status": "open"},
            {"id": "F-001-Q-03", "text": "Already answered", "criticality": "critical",
             "owner": "client", "status": "resolved"},
        ],
    }))
    (fdir / "design" / "ux-notes.md").write_text(
        "# Academy — UX Notes\n\n## Screens\n\n"
        "- **S1 — Course list** — where a learner finds a course\n"
        "- **S2 — Course page** — tabs\n\n"
        "## Assumptions\n\n"
        "- **A1** (S2) — a course with no sessions is publishable. _Status: unconfirmed_\n"
        "- **A2** (S1) — courses are newest first. _Status: confirmed_\n\n"
        "## Corrections\n\n"
        f"- {date.today().isoformat()} — S2 — tabs were fixed height → sections\n"
    )
    (fdir / "design" / "empty-state.md").write_text(
        "# Academy\n\n## Gaps found\n\n- **G1** (S1) — no create-course entry point.\n"
    )
    return root


def content(tmp_path, **overrides):
    base = {
        "headline": "Academy — what we're proposing",
        "intro": "Following our call, here is how we think this should work.",
        "sections": [{"screen": "Course list", "what_you_see": "Every course you offer.",
                      "how_it_works": "Selecting one opens it."}],
        "assumptions": [{"we_assumed": "A course can be published before sessions exist.",
                         "why_it_matters": "It changes how you would set one up."}],
        "questions": [{"ref": "F-001-Q-01", "question": "What should each tab contain?",
                       "context": "We proposed three."}],
        "next_steps": "Send us anything that reads wrong.",
    }
    base.update(overrides)
    path = tmp_path / "content.json"
    path.write_text(json.dumps(base), encoding="utf-8")
    return str(path)


# ---------------------------------------------------------------- gather


def test_gather_collects_only_what_the_client_needs(store):
    out = run("gather", "--root", str(store), "--id", "F-001")
    assert out["screens"] == ["S1 — Course list", "S2 — Course page"]
    assert [a["status"] for a in out["assumptions"]] == ["unconfirmed", "confirmed"]
    assert out["unconfirmed_assumptions"] == 1
    assert [q["id"] for q in out["client_questions"]] == ["F-001-Q-01"], \
        "internal-owned and already-resolved questions are not the client's to answer"


def test_gather_refuses_when_there_is_nothing_to_show(store):
    for f in (store / "phases/phase-1/features/F-001-academy/design/prototype").iterdir():
        f.unlink()
    payload = run("gather", "--root", str(store), "--id", "F-001", expect_ok=False)
    assert any("no prototype to show" in e for e in payload["errors"])


def test_gather_refuses_before_the_design_gate(store):
    registry = json.loads((store / "registry.json").read_text())
    registry["features"][0]["status"] = "sliced"
    (store / "registry.json").write_text(json.dumps(registry))
    payload = run("gather", "--root", str(store), "--id", "F-001", expect_ok=False)
    assert any("fdw-design" in e for e in payload["errors"])


# ---------------------------------------------------------------- the vocabulary gate


@pytest.mark.parametrize("leak,expected", [
    ("We'll deliver F-003 next.", "feature id"),
    ("See A1 for the detail.", "internal reference id"),
    ("This satisfies FR-18.", "requirement id"),
    ("Run fdw-elaborate afterwards.", "internal tool name"),
    ("Scheduled for phase-2.1.", "internal phase label"),
    ("This is an XL effort.", "effort sizing"),
    ("We'll write the spec next.", "delivery jargon"),
    ("It goes in the backlog.", "delivery jargon"),
    ("Planned for the next sprint.", "delivery jargon"),
    ("We'll add user stories.", "delivery jargon"),
    ("It lands in the registry.", "internal artifact"),
    ("About five story points.", "estimation jargon"),
    ("This one is non-critical.", "internal triage vocabulary"),
    ("That behaviour is unconfirmed.", "internal assumption status"),
])
def test_internal_vocabulary_never_reaches_a_client(tmp_path, store, leak, expected):
    payload = run("render", "--root", str(store), "--id", "F-001",
                  "--content", content(tmp_path, intro=leak), expect_ok=False)
    joined = " ".join(payload["errors"])
    assert expected in joined
    assert "paying client" in joined


def test_the_gate_names_the_field_and_the_fix(tmp_path, store):
    payload = run("render", "--root", str(store), "--id", "F-001",
                  "--content", content(tmp_path, next_steps="We'll spec F-003 in the next sprint."),
                  expect_ok=False)
    joined = " ".join(payload["errors"])
    assert "next_steps" in joined, "the caller has to know which field to rewrite"
    assert "name the feature in words" in joined


def test_question_refs_are_exempt_because_they_are_never_rendered(tmp_path, store):
    out = run("render", "--root", str(store), "--id", "F-001", "--content", content(tmp_path))
    assert out["questions_asked"] == 1


def test_allow_jargon_is_available_for_an_internal_preview(tmp_path, store):
    out = run("render", "--root", str(store), "--id", "F-001",
              "--content", content(tmp_path, intro="Draft for F-003."), "--allow-jargon")
    assert out["jargon_allowed"] is True


def test_missing_required_sections_point_at_the_example(tmp_path, store):
    path = tmp_path / "thin.json"
    path.write_text(json.dumps({"headline": "Academy"}))
    payload = run("render", "--root", str(store), "--id", "F-001", "--content", str(path), expect_ok=False)
    assert "packet.example.json" in payload["errors"][0]


def test_the_shipped_example_passes_its_own_gate(tmp_path, store):
    example = json.loads(EXAMPLE.read_text())
    path = tmp_path / "example.json"
    path.write_text(json.dumps(example))
    out = run("render", "--root", str(store), "--id", "F-001", "--content", str(path))
    assert out["questions_asked"] == 2


# ---------------------------------------------------------------- rendering


def test_packet_is_self_contained_and_carries_no_ids(tmp_path, store):
    out = run("render", "--root", str(store), "--id", "F-001", "--content", content(tmp_path),
              "--client", "Acme", "--date", "2026-03-01")
    page = (store / out["packet"]).read_text()
    assert "F-001" not in page and "Q-01" not in page
    assert "Acme" in page and "2026-03-01" in page
    assert "prefers-color-scheme" in page and "width=device-width" in page
    for absent in ("http://", "https://", "<script"):
        assert absent not in page


def test_the_id_map_is_written_beside_the_packet_and_marked_internal(tmp_path, store):
    out = run("render", "--root", str(store), "--id", "F-001", "--content", content(tmp_path))
    mapping = json.loads((store / out["map"]).read_text())
    assert mapping["questions"] == [{"ref": "F-001-Q-01", "asked": "What should each tab contain?"}]
    assert "send the .html only" in out["send"]


def test_screenshots_are_embedded_so_the_page_travels(tmp_path, store):
    shot = tmp_path / "list.png"
    shot.write_bytes(PNG)
    out = run("render", "--root", str(store), "--id", "F-001", "--content", content(tmp_path),
              "--screenshot", f"Course list={shot}")
    assert out["screenshots"] == 1
    assert "data:image/png;base64," in (store / out["packet"]).read_text()


def test_client_text_is_html_escaped(tmp_path, store):
    out = run("render", "--root", str(store), "--id", "F-001",
              "--content", content(tmp_path, next_steps="Reply if <script>alert(1)</script> looks wrong."))
    page = (store / out["packet"]).read_text()
    assert "<script>alert(1)</script>" not in page
    assert "&lt;script&gt;" in page


def test_rendering_does_not_touch_feature_state(tmp_path, store):
    watched = [store / "registry.json",
               store / "phases/phase-1/features/F-001-academy/feature.json"]
    before = {p: p.read_bytes() for p in watched}
    run("render", "--root", str(store), "--id", "F-001", "--content", content(tmp_path))
    assert {p: p.read_bytes() for p in watched} == before, \
        "sign-off goes through the shared CLI; this script only produces the document"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))


def test_authoring_comments_are_not_linted_but_are_never_rendered(tmp_path, store):
    """_comment keys document the shape for whoever writes the packet; they never reach the page."""
    out = run("render", "--root", str(store), "--id", "F-001",
              "--content", content(tmp_path, _comment="Remember: F-001 is unconfirmed, sizing XL."))
    assert "F-001" not in (store / out["packet"]).read_text()
