"""Owned source-led history/vector controls, no large-reader or native oracle."""

from __future__ import annotations

from contextlib import contextmanager

import pytest

from vantage import replay_player_history as history
from vantage.replay_memory import ReplayMemory, ReplayMemoryError
from vantage.replay_saved_apply import bind_replay_saved_apply
from vantage.replay_saved_pair import bind_replay_saved_pair
from vantage.replay_saved_result import bind_replay_saved_result
from vantage.replay_task_list_storage import bind_replay_task_list_storage
from vantage.replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
)
from vantage.replay_unit_ai_map import ReplayUnitAIMapAtomics

CTOR, ASSIGN, FILL, RELEASE, RESIZE = (
    0x14162D370,
    0x1416347F0,
    0x14162CCC0,
    0x1402BBC40,
    0x14162CB30,
)
ALLOC, MEMSET, MOVE, FREE, READER = (
    0x1402A94D0,
    0x142D6E3B7,
    0x142D6E3DB,
    0x142D6BAB4,
    0x141634B00,
)
PAIR, COPY, CLEANUP = 0x14090D270, 0x1402B9080, 0x1402BD890
SLOTS = (
    (0xA0, 0x3C),
    (0x550, 0x40),
    (0x158, 0x2C),
    (0x560, 0x30),
    (0x4D0, 0x44),
    (0x4C0, 0x48),
    (0x4D8, 0x34),
    (0x4C8, 0x38),
)
U64 = (1 << 64) - 1


def encoded(word, high=0xA5A5A5A5):
    """Authored inverse fixture of the exact source's four64-bit operations."""
    value = ((high << 32) | word) ^ 0xA9834B738A7DD167
    value = (value + 0x042AC42976FCCEF5) & U64
    return value ^ 0xC22D6B496D833977 ^ 0x6AE24D3352F04511


