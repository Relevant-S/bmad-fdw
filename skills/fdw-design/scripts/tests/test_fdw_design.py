#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["pytest"]
# ///
"""Tests for fdw_design.py — the discovery ladder, design scaffolding, grounding verification,
the one-feature boundary, and the client-readiness gate."""

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


PAGE_SRC = """import { Button, Card } from '@acme/ui'

export default function CourseListPage() {
  const rows = useCourses()
  if (rows.length === 0) return <EmptyState className="p-12 text-center text-muted" />
  return (
    <div className="flex flex-col gap-4 p-6 bg-page">
      <h1 className="text-2xl font-semibold text-foreground">Courses</h1>
      <table className="w-full border rounded-md">
        <tbody className="divide-y">
          {rows.map(r => (
            <tr className="hover:bg-muted"><td className="px-3 py-2">{r.name}</td></tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
"""

CLONED = """<section data-screen="S1" class="flex flex-col gap-4 p-6 bg-page">
  <h1 class="text-2xl font-semibold text-foreground">Courses</h1>
  <table class="w-full border rounded-md">
    <tbody class="divide-y"><tr class="hover:bg-muted"><td class="px-3 py-2">Intro</td></tr></tbody>
  </table>
</section>
"""

REIMPLEMENTED = """<section data-screen="S1" class="wrap stack pad surface">
  <h1 class="h1 heading">Courses</h1>
  <table class="grid lines"><tbody class="rows"><tr class="row"><td class="cell">Intro</td></tr></tbody></table>
</section>
"""


