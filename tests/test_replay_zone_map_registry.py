"""Current shared registry scanning, output padding, allocation/growth failures."""

from __future__ import annotations

import pytest

from vantage.replay_memory import ReplayMemory, ReplayMemoryError
from vantage.replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
)
from vantage.replay_unit_ai_map import ReplayUnitAIMapAtomics
from vantage.replay_zone_map_registry import (
    acquire_replay_zone_map,
    bind_replay_zone_map_registry,
)


def context(memory):
    return ReplayTaskRebuildStorage(1, memory.read, memory.write)


def atomics(memory):
    return ReplayUnitAIMapAtomics(memory.compare_exchange_u32, memory.fetch_add_u32)


def inputs(memory, candidate, source):
    manager, pair, obj, control, vector, header, given, output = (
        memory.allocate(n)
        for n in (32, 16, 0x828, 16, max(1, len(candidate) * 4), 16, max(1, len(source) * 4), 24)
    )
    for address, value in (
        (manager, pair),
        (manager + 8, pair + 16),
        (pair, obj),
        (pair + 8, control),
        (obj + 0x818, vector),
        (obj + 0x820, vector + len(candidate) * 4),
        (header, given),
        (header + 8, given + len(source) * 4),
    ):
        memory.write(address, 8, value)
    memory.write(control + 8, 4, 1)
    for array, values in ((vector, candidate), (given, source)):
        for index, word in enumerate(values):
            memory.write(array + index * 4, 4, word)
    memory.write_bytes(output, b"\xa5" * 24)
    return manager, pair, obj, control, header, output


@pytest.mark.parametrize(
    "candidate,source",
    [
        ([], []),
        ([], [0x3F800000]),
        ([0x3F800000], [0x40000000, 0]),
        ([0x80000000, 0xBF800000, 0x7F812345], [0, 0xFFC00000, 0x80000001]),
    ],
)
def test_positivity_prefix_match_is_not_value_or_length_equality(candidate, source):
    memory = ReplayMemory()
    manager, _, obj, control, header, output = inputs(memory, candidate, source)
    assert (
        acquire_replay_zone_map(
            context(memory),
            manager,
            output,
            header,
            0x100,
            calls=ReplayTaskRebuildCalls(None),
            atomics=atomics(memory),
            bind_local=memory.bind_local,
        )
        == output
    )
    assert memory.read(output, 2) == 0
    assert memory.read_bytes(output + 2, 6) == b"\xa5" * 6
    assert memory.read(output + 8, 8) == obj
    assert memory.read(output + 16, 8) == control
    assert memory.read(control + 8, 4) == 2  # Registry and returned hold.


@pytest.mark.parametrize("candidate,source", [([0x3F800000], [0]), ([1, 1], [1])])
def test_mismatch_releases_candidate_then_new_allocation_stops_at_constructor(candidate, source):
    memory = ReplayMemory()
    manager, _, _, control, header, output = inputs(memory, candidate, source)
    memory.write(manager + 24, 8, 0xCAFE)
    allocated = []
    runtime = memory.runtime_calls()

    def call(target, args, data):
        assert runtime.call is not None
        if target == 0x1414EA4A0:
            assert args == (allocated[0] + 16, 0xCAFE, header)
        result = runtime.call(target, args, data)
        if target == 0x142D6BA78:
            allocated.append(result)
        return result

    with pytest.raises(UnresolvedReplayTaskRebuild, match="1414ea4a0"):
        acquire_replay_zone_map(
            context(memory),
            manager,
            output,
            header,
            0,
            calls=ReplayTaskRebuildCalls(call),
            atomics=atomics(memory),
            bind_local=memory.bind_local,
        )
    assert memory.read(control + 8, 4) == 1
    assert memory.read_bytes(output, 24) == b"\xa5" * 24
    assert memory.read(allocated[0], 8) == 0x1432D91C0
    assert memory.read(allocated[0] + 8, 4) == memory.read(allocated[0] + 12, 4) == 1
    with pytest.raises(ReplayMemoryError, match="undefined"):
        memory.read(allocated[0] + 16, 1)


