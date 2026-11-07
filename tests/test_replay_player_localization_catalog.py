"""Source-led catalog traversal using owned bytes and stateful mutex services.

Authored callbacks below expose current/held mutations, not native execution.
The first-bucket fixtures use literal mask zero; hash tests use literal buckets.
"""

from __future__ import annotations

import pytest

from vantage.replay_localization_runtime import (
    ReplayLocalizationRuntime,
    ReplayLocalizationTargets,
)
from vantage.replay_memory import ReplayMemory, ReplayMemoryError, ReplayMemoryRuntimeError
from vantage.replay_player_localization_catalog import (
    ReplayLocalizationCatalogProfile,
    bind_replay_player_localization_catalog,
)
from vantage.replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
)

FIND, CATALOG = 0x14095F0B0, 0x140964B80
LOCK, UNLOCK, THROW, COMPARE = 0x142D6AA5B, 0x142D6AA61, 0x142D6AA67, 0x142D6E4B3
SLOTS = {LOCK: 0x143199288, UNLOCK: 0x143199280, THROW: 0x143199278, COMPARE: 0x14319A300}
LAYERS = ((0xB8, 0x70, 0x78), (0x158, 0xA0, 0xA8), (0x108, 0x88, 0x90))


class Fixture:
    def __init__(self, *, key_bytes=1000, nodes=100, rows=100, virtuals=100):
        self.memory = ReplayMemory(max_bytes=1 << 20)
        self.manager, self.output = self.memory.allocate(0x240), self.memory.allocate(8)
        self.memory.write(self.output, 8, 0xBAD)
        self.events, self.effects = [], {}
        self.on_read = self.on_write = None
        targets = ReplayLocalizationTargets(0xAC10, 0xAC20, 0xAC30, 0xAC40, 0xAC50)
        self.runtime = ReplayLocalizationRuntime(self.memory, targets, self.memory.runtime_calls())
        self.terminal_calls = self.runtime.calls()
        for target, token in (
            (LOCK, targets.lock),
            (UNLOCK, targets.unlock),
            (THROW, targets.error),
            (COMPARE, targets.comparison),
        ):
            self.memory.map_bytes(SLOTS[target], token.to_bytes(8, "little"))
        for mutex, begin, end in LAYERS:
            self.memory.write(self.manager + begin, 8, 0)
            self.memory.write(self.manager + end, 8, 0)
            self.memory.write(self.manager + mutex + 0x4C, 4, 0)
            self.runtime.register_mutex(self.manager + mutex)
        self.memory.write(self.manager + 0x1C0, 8, 0)
        self.memory.write(self.manager + 0x21C, 4, 0)
        self.runtime.register_mutex(self.manager + 0x1D0)
        self.context = ReplayTaskRebuildStorage(self.manager, self.read, self.write)
        self.calls = ReplayTaskRebuildCalls(self.dispatch)
        self.bound = bind_replay_player_localization_catalog(
            self.context,
            self.calls,
            profile=ReplayLocalizationCatalogProfile(key_bytes, nodes, rows, virtuals),
            imports=ReplayTaskRebuildCalls(self.terminal),
        )

    def read(self, address, width):
        value = self.memory.read(address, width)
        self.events.append(("r", address, width, value))
        if self.on_read:
            self.on_read(address, width, value)
        return value

    def write(self, address, width, value):
        self.memory.write(address, width, value)
        self.events.append(("w", address, width, value))
        if self.on_write:
            self.on_write(address, width, value)

    def dispatch(self, target, args, data):
        self.events.append(("c", target, args))
        if target in self.effects:
            return self.effects[target](args)
        if target in (FIND, CATALOG, *SLOTS):
            return self.invoke(target, *args, data=data)
        assert self.terminal_calls.call
        return self.terminal_calls.call(target, args, data)

    def terminal(self, target, args, data):
        self.events.append(("i", target, args))
        if target in self.effects:
            return self.effects[target](args)
        assert self.terminal_calls.call
        return self.terminal_calls.call(target, args, data)

    def invoke(self, target, *args, data=None):
        assert self.bound.call
        return self.bound.call(target, args, data)

    def targets(self, target):
        return [row[2] for row in self.events if row[:2] == ("c", target)]

    def string(self, value):
        address = self.memory.allocate(len(value) + 1)
        self.memory.write_bytes(address, value + b"\0")
        return address

    def table(self, entries):
        table, sentinel, bucket = (
            self.memory.allocate(0x38),
            self.memory.allocate(1),
            self.memory.allocate(16),
        )
        for offset, value in ((8, sentinel), (0x18, bucket), (0x30, 0)):
            self.memory.write(table + offset, 8, value)
        nodes = []
        for key, value in entries:
            node = self.memory.allocate(32)
            self.memory.write(node + 8, 8, nodes[-1] if nodes else sentinel)
            self.memory.write(node + 0x10, 8, self.string(key))
            self.memory.write(node + 0x18, 8, value)
            nodes.append(node)
        self.memory.write(bucket, 8, nodes[0] if nodes else sentinel)
        self.memory.write(bucket + 8, 8, nodes[-1] if nodes else sentinel)
        return table, sentinel, bucket, nodes

    def layer(self, index, tables):
        _mutex, begin, end = LAYERS[index]
        address = self.memory.allocate(16 * len(tables)) if tables else 0
        for number, table in enumerate(tables):
            self.memory.write(address + 16 * number, 8, table)
        self.memory.write(self.manager + begin, 8, address)
        self.memory.write(self.manager + end, 8, address + 16 * len(tables))
        return address


