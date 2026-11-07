"""Actual owned sound descriptors, current registry lookup and retained padding."""

from __future__ import annotations

import pytest

from vantage.replay_memory import ReplayMemory, ReplayMemoryError
from vantage.replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
)
from vantage.replay_task_references import (
    bind_replay_task_references,
    resolve_replay_task_sound,
    task_sound_has_flag,
    task_sound_is_registered,
)


def context(memory: ReplayMemory) -> ReplayTaskRebuildStorage:
    return ReplayTaskRebuildStorage(1, memory.read, memory.write)


def run(memory: ReplayMemory, target: int, *args: int) -> int | None:
    calls = bind_replay_task_references(context(memory), ReplayTaskRebuildCalls(None))
    assert calls.call is not None
    return calls.call(target, args, None)


def descriptor(memory: ReplayMemory, primary: int = 0) -> int:
    address = memory.allocate(24)
    memory.fill(address, 0xA5, 24)
    memory.write(address, 4, primary)
    return address


def sound_table(memory: ReplayMemory, *, empty: bool = False) -> tuple[int, int]:
    table, slots, sound = memory.allocate(20), memory.allocate(8), memory.allocate(56)
    memory.write(table, 8, slots)
    memory.write(table + 16, 4, 1)
    memory.write(slots, 8, sound)
    for offset, value in (
        (8, 0x1000),
        (16, 0x1000 if empty else 0x1010),
        (40, 0x2000),
        (48, 0x2000),
    ):
        memory.write(sound + offset, 8, value)
    return table, sound


def registry(memory: ReplayMemory, *keys: int) -> tuple[int, int, tuple[int, ...]]:
    head, bucket = memory.allocate(24), memory.allocate(16)
    nodes = tuple(memory.allocate(24) for _ in keys)
    for address, value in ((0x1442976B8, head), (0x1442976C8, bucket), (0x1442976E0, 0)):
        memory.map_bytes(address, value.to_bytes(8, "little"))
    memory.write(bucket, 8, nodes[-1] if nodes else head)
    memory.write(bucket + 8, 8, nodes[0] if nodes else head)
    for i, (node, key) in enumerate(zip(nodes, keys, strict=True)):
        memory.write(node + 16, 4, key)
        if i + 1 < len(nodes):
            memory.write(node + 8, 8, nodes[i + 1])
    return head, bucket, nodes


@pytest.mark.parametrize("sound_id", [0xFFFF, 0x8000, 0x10000FFFF])
def test_negative_word_sound_id_clears_only_pointer_without_context_access(sound_id: int) -> None:
    memory = ReplayMemory()
    address = descriptor(memory, 0x1234)
    before = memory.read_bytes(address, 24)
    run(memory, 0x14147B6E0, address, 0xBAD, sound_id, 7)
    assert memory.read_bytes(address, 24) == before[:8] + bytes(8) + before[16:]


@pytest.mark.parametrize("count,index", [(0, 0), (1, 1), (0xFFFFFFFF, 0)])
def test_signed_count_rejection_does_not_read_unbacked_table_begin(count: int, index: int) -> None:
    memory = ReplayMemory()
    table = memory.allocate(20)
    memory.write(table + 16, 4, count)
    address = descriptor(memory)
    run(memory, 0x14147B6E0, address, table, index, 7)
    assert memory.read(address + 8, 8) == 0
    with pytest.raises(ReplayMemoryError, match="undefined"):
        memory.read(table, 8)


def test_empty_sound_clears_pointer_without_reading_unknown_primary() -> None:
    memory = ReplayMemory()
    table, _sound = sound_table(memory, empty=True)
    address = memory.allocate(24)
    run(memory, 0x14147B6E0, address, table, 0, 7)
    assert memory.read(address + 8, 8) == 0
    for offset in (0, 4, 16, 20):
        with pytest.raises(ReplayMemoryError, match="undefined"):
            memory.read(address + offset, 4)


def test_nonempty_first_range_skips_unknown_second_and_sets_truncated_fallback() -> None:
    memory = ReplayMemory()
    table, slots, sound = memory.allocate(20), memory.allocate(8), memory.allocate(24)
    memory.write(table, 8, slots)
    memory.write(table + 16, 4, 1)
    memory.write(slots, 8, sound)
    memory.write(sound + 8, 8, 0x1000)
    memory.write(sound + 16, 8, 0x1010)
    address = descriptor(memory)
    run(memory, 0x14147B6E0, address, table, 0, 0xABCDEF0062D4B3EC)
    assert memory.read(address, 4) == memory.read(address + 4, 4) == 0x62D4B3EC
    assert memory.read(address + 8, 8) == sound
    assert memory.read_bytes(address + 16, 8) == b"\xa5" * 8


