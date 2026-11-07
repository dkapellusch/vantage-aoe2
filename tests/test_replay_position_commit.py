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
from vantage.replay_legacy_query import LegacyQueryLevel
from vantage.replay_position_commit import (
    ReplayLogicalPosition,
    ReplayPositionCommitter,
    ReplaySameTileCommitProfile,
    UnsupportedPositionCommit,
)

RAW = (Path(__file__).parent / "fixtures" / "native_position_setters_96.json.gz").read_bytes()
DATA = json.loads(gzip.decompress(RAW))
POISON = 0xA5A5A5A5A5A5A5A5
EMPTY = LegacyMutationBucket(0, (POISON,) * 16)


def bits(value: float) -> int:
    return struct.unpack("<I", struct.pack("<f", value))[0]


def state(raw: dict) -> ReplayLogicalPosition:
    return ReplayLogicalPosition(
        tuple(raw["position_bits"]),
        raw["grounded"],
        tuple(raw["stored_position_bits"]),
        raw["clock408"],
        raw["counter40c"],
    )


def profile(case: dict = DATA["cases"][0], **changes) -> ReplaySameTileCommitProfile:
    inputs = case["inputs"]
    fields = dict(
        modern_enabled=inputs["modern_enabled"],
        master_kind=5,
        master_index_field=2,
        radius_bits=(0x3E99999A, 0x3E99999A, 0x40000000),
        object_state188=2,
        collision_disable1c6=0,
        parent148_present=False,
        attachment_count=0,
        damage_controller_count=0,
        master_trail_mode=0,
        master_terrain_effect=7,
        terrain_effect_count=0,
        terrain_cache_matches=True,
        tile_slope=0,
        tile_height=inputs["flat_tile_height_byte"],
        elevation_mode=inputs["elevation_mode"],
        speed_cap_bits=0x3F333333,
    )
    fields.update(changes)
    return ReplaySameTileCommitProfile(**fields)