def test_real_leaf_finds_backward_chain_and_current_payload():
    f = Fixture()
    values = [f.string(value) for value in (b"A", b"B", b"C")]
    table, _sentinel, _bucket, nodes = f.table(
        list(zip((b"first", b"wanted", b"last"), values, strict=True))
    )
    key = f.string(b"wanted")
    assert f.invoke(FIND, table, key) == values[1]
    assert f.targets(COMPARE) == [
        (key, f.memory.read(nodes[2] + 0x10, 8)),
        (key, f.memory.read(nodes[1] + 0x10, 8)),
    ]
    with pytest.raises(ReplayMemoryError):
        f.memory.read(nodes[1], 8)  # No invented forward link is needed.


@pytest.mark.parametrize("key,bucket_index", [(b"\x80", 37), (b"", 261), (None, 261)])
def test_signed_byte_hash_and_null_empty_key_use_literal_buckets(key, bucket_index):
    f = Fixture()
    table, sentinel, buckets = (
        f.memory.allocate(0x38),
        f.memory.allocate(1),
        f.memory.allocate(512 * 16),
    )
    for offset, value in ((8, sentinel), (0x18, buckets), (0x30, 511)):
        f.memory.write(table + offset, 8, value)
    f.memory.write(buckets + 16 * bucket_index + 8, 8, sentinel)
    pointer = 0 if key is None else f.string(key)
    assert f.invoke(FIND, table, pointer) == 0
    assert not f.targets(COMPARE)
    assert ("r", buckets + 16 * bucket_index + 8, 8, sentinel) in f.events


def test_node_key_precedes_bucket_first_read_and_payload_is_reloaded_after_compare():
    f = Fixture()
    key, original, changed = f.string(b"wanted"), f.string(b"old"), f.string(b"new")
    table, _sentinel, bucket, nodes = f.table([(b"wanted", original)])
    held_key = f.memory.read(nodes[0] + 0x10, 8)

    def read(address, width, value):
        if address == bucket:
            f.memory.write(nodes[0] + 0x10, 8, 0xBAD)

    def compare(args):
        assert args == (key, held_key)
        f.memory.write(nodes[0] + 0x18, 8, changed)
        return 1 << 32  # Only EAX selects equality.

    f.on_read, f.effects[COMPARE] = read, compare
    assert f.invoke(FIND, table, key) == changed


def test_bucket_first_is_held_across_compare_callbacks():
    f = Fixture()
    table, _sentinel, bucket, nodes = f.table([(b"A", 1), (b"B", 2), (b"C", 3)])

    def compare(args):
        f.memory.write(bucket, 8, nodes[-1])
        return 1

    f.effects[COMPARE] = compare
    assert f.invoke(FIND, table, f.string(b"missing")) == 0
    assert len(f.targets(COMPARE)) == 3


@pytest.mark.parametrize("layer", [0, 1, 2])
def test_each_real_vector_layer_hits_with_correct_priority_and_balanced_mutex(layer):
    f = Fixture()
    key, value = f.string(b"wanted"), f.string(b"text")
    for number in range(layer):
        missing, *_rest = f.table([(b"missing", value)])
        f.layer(number, [missing])
    table, *_rest = f.table([(b"wanted", value)])
    f.layer(layer, [table])
    assert f.invoke(CATALOG, f.manager, key, f.output) & 255 == 1
    assert f.memory.read(f.output, 8) == value
    expected = [(f.manager + LAYERS[n][0],) for n in range(layer + 1)]
    assert f.targets(LOCK) == f.targets(UNLOCK) == expected
    for mutex, _begin, _end in LAYERS:
        assert f.memory.read(f.manager + mutex + 0x4C, 4) == 0


