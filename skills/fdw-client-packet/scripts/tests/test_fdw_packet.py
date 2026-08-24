#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["pytest"]
# ///
"""Tests for fdw_packet.py — gathering, the vocabulary gate, and rendering the client packet."""

import base64
import importlib.util
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
    for absent in ("http://", "https://", "src="):
        assert absent not in page


def test_the_packet_never_phones_home(tmp_path, store):
    """It carries a reply form, so it carries script. A document going to a client must still
    reach nothing and submit nothing on its own — that is what makes it safe to open."""
    out = run("render", "--root", str(store), "--id", "F-001", "--content", content(tmp_path))
    page = (store / out["packet"]).read_text()
    for absent in ("fetch(", "XMLHttpRequest", "navigator.sendBeacon", "<form", "action=", "import("):
        assert absent not in page, f"{absent} would send the client's answers somewhere"
    assert "localStorage" in page, "a half-finished reply must survive a closed tab"


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


# ---------------------------------------------------------------- screenshots


def manifest(tmp_path, *shots):
    files = []
    for screen, title in shots:
        png = tmp_path / f"{screen}.png"
        png.write_bytes(PNG)
        files.append({"screen": screen, "title": title, "kind": "new", "file": str(png), "bytes": len(PNG)})
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps({"feature": "F-001", "shots": files}))
    return str(path)


def test_a_capture_manifest_attaches_images_by_the_client_facing_title(tmp_path, store):
    """The BA names sections in the client's language; the harness names files by screen id.
    Matching them by hand every time is the improvisation this replaces."""
    out = run("render", "--root", str(store), "--id", "F-001", "--content", content(tmp_path),
              "--shots", manifest(tmp_path, ("S1", "Course list")))
    assert out["screenshots"] == 1
    assert "data:image/png;base64," in (store / out["packet"]).read_text()


def test_a_manifest_naming_a_missing_file_fails_rather_than_rendering_a_gap(tmp_path, store):
    path = tmp_path / "m.json"
    path.write_text(json.dumps({"shots": [{"screen": "S1", "title": "Course list",
                                           "file": str(tmp_path / "gone.png")}]}))
    payload = run("render", "--root", str(store), "--id", "F-001", "--content", content(tmp_path),
                  "--shots", str(path), expect_ok=False)
    assert "gone.png" in " ".join(payload["errors"])


# ---------------------------------------------------------------- the reply block


def test_the_reply_block_labels_answers_with_opaque_tokens_only(tmp_path, store):
    out = run("render", "--root", str(store), "--id", "F-001", "--content", content(tmp_path))
    page = (store / out["packet"]).read_text()
    assert "data-token='q1'" in page and "data-token='a1'" in page
    assert "F-001-Q-01" not in page, "the reply must travel labelled q1, never with an internal id"
    mapping = json.loads((store / out["map"]).read_text())
    assert mapping["tokens"]["q1"]["ref"] == "F-001-Q-01"
    assert mapping["tokens"]["a1"]["kind"] == "assumption"


def test_reply_can_be_left_out_for_an_archive_copy(tmp_path, store):
    out = run("render", "--root", str(store), "--id", "F-001", "--content", content(tmp_path), "--no-reply")
    page = (store / out["packet"]).read_text()
    assert "data-token" not in page and "<script" not in page
    assert out["reply_enabled"] is False


# ---------------------------------------------------------------- responses in


def reply(tmp_path, name, packet, *, answers=None, approve="yes", other="", who=None, encoded=True):
    payload = {"v": 1, "packet": packet, "from": name, "at": "2026-03-02",
               "approve": approve, "other": other, "answers": answers or {}}
    body = json.dumps(payload)
    if encoded:
        body = "Thanks — here it is.\n\nFDW1:" + base64.b64encode(body.encode()).decode() + "\n\nBest, " + name
    path = tmp_path / f"reply-{who or name}.txt"
    path.write_text(body, encoding="utf-8")
    return str(path)


def rendered(tmp_path, store, **kw):
    return run("render", "--root", str(store), "--id", "F-001", "--content", content(tmp_path, **kw))


