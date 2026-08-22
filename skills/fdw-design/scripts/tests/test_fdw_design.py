#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["pytest"]
# ///
"""Tests for fdw_design.py — component inventory, design scaffolding, and the client-readiness gate."""

import json
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "fdw_design.py"


def run(*args, expect_ok=True):
    result = subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True)
    payload = json.loads(result.stdout)
    if expect_ok:
        assert payload.get("ok") is True, payload
    else:
        assert payload.get("ok") is False, payload
        assert result.returncode == 1
    return payload


# ---------------------------------------------------------------- fixtures


@pytest.fixture
def project(tmp_path):
    root = tmp_path / "app"
    (root / "src" / "components").mkdir(parents=True)
    (root / "node_modules" / "junk").mkdir(parents=True)
    (root / "package.json").write_text(json.dumps({
        "dependencies": {"react": "^19", "next": "^15"},
        "devDependencies": {"tailwindcss": "^4", "typescript": "^5"},
    }))
    (root / "pnpm-lock.yaml").write_text("")
    comp = root / "src" / "components"
    (comp / "Button.tsx").write_text(
        "interface ButtonProps { label: string }\nexport default function Button(p: ButtonProps) { return null }\n")
    (comp / "Card.tsx").write_text("export const Card = () => null\nexport const CardHeader = () => null\n")
    (comp / "Table.tsx").write_text("function Table(){}\nfunction Row(){}\nexport { Table, Row as TableRow }\n")
    (comp / "Button.test.tsx").write_text("export const NotAComponent = () => null\n")
    (comp / "Card.stories.tsx").write_text("export const AlsoNot = () => null\n")
    (comp / "index.ts").write_text("export { Card } from './Card'\n")
    (root / "node_modules" / "junk" / "Vendor.tsx").write_text("export const Vendor = () => null\n")
    return root


@pytest.fixture
def store(tmp_path):
    root = tmp_path / "discovery"
    fdir = root / "phases" / "phase-1" / "features" / "F-001-academy"
    fdir.mkdir(parents=True)
    (root / "registry.json").write_text(json.dumps({
        "current_phase": "phase-1", "phases": ["phase-1"],
        "features": [{"id": "F-001", "title": "Academy", "slug": "academy",
                      "phase": "phase-1", "status": "designing", "flags": []}],
    }))
    (fdir / "feature.json").write_text(json.dumps({"id": "F-001", "title": "Academy", "status": "designing"}))
    return root


def complete_design(store, *, prototype=True, assumptions=True, corrections=True, walkthrough=True):
    """Bring a scaffolded feature up to whatever level of done the test needs."""
    run("scaffold", "--root", str(store), "--id", "F-001")
    design = store / "phases/phase-1/features/F-001-academy/design"
    if prototype:
        (design / "prototype" / "CoursePage.tsx").write_text("export default function CoursePage(){return null}\n")
    notes = design / "ux-notes.md"
    text = notes.read_text()
    if assumptions:
        text += "\n- **A1** (S1) — a course with no sessions is still publishable. _Status: unconfirmed_\n"
    if corrections:
        text += f"\n- {date.today().isoformat()} — S1 — date field took a single day → takes a range\n"
    notes.write_text(text)
    if walkthrough:
        (design / "empty-state.md").write_text(
            "# Academy — Empty-State Walkthrough\n\n## Narrative\n\n"
            "You open Academy with no courses. The page offers 'Create your first course'.\n\n"
            "## Gaps found\n\n- **G1** (S1) — no create-course entry point existed on the happy path.\n"
        )
    return design


# ---------------------------------------------------------------- inventory


def test_inventory_detects_stack_from_the_repo(project):
    out = run("inventory", "--project", str(project))
    assert out["stack"] == {
        "framework": "next", "styling": "tailwind", "typescript": True, "package_manager": "pnpm",
    }


def test_inventory_finds_components_across_export_styles(project):
    out = run("inventory", "--project", str(project))
    assert "Button" in out["components"]      # export default function
    assert "Card" in out["components"]        # export const
    assert "CardHeader" in out["components"]  # second export in one file
    assert "Table" in out["components"]       # export { ... }
    assert "TableRow" in out["components"]    # renamed in an export list


def test_inventory_skips_tests_stories_barrels_and_vendor_code(project):
    out = run("inventory", "--project", str(project))
    assert "NotAComponent" not in out["components"]
    assert "AlsoNot" not in out["components"]
    assert "Vendor" not in out["components"], "node_modules must never be inventoried"
    assert not any("index.ts" in f["file"] for f in out["files"])


def test_greenfield_project_is_recoverable_not_an_error(tmp_path):
    bare = tmp_path / "bare"
    bare.mkdir()
    payload = run("inventory", "--project", str(bare), expect_ok=False)
    assert payload["greenfield"] is True
    assert payload["recoverable"] is True
    assert "--path" in " ".join(payload["errors"])


