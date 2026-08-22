#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["pytest"]
# ///
"""Tests for the agent's sanctum scaffolding and waking.

init-sanctum.py and wake.py come from the agent-builder templates; these tests pin the
behaviour this agent depends on — that the sanctum builds complete, that the four capability
prompts are discovered, that a second run never overwrites a lived-in sanctum, and that
waking routes correctly on whether the sanctum exists.
"""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SKILL = Path(__file__).resolve().parents[2]
INIT = SKILL / "scripts" / "init-sanctum.py"
WAKE = SKILL / "scripts" / "wake.py"
SANCTUM_FILES = ["INDEX.md", "PERSONA.md", "CREED.md", "BOND.md", "MEMORY.md", "CAPABILITIES.md"]


def run(script, *args):
    return subprocess.run([sys.executable, str(script), *args], capture_output=True, text=True)


@pytest.fixture
def project(tmp_path):
    """A project with BMad config, and the skill copied in so paths resolve as installed."""
    root = tmp_path / "proj"
    (root / "_bmad").mkdir(parents=True)
    (root / "_bmad" / "config.yaml").write_text("user_name: Vadim\ncommunication_language: English\n")
    skill = root / "skills" / "fdw-agent-ba"
    shutil.copytree(SKILL, skill, ignore=shutil.ignore_patterns(".memlog.md", "__pycache__"))
    return root, skill


def sanctum_of(project_root):
    return project_root / "_bmad" / "memory" / "fdw-agent-ba"


# ---------------------------------------------------------------- scaffolding


def test_init_builds_every_sanctum_file(project):
    root, skill = project
    result = run(skill / "scripts" / "init-sanctum.py", str(root), str(skill))
    assert result.returncode == 0, result.stderr
    sanctum = sanctum_of(root)
    for name in SANCTUM_FILES:
        assert (sanctum / name).exists(), f"{name} missing from the sanctum"
    assert (sanctum / "sessions").is_dir()


def test_config_is_baked_into_the_bond(project):
    root, skill = project
    run(skill / "scripts" / "init-sanctum.py", str(root), str(skill))
    bond = (sanctum_of(root) / "BOND.md").read_text()
    assert "Vadim" in bond and "English" in bond
    assert "{user_name}" not in bond, "config tokens must be substituted, not left for the agent"


def test_the_seeded_files_carry_real_content_and_memory_starts_empty(project):
    root, skill = project
    run(skill / "scripts" / "init-sanctum.py", str(root), str(skill))
    sanctum = sanctum_of(root)
    persona = (sanctum / "PERSONA.md").read_text()
    creed = (sanctum / "CREED.md").read_text()
    assert "Open with state, never with a greeting" in persona
    assert "Read it, never guess it" in creed
    assert "Route, never gate" in creed
    memory = (sanctum / "MEMORY.md").read_text()
    assert "Empty at birth" in memory
    assert "##" not in memory.split("# Memory", 1)[1], "MEMORY ships guidance only; it fills at runtime"


def test_the_name_ships_rather_than_being_asked_for(project):
    root, skill = project
    run(skill / "scripts" / "init-sanctum.py", str(root), str(skill))
    persona = (sanctum_of(root) / "PERSONA.md").read_text()
    assert "**Name:** Vadim" in persona
    assert "awaiting First Breath" not in persona


def test_all_four_capabilities_are_discovered_and_registered(project):
    root, skill = project
    run(skill / "scripts" / "init-sanctum.py", str(root), str(skill))
    caps = (sanctum_of(root) / "CAPABILITIES.md").read_text()
    for code, name in [("OR", "Orient"), ("NA", "Next action"), ("QE", "Quick edit"), ("RT", "Route")]:
        assert f"[{code}]" in caps and name in caps, f"{name} was not registered"
    assert "first-breath" not in caps, "First Breath is not a capability"


def test_capability_prompts_reach_the_sanctum_so_it_stands_alone(project):
    root, skill = project
    run(skill / "scripts" / "init-sanctum.py", str(root), str(skill))
    refs = sanctum_of(root) / "references"
    for name in ("orient.md", "route.md", "next-action.md", "quick-edit.md"):
        assert (refs / name).exists(), f"{name} must live in the sanctum after init"
    assert not (refs / "first-breath.md").exists(), "First Breath stays in the skill bundle"


def test_a_second_run_never_overwrites_a_lived_in_sanctum(project):
    root, skill = project
    run(skill / "scripts" / "init-sanctum.py", str(root), str(skill))
    memory = sanctum_of(root) / "MEMORY.md"
    memory.write_text("# Memory\n\nHe wants specs written in his own words, not mine.\n")
    result = run(skill / "scripts" / "init-sanctum.py", str(root), str(skill))
    assert result.returncode == 0
    assert "already exists" in result.stdout
    assert "his own words" in memory.read_text(), "a rerun must never erase what the agent learned"


# ---------------------------------------------------------------- waking


def test_waking_without_a_sanctum_routes_to_first_breath(project):
    root, skill = project
    result = run(skill / "scripts" / "wake.py", str(root))
    assert result.returncode == 0, result.stderr
    assert "FIRST_BREATH" in result.stdout
    assert "first-breath.md" in result.stdout, "the mode must name the file to load"


def test_waking_with_a_sanctum_loads_the_whole_identity_in_one_pass(project):
    root, skill = project
    run(skill / "scripts" / "init-sanctum.py", str(root), str(skill))
    result = run(skill / "scripts" / "wake.py", str(root))
    assert result.returncode == 0, result.stderr
    out = result.stdout
    assert "Open with state, never with a greeting" in out, "PERSONA must be in the wake output"
    assert "Read it, never guess it" in out, "CREED must be in the wake output"
    assert "Vadim" in out
    assert "[OR]" in out and "[RT]" in out, "the capability registry wakes with it"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