class Fixture:
    def __init__(self, word=0, *, defined=True):
        self.memory = ReplayMemory(max_bytes=8 << 20)
        self.object = self.memory.allocate(0xF8)
        if defined:
            self.memory.fill(self.object, 0xA5, 0xF8)
        self.player, self.table = self.memory.allocate(0xA0), self.memory.allocate(601 * 8)
        self.memory.write(self.player + 0x98, 8, self.table)
        for offset, _ in SLOTS:
            self.memory.write(self.table + offset, 8, encoded(word))
        self.output = self.memory.allocate(48)
        self.memory.fill(self.output, 0xA5, 48)
        self.memory.write_bytes(self.output, bytes(41))
        for slot, target in (
            (0x143199DD0, FREE),
            (0x143199938, MEMSET),
            (0x1431999A0, MOVE),
            (0x14319A060, 0xF0A1),
        ):
            self.memory.map_bytes(slot, target.to_bytes(8, "little"))
        self.events, self.effects, self.blocked, self.routes = [], {}, set(), {}
        self.on_read = self.on_write = self.before_call = self.after_call = None
        self.frame, self.frame_after, self.active = 0, b"", False
        self.context = ReplayTaskRebuildStorage(self.object, self.read, self.write)
        self.calls = ReplayTaskRebuildCalls(self.dispatch)
        self.primitive = self.memory.runtime_calls()
        self.imports = ReplayTaskRebuildCalls(self.import_call)
        self.atomics = ReplayUnitAIMapAtomics(
            self.memory.compare_exchange_u32, self.memory.fetch_add_u32
        )
        self.scratch = history.ReplayPlayerHistoryScratch(b"\xa5" * 0x90)
        self.bound = history.bind_replay_player_history(
            self.context,
            self.calls,
            atomics=self.atomics,
            bind_local=self.bind_local,
            scratch=self.scratch,
            imports=self.imports,
        )
        self.register((CTOR, ASSIGN, FILL, RELEASE, RESIZE), self.bound)
        # Real three CRT thunk bodies perform current IAT reads before terminal primitives.
        self.register(
            (FREE, MOVE, MEMSET), bind_replay_task_list_storage(self.context, self.imports)
        )
        self.register(
            (PAIR,), bind_replay_saved_pair(self.context, self.calls, atomics=self.atomics)
        )
        self.register(
            (COPY, 0x1409076B0),
            bind_replay_saved_apply(
                self.context, self.calls, atomics=self.atomics, imports=self.imports
            ),
        )
        self.register(
            (CLEANUP, 0x1402BD7F0, 0x140900620),
            bind_replay_saved_result(
                self.context, self.calls, atomics=self.atomics, imports=self.imports
            ),
        )

    def register(self, targets, binding):
        for target in targets:
            self.routes[target] = binding

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

    def import_call(self, target, args, data):
        self.events.append(("i", target, args))
        if target in self.effects:
            return self.effects[target](args)
        assert self.primitive.call is not None
        return self.primitive.call(target, args, data)

    def dispatch(self, target, args, data):
        self.events.append(("c", target, args))
        if self.before_call:
            self.before_call(target, args)
        if target in self.blocked:
            raise UnresolvedReplayTaskRebuild(f"explicit refusal{target:x}")
        if target in self.effects:
            result = self.effects[target](args)
        else:
            receiver = self.routes.get(target, self.primitive).call
            assert receiver is not None
            result = receiver(target, args, data)
        if self.after_call:
            self.after_call(target, args, result)
        return result

    @contextmanager
    def bind_local(self, view):
        with self.memory.bind_local(view) as address:
            self.frame, self.active = address, True
            try:
                yield address
            finally:
                self.frame_after, self.active = bytes(view), False

    def run(self, *, stream=0, output=None, bound=False):
        output = self.output if output is None else output
        args = (self.object, self.player, output, stream)
        if bound:
            assert self.bound.call is not None
            return self.bound.call(CTOR, args, None)
        return history.construct_replay_player_history(
            self.context,
            *args,
            calls=self.calls,
            atomics=self.atomics,
            bind_local=self.bind_local,
            scratch=self.scratch,
        )

    def vector(self, words, capacity=None):
        capacity = len(words) if capacity is None else capacity
        header = self.memory.allocate(24)
        if capacity:
            begin = self.memory.allocate_aligned(capacity * 4)
            for index, word in enumerate(words):
                self.memory.write(begin + index * 4, 4, word)
        else:
            begin = 0
        for offset, value in ((0, begin), (8, begin + len(words) * 4), (16, begin + capacity * 4)):
            self.memory.write(header + offset, 8, value)
        return header, begin

    def word(self, value):
        result = self.memory.allocate(4)
        self.memory.write(result, 4, value)
        return result

    def targets(self, target, channel="c"):
        return [row[2] for row in self.events if row[:2] == (channel, target)]

    def contents(self, header):
        begin, end = self.memory.read(header, 8), self.memory.read(header + 8, 8)
        return [self.memory.read(at, 4) for at in range(begin, end, 4)]


@pytest.mark.parametrize(
    "word,expected",
    [
        (0, 0),
        (0x80000000, 0),
        (0x3FCCCCCD, 1),
        (0xBFCCCCCD, 0xFFFFFFFF),
        (0x4EFFFFFF, 2147483520),
        (0x4F000000, 0x80000000),
        (0xCF000000, 0x80000000),
        (0xCF000001, 0x80000000),
        (0x7F800000, 0x80000000),
        (0xFF800000, 0x80000000),
        (0x7FC12345, 0x80000000),
        (0x7F812345, 0x80000000),
        (1, 0),
        (0x80000001, 0),
    ],
)
@pytest.mark.parametrize("bound", [False, True])
def test_ctor_actual_vectors_full64_codec_and_masked_cvtt(word, expected, bound):
    f = Fixture(word)
    assert f.run(bound=bound) == f.object
    for _, destination in SLOTS:
        assert f.memory.read(f.object + destination, 4) == expected
    for offset in (0xB0, 0xC8):
        assert f.contents(f.object + offset) == [0] * 9
    assert int.from_bytes(f.frame_after[0x88:0x90], "little") == 0xA5A5A5A500000000 | word
    assert f.frame_after[0x20:0x50] == b"\xa5" * 48 and not f.active


