"""Source-led growth controls; all successful children are owned."""

from __future__ import annotations

from contextlib import contextmanager
from itertools import pairwise

import pytest

from vantage.replay_localization_alias_growth import (
    ReplayLocalizationAliasGrowthProfile,
    ReplayLocalizationAliasGrowthScratch,
    bind_replay_localization_alias_growth,
)
from vantage.replay_memory import ReplayMemory, ReplayMemoryError, ReplayMemoryRuntimeError
from vantage.replay_memory_compare import (
    bind_replay_memcmp_thunk,
    replay_memory_comparison_calls,
)
from vantage.replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
)

COUNT, REHASH, VECTOR, FILL, RELEASE, CEIL = (
    0x140969420,
    0x140969930,
    0x1409691F0,
    0x1409624E0,
    0x140969EE0,
    0x142D6E453,
)
ALLOC, FREE, COMPARE = 0x1402A94D0, 0x142D6BAB4, 0x142D6E3BD
U64, ENTRIES = (1 << 64) - 1, (COUNT, REHASH, VECTOR, FILL, RELEASE, CEIL)


class Fixture:
    def __init__(self, *, stores=10000, nodes=100, key_bytes=10000, candidates=100):
        self.memory = ReplayMemory(max_bytes=2 << 20)
        self.events, self.locals, self.closed = [], [], []
        self.effects, self.unavailable = {}, set()
        self.on_read = self.on_write = None
        self.context = ReplayTaskRebuildStorage(1, self.read, self.write)
        self.calls = ReplayTaskRebuildCalls(self.dispatch)
        self.engine = replay_memory_comparison_calls(self.memory, comparison_target=0xBE01)
        self.imports = ReplayTaskRebuildCalls(self.terminal)
        self.comparison = bind_replay_memcmp_thunk(self.context, self.calls, imports=self.imports)
        self.bound = bind_replay_localization_alias_growth(
            self.context,
            self.calls,
            bind_local=self.bind_local,
            scratch=ReplayLocalizationAliasGrowthScratch(b"\xa5" * 8, b"\xb6" * 32, b"\xc7" * 8),
            profile=ReplayLocalizationAliasGrowthProfile(
                stores, nodes, key_bytes, candidates, 0x1F80
            ),
            imports=self.imports,
        )
        self.memory.map_bytes(0x143199EF0, CEIL.to_bytes(8, "little"))
        self.memory.map_bytes(0x143199940, (0xBE01).to_bytes(8, "little"))
        self.memory.map_bytes(0x1436A0308, (0x5F000000).to_bytes(4, "little"))

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
            self.locals.append((address, len(view)))
            try:
                yield address
            finally:
                self.closed.append((address, bytes(view)))
                assert self.locals.pop() == (address, len(view))

    def dispatch(self, target, args, data):
        self.events.append(("c", target, args))
        if target in self.unavailable:
            raise UnresolvedReplayTaskRebuild(f"authored missing {target:x}")
        if target in self.effects:
            return self.effects[target](args)
        if target in ENTRIES:
            return self.invoke(target, *args, data=data)
        if target == COMPARE:
            assert self.comparison.call
            return self.comparison.call(target, args, data)
        assert self.engine.call
        return self.engine.call(target, args, data)

    def terminal(self, target, args, data):
        self.events.append(("i", target, args))
        if target in self.effects:
            return self.effects[target](args)
        assert self.engine.call
        return self.engine.call(target, args, data)

    def invoke(self, target, *args, data=None):
        assert self.bound.call
        return self.bound.call(target, args, data)

    def actual_compare(self, args):
        assert self.comparison.call
        return self.comparison.call(COMPARE, args, None)

    def targets(self, target, *, kind="c"):
        return [row[2] for row in self.events if row[:2] == (kind, target)]

    def words(self, values):
        pointer = self.memory.allocate(8 * len(values))
        for index, value in enumerate(values):
            self.memory.write(pointer + index * 8, 8, value)
        return pointer

    def header(self, begin, end, capacity):
        return self.words((begin, end, capacity))

    def alias_table(self, keys):
        table, sentinel, buckets = (
            self.memory.allocate(64),
            self.memory.allocate(56),
            self.words((0, 0)),
        )
        self.memory.write(buckets, 8, sentinel)
        self.memory.write(buckets + 8, 8, sentinel)
        nodes = []
        for number, key in enumerate(keys):
            node = self.memory.allocate(56)
            self.memory.write_bytes(node + 0x10, bytes(16))
            if len(key) > 15:
                pointer = self.memory.allocate(len(key) + 1)
                self.memory.write_bytes(pointer, key + b"\0")
                self.memory.write(node + 0x10, 8, pointer)
                self.memory.write(node + 0x28, 8, 31)
            else:
                self.memory.write_bytes(node + 0x10, key + b"\0")
                self.memory.write(node + 0x28, 8, 15)
            self.memory.write(node + 0x20, 8, len(key))
            self.memory.write(node + 0x30, 4, 100 + number)
            nodes.append(node)
        chain = [sentinel, *nodes, sentinel]
        for index, node in enumerate(nodes, 1):
            self.memory.write(node, 8, chain[index + 1])
            self.memory.write(node + 8, 8, chain[index - 1])
        self.memory.write(sentinel, 8, nodes[0] if nodes else sentinel)
        self.memory.write(sentinel + 8, 8, nodes[-1] if nodes else sentinel)
        for offset, value in (
            (8, sentinel),
            (0x10, len(nodes)),
            (0x18, buckets),
            (0x20, buckets + 16),
            (0x28, buckets + 16),
            (0x30, 0),
            (0x38, 1),
        ):
            self.memory.write(table + offset, 8, value)
        self.memory.write(table, 4, 0x3F800000)
        return table, sentinel, buckets, nodes


