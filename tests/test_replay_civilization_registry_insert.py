"""Authored owned-state controls, not a native execution or initialized registry oracle."""

from __future__ import annotations

import pytest

from vantage import replay_civilization_registry_insert as insert
from vantage.replay_memory import ReplayMemory, ReplayMemoryError
from vantage.replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
)
from vantage.replay_unit_ai_map import ReplayUnitAIMapAtomics


class Numeric:
    def __init__(self):
        self.memory = ReplayMemory()
        self.header = self.memory.allocate(0x40)
        self.nil = self.header + 0x20
        self.memory.write(self.header, 4, 0)
        self.memory.write(self.header + 8, 8, self.nil)
        self.memory.write(self.nil, 4, 0)
        self.context = ReplayTaskRebuildStorage(self.header, self.memory.read, self.memory.write)
        self.atomics = ReplayUnitAIMapAtomics(None, self.memory.fetch_add_u32)
        self.records = []

    def record(self, key, prior=0):
        address = self.memory.allocate(0x1D0)
        self.memory.write(address + 8, 4, prior)
        self.memory.write(address + 0x14, 4, key)
        self.records.append(address)
        return address

    def add(self, key, prior=0):
        record = self.record(key, prior)
        result = insert.insert_replay_civilization_numeric(
            self.context, self.header, record, atomics=self.atomics
        )
        assert result is None
        return record


def test_numeric_empty_order_unknown_padding_void_and_actual_wrapped_lock_increment():
    fixture = Numeric()
    memory, header, nil = fixture.memory, fixture.header, fixture.nil
    record = fixture.record(42, 0xFFFFFFFF)
    node = record + 0x1B0
    events = []

    def read(address, width):
        result = memory.read(address, width)
        events.append(("r", address, width, result))
        return result

    def write(address, width, value):
        events.append(("w", address, width, value & ((1 << (width * 8)) - 1)))
        memory.write(address, width, value & ((1 << (width * 8)) - 1))

    def atomic(address, addend):
        events.append(("atomic", address, addend))
        assert memory.read(header + 8, 8) == node and memory.read(node, 4) == 0
        return memory.fetch_add_u32(address, addend)

    context = ReplayTaskRebuildStorage(header, read, write)
    result = insert.insert_replay_civilization_numeric(
        context, header, record, atomics=ReplayUnitAIMapAtomics(None, atomic)
    )
    assert result is None
    assert events == [
        ("w", node + 0x10, 8, nil),
        ("w", node + 8, 8, nil),
        ("r", header + 8, 8, nil),
        ("w", node + 0x18, 8, header),
        ("w", header + 8, 8, node),
        ("w", node, 4, 1),
        ("r", node + 0x18, 8, header),
        ("r", header, 4, 0),
        ("r", header + 8, 8, node),
        ("w", node, 4, 0),
        ("atomic", record + 8, 1),
    ]
    assert memory.read(record + 8, 4) == 0
    for address in (record, record + 12, node + 4, header + 4, nil + 4):
        with pytest.raises(ReplayMemoryError, match="undefined"):
            memory.read(address, 1)


@pytest.mark.parametrize(
    ("root_key", "new_key", "offset"),
    [
        (5, 5, 0x10),
        (0, 0x80000000, 0x10),
        (0x80000000, 0, 0x10),
        (0xFFFFFFFF, 0, 0x10),
        (0, 0xFFFFFFFF, 8),
        (0x80000000, 0x7FFFFFFF, 8),
    ],
)
def test_numeric_duplicates_and_key_subtraction_are_wrapped_signed_dword(root_key, new_key, offset):
    fixture = Numeric()
    first = fixture.add(root_key)
    second = fixture.add(new_key)
    memory = fixture.memory
    assert memory.read(fixture.header + 8, 8) == first + 0x1B0
    assert memory.read(first + 0x1B0 + offset, 8) == second + 0x1B0
    assert memory.read(second + 0x1C8, 8) == first + 0x1B0
    assert memory.read(first + 8, 4) == memory.read(second + 8, 4) == 1


