"""Owned string graph and source-derived chronology/alias/partial-effect controls."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from vantage import replay_player_identifier_strings as strings
from vantage.replay_memory import ReplayMemory, ReplayMemoryError
from vantage.replay_player_civilization_lookup import bind_replay_player_civilization_lookup
from vantage.replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
)
from vantage.replay_unit_constructor_support import bind_replay_unit_constructor_support

D, S, ID, EMPTY = 0x1000, 0x2000, 0x3000, 0x14428BB30
CLEAR, COPY, MOVE, ASSIGN = 0x140A1A7E0, 0x140A15B60, 0x140A15AD0, 0x1416607B0
GROW, MEMCPY, FREE, DESTROY = 0x140A1A5E0, 0x142D6E3B1, 0x142D6C270, 0x140A1B220


class Fixture:
    def __init__(self) -> None:
        self.memory = ReplayMemory(max_bytes=1 << 20)
        self.events: list[tuple[object, ...]] = []
        self.before_child: Callable[[int, tuple[int, ...]], None] | None = None
        self.after_child: Callable[[int, tuple[int, ...]], None] | None = None
        self.after_read: Callable[[int, int], None] | None = None
        self.context = ReplayTaskRebuildStorage(D, self.read, self.write)
        self.runtime = self.memory.runtime_calls()
        self.memory.map_bytes(0x143199DD0, (0x142D6BAB4).to_bytes(8, "little"))
        self.memory.map_bytes(0x143199930, (0x142D6E3DB).to_bytes(8, "little"))
        self.calls = ReplayTaskRebuildCalls(self.dispatch)
        self.bound = strings.bind_replay_player_identifier_strings(self.context, self.calls)
        self.support = bind_replay_unit_constructor_support(
            self.context, self.runtime, bind_local=self.memory.bind_local, imports=self.runtime
        )
        self.cleanup = bind_replay_player_civilization_lookup(
            self.context, self.calls, bind_local=self.memory.bind_local, scratch=b"\xa5" * 8
        )

    def read(self, address: int, width: int) -> int:
        value = self.memory.read(address, width)
        self.events.append(("r", address, width, value))
        if self.after_read:
            self.after_read(address, width)
        return value

    def write(self, address: int, width: int, value: int) -> None:
        self.memory.write(address, width, value)
        self.events.append(("w", address, width, value))

    def dispatch(self, target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        self.events.append(("c", target, args))
        if self.before_child:
            self.before_child(target, args)
        handler = (
            self.bound
            if target in (CLEAR, COPY, MOVE, ASSIGN)
            else self.cleanup
            if target == DESTROY
            else self.support
        )
        assert handler.call
        result = handler.call(target, args, data)
        if self.after_child:
            self.after_child(target, args)
        return result

    def header(self, address: int, pointer: int, length: int, capacity: int) -> None:
        self.memory.map_bytes(
            address, b"".join(word.to_bytes(8, "little") for word in (pointer, length, capacity))
        )

    def payload(self, raw: bytes) -> int:
        address = self.memory.allocate(len(raw))
        self.memory.write_bytes(address, raw)
        return address

    def run(self, target: int, left: int, right: int, *, bound: bool = True) -> int | None:
        if bound:
            assert self.bound.call
            return self.bound.call(target, (left, right), None)
        function = {
            CLEAR: strings.clear_replay_player_identifier_string,
            COPY: strings.copy_replay_player_identifier_string,
            MOVE: strings.move_replay_player_identifier_string,
            ASSIGN: strings.assign_replay_player_named_identifier,
        }[target]
        return function(self.context, left, right, calls=self.calls)


@pytest.mark.parametrize("entry", [COPY, MOVE])
@pytest.mark.parametrize("bound", [False, True])
def test_self_assignment_returns_without_any_backing_access(entry, bound) -> None:
    f = Fixture()
    assert f.run(entry, D, D, bound=bound) == D and f.events == []


@pytest.mark.parametrize("keep", [0, 1, 0x100, (1 << 64) - 1])
def test_zero_capacity_needs_no_pointer_or_length_backing(keep) -> None:
    f = Fixture()
    f.memory.map_bytes(D + 16, bytes(8), writable=False)
    assert f.run(CLEAR, D, keep) is None
    assert f.events == [("r", D + 16, 8, 0)]


def test_keep_low_byte_clears_length_before_current_pointer_read_and_retains_capacity() -> None:
    f = Fixture()
    old, current = f.payload(b"old"), f.payload(b"new")
    f.header(D, old, 7, 3)
    f.after_read = lambda address, _width: (
        f.memory.write(D, 8, current) if address == D + 16 else None
    )
    f.run(CLEAR, D, 0x101)
    assert f.events == [
        ("r", D + 16, 8, 3),
        ("w", D + 8, 8, 0),
        ("r", D, 8, current),
        ("w", current, 1, 0),
    ]
    assert f.memory.read_bytes(old, 3) == b"old"
    assert f.memory.read_bytes(current, 3) == b"\0ew" and f.memory.read(D + 16, 8) == 3


def test_keep_null_pointer_refuses_after_length_store() -> None:
    f = Fixture()
    f.header(D, 0, 17, 1)
    with pytest.raises(ReplayMemoryError):
        f.run(CLEAR, D, 1)
    assert f.memory.read(D + 8, 8) == 0 and f.memory.read(D + 16, 8) == 1


def test_clear_with_zero_low_byte_uses_real_free_before_ordered_header_reset() -> None:
    f = Fixture()
    pointer = f.payload(b"abc")
    f.header(D, pointer, 3, 3)
    f.run(CLEAR, D, 0x100)
    assert f.events[:3] == [("r", D + 16, 8, 3), ("r", D, 8, pointer), ("c", FREE, (pointer,))]
    assert f.events[-3:] == [("w", D, 8, EMPTY), ("w", D + 16, 8, 0), ("w", D + 8, 8, 0)]
    with pytest.raises(ReplayMemoryError):
        f.memory.read(pointer, 1)


def test_clear_null_pointer_preserves_nonzero_length_and_capacity() -> None:
    f = Fixture()
    f.header(D, 0, 91, 7)
    f.run(CLEAR, D, 0)
    assert f.memory.read(D + 8, 8) == 91 and f.memory.read(D + 16, 8) == 7
    assert not [event for event in f.events if event[0] != "r"]


@pytest.mark.parametrize("entry", [COPY, MOVE])
def test_zero_length_copy_and_move_have_distinct_pointer_and_ownership_effects(entry) -> None:
    f = Fixture()
    f.header(D, 0, 91, 7)
    f.memory.map_bytes(S + 8, bytes(8))
    if entry == MOVE:
        f.memory.map_bytes(S, (0xABCDEF).to_bytes(8, "little"))
        f.memory.map_bytes(S + 16, (12).to_bytes(8, "little"))
    assert f.run(entry, D, S) == D
    assert f.memory.read(D, 8) == (0 if entry == COPY else 0xABCDEF)
    assert f.memory.read(D + 8, 8) == (91 if entry == COPY else 0)
    assert f.memory.read(D + 16, 8) == (7 if entry == COPY else 12)


@pytest.mark.parametrize("bound", [False, True])
def test_copy_real_graph_uses_saved_length_and_raw_bytes_without_strlen(bound) -> None:
    f = Fixture()
    old = f.payload(b"old")
    raw = b"a\0\xffz"
    source = f.payload(raw)
    f.header(D, old, 3, 3)
    f.header(S, source, len(raw), len(raw))
    assert f.run(COPY, D, S, bound=bound) == D
    destination = f.memory.read(D, 8)
    assert f.memory.read_bytes(destination, 5) == raw + b"\0"
    assert f.memory.read(D + 8, 8) == 4 and f.memory.read(D + 16, 8) == 32
    assert f.memory.read_bytes(source, 4) == raw and f.memory.read(S + 8, 8) == 4
    with pytest.raises(ReplayMemoryError, match="undefined"):
        f.memory.read(destination + 5, 1)


def test_copy_reloads_source_after_growth_and_destination_after_memcpy() -> None:
    f = Fixture()
    source = f.payload(b"orig")
    changed, redirected = f.payload(b"new!"), f.payload(b"?????")
    f.header(D, 0, 0, 0)
    f.header(S, source, 4, 4)

    def mutate(target, _args):
        if target == GROW:
            f.memory.write(S, 8, changed)
            f.memory.write(S + 8, 8, 900)
        elif target == MEMCPY:
            f.memory.write(D, 8, redirected)

    f.after_child = mutate
    f.run(COPY, D, S)
    copied_to = next(event[2][0] for event in f.events if event[:2] == ("c", MEMCPY))
    assert f.memory.read_bytes(copied_to, 4) == b"new!"
    assert f.memory.read_bytes(redirected, 5) == b"????\0"
    assert f.memory.read(D + 8, 8) == 4


def test_move_uses_current_source_after_destination_free_and_keeps_allocation_identity() -> None:
    f = Fixture()
    old, first, second = f.payload(b"old"), f.payload(b"first"), f.payload(b"second")
    f.header(D, old, 3, 3)
    f.header(S, first, 5, 5)

    def mutate(target, _args):
        if target == FREE:
            f.memory.write(S, 8, second)
            f.memory.write(S + 8, 8, 6)
            f.memory.write(S + 16, 8, 19)

    f.after_child = mutate
    f.run(MOVE, D, S)
    assert [f.memory.read(D + offset, 8) for offset in (0, 8, 16)] == [second, 6, 19]
    assert [f.memory.read(S + offset, 8) for offset in (0, 8, 16)] == [EMPTY, 0, 0]
    assert f.memory.read_bytes(second, 6) == b"second"


def test_move_partial_header_overlap_reads_current_length_after_pointer_write() -> None:
    f = Fixture()
    f.memory.map_bytes(S, b"".join(word.to_bytes(8, "little") for word in (0x8888, 11, 22, 0)))
    f.run(MOVE, S + 8, S)
    assert ("r", S + 8, 8, 0x8888) in f.events
    assert ("w", S + 16, 8, 0x8888) in f.events
    assert [f.memory.read(S + offset, 8) for offset in (0, 8, 16, 24)] == [EMPTY, 0, 0, 0]


def test_named_identifier_composes_real_move_and_destructor_and_preserves_padding() -> None:
    f = Fixture()
    source = f.payload(b"name\0")
    f.header(S, source, 4, 5)
    f.memory.map_bytes(ID, b"\xa5" * 32)
    f.memory.write(ID + 8, 8, EMPTY)
    f.memory.write(ID + 16, 8, 0)
    f.memory.write(ID + 24, 8, 0)
    assert f.run(ASSIGN, ID, S) is None
    assert f.memory.read_bytes(ID, 8) == b"\0\xa5\xa5\xa5\xfe\xff\xff\xff"
    assert [f.memory.read(ID + offset, 8) for offset in (8, 16, 24)] == [source, 4, 5]
    assert [f.memory.read(S + offset, 8) for offset in (0, 8, 16)] == [EMPTY, 0, 0]
    assert f.memory.read_bytes(source, 5) == b"name\0"


@pytest.mark.parametrize("target", [FREE, GROW, MEMCPY])
def test_required_child_failure_preserves_completed_prefix(target) -> None:
    f = Fixture()
    old = f.payload(b"old")
    f.header(D, old, 3, 3)
    f.header(S, f.payload(b"abc"), 3, 3)

    def fail(selected, _args):
        if selected == target:
            raise RuntimeError("required child unavailable")

    f.before_child = fail
    with pytest.raises(RuntimeError, match="required child"):
        f.run(COPY, D, S)
    assert f.memory.read(D + 8, 8) == (3 if target == FREE else 0)
    assert f.memory.read(D + 16, 8) == (3 if target == FREE else 0 if target == GROW else 32)


@pytest.mark.parametrize("target", [MOVE, DESTROY])
def test_identifier_failure_retains_flag_and_prior_real_move(target) -> None:
    f = Fixture()
    f.memory.map_bytes(ID, bytes(32))
    pointer = f.payload(b"abc")
    f.header(S, pointer, 3, 3)

    def fail(selected, _args):
        if selected == target:
            raise RuntimeError("required move or destruction")

    f.before_child = fail
    with pytest.raises(RuntimeError, match="required move"):
        f.run(ASSIGN, ID, S, bound=False)
    assert f.memory.read(ID, 1) == 0 and f.memory.read(ID + 4, 4) == 0xFFFFFFFE
    assert f.memory.read(ID + 8, 8) == (0 if target == MOVE else pointer)


def test_identifier_binder_composes_own_move_without_circular_lower_route() -> None:
    f = Fixture()
    f.memory.map_bytes(ID, bytes(32))
    pointer = f.payload(b"abc")
    f.header(S, pointer, 3, 3)
    seen = []

    def lower(target, args, data):
        seen.append(target)
        assert target not in (CLEAR, COPY, MOVE, ASSIGN)
        if target == DESTROY:
            assert f.cleanup.call
            return f.cleanup.call(target, args, data)
        assert f.support.call
        return f.support.call(target, args, data)

    bound = strings.bind_replay_player_identifier_strings(f.context, ReplayTaskRebuildCalls(lower))
    assert bound.call and bound.call(ASSIGN, (ID, S), None) is None
    assert seen == [DESTROY]
    assert f.memory.read(ID + 8, 8) == pointer and f.memory.read(S, 8) == EMPTY


@pytest.mark.parametrize("entry", [CLEAR, COPY, MOVE, ASSIGN])
@pytest.mark.parametrize(
    "args,data",
    [
        ((D,), None),
        ((D, -1), None),
        ((D, True), None),
        ((D, 1 << 64), None),
        ((D, S), memoryview(b"x")),
    ],
)
def test_bound_malformed_inputs_refuse_before_backing_access(entry, args, data) -> None:
    f = Fixture()
    assert f.bound.call
    with pytest.raises(ValueError):
        f.bound.call(entry, args, data)
    assert not f.events


def test_unknown_target_has_no_success_default() -> None:
    f = Fixture()
    bound = strings.bind_replay_player_identifier_strings(f.context, ReplayTaskRebuildCalls(None))
    assert bound.call
    with pytest.raises(UnresolvedReplayTaskRebuild, match="1234"):
        bound.call(0x1234, (), None)
    assert not f.events
