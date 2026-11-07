"""Owned staged contracts; large Player constructors/readers are explicit fixtures.

Real engine Input supplies bytes under a declared zero48B Result profile.
Production Result/control/vector bodies and saved-Player handlers compose;
no original stream/native class or complete World restore is claimed.
"""

from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from vantage.replay_base_saved_registration import (
    ReplayBaseSavedRegistrationFP,
    ReplayBaseSavedRegistrationScratch,
    bind_replay_base_saved_registration,
)
from vantage.replay_memory import ReplayMemory, ReplayMemoryError
from vantage.replay_player_saved_factory import (
    ReplayPlayerSavedFactoryScratch,
    bind_replay_player_saved_factory,
)
from vantage.replay_player_wire_factory import (
    ReplayPlayerWireFactoryScratch,
    bind_replay_player_wire_factory,
    create_replay_player_wire_factory,
    read_replay_player_wire_byte,
    read_replay_player_wire_type,
)
from vantage.replay_saved_apply import bind_replay_saved_apply
from vantage.replay_saved_input import ReplaySavedInput, bind_replay_saved_input
from vantage.replay_saved_result import bind_replay_saved_result
from vantage.replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
)
from vantage.replay_unit_ai_map import ReplayUnitAIMapAtomics

INPUT, BYTE, FACTORY = 0x1415E5830, 0x140DAF040, 0x14174F3D0
FORWARD, VECTOR, DIRECT = 0x1409076B0, 0x1402BD890, 0x1402BD7F0
IO, HANDLER, READER, DESTROY, DISPOSE = 0x7001, 0x7002, 0x7003, 0x7004, 0x7005
SCRATCH = ReplayPlayerWireFactoryScratch(
    bytes(range(0x78)), bytes(range(0x60)), bytes(i & 255 for i in range(0x118))
)
VARIANTS = (
    (0, 0x14174ECF0, 0x1417551B0, 0x1432F76C8),
    (1, 0x14174E610, 0x141755040, 0x1432F72D8),
    (2, 0x14174DF30, 0x14174FA70, 0x1432F6C88),
    (3, 0x14174D850, 0x14174B740, 0x1432F6628),
)


