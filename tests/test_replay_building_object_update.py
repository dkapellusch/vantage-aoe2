"""Owned-state controls for the complete Building caller and inherited chain.

External registration,member,repair,resource,event,rectangle andproduction
services are authored effects. Existing Unit/clock/top/clear/move bodies are
composed explicitly. No Game instructions or restored recording World run.
"""

from __future__ import annotations

import struct
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import cast

import pytest
from test_replay_action_object_update import BASE, CLOCK, U32, U64, encoded
from test_replay_unit_object_update import UNIT, bits, health_decoded, health_encoded
from test_replay_unit_object_update import Rig as UnitRig

from vantage.replay_binary32 import add_binary32
from vantage.replay_building_object_update import (
    ReplayBuildingObjectUpdateProfile,
    bind_replay_building_object_update,
)
from vantage.replay_memory import ReplayMemoryError
from vantage.replay_object_update import (
    ReplayObjectUpdateProfile,
    bind_replay_object_update,
)
from vantage.replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    UnresolvedReplayTaskRebuild,
)

BUILDING, TOP, CLEAR, MOVE, LOOKUP = 0x141281600, 0x140B88AF0, 0x140B88A20, 0x142D6E3DB, 0x141617DB0
REGISTER_OUT, REGISTER_IN, MASTER_FLAG, STATE, MAINTAIN, UPDATE_MEMBER, REPAIR, SCRIPT_FLAG = (
    0xF402E0,
    0xF402D8,
    0xF40118,
    0xF400A8,
    0xF401C0,
    0xF400D8,
    0xF40120,
    0xF400B0,
)
ANIM_GET, ANIM_SET, CREDIT = 0xF40008, 0xF40028, 0xF400F8
DETACH, TASK, EVENT, RECT, STAGE, TICK, PROD_RUN, PROD_RESET, PROD_APPLY = (
    0x1412A2170,
    0x140B67D10,
    0x140A635D0,
    0x141046E50,
    0x141286D70,
    0x14127CC00,
    0x140BB83E0,
    0x141288160,
    0x1412A2C70,
)
MA, MB = 0x6A586EB28AC201FC, 0x0CF19788B2554E70
MAX_A, MAX_B = 0xD978539418047C54, 0xABAA7F7397F61E6C
CHANNELS = (
    "virtual_calls",
    "member_fp_home_calls",
    "task_fp_calls",
    "resource_fp_home_calls",
    "resource_event_home_calls",
    "repair_fp_calls",
    "rectangle_home_calls",
)
DATA = Path(__file__).resolve().parents[1] / "artifacts/game-internals/2026-10-18-world-envelope"


