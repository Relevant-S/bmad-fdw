#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Deterministic support for fdw-design: component inventory, design-folder scaffolding,
and the readiness gate before a feature goes to the client.

Judgment — what to draw, where the gaps are, whether a correction is right — stays in the
prompt. This script only finds things, creates skeletons, and checks that what the next
skill needs actually exists.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import date
from pathlib import Path
from typing import Any

CODE_EXT = {".tsx": "react", ".jsx": "react", ".vue": "vue", ".svelte": "svelte", ".ts": "react", ".js": "react"}
SKIP_DIR = {"node_modules", ".git", "dist", "build", ".next", "coverage", "__pycache__", ".venv", "storybook-static"}
SKIP_FILE = re.compile(r"\.(test|spec|stories|d)\.[jt]sx?$|^index\.[jt]sx?$")

EXPORT_PATTERNS = [
    re.compile(r"export\s+default\s+function\s+([A-Z][A-Za-z0-9_]*)"),
    re.compile(r"export\s+function\s+([A-Z][A-Za-z0-9_]*)"),
    re.compile(r"export\s+const\s+([A-Z][A-Za-z0-9_]*)\s*[:=]"),
    re.compile(r"export\s+class\s+([A-Z][A-Za-z0-9_]*)"),
    re.compile(r"export\s*\{([^}]*)\}"),
]
PROPS_RE = re.compile(r"(?:interface|type)\s+([A-Z][A-Za-z0-9_]*Props)\b")


def emit(payload: dict[str, Any]) -> None:
    payload.setdefault("ok", True)
    print(json.dumps(payload, indent=2, ensure_ascii=False))


def die(errors: list[str], **extra: Any) -> None:
    print(json.dumps({"ok": False, "errors": errors, **extra}, indent=2, ensure_ascii=False))
    sys.exit(1)


def read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return default


# ---------------------------------------------------------------- component inventory


def detect_stack(project: Path) -> dict[str, Any]:
    pkg = read_json(project / "package.json", {}) or {}
    deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
    if "next" in deps:
        framework = "next"
    elif "react" in deps:
        framework = "react"
    elif "vue" in deps:
        framework = "vue"
    elif "svelte" in deps:
        framework = "svelte"
    else:
        framework = None
    styling = None
    if "tailwindcss" in deps:
        styling = "tailwind"
    elif any(k.startswith("@mui/") for k in deps):
        styling = "mui"
    elif "styled-components" in deps:
        styling = "styled-components"
    return {
        "framework": framework,
        "styling": styling,
        "typescript": "typescript" in deps or (project / "tsconfig.json").exists(),
        "package_manager": "pnpm" if (project / "pnpm-lock.yaml").exists()
        else "yarn" if (project / "yarn.lock").exists()
        else "npm" if (project / "package-lock.json").exists()
        else None,
    }


def guess_component_root(project: Path) -> Path | None:
    candidates = [
        "src/components", "app/components", "components", "src/ui", "src/lib/components",
        "packages/ui/src", "src/shared/components",
    ]
    for rel in candidates:
        path = project / rel
        if path.is_dir():
            return path
    return None


def walk_code(root: Path):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIR and not d.startswith(".")]
        for name in filenames:
            if Path(name).suffix.lower() in CODE_EXT and not SKIP_FILE.search(name):
                yield Path(dirpath) / name


def exported_names(text: str) -> list[str]:
    found: list[str] = []
    for pattern in EXPORT_PATTERNS[:-1]:
        found.extend(pattern.findall(text))
    for group in EXPORT_PATTERNS[-1].findall(text):
        for part in group.split(","):
            name = part.split(" as ")[-1].strip()
            if re.fullmatch(r"[A-Z][A-Za-z0-9_]*", name):
                found.append(name)
    seen, out = set(), []
    for name in found:
        if name not in seen:
            seen.add(name)
            out.append(name)
    return out


