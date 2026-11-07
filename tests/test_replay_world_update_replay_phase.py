"""Source-led caller controls; authored children do not claim native closure."""

from __future__ import annotations

from dataclasses import replace

import pytest

from vantage.replay_clock_storage import bind_replay_clock_storage
from vantage.replay_memory import ReplayMemory, ReplayMemoryError
from vantage.replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
)
from vantage.replay_world_update_prelude import ReplayWorldUpdatePrelude
from vantage.replay_world_update_replay_phase import run_replay_world_update_replay_phase

DESC, TIME, SET = 0x140E15770, 0x140E68F70, 0x140E68FA0
OP2, OP3, SKIP = 0x140DEF190, 0x140DEF370, 0x140E053D0
SETTINGS, PRED, ABORT = 0x141603AC0, 0x1413D3910, 0x140DF2240
OBSERVER, POSITION, RESET, READER = 0x141603D70, 0x14174A970, 0x140F55400, 0x140DEC960
LOOKUP, FORMAT, SHOW = 0x140803E30, 0x140A1BA10, 0x141581360
DESTROY, STOP = 0x140A1B220, 0x140DF2670
SCREEN, DEFAULT, GLOBAL, FLAG = 0x144415600, 0x1431B7520, 0x1442C3F98, 0x1442C40F4
U32 = 0xFFFFFFFF
CASES = {
    "op2": (0xC0, 0xF8, 0x1432EA8A8, 0x141600C10),
    "op3": (0x100, 0x138, 0x1432EA8E0, 0x141600C20),
    "status": (0x140, 0x178, 0x1432EA918, 0x141600C30),
    "reader": (0x180, 0x1B8, 0x1432EA950, 0x141600C40),
}


class Rig:
    """Owned byte storage, real clock binding and explicit authored test services."""

    def __init__(self, *, outgoing=0, playback=0, status=1, skip=1, read_status=6):
        self.memory = ReplayMemory()
        self.world = self.memory.allocate(0x900)
        self.clock = self.memory.allocate(0x1C)
        self.descriptor = self.memory.allocate(0xA0)
        self.player = self.memory.allocate(0x230)
        self.screen = self.memory.allocate(0x1253)
        self.manager = self.memory.allocate(1)
        self.frame = self.memory.allocate(0x2B8)
        self.seed = b"\xa5" * 0x2B8
        self.memory.write_bytes(self.frame, self.seed)
        for address, width, value in (
            (self.world + 0x70, 8, 0xCAFE),
            (self.world + 0x228, 8, self.clock),
            (self.world + 0x130, 8, self.manager),
            (self.world + 0x78, 4, 900),
            (self.world + 0x7C, 4, 777),
            (self.world + 0x88, 4, 5),
            (self.world + 0x6B0, 4, 9),
            (self.clock + 0x18, 4, 1025),
            (self.descriptor, 1, outgoing),
            (self.descriptor + 1, 1, playback),
            (self.descriptor + 0x94, 4, 17),
            (self.descriptor + 0x6C, 4, 0),
            (self.descriptor + 0x78, 4, 9),
            (self.player + 0x228, 4, 0x7FC12345),
            (self.player + 0x22C, 4, 0x80000000),
            (self.screen + 0x1252, 1, 0),
        ):
            self.memory.write(address, width, value)
        for address, width, value in (
            (SCREEN, 8, self.screen),
            (DEFAULT, 4, 0xBF800000),
            (GLOBAL, 8, 0xBEEF),
            (FLAG, 4, 0),
        ):
            self.memory.map_bytes(address, value.to_bytes(width, "little"))
        for _, _, vptr, cleanup in CASES.values():
            self.memory.map_bytes(vptr + 0x20, cleanup.to_bytes(8, "little"))
        self.events, self.after_read, self.after_write = [], None, None

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

        self.storage = ReplayTaskRebuildStorage(0x1234, read, write)
        self.handlers = {
            DESC: lambda args: self.descriptor,
            OP2: lambda args: 1,
            OP3: lambda args: 1,
            SKIP: lambda args: skip,
            SETTINGS: lambda args: 0xD00D,
            PRED: lambda args: 1,
            ABORT: lambda args: 0xFA11,
            OBSERVER: lambda args: self.player,
            POSITION: lambda args: None,
            RESET: lambda args: None,
            READER: lambda args: read_status,
            LOOKUP: lambda args: 0xABCDEF00,
            FORMAT: lambda args: None,
            SHOW: lambda args: 0xFEED,
            DESTROY: lambda args: None,
            STOP: lambda args: 0xDEAD,
        }
        for _, _, _, cleanup in CASES.values():
            self.handlers[cleanup] = lambda args: None

        def call(target, args, data):
            assert data is None
            self.events.append(("call", target, args))
            if target in (TIME, SET):
                return self.clock_binding.call(target, args, data)
            if target not in self.handlers:
                raise UnresolvedReplayTaskRebuild(f"actual test child{target:x} unavailable")
            return self.handlers[target](args)

        self.calls = ReplayTaskRebuildCalls(call)
        self.clock_binding = bind_replay_clock_storage(self.storage, self.calls, mxcsr=0x1F80)
        self.prelude = ReplayWorldUpdatePrelude(
            self.world,
            self.frame,
            1000,
            13,
            status,
            0x141628F0C,
            None,
        )

    def run(self):
        return run_replay_world_update_replay_phase(self.storage, self.calls, self.prelude)

    def calls_to(self, target):
        return [e[2] for e in self.events if e[0] == "call" and e[1] == target]

    def targets(self):
        return [e[1] for e in self.events if e[0] == "call"]