@pytest.mark.parametrize("keys", [(3, 2, 1), (1, 2, 3), (3, 1, 2), (1, 3, 2)])
def test_numeric_both_single_and_mirrored_double_rotations(keys):
    fixture = Numeric()
    records = {key: fixture.add(key) for key in keys}
    memory = fixture.memory
    root = records[2] + 0x1B0
    assert memory.read(fixture.header + 8, 8) == root
    assert memory.read(root + 8, 8) == records[1] + 0x1B0
    assert memory.read(root + 0x10, 8) == records[3] + 0x1B0
    assert memory.read(root + 0x18, 8) == fixture.header
    assert memory.read(root, 4) == 0
    assert all(memory.read(records[key] + 0x1B0, 4) == 1 for key in (1, 3))


@pytest.mark.parametrize("keys", [(4, 2, 6, 1), (4, 2, 6, 7)])
def test_numeric_red_uncle_recoloring_moves_up_in_both_directions(keys):
    fixture = Numeric()
    records = {key: fixture.add(key) for key in keys}
    memory = fixture.memory
    assert memory.read(fixture.header + 8, 8) == records[4] + 0x1B0
    assert all(memory.read(records[key] + 0x1B0, 4) == 0 for key in (4, 2, 6))
    assert memory.read(records[keys[-1]] + 0x1B0, 4) == 1


def test_numeric_held_search_key_but_current_key_reread_when_attaching():
    fixture = Numeric()
    root = fixture.add(20)
    record = fixture.record(10)
    memory = fixture.memory
    changed = False

    def read(address, width):
        nonlocal changed
        value = memory.read(address, width)
        if address == record + 0x14 and not changed:
            changed = True
            memory.write(address, 4, 30)
        return value

    context = ReplayTaskRebuildStorage(fixture.header, read, memory.write)
    insert.insert_replay_civilization_numeric(
        context, fixture.header, record, atomics=fixture.atomics
    )
    assert memory.read(root + 0x1B8, 8) == fixture.nil
    assert memory.read(root + 0x1C0, 8) == record + 0x1B0
    assert memory.read(record + 0x14, 4) == 30


def test_numeric_final_root_is_current_and_missing_atomic_preserves_prior_tree_writes():
    fixture = Numeric()
    record, other = fixture.record(1), fixture.record(2)
    node, alternative = record + 0x1B0, other + 0x1B0
    memory = fixture.memory
    memory.write(alternative, 4, 7)

    def write(address, width, value):
        memory.write(address, width, value)
        if address == node and width == 4 and value == 1:
            memory.write(fixture.header + 8, 8, alternative)

    context = ReplayTaskRebuildStorage(fixture.header, memory.read, write)
    with pytest.raises(UnresolvedReplayTaskRebuild, match="atomic effect unavailable"):
        insert.insert_replay_civilization_numeric(
            context, fixture.header, record, atomics=ReplayUnitAIMapAtomics(None, None)
        )
    assert memory.read(node, 4) == 1 and memory.read(alternative, 4) == 0
    assert memory.read(node + 0x18, 8) == fixture.header
    assert memory.read(record + 8, 4) == 0


def test_numeric_missing_header_read_retains_initial_node_link_stores():
    memory = ReplayMemory()
    record = memory.allocate(0x1D0)
    context = ReplayTaskRebuildStorage(1, memory.read, memory.write)
    with pytest.raises(ReplayMemoryError, match="unmapped"):
        insert.insert_replay_civilization_numeric(
            context, 0xBAD0, record, atomics=ReplayUnitAIMapAtomics(None, memory.fetch_add_u32)
        )
    assert memory.read(record + 0x1B8, 8) == memory.read(record + 0x1C0, 8) == 0xBAF0
    with pytest.raises(ReplayMemoryError, match="undefined"):
        memory.read(record + 0x1C8, 8)


