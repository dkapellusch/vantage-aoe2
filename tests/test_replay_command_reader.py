"""Source-derived command reader/queue controls; children have explicit test ABIs."""

from __future__ import annotations

from contextlib import contextmanager

import pytest

from vantage.replay_command_reader import (
    ReplayCommandReaderProfile,
    bind_replay_command_reader,
)
from vantage.replay_file_backend import (
    ReplayFileBackendProfile,
    bind_replay_file_backend_homes,
)
from vantage.replay_file_read import ReplayFileReadProfile, bind_replay_file_read
from vantage.replay_file_support import ReplayFileSupportProfile, bind_replay_file_support
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

READER, POLL, QUEUE = 0x140DEC2C0, 0x140E15C00, 0x140F51FC0
RELEASE, DONE = 0x140E0E0D0, 0x140E085A0
FIRST, TIMED, CLOCK, GAME, WORLD = (
    0x140E62B90,
    0x140E62A10,
    0x140E68F80,
    0x140D6AD50,
    0x1416041F0,
)
INPUT, SEEK, CLEAR, HEADER, TELL = (
    0x140916DB0,
    0x1409179E0,
    0x1402BD7F0,
    0x140DF03C0,
    0x140915F00,
)
STOP, DISPATCH, VECTOR = 0x140DF2670, 0x140A8FB50, 0x140A8E1A0
WRITER, ABORT, LOGGER = 0x140DEE940, 0x140DF2240, 0x14101ADB0
MALLOC, FREE, U32 = 0x142D6BA78, 0x142D6BAB4, 0xFFFFFFFF


