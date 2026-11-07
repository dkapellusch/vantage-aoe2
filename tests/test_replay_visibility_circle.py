"""Sparse patches compared with every byte of complete original-call snapshots."""

from __future__ import annotations

import gzip
import hashlib
import json
import struct
from dataclasses import FrozenInstanceError, replace
from functools import lru_cache
from pathlib import Path

import pytest

from vantage.replay_visibility_circle import (
    ReplayVisibilityCircleContext,
    ReplayVisibilityCirclePatch,
    ReplayVisibilityCircleState,
    UnsupportedReplayVisibilityCircle,
    explore_replay_visibility_circle,
    unexplore_replay_visibility_circle,
)

FIXTURES = Path(__file__).parent / "fixtures"
GUARD = bytes.fromhex("59d30e874dba72c1") * 2


def _layout(width, height):
    lengths = dict(
        visible=0x48,
        world=0x780,
        owner=0x650,
        map=0x5BD0,
        descriptor=0x18,
        api=0x1A8,
        counters=width * height * 2,
        masks=(width + 2) * height * 8,
        tiles=width * height * 64,
        queue=(width * height + 8) * 8,
    )
    offsets, cursor = {}, 0
    for name, length in lengths.items():
        offsets[name] = (cursor + 16, length)
        cursor += length + 32
    return offsets, cursor


@lru_cache(maxsize=1)
def _corpus():
    compressed = (FIXTURES / "native_visibility_circle_effects_54800.bin.gz").read_bytes()
    assert hashlib.sha256(compressed).hexdigest() == (
        "75ae722d7b2216d0d4651adf23de9ed4cf3aa617081d12351b3118a2f2cf3530"
    )
    raw = gzip.decompress(compressed)
    assert len(raw) == 50737948
    assert hashlib.sha256(raw).hexdigest() == (
        "2d030fe6a0918c1eb315c0fd943ddcda78c7fb7a1431e7b6f8e940af34d5c5f9"
    )
    inputs = (FIXTURES / "native_visibility_circle_effect_inputs_54800.json.gz").read_bytes()
    assert hashlib.sha256(inputs).hexdigest() == (
        "099bd3a71948fa4ac88af198173f32e7daebc7dca505c239e075e400f44087c4"
    )
    cases = json.loads(gzip.decompress(inputs))
    assert len(cases) == 602
    corpus, cursor = [], 0
    for case in cases:
        offsets, expected_size = _layout(case["width"], case["height"])
        frames = []
        for op in (0xFFFFFFFF, *range(len(case["operations"]))):
            cid, operation, returned, size = struct.unpack_from("<4I", raw, cursor)
            assert (cid, operation, size) == (case["id"], op, expected_size)
            cursor += 16
            snapshot = raw[cursor : cursor + size]
            cursor += size
            for at, length in offsets.values():
                assert snapshot[at - 16 : at] == snapshot[at + length : at + length + 16] == GUARD
            frames.append((returned, snapshot))
        corpus.append((case, frames))
    assert cursor == len(raw)
    return corpus


def _decode(raw, case):
    offsets, _ = _layout(case["width"], case["height"])

    def region(name):
        at, size = offsets[name]
        return raw[at : at + size]

    def word(name, at, fmt="I"):
        return struct.unpack_from("<" + fmt, raw, offsets[name][0] + at)[0]

    state = ReplayVisibilityCircleState(
        width=word("visible", 0x20),
        height=word("visible", 0x24),
        mask_stride=word("descriptor", 0x10),
        counters_u16_le=region("counters"),
        masks_u64_le=region("masks"),
        tile_flags19=region("tiles")[0x19::64],
        explored_count=word("visible", 0x28),
        dirty_capacity=word("owner", 0xA0),
        dirty_count=word("owner", 0xA4),
        dirty_activity=word("owner", 0xA8),
        explore_mask=word("visible", 0x30, "Q"),
        unexplore_mask=word("visible", 0x38, "Q"),
        permanent_mask=word("visible", 0x40, "Q"),
    )
    context = ReplayVisibilityCircleContext(
        observer_index=word("world", 0x6B0),
        owner_type=word("owner", 0x10, "i"),
        api_context_present=True,
        notification_disable_byte=region("api")[0x1A1],
        debug_byte=0,
        disable_word=case["disabled"],
    )
    return state, context


