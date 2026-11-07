"""Real Timeline + persisted index consumer seam; synthetic recordings only."""

from __future__ import annotations

import concurrent.futures
import copy
import json
import struct
import threading
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from tests.helpers import game_frames
from vantage import chat_playback as C
from vantage import playback_index as I
from vantage.frames import RecordingWriter
from vantage.gamedata import GameData, ModConfig
from vantage.native_conversion import ConversionCancelled
from vantage.native_session import NativeSession, SessionPort, Ticket
from vantage.timeline import Timeline


def chat(message="recorded-only", *, player=2, taunt=-1):
    raw = json.dumps(
        {
            "player": player,
            "channel": 1,
            "message": message,
            "messageAGP": "formatted",
            "tauntNumber": taunt,
            "destinationMap": 12,
        }
    ).encode()
    return struct.pack("<IiI", 4, -1, len(raw)) + raw


def replay(path):
    meta = struct.pack("<8I", 5, 500, 0, 1, 1, 0, 0, 0)
    action = struct.pack("<II", 1, 5) + b"\x0b\x02\x02\0\0" + struct.pack("<I", 0)
    body = (
        action
        + struct.pack("<II", 2, 1000)
        + chat()
        + chat()
        + struct.pack("<II", 2, 4000)
        + chat("gg")
        + struct.pack("<II", 6, 6000)
    )
    path.write_bytes(struct.pack("<II", 9, 0) + b"x" + meta + body)
    return path


@pytest.fixture
def bundle(tmp_path):
    source = replay(tmp_path / "source.aoe2record")
    path = tmp_path / "recording.vrec"
    frames = game_frames(6)
    # Establish exact comparable native occurrence; source has two OTHER repeats.
    for frame in frames:
        for event in frame.events:
            if event["kind"] == "playerchat":
                event["taunt"] = -1
    with RecordingWriter(path, {"expected_frames": len(frames), "end_ms": 6000}) as writer:
        for frame in frames:
            writer.write(frame)
    report = {
        "status": "conversion_verified",
        "recording": C.pin(path),
        "capture_frames": len(frames),
        "capture_end_ms": 6000,
        "game_ended": False,
    }
    report_path = tmp_path / "conversion.json"
    report_path.write_text(json.dumps(report))
    marker = {
        "status": "ready",
        "recording": C.pin(path),
        "conversion": C.pin(report_path),
        "identity": {"backend": "v32-sdk-1", "replay_sha256": C.pin(source)["sha256"]},
    }
    (tmp_path / "success.json").write_text(json.dumps(marker))
    data = GameData(None, cache_dir=tmp_path / "data", mods=ModConfig(live_mods=[]))
    ticket = Ticket(1, threading.Event(), data, {"replay": str(source)})
    return NS(
        path=path,
        replay=source,
        ticket=ticket,
        stop=threading.Event(),
        root=tmp_path,
        cache=tmp_path / "chats",
    )


def load(bundle, *, indexed=False):
    ticket = bundle.ticket
    if indexed:
        ticket = Ticket(
            ticket.generation, ticket.stop, ticket.data, ticket.source, bundle.root / "base-index"
        )
    return C.load_with_recorded_chat(ticket, bundle.path, bundle.stop, chat_cache_root=bundle.cache)


@pytest.mark.parametrize("indexed", [False, True])
def test_real_timeline_query_and_direct_event_consumers(bundle, indexed):
    # First indexed load publishes the ordinary base; second restores real SQLite.
    if indexed:
        _, first, _ = load(bundle, indexed=True)
        first.close()
    data, overlay, _ = load(bundle, indexed=indexed)
    base = overlay._base
    try:
        assert isinstance(base, I.ReadOnlyTimeline) is indexed
        assert isinstance(overlay, Timeline) and isinstance(overlay, I.ReadOnlyTimeline)
        assert overlay.data is data
        before = copy.deepcopy(base.events)
        rows = overlay.events_between(0, 6000)
        assert rows == overlay.events
        assert sum(e.get("text") == "recorded-only" for e in rows) == 2
        assert sum(e.get("text") == "gg" for e in rows) == 1  # exact occurrence dedup
        assert [e["t"] for e in rows] == sorted(e["t"] for e in rows)
        assert all("to" not in e for e in rows if e.get("recorded"))
        # Actual HUD/stat query APIs use overlay state and keep simulated stats equal.
        for when in (0, 1000, 5000, 6000):
            assert overlay.view_at(when) == base.view_at(when)
            assert overlay.summary(when) == base.summary(when)
        assert overlay.series_json() == base.series_json()
        assert overlay.unit_stats(101, 6000) == base.unit_stats(101, 6000)
        assert base.events == before and overlay.events is not base.events
        assert overlay.recorded_chat["added_events"] == 2
        for method in ("feed", "finish", "add_event", "oracle_chat"):
            with pytest.raises(TypeError):
                getattr(overlay, method)(None)
        assert overlay._index_source_identity is None
        with pytest.raises(I.CacheMiss):
            I.publish(
                overlay,
                bundle.path,
                bundle.root / "must-not-publish",
                I.identity(bundle.path, overlay.data),
            )
    finally:
        overlay.close()
        overlay.close()  # idempotent


