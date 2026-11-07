"""Authored caller-contract controls; opaque fixtures are not registry implementations."""

from __future__ import annotations

from contextlib import contextmanager

import pytest

from vantage.replay_player_civilization_lookup import (
    bind_replay_player_civilization_lookup,
    clear_replay_player_de_string,
    equal_replay_player_de_strings,
    lookup_replay_player_civilization,
)
from vantage.replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
)

U64 = (1 << 64) - 1
DESCRIPTOR, SELECTOR, NAME_INDEX, RESOURCE, EQUAL = (
    0x140FA3420,
    0x140FA36A0,
    0x140F6A690,
    0x140F6A320,
    0x140A15CA0,
)
FREE, MEMCMP = 0x142D6C270, 0x142D6E3BD


class Scalar:
    def __init__(self):
        self.data = {}
        self.views = {}
        self.next = 0x10000
        self.events = []
        self.exited = []
        self.read_hook = None
        self.denied = set()

    def put(self, address, value, width=8):
        for index, byte in enumerate((value & ((1 << (width * 8)) - 1)).to_bytes(width, "little")):
            self.data[(address + index) & U64] = byte

    def byte(self, address):
        for base, view in self.views.items():
            if base <= address < base + len(view):
                return view[address - base]
        return self.data[address]

    def read(self, address, width):
        raw = bytes(self.byte((address + i) & U64) for i in range(width))
        value = int.from_bytes(raw, "little")
        self.events.append(("read", address, width, value))
        if self.read_hook:
            self.read_hook(address, width, value)
        return value

    def write(self, address, width, value):
        if address in self.denied:
            raise PermissionError(address)
        raw = (value & ((1 << (width * 8)) - 1)).to_bytes(width, "little")
        for index, byte in enumerate(raw):
            current = (address + index) & U64
            for base, view in self.views.items():
                if base <= current < base + len(view):
                    view[current - base] = byte
                    break
            else:
                if current not in self.data:
                    raise KeyError(current)
                self.data[current] = byte
        self.events.append(("write", address, width, value))

    @contextmanager
    def bind(self, view):
        address = self.next
        self.next += 0x100
        self.views[address] = view
        try:
            yield address
        finally:
            self.exited.append((address, bytes(view)))
            del self.views[address]

    def context(self):
        return ReplayTaskRebuildStorage(0x100, self.read, self.write)


class Effects:
    """Declared per-test raw returns/effects, never installed as engine defaults."""

    def __init__(self):
        self.providers = {}
        self.trace = []

    def dispatch(self, target, args, data):
        self.trace.append((target, args, data))
        if target not in self.providers:
            raise UnresolvedReplayTaskRebuild(f"explicit unbound{target:x}")
        return self.providers[target](args)

    def calls(self):
        return ReplayTaskRebuildCalls(self.dispatch)


def plan(memory, effects, *, selector=2, index=1, resource=0x4000, equality=1):
    def descriptor(args):
        memory.write(args[0], 4, 2)
        memory.write(args[0] + 4, 1, 0)
        return args[0]

    effects.providers.update(
        {
            DESCRIPTOR: descriptor,
            SELECTOR: lambda _a: selector,
            NAME_INDEX: lambda _a: index,
            RESOURCE: lambda _a: resource,
            EQUAL: lambda _a: equality,
        }
    )


def lookup(memory, effects, name=0x1234, scratch=bytes([0xA5]) * 8):
    return lookup_replay_player_civilization(
        memory.context(), name, calls=effects.calls(), bind_local=memory.bind, scratch=scratch
    )


@pytest.mark.parametrize("index", [1, 7, 0xFFFFFFFF])
@pytest.mark.parametrize("resource", [0, 0x8000])
def test_nonzero_index_returns_held_resource_without_name_equality(index, resource):
    memory, effects = Scalar(), Effects()
    plan(memory, effects, selector=0xFFFFFFFF, index=index, resource=resource)
    assert lookup(memory, effects) == resource
    assert [(target, args) for target, args, _ in effects.trace] == [
        (DESCRIPTOR, (0x10000,)),
        (SELECTOR, (0x10000,)),
        (NAME_INDEX, (0x1234, 0xFFFFFFFF)),
        (RESOURCE, (index, 0xFFFFFFFF)),
    ]
    assert memory.exited == [(0x10000, b"\x02\0\0\0\0\xa5\xa5\xa5")]


