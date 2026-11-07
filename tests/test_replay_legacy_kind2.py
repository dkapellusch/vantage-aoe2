"""Actual whole-entry endpoints for the admitted kind2 legacy component.

Inputs and expected states are decoded from native snapshots. No oracle model,
artifact script or Game is imported. Masked sticky-status admission, large-pool
capacity and refusal policy are separate source/API checks.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import struct
from dataclasses import dataclass, replace
from functools import cache
from pathlib import Path
from typing import Any

import pytest

from vantage.replay_legacy_kind2 import (
    LegacyKind2Context,
    LegacyKind2Pool,
    LegacyKind2Refresh,
    LegacyKind2Registry,
    LegacyKind2State,
    UnsupportedLegacyKind2,
)
from vantage.replay_legacy_mutation import (
    LegacyMutationBucket,
    LegacyMutationObject,
    LegacyMutationRecord,
)
from vantage.replay_legacy_query import LegacyQueryLevel

FIXTURES = Path(__file__).parent / "fixtures"
CONTEXT = LegacyKind2Context(False, True, True, 0x1F80)


@dataclass(frozen=True)
class NativeCall:
    case: dict[str, Any]
    operation: tuple[int, ...]
    before: memoryview
    after: memoryview
    result: int


@cache
def metadata() -> dict[str, Any]:
    return json.loads(
        gzip.decompress((FIXTURES / "native_legacy_kind2_54800_inputs.json.gz").read_bytes())
    )


def offset(name: str, index: int = 0) -> int:
    row = next(r for r in metadata()["layout"]["groups"] if r["name"] == name)
    assert 0 <= index < row["count"]
    return int(row["offset"] + index * row["stride"] + 16)


def record_offset(index: int) -> int:
    return offset("BLOCK", index // 12) + (index % 12) * 64


@cache
def native_calls() -> tuple[NativeCall, ...]:
    raw = gzip.decompress((FIXTURES / "native_legacy_kind2_54800.bin.gz").read_bytes())
    digest = hashlib.sha256(raw).hexdigest()
    assert (
        digest
        == metadata()["native_uncompressed_sha256"]
        == ("e43a628ff72382810535ac663d4db160092832517d256ad9fb0c9f804b200819")
    )
    view = memoryview(raw)
    at = 0
    calls = []
    for case in metadata()["cases"]:
        for step, operation in enumerate(case["operations"]):
            bodies = []
            result = 0
            for stage in (0, 1):
                cid, sid, phase, result, mxcsr, size, control = struct.unpack_from("<7I", view, at)
                at += 28
                assert (cid, sid, phase, control) == (case["id"], step, stage, 0)
                assert size == metadata()["layout"]["bytes"] and mxcsr & ~0x3F == 0x1F80
                bodies.append(view[at : at + size])
                at += size
            calls.append(NativeCall(case, tuple(operation), bodies[0], bodies[1], result))
    assert at == len(raw) and len(calls) == 100
    return tuple(calls)


def native_state(call: NativeCall, body: memoryview) -> LegacyKind2State:
    token_base = int(metadata()["pointer_token_base"])
    manager, pool = offset("MANAGER"), offset("POOL")
    width, height = struct.unpack_from("<2I", body, manager + 0xA0)
    block_sizes = struct.unpack_from("<2I", body, offset("BLOCKSIZE"))
    blocks = tuple(
        tuple(token_base + record_offset(j * 12 + i) for i in range(size))
        for j, size in enumerate(block_sizes)
    )
    records = tuple(
        LegacyMutationRecord(
            token_base + record_offset(i), bytes(body[record_offset(i) : record_offset(i) + 64])
        )
        for i in range(sum(block_sizes))
    )
    objects = tuple(
        LegacyMutationObject(
            token_base + offset("OBJECT", i),
            struct.unpack_from("<i", body, offset("OBJECT", i) + 8)[0],
            struct.unpack_from("<Q", body, offset("OBJECT", i) + 0x1A0)[0],
        )
        for i in range(8)
    )
    buckets = tuple(
        LegacyMutationBucket(
            struct.unpack_from("<i", body, offset("BUCKET") + i * 16 + 8)[0],
            struct.unpack_from("<8Q", body, offset("SLOT", i)),
        )
        for i in range(1365)
    )
    levels = tuple(
        LegacyQueryLevel(*struct.unpack_from("<4i", body, manager + 0x2C0 + i * 24))
        for i in range(6)
    )
    # Pool2 explicitly includes six previously issued caller-held slots in
    # addition to the four manager reservations. This is controlled input,
    # rather than a fresh whole-constructor inference.
    reserved_count = 10 if call.case["pool"] == 2 else 4
    return LegacyKind2State(
        width,
        height,
        struct.unpack_from("<64i", body, manager + 0x1BC),
        levels,
        buckets,
        records,
        objects,
        LegacyKind2Pool(
            blocks,
            struct.unpack_from("<i", body, pool + 0x14)[0],
            struct.unpack_from("<i", body, pool + 0x20)[0],
            struct.unpack_from("<i", body, pool + 0x24)[0],
            struct.unpack_from("<Q", body, pool + 0x18)[0],
            struct.unpack_from("<i", body, pool + 0x2C)[0],
            struct.unpack_from("<i", body, pool + 0x30)[0],
        ),
        tuple(token_base + record_offset(i) for i in range(reserved_count)),
        struct.unpack_from(f"<{width * height}Q", body, offset("PLANE")),
    )


def run(registry: LegacyKind2Registry, call: NativeCall) -> LegacyKind2Refresh:
    obj, x, y, owner, _raw_id, mode, rx, ry, kind = call.operation
    return registry.refresh(
        int(metadata()["pointer_token_base"]) + offset("OBJECT", obj),
        position_bits=(x, y),
        radius_bits=(rx, ry),
        kind=kind,
        mode=mode,
        owner=owner,
    )


@pytest.mark.parametrize("index", range(100))
def test_actual_whole_entry_endpoints(index: int) -> None:
    call = native_calls()[index]
    initial = native_state(call, call.before)
    registry = LegacyKind2Registry(initial, CONTEXT)
    if not call.result:
        assert call.before == call.after
        with pytest.raises(UnsupportedLegacyKind2 if call.operation[8] != 2 else ValueError):
            run(registry, call)
        assert registry.snapshot() == initial
        return
    result = run(registry, call)
    assert result.defined_al is True
    assert registry.snapshot() == native_state(call, call.after)
    trace = offset("TRACE")
    count = struct.unpack_from("<I", call.after, trace)[0]
    observed = []
    for i in range(count):
        argument, divisor, remainder = struct.unpack_from("<3I", call.after, trace + 4 + i * 20)
        assert divisor == 0x3F000000
        observed.append((argument, remainder))
    assert result.fmod_calls == tuple(observed)


@pytest.mark.parametrize(
    "change",
    [
        {"modern_enabled": True},
        {"genuine_empty_listener_callback": False},
        {"disjoint_backing": False},
        *({"mxcsr": word} for word in (0, 0x1F00, 0x3F80, 0x5F80, 0x7F80, 0x1FC0, 0x9F80)),
    ],
)
def test_refuse_unclosed_current_context(change: dict[str, Any]) -> None:
    with pytest.raises(UnsupportedLegacyKind2):
        replace(CONTEXT, **change)


@pytest.mark.parametrize("status", (1, 2, 4, 8, 16, 32, 63))
def test_source_derived_masked_sticky_context(status: int) -> None:
    call = native_calls()[0]
    registry = LegacyKind2Registry(
        native_state(call, call.before), replace(CONTEXT, mxcsr=0x1F80 | status)
    )
    run(registry, call)
    assert registry.snapshot() == native_state(call, call.after)


@pytest.mark.parametrize(
    "field,value", [("owner", 7), ("owner", -1), ("mode", 256), ("mode", -1), ("kind", 5)]
)
def test_refuse_scalar_profiles_before_model_mutation(field: str, value: int) -> None:
    call = native_calls()[0]
    initial = native_state(call, call.before)
    registry = LegacyKind2Registry(initial, CONTEXT)
    arguments = dict(
        position_bits=(call.operation[1], call.operation[2]),
        radius_bits=(call.operation[6], call.operation[7]),
        kind=2,
        mode=1,
        owner=0,
    )
    arguments[field] = value
    with pytest.raises(ValueError):
        registry.refresh(initial.objects[0].token, **arguments)
    assert registry.snapshot() == initial


@pytest.mark.parametrize("word", (0x7FC00001, 0x7F800000, 0xC5800001))
def test_refuse_nonfinite_or_outside_coordinate_bound(word: int) -> None:
    call = native_calls()[0]
    registry = LegacyKind2Registry(native_state(call, call.before), CONTEXT)
    with pytest.raises(UnsupportedLegacyKind2):
        registry.refresh(
            int(metadata()["pointer_token_base"]) + offset("OBJECT"),
            position_bits=(word, 0),
            radius_bits=(0, 0),
            kind=2,
            mode=1,
            owner=0,
        )


def test_large_explicit_pool_keeps_unissued_slots_distinct() -> None:
    call = native_calls()[0]
    initial = native_state(call, call.before)
    records = (
        *initial.records,
        *(LegacyMutationRecord(0x200000 + i, bytes(64)) for i in range(10000 - 24)),
    )
    tokens = tuple(record.token for record in records)
    initial = replace(
        initial, records=records, pool=LegacyKind2Pool((tokens,), 8, 0, 4, 0, 9996, 5000)
    )
    registry = LegacyKind2Registry(initial, CONTEXT)
    run(registry, call)
    final = registry.snapshot()
    assert (final.pool.current_block, final.pool.next_slot, final.pool.available) == (0, 5, 9995)
    assert final.objects[0].record_token == tokens[4]
    assert final.records[5:] == initial.records[5:]


@pytest.mark.parametrize("empty_pool", (False, True))
def test_capacity_refusal_policy_is_before_model_mutation(empty_pool: bool) -> None:
    call = native_calls()[0]
    initial = native_state(call, call.before)
    if empty_pool:
        initial = replace(
            initial,
            reserved_tokens=tuple(r.token for r in initial.records),
            pool=replace(initial.pool, current_block=-1, next_slot=0, available=0),
        )
    else:
        target = native_state(call, call.after)
        record = next(r for r in target.records if r.token == target.objects[0].record_token)
        bucket = struct.unpack_from("<i", record.raw, 4)[0]
        buckets = list(initial.buckets)
        buckets[bucket] = LegacyMutationBucket(0, ())
        initial = replace(initial, buckets=tuple(buckets))
    registry = LegacyKind2Registry(initial, CONTEXT)
    with pytest.raises(UnsupportedLegacyKind2):
        run(registry, call)
    assert registry.snapshot() == initial
