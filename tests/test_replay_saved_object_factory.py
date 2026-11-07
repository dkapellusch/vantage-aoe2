"""Owned source-contract cases with real allocation and Result implementations.

Constructor effects are explicitly isolated except for the recursive first-
refusal case. These tests do not claim a restored object or native execution.
"""

from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from vantage.replay_memory import ReplayMemory, ReplayMemoryError
from vantage.replay_saved_apply import bind_replay_saved_apply
from vantage.replay_saved_object_factory import (
    ReplaySavedObjectFactoryScratch,
    bind_replay_saved_object_factory,
    construct_replay_saved_object_list,
    create_replay_saved_object,
)
from vantage.replay_saved_result import bind_replay_saved_result
from vantage.replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
)
from vantage.replay_unit_ai_construction import bind_replay_unit_ai_construction
from vantage.replay_unit_ai_map import ReplayUnitAIMapAtomics
from vantage.replay_unit_construction import (
    ReplayUnitConstructionFloatingCalls,
    ReplayUnitConstructionScratch,
    bind_replay_unit_construction,
)
from vantage.replay_unit_constructor_support import bind_replay_unit_constructor_support

GENERIC, SPECIAL = 0x1412292A0, 0x14133C030
LIST, UNIT_LIST = 0x141227160, 0x14133BEA0
ALLOC, MEMSET, ARRAY = 0x142D6BA78, 0x142D6E3B7, 0x142D6C268
COPY, CLEAR, ALIAS = 0x1402B9080, 0x1402BD7F0, 0x1402BD890
CASES = (
    (10, 0x350, 0x14122E1B0),
    (20, 0x358, 0x141141760),
    (25, 0x398, 0x14115D4F0),
    (30, 0x420, 0x141206510),
    (40, 0x4A0, 0x141136EC0),
    (50, 0x618, 0x141143C30),
    (60, 0x628, 0x1412015F0),
    (70, 0x828, 0x1412A5D60),
    (80, 0x9F8, 0x14126DAA0),
)
SCRATCH = ReplaySavedObjectFactoryScratch(bytes(range(0xA8)), bytes(range(0xB8)))


def setup(*, constructors=True, tables=True, effect=None, read_effect=None, write_effect=None):
    h = SimpleNamespace()
    h.memory = m = ReplayMemory()
    h.receiver, h.output, h.stream, h.resolver = (m.allocate(n) for n in (8, 48, 8, 8))
    m.write_bytes(h.output, b"O" * 48)
    if tables:
        branches = (
            0x1229324,
            0x122936D,
            0x12293B6,
            0x12293FF,
            0x1229491,
            0x12294D3,
            0x1229448,
            0x1229518,
        )
        selectors = bytearray([7] * 51)
        for tag, selector in ((10, 0), (20, 1), (25, 2), (30, 3), (40, 4), (50, 5), (60, 6)):
            selectors[tag - 10] = selector
        m.map_bytes(0x141229804, b"".join(v.to_bytes(4, "little") for v in branches))
        m.map_bytes(0x141229824, bytes(selectors))
    # Explicit engine import profile; the body still reads its current IAT.
    m.map_bytes(0x143199938, MEMSET.to_bytes(8, "little"))
    m.map_bytes(0x143199DD0, (0x142D6BAB4).to_bytes(8, "little"))
    h.events, h.frames, h.completed, h.constructed, h.accesses = [], [], [], [], []

    def read(address, width):
        value = m.read(address, width)
        h.accesses.append(("read", address, width, value))
        if read_effect:
            replacement = read_effect(h, address, width, value)
            if replacement is not None:
                return replacement
        return value

    def write(address, width, value):
        h.accesses.append(("write", address, width, value))
        m.write(address, width, value)
        if write_effect:
            write_effect(h, address, width, value)

    h.context = ReplayTaskRebuildStorage(h.receiver, read, write)
    h.atomics = ReplayUnitAIMapAtomics(m.compare_exchange_u32, m.fetch_add_u32)

    @contextmanager
    def local(view):
        with m.bind_local(view) as address:
            h.frames.append((address, view))
            try:
                yield address
            finally:
                h.completed.append((address, view.tobytes()))
                h.frames.pop()

    h.bind_local = local
    runtime = m.runtime_calls()

    def terminal(target, args, data):
        h.events.append((target, args, data))
        if effect:
            value = effect(h, target, args, data)
            if value is not NotImplemented:
                return value
        if constructors and target in {row[2] for row in CASES}:
            obj, result, stream, resolver, flag = args
            assert (stream, resolver, flag) == (h.stream, h.resolver, 1)
            # A finite, declared constructor fixture; zeroing/allocation and
            # Result lifetimes still use actual shipping implementations.
            assert m.read_bytes(obj, next(row[1] for row in CASES if row[2] == target)) == (
                bytes(next(row[1] for row in CASES if row[2] == target))
            )
            m.write(obj, 8, target)
            h.constructed.append((target, obj, result))
            return 0xDEADBEEF  # Caller must ignore constructor RAX.
        assert runtime.call
        return runtime.call(target, args, data)

    h.terminal = ReplayTaskRebuildCalls(terminal)
    apply = bind_replay_saved_apply(h.context, h.terminal, atomics=h.atomics)
    result = bind_replay_saved_result(h.context, apply, atomics=h.atomics)
    support = bind_replay_unit_constructor_support(
        h.context, result, bind_local=local, imports=h.terminal
    )
    h.lower = bind_replay_unit_ai_construction(
        h.context, support, bind_local=local, imports=h.terminal
    )
    h.bound = bind_replay_saved_object_factory(
        h.context, h.lower, atomics=h.atomics, bind_local=local, scratch=SCRATCH
    )
    return h