def test_ctor_high_scalar_survives_both_low_clears_and_current_count_changes_second_call():
    f = Fixture()
    observed = []

    def before(target, args):
        if target == ASSIGN:
            observed.append((args[1], f.memory.read(args[2], 8)))

    def after(target, _args, _result):
        if target == ASSIGN and len(observed) == 1:
            f.memory.write(f.frame + 0x8C, 4, 0x12345678)
            f.memory.write(f.object + 0x24, 4, 5)

    f.before_call, f.after_call = before, after
    assert f.run() == f.object
    assert observed == [(9, 0xA5A5A5A500000000), (5, 0x1234567800000000)]
    assert len(f.contents(f.object + 0xC8)) == 5


def test_ctor_second_count_signextends_negative_before_real_error_refusal():
    f = Fixture()

    def mutate(target, _args, _result):
        if target == ASSIGN:
            f.memory.write(f.object + 0x24, 4, 0xFFFFFFFF)

    f.after_call = mutate
    with pytest.raises(UnresolvedReplayTaskRebuild, match="1402ba820"):
        f.run()
    assert f.targets(ASSIGN)[1][1] == U64
    assert f.targets(0x1402BA820) == [()]
    assert f.memory.read(f.object + 0x3C, 4) == 0  # Initial store, no resource phase yet.


def test_ctor_reloads_current_player_and_table_for_each_resource():
    f = Fixture(0x3F800000)
    other_player, other_table = f.memory.allocate(0xA0), f.memory.allocate(601 * 8)
    f.memory.write(other_player + 0x98, 8, other_table)
    for offset, _ in SLOTS:
        f.memory.write(other_table + offset, 8, encoded(0x40700000))  # 3.75 ->3.

    def mutate(address, width, _value):
        if address == f.object + 0x3C and width == 4:
            f.memory.write(f.object + 0x10, 8, other_player)

    f.on_write = mutate
    assert f.run() == f.object
    assert f.memory.read(f.object + 0x3C, 4) == 1
    assert [f.memory.read(f.object + offset, 4) for _, offset in SLOTS[1:]] == [3] * 7


def test_ctor_current_full_QWORD_staging_is_not_a_detached_decode():
    f = Fixture(0x3F800000)
    changes = 0

    def mutate(address, width, value):
        nonlocal changes
        if address == f.frame + 0x88 and width == 8 and value == encoded(0x3F800000):
            f.memory.write(address, 8, encoded(0x40B00000))  # Source readback must see5.5.
            changes += 1

    f.on_write = mutate
    assert f.run() == f.object and changes == 8
    assert [f.memory.read(f.object + offset, 4) for _, offset in SLOTS] == [5] * 8


def test_ctor_stream_zero_does_not_access_output_and_preserves_undefined_holes():
    f = Fixture(defined=False)
    assert f.run(output=0xBAD000) == f.object
    for offset, width in ((0x54, 8), (0x6C, 1), (0xA0, 8), (0xF4, 4)):
        with pytest.raises(ReplayMemoryError, match="undefined"):
            f.memory.read(f.object + offset, width)
    assert f.frame_after[0x20:0x50] == b"\xa5" * 48
    assert not any(row[0] in ("r", "w") and row[1] == 0xBAD000 for row in f.events)


def test_ctor_real_nonzero_stream_stops_at_actual_large_reader_with_prior_effects():
    f = Fixture(0x3F800000)
    with pytest.raises(UnresolvedReplayTaskRebuild, match="141634b00"):
        f.run(stream=0xF123)
    assert len(f.targets(ALLOC)) == 2 and f.memory.read(f.object + 0x3C, 4) == 1
    assert f.targets(READER) == [(f.object, f.frame + 0x20, 0xF123)]
    assert not f.targets(PAIR) and not f.targets(CLEANUP)
    assert f.frame_after[0x20:0x50] == b"\xa5" * 48 and not f.active


