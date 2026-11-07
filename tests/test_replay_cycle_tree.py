"""Cycle-tree storage with real Entry/range callers and owned allocate/free.

Structural/order/payload invariants are independent controls, not a native
oracle. Mutation controls check the retained source's held/current distinctions.
No game, process memory, native instruction execution or recording restore.
"""

from __future__ import annotations

import itertools
import random
from collections.abc import Callable
from typing import cast

import pytest

from vantage.replay_cycle_tree import bind_replay_cycle_tree
from vantage.replay_cycle_tuning import (
    ReplayCycleTuningProfile,
    bind_replay_cycle_tuning,
)
from vantage.replay_memory import ReplayMemory, ReplayMemoryError
from vantage.replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
)

EXTRACT, LINK, CLEAR = 0x140E642F0, 0x140E646E0, 0x140E64A00
SUBTREE, LEFT, RIGHT, FREE = 0x140E62D90, 0x140E64940, 0x140E649A0, 0x142D6BAB4
ENTRY, ERASE = 0x140E630C0, 0x140E64160
U32, U64 = (1 << 32) - 1, (1 << 64) - 1
Handler = Callable[[tuple[int, ...]], int | None]


class Rig:
    def __init__(self) -> None:
        self.mem = ReplayMemory()
        self.events: list[tuple[str, int, int, int]] = []
        self.calls: list[tuple[int, tuple[int, ...]]] = []
        self.handlers: dict[int, Handler] = {}
        self.after_read: Callable[[int, int, int], None] | None = None
        self.after_write: Callable[[int, int, int], None] | None = None
        self.tree, self.header = self.alloc(16), self.alloc(40)
        self.position, self.key, self.endpoints = self.alloc(16), self.alloc(4), self.alloc(16)
        self.expected: dict[int, tuple[int, int]] = {}
        self.init_header(self.header)
        self.mem.write(self.tree, 8, self.header)
        self.context = ReplayTaskRebuildStorage(self.tree, self.read, self.write)
        self.ordinary_calls = ReplayTaskRebuildCalls(self.ordinary)
        self.runtime = self.mem.runtime_calls(self.ordinary_calls)
        self.bound = bind_replay_cycle_tree(self.context, self.ordinary_calls)
        unavailable = ReplayTaskRebuildCalls(None)
        self.tuning = bind_replay_cycle_tuning(
            self.context,
            self.ordinary_calls,
            ceil_calls=unavailable,
            virtual_calls=unavailable,
            logger_home_calls=unavailable,
            timer_home_calls=unavailable,
            bind_local=self.mem.bind_local,
            mxcsr=0x1F80,
            profile=ReplayCycleTuningProfile(
                bytes(0x24),
                bytes(0x70),
                bytes(0x98),
                bytes(0x40),
                bytes(0x40),
                bytes(0x44),
                bytes(0x28),
            ),
        )

    def alloc(self, size: int) -> int:
        at = self.mem.allocate(size)
        self.mem.fill(at, 0, size)
        return at

    def init_header(self, at: int) -> None:
        for field in (0, 8, 16):
            self.mem.write(at + field, 8, at)
        self.mem.write(at + 0x18, 2, 0x0101)

    def node(self, key: int, *, color: int = 0, value: int = 0) -> int:
        at = self.alloc(40)
        for offset in (0, 8, 16):
            self.mem.write(at + offset, 8, self.header)
        self.mem.write(at + 0x18, 1, color)
        self.mem.write(at + 0x1C, 4, key)
        self.mem.write(at + 0x20, 8, value)
        return at

    def read(self, address: int, width: int) -> int:
        value = self.mem.read(address, width)
        self.events.append(("r", address, width, value))
        if self.after_read:
            self.after_read(address, width, value)
        return value

    def write(self, address: int, width: int, value: int) -> None:
        self.mem.write(address, width, value)
        self.events.append(("w", address, width, value))
        if self.after_write:
            self.after_write(address, width, value)

    def ordinary(self, target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        assert data is None
        self.calls.append((target, args))
        if target in self.handlers:
            return self.handlers[target](args)
        if target in (EXTRACT, LINK, CLEAR, SUBTREE, LEFT, RIGHT):
            assert self.bound.call is not None
            return self.bound.call(target, args, data)
        if target in (FREE, 0x142D6BA78):
            assert self.runtime.call is not None
            return self.runtime.call(target, args, data)
        raise UnresolvedReplayTaskRebuild(f"unprovided authored child{target:x}")

    def run(self, target: int, *args: int) -> int | None:
        assert self.bound.call is not None
        return self.bound.call(target, args, None)

    def caller(self, target: int, *args: int) -> int | None:
        assert self.tuning.call is not None
        return self.tuning.call(target, args, None)

    def called(self, target: int) -> list[tuple[int, ...]]:
        return [args for at, args in self.calls if at == target]

    def insert(self, key: int, value: int | None = None) -> int:
        if value is None:
            value = (0xA5A5A5A5 << 32) | key
        self.mem.write(self.key, 4, key)
        slot = self.caller(ENTRY, self.tree, self.key)
        assert slot is not None
        node = slot - 0x20
        self.mem.write(slot, 8, value)
        self.expected[key] = node, value
        return node

    def remove(self, key: int) -> int:
        node, value = self.expected.pop(key)
        assert self.run(EXTRACT, self.tree, node) == node
        assert self.mem.read(node + 0x20, 8) == value
        return node

    def validate(self) -> None:
        m = self.mem
        assert m.read(self.tree, 8) == self.header
        assert m.read(self.tree + 8, 8) == len(self.expected)
        assert m.read(self.header + 0x18, 2) == 0x0101
        root = m.read(self.header + 8, 8)
        seen: set[int] = set()
        ordered: list[tuple[int, int]] = []

        def walk(node: int, parent: int, low: int, high: int) -> int:
            if node == self.header:
                return 1
            assert node not in seen
            seen.add(node)
            assert m.read(node + 0x19, 1) == 0
            assert m.read(node + 8, 8) == parent
            key, color = m.read(node + 0x1C, 4), m.read(node + 0x18, 1)
            assert low < key < high and color in (0, 1)
            assert self.expected[key] == (node, m.read(node + 0x20, 8))
            left, right = m.read(node, 8), m.read(node + 16, 8)
            if color == 0:
                assert m.read(left + 0x18, 1) == m.read(right + 0x18, 1) == 1
            first = walk(left, node, low, key)
            ordered.append((key, node))
            second = walk(right, node, key, high)
            assert first == second
            return first + color

        if root != self.header:
            assert m.read(root + 0x18, 1) == 1
        walk(root, self.header, -1, U32 + 1)
        assert [key for key, _ in ordered] == sorted(self.expected)
        assert m.read(self.header, 8) == (ordered[0][1] if ordered else self.header)
        assert m.read(self.header + 16, 8) == (ordered[-1][1] if ordered else self.header)


@pytest.mark.parametrize(
    ("target", "arity"), [(EXTRACT, 2), (LINK, 3), (CLEAR, 1), (SUBTREE, 3), (LEFT, 2), (RIGHT, 2)]
)
def test_contract_refuses_bad_arguments_or_payload_before_storage(target: int, arity: int) -> None:
    r = Rig()
    assert r.bound.call is not None
    for args, payload in (
        ((0,) * (arity + 1), None),
        ((-1,) + (0,) * (arity - 1), None),
        ((True,) + (0,) * (arity - 1), None),
        ((0,) * arity, memoryview(b"x")),
    ):
        with pytest.raises(ValueError):
            r.bound.call(target, args, payload)
    assert not r.events and not r.calls


def test_unknown_delegate_preserves_argument_payload_and_result_objects() -> None:
    r = Rig()
    args, data, result = (1, 2), memoryview(b"opaque"), 12345678912345

    def delegate(target: int, received: tuple[int, ...], payload: memoryview | None) -> int:
        assert target == 42 and received is args and payload is data
        return result

    bound = bind_replay_cycle_tree(r.context, ReplayTaskRebuildCalls(delegate))
    assert bound.call is not None and bound.call(42, args, data) is result


def test_empty_clear_stores_all_three_held_header_links_then_size() -> None:
    r = Rig()
    r.bound = bind_replay_cycle_tree(r.context, ReplayTaskRebuildCalls(None))
    assert r.run(CLEAR, r.tree) is None
    assert [(at, width, value) for kind, at, width, value in r.events if kind == "w"] == [
        (r.header + 8, 8, r.header),
        (r.header, 8, r.header),
        (r.header + 16, 8, r.header),
        (r.tree + 8, 8, 0),
    ]


def test_nil_subtree_does_not_touch_opaque_arguments_or_require_free() -> None:
    r = Rig()
    r.bound = bind_replay_cycle_tree(r.context, ReplayTaskRebuildCalls(None))
    assert r.run(SUBTREE, 0xABC, 0xF00D, r.header) is None
    assert r.events == [("r", r.header + 0x19, 1, 1)]


@pytest.mark.parametrize("keys", list(itertools.permutations((10, 20, 30))))
def test_three_node_insertions_cover_inner_outer_rotations(keys: tuple[int, ...]) -> None:
    r = Rig()
    for key in keys:
        r.insert(key)
        r.validate()
    root = r.mem.read(r.header + 8, 8)
    assert r.mem.read(root + 0x1C, 4) == 20
    assert r.mem.read(root + 0x18, 1) == 1
    assert not r.called(FREE)


@pytest.mark.parametrize("seed", [0, 17, 23, 104729])
@pytest.mark.parametrize("order", ["ascending", "descending", "insertion", "shuffled"])
def test_insert_extract_invariants_and_payload_identity_for_deletion_orders(
    seed: int,
    order: str,
) -> None:
    r = Rig()
    keys = list(range(48))
    rng = random.Random(seed)
    rng.shuffle(keys)
    for key in keys:
        r.insert(key)
        r.validate()
    removal = (
        sorted(keys)
        if order == "ascending"
        else sorted(keys, reverse=True)
        if order == "descending"
        else keys.copy()
    )
    if order == "shuffled":
        rng.shuffle(removal)
    for key in removal:
        node = r.remove(key)
        r.validate()
        r.mem.free(node)
    assert r.mem.read(r.tree + 8, 8) == 0
    assert r.mem.read(r.header + 8, 8) == r.header


def test_full_u32_keys_and_existing_entry_keep_one_payload_address() -> None:
    r = Rig()
    keys = [0x80000000, 0, U32, 1, 0x7FFFFFFF, 0xFFFFFFFE]
    for key in keys:
        r.insert(key)
    first = r.expected[0x80000000][0]
    assert r.insert(0x80000000, U64) == first
    assert r.mem.read(r.tree + 8, 8) == len(keys)
    r.validate()


def test_link_increments_wrapped_count_before_header_and_position_reads() -> None:
    r = Rig()
    node = r.node(10)
    r.mem.write(r.position, 8, r.header)
    r.mem.write(r.tree + 8, 8, U64)
    assert r.run(LINK, r.tree, r.position, node) == node
    assert r.events[:3] == [
        ("r", r.tree + 8, 8, U64),
        ("w", r.tree + 8, 8, 0),
        ("r", r.tree, 8, r.header),
    ]
    assert r.mem.read(r.header + 8, 8) == node
    assert r.mem.read(node + 0x18, 1) == 1
    assert r.mem.read(r.tree + 8, 8) == 0


def test_empty_link_does_not_read_unused_side_word() -> None:
    r = Rig()
    position = r.mem.allocate(8)
    r.mem.write(position, 8, r.header)
    node = r.node(10)
    assert r.run(LINK, r.tree, position, node) == node
    assert not any(kind == "r" and at == position + 8 for kind, at, _, _ in r.events)


def test_link_reads_side_after_publishing_parent_and_holds_initial_header() -> None:
    r = Rig()
    parent = r.insert(20)
    node = r.node(10)
    r.mem.write(r.position, 8, parent)
    r.mem.write(r.position + 8, 4, 0)
    other_header, other_root = r.alloc(40), r.node(99)
    r.init_header(other_header)
    r.mem.write(other_header + 8, 8, other_root)

    def mutate(address: int, width: int, value: int) -> None:
        if address == node + 8:
            r.mem.write(r.position + 8, 4, 0x100)
            r.mem.write(r.tree, 8, other_header)

    r.after_write = mutate
    assert r.run(LINK, r.tree, r.position, node) == node
    assert r.mem.read(parent, 8) == node
    assert r.mem.read(parent + 16, 8) == r.header
    assert r.mem.read(r.header, 8) == node
    assert r.mem.read(other_root + 0x18, 1) == 0
    assert r.mem.read(parent + 0x18, 1) == 1


@pytest.mark.parametrize("target", [LEFT, RIGHT])
def test_rotation_rereads_pivot_child_after_first_link_store(target: int) -> None:
    r = Rig()
    original, pivot, first, second = [r.node(key, color=1) for key in (10, 20, 15, 17)]
    outgoing = 16 if target == LEFT else 0
    inward = 0 if target == LEFT else 16
    r.mem.write(r.header + 8, 8, original)
    r.mem.write(original + outgoing, 8, pivot)
    r.mem.write(pivot + 8, 8, original)
    r.mem.write(pivot + inward, 8, first)
    r.mem.write(first + 8, 8, pivot)
    r.mem.write(second + 8, 8, pivot)

    def mutate(address: int, width: int, value: int) -> None:
        if address == original + outgoing:
            r.mem.write(pivot + inward, 8, second)

    r.after_write = mutate
    assert r.run(target, r.tree, original) is None
    assert r.mem.read(original + outgoing, 8) == first
    assert r.mem.read(first + 8, 8) == pivot
    assert r.mem.read(second + 8, 8) == original
    assert r.mem.read(pivot + inward, 8) == original
    assert [value for kind, at, _, value in r.events if kind == "r" and at == pivot + inward] == [
        first,
        second,
    ]


@pytest.mark.parametrize("extra", [False, True])
def test_two_child_extract_moves_successor_but_returns_original_with_payload(extra: bool) -> None:
    r = Rig()
    for key in [20, 10, 30, 25] if extra else [20, 10, 30]:
        r.insert(key)
    original, value = r.expected[20]
    assert r.remove(20) == original
    assert r.mem.read(original + 0x20, 8) == value
    root = r.mem.read(r.header + 8, 8)
    assert r.mem.read(root + 0x1C, 4) == (25 if extra else 30)
    assert not r.called(FREE)
    r.validate()


def test_extract_holds_initial_right_nil_across_later_left_read() -> None:
    r = Rig()
    root, left = r.node(10, color=1, value=10), r.node(5, value=5)
    right_nil = r.alloc(40)
    r.init_header(right_nil)
    for at, value in (
        (r.header, left),
        (r.header + 8, root),
        (r.header + 16, root),
        (root, left),
        (root + 16, right_nil),
        (left + 8, root),
        (r.tree + 8, 2),
    ):
        r.mem.write(at, 8, value)
    r.expected = {10: (root, 10), 5: (left, 5)}

    def mutate(address: int, width: int, value: int) -> None:
        if address == root:
            r.mem.write(right_nil + 0x19, 1, 0)

    r.after_read = mutate
    assert r.remove(10) == root
    r.validate()
    assert r.mem.read(r.header + 8, 8) == left


def test_black_leaf_with_nil_sibling_propagates_without_rotation_or_free() -> None:
    r = Rig()
    root, leaf = r.node(20, color=1), r.node(10, color=1)
    for at, value in (
        (r.header, leaf),
        (r.header + 8, root),
        (r.header + 16, root),
        (root, leaf),
        (leaf + 8, root),
        (r.tree + 8, 2),
    ):
        r.mem.write(at, 8, value)
    assert r.run(EXTRACT, r.tree, leaf) == leaf
    assert r.mem.read(root, 8) == r.header
    assert r.mem.read(root + 0x18, 1) == 1
    assert r.mem.read(r.tree + 8, 8) == 1
    assert not r.called(FREE)


def test_extract_late_zero_count_is_not_underflowed_or_stored() -> None:
    r = Rig()
    for key in (20, 10, 30):
        r.insert(key)
    root = r.expected[20][0]
    node = r.expected[10][0]
    r.events.clear()

    def mutate(address: int, width: int, value: int) -> None:
        if address == root:
            r.mem.write(r.tree + 8, 8, 0)

    r.after_write = mutate
    assert r.run(EXTRACT, r.tree, node) == node
    assert r.mem.read(r.tree + 8, 8) == 0
    assert not any(kind == "w" and at == r.tree + 8 for kind, at, _, _ in r.events)


def test_actual_range_erase_preserves_end_and_frees_only_removed_nodes() -> None:
    r = Rig()
    for key in (5, 2, 8, 1, 3, 6, 9, 4, 7, 0):
        r.insert(key)
    removed = {key: r.expected[key][0] for key in range(3, 7)}
    r.mem.write(r.endpoints, 8, r.expected[3][0])
    r.mem.write(r.endpoints + 8, 8, r.expected[7][0])
    assert r.caller(ERASE, r.tree, r.endpoints) == 4
    for key, node in removed.items():
        del r.expected[key]
        with pytest.raises(ReplayMemoryError):
            r.mem.read(node, 1)
    r.validate()
    assert [args[1] for args in r.called(FREE)] == [40] * 4


@pytest.mark.parametrize("target", [CLEAR, SUBTREE])
def test_right_subtree_then_root_then_held_left_free_order(target: int) -> None:
    r = Rig()
    for key in (20, 10, 30):
        r.insert(key)
    nodes = {key: value[0] for key, value in r.expected.items()}
    if target == CLEAR:
        assert r.run(CLEAR, r.tree) is None
        r.expected.clear()
        r.validate()
    else:
        assert r.run(SUBTREE, 0xABC, 0xF00D, nodes[20]) is None
        assert r.mem.read(r.tree + 8, 8) == 3
    assert r.called(FREE) == [(nodes[30], 40), (nodes[20], 40), (nodes[10], 40)]


def test_clear_resets_held_original_header_after_free_replaces_current_header() -> None:
    r = Rig()
    for key in (20, 10, 30):
        r.insert(key)
    other_header = r.alloc(40)
    r.init_header(other_header)
    r.mem.write(other_header + 8, 8, 0xF00D)

    def free(args: tuple[int, ...]) -> None:
        assert args[1] == 40
        r.mem.free(args[0])
        r.mem.write(r.tree, 8, other_header)

    r.handlers[FREE] = free
    assert r.run(CLEAR, r.tree) is None
    assert [r.mem.read(r.header + at, 8) for at in (0, 8, 16)] == [r.header] * 3
    assert r.mem.read(other_header + 8, 8) == 0xF00D
    assert r.mem.read(r.tree + 8, 8) == 0


def test_clear_holds_next_left_before_free_callback_mutates_node() -> None:
    r = Rig()
    root = r.insert(20)
    left = r.insert(10)

    def free(args: tuple[int, ...]) -> None:
        if args[0] == root:
            r.mem.write(root, 8, r.header)
        r.mem.free(args[0])

    r.handlers[FREE] = free
    assert r.run(CLEAR, r.tree) is None
    assert r.called(FREE) == [(root, 40), (left, 40)]


def test_unavailable_free_refuses_before_header_reset_and_count_change() -> None:
    r = Rig()
    nodes = [r.insert(key) for key in (20, 10, 30)]
    r.bound = bind_replay_cycle_tree(r.context, ReplayTaskRebuildCalls(None))
    r.events.clear()
    with pytest.raises(UnresolvedReplayTaskRebuild, match="142d6bab4"):
        r.run(CLEAR, r.tree)
    assert r.mem.read(r.tree + 8, 8) == 3
    assert r.mem.read(r.header + 8, 8) == nodes[0]
    assert not [e for e in r.events if e[0] == "w"]
    assert r.mem.read(nodes[2] + 0x1C, 4) == 30


def test_binding_requires_actual_context_and_dispatcher_objects() -> None:
    r = Rig()
    with pytest.raises(ValueError):
        bind_replay_cycle_tree(r.context, cast(ReplayTaskRebuildCalls, None))
    assert not r.events