@pytest.mark.parametrize(
    "old,requested,expected",
    [(1, 9, 9), (2, 9, 16), (512, 9, 512), (500, 1000, 4000), (512, 1000, 1000)],
)
def test_growth_count_real_raw_ceil_and_source_unsigned_old_bucket_rule(old, requested, expected):
    f = Fixture()
    table = f.memory.allocate(64)
    f.memory.write(table, 4, 0x3F800000)
    f.memory.write(table + 0x38, 8, old)
    assert f.invoke(COUNT, table, requested) == expected
    assert f.targets(CEIL) and f.targets(CEIL, kind="i")


@pytest.mark.parametrize("threshold,expected", [(0, 9), (0x41000000, (1 << 63) + 1)])
def test_growth_holds_old_buckets_but_reads_conversion_threshold_after_ceil(threshold, expected):
    f = Fixture()
    table = f.memory.allocate(64)
    f.memory.write(table, 4, 0x3F800000)
    f.memory.write(table + 0x38, 8, 1)
    f.memory.write(0x143199EF0, 8, REHASH)

    def selected(args):
        assert f.events[-1][0] == "i" and args == (0x41100000,)
        f.memory.write(table + 0x38, 8, 999)
        f.memory.write(0x1436A0308, 4, threshold)
        return 0x41100000

    f.effects[REHASH] = selected
    assert f.invoke(COUNT, table, 9) == expected
    # Threshold0 gives9; threshold8 gives CVTT(9-8)+highbit.
    assert f.targets(REHASH) == [] and f.targets(REHASH, kind="i") == [(0x41100000,)]
    assert f.events[-1] == ("r", 0x1436A0308, 4, threshold)


def test_growth_unsigned_high_input_uses_sticky_conversion_and_invalid_cvtt_word():
    f = Fixture()
    table = f.memory.allocate(64)
    f.memory.write(table, 4, 0x3F800000)
    f.memory.write(table + 0x38, 8, 0)
    assert f.invoke(COUNT, table, U64) == 1 << 63
    assert f.targets(CEIL) == [(0x5F800000,)]


