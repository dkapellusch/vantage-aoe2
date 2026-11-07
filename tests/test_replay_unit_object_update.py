"""Owned-state Unit controls and actual inherited simulation composition.

HP,graphics,position,suffix and FP-import services are explicit authored effects.
No Game instructions or restored recording World are executed. The percentage
oracle uses host binary64/Fraction independently of the integer candidate.
"""

from __future__ import annotations

import math
import random
import struct
from collections.abc import Callable
from dataclasses import fields, replace
from fractions import Fraction
from pathlib import Path
from typing import cast

import pytest
from test_replay_action_object_update import BASE, CLOCK, U32, U64, encoded
from test_replay_combat_object_update import COMBAT, HAS
from test_replay_combat_object_update import Rig as CombatRig

from vantage.replay_binary32 import add_binary32, subtract_binary32
from vantage.replay_memory import ReplayMemoryError
from vantage.replay_object_update import (
    ReplayObjectUpdateProfile,
    bind_replay_object_update,
)
from vantage.replay_player_color_context import (
    ReplayPlayerColorContextScratch,
    bind_replay_player_color_context,
)
from vantage.replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    UnresolvedReplayTaskRebuild,
)
from vantage.replay_unit_object_update import (
    ReplayUnitObjectUpdateProfile,
    bind_replay_unit_object_update,
)

UNIT, ABS, FMOD, MASTER_PRED, PERCENT, IDLE = (
    0x1412BD4C0,
    0x140A81F80,
    0x142D6E53D,
    0x14114B320,
    0x14114C340,
    0x140D1B180,
)
RATE, MAXIMUM, HEALTH, HEAL, HURT, POSITION = (
    0xF20278,
    0xF200D0,
    0xF200C8,
    0xF200C0,
    0xF200B8,
    0xF20900,
)
SETUP, START, STOP, RULE, STEP, TRIM, END_TEST, END_FALLBACK = (
    0x1414826E0,
    0x141485F70,
    0x141484E80,
    0x141691140,
    0x1412BC410,
    0x1412BD1D0,
    0x1412B79B0,
    0x1412BAB30,
)
SUFFIX = (0x1412B84C0, 0x1412BECC0, 0x1412BE050, 0x1412BC210)
IMPORT, OTHER_IMPORT = 0xF30001, 0xF30002
HX, HA = 0x0F2A55F7A61DD00E, 0x147B5E081EC087D9
DATA = Path(__file__).resolve().parents[1] / "artifacts/game-internals/2026-10-18-world-envelope"
CHANNELS = (
    "scalar_fp_calls",
    "imports_fp_calls",
    "virtual_fp_calls",
    "virtual_fp_apply_calls",
    "position_fp_home_calls",
    "graphic_home_calls",
)


def bits(value: float) -> int:
    return int.from_bytes(struct.pack("<f", value), "little")


def floating(word: int) -> float:
    return float(struct.unpack("<f", word.to_bytes(4, "little"))[0])


def health_encoded(value: int) -> int:
    return ((value + HA) & U64) ^ HX


def health_decoded(value: int) -> int:
    return ((value ^ HX) - HA) & U64


