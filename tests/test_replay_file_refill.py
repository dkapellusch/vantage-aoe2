"""Source-led refill controls; constructor/OS/TLS services are authored.

Source140915600, all269 instructions including post-RET diagnostic islands.
No native file identity, formatted error text or restored World is inferred.
"""

from __future__ import annotations

import io
from contextlib import contextmanager
from dataclasses import replace

import pytest

from vantage.replay_file_backend import (
    ReplayFileBackendProfile,
    bind_replay_file_backend_homes,
)
from vantage.replay_file_refill import ReplayFileRefillProfile, bind_replay_file_refill
from vantage.replay_file_support import ReplayFileSupportProfile, bind_replay_file_support
from vantage.replay_memory import ReplayMemory, ReplayMemoryError
from vantage.replay_saved_result import bind_replay_saved_result
from vantage.replay_saved_string import bind_replay_saved_string
from vantage.replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
)
from vantage.replay_unit_ai_map import ReplayUnitAIMapAtomics

REFILL, READ, SEEK = 0x140915600, 0x14093A930, 0x14093A990
CTOR, CLEAR, AUGMENT = 0x140A08840, 0x1402BD890, 0x1408ED8F0
HEADER, ATEXIT, FOOTER = 0x142D6BF80, 0x142D6BD04, 0x142D6BF14
CPP, FORMAT, INDEX = 0x1431F7B10, 0x1431F7B68, 0x144C9C828
ERROR_IAT, FREE_IAT, ERROR_OS, FREE_OS = 0x143198A88, 0x143199DD0, 0xFA03, 0xFA04
DESTROY, DISPOSE, NEW_DISPOSE = 0xDA01, 0xDA02, 0xDA03
U32, U64 = (1 << 32) - 1, (1 << 64) - 1
ROUTES = {
    0x31: (0x14427F950, 0x14427F938, 0x498, 0x1430575A0),
    0x20: (0x14427F968, 0x14427F958, 0x4B3, 0x1430579E0),
    0x25: (0x14427F96C, 0x143DA78B8, 0x4CA, 0x143057A10),
}