def cmd_inventory(args: argparse.Namespace) -> None:
    project = Path(args.project).resolve()
    if not project.is_dir():
        die([f"No project directory at {project}."])
    stack = detect_stack(project)

    root = Path(args.path).resolve() if args.path else guess_component_root(project)
    if root is None or not root.is_dir():
        die(
            [
                f"No component library found under {project}. Looked for src/components, "
                f"app/components, components, src/ui and similar.",
                "Fix: pass --path <dir>, or if this project genuinely has no component library, "
                "say so — the prototype then establishes one instead of reusing.",
            ],
            recoverable=True,
            stack=stack,
            greenfield=True,
        )

    components: list[dict[str, Any]] = []
    for file in sorted(walk_code(root)):
        try:
            text = file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        names = exported_names(text) or ([file.stem] if file.suffix == ".vue" or file.suffix == ".svelte" else [])
        if not names:
            continue
        props = PROPS_RE.findall(text)
        components.append(
            {
                "file": str(file.relative_to(project)),
                "exports": names,
                "props_types": props,
                "kind": CODE_EXT.get(file.suffix.lower(), "unknown"),
                "lines": text.count("\n") + 1,
            }
        )

    every = sorted({name for c in components for name in c["exports"]})
    emit(
        {
            "project": str(project),
            "component_root": str(root.relative_to(project)),
            "stack": stack,
            "component_count": len(every),
            "file_count": len(components),
            "components": every,
            "files": components if args.verbose else components[:60],
            "truncated": (not args.verbose) and len(components) > 60,
            "greenfield": False,
        }
    )


# ---------------------------------------------------------------- design folder


UX_NOTES = """# {title} — UX Notes

Behaviour agreed through the prototype. **This file is the primary input to `fdw-elaborate`** —
the prototype itself is disposable, these notes are not. Write so someone who never saw the
screens can still write the spec.

## Screens

<!-- One line per screen. Ids S1, S2 … are referenced by assumptions, corrections and gaps.
     Shape:  - **S1 — Course list** — where a learner finds a course
     Mark reproduced screens as-is; a description of existing behaviour is context, not a requirement. -->

## Assumptions

<!-- Every claim the prototype makes that nobody has confirmed. fdw-elaborate turns each
     unresolved one into an open question, so phrase them so they can be answered yes or no.
     Shape:  - **A1** (S1) — a course with no sessions is still publishable. _Status: unconfirmed_ -->

## Corrections

<!-- Append-only. What the BA changed and why. This is where the real requirements surface —
     a correction is a requirement nobody had written down yet.
     Shape:  - {today} — S1 — date field took a single day → takes a range -->

## Components

- **reused:** —
- **built:** —

<!-- A component built here belongs in the project's library, not inlined in one screen. -->
"""

EMPTY_STATE = """# {title} — Empty-State Walkthrough

Cold start: nothing exists yet, no data, no history. Narrate how the first one comes into
being, screen by screen. This pass exists because the happy path hides the gaps — walking the
empty case is what surfaces the steps nobody specified.

## Narrative

<!-- You have just opened this for the first time. What do you see? What do you do first?
     Where does the very first record come from? Keep going until something exists. -->

_Not written yet._

## Gaps found

<!-- Ids G1, G2 … Each gap is something the happy-path prototype did not account for,
     and what changed as a result. If this section is empty, the walkthrough was not done. -->

_Not written yet._
"""


def feature_dir(root: Path, feature_id: str) -> tuple[Path, dict[str, Any]]:
    registry = read_json(root / "registry.json")
    if registry is None:
        die([f"No discovery store at {root}. Run fdw-intake first."])
    entry = next((f for f in registry.get("features", []) if f["id"] == feature_id), None)
    if entry is None:
        die([f"No feature '{feature_id}'. Known: {[f['id'] for f in registry.get('features', [])]}"])
    return root / "phases" / entry["phase"] / "features" / f"{entry['id']}-{entry['slug']}", entry


def cmd_scaffold(args: argparse.Namespace) -> None:
    root = Path(args.root).resolve()
    fdir, entry = feature_dir(root, args.id)
    design = fdir / "design"
    (design / "prototype").mkdir(parents=True, exist_ok=True)
    created = []
    fields = {"title": entry["title"], "today": date.today().isoformat()}
    for name, template in (("ux-notes.md", UX_NOTES), ("empty-state.md", EMPTY_STATE)):
        target = design / name
        if not target.exists():
            target.write_text(template.format(**fields), encoding="utf-8")
            created.append(str(target.relative_to(root)))
    emit(
        {
            "feature": entry["id"],
            "title": entry["title"],
            "design_dir": str(design.relative_to(root)),
            "prototype_dir": str((design / "prototype").relative_to(root)),
            "created": created,
            "already_present": not created,
        }
    )


# ---------------------------------------------------------------- readiness gate