@pytest.mark.parametrize("returned", ["fixed", "external", "output"])
def test_opaque_reader_protocol_uses_returned_Result_and_cleans_fixed_Result(returned):
    f = Fixture()
    external = f.memory.allocate(48)
    f.memory.write_bytes(external, bytes(48))
    fixed_control = f.memory.allocate(16)
    f.memory.write(fixed_control + 8, 4, 2)

    def opaque_reader(args):
        fixed = args[1]
        f.memory.write_bytes(fixed, bytes(48))
        f.memory.write(fixed + 32, 8, fixed_control)
        result = {"fixed": fixed, "external": external, "output": f.output}[returned]
        f.memory.write(result + 24, 8, 17)
        return result

    f.effects[READER] = opaque_reader  # Authored protocol effect, NOT a26KB reader implementation.
    assert f.run(stream=0xF123) == f.object
    result = {"fixed": f.frame + 0x20, "external": external, "output": f.output}[returned]
    assert f.targets(PAIR) == [(f.output + 24, result + 24)]
    assert f.memory.read(f.output + 24, 8) == 17 and f.memory.read(f.output + 40, 1) == 0
    assert bool(f.targets(COPY)) == (returned != "output")
    assert f.targets(CLEANUP)[-1] == (f.frame + 0x20,)
    assert f.memory.read(fixed_control + 8, 4) == (2 if returned == "fixed" else 1)
    assert not f.active


def test_opaque_reader_output_processed_precedes_current_fixed_control_read():
    f = Fixture()
    first, current = f.memory.allocate(16), f.memory.allocate(16)
    for control in (first, current):
        f.memory.write(control + 8, 4, 2)
    external = f.memory.allocate(48)
    f.memory.write_bytes(external, bytes(48))

    def opaque_reader(args):
        f.memory.write_bytes(args[1], bytes(48))
        f.memory.write(args[1] + 32, 8, first)
        return external

    def mutate(address, width, value):
        if address == f.output + 40 and width == 1 and value == 0:
            assert f.active
            f.memory.write(f.frame + 0x40, 8, current)

    f.effects[READER], f.on_write = opaque_reader, mutate
    assert f.run(stream=0xF123) == f.object
    assert f.memory.read(first + 8, 4) == 2 and f.memory.read(current + 8, 4) == 1


@pytest.mark.parametrize("value", [0, 0x80000000, 0xFFFFFFFF])
@pytest.mark.parametrize("count", [0, 1, 3, 4, 5, 8, 9])
def test_fill_all_normal_scalar_bulk_zero_branches(value, count):
    f = Fixture()
    source, begin = f.word(value), f.memory.allocate(max(4, count * 4))
    history.fill_replay_history_words(f.context, begin, begin + count * 4, source, calls=f.calls)
    assert [f.memory.read(begin + i * 4, 4) for i in range(count)] == [value] * count
    assert len(f.targets(MEMSET)) == (value == 0)


def test_fill_holds_bulk_word_but_rereads_tail_after_callback_change():
    f = Fixture()
    source, begin = f.word(7), f.memory.allocate(20)

    def mutate(address, _width, _value):
        if address == begin:
            f.memory.write(source, 4, 9)

    f.on_write = mutate
    history.fill_replay_history_words(f.context, begin, begin + 20, source, calls=f.calls)
    assert [f.memory.read(begin + i * 4, 4) for i in range(5)] == [7, 7, 7, 7, 9]


def test_fill_inside_alias_suppresses_bulk_and_reads_current_source_each_word():
    f = Fixture()
    begin = f.memory.allocate(20)
    f.memory.write_bytes(begin, bytes(20))
    source = begin + 8
    f.memory.write(source, 4, 7)

    def mutate(address, _width, _value):
        if address == begin:
            f.memory.write(source, 4, 9)

    f.on_write = mutate
    history.fill_replay_history_words(f.context, begin, begin + 20, source, calls=f.calls)
    assert [f.memory.read(begin + i * 4, 4) for i in range(5)] == [7, 9, 9, 9, 9]


@pytest.mark.parametrize("begin,end", [(8, 4), (4, 9), (U64 - 3, 0)])
def test_fill_malformed_loop_profile_refuses_before_effects(begin, end):
    f = Fixture()
    with pytest.raises(ValueError, match="ordered wholeDWORD"):
        history.fill_replay_history_words(f.context, begin, end, 0xBAD000, calls=f.calls)
    assert not f.events


