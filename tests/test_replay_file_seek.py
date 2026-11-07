"""Complete Seek source controls and composition; unowned services are authored."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace

import pytest

from vantage.replay_file_seek import ReplayFileSeekProfile, bind_replay_file_seek
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

SEEK, PREFLIGHT, BUFFERED, BACKEND = 0x1409179E0, 0x140916440, 0x1409166C0, 0x14093A990
CTOR, CLEAR, APPEND, FORWARD = 0x140A08840, 0x1402BD890, 0x140900ED0, 0x1409076B0
GETTER, AUGMENT, HEADER, ATEXIT, FOOTER = (
    0x140913C80,
    0x1408ED8F0,
    0x142D6BF80,
    0x142D6BD04,
    0x142D6BF14,
)
INDEX, LAST_ERROR, GLOBAL = 0x144C9C828, 0x143198A88, 0x144281D30
PRE_GUARD, MODE_GUARD, RANGE_GUARD = 0x14427F1BC, 0x14427F1DC, 0x14427F1F8
PRE_TEXT, MODE_TEXT, RANGE_TEXT, DETAIL = 0x143DA7808, 0x14427F1C0, 0x14427F1E0, 0x14427F160
U32, U64 = (1 << 32) - 1, (1 << 64) - 1


class Rig:
    def __init__(self, *, mode=0, opened=1, epoch=0):
        self.memory = ReplayMemory()
        self.file, self.output = self.memory.allocate(0xA8), self.memory.allocate(48)
        self.gs, self.array, self.thread = (self.memory.allocate(n) for n in (0x60, 24, 0x3B8))
        self.service, self.vptr = self.memory.allocate(8), self.memory.allocate(0x48)
        self.memory.write_bytes(self.output, b"\xb7" * 48)
        for address, width, value in (
            (self.file + 0x54, 1, opened),
            (self.file + 0x80, 4, mode),
            (self.file + 0x48, 4, 0x1111),
            (self.file + 0x4C, 4, 0x2222),
            (self.file + 0x50, 4, 0x3333),
            (self.file + 0x40, 8, 50),
            (self.file + 0x30, 8, 1000),
            (self.file + 0x56, 1, 0),
            (self.file + 0x28, 8, 0x4444),
            (self.file + 0x78, 8, 100),
            (self.file + 0x60, 8, 200),
            (self.file + 0x68, 8, 0x9000),
            (self.file + 0x58, 8, 0x8888),
            (self.gs + 0x58, 8, self.array),
            (self.array + 8, 8, self.thread),
            (self.thread + 0x3B4, 4, epoch),
            (self.service, 8, self.vptr),
            (self.vptr + 0x40, 8, 0xBA02),
        ):
            self.memory.write(address, width, value)
        for address, raw in (
            (INDEX, (1).to_bytes(4, "little")),
            (LAST_ERROR, (0xE001).to_bytes(8, "little")),
            (GLOBAL, self.service.to_bytes(8, "little")),
            (0x143199DD0, (0x142D6BAB4).to_bytes(8, "little")),
            (PRE_GUARD, bytes(4)),
            (MODE_GUARD, bytes(4)),
            (RANGE_GUARD, bytes(4)),
            (0x14427F154, bytes(4)),
            (0x143DA77F8, b"File not open\0"),
            (PRE_TEXT, b"s" * 11 + b"\0"),
            (MODE_TEXT, b"P" * 26 + b"\0"),
            (RANGE_TEXT, b"R" * 21 + b"\0"),
            (DETAIL, b"d" * 84 + b"\0"),
            (0x1431F8130, bytes(range(16))),
            (0x1431F7ED0, bytes(range(16, 32))),
            (0x1431AB3D0, bytes(range(32, 48))),
            (0x1431AC380, bytes(range(48, 64))),
            (0x1431F8200, bytes(range(64, 80))),
        ):
            self.memory.map_bytes(address, raw)
        self.events, self.locals, self.active = [], [], []
        self.after_read, self.after_write = None, None
        self.overrides, self.handlers = {}, {}
        self.header_value, self.ctor_control = 0, 0
        self.profile = ReplayFileSeekProfile(b"\xc9" * 0x70, self.gs)

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
                # Explicit authored services, not claimed native implementations.
                HEADER: lambda args: self.memory.write(args[0], 4, self.header_value),
                ATEXIT: lambda args: None,
                FOOTER: lambda args: self.memory.write(args[0], 4, 0x5A),
                GETTER: lambda args: DETAIL,
                APPEND: lambda args: None,
                AUGMENT: self.augment,
                0xE001: lambda args: 0x12345678ABCDEF01,
                0xBA02: self.backend,
                0xD1: lambda args: None,
                0xD2: lambda args: None,
            }
        )
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

        self.constructor = self.construct
        self.variadic = ReplayTaskRebuildCalls(variadic)
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

    def bind(self, *, calls=None, variadic=None, atomics=None):
        self.bound = bind_replay_file_seek(
            self.storage,
            self.calls if calls is None else calls,
            variadic_calls=self.variadic if variadic is None else variadic,
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
        return 0xBADCAFE

    def augment(self, args):
        self.memory.write(args[0] + 24, 8, 0xFACE)
        return 0xBADD

    def backend(self, args):
        # Explicit service writes the actual position pointer before returning AL1.
        self.memory.write(args[2], 8, args[4])
        return 0x12340001

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
            e[2] for e in self.events if e[0] in ("child", "service", "variadic") and e[1] == target
        ]

    def invoke(self, requested=50):
        return self.bound.call(SEEK, (self.file, self.output, requested), None)

    def failed_preflight(self, args):
        self.memory.write(args[1] + 24, 8, 9)
        return self.output  # Source ignores this returned pointer.

    def path(self, name):
        if name == "preflight":
            self.overrides[PREFLIGHT] = self.failed_preflight
            return PRE_GUARD, PRE_TEXT, 50
        if name == "mode":
            self.memory.write(self.file + 0x80, 4, 1)
            return MODE_GUARD, MODE_TEXT, 50
        return RANGE_GUARD, RANGE_TEXT, 1200

    def assert_expired(self):
        assert not self.active
        for address, _, _ in self.locals:
            with pytest.raises(ReplayMemoryError, match="unmapped"):
                self.memory.read(address, 1)


def test_equal_seek_composes_real_preflight_result_cleanup_and_exact_frame_stores():
    rig = Rig()
    rig.profile = replace(rig.profile, gs_base=None)
    rig.bind(variadic=ReplayTaskRebuildCalls(None))
    assert rig.invoke() == rig.output
    frame, size, seed = rig.locals[0]
    assert (size, seed) == (0x70, b"\xc9" * 0x70)
    assert rig.events[:5] == [
        ("map", frame, 0x70),
        ("write", frame + 0x38, 8, rig.output),
        ("write", frame + 0x40, 16, 0),
        ("write", frame + 0x50, 16, 0),
        ("write", frame + 0x60, 16, 0),
    ]
    assert rig.calls_to(PREFLIGHT) == [(rig.file, frame + 0x40)]
    assert rig.calls_to(CLEAR) == [(frame + 0x40,)]
    assert (
        rig.events.index(("read", frame + 0x58, 8))
        < rig.events.index(("write", frame + 0x68, 1, 1))
        < rig.events.index(("read", frame + 0x60, 8))
    )
    assert rig.memory.read_bytes(rig.output, 48) == bytes(41) + b"\xb7" * 7
    assert rig.memory.read(rig.file + 0x48, 4) == 0x1111
    assert ("read", rig.file + 0x56, 1) not in rig.events
    assert not rig.calls_to(CTOR) and not rig.calls_to(BACKEND)
    rig.assert_expired()


def test_processed_store_and_status_read_callbacks_use_source_held_branch_and_current_control():
    rig = Rig()
    control = rig.control()

    def read(address, width):
        if rig.active and address == rig.active[0] + 0x58:
            rig.memory.write(address, 8, 99)  # Held status was0; do not redispatch.

    def write(address, width, value):
        if rig.active and address == rig.active[0] + 0x68 and value == 1:
            rig.memory.write(rig.active[0] + 0x60, 8, control)
            rig.memory.write(rig.active[0] + 0x38, 8, 0xBAD)

    rig.after_read, rig.after_write = read, write
    assert rig.invoke() == rig.output
    assert rig.calls_to(0xD1) == [(control,)] and rig.calls_to(0xD2) == [(control,)]
    assert not rig.calls_to(GETTER) and not rig.calls_to(AUGMENT)
    assert rig.memory.read_bytes(rig.output, 48) == bytes(41) + b"\xb7" * 7


@pytest.mark.parametrize("requested", [0, 1000, 0x12345678ABCDEF01, U64])
def test_direct_seek_composes_backend_and_clears_only_error48_on_confirmed_position(requested):
    rig = Rig()
    rig.memory.write(rig.file + 0x30, 8, U64)
    assert rig.invoke(requested) == rig.output
    assert rig.calls_to(0xBA02) == [(rig.service, 0x4444, rig.file + 0x40, 0, requested)]
    assert rig.memory.read(rig.file + 0x40, 8) == requested
    assert rig.memory.read(rig.file + 0x48, 4) == 0
    assert rig.memory.read(rig.file + 0x4C, 4) == 0x2222
    assert rig.memory.read(rig.file + 0x50, 4) == 0x3333
    assert rig.memory.read_bytes(rig.output, 48) == bytes(41) + b"\xb7" * 7
    rig.assert_expired()


@pytest.mark.parametrize("requested", [150, 400])
def test_buffered_seek_composes_actual_helper_without_outer_error_reset(requested):
    rig = Rig()
    rig.memory.write(rig.file + 0x56, 1, 1)
    if requested == 400:
        rig.handlers[0xBA02] = lambda args: None  # Buffered source ignores RAX.
    assert rig.invoke(requested) == rig.output
    assert rig.calls_to(BUFFERED) == [(rig.file, rig.output, requested)]
    assert rig.memory.read(rig.file + 0x48, 4) == 0x1111
    assert rig.memory.read(rig.file + 0x58, 8) == (100 if requested == 150 else 0)
    assert rig.memory.read_bytes(rig.output, 48) == bytes(41) + b"\xb7" * 7
    rig.assert_expired()


def test_outer_buffered_path_ignores_child_return_and_does_not_publish_own_result():
    rig = Rig()
    rig.memory.write(rig.file + 0x56, 1, 1)
    rig.overrides[BUFFERED] = lambda args: 0xBADCAFE
    assert rig.invoke(400) == rig.output
    assert rig.memory.read_bytes(rig.output, 48) == b"\xb7" * 48
    assert rig.memory.read(rig.file + 0x48, 4) == 0x1111


@pytest.mark.parametrize(
    ("returned", "position", "reads", "success"),
    [
        (0x12340000, 400, 1, False),
        (1, 399, 2, False),
        (0x12340001, 400, 2, True),
    ],
)
def test_backend_low_al_short_circuit_and_fresh_position_before_source_success(
    returned,
    position,
    reads,
    success,
):
    rig = Rig()

    def backend(args):
        rig.memory.write(args[2], 8, position)
        return returned

    rig.handlers[0xBA02] = backend
    assert rig.invoke(400) == rig.output
    assert rig.events.count(("read", rig.file + 0x40, 8)) == reads
    assert rig.memory.read(rig.file + 0x48, 4) == (0 if success else 0x20)
    if success:
        assert not rig.calls_to(CTOR)
    else:
        assert rig.calls_to(CTOR)[0][0] == rig.output
        assert not rig.calls_to(AUGMENT)
        assert len(rig.calls_to(CLEAR)) == 1  # Only successful preflight cleanup.


def test_backend_none_is_refused_at_actual_al_consumer_after_position_effect():
    rig = Rig()

    def backend(args):
        rig.memory.write(args[2], 8, 400)
        return None

    rig.handlers[0xBA02] = backend
    with pytest.raises(ValueError, match="raw scalar result"):
        rig.invoke(400)
    assert rig.memory.read(rig.file + 0x40, 8) == 400
    assert rig.memory.read(rig.file + 0x48, 4) == 0x1111
    assert rig.memory.read_bytes(rig.output, 48) == b"\xb7" * 48
    rig.assert_expired()


def test_range_gate_precedes_equal_position_and_keeps_last_error_low_dword():
    rig = Rig()
    rig.memory.write(rig.file + 0x40, 8, 1200)
    assert rig.invoke(1200) == rig.output
    assert ("read", rig.file + 0x40, 8) not in rig.events
    assert not rig.calls_to(BACKEND)
    assert rig.memory.read(rig.file + 0x48, 4) == 0x22
    assert rig.memory.read(rig.file + 0x4C, 4) == 0x22
    assert rig.memory.read(rig.file + 0x50, 4) == 0xABCDEF01
    assert rig.calls_to(0xE001) == [()]
    assert rig.calls_to(CTOR)[0][0] == rig.locals[0][0] + 0x40
    assert rig.calls_to(AUGMENT) == [(rig.output, 0x1431F7B10, 0x149, RANGE_TEXT)]


@pytest.mark.parametrize("mode", [1, 2, 3, U32])
def test_every_nonzero_mode_precedes_range_check_and_uses_temporary_constructor(mode):
    rig = Rig(mode=mode)
    assert rig.invoke(U64) == rig.output
    assert ("read", rig.file + 0x30, 8) not in rig.events
    assert rig.memory.read(rig.file + 0x48, 4) == rig.memory.read(rig.file + 0x4C, 4) == 0x30
    assert rig.memory.read(rig.file + 0x50, 4) == 0x3333
    assert rig.calls_to(CTOR)[0][0] == rig.locals[0][0] + 0x40
    assert rig.calls_to(AUGMENT) == [(rig.output, 0x1431F7B10, 0x143, MODE_TEXT)]


@pytest.mark.parametrize(("path", "code"), [("mode", 0x30), ("range", 0x22), ("backend", 0x20)])
def test_variadic_homes_are_live_locations_with_partial_padding_and_correct_destination(path, code):
    rig = Rig()
    if path == "mode":
        rig.memory.write(rig.file + 0x80, 4, 1)
    elif path == "backend":
        rig.handlers[0xBA02] = lambda args: 0
    original = rig.constructor

    def constructor(args):
        frame = rig.locals[0][0]
        assert args == (
            (rig.output if path == "backend" else frame + 0x40),
            0,
            0x1431F7B10,
            0xD7,
            frame + 0x20,
            frame + 0x28,
        )
        assert rig.memory.read(args[4], 8) == 0x1431F7B68
        assert rig.memory.read(args[5], 8) == 0xC9C9C9C900000000 | code
        assert rig.memory.read_bytes(frame + 0x40, 48)[40] == 1
        rig.memory.write(args[4], 8, 0x123456)
        rig.memory.write(args[5], 4, 77)
        assert rig.memory.read(args[4], 8) == 0x123456
        assert rig.memory.read(args[5], 8) == 0xC9C9C9C90000004D
        return original(args)

    rig.constructor = constructor
    assert rig.invoke(1200 if path == "range" else 400) == rig.output
    frame = rig.locals[0][0]
    stores = [e for e in rig.events if e[0] == "write"]
    assert stores.index(("write", frame + 0x28, 4, code)) < stores.index(
        ("write", frame + 0x20, 8, 0x1431F7B68)
    )
    rig.assert_expired()


def test_current_last_error_iat_is_sampled_after_both_file_error_stores():
    rig = Rig()
    rig.handlers[0xE002] = lambda args: 0xFEDCBA9876543210

    def write(address, width, value):
        if address == rig.file + 0x4C and value == 0x22:
            rig.memory.write(LAST_ERROR, 8, 0xE002)

    rig.after_write = write
    rig.invoke(1200)
    assert rig.calls_to(0xE002) == [()] and not rig.calls_to(0xE001)
    assert rig.memory.read(rig.file + 0x50, 4) == 0x76543210


def test_failed_real_preflight_composes_result_forward_without_caller_processed_mark():
    rig = Rig(opened=0)
    assert rig.invoke() == rig.output
    frame = rig.locals[0][0]
    assert [size for _, size, _ in rig.locals] == [0x70, 0x68]
    assert rig.memory.read(rig.file + 0x48, 4) == 31
    assert rig.memory.read(rig.output + 24, 8) == 0xFACE
    assert rig.calls_to(GETTER) == [(frame + 0x30,)]
    assert rig.calls_to(APPEND) == [(frame + 0x40, DETAIL, 0x13E, PRE_TEXT)]
    assert rig.calls_to(FORWARD) == [(rig.output, frame + 0x40)]
    processed = ("write", frame + 0x68, 1, 1)
    assert rig.events.index(processed) > rig.events.index(
        ("child", FORWARD, (rig.output, frame + 0x40))
    )
    assert rig.events.count(processed) == 1  # Actual forward writes it, not caller.
    assert rig.memory.read_bytes(rig.output, 24) == bytes(24)
    assert rig.memory.read_bytes(rig.output + 41, 7) == b"\xb7" * 7
    rig.assert_expired()


def test_append_and_forward_precede_current_control_reload_and_real_heap_cleanup():
    rig = Rig()
    rig.overrides[PREFLIGHT] = rig.failed_preflight
    first, second, final = rig.control(), rig.control(), rig.control()
    vector, data = rig.memory.allocate_aligned(32), rig.memory.allocate_aligned(24)
    for offset, value in ((0, data), (16, 20), (24, 23)):
        rig.memory.write(vector + offset, 8, value)

    def append(args):
        assert rig.memory.read(args[0] + 40, 1) == 0
        rig.memory.write(args[0] + 32, 8, second)

    def forward(args):
        assert rig.memory.read(args[1] + 32, 8) == second
        rig.memory.write(args[1] + 32, 8, final)
        for offset, value in ((0, vector), (8, vector + 32), (16, vector + 32)):
            rig.memory.write(args[1] + offset, 8, value)
        return 0xBAD  # Explicit authored mutation contract to isolate caller order.

    def preflight(args):
        rig.failed_preflight(args)
        rig.memory.write(args[1] + 32, 8, first)

    rig.overrides[PREFLIGHT], rig.overrides[FORWARD] = preflight, forward
    rig.handlers[APPEND] = append
    assert rig.invoke() == rig.output
    assert rig.memory.read(first + 8, 4) == rig.memory.read(second + 8, 4) == 1
    assert rig.memory.read(final + 8, 4) == 0
    assert [e for e in rig.events if e[0] == "import"] == [
        ("import", 0x142D6BAB4, (data, 24)),
        ("import", 0x142D6BAB4, (vector, 32)),
    ]
    frame = rig.locals[0][0]
    assert ("write", frame + 0x68, 1, 1) not in rig.events
    rig.assert_expired()


@pytest.mark.parametrize("path", ["preflight", "mode", "range"])
@pytest.mark.parametrize(
    ("guard", "epoch", "expected"),
    [
        (0, 1, False),
        (U32, 0, False),
        (U32, 0x80000000, True),
        (0x80000000, U32, False),
        (7, 0, True),
    ],
)
def test_all_three_tls_guards_compare_signed_current_guard_with_held_epoch(
    path,
    guard,
    epoch,
    expected,
):
    rig = Rig(epoch=epoch)
    address, _, requested = rig.path(path)
    rig.memory.write(address, 4, guard)
    assert rig.invoke(requested) == rig.output
    assert bool(rig.calls_to(HEADER)) is expected
    assert not rig.calls_to(ATEXIT) and not rig.calls_to(FOOTER)


@pytest.mark.parametrize(
    ("path", "constant", "text", "tail", "destructor"),
    [
        ("mode", 0x1431F8130, MODE_TEXT, bytes.fromhex("d2c4c4d2d397d1dedbd2b7"), 0x143057B10),
        ("range", 0x1431F7ED0, RANGE_TEXT, bytes.fromhex("8b968b8d8ce2"), 0x143057C70),
    ],
)
def test_guard_init_holds_vector_constant_but_rereads_late_local_tail_after_callbacks(
    path,
    constant,
    text,
    tail,
    destructor,
):
    rig = Rig()
    guard, _, requested = rig.path(path)
    rig.memory.write(guard, 4, 7)
    rig.header_value = U32
    held = rig.memory.read_bytes(constant, 16)
    changed = b"\x91" * (8 if path == "mode" else 4)
    word_offset = 0x58 if path == "mode" else 0x54

    def read(address, width):
        if address == rig.gs + 0x58:
            rig.memory.write_bytes(constant, b"\xff" * 16)

    def write(address, width, value):
        if address == text and width == 16:
            rig.memory.write_bytes(rig.locals[0][0] + 0x50, changed)
            rig.memory.write(rig.locals[0][0] + word_offset, 2, 0xBBAA)

    def atexit(args):
        assert args == (destructor,)
        assert rig.memory.read_bytes(text, 16) == held
        expected = changed + b"\xaa\xbb" + (b"\xb7" if path == "mode" else b"")
        assert rig.memory.read_bytes(text + 16, len(tail)) == expected
        assert rig.active == [rig.locals[0][0]]

    rig.after_read, rig.after_write, rig.handlers[ATEXIT] = read, write, atexit
    assert rig.invoke(requested) == rig.output
    assert rig.calls_to(HEADER) == [(guard,)] and rig.calls_to(FOOTER) == [(guard,)]
    assert rig.memory.read(guard, 4) == 0x5A
    rig.assert_expired()


def test_preflight_context_init_decodes_literal_opencheck_and_detail_current_mask_chunks():
    rig = Rig()
    rig.overrides[PREFLIGHT] = rig.failed_preflight
    rig.memory.write(PRE_GUARD, 4, 7)
    rig.header_value = U32
    original = bytes(range(85))
    rig.memory.write_bytes(DETAIL, original)
    mask = bytes(range(32, 48))

    def atexit(args):
        assert args == (0x143057940,)
        assert rig.memory.read_bytes(PRE_TEXT, 12) == bytes.fromhex("2a15000b260d00060e4d4c65")

    rig.handlers[ATEXIT] = atexit
    assert rig.invoke() == rig.output
    assert rig.memory.read_bytes(PRE_TEXT, 12) == b"OpenCheck()\0"
    expected = bytes(value ^ mask[i % 16] for i, value in enumerate(original[:80]))
    expected += bytes(value ^ 0x65 for value in original[80:])
    assert rig.memory.read_bytes(DETAIL, 85) == expected
    reads = [
        e
        for e in rig.events
        if e[0] == "read"
        and e[1] in (DETAIL, DETAIL + 16, DETAIL + 32, DETAIL + 48, DETAIL + 64, 0x1431AB3D0)
    ]
    assert reads == [("read", 0x1431AB3D0, 16)] + [
        ("read", DETAIL + offset, 16) for offset in (0, 16, 32, 48, 64)
    ]


@pytest.mark.parametrize("path", ["preflight", "mode", "range"])
def test_missing_gs_refuses_only_after_reached_temp_cleanup_and_staging(path):
    rig = Rig()
    _, _, requested = rig.path(path)
    rig.profile = replace(rig.profile, gs_base=None)
    rig.bind()
    with pytest.raises(UnresolvedReplayTaskRebuild, match="missing engine GS58"):
        rig.invoke(requested)
    assert rig.calls_to(CLEAR) or path == "preflight"
    assert not rig.calls_to(HEADER) and not rig.calls_to(AUGMENT)
    assert rig.memory.read_bytes(rig.output, 48) == b"\xb7" * 48
    if path != "preflight":
        frame = rig.locals[0][0]
        assert (
            "write",
            frame + 0x50,
            4,
            0xD2C4C4D2 if path == "mode" else 0x8D8B968B,
        ) in rig.events
    rig.assert_expired()


@pytest.mark.parametrize("missing", [GETTER, APPEND, FORWARD, CLEAR, HEADER, ATEXIT, FOOTER])
def test_missing_preflight_error_child_keeps_reached_prefix_and_expires_frame(missing):
    rig = Rig()
    rig.overrides[PREFLIGHT] = rig.failed_preflight
    rig.memory.write(PRE_GUARD, 4, 7)
    rig.header_value = U32

    def fail(args):
        raise UnresolvedReplayTaskRebuild(f"authored child{missing:x} missing")

    rig.overrides[missing] = fail
    with pytest.raises(UnresolvedReplayTaskRebuild, match=f"{missing:x}"):
        rig.invoke()
    assert rig.calls_to(missing)
    if missing != CLEAR:
        assert not rig.calls_to(CLEAR)
    rig.assert_expired()


@pytest.mark.parametrize(("path", "code"), [("mode", 0x30), ("range", 0x22), ("backend", 0x20)])
def test_missing_constructor_is_after_source_error_prefix_and_before_augmentation(path, code):
    rig = Rig()
    if path == "mode":
        rig.memory.write(rig.file + 0x80, 4, 1)
    elif path == "backend":
        rig.handlers[0xBA02] = lambda args: 0
    rig.bind(variadic=ReplayTaskRebuildCalls(None))
    with pytest.raises(UnresolvedReplayTaskRebuild, match="140a08840"):
        rig.invoke(1200 if path == "range" else 400)
    assert rig.memory.read(rig.file + 0x48, 4) == rig.memory.read(rig.file + 0x4C, 4) == code
    assert not rig.calls_to(AUGMENT)
    assert rig.memory.read_bytes(rig.output, 48) == b"\xb7" * 48
    assert len(rig.calls_to(CLEAR)) == 1
    rig.assert_expired()


def test_missing_actual_backend_keeps_successful_preflight_but_no_error_synthesis():
    rig = Rig()
    rig.handlers.pop(0xBA02)
    with pytest.raises(UnresolvedReplayTaskRebuild, match="ba02"):
        rig.invoke(400)
    assert rig.memory.read(rig.file + 0x48, 4) == 0x1111
    assert rig.memory.read_bytes(rig.output, 48) == b"\xb7" * 48
    assert not rig.calls_to(CTOR)
    rig.assert_expired()


@pytest.mark.parametrize("bad", [True, -1, 1 << 64, None])
def test_bad_abi_data_arity_refuse_before_storage(bad):
    rig = Rig()
    with pytest.raises(ValueError):
        rig.bound.call(SEEK, (bad, 0, 0), None)
    with pytest.raises(ValueError):
        rig.bound.call(SEEK, (0, 0, 0), memoryview(bytearray(1)))
    with pytest.raises(ValueError):
        rig.bound.call(SEEK, (0, 0), None)
    assert not rig.events


@pytest.mark.parametrize("bad", [bytes(0x6F), b"", bytearray(0x70), None])
def test_profile_requires_exact_immutable_frame(bad):
    with pytest.raises(ValueError):
        ReplayFileSeekProfile(bad, None)


@pytest.mark.parametrize("bad", [True, -1, 1 << 64])
def test_profile_gs_requires_unsigned_raw_base_or_none(bad):
    with pytest.raises(ValueError):
        ReplayFileSeekProfile(bytes(0x70), bad)


def test_unknown_delegate_keeps_argument_payload_and_return_identities():
    rig = Rig()
    args, data, value, seen = (object(),), memoryview(bytearray(1)), object(), []

    def call(target, actual_args, actual_data):
        seen.append((target, actual_args, actual_data))
        return value

    rig.bind(calls=ReplayTaskRebuildCalls(call))
    assert rig.bound.call(0x9876543210, args, data) is value
    assert seen[0][1] is args and seen[0][2] is data
    rig.bind(calls=ReplayTaskRebuildCalls(None))
    with pytest.raises(UnresolvedReplayTaskRebuild, match="9876543210"):
        rig.bound.call(0x9876543210, args, data)
    assert not rig.events
