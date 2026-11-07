"""Recorded reader source order with real cleanup and explicit I/O test contracts."""

from __future__ import annotations

from contextlib import contextmanager

import pytest

from vantage.replay_clock_storage import bind_replay_clock_storage
from vantage.replay_memory import ReplayMemory, ReplayMemoryError
from vantage.replay_recorded_position_reader import (
    ReplayRecordedPositionScratch,
    bind_replay_recorded_position_reader,
)
from vantage.replay_saved_result import bind_replay_saved_result
from vantage.replay_saved_string import bind_replay_saved_string
from vantage.replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
)
from vantage.replay_unit_ai_map import ReplayUnitAIMapAtomics
from vantage.replay_world_update_prelude import ReplayWorldUpdatePrelude
from vantage.replay_world_update_replay_phase import run_replay_world_update_replay_phase

READER, HEADER, TELL = 0x140DEC960, 0x140DF03C0, 0x140915F00
INPUT, SEEK, CLEAR = 0x140916DB0, 0x1409179E0, 0x1402BD7F0
U32 = 0xFFFFFFFF


class Rig:
    def __init__(self, *, active=1, header=0, counter=0, marker=3):
        self.memory = ReplayMemory()
        self.descriptor = self.memory.allocate(0xA0)
        self.stream = self.memory.allocate(0x48)
        self.outputs = tuple(self.memory.allocate(4) for _ in range(3))
        for address, width, value in (
            (self.descriptor + 1, 1, active),
            (self.descriptor + 0x48, 8, self.stream),
            (self.descriptor + 0x58, 1, counter),
            (self.descriptor + 0x5C, 4, header),
            (self.stream + 0x40, 8, 0x1234567887654321),
        ):
            self.memory.write(address, width, value)
        self.memory.map_bytes(0x143199DD0, (0x142D6BAB4).to_bytes(8, "little"))
        self.events, self.locals, self.active = [], [], []
        self.after_read, self.after_write, self.after_atomic = None, None, None
        self.inputs, self.before_inputs, self.before_clear = [], [], []
        self.words, self.word_index = [marker, 0x7FC12345, 0x80000000, 29], 0
        self.statuses, self.controls, self.seek_status = [], [], 0
        self.profile = ReplayRecordedPositionScratch(b"\xa5" * 0x58, b"\xb6" * 0x60)

        def read(address, width):
            self.events.append(("read", address, width))
            value = self.memory.read(address, width)
            if self.after_read is not None:
                self.after_read(address, width)
            return value

        def write(address, width, value):
            self.events.append(("write", address, width, value))
            self.memory.write(address, width, value)
            if self.after_write is not None:
                self.after_write(address, width, value)

        def atomic(address, delta):
            self.events.append(("atomic", address, delta))
            prior = self.memory.fetch_add_u32(address, delta)
            if self.after_atomic is not None:
                self.after_atomic(address, delta)
            return prior

        self.storage = ReplayTaskRebuildStorage(1, read, write)
        self.atomics = ReplayUnitAIMapAtomics(None, atomic)
        self.handlers = {
            INPUT: self.input,
            SEEK: self.seek,
            0xD1: lambda args: None,
            0xD2: lambda args: None,
        }
        runtime = self.memory.runtime_calls()

        def imported(target, args, data):
            self.events.append(("import", target, args))
            assert runtime.call is not None
            return runtime.call(target, args, data)

        def call(target, args, data):
            assert data is None
            self.events.append(("call", target, args))
            if target == CLEAR:
                self.before_clear.append((args[0], self.memory.read_bytes(args[0], 48)))
                if target not in self.handlers:
                    return self.result_binding.call(target, args, data)
            if target not in self.handlers:
                raise UnresolvedReplayTaskRebuild(f"actual test child{target:x} unavailable")
            return self.handlers[target](args)

        self.calls = ReplayTaskRebuildCalls(call)
        terminal = ReplayTaskRebuildCalls(imported)
        strings = bind_replay_saved_string(self.storage, self.calls, imports=terminal)
        self.result_binding = bind_replay_saved_result(
            self.storage,
            strings,
            atomics=self.atomics,
            imports=terminal,
        )
        self.bind()

    @contextmanager
    def bind_local(self, view):
        with self.memory.bind_local(view) as address:
            self.locals.append((address, len(view), bytes(view)))
            self.active.append(address)
            self.events.append(("map", address, len(view)))
            try:
                yield address
            finally:
                self.events.append(("unmap", address, len(view)))
                self.active.remove(address)

    def bind(self, *, atomics=None):
        self.bound = bind_replay_recorded_position_reader(
            self.storage,
            self.calls,
            atomics=self.atomics if atomics is None else atomics,
            bind_local=self.bind_local,
            scratch=self.profile,
        )

    def write_result(self, result, *, status=0, control=0, begin=0, end=0, capacity=0):
        raw = bytearray(b"\xd7" * 48)
        for offset, value in ((0, begin), (8, end), (16, capacity), (24, status), (32, control)):
            raw[offset : offset + 8] = value.to_bytes(8, "little")
        self.memory.write_bytes(result, bytes(raw))

    def input(self, args):
        _stream, result, destination, count = args
        self.before_inputs.append(self.memory.read_bytes(result, 48))
        index = len(self.inputs)
        self.inputs.append(args)
        if count == 1:
            word = self.memory.read(self.descriptor + 0x58, 1)
        else:
            word = self.words[self.word_index]
            self.word_index += 1
        self.memory.write(destination, count, word)
        status = self.statuses[index] if index < len(self.statuses) else 0
        control = self.controls[index] if index < len(self.controls) else 0
        self.write_result(result, status=status, control=control)
        return None  # Ordinary Input's RAX is not consumed by either caller.

    def seek(self, args):
        self.write_result(args[1], status=self.seek_status)
        return args[1]

    def control(self, strong=1, weak=1):
        pointer, table = self.memory.allocate(16), self.memory.allocate(16)
        for address, width, value in (
            (pointer, 8, table),
            (pointer + 8, 4, strong),
            (pointer + 12, 4, weak),
            (table, 8, 0xD1),
            (table + 8, 8, 0xD2),
        ):
            self.memory.write(address, width, value)
        return pointer

    def invoke(self, target=READER, args=None):
        if args is None:
            args = (self.descriptor, *self.outputs) if target == READER else (self.descriptor,)
        assert self.bound.call is not None
        return self.bound.call(target, args, None)

    def calls_to(self, target):
        return [e[2] for e in self.events if e[0] == "call" and e[1] == target]

    def assert_locals_expired(self):
        assert not self.active
        for address, _, _ in self.locals:
            with pytest.raises(ReplayMemoryError, match="unmapped"):
                self.memory.read(address, 1)