@pytest.mark.parametrize(
    "words,capacity,requested",
    [([], 0, 9), ([1, 2], 2, 3), ([1, 2], 8, 5), ([1, 2, 3], 4, 1), ([1, 2], 2, 2), ([], 0, 0)],
)
@pytest.mark.parametrize("value", [0, 0x87654321])
def test_assignment_capacity_growth_inplace_equal_shrink_and_zero(
    words, capacity, requested, value
):
    f = Fixture()
    header, _ = f.vector(words, capacity)
    history.assign_replay_history_words(f.context, header, requested, f.word(value), calls=f.calls)
    assert f.contents(header) == [value] * requested


def test_assignment_reloads_current_end_after_range_callback():
    f = Fixture()
    header, begin = f.vector([1, 2], 8)
    source = f.word(7)

    def mutate(target, _args, _result):
        if target == FILL:
            f.memory.write(header + 8, 8, begin + 12)

    f.after_call = mutate
    history.assign_replay_history_words(f.context, header, 4, source, calls=f.calls)
    assert f.memory.read(header + 8, 8) == begin + 20  # held remaining2, currentappendstart3.
    assert f.memory.read(begin + 12, 4) == f.memory.read(begin + 16, 4) == 7


def test_assignment_source_first_read_occurs_after_new_header_publication():
    f = Fixture()
    header, _ = f.vector([], 0)
    source = header + 8  # Actual local alias, currentend becomes allocation before read.
    history.assign_replay_history_words(f.context, header, 1, source, calls=f.calls)
    begin = f.memory.read(header, 8)
    assert f.contents(header) == [begin & 0xFFFFFFFF]