def test_refresh_is_mandatory_and_precedes_output_publication() -> None:
    memory = ReplayMemory()
    manager, _, obj, control, header, output = inputs(memory, [], [])
    seen = []

    def call(target, args, data):
        seen.append((target, args, data))
        raise RuntimeError("refresh failed")

    with pytest.raises(RuntimeError, match="refresh failed"):
        acquire_replay_zone_map(
            context(memory),
            manager,
            output,
            header,
            1,
            calls=ReplayTaskRebuildCalls(call),
            atomics=atomics(memory),
            bind_local=memory.bind_local,
        )
    assert seen == [(0x1414EC840, (obj,), None)]
    assert memory.read(control + 8, 4) == 2  # Earlier acquired hold survives error.
    assert memory.read_bytes(output, 24) == b"\xa5" * 24


def test_null_allocation_retains_object_token16_and_appends_without_growth() -> None:
    memory = ReplayMemory()
    manager, storage, header, output = (memory.allocate(n) for n in (32, 16, 16, 24))
    for address, value in (
        (manager, storage),
        (manager + 8, storage),
        (manager + 16, storage + 16),
    ):
        memory.write(address, 8, value)
    memory.write_bytes(output, b"\xcc" * 24)
    calls = []

    def call(target, args, data):
        calls.append((target, args, data))
        return 0

    acquire_replay_zone_map(
        context(memory),
        manager,
        output,
        header,
        0,
        calls=ReplayTaskRebuildCalls(call),
        atomics=ReplayUnitAIMapAtomics(None, None),
        bind_local=memory.bind_local,
    )
    assert calls == [(0x142D6BA78, (0x868,), None)]
    assert memory.read(storage, 8) == memory.read(output + 8, 8) == 16
    assert memory.read(storage + 8, 8) == memory.read(output + 16, 8) == 0
    assert memory.read(output, 2) == 0 and memory.read(manager + 8, 8) == storage + 16
    assert memory.read_bytes(output + 2, 6) == b"\xcc" * 6


def test_growth_pair_remains_live_and_current_result_is_held_during_output_atomic() -> None:
    memory = ReplayMemory()
    manager, storage, header, output, control = (memory.allocate(n) for n in (32, 16, 16, 24, 16))
    for offset, value in ((0, storage), (8, storage), (16, storage)):
        memory.write(manager + offset, 8, value)
    memory.write(control + 8, 4, 2)
    locals_seen = []

    def call(target, args, data):
        if target == 0x142D6BA78:
            return 0
        assert target == 0x1414EA070 and args[:2] == (manager, storage)
        pair = args[2]
        locals_seen.append(pair)
        assert memory.read(pair, 8) == 16 and memory.read(pair + 8, 8) == 0
        memory.write(pair, 8, 0xCAFE)
        memory.write(pair + 8, 8, control)
        memory.write(manager + 8, 8, storage + 16)

    def add(address, amount):
        assert memory.read(locals_seen[0], 8) == (0xCAFE if amount == 1 else 0xBAD)
        memory.write(locals_seen[0], 8, 0xBAD)
        return memory.fetch_add_u32(address, amount)

    acquire_replay_zone_map(
        context(memory),
        manager,
        output,
        header,
        0,
        calls=ReplayTaskRebuildCalls(call),
        atomics=ReplayUnitAIMapAtomics(None, add),
        bind_local=memory.bind_local,
    )
    assert memory.read(output + 8, 8) == 0xCAFE
    assert memory.read(output + 16, 8) == control and memory.read(control + 8, 4) == 2
    with pytest.raises(ReplayMemoryError, match="unmapped"):
        memory.read(locals_seen[0], 1)


def test_world_getter_is_wrapped_address_without_any_world_read() -> None:
    memory = ReplayMemory()
    bound = bind_replay_zone_map_registry(
        context(memory),
        ReplayTaskRebuildCalls(None),
        atomics=ReplayUnitAIMapAtomics(None, None),
        bind_local=memory.bind_local,
    )
    assert bound.call is not None
    assert bound.call(0x141604030, ((1 << 64) - 1,), None) == 0x787
