"""Source-derived lifecycle controls, with explicit owned storage and child services."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace

import pytest

from vantage.replay_command_lifecycle import (
    ReplayCommandLifecycleProfile,
    bind_replay_command_lifecycle,
)
from vantage.replay_memory import ReplayMemory, ReplayMemoryError
from vantage.replay_saved_result import bind_replay_saved_result
from vantage.replay_saved_string import bind_replay_saved_string
from vantage.replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
)
from vantage.replay_unit_ai_map import ReplayUnitAIMapAtomics

STOP, ABORT, WRITER = 0x140DF2670, 0x140DF2240, 0x140DEE940
DISPATCH, VECTOR, EVENT, STRONG = 0x140A8FB50, 0x140A8E1A0, 0x1409053D0, 0x140990140
CTOR, GUID, COPY16, COPYFIELDS = 0x140A3E250, 0x140900030, 0x1408FFF50, 0x140900050
CURRENT, PRESENT, SETTINGS, ADD, THUNK = (
    0x140A69450,
    0x140A694D0,
    0x140E15890,
    0x140E57AB0,
    0x141758280,
)
SERVICE, BUILD, POST = 0x140A6CB50, 0x140A70250, 0x140A6D200
WRITE, SEEK, CLEAR, HEADER, FLUSH = (
    0x140918D20,
    0x1409179E0,
    0x1402BD7F0,
    0x140DEED70,
    0x140915B30,
)
STRING, TREE, FREE, LOCK, UNLOCK, THROW, BAD = (
    0x1402A88A0,
    0x140905300,
    0x142D6BAB4,
    0x142D6AA5B,
    0x142D6AA61,
    0x142D6AA67,
    0x142D6669E,
)
GUARD, SERVICE_ADDRESS, U32 = 0x14428F4D8, 0x14428EEA0, 0xFFFFFFFF


class Rig:
    def __init__(self):
        self.memory = ReplayMemory()
        self.descriptor = self.memory.allocate(0x140)
        self.stream = self.memory.allocate(0x48)
        for address, width, value in (
            (self.descriptor, 1, 0),
            (self.descriptor + 1, 1, 0),
            (self.descriptor + 0x48, 8, self.stream),
            (self.descriptor + 0x80, 1, 7),
            (self.descriptor + 0x84, 4, 0xAABBCCDD),
            (self.descriptor + 0x8C, 1, 0),
            (self.descriptor + 0x120, 8, 0),
            (self.descriptor + 0x128, 8, 0),
            (self.stream + 8, 4, 2),
        ):
            self.memory.write(address, width, value)
        self.memory.map_bytes(0x143199DD0, FREE.to_bytes(8, "little"))
        self.memory.map_bytes(0x14319A758, (0xCA11).to_bytes(8, "little"))
        self.memory.map_bytes(0x14319A060, (0xCA12).to_bytes(8, "little"))
        self.memory.map_bytes(0x143214E58, BUILD.to_bytes(8, "little"))
        self.memory.map_bytes(0x14428ECD8, bytes(8))
        self.gs, self.tls, self.thread = (self.memory.allocate(size) for size in (0x60, 8, 0x3B8))
        self.memory.write(self.gs + 0x58, 8, self.tls)
        self.memory.write(self.tls, 8, self.thread)
        self.memory.write(self.thread + 0x3B4, 4, 0)
        self.memory.map_bytes(0x144C9C828, bytes(4))
        self.memory.map_bytes(GUARD, bytes(4))
        self.profile = ReplayCommandLifecycleProfile(
            b"\xa1" * 0x160,
            b"\xb2" * 0x50,
            b"\xc3" * 0x68,
            b"\xd4" * 0x78,
            b"\xe5" * 0x28,
            b"\xf6" * 0x28,
            self.gs,
        )
        self.events, self.locals, self.active = [], [], []
        self.after_read, self.after_write, self.after_atomic = None, None, None
        self.clear_hook = None
        self.writes, self.statuses, self.controls, self.guids = [], [], [], []
        self.header_result = 1

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

        def exchange(address, value):
            self.events.append(("exchange", address, value))
            self.memory.write(address, 1, value)
            return None  # Caller never consumes AL.

        self.exchange = exchange
        self.storage = ReplayTaskRebuildStorage(1, read, write)
        self.atomics = ReplayUnitAIMapAtomics(None, atomic)
        self.handlers = {
            WRITE: self.file_write,
            SEEK: self.seek,
            HEADER: lambda args: self.header_result,
            TREE: lambda args: None,
            LOCK: lambda args: 0,
            UNLOCK: lambda args: None,
            0x140A670B0: lambda args: None,
            0x140A60D20: lambda args: None,
            0x1409046D0: lambda args: None,
        }
        self.import_handlers, self.home_handler = {0xCA11: self.guid}, None
        runtime = self.memory.runtime_calls()

        def imported(target, args, data):
            self.events.append(("import", target, args))
            if target in self.import_handlers:
                return self.import_handlers[target](args)
            return runtime.call(target, args, data)

        def call(target, args, data):
            self.events.append(("call", target, args))
            if target in self.handlers:
                return self.handlers[target](args)
            if target == CLEAR and self.clear_hook:
                self.clear_hook(args[0])
            return self.results.call(target, args, data)

        def home(target, args, data):
            self.events.append(("home", target, args))
            if self.home_handler:
                return self.home_handler(target, args, data)
            return None

        self.calls, self.imports = ReplayTaskRebuildCalls(call), ReplayTaskRebuildCalls(imported)
        self.home_calls = ReplayTaskRebuildCalls(home)
        strings = bind_replay_saved_string(self.storage, runtime, imports=self.imports)
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

    def bind(self):
        self.bound = bind_replay_command_lifecycle(
            self.storage,
            self.calls,
            imports=self.imports,
            watson_home_calls=self.home_calls,
            atomics=self.atomics,
            exchange_byte=self.exchange,
            bind_local=self.bind_local,
            profile=self.profile,
        )

    def result(self, pointer, *, status=0, control=0):
        raw = bytearray(b"\xe7" * 48)
        for offset, value in ((0, 0), (8, 0), (16, 0), (24, status), (32, control)):
            raw[offset : offset + 8] = value.to_bytes(8, "little")
        self.memory.write_bytes(pointer, bytes(raw))

    def file_write(self, args):
        index = len(self.writes)
        self.writes.append((args, self.memory.read_bytes(args[2], args[3])))
        self.result(
            args[1],
            status=self.statuses[index] if index < len(self.statuses) else 0,
            control=self.controls[index] if index < len(self.controls) else 0,
        )
        return None

    def seek(self, args):
        self.result(args[1], status=0xBAD)
        return args[1]

    def guid(self, args):
        value = bytes([len(self.guids) + 1]) * 16
        self.memory.write_bytes(args[0], value)
        self.guids.append((args[0], value))
        return 0x80004005  # HRESULT is ignored by the source wrapper.

    def invoke(self, target, args=None):
        return self.bound.call(target, (self.descriptor,) if args is None else args, None)

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

    def event(self, event):
        self.memory.write_bytes(event, bytes(0xD0))
        head, tree = self.memory.allocate(0x50), self.memory.allocate(0x58)
        self.memory.write(head, 8, 0)
        self.memory.write(head + 8, 8, head)
        self.memory.write(event + 0x48, 8, head)
        self.memory.write(event + 8, 8, tree)
        return head, tree

    def stop_inputs(self):
        game, settings, pointer = (self.memory.allocate(size) for size in (0xA28, 0xD18, 0xB8))
        self.memory.write(0x14428ECD8, 8, game)
        self.memory.map_bytes(0x1442DA8A0, settings.to_bytes(8, "little"))
        self.memory.write(settings + 0xD10, 8, pointer)
        self.memory.write_bytes(pointer + 0xA8, bytes(range(16)))
        self.memory.write(game + 0xA24, 4, 999)
        self.fixed_events = []

        def build(args):
            assert args[2] == 0x143214E60
            self.fixed_events.append((args[1], *self.event(args[1])))
            return 0xBAAD  # Builder RAX is ignored by140a70250.

        self.handlers[0x140A31630] = build
        return game, settings, pointer

    def expired(self):
        assert not self.active
        for address, _, _ in self.locals:
            with pytest.raises(ReplayMemoryError, match="unmapped"):
                self.memory.read(address, 1)


@pytest.mark.parametrize(("target", "offset"), [(STOP, 1), (ABORT, 0)])
def test_inactive_lifecycle_skips_locals_and_all_effects(target, offset):
    rig = Rig()
    assert rig.invoke(target) is None
    assert rig.events == [("read", rig.descriptor + offset, 1)]


@pytest.mark.parametrize("strong", [0, 1, 2])
def test_strong_only_release_never_decrements_weak(strong):
    rig = Rig()
    control = rig.control(strong=strong, weak=1)
    rig.invoke(STRONG, (control,))
    assert rig.memory.read(control + 8, 4) == (strong - 1) & U32
    assert rig.memory.read(control + 12, 4) == 1
    assert rig.calls_to(0xD1) == ([(control,)] if strong == 1 else [])
    assert not rig.calls_to(0xD2)


def test_guid_ctor_preserves_padding_uses_current_iat_and_ignores_hresult():
    rig = Rig()
    target = rig.memory.allocate(48)
    rig.memory.write_bytes(target, b"\x88" * 48)
    assert rig.invoke(CTOR, (target,)) == target
    assert rig.memory.read_bytes(target, 48) == (
        b"\x01" * 16 + b"\x02" * 16 + b"\xff" * 12 + b"\x88" * 4
    )
    assert [e[2] for e in rig.events if e[0] == "import"] == [(target,), (target + 16,)]
    assert rig.invoke(PRESENT, ()) & 255 == 0
    rig.memory.write(0x14428ECD8, 8, 0x1234)
    assert rig.invoke(PRESENT, ()) & 255 == 1
    assert rig.invoke(CURRENT, ()) == 0x1234


def test_copy16_holds_snapshot_while_field_copy_reads_each_component_after_prior_store():
    rig = Rig()
    address = rig.memory.allocate(32)
    original = bytes(range(32))
    rig.memory.write_bytes(address, original)
    assert rig.invoke(COPY16, (address + 1, address)) == address + 1
    assert rig.memory.read_bytes(address + 1, 16) == original[:16]
    rig.memory.write_bytes(address, original)
    assert rig.invoke(COPYFIELDS, (address + 1, address)) == address + 1
    expected = bytearray(original)
    for offset, width in ((0, 4), (4, 2), (6, 2), (8, 8)):
        expected[1 + offset : 1 + offset + width] = expected[offset : offset + width]
    assert rig.memory.read_bytes(address, 32) == bytes(expected)
    assert rig.invoke(SETTINGS, ((1 << 64) - 0xCB8,)) == 0x58
    assert rig.invoke(ADD, ((1 << 64) - 0x58,)) == 0


def test_tls_signed_fast_path_and_real_initializer_order():
    rig = Rig()
    rig.memory.write(GUARD, 4, U32)
    assert rig.invoke(SERVICE, ()) == SERVICE_ADDRESS
    assert not rig.calls_to(0x142D6BF80)
    rig.memory.write(GUARD, 4, 1)

    def header(args):
        assert args == (GUARD,)
        rig.memory.write(GUARD, 4, U32)

    rig.handlers.update(
        {
            0x142D6BF80: header,
            0x140A6BBD0: lambda args: None,
            0x142D6BD04: lambda args: None,
            0x142D6BF14: lambda args: None,
        }
    )
    assert rig.invoke(SERVICE, ()) == SERVICE_ADDRESS
    selected = [(e[1], e[2]) for e in rig.events if e[0] == "call"]
    assert selected == [
        (0x142D6BF80, (GUARD,)),
        (0x140A6BBD0, (SERVICE_ADDRESS,)),
        (0x142D6BD04, (0x14305F220,)),
        (0x142D6BF14, (GUARD,)),
    ]


def test_missing_gs_refuses_instead_of_inventing_tls_or_service_initialization():
    rig = Rig()
    rig.profile = replace(rig.profile, gs_base=None)
    rig.bind()
    with pytest.raises(UnresolvedReplayTaskRebuild, match=r"GS|TLS|gs"):
        rig.invoke(SERVICE, ())
    assert not rig.calls_to(0x142D6BF80)


@pytest.mark.parametrize(("flag", "pointer", "post"), [(0, 1, False), (1, 0, False), (1, 1, True)])
def test_event_post_followup_only_occurs_when_both_source_gates_pass(flag, pointer, post):
    rig = Rig()
    event = rig.memory.allocate(0xD0)
    rig.memory.write(event + 0xC0, 1, flag)
    rig.memory.write(event + 0x90, 8, pointer)
    rig.invoke(POST, (SERVICE_ADDRESS, event))
    assert rig.calls_to(0x140A60D20) == ([(SERVICE_ADDRESS + 0x180, event)] if post else [])
    assert rig.calls_to(0x1409046D0) == ([(SERVICE_ADDRESS + 0x10,)] if post else [])
    if not flag:
        assert ("read", event + 0x90, 8) not in rig.events


def test_stop_release_exchange_flags_guid_event_destruction_then_current_global_write():
    rig = Rig()
    game, _, _ = rig.stop_inputs()
    rig.memory.write(rig.descriptor + 1, 1, 1)
    assert rig.invoke(STOP) is None
    assert rig.memory.read(rig.stream + 8, 4) == 1
    assert rig.memory.read(rig.descriptor + 0x48, 8) == 0
    assert rig.memory.read(rig.descriptor + 1, 1) == 0
    assert rig.memory.read(rig.descriptor + 0x80, 1) == 0
    assert rig.memory.read(game + 0xA24, 4) == 0
    atomic = ("atomic", rig.stream + 8, U32)
    clear = ("write", rig.descriptor + 0x48, 8, 0)
    exchange = ("exchange", rig.descriptor + 1, 0)
    assert rig.events.index(atomic) < rig.events.index(clear) < rig.events.index(exchange)
    assert rig.events.index(exchange) < rig.events.index(("write", rig.descriptor + 0x80, 1, 0))
    assert len(rig.guids) == 3
    event, head, tree = rig.fixed_events[0]
    assert rig.calls_to(FREE)[-2:] == [(head, 0x50), (tree, 0x58)]
    assert ("write", game + 0xA24, 4, 0) == [e for e in rig.events if e[0] == "write"][-1]
    assert event == rig.locals[0][0] + 0x40
    rig.expired()


def test_missing_byte_exchange_refuses_after_stream_release_and_clear():
    rig = Rig()
    rig.memory.write(rig.descriptor + 1, 1, 1)
    rig.exchange = None
    rig.bind()
    with pytest.raises(UnresolvedReplayTaskRebuild, match=r"byte|BYTE|exchange"):
        rig.invoke(STOP)
    assert rig.memory.read(rig.descriptor + 0x48, 8) == 0
    assert rig.memory.read(rig.stream + 8, 4) == 1
    assert rig.memory.read(rig.descriptor + 1, 1) == 1
    assert rig.memory.read(rig.descriptor + 0x80, 1) == 7
    assert not rig.guids
    rig.expired()


def test_initial_null_stream_does_not_clear_pointer_installed_by_read_callback():
    rig = Rig()
    rig.stop_inputs()
    rig.memory.write(rig.descriptor + 1, 1, 1)
    rig.memory.write(rig.descriptor + 0x48, 8, 0)

    def read(address, width):
        if address == rig.descriptor + 0x48:
            rig.memory.write(address, 8, rig.stream)

    rig.after_read = read
    rig.invoke(STOP)
    assert rig.memory.read(rig.descriptor + 0x48, 8) == rig.stream
    assert rig.memory.read(rig.stream + 8, 4) == 2


def test_missing_guid_import_refuses_after_constructor_zero_with_remaining_bytes_intact():
    rig = Rig()
    target = rig.memory.allocate(48)
    rig.memory.write_bytes(target, b"\x88" * 48)
    rig.memory.write(0x14319A758, 8, 0xBAD)
    with pytest.raises(UnresolvedReplayTaskRebuild):
        rig.invoke(CTOR, (target,))
    assert rig.memory.read_bytes(target, 48) == bytes(16) + b"\x88" * 32
    assert rig.calls_to(0xBAD, channel="import") == [(target,)]


def test_stop_posts_actual_virtual_return_but_destroys_fixed_event_and_reloads_global():
    rig = Rig()
    game, _, _ = rig.stop_inputs()
    alternate, new_game = rig.memory.allocate(0xD0), rig.memory.allocate(0xA28)
    rig.memory.write(alternate + 0xC0, 1, 1)
    rig.memory.write(alternate + 0x90, 8, 7)
    rig.memory.write(0x143214E58, 8, 0xBEEF)
    rig.memory.write(rig.descriptor + 1, 1, 1)

    def virtual(args):
        frame = rig.locals[0][0]
        assert args == (frame + 0x110, frame + 0x40)
        rig.fixed_events.append((args[1], *rig.event(args[1])))
        return alternate

    def post(args):
        assert args == (SERVICE_ADDRESS + 0x180, alternate)
        rig.memory.write(0x14428ECD8, 8, new_game)

    rig.handlers.update({0xBEEF: virtual, 0x140A60D20: post})
    rig.invoke(STOP)
    assert rig.memory.read(game + 0xA24, 4) == 999
    assert rig.memory.read(new_game + 0xA24, 4) == 0
    fixed = rig.fixed_events[0]
    assert rig.calls_to(FREE)[-2:] == [(fixed[1], 0x50), (fixed[2], 0x58)]


def test_inactive_writer_still_stores_low_argument_words_in_live_local_seed():
    rig = Rig()
    assert rig.invoke(WRITER, (rig.descriptor, 0xBAD, (1 << 32) + 3, (1 << 32) + 7)) == 7
    frame = rig.locals[0][0]
    assert [e for e in rig.events if e[0] == "write"] == [
        ("write", frame + 0x50, 4, 3),
        ("write", frame + 0x60, 4, 7),
    ]
    assert not rig.writes
    rig.expired()


@pytest.mark.parametrize("failure", [None, 0, 1, 2, 3])
def test_writer_order_and_each_status_failure_preserves_written_prefix(failure):
    rig = Rig()
    rig.memory.write(rig.descriptor, 1, 1)
    payload = rig.memory.allocate(3)
    rig.memory.write_bytes(payload, b"abc")
    if failure is not None:
        rig.statuses = [0] * failure + [1 << 32]
    assert rig.invoke(WRITER, (rig.descriptor, payload, 3, 99)) == (1 if failure is None else U32)
    expected = [b"\x01\0\0\0", b"\x03\0\0\0", b"abc", b"c\0\0\0"]
    assert [raw for _, raw in rig.writes] == expected[: 4 if failure is None else failure + 1]
    assert len(rig.calls_to(CLEAR)) == len(rig.writes)
    rig.expired()


def test_writer_flush_ignores_status_and_does_not_mark_processed():
    rig = Rig()
    rig.memory.write(rig.descriptor, 1, 1)
    rig.memory.write(rig.descriptor + 0x8C, 1, 1)
    payload = rig.memory.allocate(1)
    rig.memory.write(payload, 1, 7)
    flushed = []

    def flush(args):
        rig.result(args[1], status=0xBAD)
        flushed.append(args[1])
        return None

    def read(address, width):
        assert not flushed or address != flushed[0] + 24

    def write(address, width, value):
        assert not flushed or address != flushed[0] + 40

    rig.handlers[FLUSH], rig.after_read, rig.after_write = flush, read, write
    assert rig.invoke(WRITER, (rig.descriptor, payload, 1, 8)) == 1
    assert len(flushed) == 1 and len(rig.calls_to(CLEAR)) == 5


def test_abort_ignores_io_status_zeroes_shared_fields_before_release_and_flag_last():
    rig = Rig()
    rig.memory.write(rig.descriptor, 1, 1)
    control = rig.control()
    rig.memory.write(rig.descriptor + 0x120, 8, 0xAAAA)
    rig.memory.write(rig.descriptor + 0x128, 8, control)
    rig.statuses = [999]

    def destroy(args):
        assert rig.memory.read(rig.descriptor + 0x120, 8) == 0
        assert rig.memory.read(rig.descriptor + 0x128, 8) == 0
        assert rig.memory.read(rig.descriptor, 1) == 1

    rig.handlers[0xD1] = destroy
    rig.invoke(ABORT)
    assert rig.calls_to(SEEK)[0][2] == 0
    assert rig.writes[0][1] == b"\xdd\xcc\xbb\xaa"
    assert rig.calls_to(0xD2) == [(control,)]
    assert rig.memory.read(rig.descriptor + 0x48, 8) == 0
    assert rig.memory.read(rig.descriptor, 1) == 0
    assert ("write", rig.descriptor, 1, 0) == [e for e in rig.events if e[0] == "write"][-1]


def test_null_vector_skips_all_other_header_reads_and_resets():
    rig = Rig()
    vector = rig.memory.allocate(24)
    rig.memory.write(vector, 8, 0)
    rig.invoke(VECTOR, (vector,))
    assert [e for e in rig.events if e[0] in ("read", "write", "call", "home")] == [
        ("read", vector, 8)
    ]
    rig.expired()


def test_vector_real_free_before_three_header_resets_and_watson_uses_live_home():
    rig = Rig()
    vector, allocation = rig.memory.allocate(24), rig.memory.allocate(24)
    for offset, value in ((0, allocation), (8, allocation + 8), (16, allocation + 24)):
        rig.memory.write(vector + offset, 8, value)
    rig.invoke(VECTOR, (vector,))
    assert rig.calls_to(FREE) == [(allocation, 24)]
    assert rig.memory.read_bytes(vector, 24) == bytes(24)
    large = rig.memory.allocate(0x2000)
    begin = large + 0x48
    rig.memory.write(begin - 8, 8, large)
    rig.memory.write(vector, 8, begin)
    rig.memory.write(vector + 16, 8, begin + 0x1000)

    def watson(target, args, data):
        frame = rig.locals[-1][0]
        assert (target, args, data) == (0xCA12, (0, 0, 0, 0, frame + 0x20), None)
        assert rig.memory.read(frame + 0x20, 8) == 0
        return None

    rig.home_handler = watson
    with pytest.raises(UnresolvedReplayTaskRebuild, match=r"INT3|Watson|watson"):
        rig.invoke(VECTOR, (vector,))
    assert rig.memory.read(vector, 8) == begin
    rig.expired()


def test_event_destructor_holds_next_before_strings_then_reloads_head_and_tree():
    rig = Rig()
    event = rig.memory.allocate(0xD0)
    head, tree = rig.event(event)
    nodes = [rig.memory.allocate(0x50) for _ in range(2)]
    for index, node in enumerate(nodes):
        rig.memory.write_bytes(node, bytes(0x50))
        rig.memory.write(node, 8, nodes[1] if index == 0 else 0xBAD)
    rig.memory.write(head, 8, nodes[0])
    rig.memory.write(head + 8, 8, nodes[1])

    def string(args):
        if args == (nodes[0] + 0x30,):
            rig.memory.write(nodes[0], 8, 0)
        return rig.results.call(STRING, args, None)

    rig.handlers[STRING] = string
    rig.invoke(EVENT, (event,))
    assert rig.calls_to(STRING) == [
        (event + 0xA0,),
        (event + 0x80,),
        (nodes[0] + 0x30,),
        (nodes[0] + 0x10,),
        (nodes[1] + 0x30,),
        (nodes[1] + 0x10,),
    ]
    assert rig.calls_to(FREE) == [(nodes[0], 0x50), (nodes[1], 0x50), (head, 0x50), (tree, 0x58)]
    assert rig.calls_to(TREE) == [(event + 8, tree)]


def dispatcher(rig, *, node_count=0):
    obj, mutex = rig.memory.allocate(24), rig.memory.allocate(0x58)
    rig.memory.write_bytes(obj, bytes(24))
    rig.memory.write(mutex + 0x4C, 4, 0)
    rig.memory.write(obj, 8, mutex)
    nodes = [rig.memory.allocate(0x50) for _ in range(node_count)]
    for index, node in enumerate(nodes):
        rig.memory.write(node + 0x48, 8, nodes[index + 1] if index + 1 < len(nodes) else 0)
    rig.memory.write(mutex + 0x50, 8, nodes[0] if nodes else 0)
    table = bytearray(0x28)
    table[0x10:0x18] = (0xF10).to_bytes(8, "little")
    table[0x20:0x28] = (0xF20).to_bytes(8, "little")
    rig.memory.map_bytes(0x1432189D0, bytes(table))
    rig.handlers[0xF10], rig.handlers[0xF20] = lambda args: None, lambda args: None
    return obj, mutex, nodes


@pytest.mark.parametrize(("lock_result", "count", "error"), [(3, 0, 5), (0, 0x7FFFFFFF, 6)])
def test_dispatcher_lock_errors_preserve_source_store_and_never_auto_unlock(
    lock_result,
    count,
    error,
):
    rig = Rig()
    obj, mutex, _ = dispatcher(rig)
    rig.memory.write(mutex + 0x4C, 4, count)
    rig.handlers[LOCK], rig.handlers[THROW] = lambda args: lock_result, lambda args: None
    with pytest.raises(UnresolvedReplayTaskRebuild, match=r"INT3|throw|returned"):
        rig.invoke(DISPATCH, (obj,))
    assert rig.calls_to(THROW) == [(error,)]
    assert not rig.calls_to(UNLOCK)
    assert rig.memory.read(mutex + 0x4C, 4) == (0x7FFFFFFE if error == 6 else count)


def test_dispatcher_reads_next_after_callback_and_bad_function_falls_through_twice():
    rig = Rig()
    obj, _, nodes = dispatcher(rig, node_count=2)

    def callback(args):
        frame = rig.locals[0][0]
        assert args == (frame + 0x30, frame + 0x70)
        assert rig.memory.read(args[1], 8) == nodes[0]
        rig.memory.write(frame + 0x68, 8, 0)

    rig.handlers[0xF10], rig.handlers[BAD] = callback, lambda args: None
    with pytest.raises(UnresolvedReplayTaskRebuild, match=r"INT3|function|returned"):
        rig.invoke(DISPATCH, (obj,))
    assert len(rig.calls_to(BAD)) == 2
    assert not rig.calls_to(UNLOCK)
    rig.expired()


def test_dispatcher_decrements_end_before_callback_and_unlocks_held_mutex():
    rig = Rig()
    obj, mutex, _ = dispatcher(rig)
    vector, node, functor, table = (rig.memory.allocate(size) for size in (8, 0x40, 8, 0x18))
    rig.memory.write(vector, 8, node)
    rig.memory.write(obj + 8, 8, vector)
    rig.memory.write(obj + 16, 8, vector + 8)
    rig.memory.write(node + 0x38, 8, functor)
    rig.memory.write(functor, 8, table)
    rig.memory.write(table + 0x10, 8, 0xD10)

    def deferred(args):
        assert args == (functor,)
        assert rig.memory.read(obj + 16, 8) == vector

    rig.handlers[0xD10] = deferred
    rig.invoke(DISPATCH, (obj,))
    assert rig.calls_to(UNLOCK) == [(mutex,)]
    assert rig.calls_to(0xD10) == [(functor,)]
    assert rig.memory.read(obj + 16, 8) == vector
    rig.expired()


def test_dispatcher_current_head_after_lock_uses_held_mutex_for_unlock_and_current_next():
    rig = Rig()
    obj, mutex, nodes = dispatcher(rig, node_count=2)
    other = rig.memory.allocate(0x58)
    rig.memory.write(other + 0x50, 8, nodes[0])

    def lock(args):
        assert args == (mutex,)
        rig.memory.write(obj, 8, other)
        return 0

    def callback(args):
        rig.memory.write(nodes[0] + 0x48, 8, 0)

    rig.handlers[LOCK], rig.handlers[0xF10] = lock, callback
    rig.invoke(DISPATCH, (obj,))
    assert len(rig.calls_to(0xF10)) == 1
    assert rig.calls_to(UNLOCK) == [(mutex,)]
    assert ("read", other + 0x4C, 4) not in rig.events


def test_unknown_lifecycle_dispatch_preserves_arguments_data_and_result_identity():
    rig = Rig()
    seen, args, data = [], (-1,), memoryview(bytearray(b"abc"))
    calls = ReplayTaskRebuildCalls(lambda target, actual, view: seen.append((actual, view)) or -77)
    bound = bind_replay_command_lifecycle(
        rig.storage,
        calls,
        imports=rig.imports,
        watson_home_calls=rig.home_calls,
        atomics=rig.atomics,
        exchange_byte=rig.exchange,
        bind_local=rig.bind_local,
        profile=rig.profile,
    )
    assert bound.call(0xBAD, args, data) == -77
    assert seen[0][0] is args and seen[0][1] is data
    with pytest.raises(ValueError):
        bound.call(STOP, (), None)
    with pytest.raises(ValueError):
        bound.call(GUID, (1,), data)


@pytest.mark.parametrize(
    "field",
    [
        "stop",
        "abort",
        "writer",
        "dispatcher",
        "vector",
        "event_cleanup",
    ],
)
def test_lifecycle_profile_requires_complete_explicit_seed(field):
    rig = Rig()
    with pytest.raises(ValueError):
        replace(rig.profile, **{field: b""})