class Rig:
    """Only named capabilities; unknown children always refuse at reach."""

    def __init__(self):
        self.memory = ReplayMemory()
        self.file, self.output, self.buffer = (self.memory.allocate(n) for n in (0xA8, 48, 0x8000))
        self.gs, self.array, self.thread = (self.memory.allocate(n) for n in (0x60, 24, 0x3B8))
        self.memory.write_bytes(self.output, b"\xb7" * 48)
        for offset, width, value in (
            (0x28, 8, 7),
            (0x30, 8, 10),
            (0x40, 8, 3),
            (0x48, 4, 0x1111),
            (0x4C, 4, 0x2222),
            (0x50, 4, 0x3333),
            (0x56, 1, 1),
            (0x57, 1, 0),
            (0x58, 8, 0x8888),
            (0x60, 8, 0x9999),
            (0x68, 8, self.buffer),
            (0x70, 8, 0xAAAA),
            (0x78, 8, 0xBBBB),
        ):
            self.memory.write(self.file + offset, width, value)
        self.memory.write(self.gs + 0x58, 8, self.array)
        self.memory.write(self.array + 8, 8, self.thread)
        self.memory.write(self.thread + 0x3B4, 4, 0)
        for address, width, value in (
            (INDEX, 4, 1),
            (ERROR_IAT, 8, ERROR_OS),
            (FREE_IAT, 8, FREE_OS),
        ):
            self.memory.map_bytes(address, value.to_bytes(width, "little"))
        for guard, _, _, _ in ROUTES.values():
            self.memory.map_bytes(guard, bytes(4))
        for address, raw in (
            (ROUTES[0x31][1], b"A" * 21 + b"\0"),
            (ROUTES[0x20][1], b"B" * 15 + b"\0"),
            (ROUTES[0x25][1], b"0123456789\0"),
            (0x1431F8190, b"C" * 16),
            (0x1431F8290, b"D" * 15 + b"\0"),
            (0x1431AC380, bytes(range(16))),
            (0x1431AD060, b"\x11" * 16),
        ):
            self.memory.map_bytes(address, raw)
        self.events, self.locals, self.active = [], [], []
        self.after_read, self.after_write = None, None
        self.read_raw, self.seek_raw, self.last_error = 0xA501, 0xB601, 0xABCDEF1234567890
        self.actual, self.seek_position = None, None
        self.ctor_control, self.ctor_vector, self.header_value = 0, None, 0
        self.profile = ReplayFileRefillProfile(b"\xa5" * 0x88, self.gs)

        def read(address, width):
            self.events.append(("r", address, width))
            value = self.memory.read(address, width)
            if self.after_read is not None:
                self.after_read(address, width)
            return value

        def write(address, width, value):
            self.events.append(("w", address, width, value))
            self.memory.write(address, width, value)
            if self.after_write is not None:
                self.after_write(address, width, value)

        def atomic(address, delta):
            self.events.append(("a", address, delta))
            return self.memory.fetch_add_u32(address, delta)

        self.storage = ReplayTaskRebuildStorage(1, read, write)
        self.atomics = ReplayUnitAIMapAtomics(None, atomic)
        self.handlers = {
            READ: self.read_backend,
            SEEK: self.seek_backend,
            HEADER: lambda args: self.memory.write(args[0], 4, self.header_value),
            ATEXIT: lambda args: None,
            FOOTER: lambda args: self.memory.write(args[0], 4, 0x5A),
            AUGMENT: self.augment,
            DESTROY: lambda args: None,
            DISPOSE: lambda args: None,
            NEW_DISPOSE: lambda args: None,
        }

        def call(target, args, data):
            assert data is None
            self.events.append(("c", target, args))
            if target in self.handlers:
                return self.handlers[target](args)
            if target == CLEAR:
                return self.results.call(target, args, data)
            raise UnresolvedReplayTaskRebuild(f"authored child{target:x} unavailable")

        def imported(target, args, data):
            assert data is None
            self.events.append(("i", target, args))
            if target == ERROR_OS and not args:
                return self.last_error
            if target == FREE_OS and len(args) == 2:
                self.memory.free(args[0])
                return None
            raise UnresolvedReplayTaskRebuild(f"authored import{target:x} unavailable")

        self.calls, self.imports = ReplayTaskRebuildCalls(call), ReplayTaskRebuildCalls(imported)
        strings = bind_replay_saved_string(self.storage, self.calls, imports=self.imports)
        self.results = bind_replay_saved_result(
            self.storage, strings, atomics=self.atomics, imports=self.imports
        )
        self.constructor = self.construct

        def variadic(target, args, data):
            assert target == CTOR and data is None
            self.events.append(("v", target, args))
            return self.constructor(args)

        self.variadic = ReplayTaskRebuildCalls(variadic)
        self.bind()

    @property
    def frame(self):
        return self.locals[0][0]

    def bind(self, *, calls=None, variadic=None, imports=None, atomics=None):
        self.bound = bind_replay_file_refill(
            self.storage,
            self.calls if calls is None else calls,
            variadic_calls=self.variadic if variadic is None else variadic,
            imports=self.imports if imports is None else imports,
            atomics=self.atomics if atomics is None else atomics,
            bind_local=self.bind_local,
            profile=self.profile,
        )

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

    def read_backend(self, args):
        handle, buffer, count, home = args
        assert handle >= 0 and 0 < count <= 0x8000
        actual = count if self.actual is None else self.actual
        self.memory.write_bytes(buffer, b"R" * min(count, actual & U32))
        self.memory.write(home, 8, actual)
        return self.read_raw

    def seek_backend(self, args):
        _, home, mode, requested = args
        assert mode == 0
        self.memory.write(home, 8, requested if self.seek_position is None else self.seek_position)
        return self.seek_raw

    def construct(self, args):
        # Authored service, not a claim to own native variadic formatting.
        result = args[0]
        self.memory.write_bytes(result, b"\xd7" * 48)
        self.memory.write(result, 8, 0)
        self.memory.write(result + 24, 8, 0xEEEE)
        self.memory.write(result + 32, 8, self.ctor_control)
        if self.ctor_vector is not None:
            for offset, value in zip((0, 8, 16), self.ctor_vector, strict=True):
                self.memory.write(result + offset, 8, value)
        return 0xBADCAFE  # Refill ignores this RAX.

    def augment(self, args):
        self.memory.write(args[0] + 24, 8, 0xFACE)
        return 0xBAD  # Refill still returns held output.

    def route(self, code):
        if code == 0x31:
            self.memory.write(self.file + 0x56, 1, 0)
        elif code == 0x20:
            self.memory.write(self.file + 0x57, 1, 1)
            self.seek_raw = 0
        else:
            assert code == 0x25
            self.read_raw = 0

    def invoke(self, *, output=None):
        return self.bound.call(REFILL, (self.file, self.output if output is None else output), None)

    def calls_to(self, target):
        return [e[2] for e in self.events if e[0] in ("c", "i", "v") and e[1] == target]

    def control(self, strong=1, weak=1):
        pointer, table = self.memory.allocate(16), self.memory.allocate(16)
        for address, width, value in (
            (pointer, 8, table),
            (pointer + 8, 4, strong),
            (pointer + 12, 4, weak),
            (table, 8, DESTROY),
            (table + 8, 8, DISPOSE),
        ):
            self.memory.write(address, width, value)
        return pointer

    def vector(self):
        vector, text = self.memory.allocate(32), self.memory.allocate(17)
        self.memory.write_bytes(text, b"heap string data\0")
        for offset, value in ((0, text), (16, 16), (24, 16)):
            self.memory.write(vector + offset, 8, value)
        self.ctor_vector = (vector, vector + 32, vector + 32)
        return vector, text

    def assert_expired(self):
        assert not self.active
        for address, _, _ in self.locals:
            with pytest.raises(ReplayMemoryError, match="unmapped"):
                self.memory.read(address, 1)


