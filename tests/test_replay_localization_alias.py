"""Source-led alias controls; authored tables do not select a replay profile."""

from contextlib import contextmanager

import pytest

from vantage.replay_localization_alias import (
    ReplayLocalizationAliasProfile,
    ReplayLocalizationAliasScratch,
    bind_replay_localization_alias,
)
from vantage.replay_localization_alias_growth import (
    ReplayLocalizationAliasGrowthProfile,
    ReplayLocalizationAliasGrowthScratch,
    bind_replay_localization_alias_growth,
)
from vantage.replay_localization_runtime import (
    ReplayLocalizationRuntime,
    ReplayLocalizationTargets,
)
from vantage.replay_memory import ReplayMemory, ReplayMemoryError, ReplayMemoryRuntimeError
from vantage.replay_memory_compare import (
    bind_replay_memcmp_thunk,
    replay_memory_comparison_calls,
)
from vantage.replay_player_localization_catalog import (
    ReplayLocalizationCatalogProfile,
    bind_replay_player_localization_catalog,
)
from vantage.replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
)
from vantage.replay_unit_constructor_support import bind_replay_unit_constructor_support

LOOKUP, FIND, INSERT = 0x140964460, 0x140961D10, 0x140961DE0
INSERT_VALUE = 0x140962270
COMPARE, STRLEN, COPY, FREE = 0x142D6E3BD, 0x142D6E44D, 0x142D6E3B1, 0x142D6BAB4
LOCK, UNLOCK, THROW = 0x142D6AA5B, 0x142D6AA61, 0x142D6AA67
LENGTH, GROW, REHASH = 0x1402A91E0, 0x140969420, 0x140969930
TOKENS = ReplayLocalizationTargets(0xC00010, 0xC00020, 0xC00030, 0xC00040, 0xC00050)
MEMCMP, LEN = 0xD00010, 0xD00020
U64 = (1 << 64) - 1


