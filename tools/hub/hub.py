#!/usr/bin/env python3
"""Vantage hub: upload a replay, get its analysis and the viewer in the browser.

A small web app in front of the replay farm (``tools/farm``) and Vantage itself:

1. a visitor uploads a ``.aoe2record``; it is checked, stored under an unlisted id
   and queued;
2. a game copy from the farm plays it once and writes a ``.vrec`` recording;
3. the recording is read once for its analysis (results, timings, time series);
4. the match page shows that analysis, and the Vantage viewer for the recording.
   Each open match has a Vantage server of its own behind this one; the browser
   reaches it on the match's own host name (``<id>.localhost`` on this machine).

    hub.py serve                       on http://localhost:8750
    hub.py serve --public-host example.org --host 0.0.0.0

Standard library only, plus Vantage and the farm. See README.md in this folder.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import http.client
import importlib.util
import json
import mimetypes
import os
import re
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
WEB = HERE / "web"
ID_RE = re.compile(r"m[a-z2-7]{12}")
REPLAY_SUFFIX = ".aoe2record"
#: Uploads start with the size of a deflate-compressed header; anything else is not a replay.
MIN_REPLAY = 4096

# -- what a viewer's Vantage server may be asked through the hub ------------------------

#: GET paths passed on to a match's own Vantage server. Everything else is refused:
#: that server is the desktop one, and its other routes list local folders, start the
#: game or change settings.
VIEWER_GET = re.compile(
    r"^/(?:$|index\.html$|static/|icon/|sprite/|images/|audio/|ui/|terrain|emblem/|skins/"
    r"|particle_atlas\.(?:png|json)$|sse$"
    r"|api/(?:session|match|map|catalog|view|unit/-?\d+|group|techtree/\d+|trees|terrain"
    r"|events|series|summary|images|skins|skins/version|skins/merged|config|stream"
    r"|particles|mods|profiles|review-moments|bookmarks)$)"
)
#: Answered here with nothing, for the viewer's own menus (they would list this
#: machine's files).
VIEWER_EMPTY = {"/api/recordings": [], "/api/replays": [], "/api/native": {"available": False}}
HOP_HEADERS = {"connection", "keep-alive", "transfer-encoding", "te", "upgrade", "host"}


def load_farm() -> Any:
    spec = importlib.util.spec_from_file_location("vantage_farm", ROOT / "tools/farm/farm.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["vantage_farm"] = module
    spec.loader.exec_module(module)
    return module


def installed_build(compat: Path | None) -> int | None:
    """The installed game's build (57257), from the session file the game writes."""
    if compat is None:
        return None
    logs = compat / "pfx/drive_c/users/steamuser/Games/Age of Empires 2 DE/logs"
    with contextlib.suppress(OSError):
        text = (logs / "Age2SessionData.txt").read_text("utf-8", "replace")
        m = re.search(r"Version\s*=\s*\d+\.\d+\.(\d+)\.", text)
        if m:
            return int(m.group(1))
    return None


# -- matches on disk ------------------------------------------------------------------


