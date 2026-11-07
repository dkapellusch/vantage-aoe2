"""Actual owned TaskList lifetime, live pointer fill and current import effects."""

from __future__ import annotations

import pytest

from vantage.replay_memory import ReplayMemory, ReplayMemoryError
from vantage.replay_task_construction import bind_replay_task_construction
from vantage.replay_task_list_storage import bind_replay_task_list_storage
from vantage.replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
)


def context(memory: ReplayMemory) -> ReplayTaskRebuildStorage:
    return ReplayTaskRebuildStorage(1, memory.read, memory.write)


def imports(memory: ReplayMemory) -> None:
    # Explicit engine primitive identities, not observed native DLL addresses.
    for address, target in (
        (0x143199938, 0x142D6E3B7),
        (0x1431999A0, 0x142D6E3DB),
        (0x143199DD0, 0x142D6BAB4),
    ):
        memory.map_bytes(address, target.to_bytes(8, "little"))


def bound(
    memory: ReplayMemory,
    lower: ReplayTaskRebuildCalls | None = None,
) -> ReplayTaskRebuildCalls:
    return bind_replay_task_list_storage(
        context(memory),
        bind_replay_task_construction(
            context(memory), lower if lower is not None else memory.runtime_calls()
        ),
    )


def invoke(calls: ReplayTaskRebuildCalls, target: int, *args: int) -> int | None:
    assert calls.call is not None
    return calls.call(target, args, None)


def word(memory: ReplayMemory, address: int) -> int:
    return memory.read(address, 8)


def vector(memory: ReplayMemory, begin: int, length: int, capacity: int) -> int:
    header = memory.allocate(24)
    for offset, value in ((0, begin), (8, begin + length * 8), (16, begin + capacity * 8)):
        memory.write(header + offset, 8, value)
    return header


def test_real_factory_resize_shrink_clear_preserves_distinct_task_and_list_lifetimes() -> None:
    memory = ReplayMemory()
    imports(memory)
    calls = bound(memory)
    task_list = invoke(calls, 0x141323AE0, 0)
    assert task_list is not None and word(memory, task_list) == 0x1432BC398
    first = invoke(calls, 0x1412691B0, task_list, 1, 0)
    second = invoke(calls, 0x1412691B0, task_list, 1, 1)
    assert first and second and first != second
    with memory.bind_local(memoryview(bytearray(8))) as zero:
        invoke(calls, 0x141268370, task_list + 8, 2, zero)
    pointers = word(memory, task_list + 8)
    assert memory.read_bytes(pointers, 16) == bytes(16)
    memory.write(pointers, 8, first)
    memory.write(pointers + 8, 8, second)
    invoke(calls, 0x141268370, task_list + 8, 1, 0xBAD)
    assert word(memory, second) == 0x1432A4EF8  # Shrink does not destroy tasks.
    invoke(calls, 0x141269220, task_list)
    with pytest.raises(ReplayMemoryError, match="unmapped"):
        word(memory, first)
    assert word(memory, second) == 0x1432A4EF8
    assert word(memory, pointers) == 0 and word(memory, pointers + 8) == second
    assert word(memory, task_list + 16) == pointers
    assert word(memory, task_list + 24) == pointers + 16
    memory.free(second)


@pytest.mark.parametrize("desired", [1, 2])
def test_shrink_equal_do_not_read_unbacked_capacity_fill_or_task_slots(desired: int) -> None:
    memory = ReplayMemory()
    header = memory.allocate(16)
    memory.write(header, 8, 0x1000)
    memory.write(header + 8, 8, 0x1010)
    invoke(bound(memory), 0x141268370, header, desired, 0xBAD)
    assert word(memory, header + 8) == 0x1000 + desired * 8


def test_fill_reads_actual_qword_and_rereads_source_after_overlapping_store() -> None:
    memory = ReplayMemory()
    source = memory.allocate(28)
    memory.write(source, 8, 0x1122334455667788)
    assert invoke(bound(memory), 0x1412684D0, source + 4, 3, source, 0xBAD) == source + 28
    assert word(memory, source + 4) == 0x1122334455667788
    assert word(memory, source + 12) == word(memory, source + 20) == 0x5566778855667788
    partial = memory.allocate(8)
    memory.write(partial, 4, 0)
    with pytest.raises(ReplayMemoryError, match="undefined"):
        invoke(bound(memory), 0x1412684D0, 0xBAD, 0, partial)


def test_zero_count_still_reads_source_and_reaches_current_memset_import() -> None:
    memory = ReplayMemory()
    source = memory.allocate(8)
    memory.write(source, 8, 0)
    with pytest.raises(ReplayMemoryError, match="unmapped"):
        invoke(bound(memory), 0x1412684D0, 0xBAD, 0, source)
    imports(memory)
    assert invoke(bound(memory), 0x1412684D0, 0xBAD, 0, source) == 0xBAD
    memory.write(source, 8, 7)
    assert invoke(bound(memory), 0x1412684D0, 0xBAD, 0, source) == 0xBAD