class Fixture:
    def __init__(self, entries=((b"alpha", 7),), *, budget=4096, nodes=64):
        self.memory = ReplayMemory(max_bytes=1 << 20)
        self.manager = self.memory.allocate(0x2D0)
        self.table = self.manager + 0x240
        self.sentinel, self.buckets = self.memory.allocate(56), self.memory.allocate(16)
        self.events, self.locals, self.closed = [], [], []
        self.effects = {}
        self.on_read = self.on_write = None
        self.context = ReplayTaskRebuildStorage(self.manager, self.read, self.write)
        self.calls = ReplayTaskRebuildCalls(self.dispatch)
        capabilities = replay_memory_comparison_calls(
            self.memory,
            comparison_target=MEMCMP,
            strlen_target=LEN,
        )
        self.services = ReplayLocalizationRuntime(self.memory, TOKENS, delegate=capabilities)
        self.runtime = self.services.calls()
        self.imports = ReplayTaskRebuildCalls(self.terminal)
        self.bound = bind_replay_localization_alias(
            self.context,
            self.calls,
            bind_local=self.bind_local,
            scratch=ReplayLocalizationAliasScratch(b"\xa5" * 0xA0, b"\xb6" * 0x40),
            profile=ReplayLocalizationAliasProfile(budget, nodes),
            imports=self.imports,
        )
        self.compare = bind_replay_memcmp_thunk(self.context, self.calls, imports=self.imports)
        self.support = bind_replay_unit_constructor_support(
            self.context,
            self.calls,
            bind_local=self.bind_local,
            imports=self.imports,
        )
        self.catalog = bind_replay_player_localization_catalog(
            self.context,
            self.calls,
            profile=ReplayLocalizationCatalogProfile(0, 0, 0, 0),
            imports=self.imports,
        )
        self.growth = bind_replay_localization_alias_growth(
            self.context,
            self.calls,
            bind_local=self.bind_local,
            scratch=ReplayLocalizationAliasGrowthScratch(bytes(8), bytes(32), bytes(8)),
            profile=ReplayLocalizationAliasGrowthProfile(10000, 1000, 10000, 1000, 0x1F80),
            imports=self.imports,
        )
        for slot, token in (
            (0x143199940, MEMCMP),
            (0x14319A290, LEN),
            (0x143199930, 0x142D6E3DB),
            (0x143199DD0, FREE),
            (0x143199288, TOKENS.lock),
            (0x143199280, TOKENS.unlock),
            (0x143199278, TOKENS.error),
        ):
            self.memory.map_bytes(slot, token.to_bytes(8, "little"))
        self.memory.map_bytes(0x143199EF0, (0x142D6E453).to_bytes(8, "little"))
        self.memory.map_bytes(0x1436A0308, (0x5F000000).to_bytes(4, "little"))
        # Explicit nongrowth branch admission for these unit fixtures, not a
        # claim about the native constructor's maximum load factor.
        self.memory.write(self.table, 4, 0x7F800000)
        for offset, value in (
            (8, self.sentinel),
            (0x10, len(entries)),
            (0x18, self.buckets),
            (0x20, self.buckets + 16),
            (0x28, self.buckets + 16),
            (0x30, 0),
            (0x38, 1),
        ):
            self.memory.write(self.table + offset, 8, value)
        self.nodes = []
        for key, value in entries:
            node = self.memory.allocate(56)
            self.descriptor(key, node + 0x10)
            self.memory.write(node + 0x30, 4, value)
            self.nodes.append(node)
        chain = [self.sentinel, *self.nodes, self.sentinel]
        for index, node in enumerate(self.nodes, 1):
            self.memory.write(node, 8, chain[index + 1])
            self.memory.write(node + 8, 8, chain[index - 1])
        self.memory.write(self.sentinel, 8, self.nodes[0] if self.nodes else self.sentinel)
        self.memory.write(self.sentinel + 8, 8, self.nodes[-1] if self.nodes else self.sentinel)
        self.memory.write(self.buckets, 8, self.nodes[0] if self.nodes else self.sentinel)
        self.memory.write(self.buckets + 8, 8, self.nodes[-1] if self.nodes else self.sentinel)
        self.memory.write(self.manager + 0x2CC, 4, 0)
        self.services.register_mutex(self.manager + 0x280)

    def descriptor(self, raw, address=None):
        address = self.memory.allocate(32) if address is None else address
        if len(raw) <= 15:
            self.memory.write_bytes(address, (raw + b"\0").ljust(16, b"\0"))
            capacity = 15
        else:
            self.memory.write(address, 16, 0)
            self.memory.write(address, 8, self.string(raw))
            capacity = len(raw)
        self.memory.write(address + 0x10, 8, len(raw))
        self.memory.write(address + 0x18, 8, capacity)
        return address

    def string(self, raw):
        address = self.memory.allocate(len(raw) + 1)
        self.memory.write_bytes(address, raw + b"\0")
        return address

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
        if target in self.effects:
            return self.effects[target](args)
        if target in (LOOKUP, FIND, INSERT, INSERT_VALUE):
            return self.invoke(target, *args, data=data)
        if target == COMPARE:
            selected = self.compare
        elif target in (GROW, REHASH, 0x1409691F0, 0x1409624E0, 0x140969EE0, 0x142D6E453):
            selected = self.growth
        elif target in (LOCK, UNLOCK, THROW):
            selected = self.catalog
        elif target in (STRLEN, COPY, 0x142D6C268, 0x142D6C270):
            selected = self.support
        else:
            selected = self.runtime
        assert selected.call is not None
        return selected.call(target, args, data)

    def terminal(self, target, args, data):
        self.events.append(("i", target, args))
        if target in self.effects:
            return self.effects[target](args)
        assert self.runtime.call is not None
        return self.runtime.call(target, args, data)

    def invoke(self, target, *args, data=None):
        assert self.bound.call is not None
        return self.bound.call(target, args, data)

    def targets(self, target, kind="c"):
        return [event[2] for event in self.events if event[:2] == (kind, target)]

    def output(self):
        address = self.memory.allocate(16)
        self.memory.write_bytes(address, b"\xd7" * 16)
        return address


def test_empty_bucket_does_not_read_source_descriptor_or_first_boundary():
    f = Fixture(entries=(), nodes=0)
    output = f.output()
    f.memory.write(f.buckets, 8, 0xBAD)
    assert f.invoke(FIND, f.table, output, 0xDEAD, U64) == output
    assert f.memory.read(output, 8) == f.sentinel
    assert f.memory.read(output + 8, 8) == 0
    assert not any(event[0] == "r" and event[1] == f.buckets for event in f.events)