@pytest.mark.parametrize(
    "position,length,planned", [(3, 10, 7), (0, 0x10000, 0x8000), (9, 8, 0x8000)]
)
def test_planner_wrap_clamp_exact_success_and_no_cursor_or_error_reset(position, length, planned):
    r = Rig()
    r.memory.write(r.file + 0x40, 8, position)
    r.memory.write(r.file + 0x30, 8, length)
    assert r.invoke() == r.output
    assert r.calls_to(READ) == [(7, r.buffer, planned, r.frame + 0x80)]
    assert r.memory.read(r.file + 0x70, 8) == r.buffer
    assert r.memory.read(r.file + 0x78, 8) == position
    assert r.memory.read(r.file + 0x58, 8) == planned
    assert r.memory.read(r.file + 0x60, 8) == planned
    assert r.memory.read(r.file + 0x40, 8) == position
    assert [r.memory.read(r.file + offset, 4) for offset in (0x48, 0x4C)] == [0x1111, 0x2222]
    assert r.memory.read_bytes(r.output, 48) == bytes(41) + b"\xb7" * 7
    assert not r.calls_to(SEEK) and not r.calls_to(CTOR)
    r.assert_expired()


@pytest.mark.parametrize("seek_requested", [0, 1])
def test_zero_planned_keeps_actual_count_and_still_performs_optional_seek_first(seek_requested):
    r = Rig()
    r.memory.write(r.file + 0x30, 8, 3)
    r.memory.write(r.file + 0x57, 1, seek_requested)

    def seek(args):
        assert r.memory.read(args[1], 8) == r.output  # No prezero before Seek.
        return r.seek_backend(args)

    r.handlers[SEEK] = seek
    assert r.invoke() == r.output
    assert r.calls_to(SEEK) == ([(7, r.frame + 0x80, 0, 3)] if seek_requested else [])
    assert not r.calls_to(READ)
    assert r.memory.read(r.file + 0x58, 8) == 0
    assert r.memory.read(r.file + 0x60, 8) == 0x9999
    assert ("w", r.file + 0x60, 8, 0) not in r.events
    r.assert_expired()


def test_planner_holds_old_operands_but_seek_and_read_use_later_current_fields():
    r = Rig()
    new_buffer = r.memory.allocate(32)

    def write(address, width, value):
        if address == r.file + 0x70:
            r.memory.write(r.file + 0x68, 8, new_buffer)
            r.memory.write(r.file + 0x40, 8, 99)
            r.memory.write(r.file + 0x30, 8, 1)
        elif address == r.file + 0x78:
            r.memory.write(r.file + 0x40, 8, 3)
            r.memory.write(r.file + 0x57, 1, 1)
            r.memory.write(r.file + 0x28, 8, 9)
        elif r.active and address == r.frame + 0x80 and value == 0:
            r.memory.write(r.file + 0x68, 8, 0xBAD)
            r.memory.write(r.file + 0x28, 8, 0xBAD)

    r.after_write = write
    assert r.invoke() == r.output
    assert r.calls_to(SEEK) == [(9, r.frame + 0x80, 0, 3)]
    assert r.calls_to(READ) == [(9, new_buffer, 7, r.frame + 0x80)]
    assert r.memory.read(r.file + 0x70, 8) == r.buffer
    assert r.memory.read(r.file + 0x78, 8) == 3
    initial = [("r", r.file + offset, 8) for offset in (0x68, 0x40, 0x30)]
    assert r.events[3:6] == initial
    r.assert_expired()


def test_entry_local_output_store_precedes_current_flag_and_error_avoids_planner_reads():
    r = Rig()

    def write(address, width, value):
        if r.active and address == r.frame + 0x80 and value == r.output:
            r.memory.write(r.file + 0x56, 1, 0)

    r.after_write = write
    assert r.invoke() == r.output
    assert not any(
        e == ("r", r.file + offset, 8) for e in r.events for offset in (0x68, 0x40, 0x30)
    )
    assert r.calls_to(AUGMENT) == [(r.output, CPP, 0x498, ROUTES[0x31][1])]
    assert r.events[:3] == [
        ("map", r.frame, 0x88),
        ("w", r.frame + 0x80, 8, r.output),
        ("r", r.file + 0x56, 1),
    ]
    r.assert_expired()


@pytest.mark.parametrize(
    "raw,exception", [(0x100, None), (None, ValueError), (-1, ValueError), (True, ValueError)]
)
def test_seek_consumes_AL_before_any_home_or_current_position_read(raw, exception):
    r = Rig()
    r.memory.write(r.file + 0x57, 1, 1)
    r.seek_raw = raw
    if exception is None:
        assert r.invoke() == r.output
        assert r.calls_to(AUGMENT)[0][2] == 0x4B3
    else:
        with pytest.raises(exception):
            r.invoke()
    barrier = next(i for i, e in enumerate(r.events) if e[0:2] == ("c", SEEK))
    assert ("r", r.frame + 0x80, 8) not in r.events[barrier + 1 :]
    assert ("r", r.file + 0x40, 8) not in r.events[barrier + 1 :]
    assert r.memory.read(r.file + 0x57, 1) == 0
    r.assert_expired()