@pytest.mark.parametrize(
    "word,expected", [(0x7FC12345, 1 << 63), (0x5F000000, 1 << 63), (0xBF800000, U64), (0, 8)]
)
def test_growth_raw_ceil_nan_negative_threshold_and_zero_keep_source_conversion(word, expected):
    f = Fixture()
    table = f.memory.allocate(64)
    f.memory.write(table, 4, 0x3F800000)
    f.memory.write(table + 0x38, 8, 0)
    f.memory.write(0x143199EF0, 8, 0xBC22)
    f.effects[0xBC22] = lambda args: word
    assert f.invoke(COUNT, table, 1) == expected


def test_bulk_fill_holds_one_source_value_then_scalar_tail_rereads_it():
    f = Fixture()
    begin, source = f.words((1, 2, 3)), f.words((20,))

    def mutate(address, width, value):
        if address == source:
            f.memory.write(source, 8, 99)

    f.on_read = mutate
    f.invoke(FILL, begin, begin + 24, source)
    assert [f.memory.read(begin + i * 8, 8) for i in range(3)] == [20, 20, 99]
    assert [row[3] for row in f.events if row[:3] == ("r", source, 8)] == [20, 99]


def test_overlap_reads_source_before_decision_then_each_scalar_store_uses_current_source():
    f = Fixture()
    begin = f.words((10, 20, 30))
    source = begin + 8

    def mutate(address, width, value):
        if address == begin:
            f.memory.write(source, 8, 99)

    f.on_write = mutate
    f.invoke(FILL, begin, begin + 24, source)
    assert [f.memory.read(begin + i * 8, 8) for i in range(3)] == [20, 99, 99]
    assert [row[3] for row in f.events if row[:3] == ("r", source, 8)] == [20, 20, 99, 99]


def test_empty_fill_skips_source_and_reversed_fill_preserves_bounded_real_prefix():
    f = Fixture(stores=1)
    f.invoke(FILL, 0xBAD, 0xBAD, 0xDEAD)
    assert f.events == []
    begin, source = f.words((1, 2, 3, 4)), f.words((77,))
    with pytest.raises(UnresolvedReplayTaskRebuild, match="stores budget"):
        f.invoke(FILL, begin + 16, begin, source)
    assert f.memory.read(begin + 16, 8) == 77
    assert f.memory.read(begin + 24, 8) == 4
    assert len([row for row in f.events if row[:3] == ("r", source, 8)]) == 2


def test_vector_reuse_fills_whole_held_old_range_and_passes_live_saved_value_home():
    f = Fixture()
    begin = f.words((1, 2, 3))
    header = f.header(begin, begin + 24, begin + 24)

    def fill(args):
        assert args[:2] == (begin, begin + 24)
        assert f.locals[-1] == (args[2], 8)
        assert f.memory.read(args[2], 8) == 91
        f.memory.write(args[2], 8, 92)
        return f.invoke(FILL, *args)

    f.effects[FILL] = fill
    f.invoke(VECTOR, header, 1, 91)
    assert [f.memory.read(begin + i * 8, 8) for i in range(3)] == [92] * 3
    assert f.memory.read_bytes(header, 24) == b"".join(
        value.to_bytes(8, "little") for value in (begin, begin + 24, begin + 24)
    )
    assert not f.targets(ALLOC)