@pytest.mark.parametrize("member", [False, True])
def test_nonzero_primary_uses_actual_registry_and_preserves_flags_padding(member: bool) -> None:
    memory = ReplayMemory()
    table, sound = sound_table(memory)
    registry(memory, 0x1234 if member else 0x5678)
    address = descriptor(memory, 0x1234)
    run(memory, 0x14147B6E0, address, table, 0, 0xBEEF)
    assert memory.read(address, 4) == 0x1234
    assert memory.read(address + 4, 4) == (0x1234 if member else 0xBEEF)
    assert memory.read(address + 8, 8) == sound
    assert memory.read_bytes(address + 16, 8) == b"\xa5" * 8


def test_unresolved_registry_retains_selected_pointer_and_prior_descriptor_words() -> None:
    memory = ReplayMemory()
    table, sound = sound_table(memory)
    address = descriptor(memory, 0x1234)
    with pytest.raises(ReplayMemoryError, match="unmapped"):
        run(memory, 0x14147B6E0, address, table, 0, 7)
    assert memory.read(address + 8, 8) == sound
    assert memory.read(address + 4, 4) == 0xA5A5A5A5


def test_null_selected_sound_reaches_dereference_after_pointer_store() -> None:
    memory = ReplayMemory()
    table, _sound = sound_table(memory)
    memory.write(memory.read(table, 8), 8, 0)
    address = descriptor(memory)
    with pytest.raises(ReplayMemoryError, match="unmapped"):
        run(memory, 0x14147B6E0, address, table, 0, 7)
    assert memory.read(address + 8, 8) == 0


def test_registry_uses_inclusive_terminal_and_never_reads_its_unknown_next() -> None:
    memory = ReplayMemory()
    _head, bucket, nodes = registry(memory, 7, 9)
    assert task_sound_is_registered(context(memory), 7) == 1
    assert task_sound_is_registered(context(memory), 9) == 1
    assert task_sound_is_registered(context(memory), 11) == 0
    assert task_sound_is_registered(context(memory), 0xABCDEF0000000009) == 1
    assert memory.read(bucket, 8) == nodes[-1]
    with pytest.raises(ReplayMemoryError, match="undefined"):
        memory.read(nodes[-1] + 8, 8)


def test_registry_read_order_and_empty_bucket_skip_terminal() -> None:
    memory = ReplayMemory()
    _head, bucket, _nodes = registry(memory)
    reads = []

    def read(address: int, width: int) -> int:
        reads.append((address, width))
        return memory.read(address, width)

    current = ReplayTaskRebuildStorage(1, read, memory.write)
    assert task_sound_is_registered(current, 0x12345678) == 0
    assert reads == [(0x1442976B8, 8), (0x1442976E0, 8), (0x1442976C8, 8), (bucket + 8, 8)]


@pytest.mark.parametrize("al,expected", [(0xAB01, 0xBEEF), (0xAB00, 7)])
def test_membership_al_selects_current_primary_or_held_fallback(al: int, expected: int) -> None:
    memory = ReplayMemory()
    table, _sound = sound_table(memory)
    address = descriptor(memory, 0x1234)

    def membership(target: int, args: tuple[int, ...], data: memoryview | None) -> int:
        assert target == 0x140B25EC0 and args == (0x1234,) and data is None
        memory.write(address, 4, 0xBEEF)
        return al

    resolve_replay_task_sound(
        context(memory), address, table, 0, 7, calls=ReplayTaskRebuildCalls(membership)
    )
    assert memory.read(address + 4, 4) == expected


@pytest.mark.parametrize(
    "primary,expected",
    [
        (0, 0),
        (0x060DC0F4, 1),
        (0x76835F7D, 1),
        (0x76835F7E, 0),
        (0xCD9A7723, 1),
        (0xE14E765C, 1),
        (0xFA26EE2A, 1),
        (0xFFFFFFFF, 0),
        (0x12345678FA26EE2A, 1),
    ],
)
def test_fixed_flag_predicate_raw_ecx_membership(primary: int, expected: int) -> None:
    assert task_sound_has_flag(primary) == expected


@pytest.mark.parametrize("target", [0x14147B6E0, 0x140B25EC0, 0x140B245D0])
def test_malformed_known_entry_has_no_memory_effect(target: int) -> None:
    memory = ReplayMemory()
    before = memory.snapshot()
    with pytest.raises(ValueError, match="malformed"):
        run(memory, target)
    assert memory.snapshot() == before


def test_unknown_helper_refuses_at_reach() -> None:
    with pytest.raises(UnresolvedReplayTaskRebuild, match="bad"):
        run(ReplayMemory(), 0xBAD)
