"""Task effects through actual Python-owned memory and runtime helper bindings.

Constructed layouts are explicit inputs, not restored World/native observations.
"""

from __future__ import annotations

import struct
from collections.abc import Callable

import pytest

from vantage.replay_memory import ReplayMemory, ReplayMemoryError, ReplayMemoryRuntimeError
from vantage.replay_task_effects import (
    append_replay_task_default,
    bind_replay_task_effects,
    bind_replay_task_execution,
    build_replay_task_default,
    clear_replay_task_groups,
    grow_replay_task_vector16,
    set_replay_task_marker,
)
from vantage.replay_task_prefix import ReplayTaskPrefixScratch
from vantage.replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildScratch,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
    run_replay_task_rebuild,
)

U64 = (1 << 64) - 1
MASTER_ADD = 0x6A586EB28AC201FC + 0x0CF19788B2554E70


def initialized(memory: ReplayMemory, size: int) -> int:
    address = memory.allocate(size)
    memory.write_bytes(address, bytes(size))
    return address


def resource_word(word: int) -> int:
    return (
        (((word ^ 0xA9834B738A7DD167) + 0x042AC42976FCCEF5) & U64)
        ^ 0x6AE24D3352F04511
        ^ 0xC22D6B496D833977
    )


class Fixture:
    def __init__(self) -> None:
        self.memory = ReplayMemory()
        self.subject = initialized(self.memory, 0x900)
        self.context = ReplayTaskRebuildStorage(self.subject, self.memory.read, self.memory.write)
        self.calls = self.memory.runtime_calls()

    def vector(self, records: list[bytes], capacity: int) -> int:
        header = initialized(self.memory, 24)
        begin = self.memory.allocate_aligned(capacity * 16)
        for index, record in enumerate(records):
            self.memory.write_bytes(begin + index * 16, record)
        for offset, value in (
            (0, begin),
            (8, begin + 16 * len(records)),
            (16, begin + 16 * capacity),
        ):
            self.memory.write(header + offset, 8, value)
        return header

    def default_task(
        self,
        *,
        selector: int,
        fallback: int = 0,
        kind: int = 5,
        resource: int = 0,
        amount: int = 0x80000000,
    ) -> int:
        task = initialized(self.memory, 0x100)
        for offset, width, value in (
            (0xE, 2, 164),
            (0x10, 2, selector & 0xFFFF),
            (0x12, 2, fallback & 0xFFFF),
            (0x24, 2, kind & 0xFFFF),
            (0x22, 2, resource & 0xFFFF),
            (0x28, 4, amount),
        ):
            self.memory.write(task + offset, width, value)
        return task

    def owner_and_vtable(self, resource_values: tuple[int, ...] = (0x7FA12345, 0x80000000)) -> int:
        owner, table, vtable = (initialized(self.memory, size) for size in (0xA0, 32, 0x828))
        self.memory.write(self.subject + 0x18, 8, owner)
        self.memory.write(owner + 0x98, 8, table)
        for index, value in enumerate(resource_values):
            self.memory.write(table + index * 8, 8, resource_word(value))
        self.memory.write(self.subject, 8, vtable)
        self.memory.write(vtable + 0x820, 8, 0x141138EF0)
        return vtable


@pytest.mark.parametrize("value", [0, 1, 0x100, 0x1FF, U64])
def test_marker_stores_only_dl(value: int) -> None:
    fixture = Fixture()
    set_replay_task_marker(fixture.context, value)
    assert fixture.memory.read(fixture.subject + 0x2CA, 1) == value & 255


@pytest.mark.parametrize(
    ("selector", "fallback", "expected"),
    [
        (-1, -7, -7),
        (-999, 0, -99),
        (2, 0, 902),
        (32767, 0, 33667),
    ],
)
def test_builder_dispatches_complete_raw_record_to_current_virtual(
    selector: int,
    fallback: int,
    expected: int,
) -> None:
    fixture = Fixture()
    vtable = fixture.owner_and_vtable()
    fixture.memory.write(vtable + 0x820, 8, 0xCAFE)
    task = fixture.default_task(selector=selector, fallback=fallback, kind=-2)
    seen = []

    def call(target: int, args: tuple[int, ...], data: memoryview | None) -> None:
        assert data is not None
        seen.append((target, args, bytes(data)))
        data[0] = 1

    build_replay_task_default(fixture.context, task, calls=ReplayTaskRebuildCalls(call))
    expected_record = struct.pack("<iiII", -2, expected, 0x80000000, 0x7FA12345)
    assert seen == [(0xCAFE, (fixture.subject,), expected_record)]


