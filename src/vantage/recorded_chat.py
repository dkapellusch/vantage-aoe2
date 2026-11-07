"""Offline recorded-chat supplement; not installed into the V32 converter.

The native chat envelope is documented in native-recorded-chat-contract-v1.
Source clocks come exclusively from replay_stream, never frame interpolation.
This decodes recorded messages, not native delivery, recipient rules or effects.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import struct
from collections import Counter
from pathlib import Path
from typing import TYPE_CHECKING, Any

from vantage.replay_stream import ReplayOperation, iter_replay_operations

if TYPE_CHECKING:
    from typing import TYPE_CHECKING


MAX_CHAT_BYTES = 1 << 20
MAX_CHATS = 100_000


class ExtractionCancelled(ValueError):
    pass


def pin(path: Path) -> dict[Any, Any]:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        size = 0
        while block := stream.read(1 << 20):
            size += len(block)
            digest.update(block)
    return {"path": str(path.resolve()), "bytes": size, "sha256": digest.hexdigest()}


def _pairs(
    items: Any,
) -> Any:
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _constant(_: Any) -> None:
    raise ValueError("nonfinite JSON constant")


def _float(value: Any) -> Any:
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("nonfinite JSON number")
    return result


def decode_chat(operation: ReplayOperation) -> dict[Any, Any]:
    """Preserve every operation4, including explicit unsupported envelopes.

    Marker is the wire sender word; it is distinct from envelope.player.
    destinationMap is retained raw: recorded Comm masks are not established
    as the Timeline/Frame player's bitmask and are never translated here.
    """
    if operation.kind != "chat":
        raise ValueError("not a chat operation")
    payload = operation.payload
    row = {
        "offset": operation.offset,
        "time_ms": operation.time_ms,
        "payload_hex": payload.hex(),
        "payload_sha256": hashlib.sha256(payload).hexdigest(),
        "wire_sender": struct.unpack_from("<i", payload)[0] if len(payload) >= 4 else None,
        "status": "unsupported",
        "reason": None,
        "envelope": None,
    }
    if len(payload) < 4 or len(payload) - 4 > MAX_CHAT_BYTES:
        row["reason"] = "missing_sender_or_payload_cap"
        return row
    try:
        obj = json.loads(
            payload[4:].decode("utf-8"),
            object_pairs_hook=_pairs,
            parse_constant=_constant,
            parse_float=_float,
        )
    except (ValueError, UnicodeError, RecursionError):
        row["reason"] = "invalid_utf8_or_json"
        return row
    if not isinstance(obj, dict):
        row["reason"] = "envelope_not_object"
        return row
    row["envelope"] = obj
    if (
        type(obj.get("player")) is not int
        or not -(1 << 63) <= obj["player"] < (1 << 63)
        or type(obj.get("channel")) is not int
        or not 0 <= obj["channel"] < (1 << 32)
        or type(obj.get("message")) is not str
        or type(obj.get("messageAGP")) is not str
    ):
        row["reason"] = "unsupported_required_field"
        return row
    for name in ("tauntNumber", "destinationMap"):
        if name in obj and (type(obj[name]) is not int or not -(1 << 31) <= obj[name] < (1 << 32)):
            row["reason"] = f"unsupported_{name}"
            return row
    row["status"] = "decoded_recorded_envelope"
    return row


def timeline_chat(
    row: dict[Any, Any], source: dict[Any, Any], *, end_ms: int | None = None
) -> dict[Any, Any] | None:
    """Build existing chat UI vocabulary, without recipients or outcome claims.

    Age announcements remain in raw records. As in Timeline._resolve_events,
    do not duplicate simulated age research with a second chat entry.
    """
    if row["status"] != "decoded_recorded_envelope":
        return None
    obj, t = row["envelope"], row["time_ms"]
    if t < 0 or (end_ms is not None and t > end_ms):
        return None
    if obj["message"].startswith("<player_id,") and " advanced to " in obj["message"]:
        return None
    # Restrict UI identities to the established one-based replay player domain.
    # Other source IDs/channels remain visible as raw decoded records.
    if not 1 <= obj["player"] <= 8 or obj["channel"] not in (0, 1, 2, 3):
        return None
    return {
        "t": t,
        "cat": "chat",
        "kind": "chat",
        "player": obj["player"],
        "channel": obj["channel"],
        "text": obj["message"],
        "taunt": obj.get("tauntNumber", -1),
        "recorded": True,
        "recorded_destination_map": obj.get("destinationMap", 0),
        "recipient_mapping": "not_resolved",
        "recorded_source": {
            "sha256": source["sha256"],
            "offset": row["offset"],
            "payload_sha256": row["payload_sha256"],
            "time_basis": "original_latest_sync_absolute_ms",
        },
    }


def extract_replay(path: Path, *, end_ms: int | None = None, stop: Any = None) -> dict[Any, Any]:
    if end_ms is not None and (type(end_ms) is not int or end_ms < 0):
        raise ValueError("end_ms must be a nonnegative integer")
    path = Path(path)
    before = pin(path)
    rows: list[Any] = []
    events: list[Any] = []
    for operation in iter_replay_operations(path):
        if stop is not None and stop.is_set():
            raise ExtractionCancelled("recorded-chat extraction cancelled")
        if operation.kind != "chat":
            continue
        if len(rows) >= MAX_CHATS:
            raise ValueError("recorded-chat count cap")
        row = decode_chat(operation)
        rows.append(row)
        if (event := timeline_chat(row, before, end_ms=end_ms)) is not None:
            events.append(event)
    if pin(path) != before:
        raise ValueError("recording changed during chat extraction")
    return {
        "schema": 1,
        "source": before,
        "end_ms": end_ms,
        "chat_operations": len(rows),
        "decoded_envelopes": sum(r["status"] == "decoded_recorded_envelope" for r in rows),
        "unsupported_envelopes": sum(r["status"] == "unsupported" for r in rows),
        "timeline_chat_events": len(events),
        "records": rows,
        "events": events,
        "scope": (
            "Recorded chat only; no native delivery, recipient, simulation or score inference."
        ),
    }


def _signature(
    event: Any,
) -> tuple[Any, ...]:
    return tuple(event.get(key) for key in ("t", "player", "channel", "text", "taunt"))


def merge_events(
    existing: list[dict[Any, Any]], supplement: dict[Any, Any]
) -> list[dict[Any, Any]]:
    """Proposed consumer seam: exact occurrence dedup, stable chronological order.

    Same text at another clock is not silently matched. Duplicate recorded
    messages are preserved; one existing occurrence consumes only one match.
    This returns a new list, leaving completed read-only indexes untouched.
    """
    budget = Counter(_signature(e) for e in existing if e.get("kind") == "chat")
    merged = list(existing)
    for event in supplement["events"]:
        signature = _signature(event)
        if budget[signature]:
            budget[signature] -= 1
        else:
            merged.append(event)
    return sorted(merged, key=lambda event: event["t"])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("replay", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--end-ms", type=int)
    args = parser.parse_args()
    result = extract_replay(args.replay, end_ms=args.end_ms)
    with args.out.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    summary = {key: value for key, value in result.items() if key not in {"records", "events"}}
    print(json.dumps(summary))


if __name__ == "__main__":
    main()