class Rig:
    def __init__(self, *, active=1, marker=1, payload=b"\x7fabcde"):
        self.memory = ReplayMemory()
        self.descriptor = self.memory.allocate(0x140)
        self.stream = self.memory.allocate(0x48)
        self.pointer, self.count = self.memory.allocate(8), self.memory.allocate(4)
        self.manager = self.memory.allocate(0x3A0)
        for address, width, value in (
            (self.descriptor, 1, 0),
            (self.descriptor + 1, 1, active),
            (self.descriptor + 0x48, 8, self.stream),
            (self.stream + 0x40, 8, 0x1234567887654321),
            (self.pointer, 8, 0x1122334455667788),
            (self.count, 4, 0xAABBCCDD),
            (self.manager + 0x318, 4, 10),
            (self.manager + 0x398, 8, self.descriptor),
        ):
            self.memory.write(address, width, value)
        self.memory.map_bytes(0x143199DB0, MALLOC.to_bytes(8, "little"))
        self.memory.map_bytes(0x143199DD0, FREE.to_bytes(8, "little"))
        self.memory.map_bytes(0x144355062, b"\0")
        self.events, self.locals, self.active = [], [], []
        self.after_read, self.after_write, self.after_atomic = None, None, None
        self.marker, self.payload, self.input_index = marker, payload, 0
        self.statuses, self.controls, self.inputs = [], [], []
        self.header_result, self.seek_status = 1, 0
        self.clear_hook, self.input_hook = None, None
        self.profile = ReplayCommandReaderProfile(
            b"\xa5" * 0x58,
            b"\xb6" * 0x50,
            b"\xc7" * 0x90,
        )

        def read(address, width):
            self.events.append(("read", address, width))
            value = self.memory.read(address, width)
            if self.after_read:
                self.after_read(address, width)
            return value

        def write(address, width, value):
            self.events.append(("write", address, width, value))
            self.memory.write(address, width, value)
            if self.after_write:
                self.after_write(address, width, value)

        def atomic(address, delta):
            self.events.append(("atomic", address, delta))
            prior = self.memory.fetch_add_u32(address, delta)
            if self.after_atomic:
                self.after_atomic(address, delta)
            return prior

        self.storage = ReplayTaskRebuildStorage(1, read, write)
        self.atomics = ReplayUnitAIMapAtomics(None, atomic)
        self.handlers = {
            INPUT: self.input,
            SEEK: self.seek,
            HEADER: lambda args: self.header_result,
            TELL: lambda args: self.storage.read(args[0] + 0x40, 8),
        }
        self.import_handlers, self.home_handler = {}, None
        runtime = self.memory.runtime_calls()

        def imported(target, args, data):
            self.events.append(("import", target, args))
            if target in self.import_handlers:
                return self.import_handlers[target](args)
            return runtime.call(target, args, data)

        def call(target, args, data):
            self.events.append(("call", target, args))
            assert data is None
            if target in (CLEAR, 0x1402BD890):
                if self.clear_hook:
                    self.clear_hook(args[0])
                return self.results.call(target, args, data)
            if target not in self.handlers:
                raise UnresolvedReplayTaskRebuild(f"actual test child{target:x} unavailable")
            return self.handlers[target](args)

        def home(target, args, data):
            self.events.append(("home", target, args))
            if self.home_handler:
                return self.home_handler(target, args, data)
            raise UnresolvedReplayTaskRebuild("actual test logger unavailable")

        self.calls, self.imports = ReplayTaskRebuildCalls(call), ReplayTaskRebuildCalls(imported)
        self.home_calls = ReplayTaskRebuildCalls(home)
        strings = bind_replay_saved_string(self.storage, self.calls, imports=self.imports)
        self.results = bind_replay_saved_result(
            self.storage,
            strings,
            atomics=self.atomics,
            imports=self.imports,
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
        self.bound = bind_replay_command_reader(
            self.storage,
            self.calls,
            imports=self.imports,
            logger_home_calls=self.home_calls,
            atomics=self.atomics if atomics is None else atomics,
            bind_local=self.bind_local,
            profile=self.profile,
        )

    def result(self, address, *, status=0, control=0):
        raw = bytearray(b"\xd8" * 48)
        for offset, value in ((0, 0), (8, 0), (16, 0), (24, status), (32, control)):
            raw[offset : offset + 8] = value.to_bytes(8, "little")
        self.memory.write_bytes(address, bytes(raw))

    def input(self, args):
        index = self.input_index
        self.input_index += 1
        self.inputs.append(args)
        if self.input_hook:
            self.input_hook(index, args)
        else:
            raw = (
                self.marker.to_bytes(4, "little"),
                len(self.payload).to_bytes(4, "little"),
                self.payload,
                b"\x99\x88\x77\x66",
            )[index]
            assert len(raw) == args[3]
            self.memory.write_bytes(args[2], raw)
        self.result(
            args[1],
            status=self.statuses[index] if index < len(self.statuses) else 0,
            control=self.controls[index] if index < len(self.controls) else 0,
        )
        return None

    def seek(self, args):
        self.result(args[1], status=self.seek_status)
        return args[1]

    def invoke(self, target=READER, args=None):
        if args is None:
            args = (self.descriptor, self.pointer, self.count)
        return self.bound.call(target, args, None)

    def calls_to(self, target, *, channel="call"):
        return [e[2] for e in self.events if e[0] == channel and e[1] == target]

    def control(self, strong=1, weak=1):
        obj, table = self.memory.allocate(16), self.memory.allocate(16)
        for address, width, value in (
            (obj, 8, table),
            (obj + 8, 4, strong),
            (obj + 12, 4, weak),
            (table, 8, 0xD1),
            (table + 8, 8, 0xD2),
        ):
            self.memory.write(address, width, value)
        self.handlers[0xD1], self.handlers[0xD2] = lambda args: None, lambda args: None
        return obj

    def ring(self, rows, *, manager=None):
        manager = self.manager if manager is None else manager
        start = self.memory.allocate(max(1, 32 * len(rows)))
        self.memory.write_bytes(start, bytes(max(1, 32 * len(rows))))
        for index, (pointer, priority, time, tie, count, active) in enumerate(rows):
            row = start + index * 32
            for offset, width, value in (
                (0, 8, pointer),
                (8, 4, priority),
                (16, 4, time),
                (20, 4, tie),
                (24, 4, count),
                (28, 1, active),
            ):
                self.memory.write(row + offset, width, value)
        self.memory.write(manager + 0x360, 8, start)
        self.memory.write(manager + 0x368, 8, start + len(rows) * 32)
        return start

    def expired(self):
        assert not self.active
        for address, _, _ in self.locals:
            with pytest.raises(ReplayMemoryError, match="unmapped"):
                self.memory.read(address, 1)


def test_inactive_reader_does_not_map_or_touch_outputs():
    rig = Rig(active=0)
    assert rig.invoke() == 6
    assert rig.events == [("read", rig.descriptor + 1, 1)]
    assert rig.memory.read(rig.pointer, 8) == 0x1122334455667788
    assert rig.memory.read(rig.count, 4) == 0xAABBCCDD


def test_success_retains_padding_and_reads_count_payload_ignored_tail_in_order():
    rig = Rig()
    assert rig.invoke() == 1
    frame, length, seed = rig.locals[0]
    assert (length, seed) == (0x58, b"\xa5" * 0x58)
    pointer = rig.memory.read(rig.pointer, 8)
    assert rig.memory.read_bytes(pointer, len(rig.payload)) == rig.payload
    assert rig.memory.read(rig.count, 4) == len(rig.payload)
    assert rig.inputs == [
        (rig.stream, frame + 0x20, frame + 0x50, 4),
        (rig.stream, frame + 0x20, rig.count, 4),
        (rig.stream, frame + 0x20, pointer, len(rig.payload)),
        (rig.stream, frame + 0x20, frame + 0x54, 4),
    ]
    assert rig.calls_to(MALLOC, channel="import") == [(len(rig.payload),)]
    assert rig.calls_to(CLEAR) == [(frame + 0x20,)] * 4
    rig.expired()


@pytest.mark.parametrize(
    ("failure", "freed", "count_changed"),
    [
        (0, False, False),
        (1, False, True),
        (2, True, True),
        (3, True, True),
    ],
)
def test_failure_preserves_reached_partial_effects_and_only_payload_or_tail_frees(
    failure,
    freed,
    count_changed,
):
    rig = Rig()
    rig.statuses = [0] * failure + [1 << 63]
    assert rig.invoke() == U32
    assert len(rig.inputs) == failure + 1
    frees = rig.calls_to(FREE, channel="import")
    assert bool(frees) == freed
    assert rig.memory.read(rig.pointer, 8) == (0 if freed else 0x1122334455667788)
    assert rig.memory.read(rig.count, 4) == (len(rig.payload) if count_changed else 0xAABBCCDD)
    if freed:
        with pytest.raises(ReplayMemoryError, match="unmapped"):
            rig.memory.read(frees[0][0], 1)
    rig.expired()


@pytest.mark.parametrize("marker", [6, 0xFFFFFFFF])
def test_initial_marker_six_is_failure_but_other_operations_seek_and_clear_pointer(marker):
    rig = Rig(marker=marker)
    expected = U32 if marker == 6 else 4
    assert rig.invoke() == expected
    assert len(rig.inputs) == 1
    assert len(rig.calls_to(SEEK)) == (0 if marker == 6 else 1)
    assert rig.memory.read(rig.pointer, 8) == (0x1122334455667788 if marker == 6 else 0)


def test_initial_processed_precedes_status_and_control_and_held_failure_survives_cleanup():
    rig = Rig()
    control = rig.control()
    other = rig.control()
    rig.controls = [other]

    def write(address, width, value):
        if rig.inputs and address == rig.inputs[0][1] + 40:
            rig.memory.write(address - 16, 8, 7)
            rig.memory.write(address - 8, 8, control)

    def clear(result):
        rig.memory.write(result + 24, 8, 0)
        rig.memory.write(result + 48, 4, 1)

    rig.after_write, rig.clear_hook = write, clear
    assert rig.invoke() == U32
    assert rig.calls_to(0xD1) == [(control,)]
    assert rig.memory.read(other + 8, 4) == 1
    frame = rig.locals[0][0]
    selected = [
        e
        for e in rig.events
        if e[0] in ("write", "read") and e[1] in (frame + 0x48, frame + 0x38, frame + 0x40)
    ]
    assert selected[:3] == [
        ("write", frame + 0x48, 1, 1),
        ("read", frame + 0x38, 8),
        ("read", frame + 0x40, 8),
    ]


def test_initial_operation_is_reread_after_real_vector_cleanup():
    rig = Rig(marker=7)

    def clear(result):
        rig.memory.write(result + 48, 4, 1)

    rig.clear_hook = clear
    assert rig.invoke() == 1
    assert not rig.calls_to(SEEK)


@pytest.mark.parametrize("status", [0, 1 << 32])
def test_seek_uses_returned_status_and_processed_with_fixed_control_cleanup(status):
    rig = Rig(marker=3)
    other, control = rig.memory.allocate(48), rig.control()
    rig.result(other, status=status)

    def seek(args):
        rig.result(args[1], status=123, control=control)
        return other

    rig.handlers[SEEK] = seek
    assert rig.invoke() == (U32 if status else 4)
    assert rig.memory.read(other + 40, 1) == 1
    assert rig.calls_to(0xD1) == [(control,)]
    assert rig.calls_to(CLEAR)[-1] == (rig.locals[0][0] + 0x20,)
    assert rig.memory.read(rig.pointer, 8) == (0x1122334455667788 if status else 0)


@pytest.mark.parametrize("value", [0, 2, 0xFFFFFFFF])
def test_non_one_header_is_forwarded_without_count_allocation_or_output_reset(value):
    rig = Rig()
    rig.header_result = value
    assert rig.invoke() == value
    assert len(rig.inputs) == 1
    assert not rig.calls_to(MALLOC, channel="import")
    assert rig.memory.read(rig.pointer, 8) == 0x1122334455667788


def test_malloc_publication_can_mutate_count_but_payload_keeps_actual_allocation():
    rig = Rig()
    allocation = rig.memory.allocate(32)
    other = rig.memory.allocate(32)
    rig.import_handlers[MALLOC] = lambda args: allocation
    original = rig.input

    def input(args):
        if rig.input_index == 2:
            assert args[2:] == (allocation, 3)
            rig.memory.write_bytes(args[2], b"xyz")
            rig.input_index += 1
            rig.inputs.append(args)
            rig.result(args[1])
            return None
        return original(args)

    def write(address, width, value):
        if address == rig.pointer and value == allocation:
            rig.memory.write(rig.pointer, 8, other)
            rig.memory.write(rig.count, 4, 3)

    rig.handlers[INPUT], rig.after_write = input, write
    assert rig.invoke() == 1
    assert rig.memory.read_bytes(allocation, 3) == b"xyz"
    assert rig.memory.read(rig.pointer, 8) == other
    assert rig.calls_to(MALLOC, channel="import") == [(len(rig.payload),)]


@pytest.mark.parametrize("count", [0, 344, 0xFFFFFFFF])
def test_native_count_is_not_capped_and_null_malloc_does_not_skip_payload_read(count):
    rig = Rig()
    rig.import_handlers[MALLOC] = lambda args: 0

    def input(index, args):
        if index == 0:
            rig.memory.write(args[2], 4, 1)
        elif index == 1:
            rig.memory.write(args[2], 4, count)
        elif index == 2:
            assert args[2:] == (0, count)
        else:
            rig.memory.write(args[2], 4, 0xDEADBEEF)

    rig.input_hook = input
    assert rig.invoke() == 1
    assert rig.calls_to(MALLOC, channel="import") == [(count,)]
    assert rig.memory.read(rig.pointer, 8) == 0


def test_failed_payload_frees_current_output_through_current_iat_before_zero():
    rig = Rig()
    other = rig.memory.allocate(8)
    rig.statuses = [0, 0, 3]
    frees = []
    rig.import_handlers[0xFA] = lambda args: frees.append(args)

    def clear(result):
        if len(rig.inputs) == 3:
            rig.memory.write(rig.pointer, 8, other)

    def read(address, width):
        if address == rig.pointer:
            rig.memory.write(0x143199DD0, 8, 0xFA)

    rig.clear_hook, rig.after_read = clear, read
    assert rig.invoke() == U32
    assert frees == [(other,)]
    assert rig.memory.read(rig.pointer, 8) == 0


def test_missing_atomic_refuses_after_processed_store_and_expires_local():
    rig = Rig()
    rig.controls = [rig.control()]
    rig.bind(atomics=ReplayUnitAIMapAtomics(None, None))
    with pytest.raises(UnresolvedReplayTaskRebuild, match="atomic"):
        rig.invoke()
    frame = rig.locals[0][0]
    assert ("write", frame + 0x48, 1, 1) in rig.events
    assert not rig.calls_to(CLEAR)
    rig.expired()


@pytest.mark.parametrize("marker", [1, 3])
def test_poll_returns_current_pointer_slot_without_status_normalization(marker):
    rig = Rig(marker=marker)
    returned = rig.invoke(POLL, (rig.manager,))
    assert returned == (0 if marker == 3 else rig.inputs[2][2])
    assert rig.locals[0][1:] == (0x50, b"\xb6" * 0x50)
    rig.expired()


@pytest.mark.parametrize("header_status", [0, 2, 6, 0xFFFFFFFF])
def test_poll_error_runs_stop_dispatch_cleanup_and_returns_mutated_live_slot(header_status):
    rig = Rig()
    rig.header_result = header_status
    frame_holder = []

    def stop(args):
        assert args == (rig.descriptor,)
        frame = rig.locals[0][0]
        frame_holder.append(frame)
        rig.memory.write(frame + 0x40, 8, 0xCAFE)

    def dispatch(args):
        frame = frame_holder[0]
        assert args == (frame + 0x20,)
        assert rig.memory.read_bytes(frame + 0x28, 24) == bytes(24)
        assert rig.memory.read(frame + 0x20, 8) == rig.manager + 0x70
        rig.memory.write(frame + 0x40, 8, 0xBEEF)

    rig.handlers.update({STOP: stop, DISPATCH: dispatch, VECTOR: lambda args: None})
    assert rig.invoke(POLL, (rig.manager,)) == 0xBEEF
    assert [e[1] for e in rig.events if e[0] == "call" and e[1] in (STOP, DISPATCH, VECTOR)] == [
        STOP,
        DISPATCH,
        VECTOR,
    ]


def test_first_ring_count_before_active_and_held_payload_before_count_publication():
    rig = Rig()
    a, b = rig.memory.allocate(1), rig.memory.allocate(1)
    rows = rig.ring([(a, 0, 0, 0, 0, 1), (b, 0, 0, 0, 9, 1)])

    def write(address, width, value):
        if address == rig.count:
            rig.memory.write(rows + 32, 8, a)

    rig.after_write = write
    assert rig.invoke(FIRST, (rig.manager + 0x360, rig.count)) == b
    assert rig.memory.read(rig.count, 4) == 9
    assert rig.memory.read(rows + 32 + 28, 1) == 0
    assert ("read", rows + 28, 1) not in rig.events


def test_timed_ring_unsigned_priority_then_tie_and_current_begin_at_selected_index():
    rig = Rig()
    payloads = [rig.memory.allocate(1) for _ in range(5)]
    rows = rig.ring(
        [
            (payloads[0], U32, 77, 0, 8, 1),
            (payloads[1], 3, 78, 0, 8, 1),
            (payloads[2], 3, 77, U32, 8, 1),
            (payloads[3], 3, 77, 9, 8, 1),
            (payloads[4], 3, 77, 9, 8, 1),
        ]
    )
    replacement = rig.memory.allocate(32 * 5)
    rig.memory.write_bytes(replacement, rig.memory.read_bytes(rows, 32 * 5))
    rig.memory.write(replacement + 3 * 32, 8, payloads[0])

    def read(address, width):
        if address == rows + 4 * 32 + 20:
            rig.memory.write(rig.manager + 0x360, 8, replacement)

    rig.after_read = read
    assert rig.invoke(TIMED, (rig.manager + 0x360, 77, rig.count)) == payloads[0]
    assert rig.memory.read(replacement + 3 * 32 + 28, 1) == 0
    assert rig.memory.read(rows + 3 * 32 + 28, 1) == 1


def test_timed_logger_receives_live_home_pointer_and_retained_partial_seed():
    rig = Rig()
    payload = rig.memory.allocate(1)
    rig.memory.write(payload, 1, 0x7F)
    row = rig.ring([(payload, 19, 77, 29, 8, 1)])
    rig.memory.write(0x144355062, 1, 1)
    rig.memory.map_bytes(0x144355068, (0x1234).to_bytes(8, "little"))

    def home(target, args, data):
        frame = rig.locals[0][0]
        assert (target, args, data) == (
            LOGGER,
            (0x1234, (row & ~255) | 0x2A, 0x14326A5E0, 4, frame + 0x20),
            None,
        )
        assert rig.memory.read(frame + 0x20, 8) == frame + 0x70
        assert [rig.memory.read(frame + offset, 8) for offset in (0x70, 0x78, 0x80, 0x88)] == [
            frame + offset for offset in (0x30, 0x40, 0x50, 0x60)
        ]
        assert [
            rig.memory.read(frame + offset, 4) for offset in (0x38, 0x48, 0x50, 0x58, 0x60, 0x68)
        ] == [5, 7, 77, 7, 19, 2]
        assert rig.memory.read_bytes(frame + 0x30, 8) == b"\x7f" + b"\xc7" * 7
        rig.memory.write(payload, 1, 0x11)
        return None

    rig.home_handler = home
    assert rig.invoke(TIMED, (rig.manager + 0x360, 77, rig.count)) == payload
    rig.expired()


def test_timed_ring_all_ones_dword_keys_still_beat_initial_qword_sentinel():
    rig = Rig()
    payload = rig.memory.allocate(1)
    rig.ring([(payload, U32, 91, U32, 8, 1)])
    assert rig.invoke(TIMED, (rig.manager + 0x360, 91, rig.count)) == payload


def test_queue_reloads_manager_and_current_vtable_after_each_command_then_marks_done():
    rig = Rig()
    receiver = rig.memory.allocate(0x2010)
    table, table2 = rig.memory.allocate(0x28), rig.memory.allocate(0x28)
    manager2 = rig.memory.allocate(0x3A0)
    payload = rig.memory.allocate(1)
    for address, width, value in (
        (receiver, 8, table),
        (receiver + 0x2008, 8, rig.manager),
        (table + 0x20, 8, 0xEE),
        (table2 + 0x20, 8, 0xEF),
        (rig.manager + 0x318, 4, 3),
        (manager2 + 0x318, 4, 3),
        (manager2 + 0x398, 8, rig.descriptor),
    ):
        rig.memory.write(address, width, value)
    rig.ring([(payload, 0, 0, 0, 1, 1)])
    rig.ring([(payload, 0, 0, 0, 1, 1)], manager=manager2)

    def execute(args):
        assert args == (receiver, payload)
        rig.memory.write(receiver + 0x2008, 8, manager2)
        rig.memory.write(receiver, 8, table2)

    rig.handlers[0xEE], rig.handlers[0xEF] = execute, lambda args: None
    assert rig.invoke(QUEUE, (receiver,)) is None
    assert rig.calls_to(0xEE) == [(receiver, payload)]
    assert rig.calls_to(0xEF) == [(receiver, payload)]
    assert rig.memory.read(manager2 + 0x380, 1) == 1


def test_initial_null_queue_manager_skips_everything_and_release_only_frees_mode_ten():
    rig = Rig()
    receiver = rig.memory.allocate(0x2010)
    rig.memory.write(receiver + 0x2008, 8, 0)
    assert rig.invoke(QUEUE, (receiver,)) is None
    assert rig.events == [("read", receiver + 0x2008, 8)]
    pointer = rig.memory.allocate(1)
    rig.invoke(RELEASE, (rig.manager, pointer))
    assert rig.calls_to(FREE, channel="import") == [(pointer,)]
    rig.invoke(RELEASE, (rig.manager, 0))
    rig.memory.write(rig.manager + 0x318, 4, 3)
    rig.invoke(RELEASE, (rig.manager, pointer))
    assert len(rig.calls_to(FREE, channel="import")) == 1


def test_clock_and_game_world_leaves_use_current_storage_and_real_clock_child():
    rig = Rig()
    game = rig.memory.allocate(0x5C8)
    world, clock = rig.memory.allocate(0x230), rig.memory.allocate(0x34)
    rig.memory.write(clock + 0x30, 4, 0x80000001)
    assert rig.invoke(CLOCK, (clock,)) == 0x80000001
    rig.memory.write(game + 0x5C0, 8, 0)
    assert rig.invoke(GAME, (game,)) == 0
    rig.memory.write(game + 0x5C0, 8, world)
    rig.memory.write(world + 0x228, 8, clock)
    rig.handlers[0x140E68F70] = lambda args: 0xF1234567 if args == (clock,) else None
    assert rig.invoke(GAME, (game,)) == 0xF1234567
    assert rig.calls_to(0x140E68F70) == [(clock,)]


def test_unknown_dispatch_preserves_identity_and_known_malformed_calls_refuse():
    rig = Rig()
    data, args = memoryview(bytearray(b"abc")), (-1,)
    marker = -123
    forwarded = []
    calls = ReplayTaskRebuildCalls(
        lambda target, actual, view: forwarded.append((target, actual, view)) or marker
    )
    bound = bind_replay_command_reader(
        rig.storage,
        calls,
        imports=rig.imports,
        logger_home_calls=rig.home_calls,
        atomics=rig.atomics,
        bind_local=rig.bind_local,
        profile=rig.profile,
    )
    assert bound.call(0xBAD, args, data) is marker
    assert forwarded[0][1] is args and forwarded[0][2] is data
    for target, wrong in ((READER, (1,)), (POLL, ()), (QUEUE, (1, 2)), (RELEASE, (1,))):
        with pytest.raises(ValueError):
            bound.call(target, wrong, None)
    with pytest.raises(ValueError):
        bound.call(READER, (1, 2, 3), data)
    with pytest.raises(ValueError):
        bound.call(READER, (-1, 2, 3), None)


@pytest.mark.parametrize("lengths", [(0, 0x50, 0x90), (0x58, 0, 0x90), (0x58, 0x50, 0)])
def test_profile_requires_each_complete_explicit_seed(lengths):
    with pytest.raises(ValueError):
        ReplayCommandReaderProfile(*(bytes(length) for length in lengths))


def test_real_file_read_support_backend_result_and_wrapping_header_compose_exact_wire():
    rig = Rig()
    # Authored OS capability supplies bytes; every caller above it is the owned
    # source port. This does not establish native File/backend construction.
    wire = b"\x01\0\0\0\0\x03\0\0\0abc\xef\xbe\xad\xde"
    file, backend, table = (rig.memory.allocate(size) for size in (0xA8, 8, 0x48))
    for address, width, value in (
        (rig.descriptor + 0x48, 8, file),
        (rig.descriptor + 0x58, 1, 255),
        (rig.descriptor + 0x5C, 4, 1),
        (file + 0x28, 8, 0xC001),
        (file + 0x30, 8, len(wire)),
        (file + 0x40, 8, 0),
        (file + 0x54, 1, 1),
        (file + 0x56, 1, 0),
        (file + 0x80, 4, 0),
        (backend, 8, table),
        (table + 0x38, 8, 0x141756EA0),
    ):
        rig.memory.write(address, width, value)
    rig.memory.map_bytes(0x144281D30, backend.to_bytes(8, "little"))
    rig.memory.map_bytes(0x143198988, (0xFA01).to_bytes(8, "little"))
    os_cursor, os_reads = 0, []

    def os_call(target, args, data):
        nonlocal os_cursor
        assert target == 0xFA01 and data is None
        handle, destination, count, actual, overlapped = args
        assert handle == 0xC001 and overlapped == 0
        chunk = wire[os_cursor : os_cursor + count]
        assert len(chunk) == count
        rig.memory.write_bytes(destination, chunk)
        rig.memory.write(actual, 4, count)
        os_cursor += count
        os_reads.append(count)
        return 0x100  # Full EAX is success even though AL is0 at this boundary.

    unavailable = ReplayTaskRebuildCalls(None)
    backend_calls = bind_replay_file_backend_homes(
        rig.storage,
        unavailable,
        os_calls=ReplayTaskRebuildCalls(os_call),
        bind_local=rig.bind_local,
        profile=ReplayFileBackendProfile(b"\x11" * 0x38, b"\x22" * 0x28),
    )
    support = bind_replay_file_support(
        rig.storage,
        rig.calls,
        variadic_calls=unavailable,
        atomics=rig.atomics,
        bind_local=rig.bind_local,
        profile=ReplayFileSupportProfile(b"\x33" * 0x68, b"\x44" * 0x28, None),
        backend_home_calls=backend_calls,
    )
    file_reads = bind_replay_file_read(
        rig.storage,
        support,
        variadic_calls=unavailable,
        decoder_calls=unavailable,
        atomics=rig.atomics,
        bind_local=rig.bind_local,
        profile=ReplayFileReadProfile(b"\x55" * 0xB8, None, 0),
    )
    position = bind_replay_recorded_position_reader(
        rig.storage,
        file_reads,
        atomics=rig.atomics,
        bind_local=rig.bind_local,
        scratch=ReplayRecordedPositionScratch(b"\x66" * 0x58, b"\x77" * 0x60),
    )
    rig.bound = bind_replay_command_reader(
        rig.storage,
        position,
        imports=rig.imports,
        logger_home_calls=rig.home_calls,
        atomics=rig.atomics,
        bind_local=rig.bind_local,
        profile=rig.profile,
    )
    assert rig.invoke() == 1
    pointer = rig.memory.read(rig.pointer, 8)
    assert rig.memory.read_bytes(pointer, 3) == b"abc"
    assert rig.memory.read(rig.count, 4) == 3
    assert rig.memory.read(rig.descriptor + 0x58, 1) == 0
    assert rig.memory.read(file + 0x40, 8) == os_cursor == len(wire) == 16
    assert os_reads == [4, 1, 4, 3, 4]
    assert not rig.inputs  # The authored Input stub was never reached.
    rig.expired()
