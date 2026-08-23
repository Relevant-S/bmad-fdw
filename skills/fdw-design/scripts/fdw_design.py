#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Deterministic support for fdw-design: grounding the prototype in the real product,
scaffolding the design folder, and the readiness gate before a feature goes to the client.

Judgment — what to draw, which page to clone, whether a correction is right — stays in the
prompt. This script finds things, creates skeletons, and then verifies the prompt's claims
against the filesystem: a cited source that does not exist, a token file that was retyped
rather than copied, a screen nobody declared. Prose can assert fidelity; only a check can
establish it.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import date
from pathlib import Path
from typing import Any

COMPONENT_EXT = {".tsx": "react", ".jsx": "react", ".vue": "vue", ".svelte": "svelte",
                 ".astro": "astro", ".ts": "react", ".js": "react"}
MARKUP_EXT = {".html", ".htm", ".erb", ".hbs", ".twig", ".php", ".liquid"}
SKIP_DIR = {"node_modules", ".git", "dist", "build", ".next", ".output", ".svelte-kit", "out",
            "coverage", "__pycache__", ".venv", "venv", "storybook-static", ".turbo", "vendor",
            "target", "ios", "android", "DerivedData", "Pods", ".serena"}
BUNDLE_RE = re.compile(r"-[A-Za-z0-9_]{6,}\.(css|js)$|\.min\.(css|js)$")
SKIP_FILE = re.compile(r"\.(test|spec|stories|d)\.[jt]sx?$|^index\.[jt]sx?$")
WALK_CAP = 6000

EXPORT_PATTERNS = [
    re.compile(r"export\s+default\s+function\s+([A-Z][A-Za-z0-9_]*)"),
    re.compile(r"export\s+function\s+([A-Z][A-Za-z0-9_]*)"),
    re.compile(r"export\s+const\s+([A-Z][A-Za-z0-9_]*)\s*[:=]"),
    re.compile(r"export\s+class\s+([A-Z][A-Za-z0-9_]*)"),
    re.compile(r"export\s*\{([^}]*)\}"),
]
PROPS_RE = re.compile(r"(?:interface|type)\s+([A-Z][A-Za-z0-9_]*Props)\b")

CSS_VAR_RE = re.compile(r"--[A-Za-z0-9][\w-]*\s*:")
TOKEN_NAME_RE = re.compile(
    r"^(globals?|theme|tokens|variables|design-tokens|palette|colou?rs)\.(css|scss|sass|less|ts|js|json)$"
    r"|^tailwind\.config\.[cm]?[jt]s$|\.tokens\.json$",
    re.I,
)
CLASS_ATTR_RE = re.compile(r"\b(?:class|className|:class)\s*=\s*[\"'{`]([^\"'`}]*)")
MODULE_REF_RE = re.compile(r"^[A-Za-z_$][\w$]*\.[\w$.]+$")  # styles.row — a reference, not vocabulary
CSS_RULE_RE = re.compile(r"[^{}@;/]+\{[^{}]*\}", re.S)
COLOUR_RE = re.compile(r"#[0-9a-fA-F]{3,8}\b|\brgba?\([^)]*\)|\bhsla?\([^)]*\)")

SCREEN_FILE_RE = re.compile(r"^(S\d+)\b")
SCREEN_MARK_RE = re.compile(r"data-screen\s*=\s*[\"'](S\d+)[\"']")
NOTES_SCREEN_RE = re.compile(r"^\s*-\s+\*\*(S\d+)\b", re.M)

PAGE_DIR_HINT = re.compile(r"(^|/)(pages?|routes?|views?|screens?|app|features?|containers?)(/|$)")
PAGE_NAME_RE = re.compile(r"(^|[/\\])(page|index|route|\+page)\.[a-z]+$|(Page|View|Screen|Route)\.[a-z]+$")
ARCHETYPE_SIGNALS = {
    "list": re.compile(r"<table|<tbody|DataTable|\bTable\b|role=[\"']table|\.map\(|<ul\b|DataGrid", re.I),
    "form": re.compile(r"<form\b|onSubmit|useForm|<input\b|\bInput\b|register\(|<select\b", re.I),
    "dialog": re.compile(r"\bDialog\b|\bModal\b|<dialog\b|aria-modal|Drawer|Sheet\b", re.I),
    "detail": re.compile(r"useParams|params\.\w*id|\[id\]|:id\b|getById|<slug>", re.I),
    "empty": re.compile(r"empty[-_ ]?state|no results|nothing here|isEmpty|length === 0", re.I),
}


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


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ---------------------------------------------------------------- discovery ladder


