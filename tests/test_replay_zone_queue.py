"""Source-led zone pool and cleanup cases over real owned replay memory."""

from __future__ import annotations

import pytest

from vantage.replay_memory import ReplayMemory, ReplayMemoryError
from vantage.replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
)
from vantage.replay_zone_queue import (
    bind_replay_zone_queue,
    cleanup_replay_zone_chain,
    count_replay_zone_region,
    get_replay_zone_node,
    return_replay_zone_node,
)


def context(memory, *, read=None, write=None):
    return ReplayTaskRebuildStorage(
        1, memory.read if read is None else read, memory.write if write is None else write
    )


def static(memory):
    for address, target in ((0x143199DD0, 0x142D6BAB4), (0x143199938, 0x142D6E3B7)):
        memory.map_bytes(address, target.to_bytes(8, "little"))


def pool(memory, *, stride=16, grow=513, count=0, capacity=0, clear=1, pointers=0, head=0):
    scratch = memory.allocate(40)
    memory.write_bytes(scratch, bytes(40))
    for offset, width, value in (
        (0, 8, head),
        (8, 4, stride),
        (12, 4, grow),
        (16, 4, count),
        (20, 4, capacity),
        (24, 8, pointers),
        (32, 1, clear),
    ):
        memory.write(scratch + offset, width, value)
    return scratch


def invoke(bound, target, *args):
    assert bound.call is not None
    return bound.call(target, args, None)


def test_fresh_pool_real_three_allocations_lifo_clear_and_return() -> None:
    memory = ReplayMemory()
    static(memory)
    scratch = pool(memory)
    runtime = memory.runtime_calls()
    calls = []

    def call(target, args, data):
        calls.append((target, args))
        assert runtime.call is not None
        return runtime.call(target, args, data)

    actual = ReplayTaskRebuildCalls(call)
    bound = bind_replay_zone_queue(context(memory), actual, imports=actual)
    selected = invoke(bound, 0x14096E150, scratch)
    head = memory.read(scratch, 8)
    data = memory.read(head, 8)
    pointers = memory.read(scratch + 24, 8)
    assert selected == data + 8192
    assert memory.read(head + 8, 8) == 0
    assert memory.read(scratch + 16, 4) == 512
    assert memory.read(scratch + 20, 4) == 513
    assert [args for target, args in calls if target == 0x142D6BA78] == [(4104,), (16,), (8208,)]
    assert [memory.read(pointers + index * 8, 8) for index in range(513)] == [
        data + index * 16 for index in range(513)
    ]
    assert memory.read_bytes(selected, 16) == bytes(16)
    with pytest.raises(ReplayMemoryError, match="undefined"):
        memory.read(data, 1)
    memory.write_bytes(selected, b"nonzero payload!")
    assert invoke(bound, 0x14096E260, scratch, selected) is None
    assert memory.read(scratch + 16, 4) == 513
    assert invoke(bound, 0x14096E150, scratch) == selected
    assert memory.read_bytes(selected, 16) == bytes(16)
    assert ReplayMemory.from_snapshot(memory.snapshot()).snapshot() == memory.snapshot()


def test_existing_uncleared_pool_does_not_read_stride_growth_or_node_storage() -> None:
    memory = ReplayMemory()
    scratch, pointers = memory.allocate(40), memory.allocate(8)
    memory.write(scratch + 16, 4, 1)
    memory.write(scratch + 24, 8, pointers)
    memory.write(scratch + 32, 1, 0)
    memory.write(pointers, 8, 0xBAD)
    reads = []

    def read(address, width):
        reads.append((address, width))
        return memory.read(address, width)

    assert (
        get_replay_zone_node(
            context(memory, read=read), scratch, calls=ReplayTaskRebuildCalls(None)
        )
        == 0xBAD
    )
    assert reads == [
        (scratch + 16, 4),
        (scratch + 16, 4),
        (scratch + 32, 1),
        (scratch + 16, 4),
        (scratch + 24, 8),
        (pointers, 8),
    ]


