"""Owned input/cleanup with explicit bounded forwarding effects, not native I/O."""

from __future__ import annotations

from contextlib import contextmanager

import pytest

from vantage.replay_memory import ReplayMemory, ReplayMemoryError
from vantage.replay_saved_input import ReplaySavedInput, bind_replay_saved_input
from vantage.replay_saved_position import (
    bind_replay_saved_position,
    read_replay_saved_byte,
    read_replay_saved_position,
    read_replay_saved_u32,
)
from vantage.replay_saved_result import bind_replay_saved_result
from vantage.replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
)
from vantage.replay_unit_ai_map import ReplayUnitAIMapAtomics

FORWARD = 0x1409076B0
CLEANUP = 0x1402BD890


class Case:
    def __init__(self, result_bytes=bytes(48)):
        self.memory = m = ReplayMemory()
        self.position, self.output, self.stream, self.table = (
            m.allocate(size) for size in (16, 48, 8, 32)
        )
        m.write_bytes(self.position, b"\xa5" * 16)
        m.write_bytes(self.output, b"\xa5" * 48)
        m.write(self.stream, 8, self.table)
        m.write(self.table + 24, 8, 0xA110)
        self.events = []
        self.status_reads = []
        self.raw_results = []
        self.forwarded = []
        self.forward_hook = None
        self.diagnostic = None
        self.virtuals = {}
        self.forward_enabled = True
        self.cleanup_enabled = True
        self.source = ReplaySavedInput(bytes(range(14)))
        self.atomics = ReplayUnitAIMapAtomics(m.compare_exchange_u32, m.fetch_add_u32)

        def read(address, width):
            if width == 8 and any(address == raw + 24 for raw in self.raw_results):
                assert m.read(address + 16, 1) == 1
                self.status_reads.append(("raw", address - 24))
            if width == 8 and any(address == out + 24 for out in self.forwarded):
                self.status_reads.append(("forwarded", address - 24))
            return m.read(address, width)

        self.context = ReplayTaskRebuildStorage(self.position, read, m.write)
        runtime = m.runtime_calls()

        def effects(target, args, data):
            if target == FORWARD:
                if not self.forward_enabled:
                    raise UnresolvedReplayTaskRebuild("actual Result forward unavailable")
                output, raw = args
                self.forwarded.append(output)
                self.forward(output, raw)
                if self.forward_hook is not None:
                    self.forward_hook(output, raw)
                return 0xDEAD  # Caller must retain its output, not this RAX.
            if target == 0x140900ED0:
                if self.diagnostic is None:
                    raise UnresolvedReplayTaskRebuild("native Result diagnostic unavailable")
                return self.diagnostic(args)
            if target in self.virtuals:
                return self.virtuals[target](args)
            assert runtime.call is not None
            return runtime.call(target, args, data)

        io = bind_replay_saved_input(
            self.context,
            ReplayTaskRebuildCalls(effects),
            self.source,
            stream=self.stream,
            target=0xA110,
            result_bytes=result_bytes,
        )
        clean = bind_replay_saved_result(self.context, io, atomics=self.atomics, imports=runtime)

        def observe(target, args, data):
            self.events.append((target, args))
            if target == 0xA110:
                self.raw_results.append(args[1])
            if target == CLEANUP and not self.cleanup_enabled:
                raise UnresolvedReplayTaskRebuild("actual Result cleanup unavailable")
            assert clean.call is not None
            return clean.call(target, args, data)

        self.lower = ReplayTaskRebuildCalls(observe)
        self.calls = bind_replay_saved_position(
            self.context, self.lower, atomics=self.atomics, bind_local=m.bind_local
        )

    def forward(self, output, raw):
        """Explicit empty-vector source-contract effect, not a native oracle.

        This test dependency really initializes/copies/marks and acquires its
        control. Nonempty vector copying deliberately refuses. Production
        forwarding remains a required separately implemented body.
        """
        m = self.memory
        assert m.read(raw + 40, 1) == 1
        for offset in (0, 8, 16, 24, 32):
            m.write(output + offset, 8, 0)
        m.write(output + 40, 1, 0)
        control = m.read(raw + 32, 8)
        if control:
            m.fetch_add_u32(control + 8, 1)
        m.write(output + 24, 8, m.read(raw + 24, 8))
        m.write(output + 32, 8, m.read(raw + 32, 8))
        assert m.read(raw, 8) == m.read(raw + 8, 8) == 0
        m.write(output + 8, 8, 0)
        m.write(raw + 40, 1, 1)

    def invoke(self, target, *args):
        assert self.calls.call is not None
        return self.calls.call(target, args, None)

    def position_read(self):
        return self.invoke(0x140C29890, self.position, self.output, self.stream)