@pytest.fixture
def project(tmp_path):
    root = tmp_path / "app"
    (root / "src" / "components").mkdir(parents=True)
    (root / "node_modules" / "junk").mkdir(parents=True)
    (root / "package.json").write_text(json.dumps({
        "dependencies": {"react": "^19", "next": "^15"},
        "devDependencies": {"tailwindcss": "^4", "typescript": "^5"},
        "scripts": {"dev": "next dev"},
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
    (root / "src" / "styles").mkdir(parents=True)
    (root / "src" / "styles" / "theme.css").write_text(
        ":root{" + "".join(f"--colour-{i}:#0000{i}{i};" for i in range(10)) + "}\n")
    (root / "src" / "pages").mkdir(parents=True)
    (root / "src" / "pages" / "CourseListPage.tsx").write_text(PAGE_SRC)
    (root / "src" / "layout").mkdir(parents=True)
    (root / "src" / "layout" / "AppShell.tsx").write_text(
        'export const AppShell = () => <nav className="flex gap-2 p-4">nav</nav>\n')
    return root


@pytest.fixture
def store(tmp_path):
    root = tmp_path / "discovery"
    fdir = root / "phases" / "phase-1" / "features" / "F-001-academy"
    fdir.mkdir(parents=True)
    (root / "registry.json").write_text(json.dumps({
        "current_phase": "phase-1", "phases": ["phase-1"],
        "features": [
            {"id": "F-001", "title": "Academy", "slug": "academy",
             "phase": "phase-1", "status": "designing", "flags": []},
            {"id": "F-002", "title": "Events feedback", "slug": "events-feedback",
             "phase": "phase-1", "status": "sliced", "flags": []},
        ],
    }))
    (fdir / "feature.json").write_text(json.dumps({"id": "F-001", "title": "Academy", "status": "designing"}))
    return root


def write_grounding(design, project, **overrides):
    """A grounding record that holds up, so a test can break exactly one thing about it."""
    payload = {
        "mode": "extracted",
        "app_root": str(project),
        "component_root": "src/components",
        "prototype_dir": "prototype",
        "tokens": [{"source": "src/styles/theme.css", "copied_to": "prototype/tokens.css"}],
        "reference_pages": ["src/pages/CourseListPage.tsx"],
        "chrome": {"origin": "borrowed", "source": "src/layout/AppShell.tsx"},
        "screens": [{"id": "S1", "kind": "as-is", "file": "prototype/S1-course-list.html",
                     "source": "src/pages/CourseListPage.tsx"}],
        "comparison": [{"screen": "S1", "reference": "src/pages/CourseListPage.tsx",
                        "verdict": "matches", "differences": "none"}],
    }
    payload.update(overrides)
    (design / "grounding.json").write_text(json.dumps(payload, indent=2))
    return payload


def complete_design(store, project, *, prototype=True, assumptions=True, corrections=True,
                    walkthrough=True, screen_markup=CLONED, grounding=True, **grounding_overrides):
    """Bring a scaffolded feature up to whatever level of done the test needs."""
    run("scaffold", "--root", str(store), "--id", "F-001")
    design = store / "phases/phase-1/features/F-001-academy/design"
    if prototype:
        (design / "prototype" / "S1-course-list.html").write_text(screen_markup)
        (design / "prototype" / "tokens.css").write_bytes(
            (project / "src" / "styles" / "theme.css").read_bytes())
    notes = design / "ux-notes.md"
    text = notes.read_text()
    text += "\n- **S1 — Course list** *(as-is)* — where a learner finds a course\n"
    if assumptions:
        text += "\n- **A1** (S1) — a course with no sessions is still publishable. _Status: unconfirmed_\n"
    if corrections:
        text += f"\n- {date.today().isoformat()} — S1 — date field took a single day → takes a range\n"
    notes.write_text(text)
    if walkthrough:
        (design / "empty-state.md").write_text(
            "# Academy — Empty-State Walkthrough\n\n## Narrative\n\n"
            "You open Academy with no courses. The page offers 'Create your first course'.\n\n"
            "## Gaps found\n\n- **G1** (S1) — no create-course entry point existed on the happy path.\n")
    if grounding:
        write_grounding(design, project, **grounding_overrides)
    return design


# ---------------------------------------------------------------- the discovery ladder


def test_inventory_detects_stack_from_the_repo(project):
    out = run("inventory", "--project", str(project))
    assert out["stack"]["framework"] == "next"
    assert out["stack"]["styling"] == "tailwind"
    assert out["stack"]["typescript"] is True
    assert out["stack"]["package_manager"] == "pnpm"


def test_stack_detection_reads_workspace_packages_not_only_the_root(tmp_path):
    """A workspace root declares no dependencies of its own. Reading only the top manifest is how
    a React monorepo gets reported as having no framework and no styling system."""
    root = tmp_path / "mono"
    (root / "packages" / "ui" / "src").mkdir(parents=True)
    (root / "package.json").write_text(json.dumps({"private": True, "workspaces": ["packages/*"]}))
    (root / "pnpm-lock.yaml").write_text("")
    (root / "packages" / "ui" / "package.json").write_text(json.dumps({
        "dependencies": {"react": "^19"}, "devDependencies": {"tailwindcss": "^4"},
        "scripts": {"dev": "vite"}}))
    (root / "packages" / "ui" / "src" / "Button.tsx").write_text("export const Button = () => null\n")
    out = run("inventory", "--project", str(root), "--path", str(root / "packages" / "ui" / "src"))
    assert out["stack"]["framework"] == "react"
    assert out["stack"]["styling"] == "tailwind"
    assert {"dir": "packages/ui", "command": "pnpm run dev"} in out["stack"]["run_commands"]


def test_inventory_widens_past_the_project_root_to_a_sibling(tmp_path, project):
    """BMad is routinely installed in a docs directory with the application beside it. A search
    that stops at the project root reports a shipping product as having no components."""
    docs = tmp_path / "docs"
    docs.mkdir()
    out = run("inventory", "--project", str(docs))
    assert out["verdict"] == "found"
    assert out["app_root"] == str(project)
    assert out["component_root"] == "src/components"
    assert "Button" in out["components"]


def test_a_failed_search_is_not_a_greenfield_verdict(tmp_path):
    """The original bug: 'I could not find it' and 'it does not exist' rendered identically, so a
    brownfield project got drawn from scratch."""
    bare = tmp_path / "bare"
    bare.mkdir()
    payload = run("inventory", "--project", str(bare), expect_ok=False)
    assert payload["verdict"] == "not_found"
    assert payload.get("greenfield") is None, "a failed search must never assert greenfield"
    assert payload["recoverable"] is True
    joined = " ".join(payload["errors"]).lower()
    assert "component_library_path" in joined and "ask the ba" in joined
    assert payload["searched"], "say where it looked, so the BA can point somewhere better"


def test_inventory_surfaces_the_token_file_and_a_reference_page(project):
    out = run("inventory", "--project", str(project))
    assert out["tokens"][0]["file"] == "src/styles/theme.css"
    pages = {p["file"]: p for p in out["reference_pages"]}
    assert "src/pages/CourseListPage.tsx" in pages
    assert "list" in pages["src/pages/CourseListPage.tsx"]["archetypes"]


def test_inventory_skips_tests_stories_barrels_and_vendor_code(project):
    out = run("inventory", "--project", str(project))
    assert "NotAComponent" not in out["components"]
    assert "AlsoNot" not in out["components"]
    assert "Vendor" not in out["components"], "node_modules must never be inventoried"
    assert not any("index.ts" in f["file"] for f in out["files"])


def test_config_supplied_component_path_wins_over_detection(tmp_path, project):
    other = project / "packages" / "design-system"
    other.mkdir(parents=True)
    (other / "Badge.tsx").write_text("export const Badge = () => null\n")
    out = run("inventory", "--project", str(project), "--path", str(other))
    assert out["components"] == ["Badge"]


def test_a_config_path_that_does_not_exist_says_so_rather_than_falling_back(tmp_path, project):
    payload = run("inventory", "--project", str(project), "--path", str(tmp_path / "nowhere"), expect_ok=False)
    assert "component_library_path" in " ".join(payload["errors"])


# ---------------------------------------------------------------- scaffold


def test_untouched_scaffold_cannot_satisfy_the_gate(store):
    """A template that pre-fills its own checklist would wave through boilerplate."""
    run("scaffold", "--root", str(store), "--id", "F-001")
    payload = run("check", "--root", str(store), "--id", "F-001", expect_ok=False)
    assert any("assumptions" in p for p in payload["problems"])
    assert any("corrections" in p for p in payload["problems"])
    assert any("empty-state" in p or "walkthrough" in p for p in payload["problems"])


def test_scaffold_creates_the_contract_artifacts(store):
    out = run("scaffold", "--root", str(store), "--id", "F-001")
    design = store / out["design_dir"]
    assert (design / "ux-notes.md").exists()
    assert (design / "empty-state.md").exists()
    assert (design / "grounding.json").exists()
    assert (design / "prototype").is_dir()


def test_scaffold_names_the_other_features_as_the_boundary(store):
    """Scope creep starts with not knowing where the edge is. The registry already knows."""
    out = run("scaffold", "--root", str(store), "--id", "F-001")
    assert out["out_of_scope"] == ["F-002"]
    notes = (store / out["design_dir"] / "ux-notes.md").read_text()
    assert "F-001 only" in notes
    assert "F-002 — Events feedback" in notes


def test_scaffold_honours_a_prototype_path_outside_the_design_folder(tmp_path, store):
    target = tmp_path / "prototypes" / "F-001"
    out = run("scaffold", "--root", str(store), "--id", "F-001", "--prototype-path", str(target))
    assert target.is_dir()
    assert out["prototype_dir"] == str(target)


def test_scaffold_never_overwrites_existing_notes(store):
    run("scaffold", "--root", str(store), "--id", "F-001")
    notes = store / "phases/phase-1/features/F-001-academy/design/ux-notes.md"
    notes.write_text("hand-written\n")
    out = run("scaffold", "--root", str(store), "--id", "F-001")
    assert notes.read_text() == "hand-written\n"
    assert out["already_present"] is True


def test_unknown_feature_lists_what_exists(store):
    payload = run("scaffold", "--root", str(store), "--id", "F-404", expect_ok=False)
    assert "F-001" in payload["errors"][0]


# ---------------------------------------------------------------- grounding


def test_a_grounded_prototype_passes(store, project):
    complete_design(store, project)
    out = run("fidelity", "--root", str(store), "--id", "F-001")
    assert out["grounded"] is True
    assert out["class_overlap"]["S1"] > 0.8


def test_a_prototype_with_no_grounding_record_cannot_be_checked(store, project):
    design = complete_design(store, project, grounding=False)
    (design / "grounding.json").unlink()
    payload = run("fidelity", "--root", str(store), "--id", "F-001", expect_ok=False)
    assert "grounding.json" in payload["problems"][0]


def test_greenfield_needs_a_person_to_have_said_so(store, project):
    complete_design(store, project, mode="greenfield")
    payload = run("fidelity", "--root", str(store), "--id", "F-001", expect_ok=False)
    assert "greenfield_confirmed_by" in " ".join(payload["problems"])
    complete_design(store, project, mode="greenfield", greenfield_confirmed_by="Vadim, on the call")
    assert run("fidelity", "--root", str(store), "--id", "F-001")["grounded"] is True


def test_a_cited_source_that_does_not_exist_fails(store, project):
    complete_design(store, project, screens=[
        {"id": "S1", "kind": "new", "file": "prototype/S1-course-list.html",
         "source": "src/pages/ImaginaryPage.tsx"}])
    payload = run("fidelity", "--root", str(store), "--id", "F-001", expect_ok=False)
    assert "ImaginaryPage" in " ".join(payload["problems"])


def test_a_screen_that_cites_nothing_fails(store, project):
    complete_design(store, project, screens=[
        {"id": "S1", "kind": "new", "file": "prototype/S1-course-list.html"}])
    payload = run("fidelity", "--root", str(store), "--id", "F-001", expect_ok=False)
    assert "cites no source" in " ".join(payload["problems"])


def test_a_retyped_token_file_fails_even_when_the_values_are_right(store, project):
    """The trap failure: correct palette, wrong everything else. Bytes, not values."""
    design = complete_design(store, project)
    original = (project / "src" / "styles" / "theme.css").read_text()
    (design / "prototype" / "tokens.css").write_text(original.replace(";", "; "))
    payload = run("fidelity", "--root", str(store), "--id", "F-001", expect_ok=False)
    assert "byte-identical" in " ".join(payload["problems"])


def test_a_reimplementation_fails_the_vocabulary_check(store, project):
    """Same feature, same tokens, rewritten from memory. This is what the screenshots showed."""
    complete_design(store, project, screen_markup=REIMPLEMENTED)
    payload = run("fidelity", "--root", str(store), "--id", "F-001", expect_ok=False)
    joined = " ".join(payload["problems"])
    assert "styling vocabulary" in joined and "reimplementation" in joined


def test_a_hand_authored_stylesheet_is_flagged_when_the_project_has_one(store, project):
    design = complete_design(store, project)
    (design / "prototype" / "S1-course-list.html").write_text(
        CLONED + "<style>" + "".join(f".x{i}{{color:#0{i}0}}" for i in range(40)) + "</style>")
    payload = run("fidelity", "--root", str(store), "--id", "F-001", expect_ok=False)
    assert "styling system" in " ".join(payload["problems"])


def test_an_as_is_screen_needs_a_recorded_comparison(store, project):
    complete_design(store, project, comparison=[])
    payload = run("fidelity", "--root", str(store), "--id", "F-001", expect_ok=False)
    assert "side-by-side" in " ".join(payload["problems"])


def test_app_root_may_be_relative_to_the_store(store, project):
    complete_design(store, project, app_root="../app")
    assert run("fidelity", "--root", str(store), "--id", "F-001")["grounded"] is True


# ---------------------------------------------------------------- the one-feature boundary


def test_a_screen_nobody_declared_is_a_boundary_violation(store, project):
    """Its job was one feature; it generated an application."""
    design = complete_design(store, project)
    (design / "prototype" / "S7-payments-dashboard.html").write_text('<div data-screen="S7">payments</div>')
    payload = run("fidelity", "--root", str(store), "--id", "F-001", expect_ok=False)
    joined = " ".join(payload["problems"])
    assert "S7" in joined and "boundary" in joined


def test_a_declared_screen_that_was_never_drawn_fails(store, project):
    complete_design(store, project, screens=[
        {"id": "S1", "kind": "as-is", "file": "prototype/S1-course-list.html",
         "source": "src/pages/CourseListPage.tsx"},
        {"id": "S4", "kind": "new", "file": "prototype/S4-missing.html",
         "source": "src/pages/CourseListPage.tsx"}])
    payload = run("fidelity", "--root", str(store), "--id", "F-001", expect_ok=False)
    assert "S4" in " ".join(payload["problems"])


def test_invented_chrome_has_no_source_to_cite(store, project):
    """A nav bar needs entries, entries imply pages, and now other features are in the review."""
    complete_design(store, project, chrome={"origin": "designed", "source": ""})
    payload = run("fidelity", "--root", str(store), "--id", "F-001", expect_ok=False)
    assert "chrome.origin" in " ".join(payload["problems"])


def test_borrowed_chrome_must_name_a_file_that_exists(store, project):
    complete_design(store, project, chrome={"origin": "borrowed", "source": "src/layout/Nope.tsx"})
    payload = run("fidelity", "--root", str(store), "--id", "F-001", expect_ok=False)
    assert "Nope.tsx" in " ".join(payload["problems"])


def test_no_chrome_at_all_is_a_valid_answer(store, project):
    complete_design(store, project, chrome={"origin": "none", "source": ""})
    assert run("fidelity", "--root", str(store), "--id", "F-001")["grounded"] is True


# ---------------------------------------------------------------- the readiness gate


def test_check_passes_on_a_complete_design_and_names_the_next_command(store, project):
    complete_design(store, project)
    out = run("check", "--root", str(store), "--id", "F-001")
    assert out["ready"] is True
    assert out["assumptions"] == ["A1"] and out["gaps"] == ["G1"]
    assert any("--status client-review" in c for c in out["next"])


def test_check_refuses_a_design_that_looks_finished_but_is_not_grounded(store, project):
    """Every legacy gate passes here; only the grounding check catches it."""
    complete_design(store, project, screen_markup=REIMPLEMENTED)
    payload = run("check", "--root", str(store), "--id", "F-001", expect_ok=False)
    assert payload["ready"] is False
    assert any("styling vocabulary" in p for p in payload["problems"])


def test_empty_prototype_blocks_the_client(store, project):
    complete_design(store, project, prototype=False)
    payload = run("check", "--root", str(store), "--id", "F-001", expect_ok=False)
    assert any("empty" in p for p in payload["problems"])


def test_missing_assumptions_block_because_the_spec_needs_them(store, project):
    complete_design(store, project, assumptions=False)
    payload = run("check", "--root", str(store), "--id", "F-001", expect_ok=False)
    assert any("assumptions" in p for p in payload["problems"])


def test_a_design_nobody_corrected_is_not_reviewed(store, project):
    complete_design(store, project, corrections=False)
    payload = run("check", "--root", str(store), "--id", "F-001", expect_ok=False)
    assert any("corrections" in p for p in payload["problems"])


def test_a_stub_empty_state_walkthrough_blocks_and_says_why_it_matters(store, project):
    complete_design(store, project, walkthrough=False)
    payload = run("check", "--root", str(store), "--id", "F-001", expect_ok=False)
    assert any("cold start" in p for p in payload["problems"])


def test_check_reports_every_problem_at_once(store, project):
    complete_design(store, project, prototype=False, assumptions=False, walkthrough=False)
    payload = run("check", "--root", str(store), "--id", "F-001", expect_ok=False)
    assert len(payload["problems"]) >= 3


def test_check_never_writes_to_the_store(store, project):
    complete_design(store, project)
    before = {p: p.stat().st_mtime_ns for p in store.rglob("*") if p.is_file()}
    run("check", "--root", str(store), "--id", "F-001")
    after = {p: p.stat().st_mtime_ns for p in store.rglob("*") if p.is_file()}
    assert before == after


def test_next_command_walks_every_gate_from_where_the_feature_actually_is(tmp_path, store, project):
    registry = json.loads((store / "registry.json").read_text())
    registry["features"][0]["status"] = "candidate"
    (store / "registry.json").write_text(json.dumps(registry))
    complete_design(store, project)
    out = run("check", "--root", str(store), "--id", "F-001")
    assert [c.split("--status ")[1].split()[0] for c in out["next"]] == ["sliced", "designing", "client-review"]


def test_no_advance_suggested_when_already_past_client_review(store, project):
    registry = json.loads((store / "registry.json").read_text())
    registry["features"][0]["status"] = "design-approved"
    (store / "registry.json").write_text(json.dumps(registry))
    complete_design(store, project)
    assert run("check", "--root", str(store), "--id", "F-001")["next"] == []


def test_css_modules_are_not_scored_as_invention(store, project):
    """styles.row names nothing another file could reuse. Scoring it would fail honest work on
    any project that does not use utility classes."""
    (project / "src" / "pages" / "ModulePage.tsx").write_text(
        "export default function P(){return (<div className={styles.wrap}>" +
        "".join(f"<span className={{styles.s{i}}}>x</span>" for i in range(12)) + "</div>)}\n")
    complete_design(store, project, screen_markup=REIMPLEMENTED, screens=[
        {"id": "S1", "kind": "new", "file": "prototype/S1-course-list.html",
         "source": "src/pages/ModulePage.tsx"}], comparison=[])
    out = run("fidelity", "--root", str(store), "--id", "F-001")
    assert out["class_overlap"]["S1"] is None, "unmeasurable must read as unmeasured, not as passing"