def test_seek_comparison_reads_whole_home_then_current_position():
    r = Rig()
    r.memory.write(r.file + 0x57, 1, 1)
    r.seek_position = (1 << 32) + 3
    assert r.invoke() == r.output
    assert r.calls_to(AUGMENT)[0][2] == 0x4B3  # Equal lowDWORD is insufficient.
    barrier = next(i for i, e in enumerate(r.events) if e[0:2] == ("c", SEEK))
    assert r.events[barrier + 1 : barrier + 3] == [
        ("r", r.frame + 0x80, 8),
        ("r", r.file + 0x40, 8),
    ]
    r.assert_expired()


def test_seek_home_read_callback_can_replace_current_comparison_position():
    r = Rig()
    r.memory.write(r.file + 0x57, 1, 1)
    r.seek_position = 6

    def read(address, width):
        if address == r.frame + 0x80:
            r.memory.write(r.file + 0x40, 8, 6)

    r.after_read = read
    assert r.invoke() == r.output
    assert r.calls_to(READ)[0][2] == 7  # Held plan, not length minus changed cursor.
    assert not r.calls_to(CTOR)
    r.assert_expired()


def test_read_uses_low_actual_DWORD_and_publishes_actual_before_AL():
    r = Rig()
    r.actual = 0xFEDCBA9800000007
    assert r.invoke() == r.output
    assert r.memory.read(r.file + 0x60, 8) == 7
    barrier = next(i for i, e in enumerate(r.events) if e[0:2] == ("c", READ))
    assert r.events[barrier + 1 : barrier + 3] == [
        ("r", r.frame + 0x80, 8),
        ("w", r.file + 0x60, 8, 7),
    ]
    r.assert_expired()


@pytest.mark.parametrize("raw", [None, -1, True])
def test_opaque_or_invalid_read_raw_refuses_only_after_actual_publication(raw):
    r = Rig()
    r.read_raw, r.actual = raw, 5
    with pytest.raises(ValueError):
        r.invoke()
    assert ("w", r.file + 0x60, 8, 5) in r.events
    assert r.memory.read(r.file + 0x58, 8) == 7
    assert not r.calls_to(CTOR)
    r.assert_expired()


@pytest.mark.parametrize("raw", [0x100, 0xA501])
def test_failed_read_uses_held_actual_for_File58_despite_publication_callbacks(raw):
    r = Rig()
    r.read_raw, r.actual = raw, 5

    def write(address, width, value):
        if address == r.file + 0x60:
            r.memory.write(r.frame + 0x80, 8, 0x123)
            r.memory.write(r.file + 0x58, 8, 0x456)
            r.memory.write(r.file + 0x60, 8, 0x789)

    r.after_write = write
    assert r.invoke() == r.output
    assert r.memory.read(r.file + 0x58, 8) == 5
    assert r.memory.read(r.file + 0x60, 8) == 0x789
    assert r.calls_to(AUGMENT)[0][2] == 0x4CA
    r.assert_expired()


@pytest.mark.parametrize("code", [0x31, 0x20, 0x25])
def test_constructor_live_homes_partial_seed_and_exact_error_store_order(code):
    r = Rig()
    r.route(code)
    original = r.constructor

    def constructor(args):
        assert args == (r.frame + 0x50, 0, CPP, 0xD7, r.frame + 0x20, r.frame + 0x28)
        assert r.locals[0][1:] == (0x88, b"\xa5" * 0x88)
        assert r.memory.read_bytes(args[0], 48) == b"\xa5" * 48
        assert r.memory.read(args[4], 8) == FORMAT
        assert r.memory.read(args[5], 8) == (0xA5A5A5A5 << 32) | code
        r.memory.write(args[4], 8, 0x1234)
        r.memory.write(args[5], 4, 77)
        assert r.memory.read(args[5], 8) == 0xA5A5A5A50000004D
        return original(args)

    r.constructor = constructor
    assert r.invoke() == r.output
    code_store = ("w", r.frame + 0x28, 4, code)
    format_store = ("w", r.frame + 0x20, 8, FORMAT)
    assert (
        r.events.index(("w", r.file + 0x48, 4, code))
        < r.events.index(("w", r.file + 0x4C, 4, code))
        < r.events.index(code_store)
    )
    assert r.events.index(code_store) < r.events.index(format_store)
    if code == 0x31:
        assert not r.calls_to(ERROR_OS)
    else:
        last = ("i", ERROR_OS, ())
        error_store = ("w", r.file + 0x50, 4, r.last_error & U32)
        assert r.events.index(last) < r.events.index(code_store) < r.events.index(error_store)
        assert r.events.index(error_store) < r.events.index(format_store)
    assert r.calls_to(AUGMENT) == [(r.output, CPP, ROUTES[code][2], ROUTES[code][1])]
    r.assert_expired()


@pytest.mark.parametrize("code", [0x20, 0x25])
def test_LastError_raw_validation_waits_until_after_partial_code_home_store(code):
    r = Rig()
    r.route(code)
    r.last_error = None
    with pytest.raises(ValueError):
        r.invoke()
    assert ("w", r.frame + 0x28, 4, code) in r.events
    assert ("w", r.frame + 0x20, 8, FORMAT) not in r.events
    assert r.memory.read(r.file + 0x50, 4) == 0x3333
    assert not r.calls_to(CTOR)
    r.assert_expired()


