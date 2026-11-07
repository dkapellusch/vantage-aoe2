"""Saved apply callers over owned bytes, real frees and explicit child effects."""

from __future__ import annotations

import pytest

from vantage.replay_memory import ReplayMemory, ReplayMemoryError
from vantage.replay_saved_apply import (
    assign_replay_saved_result_vector,
    bind_replay_saved_apply,
    clear_replay_saved_ai_list,
    forward_replay_saved_result,
)
from vantage.replay_saved_string import destroy_replay_saved_string
from vantage.replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
)
from vantage.replay_unit_ai_map import ReplayUnitAIMapAtomics

U64 = (1 << 64) - 1
FREE, CLEAR, FORWARD, ASSIGN = 0x142D6BAB4, 0x140D36FE0, 0x1409076B0, 0x1402B9080


def storage(memory, *, read=None, write=None):
    return ReplayTaskRebuildStorage(
        1, memory.read if read is None else read, memory.write if write is None else write
    )


def atomics(memory):
    return ReplayUnitAIMapAtomics(memory.compare_exchange_u32, memory.fetch_add_u32)


def invoke(bound, target, *args):
    assert bound.call is not None
    return bound.call(target, args, None)


def vector(memory, begin=0, end=0, capacity=0):
    header = memory.allocate(24)
    for offset, value in ((0, begin), (8, end), (16, capacity)):
        memory.write(header + offset, 8, value)
    return header


def result(memory, *, begin=0, end=0, capacity=0, control=0, status=0x1234, flag=0xA5):
    address = memory.allocate(48)
    memory.write_bytes(address, bytes(range(48)))
    for offset, value in ((0, begin), (8, end), (16, capacity), (24, status), (32, control)):
        memory.write(address + offset, 8, value)
    memory.write(address + 40, 1, flag)
    return address


def control(memory, strong=1, weak=1):
    address, table = memory.allocate(16), memory.allocate(16)
    for pointer, width, value in (
        (address, 8, table),
        (address + 8, 4, strong),
        (address + 12, 4, weak),
        (table, 8, 0xD1),
        (table + 8, 8, 0xD2),
    ):
        memory.write(pointer, width, value)
    return address, table


def ai_list(memory, nodes=0):
    ai = memory.allocate(0xC0)
    memory.write_bytes(ai, b"\xa7" * 0xC0)
    sentinel = ai + 0x78
    values = [memory.allocate(64) for _ in range(nodes)]
    for node, following in zip(values, [*values[1:], sentinel], strict=False):
        memory.write_bytes(node, b"\xcc" * 64)
        memory.write(node + 48, 8, following)
    memory.write(ai + 0xA8, 8, values[0] if values else sentinel)
    memory.write(ai + 0xB0, 8, values[-1] if values else sentinel)
    memory.write(ai + 0xB8, 4, 99)
    return ai, sentinel, values


def sso(memory, address, byte=0x41):
    memory.write_bytes(address, bytes([byte]) * 16)
    memory.write(address + 16, 8, 1)
    memory.write(address + 24, 8, 15)


def test_empty_list_reads_only_head_then_performs_three_ordered_width_stores() -> None:
    memory = ReplayMemory()
    ai, sentinel, _ = ai_list(memory)
    before = memory.read_bytes(ai, 0xC0)
    events = []

    def read(address, width):
        events.append(("read", address, width))
        return memory.read(address, width)

    def write(address, width, value):
        events.append(("write", address, width, value))
        memory.write(address, width, value)

    clear_replay_saved_ai_list(
        storage(memory, read=read, write=write), ai, calls=ReplayTaskRebuildCalls(None)
    )
    assert events == [
        ("read", ai + 0xA8, 8),
        ("write", ai + 0xA8, 8, sentinel),
        ("write", ai + 0xB0, 8, sentinel),
        ("write", ai + 0xB8, 4, 0),
    ]
    assert memory.read_bytes(ai, 0xB8) == before[:0xB8]
    assert memory.read_bytes(ai + 0xBC, 4) == before[0xBC:]