def failure_rig(kind):
    if kind in ("op2", "op3"):
        rig = Rig(outgoing=1, skip=0 if kind == "op3" else 1)
        rig.handlers[OP3 if kind == "op3" else OP2] = lambda args: 7
        rig.handlers[PRED] = lambda args: 0x100  # AL0 despite nonzero full result.
    else:
        rig = Rig(playback=1, status=2 if kind == "status" else 1, read_status=2)
    return rig


def test_no_flags_reads_default_and_only_publishes_delta_handoff():
    rig = Rig(status=U32)
    result = rig.run()
    assert (result.world, result.logical_frame, result.entry_time, result.cycle) == (
        rig.world,
        rig.frame,
        1000,
        13,
    )
    assert (result.status, result.default_time, result.next_address, result.returned_status) == (
        U32,
        0xBF800000,
        0x14162951F,
        None,
    )
    assert rig.targets() == [DESC, DESC, TIME]
    assert ("read", DEFAULT, 4) in rig.events
    assert rig.memory.read(rig.world + 0x7C, 4) == 125
    assert rig.memory.read(rig.world + 0x88, 4) == 5
    assert rig.memory.read_bytes(rig.frame, 0x2B8) == rig.seed


@pytest.mark.parametrize(("outgoing", "playback"), [(0, 1), (1, 0), (1, 1)])
def test_record_and_playback_flags_are_independent(outgoing, playback):
    rig = Rig(outgoing=outgoing, playback=playback, skip=0)
    result = rig.run()
    assert bool(rig.calls_to(OP2)) is bool(outgoing)
    assert bool(rig.calls_to(OP3)) is bool(outgoing)
    assert bool(rig.calls_to(READER)) is bool(playback)
    assert result.next_address == 0x14162951F
    assert rig.memory.read(rig.world + 0x7C, 4) == (17 if playback else 125)


def test_op2_holds_descriptor_first_time_and_reads_current_baseline_after_second_get():
    rig = Rig(outgoing=1)
    second = rig.memory.allocate(0x1C)
    rig.memory.write(second + 0x18, 4, 3)
    third_descriptor = rig.memory.allocate(2)
    rig.memory.write_bytes(third_descriptor, b"\x00\x00")
    descriptors = iter([rig.descriptor, rig.descriptor, third_descriptor])
    rig.handlers[DESC] = lambda args: next(descriptors)
    gets = 0

    def after_read(address, width):
        nonlocal gets
        if address == rig.world + 0x228:
            gets += 1
            rig.memory.write(address, 8, second)
        if address == second + 0x18:
            rig.memory.write(rig.world + 0x78, 4, U32 - 1)

    rig.after_read = after_read
    result = rig.run()
    assert rig.calls_to(OP2) == [(rig.descriptor, 5, 1025)]
    assert result.entry_time == 1000 and result.status == 1
    assert gets == 3
    assert rig.memory.read(rig.world + 0x7C, 4) == 5
    assert [args[0] for args in rig.calls_to(TIME)] == [rig.clock, second, second]


