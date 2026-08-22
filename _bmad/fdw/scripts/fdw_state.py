#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Owns the fdw discovery state store: creation, pre-pass context, plan validation, atomic apply.

Every fdw skill reads and writes the store through this script so the registry can never
disagree with the feature folders. Stdlib only. All commands print one JSON object to stdout;
failures print {"ok": false, "errors": [...]} and exit 1.
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
from datetime import date
from pathlib import Path
from typing import Any

CONTRACT_VERSION = 1

LIFECYCLE = [
    "candidate",
    "sliced",
    "designing",
    "client-review",
    "design-approved",
    "speccing",
    "spec-approved",
    "handed-off",
    "shipped",
]
FLAGS = ["changed", "deferred", "dropped"]
CRITICALITY = ["critical", "non-critical"]
OWNERS = ["client", "internal", "dev"]
SIZES = ["XS", "S", "M", "L", "XL"]

# A contradiction against a feature at or past this point cannot edit the spec; it opens a
# change record instead. This is the sandbox rule, enforced here rather than trusted to prose.
SPEC_LOCKED = {"spec-approved", "handed-off", "shipped"}

# The contract ships with fdw-intake, which owns it. This script is module-shared, so it
# looks in both the installed and the in-repo location rather than assuming one layout.
_HERE = Path(__file__).resolve()
CONTRACT_SEARCH = [
    _HERE.parent.parent / "assets" / "state-contract.md",
    _HERE.parents[3] / "skills" / "fdw-intake" / "assets" / "state-contract.md",
    _HERE.parents[2] / "skills" / "fdw-intake" / "assets" / "state-contract.md",
]

ANCHOR_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*#(?:t=\d{1,2}:\d{2}(?::\d{2})?|L=\d+(?:-\d+)?|p=\d+|s=[a-z0-9-]+)$")


# ---------------------------------------------------------------- store plumbing


def store(root: Path) -> dict[str, Path]:
    return {
        "root": root,
        "registry": root / "registry.json",
        "decisions": root / "decisions.md",
        "questions": root / "questions.md",
        "glossary": root / "glossary.md",
        "as_built": root / "as-built.md",
        "sources": root / "sources",
        "sources_index": root / "sources" / "index.json",
        "phases": root / "phases",
        "contract": root / "CONTRACT.md",
    }


def pending_dir(root: Path) -> Path:
    """Where a run's in-flight source block and intake plan live, so a compacted
    session can find its own work again instead of starting over."""
    return root / "sources" / ".pending"


def read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        die([f"{path} is not valid JSON: {exc}. Fix the file by hand or restore it from git."])
    return default


