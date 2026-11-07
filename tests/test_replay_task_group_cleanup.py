from __future__ import annotations

from collections.abc import Callable

import pytest

from vantage.replay_memory import ReplayMemory, ReplayMemoryError, ReplayMemoryRuntimeError
from vantage.replay_task_effects import bind_replay_task_execution, clear_replay_task_groups
from vantage.replay_task_group_cleanup import (
    bind_replay_task_group_cleanup,
    destroy_replay_task_group_child,
    destroy_replay_task_group_map,
    destroy_replay_task_vector4,
    destroy_replay_task_vector8,
)
from vantage.replay_task_prefix import ReplayTaskPrefixScratch
from vantage.replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildScratch,
    ReplayTaskRebuildStorage,
    run_replay_task_rebuild,
)


@pytest.mark.parametrize("destroy", [destroy_replay_task_vector4, destroy_replay_task_vector8])
def test_null_begin_reads_no_other_fields(destroy: Callable[..., None]) -> None:
    memory = ReplayMemory()
    memory.map_bytes(0x1000, bytes(8))
    context = ReplayTaskRebuildStorage(0x1000, memory.read, memory.write)
    before = memory.snapshot()
    destroy(context, 0x1000, calls=ReplayTaskRebuildCalls(None))
    assert memory.snapshot() == before


