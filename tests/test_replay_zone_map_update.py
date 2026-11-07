"""Owned zone adjacency/bridge effects, exact write extents and caller prefixes."""

from __future__ import annotations

import pytest

from vantage.replay_memory import ReplayMemory, ReplayMemoryError
from vantage.replay_task_rebuild import ReplayTaskRebuildCalls, ReplayTaskRebuildStorage
from vantage.replay_zone_map_update import (
    bind_replay_zone_map_update,
    update_replay_zone_map,
)


def storage(memory):
    return ReplayTaskRebuildStorage(1, memory.read, memory.write)


def planes(memory, width, height, count, values):
    zone, dimensions, rows, cells = (
        memory.allocate(n) for n in (0x850, 0x38, height * 8, width * height * 2)
    )
    memory.write(zone + 0x830, 8, dimensions)
    memory.write(zone + 0x810, 8, rows)
    memory.write(zone + 0x838, 4, count)
    memory.write(dimensions + 0x30, 4, width)
    memory.write(dimensions + 0x34, 4, height)
    for y in range(height):
        memory.write(rows + y * 8, 8, cells + y * width * 2)
    for i, value in enumerate(values):
        memory.write(cells + i * 2, 2, value)
    memory.map_bytes(0x143199938, (0x142D6E3B7).to_bytes(8, "little"))
    return zone


def execute(memory, zone):
    runtime = memory.runtime_calls()
    calls = bind_replay_zone_map_update(storage(memory), runtime, imports=runtime)
    assert calls.call is not None
    calls.call(0x1414EC280, (zone,), None)


def test_actual_all_one_zone_grid_keeps_unwritten_half_of_bridge_plane_undefined() -> None:
    memory = ReplayMemory()
    zone = planes(memory, 2, 2, 1, [0] * 4)
    execute(memory, zone)
    adjacency, bridges = (memory.read(zone + offset, 8) for offset in (0x840, 0x848))
    assert memory.read(adjacency, 1) == 1
    assert memory.read(bridges, 1) == 0
    with pytest.raises(ReplayMemoryError, match="undefined"):
        memory.read(bridges, 2)
    assert ReplayMemory.from_snapshot(memory.snapshot()).snapshot() == memory.snapshot()


def test_actual_concentric_regions_produce_only_real_adjacencies_and_first_shared_bridge() -> None:
    memory = ReplayMemory()
    values = [
        0 if x in (0, 4) or y in (0, 4) else 2 if (x, y) == (2, 2) else 1
        for y in range(5)
        for x in range(5)
    ]
    zone = planes(memory, 5, 5, 3, values)
    execute(memory, zone)
    adjacency, bridges = (memory.read(zone + offset, 8) for offset in (0x840, 0x848))
    assert memory.read_bytes(adjacency, 9) == bytes((1, 1, 0, 1, 1, 1, 0, 1, 1))
    assert memory.read(bridges + 2 * 2, 2) == 1
    assert memory.read(bridges + 6 * 2, 2) == 1
    with pytest.raises(ReplayMemoryError, match="undefined"):
        memory.read(bridges + 16, 2)


def test_non_square_neighbor_prechecks_use_width_then_getter_height_bounds() -> None:
    memory = ReplayMemory()
    zone = planes(memory, 3, 1, 2, [1] * 3)
    execute(memory, zone)
    # The y=1 precheck passes width3; actual getter height1 returns region0.
    assert memory.read_bytes(memory.read(zone + 0x840, 8), 4) == bytes((0, 0, 1, 1))


def test_null_first_allocation_still_reaches_second_and_publishes_both_headers() -> None:
    memory = ReplayMemory()
    zone = memory.allocate(0x850)
    memory.write(zone + 0x838, 4, 3)
    calls, reads = [], []

    def effect(target, args, data):
        assert target == 0x142D6C268 and data is None
        calls.append(args)
        return 0  # Explicit caller-only null-allocation program, not native heap behavior.

    def read(address, width):
        reads.append((address, width))
        return memory.read(address, width)

    update_replay_zone_map(
        ReplayTaskRebuildStorage(1, read, memory.write), zone, calls=ReplayTaskRebuildCalls(effect)
    )
    assert calls == [(9,), (18,)]
    assert reads == [(zone + 0x838, 4), (zone + 0x840, 8)]
    assert memory.read(zone + 0x840, 8) == memory.read(zone + 0x848, 8) == 0


def test_current_first_plane_is_held_before_second_header_publication() -> None:
    memory = ReplayMemory()
    zone = planes(memory, 0, 0, 4, [])
    before, after = memory.allocate(16), memory.allocate(16)
    memory.fill(before, 0xAA, 16)
    memory.fill(after, 0xBB, 16)
    allocations = []
    runtime = memory.runtime_calls()

    def effect(target, args, data):
        assert runtime.call is not None
        result = runtime.call(target, args, data)
        if target == 0x142D6BA78:
            allocations.append(result)
            if len(allocations) == 2:
                memory.write(zone + 0x840, 8, before)
        return result

    def write(address, width, value):
        memory.write(address, width, value)
        if address == zone + 0x848:
            memory.write(zone + 0x840, 8, after)

    current = ReplayTaskRebuildStorage(1, memory.read, write)
    effects = ReplayTaskRebuildCalls(effect)
    bound = bind_replay_zone_map_update(current, effects, imports=effects)
    assert bound.call is not None
    bound.call(0x1414EC280, (zone,), None)
    assert memory.read_bytes(before, 16) == bytes(16)
    assert memory.read_bytes(after, 16) == bytes([0xBB]) * 16
    with pytest.raises(ReplayMemoryError, match="undefined"):
        memory.read(allocations[0], 1)
    assert memory.read_bytes(allocations[1], 16) == bytes(16)
    with pytest.raises(ReplayMemoryError, match="undefined"):
        memory.read(allocations[1] + 16, 1)


def test_signed_square_reaches_actual_resource_refusal_before_either_header_store() -> None:
    memory = ReplayMemory(max_bytes=4096)
    zone = memory.allocate(0x850)
    memory.write(zone + 0x838, 4, 46341)
    memory.write(zone + 0x840, 8, 0xCAFE)
    memory.write(zone + 0x848, 8, 0xBEEF)
    seen = []
    runtime = memory.runtime_calls()

    def effect(target, args, data):
        seen.append((target, args))
        assert runtime.call is not None
        return runtime.call(target, args, data)

    bound = bind_replay_zone_map_update(storage(memory), ReplayTaskRebuildCalls(effect))
    assert bound.call is not None
    with pytest.raises(MemoryError):
        bound.call(0x1414EC280, (zone,), None)
    assert seen == [(0x142D6BA78, (0xFFFFFFFF80001219,))]
    assert memory.read(zone + 0x840, 8) == 0xCAFE and memory.read(zone + 0x848, 8) == 0xBEEF


def test_actual_memset_terminal_can_share_owned_update_identity_without_reentry() -> None:
    memory = ReplayMemory()
    zone = planes(memory, 0, 0, 1, [])
    memory.write(0x143199938, 8, 0x1414EC280)
    seen = []

    def imported(target, args, data):
        seen.append((target, args))
        assert target == 0x1414EC280 and data is None
        return memory.fill(*args)

    bound = bind_replay_zone_map_update(
        storage(memory), memory.runtime_calls(), imports=ReplayTaskRebuildCalls(imported)
    )
    assert bound.call is not None
    bound.call(0x1414EC280, (zone,), None)
    assert [args[1:] for _, args in seen] == [(0, 1), (0x200, 1)]
