"""Owned storage and mutation controls for five whole Building services.

Queue destruction/free use existing authored destructors and actual owned
storage release. Game mode and final stage application are required authored
effects. Building and inherited bodies compose as Python, never Game code.
"""

from __future__ import annotations

from dataclasses import replace
from typing import cast

import pytest
from test_replay_action_object_update import (
    BASE,
    CLOCK,
    DESTROY,
    FREE_IMPORT,
    OTHER_FREE,
    U32,
    U64,
    UPDATE,
)
from test_replay_building_object_update import BUILDING, TASK
from test_replay_building_object_update import Rig as BuildingRig
from test_replay_unit_object_update import UNIT, bits

from vantage.replay_building_services import (
    ReplayBuildingServicesProfile,
    bind_replay_building_services,
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

RUN, THRESHOLD, STAGE, RESET, LOOKUP = (
    0x140BB83E0,
    0x140BB9290,
    0x141286D70,
    0x1412BAED0,
    0x141617DB0,
)
MODE, APPLY = 0x140D6A940, 0x141296BF0
ARITIES = {RUN: 1, THRESHOLD: 2, STAGE: 2, RESET: 1, LOOKUP: 2}


class Rig(BuildingRig):
    def __init__(self) -> None:
        super().__init__()
        self.mode = 0
        self.service_profile = ReplayBuildingServicesProfile(bytes([0xB9]) * 8)
        self.services = self.bind_services()

    def bind_services(self, **overrides: ReplayTaskRebuildCalls) -> ReplayTaskRebuildCalls:
        channels = {
            "virtual_calls": ReplayTaskRebuildCalls(self.channel("virtual_calls")),
            "imports": ReplayTaskRebuildCalls(self.channel("imports")),
            "calls": ReplayTaskRebuildCalls(self.ordinary),
        }
        channels.update(overrides)
        calls = channels.pop("calls")
        return bind_replay_building_services(
            self.context, calls, **channels, bind_local=self.local, profile=self.service_profile
        )

    def ordinary(self, target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        if target not in (MODE, APPLY):
            return super().ordinary(target, args, data)
        assert data is None
        if handler := self.record("calls", target, args):
            return handler(args)
        if target == MODE:
            return self.mode
        self.mem.write(args[0] + 0xE, 1, args[1])
        return None

    def run_service(self, target: int, *args: int) -> int | None:
        assert self.services.call is not None
        return self.services.call(target, args, None)

    def lookup_tables(self) -> tuple[int, int]:
        primary, secondary = self.alloc(24), self.alloc(32)
        for i in range(3):
            self.mem.write(primary + i * 8, 8, 0x100 + i)
        for i in range(4):
            self.mem.write(secondary + i * 8, 8, 0x400 + i)
        for field, width, value in (
            (0x168, 8, primary),
            (0x174, 4, 3),
            (0x178, 8, secondary),
            (0x184, 4, 4),
        ):
            self.mem.write(self.world + field, width, value)
        return primary, secondary

    def compose_building(self) -> None:
        self.ordinary_calls = self.services
        self.action = self.bind()
        self.combat = self.bind_combat()
        self.unit = self.bind_unit()
        self.building = self.bind_building()


def test_explicit_immutable_stage_profile() -> None:
    r = Rig()
    for seed in (b"", bytes(9), bytearray(8)):
        with pytest.raises(ValueError):
            replace(r.service_profile, stage=seed)
    assert not r.events


@pytest.mark.parametrize(("target", "arity"), list(ARITIES.items()))
def test_known_call_shape_refuses_before_effects(target: int, arity: int) -> None:
    r = Rig()
    assert r.services.call is not None
    for args, data in (((), None), ((-1,) * arity, None), ((r.obj,) * arity, memoryview(b"raw"))):
        with pytest.raises(ValueError):
            r.services.call(target, args, data)
    assert not r.events


def test_unknown_call_arguments_payload_and_result_keep_identity() -> None:
    r = Rig()
    args, data, result = (-1, 4), memoryview(b"raw"), 123456789012345

    def unknown(target: int, given: tuple[int, ...], payload: memoryview | None) -> int:
        assert target == 17 and given is args and payload is data
        return result

    bound = r.bind_services(calls=ReplayTaskRebuildCalls(unknown))
    assert bound.call is not None and bound.call(17, args, data) is result


def test_empty_queue_returns_zero_without_children_or_local_binding() -> None:
    r = Rig()
    r.services = r.bind_services(
        calls=ReplayTaskRebuildCalls(None),
        virtual_calls=ReplayTaskRebuildCalls(None),
        imports=ReplayTaskRebuildCalls(None),
    )
    assert r.run_service(RUN, r.stack) == 0
    assert r.events == [("r", r.stack + 0x10, 8, 0)]
    assert not r.calls and not r.snapshots


@pytest.mark.parametrize("status", [0, 1, 2, 3, 4, 255, U64, 0x123400000003])
def test_queue_removes_only_low_al_one_or_three_and_frees_owned_nodes(status: int) -> None:
    r = Rig()
    nodes, actions = r.nodes([status])
    removed = status & 255 in (1, 3)
    assert r.run_service(RUN, r.stack) == (0 if removed else 1)
    assert r.mem.read(r.stack + 0x10, 8) == (0 if removed else nodes[0])
    assert r.called(DESTROY, "virtual_calls") == ([(actions[0], 1)] if removed else [])
    assert r.called(FREE_IMPORT, "imports") == ([(nodes[0],)] if removed else [])
    for at in nodes + actions:
        if removed:
            with pytest.raises(ReplayMemoryError):
                r.mem.read(at, 1)
        else:
            r.mem.read(at, 1)


def test_queue_mixed_head_and_interior_removals_preserve_kept_links() -> None:
    r = Rig()
    nodes, actions = r.nodes([1, 0, 3, 2])
    assert r.run_service(RUN, r.stack) == 2
    assert r.mem.read(r.stack + 0x10, 8) == nodes[1]
    assert r.mem.read(nodes[1] + 8, 8) == nodes[3]
    assert r.called(UPDATE, "virtual_calls") == [(a,) for a in actions]
    assert r.called(FREE_IMPORT, "imports") == [(nodes[0],), (nodes[2],)]


def test_queue_returns_full_kept_dword_beyond_al() -> None:
    r = Rig()
    r.nodes([0] * 257)
    assert r.run_service(RUN, r.stack) == 257


def test_queue_kept_next_is_read_after_action_callback() -> None:
    r = Rig()
    nodes, actions = r.nodes([0, 0])

    def update(args: tuple[int, ...]) -> int:
        r.mem.write(nodes[0] + 8, 8, 0)
        return 0

    r.handlers["virtual_calls", UPDATE] = update
    assert r.run_service(RUN, r.stack) == 1
    assert r.called(UPDATE, "virtual_calls") == [(actions[0],)]


def test_queue_removal_rereads_action_after_unlink_and_can_skip_destructor() -> None:
    r = Rig()
    nodes, actions = r.nodes([1])

    def mutate(at: int, width: int, value: int) -> None:
        if at == r.stack + 0x10:
            r.mem.write(nodes[0], 8, 0)

    r.after_write = mutate
    assert r.run_service(RUN, r.stack) == 0
    assert not r.called(DESTROY, "virtual_calls")
    assert r.mem.read(actions[0], 8) == r.action_table
    with pytest.raises(ReplayMemoryError):
        r.mem.read(nodes[0], 1)


def test_queue_holds_next_across_destructor_then_reads_current_free_import() -> None:
    r = Rig()
    nodes, actions = r.nodes([1, 0])

    def destroy(args: tuple[int, ...]) -> None:
        assert args == (actions[0], 1) and r.runtime.call is not None
        r.runtime.call(0x142D6BAB4, (args[0],), None)
        r.mem.write(nodes[0] + 8, 8, 0)
        r.mem.write(0x143199DD0, 8, OTHER_FREE)

    r.handlers["virtual_calls", DESTROY] = destroy
    assert r.run_service(RUN, r.stack) == 1
    assert r.called(UPDATE, "virtual_calls") == [(a,) for a in actions]
    assert r.called(OTHER_FREE, "imports") == [(nodes[0],)]


def test_queue_missing_al_refuses_before_reading_next() -> None:
    r = Rig()
    nodes, _ = r.nodes([0])
    r.handlers["virtual_calls", UPDATE] = lambda args: None
    with pytest.raises(ValueError, match="production action AL"):
        r.run_service(RUN, r.stack)
    assert not any(event[1] == nodes[0] + 8 for event in r.events)


@pytest.mark.parametrize("span", [-12, -1, 0, 1, 11, 12, 23, 24, 25])
@pytest.mark.parametrize("index", [0, 1, U64])
def test_threshold_literal_signed_span_and_unsigned_index(span: int, index: int) -> None:
    r = Rig()
    records = r.alloc(64) + 16
    r.mem.write(records + 2, 2, 0xFFF0)
    r.mem.write(records + 14, 2, 123)
    r.mem.write(r.master + 0x338, 8, records)
    r.mem.write(r.master + 0x340, 8, records + span)
    count = (abs(span) // 12 * (-1 if span < 0 else 1)) & U64
    expected = (0xFFF0 if index == 0 else 123) if index < count else 0
    assert r.run_service(THRESHOLD, r.master, index) == expected
    assert not r.calls and not r.snapshots


def test_threshold_begin_is_held_before_current_end_read() -> None:
    r = Rig()
    old, new = r.alloc(12), r.alloc(12)
    r.mem.write(old + 2, 2, 100)
    r.mem.write(new + 2, 2, 999)
    r.mem.write(r.master + 0x338, 8, old)
    r.mem.write(r.master + 0x340, 8, old + 12)

    def mutate(at: int, width: int, value: int) -> None:
        if at == r.master + 0x340:
            r.mem.write(r.master + 0x338, 8, new)

    r.after_read = mutate
    assert r.run_service(THRESHOLD, r.master, 0) == 100


@pytest.mark.parametrize(
    ("mode", "kind", "applied"),
    [(4, 0, False), (4, 0x32, True), (4, 0x4A3, True), (4, 0x761, False), (0, 0, True)],
)
def test_stage_game_mode_four_kind_gate_and_actual_application(
    mode: int, kind: int, applied: bool
) -> None:
    r = Rig()
    r.mode = mode
    r.kind(kind)
    assert r.run_service(STAGE, r.obj, 7) is None
    assert r.called(APPLY) == ([(r.obj, 7)] if applied else [])
    assert r.mem.read(r.obj + 0xE, 1) == (7 if applied else 0)
    assert bool(r.snapshots) == (mode == 4)


@pytest.mark.parametrize("replacement", [None, 255, 9])
def test_stage_low_dl_marker_replacement_and_live_private_home(replacement: int | None) -> None:
    r = Rig()
    r.mode = 0xABCDEF0000000004
    r.kind(0x32)
    marker = r.alloc(16) if replacement is not None else 0
    r.mem.write(r.obj + 0x138, 8, marker)
    if marker:
        assert replacement is not None
        r.mem.write(marker + 0xA, 1, replacement)

    def apply(args: tuple[int, ...]) -> None:
        assert r.live and r.mem.read(r.frame(8), 8) == 0x32
        if marker:
            assert r.mem.read(marker + 0xA, 1) == 255
        r.mem.write(args[0] + 0xE, 1, args[1])

    r.handlers["calls", APPLY] = apply
    r.run_service(STAGE, r.obj, 0x123400001B)
    assert r.called(APPLY) == [(r.obj, replacement if replacement not in (None, 255) else 0x1B)]


def test_stage_current_master_is_read_after_required_game_mode_effect() -> None:
    r = Rig()

    def mode(args: tuple[int, ...]) -> int:
        r.kind(0x4A3)
        return 4

    r.handlers["calls", MODE] = mode
    r.run_service(STAGE, r.obj, 8)
    assert r.called(APPLY) == [(r.obj, 8)]


def test_stage_marker_pointer_is_held_before_marker_read_mutates_object() -> None:
    r = Rig()
    old, new = r.alloc(16), r.alloc(16)
    r.mem.write(old + 0xA, 1, 8)
    r.mem.write(new + 0xA, 1, 9)
    r.mem.write(r.obj + 0x138, 8, old)

    def mutate(at: int, width: int, value: int) -> None:
        if at == old + 0xA:
            r.mem.write(r.obj + 0x138, 8, new)

    r.after_read = mutate
    r.run_service(STAGE, r.obj, 0x1B)
    assert r.called(APPLY) == [(r.obj, 8)]
    assert r.mem.read(old + 0xA, 1) == 255 and r.mem.read(new + 0xA, 1) == 9


def test_counter_reset_writes_only_dword_and_returns_known_zero_eax() -> None:
    r = Rig()
    r.mem.write(r.obj + 0x66C, 8, U64)
    assert r.run_service(RESET, r.obj) == 0
    assert r.mem.read(r.obj + 0x66C, 8) == 0xFFFFFFFF00000000
    assert r.events == [("w", r.obj + 0x66C, 4, 0)]


@pytest.mark.parametrize(
    ("identifier", "expected"),
    [
        (0, 0x100),
        (1, 0x101),
        (2, 0x102),
        (3, 0),
        (-1, 0x401),
        (-2, 0x402),
        (-3, 0x403),
        (-4, 0),
        (-(1 << 31), 0),
        (0x100000001, 0x101),
    ],
)
def test_world_lookup_primary_secondary_and_low_edx(identifier: int, expected: int) -> None:
    r = Rig()
    r.lookup_tables()
    assert r.run_service(LOOKUP, r.world, identifier & U64) == expected
    assert not r.calls and not r.snapshots


def test_world_lookup_minimum_signed_id_does_not_read_world() -> None:
    r = Rig()
    assert r.run_service(LOOKUP, r.world, 0x80000000) == 0
    assert not r.events


@pytest.mark.parametrize(("identifier", "count_field"), [(0, 0x174), (-1, 0x184)])
def test_world_lookup_counts_are_signed(identifier: int, count_field: int) -> None:
    r = Rig()
    r.lookup_tables()
    r.mem.write(r.world + count_field, 4, U32)
    assert r.run_service(LOOKUP, r.world, identifier & U64) == 0
    assert not any(event[1] in (r.world + 0x168, r.world + 0x178) for event in r.events)


def test_world_lookup_null_primary_returns_zero_but_secondary_requires_backing() -> None:
    r = Rig()
    r.lookup_tables()
    r.mem.write(r.world + 0x168, 8, 0)
    assert r.run_service(LOOKUP, r.world, 0) == 0
    r.mem.write(r.world + 0x178, 8, 0)
    with pytest.raises(ReplayMemoryError):
        r.run_service(LOOKUP, r.world, U64)


def test_world_lookup_reads_current_table_after_count_read() -> None:
    r = Rig()
    _, secondary = r.lookup_tables()

    def mutate(at: int, width: int, value: int) -> None:
        if at == r.world + 0x174:
            r.mem.write(r.world + 0x168, 8, secondary)

    r.after_read = mutate
    assert r.run_service(LOOKUP, r.world, 1) == 0x401


@pytest.mark.parametrize("channel", ["calls", "virtual_calls", "imports"])
def test_missing_required_capability_refuses_at_reached_prefix(channel: str) -> None:
    r = Rig()
    r.services = r.bind_services(**{channel: ReplayTaskRebuildCalls(None)})
    if channel == "calls":
        target = MODE
        entry, args = STAGE, (r.obj, 1)
    else:
        nodes, actions = r.nodes([1])
        target = UPDATE if channel == "virtual_calls" else FREE_IMPORT
        entry, args = RUN, (r.stack,)
    with pytest.raises(UnresolvedReplayTaskRebuild, match=f"reached{target:x} is unavailable"):
        r.run_service(entry, *args)
    if channel == "imports":
        assert r.mem.read(r.stack + 0x10, 8) == 0
        with pytest.raises(ReplayMemoryError):
            r.mem.read(actions[0], 1)
        r.mem.read(nodes[0], 1)
    assert not r.live


def test_bad_capability_and_missing_game_mode_annotation_refuse() -> None:
    r = Rig()
    with pytest.raises(ValueError):
        r.bind_services(imports=cast(ReplayTaskRebuildCalls, None))
    r.handlers["calls", MODE] = lambda args: None
    with pytest.raises(ValueError, match="Game mode EAX"):
        r.run_service(STAGE, r.obj, 1)
    assert not r.called(APPLY) and not r.snapshots


def test_actual_building_threshold_queue_runner_and_owned_destructors_compose() -> None:
    r = Rig()
    r.construction_data()
    old = r.stack
    r.stack = r.queue
    nodes, _ = r.nodes([1, 0, 3, 2])
    r.stack = old
    r.threshold = 999
    r.compose_building()
    assert r.run_building() == 0xFA
    assert r.rectangles == [(r.resource, 7, 16, 12, 23, 0)]
    assert r.mem.read(r.obj + 0x84D, 1) == 2
    assert r.mem.read(r.queue + 0x10, 8) == nodes[1]
    assert r.mem.read(nodes[1] + 8, 8) == nodes[3]


def test_actual_building_staged_threshold_and_stage_service_compose() -> None:
    r = Rig()
    r.construction_data()
    r.kind(0x32)
    r.compose_building()
    assert r.run_building() == 0xFA
    assert r.called(APPLY) == [(r.obj, 30)]
    assert r.mem.read(r.obj + 0xE, 1) == 30


def test_actual_building_member_repair_counter_reset() -> None:
    r = Rig()
    r.active_building(1000)
    _, members, _ = r.make_members(1)
    r.mem.write(members[0] + 0x66C, 4, U32)
    r.mem.write(r.master + 0x460, 4, bits(2.0))
    r.compose_building()
    assert r.run_building() == 0xFA
    assert r.mem.read(members[0] + 0x66C, 4) == 0


def test_actual_building_world_lookup_and_memmove_skip_shifted_id() -> None:
    r = Rig()
    r.kind(0x765)
    primary, ids = r.alloc(104 * 8), r.alloc(12)
    r.mem.write(primary + 102 * 8, 8, r.other)
    r.mem.write(primary + 103 * 8, 8, r.other)
    r.mem.write(r.world + 0x168, 8, primary)
    r.mem.write(r.world + 0x174, 4, 104)
    for i, value in enumerate((101, 102, 103)):
        r.mem.write(ids + i * 4, 4, value)
    r.mem.write(r.obj + 0x828, 8, ids)
    r.mem.write(r.obj + 0x830, 8, ids + 12)
    r.mem.write(r.other + 0x168, 4, bits(7.0))
    _, actions = r.nodes([0])
    r.compose_building()
    assert r.run_building() == 0xFA
    assert r.called(TASK, "task_fp_calls") == [(actions[0], bits(7.0))]
    assert r.mem.read(r.obj + 0x830, 8) == ids + 8
    assert r.mem.read(ids, 4) == 102


def test_actual_services_building_and_inherited_object_list_chain() -> None:
    r = Rig()
    r.compose_building()
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
    assert r.mem.read(r.obj + 0x84D, 1) == 0
    assert len(r.called(CLOCK)) == 5