def _apply(raw, case, state, patch):
    offsets, _ = _layout(case["width"], case["height"])
    result = bytearray(raw)

    def put(name, at, value, fmt="I"):
        struct.pack_into("<" + fmt, result, offsets[name][0] + at, value)

    for index, value in patch.counter_writes:
        assert 0 <= index < state.width * state.height
        put("counters", index * 2, value, "H")
    for index, value in patch.mask_writes:
        assert 0 <= index < state.mask_stride * state.height
        put("masks", index * 8, value, "Q")
    for index, value in patch.tile17_writes:
        assert 0 <= index < state.width * state.height
        put("tiles", index * 64 + 0x17, value, "B")
    for offset, (x, y) in enumerate(patch.dirty_appends, start=state.dirty_count):
        assert offset < state.dirty_capacity
        put("queue", offset * 8, x, "i")
        put("queue", offset * 8 + 4, y, "i")
    put("visible", 0x28, patch.explored_count)
    put("owner", 0xA4, patch.dirty_count)
    put("owner", 0xA8, patch.dirty_activity)
    return bytes(result)


@pytest.mark.parametrize("case_id", range(602))
def test_complete_native_buffers_after_each_call(case_id):
    case, frames = _corpus()[case_id]
    current = frames[0][1]
    for index, (entry, update) in enumerate(case["operations"]):
        state, context = _decode(current, case)
        function = (
            explore_replay_visibility_circle if entry == 0 else unexplore_replay_visibility_circle
        )
        patch = function(state, context, case["x"], case["y"], case["radius"], case["mode"], update)
        returned, expected = frames[index + 1]
        assert patch.newly_explored == (returned if entry == 0 else None)
        current = _apply(current, case, state, patch)
        assert current == expected  # all ten complete regions, padding, slack and guards


def _single(old=0):
    state = ReplayVisibilityCircleState(
        width=1,
        height=1,
        mask_stride=2,
        counters_u16_le=struct.pack("<H", old),
        masks_u64_le=struct.pack("<QQ", 3, 0xDEADBEEF),
        tile_flags19=b"\0",
        explored_count=0xFFFFFFFF,
        dirty_capacity=3,
        dirty_count=2,
        dirty_activity=0xFFFFFFFF,
        explore_mask=4,
        unexplore_mask=0xFFFFFFFFFFFFFFFE,
        permanent_mask=8,
    )
    context = ReplayVisibilityCircleContext(0xFFFFFFFF, 2, True, 1, 0, 0)
    return state, context


@pytest.mark.parametrize(
    "field,value,reason",
    [
        ("observer_index", 0, "observer"),
        ("owner_type", 3, "virtual88"),
        ("api_context_present", False, "notifications"),
        ("notification_disable_byte", 0, "notifications"),
        ("debug_byte", 1, "logging"),
    ],
)
def test_required_open_dependency_rejected_without_input_mutation(field, value, reason):
    state, context = _single()
    before = (state.counters_u16_le, state.masks_u64_le, state.tile_flags19)
    with pytest.raises(UnsupportedReplayVisibilityCircle, match=reason):
        explore_replay_visibility_circle(state, replace(context, **{field: value}), 0, 0, 0, 0, 1)
    assert (state.counters_u16_le, state.masks_u64_le, state.tile_flags19) == before