@pytest.mark.parametrize("query,index", [(b"alpha", 0), (b"bravo", 1), (b"charlie", 2)])
def test_find_real_backwards_chain_returns_current_forward_and_matched_node(query, index):
    f = Fixture(entries=((b"alpha", 7), (b"bravo", 8), (b"charlie", 9)))
    output, source = f.output(), f.descriptor(query)
    assert f.invoke(FIND, f.table, output, source, 0) == output
    assert f.memory.read(output, 8) == f.memory.read(f.nodes[index], 8)
    assert f.memory.read(output + 8, 8) == f.nodes[index]
    assert f.targets(COMPARE)


def test_find_zero_length_matches_without_memcmp_and_mismatch_returns_held_first():
    f = Fixture(entries=((b"", 7),))
    output = f.output()
    f.invoke(FIND, f.table, output, f.descriptor(b""), 0)
    assert f.memory.read(output + 8, 8) == f.nodes[0]
    assert not f.targets(COMPARE)
    f.invoke(FIND, f.table, output, f.descriptor(b"longer"), 0)
    assert f.memory.read(output, 8) == f.nodes[0]
    assert f.memory.read(output + 8, 8) == 0
    assert not f.targets(COMPARE)


def test_find_reads_current_forward_after_low_eax_equal_compare_then_orders_output_writes():
    f = Fixture()
    output, source = f.output(), f.descriptor(b"alpha")

    def compare(args):
        f.memory.write(f.nodes[0], 8, 0xCAFEBABE)
        return 1 << 32

    f.effects[COMPARE] = compare
    f.invoke(FIND, f.table, output, source, 0)
    assert f.memory.read(output, 8) == 0xCAFEBABE
    writes = [event for event in f.events if event[0] == "w"]
    assert writes[-2:] == [("w", output, 8, 0xCAFEBABE), ("w", output + 8, 8, f.nodes[0])]


def test_find_holds_length_capacity_boundary_but_rereads_heap_query_pointer():
    key = b"A" * 20
    f = Fixture(entries=((key, 7), (b"B" * 20, 8)))
    source, output = f.descriptor(b"B" * 20), f.output()
    second_pointer = f.string(key)

    def compare(args):
        if len(f.targets(COMPARE)) == 1:
            f.memory.write(source, 8, second_pointer)
            f.memory.write(source + 0x10, 8, 0)
            f.memory.write(source + 0x18, 8, 0)
            f.memory.write(f.buckets, 8, f.nodes[1])
            return 1
        assert args == (second_pointer, f.memory.read(f.nodes[0] + 0x10, 8), 20)
        return 0

    f.effects[COMPARE] = compare
    f.invoke(FIND, f.table, output, source, 0)
    assert f.memory.read(output + 8, 8) == f.nodes[0]
    assert len(f.targets(COMPARE)) == 2


@pytest.mark.parametrize("key", [b"alpha", b"", b"X" * 16, b"Y" * 32])
def test_existing_insert_returns_only_byte_false_preserving_other_output_bytes_and_source(key):
    f = Fixture(entries=((key, 7),))
    source, output = f.descriptor(key), f.output()
    before = f.memory.read_bytes(source, 32)
    assert f.invoke(INSERT, f.table, output, source) == output
    assert f.memory.read(output, 8) == f.nodes[0]
    assert f.memory.read_bytes(output + 8, 8) == b"\0" + b"\xd7" * 7
    assert f.memory.read_bytes(source, 32) == before
    assert not f.targets(0x142D6BA78) and not f.targets(GROW)


@pytest.mark.parametrize("key", [b"alpha", b"X" * 20])
def test_missing_insert_moves_string_resets_source_and_splices_real_sentinel_links(key):
    f = Fixture(entries=())
    source, output = f.descriptor(key), f.output()
    before = f.memory.read_bytes(source, 32)
    assert f.invoke(INSERT, f.table, output, source) == output
    node = f.memory.read(output, 8)
    assert f.memory.read_bytes(node + 0x10, 32) == before
    assert f.memory.read(node + 0x30, 4) == 0
    assert f.memory.read(source, 1) == 0
    assert f.memory.read(source + 0x10, 8) == 0
    assert f.memory.read(source + 0x18, 8) == 15
    assert f.memory.read(node, 8) == f.memory.read(node + 8, 8) == f.sentinel
    assert f.memory.read(f.sentinel, 8) == f.memory.read(f.sentinel + 8, 8) == node
    assert f.memory.read(f.buckets, 8) == f.memory.read(f.buckets + 8, 8) == node
    assert f.memory.read(f.table + 0x10, 8) == 1
    assert f.memory.read_bytes(output + 8, 8) == b"\1" + b"\xd7" * 7
    with pytest.raises(ReplayMemoryError):
        f.memory.read(node + 0x34, 4)