def test_real_node_frees_hold_next_but_read_later_links_currently() -> None:
    memory = ReplayMemory()
    ai, sentinel, (first, second) = ai_list(memory, 2)
    memory.write(second + 48, 8, 0xBAD)
    runtime = memory.runtime_calls()
    seen = []

    def call(target, args, data):
        assert target == FREE and data is None
        seen.append(args)
        if args[0] == first:
            memory.write(first + 48, 8, 0xBAD)
            memory.write(second + 48, 8, sentinel)
            memory.write(ai + 0xA8, 8, 0xABCD)
        assert runtime.call is not None
        return runtime.call(target, args, data)

    clear_replay_saved_ai_list(storage(memory), ai, calls=ReplayTaskRebuildCalls(call))
    assert seen == [(first, 64), (second, 64)]
    assert memory.read(ai + 0xA8, 8) == memory.read(ai + 0xB0, 8) == sentinel
    assert memory.read(ai + 0xB8, 4) == 0
    for node in (first, second):
        with pytest.raises(ReplayMemoryError, match="unmapped"):
            memory.read(node, 1)


def test_list_free_failure_keeps_earlier_free_and_callback_without_header_reset() -> None:
    memory = ReplayMemory()
    ai, _, (first, second) = ai_list(memory, 2)
    runtime = memory.runtime_calls()

    def call(target, args, data):
        assert target == FREE
        if args[0] == second:
            memory.write(ai + 0xB8, 4, 123)
            raise UnresolvedReplayTaskRebuild("second free refused")
        assert runtime.call is not None
        return runtime.call(target, args, data)

    with pytest.raises(UnresolvedReplayTaskRebuild, match="second free refused"):
        clear_replay_saved_ai_list(storage(memory), ai, calls=ReplayTaskRebuildCalls(call))
    assert memory.read(ai + 0xA8, 8) == first
    assert memory.read(ai + 0xB0, 8) == second
    assert memory.read(ai + 0xB8, 4) == 123
    memory.read(second, 1)
    with pytest.raises(ReplayMemoryError, match="unmapped"):
        memory.read(first, 1)


def test_null_list_head_is_dereferenced_not_treated_as_empty() -> None:
    memory = ReplayMemory()
    ai, _, _ = ai_list(memory)
    memory.write(ai + 0xA8, 8, 0)
    before = memory.snapshot()
    with pytest.raises(ReplayMemoryError, match="unmapped"):
        clear_replay_saved_ai_list(storage(memory), ai, calls=ReplayTaskRebuildCalls(None))
    assert memory.snapshot() == before


def test_list_reset_store_failure_happens_after_real_free() -> None:
    memory = ReplayMemory()
    ai, sentinel, (node,) = ai_list(memory, 1)

    def write(address, width, value):
        if address == ai + 0xB0:
            raise RuntimeError("second reset")
        memory.write(address, width, value)

    with pytest.raises(RuntimeError, match="second reset"):
        clear_replay_saved_ai_list(storage(memory, write=write), ai, calls=memory.runtime_calls())
    assert memory.read(ai + 0xA8, 8) == sentinel
    assert memory.read(ai + 0xB0, 8) == node
    assert memory.read(ai + 0xB8, 4) == 99
    with pytest.raises(ReplayMemoryError, match="unmapped"):
        memory.read(node, 1)


def test_bound_list_samples_current_terminal_import_on_each_free() -> None:
    memory = ReplayMemory()
    ai, _, nodes = ai_list(memory, 2)
    memory.map_bytes(0x143199DD0, (0xF1).to_bytes(8, "little"))
    runtime = memory.runtime_calls()
    seen = []

    def terminal(target, args, data):
        seen.append((target, args))
        memory.write(0x143199DD0, 8, 0xF2)
        assert runtime.call is not None
        return runtime.call(FREE, args, data)

    bound = bind_replay_saved_apply(
        storage(memory),
        ReplayTaskRebuildCalls(None),
        atomics=atomics(memory),
        imports=ReplayTaskRebuildCalls(terminal),
    )
    assert invoke(bound, CLEAR, ai) is None
    assert seen == [(0xF1, (nodes[0], 64)), (0xF2, (nodes[1], 64))]