def test_neighbor_and_growth_paths_rejected():
    state, context = _single(0xFFFF)
    for changed, reason in (
        (replace(state, tile_flags19=b"\x60"), "neighbors"),
        (replace(state, dirty_capacity=2), "growth"),
    ):
        with pytest.raises(UnsupportedReplayVisibilityCircle, match=reason):
            explore_replay_visibility_circle(changed, context, 0, 0, 0, 0, 1)


def test_counter_only_branch_does_not_require_inactive_mask_or_owner_dependencies():
    state, context = _single(1)
    context = replace(context, owner_type=3, api_context_present=False, debug_byte=1)
    patch = explore_replay_visibility_circle(state, context, 0, 0, 0, 0, 1)
    assert patch.counter_writes == ((0, 2),)
    assert not patch.mask_writes and not patch.tile17_writes and not patch.dirty_appends


def test_unexplore_does_not_require_owner_callback_or_queue_capacity():
    state, context = _single()
    patch = unexplore_replay_visibility_circle(
        replace(state, dirty_count=0, dirty_capacity=0),
        replace(context, owner_type=3),
        0,
        0,
        0,
        0,
        1,
    )
    assert patch.newly_explored is None and patch.counter_writes == ((0, 0),)
    assert patch.mask_writes == ((0, 2),) and patch.tile17_writes == ((0, 0x80),)
    assert not patch.dirty_appends


def test_disable_precedes_table_index_and_dependency_reads():
    state, context = _single(0xFFFF)
    patch = explore_replay_visibility_circle(
        replace(state, tile_flags19=b"\x60", dirty_count=0, dirty_capacity=0),
        replace(
            context,
            observer_index=0,
            owner_type=3,
            api_context_present=False,
            debug_byte=1,
            disable_word=0xFFFFFFFF,
        ),
        0,
        0,
        -1,
        0,
        1,
    )
    assert patch == ReplayVisibilityCirclePatch((), (), (), (), 0xFFFFFFFF, 0, 0xFFFFFFFF, 0)


def test_owner_lookup_still_precedes_empty_geometry():
    state, context = _single()
    with pytest.raises(UnsupportedReplayVisibilityCircle, match="observer"):
        explore_replay_visibility_circle(
            state, replace(context, observer_index=0), 100, 100, 0, 0, 0
        )
    patch = explore_replay_visibility_circle(
        state, replace(context, api_context_present=False), 100, 100, 0, 0, 0
    )
    assert not patch.counter_writes and not patch.mask_writes


def test_neighbor_field_is_used_only_for_newly_explored_cells():
    state, context = _single()
    patch = explore_replay_visibility_circle(
        replace(state, tile_flags19=b"\x60"), context, 0, 0, 0, 0, 1
    )
    assert patch.newly_explored == 0 and patch.mask_writes == ((0, 7),)


def test_sparse_patch_and_immutable_buffers_preserve_queue_slack_and_mask_padding():
    state, context = _single(0xFFFF)
    counters, masks = state.counters_u16_le, state.masks_u64_le
    patch = explore_replay_visibility_circle(state, context, 0, 0, 0, 0, -1)
    assert patch.dirty_appends == ((0, 0),) and patch.dirty_count == 3
    assert patch.explored_count == patch.dirty_activity == 0
    assert patch.mask_writes == ((0, 15),) and len(patch.counter_writes) == 1
    assert state.counters_u16_le is counters and state.masks_u64_le is masks
    with pytest.raises(FrozenInstanceError):
        state.width = 2


@pytest.mark.parametrize(
    "field,value",
    [
        ("mask_stride", 0),
        ("counters_u16_le", b""),
        ("masks_u64_le", b""),
        ("tile_flags19", b""),
        ("dirty_count", 4),
        ("dirty_capacity", -1),
        ("dirty_activity", -1),
        ("explore_mask", 1 << 64),
    ],
)
def test_invalid_storage_rejected(field, value):
    state, _ = _single()
    with pytest.raises(UnsupportedReplayVisibilityCircle):
        replace(state, **{field: value})