def invoke(h, entry, kind, *, direct=False, calls=None):
    args = (h.receiver, h.output, kind, h.stream, h.resolver)
    if direct:
        return create_replay_saved_object(
            h.context,
            entry,
            *args,
            calls=h.bound if calls is None else calls,
            atomics=h.atomics,
            bind_local=h.bind_local,
            scratch=SCRATCH,
        )
    assert h.bound.call
    return h.bound.call(entry, args, None)


@pytest.mark.parametrize("kind,size,constructor", CASES)
@pytest.mark.parametrize("direct", [False, True])
def test_actual_allocation_zeroing_Result_copy_cleanup_and_selected_constructor(
    kind,
    size,
    constructor,
    direct,
):
    h = setup()
    entry = SPECIAL if kind >= 70 else GENERIC
    assert invoke(h, entry, kind, direct=direct) == h.output
    assert h.memory.read_bytes(h.output, 48) == bytes(41) + b"O" * 7
    assert len(h.constructed) == 1 and h.constructed[0][0] == constructor
    obj = h.constructed[0][1]
    assert h.memory.read(obj, 8) == constructor
    assert h.memory.read_bytes(obj + 8, size - 8) == bytes(size - 8)
    assert not h.frames and len(h.completed) == 1
    frame, data = h.completed[0]
    raw = frame + (0x48 if entry == GENERIC else 0x58)
    assert h.constructed[0][2] == raw
    assert data[0x20:0x28] == b"\1\0\0\0" + bytes(range(0x24, 0x28))
    assert data[0x38:0x40] == obj.to_bytes(8, "little")
    assert data[(raw - frame) + 40] == 1


@pytest.mark.parametrize("kind", [10, 20, 25, 30, 40, 50, 60])
def test_special_fallback_recurses_into_actual_generic_factory(kind):
    h = setup()
    assert invoke(h, SPECIAL, kind) == h.output
    assert len(h.constructed) == 1
    assert len(h.completed) == 2
    assert h.memory.read_bytes(h.output, 48) == bytes(41) + b"O" * 7


@pytest.mark.parametrize("kind", [0, 9, 61, 70, 80, 255, 256, (1 << 64) - 1])
def test_generic_out_of_range_needs_no_table_or_allocation(kind):
    h = setup(tables=False)
    assert invoke(h, GENERIC, kind) == h.output
    assert not h.constructed and not h.events
    assert h.memory.read_bytes(h.output, 48) == bytes(41) + b"O" * 7


