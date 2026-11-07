"""Offline source controls for the whole Moving/motion/Animated chain.

All external Base, virtual, spatial and diagnostic effects are explicit authored
capabilities. Positive square roots have an independent exact integer oracle.
No native execution, restored recording World or whole-game parity is claimed.
"""

from __future__ import annotations

import math
import random
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import fields, replace
from pathlib import Path
from typing import cast

import pytest

from vantage.replay_memory import ReplayMemory, ReplayMemoryError
from vantage.replay_moving_update import (
    ReplayMovingUpdateProfile,
    bind_replay_moving_update,
)
from vantage.replay_object_update import (
    ReplayObjectUpdateProfile,
    bind_replay_object_update,
)
from vantage.replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
)

MOVING, ANIMATED, MOTION = 0x14120E560, 0x141141E60, 0x141075310
COUNTER, ELAPSED, SQRT, FALLBACK = 0x1410BCE10, 0x141604200, 0x140A82E00, 0x140A80320
BASE, HOST, FREE, NAME, LOG = 0x141249740, 0x140A71140, 0x142D6BAB4, 0x140A4B870, 0x140B6EF80
POSITION, VELOCITY, TRANSLATE, DIRECTION, READY, STATE = (
    0xF00568,
    0xF00628,
    0xF005F8,
    0xF00600,
    0xF00620,
    0xF00850,
)
ANIM20, ANIM40, ANIM10, SETSTATE, RATE = 0xFA0020, 0xFA0040, 0xFA0010, 0xF000A8, 0xF00218
U32, U64 = (1 << 32) - 1, (1 << 64) - 1
MASTER_A, MASTER_B = 0x6A586EB28AC201FC, 0x0CF19788B2554E70
DATA = Path(__file__).resolve().parents[1] / (
    "artifacts/game-internals/2026-10-18-world-envelope/object-virtual-update-source-v1"
)
Handler = Callable[[tuple[int, ...]], int | None]


