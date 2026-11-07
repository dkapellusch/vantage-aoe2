"""Fake-job races and real Session assignment seam; no native/browser conversion."""

import json
import threading
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from vantage import native_session as draft
from vantage.gamedata import GameData
from vantage.native_jobs import Coordinator, NativeConfig, http_replay
from vantage.native_session import NativeSession, SessionPort, play_replay


class Executor:
    def __init__(self):
        self.pending = []

    def submit(self, fn, *args):
        self.pending.append((fn, args))
        return NS()

    def run(self, index=0):
        fn, args = self.pending[index]
        fn(*args)

    def shutdown(self, **kwargs):
        pass


class Converter:
    def __init__(self, callback=None):
        self.calls = 0
        self.cancels = 0
        self.callback = callback

    def convert(self, path):
        self.calls += 1
        if self.callback:
            self.callback()
        return Path("verified-cache.vrec")

    def cancel(self):
        self.cancels += 1


class Port:
    def __init__(self):
        self.generation, self.state = 0, "idle"
        self.adopted, self.updates = [], []
        self.preparing = lambda: None

    def begin(self, path):
        self.generation += 1
        self.state = "queued"
        return NS(generation=self.generation)

    def update(self, ticket, state, **details):
        if ticket.generation != self.generation:
            return False
        self.state = state
        self.updates.append((state, details))
        return True

    def prepare(self, ticket, path, cancelled):
        self.preparing()
        return "loaded"

    def adopt(self, ticket, path, loaded):
        if ticket.generation != self.generation:
            return False
        self.state = "ready"
        self.adopted.append(path)
        self.generation += 1
        return True

    def newer_selection(self):
        self.generation += 1
        self.state = "newer"


@pytest.fixture
def replay(tmp_path):
    path = tmp_path / "selected.aoe2record"
    path.write_bytes(b"fake replay: never parsed")
    return path


def test_async_cache_hit_still_adopts_only_after_loading(replay):
    port, converter, executor = Port(), Converter(), Executor()
    coordinator = Coordinator(port, lambda: converter, executor=executor)
    result = coordinator.start(replay)
    assert result == dict(generation=1, state="queued")
    assert converter.calls == 0 and port.adopted == []
    executor.run()
    assert converter.calls == 1 and port.state == "ready"
    assert port.updates == [
        ("queued", {}),
        ("converting", {"phase": "conversion"}),
        ("converting", {"phase": "loading"}),
    ]
    assert port.adopted == [Path("verified-cache.vrec")]


def test_queued_cancel_never_calls_converter(replay):
    port, converter, executor = Port(), Converter(), Executor()
    coordinator = Coordinator(port, lambda: converter, executor=executor)
    ticket = coordinator.start(replay)
    assert coordinator.cancel(ticket["generation"])
    executor.run()
    assert converter.cancels == 1 and converter.calls == 0
    assert port.state == "cancelled" and not port.adopted


def test_old_cancel_request_cannot_cancel_a_new_queued_selection(replay):
    port, executor = Port(), Executor()
    old, new = Converter(), Converter()
    jobs = iter((old, new))
    coordinator = Coordinator(port, lambda: next(jobs), executor=executor)
    first = coordinator.start(replay)
    second = coordinator.start(replay)
    assert not coordinator.cancel(first["generation"])
    assert new.cancels == 0 and second["generation"] != first["generation"]
    executor.run(0)
    executor.run(1)
    assert old.calls == 0 and new.calls == 1 and port.state == "ready"


def test_stale_conversion_return_cannot_replace_another_selected_session(replay):
    port, executor = Port(), Executor()
    converter = Converter(port.newer_selection)
    coordinator = Coordinator(port, lambda: converter, executor=executor)
    coordinator.start(replay)
    executor.run()
    assert port.state == "newer" and not port.adopted


def test_stale_completion_after_header_loading_cannot_adopt(replay):
    port, executor = Port(), Executor()
    port.preparing = port.newer_selection
    coordinator = Coordinator(port, Converter, executor=executor)
    coordinator.start(replay)
    executor.run()
    assert port.state == "newer" and not port.adopted