LIFECYCLE = [
    "candidate", "sliced", "designing", "client-review", "design-approved",
    "speccing", "spec-approved", "handed-off", "shipped",
]


def advance_commands(root: Path, entry: dict[str, Any]) -> list[str]:
    """The actual command sequence from where the feature is to client-review. feature-set
    refuses a forward move that skips a gate, so suggesting the single end-state command
    would hand the caller something that fails."""
    cli = "uv run {project-root}/_bmad/fdw/scripts/fdw_state.py"
    target = LIFECYCLE.index("client-review")
    here = LIFECYCLE.index(entry["status"]) if entry["status"] in LIFECYCLE else target
    if here >= target:
        return []
    return [
        f'{cli} feature-set --root {root} --id {entry["id"]} --status {stage} --by fdw-design'
        + (' --note "design agreed with the BA; empty-state pass complete"' if stage == "client-review" else "")
        for stage in LIFECYCLE[here + 1:target + 1]
    ]


def cmd_check(args: argparse.Namespace) -> None:
    """What must be true before a client sees this. Each problem names its own fix."""
    root = Path(args.root).resolve()
    fdir, entry = feature_dir(root, args.id)
    design = fdir / "design"
    problems: list[str] = []

    proto = design / "prototype"
    proto_files = [p for p in proto.rglob("*") if p.is_file()] if proto.is_dir() else []
    if not proto_files:
        problems.append(
            f"{entry['id']}: design/prototype/ is empty. The client signs off on screens, not on prose — "
            f"generate the prototype before advancing."
        )

    notes = design / "ux-notes.md"
    assumptions: list[str] = []
    if not notes.exists():
        problems.append(f"{entry['id']}: design/ux-notes.md is missing. Run scaffold, then record behaviour as you build.")
    else:
        text = notes.read_text(encoding="utf-8")
        assumptions = re.findall(r"^\s*-\s+\*\*(A\d+)\*\*", text, re.M)
        if not assumptions:
            problems.append(
                f"{entry['id']}: ux-notes.md records no assumptions. Every prototype makes behavioural "
                f"claims nobody confirmed — write them as **A1** … so fdw-elaborate can turn the "
                f"unresolved ones into open questions."
            )
        if not re.search(r"^\s*-\s+\d{4}-\d{2}-\d{2}\s+—", text, re.M):
            problems.append(
                f"{entry['id']}: ux-notes.md has no dated corrections. A design nobody corrected has not "
                f"been reviewed — walk the screens and log what changed."
            )

    empty = design / "empty-state.md"
    gaps: list[str] = []
    if not empty.exists():
        problems.append(f"{entry['id']}: design/empty-state.md is missing. Run scaffold.")
    else:
        text = empty.read_text(encoding="utf-8")
        gaps = re.findall(r"^\s*-\s+\*\*(G\d+)\*\*", text, re.M)
        if "_Not written yet._" in text or not text.split("## Narrative", 1)[-1].split("## Gaps")[0].strip(" \n<!->"):
            problems.append(
                f"{entry['id']}: the empty-state walkthrough is still a stub. Narrate the cold start — "
                f"nothing exists, how does the first one get created? This pass is where the happy path's "
                f"gaps surface, so skipping it moves them downstream into the spec."
            )

    payload = {
        "feature": entry["id"],
        "status": entry["status"],
        "prototype_files": len(proto_files),
        "assumptions": assumptions,
        "gaps": gaps,
        "problems": problems,
        "ready": not problems,
        "next": None if problems else advance_commands(root, entry),
    }
    if problems:
        die(problems, **payload)
    emit(payload)


# ---------------------------------------------------------------- cli


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Deterministic support for fdw-design")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("inventory", help="what components already exist, and what stack they are built in")
    p.add_argument("--project", required=True, help="project root to scan")
    p.add_argument("--path", default=None, help="component directory; auto-detected when omitted")
    p.add_argument("--verbose", action="store_true", help="list every file rather than the first 60")
    p.set_defaults(func=cmd_inventory)

    p = sub.add_parser("scaffold", help="create the design folder and its two contract artifacts")
    p.add_argument("--root", required=True, help="discovery store root")
    p.add_argument("--id", required=True)
    p.set_defaults(func=cmd_scaffold)

    p = sub.add_parser("check", help="is this design ready for the client? each problem names its fix")
    p.add_argument("--root", required=True)
    p.add_argument("--id", required=True)
    p.set_defaults(func=cmd_check)

    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
