#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Screenshots of a feature's prototype, captured the same way on every machine.

The packet is what the client signs, so the pictures in it cannot depend on which browser
automation the BA happens to have installed. This drives whatever Chromium-family browser is
already on the machine over the DevTools protocol — no npm install, no MCP, no third-party
package — and serves the prototype over loopback HTTP first, because file:// resolves relative
assets differently and would quietly produce a different packet.

Which screens get captured is not a judgment call: grounding.json already declares them, and
fdw-design has already refused to let an undeclared one exist.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import secrets
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

VIEWPORT = (1280, 900)
SCALE = 2
SETTLE_MS = 350
NAV_TIMEOUT = 20.0

BROWSER_CANDIDATES = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
    "/usr/bin/google-chrome", "/usr/bin/google-chrome-stable", "/usr/bin/chromium",
    "/usr/bin/chromium-browser", "/usr/bin/microsoft-edge", "/snap/bin/chromium",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
]
ON_PATH = ["google-chrome", "google-chrome-stable", "chromium", "chromium-browser",
           "microsoft-edge", "msedge", "brave-browser", "chrome"]

SCREEN_FILE_RE = re.compile(r"^(S\d+)\b")
SCREEN_MARK_RE = re.compile(r"data-screen\s*=\s*[\"'](S\d+)[\"']")
NOTES_SCREEN_RE = re.compile(r"^\s*-\s+\*\*(S\d+)\s+—\s+([^*]+?)\*\*", re.M)


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


# ---------------------------------------------------------------- a minimal CDP client


class WS:
    """Just enough WebSocket to talk to a browser on loopback. Written out rather than taken
    from a package so the capture path has no dependency the BA has to install — the whole
    point of this script."""

    def __init__(self, url: str, timeout: float = 30.0):
        host, _, rest = url[5:].partition("/")
        name, _, port = host.partition(":")
        self.sock = socket.create_connection((name, int(port)), timeout=timeout)
        key = base64.b64encode(secrets.token_bytes(16)).decode()
        self.sock.sendall(
            f"GET /{rest} HTTP/1.1\r\nHost: {host}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n".encode())
        buf = b""
        while b"\r\n\r\n" not in buf:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise IOError("browser closed the DevTools connection during the handshake")
            buf += chunk
        if b"101" not in buf.split(b"\r\n")[0]:
            raise IOError(f"DevTools refused the upgrade: {buf.split(chr(13).encode())[0]!r}")
        self.seq = 0

    def _exact(self, n: int) -> bytes:
        out = b""
        while len(out) < n:
            chunk = self.sock.recv(n - len(out))
            if not chunk:
                raise IOError("DevTools connection closed")
            out += chunk
        return out

    def send(self, payload: str) -> None:
        data = payload.encode()
        mask = secrets.token_bytes(4)
        header = bytearray([0x81])
        size = len(data)
        if size < 126:
            header.append(0x80 | size)
        elif size < 65536:
            header.append(0x80 | 126)
            header += struct.pack(">H", size)
        else:
            header.append(0x80 | 127)
            header += struct.pack(">Q", size)
        header += mask
        self.sock.sendall(bytes(header) + bytes(b ^ mask[i % 4] for i, b in enumerate(data)))

    def recv(self) -> dict[str, Any]:
        while True:
            first, second = self._exact(2)
            opcode, size = first & 0x0F, second & 0x7F
            if size == 126:
                size = struct.unpack(">H", self._exact(2))[0]
            elif size == 127:
                size = struct.unpack(">Q", self._exact(8))[0]
            body = self._exact(size)
            if opcode == 0x8:
                raise IOError("DevTools connection closed by the browser")
            if opcode in (0x1, 0x2):
                return json.loads(body.decode())

    def call(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self.seq += 1
        self.send(json.dumps({"id": self.seq, "method": method, "params": params or {}}))
        while True:
            message = self.recv()
            if message.get("id") == self.seq:
                if "error" in message:
                    raise IOError(f"{method} failed: {message['error'].get('message')}")
                return message.get("result", {})

    def wait_for(self, event: str, timeout: float) -> bool:
        deadline = time.monotonic() + timeout
        self.sock.settimeout(timeout)
        while time.monotonic() < deadline:
            try:
                if self.recv().get("method") == event:
                    return True
            except (socket.timeout, IOError):
                return False
        return False

    def close(self) -> None:
        try:
            self.sock.close()
        except OSError:
            pass


def find_browser(explicit: str | None) -> tuple[str | None, list[str]]:
    searched: list[str] = []
    for candidate in [explicit, os.environ.get("CHROME_PATH")]:
        if candidate:
            searched.append(candidate)
            if Path(candidate).exists():
                return candidate, searched
    for name in ON_PATH:
        searched.append(f"{name} (on PATH)")
        found = shutil.which(name)
        if found:
            return found, searched
    for path in BROWSER_CANDIDATES:
        searched.append(path)
        if Path(path).exists():
            return path, searched
    return None, searched


class Browser:
    def __init__(self, binary: str, scale: int, size: tuple[int, int]):
        self.profile = tempfile.mkdtemp(prefix="fdw-capture-")
        self.proc = subprocess.Popen(
            [binary, "--headless=new", f"--user-data-dir={self.profile}", "--remote-debugging-port=0",
             "--no-first-run", "--no-default-browser-check", "--disable-gpu", "--hide-scrollbars",
             "--disable-extensions", "--disable-background-networking", "--force-color-profile=srgb",
             f"--window-size={size[0]},{size[1]}", "about:blank"],
            stderr=subprocess.PIPE, stdout=subprocess.DEVNULL, text=True)
        port = None
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            line = self.proc.stderr.readline()
            if not line and self.proc.poll() is not None:
                break
            match = re.search(r"ws://127\.0\.0\.1:(\d+)/", line or "")
            if match:
                port = int(match.group(1))
                break
        if port is None:
            self.kill()
            raise IOError("the browser started but never announced a DevTools endpoint")
        targets = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=10).read())
        page = next(t for t in targets if t["type"] == "page")
        self.ws = WS(page["webSocketDebuggerUrl"])
        self.ws.call("Page.enable")
        self.ws.call("DOM.enable")
        self.ws.call("Emulation.setDeviceMetricsOverride",
                     {"width": size[0], "height": size[1], "deviceScaleFactor": scale, "mobile": False})

    def shoot(self, url: str, clip_selector: str | None) -> bytes:
        self.ws.call("Page.navigate", {"url": url})
        self.ws.wait_for("Page.loadEventFired", NAV_TIMEOUT)
        try:
            self.ws.call("Runtime.evaluate", {"expression": "document.fonts && document.fonts.ready",
                                              "awaitPromise": True, "timeout": 5000})
        except IOError:
            pass  # fonts.ready is a nicety, not a reason to lose the screen
        time.sleep(SETTLE_MS / 1000)
        params: dict[str, Any] = {"format": "png", "captureBeyondViewport": True}
        if clip_selector:
            node = self.ws.call("DOM.getDocument", {"depth": 0})["root"]["nodeId"]
            found = self.ws.call("DOM.querySelector", {"nodeId": node, "selector": clip_selector})
            if found.get("nodeId"):
                box = self.ws.call("DOM.getBoxModel", {"nodeId": found["nodeId"]})["model"]["border"]
                params["clip"] = {"x": box[0], "y": box[1], "width": box[4] - box[0],
                                  "height": box[5] - box[1], "scale": 1}
        return base64.b64decode(self.ws.call("Page.captureScreenshot", params)["data"])

    def kill(self) -> None:
        try:
            self.ws.close()
        except Exception:
            pass
        self.proc.terminate()
        try:
            self.proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.proc.kill()
        shutil.rmtree(self.profile, ignore_errors=True)


