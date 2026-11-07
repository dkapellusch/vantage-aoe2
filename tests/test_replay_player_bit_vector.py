"""Owned source-led bit-vector controls; authored callback seams are explicit."""

from __future__ import annotations

from contextlib import contextmanager

import pytest

from vantage import replay_player_bit_vector as bits
from vantage.replay_memory import ReplayMemory, ReplayMemoryError, ReplayMemoryRuntimeError
from vantage.replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
)

ASSIGN, INSERT, RESIZE, APPEND, COMMIT = (
    0x1416E4C30,
    0x1403209E0,
    0x140321420,
    0x140321870,
    0x1402BA740,
)
BIT_LENGTH, WORD_LENGTH, FATAL = 0x140322090, 0x1402BA820, 0x1402A9460
ALLOC, FREE, SET, MOVE = 0x1402A94D0, 0x142D6BAB4, 0x142D6E3B7, 0x142D6E3DB
LENGTH_IMPORT, WATSON = 0xF0A0, 0xF0A1
U64, U32, MAX = (1 << 64) - 1, (1 << 32) - 1, (1 << 62) - 1


class Fixture:
    def __init__(self, count=0, capacity=0, value=0):
        self.memory = ReplayMemory(max_bytes=2 << 20)
        self.header, self.source = self.memory.allocate(32), self.memory.allocate(4)
        words = (count + 31) // 32
        capacity = max(capacity, words)
        self.rows = self.memory.allocate_aligned(capacity * 4) if capacity else 0
        if capacity:
            self.memory.fill(self.rows, 0, capacity * 4)
            for i in range(words):
                self.memory.write(self.rows + i * 4, 4, (value >> (i * 32)) & U32)
        for offset, word in (
            (0, self.rows),
            (8, self.rows + words * 4),
            (16, self.rows + capacity * 4),
            (24, count),
        ):
            self.memory.write(self.header + offset, 8, word)
        self.memory.write(self.source, 4, 0)
        self.memory.map_bytes(0x1431992A0, LENGTH_IMPORT.to_bytes(8, "little"))
        self.memory.map_bytes(0x14319A060, WATSON.to_bytes(8, "little"))
        self.events, self.effects, self.locals, self.closed = [], {}, {}, []
        self.on_read = self.on_write = None
        self.context = ReplayTaskRebuildStorage(self.header, self.read, self.write)
        self.calls, self.imports = (
            ReplayTaskRebuildCalls(self.dispatch),
            ReplayTaskRebuildCalls(self.terminal),
        )
        self.primitive = self.memory.runtime_calls()
        self.bound = bits.bind_replay_player_bit_vector(
            self.context, self.calls, bind_local=self.bind_local, imports=self.imports
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

    @contextmanager
    def bind_local(self, view):
        with self.memory.bind_local(view) as address:
            self.locals[address] = view
            self.events.append(("local", address, len(view)))
            try:
                yield address
            finally:
                self.closed.append((address, bytes(view)))
                del self.locals[address]

    def terminal(self, target, args, data):
        self.events.append(("i", target, args))
        if target in self.effects:
            return self.effects[target](args)
        assert self.primitive.call is not None
        return self.primitive.call(target, args, data)

    def dispatch(self, target, args, data):
        self.events.append(("c", target, args))
        if target in self.effects:
            return self.effects[target](args)
        if target in (ASSIGN, INSERT, RESIZE, APPEND, COMMIT, BIT_LENGTH, WORD_LENGTH):
            assert self.bound.call is not None
            return self.bound.call(target, args, data)
        assert self.primitive.call is not None
        return self.primitive.call(target, args, data)

    def run(self, target, *args):
        assert self.bound.call is not None
        return self.bound.call(target, args, None)

    def values(self):
        return tuple(self.memory.read(self.header + o, 8) for o in (0, 8, 16, 24))

    def words(self):
        begin, end, _, _ = self.values()
        return [self.memory.read(at, 4) for at in range(begin, end, 4)]

    def iterator(self, position):
        address = self.memory.allocate(16)
        self.memory.write(address, 8, self.memory.read(self.header, 8) + position // 32 * 4)
        self.memory.write(address + 8, 8, position % 32)
        return address


@pytest.mark.parametrize("count", [0, 1, 4, 7, 31, 32, 33, 63, 64, 65, 100])
@pytest.mark.parametrize("byte", [0, 1, 0x80, 0xFF])
def test_assignment_normal_counts_boolean_normalization_and_word_padding(count, byte):
    f = Fixture()
    f.memory.write(f.source, 1, byte)
    assert f.run(ASSIGN, f.header, count, f.source) is None
    assert f.values()[3] == count
    assert f.words() == [
        ((1 << min(32, count - i * 32)) - 1) if byte else 0 for i in range((count + 31) // 32)
    ]
    assert not f.locals and len(f.closed[0][1]) == (4 if count else 16)
    reads = [e for e in f.events if e[0] == "r" and e[1] == f.source]
    assert len(reads) == bool(count)


def test_assignment_zero_count_preserves_capacity_and_does_not_read_boolean():
    f = Fixture(40, 4, (1 << 40) - 1)
    f.run(ASSIGN, f.header, 0, U64)
    assert f.values() == (f.rows, f.rows, f.rows + 16, 0)
    assert f.memory.read(f.rows, 4) == U32
    assert not any(e[0] == "c" for e in f.events)


def test_assignment_resets_end_before_bitcount_and_exposes_live_initialized_iterator():
    f = Fixture(40, 4)

    def insert(args):
        assert args[0] == f.header and args[2] == 7
        assert f.values() == (f.rows, f.rows, f.rows + 16, 0)
        assert f.memory.read_bytes(args[1], 16) == f.rows.to_bytes(8, "little") + bytes(8)
        assert len(f.locals[args[1]]) == 16
        return 0

    f.effects[INSERT] = insert
    bits.assign_replay_player_bits(
        f.context, f.header, 7, f.source, calls=f.calls, bind_local=f.bind_local
    )
    writes = [e[1:4] for e in f.events if e[0] == "w"]
    assert writes[0] == (f.header + 8, 8, f.rows)
    assert writes[2] == (f.header + 24, 8, 0)


def test_assignment_actual_insert_result_and_current_begin_control_fill():
    f = Fixture(64, 2)
    alternate = f.memory.allocate(12)
    f.memory.fill(alternate, 0, 12)

    def insert(args):
        f.memory.write(f.header, 8, alternate + 4)
        return U64  # Actual returned signed position -1, not a substitute zero.

    f.effects[INSERT] = insert
    f.memory.write(f.source, 1, 1)
    bits.assign_replay_player_bits(
        f.context, f.header, 2, f.source, calls=f.calls, bind_local=f.bind_local
    )
    assert f.memory.read(alternate, 4) == 1 << 31
    assert f.memory.read(alternate + 4, 4) == 1
    assert f.memory.read(f.rows, 4) == 0


def test_assignment_holds_boolean_across_zero_byte_memset_and_keeps_iterator_live():
    f = Fixture(64, 2)
    f.memory.write(f.source, 1, 0x80)
    f.effects[INSERT] = lambda args: 3

    def fill(args):
        assert args == (f.rows + 4, 255, 0)
        assert [len(v) for v in f.locals.values()] == [16]
        f.memory.write(f.source, 1, 0)
        f.memory.write(f.rows + 4, 4, 0x80000000)
        return -7

    f.effects[SET] = fill
    bits.assign_replay_player_bits(
        f.context, f.header, 33, f.source, calls=f.calls, bind_local=f.bind_local
    )
    assert f.memory.read(f.rows, 4) == 0xFFFFFFF8
    assert f.memory.read(f.rows + 4, 4) == 0x8000000F


@pytest.mark.parametrize("position,count,expected", [(3, 5, 0xA5A5A5FD), (0, 32, U32)])
def test_assignment_partial_words_preserve_outside_bits(position, count, expected):
    f = Fixture(64, 2, 0xA5A5A5A5)
    f.effects[INSERT] = lambda args: position
    f.memory.write(f.source, 1, 1)
    bits.assign_replay_player_bits(
        f.context, f.header, count, f.source, calls=f.calls, bind_local=f.bind_local
    )
    assert f.memory.read(f.rows, 4) == expected


@pytest.mark.parametrize(
    "old_count,position,count",
    [(8, 0, 3), (8, 4, 3), (8, 8, 3), (40, 3, 7), (40, 31, 5), (65, 32, 33)],
)
def test_insert_backward_preserves_prefix_and_moves_suffix(old_count, position, count):
    original = int("a59c2e77b801fe42d5", 16) & ((1 << old_count) - 1)
    f = Fixture(old_count, 8, original)
    iterator = f.iterator(position)
    assert f.run(INSERT, f.header, iterator, count) == position
    assert f.values()[3] == old_count + count
    actual = sum(word << (32 * i) for i, word in enumerate(f.words()))
    assert actual & ((1 << position) - 1) == original & ((1 << position) - 1)
    assert actual >> (position + count) == original >> position
    assert f.closed[-1][1] == bytes(4)


def test_insert_count_zero_reads_only_iterator_then_current_begin_then_bitoffset():
    f = Fixture(8, 1)
    iterator = f.iterator(5)
    assert f.run(INSERT, f.header, iterator, 0) == 5
    assert f.events == [
        ("r", iterator, 8, f.rows),
        ("r", f.header, 8, f.rows),
        ("r", iterator + 8, 8, 5),
    ]
    assert not f.closed


def test_insert_uses_live_zero_local_and_current_bitcount_after_resize():
    f = Fixture(8, 2, 0xFF)
    iterator = f.iterator(4)

    def resize(args):
        assert args[:2] == (f.header, 1)
        assert f.memory.read(args[2], 4) == 0 and len(f.locals[args[2]]) == 4
        f.memory.write(f.header + 24, 8, 0)

    f.effects[RESIZE] = resize
    assert (
        bits.insert_replay_player_bits(
            f.context, f.header, iterator, 3, calls=f.calls, bind_local=f.bind_local
        )
        == 4
    )
    assert f.values()[3] == 3
    assert f.memory.read(f.rows, 4) == 0xFF


def test_insert_destination_read_before_source_test_even_when_same_word():
    f = Fixture(4, 1)
    iterator = f.iterator(0)
    seen = False

    def mutate(address, width, value):
        nonlocal seen
        if address == f.rows and width == 4 and not seen:
            assert [len(v) for v in f.locals.values()] == [4]
            seen = True
            f.memory.write(f.rows, 4, 8)

    f.on_read = mutate
    f.run(INSERT, f.header, iterator, 1)
    assert f.memory.read(f.rows, 4) == 16
    row_reads = [e for e in f.events if e[0] == "r" and e[1] == f.rows and e[2] == 4]
    assert row_reads[:2] == [("r", f.rows, 4, 0), ("r", f.rows, 4, 8)]


def test_insert_position_is_held_across_resize_mutation():
    f = Fixture(8, 2, 0xA5)
    iterator = f.iterator(3)

    def resize(args):
        f.memory.write(iterator + 8, 8, 7)

    f.effects[RESIZE] = resize
    assert (
        bits.insert_replay_player_bits(
            f.context, f.header, iterator, 2, calls=f.calls, bind_local=f.bind_local
        )
        == 3
    )
    assert f.values()[3] == 10
    assert f.memory.read(f.rows, 4) >> 5 == 0xA5 >> 3


def test_insert_length_failure_before_zero_local_and_resize():
    f = Fixture()
    iterator = f.iterator(0)
    f.effects[LENGTH_IMPORT] = lambda args: None
    with pytest.raises(UnresolvedReplayTaskRebuild, match="length terminal returned"):
        f.run(INSERT, f.header, iterator, 1 << 63)
    assert ("i", LENGTH_IMPORT, (0x14367D8E8,)) in f.events
    assert not f.locals and not f.closed
    assert not any(e[0] == "c" and e[1] == ALLOC for e in f.events)


@pytest.mark.parametrize("word", [0, 7])
def test_append_zero_count_always_reads_source_and_zero_branch_calls_memset(word):
    f = Fixture(0, 1)
    f.memory.write(f.source, 4, word)
    assert f.run(APPEND, f.rows, 0, f.source, U64) == f.rows
    assert f.events[0] == ("r", f.source, 4, word)
    calls = [e for e in f.events if e[0] == "c"]
    assert calls == ([("c", SET, (f.rows, 0, 0))] if not word else [])


def test_append_nonzero_source_rereads_each_element():
    f = Fixture(0, 4)
    f.memory.write(f.source, 4, 3)

    def mutate(address, width, value):
        if f.rows <= address < f.rows + 16:
            f.memory.write(f.source, 4, value + 1)

    f.on_write = mutate
    assert f.run(APPEND, f.rows, 3, f.source, 0) == f.rows + 12
    assert [f.memory.read(f.rows + i * 4, 4) for i in range(3)] == [3, 4, 5]


def test_append_source_alias_can_be_overwritten_before_next_element():
    f = Fixture(0, 3)
    f.memory.write(f.rows, 4, 5)
    f.run(APPEND, f.rows + 4, 2, f.rows, 0)
    assert [f.memory.read(f.rows + i * 4, 4) for i in range(3)] == [5, 5, 5]


@pytest.mark.parametrize("requested", [0, 1, 2, 3])
def test_resize_shrink_equal_and_capacity_growth(requested):
    f = Fixture(64, 3, 0x1122334455667788)
    f.memory.write(f.source, 4, 0x99)
    f.run(RESIZE, f.header, requested, f.source)
    assert f.values()[:3] == (f.rows, f.rows + requested * 4, f.rows + 12)
    assert f.memory.read(f.rows, 4) == 0x55667788
    if requested == 3:
        assert f.words() == [0x55667788, 0x11223344, 0x99]
    if requested == 2:
        assert f.events == [("r", f.header + 8, 8, f.rows + 8), ("r", f.header, 8, f.rows)]


def test_resize_uses_actual_append_return():
    f = Fixture(32, 3)
    f.effects[APPEND] = lambda args: 0x1234
    bits.resize_replay_player_bit_words(f.context, f.header, 2, f.source, calls=f.calls)
    assert ("c", APPEND, (f.rows + 4, 1, f.source, f.header)) in f.events
    assert f.memory.read(f.header + 8, 8) == 0x1234


@pytest.mark.parametrize("source", [0, 0xD00D])
def test_resize_reallocation_real_tail_copy_free_commit(source):
    f = Fixture(64, 2, 0x1122334455667788)
    f.memory.write(f.source, 4, source)
    old = f.rows
    f.run(RESIZE, f.header, 4, f.source)
    assert f.words() == [0x55667788, 0x11223344, source, source]
    assert f.values()[2] - f.values()[0] == 16
    calls = [e[1:] for e in f.events if e[0] == "c"]
    assert calls[0] == (ALLOC, (16,))
    assert calls[-1] == (FREE, (old, 8))
    assert (MOVE, (f.values()[0], old, 8)) in calls
    with pytest.raises(ReplayMemoryError):
        f.memory.read(old, 4)


def test_resize_nonzero_tail_rereads_source_after_allocation_and_each_store():
    f = Fixture(32, 1, 0xAB)
    f.memory.write(f.source, 4, 8)

    def allocate(args):
        f.memory.write(f.source, 4, 11)
        return f.memory.allocate_aligned(args[0])

    f.effects[ALLOC] = allocate

    def mutate(address, width, value):
        if width == 4 and value == 11:
            f.memory.write(f.source, 4, 12)

    f.on_write = mutate
    f.run(RESIZE, f.header, 3, f.source)
    assert f.words() == [0xAB, 11, 12]


def test_resize_reads_current_old_range_after_tail_callback_and_calls_real_commit_last():
    f = Fixture(32, 1, 0xAB)
    alternate = f.memory.allocate(8)
    f.memory.write(alternate, 4, 0xBB)
    f.memory.write(alternate + 4, 4, 0xCC)

    def fill(args):
        assert args[1:] == (0, 8)
        f.memory.fill(*args)
        f.memory.write(f.header, 8, alternate)
        f.memory.write(f.header + 8, 8, alternate + 8)
        f.memory.write(f.header + 16, 8, alternate + 8)

    f.effects[SET] = fill
    f.run(RESIZE, f.header, 3, f.source)
    assert f.words() == [0xBB, 0xCC, 0]
    assert f.memory.read(f.rows, 4) == 0xAB
    assert ("c", FREE, (alternate, 8)) in f.events


def test_commit_no_oldbegin_skips_capacity_and_end_reads_then_commits_in_order():
    f = Fixture()
    f.events.clear()
    f.run(COMMIT, f.header, 0x1000, 2, 3)
    assert f.events == [
        ("r", f.header, 8, 0),
        ("w", f.header, 8, 0x1000),
        ("w", f.header + 8, 8, 0x1008),
        ("w", f.header + 16, 8, 0x100C),
    ]


def test_commit_free_callback_precedes_held_header_commit():
    f = Fixture(32, 1)

    def free(args):
        assert args == (f.rows, 4) and f.values()[0] == f.rows
        for offset in (0, 8, 16):
            f.memory.write(f.header + offset, 8, 0xBAD)
        f.memory.free(f.rows)

    f.effects[FREE] = free
    f.run(COMMIT, f.header, 0x1000, 2, 3)
    assert f.values()[:3] == (0x1000, 0x1008, 0x100C)


def test_commit_large_aligned_backpointer_free():
    f = Fixture(32, 1024)
    base = f.memory.read(f.rows - 8, 8)
    f.run(COMMIT, f.header, 0x1000, 2, 3)
    assert ("c", FREE, (base, 0x1027)) in f.events


def test_commit_invalid_large_backpointer_current_watson_and_returned_cc():
    f = Fixture(32, 1024)
    f.memory.write(f.rows - 8, 8, f.rows - 48)
    f.effects[WATSON] = lambda args: None
    with pytest.raises(UnresolvedReplayTaskRebuild, match="Watson returned"):
        f.run(COMMIT, f.header, 0x1000, 2, 3)
    assert ("i", WATSON, (0, 0, 0, 0, 0)) in f.events
    assert f.values()[:3] == (f.rows, f.rows + 4, f.rows + 4096)
    assert not any(e[0] == "w" for e in f.events)


@pytest.mark.parametrize("target,label", [(BIT_LENGTH, 0x14367D8E8), (WORD_LENGTH, 0x1436794B0)])
def test_length_leaves_actual_current_iat_one_source_argument_and_returned_cc(target, label):
    f = Fixture()
    f.effects[LENGTH_IMPORT] = lambda args: None
    with pytest.raises(UnresolvedReplayTaskRebuild, match="length terminal returned"):
        f.run(target)
    assert f.events == [("r", 0x1431992A0, 8, LENGTH_IMPORT), ("i", LENGTH_IMPORT, (label,))]


def test_resize_too_large_real_word_length_before_allocation_or_source():
    f = Fixture()
    f.effects[LENGTH_IMPORT] = lambda args: None
    with pytest.raises(UnresolvedReplayTaskRebuild, match="length terminal returned"):
        f.run(RESIZE, f.header, MAX + 1, U64)
    assert ("i", LENGTH_IMPORT, (0x1436794B0,)) in f.events
    assert not any(e[0] == "c" and e[1] == ALLOC for e in f.events)
    assert f.values() == (0, 0, 0, 0)


def test_assignment_negative_count_preserves_entry_reset_before_real_length_failure():
    f = Fixture(8, 1, 0xFF)
    f.effects[LENGTH_IMPORT] = lambda args: None
    with pytest.raises(UnresolvedReplayTaskRebuild, match="length terminal returned"):
        f.run(ASSIGN, f.header, U64, f.source)
    assert f.values() == (f.rows, f.rows, f.rows + 4, 0)
    assert not any(e[0] == "r" and e[1] == f.source for e in f.events)


@pytest.mark.parametrize("delta", [0x7FFFFFFFFFFFFFFC, 0x8000000000000000, U64 - 3])
def test_resize_extreme_capacity_takes_real_allocation_or_length_path(delta):
    f = Fixture()
    f.memory.write(f.header + 16, 8, delta)

    def stop(args):
        raise RuntimeError(f"allocated:{args[0]:x}")

    f.effects[ALLOC] = stop
    cap = ((delta if delta < 1 << 63 else delta - (1 << 64)) >> 2) & U64
    expected = MAX if cap > ((MAX - (cap >> 1)) & U64) else max(cap + (cap >> 1), 1)
    # With a huge capacity, resize takes its within-capacity branch. Force a
    # genuine requested greater than that cap only where u64 permits it.
    if cap < MAX:
        request = cap + 1
        with pytest.raises(RuntimeError, match=f"allocated:{expected * 4:x}"):
            f.run(RESIZE, f.header, request, f.source)
    elif cap == U64:

        def stop_fill(args):
            assert args == (0, 0, U64 - 3)
            raise RuntimeError("actualhugefill")

        f.effects[SET] = stop_fill
        with pytest.raises(RuntimeError, match="actualhugefill"):
            f.run(RESIZE, f.header, U64, f.source)
    else:
        f.effects[LENGTH_IMPORT] = lambda args: None
        with pytest.raises(UnresolvedReplayTaskRebuild, match="length terminal returned"):
            f.run(RESIZE, f.header, cap + 1, f.source)
        assert ("i", LENGTH_IMPORT, (0x1436794B0,)) in f.events
        assert not any(e[0] == "c" and e[1] == ALLOC for e in f.events)


@pytest.mark.parametrize("target", [ALLOC, SET, MOVE, FREE])
def test_missing_real_children_stop_with_prior_effects_preserved(target):
    f = Fixture(32, 1, 0xAB)
    old = f.values()

    def fail(args):
        raise UnresolvedReplayTaskRebuild(f"actual{target:x} unavailable")

    f.effects[target] = fail
    with pytest.raises(UnresolvedReplayTaskRebuild, match=f"actual{target:x}"):
        f.run(RESIZE, f.header, 2, f.source)
    assert f.values() == old
    assert f.memory.read(f.rows, 4) == 0xAB
    if target in (MOVE, FREE):
        assert any(e[0] == "c" and e[1] == SET for e in f.events)


def test_missing_assignment_memset_preserves_first_word_effect_and_live_local_cleanup():
    f = Fixture(64, 2)
    f.effects[INSERT] = lambda args: 0
    f.memory.write(f.source, 1, 1)

    def fail(args):
        raise UnresolvedReplayTaskRebuild("actualfill unavailable")

    f.effects[SET] = fail
    with pytest.raises(UnresolvedReplayTaskRebuild, match="actualfill"):
        bits.assign_replay_player_bits(
            f.context, f.header, 33, f.source, calls=f.calls, bind_local=f.bind_local
        )
    assert f.memory.read(f.rows, 4) == U32
    assert not f.locals and len(f.closed[-1][1]) == 16


def test_missing_length_import_never_defaults_to_success():
    f = Fixture()
    with pytest.raises(UnresolvedReplayTaskRebuild, match="f0a0"):
        f.run(BIT_LENGTH)


def test_external_fatal_is_not_bound_as_success():
    f = Fixture()
    with pytest.raises(UnresolvedReplayTaskRebuild):
        # Explicit unavailable terminal delegate; binding must forward it.
        bound = bits.bind_replay_player_bit_vector(
            f.context, ReplayTaskRebuildCalls(None), bind_local=f.bind_local
        )
        assert bound.call is not None
        bound.call(FATAL, (), None)


@pytest.mark.parametrize(
    "target,arity",
    [
        (ASSIGN, 3),
        (INSERT, 3),
        (RESIZE, 3),
        (APPEND, 4),
        (COMMIT, 4),
        (BIT_LENGTH, 0),
        (WORD_LENGTH, 0),
    ],
)
def test_binding_rejects_wrong_arity_and_data(target, arity):
    f = Fixture()
    assert f.bound.call is not None
    with pytest.raises(ValueError, match="malformed"):
        f.bound.call(target, (0,) * (arity + 1), None)
    with pytest.raises(ValueError, match="malformed"):
        f.bound.call(target, (0,) * arity, memoryview(bytearray(1)))


@pytest.mark.parametrize("bad", [-1, 1 << 64, True])
def test_binding_rejects_non_raw_u64(bad):
    f = Fixture()
    with pytest.raises(ValueError, match="raw unsigned64"):
        f.run(ASSIGN, f.header, bad, f.source)


def test_insert_reloads_begin_after_actual_resize_callback():
    f = Fixture(8, 2, 0xA5)
    iterator = f.iterator(3)
    alternate = f.memory.allocate(8)
    f.memory.fill(alternate, 0, 8)
    f.memory.write(alternate, 4, 0x5A)

    def resize(args):
        f.memory.write(f.header, 8, alternate)
        f.memory.write(f.header + 8, 8, alternate + 4)
        f.memory.write(f.header + 16, 8, alternate + 8)

    f.effects[RESIZE] = resize
    assert (
        bits.insert_replay_player_bits(
            f.context, f.header, iterator, 2, calls=f.calls, bind_local=f.bind_local
        )
        == 3
    )
    assert f.memory.read(alternate, 4) >> 5 == 0x5A >> 3
    assert f.memory.read(f.rows, 4) == 0xA5


def test_insert_signed_negative_position_uses_backed_prebegin_bit():
    f = Fixture(4, 2)
    f.memory.write(f.rows, 4, 0x80000000)
    f.memory.write(f.rows + 4, 4, 0xA)
    f.memory.write(f.header, 8, f.rows + 4)
    f.memory.write(f.header + 8, 8, f.rows + 8)
    iterator = f.memory.allocate(16)
    f.memory.write(iterator, 8, f.rows)
    f.memory.write(iterator + 8, 8, 31)
    assert f.run(INSERT, f.header, iterator, 1) == U64
    assert f.memory.read(f.rows + 4, 4) == 0x15
    assert f.memory.read(f.rows, 4) == 0x80000000


def test_missing_insert_resize_preserves_live_zero_local_then_releases_it():
    f = Fixture(8, 1)
    iterator = f.iterator(0)

    def fail(args):
        assert [len(v) for v in f.locals.values()] == [4]
        raise UnresolvedReplayTaskRebuild("actualresize unavailable")

    f.effects[RESIZE] = fail
    with pytest.raises(UnresolvedReplayTaskRebuild, match="actualresize"):
        bits.insert_replay_player_bits(
            f.context, f.header, iterator, 2, calls=f.calls, bind_local=f.bind_local
        )
    assert f.values()[3] == 8
    assert not f.locals and f.closed[-1][1] == bytes(4)


def test_external_fatal_retains_real_memory_terminal():
    f = Fixture()
    with pytest.raises(ReplayMemoryRuntimeError) as caught:
        f.run(FATAL)
    assert caught.value.target == FATAL


def test_malformed_backward_iterator_refuses_after_actual_bitcount_store():
    f = Fixture(8, 1)
    iterator = f.iterator(9)
    with pytest.raises(ValueError, match="backward range"):
        f.run(INSERT, f.header, iterator, 1)
    assert f.values()[3] == 9
    assert f.memory.read(f.rows, 4) == 0
    assert not f.locals and f.closed[-1][1] == bytes(4)


def test_nonzero_append_wrapping_span_refuses_after_source_branch_read():
    f = Fixture()
    f.memory.write(f.source, 4, 7)
    with pytest.raises(ValueError, match="nonwrapping"):
        f.run(APPEND, U64 - 1, 1, f.source, 0)
    assert f.events == [("r", f.source, 4, 7)]