class Store:
    """``<root>/matches/<id>/`` holds one upload: the replay, its recording, its analysis
    and ``meta.json`` (status and what the replay's header says)."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.matches = root / "matches"
        self.matches.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()
        self.by_hash: dict[str, str] = {}
        for meta in self.matches.glob("*/meta.json"):
            with contextlib.suppress(OSError, ValueError, KeyError):
                self.by_hash[json.loads(meta.read_text())["sha256"]] = meta.parent.name

    def dir(self, match_id: str) -> Path:
        return self.matches / match_id

    def meta(self, match_id: str) -> dict[str, Any] | None:
        if not ID_RE.fullmatch(match_id):
            return None
        try:
            return dict(json.loads((self.dir(match_id) / "meta.json").read_text()))
        except (OSError, ValueError):
            return None

    def update(self, match_id: str, **changes: Any) -> dict[str, Any]:
        with self.lock:
            meta = self.meta(match_id) or {}
            meta.update(changes)
            target = self.dir(match_id) / "meta.json"
            tmp = target.with_suffix(".tmp")
            tmp.write_text(json.dumps(meta, separators=(",", ":")))
            tmp.replace(target)
            return meta

    def create(self, data: bytes, name: str, replay: dict[str, Any]) -> tuple[str, bool]:
        """Store an upload. Returns its id and whether it is new (the same file
        uploaded again gets the match it already has)."""
        digest = hashlib.sha256(data).hexdigest()
        with self.lock:
            known = self.by_hash.get(digest)
            if known and (self.dir(known) / "meta.json").is_file():
                return known, False
            match_id = "m" + "".join(
                secrets.choice("abcdefghijklmnopqrstuvwxyz234567") for _ in range(12)
            )
            folder = self.dir(match_id)
            folder.mkdir(parents=True)
            (folder / "replay.aoe2record").write_bytes(data)
            self.by_hash[digest] = match_id
        self.update(
            match_id,
            id=match_id,
            sha256=digest,
            name=name,
            size=len(data),
            uploaded=int(time.time()),
            status="queued",
            replay=replay,
        )
        return match_id, True

    def all(self) -> list[dict[str, Any]]:
        out = []
        for folder in self.matches.iterdir():
            meta = self.meta(folder.name)
            if meta:
                out.append(meta)
        return out


def replay_summary(path: Path) -> dict[str, Any]:
    """What the upload page shows before conversion, from the replay's own header."""
    sys.path.insert(0, str(ROOT / "src"))
    from vantage.replay import read_replay

    info = read_replay(path).to_json()
    keep = (
        "build", "started_at", "map_id", "map_size", "game_type", "num_players", "ranked",
        "duration_ms", "winners", "population", "speed_name",
    )  # fmt: skip
    out = {k: info.get(k) for k in keep}
    out["players"] = [
        {k: p.get(k) for k in ("number", "name", "civ_id", "color_id", "team", "is_human", "elo")}
        for p in info.get("players", [])
    ]
    return out


def analyze(recording: Path, target: Path) -> int:
    """Read a recording once and write what the match page draws (a process of its
    own: loading a long game takes half a minute and 250 MB)."""
    sys.path.insert(0, str(ROOT / "src"))
    from vantage.frames import read_header
    from vantage.gamedata import GameData, find_game_dir
    from vantage.timeline import load_recording

    header = read_header(recording)
    data = GameData(find_game_dir(), mode=header.get("game_mode"))
    timeline = load_recording(str(recording), data)
    match = timeline.match
    from vantage.replay import load_map_names

    map_name = ""
    with contextlib.suppress(Exception):
        map_name = load_map_names(data).get(int(match.get("map_type") or -1), "")
    out = {
        "status": timeline.status(),
        "match": {
            "map": map_name or str(match.get("map_file") or "").rsplit(".", 1)[0],
            "map_size": match.get("map_size"),
            "game_mode": match.get("game_mode"),
            "ranked": match.get("ranked"),
            "pop_limit": match.get("pop_limit"),
            "players": {
                str(pid): {
                    k: p.get(k) for k in ("name", "civ_name", "color", "team_key", "ai", "elo")
                }
                for pid, p in (match.get("players") or {}).items()
                if int(pid) > 0
            },
        },
        "summary": timeline.summary(),
        "series": {k: v for k, v in timeline.series_json().items() if k != "0"},
        "events": len(timeline.events),
    }
    tmp = target.with_suffix(".tmp")
    tmp.write_text(json.dumps(out, separators=(",", ":"), default=str))
    tmp.replace(target)
    return 0


# -- conversion -----------------------------------------------------------------------


