"""Owned health/resource effects and source-order controls for three FP bodies.

Eligibility, scalar getters/setter, color/option decisions and event delivery
are explicit authored effects unless a case enables existing predicate bodies.
No original Game instructions, process memory or recording World run here.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import fields, replace
from typing import cast

import pytest
from test_replay_action_object_update import U32, U64, decoded, encoded
from test_replay_building_object_update import MAX_A, MAX_B
from test_replay_building_object_update import REPAIR as SELF_REPAIR
from test_replay_building_services import Rig as ServicesRig
from test_replay_unit_object_update import (
    HEAL,
    HEALTH,
    MAXIMUM,
    bits,
    health_decoded,
    health_encoded,
)

from vantage.replay_binary32 import add_binary32
from vantage.replay_object_health_repair import (
    ReplayObjectHealthRepairProfile,
    bind_replay_object_health_repair,
)
from vantage.replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    UnresolvedReplayTaskRebuild,
)

INCREMENT, REPAIR, COST = 0x141252890, 0x1412C8D20, 0x1417015D0
CHECK, COLOR, OPTION, EVENT = 0x1416E59E0, 0x141734F30, 0x14172AC80, 0x140A635D0
OTHER_MAXIMUM = 0xF500D0
CHANNELS = (
    "calls",
    "virtual_fp_calls",
    "virtual_fp_apply_calls",
    "cost_check_fp_home_calls",
    "resource_event_home_calls",
)


class Rig(ServicesRig):
    def __init__(self) -> None:
        super().__init__()
        self.permitted = 1
        self.colored, self.option = 1, 0
        self.real_predicates = False
        self.check_homes: list[tuple[bytes, bytes, bytes]] = []
        self.catalog = self.alloc(0x400)
        self.mem.write(self.owner + 0x28, 8, self.catalog)
        for kind in (0, 0x32):
            self.mem.write(self.catalog + kind * 8, 8, self.master)
        self.mem.write(self.resource + 0x870, 8, encoded(bits(1.0)))
        self.hp_profile = ReplayObjectHealthRepairProfile(
            bytes([0xC1]) * 8, bytes([0xC2]) * 8, bytes([0xC3]) * 0x38
        )
        self.health_body = self.bind_health()

    def bind_health(self, **overrides: ReplayTaskRebuildCalls) -> ReplayTaskRebuildCalls:
        channels = {
            name: ReplayTaskRebuildCalls(self.channel(name)) for name in CHANNELS if name != "calls"
        }
        channels["calls"] = ReplayTaskRebuildCalls(self.ordinary)
        channels["fp_calls"] = ReplayTaskRebuildCalls(self.channel("fp_calls"))
        channels.update(overrides)
        fallback = channels.pop("fp_calls")
        return bind_replay_object_health_repair(
            self.context,
            fallback,
            **channels,
            bind_local=self.local,
            profile=self.hp_profile,
            mxcsr=0x1F80,
        )

    def ordinary(self, target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        if target not in (COLOR, OPTION) or self.real_predicates:
            return super().ordinary(target, args, data)
        assert data is None
        if handler := self.record("calls", target, args):
            return handler(args)
        return self.colored if target == COLOR else self.option

    def apply_health(self, args: tuple[int, ...]) -> None:
        current = health_decoded(self.mem.read(args[0] + 0x130, 8))
        result = add_binary32(current & U32, args[1])
        self.mem.write(args[0] + 0x130, 8, health_encoded(current & ~U32 | result))

    def channel(
        self, channel: str
    ) -> Callable[[int, tuple[int, ...], memoryview | None], int | None]:
        fallback = super().channel(channel)

        def dispatch(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
            local = (
                channel in ("fp_calls", "cost_check_fp_home_calls")
                or (channel == "virtual_fp_calls" and target in (HEALTH, MAXIMUM, OTHER_MAXIMUM))
                or (channel == "virtual_fp_apply_calls" and target == HEAL)
            )
            if not local:
                return fallback(target, args, data)
            assert data is None
            if handler := self.record(channel, target, args):
                return handler(args)
            if channel == "cost_check_fp_home_calls" and target == CHECK:
                self.check_homes.append(tuple(self.mem.read_bytes(at, 8) for at in args[-3:]))
                return self.permitted
            if channel == "virtual_fp_apply_calls" and target == HEAL:
                self.apply_health(args)
                return None
            if channel == "virtual_fp_calls":
                if target == HEALTH:
                    return health_decoded(self.mem.read(args[0] + 0x130, 8)) & U32
                if target == MAXIMUM:
                    encoded_master = self.mem.read(args[0] + 0x10, 8)
                    master = (encoded_master - 0x6A586EB28AC201FC - 0x0CF19788B2554E70) & U64
                    maximum = (self.mem.read(master + 0x68, 8) ^ MAX_A ^ MAX_B) & 0xFFFF
                    signed = maximum if maximum < 0x8000 else maximum - 0x10000
                    return bits(float(signed))
            raise UnresolvedReplayTaskRebuild(f"authored {channel} missing{target:x}")

        return dispatch

    def run_health(self, target: int, *args: int) -> int | None:
        assert self.health_body.call is not None
        return self.health_body.call(target, args, None)

    def repair_data(self, hp: float = 5.0, threshold: int = 100) -> None:
        self.set_health(bits(hp))
        self.object_class(2)
        self.kind(0x32)
        records = self.alloc(12)
        self.mem.write(records + 2, 2, threshold & 0xFFFF)
        self.mem.write(self.master + 0x338, 8, records)
        self.mem.write(self.master + 0x340, 8, records + 12)
        self.cost_rows([])

    def cost_rows(self, rows: list[tuple[int, int, int]]) -> None:
        assert len(rows) <= 3
        rows = [*rows, *((-1, 0, 0) for _ in range(3 - len(rows)))]
        for i, (resource_id, coefficient, enabled) in enumerate(rows):
            at = self.master + 0x320 + i * 6
            self.mem.write(at, 2, resource_id & 0xFFFF)
            self.mem.write(at + 2, 2, coefficient & 0xFFFF)
            self.mem.write(at + 4, 1, enabled)


@pytest.mark.parametrize("field", [f.name for f in fields(ReplayObjectHealthRepairProfile)])
def test_private_profile_requires_exact_immutable_seed(field: str) -> None:
    r = Rig()
    for seed in (b"", bytearray(getattr(r.hp_profile, field))):
        with pytest.raises(ValueError):
            replace(r.hp_profile, **{field: seed})


@pytest.mark.parametrize(("target", "arity"), [(INCREMENT, 2), (REPAIR, 2), (COST, 4)])
def test_entry_shape_and_raw_fp_width_refuse_before_effects(target: int, arity: int) -> None:
    r = Rig()
    assert r.health_body.call is not None
    bad_fp = [r.obj] * arity
    bad_fp[2 if target == COST else 1] = 1 << 32
    for args, data in (
        ((), None),
        ((-1,) * arity, None),
        (tuple(bad_fp), None),
        ((0,) * arity, memoryview(b"raw")),
    ):
        with pytest.raises(ValueError):
            r.health_body.call(target, args, data)
    assert not r.events and not r.calls


def test_unknown_mixed_fp_calls_preserve_identity() -> None:
    r = Rig()
    args, data, result = (-1, 4), memoryview(b"raw"), 123456789012345

    def unknown(target: int, given: tuple[int, ...], payload: memoryview | None) -> int:
        assert target == 17 and given is args and payload is data
        return result

    bound = r.bind_health(fp_calls=ReplayTaskRebuildCalls(unknown))
    assert bound.call is not None and bound.call(17, args, data) is result


@pytest.mark.parametrize(
    ("hp", "delta", "expected", "result"),
    [
        (5.0, 10.0, 15.0, 0),
        (5.0, 95.0, 100.0, 1),
        (5.0, 195.0, 100.0, 1),
        (5.0, -10.0, 1.0, 0),
        (5.0, -5.0, 1.0, 0),
        (5.0, -1.0, 4.0, 0),
        (0.0, -0.0, 0.0, 0),
        (100.0, 0.0, 100.0, 1),
    ],
)
def test_actual_health_application_floor_and_equal_or_greater_maximum_clamp(
    hp: float, delta: float, expected: float, result: int
) -> None:
    r = Rig()
    r.set_health(bits(hp))
    assert r.run_health(INCREMENT, r.obj, bits(delta)) == result
    assert health_decoded(r.mem.read(r.obj + 0x130, 8)) & U32 == bits(expected)
    assert r.called(HEAL, "virtual_fp_apply_calls") == [(r.obj, bits(delta))]


@pytest.mark.parametrize(("delta", "expected_high"), [(-10.0, 0x11223344), (195.0, 0x55667788)])
def test_floor_preserves_health_upper_half_but_clamp_uses_master_upper_half(
    delta: float, expected_high: int
) -> None:
    r = Rig()
    r.set_health(bits(5.0), 0x11223344)
    r.mem.write(r.master + 0x68, 8, (0x55667788 << 32 | 100) ^ MAX_A ^ MAX_B)
    r.run_health(INCREMENT, r.obj, bits(delta))
    assert health_decoded(r.mem.read(r.obj + 0x130, 8)) >> 32 == expected_high


def test_floor_captures_encoded_health_before_one_constant_read() -> None:
    r = Rig()
    r.set_health(bits(5.0), 0x11223344)

    def mutate(at: int, width: int, value: int) -> None:
        if at == 0x1436A0294:
            r.mem.write(r.obj + 0x130, 8, health_encoded(bits(999.0)))

    r.after_read = mutate
    r.run_health(INCREMENT, r.obj, bits(-10.0))
    assert health_decoded(r.mem.read(r.obj + 0x130, 8)) == 0x112233443F800000


def test_increment_holds_both_getter_targets_before_first_getter_callback() -> None:
    r = Rig()
    r.set_health(bits(5.0))

    def hp(args: tuple[int, ...]) -> int:
        r.mem.write(r.table + 0xD0, 8, OTHER_MAXIMUM)
        return bits(5.0)

    r.handlers["virtual_fp_calls", HEALTH] = hp
    assert r.run_health(INCREMENT, r.obj, 0) == 0
    assert r.called(MAXIMUM, "virtual_fp_calls") == [(r.obj,)]
    assert not r.called(OTHER_MAXIMUM, "virtual_fp_calls")


def test_increment_clamp_uses_current_protected_master_after_getters() -> None:
    r = Rig()
    r.set_health(bits(120.0))

    def maximum(args: tuple[int, ...]) -> int:
        r.mem.write(r.master + 0x68, 8, (0xAABBCCDD << 32 | 40) ^ MAX_A ^ MAX_B)
        return bits(100.0)

    r.handlers["virtual_fp_calls", MAXIMUM] = maximum
    assert r.run_health(INCREMENT, r.obj, 0) == 1
    assert health_decoded(r.mem.read(r.obj + 0x130, 8)) == 0xAABBCCDD42200000


@pytest.mark.parametrize("nan_target", [HEALTH, MAXIMUM])
def test_unordered_getter_comparison_skips_clamp(nan_target: int) -> None:
    r = Rig()
    r.set_health(bits(5.0))
    r.handlers["virtual_fp_calls", nan_target] = lambda args: 0x7FC12345
    assert r.run_health(INCREMENT, r.obj, 0) == 0
    assert not r.snapshots


def test_ordinary_repair_tail_ends_private_view_before_health_application() -> None:
    r = Rig()
    r.set_health(bits(5.0))

    def apply(args: tuple[int, ...]) -> None:
        assert not any(size == 8 for size, _ in r.live)
        r.apply_health(args)

    r.handlers["virtual_fp_apply_calls", HEAL] = apply
    assert r.run_health(REPAIR, r.obj, bits(2.0)) == 0
    assert health_decoded(r.mem.read(r.obj + 0x130, 8)) & U32 == bits(7.0)
    assert not r.called(CHECK, "cost_check_fp_home_calls")


@pytest.mark.parametrize("object_class", [0x14, 0x15, 0x16, 2, 0x35])
def test_special_repair_scales_actual_health_and_uses_actual_cost_body(object_class: int) -> None:
    r = Rig()
    r.repair_data()
    r.object_class(object_class)
    assert r.run_health(REPAIR, r.obj, bits(2.0)) == 0
    assert health_decoded(r.mem.read(r.obj + 0x130, 8)) & U32 == bits(7.0)
    assert [args[3] for args in r.called(CHECK, "cost_check_fp_home_calls")] == [bits(0.02)]


def test_repair_checks_each_class_again_after_current_master_mutation() -> None:
    r = Rig()
    r.repair_data()
    r.object_class(0)
    class_reads = 0

    def mutate(at: int, width: int, value: int) -> None:
        nonlocal class_reads
        if at == r.master + 0x38:
            class_reads += 1
            if class_reads == 1:
                r.object_class(0x15)

    r.after_read = mutate
    r.run_health(REPAIR, r.obj, bits(2.0))
    assert class_reads == 2 and r.called(CHECK, "cost_check_fp_home_calls")


def test_special_repair_clamps_delta_and_applies_exact_owned_resource_cost() -> None:
    r = Rig()
    r.repair_data(99.0)
    r.cost_rows([(0, 20, 1)])
    r.mem.write(r.resource, 8, encoded(bits(100.0)))
    assert r.run_health(REPAIR, r.obj, bits(2.0)) == 1
    assert health_decoded(r.mem.read(r.obj + 0x130, 8)) & U32 == bits(100.0)
    assert decoded(r.mem.read(r.resource, 8)) & U32 == bits(99.8)
    assert r.called(HEAL, "virtual_fp_apply_calls") == [(r.obj, bits(1.0))]


def test_refused_repair_returns_two_and_skips_health_application() -> None:
    r = Rig()
    r.repair_data()
    r.permitted = 0
    assert r.run_health(REPAIR, r.obj, bits(2.0)) == 2
    assert not r.called(HEAL, "virtual_fp_apply_calls")
    assert health_decoded(r.mem.read(r.obj + 0x130, 8)) & U32 == bits(5.0)


def test_negative_signed_threshold_is_used_for_health_and_resource_arithmetic() -> None:
    r = Rig()
    r.repair_data(threshold=-100)
    r.cost_rows([(0, 20, 1)])
    r.mem.write(r.resource, 8, encoded(bits(100.0)))
    assert r.run_health(REPAIR, r.obj, bits(2.0)) == 0
    assert health_decoded(r.mem.read(r.obj + 0x130, 8)) & U32 == bits(3.0)
    assert decoded(r.mem.read(r.resource, 8)) & U32 == bits(100.4)


def test_zero_threshold_raw_nan_reaches_required_cost_check() -> None:
    r = Rig()
    r.repair_data(threshold=0)
    r.permitted = 0
    assert r.run_health(REPAIR, r.obj, 0) == 2
    amount = r.called(CHECK, "cost_check_fp_home_calls")[0][3]
    assert amount & 0x7F800000 == 0x7F800000 and amount & 0x7FFFFF
    assert not r.called(HEAL, "virtual_fp_apply_calls")


def test_repair_health_result_consumption_follows_current_vptr_read() -> None:
    r = Rig()
    r.repair_data()
    r.handlers["virtual_fp_calls", HEALTH] = lambda args: None
    with pytest.raises(ValueError, match="repair health getter XMM0"):
        r.run_health(REPAIR, r.obj, bits(2.0))
    assert r.events[-1][:3] == ("r", r.obj, 8)
    assert not r.called(MAXIMUM, "virtual_fp_calls")


def test_repair_cost_maximum_annotation_is_consumed_after_fresh_master_decode() -> None:
    r = Rig()
    r.repair_data()
    calls = 0

    def maximum(args: tuple[int, ...]) -> int | None:
        nonlocal calls
        calls += 1
        return bits(100.0) if calls == 1 else None

    r.handlers["virtual_fp_calls", MAXIMUM] = maximum
    with pytest.raises(ValueError, match="repair cost maximum XMM0"):
        r.run_health(REPAIR, r.obj, bits(2.0))
    assert r.events[-1] == ("r", r.events[-2][1], 8, r.master)
    assert r.events[-2] == ("w", r.events[-1][1], 8, r.master)


def test_cost_check_receives_partial_live_homes_before_any_master_lookup() -> None:
    r = Rig()
    r.permitted = 0
    assert r.run_health(COST, r.owner, 0x123400000032, bits(0.5), 0xABCDEF0000000007) == 0
    assert r.check_homes == [
        (b"\x07\x00\x00\x00" + b"\xc3" * 4, bytes(4) + b"\xc3" * 4, bytes(4) + b"\xc3" * 4)
    ]
    assert not any(e[1] == r.owner + 0x28 for e in r.events)
    args = r.called(CHECK, "cost_check_fp_home_calls")[0]
    assert args[:4] == (r.owner, 0x32, 0, bits(0.5))


def test_cost_check_missing_al_refuses_before_master_lookup() -> None:
    r = Rig()
    r.handlers["cost_check_fp_home_calls", CHECK] = lambda args: None
    with pytest.raises(ValueError, match="repair cost check AL"):
        r.run_health(COST, r.owner, 0, bits(1.0), 1)
    assert not any(event[1] == r.owner + 0x28 for event in r.events)


def test_cost_three_records_mutate_resources_and_encode_seed_upper_half() -> None:
    r = Rig()
    r.cost_rows([(0, 20, 1), (1, -4, 1), (2, 999, 0)])
    for i in range(3):
        r.mem.write(r.resource + i * 8, 8, encoded(0x1122334400000000 | bits(100.0)))
    assert r.run_health(COST, r.owner, 0, bits(0.5), 1) == 1
    assert decoded(r.mem.read(r.resource, 8)) == 0xC3C3C3C300000000 | bits(90.0)
    assert decoded(r.mem.read(r.resource + 8, 8)) == 0xC3C3C3C300000000 | bits(102.0)
    assert decoded(r.mem.read(r.resource + 16, 8)) == 0x1122334400000000 | bits(100.0)
    assert [args[2:4] for args in r.called(EVENT, "resource_event_home_calls")] == [(0, 2), (1, 2)]


@pytest.mark.parametrize(
    ("colored", "option", "published"), [(1, 0, True), (0, 1, True), (0, 0, False)]
)
def test_cost_predicate_short_circuit_controls_required_event(
    colored: int, option: int, published: bool
) -> None:
    r = Rig()
    r.colored, r.option = colored, option
    r.cost_rows([(0, 2, 1)])
    r.mem.write(r.resource, 8, encoded(bits(10.0)))
    r.run_health(COST, r.owner, 0, bits(1.0), 1)
    assert bool(r.called(OPTION)) == (colored == 0)
    assert bool(r.called(EVENT, "resource_event_home_calls")) == published
    assert decoded(r.mem.read(r.resource, 8)) & U32 == bits(8.0)


@pytest.mark.parametrize("observer_matches", [False, True])
def test_cost_actual_color_and_option_predicate_bodies_compose(observer_matches: bool) -> None:
    r = Rig()
    r.real_predicates = True
    r.mem.write(r.world + 0x6B0, 4, 1 if observer_matches else 99)
    r.cost_rows([(0, 2, 1)])
    r.mem.write(r.resource, 8, encoded(bits(10.0)))
    assert r.run_health(COST, r.owner, 0, bits(1.0), 1) == 1
    assert bool(r.called(OPTION)) == (not observer_matches)
    assert r.called(COLOR) == [(r.owner,)]
    assert r.called(EVENT, "resource_event_home_calls")


def test_cost_source_h50_high_half_is_current_after_event_callback() -> None:
    r = Rig()
    r.cost_rows([(0, 2, 1), (1, 4, 1)])
    for i in range(2):
        r.mem.write(r.resource + i * 8, 8, encoded(bits(100.0)))

    def event(args: tuple[int, ...]) -> None:
        r.mem.write(r.frame(0x38) + 0x34, 4, 0xAABBCCDD)

    r.handlers["resource_event_home_calls", EVENT] = event
    r.run_health(COST, r.owner, 0, bits(1.0), 1)
    assert decoded(r.mem.read(r.resource, 8)) >> 32 == 0xC3C3C3C3
    assert decoded(r.mem.read(r.resource + 8, 8)) >> 32 == 0xAABBCCDD


def test_cost_reads_next_row_after_effect_and_holds_current_resource_destination() -> None:
    r = Rig()
    r.cost_rows([(0, 2, 1), (1, 4, 1)])
    other = r.alloc(0x900)
    for resources in (r.resource, other):
        for i in range(2):
            r.mem.write(resources + i * 8, 8, encoded(bits(100.0)))
    changed = False

    def mutate(at: int, width: int, value: int) -> None:
        nonlocal changed
        if at == r.frame(0x38) + 0x30 and not changed:
            changed = True
            r.mem.write(r.owner + 0x98, 8, other)

    def event(args: tuple[int, ...]) -> None:
        r.mem.write(r.master + 0x328, 2, 8)

    r.after_write = mutate
    r.handlers["resource_event_home_calls", EVENT] = event
    r.run_health(COST, r.owner, 0, bits(1.0), 1)
    assert decoded(r.mem.read(r.resource, 8)) & U32 == bits(98.0)
    assert decoded(r.mem.read(other, 8)) & U32 == bits(100.0)
    assert decoded(r.mem.read(other + 8, 8)) & U32 == bits(92.0)


@pytest.mark.parametrize("channel", CHANNELS)
def test_missing_channel_refuses_at_exact_reached_target(channel: str) -> None:
    r = Rig()
    if channel in ("virtual_fp_calls", "virtual_fp_apply_calls"):
        target = HEALTH if channel == "virtual_fp_calls" else HEAL
        entry, args = INCREMENT, (r.obj, 0)
    else:
        r.cost_rows([(0, 1, 1)])
        r.mem.write(r.resource, 8, encoded(bits(10.0)))
        target = (
            COLOR
            if channel == "calls"
            else CHECK
            if channel == "cost_check_fp_home_calls"
            else EVENT
        )
        entry, args = COST, (r.owner, 0, bits(1.0), 1)
    r.health_body = r.bind_health(**{channel: ReplayTaskRebuildCalls(None)})
    with pytest.raises(UnresolvedReplayTaskRebuild, match=f"reached{target:x} is unavailable"):
        r.run_health(entry, *args)
    assert not r.live


def test_invalid_capability_and_mxcsr_refuse_before_effects() -> None:
    r = Rig()
    with pytest.raises(ValueError):
        r.bind_health(calls=cast(ReplayTaskRebuildCalls, None))
    for mxcsr in (True, 0, 0x1F81, 0x3F80):
        with pytest.raises(ValueError):
            bind_replay_object_health_repair(
                r.context,
                ReplayTaskRebuildCalls(None),
                **{name: ReplayTaskRebuildCalls(None) for name in CHANNELS},
                bind_local=r.local,
                profile=r.hp_profile,
                mxcsr=mxcsr,
            )
    assert not r.events


def test_building_actual_special_repair_cost_health_and_counter_reset_compose() -> None:
    r = Rig()
    r.active_building(1000)
    r.cost_rows([(0, 20, 1)])
    r.mem.write(r.resource, 8, encoded(bits(100.0)))
    _, members, masters = r.make_members(1)
    member, master = members[0], masters[0]
    r.mem.write(member + 0x18, 8, r.owner)
    r.mem.write(member + 0x130, 8, health_encoded(bits(99.0)))
    r.mem.write(member + 0x66C, 4, U32)
    r.mem.write(master + 0x18, 8, (0x32 + 0x47E37DFF0616CE4F) ^ 0x349E37847AD69F19)
    r.mem.write(master + 0x38, 8, (2 - 0x5B32AA7995D95916 + 0x50A06BCECEBEF905) & U64)
    records = r.alloc(12)
    r.mem.write(records + 2, 2, 100)
    r.mem.write(master + 0x338, 8, records)
    r.mem.write(master + 0x340, 8, records + 12)
    r.mem.write(r.master + 0x460, 4, bits(2.0))
    r.compose_building()
    r.building = r.bind_building(repair_fp_calls=r.health_body)
    assert r.run_building() == 0xFA
    assert health_decoded(r.mem.read(member + 0x130, 8)) & U32 == bits(100.0)
    assert decoded(r.mem.read(r.resource, 8)) & U32 == bits(99.8)
    assert r.mem.read(member + 0x66C, 4) == 0
    assert not r.called(SELF_REPAIR, "repair_fp_calls")
