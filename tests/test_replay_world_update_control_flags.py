"""Source-led controls for the complete303B World control-flag interval."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace

import pytest

from vantage.replay_memory import ReplayMemory
from vantage.replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
)
from vantage.replay_world_update_control_flags import (
    ReplayWorldUpdateControlFlags,
    run_replay_world_update_control_flags,
)
from vantage.replay_world_update_special_mode import ReplayWorldUpdateSpecialMode

SETTING, ROW, CLOCK = 0x14097FB40, 0x1416DFB20, 0x140E68F70
OPTIONS, PREDICATE, RELEASE = 0x140D6A530, 0x1413F7A00, 0x140990140
SETTINGS, GAME, INVALID = 0x14425B930, 0x144353698, 0x143DA5054
U32, U64 = (1 << 32) - 1, (1 << 64) - 1
Handler = Callable[[tuple[int, ...]], int | None]


class Rig:
    def __init__(self, flags: int = 0) -> None:
        self.memory = ReplayMemory()
        self.events: list[tuple] = []
        self.after_read: Callable[[int, int], None] | None = None
        self.after_write: Callable[[int, int, int], None] | None = None
        self.world, self.frame, self.clock = (
            self.alloc(0x800),
            self.alloc(0x2C0, 0xA5),
            self.alloc(8),
        )
        for address, width, value in ((SETTINGS, 8, 0x1234), (GAME, 8, 0x5678), (INVALID, 4, U32)):
            self.memory.map_bytes(address, value.to_bytes(width, "little"))
        self.put(self.world + 0x228, 8, self.clock)
        self.put(self.world + 0x6B0, 4, U32)
        self.setting_result: int | None = 0
        self.clock_result: int | None = 0
        self.predicate_result: int | None = 0
        self.handlers: dict[int, Handler] = {
            SETTING: lambda _a: self.setting_result,
            CLOCK: lambda _a: self.clock_result,
            ROW: lambda _a: None,
            RELEASE: lambda _a: None,
        }
        self.context = ReplayTaskRebuildStorage(1, self.read, self.write)
        self.services = ReplayTaskRebuildCalls(self.call)
        self.phase = ReplayWorldUpdateSpecialMode(
            self.world,
            self.frame,
            0x11223344,
            0x55667788,
            0x99AABBCC,
            0xDD112233,
            flags,
            0x141629B2A,
            None,
        )

    def alloc(self, size: int, fill: int = 0) -> int:
        address = self.memory.allocate(size)
        self.memory.write_bytes(address, bytes([fill]) * size)
        return address

    def put(self, address: int, width: int, value: int) -> None:
        self.memory.write(address, width, value & ((1 << (width * 8)) - 1))

    def get(self, address: int, width: int = 8) -> int:
        return self.memory.read(address, width)

    def read(self, address: int, width: int) -> int:
        self.events.append(("read", address, width))
        value = self.get(address, width)
        if self.after_read:
            self.after_read(address, width)
        return value

    def write(self, address: int, width: int, value: int) -> None:
        self.events.append(("write", address, width, value))
        self.put(address, width, value)
        if self.after_write:
            self.after_write(address, width, value)

    def call(self, target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        assert data is None
        self.events.append(("call", target, args))
        if target not in self.handlers:
            raise UnresolvedReplayTaskRebuild(f"authored child {target:x} unavailable")
        return self.handlers[target](args)

    def calls(self, target: int) -> list[tuple[int, ...]]:
        return [e[2] for e in self.events if e[0] == "call" and e[1] == target]

    def run(self) -> ReplayWorldUpdateControlFlags:
        return run_replay_world_update_control_flags(self.context, self.services, self.phase)

    def carried(self, out: ReplayWorldUpdateControlFlags, flags: int) -> None:
        assert isinstance(out, ReplayWorldUpdateControlFlags)
        for field in ("world", "logical_frame", "entry_time", "cycle", "status", "default_time"):
            assert getattr(out, field) == getattr(self.phase, field)
        assert out.control_flags == flags and out.next_address == 0x141629C59
        assert out.returned_status is None

    def options(self, selector: int = 13, predicate: int = 1) -> tuple[int, ...]:
        first, second = self.alloc(0xA0), self.alloc(0xA0)
        slot1, slot2, cleanup1, cleanup2 = (self.alloc(8) for _ in range(4))
        self.put(first + 0x34, 4, selector)
        self.put(slot1, 8, first)
        self.put(slot2, 8, second)
        self.predicate_result = predicate

        def options_call(a: tuple[int, ...]) -> int:
            n = len(self.calls(OPTIONS))
            assert n in (1, 2)
            assert a[1] == self.frame + (0x60 if n == 1 else 0x2B0)
            self.put(a[1], 8, cleanup1 if n == 1 else cleanup2)
            return slot1 if n == 1 else slot2

        self.handlers[OPTIONS] = options_call
        self.handlers[PREDICATE] = lambda _a: self.predicate_result
        return first, second, slot1, slot2, cleanup1, cleanup2


@pytest.mark.parametrize("setting", [0, 1])
def test_zero_clock_preserves_metadata_and_only_source_prefix_without_cleanup(setting: int) -> None:
    r = Rig()
    r.setting_result = setting
    r.put(r.world + 0x6C7, 1, setting)
    out = r.run()
    r.carried(out, 0)
    assert r.events == [
        ("read", SETTINGS, 8),
        ("call", SETTING, (0x1234, 0x91)),
        ("read", r.world + 0x6C7, 1),
        ("write", r.frame + 0x70, 1, 0),
        ("read", r.world + 0x228, 8),
        ("call", CLOCK, (r.clock,)),
    ]
    assert r.get(r.frame + 0x70) == 0xA5A5A5A5A5A5A500
    assert r.get(r.frame + 0x208, 4) == 0xA5A5A5A5


@pytest.mark.parametrize("flags", [0, 1, 2, 3, 0x80000103, U32])
def test_zero_clock_uses_held_flags_and_current_homes_in_release_order(flags: int) -> None:
    r = Rig(flags)
    first, second, changed_first, changed_second = (r.alloc(8) for _ in range(4))
    r.put(r.frame + 0x60, 8, first)
    r.put(r.frame + 0x2B0, 8, second)
    r.put(r.frame + 0x208, 4, 0x1122)

    def after(a: int, n: int, _v: int) -> None:
        if (a, n) == (r.frame + 0x208, 4):
            r.put(r.frame + 0x208, 4, 0xDEADBEEF)
            r.put(r.frame + 0x2B0, 8, changed_second)

    r.after_write = after

    def release(a: tuple[int, ...]) -> int:
        if a == (changed_second,):
            r.put(r.frame + 0x60, 8, changed_first)
        return -1  # Source ignores these actual child returns.

    r.handlers[RELEASE] = release
    out = r.run()
    r.carried(out, flags & 0xFFFFFFFD)
    expected = [(changed_second,)] if flags & 2 else []
    if flags & 1:
        expected += [(changed_first if flags & 2 else first,)]
    assert r.calls(RELEASE) == expected and not r.calls(OPTIONS)
    assert r.get(r.frame + 0x208, 4) == (0xDEADBEEF if flags & 2 else 0x1122)
    assert not any(e[0] == "read" and e[1] == r.frame + 0x208 for e in r.events)


def test_zero_clock_does_not_normalize_frame70_after_child_callback() -> None:
    r = Rig()

    def clock(_a: tuple[int, ...]) -> int:
        r.put(r.frame + 0x70, 1, 9)
        return 1 << 40  # Low EAX is zero.

    r.handlers[CLOCK] = clock
    r.carried(r.run(), 0)
    assert r.get(r.frame + 0x70) == 0xA5A5A5A5A5A5A509


@pytest.mark.parametrize("word", [0, 1, 2, 0x101, 0x100000001, 1 << 40])
def test_setting_compares_full_low_eax_to_one_and_publishes_held_byte(word: int) -> None:
    r = Rig()
    r.setting_result = word
    r.put(r.world + 0x6C7, 1, 2)

    def row(_a: tuple[int, ...]) -> int:
        r.put(r.world + 0x6C7, 1, 0xFF)
        return -1

    r.handlers[ROW] = row
    r.run()
    held = int((word & U32) == 1)
    assert r.calls(ROW) == [(0, held)]
    assert r.get(r.world + 0x6C7, 1) == held
    row_at = r.events.index(("call", ROW, (0, held)))
    assert r.events[row_at + 1] == ("write", r.world + 0x6C7, 1, held)


@pytest.mark.parametrize("branch", ["sentinel", "at_end", "selected", "negative_count"])
def test_receiver_selection_keeps_unsigned_sar_count_and_calls_even_zero(branch: str) -> None:
    r = Rig()
    r.setting_result = 1
    begin, receiver = r.alloc(32), r.alloc(8)
    index = U32 if branch in ("sentinel", "negative_count") else 1
    end = begin - 16 if branch == "negative_count" else begin + (32 if branch == "selected" else 16)
    r.put(r.world + 0x6B0, 4, index)
    r.put(INVALID, 4, U32 if branch == "sentinel" else 0xBAD)
    r.put(r.world + 0x768, 8, begin)
    r.put(r.world + 0x770, 8, end)
    if branch == "negative_count":
        r.memory.map_bytes(begin + U32 * 16, receiver.to_bytes(8, "little"))
    else:
        r.put(begin + 16, 8, receiver)
    r.run()
    assert r.calls(ROW) == [(receiver if branch in ("selected", "negative_count") else 0, 1)]
    header_reads = [
        e for e in r.events if e[0] == "read" and e[1] in (r.world + 0x768, r.world + 0x770)
    ]
    assert len(header_reads) == (0 if branch == "sentinel" else 2)


def test_receiver_selection_holds_id_and_begin_across_later_reads() -> None:
    r = Rig()
    r.setting_result = 1
    begin, other, selected, changed = r.alloc(16), r.alloc(16), r.alloc(8), r.alloc(8)
    r.put(r.world + 0x6B0, 4, 0)
    r.put(r.world + 0x768, 8, begin)
    r.put(r.world + 0x770, 8, begin + 16)
    r.put(begin, 8, selected)
    r.put(other, 8, changed)

    def after(a: int, _n: int) -> None:
        if a == r.world + 0x6B0:
            r.put(a, 4, 1)
        if a == r.world + 0x768:
            r.put(a, 8, other)

    r.after_read = after
    r.run()
    assert r.calls(ROW) == [(selected, 1)]


def test_selector13_uses_actual_slot_and_holds_boolean_across_cleanup() -> None:
    r = Rig(U32)
    r.clock_result = 1
    first, _second, _slot1, _slot2, cleanup1, _cleanup2 = r.options()

    def release(a: tuple[int, ...]) -> None:
        assert a == (cleanup1,)
        r.put(first + 0x34, 4, 0)

    r.handlers[RELEASE] = release

    def after(a: int, n: int, _v: int) -> None:
        if (a, n) == (r.world + 0x6C6, 1):
            r.put(r.frame + 0x70, 1, 9)

    r.after_write = after
    out = r.run()
    r.carried(out, 1)
    assert r.calls(OPTIONS) == [(0x5678, r.frame + 0x60)]
    assert not r.calls(PREDICATE) and r.calls(RELEASE) == [(cleanup1,)]
    assert r.get(r.world + 0x6C6, 1) == 1 and r.get(r.frame + 0x70, 1) == 1
    assert r.events[-2:] == [("write", r.world + 0x6C6, 1, 1), ("write", r.frame + 0x70, 1, 1)]


def test_final_latch_is_sampled_after_current_cleanup_callback() -> None:
    r = Rig()
    r.clock_result = 1
    r.options()

    def release(_a: tuple[int, ...]) -> None:
        r.put(r.world + 0x6C6, 1, 7)
        r.put(r.frame + 0x70, 1, 6)

    r.handlers[RELEASE] = release
    r.carried(r.run(), 1)
    assert r.get(r.world + 0x6C6, 1) == 7 and r.get(r.frame + 0x70, 1) == 6
    assert not any(e[0] == "write" and e[1] == r.world + 0x6C6 for e in r.events)
    release_at = next(i for i, e in enumerate(r.events) if e[0:2] == ("call", RELEASE))
    latch_at = r.events.index(("read", r.world + 0x6C6, 1))
    assert release_at < latch_at


@pytest.mark.parametrize("predicate", [0, 1, 2, 3, 0x1000000000000100, 0x8000000000000001])
@pytest.mark.parametrize("latched", [0, 7])
def test_two_actual_return_slots_follow_state_stores_and_final_gate_is_late(
    predicate: int,
    latched: int,
) -> None:
    r = Rig(U32)
    r.clock_result = 1 << 32 | 1
    _first, _second, slot1, slot2, cleanup1, cleanup2 = r.options(13, predicate)
    new_first, new_second = r.alloc(0xA0), r.alloc(0xA0)
    r.put(new_first + 0x34, 4, 0)
    r.put(r.world + 0x6C6, 1, latched)
    original_options = r.handlers[OPTIONS]

    def options(a: tuple[int, ...]) -> int | None:
        value = original_options(a)
        r.put(GAME, 8, 0x9876)
        return value

    r.handlers[OPTIONS] = options

    def after(a: int, n: int, value: int) -> None:
        if (a, n) == (r.frame + 0x208, 4):
            if value == 1:
                r.put(slot1, 8, new_first)
            elif value == 3:
                r.put(slot2, 8, new_second)

    r.after_write = after

    def predicate_call(_a: tuple[int, ...]) -> int:
        r.put(r.frame + 0x70, 1, 7)
        return predicate

    r.handlers[PREDICATE] = predicate_call
    out = r.run()
    r.carried(out, 1)
    assert r.calls(OPTIONS) == [(0x5678, r.frame + 0x60), (0x9876, r.frame + 0x2B0)]
    assert r.calls(PREDICATE) == [(new_second + 0x18,)]
    assert r.calls(RELEASE) == [(cleanup2,), (cleanup1,)]
    states = [e[3] for e in r.events if e[0] == "write" and e[1] == r.frame + 0x208]
    assert states == [1, 3, 1]
    final_write = bool(predicate & 1) and not latched
    assert r.get(r.frame + 0x70, 1) == (1 if final_write else 7)
    assert r.get(r.world + 0x6C6, 1) == (1 if final_write else latched)
    read_latch = ("read", r.world + 0x6C6, 1) in r.events
    assert read_latch == bool(predicate & 1)


def test_predicate_pointer_add_wraps_before_actual_child() -> None:
    r = Rig()
    r.clock_result = 1
    _first, _second, _slot1, slot2, _cleanup1, _cleanup2 = r.options(0)
    r.put(slot2, 8, U64 - 15)
    r.run()
    assert r.calls(PREDICATE) == [(8,)]


@pytest.mark.parametrize("target", [SETTING, CLOCK, OPTIONS, PREDICATE, RELEASE, ROW])
def test_missing_reached_child_refuses_with_prior_effects_retained(target: int) -> None:
    r = Rig(1 if target == RELEASE else 0)
    if target in (OPTIONS, PREDICATE):
        r.clock_result = 1
        r.options(0)
    if target == RELEASE:
        r.put(r.frame + 0x60, 8, r.alloc(8))
    if target == ROW:
        r.setting_result = 1
    r.handlers.pop(target)
    with pytest.raises(UnresolvedReplayTaskRebuild):
        r.run()
    assert r.events[-1][0:2] == ("call", target)
    if target in (CLOCK, OPTIONS, PREDICATE, RELEASE):
        assert r.get(r.frame + 0x70, 1) == 0
    if target == PREDICATE:
        assert r.get(r.frame + 0x208, 4) == 3 and not r.calls(RELEASE)
    if target == ROW:
        assert r.get(r.world + 0x6C7, 1) == 0 and r.get(r.frame + 0x70, 1) == 0xA5


@pytest.mark.parametrize("result", [None, -1, 1 << 64, True])
@pytest.mark.parametrize("target", [SETTING, CLOCK, OPTIONS, PREDICATE])
def test_consumed_returns_require_actual_raw_rax(result: int | None, target: int) -> None:
    r = Rig()
    if target in (OPTIONS, PREDICATE):
        r.clock_result = 1
        r.options(0)
    r.handlers[target] = lambda _a: result
    with pytest.raises(ValueError):
        r.run()
    assert r.calls(target)


@pytest.mark.parametrize(
    "field,value",
    [
        ("next_address", None),
        ("next_address", 0x141629C59),
        ("returned_status", 0),
        ("control_flags", -1),
        ("control_flags", 1 << 32),
        ("entry_time", True),
        ("world", -1),
        ("logical_frame", 1 << 64),
    ],
)
def test_bad_handoff_is_rejected_before_storage_effects(field: str, value: int | None) -> None:
    r = Rig()
    r.phase = replace(r.phase, **{field: value})
    with pytest.raises(ValueError):
        r.run()
    assert r.events == []