class Converter:
    """Queues uploads on the farm, then analyses each finished recording."""

    def __init__(self, store: Store, opts: argparse.Namespace) -> None:
        self.store = store
        self.opts = opts
        self.farm = load_farm()
        self.pool: Any = None
        self.error = ""
        self.order: list[str] = []
        self.lock = threading.Lock()
        game = self.farm.find_game()
        self.build = opts.build or installed_build(
            self.farm.find_compatdata(game) if game else None
        )

    def _pool(self) -> Any:
        if self.pool is None:
            options = self.farm.options(jobs=self.opts.jobs, replays=[])
            self.pool = self.farm.Pool(
                options, self._done, idle_seconds=self.opts.idle_seconds, log=log
            )
            log(f"farm: up to {self.opts.jobs} game copies, {self.pool.describe()}")
        return self.pool

    def submit(self, match_id: str) -> None:
        folder = self.store.dir(match_id)
        try:
            pool = self._pool()
        except Exception as exc:  # FarmError: say why on the match page
            self.store.update(match_id, status="failed", error=f"Conversion is unavailable: {exc}")
            return
        with self.lock:
            self.order.append(match_id)
        self.store.update(match_id, status="queued", error="")
        pool.submit(folder / "replay.aoe2record", folder / "match.vrec", match_id)

    def position(self, match_id: str) -> int:
        """How many uploads are ahead of this one (0: it is being converted or next)."""
        with self.lock:
            return (
                max(0, self.order.index(match_id) - self.opts.jobs + 1)
                if match_id in self.order
                else 0
            )

    def _done(self, row: dict[str, Any]) -> None:
        match_id = row["tag"]
        with self.lock, contextlib.suppress(ValueError):
            self.order.remove(match_id)
        if not row["ok"]:
            meta = self.store.meta(match_id) or {}
            build = (meta.get("replay") or {}).get("build")
            if row.get("load") == "NO_GAME":
                error = "The game did not start on the server. Try again later."
            elif build and self.build and build != self.build:
                error = (
                    f"This replay is from game build {build}; the server's game is build "
                    f"{self.build}, and the game only plays replays of its own build."
                )
            else:
                error = "The game could not play this replay."
            self.store.update(match_id, status="failed", error=error, detail=row.get("load"))
            log(f"{match_id}: conversion failed ({row.get('load')})")
            return
        self.store.update(
            match_id,
            status="analyzing",
            converted=int(time.time()),
            convert_s=row.get("total_s"),
            game_s=row.get("game_s"),
        )
        threading.Thread(target=self.analyze, args=(match_id,), daemon=True).start()

    def analyze(self, match_id: str) -> None:
        folder = self.store.dir(match_id)
        cmd = [sys.executable, __file__, "_analyze", str(folder / "match.vrec")]
        cmd.append(str(folder / "analysis.json"))
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if proc.returncode == 0:
            self.store.update(match_id, status="ready", analyzed=int(time.time()))
            log(f"{match_id}: ready")
        else:
            # The recording exists and the viewer can open it; only the tables are missing.
            self.store.update(match_id, status="ready", analysis_error=proc.stderr.strip()[-300:])
            log(f"{match_id}: analysis failed: {proc.stderr.strip()[-200:]}")

    def resume(self) -> None:
        """After a restart: take up uploads that were waiting or half done."""
        for meta in sorted(self.store.all(), key=lambda m: m.get("uploaded", 0)):
            folder = self.store.dir(meta["id"])
            if meta.get("status") in ("queued", "converting"):
                self.submit(meta["id"])
            elif meta.get("status") == "analyzing" and (folder / "match.vrec").is_file():
                threading.Thread(target=self.analyze, args=(meta["id"],), daemon=True).start()

    def close(self) -> None:
        if self.pool is not None:
            self.pool.close()


# -- viewers --------------------------------------------------------------------------


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


