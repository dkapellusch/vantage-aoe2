"""Source-led919B World caller controls, authored before candidate inspection."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace

import pytest

from vantage.replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
)
from vantage.replay_world_update_command_bridge import ReplayWorldUpdateCommandBridge
from vantage.replay_world_update_special_mode import (
    ReplayWorldUpdateSpecialMode,
    run_replay_world_update_special_mode,
)

W, F, G, MAP, CLOCK, CFG, SLOT, REF = (
    0x10000,
    0x20000,
    0x30000,
    0x40000,
    0x50000,
    0x60000,
    0x62000,
    0x70000,
)
GAME, LEVEL, LOGGER = 0x144353698, 0x14435505F, 0x144355068
OPTIONS, RELEASE, TIME, SCALAR = 0x140D6A530, 0x140990140, 0x140E68F70, 0x1413D2980
TILE, LOG, UI, FLAG = 0x1415F9740, 0x14101ADB0, 0x140D66C40, 0x140D63400
U32, U64 = (1 << 32) - 1, (1 << 64) - 1


class Memory:
    def __init__(self) -> None:
        self.data: dict[int, int] = {}
        self.events: list[tuple[str, int, int, int]] = []
        self.before_read: Callable[[int, int], None] | None = None
        for start, size in (
            (W, 0x800),
            (F, 0x300),
            (MAP, 0x100),
            (CFG, 0x1200),
            (SLOT, 0x10),
            (REF, 0x100),
            (0x80000, 0x4000),
            (GAME, 8),
            (LEVEL, 1),
            (LOGGER, 8),
            (0x1432EA9D8, 8),
        ):
            self.data.update((a, 0) for a in range(start, start + size))

    def peek(self, address: int, width: int) -> int:
        return int.from_bytes(bytes(self.data[address + i] for i in range(width)), "little")

    def put(self, address: int, width: int, value: int) -> None:
        for i, byte in enumerate((value & ((1 << (width * 8)) - 1)).to_bytes(width, "little")):
            assert address + i in self.data, f"unbacked {address + i:x}"
            self.data[address + i] = byte

    def read(self, address: int, width: int) -> int:
        if self.before_read:
            self.before_read(address, width)
        value = self.peek(address, width)
        self.events.append(("r", address, width, value))
        return value

    def write(self, address: int, width: int, value: int) -> None:
        self.events.append(("w", address, width, value))
        self.put(address, width, value)


class Case:
    def __init__(self, selector: int = 12, width: int = 2, height: int = 2) -> None:
        self.m = Memory()
        for a, n, v in (
            (GAME, 8, G),
            (LOGGER, 8, 0x777),
            (W + 0x98, 8, MAP),
            (W + 0x228, 8, CLOCK),
            (W + 0x234, 4, 1),
            (MAP + 0x30, 4, width),
            (MAP + 0x34, 4, height),
            (CFG + 0x34, 4, selector),
            (CFG + 0x1158, 4, 1),
            (SLOT, 8, CFG),
            (F + 0x208, 4, 0xA5),
            (0x1432EA9DC, 4, 0x3F800000),
            (0x1432EA9D8, 4, 0x3F000000),
        ):
            self.m.put(a, n, v)
        self.times = [0, 60000]
        self.calls: list[tuple[int, tuple[int, ...], bool]] = []
        self.time_index = 0
        self.returns: dict[int, int | None] = {}
        self.hook: Callable[[int, tuple[int, ...], bool], None] | None = None
        self.context = ReplayTaskRebuildStorage(W, self.m.read, self.m.write)
        self.phase = ReplayWorldUpdateCommandBridge(W, F, 17, 23, 7, 0x7FC01234, 0x141629793, None)

    def invoke(self, target: int, args: tuple[int, ...], logger: bool) -> int | None:
        self.calls.append((target, args, logger))
        assert logger == (target == LOG)
        if target == OPTIONS:
            self.m.put(args[1], 8, REF)
            value: int | None = SLOT
        elif target == SCALAR:
            value = self.m.peek(args[0] + 0x1158, 4)
        elif target == TIME:
            value = self.times[self.time_index]
            self.time_index += 1
        else:
            assert target in (RELEASE, TILE, LOG, UI, FLAG)
            value = None
        if self.hook:
            self.hook(target, args, logger)
        return self.returns.get(target, value)

    def run(self) -> ReplayWorldUpdateSpecialMode:
        return run_replay_world_update_special_mode(
            self.context,
            ReplayTaskRebuildCalls(lambda t, a, _k: self.invoke(t, a, False)),
            self.phase,
            logger_home_calls=ReplayTaskRebuildCalls(lambda t, a, _k: self.invoke(t, a, True)),
            mxcsr=0x1F80,
        )

    def targets(self) -> list[int]:
        return [t for t, _, _ in self.calls]

    def tiles(self) -> list[tuple[int, ...]]:
        return [a for t, a, _ in self.calls if t == TILE]


def test_nonselected_actual_slot_current_release_and_historical_metadata() -> None:
    c = Case(11)
    c.m.put(F + 0x208, 4, 0xDEAD)

    def hook(t: int, _a: tuple[int, ...], _l: bool) -> None:
        if t == RELEASE:
            c.m.put(CFG + 0x34, 4, 12)

    c.hook = hook
    out = c.run()
    assert c.calls == [(OPTIONS, (G, F + 0x2B0), False), (RELEASE, (REF,), False)]
    assert (
        out.world,
        out.logical_frame,
        out.entry_time,
        out.cycle,
        out.status,
        out.default_time,
        out.control_flags,
        out.next_address,
        out.returned_status,
    ) == (
        W,
        F,
        17,
        23,
        7,
        0x7FC01234,
        0,
        0x141629B2A,
        None,
    )
    assert not any(a == F + 0x208 for _, a, _, _ in c.m.events)


def test_selected_square_calls_literal_boundary_and_equal_final_store() -> None:
    c = Case()
    out = c.run()
    assert c.targets() == [OPTIONS, RELEASE, TIME, OPTIONS, SCALAR, RELEASE, TIME, TILE, TILE, TILE]
    assert c.tiles() == [(0, W, 0, 0), (0, W, 0, 1), (0, W, 1, 0)]
    assert (out.control_flags, out.status, out.next_address) == (0xA5, 7, 0x141629B2A)
    assert c.m.events[-2:] == [("w", W + 0x148, 4, 0), ("r", F + 0x208, 4, 0xA5)]


def test_rectangular_map_not_square_or_geometric_shortcut() -> None:
    c = Case(width=4, height=3)
    out = c.run()
    assert c.tiles() == [
        (0, W, 0, 0),
        (0, W, 0, 1),
        (0, W, 0, 2),
        (0, W, 1, 0),
        (0, W, 1, 2),
        (0, W, 3, 0),
        (0, W, 3, 2),
    ]
    assert out.control_flags == 0xA5


def test_magic_unsigned_multiplications_change_second_divisor() -> None:
    c = Case()
    c.times = [3_000_000, 48_000]
    c.run()
    assert c.m.peek(F + 0x94, 4) == 0
    assert len(c.tiles()) == 3
    assert UI not in c.targets()


@pytest.mark.parametrize("width", [U32, U32 - 1, 0x80000000])
def test_signed_negative_width_skips_outer_and_retains_delta(width: int) -> None:
    c = Case(width=width, height=1)
    c.times = [0, 0]
    if width == 0x80000000:
        c.m.put(0x1432EA9DC, 4, 0x47000000)
    c.m.put(0x1432EA9D8, 4, 0)
    out = c.run()
    assert c.tiles() == []
    assert ("r", F + 0x94, 4, 0) not in c.m.events
    assert c.m.peek(F + 0x90, 4) == ((-(abs(width - (1 << 32)) // 2)) & U32)
    assert out.control_flags == 0xA5


def test_empty_inner_does_not_reload_row_homes_but_reloads_delta() -> None:
    c = Case(height=0)
    c.run()
    assert c.tiles() == []
    for offset in (0x210, 0x200, 0x90):
        assert not any(k == "r" and a == F + offset for k, a, _, _ in c.m.events)
    assert [e for e in c.m.events if e[:3] == ("r", F + 0x94, 4)] == [
        ("r", F + 0x94, 4, 0),
    ]


def test_live_row_bounds_late_delta_logger_homes_and_two_fresh_games() -> None:
    c = Case()
    c.m.put(LEVEL, 1, 1)
    for offset in (0x78, 0x80, 0x250, 0x258):
        c.m.put(F + offset, 8, 0xABCD0123DEADBEEF)

    def hook(t: int, a: tuple[int, ...], _l: bool) -> None:
        if t == TILE:
            c.m.put(F + 0x210, 4, 1)
            c.m.put(F + 0x200, 4, 1)
            c.m.put(F + 0x90, 4, 9)
            c.m.put(F + 0x94, 4, 7)
        if t == LOG:
            assert a == (0x777, 0x27, 0x1432EA1B0, 2, F + 0x20)
            assert c.m.peek(a[4], 8) == F + 0x238
            assert c.m.peek(F + 0x238, 8) == F + 0x78
            assert c.m.peek(F + 0x240, 8) == F + 0x250
            assert c.m.peek(F + 0x78, 8) == 0xABCD012300000007
            assert c.m.peek(F + 0x80, 8) == 0xABCD012300000002
            assert c.m.peek(F + 0x250, 8) == 0xABCD012300000001
            assert c.m.peek(F + 0x258, 8) == 0xABCD012300000002
            assert c.m.peek(W + 0x148, 4) == 0
            c.m.put(F + 0x208, 4, 0x55)
            c.m.put(GAME, 8, G + 1)
        if t == UI:
            assert a == (G + 1,)
            c.m.put(GAME, 8, G + 2)
        if t == FLAG:
            assert a == (G + 2,)
            assert c.m.peek(W + 0x148, 4) == 0

    c.hook = hook
    out = c.run()
    assert c.tiles() == [(0, W, 0, 0), (0, W, 0, 1)]
    assert c.targets()[-3:] == [LOG, UI, FLAG]
    assert c.m.peek(W + 0x148, 4) == 7
    assert out.control_flags == 0x55 and out.status == 7


@pytest.mark.parametrize("level", [0, 1, 255])
def test_inequality_level_gate_and_equal_store_order(level: int) -> None:
    c = Case()
    c.m.put(W + 0x148, 4, 99)
    c.m.put(LEVEL, 1, level)
    c.run()
    assert (LOG in c.targets()) == bool(level)
    assert c.targets()[-2:] == [UI, FLAG]
    assert c.m.peek(W + 0x148, 4) == 0


def test_missing_initial_player_skips_scan_only() -> None:
    c = Case()
    c.m.put(W + 0x234, 4, 0)
    c.m.put(W + 0x768, 8, 0x80000)
    c.run()
    assert c.m.peek(W + 0x234, 4) == 0
    assert len(c.tiles()) == 3


def test_scan_skips_then_redecodes_selected_signed_word() -> None:
    c = Case()
    player, header, array, unit, master = 0x80100, 0x80200, 0x80300, 0x80400, 0x80500
    for a, n, v in (
        (W + 0x234, 4, 0),
        (W + 0x768, 8, 0x80000),
        (0x80000, 8, player),
        (player + 0x30, 8, header),
        (header + 8, 8, array),
        (header + 0x10, 4, 2),
        (array + 8, 8, unit),
        (unit + 0xF, 1, 0x46),
        (unit + 0x10, 8, master + 0x6A586EB28AC201FC + 0x0CF19788B2554E70),
        (master + 0x38, 8, (2 - 0x5B32AA7995D95916 + 0x50A06BCECEBEF905) & U64),
        (master + 0x18, 8, (0xFFF9 + 0x47E37DFF0616CE4F) ^ 0x349E37847AD69F19),
    ):
        c.m.put(a, n, v)
    c.run()
    assert c.m.peek(W + 0x234, 4) == 0xFFFFFFF9
    assert len([e for e in c.m.events if e[:3] == ("r", unit + 0x10, 8)]) == 2
    stores = [e[3] for e in c.m.events if e[:3] == ("w", F + 0x68, 8)]
    assert stores[:3] == [
        (master + 0x6A586EB28AC201FC + 0x0CF19788B2554E70) & U64,
        (master + 0x0CF19788B2554E70) & U64,
        master,
    ]
    assert stores[-1] & 0xFFFF == 0xFFF9


def test_scan_backedge_current_count_retains_initial_array() -> None:
    c = Case()
    for a, n, v in (
        (W + 0x234, 4, 0),
        (W + 0x768, 8, 0x80000),
        (0x80000, 8, 0x80100),
        (0x80130, 8, 0x80200),
        (0x80208, 8, 0x80300),
        (0x80210, 4, 2),
    ):
        c.m.put(a, n, v)
    reads = 0

    def before(a: int, _n: int) -> None:
        nonlocal reads
        if a == W + 0x768:
            reads += 1
            if reads == 2:
                c.m.put(0x80000, 8, 0x80600)
                c.m.put(0x80630, 8, 0x80700)
                c.m.put(0x80710, 4, 1)
                c.m.put(0x80708, 8, 0x80800)

    c.m.before_read = before
    c.run()
    assert ("r", 0x80300, 8, 0) in c.m.events
    assert not any(a in (0x80308, 0x80800) for _, a, _, _ in c.m.events)


def test_first_unsigned_division_zero_preserves_prefix() -> None:
    c = Case(width=0)
    with pytest.raises(UnresolvedReplayTaskRebuild):
        c.run()
    assert c.targets() == [OPTIONS, RELEASE, TIME]
    assert not any(k == "w" and a == F + 0x94 for k, a, _, _ in c.m.events)


def test_second_division_zero_is_after_second_clock_and_current_width_read() -> None:
    c = Case()
    c.m.put(CFG + 0x1158, 4, 0)
    with pytest.raises(UnresolvedReplayTaskRebuild):
        c.run()
    assert c.targets() == [OPTIONS, RELEASE, TIME, OPTIONS, SCALAR, RELEASE, TIME]
    assert c.m.events[-1][:3] == ("r", MAP + 0x30, 4)
    assert not any(k == "w" and a == F + 0x94 for k, a, _, _ in c.m.events)


@pytest.mark.parametrize("word", [0x7FC01234, 0x7F800000, 0xFF800000])
def test_cvtt_indefinite_is_valid_unsigned_divisor(word: int) -> None:
    c = Case(width=U32, height=0)
    c.m.put(0x1432EA9DC, 4, word)
    c.m.put(0x1432EA9D8, 4, 0)
    c.times = [0, U32]
    c.run()
    assert c.m.peek(F + 0x94, 4) == 1
    assert c.tiles() == []


@pytest.mark.parametrize("target", [TIME, SCALAR])
def test_raw_high_rax_bits_narrow_at_eax_consumer(target: int) -> None:
    c = Case()
    c.returns[target] = (1 << 48) | (1 if target == SCALAR else 0)
    c.run()
    assert c.m.peek(F + 0x94, 4) == (0 if target == SCALAR else U32)


@pytest.mark.parametrize("value", [None, -1, 1 << 64, True])
def test_consumed_options_rax_must_be_raw_u64(value: int | None) -> None:
    c = Case()
    c.returns[OPTIONS] = value
    with pytest.raises(ValueError):
        c.run()
    assert c.targets() == [OPTIONS]


@pytest.mark.parametrize("target", [TILE, LOG, UI, FLAG])
def test_opaque_ignored_results_remain_ignored(target: int) -> None:
    c = Case()
    c.m.put(W + 0x148, 4, 99)
    c.m.put(LEVEL, 1, 1)
    c.returns[target] = -1
    c.run()
    assert c.m.peek(W + 0x148, 4) == 0


@pytest.mark.parametrize("target", [TILE, LOG, UI, FLAG])
def test_child_refusal_retains_prefix_and_does_not_publish_delta(target: int) -> None:
    c = Case()
    c.m.put(W + 0x148, 4, 99)
    c.m.put(LEVEL, 1, 1)

    def hook(t: int, _a: tuple[int, ...], _l: bool) -> None:
        if t == target:
            raise UnresolvedReplayTaskRebuild("actual reached child unavailable")

    c.hook = hook
    with pytest.raises(UnresolvedReplayTaskRebuild):
        c.run()
    assert c.targets()[-1] == target
    assert c.m.peek(W + 0x148, 4) == 99
    assert c.m.peek(F + 0x94, 4) == 0


@pytest.mark.parametrize("next_address,returned", [(0x14162951F, None), (None, 1)])
def test_wrong_bridge_handoff_refuses_before_effects(
    next_address: int | None, returned: int | None
) -> None:
    c = Case()
    c.phase = replace(c.phase, next_address=next_address, returned_status=returned)
    with pytest.raises(ValueError):
        c.run()
    assert c.m.events == [] and c.calls == []