def walk_files(root: Path, exts: set[str], cap: int = WALK_CAP):
    """Every source file under root, vendor and build output excluded. Capped, because a
    monorepo with a stray artifacts directory should slow the BA down, not stop them."""
    seen = 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIR and not d.startswith(".")]
        for name in filenames:
            if Path(name).suffix.lower() in exts:
                seen += 1
                if seen > cap:
                    return
                yield Path(dirpath) / name


def all_manifests(root: Path) -> list[Path]:
    """Every package.json outside vendor directories. A workspace root declares none of the
    real dependencies — they live in the member packages — so reading only the top one is how
    a monorepo gets reported as having no framework at all."""
    found: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIR and not d.startswith(".")]
        if "package.json" in filenames:
            found.append(Path(dirpath) / "package.json")
        if len(found) > 200:
            break
    return found


def detect_stack(project: Path) -> dict[str, Any]:
    deps: dict[str, Any] = {}
    scripts: dict[str, Any] = {}
    for manifest in all_manifests(project):
        pkg = read_json(manifest, {}) or {}
        deps.update(pkg.get("dependencies", {}) or {})
        deps.update(pkg.get("devDependencies", {}) or {})
        if manifest.parent == project:
            scripts = pkg.get("scripts", {}) or {}
    framework = next((f for f in ("next", "nuxt", "remix", "astro", "svelte", "vue", "react")
                      if f in deps or f"@sveltejs/kit" in deps and f == "svelte"), None)
    styling = ("tailwind" if "tailwindcss" in deps
               else "mui" if any(k.startswith("@mui/") for k in deps)
               else "chakra" if any(k.startswith("@chakra-ui/") for k in deps)
               else "styled-components" if "styled-components" in deps
               else "css-modules" if any((project / d).exists() for d in ("src/styles", "styles")) else None)
    pm = ("pnpm" if (project / "pnpm-lock.yaml").exists()
          else "yarn" if (project / "yarn.lock").exists()
          else "bun" if (project / "bun.lockb").exists()
          else "npm" if (project / "package-lock.json").exists() else None)
    return {"framework": framework, "styling": styling,
            "typescript": "typescript" in deps or (project / "tsconfig.json").exists(),
            "package_manager": pm, "run_commands": runnable(project, pm)}


def runnable(project: Path, pm: str | None) -> list[dict[str, str]]:
    """How to start each app in the tree. A workspace root usually cannot be started at all —
    the dev script lives in the member app — so a single root-only lookup reports a runnable
    product as unrunnable, and the BA never gets to see the real thing beside the prototype."""
    out: list[dict[str, str]] = []
    for manifest in all_manifests(project):
        scripts = (read_json(manifest, {}) or {}).get("scripts", {}) or {}
        script = next((s for s in ("dev", "start", "serve") if s in scripts), None)
        if script:
            rel = manifest.parent.relative_to(project) if manifest.parent.is_relative_to(project) else manifest.parent
            out.append({"dir": str(rel), "command": f"{pm or 'npm'} run {script}"})
    return out[:8]


COMPONENT_DIR_CANDIDATES = [
    "src/components", "app/components", "components", "src/ui", "src/lib/components",
    "packages/ui/src", "packages/ui/src/components", "packages/design-system/src",
    "src/shared/components", "lib/components", "app/javascript/components", "resources/js/components",
]


def search_roots(project: Path) -> list[Path]:
    """Where to look, in widening order. The BMad project root is routinely the docs directory
    with the application beside it, so a search that never leaves the project root reports a
    shipping product as having no components at all."""
    roots = [project]
    parent = project.parent
    if parent != project:
        roots.append(parent)
        for sib in sorted(p for p in parent.iterdir() if p.is_dir()):
            if sib != project and sib.name not in SKIP_DIR and not sib.name.startswith("."):
                roots.append(sib)
    return roots


def find_component_root(project: Path) -> tuple[Path | None, Path, list[str]]:
    """Returns (component_root, app_root, places searched)."""
    searched: list[str] = []
    for root in search_roots(project):
        for rel in COMPONENT_DIR_CANDIDATES:
            path = root / rel
            searched.append(str(path))
            if path.is_dir() and any(walk_files(path, set(COMPONENT_EXT), cap=1)):
                return path, root, searched
    return None, project, searched