def test_growth_uses_real_aligned_allocation_then_releases_old_large_backing() -> None:
    memory = ReplayMemory()
    imports(memory)
    header = vector(memory, 0, 0, 0)
    calls = bound(memory)
    with memory.bind_local(memoryview(bytearray(8))) as zero:
        invoke(calls, 0x141268370, header, 512, zero)
        old = word(memory, header)
        old_raw = word(memory, old - 8)
        assert old % 32 == 0 and memory.read_bytes(old, 4096) == bytes(4096)
        memory.write(old, 8, 0xBEEF)
        invoke(calls, 0x141268370, header, 513, zero)
    new = word(memory, header)
    assert new != old and word(memory, new) == 0xBEEF
    assert word(memory, header + 8) == new + 513 * 8
    assert word(memory, header + 16) == new + 768 * 8
    assert memory.read_bytes(new + 8, 512 * 8) == bytes(512 * 8)
    with pytest.raises(ReplayMemoryError, match="undefined"):
        memory.read(new + 513 * 8, 1)
    with pytest.raises(ReplayMemoryError, match="unmapped"):
        word(memory, old_raw)


def test_allocator_changes_fill_and_current_move_import_before_reached_reads() -> None:
    memory = ReplayMemory()
    imports(memory)
    header = vector(memory, 0, 0, 0)
    source = memory.allocate(8)
    memory.write(source, 8, 0)
    runtime = memory.runtime_calls()
    seen = []

    def lower(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        seen.append(target)
        if target == 0x1402A94D0:
            memory.write(source, 8, 0xFEDCBA9876543210)
            memory.write(0x1431999A0, 8, 0xF103)
        if target == 0xF103:
            return memory.move(*args)
        assert runtime.call is not None
        return runtime.call(target, args, data)

    invoke(bound(memory, ReplayTaskRebuildCalls(lower)), 0x141268370, header, 2, source)
    assert memory.read_bytes(word(memory, header), 16) == bytes.fromhex("1032547698badcfe") * 2
    assert seen == [0x1402A94D0, 0xF103]


def test_unknown_fill_refuses_after_real_allocation_without_header_commit() -> None:
    memory = ReplayMemory()
    header = vector(memory, 0, 0, 0)
    source = memory.allocate(8)
    before = memory.snapshot()
    with pytest.raises(ReplayMemoryError, match="undefined"):
        invoke(bound(memory), 0x141268370, header, 1, source)
    after = memory.snapshot()
    assert len(after.regions) == len(before.regions) + 1
    assert word(memory, header) == word(memory, header + 8) == word(memory, header + 16) == 0
    assert after.regions[-1].defined == bytes(8)


def test_clear_free_exception_keeps_direct_destructor_and_slot_before_zero() -> None:
    memory = ReplayMemory()
    imports(memory)
    calls = bound(memory)
    task = invoke(calls, 0x1412691B0, 0, 1, 0)
    task_list = invoke(calls, 0x14116BA60, 0)
    assert task and task_list
    memory.write(task, 8, 0xBAD)
    pointers = memory.allocate(8)
    memory.write(pointers, 8, task)
    for offset, value in ((8, pointers), (16, pointers + 8), (24, pointers + 8)):
        memory.write(task_list + offset, 8, value)

    def fail(target: int, args: tuple[int, ...], data: memoryview | None) -> None:
        assert target == 0x142D6BAB4 and args == (task, 0x90) and data is None
        assert word(memory, task) == 0x1432A4EF8
        raise OSError("free failed")

    with pytest.raises(OSError, match="free failed"):
        invoke(bound(memory, ReplayTaskRebuildCalls(fail)), 0x141269220, task_list)
    assert word(memory, pointers) == task and word(memory, task_list + 16) == pointers + 8


def test_clear_follows_current_begin_after_free_and_keeps_old_slot() -> None:
    memory = ReplayMemory()
    imports(memory)
    calls = bound(memory)
    task_list = invoke(calls, 0x14116BA60, 0)
    task = invoke(calls, 0x1412691B0, 0, 1, 0)
    assert task_list and task
    old, new = memory.allocate(16), memory.allocate(8)
    memory.write(old, 8, task)
    memory.write(old + 8, 8, 0xBAD)
    memory.write(new, 8, 0xBEEF)
    for offset, value in ((8, old), (16, old + 16), (24, old + 16)):
        memory.write(task_list + offset, 8, value)

    def free_redirect(target: int, args: tuple[int, ...], data: memoryview | None) -> None:
        assert target == 0x142D6BAB4 and args == (task, 0x90) and data is None
        memory.free(task)
        memory.write(task_list + 8, 8, new)
        memory.write(task_list + 16, 8, new + 8)

    invoke(bound(memory, ReplayTaskRebuildCalls(free_redirect)), 0x141269220, task_list)
    assert word(memory, old) == task and word(memory, old + 8) == 0xBAD
    assert word(memory, new) == 0 and word(memory, task_list + 16) == new


def test_clear_preserves_signed16_stop_at_32768_slots() -> None:
    memory = ReplayMemory()
    pointers = memory.allocate(32769 * 8)
    memory.fill(pointers, 0, 32768 * 8)
    memory.write(pointers + 32768 * 8, 8, 0xBAD)
    task_list = memory.allocate(24)
    memory.write(task_list + 8, 8, pointers)
    memory.write(task_list + 16, 8, pointers + 32769 * 8)
    invoke(bound(memory), 0x141269220, task_list)
    assert word(memory, task_list + 16) == pointers
    assert word(memory, pointers + 32768 * 8) == 0xBAD


@pytest.mark.parametrize("gap", [31, 32])
def test_large_release_checks_current_backpointer_and_watson_before_commit(gap: int) -> None:
    memory = ReplayMemory()
    imports(memory)
    raw = memory.allocate(64)
    old = raw + 8 + gap
    memory.write(old - 8, 8, raw)
    header = vector(memory, old, 0, 512)
    if gap == 31:
        invoke(bound(memory), 0x141268DD0, header, 0x100, 2, 3)
        assert word(memory, header) == 0x100
        with pytest.raises(ReplayMemoryError, match="unmapped"):
            word(memory, raw)
    else:
        memory.map_bytes(0x14319A060, (0xF004).to_bytes(8, "little"))

        def watson(target: int, args: tuple[int, ...], data: memoryview | None) -> None:
            assert target == 0xF004 and args == (0, 0, 0, 0, 0) and data is None

        with pytest.raises(RuntimeError, match="unexpectedly returned"):
            invoke(bound(memory, ReplayTaskRebuildCalls(watson)), 0x141268DD0, header, 0x100, 2, 3)
        assert word(memory, header) == old and word(memory, header + 16) == old + 4096


def test_commit_free_callback_cannot_replace_held_new_header_words() -> None:
    memory = ReplayMemory()
    imports(memory)
    old = memory.allocate(8)
    header = vector(memory, old, 1, 1)

    def free(target: int, args: tuple[int, ...], data: memoryview | None) -> None:
        assert target == 0x142D6BAB4 and args == (old, 8) and data is None
        memory.free(old)
        memory.fill(header, 0xA5, 24)

    invoke(bound(memory, ReplayTaskRebuildCalls(free)), 0x141268DD0, header, 0x1000, 2, 4)
    assert [word(memory, header + i) for i in (0, 8, 16)] == [0x1000, 0x1010, 0x1020]


def test_snapshot_continuation_preserves_actual_owned_task_clear() -> None:
    memory = ReplayMemory()
    imports(memory)
    calls = bound(memory)
    task_list = invoke(calls, 0x14116BA60, 0)
    task = invoke(calls, 0x1412691B0, 0, 1, 9)
    assert task_list and task
    with memory.bind_local(memoryview(bytearray(task.to_bytes(8, "little")))) as value:
        invoke(calls, 0x141268370, task_list + 8, 1, value)
    restored = ReplayMemory.from_snapshot(memory.snapshot())
    invoke(calls, 0x141269220, task_list)
    invoke(bound(restored), 0x141269220, task_list)
    assert memory.snapshot() == restored.snapshot()


@pytest.mark.parametrize(
    "target,args",
    [
        (0x141269220, ()),
        (0x141268DD0, (1, 2, 3)),
        (0x141268370, (1, 2)),
        (0x14112AAD0, (1, 2)),
        (0x1412684D0, (1, 2)),
        (0x142D6E3B7, (1, 2)),
        (0x142D6E3DB, (1, 2)),
        (0x142D6BAB4, (1,)),
    ],
)
def test_malformed_known_calls_fail_without_effects(target: int, args: tuple[int, ...]) -> None:
    memory = ReplayMemory()
    before = memory.snapshot()
    with pytest.raises(ValueError, match="malformed"):
        invoke(bound(memory), target, *args)
    assert memory.snapshot() == before


def test_resolved_unknown_import_and_unknown_entry_refuse_without_fabricated_success() -> None:
    memory = ReplayMemory()
    memory.map_bytes(0x143199938, (0xBAD).to_bytes(8, "little"))
    source = memory.allocate(8)
    memory.write(source, 8, 0)
    calls = bind_replay_task_list_storage(context(memory), ReplayTaskRebuildCalls(None))
    with pytest.raises(UnresolvedReplayTaskRebuild, match="bad"):
        invoke(calls, 0x1412684D0, 0x123, 0, source)
    with pytest.raises(UnresolvedReplayTaskRebuild, match="beef"):
        invoke(calls, 0xBEEF)