def setup(
    value=1,
    *,
    effect=None,
    read_effect=None,
    write_effect=None,
    result_bytes=bytes(48),
    compose=False,
    large=True,
):
    h = SimpleNamespace()
    h.memory = m = ReplayMemory()
    h.subject, h.out, h.dest, h.stream, h.vtable, h.world, h.index, h.rows = (
        m.allocate(n) for n in (8, 48, 8, 8, 32, 0x800, 4, 64)
    )
    m.write_bytes(h.out, b"O" * 48)
    m.write_bytes(h.dest, b"D" * 8)
    m.write(h.stream, 8, h.vtable)
    m.write(h.vtable + 24, 8, IO)
    m.write(h.index, 4, 2)
    m.write(h.world + 0x768, 8, h.rows)
    m.write_bytes(h.rows, bytes(64))
    m.map_bytes(0x143199DD0, (0x142D6BAB4).to_bytes(8, "little"))
    h.frames, h.completed, h.events, h.accesses, h.handles, h.readers = [], [], [], [], [], []
    h.callbacks = {}

    def read(address, width):
        value = m.read(address, width)
        h.accesses.append(("read", address, width, value))
        if read_effect:
            replacement = read_effect(h, address, width, value)
            if replacement is not None:
                return replacement
        return value

    def write(address, width, value):
        m.write(address, width, value)
        h.accesses.append(("write", address, width, value))
        if write_effect:
            write_effect(h, address, width, value)

    h.context = ReplayTaskRebuildStorage(h.subject, read, write)
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

    h.local = local
    runtime = m.runtime_calls()

    def terminal(target, args, data):
        if target in h.callbacks:
            return h.callbacks[target](args)
        if target == HANDLER:
            assert len(args) == 6
            h.handles.append((args, m.read(args[5], 4)))
            m.write_bytes(args[1], b"H" * 48)  # Declared selected-handler effect fixture.
            return 0xBAD
        if target in (0x1416C2440, 0x14174FA70) and large:
            subject, _result, stream, world, index = args
            assert (stream, world) == (h.stream, h.world)
            assert m.read(index, 4) == 2
            m.write(subject, 8, 0x1432F6C88)
            m.write(subject + 8, 8, world)
            return 0xBAD  # Explicit incomplete large-constructor fixture.
        if target == READER and large:
            h.readers.append(args)
            assert m.read_bytes(args[1], 48) == bytes(48)
            return 0xBAD  # Explicit large-reader fixture; no body success claim.
        assert runtime.call
        return runtime.call(target, args, data)

    terminal_calls = ReplayTaskRebuildCalls(terminal)
    h.source = ReplaySavedInput(bytes([value]))
    if callable(result_bytes):
        result_bytes = result_bytes(h)
    lower = bind_replay_saved_input(
        h.context, terminal_calls, h.source, stream=h.stream, target=IO, result_bytes=result_bytes
    )
    lower = bind_replay_saved_apply(h.context, lower, atomics=h.atomics, imports=terminal_calls)
    lower = bind_replay_saved_result(h.context, lower, atomics=h.atomics, imports=terminal_calls)
    if compose:
        lower = bind_replay_base_saved_registration(
            h.context,
            lower,
            imports=terminal_calls,
            fp_calls=ReplayBaseSavedRegistrationFP(None),
            bind_local=local,
            scratch=ReplayBaseSavedRegistrationScratch(bytes(0xB0)),
        )
        lower = bind_replay_player_saved_factory(
            h.context,
            lower,
            atomics=h.atomics,
            bind_local=local,
            scratch=ReplayPlayerSavedFactoryScratch(bytes(0xD0), bytes(0x48)),
        )
        for _, _, _, table in VARIANTS:
            m.map_bytes(table + 0xE8, READER.to_bytes(8, "little"))

    def observe(target, args, data):
        h.events.append((target, args))
        if effect:
            value = effect(h, target, args, data)
            if value is not NotImplemented:
                return value
        assert lower.call
        return lower.call(target, args, data)

    h.lower = ReplayTaskRebuildCalls(observe)
    h.bound = bind_replay_player_wire_factory(
        h.context, h.lower, atomics=h.atomics, bind_local=local, scratch=SCRATCH
    )
    h.registry = registry(
        h,
        [value],
        target=next(row[1] for row in VARIANTS if row[0] == value) if compose else HANDLER,
    )
    return h


def registry(h, keys, *, target=HANDLER):
    m = h.memory
    sentinel = m.allocate(0x38)
    m.write(sentinel + 0x19, 1, 1)
    nodes = {}

    def build(ordered):
        if not ordered:
            return sentinel
        middle = len(ordered) // 2
        key = ordered[middle]
        node, handler, vptr = m.allocate(0x38), m.allocate(8), m.allocate(16)
        m.write(handler, 8, vptr)
        m.write(vptr + 8, 8, target)
        m.write(node + 0x19, 1, 0)
        m.write(node + 0x20, 4, key & 0xFFFFFFFF)
        m.write(node + 0x28, 8, handler)
        # node+30 is intentionally undefined: factory may not read/retain it.
        m.write(node, 8, build(ordered[:middle]))
        m.write(node + 0x10, 8, build(ordered[middle + 1 :]))
        nodes[key] = (node, handler, vptr)
        return node

    m.write(sentinel + 8, 8, build(sorted(keys)))
    if not hasattr(h, "global_mapped"):
        m.map_bytes(0x144440968, sentinel.to_bytes(8, "little"))
        h.global_mapped = True
    else:
        m.write(0x144440968, 8, sentinel)
    h.nodes = nodes
    return sentinel


