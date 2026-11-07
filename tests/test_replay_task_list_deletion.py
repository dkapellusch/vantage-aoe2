"""Real task/vector/list ownership through the complete deleting call graph."""

from __future__ import annotations

import pytest

from vantage.replay_memory import ReplayMemory, ReplayMemoryError
from vantage.replay_task_construction import bind_replay_task_construction
from vantage.replay_task_list_deletion import bind_replay_task_list_deletion
from vantage.replay_task_list_storage import bind_replay_task_list_storage
from vantage.replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
)


def bind(
    memory: ReplayMemory,
    lower: ReplayTaskRebuildCalls | None = None,
) -> ReplayTaskRebuildCalls:
    context = ReplayTaskRebuildStorage(1, memory.read, memory.write)
    return bind_replay_task_list_deletion(
        context,
        bind_replay_task_list_storage(
            context,
            bind_replay_task_construction(
                context, lower if lower is not None else memory.runtime_calls()
            ),
        ),
    )


def invoke(calls: ReplayTaskRebuildCalls, target: int, *args: int) -> int | None:
    assert calls.call is not None
    return calls.call(target, args, None)


def setup(memory: ReplayMemory, *, derived: bool, count: int = 2) -> tuple[int, int]:
    # Explicit engine primitive identities, separate from native DLL bindings.
    for iat, target in (
        (0x143199DD0, 0x142D6BAB4),
        (0x143199938, 0x142D6E3B7),
        (0x1431999A0, 0x142D6E3DB),
    ):
        memory.map_bytes(iat, target.to_bytes(8, "little"))
    calls = bind(memory)
    task_list = invoke(calls, 0x141323AE0 if derived else 0x14116BA60, 0)
    assert task_list
    with memory.bind_local(memoryview(bytearray(8))) as zero:
        invoke(calls, 0x141268370, task_list + 8, count, zero)
    return task_list, memory.read(task_list + 8, 8)


@pytest.mark.parametrize("derived", [False, True])
@pytest.mark.parametrize("flags", [0, 1, 2, 0xFFFFFFFF, 1 << 32])
def test_deleting_wrappers_release_real_tasks_vector_and_optional_list(
    derived: bool,
    flags: int,
) -> None:
    memory = ReplayMemory()
    task_list, pointers = setup(memory, derived=derived)
    calls = bind(memory)
    tasks = [invoke(calls, 0x1412691B0, task_list, 1, i) for i in range(2)]
    for i, task in enumerate(tasks):
        assert task
        memory.write(pointers + i * 8, 8, task)
    # The selected current vtable is backed with verified original slot0 bytes.
    table = memory.read(task_list, 8)
    entry = 0x141320510 if derived else 0x141268D80
    memory.map_bytes(table, entry.to_bytes(8, "little"), writable=False)
    assert invoke(calls, memory.read(table, 8), task_list, flags) == task_list
    for task in tasks:
        assert task
        with pytest.raises(ReplayMemoryError, match="unmapped"):
            memory.read(task, 1)
    with pytest.raises(ReplayMemoryError, match="unmapped"):
        memory.read(pointers, 1)
    if flags & 1:
        with pytest.raises(ReplayMemoryError, match="unmapped"):
            memory.read(task_list, 1)
        assert not any(r.owned for r in memory.snapshot().regions)
    else:
        assert memory.read(task_list, 8) == 0x1432B5EE8
        assert memory.read_bytes(task_list + 8, 24) == bytes(24)


def test_null_vector_release_does_not_read_or_normalize_unknown_tail() -> None:
    memory = ReplayMemory()
    vector = memory.allocate(24)
    memory.write(vector, 8, 0)
    invoke(bind(memory), 0x1412686F0, vector)
    with pytest.raises(ReplayMemoryError, match="undefined"):
        memory.read(vector + 8, 8)
    memory.write(vector + 8, 8, 0x1234)
    memory.write(vector + 16, 8, 0x5678)
    invoke(bind(memory), 0x1412686F0, vector)
    assert memory.read(vector + 8, 8) == 0x1234
    assert memory.read(vector + 16, 8) == 0x5678


def test_destructor_base_vptr_store_survives_later_clear_read_failure() -> None:
    memory = ReplayMemory()
    task_list = memory.allocate(32)
    memory.write(task_list, 8, 0x1432BC398)
    with pytest.raises(ReplayMemoryError, match="undefined"):
        invoke(bind(memory), 0x141320510, task_list, 1)
    assert memory.read(task_list, 8) == 0x1432B5EE8


