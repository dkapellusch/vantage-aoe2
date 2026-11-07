from __future__ import annotations

import gzip
import hashlib
import json
import struct
from dataclasses import replace
from pathlib import Path

import pytest

from vantage.replay_legacy_mutation import (
    LegacyContactRegistry,
    LegacyMutationBucket,
    LegacyMutationObject,
    LegacyMutationRecord,
    LegacyMutationState,
    UnsupportedLegacyMutation,
)
from vantage.replay_legacy_query import LegacyQueryLevel, legacy_query_segment

FIXTURES = Path(__file__).parent / "fixtures"
RAW = (FIXTURES / "native_legacy_mutation_2120.json.gz").read_bytes()
DATA = json.loads(gzip.decompress(RAW))
EXTERNAL_RAW = (FIXTURES / "native_legacy_external_rows_145.json.gz").read_bytes()
EXTERNAL = json.loads(gzip.decompress(EXTERNAL_RAW))
DIMENSION_RAW = (FIXTURES / "native_legacy_dimensions_1728.json.gz").read_bytes()
DIMENSIONS = json.loads(gzip.decompress(DIMENSION_RAW))
POISON = 0xA5A5A5A5A5A5A5A5
EMPTY_SLOTS = (POISON,) * 16


def bits(value: float) -> int:
    return struct.unpack("<I", struct.pack("<f", value))[0]


