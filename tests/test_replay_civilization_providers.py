"""Authored owned-memory caller controls; opaque leaf plans are not registries."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from vantage.replay_civilization_providers import (
    bind_replay_civilization_providers,
    find_replay_civilization_name,
    find_replay_civilization_resource,
    less_replay_civilization_names,
    read_replay_civilization_descriptor,
    select_replay_civilization_family,
)
from vantage.replay_memory import ReplayMemory, ReplayMemoryError
from vantage.replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
)

U64 = (1 << 64) - 1
Hook = Callable[[str, int, int, int], None]


class Rig:
    def __init__(self) -> None:
        self.memory = ReplayMemory(max_bytes=1 << 20)
        self.trace: list[tuple[str, int, int, int]] = []
        self.reached: list[tuple[int, tuple[int, ...]]] = []
        self.hook: Hook | None = None
        self.effects: dict[int, Callable[[tuple[int, ...]], int | None]] = {}
        self.storage = ReplayTaskRebuildStorage(0x500, self.read, self.write)
        self.calls = ReplayTaskRebuildCalls(self.effect)
        self.bound = bind_replay_civilization_providers(self.storage, self.calls)

    def read(self, address: int, width: int) -> int:
        value = self.memory.read(address, width)
        self.trace.append(("read", address, width, value))
        if self.hook:
            self.hook("read", address, width, value)
        return value

    def write(self, address: int, width: int, value: int) -> None:
        self.memory.write(address, width, value)
        self.trace.append(("write", address, width, value))
        if self.hook:
            self.hook("write", address, width, value)

    def effect(self, target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        assert data is None
        self.reached.append((target, args))
        if target not in self.effects:
            raise UnresolvedReplayTaskRebuild(f"opaque authored leaf{target:x} unavailable")
        return self.effects[target](args)

    def invoke(self, target: int, *args: int) -> int | None:
        assert self.bound.call is not None
        return self.bound.call(target, args, None)

    def word(self, address: int, width: int, value: int) -> None:
        self.memory.map_bytes(address, value.to_bytes(width, "little"))

    def block(self, size: int, *, fill: int = 0) -> int:
        address = self.memory.allocate(size)
        self.memory.write_bytes(address, bytes([fill]) * size)
        return address

    def string(self, value: bytes) -> int:
        data = self.block(max(len(value), 1))
        self.memory.write_bytes(data, value)
        header = self.block(24)
        self.memory.write(header, 8, data)
        self.memory.write(header + 8, 8, len(value))
        return header

    def name_tree(self, selector: int, keys: tuple[bytes, ...]) -> tuple[int, list[int]]:
        header = 0x1442E9720 if selector == 2 else 0x1442E9730
        sentinel = self.block(64)
        self.memory.write(sentinel + 0x19, 1, 1)
        nodes = [self.block(64) for _ in keys]
        self.word(header, 8, sentinel)
        self.memory.write(sentinel + 8, 8, nodes[0] if nodes else sentinel)
        for i, (node, key) in enumerate(zip(nodes, keys, strict=True)):
            string = self.string(key)
            self.memory.write(node, 8, sentinel)
            self.memory.write(node + 0x10, 8, sentinel)
            self.memory.write_bytes(node + 0x20, self.memory.read_bytes(string, 24))
            self.memory.write(node + 0x38, 4, i + 10)
        return sentinel, nodes

    def numeric_tree(self, selector: int, keys: tuple[int, ...]) -> tuple[int, list[int]]:
        header = 0x143DB06C0 if selector == 1 else 0x143DB0680
        sentinel = header + 0x20
        nodes = [self.block(0x1D0) + 0x1B0 for _ in keys]
        self.word(header + 8, 8, nodes[0] if nodes else sentinel)
        for node, key in zip(nodes, keys, strict=True):
            self.memory.write(node - 0x19C, 4, key)
            self.memory.write(node + 8, 8, sentinel)
            self.memory.write(node + 0x10, 8, sentinel)
            self.memory.write(node + 0x18, 8, header)
        return sentinel, nodes


def test_descriptor_null_global_preserves_three_padding_bytes() -> None:
    rig = Rig()
    rig.word(0x144353698, 8, 0)
    home = rig.block(8, fill=0xA5)
    assert rig.invoke(0x140FA3420, home) == home
    assert rig.memory.read_bytes(home, 8) == bytes.fromhex("0200000000a5a5a5")
    assert rig.trace == [
        ("read", 0x144353698, 8, 0),
        ("write", home, 4, 2),
        ("write", home + 4, 1, 0),
    ]


def test_descriptor_holds_current_global_pointer_before_child_read() -> None:
    rig = Rig()
    first, second, home = rig.block(0x688), rig.block(0x688), rig.block(8)
    rig.word(0x144353698, 8, first)
    rig.memory.write(first + 0x680, 8, 0xA50100000003)
    rig.memory.write(second + 0x680, 8, 0xFFFFFFFFFFFFFFFF)

    def mutate(kind: str, address: int, _width: int, _value: int) -> None:
        if kind == "read" and address == 0x144353698:
            rig.memory.write(address, 8, second)

    rig.hook = mutate
    assert rig.invoke(0x140FA3420, home) == home
    assert rig.memory.read(home, 8) == 0xA50100000003
    assert [x[1] for x in rig.trace if x[0] == "read"] == [0x144353698, first + 0x680]


def test_descriptor_second_store_failure_keeps_first_store() -> None:
    rig = Rig()
    rig.word(0x144353698, 8, 0)
    rig.word(0x9000, 4, 0xFFFFFFFF)
    rig.memory.map_bytes(0x9004, b"\xff", writable=False)
    with pytest.raises(ReplayMemoryError):
        rig.invoke(0x140FA3420, 0x9000)
    assert rig.memory.read(0x9000, 4) == 2
    assert rig.memory.read(0x9004, 1) == 0xFF


@pytest.mark.parametrize(
    "tag,value,result",
    [(0, 0, 0), (0, 0xFFFFFFFF, 0xFFFFFFFF), (0, 2, 2), (1, 3, 2), (1, 0, 0), (1, 0xFFFFFFFF, 0)],
)
def test_selector_reads_tag_before_current_dword(tag: int, value: int, result: int) -> None:
    rig = Rig()
    descriptor = rig.block(8)
    rig.memory.write(descriptor + 4, 1, tag)
    rig.memory.write(descriptor, 4, value ^ 0xFFFFFFFF)

    def mutate(kind: str, address: int, _width: int, _value: int) -> None:
        if kind == "read" and address == descriptor + 4:
            rig.memory.write(descriptor, 4, value)

    rig.hook = mutate
    assert rig.invoke(0x140FA36A0, descriptor) == result
    assert [x[1] for x in rig.trace] == [descriptor + 4, descriptor]


@pytest.mark.parametrize("tag", [2, 0xFF])
@pytest.mark.parametrize("returns", [False, True])
def test_selector_bad_tag_calls_real_fatal_then_return_trap(tag: int, returns: bool) -> None:
    rig = Rig()
    rig.word(0x9004, 1, tag)
    if returns:
        rig.effects[0x1408F56B0] = lambda args: 123
    with pytest.raises(UnresolvedReplayTaskRebuild, match="CC140fa36ce" if returns else "leaf"):
        rig.invoke(0x140FA36A0, 0x9000)
    assert rig.reached == [(0x1408F56B0, ())]
    assert rig.trace == [("read", 0x9004, 1, tag)]


def test_comparator_right_empty_skips_all_left_fields() -> None:
    rig = Rig()
    rig.word(0x9008, 8, 0)
    assert rig.invoke(0x140A162A0, 0xBAD0, 0x9000) == 0
    assert rig.trace == [("read", 0x9008, 8, 0)]
    assert not rig.reached


def test_comparator_left_empty_skips_pointer_reads() -> None:
    rig = Rig()
    rig.word(0x9008, 8, 100)
    rig.word(0xA008, 8, 0)
    assert rig.invoke(0x140A162A0, 0xA000, 0x9000) == 1
    assert [x[1] for x in rig.trace] == [0x9008, 0xA008]
    assert not rig.reached


@pytest.mark.parametrize(
    "left_len,right_len,eax,result",
    [
        (3, 9, 0, 1),
        (9, 3, 0, 0),
        (9, 9, 0, 0),
        (3, 9, 1, 0),
        (9, 3, 0x7FFFFFFF, 0),
        (9, 3, 0xFFFFFFFF, 1),
        (9, 3, 0x80000000, 1),
        (1 << 63, U64, 0, 1),
        (U64, 1 << 63, 0, 0),
    ],
)
def test_comparator_opaque_raw_eax_and_unsigned_minimum(
    left_len: int,
    right_len: int,
    eax: int,
    result: int,
) -> None:
    rig = Rig()
    left, right = rig.block(16), rig.block(16)
    rig.memory.write(left, 8, 0xCAFE)
    rig.memory.write(right, 8, 0xBEEF)
    rig.memory.write(left + 8, 8, left_len)
    rig.memory.write(right + 8, 8, right_len)
    rig.effects[0x142D6E3BD] = lambda args: eax  # Explicit opaque raw-EAX plan, not memcmp.
    assert rig.invoke(0x140A162A0, left, right) == result
    assert rig.reached == [(0x142D6E3BD, (0xCAFE, 0xBEEF, min(left_len, right_len)))]
    assert [x[1] for x in rig.trace] == [right + 8, left + 8, right, left]


def test_comparator_pointer_current_reads_and_lengths_held_across_mutations() -> None:
    rig = Rig()
    left, right = rig.block(16), rig.block(16)
    rig.memory.write(left + 8, 8, 3)
    rig.memory.write(right + 8, 8, 7)
    rig.memory.write(left, 8, 0x1111)
    rig.memory.write(right, 8, 0x2222)

    def mutate(kind: str, address: int, _width: int, _value: int) -> None:
        if kind == "read" and address == right:
            rig.memory.write(left, 8, 0x3333)
            rig.memory.write(left + 8, 8, 99)
            rig.memory.write(right + 8, 8, 1)

    rig.hook = mutate
    rig.effects[0x142D6E3BD] = lambda args: 0
    assert rig.invoke(0x140A162A0, left, right) == 1
    assert rig.reached == [(0x142D6E3BD, (0x3333, 0x2222, 3))]


def test_comparator_self_alias_still_requires_real_memcmp() -> None:
    rig = Rig()
    value = rig.string(b"a")
    with pytest.raises(UnresolvedReplayTaskRebuild):
        rig.invoke(0x140A162A0, value, value)
    assert len(rig.trace) == 4
    assert rig.reached[0][0] == 0x142D6E3BD


@pytest.mark.parametrize("raw", [None, True, -1, 1 << 32])
def test_comparator_refuses_malformed_raw_eax_after_actual_pointer_reads(raw) -> None:
    rig = Rig()
    value = rig.string(b"a")
    rig.effects[0x142D6E3BD] = lambda args: raw
    with pytest.raises(ValueError):
        rig.invoke(0x140A162A0, value, value)
    assert len(rig.trace) == 4 and len(rig.reached) == 1


@pytest.mark.parametrize("selector", [0, 1, 2, 0xFFFFFFFF])
def test_name_empty_explicit_tree_returns_zero_without_default(selector: int) -> None:
    rig = Rig()
    sentinel, _ = rig.name_tree(selector, ())
    assert rig.invoke(0x140F6A690, 0xBAD0, selector) == 0
    assert rig.trace[-2:] == [("read", sentinel + 0x19, 1, 1)] * 2
    assert not rig.reached


@pytest.mark.parametrize("selector", [1, 2])
def test_name_two_searches_actual_comparator_with_opaque_equal_leaf(selector: int) -> None:
    rig = Rig()
    _, nodes = rig.name_tree(selector, (b"a",))
    name = rig.string(b"a")
    rig.memory.write(nodes[0] + 0x38, 4, 0xFFFFFFFF)
    rig.effects[0x142D6E3BD] = lambda args: 0
    assert rig.invoke(0x140F6A690, name, selector) == 0xFFFFFFFF
    assert len(rig.reached) == 4
    header = 0x1442E9720 if selector == 2 else 0x1442E9730
    assert sum(x[1] == header for x in rig.trace) == 2


@pytest.mark.parametrize(
    "offset,answer,keys", [(0, 1, (b"b", b"a")), (0x10, 0xFFFFFFFF, (b"a", b"b"))]
)
def test_name_first_comparator_uses_current_edge_after_leaf_effect(
    offset: int,
    answer: int,
    keys: tuple[bytes, bytes],
) -> None:
    rig = Rig()
    sentinel, nodes = rig.name_tree(2, keys)
    root, child = nodes
    name = rig.string(keys[1])
    answers = iter([answer, 0, 0, answer, 0, 0])

    def opaque(args: tuple[int, ...]) -> int:
        if len(rig.reached) == 1:
            rig.memory.write(root + offset, 8, child)
        return next(answers)

    rig.effects[0x142D6E3BD] = opaque
    assert rig.invoke(0x140F6A690, name, 2) == 11
    assert rig.memory.read(child, 8) == sentinel
    assert any(x[:3] == ("read", root + offset, 8) and x[3] == child for x in rig.trace)


def test_name_second_search_reloads_header_and_reads_value_after_reverse_effect() -> None:
    rig = Rig()
    _, first = rig.name_tree(2, (b"a",))
    second_sentinel = rig.block(64)
    rig.memory.write(second_sentinel + 0x19, 1, 1)
    second = rig.block(64)
    rig.memory.write_bytes(second + 0x20, rig.memory.read_bytes(first[0] + 0x20, 24))
    rig.memory.write(second, 8, second_sentinel)
    rig.memory.write(second_sentinel + 8, 8, second)
    name = rig.string(b"a")

    def opaque(args: tuple[int, ...]) -> int:
        if len(rig.reached) == 2:
            rig.memory.write(0x1442E9720, 8, second_sentinel)
        if len(rig.reached) == 4:
            rig.memory.write(second + 0x38, 4, 123)
        return 0

    rig.effects[0x142D6E3BD] = opaque
    assert rig.invoke(0x140F6A690, name, 2) == 123
    assert rig.trace[-1] == ("read", second + 0x38, 4, 123)


@pytest.mark.parametrize("returns", [False, True])
def test_name_disappearing_second_key_reaches_real_fatal(returns: bool) -> None:
    rig = Rig()
    sentinel, _ = rig.name_tree(2, (b"a",))
    name = rig.string(b"a")

    def opaque(args: tuple[int, ...]) -> int:
        if len(rig.reached) == 2:
            rig.memory.write(sentinel + 8, 8, sentinel)
        return 0

    rig.effects[0x142D6E3BD] = opaque
    if returns:
        rig.effects[0x142D6AA55] = lambda args: None
    with pytest.raises(UnresolvedReplayTaskRebuild, match="CC140f6a78e" if returns else "leaf"):
        rig.invoke(0x140F6A690, name, 2)
    assert rig.reached[-1] == (0x142D6AA55, (0x1436802B0,))
    assert rig.memory.read(sentinel + 8, 8) == sentinel


def test_name_nonempty_actual_comparator_missing_memcmp_refuses() -> None:
    rig = Rig()
    rig.name_tree(2, (b"a",))
    with pytest.raises(UnresolvedReplayTaskRebuild):
        rig.invoke(0x140F6A690, rig.string(b"a"), 2)
    assert rig.reached[0][0] == 0x142D6E3BD


@pytest.mark.parametrize("answers", [(0xFFFFFFFF,), (0, 0xFFFFFFFF)])
def test_name_first_search_absence_shortcuts_before_second_header(answers: tuple[int, ...]) -> None:
    rig = Rig()
    rig.name_tree(2, (b"a",))
    plan = iter(answers)
    rig.effects[0x142D6E3BD] = lambda args: next(plan)
    assert rig.invoke(0x140F6A690, rig.string(b"b"), 2) == 0
    assert sum(x[1] == 0x1442E9720 for x in rig.trace) == 1
    assert len(rig.reached) == len(answers)


def test_name_current_candidate_nil_after_leaf_mutation_skips_reverse() -> None:
    rig = Rig()
    _, nodes = rig.name_tree(2, (b"a",))

    def opaque(args: tuple[int, ...]) -> int:
        rig.memory.write(nodes[0] + 0x19, 1, 1)
        return 0

    rig.effects[0x142D6E3BD] = opaque
    assert rig.invoke(0x140F6A690, rig.string(b"a"), 2) == 0
    assert len(rig.reached) == 1
    assert rig.trace[-1] == ("read", nodes[0] + 0x19, 1, 1)


def test_name_second_reverse_mismatch_reaches_fatal_with_four_leaf_effects() -> None:
    rig = Rig()
    rig.name_tree(2, (b"a",))
    plan = iter([0, 0, 0, 0xFFFFFFFF])
    rig.effects[0x142D6E3BD] = lambda args: next(plan)
    with pytest.raises(UnresolvedReplayTaskRebuild):
        rig.invoke(0x140F6A690, rig.string(b"a"), 2)
    assert len(rig.reached) == 5
    assert rig.reached[-1] == (0x142D6AA55, (0x1436802B0,))


@pytest.mark.parametrize("selector", [0, 1, 2, 0xFFFFFFFF])
def test_numeric_explicit_empty_root_returns_zero(selector: int) -> None:
    rig = Rig()
    rig.numeric_tree(selector, ())
    assert rig.invoke(0x140F6A320, 7, selector) == 0
    assert len(rig.trace) == 1 and not rig.reached


@pytest.mark.parametrize("selector", [1, 2])
@pytest.mark.parametrize(
    "key,index,offset",
    [
        (7, 8, 0x10),
        (8, 7, 8),
        (0, 0x80000001, 8),
        (0xFFFFFFFF, 0x7FFFFFFF, 0x10),
        (0x80000000, 1, 8),
    ],
)
def test_numeric_routing_uses_wrapped_signed_subtraction(
    selector: int,
    key: int,
    index: int,
    offset: int,
) -> None:
    rig = Rig()
    sentinel, nodes = rig.numeric_tree(selector, (key,))
    assert rig.invoke(0x140F6A320, index, selector) == 0
    assert rig.trace[-1] == ("read", nodes[0] + offset, 8, sentinel)


@pytest.mark.parametrize("selector", [1, 2])
def test_numeric_root_match_reads_header_plus8_before_header_exit(selector: int) -> None:
    rig = Rig()
    _, nodes = rig.numeric_tree(selector, (7,))
    header = 0x143DB06C0 if selector == 1 else 0x143DB0680
    assert rig.invoke(0x140F6A320, 7, selector) == nodes[0] - 0x1B0
    assert rig.trace[-1] == ("read", header + 8, 8, nodes[0])
    assert not rig.reached


@pytest.mark.parametrize("selector", [1, 2])
def test_numeric_duplicate_predecessor_rightmost_and_parent_walk(selector: int) -> None:
    rig = Rig()
    _, nodes = rig.numeric_tree(selector, (5, 5, 5, 5))
    root, a, b, c = nodes
    for address, value in (
        (root + 8, a),
        (a + 0x10, b),
        (b + 0x10, c),
        (a + 0x18, root),
        (b + 0x18, a),
        (c + 0x18, b),
    ):
        rig.memory.write(address, 8, value)
    assert rig.invoke(0x140F6A320, 5, selector) == a - 0x1B0
    read_addresses = [x[1] for x in rig.trace]
    assert read_addresses.count(c - 0x19C) == 1
    assert read_addresses.count(b - 0x19C) == 1
    assert read_addresses.count(a - 0x19C) == 1


@pytest.mark.parametrize("selector", [1, 2])
def test_numeric_climbs_multiple_left_ancestors(selector: int) -> None:
    rig = Rig()
    _, nodes = rig.numeric_tree(selector, (10, 8, 7))
    root, middle, leaf = nodes
    rig.memory.write(root + 8, 8, middle)
    rig.memory.write(middle + 8, 8, leaf)
    rig.memory.write(middle + 0x18, 8, root)
    rig.memory.write(leaf + 0x18, 8, middle)
    assert rig.invoke(0x140F6A320, 7, selector) == leaf - 0x1B0
    assert sum(x[1] == middle + 0x18 for x in rig.trace) == 1
    assert sum(x[1] == root + 0x18 for x in rig.trace) == 1


@pytest.mark.parametrize("selector", [1, 2])
def test_numeric_predecessor_nonmatching_key_preserves_held_node(selector: int) -> None:
    rig = Rig()
    _, nodes = rig.numeric_tree(selector, (5, 4))
    rig.memory.write(nodes[0] + 8, 8, nodes[1])
    assert rig.invoke(0x140F6A320, 5, selector) == nodes[0] - 0x1B0
    assert rig.trace[-1] == ("read", nodes[1] - 0x19C, 4, 4)


@pytest.mark.parametrize("selector", [1, 2])
def test_numeric_nonempty_right_search_and_parent_predecessor(selector: int) -> None:
    rig = Rig()
    _, nodes = rig.numeric_tree(selector, (3, 7))
    rig.memory.write(nodes[0] + 0x10, 8, nodes[1])
    rig.memory.write(nodes[1] + 0x18, 8, nodes[0])
    assert rig.invoke(0x140F6A320, 7, selector) == nodes[1] - 0x1B0
    assert rig.trace[-1] == ("read", nodes[0] - 0x19C, 4, 3)


@pytest.mark.parametrize("selector", [1, 2])
def test_numeric_ancestor_climb_breaks_on_current_parent_child_relation(selector: int) -> None:
    rig = Rig()
    _, nodes = rig.numeric_tree(selector, (5, 10, 4))
    found, parent, grandparent = nodes
    rig.memory.write(found + 0x18, 8, parent)
    rig.memory.write(parent + 8, 8, found)
    rig.memory.write(parent + 0x18, 8, grandparent)
    # Authored adversarial defined backing; no current/native tree identity claim.
    assert rig.invoke(0x140F6A320, 5, selector) == found - 0x1B0
    assert rig.trace[-1] == ("read", grandparent - 0x19C, 4, 4)


def test_numeric_holds_initial_root_across_access_hook() -> None:
    rig = Rig()
    sentinel, nodes = rig.numeric_tree(2, (7,))

    def mutate(kind: str, address: int, _width: int, _value: int) -> None:
        if kind == "read" and address == 0x143DB0688:
            rig.memory.write(address, 8, sentinel)
            rig.hook = None

    rig.hook = mutate
    # The held found node is returned; current header+8 differs at the later comparison,
    # so make its selected predecessor a sentinel before that comparison.
    rig.memory.write(nodes[0] + 0x18, 8, sentinel)
    rig.word(sentinel + 8, 8, 0)
    assert rig.invoke(0x140F6A320, 7, 2) == nodes[0] - 0x1B0


def test_numeric_unknown_parent_backing_refuses_at_reached_read() -> None:
    rig = Rig()
    _, nodes = rig.numeric_tree(1, (7,))
    rig.memory.write(nodes[0] + 0x18, 8, 0xBAD0)
    with pytest.raises(ReplayMemoryError):
        rig.invoke(0x140F6A320, 7, 1)
    assert rig.trace[-1] == ("read", nodes[0] + 0x18, 8, 0xBAD0)


def test_numeric_wrapped_record_result_and_key_address() -> None:
    rig = Rig()
    node, header, sentinel = 0x100, 0x143DB0680, 0x143DB06A0
    rig.word(header + 8, 8, node)
    rig.word((node - 0x19C) & U64, 4, 7)
    rig.word(node + 8, 8, sentinel)
    rig.word(node + 0x18, 8, header)
    assert rig.invoke(0x140F6A320, 7, 2) == (node - 0x1B0) & U64


@pytest.mark.parametrize(
    "target,args",
    [
        (0x140FA3420, (0x9000,)),
        (0x140FA36A0, (0x9000,)),
        (0x140F6A690, (0x9000, 2)),
        (0x140F6A320, (0, 2)),
        (0x140A162A0, (0x9000, 0xA000)),
    ],
)
def test_missing_current_backing_never_becomes_default(target: int, args: tuple[int, ...]) -> None:
    rig = Rig()
    with pytest.raises(ReplayMemoryError):
        rig.invoke(target, *args)
    assert not rig.reached


@pytest.mark.parametrize(
    "target,args",
    [
        (0x140FA3420, ()),
        (0x140FA36A0, ()),
        (0x140F6A690, (1,)),
        (0x140F6A320, (1,)),
        (0x140A162A0, (1,)),
    ],
)
def test_binder_refuses_wrong_arity_without_effects(target: int, args: tuple[int, ...]) -> None:
    rig = Rig()
    with pytest.raises(ValueError, match="malformed"):
        rig.invoke(target, *args)
    assert not rig.trace and not rig.reached


def test_binder_nonnull_data_refuses_and_unowned_target_delegates() -> None:
    rig = Rig()
    assert rig.bound.call is not None
    with pytest.raises(ValueError):
        rig.bound.call(0x140FA3420, (1,), memoryview(bytearray(1)))
    rig.effects[0xFEED] = lambda args: args[0] + 1
    assert rig.invoke(0xFEED, 10) == 11
    assert rig.reached == [(0xFEED, (10,))]


@pytest.mark.parametrize(
    "function,args",
    [
        (read_replay_civilization_descriptor, (True,)),
        (select_replay_civilization_family, (-1,)),
        (less_replay_civilization_names, (0, 1 << 64)),
        (find_replay_civilization_name, (0, 1 << 32)),
        (find_replay_civilization_resource, (1 << 32, 2)),
        (find_replay_civilization_resource, (0, True)),
    ],
)
def test_public_raw_word_validation_precedes_access(function, args) -> None:
    rig = Rig()
    with pytest.raises(ValueError):
        function(rig.storage, *args, calls=rig.calls)
    assert not rig.trace and not rig.reached
