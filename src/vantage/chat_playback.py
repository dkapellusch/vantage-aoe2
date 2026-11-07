"""Staged V32 consumer adapter. No converter, VREC or base-index mutation."""

from __future__ import annotations

import contextlib
import copy
import functools
import hashlib
import json
import os
import threading
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

from vantage import replay_stream
from vantage.native_conversion import ConversionCancelled
from vantage.native_session import SessionPort
from vantage.playback_index import ReadOnlyTimeline, StopAny
from vantage.timeline import Timeline

from . import recorded_chat as chat

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path
    from typing import TYPE_CHECKING, Any

    from vantage.native_session import Ticket


SCHEMA = 1


def checked(stop: Any) -> None:
    if stop is not None and stop.is_set():
        raise ConversionCancelled("recorded chat loading cancelled")


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def pin(path: Any, stop: Any = None) -> Any:
    checked(stop)
    path = Path(path).resolve()
    value = hashlib.sha256()
    count = 0
    with path.open("rb") as stream:
        while block := stream.read(1 << 20):
            checked(stop)
            count += len(block)
            value.update(block)
    checked(stop)
    return {"path": str(path), "bytes": count, "sha256": value.hexdigest()}


def source_identity(stop: Any = None) -> Any:
    return [pin(path, stop) for path in (__file__, chat.__file__, replay_stream.__file__)]


def identity(replay: Path, recording: Path, end_ms: int, stop: Any = None) -> Any:
    return {
        "schema": SCHEMA,
        "replay": pin(replay, stop),
        "recording": pin(recording, stop),
        "end_ms": end_ms,
        "sources": source_identity(stop),
    }


def validate_result(
    result: Any,
    expected: Any,
    stop: Any = None,
) -> None:
    """A cache is only a hash-bound derivation; it cannot introduce event fields."""
    if (
        type(result) is not dict
        or result.get("schema") != 1
        or result.get("source") != expected["replay"]
        or result.get("end_ms") != expected["end_ms"]
        or type(result.get("records")) is not list
        or len(result["records"]) > chat.MAX_CHATS
    ):
        raise ValueError("recorded chat cache identity/shape differs")
    decoded, events, offset = [], [], -1
    for row in result["records"]:
        checked(stop)
        if (
            type(row) is not dict
            or type(row.get("offset")) is not int
            or row["offset"] <= offset
            or type(row.get("time_ms")) is not int
            or row["time_ms"] < 0
        ):
            raise ValueError("recorded chat cache record order differs")
        offset = row["offset"]
        raw = bytes.fromhex(row["payload_hex"])
        operation = replay_stream.ReplayOperation("chat", offset, row["time_ms"], raw)
        actual = chat.decode_chat(operation)
        if actual != row:
            raise ValueError("recorded chat cache raw derivation differs")
        decoded.append(actual)
        event = chat.timeline_chat(actual, expected["replay"], end_ms=expected["end_ms"])
        if event is not None:
            events.append(event)
    if (
        result.get("events") != events
        or result.get("chat_operations") != len(decoded)
        or result.get("decoded_envelopes") != sum(r["status"] != "unsupported" for r in decoded)
        or result.get("unsupported_envelopes") != sum(r["status"] == "unsupported" for r in decoded)
        or result.get("timeline_chat_events") != len(events)
    ):
        raise ValueError("recorded chat cache events/counts differ")


def validate_against_replay(
    result: Any,
    replay: Path,
    stop: Any = None,
) -> None:
    """Match every cached chat to source framing, clock, payload and occurrence.

    An unauthenticated cache digest alone cannot prove source derivation. A hit
    still walks the cheap source operation stream; it avoids envelope extraction,
    not replay framing validation. Missing or extra cached records are rejected.
    """
    rows = iter(result["records"])
    for operation in replay_stream.iter_replay_operations(replay):
        checked(stop)
        if operation.kind != "chat":
            continue
        row = next(rows, None)
        if (
            row is None
            or row["offset"] != operation.offset
            or row["time_ms"] != operation.time_ms
            or row["payload_hex"] != operation.payload.hex()
        ):
            raise ValueError("recorded chat cache differs from original replay stream")
    if next(rows, None) is not None:
        raise ValueError("recorded chat cache has extra source records")