def test_zero_size_clear_still_reads_current_iat_and_calls_real_memset() -> None:
    memory = ReplayMemory()
    static(memory)
    pointers = memory.allocate(8)
    memory.write(pointers, 8, 0)
    scratch = pool(memory, stride=0, count=1, clear=0x80, pointers=pointers)
    seen = []
    runtime = memory.runtime_calls()

    def call(target, args, data):
        seen.append((target, args))
        assert runtime.call is not None
        return runtime.call(target, args, data)

    bound = bind_replay_zone_queue(context(memory), ReplayTaskRebuildCalls(call))
    assert invoke(bound, 0x14096E150, scratch) == 0
    assert seen == [(0x142D6E3B7, (0, 0, 0))]


def test_missing_first_free_retains_capacity_increment_without_allocations() -> None:
    memory = ReplayMemory()
    scratch = pool(memory, grow=3, capacity=4)
    before = memory.mapped_bytes
    with pytest.raises(UnresolvedReplayTaskRebuild, match="142d6c270"):
        get_replay_zone_node(context(memory), scratch, calls=ReplayTaskRebuildCalls(None))
    assert memory.read(scratch + 20, 4) == 7
    assert memory.read(scratch + 16, 4) == memory.read(scratch, 8) == 0
    assert memory.mapped_bytes == before


def test_allocation_failure_keeps_real_old_free_and_new_pointer_header() -> None:
    memory = ReplayMemory()
    static(memory)
    old = memory.allocate(8)
    scratch = pool(memory, grow=2, capacity=1, pointers=old)
    runtime = memory.runtime_calls()
    allocated = []

    def call(target, args, data):
        if target == 0x142D6BA78 and args == (16,):
            raise RuntimeError("node allocation failed")
        assert runtime.call is not None
        result = runtime.call(target, args, data)
        if target == 0x142D6BA78:
            allocated.append(result)
        return result

    bound = bind_replay_zone_queue(context(memory), ReplayTaskRebuildCalls(call))
    with pytest.raises(RuntimeError, match="node allocation failed"):
        invoke(bound, 0x14096E150, scratch)
    assert memory.read(scratch + 20, 4) == 3
    assert memory.read(scratch + 24, 8) == allocated[0]
    assert memory.read(scratch, 8) == memory.read(scratch + 16, 4) == 0
    with pytest.raises(ReplayMemoryError, match="unmapped"):
        memory.read(old, 1)


def test_null_node_control_does_not_become_successful_null_get() -> None:
    memory = ReplayMemory()
    static(memory)
    scratch = pool(memory, grow=1)
    runtime = memory.runtime_calls()
    requests = []

    def call(target, args, data):
        if target == 0x142D6BA78:
            requests.append(args[0])
            if len(requests) == 2:
                return 0  # Explicit negative allocator result, not a successful leaf.
        assert runtime.call is not None
        return runtime.call(target, args, data)

    bound = bind_replay_zone_queue(context(memory), ReplayTaskRebuildCalls(call))
    with pytest.raises(ReplayMemoryError, match="unmapped"):
        invoke(bound, 0x14096E150, scratch)
    assert requests == [8, 16, 16]
    assert memory.read(scratch, 8) == 0
    assert memory.read(scratch + 24, 8) != 0


def test_zero_growth_returns_only_after_real_allocations_and_node_link() -> None:
    memory = ReplayMemory()
    static(memory)
    scratch = pool(memory, grow=0)
    runtime = memory.runtime_calls()
    seen = []

    def call(target, args, data):
        seen.append((target, args))
        assert runtime.call is not None
        return runtime.call(target, args, data)

    bound = bind_replay_zone_queue(context(memory), ReplayTaskRebuildCalls(call))
    assert invoke(bound, 0x14096E150, scratch) == 0
    assert [args for target, args in seen if target == 0x142D6BA78] == [(0,), (16,), (0,)]
    head = memory.read(scratch, 8)
    assert memory.read(head, 8) != 0 and memory.read(head + 8, 8) == 0
    assert memory.read(scratch + 16, 4) == 0
    assert not any(target == 0x142D6E3B7 for target, _ in seen)


def test_growth_zero_is_held_before_publishing_list_head() -> None:
    memory = ReplayMemory()
    static(memory)
    scratch = pool(memory, grow=0)

    def write(address, width, value):
        memory.write(address, width, value)
        if address == scratch:
            memory.write(scratch + 12, 4, 2)

    bound = bind_replay_zone_queue(context(memory, write=write), memory.runtime_calls())
    assert invoke(bound, 0x14096E150, scratch) == 0
    assert memory.read(scratch + 12, 4) == 2 and memory.read(scratch + 16, 4) == 0