def test_all_misses_visit_three_vectors_then_virtual_list_without_resetting_output():
    f = Fixture()
    assert f.invoke(CATALOG, f.manager, 0xBAD, f.output) & 255 == 0
    assert f.memory.read(f.output, 8) == 0xBAD
    locks = [(f.manager + n,) for n in (0xB8, 0x158, 0x108, 0x1D0)]
    assert f.targets(LOCK) == f.targets(UNLOCK) == locks


def test_current_vector_end_changes_are_observed_after_each_failed_row():
    f = Fixture()
    rows = f.layer(0, [0x111, 0x222, 0x333])

    def find(args):
        assert args == (0x111, 0xBAD)
        f.memory.write(f.manager + 0x78, 8, rows + 16)
        return 0

    f.effects[FIND] = find
    assert f.invoke(CATALOG, f.manager, 0xBAD, f.output) & 255 == 0
    assert f.targets(FIND) == [(0x111, 0xBAD)]


def test_fixed_table_hit_accepts_null_output_and_unlocks():
    f = Fixture()
    f.layer(0, [0x111])
    f.effects[FIND] = lambda args: 0xCAFE
    assert f.invoke(CATALOG, f.manager, 0xBAD, 0) & 255 == 1
    assert f.targets(UNLOCK) == [(f.manager + 0xB8,)]
    assert not any(row[0] == "w" and row[1] == 0 for row in f.events)


@pytest.mark.parametrize("output_null", [False, True])
def test_virtual_hit_uses_current_slot_and_unconditionally_writes_output(output_null):
    f = Fixture()
    node, vtable = f.memory.allocate(24), f.memory.allocate(0x30)
    f.memory.write(node, 8, vtable)
    f.memory.write(vtable + 0x28, 8, 0xF123)
    f.memory.write(f.manager + 0x1C0, 8, node)
    f.effects[0xF123] = lambda args: 0xCAFE
    if output_null:
        with pytest.raises(ReplayMemoryError):
            f.invoke(CATALOG, f.manager, 0xBAD, 0)
        assert f.memory.read(f.manager + 0x21C, 4) == 1
        assert len(f.targets(UNLOCK)) == 3
    else:
        assert f.invoke(CATALOG, f.manager, 0xBAD, f.output) & 255 == 1
        assert f.memory.read(f.output, 8) == 0xCAFE
        assert len(f.targets(UNLOCK)) == 4
    assert f.targets(0xF123) == [(node, 0xBAD)]


def test_virtual_next_pointer_is_reloaded_after_lookup():
    f = Fixture(virtuals=2)
    first, second, vtable = (f.memory.allocate(24), f.memory.allocate(24), f.memory.allocate(0x30))
    for node in (first, second):
        f.memory.write(node, 8, vtable)
    f.memory.write(vtable + 0x28, 8, 0xF123)
    f.memory.write(f.manager + 0x1C0, 8, first)

    def lookup(args):
        if args[0] == first:
            f.memory.write(first + 0x10, 8, second)
            return 0
        return 0xCAFE

    f.effects[0xF123] = lookup
    assert f.invoke(CATALOG, f.manager, 0xBAD, f.output) & 255 == 1
    assert f.targets(0xF123) == [(first, 0xBAD), (second, 0xBAD)]


@pytest.mark.parametrize("code", [5, 6])
def test_real_error_paths_keep_lock_count_effects_and_never_invent_unlock(code):
    f = Fixture()
    mutex = f.manager + 0xB8
    if code == 5:
        f.effects[LOCK] = lambda args: 0x100000001
    else:
        f.memory.write(mutex + 0x4C, 4, 0x7FFFFFFE)
    with pytest.raises(ReplayMemoryRuntimeError) as raised:
        f.invoke(CATALOG, f.manager, 0xBAD, f.output)
    assert raised.value.args_words == (code,)
    assert f.targets(THROW) == [(code,)] and f.targets(UNLOCK) == []
    if code == 6:
        assert ("w", mutex + 0x4C, 4, 0x7FFFFFFE) in f.events