@pytest.mark.parametrize(
    ("target", "field", "width", "expected"),
    [
        (READER, 1, 1, 6),
        (HEADER, 0x5C, 4, 1),
    ],
)
def test_inactive_leaf_has_one_read_no_mapping_or_io(target, field, width, expected):
    rig = Rig(active=0, header=0)
    assert rig.invoke(target) == expected
    assert rig.events == [("read", rig.descriptor + field, width)]


def test_tell_reads_current_full_qword_without_io_and_wraps_effective_address():
    rig = Rig()
    assert rig.invoke(TELL, (rig.stream,)) == 0x1234567887654321
    rig.memory.map_bytes(0, (0xFEDCBA9876543210).to_bytes(8, "little"))
    assert rig.invoke(TELL, ((1 << 64) - 0x40,)) == 0xFEDCBA9876543210
    assert rig.events == [("read", rig.stream + 0x40, 8), ("read", 0, 8)]


def test_success_reads_exact_output_order_with_shared_result_and_original_padding():
    rig = Rig()
    original = rig.handlers[INPUT]

    def input(args):
        if not rig.inputs:
            frame = rig.locals[0][0]
            expected = bytearray(b"\xa5" * 0x58)
            expected[0x50:0x54] = b"\xff" * 4
            assert rig.memory.read_bytes(frame, 0x58) == bytes(expected)
        return original(args)

    rig.handlers[INPUT] = input
    assert rig.invoke() == 1
    frame, size, seed = rig.locals[0]
    assert (size, seed) == (0x58, b"\xa5" * 0x58)
    result = frame + 0x20
    assert rig.inputs == [(rig.stream, result, frame + 0x50, 4)] + [
        (rig.stream, result, output, 4) for output in rig.outputs
    ]
    assert rig.before_inputs[0] == b"\xa5" * 48
    assert all(raw[40:] == b"\x01" + b"\xd7" * 7 for raw in rig.before_inputs[1:])
    assert [rig.memory.read(out, 4) for out in rig.outputs] == [0x7FC12345, 0x80000000, 29]
    assert rig.calls_to(CLEAR) == [(result,)] * 4
    # Apart from child I/O, only marker and processed-byte stores occur.
    writes = [e for e in rig.events if e[0] == "write"]
    assert writes == [("write", frame + 0x50, 4, U32)] + [("write", result + 40, 1, 1)] * 4
    rig.assert_locals_expired()