def test_growth_rereads_capacity_stride_and_head_after_real_calls() -> None:
    memory = ReplayMemory()
    static(memory)
    old, old_head, new_head = (memory.allocate(n) for n in (8, 16, 16))
    scratch = pool(memory, grow=2, capacity=1, pointers=old, head=old_head, clear=0)
    runtime = memory.runtime_calls()
    sizes = []

    def call(target, args, data):
        assert runtime.call is not None
        result = runtime.call(target, args, data)
        if target == 0x142D6BAB4:
            memory.write(scratch + 20, 4, 4)
            memory.write(scratch + 12, 4, 3)
            memory.write(scratch + 8, 4, 8)
        if target == 0x142D6BA78:
            sizes.append(args[0])
            if len(sizes) == 3:
                memory.write(scratch, 8, new_head)
        return result

    bound = bind_replay_zone_queue(context(memory), ReplayTaskRebuildCalls(call))
    selected = invoke(bound, 0x14096E150, scratch)
    head = memory.read(scratch, 8)
    assert sizes == [32, 16, 24]
    assert selected == memory.read(head, 8) + 16
    assert memory.read(head + 8, 8) == new_head
    assert memory.read(scratch + 16, 4) == 2 and memory.read(scratch + 20, 4) == 4


@pytest.mark.parametrize(
    "grow,stride,expected",
    [
        (0x80000001, 2, 2),
        (0x80000000, 1, 0x80000000),
        (0xFFFFFFFF, 0xFFFFFFFF, 1),
    ],
)
def test_data_product_wraps32_and_zeroextends_before_allocation(grow, stride, expected):
    memory = ReplayMemory()
    static(memory)
    scratch = pool(memory, grow=grow, stride=stride)
    runtime = memory.runtime_calls()
    sizes = []

    def call(target, args, data):
        if target == 0x142D6BA78:
            sizes.append(args[0])
            if len(sizes) == 3:
                assert args == (expected,)
                raise RuntimeError("bounded data allocation observation")
        assert runtime.call is not None
        result = runtime.call(target, args, data)
        if target == 0x142D6BAB4:
            memory.write(scratch + 20, 4, 1)
        return result

    bound = bind_replay_zone_queue(context(memory), ReplayTaskRebuildCalls(call))
    with pytest.raises(RuntimeError, match="bounded data allocation observation"):
        invoke(bound, 0x14096E150, scratch)
    assert sizes == [8, 16, expected]
    assert memory.read(scratch, 8) == 0


def test_pointer_population_uses_current_count_stride_and_final_array() -> None:
    memory = ReplayMemory()
    static(memory)
    alternate = memory.allocate(32)
    memory.write(alternate + 24, 8, 0xCAFE)
    scratch = pool(memory, grow=2, clear=0)
    runtime = memory.runtime_calls()
    allocations = []

    def call(target, args, data):
        assert runtime.call is not None
        result = runtime.call(target, args, data)
        if target == 0x142D6BA78:
            allocations.append(result)
        return result

    def write(address, width, value):
        memory.write(address, width, value)
        if allocations and address == allocations[0]:
            memory.write(scratch + 24, 8, alternate)
            memory.write(scratch + 16, 4, 3)
            memory.write(scratch + 8, 4, 32)
            memory.write(scratch + 12, 4, 1)

    bound = bind_replay_zone_queue(context(memory, write=write), ReplayTaskRebuildCalls(call))
    assert invoke(bound, 0x14096E150, scratch) == 0xCAFE
    assert memory.read(allocations[0], 8) == allocations[2]
    assert memory.read(scratch + 16, 4) == 3


def test_clear_flag_is_held_before_current_selection_headers() -> None:
    memory = ReplayMemory()
    old, changed = memory.allocate(16), memory.allocate(8)
    memory.write(changed, 8, 0xBEEF)
    scratch = pool(memory, count=2, clear=0, pointers=old)

    def read(address, width):
        value = memory.read(address, width)
        if address == scratch + 32:
            memory.write(scratch + 32, 1, 1)
            memory.write(scratch + 16, 4, 0)
            memory.write(scratch + 24, 8, changed)
        return value

    assert (
        get_replay_zone_node(
            context(memory, read=read), scratch, calls=ReplayTaskRebuildCalls(None)
        )
        == 0xBEEF
    )
    assert memory.read(scratch + 16, 4) == 0