class Rig(UnitRig):
    def __init__(self) -> None:
        super().__init__()
        self.real_unit = False
        self.unit_result = 0x1234000000FA
        self.threshold = 100
        self.animation_stage = 0xFFFF
        self.queue_result = 0xA5
        self.remove_on_detach = False
        self.detached: list[int] = []
        self.credits: list[tuple[int, ...]] = []
        self.credit_homes: list[bytes] = []
        self.resource_events: list[tuple[int, int, int, int]] = []
        self.rectangles: list[tuple[int, ...]] = []
        self.registered: dict[int, set[int]] = {p: set() for p in self.players}
        self.master_table = self.alloc(0x120)
        self.mem.write(self.master_table + 0x118, 8, MASTER_FLAG)
        self.mem.write(self.master, 8, self.master_table)
        self.mem.write(self.master + 0x68, 8, 100 ^ MAX_A ^ MAX_B)
        self.set_health(bits(100.0))
        old = self.player_table
        self.player_table = self.alloc(0x300)
        self.mem.write_bytes(self.player_table, self.mem.read_bytes(old, 0xB0))
        for slot, target in ((0x2E0, REGISTER_OUT), (0x2D8, REGISTER_IN), (0xF8, CREDIT)):
            self.mem.write(self.player_table + slot, 8, target)
        for player in self.players:
            self.mem.write(player, 8, self.player_table)
        for slot, target in (
            (0xA8, STATE),
            (0x1C0, MAINTAIN),
            (0xD8, UPDATE_MEMBER),
            (0x120, REPAIR),
        ):
            self.mem.write(self.table + slot, 8, target)
        for slot, target in ((8, ANIM_GET), (0x28, ANIM_SET)):
            self.mem.write(self.anim_table + slot, 8, target)
        old = self.script_table
        self.script_table = self.alloc(0xC0)
        self.mem.write_bytes(self.script_table, self.mem.read_bytes(old, 0x28))
        self.mem.write(self.script_table + 0xB0, 8, SCRIPT_FLAG)
        self.mem.write(self.script_obj, 8, self.script_table)
        self.queue = self.alloc(0x20)
        self.mem.write(self.queue + 8, 8, self.obj)
        self.mem.write(self.obj + 0x850, 8, self.queue)
        self.bus = self.alloc(8)
        for constant in (DATA / "building-object-update-source-v1").glob("constant-*.bin"):
            at, raw = int(constant.stem.split("-")[1], 16), constant.read_bytes()
            try:
                assert self.mem.read_bytes(at, len(raw)) == raw
            except ReplayMemoryError:
                self.mem.map_bytes(at, raw)
        self.building_profile = ReplayBuildingObjectUpdateProfile(bytes([0xA8]) * 0x50)
        self.building = self.bind_building()

    def active_building(self, now: int = 100) -> None:
        self.mem.write(self.obj + 0x188, 1, 2)
        self.mem.write(self.clock + 0x18, 4, now)

    def make_members(self, count: int) -> tuple[int, list[int], list[int]]:
        container, data = self.alloc(16), self.alloc(max(count * 8, 8))
        members, masters = [], []
        for index in range(count):
            member, master = self.alloc(0xA00), self.alloc(0x600)
            self.mem.write(member, 8, self.table)
            self.mem.write(member + 0x10, 8, (master + MA + MB) & U64)
            self.mem.write(member + 0x130, 8, health_encoded(bits(5.0)))
            self.mem.write(member + 0xF, 1, 0x50)
            self.mem.write(master, 8, self.master_table)
            self.mem.write(master + 0x68, 8, 100 ^ MAX_A ^ MAX_B)
            self.mem.write(master + 0x38, 8, (-0x5B32AA7995D95916 + 0x50A06BCECEBEF905) & U64)
            self.mem.write(data + index * 8, 8, member)
            members.append(member)
            masters.append(master)
        self.mem.write(container, 8, data)
        self.mem.write(container + 8, 4, count)
        self.mem.write(self.obj + 0x150, 8, container)
        return container, members, masters

    def construction_data(self, progress: float = 50.0) -> None:
        records, graphic = self.alloc(12), self.alloc(0x20)
        self.mem.write(records + 2, 2, 100)
        self.mem.write(self.master + 0x338, 8, records)
        self.mem.write(self.master + 0x340, 8, records + 12)
        self.mem.write(graphic + 8, 2, 4)
        self.mem.write(graphic + 0xA, 2, 4)
        self.mem.write(self.obj + 0x20, 8, graphic)
        self.mem.write(self.obj + 0x188, 1, 0)
        self.mem.write(self.obj + 0x900, 4, bits(progress))
        self.mem.write(self.master + 0x78, 4, bits(2.0))
        self.mem.write(self.master + 0x7C, 4, bits(3.0))
        self.coords(self.obj, bits(10.0), bits(20.0))

    def resource_data(self) -> None:
        self.active_building(6000)
        self.kind(0x68)
        self.mem.write(self.obj + 0x8D0, 4, 1)
        self.mem.write(self.obj + 0x8D4, 4, 2)
        for member, value in ((0x708, 60.0), (0x840, 120.0), (0x848, 180.0), (0x5F8, 240.0)):
            self.mem.write(self.resource + member, 8, encoded(bits(value)))

    def bind_building(self, **overrides: ReplayTaskRebuildCalls) -> ReplayTaskRebuildCalls:
        channels = {name: ReplayTaskRebuildCalls(self.channel(name)) for name in CHANNELS}
        channels.update(overrides)
        return bind_replay_building_object_update(
            self.context,
            self.ordinary_calls,
            **channels,
            bind_local=self.local,
            profile=self.building_profile,
            mxcsr=0x1F80,
        )

    def ordinary(self, target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        local = target in (
            UNIT,
            CLEAR,
            MOVE,
            0x140BB9290,
            STAGE,
            TICK,
            PROD_RUN,
            PROD_RESET,
            PROD_APPLY,
            0x1412BAED0,
            0x140A69450,
        )
        if not local:
            return super().ordinary(target, args, data)
        assert data is None
        if handler := self.record("calls", target, args):
            return handler(args)
        if target == UNIT:
            if self.real_unit:
                assert self.unit.call is not None
                return self.unit.call(target, args, None)
            return self.unit_result
        if target == CLEAR:
            assert self.action.call is not None
            return self.action.call(target, args, None)
        if target == MOVE:
            assert self.runtime.call is not None
            return self.runtime.call(target, args, None)
        if target == 0x140BB9290:
            return self.threshold
        if target == PROD_RUN:
            return self.queue_result
        if target == STAGE:
            self.mem.write(args[0] + 0xE, 1, args[1])
        if target == PROD_RESET:
            self.mem.write(args[0] + 0x84D, 1, 0)
        if target == 0x140A69450:
            return self.bus
        return None

    def channel(
        self, channel: str
    ) -> Callable[[int, tuple[int, ...], memoryview | None], int | None]:
        fallback = super().channel(channel)

        def dispatch(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
            local = channel in CHANNELS[1:] or (
                channel == "virtual_calls"
                and target
                in (
                    REGISTER_OUT,
                    REGISTER_IN,
                    MASTER_FLAG,
                    STATE,
                    MAINTAIN,
                    UPDATE_MEMBER,
                    SCRIPT_FLAG,
                    ANIM_GET,
                    ANIM_SET,
                )
            )
            if not local:
                return fallback(target, args, data)
            assert data is None
            if handler := self.record(channel, target, args):
                return handler(args)
            if channel == "virtual_calls":
                if target == REGISTER_OUT:
                    self.registered[args[0]].discard(args[1])
                if target == REGISTER_IN:
                    self.registered[args[0]].add(args[1])
                if target == MASTER_FLAG:
                    self.mem.write(args[0] + 0x3F0, 1, args[1])
                if target == STATE:
                    self.mem.write(args[0] + 0x188, 1, args[1])
                if target == ANIM_GET:
                    return self.animation_stage
                if target == ANIM_SET:
                    self.animation_stage = args[2]
                if target == SCRIPT_FLAG:
                    self.mem.write(args[0] + 0x44, 4, args[1])
                return None
            if channel == "member_fp_home_calls" and target == DETACH:
                self.detached.append(args[1])
                if self.remove_on_detach:
                    container = self.mem.read(args[0] + 0x150, 8)
                    array, count = self.mem.read(container, 8), self.mem.read(container + 8, 4)
                    members = [self.mem.read(array + i * 8, 8) for i in range(count)]
                    members.remove(args[1])
                    for i, member in enumerate(members):
                        self.mem.write(array + i * 8, 8, member)
                    self.mem.write(container + 8, 4, count - 1)
                return None
            if channel == "task_fp_calls" and target == TASK:
                self.mem.write(args[0] + 0x44, 4, args[1])
                return None
            if channel == "resource_fp_home_calls" and target == CREDIT:
                self.credits.append(args)
                self.credit_homes.append(self.mem.read_bytes(args[-1], 8))
                return None
            if channel == "resource_event_home_calls" and target == EVENT:
                self.resource_events.append(
                    (args[0], self.mem.read(args[1], 4), args[2], self.mem.read(args[4], 8))
                )
                return None
            if channel == "repair_fp_calls" and target in (REPAIR, 0x1412C8D20):
                hp = health_decoded(self.mem.read(args[0] + 0x130, 8))
                value = add_binary32(hp & U32, args[1])
                self.mem.write(args[0] + 0x130, 8, health_encoded(hp & ~U32 | value))
                return 1
            if channel == "rectangle_home_calls" and target == RECT:
                self.rectangles.append(
                    (
                        args[0],
                        args[1],
                        args[2],
                        args[3],
                        self.mem.read(args[4], 4),
                        self.mem.read(args[5], 1),
                    )
                )
                return None
            raise UnresolvedReplayTaskRebuild(f"authored {channel} missing{target:x}")

        return dispatch

    def run_building(self) -> int | None:
        assert self.building.call is not None
        return self.building.call(BUILDING, (self.obj,), None)


def test_exact_immutable_profile_and_addressed_call_shape() -> None:
    r = Rig()
    for seed in (b"", bytearray(0x50), bytes(0x51)):
        with pytest.raises(ValueError):
            replace(r.building_profile, building=seed)
    assert r.building.call is not None
    for args, data in (((), None), ((-1,), None), ((r.obj,), memoryview(b"raw"))):
        with pytest.raises(ValueError):
            r.building.call(BUILDING, args, data)
    assert not r.events


def test_unknown_calls_preserve_identity() -> None:
    r = Rig()
    args, payload, result = (-1, 3), memoryview(b"raw"), 123456789012345

    def unknown(target: int, given: tuple[int, ...], data: memoryview | None) -> int:
        assert target == 17 and given is args and data is payload
        return result

    r.ordinary_calls = ReplayTaskRebuildCalls(unknown)
    bound = r.bind_building()
    assert bound.call is not None and bound.call(17, args, payload) is result


@pytest.mark.parametrize("pending", [False, True])
def test_early_registration_returns_zero_without_unit_constant_or_private_frame(
    pending: bool,
) -> None:
    r = Rig()
    r.mem.write(r.obj + 0x948, 1, 1)
    r.mem.write(r.obj + 0x18B, 1, int(pending))
    r.mem.write(r.obj + 0x18A, 1, 7)
    assert r.run_building() == 0
    assert not r.called(UNIT) and not r.snapshots
    assert not any(e[1] == 0x1431B7520 for e in r.events)
    assert r.called(REGISTER_OUT, "virtual_calls") == ([(r.owner, r.obj, 0, 7)] if pending else [])
    assert r.called(REGISTER_IN, "virtual_calls") == ([(r.owner, r.obj, 1, 7)] if pending else [])


def test_registration_holds_first_tag_and_second_owner_before_current_tag() -> None:
    r = Rig()
    r.mem.write(r.obj + 0x948, 1, 1)
    r.mem.write(r.obj + 0x18B, 1, 1)
    r.mem.write(r.obj + 0x18A, 1, 7)
    second = False

    def write(at: int, width: int, value: int) -> None:
        if at == r.obj + 0x189:
            r.mem.write(r.obj + 0x18, 8, r.player2)

    def remove(args: tuple[int, ...]) -> None:
        nonlocal second
        r.mem.write(r.obj + 0x18, 8, r.owner)
        second = True

    def read(at: int, width: int, value: int) -> None:
        if at == r.obj + 0x18 and second:
            r.mem.write(r.obj + 0x18, 8, r.player2)
            r.mem.write(r.obj + 0x18A, 1, 11)

    r.after_write, r.after_read = write, read
    r.handlers["virtual_calls", REGISTER_OUT] = remove
    r.run_building()
    assert r.called(REGISTER_OUT, "virtual_calls") == [(r.player2, r.obj, 0, 7)]
    assert r.called(REGISTER_IN, "virtual_calls") == [(r.owner, r.obj, 1, 11)]


def test_default_path_keeps_unit_al_and_runs_production_then_apply() -> None:
    r = Rig()
    assert r.run_building() == 0xFA
    assert r.called(PROD_RUN) == [(r.queue,)]
    assert r.called(PROD_APPLY) == [(r.obj,)]
    assert r.mem.read(r.obj + 0x84D, 1) == 0xA5


@pytest.mark.parametrize("result", [0, U64])
def test_unit_zero_and_full_width_results_do_not_skip_production(result: int) -> None:
    r = Rig()
    r.unit_result = result
    assert r.run_building() == result & 255
    assert r.called(PROD_RUN) == [(r.queue,)] and r.called(PROD_APPLY) == [(r.obj,)]


@pytest.mark.parametrize(
    ("hp", "detach"),
    [(bits(19.0), True), (bits(20.0), True), (0x41A00001, False), (0x7FC12345, False)],
)
def test_exact_twenty_percent_health_guard_and_two_reverse_member_loops(
    hp: int, detach: bool
) -> None:
    r = Rig()
    r.active_building()
    r.set_health(hp)
    _, members, _ = r.make_members(3)
    r.run_building()
    assert r.detached == (members[::-1] if detach else [])
    assert r.called(MAINTAIN, "virtual_calls") == ([(m,) for m in members[::-1]] if detach else [])
    assert r.called(UPDATE_MEMBER, "virtual_calls") == (
        [(m,) for m in members[::-1]] if detach else []
    )


def test_detach_uses_real_partial_homes_and_current_count_for_second_loop() -> None:
    r = Rig()
    r.active_building()
    r.set_health(bits(1.0))
    _, members, _ = r.make_members(2)
    r.remove_on_detach = True
    r.run_building()
    assert r.detached == members[::-1]
    assert not r.called(MAINTAIN, "virtual_calls")
    for args in r.called(DETACH, "member_fp_home_calls"):
        assert args[2:4] == (0xBF800000, 0xBF800000)
    snapshot = next(raw for size, raw in r.snapshots if size == 0x50)
    assert snapshot[0x20:0x28] == bytes(8)
    assert snapshot[0x28:0x30] == b"\x01" + b"\xa8" * 7
    assert snapshot[0x30:0x38] == b"\x00" + b"\xa8" * 7


def test_entry_state_comparison_is_held_before_constant_read() -> None:
    r = Rig()
    r.set_health(bits(1.0))
    r.make_members(1)

    def mutate(at: int, width: int, value: int) -> None:
        if at == 0x1431B7520:
            r.mem.write(r.obj + 0x188, 1, 2)

    r.after_read = mutate
    r.run_building()
    assert not r.detached and not r.called(MASTER_FLAG, "virtual_calls")


def test_task_delta_uses_actual_top_and_clears_flag_after_required_effect() -> None:
    r = Rig()
    r.active_building()
    _, actions = r.nodes([0])
    r.mem.write(actions[0] + 0x44, 4, bits(9.0))
    r.mem.write(r.resource + 0x768, 8, encoded(bits(2.5)))
    r.mem.write(r.obj + 0x95C, 1, 1)
    r.run_building()
    assert r.called(TASK, "task_fp_calls") == [(actions[0], bits(6.5))]
    assert r.mem.read(r.obj + 0x95C, 1) == 0


def test_null_top_leaves_task_delta_flag_and_skips_resource_decode() -> None:
    r = Rig()
    r.active_building()
    r.mem.write(r.obj + 0x95C, 1, 1)
    r.run_building()
    assert r.mem.read(r.obj + 0x95C, 1) == 1
    assert not any(e[1] == r.resource + 0x768 for e in r.events)


@pytest.mark.parametrize(
    ("now", "previous", "seconds"),
    [(999, 0, 0), (1000, 0, 1), (2500, 0, 2), (U32, 0, 4294967), (599, U32 - 500, 1)],
)
def test_regular_unsigned_seconds_stamp_and_single_byte_decrement(
    now: int, previous: int, seconds: int
) -> None:
    r = Rig()
    r.active_building(now)
    r.mem.write(r.obj + 0x890, 4, previous)
    r.mem.write(r.obj + 0x165, 1, 3)
    r.run_building()
    assert r.called(TICK) == [(r.obj,)]
    assert r.mem.read(r.obj + 0x890, 4) == (previous + seconds * 1000) & U32
    assert r.mem.read(r.obj + 0x165, 1) == (2 if seconds else 3)


def test_resource_amounts_known_r9_masks_events_and_shared_partial_home() -> None:
    r = Rig()
    r.resource_data()
    r.run_building()
    assert [(args[1], args[2]) for args in r.credits] == [
        (0, bits(30.0)),
        (1, bits(60.0)),
        (2, bits(90.0)),
        (3, bits(120.0)),
        (100, bits(120.0)),
    ]
    assert [(args[3], args[4]) for args in r.credits] == [
        (0xA9834B738A7DD101, U64),
        (1, U64),
        (1, 255),
        (1, 255),
        (1, 255),
    ]
    assert r.credit_homes[0] == b"\x01" + b"\xa8" * 7
    assert r.credit_homes[-1] == bytes.fromhex("0100000000005e40")
    assert r.resource_events == [
        (r.bus, 1, i, int.from_bytes(struct.pack("<d", value), "little"))
        for i, value in enumerate((30.0, 60.0, 90.0, 120.0))
    ]


def test_first_resource_owner_is_held_before_last_decode_stage_then_owner_reloads() -> None:
    r = Rig()
    r.resource_data()

    def mutate(at: int, width: int, value: int) -> None:
        if r.live and at == r.frame(0x50) + 0x48 and value == bits(240.0):
            r.mem.write(r.obj + 0x18, 8, r.player2)

    r.after_write = mutate
    r.run_building()
    assert [args[0] for args in r.credits] == [r.owner, r.player2, r.player2, r.player2, r.player2]
    assert [event[1] for event in r.resource_events] == [2] * 4


def test_held_resource_amounts_survive_credit_callback_replacing_rates() -> None:
    r = Rig()
    r.resource_data()

    def credit(args: tuple[int, ...]) -> None:
        r.credits.append(args)
        for member in (0x708, 0x840, 0x848, 0x5F8):
            r.mem.write(r.resource + member, 8, encoded(bits(999.0)))

    r.handlers["resource_fp_home_calls", CREDIT] = credit
    r.run_building()
    assert [args[2] for args in r.credits] == [bits(v) for v in (30.0, 60.0, 90.0, 120.0, 120.0)]


def test_expiring_member_script_and_actual_detach_before_ordinary_decrement() -> None:
    r = Rig()
    r.active_building(1000)
    _, members, masters = r.make_members(2)
    for master in masters:
        r.mem.write(master + 8, 1, 0x46)
    r.mem.write(members[0] + 0x628, 4, 2)
    r.mem.write(members[1] + 0x628, 4, 1)
    r.mem.write(members[1] + 0x1F0, 8, r.script_obj)
    r.run_building()
    assert r.called(SCRIPT_FLAG, "virtual_calls") == [(r.script_obj, 1)]
    assert r.detached == [members[1]]
    assert r.mem.read(members[0] + 0x628, 4) == 1


def test_member_and_worker_repair_apply_actual_owned_health_effects() -> None:
    r = Rig()
    r.active_building(1000)
    r.set_health(bits(50.0))
    _, members, masters = r.make_members(2)
    r.mem.write(r.master + 0x460, 4, bits(2.0))
    r.mem.write(r.master + 0x464, 4, bits(3.0))
    for master in masters:
        r.mem.write(master + 0x38, 8, (4 - 0x5B32AA7995D95916 + 0x50A06BCECEBEF905) & U64)
    r.run_building()
    assert r.called(0x1412C8D20, "repair_fp_calls") == [(m, bits(2.0)) for m in members]
    assert r.called(REPAIR, "repair_fp_calls") == [(r.obj, bits(6.0))]
    assert health_decoded(r.mem.read(r.obj + 0x130, 8)) == bits(56.0)
    assert r.called(0x1412BAED0) == [(m,) for m in members]


def test_repair_return_is_only_consumed_after_current_member_type_read() -> None:
    r = Rig()
    r.active_building(1000)
    _, members, _ = r.make_members(1)
    r.mem.write(r.master + 0x460, 4, bits(2.0))

    def repair(args: tuple[int, ...]) -> None:
        r.mem.write(members[0] + 0xF, 1, 0)

    r.handlers["repair_fp_calls", 0x1412C8D20] = repair
    assert r.run_building() == 0xFA
    assert not r.called(0x1412BAED0)


def test_repair_requires_al_when_current_member_type_still_qualifies() -> None:
    r = Rig()
    r.active_building(1000)
    r.make_members(1)
    r.mem.write(r.master + 0x460, 4, bits(2.0))
    r.handlers["repair_fp_calls", 0x1412C8D20] = lambda args: None
    with pytest.raises(ValueError, match="member repair AL"):
        r.run_building()
    assert not r.called(0x1412BAED0) and not r.called(UNIT)
    assert r.mem.read(r.obj + 0x890, 4) == 1000


def test_forward_repair_loop_reloads_count_after_callback() -> None:
    r = Rig()
    r.active_building(1000)
    container, members, _ = r.make_members(2)
    r.mem.write(r.master + 0x460, 4, bits(2.0))

    def repair(args: tuple[int, ...]) -> int:
        r.mem.write(container + 8, 4, 1)
        return 0

    r.handlers["repair_fp_calls", 0x1412C8D20] = repair
    r.run_building()
    assert r.called(0x1412C8D20, "repair_fp_calls") == [(members[0], bits(2.0))]


def test_virtual_member_repair_holds_target_before_fresh_self_master_read() -> None:
    r = Rig()
    r.active_building(1000)
    _, members, _ = r.make_members(1)
    r.mem.write(members[0] + 0xF, 1, 0x46)
    r.mem.write(r.master + 0x460, 4, bits(2.0))

    def mutate(at: int, width: int, value: int) -> None:
        if at == r.table + 0x120:
            r.mem.write(at, width, 0xDEAD)

    r.after_read = mutate
    r.run_building()
    assert r.called(REPAIR, "repair_fp_calls") == [(members[0], bits(2.0))]
    assert r.called(0x1412BAED0) == [(members[0],)]


@pytest.mark.parametrize(
    "variant", ["normal_plain", "excluded_plain", "normal_anim", "excluded_anim"]
)
def test_four_construction_rectangle_routes_and_owned_animation_effects(variant: str) -> None:
    r = Rig()
    r.construction_data()
    if variant == "excluded_plain":
        r.kind(0x46)
    elif variant == "excluded_anim":
        r.object_class(0x1B)
    elif variant == "normal_anim":
        reads = 0

        def mutate(at: int, width: int, value: int) -> None:
            nonlocal reads
            if at == r.obj + 0x188:
                reads += 1
                if reads == 2:
                    r.object_class(0x1B)

        r.after_read = mutate
    r.run_building()
    assert r.rectangles == [(r.resource, 7, 16, 12, 23, 0)]
    if "anim" in variant:
        assert r.animation_stage == 2
    else:
        assert r.mem.read(r.obj + 0xE, 1) == 2


@pytest.mark.parametrize(("animation", "expected_min_y"), [(False, 16), (True, -181 & U32)])
def test_normal_rectangle_variants_sample_next_master_on_different_sides_of_y_read(
    animation: bool, expected_min_y: int
) -> None:
    r = Rig()
    r.construction_data()
    other = r.alloc(0x600)
    r.mem.write_bytes(other, r.mem.read_bytes(r.master, 0x600))
    r.mem.write(other + 0x78, 4, bits(100.0))
    r.mem.write(other + 0x7C, 4, bits(200.0))
    state_reads = 0
    changed = False

    def mutate(at: int, width: int, value: int) -> None:
        nonlocal state_reads, changed
        if animation and at == r.obj + 0x188:
            state_reads += 1
            if state_reads == 2:
                r.object_class(0x1B)
        if at == r.obj + 0x178 and not changed:
            changed = True
            r.mem.write(r.obj + 0x10, 8, (other + MA + MB) & U64)

    r.after_read = mutate
    r.run_building()
    assert r.rectangles == [(r.resource, 7, expected_min_y, 110, 220, 0)]


@pytest.mark.parametrize(
    ("variant", "max_y"),
    [("normal_plain", 220), ("excluded_plain", 220), ("normal_anim", 23), ("excluded_anim", 23)],
)
def test_rectangle_final_master_is_captured_on_source_side_of_last_y_read(
    variant: str, max_y: int
) -> None:
    r = Rig()
    r.construction_data()
    other = r.alloc(0x600)
    r.mem.write_bytes(other, r.mem.read_bytes(r.master, 0x600))
    r.mem.write(other + 0x7C, 4, bits(200.0))
    if variant == "excluded_plain":
        r.kind(0x46)
    elif variant == "excluded_anim":
        r.object_class(0x1B)
    states, ys = 0, 0

    def mutate(at: int, width: int, value: int) -> None:
        nonlocal states, ys
        if variant == "normal_anim" and at == r.obj + 0x188:
            states += 1
            if states == 2:
                r.object_class(0x1B)
        if at == r.obj + 0x178:
            ys += 1
            if ys == 2:
                r.mem.write(r.obj + 0x10, 8, (other + MA + MB) & U64)

    r.after_read = mutate
    r.run_building()
    assert ys == 2 and r.rectangles == [(r.resource, 7, 16, 12, max_y, 0)]


@pytest.mark.parametrize(
    ("progress", "rectangle", "completed"),
    [
        (0x7FC12345, True, False),
        (0x7F800000, True, True),
        (bits(-50.0), False, False),
        (bits(6400.0), True, True),
    ],
)
def test_graphic_stage_uses_cvtt_low_byte_and_ordered_completion(
    progress: int, rectangle: bool, completed: bool
) -> None:
    r = Rig()
    r.construction_data()
    r.mem.write(r.obj + 0x900, 4, progress)
    r.mem.write(r.obj + 0xE, 1, 1)
    r.run_building()
    assert bool(r.rectangles) == rectangle
    assert bool(r.called(STATE, "virtual_calls")) == completed
    if rectangle:
        assert r.mem.read(r.obj + 0xE, 1) == 0


def test_excluded_construction_requires_animation_before_class_resampling() -> None:
    r = Rig()
    r.construction_data()
    r.kind(0x46)
    r.mem.write(r.obj + 0x28, 8, 0)
    r.run_building()
    assert not r.called(0x140BB9290) and not r.rectangles


@pytest.mark.parametrize(
    ("kind", "flag", "expected"), [(0x32, 0, 30), (0x4A3, 1, 66), (0x761, 0, 13)]
)
def test_normal_staged_progress_low_byte_mapping(kind: int, flag: int, expected: int) -> None:
    r = Rig()
    r.construction_data()
    r.kind(kind)
    r.mem.write(r.obj + 0x980, 1, flag)
    r.mem.write(r.master + 0x428, 1, 10)
    r.run_building()
    assert r.called(STAGE) == [(r.obj, expected)]
    assert not r.rectangles


def test_stage_type_is_reloaded_after_threshold_callback() -> None:
    r = Rig()
    r.construction_data()
    r.kind(0x32)
    r.mem.write(r.master + 0x428, 1, 20)

    def threshold(args: tuple[int, ...]) -> int:
        r.kind(0x761)
        return 100

    r.handlers["calls", 0x140BB9290] = threshold
    r.run_building()
    assert r.called(STAGE) == [(r.obj, 23)]


@pytest.mark.parametrize(("excluded", "blocked"), [(False, False), (False, True), (True, False)])
def test_completion_threshold_and_normal_linked_pointer_gate(excluded: bool, blocked: bool) -> None:
    r = Rig()
    r.construction_data(100.0)
    if excluded:
        r.kind(0x46)
    if blocked:
        r.mem.write(r.obj + 0x868, 8, r.other)
    r.run_building()
    assert r.called(STATE, "virtual_calls") == ([] if blocked else [(r.obj, 2)])


def test_normal_unit_annotation_refuses_after_state_read_before_queue_read() -> None:
    r = Rig()
    r.handlers["calls", UNIT] = lambda args: None
    with pytest.raises(ValueError, match="Unit AL"):
        r.run_building()
    assert r.events[-1][:3] == ("r", r.obj + 0x188, 1)
    assert not any(e[:3] == ("r", r.obj + 0x850, 8) for e in r.events)


def test_excluded_unit_tail_result_is_forwarded_and_skips_postpasses() -> None:
    r = Rig()
    r.object_class(0x1B)
    result = 123456789012345

    def parent(args: tuple[int, ...]) -> int:
        r.kind(0x765)
        return result

    r.handlers["calls", UNIT] = parent
    assert r.run_building() is result
    assert not r.called(PROD_RUN) and not r.called(PROD_RESET) and not r.called(LOOKUP)


@pytest.mark.parametrize("state", [1, 3])
def test_production_branch_keeps_state_comparison_across_queue_pointer_read(state: int) -> None:
    r = Rig()
    r.mem.write(r.obj + 0x188, 1, state)

    def mutate(at: int, width: int, value: int) -> None:
        if at == r.obj + 0x850:
            r.mem.write(r.obj + 0x188, 1, 3 if state == 1 else 1)

    r.after_read = mutate
    r.run_building()
    assert bool(r.called(PROD_RUN)) == (state == 1)
    assert bool(r.called(PROD_RESET)) == (state == 3)


def test_high_state_uses_actual_clear_and_frees_owned_production_nodes() -> None:
    r = Rig()
    stack = r.stack
    r.stack = r.queue
    nodes, actions = r.nodes([0, 0])
    r.stack = stack
    r.mem.write(r.obj + 0x188, 1, 3)
    r.run_building()
    assert r.called(CLEAR) == [(r.queue,)]
    for at in nodes + actions:
        with pytest.raises(ReplayMemoryError):
            r.mem.read(at, 1)
    assert r.called(PROD_RESET) == [(r.obj,)]


def test_aggregation_removes_missing_id_skips_shifted_entry_and_uses_actual_memmove() -> None:
    r = Rig()
    r.kind(0x765)
    ids = r.alloc(12)
    for index, value in enumerate((101, 102, 103)):
        r.mem.write(ids + index * 4, 4, value)
    r.mem.write(r.obj + 0x828, 8, ids)
    r.mem.write(r.obj + 0x830, 8, ids + 12)
    r.mem.write(r.other + 0x168, 4, bits(7.0))
    _, actions = r.nodes([0])
    r.handlers["calls", LOOKUP] = lambda args: 0 if args[1] == 101 else r.other
    r.run_building()
    assert r.called(LOOKUP) == [(r.world, 101), (r.world, 103)]
    assert r.called(MOVE) == [(ids, ids + 4, 8)]
    assert [r.mem.read(ids + i * 4, 4) for i in range(2)] == [102, 103]
    assert r.mem.read(r.obj + 0x830, 8) == ids + 8
    assert r.called(TASK, "task_fp_calls") == [(actions[0], bits(7.0))]
    assert r.mem.read(r.obj + 0x168, 4) == 0


def test_aggregate_holds_task_stack_before_zeroing_own_amount() -> None:
    r = Rig()
    r.kind(0x769)
    _, actions = r.nodes([0])
    r.mem.write(r.obj + 0x168, 4, bits(7.0))

    def mutate(at: int, width: int, value: int) -> None:
        if at == r.obj + 0x168:
            r.mem.write(r.obj + 0x420, 8, 0)

    r.after_write = mutate
    r.run_building()
    assert r.called(TASK, "task_fp_calls") == [(actions[0], 0)]


def test_actual_object_list_building_unit_combat_action_and_movement_compose() -> None:
    r = Rig()
    r.real_unit, r.real_combat, r.real_action, r.real_parent = True, True, True, True
    r.visible()
    r.mem.write(r.obj + 0x400, 8, r.motion)
    r.mem.write(r.table + 0x30, 8, BUILDING)
    header, data = r.alloc(0x20), r.alloc(8)
    r.mem.write(header + 8, 8, data)
    r.mem.write(header + 0x10, 4, 1)
    r.mem.write(data, 8, r.obj)
    objects = bind_replay_object_update(r.context, r.building, profile=ReplayObjectUpdateProfile(1))
    assert objects.call is not None and objects.call(0x141229A20, (header,), None) is None
    assert r.called(BASE) == [(r.obj,)] and r.called(UNIT) == [(r.obj,)]
    assert r.mem.read(r.obj + 0x198, 4) == 93
    assert r.mem.read(r.obj + 0x350, 4) == bits(3.0)
    assert len(r.called(CLOCK)) == 5


@pytest.mark.parametrize("channel", CHANNELS)
def test_missing_category_refuses_at_exact_reached_prefix(channel: str) -> None:
    r = Rig()
    if channel == "virtual_calls":
        r.mem.write(r.obj + 0x948, 1, 1)
        r.mem.write(r.obj + 0x18B, 1, 1)
        target = REGISTER_OUT
    elif channel == "member_fp_home_calls":
        r.active_building()
        r.set_health(bits(1.0))
        r.make_members(1)
        target = DETACH
    elif channel == "task_fp_calls":
        r.active_building()
        r.nodes([0])
        r.mem.write(r.obj + 0x95C, 1, 1)
        r.mem.write(r.resource + 0x768, 8, encoded(bits(2.0)))
        target = TASK
    elif channel in ("resource_fp_home_calls", "resource_event_home_calls"):
        r.resource_data()
        target = CREDIT if channel == "resource_fp_home_calls" else EVENT
    elif channel == "repair_fp_calls":
        r.active_building(1000)
        r.make_members(1)
        r.mem.write(r.master + 0x460, 4, bits(2.0))
        target = 0x1412C8D20
    else:
        r.construction_data()
        target = RECT
    r.building = r.bind_building(**{channel: ReplayTaskRebuildCalls(None)})
    with pytest.raises(UnresolvedReplayTaskRebuild, match=f"reached{target:x} is unavailable"):
        r.run_building()
    assert not r.live


def test_invalid_capabilities_and_mxcsr_refuse_before_effects() -> None:
    r = Rig()
    with pytest.raises(ValueError):
        r.bind_building(resource_fp_home_calls=cast(ReplayTaskRebuildCalls, None))
    for mxcsr in (True, 0, 0x1F81, 0x3F80):
        with pytest.raises(ValueError):
            bind_replay_building_object_update(
                r.context,
                r.ordinary_calls,
                **{name: ReplayTaskRebuildCalls(None) for name in CHANNELS},
                bind_local=r.local,
                profile=r.building_profile,
                mxcsr=mxcsr,
            )
    assert not r.events