def test_insert_load_factor_grows_with_held_count_plus_one_then_reloads_current_headers():
    f = Fixture(entries=())
    source, output = f.descriptor(b"new"), f.output()
    f.memory.write(f.table, 4, 0x3F000000)  # 1/1 >0.5.
    new_buckets = f.memory.allocate(16)
    f.memory.write(new_buckets, 8, f.sentinel)
    f.memory.write(new_buckets + 8, 8, f.sentinel)

    def growth(args):
        assert args == (f.table, 1)
        assert f.memory.read(source, 1) == 0  # Move/reset precedes growth.
        return 8

    def rehash(args):
        assert args == (f.table, 8)
        f.memory.write(f.table + 0x18, 8, new_buckets)

    f.effects[GROW], f.effects[REHASH] = growth, rehash
    f.invoke(INSERT, f.table, output, source)
    node = f.memory.read(output, 8)
    assert f.memory.read(new_buckets, 8) == f.memory.read(new_buckets + 8, 8) == node
    assert f.memory.read(f.buckets, 8) == f.sentinel


def test_payload_insert_grows_real_bucket_vector_then_finds_all_preserved_ids():
    f = Fixture(entries=((b"alpha", 7), (b"bravo", 8)))
    f.memory.write(f.table, 4, 0x3F800000)
    source = f.memory.allocate(36)
    f.descriptor(b"charlie", source)
    f.memory.write(source + 0x20, 4, 9)
    output = f.output()
    f.invoke(INSERT_VALUE, f.table, output, source)
    assert f.memory.read(f.table + 0x10, 8) == 3
    assert f.memory.read(f.table + 0x30, 8) == 7
    assert f.memory.read(f.table + 0x38, 8) == 8
    assert f.targets(GROW) == [(f.table, 3)]
    assert f.targets(REHASH) == [(f.table, 8)]
    assert f.memory.read(f.table + 0x18, 8) != f.buckets
    with pytest.raises(ReplayMemoryError):
        f.memory.read(f.buckets, 1)
    for key, value in ((b"alpha", 7), (b"bravo", 8), (b"charlie", 9)):
        assert f.invoke(LOOKUP, f.manager, f.string(key)) == value
    assert f.memory.read(f.manager + 0x2CC, 4) == 0


def test_insert_mandatory_allocation_refusal_keeps_source_intact_and_locals_expire():
    f = Fixture(entries=())
    source, output = f.descriptor(b"new"), f.output()
    before = f.memory.read_bytes(source, 32)
    f.effects[0x142D6BA78] = lambda args: (_ for _ in ()).throw(
        UnresolvedReplayTaskRebuild("allocator unavailable")
    )
    with pytest.raises(UnresolvedReplayTaskRebuild, match="allocator unavailable"):
        f.invoke(INSERT, f.table, output, source)
    assert f.memory.read_bytes(source, 32) == before
    assert not f.locals and f.closed[-1][1][0x20:0x28] == (f.table + 8).to_bytes(8, "little")
    with pytest.raises(ReplayMemoryError):
        f.memory.read(f.closed[-1][0], 1)


def test_insert_count_limit_calls_actual_length_error_before_allocating_or_moving():
    f = Fixture(entries=())
    source, output = f.descriptor(b"new"), f.output()
    before = f.memory.read_bytes(source, 32)
    f.memory.write(f.table + 0x10, 8, 0x0492492492492492)
    f.effects[0x142D66698] = lambda args: None
    with pytest.raises(UnresolvedReplayTaskRebuild, match="INT3 140962041"):
        f.invoke(INSERT, f.table, output, source)
    assert f.targets(0x142D66698) == [(0x143682918,)]
    assert not f.targets(0x142D6BA78)
    assert f.memory.read_bytes(source, 32) == before


@pytest.mark.parametrize(
    "key,value",
    [
        (b"alpha", 7),
        (b"", 0),
        (b"IDS_PROGRAM_TITLE", 1001),
        (b"IDS_TEXT_CLOSE_BUTTON", 1002),
    ],
)
def test_numeric_lookup_uses_real_strings_two_map_lookups_and_balanced_mutex(key, value):
    # The two symbolic key/value pairs match the pinned stringreference.json;
    # this is authored backing, not native startup or current profile identity.
    f = Fixture(entries=((key, value),))
    query = f.string(key)
    assert f.invoke(LOOKUP, f.manager, query) == value
    assert f.memory.read(f.manager + 0x2CC, 4) == 0
    assert len(f.targets(STRLEN)) == 2
    assert len(f.targets(INSERT)) == len(f.targets(FIND)) == 1
    assert len(f.targets(FREE)) == (2 if len(key) > 15 else 0)
    assert not f.targets(GROW) and not f.locals
    assert [len(raw) for _, raw in f.closed] == [0x40, 0xA0]