def test_missing_clear_import_keeps_pop_without_clearing_selected_bytes() -> None:
    memory = ReplayMemory()
    pointers, selected = memory.allocate(8), memory.allocate(16)
    memory.write(pointers, 8, selected)
    memory.write_bytes(selected, b"x" * 16)
    scratch = pool(memory, count=1, pointers=pointers)
    bound = bind_replay_zone_queue(context(memory), memory.runtime_calls())
    with pytest.raises(ReplayMemoryError, match="unmapped"):
        invoke(bound, 0x14096E150, scratch)
    assert memory.read(scratch + 16, 4) == 0
    assert memory.read_bytes(selected, 16) == b"x" * 16


def test_clear_returns_held_selection_after_real_memset_and_current_header_mutation() -> None:
    memory = ReplayMemory()
    static(memory)
    pointers, selected = memory.allocate(8), memory.allocate(16)
    memory.write(pointers, 8, selected)
    memory.write_bytes(selected, b"x" * 16)
    scratch = pool(memory, count=1, pointers=pointers)
    runtime = memory.runtime_calls()

    def call(target, args, data):
        assert target == 0x142D6E3B7 and args == (selected, 0, 16)
        assert runtime.call is not None
        runtime.call(target, args, data)
        memory.write(scratch + 24, 8, 0xBAD)
        return 0xBEEF  # Caller ignores the imported function's scalar result.

    bound = bind_replay_zone_queue(context(memory), ReplayTaskRebuildCalls(call))
    assert invoke(bound, 0x14096E150, scratch) == selected
    assert memory.read_bytes(selected, 16) == bytes(16)
    assert memory.read(scratch + 24, 8) == 0xBAD


def test_return_node_uses_raw_pointer_and_current_increment_after_store_hook() -> None:
    memory = ReplayMemory()
    pointers = memory.allocate(8)
    scratch = pool(memory, pointers=pointers)

    def write(address, width, value):
        memory.write(address, width, value)
        if address == pointers:
            memory.write(scratch + 16, 4, 41)

    return_replay_zone_node(context(memory, write=write), scratch, 0xBAD)
    assert memory.read(pointers, 8) == 0xBAD
    assert memory.read(scratch + 16, 4) == 42


def test_return_node_index_zeroextends_and_count_wraps_without_node_access() -> None:
    memory = ReplayMemory()
    pointers = 0x4000
    slot = pointers + 0xFFFFFFFF * 8
    memory.map_bytes(slot, b"\xff" * 8)
    scratch = pool(memory, count=0xFFFFFFFF, pointers=pointers)
    return_replay_zone_node(context(memory), scratch, 0xDEADBEEF)
    assert memory.read(slot, 8) == 0xDEADBEEF
    assert memory.read(scratch + 16, 4) == 0


def test_nonzero_negative_get_count_skips_growth_and_zeroextends_index() -> None:
    memory = ReplayMemory()
    pointers = 0x8000
    memory.map_bytes(pointers + 0xFFFFFFFE * 8, (0xCAFE).to_bytes(8, "little"))
    scratch = pool(memory, count=0xFFFFFFFF, pointers=pointers, clear=0)
    assert (
        get_replay_zone_node(context(memory), scratch, calls=ReplayTaskRebuildCalls(None)) == 0xCAFE
    )
    assert memory.read(scratch + 16, 4) == 0xFFFFFFFE


@pytest.mark.parametrize("writable", [False, True])
def test_return_failure_does_not_increment_or_grow(writable) -> None:
    memory = ReplayMemory()
    pointers = 0x6000
    if not writable:
        memory.map_bytes(pointers, bytes(8), writable=False)
    scratch = pool(memory, pointers=pointers)
    before = memory.snapshot()
    with pytest.raises(ReplayMemoryError, match=r"readonly|unmapped"):
        return_replay_zone_node(context(memory), scratch, 0xAA)
    assert memory.snapshot() == before


