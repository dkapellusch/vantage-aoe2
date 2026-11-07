"""Source controls using owned memory, actual inherited ports and typed effects.

ActionRig supplies the already tested Base/Moving/clock/node environment.
Configuration,ownership,visibility publication and script effects remain
explicit authored services; no real recording World or target code is run.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import cast

import pytest
from test_replay_action_object_update import (
    ACTION,
    BASE,
    CLOCK,
    LOG,
    RESUME,
    U32,
    U64,
)
from test_replay_action_object_update import (
    Rig as ActionRig,
)

from vantage.replay_combat_object_update import (
    ReplayCombatObjectUpdateProfile,
    bind_replay_combat_object_update,
)
from vantage.replay_formation_member_children import (
    ReplayFormationMemberChildrenProfile,
    bind_replay_formation_member_children,
)
from vantage.replay_memory import ReplayMemoryError
from vantage.replay_object_update import (
    ReplayObjectUpdateProfile,
    bind_replay_object_update,
)
from vantage.replay_player_color_context import read_replay_player_color_observer
from vantage.replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    UnresolvedReplayTaskRebuild,
)
from vantage.replay_world_postpasses import (
    ReplayWorldPostpassesProfile,
    bind_replay_world_postpasses,
)

COMBAT, HAS, OBSERVER, SELECTED, ELAPSED = (
    0x14114C3A0,
    0x140B88B30,
    0x140D6AED0,
    0x141608320,
    0x141604210,
)
BITS, TOP, COUNT, PLAYER = 0x14188E440, 0x140B88AF0, 0x141603EF0, 0x141603F60
CONFIG, RELEASE_CONFIG, CONFIG_FLAG, PUBLISH = 0x140D6A530, 0x140990140, 0x1413D5580, 0x141357E10
EXPIRES, RESET, INSTALL, TRANSFER, DESCRIPTOR, SCRIPT = (
    0xF10268,
    0xF10260,
    0xF10098,
    0xF10078,
    0xF100A8,
    0xF11020,
)
CHANNELS = (
    "virtual_calls",
    "logger_home_calls",
    "config_home_calls",
    "virtual_home_calls",
    "visibility_fp_home_calls",
)
DATA = Path(__file__).resolve().parents[1] / "artifacts/game-internals/2026-10-18-world-envelope"


class Rig(ActionRig):
    def __init__(self) -> None:
        super().__init__()
        self.action = self.bound
        self.real_action = False
        self.action_result = 0x123400000005
        self.expiry = 0
        self.player_count = 3
        self.config_enabled = 1
        self.alliance = 1
        self.config_handles: list[int] = []
        old_world, old_resource = self.world, self.resource
        self.world, self.resource = self.alloc(0xA00), self.alloc(0x6000)
        self.mem.write_bytes(self.world, self.mem.read_bytes(old_world, 0x300))
        self.mem.write_bytes(self.resource, self.mem.read_bytes(old_resource, 0x900))
        self.mem.write(self.owner + 8, 8, self.world)
        self.mem.write(self.owner + 0x98, 8, self.resource)
        self.mem.write(self.world + 0x98, 8, self.resource)
        self.mem.write(self.owner + 0x648, 4, 1)
        self.mem.write(self.game + 0x5C0, 8, self.world)
        self.gaia, self.player2 = self.alloc(0xA00), self.alloc(0xA00)
        self.players = [self.gaia, self.owner, self.player2]
        self.player_array = self.alloc(48)
        self.player_table, self.script_table = self.alloc(0xB0), self.alloc(0x28)
        self.script_obj = self.alloc(8)
        self.mem.write(self.script_obj, 8, self.script_table)
        self.mem.write(self.script_table + 0x20, 8, SCRIPT)
        self.mem.write(self.player_table + 0xA8, 8, DESCRIPTOR)
        self.masters: list[int] = []
        for index, player in enumerate(self.players):
            self.mem.write(player, 8, self.player_table)
            self.mem.write(player + 8, 8, self.world)
            self.mem.write(player + 0x10, 4, 3)
            self.mem.write(player + 0x98, 8, self.resource)
            self.mem.write(player + 0x648, 4, index)
            masters = self.alloc(0x4008) + 8
            self.masters.append(masters)
            self.mem.write(player + 0x28, 8, masters)
            for kind in (0, 0x52, 0x6DE):
                self.mem.write(masters + kind * 8, 8, 1)
            self.mem.write(self.player_array + index * 16, 8, player)
        for at, width, value in (
            (self.world + 0x768, 8, self.player_array),
            (self.world + 0x770, 8, self.player_array + 48),
            (self.world + 0x188, 4, 1),
            (self.world + 0x190, 4, 41),
            (self.table + 0x268, 8, EXPIRES),
            (self.table + 0x260, 8, RESET),
            (self.table + 0x98, 8, INSTALL),
            (self.table + 0x78, 8, TRANSFER),
            (self.obj + 0x418, 4, 0x40000000),
        ):
            self.mem.write(at, width, value)
        for at, size, value in (
            (0x1443C9920, 8, 0xABCDEF),
            (0x1442C3FA3, 1, 0),
            (0x143DA5054, 4, U32),
        ):
            self.mem.map_bytes(at, value.to_bytes(size, "little"))
        constant = DATA / "combat-object-update-source-v1/default-graphic-rate-1432a85d8.bin"
        self.mem.map_bytes(0x1432A85D8, constant.read_bytes())
        self.grid = self.alloc(0x20)
        self.cells = self.alloc(32 * 8) + 8 * 8
        self.footprints = self.alloc(8)
        self.mem.write(self.resource + 0x5BC8, 8, self.grid)
        self.mem.write(self.resource + 0x5BA8, 8, self.footprints)
        self.mem.write(self.grid, 8, self.cells)
        self.mem.write(self.grid + 0x10, 4, 4)
        self.mem.write(self.grid + 0x14, 4, 4)
        self.cfg, self.cfg_cell = self.alloc(0x50), self.alloc(8)
        self.mem.write(self.cfg_cell, 8, self.cfg)
        self.observer_cell, self.descriptor = self.alloc(8), self.alloc(0x30)
        self.mem.write(self.observer_cell, 8, self.gaia)
        self.coords(self.other)
        unavailable = ReplayTaskRebuildCalls(None)
        self.post = bind_replay_world_postpasses(
            self.context,
            self.ordinary_calls,
            visibility_calls=unavailable,
            fog_home_calls=unavailable,
            player_event_home_calls=unavailable,
            resource_home_calls=unavailable,
            state_byte_calls=unavailable,
            rule_event_home_calls=unavailable,
            bind_local=self.local,
            mxcsr=0x1F80,
            profile=ReplayWorldPostpassesProfile(
                bytes(0xF0), bytes(0xD0), bytes(0x34), bytes(0x54)
            ),
        )
        self.members = bind_replay_formation_member_children(
            self.context,
            self.ordinary_calls,
            bind_local=self.local,
            mxcsr=0x1F80,
            profile=ReplayFormationMemberChildrenProfile(bytes(0x58), bytes(0x40), bytes(0x48)),
        )
        self.combat_profile = ReplayCombatObjectUpdateProfile(bytes([0xA4]) * 0x120)
        self.combat = self.bind_combat()

    def coords(self, obj: int, x: int = 0, y: int = 0) -> None:
        self.mem.write(obj + 0x170, 8, (x - 0x4C3FBA69E4EA7FD1 + 0x183CAC30D2441D0E) & U64)
        self.mem.write(obj + 0x178, 8, (y - 0x6C5EAB60B426DD28 + 0x61501AA6ECFD980A) & U64)

    def visible(self, mask: int = 1) -> None:
        self.mem.write(self.obj + 0x138, 8, self.alloc(8))
        self.mem.write(self.cells, 8, mask)

    def footprint(self, offsets: list[tuple[int, int]], *, other: bool = False) -> None:
        data = self.alloc(8 + len(offsets) * 8)
        self.mem.write(data, 4, len(offsets))
        for index, (x, y) in enumerate(offsets, 1):
            self.mem.write(data + index * 8, 4, x & U32)
            self.mem.write(data + index * 8 + 4, 4, y & U32)
        self.mem.write(self.footprints, 8, data)
        self.mem.write((self.other if other else self.obj) + 0x4FC, 1, 1)
        if other:
            self.mem.write(self.master + 8, 1, 0x50)
            self.mem.write(self.obj + 0x868, 8, self.other)

    def bind_combat(self, **overrides: ReplayTaskRebuildCalls) -> ReplayTaskRebuildCalls:
        channels = {name: ReplayTaskRebuildCalls(self.channel(name)) for name in CHANNELS}
        channels.update(overrides)
        return bind_replay_combat_object_update(
            self.context,
            self.ordinary_calls,
            **channels,
            bind_local=self.local,
            profile=self.combat_profile,
            mxcsr=0x1F80,
        )

    def ordinary(self, target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        targets = (
            ACTION,
            BITS,
            TOP,
            COUNT,
            PLAYER,
            CONFIG_FLAG,
            RELEASE_CONFIG,
            0x140D6AD50,
            0x141603D70,
            0x141604060,
            0x1410F6800,
            0x1410D3AB0,
            0x14110DF30,
            0x14114A140,
            0x1416F3150,
            0x141604010,
            0x140D866C0,
            0x140B27590,
            0x140FFD0A0,
            0x1415A3480,
            0x140D42470,
        )
        if target not in targets:
            return super().ordinary(target, args, data)
        assert data is None
        if handler := self.record("calls", target, args):
            return handler(args)
        if target == ACTION:
            if self.real_action:
                assert self.action.call is not None
                return self.action.call(target, args, None)
            return self.action_result
        if target == BITS:
            assert self.post.call is not None
            return self.post.call(target, args, None)
        if target == TOP:
            assert self.members.call is not None
            return self.members.call(target, args, None)
        if target == 0x140D6AD50:
            assert self.reader.call is not None
            return self.reader.call(target, args, None)
        if target == 0x141603D70:
            return read_replay_player_color_observer(self.context, args[0])
        if target == COUNT:
            return self.player_count
        if target == PLAYER:
            return self.players[args[1]]
        if target == CONFIG_FLAG:
            return self.config_enabled
        if target == RELEASE_CONFIG:
            self.mem.free(args[0])
            return None
        if target in (0x141604060, 0x14114A140, 0x140FFD0A0):
            return 0
        if target == 0x1416F3150:
            return self.world
        if target == 0x141604010:
            return self.observer_cell
        if target == 0x140D866C0:
            return self.alliance
        return None

    def channel(
        self, channel: str
    ) -> Callable[[int, tuple[int, ...], memoryview | None], int | None]:
        fallback = super().channel(channel)

        def dispatch(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
            local = (
                channel == "virtual_calls" and target in (EXPIRES, RESET, INSTALL, TRANSFER, SCRIPT)
            ) or channel in ("config_home_calls", "virtual_home_calls", "visibility_fp_home_calls")
            if not local:
                return fallback(target, args, data)
            assert data is None
            if handler := self.record(channel, target, args):
                return handler(args)
            if channel == "config_home_calls" and target == CONFIG:
                handle = self.alloc(8)
                self.mem.write(handle, 8, 1)
                self.config_handles.append(handle)
                self.mem.write(args[1], 8, handle)
                return self.cfg_cell
            if channel == "virtual_home_calls" and target == DESCRIPTOR:
                self.mem.write(args[1], 8, self.descriptor)
                return self.descriptor
            if channel == "visibility_fp_home_calls" and target == PUBLISH:
                return None
            if channel == "virtual_calls":
                if target == EXPIRES:
                    return self.expiry
                if target == TRANSFER:
                    self.mem.write(args[0] + 0x18, 8, args[1])
                return None
            raise UnresolvedReplayTaskRebuild(f"authored {channel} missing{target:x}")

        return dispatch

    def run_combat(self, target: int = COMBAT, *args: int) -> int | None:
        assert self.combat.call is not None
        return self.combat.call(target, args or (self.obj,), None)


def test_profile_is_explicit_immutable_exact_prefix() -> None:
    for seed in (b"", bytes(0x121), bytearray(0x120)):
        with pytest.raises(ValueError):
            ReplayCombatObjectUpdateProfile(cast(bytes, seed))


@pytest.mark.parametrize(
    ("target", "arity"), [(COMBAT, 1), (HAS, 1), (OBSERVER, 1), (SELECTED, 2), (ELAPSED, 2)]
)
def test_addressed_shape_refuses_before_effects(target: int, arity: int) -> None:
    r = Rig()
    assert r.combat.call is not None
    args = (r.obj,) * arity
    for given, data in (((), None), ((-1,) * arity, None), (args, memoryview(b"raw"))):
        with pytest.raises(ValueError):
            r.combat.call(target, given, data)
    assert not r.events


def test_unknown_dispatch_preserves_arguments_payload_and_return_identity() -> None:
    r = Rig()
    args, payload, result = (-1, 4), memoryview(b"raw"), 123456789012345

    def unknown(target: int, given: tuple[int, ...], data: memoryview | None) -> int:
        assert target == 17 and given is args and data is payload
        return result

    r.ordinary_calls = ReplayTaskRebuildCalls(unknown)
    bound = r.bind_combat()
    assert bound.call is not None and bound.call(17, args, payload) is result


@pytest.mark.parametrize("head", [0, 0xFFFFFFFFFFFFFFFF])
def test_has_only_tests_current_head_without_dereferencing(head: int) -> None:
    r = Rig()
    r.mem.write(r.stack + 0x10, 8, head)
    assert r.run_combat(HAS, r.stack) == int(head != 0)


@pytest.mark.parametrize(("index", "selected"), [(1, True), (0, False), (0x100000001, True)])
def test_selected_uses_low_edx_word_and_returns_known_eax(index: int, selected: bool) -> None:
    r = Rig()
    assert r.run_combat(SELECTED, r.world, index) == int(selected)


@pytest.mark.parametrize("index", [0, 1, U32, 0x100000001])
def test_elapsed_uses_signed_low_edx_index_and_raw_dword(index: int) -> None:
    r = Rig()
    signed = (index & U32) - (1 << 32) if index & 0x80000000 else index & U32
    r.mem.write(r.world + 0x18C + signed * 4, 4, U32)
    assert r.run_combat(ELAPSED, r.world, index) == U32


def test_observer_null_and_actual_existing_tail() -> None:
    r = Rig()
    assert r.run_combat(OBSERVER, r.game) == r.gaia
    assert r.called(0x141603D70) == [(r.world,)]
    r.mem.write(r.game + 0x5C0, 8, 0)
    assert r.run_combat(OBSERVER, r.game) == 0
    assert len(r.called(0x141603D70)) == 1


def test_default_path_always_reads_graphic_coordinates_and_four_clocks() -> None:
    r = Rig()
    assert r.run_combat() == 5
    assert r.called(CLOCK) == [(r.world,)] * 4
    assert r.called(ACTION) == [(r.obj,)]
    assert ("r", 0x1432A85D8, 4, 0x7FC00000) in r.events
    assert sum(e[:3] == ("r", r.obj + 0x180, 8) for e in r.events) == 2
    assert not r.called(BITS) and not r.live


def test_initial_log_home_store_precedes_current_logger_read_and_keeps_padding() -> None:
    r = Rig()
    r.mem.write(0x14435505B, 1, 1)

    def mutate(at: int, width: int, value: int) -> None:
        if r.live and at == r.frame(0x120) + 0x20:
            r.mem.write(0x144355068, 8, 0x1234)

    def logger(args: tuple[int, ...]) -> None:
        if args[2] == 0x1432A7D00:
            assert args[:4] == (0x1234, 0x23, 0x1432A7D00, 0)
            assert r.mem.read(args[4], 8) == 0
            assert r.mem.read_bytes(r.frame(0x120) + 0xB8, 8) == bytes(4) + b"\xa4" * 4
        elif args[2] == 0x1432A7D20:
            array = r.mem.read(args[4], 8)
            node = r.mem.read(array + 8, 8)
            assert r.mem.read_bytes(node, 8) == bytes.fromhex("0000c07f") + b"\xa4" * 4
            assert r.mem.read(node + 8, 4) == 10

    r.after_write = mutate
    r.handlers["logger_home_calls", LOG] = logger
    r.run_combat()


@pytest.mark.parametrize(
    ("start", "expected"),
    [
        (0x40400000, 0x40200000),
        (0x3E800000, 0),
        (0, 0),
        (0x80000000, 0x80000000),
        (0xBF800000, 0xBF800000),
        (0x7FC12345, 0x7FC12345),
        (0x7F800000, 0x7F800000),
    ],
)
def test_cooldown_uses_raw_fp_strict_positive_and_negative_clamp(start: int, expected: int) -> None:
    r = Rig()
    r.mem.write(r.obj + 0x514, 4, start)
    r.run_combat()
    assert r.mem.read(r.obj + 0x514, 4) == expected


@pytest.mark.parametrize(
    ("expiry", "reset"), [(0, False), (99, True), (100, False), (101, False), (U32, False)]
)
def test_expiry_uses_unsigned_clock_comparison_and_current_reset_target(
    expiry: int, reset: bool
) -> None:
    r = Rig()
    r.expiry = expiry
    r.mem.write(r.obj + 0xF, 1, 0x46)
    r.mem.write(r.obj + 0x68C, 1, 77)

    def mutate(at: int, width: int, value: int) -> None:
        if at == r.obj + 0x68C:
            r.mem.write(r.table + 0x260, 8, 0xEE0260)

    r.after_write = mutate
    r.handlers["virtual_calls", 0xEE0260] = lambda args: None
    r.run_combat()
    assert r.called(0xEE0260, "virtual_calls") == ([(r.obj, 0)] if reset else [])
    assert r.mem.read(r.obj + 0x68C, 1) == (0 if reset else 77)


def test_master_expiry_uses_actual_clocks_and_top_then_resumes_real_action() -> None:
    r = Rig()
    _, actions = r.nodes([0])
    old = r.alloc(0x600)
    r.mem.write(r.obj + 0x500, 8, old)
    r.mem.write(r.obj + 0x50C, 4, 50)
    r.mem.write(r.obj + 0x510, 4, 50)
    r.run_combat()
    assert r.called(INSTALL, "virtual_calls") == [(r.obj, old, 1)]
    assert len(r.called(0x140D6AD50)) == 2
    assert r.mem.read(r.obj + 0x500, 8) == 0
    assert r.called(TOP) == [(r.stack,)]
    assert r.called(RESUME, "virtual_calls") == [(actions[0], 0)]


def test_repeated_expiry_sample_can_cancel_install_after_first_gate_passed() -> None:
    r = Rig()
    old = r.alloc(0x600)
    r.mem.write(r.obj + 0x500, 8, old)
    r.mem.write(r.obj + 0x50C, 4, 50)
    values = iter((100, 40))
    r.handlers["calls", 0x140D6AD50] = lambda args: next(values)
    r.run_combat()
    assert not r.called(INSTALL, "virtual_calls")
    assert r.mem.read(r.obj + 0x500, 8) == old


def test_master_group_effects_reload_ids_and_clear_before_install() -> None:
    r = Rig()
    group, old = r.alloc(8), r.alloc(0x600)
    r.mem.write(r.obj + 0x500, 8, old)
    r.mem.write(r.obj + 0x50C, 4, 1)
    r.handlers["calls", 0x141604060] = lambda args: group

    def detach(args: tuple[int, ...]) -> None:
        assert args == (group, 100, U32, 0)
        r.mem.write(r.obj + 8, 4, 200)

    def install(args: tuple[int, ...]) -> None:
        assert args == (r.obj, old, 1)
        assert r.mem.read(r.obj + 0x500, 8) == 0
        r.mem.write(r.obj + 8, 4, 300)

    r.handlers["calls", 0x1410F6800] = detach
    r.handlers["virtual_calls", INSTALL] = install
    r.run_combat()
    assert r.called(0x1410D3AB0) == [(group, 300, U32, 0)]
    assert r.called(0x14110DF30) == [(group, 300)]


@pytest.mark.parametrize("equal", [False, True])
def test_expired_master_null_or_equal_current_master_skips_second_time_sample(equal: bool) -> None:
    r = Rig()
    r.mem.write(r.obj + 0x50C, 4, 1)
    r.mem.write(r.obj + 0x500, 8, r.master if equal else 0)
    r.run_combat()
    assert len(r.called(0x140D6AD50)) == 1
    assert not r.called(INSTALL, "virtual_calls")


def test_visibility_publication_has_eleven_annotations_and_partial_live_homes() -> None:
    r = Rig()
    r.visible()
    r.object_class(0xFFFF)
    r.mem.write(r.master + 0x78, 4, 0x3F800000)
    r.mem.write(r.master + 0x7C, 4, 0x40000000)

    def publish(args: tuple[int, ...]) -> None:
        assert len(args) == 11
        assert args[:4] == (0xABCDEF, 100, 1, 0)
        assert [
            r.mem.read(at, width) for at, width in zip(args[4:], (4, 4, 4, 4, 8, 8, 8), strict=True)
        ] == [0, 0x3F800000, 0x40000000, U32, 0, 1, r.obj + 0x4A8]
        assert r.mem.read_bytes(args[4], 8)[4:] == b"\xa4" * 4
        assert r.mem.read_bytes(args[7], 8)[4:] == b"\xa4" * 4

    r.handlers["visibility_fp_home_calls", PUBLISH] = publish
    r.run_combat()
    assert r.mem.read(r.obj + 0x4F0, 8) == 1


def test_normal_footprint_skips_out_of_bounds_and_merges_valid_cells() -> None:
    r = Rig()
    r.visible()
    r.footprint([(-1, 0), (0, -1), (4, 0), (0, 4), (1, 0), (0, 1)])
    r.mem.write(r.cells - 8, 8, 0x80)
    r.mem.write(r.cells + 8, 8, 2)
    r.mem.write(r.cells + 4 * 8, 8, 4)
    r.run_combat()
    assert len(r.called(BITS)) == 3
    assert r.mem.read(r.obj + 0x4F0, 8) == 7


def test_other_object_footprint_does_not_add_normal_bounds_checks() -> None:
    r = Rig()
    r.visible()
    r.footprint([(-1, 0)], other=True)
    r.mem.write(r.cells - 8, 8, 8)
    r.run_combat()
    assert r.mem.read(r.obj + 0x4F0, 8) == 9


@pytest.mark.parametrize("x", [0x7FC12345, 0x7F800000, 0xFF800000, 0x4F000000])
def test_base_visibility_lookup_uses_cvtt_indefinite_and_signed_index_without_new_clamp(
    x: int,
) -> None:
    r = Rig()
    r.visible()
    r.coords(r.obj, x)
    r.mem.map_bytes(r.cells - (1 << 31) * 8, (2).to_bytes(8, "little"))
    r.run_combat()
    assert r.mem.read(r.obj + 0x4F0, 8) == 2


def test_current_saved_old_mask_home_can_suppress_publish() -> None:
    r = Rig()
    r.visible(3)

    def bits(args: tuple[int, ...]) -> int:
        r.mem.write(r.frame(0x120) + 0x68, 8, 3)
        return r.mem.read(args[0], 8)

    r.handlers["calls", BITS] = bits
    r.run_combat()
    assert not r.called(PUBLISH, "visibility_fp_home_calls")


@pytest.mark.parametrize(("other", "expected"), [(False, 10), (True, 3)])
def test_footprint_other_accumulator_is_held_but_normal_uses_current_mask(
    other: bool, expected: int
) -> None:
    r = Rig()
    r.visible()
    r.footprint([(1, 0)], other=other)
    r.mem.write(r.cells + 8, 8, 2)
    writes = 0

    def mutate(at: int, width: int, value: int) -> None:
        nonlocal writes
        if at == r.obj + 0x4F0:
            writes += 1
            if writes == 1:
                r.mem.write(at, 8, 8)

    r.after_write = mutate
    r.run_combat()
    assert r.mem.read(r.obj + 0x4F0, 8) == expected


@pytest.mark.parametrize("footprint", [False, True])
def test_prestate_byte_home_reload_is_branch_specific(footprint: bool) -> None:
    r = Rig()
    r.visible()
    if footprint:
        r.footprint([])

    def bits(args: tuple[int, ...]) -> int:
        r.mem.write(r.frame(0x120) + 0x61, 1, 7)
        r.mem.write(r.obj + 0x188, 1, 7)
        r.mem.write(0x14435505B, 1, 1)
        return r.mem.read(args[0], 8)

    r.handlers["calls", BITS] = bits
    r.run_combat()
    formats = [args[2] for args in r.called(LOG, "logger_home_calls")]
    assert (0x1432A7EF0 if footprint else 0x1432A7EA0) in formats


@pytest.mark.parametrize("visible", [False, True])
def test_parent_byte_home_is_refreshed_only_after_visibility_path(visible: bool) -> None:
    r = Rig()
    if visible:
        r.visible()

    def mutate(at: int, width: int, value: int) -> None:
        if r.live and at == r.frame(0x120) + 0x60 and width == 1:
            r.mem.write(at, 1, 0xA5)

    r.after_write = mutate
    assert r.run_combat() == (0xA5 if visible else 5)


def test_publish_holds_owner_before_homes_and_loads_receiver_after_current_id() -> None:
    r = Rig()
    r.visible()

    def mutate(at: int, width: int, value: int) -> None:
        frame = r.frame(0x120)
        if at == frame + 0x50:
            r.mem.write(r.obj + 0x18, 8, r.player2)
            r.mem.write(r.owner + 0x648, 4, 7)
        elif at == frame + 0x20 and width == 4:
            r.mem.write(r.obj + 8, 4, 88)

    def read(at: int, width: int, value: int) -> None:
        if at == r.obj + 8 and value == 88:
            r.mem.write(0x1443C9920, 8, 0x2222)

    r.after_write, r.after_read = mutate, read
    r.run_combat()
    assert r.called(PUBLISH, "visibility_fp_home_calls")[0][:4] == (0x2222, 88, 7, 0)


def test_visibility_masks_reserved_bits_before_comparing() -> None:
    r = Rig()
    r.visible(U64)
    r.mem.write(r.obj + 0x4F0, 8, 0x01FFFFFF01FFFFFF)
    r.run_combat()
    assert not r.called(PUBLISH, "visibility_fp_home_calls")


def test_owner_transfer_releases_config_and_uses_actual_observer_tail_and_ui() -> None:
    r = Rig()
    r.visible(4)
    r.mem.write(r.obj + 0x51C, 1, 1)
    r.mem.write(r.world + 0x6B0, 4, 2)
    hud = r.alloc(8)
    r.handlers["calls", 0x140FFD0A0] = lambda args: hud
    r.run_combat()
    assert r.mem.read(r.obj + 0x18, 8) == r.player2
    assert r.mem.read(r.obj + 0x51C, 1) == 0
    assert r.called(0x140B27590) == [(0x1432A7DC8, 7, 0)]
    assert r.called(0x1415A3480) == [(hud, 100)]
    assert r.called(0x141603D70) == [(r.world,)]
    for at in r.config_handles:
        with pytest.raises(ReplayMemoryError):
            r.mem.read(at, 1)


def test_missing_owner_master_entry_ends_search_without_clearing_transfer_state() -> None:
    r = Rig()
    r.visible(4)
    r.mem.write(r.obj + 0x51C, 1, 1)
    r.mem.write(r.masters[2], 8, 0)
    r.run_combat()
    assert not r.called(TRANSFER, "virtual_calls")
    assert r.mem.read(r.obj + 0x51C, 1) == 1
    assert r.called(PLAYER) == [(r.world, 1), (r.world, 2), (r.world, 2)]


@pytest.mark.parametrize(
    ("enabled", "kind", "setting", "alliance", "flag", "eligible"),
    [
        (1, 3, 0, 1, 0, True),
        (0, 0, 0, 1, 0, True),
        (0, 3, 0, 1, 0, False),
        (0, 3, 0, 1, 1, True),
        (0, 3, 1, 0, 0, True),
        (0, 3, 1, 1, 0, False),
        (0, 3, 1, 1, 1, True),
    ],
)
def test_owner_eligibility_uses_config_type_setting_alliance_and_player_flag(
    enabled: int, kind: int, setting: int, alliance: int, flag: int, eligible: bool
) -> None:
    r = Rig()
    r.visible(4)
    r.mem.write(r.obj + 0x51C, 1, 1)
    r.mem.write(r.player2 + 0x10, 4, kind)
    r.mem.write(r.player2 + 0x5A0, 1, flag)
    r.mem.write(0x1442C3FA3, 1, setting)
    r.config_enabled, r.alliance = enabled, alliance
    r.run_combat()
    assert bool(r.called(TRANSFER, "virtual_calls")) == eligible
    assert len(r.called(RELEASE_CONFIG)) == 2


def test_player_count_is_reread_after_each_eligibility_callback() -> None:
    r = Rig()
    r.visible(4)
    r.mem.write(r.obj + 0x51C, 1, 1)

    def config(args: tuple[int, ...]) -> int:
        r.player_count = 2
        return 1

    r.handlers["calls", CONFIG_FLAG] = config
    r.run_combat()
    assert r.called(PLAYER) == [(r.world, 1)]
    assert not r.called(TRANSFER, "virtual_calls")


def test_config_release_uses_current_local_control_after_predicate_callback() -> None:
    r = Rig()
    r.visible(4)
    r.mem.write(r.obj + 0x51C, 1, 1)
    r.player_count = 2
    replacement = r.alloc(8)

    def predicate(args: tuple[int, ...]) -> int:
        r.mem.write(r.frame(0x120) + 0xC8, 8, replacement)
        return 1

    r.handlers["calls", CONFIG_FLAG] = predicate
    r.run_combat()
    assert r.called(RELEASE_CONFIG) == [(replacement,)]
    assert r.mem.read(r.config_handles[0], 8) == 1
    with pytest.raises(ReplayMemoryError):
        r.mem.read(replacement, 1)


@pytest.mark.parametrize(
    ("kind", "mode", "candidate", "expected"),
    [(0x52, 12, True, 1), (0x52, 11, True, 0), (0, 12, True, 0), (0x52, 12, False, 0)],
)
def test_special_owner_sets_world_flag_only_after_exact_type_and_mode_gate(
    kind: int, mode: int, candidate: bool, expected: int
) -> None:
    r = Rig()
    r.kind(kind)
    r.mem.write(r.obj + 0x51C, 1, 2)
    r.mem.write(r.cfg + 0x34, 4, mode)
    r.handlers["calls", 0x14114A140] = lambda args: r.player2 if candidate else 0
    r.run_combat()
    assert r.mem.read(r.world + 0x8E0, 1) == expected
    assert len(r.called(RELEASE_CONFIG)) == int(candidate)


def test_special_config_missing_result_refuses_after_partial_local_flag_store() -> None:
    r = Rig()
    r.mem.write(r.obj + 0x51C, 1, 2)
    r.handlers["calls", 0x14114A140] = lambda args: r.player2
    r.handlers["config_home_calls", CONFIG] = lambda args: None
    with pytest.raises(ValueError, match="special owner config cell RAX"):
        r.run_combat()
    assert r.events[-1][0] == "w" and r.events[-1][2:] == (4, 1)
    assert not r.called(RELEASE_CONFIG) and not r.live


def test_neutral_type_holds_transfer_target_before_player_zero_call() -> None:
    r = Rig()
    r.kind(0x6DE)

    def player(args: tuple[int, ...]) -> int:
        assert args == (r.world, 0)
        r.mem.write(r.table + 0x78, 8, 0xEE0078)
        return r.gaia

    r.handlers["calls", PLAYER] = player
    r.run_combat()
    assert r.called(TRANSFER, "virtual_calls") == [(r.obj, r.gaia)]
    assert not r.called(0xEE0078, "virtual_calls")


@pytest.mark.parametrize(
    ("selected", "linked", "updated"), [(1, False, True), (0, False, False), (1, True, True)]
)
def test_script_uses_actual_selected_elapsed_leaves_and_linked_bool_gate(
    selected: int, linked: bool, updated: bool
) -> None:
    r = Rig()
    r.mem.write(r.obj + 0x1F0, 8, r.script_obj)
    r.mem.write(r.world + 0x188, 4, selected)
    r.mem.write(r.world + 0x190, 4, U32)
    r.nodes([0])
    if linked:
        r.mem.write(r.obj + 0xF, 1, 0x46)
        r.mem.write(r.obj + 0x148, 8, 1)
    r.run_combat()
    assert r.called(SCRIPT, "virtual_calls") == ([(r.script_obj, U32)] if updated else [])
    assert r.called(0x140D42470) == ([] if linked else [(r.script_obj, 1)])
    assert len(r.called(CLOCK)) == 6


def test_script_target_and_receiver_are_held_across_actual_elapsed_read() -> None:
    r = Rig()
    r.mem.write(r.obj + 0x1F0, 8, r.script_obj)

    def mutate(at: int, width: int, value: int) -> None:
        if at == r.world + 0x190:
            r.mem.write(r.script_table + 0x20, 8, 0xEE0020)
            r.mem.write(r.obj + 0x1F0, 8, 0)

    r.after_read = mutate
    r.run_combat()
    assert r.called(SCRIPT, "virtual_calls") == [(r.script_obj, 41)]
    assert not r.called(0xEE0020, "virtual_calls")


def test_final_world_is_held_before_state_read_and_log_format_before_clock_callback() -> None:
    r = Rig()
    other_world = r.alloc(0xA00)
    r.mem.write(other_world + 0x228, 8, r.clock)

    def mutate(at: int, width: int, value: int) -> None:
        if at == r.obj + 0x188 and len(r.called(CLOCK)) == 3:
            r.mem.write(r.owner + 8, 8, other_world)

    def clock(args: tuple[int, ...]) -> int:
        if len(r.called(CLOCK)) == 4:
            assert args == (r.world,)
            r.mem.write(r.obj + 0x188, 1, 7)
            r.mem.write(0x14435505B, 1, 1)
        return 100

    r.after_read = mutate
    r.handlers["calls", CLOCK] = clock
    r.run_combat()
    formats = [args[2] for args in r.called(LOG, "logger_home_calls")]
    assert 0x1432A7EF0 in formats and 0x1432A7EA0 not in formats


def test_signed_negative_id_skips_even_visibility_presence_read() -> None:
    r = Rig()
    r.visible()
    r.mem.write(r.obj + 8, 4, U32)
    assert r.run_combat() == 5
    assert not r.called(BITS)
    assert not any(e[:3] == ("r", r.obj + 0x138, 8) for e in r.events)


@pytest.mark.parametrize("channel", CHANNELS)
def test_missing_typed_effect_refuses_at_reached_prefix(channel: str) -> None:
    r = Rig()
    if channel == "logger_home_calls":
        r.mem.write(0x14435505B, 1, 1)
    elif channel in ("visibility_fp_home_calls", "virtual_home_calls"):
        r.visible(4)
        if channel == "virtual_home_calls":
            r.config_enabled, r.alliance = 0, 0
            r.mem.write(0x1442C3FA3, 1, 1)
            r.mem.write(r.obj + 0x51C, 1, 1)
    elif channel == "config_home_calls":
        r.mem.write(r.obj + 0x51C, 1, 2)
        r.handlers["calls", 0x14114A140] = lambda args: r.player2
    r.combat = r.bind_combat(**{channel: ReplayTaskRebuildCalls(None)})
    with pytest.raises(UnresolvedReplayTaskRebuild):
        r.run_combat()
    assert not r.live


def test_actual_list_combat_action_moving_base_motion_mask_and_clocks_compose() -> None:
    r = Rig()
    r.real_action, r.real_parent = True, True
    r.visible()
    r.mem.write(r.obj + 0x400, 8, r.motion)
    r.mem.write(r.table + 0x30, 8, COMBAT)
    header, data = r.alloc(0x20), r.alloc(8)
    r.mem.write(header + 8, 8, data)
    r.mem.write(header + 0x10, 4, 1)
    r.mem.write(data, 8, r.obj)
    objects = bind_replay_object_update(r.context, r.combat, profile=ReplayObjectUpdateProfile(1))
    assert objects.call is not None and objects.call(0x141229A20, (header,), None) is None
    assert r.mem.read(r.obj + 0x198, 4) == 93
    assert r.mem.read(r.obj + 0x350, 4) == 0x40400000
    assert r.mem.read(r.obj + 0x42A, 2) == 0
    assert r.called(BASE) == [(r.obj,)]
    assert r.called(ACTION) == [(r.obj,)]
    assert len(r.called(CLOCK)) == 5
    assert r.called(PUBLISH, "visibility_fp_home_calls")
    assert r.called(0x141121110) == [(0xBBB0, r.obj, 0x10)]


def test_invalid_channels_and_mxcsr_refuse_before_effects() -> None:
    r = Rig()
    with pytest.raises(ValueError):
        r.bind_combat(config_home_calls=cast(ReplayTaskRebuildCalls, None))
    for mxcsr in (True, 0, 0x1F81, 0x3F80):
        with pytest.raises(ValueError):
            bind_replay_combat_object_update(
                r.context,
                r.ordinary_calls,
                **{name: ReplayTaskRebuildCalls(None) for name in CHANNELS},
                bind_local=r.local,
                profile=r.combat_profile,
                mxcsr=mxcsr,
            )
    assert not r.events
