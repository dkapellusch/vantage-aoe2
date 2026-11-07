"""Constructor leaves with current native hash/vector backing and raw float words."""

from __future__ import annotations

import pytest

from vantage.replay_memory import ReplayMemory, ReplayMemoryError
from vantage.replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
)
from vantage.replay_unit_ai_support import (
    apply_replay_object_stat,
    apply_replay_stat_record,
    bind_replay_unit_ai_support,
    construct_replay_ai_position,
    reserve_replay_ai_classes,
    update_replay_ai_idle_time,
)


def context(memory: ReplayMemory) -> ReplayTaskRebuildStorage:
    return ReplayTaskRebuildStorage(1, memory.read, memory.write)


def test_position_kind_first_and_unwritten_padding_survives() -> None:
    memory = ReplayMemory()
    address = memory.allocate(16)
    writes = []

    def write(at: int, width: int, value: int) -> None:
        writes.append((at - address, width, value))
        memory.write(at, width, value)

    current = ReplayTaskRebuildStorage(1, memory.read, write)
    assert (
        construct_replay_ai_position(
            current, address, 0x80000000, 0x7F812345, 0xFFC00001, 0xDEADBEEF
        )
        == address
    )
    assert writes == [(12, 2, 0xBEEF), (0, 4, 0x80000000), (4, 4, 0x7F812345), (8, 4, 0xFFC00001)]
    with pytest.raises(ReplayMemoryError, match="undefined"):
        memory.read(address + 14, 2)


def test_fresh_class_reserve_uses_real_aligned_allocator() -> None:
    memory = ReplayMemory()
    vector = memory.allocate(24)
    memory.write_bytes(vector, bytes(24))
    bound = bind_replay_unit_ai_support(context(memory), memory.runtime_calls())
    assert bound.call is not None
    assert bound.call(0x1402BA470, (vector, 42), None) is None
    begin = memory.read(vector, 8)
    assert begin and memory.read(vector + 8, 8) == begin
    assert memory.read(vector + 16, 8) == begin + 168
    with pytest.raises(ReplayMemoryError, match="undefined"):
        memory.read(begin, 168)


