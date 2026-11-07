"""Owned controls for193 original source bytes, without native execution."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from vantage.replay_action_saved import (
    ReplayActionSavedScratch,
    bind_replay_action_saved,
)
from vantage.replay_behavior_factory import (
    bind_replay_behavior_factory,
    construct_replay_behavior_manager,
    create_replay_behavior_manager,
)
from vantage.replay_memory import ReplayMemory, ReplayMemoryError
from vantage.replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
)

ACTION, UNIT, BASE_CTOR, UNIT_CTOR = 0x14113B370, 0x1412C5A30, 0x140B875A0, 0x140BB6EC0
ALLOC = 0x142D6BA78


def setup(*, effect=None, write_effect=None):
    memory = ReplayMemory()
    subject = memory.allocate(8)
    events = []

    def write(pointer, width, value):
        memory.write(pointer, width, value)
        events.append(("write", pointer, width, value))
        if write_effect:
            write_effect(memory, pointer, width, value)

    context = ReplayTaskRebuildStorage(subject, memory.read, write)
    runtime = memory.runtime_calls()

    def call(target, args, data):
        events.append(("call", target, args, data))
        if effect:
            result = effect(memory, target, args, data)
            if result is not None:
                return result
        assert runtime.call
        return runtime.call(target, args, data)

    calls = ReplayTaskRebuildCalls(call)
    return memory, context, calls, bind_replay_behavior_factory(context, calls), events


@pytest.mark.parametrize("entry,table", [(ACTION, 0x143226988), (UNIT, 0x1432284C8)])
@pytest.mark.parametrize("direct", [True, False])
def test_complete_factory_and_real_constructor_chain(entry, table, direct):
    m, c, _, bound, events = setup()
    assert bound.call
    pointer = (
        create_replay_behavior_manager(c, entry, c.subject, calls=bound)
        if direct
        else (bound.call(entry, (c.subject,), None))
    )
    assert pointer is not None
    assert m.read_bytes(pointer, 24) == (
        table.to_bytes(8, "little") + c.subject.to_bytes(8, "little") + bytes(8)
    )
    writes = [event for event in events if event[0] == "write"]
    assert writes[:2] == [("write", pointer, 16, 0), ("write", pointer + 16, 8, 0)]
    assert writes[2:5] == [
        ("write", pointer + 8, 8, c.subject),
        ("write", pointer, 8, 0x143226988),
        ("write", pointer + 16, 8, 0),
    ]
    if entry == UNIT:
        assert writes[5:] == [("write", pointer, 8, 0x1432284C8)]


@pytest.mark.parametrize("entry", [ACTION, UNIT])
def test_explicit_allocation_zero_skips_stores_and_child(entry):
    m, c, _, bound, events = setup(effect=lambda m, target, args, data: 0)
    assert bound.call and bound.call(entry, (c.subject,), None) == 0
    assert events == [("call", ALLOC, (24,), None)]
    assert m.snapshot().regions[0].defined == bytes(8)


@pytest.mark.parametrize("entry", [ACTION, UNIT])
def test_missing_allocator_refuses_without_success(entry):
    m, c, _, _, events = setup()
    with pytest.raises(UnresolvedReplayTaskRebuild, match="unavailable"):
        create_replay_behavior_manager(c, entry, c.subject, calls=ReplayTaskRebuildCalls(None))
    assert events == [] and len(m.snapshot().regions) == 1


@pytest.mark.parametrize("entry,child", [(ACTION, BASE_CTOR), (UNIT, UNIT_CTOR)])
def test_direct_factory_requires_actual_constructor_after_complete_zeroing(entry, child):
    m, c, calls, _, events = setup()
    with pytest.raises(UnresolvedReplayTaskRebuild, match=f"reached{child:x}"):
        create_replay_behavior_manager(c, entry, c.subject, calls=calls)
    allocated = events[0]
    assert allocated == ("call", ALLOC, (24,), None)
    pointer = next(event[1] for event in events if event[0] == "write")
    assert m.read_bytes(pointer, 24) == bytes(24)
    assert events[-1] == ("call", child, (pointer, c.subject), None)


@pytest.mark.parametrize("entry", [BASE_CTOR, UNIT_CTOR])
def test_direct_constructor_store_order_and_held_this(entry):
    m, c, _, bound, events = setup()
    pointer = m.allocate(24)
    m.write_bytes(pointer, b"Z" * 24)
    assert construct_replay_behavior_manager(c, entry, pointer, c.subject, calls=bound) == pointer
    expected = [
        ("write", pointer + 8, 8, c.subject),
        ("write", pointer, 8, 0x143226988),
        ("write", pointer + 16, 8, 0),
    ]
    if entry == UNIT_CTOR:
        expected.append(("write", pointer, 8, 0x1432284C8))
    assert [e for e in events if e[0] == "write"] == expected


def test_base_constructor_failed_vptr_store_retains_prior_owner_only():
    m, c, _, bound, _ = setup()
    pointer = m.allocate(24)
    m.write_bytes(pointer, b"Z" * 24)

    def write(address, width, value):
        if address == pointer:
            raise RuntimeError("current writer failure")
        m.write(address, width, value)

    failing = ReplayTaskRebuildStorage(c.subject, m.read, write)
    with pytest.raises(RuntimeError, match="writer failure"):
        construct_replay_behavior_manager(failing, BASE_CTOR, pointer, c.subject, calls=bound)
    assert m.read_bytes(pointer, 8) == b"Z" * 8
    assert m.read(pointer + 8, 8) == c.subject
    assert m.read_bytes(pointer + 16, 8) == b"Z" * 8


def test_factory_second_zero_failure_retains_first_zero_and_definedness():
    m, c, calls, _, events = setup()

    def write(address, width, value):
        if width == 8:
            raise RuntimeError("tail zero writer unavailable")
        m.write(address, width, value)

    failing = ReplayTaskRebuildStorage(c.subject, m.read, write)
    with pytest.raises(RuntimeError, match="tail zero"):
        create_replay_behavior_manager(failing, ACTION, c.subject, calls=calls)
    assert events[0] == ("call", ALLOC, (24,), None)
    region = m.snapshot().regions[-1]
    assert region.defined == b"\x01" * 16 + bytes(8)
    with pytest.raises(ReplayMemoryError, match="undefined"):
        m.read(region.address + 16, 8)


def test_unit_constructor_missing_base_does_not_apply_override():
    m, c, calls, _, events = setup()
    pointer = m.allocate(24)
    m.write_bytes(pointer, b"Z" * 24)
    with pytest.raises(UnresolvedReplayTaskRebuild, match=f"reached{BASE_CTOR:x}"):
        construct_replay_behavior_manager(c, UNIT_CTOR, pointer, c.subject, calls=calls)
    assert m.read_bytes(pointer, 24) == b"Z" * 24
    assert events == [("call", BASE_CTOR, (pointer, c.subject), None)]


@pytest.mark.parametrize(
    "entry,args",
    [
        (ACTION, ()),
        (ACTION, (1, 2)),
        (UNIT, ()),
        (UNIT, (1, 2)),
        (BASE_CTOR, (1,)),
        (BASE_CTOR, (1, 2, 3)),
        (UNIT_CTOR, (1,)),
        (UNIT_CTOR, ()),
    ],
)
def test_bound_arity_refuses_before_effects(entry, args):
    _, _, _, bound, events = setup()
    assert bound.call
    with pytest.raises(ValueError, match="malformed behavior"):
        bound.call(entry, args, None)
    assert events == []


@pytest.mark.parametrize("entry,args", [(ACTION, (1,)), (BASE_CTOR, (1, 2))])
def test_known_entries_reject_data_view(entry, args):
    _, _, _, bound, events = setup()
    assert bound.call
    with pytest.raises(ValueError, match="malformed behavior"):
        bound.call(entry, args, memoryview(bytearray(1)))
    assert events == []


def test_unknown_target_delegates_exactly_or_refuses():
    m = ReplayMemory()
    c = ReplayTaskRebuildStorage(1, m.read, m.write)
    seen = []

    def call(target, args, data):
        seen.append((target, args, data))
        return 123

    view = memoryview(bytearray(3))
    bound = bind_replay_behavior_factory(c, ReplayTaskRebuildCalls(call))
    assert bound.call and bound.call(0xABCD, (1, 2, 3), view) == 123
    assert seen == [(0xABCD, (1, 2, 3), view)]
    missing = bind_replay_behavior_factory(c, ReplayTaskRebuildCalls(None))
    assert missing.call
    with pytest.raises(UnresolvedReplayTaskRebuild, match="unavailable"):
        missing.call(0xABCD, (), None)


@pytest.mark.parametrize("entry", [0, 0xFFFFFFFFFFFFFFFF])
def test_unsupported_direct_entries_are_not_silent_aliases(entry):
    _, c, calls, _, events = setup()
    with pytest.raises(ValueError, match="unsupported behavior"):
        create_replay_behavior_manager(c, entry, c.subject, calls=calls)
    with pytest.raises(ValueError, match="unsupported behavior"):
        construct_replay_behavior_manager(c, entry, 123, c.subject, calls=calls)
    assert events == []


@pytest.mark.parametrize(
    "table,factory,manager_table",
    [
        (0x1432A5708, ACTION, 0x143226988),
        (0x1432A70D0, ACTION, 0x143226988),
        (0x1432B8270, UNIT, 0x1432284C8),
    ],
)
def test_real_current_factory_action_reader_map_list_and_owned_input(
    table,
    factory,
    manager_table,
):
    # Reuse the frozen79-case harness as a fixture provider, not its tests.
    # Only Moving remains isolated; its manager-selection engine tokens below
    # are never reached because the current slot names the actual native body.
    path = Path(__file__).with_name("test_replay_action_saved.py")
    spec = importlib.util.spec_from_file_location("frozen_action_fixture", path)
    assert spec and spec.loader
    fixture = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixture)
    h = fixture.setup(fixture.wire_plan(count=2, pairs=((7, 11), (7, 22))))
    h.memory.map_bytes(table + 0x8F8, factory.to_bytes(8, "little"), writable=False)
    h.memory.write(h.obj, 8, table)
    factories = bind_replay_behavior_factory(h.context, h.calls)
    bound = bind_replay_action_saved(
        h.context,
        factories,
        atomics=h.atomics,
        bind_local=h.bind_local,
        scratch=ReplayActionSavedScratch(bytes(range(0xB0))),
    )
    assert bound.call and bound.call(0x14113E920, (h.obj, h.out, h.stream, h.opaque), None) == h.out
    manager = h.memory.read(h.obj + 0x420, 8)
    assert manager != h.manager
    assert h.memory.read_bytes(manager, 24) == (
        manager_table.to_bytes(8, "little") + h.obj.to_bytes(8, "little") + bytes(8)
    )
    assert fixture.map_items(h) == {7: 22}
    assert h.source.remaining == 0
    assert h.memory.read_bytes(h.out, 48) == bytes(41) + b"O" * 7
    assert not any(target in (fixture.FACTORY, fixture.FACTORY2) for target, _, _ in h.events)
    assert sum(target == fixture.PARENT for target, _, _ in h.events) == 1