class Viewers:
    """One Vantage server per match being watched, started on demand, at most
    ``limit`` at once (the least recently used goes first) and stopped when idle."""

    def __init__(self, store: Store, opts: argparse.Namespace) -> None:
        self.store = store
        self.opts = opts
        self.lock = threading.Lock()
        self.running: dict[str, tuple[subprocess.Popen[bytes], int]] = {}
        self.used: dict[str, float] = {}
        self.starting: dict[str, threading.Lock] = {}
        threading.Thread(target=self._reap, daemon=True).start()

    def port(self, match_id: str) -> int | None:
        """The port of this match's server, starting it if need be. None when the
        match has no recording (yet)."""
        recording = self.store.dir(match_id) / "match.vrec"
        if not recording.is_file():
            return None
        with self.lock:
            gate = self.starting.setdefault(match_id, threading.Lock())
        with gate:
            with self.lock:
                self.used[match_id] = time.monotonic()
                held = self.running.get(match_id)
                if held and held[0].poll() is None:
                    return held[1]
                self._evict(keep=self.opts.viewers - 1)
            port = free_port()
            env = dict(os.environ, VANTAGE_DATA_DIR=str(self.store.root / "viewer-data"))
            env["PYTHONPATH"] = str(ROOT / "src")
            cmd = [sys.executable, "-m", "vantage", "serve", "--host", "127.0.0.1"]
            cmd += ["--port", str(port), "--recording", str(recording)]
            if not self.opts.game_art:
                cmd.append("--recording-only")
            # Every match has an origin of its own, so the viewer's first-run guide would
            # show again for each one.
            cmd += ["--patch-config", json.dumps({"seenTutorial": True, "seenRorTutorial": True})]
            proc = subprocess.Popen(
                cmd, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, start_new_session=True,
            )  # fmt: skip
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline and proc.poll() is None:
                with (
                    contextlib.suppress(OSError),
                    socket.create_connection(("127.0.0.1", port), 0.3),
                ):
                    with self.lock:
                        self.running[match_id] = (proc, port)
                    log(f"{match_id}: viewer on port {port}")
                    return port
                time.sleep(0.15)
            proc.kill()
            return None

    def _evict(self, keep: int) -> None:
        live = [m for m, (p, _) in self.running.items() if p.poll() is None]
        for match_id in sorted(live, key=lambda m: self.used.get(m, 0))[: max(0, len(live) - keep)]:
            self._stop(match_id)

    def _stop(self, match_id: str) -> None:
        proc, _ = self.running.pop(match_id)
        with contextlib.suppress(OSError):
            proc.terminate()

    def _reap(self) -> None:
        while True:
            time.sleep(30)
            with self.lock:
                now = time.monotonic()
                for match_id in list(self.running):
                    idle = now - self.used.get(match_id, 0) > self.opts.viewer_idle
                    if idle or self.running[match_id][0].poll() is not None:
                        self._stop(match_id)

    def close(self) -> None:
        with self.lock:
            for match_id in list(self.running):
                self._stop(match_id)


# -- HTTP -----------------------------------------------------------------------------


def log(text: str) -> None:
    print(time.strftime("%H:%M:%S"), text, flush=True)


