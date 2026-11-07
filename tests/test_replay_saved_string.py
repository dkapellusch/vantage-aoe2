"""Owned string allocation lifetime and actual Result element composition."""

from __future__ import annotations

import pytest

from vantage.replay_memory import ReplayMemory, ReplayMemoryError
from vantage.replay_saved_result import bind_replay_saved_result
from vantage.replay_saved_string import (
    bind_replay_saved_string,
    destroy_replay_saved_string,
)
from vantage.replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
)
from vantage.replay_unit_ai_map import ReplayUnitAIMapAtomics


def storage(memory, read=None):
    return ReplayTaskRebuildStorage(1, memory.read if read is None else read, memory.write)


@pytest.mark.parametrize("capacity", [0, 15])
def test_inline_string_reads_only_capacity_and_preserves_unused_union_bytes(capacity):
    memory = ReplayMemory()
    address = memory.allocate(32)
    memory.write_bytes(address, b"X" * 32)
    memory.write(address + 24, 8, capacity)
    reads = []

    def read(pointer, width):
        reads.append((pointer, width))
        return memory.read(pointer, width)

    destroy_replay_saved_string(storage(memory, read), address, calls=ReplayTaskRebuildCalls(None))
    assert reads == [(address + 24, 8)]
    assert memory.read_bytes(address, 16) == b"\0" + b"X" * 15
    assert memory.read(address + 16, 8) == 0 and memory.read(address + 24, 8) == 15


@pytest.mark.parametrize(
    ("capacity", "size"), [(16, 17), (4094, 4095), (4095, 4096), ((1 << 64) - 1, 32)]
)
def test_real_heap_small_aligned_and_wrapping_capacity_free(capacity, size):
    memory = ReplayMemory()
    data, address = memory.allocate_aligned(size), memory.allocate(32)
    memory.write(address, 8, data)
    memory.write(address + 24, 8, capacity)
    destroy_replay_saved_string(storage(memory), address, calls=memory.runtime_calls())
    with pytest.raises(ReplayMemoryError, match="unmapped"):
        memory.read(data, 1)
    assert memory.read(address, 1) == 0
    assert memory.read(address + 16, 8) == 0 and memory.read(address + 24, 8) == 15


def test_free_failure_preserves_original_string_header_and_prior_free_effect() -> None:
    memory = ReplayMemory()
    address, data = memory.allocate(32), memory.allocate(20)
    memory.write_bytes(address, b"X" * 32)
    memory.write(address, 8, data)
    memory.write(address + 24, 8, 19)
    before = memory.read_bytes(address, 32)

    def call(target, args, local):
        assert (target, args, local) == (0x142D6BAB4, (data, 20), None)
        memory.free(data)
        raise UnresolvedReplayTaskRebuild("after actual free")

    with pytest.raises(UnresolvedReplayTaskRebuild, match="after actual free"):
        destroy_replay_saved_string(storage(memory), address, calls=ReplayTaskRebuildCalls(call))
    assert memory.read_bytes(address, 32) == before
    with pytest.raises(ReplayMemoryError, match="unmapped"):
        memory.read(data, 1)


@pytest.mark.parametrize("vector_entry", [0x1402BD890, 0x140900620])
def test_result_destroys_actual_inline_and_heap_strings_then_frees_vector(vector_entry):
    memory = ReplayMemory()
    entries, string, result = (memory.allocate_aligned(size) for size in (64, 4096, 48))
    memory.write(entries + 24, 8, 15)
    memory.write(entries + 32, 8, string)
    memory.write(entries + 56, 8, 4095)
    memory.write_bytes(result, bytes(48))
    for offset, pointer in ((0, entries), (8, entries + 64), (16, entries + 64)):
        memory.write(result + offset, 8, pointer)
    memory.map_bytes(0x143199DD0, (0x142D6BAB4).to_bytes(8, "little"))
    runtime = memory.runtime_calls()
    freed = []

    def terminal(target, args, data):
        assert target == 0x142D6BAB4
        freed.append(args)
        assert runtime.call is not None
        return runtime.call(target, args, data)

    imports = ReplayTaskRebuildCalls(terminal)
    strings = bind_replay_saved_string(storage(memory), imports, imports=imports)
    bound = bind_replay_saved_result(
        storage(memory),
        strings,
        imports=imports,
        atomics=ReplayUnitAIMapAtomics(memory.compare_exchange_u32, memory.fetch_add_u32),
    )
    assert bound.call is not None
    assert bound.call(vector_entry, (result,), None) is None
    assert freed[0][1] == 4096 + 39 and freed[1] == (entries, 64)
    assert memory.read_bytes(result, 48) == bytes(48)
    with pytest.raises(ReplayMemoryError, match="unmapped"):
        memory.read(entries, 1)
    with pytest.raises(ReplayMemoryError, match="unmapped"):
        memory.read(string, 1)


def test_invalid_large_backpointer_calls_terminal_watson_before_any_reset() -> None:
    memory = ReplayMemory()
    address = memory.allocate(32)
    memory.write_bytes(address, b"X" * 32)
    memory.write(address, 8, 0x1008)
    memory.write(address + 24, 8, 4095)
    memory.map_bytes(0x1000, (0x10).to_bytes(8, "little"))
    memory.map_bytes(0x14319A060, (0x1402A88A0).to_bytes(8, "little"))
    before = memory.read_bytes(address, 32)
    seen = []
    bound = bind_replay_saved_string(
        storage(memory),
        ReplayTaskRebuildCalls(None),
        imports=ReplayTaskRebuildCalls(lambda target, args, data: seen.append((target, args))),
    )
    assert bound.call is not None
    with pytest.raises(UnresolvedReplayTaskRebuild, match="Watson returned before INT3"):
        bound.call(0x1402A8920, (address,), None)
    assert seen == [(0x1402A88A0, (0, 0, 0, 0, 0))]
    assert memory.read_bytes(address, 32) == before


def test_current_free_slot_is_held_across_read_hook_and_terminal_result_propagates() -> None:
    memory = ReplayMemory()
    memory.map_bytes(0x143199DD0, (0x1402A8920).to_bytes(8, "little"))
    seen = []

    def read(address, width):
        value = memory.read(address, width)
        memory.write(address, width, 0xBAD)
        return value

    def terminal(target, args, data):
        seen.append((target, args, data))
        return 0xD0

    bound = bind_replay_saved_string(
        storage(memory, read),
        ReplayTaskRebuildCalls(None),
        imports=ReplayTaskRebuildCalls(terminal),
    )
    assert bound.call is not None
    assert bound.call(0x142D6BAB4, (0x1000, 17), None) == 0xD0
    assert seen == [(0x1402A8920, (0x1000, 17), None)]
