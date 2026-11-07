"""Saved Result lifetime, current storage and real owned allocation effects."""

from __future__ import annotations

import pytest

from vantage.replay_memory import ReplayMemory, ReplayMemoryError
from vantage.replay_saved_result import (
    bind_replay_saved_result,
    clear_replay_saved_result_vector,
    finalize_replay_saved_result,
)
from vantage.replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
)
from vantage.replay_unit_ai_map import ReplayUnitAIMapAtomics


def storage(memory, read=None):
    return ReplayTaskRebuildStorage(1, memory.read if read is None else read, memory.write)


def atomics(memory):
    return ReplayUnitAIMapAtomics(memory.compare_exchange_u32, memory.fetch_add_u32)


def result(memory, begin=0, end=0, capacity=0, control=0):
    address = memory.allocate(48)
    memory.write_bytes(address, bytes(range(48)))
    for offset, value in ((0, begin), (8, end), (16, capacity), (32, control)):
        memory.write(address + offset, 8, value)
    return address


def invoke(bound, target, *args):
    assert bound.call is not None
    return bound.call(target, args, None)


def test_null_vector_reads_only_begin_and_preserves_all_result_bytes() -> None:
    memory = ReplayMemory()
    address = result(memory, end=0xBAD, capacity=0xCAFE)
    original = memory.read_bytes(address, 48)
    reads = []

    def read(pointer, width):
        reads.append((pointer, width))
        return memory.read(pointer, width)

    clear_replay_saved_result_vector(
        storage(memory, read), address, calls=ReplayTaskRebuildCalls(None)
    )
    assert reads == [(address, 8)]
    assert memory.read_bytes(address, 48) == original


@pytest.mark.parametrize("capacity", [32, 4096])
def test_nonnull_empty_vector_frees_real_small_or_aligned_backing(capacity) -> None:
    memory = ReplayMemory()
    allocation = memory.allocate_aligned(capacity)
    address = result(memory, allocation, allocation, allocation + capacity)
    tail = memory.read_bytes(address + 24, 24)
    clear_replay_saved_result_vector(storage(memory), address, calls=memory.runtime_calls())
    assert memory.read_bytes(address, 24) == bytes(24)
    assert memory.read_bytes(address + 24, 24) == tail
    with pytest.raises(ReplayMemoryError, match="unmapped"):
        memory.read(allocation, 1)


@pytest.mark.parametrize(
    ("entry", "element"),
    [(0x1402BD7F0, 0x1402A88A0), (0x1402BD890, 0x1402A88A0), (0x140900620, 0x1402A8920)],
)
def test_current_headers_are_reloaded_after_held_range_elements(entry, element) -> None:
    memory = ReplayMemory()
    old, replacement = memory.allocate_aligned(64), memory.allocate_aligned(96)
    address = result(memory, old, old + 64, old + 64)
    memory.map_bytes(0x143199DD0, (0x142D6BAB4).to_bytes(8, "little"))
    seen = []
    runtime = memory.runtime_calls()

    def call(target, args, data):
        seen.append((target, args))
        if target == element:
            # The first cleanup replaces all headers. The next entry must
            # still belong to the original captured range, not the replacement.
            if args == (old,):
                for offset, value in ((0, replacement), (8, replacement), (16, replacement + 96)):
                    memory.write(address + offset, 8, value)
            return None
        assert runtime.call is not None
        return runtime.call(target, args, data)

    effects = ReplayTaskRebuildCalls(call)
    bound = bind_replay_saved_result(
        storage(memory), effects, atomics=atomics(memory), imports=effects
    )
    assert invoke(bound, entry, address) is None
    assert seen == [(element, (old,)), (element, (old + 32,)), (0x142D6BAB4, (replacement, 96))]
    assert memory.read_bytes(address, 24) == bytes(24)
    with pytest.raises(ReplayMemoryError, match="unmapped"):
        memory.read(replacement, 1)
    memory.write(old, 1, 0xAB)
    assert memory.read(old, 1) == 0xAB