def test_a_single_reply_closes_the_question_and_approves(tmp_path, store):
    out = rendered(tmp_path, store)
    packet = Path(out["packet"]).name
    answer = reply(tmp_path, "Sasha", packet,
                   answers={"q1": {"text": "Overview and Sessions only."},
                            "a1": {"verdict": "agree"}})
    result = run("sync", "--root", str(store), "--id", "F-001", "--response", answer)
    assert result["answered"][0]["ref"] == "F-001-Q-01"
    assert result["answered"][0]["from"] == "Sasha"
    assert result["blocked_by"] == []
    assert any("question-close" in c and "F-001-Q-01" in c for c in result["run"])
    assert any("--status design-approved" in c for c in result["run"])


def test_the_clients_own_words_become_the_quote(tmp_path, store):
    out = rendered(tmp_path, store)
    answer = reply(tmp_path, "Sasha", Path(out["packet"]).name,
                   answers={"q1": {"text": "Overview and Sessions only."}})
    result = run("sync", "--root", str(store), "--id", "F-001", "--response", answer)
    assert '--quote "Overview and Sessions only."' in " ".join(result["run"])


def test_two_people_answering_differently_is_a_conflict_not_a_decision(tmp_path, store):
    """Picking one would invent a client decision. The whole module rests on not doing that."""
    out = rendered(tmp_path, store)
    packet = Path(out["packet"]).name
    a = reply(tmp_path, "Sasha", packet, answers={"q1": {"text": "Two tabs."}})
    b = reply(tmp_path, "Ines", packet, answers={"q1": {"text": "Three tabs, keep Certification."}})
    result = run("sync", "--root", str(store), "--id", "F-001", "--response", a, "--response", b)
    assert result["answered"] == []
    assert result["conflicts"][0]["answers"][0]["from"] in ("Sasha", "Ines")
    assert not any("question-close" in c for c in result["run"])
    assert any("disagree with each other" in b for b in result["blocked_by"])


def test_two_people_agreeing_still_closes_the_question(tmp_path, store):
    out = rendered(tmp_path, store)
    packet = Path(out["packet"]).name
    a = reply(tmp_path, "Sasha", packet, answers={"q1": {"text": "Two tabs."}})
    b = reply(tmp_path, "Ines", packet, answers={"q1": {"text": "Two tabs."}})
    result = run("sync", "--root", str(store), "--id", "F-001", "--response", a, "--response", b)
    assert len(result["answered"]) == 1


def test_a_disagreed_assumption_is_a_correction_for_the_designer(tmp_path, store):
    out = rendered(tmp_path, store)
    answer = reply(tmp_path, "Sasha", Path(out["packet"]).name,
                   answers={"q1": {"text": "Two tabs."},
                            "a1": {"verdict": "disagree", "text": "Publishing needs one session."}})
    result = run("sync", "--root", str(store), "--id", "F-001", "--response", answer)
    assert result["corrections"][0]["instead"] == ["Publishing needs one session."]
    assert "fdw-design" in result["then"]


def test_an_unanswered_question_blocks_sign_off(tmp_path, store):
    out = rendered(tmp_path, store)
    answer = reply(tmp_path, "Sasha", Path(out["packet"]).name, answers={"a1": {"verdict": "agree"}})
    result = run("sync", "--root", str(store), "--id", "F-001", "--response", answer)
    assert result["unanswered"] == ["What should each tab contain?"]
    assert not any("design-approved" in c for c in result["run"])


def test_silence_is_not_sign_off(tmp_path, store):
    out = rendered(tmp_path, store)
    answer = reply(tmp_path, "Sasha", Path(out["packet"]).name,
                   answers={"q1": {"text": "Two tabs."}}, approve="")
    result = run("sync", "--root", str(store), "--id", "F-001", "--response", answer)
    assert any("Silence is not sign-off" in b for b in result["blocked_by"])


def test_one_not_yet_holds_the_whole_feature(tmp_path, store):
    out = rendered(tmp_path, store)
    packet = Path(out["packet"]).name
    a = reply(tmp_path, "Sasha", packet, answers={"q1": {"text": "Two tabs."}}, approve="yes")
    b = reply(tmp_path, "Ines", packet, answers={}, approve="not-yet", who="ines")
    result = run("sync", "--root", str(store), "--id", "F-001", "--response", a, "--response", b)
    assert any("Ines" in x for x in result["blocked_by"])
    assert not any("design-approved" in c for c in result["run"])


