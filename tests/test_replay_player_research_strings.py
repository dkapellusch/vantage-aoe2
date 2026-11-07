"""Source-led string controls using owned bytes and real string primitives.

Conversion and catalog callbacks are explicitly authored service seams. They
test the callers' protocol and mutation ordering, not native language identity.
"""

from __future__ import annotations

from contextlib import contextmanager

import pytest

from vantage.replay_memory import ReplayMemory, ReplayMemoryError
from vantage.replay_player_research_strings import (
    ReplayPlayerResearchStringsProfile,
    ReplayPlayerResearchStringsScratch,
    bind_replay_player_research_strings,
)
from vantage.replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
)
from vantage.replay_unit_constructor_support import bind_replay_unit_constructor_support

IDENTIFIER, RESOLVE, ASSIGN = 0x140803E30, 0x140803EA0, 0x140A15BF0
ACTIVE, MANAGER, LOOKUP, CATALOG, NUMBER = (
    0x140967520,
    0x140963BE0,
    0x140964A30,
    0x140964B80,
    0x140964460,
)
STRLEN, GETTER, GROW, COPY, FREE = (
    0x142D6E44D,
    0x140A13780,
    0x140A1A5E0,
    0x142D6E3B1,
    0x142D6C270,
)
GLOBAL, ITOA_IAT, CONVERT, CONVERT2, LEN_TOKEN = (
    0x1442842E8,
    0x143199CA0,
    0xC00010,
    0xC00020,
    0xC00030,
)
EMPTY, RESET, U64 = 0x143676DC8, 0x14428BB30, (1 << 64) - 1
ENTRIES = (IDENTIFIER, RESOLVE, ASSIGN, ACTIVE, MANAGER, LOOKUP)
SUPPORT = (STRLEN, GETTER, GROW, COPY, FREE, 0x142D6C268)