@pytest.mark.parametrize("status", [0, 2, 3, 7, U32])
def test_writer_failure_can_continue_without_playback_and_uses_only_predicate_al(status):
    rig = Rig(outgoing=1)
    rig.handlers[OP2] = lambda args: status
    rig.handlers[PRED] = lambda args: 0x123401
    result = rig.run()
    assert result.status == status and result.returned_status is None
    assert rig.calls_to(SETTINGS) == [(rig.world,)]
    assert rig.calls_to(PRED) == [(0xD00D,)]
    assert rig.calls_to(ABORT) == [(rig.descriptor,)]
    assert rig.memory.read(FLAG, 4) == 1
    assert not rig.calls_to(FORMAT) and not rig.calls_to(STOP)


def test_abort_callback_can_enable_playback_and_op3_status_replaces_failed_op2():
    rig = Rig(outgoing=1, skip=0)
    rig.handlers[OP2] = lambda args: U32

    def abort(args):
        rig.memory.write(rig.descriptor + 1, 1, 1)
        rig.memory.write(rig.world + 0x70, 8, 0xBADD)

    rig.handlers[ABORT] = abort
    result = rig.run()
    assert result.status == 1 and result.next_address == 0x14162951F
    assert rig.calls_to(READER)
    assert rig.calls_to(DESC)[-1] == (0xBADD,)


@pytest.mark.parametrize(("skip", "op3"), [(0x100, True), (0x101, False)])
def test_between_writer_predicate_uses_al_and_current_global(skip, op3):
    rig = Rig(outgoing=1, skip=skip)
    rig.memory.write(GLOBAL, 8, 0x87654321)
    rig.run()
    assert rig.calls_to(SKIP) == [(0x87654321,)]
    assert bool(rig.calls_to(OP3)) is op3


def test_op3_holds_observer_reads_y_before_x_and_passes_live_index_home():
    rig = Rig(outgoing=1, skip=0)
    other_player = rig.memory.allocate(0x230)
    count = 0

    def descriptor(args):
        nonlocal count
        count += 1
        if count == 3:
            rig.handlers[OBSERVER] = lambda args: other_player
            rig.memory.write(rig.world + 0x6B0, 4, 17)
        return rig.descriptor

    def after_read(address, width):
        if address == rig.player + 0x22C:
            rig.memory.write(rig.player + 0x228, 4, 0xFFC56789)

    def after_write(address, width, value):
        if address == rig.frame + 0x210:
            rig.memory.write(address, 4, 99)

    def writer(args):
        assert args == (rig.descriptor, 0xFFC56789, 0x80000000, rig.frame + 0x210)
        assert rig.memory.read(args[3], 4) == 99
        return 1

    rig.handlers[DESC], rig.handlers[OP3] = descriptor, writer
    rig.after_read, rig.after_write = after_read, after_write
    rig.run()
    reads = [(e[1], e[2]) for e in rig.events if e[0] == "read"]
    assert reads.index((rig.player + 0x22C, 4)) < reads.index((rig.player + 0x228, 4))
    assert ("write", rig.frame + 0x210, 4, 17) in rig.events


def test_playback_holds_original_entry_and_clock_before_fresh_descriptor_callback():
    rig = Rig(playback=1, status=0)
    replacement = rig.memory.allocate(0x1C)
    rig.memory.write(replacement + 0x18, 4, 2222)
    count = 0

    def descriptor(args):
        nonlocal count
        count += 1
        if count == 3:
            rig.memory.write(rig.world + 0x228, 8, replacement)
            rig.memory.write(rig.world + 0x78, 4, 555)
            rig.memory.write(rig.descriptor + 0x94, 4, 0xFFFFFFF9)
        return rig.descriptor

    rig.handlers[DESC] = descriptor
    rig.prelude = replace(rig.prelude, entry_time=5)
    result = rig.run()
    assert rig.calls_to(SET) == [(rig.clock, 0xFFFFFFFE)]
    assert rig.memory.read(rig.clock + 0x18, 4) == 0xFFFFFFFE
    assert rig.memory.read(replacement + 0x18, 4) == 2222
    assert (result.returned_status, result.next_address) == (4, None)
    assert rig.memory.read(rig.world + 0x78, 4) == 555
    assert rig.memory.read(rig.world + 0x7C, 4) == 777
    assert rig.targets().index(SET) < rig.targets().index(STOP)