@pytest.mark.parametrize("mapped", [False, True])
def test_bound_list_refuses_missing_current_import_without_reset(mapped) -> None:
    memory = ReplayMemory()
    ai, _, _ = ai_list(memory, 1)
    if mapped:
        memory.map_bytes(0x143199DD0, (0xF1).to_bytes(8, "little"))
    before = memory.snapshot()
    bound = bind_replay_saved_apply(
        storage(memory),
        ReplayTaskRebuildCalls(None),
        atomics=atomics(memory),
        imports=ReplayTaskRebuildCalls(None),
    )
    with pytest.raises((ReplayMemoryError, UnresolvedReplayTaskRebuild)):
        invoke(bound, CLEAR, ai)
    assert memory.snapshot() == before


def test_bound_forward_empty_runs_actual_assignment_four_reads_one_store() -> None:
    memory = ReplayMemory()
    destination, source = result(memory, status=7), result(memory)
    padding = memory.read_bytes(destination + 41, 7)
    events = []

    def read(address, width):
        events.append(("read", address, width))
        return memory.read(address, width)

    def write(address, width, value):
        events.append(("write", address, width, value))
        memory.write(address, width, value)

    bound = bind_replay_saved_apply(
        storage(memory, read=read, write=write),
        ReplayTaskRebuildCalls(None),
        atomics=ReplayUnitAIMapAtomics(None, None),
    )
    assert invoke(bound, FORWARD, destination, source) == destination
    assert events[:6] == [
        ("write", destination + offset, 8, 0) for offset in (0, 8, 16, 24, 32)
    ] + [
        ("write", destination + 40, 1, 0),
    ]
    assert events[-6:] == [
        ("read", destination, 8),
        ("read", destination + 16, 8),
        ("read", destination + 8, 8),
        ("read", destination + 8, 8),
        ("write", destination + 8, 8, 0),
        ("write", source + 40, 1, 1),
    ]
    assert memory.read_bytes(destination, 24) == bytes(24)
    assert memory.read(destination + 24, 8) == 0x1234
    assert memory.read(destination + 32, 8) == memory.read(destination + 40, 1) == 0
    assert memory.read_bytes(destination + 41, 7) == padding
    assert memory.read(source + 40, 1) == 1


def test_self_forward_resets_before_identity_and_never_touches_old_control() -> None:
    memory = ReplayMemory()
    old, _ = control(memory, 5, 6)
    address = result(memory, begin=0xBAD, end=0xBAD, capacity=0xBAD, control=old)
    padding = memory.read_bytes(address + 41, 7)
    assert (
        forward_replay_saved_result(
            storage(memory),
            address,
            address,
            calls=ReplayTaskRebuildCalls(None),
            atomics=ReplayUnitAIMapAtomics(None, None),
        )
        == address
    )
    assert memory.read_bytes(address, 40) == bytes(40)
    assert memory.read(address + 40, 1) == 1
    assert memory.read_bytes(address + 41, 7) == padding
    assert memory.read(old + 8, 4) == 5
    assert memory.read(old + 12, 4) == 6


@pytest.mark.parametrize("strong", [0, 1, 0xFFFFFFFF])
def test_forward_increments_current_source_strong_modulo32(strong) -> None:
    memory = ReplayMemory()
    shared, _ = control(memory, strong, 7)
    destination, source = result(memory), result(memory, control=shared)
    bound = bind_replay_saved_apply(
        storage(memory), ReplayTaskRebuildCalls(None), atomics=atomics(memory)
    )
    invoke(bound, FORWARD, destination, source)
    assert memory.read(shared + 8, 4) == (strong + 1) & 0xFFFFFFFF
    assert memory.read(shared + 12, 4) == 7
    assert memory.read(destination + 32, 8) == shared


def test_forward_rereads_source_control_and_status_after_increment_effect() -> None:
    memory = ReplayMemory()
    first, _ = control(memory, 2, 3)
    second, _ = control(memory, 4, 5)
    destination, source = result(memory), result(memory, control=first)

    def increment(address, delta):
        assert (address, delta) == (first + 8, 1)
        old = memory.fetch_add_u32(address, delta)
        memory.write(source + 32, 8, second)
        memory.write(source + 24, 8, 0x5678)
        return old

    bound = bind_replay_saved_apply(
        storage(memory),
        ReplayTaskRebuildCalls(None),
        atomics=ReplayUnitAIMapAtomics(None, increment),
    )
    invoke(bound, FORWARD, destination, source)
    assert memory.read(first + 8, 4) == 3
    assert memory.read(second + 8, 4) == 4
    assert memory.read(destination + 32, 8) == second
    assert memory.read(destination + 24, 8) == 0x5678