class Names:
    def __init__(self):
        self.memory = ReplayMemory()
        self.header, self.nil = self.memory.allocate(16), self.memory.allocate(32)
        self.memory.write(self.header, 8, self.nil)
        self.memory.write(self.header + 8, 8, 0)
        for offset in (0, 8, 16):
            self.memory.write(self.nil + offset, 8, self.nil)
        self.memory.write(self.nil + 24, 1, 1)
        self.memory.write(self.nil + 25, 1, 1)
        self.context = ReplayTaskRebuildStorage(self.header, self.memory.read, self.memory.write)
        self.keys = {}

    def node(self):
        address = self.memory.allocate(64)
        for offset in (0, 8, 16):
            self.memory.write(address + offset, 8, self.nil)
        self.memory.write(address + 24, 1, 0)
        self.memory.write(address + 25, 1, 0)
        return address

    def add(self, key):
        # Authored fixture supplies a coherent parent/direction descriptor;
        # this is not an implementation of a registry's comparison/search.
        parent, cursor, direction = self.nil, self.memory.read(self.nil + 8, 8), 0
        while cursor != self.nil:
            parent = cursor
            direction = int(key < self.keys[cursor])
            cursor = self.memory.read(cursor + (0 if direction else 16), 8)
        descriptor, node = self.memory.allocate(16), self.node()
        self.memory.write(descriptor, 8, parent)
        self.memory.write(descriptor + 8, 4, direction)
        self.keys[node] = key
        assert (
            insert.link_replay_civilization_name(self.context, self.header, descriptor, node)
            == node
        )
        with pytest.raises(ReplayMemoryError, match="undefined"):
            self.memory.read(descriptor + 12, 4)
        return node


def test_name_empty_counter_wrap_held_return_no_payload_or_padding_initialization():
    fixture = Names()
    fixture.memory.write(fixture.header + 8, 8, (1 << 64) - 1)
    node = fixture.add(1)
    memory = fixture.memory
    assert memory.read(fixture.header + 8, 8) == 0
    assert all(memory.read(fixture.nil + offset, 8) == node for offset in (0, 8, 16))
    assert memory.read(node + 24, 1) == 1 and memory.read(node + 25, 1) == 0
    with pytest.raises(ReplayMemoryError, match="undefined"):
        memory.read(node + 26, 1)
    with pytest.raises(ReplayMemoryError, match="undefined"):
        memory.read(node + 32, 1)


@pytest.mark.parametrize("keys", [(3, 2, 1), (1, 2, 3), (3, 1, 2), (1, 3, 2)])
def test_name_real_shared_603_body_rotates_both_mirrored_cases(keys):
    fixture = Names()
    nodes = {key: fixture.add(key) for key in keys}
    memory = fixture.memory
    assert memory.read(fixture.header + 8, 8) == 3
    assert memory.read(fixture.nil + 8, 8) == nodes[2]
    assert memory.read(nodes[2], 8) == nodes[1]
    assert memory.read(nodes[2] + 16, 8) == nodes[3]
    assert memory.read(nodes[2] + 8, 8) == fixture.nil
    assert memory.read(nodes[2] + 24, 1) == 1
    assert memory.read(fixture.nil, 8) == nodes[1]
    assert memory.read(fixture.nil + 16, 8) == nodes[3]


@pytest.mark.parametrize("keys", [(4, 2, 6, 1), (4, 2, 6, 7)])
def test_name_real_shared_body_red_uncle_paths(keys):
    fixture = Names()
    nodes = {key: fixture.add(key) for key in keys}
    memory = fixture.memory
    assert all(memory.read(nodes[key] + 24, 1) == 1 for key in (4, 2, 6))
    assert memory.read(nodes[keys[-1]] + 24, 1) == 0


def test_name_count_store_precedes_current_header_pointer_read():
    fixture = Names()
    memory = fixture.memory
    alternative = memory.allocate(32)
    for offset in (0, 8, 16):
        memory.write(alternative + offset, 8, alternative)
    memory.write(alternative + 24, 1, 1)
    memory.write(alternative + 25, 1, 1)
    descriptor, node = memory.allocate(16), fixture.node()
    memory.write(descriptor, 8, alternative)

    def write(address, width, value):
        memory.write(address, width, value)
        if address == fixture.header + 8:
            memory.write(fixture.header, 8, alternative)

    context = ReplayTaskRebuildStorage(fixture.header, memory.read, write)
    assert insert.link_replay_civilization_name(context, fixture.header, descriptor, node) == node
    assert memory.read(fixture.nil + 8, 8) == fixture.nil
    assert memory.read(alternative + 8, 8) == node


