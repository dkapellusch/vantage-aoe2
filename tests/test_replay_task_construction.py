"""Owned task identities, constructor definedness and ordered shallow clones."""

from __future__ import annotations

import pytest

from vantage.replay_memory import ReplayMemory, ReplayMemoryError
from vantage.replay_task_construction import (
    bind_replay_task_construction,
    construct_replay_task,
    construct_replay_task_descriptor,
    copy_replay_task,
    create_replay_task,
    create_replay_task_list,
)
from vantage.replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
)

# Independently retained factory+ctor source image, ordinal1234. Not native output.
FACTORY_IMAGE = bytes.fromhex(
    "f84e2a43010000000100341200000000000000000000ffff0000000000000000"
    "ffffffffffffffff00000000000000000000000000000000ffff000000000000"
    "0000000000000000000000000000000000000000000000000000000000000000"
    "0000000000000000000000000000000000000000000000000000000000000000"
    "00000000000000000000000000000000"
)


def context(memory: ReplayMemory) -> ReplayTaskRebuildStorage:
    return ReplayTaskRebuildStorage(0x1000, memory.read, memory.write)


def bound(memory: ReplayMemory) -> ReplayTaskRebuildCalls:
    return bind_replay_task_construction(context(memory), memory.runtime_calls())


def invoke(calls: ReplayTaskRebuildCalls, target: int, *args: int) -> int | None:
    assert calls.call is not None
    return calls.call(target, args, None)


def test_factory_golden_image_and_per_occurrence_identity() -> None:
    memory = ReplayMemory()
    calls = bound(memory)
    first = invoke(calls, 0x1412691B0, 0, 0xCAFE0001, 0xDEAD1234)
    second = invoke(calls, 0x1412691B0, 0, 1, 0x1234)
    assert first and second and first != second
    assert memory.read_bytes(first, 144) == memory.read_bytes(second, 144) == FACTORY_IMAGE
    memory.write(first + 0xE, 2, 155)
    assert memory.read(second + 0xE, 2) == 0
    snapshot = memory.snapshot()
    third = invoke(calls, 0x1412691B0, 0, 1, 0x1234)
    restored = ReplayMemory.from_snapshot(snapshot)
    assert invoke(bound(restored), 0x1412691B0, 0, 1, 0x1234) == third
    assert restored.snapshot() == memory.snapshot()


@pytest.mark.parametrize("tag", [0, 2, 155, 158, 0xFFFF, 0x10000])
def test_unsupported_external_tags_do_not_allocate(tag: int) -> None:
    memory = ReplayMemory()
    before = memory.snapshot()
    assert create_replay_task(context(memory), 0, tag, 0, calls=ReplayTaskRebuildCalls(None)) == 0
    assert memory.snapshot() == before


@pytest.mark.parametrize(
    "target,args",
    [
        (0x1412691B0, (0, 1, 0)),
        (0x14116BA60, (0,)),
        (0x141323AE0, (0,)),
    ],
)
def test_null_allocation_branch_returns_zero_without_writes(
    target: int,
    args: tuple[int, ...],
) -> None:
    memory = ReplayMemory()
    seen = []

    def allocate(entry: int, values: tuple[int, ...], data: memoryview | None) -> int:
        seen.append((entry, values, data))
        return 0

    calls = bind_replay_task_construction(context(memory), ReplayTaskRebuildCalls(allocate))
    before = memory.snapshot()
    assert invoke(calls, target, *args) == 0
    assert seen == [(0x142D6BA78, (144 if target == 0x1412691B0 else 32,), None)]
    assert memory.snapshot() == before


@pytest.mark.parametrize("derived,table", [(False, 0x1432B5EE8), (True, 0x1432BC398)])
def test_nonnull_empty_list_is_distinct_and_fully_defined(derived: bool, table: int) -> None:
    memory = ReplayMemory()
    first = create_replay_task_list(context(memory), 0, derived=derived, calls=bound(memory))
    second = create_replay_task_list(context(memory), 0, derived=derived, calls=bound(memory))
    assert first != second and first and second
    assert memory.read_bytes(first, 32) == table.to_bytes(8, "little") + bytes(24)
    assert memory.read_bytes(second, 32) == memory.read_bytes(first, 32)


def test_standalone_descriptor_preserves_unknown_or_existing_padding() -> None:
    memory = ReplayMemory()
    descriptor = memory.allocate(24)
    assert construct_replay_task_descriptor(context(memory), descriptor) == descriptor
    assert memory.read_bytes(descriptor, 20) == bytes(20)
    with pytest.raises(ReplayMemoryError):
        memory.read(descriptor + 20, 4)
    memory.write(descriptor + 20, 4, 0xDEADBEEF)
    construct_replay_task_descriptor(context(memory), descriptor)
    assert memory.read(descriptor + 20, 4) == 0xDEADBEEF