@pytest.mark.parametrize("code,trap", [(5, "140964d9d"), (6, "140964d92")])
def test_returned_error_provider_refuses_at_actual_trap(code, trap):
    f = Fixture()
    if code == 5:
        f.effects[LOCK] = lambda args: 1
    else:
        f.memory.write(f.manager + 0x104, 4, 0x7FFFFFFE)
    f.effects[THROW] = lambda args: None
    with pytest.raises(UnresolvedReplayTaskRebuild, match=trap):
        f.invoke(CATALOG, f.manager, 0xBAD, f.output)
    assert not f.targets(UNLOCK)


def test_lock_tests_low_eax_after_an_actual_stateful_successful_lock():
    f = Fixture()

    def lock(args):
        assert f.invoke(LOCK, *args) == 0  # Actual current-IAT service mutates count.
        return 1 << 32

    f.effects[LOCK] = lock
    assert f.invoke(CATALOG, f.manager, 0xBAD, f.output) & 255 == 0
    assert len(f.targets(LOCK)) == len(f.targets(UNLOCK)) == 4
    assert not f.targets(THROW)


def test_key_byte_budget_is_shared_across_real_leaf_reentry_for_two_catalog_rows():
    f = Fixture(key_bytes=1)
    missing, *_rest = f.table([(b"B", 1)])
    matching, *_rest = f.table([(b"A", 2)])
    f.layer(0, [missing, matching])
    key = f.string(b"A")
    with pytest.raises(UnresolvedReplayTaskRebuild, match="key_bytes budget"):
        f.invoke(CATALOG, f.manager, key, f.output)
    assert f.targets(FIND) == [(missing, key), (matching, key)]
    assert len(f.targets(COMPARE)) == 1
    assert f.memory.read(f.manager + 0x104, 4) == 1
    assert not f.targets(UNLOCK)


def test_imported_token_equal_to_owned_entry_is_terminal_and_raw_return_survives():
    f = Fixture()
    f.memory.write(SLOTS[COMPARE], 8, FIND)

    def terminal(args):
        assert f.events[-1][0] == "i" and args == (1, 2)
        return 0x1234567800000000

    f.effects[FIND] = terminal
    assert f.invoke(COMPARE, 1, 2) == 0x1234567800000000
    assert f.targets(FIND) == []


@pytest.mark.parametrize("budget", ["key_bytes", "nodes", "rows", "virtuals"])
def test_reached_budget_refusals_preserve_preceding_effects(budget):
    f = Fixture(**{budget: 0})
    if budget in ("key_bytes", "nodes"):
        table, *_rest = f.table([(b"A", 1)])
        with pytest.raises(UnresolvedReplayTaskRebuild, match="budget exhausted"):
            f.invoke(FIND, table, f.string(b"A"))
    elif budget == "rows":
        f.layer(0, [0x111])
        with pytest.raises(UnresolvedReplayTaskRebuild, match="rows budget"):
            f.invoke(CATALOG, f.manager, 0xBAD, f.output)
        assert f.memory.read(f.manager + 0x104, 4) == 1
    else:
        f.memory.write(f.manager + 0x1C0, 8, 0xBAD)
        with pytest.raises(UnresolvedReplayTaskRebuild, match="virtuals budget"):
            f.invoke(CATALOG, f.manager, 0xBAD, f.output)
        assert f.memory.read(f.manager + 0x21C, 4) == 1


@pytest.mark.parametrize(
    "target,args",
    [(FIND, (1,)), (CATALOG, (1, 2)), (LOCK, ()), (UNLOCK, ()), (THROW, ()), (COMPARE, (1,))],
)
def test_source_arities_validate_before_effects(target, args):
    f = Fixture()
    with pytest.raises(ValueError, match="malformed"):
        f.invoke(target, *args)
    assert f.events == []


def test_unknown_delegate_keeps_data_identity_and_raw_result():
    f = Fixture()
    seen, view = [], memoryview(bytearray(b"abc"))

    def delegate(target, args, data):
        seen.append((target, args, data))
        return 0xCAFE

    bound = bind_replay_player_localization_catalog(
        f.context,
        ReplayTaskRebuildCalls(delegate),
        profile=ReplayLocalizationCatalogProfile(0, 0, 0, 0),
    )
    assert bound.call and bound.call(0x123, (7,), view) == 0xCAFE
    assert seen == [(0x123, (7,), view)] and seen[0][2] is view


@pytest.mark.parametrize("values", [(-1, 0, 0, 0), (0, True, 0, 0), (0, 0, 1.5, 0)])
def test_explicit_nonnegative_traversal_budget_contract(values):
    with pytest.raises(ValueError):
        ReplayLocalizationCatalogProfile(*values)