def supplement(
    replay: Path,
    recording: Path,
    end_ms: int,
    *,
    expected_replay_sha: Any,
    cache_root: Any = None,
    stop: Any = None,
) -> Any:
    """Read/extract a companion cache; bind all inputs again before returning."""
    checked(stop)
    expected = identity(replay, recording, end_ms, stop)
    if expected["replay"]["sha256"] != expected_replay_sha:
        raise ValueError("selected replay differs from V32 conversion identity")
    path = Path(cache_root) / (digest(expected) + ".json") if cache_root is not None else None
    result = None
    hit = False
    if path is not None:
        try:
            limit = max(1 << 20, expected["replay"]["bytes"] * 8)
            with path.open("rb") as stream:
                raw = stream.read(limit + 1)
            if len(raw) > limit:
                raise ValueError("recorded chat cache size cap")
            envelope = json.loads(raw)
            if envelope["identity"] != expected or envelope["result_sha256"] != digest(
                envelope["result"]
            ):
                raise ValueError("recorded chat cache changed")
            validate_result(envelope["result"], expected, stop)
            validate_against_replay(envelope["result"], replay, stop)
            result, hit = envelope["result"], True
        except (OSError, ValueError, KeyError, TypeError, OverflowError, RecursionError):
            pass  # A corrupt/missing supplement falls back to the original replay.
    if result is None:
        try:
            result = chat.extract_replay(Path(replay), end_ms=end_ms, stop=stop)
        except chat.ExtractionCancelled as error:
            raise ConversionCancelled(str(error)) from error
        validate_result(result, expected, stop)
    if identity(replay, recording, end_ms, stop) != expected:
        raise ValueError("recorded chat input/source changed during loading")
    write_error = None
    if path is not None and not hit:
        pending = path.with_name("." + path.name + ".pending-" + uuid.uuid4().hex)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with pending.open("xb") as stream:
                stream.write(
                    canonical(
                        {"identity": expected, "result": result, "result_sha256": digest(result)}
                    )
                )
                stream.flush()
                os.fsync(stream.fileno())
            checked(stop)
            if identity(replay, recording, end_ms, stop) != expected:
                raise ValueError("recorded chat source changed before cache publication")
            os.replace(pending, path)
        except OSError as error:
            # Optional cache failure cannot invalidate a verified replay/VREC.
            # Required input/source checks below still propagate failures.
            write_error = f"{type(error).__name__}: {error}"
        finally:
            with contextlib.suppress(OSError):
                pending.unlink(missing_ok=True)
    if identity(replay, recording, end_ms, stop) != expected:
        raise ValueError("recorded chat input/source changed before return")
    checked(stop)
    return result, {
        "identity": expected,
        "cache_hit": hit,
        "cache_write_error": write_error,
        "cache_source_stream_verified": hit,
        "cache_path": str(path) if path is not None else None,
    }


def query(method: Callable[..., Any]) -> Callable[..., Any]:
    """Own the lazy store for a whole query, including formerly lock-free views."""

    @functools.wraps(method)
    def guarded(self: Any, *args: Any, **kwargs: Any) -> Any:
        if getattr(self._chat_query_local, "inside", False):
            return method(self, *args, **kwargs)
        with self._chat_query_condition:
            if self._chat_closing or self._chat_closed:
                raise ValueError("recorded-chat playback is closed")
            self._chat_query_count += 1
        self._chat_query_local.inside = True
        try:
            return method(self, *args, **kwargs)
        finally:
            self._chat_query_local.inside = False
            with self._chat_query_condition:
                self._chat_query_count -= 1
                self._chat_query_condition.notify_all()

    return guarded