def test_forward_missing_increment_preserves_initial_resets_without_source_flag() -> None:
    memory = ReplayMemory()
    shared, _ = control(memory)
    destination, source = result(memory), result(memory, control=shared)
    with pytest.raises(UnresolvedReplayTaskRebuild, match="atomic effect unavailable"):
        forward_replay_saved_result(
            storage(memory),
            destination,
            source,
            calls=ReplayTaskRebuildCalls(None),
            atomics=ReplayUnitAIMapAtomics(None, None),
        )
    assert memory.read_bytes(destination, 41) == bytes(41)
    assert memory.read(source + 40, 1) == 0xA5
    assert memory.read(shared + 8, 4) == 1


def test_current_old_destination_control_is_held_across_destroy_and_dispose() -> None:
    memory = ReplayMemory()
    old, _ = control(memory)
    current, _ = control(memory, 2, 3)
    replacement, _ = control(memory, 4, 5)
    new_table = memory.allocate(16)
    memory.write(new_table + 8, 8, 0xD3)
    destination, source = result(memory), result(memory, control=current)
    source_begin = memory.allocate(32)
    seen = []

    def write(address, width, value):
        memory.write(address, width, value)
        if (address, width, value) == (destination + 24, 8, 0x1234):
            memory.write(destination + 32, 8, old)

    ctx = storage(memory, write=write)

    def call(target, args, data):
        seen.append((target, args))
        if target == 0xD1:
            assert args == (old,)
            memory.write(destination + 32, 8, replacement)
            memory.write(old, 8, new_table)
        elif target == 0xD3:
            assert args == (old,)
            memory.write(source, 8, source_begin)
            memory.write(source + 8, 8, source_begin)
            memory.write(source + 16, 8, 0xBAD)
        elif target == ASSIGN:
            assert args == (destination, source_begin, 0)
            assign_replay_saved_result_vector(ctx, *args, calls=effects)
        else:
            raise UnresolvedReplayTaskRebuild(f"unexpected{target:x}")
        return None

    effects = ReplayTaskRebuildCalls(call)
    assert (
        forward_replay_saved_result(
            ctx, destination, source, calls=effects, atomics=atomics(memory)
        )
        == destination
    )
    assert seen == [(0xD1, (old,)), (0xD3, (old,)), (ASSIGN, (destination, source_begin, 0))]
    assert memory.read(old + 8, 4) == memory.read(old + 12, 4) == 0
    assert memory.read(destination + 32, 8) == replacement
    assert memory.read(source + 40, 1) == 1


@pytest.mark.parametrize(("delta", "raw_count"), [(-1, U64), (31, 0), (33, 1)])
def test_forward_passes_sar_raw_count_even_odd_or_negative_extent(delta, raw_count) -> None:
    memory = ReplayMemory()
    destination = result(memory)
    source = result(memory, begin=0x3000, end=0x3000 + delta, capacity=0xBAD)

    def call(target, args, data):
        assert (target, args, data) == (ASSIGN, (destination, 0x3000, raw_count), None)
        memory.write(destination + 8, 8, 0xC0DE)
        raise UnresolvedReplayTaskRebuild("explicit vector boundary")

    with pytest.raises(UnresolvedReplayTaskRebuild, match="explicit vector boundary"):
        forward_replay_saved_result(
            storage(memory),
            destination,
            source,
            calls=ReplayTaskRebuildCalls(call),
            atomics=atomics(memory),
        )
    assert memory.read(destination + 8, 8) == 0xC0DE
    assert memory.read(source + 40, 1) == 0xA5


def test_forward_even_empty_needs_assignment_binding_unless_actual_binder_supplied() -> None:
    memory = ReplayMemory()
    destination, source = result(memory), result(memory)
    with pytest.raises(UnresolvedReplayTaskRebuild, match="1402b9080"):
        forward_replay_saved_result(
            storage(memory),
            destination,
            source,
            calls=ReplayTaskRebuildCalls(None),
            atomics=atomics(memory),
        )
    assert memory.read(destination + 24, 8) == 0x1234
    assert memory.read(source + 40, 1) == 0xA5