def test_new_native_selection_wins_even_if_old_converter_ignores_cancel(replay):
    port, executor = Port(), Executor()
    entered, release = threading.Event(), threading.Event()

    def blocked():
        entered.set()
        assert release.wait(2)

    old, new = Converter(blocked), Converter()
    jobs = iter((old, new))
    coordinator = Coordinator(port, lambda: next(jobs), executor=executor)
    coordinator.start(replay)
    thread = threading.Thread(target=executor.run)
    thread.start()
    assert entered.wait(2)
    newer = coordinator.start(replay)
    executor.run(1)
    assert port.state == "ready" and len(port.adopted) == 1
    release.set()
    thread.join(2)
    assert not thread.is_alive() and port.state == "ready" and len(port.adopted) == 1
    assert old.cancels == 1 and not coordinator.cancel(newer["generation"] - 1)


def test_failure_does_not_load_or_fall_back(replay):
    port, executor = Port(), Executor()

    def fail():
        raise RuntimeError("native failed")

    converter = Converter(fail)
    coordinator = Coordinator(port, lambda: converter, executor=executor)
    coordinator.start(replay)
    executor.run()
    assert port.state == "failed" and not port.adopted
    assert port.updates[-1] == ("failed", {"error": "native failed"})


def test_loading_failure_and_loading_cancellation(replay):
    for cancelled in (False, True):
        port, executor = Port(), Executor()
        coordinator = Coordinator(port, Converter, executor=executor)

        def during_load(cancelled=cancelled, coordinator=coordinator):
            if cancelled:
                coordinator.cancel()
            raise ValueError("bad VREC")

        port.preparing = during_load
        coordinator.start(replay)
        executor.run()
        assert port.state == ("cancelled" if cancelled else "failed") and not port.adopted


def test_real_Session_CAS_after_IO_does_not_call_stop_or_open_recording(tmp_path, monkeypatch):
    session = NativeSession(GameData(None, cache_dir=tmp_path), tmp_path)
    port = SessionPort(session)
    ticket = port.begin(tmp_path / "old.aoe2record")
    # A newer real Session selection is committed while old header/data I/O finishes.
    newer = session._replace("recording", {"path": "newer.vrec", "status": "loading"})
    generation, source, data = session.generation, session.source, session.data
    monkeypatch.setattr(session, "stop", lambda: pytest.fail("stale completion called stop"))
    monkeypatch.setattr(
        session, "open_recording", lambda *_: pytest.fail("stale completion opened recording")
    )
    assert port.adopt(ticket, Path("old.vrec"), (object(), object(), {})) is False
    assert (session.generation, session.source, session.data, session.timeline) == (
        generation,
        source,
        data,
        newer,
    )


def test_old_recording_loader_finally_cannot_mark_a_new_native_selection_ready(
    tmp_path, monkeypatch
):
    created = []

    class DelayedThread:
        def __init__(self, *, target, **kwargs):
            self.target = target
            created.append(self)

        def start(self):
            pass

        def join(self, timeout):
            pass  # Models the existing bounded join returning before a stuck reader.

    monkeypatch.setattr(draft.threading, "Thread", DelayedThread)
    monkeypatch.setattr(draft, "read_header", lambda _: {})

    def old_reader(_):
        raise ValueError("late old loader failure")

    monkeypatch.setattr(draft, "read_frames", old_reader)
    session = NativeSession(GameData(None, cache_dir=tmp_path), tmp_path)
    session.open_recording("old.vrec")
    session._replace("native_replay", {"status": "queued", "replay": "new.aoe2record"})
    newer_source = session.source
    created[0].target()
    assert session.source is newer_source and session.source["status"] == "queued"
    assert session.error is None


def test_queue_ticket_is_captured_atomically_even_if_cleanup_selects_newer(tmp_path, monkeypatch):
    session = NativeSession(GameData(None, cache_dir=tmp_path), tmp_path)
    port = SessionPort(session)
    cleanup = session._cleanup
    once = False

    def interleaved(old):
        nonlocal once
        cleanup(old)
        if not once:
            once = True
            session._replace("recording", {"path": "newer.vrec"})

    monkeypatch.setattr(session, "_cleanup", interleaved)
    ticket = port.begin(tmp_path / "old.aoe2record")
    assert ticket.source is not session.source
    assert not port.update(ticket, "converting")
    assert session.source["path"] == "newer.vrec"