def workspace_root(start: Path) -> Path:
    """The outermost ancestor that still looks like part of this install. A component library in a
    monorepo sits under its own package.json, but the framework, the lockfile and the run scripts
    live at the workspace root — stopping at the nearest manifest reports the design-system package
    as the whole application."""
    best = start
    current = start
    for _ in range(8):
        if current.parent == current:
            break
        current = current.parent
        if any((current / m).exists() for m in
               ("package.json", "pnpm-workspace.yaml", "pnpm-lock.yaml", "yarn.lock", "package-lock.json")):
            best = current
    return best


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


def find_token_sources(app_root: Path, component_root: Path | None) -> list[dict[str, Any]]:
    """The files that define colour, type and spacing. These get copied verbatim into the
    prototype — never transcribed — so what matters is finding the file, not reading it."""
    hits: list[dict[str, Any]] = []
    scopes = [p for p in {component_root.parent if component_root else None, app_root} if p]
    seen: set[Path] = set()
    for scope in scopes:
        for file in walk_files(scope, {".css", ".scss", ".sass", ".less", ".json", ".ts", ".js"}, cap=3000):
            if file in seen:
                continue
            if BUNDLE_RE.search(file.name):
                continue
            named = bool(TOKEN_NAME_RE.search(file.name))
            if not named and file.suffix.lower() not in (".css", ".scss", ".sass", ".less"):
                continue
            text = read_text(file)
            variables = len(CSS_VAR_RE.findall(text))
            if named or variables >= 8:
                seen.add(file)
                hits.append({"file": str(file.relative_to(app_root)) if file.is_relative_to(app_root) else str(file),
                             "variables": variables, "named_like_tokens": named})
    hits.sort(key=lambda h: (not h["named_like_tokens"], -h["variables"]))
    return hits[:10]


def score_reference_pages(app_root: Path, component_root: Path | None) -> list[dict[str, Any]]:
    """Real pages, ranked by archetype. The single most useful thing to hand the model: a page
    of the same shape that already ships tells it the shell, the spacing, the table style and
    the empty state all at once — none of which a list of component names carries."""
    pages: list[dict[str, Any]] = []
    exts = set(COMPONENT_EXT) | MARKUP_EXT
    for file in walk_files(app_root, exts):
        if component_root and file.is_relative_to(component_root):
            continue
        if SKIP_FILE.search(file.name):
            continue
        rel = str(file.relative_to(app_root))
        if not (PAGE_DIR_HINT.search(rel.replace(os.sep, "/")) or PAGE_NAME_RE.search(rel)):
            continue
        text = read_text(file)
        if len(text) < 400:
            continue
        archetypes = [name for name, pattern in ARCHETYPE_SIGNALS.items() if pattern.search(text)]
        if not archetypes:
            continue
        pages.append({"file": rel, "archetypes": archetypes, "lines": text.count("\n") + 1,
                      "classes": len(class_vocabulary(text))})
    pages.sort(key=lambda p: (-len(p["archetypes"]), -p["classes"]))
    return pages[:25]