def test_persisted_base_bytes_and_restore_stay_chat_free(bundle):
    _, initial, _ = load(bundle, indexed=True)
    initial.close()
    stored = list((bundle.root / "base-index").rglob("index.sqlite3"))
    assert len(stored) == 1
    before = C.pin(stored[0])
    _, overlay, _ = load(bundle, indexed=True)
    try:
        assert C.pin(stored[0]) == before
        fresh = I.restore(bundle.path, bundle.ticket.data, bundle.root / "base-index")
        try:
            assert not any(e.get("recorded") for e in fresh.events)
            assert len(overlay.events) == len(fresh.events) + 2
        finally:
            fresh.close()
    finally:
        overlay.close()


def test_companion_cache_hit_no_reparse_and_source_identity_bound(bundle, monkeypatch):
    _, first, _ = load(bundle)
    expected = first.recorded_chat["identity"]
    first.close()
    monkeypatch.setattr(C.chat, "extract_replay", lambda *a, **k: pytest.fail("cache reparsed"))
    _, second, _ = load(bundle)
    assert second.recorded_chat["cache_hit"] and second.recorded_chat["identity"] == expected
    assert {Path(x["path"]).name for x in expected["sources"]} == {
        "chat_playback.py",
        "recorded_chat.py",
        "replay_stream.py",
    }
    second.close()


@pytest.mark.parametrize("damage", ["json", "hash", "events", "row", "type"])
def test_bad_chat_cache_falls_back_to_original_input(bundle, damage):
    _, initial, _ = load(bundle)
    cache_path = Path(initial.recorded_chat["cache_path"])
    initial.close()
    obj = json.loads(cache_path.read_bytes())
    if damage == "json":
        cache_path.write_text("bad")
    else:
        if damage == "hash":
            obj["result_sha256"] = "0" * 64
        elif damage == "events":
            obj["result"]["events"][0]["text"] = "invented"
        elif damage == "row":
            obj["result"]["records"][0] = None
        else:
            obj["result"] = None
        if damage != "hash":
            obj["result_sha256"] = C.digest(obj["result"])
        cache_path.write_text(json.dumps(obj))
    _, overlay, _ = load(bundle)
    assert not overlay.recorded_chat["cache_hit"]
    assert any(e.get("text") == "recorded-only" for e in overlay.events)
    overlay.close()


def test_selected_replay_mismatch_precedes_base_io(bundle, monkeypatch):
    bundle.replay.write_bytes(bundle.replay.read_bytes() + b"changed")
    monkeypatch.setattr(C.SessionPort, "load", lambda *a: pytest.fail("base was loaded"))
    with pytest.raises(ValueError, match="V32 identity"):
        load(bundle)


@pytest.mark.parametrize("channel", ["request", "ticket"])
def test_cancellation_before_io(bundle, channel):
    (bundle.stop if channel == "request" else bundle.ticket.stop).set()
    bundle.path.unlink()
    with pytest.raises(ConversionCancelled):
        load(bundle)


def test_cancel_during_extraction_leaves_no_cache(bundle, monkeypatch):
    original = C.chat.iter_replay_operations

    def cancel(path):
        for op in original(path):
            bundle.stop.set()
            yield op

    monkeypatch.setattr(C.chat, "iter_replay_operations", cancel)
    with pytest.raises(ConversionCancelled):
        load(bundle)
    assert not bundle.cache.exists()


def test_change_during_extraction_rejects_and_never_publishes(bundle, monkeypatch):
    original = C.chat.extract_replay

    def changed(*args, **kwargs):
        result = original(*args, **kwargs)
        bundle.replay.write_bytes(bundle.replay.read_bytes() + b"changed")
        return result

    monkeypatch.setattr(C.chat, "extract_replay", changed)
    with pytest.raises(ValueError, match="changed"):
        load(bundle)
    assert not bundle.cache.exists()