def test_real_Session_adoption_increments_generation_and_preserves_game_end_semantics(
    tmp_path, replay
):
    data = GameData(None, cache_dir=tmp_path)
    session = NativeSession(data, tmp_path)
    executor = Executor()
    timeline = object()
    config = NS(converter=Converter, cache_dir=tmp_path / "cache")
    session.configure_native(
        config, executor=executor, loader=lambda *_: (data, timeline, {"game_ended": None})
    )
    old_generation = session.open_native_replay(replay)["generation"]
    executor.run()
    assert session.timeline is timeline and session.generation == old_generation + 1
    assert session.mode == "recording" and session.source["status"] == "ready"
    assert session.source["header"]["game_ended"] is None
    assert session.ended.is_set()  # Ingestion, not a synthesized native game-end field.


@pytest.fixture
def config(tmp_path):
    profile = tmp_path / "profile.json"
    profile.write_text("{}")
    root = tmp_path / "root"
    root.mkdir()
    return NativeConfig(profile, "a" * 64, tmp_path / "cache", (root,))


@pytest.mark.parametrize(
    "name",
    ("../x.aoe2record", "/tmp/x.aoe2record", "x\\y.aoe2record", "C:x.aoe2record", "x.vrec", "", 1),
)
def test_http_rejects_untrusted_paths(config, name):
    with pytest.raises(ValueError):
        http_replay(config, name, None)


def test_http_root_selector_and_symlink_escape(config, tmp_path):
    root = config.replay_roots[0]
    selected = root / "game.aoe2record"
    selected.write_bytes(b"fake")
    assert http_replay(config, selected.name, str(root)) == selected
    with pytest.raises(ValueError, match="not configured"):
        http_replay(config, selected.name, str(tmp_path))
    outside = tmp_path / "outside.aoe2record"
    outside.write_bytes(b"outside")
    (root / "escape.aoe2record").symlink_to(outside)
    with pytest.raises(ValueError, match="escapes"):
        http_replay(config, "escape.aoe2record", str(root))


def test_http_unconfigured_is_error_not_live_fallback():
    session = NS(native=None, open_live=lambda *_: pytest.fail("game fallback"))
    with pytest.raises(ValueError, match="not configured"):
        play_replay(session, {"name": "x.aoe2record"})


@pytest.fixture
def committed(tmp_path, monkeypatch):
    path = tmp_path / "recording.vrec"
    path.write_bytes(b"fake backend committed bytes: not a real VREC")
    report_path = tmp_path / "conversion.json"
    report = dict(
        status="conversion_verified",
        recording=draft.pin(path),
        capture_frames=2,
        capture_end_ms=31,
        game_ended=False,
    )
    report_path.write_text(json.dumps(report))
    marker_path = tmp_path / "success.json"
    marker_path.write_text(
        json.dumps(
            dict(status="ready", recording=draft.pin(path), conversion=draft.pin(report_path))
        )
    )
    header = dict(expected_frames=2, end_ms=31, game_ended=None)
    frames = [NS(time=0, is_snapshot=False), NS(time=31, is_snapshot=False)]

    class Timeline:
        def __init__(self, data):
            self.frames, self.errors, self.desynced = [], 0, False

        def feed(self, frame):
            self.frames.append(frame)

        def finish(self):
            pass

        def status(self):
            return dict(
                frames=len(self.frames),
                end=self.frames[-1].time,
                errors=self.errors,
                desynced=self.desynced,
            )

        def view_at(self, time):
            return dict(game_ended=False)

    monkeypatch.setattr(draft, "Timeline", Timeline)
    monkeypatch.setattr(draft, "read_header", lambda _: header)
    monkeypatch.setattr(draft, "read_frames", lambda _: iter(frames))
    data = NS(with_mode=lambda _: "mode-selected-outside-Session")
    ticket = NS(data=data, stop=threading.Event(), playback_index_root=None)
    return NS(
        path=path,
        report=report_path,
        marker=marker_path,
        ticket=ticket,
        header=header,
        frames=frames,
    )


def test_load_rechecks_committed_cache_and_actual_ongoing_state(committed):
    data, timeline, header = SessionPort.load(committed.ticket, committed.path, threading.Event())
    assert data == "mode-selected-outside-Session" and len(timeline.frames) == 2
    assert header["game_ended"] is None and timeline.view_at(31)["game_ended"] is False


