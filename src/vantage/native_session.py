"""Concrete draft adapter/subclass against today's Session; no shipping edits."""

from __future__ import annotations

import contextlib
import json
import threading
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any

from vantage.frames import read_frames, read_header
from vantage.native_conversion import ConversionCancelled, pin
from vantage.server import Session
from vantage.timeline import Timeline, settle_heap

from .native_jobs import Coordinator, http_replay
from .playback_index import Cancelled as PlaybackCancelled
from .playback_index import StopAny, load_completed

if TYPE_CHECKING:
    from pathlib import Path
    from typing import TYPE_CHECKING


@dataclass(frozen=True)
class Ticket:
    generation: int
    stop: threading.Event
    data: Any
    source: dict[Any, Any]
    playback_index_root: Path | None = None


class SessionPort:
    def __init__(self, session: Any, loader: Any = None) -> None:
        self.session = session
        self.loader = loader or self.load
        self.lock = session.lock

    def begin(self, replay: Path) -> Ticket:
        ticket: Ticket
        ticket, _ = self.session._reserve(
            "native_replay", dict(replay=str(replay), status="queued", native=True)
        )
        config = getattr(self.session, "native_config", None)
        if config is not None:
            ticket = replace(ticket, playback_index_root=(config.cache_dir / "playback-index-v2"))
        return ticket

    def _current(self, ticket: Ticket) -> bool:
        return self.session.generation == ticket.generation and self.session.source is ticket.source

    def _cancel_replaced_data(self, ticket: Ticket) -> Any:
        # Changing the install replaces GameData without replacing the Session.
        # Do not let an older load put its captured install back at adoption.
        if self.session.data is ticket.data:
            return False
        ticket.stop.set()
        ticket.source["status"] = "cancelled"
        self.session.ended.set()
        return True

    def update(self, ticket: Ticket, state: str, **details: Any) -> Any:
        with self.session.lock:
            if not self._current(ticket) or ticket.stop.is_set():
                return False
            if self._cancel_replaced_data(ticket):
                return False
            ticket.source.update(status=state, **details)
            self.session.error = details.get("error")
            if state in ("failed", "cancelled"):
                self.session.ended.set()
            return True

    def prepare(self, ticket: Ticket, path: Path, cancelled: threading.Event) -> Any:
        with self.session.lock:
            if (
                not self._current(ticket)
                or ticket.stop.is_set()
                or self._cancel_replaced_data(ticket)
            ):
                raise ConversionCancelled("recording selection or game data changed")
        return self.loader(ticket, Path(path), cancelled)

    @staticmethod
    def load(ticket: Any, path: Path, cancelled: threading.Event) -> Any:
        if cancelled.is_set() or ticket.stop.is_set():
            raise ConversionCancelled("recording loading cancelled")
        before = pin(path)
        # convert() without --out returns a committed cache entry, never a pending file.
        marker_path, report_path = path.parent / "success.json", path.parent / "conversion.json"
        marker_pin, report_pin = pin(marker_path), pin(report_path)
        marker, report = json.loads(marker_path.read_text()), json.loads(report_path.read_text())
        if (
            marker.get("status") != "ready"
            or marker.get("recording") != before
            or marker.get("conversion") != report_pin
        ):
            raise ValueError("native cache has no matching committed recording/report")
        recorded = report.get("recording", {})
        if report.get("status") != "conversion_verified" or any(
            recorded.get(key) != before[key] for key in ("bytes", "sha256")
        ):
            raise ValueError("native conversion report does not bind the ready bytes")
        header = read_header(path)
        count, end = header.get("expected_frames"), header.get("end_ms")
        if (
            type(count) is not int
            or count <= 0
            or type(end) is not int
            or end < 0
            or (count, end) != (report.get("capture_frames"), report.get("capture_end_ms"))
        ):
            raise ValueError("native header extent differs from committed report")
        data = ticket.data.with_mode(header.get("game_mode"))
        if ticket.playback_index_root is None:
            timeline = Timeline(data)
            for frame in read_frames(path):
                if cancelled.is_set() or ticket.stop.is_set():
                    raise ConversionCancelled("recording loading cancelled")
                timeline.feed(frame)
                if frame.is_snapshot:
                    settle_heap()
                if timeline.errors or timeline.desynced:
                    raise ValueError("native recording consumer rejected a frame")
            timeline.finish()
        else:
            try:
                data, timeline = load_completed(
                    path, data, ticket.playback_index_root, StopAny(cancelled, ticket.stop)
                )
            except PlaybackCancelled as error:
                raise ConversionCancelled(str(error)) from error
        if cancelled.is_set() or ticket.stop.is_set():
            raise ConversionCancelled("recording loading cancelled")
        status = timeline.status()
        if status["errors"] or status["desynced"]:
            raise ValueError("native recording consumer rejected a frame")
        if (status["frames"], status["end"]) != (count, end):
            raise ValueError("native recording is incomplete or has an unexpected extent")
        view = timeline.view_at(end)
        if view is None or view["game_ended"] is not report.get("game_ended"):
            raise ValueError("native final game-ended field differs from committed report")
        if before != pin(path) or marker_pin != pin(marker_path) or report_pin != pin(report_path):
            raise ValueError("native recording changed while loading")
        return data, timeline, header

    def adopt(
        self,
        ticket: Ticket,
        path: Path,
        loaded: Any,
    ) -> Any:
        data, timeline, header = loaded
        # This check and assignment are atomic AFTER all header/data/loading I/O.
        # Never call ordinary open_recording here: it stops/replaces unconditionally.
        with self.session.lock:
            if not self._current(ticket) or ticket.stop.is_set():
                return False
            if self._cancel_replaced_data(ticket):
                return False
            self.session.data, self.session.timeline = data, timeline
            self.session.generation += 1  # Invalidate queued-session view/bookmark caches.
            self.session.mode = "recording"
            self.session.source = dict(
                path=str(path),
                header=header,
                game=data.game,
                replay=ticket.source["replay"],
                native=True,
                request_generation=ticket.generation,
                status="ready",
            )
            self.session.error = None
            self.session.ended.set()  # Ingestion complete; playback end remains browser-owned.
            return True