def test_vector_release_free_failure_retains_prior_clear_and_prevents_list_free() -> None:
    memory = ReplayMemory()
    task_list, pointers = setup(memory, derived=True)
    reached = []

    def fail(target: int, args: tuple[int, ...], data: memoryview | None) -> None:
        reached.append((target, args))
        assert target == 0x142D6BAB4 and args == (pointers, 16) and data is None
        assert memory.read(task_list, 8) == 0x1432B5EE8
        assert memory.read(task_list + 16, 8) == pointers
        raise OSError("vector free failed")

    with pytest.raises(OSError, match="vector free failed"):
        invoke(bind(memory, ReplayTaskRebuildCalls(fail)), 0x141320510, task_list, 1)
    assert reached == [(0x142D6BAB4, (pointers, 16))]
    assert memory.read(task_list + 8, 8) == pointers
    assert memory.read(task_list + 24, 8) == pointers + 16


def test_list_free_failure_follows_successful_vector_reset() -> None:
    memory = ReplayMemory()
    task_list, pointers = setup(memory, derived=True)

    def free(target: int, args: tuple[int, ...], data: memoryview | None) -> None:
        assert target == 0x142D6BAB4 and data is None
        if args[0] == pointers:
            memory.free(pointers)
        else:
            assert args == (task_list, 32)
            assert memory.read_bytes(task_list + 8, 24) == bytes(24)
            raise OSError("list free failed")

    with pytest.raises(OSError, match="list free failed"):
        invoke(bind(memory, ReplayTaskRebuildCalls(free)), 0x141320510, task_list, 1)
    assert memory.read(task_list, 8) == 0x1432B5EE8


def test_large_vector_release_uses_owned_aligned_allocation_base() -> None:
    memory = ReplayMemory()
    task_list, pointers = setup(memory, derived=True, count=512)
    raw = memory.read(pointers - 8, 8)
    assert pointers % 32 == 0 and raw != pointers
    assert invoke(bind(memory), 0x141320510, task_list, 0) == task_list
    assert memory.read_bytes(task_list + 8, 24) == bytes(24)
    with pytest.raises(ReplayMemoryError, match="unmapped"):
        memory.read(raw, 1)


def test_invalid_large_metadata_reads_current_watson_and_never_resets_header() -> None:
    memory = ReplayMemory()
    task_list, pointers = setup(memory, derived=True, count=512)
    memory.write(pointers - 8, 8, pointers - 40)
    memory.map_bytes(0x14319A060, (0xF004).to_bytes(8, "little"))

    def watson(target: int, args: tuple[int, ...], data: memoryview | None) -> None:
        assert target == 0xF004 and args == (0, 0, 0, 0, 0) and data is None

    with pytest.raises(RuntimeError, match="unexpectedly returned"):
        invoke(bind(memory, ReplayTaskRebuildCalls(watson)), 0x141320510, task_list, 1)
    assert memory.read(task_list + 8, 8) == pointers
    assert memory.read(task_list + 16, 8) == pointers  # Clear completed before release failed.
    assert memory.read(task_list + 24, 8) == pointers + 4096


def test_snapshot_continuation_repeats_deleting_ownership_effects() -> None:
    memory = ReplayMemory()
    task_list, pointers = setup(memory, derived=True)
    task = invoke(bind(memory), 0x1412691B0, task_list, 1, 0)
    assert task
    memory.write(pointers, 8, task)
    restored = ReplayMemory.from_snapshot(memory.snapshot())
    assert invoke(bind(memory), 0x141320510, task_list, 1) == task_list
    assert invoke(bind(restored), 0x141320510, task_list, 1) == task_list
    assert memory.snapshot() == restored.snapshot()


@pytest.mark.parametrize("target", [0x1412686F0, 0x141268760, 0x141320510, 0x141268D80])
def test_malformed_known_entry_has_no_effects(target: int) -> None:
    memory = ReplayMemory()
    before = memory.snapshot()
    with pytest.raises(ValueError, match="malformed"):
        invoke(bind(memory), target)
    assert memory.snapshot() == before


def test_unknown_entry_delegates_or_refuses_at_reach() -> None:
    memory = ReplayMemory()
    context = ReplayTaskRebuildStorage(1, memory.read, memory.write)
    calls = bind_replay_task_list_deletion(context, ReplayTaskRebuildCalls(None))
    with pytest.raises(UnresolvedReplayTaskRebuild, match="beef"):
        invoke(calls, 0xBEEF)