def write_json_atomic(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    _write_atomic(path, text)


def _write_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp-", suffix=path.suffix)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def append_md(path: Path, line: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    if existing and not existing.endswith("\n"):
        existing += "\n"
    _write_atomic(path, existing + line.rstrip("\n") + "\n")


def slugify(text: str, limit: int = 48) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    slug = re.sub(r"-{2,}", "-", slug)
    return (slug[:limit].rstrip("-")) or "untitled"


def emit(payload: dict[str, Any]) -> None:
    payload.setdefault("ok", True)
    print(json.dumps(payload, indent=2, ensure_ascii=False))


def die(errors: list[str], **extra: Any) -> None:
    print(json.dumps({"ok": False, "errors": errors, **extra}, indent=2, ensure_ascii=False))
    sys.exit(1)


def today() -> str:
    return date.today().isoformat()


# ---------------------------------------------------------------- init


def empty_registry() -> dict[str, Any]:
    return {
        "contract_version": CONTRACT_VERSION,
        "current_phase": "phase-1",
        "next_feature_seq": 1,
        "phases": ["phase-1"],
        "features": [],
    }


def cmd_init(args: argparse.Namespace) -> None:
    root = Path(args.root).resolve()
    paths = store(root)
    created = []

    for directory in (root, paths["sources"], paths["phases"]):
        if not directory.exists():
            directory.mkdir(parents=True, exist_ok=True)
            created.append(str(directory))

    if not paths["registry"].exists():
        write_json_atomic(paths["registry"], empty_registry())
        created.append(str(paths["registry"]))

    if not paths["sources_index"].exists():
        write_json_atomic(paths["sources_index"], {"contract_version": CONTRACT_VERSION, "sources": []})
        created.append(str(paths["sources_index"]))

    seeds = {
        paths["decisions"]: "# Decisions\n\nAppend-only. One line per decision: what, why, what was rejected, source.\n",
        paths["questions"]: "# Open Questions\n\nDerived rollup — regenerated by fdw-consistency. Do not hand-edit.\n",
        paths["glossary"]: "# Glossary\n\nCanonical domain terms and the aliases seen in sources.\n",
        paths["as_built"]: "# As-Built Baseline\n\nWhat has actually shipped. Refreshed by fdw-handoff at each phase close.\n\n_Nothing shipped yet._\n",
    }
    for path, seed in seeds.items():
        if not path.exists():
            _write_atomic(path, seed)
            created.append(str(path))

    registry = read_json(paths["registry"], empty_registry())
    phase = args.phase or registry.get("current_phase", "phase-1")
    phase_dir = paths["phases"] / phase
    phase_file = phase_dir / "phase.json"
    if not phase_file.exists():
        (phase_dir / "features").mkdir(parents=True, exist_ok=True)
        write_json_atomic(
            phase_file,
            {
                "contract_version": CONTRACT_VERSION,
                "phase": phase,
                "status": "open",
                "opened": today(),
                "closed": None,
                "exit_criteria": [],
                "features": [],
                "carried_over": [],
                "blocker_count_at_handoff": None,
                "prd_path": None,
            },
        )
        created.append(str(phase_file))
        if phase not in registry.get("phases", []):
            registry.setdefault("phases", []).append(phase)
            write_json_atomic(paths["registry"], registry)

    contract_src = next(
        (c for c in CONTRACT_SEARCH if c.exists()),
        None,
    )
    if contract_src and not paths["contract"].exists():
        shutil.copyfile(contract_src, paths["contract"])
        created.append(str(paths["contract"]))

    emit({"root": str(root), "created": created, "already_present": not created, "current_phase": phase})


# ---------------------------------------------------------------- normalize


def _read_source_text(path: Path) -> tuple[str, str, list[dict[str, Any]]]:
    """Return (kind, raw_text, turns). turns is non-empty only for transcripts."""
    suffix = path.suffix.lower()
    raw = path.read_bytes()
    if suffix == ".json":
        try:
            data = json.loads(raw.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return "text", raw.decode("utf-8", errors="replace"), []
        turns = _transcript_turns(data)
        if turns:
            return "transcript", raw.decode("utf-8", errors="replace"), turns
        return "json", json.dumps(data, indent=2, ensure_ascii=False), []
    if suffix in {".md", ".markdown", ".txt", ".csv", ".rst"}:
        return "text", raw.decode("utf-8", errors="replace"), []
    return "binary", "", []


def _transcript_turns(data: Any) -> list[dict[str, Any]]:
    """Group a transcript array into speaker turns. Empty list if this isn't a transcript."""
    if not isinstance(data, list) or not data:
        return []
    text_keys = ("sentence", "text", "content", "utterance")
    time_keys = ("startTime", "start_time", "start", "timestamp", "ts")
    speaker_keys = ("speaker_name", "speaker", "name", "speakerName")

    rows = []
    for item in data:
        if not isinstance(item, dict):
            return []
        text = next((str(item[k]) for k in text_keys if item.get(k)), None)
        if text is None:
            return []
        rows.append(
            {
                "text": text.strip(),
                "time": next((str(item[k]) for k in time_keys if item.get(k)), ""),
                "speaker": next((str(item[k]) for k in speaker_keys if item.get(k)), "Unknown"),
            }
        )

    turns: list[dict[str, Any]] = []
    for row in rows:
        if turns and turns[-1]["speaker"] == row["speaker"]:
            turns[-1]["lines"].append(row["text"])
        else:
            turns.append({"speaker": row["speaker"], "time": row["time"], "lines": [row["text"]]})
    return turns


def _near_matches(index: dict[str, Any], digest: str, sample: str) -> list[dict[str, Any]]:
    hits = []
    for entry in index.get("sources", []):
        if entry.get("sha256") == digest:
            hits.append({"source_id": entry["source_id"], "similarity": 1.0, "relation": "identical"})
            continue
        prior = entry.get("sample", "")
        if not prior or not sample:
            continue
        ratio = difflib.SequenceMatcher(None, prior, sample).quick_ratio()
        if ratio >= 0.80:
            ratio = difflib.SequenceMatcher(None, prior, sample).ratio()
            if ratio >= 0.80:
                hits.append({"source_id": entry["source_id"], "similarity": round(ratio, 3), "relation": "near"})
    return sorted(hits, key=lambda h: -h["similarity"])


def cmd_normalize(args: argparse.Namespace) -> None:
    root = Path(args.root).resolve()
    src = Path(args.file).resolve()
    if not src.exists():
        die([f"Source not found: {src}"])
    paths = store(root)
    if not paths["registry"].exists():
        die([f"No store at {root}. Run: fdw_state.py init --root {root}"])

    kind, raw_text, turns = _read_source_text(src)
    if kind == "binary":
        die(
            [
                f"{src.suffix or 'This file type'} cannot be read as text by this script.",
                "Fix: have a subagent extract it to markdown first, keeping page or section markers "
                "as anchors, then normalize the extracted markdown.",
            ],
            recoverable=True,
            original=str(src),
        )

    digest = hashlib.sha256(src.read_bytes()).hexdigest()
    index = read_json(paths["sources_index"], {"sources": []})
    sample = " ".join(t["lines"][0] for t in turns[:80]) if turns else raw_text[:8000]
    matches = _near_matches(index, digest, sample)

    source_date = args.date or today()
    title = args.title or src.stem.replace("_", " ").replace("-", " ").strip()
    source_id = f"{source_date}-{slugify(title)}"

    if turns:
        body = [f"## [[t={t['time']}]] {t['speaker']}\n\n" + "\n".join(t["lines"]) for t in turns]
        anchor_count = len(turns)
        content = "\n\n".join(body)
        anchor_kind = "t"
    else:
        lines = raw_text.splitlines()
        body = []
        for start in range(0, len(lines), 20):
            chunk = "\n".join(lines[start : start + 20]).rstrip()
            if chunk.strip():
                body.append(f"## [[L={start + 1}]]\n\n{chunk}")
        anchor_count = len(body)
        content = "\n\n".join(body)
        anchor_kind = "L"

    front = [
        "---",
        f"source_id: {source_id}",
        f"kind: {kind}",
        f"original: {src}",
        f"sha256: {digest}",
        f"ingested: {today()}",
        f"anchor_kind: {anchor_kind}",
        "---",
        "",
        f"# {title}",
        "",
        "_Verbatim. Original language preserved — a translated quote is not evidence._",
        "",
        "",
    ]
    out = paths["sources"] / f"{source_id}.md"
    _write_atomic(out, "\n".join(front) + content + "\n")

    # The source block is written here, not transcribed by the model into its plan.
    # A hand-copied sha256 is a defect waiting to happen.
    source_block = {
        "source_id": source_id,
        "sha256": digest,
        "path": str(out.relative_to(root)),
        "original": str(src),
        "title": title,
        "date": source_date,
        "kind": kind,
        "sample": sample[:400],
    }
    write_json_atomic(pending_dir(root) / f"{source_id}.source.json", source_block)

    emit(
        {
            "source_id": source_id,
            "plan_path": str((pending_dir(root) / f"{source_id}.plan.json").relative_to(root)),
            "path": str(out.relative_to(root)),
            "sha256": digest,
            "kind": kind,
            "anchor_kind": anchor_kind,
            "anchor_count": anchor_count,
            "chars": len(content),
            "sample": sample[:400],
            "matches": matches,
            "already_ingested": any(m["relation"] == "identical" for m in matches),
        }
    )


# ---------------------------------------------------------------- context pre-pass


def _feature_dir(root: Path, feature: dict[str, Any]) -> Path:
    return store(root)["phases"] / feature["phase"] / "features" / f"{feature['id']}-{feature['slug']}"


def _open_questions(root: Path, registry: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for feature in registry.get("features", []):
        record = read_json(_feature_dir(root, feature) / "feature.json", {})
        for question in record.get("questions", []):
            if question.get("status", "open") == "open":
                out.append({**question, "feature_id": feature["id"], "feature_title": feature["title"]})
    return out


def cmd_context(args: argparse.Namespace) -> None:
    root = Path(args.root).resolve()
    paths = store(root)
    if not paths["registry"].exists():
        die([f"No store at {root}. Run: fdw_state.py init --root {root}"])
    registry = read_json(paths["registry"], empty_registry())

    features = []
    for feature in registry.get("features", []):
        record = read_json(_feature_dir(root, feature) / "feature.json", {})
        features.append(
            {
                "id": feature["id"],
                "title": feature["title"],
                "slug": feature["slug"],
                "phase": feature["phase"],
                "status": feature["status"],
                "flags": feature.get("flags", []),
                "size": feature.get("size"),
                "aliases": record.get("aliases", []),
                "summary": record.get("summary", ""),
                "spec_locked": feature["status"] in SPEC_LOCKED,
            }
        )

    glossary = []
    if paths["glossary"].exists():
        for line in paths["glossary"].read_text(encoding="utf-8").splitlines():
            match = re.match(r"^-\s+\*\*(.+?)\*\*\s*(?:\((.*?)\))?\s*—\s*(.*)$", line.strip())
            if match:
                aliases = [a.strip() for a in (match.group(2) or "").split(",") if a.strip()]
                glossary.append({"term": match.group(1), "aliases": aliases, "definition": match.group(3)})

    index = read_json(paths["sources_index"], {"sources": []})
    emit(
        {
            "root": str(root),
            "current_phase": registry.get("current_phase", "phase-1"),
            "phases": registry.get("phases", []),
            "next_feature_id": f"F-{registry.get('next_feature_seq', 1):03d}",
            "features": features,
            "open_questions": _open_questions(root, registry),
            "glossary": glossary,
            "ingested_sources": [
                {"source_id": s["source_id"], "date": s.get("date"), "title": s.get("title")}
                for s in index.get("sources", [])
            ],
            "as_built_present": paths["as_built"].exists()
            and "_Nothing shipped yet._" not in paths["as_built"].read_text(encoding="utf-8"),
            "lifecycle": LIFECYCLE,
        }
    )


# ---------------------------------------------------------------- plan validation


def _check_signal(entries: Any, where: str, source_id: str, errors: list[str]) -> None:
    if not isinstance(entries, list) or not entries:
        errors.append(f"{where}: needs at least one signal entry. A feature with no evidence does not get written.")
        return
    for i, entry in enumerate(entries):
        label = f"{where}.signal[{i}]"
        if not isinstance(entry, dict):
            errors.append(f"{label}: must be an object with text, anchor and quote.")
            continue
        for field in ("text", "anchor", "quote"):
            if not str(entry.get(field, "")).strip():
                errors.append(
                    f"{label}: missing '{field}'. Every requirement carries provenance — "
                    f"source anchor and verbatim quote — or it does not get written."
                )
        anchor = str(entry.get("anchor", "")).strip()
        if anchor and not ANCHOR_RE.match(anchor):
            errors.append(
                f"{label}: anchor '{anchor}' is malformed. Use '{source_id}#t=MM:SS' for transcripts "
                f"or '{source_id}#L=<line>' for documents."
            )


def _check_questions(entries: Any, where: str, errors: list[str]) -> None:
    for i, question in enumerate(entries or []):
        label = f"{where}.questions[{i}]"
        if not str(question.get("text", "")).strip():
            errors.append(f"{label}: missing 'text'.")
        if question.get("criticality") not in CRITICALITY:
            errors.append(f"{label}: criticality must be one of {CRITICALITY}.")
        if question.get("owner") not in OWNERS:
            errors.append(f"{label}: owner must be one of {OWNERS} — who has to answer this?")


def resolve_source(root: Path, plan: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Fill the plan's source block from what `normalize` recorded. The plan only has to
    name a source_id; everything else is looked up, so nothing is transcribed by hand."""
    source = dict(plan.get("source") or {})
    source_id = str(source.get("source_id", "")).strip()
    if not source_id:
        return source, ["source.source_id is required — it is what every anchor points at."]
    recorded = read_json(pending_dir(root) / f"{source_id}.source.json")
    if recorded is None:
        missing = [f for f in ("sha256", "path") if not str(source.get(f, "")).strip()]
        if missing:
            return source, [
                f"No normalize record for source '{source_id}', and the plan does not supply {missing}. "
                f"Run: fdw_state.py normalize --root {root} --file <path>"
            ]
        return source, []
    if source.get("sha256") and source["sha256"] != recorded["sha256"]:
        return source, [
            f"source.sha256 does not match what normalize recorded for '{source_id}'. "
            f"Drop the field and let it be looked up rather than copying it by hand."
        ]
    merged = {**recorded, **{k: v for k, v in source.items() if v not in (None, "")}}
    merged["sha256"] = recorded["sha256"]
    merged["path"] = recorded["path"]
    return merged, []


def validate_plan(root: Path, plan: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    paths = store(root)
    registry = read_json(paths["registry"], empty_registry())
    by_id = {f["id"]: f for f in registry.get("features", [])}
    known_slugs = {f["slug"] for f in registry.get("features", [])}
    open_q = {q["id"]: q for q in _open_questions(root, registry)}
    phases = set(registry.get("phases", []))

    source, source_errors = resolve_source(root, plan)
    errors.extend(source_errors)
    source_id = str(source.get("source_id", "")).strip()

    supersedes = source.get("supersedes")
    if supersedes:
        index = read_json(paths["sources_index"], {"sources": []})
        if supersedes not in {s["source_id"] for s in index.get("sources", [])}:
            errors.append(f"source.supersedes '{supersedes}' is not an ingested source.")

    seen_slugs: set[str] = set()
    for i, feature in enumerate(plan.get("new_features", [])):
        where = f"new_features[{i}]"
        title = str(feature.get("title", "")).strip()
        if not title:
            errors.append(f"{where}: missing 'title'.")
        slug = str(feature.get("slug", "")).strip() or slugify(title)
        if slug in known_slugs:
            errors.append(
                f"{where}: slug '{slug}' already exists in the registry. "
                f"If this is the same feature, move it to 'merges'; if not, give it a distinct slug."
            )
        if slug in seen_slugs:
            errors.append(f"{where}: slug '{slug}' is duplicated inside this plan.")
        seen_slugs.add(slug)
        phase = feature.get("phase")
        if phase not in phases:
            errors.append(f"{where}: phase '{phase}' does not exist. Known phases: {sorted(phases)}.")
        if feature.get("size") is not None and feature.get("size") not in SIZES:
            errors.append(f"{where}: size must be null or one of {SIZES}.")
        _check_signal(feature.get("signal"), where, source_id, errors)
        _check_questions(feature.get("questions"), where, errors)

    for i, merge in enumerate(plan.get("merges", [])):
        where = f"merges[{i}]"
        fid = merge.get("feature_id")
        if fid not in by_id:
            errors.append(f"{where}: feature_id '{fid}' is not in the registry.")
            continue
        _check_signal(merge.get("signal"), where, source_id, errors)
        _check_questions(merge.get("questions"), where, errors)

    for i, contradiction in enumerate(plan.get("contradictions", [])):
        where = f"contradictions[{i}]"
        fid = contradiction.get("feature_id")
        if fid not in by_id:
            errors.append(f"{where}: feature_id '{fid}' is not in the registry.")
            continue
        for field in ("text", "anchor", "quote"):
            if not str(contradiction.get(field, "")).strip():
                errors.append(f"{where}: missing '{field}'. Both sides of a contradiction must be quotable.")
        if by_id[fid]["status"] in SPEC_LOCKED and contradiction.get("route") != "change-record":
            errors.append(
                f"{where}: feature {fid} is '{by_id[fid]['status']}', so its spec is locked. "
                f"Set route to 'change-record' — intake never edits an approved spec."
            )

    for i, closure in enumerate(plan.get("question_closures", [])):
        where = f"question_closures[{i}]"
        qid = closure.get("question_id")
        if qid not in open_q:
            errors.append(f"{where}: question_id '{qid}' is not an open question. Open ids: {sorted(open_q)[:12]}")
            continue
        for field in ("answer", "anchor", "quote"):
            if not str(closure.get(field, "")).strip():
                errors.append(
                    f"{where}: missing '{field}'. A question closes against the client's own words, not a paraphrase."
                )

    for i, term in enumerate(plan.get("glossary", [])):
        if not str(term.get("term", "")).strip():
            errors.append(f"glossary[{i}]: missing 'term'.")

    if not any(
        plan.get(key)
        for key in ("new_features", "merges", "contradictions", "question_closures", "glossary", "deferred")
    ):
        errors.append(
            "Plan is empty. If the source genuinely contained nothing new, that is a valid outcome — "
            "record it with --empty instead of applying an empty plan."
        )
    return errors


def cmd_validate_plan(args: argparse.Namespace) -> None:
    root = Path(args.root).resolve()
    plan = read_json(Path(args.plan).resolve())
    if plan is None:
        die([f"Plan not found: {args.plan}"])
    errors = validate_plan(root, plan)
    if errors:
        die(errors)
    emit({"valid": True, "counts": _plan_counts(plan)})


def _plan_counts(plan: dict[str, Any]) -> dict[str, int]:
    return {key: len(plan.get(key, [])) for key in ("new_features", "merges", "contradictions", "question_closures", "glossary", "deferred")}


# ---------------------------------------------------------------- apply


def _signal_block(source_id: str, entries: list[dict[str, Any]]) -> str:
    lines = [f"\n## From {source_id}\n"]
    for entry in entries:
        lines.append(f"- {entry['text'].strip()}")
        lines.append(f"  - anchor: `{entry['anchor']}`")
        lines.append(f"  - quote: > {entry['quote'].strip()}")
        if entry.get("speaker"):
            lines.append(f"  - speaker: {entry['speaker']}")
    return "\n".join(lines) + "\n"


def cmd_apply_plan(args: argparse.Namespace) -> None:
    root = Path(args.root).resolve()
    plan = read_json(Path(args.plan).resolve())
    if plan is None:
        die([f"Plan not found: {args.plan}"])
    errors = validate_plan(root, plan)
    if errors:
        die(errors, hint="Fix the plan and re-run apply-plan. Nothing was written.")

    paths = store(root)
    registry = read_json(paths["registry"], empty_registry())
    by_id = {f["id"]: f for f in registry.get("features", [])}
    source, _ = resolve_source(root, plan)
    source_id = source["source_id"]
    stamp = today()
    delta: dict[str, Any] = {"created": [], "merged": [], "questions_closed": [], "contradictions": [], "deferred": []}

    # New features: folder + feature.json + signal.md, registry entry appended.
    for feature in plan.get("new_features", []):
        seq = registry.get("next_feature_seq", 1)
        fid = f"F-{seq:03d}"
        registry["next_feature_seq"] = seq + 1
        slug = str(feature.get("slug") or slugify(feature["title"]))
        phase = feature["phase"]
        entry = {
            "id": fid,
            "title": feature["title"],
            "slug": slug,
            "phase": phase,
            "status": "sliced",
            "flags": [],
            "size": feature.get("size"),
            "depends_on": [],
            "overlaps": [],
            "open_questions": {"critical": 0, "non-critical": 0},
            "updated": stamp,
        }
        for question in feature.get("questions", []):
            entry["open_questions"][question["criticality"]] += 1
        registry.setdefault("features", []).append(entry)

        fdir = paths["phases"] / phase / "features" / f"{fid}-{slug}"
        (fdir / "design").mkdir(parents=True, exist_ok=True)
        questions = [
            {
                "id": f"{fid}-Q-{i + 1:02d}",
                "text": q["text"],
                "criticality": q["criticality"],
                "owner": q["owner"],
                "status": "open",
                "raised": stamp,
                "raised_by": source_id,
            }
            for i, q in enumerate(feature.get("questions", []))
        ]
        write_json_atomic(
            fdir / "feature.json",
            {
                "contract_version": CONTRACT_VERSION,
                "id": fid,
                "title": feature["title"],
                "slug": slug,
                "phase": phase,
                "status": "sliced",
                "flags": [],
                "size": feature.get("size"),
                "summary": feature.get("summary", ""),
                "aliases": feature.get("aliases", []),
                "depends_on": [],
                "overlaps": [],
                "sources": [source_id],
                "questions": questions,
                "created": stamp,
                "updated": stamp,
            },
        )
        _write_atomic(
            fdir / "signal.md",
            f"# {feature['title']} — Signal\n\n"
            f"Evidence only. Every line is anchored to a source; nothing here is inference.\n"
            + _signal_block(source_id, feature["signal"]),
        )
        delta["created"].append({"id": fid, "title": feature["title"], "phase": phase, "path": str(fdir.relative_to(root))})

    # Merges: append evidence and questions to an existing feature.
    for merge in plan.get("merges", []):
        fid = merge["feature_id"]
        entry = by_id[fid]
        fdir = _feature_dir(root, entry)
        record = read_json(fdir / "feature.json", {})
        append_md(fdir / "signal.md", _signal_block(source_id, merge["signal"]))
        existing = len(record.get("questions", []))
        for i, question in enumerate(merge.get("questions", [])):
            record.setdefault("questions", []).append(
                {
                    "id": f"{fid}-Q-{existing + i + 1:02d}",
                    "text": question["text"],
                    "criticality": question["criticality"],
                    "owner": question["owner"],
                    "status": "open",
                    "raised": stamp,
                    "raised_by": source_id,
                }
            )
            entry["open_questions"][question["criticality"]] += 1
        for alias in merge.get("aliases_add", []):
            if alias not in record.setdefault("aliases", []):
                record["aliases"].append(alias)
        if source_id not in record.setdefault("sources", []):
            record["sources"].append(source_id)
        record["updated"] = stamp
        entry["updated"] = stamp
        write_json_atomic(fdir / "feature.json", record)
        delta["merged"].append({"id": fid, "signal_added": len(merge["signal"])})

    # Contradictions: a change record when the spec is locked, an open question otherwise.
    for contradiction in plan.get("contradictions", []):
        fid = contradiction["feature_id"]
        entry = by_id[fid]
        fdir = _feature_dir(root, entry)
        record = read_json(fdir / "feature.json", {})
        locked = entry["status"] in SPEC_LOCKED
        if locked:
            append_md(
                fdir / "changes.md",
                f"\n## {stamp} — change raised by {source_id}\n\n"
                f"- what: {contradiction['text']}\n"
                f"- anchor: `{contradiction['anchor']}`\n"
                f"- quote: > {contradiction['quote']}\n"
                f"- feature status when raised: {entry['status']}\n"
                f"- downstream impact: design invalidated = {contradiction.get('design_invalidated', 'unknown')}; "
                f"already handed to dev = {entry['status'] in {'handed-off', 'shipped'}}\n"
                f"- resolution: OPEN — route through fdw-elaborate. Intake never edits an approved spec.\n",
            )
            if "changed" not in entry.setdefault("flags", []):
                entry["flags"].append("changed")
            if "changed" not in record.setdefault("flags", []):
                record["flags"].append("changed")
        existing = len(record.get("questions", []))
        record.setdefault("questions", []).append(
            {
                "id": f"{fid}-Q-{existing + 1:02d}",
                "text": f"Contradiction: {contradiction['text']}",
                "criticality": contradiction.get("criticality", "critical"),
                "owner": contradiction.get("owner", "client"),
                "status": "open",
                "raised": stamp,
                "raised_by": source_id,
            }
        )
        entry["open_questions"][contradiction.get("criticality", "critical")] += 1
        record["updated"] = stamp
        entry["updated"] = stamp
        write_json_atomic(fdir / "feature.json", record)
        delta["contradictions"].append({"id": fid, "locked": locked, "text": contradiction["text"]})

    # Question closures: the answer plus the words that answered it.
    open_lookup = {q["id"]: q for q in _open_questions(root, registry)}
    for closure in plan.get("question_closures", []):
        qid = closure["question_id"]
        fid = open_lookup[qid]["feature_id"]
        entry = by_id[fid]
        fdir = _feature_dir(root, entry)
        record = read_json(fdir / "feature.json", {})
        for question in record.get("questions", []):
            if question["id"] == qid:
                question["status"] = "resolved"
                question["answer"] = closure["answer"]
                question["answer_anchor"] = closure["anchor"]
                question["answer_quote"] = closure["quote"]
                question["resolved"] = stamp
                counts = entry["open_questions"]
                counts[question["criticality"]] = max(0, counts.get(question["criticality"], 0) - 1)
        record["updated"] = stamp
        entry["updated"] = stamp
        write_json_atomic(fdir / "feature.json", record)
        delta["questions_closed"].append({"question_id": qid, "feature_id": fid})

    for item in plan.get("deferred", []):
        append_md(
            paths["decisions"],
            f"- {stamp} · deferred · {item.get('title', '?')} → {item.get('phase', 'later')} · "
            f"{item.get('reason', 'no reason given')} · source: {source_id}",
        )
        delta["deferred"].append(item)

    for term in plan.get("glossary", []):
        aliases = ", ".join(term.get("aliases", []))
        alias_part = f" ({aliases})" if aliases else ""
        append_md(paths["glossary"], f"- **{term['term']}**{alias_part} — {term.get('definition', '')}")

    for line in plan.get("decisions", []):
        append_md(paths["decisions"], f"- {stamp} · decision · {line} · source: {source_id}")

    # Phase membership.
    for created in delta["created"]:
        phase_file = paths["phases"] / created["phase"] / "phase.json"
        phase_record = read_json(phase_file, {})
        if phase_record:
            phase_record.setdefault("features", []).append(created["id"])
            write_json_atomic(phase_file, phase_record)

    # Source index, then the registry LAST — it is the index, so it lands only once
    # every folder it points at exists.
    index = read_json(paths["sources_index"], {"sources": []})
    index.setdefault("sources", []).append(
        {
            "source_id": source_id,
            "sha256": source["sha256"],
            "path": source["path"],
            "original": source.get("original"),
            "title": source.get("title", source_id),
            "date": source.get("date", stamp),
            "kind": source.get("kind", "unknown"),
            "sample": source.get("sample", "")[:400],
            "supersedes": source.get("supersedes"),
            "features_touched": [c["id"] for c in delta["created"]] + [m["id"] for m in delta["merged"]],
            "ingested": stamp,
        }
    )
    write_json_atomic(paths["sources_index"], index)

    if source.get("supersedes"):
        append_md(
            paths["decisions"],
            f"- {stamp} · decision · source {source_id} supersedes {source['supersedes']} "
            f"(corrected re-export; evidence re-anchored, features not duplicated)",
        )

    write_json_atomic(paths["registry"], registry)

    # The run landed, so its in-flight scratch is no longer state anyone should resume from.
    for leftover in pending_dir(root).glob(f"{source_id}.*"):
        leftover.unlink(missing_ok=True)

    emit({"applied": True, "source_id": source_id, "delta": delta, "counts": _plan_counts(plan)})


def cmd_record_empty(args: argparse.Namespace) -> None:
    root = Path(args.root).resolve()
    paths = store(root)
    stamp = today()
    source, errors = resolve_source(root, {"source": {"source_id": args.source_id}})
    if errors:
        die(errors)
    index = read_json(paths["sources_index"], {"sources": []})
    index.setdefault("sources", []).append(
        {
            **source,
            "features_touched": [],
            "ingested": stamp,
            "outcome": "no-new-signal",
        }
    )
    write_json_atomic(paths["sources_index"], index)
    for leftover in pending_dir(root).glob(f"{args.source_id}.*"):
        leftover.unlink(missing_ok=True)
    append_md(paths["decisions"], f"- {stamp} · event · ingested {args.source_id} — no new features or requirements. {args.reason or ''}".rstrip())
    emit({"recorded": args.source_id, "outcome": "no-new-signal"})


# ---------------------------------------------------------------- feature updates


def cmd_feature_set(args: argparse.Namespace) -> None:
    """Advance or amend one feature. Forward moves may not skip a gate; backward moves are
    always allowed, because rework is normal and pretending otherwise makes skills lie."""
    root = Path(args.root).resolve()
    paths = store(root)
    registry = read_json(paths["registry"], empty_registry())
    entry = next((f for f in registry.get("features", []) if f["id"] == args.id), None)
    if entry is None:
        die([f"No feature '{args.id}' in the registry. Known: {[f['id'] for f in registry.get('features', [])]}"])

    fdir = _feature_dir(root, entry)
    record = read_json(fdir / "feature.json")
    if record is None:
        die([f"{args.id}: {fdir.relative_to(root)}/feature.json is missing. Run: fdw_state.py validate --root {root}"])

    stamp = today()
    changes: list[str] = []

    if args.status and args.status != entry["status"]:
        if args.status not in LIFECYCLE:
            die([f"'{args.status}' is not a lifecycle stage. Stages: {LIFECYCLE}"])
        here, there = LIFECYCLE.index(entry["status"]), LIFECYCLE.index(args.status)
        if there > here + 1 and not args.force:
            skipped = LIFECYCLE[here + 1:there]
            die([
                f"{args.id}: moving {entry['status']} → {args.status} skips {skipped}. "
                f"Each stage is a gate — {LIFECYCLE[here + 1]} has to happen first. "
                f"Pass --force only if the skipped work genuinely happened elsewhere; it is logged as an override."
            ])
        if there > here + 1:
            append_md(
                paths["decisions"],
                f"- {stamp} · override · {args.id} forced {entry['status']} → {args.status}, "
                f"skipping {LIFECYCLE[here + 1:there]} · {args.note or 'no reason given'}",
            )
        changes.append(f"status {entry['status']} → {args.status}")
        entry["status"] = record["status"] = args.status

    if args.size:
        if args.size not in SIZES:
            die([f"size must be one of {SIZES}."])
        changes.append(f"size {entry.get('size')} → {args.size}")
        entry["size"] = record["size"] = args.size

    for flag in args.add_flag or []:
        if flag not in FLAGS:
            die([f"'{flag}' is not a known flag. Known: {FLAGS}"])
        for target in (entry, record):
            if flag not in target.setdefault("flags", []):
                target["flags"].append(flag)
        changes.append(f"+flag {flag}")

    for flag in args.remove_flag or []:
        for target in (entry, record):
            if flag in target.get("flags", []):
                target["flags"].remove(flag)
        changes.append(f"-flag {flag}")

    for dep in args.depends_on or []:
        if dep == args.id:
            die([f"{args.id} cannot depend on itself."])
        if dep not in {f["id"] for f in registry.get("features", [])}:
            die([f"depends_on '{dep}' is not a feature in the registry."])
        for target in (entry, record):
            if dep not in target.setdefault("depends_on", []):
                target["depends_on"].append(dep)
        changes.append(f"depends_on +{dep}")

    if not changes:
        emit({"id": args.id, "changed": [], "status": entry["status"], "note": "nothing to do"})
        return

    entry["updated"] = record["updated"] = stamp
    write_json_atomic(fdir / "feature.json", record)
    write_json_atomic(paths["registry"], registry)
    if args.note:
        append_md(paths["decisions"], f"- {stamp} · decision · {args.id}: {args.note} · source: {args.by or 'fdw'}")
    emit({"id": args.id, "changed": changes, "status": entry["status"], "flags": entry.get("flags", [])})


def cmd_question_close(args: argparse.Namespace) -> None:
    """Close one question outside an ingest run. Client sign-off and inline feedback are real
    answers but have no anchored document, so this path takes a named source instead of an
    anchor. Answers that arrive as a document should go through intake, which anchors them."""
    root = Path(args.root).resolve()
    paths = store(root)
    registry = read_json(paths["registry"], empty_registry())
    open_lookup = {q["id"]: q for q in _open_questions(root, registry)}
    if args.question_id not in open_lookup:
        die([
            f"'{args.question_id}' is not an open question. Open ids: {sorted(open_lookup)[:12]}"
        ])
    fid = open_lookup[args.question_id]["feature_id"]
    entry = next(f for f in registry["features"] if f["id"] == fid)
    fdir = _feature_dir(root, entry)
    record = read_json(fdir / "feature.json", {})
    stamp = today()
    for question in record.get("questions", []):
        if question["id"] == args.question_id:
            question.update({
                "status": "resolved",
                "answer": args.answer,
                "answer_source": args.source,
                "resolved": stamp,
            })
            if args.quote:
                question["answer_quote"] = args.quote
            counts = entry["open_questions"]
            counts[question["criticality"]] = max(0, counts.get(question["criticality"], 0) - 1)
    record["updated"] = entry["updated"] = stamp
    write_json_atomic(fdir / "feature.json", record)
    write_json_atomic(paths["registry"], registry)
    append_md(
        paths["decisions"],
        f"- {stamp} · decision · {args.question_id} answered: {args.answer} · source: {args.source}",
    )
    emit({"question_id": args.question_id, "feature_id": fid, "status": "resolved",
          "open_questions": entry["open_questions"]})


# ---------------------------------------------------------------- store integrity


def cmd_validate(args: argparse.Namespace) -> None:
    root = Path(args.root).resolve()
    paths = store(root)
    if not paths["registry"].exists():
        die([f"No store at {root}. Run: fdw_state.py init --root {root}"])
    registry = read_json(paths["registry"], empty_registry())
    problems: list[str] = []
    seen_ids: set[str] = set()
    seen_slugs: set[str] = set()

    for feature in registry.get("features", []):
        fid = feature.get("id", "?")
        if fid in seen_ids:
            problems.append(f"{fid}: duplicate id in registry. Ids are minted once and never reused.")
        seen_ids.add(fid)
        if feature.get("slug") in seen_slugs:
            problems.append(f"{fid}: slug '{feature.get('slug')}' is used by another feature.")
        seen_slugs.add(feature.get("slug"))
        if feature.get("status") not in LIFECYCLE:
            problems.append(f"{fid}: status '{feature.get('status')}' is not in the lifecycle {LIFECYCLE}.")
        for flag in feature.get("flags", []):
            if flag not in FLAGS:
                problems.append(f"{fid}: unknown flag '{flag}'. Known flags: {FLAGS}.")
        fdir = _feature_dir(root, feature)
        if not fdir.exists():
            problems.append(f"{fid}: registry points at {fdir.relative_to(root)} but that folder does not exist.")
            continue
        record = read_json(fdir / "feature.json")
        if record is None:
            problems.append(f"{fid}: {fdir.relative_to(root)}/feature.json is missing.")
            continue
        for field in ("id", "title", "slug", "phase", "status"):
            if record.get(field) != feature.get(field):
                problems.append(
                    f"{fid}: '{field}' disagrees — registry has '{feature.get(field)}', "
                    f"feature.json has '{record.get(field)}'. The registry is the index; reconcile to the feature record."
                )
        if not (fdir / "signal.md").exists():
            problems.append(f"{fid}: signal.md is missing. A feature with no evidence should not exist.")
        counted = {"critical": 0, "non-critical": 0}
        for question in record.get("questions", []):
            if question.get("status", "open") == "open":
                counted[question.get("criticality", "critical")] += 1
        if counted != feature.get("open_questions"):
            problems.append(f"{fid}: open_questions count is stale — registry {feature.get('open_questions')}, actual {counted}.")

    for phase in registry.get("phases", []):
        if not (paths["phases"] / phase / "phase.json").exists():
            problems.append(f"phase '{phase}' is in the registry but has no phases/{phase}/phase.json.")

    orphans = []
    if paths["sources"].exists():
        indexed = {s["source_id"] for s in read_json(paths["sources_index"], {"sources": []}).get("sources", [])}
        orphans = sorted(p.stem for p in paths["sources"].glob("*.md") if p.stem not in indexed)

    payload = {
        "root": str(root),
        "features": len(registry.get("features", [])),
        "problems": problems,
        "unindexed_sources": orphans,
        "healthy": not problems,
    }
    if problems:
        die(problems, **payload)
    emit(payload)


# ---------------------------------------------------------------- cli


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="fdw discovery state store")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("init", help="create the store, idempotently")
    p.add_argument("--root", required=True)
    p.add_argument("--phase", default=None)
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("normalize", help="normalize one source into anchored markdown and hash it")
    p.add_argument("--root", required=True)
    p.add_argument("--file", required=True)
    p.add_argument("--title", default=None)
    p.add_argument("--date", default=None)
    p.set_defaults(func=cmd_normalize)

    p = sub.add_parser("context", help="pre-pass JSON: features, open questions, glossary, next id")
    p.add_argument("--root", required=True)
    p.set_defaults(func=cmd_context)

    p = sub.add_parser("validate-plan", help="check an intake plan against the store; errors name the fix")
    p.add_argument("--root", required=True)
    p.add_argument("--plan", required=True)
    p.set_defaults(func=cmd_validate_plan)

    p = sub.add_parser("apply-plan", help="apply a validated intake plan and return the delta")
    p.add_argument("--root", required=True)
    p.add_argument("--plan", required=True)
    p.set_defaults(func=cmd_apply_plan)

    p = sub.add_parser("record-empty", help="record a source that carried no new signal")
    p.add_argument("--root", required=True)
    p.add_argument("--source-id", required=True, dest="source_id")
    p.add_argument("--reason", default=None)
    p.set_defaults(func=cmd_record_empty)

    p = sub.add_parser("feature-set", help="advance or amend one feature; forward moves cannot skip a gate")
    p.add_argument("--root", required=True)
    p.add_argument("--id", required=True)
    p.add_argument("--status", default=None)
    p.add_argument("--size", default=None)
    p.add_argument("--add-flag", action="append", dest="add_flag")
    p.add_argument("--remove-flag", action="append", dest="remove_flag")
    p.add_argument("--depends-on", action="append", dest="depends_on")
    p.add_argument("--note", default=None, help="one line for decisions.md")
    p.add_argument("--by", default=None, help="which skill made the change")
    p.add_argument("--force", action="store_true", help="allow a forward move that skips a gate; logged as an override")
    p.set_defaults(func=cmd_feature_set)

    p = sub.add_parser("question-close", help="close one question from client feedback or sign-off")
    p.add_argument("--root", required=True)
    p.add_argument("--question-id", required=True, dest="question_id")
    p.add_argument("--answer", required=True)
    p.add_argument("--source", required=True, help="where the answer came from, e.g. a packet id or 'client email 2026-08-25'")
    p.add_argument("--quote", default=None, help="the client's own words, when you have them")
    p.set_defaults(func=cmd_question_close)

    p = sub.add_parser("validate", help="check the registry and the feature folders still agree")
    p.add_argument("--root", required=True)
    p.set_defaults(func=cmd_validate)

    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