def sqrt_oracle(word: int) -> int:
    """Nearest-even sqrt from exact integer midpoint comparisons, no FP/LUT."""
    if word in (0, 0x80000000, 0x7F800000):
        return word
    exponent, fraction = word >> 23, word & 0x7FFFFF
    numerator = fraction | 0x800000 if exponent else fraction
    power = exponent - 150 if exponent else -149
    top = (numerator.bit_length() - 1 + power) // 2
    shift = power - 2 * (top - 23)
    numerator <<= max(shift, 0)
    denominator = 1 << max(-shift, 0)
    significand = math.isqrt(numerator // denominator)
    midpoint = denominator * (2 * significand + 1) ** 2
    if 4 * numerator > midpoint or (4 * numerator == midpoint and significand & 1):
        significand += 1
    if significand == 1 << 24:
        significand >>= 1
        top += 1
    return ((top + 127) << 23) | (significand & 0x7FFFFF)


class Rig:
    def __init__(self) -> None:
        self.mem = ReplayMemory()
        self.events: list[tuple[str, int, int, int]] = []
        self.calls: list[tuple[str, int, tuple[int, ...]]] = []
        self.handlers: dict[tuple[str, int], Handler] = {}
        self.live: list[tuple[int, int]] = []
        self.snapshots: list[tuple[int, bytes]] = []
        self.after_read: Callable[[int, int, int], None] | None = None
        self.after_write: Callable[[int, int, int], None] | None = None
        self.subject = self.alloc(0x500)
        self.owner, self.clock = self.alloc(0xA00), self.alloc(0x200)
        self.master = self.alloc(0x100)
        self.vtable, self.animation = self.alloc(0x900), self.alloc(8)
        self.animation_table, self.motion = self.alloc(0x50), self.alloc(24)
        self.resource, self.target, self.name, self.game = (
            self.alloc(0x900),
            self.alloc(0x100),
            self.alloc(8),
            self.alloc(0x600),
        )
        self.mem.map_bytes(0x144353698, self.game.to_bytes(8, "little"))
        self.mem.map_bytes(0x14435A264, (77).to_bytes(4, "little"))
        for file, at in (
            ("sqrt-table-143218010.bin", 0x143218010),
            ("sqrt-normalize-143217ea0.bin", 0x143217EA0),
            ("moving-threshold-1431fe590.bin", 0x1431FE590),
        ):
            self.mem.map_bytes(at, (DATA / file).read_bytes())
        for at, width, value in (
            (self.subject, 8, self.vtable),
            (self.subject + 8, 4, 101),
            (self.subject + 0x10, 8, (self.master + MASTER_A + MASTER_B) & U64),
            (self.subject + 0x18, 8, self.owner),
            (self.subject + 0x20, 8, 0x123400000001),
            (self.subject + 0x28, 8, self.animation),
            (self.subject + 0x198, 4, 100),
            (self.subject + 0x3A0, 4, U32),
            (self.subject + 0x3A4, 4, 99),
            (self.subject + 0x3BC, 4, 0x3F800000),
            (self.subject + 0x3C0, 4, 0x40000000),
            (self.subject + 0x3C4, 4, 0x40400000),
            (self.owner + 8, 8, self.clock),
            (self.owner + 0x98, 8, self.resource),
            (self.clock + 0x7C, 4, 7),
            (self.clock + 0x164, 4, 0x3F000000),
            (self.animation, 8, self.animation_table),
            (self.animation_table + 0x10, 8, ANIM10),
            (self.animation_table + 0x20, 8, ANIM20),
            (self.animation_table + 0x40, 8, ANIM40),
            (self.motion + 8, 4, 0x3F800000),
            (self.motion + 0x14, 4, 0x40000000),
            (self.master + 0x18, 8, ((0xFFF9 + 0x47E37DFF0616CE4F) & U64) ^ 0x349E37847AD69F19),
            (self.name, 8, 0xABCD1234),
        ):
            self.mem.write(at, width, value)
        for offset, target in (
            (0x568, POSITION),
            (0x628, VELOCITY),
            (0x5F8, TRANSLATE),
            (0x600, DIRECTION),
            (0x620, READY),
            (0x850, STATE),
            (0xA8, SETSTATE),
            (0x218, RATE),
        ):
            self.mem.write(self.vtable + offset, 8, target)
        self.limit(0x40000000)
        self.context = ReplayTaskRebuildStorage(self.subject, self.read, self.write)
        self.ordinary_calls = ReplayTaskRebuildCalls(self.ordinary)
        self.runtime = self.mem.runtime_calls(self.ordinary_calls)
        self.profile = ReplayMovingUpdateProfile(
            bytes([0xA1]) * 0x40, bytes([0xA2]) * 0x48, bytes([0xA3]) * 0xF0
        )
        self.bound = self.bind()

    def alloc(self, size: int) -> int:
        at = self.mem.allocate(size)
        self.mem.fill(at, 0, size)
        return at

    def limit(self, word: int) -> None:
        encoded = ((word ^ 0xA9834B738A7DD167) + 0x042AC42976FCCEF5) & U64
        self.mem.write(self.resource + 0x800, 8, encoded ^ 0xC22D6B496D833977 ^ 0x6AE24D3352F04511)

    def read(self, at: int, width: int) -> int:
        value = self.mem.read(at, width)
        self.events.append(("r", at, width, value))
        if self.after_read:
            self.after_read(at, width, value)
        return value

    def write(self, at: int, width: int, value: int) -> None:
        self.mem.write(at, width, value)
        self.events.append(("w", at, width, value))
        if self.after_write:
            self.after_write(at, width, value)

    @contextmanager
    def local(self, view: memoryview) -> Iterator[int]:
        with self.mem.bind_local(view) as at:
            self.live.append((len(view), at))
            try:
                yield at
            finally:
                self.snapshots.append((len(view), bytes(view)))
                self.live.pop()

    def frame(self, size: int) -> int:
        return next(at for length, at in reversed(self.live) if length == size)

    def bind(self, **overrides: ReplayTaskRebuildCalls) -> ReplayTaskRebuildCalls:
        channels = {
            name: ReplayTaskRebuildCalls(self.channel(name))
            for name in (
                "virtual_calls",
                "scalar_fp_calls",
                "motion_fp_calls",
                "virtual_fp_calls",
                "virtual_fp_home_calls",
                "logger_home_calls",
            )
        }
        channels.update(overrides)
        return bind_replay_moving_update(
            self.context,
            self.ordinary_calls,
            **channels,
            bind_local=self.local,
            profile=self.profile,
            mxcsr=0x1F80,
        )

    def record(self, channel: str, target: int, args: tuple[int, ...]) -> Handler | None:
        self.calls.append((channel, target, args))
        self.events.append(("call", target, 0, len(self.calls)))
        return self.handlers.get((channel, target))

    def channel(
        self, channel: str
    ) -> Callable[[int, tuple[int, ...], memoryview | None], int | None]:
        def dispatch(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
            assert data is None
            if handler := self.record(channel, target, args):
                return handler(args)
            if channel == "scalar_fp_calls":
                if target in (SQRT, ELAPSED):
                    assert self.bound.call is not None
                    return self.bound.call(target, args, None)
                if target in (RATE, 0x14124E840):
                    return 0x3F800000
            if channel == "motion_fp_calls" and target == MOTION:
                assert self.bound.call is not None
                return self.bound.call(target, args, None)
            if channel == "virtual_calls":
                if target == POSITION:
                    for i in range(3):
                        self.mem.write(args[1] + i * 4, 4, 0x100 + i)
                    return args[1]
                if target in (READY, STATE, ANIM20, ANIM40):
                    return 0
                if target in (DIRECTION, SETSTATE):
                    return None
            if channel == "virtual_fp_home_calls":
                if target == VELOCITY:
                    return 0x40400000
                if target == 0x140B2D140:
                    return None
            if channel == "virtual_fp_calls" and target in (ANIM10, TRANSLATE, 0x140B2D060):
                return None
            if channel == "logger_home_calls" and target == LOG:
                return None
            raise UnresolvedReplayTaskRebuild(f"authored {channel} missing{target:x}")

        return dispatch

    def ordinary(self, target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        assert data is None
        if handler := self.record("calls", target, args):
            return handler(args)
        if target == FREE:
            assert self.runtime.call is not None
            return self.runtime.call(target, args, None)
        if target in (MOVING, ANIMATED, MOTION, COUNTER, ELAPSED, SQRT):
            assert self.bound.call is not None
            return self.bound.call(target, args, None)
        if target == BASE:
            return 0
        if target == NAME:
            return self.name
        if target == HOST:
            return 100000
        if target == 0x140D6ACC0:
            return self.clock
        if target == 0x141617DB0:
            return self.target
        if target == 0x140B2CFF0:
            return 1
        if target == 0x140903E40:
            return 0
        if target in (0x141248570, 0x141247F00, 0x141265AC0, 0x140B2CFC0):
            return None
        raise UnresolvedReplayTaskRebuild(f"authored child missing{target:x}")

    def run(self, target: int, *args: int) -> int | None:
        assert self.bound.call is not None
        return self.bound.call(target, args, None)

    def called(self, target: int, channel: str = "calls") -> list[tuple[int, ...]]:
        return [args for name, at, args in self.calls if name == channel and at == target]


@pytest.mark.parametrize("field", [f.name for f in fields(ReplayMovingUpdateProfile)])
def test_profile_has_exact_immutable_explicit_prefixes(field: str) -> None:
    r = Rig()
    for value in (b"", bytearray(getattr(r.profile, field))):
        with pytest.raises(ValueError):
            replace(r.profile, **{field: value})


@pytest.mark.parametrize(
    ("target", "arity"),
    [(MOVING, 1), (ANIMATED, 1), (MOTION, 3), (COUNTER, 0), (ELAPSED, 1), (SQRT, 1)],
)
def test_addressed_arity_and_payload_refuse_before_effects(target: int, arity: int) -> None:
    r = Rig()
    assert r.bound.call is not None
    for args, data in (((0,) * (arity + 1), None), ((0,) * arity, memoryview(b"payload"))):
        with pytest.raises(ValueError):
            r.bound.call(target, args, data)
    assert not r.events


def test_known_scalar_profiles_refuse_bad_words_and_unknown_calls_preserve_identity() -> None:
    r = Rig()
    for target, args in ((SQRT, (True,)), (SQRT, (1 << 32,)), (MOTION, (1, 0, 1 << 32))):
        with pytest.raises(ValueError):
            r.run(target, *args)
    args, data, result = (-5, 99), memoryview(b"raw"), 123456789012345

    def unknown(target: int, given: tuple[int, ...], payload: memoryview | None) -> int:
        assert target == 42 and given is args and payload is data
        return result

    r.ordinary_calls = ReplayTaskRebuildCalls(unknown)
    bound = r.bind()
    assert bound.call is not None and bound.call(42, args, data) is result
    assert not r.events


def test_positive_sqrt_matches_independent_integer_oracle_across_table_and_exponents() -> None:
    r = Rig()
    words = [
        0,
        0x80000000,
        1,
        2,
        3,
        0x7FFFFF,
        0x800000,
        0x800001,
        0x7F7FFFFF,
        0x7F800000,
        0x3F800000,
        0x40000000,
        0x40800000,
    ]
    for exponent in (1, 2, 126, 127, 128, 129, 253, 254):
        for bucket in range(64):
            for low in (0, 1, 0x10000, 0x1FFFF):
                words.append((exponent << 23) | (bucket << 17) | low)
    rng = random.Random(54800)
    words.extend(rng.randrange(1, 0x7F800000) for _ in range(1024))
    for word in words:
        assert r.run(SQRT, word) == sqrt_oracle(word), f"{word:08x}"
    assert not r.calls and not r.snapshots


def test_sqrt_uses_current_table_word_and_requires_real_fallback() -> None:
    r = Rig()
    r.mem.write(0x143218010, 2, 0)
    assert r.run(SQRT, 0x40000000) == 0x3F800000
    assert r.events[-1] == ("r", 0x143218010, 2, 0)
    for word in (0xBF800000, 0xFF800000, 0x7FC12345, 0x7F812345, 0xFFC12345):
        r.handlers["scalar_fp_calls", FALLBACK] = lambda args: args[0] ^ 0x00400000
        assert r.run(SQRT, word) == word ^ 0x00400000
        assert r.called(FALLBACK, "scalar_fp_calls")[-1] == (word,)
    r.bound = r.bind(scalar_fp_calls=ReplayTaskRebuildCalls(None))
    with pytest.raises(UnresolvedReplayTaskRebuild, match=f"{FALLBACK:x}"):
        r.run(SQRT, 0xBF800000)


def test_leaf_counter_and_elapsed_are_exact_and_motion_null_does_not_bind() -> None:
    r = Rig()
    assert r.run(COUNTER) == 5000
    assert r.run(ELAPSED, r.clock) == 0x3F000000
    assert r.run(MOTION, 0, 0, 0x7F800001) == 0
    assert not r.snapshots and not r.calls


def test_motion_publishes_velocity_then_typed_diagnostic_and_current_translation() -> None:
    r = Rig()

    def logger(args: tuple[int, ...]) -> None:
        assert args[:4] == (0x17, 1, 77, 101)
        home = args[4]
        assert r.mem.read(home, 8) == 0x14329D690
        assert r.mem.read(home + 8, 8) == 0xABCD1234
        assert r.mem.read_bytes(home + 0x10, 8) == b"\xf9\xff\xff\xff" + bytes([0xA3]) * 4
        assert r.mem.read_bytes(home + 0x18, 8) == (101).to_bytes(4, "little") + bytes([0xA3]) * 4
        assert [r.mem.read(home + i, 8) for i in (0x20, 0x28, 0x30)] == [
            0x3FE0000000000000,
            0x4000000000000000,
            0x4008000000000000,
        ]
        assert r.mem.read(r.motion + 8, 4) == 0x40400000
        r.mem.write(r.motion + 8, 4, 0x40800000)

    r.handlers["logger_home_calls", LOG] = logger
    assert r.run(MOTION, r.motion, r.subject, 0x3F000000) == 1
    assert r.called(TRANSLATE, "virtual_fp_calls") == [(r.subject, 0x40000000)]
    assert len(r.called(POSITION, "virtual_calls")) == 4
    assert not r.live


def test_motion_holds_first_vptr_and_prior_id_but_uses_later_positions_and_id() -> None:
    r = Rig()
    other = r.alloc(0x900)
    r.mem.write(other + 0x568, 8, 0xEE0568)
    r.mem.write(other + 0x5F8, 8, 0xEE05F8)

    def position(args: tuple[int, ...]) -> int:
        r.mem.write(r.subject, 8, other)
        return args[1] + 4

    def name(args: tuple[int, ...]) -> int:
        r.mem.write(r.subject + 8, 4, 202)
        return r.name

    def logger(args: tuple[int, ...]) -> None:
        assert args[:4] == (0x17, 1, 77, 202)
        assert r.mem.read(args[4] + 0x18, 4) == 101

    def velocity(args: tuple[int, ...]) -> int:
        assert r.mem.read(args[4], 8) == r.frame(0xF0) + 0x64
        return 0x40400000

    r.handlers["virtual_calls", POSITION] = position
    r.handlers["calls", NAME] = name
    r.handlers["virtual_fp_home_calls", VELOCITY] = velocity
    r.handlers["logger_home_calls", LOG] = logger
    r.handlers["virtual_calls", 0xEE0568] = lambda args: None
    r.handlers["virtual_fp_calls", 0xEE05F8] = lambda args: None
    assert r.run(MOTION, r.motion, r.subject, 0x3F000000) == 1
    assert r.called(VELOCITY, "virtual_fp_home_calls")
    assert len(r.called(0xEE0568, "virtual_calls")) == 3
    assert r.called(0xEE05F8, "virtual_fp_calls")


def test_missing_motion_logger_preserves_velocity_and_refuses_before_translation() -> None:
    r = Rig()
    r.bound = r.bind(logger_home_calls=ReplayTaskRebuildCalls(None))
    with pytest.raises(UnresolvedReplayTaskRebuild, match=f"{LOG:x}"):
        r.run(MOTION, r.motion, r.subject, 0x3F000000)
    assert r.mem.read(r.motion + 8, 4) == 0x40400000
    assert not r.called(TRANSLATE, "virtual_fp_calls") and not r.live


@pytest.mark.parametrize(
    ("timer", "decrement", "expected"),
    [(0, 7, 0), (100, 7, 93), (5000, U32, 0), (5001, 7, 5001), (U32, 7, U32)],
)
def test_moving_timer_signed64_saturation_and_upper_gate(
    timer: int, decrement: int, expected: int
) -> None:
    r = Rig()
    r.mem.write(r.subject + 0x198, 4, timer)
    r.mem.write(r.clock + 0x7C, 4, decrement)
    assert r.run(MOVING, r.subject) == 0
    assert r.mem.read(r.subject + 0x198, 4) == expected
    assert not r.called(ELAPSED, "scalar_fp_calls")


def test_moving_composes_actual_motion_sqrt_and_animated_with_required_base() -> None:
    r = Rig()
    r.mem.write(r.subject + 0x400, 8, r.motion)
    r.mem.write(r.subject + 0x3B9, 1, 1)
    r.mem.write(r.subject + 0x410, 4, U32)
    r.handlers["calls", BASE] = lambda args: 0x10000007F
    assert r.run(MOVING, r.subject) == 127
    assert r.mem.read(r.motion + 8, 4) == 0x40400000
    assert r.mem.read(r.subject + 0x350, 4) == 0x40400000
    assert len(r.called(SQRT, "scalar_fp_calls")) == 2
    assert r.mem.read(r.subject + 0x410, 4) == 0
    assert r.mem.read(r.subject + 0x3B9, 1) == 0
    assert r.called(DIRECTION, "virtual_calls") == [(r.subject, r.subject + 0x3E0)]
    assert r.called(BASE) == [(r.subject,)]


def test_moving_repeats_magnitude_from_current_motion_pointer() -> None:
    r = Rig()
    other = r.alloc(24)
    r.mem.write(other, 4, 0x40800000)
    r.mem.write(r.subject + 0x400, 8, r.motion)

    def sqrt(args: tuple[int, ...]) -> int:
        result = r.run(SQRT, *args)
        assert result is not None
        if len(r.called(SQRT, "scalar_fp_calls")) == 1:
            r.mem.write(r.subject + 0x400, 8, other)
        return result

    r.handlers["scalar_fp_calls", SQRT] = sqrt
    r.run(MOVING, r.subject)
    assert r.mem.read(r.subject + 0x350, 4) == 0x40800000
    assert r.mem.read(r.motion + 8, 4) == 0x40400000
    assert r.called(MOTION, "motion_fp_calls") == [(r.motion, r.subject, 0x3F000000)]


@pytest.mark.parametrize(
    ("motion_present", "flag", "expected"),
    [(False, 1, 9), (True, 0, 0), (True, 2, 0), (True, 1, 10)],
)
def test_direction_counter_requires_motion_and_exact_one(
    motion_present: bool, flag: int, expected: int
) -> None:
    r = Rig()
    r.mem.write(r.subject + 0x400, 8, r.motion if motion_present else 0)
    r.mem.write(r.subject + 0x3B9, 1, flag)
    r.mem.write(r.subject + 0x410, 4, 9)
    r.run(MOVING, r.subject)
    assert r.mem.read(r.subject + 0x410, 4) == expected


@pytest.mark.parametrize(
    ("pointer", "end1", "begin1", "end2", "begin2", "refresh"),
    [
        (0, 7, 0, 7, 0, False),
        (1, 0, 0, 0, 0, True),
        (0, 8, 0, 0, 0, True),
        (0, 0, 0, 8, 0, True),
        (0, 0, 1, 0, 0, True),
    ],
)
def test_refresh_unsigned_ranges_and_exact_coordinate_order(
    pointer: int, end1: int, begin1: int, end2: int, begin2: int, refresh: bool
) -> None:
    r = Rig()
    for offset, value in (
        (0x58, pointer),
        (0x68, end1),
        (0x60, begin1),
        (0x80, end2),
        (0x78, begin2),
    ):
        r.mem.write(r.subject + offset, 8, value)

    def update(args: tuple[int, ...]) -> None:
        assert args[0] == r.subject
        assert [r.mem.read(args[1] + i * 4, 4) for i in range(3)] == [
            0x3F800000,
            0x40400000,
            0x40000000,
        ]

    r.handlers["calls", 0x141248570] = update
    r.run(MOVING, r.subject)
    assert bool(r.called(0x141248570)) == refresh


@pytest.mark.parametrize(("elapsed", "free"), [(29999, False), (30000, True), (U32, True)])
def test_buffer_timeout_uses_actual_owned_free_and_common_clear(elapsed: int, free: bool) -> None:
    r = Rig()
    buffer = r.alloc(8)
    r.mem.write(r.subject + 0x3B0, 8, buffer)
    r.mem.write(r.subject + 0x3A8, 4, (100000 - elapsed) & U32)
    r.handlers["calls", 0x140B2CFF0] = lambda args: 0x100
    r.run(MOVING, r.subject)
    assert r.mem.read(r.subject + 0x3B0, 8) == (0 if free else buffer)
    assert r.called(FREE) == ([(buffer, 8)] if free else [])
    if free:
        with pytest.raises(ReplayMemoryError):
            r.mem.read(buffer, 1)


@pytest.mark.parametrize("speed", [0xBF800000, 0x7FC12345])
def test_buffer_negative_or_unordered_speed_skips_vector_update(speed: int) -> None:
    r = Rig()
    r.mem.write(r.subject + 0x3B0, 8, r.alloc(8))
    r.mem.write(r.subject + 0x350, 4, speed)
    r.run(MOVING, r.subject)
    assert not r.called(0x140B2D060, "virtual_fp_calls")


def test_buffer_holds_receiver_before_rate_and_preserves_high_home_bytes() -> None:
    r = Rig()
    buffer, other = r.alloc(8), r.alloc(8)
    r.mem.write(r.subject + 0x3B0, 8, buffer)
    r.mem.write(r.subject + 0x3B8, 1, 1)

    def rate(args: tuple[int, ...]) -> int:
        r.mem.write(r.subject + 0x3B0, 8, other)
        return 0x3F000000

    def update(args: tuple[int, ...]) -> None:
        assert args[:4] == (buffer, 0x3F800000, 0x40400000, 0x40000000)
        assert r.mem.read_bytes(args[4], 8) == bytes.fromhex("0000003fa1a1a1a1")

    r.handlers["scalar_fp_calls", RATE] = rate
    r.handlers["virtual_fp_home_calls", 0x140B2D140] = update
    r.run(MOVING, r.subject)


@pytest.mark.parametrize(
    ("distance", "target", "cleared"),
    [
        (0x40800000, True, False),
        (0x40800001, True, True),
        (0x7FC12345, True, False),
        (0x3F800000, False, True),
    ],
)
def test_target_squared_limit_unordered_and_null(
    distance: int, target: bool, cleared: bool
) -> None:
    r = Rig()
    r.mem.write(r.subject + 0x3A0, 4, 123)
    r.handlers["calls", 0x141617DB0] = lambda args: r.target if target else 0
    r.handlers["scalar_fp_calls", 0x14124E840] = lambda args: distance
    r.run(MOVING, r.subject)
    assert r.mem.read(r.subject + 0x3A0, 4) == (U32 if cleared else 123)
    assert r.mem.read(r.subject + 0x3A4, 4) == (0 if cleared else 99)


def test_target_uses_current_decoded_home_after_distance_and_current_id_after_token() -> None:
    r = Rig()
    r.mem.write(r.subject + 0x3A0, 4, 123)

    def token(args: tuple[int, ...]) -> int:
        r.mem.write(r.subject + 0x3A0, 4, 456)
        return r.clock

    def distance(args: tuple[int, ...]) -> int:
        r.mem.write(r.frame(0x40) + 0x30, 4, 0x3F800000)
        return 0x40000000

    r.handlers["calls", 0x140D6ACC0] = token
    r.handlers["scalar_fp_calls", 0x14124E840] = distance
    r.run(MOVING, r.subject)
    assert r.called(0x141617DB0) == [(r.clock, 456)]
    assert r.mem.read(r.subject + 0x3A0, 4) == U32


@pytest.mark.parametrize(
    ("state", "kind", "cleanup"), [(4, 0x4F, True), (4, 0x50, False), (0, 0, False)]
)
def test_animated_state_four_and_held_base_al(state: int, kind: int, cleanup: bool) -> None:
    r = Rig()
    r.mem.write(r.subject + 0x188, 1, state)
    r.mem.write(r.subject + 0xF, 1, kind)
    r.mem.write(r.subject + 0x350, 4, 0x3F800000)
    r.handlers["calls", BASE] = lambda args: 0x1000000FE
    assert r.run(ANIMATED, r.subject) == 254
    assert r.mem.read(r.subject + 0x188, 1) == (5 if state == 4 else state)
    assert r.mem.read(r.subject + 0x350, 4) == (0 if state == 4 else 0x3F800000)
    assert bool(r.called(0x141265AC0)) == cleanup


@pytest.mark.parametrize("selected", [0, 0x100000000])
def test_animated_state_three_uses_raw_pointer_and_late_state_slot(selected: int) -> None:
    r = Rig()
    r.mem.write(r.subject + 0x188, 1, 3)

    def choose(args: tuple[int, ...]) -> int:
        r.mem.write(r.vtable + 0xA8, 8, 0xEE00A8)
        return selected

    r.handlers["virtual_calls", STATE] = choose
    r.handlers["virtual_calls", 0xEE00A8] = lambda args: None
    r.run(ANIMATED, r.subject)
    assert r.called(0xEE00A8, "virtual_calls") == [(r.subject, 4 if selected else 5)]


@pytest.mark.parametrize(
    ("random_value", "reset"), [(0x3FFF, False), (0x4000, True), (0xFFFFFFFF, False)]
)
def test_animated_rng_signed_gate_and_live_reset_flag(random_value: int, reset: bool) -> None:
    r = Rig()
    current = r.mem.read(r.subject + 0x20, 8)
    r.mem.write(r.master + 0x48, 8, current)
    r.handlers["virtual_calls", ANIM40] = lambda args: 0x101

    def draw(args: tuple[int, ...]) -> int:
        r.mem.write(r.subject + 0x2CC, 4, 1)
        return random_value

    r.handlers["calls", 0x140903E40] = draw
    assert r.run(ANIMATED, r.subject) == 0
    assert r.called(0x141247F00) == ([(r.subject, 0, 0x7FFF)] if reset else [])
    assert r.called(0x140903E40) == [(0x144352FD0, 0x14329E98C, 0xB0)]


def test_selection_holds_old_identity_before_home_writes_then_passes_current_identity() -> None:
    r = Rig()
    original = r.mem.read(r.subject + 0x20, 8)
    r.mem.write(r.master + 0x48, 8, original)
    r.handlers["virtual_calls", READY] = lambda args: 1
    r.handlers["virtual_calls", ANIM40] = lambda args: 1

    def mutate(at: int, width: int, value: int) -> None:
        if r.live and at == r.frame(0x40) + 0x30 and width == 8:
            r.mem.write(r.subject + 0x20, 8, 0xFEED)

    r.after_write = mutate
    r.run(MOVING, r.subject)
    assert r.called(ANIM40, "virtual_calls") == [(r.animation, 0xFEED)]
    assert r.called(0x141247F00) == [(r.subject, 0, 0x7FFF)]


def test_animated_third_master_decode_samples_current_pointer() -> None:
    r = Rig()
    other = r.alloc(0x100)
    original = r.mem.read(r.subject + 0x20, 8)
    r.mem.write(r.master + 0x48, 8, 7)
    r.mem.write(other + 0x48, 8, original)
    r.handlers["virtual_calls", ANIM40] = lambda args: 1

    def mutate(at: int, width: int, value: int) -> None:
        if at == r.master + 0x40:
            r.mem.write(r.subject + 0x10, 8, (other + MASTER_A + MASTER_B) & U64)

    r.after_read = mutate
    r.run(ANIMATED, r.subject)
    assert r.called(0x140903E40)
    assert len([e for e in r.events if e[:3] == ("r", r.subject + 0x10, 8)]) == 3


@pytest.mark.parametrize(
    "channel",
    [
        "virtual_calls",
        "scalar_fp_calls",
        "motion_fp_calls",
        "virtual_fp_calls",
        "virtual_fp_home_calls",
        "logger_home_calls",
    ],
)
def test_missing_reached_category_preserves_prefix_and_does_not_fall_back(channel: str) -> None:
    r = Rig()
    r.mem.write(r.subject + 0x400, 8, r.motion)
    r.bound = r.bind(**{channel: ReplayTaskRebuildCalls(None)})
    with pytest.raises(UnresolvedReplayTaskRebuild):
        r.run(MOVING, r.subject)
    assert r.mem.read(r.subject + 0x198, 4) == 93
    assert not r.live


def test_object_list_dispatcher_reaches_actual_moving_motion_and_animated_chain() -> None:
    r = Rig()
    r.mem.write(r.subject + 0x400, 8, r.motion)
    r.mem.write(r.vtable + 0x30, 8, MOVING)
    header, data = r.alloc(0x20), r.alloc(8)
    r.mem.write(header + 8, 8, data)
    r.mem.write(header + 0x10, 4, 1)
    r.mem.write(data, 8, r.subject)
    objects = bind_replay_object_update(r.context, r.bound, profile=ReplayObjectUpdateProfile(1))
    assert objects.call is not None and objects.call(0x141229A20, (header,), None) is None
    assert r.mem.read(r.subject + 0x198, 4) == 93
    assert r.mem.read(r.subject + 0x350, 4) == 0x40400000
    assert r.mem.read(r.motion + 8, 4) == 0x40400000
    assert r.called(BASE) == [(r.subject,)]
    assert r.called(TRANSLATE, "virtual_fp_calls") == [(r.subject, 0x3FC00000)]


def test_invalid_capabilities_and_mxcsr_refuse_before_effects() -> None:
    r = Rig()
    with pytest.raises(ValueError):
        r.bind(virtual_calls=cast(ReplayTaskRebuildCalls, None))
    for mxcsr in (0, 0x1F81, 0x3F80, True):
        with pytest.raises(ValueError):
            bind_replay_moving_update(
                r.context,
                r.ordinary_calls,
                **{
                    name: ReplayTaskRebuildCalls(None)
                    for name in (
                        "virtual_calls",
                        "scalar_fp_calls",
                        "motion_fp_calls",
                        "virtual_fp_calls",
                        "virtual_fp_home_calls",
                        "logger_home_calls",
                    )
                },
                bind_local=r.local,
                profile=r.profile,
                mxcsr=mxcsr,
            )
    assert not r.events