def test_numeric_miss_is_real_zero_after_first_temporary_cleanup_and_unlock():
    f = Fixture(entries=())
    query = f.string(b"MissingLongSymbolicName")
    assert f.invoke(LOOKUP, f.manager, query) == 0
    assert len(f.targets(STRLEN)) == len(f.targets(FREE)) == 1
    assert not f.targets(INSERT)
    assert f.memory.read(f.manager + 0x2CC, 4) == 0


def test_initial_empty_bucket_zeros_candidate_before_reading_current_sentinel_home():
    f = Fixture(entries=())

    def mutate(address, width, value):
        if f.locals and address == f.locals[0][0] + 0x88 and value == f.sentinel:
            f.memory.write(address, 8, 0xDEADBEEF)

    f.on_write = mutate
    assert f.invoke(LOOKUP, f.manager, f.string(b"alpha")) == 0
    assert len(f.targets(STRLEN)) == 1 and not f.targets(INSERT)
    assert f.memory.read(f.manager + 0x2CC, 4) == 0


@pytest.mark.parametrize("value", [0, 1001, 0xFFFFFFFF])
def test_payload_insertion_reads_current_value_after_string_move_and_source_reset(value):
    f = Fixture(entries=())
    source = f.memory.allocate(36)
    f.descriptor(b"alpha", source)
    f.memory.write(source + 0x20, 4, 123)
    output = f.output()

    def mutate(address, width, written):
        if (address, width, written) == (source, 1, 0):
            f.memory.write(source + 0x20, 4, value)

    f.on_write = mutate
    assert f.invoke(INSERT_VALUE, f.table, output, source) == output
    node = f.memory.read(output, 8)
    assert f.memory.read(node + 0x30, 4) == value
    assert f.memory.read(source + 0x10, 8) == 0


@pytest.mark.parametrize("number,trap", [(1, "1409647be"), (2, "140964799")])
def test_numeric_string_length_errors_require_actual_child_and_retain_held_lock(number, trap):
    f = Fixture()
    strlen = f.support.call

    def length(args):
        assert strlen is not None
        return U64 if len(f.targets(STRLEN)) == number else strlen(STRLEN, args, None)

    f.effects[STRLEN] = length
    f.effects[LENGTH] = lambda args: None
    with pytest.raises(UnresolvedReplayTaskRebuild, match=f"INT3 {trap}"):
        f.invoke(LOOKUP, f.manager, f.string(b"alpha"))
    assert f.targets(LENGTH) == [()]
    assert not f.targets(UNLOCK) and not f.locals
    assert f.memory.read(f.manager + 0x2CC, 4) == 1


def test_large_string_invalid_free_uses_current_import_and_live_fifth_home_before_trap():
    key = b"K" * 4080
    f = Fixture(entries=((key, 7),), budget=8192)
    query = f.string(key)
    original_copy = f.support.call
    allocated = []

    def copy(args):
        assert original_copy is not None
        result = original_copy(COPY, args, None)
        allocated.append(args[0])
        f.memory.write(args[0] - 8, 8, args[0] - 0x40)
        return result

    terminal = 0xD00030
    f.effects[COPY] = copy
    f.memory.map_bytes(0x14319A060, terminal.to_bytes(8, "little"))

    def read(address, width, value):
        if address == 0x14319A060:
            f.memory.write(f.locals[0][0] + 0x20, 8, 0xABCD)

    f.on_read = read
    seen = []
    f.effects[terminal] = lambda args: seen.append(args)
    with pytest.raises(UnresolvedReplayTaskRebuild, match="INT3 14096465c"):
        f.invoke(LOOKUP, f.manager, query)
    assert seen == [(0, 0, 0, 0, 0xABCD)]
    assert len(allocated) == 1 and not f.targets(FREE) and not f.targets(UNLOCK)
    assert f.memory.read(f.manager + 0x2CC, 4) == 1


