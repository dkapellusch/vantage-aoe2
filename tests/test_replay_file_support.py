"""File caller/dispatch source controls; external constructors/backends are authored."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace

import pytest

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

PREFLIGHT, BUFFERED, READ, SEEK = 0x140916440, 0x1409166C0, 0x14093A930, 0x14093A990
CTOR, CLEAR, AUGMENT = 0x140A08840, 0x1402BD890, 0x1408ED8F0
HEADER, ATEXIT, FOOTER = 0x142D6BF80, 0x142D6BD04, 0x142D6BF14
GLOBAL, GUARD, TEXT, INDEX = 0x144281D30, 0x14427F154, 0x143DA77F8, 0x144C9C828
U64, U32 = (1 << 64) - 1, (1 << 32) - 1


class Rig:
    def __init__(self, *, opened=1, guard=0, epoch=0):
        self.memory = ReplayMemory()
        self.file, self.output = self.memory.allocate(0xA8), self.memory.allocate(48)
        self.gs, self.array, self.thread = (self.memory.allocate(n) for n in (0x60, 24, 0x3B8))
        self.service, self.vptr = self.memory.allocate(8), self.memory.allocate(0x48)
        self.memory.write_bytes(self.output, b"\xb7" * 48)
        for address, width, value in (
            (self.file + 0x54, 1, opened),
            (self.file + 0x48, 4, 0x1111),
            (self.file + 0x4C, 4, 0x2222),
            (self.file + 0x40, 8, 50),
            (self.file + 0x30, 8, 1000),
            (self.file + 0x78, 8, 100),
            (self.file + 0x60, 8, 200),
            (self.file + 0x68, 8, 0x9000),
            (self.file + 0x70, 8, 0x9111),
            (self.file + 0x58, 8, 0x8888),
            (self.file + 0x57, 1, 0),
            (self.file + 0x28, 8, 0x4444),
            (self.gs + 0x58, 8, self.array),
            (self.array + 8, 8, self.thread),
            (self.thread + 0x3B4, 4, epoch),
            (self.service, 8, self.vptr),
            (self.vptr + 0x38, 8, 0xBA01),
            (self.vptr + 0x40, 8, 0xBA02),
        ):
            self.memory.write(address, width, value)
        for address, width, value in (
            (GLOBAL, 8, self.service),
            (GUARD, 4, guard),
            (INDEX, 4, 1),
            (0x143199DD0, 8, 0x142D6BAB4),
        ):
            self.memory.map_bytes(address, value.to_bytes(width, "little"))
        self.memory.map_bytes(TEXT, b"ABCDEFGHIJKLM\0")
        self.events, self.locals, self.active = [], [], []
        self.after_read, self.after_write = None, None
        self.ctor_control, self.header_value = 0, 0
        self.profile = ReplayFileSupportProfile(b"\xa5" * 0x68, b"\xc6" * 0x28, self.gs)

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
        self.handlers = {
            HEADER: lambda args: self.memory.write(GUARD, 4, self.header_value),
            ATEXIT: lambda args: None,
            FOOTER: lambda args: self.memory.write(GUARD, 4, 0x5A),
            AUGMENT: self.augment,
            0xBA01: lambda args: 0x123456789ABCDE00,
            0xBA02: lambda args: None,
            0xD1: lambda args: None,
            0xD2: lambda args: None,
        }
        runtime = self.memory.runtime_calls()

        def imported(target, args, data):
            self.events.append(("import", target, args))
            return runtime.call(target, args, data)

        def call(target, args, data):
            assert data is None
            self.events.append(("call", target, args))
            if target == CLEAR and target not in self.handlers:
                return self.results.call(target, args, data)
            if target not in self.handlers:
                raise UnresolvedReplayTaskRebuild(f"actual test child{target:x} unavailable")
            return self.handlers[target](args)

        self.calls = ReplayTaskRebuildCalls(call)
        terminal = ReplayTaskRebuildCalls(imported)
        strings = bind_replay_saved_string(self.storage, self.calls, imports=terminal)
        self.results = bind_replay_saved_result(
            self.storage, strings, atomics=self.atomics, imports=terminal
        )
        self.constructor = self.construct

        def variadic(target, args, data):
            assert target == CTOR and data is None
            self.events.append(("variadic", target, args))
            return self.constructor(args)

        self.variadic = ReplayTaskRebuildCalls(variadic)
        self.bind()

    def bind(self, *, variadic=None, atomics=None):
        self.bound = bind_replay_file_support(
            self.storage,
            self.calls,
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
        # Explicit authored constructor contract; native variadic body is unowned.
        result = args[0]
        self.memory.write_bytes(result, b"\xd7" * 48)
        self.memory.write(result, 8, 0)
        self.memory.write(result + 24, 8, 0xEEEE)
        self.memory.write(result + 32, 8, self.ctor_control)
        return 0xBADCAFE

    def augment(self, args):
        self.memory.write(args[0] + 24, 8, 0xFACE)
        return 0xBADD  # Source must still return the held entry output.

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

    def invoke(self, target=PREFLIGHT, args=None):
        if args is None:
            args = (self.file, self.output)
        return self.bound.call(target, args, None)

    def calls_to(self, target):
        return [e[2] for e in self.events if e[0] in ("call", "variadic") and e[1] == target]

    def assert_expired(self):
        assert not self.active
        for address, _, _ in self.locals:
            with pytest.raises(ReplayMemoryError, match="unmapped"):
                self.memory.read(address, 1)


@pytest.mark.parametrize("opened", [1, 128, 255])
def test_positive_preflight_only_reads_flag_and_writes_exact41_bytes(opened):
    rig = Rig(opened=opened)
    rig.profile = replace(rig.profile, gs_base=None)
    rig.bind(variadic=ReplayTaskRebuildCalls(None))
    assert rig.invoke() == rig.output
    assert rig.memory.read_bytes(rig.output, 48) == bytes(41) + b"\xb7" * 7
    assert rig.events == [("read", rig.file + 0x54, 1)] + [
        ("write", rig.output + offset, 8, 0) for offset in (0, 8, 16, 24, 32)
    ] + [("write", rig.output + 40, 1, 0)]
    assert rig.memory.read(rig.file + 0x48, 4) == 0x1111


def test_successful_output_alias_can_clear_file_flag_after_sole_branch_test():
    rig = Rig()
    output = rig.file + 0x30
    rig.memory.write_bytes(output, b"\xb7" * 48)
    rig.memory.write(rig.file + 0x54, 1, 1)
    assert rig.invoke(args=(rig.file, output)) == output
    assert rig.memory.read_bytes(output, 48) == bytes(41) + b"\xb7" * 7
    assert rig.memory.read(rig.file + 0x54, 1) == 0
    assert not rig.calls_to(CTOR) and not rig.locals


def test_preflight_constructor_receives_live_home_locations_and_unwritten_padding():
    rig = Rig(opened=0)
    original = rig.constructor

    def constructor(args):
        frame, size, seed = rig.locals[0]
        assert (size, seed) == (0x68, b"\xa5" * 0x68)
        assert args == (frame + 0x38, 0, 0x1431F7B10, 0xD7, frame + 0x20, frame + 0x28)
        expected = bytearray(b"\xa5" * 0x68)
        expected[0x28:0x2C] = (31).to_bytes(4, "little")
        expected[0x20:0x28] = (0x1431F7B68).to_bytes(8, "little")
        assert rig.memory.read_bytes(frame, size) == bytes(expected)
        # An intervening authored child changes the values before consumption.
        rig.memory.write(args[4], 8, 0x123456789ABC)
        rig.memory.write(args[5], 4, 77)
        assert rig.memory.read(args[4], 8) == 0x123456789ABC
        assert rig.memory.read(args[5], 8) == 0xA5A5A5A50000004D
        return original(args)

    rig.constructor = constructor
    assert rig.invoke() == rig.output
    frame = rig.locals[0][0]
    stores = [e for e in rig.events if e[0] == "write"]
    assert stores[:4] == [
        ("write", rig.file + 0x48, 4, 31),
        ("write", rig.file + 0x4C, 4, 31),
        ("write", frame + 0x28, 4, 31),
        ("write", frame + 0x20, 8, 0x1431F7B68),
    ]
    assert rig.calls_to(CLEAR) == [(frame + 0x38,)]
    assert rig.calls_to(AUGMENT) == [(rig.output, 0x1431F7B10, 0xB5, TEXT)]
    assert rig.memory.read(rig.output + 24, 8) == 0xFACE
    assert ("read", frame + 0x50, 8) not in rig.events  # No temp status read.
    assert not any(e[0] == "write" and e[1] == frame + 0x60 for e in rig.events)
    rig.assert_expired()


@pytest.mark.parametrize(
    ("strong", "weak", "virtuals"),
    [
        (0, 1, []),
        (2, 1, []),
        (1, 0, [0xD1]),
        (1, 2, [0xD1]),
        (1, 1, [0xD1, 0xD2]),
    ],
)
def test_error_temp_inline_atomic_release_precedes_real_alias_cleanup(strong, weak, virtuals):
    rig = Rig(opened=0)
    control = rig.control(strong, weak)
    rig.ctor_control = control
    assert rig.invoke() == rig.output
    selected = [e[1] for e in rig.events if e[0] == "call" and e[1] in (0xD1, 0xD2, CLEAR)]
    assert selected == [*virtuals, CLEAR]
    assert rig.memory.read(control + 8, 4) == (strong - 1) & U32
    assert rig.memory.read(control + 12, 4) == ((weak - 1) & U32 if strong == 1 else weak)


def test_error_cleanup_keeps_held_control_and_uses_current_weak_vptr():
    rig = Rig(opened=0)
    held, other, table = rig.control(), rig.control(), rig.memory.allocate(16)
    rig.memory.write(table + 8, 8, 0xD3)
    rig.ctor_control = held

    def destroy(args):
        assert args == (held,)
        rig.memory.write(rig.locals[0][0] + 0x58, 8, other)
        rig.memory.write(held, 8, table)

    rig.handlers[0xD1], rig.handlers[0xD3] = destroy, lambda args: None
    assert rig.invoke() == rig.output
    assert rig.calls_to(0xD3) == [(held,)]
    assert rig.memory.read(other + 8, 4) == 1


def test_real_nonempty_error_result_alias_cleans_heap_string_and_vector_before_gs():
    rig = Rig(opened=0)
    rig.profile = replace(rig.profile, gs_base=None)
    rig.bind()
    vector, data = rig.memory.allocate_aligned(32), rig.memory.allocate_aligned(24)
    for offset, value in ((0, data), (16, 20), (24, 23)):
        rig.memory.write(vector + offset, 8, value)
    original = rig.constructor

    def constructor(args):
        original(args)
        for offset, value in ((0, vector), (8, vector + 32), (16, vector + 32)):
            rig.memory.write(args[0] + offset, 8, value)

    rig.constructor = constructor
    with pytest.raises(UnresolvedReplayTaskRebuild, match="missing engine GS58"):
        rig.invoke()
    assert [e for e in rig.events if e[0] == "import"] == [
        ("import", 0x142D6BAB4, (data, 24)),
        ("import", 0x142D6BAB4, (vector, 32)),
    ]
    assert not rig.calls_to(AUGMENT)
    for pointer in (data, vector):
        with pytest.raises(ReplayMemoryError, match="unmapped"):
            rig.memory.read(pointer, 1)
    rig.assert_expired()


@pytest.mark.parametrize(
    ("guard", "epoch", "header"),
    [
        (0, 1, False),
        (U32, 0, False),
        (U32, 0x80000000, True),
        (0x80000000, U32, False),
        (7, 0, True),
    ],
)
def test_tls_guard_comparison_is_signed_and_epoch_is_not_a_boolean(guard, epoch, header):
    rig = Rig(opened=0, guard=guard, epoch=epoch)
    rig.invoke()
    assert bool(rig.calls_to(HEADER)) is header
    assert not rig.calls_to(ATEXIT) and not rig.calls_to(FOOTER)
    assert rig.memory.read_bytes(TEXT, 14) == b"ABCDEFGHIJKLM\0"


def test_current_gs_index_guard_and_held_array_epoch_read_order():
    rig = Rig(opened=0)
    new_array, thread2 = rig.memory.allocate(24), rig.memory.allocate(0x3B8)
    rig.memory.write(rig.array + 16, 8, thread2)
    rig.memory.write(thread2 + 0x3B4, 4, 0x80000000)

    def read(address, width):
        if address == rig.gs + 0x58:
            rig.memory.write(address, 8, new_array)
            rig.memory.write(INDEX, 4, 2)
        elif address == thread2 + 0x3B4:
            rig.memory.write(address, 4, 0x7FFFFFFF)
            rig.memory.write(GUARD, 4, U32)

    rig.after_read = read
    rig.invoke()
    assert rig.calls_to(HEADER) == [(GUARD,)]  # Held negative epoch/current-1 guard.
    addresses = [e[1] for e in rig.events if e[0] == "read"]
    sequence = [rig.gs + 0x58, INDEX, rig.array + 16, thread2 + 0x3B4, GUARD]
    assert [address for address in addresses if address in sequence][:5] == sequence
    assert new_array not in addresses and new_array + 16 not in addresses


def test_guard_initialization_literal_stores_then_atexit_footer_then_fourteen_current_xors():
    rig = Rig(opened=0, guard=7)
    rig.header_value = U32
    encoded = bytes.fromhex("715e5b5217595843175847525937")

    def atexit(args):
        assert args == (0x1430575C0,)
        assert rig.memory.read_bytes(TEXT, 14) == encoded
        assert rig.active == [rig.locals[0][0]]

    rig.handlers[ATEXIT] = atexit
    assert rig.invoke() == rig.output
    assert rig.memory.read_bytes(TEXT, 14) == b"File not open\0"
    assert rig.memory.read(GUARD, 4) == 0x5A
    targets = [e[1] for e in rig.events if e[0] == "call"]
    assert (
        targets.index(HEADER)
        < targets.index(ATEXIT)
        < targets.index(FOOTER)
        < targets.index(AUGMENT)
    )
    writes = [e for e in rig.events if e[0] == "write" and TEXT <= e[1] < TEXT + 14]
    assert writes[:4] == [
        ("write", TEXT, 4, 0x525B5E71),
        ("write", TEXT + 4, 4, 0x43585917),
        ("write", TEXT + 8, 4, 0x52475817),
        ("write", TEXT + 12, 2, 0x3759),
    ]
    assert writes[4:] == [
        ("write", TEXT + i, 1, value) for i, value in enumerate(b"File not open\0")
    ]
    rig.assert_expired()


def test_decoder_uses_current_each_byte_and_does_not_retest_flag_inside_loop():
    rig = Rig(opened=0)
    rig.memory.write_bytes(TEXT, b"a" * 13 + b"\x01")

    def store(address, width, value):
        if address == TEXT:
            rig.memory.write(TEXT + 1, 1, 0x40)
            rig.memory.write(TEXT + 13, 1, 3)

    rig.after_write = store
    rig.invoke()
    assert rig.memory.read_bytes(TEXT, 14) == b"Vw" + b"V" * 11 + b"4"
    selected = [e for e in rig.events if e[0] in ("read", "write") and TEXT <= e[1] < TEXT + 14]
    assert selected[0] == ("read", TEXT + 13, 1)
    for index in range(14):
        assert selected[1 + index * 2][:3] == ("read", TEXT + index, 1)
        assert selected[2 + index * 2][:3] == ("write", TEXT + index, 1)


@pytest.mark.parametrize("missing", [CTOR, CLEAR, HEADER, ATEXIT, FOOTER, AUGMENT])
def test_missing_error_child_preserves_prefix_and_expires_live_frame(missing):
    rig = Rig(opened=0, guard=7)
    rig.header_value = U32
    if missing == CTOR:
        rig.bind(variadic=ReplayTaskRebuildCalls(None))
    elif missing == CLEAR:

        def fail(args):
            raise UnresolvedReplayTaskRebuild(f"actual test child{CLEAR:x} unavailable")

        rig.handlers[CLEAR] = fail
    else:
        rig.handlers.pop(missing)
    with pytest.raises(UnresolvedReplayTaskRebuild, match=f"{missing:x}"):
        rig.invoke()
    assert rig.memory.read(rig.file + 0x48, 4) == rig.memory.read(rig.file + 0x4C, 4) == 31
    assert rig.memory.read_bytes(rig.output, 48) == b"\xb7" * 48
    if missing != CTOR:
        assert rig.calls_to(missing)
    rig.assert_expired()


def test_missing_atomic_is_after_constructor_and_before_alias_cleanup():
    rig = Rig(opened=0)
    control = rig.control()
    rig.ctor_control = control
    rig.bind(atomics=ReplayUnitAIMapAtomics(None, None))
    with pytest.raises(UnresolvedReplayTaskRebuild, match="atomic effect unavailable"):
        rig.invoke()
    assert rig.calls_to(CTOR) and not rig.calls_to(CLEAR)
    assert rig.memory.read(control + 8, 4) == 1
    rig.assert_expired()


def test_buffered_equal_position_reads_no_other_file_fields_or_backend():
    rig = Rig()
    assert rig.invoke(BUFFERED, (rig.file, rig.output, 50)) == rig.output
    assert [e for e in rig.events if e[0] == "read"] == [("read", rig.file + 0x40, 8)]
    assert rig.memory.read_bytes(rig.output, 48) == bytes(41) + b"\xb7" * 7
    assert rig.memory.read(rig.file + 0x57, 1) == 0 and not rig.locals


@pytest.mark.parametrize(
    ("requested", "anchor", "length", "total", "inside", "pointer", "count"),
    [
        (150, 100, 200, 1000, True, 0x9032, 100),
        (100, 100, 200, 1000, True, 0x9000, 100),
        (299, 100, 200, 1000, True, 0x90C7, 100),
        (300, 100, 200, 1000, False, 0x9000, 0),
        (99, 100, 200, 1000, False, 0x9000, 0),
        (1000, 100, 200, 1000, False, 0x9000, 0),
        (U64 - 3, U64 - 5, 10, U64, False, 0x9000, 0),
        (105, 100, 10, 1000, True, 0x9005, U64 - 89),
    ],
)
def test_buffered_window_boundaries_wrap_and_literal_length_minus_anchor(
    requested,
    anchor,
    length,
    total,
    inside,
    pointer,
    count,
):
    rig = Rig()
    for offset, value in ((0x40, 0), (0x78, anchor), (0x60, length), (0x30, total)):
        rig.memory.write(rig.file + offset, 8, value)
    assert rig.invoke(BUFFERED, (rig.file, rig.output, requested)) == rig.output
    assert rig.memory.read(rig.file + 0x70, 8) == pointer
    assert rig.memory.read(rig.file + 0x58, 8) == count
    assert rig.memory.read(rig.file + 0x78, 8) == (anchor if inside else requested)
    assert bool(rig.calls_to(0xBA02)) is not inside
    assert rig.memory.read(rig.file + 0x48, 4) == 0x1111
    assert rig.memory.read_bytes(rig.output, 48) == bytes(41) + b"\xb7" * 7


def test_buffered_inside_retains_held_operands_across_current_base_and_store_callbacks():
    rig = Rig()

    def read(address, width):
        if address == rig.file + 0x68:
            rig.memory.write(address, 8, 0xB000)

    def store(address, width, value):
        if address == rig.file + 0x70:
            rig.memory.write(rig.file + 0x78, 8, 1)
            rig.memory.write(rig.file + 0x60, 8, 2)

    rig.after_read, rig.after_write = read, store
    rig.invoke(BUFFERED, (rig.file, rig.output, 150))
    assert rig.memory.read(rig.file + 0x70, 8) == 0x9032
    assert rig.memory.read(rig.file + 0x58, 8) == 100
    assert not rig.calls_to(0xBA02)


@pytest.mark.parametrize(("first", "calls", "reads"), [(U64, 0, 1), (0x4444, 1, 2)])
def test_buffered_outside_handle_compare_and_reload_are_separate(first, calls, reads):
    rig = Rig()
    rig.memory.write(rig.file + 0x28, 8, first)

    def read(address, width):
        if address == rig.file + 0x28:
            rig.memory.write(address, 8, 0x5555)

    rig.after_read = read
    rig.invoke(BUFFERED, (rig.file, rig.output, 400))
    assert len(rig.calls_to(0xBA02)) == calls
    assert rig.events.count(("read", rig.file + 0x28, 8)) == reads
    if calls:
        assert rig.calls_to(0xBA02) == [(rig.service, 0x5555, 0, 0, 400)]


@pytest.mark.parametrize("returned", [None, 0, 0x123400])
def test_buffered_seek_ignores_backend_return_and_publishes_source_success(returned):
    rig = Rig()
    rig.handlers[0xBA02] = lambda args: returned
    assert rig.invoke(BUFFERED, (rig.file, rig.output, 400)) == rig.output
    assert rig.calls_to(0xBA02) == [(rig.service, 0x4444, 0, 0, 400)]
    assert rig.memory.read_bytes(rig.output, 48) == bytes(41) + b"\xb7" * 7
    rig.assert_expired()


def test_missing_buffered_backend_preserves_ordered_file_stores_without_result_success():
    rig = Rig()
    rig.handlers.pop(0xBA02)
    with pytest.raises(UnresolvedReplayTaskRebuild, match="ba02"):
        rig.invoke(BUFFERED, (rig.file, rig.output, 400))
    writes = [e for e in rig.events if e[0] == "write" and rig.file <= e[1] < rig.file + 0xA8]
    assert writes == [
        ("write", rig.file + 0x57, 1, 1),
        ("write", rig.file + 0x40, 8, 400),
        ("write", rig.file + 0x70, 8, 0x9000),
        ("write", rig.file + 0x58, 8, 0),
        ("write", rig.file + 0x78, 8, 400),
    ]
    assert rig.memory.read_bytes(rig.output, 48) == b"\xb7" * 48
    rig.assert_expired()


@pytest.mark.parametrize(
    ("target", "method", "fourth"), [(READ, 0xBA01, 0x12345678AABBCCDD), (SEEK, 0xBA02, 0xAABBCCDD)]
)
@pytest.mark.parametrize("returned", [None, 0, 0xFEDCBA9876543210])
def test_backend_full_count_vs_low_mode_and_transparent_raw_or_none_return(
    target,
    method,
    fourth,
    returned,
):
    rig = Rig()
    rig.handlers[method] = lambda args: returned
    assert rig.invoke(target, (0x11, 0x22, 0x12345678AABBCCDD, 0x3344)) is returned
    assert rig.calls_to(method) == [(rig.service, 0x11, 0x22, fourth, 0x3344)]
    frame, size, seed = rig.locals[0]
    assert (size, seed) == (0x28, b"\xc6" * 0x28)
    assert [e for e in rig.events if e[0] == "write"] == [("write", frame + 0x20, 8, 0x3344)]
    rig.assert_expired()


@pytest.mark.parametrize(("target", "slot", "method"), [(READ, 0x38, 0xBA01), (SEEK, 0x40, 0xBA02)])
def test_backend_holds_service_and_vptr_but_samples_fifth_home_after_target_read(
    target,
    slot,
    method,
):
    rig = Rig()
    other, table = rig.memory.allocate(8), rig.memory.allocate(0x48)

    def store(address, width, value):
        if rig.active and address == rig.active[0] + 0x20:
            rig.memory.write(GLOBAL, 8, other)

    def read(address, width):
        if address == rig.vptr + slot:
            rig.memory.write(rig.service, 8, table)
            rig.memory.write(address, 8, 0xDEAD)
            rig.memory.write(rig.active[0] + 0x20, 8, 0x9876)

    rig.after_write, rig.after_read = store, read
    rig.invoke(target, (1, 2, 3, 4))
    assert rig.calls_to(method) == [(rig.service, 1, 2, 3, 0x9876)]
    assert rig.events.count(("read", GLOBAL, 8)) == 1
    assert ("read", table + slot, 8) not in rig.events


def test_partial_success_store_exception_keeps_prefix_without_transaction_or_local():
    rig = Rig()

    def store(address, width, value):
        if address == rig.output + 16:
            raise UnresolvedReplayTaskRebuild("authored store observer stopped")

    rig.after_write = store
    with pytest.raises(UnresolvedReplayTaskRebuild, match="observer stopped"):
        rig.invoke()
    assert rig.memory.read_bytes(rig.output, 48) == bytes(24) + b"\xb7" * 24
    assert not rig.locals


@pytest.mark.parametrize(("entry", "arity"), [(PREFLIGHT, 2), (BUFFERED, 3), (READ, 4), (SEEK, 4)])
@pytest.mark.parametrize("bad", [True, -1, 1 << 64, None])
def test_known_bad_abi_data_and_arity_refuse_before_storage(entry, arity, bad):
    rig = Rig()
    with pytest.raises(ValueError):
        rig.invoke(entry, (bad,) + (0,) * (arity - 1))
    with pytest.raises(ValueError):
        rig.bound.call(entry, (0,) * arity, memoryview(bytearray(1)))
    with pytest.raises(ValueError):
        rig.invoke(entry, (0,) * (arity + 1))
    assert not rig.events


@pytest.mark.parametrize("bad", [b"", bytearray(0x68), None, bytes(0x67)])
def test_profile_seeds_require_exact_immutable_lengths(bad):
    with pytest.raises(ValueError):
        ReplayFileSupportProfile(bad, bytes(0x28), None)
    with pytest.raises(ValueError):
        ReplayFileSupportProfile(bytes(0x68), bad, None)


@pytest.mark.parametrize("bad", [True, -1, 1 << 64])
def test_profile_gs_requires_explicit_raw_base_or_none(bad):
    with pytest.raises(ValueError):
        ReplayFileSupportProfile(bytes(0x68), bytes(0x28), bad)


def test_unknown_delegation_preserves_args_payload_and_result_identities():
    rig = Rig()
    args, data, value, seen = (object(),), memoryview(bytearray(1)), object(), []

    def call(target, actual_args, actual_data):
        seen.append((target, actual_args, actual_data))
        return value

    bound = bind_replay_file_support(
        rig.storage,
        ReplayTaskRebuildCalls(call),
        variadic_calls=rig.variadic,
        atomics=rig.atomics,
        bind_local=rig.bind_local,
        profile=rig.profile,
    )
    assert bound.call(0x9876543210, args, data) is value
    assert seen[0][1] is args and seen[0][2] is data
    absent = bind_replay_file_support(
        rig.storage,
        ReplayTaskRebuildCalls(None),
        variadic_calls=rig.variadic,
        atomics=rig.atomics,
        bind_local=rig.bind_local,
        profile=rig.profile,
    )
    with pytest.raises(UnresolvedReplayTaskRebuild, match="9876543210"):
        absent.call(0x9876543210, args, data)
    assert not rig.events