@pytest.mark.parametrize(("status", "code"), [(2, 0x2336), (3, 0x2335), (7, 0x2334), (U32, 0x2334)])
def test_playback_status_rejection_uses_real_diagnostic_and_explicit_four(status, code):
    rig = Rig(playback=1, status=status)
    result = rig.run()
    assert (result.returned_status, result.next_address) == (4, None)
    assert rig.calls_to(LOOKUP) == [(code,)]
    assert rig.memory.read(rig.clock + 0x18, 4) == 1017
    assert rig.memory.read(rig.world + 0x78, 4) == 1000
    assert rig.memory.read(rig.world + 0x7C, 4) == 777
    assert not rig.calls_to(RESET) and not rig.calls_to(READER)


def test_manager_uses_held_raw_default_and_reader_output_homes_are_not_initialized():
    rig = Rig(playback=1)
    rig.frame = rig.memory.allocate(0x2B8)
    rig.memory.write(rig.frame + 0x24, 4, 0x12345678)
    rig.prelude = replace(rig.prelude, logical_frame=rig.frame)

    def after_read(address, width):
        if address == DEFAULT:
            rig.memory.write(DEFAULT, 4, 0x7FC56789)

    def reset(args):
        assert args == (rig.manager, U32, U32, 0xBF800000, 0xBF800000)
        assert rig.memory.read(rig.frame + 0x20, 8) == 0x12345678BF800000

    def reader(args):
        assert args == (rig.descriptor, rig.frame + 0x200, rig.frame + 0x210, rig.frame + 0x270)
        for address in args[1:]:
            with pytest.raises(ReplayMemoryError):
                rig.memory.read(address, 4)
        return 6

    rig.after_read, rig.handlers[RESET], rig.handlers[READER] = after_read, reset, reader
    result = rig.run()
    assert result.default_time == 0xBF800000 and result.next_address == 0x14162951F


@pytest.mark.parametrize("read_status", [0, 1, 2, 3, 4, 6, 7, U32])
def test_reader_result_branches_include_non_success_nonzero_continuations(read_status):
    rig = Rig(playback=1, read_status=read_status)
    result = rig.run()
    if read_status in (0, 2):
        assert result.returned_status == 4 and result.next_address is None
        assert rig.memory.read(rig.world + 0x7C, 4) == 777
    else:
        assert result.returned_status is None and result.next_address == 0x14162951F
        assert rig.memory.read(rig.world + 0x7C, 4) == 17
    assert bool(rig.calls_to(STOP)) is (read_status == 0)
    assert bool(rig.calls_to(FORMAT)) is (read_status == 2)
    assert not rig.calls_to(POSITION)


@pytest.mark.parametrize(
    ("enabled", "matching", "applied"), [(0, True, False), (1, False, False), (1, True, True)]
)
def test_reader_position_uses_two_fresh_descriptor_checks_and_current_output_words(
    enabled,
    matching,
    applied,
):
    rig = Rig(playback=1, read_status=1)
    other = rig.memory.allocate(0xA0)
    rig.memory.write(other + 0x78, 4, 99 if matching else 98)
    rig.memory.write(rig.descriptor + 0x6C, 4, enabled)
    count = 0

    def descriptor(args):
        nonlocal count
        count += 1
        if count == 6:
            rig.memory.write(rig.world + 0x6B0, 4, 99)
            return other
        return rig.descriptor

    def reader(args):
        rig.memory.write(args[1], 4, 0x80000000)
        rig.memory.write(args[2], 4, 0x7FC13579)
        rig.memory.write(args[3], 4, 123)
        return 1

    def observer(args):
        rig.memory.write(rig.frame + 0x200, 4, 0xFFC24680)
        return rig.player

    def after_read(address, width):
        if address == rig.frame + 0x210:
            rig.memory.write(rig.frame + 0x200, 4, 0x7FA24680)

    rig.handlers[DESC], rig.handlers[READER], rig.handlers[OBSERVER] = descriptor, reader, observer
    rig.after_read = after_read
    rig.run()
    assert bool(rig.calls_to(POSITION)) is applied
    if applied:
        assert rig.calls_to(POSITION) == [(rig.player, 0x7FA24680, 0x7FC13579, 1)]
    else:
        assert not rig.calls_to(OBSERVER)
    assert count == (6 if enabled else 5)


