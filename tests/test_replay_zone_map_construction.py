"""Zone constructor and growth callers with real memory and explicit child programs."""

from __future__ import annotations

import pytest

from vantage.replay_memory import ReplayMemory, ReplayMemoryError
from vantage.replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
)
from vantage.replay_unit_ai_map import ReplayUnitAIMapAtomics
from vantage.replay_zone_map_construction import (
    bind_replay_zone_map_construction,
    construct_replay_zone_map,
    grow_replay_zone_pairs,
)


def context(memory):
    return ReplayTaskRebuildStorage(1, memory.read, memory.write)


def atomic(memory):
    return ReplayUnitAIMapAtomics(memory.compare_exchange_u32, memory.fetch_add_u32)


def imports(memory):
    for address, target in (
        (0x143199DC0, 0xCA110C),
        (0x143199938, 0x142D6E3B7),
        (0x143199DD0, 0x142D6BAB4),
    ):
        memory.map_bytes(address, target.to_bytes(8, "little"))


def inputs(memory, width=3, height=2):
    zone, dimensions, source = (memory.allocate(n) for n in (0x858, 0x38, 16))
    memory.write(dimensions + 0x30, 4, width)
    memory.write(dimensions + 0x34, 4, height)
    memory.write_bytes(source, bytes(16))
    return zone, dimensions, source


def test_real_calloc_rows_and_memset_prefix_stop_at_mandatory_vector_assignment() -> None:
    memory = ReplayMemory()
    zone, dimensions, source = inputs(memory)
    imports(memory)
    runtime = memory.runtime_calls(calloc_target=0xCA110C)
    seen = []

    def call(target, args, data):
        seen.append((target, args))
        assert runtime.call is not None
        return runtime.call(target, args, data)

    bound = bind_replay_zone_map_construction(
        context(memory), ReplayTaskRebuildCalls(call), atomics=atomic(memory)
    )
    assert bound.call is not None
    with pytest.raises(UnresolvedReplayTaskRebuild, match="14104eb10"):
        bound.call(0x1414EA4A0, (zone, dimensions, source), None)
    data = memory.read(zone + 0x808, 8)
    rows = memory.read(zone + 0x810, 8)
    assert memory.read_bytes(data, 12) == bytes(12)
    assert [memory.read(rows + index * 8, 8) for index in range(2)] == [data, data + 6]
    assert memory.read_bytes(zone, 0x800) == bytes(0x800)
    assert [args for target, args in seen if target == 0xCA110C] == [(6, 2), (2, 8)]
    assert [args for target, args in seen if target == 0x142D6E3B7] == [
        (data, 0x200, 6),
        (zone, 0, 0x800),
    ]
    assert seen[-1] == (0x14104EB10, (zone + 0x818, 0, 0))
    for offset in (0x800, 0x838, 0x848):
        with pytest.raises(ReplayMemoryError, match="undefined"):
            memory.read(zone + offset, 8)
    assert memory.read(zone + 0x850, 8) == 0
    assert ReplayMemory.from_snapshot(memory.snapshot()).snapshot() == memory.snapshot()


def test_alias_source_skips_assignment_but_real_scratch_initialization_precedes_child() -> None:
    memory = ReplayMemory()
    zone, dimensions, _ = inputs(memory, 0, 0)
    imports(memory)
    bound = bind_replay_zone_map_construction(
        context(memory), memory.runtime_calls(calloc_target=0xCA110C), atomics=atomic(memory)
    )
    assert bound.call is not None
    with pytest.raises(UnresolvedReplayTaskRebuild, match="14096e250"):
        bound.call(0x1414EA4A0, (zone, dimensions, zone + 0x818), None)
    scratch = memory.read(zone + 0x850, 8)
    assert memory.read_bytes(scratch, 40) == bytes(40)
    assert memory.read(zone + 0x818, 24) == 0


def test_area_overflow_then_current_area_and_import_are_separate() -> None:
    memory = ReplayMemory()
    zone, dimensions, source = inputs(memory, 0x7FFFFFFF, 2)
    replacement = memory.allocate(0x38)
    memory.write(replacement + 0x30, 4, 2)
    memory.write(replacement + 0x34, 4, 3)
    memory.map_bytes(0x143199DC0, (0xAA).to_bytes(8, "little"))
    seen = []

    def call(target, args, data):
        seen.append((target, args))
        if target == 0xAA:
            assert args == ((1 << 64) - 1, 2)
            memory.write(zone + 0x830, 8, replacement)
            memory.write(0x143199DC0, 8, 0xBB)
            return 0x1234
        if target == 0x142D6E3B7:
            assert args == (0x1234, 0x200, 6)
            return 0
        assert target == 0xBB and args == (3, 8)
        raise RuntimeError("second allocation failed")

    with pytest.raises(RuntimeError, match="second allocation failed"):
        construct_replay_zone_map(
            context(memory), zone, dimensions, source, calls=ReplayTaskRebuildCalls(call)
        )
    assert len(seen) == 3 and memory.read(zone + 0x808, 8) == 0x1234
    assert memory.read(zone + 0x830, 8) == replacement
    with pytest.raises(ReplayMemoryError, match="undefined"):
        memory.read(zone + 0x810, 8)


