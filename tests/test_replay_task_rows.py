"""Real task vectors/search, late copies and complete155 execution routing."""

from __future__ import annotations

import struct

import pytest

from vantage.replay_memory import ReplayMemory, ReplayMemoryError
from vantage.replay_task_construction import bind_replay_task_construction
from vantage.replay_task_effects import bind_replay_task_execution
from vantage.replay_task_prefix import ReplayTaskPrefixScratch
from vantage.replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildScratch,
    ReplayTaskRebuildStorage,
    run_replay_task_rebuild,
)
from vantage.replay_task_rows import (
    bind_replay_task_rows,
    find_replay_task_class,
)

FEATURE, MASK_START = 0x144114154, 0x14365D534
U64 = (1 << 64) - 1


def storage(memory: ReplayMemory, subject: int = 0x1000) -> ReplayTaskRebuildStorage:
    return ReplayTaskRebuildStorage(subject, memory.read, memory.write)


def bound(
    memory: ReplayMemory,
    calls: ReplayTaskRebuildCalls | None = None,
) -> ReplayTaskRebuildCalls:
    return bind_replay_task_rows(
        storage(memory), calls or memory.runtime_calls(), bind_local=memory.bind_local
    )


def invoke(
    calls: ReplayTaskRebuildCalls,
    target: int,
    args: tuple[int, ...],
    data: memoryview | None = None,
) -> int | None:
    assert calls.call is not None
    return calls.call(target, args, data)


def vector(memory: ReplayMemory, stride: int, used: int = 0, capacity: int = 0) -> tuple[int, int]:
    header = memory.allocate(24)
    begin = memory.allocate_aligned(stride * capacity) if capacity else 0
    if capacity:
        memory.write_bytes(begin, bytes((i * 7 + 5) & 255 for i in range(stride * capacity)))
    for offset, value in ((0, begin), (8, begin + used * stride), (16, begin + capacity * stride)):
        memory.write(header + offset, 8, value)
    return header, begin


@pytest.mark.parametrize("value", [0, 55, 899, 900, 999, 1000, 0x7FFFFFFF, 0x80000000, U64])
@pytest.mark.parametrize("target", [0x1410B9F00, 0x1410BD060, 0x1410BA3D0])
def test_selector_register_widths(value: int, target: int) -> None:
    calls = bound(ReplayMemory())
    expected = (
        (value + 900) & 0xFFFFFFFF
        if target == 0x1410B9F00
        else (value - 900) & 0xFFFFFFFF
        if target == 0x1410BD060
        else int(900 <= value & 0xFFFFFFFF <= 999)
    )
    assert invoke(calls, target, (value,)) == expected
    if target == 0x1410B9F00:
        assert invoke(calls, target, (value, 1998)) == expected