@pytest.mark.parametrize(
    ("entry", "width"), [(0x140D07EE0, 1), (0x140B81E60, 4), (0x140B81D60, 4), (0x140D94310, 4)]
)
def test_wrappers_actual_input_forward_and_cleanup(entry, width):
    case = Case()
    assert (
        case.invoke(entry, case.output, 0xABC, 0x100000012, 0xDEF, case.stream, case.position)
        == case.output
    )
    assert case.source.position == width
    assert case.memory.read_bytes(case.position, 16) == bytes(range(width)) + b"\xa5" * (16 - width)
    assert case.memory.read_bytes(case.output, 48) == bytes(48)
    assert [target for target, _ in case.events] == [0xA110, FORWARD, CLEANUP]
    raw = case.raw_results[0]
    with pytest.raises(ReplayMemoryError, match="unmapped"):
        case.memory.read(raw, 1)


def test_position_all_four_actual_reads_and_final_padding_preservation():
    case = Case()
    assert case.position_read() == case.output
    assert case.source.position == 14
    assert case.memory.read_bytes(case.position, 16) == bytes(range(14)) + b"\xa5\xa5"
    assert case.memory.read_bytes(case.output, 48) == bytes(41) + b"\xa5" * 7
    io = [args for target, args in case.events if target == 0xA110]
    assert [args[2] for args in io] == [case.position + x for x in (0, 4, 8, 12)]
    assert [args[3] for args in io] == [4, 4, 4, 2]
    assert [target for target, _ in case.events] == [0xA110, FORWARD, CLEANUP, CLEANUP] * 4
    assert [kind for kind, _ in case.status_reads] == ["raw", "forwarded"] * 4


def test_direct_public_position_executes_bound_middle_wrappers():
    case = Case()
    assert (
        read_replay_saved_position(
            case.context,
            case.position,
            case.output,
            case.stream,
            calls=case.calls,
            atomics=case.atomics,
            bind_local=case.memory.bind_local,
        )
        == case.output
    )
    assert case.source.position == 14


@pytest.mark.parametrize(
    ("function", "width"), [(read_replay_saved_byte, 1), (read_replay_saved_u32, 4)]
)
def test_direct_public_wrappers_keep_current_read_before_output_clear(function, width):
    case = Case()
    seen = []

    def hook(output, raw):
        seen.append(case.memory.read_bytes(output, 48))

    case.forward_hook = hook
    assert (
        function(
            case.context,
            case.output,
            3,
            4,
            5,
            case.stream,
            case.output,
            calls=case.lower,
            atomics=case.atomics,
            bind_local=case.memory.bind_local,
        )
        == case.output
    )
    assert case.source.position == width and seen == [bytes(48)]


def test_missing_forward_refuses_after_bytes_and_output_clear_before_cleanup():
    case = Case()
    case.forward_enabled = False
    with pytest.raises(UnresolvedReplayTaskRebuild, match="forward unavailable"):
        case.invoke(0x140D07EE0, case.output, 0, 0, 0, case.stream, case.position)
    assert case.source.position == 1 and case.memory.read(case.position, 1) == 0
    assert case.memory.read_bytes(case.output, 48) == bytes(48)
    assert [target for target, _ in case.events] == [0xA110, FORWARD]


def test_missing_cleanup_refuses_after_real_forward_effects():
    case = Case()
    case.cleanup_enabled = False
    with pytest.raises(UnresolvedReplayTaskRebuild, match="cleanup unavailable"):
        case.invoke(0x140B81E60, case.output, 0, 0, 0, case.stream, case.position)
    assert case.source.position == 4
    assert case.memory.read_bytes(case.output, 48) == bytes(48)
    assert [target for target, _ in case.events] == [0xA110, FORWARD, CLEANUP]