def test_a_raw_json_reply_works_as_well_as_the_pasted_block(tmp_path, store):
    out = rendered(tmp_path, store)
    answer = reply(tmp_path, "Sasha", Path(out["packet"]).name,
                   answers={"q1": {"text": "Two tabs."}}, encoded=False)
    assert len(run("sync", "--root", str(store), "--id", "F-001", "--response", answer)["answered"]) == 1


def test_a_reply_to_a_different_packet_is_refused(tmp_path, store):
    rendered(tmp_path, store)
    answer = reply(tmp_path, "Sasha", "2020-01-01-something-else.html", answers={"q1": {"text": "x"}})
    payload = run("sync", "--root", str(store), "--id", "F-001", "--response", answer, expect_ok=False)
    assert "not" in " ".join(payload["errors"]).lower()


def test_replies_are_filed_so_every_quote_is_traceable(tmp_path, store):
    out = rendered(tmp_path, store)
    answer = reply(tmp_path, "Sasha", Path(out["packet"]).name, answers={"q1": {"text": "Two tabs."}})
    result = run("sync", "--root", str(store), "--id", "F-001", "--response", answer)
    filed = json.loads((store / result["recorded"]).read_text())
    assert filed["replies"][0]["from"] == "Sasha"
    run("sync", "--root", str(store), "--id", "F-001", "--response", answer)
    again = json.loads((store / result["recorded"]).read_text())
    assert len(again["replies"]) == 1, "re-syncing the same reply must not duplicate it"


def test_sync_writes_no_feature_state_itself(tmp_path, store):
    out = rendered(tmp_path, store)
    answer = reply(tmp_path, "Sasha", Path(out["packet"]).name, answers={"q1": {"text": "Two tabs."}})
    before = (store / "registry.json").read_text()
    run("sync", "--root", str(store), "--id", "F-001", "--response", answer)
    assert (store / "registry.json").read_text() == before


# ---------------------------------------------------------------- the loop, for real


def _browser():
    spec = importlib.util.spec_from_file_location(
        "fdw_capture", Path(__file__).resolve().parent.parent / "fdw_capture.py")
    cap = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cap)
    return cap, cap.find_browser(None)[0]


CAP, BROWSER = _browser()


@pytest.mark.skipif(BROWSER is None, reason="no Chromium-family browser here")
def test_the_reply_actually_runs_in_a_browser_and_syncs_back(tmp_path, store):
    """The reply is script running on someone else's machine at the far end of an email. A
    broken string literal there fails silently in front of the client and nothing upstream
    notices — so the loop is closed here against a real browser."""
    out = rendered(tmp_path, store)
    page = store / out["packet"]
    browser = CAP.Browser(BROWSER, 1, (1280, 900))
    try:
        ws = browser.ws
        ws.call("Page.navigate", {"url": page.resolve().as_uri()})
        ws.wait_for("Page.loadEventFired", 20)

        def js(expression):
            result = ws.call("Runtime.evaluate", {"expression": expression, "returnByValue": True})
            assert "exceptionDetails" not in result, result.get("exceptionDetails")
            return result["result"].get("value")

        assert js("typeof PACKET") == "string", "the reply script did not parse"
        js("""(function(){
          document.querySelector('[data-token="q1"][data-part="text"]').value='Two tabs only.';
          document.querySelector('[data-token="a1"][value="disagree"]').checked=true;
          document.querySelector('[data-token="a1"][data-part="text"]').value='It needs one session.';
          document.querySelector('[data-field="name"]').value='Sasha';
          document.querySelector('[data-field="approve"][value="yes"]').checked=true;
          document.getElementById('fdw-finish').click();
        })()""")
        blob = js("document.getElementById('fdw-blob').value")
        summary = js("document.getElementById('fdw-summary').textContent")
    finally:
        browser.kill()

    assert blob.startswith("FDW1:")
    assert "Sasha" in summary and "Two tabs only." in summary
    assert "F-001" not in blob and "F-001" not in summary

    reply_file = tmp_path / "from-client.txt"
    reply_file.write_text(f"Hi — see below.\n\n{blob}\n\nThanks, Sasha", encoding="utf-8")
    result = run("sync", "--root", str(store), "--id", "F-001", "--response", str(reply_file))
    assert result["answered"][0]["answer"] == "Two tabs only."
    assert result["corrections"][0]["instead"] == ["It needs one session."]
    assert any("--status design-approved" in c for c in result["run"])
