"""Read140916db0 source controls; unowned services are explicit authored inputs."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace

import pytest

from vantage.replay_file_read import ReplayFileReadProfile, bind_replay_file_read
from vantage.replay_file_support import ReplayFileSupportProfile, bind_replay_file_support
from vantage.replay_memory import ReplayMemory, ReplayMemoryError
from vantage.replay_saved_apply import bind_replay_saved_apply
from vantage.replay_saved_result import bind_replay_saved_result
from vantage.replay_saved_string import bind_replay_saved_string
from vantage.replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
)
from vantage.replay_unit_ai_map import ReplayUnitAIMapAtomics

READ, PREFLIGHT, MODE, REFILL = 0x140916DB0, 0x140916440, 0x140916040, 0x140915600
BACKEND, DECODER, COPY = 0x14093A930, 0x14178AE30, 0x142D6E3B1
CTOR, CLEAR, APPEND, FORWARD = 0x140A08840, 0x1402BD890, 0x140900ED0, 0x1409076B0
AUGMENT, HEADER, ATEXIT, FOOTER = 0x1408ED8F0, 0x142D6BF80, 0x142D6BD04, 0x142D6BF14
INDEX, LAST_ERROR, GLOBAL = 0x144C9C828, 0x143198A88, 0x144281D30
U32, U64 = (1 << 32) - 1, (1 << 64) - 1
# Route: guard, text, flag offset, destructor, expected diagnostic line.
PATHS = {
    "preflight": (0x14427F41C, 0x143DA7848, 11, 0x143057930, 0x2AB),
    "mode": (0x14427F448, 0x14427F420, 36, 0x1430579F0, 0x2BA),
    "mode_child": (0x14427F4C4, 0x14427F4B0, 19, 0x143057C90, 0x2C0),
    "decoder": (0x14427F4E0, 0x14427F4C8, 22, 0x143057DB0, 0x2D7),
    "refill": (0x14427F564, 0x14427F550, 16, 0x143057EB0, 0x2FA),
    "direct": (0x14427F568, 0x143DA7858, 10, 0x143057ED0, 0x30D),
}
GETTERS = (0x140913B70, 0x140914610, 0x140914B60)


class Rig:
    def __init__(self, *, mode=0):
        self.memory = ReplayMemory()
        self.file, self.output, self.destination, self.buffer = (
            self.memory.allocate(n) for n in (0xA8, 48, 128, 128)
        )
        self.memory.write_bytes(self.output, b"\xb7" * 48)
        self.memory.write_bytes(self.buffer, bytes(range(128)))
        self.gs, self.array, self.thread = (self.memory.allocate(n) for n in (0x60, 24, 0x3B8))
        self.service, self.vptr = self.memory.allocate(8), self.memory.allocate(0x48)
        self.details = [self.memory.allocate(85) for _ in GETTERS]
        for pointer in self.details:
            self.memory.write_bytes(pointer, b"d" * 84 + b"\0")
        for address, width, value in (
            (self.file + 0x54, 1, 1),
            (self.file + 0x80, 4, mode),
            (self.file + 0x48, 4, 0x1111),
            (self.file + 0x4C, 4, 0x2222),
            (self.file + 0x50, 4, 0x3333),
            (self.file + 0x40, 8, 50),
            (self.file + 0x30, 8, 1000),
            (self.file + 0x28, 8, 0x4444),
            (self.file + 0x56, 1, 0),
            (self.file + 0x58, 8, 2),
            (self.file + 0x70, 8, self.buffer),
            (self.file + 0x88, 8, 0x8888),
            (self.file + 0x90, 8, 0x9999),
            (self.file + 0x98, 8, 30),
            (self.file + 0xA0, 8, 7),
            (self.gs + 0x58, 8, self.array),
            (self.array + 8, 8, self.thread),
            (self.thread + 0x3B4, 4, 0),
            (self.service, 8, self.vptr),
            (self.vptr + 0x38, 8, 0xBA01),
        ):
            self.memory.write(address, width, value)
        rows = [
            (INDEX, (1).to_bytes(4, "little")),
            (LAST_ERROR, (0xE001).to_bytes(8, "little")),
            (GLOBAL, self.service.to_bytes(8, "little")),
            (0x143199DD0, (0x142D6BAB4).to_bytes(8, "little")),
            (0x14427F154, bytes(4)),
            (0x143DA77F8, b"File not open\0"),
        ]
        for guard, text, flag, _, _ in PATHS.values():
            rows.extend(((guard, bytes(4)), (text, b"t" * flag + b"\0")))
        for i, address in enumerate(
            (
                0x1431F7CA0,
                0x1431F7C10,
                0x1431F7D90,
                0x1431F7FE0,
                0x1431F8270,
                0x1431F8180,
                0x1431F6E20,
                0x1431F81E0,
                0x1431AD060,
                0x1431AB6E0,
            )
        ):
            rows.append((address, bytes(range(i * 16, i * 16 + 16))))
        for address, raw in rows:
            self.memory.map_bytes(address, raw)
        self.events, self.locals, self.active = [], [], []
        self.after_read, self.after_write = None, None
        self.overrides, self.handlers = {}, {}
        self.header_value, self.ctor_control = 0, 0
        self.profile = ReplayFileReadProfile(b"\xc9" * 0xB8, self.gs, 8)

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
            return self.memory.fetch_add_u32(address, delta)

        self.storage = ReplayTaskRebuildStorage(1, read, write)
        self.atomics = ReplayUnitAIMapAtomics(None, atomic)
        self.handlers.update(
            {
                HEADER: lambda args: self.memory.write(args[0], 4, self.header_value),
                ATEXIT: lambda args: None,
                FOOTER: lambda args: self.memory.write(args[0], 4, 0x5A),
                APPEND: lambda args: None,
                AUGMENT: self.augment,
                0xE001: lambda args: 0x12345678ABCDEF01,
                0xBA01: self.backend,
                MODE: lambda args: None,
                REFILL: self.refill,
                COPY: lambda args: self.memory.move(*args),
                0xD1: lambda args: None,
                0xD2: lambda args: None,
            }
        )
        for target, detail in zip(GETTERS, self.details, strict=True):
            self.handlers[target] = lambda args, detail=detail: detail
        runtime = self.memory.runtime_calls()

        def imported(target, args, data):
            self.events.append(("import", target, args))
            return runtime.call(target, args, data)

        def authored(target, args, data):
            assert data is None
            if not self.events or self.events[-1] != ("child", target, args):
                self.events.append(("service", target, args))
            if target not in self.handlers:
                raise UnresolvedReplayTaskRebuild(f"authored child{target:x} missing")
            return self.handlers[target](args)

        def variadic(target, args, data):
            assert target == CTOR and data is None
            self.events.append(("variadic", target, args))
            return self.constructor(args)

        def decoder(target, args, data):
            assert target == DECODER and data is None
            self.events.append(("decoder", target, args))
            return self.decode(args)

        self.constructor, self.decode = self.construct, self.decode_data
        self.variadic = ReplayTaskRebuildCalls(variadic)
        self.decoders = ReplayTaskRebuildCalls(decoder)
        self.imports = ReplayTaskRebuildCalls(imported)
        strings = bind_replay_saved_string(
            self.storage, ReplayTaskRebuildCalls(authored), imports=self.imports
        )
        results = bind_replay_saved_result(
            self.storage, strings, atomics=self.atomics, imports=self.imports
        )
        apply = bind_replay_saved_apply(
            self.storage, results, atomics=self.atomics, imports=self.imports
        )
        self.support = bind_replay_file_support(
            self.storage,
            apply,
            variadic_calls=self.variadic,
            atomics=self.atomics,
            bind_local=self.bind_local,
            profile=ReplayFileSupportProfile(b"\xa5" * 0x68, b"\xc6" * 0x28, self.gs),
        )

        def route(target, args, data):
            assert data is None
            self.events.append(("child", target, args))
            if target in self.overrides:
                return self.overrides[target](args)
            return self.support.call(target, args, data)

        self.calls = ReplayTaskRebuildCalls(route)
        self.bind()

    def bind(self, *, calls=None, variadic=None, decoder=None, atomics=None):
        self.bound = bind_replay_file_read(
            self.storage,
            self.calls if calls is None else calls,
            variadic_calls=self.variadic if variadic is None else variadic,
            decoder_calls=self.decoders if decoder is None else decoder,
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

    def construct(self, args):
        result = args[0]
        self.memory.write_bytes(result, b"\xd7" * 48)
        for offset, value in ((0, 0), (8, 0), (16, 0), (24, 0xEEEE), (32, self.ctor_control)):
            self.memory.write(result + offset, 8, value)
        self.memory.write(result + 40, 1, 0)
        return 0xBADCAFE

    def augment(self, args):
        self.memory.write(args[0] + 24, 8, 0xFACE)
        return 0xBADD

    def backend(self, args):
        self.memory.write(args[4], 8, args[3])
        return 0x12340001

    def decode_data(self, args):
        self.memory.write(args[2], 8, 2)
        return 0

    def refill(self, args):
        self.memory.write(self.file + 0x58, 8, 3)
        self.memory.write(self.file + 0x70, 8, self.buffer + 10)

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

    def calls_to(self, target):
        return [
            e[2]
            for e in self.events
            if e[0] in ("child", "service", "variadic", "decoder") and e[1] == target
        ]

    def invoke(self, count=4):
        return self.bound.call(READ, (self.file, self.output, self.destination, count), None)

    def failure(self, args):
        self.memory.write(args[1] + 24, 8, 9)
        return 0xBAD  # Caller must use the supplied Result, never this return.

    def path(self, name):
        if name == "preflight":
            self.overrides[PREFLIGHT] = self.failure
        elif name in ("mode", "mode_child", "decoder"):
            self.memory.write(self.file + 0x80, 4, 3 if name == "mode" else 1)
            if name == "mode_child":
                self.handlers[MODE] = self.failure
            if name == "decoder":
                self.decode = lambda args: 0xFFFFFFFE
        elif name == "refill":
            self.memory.write(self.file + 0x56, 1, 1)
            self.memory.write(self.file + 0x58, 8, 0)
            self.handlers[REFILL] = self.failure
        else:
            self.handlers[0xBA01] = lambda args: 0
        return PATHS[name]

    def assert_expired(self):
        assert not self.active
        for address, _, _ in self.locals:
            with pytest.raises(ReplayMemoryError, match="unmapped"):
                self.memory.read(address, 1)


def test_zero_count_still_composes_preflight_cleanup_before_exact_success_without_mode_read():
    r = Rig(mode=3)
    r.profile = replace(r.profile, gs_base=None)
    r.bind(variadic=ReplayTaskRebuildCalls(None), decoder=ReplayTaskRebuildCalls(None))
    assert r.invoke(0) == r.output
    frame, size, seed = r.locals[0]
    assert (size, seed) == (0xB8, b"\xc9" * 0xB8)
    assert r.events[:5] == [
        ("map", frame, 0xB8),
        ("write", frame + 0x48, 8, r.output),
        ("write", frame + 0x80, 16, 0),
        ("write", frame + 0x90, 16, 0),
        ("write", frame + 0xA0, 16, 0),
    ]
    assert r.calls_to(PREFLIGHT) == [(r.file, frame + 0x80)]
    assert r.calls_to(CLEAR) == [(frame + 0x80,)]
    assert (
        r.events.index(("read", frame + 0x98, 8))
        < r.events.index(("write", frame + 0xA8, 1, 1))
        < r.events.index(("read", frame + 0xA0, 8))
    )
    assert ("read", r.file + 0x80, 4) not in r.events
    assert r.memory.read_bytes(r.output, 48) == bytes(41) + b"\xb7" * 7
    assert r.memory.read(r.file + 0x48, 4) == 0x1111
    r.assert_expired()


@pytest.mark.parametrize(
    "raw,actual,ok",
    [(1, 4, True), (0x100, 4, False), (0x101, 3, False), (U64, 4, True), (1, (77 << 32) | 4, True)],
)
def test_direct_backend_low_widths_and_cursor_before_result(raw, actual, ok):
    r = Rig()

    def backend(args):
        r.memory.write(args[4], 8, actual)
        r.memory.write(r.file + 0x40, 8, U64 - 2)
        return raw

    r.handlers[0xBA01] = backend
    assert r.invoke() == r.output
    frame = r.locals[0][0]
    assert r.calls_to(0xBA01) == [(r.service, 0x4444, r.destination, 4, frame + 0x48)]
    assert r.memory.read(r.file + 0x40, 8) == ((U64 - 2 + (actual & U32)) & U64)
    assert r.memory.read(r.file + 0x48, 4) == (0 if ok else 0x25)
    assert r.memory.read(r.file + 0x4C, 4) == (0x2222 if ok else 0x25)
    assert r.memory.read(r.output + 24, 8) == (0 if ok else 0xFACE)
    assert len(r.calls_to(CTOR)) == (0 if ok else 1)
    r.assert_expired()


@pytest.mark.parametrize("raw", [None, -1, U64 + 1, True])
def test_direct_invalid_return_refuses_only_after_actual_count_and_fresh_cursor_publication(raw):
    r = Rig()

    def backend(args):
        r.memory.write(args[4], 8, 3)
        r.memory.write(r.file + 0x40, 8, 80)
        return raw

    r.handlers[0xBA01] = backend
    with pytest.raises(ValueError):
        r.invoke()
    assert r.memory.read(r.file + 0x40, 8) == 83
    assert r.memory.read(r.file + 0x48, 4) == 0x1111
    assert r.memory.read_bytes(r.output, 48) == b"\xb7" * 48
    assert not r.calls_to(CTOR)
    r.assert_expired()


@pytest.mark.parametrize("count", [1 << 32, (1 << 32) + 4, U64])
def test_direct_count_truncation_uses_low_dword_without_shortening_bounds(count):
    r = Rig()
    r.memory.write(r.file + 0x30, 8, U64)
    assert r.invoke(count) == r.output
    assert r.calls_to(0xBA01)[0][3] == count & U32
    assert r.memory.read(r.file + 0x40, 8) == 50 + (count & U32)


def test_bounds_error_constructs_directly_into_output_without_augment_or_temporary_cleanup():
    r = Rig()
    assert r.invoke(951) == r.output
    frame = r.locals[0][0]
    assert r.memory.read(r.file + 0x48, 4) == r.memory.read(r.file + 0x4C, 4) == 0x24
    assert r.calls_to(CTOR) == [(r.output, 0, 0x1431F7B10, 0xD7, frame + 0x20, frame + 0x28)]
    assert r.events.index(("write", frame + 0x28, 4, 0x24)) < r.events.index(
        ("write", frame + 0x20, 8, 0x1431F7B68)
    )
    assert r.calls_to(CLEAR) == [(frame + 0x80,)]
    assert not r.calls_to(AUGMENT) and not r.calls_to(BACKEND)
    assert r.memory.read(r.output + 24, 8) == 0xEEEE


def test_wrapped_unsigned_bounds_and_late_get_last_error_import():
    r = Rig()
    r.memory.write(r.file + 0x40, 8, U64 - 1)
    r.memory.write(r.file + 0x30, 8, 3)

    def backend(args):
        r.memory.write(args[4], 8, 1)
        r.memory.write(LAST_ERROR, 8, 0xE002)
        return 0

    r.handlers[0xBA01] = backend
    r.handlers[0xE002] = lambda args: 0xFEED12345678
    assert r.invoke() == r.output
    assert r.memory.read(r.file + 0x40, 8) == U64
    assert r.memory.read(r.file + 0x50, 4) == 0x12345678
    assert r.calls_to(0xE002) == [()] and not r.calls_to(0xE001)


@pytest.mark.parametrize("mode", [1, 2, 4, U32])
def test_decoder_homes_are_live_locations_with_partial_width_seed_and_exact_cleanup(mode):
    r = Rig(mode=mode)

    def decode(args):
        frame = r.active[0]
        assert args == (
            0x9999,
            7,
            frame + 0x48,
            r.destination,
            frame + 0x20,
            frame + 0x28,
            frame + 0x30,
            frame + 0x38,
        )
        assert r.memory.read(args[4], 8) == 0xC9C9C9C900000000
        assert r.memory.read(args[5], 8) == frame + 0xB0
        assert r.memory.read(args[6], 8) == 0x8888
        assert r.memory.read(args[7], 8) == 0xC9C9C9C900000001
        assert r.memory.read(args[2], 8) == 23
        r.memory.write(args[2], 8, (1 << 32) + 2)
        r.memory.write(r.file + 0xA0, 8, U64)
        return 0x1234FFFF0001  # Every lowEAX except fffffffe is admitted here.

    r.decode = decode
    assert r.invoke() == r.output
    frame = r.locals[0][0]
    assert r.memory.read(r.file + 0xA0, 8) == (1 << 32) + 1
    assert r.memory.read(r.file + 0x40, 8) == 50
    assert r.calls_to(MODE) == ([(r.file, frame + 0x50)] if mode == 1 else [])
    tail = [
        ("write", frame + 0x50, 16, 0),
        ("write", frame + 0x60, 16, 0),
        ("write", frame + 0x70, 8, 0),
        ("write", frame + 0x78, 1, 0),
    ]
    last = max(i for i, e in enumerate(r.events) if e == tail[0])
    assert r.events[last : last + 4] == tail
    assert r.calls_to(CLEAR)[-1] == (frame + 0x50,)
    assert r.memory.read_bytes(r.output, 48) == bytes(41) + b"\xb7" * 7
    r.assert_expired()


@pytest.mark.parametrize("changed_mode", [0, 3])
def test_mode_child_success_cleanup_does_not_redispatch_mutated_file_mode(changed_mode):
    r = Rig(mode=1)
    control = r.control()

    def write(address, width, value):
        if r.active and address == r.active[0] + 0x78 and value == 1:
            r.memory.write(r.active[0] + 0x70, 8, control)
            r.memory.write(r.file + 0x80, 4, changed_mode)

    r.after_write = write
    assert r.invoke() == r.output
    assert r.calls_to(0xD1) == [(control,)] and r.calls_to(0xD2) == [(control,)]
    assert len(r.calls_to(DECODER)) == 1 and not r.calls_to(BACKEND)
    assert not r.calls_to(CTOR)


@pytest.mark.parametrize(
    "raw,actual,early",
    [(0xFFFFFFFE, 4, True), (0xABCDFFFFFFFE, 4, True), (0, (1 << 32) + 4, False), (1, 3, False)],
)
def test_decoder_error_short_circuit_and_whole_output_count(raw, actual, early):
    r = Rig(mode=2)

    def decode(args):
        r.memory.write(r.memory.read(args[5], 8), 8, actual)
        return raw

    r.decode = decode
    assert r.invoke() == r.output
    frame = r.locals[0][0]
    assert (("read", frame + 0xB0, 8) not in r.events) == early
    assert r.memory.read(r.file + 0x80, 4) == 0
    assert r.memory.read(r.file + 0xA0, 8) == 7
    assert r.memory.read(r.file + 0x48, 4) == 0x2E
    assert r.calls_to(CTOR)[0][0] == frame + 0x50
    assert r.memory.read(r.output + 24, 8) == 0xFACE
    assert not r.calls_to(FORWARD)


def test_buffered_multichunk_copies_actual_bytes_and_refill_processed_cleanup():
    r = Rig()
    r.memory.write(r.file + 0x56, 1, 1)
    assert r.invoke(7) == r.output
    assert r.memory.read_bytes(r.destination, 7) == bytes([0, 1, 10, 11, 12, 10, 11])
    assert [a[2] for a in r.calls_to(COPY)] == [2, 3, 2]
    assert len(r.calls_to(REFILL)) == 2
    assert r.memory.read(r.file + 0x40, 8) == 57
    assert r.memory.read(r.file + 0x58, 8) == 1
    assert r.memory.read(r.file + 0x48, 4) == 0x1111
    frame = r.locals[0][0]
    assert r.events.count(("write", frame + 0x78, 1, 1)) == 2
    assert r.calls_to(CLEAR) == [(frame + 0x80,), (frame + 0x50,), (frame + 0x50,)]


def test_zero_buffer_copy_and_current_count_pointer_cursor_after_callback():
    r = Rig()
    r.memory.write(r.file + 0x56, 1, 1)
    r.memory.write(r.file + 0x58, 8, 0)

    def copy(args):
        assert args[2] == 0
        r.memory.write(r.file + 0x58, 8, 4)
        r.memory.write(r.file + 0x70, 8, r.buffer + 20)
        r.memory.write(r.file + 0x40, 8, 90)
        r.handlers[COPY] = lambda args: r.memory.move(*args)

    r.handlers[COPY] = copy
    assert r.invoke() == r.output
    assert [a[2] for a in r.calls_to(COPY)] == [0, 4]
    assert not r.calls_to(REFILL)
    assert r.memory.read_bytes(r.destination, 4) == bytes(range(20, 24))
    assert r.memory.read(r.file + 0x40, 8) == 94


def test_held_remainder_selects_refill_despite_store_callback_and_next_updates_are_current():
    r = Rig()
    r.memory.write(r.file + 0x56, 1, 1)
    seen = False

    def write(address, width, value):
        nonlocal seen
        if address == r.file + 0x58 and not seen:
            seen = True
            r.memory.write(address, 8, 9)  # Held remainder0 must still select refill.
            r.memory.write(r.file + 0x70, 8, r.buffer + 30)
            r.memory.write(r.file + 0x40, 8, 80)

    r.after_write = write
    assert r.invoke() == r.output
    assert len(r.calls_to(REFILL)) == 1
    assert ("write", r.file + 0x70, 8, r.buffer + 32) in r.events
    assert ("write", r.file + 0x40, 8, 82) in r.events
    assert r.memory.read(r.file + 0x40, 8) == 84


@pytest.mark.parametrize("budget", [0, 1, 3])
def test_buffer_budget_stops_before_next_count_read_and_retains_prior_effects(budget):
    r = Rig()
    r.memory.write(r.file + 0x56, 1, 1)
    r.memory.write(r.file + 0x58, 8, 0)
    r.handlers[REFILL] = lambda args: None  # Successful child with no progress.
    r.profile = replace(r.profile, maximum_buffer_iterations=budget)
    r.bind()
    with pytest.raises(UnresolvedReplayTaskRebuild, match="budget exhausted"):
        r.invoke()
    assert len(r.calls_to(COPY)) == len(r.calls_to(REFILL)) == budget
    assert r.events.count(("read", r.file + 0x58, 8)) == 2 * budget
    assert r.memory.read_bytes(r.output, 48) == b"\xb7" * 48
    assert r.memory.read(r.file + 0x40, 8) == 50
    r.assert_expired()


@pytest.mark.parametrize("name", PATHS)
@pytest.mark.parametrize(
    "guard,epoch,header,initialize",
    [(U32, 0, 0, False), (0x80000000, 0, 0, False), (0, U32, 7, False), (1, 0, U32, True)],
)
def test_all_six_signed_tls_routes_current_guard_and_registration(
    name, guard, epoch, header, initialize
):
    r = Rig()
    target_guard, text, flag, destructor, line = r.path(name)
    r.memory.write(target_guard, 4, guard)
    r.memory.write(r.thread + 0x3B4, 4, epoch)
    r.header_value = header
    assert r.invoke() == r.output
    reached = (guard == 0 and epoch == U32) or guard == 1
    assert r.calls_to(HEADER) == ([(target_guard,)] if reached else [])
    assert r.calls_to(ATEXIT) == ([(destructor,)] if initialize else [])
    assert r.calls_to(FOOTER) == ([(target_guard,)] if initialize else [])
    target = APPEND if name in ("preflight", "mode_child", "refill") else AUGMENT
    assert r.calls_to(target)[0][2] == line
    assert r.memory.read(text + flag, 1) == 0
    r.assert_expired()


@pytest.mark.parametrize("name", PATHS)
def test_missing_gs_refuses_only_at_error_guard_after_prior_source_effects(name):
    r = Rig()
    r.path(name)
    r.profile = replace(r.profile, gs_base=None)
    r.bind()
    with pytest.raises(UnresolvedReplayTaskRebuild, match="GS58"):
        r.invoke()
    assert not r.calls_to(HEADER) and not r.calls_to(APPEND) and not r.calls_to(AUGMENT)
    if name in ("mode", "decoder", "direct"):
        assert len(r.calls_to(CTOR)) == 1 and len(r.calls_to(CLEAR)) >= 2
    assert r.memory.read_bytes(r.output, 48) == b"\xb7" * 48
    r.assert_expired()


@pytest.mark.parametrize(
    "name,getter_index,xor,mask",
    [
        ("preflight", 0, 0x79, 0x1431AB6E0),
        ("mode_child", 1, 0xF0, 0x1431F8270),
        ("refill", 2, 0xF6, 0x1431AD060),
    ],
)
def test_actual_forward_and_detail_decode_before_current_control_cleanup(
    name, getter_index, xor, mask
):
    r = Rig()
    _, text, _, _, line = r.path(name)
    detail = r.details[getter_index]
    r.memory.write(detail + 84, 1, xor)
    control = r.control(strong=1)
    result_offset = 0x80 if name == "preflight" else 0x50

    def append(args):
        assert args[1:] == (detail, line, text)
        r.memory.write(args[0] + 32, 8, control)

    r.handlers[APPEND] = append
    assert r.invoke() == r.output
    frame = r.locals[0][0]
    assert r.calls_to(GETTERS[getter_index]) == [(frame + 0x40,)]
    assert r.calls_to(FORWARD) == [(r.output, frame + result_offset)]
    assert r.memory.read(r.output + 24, 8) == 9
    assert r.memory.read(r.output + 32, 8) == control
    assert r.memory.read(control + 8, 4) == 1  # Actual Forward adds1, caller cleanup subtracts1.
    assert not r.calls_to(0xD1)
    assert r.memory.read_bytes(detail, 16) == bytes(
        x ^ ord("d") for x in r.memory.read_bytes(mask, 16)
    )
    assert r.memory.read(detail + 84, 1) == 0
    processed = ("write", frame + result_offset + 40, 1, 1)
    assert r.events.index(processed) > r.events.index(
        ("child", FORWARD, (r.output, frame + result_offset))
    )
    assert not r.calls_to(AUGMENT)


def test_mode_child_initialization_does_not_overwrite_flag_changed_by_dword_store_callback():
    r = Rig()
    guard, text, _, _, _ = r.path("mode_child")
    r.memory.write(guard, 4, 1)
    r.header_value = U32

    def write(address, width, value):
        if address == text + 16 and width == 4:
            r.memory.write(text + 19, 1, 0)

    r.after_write = write
    assert r.invoke() == r.output
    assert not [e for e in r.events if e[:3] == ("write", text + 19, 1)]
    assert r.memory.read(text + 19, 1) == 0
    assert ("read", 0x1431F8270, 16) not in r.events


def test_mode3_reads_current_data_before_fresh_mask_for_each_block_and_current_staging():
    r = Rig()
    guard, text, _, _, _ = r.path("mode")
    r.memory.write(guard, 4, 1)

    def header(args):
        r.memory.write(guard, 4, U32)
        r.memory.write(r.active[0] + 0xA0, 4, 0x12345678)
        r.memory.write_bytes(0x1431F7CA0, b"\xff" * 16)  # Constants were already held.

    r.handlers[HEADER] = header

    def read(address, width):
        if address in (text, text + 16) and width == 16:
            r.memory.write_bytes(0x1431F7D90, bytes([3 if address == text else 5]) * 16)

    r.after_read = read
    assert r.invoke() == r.output
    assert r.memory.read_bytes(text, 16) == bytes(x ^ 3 for x in range(16))
    assert r.memory.read_bytes(text + 16, 16) == bytes(x ^ 5 for x in range(16, 32))
    assert r.memory.read(text + 32, 4) == 0x12345678 ^ 0x51515151
    assert r.events.count(("read", 0x1431F7D90, 16)) == 2


@pytest.mark.parametrize("name,xor", [("refill", 0xF6), ("direct", 0x37)])
def test_final_flag_uses_held_gate_despite_text_store_callback(name, xor):
    r = Rig()
    _, text, flag, _, _ = r.path(name)
    r.memory.write(text + flag, 1, 0x12)

    def write(address, width, value):
        if address == text:
            r.memory.write(text + flag, 1, 0x77)

    r.after_write = write
    assert r.invoke() == r.output
    assert r.memory.read(text + flag, 1) == 0x12 ^ xor


def test_post_forward_control_is_captured_after_callback_and_uses_current_virtual_slots():
    r = Rig()
    r.path("preflight")
    control, replacement = r.control(), r.memory.allocate(16)
    r.memory.write(replacement + 8, 8, 0xD3)
    r.handlers[0xD3] = lambda args: None

    def forward(args):
        r.memory.write(args[1] + 32, 8, control)

    def destroy(args):
        r.memory.write(control, 8, replacement)

    r.overrides[FORWARD] = forward
    r.handlers[0xD1] = destroy
    assert r.invoke() == r.output
    assert r.calls_to(0xD1) == [(control,)] and r.calls_to(0xD3) == [(control,)]
    assert not r.calls_to(0xD2)
    assert r.memory.read_bytes(r.output, 48) == b"\xb7" * 48
    frame = r.locals[0][0]
    assert ("write", frame + 0xA8, 1, 1) not in r.events


@pytest.mark.parametrize(
    "target,name",
    [
        (MODE, "mode_child"),
        (REFILL, "refill"),
        (COPY, "refill"),
        (GETTERS[0], "preflight"),
        (APPEND, "preflight"),
        (AUGMENT, "mode"),
        (HEADER, "mode"),
        (ATEXIT, "mode"),
        (FOOTER, "mode"),
        (0xBA01, "direct"),
    ],
)
def test_missing_reached_service_preserves_prefix_and_unmaps_local(target, name):
    r = Rig()
    guard, _, _, _, _ = r.path(name)
    if target in (HEADER, ATEXIT, FOOTER):
        r.memory.write(guard, 4, 1)
        r.header_value = U32
    del r.handlers[target]
    with pytest.raises(UnresolvedReplayTaskRebuild, match="missing"):
        r.invoke()
    assert r.memory.read_bytes(r.output, 48) == b"\xb7" * 48
    r.assert_expired()


@pytest.mark.parametrize(
    "channel,name", [("variadic", "mode"), ("decoder", "decoder"), ("calls", "preflight")]
)
def test_missing_dedicated_dispatcher_fails_at_reach(channel, name):
    r = Rig()
    r.path(name)
    r.bind(**{channel: ReplayTaskRebuildCalls(None)})
    with pytest.raises(UnresolvedReplayTaskRebuild):
        r.invoke()
    r.assert_expired()


@pytest.mark.parametrize(
    "field,value",
    [
        ("frame", b""),
        ("frame", bytearray(0xB8)),
        ("gs_base", -1),
        ("gs_base", True),
        ("maximum_buffer_iterations", -1),
        ("maximum_buffer_iterations", True),
    ],
)
def test_profile_rejects_invalid_inputs_before_execution(field, value):
    with pytest.raises(ValueError):
        replace(ReplayFileReadProfile(bytes(0xB8), None, 0), **{field: value})


@pytest.mark.parametrize(
    "args,data",
    [
        ((1, 2, 3), None),
        ((1, 2, 3, -1), None),
        ((1, 2, 3, True), None),
        ((1, 2, 3, 4), memoryview(b"x")),
    ],
)
def test_owned_abi_rejects_before_mapping(args, data):
    r = Rig()
    with pytest.raises(ValueError):
        r.bound.call(READ, args, data)
    assert not r.locals and not r.events


def test_unknown_dispatch_preserves_identity_and_raw_return():
    r = Rig()
    args, data, received = (1, 2), memoryview(b"x"), []

    def delegate(target, actual_args, actual_data):
        received.append((target, actual_args, actual_data))
        return None

    r.bind(calls=ReplayTaskRebuildCalls(delegate))
    assert r.bound.call(0x123, args, data) is None
    assert received[0][1] is args and received[0][2] is data
    assert not r.locals


def test_preflight_processed_store_uses_current_control_and_held_status_branch():
    r = Rig()
    control = r.control()

    def read(address, width):
        if r.active and address == r.active[0] + 0x98:
            r.memory.write(address, 8, 99)

    def write(address, width, value):
        if r.active and address == r.active[0] + 0xA8 and value == 1:
            r.memory.write(r.active[0] + 0xA0, 8, control)
            r.memory.write(r.active[0] + 0x48, 8, 0xBAD)

    r.after_read, r.after_write = read, write
    assert r.invoke(0) == r.output
    assert r.calls_to(0xD1) == [(control,)] and r.calls_to(0xD2) == [(control,)]
    assert not r.calls_to(APPEND)
    assert r.memory.read_bytes(r.output, 48) == bytes(41) + b"\xb7" * 7


def test_decoder_setup_holds_offset_but_reloads_later_state_and_base():
    r = Rig(mode=2)

    def read(address, width):
        if address == r.file + 0x98:
            r.memory.write(r.file + 0xA0, 8, 100)
            r.memory.write(r.file + 0x88, 8, 0x7777)

    def write(address, width, value):
        if r.active and address == r.active[0] + 0x38:
            r.memory.write(r.file + 0x90, 8, 0x6666)

    def decode(args):
        assert args[0:2] == (0x6666, 7)
        assert r.memory.read(args[2], 8) == 23
        assert r.memory.read(args[6], 8) == 0x7777
        r.memory.write(args[2], 8, 2)
        return 0

    r.after_read, r.after_write, r.decode = read, write, decode
    assert r.invoke() == r.output
    assert r.memory.read(r.file + 0xA0, 8) == 102


def test_buffer_wrapped_held_remainder_skips_refill_despite_current_zero():
    r = Rig()
    r.memory.write(r.file + 0x56, 1, 1)
    r.profile = replace(r.profile, maximum_buffer_iterations=1)
    r.bind()

    def copy(args):
        r.memory.move(*args)
        r.memory.write(r.file + 0x58, 8, 1)

    def write(address, width, value):
        if address == r.file + 0x58:
            r.memory.write(address, 8, 0)

    r.handlers[COPY], r.after_write = copy, write
    with pytest.raises(UnresolvedReplayTaskRebuild, match="budget exhausted"):
        r.invoke()
    assert ("write", r.file + 0x58, 8, U64) in r.events
    assert not r.calls_to(REFILL)
    assert r.memory.read_bytes(r.destination, 2) == b"\0\1"
    assert r.memory.read(r.file + 0x40, 8) == 52


def test_output_aliasing_file_cursor_preserves_source_publication_order():
    r = Rig()
    r.output = r.file + 0x40
    assert r.invoke() == r.output
    assert r.events.index(("write", r.file + 0x40, 8, 54)) < r.events.index(
        ("write", r.file + 0x40, 8, 0)
    )
    assert r.memory.read_bytes(r.output, 41) == bytes(41)


@pytest.mark.parametrize("name,code", [("mode", 0x2F), ("decoder", 0x2E), ("direct", 0x25)])
def test_variadic_homes_preserve_upper_dword_and_no_local_result_copy(name, code):
    r = Rig()
    r.path(name)
    original = r.constructor

    def constructor(args):
        frame = r.active[0]
        assert args == (frame + 0x50, 0, 0x1431F7B10, 0xD7, frame + 0x20, frame + 0x28)
        assert r.memory.read(args[4], 8) == 0x1431F7B68
        upper = (frame + 0xB0) & (U32 << 32) if name == "decoder" else 0xC9C9C9C900000000
        assert r.memory.read(args[5], 8) == upper | code
        return original(args)

    r.constructor = constructor
    assert r.invoke() == r.output
    assert not r.calls_to(FORWARD)
    assert r.memory.read_bytes(r.output, 24) == b"\xb7" * 24
    assert r.memory.read(r.output + 24, 8) == 0xFACE


def test_actual_vector_string_and_free_cleanup_after_error_forward_effects():
    r = Rig()
    r.path("preflight")
    vector, data = r.memory.allocate_aligned(32), r.memory.allocate_aligned(24)
    for offset, value in ((0, data), (16, 20), (24, 23)):
        r.memory.write(vector + offset, 8, value)

    def forward(args):
        for offset, value in ((0, vector), (8, vector + 32), (16, vector + 32)):
            r.memory.write(args[1] + offset, 8, value)

    r.overrides[FORWARD] = forward
    assert r.invoke() == r.output
    assert [e for e in r.events if e[0] == "import"] == [
        ("import", 0x142D6BAB4, (data, 24)),
        ("import", 0x142D6BAB4, (vector, 32)),
    ]
    r.assert_expired()


@pytest.mark.parametrize("missing", ["atomics", "slot0", "slot8"])
def test_missing_reached_control_service_stops_after_processed_prefix(missing):
    r = Rig()
    control = r.control()

    def write(address, width, value):
        if r.active and address == r.active[0] + 0xA8 and value == 1:
            r.memory.write(r.active[0] + 0xA0, 8, control)

    r.after_write = write
    if missing == "atomics":
        r.bind(atomics=ReplayUnitAIMapAtomics(None, None))
    else:
        del r.handlers[0xD1 if missing == "slot0" else 0xD2]
    with pytest.raises(UnresolvedReplayTaskRebuild):
        r.invoke(0)
    frame = r.locals[0][0]
    assert ("write", frame + 0xA8, 1, 1) in r.events
    assert not r.calls_to(CLEAR)
    assert r.memory.read_bytes(r.output, 48) == b"\xb7" * 48
    r.assert_expired()
