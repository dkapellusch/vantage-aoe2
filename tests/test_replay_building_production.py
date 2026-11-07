"""Owned-state controls for area, cancellation and production completion.

Actual queue query/pop/clear/top, allocation, inherited bodies and health/cost
ports compose explicitly. Cell, scalar, catalog, selection, constructor,
message and research child effects are authored capabilities, not native parity.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import fields, replace
from pathlib import Path
from typing import cast

import pytest
from test_replay_action_object_update import (
    BASE,
    CLOCK,
    DESTROY,
    U32,
    U64,
    decoded,
    encoded,
)
from test_replay_building_object_update import BUILDING, CREDIT
from test_replay_object_health_repair import Rig as HealthRig
from test_replay_unit_object_update import UNIT, bits

from vantage.replay_binary32 import add_binary32
from vantage.replay_building_production import (
    ReplayBuildingProductionProfile,
    bind_replay_building_production,
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

AREA, RESET, APPLY = 0x14127CC00, 0x141288160, 0x1412A2C70
CELL, SCALAR, MESSAGE = 0x14127DC70, 0x1417102A0, 0x140D6C3D0
TOP, CLEAR, QUERY, POP, APPEND = (
    0x140B88AF0,
    0x140B88A20,
    0x140B899F0,
    0x140B893D0,
    0x140B87C40,
)
TRAIN, RESEARCH, CHOOSE, READ_TRAIN, READ_RESEARCH = (
    0x140BB8550,
    0x140BBB720,
    0x1412E03A0,
    0x140BB9EF0,
    0x140BBCA50,
)
OPTION, STOCK, SETTING, FIND, PUSH = (
    0x14172AC80,
    0x14122CC30,
    0x14097F980,
    0x142D6A0C0,
    0x14116C430,
)
UNIT_REFUND, COUNT, ITEM, USE_ITEM, RESEARCH_REFUND, DROP, UNTRIGGER, READY = (
    0x141702A00,
    0x14111B550,
    0x141729140,
    0x14111ADE0,
    0x1414987A0,
    0x14127FF00,
    0x14127E490,
    0x141498220,
)
CHANNELS = (
    "area_fp_home_calls",
    "scalar_fp_calls",
    "resource_fp_home_calls",
    "message_home_calls",
    "selection_home_calls",
    "constructor_home_calls",
)
DATA = Path(__file__).resolve().parents[1] / "artifacts/game-internals/2026-10-18-world-envelope"


class Rig(HealthRig):
    def __init__(self) -> None:
        super().__init__()
        self.scalar_word = bits(1.0)
        self.action_status = 0
        self.choice_kind, self.choice_type, self.choice_flag, self.choice_result = 0x66, 10, 0, 0
        self.stock, self.setting, self.research_ready = 0, 0, 1
        self.area_cells: dict[tuple[int, int, int, int], int] = {}
        self.messages_received: list[tuple[int, ...]] = []
        self.constructed: list[int] = []
        self.effects: list[tuple[int, tuple[int, ...]]] = []
        self.catalog_values: dict[int, int] = {}
        self.catalog = self.alloc(0x20)
        self.item_output = self.alloc(8)
        self.settings_pointer = self.alloc(8)
        try:
            self.mem.read_bytes(0x14425B930, 8)
        except ReplayMemoryError:
            self.mem.map_bytes(0x14425B930, self.settings_pointer.to_bytes(8, "little"))
        else:
            self.mem.write(0x14425B930, 8, self.settings_pointer)
        self.terrain = self.alloc(0x6000)
        old_terrain = self.mem.read(self.world + 0x98, 8)
        self.mem.write_bytes(self.terrain, self.mem.read_bytes(old_terrain, 0x6000))
        self.manager, self.research_data = self.alloc(8), self.alloc(4 * 0x98 + 0x80)
        self.mem.write(self.manager, 8, self.research_data)
        for player in self.players:
            self.mem.write(player + 0x18, 8, self.catalog)
            self.mem.write(player + 0x6D0, 8, self.manager)
        self.mem.write(self.world + 0x98, 8, self.terrain)
        self.mem.write(self.terrain + 0x30, 4, 5)
        self.mem.write(self.terrain + 0x34, 4, 5)
        self.production_queue = self.alloc(0x20)
        self.mem.write(self.production_queue + 8, 8, self.obj)
        self.mem.write(self.obj + 0x8A8, 8, self.production_queue)
        self.mem.write(self.obj + 0x8B2, 2, 0xFFFF)
        self.mem.write(self.resource + 80 * 8, 8, encoded(bits(10.0)))
        for field, value in (
            (0x20, 10.0),
            (0x58, 0.0),
            (0x288, 0.0),
            (0x100, 100.0),
            (0x7F8, -1.0),
        ):
            self.mem.write(self.resource + field, 8, encoded(bits(value)))
        for constant in (DATA / "building-update-services-source-v1").glob("constant-*.bin"):
            at, raw = int(constant.stem.split("-")[1], 16), constant.read_bytes()
            try:
                assert self.mem.read_bytes(at, len(raw)) == raw
            except ReplayMemoryError:
                self.mem.map_bytes(at, raw)
        self.production_profile = ReplayBuildingProductionProfile(
            bytes([0xD1]) * 0xD0, bytes([0xD2]) * 0x88, bytes([0xD3]) * 0x70
        )
        self.production = self.bind_production()

    def bind_production(self, **overrides: ReplayTaskRebuildCalls) -> ReplayTaskRebuildCalls:
        channels = {name: ReplayTaskRebuildCalls(self.channel(name)) for name in CHANNELS}
        channels["calls"] = self.services
        channels.update(overrides)
        calls = channels.pop("calls")
        return bind_replay_building_production(
            self.context,
            calls,
            **channels,
            bind_local=self.local,
            profile=self.production_profile,
            mxcsr=0x1F80,
        )

    def run_production(self, target: int) -> int | None:
        assert self.production.call is not None
        return self.production.call(target, (self.obj,), None)

    def compose_all(self) -> None:
        self.ordinary_calls = self.production
        self.action = self.bind()
        self.combat = self.bind_combat()
        self.unit = self.bind_unit()
        self.building = self.bind_building(repair_fp_calls=self.health_body)

    def construct_action(self, target: int, args: tuple[int, ...]) -> int:
        size = 0x80 if target == TRAIN else 0x78
        assert self.mem.read_bytes(args[0], size) == bytes(size)
        self.mem.write(args[0], 8, self.action_table)
        self.mem.write(args[0] + 8, 2, 0x66 if target == TRAIN else 0x67)
        self.mem.write(args[0] + 0x10, 8, args[1])
        self.mem.write(args[0] + 0x34, 4, U32)
        self.statuses[args[0]] = self.action_status
        self.constructed.append(args[0])
        return args[0]

    def rows(self, rows: list[tuple[int, int, int]], *, enable: bool = True) -> int:
        base = self.alloc(max(48, len(rows) * 48))
        for index, (item, quantity, association) in enumerate(rows):
            for member, value in ((0, item), (2, quantity), (4, association)):
                self.mem.write(base + index * 48 + member, 2, value & 0xFFFF)
        self.mem.write(self.obj + 0x898, 8, base)
        self.mem.write(self.obj + 0x8A2, 2, len(rows))
        self.mem.write(self.obj + 0x8A4, 2, sum(quantity for _, quantity, _ in rows) & 0xFFFF)
        self.mem.write(self.obj + 0x8A6, 1, int(enable))
        return base

    def queue_nodes(self, statuses: list[int]) -> tuple[list[int], list[int]]:
        old = self.stack
        self.stack = self.production_queue
        nodes, actions = self.nodes(statuses)
        self.stack = old
        return nodes, actions

    def vector(self, offset: int, values: list[int]) -> int:
        buffer = self.alloc(16)
        for i, value in enumerate(values):
            self.mem.write(buffer + i * 2, 2, value)
        self.mem.write(self.obj + offset, 8, buffer)
        self.mem.write(self.obj + offset + 8, 8, buffer + 2 * len(values))
        self.mem.write(self.obj + offset + 16, 8, buffer + 16)
        return buffer

    def area_data(self) -> None:
        self.kind(7)
        self.coords(self.obj, bits(2.0), bits(3.0))
        self.mem.write(self.master + 0x78, 4, bits(0.5))
        self.mem.write(self.master + 0x7C, 4, bits(0.5))
        for field, value in (
            (0x7F8, 7.0),
            (0x800, 0.5),
            (0x808, 2.0),
            (0x828, 3.0),
            (0x810, 4.0),
            (0x818, 1.0),
            (0x820, 2.0),
        ):
            self.mem.write(self.resource + field, 8, encoded(bits(value)))

    def ordinary(self, target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        local = target in (
            QUERY,
            POP,
            APPEND,
            0x142D6BA78,
            STOCK,
            SETTING,
            FIND,
            PUSH,
            UNIT_REFUND,
            COUNT,
            ITEM,
            USE_ITEM,
            RESEARCH_REFUND,
            DROP,
            UNTRIGGER,
            READY,
        )
        if not local:
            return super().ordinary(target, args, data)
        assert data is None
        if handler := self.record("calls", target, args):
            return handler(args)
        if target in (QUERY, POP):
            assert self.action.call is not None
            return self.action.call(target, args, None)
        if target == 0x142D6BA78:
            assert self.runtime.call is not None
            return self.runtime.call(target, args, None)
        if target == APPEND:
            node = self.alloc(16)
            self.mem.write(node, 8, args[1])
            self.mem.write(node + 8, 8, self.mem.read(args[0] + 0x10, 8))
            self.mem.write(args[0] + 0x10, 8, node)
            return None
        if target == STOCK:
            return self.stock
        if target == SETTING:
            return self.setting
        if target == READY:
            return self.research_ready
        if target == FIND:
            begin, end, key = args
            for at in range(begin, end, 2):
                if self.mem.read(at, 2) == key:
                    return at
            return end
        if target == PUSH:
            begin, end = self.mem.read(args[0], 8), self.mem.read(args[0] + 8, 8)
            assert begin <= end < self.mem.read(args[0] + 16, 8)
            self.mem.write(end, 2, self.mem.read(args[1], 2))
            self.mem.write(args[0] + 8, 8, end + 2)
            return None
        self.effects.append((target, args))
        if target == COUNT:
            raw = args[1] & 0xFFFF
            delta = raw if raw < 0x8000 else raw - 0x10000
            self.mem.write(args[0], 4, (self.mem.read(args[0], 4) + delta) & U32)
        if target == ITEM:
            self.mem.write(args[1] + 4, 4, (1000 + args[2]) & U32)
            return args[1]
        if target == USE_ITEM:
            self.catalog_values[args[1]] = args[2]
        return None

    def channel(
        self, channel: str
    ) -> Callable[[int, tuple[int, ...], memoryview | None], int | None]:
        fallback = super().channel(channel)

        def dispatch(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
            local = (
                channel
                in (
                    "area_fp_home_calls",
                    "message_home_calls",
                    "selection_home_calls",
                    "constructor_home_calls",
                )
                or (channel == "scalar_fp_calls" and target == SCALAR)
                or (channel == "resource_fp_home_calls" and target == CREDIT and args[1] == 80)
            )
            if not local:
                return fallback(target, args, data)
            assert data is None
            if handler := self.record(channel, target, args):
                return handler(args)
            if channel == "area_fp_home_calls" and target == CELL:
                x, y = self.mem.read(args[4], 4), self.mem.read(args[5], 4)
                key = (args[1], args[2], x, y)
                self.area_cells[key] = add_binary32(self.area_cells.get(key, 0), args[3])
                return None
            if channel == "scalar_fp_calls" and target == SCALAR:
                return self.scalar_word
            if channel == "resource_fp_home_calls" and target == CREDIT:
                self.credits.append(args)
                self.credit_homes.append(self.mem.read_bytes(args[-1], 8))
                resources = self.mem.read(args[0] + 0x98, 8)
                before = decoded(self.mem.read(resources + 80 * 8, 8))
                after = add_binary32(before & U32, args[2])
                self.mem.write(resources + 80 * 8, 8, encoded(before & ~U32 | after))
                return None
            if channel == "message_home_calls" and target == MESSAGE:
                self.messages_received.append(
                    (*args[:4], self.mem.read(args[4], 4), self.mem.read(args[5], 4))
                )
                return None
            if channel == "selection_home_calls" and target in (CHOOSE, READ_TRAIN, READ_RESEARCH):
                if target == CHOOSE:
                    self.mem.write(args[1], 2, self.choice_kind)
                    self.mem.write(args[2], 2, self.choice_type)
                    self.mem.write(args[3], 2, self.choice_flag)
                else:
                    self.mem.write(args[1], 2, self.choice_type)
                    self.mem.write(args[2], 2, self.choice_flag)
                return self.choice_result
            if channel == "constructor_home_calls" and target in (TRAIN, RESEARCH):
                return self.construct_action(target, args)
            raise UnresolvedReplayTaskRebuild(f"authored {channel} missing{target:x}")

        return dispatch


@pytest.mark.parametrize("field", [f.name for f in fields(ReplayBuildingProductionProfile)])
def test_exact_immutable_profiles(field: str) -> None:
    r = Rig()
    for value in (b"", bytearray(getattr(r.production_profile, field))):
        with pytest.raises(ValueError):
            replace(r.production_profile, **{field: value})


@pytest.mark.parametrize("target", [AREA, RESET, APPLY])
def test_addressed_shape_refuses_before_effects(target: int) -> None:
    r = Rig()
    assert r.production.call is not None
    for args, data in (((), None), ((-1,), None), ((r.obj,), memoryview(b"raw"))):
        with pytest.raises(ValueError):
            r.production.call(target, args, data)
    assert not r.events


def test_unknown_calls_preserve_identity() -> None:
    r = Rig()
    args, data, result = (-1, 4), memoryview(b"raw"), 123456789012345

    def unknown(target: int, actual: tuple[int, ...], payload: memoryview | None) -> int:
        assert target == 17 and actual is args and payload is data
        return result

    bound = r.bind_production(calls=ReplayTaskRebuildCalls(unknown))
    assert bound.call is not None and bound.call(17, args, data) is result


@pytest.mark.parametrize("wanted", [bits(7.0), bits(8.0), 0x7FC12345])
def test_area_ordered_kind_guard_and_actual_owned_cell_effects(wanted: int) -> None:
    r = Rig()
    r.area_data()
    r.mem.write(r.resource + 0x7F8, 8, encoded(wanted))
    assert r.run_production(AREA) is None
    expected = (
        {
            (kind, 4, x, y): bits(amount)
            for x in (1, 2)
            for y in (2, 3)
            for kind, amount in ((1, 2.0), (2, 3.0))
        }
        if wanted == bits(7.0)
        else {}
    )
    assert r.area_cells == expected
    if wanted != bits(7.0):
        assert not any(event[0] == "r" and event[1] == r.resource + 0x800 for event in r.events)


def test_area_holds_amounts_and_reloads_bounds_after_each_inner_row() -> None:
    r = Rig()
    r.area_data()
    calls = 0

    def cell(args: tuple[int, ...]) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            r.mem.write(r.frame(0xD0) + 0xB0, 4, 2)
            r.mem.write(r.resource + 0x808, 8, encoded(bits(99.0)))
            r.mem.write(r.resource + 0x828, 8, encoded(bits(88.0)))

    r.handlers["area_fp_home_calls", CELL] = cell
    r.run_production(AREA)
    actual = r.called(CELL, "area_fp_home_calls")
    assert len(actual) == 6
    assert [args[3] for args in actual] == [bits(value) for value in (2, 3, 2, 3, 2, 3)]


def test_area_selector_is_converted_after_encoded_x_read() -> None:
    r = Rig()
    r.area_data()
    changed = False

    def mutate(at: int, width: int, value: int) -> None:
        nonlocal changed
        if at == r.obj + 0x170 and not changed:
            changed = True
            r.mem.write(r.frame(0xD0) + 0xB0, 4, bits(9.0))

    r.after_read = mutate
    r.run_production(AREA)
    assert r.area_cells and all(key[1] == 9 for key in r.area_cells)


def test_area_captures_terrain_dimensions_before_final_epsilon_read() -> None:
    r = Rig()
    r.area_data()
    reads = 0

    def mutate(at: int, width: int, value: int) -> None:
        nonlocal reads
        if at == 0x1431FF7BC:
            reads += 1
            if reads == 2:
                r.mem.write(r.terrain + 0x30, 4, 0)
                r.mem.write(r.terrain + 0x34, 4, 0)

    r.after_read = mutate
    r.run_production(AREA)
    assert reads == 2 and len(r.area_cells) == 8


@pytest.mark.parametrize("x", [0x7FC12345, 0x7F800000, 0xFF800000])
def test_area_raw_cvtt_invalid_x_skips_empty_cell_range(x: int) -> None:
    r = Rig()
    r.area_data()
    r.coords(r.obj, x, bits(3.0))
    r.production = r.bind_production(area_fp_home_calls=ReplayTaskRebuildCalls(None))
    assert r.run_production(AREA) is None and not r.area_cells


def test_reset_empty_rows_uses_actual_clear_and_partial_counter_writes() -> None:
    r = Rig()
    nodes, actions = r.queue_nodes([0, 0])
    r.mem.write(r.obj + 0x8B0, 1, 255)
    r.mem.write(r.obj + 0x8A4, 2, 7)
    assert r.run_production(RESET) is None
    assert r.mem.read(r.obj + 0x8B0, 1) == 0 and r.mem.read(r.obj + 0x8A4, 2) == 0
    assert r.called(CLEAR) == [(r.production_queue,)]
    for at in nodes + actions:
        with pytest.raises(ReplayMemoryError):
            r.mem.read(at, 1)


@pytest.mark.parametrize(("quantity", "amount"), [(2, -2.0), (0, -0.0), (-1, 1.0)])
def test_reset_signed_quantity_actual_catalog_effects_and_credit(
    quantity: int, amount: float
) -> None:
    r = Rig()
    rows = r.rows([(10, quantity, -1)])
    r.run_production(RESET)
    positive = max(quantity, 0)
    assert r.called(UNIT_REFUND) == [(r.owner, rows + 8, 10)] * positive
    assert r.called(COUNT) == [(r.catalog, U32)] * positive + [(r.catalog, (-quantity) & 0xFFFF)]
    assert [args[2] for args in r.credits] == [bits(amount)]
    assert decoded(r.mem.read(r.resource + 80 * 8, 8)) & U32 == bits(10.0 + amount)
    assert r.mem.read(r.obj + 0x8A2, 2) == 0
    assert r.called(SCALAR, "scalar_fp_calls")[0][1:] == (10, 1, 255)


def test_reset_held_repeat_count_then_current_partial_quantity_home() -> None:
    r = Rig()
    r.rows([(10, 2, -1)])

    def refund(args: tuple[int, ...]) -> None:
        r.mem.write(r.frame(0x88) + 0x80, 2, 7)

    r.handlers["calls", UNIT_REFUND] = refund
    r.run_production(RESET)
    assert len(r.called(UNIT_REFUND)) == 2
    assert r.credits[0][2] == bits(-7.0)
    assert r.called(COUNT)[-1] == (r.catalog, 0xFFF9)
    snapshot = next(raw for size, raw in r.snapshots if size == 0x88)
    assert snapshot[0x80:0x88] == b"\x07\x00" + b"\xd2" * 6


def test_reset_sign_mask_owner_and_f8_target_survive_scalar_callback() -> None:
    r = Rig()
    r.rows([(10, 2, -1)])

    def scalar(args: tuple[int, ...]) -> int:
        r.mem.write_bytes(0x1431D37E0, bytes(16))
        r.mem.write(r.obj + 0x18, 8, r.player2)
        r.mem.write(r.player_table + 0xF8, 8, 0xBAD)
        return bits(1.0)

    r.handlers["scalar_fp_calls", SCALAR] = scalar
    r.run_production(RESET)
    assert r.credits[0][:3] == (r.owner, 80, bits(-2.0))


def test_reset_associated_research_uses_current_owned_manager_count() -> None:
    r = Rig()
    rows = r.rows([(10, 3, 2)])
    at = r.research_data + 2 * 0x98 + 0x70
    r.mem.write(at, 2, 10)
    r.run_production(RESET)
    assert r.called(RESEARCH_REFUND) == [(r.manager, rows + 8, 2, 3)]
    assert r.called(DROP) == [(r.obj, 2)] and r.called(UNTRIGGER) == [(r.obj, 2)]
    assert r.mem.read(at, 2) == 7
    assert not r.credits and not r.called(UNIT_REFUND)


def test_reset_reload_row_count_after_callback_can_end_iteration() -> None:
    r = Rig()
    r.rows([(10, 1, -1), (20, 1, -1)])

    def refund(args: tuple[int, ...]) -> None:
        r.mem.write(r.obj + 0x8A2, 2, 1)

    r.handlers["calls", UNIT_REFUND] = refund
    r.run_production(RESET)
    assert len(r.called(UNIT_REFUND)) == 1


def test_reset_message_holds_game_before_homes_and_reads_owner_id_after() -> None:
    r = Rig()
    r.mem.write(r.obj + 0x8B2, 2, 0xFFF0)

    def mutate(at: int, width: int, value: int) -> None:
        if r.live and at == r.frame(0x88) + 0x28:
            r.mem.write(0x144353698, 8, r.other)
            r.mem.write(r.owner + 0x648, 4, 55)

    r.after_write = mutate
    r.run_production(RESET)
    assert r.messages_received == [(r.game, 125, 55, 0xFFFFFFF0, 0, 0)]
    assert r.mem.read(r.obj + 0x8B2, 2) == 0xFFFF


def test_reset_holds_queue_before_zeroing_row_count() -> None:
    r = Rig()
    nodes, _ = r.queue_nodes([0])
    other = r.alloc(0x20)

    def mutate(at: int, width: int, value: int) -> None:
        if at == r.obj + 0x8A2:
            r.mem.write(r.obj + 0x8A8, 8, other)

    r.after_write = mutate
    r.run_production(RESET)
    assert r.called(CLEAR) == [(r.production_queue,)]
    with pytest.raises(ReplayMemoryError):
        r.mem.read(nodes[0], 1)


@pytest.mark.parametrize(("enabled", "count"), [(False, 1), (True, 0)])
def test_apply_entry_gates_skip_children_and_private_view(enabled: bool, count: int) -> None:
    r = Rig()
    r.rows([(10, 1, -1)], enable=enabled)
    r.mem.write(r.obj + 0x8A2, 2, count)
    r.production = r.bind_production(calls=ReplayTaskRebuildCalls(None))
    assert r.run_production(APPLY) is None
    assert not r.calls and not r.snapshots


@pytest.mark.parametrize("kind", [0x66, 0x67, 0x7B, 0x7C, 0x7D, 0x70])
def test_apply_live_choice_blockers_and_waiting_byte(kind: int) -> None:
    r = Rig()
    r.rows([(10, 2, -1)])
    r.choice_kind, r.choice_result = kind, 1
    r.run_production(APPLY)
    blocked = kind != 0x70
    assert r.mem.read(r.obj + 0x8B1, 1) == int(blocked)
    assert bool(r.constructed) == (not blocked)


def test_apply_rechecks_live_kind_after_first_option_callback() -> None:
    r = Rig()
    r.rows([(10, 2, -1)])
    r.choice_result = 1
    count = 0

    def option(args: tuple[int, ...]) -> int:
        nonlocal count
        count += 1
        if count == 2:
            r.mem.write(r.frame(0x70) + 0x60, 2, 0x67)
            return 1
        return 0

    r.handlers["calls", OPTION] = option
    r.run_production(APPLY)
    assert count == 3 and r.mem.read(r.obj + 0x8B1, 1) == 1
    assert not r.constructed


@pytest.mark.parametrize(("kind", "reader"), [(0x66, READ_TRAIN), (0x67, READ_RESEARCH)])
def test_apply_actual_top_and_partial_reader_homes(kind: int, reader: int) -> None:
    r = Rig()
    r.rows([(10, 2, -1)])
    _, actions = r.queue_nodes([0])
    r.mem.write(actions[0] + 8, 2, kind)
    r.option = 1
    r.run_production(APPLY)
    assert r.called(TOP) == [(r.production_queue,)]
    assert r.called(reader, "selection_home_calls")[0][0] == actions[0]
    raw = next(raw for size, raw in r.snapshots if size == 0x70)
    assert raw[0x20:0x28] == bytes(2) + b"\xd3" * 6
    assert not r.constructed


def test_apply_negative_raw_row_count_passes_entry_gate() -> None:
    r = Rig()
    r.rows([(10, 2, -1)])
    r.queue_nodes([0])
    r.mem.write(r.obj + 0x8A2, 2, 0xFFFF)
    r.run_production(APPLY)
    assert r.called(CHOOSE, "selection_home_calls")
    assert r.called(STOCK) and r.called(QUERY)


@pytest.mark.parametrize("stock", [0x80, 0xFF, 0x123456FFFF])
def test_apply_signed_stock_al_blocks_without_queue_work(stock: int) -> None:
    r = Rig()
    r.rows([(10, 2, -1)])
    r.stock = stock
    r.run_production(APPLY)
    assert r.mem.read(r.obj + 0x8B1, 1) == 1
    assert not r.constructed and not r.called(QUERY)


@pytest.mark.parametrize("status", [32, 4])
def test_apply_capacity_limits_publish_notice_without_allocating(status: int) -> None:
    r = Rig()
    r.rows([(10, 2, -1)])
    field = 0x58 if status == 32 else 0x20
    r.mem.write(r.resource + field, 8, encoded(bits(100.0 if status == 32 else 0.0)))
    r.run_production(APPLY)
    assert r.mem.read(r.obj + 0x8B2, 2) == status
    assert [msg[1:4] for msg in r.messages_received] == [(124, 1, status)]
    assert not r.constructed and not r.called(QUERY)


def test_apply_capacity_notice_cancel_then_replace_and_duplicate_suppression() -> None:
    r = Rig()
    r.rows([(10, 2, -1)])
    r.mem.write(r.resource + 0x58, 8, encoded(bits(100.0)))
    r.mem.write(r.obj + 0x8B2, 2, 0xFFF0)
    r.run_production(APPLY)
    assert [(msg[1], msg[3]) for msg in r.messages_received] == [(125, 0xFFFFFFF0), (124, 32)]
    before = len(r.messages_received)
    r.run_production(APPLY)
    assert len(r.messages_received) == before


def test_apply_capacity_option_composes_actual_reset_and_clear() -> None:
    r = Rig()
    r.rows([(10, 2, -1)])
    r.mem.write(r.resource + 0x58, 8, encoded(bits(100.0)))
    replies = iter((0, 1))
    r.handlers["calls", OPTION] = lambda args: next(replies)
    r.run_production(APPLY)
    assert r.mem.read(r.obj + 0x8A2, 2) == 0
    assert r.credits[0][2] == bits(-2.0)
    assert r.called(CLEAR) == [(r.production_queue,)]
    assert not r.constructed and not r.messages_received


def test_apply_message_samples_game_after_homes_and_current_owner_id() -> None:
    r = Rig()
    r.rows([(10, 2, -1)])
    r.mem.write(r.resource + 0x58, 8, encoded(bits(100.0)))

    def mutate(at: int, width: int, value: int) -> None:
        if r.live and at == r.frame(0x70) + 0x28 and width == 4:
            r.mem.write(0x144353698, 8, r.other)
            r.mem.write(r.owner + 0x648, 4, 55)

    r.after_write = mutate
    r.run_production(APPLY)
    assert r.messages_received == [(r.other, 124, 55, 32, 0, 0)]


def test_apply_unordered_capacity_sum_does_not_invent_limit_failure() -> None:
    r = Rig()
    r.rows([(10, 2, -1)])
    r.mem.write(r.resource + 0x58, 8, encoded(0x7FC12345))
    r.run_production(APPLY)
    assert r.constructed and not r.messages_received


def test_apply_training_constructor_zeroing_and_current_partial_arguments() -> None:
    r = Rig()
    rows = r.rows([(0xF0F0, 2, -1)])
    r.mem.write(rows + 0x28, 4, 0xAABBCCDD)
    r.mem.write(rows + 0x2C, 2, 0x1234)
    observed: list[tuple[int, int, int, int]] = []

    def constructor(args: tuple[int, ...]) -> int:
        observed.append((args[2], args[3], r.mem.read(args[5], 2), r.mem.read(args[6], 4)))
        return r.construct_action(TRAIN, args)

    def mutate(at: int, width: int, value: int) -> None:
        if r.live and at == r.frame(0x70) + 0x20 and width == 1 and value == 0:
            r.mem.write(rows, 2, 77)
            r.mem.write(rows + 0x2C, 2, 0x9999)

    r.after_write = mutate
    r.handlers["constructor_home_calls", TRAIN] = constructor
    r.run_production(APPLY)
    assert observed == [(77, U32, 0x1234, 0xAABBCCDD)]
    assert r.constructed and r.called(APPEND)
    assert r.called(SCALAR, "scalar_fp_calls")[0][1:] == (0xFFFFF0F0, 1, 255)


def test_apply_research_constructor_uses_signed_item_and_zeroed_120_bytes() -> None:
    r = Rig()
    r.rows([(-1, 2, 2)])
    r.run_production(APPLY)
    args = r.called(RESEARCH, "constructor_home_calls")[0]
    assert args[2:4] == (2, U32)
    assert r.constructed and not r.called(SCALAR, "scalar_fp_calls")


def test_apply_null_allocation_skips_constructor_then_keeps_source_completion() -> None:
    r = Rig()
    rows = r.rows([(10, 2, -1)])
    r.handlers["calls", 0x142D6BA78] = lambda args: 0
    r.run_production(APPLY)
    assert not r.constructed and not r.called(TRAIN, "constructor_home_calls")
    assert r.called(SETTING) and r.called(POP)
    assert r.mem.read(rows + 2, 2) == 1
    assert r.credits[0][2] == bits(-1.0)


def test_apply_constructor_annotation_is_delayed_until_after_setting_and_message() -> None:
    r = Rig()
    r.rows([(10, 2, -1)])
    r.mem.write(r.resource + 0x20, 8, encoded(bits(2.0)))
    r.setting = 1
    r.handlers["constructor_home_calls", TRAIN] = lambda args: None
    with pytest.raises(ValueError, match="production constructor RAX"):
        r.run_production(APPLY)
    assert r.called(SETTING) and [m[1] for m in r.messages_received] == [169]
    assert not r.called(APPEND) and not r.called(QUERY)


def test_apply_out_of_range_setting_result_is_ignored() -> None:
    r = Rig()
    r.rows([(10, 2, -1)])
    r.handlers["calls", SETTING] = lambda args: None
    assert r.run_production(APPLY) is None and r.constructed


@pytest.mark.parametrize(
    ("status", "completed"), [(0, False), (1, True), (2, True), (3, True), (4, False)]
)
def test_apply_actual_query_pop_destroy_and_owned_credit(status: int, completed: bool) -> None:
    r = Rig()
    rows = r.rows([(10, 2, -1)])
    nodes, actions = r.queue_nodes([status])
    r.run_production(APPLY)
    assert r.mem.read(rows + 2, 2) == (1 if completed else 2)
    assert r.mem.read(r.obj + 0x8B0, 1) == int(completed)
    assert bool(r.called(DESTROY, "virtual_calls")) == completed
    assert decoded(r.mem.read(r.resource + 80 * 8, 8)) & U32 == bits(9.0 if completed else 10.0)
    for at in nodes + actions:
        if completed:
            with pytest.raises(ReplayMemoryError):
                r.mem.read(at, 1)
        else:
            r.mem.read(at, 1)


def test_apply_completion_rereads_current_16_byte_sign_mask_after_getter() -> None:
    r = Rig()
    r.rows([(10, 2, -1)])
    r.queue_nodes([2])

    def scalar(args: tuple[int, ...]) -> int:
        r.mem.write_bytes(0x1431D37E0, bytes(16))
        return bits(1.0)

    r.handlers["scalar_fp_calls", SCALAR] = scalar
    r.run_production(APPLY)
    assert r.credits[0][2] == bits(1.0)
    assert any(event[:3] == ("r", 0x1431D37E0, 16) for event in r.events)


def test_apply_missing_completion_fp_annotation_refuses_after_sign_mask_load() -> None:
    r = Rig()
    r.rows([(10, 2, -1)])
    r.queue_nodes([2])
    r.handlers["scalar_fp_calls", SCALAR] = lambda args: None
    with pytest.raises(ValueError, match="completion scalar XMM0"):
        r.run_production(APPLY)
    assert r.events[-1][:3] == ("r", 0x1431D37E0, 16)
    assert not r.credits


def test_apply_research_vectors_append_live_words_before_actual_pop() -> None:
    r = Rig()
    r.rows([(10, 1, 2)])
    r.queue_nodes([1])
    first, second = r.vector(0x9C8, []), r.vector(0x9B0, [])
    r.run_production(APPLY)
    assert r.mem.read(first, 2) == 2 and r.mem.read(second, 2) == 2
    assert r.mem.read(r.obj + 0x9D0, 8) == first + 2
    assert r.mem.read(r.obj + 0x9B8, 8) == second + 2
    assert len(r.called(PUSH)) == 2 and r.called(POP)


def test_apply_existing_first_research_vector_skips_second_search() -> None:
    r = Rig()
    r.rows([(10, 1, 2)])
    r.queue_nodes([1])
    r.vector(0x9C8, [2])
    second = r.vector(0x9B0, [])
    r.run_production(APPLY)
    assert len(r.called(FIND)) == 1 and not r.called(PUSH)
    assert r.mem.read(r.obj + 0x9B8, 8) == second


def test_apply_find_result_consumption_follows_current_end_read() -> None:
    r = Rig()
    r.rows([(10, 1, 2)])
    r.queue_nodes([1])
    r.vector(0x9C8, [])
    r.handlers["calls", FIND] = lambda args: None
    with pytest.raises(ValueError, match="research find RAX"):
        r.run_production(APPLY)
    assert r.events[-1][:3] == ("r", r.obj + 0x9D0, 8)
    assert not r.called(POP)


def test_apply_row_shift_copies_fields_and_preserves_destination_padding() -> None:
    r = Rig()
    rows = r.rows([(10, 1, -1), (20, 2, 2), (30, 3, 3)])
    for i in range(3):
        r.mem.write_bytes(rows + i * 48 + 6, bytes([0xA0 + i]) * 2)
        r.mem.write_bytes(rows + i * 48 + 8, bytes([0x10 + i]) * 38)
        r.mem.write_bytes(rows + i * 48 + 46, bytes([0xB0 + i]) * 2)
    next_rows = [r.mem.read_bytes(rows + i * 48, 48) for i in (1, 2)]
    r.queue_nodes([2])
    r.run_production(APPLY)
    for i, original in enumerate(next_rows):
        after = r.mem.read_bytes(rows + i * 48, 48)
        assert after[:6] == original[:6] and after[8:32] == original[8:32]
        assert after[40:46] == original[40:46]
        assert after[6:8] == bytes([0xA0 + i]) * 2
        assert after[32:40] == bytes([0x10 + i]) * 8
        assert after[46:48] == bytes([0xB0 + i]) * 2
    assert r.mem.read(r.obj + 0x8A2, 2) == 2
    assert r.mem.read(r.obj + 0x8A4, 2) == 5


def test_apply_row_shift_holds_group_base_then_reloads_for_later_scalar_fields() -> None:
    r = Rig()
    old = r.rows([(10, 1, -1), (20, 2, 2)])
    new = r.rows([(40, 4, 1), (50, 5, 2)])
    r.mem.write(r.obj + 0x898, 8, old)
    for rows, low, high in ((old, 0x11, 0x22), (new, 0x33, 0x44)):
        r.mem.write_bytes(rows + 8, bytes([low]) * 38)
        r.mem.write_bytes(rows + 48 + 8, bytes([high]) * 38)
    r.queue_nodes([2])
    changed = False

    def mutate(at: int, width: int, value: int) -> None:
        nonlocal changed
        if at == old + 8 and width == 16 and not changed:
            changed = True
            r.mem.write(r.obj + 0x898, 8, new)

    r.after_write = mutate
    r.run_production(APPLY)
    assert changed
    assert r.mem.read_bytes(old + 0x18, 8) == b"\x22" * 8
    assert r.mem.read_bytes(new + 0x18, 8) == b"\x33" * 8
    assert r.mem.read_bytes(old + 0x28, 4) == b"\x11" * 4
    assert r.mem.read_bytes(new + 0x28, 4) == b"\x44" * 4


def test_apply_holds_credit_owner_and_target_before_completion_getter() -> None:
    r = Rig()
    r.rows([(10, 2, -1)])
    r.queue_nodes([2])

    def scalar(args: tuple[int, ...]) -> int:
        r.mem.write(r.obj + 0x18, 8, r.player2)
        r.mem.write(r.player_table + 0xF8, 8, 0xBAD)
        return bits(1.0)

    r.handlers["scalar_fp_calls", SCALAR] = scalar
    r.run_production(APPLY)
    assert r.credits[0][:3] == (r.owner, 80, bits(-1.0))
    assert r.credits[0][3:5] == (0, U64)


@pytest.mark.parametrize("channel", CHANNELS)
def test_missing_typed_capability_refuses_at_exact_reached_target(channel: str) -> None:
    r = Rig()
    if channel == "area_fp_home_calls":
        r.area_data()
        entry, target = AREA, CELL
    elif channel in ("scalar_fp_calls", "resource_fp_home_calls"):
        r.rows([(10, 0, -1)])
        entry, target = RESET, SCALAR if channel == "scalar_fp_calls" else CREDIT
    elif channel == "message_home_calls":
        r.mem.write(r.obj + 0x8B2, 2, 7)
        entry, target = RESET, MESSAGE
    else:
        r.rows([(10, 2, -1)])
        entry, target = APPLY, CHOOSE if channel == "selection_home_calls" else TRAIN
    r.production = r.bind_production(**{channel: ReplayTaskRebuildCalls(None)})
    with pytest.raises(UnresolvedReplayTaskRebuild, match=f"reached{target:x} is unavailable"):
        r.run_production(entry)
    assert not r.live


def test_missing_ordinary_capability_and_unused_area_ordinary_capability() -> None:
    r = Rig()
    r.rows([(10, 2, -1)])
    r.production = r.bind_production(calls=ReplayTaskRebuildCalls(None))
    with pytest.raises(UnresolvedReplayTaskRebuild, match=f"reached{OPTION:x} is unavailable"):
        r.run_production(APPLY)
    r.area_data()
    assert r.run_production(AREA) is None and len(r.area_cells) == 8


def test_invalid_capabilities_and_mxcsr_refuse_before_effects() -> None:
    r = Rig()
    with pytest.raises(ValueError):
        r.bind_production(scalar_fp_calls=cast(ReplayTaskRebuildCalls, None))
    for mxcsr in (True, 0, 0x1F81, 0x3F80):
        with pytest.raises(ValueError):
            bind_replay_building_production(
                r.context,
                ReplayTaskRebuildCalls(None),
                **{name: ReplayTaskRebuildCalls(None) for name in CHANNELS},
                bind_local=r.local,
                profile=r.production_profile,
                mxcsr=mxcsr,
            )
    assert not r.events


def test_actual_building_area_update_and_ordinary_queue_services_compose() -> None:
    r = Rig()
    r.area_data()
    r.active_building(1000)
    r.compose_all()
    assert r.run_building() == 0xFA
    assert len(r.area_cells) == 8
    assert r.mem.read(r.obj + 0x84D, 1) == 0
    assert r.mem.read(r.obj + 0x890, 4) == 1000


def test_actual_building_high_state_production_reset_updates_owned_counters() -> None:
    r = Rig()
    r.mem.write(r.obj + 0x188, 1, 7)
    r.compose_all()
    assert r.run_building() == 0xFA
    assert r.mem.read(r.obj + 0x8B0, 1) == 1
    assert r.called(CLEAR) == [(r.production_queue,)]


def test_actual_building_production_apply_pops_action_and_updates_row_and_credit() -> None:
    r = Rig()
    rows = r.rows([(10, 2, -1)])
    nodes, _ = r.queue_nodes([2])
    r.compose_all()
    assert r.run_building() == 0xFA
    assert r.mem.read(rows + 2, 2) == 1
    assert decoded(r.mem.read(r.resource + 80 * 8, 8)) & U32 == bits(9.0)
    with pytest.raises(ReplayMemoryError):
        r.mem.read(nodes[0], 1)


def test_actual_production_services_and_full_inherited_object_list_chain() -> None:
    r = Rig()
    r.compose_all()
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