def test_LastError_uses_current_IAT_after_File_error_writes():
    r = Rig()
    r.route(0x25)

    def write(address, width, value):
        if address == r.file + 0x4C:
            r.memory.write(ERROR_IAT, 8, 0xFA99)

    r.after_write = write
    with pytest.raises(UnresolvedReplayTaskRebuild, match="importfa99"):
        r.invoke()
    assert r.calls_to(0xFA99) == [()]
    assert ("w", r.frame + 0x28, 4, 0x25) not in r.events
    r.assert_expired()


@pytest.mark.parametrize("code", [0x31, 0x20, 0x25])
@pytest.mark.parametrize(
    "strong,weak,virtuals", [(2, 1, ()), (1, 2, (DESTROY,)), (1, 1, (DESTROY, DISPOSE))]
)
def test_real_atomic_control_branches_precede_actual_vector_cleanup_and_GS(
    code, strong, weak, virtuals
):
    r = Rig()
    r.route(code)
    control = r.control(strong, weak)
    r.ctor_control = control
    assert r.invoke() == r.output
    calls = [e[1] for e in r.events if e[0] == "c" and e[1] in (DESTROY, DISPOSE)]
    assert calls == list(virtuals)
    assert r.memory.read(control + 8, 4) == strong - 1
    assert r.memory.read(control + 12, 4) == weak - (strong == 1)
    clear = r.events.index(("c", CLEAR, (r.frame + 0x50,)))
    assert all(i < clear for i, e in enumerate(r.events) if e[0] == "a")
    assert clear < r.events.index(("r", r.gs + 0x58, 8))
    assert ("r", r.frame + 0x68, 8) not in r.events  # No caller status read.
    assert ("r", r.frame + 0x78, 1) not in r.events  # No caller processed read.
    assert r.memory.read(r.file + 0x48, 4) == code
    r.assert_expired()


def test_held_control_and_current_virtual_table_survive_Result_control_replacement():
    r = Rig()
    r.route(0x31)
    control, replacement = r.control(), r.control(7, 9)
    r.ctor_control = control
    table = r.memory.allocate(16)
    r.memory.write(table + 8, 8, NEW_DISPOSE)

    def destroy(args):
        assert args == (control,)
        r.memory.write(r.frame + 0x70, 8, replacement)
        r.memory.write(control, 8, table)

    r.handlers[DESTROY] = destroy
    assert r.invoke() == r.output
    assert r.calls_to(NEW_DISPOSE) == [(control,)]
    assert not r.calls_to(DISPOSE)
    assert r.memory.read(replacement + 8, 4) == 7
    assert r.memory.read(replacement + 12, 4) == 9
    r.assert_expired()


@pytest.mark.parametrize("code", [0x31, 0x20, 0x25])
def test_real_heap_string_and_vector_free_finish_before_missing_GS_refusal(code):
    r = Rig()
    r.route(code)
    vector, text = r.vector()
    r.ctor_control = r.control()
    r.profile = replace(r.profile, gs_base=None)
    r.bind()
    with pytest.raises(UnresolvedReplayTaskRebuild, match="GS58"):
        r.invoke()
    assert r.calls_to(FREE_OS) == [(text, 17), (vector, 32)]
    clear = r.events.index(("c", CLEAR, (r.frame + 0x50,)))
    assert r.events.index(("c", DISPOSE, (r.ctor_control,))) < clear
    for pointer in (text, vector):
        with pytest.raises(ReplayMemoryError, match="unmapped"):
            r.memory.read(pointer, 1)
    assert not r.calls_to(AUGMENT)
    r.assert_expired()


def test_destroy_callback_publishes_current_vector_before_real_cleanup():
    r = Rig()
    r.route(0x31)
    vector, text = r.vector()
    replacement = r.ctor_vector
    r.ctor_vector = None  # Constructor begins with null vector, not the later one.
    r.ctor_control = r.control()

    def destroy(args):
        assert args == (r.ctor_control,)
        for offset, value in zip((0, 8, 16), replacement, strict=True):
            r.memory.write(r.frame + 0x50 + offset, 8, value)

    r.handlers[DESTROY] = destroy
    assert r.invoke() == r.output
    assert r.calls_to(FREE_OS) == [(text, 17), (vector, 32)]
    assert r.events.index(("c", DESTROY, (r.ctor_control,))) < r.events.index(
        ("c", CLEAR, (r.frame + 0x50,))
    )
    r.assert_expired()


