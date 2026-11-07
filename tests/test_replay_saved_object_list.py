"""Actual Input/Result/list/factory compositions with explicit constructor fixtures."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from vantage.replay_memory import ReplayMemoryError
from vantage.replay_saved_input import ReplaySavedInput, bind_replay_saved_input
from vantage.replay_saved_object_list import (
    ReplaySavedObjectListScratch,
    bind_replay_saved_object_list,
    read_replay_saved_object_list,
)
from vantage.replay_task_rebuild import ReplayTaskRebuildCalls, UnresolvedReplayTaskRebuild

ENTRY, GENERIC, SPECIAL = 0x14122B360, 0x1412292A0, 0x14133C030
VERSION, INPUT, INPUT2 = 0x1440A0D94, 0xE01, 0xE02
SCRATCH = ReplaySavedObjectListScratch(bytes(range(0xB0)))


def setup(
    wire, *, version=0x44E666, result=bytes(48), effect=None, read_effect=None, write_effect=None
):
    # Reuse the allocation/Result fixture provider, not its tests or outcomes.
    # Object constructors remain explicitly isolated; the factory and list
    # bodies, Input cursor, Result copy/release and runtime effects are real.
    path = Path(__file__).with_name("test_replay_saved_object_factory.py")
    spec = importlib.util.spec_from_file_location("saved_object_factory_fixture", path)
    assert spec and spec.loader
    fixture = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixture)
    h = fixture.setup(effect=effect, read_effect=read_effect, write_effect=write_effect)
    m = h.memory
    h.address = m.allocate(32)
    m.write_bytes(h.address, b"Z" * 32)
    m.map_bytes(VERSION, version.to_bytes(4, "little"))
    m.map_bytes(0x1432BEBB8, SPECIAL.to_bytes(8, "little"))
    m.map_bytes(0x1432B3DC0, GENERIC.to_bytes(8, "little"))
    assert h.bound.call and h.bound.call(0x14133BEA0, (h.address, 2, 1), None) == h.address
    h.old_array = m.read(h.address + 8, 8)
    m.write_bytes(h.old_array, b"old list backing")
    h.table, h.table2 = m.allocate(32), m.allocate(32)
    m.write(h.stream, 8, h.table)
    m.write(h.table + 24, 8, INPUT)
    m.write(h.table2 + 24, 8, INPUT2)
    h.source = ReplaySavedInput(wire)
    calls = bind_replay_saved_input(
        h.context, h.bound, h.source, stream=h.stream, target=INPUT, result_bytes=result
    )
    h.calls = bind_replay_saved_input(
        h.context, calls, h.source, stream=h.stream, target=INPUT2, result_bytes=result
    )
    h.reader = bind_replay_saved_object_list(
        h.context, h.calls, atomics=h.atomics, bind_local=h.bind_local, scratch=SCRATCH
    )
    h.events.clear()
    h.accesses.clear()
    h.completed.clear()
    return h


def invoke(h, *, direct=False):
    args = (h.address, h.output, h.stream, h.resolver)
    if direct:
        return read_replay_saved_object_list(
            h.context,
            *args,
            calls=h.calls,
            atomics=h.atomics,
            bind_local=h.bind_local,
            scratch=SCRATCH,
        )
    assert h.reader.call
    return h.reader.call(ENTRY, args, None)


def modern(tags, *, capacity=4, growth=7):
    return capacity.to_bytes(4, "little") + growth.to_bytes(4, "little") + bytes(tags)


@pytest.mark.parametrize("direct", [False, True])
@pytest.mark.parametrize(
    "tags",
    [
        (0,),
        (10, 0),
        (70, 80, 0),
        (10, 20, 25, 30, 40, 50, 60, 70, 80, 0),
    ],
)
def test_actual_tagged_Input_allocation_Results_and_factories(direct, tags):
    wire = modern(tags) + b"N"
    h = setup(wire)
    assert invoke(h, direct=direct) == h.output
    assert h.source.remaining == 1 and h.source.position == len(wire) - 1
    assert h.memory.read_bytes(h.output, 48) == bytes(41) + b"O" * 7
    assert h.memory.read(h.address + 0x14, 4) == 4
    assert h.memory.read(h.address + 0x18, 4) == 7
    assert h.memory.read(h.address + 0x10, 4) == 0  # Publication is isolated with constructors.
    assert len(h.constructed) == len(tags) - 1
    assert not h.frames
    with pytest.raises(ReplayMemoryError, match="unmapped"):
        h.memory.read(h.old_array, 1)
    backing = h.memory.read(h.address + 8, 8)
    with pytest.raises(ReplayMemoryError, match="undefined"):
        h.memory.read(backing, 1)


@pytest.mark.parametrize("version", [0, 0xAFAE0, 0x80000000, 0xFFFFFFFF])
def test_signed_legacy_gate_preserves_old_array_capacity_growth_and_flag(version):
    h = setup(b"\0N", version=version)
    h.memory.write(h.address + 0x10, 4, 123)
    h.memory.write(h.address + 0x1C, 1, 99)
    assert invoke(h) == h.output and h.source.position == 1
    assert h.memory.read(h.address + 8, 8) == h.old_array
    assert h.memory.read(h.address + 0x14, 4) == 2
    assert h.memory.read(h.address + 0x18, 4) == 1
    assert h.memory.read(h.address + 0x1C, 1) == 99
    assert h.memory.read(h.address + 0x10, 4) == 0
    assert not h.events


def test_header_gate_is_read_once_but_allocator_uses_current_post_cleanup_fields():
    def write_effect(h, address, width, value):
        if not h.frames or not hasattr(h, "address"):
            return
        frame, view = h.frames[-1]
        if len(view) == 0xB0 and address == frame + 0xA8 and value == 1:
            h.finished_inputs = getattr(h, "finished_inputs", 0) + 1
            if h.finished_inputs == 1:
                h.memory.write(VERSION, 4, 0)
                h.memory.write(h.stream, 8, h.table2)
            elif h.finished_inputs == 2:
                h.memory.write(h.address + 0x14, 4, 3)
                h.memory.write(h.address + 8, 8, h.replacement)

    h = setup(modern([0]), write_effect=write_effect)
    h.replacement = h.memory.allocate(8)
    assert invoke(h) == h.output and h.source.remaining == 0
    assert h.memory.read_bytes(h.old_array, 16) == b"old list backing"
    with pytest.raises(ReplayMemoryError, match="unmapped"):
        h.memory.read(h.replacement, 1)
    assert (0x142D6BA78, (24,), None) in h.events
    assert sum(e[0] == "read" and e[1] == VERSION for e in h.accesses) == 1
    methods = [e[1] for e in h.accesses if e[0] == "read" and e[1] in (h.table + 24, h.table2 + 24)]
    assert methods == [h.table + 24, h.table2 + 24, h.table2 + 24]


def test_tag_is_reloaded_after_actual_Result_cleanup():
    def write_effect(h, address, width, value):
        if h.frames:
            frame, view = h.frames[-1]
            if len(view) == 0xB0 and address == frame + 0xA8 and value == 1:
                h.memory.write(frame + 0x78, 1, 0)

    h = setup(b"\x0aN", version=0, write_effect=write_effect)
    assert invoke(h) == h.output and h.source.position == 1
    assert not h.constructed


def test_factory_holds_table_before_outgoing_context_store_but_reads_current_slot_after_it():
    def write_effect(h, address, width, value):
        if h.frames:
            frame, view = h.frames[-1]
            if len(view) == 0xB0 and address == frame + 0x20:
                assert value == h.resolver
                h.memory.write(h.address, 8, h.other_table)
                h.memory.write(0x1432BEBB8, 8, GENERIC)

    h = setup(b"\x0a\0", version=0, write_effect=write_effect)
    h.other_table = h.memory.allocate(8)
    h.memory.write(h.other_table, 8, 0xF01)
    assert invoke(h) == h.output
    assert len(h.constructed) == 1
    assert len(h.completed) == 2  # Direct generic factory plus reader; special was not selected.


@pytest.mark.parametrize("source", [b"", b"\1", b"\1\0\0\0", modern([])])
def test_truncation_retains_prior_effects_and_does_not_fabricate_success(source):
    h = setup(source)
    with pytest.raises(UnresolvedReplayTaskRebuild, match="exceeds remaining"):
        invoke(h)
    assert h.memory.read_bytes(h.output, 48) == b"O" * 48
    assert not h.frames


def test_Input_error_keeps_first_field_effect_without_replacing_array_or_processing_Result():
    result = bytearray(48)
    result[24:32] = (7).to_bytes(8, "little")
    h = setup(modern([0], capacity=9), result=bytes(result))
    with pytest.raises(UnresolvedReplayTaskRebuild, match=r"14122b3dd.*metadata/TLS"):
        invoke(h)
    assert h.source.position == 4
    assert h.memory.read(h.address + 0x14, 4) == 9
    assert h.memory.read(h.address + 8, 8) == h.old_array
    assert h.completed[0][1][0xA8] == 0


@pytest.mark.parametrize("capacity", [0xFFFFFFFF, 0x80000000])
def test_negative_saved_capacity_frees_current_old_array_then_real_allocation_refuses(capacity):
    h = setup(modern([0], capacity=capacity))
    with pytest.raises(MemoryError):
        invoke(h)
    assert h.source.position == 8
    assert h.memory.read(h.address + 8, 8) == h.old_array  # Publication has not reached.
    with pytest.raises(ReplayMemoryError, match="unmapped"):
        h.memory.read(h.old_array, 1)
    assert (0x142D6BA78, ((1 << 64) - 1,), None) in h.events


@pytest.mark.parametrize("error_in_local", [False, True])
def test_selected_factory_RAX_is_ignored_in_favor_of_fixed_local_Result(error_in_local):
    def effect(h, target, args, data):
        if target == 0xF01:
            _list, result, kind, stream, context = args
            assert (kind, stream, context) == (10, h.stream, h.resolver)
            h.memory.write(result + 24, 8, 9 if error_in_local else 0)
            h.memory.write(h.output + 24, 8, 0 if error_in_local else 9)
            return h.output
        return NotImplemented

    h = setup(b"\x0a\0", version=0, effect=effect)
    h.memory.write(0x1432BEBB8, 8, 0xF01)
    if error_in_local:
        with pytest.raises(UnresolvedReplayTaskRebuild, match=r"14122b82e.*metadata/TLS"):
            invoke(h)
        assert h.source.position == 1
    else:
        assert invoke(h) == h.output and h.source.position == 2
        assert h.memory.read_bytes(h.output, 41) == bytes(41)


@pytest.mark.parametrize(
    "args,data", [((), None), ((1, 2, 3), None), ((1, 2, 3, 4), memoryview(bytearray(1)))]
)
def test_bound_input_shape_rejected_before_effects(args, data):
    h = setup(b"\0", version=0)
    assert h.reader.call
    with pytest.raises(ValueError, match="malformed"):
        h.reader.call(ENTRY, args, data)
    assert not h.accesses


def test_unknown_call_delegation_and_missing_selected_factory_are_explicit():
    h = setup(b"\x0a\0", version=0)
    h.memory.write(0x1432BEBB8, 8, 0xF01)
    with pytest.raises(UnresolvedReplayTaskRebuild, match="f01"):
        invoke(h)
    assert h.source.position == 1 and h.memory.read_bytes(h.output, 48) == b"O" * 48
    missing = bind_replay_saved_object_list(
        h.context,
        ReplayTaskRebuildCalls(None),
        atomics=h.atomics,
        bind_local=h.bind_local,
        scratch=SCRATCH,
    )
    assert missing.call
    with pytest.raises(UnresolvedReplayTaskRebuild, match="unavailable"):
        missing.call(0xABCD, (), None)