def test_cleanup_reads_current_scratch_and_frees_held_nested_identity_after_callbacks() -> None:
    memory = ReplayMemory()
    zone, dimensions, source = inputs(memory, 0, 0)
    imports(memory)
    runtime = memory.runtime_calls(calloc_target=0xCA110C)
    freed = []
    held = []

    def call(target, args, data):
        if target == 0x14104EB10:
            return None  # Explicit opaque child input for this caller-only control.
        if target == 0x14096E250:
            assert memory.read_bytes(args[0], 40) == bytes(40)
            return 1
        if target == 0x1414EC840:
            return None
        if target == 0x1414EC280:
            old = memory.read(zone + 0x850, 8)
            memory.free(old)
            scratch, nested, buffer, linked = (memory.allocate(n) for n in (40, 16, 4, 4))
            memory.write(scratch, 8, nested)
            memory.write(scratch + 24, 8, 0)
            memory.write(nested, 8, buffer)
            memory.write(nested + 8, 8, linked)
            memory.write(zone + 0x850, 8, scratch)
            held.extend((scratch, nested, buffer, linked))
            return None
        if target == 0x14096E100:
            assert args == (held[3], 1)
            memory.free(args[0])
            memory.write(zone + 0x850, 8, 0xBAD)
            return None
        if target == 0x142D6BAB4:
            freed.append(args)
        assert runtime.call is not None
        return runtime.call(target, args, data)

    bound = bind_replay_zone_map_construction(
        context(memory), ReplayTaskRebuildCalls(call), atomics=atomic(memory)
    )
    assert bound.call is not None
    assert bound.call(0x1414EA4A0, (zone, dimensions, source), None) == zone
    assert memory.read(zone + 0x850, 8) == 0
    assert freed == [(0,), (held[2],), (held[1], 16), (held[0], 40)]
    for pointer in held:
        with pytest.raises(ReplayMemoryError, match="unmapped"):
            memory.read(pointer, 1)


def test_growth_initializes_new_pair_then_refuses_real_unknown_tail_even_when_empty() -> None:
    memory = ReplayMemory()
    vector, old, source, control = (memory.allocate(n) for n in (24, 16, 16, 16))
    for offset, value in ((0, old), (8, old + 16), (16, old + 16)):
        memory.write(vector + offset, 8, value)
    memory.write(source, 8, 0xCAFE)
    memory.write(source + 8, 8, control)
    memory.write(control + 8, 4, 3)
    allocated = []
    runtime = memory.runtime_calls()

    def call(target, args, data):
        assert runtime.call is not None
        if target == 0x1414EA3E0:
            assert args == (old, old + 16, allocated[0], vector)
        result = runtime.call(target, args, data)
        if target == 0x1402A94D0:
            allocated.append(result)
        return result

    with pytest.raises(UnresolvedReplayTaskRebuild, match="1414ea3e0"):
        grow_replay_zone_pairs(
            context(memory),
            vector,
            old + 16,
            source,
            calls=ReplayTaskRebuildCalls(call),
            atomics=atomic(memory),
        )
    assert memory.read(allocated[0] + 16, 8) == 0xCAFE
    assert memory.read(allocated[0] + 24, 8) == control
    assert memory.read(control + 8, 4) == 4
    assert memory.read(vector, 8) == old


def test_growth_source_rereads_prefix_tail_and_held_return_after_commit() -> None:
    memory = ReplayMemory()
    vector, old, source, control, replacement = (memory.allocate(n) for n in (24, 48, 16, 16, 16))
    for offset, value in ((0, old), (8, old + 32), (16, old + 32)):
        memory.write(vector + offset, 8, value)
    memory.write(source, 8, 0xAA)
    memory.write(source + 8, 8, control)
    memory.write(control + 8, 4, 1)
    effects = []
    allocation = []

    def add(address, value):
        result = memory.fetch_add_u32(address, value)
        memory.write(source, 8, 0xBB)
        memory.write(source + 8, 8, replacement)
        return result

    def call(target, args, data):
        effects.append((target, args))
        if target == 0x1402A94D0:
            allocation.append(memory.allocate_aligned(args[0]))
            return allocation[0]
        if target == 0x1414EA3E0:
            memory.write(vector + 8, 8, old + 48)
        else:
            assert target == 0x1414EC140
            memory.write(vector, 8, 0xBAD)
        return 0

    result = grow_replay_zone_pairs(
        context(memory),
        vector,
        old + 17,
        source,
        calls=ReplayTaskRebuildCalls(call),
        atomics=ReplayUnitAIMapAtomics(None, add),
    )
    assert result == allocation[0] + 16  # Native rounds held displacement down.
    assert memory.read(result, 8) == 0xBB and memory.read(result + 8, 8) == replacement
    assert effects == [
        (0x1402A94D0, (48,)),
        (0x1414EA3E0, (old, old + 17, allocation[0], vector)),
        (0x1414EA3E0, (old + 17, old + 48, result + 16, vector)),
        (0x1414EC140, (vector, allocation[0], 3, 3)),
    ]