def test_explicit_component_path_overrides_detection(tmp_path, project):
    other = project / "packages" / "design-system"
    other.mkdir(parents=True)
    (other / "Badge.tsx").write_text("export const Badge = () => null\n")
    out = run("inventory", "--project", str(project), "--path", str(other))
    assert out["components"] == ["Badge"]


# ---------------------------------------------------------------- scaffold


def test_untouched_scaffold_cannot_satisfy_the_gate(store):
    """A template that pre-fills its own checklist would wave through boilerplate."""
    run("scaffold", "--root", str(store), "--id", "F-001")
    payload = run("check", "--root", str(store), "--id", "F-001", expect_ok=False)
    joined = " ".join(payload["errors"])
    assert "records no assumptions" in joined
    assert "no dated corrections" in joined


def test_scaffold_creates_the_two_contract_artifacts(store):
    out = run("scaffold", "--root", str(store), "--id", "F-001")
    design = store / out["design_dir"]
    assert (design / "prototype").is_dir()
    assert (design / "ux-notes.md").exists()
    assert (design / "empty-state.md").exists()
    assert "Academy" in (design / "ux-notes.md").read_text()


def test_scaffold_never_overwrites_existing_notes(store):
    run("scaffold", "--root", str(store), "--id", "F-001")
    notes = store / "phases/phase-1/features/F-001-academy/design/ux-notes.md"
    notes.write_text("# hand-written work\n")
    out = run("scaffold", "--root", str(store), "--id", "F-001")
    assert out["already_present"] is True
    assert notes.read_text() == "# hand-written work\n"


def test_unknown_feature_lists_what_exists(store):
    payload = run("scaffold", "--root", str(store), "--id", "F-404", expect_ok=False)
    assert "F-001" in payload["errors"][0]


# ---------------------------------------------------------------- the readiness gate


def test_check_passes_on_a_complete_design_and_names_the_next_command(store):
    complete_design(store)
    out = run("check", "--root", str(store), "--id", "F-001")
    assert out["ready"] is True
    assert out["assumptions"] == ["A1"]
    assert out["gaps"] == ["G1"]
    assert any("client-review" in step for step in out["next"])


def test_empty_prototype_blocks_the_client(store):
    complete_design(store, prototype=False)
    payload = run("check", "--root", str(store), "--id", "F-001", expect_ok=False)
    assert any("signs off on screens" in e for e in payload["errors"])


def test_missing_assumptions_block_because_the_spec_needs_them(store):
    complete_design(store, assumptions=False)
    payload = run("check", "--root", str(store), "--id", "F-001", expect_ok=False)
    assert any("fdw-elaborate" in e for e in payload["errors"])


def test_a_design_nobody_corrected_is_not_reviewed(store):
    complete_design(store, corrections=False)
    payload = run("check", "--root", str(store), "--id", "F-001", expect_ok=False)
    assert any("has no dated corrections" in e for e in payload["errors"])


def test_a_stub_empty_state_walkthrough_blocks_and_says_why_it_matters(store):
    complete_design(store, walkthrough=False)
    payload = run("check", "--root", str(store), "--id", "F-001", expect_ok=False)
    joined = " ".join(payload["errors"])
    assert "still a stub" in joined
    assert "gaps surface" in joined, "the gate must explain why the pass exists, not just demand it"


def test_check_reports_every_problem_at_once(store):
    run("scaffold", "--root", str(store), "--id", "F-001")
    payload = run("check", "--root", str(store), "--id", "F-001", expect_ok=False)
    assert len(payload["errors"]) >= 2, "one round trip per missing artifact would be miserable"


def test_check_never_writes_to_the_store(store):
    complete_design(store)
    before = {p: p.read_bytes() for p in sorted(store.rglob("*")) if p.is_file()}
    run("check", "--root", str(store), "--id", "F-001")
    after = {p: p.read_bytes() for p in sorted(store.rglob("*")) if p.is_file()}
    assert before == after


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))


def test_next_command_walks_every_gate_from_where_the_feature_actually_is(tmp_path, store):
    """feature-set refuses a forward skip, so a single end-state command would just fail."""
    registry = json.loads((store / "registry.json").read_text())
    registry["features"][0]["status"] = "sliced"
    (store / "registry.json").write_text(json.dumps(registry))
    complete_design(store)
    steps = run("check", "--root", str(store), "--id", "F-001")["next"]
    assert len(steps) == 2
    assert "--status designing" in steps[0]
    assert "--status client-review" in steps[1]


def test_no_advance_suggested_when_already_past_client_review(store):
    registry = json.loads((store / "registry.json").read_text())
    registry["features"][0]["status"] = "design-approved"
    (store / "registry.json").write_text(json.dumps(registry))
    complete_design(store)
    assert run("check", "--root", str(store), "--id", "F-001")["next"] == []