def cmd_inventory(args: argparse.Namespace) -> None:
    project = Path(args.project).resolve()
    if not project.is_dir():
        die([f"No project directory at {project}."])

    if args.path:
        component_root: Path | None = Path(args.path).resolve()
        app_root = Path(args.app_root).resolve() if args.app_root else workspace_root(component_root)
        searched = [str(component_root)]
        if not component_root.is_dir():
            die([f"No component directory at {component_root}. Config points there via "
                 f"component_library_path — fix the config or drop the --path argument."])
    else:
        component_root, app_root, searched = find_component_root(project)

    stack = detect_stack(app_root)

    if component_root is None:
        die(
            [
                f"Could not find a component library from {project}. Searched {len(searched)} "
                f"locations under the project, its parent and its siblings.",
                "This is a failed search, not a verdict. Before drawing anything, work the ladder: "
                "read component_library_path from config; ask the BA where the application lives and "
                "write the answer back to config; or have the BA confirm in words that this project "
                "has no UI yet.",
                "Never infer greenfield from this result. On a project that already ships, drawing "
                "from scratch produces a redesign the client did not ask for.",
            ],
            verdict="not_found",
            recoverable=True,
            project=str(project),
            stack=stack,
            searched=searched[:40],
        )

    components: list[dict[str, Any]] = []
    for file in sorted(walk_files(component_root, set(COMPONENT_EXT))):
        if SKIP_FILE.search(file.name):
            continue
        text = read_text(file)
        names = exported_names(text) or ([file.stem] if file.suffix in (".vue", ".svelte", ".astro") else [])
        if not names:
            continue
        components.append({
            "file": str(file.relative_to(app_root)) if file.is_relative_to(app_root) else str(file),
            "exports": names,
            "props_types": PROPS_RE.findall(text),
            "kind": COMPONENT_EXT.get(file.suffix.lower(), "unknown"),
            "lines": text.count("\n") + 1,
        })

    every = sorted({name for c in components for name in c["exports"]})
    emit({
        "verdict": "found",
        "project": str(project),
        "app_root": str(app_root),
        "component_root": str(component_root.relative_to(app_root)) if component_root.is_relative_to(app_root)
        else str(component_root),
        "stack": stack,
        "component_count": len(every),
        "file_count": len(components),
        "components": every,
        "tokens": find_token_sources(app_root, component_root),
        "reference_pages": score_reference_pages(app_root, component_root),
        "files": components if args.verbose else components[:60],
        "truncated": (not args.verbose) and len(components) > 60,
    })


# ---------------------------------------------------------------- design folder