def test_missing_error_decorator_preserves_processed_raw_and_cleared_output():
    profile = bytearray(48)
    profile[24] = 7
    case = Case(bytes(profile))
    with pytest.raises(UnresolvedReplayTaskRebuild, match="diagnostic unavailable"):
        case.invoke(0x140B81E60, case.output, 0xABC, 0x100000012, 0xDEF, case.stream, case.position)
    assert case.source.position == 4
    assert case.memory.read_bytes(case.output, 48) == bytes(48)
    assert case.events[-1][0] == 0x140900ED0
    assert case.events[-1][1][1:] == (0xABC, 0x12, 0xDEF)


@pytest.mark.parametrize("phase", range(4))
def test_forwarded_error_refuses_only_after_raw_release_cleanup(phase):
    case = Case()
    count = 0

    def hook(output, raw):
        nonlocal count
        if count == phase:
            case.memory.write(output + 24, 8, 0xBAD)
        count += 1

    case.forward_hook = hook
    with pytest.raises(UnresolvedReplayTaskRebuild, match="returned-error/logging frontier"):
        case.position_read()
    assert case.source.position == (4, 8, 12, 14)[phase]
    assert [target for target, _ in case.events].count(CLEANUP) == phase * 2 + 1
    assert case.memory.read_bytes(case.output, 48) == b"\xa5" * 48


def test_raw_release_mutates_forwarded_status_and_reloads_current_control_vptr():
    case = Case()
    m = case.memory
    control, table, next_table = (m.allocate(16) for _ in range(3))
    m.write(control, 8, table)
    m.write(control + 8, 4, 1)
    m.write(control + 12, 4, 1)
    m.write(table, 8, 0xD1)
    m.write(next_table + 8, 8, 0xD2)
    held = []

    def hook(output, raw):
        if not held:
            held.extend((output, raw))
            m.write(output + 24, 8, 1)
            m.write(raw + 32, 8, control)

    def destroy(args):
        assert args == (control,)
        m.write(held[0] + 24, 8, 0)
        m.write(held[1] + 32, 8, 0xBAD)
        m.write(control, 8, next_table)

    def dispose(args):
        assert args == (control,)
        m.write(case.position + 15, 1, 0xCC)

    case.forward_hook = hook
    case.virtuals.update({0xD1: destroy, 0xD2: dispose})
    assert case.position_read() == case.output
    assert m.read(control + 8, 4) == m.read(control + 12, 4) == 0
    assert m.read(case.position + 15, 1) == 0xCC
    targets = [target for target, _ in case.events]
    assert targets[:6] == [0xA110, FORWARD, 0xD1, 0xD2, CLEANUP, CLEANUP]


def test_every_read_uses_current_stream_vptr_and_slot_with_held_position():
    case = Case()
    m = case.memory
    replacement = m.allocate(32)
    m.write(replacement + 24, 8, 0xA110)
    reads = []

    def read(address, width):
        reads.append((address, width))
        return case.context.read(address, width)

    context = ReplayTaskRebuildStorage(case.position, read, m.write)

    def hook(output, raw):
        m.write(case.stream, 8, replacement)

    case.forward_hook = hook
    # The bound wrappers use the same observed storage as the outer reader.
    bound = bind_replay_saved_position(
        context, case.lower, atomics=case.atomics, bind_local=m.bind_local
    )
    read_replay_saved_position(
        context,
        case.position,
        case.output,
        case.stream,
        calls=bound,
        atomics=case.atomics,
        bind_local=m.bind_local,
    )
    assert reads.count((case.stream, 8)) == 4
    assert reads.count((case.table + 24, 8)) == 1
    assert reads.count((replacement + 24, 8)) == 3
    assert case.source.position == 14


