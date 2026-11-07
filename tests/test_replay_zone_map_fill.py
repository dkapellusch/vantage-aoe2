"""Actual owned effects and mandatory flood/ownership-release boundaries."""

from __future__ import annotations

import pytest

from vantage.replay_memory import ReplayMemory, ReplayMemoryError
from vantage.replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
)
from vantage.replay_unit_ai_map import ReplayUnitAIMapAtomics
from vantage.replay_zone_map_construction import bind_replay_zone_map_construction
from vantage.replay_zone_map_fill import (
    bind_replay_zone_map_fill,
    flood_replay_zone_map,
    release_replay_zone_mask,
    release_replay_zone_pairs,
)
from vantage.replay_zone_map_support import bind_replay_zone_map_support
from vantage.replay_zone_map_update import bind_replay_zone_map_update
from vantage.replay_zone_queue import bind_replay_zone_queue


def storage(memory):
    return ReplayTaskRebuildStorage(1, memory.read, memory.write)


def grid(memory, width, height):
    zone, dimensions, terrain, rows, cells, mask, scratch = (
        memory.allocate(n)
        for n in (0x858, 0x38, width * height * 64, height * 8, width * height * 2, 4, 40)
    )
    memory.fill(zone, 0, 0x800)
    for address, value in (
        (zone + 0x830, dimensions),
        (dimensions + 8, terrain),
        (zone + 0x810, rows),
        (zone + 0x818, mask),
        (zone + 0x850, scratch),
    ):
        memory.write(address, 8, value)
    memory.write(dimensions + 0x30, 4, width)
    memory.write(dimensions + 0x34, 4, height)
    memory.write(mask, 4, 0x3F800000)
    for y in range(height):
        memory.write(rows + y * 8, 8, cells + y * width * 2)
        for x in range(width):
            memory.write(cells + (y * width + x) * 2, 2, 512)
            memory.write(terrain + (y * width + x) * 64 + 9, 1, 0)
    return zone, dimensions, terrain, cells, mask


def test_first_accepted_neighbor_is_marked_before_unavailable_real_queue_get() -> None:
    memory = ReplayMemory()
    zone, _, _, cells, _ = grid(memory, 2, 2)
    memory.write(cells, 2, 0)
    with pytest.raises(UnresolvedReplayTaskRebuild, match="14096e150"):
        flood_replay_zone_map(storage(memory), zone, 0, 0, 1, 0, calls=memory.runtime_calls())
    assert [memory.read(cells + i * 2, 2) for i in range(4)] == [0, 0, 512, 512]
    assert memory.read(zone, 4) == 0


def test_empty_neighbor_queue_still_requires_finalizer_without_reading_grid() -> None:
    memory = ReplayMemory()
    zone, dimensions = memory.allocate(0x858), memory.allocate(0x38)
    memory.write(zone + 0x830, 8, dimensions)
    memory.write(dimensions + 0x30, 4, 1)
    memory.write(dimensions + 0x34, 4, 1)
    reads = []

    def read(address, width):
        reads.append((address, width))
        return memory.read(address, width)

    with pytest.raises(UnresolvedReplayTaskRebuild, match="1414ed250"):
        flood_replay_zone_map(
            ReplayTaskRebuildStorage(1, read, memory.write),
            zone,
            0,
            0,
            1,
            0xDEAD0002,
            calls=memory.runtime_calls(),
        )
    assert reads == [(zone + 0x830, 8), (dimensions + 0x30, 4), (dimensions + 0x34, 4)]


@pytest.mark.parametrize("flag", [0, 1, 0x100])
def test_nan_mask_is_nonpositive_and_only_effective_flag_byte_is_consumed(flag) -> None:
    memory = ReplayMemory()
    zone, _, _, cells, mask = grid(memory, 2, 1)
    memory.write(cells, 2, 11)
    memory.write(mask, 4, 0x7FC12345)
    accepted = not (flag & 0xFF)
    with pytest.raises(UnresolvedReplayTaskRebuild, match="14096e150" if accepted else "1414ed250"):
        flood_replay_zone_map(storage(memory), zone, 0, 0, flag, 11, calls=memory.runtime_calls())
    assert memory.read(cells + 2, 2) == (11 if accepted else 512)