def grid(memory, values, *, region=1, cached=0):
    address, dimensions, rows = (memory.allocate(n) for n in (0x838, 0x38, len(values) * 8))
    width = len(values[0])
    memory.write(address + region * 4, 4, cached)
    memory.write(address + 0x830, 8, dimensions)
    memory.write(address + 0x810, 8, rows)
    memory.write(dimensions + 0x30, 4, width)
    memory.write(dimensions + 0x34, 4, len(values))
    payload = []
    for index, row in enumerate(values):
        pointer = memory.allocate(width * 2)
        memory.write_bytes(pointer, b"".join(value.to_bytes(2, "little") for value in row))
        memory.write(rows + index * 8, 8, pointer)
        payload.append(pointer)
    return address, dimensions, rows, payload


def test_region_positive_cache_needs_only_its_word_and_uses_low_dx() -> None:
    memory = ReplayMemory()
    address = memory.allocate(4)
    memory.write(address, 4, 0x7FFFFFFF)
    seen = []

    def read(pointer, width):
        seen.append((pointer, width))
        return memory.read(pointer, width)

    assert count_replay_zone_region(context(memory, read=read), address, 0xABCDE0000) == 0x7FFFFFFF
    assert seen == [(address, 4)]


def test_region_scan_is_column_outer_row_inner_and_then_positive_cache_skips() -> None:
    memory = ReplayMemory()
    address, dimensions, _, payload = grid(memory, [[1, 2], [2, 1], [1, 1]])
    cells = []
    field_reads = []

    def read(pointer, width):
        if width == 2:
            cells.append(pointer)
        if pointer == address + 0x810:
            field_reads.append(pointer)
        return memory.read(pointer, width)

    assert count_replay_zone_region(context(memory, read=read), address, 0x10001) == 4
    assert cells == [*payload, *(pointer + 2 for pointer in payload)]
    assert len(field_reads) == 6
    assert memory.read(address + 4, 4) == 4
    memory.free(dimensions)
    assert count_replay_zone_region(context(memory), address, 1) == 4


@pytest.mark.parametrize("cached", [0, 0xFFFFFFFF, 0x80000000])
@pytest.mark.parametrize("width,height", [(0, 3), (0xFFFFFFFF, 2), (2, 0), (2, 0xFFFFFFFF)])
def test_nonpositive_cache_or_dimensions_recompute_zero_without_row_reads(cached, width, height):
    memory = ReplayMemory()
    address, dimensions = memory.allocate(0x838), memory.allocate(0x38)
    memory.write(address, 4, cached)
    memory.write(address + 0x830, 8, dimensions)
    memory.write(dimensions + 0x30, 4, width)
    memory.write(dimensions + 0x34, 4, height)
    assert count_replay_zone_region(context(memory), address, 0) == 0
    assert memory.read(address, 4) == 0


def test_width_zero_does_not_skip_required_height_read() -> None:
    memory = ReplayMemory()
    address, dimensions = memory.allocate(0x838), memory.allocate(0x38)
    memory.write(address, 4, 0xFFFFFFFF)
    memory.write(address + 0x830, 8, dimensions)
    memory.write(dimensions + 0x30, 4, 0)
    with pytest.raises(ReplayMemoryError, match="undefined"):
        count_replay_zone_region(context(memory), address, 0)
    assert memory.read(address, 4) == 0xFFFFFFFF


def test_region_holds_dimensions_and_cache_address_but_rereads_rows() -> None:
    memory = ReplayMemory()
    address, dimensions, _, original = grid(memory, [[1, 0], [0, 0]])
    _, _, alternate_rows, _ = grid(memory, [[0, 0], [1, 1]])
    changed = False

    def read(pointer, width):
        nonlocal changed
        value = memory.read(pointer, width)
        if pointer == original[0] and width == 2 and not changed:
            changed = True
            memory.write(address + 0x810, 8, alternate_rows)
            memory.write(dimensions + 0x30, 4, 1)
            memory.write(dimensions + 0x34, 4, 1)
            memory.write(address + 4, 4, 999)
        return value

    assert count_replay_zone_region(context(memory, read=read), address, 1) == 3
    assert memory.read(address + 4, 4) == 3