class Hub:
    def __init__(self, opts: argparse.Namespace) -> None:
        self.opts = opts
        self.store = Store(Path(opts.data_dir).expanduser())
        self.converter = Converter(self.store, opts)
        self.viewers = Viewers(self.store, opts)
        self.uploads: dict[str, list[float]] = {}
        self.lock = threading.Lock()

    # The viewer of match <id> lives on the host name <id>.<the hub's own host>.
    def match_of_host(self, host: str) -> str | None:
        label = host.split(":")[0].split(".")[0].lower()
        return label if ID_RE.fullmatch(label) and "." in host.split(":")[0] else None

    def viewer_url(self, match_id: str, h: BaseHTTPRequestHandler) -> str:
        if self.opts.public_host:
            return f"{self.opts.public_scheme}://{match_id}.{self.opts.public_host}/"
        host = h.headers.get("Host") or f"localhost:{self.opts.port}"
        name, _, port = host.partition(":")
        if name in ("127.0.0.1", "::1", "[::1]"):
            name = "localhost"  # browsers resolve every *.localhost name to this machine
        return f"http://{match_id}.{name}{':' + port if port else ''}/"

    def allowed(self, ip: str) -> bool:
        """At most ``--uploads-per-hour`` uploads from one address."""
        now = time.time()
        with self.lock:
            recent = [t for t in self.uploads.get(ip, []) if now - t < 3600]
            ok = len(recent) < self.opts.uploads_per_hour
            if ok:
                recent.append(now)
            self.uploads[ip] = recent
            return ok

    def describe(self, meta: dict[str, Any], h: BaseHTTPRequestHandler) -> dict[str, Any]:
        keys = (
            "id",
            "name",
            "size",
            "uploaded",
            "status",
            "error",
            "replay",
            "convert_s",
            "game_s",
        )
        out = {k: meta.get(k) for k in keys}
        if meta.get("status") == "queued":
            out["ahead"] = self.converter.position(meta["id"])
        if meta.get("status") in ("ready", "analyzing"):
            out["viewer"] = self.viewer_url(meta["id"], h)
        folder = self.store.dir(meta["id"])
        out["analysis"] = (folder / "analysis.json").is_file()
        return out