def test_forward_reset_failure_occurs_before_any_source_read() -> None:
    memory = ReplayMemory()
    destination, source = result(memory), result(memory)
    source_before = memory.read_bytes(source, 48)
    reads = []

    def write(address, width, value):
        if address == destination + 8:
            raise RuntimeError("second initial reset")
        memory.write(address, width, value)

    def read(address, width):
        reads.append((address, width))
        return memory.read(address, width)

    with pytest.raises(RuntimeError, match="second initial reset"):
        forward_replay_saved_result(
            storage(memory, read=read, write=write),
            destination,
            source,
            calls=ReplayTaskRebuildCalls(None),
            atomics=atomics(memory),
        )
    assert not reads
    assert memory.read_bytes(source, 48) == source_before


def test_zero_vector_profile_keeps_all_four_header_reads_and_one_end_store() -> None:
    memory = ReplayMemory()
    header = vector(memory)
    events = []

    def read(address, width):
        events.append(("r", address, width))
        return memory.read(address, width)

    def write(address, width, value):
        events.append(("w", address, width, value))
        memory.write(address, width, value)

    assign_replay_saved_result_vector(
        storage(memory, read=read, write=write),
        header,
        0xBAD,
        0,
        calls=ReplayTaskRebuildCalls(None),
    )
    assert events == [
        ("r", header, 8),
        ("r", header + 16, 8),
        ("r", header + 8, 8),
        ("r", header + 8, 8),
        ("w", header + 8, 8, 0),
    ]


def test_zero_requested_nonempty_tail_runs_actual_element_destruction() -> None:
    memory = ReplayMemory()
    elements = memory.allocate(64)
    for slot in (elements, elements + 32):
        sso(memory, slot)
    header = vector(memory, elements, elements + 64, elements + 64)
    runtime = memory.runtime_calls()

    def call(target, args, data):
        assert target == 0x1402A88A0
        destroy_replay_saved_string(storage(memory), *args, calls=runtime)
        return None

    assign_replay_saved_result_vector(
        storage(memory), header, 0xBAD, 0, calls=ReplayTaskRebuildCalls(call)
    )
    assert memory.read(header + 8, 8) == elements
    for slot in (elements, elements + 32):
        assert memory.read(slot, 1) == memory.read(slot + 16, 8) == 0
        assert memory.read(slot + 24, 8) == 15


def test_exact_element_identity_skips_undefined_source_descriptor_and_children() -> None:
    memory = ReplayMemory()
    element = memory.allocate(32)
    header = vector(memory, element, element + 32, element + 32)
    assign_replay_saved_result_vector(
        storage(memory), header, element, 1, calls=ReplayTaskRebuildCalls(None)
    )
    assert memory.read(header + 8, 8) == element + 32
    with pytest.raises(ReplayMemoryError, match="undefined"):
        memory.read(element + 24, 8)


@pytest.mark.parametrize("capacity", [15, 16, U64])
def test_assignment_selects_inline_or_current_heap_pointer_before_length(capacity) -> None:
    memory = ReplayMemory()
    destination, source, heap = (memory.allocate(32) for _ in range(3))
    header = vector(memory, destination, destination + 32, destination + 32)
    sso(memory, source)
    memory.write(source + 24, 8, capacity)
    memory.write(source, 8, 0xBAD)
    reads, calls = [], []

    def read(address, width):
        value = memory.read(address, width)
        reads.append((address, width))
        if address == source + 24:
            memory.write(source, 8, heap)
            memory.write(source + 16, 8, 9)
        return value

    def call(target, args, data):
        calls.append((target, args))
        assert (target, args, data) == (
            0x1402A8FB0,
            (destination, source if capacity == 15 else heap, 9),
            None,
        )
        # Explicit supplied child effect; this test does not implement that child.
        memory.write(destination, 1, 0xAB)
        return None

    assign_replay_saved_result_vector(
        storage(memory, read=read), header, source, 1, calls=ReplayTaskRebuildCalls(call)
    )
    expected = [(header, 8), (header + 16, 8), (header + 8, 8), (source + 24, 8)]
    if capacity > 15:
        expected.append((source, 8))
    assert reads == [*expected, (source + 16, 8), (header + 8, 8)]
    assert len(calls) == 1 and memory.read(destination, 1) == 0xAB