@pytest.mark.parametrize("kind", ["op2", "op3", "status", "reader"])
def test_diagnostic_whole_frame_and_three_cleanup_orders(kind):
    rig = failure_rig(kind)
    inline, owner, vptr, cleanup = CASES[kind]
    writer = kind in ("op2", "op3")
    expected = bytearray(rig.seed)

    def store(offset, width, value):
        expected[offset : offset + width] = value.to_bytes(width, "little")

    if kind == "op3":
        store(0x210, 4, 9)
    if kind == "reader":
        store(0x20, 4, 0xBF800000)
    if writer:
        store(0x64, 1, 0)
        store(inline, 8, vptr)
        store(owner, 8, rig.frame + inline)
        store(0x2B0, 8, rig.frame + 0x78)
    else:
        store(0x250, 4, 1017)
        store(0x258, 4, 7)
        store(0x238, 8, rig.frame + 0x78)
        store(0x240, 8, rig.frame + 0x250)
    store(0x80, 4, 15)
    store(0x78, 8, 0xABCDEF00)
    store(0x218, 8, 0x14428BB30)
    store(0x220, 8, 0)
    store(0x228, 8, 0)

    def formatter(args):
        assert args == (
            (rig.frame + 0x218, 0x143679A90, 1, rig.frame + 0x2B0)
            if writer
            else (rig.frame + 0x218, 0x1432EA160, 2, rig.frame + 0x238)
        )
        assert rig.memory.read_bytes(rig.frame, 0x2B8) == bytes(expected)
        assert rig.memory.read(rig.screen + 0x1252, 1) == int(kind == "status")

    def show(args):
        if not writer:
            store(0x2B0, 4, 1)
            store(0x2B4, 1, 1)
            store(inline, 8, vptr)
            store(owner, 8, rig.frame + inline)
        assert rig.memory.read_bytes(rig.frame, 0x2B8) == bytes(expected)
        flags = 0xA5A5A500A5A5A5A5 if writer else 0xA5A5A50100000001
        assert args == (rig.screen, rig.frame + 0x218, rig.frame + inline, flags)
        return 999

    rig.handlers[FORMAT], rig.handlers[SHOW] = formatter, show
    result = rig.run()
    selected = [t for t in rig.targets() if t in (FORMAT, SHOW, DESTROY, cleanup)]
    assert selected == (
        [FORMAT, SHOW, DESTROY, cleanup] if writer else [FORMAT, SHOW, cleanup, DESTROY]
    )
    assert rig.calls_to(cleanup) == [(rig.frame + inline, 0)]
    assert rig.memory.read(rig.frame + owner, 8) == (0 if writer else rig.frame + inline)
    # Literal native instruction order, independent of the candidate's helpers.
    stores = []
    if kind == "op3":
        stores.append((0x210, 4, 9))
    if kind == "reader":
        stores.append((0x20, 4, 0xBF800000))
    if writer:
        stores += [(0x64, 1, 0), (inline, 8, vptr), (owner, 8, rig.frame + inline)]
    else:
        stores += [(0x218, 16, 0), (0x228, 8, 0), (0x258, 4, 7), (0x250, 4, 1017)]
    stores += [
        (0x80, 4, 15),
        (0x78, 8, 0xABCDEF00),
        (0x218, 8, 0x14428BB30),
        (0x220, 8, 0),
        (0x228, 8, 0),
    ]
    if writer:
        stores += [(0x2B0, 8, rig.frame + 0x78), (owner, 8, 0)]
    else:
        stores += [
            (0x238, 8, rig.frame + 0x78),
            (0x240, 8, rig.frame + 0x250),
            (0x2B0, 4, 1),
            (0x2B4, 1, 1),
            (inline, 8, vptr),
            (owner, 8, rig.frame + inline),
        ]
    actual = [e for e in rig.events if e[0] == "write" and rig.frame <= e[1] < rig.frame + 0x2B8]
    assert actual == [
        ("write", rig.frame + offset, width, value) for offset, width, value in stores
    ]
    if writer:
        assert result.returned_status is None
    else:
        assert result.returned_status == 4
        flag_event = ("write", rig.screen + 0x1252, 1, 1)
        cleanup_event = ("call", cleanup, (rig.frame + inline, 0))
        if kind == "status":
            assert rig.events.index(flag_event) < rig.events.index(cleanup_event)
        else:
            assert rig.events.index(cleanup_event) < rig.events.index(flag_event)
            assert rig.events.index(flag_event) < rig.events.index(
                ("call", DESTROY, (rig.frame + 0x218,))
            )