def invoke(h, entry=FACTORY, *, direct=False, output=None, destination=None):
    out = h.out if output is None else output
    dest = h.dest if destination is None else destination
    if entry == FACTORY:
        args = (out, h.stream, h.dest, h.world, h.index)
        fn = create_replay_player_wire_factory
    else:
        args = (out, 0x111, 0x100000073, 0x222, h.stream, dest)
        fn = read_replay_player_wire_byte if entry == BYTE else read_replay_player_wire_type
    if not direct:
        assert h.bound.call
        return h.bound.call(entry, args, None)
    return fn(
        h.context, *args, calls=h.bound, atomics=h.atomics, bind_local=h.local, scratch=SCRATCH
    )


@pytest.mark.parametrize("entry", [BYTE, INPUT, FACTORY])
@pytest.mark.parametrize("value", [0, 1, 2, 3, 255])
@pytest.mark.parametrize("direct", [False, True])
def test_real_input_Result_cleanup_and_current_dispatch(entry, value, direct):
    h = setup(value)
    assert invoke(h, entry, direct=direct) == h.out
    assert h.source.position == 1
    if entry == FACTORY:
        assert h.memory.read_bytes(h.out, 48) == b"H" * 48
        args, copied = h.handles[0]
        assert args[:5] == (h.nodes[value][1], h.out, h.stream, h.dest, h.world)
        assert copied == 2  # Index2 is not the wiretype.
    else:
        width = 1 if entry == BYTE else 4
        assert h.memory.read(h.dest, width) == value
        assert h.memory.read_bytes(h.dest + width, 8 - width) == b"D" * (8 - width)
        if entry == BYTE:
            assert h.memory.read_bytes(h.out, 48) == bytes(48)
        else:
            assert h.memory.read_bytes(h.out, 48) == bytes(41) + b"O" * 7
    assert not h.frames


@pytest.mark.parametrize("key", [-0x80000000, -1, 0, 1, 0x7FFFFFFF])
def test_signed_lookup_reads_current_type_after_cleanup(key):
    def effect(h, target, args, data):
        if target == VECTOR and len(h.frames) == 1:
            h.memory.write(h.frames[0][0] + 0x38, 4, key & 0xFFFFFFFF)
        return NotImplemented

    h = setup(effect=effect)
    h.registry = registry(h, [-0x80000000, -1, 0, 1, 0x7FFFFFFF])
    assert invoke(h) == h.out
    assert h.handles[0][0][0] == h.nodes[key][1]


def test_cleanup_reloads_current_registry_and_late_incoming_index_pointer():
    h = setup()
    alternate = h.memory.allocate(4)
    h.memory.write(alternate, 4, 3)
    old = h.registry
    replacement = registry(h, [1])
    selected = h.nodes[1][1]
    h.memory.write(0x144440968, 8, old)
    lower = h.lower.call

    def callback(target, args, data):
        if target == VECTOR and len(h.frames) == 1:
            h.memory.write(0x144440968, 8, replacement)
            h.memory.write(h.frames[0][0] + 0x110, 8, alternate)
        assert lower
        return lower(target, args, data)

    h.bound = bind_replay_player_wire_factory(
        h.context,
        ReplayTaskRebuildCalls(callback),
        atomics=h.atomics,
        bind_local=h.local,
        scratch=SCRATCH,
    )
    assert invoke(h) == h.out
    assert h.handles[0][0][0] == selected and h.handles[0][1] == 3
    snapshot = h.completed[-1][1]
    assert snapshot[0x38:0x40] == ((h.out & ~0xFFFFFFFF) | 3).to_bytes(8, "little")