def test_vector_allocation_rereads_current_old_begin_capacity_and_fills_held_value():
    f = Fixture()
    old, replacement = f.words((1,)), f.words((2, 3))
    header = f.header(old, old + 8, old + 8)

    def allocate(args):
        assert args == (24,) and f.engine.call
        result = f.engine.call(ALLOC, args, None)
        f.memory.write(header, 8, replacement)
        f.memory.write(header + 0x10, 8, replacement + 16)
        f.memory.write(f.locals[-1][0], 8, 0xBAD)
        return result

    f.effects[ALLOC] = allocate
    f.invoke(VECTOR, header, 3, 44)
    pointer = f.memory.read(header, 8)
    assert f.targets(RELEASE) == [(header, replacement, 2)]
    assert [f.memory.read(pointer + i * 8, 8) for i in range(3)] == [44] * 3
    assert f.memory.read(old, 8) == 1
    with pytest.raises(ReplayMemoryError):
        f.memory.read(replacement, 1)
    writes = [row[1:] for row in f.events if row[0] == "w" and header <= row[1] < header + 24]
    assert writes == [
        (header, 8, pointer),
        (header + 8, 8, pointer + 24),
        (header + 16, 8, pointer + 24),
    ]


def test_vector_release_refusal_preserves_old_header_after_real_new_allocation():
    f = Fixture()
    old = f.words((1,))
    header = f.header(old, old + 8, old + 8)
    before = f.memory.read_bytes(header, 24)
    f.unavailable.add(RELEASE)
    with pytest.raises(UnresolvedReplayTaskRebuild, match="authored missing"):
        f.invoke(VECTOR, header, 3, 88)
    assert f.memory.read_bytes(header, 24) == before
    assert f.targets(ALLOC) == [(24,)] and not f.locals


def test_vector_error_is_actual_and_returning_error_stops_before_its_trap():
    f = Fixture()
    header = f.header(0, 0, 0)
    with pytest.raises(ReplayMemoryRuntimeError):
        f.invoke(VECTOR, header, 1 << 61, 0)
    f.effects[0x1402A9460] = lambda args: None
    with pytest.raises(UnresolvedReplayTaskRebuild, match="1409692b1"):
        f.invoke(VECTOR, header, 1 << 61, 0)
    assert not f.targets(ALLOC)


def test_release_small_zero_tail_preserves_raw_result_without_header_access():
    f = Fixture()

    def free(args):
        assert f.engine.call
        assert f.engine.call(FREE, args, None) is None
        return U64

    f.effects[FREE] = free
    assert f.invoke(RELEASE, 0xBAD, 0, 0) == U64
    assert f.events == [("c", FREE, (0, 0))]


def test_release_large_uses_real_aligned_backpointer_and_sized_free():
    f = Fixture()
    pointer = f.memory.allocate_aligned(4096)
    base = f.memory.read(pointer - 8, 8)
    f.invoke(RELEASE, 0xBAD, pointer, 512)
    assert f.targets(FREE) == [(base, 0x1027)]
    with pytest.raises(ReplayMemoryError):
        f.memory.read(pointer, 1)


def test_release_watson_uses_current_terminal_target_and_live_fifth_after_slot_read():
    f = Fixture()
    base = f.words((0, 0))
    pointer = base + 8
    f.memory.write(base, 8, pointer)  # Wrapped negative delta, invalid.
    f.memory.map_bytes(0x14319A060, REHASH.to_bytes(8, "little"))

    def mutate(address, width, value):
        if address == 0x14319A060:
            f.memory.write(f.locals[-1][0], 8, 0x1234)

    def terminal(args):
        assert f.events[-1][0] == "i" and args == (0, 0, 0, 0, 0x1234)
        return None

    f.on_read, f.effects[REHASH] = mutate, terminal
    with pytest.raises(UnresolvedReplayTaskRebuild, match="140969f35"):
        f.invoke(RELEASE, 0, pointer, 512)
    assert not f.targets(FREE) and not f.targets(REHASH)
    assert f.closed[-1][1] == (0x1234).to_bytes(8, "little")


