"""Current storage, partial failures and callback order in common UnitAI setup."""

from __future__ import annotations

import pytest

from vantage.replay_memory import ReplayMemory, ReplayMemoryError
from vantage.replay_random_storage import bind_replay_random_storage
from vantage.replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
)
from vantage.replay_unit_ai_base import (
    assign_replay_unit_ai_classes,
    bind_replay_unit_ai_base,
    construct_replay_unit_ai_base,
    set_replay_unit_ai_retarget_timer,
)

U64 = (1 << 64) - 1


def context(memory: ReplayMemory) -> ReplayTaskRebuildStorage:
    return ReplayTaskRebuildStorage(1, memory.read, memory.write)


def inputs(memory: ReplayMemory) -> tuple[int, int, int]:
    ai, subject, master, table = (memory.allocate(n) for n in (528, 0x1F8, 0x40, 0x230))
    memory.write(subject, 8, table)
    memory.write(table + 0x228, 8, 0xFA000)
    memory.write(subject + 0x10, 8, (master + 0x6A586EB28AC201FC + 0xCF19788B2554E70) & U64)
    memory.write(master + 0x38, 8, (0x50A06BCECEBEF905 - 0x5B32AA7995D95916 - 7) & U64)
    for offset, raw in (
        (0x170, 0x183CAC30D2441D0E - 0x4C3FBA69E4EA7FD1 + 0x41200000),
        (0x178, 0x61501AA6ECFD980A - 0x6C5EAB60B426DD28 + 0x41A00000),
        (0x180, -0x2B3719EF44DE99FF - 0x21D14A25ED7C802C + 0x3F800000),
    ):
        memory.write(subject + offset, 8, raw & U64)
    return ai, subject, table


def test_unavailable_actual_random_stream_retains_prefix_and_does_not_read_subject() -> None:
    memory = ReplayMemory()
    ai = memory.allocate(528)
    current = context(memory)
    calls = bind_replay_unit_ai_base(
        current, bind_replay_random_storage(current, memory.runtime_calls())
    )
    assert calls.call is not None
    with pytest.raises(ReplayMemoryError, match="144353108"):
        calls.call(0x140D094C0, (ai, 0xDEAD, 10, 0), None)
    assert memory.read(ai, 8) == 0x14324B288
    assert memory.read(ai + 8, 8) == 0xDEAD
    assert memory.read(ai + 0x1C, 4) == 10
    assert memory.read(ai + 0xB0, 8) == ai + 0x78
    with pytest.raises(ReplayMemoryError, match="undefined"):
        memory.read(ai + 0xBC, 4)