def initial_state() -> LegacyMutationState:
    # This is measured post-case0 state, not a direct pre-call index snapshot.
    # Original initialization and case0 both refresh the same original XY;
    # the retained source establishes idempotence for this explicit state.
    seed = DATA["seed_checkpoint"]["state"]
    buckets = {row[0]: LegacyMutationBucket(row[1], tuple(row[2:])) for row in seed["buckets"]}
    return LegacyMutationState(
        200,
        200,
        tuple(max(-1, 5 - i.bit_length()) for i in range(64)),
        tuple(LegacyQueryLevel(i, 8 - i, 256 >> i, (4**i - 1) // 3) for i in range(6)),
        tuple(buckets.get(i, EMPTY) for i in range(1365)),
        tuple(
            LegacyMutationRecord(0x20000 + i, bytes.fromhex(raw))
            for i, raw in enumerate(seed["records"])
        ),
        (LegacyMutationObject(0x10000, 10449, seed["subject_record_token"]),),
        seed["free_head"],
        seed["free_count"],
        False,
    )


def observed(snapshot: LegacyMutationState) -> dict:
    return dict(
        records=[record.raw.hex() for record in snapshot.records],
        buckets=[
            [i, bucket.used, *bucket.slots]
            for i, bucket in enumerate(snapshot.buckets)
            if bucket.slots != EMPTY.slots
        ],
        free_head=snapshot.free_head,
        free_count=snapshot.free_count,
        subject_record_token=snapshot.objects[0].record_token,
    )


def call(committer, case, *, position=None, target=None, **changes):
    kwargs = dict(
        entry=case["entry"],
        state=position or state(case["inputs"]["state"]),
        target_bits=target or tuple(case["inputs"]["target_bits"]),
        profile=profile(case),
        game_clock=case["inputs"]["game_clock"],
        object_token=0x10000,
    )
    kwargs.update(changes)
    return committer.commit(**kwargs)


def test_native_fixture_is_actual_output_with_all_entries_and_closure_controls():
    assert hashlib.sha256(RAW).hexdigest() == (
        "2c36d784d9ea1f37569181f49419bf7180af344a15937c37977d8447022aaa4e"
    )
    provenance = DATA["provenance"]
    assert provenance["native_output_sha256"] == (
        "d9fa4613d9ad4452fcdd7f61bfcb058bb17046407ebd6573b815a2bff5dd834c"
    )
    assert provenance["rea_evidence_id"] == (
        "ev_8d3a26a1a5c87c6827fa6363d4c274cfccce73484e972a0f15bc603f1d7f25c8"
    )
    assert len(DATA["cases"]) == 96 and DATA["closure_controls"]["verified_count"] == 3
    assert DATA["closure_controls"]["execute_faults_exact"]
    assert not DATA["closure_controls"]["runtime_addresses_exported"]
    assert not DATA["seed_checkpoint"]["direct_pre_call_index_snapshot"]


@pytest.mark.parametrize("entry", ["common", "moving", "unit70"])
def test_all_actual_native_logical_fields_and_complete_legacy_projection(entry):
    checked = return_differs = resynchronized = 0
    for case in DATA["cases"]:
        if case["entry"] != entry or not case["admitted_modern_disabled"]:
            continue
        initial = initial_state()
        registry = LegacyContactRegistry(initial)
        result = call(ReplayPositionCommitter(registry), case)
        assert result.state == state(case["expected"]["state"]), case["case"]
        assert result.terrain_return_bits == case["expected"]["terrain_return_bits"]
        assert result.legacy_refreshed is True
        snapshot = registry.snapshot()
        assert observed(snapshot) == case["expected"]["legacy"], case["case"]
        assert snapshot.width == initial.width and snapshot.height == initial.height
        assert snapshot.levels == initial.levels and snapshot.lookup_words == initial.lookup_words
        assert snapshot.modern_enabled is False
        original = state(case["inputs"]["state"])
        if entry == "common":
            assert result.state.stored_position_bits == original.stored_position_bits
            assert (result.state.clock408, result.state.counter40c) == (111, 222)
        resynchronized += result.state.clock408 == 6388
        return_differs += result.terrain_return_bits != result.state.position_bits[1]
        checked += 1
    assert checked == 16 and return_differs == 8
    assert resynchronized == (0 if entry == "common" else 14)


def test_all_modern_true_native_rows_remain_rejected_before_mutation():
    registry = LegacyContactRegistry(initial_state())
    before = registry.snapshot()
    checked = 0
    for case in DATA["cases"]:
        if case["inputs"]["modern_enabled"]:
            with pytest.raises(UnsupportedPositionCommit, match="combined modern"):
                profile(case)
            checked += 1
    assert checked == 48 and registry.snapshot() == before


@pytest.mark.parametrize(
    "change",
    [
        {"master_kind": 3},
        {"master_index_field": 0},
        {"object_state188": 7},
        {"radius_bits": (0, 0, 0)},
        {"collision_disable1c6": 1},
        {"parent148_present": True},
        {"attachment_count": 1},
        {"damage_controller_count": 1},
        {"master_trail_mode": 1},
        {"master_terrain_effect": 8},
        {"terrain_effect_count": 1},
        {"terrain_cache_matches": False},
        {"tile_slope": 1},
        {"tile_height": 1},
        {"elevation_mode": 3},
        {"speed_cap_bits": 0},
    ],
)
def test_missing_original_profile_gates_are_explicit_rejections(change):
    with pytest.raises(UnsupportedPositionCommit):
        profile(**change)


@pytest.mark.parametrize(
    "change",
    [
        {"entry": "unit80"},
        {"game_clock": -1},
        {"game_clock": True},
        {"object_token": 0},
        {"object_token": True},
        {"target": (0x7FC00000, 0, bits(128.45))},
        {"target": (bits(156.6), 0x7F800000, bits(128.45))},
        {"target": (bits(199), 0, bits(128.45))},
        {"target": (bits(157), 0, bits(128.45))},
        {"target": (bits(156.6), 0, bits(127.99))},
    ],
)
def test_bad_inputs_do_not_partially_mutate_the_registry(change):
    registry = LegacyContactRegistry(initial_state())
    before = registry.snapshot()
    with pytest.raises(ValueError):
        call(ReplayPositionCommitter(registry), DATA["cases"][0], **change)
    assert registry.snapshot() == before


@pytest.mark.parametrize("reason", ["capacity", "pool"])
def test_existing_registry_rejection_precedes_any_mutation(reason):
    initial = initial_state()
    if reason == "capacity":
        # Lowering the target within tile128 crosses a coarse legacy boundary
        # through radius.3; destination bucket0 has no preallocated capacity.
        buckets = list(initial.buckets)
        buckets[0] = LegacyMutationBucket(0, ())
        initial = replace(initial, buckets=tuple(buckets))
    else:
        initial = replace(
            initial,
            records=(),
            buckets=(EMPTY,) * 1365,
            free_head=0,
            free_count=0,
            objects=(LegacyMutationObject(0x10000, 10449, 0),),
        )
    registry = LegacyContactRegistry(initial)
    target = bits(156.6), 0, bits(128.05)
    with pytest.raises(UnsupportedLegacyMutation, match=r"growth|allocation"):
        call(ReplayPositionCommitter(registry), DATA["cases"][0], target=target)
    assert registry.snapshot() == initial


@pytest.mark.parametrize("difference,changed", [(0x33D6BF95, False), (0x33D6BF96, True)])
def test_strict_rounded_tolerance_and_explicit_clock_store(difference, changed):
    registry = LegacyContactRegistry(initial_state())
    original = state(DATA["cases"][0]["inputs"]["state"])
    target = original.position_bits[0], difference, original.position_bits[2]
    result = call(
        ReplayPositionCommitter(registry),
        DATA["cases"][0],
        entry="moving",
        target=target,
        profile=profile(elevation_mode=2),
        game_clock=0xFFFFFFFF,
    )
    assert result.state.position_bits == target
    assert result.state.stored_position_bits == (target if changed else original.position_bits)
    assert (result.state.clock408, result.state.counter40c) == (
        (0xFFFFFFFF, 0) if changed else (111, 222)
    )


def test_signed_zero_height_is_preserved_without_spurious_moving_resynchronization():
    registry = LegacyContactRegistry(initial_state())
    original = state(DATA["cases"][0]["inputs"]["state"])
    target = original.position_bits[0], 0x80000000, original.position_bits[2]
    result = call(
        ReplayPositionCommitter(registry),
        DATA["cases"][0],
        entry="unit70",
        target=target,
        profile=profile(elevation_mode=2),
        game_clock=0,
    )
    assert result.state.position_bits == target and result.state.grounded
    assert result.state.stored_position_bits == original.position_bits
    assert (result.state.clock408, result.state.counter40c) == (111, 222)
    assert result.terrain_return_bits == 0


def test_commit_has_no_implicit_whole_registry_snapshot(monkeypatch):
    registry = LegacyContactRegistry(initial_state())
    committer = ReplayPositionCommitter(registry)

    def forbidden():
        raise AssertionError("per-commit whole registry snapshot")

    monkeypatch.setattr(registry, "snapshot", forbidden)
    result = call(committer, DATA["cases"][0])
    assert result.state.position_bits == tuple(
        DATA["cases"][0]["expected"]["state"]["position_bits"]
    )


def test_constructor_and_state_reject_unproved_dimensions_and_malformed_words():
    with pytest.raises(UnsupportedPositionCommit, match="200x200"):
        ReplayPositionCommitter(LegacyContactRegistry(replace(initial_state(), width=199)))
    with pytest.raises(ValueError, match="u32"):
        replace(state(DATA["cases"][0]["inputs"]["state"]), clock408=True)
    with pytest.raises(UnsupportedPositionCommit, match="finite"):
        replace(state(DATA["cases"][0]["inputs"]["state"]), stored_position_bits=(0, 0, 0x7F800000))