def test_current_handler_vptr_is_loaded_after_index_copy_and_slot_after_arg_stores():
    h = setup()
    _, handler, _ = h.nodes[1]
    replacement = h.memory.allocate(16)
    new_target = 0x7999
    h.callbacks[new_target] = lambda args: h.handles.append((args, 99))

    def write(address, width, value):
        h.memory.write(address, width, value)
        if h.frames and len(h.frames[-1][1]) == 0x118:
            frame = h.frames[-1][0]
            if address == frame + 0x38 and width == 4:
                h.memory.write(handler, 8, replacement)
            if address == frame + 0x20 and value == h.world:
                h.memory.write(replacement + 8, 8, new_target)

    context = ReplayTaskRebuildStorage(h.subject, h.context.read, write)
    h.context = context
    h.bound = bind_replay_player_wire_factory(
        context, h.lower, atomics=h.atomics, bind_local=h.local, scratch=SCRATCH
    )
    assert invoke(h) == h.out and h.handles[0][1] == 99


def test_outer_cleanup_can_replace_current_scratch_byte_before_publication():
    def effect(h, target, args, data):
        if target == DIRECT:
            assert h.memory.read(args[0] + 40, 1) == 1
            h.memory.write(h.frames[0][0] + 0x40, 1, 0xFE)
        return NotImplemented

    h = setup(effect=effect)
    invoke(h, INPUT)
    assert h.memory.read(h.dest, 4) == 0xFE


def test_destination_alias_is_written_before_later_output_clear():
    h = setup(255)
    invoke(h, INPUT, destination=h.out)
    writes = [row for row in h.accesses if row[:3] == ("write", h.out, 4)]
    assert writes == [("write", h.out, 4, 255)]
    assert h.memory.read_bytes(h.out, 48) == bytes(41) + b"O" * 7


@pytest.mark.parametrize("entry", [BYTE, INPUT, FACTORY])
def test_child_RAX_cannot_replace_fixed_Result(entry):
    def effect(h, target, args, data):
        if target == IO:
            h.memory.write(args[2], args[3], 1)
            h.memory.write_bytes(args[1], bytes(48))
            return h.out  # No write to that unrelated returned Result.
        return NotImplemented

    h = setup(effect=effect)
    invoke(h, entry)
    assert h.memory.read_bytes(h.out, 48) == (
        b"H" * 48 if entry == FACTORY else bytes(48) if entry == BYTE else bytes(41) + b"O" * 7
    )


def test_byte_wrapper_status_requires_real_decoration_after_clear_and_processed():
    result = bytearray(48)
    result[24] = 7
    h = setup(result_bytes=bytes(result))
    with pytest.raises(UnresolvedReplayTaskRebuild, match="140900ed0"):
        invoke(h, BYTE)
    assert h.source.position == 1 and h.memory.read(h.dest, 1) == 1
    assert h.memory.read_bytes(h.out, 48) == bytes(48)
    assert h.completed[-1][1][0x58] == 1
    assert not any(target == FORWARD for target, _ in h.events)


@pytest.mark.parametrize(
    "target,entry,message", [(BYTE, INPUT, "wire Input"), (INPUT, FACTORY, "factory Input")]
)
def test_fixed_status_error_refuses_without_later_cleanup_or_dispatch(target, entry, message):
    def effect(h, selected, args, data):
        if selected == target:
            h.memory.write(args[0] + 24, 8, 7)
            return h.out
        return NotImplemented

    h = setup(effect=effect)
    with pytest.raises(UnresolvedReplayTaskRebuild, match=message):
        if entry == INPUT:
            read_replay_player_wire_type(
                h.context,
                h.out,
                0x111,
                0x73,
                0x222,
                h.stream,
                h.dest,
                calls=h.lower,
                atomics=h.atomics,
                bind_local=h.local,
                scratch=SCRATCH,
            )
        else:
            create_replay_player_wire_factory(
                h.context,
                h.out,
                h.stream,
                h.dest,
                h.world,
                h.index,
                calls=h.lower,
                atomics=h.atomics,
                bind_local=h.local,
                scratch=SCRATCH,
            )
    assert h.source.position == 0 and not h.handles
    assert h.memory.read_bytes(h.out, 48) == b"O" * 48
    assert not any(selected in (DIRECT, VECTOR) for selected, _ in h.events)