def test_zero_index_null_resource_returns_zero_without_equality():
    memory, effects = Scalar(), Effects()
    plan(memory, effects, index=0, resource=0)
    assert lookup(memory, effects) == 0
    assert [t for t, _, _ in effects.trace] == [DESCRIPTOR, SELECTOR, NAME_INDEX, RESOURCE]


@pytest.mark.parametrize("equality", [0, 1])
def test_zero_index_nonnull_resource_requires_equality_and_returns_held_pointer(equality):
    memory, effects = Scalar(), Effects()
    plan(memory, effects, index=0, resource=0x5000, equality=equality)

    def compare(args):
        assert args == (0x5058, 0x1234)
        assert memory.read(0x10000, 4) == 2  # Home stays live through the last call.
        effects.providers[RESOURCE] = lambda _a: 0xDEAD
        return equality

    effects.providers[EQUAL] = compare
    assert lookup(memory, effects) == (0x5000 if equality else 0)
    assert [target for target, _, _ in effects.trace].count(RESOURCE) == 1
    assert not memory.views


def test_actual_descriptor_return_pointer_not_fixed_home_reaches_selector():
    memory, effects = Scalar(), Effects()
    plan(memory, effects, resource=0)
    memory.put(0x2000, 9, 4)
    seen = []

    def descriptor(args):
        seen.append(args[0])
        memory.write(args[0], 4, 77)
        return 0x2000

    def selector(args):
        assert args == (0x2000,)
        return memory.read(args[0], 4)

    effects.providers[DESCRIPTOR], effects.providers[SELECTOR] = descriptor, selector
    assert lookup(memory, effects) == 0
    assert effects.trace[2][1] == (0x1234, 9)
    assert seen == [0x10000]


def test_selector_is_held_across_name_search_mutation_of_live_home():
    memory, effects = Scalar(), Effects()
    plan(memory, effects, selector=3, index=99, resource=0)

    def index(args):
        assert args == (0x1234, 3)
        memory.write(0x10000, 4, 0xFFFFFFFF)
        return 99

    effects.providers[NAME_INDEX] = index
    lookup(memory, effects)
    assert effects.trace[-1][1] == (99, 3)


def test_resource_string_pointer_addition_wraps_u64():
    memory, effects = Scalar(), Effects()
    resource = U64 - 0x4F
    plan(memory, effects, index=0, resource=resource)
    assert lookup(memory, effects) == resource
    assert effects.trace[-1][1] == (8, 0x1234)


@pytest.mark.parametrize("target", [DESCRIPTOR, SELECTOR, NAME_INDEX, RESOURCE])
def test_each_missing_opaque_child_refuses_at_reach_with_prior_home_effects(target):
    memory, effects = Scalar(), Effects()
    plan(memory, effects)
    del effects.providers[target]
    with pytest.raises(UnresolvedReplayTaskRebuild, match=f"{target:x}"):
        lookup(memory, effects)
    assert effects.trace[-1][0] == target
    final = memory.exited[0][1]
    assert final == (bytes([0xA5]) * 8 if target == DESCRIPTOR else b"\x02\0\0\0\0\xa5\xa5\xa5")
    assert not memory.views


@pytest.mark.parametrize(
    "target,value",
    [(DESCRIPTOR, None), (SELECTOR, 1 << 32), (NAME_INDEX, -1), (RESOURCE, 1 << 64), (EQUAL, 256)],
)
def test_raw_child_result_widths_refuse_without_later_calls(target, value):
    memory, effects = Scalar(), Effects()
    plan(memory, effects, index=0)
    effects.providers[target] = lambda _args: value
    with pytest.raises(ValueError, match=r"return|scalar"):
        lookup(memory, effects)
    assert effects.trace[-1][0] == target
    assert not memory.views


