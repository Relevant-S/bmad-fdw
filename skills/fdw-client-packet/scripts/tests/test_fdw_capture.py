#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["pytest"]
# ///
"""Tests for fdw_capture.py — what gets captured, in what order, and what happens when the
machine cannot capture at all."""

import importlib.util
import json
import struct
import subprocess
import sys
import urllib.request
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "fdw_capture.py"
spec = importlib.util.spec_from_file_location("fdw_capture", SCRIPT)
cap = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cap)


def run(*args, expect_ok=True):
    result = subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True)
    payload = json.loads(result.stdout)
    assert payload.get("ok") is (True if expect_ok else False), payload
    return payload


@pytest.fixture
def store(tmp_path):
    root = tmp_path / "discovery"
    design = root / "phases" / "phase-1" / "features" / "F-001-academy" / "design"
    (design / "prototype").mkdir(parents=True)
    (root / "registry.json").write_text(json.dumps({
        "current_phase": "phase-1", "phases": ["phase-1"],
        "features": [{"id": "F-001", "title": "Academy", "slug": "academy",
                      "phase": "phase-1", "status": "designing", "flags": []}]}))
    (design / "ux-notes.md").write_text(
        "## Screens\n\n- **S1 — Course list** — where a learner finds a course\n"
        "- **S2 — Course page** — tabs\n")
    for name, body in (("S1-course-list.html", "<section data-screen='S1'>list</section>"),
                       ("S2-course-page.html", "<section data-screen='S2'>page</section>")):
        (design / "prototype" / name).write_text(
            "<!doctype html><meta charset='utf-8'><style>body{margin:0;height:1400px}</style>" + body)
    (design / "grounding.json").write_text(json.dumps({
        "mode": "extracted", "prototype_dir": "prototype",
        "screens": [{"id": "S2", "kind": "new", "file": "prototype/S2-course-page.html"},
                    {"id": "S1", "kind": "as-is", "file": "prototype/S1-course-list.html"}]}))
    return root, design


def test_the_capture_list_is_the_declared_screens_in_order(store):
    """Not whatever files are in the folder — that is how a packet ends up showing another
    feature's screens. fdw-design has already gated this list."""
    root, design = store
    _, plan, problems = cap.screen_plan(design)
    assert [p["screen"] for p in plan] == ["S1", "S2"]
    assert [p["title"] for p in plan] == ["Course list", "Course page"]
    assert problems == []


def test_one_screen_per_file_is_captured_whole_so_a_borrowed_shell_survives(store):
    root, design = store
    _, plan, _ = cap.screen_plan(design)
    assert all(p["clip"] is None for p in plan)


def test_screens_sharing_a_file_are_clipped_to_their_own_region(store):
    root, design = store
    (design / "grounding.json").write_text(json.dumps({
        "mode": "extracted", "prototype_dir": "prototype",
        "screens": [{"id": "S1", "file": "prototype/S1-course-list.html"},
                    {"id": "S2", "file": "prototype/S1-course-list.html"}]}))
    _, plan, _ = cap.screen_plan(design)
    assert [p["clip"] for p in plan] == ['[data-screen="S1"]', '[data-screen="S2"]']


def test_a_declared_screen_with_no_file_is_reported_not_skipped_silently(store):
    root, design = store
    (design / "prototype" / "S2-course-page.html").unlink()
    _, plan, problems = cap.screen_plan(design)
    assert [p["screen"] for p in plan] == ["S1"]
    assert "S2" in problems[0]


def test_no_grounding_record_means_there_is_no_list_to_capture(store):
    root, design = store
    (design / "grounding.json").unlink()
    payload = run("shots", "--root", str(root), "--id", "F-001", expect_ok=False)
    assert payload["capture"] == "unavailable"
    assert "fdw-design" in " ".join(payload["errors"])


def test_an_unknown_feature_lists_what_exists(store):
    root, _ = store
    payload = run("shots", "--root", str(root), "--id", "F-404", expect_ok=False)
    assert "F-001" in payload["errors"][0]


def test_the_browser_search_is_reported_so_the_ba_can_point_at_one(monkeypatch):
    monkeypatch.setattr(cap, "BROWSER_CANDIDATES", ["/nowhere/chrome"])
    monkeypatch.setattr(cap, "ON_PATH", ["definitely-not-a-browser"])
    monkeypatch.delenv("CHROME_PATH", raising=False)
    binary, searched = cap.find_browser(None)
    assert binary is None
    assert "/nowhere/chrome" in searched


def test_an_explicit_browser_path_wins(tmp_path, monkeypatch):
    fake = tmp_path / "chrome"
    fake.write_text("")
    monkeypatch.setenv("CHROME_PATH", str(tmp_path / "other"))
    assert cap.find_browser(str(fake))[0] == str(fake)


def test_chrome_path_is_honoured_when_nothing_is_passed(tmp_path, monkeypatch):
    fake = tmp_path / "edge"
    fake.write_text("")
    monkeypatch.setenv("CHROME_PATH", str(fake))
    assert cap.find_browser(None)[0] == str(fake)


def test_the_prototype_is_served_over_loopback_not_file_urls(tmp_path):
    """file:// resolves relative assets differently, which is exactly the kind of difference
    that makes one BA's packet not match another's."""
    (tmp_path / "index.html").write_text("<p>hello</p>")
    httpd, base = cap.serve(tmp_path)
    try:
        assert base.startswith("http://127.0.0.1:")
        assert b"hello" in urllib.request.urlopen(f"{base}/index.html", timeout=5).read()
    finally:
        httpd.shutdown()


@pytest.mark.skipif(cap.find_browser(None)[0] is None, reason="no Chromium-family browser here")
def test_end_to_end_capture_produces_full_page_pngs_at_the_fixed_viewport(store):
    root, design = store
    out = run("shots", "--root", str(root), "--id", "F-001")
    assert out["capture"] == "complete"
    assert [s["screen"] for s in out["shots"]] == ["S1", "S2"]
    assert out["viewport"] == [1280, 900] and out["scale"] == 2
    header = Path(out["shots"][0]["file"]).read_bytes()[16:24]
    width, height = struct.unpack(">II", header)
    assert width == 2560, "1280 CSS pixels at a device scale factor of 2"
    assert height == 2800, "the page is 1400 tall, so capture must go beyond the viewport"
    assert json.loads(Path(out["manifest"]).read_text())["shots"][0]["title"] == "Course list"