def test_fast_append_snapshots_overlap_and_rereads_end_after_header_alias_store() -> None:
    fixture = Fixture()
    vector = fixture.subject + 0x448
    source = initialized(fixture.memory, 16)
    fixture.memory.write_bytes(source, struct.pack("<QQ", 0x1234, 0x5678))
    fixture.memory.write(vector + 8, 8, vector + 8)
    fixture.memory.write(vector + 16, 8, 0x9999)
    append_replay_task_default(fixture.context, source, calls=fixture.calls)
    assert fixture.memory.read(vector + 8, 8) == 0x1244
    assert fixture.memory.read(vector + 16, 8) == 0x5678


def test_growth_in_middle_copies_aliased_descriptor_and_releases_old_owned_buffer() -> None:
    fixture = Fixture()
    records = [bytes([i]) * 16 for i in range(3)]
    vector = fixture.vector(records, 3)
    begin = fixture.memory.read(vector, 8)
    inserted = grow_replay_task_vector16(
        fixture.context, vector, begin + 16, begin + 32, calls=fixture.calls
    )
    new_begin = fixture.memory.read(vector, 8)
    assert inserted == new_begin + 16
    assert fixture.memory.read_bytes(new_begin, 64) == b"".join(
        (records[0], records[2], records[1], records[2])
    )
    assert fixture.memory.read(vector + 8, 8) == new_begin + 64
    with pytest.raises(ReplayMemoryError, match="unmapped"):
        fixture.memory.read(begin, 1)


def test_large_growth_uses_real_aligned_allocation_header_and_frees_previous_base() -> None:
    fixture = Fixture()
    record = b"abcdefghijklmnop"
    vector = fixture.vector([record] * 256, 256)
    old = fixture.memory.read(vector, 8)
    old_base = fixture.memory.read(old - 8, 8)
    source = initialized(fixture.memory, 16)
    fixture.memory.write_bytes(source, b"0123456789ABCDEF")
    result = grow_replay_task_vector16(
        fixture.context, vector, old + 4096, source, calls=fixture.calls
    )
    begin = fixture.memory.read(vector, 8)
    assert begin % 32 == 0 and result == begin + 4096
    assert fixture.memory.read(vector + 16, 8) == begin + 6144
    assert fixture.memory.read_bytes(begin, 4112) == record * 256 + b"0123456789ABCDEF"
    with pytest.raises(ReplayMemoryError, match="owned"):
        fixture.memory.free(old_base)