@pytest.mark.parametrize("scratch", [b"", bytes(7), bytes(9), bytearray(8)])
def test_lookup_requires_exact_explicit_descriptor_seed_before_effects(scratch):
    memory, effects = Scalar(), Effects()
    with pytest.raises(ValueError, match="8B"):
        lookup(memory, effects, scratch=scratch)
    assert not effects.trace and not memory.exited


def test_bound_lookup_has_no_implicit_global_or_empty_name_success():
    memory = Scalar()
    bound = bind_replay_player_civilization_lookup(
        memory.context(), ReplayTaskRebuildCalls(None), bind_local=memory.bind, scratch=bytes(8)
    )
    with pytest.raises(UnresolvedReplayTaskRebuild, match="140fa3420"):
        bound.call(0x140F6A4B0, (0,), None)
    assert memory.exited == [(0x10000, bytes(8))]


def test_cleanup_null_pointer_reads_no_other_fields_or_providers():
    memory = Scalar()
    memory.put(0x100, 0)
    assert (
        clear_replay_player_de_string(memory.context(), 0x100, calls=ReplayTaskRebuildCalls(None))
        is None
    )
    assert memory.events == [("read", 0x100, 8, 0)]


@pytest.mark.parametrize("capacity", [0, 1, 15, U64])
def test_cleanup_free_gate_and_exact_pointer_capacity_length_store_order(capacity):
    memory, effects = Scalar(), Effects()
    memory.put(0x100, 0x200)
    memory.put(0x108, 77)
    memory.put(0x110, capacity)
    memory.put(0x200, 0xABC)

    def free(args):
        assert args == (0x200,)
        for address in range(0x200, 0x208):
            del memory.data[address]
        memory.put(0x100, 0xDEAD)
        memory.put(0x108, 123)
        memory.put(0x110, 456)

    effects.providers[FREE] = free
    assert clear_replay_player_de_string(memory.context(), 0x100, calls=effects.calls()) is None
    assert [event[:3] for event in memory.events] == [
        ("read", 0x100, 8),
        ("read", 0x110, 8),
        ("write", 0x100, 8),
        ("write", 0x110, 8),
        ("write", 0x108, 8),
    ]
    assert memory.read(0x100, 8) == 0x14428BB30
    assert memory.read(0x108, 8) == memory.read(0x110, 8) == 0
    assert len(effects.trace) == int(capacity != 0)


def test_cleanup_holds_pointer_before_current_capacity_read():
    memory, effects = Scalar(), Effects()
    memory.put(0x100, 0x200)
    memory.put(0x108, 9)
    memory.put(0x110, 0)

    def changed(address, _width, _value):
        if address == 0x100:
            memory.put(0x100, 0x300)
            memory.put(0x110, 1)

    memory.read_hook = changed
    effects.providers[FREE] = lambda args: memory.put(args[0], 0xFEEF)
    clear_replay_player_de_string(memory.context(), 0x100, calls=effects.calls())
    assert effects.trace == [(FREE, (0x200,), None)]


@pytest.mark.parametrize("failure", ["free", "capacity-write"])
def test_cleanup_failure_preserves_exact_prior_effects(failure):
    memory, effects = Scalar(), Effects()
    memory.put(0x100, 0x200)
    memory.put(0x108, 9)
    memory.put(0x110, 0 if failure == "capacity-write" else 1)
    if failure == "capacity-write":
        memory.denied.add(0x110)
    with pytest.raises((PermissionError, UnresolvedReplayTaskRebuild)):
        clear_replay_player_de_string(memory.context(), 0x100, calls=effects.calls())
    assert memory.read(0x100, 8) == (0x14428BB30 if failure == "capacity-write" else 0x200)
    assert memory.read(0x108, 8) == 9


@pytest.mark.parametrize("left,right", [(0, 1), (1, 0), (1, 2), (U64, 0)])
def test_equality_unequal_lengths_skip_both_data_pointers(left, right):
    memory = Scalar()
    memory.put(0x108, left)
    memory.put(0x208, right)
    assert (
        equal_replay_player_de_strings(
            memory.context(), 0x100, 0x200, calls=ReplayTaskRebuildCalls(None)
        )
        == 0
    )
    assert [event[1] for event in memory.events] == [0x108, 0x208]