def test_heap_descriptor_pointer_fault_precedes_length_and_child() -> None:
    memory = ReplayMemory()
    destination, source = memory.allocate(32), memory.allocate(32)
    header = vector(memory, destination, destination + 32, destination + 32)
    memory.write(source + 24, 8, 16)
    reads = []

    def read(address, width):
        reads.append((address, width))
        return memory.read(address, width)

    before = memory.snapshot()
    with pytest.raises(ReplayMemoryError, match="undefined"):
        assign_replay_saved_result_vector(
            storage(memory, read=read), header, source, 1, calls=ReplayTaskRebuildCalls(None)
        )
    assert reads[-2:] == [(source + 24, 8), (source, 8)]
    assert memory.snapshot() == before


def test_append_reloads_current_end_but_keeps_original_size_and_constructor_cursor() -> None:
    memory = ReplayMemory()
    destination, source = memory.allocate(128), memory.allocate(128)
    for i in range(4):
        sso(memory, source + i * 32, 0x41 + i)
    header = vector(memory, destination, destination + 32, destination + 128)
    seen = []

    def call(target, args, data):
        assert data is None
        seen.append((target, args))
        if target == 0x1402A8FB0:
            memory.write(args[0], 1, 0xAA)
            memory.write(header + 8, 8, destination + 64)
        elif target == 0x1402A9630:
            memory.write_bytes(args[0], memory.read_bytes(args[1], 32))
            memory.write(header + 8, 8, 0xBAD)
        else:
            raise UnresolvedReplayTaskRebuild(f"unexpected{target:x}")
        return None

    assign_replay_saved_result_vector(
        storage(memory), header, source, 3, calls=ReplayTaskRebuildCalls(call)
    )
    assert seen == [
        (0x1402A8FB0, (destination, source, 1)),
        (0x1402A8FB0, (destination + 32, source + 32, 1)),
        (0x1402A9630, (destination + 64, source + 64)),
        (0x1402A9630, (destination + 96, source + 96)),
    ]
    assert memory.read(header + 8, 8) == destination + 128
    assert memory.read(destination + 64, 1) == 0x43
    assert memory.read(destination + 96, 1) == 0x44


@pytest.mark.parametrize("fail_second", [False, True])
def test_initially_empty_append_holds_cursor_and_preserves_partial_constructions(
    fail_second,
) -> None:
    memory = ReplayMemory()
    destination, source = memory.allocate(64), memory.allocate(64)
    memory.write_bytes(source, bytes(range(64)))
    header = vector(memory, destination, destination, destination + 64)
    seen, reads = [], []

    def read(address, width):
        reads.append((address, width))
        return memory.read(address, width)

    def call(target, args, data):
        assert target == 0x1402A9630 and data is None
        seen.append(args)
        memory.write_bytes(args[0], memory.read_bytes(args[1], 32))
        memory.write(header + 8, 8, 0xBAD)
        if fail_second and len(seen) == 2:
            raise UnresolvedReplayTaskRebuild("constructor partial failure")
        return None

    def execute():
        assign_replay_saved_result_vector(
            storage(memory, read=read), header, source, 2, calls=ReplayTaskRebuildCalls(call)
        )

    if fail_second:
        with pytest.raises(UnresolvedReplayTaskRebuild, match="constructor partial failure"):
            execute()
    else:
        execute()
    assert seen == [(destination, source), (destination + 32, source + 32)]
    assert reads == [(header, 8), (header + 16, 8), (header + 8, 8)]
    assert memory.read_bytes(destination, 64) == bytes(range(64))
    assert memory.read(header + 8, 8) == (0xBAD if fail_second else destination + 64)