def test_finalize_holds_control_reloads_its_vtable_and_reads_vector_after_dispose() -> None:
    memory = ReplayMemory()
    control, other, table, replacement_table = (memory.allocate(16) for _ in range(4))
    allocation = memory.allocate_aligned(32)
    address = result(memory, control=control)
    for pointer, value in ((control, table), (table, 0xD1), (replacement_table + 8, 0xD2)):
        memory.write(pointer, 8, value)
    memory.write(control + 8, 4, 1)
    memory.write(control + 12, 4, 1)
    seen = []
    original_tail = memory.read_bytes(address + 24, 8) + memory.read_bytes(address + 40, 8)
    runtime = memory.runtime_calls()

    def call(target, args, data):
        seen.append((target, args))
        if target == 0xD1:
            assert args == (control,)
            memory.write(address + 32, 8, other)
            memory.write(control, 8, replacement_table)
        elif target == 0xD2:
            assert args == (control,)
            for offset, value in ((0, allocation), (8, allocation), (16, allocation + 32)):
                memory.write(address + offset, 8, value)
        else:
            assert runtime.call is not None
            return runtime.call(target, args, data)
        return None

    finalize_replay_saved_result(
        storage(memory), address, calls=ReplayTaskRebuildCalls(call), atomics=atomics(memory)
    )
    assert seen == [(0xD1, (control,)), (0xD2, (control,)), (0x142D6BAB4, (allocation, 32))]
    assert memory.read(control + 8, 4) == memory.read(control + 12, 4) == 0
    assert memory.read(address + 32, 8) == other
    assert memory.read_bytes(address, 24) == bytes(24)
    assert memory.read_bytes(address + 24, 8) + memory.read_bytes(address + 40, 8) == original_tail


@pytest.mark.parametrize(
    ("strong", "weak", "expected"),
    [(2, 1, []), (0, 1, []), (1, 2, [0xD1]), (1, 0, [0xD1]), (1, 1, [0xD1, 0xD2])],
)
def test_control_counts_use_atomic_prior_values(strong, weak, expected) -> None:
    memory = ReplayMemory()
    control, table = memory.allocate(16), memory.allocate(16)
    address = result(memory, control=control)
    memory.write(control, 8, table)
    memory.write(table, 8, 0xD1)
    memory.write(table + 8, 8, 0xD2)
    memory.write(control + 8, 4, strong)
    memory.write(control + 12, 4, weak)
    seen = []
    finalize_replay_saved_result(
        storage(memory),
        address,
        calls=ReplayTaskRebuildCalls(lambda target, args, data: seen.append(target)),
        atomics=atomics(memory),
    )
    assert seen == expected
    assert memory.read(control + 8, 4) == (strong - 1) & 0xFFFFFFFF
    assert memory.read(control + 12, 4) == ((weak - 1) & 0xFFFFFFFF if strong == 1 else weak)


def test_missing_atomic_refuses_before_vector_access_or_stores() -> None:
    memory = ReplayMemory()
    address = result(memory, begin=0xBAD, control=0xCAFE)
    before = memory.snapshot()
    with pytest.raises(UnresolvedReplayTaskRebuild, match="atomic effect unavailable"):
        finalize_replay_saved_result(
            storage(memory),
            address,
            calls=ReplayTaskRebuildCalls(None),
            atomics=ReplayUnitAIMapAtomics(None, None),
        )
    assert memory.snapshot() == before


def test_missing_dispose_preserves_atomic_and_destroy_effects_before_vector() -> None:
    memory = ReplayMemory()
    control, table = memory.allocate(16), memory.allocate(16)
    address = result(memory, begin=0xBAD, control=control)
    memory.write(control, 8, table)
    memory.write(table, 8, 0xD1)
    memory.write(table + 8, 8, 0xD2)
    memory.write(control + 8, 4, 1)
    memory.write(control + 12, 4, 1)

    def call(target, args, data):
        if target == 0xD1:
            memory.write(address + 40, 1, 0xAC)
            return None
        raise UnresolvedReplayTaskRebuild(f"reached{target:x}")

    with pytest.raises(UnresolvedReplayTaskRebuild, match="d2"):
        finalize_replay_saved_result(
            storage(memory), address, calls=ReplayTaskRebuildCalls(call), atomics=atomics(memory)
        )
    assert memory.read(control + 8, 4) == memory.read(control + 12, 4) == 0
    assert memory.read(address, 8) == 0xBAD
    assert memory.read(address + 40, 1) == 0xAC