@pytest.mark.parametrize(
    ("target", "args", "payload"),
    [
        (0x140F6AE70, (), None),
        (0x140F6AE70, (1, 2, 3), None),
        (0x140F6B790, (1, 2), None),
        (0x140F6B790, (1, 2, 3, 4), None),
        (0x140F6AE70, (1, 2), memoryview(bytearray())),
        (0x140F6B790, (1, 2, 3), memoryview(bytearray())),
    ],
)
def test_bound_entry_arity_payload_refusal_has_no_backing_effect(target, args, payload):
    memory = ReplayMemory()
    context = ReplayTaskRebuildStorage(1, memory.read, memory.write)
    bound = insert.bind_replay_civilization_registry_insert(
        context, ReplayTaskRebuildCalls(None), atomics=ReplayUnitAIMapAtomics(None, None)
    )
    with pytest.raises(ValueError, match="malformed"):
        bound.call(target, args, payload)
    assert memory.mapped_bytes == 0


def test_bound_real_numeric_and_name_entries_unknown_delegation_and_no_ctor_binding():
    fixture = Numeric()
    seen = []

    def delegate(target, args, data):
        seen.append((target, args, data))
        raise UnresolvedReplayTaskRebuild(f"required child{target:x}")

    bound = insert.bind_replay_civilization_registry_insert(
        fixture.context, ReplayTaskRebuildCalls(delegate), atomics=fixture.atomics
    )
    record = fixture.record(7)
    assert bound.call(0x140F6AE70, (fixture.header, record), None) is None
    assert fixture.memory.read(record + 8, 4) == 1
    payload = memoryview(bytearray(b"x"))
    with pytest.raises(UnresolvedReplayTaskRebuild, match="140f69780"):
        bound.call(0x140F69780, (1, 2), payload)
    assert seen == [(0x140F69780, (1, 2), payload)]
    names = Names()
    node, descriptor = names.node(), names.memory.allocate(16)
    names.memory.write(descriptor, 8, names.nil)
    name_bound = insert.bind_replay_civilization_registry_insert(
        names.context, ReplayTaskRebuildCalls(None), atomics=ReplayUnitAIMapAtomics(None, None)
    )
    assert name_bound.call(0x140F6B790, (names.header, descriptor, node), None) == node


@pytest.mark.parametrize("failure", ["raise-after-atomic", "invalid-prior-word"])
def test_numeric_atomic_provider_failure_preserves_actual_reached_increment_and_tree(failure):
    fixture = Numeric()
    record = fixture.record(11)
    effects = []

    def atomic(address, addend):
        prior = fixture.memory.fetch_add_u32(address, addend)
        effects.append((address, addend, prior))
        if failure == "raise-after-atomic":
            raise LookupError("actual atomic provider failure")
        return True  # Invalid raw-u32 provider result; the actual effect already happened.

    expected = LookupError if failure == "raise-after-atomic" else ValueError
    with pytest.raises(expected):
        insert.insert_replay_civilization_numeric(
            fixture.context, fixture.header, record, atomics=ReplayUnitAIMapAtomics(None, atomic)
        )
    node = record + 0x1B0
    assert effects == [(record + 8, 1, 0)]
    assert fixture.memory.read(record + 8, 4) == 1
    assert fixture.memory.read(fixture.header + 8, 8) == node
    assert fixture.memory.read(node, 4) == 0


@pytest.mark.parametrize("direction", [0x80000000, 0xFFFFFFFF])
def test_name_descriptor_direction_is_any_nonzero_raw_dword(direction):
    fixture = Names()
    root = fixture.add(5)
    descriptor, node = fixture.memory.allocate(16), fixture.node()
    fixture.memory.write(descriptor, 8, root)
    fixture.memory.write(descriptor + 8, 4, direction)
    result = insert.link_replay_civilization_name(fixture.context, fixture.header, descriptor, node)
    assert result == node
    assert fixture.memory.read(root, 8) == node
    assert fixture.memory.read(fixture.nil, 8) == node
    assert fixture.memory.read(fixture.nil + 8, 8) == root


@pytest.mark.parametrize(("header", "record"), [(-1, 1), (1, True), (1, 1 << 64), (1, 1.5)])
def test_numeric_raw_argument_validation_rejects_before_backing_effects(header, record):
    fixture = Numeric()
    before = fixture.memory.snapshot()
    with pytest.raises(ValueError):
        insert.insert_replay_civilization_numeric(
            fixture.context, header, record, atomics=fixture.atomics
        )
    assert fixture.memory.snapshot() == before