def test_tell_stream_is_held_before_marker_store_but_input_stream_is_refreshed():
    rig = Rig(marker=5)
    other = rig.memory.allocate(0x48)
    rig.memory.write(other + 0x40, 8, 0x1111222233334444)

    def store(address, width, value):
        if width == 4 and value == U32:
            rig.memory.write(rig.descriptor + 0x48, 8, other)

    rig.after_write = store
    assert rig.invoke() == 4
    assert rig.inputs[0][0] == other
    assert rig.calls_to(SEEK) == [(other, rig.inputs[0][1], 0x1234567887654321)]
    assert ("read", rig.stream + 0x40, 8) in rig.events
    assert ("read", other + 0x40, 8) not in rig.events


@pytest.mark.parametrize("failure", [0, 1, 2, 3])
def test_failure_at_each_read_cleans_current_result_preserves_output_prefix(failure):
    rig = Rig()
    rig.statuses = [0] * failure + [0x8000000000000000]
    assert rig.invoke() == U32
    assert len(rig.inputs) == failure + 1
    assert len(rig.calls_to(CLEAR)) == failure + 1
    # Failed read may already have written its output; no rollback is invented.
    for index, out in enumerate(rig.outputs):
        if index < failure:
            assert rig.memory.read(out, 4) == [0x7FC12345, 0x80000000, 29][index]
        else:
            with pytest.raises(ReplayMemoryError, match="undefined"):
                rig.memory.read(out, 4)
    assert not rig.calls_to(SEEK)
    rig.assert_locals_expired()


@pytest.mark.parametrize(
    ("strong", "weak", "targets"),
    [
        (0, 1, []),
        (2, 1, []),
        (1, 0, [0xD1]),
        (1, 2, [0xD1]),
        (1, 1, [0xD1, 0xD2]),
    ],
)
def test_inline_strong_weak_release_uses_atomic_prior_words_before_clear(strong, weak, targets):
    rig = Rig()
    control = rig.control(strong, weak)
    rig.controls, rig.statuses = [control], [1]
    assert rig.invoke() == U32
    sequence = [e[1] for e in rig.events if e[0] == "call" and e[1] in (0xD1, 0xD2, CLEAR)]
    assert sequence == [*targets, CLEAR]
    assert rig.memory.read(control + 8, 4) == (strong - 1) & U32
    assert rig.memory.read(control + 12, 4) == ((weak - 1) & U32 if strong == 1 else weak)
    result = rig.inputs[0][1]
    assert rig.events.index(("write", result + 40, 1, 1)) < rig.events.index(
        ("atomic", control + 8, U32)
    )


def test_control_is_held_before_status_read_and_processed_mutations_and_weak_vptr_is_current():
    rig = Rig()
    held, other, replacement = rig.control(), rig.control(), rig.memory.allocate(16)
    rig.memory.write(replacement + 8, 8, 0xD3)
    rig.controls, rig.statuses = [held], [7]

    def read(address, width):
        if rig.inputs and address == rig.inputs[0][1] + 32:
            rig.memory.write(address, 8, other)
            rig.memory.write(rig.inputs[0][1] + 24, 8, 0)

    def store(address, width, value):
        if rig.inputs and address == rig.inputs[0][1] + 40:
            rig.memory.write(rig.inputs[0][1] + 24, 8, 999)

    def destroy(args):
        assert args == (held,)
        rig.memory.write(held, 8, replacement)

    rig.after_read, rig.after_write = read, store
    rig.handlers[0xD1], rig.handlers[0xD3] = destroy, lambda args: None
    assert rig.invoke() == 1  # Held status was0 before processed mutation999.
    assert rig.calls_to(0xD1) == [(held,)] and rig.calls_to(0xD3) == [(held,)]
    assert rig.memory.read(other + 8, 4) == 1
    first = rig.inputs[0][1]
    selected = [e for e in rig.events if e[0] == "read" and e[1] in (first + 32, first + 24)]
    assert selected[:2] == [("read", first + 32, 8), ("read", first + 24, 8)]