UX_NOTES = """# {title} — UX Notes

Behaviour agreed through the prototype. **This file is the primary input to `fdw-elaborate`** —
the prototype itself is disposable, these notes are not. Write so someone who never saw the
screens can still write the spec.

## Scope boundary

This prototype covers **{fid} only**. The features below are separate entries in the registry with
their own designs; screens for them do not belong here, and neither does an invented navigation
shell that implies them.

{siblings}

## Screens

<!-- One line per screen. Ids S1, S2 … are referenced by assumptions, corrections and gaps, and
     every one of them must also appear in grounding.json with the real source it was cloned from.
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

GROUNDING: dict[str, Any] = {
    "_comment": "Where this prototype came from. Every claim here is verified against the filesystem "
                "by `fdw_design.py check`, so a cited path that does not exist, a token file that was "
                "retyped instead of copied, or a screen nobody declared will fail the gate. "
                "Project-side paths resolve from app_root; app_root and prototype_dir resolve from the "
                "discovery store root unless absolute.",
    "mode": "",
    "_mode": "extracted = cloned from the real product's own source, which is every project that "
             "already ships anything. greenfield = there is genuinely no UI yet, and this prototype "
             "establishes the library. A failed component search is not greenfield.",
    "greenfield_confirmed_by": "",
    "_greenfield_confirmed_by": "Who said so, in words. Required for greenfield mode: it is a fact the "
                                "BA states, never one a search infers.",
    "app_root": "",
    "component_root": "",
    "prototype_dir": "prototype",
    "tokens": [],
    "_tokens": "[{\"source\": \"packages/ui/src/styles/globals.css\", \"copied_to\": \"prototype/tokens.css\"}]. "
               "copied_to must be byte-identical to source. Retyping the palette is what produces a "
               "prototype with the right colours and the wrong everything else.",
    "reference_pages": [],
    "_reference_pages": "Real pages of the same archetype that the new screens were cloned from.",
    "chrome": {"origin": "", "source": ""},
    "_chrome": "borrowed = the shell comes from a real layout file, named in source. none = the "
               "prototype draws no navigation at all. There is no third option; invented chrome is how "
               "a one-feature prototype turns into a whole application.",
    "screens": [],
    "_screens": "[{\"id\": \"S1\", \"kind\": \"as-is|new\", \"file\": \"prototype/S1-course-list.html\", "
                "\"source\": \"apps/admin/src/features/courses/CourseListPage.tsx\"}]. One screen, one "
                "file named for its id — or a region marked data-screen=\"S1\" inside one.",
    "comparison": [],
    "_comparison": "[{\"screen\": \"S1\", \"reference\": \"screenshot or real source path\", "
                   "\"verdict\": \"matches|differs\", \"differences\": \"what differs, and why it is "
                   "deliberate\"}]. Required for every as-is screen: the reproduction is worthless if "
                   "nobody put it beside the thing it reproduces.",
}


def feature_dir(root: Path, feature_id: str) -> tuple[Path, dict[str, Any], dict[str, Any]]:
    registry = read_json(root / "registry.json")
    if registry is None:
        die([f"No discovery store at {root}. Run fdw-intake first."])
    entry = next((f for f in registry.get("features", []) if f["id"] == feature_id), None)
    if entry is None:
        die([f"No feature '{feature_id}'. Known: {[f['id'] for f in registry.get('features', [])]}"])
    return root / "phases" / entry["phase"] / "features" / f"{entry['id']}-{entry['slug']}", entry, registry


def sibling_lines(registry: dict[str, Any], entry: dict[str, Any]) -> str:
    others = [f for f in registry.get("features", [])
              if f["id"] != entry["id"] and f.get("phase") == entry.get("phase")]
    if not others:
        return "_No other features in this phase yet._"
    return "**Out of scope — other features in this phase:**\n\n" + "\n".join(
        f"- {f['id']} — {f['title']}" for f in others)


def cmd_scaffold(args: argparse.Namespace) -> None:
    root = Path(args.root).resolve()
    fdir, entry, registry = feature_dir(root, args.id)
    design = fdir / "design"
    proto_rel = args.prototype_path or "prototype"
    proto = Path(proto_rel) if Path(proto_rel).is_absolute() else design / proto_rel
    design.mkdir(parents=True, exist_ok=True)
    proto.mkdir(parents=True, exist_ok=True)
    created = []
    fields = {"title": entry["title"], "fid": entry["id"], "today": date.today().isoformat(),
              "siblings": sibling_lines(registry, entry)}
    for name, template in (("ux-notes.md", UX_NOTES), ("empty-state.md", EMPTY_STATE)):
        target = design / name
        if not target.exists():
            target.write_text(template.format(**fields), encoding="utf-8")
            created.append(str(target.relative_to(root)))
    grounding = design / "grounding.json"
    if not grounding.exists():
        payload = dict(GROUNDING)
        payload["prototype_dir"] = proto_rel
        grounding.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        created.append(str(grounding.relative_to(root)))
    emit({
        "feature": entry["id"],
        "title": entry["title"],
        "design_dir": str(design.relative_to(root)),
        "prototype_dir": str(proto),
        "grounding": str(grounding.relative_to(root)),
        "out_of_scope": [f["id"] for f in registry.get("features", [])
                         if f["id"] != entry["id"] and f.get("phase") == entry.get("phase")],
        "created": created,
        "already_present": not created,
    })


# ---------------------------------------------------------------- fidelity


def class_vocabulary(text: str) -> set[str]:
    """Class names actually shared between files. A CSS-modules project writes `styles.row`, which
    names nothing another file could reuse — counting those would score honest work as invention."""
    out: set[str] = set()
    for chunk in CLASS_ATTR_RE.findall(text):
        for token in chunk.split():
            token = token.strip("{}$`,'\"")
            if token and not token.startswith(("${", "@")) and not MODULE_REF_RE.match(token):
                out.add(token)
    return out


def resolve(base: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else (base / path)


def prototype_files(design: Path, root: Path, grounding: dict[str, Any]) -> tuple[Path, list[Path]]:
    proto = resolve(design, grounding.get("prototype_dir") or "prototype")
    files = [p for p in proto.rglob("*") if p.is_file()] if proto.is_dir() else []
    return proto, files


def screens_in_prototype(files: list[Path]) -> set[str]:
    found: set[str] = set()
    for file in files:
        match = SCREEN_FILE_RE.match(file.name)
        if match:
            found.add(match.group(1))
        if file.suffix.lower() in MARKUP_EXT | set(COMPONENT_EXT):
            found.update(SCREEN_MARK_RE.findall(read_text(file)))
    return found


def fidelity_problems(design: Path, root: Path, entry: dict[str, Any],
                      notes_text: str) -> tuple[list[str], dict[str, Any]]:
    """Verify what the notes claim. Every rule here exists because prose asserting fidelity is
    free and a prototype that reimplements the product from memory reads exactly the same."""
    fid = entry["id"]
    path = design / "grounding.json"
    grounding = read_json(path)
    if grounding is None:
        return ([f"{fid}: design/grounding.json is missing or unparseable. Run scaffold, then record "
                 f"what the prototype was cloned from — an ungrounded prototype cannot be checked, "
                 f"only believed."], {})

    problems: list[str] = []
    report: dict[str, Any] = {"mode": grounding.get("mode") or None}
    mode = (grounding.get("mode") or "").strip()

    if mode not in ("extracted", "greenfield"):
        problems.append(
            f"{fid}: grounding.json records no mode. Set it to 'extracted' when the product already "
            f"ships anything, or 'greenfield' when the BA has confirmed there is no UI yet.")
        return problems, report

    if mode == "greenfield":
        if not (grounding.get("greenfield_confirmed_by") or "").strip():
            problems.append(
                f"{fid}: greenfield mode with nobody named in greenfield_confirmed_by. Greenfield is a "
                f"fact the BA states; a component search that came back empty is not evidence of it.")
        report["screens"] = sorted(screens_in_prototype(prototype_files(design, root, grounding)[1]))
        return problems, report

    app_root = resolve(root, grounding.get("app_root") or "")
    if not (grounding.get("app_root") or "").strip() or not app_root.is_dir():
        problems.append(
            f"{fid}: app_root '{grounding.get('app_root')}' is not a directory. Extracted mode means "
            f"cloning real source; without a real app on disk there is nothing to clone from.")
        return problems, report
    report["app_root"] = str(app_root)

    comp_root = grounding.get("component_root") or ""
    if comp_root and not resolve(app_root, comp_root).is_dir():
        problems.append(f"{fid}: component_root '{comp_root}' does not exist under {app_root}.")

    proto, files = prototype_files(design, root, grounding)
    source_text: dict[str, str] = {}

    def cited(rel: str) -> Path:
        return resolve(app_root, rel)

    # Tokens are copied, never transcribed.
    for token in grounding.get("tokens") or []:
        src = cited(token.get("source", ""))
        if not src.is_file():
            problems.append(f"{fid}: token source '{token.get('source')}' does not exist under {app_root}.")
            continue
        copied = token.get("copied_to")
        if not copied:
            continue
        dst = resolve(design, copied)
        if not dst.is_file():
            problems.append(f"{fid}: token file '{copied}' is declared copied but is not in the prototype.")
        elif sha256(dst) != sha256(src):
            problems.append(
                f"{fid}: '{copied}' is not byte-identical to {token['source']}. Copy the token file; do "
                f"not retype its values. A transcribed palette drifts the moment the product's does.")

    # Every screen is declared, cloned from something real, and present.
    declared_notes = set(NOTES_SCREEN_RE.findall(notes_text))
    declared_ground = {s.get("id") for s in grounding.get("screens") or [] if s.get("id")}
    present = screens_in_prototype(files)
    report.update({"screens_declared": sorted(declared_notes | declared_ground),
                   "screens_in_prototype": sorted(present)})

    if not grounding.get("screens"):
        problems.append(
            f"{fid}: grounding.json lists no screens. Each screen needs the real file it was cloned "
            f"from — that citation is the whole difference between reproducing and inventing.")
    for screen in grounding.get("screens") or []:
        sid = screen.get("id", "?")
        file_rel = screen.get("file")
        src_rel = screen.get("source")
        pfile = resolve(design, file_rel) if file_rel else None
        if not file_rel or not pfile or not pfile.is_file():
            problems.append(f"{fid}: screen {sid} names no prototype file that exists ('{file_rel}').")
        if not src_rel:
            problems.append(
                f"{fid}: screen {sid} cites no source. An as-is screen cites what it reproduces; a new "
                f"screen cites the page it was cloned from.")
            continue
        src = cited(src_rel)
        if not src.is_file():
            problems.append(f"{fid}: screen {sid} cites '{src_rel}', which does not exist under {app_root}.")
            continue
        source_text[sid] = read_text(src)

        if pfile and pfile.is_file():
            proto_classes = class_vocabulary(read_text(pfile))
            src_classes = class_vocabulary(source_text[sid])
            if len(src_classes) < 8 or len(proto_classes) < 8:
                # Nothing measurable: styled-components, CSS modules, a source that carries no
                # shared class names. The visual comparison below is the only check left, so say so
                # rather than reporting a fidelity the script never established.
                report.setdefault("class_overlap", {})[sid] = None
            else:
                shared = len(proto_classes & src_classes) / len(proto_classes)
                report.setdefault("class_overlap", {})[sid] = round(shared, 3)
                if shared < 0.3:
                    problems.append(
                        f"{fid}: screen {sid} shares {shared:.0%} of its styling vocabulary with "
                        f"{src_rel}. That is a reimplementation wearing the right colours, not a clone. "
                        f"Start from the real markup and change what the feature changes.")

    for sid in sorted(declared_notes - declared_ground):
        problems.append(f"{fid}: {sid} appears in ux-notes but not in grounding.json — nothing says where it came from.")
    for sid in sorted(present - (declared_notes | declared_ground)):
        problems.append(
            f"{fid}: the prototype contains {sid}, which no note declares. Screens outside the feature "
            f"boundary are how one feature turns into a whole application — remove it or declare it.")
    for sid in sorted((declared_notes | declared_ground) - present):
        problems.append(f"{fid}: {sid} is declared but not present in the prototype at {proto}.")

    # Chrome is borrowed or absent. Invented chrome has no source to cite.
    chrome = grounding.get("chrome") or {}
    origin = (chrome.get("origin") or "").strip()
    if origin not in ("borrowed", "none"):
        problems.append(
            f"{fid}: chrome.origin is '{origin or 'unset'}'. Say 'borrowed' and name the real layout "
            f"file, or 'none' and draw no navigation. Anything else is a nav bar the client never "
            f"asked for, implying pages that belong to other features.")
    elif origin == "borrowed":
        src = cited(chrome.get("source") or "")
        if not (chrome.get("source") or "").strip() or not src.exists():
            problems.append(f"{fid}: chrome is 'borrowed' but its source '{chrome.get('source')}' does not exist.")

    # A stylesheet the project already has, written a second time.
    bespoke = 0
    copied_paths = {resolve(design, t["copied_to"]) for t in (grounding.get("tokens") or []) if t.get("copied_to")}
    for file in files:
        if file in copied_paths or file.suffix.lower() not in MARKUP_EXT | {".css", ".scss", ".less"}:
            continue
        bespoke += len(CSS_RULE_RE.findall(read_text(file)))
    report["bespoke_css_rules"] = bespoke
    if grounding.get("tokens") and bespoke > 30:
        problems.append(
            f"{fid}: the prototype hand-authors {bespoke} CSS rules while the project already has a "
            f"styling system. Reuse it — a parallel stylesheet is the same reimplementation the class "
            f"check catches, moved into a <style> block.")

    # The reproduction has to be put beside the thing it reproduces.
    compared = {c.get("screen") for c in grounding.get("comparison") or []}
    as_is = {s.get("id") for s in grounding.get("screens") or [] if s.get("kind") == "as-is"}
    missing = sorted(as_is - compared)
    if missing:
        problems.append(
            f"{fid}: no side-by-side comparison recorded for {', '.join(missing)}. Put each as-is screen "
            f"next to the real one and record what matched and what differs, before the BA sees it — "
            f"they should be correcting the feature, not the reproduction.")
    report["compared"] = sorted(compared)

    return problems, report


# ---------------------------------------------------------------- readiness gate


LIFECYCLE = [
    "candidate", "sliced", "designing", "client-review", "design-approved",
    "speccing", "spec-approved", "handed-off", "shipped",
]


def state_cli() -> str:
    """The shared state CLI ships inside fdw-intake, a sibling of this skill once installed.
    Resolve a real path so the command printed here is one the caller can actually paste."""
    sibling = Path(__file__).resolve().parents[2] / "fdw-intake" / "scripts" / "fdw_state.py"
    return f"uv run {sibling}" if sibling.exists() else \
        "uv run {skill-root}/../fdw-intake/scripts/fdw_state.py"


def advance_commands(root: Path, entry: dict[str, Any]) -> list[str]:
    """The actual command sequence from where the feature is to client-review. feature-set
    refuses a forward move that skips a gate, so suggesting the single end-state command
    would hand the caller something that fails."""
    cli = state_cli()
    target = LIFECYCLE.index("client-review")
    here = LIFECYCLE.index(entry["status"]) if entry["status"] in LIFECYCLE else target
    if here >= target:
        return []
    return [
        f'{cli} feature-set --root {root} --id {entry["id"]} --status {stage} --by fdw-design'
        + (' --note "design agreed with the BA; empty-state pass complete"' if stage == "client-review" else "")
        for stage in LIFECYCLE[here + 1:target + 1]
    ]


def cmd_fidelity(args: argparse.Namespace) -> None:
    root = Path(args.root).resolve()
    fdir, entry, _ = feature_dir(root, args.id)
    design = fdir / "design"
    notes = design / "ux-notes.md"
    problems, report = fidelity_problems(design, root, entry, read_text(notes) if notes.exists() else "")
    payload = {"feature": entry["id"], "problems": problems, "grounded": not problems, **report}
    if problems:
        die(problems, **payload)
    emit(payload)


def cmd_check(args: argparse.Namespace) -> None:
    """What must be true before a client sees this. Each problem names its own fix."""
    root = Path(args.root).resolve()
    fdir, entry, _ = feature_dir(root, args.id)
    design = fdir / "design"
    problems: list[str] = []

    grounding = read_json(design / "grounding.json") or {}
    proto, proto_files = prototype_files(design, root, grounding)
    if not proto_files:
        problems.append(
            f"{entry['id']}: the prototype at {proto} is empty. The client signs off on screens, not on "
            f"prose — generate the prototype before advancing.")

    notes = design / "ux-notes.md"
    notes_text = ""
    assumptions: list[str] = []
    if not notes.exists():
        problems.append(f"{entry['id']}: design/ux-notes.md is missing. Run scaffold, then record behaviour as you build.")
    else:
        notes_text = read_text(notes)
        assumptions = re.findall(r"^\s*-\s+\*\*(A\d+)\*\*", notes_text, re.M)
        if not assumptions:
            problems.append(
                f"{entry['id']}: ux-notes.md records no assumptions. Every prototype makes behavioural "
                f"claims nobody confirmed — write them as **A1** … so fdw-elaborate can turn the "
                f"unresolved ones into open questions.")
        if not re.search(r"^\s*-\s+\d{4}-\d{2}-\d{2}\s+—", notes_text, re.M):
            problems.append(
                f"{entry['id']}: ux-notes.md has no dated corrections. A design nobody corrected has not "
                f"been reviewed — walk the screens and log what changed.")

    empty = design / "empty-state.md"
    gaps: list[str] = []
    if not empty.exists():
        problems.append(f"{entry['id']}: design/empty-state.md is missing. Run scaffold.")
    else:
        text = read_text(empty)
        gaps = re.findall(r"^\s*-\s+\*\*(G\d+)\*\*", text, re.M)
        if "_Not written yet._" in text or not text.split("## Narrative", 1)[-1].split("## Gaps")[0].strip(" \n<!->"):
            problems.append(
                f"{entry['id']}: the empty-state walkthrough is still a stub. Narrate the cold start — "
                f"nothing exists, how does the first one get created? This pass is where the happy path's "
                f"gaps surface, so skipping it moves them downstream into the spec.")

    fidelity, report = fidelity_problems(design, root, entry, notes_text)
    problems.extend(fidelity)

    payload = {
        "feature": entry["id"],
        "status": entry["status"],
        "prototype_dir": str(proto),
        "prototype_files": len(proto_files),
        "assumptions": assumptions,
        "gaps": gaps,
        "fidelity": report,
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

    p = sub.add_parser("inventory", help="the fidelity kit: components, tokens, reference pages, stack")
    p.add_argument("--project", required=True, help="project root to scan; parent and siblings are searched too")
    p.add_argument("--path", default=None, help="component directory, from config component_library_path")
    p.add_argument("--app-root", default=None, help="application root, when it is not an ancestor of --path")
    p.add_argument("--verbose", action="store_true", help="list every file rather than the first 60")
    p.set_defaults(func=cmd_inventory)

    p = sub.add_parser("scaffold", help="create the design folder, its contract artifacts and the grounding record")
    p.add_argument("--root", required=True, help="discovery store root")
    p.add_argument("--id", required=True)
    p.add_argument("--prototype-path", default=None,
                   help="where the prototype lives; relative to the design folder unless absolute")
    p.set_defaults(func=cmd_scaffold)

    p = sub.add_parser("fidelity", help="is the prototype actually grounded in the real product?")
    p.add_argument("--root", required=True)
    p.add_argument("--id", required=True)
    p.set_defaults(func=cmd_fidelity)

    p = sub.add_parser("check", help="is this design ready for the client? each problem names its fix")
    p.add_argument("--root", required=True)
    p.add_argument("--id", required=True)
    p.set_defaults(func=cmd_check)

    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