def test_missing_type_reaches_actual_error_helper_without_fallback():
    h = setup(4)
    registry(h, [1, 3, 5])
    with pytest.raises(UnresolvedReplayTaskRebuild, match="140a08840"):
        invoke(h)
    error = next(args for target, args in h.events if target == 0x140A08840)
    assert error[1:] == (0, 0x1432F6A30, 0x5C, 0x1432F6A10, 4)
    assert h.memory.read_bytes(h.out, 48) == b"O" * 48 and not h.handles


def test_error_helper_returned_nonzero_status_reaches_TLS_frontier():
    h = setup()
    registry(h, [])
    h.callbacks[0x140A08840] = lambda args: h.memory.write(args[0] + 24, 8, 9)
    with pytest.raises(UnresolvedReplayTaskRebuild, match="lookup metadata/TLS"):
        invoke(h)
    assert not h.handles and not h.frames


def test_missing_type_error_claiming_success_does_not_create_a_handler():
    h = setup()
    registry(h, [])
    h.callbacks[0x140A08840] = lambda args: None  # Isolated source-order counterexample.
    with pytest.raises(ReplayMemoryError):
        invoke(h)
    assert not h.handles and h.memory.read_bytes(h.out, 48) == b"O" * 48


@pytest.mark.parametrize("value,handler,constructor,table", VARIANTS)
def test_real_saved_factory_handlers_with_qualified_large_Player_fixtures(
    value,
    handler,
    constructor,
    table,
):
    h = setup(value, compose=True)
    assert invoke(h) == h.out
    subject = h.memory.read(h.rows + 32, 8)
    assert subject and h.memory.read(subject, 8) == table
    assert h.memory.read(subject + 8, 8) == h.world
    assert h.readers and h.readers[0][0] == subject
    assert h.memory.read_bytes(h.out, 48) == bytes(41) + b"O" * 7
    assert h.source.position == 1 and not h.frames


def test_real_handler_refuses_at_unprovided_large_Player_constructor_after_allocation():
    h = setup(1, compose=True, large=False)
    with pytest.raises(UnresolvedReplayTaskRebuild, match="1416c2440"):
        invoke(h)
    assert h.source.position == 1 and h.memory.read(h.rows + 32, 8) == 0
    assert not h.readers and h.memory.read_bytes(h.out, 48) == b"O" * 48


@pytest.mark.parametrize("entry,count", [(BYTE, 6), (INPUT, 6), (FACTORY, 5)])
def test_binder_rejects_malformed_current_entry_arity_or_data(entry, count):
    h = setup()
    assert h.bound.call
    with pytest.raises(ValueError, match="malformed"):
        h.bound.call(entry, (0,) * (count - 1), None)
    with pytest.raises(ValueError, match="malformed"):
        h.bound.call(entry, (0,) * count, memoryview(bytearray()))
    assert not h.events and h.source.position == 0


def test_unprovided_children_and_current_stream_virtual_are_not_successful():
    h = setup()
    h.memory.write(h.vtable + 24, 8, 0x7BAD)
    with pytest.raises(UnresolvedReplayTaskRebuild, match="7bad"):
        invoke(h)
    assert h.source.position == 0 and h.memory.read_bytes(h.out, 48) == b"O" * 48
    assert not h.frames