class Rig(CombatRig):
    def __init__(self) -> None:
        super().__init__()
        self.real_combat = False
        self.combat_result = 0x1234000000F3
        self.rule = 0
        self.rate = 0
        self.maximum = bits(10.0)
        self.hp = bits(5.0)
        self.trim, self.end = 1, 1
        self.graphic_state: dict[int, tuple[int, int]] = {}
        self.positions: list[tuple[int, ...]] = []
        old_table = self.table
        self.table = self.alloc(0xA00)
        self.mem.write_bytes(self.table, self.mem.read_bytes(old_table, 0x900))
        self.mem.write(self.obj, 8, self.table)
        for slot, target in (
            (0x278, RATE),
            (0xD0, MAXIMUM),
            (0xC8, HEALTH),
            (0xC0, HEAL),
            (0xB8, HURT),
            (0x900, POSITION),
        ):
            self.mem.write(self.table + slot, 8, target)
        self.script_obj = self.alloc(0x200)
        self.mem.write(self.script_obj, 8, self.script_table)
        self.ui = self.alloc(0x1900)
        self.mem.map_bytes(0x144415600, self.ui.to_bytes(8, "little"))
        self.mem.map_bytes(0x143199FA0, IMPORT.to_bytes(8, "little"))
        for constant in (DATA / "unit-object-update-source-v1").glob("constant-*.bin"):
            at, raw = int(constant.stem.split("-")[1], 16), constant.read_bytes()
            try:
                assert self.mem.read_bytes(at, len(raw)) == raw
            except ReplayMemoryError:
                self.mem.map_bytes(at, raw)
        self.mem.write(self.resource + 0x8D0, 8, encoded(0))
        self.mem.write(self.resource + 0x208, 8, encoded(0))
        self.mem.write(self.world + 0x6B0, 4, 1)
        self.color = bind_replay_player_color_context(
            self.context,
            self.ordinary_calls,
            bind_local=self.local,
            scratch=ReplayPlayerColorContextScratch(bytes(4)),
        )
        self.unit_profile = ReplayUnitObjectUpdateProfile(
            bytes([0xA5]) * 0x90, bytes([0xA6]) * 0x10, bytes([0xA7]) * 0xC
        )
        self.unit = self.bind_unit()

    def set_health(self, word: int, high: int = 0) -> None:
        self.hp = word
        self.mem.write(self.obj + 0x130, 8, health_encoded(high << 32 | word))

    def active(self) -> None:
        self.mem.write(self.obj + 0x188, 1, 2)
        self.set_health(bits(5.0))

    def bind_unit(self, **overrides: ReplayTaskRebuildCalls) -> ReplayTaskRebuildCalls:
        channels = {name: ReplayTaskRebuildCalls(self.channel(name)) for name in CHANNELS}
        channels.update(overrides)
        return bind_replay_unit_object_update(
            self.context,
            self.ordinary_calls,
            **channels,
            bind_local=self.local,
            profile=self.unit_profile,
            mxcsr=0x1F80,
        )

    def ordinary(self, target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        local = (
            target
            in (
                COMBAT,
                HAS,
                RULE,
                START,
                STOP,
                STEP,
                TRIM,
                END_TEST,
                END_FALLBACK,
                0x142D6BAB4,
                0x141734F30,
            )
            or target in SUFFIX
        )
        if not local:
            return super().ordinary(target, args, data)
        assert data is None
        if handler := self.record("calls", target, args):
            return handler(args)
        if target == COMBAT:
            if self.real_combat:
                assert self.combat.call is not None
                return self.combat.call(target, args, None)
            return self.combat_result
        if target == HAS:
            assert self.combat.call is not None
            return self.combat.call(target, args, None)
        if target == RULE:
            return self.rule
        if target == 0x141734F30:
            assert self.color.call is not None
            return self.color.call(target, args, None)
        if target == 0x142D6BAB4:
            assert self.runtime.call is not None
            return self.runtime.call(target, args, None)
        if target == TRIM:
            return self.trim
        if target == END_TEST:
            return self.end
        if target == START:
            self.graphic_state[args[0]] = (args[1], args[2])
        if target == STOP:
            self.graphic_state.pop(args[0], None)
        return None

    def channel(
        self, channel: str
    ) -> Callable[[int, tuple[int, ...], memoryview | None], int | None]:
        fallback = super().channel(channel)

        def dispatch(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
            local = (
                channel
                in (
                    "imports_fp_calls",
                    "virtual_fp_apply_calls",
                    "position_fp_home_calls",
                    "graphic_home_calls",
                )
                or (channel == "scalar_fp_calls" and target in (ABS, FMOD))
                or (channel == "virtual_fp_calls" and target in (RATE, MAXIMUM, HEALTH))
            )
            if not local:
                return fallback(target, args, data)
            assert data is None
            if handler := self.record(channel, target, args):
                return handler(args)
            if channel == "scalar_fp_calls":
                assert self.unit.call is not None
                return self.unit.call(target, args, None)
            if channel == "imports_fp_calls" and target in (IMPORT, OTHER_IMPORT):
                left, right = (floating(word) for word in args)
                if not math.isfinite(left) or not right:
                    return 0x7FC00000
                return bits(math.fmod(left, right))
            if channel == "virtual_fp_calls":
                return {RATE: self.rate, MAXIMUM: self.maximum, HEALTH: self.hp}[target]
            if channel == "virtual_fp_apply_calls":
                if target == HEAL:
                    self.hp = add_binary32(self.hp, args[1])
                elif target == HURT:
                    self.hp = subtract_binary32(self.hp, args[1])
                else:
                    raise UnresolvedReplayTaskRebuild("unknown authored health effect")
                self.mem.write(self.obj + 0x130, 8, health_encoded(self.hp))
                return None
            if channel == "position_fp_home_calls" and target == POSITION:
                self.positions.append(args)
                self.mem.write(args[-1], 1, 1)
                return None
            if channel == "graphic_home_calls" and target == SETUP:
                self.graphic_state[args[0]] = (args[1], 0)
                return None
            raise UnresolvedReplayTaskRebuild(f"authored {channel} missing{target:x}")

        return dispatch

    def run_unit(self, target: int = UNIT, *args: int) -> int | None:
        assert self.unit.call is not None
        return self.unit.call(target, args or (self.obj,), None)


@pytest.mark.parametrize("field", [f.name for f in fields(ReplayUnitObjectUpdateProfile)])
def test_exact_immutable_profile_prefixes(field: str) -> None:
    r = Rig()
    for seed in (b"", bytearray(getattr(r.unit_profile, field))):
        with pytest.raises(ValueError):
            replace(r.unit_profile, **{field: seed})


@pytest.mark.parametrize(
    ("target", "arity"), [(UNIT, 1), (ABS, 1), (FMOD, 2), (MASTER_PRED, 1), (PERCENT, 1), (IDLE, 1)]
)
def test_addressed_shape_refuses_before_effects(target: int, arity: int) -> None:
    r = Rig()
    assert r.unit.call is not None
    for args, data in (((), None), ((-1,) * arity, None), ((r.obj,) * arity, memoryview(b"raw"))):
        with pytest.raises(ValueError):
            r.unit.call(target, args, data)
    assert not r.events


def test_unknown_calls_preserve_identity() -> None:
    r = Rig()
    args, data, result = (-1, 3), memoryview(b"raw"), 123456789012345

    def unknown(target: int, given: tuple[int, ...], payload: memoryview | None) -> int:
        assert target == 17 and given is args and payload is data
        return result

    r.ordinary_calls = ReplayTaskRebuildCalls(unknown)
    bound = r.bind_unit()
    assert bound.call is not None and bound.call(17, args, data) is result


@pytest.mark.parametrize("word", [0, 0x80000000, 0xBF800000, 0xFF800000, 0xFFA12345, 0x7FA12345])
def test_fabs_is_raw_sign_clear_without_quieting_nan(word: int) -> None:
    r = Rig()
    assert r.run_unit(ABS, word) == word & 0x7FFFFFFF
    assert not r.live


def test_fabs_returns_current_home_after_and_store() -> None:
    r = Rig()

    def mutate(at: int, width: int, value: int) -> None:
        if at == r.frame(0xC) + 8 and value == 0x3F800000:
            r.mem.write(at, 4, 0x80000000)

    r.after_write = mutate
    assert r.run_unit(ABS, 0xBF800000) == 0x80000000


def test_fmod_reads_current_iat_and_forwards_import_identity() -> None:
    r = Rig()
    r.mem.write(0x143199FA0, 8, OTHER_IMPORT)
    result = 123456789012345
    r.handlers["imports_fp_calls", OTHER_IMPORT] = lambda args: result
    assert r.run_unit(FMOD, bits(2.5), bits(1.0)) is result
    assert r.called(OTHER_IMPORT, "imports_fp_calls") == [(bits(2.5), bits(1.0))]


@pytest.mark.parametrize(("kind", "expected"), [(0xFFFD, 1), (0, 0), (0xFFFF, 0)])
def test_master_predicate_reads_current_decoded_master_word(kind: int, expected: int) -> None:
    r = Rig()
    r.mem.write(r.master + 0x3C2, 2, kind)
    assert r.run_unit(MASTER_PRED) == expected


@pytest.mark.parametrize(
    ("enabled", "busy", "target", "expected"),
    [(1, 0, U32, 1), (0, 0, U32, 0), (1, 1, U32, 0), (1, 0, 3, 0)],
)
def test_idle_predicate_short_circuits_current_fields(
    enabled: int, busy: int, target: int, expected: int
) -> None:
    r = Rig()
    r.mem.write(r.script_obj + 0x1C0, 1, enabled)
    r.mem.write(r.script_obj + 0xD0, 4, busy)
    r.mem.write(r.script_obj + 0x44, 4, target)
    assert r.run_unit(IDLE, r.script_obj) == expected
    if not enabled:
        assert not any(e[1] == r.script_obj + 0xD0 for e in r.events)


def test_percentage_matches_independent_binary64_oracle_including_wrapped_times() -> None:
    r = Rig()
    rng = random.Random(54800)
    cases = [
        (0, 0, 0),
        (100, 0, 0),
        (100, 0, 1),
        (100, 0, 99),
        (100, 0, 100),
        (100, 0, 101),
        (U32, U32 - 4, 1),
    ]
    cases += [
        (rng.randrange(1 << 32), rng.randrange(1 << 32), rng.randrange(1 << 32))
        for _ in range(1024)
    ]
    cases += [
        (interval, 0, elapsed)
        for interval in range(1, 101)
        for elapsed in (0, interval // 3, interval - 1, interval)
    ]
    for interval, start, now in cases:
        r.mem.write(r.obj + 0x50C, 4, interval)
        r.mem.write(r.obj + 0x510, 4, start)
        r.mem.write(r.clock + 0x18, 4, now)
        elapsed = (now - start) & U32
        numerator = 0 if elapsed > interval else interval - elapsed
        expected = int(float(Fraction(numerator, interval)) * 100.0) if interval else 0x80000000
        assert r.run_unit(PERCENT) == expected, (interval, start, now)


@pytest.mark.parametrize(
    ("scale", "expected"),
    [
        (0x7FF0000000000000, 0x80000000),
        (0x7FF8123456789ABC, 0x80000000),
        (0xBFF0000000000000, U32),
        (0x41E0000000000000, 0x80000000),
    ],
)
def test_percentage_uses_current_scale_and_cvtt32_indefinite(scale: int, expected: int) -> None:
    r = Rig()
    r.mem.write(r.obj + 0x50C, 4, 100)
    r.mem.write(r.clock + 0x18, 4, 0)
    r.mem.write(0x1432A85D0, 8, scale)
    assert r.run_unit(PERCENT) == expected


def test_percentage_holds_start_before_clock_and_reads_interval_after_callback() -> None:
    r = Rig()

    def clock(args: tuple[int, ...]) -> int:
        r.mem.write(r.obj + 0x510, 4, 500)
        r.mem.write(r.obj + 0x50C, 4, 200)
        return 100

    r.handlers["calls", 0x140D6AD50] = clock
    assert r.run_unit(PERCENT) == 50


def test_default_caller_holds_combat_al_and_invokes_all_required_suffixes() -> None:
    r = Rig()
    assert r.run_unit() == 0xF3
    assert r.called(COMBAT) == [(r.obj,)]
    assert r.called(RATE, "virtual_fp_calls") == [(r.obj,)]
    assert r.called(STEP) == [(r.obj, 0xF3)]
    suffix = [at for channel, at, args in r.calls if channel == "calls" and at in SUFFIX]
    assert suffix == list(SUFFIX)
    assert not r.called(END_FALLBACK) and not r.live


@pytest.mark.parametrize("kind", [0x12, 0x35])
def test_special_class_regeneration_uses_master_rate_without_general_rule(kind: int) -> None:
    r = Rig()
    r.active()
    r.object_class(kind)
    r.mem.write(r.master + 0x2D8, 4, bits(4.0))
    r.mem.write(r.obj + 0x168, 4, bits(2.0))
    r.run_unit()
    assert r.mem.read(r.obj + 0x168, 4) == bits(3.0)
    assert r.mem.read(r.obj + 0x160, 2) == 0x22
    assert not r.called(RULE)


@pytest.mark.parametrize(
    ("start", "expected"),
    [(bits(99.5), bits(100.0)), (bits(100.0), bits(100.0)), (0x7FC12345, 0x7FC12345)],
)
def test_general_regeneration_protected_rate_and_source_cap_store_order(
    start: int, expected: int
) -> None:
    r = Rig()
    r.active()
    r.rule = 1
    r.mem.write(r.resource + 0x8D0, 8, encoded(bits(4.0)))
    r.mem.write(r.obj + 0x168, 4, start)
    r.run_unit()
    assert r.mem.read(r.obj + 0x168, 4) == expected
    writes = [e[3] for e in r.events if e[:3] == ("w", r.obj + 0x168, 4)]
    assert writes[0] == (0x7FC12345 if start == 0x7FC12345 else bits(floating(start) + 1.0))


def test_general_rule_holds_world_but_loads_owner_id_after_kind_decode() -> None:
    r = Rig()
    r.kind(0xFFFF)

    def mutate(at: int, width: int, value: int) -> None:
        if at == r.master + 0x18:
            r.mem.write(r.obj + 0x18, 8, r.player2)

    r.after_read = mutate
    r.run_unit()
    assert r.called(RULE) == [(r.world, 2, U32, 0x68)]


def test_regeneration_comparison_is_held_before_value_store_callback_changes_cap() -> None:
    r = Rig()
    r.active()
    r.object_class(0x12)
    r.mem.write(r.obj + 0x168, 4, bits(150.0))
    r.mem.write(r.master + 0x2D8, 4, bits(4.0))

    def mutate(at: int, width: int, value: int) -> None:
        if at == r.obj + 0x168:
            r.mem.write(0x1436A02E4, 4, bits(200.0))

    r.after_write = mutate
    r.run_unit()
    assert r.mem.read(r.obj + 0x168, 4) == bits(100.0)


@pytest.mark.parametrize(
    ("timer", "expected", "decrement"),
    [(8, 1, False), (7, 2000, True), (0, 2000, True), (0x8000, 0x7FF9, False)],
)
def test_class28_signed_word_timer_and_six_wrapped_counters(
    timer: int, expected: int, decrement: bool
) -> None:
    r = Rig()
    r.object_class(0x28)
    r.mem.write(r.obj + 0x168, 4, bits(3.0))
    r.mem.write(r.obj + 0x624, 2, timer)
    r.mem.write(r.resource + 0x208, 8, encoded(bits(2.0)))
    r.run_unit()
    assert r.mem.read(r.obj + 0x624, 2) == expected
    assert [r.mem.read(r.obj + offset, 2) for offset in range(0x618, 0x624, 2)] == [
        0xFFFF if decrement else 0
    ] * 6
    assert r.mem.read(r.obj + 0x168, 4) == bits(2.0 if decrement else 3.0)


def test_class28_resource_owner_is_held_before_timer_store() -> None:
    r = Rig()
    r.object_class(0x28)
    r.mem.write(r.obj + 0x168, 4, bits(3.0))
    r.mem.write(r.resource + 0x208, 8, encoded(bits(2.0)))
    other_resource = r.alloc(0x900)
    r.mem.write(other_resource + 0x208, 8, encoded(bits(3.0)))
    r.mem.write(r.player2 + 0x98, 8, other_resource)

    def mutate(at: int, width: int, value: int) -> None:
        if at == r.obj + 0x624:
            r.mem.write(r.obj + 0x18, 8, r.player2)

    r.after_write = mutate
    r.run_unit()
    assert r.mem.read(r.obj + 0x624, 2) == 2000


def test_stance_graphic_partial_arguments_and_current_animation_second_call() -> None:
    r = Rig()
    r.mem.write(r.master + 0x378, 1, 2)
    graphic = r.alloc(8)
    r.mem.write(r.master + 0x388, 8, graphic)
    r.mem.write(r.obj + 0x1F0, 8, r.script_obj)
    r.mem.write(r.script_obj + 0x1C0, 1, 1)
    r.mem.write(r.script_obj + 0x44, 4, U32)
    r.mem.write(r.obj + 0xE, 1, 0x7F)
    other_animation = r.alloc(8)

    def setup(args: tuple[int, ...]) -> None:
        assert args[:4] == (r.animation, graphic, 0x3C, 0)
        assert r.mem.read_bytes(args[4], 8) == bytes(4) + b"\xa5" * 4
        assert r.mem.read_bytes(args[5], 8) == b"\x7f\x00" + b"\xa5" * 6
        r.mem.write(r.obj + 0x28, 8, other_animation)

    r.handlers["graphic_home_calls", SETUP] = setup
    r.run_unit()
    assert r.called(START) == [(other_animation, graphic, 2)]
    assert r.mem.read(r.obj + 0x68D, 1) == 1


def test_nonidle_stance_stops_required_graphic_before_clearing_flag() -> None:
    r = Rig()
    r.mem.write(r.master + 0x378, 1, 2)
    graphic = r.alloc(8)
    r.mem.write(r.master + 0x388, 8, graphic)
    r.mem.write(r.obj + 0x68D, 1, 1)
    r.run_unit()
    assert r.called(STOP) == [(r.animation, graphic)]
    assert r.mem.read(r.obj + 0x68D, 1) == 0


@pytest.mark.parametrize(
    ("kind", "object_class", "expected"),
    [
        (0x20F, 0, True),
        (0x210, 0, True),
        (0x450, 0, True),
        (0x855, 0, True),
        (0x857, 0, True),
        (0x858, 0, False),
        (0, 0x23, True),
        (0, 0x40, True),
        (0, 0, False),
    ],
)
def test_low_health_position_type_and_class_gates(
    kind: int, object_class: int, expected: bool
) -> None:
    r = Rig()
    r.active()
    r.kind(kind)
    r.object_class(object_class)
    r.set_health(bits(0.5))
    r.run_unit()
    assert bool(r.positions) == expected


def test_position_descriptor_sentinels_partial_flag_and_held_virtual_target() -> None:
    r = Rig()
    r.active()
    r.kind(0x20F)
    r.set_health(bits(0.5))
    r.coords(r.obj, bits(2.0), bits(3.0))

    def read(at: int, width: int, value: int) -> None:
        if at == r.obj + 0x180:
            r.mem.write(r.table + 0x900, 8, 0xEE0900)

    def position(args: tuple[int, ...]) -> None:
        assert args[:4] == (r.obj, bits(2.0), bits(3.0), 0)
        assert [r.mem.read(at, 8) for at in args[4:7]] == [r.obj, 0, 0]
        assert r.mem.read(args[7], 4) == bits(1.0)
        descriptor = r.mem.read(args[8], 8)
        assert r.mem.read_bytes(descriptor, 32) == bytes(20) + b"\xff" * 12
        assert r.mem.read_bytes(args[9], 8) == b"\x00" + b"\xa5" * 7

    r.after_read = read
    r.handlers["position_fp_home_calls", POSITION] = position
    r.run_unit()
    assert r.called(POSITION, "position_fp_home_calls")
    assert not r.called(0xEE0900, "position_fp_home_calls")


def test_missing_combat_annotation_refuses_after_current_object_vptr_read() -> None:
    r = Rig()
    r.handlers["calls", COMBAT] = lambda args: None
    with pytest.raises(ValueError, match="Combat AL"):
        r.run_unit()
    assert r.events[-1] == ("r", r.obj, 8, r.table)
    assert not r.called(RATE, "virtual_fp_calls") and not r.live


@pytest.mark.parametrize(
    ("rate", "hp", "maximum", "heal", "hurt", "after"),
    [
        (60.0, 5.0, 10.0, 2.0, None, 7.0),
        (-60.0, 5.0, 10.0, None, 2.0, 3.0),
        (60.0, 9.0, 10.0, 1.0, None, 10.0),
        (-60.0, 1.0, 10.0, None, 1.0, 0.0),
        (60.0, 10.0, 10.0, None, None, 10.0),
    ],
)
def test_periodic_health_remainder_amount_caps_and_real_owned_effects(
    rate: float, hp: float, maximum: float, heal: float | None, hurt: float | None, after: float
) -> None:
    r = Rig()
    r.active()
    r.set_health(bits(hp))
    r.rate, r.maximum = bits(rate), bits(maximum)
    r.mem.write(r.obj + 0x698, 4, bits(2.0))
    r.mem.write(r.obj + 0x66C, 4, 77)
    r.run_unit()
    assert r.called(HEAL, "virtual_fp_apply_calls") == (
        [] if heal is None else [(r.obj, bits(heal))]
    )
    assert r.called(HURT, "virtual_fp_apply_calls") == (
        [] if hurt is None else [(r.obj, bits(hurt))]
    )
    assert r.hp == bits(after)
    assert r.mem.read(r.obj + 0x698, 4) == bits(0.25)
    assert r.mem.read(r.obj + 0x66C, 4) == (0 if after >= maximum else 77)


@pytest.mark.parametrize("rate", [0, 0x80000000, 0x00000001, 0x34000000])
def test_small_rate_skips_periodic_accumulation_after_required_raw_fabs(rate: int) -> None:
    r = Rig()
    r.active()
    r.rate = rate
    r.mem.write(r.obj + 0x698, 4, bits(2.0))
    r.run_unit()
    assert r.mem.read(r.obj + 0x698, 4) == bits(2.0)
    assert len(r.called(ABS, "scalar_fp_calls")) == 1
    assert not r.called(FMOD, "scalar_fp_calls")


def test_unused_rate_annotation_is_not_required_when_postparent_state_skips_hp() -> None:
    r = Rig()
    r.handlers["virtual_fp_calls", RATE] = lambda args: None
    assert r.run_unit() == 0xF3


def test_meter_accumulation_reads_encoded_master_before_store_and_decodes_after_store() -> None:
    r = Rig()
    r.mem.write(r.master + 0x3B8, 4, bits(1.0))
    r.mem.write(r.master + 0x3BC, 4, bits(4.0))
    other_master = r.alloc(0x600)
    r.mem.write(other_master + 0x3B8, 4, bits(100.0))

    def mutate(at: int, width: int, value: int) -> None:
        if at == r.obj + 0x668:
            r.mem.write(
                r.obj + 0x10, 8, (other_master + 0x6A586EB28AC201FC + 0x0CF19788B2554E70) & U64
            )

    r.after_write = mutate
    r.run_unit()
    assert r.mem.read(r.obj + 0x668, 4) == bits(1.0)
    assert r.mem.read(r.ui + 0x1874, 1) == 1


def test_master_percent_gate_uses_positive_signed_low_al_before_meter_accumulation() -> None:
    r = Rig()
    r.mem.write(r.master + 0x3B8, 4, bits(10.0))
    r.mem.write(r.master + 0x3BC, 4, bits(4.0))
    r.mem.write(r.master + 0x3C2, 2, 0xFFFD)
    r.mem.write(r.obj + 0x50C, 4, 1000)
    r.run_unit()
    assert r.mem.read(r.obj + 0x668, 4) == 0
    assert r.called(0x140D6AD50)


def test_trim_clears_held_pointer_before_actual_free_and_final_fallback_runs() -> None:
    r = Rig()
    pointer = r.alloc(8)
    r.mem.write(r.obj + 0x818, 8, pointer)
    r.trim, r.end = 0, 0

    def mutate(at: int, width: int, value: int) -> None:
        if at == r.obj + 0x818:
            assert value == 0

    r.after_write = mutate
    assert r.run_unit() == 0xF3
    assert r.called(0x142D6BAB4) == [(pointer, 8)]
    with pytest.raises(ReplayMemoryError):
        r.mem.read(pointer, 1)
    assert r.called(END_FALLBACK) == [(r.obj,)]


@pytest.mark.parametrize(
    ("hp", "previous", "current", "expected"),
    [(10.0, 5.0, 2.0, 7.0), (2.0, 5.0, 2.0, 1.0), (10.0, 2.0, 5.0, 10.0)],
)
def test_shield_reduction_protected_high_halves_and_one_floor(
    hp: float, previous: float, current: float, expected: float
) -> None:
    r = Rig()
    r.set_health(bits(hp), 0x12345678)
    r.mem.write(r.obj + 0x6C0, 4, bits(previous))
    r.mem.write(r.obj + 0x6C4, 4, bits(current))
    r.run_unit()
    assert health_decoded(r.mem.read(r.obj + 0x130, 8)) == 0x1234567800000000 | bits(expected)
    assert r.mem.read(r.obj + 0x6C0, 4) == bits(current if previous > current else previous)


def test_shield_uses_held_one_and_source_maxss_nan_selection() -> None:
    r = Rig()
    r.set_health(0x7FA12345)
    r.mem.write(r.obj + 0x6C0, 4, bits(5.0))
    r.mem.write(r.obj + 0x6C4, 4, bits(2.0))

    def combat(args: tuple[int, ...]) -> int:
        r.mem.write(0x1436A0294, 4, bits(2.0))
        return 0xF3

    r.handlers["calls", COMBAT] = combat
    r.run_unit()
    assert health_decoded(r.mem.read(r.obj + 0x130, 8)) == bits(1.0)


def test_shield_redecodes_current_local_and_copies_latest_6c4_after_final_health_store() -> None:
    r = Rig()
    r.set_health(bits(10.0))
    r.mem.write(r.obj + 0x6C0, 4, bits(5.0))
    r.mem.write(r.obj + 0x6C4, 4, bits(2.0))
    changed = False

    def mutate(at: int, width: int, value: int) -> None:
        nonlocal changed
        if at == r.frame(0x90) + 0x50 and value == health_encoded(bits(7.0)) and not changed:
            changed = True
            r.mem.write(at, 8, health_encoded(bits(4.0)))
        if at == r.obj + 0x130:
            r.mem.write(r.obj + 0x6C4, 4, bits(1.0))

    r.after_write = mutate
    r.run_unit()
    assert changed and health_decoded(r.mem.read(r.obj + 0x130, 8)) == bits(4.0)
    assert r.mem.read(r.obj + 0x6C0, 4) == bits(1.0)


def test_actual_object_list_unit_combat_action_moving_base_and_clocks_compose() -> None:
    r = Rig()
    r.real_combat, r.real_action, r.real_parent = True, True, True
    r.visible()
    r.mem.write(r.obj + 0x400, 8, r.motion)
    r.mem.write(r.table + 0x30, 8, UNIT)
    header, data = r.alloc(0x20), r.alloc(8)
    r.mem.write(header + 8, 8, data)
    r.mem.write(header + 0x10, 4, 1)
    r.mem.write(data, 8, r.obj)
    objects = bind_replay_object_update(r.context, r.unit, profile=ReplayObjectUpdateProfile(1))
    assert objects.call is not None and objects.call(0x141229A20, (header,), None) is None
    assert r.mem.read(r.obj + 0x198, 4) == 93
    assert r.mem.read(r.obj + 0x350, 4) == bits(3.0)
    assert r.mem.read(r.obj + 0x42A, 2) == 0
    assert r.called(BASE) == [(r.obj,)] and r.called(COMBAT) == [(r.obj,)]
    assert len(r.called(CLOCK)) == 5


@pytest.mark.parametrize("channel", CHANNELS)
def test_missing_category_refuses_at_reached_prefix(channel: str) -> None:
    r = Rig()
    if channel in ("scalar_fp_calls", "imports_fp_calls", "virtual_fp_apply_calls"):
        r.active()
        r.rate = bits(60.0)
        r.mem.write(r.obj + 0x698, 4, bits(2.0))
    elif channel == "position_fp_home_calls":
        r.active()
        r.set_health(bits(0.5))
        r.kind(0x20F)
    elif channel == "graphic_home_calls":
        r.mem.write(r.master + 0x378, 1, 2)
        r.mem.write(r.master + 0x388, 8, r.alloc(8))
        r.mem.write(r.obj + 0x1F0, 8, r.script_obj)
        r.mem.write(r.script_obj + 0x1C0, 1, 1)
        r.mem.write(r.script_obj + 0x44, 4, U32)
    r.unit = r.bind_unit(**{channel: ReplayTaskRebuildCalls(None)})
    expected = dict(
        scalar_fp_calls=ABS,
        imports_fp_calls=IMPORT,
        virtual_fp_calls=RATE,
        virtual_fp_apply_calls=HEAL,
        position_fp_home_calls=POSITION,
        graphic_home_calls=SETUP,
    )
    message = f"reached{expected[channel]:x} is unavailable"
    with pytest.raises(UnresolvedReplayTaskRebuild, match=message):
        r.run_unit()
    assert not r.live


def test_invalid_services_and_mxcsr_refuse_before_effects() -> None:
    r = Rig()
    with pytest.raises(ValueError):
        r.bind_unit(imports_fp_calls=cast(ReplayTaskRebuildCalls, None))
    for mxcsr in (True, 0, 0x1F81, 0x3F80):
        with pytest.raises(ValueError):
            bind_replay_unit_object_update(
                r.context,
                r.ordinary_calls,
                **{name: ReplayTaskRebuildCalls(None) for name in CHANNELS},
                bind_local=r.local,
                profile=r.unit_profile,
                mxcsr=mxcsr,
            )
    assert not r.events