@pytest.mark.parametrize("initial", [0, 1])
def test_status_is_held_across_actual_vector_cleanup_but_marker_is_current(initial):
    rig = Rig(marker=9)
    rig.statuses = [initial]

    def cleanup(args):
        result = args[0]
        rig.memory.write(result + 24, 8, 0 if initial else 1)
        rig.memory.write(result + 48, 4, 3)
        return rig.result_binding.call(CLEAR, args, None)

    rig.handlers[CLEAR] = cleanup
    assert rig.invoke() == (U32 if initial else 1)
    assert not rig.calls_to(SEEK)
    assert len(rig.inputs) == (1 if initial else 4)


def test_real_nonempty_result_strings_free_after_release_and_before_later_inputs():
    rig = Rig()
    control = rig.control()
    vector, data = rig.memory.allocate_aligned(32), rig.memory.allocate_aligned(24)
    for offset, value in ((0, data), (16, 20), (24, 23)):
        rig.memory.write(vector + offset, 8, value)
    original = rig.handlers[INPUT]

    def input(args):
        value = original(args)
        if len(rig.inputs) == 1:
            rig.write_result(
                args[1], control=control, begin=vector, end=vector + 32, capacity=vector + 32
            )
        return value

    rig.handlers[INPUT] = input
    assert rig.invoke() == 1
    frees = [e for e in rig.events if e[0] == "import"]
    assert frees == [("import", 0x142D6BAB4, (data, 24)), ("import", 0x142D6BAB4, (vector, 32))]
    assert rig.events.index(("call", 0xD2, (control,))) < rig.events.index(frees[0])
    assert rig.events.index(frees[-1]) < rig.events.index(("call", INPUT, rig.inputs[1]))
    for pointer in (data, vector):
        with pytest.raises(ReplayMemoryError, match="unmapped"):
            rig.memory.read(pointer, 1)
    assert rig.before_inputs[1][:24] == bytes(24)


@pytest.mark.parametrize("status", [0, 0x100000000])
def test_seek_reads_returned_status_and_marks_returned_object_but_releases_fixed_control(status):
    rig = Rig(marker=2)
    returned, control, other = rig.memory.allocate(48), rig.control(), rig.control()
    rig.write_result(returned, status=status, control=other)
    fixed = None

    def seek(args):
        nonlocal fixed
        fixed = args[1]
        rig.write_result(fixed, status=999, control=other)
        return returned

    def store(address, width, value):
        if address == returned + 40:
            rig.memory.write(fixed + 32, 8, control)
            rig.memory.write(returned + 24, 8, 0 if status else 123)

    rig.handlers[SEEK], rig.after_write = seek, store
    assert rig.invoke() == (U32 if status else 4)
    assert rig.calls_to(0xD1) == [(control,)]
    assert rig.calls_to(CLEAR) == [(fixed,), (fixed,)]
    assert rig.memory.read(returned + 40, 1) == 1
    assert rig.memory.read(other + 8, 4) == 1
    seek_event = ("call", SEEK, (rig.stream, fixed, 0x1234567887654321))
    after = rig.events[rig.events.index(seek_event) + 1 :]
    reads = [e for e in after if e[0] == "read"]
    assert reads[:2] == [("read", returned + 24, 8), ("read", fixed + 32, 8)]
    assert ("read", fixed + 24, 8) not in reads
    rig.assert_locals_expired()


def test_input_incidental_alternate_rax_is_ignored_without_reading_it():
    rig = Rig()
    original = rig.handlers[INPUT]

    def input(args):
        original(args)
        return 0xDEADBEEF  # Intentionally unbacked and not an output Result.

    rig.handlers[INPUT] = input
    assert rig.invoke() == 1
    assert all(e[1] != 0xDEADBEEF + 24 for e in rig.events if e[0] == "read")