@pytest.mark.parametrize("strong", [1, 2])
def test_real_forwarded_control_counts_and_current_dispose_vptr(strong):
    def profile(h):
        m = h.memory
        h.control, h.control_table, h.new_control_table = (m.allocate(16) for _ in range(3))
        m.write(h.control, 8, h.control_table)
        m.write(h.control + 8, 4, strong)
        m.write(h.control + 12, 4, 1)
        m.write(h.control_table, 8, DESTROY)
        m.write(h.control_table + 8, 8, 0x7BAD)
        m.write(h.new_control_table + 8, 8, DISPOSE)
        h.destroyed = []

        def destroy(args):
            assert args == (h.control,)
            h.destroyed.append(DESTROY)
            m.write(h.control, 8, h.new_control_table)
            # Outer Input cleanup occurs before its current scratch-byte reload.
            m.write(h.frames[0][0] + 0x40, 1, 0xFE)

        h.callbacks[DESTROY] = destroy
        h.callbacks[DISPOSE] = lambda args: h.destroyed.append(DISPOSE)
        result = bytearray(48)
        result[32:40] = h.control.to_bytes(8, "little")
        return bytes(result)

    h = setup(result_bytes=profile)
    invoke(h, INPUT)
    assert h.memory.read(h.control + 8, 4) == strong - 1
    assert h.destroyed == ([DESTROY, DISPOSE] if strong == 1 else [])
    assert h.memory.read(h.dest, 4) == (0xFE if strong == 1 else 1)
    assert h.memory.read(h.control + 12, 4) == (0 if strong == 1 else 1)


def test_required_cleanup_failure_preserves_stream_effects_without_late_publication():
    def effect(h, target, args, data):
        if target == DIRECT:
            raise UnresolvedReplayTaskRebuild("declared cleanup failure")
        return NotImplemented

    h = setup(effect=effect)
    with pytest.raises(UnresolvedReplayTaskRebuild, match="cleanup failure"):
        invoke(h, INPUT)
    assert h.source.position == 1 and h.memory.read_bytes(h.dest, 8) == b"D" * 8
    assert h.memory.read_bytes(h.out, 48) == b"O" * 48 and not h.frames


def test_success_without_destination_write_uses_explicit_scratch_seed_not_zero():
    def effect(h, target, args, data):
        if target == IO:
            # Qualified adversarial child fixture, not ReplaySavedInput behavior.
            h.memory.write_bytes(args[1], bytes(48))
            return h.out
        return NotImplemented

    h = setup(effect=effect)
    invoke(h, INPUT)
    assert h.source.position == 0 and h.memory.read(h.dest, 4) == SCRATCH.input[0x40]


def test_byte_destination_alias_can_be_overwritten_by_output48_clear():
    h = setup(255)
    invoke(h, BYTE, destination=h.out + 24)
    assert h.source.position == 1 and h.memory.read_bytes(h.out, 48) == bytes(48)
    assert ("write", h.out + 24, 1, 255) in h.accesses


def test_missing_atomic_provider_refuses_after_source_processed_write():
    h = setup()
    control = h.memory.allocate(16)
    h.memory.write(control + 8, 4, 1)
    h.atomics = ReplayUnitAIMapAtomics(None, None)
    # An explicit child fixture reaches outer held-control cleanup; this is
    # not a claimed implementation of the byte wrapper or native stream.
    lower = h.lower.call

    def call(target, args, data):
        if target == BYTE:
            h.memory.write_bytes(args[0], bytes(48))
            h.memory.write(args[0] + 32, 8, control)
            h.memory.write(args[5], 1, 1)
            return args[0]
        assert lower
        return lower(target, args, data)

    with pytest.raises(UnresolvedReplayTaskRebuild, match="atomic effect unavailable"):
        read_replay_player_wire_type(
            h.context,
            h.out,
            0,
            0,
            0,
            h.stream,
            h.dest,
            calls=ReplayTaskRebuildCalls(call),
            atomics=h.atomics,
            bind_local=h.local,
            scratch=SCRATCH,
        )
    assert h.completed[-1][1][0x70] == 1
    assert h.memory.read_bytes(h.dest, 8) == b"D" * 8


def test_byte_error_decoration_receives_truncated_line_before_real_forward():
    raw = bytearray(48)
    raw[24] = 9
    h = setup(result_bytes=bytes(raw))
    h.callbacks[0x140900ED0] = lambda args: h.memory.write(args[0] + 24, 8, 0)
    invoke(h, BYTE)
    call = next(args for target, args in h.events if target == 0x140900ED0)
    assert call[1:] == (0x111, 0x73, 0x222)
    assert h.memory.read_bytes(h.out, 48) == bytes(48)
