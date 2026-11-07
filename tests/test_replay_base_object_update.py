"""Source-driven Base update controls with owned storage and real getters.

Virtual/graphic/script effects remain explicit authored capabilities. Composite
checks execute the real Moving/motion/Animated/Base callers, not a recording.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from typing import cast

import pytest

from vantage.replay_base_object_update import (
    ReplayBaseObjectUpdateProfile,
    bind_replay_base_object_update,
)
from vantage.replay_civilization_providers import bind_replay_civilization_providers
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
from vantage.replay_unit_ai_map import ReplayUnitAIMapAtomics
from vantage.replay_unit_ai_variants import (
    ReplayUnitAIVariantScratch,
    bind_replay_unit_ai_variants,
)

ENTRY, NAME, LOG, CAST = 0x141249740, 0x140A4B870, 0x14101ADB0, 0x142D6E3D5
GAME, OWNER, MODE, FREE, MALLOC, ZERO = (
    0x140D6ACC0,
    0x14172AC80,
    0x140FA36A0,
    0x142D6BAB4,
    0x142D6BA78,
    0x142D6E3B7,
)
SELECT, STATE, OTHER, DELETE, FRAME, FACTORY, CLONE = (
    0xF00070,
    0xF000A8,
    0xF00170,
    0xF00178,
    0xFA0008,
    0xFB0040,
    0xFC0048,
)
GET850, GET858, GET848, CHECK, REG_A, REG_B = (
    0xF00850,
    0xF00858,
    0xF00848,
    0xF001C0,
    0xFD02E0,
    0xFD02D8,
)
SCRIPT, RNG = 0x140F49E90, 0x140903E40
MOVING, MOTION, ANIMATED, SQRT, ELAPSED = (
    0x14120E560,
    0x141075310,
    0x141141E60,
    0x140A82E00,
    0x141604200,
)
POSITION, VELOCITY, TRANSLATE, ANIM10 = 0xF00568, 0xF00628, 0xF005F8, 0xFA0010
U32, U64 = (1 << 32) - 1, (1 << 64) - 1
MA, MB, TX, TS, HX, HS = (
    0x6A586EB28AC201FC,
    0x0CF19788B2554E70,
    0x349E37847AD69F19,
    0x47E37DFF0616CE4F,
    0x0F2A55F7A61DD00E,
    0x147B5E081EC087D9,
)
DATA = Path(__file__).resolve().parents[1] / "artifacts/game-internals/2026-10-18-world-envelope"
Handler = Callable[[tuple[int, ...]], int | None]


class Rig:
    def __init__(self) -> None:
        self.mem = ReplayMemory()
        self.events: list[tuple[str, int, int, int]] = []
        self.calls: list[tuple[str, int, tuple[int, ...]]] = []
        self.handlers: dict[tuple[str, int], Handler] = {}
        self.live: list[tuple[int, int]] = []
        self.snapshots: list[bytes] = []
        self.sizes: dict[int, int] = {}
        self.after_read: Callable[[int, int, int], None] | None = None
        self.after_write: Callable[[int, int, int], None] | None = None
        self.obj, self.owner, self.world = self.alloc(0xA00), self.alloc(0x700), self.alloc(0x300)
        self.master, self.clone = self.alloc(0x600), self.alloc(0x600)
        self.table, self.master_table, self.owner_table = (
            self.alloc(0x900),
            self.alloc(0x50),
            self.alloc(0x300),
        )
        self.animation, self.anim_table = self.alloc(8), self.alloc(0x50)
        self.graphic, self.graphic_table = self.alloc(0x80), self.alloc(0x50)
        self.graphics, self.factory_table, self.palette = (
            self.alloc(0x1200),
            self.alloc(0x50),
            self.alloc(0x100),
        )
        self.factory, self.created, self.other = self.alloc(8), self.alloc(0xA00), self.alloc(0xA00)
        self.game, self.name = self.alloc(0x700), self.alloc(8)
        self.gfx_buffer = self.alloc(0x18100)
        self.replacement = self.alloc(0x30)
        self.motion = self.alloc(24)
        for at, size in ((0x144353698, 8), (0x144355050, 0x20), (0x14435A264, 4)):
            self.mem.map_bytes(at, bytes(size))
        base = DATA / "base-object-update-source-v1"
        moving = DATA / "object-virtual-update-source-v1"
        for path, at in (
            (base / "state-jump-table-14124aa10.bin", 0x14124AA10),
            (base / "threshold-1436a0294.bin", 0x1436A0294),
            (moving / "sqrt-table-143218010.bin", 0x143218010),
            (moving / "sqrt-normalize-143217ea0.bin", 0x143217EA0),
            (moving / "moving-threshold-1431fe590.bin", 0x1431FE590),
        ):
            self.mem.map_bytes(at, path.read_bytes())
        for at, width, value in (
            (self.obj, 8, self.table),
            (self.other, 8, self.table),
            (self.obj + 8, 4, 123),
            (self.obj + 0x18, 8, self.owner),
            (self.obj + 0x20, 8, self.graphic),
            (self.obj + 0x28, 8, self.animation),
            (self.obj + 0x188, 1, 1),
            (self.obj + 0x160, 2, 0),
            (self.obj + 0x168, 4, 0x3F800000),
            (self.obj + 0x198, 4, 100),
            (self.obj + 0x290, 4, U32),
            (self.obj + 0x3A0, 4, U32),
            (self.owner, 8, self.owner_table),
            (self.owner + 8, 8, self.world),
            (self.owner + 0x10, 4, 3),
            (self.owner + 0x28, 8, self.graphics),
            (self.owner + 0x648, 4, 1),
            (self.master, 8, self.master_table),
            (self.master + 0x86, 2, 0xFFFF),
            (self.master + 0xC0, 4, 0x40000000),
            (self.master_table + 0x48, 8, CLONE),
            (self.animation, 8, self.anim_table),
            (self.anim_table + 8, 8, FRAME),
            (self.anim_table + 0x10, 8, ANIM10),
            (self.world + 0x7C, 4, 7),
            (self.world + 0x164, 4, 0x3E800000),
            (self.world + 0xC0, 8, self.gfx_buffer),
            (self.world + 0xC8, 8, 4),
            (self.world + 0xD0, 8, 2),
            (self.world + 0x130, 8, 0xC0FFEE),
            (self.gfx_buffer + 0x180B0, 8, self.replacement),
            (self.game + 0x5C0, 8, self.world),
            (self.game + 0x680, 4, 2),
            (0x144353698, 8, self.game),
            (0x144355068, 8, 0xABC0),
            (self.name, 8, 0xABCDEF01),
            (self.graphic, 8, self.graphic_table),
            (self.graphic + 0xA, 2, 2),
            (self.factory, 8, self.factory_table),
            (self.factory_table + 0x40, 8, FACTORY),
            (self.graphics + 0x1108, 8, self.palette),
            (self.palette + 0x74, 1, 10),
            (self.motion + 8, 4, 0x3F800000),
            (self.motion + 0x14, 4, 0x40000000),
        ):
            self.mem.write(at, width, value)
        self.set_master(self.master)
        self.set_kind(self.master, 0)
        self.set_hp(0x3F800000)
        self.coords(0x112233443F800000, 0x2233445540000000, 0x3344556640400000)
        for slot, target in (
            (0x70, SELECT),
            (0xA8, STATE),
            (0x170, OTHER),
            (0x178, DELETE),
            (0x1C0, CHECK),
            (0x4F8, 0xF004F8),
            (0x850, GET850),
            (0x858, GET858),
            (0x848, GET848),
            (0x620, 0xF00620),
            (0x568, POSITION),
            (0x628, VELOCITY),
            (0x5F8, TRANSLATE),
            (0x600, 0xF00600),
        ):
            self.mem.write(self.table + slot, 8, target)
        self.mem.write(self.owner_table + 0x2E0, 8, REG_A)
        self.mem.write(self.owner_table + 0x2D8, 8, REG_B)
        self.context = ReplayTaskRebuildStorage(self.obj, self.read, self.write)
        self.ordinary_calls = ReplayTaskRebuildCalls(self.ordinary)
        self.runtime = self.mem.runtime_calls(self.ordinary_calls)
        self.mode = bind_replay_civilization_providers(self.context, self.ordinary_calls)
        self.variants = bind_replay_unit_ai_variants(
            self.context,
            self.ordinary_calls,
            atomics=ReplayUnitAIMapAtomics(self.mem.compare_exchange_u32, self.mem.fetch_add_u32),
            bind_local=self.local,
            scratch=ReplayUnitAIVariantScratch(bytes(0x140), bytes(0xC0), bytes(0xD0)),
        )
        self.profile = ReplayBaseObjectUpdateProfile(bytes([0xA5]) * 0xC0)
        self.bound = self.bind()
        self.moving = bind_replay_moving_update(
            self.context,
            self.ordinary_calls,
            virtual_calls=ReplayTaskRebuildCalls(self.channel("virtual_calls")),
            scalar_fp_calls=ReplayTaskRebuildCalls(self.channel("scalar_fp_calls")),
            motion_fp_calls=ReplayTaskRebuildCalls(self.channel("motion_fp_calls")),
            virtual_fp_calls=ReplayTaskRebuildCalls(self.channel("virtual_fp_calls")),
            virtual_fp_home_calls=ReplayTaskRebuildCalls(self.channel("virtual_fp_home_calls")),
            logger_home_calls=ReplayTaskRebuildCalls(self.channel("motion_logger")),
            bind_local=self.local,
            mxcsr=0x1F80,
            profile=ReplayMovingUpdateProfile(bytes(0x40), bytes(0x48), bytes(0xF0)),
        )

    def alloc(self, size: int) -> int:
        at = self.mem.allocate(size)
        self.mem.fill(at, 0, size)
        self.sizes[at] = size
        return at

    def set_master(self, at: int) -> None:
        self.mem.write(self.obj + 0x10, 8, (at + MA + MB) & U64)

    def set_kind(self, at: int, kind: int) -> None:
        self.mem.write(at + 0x18, 8, ((kind + TS) & U64) ^ TX)

    def set_hp(self, word: int) -> None:
        self.mem.write(self.obj + 0x130, 8, ((word + HS) & U64) ^ HX)

    def coords(self, x: int, y: int, z: int) -> None:
        self.mem.write(self.obj + 0x170, 8, (x - 0x4C3FBA69E4EA7FD1 + 0x183CAC30D2441D0E) & U64)
        self.mem.write(self.obj + 0x178, 8, (y - 0x6C5EAB60B426DD28 + 0x61501AA6ECFD980A) & U64)
        self.mem.write(self.obj + 0x180, 8, (z - 0x21D14A25ED7C802C - 0x2B3719EF44DE99FF) & U64)

    def members(self, kinds: list[int]) -> tuple[int, int]:
        vector, data = self.alloc(16), self.alloc(max(8, len(kinds) * 8))
        self.mem.write(vector, 8, data)
        self.mem.write(vector + 8, 4, len(kinds))
        for i, kind in enumerate(kinds):
            member, master = self.alloc(0x20), self.alloc(0x30)
            self.mem.write(member + 0x10, 8, (master + MA + MB) & U64)
            self.set_kind(master, kind)
            self.mem.write(data + i * 8, 8, member)
        self.mem.write(self.obj + 0x150, 8, vector)
        return vector, data

    def special(self, count: int = 10) -> tuple[int, int]:
        self.set_kind(self.master, 0x221)
        self.mem.write(self.master + 0x74, 1, 10)
        return self.members([0xEF] * count)

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
                self.snapshots.append(bytes(view))
                self.live.pop()

    def frame(self) -> int:
        return next(at for length, at in reversed(self.live) if length == 0xC0)

    def bind(self, **overrides: ReplayTaskRebuildCalls) -> ReplayTaskRebuildCalls:
        channels = {
            key: ReplayTaskRebuildCalls(self.channel(key))
            for key in (
                "virtual_calls",
                "logger_home_calls",
                "position_fp_home_calls",
                "rtti_home_calls",
            )
        }
        channels.update(overrides)
        return bind_replay_base_object_update(
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
            if channel == "virtual_calls":
                if target == STATE:
                    self.mem.write(args[0] + 0x188, 1, args[1])
                    return None
                if target in (SELECT, DELETE, CHECK, REG_A, REG_B, 0xF004F8, 0xF00600):
                    return None
                if target in (OTHER, GET850, GET858, GET848):
                    return self.other if target == OTHER else self.graphic
                if target == FRAME:
                    return 5
                if target == CLONE:
                    self.mem.write_bytes(self.clone, self.mem.read_bytes(args[0], 0x600))
                    return self.clone
                if target == 0xF00620:
                    return 0
                if target == POSITION:
                    self.mem.fill(args[1], 0, 12)
                    return args[1]
            if channel == "logger_home_calls" and target == LOG:
                return None
            if channel == "position_fp_home_calls" and target == FACTORY:
                return self.created
            if channel == "rtti_home_calls" and target == CAST:
                return args[0]
            if channel == "scalar_fp_calls" and target in (SQRT, ELAPSED):
                assert self.moving.call is not None
                return self.moving.call(target, args, None)
            if channel == "motion_fp_calls" and target == MOTION:
                assert self.moving.call is not None
                return self.moving.call(target, args, None)
            if channel == "virtual_fp_home_calls" and target == VELOCITY:
                return 0x40400000
            if channel == "virtual_fp_calls" and target in (TRANSLATE, ANIM10):
                return None
            if channel == "motion_logger" and target == 0x140B6EF80:
                return None
            raise UnresolvedReplayTaskRebuild(f"authored {channel} missing{target:x}")

        return dispatch

    def ordinary(self, target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        assert data is None
        if handler := self.record("calls", target, args):
            return handler(args)
        if target in (MALLOC, ZERO, FREE):
            assert self.runtime.call is not None
            return self.runtime.call(target, args, None)
        if target == ENTRY:
            assert self.bound.call is not None
            return self.bound.call(target, args, None)
        if target in (GAME, OWNER):
            assert self.variants.call is not None
            return self.variants.call(target, args, None)
        if target == MODE:
            assert self.mode.call is not None
            return self.mode.call(target, args, None)
        if target == NAME:
            return self.name
        if target in (0x141252300, 0x140BB9290):
            return 1
        if target in (0x1410B9490, RNG):
            return 0
        if target == 0x141603D70:
            return self.owner
        if target == 0x141694610:
            return 5
        if target == 0x1409CBEF0:
            self.mem.write(args[0] + 0x18, 2, args[1])
            return args[0]
        if target == 0x141248170:
            header, capacity = args
            old, count = self.mem.read(header, 8), self.mem.read(header + 0x10, 8)
            current = self.alloc(max(capacity * 8, 0x18100))
            self.mem.write_bytes(current, self.mem.read_bytes(old, count * 8))
            self.mem.write(header, 8, current)
            self.mem.write(header + 8, 8, capacity)
            assert self.runtime.call is not None
            self.runtime.call(FREE, (old, self.sizes[old]), None)
            return None
        if target == 0x1412429D0:
            self.mem.write(args[0], 8, self.master)
            return None
        if target in (
            0x141243980,
            0x141248340,
            0x1412493C0,
            0x14125CC30,
            0x14120E0F0,
            0x14172C8D0,
            0x1409B5F00,
            0x1409B5F80,
            0x1409B5E80,
            0x1409CD830,
            SCRIPT,
        ):
            return None
        raise UnresolvedReplayTaskRebuild(f"authored child missing{target:x}")

    def run(self) -> int | None:
        assert self.bound.call is not None
        return self.bound.call(ENTRY, (self.obj,), None)

    def called(self, target: int, channel: str = "calls") -> list[tuple[int, ...]]:
        return [args for key, at, args in self.calls if key == channel and at == target]


def test_profile_and_addressed_contracts_refuse_before_effects() -> None:
    r = Rig()
    for seed in (b"", bytearray(r.profile.frame)):
        with pytest.raises(ValueError):
            replace(r.profile, frame=seed)
    assert r.bound.call is not None
    for args, data in (((), None), ((-1,), None), ((r.obj,), memoryview(b"raw"))):
        with pytest.raises(ValueError):
            r.bound.call(ENTRY, args, data)
    assert not r.events


def test_unknown_calls_preserve_arguments_payload_and_result_identity() -> None:
    r = Rig()
    args, payload, result = (-1, 2), memoryview(b"raw"), 123456789012345

    def unknown(target: int, given: tuple[int, ...], data: memoryview | None) -> int:
        assert target == 42 and given is args and data is payload
        return result

    r.ordinary_calls = ReplayTaskRebuildCalls(unknown)
    bound = r.bind()
    assert bound.call is not None and bound.call(42, args, payload) is result


@pytest.mark.parametrize("state", [*range(10), 255])
def test_all_state_arms_and_default_preserve_normal_return(state: int) -> None:
    r = Rig()
    r.mem.write(r.obj + 0x188, 1, state)
    assert r.run() == int(state == 8)
    assert bool(r.called(0x141243980)) == (state in (2, 3))
    assert bool(r.called(0x141248340)) == (state == 2)
    assert r.mem.read(r.obj + 0x168, 4) == (0x3F000000 if state in (3, 5) else 0x3F800000)
    assert not r.live


def test_current_jump_table_alias_and_unknown_target_preserve_prefix() -> None:
    r = Rig()
    r.mem.write(0x14124AA10 + 4, 4, 0x124A075)
    assert r.run() == 1
    r.mem.write(0x14124AA10 + 4, 4, 0x1234567)
    with pytest.raises(UnresolvedReplayTaskRebuild, match="state target"):
        r.run()
    assert len(r.called(NAME)) == 2
    assert not r.live


def test_initial_name_is_required_even_when_debug_logging_disabled() -> None:
    r = Rig()
    r.handlers["calls", NAME] = lambda args: None
    with pytest.raises(ValueError, match="RAX"):
        r.run()
    assert not r.called(OWNER)
    assert not r.live


def test_diagnostic_has_live_typed_nodes_and_held_owner_index() -> None:
    r = Rig()
    r.mem.write(0x14435505B, 1, 2)

    def logger(args: tuple[int, ...]) -> None:
        assert args[:4] == (0xABC0, 0x23, 0x1432B4A40, 5)
        array = r.mem.read(args[4], 8)
        nodes = [r.mem.read(array + i * 8, 8) for i in range(5)]
        assert [r.mem.read(at + 8, 4) for at in nodes] == [15, 10, 10, 10, 2]
        assert r.mem.read(nodes[0], 8) == 0xABCDEF01
        assert [r.mem.read(at, 4) for at in nodes[1:]] == [0x3F800000, 0x40000000, 0x40400000, 1]

    r.handlers["logger_home_calls", LOG] = logger
    assert r.run() == 0


def test_registration_reload_owner_and_flag_before_early_zero() -> None:
    r = Rig()
    other = r.alloc(0x700)
    r.mem.write(other, 8, r.owner_table)
    r.mem.write(r.obj + 0x18B, 1, 1)
    r.mem.write(r.obj + 0x18A, 1, 7)

    def first(args: tuple[int, ...]) -> None:
        assert args == (r.owner, r.obj, 0, 7)
        assert r.mem.read(r.obj + 0x18B, 1) == 0
        assert r.mem.read(r.obj + 0x189, 1) == 1
        r.mem.write(r.obj + 0x18, 8, other)
        r.mem.write(r.obj + 0x18A, 1, 9)

    r.handlers["virtual_calls", REG_A] = first
    assert r.run() == 0
    assert r.called(REG_B, "virtual_calls") == [(other, r.obj, 1, 9)]
    assert not r.called(OWNER)


@pytest.mark.parametrize(
    ("status", "hp", "check"),
    [(2, 0x3F000000, True), (2, 0x3F800000, False), (2, 0x7FC12345, False), (5, 0, False)],
)
def test_linked_status_uses_other_status_and_exact_hp_comparison(
    status: int, hp: int, check: bool
) -> None:
    r = Rig()
    r.mem.write(r.obj + 0x148, 8, r.other)
    r.mem.write(r.other + 0x188, 1, status)
    r.set_hp(hp)
    r.run()
    assert bool(r.called(CHECK, "virtual_calls")) == check
    if status == 5:
        assert r.called(STATE, "virtual_calls") == [(r.obj, 5), (r.other, 7)]


@pytest.mark.parametrize(
    ("hp", "death"), [(0x3F7FFFFF, True), (0x3F800000, False), (0x7FC12345, False)]
)
def test_dead_threshold_and_required_cleanup(hp: int, death: bool) -> None:
    r = Rig()
    r.mem.write(r.obj + 0x188, 1, 0)
    r.set_hp(hp)
    r.run()
    assert bool(r.called(0x1412493C0)) == death
    assert r.called(STATE, "virtual_calls") == ([(r.obj, 3)] if death else [])


def test_building_links_copy_low_hp_preserving_current_coordinate_high_word() -> None:
    r = Rig()
    r.mem.write(r.obj + 0x188, 1, 0)
    r.mem.write(r.obj + 0xF, 1, 0x50)
    r.set_hp(0x3F000000)
    r.mem.write(r.obj + 0x870, 8, r.other)
    r.mem.write(r.other + 0xF, 1, 0x50)
    r.mem.write(r.other + 0x868, 8, 123)
    r.run()
    decoded = ((r.mem.read(r.other + 0x130, 8) ^ HX) - HS) & U64
    assert decoded == 0x223344553F000000
    assert r.mem.read(r.other + 0x868, 8) == 0
    assert r.mem.read(r.obj + 0x870, 8) == 0


def test_positive_building_factory_rtti_homes_and_actual_followups() -> None:
    r = Rig()
    for at, width, value in (
        (r.obj + 0x188, 1, 0),
        (r.obj + 0xF, 1, 0x50),
        (r.master + 0x86, 2, 2),
        (r.graphics + 16, 8, r.factory),
    ):
        r.mem.write(at, width, value)
    r.set_hp(0x3F000000)

    def factory(args: tuple[int, ...]) -> int:
        assert args[:4] == (r.factory, r.owner, 0x3F800000, 0x40000000)
        assert r.mem.read_bytes(args[4], 8) == bytes.fromhex("00004040a5a5a5a5")
        assert r.mem.read(r.mem.read(args[5], 8), 1) == 1
        return r.created

    def rtti(args: tuple[int, ...]) -> int:
        assert args[:4] == (r.created, 0, 0x14411D848, 0x1441290A0)
        assert r.mem.read_bytes(args[4], 8) == bytes.fromhex("00000000a5a5a5a5")
        return r.other

    r.handlers["position_fp_home_calls", FACTORY] = factory
    r.handlers["rtti_home_calls", CAST] = rtti
    r.run()
    assert r.called(0x14120E0F0) == [(r.other,)]
    assert (r.other, 0) in r.called(0x14125CC30)


@pytest.mark.parametrize(
    ("timer", "rate", "expected"),
    [
        (0x3F800000, 0x40000000, 0x3F000000),
        (0x3E000000, 0x40000000, 0),
        (0x3F800000, 0, 0x3F800000),
        (0x7FC12345, 0x40000000, 0x7FC12345),
    ],
)
def test_timer_fp_words_and_unordered_alternative(timer: int, rate: int, expected: int) -> None:
    r = Rig()
    r.mem.write(r.obj + 0x188, 1, 5)
    r.mem.write(r.obj + 0x168, 4, timer)
    r.mem.write(r.master + 0xC0, 4, rate)
    r.run()
    assert r.mem.read(r.obj + 0x168, 4) == expected


def test_timer_inactive_holds_other_target_but_calls_fresh_third_selector() -> None:
    r = Rig()
    r.mem.write(r.obj + 0x188, 1, 5)
    r.mem.write(r.obj + 0x160, 2, 0xFFFF)
    sequence = iter((r.graphic, r.created))
    r.handlers["virtual_calls", GET858] = lambda args: next(sequence)
    r.run()
    assert r.called(SELECT, "virtual_calls") == [(r.other, r.created)]
    assert r.called(0x14125CC30) == [(r.other, 0)]


@pytest.mark.parametrize(("answer", "registered"), [(0x7FFFFFFF, True), (0x80000000, False)])
def test_state_seven_uses_signed_eax_and_known_ecx_word(answer: int, registered: bool) -> None:
    r = Rig()
    r.mem.write(r.obj + 0x188, 1, 7)
    r.mem.write(r.obj + 0x160, 2, 0xFFFF)
    r.handlers["calls", 0x1410B9490] = lambda args: answer
    r.run()
    assert r.called(0x1410B9490) == [(U32,)]
    assert bool(r.called(0x14172C8D0)) == registered


def test_effect_vector_mutations_reach_current_end_and_current_cleanup_member() -> None:
    r = Rig()
    data, first, second = r.alloc(16), r.alloc(0x30), r.alloc(0x30)
    r.mem.write(data, 8, first)
    r.mem.write(data + 8, 8, second)
    r.mem.write(r.obj + 0x248, 8, data)
    r.mem.write(r.obj + 0x250, 8, data + 8)

    def disable(args: tuple[int, ...]) -> None:
        if args[0] == first:
            r.mem.write(data, 8, r.other)
            r.mem.write(r.obj + 0x250, 8, data + 16)
        r.mem.write(r.frame() + 0x40, 1, 7)

    r.handlers["calls", 0x1409B5F80] = disable
    assert r.run() == 7
    assert r.called(0x1409B5E80) == [(r.other,), (second,)]
    assert r.mem.read(data, 16) == 0


def test_enabled_effect_uses_bitmap_and_exact_current_vector() -> None:
    r = Rig()
    data, effect, bitmap = r.alloc(8), r.alloc(0x30), r.alloc(4)
    for at, width, value in (
        (data, 8, effect),
        (effect + 0x24, 2, 0x0101),
        (bitmap, 4, 1),
        (r.obj + 0x260, 8, bitmap),
        (r.obj + 0x248, 8, data),
        (r.obj + 0x250, 8, data + 8),
    ):
        r.mem.write(at, width, value)

    def update(args: tuple[int, ...]) -> None:
        assert args[0] == effect
        assert [r.mem.read(args[1] + i * 4, 4) for i in range(3)] == [
            0x3F800000,
            0x40000000,
            0x40400000,
        ]

    r.handlers["calls", 0x1409B5F00] = update
    r.run()
    assert r.called(0x1409B5F00)
    assert not r.called(0x1409B5F80)


def test_special_graphic_creation_real_allocation_append_clone_and_master_install() -> None:
    r = Rig()
    r.special()
    r.run()
    assert r.called(MALLOC) == [(0xF8,)]
    allocated = r.called(ZERO)[0][0]
    assert r.called(ZERO) == [(allocated, 0, 0xF8)]
    assert r.mem.read(r.world + 0xD0, 8) == 3
    assert r.mem.read(r.gfx_buffer + 16, 8) == allocated
    assert r.mem.read(r.obj + 0x290, 4) == 2
    assert r.mem.read(r.obj + 0x294, 1) == 1
    assert r.mem.read(r.obj + 0x10, 8) == (r.clone + MA + MB) & U64
    assert r.mem.read(r.clone + 0x40, 8) == allocated
    assert r.mem.read(r.clone + 0x1E8, 8) == allocated
    assert r.called(SELECT, "virtual_calls") == [(r.obj, allocated)]


@pytest.mark.parametrize("reason", ["malloc-null", "counterpart-null", "clone-null"])
def test_graphic_failed_publication_prefixes_remain_literal(reason: str) -> None:
    r = Rig()
    r.special()
    if reason == "malloc-null":
        r.handlers["calls", MALLOC] = lambda args: 0
    elif reason == "counterpart-null":
        r.mem.write(r.gfx_buffer + 0x180B0, 8, 0)
    else:
        r.handlers["virtual_calls", CLONE] = lambda args: 0
    r.run()
    assert r.mem.read(r.obj + 0x294, 1) == 1
    assert not r.called(SELECT, "virtual_calls")
    assert r.mem.read(r.world + 0xD0, 8) == (3 if reason == "clone-null" else 2)


def test_graphic_growth_and_attributes_use_actual_backing_and_free_old_buffer() -> None:
    r = Rig()
    r.special()
    r.mem.write(r.world + 0xC8, 8, 2)
    attributes, old_attribute = r.alloc(16), r.alloc(0x30)
    r.mem.write(old_attribute + 0x18, 2, 0x1002)
    r.mem.write(attributes, 8, old_attribute)

    def construct(args: tuple[int, ...]) -> int:
        r.mem.write(args[0] + 0x18, 2, args[1])
        r.mem.write(args[0] + 0x8C, 2, 1)
        r.mem.write(args[0] + 0x90, 8, attributes)
        return args[0]

    r.handlers["calls", 0x1409CBEF0] = construct
    r.run()
    assert r.called(0x141248170) == [(r.world + 0xC0, 3)]
    assert r.mem.read(attributes, 8) == r.replacement
    assert r.mem.read(r.world + 0xC8, 8) == 3
    with pytest.raises(ReplayMemoryError):
        r.mem.read(r.gfx_buffer, 1)


def test_positive_member_scan_reloads_return_home_but_empty_effects_do_not() -> None:
    r = Rig()
    r.special(1)

    def mode(args: tuple[int, ...]) -> int:
        r.mem.write(r.frame() + 0x40, 1, 6)
        return 2

    r.handlers["calls", MODE] = mode
    assert r.run() == 6
    r.mem.write(r.obj + 0x150, 8, 0)
    assert r.run() == 0


def test_member_range_uses_live_home_base_and_rereads_current_count() -> None:
    r = Rig()
    r.special(0)
    r.members([0xEF] * 9 + [0x430])

    def change_base(at: int, width: int, value: int) -> None:
        if r.live and at == r.frame() + 0x30 and width == 4 and value == 0x42F:
            r.mem.write(at, 2, 0x430)

    r.after_write = change_base
    r.run()
    assert r.called(MALLOC) == [(0xF8,)]
    r = Rig()
    vector, data = r.special(10)

    def shrink(at: int, width: int, value: int) -> None:
        if at == data:
            r.mem.write(vector + 8, 4, 1)

    r.after_read = shrink
    r.run()
    assert not r.called(MALLOC)


def test_low_member_count_holds_vptr_and_late_slot_when_restoring_graphic() -> None:
    r = Rig()
    r.special(9)
    r.mem.write(r.obj + 0x188, 1, 2)
    r.mem.write(r.obj + 0x294, 1, 1)
    other_table = r.alloc(0x900)
    r.mem.write(other_table + 0x70, 8, 0xEE7777)

    def select(args: tuple[int, ...]) -> int:
        r.mem.write(r.obj, 8, other_table)
        r.mem.write(r.table + 0x70, 8, 0xEE0070)
        return r.created

    r.handlers["virtual_calls", GET848] = select
    r.handlers["virtual_calls", 0xEE0070] = lambda args: None
    r.run()
    assert r.mem.read(r.obj + 0x294, 1) == 0
    assert r.called(DELETE, "virtual_calls") == [(r.obj,)]
    assert r.called(0xEE0070, "virtual_calls") == [(r.obj, r.created)]
    assert not r.called(0xEE7777, "virtual_calls")


def test_state_eight_held_return_ignores_late_home_change_without_source_reload() -> None:
    r = Rig()
    r.mem.write(r.obj + 0x188, 1, 8)

    def owner(args: tuple[int, ...]) -> int:
        r.mem.write(r.frame() + 0x40, 1, 9)
        return 1

    r.handlers["calls", OWNER] = owner
    assert r.run() == 1
    assert r.snapshots[-1][0x40] == 9


@pytest.mark.parametrize(
    ("variant", "mode"),
    [
        (0, None),
        (1, 0x672),
        (9, 0x672),
        (10, 0x673),
        (18, 0x673),
        (19, 0x674),
        (26, 0x674),
        (27, 0x675),
        (0x7FFFFFFF, 0x675),
        (U32, None),
    ],
)
def test_final_script_signed_unsigned_ranges_and_live_homes(variant: int, mode: int | None) -> None:
    r = Rig()
    r.mem.write(r.owner + 0x10, 4, 0)
    r.set_kind(r.master, 0x671)
    r.handlers["calls", 0x141694610] = lambda args: variant

    def script(args: tuple[int, ...]) -> None:
        assert args[0] == 0xC0FFEE and args[2:] == (mode, 123)
        assert r.mem.read(args[1], 4) == 1

    r.handlers["calls", SCRIPT] = script
    r.run()
    assert bool(r.called(SCRIPT)) == (mode is not None)


@pytest.mark.parametrize(
    ("variant", "receiver"), [(1, 0xC0FFEE), (10, 0xFEED), (19, 0xFEED), (27, 0xC0FFEE)]
)
def test_final_script_arm_specific_receiver_sampling_and_late_object_id(
    variant: int, receiver: int
) -> None:
    r = Rig()
    r.mem.write(r.owner + 0x10, 4, 0)
    r.set_kind(r.master, 0x671)
    r.handlers["calls", 0x141694610] = lambda args: variant

    def mutate(at: int, width: int, value: int) -> None:
        if r.live and at == r.frame() + 0x30 and width == 4 and value == 1:
            r.mem.write(r.world + 0x130, 8, 0xFEED)
            r.mem.write(r.obj + 8, 4, 456)

    r.after_write = mutate
    r.run()
    args = r.called(SCRIPT)[0]
    assert args[0] == receiver and args[3] == 456


@pytest.mark.parametrize(
    "channel", ["virtual_calls", "logger_home_calls", "position_fp_home_calls", "rtti_home_calls"]
)
def test_missing_channel_refuses_after_source_prefix(channel: str) -> None:
    r = Rig()
    if channel == "logger_home_calls":
        r.mem.write(0x14435505B, 1, 2)
    elif channel in ("position_fp_home_calls", "rtti_home_calls"):
        r.mem.write(r.obj + 0x188, 1, 0)
        r.mem.write(r.obj + 0xF, 1, 0x50)
        r.mem.write(r.master + 0x86, 2, 2)
        r.mem.write(r.graphics + 16, 8, r.factory)
        r.set_hp(0x3F000000)
    else:
        r.mem.write(r.obj + 0x18B, 1, 1)
    r.bound = r.bind(**{channel: ReplayTaskRebuildCalls(None)})
    with pytest.raises(UnresolvedReplayTaskRebuild):
        r.run()
    assert r.called(NAME) and not r.live


def test_object_list_composes_real_base_moving_motion_and_animated() -> None:
    r = Rig()
    r.mem.write(r.obj + 0x400, 8, r.motion)
    r.mem.write(r.table + 0x30, 8, MOVING)
    header, data = r.alloc(0x20), r.alloc(8)
    r.mem.write(header + 8, 8, data)
    r.mem.write(header + 0x10, 4, 1)
    r.mem.write(data, 8, r.obj)
    objects = bind_replay_object_update(r.context, r.moving, profile=ReplayObjectUpdateProfile(1))
    assert objects.call is not None and objects.call(0x141229A20, (header,), None) is None
    assert r.mem.read(r.obj + 0x198, 4) == 93
    assert r.mem.read(r.obj + 0x350, 4) == 0x40400000
    assert r.called(ENTRY) == [(r.obj,)]
    assert r.called(NAME) == [(r.master,), (r.master,)]
    assert r.called(OWNER) == [(r.owner,)]


def test_invalid_capabilities_and_mxcsr_refuse_before_effects() -> None:
    r = Rig()
    with pytest.raises(ValueError):
        r.bind(virtual_calls=cast(ReplayTaskRebuildCalls, None))
    for mxcsr in (True, 0, 0x1F81, 0x3F80):
        with pytest.raises(ValueError):
            bind_replay_base_object_update(
                r.context,
                r.ordinary_calls,
                **{
                    name: ReplayTaskRebuildCalls(None)
                    for name in (
                        "virtual_calls",
                        "logger_home_calls",
                        "position_fp_home_calls",
                        "rtti_home_calls",
                    )
                },
                bind_local=r.local,
                profile=r.profile,
                mxcsr=mxcsr,
            )
    assert not r.events
