"""Source-led backend and live-home composition controls; OS fixtures are authored."""

from __future__ import annotations

import io
from contextlib import contextmanager
from dataclasses import replace

import pytest

from vantage.replay_file_backend import (
    ReplayFileBackendProfile,
    bind_replay_file_backend_homes,
)
from vantage.replay_file_read import ReplayFileReadProfile, bind_replay_file_read
from vantage.replay_file_seek import ReplayFileSeekProfile, bind_replay_file_seek
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

READ, SEEK = 0x141756EA0, 0x141757120
READ_SHIM, SEEK_SHIM, READ_FILE, SEEK_FILE = (
    0x14093A930,
    0x14093A990,
    0x140916DB0,
    0x1409179E0,
)
READ_IAT, SEEK_IAT, ERROR_IAT = 0x143198988, 0x1431989A8, 0x143198A88
LOGGER, GLOBAL = 0x1417583C0, 0x144281D30
READ_OS, SEEK_OS, ERROR_OS = 0xFA01, 0xFA02, 0xFA03
U32, U64 = (1 << 32) - 1, (1 << 64) - 1


class Rig:
    def __init__(self):
        self.memory = ReplayMemory()
        self.output, self.other, self.home, self.destination = (
            self.memory.allocate(n) for n in (8, 8, 8, 64)
        )
        self.memory.write_bytes(self.output, b"A" * 8)
        self.memory.write_bytes(self.other, b"B" * 8)
        self.memory.write(self.home, 8, self.output)
        self.service, self.vptr = self.memory.allocate(8), self.memory.allocate(0x48)
        self.memory.write(self.service, 8, self.vptr)
        self.memory.write(self.vptr + 0x38, 8, READ)
        self.memory.write(self.vptr + 0x40, 8, SEEK)
        for address, value in (
            (READ_IAT, READ_OS),
            (SEEK_IAT, SEEK_OS),
            (ERROR_IAT, ERROR_OS),
            (GLOBAL, self.service),
        ):
            self.memory.map_bytes(address, value.to_bytes(8, "little"))
        self.events, self.locals, self.active = [], [], []
        self.after_read, self.after_write = None, None
        self.profile = ReplayFileBackendProfile(b"R" * 0x38, b"S" * 0x28)
        self.read_raw, self.seek_raw, self.error_raw, self.logger_raw = (
            0x100,
            0x100,
            0xABCD12345678,
            0x1122334455667788,
        )
        self.os_handlers = {
            READ_OS: self.read_os,
            SEEK_OS: self.seek_os,
            ERROR_OS: lambda args: self.error_raw,
        }
        self.generic_handlers = {}

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

        def os_call(target, args, data):
            assert data is None
            self.events.append(("os", target, args))
            if target not in self.os_handlers:
                raise UnresolvedReplayTaskRebuild(f"owned OS capability{target:x} missing")
            return self.os_handlers[target](args)

        def strict_home_delegate(target, args, data):
            assert data is None
            self.events.append(("strict", target, args))
            if target != LOGGER or len(args) != 2:
                raise UnresolvedReplayTaskRebuild(f"unknown HOME target{target:x}")
            return self.logger_raw

        self.storage = ReplayTaskRebuildStorage(1, read, write)
        self.os_calls = ReplayTaskRebuildCalls(os_call)
        self.strict = ReplayTaskRebuildCalls(strict_home_delegate)
        self.bind()

    def bind(self, *, calls=None, os_calls=None):
        self.bound = bind_replay_file_backend_homes(
            self.storage,
            self.strict if calls is None else calls,
            os_calls=self.os_calls if os_calls is None else os_calls,
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
                self.active.pop()

    def read_os(self, args):
        self.memory.write(args[3], 4, 0x12345678)
        return self.read_raw

    def seek_os(self, args):
        self.memory.write(args[2], 8, 0xFEDCBA9876543210)
        return self.seek_raw

    def invoke(self, target=READ, *, handle=7, pointer=None, fourth=4, home=None):
        if pointer is None:
            pointer = self.destination if target == READ else self.output
        return self.bound.call(
            target, (0x9999, handle, pointer, fourth, self.home if home is None else home), None
        )

    def calls_to(self, target):
        return [
            e[2] for e in self.events if e[0] in ("os", "strict", "ordinary") and e[1] == target
        ]

    def assert_expired(self):
        assert not self.active
        for address, _, _ in self.locals:
            with pytest.raises(ReplayMemoryError, match="unmapped"):
                self.memory.read(address, 1)

    def support(self, *, home=True, provider=None):
        def ordinary(target, args, data):
            assert data is None
            self.events.append(("ordinary", target, args))
            if target not in self.generic_handlers:
                raise UnresolvedReplayTaskRebuild(f"ordinary service{target:x} missing")
            return self.generic_handlers[target](args)

        terminal = ReplayTaskRebuildCalls(ordinary)
        strings = bind_replay_saved_string(self.storage, terminal)
        results = bind_replay_saved_result(
            self.storage, strings, atomics=ReplayUnitAIMapAtomics(None, None)
        )
        return bind_replay_file_support(
            self.storage,
            results,
            variadic_calls=ReplayTaskRebuildCalls(None),
            atomics=ReplayUnitAIMapAtomics(None, None),
            bind_local=self.bind_local,
            profile=ReplayFileSupportProfile(b"P" * 0x68, b"W" * 0x28, None),
            backend_home_calls=(self.bound if provider is None else provider) if home else None,
        )


def test_read_exact_seed_store_widths_count_narrowing_and_logical_al_return():
    r = Rig()
    raw = r.invoke(fourth=(9 << 32) | 4)
    frame, size, seed = r.locals[0]
    assert (size, seed) == (0x38, b"R" * 0x38)
    assert r.events[:4] == [
        ("map", frame, 0x38),
        ("read", r.home, 8),
        ("write", frame + 0x30, 4, 0),
        ("write", frame + 0x20, 8, 0),
    ]
    assert r.calls_to(READ_OS) == [(7, r.destination, 4, frame + 0x30, 0)]
    assert r.memory.read(r.output, 8) == 0x12345678
    assert raw == 0x12345601  # Logical pre-cookie tracking, only AL is semantic.
    assert ("read", frame + 0x30, 8) not in r.events
    r.assert_expired()


@pytest.mark.parametrize("target", [READ, SEEK])
def test_invalid_handle_preserves_seed_and_no_os_or_local_initialization(target):
    r = Rig()
    assert r.invoke(target, handle=U64) == U64 & ~255
    assert not [e for e in r.events if e[0] in ("write", "os", "strict")]
    assert (("read", r.home, 8) in r.events) == (target == READ)
    assert r.memory.read(r.output, 8) == int.from_bytes(b"A" * 8, "little")
    r.assert_expired()


def test_invalid_read_requires_home_but_invalid_seek_does_not_access_it():
    r = Rig()
    with pytest.raises(ReplayMemoryError, match="unmapped"):
        r.invoke(handle=U64, home=0)
    r.assert_expired()
    assert r.invoke(SEEK, handle=U64, home=0) & 255 == 0


@pytest.mark.parametrize("target", [READ, SEEK])
@pytest.mark.parametrize("handle", [0, 1, U64 - 1])
def test_all_other_handle_patterns_reach_actual_os_capability(target, handle):
    r = Rig()
    assert r.invoke(target, handle=handle) & 255 == 1
    assert r.calls_to(READ_OS if target == READ else SEEK_OS)[0][0] == handle


@pytest.mark.parametrize("target", [READ, SEEK])
@pytest.mark.parametrize("raw,success", [(0, False), (1 << 32, False), (0x100, True), (U64, True)])
def test_os_status_full_eax_and_failure_logical_upper(target, raw, success):
    r = Rig()
    r.read_raw = r.seek_raw = raw
    returned = r.invoke(target)
    if success:
        assert returned & 255 == 1
        assert not r.calls_to(ERROR_OS) and not r.calls_to(LOGGER)
    else:
        assert returned == r.logger_raw & ~255
        assert r.memory.read(r.output, 8) == int.from_bytes(b"A" * 8, "little")
        assert r.calls_to(ERROR_OS) == [()]
        assert r.calls_to(LOGGER) == [(0x1432F7F10 if target == READ else 0x1432F7F40, 0x12345678)]
    r.assert_expired()


@pytest.mark.parametrize("target", [READ, SEEK])
def test_null_output_skips_local_result_read_and_retains_os_logical_upper(target):
    r = Rig()
    r.memory.write(r.home, 8, 0)
    r.read_raw = r.seek_raw = 0xDEADBEEF12340100
    raw = r.invoke(target, pointer=0 if target == SEEK else r.destination)
    frame = r.locals[0][0]
    assert raw == 0xDEADBEEF12340101
    assert (
        "read",
        frame + (0x30 if target == READ else 0x20),
        4 if target == READ else 8,
    ) not in r.events
    r.assert_expired()


@pytest.mark.parametrize(
    "mode,mapped", [(0, 0), (1, 2), (2, 1), (3, 0), (U32, 0), ((1 << 32) + 1, 2), (U64, 0)]
)
def test_seek_mode_mapping_and_full_qword_publication(mode, mapped):
    r = Rig()
    r.memory.write(r.home, 8, 0x123456789)
    returned = r.invoke(SEEK, fourth=mode)
    frame, size, seed = r.locals[0]
    assert (size, seed) == (0x28, b"S" * 0x28)
    assert r.events[:3] == [
        ("map", frame, 0x28),
        ("write", frame + 0x20, 8, 0),
        ("read", r.home, 8),
    ]
    assert r.calls_to(SEEK_OS) == [(7, 0x123456789, frame + 0x20, mapped)]
    assert r.memory.read(r.output, 8) == 0xFEDCBA9876543210
    assert returned == 0xFEDCBA9876543201


def test_read_holds_output_before_local_store_and_samples_outgoing_home_after_current_iat():
    r = Rig()

    def write(address, width, value):
        if r.active and address == r.active[-1] + 0x30:
            r.memory.write(r.home, 8, r.other)

    def read(address, width):
        if address == READ_IAT:
            r.memory.write(r.active[-1] + 0x20, 8, 0xBEEF)

    r.after_write, r.after_read = write, read
    r.invoke()
    assert r.calls_to(READ_OS)[0][4] == 0xBEEF
    assert r.memory.read(r.output, 8) == 0x12345678
    assert r.memory.read(r.other, 8) == int.from_bytes(b"B" * 8, "little")


def test_seek_late_requested_home_is_held_across_current_iat_callback():
    r = Rig()

    def write(address, width, value):
        if r.active and address == r.active[-1] + 0x20:
            r.memory.write(r.home, 8, 222)

    def read(address, width):
        if address == SEEK_IAT:
            r.memory.write(r.home, 8, 333)

    r.after_write, r.after_read = write, read
    r.invoke(SEEK)
    assert r.calls_to(SEEK_OS)[0][1] == 222


@pytest.mark.parametrize("target", [READ, SEEK])
def test_output_store_callback_does_not_change_held_logical_return(target):
    r = Rig()

    def write(address, width, value):
        if address == r.output:
            r.memory.write(
                r.active[-1] + (0x30 if target == READ else 0x20),
                4 if target == READ else 8,
                0xBA00,
            )

    r.after_write = write
    returned = r.invoke(target)
    assert returned == (0x12345601 if target == READ else 0xFEDCBA9876543201)


def test_current_import_target_dispatch_uses_os_terminal_even_for_owned_address_collision():
    r = Rig()
    r.memory.write(READ_IAT, 8, READ)
    r.os_handlers[READ] = r.read_os
    assert r.invoke() & 255 == 1
    assert len(r.locals) == 1 and len(r.calls_to(READ)) == 1
    assert not r.calls_to(READ_OS)


@pytest.mark.parametrize("target", [READ, SEEK])
def test_failure_reads_new_current_error_target_after_actual_os_effect(target):
    r = Rig()

    def failed(args):
        r.memory.write(ERROR_IAT, 8, 0xFA04)
        return 0

    r.os_handlers[READ_OS if target == READ else SEEK_OS] = failed
    r.os_handlers[0xFA04] = lambda args: 0xFEEDCAFE55667788
    assert r.invoke(target) & 255 == 0
    assert r.calls_to(0xFA04) == [()] and not r.calls_to(ERROR_OS)
    assert r.calls_to(LOGGER)[0][1] == 0x55667788


@pytest.mark.parametrize("target", [READ, SEEK])
@pytest.mark.parametrize("raw", [None, -1, U64 + 1, True])
def test_invalid_os_raw_return_refuses_at_eax_consumer_without_output_publication(target, raw):
    r = Rig()
    r.read_raw = r.seek_raw = raw
    with pytest.raises(ValueError):
        r.invoke(target)
    assert not r.calls_to(ERROR_OS) and not r.calls_to(LOGGER)
    assert r.memory.read(r.output, 8) == int.from_bytes(b"A" * 8, "little")
    r.assert_expired()


@pytest.mark.parametrize("target", [READ, SEEK])
@pytest.mark.parametrize("channel", ["os", "logger", "error"])
def test_missing_reached_service_keeps_prefix_and_expires_local(target, channel):
    r = Rig()
    r.read_raw = r.seek_raw = 0
    if channel == "os":
        r.bind(os_calls=ReplayTaskRebuildCalls(None))
    elif channel == "logger":
        r.bind(calls=ReplayTaskRebuildCalls(None))
    else:
        del r.os_handlers[ERROR_OS]
    with pytest.raises(UnresolvedReplayTaskRebuild):
        r.invoke(target)
    frame = r.locals[0][0]
    assert ("write", frame + 0x20, 8, 0) in r.events
    assert r.memory.read(r.output, 8) == int.from_bytes(b"A" * 8, "little")
    r.assert_expired()


@pytest.mark.parametrize("target", [READ_SHIM, SEEK_SHIM])
def test_wrapper_home_composes_actual_backend_and_retains_nested_home_timing(target):
    r = Rig()
    support = r.support()

    def write(address, width, value):
        if len(r.active) == 2:
            parent, child = r.active
            if target == READ_SHIM and address == child + 0x30:
                r.memory.write(parent + 0x20, 8, r.other)
            elif target == SEEK_SHIM and address == child + 0x20:
                r.memory.write(parent + 0x20, 8, 987)

    r.after_write = write
    pointer = r.destination if target == READ_SHIM else r.output
    fourth = r.output if target == READ_SHIM else 123
    assert support.call(target, (7, pointer, (1 << 32) + 2, fourth), None) & 255 == 1
    parent, child = r.locals[0][0], r.locals[1][0]
    home_reads = [e for e in r.events if e == ("read", parent + 0x20, 8)]
    assert len(home_reads) == 1  # Callee only: wrapper has no fifth-home read.
    assert r.events.index(home_reads[0]) > r.events.index(("map", child, r.locals[1][1]))
    if target == READ_SHIM:
        assert r.memory.read(r.output, 8) == 0x12345678
        assert r.calls_to(READ_OS)[0][2] == 2
    else:
        assert r.calls_to(SEEK_OS)[0][1:] == (987, child + 0x20, 1)
    assert r.events[-2:] == [("unmap", child, r.locals[1][1]), ("unmap", parent, 0x28)]
    r.assert_expired()


@pytest.mark.parametrize("target", [READ_SHIM, SEEK_SHIM])
def test_unavailable_home_channel_refuses_after_source_target_selection_without_home_read(target):
    r = Rig()
    support = r.support(provider=ReplayTaskRebuildCalls(None))
    with pytest.raises(UnresolvedReplayTaskRebuild, match="HOME method"):
        support.call(target, (7, r.output, 4, 123), None)
    parent = r.locals[0][0]
    assert ("read", parent + 0x20, 8) not in r.events
    assert ("read", r.vptr + (0x38 if target == READ_SHIM else 0x40), 8) in r.events
    r.assert_expired()


@pytest.mark.parametrize("unsupported", [0xCA01, LOGGER])
def test_unknown_current_home_target_refuses_without_generic_scalar_fallback(unsupported):
    r = Rig()
    r.memory.write(r.vptr + 0x38, 8, unsupported)
    r.generic_handlers[unsupported] = lambda args: 1
    with pytest.raises(UnresolvedReplayTaskRebuild, match=f"unknown HOME target{unsupported:x}"):
        r.support().call(READ_SHIM, (7, r.destination, 4, r.output), None)
    assert r.calls_to(unsupported)
    assert not any(e[0] == "ordinary" and e[1] == unsupported for e in r.events)
    assert len(r.locals) == 1
    assert ("read", r.locals[0][0] + 0x20, 8) not in r.events


@pytest.mark.parametrize("returned", [None, 0xFEDCBA9876543210])
def test_default_scalar_route_retains_effective_sample_and_transparent_return(returned):
    r = Rig()
    r.memory.write(r.vptr + 0x38, 8, 0xCA01)
    r.generic_handlers[0xCA01] = lambda args: returned
    support = r.support(home=False)
    assert support.call(READ_SHIM, (7, r.destination, U64, r.output), None) == returned
    parent = r.locals[0][0]
    assert r.calls_to(0xCA01) == [(r.service, 7, r.destination, U64, r.output)]
    assert r.events.count(("read", parent + 0x20, 8)) == 1
    assert len(r.locals) == 1 and not r.calls_to(READ_OS)


def test_complete_read_seek_compose_owned_byte_stream_and_real_result_cleanup():
    r = Rig()
    stream = io.BytesIO(b"abcdefghijklmnop")

    def read(args):
        assert args[0] == 7 and args[4] == 0
        data = stream.read(args[2])
        r.memory.write_bytes(args[1], data)
        r.memory.write(args[3], 4, len(data))
        return 0x100

    def seek(args):
        assert args[0] == 7
        position = stream.seek(args[1], args[3])
        r.memory.write(args[2], 8, position)
        return 0x100

    r.os_handlers[READ_OS], r.os_handlers[SEEK_OS] = read, seek
    file, output = r.memory.allocate(0xA8), r.memory.allocate(48)
    r.memory.write_bytes(output, b"\xb7" * 48)
    for offset, width, value in (
        (0x28, 8, 7),
        (0x30, 8, 16),
        (0x40, 8, 0),
        (0x48, 4, 55),
        (0x4C, 4, 66),
        (0x54, 1, 1),
        (0x56, 1, 0),
        (0x80, 4, 0),
    ):
        r.memory.write(file + offset, width, value)
    calls = bind_replay_file_seek(
        r.storage,
        r.support(),
        variadic_calls=ReplayTaskRebuildCalls(None),
        atomics=ReplayUnitAIMapAtomics(None, None),
        bind_local=r.bind_local,
        profile=ReplayFileSeekProfile(bytes(0x70), None),
    )
    calls = bind_replay_file_read(
        r.storage,
        calls,
        variadic_calls=ReplayTaskRebuildCalls(None),
        decoder_calls=ReplayTaskRebuildCalls(None),
        atomics=ReplayUnitAIMapAtomics(None, None),
        bind_local=r.bind_local,
        profile=ReplayFileReadProfile(bytes(0xB8), None, 0),
    )
    assert calls.call(READ_FILE, (file, output, r.destination, 4), None) == output
    assert r.memory.read_bytes(r.destination, 4) == b"abcd"
    assert r.memory.read(file + 0x40, 8) == stream.tell() == 4
    assert calls.call(SEEK_FILE, (file, output, 10), None) == output
    assert r.memory.read(file + 0x40, 8) == stream.tell() == 10
    assert calls.call(READ_FILE, (file, output, r.destination, 4), None) == output
    assert r.memory.read_bytes(r.destination, 4) == b"klmn"
    assert r.memory.read(file + 0x40, 8) == stream.tell() == 14
    assert r.memory.read_bytes(output, 48) == bytes(41) + b"\xb7" * 7
    assert not r.calls_to(LOGGER)
    r.assert_expired()


@pytest.mark.parametrize(
    "field,value", [("read", b""), ("read", bytearray(0x38)), ("seek", bytes(0x27)), ("seek", None)]
)
def test_profile_validation_is_before_execution(field, value):
    with pytest.raises(ValueError):
        replace(ReplayFileBackendProfile(bytes(0x38), bytes(0x28)), **{field: value})


@pytest.mark.parametrize(
    "args,data",
    [
        ((1, 2, 3, 4), None),
        ((1, 2, 3, 4, -1), None),
        ((1, 2, 3, True, 5), None),
        ((1, 2, 3, 4, 5), memoryview(b"x")),
    ],
)
def test_owned_abi_refuses_before_any_local_mapping(args, data):
    r = Rig()
    with pytest.raises(ValueError):
        r.bound.call(READ, args, data)
    assert not r.events and not r.locals


def test_unknown_dispatch_keeps_original_objects_and_opaque_return():
    r = Rig()
    seen, args, data = [], (1, 2), memoryview(b"x")

    def delegate(target, actual_args, actual_data):
        seen.append((target, actual_args, actual_data))
        return None

    r.bind(calls=ReplayTaskRebuildCalls(delegate))
    assert r.bound.call(0x123, args, data) is None
    assert seen[0][1] is args and seen[0][2] is data
    assert not r.locals


@pytest.mark.parametrize("target", [READ_SHIM, SEEK_SHIM])
def test_wrapper_holds_global_before_store_but_loads_current_vptr_and_slot(target):
    r = Rig()
    new_table, seen = r.memory.allocate(0x48), []
    offset = 0x38 if target == READ_SHIM else 0x40
    method = READ if target == READ_SHIM else SEEK
    r.memory.write(new_table + offset, 8, method)

    def write(address, width, value):
        if len(r.active) == 1 and address == r.active[0] + 0x20:
            r.memory.write(GLOBAL, 8, 0xBAD)  # Must not reread this unbacked new service.
            r.memory.write(r.service, 8, new_table)

    def provider(actual_target, args, data):
        seen.append((actual_target, args))
        return r.bound.call(actual_target, args, data)

    r.after_write = write
    support = r.support(provider=ReplayTaskRebuildCalls(provider))
    fourth = r.output if target == READ_SHIM else 123
    assert (
        support.call(
            target, (7, r.destination if target == READ_SHIM else r.output, 4, fourth), None
        )
        & 255
        == 1
    )
    assert seen[0][0] == method and seen[0][1][0] == r.service
    assert ("read", new_table + offset, 8) in r.events
    assert ("read", r.vptr + offset, 8) not in r.events
    assert r.events.count(("read", GLOBAL, 8)) == 1


@pytest.mark.parametrize("target", [READ_SHIM, SEEK_SHIM])
@pytest.mark.parametrize("returned", [None, U64])
def test_explicit_home_channel_does_not_consume_raw_or_opaque_return(target, returned):
    r = Rig()
    seen = []

    def provider(method, args, data):
        seen.append((method, args, data))
        assert r.active == [r.locals[0][0]]
        return returned

    support = r.support(provider=ReplayTaskRebuildCalls(provider))
    assert support.call(target, (7, r.destination, U64, 123), None) == returned
    parent = r.locals[0][0]
    assert seen == [
        (
            READ if target == READ_SHIM else SEEK,
            (r.service, 7, r.destination, U64 if target == READ_SHIM else U32, parent + 0x20),
            None,
        )
    ]
    assert ("read", parent + 0x20, 8) not in r.events
    r.assert_expired()


@pytest.mark.parametrize("target", [READ, SEEK])
@pytest.mark.parametrize("which", ["error", "logger"])
def test_required_raw_error_and_logger_profile_refuses_none_before_return(target, which):
    r = Rig()
    r.read_raw = r.seek_raw = 0
    if which == "error":
        r.error_raw = None
    else:
        r.logger_raw = None
    with pytest.raises(ValueError):
        r.invoke(target)
    assert bool(r.calls_to(LOGGER)) == (which == "logger")
    assert r.memory.read(r.output, 8) == int.from_bytes(b"A" * 8, "little")
    r.assert_expired()