def test_base_current_children_fields_arrays_padding_and_snapshot() -> None:
    memory = ReplayMemory()
    ai, subject, _ = inputs(memory)
    runtime = memory.runtime_calls()
    events = []
    draws = iter((1234, 2001, 888))
    previous = memory.allocate(16)

    def call(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        events.append((target, args))
        if target == 0x140903E40:
            assert args[0] == 0x1443530F0
            return next(draws)
        if target == 0xFA000:
            assert args == (subject,)
            memory.write(ai + 0xC0, 8, previous)
            return 0x40200000  # Effective raw XMM0 low word.
        if target == 0x14124DD50:
            return 0x12345678
        if target == 0x140C285F0:
            assert args[1:] == (0x41200000, 0x41A00000, 0x3F800000, 0x5678)
            for offset, width, value in (
                (12, 2, args[4]),
                (0, 4, args[1]),
                (4, 4, args[2]),
                (8, 4, args[3]),
            ):
                memory.write(args[0] + offset, width, value)
            return args[0]
        if target == 0x142D6BAB4:
            assert args == (previous, 16)
            assert memory.read(ai + 0xC0, 8) != previous
        assert runtime.call is not None
        return runtime.call(target, args, data)

    memory.map_bytes(0x143199DD0, (0x142D6BAB4).to_bytes(8, "little"))
    bound = bind_replay_unit_ai_base(context(memory), ReplayTaskRebuildCalls(call))
    assert bound.call is not None
    assert bound.call(0x140D094C0, (ai, subject, 0xDEAD00000002, 0xBEEF00000003), None) == ai
    assert memory.read(ai + 0x14, 4) == 0xFFFFFFF9
    assert memory.read(ai + 0x1F0, 4) == 3
    assert memory.read(ai + 0xBC, 4) == 234
    assert memory.read(ai + 0x194, 4) == 0x40200000
    assert memory.read(ai + 0x1B4, 8) == 0x41A0000041200000
    assert memory.read(ai + 0x16C, 4) == 2751
    assert memory.read(ai + 0x1D4, 4) == 1138
    assert [args[2] for target, args in events if target == 0x140903E40] == [0x184, 0x1A6C, 0x1A8B]
    assert [args for target, args in events if target == 0x142D6BA78] == [(16,), (104,), (48,)]
    records, slots = memory.read(ai + 0x20, 8), memory.read(ai + 0x30, 8)
    for index in range(2):
        assert memory.read(records + index * 52 + 4, 4) == 706
        assert memory.read(records + index * 52 + 44, 1) == 0
        assert memory.read(records + index * 52 + 48, 4) == 0xFFFFFFFF
        with pytest.raises(ReplayMemoryError, match="undefined"):
            memory.read(records + index * 52 + 45, 3)
    with pytest.raises(ReplayMemoryError, match="undefined"):
        memory.read(slots, 48)
    with pytest.raises(ReplayMemoryError, match="unmapped"):
        memory.read(previous, 1)
    clone = ReplayMemory.from_snapshot(memory.snapshot())
    assert clone.snapshot() == memory.snapshot()
    assert clone.read(ai + 0xC0, 8) == memory.read(ai + 0xC0, 8)


def test_current_counts_saturate_and_idle_divisor_failure_keeps_draw_effects() -> None:
    memory = ReplayMemory()
    ai, subject, _ = inputs(memory)
    sizes = []
    draws = []

    def call(target: int, args: tuple[int, ...], data: memoryview | None) -> int:
        if target == 0x140903E40:
            draws.append(args[2])
            memory.write(ai + 0xBC, 4, 0xCAFE)
            return 1
        if target == 0xFA000:
            memory.write(ai + 0x1C, 4, 0xFFFFFFFF)
            memory.write(ai + 0x170, 4, 1)
            return 0x3F800000
        if target == 0x142D6C268:
            sizes.append(args[0])
            memory.write(ai + 0x2C, 4, 0x80000000)
        return 0

    with pytest.raises(UnresolvedReplayTaskRebuild, match="divisor is zero"):
        construct_replay_unit_ai_base(
            context(memory), ai, subject, 2, 0, calls=ReplayTaskRebuildCalls(call)
        )
    assert sizes == [U64, U64] and draws == [0x184, 0x1A6C]
    assert memory.read(ai + 0xBC, 4) == 0xCAFE
    assert memory.read(ai + 0x20, 8) == memory.read(ai + 0x30, 8) == 0
    with pytest.raises(ReplayMemoryError, match="undefined"):
        memory.read(ai + 0x16C, 4)
    with pytest.raises(ReplayMemoryError, match="undefined"):
        memory.read(ai + 0x1D4, 4)


@pytest.mark.parametrize("length,requested", [(0, 0), (3, 2), (1, 3)])
def test_range_reuse_keeps_zero_moves_and_reads_current_second_destination(length, requested):
    memory = ReplayMemory()
    vector, source_header, destination, source, alternate = (
        memory.allocate(n) for n in (24, 16, 16, 16, 16)
    )
    memory.write_bytes(source, bytes(range(16)))
    for address, value in (
        (vector, destination),
        (vector + 8, destination + length * 4),
        (vector + 16, destination + 16),
        (source_header, source),
        (source_header + 8, source + requested * 4),
    ):
        memory.write(address, 8, value)
    moves = []

    def call(target: int, args: tuple[int, ...], data: memoryview | None) -> int:
        assert target == 0x142D6E3DB and data is None
        moves.append(args)
        result = memory.move(*args)
        if len(moves) == 1:
            memory.write(vector + 8, 8, alternate)
        return result

    assert (
        assign_replay_unit_ai_classes(
            context(memory), vector, source_header, calls=ReplayTaskRebuildCalls(call)
        )
        == vector
    )
    expected = [(destination, source, min(length, requested) * 4)]
    end = destination + requested * 4
    if length < requested:
        expected.append((alternate, source + length * 4, (requested - length) * 4))
        end = alternate + (requested - length) * 4
    assert moves == expected
    assert memory.read(vector + 8, 8) == end
    assert memory.read(vector + 16, 8) == destination + 16


def test_range_reserve_holds_source_and_reload_destination_before_last_commit() -> None:
    memory = ReplayMemory()
    vector, header, source, replacement = (memory.allocate(n) for n in (24, 16, 8, 8))
    memory.write_bytes(vector, bytes(24))
    memory.write_bytes(source, b"abcdefgh")
    memory.write(header, 8, source)
    memory.write(header + 8, 8, source + 8)
    calls_seen = []

    def call(target: int, args: tuple[int, ...], data: memoryview | None) -> int:
        calls_seen.append((target, args))
        if target == 0x1402BA470:
            assert args == (vector, 2)
            memory.write(vector, 8, replacement)
            memory.write(header, 8, 0xBAD)
            return 0
        assert args == (replacement, source, 8)
        result = memory.move(*args)
        memory.write(vector, 8, 0xCAFE)
        return result

    assign_replay_unit_ai_classes(
        context(memory), vector, header, calls=ReplayTaskRebuildCalls(call)
    )
    assert len(calls_seen) == 2 and memory.read_bytes(replacement, 8) == b"abcdefgh"
    assert memory.read(vector, 8) == 0xCAFE
    assert memory.read(vector + 8, 8) == replacement + 8


def test_timer_holds_vptr_reads_current_slot_and_forwards_raw_argument_and_return() -> None:
    memory = ReplayMemory()
    ai, old_table, new_table = (memory.allocate(n) for n in (528, 0x1B0, 0x1B0))
    memory.write(ai, 8, old_table)
    memory.write(old_table + 0x1A8, 8, 0xAA)
    seen = []

    def write(address: int, width: int, value: int) -> None:
        memory.write(address, width, value)
        if address == ai + 0x170:
            memory.write(ai, 8, new_table)
            memory.write(old_table + 0x1A8, 8, 0xBB)

    def call(target: int, args: tuple[int, ...], data: memoryview | None) -> int:
        seen.append((target, args, data))
        return 0xDEADBEEF

    current = ReplayTaskRebuildStorage(1, memory.read, write)
    raw_timeout = 0xDEADBEEF000003E8
    assert (
        set_replay_unit_ai_retarget_timer(
            current, ai, raw_timeout, calls=ReplayTaskRebuildCalls(call)
        )
        == 0xDEADBEEF
    )
    assert memory.read(ai + 0x170, 4) == 1000
    assert seen == [(0xBB, (ai, raw_timeout), None)]


def test_current_iat_tokens_delegate_once_without_same_token_recursion() -> None:
    memory = ReplayMemory()
    memory.map_bytes(0x1431999A0, (0x142D6E3DB).to_bytes(8, "little"))
    memory.map_bytes(0x143199DD0, (0x142D6BAB4).to_bytes(8, "little"))
    seen = []

    def call(target: int, args: tuple[int, ...], data: memoryview | None) -> int:
        seen.append((target, args, data))
        return 17

    bound = bind_replay_unit_ai_base(context(memory), ReplayTaskRebuildCalls(call))
    assert bound.call is not None
    assert bound.call(0x142D6E3DB, (1, 2, 0), None) == 17
    assert bound.call(0x142D6BAB4, (0, 16), None) == 17
    assert seen == [(0x142D6E3DB, (1, 2, 0), None), (0x142D6BAB4, (0, 16), None)]