def test_readable_uncommitted_or_changed_file_never_adopts(committed):
    committed.path.write_bytes(b"changed between backend return and Session load")
    with pytest.raises(ValueError, match="committed"):
        SessionPort.load(committed.ticket, committed.path, threading.Event())


def test_load_rejects_readable_prefix_extent(committed):
    committed.frames.pop()
    with pytest.raises(ValueError, match="incomplete"):
        SessionPort.load(committed.ticket, committed.path, threading.Event())


def test_loader_cancellation_precedes_file_IO(committed):
    cancelled = threading.Event()
    cancelled.set()
    with pytest.raises(Exception, match="cancelled"):
        SessionPort.load(committed.ticket, committed.path.parent / "absent.vrec", cancelled)


def test_load_rejects_commit_marker_change_during_loading(committed, monkeypatch):
    def frames(_):
        yield committed.frames[0]
        committed.marker.write_text("changed after initial commit check")
        yield committed.frames[1]

    monkeypatch.setattr(draft, "read_frames", frames)
    with pytest.raises(ValueError, match="changed while loading"):
        SessionPort.load(committed.ticket, committed.path, threading.Event())


@pytest.mark.parametrize("history", ("recording", "live", "thread", "oracle", "source"))
def test_configure_native_requires_a_fresh_idle_session(tmp_path, history):
    session = NativeSession(GameData(None, cache_dir=tmp_path), tmp_path)
    if history == "recording":
        session._replace("recording", {})
        session.stop()
    elif history == "live":
        session.generation = 1  # Even an already-disconnected historical worker is disallowed.
    elif history == "thread":
        session._thread = object()
    elif history == "oracle":
        session._oracle_thread = object()
    else:
        session.source = {"old": True}
    with pytest.raises(ValueError, match="fresh idle"):
        session.configure_native(
            NS(converter=Converter, cache_dir=tmp_path / "cache"), executor=Executor()
        )


def test_configured_native_refuses_live_before_any_legacy_connection(tmp_path, monkeypatch):
    monkeypatch.setattr(draft.Session, "open_live", lambda *a, **kw: pytest.fail("legacy called"))
    session = NativeSession(GameData(None, cache_dir=tmp_path), tmp_path)
    session.configure_native(
        NS(converter=Converter, cache_dir=tmp_path / "cache"), executor=Executor()
    )
    assert session.native.lock is session.lock
    with pytest.raises(ValueError, match="live mode is unavailable"):
        session.open_live()