# ---------------------------------------------------------------- what to capture


def locate(root: Path, feature_id: str) -> tuple[Path, dict[str, Any]]:
    registry = read_json(root / "registry.json")
    if registry is None:
        die([f"No discovery store at {root}."])
    entry = next((f for f in registry.get("features", []) if f["id"] == feature_id), None)
    if entry is None:
        die([f"No feature '{feature_id}'. Known: {[f['id'] for f in registry.get('features', [])]}"])
    return root / "phases" / entry["phase"] / "features" / f"{entry['id']}-{entry['slug']}", entry


def screen_plan(design: Path) -> tuple[Path, list[dict[str, Any]], list[str]]:
    """The declared screens, in id order, with the client-facing title fdw-design gave each one.
    grounding.json is the source: fdw-design already refuses to let the prototype hold a screen
    that is not in it, so the capture list and the feature boundary are the same list."""
    problems: list[str] = []
    grounding = read_json(design / "grounding.json")
    if grounding is None:
        return design / "prototype", [], [
            "design/grounding.json is missing, so there is no declared list of screens to capture. "
            "Run fdw-design first — capturing whatever files happen to be in the folder is how the "
            "packet ends up showing screens from another feature."]
    proto_dir = Path(grounding.get("prototype_dir") or "prototype")
    proto = proto_dir if proto_dir.is_absolute() else design / proto_dir

    titles = dict(NOTES_SCREEN_RE.findall((design / "ux-notes.md").read_text(encoding="utf-8"))
                  if (design / "ux-notes.md").exists() else [])

    per_file: dict[str, int] = {}
    for screen in grounding.get("screens") or []:
        per_file[screen.get("file", "")] = per_file.get(screen.get("file", ""), 0) + 1

    plan: list[dict[str, Any]] = []
    for screen in sorted(grounding.get("screens") or [], key=lambda s: int(re.sub(r"\D", "", s.get("id", "0")) or 0)):
        sid, rel = screen.get("id"), screen.get("file")
        if not sid or not rel:
            continue
        path = Path(rel) if Path(rel).is_absolute() else design / rel
        if not path.is_file():
            problems.append(f"{sid}: {rel} does not exist, so it cannot be captured.")
            continue
        plan.append({
            "screen": sid,
            "title": (titles.get(sid) or "").strip() or sid,
            "kind": screen.get("kind", ""),
            "path": path,
            # One screen per file is captured whole, so a borrowed shell stays in the picture.
            # Several screens sharing a file are clipped to their own region.
            "clip": f'[data-screen="{sid}"]' if per_file.get(rel, 0) > 1 else None,
        })
    if not plan and not problems:
        problems.append("grounding.json declares no screens. There is nothing to show the client yet.")
    return proto, plan, problems