def initial_state(
    seed: dict | None = None,
    *,
    objects: int = 8,
    records: int = 16,
    dimensions: tuple[int, int] = (200, 200),
):
    if seed is None:
        raw_records = [bytearray(b"\xa5" * 64) for _ in range(records)]
        for i, raw in enumerate(raw_records):
            struct.pack_into("<Q", raw, 0x10, 0x20000 + i + 1 if i + 1 < records else 0)
        rows, links, head, count = {}, [0] * objects, 0x20000 if records else 0, records
    else:
        raw_records = [bytes.fromhex(raw) for raw in seed["records"]]
        rows = {row[0]: LegacyMutationBucket(row[1], tuple(row[2:])) for row in seed["buckets"]}
        links, head, count = seed["objects"], seed["head"], seed["free"]
    levels = tuple(LegacyQueryLevel(i, 8 - i, 256 >> i, (4**i - 1) // 3) for i in range(6))
    return LegacyMutationState(
        *dimensions,
        tuple(max(-1, 5 - i.bit_length()) for i in range(64)),
        levels,
        tuple(rows.get(i, LegacyMutationBucket(0, EMPTY_SLOTS)) for i in range(1365)),
        tuple(LegacyMutationRecord(0x20000 + i, bytes(raw)) for i, raw in enumerate(raw_records)),
        tuple(LegacyMutationObject(0x10000 + i, 1000 + i, token) for i, token in enumerate(links)),
        head,
        count,
        False,
    )


def run(registry: LegacyContactRegistry, kind: int, radii: list[int], operation: list[int]):
    code, obj, x, y, mode = operation
    token = 0x10000 + obj
    if code == 0:
        return registry.refresh(
            token, kind=kind, enabled=True, position_bits=(x, y), radius_bits=tuple(radii)
        )
    if code == 1:
        return registry.remove(token, kind=kind)
    assert registry.action_end_flags(token, mode=mode) is None
    return None


def observed(snapshot: LegacyMutationState) -> dict:
    return dict(
        free=snapshot.free_count,
        head=snapshot.free_head,
        objects=[obj.record_token for obj in snapshot.objects],
        records=[record.raw.hex() for record in snapshot.records],
        buckets=[
            [i, bucket.used, *bucket.slots]
            for i, bucket in enumerate(snapshot.buckets)
            if bucket.slots != EMPTY_SLOTS
        ],
    )


def test_fixtures_bind_unchanged_original_entries_and_independent_foreign_rows():
    assert hashlib.sha256(RAW).hexdigest() == (
        "b247f3fc0d192fa61937c9243f1eb16cbf3c2d70f1123e182bff3ec8ebfbf150"
    )
    assert DATA["evidence_id"] == (
        "ev_8186aa169d0476733ed20f79cf60b3e2104ae70e0b3aa4d6653f8323a9631531"
    )
    assert not DATA["original_code_changed"] and not DATA["modern_enabled"]
    assert len(DATA["cases"]) == 158 and len(DATA["native"]) == 2120
    assert hashlib.sha256(EXTERNAL_RAW).hexdigest() == (
        "ca81b51041180e44d79437512fadd4dedf70c858efb8a10c40dba2e745b9f13c"
    )
    assert EXTERNAL["evidence_id"] == (
        "ev_d506d2806a3b3b45e057a8191f99fe91f6b84f728544392ffaf35c190eaa8085"
    )
    assert EXTERNAL["original_functions"] == DATA["original_functions"]
    assert len(EXTERNAL["cases"]) == 12 and len(EXTERNAL["native"]) == 145
    assert EXTERNAL["foreign_rows"]["repaired_row_cases"] == 6
    assert EXTERNAL["foreign_rows"]["full_payload_preserved_except_row"]
    assert hashlib.sha256(DIMENSION_RAW).hexdigest() == (
        "8c3936fb09bfa3faa6ef4dd4fa1990becd0ccd5c806b03c7c64e3334f03c2d74"
    )
    assert DIMENSIONS["evidence_id"] == (
        "ev_c4cea9890717f9dc4535297c6b0b85e7868bc60b12144187e039377b48b84980"
    )
    assert DIMENSIONS["original_functions"] == DATA["original_functions"]
    assert len(DIMENSIONS["cases"]) == 108 and len(DIMENSIONS["native"]) == 1728


@pytest.mark.parametrize("kind", [3, 5])
def test_all_original_native_records_full_ordered_slots_and_free_pool(kind):
    expected = iter(DATA["native"])
    checked = 0
    for index, case in enumerate(DATA["cases"]):
        rows = [next(expected) for _ in case["operations"]]
        if case["kind"] != kind:
            continue
        registry = LegacyContactRegistry(initial_state())
        for step, (operation, row) in enumerate(zip(case["operations"], rows, strict=True)):
            result = run(registry, kind, case["radii"], operation)
            if result is not None:
                assert int(result) == row["result"], (index, step)
            snapshot = registry.snapshot()
            assert observed(snapshot) == {key: row[key] for key in observed(snapshot)}, (
                index,
                step,
                operation,
            )
            checked += 1
    assert checked == (1056 if kind == 3 else 1064)


@pytest.mark.parametrize("foreign_kind", [2, 11, 13])
def test_untouched_foreign_payload_survives_native_swap_repair(foreign_kind):
    expected = iter(EXTERNAL["native"])
    repaired = 0
    for case in EXTERNAL["cases"]:
        rows = [next(expected) for _ in case["operations"]]
        if case["foreign_kind"] != foreign_kind:
            continue
        state = initial_state(case["initial_state"])
        registry = LegacyContactRegistry(state)
        initial = state.records[0].raw
        row_changed = False
        for operation, row in zip(case["operations"], rows, strict=True):
            result = run(registry, case["kind"], case["radii"], operation)
            if result is not None:
                assert int(result) == row["result"]
            snapshot = registry.snapshot()
            actual = observed(snapshot)
            assert actual == {key: row[key] for key in actual}
            foreign = snapshot.records[0].raw
            assert foreign[:0x1C] == initial[:0x1C] and foreign[0x20:] == initial[0x20:]
            row_changed |= foreign[0x1C:0x20] != initial[0x1C:0x20]
        assert row_changed == (case["actor_row"] == 0)
        repaired += int(row_changed)
    assert repaired == 2


@pytest.mark.parametrize("dimensions", DIMENSIONS["dimensions"])
def test_native_per_axis_clipping_with_same_initialized_levels(dimensions):
    expected = iter(DIMENSIONS["native"])
    checked = 0
    for index, case in enumerate(DIMENSIONS["cases"]):
        rows = [next(expected) for _ in case["operations"]]
        if case["dimensions"] != dimensions:
            continue
        registry = LegacyContactRegistry(initial_state(dimensions=tuple(dimensions)))
        for step, (operation, row) in enumerate(zip(case["operations"], rows, strict=True)):
            result = run(registry, case["kind"], case["radii"], operation)
            if result is not None:
                assert int(result) == row["result"]
            actual = observed(registry.snapshot())
            assert actual == {key: row[key] for key in actual}, (index, step, operation)
            checked += 1
    assert checked == 192


def test_snapshot_is_an_independent_seek_checkpoint_and_refresh_does_not_snapshot(monkeypatch):
    registry = LegacyContactRegistry(initial_state())
    first = [0, 0, bits(100.5), bits(100.5), 0]
    run(registry, 5, [bits(0.3)] * 2, first)
    checkpoint = registry.snapshot()
    resumed = LegacyContactRegistry(checkpoint)
    second = [0, 0, bits(10.1), bits(10.1), 0]
    # A refresh must not rebuild or fully validate an immutable checkpoint.
    with monkeypatch.context() as patch:
        patch.setattr(registry, "snapshot", lambda: pytest.fail("implicit full snapshot"))
        run(registry, 5, [bits(0.3)] * 2, second)
    run(resumed, 5, [bits(0.3)] * 2, second)
    assert registry.snapshot() == resumed.snapshot()
    assert checkpoint.objects[0].record_token == 0x20000
    assert checkpoint.records[0].raw != registry.snapshot().records[0].raw


def test_query_snapshot_reuses_unchanged_collector_and_preserves_used_order():
    case = next(row for row in EXTERNAL["cases"] if row["actor_row"] == 0)
    registry = LegacyContactRegistry(initial_state(case["initial_state"]))
    before = registry.query_index_snapshot(callback_outputs_independent=True)
    segment = (bits(99), bits(100.5), bits(102), bits(100.5))
    result = legacy_query_segment(before, segment, radius_bits=0, expand=False)
    assert result.collision_tokens == (0x20001, 0x20000)
    registry.refresh(
        0x10000,
        kind=3,
        enabled=True,
        position_bits=(bits(10.1), bits(10.1)),
        radius_bits=(bits(0.3), bits(0.3)),
    )
    after = registry.query_index_snapshot(callback_outputs_independent=True)
    assert legacy_query_segment(after, segment, radius_bits=0, expand=False).collision_tokens == (
        0x20000,
    )
    assert legacy_query_segment(before, segment, radius_bits=0, expand=False) == result
    with pytest.raises(UnsupportedLegacyMutation, match="independence"):
        registry.query_index_snapshot(callback_outputs_independent=False)


def test_full_bucket_and_exhausted_pool_reject_before_any_partial_mutation():
    registry = LegacyContactRegistry(initial_state(objects=17))
    arguments = dict(
        kind=5,
        enabled=True,
        position_bits=(bits(100.5), bits(100.5)),
        radius_bits=(bits(0.3), bits(0.3)),
    )
    for i in range(16):
        assert registry.refresh(0x10000 + i, **arguments)
    full = registry.snapshot()
    with pytest.raises(UnsupportedLegacyMutation, match="growth"):
        registry.refresh(0x10010, **arguments)
    assert registry.snapshot() == full
    # Existing same-bucket records require neither allocation nor append capacity.
    assert registry.refresh(0x10000, **arguments)
    with pytest.raises(UnsupportedLegacyMutation, match="allocation"):
        registry.refresh(0x10010, **(arguments | {"position_bits": (bits(10), bits(10))}))
    assert registry.snapshot() == full
    assert registry.remove(0x10000, kind=5)
    assert registry.refresh(0x10010, **arguments)
    assert registry.snapshot().objects[16].record_token == 0x20000


@pytest.mark.parametrize("kind", [0, 1, 2, 10, 11, 12, 13, True, 3.0])
def test_terrain_and_unknown_current_master_kinds_fail_explicitly(kind):
    registry = LegacyContactRegistry(initial_state())
    before = registry.snapshot()
    with pytest.raises(UnsupportedLegacyMutation):
        registry.refresh(0x10000, kind=kind, enabled=True, position_bits=(0, 0), radius_bits=(0, 0))
    with pytest.raises(UnsupportedLegacyMutation):
        registry.remove(0x10000, kind=kind)
    assert registry.snapshot() == before


@pytest.mark.parametrize(
    "changes",
    [
        {"enabled": False},
        {"enabled": 1},
        {"position_bits": (0x7FC00000, 0)},
        {"position_bits": (0x7F800000, 0)},
        {"radius_bits": (bits(-0.3), 0)},
        {"position_bits": (bits(4097), 0)},
        {"position_bits": [0, 0]},
        {"position_bits": (True, 0)},
    ],
)
def test_malformed_and_unadmitted_refresh_inputs_leave_registry_unchanged(changes):
    registry = LegacyContactRegistry(initial_state())
    before = registry.snapshot()
    arguments = dict(kind=3, enabled=True, position_bits=(0, 0), radius_bits=(0, 0))
    with pytest.raises(ValueError):
        registry.refresh(0x10000, **(arguments | changes))
    assert registry.snapshot() == before


def test_null_removal_and_flag_phase_do_not_allocate_and_unknown_modes_do_not_run():
    registry = LegacyContactRegistry(initial_state())
    before = registry.snapshot()
    assert registry.remove(0x10000, kind=3) is False
    assert registry.action_end_flags(0x10000, mode=16) is None
    assert registry.snapshot() == before
    for mode in (1, 17, -1, True):
        with pytest.raises(UnsupportedLegacyMutation):
            registry.action_end_flags(0x10000, mode=mode)
    with pytest.raises(ValueError, match="registered"):
        registry.remove(0x10008, kind=3)


@pytest.mark.parametrize(
    "change",
    [
        "modern",
        "extent",
        "lookup",
        "level",
        "free-count",
        "free-cycle",
        "duplicate-record",
        "unknown-used",
        "duplicate-used",
        "wrong-row",
        "wrong-id",
        "missing-object-link",
        "overlapping-domains",
        "unaccounted-record",
    ],
)
def test_incoherent_initial_state_is_rejected(change):
    registry = LegacyContactRegistry(initial_state())
    registry.refresh(
        0x10000,
        kind=5,
        enabled=True,
        position_bits=(bits(100.5), bits(100.5)),
        radius_bits=(bits(0.3), bits(0.3)),
    )
    state = registry.snapshot()
    row = struct.unpack_from("<i", state.records[0].raw, 4)[0]
    with pytest.raises(ValueError):
        if change == "modern":
            replace(state, modern_enabled=True)
        elif change == "extent":
            replace(state, width=256)
        elif change == "lookup":
            replace(state, lookup_words=(4, *state.lookup_words[1:]))
        elif change == "level":
            replace(state, levels=(replace(state.levels[0], base_index=1), *state.levels[1:]))
        elif change == "free-count":
            replace(state, free_count=14)
        elif change == "free-cycle":
            raw = bytearray(state.records[1].raw)
            struct.pack_into("<Q", raw, 0x10, state.records[1].token)
            replace(
                state,
                records=(
                    state.records[0],
                    replace(state.records[1], raw=bytes(raw)),
                    *state.records[2:],
                ),
            )
        elif change == "duplicate-record":
            replace(state, records=(state.records[0], state.records[0], *state.records[2:]))
        elif change in ("unknown-used", "duplicate-used"):
            slots = list(state.buckets[row].slots)
            slots[1] = 0x999 if change == "unknown-used" else slots[0]
            buckets = list(state.buckets)
            buckets[row] = LegacyMutationBucket(2, tuple(slots))
            replace(state, buckets=tuple(buckets))
        elif change in ("wrong-row", "wrong-id"):
            raw = bytearray(state.records[0].raw)
            struct.pack_into("<i", raw, 0x1C if change == "wrong-row" else 0x18, 123)
            replace(state, records=(replace(state.records[0], raw=bytes(raw)), *state.records[1:]))
        elif change == "missing-object-link":
            replace(state, objects=(replace(state.objects[0], record_token=0), *state.objects[1:]))
        elif change == "overlapping-domains":
            replace(state, objects=(replace(state.objects[0], token=0x20000), *state.objects[1:]))
        else:
            replace(state, records=(*state.records, LegacyMutationRecord(0x30000, bytes(64))))
