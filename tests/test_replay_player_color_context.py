"""Source-led current-storage controls; fixture policies are explicit, not native defaults."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from vantage import replay_player_color_context as color
from vantage.replay_base_saved_registration import (
    ReplayBaseSavedRegistrationFP,
    ReplayBaseSavedRegistrationScratch,
    bind_replay_base_saved_registration,
)
from vantage.replay_memory import ReplayMemory, ReplayMemoryError
from vantage.replay_player_base_children import set_replay_player_color
from vantage.replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
)

OBSERVER, INDEX, OWNER, SETTING = 0x141603D70, 0x141603DB0, 0x141734F30, 0x14097FB40
SETTER, SENTINEL, ENABLED, ONCE, GLOBAL = (
    0x140984210,
    0x143DA5054,
    0x144287088,
    0x1442870D0,
    0x14425B930,
)
W, P, S = 0x10000, 0x20000, 0x30000


def fnv(key: int) -> int:
    result = 0xCBF29CE484222325
    for byte in (key & 0xFFFFFFFF).to_bytes(4, "little"):
        result = ((result ^ byte) * 0x100000001B3) % (1 << 64)
    return result


class Fixture:
    """Defined owned scalar backing with opt-in opaque setter/current read effects."""

    def __init__(self) -> None:
        self.memory = ReplayMemory()
        self.events: list[tuple] = []
        self.effects: dict[int, Callable[[tuple[int, ...]], int | None]] = {}
        self.after_read: Callable[[int, int, int], None] | None = None
        self.after_write: Callable[[int, int, int], None] | None = None
        self.context = ReplayTaskRebuildStorage(P, self.read, self.write)

    def map(self, address: int, width: int, value: int) -> None:
        self.memory.map_bytes(address, value.to_bytes(width, "little"))

    def read(self, address: int, width: int) -> int:
        value = self.memory.read(address, width)
        self.events.append(("r", address, width, value))
        if self.after_read is not None:
            self.after_read(address, width, value)
        return value

    def write(self, address: int, width: int, value: int) -> None:
        self.memory.write(address, width, value)
        self.events.append(("w", address, width, value))
        if self.after_write is not None:
            self.after_write(address, width, value)

    def ordinary(self, target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        self.events.append(("c", target, args, data))
        if target not in self.effects:
            raise UnresolvedReplayTaskRebuild(f"required fixture body{target:x} is unavailable")
        return self.effects[target](args)

    def bound(self, lower: ReplayTaskRebuildCalls | None = None) -> ReplayTaskRebuildCalls:
        return color.bind_replay_player_color_context(
            self.context,
            lower or ReplayTaskRebuildCalls(self.ordinary),
            bind_local=self.memory.bind_local,
            scratch=color.ReplayPlayerColorContextScratch(b"\xa5" * 4),
        )

    def call(self, target: int, *args: int) -> int:
        provider = self.bound().call
        assert provider is not None
        result = provider(target, args, None)
        assert type(result) is int
        return result

    def table(self, values: dict[int, int], *, mask: int = 0) -> tuple[int, int, dict[int, int]]:
        """Explicit coherent getter-only hash storage; no native constructor claim."""
        head = self.memory.allocate(24)
        buckets = self.memory.allocate((mask + 1) * 16)
        nodes = {key: self.memory.allocate(24) for key in values}
        for bucket in range(mask + 1):
            members = [key for key in values if fnv(key) & mask == bucket]
            first = nodes[members[-1]] if members else head  # Terminal in this source traversal.
            last = nodes[members[0]] if members else head
            self.memory.write(buckets + bucket * 16, 8, first)
            self.memory.write(buckets + bucket * 16 + 8, 8, last)
            for index, key in enumerate(members):
                next_node = nodes[members[index + 1]] if index + 1 < len(members) else head
                self.memory.write(nodes[key] + 8, 8, next_node)
                self.memory.write(nodes[key] + 16, 4, key)
                self.memory.write(nodes[key] + 20, 4, values[key])
        self.map(S + 0x50, 8, head)
        self.map(S + 0x60, 8, buckets)
        self.map(S + 0x78, 8, mask)
        return head, buckets, nodes


@pytest.mark.parametrize("sentinel", [0, 7, 0xFFFFFFFF])
def test_observer_sentinel_returns_before_all_vector_reads(sentinel: int) -> None:
    f = Fixture()
    f.map(W + 0x6B0, 4, sentinel)
    f.map(SENTINEL, 4, sentinel)
    assert f.call(OBSERVER, W) == 0
    assert f.events == [("r", W + 0x6B0, 4, sentinel), ("r", SENTINEL, 4, sentinel)]


@pytest.mark.parametrize(("index", "expected"), [(0, 0xA000), (1, 0xB000), (2, 0)])
def test_observer_uses_sixteen_byte_pairs_and_unsigned_bounds(index, expected) -> None:
    f = Fixture()
    begin = f.memory.allocate(32)
    f.memory.write(begin, 8, 0xA000)
    f.memory.write(begin + 16, 8, 0xB000)
    f.map(W + 0x6B0, 4, index)
    f.map(SENTINEL, 4, 0xFFFFFFFF)
    f.map(W + 0x768, 8, begin)
    f.map(W + 0x770, 8, begin + 32)
    assert f.call(OBSERVER, W) == expected
    assert not any(row[0] == "r" and row[1] in (begin + 8, begin + 24) for row in f.events)


def test_negative_sar_count_keeps_unsigned_bits_instead_of_clamping() -> None:
    f = Fixture()
    begin = f.memory.allocate(16)
    f.memory.write(begin, 8, 0xA000)
    f.map(W + 0x6B0, 4, 0)
    f.map(SENTINEL, 4, 0xFFFFFFFF)
    f.map(W + 0x768, 8, begin)
    f.map(W + 0x770, 8, begin - 16)
    assert f.call(OBSERVER, W) == 0xA000  # SAR(-16,4) rawu64 isFFFFFFFFFFFFFFFF.


def test_observer_holds_index_and_begin_across_current_reads() -> None:
    f = Fixture()
    begin, late = f.memory.allocate(16), f.memory.allocate(16)
    f.memory.write(begin, 8, 0xA000)
    f.memory.write(late, 8, 0xB000)
    f.map(W + 0x6B0, 4, 0)
    f.map(SENTINEL, 4, 0xFFFFFFFF)
    f.map(W + 0x768, 8, begin)
    f.map(W + 0x770, 8, begin + 16)

    def change(address: int, _width: int, _value: int) -> None:
        if address == W + 0x768:
            f.memory.write(W + 0x768, 8, late)
            f.memory.write(W + 0x6B0, 4, 1)

    f.after_read = change
    assert f.call(OBSERVER, W) == 0xA000


def test_sentinel_and_missing_or_undefined_backing_are_current_not_defaulted() -> None:
    f = Fixture()
    f.map(W + 0x6B0, 4, 0)
    with pytest.raises(ReplayMemoryError, match="unmapped"):
        f.call(OBSERVER, W)
    f.map(SENTINEL, 4, 0)
    assert f.call(OBSERVER, W) == 0
    f.memory.write(SENTINEL, 4, 1)
    with pytest.raises(ReplayMemoryError, match="unmapped"):
        f.call(OBSERVER, W)


def test_index_getter_alias_preserves_held_read_and_returns_exact_output() -> None:
    f = Fixture()
    f.map(W + 0x6B0, 4, 0xFFFFFFFF)
    f.after_read = lambda _a, _w, _v: f.memory.write(W + 0x6B0, 4, 7)
    assert f.call(INDEX, W, W + 0x6B0) == W + 0x6B0
    assert f.memory.read(W + 0x6B0, 4) == 0xFFFFFFFF
    assert f.events == [("r", W + 0x6B0, 4, 0xFFFFFFFF), ("w", W + 0x6B0, 4, 0xFFFFFFFF)]


@pytest.mark.parametrize(
    ("selected", "query", "expected"), [(2, 2, 1), (2, 1, 0), (0xFFFFFFFF, 0xFFFFFFFF, 1)]
)
def test_owner_composes_real_twelve_byte_getter(selected, query, expected) -> None:
    f = Fixture()
    f.map(P + 8, 8, W)
    f.map(P + 0x648, 4, query)
    f.map(W + 0x6B0, 4, selected)
    assert f.call(OWNER, P) == expected
    assert not any(row[0] == "c" for row in f.events)
    assert [row[1:3] for row in f.events if row[0] == "r"][:2] == [(P + 8, 8), (W + 0x6B0, 4)]


def test_owner_reads_returned_pointer_then_current_id_after_opaque_getter() -> None:
    f = Fixture()
    returned = f.memory.allocate(4)
    f.memory.write(returned, 4, 9)
    f.map(P + 8, 8, W)
    f.map(P + 0x648, 4, 1)

    def getter(args: tuple[int, ...]) -> int:
        assert args[0] == W
        f.memory.write(args[1], 4, 1)
        f.memory.write(P + 0x648, 4, 9)
        return returned  # Explicit alternate getter-boundary fixture, not native12B behavior.

    f.effects[INDEX] = getter
    assert (
        color.is_replay_player_color_observer(
            f.context,
            P,
            calls=ReplayTaskRebuildCalls(f.ordinary),
            bind_local=f.memory.bind_local,
            scratch=color.ReplayPlayerColorContextScratch(b"\xa5" * 4),
        )
        == 1
    )
    assert f.events[-2:] == [("r", returned, 4, 9), ("r", P + 0x648, 4, 9)]


def test_owner_unprovided_getter_refuses_without_reading_player_id() -> None:
    f = Fixture()
    f.map(P + 8, 8, W)
    with pytest.raises(UnresolvedReplayTaskRebuild, match="141603db0"):
        color.is_replay_player_color_observer(
            f.context,
            P,
            calls=ReplayTaskRebuildCalls(f.ordinary),
            bind_local=f.memory.bind_local,
            scratch=color.ReplayPlayerColorContextScratch(bytes(4)),
        )
    assert [row[0] for row in f.events] == ["r", "c"]


@pytest.mark.parametrize("key", [0x94, 0x9A, (1 << 63) + 0x94])
def test_special_disabled_setting_returns_before_unbacked_context(key: int) -> None:
    f = Fixture()
    f.map(ENABLED, 1, 0)
    assert f.call(SETTING, S, key) == 1
    assert f.events == [("r", ENABLED, 1, 0)]


@pytest.mark.parametrize("key", [0, 0x6A, 0x49, 0x3C, 0xFFFFFFFF])
def test_empty_bucket_returns_zero_without_terminal_or_head_data(key: int) -> None:
    f = Fixture()
    f.map(ENABLED, 1, 0)
    head, buckets, _nodes = f.table({}, mask=7)
    assert f.call(SETTING, S, key) == 0
    bucket = buckets + (fnv(key) & 7) * 16
    assert f.events == [
        ("r", ENABLED, 1, 0),
        ("r", S + 0x50, 8, head),
        ("r", S + 0x78, 8, 7),
        ("r", S + 0x60, 8, buckets),
        ("r", bucket + 8, 8, head),
    ]


@pytest.mark.parametrize(
    ("key", "expected"),
    [(0x6A, 7), (0x49, 0xFFFFFFFF), (0x3C, 3), (0xAABBCCDD00000049, 0xFFFFFFFF)],
)
def test_inclusive_collision_chain_finds_head_middle_and_terminal(key, expected) -> None:
    f = Fixture()
    f.map(ENABLED, 1, 1)
    _head, _buckets, nodes = f.table({0x6A: 7, 0x49: 0xFFFFFFFF, 0x3C: 3})
    assert f.call(SETTING, S, key) == expected
    assert f.events[-1] == ("r", nodes[key & 0xFFFFFFFF] + 20, 4, expected)
    assert not any(row[0] == "c" for row in f.events)


@pytest.mark.parametrize("key", [0x01020304, 0x04030201, 0x11223344])
def test_fnv_uses_all_four_little_endian_key_bytes(key: int) -> None:
    f = Fixture()
    f.map(ENABLED, 1, 1)
    values = {0x01020304: 11, 0x04030201: 22, 0x11223344: 33}
    _head, buckets, _nodes = f.table(values, mask=255)
    assert f.call(SETTING, S, key) == values[key]
    assert f.events[4][1] == buckets + (fnv(key) & 255) * 16 + 8


def test_missing_after_inclusive_terminal_skips_terminal_next_pointer() -> None:
    f = Fixture()
    f.map(ENABLED, 1, 1)
    _head, _buckets, nodes = f.table({1: 11, 2: 22})
    assert f.call(SETTING, S, 3) == 0
    assert not any(row[:3] == ("r", nodes[2] + 8, 8) for row in f.events)
    assert f.events[-1] == ("r", nodes[2] + 16, 4, 2)


def test_found_value_is_current_after_key_read_hook() -> None:
    f = Fixture()
    f.map(ENABLED, 1, 1)
    _head, _buckets, nodes = f.table({0x49: 2})
    f.after_read = lambda a, _w, _v: (
        f.memory.write(nodes[0x49] + 20, 4, 9) if a == nodes[0x49] + 16 else None
    )
    assert f.call(SETTING, S, 0x49) == 9


def test_special_setter_uses_current_global_but_holds_entry_settings() -> None:
    f = Fixture()
    f.map(ENABLED, 1, 1)
    f.map(ONCE, 1, 0)
    f.map(GLOBAL, 8, 0xDEAD0000)
    _head, _buckets, nodes = f.table({0x94: 5})

    def setter(args: tuple[int, ...]) -> None:
        assert args == (0xDEAD0000, 0x94, 0)
        assert f.memory.read(ONCE, 1) == 1  # Store-before-child is observable.
        f.memory.write(GLOBAL, 8, 0xBEEF0000)
        f.memory.write(nodes[0x94] + 20, 4, 13)

    f.effects[SETTER] = setter  # Explicit opaque effect, not656B implementation.
    assert f.call(SETTING, S, 0x94) == 13
    assert [row for row in f.events if row[0] in ("w", "c")] == [
        ("w", ONCE, 1, 1),
        ("c", SETTER, (0xDEAD0000, 0x94, 0), None),
    ]


def test_setter_failure_preserves_flag_before_any_map_read() -> None:
    f = Fixture()
    f.map(ENABLED, 1, 1)
    f.map(ONCE, 1, 0)
    f.map(GLOBAL, 8, S)
    with pytest.raises(UnresolvedReplayTaskRebuild, match="140984210"):
        f.call(SETTING, S, 0x94)
    assert f.memory.read(ONCE, 1) == 1
    assert not any(row[:3] == ("r", S + 0x50, 8) for row in f.events)


def test_setter_receiver_is_held_before_flag_store_hook() -> None:
    f = Fixture()
    f.map(ENABLED, 1, 1)
    f.map(ONCE, 1, 0)
    f.map(GLOBAL, 8, 0xDEAD0000)
    f.table({0x94: 5})
    f.after_write = lambda a, _w, _v: f.memory.write(GLOBAL, 8, 0xBEEF0000) if a == ONCE else None

    def setter(args: tuple[int, ...]) -> None:
        assert args == (0xDEAD0000, 0x94, 0)
        assert f.memory.read(GLOBAL, 8) == 0xBEEF0000

    f.effects[SETTER] = setter
    assert f.call(SETTING, S, 0x94) == 5


def test_mask_and_bucket_pointer_are_current_after_held_head_read() -> None:
    f = Fixture()
    f.map(ENABLED, 1, 1)
    head, _old_buckets, _nodes = f.table({}, mask=7)
    current = f.memory.allocate(16)
    f.memory.write(current + 8, 8, head)

    def change(address: int, _width: int, _value: int) -> None:
        if address == S + 0x50:
            f.memory.write(S + 0x78, 8, 0)
            f.memory.write(S + 0x60, 8, current)

    f.after_read = change
    assert f.call(SETTING, S, 0x49) == 0
    assert f.events[2:] == [
        ("r", S + 0x78, 8, 0),
        ("r", S + 0x60, 8, current),
        ("r", current + 8, 8, head),
    ]


def test_special_already_set_flag_skips_global_context_and_setter() -> None:
    f = Fixture()
    f.map(ENABLED, 1, 1)
    f.map(ONCE, 1, 2)
    f.table({0x94: 4})
    assert f.call(SETTING, S, 0x94) == 4
    assert not any(row[0] == "c" for row in f.events)


@pytest.mark.parametrize(("nested", "expected"), [(0, 1), (1, 2), (0xFFFFFFFF, 2)])
def test_de_derived_value_recurses_through_real_setting_body(nested, expected) -> None:
    f = Fixture()
    f.map(ENABLED, 1, 1)
    f.table({0xDE: 0xFFFFFFFF, 0x3B: nested})
    assert f.call(SETTING, S, 0xDE) == expected
    assert sum(row[:3] == ("r", ENABLED, 1) for row in f.events) == 2


def test_other_de_value_skips_derived_lookup() -> None:
    f = Fixture()
    f.map(ENABLED, 1, 1)
    f.table({0xDE: 7})
    assert f.call(SETTING, S, 0xDE) == 7
    assert sum(row[:3] == ("r", ENABLED, 1) for row in f.events) == 1


def test_direct_unprovided_recursive_body_is_not_synthesized() -> None:
    f = Fixture()
    f.map(ENABLED, 1, 1)
    f.table({0xDE: 0xFFFFFFFF})
    with pytest.raises(UnresolvedReplayTaskRebuild, match="14097fb40"):
        color.read_replay_player_color_setting(
            f.context, S, 0xDE, calls=ReplayTaskRebuildCalls(f.ordinary)
        )


def test_current_head_mask_and_bucket_reads_follow_special_child() -> None:
    f = Fixture()
    f.map(ENABLED, 1, 1)
    f.map(ONCE, 1, 0)
    f.map(GLOBAL, 8, S)
    old_head, _buckets, _nodes = f.table({})
    new_head = f.memory.allocate(24)

    def setter(_args: tuple[int, ...]) -> None:
        f.memory.write(S + 0x50, 8, new_head)

    f.effects[SETTER] = setter
    # The old bucket last now differs from current head; its uninitialized node key must fail.
    with pytest.raises(ReplayMemoryError, match="undefined"):
        f.call(SETTING, S, 0x94)
    assert ("r", S + 0x50, 8, new_head) in f.events
    assert ("r", old_head + 16, 4, 0) not in f.events


def test_complete_color_consumer_composes_real_mode_and_four_context_bodies() -> None:
    f = Fixture()
    observer, game, descriptor = 0x40000, 0x50000, 0x60000
    f.map(ENABLED, 1, 1)
    f.map(GLOBAL, 8, S)
    f.map(S + 0x151, 1, 1)
    f.table({0x6A: 0, 0x49: 0, 0x3C: 0})  # Explicit owned viewer policy values.
    f.map(0x144353698, 8, game)
    f.map(game + 0x560, 8, descriptor)
    f.map(descriptor + 8, 4, 0)  # Declared test Game profile, not startup inference.
    f.map(P + 8, 8, W)
    f.map(P + 0x648, 4, 1)
    f.map(P + 0x1F4, 4, 0)
    for offset in (0x200, 0x1F8):
        f.map(P + offset, 8, 0)
    for offset in (0x650, 0x654, 0x658):
        f.map(P + offset, 4, 0)
    f.map(W + 0x6B0, 4, 0)
    f.map(SENTINEL, 4, 0xFFFFFFFF)
    pairs = f.memory.allocate(32)
    f.memory.write(pairs, 8, observer)
    f.memory.write(pairs + 16, 8, P)
    f.map(W + 0x768, 8, pairs)
    f.map(W + 0x770, 8, pairs + 32)
    relations = f.memory.allocate(2)
    f.memory.write(relations + 1, 1, 0)
    f.map(observer + 0x180, 8, relations)
    table = f.memory.allocate(32)
    colors = [f.memory.allocate(0x38) for _ in range(4)]
    for ordinal, address in enumerate(colors):
        f.memory.write(table + ordinal * 8, 8, address)
        f.memory.write(address + 4, 4, 7 if ordinal == 3 else ordinal)
    f.map(W + 0xE8, 8, table)
    f.memory.map_bytes(0x1432F46B0, b"".join((0x100 + i).to_bytes(4, "little") for i in range(16)))
    f.map(0x1444167AF, 1, 0xA5)
    lower = bind_replay_base_saved_registration(
        f.context,
        ReplayTaskRebuildCalls(f.ordinary),
        imports=ReplayTaskRebuildCalls(f.ordinary),
        fp_calls=ReplayBaseSavedRegistrationFP(None),
        bind_local=f.memory.bind_local,
        scratch=ReplayBaseSavedRegistrationScratch(bytes(0xB0)),
    )
    set_replay_player_color(f.context, P, 2, calls=f.bound(lower))
    assert f.memory.read(P + 0x200, 8) == colors[2]
    assert f.memory.read(P + 0x1F8, 8) == colors[3]
    assert tuple(f.memory.read(P + offset, 4) for offset in (0x650, 0x654, 0x658)) == (
        0x108,
        0xA5,
        0x108,
    )
    assert not any(row[0] == "c" for row in f.events)
    with pytest.raises(ReplayMemoryError, match="undefined"):
        f.memory.read(colors[3], 4)  # No invented full descriptor initialization.


@pytest.mark.parametrize(
    ("target", "args"), [(OBSERVER, (W, 0)), (INDEX, (W,)), (OWNER, (P, 1)), (SETTING, (S,))]
)
def test_bound_arity_and_payload_are_strict(target, args) -> None:
    f = Fixture()
    provider = f.bound().call
    assert provider is not None
    with pytest.raises(ValueError, match="malformed"):
        provider(target, args, None)
    with pytest.raises(ValueError, match="malformed"):
        provider(OWNER, (P,), memoryview(bytearray(1)))
    assert f.events == []


@pytest.mark.parametrize("bad", [True, -1, 1 << 64])
def test_raw_argument_validation_precedes_effects(bad: int) -> None:
    f = Fixture()
    provider = f.bound().call
    assert provider is not None
    with pytest.raises(ValueError, match="argument"):
        provider(SETTING, (S, bad), None)
    assert f.events == []


@pytest.mark.parametrize("seed", [b"", bytes(3), bytes(5), bytearray(4)])
def test_explicit_seed_width_and_type(seed) -> None:
    with pytest.raises(ValueError, match="explicit4B"):
        color.ReplayPlayerColorContextScratch(seed)


def test_unknown_call_delegates_original_tuple_and_payload() -> None:
    f = Fixture()
    f.effects[0xAA] = lambda args: len(args)
    provider = f.bound().call
    assert provider is not None
    payload = memoryview(bytearray(7))
    assert provider(0xAA, (1, 2), payload) == 2
    assert f.events == [("c", 0xAA, (1, 2), payload)]
