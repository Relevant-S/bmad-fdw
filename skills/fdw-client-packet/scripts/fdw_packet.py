#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Builds the client review packet: gathers what the client needs to see, then renders it —
refusing to render if internal vocabulary leaked into a document a paying client will read.

Writing the client-facing prose is judgment and stays in the prompt. This script assembles the
inputs, enforces the vocabulary rule, and renders a self-contained page.
"""

from __future__ import annotations

import argparse
import base64
import html
import json
import mimetypes
import re
import sys
from datetime import date
from pathlib import Path
from typing import Any

# Vocabulary that must never reach a client. Each pattern carries the plain-language
# replacement to reach for, because "don't use jargon" is not actionable at 11pm.
FORBIDDEN: list[tuple[str, str, str]] = [
    (r"\bF-\d{3}\b", "feature id", "name the feature in words"),
    (r"\b[AGS]\d+\b", "internal reference id", "say the thing itself, not its id"),
    (r"\bFR-?\d+\b", "requirement id", "describe the requirement in a sentence"),
    (r"\bfdw-[a-z-]+\b", "internal tool name", "remove it — the client does not run our tooling"),
    (r"\bphase-\d[\d.]*\b", "internal phase label", "say 'this stage of the work' or name the date"),
    (r"\b(?:XS|XL|[SML])\s*(?:-|–)?\s*(?:size|effort|t-shirt)\b", "effort sizing", "remove it — sizing is ours, not theirs"),
    (r"\b(?:spec|specced|elaboration doc|backlog|sprint|epic|user stor(?:y|ies))\b", "delivery jargon", "say what it means for them"),
    (r"\b(?:registry|handoff|discovery store|signal\.md|ux-notes)\b", "internal artifact", "remove it"),
    (r"\bstory points?\b", "estimation jargon", "remove it"),
    (r"\bnon-critical\b|\bcriticality\b", "internal triage vocabulary", "say 'when you have a moment' or 'we need this to proceed'"),
    (r"\bunconfirmed\b", "internal assumption status", "phrase it as a question to them"),
]

REQUIRED = ("headline", "intro", "sections", "next_steps")


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


def slugify(text: str, limit: int = 48) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return (slug[:limit].rstrip("-")) or "feature"


def locate(root: Path, feature_id: str) -> tuple[Path, dict[str, Any]]:
    registry = read_json(root / "registry.json")
    if registry is None:
        die([f"No discovery store at {root}. Run fdw-intake first."])
    entry = next((f for f in registry.get("features", []) if f["id"] == feature_id), None)
    if entry is None:
        die([f"No feature '{feature_id}'. Known: {[f['id'] for f in registry.get('features', [])]}"])
    return root / "phases" / entry["phase"] / "features" / f"{entry['id']}-{entry['slug']}", entry


# ---------------------------------------------------------------- gather


def cmd_gather(args: argparse.Namespace) -> None:
    root = Path(args.root).resolve()
    fdir, entry = locate(root, args.id)
    record = read_json(fdir / "feature.json", {})
    design = fdir / "design"

    screens: list[str] = []
    assumptions: list[dict[str, str]] = []
    corrections: list[str] = []
    notes = design / "ux-notes.md"
    if notes.exists():
        text = notes.read_text(encoding="utf-8")
        screens = [
            f"{sid} — {title.strip()}"
            for sid, title in re.findall(r"^\s*-\s+\*\*(S\d+)\s+—\s+([^*]+?)\*\*", text, re.M)
        ]
        for match in re.finditer(r"^\s*-\s+\*\*(A\d+)\*\*\s*(?:\(([^)]*)\))?\s*—\s*(.+)$", text, re.M):
            aid, screen, body = match.group(1), match.group(2) or "", match.group(3)
            status = "unconfirmed"
            if "_Status:" in body:
                body, _, tail = body.partition("_Status:")
                status = tail.strip(" _.").lower() or status
            assumptions.append({"id": aid, "screen": screen, "text": body.strip(" ._"), "status": status})
        corrections = re.findall(r"^\s*-\s+(\d{4}-\d{2}-\d{2}\s+—\s+.+)$", text, re.M)

    gaps: list[str] = []
    empty = design / "empty-state.md"
    if empty.exists():
        gaps = [
            f"{gid} — {body.strip()}"
            for gid, body in re.findall(r"^\s*-\s+\*\*(G\d+)\*\*[^—]*—\s*(.+)$", empty.read_text(encoding="utf-8"), re.M)
        ]

    proto = design / "prototype"
    prototype_files = sorted(str(p.relative_to(fdir)) for p in proto.rglob("*") if p.is_file()) if proto.is_dir() else []

    client_questions = [
        {"id": q["id"], "text": q["text"], "criticality": q.get("criticality", "critical")}
        for q in record.get("questions", [])
        if q.get("status", "open") == "open" and q.get("owner") == "client"
    ]

    packets_dir = root / "phases" / entry["phase"] / "client-packets"
    prior = sorted(p.name for p in packets_dir.glob("*.html")) if packets_dir.is_dir() else []

    unconfirmed = [a for a in assumptions if a["status"] == "unconfirmed"]
    problems = []
    if not prototype_files:
        problems.append(f"{entry['id']}: no prototype to show. Run fdw-design before building a packet.")
    if entry["status"] not in {"client-review", "design-approved", "designing"}:
        problems.append(
            f"{entry['id']}: status is '{entry['status']}'. A packet is what you send at client-review; "
            f"run fdw-design's check and advance the feature first."
        )
    if problems:
        die(problems, feature=entry["id"], status=entry["status"])

    emit(
        {
            "feature": entry["id"],
            "title": entry["title"],
            "phase": entry["phase"],
            "status": entry["status"],
            "summary": record.get("summary", ""),
            "screens": screens,
            "assumptions": assumptions,
            "unconfirmed_assumptions": len(unconfirmed),
            "corrections": corrections,
            "empty_state_gaps": gaps,
            "client_questions": client_questions,
            "prototype_files": prototype_files,
            "prior_packets": prior,
            "packets_dir": str(packets_dir.relative_to(root)),
        }
    )


# ---------------------------------------------------------------- vocabulary gate


def scan_vocabulary(content: dict[str, Any]) -> list[str]:
    """Walk every string that will be rendered and report internal vocabulary. Keys that are
    never rendered are exempt: `ref` carries question ids into the sidecar map, and `_`-prefixed
    keys are authoring notes."""
    problems: list[str] = []

    def walk(node: Any, path: str) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key == "ref" or key.startswith("_"):
                    continue
                walk(value, f"{path}.{key}" if path else key)
        elif isinstance(node, list):
            for i, value in enumerate(node):
                walk(value, f"{path}[{i}]")
        elif isinstance(node, str):
            for pattern, label, fix in FORBIDDEN:
                for hit in re.findall(pattern, node, re.I):
                    text = hit if isinstance(hit, str) else hit[0]
                    problems.append(
                        f"{path}: '{text}' is {label} and must not reach a client — {fix}."
                    )

    walk(content, "")
    return problems


def cmd_render(args: argparse.Namespace) -> None:
    root = Path(args.root).resolve()
    fdir, entry = locate(root, args.id)
    content = read_json(Path(args.content).resolve())
    if content is None:
        die([f"No packet content at {args.content}."])

    missing = [f for f in REQUIRED if not content.get(f)]
    if missing:
        die([f"Packet content is missing {missing}. See assets/packet.example.json for the shape."])

    problems = scan_vocabulary(content)
    if problems and not args.allow_jargon:
        die(
            problems + [
                "This document goes to a paying client. Rewrite the flagged text in their language; "
                "--allow-jargon exists only for an internal preview."
            ],
            leaked=len(problems),
        )

    images: dict[str, str] = {}
    for shot in (read_json(Path(args.shots).resolve(), {}) or {}).get("shots", []) if args.shots else []:
        file = Path(shot["file"])
        if not file.exists():
            die([f"The capture manifest names {file}, which is not there. Re-run fdw_capture.py shots."])
        mime = mimetypes.guess_type(file.name)[0] or "image/png"
        encoded = f"data:{mime};base64," + base64.b64encode(file.read_bytes()).decode()
        # Keyed by the client-facing title the BA wrote and by the screen id, so the content JSON
        # can use either without the BA hand-matching filenames to sections.
        images[shot.get("title") or shot["screen"]] = encoded
        images[shot["screen"]] = encoded
    for pair in args.screenshot or []:
        label, _, path = pair.partition("=")
        file = Path(path).expanduser().resolve()
        if not file.exists():
            die([f"Screenshot not found: {file}"])
        mime = mimetypes.guess_type(file.name)[0] or "image/png"
        images[label.strip()] = f"data:{mime};base64," + base64.b64encode(file.read_bytes()).decode()

    stamp = args.date or date.today().isoformat()
    slug = slugify(content.get("headline") or entry["title"])
    out_dir = root / "phases" / entry["phase"] / "client-packets"
    out_dir.mkdir(parents=True, exist_ok=True)
    page = out_dir / f"{stamp}-{slug}.html"

    # Opaque per-packet tokens. The client's reply travels labelled q1/a1, so answers come back
    # bound to the question that was asked without a single internal id ever leaving the building.
    tokens: dict[str, dict[str, Any]] = {}
    for i, item in enumerate(content.get("questions", []), 1):
        tokens[f"q{i}"] = {"kind": "question", "ref": item.get("ref"), "asked": item.get("question")}
    for i, item in enumerate(content.get("assumptions", []), 1):
        tokens[f"a{i}"] = {"kind": "assumption", "we_assumed": item.get("we_assumed")}

    page.write_text(render(content, images, stamp, args.client, page.name, not args.no_reply),
                    encoding="utf-8")

    # Question ids must map answers back to features but must never appear in the packet.
    mapping = {
        "feature": entry["id"],
        "packet": page.name,
        "date": stamp,
        "reply_enabled": not args.no_reply,
        "tokens": tokens,
        "questions": [
            {"ref": q.get("ref"), "asked": q.get("question")}
            for q in content.get("questions", [])
            if q.get("ref")
        ],
    }
    map_file = out_dir / f"{stamp}-{slug}.map.json"
    map_file.write_text(json.dumps(mapping, indent=2, ensure_ascii=False), encoding="utf-8")

    emit(
        {
            "feature": entry["id"],
            "packet": str(page.relative_to(root)),
            "map": str(map_file.relative_to(root)),
            "questions_asked": len(mapping["questions"]),
            "screenshots": len({v for v in images.values()}),
            "reply_enabled": not args.no_reply,
            "jargon_allowed": bool(args.allow_jargon),
            "send": "The .map.json is internal — send the .html only.",
        }
    )


# ---------------------------------------------------------------- render


def esc(text: Any) -> str:
    return html.escape(str(text if text is not None else ""))


CSS = """
*{box-sizing:border-box}
:root{--bg:#fbfbf9;--panel:#fff;--ink:#1c1c19;--muted:#6a6a62;--line:#e4e4dd;--accent:#2f5d8a;--soft:#f0f0ea}
@media(prefers-color-scheme:dark){:root{--bg:#17181b;--panel:#1f2126;--ink:#eaeae5;--muted:#9b9b93;--line:#32353b;--accent:#82abd6;--soft:#272a2f}}
body{margin:0;padding:28px 20px;background:var(--bg);color:var(--ink);
 font:16px/1.65 ui-serif,Georgia,'Times New Roman',serif}
.wrap{max-width:760px;margin:0 auto}
h1{font-size:27px;line-height:1.25;margin:0 0 6px}
.meta{color:var(--muted);font-size:14px;margin-bottom:26px;
 font-family:ui-sans-serif,-apple-system,'Segoe UI',sans-serif}
.intro{font-size:18px;line-height:1.6}
h2{font-size:13px;text-transform:uppercase;letter-spacing:.09em;color:var(--muted);
 margin:34px 0 12px;font-weight:600;font-family:ui-sans-serif,-apple-system,sans-serif}
.screen{background:var(--panel);border:1px solid var(--line);border-radius:10px;
 padding:18px 20px;margin-bottom:14px}
.screen h3{margin:0 0 8px;font-size:19px}
.screen p{margin:0 0 10px}
.screen p:last-child{margin-bottom:0}
.label{font-family:ui-sans-serif,-apple-system,sans-serif;font-size:12px;
 text-transform:uppercase;letter-spacing:.06em;color:var(--muted);margin-bottom:2px}
img{max-width:100%;border-radius:7px;border:1px solid var(--line);margin:12px 0 4px;display:block}
ol,ul{padding-left:22px}
li{margin-bottom:11px}
.ask{background:var(--soft);border-left:3px solid var(--accent);border-radius:0 8px 8px 0;
 padding:14px 18px;margin-bottom:12px}
.ask .q{font-weight:600}
.ask .c{color:var(--muted);font-size:15px;margin-top:5px}
.assume{border-bottom:1px solid var(--line);padding:12px 0}
.assume:last-child{border-bottom:none}
.assume .w{color:var(--muted);font-size:15px;margin-top:4px}
.next{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:18px 20px;margin-top:12px}
footer{margin-top:36px;padding-top:16px;border-top:1px solid var(--line);
 color:var(--muted);font-size:13px;font-family:ui-sans-serif,sans-serif}
@media(max-width:600px){body{padding:18px 14px}h1{font-size:23px}.intro{font-size:17px}}
.reply{font-family:ui-sans-serif,-apple-system,'Segoe UI',sans-serif;font-size:15px;margin-top:10px}
.reply label{display:inline-flex;align-items:center;gap:6px;margin-right:16px;cursor:pointer}
.reply textarea,.reply input[type=text]{width:100%;font:inherit;color:inherit;background:var(--bg);
 border:1px solid var(--line);border-radius:7px;padding:9px 11px;margin-top:7px}
.reply textarea{min-height:74px;resize:vertical}
.send{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:18px 20px;margin-top:14px;
 font-family:ui-sans-serif,-apple-system,sans-serif}
.send h3{margin:0 0 8px;font-size:18px}
button{font:inherit;font-family:ui-sans-serif,-apple-system,sans-serif;background:var(--accent);color:#fff;
 border:0;border-radius:8px;padding:11px 18px;cursor:pointer;margin:4px 8px 4px 0}
button.ghost{background:transparent;color:var(--accent);border:1px solid var(--accent)}
#fdw-out{display:none;margin-top:14px}
#fdw-out textarea{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:12px;min-height:120px;
 word-break:break-all}
#fdw-summary{white-space:pre-wrap;background:var(--soft);border-radius:8px;padding:12px 14px;margin-top:10px;
 font-size:14px}
.saved{color:var(--muted);font-size:13px;margin-left:4px}
"""

REPLY_JS = r"""
(function(){
 var key='fdw-reply:'+PACKET, form=document.getElementById('fdw-form');
 if(!form) return;
 function fields(){return form.querySelectorAll('[data-token],[data-field]');}
 function load(){
  try{var saved=JSON.parse(localStorage.getItem(key)||'{}');
   fields().forEach(function(el){
    var k=el.dataset.token?el.dataset.token+':'+(el.dataset.part||'text'):el.dataset.field;
    if(saved[k]===undefined) return;
    if(el.type==='radio') el.checked=(el.value===saved[k]); else el.value=saved[k];
   });}catch(e){}
 }
 function save(){
  var out={};
  fields().forEach(function(el){
   var k=el.dataset.token?el.dataset.token+':'+(el.dataset.part||'text'):el.dataset.field;
   if(el.type==='radio'){ if(el.checked) out[k]=el.value; } else if(el.value) out[k]=el.value;
  });
  try{localStorage.setItem(key,JSON.stringify(out));}catch(e){}
  var note=document.getElementById('fdw-saved');
  if(note){note.textContent='Saved on this device';}
 }
 form.addEventListener('input',save); form.addEventListener('change',save); load();

 function collect(){
  var answers={};
  fields().forEach(function(el){
   if(!el.dataset.token) return;
   if(el.type==='radio' && !el.checked) return;
   if(!el.value) return;
   var slot=answers[el.dataset.token]||(answers[el.dataset.token]={});
   slot[el.dataset.part||'text']=el.value;
  });
  var f={};
  fields().forEach(function(el){ if(el.dataset.field && el.value && (el.type!=='radio'||el.checked)) f[el.dataset.field]=el.value; });
  return {v:1,packet:PACKET,from:f.name||'',at:new Date().toISOString().slice(0,10),
          approve:f.approve||'',other:f.other||'',answers:answers};
 }
 function encode(o){return 'FDW1:'+btoa(unescape(encodeURIComponent(JSON.stringify(o))));}
 function readable(o){
  var lines=['From: '+(o.from||'(no name given)'),'Date: '+o.at,
             'Are the screens right? '+(o.approve==='yes'?'Yes, go ahead':(o.approve==='not-yet'?'Not yet':'(not answered)'))];
  LABELS.forEach(function(l){
   var a=o.answers[l.token]; if(!a) return;
   lines.push('');lines.push(l.label);
   if(a.verdict) lines.push('  '+(a.verdict==='agree'?'Agreed':'Not quite'));
   if(a.text) lines.push('  '+a.text);
  });
  if(o.other){lines.push('');lines.push('Anything else');lines.push('  '+o.other);}
  return lines.join('\n');
 }
 document.getElementById('fdw-finish').addEventListener('click',function(){
  var data=collect(), box=document.getElementById('fdw-out');
  document.getElementById('fdw-blob').value=encode(data);
  document.getElementById('fdw-summary').textContent=readable(data);
  box.style.display='block'; box.scrollIntoView({behavior:'smooth',block:'start'});
 });
 document.getElementById('fdw-copy').addEventListener('click',function(){
  var t=document.getElementById('fdw-blob'); t.select(); t.setSelectionRange(0,99999);
  try{document.execCommand('copy');}catch(e){}
  if(navigator.clipboard) navigator.clipboard.writeText(t.value);
  this.textContent='Copied — now paste it into your reply';
 });
 document.getElementById('fdw-download').addEventListener('click',function(){
  var blob=new Blob([document.getElementById('fdw-blob').value],{type:'text/plain'});
  var a=document.createElement('a'); a.href=URL.createObjectURL(blob);
  a.download=PACKET.replace(/\.html$/,'')+'-reply.txt'; a.click();
 });
})();
"""


def render(content: dict[str, Any], images: dict[str, str], stamp: str, client: str | None,
           packet_name: str = "", reply: bool = True) -> str:
    out = [
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>",
        "<meta name='viewport' content='width=device-width,initial-scale=1'>",
        f"<title>{esc(content['headline'])}</title><style>{CSS}</style></head><body>"
        f"<div class='wrap' id='fdw-form'>",
        f"<h1>{esc(content['headline'])}</h1>",
        f"<div class='meta'>{esc(client) + ' · ' if client else ''}{esc(stamp)}</div>",
        f"<div class='intro'>{esc(content['intro'])}</div>",
    ]

    if content.get("sections"):
        out.append("<h2>What we're proposing</h2>")
        for section in content["sections"]:
            out.append("<div class='screen'>")
            out.append(f"<h3>{esc(section.get('screen', ''))}</h3>")
            if section.get("screen") in images:
                out.append(f"<img alt='{esc(section['screen'])}' src='{images[section['screen']]}'>")
            if section.get("what_you_see"):
                out.append(f"<div class='label'>What you see</div><p>{esc(section['what_you_see'])}</p>")
            if section.get("how_it_works"):
                out.append(f"<div class='label'>How it works</div><p>{esc(section['how_it_works'])}</p>")
            out.append("</div>")

    labels: list[dict[str, str]] = []
    if content.get("assumptions"):
        out.append("<h2>Things we've assumed — please confirm</h2>")
        for i, item in enumerate(content["assumptions"], 1):
            token = f"a{i}"
            out.append(
                f"<div class='assume'><div>{esc(item.get('we_assumed', ''))}</div>"
                + (f"<div class='w'>{esc(item['why_it_matters'])}</div>" if item.get("why_it_matters") else "")
            )
            if reply:
                labels.append({"token": token, "label": f"We assumed: {item.get('we_assumed', '')}"})
                out.append(
                    f"<div class='reply'>"
                    f"<label><input type='radio' name='{token}' value='agree' data-token='{token}' "
                    f"data-part='verdict'> That's right</label>"
                    f"<label><input type='radio' name='{token}' value='disagree' data-token='{token}' "
                    f"data-part='verdict'> Not quite</label>"
                    f"<textarea data-token='{token}' data-part='text' "
                    f"placeholder='If not quite, what should it be?'></textarea></div>")
            out.append("</div>")

    if content.get("questions"):
        out.append("<h2>What we need from you</h2>")
        for i, item in enumerate(content["questions"], 1):
            token = f"q{i}"
            out.append(
                f"<div class='ask'><div class='q'>{i}. {esc(item.get('question', ''))}</div>"
                + (f"<div class='c'>{esc(item['context'])}</div>" if item.get("context") else "")
            )
            if reply:
                labels.append({"token": token, "label": f"Q{i}. {item.get('question', '')}"})
                out.append(
                    f"<div class='reply'><textarea data-token='{token}' data-part='text' "
                    f"placeholder='Your answer'></textarea></div>")
            out.append("</div>")

    out.append(f"<h2>Next steps</h2><div class='next'>{esc(content['next_steps'])}</div>")

    if reply:
        out.append(
            "<h2>Send us your answers</h2>"
            "<div class='send'>"
            "<div class='reply'>"
            "<div>Your name <span id='fdw-saved' class='saved'></span></div>"
            "<input type='text' data-field='name' placeholder='So we know who said what'>"
            "<div style='margin-top:14px'>Anything else we should know?</div>"
            "<textarea data-field='other' placeholder='Anything at all — however small'></textarea>"
            "<div style='margin-top:14px'>Are these screens right?</div>"
            "<label><input type='radio' name='fdw-approve' value='yes' data-field='approve'> "
            "Yes, go ahead</label>"
            "<label><input type='radio' name='fdw-approve' value='not-yet' data-field='approve'> "
            "Not yet</label>"
            "</div>"
            "<div style='margin-top:16px'>"
            "<button type='button' id='fdw-finish'>Finish and prepare my reply</button></div>"
            "<div id='fdw-out'>"
            "<h3>Two ways to send it</h3>"
            "<p>Copy the block below and paste it into your reply — that's all we need. "
            "Or download it and attach it.</p>"
            "<textarea id='fdw-blob' readonly></textarea>"
            "<div><button type='button' id='fdw-copy'>Copy</button>"
            "<button type='button' class='ghost' id='fdw-download'>Download instead</button></div>"
            "<h3 style='margin-top:18px'>What you're sending</h3>"
            "<div id='fdw-summary'></div>"
            "</div></div>"
            "<footer style='margin-top:8px'>Your answers stay in this browser until you send them. "
            "Nothing is submitted anywhere on its own. If you'd rather just write us an email, do that "
            "instead — it works just as well.</footer>")
    if content.get("how_to_view"):
        out.append(f"<footer>{esc(content['how_to_view'])}</footer>")
    if reply:
        out.append(
            "</div><script>var PACKET=" + json.dumps(packet_name)
            + ";var LABELS=" + json.dumps(labels, ensure_ascii=False) + ";" + REPLY_JS + "</script></body></html>")
    else:
        out.append("</div></body></html>")
    return "\n".join(out)



# ---------------------------------------------------------------- responses in


def state_cli() -> str:
    """The shared state CLI ships inside fdw-intake, a sibling once installed. Resolve a real
    path so the commands printed below are ones the BA can actually paste."""
    sibling = Path(__file__).resolve().parents[2] / "fdw-intake" / "scripts" / "fdw_state.py"
    return f"uv run {sibling}" if sibling.exists() else \
        "uv run {skill-root}/../fdw-intake/scripts/fdw_state.py"


def parse_response(raw: str) -> dict[str, Any] | None:
    """A reply arrives as the token the packet produced, or as the downloaded file, or pasted
    inside an email with the client's own words wrapped around it. Find it either way."""
    text = raw.strip()
    marker = text.find("FDW1:")
    if marker >= 0:
        # Mail clients wrap lines and the client types around the block, so the end of the
        # payload is not marked by anything reliable. Trim back until it decodes.
        blob = re.sub(r"[^A-Za-z0-9+/=].*$", "", re.sub(r"\s+", "", text[marker + 5:]), flags=re.S)
        for size in range(len(blob), 3, -1):
            chunk = blob[:size]
            try:
                decoded = base64.b64decode(chunk + "=" * (-len(chunk) % 4), validate=False)
                parsed = json.loads(decoded.decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                continue
            if isinstance(parsed, dict):
                return parsed
        return None
    start = text.find("{")
    if start >= 0:
        try:
            return json.loads(text[start:text.rfind("}") + 1])
        except json.JSONDecodeError:
            return None
    return None


def newest_map(out_dir: Path, feature_id: str, packet: str | None) -> Path | None:
    maps = sorted(out_dir.glob("*.map.json"))
    if packet:
        stem = packet[:-5] if packet.endswith(".html") else packet
        maps = [m for m in maps if m.name == f"{stem}.map.json"]
    maps = [m for m in maps if (read_json(m, {}) or {}).get("feature") == feature_id]
    return maps[-1] if maps else None


def cmd_sync(args: argparse.Namespace) -> None:
    root = Path(args.root).resolve()
    fdir, entry = locate(root, args.id)
    out_dir = root / "phases" / entry["phase"] / "client-packets"
    map_file = newest_map(out_dir, entry["id"], args.packet)
    if map_file is None:
        die([f"No packet map for {entry['id']} in {out_dir}. Render the packet before syncing replies."])
    mapping = read_json(map_file, {}) or {}
    tokens = mapping.get("tokens") or {}
    if not tokens:
        die([f"{map_file.name} carries no token map — it was written by an older render. "
             f"Re-render the packet so replies can be matched to the questions that were asked."])

    replies: list[dict[str, Any]] = []
    problems: list[str] = []
    for source in args.response or []:
        raw = sys.stdin.read() if source == "-" else Path(source).expanduser().read_text(encoding="utf-8")
        parsed = parse_response(raw)
        if parsed is None:
            problems.append(f"{source}: no reply found. Expected the block the packet produced "
                            f"(it starts with FDW1:) or the downloaded file.")
            continue
        if parsed.get("packet") and parsed["packet"] != mapping.get("packet"):
            problems.append(f"{source}: this reply is to '{parsed['packet']}', not "
                            f"'{mapping.get('packet')}'. Sync it against the packet it answers.")
            continue
        parsed["_source"] = source
        replies.append(parsed)
    if not replies:
        die(problems or ["No replies to read."], feature=entry["id"])

    # Group every answer by the question it answers, keeping who said it.
    by_token: dict[str, list[dict[str, Any]]] = {}
    for reply in replies:
        who = (reply.get("from") or "").strip() or "unnamed"
        for token, value in (reply.get("answers") or {}).items():
            if token not in tokens:
                problems.append(f"{who}: answered '{token}', which this packet never asked. Ignored.")
                continue
            by_token.setdefault(token, []).append({"from": who, "at": reply.get("at", ""), **value})

    cli, quoted_root = state_cli(), str(root)
    answered: list[dict[str, Any]] = []
    conflicts: list[dict[str, Any]] = []
    corrections: list[dict[str, Any]] = []
    commands: list[str] = []

    for token, meta in tokens.items():
        given = by_token.get(token, [])
        if meta.get("kind") == "assumption":
            verdicts = {g.get("verdict") for g in given if g.get("verdict")}
            if verdicts == {"disagree"} or (len(given) and "disagree" in verdicts):
                corrections.append({
                    "we_assumed": meta.get("we_assumed"),
                    "said_by": [g["from"] for g in given if g.get("verdict") == "disagree"],
                    "instead": [g.get("text", "") for g in given if g.get("verdict") == "disagree"],
                })
            if len(verdicts) > 1:
                conflicts.append({"about": meta.get("we_assumed"),
                                  "answers": [{"from": g["from"], "said": g.get("verdict")} for g in given]})
            continue

        if not given:
            continue
        distinct = {g.get("text", "").strip() for g in given if g.get("text", "").strip()}
        if not distinct:
            continue
        if len(given) > 1 and len(distinct) > 1:
            # Two people said different things. Picking one would invent a client decision.
            conflicts.append({"about": meta.get("asked"),
                              "answers": [{"from": g["from"], "said": g.get("text", "")} for g in given]})
            continue
        speaker = given[0]
        answer = next(iter(distinct))
        answered.append({"ref": meta.get("ref"), "asked": meta.get("asked"),
                         "answer": answer, "from": speaker["from"]})
        if meta.get("ref"):
            commands.append(
                f'{cli} question-close --root {quoted_root} --question-id {meta["ref"]} '
                f'--answer "{answer}" --source "{mapping.get("packet")}" --quote "{answer}"')

    asked = [t for t, meta in tokens.items() if meta.get("kind") == "question"]
    closed = {a["ref"] for a in answered}
    unanswered = [tokens[t].get("asked") for t in asked
                  if tokens[t].get("ref") not in closed and tokens[t].get("ref")]

    approvals = [{"from": (r.get("from") or "unnamed"), "verdict": r.get("approve", ""),
                  "at": r.get("at", "")} for r in replies if r.get("approve")]
    said_yes = [a["from"] for a in approvals if a["verdict"] == "yes"]
    said_not_yet = [a["from"] for a in approvals if a["verdict"] == "not-yet"]

    blockers: list[str] = []
    if unanswered:
        blockers.append(f"{len(unanswered)} of the questions this packet asked are still unanswered.")
    if conflicts:
        blockers.append(f"{len(conflicts)} answers disagree with each other and need one decision.")
    if said_not_yet:
        blockers.append(f"{', '.join(said_not_yet)} said the screens are not right yet.")
    if not said_yes:
        blockers.append("Nobody approved. Silence is not sign-off.")
    if not blockers:
        commands.append(
            f'{cli} feature-set --root {quoted_root} --id {entry["id"]} --status design-approved '
            f'--by fdw-client-packet --note "approved by {", ".join(said_yes)} via {mapping.get("packet")}"')

    # File the raw replies beside the packet. The quote in every question-close has to be
    # traceable to something on disk, or the provenance rule is decoration.
    record = out_dir / f"{map_file.name[:-len('.map.json')]}.responses.json"
    existing = read_json(record, {"packet": mapping.get("packet"), "replies": []}) or {}
    seen = {(r.get("from"), r.get("at")) for r in existing.get("replies", [])}
    for reply in replies:
        if (reply.get("from"), reply.get("at")) not in seen:
            existing.setdefault("replies", []).append(reply)
    record.write_text(json.dumps(existing, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    emit({
        "feature": entry["id"],
        "packet": mapping.get("packet"),
        "responders": [r.get("from") or "unnamed" for r in replies],
        "answered": answered,
        "conflicts": conflicts,
        "corrections": corrections,
        "unanswered": unanswered,
        "approvals": approvals,
        "recorded": str(record.relative_to(root)),
        "problems": problems,
        "blocked_by": blockers,
        "run": commands,
        "then": ("Send the disagreed assumptions back to fdw-design as corrections."
                 if corrections else None),
    })


# ---------------------------------------------------------------- cli


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Build the client review packet")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("gather", help="everything the packet is written from")
    p.add_argument("--root", required=True)
    p.add_argument("--id", required=True)
    p.set_defaults(func=cmd_gather)

    p = sub.add_parser("render", help="render the packet, refusing if internal vocabulary leaked")
    p.add_argument("--root", required=True)
    p.add_argument("--id", required=True)
    p.add_argument("--content", required=True, help="packet content JSON; see assets/packet.example.json")
    p.add_argument("--shots", default=None,
                   help="capture manifest from fdw_capture.py shots; the deterministic path")
    p.add_argument("--screenshot", action="append",
                   help="Screen name=path.png, for an image the capture harness cannot produce")
    p.add_argument("--no-reply", action="store_true",
                   help="render without the reply block (a read-only copy, e.g. for an archive)")
    p.add_argument("--client", default=None, help="client name for the header")
    p.add_argument("--date", default=None)
    p.add_argument("--allow-jargon", action="store_true", help="internal preview only; never for a client send")
    p.set_defaults(func=cmd_render)

    p = sub.add_parser("sync", help="read the client's replies back in and say what to run")
    p.add_argument("--root", required=True)
    p.add_argument("--id", required=True)
    p.add_argument("--response", action="append", required=True,
                   help="a reply: a file, or - for stdin. Repeat for each person who answered.")
    p.add_argument("--packet", default=None, help="which packet; defaults to the most recent")
    p.set_defaults(func=cmd_sync)

    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