def serve(directory: Path) -> tuple[ThreadingHTTPServer, str]:
    """Loopback HTTP, not file://. Relative assets, module scripts and fetch all behave
    differently under file://, which is exactly the sort of difference that makes one BA's
    packet not match another's."""
    class Quiet(SimpleHTTPRequestHandler):
        def log_message(self, *args: Any) -> None:  # stdout carries JSON; keep the noise out
            return

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), partial(Quiet, directory=str(directory)))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, f"http://127.0.0.1:{httpd.server_port}"


def cmd_shots(args: argparse.Namespace) -> None:
    root = Path(args.root).resolve()
    design_dir, entry = locate(root, args.id)
    design = design_dir / "design"
    proto, plan, problems = screen_plan(design)
    if problems and not plan:
        die(problems, feature=entry["id"], capture="unavailable")
    if not proto.is_dir():
        die([f"No prototype directory at {proto}."], feature=entry["id"], capture="unavailable")

    binary, searched = find_browser(args.browser)
    if binary is None:
        die(
            [
                "No Chromium-family browser found, so the prototype cannot be captured on this machine.",
                "Set CHROME_PATH to a Chrome, Chromium, Edge or Brave binary, or pass --browser.",
                "Without screenshots the packet still renders — it describes the screens and offers a "
                "walkthrough instead. Say that to the client rather than implying pictures exist.",
            ],
            feature=entry["id"], capture="unavailable", searched=searched)

    out_dir = Path(args.out).resolve() if args.out else design / "screenshots"
    out_dir.mkdir(parents=True, exist_ok=True)
    httpd, base = serve(proto)
    browser = None
    shots: list[dict[str, Any]] = []
    try:
        browser = Browser(binary, args.scale, (args.width, args.height))
        for item in plan:
            rel = item["path"].relative_to(proto).as_posix() if item["path"].is_relative_to(proto) \
                else item["path"].name
            png = out_dir / f"{item['screen']}.png"
            png.write_bytes(browser.shoot(f"{base}/{rel}", item["clip"]))
            shots.append({"screen": item["screen"], "title": item["title"], "kind": item["kind"],
                          "file": str(png), "bytes": png.stat().st_size,
                          "clipped": bool(item["clip"])})
    except (IOError, OSError, StopIteration) as error:
        die([f"Capture failed: {error}",
             "The packet can still be rendered without screenshots — say so to the client rather "
             "than implying pictures exist."],
            feature=entry["id"], capture="failed", browser=binary, captured=len(shots))
    finally:
        if browser:
            browser.kill()
        httpd.shutdown()

    manifest = out_dir / "manifest.json"
    manifest.write_text(json.dumps(
        {"feature": entry["id"], "browser": binary, "viewport": [args.width, args.height],
         "scale": args.scale, "shots": shots}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    emit({"feature": entry["id"], "capture": "complete", "browser": binary,
          "viewport": [args.width, args.height], "scale": args.scale,
          "shots": shots, "manifest": str(manifest), "problems": problems,
          "next": f"pass --shots {manifest} to fdw_packet.py render"})


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Capture a feature's prototype screens")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("shots", help="capture every declared screen, the same way on every machine")
    p.add_argument("--root", required=True, help="discovery store root")
    p.add_argument("--id", required=True)
    p.add_argument("--out", default=None, help="output directory; defaults to design/screenshots")
    p.add_argument("--width", type=int, default=VIEWPORT[0])
    p.add_argument("--height", type=int, default=VIEWPORT[1])
    p.add_argument("--scale", type=int, default=SCALE, help="device pixel ratio")
    p.add_argument("--browser", default=None, help="browser binary; CHROME_PATH is honoured too")
    p.set_defaults(func=cmd_shots)
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