def test_unconfigured_live_keeps_legacy_call_but_prevents_late_configuration(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(draft.Session, "open_live", lambda *a, **kw: calls.append(kw))
    session = NativeSession(GameData(None, cache_dir=tmp_path), tmp_path)
    session.open_live(host="legacy")
    assert calls == [{"host": "legacy"}]
    with pytest.raises(ValueError, match="fresh idle"):
        session.configure_native(
            NS(converter=Converter, cache_dir=tmp_path / "cache"), executor=Executor()
        )


def test_old_slow_header_cannot_stop_or_replace_newer_selection(tmp_path, monkeypatch):
    session = NativeSession(GameData(None, cache_dir=tmp_path), tmp_path)
    saved = {}

    def header(_):
        assert session.source["path"] == "old.vrec"  # Reservation precedes read.
        saved["timeline"] = session._replace("native_replay", {"status": "queued"})
        saved["generation"], saved["source"] = session.generation, session.source
        return {}

    monkeypatch.setattr(draft, "read_header", header)
    session.open_recording("old.vrec")
    assert session.timeline is saved["timeline"]
    assert session.generation == saved["generation"] and session.source is saved["source"]
    assert session.source["status"] == "queued" and session._thread is None


def test_stale_header_error_cannot_change_newer_error_or_end_event(tmp_path, monkeypatch):
    session = NativeSession(GameData(None, cache_dir=tmp_path), tmp_path)

    def header(_):
        session._replace("native_replay", {"status": "queued"})
        raise ValueError("bad old header")

    monkeypatch.setattr(draft, "read_header", header)
    with pytest.raises(ValueError, match="bad old header"):
        session.open_recording("old.vrec")
    assert session.error is None and session.source["status"] == "queued"
    assert not session.ended.is_set()


def test_cleanup_join_never_holds_shared_selection_lock(tmp_path):
    session = NativeSession(GameData(None, cache_dir=tmp_path), tmp_path)
    session.configure_native(
        NS(converter=Converter, cache_dir=tmp_path / "cache"), executor=Executor()
    )
    acquired = threading.Event()

    def old_worker():
        with session.lock:
            acquired.set()

    worker = threading.Thread(target=old_worker)
    with session.lock:
        session._thread = worker
        worker.start()
    session._replace("recording", {})
    assert acquired.is_set() and not worker.is_alive()


def test_close_during_reservation_never_submits_new_work(replay):
    port, executor = Port(), Executor()
    coordinator = Coordinator(port, Converter, executor=executor)
    original = port.begin

    def begin(path):
        ticket = original(path)
        coordinator.close()
        return ticket

    port.begin = begin
    with pytest.raises(Exception, match="closed"):
        coordinator.start(replay)
    assert executor.pending == [] and port.state == "cancelled"


def test_close_marks_closed_before_backend_cancel_can_reenter(replay):
    port, executor = Port(), Executor()
    converter = Converter()
    coordinator = Coordinator(port, lambda: converter, executor=executor)
    coordinator.start(replay)

    def cancel():
        assert coordinator.closed
        with pytest.raises(ValueError, match="closed"):
            coordinator.start(replay)

    converter.cancel = cancel
    coordinator.close()
    executor.run()
    assert converter.calls == 0 and port.state == "cancelled"


def test_http_backend_error_becomes_bounded_error_without_live_fallback(config):
    root = config.replay_roots[0]
    (root / "game.aoe2record").write_bytes(b"fake")

    def failure(_):
        raise RuntimeError("executor unavailable")

    session = NS(
        native=object(),
        native_config=config,
        open_native_replay=failure,
        open_live=lambda *a: pytest.fail("fallback"),
    )
    with pytest.raises(ValueError, match="executor unavailable"):
        play_replay(session, {"name": "game.aoe2record"})


def test_http_duplicate_replay_requires_explicit_root(config, tmp_path):
    other = tmp_path / "other"
    other.mkdir()
    for root in (other, config.replay_roots[0]):
        (root / "same.aoe2record").write_bytes(b"fake")
    cfg = NativeConfig(
        config.profile, config.profile_sha256, config.cache_dir, (other, *config.replay_roots)
    )
    with pytest.raises(ValueError, match="ambiguous"):
        http_replay(cfg, "same.aoe2record", None)
    assert http_replay(cfg, "same.aoe2record", str(other)) == other / "same.aoe2record"


def test_recording_thread_start_failure_can_be_replaced_cleanly(tmp_path, monkeypatch):
    class BrokenThread:
        def __init__(self, **kwargs):
            pass

        def start(self):
            raise RuntimeError("cannot start thread")

        def join(self, **kwargs):
            pytest.fail("unstarted thread was retained")

    monkeypatch.setattr(draft.threading, "Thread", BrokenThread)
    monkeypatch.setattr(draft, "read_header", lambda _: {})
    session = NativeSession(GameData(None, cache_dir=tmp_path), tmp_path)
    with pytest.raises(RuntimeError, match="cannot start thread"):
        session.open_recording("bad.vrec")
    assert session._thread is None and session.source["status"] == "failed"
    assert session.ended.is_set()
    session._replace("recording", {"path": "newer.vrec"})
    assert session.error is None


def test_stop_during_visible_reservation_before_job_install_cancels_source(
    replay, tmp_path, monkeypatch
):
    session = NativeSession(GameData(None, cache_dir=tmp_path), tmp_path)
    executor = Executor()
    session.configure_native(
        NS(converter=Converter, cache_dir=tmp_path / "cache"), executor=executor
    )
    cleanup, once = session._cleanup, False

    def stop_during_cleanup(old):
        nonlocal once
        cleanup(old)
        if not once:
            once = True
            session.stop()

    monkeypatch.setattr(session, "_cleanup", stop_during_cleanup)
    with pytest.raises(Exception, match="selection changed"):
        session.open_native_replay(replay)
    assert session.source["status"] == "cancelled" and session.ended.is_set()
    assert not executor.pending