@pytest.mark.parametrize(
    ("phase", "detail"), [(0, 0x1432364D0), (1, 0x143236540), (2, 0x143236550), (3, 0x14323655C)]
)
def test_position_reaches_exact_source_metadata_and_line(phase, detail):
    case = Case()
    # Set raw status at the actual I/O boundary, before the caller checks it.
    original = case.lower
    seen = 0

    def call(target, args, data):
        nonlocal seen
        assert original.call is not None
        result = original.call(target, args, data)
        if target == 0xA110:
            if seen == phase:
                case.memory.write(args[1] + 24, 8, 7)
            seen += 1
        return result

    bound = bind_replay_saved_position(
        case.context,
        ReplayTaskRebuildCalls(call),
        atomics=case.atomics,
        bind_local=case.memory.bind_local,
    )
    assert bound.call is not None
    with pytest.raises(UnresolvedReplayTaskRebuild, match="diagnostic unavailable"):
        bound.call(0x140C29890, (case.position, case.output, case.stream), None)
    assert case.events[-1][0] == 0x140900ED0
    assert case.events[-1][1][1:] == (0x1432364E0, 0x10 + phase, detail)


def test_partial_output_initialization_keeps_input_cursor_and_first_store():
    case = Case()
    output = 0x1000
    case.memory.map_bytes(output, b"\xcc" * 16)
    captured = []

    @contextmanager
    def local(view):
        with case.memory.bind_local(view) as address:
            try:
                yield address
            finally:
                captured.append(bytes(view))

    with pytest.raises(ReplayMemoryError, match="unmapped"):
        read_replay_saved_byte(
            case.context,
            output,
            0,
            0,
            0,
            case.stream,
            case.position,
            calls=case.lower,
            atomics=case.atomics,
            bind_local=local,
        )
    assert case.source.position == 1
    assert case.memory.read_bytes(output, 16) == bytes(16)
    assert captured == [bytes(48)]  # No processed store before all three zeros.
    assert [target for target, _ in case.events] == [0xA110]


def test_missing_atomic_refuses_after_forward_before_vector_cleanup():
    case = Case()
    control = case.memory.allocate(16)
    case.memory.write(control + 8, 4, 1)

    def hook(output, raw):
        case.memory.write(raw + 32, 8, control)

    case.forward_hook = hook
    with pytest.raises(UnresolvedReplayTaskRebuild, match="atomic effect unavailable"):
        read_replay_saved_byte(
            case.context,
            case.output,
            0,
            0,
            0,
            case.stream,
            case.position,
            calls=case.lower,
            atomics=ReplayUnitAIMapAtomics(None, None),
            bind_local=case.memory.bind_local,
        )
    assert case.memory.read(control + 8, 4) == 1
    assert [target for target, _ in case.events] == [0xA110, FORWARD]


def test_actual_current_raw_empty_allocation_is_freed_after_forward():
    case = Case()
    m = case.memory
    allocation = m.allocate_aligned(32)
    m.map_bytes(0x143199DD0, (0x142D6BAB4).to_bytes(8, "little"))
    first = True

    def hook(output, raw):
        nonlocal first
        if first:
            first = False
            # Explicit forwarding callback mutation occurs after its empty
            # copy. Raw cleanup must inspect the changed current header.
            for offset, value in ((0, allocation), (8, allocation), (16, allocation + 32)):
                m.write(raw + offset, 8, value)

    case.forward_hook = hook
    assert case.position_read() == case.output
    with pytest.raises(ReplayMemoryError, match="unmapped"):
        m.read(allocation, 1)