def test_shrink_holds_target_and_destruction_end_across_actual_element_resets() -> None:
    memory = ReplayMemory()
    destination, source = memory.allocate(96), memory.allocate(32)
    for i in range(3):
        sso(memory, destination + i * 32, 0x41 + i)
    sso(memory, source, 0x50)
    header = vector(memory, destination, destination + 96, destination + 96)
    seen = []
    runtime = memory.runtime_calls()

    def call(target, args, data):
        seen.append((target, args))
        if target == 0x1402A8FB0:
            memory.write(args[0], 1, memory.read(args[1], 1))
        elif target == 0x1402A88A0:
            destroy_replay_saved_string(storage(memory), *args, calls=runtime)
            memory.write(header + 8, 8, destination + 32)
        else:
            raise UnresolvedReplayTaskRebuild(f"unexpected{target:x}")
        return None

    assign_replay_saved_result_vector(
        storage(memory), header, source, 1, calls=ReplayTaskRebuildCalls(call)
    )
    assert seen == [
        (0x1402A8FB0, (destination, source, 1)),
        (0x1402A88A0, (destination + 32,)),
        (0x1402A88A0, (destination + 64,)),
    ]
    assert memory.read(header + 8, 8) == destination + 32
    assert memory.read(destination, 1) == 0x50
    assert memory.read(destination + 32, 1) == memory.read(destination + 64, 1) == 0


def test_growth_passes_incidental_r8_and_reloads_begin_then_commits_real_return() -> None:
    memory = ReplayMemory()
    old, source = memory.allocate(32), memory.allocate(64)
    memory.write_bytes(source, bytes(range(64)))
    header = vector(memory, old, old + 32, old + 32)
    replacement = 0
    seen = []

    def call(target, args, data):
        nonlocal replacement
        assert data is None
        seen.append((target, args))
        if target == 0x1402BA380:
            assert args == (header, 2, 2)  # R8 is source-incidental, not proven consumed.
            replacement = memory.allocate(64)
            memory.write(header, 8, replacement)
            memory.write(header + 16, 8, replacement + 64)
            return None
        if target == 0x1402B9B40:
            assert args == (source, 2, replacement, header)
            memory.write_bytes(replacement, memory.read_bytes(source, 64))
            memory.write(header + 8, 8, 0xBAD)
            return replacement + 64
        raise UnresolvedReplayTaskRebuild(f"unexpected{target:x}")

    assign_replay_saved_result_vector(
        storage(memory), header, source, 2, calls=ReplayTaskRebuildCalls(call)
    )
    assert [target for target, _ in seen] == [0x1402BA380, 0x1402B9B40]
    assert memory.read(header, 8) == replacement
    assert memory.read(header + 8, 8) == memory.read(header + 16, 8) == replacement + 64
    assert memory.read_bytes(replacement, 64) == bytes(range(64))


@pytest.mark.parametrize("count", [1, U64])
def test_growth_requires_real_reserve_before_later_header_reads(count) -> None:
    memory = ReplayMemory()
    header = vector(memory)
    reads = []

    def read(address, width):
        reads.append((address, width))
        return memory.read(address, width)

    def call(target, args, data):
        assert (target, args, data) == (0x1402BA380, (header, count, count), None)
        raise UnresolvedReplayTaskRebuild("reserve unavailable")

    before = memory.snapshot()
    with pytest.raises(UnresolvedReplayTaskRebuild, match="reserve unavailable"):
        assign_replay_saved_result_vector(
            storage(memory, read=read), header, 0xBAD, count, calls=ReplayTaskRebuildCalls(call)
        )
    assert reads == [(header, 8), (header + 16, 8)]
    assert memory.snapshot() == before


def test_growth_missing_range_return_keeps_real_reserve_and_child_writes() -> None:
    memory = ReplayMemory()
    header, data = vector(memory), memory.allocate(32)

    def call(target, args, local):
        if target == 0x1402BA380:
            memory.write(header, 8, data)
            memory.write(header + 16, 8, data + 32)
        elif target == 0x1402B9B40:
            memory.write(data, 1, 0xAC)
        else:
            raise UnresolvedReplayTaskRebuild(f"unexpected{target:x}")
        return None

    with pytest.raises(ValueError, match="must return its raw scalar"):
        assign_replay_saved_result_vector(
            storage(memory), header, 0xBAD, 1, calls=ReplayTaskRebuildCalls(call)
        )
    assert memory.read(header, 8) == data
    assert memory.read(header + 16, 8) == data + 32
    assert memory.read(header + 8, 8) == 0
    assert memory.read(data, 1) == 0xAC