@pytest.mark.parametrize(("counter", "header", "expected"), [(255, 255, 1), (7, 1, 1)])
def test_active_header_wrap_and_nested_reader_mapping_stay_live(counter, header, expected):
    rig = Rig(header=header, counter=counter)
    original = rig.handlers[INPUT]

    def input(args):
        if args[3] == 1:
            assert len(rig.active) == 2
            outer, inner = rig.locals
            assert outer[1:] == (0x58, b"\xa5" * 0x58)
            assert inner[1:] == (0x60, b"\xb6" * 0x60)
            assert args[1:3] == (inner[0] + 0x28, inner[0] + 0x58)
            assert rig.memory.read_bytes(args[1], 48) == b"\xb6" * 48
            assert rig.memory.read_bytes(inner[0] + 0x58, 8) == b"\xb6" * 8
            assert rig.memory.read(outer[0] + 0x50, 4) == 3
            assert rig.memory.read(rig.descriptor + 0x58, 1) == (counter + 1) & 255
        return original(args)

    rig.handlers[INPUT] = input
    assert rig.invoke() == expected
    assert [args[3] for args in rig.inputs] == [4, 1, 4, 4, 4]
    assert rig.memory.read(rig.descriptor + 0x58, 1) == (counter + 1) & 255
    rig.assert_locals_expired()


@pytest.mark.parametrize(("status", "mismatch", "expected"), [(0, True, 2), (1, False, U32)])
def test_non_one_header_result_propagates_without_coordinate_reads(status, mismatch, expected):
    rig = Rig(header=1, counter=5)
    rig.statuses = [0, status]
    original = rig.handlers[INPUT]

    def input(args):
        result = original(args)
        if args[3] == 1 and mismatch:
            rig.memory.write(args[2], 1, 77)
        return result

    rig.handlers[INPUT] = input
    assert rig.invoke() == expected
    assert len(rig.inputs) == len(rig.calls_to(CLEAR)) == 2
    rig.assert_locals_expired()


def test_header_compares_current_counter_then_current_marker_after_cleanup():
    rig = Rig(header=1, counter=8)
    result = None

    def cleanup(args):
        nonlocal result
        result = args[0]
        rig.memory.write(rig.descriptor + 0x58, 1, 77)
        rig.memory.write(result + 48, 1, 0)
        return rig.result_binding.call(CLEAR, args, None)

    def read(address, width):
        if result is not None and address == rig.descriptor + 0x58:
            rig.memory.write(address, 1, 99)
            rig.memory.write(result + 48, 1, 77)

    rig.handlers[CLEAR], rig.after_read = cleanup, read
    assert rig.invoke(HEADER) == 1  # Counter77 held before marker77/currentcounter99.
    assert rig.memory.read(rig.descriptor + 0x58, 1) == 99


def test_each_input_reloads_stream_and_aliased_outputs_follow_sequential_writes():
    rig = Rig()
    streams = [rig.memory.allocate(0x48) for _ in range(4)]

    def cleanup(args):
        rig.memory.write(rig.descriptor + 0x48, 8, streams[len(rig.inputs) - 1])
        return rig.result_binding.call(CLEAR, args, None)

    rig.handlers[CLEAR] = cleanup
    output = rig.outputs[0]
    assert rig.invoke(args=(rig.descriptor, output, output, output)) == 1
    assert [args[0] for args in rig.inputs] == [rig.stream, *streams[:3]]
    assert rig.memory.read(output, 4) == 29


def test_world_replay_phase_composes_actual_reader_and_clock_with_shared_output_homes():
    rig = Rig(header=1, counter=255)
    world, frame, clock = (rig.memory.allocate(n) for n in (0x900, 0x2B8, 0x1C))
    rig.memory.write_bytes(frame, b"\x93" * 0x2B8)
    rig.memory.map_bytes(0x1431B7520, (0xBF800000).to_bytes(4, "little"))
    for address, width, value in (
        (world + 0x70, 8, 0x123400),
        (world + 0x228, 8, clock),
        (world + 0x130, 8, 0x567800),
        (world + 0x78, 4, 999),
        (world + 0x7C, 4, 777),
        (world + 0x88, 4, 5),
        (rig.descriptor, 1, 0),
        (rig.descriptor + 0x94, 4, 17),
        (rig.descriptor + 0x6C, 4, 0),
    ):
        rig.memory.write(address, width, value)
    resets = []

    def call(target, args, data):
        if target == 0x140E15770:
            assert args == (0x123400,)
            return rig.descriptor
        if target == 0x140F55400:
            resets.append(args)  # Explicit authored manager test contract.
            return None
        if target in (0x140E68F70, 0x140E68FA0):
            return clocks.call(target, args, data)
        return rig.bound.call(target, args, data)

    calls = ReplayTaskRebuildCalls(call)
    clocks = bind_replay_clock_storage(rig.storage, calls, mxcsr=0x1F80)
    prelude = ReplayWorldUpdatePrelude(world, frame, 1000, 13, 1, 0x141628F0C, None)
    result = run_replay_world_update_replay_phase(rig.storage, calls, prelude)
    assert (result.next_address, result.returned_status) == (0x14162951F, None)
    assert resets == [(0x567800, U32, U32, 0xBF800000, 0xBF800000)]
    assert [rig.memory.read(frame + offset, 4) for offset in (0x200, 0x210, 0x270)] == [
        0x7FC12345,
        0x80000000,
        29,
    ]
    assert rig.memory.read(clock + 0x18, 4) == 1017
    assert rig.memory.read(world + 0x7C, 4) == 17 and rig.memory.read(world + 0x88, 4) == 5
    assert len(rig.inputs) == len(rig.calls_to(CLEAR)) == 5
    rig.assert_locals_expired()