@pytest.mark.parametrize("code", [0x20, 0x25])
def test_error20_and25_have_distinct_exact_GS_index_constant_thread_preludes(code):
    r = Rig()
    r.route(code)
    guard, text, _, _ = ROUTES[code]
    r.memory.write(guard, 4, 1)
    r.header_value = U32

    def read(address, width):
        if code == 0x20 and address == r.array + 8:
            r.memory.write_bytes(0x1431F8290, b"Z" * 16)

    r.after_read = read
    assert r.invoke() == r.output
    start = r.events.index(("r", r.gs + 0x58, 8))
    expected = [("r", r.gs + 0x58, 8), ("r", INDEX, 4)]
    if code == 0x20:
        expected.append(("r", 0x1431F8290, 16))
    expected += [("r", r.array + 8, 8), ("r", r.thread + 0x3B4, 4), ("r", guard, 4)]
    assert r.events[start : start + len(expected)] == expected
    if code == 0x20:
        assert r.memory.read_bytes(text, 16) == b"D" * 15 + b"\0"
        assert [e for e in r.events if e[0] == "w" and text <= e[1] < text + 16] == [
            ("w", text, 16, int.from_bytes(b"D" * 15 + b"\0", "little"))
        ]
    else:
        assert ("r", 0x1431F8190, 16) not in r.events
        assert ("r", 0x1431F8290, 16) not in r.events
    r.assert_expired()


@pytest.mark.parametrize("code", [0x31, 0x20, 0x25])
@pytest.mark.parametrize(
    "guard,epoch,header",
    [
        (0, 0, False),
        (U32, 0, False),
        (0x80000000, 0x7FFFFFFF, False),
        (0x7FFFFFFF, 0x80000000, True),
        (1, 0, True),
    ],
)
def test_diagnostic_signed_guard_comparison_and_post_header_current_gate(
    code,
    guard,
    epoch,
    header,
):
    r = Rig()
    r.route(code)
    r.memory.write(ROUTES[code][0], 4, guard)
    r.memory.write(r.thread + 0x3B4, 4, epoch)
    r.header_value = 0  # Fresh guard not -1: header alone does not authorize init.
    assert r.invoke() == r.output
    assert r.calls_to(HEADER) == ([(ROUTES[code][0],)] if header else [])
    assert not r.calls_to(ATEXIT) and not r.calls_to(FOOTER)
    r.assert_expired()


@pytest.mark.parametrize("code", [0x31, 0x20, 0x25])
def test_minus_one_initialization_uses_exact_registration_and_outer_augmentation(code):
    r = Rig()
    r.route(code)
    guard, text, line, destructor = ROUTES[code]
    r.memory.write(guard, 4, 1)
    r.header_value = U32
    assert r.invoke() == r.output
    assert r.calls_to(HEADER) == [(guard,)]
    assert r.calls_to(ATEXIT) == [(destructor,)]
    assert r.calls_to(FOOTER) == [(guard,)]
    assert r.calls_to(AUGMENT) == [(r.output, CPP, line, text)]
    assert (
        r.events.index(("c", HEADER, (guard,)))
        < r.events.index(("c", ATEXIT, (destructor,)))
        < r.events.index(("c", FOOTER, (guard,)))
    )
    before_registration = r.events[: r.events.index(("c", ATEXIT, (destructor,)))]
    stores = [e for e in before_registration if e[0] == "w" and text <= e[1] < text + 22]
    expected = {
        0x31: [
            ("w", text + 16, 4, 0xD2DBD5D6),
            ("w", text + 20, 2, 0xB7D3),
            ("w", text, 16, int.from_bytes(b"C" * 16, "little")),
        ],
        0x20: [("w", text, 16, int.from_bytes(b"D" * 15 + b"\0", "little"))],
        0x25: [
            ("w", text, 4, 0xFEFBFFC8),
            ("w", text + 4, 4, 0xE8E8FFBA),
            ("w", text + 8, 2, 0xE8F5),
            ("w", text + 10, 1, 0x9A),
        ],
    }
    assert stores == expected[code]
    r.assert_expired()


def test_error31_interleaves_stage_thread_epoch_and_initializes_current_tails_before_held_block():
    r = Rig()
    r.route(0x31)
    guard, text, _, _ = ROUTES[0x31]
    r.memory.write(guard, 4, 1)
    new_thread = r.memory.allocate(0x3B8)
    r.memory.write(new_thread + 0x3B4, 4, 99)

    def write(address, width, value):
        if address == r.frame + 0x40:
            r.memory.write(r.array + 8, 8, new_thread)
        elif address == r.frame + 0x44:
            r.memory.write(new_thread + 0x3B4, 4, 0)

    def header(args):
        r.memory.write(guard, 4, U32)
        r.memory.write(r.frame + 0x40, 4, 0x12345678)
        r.memory.write(r.frame + 0x44, 2, 0x00EF)
        r.memory.write_bytes(0x1431F8190, b"Z" * 16)

    r.after_write, r.handlers[HEADER] = write, header
    assert r.invoke() == r.output
    assert r.memory.read_bytes(text, 22) == b"C" * 16 + b"\x78\x56\x34\x12\xef\0"
    start = r.events.index(("r", r.gs + 0x58, 8))
    assert r.events[start : start + 8] == [
        ("r", r.gs + 0x58, 8),
        ("r", INDEX, 4),
        ("r", 0x1431F8190, 16),
        ("w", r.frame + 0x40, 4, 0xD2DBD5D6),
        ("r", r.array + 8, 8),
        ("w", r.frame + 0x44, 2, 0xB7D3),
        ("r", new_thread + 0x3B4, 4),
        ("r", guard, 4),
    ]
    tail = [
        ("w", text + 16, 4, 0x12345678),
        ("w", text + 20, 2, 0x00EF),
        ("w", text, 16, int.from_bytes(b"C" * 16, "little")),
    ]
    assert [e for e in r.events if e[0] == "w" and text <= e[1] < text + 22] == tail
    r.assert_expired()