class NativeSession(Session):
    """Draft selectable by CLI instead of Session, preserving its public interfaces."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.native: Any = None
        self.native_config: Any = None
        super().__init__(*args, **kwargs)
        # One shared selection/coordinator lock (re-entrant, unlike Session's).
        self.lock: Any = threading.RLock()

    def configure_native(
        self, config: Any, *, factory: Any = None, executor: Any = None, loader: Any = None
    ) -> None:
        with self.lock:
            if (
                self.native is not None
                or self.generation != 0
                or self.mode != "idle"
                or self.source
                or self.timeline is not None
                or any(
                    value is not None
                    for value in (
                        self._thread,
                        self._live,
                        self._oracle_thread,
                        self._oracle_game,
                        self._writer,
                    )
                )
            ):
                raise ValueError("native conversion requires a fresh idle Session")
            self.native_config = config
            self.native = Coordinator(
                SessionPort(self, loader), factory or config.converter, executor=executor
            )

    def open_native_replay(self, replay: Any) -> Any:
        if self.native is None:
            raise ValueError("native replay conversion requires explicit local configuration")
        return self.native.start(Path(replay))

    def set_game_dir(self, raw: str) -> Any:
        # Install replacement and the ticket's final data/adoption check must
        # share the same lock, rather than racing after that check succeeds.
        with self.lock:
            return super().set_game_dir(raw)

    def open_live(self, *args: Any, **kwargs: Any) -> Any:
        # Serialize policy check with configuration. Mark the session selected
        # before releasing this lock, so later configuration cannot race a live
        # worker that is still connecting. Legacy behavior itself stays inherited.
        with self.lock:
            if self.native is not None:
                raise ValueError("live mode is unavailable with local replay conversion configured")
            self.generation += 1
        return super().open_live(*args, **kwargs)

    def _detach_locked(
        self,
    ) -> Any:
        converter = self.native._cancel_locked() if self.native is not None else None
        # A reservation may be visible before its Job is installed. Stop owns
        # that selection too, including its status/event and pending CAS gate.
        if self.mode == "native_replay" and self.source.get("status") in ("queued", "converting"):
            self.source["status"] = "cancelled"
            self.ended.set()
        self._stop.set()
        old = (converter, self._thread, self._oracle_game, self._live)
        self._thread = self._oracle_game = self._live = None
        return old

    @staticmethod
    def _cleanup(
        old: Any,
    ) -> None:
        converter, thread, oracle, live = old
        if converter is not None:
            converter.cancel()
        if oracle is not None:
            with contextlib.suppress(Exception):
                oracle.close()
        if live is not None:
            with contextlib.suppress(Exception):
                live.cancel_frames()
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=5)

    def _reserve(self, mode: str, source: Any) -> tuple[Any, ...]:
        with self.lock:
            if self.native is not None and self.native.closed:
                raise ValueError("native coordinator is closed")
            old = self._detach_locked()
            self.generation += 1
            self.timeline = Timeline(self.data)
            self.mode, self.source = mode, source
            self.error = self._stream_error = None
            self._stop, self.ended = threading.Event(), threading.Event()
            ticket = Ticket(self.generation, self._stop, self.data, self.source)
            timeline = self.timeline
        self._cleanup(old)  # Never wait for an old worker while holding its lock.
        return ticket, timeline

    def _replace(self, mode: str, source: dict[Any, Any]) -> Any:
        return self._reserve(mode, source)[1]

    def stop(self) -> None:
        with self.lock:
            old = self._detach_locked()
        self._cleanup(old)

    def close_native(self) -> None:
        if self.native is not None:
            self.native.close()

    def open_recording(self, path: str | Path) -> None:
        """Reserve BEFORE I/O. Slow old headers cannot replace newer selections."""
        path = Path(path).expanduser()
        ticket, placeholder = self._reserve("recording", dict(path=str(path), status="loading"))
        source, stop = ticket.source, ticket.stop
        with self.lock:
            ended = self.ended if self.source is source else None

        def current() -> Any:
            return (
                self.generation == ticket.generation and self.source is source and not stop.is_set()
            )

        try:
            header = read_header(path)
            data = ticket.data.with_mode(header.get("game_mode"))
            timeline = Timeline(data)
        except Exception as error:
            with self.lock:
                if current():
                    self.error = f"{type(error).__name__}: {error}"
                    source["status"] = "failed"
                    self.ended.set()
            raise

        def run() -> None:
            failed = False
            try:
                for frame in read_frames(path):
                    if stop.is_set():
                        return
                    timeline.feed(frame)
                    if frame.is_snapshot:
                        settle_heap()
                timeline.finish()
            except Exception as error:
                failed = True
                with self.lock:
                    if current():
                        self.error = f"{type(error).__name__}: {error}"
                timeline.finish()
            finally:
                with self.lock:
                    if current():
                        source["status"] = "failed" if failed else "ready"
                if ended is not None:
                    ended.set()  # Captured event, never a newer session's event.

        with self.lock:
            if not current() or self.timeline is not placeholder:
                return
            self.data, self.timeline = data, timeline
            source.update(header=header, game=data.game)
            self._thread = threading.Thread(target=run, name="vantage-load", daemon=True)
            try:
                self._thread.start()
            except Exception as error:
                self._thread = None
                self.error = f"{type(error).__name__}: {error}"
                source["status"] = "failed"
                self.ended.set()
                raise


def play_replay(session: Any, body: dict[str, Any]) -> dict[str, Any]:
    if getattr(session, "native", None) is None:
        raise ValueError("native conversion is not configured")
    replay = http_replay(session.native_config, body["name"], body.get("dir"))
    try:
        return {"ok": True, **session.open_native_replay(replay)}
    except RuntimeError as error:
        # The existing HTTP dispatcher serializes ValueError as a bounded 400.
        # Never retry this request through the legacy running-game path.
        raise ValueError(str(error)) from error


def cancel_replay(session: Any, body: dict[str, Any]) -> dict[str, Any]:
    generation = body.get("generation")
    if type(generation) is not int:
        raise ValueError("explicit native request generation required")
    native = getattr(session, "native", None)
    return {"ok": True, "cancelled": bool(native and native.cancel(generation))}