@pytest.mark.parametrize("requested,expected", [(0, 1), (1, 2), (2, 2), (3, 4), (4, 4)])
def test_empty_rehash_bsr_corner_counts_and_ordered_header_updates(requested, expected):
    f = Fixture()
    table, sentinel, old, _nodes = f.alias_table([])
    f.invoke(REHASH, table, requested)
    assert f.memory.read(table + 0x38, 8) == expected
    assert f.memory.read(table + 0x30, 8) == expected - 1
    header_writes = [
        row[1:] for row in f.events if row[0] == "w" and row[1] in (table + 0x38, table + 0x30)
    ]
    assert header_writes == [(table + 0x38, 8, expected), (table + 0x30, 8, expected - 1)]
    buckets = f.memory.read(table + 0x18, 8)
    assert [f.memory.read(buckets + i * 8, 8) for i in range(2 * expected)] == (
        [sentinel] * (2 * expected)
    )
    if expected > 1:
        with pytest.raises(ReplayMemoryError):
            f.memory.read(old, 1)


@pytest.mark.parametrize(
    "keys,order,first,last",
    [
        ((b"A", b"C"), (1, 0), 1, 0),
        ((b"A", b"C", b"A"), (1, 0, 2), 1, 2),
        ((b"A", b"C", b"C"), (1, 2, 0), 1, 0),
        ((b"A", b"B", b"A"), (0, 2, 1), 0, 2),
    ],
)
def test_real_rehash_splice_cases_have_literal_list_and_bucket_boundaries(keys, order, first, last):
    f = Fixture()
    table, sentinel, _old, nodes = f.alias_table(keys)
    f.invoke(REHASH, table, 1)  # B2: odd ASCII final bytes use literal bucket0.
    buckets = f.memory.read(table + 0x18, 8)
    assert f.memory.read(buckets, 8) == nodes[first]
    assert f.memory.read(buckets + 8, 8) == nodes[last]
    chain = [sentinel, *(nodes[i] for i in order), sentinel]
    for before, after in pairwise(chain):
        assert f.memory.read(before, 8) == after
        assert f.memory.read(after + 8, 8) == before
    assert f.memory.read(table + 0x10, 8) == len(keys)
    assert [f.memory.read(node + 0x30, 4) for node in nodes] == list(range(100, 100 + len(keys)))


def test_first_compare_reloads_bucket_home_and_rewrites_held_capacity_home():
    f = Fixture()
    table, sentinel, _old, nodes = f.alias_table((b"A", b"A"))
    alternate = f.words((sentinel, sentinel))

    def compare(args):
        result = f.actual_compare(args)
        home, width = f.locals[-1]
        assert width == 32
        f.memory.write(home + 8, 8, alternate)
        f.memory.write(home, 8, 99)
        return result

    f.effects[COMPARE] = compare
    f.invoke(REHASH, table, 1)
    buckets = f.memory.read(table + 0x18, 8)
    assert f.memory.read(buckets + 8, 8) == nodes[0]
    assert f.memory.read(alternate + 8, 8) == nodes[1]
    assert int.from_bytes(f.closed[-1][1][:8], "little") == 15


@pytest.mark.parametrize("late_reload", [False, True])
def test_branch_specific_map_vector_home_reload_precedes_or_follows_splice_writes(late_reload):
    f = Fixture()
    keys = (b"A", b"B", b"A", b"C") if late_reload else (b"A", b"C", b"B")
    table, sentinel, _old, nodes = f.alias_table(keys)
    shadow = f.memory.allocate(64)
    alternate = f.words((sentinel, sentinel))
    f.memory.write(shadow + 0x30, 8, 0)
    f.memory.write(shadow + 0x18, 8, alternate)
    trigger = nodes[1] if late_reload else nodes[0]
    seen = False

    def mutate(address, width, value):
        nonlocal seen
        if address == trigger and not seen:
            seen = True
            home = f.locals[-1][0]
            f.memory.write(home + 16, 8, shadow)
            f.memory.write(home + 24, 8, shadow + 0x18)

    f.on_write = mutate
    f.invoke(REHASH, table, 1)
    assert seen
    assert f.memory.read(alternate, 8) == (nodes[3] if late_reload else sentinel)
    assert f.memory.read(alternate + 8, 8) == (nodes[3] if late_reload else sentinel)