def test_growth_reads_descriptor_after_actual_allocation_callback() -> None:
    fixture = Fixture()
    source = initialized(fixture.memory, 16)
    fixture.memory.write_bytes(source, b"a" * 16)
    base = fixture.calls.call
    assert base is not None

    def call(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        result = base(target, args, data)
        if target == 0x1402A94D0:
            fixture.memory.write_bytes(source, b"B" * 16)
        return result

    append_replay_task_default(fixture.context, source, calls=ReplayTaskRebuildCalls(call))
    begin = fixture.memory.read(fixture.subject + 0x448, 8)
    assert fixture.memory.read_bytes(begin, 16) == b"B" * 16


def test_split_growth_rereads_end_after_prefix_move_without_inventing_unwritten_tail() -> None:
    fixture = Fixture()
    records = [bytes([i]) * 16 for i in range(3)]
    vector = fixture.vector(records, 3)
    begin = fixture.memory.read(vector, 8)
    source = initialized(fixture.memory, 16)
    fixture.memory.write_bytes(source, b"X" * 16)
    base = fixture.calls.call
    assert base is not None
    moves = []

    def call(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        result = base(target, args, data)
        if target == 0x142D6E3DB:
            moves.append(args)
            if len(moves) == 1:
                fixture.memory.write(vector + 8, 8, begin + 32)
        return result

    grow_replay_task_vector16(
        fixture.context, vector, begin + 16, source, calls=ReplayTaskRebuildCalls(call)
    )
    current = fixture.memory.read(vector, 8)
    assert moves == [(current, begin, 16), (current + 32, begin + 16, 16)]
    assert fixture.memory.read_bytes(current, 48) == records[0] + b"X" * 16 + records[1]
    assert fixture.memory.read(vector + 8, 8) == current + 64
    with pytest.raises(ReplayMemoryError, match="undefined"):
        fixture.memory.read_bytes(current + 48, 16)


def test_invalid_growth_count_reaches_real_error_before_descriptor_read() -> None:
    fixture = Fixture()
    vector = fixture.vector([], 0)
    fixture.memory.write(vector + 8, 8, U64 - 31)
    before = fixture.memory.snapshot()
    with pytest.raises(ReplayMemoryRuntimeError) as caught:
        grow_replay_task_vector16(fixture.context, vector, 0, 0, calls=fixture.calls)
    assert caught.value.target == 0x1402A9460
    assert fixture.memory.snapshot() == before


def test_group_count_zero_needs_no_sentinel_or_other_header_bytes() -> None:
    memory = ReplayMemory()
    memory.map_bytes(0x10010, bytes(8))
    reads = []

    def read(address: int, width: int) -> int:
        reads.append((address, width))
        return memory.read(address, width)

    context = ReplayTaskRebuildStorage(0x10000, read, memory.write)
    clear_replay_task_groups(context, 0x10000, calls=memory.runtime_calls())
    assert reads == [(0x10010, 8)]


def test_nonempty_group_clear_refuses_unknown_destructor_after_real_detach() -> None:
    fixture = Fixture()
    group, head, node = (initialized(fixture.memory, size) for size in (64, 32, 120))
    for address, value in (
        (group + 8, head),
        (group + 16, 1),
        (head, node),
        (head + 8, node),
        (node, head),
        (node + 8, head),
    ):
        fixture.memory.write(address, 8, value)
    with pytest.raises(UnresolvedReplayTaskRebuild, match="1402bd6f0"):
        clear_replay_task_groups(fixture.context, group, calls=fixture.calls)
    assert fixture.memory.read(node, 8) == 0
    assert fixture.memory.read(group + 16, 8) == 1
    assert fixture.memory.read(head, 8) == node


def configure_execution_fixture() -> tuple[Fixture, int, int, int]:
    fixture = Fixture()
    memory, subject = fixture.memory, fixture.subject
    fixture.owner_and_vtable()
    master = initialized(memory, 0x300)
    memory.write(master + 0x1FC, 1, 7)
    memory.write(subject + 0x10, 8, (master + MASTER_ADD) & U64)
    memory.map_bytes(0x1436A0308, (0x5F000000).to_bytes(4, "little"), writable=False)
    memory.map_bytes(0x1432A70C0, bytes((1, 2, 4, 8)), writable=False)
    for offset in (0x548, 0x5D8):
        header = subject + offset
        head, table = initialized(memory, 32), memory.allocate_aligned(16)
        memory.write(header, 4, 0x3E000000)
        for member, value in (
            (8, head),
            (0x10, 0),
            (0x18, table),
            (0x20, table + 16),
            (0x28, table + 16),
            (0x30, 0),
            (0x38, 1),
        ):
            memory.write(header + member, 8, value)
        for address, value in ((head, head), (head + 8, head), (table, head), (table + 8, head)):
            memory.write(address, 8, value)
    health = memory.allocate_aligned(96)
    for member, value in ((0x7A8, health), (0x7B0, health + 48), (0x7B8, health + 96)):
        memory.write(subject + member, 8, value)
    tasks = [initialized(memory, 0x100) for _ in range(5)]
    for task, kind in zip(tasks, (3, 6, 157, 162, 158), strict=True):
        memory.write(task + 0xE, 2, kind)
    memory.write(tasks[0] + 0x10, 2, 3)
    memory.write(tasks[1] + 0x30, 4, 0x3F800000)
    memory.write(tasks[1] + 0x1C, 4, 0x40000000)
    memory.write(tasks[2] + 0x36, 2, 3)
    memory.write(tasks[2] + 0x1C, 4, 0x41200000)
    memory.write(tasks[3] + 0x15, 1, 1)
    memory.write(tasks[3] + 0x28, 4, 0x3F800000)
    memory.write(tasks[4] + 0x28, 4, 0x40000000)
    tasks.extend(
        (
            fixture.default_task(selector=-1, fallback=7, kind=5, resource=1),
            fixture.default_task(selector=2, kind=-2, resource=0, amount=0x3F800000),
        )
    )
    task_array = initialized(memory, len(tasks) * 8)
    for index, task in enumerate(tasks):
        memory.write(task_array + index * 8, 8, task)
    task_list = initialized(memory, 24)
    memory.write(task_list + 8, 8, task_array)
    memory.write(task_list + 16, 8, task_array + len(tasks) * 8)
    return fixture, task_list, initialized(memory, 9), initialized(memory, 9)


def executor(fixture: Fixture, pair_out: int, byte_out: int) -> Callable[[int], None]:
    calls = bind_replay_task_execution(
        fixture.context,
        fixture.memory.runtime_calls(),
        bind_local=fixture.memory.bind_local,
        pair_out=pair_out,
        byte_out=byte_out,
        mxcsr=0x1F80,
        prefix_scratch=ReplayTaskPrefixScratch(bytes(range(64)), b"abc", b"xyz"),
    )

    def run(task_list: int) -> None:
        run_replay_task_rebuild(
            fixture.context,
            task_list,
            mxcsr=0x1F80,
            calls=calls,
            scratch=ReplayTaskRebuildScratch(bytes(range(48)), b"abc", b"xyz"),
        )

    return run


def test_full_outer_rebuild_uses_actual_memory_prefix_maps_records_and_runtime_leaves() -> None:
    fixture, task_list, pair_out, byte_out = configure_execution_fixture()
    memory, subject = fixture.memory, fixture.subject
    run = executor(fixture, pair_out, byte_out)
    run(task_list)
    assert memory.read(subject + 0x2CA, 1) == 1
    assert memory.read(subject + 0x80C, 4) == 0x3F800000
    assert memory.read(subject + 0x810, 4) == 0x40000000
    for offset in (0x548, 0x5D8):
        assert memory.read(subject + offset + 0x10, 8) == 1
        assert memory.read(subject + offset + 0x38, 8) == 8
    rules = memory.read(subject + 0x530, 8)
    assert memory.read(subject + 0x538, 8) == rules + 64
    defaults = memory.read(subject + 0x448, 8)
    expected = struct.pack("<iiII", 5, 7, 0x80000000, 0x80000000)
    expected += struct.pack("<iiII", -2, 902, 0x3F800000, 0x7FA12345)
    assert memory.read_bytes(defaults, 32) == expected
    health = memory.read(subject + 0x7A8, 8)
    assert memory.read(subject + 0x7B0, 8) == health + 48
    assert memory.read(health, 4) == 2
    assert memory.read_bytes(health + 13, 3) == bytes((13, 14, 15))
    run(task_list)  # Real clear/free/fill and retained default-vector chronology.
    defaults = memory.read(subject + 0x448, 8)
    assert memory.read_bytes(defaults, 64) == expected * 2
    assert memory.read(subject + 0x450, 8) == defaults + 64
    run(0)
    assert memory.read(subject + 0x538, 8) == memory.read(subject + 0x530, 8)
    assert memory.read(subject + 0x7B0, 8) == health
    assert memory.read(subject + 0x450, 8) == defaults + 64


def test_full_rebuild_is_deterministic_after_memory_snapshot_restore() -> None:
    original, task_list, pair_out, byte_out = configure_execution_fixture()
    snapshot = original.memory.snapshot()
    executor(original, pair_out, byte_out)(task_list)
    restored = Fixture()
    restored.memory = ReplayMemory.from_snapshot(snapshot)
    restored.subject = original.subject
    restored.context = ReplayTaskRebuildStorage(
        restored.subject, restored.memory.read, restored.memory.write
    )
    executor(restored, pair_out, byte_out)(task_list)
    assert restored.memory.snapshot() == original.memory.snapshot()


def test_effect_adapter_does_not_replace_unknown_current_virtual_target() -> None:
    fixture = Fixture()
    vtable = fixture.owner_and_vtable()
    fixture.memory.write(vtable + 0x820, 8, 0xBADC0DE)
    task = fixture.default_task(selector=1)
    calls = bind_replay_task_effects(
        fixture.context, fixture.calls, bind_local=fixture.memory.bind_local
    )
    with pytest.raises(UnresolvedReplayTaskRebuild, match="badc0de"):
        build_replay_task_default(fixture.context, task, calls=calls)
    assert fixture.memory.read(fixture.subject + 0x450, 8) == 0