def make_handler(hub: Hub) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, format: str, *args: Any) -> None:
            return

        # -- answers ----------------------------------------------------------

        def send(self, body: bytes, ctype: str, status: int = 200, cache: str = "no-store") -> None:
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", cache)
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def json(self, value: Any, status: int = 200) -> None:
            self.send(json.dumps(value, separators=(",", ":")).encode(), "application/json", status)

        def fail(self, status: int, message: str) -> None:
            self.json({"ok": False, "error": message}, status)

        def client(self) -> str:
            if hub.opts.trust_proxy:
                forwarded = self.headers.get("X-Forwarded-For", "")
                if forwarded:
                    return forwarded.split(",")[-1].strip()
            return str(self.client_address[0])

        # -- routes -----------------------------------------------------------

        def route(self) -> None:
            match_id = hub.match_of_host(self.headers.get("Host", ""))
            if match_id:
                return self.viewer(match_id)
            url = urlparse(self.path)
            path = url.path
            if self.command == "POST":
                if path == "/api/upload":
                    return self.upload(parse_qs(url.query))
                m = re.fullmatch(r"/api/match/(m[a-z2-7]{12})/retry", path)
                if m:
                    return self.retry(m.group(1))
                return self.fail(404, "not found")
            if path == "/" or re.fullmatch(r"/m/m[a-z2-7]{12}", path):
                return self.static("index.html")
            if path.startswith("/hub/"):
                return self.static(path[len("/hub/") :])
            if path == "/api/info":
                return self.json(
                    {
                        "build": hub.converter.build,
                        "max_mb": hub.opts.max_mb,
                        "game_art": bool(hub.opts.game_art),
                    }
                )
            m = re.fullmatch(r"/api/match/(m[a-z2-7]{12})(/analysis)?", path)
            if m:
                meta = hub.store.meta(m.group(1))
                if meta is None:
                    return self.fail(404, "no such match")
                if m.group(2):
                    try:
                        body = (hub.store.dir(m.group(1)) / "analysis.json").read_bytes()
                    except OSError:
                        return self.fail(404, "not analysed yet")
                    return self.send(body, "application/json", cache="private, max-age=3600")
                return self.json(hub.describe(meta, self))
            return self.fail(404, "not found")

        def static(self, name: str) -> None:
            target = (WEB / name).resolve()
            if WEB not in target.parents or not target.is_file():
                return self.fail(404, "not found")
            ctype = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
            if target.suffix == ".js":
                ctype = "text/javascript"
            self.send(target.read_bytes(), ctype)

        def upload(self, query: dict[str, list[str]]) -> None:
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                length = 0
            limit = hub.opts.max_mb * 1024 * 1024
            if length <= 0:
                return self.fail(411, "The upload has no length.")
            if length > limit:
                # Read a moderately oversized body so the browser gets the message, not a
                # broken connection; hang up on anything larger.
                if length <= 4 * limit:
                    left = length
                    while left > 0 and (chunk := self.rfile.read(min(left, 1 << 16))):
                        left -= len(chunk)
                else:
                    self.close_connection = True
                return self.fail(413, f"Replays up to {hub.opts.max_mb} MB are accepted.")
            data = self.rfile.read(length)
            if len(data) != length:
                return self.fail(400, "The upload was cut short.")
            name = re.sub(r"[^\w .@()+-]", "_", unquote((query.get("name") or ["replay"])[0]))[
                -120:
            ]
            if len(data) < MIN_REPLAY or not name.lower().endswith(REPLAY_SUFFIX):
                return self.fail(400, "That is not an .aoe2record replay file.")
            if not hub.allowed(self.client()):
                return self.fail(429, "Too many uploads from this address. Try again in an hour.")
            scratch = hub.store.root / "incoming"
            scratch.mkdir(exist_ok=True)
            probe = scratch / (secrets.token_hex(8) + REPLAY_SUFFIX)
            probe.write_bytes(data)
            try:
                replay = replay_summary(probe)
            except Exception:
                return self.fail(400, "The file could not be read as an AoE2 DE replay.")
            finally:
                probe.unlink(missing_ok=True)
            build = hub.converter.build
            if (
                build
                and replay.get("build")
                and replay["build"] != build
                and not hub.opts.any_build
            ):
                return self.fail(
                    422,
                    f"This replay is from game build {replay['build']}. The server's game is "
                    f"build {build}, and the game only plays replays of its own build.",
                )
            match_id, new = hub.store.create(data, name, replay)
            if new:
                log(f"{match_id}: upload {name} ({len(data) // 1024} KB) from {self.client()}")
                hub.converter.submit(match_id)
            self.json({"ok": True, "id": match_id, "new": new})

        def retry(self, match_id: str) -> None:
            meta = hub.store.meta(match_id)
            if meta is None:
                return self.fail(404, "no such match")
            if meta.get("status") != "failed":
                return self.fail(409, "This match is not in a failed state.")
            if not hub.allowed(self.client()):
                return self.fail(429, "Too many uploads from this address. Try again in an hour.")
            hub.converter.submit(match_id)
            self.json({"ok": True})

        # -- a match's own Vantage server, on the match's host name ------------

        def viewer(self, match_id: str) -> None:
            path = urlparse(self.path).path
            if self.command == "POST":
                # The viewer saves bookmarks and reports the end of playback; nothing a
                # visitor does may change the server.
                return self.json({"ok": False, "error": "read-only"})
            if path in VIEWER_EMPTY:
                return self.json(VIEWER_EMPTY[path])
            if not VIEWER_GET.match(path):
                return self.fail(404, "not available here")
            if hub.store.meta(match_id) is None:
                return self.fail(404, "no such match")
            port = hub.viewers.port(match_id)
            if port is None:
                return self.fail(503, "This match has no recording yet.")
            headers = {k: v for k, v in self.headers.items() if k.lower() not in HOP_HEADERS}
            headers["Host"] = f"127.0.0.1:{port}"
            # These two name the recording's file: read them uncompressed to strip the path.
            private = path in ("/api/session", "/api/stream")
            if private:
                headers.pop("Accept-Encoding", None)
            upstream = http.client.HTTPConnection("127.0.0.1", port, timeout=120)
            try:
                upstream.request("GET", self.path, headers=headers)
                answer = upstream.getresponse()
                secret = str(hub.store.dir(match_id)).encode()
                length = answer.getheader("Content-Length")
                self.send_response(answer.status)
                for key, value in answer.getheaders():
                    if key.lower() not in HOP_HEADERS and key.lower() != "content-length":
                        self.send_header(key, value)
                if length is not None:
                    body = answer.read()
                    if private:
                        body = body.replace(secret, b"")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                # No length: an event stream. Pass it on as it comes, until either side ends.
                self.send_header("Connection", "close")
                self.end_headers()
                self.close_connection = True
                while chunk := answer.read1(65536):
                    self.wfile.write(chunk.replace(secret, b"") if private else chunk)
                    self.wfile.flush()
                    hub.viewers.used[match_id] = time.monotonic()
            finally:
                upstream.close()

        def handle_any(self) -> None:
            try:
                self.route()
            except (BrokenPipeError, ConnectionResetError, TimeoutError):
                self.close_connection = True
            except Exception as exc:
                log(f"error on {self.command} {self.path}: {exc!r}")
                with contextlib.suppress(Exception):
                    self.send_error(HTTPStatus.INTERNAL_SERVER_ERROR)

        do_GET = do_POST = do_HEAD = handle_any

    return Handler


