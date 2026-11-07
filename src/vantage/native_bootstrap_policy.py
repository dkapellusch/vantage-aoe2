"""Explicit descriptor-derived cadence variant; no renderer or worker execution."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import TYPE_CHECKING, Any


FRAME_STAGES = (
    "native_master_frame",
    "native_own_master_frame",
    "native_world_frame",
    "native_player_frame",
    "native_entity_frame",
    "native_entity_presentation_frame",
    "native_activity_frame",
    "native_research_frame",
)
NORMALIZE = re.compile(r"^(?:[0-9]+ ResignPlayer)+")


def require(ok: Any, message: str) -> None:
    if not ok:
        raise ValueError(message)


def uint(value: Any, maximum: int = 0xFFFFFFFF) -> bool:
    return type(value) is int and 0 <= value <= maximum


def exact(a: Any, b: Any) -> bool:
    if type(a) is not type(b):
        return False
    if type(a) is dict:
        return a.keys() == b.keys() and all(exact(a[k], b[k]) for k in a)
    if type(a) in (list, tuple):
        return len(a) == len(b) and all(exact(x, y) for x, y in zip(a, b, strict=True))
    return bool(a == b)


def is_positive_first(descriptor: dict[Any, Any]) -> bool:
    syncs: Any = descriptor.get("bootstrap_syncs")
    require(
        type(syncs) is list and len(syncs) == 3 and all(type(row) is dict for row in syncs),
        "three descriptor sync facts required",
    )
    first = syncs[0].get("delta_ms")
    require(uint(first, 1000), "first delta must be an exact bounded DWORD")
    return bool(first > 0)


@dataclass(frozen=True)
class Plan:
    descriptor_identity: str
    recording_sha256: str
    recording_bytes: int
    first_delta: int
    first_cursor: int
    first_update_cursor: int
    second_update_cursor: int
    final_clock: int
    sync_count: int

    def declaration(self) -> Any:
        return dict(
            stage="native_replay_bootstrap_policy",
            version=1,
            projection_policy="initial_snapshot_plus_updates",
            descriptor_identity=self.descriptor_identity,
            recording_sha256=self.recording_sha256,
            recording_bytes=self.recording_bytes,
            first_delta_ms=self.first_delta,
            first_time_ms=self.first_delta,
        )


def positive_plan(descriptor: dict[Any, Any]) -> Plan:
    require(is_positive_first(descriptor), "positive-first policy requires a positive first delta")
    for name in ("initial_clock_ms", "body_clock_origin_ms"):
        require(
            type(descriptor.get(name)) is int and descriptor[name] == 0,
            "saved and body clock origins must be zero",
        )
    require(descriptor.get("first_operation_kind") == "sync", "first operation must be sync")
    metadata = descriptor.get("body_metadata_words")
    require(
        type(metadata) is list
        and all(type(x) is int for x in metadata)
        and metadata in ([5, 500, 0, 1, 1, 0, 0, 0], [5, 500, 1, 1, 1, 0, 0, 0]),
        "unsupported native metadata profile",
    )
    for name in ("recording_sha256", "inflated_save_sha256"):
        value = descriptor.get(name)
        require(type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value), "SHA identity missing")
    for name in (
        "recording_bytes",
        "inflated_save_bytes",
        "body_offset",
        "final_clock_ms",
        "postgame_offset",
        "postgame_marker_end",
        "postgame_remaining_bytes",
    ):
        require(uint(descriptor.get(name)) and descriptor[name] > 0, "descriptor bounds missing")
    syncs = descriptor["bootstrap_syncs"]
    require(
        type(descriptor.get("first_operation_offset")) is int
        and descriptor["first_operation_offset"] == descriptor["body_offset"] == syncs[0]["offset"],
        "first sync body binding differs",
    )
    previous_time, previous_offset = 0, descriptor["body_offset"] - 1
    for row in syncs:
        require(
            type(row) is dict and set(row) == {"offset", "delta_ms", "time_ms", "payload_bytes"},
            "sync descriptor keys differ",
        )
        require(all(type(x) is int for x in row.values()), "sync descriptor integer types differ")
        require(
            0 < row["delta_ms"] <= 1000
            and row["time_ms"] == previous_time + row["delta_ms"]
            and row["offset"] > previous_offset
            and row["payload_bytes"] == 4
            and row["offset"] + 4 + row["payload_bytes"] <= descriptor["recording_bytes"],
            "sync chronology or bounds differ",
        )
        previous_time, previous_offset = row["time_ms"], row["offset"]
    counts: Any = descriptor.get("operation_counts")
    require(
        type(counts) is list
        and all(
            type(x) is list and len(x) == 2 and type(x[0]) is str and uint(x[1]) for x in counts
        ),
        "operation counts malformed",
    )
    count_map = dict(counts)
    require(
        len(count_map) == len(counts)
        and count_map.get("postgame") == 1
        and count_map.get("sync", 0) >= 3,
        "complete sync/postgame count missing",
    )
    deltas: Any = descriptor.get("sync_deltas_ms")
    require(
        type(deltas) is list
        and all(
            type(x) is list
            and len(x) == 2
            and uint(x[0], 1000)
            and x[0] > 0
            and uint(x[1])
            and x[1] > 0
            for x in deltas
        ),
        "all sync deltas must be positive bounded integers",
    )
    require(
        len(dict(deltas)) == len(deltas)
        and sum(x[1] for x in deltas) == count_map["sync"]
        and sum(d * n for d, n in deltas) == descriptor["final_clock_ms"],
        "sync totals differ from final clock/count",
    )
    require(
        descriptor["postgame_offset"] + 4 == descriptor["postgame_marker_end"]
        and descriptor["recording_bytes"] - descriptor["postgame_marker_end"]
        == descriptor["postgame_remaining_bytes"]
        >= 4
        and previous_time <= descriptor["final_clock_ms"],
        "postgame bounds differ",
    )
    # Bind the entire source descriptor, including original input/save identity and operation facts.
    identity = hashlib.sha256(
        json.dumps(descriptor, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()
    return Plan(
        identity,
        descriptor["recording_sha256"],
        descriptor["recording_bytes"],
        syncs[0]["delta_ms"],
        syncs[0]["offset"] + 8,
        syncs[1]["offset"],
        syncs[2]["offset"],
        descriptor["final_clock_ms"],
        count_map["sync"],
    )


class Updates:
    def __init__(self, plan: Plan) -> None:
        self.plan, self.count, self.clock, self.terminal = plan, 0, 0, False

    def accept(self, event: Any) -> None:
        ordinal, clock, status = (event.get(k) for k in ("ordinal", "world_time_ms", "status"))
        require(type(ordinal) is int and ordinal == self.count + 1, "update ordinal gap/duplicate")
        require(
            uint(clock) and self.clock < clock <= self.plan.final_clock,
            "update clock not strictly advancing within descriptor",
        )
        require(
            type(status) is int and status in (0, 1) and not self.terminal,
            "failed update or data after terminal",
        )
        require(
            type(event.get("recorded_delta_ms")) is int
            and event["recorded_delta_ms"] == clock - self.clock
            and 0 < event["recorded_delta_ms"] <= 1000,
            "recorded delta differs",
        )
        require(
            type(event.get("native_log_ms")) is int and event["native_log_ms"] == clock,
            "native log clock differs",
        )
        require(
            uint(event.get("file_position")) and uint(event.get("clock_cycles")),
            "update diagnostic carriers malformed",
        )
        if ordinal == 1:
            require(
                clock == self.plan.first_delta
                and status == 0
                and event["file_position"] == self.plan.first_update_cursor,
                "first actual update differs from descriptor",
            )
        elif ordinal == 2:
            require(
                event["file_position"] == self.plan.second_update_cursor,
                "second actual update cursor differs from descriptor",
            )
        require(status == 0 or clock == self.plan.final_clock, "early native terminal")
        self.count, self.clock, self.terminal = ordinal, clock, status == 1

    def finish(self) -> None:
        require(
            self.count == self.plan.sync_count and self.clock == self.plan.final_clock,
            "missing/extra returned update or final clock mismatch",
        )


class BoundaryOrder:
    def __init__(self) -> None:
        self.pending: list[Any] = []
        self.time: Any = None
        self.boundaries = 0

    def accept(self, event: Any, update_count: int, update_clock: int) -> None:
        require(event["stage"] == FRAME_STAGES[len(self.pending)], "projection stage order differs")
        time = event.get("time_ms")
        require(uint(time), "projection clock type differs")
        if not self.pending:
            require(self.boundaries == update_count, "missing or extra projection boundary")
            self.time = 0 if self.boundaries == 0 else update_clock
        require(time == self.time, "projection clock differs from actual returned update")
        require(
            event.get("kind") == ("snapshot" if self.boundaries == 0 else "delta"),
            "projection snapshot/delta kind differs",
        )
        self.pending.append(event["stage"])
        if len(self.pending) == len(FRAME_STAGES):
            self.pending = []
            self.boundaries += 1

    def before_update(self, update_count: int) -> None:
        require(
            not self.pending and self.boundaries == update_count + 1,
            "initial snapshot or prior update projection is absent/incomplete",
        )

    def finish(self, update_count: int) -> None:
        self.before_update(update_count)
