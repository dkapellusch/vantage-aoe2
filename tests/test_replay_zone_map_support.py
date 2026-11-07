"""Zone helper data movement, current imports and first real flood-fill boundary."""

from __future__ import annotations

import pytest

from vantage.replay_memory import ReplayMemory, ReplayMemoryError
from vantage.replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
)
from vantage.replay_unit_ai_base import bind_replay_unit_ai_base
from vantage.replay_unit_ai_construction import bind_replay_unit_ai_construction
from vantage.replay_unit_ai_map import ReplayUnitAIMapAtomics
from vantage.replay_zone_map_construction import bind_replay_zone_map_construction
from vantage.replay_zone_map_support import (
    assign_replay_zone_mask,
    bind_replay_zone_map_support,
    commit_replay_zone_pairs,
    initialize_replay_zone_scratch,
    move_replay_zone_pairs,
    refresh_replay_zone_map,
)


def context(memory):
    return ReplayTaskRebuildStorage(1, memory.read, memory.write)


def static(memory):
    for address, target in (
        (0x143199DC0, 0xCA110C),
        (0x143199938, 0x142D6E3B7),
        (0x143199DD0, 0x142D6BAB4),
        (0x1431999A0, 0x142D6E3DB),
    ):
        memory.map_bytes(address, target.to_bytes(8, "little"))


def test_composed_real_constructor_reaches_seed_flood_fill_with_owned_mask_rows_and_scratch():
    memory = ReplayMemory()
    static(memory)
    zone, dimensions, terrain, header, mask = (
        memory.allocate(n) for n in (0x858, 0x38, 256, 16, 4)
    )
    memory.write(dimensions + 0x30, 4, 2)
    memory.write(dimensions + 0x34, 4, 2)
    memory.write(dimensions + 8, 8, terrain)
    for index in range(4):
        memory.write(terrain + index * 64 + 9, 1, 0)
    memory.write(header, 8, mask)
    memory.write(header + 8, 8, mask + 4)
    memory.write(mask, 4, 0x3F800000)
    runtime = memory.runtime_calls(calloc_target=0xCA110C)
    support = bind_replay_zone_map_support(context(memory), runtime, imports=runtime)
    calls = bind_replay_zone_map_construction(
        context(memory),
        support,
        imports=runtime,
        atomics=ReplayUnitAIMapAtomics(memory.compare_exchange_u32, memory.fetch_add_u32),
    )
    assert calls.call is not None
    with pytest.raises(UnresolvedReplayTaskRebuild, match="1414eca00"):
        calls.call(0x1414EA4A0, (zone, dimensions, header), None)
    data = memory.read(zone + 0x808, 8)
    assert [memory.read(data + index * 2, 2) for index in range(4)] == [0, 512, 512, 512]
    vector = memory.read(zone + 0x818, 8)
    assert memory.read(vector, 4) == 0x3F800000
    assert memory.read(zone + 0x820, 8) == vector + 4
    scratch = memory.read(zone + 0x850, 8)
    assert memory.read(scratch + 8, 4) == 16
    assert memory.read(scratch + 12, 4) == 513 and memory.read(scratch + 32, 1) == 1
    with pytest.raises(ReplayMemoryError, match="undefined"):
        memory.read(zone + 0x838, 4)  # No final counter commit before fill returns.
    assert ReplayMemory.from_snapshot(memory.snapshot()).snapshot() == memory.snapshot()


def test_fresh_mask_assignment_preserves_raw_words_and_copies_in_order() -> None:
    memory = ReplayMemory()
    vector, source = memory.allocate(24), memory.allocate(12)
    memory.write_bytes(vector, bytes(24))
    memory.write_bytes(source, bytes.fromhex("4523817f0000008001000000"))
    assign_replay_zone_mask(context(memory), vector, source, 3, calls=memory.runtime_calls())
    begin = memory.read(vector, 8)
    assert memory.read_bytes(begin, 12) == memory.read_bytes(source, 12)
    assert memory.read(vector + 8, 8) == memory.read(vector + 16, 8) == begin + 12


def test_reused_mask_tail_uses_current_end_after_memmove() -> None:
    memory = ReplayMemory()
    vector, destination, source, changed = (memory.allocate(n) for n in (24, 16, 12, 8))
    for offset, value in ((0, destination), (8, destination + 4), (16, destination + 16)):
        memory.write(vector + offset, 8, value)
    memory.write_bytes(source, b"abcdefghijkl")

    def call(target, args, data):
        assert target == 0x142D6E3DB and args == (destination, source, 4)
        memory.move(*args)
        memory.write(vector + 8, 8, changed)

    assign_replay_zone_mask(context(memory), vector, source, 3, calls=ReplayTaskRebuildCalls(call))
    assert memory.read_bytes(destination, 4) == b"abcd"
    assert memory.read_bytes(changed, 8) == b"efghijkl"
    assert memory.read(vector + 8, 8) == changed + 8