@pytest.mark.parametrize("feature", [0, 4, 0x20, 0x24])
@pytest.mark.parametrize("count", [0, 3, 4, 8, 9, 15])
@pytest.mark.parametrize("hit", [False, True])
def test_find_first_match_or_end_across_scalar_and_vector_paths(
    feature: int,
    count: int,
    hit: bool,
) -> None:
    memory = ReplayMemory()
    memory.map_bytes(FEATURE, feature.to_bytes(4, "little"))
    memory.map_bytes(MASK_START, b"\xff" * 28 + bytes(28), writable=False)
    first = 0x2000
    values = list(range(1, count + 1))
    if hit and count:
        values[count // 2] = 99
    if count:
        memory.map_bytes(first, struct.pack(f"<{count}I", *values))
    expected = first + (values.index(99) if 99 in values else count) * 4
    assert invoke(bound(memory), 0x142D6A0D0, (first, first + 4 * count, 99)) == expected


@pytest.mark.parametrize("feature,count", [(4, 4), (0x20, 8)])
def test_vector_find_reads_whole_operand_before_first_match(feature: int, count: int) -> None:
    memory = ReplayMemory()
    memory.map_bytes(FEATURE, feature.to_bytes(4, "little"))
    first = memory.allocate(count * 4)
    memory.write(first, 4, 99)
    with pytest.raises(ReplayMemoryError):
        find_replay_task_class(storage(memory), first, first + count * 4, 99)
    memory.write(FEATURE, 4, 0)
    assert find_replay_task_class(storage(memory), first, first + count * 4, 99) == first


def test_empty_find_still_requires_current_feature_word() -> None:
    memory = ReplayMemory()
    with pytest.raises(ReplayMemoryError):
        find_replay_task_class(storage(memory), 0, 0, 0)
    memory.map_bytes(FEATURE, bytes(4))
    assert find_replay_task_class(storage(memory), 0, 0, 0) == 0


@pytest.mark.parametrize("mask,offset", [(0x80000000, 3), (0x00800000, 2), (0, 4)])
def test_current_noncanonical_mask_preserves_raw_byte_match_bits(mask: int, offset: int) -> None:
    memory = ReplayMemory()
    memory.map_bytes(FEATURE, (0x20).to_bytes(4, "little"))
    memory.map_bytes(0x14365D54C, mask.to_bytes(32, "little"))
    memory.map_bytes(0x2000, struct.pack("<8I", *([1] * 8)) + bytes(4))
    assert find_replay_task_class(storage(memory), 0x2000, 0x2024, 0) == 0x2020 + offset


@pytest.mark.parametrize(
    "target,width,expected",
    [
        (0x1412A57E0, 4, 0x8000),
        (0x1412A56C0, 2, 0xFFFF8000),
    ],
)
def test_append_grows_real_storage_and_reads_value_after_allocator(
    target: int,
    width: int,
    expected: int,
) -> None:
    memory = ReplayMemory()
    header, old = vector(memory, 4, 1, 1)
    initial = memory.read_bytes(old, 4)
    source = memory.allocate(width)  # Undefined until the actual allocator callback.
    actual = memory.runtime_calls()

    def call(entry: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        assert actual.call is not None
        result = actual.call(entry, args, data)
        if entry == 0x1402A94D0:
            memory.write(source, width, 0x8000)
        return result

    inserted = invoke(bound(memory, ReplayTaskRebuildCalls(call)), target, (header, source))
    begin = memory.read(header, 8)
    assert inserted == begin + 4
    assert memory.read_bytes(begin, 4) == initial
    assert memory.read(begin + 4, 4) == expected
    assert memory.read(header + 8, 8) == memory.read(header + 16, 8) == begin + 8
    with pytest.raises(ReplayMemoryError, match="unmapped"):
        memory.read(old, 1)


@pytest.mark.parametrize("target,width", [(0x1412A57E0, 4), (0x1412A56C0, 2)])
def test_fast_append_returns_reread_end_after_destination_alias(target: int, width: int) -> None:
    memory = ReplayMemory()
    memory.map_bytes(0x1000, struct.pack("<3Q", 0, 0x1008, 0x100C))
    memory.map_bytes(0x2000, (0x1234).to_bytes(width, "little"))
    assert invoke(bound(memory), target, (0x1000, 0x2000)) == 0x1234
    assert memory.read(0x1008, 8) == 0x1238


@pytest.mark.parametrize("stride,target", [(40, 0x1412A3CA0), (48, 0x1412A3AB0)])
def test_middle_row_insertion_moves_both_sides_and_releases_old(
    stride: int,
    target: int,
) -> None:
    memory = ReplayMemory()
    header, old = vector(memory, stride, 3, 3)
    previous = memory.read_bytes(old, stride * 3)
    source = memory.allocate(stride)
    raw = bytes(range(stride))
    memory.write_bytes(source, raw)
    inserted = invoke(bound(memory), target, (header, old + stride, source))
    begin = memory.read(header, 8)
    assert inserted == begin + stride
    assert memory.read_bytes(begin, stride * 4) == previous[:stride] + raw + previous[stride:]
    assert memory.read(header + 8, 8) == memory.read(header + 16, 8) == begin + stride * 4
    with pytest.raises(ReplayMemoryError, match="unmapped"):
        memory.read(old, 1)


@pytest.mark.parametrize("stride,target", [(40, 0x1412A3CA0), (48, 0x1412A3AB0)])
def test_row_chunk_copy_observes_alias_from_previous_wide_store(stride: int, target: int) -> None:
    memory = ReplayMemory()
    header, _ = vector(memory, stride)
    source = memory.allocate(stride + 8)
    original = bytes(range(stride + 8))
    memory.write_bytes(source, original)
    actual = memory.runtime_calls()

    def call(entry: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        if entry == 0x1402A94D0:
            return source + 8  # Explicit real backed allocation/source alias.
        assert actual.call is not None
        return actual.call(entry, args, data)

    result = invoke(bound(memory, ReplayTaskRebuildCalls(call)), target, (header, 0, source))
    expected = original[:16] + original[8:16] + original[24:32] + original[24:32]
    if stride == 48:
        expected += original[40:48]
    assert result == source + 8
    assert memory.read_bytes(source + 8, stride) == expected


@pytest.mark.parametrize("stride,target", [(40, 0x1412A3CA0), (48, 0x1412A3AB0)])
def test_late_source_failure_retains_first_two_record_chunks(stride: int, target: int) -> None:
    memory = ReplayMemory()
    header, old = vector(memory, stride, 1, 1)
    source = memory.allocate(stride)
    memory.write_bytes(source, bytes(range(32)))
    actual, allocated = memory.runtime_calls(), []

    def call(entry: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        assert actual.call is not None
        result = actual.call(entry, args, data)
        if entry == 0x1402A94D0:
            allocated.append(result)
        return result

    with pytest.raises(ReplayMemoryError):
        invoke(bound(memory, ReplayTaskRebuildCalls(call)), target, (header, old + stride, source))
    assert len(allocated) == 1 and allocated[0] is not None
    assert memory.read_bytes(allocated[0] + stride, 32) == bytes(range(32))
    assert memory.read(header, 8) == old and memory.read(header + 8, 8) == old + stride


@pytest.mark.parametrize("stride,target", [(40, 0x1412A3CA0), (48, 0x1412A3AB0)])
def test_free_callback_cannot_replace_held_new_header_values(stride: int, target: int) -> None:
    memory = ReplayMemory()
    header, old = vector(memory, stride, 1, 1)
    source = memory.allocate(stride)
    memory.write_bytes(source, bytes(stride))
    actual = memory.runtime_calls()

    def call(entry: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        assert actual.call is not None
        result = actual.call(entry, args, data)
        if entry == 0x142D6BAB4:
            for offset in (0, 8, 16):
                memory.write(header + offset, 8, 0xDEAD)
        return result

    inserted = invoke(
        bound(memory, ReplayTaskRebuildCalls(call)), target, (header, old + stride, source)
    )
    begin = memory.read(header, 8)
    assert inserted == begin + stride and begin != 0xDEAD
    assert memory.read(header + 8, 8) == memory.read(header + 16, 8) == begin + 2 * stride


def test_live_input_and_truthy_mapping_exit_cannot_hide_body_failure() -> None:
    memory = ReplayMemory()
    header, _ = vector(memory, 40)
    phases = []
    failure = RuntimeError("actual allocator failure")

    def call(target: int, args: tuple[int, ...], data: memoryview | None) -> int:
        assert target == 0x1402A94D0 and args == (40,) and data is None
        raise failure

    data = memoryview(bytearray(range(40)))

    def local(view: memoryview):
        assert view is data
        actual = memory.bind_local(view)

        class Manager:
            def __enter__(self) -> int:
                phases.append("enter")
                return actual.__enter__()

            def __exit__(self, kind, error, traceback) -> bool:
                assert error is failure
                phases.append("exit")
                actual.__exit__(kind, error, traceback)
                return True

        return Manager()

    calls = bind_replay_task_rows(storage(memory), ReplayTaskRebuildCalls(call), bind_local=local)
    with pytest.raises(RuntimeError) as caught:
        invoke(calls, 0x1412A3CA0, (header, 0), data)
    assert caught.value is failure and phases == ["enter", "exit"]
    memory.snapshot()  # Actual scoped mapping has ended, even on the truthy exit.


@pytest.mark.parametrize("width,target", [(4, 0x1412A57E0), (40, 0x1412A3CA0), (48, 0x1412A3AB0)])
def test_actual_live_view_observes_allocator_mutation(width: int, target: int) -> None:
    memory = ReplayMemory()
    header, _ = vector(memory, width)
    data = memoryview(bytearray(range(width)))
    actual = memory.runtime_calls()

    def call(entry: int, args: tuple[int, ...], view: memoryview | None) -> int | None:
        assert actual.call is not None
        result = actual.call(entry, args, view)
        if entry == 0x1402A94D0:
            data[0] = 0xC3
        return result

    args = (header,) if width == 4 else (header, 0)
    inserted = invoke(bound(memory, ReplayTaskRebuildCalls(call)), target, args, data)
    assert inserted and memory.read_bytes(inserted, width) == bytes(data)
    assert data[0] == 0xC3
    memory.snapshot()


@pytest.mark.parametrize("missing_slot", [False, True])
def test_large_release_uses_current_watson_and_never_commits_on_failure(missing_slot: bool) -> None:
    memory = ReplayMemory()
    header, old = vector(memory, 4, 1, 1024)
    memory.write(old - 8, 8, old - 40)  # Invalid raw allocation gap32.
    if not missing_slot:
        memory.map_bytes(0x14319A060, (0xCAFE).to_bytes(8, "little"))
    seen = []

    def call(entry: int, args: tuple[int, ...], data: memoryview | None) -> None:
        seen.append((entry, args, data))

    expected = ReplayMemoryError if missing_slot else RuntimeError
    with pytest.raises(expected):
        invoke(bound(memory, ReplayTaskRebuildCalls(call)), 0x1402BA840, (header, 0xBEEF, 2, 3))
    assert seen == ([] if missing_slot else [(0xCAFE, (0, 0, 0, 0, 0), None)])
    assert memory.read(header, 8) == old
    assert memory.read(header + 8, 8) == old + 4
    assert memory.read(header + 16, 8) == old + 4096


def fresh_map(memory: ReplayMemory, header: int, node_size: int) -> int:
    head, buckets = memory.allocate(node_size), memory.allocate_aligned(128)
    memory.write(header, 4, 0x3F800000)
    for offset, value in (
        (8, head),
        (16, 0),
        (24, buckets),
        (32, buckets + 128),
        (40, buckets + 128),
        (48, 7),
        (56, 8),
    ):
        memory.write(header + offset, 8, value)
    memory.write(head, 8, head)
    memory.write(head + 8, 8, head)
    for i in range(16):
        memory.write(buckets + 8 * i, 8, head)
    return head


def run_initial_rules(memory: ReplayMemory, subject: int, task_list: int, out: int) -> None:
    actual = memory.runtime_calls()

    def runtime(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        assert actual.call is not None
        return actual.call(0x142D6E453 if target == 0x7FF010001000 else target, args, data)

    context = storage(memory, subject)
    calls = bind_replay_task_execution(
        context,
        ReplayTaskRebuildCalls(runtime),
        bind_local=memory.bind_local,
        pair_out=out,
        byte_out=out + 16,
        mxcsr=0x1F80,
        prefix_scratch=ReplayTaskPrefixScratch(bytes(range(64)), b"abc", b"xyz"),
    )
    run_replay_task_rebuild(
        context,
        task_list,
        mxcsr=0x1F80,
        calls=calls,
        scratch=ReplayTaskRebuildScratch(bytes(range(48)), b"abc", b"xyz"),
    )


def test_actual_fifteen_rule_graph_with_constructed_tasks_cleanup_and_snapshot() -> None:
    memory = ReplayMemory()
    subject = memory.allocate(0x900)
    # Explicit fresh task-facet fields from the retained Combat/Unit constructors.
    # Other subject fields stay undefined; this fixture is not a restored World.
    for offset in (0x530, 0x538, 0x540, 0x730, 0x738, 0x740, 0x7A8, 0x7B0, 0x7B8):
        memory.write(subject + offset, 8, 0)
    for offset in (0x548, 0x5D8):
        fresh_map(memory, subject + offset, 32)
    head = fresh_map(memory, subject + 0x6E0, 120)
    memory.map_bytes(FEATURE, bytes(4))
    memory.map_bytes(0x143199EF0, (0x7FF010001000).to_bytes(8, "little"))
    memory.map_bytes(0x1436A0308, (0x5F000000).to_bytes(4, "little"), writable=False)
    constructors = bind_replay_task_construction(storage(memory, subject), memory.runtime_calls())
    task_list = invoke(constructors, 0x141323AE0, (0,))
    assert task_list
    selectors = [0, 4, 6, 12, 13, 22, 36, 44, 47, 54, 55, 19, 20, 21, 2]
    pointers = memory.allocate_aligned(8 * len(selectors))
    for index, selector in enumerate(selectors):
        task = invoke(constructors, 0x1412691B0, (task_list, 1, index))
        assert task
        for offset, width, value in (
            (0xE, 2, 155),
            (0x10, 2, selector),
            (0x12, 2, 0xFFFF),
            (0x15, 1, 4),
            (0x18, 1, 1),
            (0x2C, 4, 0x3F800000),
        ):
            memory.write(task + offset, width, value)
        memory.write(pointers + index * 8, 8, task)
    for offset, value in ((8, pointers), (16, pointers + 120), (24, pointers + 120)):
        memory.write(task_list + offset, 8, value)
    out = memory.allocate(32)
    run_initial_rules(memory, subject, task_list, out)
    rules = memory.read(subject + 0x730, 8)
    assert memory.read(subject + 0x738, 8) == rules + 600
    assert [memory.read(rules + i * 40, 4) for i in range(15)] == [900 + i for i in selectors]
    assert all(memory.read(rules + i * 40 + 12, 4) == 0x3F800000 for i in range(15))
    group = memory.read(head, 8)
    classes = memory.read(group + 0x60, 8)
    assert list(struct.unpack("<15I", memory.read_bytes(classes, 60))) == selectors
    criterion_head = memory.read(group + 0x28, 8)
    criterion = memory.read(criterion_head, 8)
    indices = memory.read(criterion + 0x28, 8)
    assert list(struct.unpack("<15I", memory.read_bytes(indices, 60))) == list(range(15))
    saved = memory.snapshot()
    run_initial_rules(memory, subject, task_list, out)
    assert memory.read(subject + 0x730, 8) == rules  # Retained row allocation/capacity.
    assert memory.read(head, 8) != group  # Real group/criterion cleanup and reconstruction.
    with pytest.raises(ReplayMemoryError, match="unmapped"):
        memory.read(group, 1)
    restored = ReplayMemory.from_snapshot(saved)
    run_initial_rules(restored, subject, task_list, out)
    assert restored.snapshot() == memory.snapshot()