@pytest.mark.parametrize("kind", ["op2", "op3", "status", "reader"])
def test_cleanup_uses_replaced_current_pointer_and_vptr_with_correct_dl_and_owner_store(kind):
    rig = failure_rig(kind)
    inline, owner, _, _ = CASES[kind]
    pointer, vptr = rig.memory.allocate(8), rig.memory.allocate(0x28)
    rig.memory.write(pointer, 8, vptr)
    rig.memory.write(vptr + 0x20, 8, 0x12345678)

    def show(args):
        rig.memory.write(rig.frame + owner, 8, pointer)

    def cleanup(args):
        assert args == (pointer, 1)
        rig.memory.write(rig.frame + owner, 8, 0xBADCAFE)

    rig.handlers[SHOW], rig.handlers[0x12345678] = show, cleanup
    rig.run()
    assert rig.calls_to(0x12345678) == [(pointer, 1)]
    assert rig.memory.read(rig.frame + owner, 8) == (0 if kind in ("op2", "op3") else 0xBADCAFE)
    assert ("read", rig.frame + inline, 8) not in rig.events


@pytest.mark.parametrize("kind", ["op2", "op3", "status", "reader"])
def test_null_current_cleanup_owner_skips_dispatch_and_writer_clear(kind):
    rig = failure_rig(kind)
    _, owner, _, cleanup = CASES[kind]

    def show(args):
        rig.memory.write(rig.frame + owner, 8, 0)

    rig.handlers[SHOW] = show
    rig.run()
    assert not rig.calls_to(cleanup)
    assert ("write", rig.frame + owner, 8, 0) not in rig.events


def test_writer_holds_screen_but_reads_current_flags_after_formatter_and_destroys_first():
    rig = failure_rig("op2")
    other_screen = rig.memory.allocate(0x1253)
    replacement, table = rig.memory.allocate(8), rig.memory.allocate(0x28)
    rig.memory.write(replacement, 8, table)
    rig.memory.write(table + 0x20, 8, 0x22223333)

    def lookup(args):
        rig.memory.write(SCREEN, 8, other_screen)
        return 0x12345678

    def formatter(args):
        rig.memory.write(rig.frame + 0x60, 8, 0x1122334455667788)

    def destroy(args):
        rig.memory.write(rig.frame + 0xF8, 8, replacement)

    rig.handlers[LOOKUP], rig.handlers[FORMAT], rig.handlers[DESTROY] = lookup, formatter, destroy
    rig.handlers[0x22223333] = lambda args: None
    rig.run()
    assert rig.calls_to(SHOW) == [
        (rig.screen, rig.frame + 0x218, rig.frame + 0xC0, 0x1122334455667788)
    ]
    assert rig.calls_to(0x22223333) == [(replacement, 1)]


@pytest.mark.parametrize("kind", ["status", "reader"])
def test_playback_reads_flags_before_fresh_screen_and_reader_refreshes_screen_after_cleanup(kind):
    rig = failure_rig(kind)
    screen2, screen3 = rig.memory.allocate(0x1253), rig.memory.allocate(0x1253)
    rig.memory.write(screen2 + 0x1252, 1, 0)
    rig.memory.write(screen3 + 0x1252, 1, 0)
    _, _, _, cleanup = CASES[kind]

    def after_read(address, width):
        if address == rig.frame + 0x2B0:
            rig.memory.write(SCREEN, 8, screen2)
            rig.memory.write(address, 8, 0x9876)

    def finish(args):
        rig.memory.write(SCREEN, 8, screen3)

    rig.after_read, rig.handlers[cleanup] = after_read, finish
    rig.run()
    assert rig.calls_to(SHOW)[0][0] == screen2
    assert rig.calls_to(SHOW)[0][3] == 0xA5A5A50100000001
    assert rig.memory.read(screen3 + 0x1252, 1) == int(kind == "reader")