def test_region_grid_failure_leaves_old_cache_without_partial_commit() -> None:
    memory = ReplayMemory()
    address, _, _, payload = grid(memory, [[1, 1], [1, 1]], cached=0xFFFFFFFF)
    before = memory.snapshot()

    def read(pointer, width):
        if pointer == payload[0] + 2 and width == 2:
            raise RuntimeError("third cell unavailable")
        return memory.read(pointer, width)

    with pytest.raises(RuntimeError, match="third cell unavailable"):
        count_replay_zone_region(context(memory, read=read), address, 1)
    assert memory.snapshot() == before


def chain(memory, count=3):
    nodes = [memory.allocate(16) for _ in range(count)]
    data = [memory.allocate(4) for _ in range(count)]
    for index, (node, pointer) in enumerate(zip(nodes, data, strict=True)):
        memory.write(node, 8, pointer)
        memory.write(node + 8, 8, nodes[index + 1] if index + 1 < count else 0)
    return nodes, data


@pytest.mark.parametrize("flags", [0, 1, 2, 3, 0xFFFFFFFF00000000, 0xFFFFFFFF00000001])
def test_recursive_cleanup_real_data_forward_nodes_reverse_and_held_return(flags):
    memory = ReplayMemory()
    static(memory)
    nodes, payload = chain(memory)
    frees = []
    runtime = memory.runtime_calls()

    def call(target, args, data):
        if target == 0x142D6BAB4:
            frees.append(args)
        assert runtime.call is not None
        return runtime.call(target, args, data)

    bound = bind_replay_zone_queue(context(memory), ReplayTaskRebuildCalls(call))
    assert invoke(bound, 0x14096E100, nodes[0], flags) == nodes[0]
    expected = [(pointer,) for pointer in payload] + [(nodes[2], 16), (nodes[1], 16)]
    if flags & 1:
        expected.append((nodes[0], 16))
    assert frees == expected
    for pointer in [*payload, *nodes[1:], *([nodes[0]] if flags & 1 else [])]:
        with pytest.raises(ReplayMemoryError, match="unmapped"):
            memory.read(pointer, 1)
    if not flags & 1:
        assert memory.read(nodes[0], 8) == payload[0]
        assert memory.read(nodes[0] + 8, 8) == nodes[1]


def test_cleanup_reads_next_after_real_data_free_and_does_not_reread_after_child() -> None:
    memory = ReplayMemory()
    static(memory)
    nodes, payload = chain(memory, 2)
    # The next word is supplied by the first free effect, not a prefetched link.
    first = memory.allocate(16)
    memory.write(first, 8, payload[0])
    runtime = memory.runtime_calls()

    def call(target, args, data):
        assert runtime.call is not None
        result = runtime.call(target, args, data)
        if target == 0x142D6BAB4 and args == (payload[0],):
            memory.write(first + 8, 8, nodes[1])
        elif target == 0x142D6BAB4 and args == (payload[1],):
            memory.write(first + 8, 8, 0xBAD)
        return result

    bound = bind_replay_zone_queue(context(memory), ReplayTaskRebuildCalls(call))
    assert invoke(bound, 0x14096E100, first, 0) == first
    assert memory.read(first + 8, 8) == 0xBAD
    with pytest.raises(ReplayMemoryError, match="unmapped"):
        memory.read(nodes[1], 1)


def test_missing_recursive_child_keeps_prior_data_free_without_outer_delete() -> None:
    memory = ReplayMemory()
    nodes, payload = chain(memory, 2)
    runtime = memory.runtime_calls()
    calls = []

    def call(target, args, data):
        calls.append((target, args))
        if target == 0x142D6C270:
            memory.free(args[0])
            return None
        assert runtime.call is not None
        return runtime.call(target, args, data)

    with pytest.raises(UnresolvedReplayTaskRebuild, match="14096e100"):
        cleanup_replay_zone_chain(context(memory), nodes[0], 1, calls=ReplayTaskRebuildCalls(call))
    assert calls == [(0x142D6C270, (payload[0],)), (0x14096E100, (nodes[1], 1))]
    assert memory.read(nodes[0] + 8, 8) == nodes[1]
    assert memory.read(nodes[1], 8) == payload[1]