@pytest.mark.parametrize("kind", [11, 19, 21, 39, 59])
def test_in_range_default_uses_current_tables_but_no_allocation(kind):
    h = setup()
    assert invoke(h, GENERIC, kind) == h.output
    assert not h.constructed and not h.events
    assert any(event[1] == 0x141229824 + kind - 10 for event in h.accesses)


def test_current_table_redirects_to_an_actual_different_case():
    h = setup()
    h.memory.write(0x141229804, 4, 0x12293FF)
    assert invoke(h, GENERIC, 10) == h.output
    assert h.constructed[0][0] == 0x141206510
    assert (ALLOC, (0x420,), None) in h.events


def test_unknown_current_table_target_refuses_before_allocation():
    h = setup()
    h.memory.write(0x141229804, 4, 0x123456)
    with pytest.raises(UnresolvedReplayTaskRebuild, match="branch140123456"):
        invoke(h, GENERIC, 10)
    assert not h.events and h.memory.read_bytes(h.output, 48) == b"O" * 48


@pytest.mark.parametrize("entry,kind", [(GENERIC, 10), (SPECIAL, 70), (SPECIAL, 80)])
def test_null_allocation_still_performs_normal_Result_path(entry, kind):
    h = setup(effect=lambda h, target, args, data: 0 if target == ALLOC else NotImplemented)
    assert invoke(h, entry, kind) == h.output
    assert len(h.events) == 1 and not h.constructed
    assert h.completed[0][1][0x38:0x40] == bytes(8)


def test_required_constructor_refusal_retains_allocated_zeroed_object_and_unmodified_output():
    h = setup(constructors=False)
    with pytest.raises(UnresolvedReplayTaskRebuild, match="14122e1b0"):
        invoke(h, GENERIC, 10)
    allocation = h.completed[0][1][0x38:0x40]
    obj = int.from_bytes(allocation, "little")
    assert h.memory.read_bytes(obj, 0x350) == bytes(0x350)
    assert h.memory.read_bytes(h.output, 48) == b"O" * 48


@pytest.mark.parametrize("entry,kind", [(GENERIC, 10), (SPECIAL, 70)])
def test_shared_control_has_real_increment_and_both_ordered_releases(entry, kind):
    def effect(h, target, args, data):
        if target in {row[2] for row in CASES}:
            h.memory.write(args[1] + 32, 8, h.control)
            return None
        if target in (0xD01, 0xD02):
            assert h.memory.read_bytes(h.output, 41) == bytes(41)
            return None
        return NotImplemented

    h = setup(effect=effect)
    h.control, table = h.memory.allocate(16), h.memory.allocate(16)
    h.memory.write(h.control, 8, table)
    h.memory.write(h.control + 8, 4, 1)
    h.memory.write(h.control + 12, 4, 1)
    h.memory.write(table, 8, 0xD01)
    h.memory.write(table + 8, 8, 0xD02)
    assert invoke(h, entry, kind) == h.output
    assert h.memory.read(h.control + 8, 4) == 0
    assert h.memory.read(h.control + 12, 4) == 0
    assert [target for target, _, _ in h.events if target in (0xD01, 0xD02)] == [0xD01, 0xD02]


@pytest.mark.parametrize("entry,kind", [(GENERIC, 10), (SPECIAL, 70)])
def test_child_error_refuses_at_metadata_after_raw_processed_before_output_reset(entry, kind):
    def effect(h, target, args, data):
        if target in {row[2] for row in CASES}:
            h.memory.write(args[1] + 24, 8, 123)
            return None
        return NotImplemented

    h = setup(effect=effect)
    with pytest.raises(UnresolvedReplayTaskRebuild, match="metadata/TLS"):
        invoke(h, entry, kind)
    data = h.completed[0][1]
    offset = 0x48 if entry == GENERIC else 0x58
    assert data[offset + 40] == 1
    assert int.from_bytes(data[offset + 48 + 24 : offset + 48 + 32], "little") == 123
    assert h.memory.read_bytes(h.output, 48) == b"O" * 48