@pytest.mark.parametrize("missing", [INPUT, SEEK, CLEAR, 0xD1, 0xD2])
def test_missing_actual_child_keeps_prefix_and_expires_locals(missing):
    rig = Rig(marker=2 if missing == SEEK else 3)
    if missing in (0xD1, 0xD2):
        rig.controls = [rig.control()]
    if missing == CLEAR:
        rig.handlers[CLEAR] = lambda args: (_ for _ in ()).throw(
            UnresolvedReplayTaskRebuild("actual test child1402bd7f0 unavailable")
        )
    else:
        rig.handlers.pop(missing)
    with pytest.raises(UnresolvedReplayTaskRebuild, match=f"{missing:x}"):
        rig.invoke()
    assert rig.calls_to(missing)
    if missing != INPUT:
        assert rig.before_clear or missing in (0xD1, 0xD2)
    rig.assert_locals_expired()


def test_missing_atomic_stops_after_processed_store_without_clear():
    rig = Rig()
    control = rig.control()
    rig.controls = [control]
    rig.bind(atomics=ReplayUnitAIMapAtomics(None, None))
    with pytest.raises(UnresolvedReplayTaskRebuild, match="atomic effect unavailable"):
        rig.invoke()
    assert not rig.calls_to(CLEAR)
    assert ("write", rig.inputs[0][1] + 40, 1, 1) in rig.events
    assert rig.memory.read(control + 8, 4) == 1
    rig.assert_locals_expired()


@pytest.mark.parametrize(("entry", "arity"), [(READER, 4), (HEADER, 1), (TELL, 1)])
@pytest.mark.parametrize("bad", [True, -1, 1 << 64, None])
def test_bad_known_abi_refuses_before_storage_or_mapping(entry, arity, bad):
    rig = Rig()
    with pytest.raises(ValueError):
        rig.invoke(entry, (bad,) + (0,) * (arity - 1))
    assert not rig.events
    with pytest.raises(ValueError):
        rig.bound.call(entry, (0,) * arity, memoryview(bytearray(1)))
    with pytest.raises(ValueError):
        rig.invoke(entry, (0,) * (arity + 1))
    assert not rig.events


@pytest.mark.parametrize("bad", [b"", bytes(0x57), bytearray(0x58), None])
def test_scratch_requires_exact_immutable_reader_and_header_seeds(bad):
    with pytest.raises(ValueError):
        ReplayRecordedPositionScratch(bad, bytes(0x60))
    with pytest.raises(ValueError):
        ReplayRecordedPositionScratch(bytes(0x58), bad)


def test_unknown_delegation_preserves_all_object_identities_and_missing_delegate_refuses():
    rig = Rig()
    args, data, returned = (object(),), memoryview(bytearray(1)), object()
    seen = []

    def call(target, actual_args, actual_data):
        seen.append((target, actual_args, actual_data))
        return returned

    lower = ReplayTaskRebuildCalls(call)
    bound = bind_replay_recorded_position_reader(
        rig.storage,
        lower,
        atomics=rig.atomics,
        bind_local=rig.bind_local,
        scratch=rig.profile,
    )
    assert bound.call(0x9876543210, args, data) is returned
    assert seen[0][1] is args and seen[0][2] is data
    none = bind_replay_recorded_position_reader(
        rig.storage,
        ReplayTaskRebuildCalls(None),
        atomics=rig.atomics,
        bind_local=rig.bind_local,
        scratch=rig.profile,
    )
    with pytest.raises(UnresolvedReplayTaskRebuild, match="9876543210"):
        none.call(0x9876543210, args, data)
    assert not rig.events