@pytest.mark.parametrize(
    "destroy,rounding",
    [
        (destroy_replay_task_vector4, 4),
        (destroy_replay_task_vector8, 8),
    ],
)
@pytest.mark.parametrize("size", [4, 8, 0xFFC, 0x1000, 0x1008])
def test_free_before_header_reset(
    destroy: Callable[..., None],
    rounding: int,
    size: int,
) -> None:
    memory = ReplayMemory()
    header = memory.allocate(24)
    rounded = (size + rounding - 1) & -rounding
    buffer = memory.allocate_aligned(rounded)
    memory.write(header, 8, buffer)
    # End remains undefined and must not be interpreted.
    memory.write(header + 16, 8, buffer + size + rounding - 1)
    context = ReplayTaskRebuildStorage(header, memory.read, memory.write)
    base = memory.read(buffer - 8, 8) if rounded >= 0x1000 else buffer
    events = []
    runtime = memory.runtime_calls()

    def free(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        assert target == 0x142D6BAB4 and data is None
        events.append(args)
        assert memory.read(header, 8) == buffer
        memory.write(header + 8, 8, 0xBAD)
        assert runtime.call is not None
        return runtime.call(target, args, data)

    destroy(context, header, calls=ReplayTaskRebuildCalls(free))
    assert events == [(base, rounded + (0x27 if rounded >= 0x1000 else 0))]
    assert memory.read_bytes(header, 24) == bytes(24)
    assert memory.mapped_bytes == 24


@pytest.mark.parametrize("destroy", [destroy_replay_task_vector4, destroy_replay_task_vector8])
def test_invalid_backpointer_preserves_header_and_does_not_free(
    destroy: Callable[..., None],
) -> None:
    memory = ReplayMemory()
    memory.map_bytes(
        0x1000, (0x3000).to_bytes(8, "little") + bytes(8) + (0x4000).to_bytes(8, "little")
    )
    memory.map_bytes(0x2FF8, (0x2FD0).to_bytes(8, "little"))  # delta40 >31
    memory.map_bytes(0x14319A060, (0x142D66698).to_bytes(8, "little"))
    context = ReplayTaskRebuildStorage(0x1000, memory.read, memory.write)
    before = memory.snapshot()
    with pytest.raises(ReplayMemoryRuntimeError) as error:
        destroy(context, 0x1000, calls=memory.runtime_calls())
    assert error.value.target == 0x142D66698 and error.value.args_words == (0, 0, 0, 0, 0)
    assert memory.snapshot() == before
    with pytest.raises(RuntimeError, match="unexpectedly returned"):
        destroy(context, 0x1000, calls=ReplayTaskRebuildCalls(lambda *_: None))
    assert memory.snapshot() == before


def _zero(memory: ReplayMemory, size: int) -> int:
    address = memory.allocate(size)
    memory.write_bytes(address, bytes(size))
    return address


def _ring(memory: ReplayMemory, size: int, count: int) -> tuple[int, list[int]]:
    head = _zero(memory, size)
    nodes = [_zero(memory, size) for _ in range(count)]
    ring = [head, *nodes]
    for index, node in enumerate(ring):
        memory.write(node, 8, ring[(index + 1) % len(ring)])
        memory.write(node + 8, 8, ring[index - 1])
    return head, nodes


def _vector(memory: ReplayMemory, header: int, size: int) -> None:
    buffer = memory.allocate_aligned(size)
    memory.write(header, 8, buffer)
    memory.write(header + 8, 8, buffer + size)
    memory.write(header + 16, 8, buffer + size)


@pytest.mark.parametrize("outer_count,inner_count,leaf_count", [(1, 0, 0), (2, 2, 3)])
def test_actual_recursive_group_clear_releases_all_members(
    outer_count: int,
    inner_count: int,
    leaf_count: int,
) -> None:
    memory = ReplayMemory()
    header = _zero(memory, 0x40)
    head, nodes = _ring(memory, 0x78, outer_count)
    buckets = _zero(memory, 64)
    memory.write(header + 8, 8, head)
    memory.write(header + 0x10, 8, outer_count)
    memory.write(header + 0x18, 8, buckets)
    memory.write(header + 0x20, 8, buckets + 64)
    for node in nodes:
        _vector(memory, node + 0x60, 0x1000)
        _vector(memory, node + 0x38, 24)
        inner_head, inner_nodes = _ring(memory, 0xA0, inner_count)
        memory.write(node + 0x28, 8, inner_head)
        for inner in inner_nodes:
            child = inner + 0x28
            _vector(memory, child, 16)
            _vector(memory, child + 0x18, 0x1000)
            _vector(memory, child + 0x48, 40)
            leaf_head, _ = _ring(memory, 0x18, leaf_count)
            memory.write(child + 0x38, 8, leaf_head)
    context = ReplayTaskRebuildStorage(header, memory.read, memory.write)
    bound = bind_replay_task_group_cleanup(
        context, memory.runtime_calls(), bind_local=memory.bind_local
    )
    clear_replay_task_groups(context, header, calls=bound)
    assert memory.read(head, 8) == head and memory.read(head + 8, 8) == head
    assert memory.read(header + 0x10, 8) == 0
    assert memory.read_bytes(buckets, 64) == head.to_bytes(8, "little") * 8
    assert memory.mapped_bytes == 0x40 + 0x78 + 64
    snapshot = memory.snapshot()
    restored = ReplayMemory.from_snapshot(snapshot)
    restored_context = ReplayTaskRebuildStorage(header, restored.read, restored.write)
    clear_replay_task_groups(restored_context, header, calls=ReplayTaskRebuildCalls(None))
    assert restored.snapshot() == snapshot
    for freed in nodes:
        with pytest.raises(ReplayMemoryError, match="unmapped"):
            memory.read(freed, 8)


def test_empty_nested_map_still_detaches_and_frees_sentinel() -> None:
    memory = ReplayMemory()
    address = _zero(memory, 8)
    head, _ = _ring(memory, 0xA0, 0)
    memory.write(address, 8, head)
    context = ReplayTaskRebuildStorage(address, memory.read, memory.write)
    bound = bind_replay_task_group_cleanup(
        context, memory.runtime_calls(), bind_local=memory.bind_local
    )
    destroy_replay_task_group_map(context, address, calls=bound)
    assert memory.mapped_bytes == 8
    assert memory.read(address, 8) == head  # Source leaves dangling input unchanged.


def test_child_reads_head_after_first_destructor() -> None:
    memory = ReplayMemory()
    child = _zero(memory, 0x78)
    old_head = 0xBAD  # Not backed: eager head access would fail.
    head, _ = _ring(memory, 0x18, 0)
    memory.write(child + 0x38, 8, old_head)
    context = ReplayTaskRebuildStorage(child, memory.read, memory.write)
    events = []
    runtime = memory.runtime_calls()

    def call(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        events.append((target, args))
        if target == 0x1412A66A0:
            assert args == (child + 0x48,)
            memory.write(child + 0x38, 8, head)
        elif target == 0x1402BD6F0:
            destroy_replay_task_vector4(context, args[0], calls=runtime)
        else:
            assert runtime.call is not None
            return runtime.call(target, args, data)
        return None

    destroy_replay_task_group_child(context, child, calls=ReplayTaskRebuildCalls(call))
    assert events == [
        (0x1412A66A0, (child + 0x48,)),
        (0x142D6BAB4, (head, 0x18)),
        (0x1402BD6F0, (child + 0x18,)),
        (0x1402BD6F0, (child,)),
    ]
    assert memory.read(child + 0x38, 8) == head


def test_map_holds_next_across_child_and_reloads_current_sentinel() -> None:
    memory = ReplayMemory()
    address = _zero(memory, 8)
    original, nodes = _ring(memory, 0xA0, 2)
    replacement = _zero(memory, 0xA0)
    memory.write(address, 8, original)
    context = ReplayTaskRebuildStorage(address, memory.read, memory.write)
    runtime = memory.runtime_calls()
    events = []

    def call(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        events.append((target, args))
        if target == 0x1412A71D0:
            node = args[0] - 0x28
            # Neither mutation invalidates the held next or original node.
            memory.write(node, 8, 0xBAD)
            memory.write(address, 8, replacement)
        else:
            assert runtime.call is not None
            return runtime.call(target, args, data)
        return None

    destroy_replay_task_group_map(context, address, calls=ReplayTaskRebuildCalls(call))
    assert events == [
        (0x1412A71D0, (nodes[0] + 0x28,)),
        (0x142D6BAB4, (nodes[0], 0xA0)),
        (0x1412A71D0, (nodes[1] + 0x28,)),
        (0x142D6BAB4, (nodes[1], 0xA0)),
        (0x142D6BAB4, (replacement, 0xA0)),
    ]
    assert memory.mapped_bytes == 8 + 0xA0
    assert memory.read(original, 8) == nodes[0]
    assert memory.read(address, 8) == replacement


def test_child_holds_next_across_free_and_rereads_current_sentinel() -> None:
    memory = ReplayMemory()
    child = _zero(memory, 0x78)
    original, nodes = _ring(memory, 0x18, 2)
    replacement = _zero(memory, 0x18)
    memory.write(child + 0x38, 8, original)
    context = ReplayTaskRebuildStorage(child, memory.read, memory.write)
    runtime = memory.runtime_calls()
    freed = []

    def call(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        assert target == 0x142D6BAB4
        freed.append(args)
        if args[0] in nodes:
            memory.write(args[0], 8, 0xBAD)
            memory.write(child + 0x38, 8, replacement)
        assert runtime.call is not None
        return runtime.call(target, args, data)

    bound = bind_replay_task_group_cleanup(
        context, ReplayTaskRebuildCalls(call), bind_local=memory.bind_local
    )
    destroy_replay_task_group_child(context, child, calls=bound)
    assert freed == [(node, 0x18) for node in [*nodes, replacement]]
    assert memory.mapped_bytes == 0x78 + 0x18
    assert memory.read(original, 8) == nodes[0]
    assert memory.read(child + 0x38, 8) == replacement


def test_failed_node_release_preserves_prior_detach_and_current_header() -> None:
    memory = ReplayMemory()
    child = _zero(memory, 0x78)
    head, nodes = _ring(memory, 0x18, 1)
    memory.write(child + 0x38, 8, head)
    context = ReplayTaskRebuildStorage(child, memory.read, memory.write)

    def fail(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        assert target == 0x142D6BAB4 and args == (nodes[0], 0x18) and data is None
        raise RuntimeError("free stopped")

    bound = bind_replay_task_group_cleanup(
        context, ReplayTaskRebuildCalls(fail), bind_local=memory.bind_local
    )
    with pytest.raises(RuntimeError, match="free stopped"):
        destroy_replay_task_group_child(context, child, calls=bound)
    assert memory.read(nodes[0], 8) == 0  # Detach survives; free did not execute.
    assert memory.read(child + 0x38, 8) == head
    assert memory.mapped_bytes == 0x78 + 0x30


def test_fill_keeps_live_partial_alias_source() -> None:
    from collections.abc import Iterator
    from contextlib import contextmanager

    memory = ReplayMemory()
    local = bytearray.fromhex("0807060504030201")
    with memory.bind_local(memoryview(local)) as source:
        memory.map_bytes(source - 4, bytes(4))
        memory.map_bytes(source + 8, bytes(12))
        context = ReplayTaskRebuildStorage(source, memory.read, memory.write)

        @contextmanager
        def alias(view: memoryview) -> Iterator[int]:
            assert view.obj is local
            yield source

        bound = bind_replay_task_group_cleanup(
            context, ReplayTaskRebuildCalls(None), bind_local=alias
        )
        assert bound.call is not None
        bound.call(0x1412A5BD0, (source - 4, source + 20), memoryview(local))
        # source is inside qword-start bounds. Each write overlaps the next
        # source interpretation; caching the original value would differ.
        expected = bytes.fromhex("080706050403020104030201040302010403020104030201")
        assert memory.read_bytes(source - 4, 24) == expected
        assert local == bytes.fromhex("0403020104030201")


def test_fill_odd_tail_rereads_live_local_after_bulk_writes() -> None:
    from collections.abc import Iterator
    from contextlib import contextmanager

    memory = ReplayMemory()
    begin = _zero(memory, 24)
    value = bytearray((7).to_bytes(8, "little"))

    def write(address: int, width: int, word: int) -> None:
        memory.write(address, width, word)
        if address == begin:
            value[:] = (9).to_bytes(8, "little")

    context = ReplayTaskRebuildStorage(begin, memory.read, write)

    @contextmanager
    def bind(view: memoryview) -> Iterator[int]:
        with memory.bind_local(view) as address:
            yield address

    bound = bind_replay_task_group_cleanup(context, ReplayTaskRebuildCalls(None), bind_local=bind)
    assert bound.call is not None
    bound.call(0x1412A5BD0, (begin, begin + 24), memoryview(value))
    assert [memory.read(begin + i * 8, 8) for i in range(3)] == [7, 7, 9]


def test_fill_binding_exit_cannot_suppress_unbacked_write() -> None:
    class Suppressor:
        def __enter__(self) -> int:
            return 0x2000  # Empty destination does not read this source.

        def __exit__(self, *_: object) -> bool:
            return True

    memory = ReplayMemory()
    memory.map_bytes(0x2000, bytes(8))
    context = ReplayTaskRebuildStorage(0x1000, memory.read, memory.write)
    bound = bind_replay_task_group_cleanup(
        context, ReplayTaskRebuildCalls(None), bind_local=lambda _: Suppressor()
    )
    assert bound.call is not None
    with pytest.raises(ReplayMemoryError, match="unmapped"):
        bound.call(0x1412A5BD0, (0x1000, 0x1008), memoryview(bytearray(8)))


@pytest.mark.parametrize("has_task_list", [False, True])
def test_outer_rebuild_recursively_clears_populated_groups_and_restores_exactly(
    has_task_list: bool,
) -> None:
    memory = ReplayMemory()
    subject = _zero(memory, 0x900)
    header = subject + 0x6E0
    head, nodes = _ring(memory, 0x78, 2)
    buckets = _zero(memory, 64)
    memory.write(header + 8, 8, head)
    memory.write(header + 0x10, 8, 2)
    memory.write(header + 0x18, 8, buckets)
    memory.write(header + 0x20, 8, buckets + 64)
    for node in nodes:
        _vector(memory, node + 0x60, 0x1000)
        _vector(memory, node + 0x38, 24)
        inner_head, inner_nodes = _ring(memory, 0xA0, 2)
        memory.write(node + 0x28, 8, inner_head)
        for inner in inner_nodes:
            child = inner + 0x28
            _vector(memory, child, 16)
            _vector(memory, child + 0x18, 0x1000)
            _vector(memory, child + 0x48, 40)
            leaf_head, _ = _ring(memory, 0x18, 2)
            memory.write(child + 0x38, 8, leaf_head)
    retained = []
    for offset, size in ((0x530, 16), (0x730, 40), (0x7A8, 48)):
        _vector(memory, subject + offset, size)
        retained.append((offset, memory.read(subject + offset, 8), size))
    pair_out, byte_out = _zero(memory, 9), _zero(memory, 9)
    task_list = _zero(memory, 24) if has_task_list else 0
    initial = memory.snapshot()

    def rebuild(current: ReplayMemory) -> None:
        context = ReplayTaskRebuildStorage(subject, current.read, current.write)
        bound = bind_replay_task_execution(
            context,
            current.runtime_calls(),
            bind_local=current.bind_local,
            pair_out=pair_out,
            byte_out=byte_out,
            mxcsr=0x1F80,
            prefix_scratch=ReplayTaskPrefixScratch(bytes(64), b"abc", b"xyz"),
        )
        run_replay_task_rebuild(
            context,
            task_list,
            mxcsr=0x1F80,
            calls=bound,
            scratch=ReplayTaskRebuildScratch(bytes(48), b"abc", b"xyz"),
        )

    rebuild(memory)
    assert memory.mapped_bytes == 0x900 + 0x78 + 64 + 18 + 104 + (24 if has_task_list else 0)
    assert memory.read(header + 0x10, 8) == 0
    assert memory.read(head, 8) == head and memory.read(head + 8, 8) == head
    assert memory.read_bytes(buckets, 64) == head.to_bytes(8, "little") * 8
    for offset, begin, capacity in retained:
        assert memory.read(subject + offset, 8) == begin
        assert memory.read(subject + offset + 8, 8) == begin
        assert memory.read(subject + offset + 16, 8) == begin + capacity
    final = memory.snapshot()
    rebuild(memory)  # A second real rebuild reaches the source's count-zero path.
    assert memory.snapshot() == final
    restored = ReplayMemory.from_snapshot(initial)
    rebuild(restored)
    assert restored.snapshot() == final
