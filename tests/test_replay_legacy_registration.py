from __future__ import annotations

import gzip
import hashlib
import json
import struct
from dataclasses import replace
from functools import lru_cache
from pathlib import Path
from typing import Any

import pytest

from vantage.replay_legacy_kind2 import (
    LegacyKind2Context,
    LegacyKind2Registry,
    UnsupportedLegacyKind2,
)
from vantage.replay_legacy_mutation import (
    LegacyMutationBucket,
    LegacyMutationObject,
    LegacyMutationRecord,
)
from vantage.replay_legacy_query import LegacyQueryLevel
from vantage.replay_legacy_registration import (
    LegacyRegistrationContext,
    LegacyRegistrationPool,
    LegacyRegistrationRegistry,
    LegacyRegistrationState,
    UnsupportedLegacyRegistration,
)

POISON = 0xA5A5A5A5A5A5A5A5
EMPTY = (POISON,) * 16
TILES = (0x55,) * 40000  # Declared adapter input; absent from the old native fixture.


@lru_cache(maxsize=1)
def native_cases() -> dict[int, tuple[dict[str, Any], list[dict[str, Any]]]]:
    raw = (Path(__file__).parent / "fixtures/native_legacy_mutation_2120.json.gz").read_bytes()
    assert hashlib.sha256(raw).hexdigest() == (
        "b247f3fc0d192fa61937c9243f1eb16cbf3c2d70f1123e182bff3ec8ebfbf150"
    )
    data = json.loads(gzip.decompress(raw))
    assert data["evidence_id"] == (
        "ev_8186aa169d0476733ed20f79cf60b3e2104ae70e0b3aa4d6653f8323a9631531"
    )
    assert data["modern_enabled"] is False and data["original_code_changed"] is False
    result = {}
    at = 0
    for index, case in enumerate(data["cases"]):
        frames = data["native"][at : at + len(case["operations"])]
        at += len(frames)
        assert all((row["case"], row["step"]) == (index, step) for step, row in enumerate(frames))
        if case["kind"] == 5:
            result[index] = case, frames
    assert at == len(data["native"]) == 2120 and len(result) == 80
    return result