def test_standalone_task_ctor_does_not_define_all_padding() -> None:
    memory = ReplayMemory()
    address = memory.allocate(144)
    assert (
        construct_replay_task(context(memory), address, 0x100001234, calls=bound(memory)) == address
    )
    assert memory.read(address + 0xA, 2) == 0x1234
    assert memory.read(address + 0x16, 4) == 0xFFFF
    assert memory.read(address + 0x20, 8) == (1 << 64) - 1
    assert memory.read_bytes(address + 0x60, 20) == bytes(20)
    for offset, width in ((0xD, 1), (0x3A, 6), (0x74, 4), (0x8C, 4)):
        with pytest.raises(ReplayMemoryError):
            memory.read(address + offset, width)


def test_ctor_requires_real_descriptor_effects_after_vtable_store() -> None:
    memory = ReplayMemory()
    task = memory.allocate(144)
    with pytest.raises(UnresolvedReplayTaskRebuild, match="14147b480"):
        construct_replay_task(context(memory), task, 5, calls=ReplayTaskRebuildCalls(None))
    assert memory.read(task, 8) == 0x1432A4EF8
    with pytest.raises(ReplayMemoryError):
        memory.read(task + 0xA, 2)


def test_clone_copies_descriptors_but_keeps_destination_identity_and_padding() -> None:
    memory = ReplayMemory()
    source, destination = memory.allocate(144), memory.allocate(144)
    raw = bytes(range(144))
    memory.write_bytes(source, raw)
    memory.write_bytes(destination, b"\xa5" * 144)
    assert invoke(bound(memory), 0x14112F830, destination, source) is None
    expected = bytearray(b"\xa5" * 144)
    expected[0xC] = raw[0xC]
    expected[0xE:0x3A] = raw[0xE:0x3A]
    expected[0x40:0x90] = raw[0x40:0x90]
    assert memory.read_bytes(destination, 144) == bytes(expected)
    assert memory.read_bytes(source, 144) == raw


def test_clone_overlapping_scalar_reads_observe_prior_stores() -> None:
    memory = ReplayMemory()
    source = memory.allocate(160)
    memory.write_bytes(source, bytes(range(160)))
    copy_replay_task(context(memory), source + 16, source)
    # Earlier stores at source1c and1e alter the later source1c DWORD load.
    assert memory.read(source + 16 + 0x1C, 4) == 0x0F0E1D0C


def test_clone_failure_keeps_prior_fields_and_graphic_copy() -> None:
    memory = ReplayMemory()
    source, destination = memory.allocate(144), memory.allocate(144)
    memory.write_bytes(source, bytes(range(0x48)))
    memory.write_bytes(destination, b"\xa5" * 144)
    with pytest.raises(ReplayMemoryError):
        copy_replay_task(context(memory), destination, source)
    assert memory.read_bytes(destination + 0x40, 8) == bytes(range(0x40, 0x48))
    assert memory.read_bytes(destination + 0x48, 8) == b"\xa5" * 8
    # The final word38 copy has not been reached.
    assert memory.read(destination + 0x38, 2) == 0xA5A5
    assert memory.read_bytes(destination, 12) == b"\xa5" * 12


def test_factory_prezeros_before_actual_ctor_and_derived_ignores_ctor_return() -> None:
    memory = ReplayMemory()
    record = memory.allocate(144)

    def task_child(target: int, args: tuple[int, ...], data: memoryview | None) -> int:
        assert data is None
        if target == 0x142D6BA78:
            assert args == (144,)
            return record
        assert target == 0x14112AA40 and args == (record, 0x1234)
        assert memory.read_bytes(record, 144) == bytes(144)
        memory.write(record + 0xD, 1, 9)
        return 0xCAFE

    assert (
        create_replay_task(context(memory), 0, 1, 0x1234, calls=ReplayTaskRebuildCalls(task_child))
        == 0xCAFE
    )
    assert memory.read(record + 0xD, 1) == 9
    empty_list = memory.allocate(32)

    def list_child(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        assert data is None
        if target == 0x142D6BA78:
            return empty_list
        assert target == 0x1412686D0 and args == (empty_list,)
        assert memory.read_bytes(empty_list, 32) == bytes(32)
        return None

    assert (
        create_replay_task_list(
            context(memory), 0, derived=True, calls=ReplayTaskRebuildCalls(list_child)
        )
        == empty_list
    )
    assert memory.read(empty_list, 8) == 0x1432BC398


@pytest.mark.parametrize(
    "target",
    [
        0x14147B480,
        0x1412686D0,
        0x14112AA40,
        0x1412691B0,
        0x14116BA60,
        0x141323AE0,
        0x14112F830,
    ],
)
def test_known_malformed_entry_refuses_before_effects(target: int) -> None:
    memory = ReplayMemory()
    before = memory.snapshot()
    with pytest.raises(ValueError, match="malformed"):
        invoke(bound(memory), target)
    assert memory.snapshot() == before


def test_unavailable_unknown_leaf_refuses() -> None:
    memory = ReplayMemory()
    calls = bind_replay_task_construction(context(memory), ReplayTaskRebuildCalls(None))
    with pytest.raises(UnresolvedReplayTaskRebuild, match="12345"):
        invoke(calls, 0x12345, 1)