@pytest.mark.parametrize("available", [0, 3, 4, 8, 12, 13])
def test_truncated_input_refuses_at_exact_next_read_with_previous_effects(available):
    case = Case()
    # Use a separate explicitly bounded owned stream without changing its
    # virtual method. No synthetic successful Result is supplied on truncation.
    source = ReplaySavedInput(bytes(range(available)))
    io = bind_replay_saved_input(
        case.context, case.lower, source, stream=case.stream, target=0xA110, result_bytes=bytes(48)
    )
    bound = bind_replay_saved_position(
        case.context, io, atomics=case.atomics, bind_local=case.memory.bind_local
    )
    assert bound.call is not None
    with pytest.raises(UnresolvedReplayTaskRebuild, match="exceeds remaining"):
        bound.call(0x140C29890, (case.position, case.output, case.stream), None)
    completed = min(available // 4 * 4, 12)
    assert source.position == completed
    assert case.memory.read_bytes(case.position, 16) == (
        bytes(range(completed)) + b"\xa5" * (16 - completed)
    )
    assert case.memory.read_bytes(case.output, 48) == b"\xa5" * 48


def test_partial_final_success_output_keeps_all_input_and_cleanup_effects():
    case = Case()
    output = 0x1000
    case.memory.map_bytes(output, b"\xcc" * 24)
    with pytest.raises(ReplayMemoryError, match="unmapped"):
        read_replay_saved_position(
            case.context,
            case.position,
            output,
            case.stream,
            calls=case.calls,
            atomics=case.atomics,
            bind_local=case.memory.bind_local,
        )
    assert case.source.position == 14
    assert case.memory.read_bytes(output, 24) == bytes(24)
    assert [target for target, _ in case.events].count(CLEANUP) == 8


def test_local_exit_true_cannot_turn_missing_forward_into_success():
    case = Case()
    case.forward_enabled = False

    class Suppressing:
        def __init__(self, view):
            self.actual = case.memory.bind_local(view)

        def __enter__(self):
            return self.actual.__enter__()

        def __exit__(self, kind, value, traceback):
            self.actual.__exit__(kind, value, traceback)
            return True

    with pytest.raises(UnresolvedReplayTaskRebuild, match="forward unavailable"):
        read_replay_saved_byte(
            case.context,
            case.output,
            0,
            0,
            0,
            case.stream,
            case.position,
            calls=case.lower,
            atomics=case.atomics,
            bind_local=Suppressing,
        )
    assert case.source.position == 1


@pytest.mark.parametrize(
    ("target", "args", "data"),
    [
        (0x140D07EE0, (1, 2, 3, 4, 5), None),
        (0x140B81E60, (1,) * 7, None),
        (0x140C29890, (1, 2), None),
        (0x140C29890, (1, 2, -1), None),
        (0x140D07EE0, (1,) * 6, memoryview(bytearray(1))),
    ],
)
def test_malformed_owned_binding_refuses_before_storage(target, args, data):
    def unavailable(*args):
        raise AssertionError("malformed call touched storage")

    calls = bind_replay_saved_position(
        ReplayTaskRebuildStorage(1, unavailable, unavailable),
        ReplayTaskRebuildCalls(None),
        atomics=ReplayUnitAIMapAtomics(None, None),
        bind_local=unavailable,
    )
    assert calls.call is not None
    with pytest.raises(ValueError):
        calls.call(target, args, data)


def test_unknown_dispatch_preserves_arguments_payload_and_return():
    case = Case()
    seen = []
    payload = memoryview(bytearray(b"kept"))

    def call(target, args, data):
        seen.append((target, args, data))
        return 0xCAFE

    calls = bind_replay_saved_position(
        case.context,
        ReplayTaskRebuildCalls(call),
        atomics=case.atomics,
        bind_local=case.memory.bind_local,
    )
    assert calls.call is not None
    assert calls.call(0xCA11, (2, 3), payload) == 0xCAFE
    assert seen == [(0xCA11, (2, 3), payload)]


@pytest.mark.parametrize("entry", [0x140B81D60, 0x140D94310])
def test_equivalent_stinger_wrapper_requires_forward_after_actual_four_byte_read(entry):
    case = Case()
    case.forward_enabled = False
    processed = []

    def observe(target, args, data):
        if target == FORWARD:
            processed.append(case.memory.read(args[1] + 40, 1))
        assert case.lower.call is not None
        return case.lower.call(target, args, data)

    case.calls = bind_replay_saved_position(
        case.context,
        ReplayTaskRebuildCalls(observe),
        atomics=case.atomics,
        bind_local=case.memory.bind_local,
    )
    with pytest.raises(UnresolvedReplayTaskRebuild, match="actual Result forward unavailable"):
        case.invoke(entry, case.output, 0x123, 0x100000001, 0x456, case.stream, case.position)
    assert case.source.position == 4
    assert case.memory.read_bytes(case.position, 4) == bytes(range(4))
    assert case.memory.read_bytes(case.output, 48) == bytes(48)
    assert processed == [1]
    with pytest.raises(ReplayMemoryError, match="unmapped"):
        case.memory.read(case.raw_results[0], 1)
    assert not any(target == CLEANUP for target, _ in case.events)