def state(observed: dict[str, Any] | None = None) -> LegacyRegistrationState:
    if observed is None:
        # Explicit old controller initial input; these are not captured before bytes.
        records = [bytearray(b"\xa5" * 64) for _ in range(16)]
        for index, raw in enumerate(records):
            struct.pack_into("<Q", raw, 0x10, 0x20001 + index if index < 15 else 0)
        links, head, available, rows = [0] * 8, 0x20000, 16, {}
    else:
        records = [bytearray.fromhex(raw) for raw in observed["records"]]
        links, head, available = observed["objects"], observed["head"], observed["free"]
        rows = {row[0]: LegacyMutationBucket(row[1], tuple(row[2:])) for row in observed["buckets"]}
    # All records already issued: block metadata/tiles are adapter declarations.
    return LegacyRegistrationState(
        200,
        200,
        tuple(max(-1, 5 - i.bit_length()) for i in range(64)),
        tuple(LegacyQueryLevel(i, 8 - i, 256 >> i, (4**i - 1) // 3) for i in range(6)),
        tuple(rows.get(i, LegacyMutationBucket(0, EMPTY)) for i in range(1365)),
        tuple(LegacyMutationRecord(0x20000 + i, bytes(raw)) for i, raw in enumerate(records)),
        tuple(LegacyMutationObject(0x10000 + i, 1000 + i, link) for i, link in enumerate(links)),
        LegacyRegistrationPool(
            (tuple(0x20000 + i for i in range(16)),), 1, -1, 0, head, available, 0
        ),
        (),
        TILES,
    )


def projection(value: LegacyRegistrationState) -> dict[str, Any]:
    return dict(
        free=value.pool.available,
        head=value.pool.free_head,
        objects=[obj.record_token for obj in value.objects],
        records=[record.raw.hex() for record in value.records],
        buckets=[
            [i, bucket.used, *bucket.slots]
            for i, bucket in enumerate(value.buckets)
            if bucket.slots != EMPTY
        ],
    )


def context(empty_callback: bool = False) -> LegacyRegistrationContext:
    return LegacyRegistrationContext(False, empty_callback, True, 0x1F80)


@pytest.mark.parametrize(
    "case_id",
    [i for i, (case, _) in native_cases().items() if any(op[0] == 0 for op in case["operations"])],
)
def test_existing_native_kind5_refreshes(case_id: int) -> None:
    case, frames = native_cases()[case_id]
    previous = None
    for operation, after in zip(case["operations"], frames, strict=True):
        code, obj, x, y, _flag_mode = operation
        if code == 0:
            before = state(previous)
            registry = LegacyRegistrationRegistry(before, context())
            result = registry.refresh(
                0x10000 + obj,
                position_bits=(x, y),
                radius_bits=tuple(case["radii"]),
                kind=5,
                mode=1,
                owner=0,
            )
            assert int(result.defined_al) == after["result"]
            assert projection(registry.snapshot()) == {
                key: after[key] for key in projection(registry.snapshot())
            }
            # Source-only absence checks: these buffers/traces were not captured.
            assert result.callback_bounds is None and result.fmod_calls == ()
            assert registry.snapshot().tile_words == before.tile_words
        # Actual removal/flag postframes seed later refreshes; this API does not execute them.
        previous = after


def test_native_input_authority_counts() -> None:
    count = prior_actual = source_initial = 0
    for case, frames in native_cases().values():
        assert len(case["operations"]) == len(frames)
        for step, operation in enumerate(case["operations"]):
            if operation[0] == 0:
                count += 1
                prior_actual += step > 0
                source_initial += step == 0
    assert (count, prior_actual, source_initial) == (528, 502, 26)


@pytest.mark.parametrize(
    ("radius", "squared"),
    [
        (0, 0),
        (0x80000000, 0),
        (1, 0),
        (0x1A000000, 0),
        (0x1A000001, 1),
        (0x1A800000, 2),
        (0x20000000, 0x800000),
        (0x45800000, 0x4B800000),
    ],
)
def test_source_derived_radius_square_boundaries(radius: int, squared: int) -> None:
    registry = LegacyRegistrationRegistry(state(), context())
    result = registry.refresh(
        0x10000,
        position_bits=(0x80000000, 0),
        radius_bits=(radius, 0x3E800000),
        kind=5,
        mode=255,
        owner=6,
    )
    raw = registry.snapshot().records[0].raw
    assert struct.unpack_from("<4I", raw, 0x30) == (0x80000000, 0, radius, squared)
    assert result.callback_bounds is None and result.fmod_calls == ()
    assert registry.snapshot().tile_words == TILES


def test_kind2_requires_callback_premise_after_kind5_on_same_registry() -> None:
    registry = LegacyRegistrationRegistry(state(), context())
    arguments = dict(
        position_bits=(0x41A00000, 0x41A00000),
        radius_bits=(0x3F000000, 0x3E800000),
        mode=5,
        owner=0,
    )
    registry.refresh(0x10000, kind=5, **arguments)
    before = registry.snapshot()
    with pytest.raises(UnsupportedLegacyRegistration, match="kind2 requires"):
        registry.refresh(0x10000, kind=2, **arguments)
    assert registry.snapshot() == before


@pytest.mark.parametrize("unsupported", ["kind", "finite", "pool"])
def test_shared_phase_support_refusals_use_public_registration_error(unsupported: str) -> None:
    initial = state()
    arguments: dict[str, Any] = dict(
        position_bits=(0, 0), radius_bits=(0, 0), kind=5, mode=1, owner=0
    )
    if unsupported == "kind":
        arguments["kind"] = 3
    elif unsupported == "finite":
        arguments["position_bits"] = (0x7F800000, 0)
    else:
        initial = replace(
            initial,
            pool=replace(initial.pool, free_head=0, available=0),
            reserved_tokens=tuple(record.token for record in initial.records),
        )
    registry = LegacyRegistrationRegistry(initial, context())
    with pytest.raises(UnsupportedLegacyRegistration) as caught:
        registry.refresh(0x10000, **arguments)
    assert type(caught.value.__cause__) is UnsupportedLegacyKind2
    assert registry.snapshot() == initial


def test_generic_argument_errors_remain_plain_value_errors() -> None:
    initial = state()
    registry = LegacyRegistrationRegistry(initial, context())
    with pytest.raises(ValueError) as caught:
        registry.refresh(
            0x10000, position_bits=(0, 0), radius_bits=(0, 0), kind=5, mode=1, owner=True
        )
    assert type(caught.value) is ValueError
    assert registry.snapshot() == initial


def test_kind_transitions_preserve_existing_flags_and_circle_tail() -> None:
    registry = LegacyRegistrationRegistry(state(), context(True))
    arguments = dict(
        position_bits=(0x41A00000, 0x41A00000),
        radius_bits=(0x3F000000, 0x3E800000),
        mode=5,
        owner=1,
    )
    registry.refresh(0x10000, kind=5, **arguments)
    before = registry.snapshot()
    raw = bytearray(before.records[0].raw)
    raw[2:4] = b"\x31\xe7"
    registry = LegacyRegistrationRegistry(
        replace(before, records=(replace(before.records[0], raw=bytes(raw)), *before.records[1:])),
        context(True),
    )
    result = registry.refresh(0x10000, kind=2, **arguments)
    after = registry.snapshot().records[0].raw
    assert after[:2] == b"\x03\x02" and after[2:4] == b"\x31\xe7"
    assert after[0x30:] == raw[0x30:] and result.callback_bounds is not None
    assert result.fmod_calls
    result = registry.refresh(0x10000, kind=5, **dict(arguments, radius_bits=(0x3E800000, 0)))
    after = registry.snapshot().records[0].raw
    assert after[:2] == b"\x02\x05" and after[2:4] == b"\x31\xe7"
    assert struct.unpack_from("<4I", after, 0x30)[2:] == (0x3E800000, 0x3D800000)
    assert result.callback_bounds is None and result.fmod_calls == ()


def test_source_kind5_uses_unissued_slot_after_reserved_records() -> None:
    initial = state()
    initial = replace(
        initial,
        pool=replace(initial.pool, current_block=0, next_slot=4, free_head=0, available=12),
        reserved_tokens=tuple(record.token for record in initial.records[:4]),
    )
    registry = LegacyRegistrationRegistry(initial, context())
    registry.refresh(0x10000, position_bits=(0, 0), radius_bits=(0, 0), kind=5, mode=1, owner=0)
    after = registry.snapshot()
    assert after.objects[0].record_token == initial.records[4].token
    assert (after.pool.current_block, after.pool.next_slot, after.pool.available) == (0, 5, 11)
    assert after.reserved_tokens == initial.reserved_tokens
    assert after.records[:4] == initial.records[:4]


def test_generic_kind2_agrees_with_specialized_public_api() -> None:
    initial = state()
    generic = LegacyRegistrationRegistry(initial, context(True))
    specialized = LegacyKind2Registry(initial, LegacyKind2Context(False, True, True, 0x1F80))
    arguments = dict(
        position_bits=(0x41A00000, 0x41A00000),
        radius_bits=(0x3F000000, 0x3F000000),
        kind=2,
        mode=5,
        owner=2,
    )
    actual, expected = (
        generic.refresh(0x10000, **arguments),
        specialized.refresh(0x10000, **arguments),
    )
    assert (actual.defined_al, actual.callback_bounds, actual.fmod_calls) == (
        expected.defined_al,
        expected.callback_bounds,
        expected.fmod_calls,
    )
    assert generic.snapshot() == specialized.snapshot()


@pytest.mark.parametrize(
    "changes",
    [
        {"modern_enabled": True},
        {"disjoint_backing": False},
        {"mxcsr": 0},
        {"mxcsr": 0x1FC0},
        {"mxcsr": 0x9F80},
        {"mxcsr": 0x3F80},
        {"modern_enabled": 0},
        {"genuine_empty_listener_callback": 0},
        {"mxcsr": True},
    ],
)
def test_refuse_unproved_context(changes: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        LegacyRegistrationContext(
            **dict(
                dict(
                    modern_enabled=False,
                    genuine_empty_listener_callback=False,
                    disjoint_backing=True,
                    mxcsr=0x1F80,
                ),
                **changes,
            )
        )


@pytest.mark.parametrize("status", [0, 1, 3, 8, 16, 32, 63])
def test_source_derived_sticky_status_admission(status: int) -> None:
    supplied = replace(context(), mxcsr=0x1F80 | status)
    registry = LegacyRegistrationRegistry(state(), supplied)
    assert registry.refresh(
        0x10000, position_bits=(0, 0), radius_bits=(0, 0), kind=5, mode=1, owner=0
    ).defined_al


@pytest.mark.parametrize("case_id", list(native_cases()))
def test_existing_native_kind5_consecutive_lifecycle(case_id: int) -> None:
    case, frames = native_cases()[case_id]
    registry = LegacyRegistrationRegistry(state(), context())
    for operation, observed in zip(case["operations"], frames, strict=True):
        code, obj, x, y, flag_mode = operation
        if code == 0:
            result = registry.refresh(
                0x10000 + obj,
                position_bits=(x, y),
                radius_bits=tuple(case["radii"]),
                kind=5,
                mode=1,
                owner=0,
            )
            assert int(result.defined_al) == observed["result"]
        elif code == 1:
            assert int(registry.remove(0x10000 + obj, kind=5)) == observed["result"]
        else:
            assert code == 2 and flag_mode in (0, 16)
            # The controller's result0 is not a native void-leaf return value.
            assert registry.action_end_flags(0x10000 + obj, mode=flag_mode) is None
        after = registry.snapshot()
        assert projection(after) == {key: observed[key] for key in projection(after)}
        assert after.tile_words == TILES  # Source-only: the old fixture omits tiles.


def test_source_release_keeps_cursor_and_borrows_returned_before_unissued() -> None:
    initial = state()
    initial = replace(
        initial,
        pool=replace(initial.pool, current_block=0, next_slot=4, free_head=0, available=12),
        reserved_tokens=tuple(record.token for record in initial.records[:4]),
    )
    registry = LegacyRegistrationRegistry(initial, context())
    arguments = dict(position_bits=(0, 0), radius_bits=(0, 0), kind=5, mode=255, owner=6)
    for obj in (0x10000, 0x10001, 0x10002):
        registry.refresh(obj, **arguments)
    before = registry.snapshot()
    assert before.pool.next_slot == 7 and before.pool.available == 9
    assert registry.remove(0x10001, kind=5) is True
    after = registry.snapshot()
    token = initial.records[5].token
    assert after.pool.free_head == token and after.pool.available == 10
    assert after.pool.current_block == 0 and after.pool.next_slot == 7
    assert after.records[5].raw[:0x10] == before.records[5].raw[:0x10]
    assert after.records[5].raw[0x18:] == before.records[5].raw[0x18:]
    assert struct.unpack_from("<Q", after.records[5].raw, 0x10)[0] == 0
    assert after.reserved_tokens == initial.reserved_tokens
    assert after.records[:4] == initial.records[:4] and after.tile_words == TILES
    repeated = after
    assert registry.remove(0x10001, kind=5) is False
    assert registry.snapshot() == repeated
    registry.refresh(0x10003, **arguments)
    after = registry.snapshot()
    assert after.objects[3].record_token == token
    assert after.pool.next_slot == 7 and after.pool.free_head == 0 and after.pool.available == 9
    registry.refresh(0x10004, **arguments)
    after = registry.snapshot()
    assert after.objects[4].record_token == initial.records[7].token
    assert after.pool.next_slot == 8 and after.pool.available == 8


def test_source_release_uses_current_master_kind_after_kind2_refresh() -> None:
    registry = LegacyRegistrationRegistry(state(), context(True))
    registry.refresh(
        0x10000,
        position_bits=(0x41A00000, 0x41A00000),
        radius_bits=(0x3F000000, 0x3F000000),
        kind=2,
        mode=5,
        owner=0,
    )
    before = registry.snapshot()
    assert before.records[0].raw[1] == 2
    assert registry.remove(0x10000, kind=5) is True
    after = registry.snapshot()
    assert after.records[0].raw[1] == 2 and after.tile_words == before.tile_words
    assert after.objects[0].record_token == 0
    assert after.pool.available == before.pool.available + 1


@pytest.mark.parametrize("kind", [0, 2, 3, 11, 12, 13, True, None])
def test_refuse_unproved_removal_even_without_a_record(kind: Any) -> None:
    initial = state()
    registry = LegacyRegistrationRegistry(initial, context())
    with pytest.raises(UnsupportedLegacyRegistration):
        registry.remove(0x10000, kind=kind)
    assert registry.snapshot() == initial


@pytest.mark.parametrize("mode", [1, 255, 256, 65536, -1, True, None, "0"])
def test_refuse_unproved_action_end_flag_mode_without_mutation(mode: Any) -> None:
    initial = state()
    registry = LegacyRegistrationRegistry(initial, context())
    with pytest.raises(UnsupportedLegacyRegistration):
        registry.action_end_flags(0x10000, mode=mode)
    assert registry.snapshot() == initial


def test_source_flags_only_change_linked_record_flag_byte() -> None:
    registry = LegacyRegistrationRegistry(state(), context())
    assert registry.action_end_flags(0x10000, mode=16) is None
    assert registry.snapshot() == state()
    registry.refresh(0x10000, position_bits=(0, 0), radius_bits=(0, 0), kind=5, mode=1, owner=0)
    before = registry.snapshot()
    raw = bytearray(before.records[0].raw)
    raw[3] = 0xE7
    before = replace(
        before, records=(replace(before.records[0], raw=bytes(raw)), *before.records[1:])
    )
    registry = LegacyRegistrationRegistry(before, context())
    assert registry.action_end_flags(0x10000, mode=16) is None
    expected = bytearray(raw)
    expected[3] = 0x17
    after = registry.snapshot()
    assert after == replace(
        before, records=(replace(before.records[0], raw=bytes(expected)), *before.records[1:])
    )
    assert registry.action_end_flags(0x10000, mode=0) is None
    expected[3] = 7
    assert registry.snapshot() == replace(
        before, records=(replace(before.records[0], raw=bytes(expected)), *before.records[1:])
    )