def test_assignment_release_before_reset_and_new_allocation():
    f = Fixture()
    header, old = f.vector([1], 1)
    old_capacity = f.memory.read(header + 16, 8)

    def before(target, _args):
        if target == RELEASE:
            assert f.memory.read(header, 8) == old
        if target == ALLOC:
            assert f.memory.read_bytes(header, 24) == bytes(24)

    f.before_call = before
    history.assign_replay_history_words(f.context, header, 4, f.word(3), calls=f.calls)
    assert f.targets(RELEASE) == [(header, old, (old_capacity - old) // 4)]
    assert f.contents(header) == [3] * 4


@pytest.mark.parametrize(
    "words,capacity,requested",
    [([], 0, 0), ([1, 2], 2, 1), ([1, 2], 2, 2), ([1, 2], 8, 5), ([1, 2], 2, 5), ([], 0, 3)],
)
def test_resize_ignored_R8_and_all_normal_size_capacity_branches(words, capacity, requested):
    f = Fixture()
    header, _ = f.vector(words, capacity)
    history.resize_replay_history_words(
        f.context, header, requested, 0xBAD000, calls=f.calls, imports=f.imports
    )
    assert f.contents(header) == words[:requested] + [0] * max(0, requested - len(words))
    assert not any(row[0] == "r" and row[1] == 0xBAD000 for row in f.events)


def test_resize_equal_skips_capacity_read_and_all_children():
    f = Fixture()
    header, begin = f.vector([1, 2], 2)
    f.events.clear()
    history.resize_replay_history_words(f.context, header, 2, 0xBAD000, calls=f.calls)
    assert f.events == [("r", header + 8, 8, begin + 8), ("r", header, 8, begin)]


def test_resize_tail_memset_before_current_copy_and_current_free_before_commit():
    f = Fixture()
    header, old = f.vector([1, 2], 2)
    second = f.memory.allocate_aligned(12)
    third = f.memory.allocate_aligned(4)
    for i, value in enumerate((5, 6, 7)):
        f.memory.write(second + 4 * i, 4, value)
    f.memory.write(third, 4, 99)

    def after(target, _args, _result):
        if target == MEMSET:
            for offset, value in ((0, second), (8, second + 12), (16, second + 12)):
                f.memory.write(header + offset, 8, value)
        elif target == MOVE:
            for offset, value in ((0, third), (8, third + 4), (16, third + 4)):
                f.memory.write(header + offset, 8, value)

    def before(target, _args):
        if target == FREE:
            assert f.memory.read(header, 8) == third

    f.before_call, f.after_call = before, after
    history.resize_replay_history_words(
        f.context, header, 4, 0xBAD000, calls=f.calls, imports=f.imports
    )
    assert f.contents(header) == [5, 6, 7, 0]
    assert f.targets(MOVE)[0][1:] == (second, 12)
    assert f.targets(FREE)[0] == (third, 4)
    assert f.memory.read(old, 4) == 1  # Current mutated allocation, not staleold, was freed.
    with pytest.raises(ReplayMemoryError):
        f.memory.read(third, 4)


@pytest.mark.parametrize("count", [0, 1, 1023, 1024, 2048])
def test_release_real_owned_small_large_and_zero_capacity(count):
    f = Fixture()
    begin = f.memory.allocate_aligned(count * 4) if count else 0
    history.release_replay_history_words(
        f.context, 0xBAD000, begin, count, calls=f.calls, imports=f.imports
    )
    if begin:
        with pytest.raises(ReplayMemoryError):
            f.memory.read(begin, 1)
    assert len(f.targets(FREE)) == 1


def test_release_capacity_product_wraps_before_large_header_gate():
    f = Fixture()
    history.release_replay_history_words(
        f.context, 0xBAD000, 0, 1 << 62, calls=f.calls, imports=f.imports
    )
    assert f.targets(FREE) == [(0, 0)]


def test_release_bad_large_header_current_IAT_terminal_alias_and_returned_trap():
    f = Fixture()
    allocation = f.memory.allocate(0x1100)
    begin = allocation + 64
    f.memory.write(begin - 8, 8, allocation)
    f.memory.write(0x14319A060, 8, FILL)  # Alias a knownbody, but imported call isterminal.
    f.effects[FILL] = lambda args: None  # Explicit returning invalid-parameter capability.
    with pytest.raises(UnresolvedReplayTaskRebuild, match="Watson returned before INT3"):
        history.release_replay_history_words(
            f.context, 0, begin, 1024, calls=f.calls, imports=f.imports
        )
    assert f.targets(FILL, "i") == [(0, 0, 0, 0, 0)] and not f.targets(FILL)
    assert not f.targets(FREE)


@pytest.mark.parametrize("function", ["assign", "resize"])
def test_excess_count_requires_actual_length_helper_before_allocation(function):
    f = Fixture()
    header, _ = f.vector([], 0)
    with pytest.raises(UnresolvedReplayTaskRebuild, match="1402ba820"):
        if function == "assign":
            history.assign_replay_history_words(
                f.context, header, 1 << 62, f.word(0), calls=f.calls
            )
        else:
            history.resize_replay_history_words(
                f.context, header, 1 << 62, 0, calls=f.calls, imports=f.imports
            )
    assert not f.targets(ALLOC) and f.targets(0x1402BA820) == [()]


@pytest.mark.parametrize("target", [ALLOC, MEMSET, MOVE, FREE])
def test_resize_missing_runtime_provider_retains_source_phase_effects(target):
    f = Fixture()
    header, old = f.vector([1, 2], 2)
    f.blocked.add(target)
    with pytest.raises(UnresolvedReplayTaskRebuild, match="explicit refusal"):
        history.resize_replay_history_words(
            f.context, header, 5, 0, calls=f.calls, imports=f.imports
        )
    assert f.memory.read(header, 8) == old and f.contents(header) == [1, 2]
    assert len(f.targets(ALLOC)) == 1


@pytest.mark.parametrize(
    "target,args,data",
    [
        (CTOR, (1, 2, 3), None),
        (ASSIGN, (1, 2), None),
        (FILL, (1, 2, 3), memoryview(b"")),
        (RELEASE, (1, 2, -1), None),
        (RESIZE, (1, 2, 3, 4), None),
    ],
)
def test_binder_arity_scalar_and_data_guards_are_pre_effect(target, args, data):
    f = Fixture()
    assert f.bound.call is not None
    with pytest.raises(ValueError):
        f.bound.call(target, args, data)
    assert not f.events


def test_scratch_requires_explicit_exact_bytes_before_any_local_binding():
    for seed in (b"", bytes(0x8F), bytearray(0x90)):
        with pytest.raises(ValueError, match="explicit90"):
            history.ReplayPlayerHistoryScratch(seed)


def test_ctor_holds_fixed_control_and_reloads_current_weak_virtual_after_destroy():
    f = Fixture()
    control, replacement, old_table, new_table, result = (
        f.memory.allocate(size) for size in (16, 16, 16, 16, 48)
    )
    destroy, old_weak, new_weak = 0xFA01, 0xFA02, 0xFA03
    for address, width, value in (
        (control, 8, old_table),
        (control + 8, 4, 1),
        (control + 12, 4, 1),
        (replacement + 8, 4, 2),
        (old_table, 8, destroy),
        (old_table + 8, 8, old_weak),
        (new_table + 8, 8, new_weak),
    ):
        f.memory.write(address, width, value)
    f.memory.write_bytes(result, bytes(48))

    def opaque_reader(args):
        f.memory.write_bytes(args[1], bytes(48))
        f.memory.write(args[1] + 32, 8, control)
        return result

    def destroy_effect(_args):
        assert f.active
        f.memory.write(f.frame + 0x40, 8, replacement)
        f.memory.write(control, 8, new_table)

    f.effects[READER] = opaque_reader
    f.effects[destroy] = destroy_effect
    f.effects[new_weak] = lambda _args: None  # Explicit logical disposal boundary.
    assert f.run(stream=0xF123) == f.object
    assert f.targets(destroy) == f.targets(new_weak) == [(control,)]
    assert not f.targets(old_weak)
    assert f.memory.read(control + 8, 4) == f.memory.read(control + 12, 4) == 0
    assert f.memory.read(replacement + 8, 4) == 2


def test_assignment_release_uses_held_capacity_even_if_current_header_changes_on_read():
    f = Fixture()
    header, begin = f.vector([1], 2)

    def mutate(address, _width, _value):
        if address == header + 16:
            f.memory.write(address, 8, begin)

    f.on_read = mutate
    history.assign_replay_history_words(f.context, header, 4, f.word(7), calls=f.calls)
    assert f.targets(RELEASE) == [(header, begin, 2)]
    assert f.contents(header) == [7] * 4


def test_resize_from_null_empty_still_calls_actual_zero_width_memmove():
    f = Fixture()
    header, _ = f.vector([], 0)
    history.resize_replay_history_words(
        f.context, header, 3, 0xBAD000, calls=f.calls, imports=f.imports
    )
    assert f.targets(MOVE) == [(f.memory.read(header, 8), 0, 0)]
    assert any(row[:2] == ("r", 0x1431999A0) for row in f.events)
    assert not f.targets(FREE)


def test_resize_current_bad_large_header_calls_current_Watson_and_never_commits():
    f = Fixture()
    header, _ = f.vector([1, 2], 2)
    raw = f.memory.allocate(0x1100)
    bad_begin = raw + 64
    f.memory.write(bad_begin - 8, 8, raw)
    f.effects[0xF0A1] = lambda _args: None  # Explicit returned nonreturning-provider control.

    def mutate(target, _args, _result):
        if target == MOVE:
            for offset, value in ((0, bad_begin), (8, bad_begin + 4), (16, bad_begin + 0x1000)):
                f.memory.write(header + offset, 8, value)

    f.after_call = mutate
    with pytest.raises(UnresolvedReplayTaskRebuild, match="Watson returned before INT3"):
        history.resize_replay_history_words(
            f.context, header, 5, 0, calls=f.calls, imports=f.imports
        )
    assert f.targets(0xF0A1, "i") == [(0, 0, 0, 0, 0)]
    assert f.memory.read(header, 8) == bad_begin and not f.targets(FREE)


@pytest.mark.parametrize("target", [ASSIGN, FILL, RELEASE, RESIZE])
def test_actual_bound_vector_entry_routes_complete_known_body(target):
    f = Fixture()
    header, begin = f.vector([3, 4], 4)
    source = f.word(7)
    args = {
        ASSIGN: (header, 3, source),
        FILL: (begin, begin + 8, source),
        RELEASE: (header, begin, 4),
        RESIZE: (header, 3, 0xBAD000),
    }[target]
    assert f.bound.call is not None
    assert f.bound.call(target, args, None) is None
    if target == RELEASE:
        with pytest.raises(ReplayMemoryError):
            f.memory.read(begin, 4)
    elif target == FILL:
        assert f.contents(header) == [7, 7]
    elif target == ASSIGN:
        assert f.contents(header) == [7, 7, 7]
    else:
        assert f.contents(header) == [3, 4, 0]
