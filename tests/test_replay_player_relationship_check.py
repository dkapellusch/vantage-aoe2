"""Source-led188B controls, including the actual423 caller over owned memory."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from vantage.replay_memory import ReplayMemory
from vantage.replay_player_relationship_check import (
    bind_replay_player_relationship_check,
    check_replay_player_relationship,
)
from vantage.replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
)
from vantage.replay_world_update_player_links import (
    ReplayWorldUpdatePlayerLinksReentry,
    run_replay_world_update_player_links,
)

U32, U64 = (1 << 32) - 1, (1 << 64) - 1
COUNT, PREDICATE, RELATION = 0x141603F30, 0x1416B69F0, 0x141734D70


class Rig:
    def __init__(self) -> None:
        self.memory = ReplayMemory(start=0x10000)
        self.events: list[tuple] = []
        self.after_read: Callable[[int, int], None] | None = None
        self.on_call: Callable[[int, tuple[int, ...]], int | None] | None = None
        self.receiver = self.alloc(0x700)
        self.index, self.home, self.table = self.alloc(8), self.alloc(0x400), self.alloc(256)
        self.put(self.index, 4, 1)
        self.put(self.receiver + 0x648, 4, 10)
        self.put(self.receiver + 8, 8, 0x888)
        self.put(self.receiver + 0x180, 8, self.table)
        self.count, self.count_result, self.predicate = 20, self.home, 0
        self.context = ReplayTaskRebuildStorage(self.receiver, self.read, self.write)
        self.calls = ReplayTaskRebuildCalls(self.call)

    def alloc(self, size: int) -> int:
        address = self.memory.allocate(size)
        self.memory.write_bytes(address, b"\xa5" * size)
        return address

    def put(self, address: int, width: int, value: int) -> None:
        self.memory.write(address & U64, width, value & ((1 << (width * 8)) - 1))

    def get(self, address: int, width: int = 8) -> int:
        return self.memory.read(address & U64, width)

    def read(self, address: int, width: int) -> int:
        self.events.append(("read", address, width))
        value = self.get(address, width)
        if self.after_read:
            self.after_read(address, width)
        return value

    def write(self, address: int, width: int, value: int) -> None:
        self.events.append(("write", address, width, value))
        self.put(address, width, value)

    def call(self, target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        assert data is None
        self.events.append(("call", target, args))
        if self.on_call:
            return self.on_call(target, args)
        if target == COUNT:
            assert args == (0x888, self.home)
            self.put(self.home, 4, self.count)
            return self.count_result
        assert target == PREDICATE and args == (0x888,)
        return self.predicate

    def run(self, flag: int = 1, calls: ReplayTaskRebuildCalls | None = None) -> int:
        return check_replay_player_relationship(
            self.context,
            self.calls if calls is None else calls,
            self.receiver,
            self.index,
            flag,
            count_home=self.home,
        )

    def bound(self, calls: ReplayTaskRebuildCalls | None = None) -> ReplayTaskRebuildCalls:
        return bind_replay_player_relationship_check(
            self.context,
            self.calls if calls is None else calls,
            count_home=self.home,
        )


@pytest.mark.parametrize("index,self_index,expected", [(0, 0, 1), (0, 2, 0), (2, 2, 1)])
def test_entry_self_guard_precedes_initial_zero_guard(
    index: int,
    self_index: int,
    expected: int,
) -> None:
    r = Rig()
    r.put(r.index, 4, index)
    r.put(r.receiver + 0x648, 4, self_index)
    assert r.run(calls=ReplayTaskRebuildCalls(None)) == expected
    assert r.events == [("read", r.index, 4), ("read", r.receiver + 0x648, 4)]
    assert r.get(r.home) == 0xA5A5A5A5A5A5A5A5


def test_initial_index_is_held_while_self_is_current() -> None:
    r = Rig()

    def after(at: int, width: int) -> None:
        if at == r.index:
            r.put(r.index, 4, 7)
            r.put(r.receiver + 0x648, 4, 1)

    r.after_read = after
    assert r.run() == 1
    assert len(r.events) == 2


def test_count_uses_actual_returned_pointer_and_samples_index_before_pointee() -> None:
    r = Rig()
    actual = r.alloc(8)
    r.put(actual, 4, 5)
    r.put(r.table + 2, 1, 4)

    def child(target: int, args: tuple[int, ...]) -> int:
        assert target == COUNT and args == (0x888, r.home)
        assert r.get(r.home) == 0xA5A5A5A5A5A5A5A5
        r.put(r.home, 4, 0)
        r.put(r.index, 4, 2)
        return actual

    r.on_call = child
    assert r.run() == 1
    k = r.events.index(("call", COUNT, (0x888, r.home)))
    assert r.events[k + 1 : k + 4] == [
        ("read", r.index, 4),
        ("read", actual, 4),
        ("read", r.receiver + 0x648, 4),
    ]
    assert ("read", r.home, 4) not in r.events
    assert r.get(r.home) == 0xA5A5A5A500000000


def test_count_is_current_after_the_post_count_index_sample() -> None:
    r = Rig()
    samples = 0

    def after(at: int, width: int) -> None:
        nonlocal samples
        if at == r.index:
            samples += 1
            if samples == 2:
                r.put(r.home, 4, 0)

    r.after_read = after
    assert r.run() == 0
    assert r.events[-2:] == [("read", r.index, 4), ("read", r.home, 4)]


@pytest.mark.parametrize("index,count", [(1, 0), (1, 1), (U32, U32), (0x80000000, 2)])
def test_count_guard_is_unsigned_and_inclusive(index: int, count: int) -> None:
    r = Rig()
    r.put(r.index, 4, index)
    r.count = count
    assert r.run() == 0
    assert r.events[-1] == ("read", r.home, 4)
    assert r.events.count(("read", r.receiver + 0x648, 4)) == 1


def test_second_current_self_equality_returns_false() -> None:
    r = Rig()

    def child(target: int, args: tuple[int, ...]) -> int:
        assert target == COUNT
        r.put(r.index, 4, 3)
        r.put(r.receiver + 0x648, 4, 3)
        r.put(r.home, 4, 20)
        return r.home

    r.on_call = child
    assert r.run() == 0
    assert r.events[-1] == ("read", r.receiver + 0x648, 4)


@pytest.mark.parametrize(
    "flag,byte,expected,calls",
    [
        (2, 4, 1, 1),
        (128, 4, 1, 1),
        (255, 4, 1, 1),
        (0, 4, 0, 2),
        (0, 0, 1, 1),
        (1, 0, 1, 1),
    ],
)
def test_flag_is_whole_byte_and_zero_skips_the_first_table_sample(
    flag: int,
    byte: int,
    expected: int,
    calls: int,
) -> None:
    r = Rig()
    r.put(r.table + 1, 1, byte)
    assert r.run(flag) == expected
    assert sum(e[0] == "call" for e in r.events) == calls
    table_reads = [e for e in r.events if e == ("read", r.receiver + 0x180, 8)]
    assert len(table_reads) == (2 if flag and byte == 0 else 1)


def test_second_table_base_is_fresh_but_post_count_index_is_held() -> None:
    r = Rig()
    other = r.alloc(256)
    r.put(r.table + 1, 1, 2)
    r.put(other + 1, 1, 0)
    r.put(other + 3, 1, 2)

    def after(at: int, width: int) -> None:
        if at == r.table + 1:
            r.put(r.receiver + 0x180, 8, other)
            r.put(r.index, 4, 3)

    r.after_read = after
    assert r.run() == 1
    assert r.events[-2:] == [("read", r.receiver + 0x180, 8), ("read", other + 1, 1)]
    assert r.events.count(("read", r.index, 4)) == 2


@pytest.mark.parametrize("eax,expected", [(0, 0), (0x100, 1), (0x80000000, 1), (U32, 1)])
def test_predicate_consumes_full_eax_annotation(eax: int, expected: int) -> None:
    r = Rig()
    r.put(r.table + 1, 1, 1)
    r.predicate = eax
    assert r.run() == expected
    assert r.events.count(("read", r.index, 4)) == (3 if eax else 2)


def test_predicate_game_is_fresh_and_zero_flag_stops_without_final_reads() -> None:
    r = Rig()
    r.put(r.table + 1, 1, 2)

    def after(at: int, width: int) -> None:
        if at == r.table + 1:
            r.put(r.receiver + 8, 8, 0x999)

    def child(target: int, args: tuple[int, ...]) -> int:
        if target == COUNT:
            r.put(r.home, 4, 20)
            return r.home
        assert target == PREDICATE and args == (0x999,)
        return 0x100

    r.after_read, r.on_call = after, child
    assert r.run(0) == 0
    assert r.events[-1] == ("call", PREDICATE, (0x999,))


def test_final_base_precedes_new_index_with_no_new_count_or_self_guard() -> None:
    r = Rig()
    other = r.alloc(256)
    r.put(r.table + 1, 1, 2)
    r.put(r.table + 30, 1, 1)
    r.put(other + 30, 1, 0)

    def child(target: int, args: tuple[int, ...]) -> int:
        if target == COUNT:
            r.put(r.home, 4, 2)
            return r.home
        assert target == PREDICATE
        r.put(r.index, 4, 30)
        r.put(r.receiver + 0x648, 4, 30)
        return 1

    def after(at: int, width: int) -> None:
        if at == r.index and r.get(r.index, 4) == 30:
            r.put(r.receiver + 0x180, 8, other)

    r.on_call, r.after_read = child, after
    assert r.run() == 1
    assert r.events[-3:] == [
        ("read", r.receiver + 0x180, 8),
        ("read", r.index, 4),
        ("read", r.table + 30, 1),
    ]
    assert r.events.count(("read", r.home, 4)) == 1
    assert r.events.count(("read", r.receiver + 0x648, 4)) == 2


@pytest.mark.parametrize(
    "target,bad",
    [
        (COUNT, None),
        (COUNT, -1),
        (COUNT, 1 << 64),
        (COUNT, True),
        (PREDICATE, None),
        (PREDICATE, -1),
        (PREDICATE, 1 << 32),
        (PREDICATE, True),
    ],
)
def test_invalid_consumed_child_word_refuses_at_its_actual_prefix(
    target: int,
    bad: int | None,
) -> None:
    r = Rig()

    def child(at: int, args: tuple[int, ...]) -> int | None:
        if at == target:
            return bad
        assert at == COUNT
        r.put(r.home, 4, 20)
        return r.home

    r.on_call = child
    with pytest.raises(ValueError):
        r.run()
    if target == COUNT:
        assert r.events[-2][0:2] == ("call", COUNT)
        assert r.events[-1] == ("read", r.index, 4)
    else:
        assert r.events[-1][0:2] == ("call", PREDICATE)


@pytest.mark.parametrize("target", [COUNT, PREDICATE])
def test_missing_reached_actual_child_preserves_prefix(target: int) -> None:
    r = Rig()

    def child(at: int, args: tuple[int, ...]) -> int:
        if at == target:
            raise UnresolvedReplayTaskRebuild("unavailable actual child")
        r.put(r.home, 4, 20)
        return r.home

    r.on_call = child
    with pytest.raises(UnresolvedReplayTaskRebuild):
        r.run()
    assert r.events[-1][0:2] == ("call", target)


@pytest.mark.parametrize(
    "slot,value",
    [
        ("receiver", -1),
        ("index_address", 1 << 64),
        ("flag", True),
        ("flag", -1),
        ("flag", 256),
        ("count_home", True),
        ("count_home", 1 << 64),
        ("context", None),
        ("calls", None),
    ],
)
def test_public_admission_precedes_all_source_effects(slot: str, value: object) -> None:
    r = Rig()
    args = dict(
        context=r.context,
        calls=r.calls,
        receiver=r.receiver,
        index_address=r.index,
        flag=1,
        count_home=r.home,
    )
    args[slot] = value
    with pytest.raises(ValueError):
        check_replay_player_relationship(**args)
    assert not r.events


@pytest.mark.parametrize("value,mask,flag", [(2, 255, 2), (0xAB00, 255, 0), (U64, U64, 255)])
def test_binder_uses_only_defined_low_byte(value: int, mask: int, flag: int) -> None:
    r = Rig()
    r.put(r.table + 1, 1, 4)
    bound = r.bound()
    assert bound.call is not None
    assert bound.call(RELATION, (r.receiver, r.index, value, mask), None) == int(flag != 0)


@pytest.mark.parametrize(
    "args,data",
    [
        ((), None),
        ((1, 2, 3), None),
        ((1, 2, 3, 255, 5), None),
        ((1, 2, 3, 255), memoryview(b"x")),
        ((1, 2, 3, 254), None),
        ((1, 2, 3, 0), None),
        ((-1, 2, 3, 255), None),
        ((1, True, 3, 255), None),
        ((1, 2, 1 << 64, 255), None),
        ((1, 2, 3, 1 << 64), None),
    ],
)
def test_owned_binder_arity_data_mask_and_words_fail_before_effects(
    args: tuple[int, ...],
    data: memoryview | None,
) -> None:
    r = Rig()
    bound = r.bound()
    assert bound.call is not None
    with pytest.raises(ValueError):
        bound.call(RELATION, args, data)
    assert not r.events


def test_unknown_dispatch_preserves_argument_data_and_result_identity() -> None:
    r = Rig()
    args, data = (1, 2), memoryview(b"abc")
    result = int("123456789012345678901234567890")

    def other(target: int, actual: tuple[int, ...], view: memoryview | None) -> int:
        assert target == 0xDEAD and actual is args and view is data
        return result

    bound = r.bound(ReplayTaskRebuildCalls(other))
    assert bound.call is not None and bound.call(0xDEAD, args, data) is result
    assert not r.events
    missing = r.bound(ReplayTaskRebuildCalls(None))
    assert missing.call is not None
    with pytest.raises(UnresolvedReplayTaskRebuild):
        missing.call(0xDEAD, args, data)


@pytest.mark.parametrize("slot,bad", [("context", None), ("calls", None), ("count_home", -1)])
def test_binder_construction_validates_without_source_access(slot: str, bad: object) -> None:
    r = Rig()
    args = dict(context=r.context, calls=r.calls, count_home=r.home)
    args[slot] = bad
    with pytest.raises(ValueError):
        bind_replay_player_relationship_check(**args)
    assert not r.events


@pytest.mark.parametrize("counts,virtuals", [([3, 3], 1), ([1], 0), ([3, 2], 0)])
def test_actual_world_caller_composes_relationships_with_shared_frame_zero_home(
    counts: list[int],
    virtuals: int,
) -> None:
    r = Rig()
    world, frame = r.alloc(0xA00), r.home
    players = [r.alloc(0x700) for _ in range(3)]
    array = r.alloc(48)
    for i, player in enumerate(players):
        r.put(array + 16 * i, 8, player)
        r.put(player + 0x648, 4, i + 1)
        r.put(player + 8, 8, 0x880 + i)
        table = r.alloc(256)
        r.put(table + 1, 1, 4)
        r.put(table + 2, 1, 4)
        r.put(player + 0x180, 8, table)
        vptr = r.alloc(0x330)
        r.put(player, 8, vptr)
        r.put(vptr + 0x328, 8, 0xAA328)
    # Both relationships must pass entry guards: first receiverP2/index1;
    # second receiverP1/index2. P1 self1 makes the second distinct as well.
    r.put(players[1] + 0x648, 4, 1)
    r.put(world + 0x768, 8, array)
    r.put(world + 0x770, 8, array + 48)
    r.put(world + 0x7C, 4, 7)
    r.put(world + 0x194, 4, 10)
    r.put(frame + 0x27C, 4, 0)
    r.memory.map_bytes(0x14435505D, b"\0")
    seen: list[tuple[int, tuple[int, ...]]] = []
    values = iter(counts)

    def children(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        assert data is None
        seen.append((target, args))
        if target == 0x141711B80:
            assert args == (players[2],)
            return None
        assert target == COUNT
        assert args[1] == frame
        r.put(frame, 4, next(values))
        return frame

    def virtual(target: int, args: tuple[int, ...], data: memoryview | None) -> None:
        assert data is None and target == 0xAA328 and args == (players[1], frame + 0xA0)
        seen.append((target, args))

    calls = ReplayTaskRebuildCalls(children)
    relations = bind_replay_player_relationship_check(r.context, calls, count_home=frame)
    phase = ReplayWorldUpdatePlayerLinksReentry(
        world,
        frame,
        0,
        1,
        0,
        0,
        0,
        2,
        0,
        0x141629C90,
        None,
    )
    result = run_replay_world_update_player_links(
        r.context,
        calls,
        phase,
        logger_home_calls=ReplayTaskRebuildCalls(None),
        relationship_calls=relations,
        virtual_calls=ReplayTaskRebuildCalls(virtual),
    )
    expected_counts = [(COUNT, (0x882, frame))]
    if len(counts) == 2:
        expected_counts.append((COUNT, (0x881, frame)))
    assert [e for e in seen if e[0] == COUNT] == expected_counts
    assert sum(e[0] == 0xAA328 for e in seen) == virtuals
    assert r.get(frame) == (0xA5A5A5A5 << 32) | counts[-1]
    assert r.get(frame + 0x27C, 4) == virtuals
    assert result.held_r13 == players[2] and result.inner_index == 3
    assert result.marker_address == frame + 0x280 and result.next_address == 0x141629E00
