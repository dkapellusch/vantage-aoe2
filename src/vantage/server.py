"""Vantage server: one spectating session, served to a browser UI.

Stdlib HTTP only. The browser owns the playback clock and asks for the view at
the moment it wants to show (``/api/view?t=``); keyframes make that a lookup.
Server-sent events (``/api/stream``) announce new data so a live view follows
the game without polling.

Sources a session can hold:

* **live** -- the running game's ``CadeRemote`` stream (spectating a match, or a
  replay the game is playing). Frames are recorded to ``.vrec`` as they arrive.
  On a broken stream the source reconnects; the new stream opens with a full
  snapshot, which resynchronises the tree.
* **recording** -- a ``.vrec`` file, loaded in the background.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import mimetypes
import os
import re
import secrets
import sys
import threading
import time
import traceback
import weakref
from collections.abc import Sequence
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from vantage import __version__, recording_summary
from vantage.certs import cert_status, certs_dir, missing_cert_files
from vantage.deployment import asset_revision, deployment_revision
from vantage.frames import RecordingWriter, read_header
from vantage.gamedata import (
    GameData,
    find_game_dir,
    host_path,
    profile_dirs,
    replay_dirs,
    windows_path,
)
from vantage.http_cache import content_encoding
from vantage.launcher import GameLauncher
from vantage.live import MAX_API_VERSION, classify_stream_error, port_open
from vantage.paths import local_data_dir
from vantage.replay import ReplayError, load_map_names, read_replay
from vantage.review_moments import normalize_moments
from vantage.skins import SkinStore
from vantage.sprites import RENDER_VERSION, SpriteInfo, SpriteStore, strip_options
from vantage.timeline import Timeline, load_recording, settle_heap

WEB_PACKAGE = "vantage"


#: ``Code`` names the game answers when loading/switching would end a game.
NEED_CONFIRM = "FAILED_PLAYING_NEED_CONFIRM"
#: No frame for this long while the game is neither paused nor over: the game
#: is waiting for a lagging or dropped player.
WAITING_AFTER_S = 3.0
#: Most entity ids one ``/api/group`` request reads (a box over a whole army).
GROUP_MAX = 600
#: Seconds before reconnecting a broken live stream.
RECONNECT_S = 3.0
#: Once the game is over, reconnects back off (doubling) up to this many seconds.
RECONNECT_ENDED_MAX_S = 60.0


#: Least time between two session pushes on ``/api/stream`` for a new timeline
#: version alone. A loading recording bumps the version for every keyframe (dozens
#: a second) and each push made the browser refresh what it shows.
SESSION_PUSH_S = 0.25


def push_wait(
    key: tuple[Any, ...], last: tuple[Any, ...], last_push: float, now: float
) -> float | None:
    """Seconds to hold a session push back: None when nothing changed, 0 to send
    now. ``key`` is (generation, version, error, connected, status, phase); a
    change other than the version goes out at once."""
    if key == last:
        return None
    if not last or key[0] != last[0] or key[2:] != last[2:]:
        return 0.0
    return max(0.0, last_push + SESSION_PUSH_S - now)


def reconnect_delay(game_over: bool, idle_streams: int) -> float:
    """Seconds to wait before reopening the live stream.

    ``idle_streams`` counts the streams in a row, since the game ended, that
    brought nothing new. An ended game answers each reconnect with the same full
    snapshot (23 MB late in a game), so retrying every 3 s for an hour only
    burned CPU; the game starting something new is still seen within a minute.
    """
    if not game_over:
        return RECONNECT_S
    return min(RECONNECT_ENDED_MAX_S, RECONNECT_S * 2.0 ** min(idle_streams, 16))


class Session:
    """The one game being watched, whatever its source."""

    def __init__(self, data: GameData, recordings_dir: Path) -> None:
        self.data = data
        self.viewer_build = deployment_revision()
        self.asset_build = asset_revision()
        self.server_instance = secrets.token_hex(8)
        self.recordings_dir = recordings_dir
        self.timeline: Timeline | None = None
        self.tc_idle_villagers = 120
        self.mode = "idle"
        self.source: dict[str, Any] = {}
        self.error: str | None = None
        self._live: Any = None
        #: Stream status of the last failed live connection (None once connected).
        self._stream_error: str | None = None
        self._oracle_game: Any = None
        self._oracle_thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.lock = threading.Lock()
        self.generation = 0
        self.ended = threading.Event()
        #: The live game's profile folders (from ``Info.userdirectory``).
        self.user_dirs: list[Path] = []
        self._writer: RecordingWriter | None = None
        self._writer_lock = threading.Lock()
        self._record_wanted = False
        self._restart_stream = False
        #: Fast replay (the game at FAST / EXTRA_FAST): a lighter frame stream, see
        #: LIGHT_STREAM_MS.
        self._light_stream = False
        self._last_frame = 0.0
        #: Reads what unopened recordings hold, for the recordings list.
        self.summaries = recording_summary.Summarizer()

    # -- lifecycle ------------------------------------------------------------

    def _replace(self, mode: str, source: dict[str, Any]) -> Timeline:
        self.stop()
        with self.lock:
            self.generation += 1
            self.timeline = Timeline(self.data, tc_idle_villagers=self.tc_idle_villagers)
            self.mode = mode
            self.source = source
            self.error = None
            self._stream_error = None
            self._stop = threading.Event()
            self.ended = threading.Event()
            return self.timeline

    def stop(self) -> None:
        self._stop.set()
        if self._oracle_game is not None:
            with contextlib.suppress(Exception):
                self._oracle_game.close()
        if self._live is not None:
            # Best effort: the stream may already be gone.
            with contextlib.suppress(Exception):
                self._live.cancel_frames()
        if self._thread is not None and self._thread is not threading.current_thread():
            self._thread.join(timeout=5)
        self._thread = None

    def open_recording(self, path: str) -> None:
        p = Path(path).expanduser()
        header = read_header(p)
        self.data = self.data.with_mode(header.get("game_mode"))
        tl = self._replace("recording", {"path": str(p), "header": header, "game": self.data.game})
        stop = self._stop
        ended = self.ended

        def run() -> None:
            from vantage.frames import read_frames

            try:
                for f in read_frames(p):
                    if stop.is_set():
                        return
                    if tl.feed(f) and f.is_snapshot:
                        settle_heap()
                tl.finish()
                # The recordings list shows who played and for how long: both
                # are known now, at no cost.
                if self.summaries.enabled and tl.match.get("players"):
                    summary = recording_summary.describe(tl.match, self.data)
                    summary["duration_ms"] = int(tl.end - tl.start)
                    recording_summary.store(self.data.cache_dir, p, summary)
            except Exception as exc:  # surfaced to the UI; the server keeps running
                self.error = f"{type(exc).__name__}: {exc}"
                tl.finish()
            finally:
                self.source["status"] = "ready"
                ended.set()

        self.source["status"] = "loading"
        self._thread = threading.Thread(target=run, name="vantage-load", daemon=True)
        self._thread.start()

    # -- live -----------------------------------------------------------------

    def open_live(
        self,
        host: str = "127.0.0.1",
        port: int = 4341,
        replay: str | None = None,
        lobby: str | None = None,
        record: bool = True,
        resolution_ms: int = 100,
        minimize: bool = False,
        exit_on_end: bool = False,
        particles: bool = True,
        game: int | None = None,
        confirm: bool | None = None,
        cloud: bool = False,
        lobby_source: str | None = None,
    ) -> None:
        """Stream the running game. ``game`` (1 Return of Rome, 2 AoE2) switches
        the client first, for a replay of the other game.

        ``confirm`` is passed to the game's load/switch requests (see
        :meth:`vantage.live.LiveGame.load_replay`): the web UI sends
        False, then True once the user agreed; None (asks, then agrees) is
        only for command-line use. When the game asks for confirmation the
        session stops with ``source.needs_confirm`` set.
        """
        game_id = game
        source: dict[str, Any] = {
            "host": host,
            "port": port,
            "replay": replay,
            "lobby_id": lobby,
            "lobby": None,
            "status": "connecting",
            "waiting": None,
            "recording_active": False,
        }
        if cloud:
            source["cloud"] = True
        if lobby_source:
            source["lobby_source"] = lobby_source
        # The request as /api/live takes it, so the UI can resend it confirmed
        # when the game asks whether to leave a game in progress.
        source["request"] = {
            "host": host,
            "port": port,
            "replay": replay,
            "lobby": lobby,
            "record": record,
            "game": game,
            "cloud": cloud,
            "source": lobby_source,
        }
        tl = self._replace("live", source)
        stop = self._stop
        ended = self.ended
        self._record_wanted = record

        def run() -> None:
            from vantage.live import LiveGame

            timeline = tl
            loaded = False
            game_version = 0

            def new_writer() -> RecordingWriter:
                stamp = time.strftime("%Y%m%d-%H%M%S")
                out = self.recordings_dir / f"live-{stamp}-{self.generation}.vrec"
                source["recording"] = str(out)
                source["recording_active"] = True
                header = {
                    "source": "live",
                    "replay": replay,
                    "game_version": game_version,
                    "game_mode": self.data.mode,
                }
                return RecordingWriter(out, header)

            watchdog = threading.Thread(
                target=self._watch_waiting, args=(stop,), name="vantage-waiting", daemon=True
            )
            watchdog.start()
            idle_streams = 0
            while not stop.is_set():
                game = None
                self._restart_stream = False
                progressed = False
                try:
                    if source.get("status") != "needs_certs" and not self._match_over(timeline):
                        source["status"] = "connecting"
                    game = LiveGame(host, port).connect(timeout=5)
                    self._live = game
                    info = game.info()
                    game_version = info.game_version
                    source["game_version"] = info.game_version
                    source["api_version"] = info.api_version
                    self._adopt_info(info)
                    if not loaded and game_id is not None and info.selected_game != game_id:
                        source["status"] = "loading"
                        result = game.set_desired_game(game_id, confirm=confirm)
                        source["switch_result"] = result
                        if result == NEED_CONFIRM:
                            self._ask_confirm(result)
                            break
                        info = game.info()
                    # Return of Rome runs from modes/Pompeii: read names, civs and
                    # icons from there.
                    game_mode = mode_from_path(info.selected_mode)
                    self.data = self.data.with_mode(game_mode)
                    timeline.data = timeline.catalog.data = self.data
                    source["game"] = self.data.game
                    if not loaded and replay:
                        source["status"] = "loading"
                        if not cloud and "replay_duration_ms" not in source:
                            # Its length lets the view buffer for fast replay (8x).
                            source["replay_duration_ms"] = replay_duration(replay, self.data)
                        result = game.load_replay(replay, confirm=confirm, cloud=cloud)
                        source["load_result"] = result
                        if result == NEED_CONFIRM:
                            self._ask_confirm(result)
                            break
                    elif not loaded and lobby:
                        source["status"] = "joining"
                        source["lobby"] = {"id": lobby, **(source.get("lobby") or {})}
                        result = game.spectate_lobby(lobby, confirm=confirm)
                        source["load_result"] = result
                        if result == NEED_CONFIRM:
                            self._ask_confirm(result)
                            break
                    else:
                        source["status"] = "ready"
                    loaded = True
                    self.error = None
                    self._stream_error = None
                    if self._match_over(timeline):
                        # A reconnect to a finished game: it is still finished, whatever
                        # the stream's first frame looks like. The viewer reads "the game
                        # is over" from this status.
                        source["status"] = "ended"

                    if minimize:
                        with contextlib.suppress(Exception):
                            game.set_window("MINIMIZED")
                    last_flush = time.monotonic()
                    oracle_started = False
                    # Share of wall time spent processing frames (moving average).
                    # Near 1 the timeline is falling behind the game's stream, as in
                    # an 8x replay of a large late game: keyframes then go to every
                    # 2 s until there is headroom again.
                    busy = 0.0
                    last_seen = time.monotonic()
                    light = self._light_stream
                    whitelist = (
                        (
                            light_particles(self.data.particle_definitions)
                            if light
                            else self.data.particle_definitions
                        )
                        if particles
                        else None
                    )
                    for f in game.frames(
                        resolution_ms=LIGHT_STREAM_MS if light else resolution_ms,
                        particles=bool(particles and whitelist),
                        particle_whitelist=whitelist,
                        category_ms=LIGHT_STREAM_CATEGORIES if light else None,
                    ):
                        if stop.is_set():
                            break
                        self._last_frame = time.monotonic()
                        if source.get("status") != "ended":
                            source["status"] = "playing"
                        oracle = self._oracle_thread
                        if not oracle_started and (oracle is None or not oracle.is_alive()):
                            # Only once the world has arrived, and on its own
                            # connection (the game serves one stream per connection).
                            oracle_started = True
                            self._oracle_thread = threading.Thread(
                                target=self._watch_oracle,
                                args=(host, port, stop),
                                name="vantage-oracle",
                                daemon=True,
                            )
                            self._oracle_thread.start()
                        if f.is_snapshot and timeline.frames and f.time + 5000 < timeline.time:
                            # Time went backwards: the game now shows a different
                            # match. Start a new timeline (and recording) for it.
                            timeline.finish()
                            with self.lock:
                                self.generation += 1
                                timeline = self.timeline = Timeline(
                                    self.data, tc_idle_villagers=self.tc_idle_villagers
                                )
                            with self._writer_lock:
                                if self._writer is not None:
                                    self._close_writer()
                                    self._writer = new_writer()
                        fed = time.monotonic()
                        applied = timeline.feed(f)
                        # A snapshot repeating the state held (the game ended or is
                        # paused, and answered a reconnect): not fed, not recorded.
                        repeated = f.is_snapshot and not applied and not timeline.desynced
                        progressed = progressed or applied
                        if applied and f.is_snapshot:
                            settle_heap()
                        done = time.monotonic()
                        span = max(1e-6, done - last_seen)
                        busy = 0.9 * busy + 0.1 * min(1.0, (done - fed) / span)
                        last_seen = done
                        timeline.keyframe_step_ms = keyframe_step(busy, timeline.keyframe_step_ms)
                        if timeline.game_ended:
                            source["status"] = "ended"
                        with self._writer_lock:
                            opened = self._writer is None and self._record_wanted
                            if opened and f.is_snapshot:
                                # A recording must open with a full-state frame.
                                self._writer = new_writer()
                            if self._writer is not None and (not repeated or opened):
                                self._writer.write(f)
                                if time.monotonic() - last_flush > 5:
                                    self._writer.flush()
                                    last_flush = time.monotonic()
                except Exception as exc:  # reconnect: the next stream starts with a snapshot
                    self.error = f"{type(exc).__name__}: {exc}"
                    self._stream_error = classify_stream_error(exc)
                    if not loaded:
                        self._explain_connect_failure(source, host, port)
                finally:
                    self._live = None
                    if game is not None:
                        game.close()
                if self._restart_stream and not stop.is_set():
                    continue  # asked for a fresh stream (e.g. to start a recording)
                if self._match_over(timeline):
                    # Nothing more comes: show the final moments, where the result is.
                    timeline.flush_keyframe()
                if exit_on_end and loaded and self.error is None:
                    break  # the stream ended cleanly: done, not reconnecting
                game_over = timeline.game_ended or source.get("status") == "ended"
                idle_streams = idle_streams + 1 if game_over and not progressed else 0
                if not stop.is_set():
                    stop.wait(reconnect_delay(game_over, idle_streams))
            with self._writer_lock:
                self._close_writer()
            timeline.finish()
            if source.get("status") != "needs_confirm":
                source["status"] = "ended"
            ended.set()

        self._thread = threading.Thread(target=run, name="vantage-live", daemon=True)
        self._thread.start()

    def _explain_connect_failure(self, source: dict[str, Any], host: str, port: int) -> None:
        """Name the likely cause of a failed first connection. Without the client
        certificate the game refuses every connection, which gRPC reports only as
        a timeout; retries go on, so files put in place are picked up."""
        missing = missing_cert_files()
        if missing:
            source["status"] = "needs_certs"
            self.error = f"certificate files missing from {certs_dir()}: {', '.join(missing)}"
            return
        source["status"] = "connecting"
        if port_open(host, port):
            self.error = (
                f"the game answers on port {port} but refused the secure connection;"
                f" check the certificate files in {certs_dir()}"
            )

    def _adopt_info(self, info: Any) -> None:
        """Game install, profile folder and enabled mods the live game reports."""
        game_dir = self.data.game_dir
        if game_dir is None:
            found = find_game_dir(info.base_directory)
            if found is not None:
                self.data = GameData(found, mods=self.data.mods)
                game_dir = found
        user = host_path(info.user_directory, game_dir) if info.user_directory else None
        if user is not None:
            self.source["user_directory"] = str(user)
            if user not in self.user_dirs:
                self.user_dirs.append(user)
            self.data.mods.profiles = [user]
        mods = [host_path(m, game_dir) for m in info.mods]
        self.data.mods.live_mods = [m for m in mods if m is not None]

    def set_game_dir(self, raw: str) -> dict[str, Any]:
        """Re-point game data at another install (the UI's ``lastUsedGameDirectory``).

        The folder must hold ``AoE2DE_s.exe``; an empty path is a no-op that
        reports the current install. Mod settings carry over.
        """
        text = (raw or "").strip()
        if not text:
            return {"ok": True, "game_dir": str(self.data.game_dir or "")}
        path = Path(text).expanduser()
        if not (path / "AoE2DE_s.exe").is_file():
            return {"ok": False, "error": "AoE2DE_s.exe not found in that folder"}
        if self.data.game_dir != path:
            old = self.data
            self.data = GameData(path, old.cache_dir, old.mode, old.mods)
            tl = self.timeline
            if tl is not None:
                tl.data = tl.catalog.data = self.data
        return {"ok": True, "game_dir": str(path)}

    def _ask_confirm(self, code: str) -> None:
        """The game wants the user's agreement first: stop and say so."""
        self.source["needs_confirm"] = True
        self.source["status"] = "needs_confirm"
        self.source["code"] = code

    def recording_path(self) -> Path | None:
        """The ``.vrec`` being written now, if any."""
        w = self._writer
        return w.path if w is not None else None

    def _close_writer(self) -> None:
        """Close the live recording (caller holds ``_writer_lock``)."""
        w = self._writer
        if w is None:
            return
        self._writer = None
        with contextlib.suppress(OSError):
            w.close()
        self.source["recording_saved"] = str(w.path)
        self.source["recording_active"] = False

    def set_recording(self, on: bool) -> dict[str, Any]:
        """Start or stop writing the live session to a ``.vrec``.

        Starting asks the game for a fresh stream, because a recording must
        begin with a full-state snapshot; the timeline continues seamlessly.
        """
        if self.mode != "live":
            return {"ok": False, "error": "recording needs a live session"}
        self._record_wanted = on
        with self._writer_lock:
            if not on:
                saved = self._writer.path if self._writer is not None else None
                self._close_writer()
                return {"ok": True, "recording": False, "saved": str(saved) if saved else None}
            if self._writer is not None:
                return {"ok": True, "recording": True, "path": str(self._writer.path)}
        live = self._live
        if live is not None:
            self._restart_stream = True
            with contextlib.suppress(Exception):
                live.cancel_frames()
        return {"ok": True, "recording": True, "pending": True}

    def _watch_waiting(self, stop: threading.Event) -> None:
        """Flag a stalled stream: no frames while the game is not paused or over
        means it waits for a lagging or dropped player."""
        stalled = False
        while not stop.wait(1.0):
            src = self.source
            idle = time.monotonic() - self._last_frame if self._last_frame else 0.0
            waiting = (
                self._live is not None
                and src.get("status") == "playing"
                and not src.get("paused")
                and idle >= WAITING_AFTER_S
            )
            src["waiting"] = round(idle, 1) if waiting else None
            tl = self.timeline
            if waiting and not stalled and tl is not None:
                tl.add_event(
                    {
                        "t": tl.time,
                        "cat": "status",
                        "kind": "waiting",
                        "seconds": round(idle, 1),
                        "players": [],
                    }
                )
            stalled = waiting

    def _watch_oracle(self, host: str, port: int, stop: threading.Event) -> None:
        """Game status side-channel: pause state (and who paused), screen, lobby,
        game state, and chat sent while the game is paused (no frames flow then)."""
        from vantage.live import LiveGame

        try:
            game = LiveGame(host, port).connect(timeout=5)
        except Exception:
            return
        self._oracle_game = game
        try:
            for msg in game.oracle():
                if stop.is_set():
                    return
                self.oracle_message(msg)
        except Exception:  # the frames loop owns reconnection; status is best effort
            return
        finally:
            game.close()

    #: ``ScreenState.Location``: the spectator lobby screen, the game screen.
    _SCREEN_LOBBY, _SCREEN_GAME = 5, 2
    #: ``GameState``: the match is on, the match is over.
    _GAME_PLAYING, _GAME_DONE = 2, 3

    def _match_over(self, timeline: Timeline | None) -> bool:
        """The match is over: the world says so, or the game's own state does (a replay
        that reached its end sets no ``gameEnded`` in the world)."""
        return bool(
            (timeline is not None and timeline.game_ended)
            or self.source.get("game_state") == self._GAME_DONE
        )

    def oracle_message(self, msg: dict[str, Any]) -> None:
        """Apply one Oracle status message to ``source``."""
        src = self.source
        kind = msg.get("kind")
        if kind == "gamepaused":
            src["paused"] = bool(msg.get("paused"))
            src["paused_by"] = msg.get("pausedbyplayerid")
        elif kind == "currentscreenstate":
            src["screen"] = msg.get("location", 0)
            if src["screen"] == self._SCREEN_LOBBY and src.get("status") != "playing":
                src["status"] = "waiting_lobby"
        elif kind == "currentwindowstate":
            src["window"] = msg.get("mode", 0)
        elif kind == "observerlobby":
            info = _lobby_info(msg.get("lobbyinfo") or {})
            src["lobby"] = {
                "id": src.get("lobby_id") or info.get("sessionid") or info.get("gameid"),
                "name": info.get("custommapname") or info.get("scenarioname") or "",
                "match_start_time": msg.get("matchstarttime"),
                "join_time": msg.get("jointime"),
                **info,
            }
            if src.get("status") != "playing":
                # Waiting for the lobby: in the spectator lobby, counting
                # down the spectator delay; "joining" is only the pending request.
                src["status"] = "waiting_lobby"
        elif kind == "observerleave":
            src["lobby"] = None
        elif kind == "gamestate":
            src["game_state"] = msg.get("value", 0)
            if src["game_state"] == self._GAME_DONE:
                src["status"] = "ended"
            elif src.get("status") == "ended" and src["game_state"] == self._GAME_PLAYING:
                src["status"] = "playing"  # the game started another match
        elif kind == "gametype":
            src["game_type"] = msg.get("value", 0)
        elif kind == "currentreplay":
            src["current_replay"] = msg.get("replayfile")
        elif kind == "gamechat":
            tl = self.timeline
            if tl is not None:
                # Every Oracle chat is logged at the newest world time, not
                # only while paused; the frame stream's copy is dropped.
                tl.oracle_chat(msg, paused=bool(src.get("paused")))

    # -- control (live only) --------------------------------------------------

    def control(self, action: str, value: Any) -> dict[str, Any]:
        game = self._live
        own: Any = None
        if game is None:
            if self.mode != "live":
                return {"ok": False, "error": "no live game connected"}
            # Between streams (reconnecting): commands still reach the game
            # over a short-lived connection of their own.
            from vantage.live import LiveGame

            try:
                game = own = LiveGame(self.source["host"], self.source["port"]).connect(timeout=3)
            except Exception as exc:
                return {"ok": False, "error": f"no live game connected ({exc})"}
        try:
            result = self._control(game, action, value)
            if action == "pause" and result.get("ok"):
                self.source["paused"] = bool(value)
                self.source["paused_by"] = None
            if action == "speed" and result.get("ok"):
                self._use_light_stream(str(value) in ("FAST", "EXTRA_FAST"))
            return result
        except Exception as exc:  # the stream may be reconnecting; report, don't crash
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        finally:
            if own is not None:
                own.close()

    def _use_light_stream(self, on: bool) -> None:
        """Switch the live stream between full detail and the fast-replay profile.
        The game reads the frame request once per stream, so this reopens it
        (one full snapshot, a few seconds on a large game)."""
        if on == self._light_stream:
            return
        self._light_stream = on
        live = self._live
        if live is not None:
            self._restart_stream = True
            with contextlib.suppress(Exception):
                live.cancel_frames()

    @staticmethod
    def _control(game: Any, action: str, value: Any) -> dict[str, Any]:
        if action == "pause":
            return {"ok": game.pause(bool(value))}
        if action == "speed":
            return {"ok": game.set_speed(str(value))}
        if action == "fog":
            return {"ok": game.set_fog(bool(value))}
        if action == "perspective":
            return {"ok": game.set_perspective(int(value))}
        if action == "window":
            return {"ok": game.set_window(str(value))}
        return {"ok": False, "error": f"unknown action {action!r}"}

    def live_connected(self) -> bool:
        return self._live is not None

    def stream_state(self) -> str | None:
        """The gRPC stream status for the launcher (``GameLauncher.status``):
        ``connected`` / ``connected-hiccup`` (frames stalled), ``closed-needs-update``
        (the game's API is newer than Vantage knows), or the last connection failure
        (``closed-player`` / ``closed-unavailable`` / ``closed-error``); None when
        Vantage is not following a live game."""
        if self._live is not None:
            if int(self.source.get("api_version") or 0) > MAX_API_VERSION:
                return "closed-needs-update"
            return "connected-hiccup" if self.source.get("waiting") else "connected"
        return self._stream_error if self.mode == "live" else None

    def _game_details(self, tl: Timeline | None) -> dict[str, Any] | None:
        """``{map_name, player_count}`` for "Ready to watch {map} | {N} players":
        from the loaded match, else from the lobby the live game reported."""
        lobby = self.source.get("lobby")
        if tl is not None and tl.match.get("players"):
            players = [p for pid, p in tl.match["players"].items() if pid > 0]
            name = tl.match.get("map_name") or ""
            if not name and tl.match.get("map_type") is not None:
                try:
                    name = load_map_names(self.data).get(int(tl.match["map_type"]), "")
                except (OSError, ValueError, TypeError):
                    name = ""
            name = name or tl.match.get("map_file") or ""
            if players:
                return {"map_name": name, "player_count": len(players)}
        if isinstance(lobby, dict) and (lobby.get("players") or lobby.get("name")):
            return {
                "map_name": str(lobby.get("map_name") or lobby.get("name") or ""),
                "player_count": len(lobby.get("players") or ()),
            }
        return None

    def describe(self) -> dict[str, Any]:
        tl = self.timeline
        lobby = self.source.get("lobby")
        if isinstance(lobby, dict) and tl is not None and "spectator_delay" in tl.match:
            lobby["spec_delay"] = tl.match["spectator_delay"]
        details = self._game_details(tl)
        if details is not None:
            self.source["game_details"] = details
        return {
            "mode": self.mode,
            "viewer_build": self.viewer_build,
            "server_instance": self.server_instance,
            "source": self.source,
            "error": self.error,
            "generation": self.generation,
            "live_connected": self._live is not None,
            "game_data": self.data.available,
            "game": self.data.game,
            "timeline": tl.status() if tl is not None else None,
            "installed_build": self.data.build,
            "game_dir": str(self.data.game_dir) if self.data.game_dir else "",
            # What live games and replays need, for the UI's setup hints.
            "certs": cert_status(),
        }


def _lobby_info(info: dict[str, Any]) -> dict[str, Any]:
    """``OracleMessage.LobbyInfo`` as the UI shows it (players from used slots)."""
    players = []
    for slot in info.get("slots") or ():
        used = slot.get("used") if isinstance(slot, dict) else None
        if used:
            players.append(
                {
                    "name": used.get("name", ""),
                    "team": used.get("teamid", 0),
                    "color": used.get("color", 0),
                    "civ": used.get("civid", 0),
                }
            )
    keep = (
        "sessionid", "gameid", "playercount", "spectatable", "spectatorcount", "ingame",
        "custommapname", "scenarioname", "rankedtype", "mapsize", "populationcap",
        "gamespeed", "victorytype", "server", "selectedgame",
    )  # fmt: skip
    out = {**{k: info[k] for k in keep if k in info}, "players": players}
    for key in ("teamslocked", "lockteams"):
        if key in info:
            out["teams_locked"] = bool(info[key])
    return out


def _json(
    handler: BaseHTTPRequestHandler,
    obj: Any,
    status: int = 200,
    headers: dict[str, str] | None = None,
) -> None:
    body = json.dumps(obj, separators=(",", ":"), default=str).encode()
    _json_body(handler, body, status, headers)


def _json_body(
    handler: BaseHTTPRequestHandler,
    body: bytes,
    status: int = 200,
    headers: dict[str, str] | None = None,
) -> None:
    """Send JSON that is already encoded."""
    body, headers = content_encoding(
        body, "application/json", handler.headers.get("Accept-Encoding", ""), headers
    )
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    for k, v in (headers or {}).items():
        handler.send_header(k, v)
    handler.end_headers()
    handler.wfile.write(body)


#: Browser caching of game assets: a day, or for good when the URL carries the
#: current :meth:`App.asset_version` (it then changes whenever the content can).
ASSET_MAX_AGE = "max-age=86400"
ASSET_IMMUTABLE = "max-age=31536000, immutable"


def asset_cache_control(query: dict[str, str], version: str) -> str:
    """``Cache-Control`` for a converted asset: immutable only when the request
    names the asset version in force (``av=``); an asset URL without it keeps
    its content across a game update, a Vantage update or a mod change."""
    return ASSET_IMMUTABLE if query.get("av") == version else ASSET_MAX_AGE


def _bytes(
    handler: BaseHTTPRequestHandler,
    body: bytes,
    ctype: str,
    cache: bool | str = False,
    headers: dict[str, str] | None = None,
) -> None:
    """Send ``body``; ``cache`` True caches it for a day, a string is the
    ``Cache-Control`` value itself."""
    body, headers = content_encoding(
        body, ctype, handler.headers.get("Accept-Encoding", ""), headers
    )
    handler.send_response(200)
    handler.send_header("Content-Type", ctype)
    handler.send_header("Content-Length", str(len(body)))
    control = cache if isinstance(cache, str) else ASSET_MAX_AGE if cache else "no-store"
    handler.send_header("Cache-Control", control)
    for k, v in (headers or {}).items():
        handler.send_header(k, v)
    handler.end_headers()
    handler.wfile.write(body)


def _error(
    handler: BaseHTTPRequestHandler,
    status: HTTPStatus = HTTPStatus.NOT_FOUND,
    headers: dict[str, str] | None = None,
) -> None:
    """A short error answer on the kept-alive connection. ``send_error`` closes it,
    and a cold battle scene asks for many sprites the game does not have: each
    then cost the browser a new connection out of its six."""
    body = status.phrase.encode()
    handler.send_response(status)
    handler.send_header("Content-Type", "text/plain")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    for k, v in (headers or {}).items():
        handler.send_header(k, v)
    handler.end_headers()
    handler.wfile.write(body)


def paired_origin_headers(handler: BaseHTTPRequestHandler) -> dict[str, str]:
    """CORS headers for the browser's second loopback origin.

    The page on ``127.0.0.1`` fetches sprites from ``localhost`` (and the other
    way round) for a second pool of six connections. Only this server's own port
    on a loopback name is allowed, never a wildcard: any web page could otherwise
    read the game data the local server serves. ``Vary`` is sent either way, so a
    cached copy without the header is never reused for the other origin.
    """
    out = {"Vary": "Origin"}
    origin = handler.headers.get("Origin")
    if not origin:
        return out
    address: Any = handler.server.server_address
    port = address[1]
    if origin in (
        f"http://127.0.0.1:{port}",
        f"http://localhost:{port}",
        f"http://[::1]:{port}",
    ):
        out["Access-Control-Allow-Origin"] = origin
        out["Access-Control-Expose-Headers"] = "X-Sprite-Meta"
    return out


class App:
    """Routes requests to the session. One instance per server."""

    def __init__(
        self,
        session: Session,
        replay_dirs: list[Path],
        follow_live: bool = True,
        plugins: Sequence[Any] = (),
        recording_only: bool = False,
        game_art: bool = True,
    ) -> None:
        self.session = session
        # Keep an immutable module graph for this process, even during a deploy.
        web = resources.files(WEB_PACKAGE).joinpath("web")
        self.web_assets: dict[str, bytes] = {}

        def collect(folder: Any, prefix: str = "") -> None:
            for item in folder.iterdir():
                name = prefix + item.name
                if item.is_dir():
                    collect(item, name + "/")
                else:
                    self.web_assets[name] = item.read_bytes()

        collect(web)
        #: Extensions from outside this package. A plugin may define
        #: ``get(app, handler, path, query)`` and ``post(app, handler, path, body)``,
        #: each returning True once it has answered the request; ``config(app,
        #: config)`` to add to ``/api/config``; and ``config_keys``, names only the
        #: server may set there.
        self.plugins = list(plugins)
        #: Replay folders given at start (``--replay-dir``, or detected).
        self.replay_dirs = replay_dirs
        #: Also list the replay folders of the profile the live game reports.
        self.follow_live = follow_live
        self.recording_only = recording_only
        self.game_art = game_art
        self._sprites: SpriteStore | None = None
        self._sprites_key: tuple[Any, ...] = ()
        #: ``/api/series`` as last encoded: (timeline, its version, body).
        self._series_cache: tuple[weakref.ref[Timeline], int, bytes] | None = None
        self._audio_lib: Any = None
        self._audio_lib_dir: Path | None = None
        self.data_dir = data_dir()
        self.images_dir = self.data_dir / "images"
        self.profiles_dir = self.data_dir / "profiles"
        self.skins_dir = self.data_dir / "skins"
        self.skins = SkinStore(self.skins_dir, self.data_dir / "skins-added.json")
        #: Starts the game through Steam (``/api/launch_game``); tests inject
        #: a launcher with a fake runner -- nothing here starts the game.
        self.launcher = GameLauncher(lambda: session.data.game_dir)
        #: Called when the browser reports the end of playback and the server
        #: was started with ``--exit-on-stream-end``.
        self.on_playback_ended: Any = None
        #: Replay headers keyed by (path, size, mtime); durations fill in from
        #: a background scan because reading them walks the whole file.
        self._replay_meta: dict[tuple[str, int, float], dict[str, Any]] = {}
        self._recording_headers: dict[tuple[str, int, int], dict[str, Any]] = {}
        self._replay_scan: threading.Thread | None = None
        #: Settings overrides pushed to every browser (``--patch-config``) and
        #: whether browsers should ignore their saved settings.
        self.client_config: dict[str, Any] = {"patch": {}, "force_default": False}

    # -- GET ------------------------------------------------------------------

    def get(self, h: BaseHTTPRequestHandler) -> None:
        url = urlparse(h.path)
        q = {k: v[0] for k, v in parse_qs(url.query).items()}
        path = url.path
        s = self.session
        tl = s.timeline
        if path in ("/", "/index.html"):
            return self._static(h, "index.html")
        if path.startswith("/static/"):
            return self._static(h, path[len("/static/") :])
        if not self.game_art and re.match(
            r"^/(?:icon/|emblem/|ui/|sprite/|terrain(?:/|-)|audio/|particle_atlas\.)", path
        ):
            if path.startswith(("/icon/", "/emblem/", "/ui/")):
                # Neutral, original placeholder: reserve image space without
                # serving game art or dropping the underlying game metadata.
                return _bytes(
                    h,
                    b'<svg xmlns="http://www.w3.org/2000/svg" width="36" height="36">'
                    b'<rect x="2" y="2" width="32" height="32" rx="4" '
                    b'fill="#24282c" stroke="#8b8679"/></svg>',
                    "image/svg+xml",
                )
            _error(h)
            return None
        for plugin in getattr(self, "plugins", ()):
            answer = getattr(plugin, "get", None)
            if answer is not None and answer(self, h, path, q):
                return None
        if path == "/api/session":
            desc = s.describe()
            if q.get("probe"):
                # The home screen asks whether the game is running before offering it.
                desc["game_api_open"] = (
                    False
                    if getattr(self, "recording_only", False)
                    else s.live_connected() or port_open()
                )
            return _json(h, desc)
        if getattr(self, "recording_only", False) and path == "/api/launch_game":
            return _json(
                h, {"ok": False, "error": "This session opens recordings without the game."}, 400
            )
        if path == "/api/match":
            return _json(h, tl.match if tl else {})
        if path == "/api/map":
            return _json(h, tl.map if tl and tl.map else {})
        if path == "/api/catalog":
            lang = q.get("lang", "en")
            cat = tl.catalog.to_json(lang) if tl else {"units": {}, "techs": {}}
            cat["color_grade_names"] = s.data.color_grade_names(lang)
            return _json(h, cat)
        if path == "/api/view":
            t = int(q["t"]) if q.get("t") not in (None, "") else None
            body = tl.view_json(t) if tl else None
            return _json_body(h, body or b"{}")
        m = re.match(r"^/api/unit/(-?\d+)$", path)
        if m:
            t = int(q["t"]) if q.get("t") else None
            since = max(0, int(q["since"])) if q.get("since") else None
            # Bind single-entity detail to the Timeline actually queried, as /api/group does.
            with s.lock:
                unit_timeline, generation = s.timeline, s.generation
            result = unit_timeline.unit_stats(int(m.group(1)), t, since) if unit_timeline else {}
            return _json(h, {**result, "generation": generation})
        if path == "/api/group":
            t = int(q["t"]) if q.get("t") else None
            since = max(0, int(q["since"])) if q.get("since") else None
            raw = (q.get("ids") or "").split(",")[:GROUP_MAX]
            ids = [int(x) for x in raw if x.lstrip("-").isdigit()]
            # Bind the response to the Timeline actually captured for this request.
            # Never hold the Session lock across Timeline work or socket writes.
            with s.lock:
                group_timeline, generation = s.timeline, s.generation
            result = group_timeline.group_stats(ids, t, since) if group_timeline else {}
            return _json(h, {**result, "generation": generation})
        m = re.match(r"^/api/techtree/(\d+)$", path)
        if m:
            tree = s.data.tech_tree(int(m.group(1)), q.get("lang", "en")) or {}
            if tree and tl is not None:
                _tree_costs(tree, tl)
            return _json(h, tree)
        if path == "/api/trees":
            got = tl.trees_at(int(q.get("t", 0))) if tl else None
            if got is None:
                return _json(h, {})
            import base64

            tiles = base64.b64encode(got[1]).decode()
            return _json(h, {"t": got[0], "tiles": tiles, "kinds": got[2]})
        if path == "/api/terrain":
            got_t = tl.terrain_at(int(q.get("t", 0))) if tl else None
            if got_t is None:
                return _json(h, {})
            import base64

            return _json(h, {"t": got_t[0], "tiles": base64.b64encode(got_t[1]).decode()})
        if path == "/api/events":
            if tl is None:
                return _json(h, [])
            t0 = int(q.get("from", 0))
            t1 = int(q.get("to", 1 << 62))
            return _json(h, tl.events_between(t0, t1))
        if path == "/api/series":
            if tl is None:
                return _json(h, {})
            raw_from = q.get("from") or ""
            if raw_from.lstrip("-").isdigit():
                # Rows the browser does not have yet (it drops its own from then on).
                return _json(h, tl.series_json(int(raw_from)))
            return _json_body(h, self._series_body(tl))
        if path == "/api/summary":
            t_q = int(q["t"]) if q.get("t") not in (None, "") else None
            return _json(h, tl.summary(t_q) if tl else {})
        if path == "/api/images":
            return _json(h, self._images())
        if path == "/api/skins":
            return _json(h, self.skins.rows())
        if path == "/api/skins/version":
            return _json(h, {"version": self.skins.version()})
        if path == "/api/launch_game":
            return _json(h, self._launch_status())
        if path == "/api/skins/merged":
            names = [n for n in q.get("enabled", "").split(",") if n]
            return _json(h, self.skins.merged(names))
        if path == "/sse":
            return self._sse(h)
        if path == "/stats-dump":
            return _json(h, self._stats_dump())
        m = re.match(r"^/skins/([\w -]{1,40})/([\w./ -]{1,120})$", unquote(path))
        if m:
            return self._skin_file(h, m.group(1), m.group(2))
        if path == "/api/mods":
            return _json(h, self._mods_state())
        if path == "/api/recordings":
            return _json(h, self._recordings())
        if path == "/api/replays":
            return _json(h, self._replays())
        if path == "/api/review-moments":
            return _json(h, self._review_moments_load())
        if path == "/api/bookmarks":
            return _json(h, self._bookmarks_load())
        if path == "/api/stream":
            return self._stream(h)
        m = re.match(r"^/icon/(unit|building|tech)/(-?\d+)\.png$", path)
        if m:
            png = s.data.icon_png(m.group(1), int(m.group(2)))
            if png is None:
                _error(h)
                return None
            return _bytes(h, png, "image/png", cache=self._asset_cache(q))
        m = re.match(r"^/sprite/(\d+)/(\d+)/(-?\d+)\.(png|json)$", path)
        if m:
            hd = q.get("hd") == "1"
            return self._sprite(
                h, int(m.group(1)), int(m.group(2)), int(m.group(3)), m.group(4), hd, q
            )
        m = re.match(r"^/images/([\w.-]+\.(?:png|jpe?g|gif|webp|svg))$", path)
        if m:
            f = self.images_dir / m.group(1)
            if not f.is_file():
                _error(h)
                return None
            ctype = mimetypes.guess_type(f.name)[0] or "application/octet-stream"
            return _bytes(h, f.read_bytes(), ctype, cache=True)
        if path == "/api/config":
            # Also the browser's probe of the second loopback origin (CORS).
            # Some keys are the server's to say (a forced config cannot claim them).
            plugins = getattr(self, "plugins", ())
            reserved = {key for plugin in plugins for key in getattr(plugin, "config_keys", ())}
            config = {
                **{k: v for k, v in self.client_config.items() if k not in reserved},
                "version": __version__,
            }
            config["asset_version"] = self.asset_version()
            config["viewer_build"] = self.session.viewer_build
            config["server_instance"] = self.session.server_instance
            config["game_art"] = self.game_art
            for plugin in plugins:
                extend = getattr(plugin, "config", None)
                if extend is not None:
                    extend(self, config)
            return _json(h, config, headers=paired_origin_headers(h))
        m = re.match(r"^/audio/(event|taunt|notify)/([\w-]+)\.ogg$", path)
        if m:
            voice = q.get("lang") if m.group(1) == "taunt" else None
            return self._audio(h, m.group(1), m.group(2), int(q.get("v", 0) or 0), voice)
        if path == "/api/profiles":
            return _json(h, sorted(p.stem for p in self.profiles_dir.glob("*.json")))
        m = re.match(r"^/api/profile/([\w -]{1,40})$", unquote(path))
        if m:
            f = self.profiles_dir / f"{m.group(1)}.json"
            if not f.is_file():
                _error(h)
                return None
            return _bytes(h, f.read_bytes(), "application/json")
        if path == "/api/particles":
            return _json(h, s.data.particle_definitions_table() if self.game_art else {})
        if path in ("/particle_atlas.png", "/particle_atlas.json"):
            got_atlas = s.data.particle_atlas(q.get("path", ""))
            if got_atlas is None:
                _error(h)
                return None
            img, mime, meta = got_atlas
            control = self._asset_cache(q)
            if path.endswith(".json"):
                return _bytes(h, json.dumps(meta).encode(), "application/json", cache=control)
            return _bytes(h, img, mime, cache=control)
        m = re.match(r"^/terrain/([\w-]+)\.png$", path)
        if m:
            png = s.data.terrain_png(m.group(1))
            if png is None:
                _error(h)
                return None
            return _bytes(h, png, "image/png", cache=self._asset_cache(q))
        m = re.match(r"^/terrain-mask/([\w-]+)\.png$", path)
        if m:
            mask = s.data.terrain_mask_png(m.group(1))
            if mask is None:
                _error(h)
                return None
            return _bytes(h, mask, "image/png", cache=self._asset_cache(q))
        m = re.match(r"^/ui/material/([\w-]+)\.png$", path)
        if m:
            mat = s.data.material_png(m.group(1))
            if mat is None:
                _error(h)
                return None
            return _bytes(h, mat.read_bytes(), "image/png", cache=self._asset_cache(q))
        m = re.match(r"^/ui/([\w-]+)\.png$", path)
        if m and s.data.game_dir is not None:
            # A game mode's own HUD art (Return of Rome age icons) wins.
            for root in s.data.roots():
                f = root / "widgetui" / "textures" / "ingame" / "icons" / f"{m.group(1)}.png"
                if f.is_file():
                    # Not cached by the browser: the same URL differs per game,
                    # unless it names the asset version (which includes the game).
                    versioned = q.get("av") == self.asset_version()
                    return _bytes(
                        h, f.read_bytes(), "image/png", cache=versioned and ASSET_IMMUTABLE
                    )
            _error(h)
            return None
        m = re.match(r"^/emblem/(\d+)\.png$", path)
        if m:
            png = s.data.emblem_png(int(m.group(1)))
            if png is None:
                _error(h)
                return None
            return _bytes(h, png, "image/png", cache=self._asset_cache(q))
        _error(h)
        return None

    def _launch_status(self) -> dict[str, Any]:
        """The launcher status with the live gRPC stream state fed in, so the game
        running as a player account / needing a newer app are reachable statuses."""
        stream = self.session.stream_state()
        connected = stream in ("connected", "connected-hiccup")
        return self.launcher.status(connected, stream)

    def asset_version(self) -> str:
        """What every converted asset depends on besides its URL: Vantage and its
        sprite renderer, the installed build, the game mode and the mod folders in
        use. Asset URLs carrying it (``av=``) are cached by the browser for good."""
        data = self.session.data
        mods = (data.mod_roots("graphics"), data.mod_roots("sprites"), data.mod_roots("terrain"))
        parts = (
            __version__,
            # The server-side code, not the whole deployment: an interface change
            # (most changes) leaves every cached asset valid.
            self.session.asset_build,
            RENDER_VERSION,
            data.build,
            data.game_dir,
            data.mode,
            mods,
            self.game_art,
        )
        return hashlib.sha1(repr(parts).encode()).hexdigest()[:12]

    def _asset_cache(self, query: dict[str, str]) -> str:
        return asset_cache_control(query, self.asset_version())

    def _series_body(self, tl: Timeline) -> bytes:
        """``/api/series`` encoded, kept until the timeline's next version: 4-5 MB
        late in a game, asked for by every refresh of the statistics screens."""
        version = tl.version
        cached = self._series_cache
        if cached is not None and cached[0]() is tl and cached[1] == version:
            return cached[2]
        body = json.dumps(tl.series_json(), separators=(",", ":"), default=str).encode()
        # A weak reference: a replaced timeline is freed, never mistaken for the next.
        self._series_cache = (weakref.ref(tl), version, body)
        return body

    def _store(self) -> SpriteStore | None:
        """The sprite store for the current game folder and enabled mods."""
        data = self.session.data
        if data.game_dir is None:
            return None
        mods = list(dict.fromkeys(data.mod_roots("graphics") + data.mod_roots("sprites")))
        key = (data.game_dir, data.mode, tuple(mods))
        store = self._sprites
        if store is None or store.graphics is None or self._sprites_key != key:
            store = self._sprites = _sprite_store(data, mods)
            self._sprites_key = key
        return store

    def _sprite(
        self,
        h: BaseHTTPRequestHandler,
        sid: int,
        facet: int,
        color: int,
        kind: str,
        hd: bool = False,
        query: dict[str, str] | None = None,
    ) -> None:
        tl = self.session.timeline
        entry = tl.sprites.get(sid) if tl is not None else None
        data = self.session.data
        store = self._store() if entry is not None else None
        # Errors too: a cross-origin 404 without them reads as a network failure.
        cors = paired_origin_headers(h)
        if entry is None or store is None:
            _error(h, headers=cors)
            return
        info = SpriteInfo(sid, *entry)
        rgb = data.player_colors[color % 8] if color >= 0 else None
        # Damage level, single-layer and player-mask variants (``&dmg=``,
        # ``&layer=``, ``&pm=``).
        got = store.strip(info, facet, rgb, str(color), hd, **strip_options(query or {}))
        if got is None:
            _error(h, headers=cors)
            return
        png, meta = got
        control = self._asset_cache(query or {})
        if kind == "json":
            body = json.dumps(meta).encode()
            _bytes(h, body, "application/json", cache=control, headers=cors)
        else:
            # The strip's layout rides along: one request per strip, not two (the
            # browser keeps only 6 connections to a host; a cold battle scene
            # needs hundreds of strips).
            meta_h = json.dumps(meta, separators=(",", ":"))
            headers = {"X-Sprite-Meta": meta_h, **cors}
            _bytes(h, png, "image/png", cache=control, headers=headers)

    def _audio(
        self,
        h: BaseHTTPRequestHandler,
        kind: str,
        ident: str,
        variant: int,
        language: str | None = None,
    ) -> None:
        from vantage.audio import NOTIFICATION_EVENTS, AudioLibrary, taunt_event

        data = self.session.data
        if self._audio_lib is None or self._audio_lib_dir != data.game_dir:
            self._audio_lib = AudioLibrary(data.game_dir, data.cache_dir)
            self._audio_lib_dir = data.game_dir
        event: int | None = None
        if kind == "event" and ident.isdigit():
            event = int(ident)
        elif kind == "taunt" and ident.isdigit():
            event = taunt_event(int(ident))
        elif kind == "notify":
            event = NOTIFICATION_EVENTS.get(ident)
        got = (
            self._audio_lib.event_audio(event, variant, language=language)
            if event is not None
            else None
        )
        if got is None:
            _error(h)
            return
        body, mime = got
        _bytes(h, body, mime, cache=True)

    def _static(self, h: BaseHTTPRequestHandler, name: str) -> None:
        # On Windows a drive or UNC path (C:/x, \\host\x) would escape web/.
        if ".." in name or name.startswith("/") or ":" in name or "\\" in name:
            _error(h, HTTPStatus.BAD_REQUEST)
            return
        versioned = False
        version, sep, rest = name.partition("/")
        if sep and re.fullmatch(r"[0-9a-f]{16}", version):
            if version != self.session.viewer_build:
                return _error(h, HTTPStatus.GONE)
            name, versioned = rest, True
        body = self.web_assets.get(name)
        if body is None:
            return _error(h)
        ctype = mimetypes.guess_type(name)[0] or "application/octet-stream"
        if name == "index.html":
            # Fetch the actual initial module graph in parallel, without
            # downloading optional editors/workers that boot does not import.
            found, pending = set(), ["app.js"]
            while pending:
                module = pending.pop()
                if module in found or module not in self.web_assets:
                    continue
                found.add(module)
                for relative in re.findall(
                    rb"(?:from\s*|import\s*)['\"](\./[^'\"]+\.js)['\"]", self.web_assets[module]
                ):
                    pending.append(str(Path(module).parent / relative.decode()))
            links = b"".join(
                f'<link rel="modulepreload" href="/static/{module}">'.encode()
                for module in sorted(found)
            )
            body = body.replace(b"</head>", links + b"</head>")
            body = body.replace(b"/static/", f"/static/{self.session.viewer_build}/".encode())
        _bytes(h, body, ctype, cache=ASSET_IMMUTABLE if versioned else False)

    def _stream(self, h: BaseHTTPRequestHandler) -> None:
        h.send_response(200)
        h.send_header("Content-Type", "text/event-stream")
        h.send_header("Cache-Control", "no-store")
        h.end_headers()
        last: tuple[Any, ...] = ()
        last_push = 0.0
        skins_seen = self.skins.version()
        try:
            while True:
                tl = self.session.timeline
                ver = tl.version if tl else -1
                skins_now = self.skins.version()
                if skins_now != skins_seen:
                    skins_seen = skins_now
                    h.wfile.write(b"event: skins\ndata: update\n\n")
                    h.wfile.flush()
                desc = self.session.describe()
                # The source status too: the launch card follows connecting ->
                # loading -> ready, and needs_certs / ended, between frames.
                src = desc.get("source") or {}
                key = (
                    self.session.generation,
                    ver,
                    desc["error"],
                    desc["live_connected"],
                    src.get("status"),
                    src.get("phase"),
                )
                wait = push_wait(key, last, last_push, time.monotonic())
                if wait:
                    # Only the timeline version moved, and too soon: look again
                    # then, and send the state as it is by that time.
                    time.sleep(wait)
                    continue
                if wait == 0:
                    h.wfile.write(f"data: {json.dumps(desc, default=str)}\n\n".encode())
                    h.wfile.flush()
                    last = key
                    last_push = time.monotonic()
                if tl is not None and not tl.complete:
                    tl.wait_change(ver, 1.0)
                elif tl is not None and tl.version != ver:
                    # It finished after this state was read: send the final
                    # state now, not after a keep-alive (the browser may be gone).
                    continue
                else:
                    time.sleep(1.0)
                    h.wfile.write(b": keepalive\n\n")
                    h.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            return

    def _sse(self, h: BaseHTTPRequestHandler) -> None:
        """Skin-debugging event stream (``/sse``):
        ``data: update`` (also as ``event: skins``) whenever an enabled skin's
        files change, so a browser can live-reload the skin CSS."""
        h.send_response(200)
        h.send_header("Content-Type", "text/event-stream")
        h.send_header("Cache-Control", "no-store")
        h.end_headers()
        seen = self.skins.version()
        try:
            h.wfile.write(b"retry: 1000\n\n")
            h.wfile.flush()
            while True:
                time.sleep(0.5)
                now = self.skins.version()
                if now != seen:
                    seen = now
                    h.wfile.write(b"event: skins\ndata: update\n\n")
                else:
                    h.wfile.write(b": keepalive\n\n")
                h.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            return

    def _stats_dump(self) -> dict[str, Any]:
        """Everything the statistics screens show, as one JSON document
        (``/stats-dump``): match, summary, series, events, status."""
        tl = self.session.timeline
        if tl is None:
            return {"session": self.session.describe(), "match": {}, "summary": {}}
        return {
            "session": self.session.describe(),
            "match": tl.match,
            "status": tl.status(),
            "summary": tl.summary(),
            "series": tl.series_json(),
            "events": tl.events_between(0, 1 << 62),
        }

    # -- POST -----------------------------------------------------------------

    def post(self, h: BaseHTTPRequestHandler) -> None:
        n = int(h.headers.get("Content-Length", 0) or 0)
        body: dict[str, Any] = json.loads(h.rfile.read(n) or b"{}") if n else {}
        path = urlparse(h.path).path
        s = self.session
        try:
            if getattr(self, "recording_only", False) and path in {
                "/api/live",
                "/api/play_replay",
                "/api/launch_game",
                "/api/record",
                "/api/game_dir",
            }:
                return _json(
                    h,
                    {"ok": False, "error": "This session opens recordings without the game."},
                    400,
                )
            if getattr(self, "recording_only", False) and path == "/api/open_url":
                target = str(body.get("url", ""))
                if not target.lower().endswith(".vrec") or not Path(target).expanduser().is_file():
                    return _json(
                        h,
                        {"ok": False, "error": "This session opens recordings without the game."},
                        400,
                    )
            for plugin in getattr(self, "plugins", ()):
                answer = getattr(plugin, "post", None)
                if answer is not None and answer(self, h, path, body):
                    return None
            if path == "/api/open":
                s.open_recording(str(body["path"]))
                return _json(h, {"ok": True})
            if path == "/api/live":
                game = body.get("game")
                s.open_live(
                    host=body.get("host", "127.0.0.1"),
                    port=int(body.get("port", 4341)),
                    replay=body.get("replay"),
                    lobby=body.get("lobby"),
                    record=bool(body.get("record", True)),
                    game=int(game) if game is not None else None,
                    confirm=bool(body.get("confirm", False)),
                    cloud=bool(body.get("cloud", False)),
                    lobby_source=body.get("source"),
                )
                if body.get("replay") or body.get("lobby") or game is not None:
                    return _json(h, self._await_load())
                return _json(h, {"ok": True})
            if path == "/api/play_replay":
                name, where = str(body["name"]), body.get("dir")
                win = self._windows_replay_path(name, where)
                found = next(
                    d
                    for d in self._replay_dir_list()
                    if (d / name).is_file() and (where is None or str(d) == str(where))
                )
                ror = _replay_dir_mode(found) == "Pompeii"
                # Never confirm on the user's behalf: a "needs confirmation"
                # answer goes back to the browser, which asks and resends.
                s.open_live(
                    replay=win,
                    record=bool(body.get("record", True)),
                    game=GAME_ROR if ror else GAME_AOE2,
                    confirm=bool(body.get("confirm", False)),
                )
                return _json(h, {**self._await_load(), "path": win})
            if path == "/api/skins/add":
                return _json(h, self.skins.add(str(body["path"]), body.get("kind")))
            if path == "/api/skins/remove":
                return _json(h, self.skins.remove(str(body["name"])))
            if path == "/api/launch_game":
                return _json(h, self.launcher.launch(self.session.live_connected()))
            if path == "/api/record":
                return _json(h, s.set_recording(bool(body.get("on", True))))
            if path == "/api/mods":
                return _json(h, self._set_mods(body))
            if path == "/api/game_dir":
                return _json(h, s.set_game_dir(str(body.get("path", ""))))
            if path == "/api/open_url":
                return _json(h, self._open_url(str(body.get("url", ""))))
            if path == "/api/playback_ended":
                if self.on_playback_ended is not None and s.mode == "recording":
                    self.on_playback_ended()
                    return _json(h, {"ok": True, "exiting": True})
                return _json(h, {"ok": True, "exiting": False})
            if path == "/api/profile":
                # Named settings profiles, kept locally (share the folder or
                # export the file to carry them to another machine).
                name = str(body.get("name", "")).strip()
                if not re.fullmatch(r"[\w -]{1,40}", name) or not isinstance(
                    body.get("settings"), dict
                ):
                    return _json(h, {"ok": False, "error": "bad profile name or settings"})
                self.profiles_dir.mkdir(parents=True, exist_ok=True)
                (self.profiles_dir / f"{name}.json").write_text(
                    json.dumps(body["settings"]), encoding="utf-8"
                )
                return _json(h, {"ok": True})
            if path == "/api/open_folder":
                return _json(h, self._open_folder(str(body.get("which", ""))))
            if path == "/api/control":
                return _json(h, s.control(str(body["action"]), body.get("value")))
            if path == "/api/stop":
                s.stop()
                return _json(h, {"ok": True})
            if path == "/api/review-moments":
                with s.lock:
                    if body.get("generation") != s.generation:
                        raise ValueError("Replay changed; reload review moments")
                    rows = normalize_moments(body.get("moments"))
                    bookmarks_file = self._bookmarks_file()
                    if bookmarks_file is None:
                        raise ValueError("Record this session before saving review moments")
                    moments_file = Path(
                        str(bookmarks_file).removesuffix(".bookmarks.json") + ".moments.json"
                    )
                    temporary = moments_file.with_suffix(moments_file.suffix + ".tmp")
                    temporary.write_text(json.dumps(rows))
                    temporary.replace(moments_file)
                return _json(h, {"ok": True})
            if path == "/api/bookmarks":
                self._bookmarks_save(body.get("bookmarks", []))
                return _json(h, {"ok": True})
        except (KeyError, ValueError, OSError) as exc:
            return _json(h, {"ok": False, "error": f"{type(exc).__name__}: {exc}"}, 400)
        _error(h)
        return None

    # -- files ----------------------------------------------------------------

    def _recordings(self) -> list[dict[str, Any]]:
        out = []
        d = self.session.recordings_dir
        data = self.session.data
        live = self.session.recording_path()
        unread: list[Path] = []
        for p in sorted(d.glob("*.vrec"), key=lambda p: p.stat().st_mtime, reverse=True):
            st = p.stat()
            # Headers are kept per file as it is on disk: a listing of a hundred
            # recordings then opens no gzip stream at all (the list is asked for
            # on every home-screen open).
            key = (str(p), st.st_size, st.st_mtime_ns)
            hdr = self._recording_headers.get(key)
            if hdr is None:
                try:
                    hdr = read_header(p)
                except (OSError, ValueError, EOFError):
                    continue
                self._recording_headers[key] = hdr
            # Who played and on what map (recording_summary): cached, else read
            # in the background and present on a later listing. Not the file
            # being written now: it changes with every frame.
            known = self.session.summaries.enabled
            summary = recording_summary.load(data.cache_dir, p) if known else None
            if known and summary is None and p != live:
                unread.append(p)
            out.append(
                {
                    "path": str(p),
                    "name": p.name,
                    "size": st.st_size,
                    "mtime": st.st_mtime,
                    "header": hdr,
                    "summary": summary,
                    "summary_pending": known and summary is None and p != live,
                }
            )
        self.session.summaries.request(data.cache_dir, data.game_dir, unread)
        return out

    def _await_load(self, timeout: float = 4.0) -> dict[str, Any]:
        """Wait briefly for the game's answer to a load/switch request.

        A request that needs the user's agreement comes back at once; a load
        that is going ahead keeps running in the background.
        """
        deadline = time.monotonic() + timeout
        src = self.session.source
        while time.monotonic() < deadline:
            if src.get("needs_confirm"):
                return {"ok": False, "needs_confirm": True, "code": src.get("code")}
            if "load_result" in src:
                result = src["load_result"]
                return {"ok": result == "SUCCESS", "load_result": result, "code": result}
            if not src.get("replay") and src.get("status") in ("ready", "playing"):
                return {"ok": True, "switch_result": src.get("switch_result")}
            if src.get("status") == "needs_certs":
                return {"ok": False, "needs_certs": True, "error": self.session.error}
            if self.session.error and src.get("status") == "connecting":
                return {"ok": False, "error": self.session.error}
            time.sleep(0.05)
        return {"ok": True, "pending": True}

    def _replay_dir_list(self) -> list[Path]:
        """Configured replay folders plus the live game's profile folders."""
        dirs = list(self.replay_dirs)
        if self.follow_live and self.session.user_dirs:
            dirs += [d for d in replay_dirs(self.session.user_dirs) if d not in dirs]
        return dirs

    def _replays(self) -> list[dict[str, Any]]:
        """Replays in the profile folders with their lobby header: players,
        civs, map, mode, version and (once scanned) duration.

        ``version_state`` compares a replay's build with the installed game
        (``AoE2DE_s.exe``'s FileVersion): ``current``, ``old``, or ``unknown``
        (no build in the replay, no installed build, or a newer build).
        """
        out: list[dict[str, Any]] = []
        pending: list[tuple[tuple[str, int, float], Path]] = []
        for d in self._replay_dir_list():
            data = self.session.data.with_mode(_replay_dir_mode(d))
            map_names = load_map_names(data)
            for p in d.glob("*.aoe2record"):
                st = p.stat()
                key = (str(p), st.st_size, st.st_mtime)
                meta = self._replay_meta.get(key)
                if meta is None:
                    try:
                        info = read_replay(p, with_duration=False, map_names=map_names)
                        meta = _replay_summary(info.to_json(), data)
                        if not meta.get("players"):
                            meta["missing_data"] = True  # header read, nothing in it
                    except (ReplayError, OSError, ValueError) as exc:
                        meta = {"error": str(exc), "missing_data": True}
                    self._replay_meta[key] = meta
                if "error" not in meta and "duration_ms" not in meta:
                    pending.append((key, p))
                out.append(
                    {
                        "name": p.name,
                        "dir": str(d),
                        "size": st.st_size,
                        "mtime": st.st_mtime,
                        **meta,
                    }
                )
        out.sort(key=lambda r: -float(r["mtime"]))
        builds = [int(r["build"]) for r in out if r.get("build")]
        newest = max(builds) if builds else None
        installed = self.session.data.build
        target = installed if installed is not None else newest
        for r in out:
            build = r.get("build")
            r["newest_build"] = newest
            r["installed_build"] = installed
            # True when the replay matches the installed game (or, with no
            # install found, the newest replay build).
            r["current_build"] = target is not None and build == target
            if not build or installed is None:
                r["version_state"] = "current" if r["current_build"] else "unknown"
            elif build == installed:
                r["version_state"] = "current"
            elif int(build) < installed:
                r["version_state"] = "old"
            else:
                r["version_state"] = "unknown"
        if pending and (self._replay_scan is None or not self._replay_scan.is_alive()):
            self._replay_scan = threading.Thread(
                target=self._scan_durations, args=(pending,), name="vantage-replays", daemon=True
            )
            self._replay_scan.start()
        return out

    def _scan_durations(self, pending: list[tuple[tuple[str, int, float], Path]]) -> None:
        for key, p in pending:
            try:
                info = read_replay(p, with_duration=True)
            except (ReplayError, OSError, ValueError):
                self._replay_meta[key] = {**self._replay_meta.get(key, {}), "duration_ms": None}
                continue
            meta = self._replay_meta.get(key, {})
            # Ratings come from the post-game record at the end of the file.
            by_number = {pl.number: pl for pl in info.players}
            players = [
                {
                    **row,
                    "elo": by_number[row["number"]].elo if row.get("number") in by_number else None,
                    "ratings": [list(r) for r in by_number[row["number"]].ratings]
                    if row.get("number") in by_number
                    else [],
                }
                for row in meta.get("players", [])
            ]
            self._replay_meta[key] = {
                **meta,
                "players": players,
                "duration_ms": info.duration_ms,
                "complete": info.has_postgame,
                "winners": list(info.winners),
                "resigned": [[num, ms] for num, _, ms in info.resigned],
            }

    def _open_folder(self, which: str) -> dict[str, Any]:
        """Show the game profile (replays) or the recordings folder in the file manager."""
        import shutil
        import subprocess

        dirs = self._replay_dir_list()
        if which == "recordings":
            folder: Path | None = self.session.recordings_dir
        elif which == "profile":
            folder = _profile_of(dirs[0]) if dirs else None
        elif which == "images":
            folder = self.images_dir
            folder.mkdir(parents=True, exist_ok=True)
        elif which == "skins":
            folder = self.skins_dir
            folder.mkdir(parents=True, exist_ok=True)
        else:
            return {"ok": False, "error": f"unknown folder {which!r}"}
        if sys.platform == "win32":
            if folder is None or not folder.is_dir():
                return {"ok": False, "error": "folder not available", "path": str(folder)}
            try:
                os.startfile(folder)  # Explorer
            except OSError as e:
                return {"ok": False, "error": str(e), "path": str(folder)}
            return {"ok": True, "path": str(folder)}
        opener = shutil.which("xdg-open")
        if folder is None or not folder.is_dir() or opener is None:
            return {"ok": False, "error": "folder or xdg-open not available", "path": str(folder)}
        subprocess.Popen(  # fixed program, fixed folder: no user-supplied paths
            [opener, str(folder)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        return {"ok": True, "path": str(folder)}

    def _windows_replay_path(self, name: str, where: Any = None) -> str:
        """The path of a savegame replay as the game (under Proton, or natively
        on Windows) sees it."""
        dirs = [d for d in self._replay_dir_list() if where is None or str(d) == str(where)]
        for d in dirs:
            if (d / name).is_file():
                return windows_path(d / name)
        raise KeyError(name)

    # -- user content ---------------------------------------------------------

    def _images(self) -> list[str]:
        """Casting images (flags, logos) in ``<data dir>/images``."""
        if not self.images_dir.is_dir():
            return []
        return sorted(
            p.name for p in self.images_dir.iterdir() if p.is_file() and _IMAGE_RE.fullmatch(p.name)
        )

    def _skin_file(self, h: BaseHTTPRequestHandler, name: str, rel: str) -> None:
        got = self.skins.file(name, rel)
        if got is None:
            _error(h)
            return
        _bytes(h, got[0], got[1])

    def _mods_state(self) -> dict[str, Any]:
        data = self.session.data
        return {
            "ok": True,
            "enabled": dict(data.mods.enabled),
            "roots": {k: [str(p) for p in data.mod_roots(k)] for k in data.mods.enabled},
            "dirs": [str(p) for p in data.mods.extra],
        }

    def _set_mods(self, body: dict[str, Any]) -> dict[str, Any]:
        """Which mod content to read (``graphics``/``sprites``/``terrain`` flags)
        and extra mod folders (``dirs``, the UI's ``modDirectories``)."""
        mods = self.session.data.mods
        for kind in mods.enabled:
            if kind in body:
                mods.enabled[kind] = bool(body[kind])
        dirs = body.get("dirs", body.get("modDirectories"))
        if isinstance(dirs, list):
            mods.extra = [Path(str(d)).expanduser() for d in dirs if str(d).strip()]
        return self._mods_state()

    def _open_url(self, url: str) -> dict[str, Any]:
        """A ``vantage://``/``captureage://`` link or a ``.vrec`` path from a
        second ``vantage open-url`` (this server is the single instance)."""
        from vantage.cli import live_request

        if url.lower().endswith(".vrec") and Path(url).expanduser().is_file():
            self.session.open_recording(url)
            return {"ok": True, "opened": url}
        if getattr(self, "recording_only", False):
            return {"ok": False, "error": "This session opens recordings without the game."}
        req = live_request(url)
        if req is None:
            return {"ok": False, "error": f"not a spectate link: {url!r}"}
        self.session.open_live(**req)
        return {"ok": True, **{k: v for k, v in req.items() if v is not None}}

    def _bookmarks_file(self) -> Path | None:
        src = self.session.source
        p = src.get("path") or src.get("recording") or src.get("recording_saved")
        return Path(str(p) + ".bookmarks.json") if p else None

    def _review_moments_load(self) -> list[dict[str, Any]]:
        target = self._bookmarks_file()
        if target is None:
            return []
        target = Path(str(target).removesuffix(".bookmarks.json") + ".moments.json")
        try:
            return normalize_moments(json.loads(target.read_text()))
        except (OSError, ValueError):
            return []

    def _bookmarks_load(self) -> list[Any]:
        f = self._bookmarks_file()
        if f is None or not f.is_file():
            return []
        try:
            data: list[Any] = json.loads(f.read_text(encoding="utf-8"))
            return data
        except ValueError:
            return []

    def _bookmarks_save(self, marks: list[Any]) -> None:
        f = self._bookmarks_file()
        if f is not None:
            f.write_text(json.dumps(marks), encoding="utf-8")


def replay_duration(windows_path: str, data: GameData) -> int | None:
    """Game-clock length of a replay the game is asked to play (None if unreadable)."""
    p = host_path(windows_path, data.game_dir)
    if p is None or not p.is_file():
        return None
    try:
        return read_replay(p, with_duration=True).duration_ms
    except (OSError, ValueError, EOFError, ReplayError):
        return None


#: The frame stream while the game replays at FAST / EXTRA_FAST. Building 100 ms
#: patches is much of the game's own work late in a large game: measured on a
#: 6-player replay at minute 40, the game ran 5.1 game s/s with 100 ms frames,
#: 8.3-8.8 with 1000 ms, and 9.4-11.4 with these settings and the game minimized
#: (8x is 13.6). Frames between views are the units' tracks (Timeline
#: _track_units): on an 8-player 47-minute replay at extra fast (2026-10-19),
#: 1000 / 500 / 250 ms took 343 / 361 / 401 s for the whole game (minute 30+:
#: 4.9 / 4.6 / 4.2 game s/s) and drew a moving unit facing the wrong way 7.0 /
#: 4.7 / 4.3 % of the time. 500 ms takes most of the gain for 5 % of the speed.
LIGHT_STREAM_MS = 500
#: FramesRequest categories 1 (low priority) and 2 (sleeping units) at 2 s.
LIGHT_STREAM_CATEGORIES = {1: 2000, 2: 2000}
#: Particle effects kept in the light stream: the ones that show game state
#: (research under way, burning or smoking buildings, explosions and impacts,
#: conversions, construction, upgrades, relics). Cosmetic high-volume ones
#: (blood, dust trails, footprints, wakes, butterflies, villagers' work dust)
#: are what cost the game its fast-replay speed.
LIGHT_STREAM_PARTICLES = (
    "building_research",
    "smoke_chimney",
    "fire_",
    "smoke_large",
    "smoke_medium",
    "explosion",
    "impact_",
    "unit_conversion",
    "construction_",
    "upgrade",
    "relic_glow",
    "building_levelup",
)


def light_particles(definitions: list[str]) -> list[str]:
    """The particle definitions the light stream still asks the game for."""
    return [d for d in definitions if d.startswith(LIGHT_STREAM_PARTICLES)]


def keyframe_step(busy: float, current: int) -> int:
    """Keyframe spacing for a live timeline that spends ``busy`` (0..1) of the
    wall time processing frames: 2 s once it saturates, back to 1 s with headroom
    (hysteresis so it does not flap)."""
    from vantage.timeline import KEYFRAME_MS

    if busy > 0.8:
        return 2 * KEYFRAME_MS
    if busy < 0.5:
        return KEYFRAME_MS
    return current


#: ``SelectedGameInfo.enumvalue`` / ``SetDesiredGame`` ids (measured live).
GAME_ROR, GAME_AOE2 = 1, 2


def _replay_dir_mode(d: Path) -> str | None:
    """``…/modes/Pompeii/savegame`` -> ``Pompeii``; None for AoE2 folders."""
    parts = d.parts
    return parts[parts.index("modes") + 1] if "modes" in parts[:-1] else None


def mode_from_path(path: str) -> str | None:
    """``modes\\Pompeii\\`` (the game's ``SelectedGameInfo.modepath``) -> ``Pompeii``."""
    parts = [p for p in re.split(r"[\\/]+", path or "") if p]
    return parts[1] if len(parts) >= 2 and parts[0].lower() == "modes" else None


def _replay_summary(info: dict[str, Any], data: GameData) -> dict[str, Any]:
    """The replay-browser fields of a ``ReplayInfo.to_json()``."""
    players = [
        {
            "number": pl["number"],
            "name": pl["name"],
            "civ": data.civ_name(pl["civ_id"]),
            "civ_id": pl["civ_id"],
            "team": pl["team"],
            "color": pl["color_id"],
            "human": pl["is_human"],
            "ai": pl["ai_script"],
        }
        for pl in info.get("players", [])
    ]
    return {
        "game": data.game,
        "players": players,
        "map": info.get("map_name") or info.get("rms_file") or info.get("scenario_file") or "",
        "mode": info.get("game_type") or "",
        "build": info.get("build"),
        "game_version": info.get("game_version"),
        "compatible": info.get("compatible"),
        "started_at": info.get("started_at"),
        "multiplayer": info.get("multiplayer"),
        # Lobby settings for the details card (raw ids where no name is known).
        "settings": {
            k: info.get(k)
            for k in (
                "map_size",
                "difficulty",
                "speed_name",
                "population",
                "starting_resources_id",
                "starting_age_id",
                "ending_age_id",
                "reveal_map_id",
                "victory_type_id",
                "treaty_minutes",
                "lock_teams",
                "lock_speed",
                "team_positions",
                "shared_exploration",
                "cheats",
                "all_techs",
                "turbo",
                "handicap",
                "ranked",
                "multiplayer",
                "rms_file",
                "scenario_file",
                "save_version",
                "version",
            )
            if info.get(k) not in (None, "")
        },
        "warnings": info.get("warnings") or [],
    }


def default_replay_dirs() -> list[Path]:
    """Replay folders of every AoE2 profile in every Steam library's Proton
    prefix (libraries from ``libraryfolders.vdf``), or on Windows in the
    user's ``Games`` folder."""
    return replay_dirs(profile_dirs())


def _tree_costs(tree: dict[str, Any], tl: Timeline) -> None:
    """Costs on tech-tree nodes, from the stream (techs, and unit masters)."""
    techs = tl.catalog.techs
    masters = tl.catalog.masters
    for n in tree.get("nodes", ()):
        nid = n.get("id")
        if n.get("kind") == "tech":
            t = techs.get(nid) if isinstance(nid, int) else None
            cost = t.get("cost") if t else None
        else:
            trig = n.get("trigger_tech")
            t = techs.get(trig) if isinstance(trig, int) and trig >= 0 else None
            info = masters.get(nid) if isinstance(nid, int) else None
            cost = (t.get("cost") if t else None) or (info.cost if info else None)
        if cost:
            n["cost"] = cost
    # Hover-tree layout stages: the same lookup, by kind and id.
    for row in (tree.get("layout") or {}).get("rows", ()):
        for grp in row.get("groups", ()):
            for st in grp.get("stages", ()):
                sid = st.get("id")
                if not isinstance(sid, int):
                    continue
                if st.get("kind") == "tech":
                    c = (techs.get(sid) or {}).get("cost")
                else:
                    info = masters.get(sid)
                    c = info.cost if info else None
                if c:
                    st["cost"] = c


def data_dir() -> Path:
    """Vantage's own folder (recordings, images, profiles, skins);
    ``$VANTAGE_DATA_DIR`` overrides :func:`vantage.paths.local_data_dir`."""
    env = os.environ.get("VANTAGE_DATA_DIR")
    return Path(env).expanduser() if env is not None else local_data_dir()


_IMAGE_RE = re.compile(r"[\w.-]+\.(?:png|jpe?g|gif|webp|svg)", re.IGNORECASE)
_SKIN_NAME = re.compile(r"[\w -]{1,40}")


def _safe_child(base: Path, rel: str) -> Path | None:
    """``base/rel`` when it is an existing file inside ``base``, else None."""
    if not rel or rel.startswith(("/", "\\")) or ".." in Path(rel).parts:
        return None
    try:
        f = (base / rel).resolve()
        f.relative_to(base.resolve())
    except (OSError, ValueError):
        return None
    return f if f.is_file() else None


def _profile_of(replay_dir: Path) -> Path:
    """``<profile>/savegame[/multi]`` or ``<profile>/modes/X/savegame`` -> profile."""
    parts = replay_dir.parts
    if "modes" in parts:
        return Path(*parts[: parts.index("modes")])
    if "savegame" in parts:
        return Path(*parts[: parts.index("savegame")])
    return replay_dir.parent


def _sprite_store(data: GameData, mods: list[Path]) -> SpriteStore:
    """A sprite store searching the enabled mods' graphics folders first."""
    # Strips render in worker processes: a cold battle scene needs hundreds.
    # VANTAGE_SPRITE_WORKERS overrides (0: render in the server process).
    env = os.environ.get("VANTAGE_SPRITE_WORKERS", "")
    workers = int(env) if env.isdigit() else max(1, min(8, (os.cpu_count() or 2) - 2))
    return SpriteStore(data.game_dir, data.cache_dir, data.mode, extra_dirs=mods, workers=workers)


def make_handler(app: App) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        # Headers and bodies are written separately. Nagle plus a browser's
        # delayed ACK otherwise adds about 40 ms to small keep-alive responses,
        # serialising sprite look-ahead behind avoidable socket waits.
        disable_nagle_algorithm = True

        def log_message(self, format: str, *args: Any) -> None:
            return

        def do_GET(self) -> None:
            try:
                app.get(self)
            except (BrokenPipeError, ConnectionResetError):
                pass
            except Exception:
                traceback.print_exc()
                self.send_error(HTTPStatus.INTERNAL_SERVER_ERROR)

        def do_POST(self) -> None:
            try:
                app.post(self)
            except (BrokenPipeError, ConnectionResetError):
                pass
            except Exception:
                traceback.print_exc()
                self.send_error(HTTPStatus.INTERNAL_SERVER_ERROR)

    return Handler


#: GIL switch interval while serving (seconds; Python's default is 0.005).
SWITCH_INTERVAL_S = 0.0005


class _HTTPServer(ThreadingHTTPServer):
    # Browsers burst dozens of module/icon requests; the default five pending
    # connections causes TCP retry delays under concurrent viewers.
    request_queue_size = 128
    #: On Windows SO_REUSEADDR lets a second server bind a port that is in use,
    #: and two Vantages would split the requests; elsewhere it only skips TIME_WAIT.
    allow_reuse_address = sys.platform != "win32"


def _pin_web_types() -> None:
    """Windows' registry can map ``.js`` to ``text/plain``, and browsers refuse
    module scripts served so; pin the UI's own types over the registry's."""
    for ext, ctype in (
        (".js", "text/javascript"),
        (".mjs", "text/javascript"),
        (".css", "text/css"),
        (".html", "text/html"),
        (".json", "application/json"),
        (".svg", "image/svg+xml"),
    ):
        mimetypes.add_type(ctype, ext)


if sys.platform == "win32":
    _pin_web_types()


def serve(
    host: str,
    port: int,
    session: Session,
    replay_dirs: list[Path],
    client_config: dict[str, Any] | None = None,
    follow_live: bool = True,
    plugins: Sequence[Any] = (),
    recording_only: bool = False,
    game_art: bool = True,
) -> ThreadingHTTPServer:
    # Request threads share the GIL with the thread ingesting the stream. At the
    # default 5 ms switch interval a cached sprite strip took 19 ms (p50) while a
    # recording loaded; at 0.5 ms 6 ms, /api/session 14 -> 4 ms, with the same
    # ingestion speed (24 game-s/s, 8-player recording, 2026-10-18).
    sys.setswitchinterval(SWITCH_INTERVAL_S)
    app = App(
        session,
        replay_dirs,
        follow_live=follow_live,
        plugins=plugins,
        recording_only=recording_only,
        game_art=game_art,
    )
    if client_config is not None:
        app.client_config = client_config
    server = _HTTPServer((host, port), make_handler(app))
    server.daemon_threads = True
    server.app = app  # type: ignore[attr-defined]  # for the CLI's exit hooks
    return server


def unquote_path(p: str) -> str:
    return unquote(p)


#: For plugins: answer a request the way the server's own routes do.
json_response = _json
bytes_response = _bytes

__all__ = [
    "App",
    "Session",
    "bytes_response",
    "data_dir",
    "default_replay_dirs",
    "json_response",
    "load_recording",
    "mode_from_path",
    "serve",
]