def test_error31_decode_reads_current_text_before_current_mask_and_final_flag_is_current():
    r = Rig()
    r.route(0x31)
    text = ROUTES[0x31][1]
    r.memory.write(text + 21, 1, 1)

    def read(address, width):
        if address == text and width == 16:
            r.memory.write_bytes(0x1431AC380, b"\x22" * 16)

    def write(address, width, value):
        if address == text and width == 16:
            r.memory.write_bytes(text + 16, b"12345\x33")

    r.after_read, r.after_write = read, write
    assert r.invoke() == r.output
    assert r.memory.read_bytes(text, 16) == bytes([ord("A") ^ 0x22]) * 16
    assert r.memory.read_bytes(text + 16, 6) == bytes(value ^ 0xB7 for value in b"12345\x33")
    assert r.events.index(("r", text, 16)) < r.events.index(("r", 0x1431AC380, 16))
    assert [
        e[1] for e in r.events if e[0] == "w" and e[2] == 1 and text <= e[1] < text + 22
    ] == list(range(text + 16, text + 22))
    r.assert_expired()


def test_error20_current_text_before_mask_and_no_extra_flag_store_after_block_callback():
    r = Rig()
    r.route(0x20)
    text = ROUTES[0x20][1]
    r.memory.write(text + 15, 1, 1)
    original = r.memory.read_bytes(text, 16)

    def read(address, width):
        if address == text and width == 16:
            r.memory.write_bytes(0x1431AD060, b"\x33" * 16)

    def write(address, width, value):
        if address == text and width == 16:
            r.memory.write(text + 15, 1, 0x44)

    r.after_read, r.after_write = read, write
    assert r.invoke() == r.output
    assert r.memory.read_bytes(text, 15) == bytes(value ^ 0x33 for value in original[:15])
    assert r.memory.read(text + 15, 1) == 0x44
    assert r.events.index(("r", text, 16)) < r.events.index(("r", 0x1431AD060, 16))
    assert [e for e in r.events if e[0] == "w" and text <= e[1] < text + 16] == [
        ("w", text, 16, int.from_bytes(bytes(value ^ 0x33 for value in original), "little"))
    ]
    r.assert_expired()


def test_error25_decode_uses_held_gate_but_current_each_payload_byte():
    r = Rig()
    r.route(0x25)
    text = ROUTES[0x25][1]
    r.memory.write(text + 10, 1, 0x55)

    def write(address, width, value):
        if address == text:
            r.memory.write(text + 1, 1, 0x77)
            r.memory.write(text + 10, 1, 0x11)

    r.after_write = write
    assert r.invoke() == r.output
    assert r.memory.read(text + 1, 1) == 0x77 ^ 0x9A
    assert r.memory.read(text + 10, 1) == 0x55 ^ 0x9A
    assert len([e for e in r.events if e[0] == "r" and e[1] == text + 10]) == 1
    r.assert_expired()


@pytest.mark.parametrize("code", [0x31, 0x20, 0x25])
def test_GS_array_is_held_but_index_and_thread_cell_are_sampled_at_their_source_points(code):
    r = Rig()
    r.route(code)
    other = r.memory.allocate(0x3B8)
    r.memory.write(other + 0x3B4, 4, 0)
    r.memory.write(r.array + 16, 8, other)

    def read(address, width):
        if address == r.gs + 0x58:
            r.memory.write(r.gs + 0x58, 8, 0xBAD)
            r.memory.write(INDEX, 4, 2)

    r.after_read = read
    assert r.invoke() == r.output
    assert ("r", r.array + 16, 8) in r.events
    assert ("r", other + 0x3B4, 4) in r.events
    assert ("r", 0xBAD + 16, 8) not in r.events
    r.assert_expired()


@pytest.mark.parametrize(
    "missing",
    [
        "read",
        "seek",
        "constructor",
        "vector",
        "atomic",
        "virtual",
        "header",
        "atexit",
        "footer",
        "augment",
    ],
)
def test_missing_reached_children_refuse_with_prior_effects_and_expire_local(missing):
    r = Rig()
    if missing == "read":
        del r.handlers[READ]
    elif missing == "seek":
        r.memory.write(r.file + 0x57, 1, 1)
        del r.handlers[SEEK]
    else:
        r.route(0x31)
        if missing == "constructor":
            r.bind(variadic=ReplayTaskRebuildCalls(None))
        elif missing == "vector":
            r.handlers[CLEAR] = lambda args: (_ for _ in ()).throw(
                UnresolvedReplayTaskRebuild("actual vector unavailable")
            )
        elif missing in ("atomic", "virtual"):
            r.ctor_control = r.control()
            if missing == "atomic":
                r.bind(atomics=ReplayUnitAIMapAtomics(None, None))
            else:
                del r.handlers[DESTROY]
        elif missing in ("header", "atexit", "footer"):
            r.memory.write(ROUTES[0x31][0], 4, 1)
            r.header_value = U32
            del r.handlers[{"header": HEADER, "atexit": ATEXIT, "footer": FOOTER}[missing]]
        else:
            del r.handlers[AUGMENT]
    with pytest.raises(UnresolvedReplayTaskRebuild):
        r.invoke()
    assert ("w", r.frame + 0x80, 8, r.output) in r.events
    if missing not in ("read", "seek"):
        assert r.memory.read(r.file + 0x48, 4) == 0x31
    r.assert_expired()