def test_mask_growth_forwards_held_capacity_before_required_release_and_header_changes() -> None:
    memory = ReplayMemory()
    vector, old, source, changed = (memory.allocate(n) for n in (24, 8, 12, 4))
    for offset, value in ((0, old), (8, old + 8), (16, old + 8)):
        memory.write(vector + offset, 8, value)
    memory.write_bytes(old, b"old-data")
    reads = []
    seen = []

    def read(address, width):
        reads.append((address, width))
        value = memory.read(address, width)
        if address == vector + 16:
            memory.write(vector, 8, changed)
            memory.write(vector + 16, 8, changed + 4)
        return value

    def release(target, args, data):
        seen.append((target, args, data))
        raise UnresolvedReplayTaskRebuild("required mask release")

    current = ReplayTaskRebuildStorage(1, read, memory.write)
    with pytest.raises(UnresolvedReplayTaskRebuild, match="required mask release"):
        assign_replay_zone_mask(current, vector, source, 3, calls=ReplayTaskRebuildCalls(release))
    assert seen == [(0x1410565B0, (vector, old, 2), None)]
    assert reads == [(vector, 8), (vector + 16, 8)]
    assert memory.read(vector, 8) == changed
    assert memory.read(vector + 8, 8) == old + 8
    assert memory.read(vector + 16, 8) == changed + 4
    assert memory.read_bytes(old, 8) == b"old-data"


def test_scratch_effective_words_and_byte_use_native_store_order() -> None:
    memory = ReplayMemory()
    scratch = memory.allocate(40)
    writes = []

    def write(address, width, value):
        writes.append((address - scratch, width, value))
        memory.write(address, width, value)

    assert (
        initialize_replay_zone_scratch(
            ReplayTaskRebuildStorage(1, memory.read, write),
            scratch,
            0xFFFFFFFF00000010,
            0xDEAD00000201,
            0xAA01,
        )
        == 1
    )
    assert writes == [(8, 4, 16), (12, 4, 513), (32, 1, 1)]


@pytest.mark.parametrize("count", [0, 2])
def test_pair_move_has_real_move_zero_effects_and_still_calls_empty_release(count):
    memory = ReplayMemory()
    source, destination = memory.allocate(max(1, count * 16)), memory.allocate(max(1, count * 16))
    memory.write_bytes(source, bytes(range(count * 16)))
    with pytest.raises(UnresolvedReplayTaskRebuild, match="1414e9ff0"):
        move_replay_zone_pairs(
            context(memory),
            source,
            source + count * 16,
            destination,
            0xCAFE,
            calls=memory.runtime_calls(),
        )
    assert memory.read_bytes(destination, count * 16) == bytes(range(count * 16))
    assert memory.read_bytes(source, count * 16) == bytes(count * 16)


def test_pair_move_exact_self_alias_reads_after_destination_zeroing() -> None:
    memory = ReplayMemory()
    source = memory.allocate(16)
    memory.write_bytes(source, b"x" * 16)
    seen = []

    def call(target, args, data):
        seen.append((target, args, data))

    assert (
        move_replay_zone_pairs(
            context(memory), source, source + 16, source, 7, calls=ReplayTaskRebuildCalls(call)
        )
        == source + 16
    )
    assert memory.read(source, 16) == 0
    assert seen == [(0x1414E9FF0, (source + 16, source + 16, 7), None)]


def test_pair_commit_reloads_current_large_allocation_after_release_before_free() -> None:
    memory = ReplayMemory()
    vector, old = memory.allocate(24), memory.allocate(16)
    large = memory.allocate_aligned(4096)
    base = memory.read(large - 8, 8)
    for offset, value in ((0, old), (8, old + 16), (16, old + 16)):
        memory.write(vector + offset, 8, value)
    seen = []

    def call(target, args, data):
        seen.append((target, args))
        if target == 0x1414E9FF0:
            assert args == (old, old + 16, vector)
            memory.write(vector, 8, large)
            memory.write(vector + 16, 8, large + 4096)
        else:
            assert target == 0x142D6BAB4 and args == (base, 4135)
            memory.free(base)
        return None

    commit_replay_zone_pairs(
        context(memory), vector, 0xCAFE, 2, 3, calls=ReplayTaskRebuildCalls(call)
    )
    assert len(seen) == 2 and memory.read(vector, 8) == 0xCAFE
    assert memory.read(vector + 8, 8) == 0xCB1E and memory.read(vector + 16, 8) == 0xCB2E