def test_unavailable_second_element_keeps_first_effect_and_headers() -> None:
    memory = ReplayMemory()
    allocation = memory.allocate_aligned(64)
    address = result(memory, allocation, allocation + 64, allocation + 64)
    before = memory.read_bytes(address, 48)

    def call(target, args, data):
        assert target == 0x1402A88A0
        if args == (allocation,):
            memory.write(allocation, 4, 0xDEAD)
            return None
        raise UnresolvedReplayTaskRebuild("second entry")

    with pytest.raises(UnresolvedReplayTaskRebuild, match="second entry"):
        clear_replay_saved_result_vector(
            storage(memory), address, calls=ReplayTaskRebuildCalls(call)
        )
    assert memory.read_bytes(address, 48) == before
    assert memory.read(allocation, 4) == 0xDEAD


@pytest.mark.parametrize("entry", [0x1402BD7F0, 0x140900620])
def test_watson_uses_current_terminal_import_without_entering_owned_alias(entry) -> None:
    memory = ReplayMemory()
    memory.map_bytes(0x1000, (0x10).to_bytes(8, "little"))
    address = result(memory, 0x1008, 0x1008, 0x2008)
    memory.map_bytes(0x14319A060, entry.to_bytes(8, "little"))
    before = memory.read_bytes(address, 48)
    seen = []
    bound = bind_replay_saved_result(
        storage(memory),
        ReplayTaskRebuildCalls(None),
        atomics=atomics(memory),
        imports=ReplayTaskRebuildCalls(
            lambda target, args, data: seen.append((target, args, data))
        ),
    )
    with pytest.raises(UnresolvedReplayTaskRebuild, match="Watson returned before INT3"):
        invoke(bound, entry, address)
    assert seen == [(entry, (0, 0, 0, 0, 0), None)]
    assert memory.read_bytes(address, 48) == before


def test_bound_free_reads_current_iat_once_and_preserves_terminal_return() -> None:
    memory = ReplayMemory()
    memory.map_bytes(0x143199DD0, (0x140900620).to_bytes(8, "little"))
    reads, seen = [], []

    def read(address, width):
        value = memory.read(address, width)
        reads.append((address, width))
        memory.write(0x143199DD0, 8, 0xBAD)
        return value

    def terminal(target, args, data):
        seen.append((target, args, data))
        return 0xCAFE

    bound = bind_replay_saved_result(
        storage(memory, read),
        ReplayTaskRebuildCalls(None),
        atomics=atomics(memory),
        imports=ReplayTaskRebuildCalls(terminal),
    )
    assert invoke(bound, 0x142D6BAB4, 0x100, 32) == 0xCAFE
    assert reads == [(0x143199DD0, 8)]
    assert seen == [(0x140900620, (0x100, 32), None)]


@pytest.mark.parametrize(
    ("target", "args", "data"),
    [
        (0x1402BD890, (), None),
        (0x140900620, (1, 2), None),
        (0x142D6BAB4, (1,), None),
        (0x1402BD7F0, (1,), memoryview(bytearray(1))),
        (0x1402BD7F0, (-1,), None),
    ],
)
def test_malformed_owned_calls_refuse_before_any_storage(target, args, data) -> None:
    def unavailable(*args):
        raise AssertionError("malformed call touched storage")

    bound = bind_replay_saved_result(
        ReplayTaskRebuildStorage(1, unavailable, unavailable),
        ReplayTaskRebuildCalls(None),
        atomics=ReplayUnitAIMapAtomics(None, None),
    )
    assert bound.call is not None
    with pytest.raises(ValueError):
        bound.call(target, args, data)


def test_unknown_call_retains_lower_dispatch_payload_and_result() -> None:
    memory = ReplayMemory()
    seen = []
    payload = memoryview(bytearray(b"input"))

    def call(target, args, data):
        seen.append((target, args, data))
        return 0xA1

    bound = bind_replay_saved_result(
        storage(memory), ReplayTaskRebuildCalls(call), atomics=atomics(memory)
    )
    assert bound.call is not None
    assert bound.call(0xB1, (3,), payload) == 0xA1
    assert seen == [(0xB1, (3,), payload)]