@pytest.mark.parametrize("entry", [LIST, UNIT_LIST])
@pytest.mark.parametrize("capacity", [0, 3])
def test_real_list_parent_allocation_preserves_padding_and_uninitialized_backing(entry, capacity):
    h = setup()
    obj = h.memory.allocate(32)
    h.memory.write_bytes(obj, b"Z" * 32)
    assert h.bound.call and h.bound.call(entry, (obj, capacity, 0x123456789), None) == obj
    assert h.memory.read(obj, 8) == (0x1432B3DC0 if entry == LIST else 0x1432BEBB8)
    assert h.memory.read(obj + 0x10, 4) == 0
    assert h.memory.read(obj + 0x14, 4) == capacity
    assert h.memory.read(obj + 0x18, 4) == 0x23456789
    assert h.memory.read_bytes(obj + 0x1C, 4) == b"\0ZZZ"
    backing = h.memory.read(obj + 8, 8)
    if capacity:
        with pytest.raises(ReplayMemoryError, match="undefined"):
            h.memory.read(backing, 8)
    assert (ALLOC, (capacity * 8,), None) in h.events


@pytest.mark.parametrize("capacity", [0x80000000, 0xFFFFFFFF, 0x12345678FFFFFFFF])
def test_negative_low32_capacity_saturates_unsigned_multiply_before_real_allocator(capacity):
    h = setup()
    obj = h.memory.allocate(32)
    h.memory.write_bytes(obj, b"Z" * 32)
    with pytest.raises(MemoryError):
        construct_replay_saved_object_list(h.context, LIST, obj, capacity, 7, calls=h.bound)
    assert (ALLOC, ((1 << 64) - 1,), None) in h.events
    assert h.memory.read_bytes(obj + 8, 12) == b"Z" * 12
    assert h.memory.read(obj + 0x14, 4) == capacity & 0xFFFFFFFF


def test_actual_unit_constructor_parent_chain_reaches_real_first_missing_Base_child():
    h = setup(constructors=False)
    flags = (0xC0, 0xB0, 0xB0, 0xB0, 0xD0, 0xD0)
    constructors = bind_replay_unit_construction(
        h.context,
        h.lower,
        atomics=h.atomics,
        bind_local=h.bind_local,
        scratch=ReplayUnitConstructionScratch(*(bytes(n + 4) for n in flags)),
        floating=ReplayUnitConstructionFloatingCalls(None),
    )
    h.bound = bind_replay_saved_object_factory(
        h.context, constructors, atomics=h.atomics, bind_local=h.bind_local, scratch=SCRATCH
    )
    with pytest.raises(UnresolvedReplayTaskRebuild, match="14122dc70"):
        invoke(h, SPECIAL, 70)
    obj = int.from_bytes(h.completed[-1][1][0x38:0x40], "little")
    assert h.memory.read(obj, 8) == 0x1432B4078
    assert h.memory.read(obj + 8, 4) == 0xFFFFFFFF
    assert h.memory.read_bytes(h.output, 48) == b"O" * 48
    assert len(h.completed) == 7 and not h.frames


@pytest.mark.parametrize(
    "entry,args",
    [(GENERIC, ()), (SPECIAL, (1, 2, 3, 4)), (LIST, (1, 2)), (UNIT_LIST, (1, 2, 3, 4))],
)
def test_known_entry_arity_fails_before_effects(entry, args):
    h = setup()
    assert h.bound.call
    with pytest.raises(ValueError, match="malformed"):
        h.bound.call(entry, args, None)
    assert not h.events and not h.accesses


def test_unknown_call_delegates_or_refuses_and_known_entry_rejects_data():
    h = setup(effect=lambda h, target, args, data: 123 if target == 0xABCD else NotImplemented)
    view = memoryview(bytearray(3))
    assert h.bound.call and h.bound.call(0xABCD, (1, 2), view) == 123
    assert h.events == [(0xABCD, (1, 2), view)]
    with pytest.raises(ValueError, match="malformed"):
        h.bound.call(LIST, (1, 2, 3), view)
    missing = bind_replay_saved_object_factory(
        h.context,
        ReplayTaskRebuildCalls(None),
        atomics=h.atomics,
        bind_local=h.bind_local,
        scratch=SCRATCH,
    )
    assert missing.call
    with pytest.raises(UnresolvedReplayTaskRebuild, match="unavailable"):
        missing.call(0xABCD, (), None)