def test_numeric_second_string_rereads_original_key_and_really_inserts_after_mutation():
    f = Fixture(entries=((b"alpha", 7),))
    query = f.string(b"alpha")
    original = f.support.call

    def strlen(args):
        if len(f.targets(STRLEN)) == 2:
            f.memory.write_bytes(query, b"bravo\0")
        assert original is not None
        return original(STRLEN, args, None)

    f.effects[STRLEN] = strlen
    assert f.invoke(LOOKUP, f.manager, query) == 0
    assert f.memory.read(f.table + 0x10, 8) == 2
    assert f.targets(0x142D6BA78) == [(56,)]
    assert f.memory.read(f.manager + 0x2CC, 4) == 0


def test_numeric_returns_current_result_home_after_actual_unlock_effect():
    f = Fixture()
    native_thunk = f.catalog.call

    def unlock(args):
        assert native_thunk is not None
        native_thunk(UNLOCK, args, None)
        f.memory.write(f.locals[0][0] + 0x30, 4, 0xCAFEBABE)
        return U64

    f.effects[UNLOCK] = unlock
    assert f.invoke(LOOKUP, f.manager, f.string(b"alpha")) == 0xCAFEBABE


@pytest.mark.parametrize("error", [5, 6])
def test_lock_failure_or_count_overflow_terminates_without_unlock(error):
    f = Fixture()
    if error == 5:
        f.effects[LOCK] = lambda args: 1
    else:
        f.memory.write(f.manager + 0x2CC, 4, 0x7FFFFFFE)
    with pytest.raises(ReplayMemoryRuntimeError) as caught:
        f.invoke(LOOKUP, f.manager, 0xDEAD)
    assert caught.value.args_words == (error,)
    assert not f.targets(STRLEN) and not f.targets(UNLOCK)
    if error == 6:
        assert f.memory.read(f.manager + 0x2CC, 4) == 0x7FFFFFFE


def test_lock_tests_low_eax_after_actual_successful_stateful_lock():
    f = Fixture()
    thunk = f.catalog.call

    def lock(args):
        assert thunk is not None
        thunk(LOCK, args, None)
        return 1 << 32

    f.effects[LOCK] = lock
    assert f.invoke(LOOKUP, f.manager, f.string(b"alpha")) == 7
    assert f.memory.read(f.manager + 0x2CC, 4) == 0


def test_shared_byte_budget_spans_wrapper_and_insertion_and_refuses_with_held_lock():
    f = Fixture(budget=5)
    with pytest.raises(UnresolvedReplayTaskRebuild, match="key_bytes budget exhausted"):
        f.invoke(LOOKUP, f.manager, f.string(b"alpha"))
    assert f.targets(FIND) == []
    assert len(f.targets(STRLEN)) == 2
    assert f.memory.read(f.manager + 0x2CC, 4) == 1
    assert not f.targets(UNLOCK)


@pytest.mark.parametrize(
    "target,args",
    [
        (LOOKUP, (1,)),
        (FIND, (1, 2, 3)),
        (INSERT, (1, 2)),
    ],
)
def test_known_arity_errors_have_no_source_effects(target, args):
    f = Fixture()
    with pytest.raises(ValueError, match="malformed"):
        f.invoke(target, *args)
    assert f.events == []


def test_unknown_target_preserves_payload_identity_arguments_and_raw_return():
    f = Fixture()
    payload = memoryview(b"opaque")
    seen = []

    def delegate(target, args, data):
        seen.append((target, args, data is payload))
        return U64

    bound = bind_replay_localization_alias(
        f.context,
        ReplayTaskRebuildCalls(delegate),
        bind_local=f.bind_local,
        scratch=ReplayLocalizationAliasScratch(bytes(0xA0), bytes(0x40)),
        profile=ReplayLocalizationAliasProfile(0, 0),
    )
    assert bound.call(0xDEAD, (1, 2), payload) == U64
    assert seen == [(0xDEAD, (1, 2), True)]


@pytest.mark.parametrize(
    "lookup,insertion", [(b"", bytes(64)), (bytes(160), b""), (bytearray(160), bytes(64))]
)
def test_explicit_frame_seed_sizes_are_required(lookup, insertion):
    with pytest.raises(ValueError):
        ReplayLocalizationAliasScratch(lookup, insertion)


@pytest.mark.parametrize("values", [(-1, 0), (0, -1), (True, 1), (1, 1.0)])
def test_explicit_budget_types_and_bounds(values):
    with pytest.raises(ValueError):
        ReplayLocalizationAliasProfile(*values)