def test_refresh_captured_limits_and_current_bounds_skip_without_fabricating_fill() -> None:
    memory = ReplayMemory()
    zone, dims, rows, cells = (memory.allocate(n) for n in (0x858, 0x38, 16, 8))
    for address, value in (
        (zone + 0x830, dims),
        (zone + 0x810, rows),
        (rows, cells),
        (rows + 8, cells + 4),
    ):
        memory.write(address, 8, value)
    memory.write(dims + 0x30, 4, 2)
    memory.write(dims + 0x34, 4, 2)
    stores = []

    def write(address, width, value):
        stores.append((address, width, value))
        memory.write(address, width, value)
        if address == cells + 6:
            memory.write(dims + 0x34, 4, 0)  # Clear uses captured limit; seeds use current bounds.

    refresh_replay_zone_map(
        ReplayTaskRebuildStorage(1, memory.read, write), zone, calls=ReplayTaskRebuildCalls(None)
    )
    assert stores == [(cells + index * 2, 2, 512) for index in range(4)] + [(zone + 0x838, 4, 0)]


def test_terminal_imports_bypass_composed_body_handlers_and_read_iat_once() -> None:
    memory = ReplayMemory()
    static(memory)
    reads = []
    effects = []

    def read(address, width):
        reads.append((address, width))
        return memory.read(address, width)

    def terminal(target, args, data):
        effects.append((target, args, data))
        return 0xCAFE

    current = ReplayTaskRebuildStorage(1, read, memory.write)
    imports = ReplayTaskRebuildCalls(terminal)
    support = bind_replay_zone_map_support(current, ReplayTaskRebuildCalls(None), imports=imports)
    constructor = bind_replay_zone_map_construction(
        current, support, imports=imports, atomics=ReplayUnitAIMapAtomics(None, None)
    )
    base = bind_replay_unit_ai_base(current, constructor, imports=imports)
    factory = bind_replay_unit_ai_construction(
        current, base, imports=imports, bind_local=memory.bind_local
    )
    assert factory.call is not None and constructor.call is not None and base.call is not None
    assert factory.call(0x142D6E3B7, (1, 2, 3), None) == 0xCAFE
    assert constructor.call(0x142D6C270, (4,), None) == 0xCAFE
    assert base.call(0x142D6E3DB, (5, 6, 7), None) == 0xCAFE
    assert reads == [(0x143199938, 8), (0x143199DD0, 8), (0x1431999A0, 8)]
    assert effects == [
        (0x142D6E3B7, (1, 2, 3), None),
        (0x142D6BAB4, (4,), None),
        (0x142D6E3DB, (5, 6, 7), None),
    ]


def test_direct_calloc_import_can_share_body_identity_without_reentering_constructor() -> None:
    memory = ReplayMemory()
    static(memory)
    memory.write(0x143199DC0, 8, 0x1414EA4A0)
    zone, dims = memory.allocate(0x858), memory.allocate(0x38)
    memory.write(dims + 0x30, 4, 0)
    memory.write(dims + 0x34, 4, 0)
    runtime = memory.runtime_calls(calloc_target=0x1414EA4A0)
    support = bind_replay_zone_map_support(context(memory), runtime, imports=runtime)
    bound = bind_replay_zone_map_construction(
        context(memory), support, imports=runtime, atomics=ReplayUnitAIMapAtomics(None, None)
    )
    assert bound.call is not None
    with pytest.raises(UnresolvedReplayTaskRebuild, match="1414ec280"):
        bound.call(0x1414EA4A0, (zone, dims, zone + 0x818), None)
    assert memory.read(zone + 0x808, 8) and memory.read(zone + 0x810, 8)
    assert memory.read(zone + 0x838, 4) == 0


def test_direct_watson_import_bypasses_owned_free_handler_without_reinterpreting_arity() -> None:
    memory = ReplayMemory()
    vector = memory.allocate(24)
    memory.map_bytes(0x1000, bytes(16))
    memory.write(0x1000, 8, 0x10)  # Deliberately invalid large allocation backpointer.
    for offset, value in ((0, 0x1008), (8, 0x1008), (16, 0x2008)):
        memory.write(vector + offset, 8, value)
    memory.map_bytes(0x14319A060, (0x142D6BAB4).to_bytes(8, "little"))
    seen = []

    def ordinary(target, args, data):
        assert target == 0x1414E9FF0

    def imported(target, args, data):
        seen.append((target, args, data))

    calls = bind_replay_zone_map_support(
        context(memory), ReplayTaskRebuildCalls(ordinary), imports=ReplayTaskRebuildCalls(imported)
    )
    assert calls.call is not None
    with pytest.raises(UnresolvedReplayTaskRebuild, match="Watson returned before INT3"):
        calls.call(0x1414EC140, (vector, 0xCAFE, 0, 0), None)
    assert seen == [(0x142D6BAB4, (0, 0, 0, 0, 0), None)]
    assert memory.read(vector, 8) == 0x1008