def test_cache_key_changes_with_vrec_and_operative_source(bundle, monkeypatch):
    old = C.identity(bundle.replay, bundle.path, 6000)
    bundle.path.write_bytes(bundle.path.read_bytes() + b"different")
    assert C.digest(C.identity(bundle.replay, bundle.path, 6000)) != C.digest(old)
    monkeypatch.setattr(
        C, "source_identity", lambda stop=None: [dict(old["sources"][0], sha256="x")]
    )
    assert C.digest(C.identity(bundle.replay, bundle.path, 6000)) != C.digest(old)


def test_read_only_store_closed_on_late_cancel(bundle, monkeypatch):
    _, initial, _ = load(bundle, indexed=True)
    initial.close()
    base = I.restore(bundle.path, bundle.ticket.data, bundle.root / "base-index")
    monkeypatch.setattr(C.SessionPort, "load", lambda *a: (base.data, base, {}))

    def cancel(*args, **kwargs):
        bundle.stop.set()
        raise ConversionCancelled("late cancel")

    monkeypatch.setattr(C, "supplement", cancel)
    with pytest.raises(ConversionCancelled):
        load(bundle)
    assert not base._index_finalizer.alive


@pytest.mark.parametrize("stale", [False, True])
def test_real_session_loader_and_generation_adoption(bundle, stale):
    session = NativeSession(bundle.ticket.data, bundle.root)
    port = SessionPort(session, loader=C.load_with_recorded_chat)
    ticket = port.begin(bundle.replay)
    loaded = port.prepare(ticket, bundle.path, threading.Event())
    overlay = loaded[1]
    try:
        if stale:
            session._replace("recording", {"path": "newer.vrec"})
            assert not port.adopt(ticket, bundle.path, loaded)
            assert session.source == {"path": "newer.vrec"}
        else:
            assert port.adopt(ticket, bundle.path, loaded)
            assert session.timeline is overlay and session.source["status"] == "ready"
            assert len(session.timeline.events_between(1000, 1000)) == 2
    finally:
        overlay.close()
        session.stop()


def test_selection_replacement_cancels_real_session_extraction(bundle, monkeypatch):
    session = NativeSession(bundle.ticket.data, bundle.root)
    port = SessionPort(session, loader=C.load_with_recorded_chat)
    ticket = port.begin(bundle.replay)
    original = C.chat.iter_replay_operations

    def replace(path):
        for operation in original(path):
            session._replace("recording", {"path": "newer.vrec"})
            yield operation

    monkeypatch.setattr(C.chat, "iter_replay_operations", replace)
    with pytest.raises(ConversionCancelled):
        port.prepare(ticket, bundle.path, threading.Event())
    assert session.source == {"path": "newer.vrec"}
    session.stop()


def test_summary_defaultdict_reads_do_not_mutate_base_bookkeeping(bundle):
    _, overlay, _ = load(bundle)
    base = overlay._base
    overlay._ages.pop(2, None)
    overlay._peak_army.pop(2, None)
    before = copy.deepcopy(base._ages), copy.deepcopy(base._peak_army)
    overlay.summary(6000)
    assert (base._ages, base._peak_army) == before
    assert overlay._ages is not base._ages and overlay._peak_army is not base._peak_army
    overlay.close()


@pytest.mark.parametrize("kind", ["content", "timestamp", "omission"])
def test_self_consistent_cache_corruption_cannot_change_recorded_events(bundle, kind):
    _, original, _ = load(bundle)
    path = Path(original.recorded_chat["cache_path"])
    expected = copy.deepcopy(original.events)
    original.close()
    obj = json.loads(path.read_bytes())
    result = obj["result"]
    if kind == "omission":
        result["records"].pop(0)
    else:
        row = result["records"][0]
        operation = C.replay_stream.ReplayOperation(
            "chat", row["offset"], row["time_ms"], bytes.fromhex(row["payload_hex"])
        )
        if kind == "timestamp":
            operation = C.replay_stream.ReplayOperation(
                "chat", operation.offset, operation.time_ms + 1, operation.payload
            )
        else:
            raw = json.loads(operation.payload[4:])
            raw["message"] = "invented-but-internally-consistent"
            operation = C.replay_stream.ReplayOperation(
                "chat",
                operation.offset,
                operation.time_ms,
                operation.payload[:4] + json.dumps(raw).encode(),
            )
        result["records"][0] = C.chat.decode_chat(operation)
    result["events"] = [
        event
        for row in result["records"]
        if (event := C.chat.timeline_chat(row, result["source"], end_ms=6000))
    ]
    result["chat_operations"] = len(result["records"])
    result["decoded_envelopes"] = len(result["records"])
    result["timeline_chat_events"] = len(result["events"])
    obj["result_sha256"] = C.digest(result)
    path.write_text(json.dumps(obj))
    _, actual, _ = load(bundle)
    try:
        assert actual.events == expected
        assert not actual.recorded_chat["cache_hit"]
    finally:
        actual.close()