@pytest.mark.parametrize(("now", "baseline", "expected"), [(900, 900, 0), (3, 0xFFFFFFFE, 5)])
def test_final_getter_precedes_current_baseline_read_and_zero_delta_still_hands_off(
    now,
    baseline,
    expected,
):
    rig = Rig()
    rig.memory.write(rig.clock + 0x18, 4, now)

    def after_read(address, width):
        if address == rig.clock + 0x18:
            rig.memory.write(rig.world + 0x78, 4, baseline)

    rig.after_read = after_read
    assert rig.run().next_address == 0x14162951F
    assert rig.memory.read(rig.world + 0x7C, 4) == expected


@pytest.mark.parametrize("kind", ["op2", "op3", "status", "reader"])
@pytest.mark.parametrize("missing", [FORMAT, SHOW, DESTROY])
def test_missing_diagnostic_child_retains_prefix_and_never_publishes_delta(kind, missing):
    rig = failure_rig(kind)
    rig.handlers.pop(missing)
    with pytest.raises(UnresolvedReplayTaskRebuild, match=f"{missing:x}"):
        rig.run()
    assert rig.memory.read(rig.world + 0x7C, 4) == 777
    assert rig.memory.read(rig.frame + 0x78, 8) == 0xABCDEF00
    assert rig.calls_to(missing)


@pytest.mark.parametrize("missing", [OP2, SKIP, OP3, RESET, READER, POSITION, STOP])
def test_missing_reached_operational_child_refuses_after_prior_effects(missing):
    outgoing = missing in (OP2, SKIP, OP3)
    rig = Rig(
        outgoing=int(outgoing),
        playback=int(not outgoing),
        skip=0,
        status=0 if missing == STOP else 1,
        read_status=1,
    )
    if missing == POSITION:
        rig.memory.write(rig.descriptor + 0x6C, 4, 1)
    rig.handlers.pop(missing)
    with pytest.raises(UnresolvedReplayTaskRebuild, match=f"{missing:x}"):
        rig.run()
    assert rig.calls_to(missing)
    assert rig.memory.read(rig.world + 0x7C, 4) == 777
    if missing in (RESET, READER, POSITION, STOP):
        assert rig.memory.read(rig.clock + 0x18, 4) == 1017
        assert rig.memory.read(rig.world + 0x78, 4) == 1000


def test_default_is_required_even_when_playback_inactive_and_unknown_dispatch_refuses():
    rig = Rig()

    def read(address, width):
        if address == DEFAULT:
            raise ReplayMemoryError("unbacked current default")
        return rig.storage.read(address, width)

    storage = ReplayTaskRebuildStorage(0x1234, read, rig.storage.write)
    with pytest.raises(ReplayMemoryError, match="unbacked current default"):
        run_replay_world_update_replay_phase(storage, rig.calls, rig.prelude)
    assert rig.memory.read(rig.world + 0x7C, 4) == 777
    other = Rig()
    with pytest.raises(UnresolvedReplayTaskRebuild, match="140e15770"):
        run_replay_world_update_replay_phase(
            other.storage,
            ReplayTaskRebuildCalls(None),
            other.prelude,
        )
    assert other.events == [("read", other.world + 0x70, 8)]


@pytest.mark.parametrize(
    "field",
    [
        "entry_time",
        "cycle",
        "incoming_status",
        "world",
        "logical_frame",
    ],
)
@pytest.mark.parametrize("bad", [True, -1, 1 << 64, None])
def test_bad_handoff_scalars_refuse_before_effects(field, bad):
    rig = Rig()
    rig.prelude = replace(rig.prelude, **{field: bad})
    with pytest.raises(ValueError):
        rig.run()
    assert not rig.events


@pytest.mark.parametrize("field", ["entry_time", "cycle", "incoming_status"])
def test_wide_held_dword_is_rejected_without_silent_truncation(field):
    rig = Rig()
    rig.prelude = replace(rig.prelude, **{field: 1 << 32})
    with pytest.raises(ValueError):
        rig.run()
    assert not rig.events


@pytest.mark.parametrize(
    "changes",
    [
        dict(next_address=None, returned_status=1),
        dict(next_address=0x14162951F),
        dict(returned_status=4),
    ],
)
def test_wrong_or_idle_prelude_cannot_be_reused_as_replay_handoff(changes):
    rig = Rig()
    rig.prelude = replace(rig.prelude, **changes)
    with pytest.raises(ValueError, match="hand off"):
        rig.run()
    assert not rig.events