def test_source_success_output_alias_changes_File_fields_after_planning_and_keeps_return():
    r = Rig()
    output = r.file + 0x30
    r.memory.write_bytes(output, b"\xb7" * 48)
    for offset, width, value in ((0x30, 8, 3), (0x40, 8, 3), (0x56, 1, 1), (0x57, 1, 0)):
        r.memory.write(r.file + offset, width, value)
    assert r.invoke(output=output) == output
    assert r.memory.read(r.file + 0x56, 1) == 0
    assert r.memory.read(r.file + 0x58, 8) == 0
    assert not r.calls_to(READ) and not r.calls_to(CTOR)
    r.assert_expired()


def test_actual_refill_support_HOME_backend_compose_with_explicit_owned_BytesIO_services():
    r = Rig()
    stream = io.BytesIO(b"abcdefghijklmnop")
    service, table = r.memory.allocate(8), r.memory.allocate(0x48)
    r.memory.write(service, 8, table)
    r.memory.write(table + 0x38, 8, 0x141756EA0)
    r.memory.write(table + 0x40, 8, 0x141757120)
    for address, value in ((0x144281D30, service), (0x143198988, 0xFA11), (0x1431989A8, 0xFA12)):
        r.memory.map_bytes(address, value.to_bytes(8, "little"))
    os_events = []

    def os_call(target, args, data):
        assert data is None and args[0] == 7
        os_events.append((target, args))
        if target == 0xFA11 and len(args) == 5:
            assert args[4] == 0
            payload = stream.read(args[2])
            r.memory.write_bytes(args[1], payload)
            r.memory.write(args[3], 4, len(payload))
            return 0x100  # OS checks full EAX; concrete method produces AL1.
        if target == 0xFA12 and len(args) == 4:
            position = stream.seek(args[1], args[3])
            r.memory.write(args[2], 8, position)
            return 0x100
        raise UnresolvedReplayTaskRebuild(f"unprovided composed OS target{target:x}")

    home = bind_replay_file_backend_homes(
        r.storage,
        ReplayTaskRebuildCalls(None),
        os_calls=ReplayTaskRebuildCalls(os_call),
        bind_local=r.bind_local,
        profile=ReplayFileBackendProfile(b"R" * 0x38, b"S" * 0x28),
    )
    support = bind_replay_file_support(
        r.storage,
        r.calls,
        variadic_calls=ReplayTaskRebuildCalls(None),
        atomics=r.atomics,
        bind_local=r.bind_local,
        backend_home_calls=home,
        profile=ReplayFileSupportProfile(b"P" * 0x68, b"H" * 0x28, None),
    )
    r.memory.write(r.file + 0x30, 8, 16)
    r.memory.write(r.file + 0x40, 8, 2)
    r.memory.write(r.file + 0x57, 1, 1)
    r.bind(calls=support, variadic=ReplayTaskRebuildCalls(None))
    assert r.invoke() == r.output
    assert [target for target, _ in os_events] == [0xFA12, 0xFA11]
    assert r.memory.read_bytes(r.buffer, 14) == b"cdefghijklmnop"
    assert r.memory.read(r.file + 0x40, 8) == 2  # Refill does not advance this field.
    assert r.memory.read(r.file + 0x58, 8) == r.memory.read(r.file + 0x60, 8) == 14
    assert stream.tell() == 16
    assert r.memory.read_bytes(r.output, 48) == bytes(41) + b"\xb7" * 7
    assert not r.calls_to(CTOR) and not r.calls_to(AUGMENT)
    assert len(r.locals) == 5  # Refill + two wrapper frames + two concrete frames.
    r.assert_expired()


@pytest.mark.parametrize(
    "args,data",
    [
        ((1,), None),
        ((1, 2, 3), None),
        ((-1, 2), None),
        ((1, True), None),
        ((1, 2), memoryview(b"x")),
    ],
)
def test_malformed_owned_calls_refuse_before_mapping(args, data):
    r = Rig()
    with pytest.raises(ValueError):
        r.bound.call(REFILL, args, data)
    assert not r.locals and not r.events


def test_unknown_delegate_keeps_args_and_data_identity_and_opaque_return():
    r = Rig()
    seen, args, data = [], (1, 2), memoryview(b"x")

    def call(target, actual_args, actual_data):
        seen.append((target, actual_args, actual_data))
        return None

    r.bind(calls=ReplayTaskRebuildCalls(call))
    assert r.bound.call(0x123, args, data) is None
    assert seen[0][1] is args and seen[0][2] is data
    assert not r.locals and not r.events