@pytest.mark.parametrize("failure", ["release", "allocation", None])
def test_reserve_old_release_precedes_clear_and_allocation_uses_held_growth(failure):
    memory = ReplayMemory()
    vector, old = (memory.allocate(n) for n in (24, 16))
    for offset, value in ((0, old), (8, old + 4), (16, old + 16)):
        memory.write(vector + offset, 8, value)
    events = []
    error = RuntimeError("leaf failure")

    def call(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        events.append((target, args))
        if target == 0x1402BD690:
            assert args == (vector, old)
            assert memory.read(vector, 8) == old
            if failure == "release":
                raise error
            memory.free(old)
            memory.write(vector + 16, 8, 0xFFFF)  # Must not change held growth6.
            return None
        assert target == 0x1402A94D0 and args == (24,)
        assert memory.read(vector, 24) == 0
        if failure == "allocation":
            raise error
        return memory.allocate_aligned(args[0])

    if failure:
        with pytest.raises(RuntimeError) as caught:
            reserve_replay_ai_classes(
                context(memory), vector, 5, calls=ReplayTaskRebuildCalls(call)
            )
        assert caught.value is error
        assert memory.read(vector, 8) == (old if failure == "release" else 0)
    else:
        reserve_replay_ai_classes(context(memory), vector, 5, calls=ReplayTaskRebuildCalls(call))
        assert memory.read(vector + 16, 8) == memory.read(vector, 8) + 24
    assert len(events) == (1 if failure == "release" else 2)


def test_oversize_class_count_calls_nonreturn_error_before_reading_headers() -> None:
    seen = []

    def call(target: int, args: tuple[int, ...], data: memoryview | None) -> None:
        seen.append((target, args, data))

    with pytest.raises(UnresolvedReplayTaskRebuild, match="nonreturning"):
        reserve_replay_ai_classes(
            context(ReplayMemory()), 0xDEAD, 1 << 62, calls=ReplayTaskRebuildCalls(call)
        )
    assert seen == [(0x1402BA950, (), None)]


@pytest.mark.parametrize("idle", [0, 1, 1000, 0xFFFFFFFF])
def test_idle_callback_holds_current_word_across_actual_required_draw(idle: int) -> None:
    memory = ReplayMemory()
    ai = memory.allocate(528)
    memory.write(ai + 0x170, 4, idle)
    seen = []

    def call(target: int, args: tuple[int, ...], data: memoryview | None) -> int:
        seen.append((target, args, data))
        memory.write(ai + 0x170, 4, 2000)
        return 0xFFFFFFFF

    if idle < 2:
        with pytest.raises(UnresolvedReplayTaskRebuild, match="divisor is zero"):
            update_replay_ai_idle_time(context(memory), ai, calls=ReplayTaskRebuildCalls(call))
        with pytest.raises(ReplayMemoryError, match="undefined"):
            memory.read(ai + 0x16C, 4)
    else:
        update_replay_ai_idle_time(context(memory), ai, calls=ReplayTaskRebuildCalls(call))
        assert (
            memory.read(ai + 0x16C, 4)
            == (0xFFFFFFFF % (idle >> 1) + ((idle * 3 & 0xFFFFFFFF) >> 2)) & 0xFFFFFFFF
        )
    assert seen == [(0x140903E40, (0x1443530F0, 0x14324D5B0, 0x1A6C), None)]
    assert memory.read(ai + 0x170, 4) == 2000


@pytest.mark.parametrize(
    "operation,amount,current,expected",
    [
        (1, 0x3F800000, 0x40000000, 0x40400000),
        (2, 0x40000000, 0x40400000, 0x40C00000),
        (3, 0x80000000, 0, 0),
        (4, 0, 0x80000000, 0x80000000),
        (3, 0x7F812345, 0x3F800000, 0x3F800000),
        (4, 0x3F800000, 0x7F812345, 0x7F812345),
        (3, 0x3F800000, 0x40000000, 0x3F800000),
        (4, 0x40000000, 0x3F800000, 0x40000000),
    ],
)
def test_stat_record_exact_raw_sse_operand_order(operation, amount, current, expected):
    memory = ReplayMemory()
    record = memory.allocate(12)
    memory.write(record, 4, operation)
    memory.write(record + 8, 4, amount)
    assert apply_replay_stat_record(context(memory), record, current) == expected
    with pytest.raises(ReplayMemoryError, match="undefined"):
        memory.read(record + 4, 4)


def test_unknown_stat_operation_preserves_signaling_nan_without_reading_amount() -> None:
    memory = ReplayMemory()
    memory.map_bytes(0x1000, (0xFFFFFFFF).to_bytes(4, "little"))
    assert apply_replay_stat_record(context(memory), 0x1000, 0x7F812345) == 0x7F812345


def test_building_getter_real_category_one_map_and_ordered_modifiers() -> None:
    memory = ReplayMemory()
    subject, master, buckets, node, records = (
        memory.allocate(n) for n in (0x760, 0x74, 16, 0x28, 24)
    )
    memory.write(
        subject + 0x10, 8, (master + 0x6A586EB28AC201FC + 0xCF19788B2554E70) & ((1 << 64) - 1)
    )
    memory.write(subject + 0x75C, 4, 0x3F800000)
    memory.write(master + 0x70, 4, 0x40000000)
    memory.write(subject + 0x300, 8, 0xDEAD)
    memory.write(subject + 0x310, 8, buckets)
    memory.write(subject + 0x328, 8, 0)
    memory.write(buckets, 8, node)
    memory.write(buckets + 8, 8, node)
    memory.write(node + 0x10, 4, 1)
    memory.write(node + 0x18, 8, records)
    memory.write(node + 0x20, 8, records + 24)
    for offset, value in ((0, 1), (8, 0x3F800000), (12, 2), (20, 0x40000000)):
        memory.write(records + offset, 4, value)
    bound = bind_replay_unit_ai_support(context(memory), ReplayTaskRebuildCalls(None))
    assert bound.call is not None
    assert bound.call(0x1412B6520, (subject,), None) == 0x41000000  # (1+2+1)*2.
    memory.write(node + 0x10, 4, 5)  # A real miss; no interpretation of undefined next pointer.
    assert bound.call(0x1412B6520, (subject,), None) == 0x40400000


def test_stat_hash_holds_bucket_terminal_and_modifier_end_across_mutations() -> None:
    memory = ReplayMemory()
    subject, buckets, first, last, records = (
        memory.allocate(n) for n in (0x330, 16, 0x28, 0x28, 24)
    )
    memory.write(subject + 0x300, 8, 0xDEAD)
    memory.write(subject + 0x310, 8, buckets)
    memory.write(subject + 0x328, 8, 0)
    memory.write(buckets, 8, last)
    memory.write(buckets + 8, 8, first)
    memory.write(first + 8, 8, last)
    memory.write(first + 0x10, 4, 2)
    memory.write(last + 0x10, 4, 1)
    memory.write(last + 0x18, 8, records)
    memory.write(last + 0x20, 8, records + 24)
    reads = []
    seen = []

    def read(address: int, width: int) -> int:
        reads.append((address, width))
        value = memory.read(address, width)
        if address == buckets:
            memory.write(subject + 0x310, 8, 0xBAD)
            memory.write(buckets, 8, first)
        return value

    def call(target: int, args: tuple[int, ...], data: memoryview | None) -> int:
        seen.append((target, args, data))
        memory.write(last + 0x20, 8, 0)
        return args[1] + 1

    current = ReplayTaskRebuildStorage(1, read, memory.write)
    assert (
        apply_replay_object_stat(
            current, subject, 0xDEAD00000001, 0, calls=ReplayTaskRebuildCalls(call)
        )
        == 2
    )
    assert reads.index((buckets, 8)) < reads.index((first + 0x10, 4))
    assert reads.count((subject + 0x310, 8)) == reads.count((buckets, 8)) == 1
    assert seen == [(0x1414C47E0, (records, 0), None), (0x1414C47E0, (records + 12, 1), None)]