class Fixture:
    def __init__(self, *, budget=8):
        self.memory = ReplayMemory(max_bytes=1 << 20)
        self.subject, self.manager = self.memory.allocate(24), self.memory.allocate(0x240)
        self.memory.write(self.subject, 8, 0)
        self.memory.write(self.manager + 0x239, 1, 1)
        self.memory.map_bytes(GLOBAL, self.manager.to_bytes(8, "little"))
        self.memory.map_bytes(ITOA_IAT, CONVERT.to_bytes(8, "little"))
        self.memory.map_bytes(0x14319A290, LEN_TOKEN.to_bytes(8, "little"))
        # Authored owned imports. Disjoint memcpy uses actual byte movement;
        # overlapping native memcpy semantics are not asserted by these tests.
        self.memory.map_bytes(0x143199930, (0x142D6E3DB).to_bytes(8, "little"))
        self.memory.map_bytes(0x143199DD0, (0x142D6BAB4).to_bytes(8, "little"))
        self.memory.map_bytes(EMPTY, b"\0")
        self.runtime = self.memory.runtime_calls(strlen_target=LEN_TOKEN)
        self.events, self.locals, self.closed = [], [], []
        self.effects, self.unavailable = {}, set()
        self.on_read = self.on_write = None
        self.context = ReplayTaskRebuildStorage(self.subject, self.read, self.write)
        self.calls = ReplayTaskRebuildCalls(self.dispatch)
        self.imports = ReplayTaskRebuildCalls(self.terminal)
        self.support = bind_replay_unit_constructor_support(
            self.context,
            self.calls,
            bind_local=self.bind_local,
            imports=self.imports,
        )
        self.bound = bind_replay_player_research_strings(
            self.context,
            self.calls,
            bind_local=self.bind_local,
            scratch=ReplayPlayerResearchStringsScratch(b"\xa5" * 16, b"\xb6" * 16, b"\xc7" * 8),
            profile=ReplayPlayerResearchStringsProfile(budget),
            imports=self.imports,
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
            self.locals.append((address, len(view)))
            try:
                yield address
            finally:
                self.closed.append((address, bytes(view)))
                assert self.locals.pop() == (address, len(view))

    def dispatch(self, target, args, data):
        self.events.append(("c", target, args))
        if target in self.unavailable:
            raise UnresolvedReplayTaskRebuild(f"authored unavailable {target:x}")
        if target in self.effects:
            return self.effects[target](args)
        if target in ENTRIES:
            return self.invoke(target, *args, data=data)
        if target in SUPPORT:
            assert self.support.call
            return self.support.call(target, args, data)
        assert self.runtime.call
        return self.runtime.call(target, args, data)

    def terminal(self, target, args, data):
        self.events.append(("i", target, args))
        if target in self.effects:
            return self.effects[target](args)
        assert self.runtime.call
        return self.runtime.call(target, args, data)

    def invoke(self, target, *args, data=None):
        assert self.bound.call
        return self.bound.call(target, args, data)

    def string(self, raw):
        address = self.memory.allocate(len(raw) + 1)
        self.memory.write_bytes(address, raw + b"\0")
        return address

    def descriptor(self, pointer, length, capacity):
        for offset, value in ((0, pointer), (8, length), (16, capacity)):
            self.memory.write(self.subject + offset, 8, value)

    def targets(self, target, *, kind="c"):
        return [row[2] for row in self.events if row[0] == kind and row[1] == target]

    def converter(self, encoded):
        def convert(args):
            identifier, buffer, size, radix = args
            assert (size, radix) == (16, 10)
            assert self.locals[-1] == (buffer, 16)
            assert self.memory.read_bytes(buffer, 16) == b"\xa5" * 16
            self.memory.write_bytes(buffer, encoded[identifier])
            return 0xDEADBEEF  # The caller must ignore this result.

        return convert


@pytest.mark.parametrize("identifier", [0xFFFFFFFE, 0x12345678FFFFFFFE, U64 - 1])
def test_only_low_dword_minus_two_bypasses_conversion_and_catalog(identifier):
    f = Fixture(budget=0)
    assert f.invoke(IDENTIFIER, identifier) == EMPTY
    assert f.events == [] and f.closed == []


@pytest.mark.parametrize(
    "identifier,encoded",
    [
        (0, b"0\0"),
        (407089, b"407089\0"),
        (U64, b"-1\0"),
    ],
)
def test_current_conversion_iat_receives_live_seeded_buffer_and_ignores_return(identifier, encoded):
    f = Fixture()
    text = f.string(b"Actual text")
    f.memory.write(ITOA_IAT, 8, CONVERT2)
    f.effects[CONVERT2] = f.converter({identifier & 0xFFFFFFFF: encoded})

    def catalog(args):
        manager, key, output = args
        assert manager == f.manager and f.memory.read(output, 8) == 0
        assert f.memory.read_bytes(key, len(encoded)) == encoded
        assert f.locals[0] == (key, 16) and f.locals[-1] == (output, 8)
        f.memory.write(output, 8, text)
        return 0  # Child AL does not select the wrapper's pointer result.

    f.effects[CATALOG] = catalog
    assert f.invoke(IDENTIFIER, identifier) == text
    assert f.targets(CONVERT2, kind="i")[0][0] == identifier & 0xFFFFFFFF
    assert f.targets(RESOLVE)[0][0] == f.targets(CONVERT2, kind="i")[0][1]
    assert not f.locals and len(f.closed) == 2
    for address, _raw in f.closed:
        with pytest.raises(ReplayMemoryError):
            f.memory.read(address, 1)


def test_conversion_returning_its_buffer_does_not_extend_the_local_lifetime():
    f = Fixture()
    f.effects[CONVERT] = f.converter({1: b"1\0"})
    f.effects[RESOLVE] = lambda args: args[0]
    returned = f.invoke(IDENTIFIER, 1)
    assert returned == f.closed[-1][0]
    with pytest.raises(ReplayMemoryError):
        f.memory.read(returned, 1)


@pytest.mark.parametrize("manager,flag,expected", [(0, None, 0), (1, 0, 0), (1, 1, 1), (1, 255, 1)])
def test_real_global_predicate_and_getter_read_current_backing(manager, flag, expected):
    f = Fixture()
    address = f.manager if manager else 0
    f.memory.write(GLOBAL, 8, address)
    if flag is not None:
        f.memory.write(f.manager + 0x239, 1, flag)
    assert f.invoke(ACTIVE, 0xBAD) == expected
    assert f.invoke(ACTIVE) == expected
    assert f.invoke(MANAGER) == address
    reads = [(row[1], row[2]) for row in f.events if row[0] == "r"]
    assert reads == (
        [(GLOBAL, 8), (f.manager + 0x239, 1)] * 2 + [(GLOBAL, 8)] if manager else [(GLOBAL, 8)] * 3
    )


def test_predicate_holds_the_sampled_manager_before_its_flag_read():
    f = Fixture()
    other = f.memory.allocate(0x240)
    f.memory.write(other + 0x239, 1, 0)

    def mutate(address, width, value):
        if address == GLOBAL:
            f.memory.write(GLOBAL, 8, other)

    f.on_read = mutate
    assert f.invoke(ACTIVE) == 1
    assert f.invoke(MANAGER) == other


def test_resolver_tests_al_only_and_does_not_examine_key_on_inactive_branch():
    f = Fixture()
    f.effects[ACTIVE] = lambda args: 0x100
    assert f.invoke(RESOLVE, 0xBAD) == EMPTY
    assert f.targets(ACTIVE) == [(0xBAD,)]
    assert not f.targets(MANAGER) and not any(row[0] == "r" for row in f.events)


def test_current_manager_is_fetched_again_after_failed_pointer_lookup():
    f = Fixture()
    key = f.string(b"407089")
    other = f.memory.allocate(0x240)
    f.effects[ACTIVE] = lambda args: 0x101

    def catalog(args):
        assert args[:2] == (f.manager, key)
        f.memory.write(GLOBAL, 8, other)
        return 1  # Output remains zero despite this success-looking AL.

    f.effects[CATALOG] = catalog

    def number(args):
        assert args == (other, key)
        return 0xFFFF000100000000  # EAX is zero, so no numeric recursion.

    f.effects[NUMBER] = number
    assert f.invoke(RESOLVE, key) == EMPTY
    assert len(f.targets(MANAGER)) == 2 and not f.targets(IDENTIFIER)


def test_numeric_fallback_uses_low_eax_and_actual_identifier_special_case():
    f = Fixture()
    key = f.string(b"alias")
    f.effects[CATALOG] = lambda args: None
    f.effects[NUMBER] = lambda args: 0x12345678FFFFFFFE
    assert f.invoke(RESOLVE, key) == EMPTY
    assert f.targets(IDENTIFIER) == [(0xFFFFFFFE,)]
    assert not f.targets(CONVERT, kind="i")


def test_recursive_numeric_resolution_shares_budget_and_next_outer_call_resets_it():
    f = Fixture(budget=1)
    f.effects[CONVERT] = f.converter({1: b"1\0"})
    f.effects[CATALOG] = lambda args: None
    f.effects[NUMBER] = lambda args: 1
    for _ in range(2):
        with pytest.raises(UnresolvedReplayTaskRebuild, match="budget exhausted"):
            f.invoke(IDENTIFIER, 1)
        assert not f.locals
    assert len(f.targets(CONVERT, kind="i")) == 4
    assert len(f.targets(ACTIVE)) == 2
    assert len(f.targets(NUMBER)) == 2
    assert len(f.closed) == 6  # Two conversion windows plus one lookup each time.


def test_direct_lookup_returns_current_home_and_ignores_child_boolean():
    f = Fixture()
    text = f.string(b"known")

    def catalog(args):
        manager, key, output = args
        assert (manager, key) == (0x123, 0x456)
        assert f.memory.read(output, 8) == 0 and f.locals[-1] == (output, 8)
        f.memory.write(output, 8, text)
        return 0

    f.effects[CATALOG] = catalog
    assert f.invoke(LOOKUP, 0x123, 0x456) == text
    assert f.closed[-1][1] == text.to_bytes(8, "little")


@pytest.mark.parametrize("source", [0, EMPTY])
def test_null_old_pointer_skips_undefined_capacity_and_all_descriptor_resets(source):
    f = Fixture()
    f.memory.write(f.subject + 8, 8, 77)
    assert f.invoke(ASSIGN, f.subject, source) == f.subject
    assert f.memory.read(f.subject + 8, 8) == 77
    assert not any(row[0] == "w" for row in f.events)
    assert not f.targets(FREE) and not f.closed
    with pytest.raises(ReplayMemoryError):
        f.memory.read(f.subject + 16, 8)


@pytest.mark.parametrize("capacity", [0, 32])
def test_old_pointer_free_and_reset_order_precede_empty_source_check(capacity):
    f = Fixture()
    old = f.string(b"old")
    f.descriptor(old, 3, capacity)
    assert f.invoke(ASSIGN, f.subject, EMPTY) == f.subject
    writes = [row for row in f.events if row[0] == "w"]
    assert writes == [
        ("w", f.subject, 8, RESET),
        ("w", f.subject + 16, 8, 0),
        ("w", f.subject + 8, 8, 0),
    ]
    assert f.targets(FREE) == ([(old,)] if capacity else [])
    first_byte = next(n for n, row in enumerate(f.events) if row[:3] == ("r", EMPTY, 1))
    assert all(f.events.index(row) < first_byte for row in writes)


def test_source_alias_to_freed_old_string_fails_after_actual_free_and_resets():
    f = Fixture()
    old = f.string(b"old")
    f.descriptor(old, 3, 32)
    with pytest.raises(ReplayMemoryError):
        f.invoke(ASSIGN, f.subject, old)
    assert tuple(f.memory.read(f.subject + offset, 8) for offset in (0, 8, 16)) == (RESET, 0, 0)
    assert f.targets(FREE) == [(old,)] and not f.targets(STRLEN)


def test_real_assignment_uses_existing_strlen_getter_growth_and_current_imports():
    f = Fixture()
    source = f.string(b"Paphos research")
    assert f.invoke(ASSIGN, f.subject, source) == f.subject
    pointer = f.memory.read(f.subject, 8)
    assert f.memory.read_bytes(pointer, 16) == b"Paphos research\0"
    assert f.memory.read(f.subject + 8, 8) == 15
    assert f.memory.read(f.subject + 16, 8) == 16
    assert f.targets(STRLEN) == [(source,)]
    assert f.targets(GROW) == [(f.subject, 16)]
    assert f.targets(COPY) == [(pointer, source, 15)]
    assert f.closed[-1][1] == source.to_bytes(8, "little") + (15).to_bytes(8, "little")


def test_strlen_observes_pointer_store_and_seeded_length_before_actual_getter():
    f = Fixture()
    source = f.string(b"hello")
    changed = f.string(b"other")

    def strlen(args):
        local, width = f.locals[-1]
        assert width == 16 and args == (source,)
        assert f.memory.read(local, 8) == source
        assert f.memory.read_bytes(local + 8, 8) == b"\xb6" * 8
        f.memory.write(local, 8, changed)
        return 3

    f.effects[STRLEN] = strlen

    def stored(address, width, value):
        if f.locals and address == f.locals[-1][0] + 8 and value == 3:
            f.memory.write(address, 8, 5)

    f.on_write = stored
    f.invoke(ASSIGN, f.subject, source)
    pointer = f.memory.read(f.subject, 8)
    assert f.memory.read_bytes(pointer, 6) == b"hello\0"
    assert f.targets(COPY) == [(pointer, source, 5)]
    assert f.closed[-1][1] == changed.to_bytes(8, "little") + (5).to_bytes(8, "little")


def test_copy_and_terminator_use_separate_current_destination_reads():
    f = Fixture()
    source = f.string(b"hello")
    copied, terminated = f.memory.allocate(16), f.memory.allocate(16)
    f.memory.fill(copied, 0xA1, 16)
    f.memory.fill(terminated, 0xB2, 16)

    def grow(args):
        assert args == (f.subject, 6)
        f.memory.write(f.subject, 8, copied)
        f.memory.write(f.subject + 16, 8, 91)
        return 0xBAD

    def copy(args):
        assert args == (copied, source, 5)
        f.memory.move(*args)
        f.memory.write(f.subject, 8, terminated)
        f.memory.write(f.locals[-1][0], 8, 0xBAD)
        f.memory.write(f.locals[-1][0] + 8, 8, 0xBAD)
        return 0xBAD

    f.effects[GROW], f.effects[COPY] = grow, copy
    f.invoke(ASSIGN, f.subject, source)
    assert f.memory.read_bytes(copied, 6) == b"hello\xa1"
    assert f.memory.read_bytes(terminated, 6) == b"\xb2" * 5 + b"\0"
    assert f.memory.read(f.subject + 8, 8) == 5
    assert f.memory.read(f.subject + 16, 8) == 91


def test_zero_strlen_still_calls_actual_getter_then_skips_growth_and_copy():
    f = Fixture()
    source = f.string(b"nonempty")
    f.effects[STRLEN] = lambda args: 0
    assert f.invoke(ASSIGN, f.subject, source) == f.subject
    assert len(f.targets(GETTER)) == 1
    assert not f.targets(GROW) and not f.targets(COPY)


@pytest.mark.parametrize("child", [STRLEN, GETTER, GROW, COPY])
def test_missing_assignment_child_keeps_prior_effects_and_unmaps_local(child):
    f = Fixture()
    old, source = f.string(b"old"), f.string(b"new")
    f.descriptor(old, 3, 32)
    f.unavailable.add(child)
    with pytest.raises(UnresolvedReplayTaskRebuild, match="authored unavailable"):
        f.invoke(ASSIGN, f.subject, source)
    assert f.targets(FREE) == [(old,)] and not f.locals
    if child == COPY:
        assert f.memory.read(f.subject, 8) not in (old, RESET)
        assert f.memory.read(f.subject + 16, 8) == 32
    else:
        assert tuple(f.memory.read(f.subject + offset, 8) for offset in (0, 8, 16)) == (RESET, 0, 0)


def test_missing_conversion_import_preserves_seed_and_unmaps_buffer():
    f = Fixture()
    with pytest.raises(UnresolvedReplayTaskRebuild, match="c00010"):
        f.invoke(IDENTIFIER, 407089)
    assert f.closed[-1][1] == b"\xa5" * 16 and not f.targets(RESOLVE)


def test_free_refusal_precedes_all_resets_source_reads_and_local_binding():
    f = Fixture()
    old, source = f.string(b"old"), f.string(b"new")
    f.descriptor(old, 3, 32)
    f.unavailable.add(FREE)
    with pytest.raises(UnresolvedReplayTaskRebuild, match="authored unavailable"):
        f.invoke(ASSIGN, f.subject, source)
    assert f.events == [
        ("r", f.subject, 8, old),
        ("r", f.subject + 16, 8, 32),
        ("c", FREE, (old,)),
    ]
    assert not f.closed and f.memory.read_bytes(old, 4) == b"old\0"


def test_conversion_iat_equal_to_owned_entry_uses_terminal_without_reinterpretation():
    f = Fixture()
    text = f.string(b"one")
    f.memory.write(ITOA_IAT, 8, IDENTIFIER)
    converter = f.converter({1: b"1\0"})

    def convert(args):
        assert f.events[-1][0] == "i"
        return converter(args)

    def catalog(args):
        f.memory.write(args[2], 8, text)
        return 0

    f.effects[IDENTIFIER], f.effects[CATALOG] = convert, catalog
    assert f.invoke(IDENTIFIER, 1) == text
    assert len(f.targets(IDENTIFIER, kind="i")) == 1
    assert f.targets(IDENTIFIER) == []


def test_missing_catalog_child_leaves_zeroed_output_and_unmaps_home():
    f = Fixture()
    with pytest.raises(UnresolvedReplayTaskRebuild, match="140964b80"):
        f.invoke(LOOKUP, 1, 2)
    assert f.closed == [(f.closed[0][0], bytes(8))] and not f.locals


@pytest.mark.parametrize(
    "target,args",
    [
        (IDENTIFIER, ()),
        (RESOLVE, ()),
        (ASSIGN, (1,)),
        (ACTIVE, (1, 2)),
        (MANAGER, (1,)),
        (LOOKUP, (1,)),
    ],
)
def test_exact_effective_arity_rejects_before_effects(target, args):
    f = Fixture()
    with pytest.raises(ValueError, match="malformed"):
        f.invoke(target, *args)
    assert f.events == []


def test_unknown_target_preserves_delegate_args_data_identity_and_raw_return():
    f = Fixture()
    seen, view = [], memoryview(bytearray(b"abc"))

    def delegate(target, args, data):
        seen.append((target, args, data))
        return 0xABCD

    bound = bind_replay_player_research_strings(
        f.context,
        ReplayTaskRebuildCalls(delegate),
        bind_local=f.bind_local,
        scratch=ReplayPlayerResearchStringsScratch(bytes(16), bytes(16), bytes(8)),
        profile=ReplayPlayerResearchStringsProfile(0),
    )
    assert bound.call and bound.call(0x123, (7,), view) == 0xABCD
    assert seen == [(0x123, (7,), view)] and seen[0][2] is view


@pytest.mark.parametrize("budget", [-1, True, 1.5])
def test_profile_requires_explicit_nonnegative_integer_budget(budget):
    with pytest.raises(ValueError):
        ReplayPlayerResearchStringsProfile(budget)


@pytest.mark.parametrize(
    "seeds",
    [
        (bytes(15), bytes(16), bytes(8)),
        (bytes(16), bytes(15), bytes(8)),
        (bytes(16), bytes(16), bytes(7)),
        (bytearray(16), bytes(16), bytes(8)),
    ],
)
def test_all_source_windows_require_exact_immutable_seed_bytes(seeds):
    with pytest.raises(ValueError):
        ReplayPlayerResearchStringsScratch(*seeds)