def test_optional_cache_write_failure_does_not_reject_valid_playback(bundle, monkeypatch):
    def readonly(*args, **kwargs):
        raise PermissionError("cache is read-only")

    monkeypatch.setattr(C.os, "replace", readonly)
    _, overlay, _ = load(bundle)
    try:
        assert overlay.recorded_chat["added_events"] == 2
        assert not list(bundle.cache.glob("*.pending-*"))
    finally:
        overlay.close()


def test_close_waits_for_inflight_lazy_index_query(bundle, monkeypatch):
    _, first, _ = load(bundle, indexed=True)
    first.close()
    _, overlay, _ = load(bundle, indexed=True)
    entered, release, close_started, closed = (threading.Event() for _ in range(4))
    original = overlay._index_store.blob

    def delayed(key):
        entered.set()
        assert release.wait(5)
        return original(key)

    def close():
        close_started.set()
        overlay.close()
        closed.set()

    monkeypatch.setattr(overlay._index_store, "blob", delayed)
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        reading = executor.submit(overlay.view_at, 6000)
        assert entered.wait(5)
        closing = executor.submit(close)
        assert close_started.wait(5)
        try:
            assert not closed.wait(0.05), "closed SQLite while a query still owns it"
        finally:
            release.set()
        assert reading.result(5)["time"] == 6000
        closing.result(5)
    assert closed.is_set()


def test_unlocked_lazy_views_remain_concurrent(bundle, monkeypatch):
    _, first, _ = load(bundle, indexed=True)
    first.close()
    _, overlay, _ = load(bundle, indexed=True)
    original = overlay._index_store.blob
    barrier = threading.Barrier(2)

    def simultaneous(key):
        barrier.wait(timeout=2)
        return original(key)

    monkeypatch.setattr(overlay._index_store, "blob", simultaneous)
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            results = [executor.submit(overlay.view_at, 6000) for _ in range(2)]
            assert all(row.result(5)["time"] == 6000 for row in results)
    finally:
        overlay.close()


def test_cancellation_during_cache_source_validation_is_not_swallowed(bundle, monkeypatch):
    _, first, _ = load(bundle)
    first.close()
    original = C.replay_stream.iter_replay_operations

    def cancel(path):
        for operation in original(path):
            bundle.stop.set()
            yield operation

    monkeypatch.setattr(C.replay_stream, "iter_replay_operations", cancel)
    with pytest.raises(ConversionCancelled):
        load(bundle)


@pytest.mark.parametrize("raw", [b"not JSON", b'{"player":true,"message":"bad identity"}'])
def test_malformed_source_chat_preserves_playback_without_invented_defaults(bundle, raw):
    meta = struct.pack("<8I", 5, 500, 0, 1, 1, 0, 0, 0)
    body = struct.pack("<IiI", 4, -1, len(raw)) + raw + struct.pack("<II", 6, 6000)
    bundle.replay.write_bytes(struct.pack("<II", 9, 0) + b"x" + meta + body)
    path = bundle.root / "success.json"
    marker = json.loads(path.read_bytes())
    marker["identity"]["replay_sha256"] = C.pin(bundle.replay)["sha256"]
    path.write_text(json.dumps(marker))
    _, overlay, _ = load(bundle)
    try:
        assert overlay.recorded_chat["unsupported_envelopes"] == 1
        assert overlay.recorded_chat["added_events"] == 0
        assert not any(e.get("recorded") for e in overlay.events)
        assert overlay.view_at(6000)["time"] == 6000
    finally:
        overlay.close()


def test_queries_after_close_fail_explicitly(bundle):
    _, overlay, _ = load(bundle)
    overlay.close()
    for method, args in (("view_at", (0,)), ("events_between", (0, 6000)), ("status", ())):
        with pytest.raises(ValueError, match="closed"):
            getattr(overlay, method)(*args)