def test_later_failed_compare_reloads_current_capacity_home_for_the_next_query_pointer():
    f = Fixture()
    keys = tuple(b"X" * 15 + value for value in (b"A", b"C", b"E", b"G"))
    table, _sentinel, _old, nodes = f.alias_table(keys)
    query = f.memory.read(nodes[-1] + 0x10, 8)
    observed = []

    def compare(args):
        result = f.actual_compare(args)
        if args[0] in (query, nodes[-1] + 0x10):
            observed.append(args[0])
            if len(observed) == 2:
                f.memory.write(f.locals[-1][0], 8, 15)
        return result

    f.effects[COMPARE] = compare
    f.invoke(REHASH, table, 1)
    assert observed == [query, query, nodes[-1] + 0x10]


def test_rehash_error_guard_preserves_saved_map_home_and_actual_error_frontier():
    f = Fixture()
    table = f.memory.allocate(64)
    f.effects[0x142D66698] = lambda args: None
    with pytest.raises(UnresolvedReplayTaskRebuild, match="140969be5"):
        f.invoke(REHASH, table, (1 << 59) + 1)
    assert f.targets(0x142D66698) == [(0x143682938,)]
    assert f.closed[-1][1][16:24] == table.to_bytes(8, "little")
    assert not f.targets(VECTOR)


def test_shared_fill_store_budget_survives_owned_vector_reentry_and_outer_call_resets():
    f = Fixture(stores=1)
    table, _sentinel, _old, _nodes = f.alias_table([])
    for _ in range(2):
        with pytest.raises(UnresolvedReplayTaskRebuild, match="stores budget"):
            f.invoke(REHASH, table, 1)
        assert not f.locals
    assert len(f.targets(VECTOR)) == 2


@pytest.mark.parametrize(
    "target,args",
    [
        (COUNT, (1,)),
        (REHASH, (1,)),
        (VECTOR, (1, 2)),
        (FILL, (1, 2)),
        (RELEASE, (1, 2)),
        (CEIL, ()),
    ],
)
def test_known_arity_payload_and_unsigned_arguments_refuse_before_effects(target, args):
    f = Fixture()
    with pytest.raises(ValueError, match="malformed"):
        f.invoke(target, *args)
    assert f.events == []


def test_unknown_delegate_keeps_payload_identity_arguments_and_raw_none_result():
    f = Fixture()
    view = memoryview(bytearray(b"abc"))
    seen = []

    def delegate(target, args, data):
        assert data is view
        seen.append((target, args, data))
        return None

    bound = bind_replay_localization_alias_growth(
        f.context,
        ReplayTaskRebuildCalls(delegate),
        bind_local=f.bind_local,
        scratch=ReplayLocalizationAliasGrowthScratch(bytes(8), bytes(32), bytes(8)),
        profile=ReplayLocalizationAliasGrowthProfile(0, 0, 0, 0, 0x1F80),
    )
    assert bound.call and bound.call(0x123, (7,), view) is None
    assert seen == [(0x123, (7,), view)]


@pytest.mark.parametrize(
    "values",
    [
        (bytes(7), bytes(32), bytes(8)),
        (bytes(8), bytes(31), bytes(8)),
        (bytes(8), bytes(32), bytearray(8)),
    ],
)
def test_exact_local_seeds_required(values):
    with pytest.raises(ValueError):
        ReplayLocalizationAliasGrowthScratch(*values)


@pytest.mark.parametrize("mxcsr", [0, 0x1FC0, 0x9F80, 0x3F80, True])
def test_explicit_masked_nearest_even_fp_profile_required(mxcsr):
    with pytest.raises(ValueError):
        ReplayLocalizationAliasGrowthProfile(1, 1, 1, 1, mxcsr)