class RecordedChatTimeline(ReadOnlyTimeline):
    """Completed query state with owned chat events; retains the lazy store owner.

    Shallow-copy Timeline state, deep-copy events. Existing query methods then
    resolve `self.events`, including summary, against the overlay. The base is
    retained strongly for lazy blob lifetime. It must not be concurrently fed.
    This is intentionally not publishable as an ordinary VREC-only index.
    """

    def __init__(
        self,
        base: Any,
        result: dict[Any, Any],
        provenance: Any,
    ) -> None:
        if not base.complete or base.errors or base.desynced:
            raise ValueError("recorded chat requires completed healthy playback")
        with base._lock:
            self.__dict__.update(base.__dict__)
            self._base = base
            self._chat_closed = False
            self._chat_closing = False
            self._chat_query_condition = threading.Condition()
            self._chat_query_local = threading.local()
            self._chat_query_count = 0
            self.events = chat.merge_events(copy.deepcopy(base.events), copy.deepcopy(result))
            # summary() indexes these defaultdicts and may create absent keys.
            # Keep that query-side bookkeeping owned by the overlay too.
            self._ages = copy.deepcopy(base._ages)
            self._peak_army = copy.deepcopy(base._peak_army)
            self.version = base.version + int(self.events != base.events)
            self.recorded_chat = copy.deepcopy(provenance)
            self.recorded_chat.update(
                extracted_events=len(result["events"]),
                added_events=len(self.events) - len(base.events),
                unsupported_envelopes=result["unsupported_envelopes"],
                timing="original_latest_sync_absolute_ms_not_native_delivery",
                recipient_mapping="not_resolved",
            )
            self.patcher = None  # type: ignore[assignment]  # read-only: never simulates
            self._index_source_identity = None

    def close(self) -> None:
        if getattr(self._chat_query_local, "inside", False):
            raise ValueError("cannot close playback from its own query")
        with self._chat_query_condition:
            if self._chat_closed:
                return
            if self._chat_closing:
                self._chat_query_condition.wait_for(lambda: self._chat_closed)
                return
            self._chat_closing = True
            self._chat_query_condition.wait_for(lambda: self._chat_query_count == 0)
            try:
                if isinstance(self._base, ReadOnlyTimeline):
                    self._base.close()
            finally:
                self._chat_closed = True
                self._chat_query_condition.notify_all()

    view_at = query(Timeline.view_at)
    terrain_at = query(Timeline.terrain_at)
    trees_at = query(Timeline.trees_at)
    units_after = query(Timeline.units_after)
    missiles_after = query(Timeline.missiles_after)
    master_stats = query(Timeline.master_stats)
    entity_master_stats = query(Timeline.entity_master_stats)
    events_between = query(Timeline.events_between)
    series_json = query(Timeline.series_json)
    summary = query(Timeline.summary)
    unit_stats = query(Timeline.unit_stats)
    group_stats = query(Timeline.group_stats)
    status = query(Timeline.status)
    wait_change = query(Timeline.wait_change)


def load_with_recorded_chat(
    ticket: Ticket, path: Path, cancelled: threading.Event, *, chat_cache_root: Any = None
) -> Any:
    """Drop-in NativeSession.configure_native(loader=...) candidate.

    SessionPort.load performs existing commit/header/end/GameData/index checks.
    Its adoption generation CAS remains unchanged. This wrapper verifies the
    selected replay against the committed V32 marker before any chat parsing,
    then rechecks all inputs after both loaders and before returning to adoption.
    """
    stop = StopAny(cancelled, ticket.stop)
    checked(stop)
    path = Path(path)
    replay = Path(ticket.source["replay"])
    files = (path, path.parent / "success.json", path.parent / "conversion.json", replay)
    before = [pin(value, stop) for value in files]
    marker = json.loads(files[1].read_bytes())
    expected_sha = marker.get("identity", {}).get("replay_sha256")
    if (
        marker.get("identity", {}).get("backend") != "v32-sdk-1"
        or expected_sha != before[-1]["sha256"]
    ):
        raise ValueError("selected replay differs from committed V32 identity")
    base = None
    try:
        data, base, header = SessionPort.load(ticket, path, cancelled)
        result, provenance = supplement(
            replay,
            path,
            base.end,
            expected_replay_sha=expected_sha,
            cache_root=chat_cache_root,
            stop=stop,
        )
        checked(stop)
        if [pin(value, stop) for value in files] != before:
            raise ValueError("committed recording/replay changed while loading chat")
        overlay = RecordedChatTimeline(base, result, provenance)
        checked(stop)
        return data, overlay, header
    except BaseException:
        if isinstance(base, ReadOnlyTimeline):
            base.close()
        raise
