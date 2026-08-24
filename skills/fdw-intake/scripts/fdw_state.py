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

# This script and the contract it copies both ship inside fdw-intake, which owns them.
_HERE = Path(__file__).resolve()
CONTRACT_SEARCH = [_HERE.parent.parent / "assets" / "state-contract.md"]

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


def phase_key(label: str) -> tuple[int, ...]:
    """Sort phases by their numeric label, so phase-2.1 sits between 2 and 3 and phase-10
    after phase-9. Insertion order stops being reliable the moment a brownfield store starts
    at phase-3 and someone later opens an earlier one."""
    nums = re.findall(r"\d+", label or "")
    return tuple(int(n) for n in nums) or (0,)


def sort_phases(labels: list[str]) -> list[str]:
    return sorted(dict.fromkeys(labels), key=phase_key)


def empty_registry(phase: str = "phase-1") -> dict[str, Any]:
    """A new store knows about exactly one phase: the one it was started at. Earlier phases
    are deliberately absent — this module never invents history it has no evidence for, and a
    brownfield project's prior work belongs in as-built.md, not in fabricated phase records."""
    return {
        "contract_version": CONTRACT_VERSION,
        "current_phase": phase,
        "next_feature_seq": 1,
        "phases": [phase],
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

    # Decide the starting phase before the registry is written, so current_phase and the
    # phases list agree with the folder that actually gets created.
    fresh = not paths["registry"].exists()
    start_phase = args.phase or ("phase-1" if fresh else None)
    if fresh:
        write_json_atomic(paths["registry"], empty_registry(start_phase))
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
    phase = start_phase or registry.get("current_phase", "phase-1")
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
            registry["phases"] = sort_phases(registry.get("phases", []) + [phase])
            write_json_atomic(paths["registry"], registry)

    contract_src = next(
        (c for c in CONTRACT_SEARCH if c.exists()),
        None,
    )
    if contract_src and not paths["contract"].exists():
        shutil.copyfile(contract_src, paths["contract"])
        created.append(str(paths["contract"]))

    emit({"root": str(root), "created": created, "already_present": not created,
          "current_phase": registry.get("current_phase", phase), "phase": phase,
          "phases": registry.get("phases", [phase])})


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


def next_question_id(fid: str, record: dict[str, Any]) -> str:
    """The next free question id for a feature. Derived from the highest id actually in use, not
    from how many questions there are: once a caller may supply its own id, the list can carry
    gaps, and length-plus-one walks straight into an id that is already taken."""
    used = [
        int(match.group(1))
        for question in record.get("questions", [])
        if (match := re.match(rf"^{re.escape(fid)}-Q-(\d+)$", str(question.get("id", ""))))
    ]
    return f"{fid}-Q-{max(used, default=0) + 1:02d}"


def question_record(fid: str, question: dict[str, Any], stamp: str, source: str,
                    record: dict[str, Any], text: str | None = None) -> dict[str, Any]:
    """One question, in the shape the contract declares. Every writer goes through here so the
    seven keys can never drift apart between one creation site and the next."""
    return {
        "id": question.get("id") or next_question_id(fid, record),
        "text": text if text is not None else question["text"],
        "criticality": question.get("criticality", "critical"),
        "owner": question.get("owner", "client"),
        "status": "open",
        "raised": stamp,
        "raised_by": source,
    }


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
        questions: list[dict[str, Any]] = []
        for q in feature.get("questions", []):
            questions.append(question_record(fid, q, stamp, source_id, {"questions": questions}))
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
        for question in merge.get("questions", []):
            record.setdefault("questions", []).append(
                question_record(fid, question, stamp, source_id, record))
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
        record.setdefault("questions", []).append(
            question_record(fid, contradiction, stamp, source_id, record,
                            text=f"Contradiction: {contradiction['text']}"))
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

    for other in args.overlaps or []:
        if other == args.id:
            die([f"{args.id} cannot overlap itself."])
        if other not in {f["id"] for f in registry.get("features", [])}:
            die([f"overlaps '{other}' is not a feature in the registry."])
        # Overlap is symmetric, so record both directions. A one-sided edge is a graph the
        # dashboard and the audit would each have to guess at.
        peer = next(f for f in registry["features"] if f["id"] == other)
        peer_dir = _feature_dir(root, peer)
        peer_record = read_json(peer_dir / "feature.json", {})
        for target in (entry, record):
            if other not in target.setdefault("overlaps", []):
                target["overlaps"].append(other)
        for target in (peer, peer_record):
            if args.id not in target.setdefault("overlaps", []):
                target["overlaps"].append(args.id)
        if peer_record:
            peer_record["updated"] = stamp
            write_json_atomic(peer_dir / "feature.json", peer_record)
        peer["updated"] = stamp
        changes.append(f"overlaps {other} (both ways)")

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


def _normalise(text: str) -> str:
    return re.sub(r"[\s.;:!?—–-]+", " ", str(text)).strip().casefold()


def cmd_question_add(args: argparse.Namespace) -> None:
    """Raise questions against a feature from outside an ingest run.

    Until this existed, a question could only be born inside apply-plan — so every question a BA
    found while writing the spec lived in prose that no gate reads, and approval, the pre-flight
    report and the phase's own blocker count all reported zero while the spec listed eight."""
    root = Path(args.root).resolve()
    paths = store(root)
    registry = read_json(paths["registry"], empty_registry())

    batch = read_json(Path(args.from_file).resolve()) if args.from_file else None
    if args.from_file and batch is None:
        die([f"No batch at {args.from_file}, or it is not JSON."])
    fid = args.id or (batch or {}).get("feature")
    source = args.source or (batch or {}).get("source")
    incoming = (batch or {}).get("questions") if batch else [
        {"id": args.question_id, "text": args.text,
         "criticality": args.criticality, "owner": args.owner}
    ]
    if not fid:
        die(["No feature id. Pass --id, or put 'feature' in the batch file."])
    if not source:
        die([f"{fid}: --source is required — where did this question come from? It is what a "
             f"later reader uses to tell an evidenced question from a guess."])
    if not incoming:
        die([f"{fid}: nothing to add."])

    entry = next((f for f in registry.get("features", []) if f["id"] == fid), None)
    if entry is None:
        die([f"No feature '{fid}'. Known: {[f['id'] for f in registry.get('features', [])]}"])
    fdir = _feature_dir(root, entry)
    record = read_json(fdir / "feature.json")
    if record is None:
        die([f"{fid}: no feature.json at {fdir}. Run validate — the registry and the folders disagree."])

    # Validate every entry before writing any of it: a batch that is half-applied is worse than
    # one that is refused, because nothing downstream can tell which half landed.
    errors: list[str] = []
    known = {q.get("id"): q for q in record.get("questions", [])}
    open_text = {_normalise(q.get("text", "")): q for q in record.get("questions", [])
                 if q.get("status", "open") == "open"}
    done_text = {_normalise(q.get("text", "")): q for q in record.get("questions", [])
                 if q.get("status") == "resolved"}
    plan: list[dict[str, Any]] = []
    already: list[str] = []
    warnings: list[str] = []

    for i, question in enumerate(incoming):
        where = f"{fid}.questions[{i}]"
        text = str(question.get("text", "")).strip()
        criticality = question.get("criticality")
        owner = question.get("owner")
        qid = question.get("id")
        if not text:
            errors.append(f"{where}: missing 'text'.")
        if criticality not in CRITICALITY:
            errors.append(f"{where}: criticality must be one of {CRITICALITY}.")
        if owner not in OWNERS:
            errors.append(f"{where}: owner must be one of {OWNERS} — who has to answer this?")
        if qid is not None:
            if not re.fullmatch(rf"{re.escape(fid)}-Q-\d{{2,}}", str(qid)):
                errors.append(f"{where}: '{qid}' is not an id for {fid}. Shape is {fid}-Q-NN.")
            elif qid in known:
                # Re-running the same sync must be a no-op, not a second copy.
                if _normalise(known[qid].get("text", "")) == _normalise(text):
                    already.append(qid)
                    continue
                errors.append(
                    f"{where}: {qid} already exists with different wording. Ids never change meaning "
                    f"— close it and raise a new one.\n    have: {known[qid].get('text', '')}\n"
                    f"    got:  {text}")
                continue
        twin = open_text.get(_normalise(text))
        if twin and not args.allow_duplicate:
            errors.append(
                f"{where}: {twin['id']} is already open with the same wording. Pass "
                f"--allow-duplicate if these really are two questions.")
            continue
        settled = done_text.get(_normalise(text))
        if settled:
            warnings.append(
                f"{settled['id']} was answered on {settled.get('resolved', '?')} with the same "
                f"wording. Raising it again is fine if something changed — worth a look first.")
        plan.append({"id": qid, "text": text, "criticality": criticality, "owner": owner})

    if errors:
        die(errors, feature=fid, hint="Nothing was written.")

    if entry["status"] in SPEC_LOCKED and plan:
        warnings.append(
            f"{fid} is '{entry['status']}'. These count as blockers from now on: fdw-handoff will "
            f"refuse to bundle while a critical one is open.")

    stamp = today()
    added: list[str] = []
    for question in plan:
        minted = question_record(fid, question, stamp, source, record)
        record.setdefault("questions", []).append(minted)
        counts = entry.setdefault("open_questions", {"critical": 0, "non-critical": 0})
        counts[minted["criticality"]] = counts.get(minted["criticality"], 0) + 1
        added.append(minted["id"])

    if added:
        record["updated"] = entry["updated"] = stamp
        write_json_atomic(fdir / "feature.json", record)
        write_json_atomic(paths["registry"], registry)
        for question, qid in zip(plan, added):
            append_md(
                paths["decisions"],
                f"- {stamp} · event · {qid} raised ({question['criticality']}, {question['owner']}): "
                f"{question['text']} · source: {source}",
            )

    emit({"feature": fid, "added": added, "already_present": already,
          "open_questions": entry.get("open_questions"), "warnings": warnings})


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


# ---------------------------------------------------------------- phases


TERMINAL = {"handed-off", "shipped"}


def _phase_file(root: Path, phase: str) -> Path:
    return store(root)["phases"] / phase / "phase.json"


def _phase_features(registry: dict[str, Any], phase: str) -> list[dict[str, Any]]:
    return [f for f in registry.get("features", []) if f["phase"] == phase]


def _all_open(root: Path, features: list[dict[str, Any]]) -> list[str]:
    out = []
    for feature in features:
        record = read_json(_feature_dir(root, feature) / "feature.json", {})
        out += [q["id"] for q in record.get("questions", [])
                if q.get("status", "open") == "open"]
    return out


def _critical_open(root: Path, features: list[dict[str, Any]]) -> list[str]:
    out = []
    for feature in features:
        record = read_json(_feature_dir(root, feature) / "feature.json", {})
        out += [
            q["id"] for q in record.get("questions", [])
            if q.get("status", "open") == "open" and q.get("criticality") == "critical"
        ]
    return out


def cmd_phase_open(args: argparse.Namespace) -> None:
    """Open a phase, carrying forward everything the previous one did not finish. A phase that
    starts blank has thrown away the reason half its scope exists."""
    root = Path(args.root).resolve()
    paths = store(root)
    registry = read_json(paths["registry"], empty_registry())
    if _phase_file(root, args.phase).exists():
        die([f"Phase '{args.phase}' already exists at phases/{args.phase}/phase.json."])

    stamp = today()
    carried: dict[str, Any] = {"from": args.from_phase, "questions": [], "features": [], "changes": []}
    if args.from_phase:
        prior = _phase_file(root, args.from_phase)
        if not prior.exists():
            die([f"No phase '{args.from_phase}' to carry from. Known: {registry.get('phases', [])}"])
        for feature in _phase_features(registry, args.from_phase):
            fdir = _feature_dir(root, feature)
            record = read_json(fdir / "feature.json", {})
            carried["questions"] += [
                {"id": q["id"], "feature": feature["id"], "criticality": q.get("criticality"),
                 "owner": q.get("owner"), "text": q.get("text", "")}
                for q in record.get("questions", []) if q.get("status", "open") == "open"
            ]
            if "deferred" in feature.get("flags", []):
                carried["features"].append({"id": feature["id"], "title": feature["title"]})
            changes = fdir / "changes.md"
            if changes.exists() and "resolution: OPEN" in changes.read_text(encoding="utf-8"):
                carried["changes"].append(feature["id"])

    (paths["phases"] / args.phase / "features").mkdir(parents=True, exist_ok=True)
    write_json_atomic(_phase_file(root, args.phase), {
        "contract_version": CONTRACT_VERSION,
        "phase": args.phase, "status": "open", "opened": stamp, "closed": None,
        "exit_criteria": args.exit_criterion or [],
        "features": [], "carried_over": carried,
        "blocker_count_at_handoff": None, "prd_path": None,
    })
    if args.phase not in registry.setdefault("phases", []):
        registry["phases"] = sort_phases(registry["phases"] + [args.phase])
    if not args.keep_current:
        registry["current_phase"] = args.phase
    write_json_atomic(paths["registry"], registry)
    append_md(paths["decisions"],
              f"- {stamp} · event · opened {args.phase}"
              + (f", carrying {len(carried['questions'])} open question(s) and "
                 f"{len(carried['features'])} deferred feature(s) from {args.from_phase}"
                 if args.from_phase else ""))
    emit({"phase": args.phase, "current_phase": registry["current_phase"], "carried_over": carried})


def cmd_phase_move(args: argparse.Namespace) -> None:
    """Move a feature to another phase. The id and everything under it travel with it —
    continuity of id across phases is what keeps state consistent."""
    root = Path(args.root).resolve()
    paths = store(root)
    registry = read_json(paths["registry"], empty_registry())
    entry = next((f for f in registry.get("features", []) if f["id"] == args.id), None)
    if entry is None:
        die([f"No feature '{args.id}'. Known: {[f['id'] for f in registry.get('features', [])]}"])
    if not _phase_file(root, args.to).exists():
        die([f"No phase '{args.to}'. Open it first: fdw_state.py phase-open --root {root} --phase {args.to}"])
    if entry["phase"] == args.to:
        emit({"id": args.id, "phase": args.to, "moved": False, "note": "already there"})
        return

    order = registry.get("phases", [])
    here, there = phase_key(entry["phase"]), phase_key(args.to)
    by_id = {f["id"]: f for f in registry["features"]}
    violations = []
    for dep in entry.get("depends_on", []):
        target = by_id.get(dep)
        if target and phase_key(target["phase"]) > there:
            violations.append(f"{args.id} depends on {dep} in {target['phase']}, which would then ship later.")
    for other in registry["features"]:
        if args.id in other.get("depends_on", []):
            if phase_key(other["phase"]) < there:
                violations.append(f"{other['id']} in {other['phase']} depends on {args.id}, which would then ship later.")
    if violations and not args.force:
        die(violations + ["Move the dependency too, drop the edge, or pass --force to accept the break."])

    src_phase = entry["phase"]
    src = _feature_dir(root, entry)
    entry["phase"] = args.to
    dst = _feature_dir(root, entry)
    if src.exists():
        dst.parent.mkdir(parents=True, exist_ok=True)
        if dst.exists():
            die([f"{dst} already exists; refusing to overwrite."])
        src.rename(dst)

    record = read_json(dst / "feature.json", {})
    if record:
        record["phase"] = args.to
        record["updated"] = today()
        write_json_atomic(dst / "feature.json", record)

    flags = entry.setdefault("flags", [])
    if there > here and "deferred" not in flags:
        flags.append("deferred")
    elif there < here and "deferred" in flags:
        flags.remove("deferred")
    if record:
        record["flags"] = list(flags)
        write_json_atomic(dst / "feature.json", record)
    entry["updated"] = today()

    for phase in {p for p in (src_phase, args.to) if p}:
        pf = _phase_file(root, phase)
        precord = read_json(pf, None)
        if precord is None:
            continue
        members = [f["id"] for f in _phase_features(registry, phase)]
        precord["features"] = members
        write_json_atomic(pf, precord)

    write_json_atomic(paths["registry"], registry)
    append_md(paths["decisions"],
              f"- {today()} · decision · {args.id} moved to {args.to} · {args.reason or 'no reason given'}")
    emit({"id": args.id, "phase": args.to, "moved": True, "flags": flags,
          "violations_accepted": violations if args.force else []})


def cmd_phase_close(args: argparse.Namespace) -> None:
    """Close a phase and record what it cost. blocker_count_at_handoff is the module's own
    evaluation metric, so it is captured here rather than reconstructed later."""
    root = Path(args.root).resolve()
    paths = store(root)
    registry = read_json(paths["registry"], empty_registry())
    pf = _phase_file(root, args.phase)
    record = read_json(pf)
    if record is None:
        die([f"No phase '{args.phase}'. Known: {registry.get('phases', [])}"])
    if record.get("status") == "closed":
        die([f"Phase '{args.phase}' is already closed ({record.get('closed')})."])

    members = _phase_features(registry, args.phase)
    unfinished = [
        f["id"] for f in members
        if f["status"] not in TERMINAL and not ({"deferred", "dropped"} & set(f.get("flags", [])))
    ]
    if unfinished and not args.force:
        die([
            f"Phase '{args.phase}' still has {len(unfinished)} unfinished feature(s): {', '.join(unfinished)}.",
            "Hand them off, defer them to a later phase, drop them, or pass --force to close anyway.",
        ])

    blockers = _critical_open(root, members)
    stamp = today()
    record.update({
        "status": "closed", "closed": stamp,
        "features": [f["id"] for f in members],
        "blocker_count_at_handoff": len(blockers),
        "blockers_at_handoff": blockers,
        # Critical-only, deliberately: earlier phases recorded their score under that definition
        # and redefining it would destroy the only cross-phase trend the module has. The wider
        # count sits beside it so future trends can have both.
        "open_question_count_at_handoff": len(_all_open(root, members)),
    })
    if args.prd_path:
        record["prd_path"] = args.prd_path
    write_json_atomic(pf, record)
    append_md(paths["decisions"],
              f"- {stamp} · event · closed {args.phase} with {len(members)} feature(s) and "
              f"{len(blockers)} unresolved critical blocker(s)"
              + (f"; forced past {len(unfinished)} unfinished" if unfinished else ""))
    emit({"phase": args.phase, "closed": stamp, "features": len(members),
          "blocker_count_at_handoff": len(blockers), "blockers": blockers,
          "forced_past": unfinished if args.force else []})


def cmd_as_built_seed(args: argparse.Namespace) -> None:
    """Record what a brownfield project already shipped, before this module was installed.

    The content is the BA's — summarised from a prior PRD, a handover note, or dictated.
    This command only files it, and refuses to overwrite a baseline that already has
    substance, because as-built.md is what later phases are specced against."""
    root = Path(args.root).resolve()
    paths = store(root)
    if not paths["registry"].exists():
        die([f"No store at {root}. Run: fdw_state.py init --root {root}"])

    if args.file:
        source_file = Path(args.file).resolve()
        if not source_file.exists():
            die([f"No such file: {source_file}"])
        content = source_file.read_text(encoding="utf-8").strip()
    else:
        content = (args.text or "").strip()
    if not content:
        die(["Nothing to record. Pass --file <markdown> or --text \"...\"."])

    path = paths["as_built"]
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    body = existing.split("_Nothing shipped yet._")[-1].strip() if existing else ""
    if body and not args.force:
        die([
            "as-built.md already describes shipped work. Seeding is for a store that has none.",
            "Pass --force only if you mean to prepend another baseline section.",
        ])

    stamp = today()
    header = "# As-Built Baseline\n\nWhat has actually shipped. Refreshed by fdw-handoff at each phase close.\n"
    section = [
        f"## Before {args.phase}" if args.phase else "## Before this module",
        "",
        f"_Recorded at setup on {stamp}"
        + (f" from {args.source}" if args.source else " from the BA")
        + ". Not produced by this module — treat it as context, not as verified requirements._",
        "",
        content,
        "",
    ]
    _write_atomic(path, header + "\n" + "\n".join(section) + (("\n" + body) if body else ""))
    append_md(
        paths["decisions"],
        f"- {stamp} · event · seeded as-built baseline for work delivered before "
        f"{args.phase or 'this module'} · source: {args.source or 'BA'}",
    )
    emit({"as_built": str(path.relative_to(root)), "phase": args.phase,
          "chars": len(content), "source": args.source})


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
    p.add_argument("--overlaps", action="append", dest="overlaps", help="record a symmetric overlap edge")
    p.add_argument("--note", default=None, help="one line for decisions.md")
    p.add_argument("--by", default=None, help="which skill made the change")
    p.add_argument("--force", action="store_true", help="allow a forward move that skips a gate; logged as an override")
    p.set_defaults(func=cmd_feature_set)

    p = sub.add_parser("question-add", help="raise questions found outside an ingest run")
    p.add_argument("--root", required=True)
    p.add_argument("--id", default=None, help="feature id; may also come from the batch file")
    p.add_argument("--from", dest="from_file", default=None,
                   help="batch JSON: {feature, source, questions:[{id?,text,criticality,owner}]}")
    p.add_argument("--text", default=None)
    p.add_argument("--criticality", default=None, choices=CRITICALITY)
    p.add_argument("--owner", default=None, choices=OWNERS)
    p.add_argument("--question-id", dest="question_id", default=None,
                   help="supply the id to make a re-run a no-op instead of a second copy")
    p.add_argument("--source", default=None,
                   help="where it came from, e.g. 'spec F-001 open questions'")
    p.add_argument("--allow-duplicate", dest="allow_duplicate", action="store_true",
                   help="add even though an open question has the same wording")
    p.set_defaults(func=cmd_question_add)

    p = sub.add_parser("question-close", help="close one question from client feedback or sign-off")
    p.add_argument("--root", required=True)
    p.add_argument("--question-id", required=True, dest="question_id")
    p.add_argument("--answer", required=True)
    p.add_argument("--source", required=True, help="where the answer came from, e.g. a packet id or 'client email 2026-08-25'")
    p.add_argument("--quote", default=None, help="the client's own words, when you have them")
    p.set_defaults(func=cmd_question_close)

    p = sub.add_parser("phase-open", help="open a phase, carrying forward what the last one did not finish")
    p.add_argument("--root", required=True)
    p.add_argument("--phase", required=True)
    p.add_argument("--from", dest="from_phase", default=None, help="phase to carry over from")
    p.add_argument("--exit-criterion", action="append", dest="exit_criterion")
    p.add_argument("--keep-current", action="store_true", help="open it without making it the current phase")
    p.set_defaults(func=cmd_phase_open)

    p = sub.add_parser("phase-move", help="move a feature to another phase, id and history intact")
    p.add_argument("--root", required=True)
    p.add_argument("--id", required=True)
    p.add_argument("--to", required=True)
    p.add_argument("--reason", default=None)
    p.add_argument("--force", action="store_true", help="accept a dependency break")
    p.set_defaults(func=cmd_phase_move)

    p = sub.add_parser("phase-close", help="close a phase and record its blocker count")
    p.add_argument("--root", required=True)
    p.add_argument("--phase", required=True)
    p.add_argument("--prd-path", default=None, dest="prd_path")
    p.add_argument("--force", action="store_true", help="close with unfinished features")
    p.set_defaults(func=cmd_phase_close)

    p = sub.add_parser("as-built-seed", help="record what a brownfield project shipped before this module")
    p.add_argument("--root", required=True)
    p.add_argument("--file", default=None, help="markdown file describing what already exists")
    p.add_argument("--text", default=None, help="the description inline, instead of --file")
    p.add_argument("--phase", default=None, help="the phase this module is starting at")
    p.add_argument("--source", default=None, help="where the description came from, e.g. a prior PRD path")
    p.add_argument("--force", action="store_true", help="prepend even though a baseline already exists")
    p.set_defaults(func=cmd_as_built_seed)

    p = sub.add_parser("validate", help="check the registry and the feature folders still agree")
    p.add_argument("--root", required=True)
    p.set_defaults(func=cmd_validate)

    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