def test_recursive_data_failure_never_runs_blanket_node_cleanup() -> None:
    memory = ReplayMemory()
    static(memory)
    nodes, payload = chain(memory)
    runtime = memory.runtime_calls()

    def call(target, args, data):
        if args == (payload[1],):
            raise RuntimeError("second data free failed")
        assert runtime.call is not None
        return runtime.call(target, args, data)

    bound = bind_replay_zone_queue(context(memory), ReplayTaskRebuildCalls(call))
    with pytest.raises(RuntimeError, match="second data free failed"):
        invoke(bound, 0x14096E100, nodes[0], 1)
    for node in nodes:
        memory.read(node, 16)
    with pytest.raises(ReplayMemoryError, match="unmapped"):
        memory.read(payload[0], 1)
    memory.free(payload[1])  # Still owned; the failed effect did not free it.


def test_cleanup_has_no_invented_success_or_cycle_guard() -> None:
    memory = ReplayMemory()
    static(memory)
    node = memory.allocate(16)
    memory.write(node, 8, 0)
    memory.write(node + 8, 8, node)
    bound = bind_replay_zone_queue(context(memory), memory.runtime_calls())
    with pytest.raises(RecursionError):
        invoke(bound, 0x14096E100, node, 1)
    assert memory.read(node + 8, 8) == node


def test_current_imports_are_terminal_and_unknown_normal_entries_delegate_below() -> None:
    memory = ReplayMemory()
    static(memory)
    node = memory.allocate(16)
    memory.write(node, 8, 0)
    memory.write(node + 8, 8, 0)
    memory.write(0x143199DD0, 8, 0xAA)
    imported, ordinary = [], []
    runtime = memory.runtime_calls()

    def terminal(target, args, data):
        imported.append((target, args, data))
        assert target in (0xAA, 0xBB)
        memory.write(0x143199DD0, 8, 0xBB)
        assert runtime.call is not None
        return runtime.call(0x142D6BAB4, args, data)

    def lower(target, args, data):
        ordinary.append((target, args, data))
        if target == 0x142D6BA78:
            assert runtime.call is not None
            return runtime.call(target, args, data)
        assert target == 0x123 and data is not None
        return 77

    bound = bind_replay_zone_queue(
        context(memory), ReplayTaskRebuildCalls(lower), imports=ReplayTaskRebuildCalls(terminal)
    )
    assert invoke(bound, 0x14096E100, node, 1) == node
    assert [(target, args) for target, args, _ in imported] == [(0xAA, (0,)), (0xBB, (node, 16))]
    allocated = invoke(bound, 0x142D6C268, 7)
    assert ordinary == [(0x142D6BA78, (7,), None)]
    assert allocated is not None
    assert bound.call is not None
    view = memoryview(b"x")
    assert bound.call(0x123, (9,), view) == 77
    assert ordinary[-1] == (0x123, (9,), view)


@pytest.mark.parametrize(
    "target,arity",
    [
        (0x14096E150, 1),
        (0x14096E260, 2),
        (0x1414ED250, 2),
        (0x14096E100, 2),
        (0x142D6C268, 1),
        (0x142D6C270, 1),
        (0x142D6BAB4, 2),
        (0x142D6E3B7, 3),
    ],
)
def test_binder_rejects_malformed_calls_before_memory_effects(target, arity):
    memory = ReplayMemory()
    bound = bind_replay_zone_queue(context(memory), ReplayTaskRebuildCalls(None))
    assert bound.call is not None
    before = memory.snapshot()
    for args, data in (
        ((), None),
        ((0,) * arity, memoryview(b"x")),
        ((True, *(0 for _ in range(arity - 1))), None),
    ):
        with pytest.raises(ValueError):
            bound.call(target, args, data)
    assert memory.snapshot() == before


def test_unavailable_normal_and_terminal_calls_stay_unresolved() -> None:
    memory = ReplayMemory()
    static(memory)
    bound = bind_replay_zone_queue(
        context(memory), ReplayTaskRebuildCalls(None), imports=ReplayTaskRebuildCalls(None)
    )
    with pytest.raises(UnresolvedReplayTaskRebuild, match="142d6ba78"):
        invoke(bound, 0x142D6C268, 8)
    with pytest.raises(UnresolvedReplayTaskRebuild, match="142d6bab4"):
        invoke(bound, 0x142D6C270, 0)
    with pytest.raises(UnresolvedReplayTaskRebuild, match="dead"):
        invoke(bound, 0xDEAD, 0)