def cmd_serve(opts: argparse.Namespace) -> int:
    if not opts.public_host and opts.host not in ("127.0.0.1", "localhost", "::1"):
        raise SystemExit("--host other than this machine needs --public-host (see README.md)")
    hub = Hub(opts)
    server = ThreadingHTTPServer((opts.host, opts.port), make_handler(hub))
    server.daemon_threads = True
    hub.converter.resume()
    where = (
        f"{opts.public_scheme}://{opts.public_host}"
        if opts.public_host
        else f"http://localhost:{opts.port}"
    )
    log(f"hub on {where}  (data: {hub.store.root}, game build: {hub.converter.build or 'unknown'})")

    # A plain "kill" ends the hub the same way Ctrl+C does: its viewers and game copies
    # are processes of their own and must be stopped with it.
    def interrupt(*_: Any) -> None:
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, interrupt)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        hub.viewers.close()
        hub.converter.close()
        shutil.rmtree(hub.store.root / "incoming", ignore_errors=True)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("serve", help="run the web app")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8750)
    s.add_argument("--data-dir", default="~/.local/share/vantage-hub")
    s.add_argument("--public-host", help="the site's host name; viewers use <id>.<this>")
    s.add_argument("--public-scheme", default="https", choices=("http", "https"))
    s.add_argument(
        "--trust-proxy", action="store_true", help="take client addresses from X-Forwarded-For"
    )
    s.add_argument("-j", "--jobs", type=int, default=2, help="game copies converting at once")
    s.add_argument(
        "--idle-seconds", type=float, default=600, help="stop an idle game copy after this"
    )
    s.add_argument("--viewers", type=int, default=4, help="matches that can be watched at once")
    s.add_argument(
        "--viewer-idle", type=float, default=900, help="stop an unwatched viewer after this"
    )
    s.add_argument("--max-mb", type=int, default=64, help="largest upload")
    s.add_argument("--uploads-per-hour", type=int, default=20, help="per client address")
    s.add_argument("--build", type=int, help="the installed game's build (default: detected)")
    s.add_argument("--any-build", action="store_true", help="queue replays of other builds too")
    s.add_argument(
        "--no-game-art", dest="game_art", action="store_false",
        help="viewers draw plain markers instead of the installed game's graphics",
    )  # fmt: skip
    s.set_defaults(func=cmd_serve)
    a = sub.add_parser("_analyze")  # internal: one recording's analysis
    a.add_argument("recording", type=Path)
    a.add_argument("target", type=Path)
    a.set_defaults(func=lambda o: analyze(o.recording, o.target))
    opts = parser.parse_args()
    return int(opts.func(opts))


if __name__ == "__main__":
    raise SystemExit(main())