def test_equality_zero_lengths_shortcut_without_reading_absent_pointers():
    memory = Scalar()
    memory.put(0x108, 0)
    memory.put(0x208, 0)
    assert (
        equal_replay_player_de_strings(
            memory.context(), 0x100, 0x200, calls=ReplayTaskRebuildCalls(None)
        )
        == 1
    )
    assert len(memory.events) == 2


@pytest.mark.parametrize("eax", [0, 1, 0xFFFFFFFF, 0x80000000])
def test_equality_reads_right_pointer_then_current_left_and_holds_length(eax):
    memory, effects = Scalar(), Effects()
    for address, value in ((0x100, 0x1000), (0x108, 3), (0x200, 0x2000), (0x208, 3)):
        memory.put(address, value)

    def changed(address, _width, _value):
        if address == 0x208:
            memory.put(0x108, 99)
        if address == 0x200:
            memory.put(0x100, 0x3000)

    memory.read_hook = changed
    effects.providers[MEMCMP] = lambda _args: eax
    assert equal_replay_player_de_strings(
        memory.context(), 0x100, 0x200, calls=effects.calls()
    ) == int(eax == 0)
    assert effects.trace == [(MEMCMP, (0x3000, 0x2000, 3), None)]
    assert [event[1] for event in memory.events] == [0x108, 0x208, 0x200, 0x100]


def test_equality_self_alias_still_performs_both_reads_and_actual_memcmp():
    memory, effects = Scalar(), Effects()
    memory.put(0x100, 0x1000)
    memory.put(0x108, 2)
    effects.providers[MEMCMP] = lambda _args: 0
    assert (
        equal_replay_player_de_strings(memory.context(), 0x100, 0x100, calls=effects.calls()) == 1
    )
    assert [event[1] for event in memory.events] == [0x108, 0x108, 0x100, 0x100]
    assert effects.trace == [(MEMCMP, (0x1000, 0x1000, 2), None)]


def test_bound_lookup_zero_index_reaches_actual_equality_then_unbound_memcmp():
    memory, effects = Scalar(), Effects()
    plan(memory, effects, index=0, resource=0x4000)
    del effects.providers[EQUAL]
    for address, value in ((0x100, 0x1000), (0x108, 2), (0x4058, 0x2000), (0x4060, 2)):
        memory.put(address, value)
    bound = bind_replay_player_civilization_lookup(
        memory.context(), effects.calls(), bind_local=memory.bind, scratch=bytes(8)
    )
    with pytest.raises(UnresolvedReplayTaskRebuild, match="142d6e3bd"):
        bound.call(0x140F6A4B0, (0x100,), None)
    assert effects.trace[-1] == (MEMCMP, (0x2000, 0x1000, 2), None)
    assert not memory.views


@pytest.mark.parametrize("target,arity", [(0x140F6A4B0, 1), (0x140A1B220, 1), (EQUAL, 2)])
def test_binder_arity_data_and_unknown_delegation(target, arity):
    memory, effects = Scalar(), Effects()
    bound = bind_replay_player_civilization_lookup(
        memory.context(), effects.calls(), bind_local=memory.bind, scratch=bytes(8)
    )
    with pytest.raises(ValueError, match="malformed"):
        bound.call(target, (0,) * (arity + 1), None)
    with pytest.raises(ValueError, match="malformed"):
        bound.call(target, (0,) * arity, memoryview(b"x"))
    with pytest.raises(UnresolvedReplayTaskRebuild, match="dead"):
        bound.call(0xDEAD, (7,), None)


@pytest.mark.parametrize("entry", ["cleanup", "equality"])
def test_unknown_current_field_refuses_at_first_reached_read(entry):
    memory, effects = Scalar(), Effects()
    if entry == "cleanup":
        memory.put(0x100, 0x200)
        with pytest.raises(KeyError) as error:
            clear_replay_player_de_string(memory.context(), 0x100, calls=effects.calls())
        assert error.value.args == (0x110,)
    else:
        memory.put(0x108, 1)
        memory.put(0x208, 1)
        with pytest.raises(KeyError) as error:
            equal_replay_player_de_strings(memory.context(), 0x100, 0x200, calls=effects.calls())
        assert error.value.args == (0x200,)
    assert not effects.trace