def test_signed_negative_capacity_count_is_compared_as_unsigned_raw_word() -> None:
    memory = ReplayMemory()
    destination, source = memory.allocate(32), memory.allocate(32)
    memory.write_bytes(source, bytes(range(32)))
    header = vector(memory, destination, destination, destination - 1)
    seen = []

    def call(target, args, data):
        assert (target, args, data) == (0x1402A9630, (destination, source), None)
        seen.append(target)
        memory.write_bytes(destination, memory.read_bytes(source, 32))
        return None

    assign_replay_saved_result_vector(
        storage(memory), header, source, 1, calls=ReplayTaskRebuildCalls(call)
    )
    assert seen == [0x1402A9630]
    assert memory.read(header + 8, 8) == destination + 32


@pytest.mark.parametrize("count", [0, 1])
def test_unprovided_assignment_or_tail_destructor_refuses_without_end_commit(count) -> None:
    memory = ReplayMemory()
    destination, source = memory.allocate(32), memory.allocate(32)
    sso(memory, destination)
    sso(memory, source)
    header = vector(memory, destination, destination + 32, destination + 32)
    before = memory.snapshot()
    with pytest.raises(UnresolvedReplayTaskRebuild, match=r"1402a88a0|1402a8fb0"):
        assign_replay_saved_result_vector(
            storage(memory), header, source, count, calls=ReplayTaskRebuildCalls(None)
        )
    assert memory.snapshot() == before


def test_forward_does_not_set_processed_if_actual_assignment_end_store_fails() -> None:
    memory = ReplayMemory()
    destination, source = result(memory), result(memory)
    writes = 0

    def write(address, width, value):
        nonlocal writes
        if address == destination + 8:
            writes += 1
            if writes == 2:
                raise RuntimeError("assignment final store")
        memory.write(address, width, value)

    bound = bind_replay_saved_apply(
        storage(memory, write=write), ReplayTaskRebuildCalls(None), atomics=atomics(memory)
    )
    with pytest.raises(RuntimeError, match="assignment final store"):
        invoke(bound, FORWARD, destination, source)
    assert writes == 2
    assert memory.read(destination + 24, 8) == 0x1234
    assert memory.read(source + 40, 1) == 0xA5


def test_terminal_free_target_equal_to_bound_entry_is_not_redispatched() -> None:
    memory = ReplayMemory()
    ai, sentinel, (node,) = ai_list(memory, 1)
    memory.map_bytes(0x143199DD0, CLEAR.to_bytes(8, "little"))
    runtime = memory.runtime_calls()
    seen = []

    def terminal(target, args, data):
        assert (target, args, data) == (CLEAR, (node, 64), None)
        seen.append(target)
        assert runtime.call is not None
        return runtime.call(FREE, args, data)

    bound = bind_replay_saved_apply(
        storage(memory),
        ReplayTaskRebuildCalls(None),
        atomics=atomics(memory),
        imports=ReplayTaskRebuildCalls(terminal),
    )
    invoke(bound, CLEAR, ai)
    assert seen == [CLEAR]
    assert memory.read(ai + 0xA8, 8) == sentinel


@pytest.mark.parametrize(
    ("target", "args"),
    [
        (CLEAR, ()),
        (FORWARD, (1,)),
        (ASSIGN, (1, 2)),
        (FREE, (1,)),
        (ASSIGN, (1, 2, -1)),
        (CLEAR, (True,)),
    ],
)
def test_binder_rejects_malformed_raw_calls_before_storage(target, args) -> None:
    memory = ReplayMemory()
    before = memory.snapshot()
    bound = bind_replay_saved_apply(
        storage(memory), ReplayTaskRebuildCalls(None), atomics=atomics(memory)
    )
    with pytest.raises(ValueError):
        invoke(bound, target, *args)
    assert memory.snapshot() == before


def test_binder_data_guard_and_unknown_target_raw_delegation() -> None:
    memory = ReplayMemory()
    seen = []

    def call(target, args, data):
        seen.append((target, args, None if data is None else bytes(data)))
        return 0xCAFE

    bound = bind_replay_saved_apply(
        storage(memory), ReplayTaskRebuildCalls(call), atomics=atomics(memory)
    )
    assert bound.call is not None
    with pytest.raises(ValueError, match="malformed saved apply"):
        bound.call(CLEAR, (1,), memoryview(b""))
    assert not seen
    assert bound.call(0xBAD, (1, 2), memoryview(b"x")) == 0xCAFE
    assert seen == [(0xBAD, (1, 2), b"x")]