def test_up_neighbor_holds_mask_pointer_before_current_terrain_byte_read() -> None:
    memory = ReplayMemory()
    zone, _, terrain, cells, old_mask = grid(memory, 3, 3)
    new_mask = memory.allocate(4)
    memory.write(new_mask, 4, 0xBF800000)
    for i in range(9):
        memory.write(cells + i * 2, 2, 7 if i != 1 else 512)

    def read(address, width):
        value = memory.read(address, width)
        if address == terrain + 64 + 9:
            memory.write(zone + 0x818, 8, new_mask)
        return value

    with pytest.raises(UnresolvedReplayTaskRebuild, match="14096e150"):
        flood_replay_zone_map(
            ReplayTaskRebuildStorage(1, read, memory.write),
            zone,
            1,
            1,
            1,
            7,
            calls=memory.runtime_calls(),
        )
    assert memory.read(old_mask, 4) == 0x3F800000
    assert memory.read(zone + 0x818, 8) == new_mask
    assert memory.read(cells + 2, 2) == 7


def test_empty_pair_release_has_no_storage_atomic_or_call_effect() -> None:
    def unavailable(*args):
        raise AssertionError("empty range touched a provider")

    release_replay_zone_pairs(
        ReplayTaskRebuildStorage(1, unavailable, unavailable),
        0xCAFE,
        0xCAFE,
        calls=ReplayTaskRebuildCalls(unavailable),
        atomics=ReplayUnitAIMapAtomics(None, None),
    )


def test_pair_release_holds_control_through_destroy_and_reloads_its_current_vtable() -> None:
    memory = ReplayMemory()
    pairs, control, other, first_table, new_table = (
        memory.allocate(n) for n in (32, 16, 16, 16, 16)
    )
    for address, value in (
        (pairs + 8, control),
        (pairs + 24, other),
        (control, first_table),
        (first_table, 0xD1),
        (first_table + 8, 0xD2),
        (new_table + 8, 0xD3),
    ):
        memory.write(address, 8, value)
    for address, value in ((control + 8, 1), (control + 12, 1), (other + 8, 2), (other + 12, 1)):
        memory.write(address, 4, value)
    calls = []

    def effect(target, args, data):
        calls.append((target, args, data))
        assert args == (control,)
        if target == 0xD1:
            memory.write(pairs + 8, 8, other)
            memory.write(control, 8, new_table)

    release_replay_zone_pairs(
        storage(memory),
        pairs,
        pairs + 32,
        calls=ReplayTaskRebuildCalls(effect),
        atomics=ReplayUnitAIMapAtomics(memory.compare_exchange_u32, memory.fetch_add_u32),
    )
    assert calls == [(0xD1, (control,), None), (0xD3, (control,), None)]
    assert memory.read(control + 8, 4) == memory.read(control + 12, 4) == 0
    assert memory.read(other + 8, 4) == 1 and memory.read(other + 12, 4) == 1
    assert memory.read(pairs + 8, 8) == other


@pytest.mark.parametrize("size", [8, 4096])
def test_mask_release_frees_actual_small_or_aligned_backing_without_vector_access(size) -> None:
    memory = ReplayMemory()
    pointer = memory.allocate_aligned(size)
    release_replay_zone_mask(
        storage(memory), 0xCAFE, pointer, size // 4, calls=memory.runtime_calls()
    )
    assert memory.mapped_bytes == 0


def test_mask_watson_uses_terminal_import_even_when_selected_token_is_owned_body() -> None:
    memory = ReplayMemory()
    memory.map_bytes(0x1000, (0x10).to_bytes(8, "little"))
    memory.map_bytes(0x14319A060, (0x1414ECA00).to_bytes(8, "little"))
    seen = []

    def terminal(target, args, data):
        seen.append((target, args, data))

    bound = bind_replay_zone_map_fill(
        storage(memory),
        ReplayTaskRebuildCalls(None),
        atomics=ReplayUnitAIMapAtomics(None, None),
        imports=ReplayTaskRebuildCalls(terminal),
    )
    assert bound.call is not None
    with pytest.raises(UnresolvedReplayTaskRebuild, match="Watson returned before INT3"):
        bound.call(0x1410565B0, (0xCAFE, 0x1008, 1024), None)
    assert seen == [(0x1414ECA00, (0, 0, 0, 0, 0), None)]


def test_mask_growth_composes_actual_old_buffer_release_new_allocation_and_copy() -> None:
    memory = ReplayMemory()
    vector, old, source = memory.allocate(24), memory.allocate_aligned(8), memory.allocate(12)
    for offset, value in ((0, old), (8, old + 8), (16, old + 8)):
        memory.write(vector + offset, 8, value)
    raw = bytes.fromhex("4523817f0000008001000000")
    memory.write_bytes(source, raw)
    memory.map_bytes(0x143199DD0, (0x142D6BAB4).to_bytes(8, "little"))
    runtime = memory.runtime_calls()
    fill = bind_replay_zone_map_fill(
        storage(memory), runtime, imports=runtime, atomics=ReplayUnitAIMapAtomics(None, None)
    )
    bound = bind_replay_zone_map_support(storage(memory), fill, imports=runtime)
    assert bound.call is not None
    bound.call(0x14104EB10, (vector, source, 3), None)
    begin = memory.read(vector, 8)
    assert memory.read_bytes(begin, 12) == raw
    assert memory.read(vector + 8, 8) == memory.read(vector + 16, 8) == begin + 12
    with pytest.raises(ReplayMemoryError, match="unmapped"):
        memory.read(old, 1)
    assert ReplayMemory.from_snapshot(memory.snapshot()).snapshot() == memory.snapshot()


@pytest.mark.parametrize(("side", "growth"), [(2, None), (3, 2)])
def test_complete_constructor_runs_real_flood_pool_adjacency_and_recursive_cleanup(side, growth):
    memory = ReplayMemory()
    zone, dimensions, terrain, header, mask = (
        memory.allocate(n) for n in (0x858, 0x38, side * side * 64, 16, 4)
    )
    memory.write(dimensions + 0x30, 4, side)
    memory.write(dimensions + 0x34, 4, side)
    memory.write(dimensions + 8, 8, terrain)
    memory.write(header, 8, mask)
    memory.write(header + 8, 8, mask + 4)
    memory.write(mask, 4, 0x3F800000)
    for i in range(side * side):
        memory.write(terrain + i * 64 + 9, 1, 0)
    for address, target in (
        (0x143199DC0, 0xCA110C),
        (0x143199938, 0x142D6E3B7),
        (0x143199DD0, 0x142D6BAB4),
        (0x1431999A0, 0x142D6E3DB),
    ):
        memory.map_bytes(address, target.to_bytes(8, "little"))
    runtime = memory.runtime_calls(calloc_target=0xCA110C)
    allocations, free_sizes = {}, []

    def effect(target, args, data):
        assert runtime.call is not None
        if target == 0x142D6BAB4:
            free_sizes.append(allocations.get(args[0], 0))
        result = runtime.call(target, args, data)
        if target == 0x142D6BA78:
            allocations[result] = args[0]
        return result

    def write(address, width, value):
        memory.write(address, width, value)
        if growth is not None and width == 1 and value == 1:
            # Explicit changed current pool profile after initializer's last store.
            scratch = memory.read(zone + 0x850, 8)
            if address == scratch + 32:
                memory.write(scratch + 12, 4, growth)

    current = ReplayTaskRebuildStorage(1, memory.read, write)
    terminal = ReplayTaskRebuildCalls(effect)
    queue = bind_replay_zone_queue(current, terminal, imports=terminal)
    atomics = ReplayUnitAIMapAtomics(memory.compare_exchange_u32, memory.fetch_add_u32)
    fill = bind_replay_zone_map_fill(current, queue, atomics=atomics, imports=terminal)
    update = bind_replay_zone_map_update(current, fill, imports=terminal)
    support = bind_replay_zone_map_support(current, update, imports=terminal)
    calls = bind_replay_zone_map_construction(current, support, atomics=atomics, imports=terminal)
    assert calls.call is not None
    assert calls.call(0x1414EA4A0, (zone, dimensions, header), None) == zone
    cells = memory.read(zone + 0x808, 8)
    assert memory.read_bytes(cells, side * side * 2) == bytes(side * side * 2)
    assert memory.read(zone, 4) == side * side
    assert memory.read(zone + 0x838, 4) == 1
    assert memory.read(zone + 0x850, 8) == 0
    assert memory.read(memory.read(zone + 0x840, 8), 1) == 1
    bridges = memory.read(zone + 0x848, 8)
    assert memory.read(bridges, 1) == 0
    with pytest.raises(ReplayMemoryError, match="undefined"):
        memory.read(bridges + 1, 1)
    assert free_sizes == (
        [0, 4104, 8208, 16, 40] if growth is None else [0, 16, 32, 32, 32, 16, 16, 40]
    )
    assert ReplayMemory.from_snapshot(memory.snapshot()).snapshot() == memory.snapshot()
