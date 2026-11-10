"""Receipts include bonus yield; source ambiguity never creates phantom money."""

from __future__ import annotations

from copy import deepcopy

import pytest

from vantage import world as W
from vantage.gamedata import GameData
from vantage.patch import Node
from vantage.resource_review import TARGET2, ResourceHistory
from vantage.schema import SCHEMA


def scene(civ: int = 1) -> tuple[ResourceHistory, Node, Node, Node, Node]:
    attrs = Node(SCHEMA.model_id("PlayerAttributes"), {})
    master = Node(SCHEMA.model_id("MasterCombatEntity"), {W.M_CLASS: 4, W.M_TYPE: 70})
    site_master = Node(
        SCHEMA.model_id("MasterBuildingEntity"), {W.M_CLASS: 3, W.M_TYPE: 80, W.M_RADIUS_X: 2}
    )
    player = Node(
        SCHEMA.model_id("Player"),
        {W.P_CIV: civ, W.P_ATTR: attrs, W.P_MASTERS: {83: master, 109: site_master}},
    )
    action = Node(
        SCHEMA.model_id("GatherAction"),
        {W.A_TYPE: 110, W.A_STATE: 7, W.A_TARGET: 999, TARGET2: 200},
    )
    worker = Node(
        SCHEMA.model_id("CombatEntity"),
        {
            W.E_OWNER: 1,
            W.E_MASTER: 83,
            W.E_STATE: 2,
            W.E_HELD_TYPE: 3,
            W.E_HELD_AMT: 0,
            W.E_X: 10,
            W.E_Y: 10,
            W.E_ACTION: action,
        },
    )
    site = Node(
        SCHEMA.model_id("BuildingEntity"),
        {W.E_OWNER: 1, W.E_MASTER: 109, W.E_STATE: 2, W.E_X: 11, W.E_Y: 11, W.B_BUILT: True},
    )
    world = Node(
        SCHEMA.model_id("World"), {W.W_PLAYERS: {1: player}, W.W_ENTITIES: {100: worker, 200: site}}
    )
    history = ResourceHistory(GameData(None))
    history._site_rules = {109: {"food", "wood", "gold", "stone"}}
    return history, world, worker, attrs, master


def attr(node: Node, name: str, value: float) -> None:
    node.fields[SCHEMA.fid(SCHEMA.model_id("PlayerAttributes"), name)] = value


def carry_bonus(master: Node, multiplier: int, output: int = 3) -> None:
    master.fields[W.M_TASKS] = [
        Node(
            SCHEMA.model_id("Task"),
            {
                W.TASK_ACTION: 164,
                W.TASK_ATTR: -1,
                W.TASK_ATTR2: multiplier,
                W.TASK_ATTR3: output,
                W.TASK_VAL1: 0.01,
            },
        )
    ]


def tick(
    history: ResourceHistory,
    world: Node,
    time: int,
    *,
    handicaps: dict[int, int] | None = None,
    **kwargs: bool,
) -> None:
    history.sample(world, time, [], handicaps=handicaps, **kwargs)
    history.checkpoint(time)


@pytest.mark.parametrize("stockpile", [11, 1])
def test_malian_dropoff_credits_full_stockpile_amount_not_visible_load(stockpile: int) -> None:
    h, w, worker, attrs, master = scene(26)
    carry_bonus(master, 276)
    tick(h, w, 0)
    worker.fields[W.E_HELD_AMT] = 10
    tick(h, w, 1000)
    worker.fields[W.E_HELD_AMT] = 0
    attr(attrs, "goldTotal", 11)
    # Spending ten gold in the same frame does not erase a delivery of eleven.
    attr(attrs, "gold", stockpile)
    tick(h, w, 2000)
    assert h.entity(100, 2000)["collected"]["gold"] == 10
    assert h.entity(100, 2000)["credited"]["gold"] == 11
    assert h.entity(200, 2000)["dropped_off"]["gold"] == 11
    assert h.player(1, 2000)["bonus"]["gold"] == 1
    assert h.entity(200, 1500)["dropped_off"]["gold"] == 0


def test_drop_and_resume_between_frames_recovers_missing_gathered_tail() -> None:
    h, w, worker, attrs, master = scene(62)
    carry_bonus(master, 299, 0)
    worker.fields[W.E_HELD_TYPE] = 0
    tick(h, w, 0)
    worker.fields[W.E_HELD_AMT] = 9.7
    tick(h, w, 1000)
    worker.fields[W.E_HELD_AMT] = 0.2
    attr(attrs, "foodTotal", 10.501)
    tick(h, w, 1500)
    assert h.entity(100, 1500)["collected"]["food"] == 10.2
    assert h.entity(100, 1500)["credited"]["food"] == 10.5
    assert h.entity(200, 1500)["dropped_off"]["food"] == 10.5
    assert h.player(1, 1500)["bonus"]["food"] == 0.5


def test_secondary_resource_paid_to_same_camp_and_not_double_counted() -> None:
    h, w, worker, attrs, master = scene(24)
    carry_bonus(master, 267, 1)
    worker.fields[W.E_HELD_TYPE] = 0
    tick(h, w, 0)
    worker.fields[W.E_HELD_AMT] = 10
    tick(h, w, 1000)
    worker.fields[W.E_HELD_AMT] = 0
    attr(attrs, "foodTotal", 10)
    attr(attrs, "woodTotal", 3.33333)
    tick(h, w, 2000)
    assert h.entity(200, 2000)["dropped_off"]["wood"] == 3.3
    assert h.entity(100, 2000)["credited"]["wood"] == 3.3
    assert h.player(1, 2000)["bonus"]["wood"] == 3.3
    assert sum(row["total"] for row in h.player(1, 2000)["sources"]) == 13.3


@pytest.mark.parametrize("change", ["death", "conversion", "gap", "no_receipt"])
def test_carry_loss_does_not_become_a_delivery(change: str) -> None:
    h, w, worker, attrs, _ = scene()
    tick(h, w, 0)
    worker.fields[W.E_HELD_AMT] = 10
    tick(h, w, 1000)
    worker.fields[W.E_HELD_AMT] = 0
    if change == "death":
        worker.fields[W.E_STATE] = 3
    if change == "conversion":
        worker.fields[W.E_OWNER] = 0
    if change != "no_receipt":
        attr(attrs, "goldTotal", 10)
    tick(h, w, 2000, discontinuity=change == "gap")
    assert h.entity(200, 2000)["dropped_off"]["gold"] == 0
    if change == "gap":
        assert h.entity(100, 2000)["has_gaps"]


def test_ambiguous_camps_are_not_assigned_by_nearest_distance() -> None:
    h, w, worker, attrs, _ = scene()
    entities = w.fields[W.W_ENTITIES]
    entities[201] = Node(entities[200].model, dict(entities[200].fields))
    worker.fields[W.E_ACTION].fields[TARGET2] = -1
    tick(h, w, 0)
    worker.fields[W.E_HELD_AMT] = 10
    tick(h, w, 1000)
    worker.fields[W.E_HELD_AMT] = 0
    attr(attrs, "goldTotal", 10)
    tick(h, w, 2000)
    assert h.entity(200, 2000)["dropped_off"]["gold"] == 0
    assert h.entity(201, 2000)["dropped_off"]["gold"] == 0
    assert h.entity(100, 2000)["credited"]["gold"] == 10
    assert h.entity(200, 2000)["ambiguous_dropoffs"] == 1
    assert h.entity(201, 2000)["ambiguous_dropoffs"] == 1


def test_late_join_does_not_import_entire_player_income_into_a_worker() -> None:
    h, w, worker, attrs, _ = scene()
    worker.fields[W.E_HELD_AMT] = 8
    attr(attrs, "goldTotal", 10000)
    tick(h, w, 900000)
    assert h.entity(100, 900000)["collected"]["gold"] == 0
    assert h.player(1, 900000)["total"] == 0
    assert h.entity(100, 900000)["observed_from_ms"] == 900000


def test_relic_counter_and_unknown_income_are_separate_from_bonus_estimates() -> None:
    h, w, _, attrs, _ = scene()
    tick(h, w, 0)
    attr(attrs, "relicIncomeCostSummation", 4)
    attr(attrs, "goldTotal", 15)
    tick(h, w, 1000)
    result = h.player(1, 1000)
    assert result["total"] == 4
    assert {r["source"]: r["total"] for r in result["sources"]} == {"Relics": 4, "Unattributed": 11}


def relic_vp(world: Node, amount: float) -> None:
    world.fields[W.W_PLAYERS][1].fields[W.P_VP_MAP] = {
        27: Node(
            SCHEMA.model_id("VictoryPointEntry"),
            {W.VP_ID: 27, W.VP_AMOUNT: amount},
        )
    }


def test_fractional_relic_counter_prevents_rounded_counter_leak_and_double_count() -> None:
    h, w, _, attrs, _ = scene()
    relic_vp(w, 0)
    tick(h, w, 0)
    attr(attrs, "goldTotal", 0.5)
    attr(attrs, "relicIncomeCostSummation", 0.5)
    tick(h, w, 1000)
    assert {r["source"]: r["total"] for r in h.player(1, 1000)["sources"]} == {"Relics": 0.5}
    attr(attrs, "goldTotal", 1)
    attr(attrs, "relicIncomeCostSummation", 1)
    relic_vp(w, 1)
    tick(h, w, 2000)
    assert h.player(1, 2000)["total"] == 1
    assert h.player(1, 1500)["total"] == 0.5


def test_relic_fraction_does_not_inflate_a_simultaneous_mining_delivery() -> None:
    h, w, worker, attrs, _ = scene()
    relic_vp(w, 0)
    tick(h, w, 0)
    worker.fields[W.E_HELD_AMT] = 20
    tick(h, w, 1000)
    worker.fields[W.E_HELD_AMT] = 0
    attr(attrs, "goldTotal", 20.5)
    attr(attrs, "relicIncomeCostSummation", 0.5)
    tick(h, w, 2000)
    assert h.entity(100, 2000)["credited"]["gold"] == 20
    assert h.player(1, 2000)["bonus"]["gold"] == 0.5
    assert sum(r["total"] for r in h.player(1, 2000)["sources"]) == 20.5


def test_relic_fallback_and_late_join_preserve_fractional_high_water_mark() -> None:
    h, w, _, attrs, _ = scene()
    attr(attrs, "goldTotal", 10000)
    relic_vp(w, 10)
    tick(h, w, 1000)
    attr(attrs, "goldTotal", 10000.5)
    attr(attrs, "relicIncomeCostSummation", 10.5)
    tick(h, w, 2000)
    del attrs.fields[W._ATTR["relicIncomeCostSummation"]]
    tick(h, w, 3000)
    attr(attrs, "relicIncomeCostSummation", 10.5)
    tick(h, w, 4000)
    assert h.player(1, 4000)["total"] == 0.5


def raw_market(amount: float, gold: float, resource: int = 1) -> dict:
    return {
        "kind": "markettransaction",
        "playerid": 1,
        "attributeexchanged": amount,
        "goldexchanged": gold,
        "attributetype": resource,
    }


def test_raw_market_sales_survive_merged_display_events_and_keep_payment_breakdown() -> None:
    h, w, _, attrs, _ = scene()
    tick(h, w, 0)
    attr(attrs, "goldTotal", 139)
    h.sample(w, 1000, [], raw_events=[raw_market(-100, 70), raw_market(-100, 69)])
    h.checkpoint(1000)
    attr(attrs, "goldTotal", 207)
    # The timeline can merge this trade into a previous UI row and emit no row.
    h.sample(w, 2000, [], raw_events=[raw_market(-100, 68)])
    h.checkpoint(2000)
    result = h.player(1, 2000)
    assert not result["sources"] and result["total"] == 0
    assert result["exchanges"][0]["resources"]["gold"] == 207
    assert result["exchanges"][0]["spent"]["wood"] == 300
    assert result["exchanges"][0]["count"] == 3
    assert h.player(1, 1500)["exchanges"][0]["resources"]["gold"] == 139
    assert not h.player(1, 500)["exchanges"]


def test_market_gold_is_not_misattributed_to_a_simultaneous_worker_delivery() -> None:
    h, w, worker, attrs, _ = scene()
    tick(h, w, 0)
    worker.fields[W.E_HELD_AMT] = 20
    tick(h, w, 1000)
    worker.fields[W.E_HELD_AMT] = 0
    attr(attrs, "goldTotal", 90)
    h.sample(w, 2000, [], raw_events=[raw_market(-100, 70)])
    h.checkpoint(2000)
    assert h.entity(100, 2000)["credited"]["gold"] == 20
    assert {r["source"]: r["total"] for r in h.player(1, 2000)["sources"]} == {"villagers": 20}


def test_market_food_purchase_is_separate_and_does_not_erase_gathered_food() -> None:
    h, w, worker, attrs, _ = scene()
    worker.fields[W.E_HELD_TYPE] = 0
    tick(h, w, 0)
    worker.fields[W.E_HELD_AMT] = 10
    tick(h, w, 1000)
    worker.fields[W.E_HELD_AMT] = 0
    attr(attrs, "foodTotal", 10)
    event = raw_market(100, -146, 0)
    del event["attributetype"]  # zero-valued food field is omitted on the wire
    h.sample(w, 2000, [], raw_events=[event])
    h.checkpoint(2000)
    assert h.entity(100, 2000)["credited"]["food"] == 10
    result = h.player(1, 2000)
    assert result["exchanges"][0]["resources"]["food"] == 100
    assert result["exchanges"][0]["spent"]["gold"] == 146
    assert result["bonus"]["food"] == 0


def test_market_history_excludes_initial_snapshot_and_discontinuity_notifications() -> None:
    h, w, _, attrs, _ = scene()
    attr(attrs, "goldTotal", 10000)
    h.sample(w, 900000, [], raw_events=[raw_market(-100, 70)])
    h.checkpoint(900000)
    assert not h.player(1, 900000)["exchanges"]
    attr(attrs, "goldTotal", 10070)
    h.sample(w, 901000, [], raw_events=[raw_market(-100, 70)])
    h.checkpoint(901000)
    h.sample(w, 905000, [], raw_events=[raw_market(-100, 70)], discontinuity=True)
    h.checkpoint(905000)
    assert h.player(1, 905000)["exchanges"][0]["resources"]["gold"] == 70


def direct_farm(world: Node, worker: Node) -> None:
    world.fields[W.W_PLAYERS][1].fields[W.P_MASTERS][50] = Node(
        SCHEMA.model_id("MasterBuildingEntity"),
        {W.M_TYPE: 80, W.M_CLASS: 49},
    )
    world.fields[W.W_ENTITIES][300] = Node(
        SCHEMA.model_id("BuildingEntity"),
        {
            W.E_OWNER: 1,
            W.E_MASTER: 50,
            W.E_STATE: 2,
            W.B_BUILT: True,
        },
    )
    worker.fields[W.E_HELD_TYPE] = 0
    worker.fields[W.E_ACTION].fields.update({W.A_TYPE: 5, W.A_TARGET: 300, TARGET2: -1})


def test_khmer_direct_farming_is_ordinary_collection_without_camp_or_carry() -> None:
    h, w, worker, attrs, _ = scene(28)
    direct_farm(w, worker)
    tick(h, w, 0)
    attr(attrs, "foodTotal", 12)
    tick(h, w, 1000)
    assert h.entity(100, 1000)["collected"]["food"] == 12
    assert h.entity(100, 1000)["credited"]["food"] == 12
    assert h.entity(200, 1000)["dropped_off"]["food"] == 0
    assert h.entity(300, 1000)["dropped_off"]["food"] == 0
    assert {r["source"]: r["total"] for r in h.player(1, 1000)["sources"]} == {"villagers": 12}
    assert h.player(1, 1000)["total"] == 0
    assert h.entity(100, 500)["collected"]["food"] == 0


def test_direct_farming_shares_actual_receipts_once_and_updates_handicap_estimate() -> None:
    h, w, worker, attrs, _ = scene(28)
    direct_farm(w, worker)
    second = deepcopy(worker)
    second.fields[W.E_ACTION].fields[W.A_TARGET] = 301
    w.fields[W.W_ENTITIES][101] = second
    w.fields[W.W_ENTITIES][301] = deepcopy(w.fields[W.W_ENTITIES][300])
    neutral = Node(SCHEMA.model_id("PlayerAttributes"), {})
    attr(neutral, "foodBonus", 1)
    attr(attrs, "foodBonus", 1.2)
    w.fields[W.W_PLAYERS][0] = Node(SCHEMA.model_id("Player"), {W.P_ATTR: neutral})
    tick(h, w, 0, handicaps={1: 120})
    attr(attrs, "foodTotal", 24)
    tick(h, w, 1000, handicaps={1: 120})
    assert h.entity(100, 1000)["credited"]["food"] == 12
    assert h.entity(101, 1000)["credited"]["food"] == 12
    assert h.player(1, 1000)["handicap_yield"]["food"] == 4
    assert h.player(1, 1000)["extra_yield"]["food"] == 0


def test_direct_farm_final_credit_does_not_continue_claiming_idle_income() -> None:
    h, w, worker, attrs, _ = scene(28)
    direct_farm(w, worker)
    tick(h, w, 0)
    worker.fields[W.E_ACTION].fields[W.A_STATE] = 4
    attr(attrs, "foodTotal", 1)
    tick(h, w, 1000)
    attr(attrs, "foodTotal", 10)
    tick(h, w, 2000)
    assert h.entity(100, 2000)["credited"]["food"] == 1
    assert {r["source"]: r["total"] for r in h.player(1, 2000)["sources"]} == {
        "villagers": 1,
        "Unattributed": 9,
    }


@pytest.mark.parametrize("change", ["death", "conversion", "gap", "not_khmer"])
def test_direct_farm_needs_an_eligible_observed_worker_and_continuous_receipt(change: str) -> None:
    h, w, worker, attrs, _ = scene(28 if change != "not_khmer" else 1)
    direct_farm(w, worker)
    tick(h, w, 0)
    if change == "death":
        worker.fields[W.E_STATE] = 3
    if change == "conversion":
        worker.fields[W.E_OWNER] = 0
    attr(attrs, "foodTotal", 12)
    tick(h, w, 1000, discontinuity=change == "gap")
    assert h.entity(100, 1000)["collected"]["food"] == 0


def test_direct_farm_does_not_claim_a_competing_feitoria_receipt() -> None:
    h, w, worker, attrs, _ = scene(28)
    direct_farm(w, worker)
    w.fields[W.W_PLAYERS][1].fields[W.P_MASTERS][1021] = Node(
        SCHEMA.model_id("MasterBuildingEntity"),
        {W.M_TYPE: 80, W.M_CLASS: 3},
    )
    w.fields[W.W_ENTITIES][400] = Node(
        SCHEMA.model_id("BuildingEntity"),
        {
            W.E_OWNER: 1,
            W.E_MASTER: 1021,
            W.E_STATE: 2,
            W.B_BUILT: True,
        },
    )
    tick(h, w, 0)
    attr(attrs, "foodTotal", 12)
    tick(h, w, 1000)
    assert h.entity(100, 1000)["collected"]["food"] == 0
    assert h.player(1, 1000)["sources"][0]["source"] == "Unattributed"


def test_feitoria_receipts_are_observed_not_integrated_across_missing_time() -> None:
    h, w, _, attrs, _ = scene()
    player = w.fields[W.W_PLAYERS][1]
    player.fields[W.P_MASTERS][1021] = Node(
        SCHEMA.model_id("MasterBuildingEntity"), {W.M_TYPE: 80, W.M_CLASS: 3}
    )
    w.fields[W.W_ENTITIES][300] = Node(
        SCHEMA.model_id("BuildingEntity"),
        {W.E_OWNER: 1, W.E_MASTER: 1021, W.E_STATE: 2, W.B_BUILT: True},
    )
    tick(h, w, 0)
    attr(attrs, "foodTotal", 8)
    tick(h, w, 1000)
    assert h.player(1, 1000)["bonus"]["food"] == 8
    attr(attrs, "foodTotal", 800)
    tick(h, w, 100000, discontinuity=True)
    assert h.player(1, 100000)["bonus"]["food"] == 8


def test_tupi_refund_requires_a_real_receipt_not_a_theoretical_percentage() -> None:
    h, w, _, attrs, _ = scene(59)
    tick(h, w, 0)
    event = {
        "kind": "kill",
        "victim": {"id": 500, "owner": 1, "kind": "unit"},
        "killer": {"id": 600, "owner": 2},
    }
    h.sample(w, 1000, [event])
    h.checkpoint(1000)
    assert h.player(1, 1000)["total"] == 0
    attr(attrs, "foodTotal", 7)
    h.sample(w, 2000, [event])
    h.checkpoint(2000)
    assert h.player(1, 2000)["bonus"]["food"] == 7
    assert h.player(1, 1500)["total"] == 0


def test_danish_loot_uses_the_actual_receipt_in_each_resource() -> None:
    h, w, _, attrs, _ = scene(62)
    tick(h, w, 0)
    attr(attrs, "woodTotal", 15)
    attr(attrs, "goldTotal", 4)
    h.sample(
        w,
        1000,
        [
            {
                "kind": "kill",
                "victim": {"id": 500, "owner": 2, "kind": "building"},
                "killer": {"id": 100, "owner": 1},
            }
        ],
    )
    h.checkpoint(1000)
    source = next(r for r in h.player(1, 1000)["sources"] if r["source"] == "Building loot")
    assert source["resources"] == {"food": 0, "wood": 15, "stone": 0, "gold": 4}


def test_dropsite_rows_are_unioned_and_civilization_restrictions_retained(tmp_path) -> None:
    import json

    folder = tmp_path / "resources" / "_common" / "dat"
    folder.mkdir(parents=True)
    (folder / "dropsites.json").write_text(
        json.dumps(
            {
                "drop_site_list": [
                    {"building_id": 45, "target_list": [{"attribute_type": 3}]},
                    {"building_id": 45, "target_list": [{"attribute_type": 17}]},
                    {
                        "building_id": 82,
                        "target_civs": [55],
                        "target_list": [{"attribute_type": 1}],
                    },
                ]
            }
        )
    )
    h = ResourceHistory(GameData(tmp_path))
    assert h._site_rules[45] == {"food", "gold"}
    assert h._site_civs[82] == {55}


def economic_baseline(
    world: Node, mid: int, base: dict[str, float], paid: dict[str, float]
) -> None:
    def master(cost: dict[str, float]) -> Node:
        return Node(
            SCHEMA.model_id("MasterCombatEntity"),
            {
                W.M_TYPE: 70,
                W.M_CLASS: 0,
                W.M_COST: [
                    Node(
                        SCHEMA.model_id("AttributeValue"),
                        {W.AV_TYPE: ("food", "wood", "stone", "gold").index(r), W.AV_AMOUNT: n},
                    )
                    for r, n in cost.items()
                ],
            },
        )

    players = world.fields[W.W_PLAYERS]
    players.setdefault(
        0,
        Node(
            SCHEMA.model_id("Player"),
            {W.P_MASTERS: {}, W.P_ATTR: Node(SCHEMA.model_id("PlayerAttributes"), {})},
        ),
    )
    players[0].fields[W.P_MASTERS][mid] = master(base)
    players[1].fields[W.P_MASTERS][mid] = master(paid)


def test_maya_resource_longevity_is_not_reported_as_extra_yield() -> None:
    # Longevity makes resources last longer; it is not a proven gather-rate or
    # yield bonus, so a 1.15 multiplier alone must not create an effect row.
    h, w, worker, attrs, _ = scene(16)
    neutral_attrs = Node(SCHEMA.model_id("PlayerAttributes"), {})
    w.fields[W.W_PLAYERS][0] = Node(SCHEMA.model_id("Player"), {W.P_ATTR: neutral_attrs})
    attr(neutral_attrs, "goldBonus", 1)
    attr(attrs, "goldBonus", 1.15)
    tick(h, w, 0)
    worker.fields[W.E_HELD_AMT] = 115
    tick(h, w, 1000)
    assert h.player(1, 1000)["extra_yield"]["gold"] == 0
    assert h.player(1, 1000)["bonus"]["gold"] == 0
    assert not h.player(1, 1000)["effects"]


def test_unit_discounts_count_completed_production_not_queued_or_cancelled_units() -> None:
    h, w, _, _, _ = scene(16)
    economic_baseline(w, 4, {"wood": 25, "gold": 45}, {"wood": 20, "gold": 36})
    tick(h, w, 0)
    tick(h, w, 1000)
    assert not h.player(1, 1000)["effects"]
    h.sample(w, 2000, [{"kind": "trained", "player": 1, "master": 4}] * 2)
    h.checkpoint(2000)
    assert h.player(1, 2000)["savings"] == {"food": 0, "wood": 10, "stone": 0, "gold": 18}
    assert h.player(1, 2000)["total"] == 0
    assert h.player(1, 1000)["savings"]["gold"] == 0


def test_free_tech_is_counted_once_on_automatic_completion_not_initial_snapshot() -> None:
    h, w, _, _, _ = scene(2)
    player = w.fields[W.W_PLAYERS][1]
    state = Node(SCHEMA.model_id("ResearchState"), {W.R_STATE: 0, 6: -75, 7: -75})
    player.fields[W.P_RESEARCH] = {14: state}
    w.fields[W.W_TECHS] = {
        14: Node(
            SCHEMA.model_id("Technology"),
            {
                W.T_COST: [
                    Node(SCHEMA.model_id("AttributeValue"), {W.AV_TYPE: 0, W.AV_AMOUNT: 75}),
                    Node(SCHEMA.model_id("AttributeValue"), {W.AV_TYPE: 1, W.AV_AMOUNT: 75}),
                ]
            },
        )
    }
    tick(h, w, 0)
    state.fields[W.R_STATE] = W.RESEARCH_DONE
    tick(h, w, 1000)
    tick(h, w, 2000)
    result = h.player(1, 2000)
    assert result["savings"]["food"] == result["savings"]["wood"] == 75
    assert result["effects"][0]["source"].startswith("Free tech")
    late = ResourceHistory(GameData(None))
    tick(late, w, 2000)
    assert not late.player(1, 2000)["effects"]


@pytest.mark.parametrize(
    "civ,building,source", [(62, True, "Building loot"), (59, False, "Fallen units")]
)
def test_bonus_kills_resolve_compact_timeline_references_after_victim_disappears(
    civ: int, building: bool, source: str
) -> None:
    h, w, _, attrs, _ = scene(civ)
    players = w.fields[W.W_PLAYERS]
    owner = 2 if building else 1
    if owner == 2:
        players[2] = Node(
            SCHEMA.model_id("Player"),
            {
                W.P_MASTERS: {
                    109: Node(SCHEMA.model_id("MasterBuildingEntity"), {W.M_TYPE: 80, W.M_CLASS: 3})
                }
            },
        )
    tick(h, w, 0)
    attr(attrs, "goldTotal", 15)
    event = {
        "kind": "kill",
        "victim": {"id": 500, "owner": owner, "master": 109 if building else 83},
        "killer": {"id": 100, "owner": 1 if building else 2, "master": 83},
    }
    h.sample(w, 1000, [event])
    h.checkpoint(1000)
    assert (
        next(row for row in h.player(1, 1000)["sources"] if row["source"] == source)["resources"][
            "gold"
        ]
        == 15
    )


def test_varangian_last_hit_gold_is_recognized_after_target_disappears() -> None:
    h, w, _, attrs, _ = scene(61)
    w.fields[W.W_PLAYERS][2] = Node(
        SCHEMA.model_id("Player"),
        {
            W.P_MASTERS: {
                83: Node(SCHEMA.model_id("MasterCombatEntity"), {W.M_TYPE: 70, W.M_CLASS: 4})
            }
        },
    )
    tick(h, w, 0)
    attr(attrs, "goldTotal", 1)
    h.sample(
        w,
        1000,
        [
            {
                "kind": "kill",
                "killer": {"id": 300, "owner": 1, "master": 2704},
                "victim": {"id": 500, "owner": 2, "master": 83},
            }
        ],
    )
    h.checkpoint(1000)
    assert h.player(1, 1000)["sources"][0]["source"] == "Varangian Gold Generation"


def test_maya_stacked_yield_does_not_attribute_handicap_to_its_civilization_bonus() -> None:
    h, w, worker, attrs, _ = scene(16)
    neutral_attrs = Node(SCHEMA.model_id("PlayerAttributes"), {})
    w.fields[W.W_PLAYERS][0] = Node(SCHEMA.model_id("Player"), {W.P_ATTR: neutral_attrs})
    attr(neutral_attrs, "goldBonus", 1)
    attr(attrs, "goldBonus", 1.15 * 1.6)
    tick(h, w, 0, handicaps={1: 160})
    worker.fields[W.E_HELD_AMT] = 184
    tick(h, w, 1000, handicaps={1: 160})
    effects = {row["source"]: row["total"] for row in h.player(1, 1000)["effects"]}
    assert effects == {"Handicap · 160%": 60}
    assert h.player(1, 1000)["extra_yield"]["gold"] == 0
    assert h.player(1, 1000)["handicap_yield"]["gold"] == 60


@pytest.mark.parametrize(
    "resource_index,resource", list(enumerate(("food", "wood", "stone", "gold")))
)
def test_khmer_handicap_before_farms_is_not_civilization_extra_yield(
    resource_index: int,
    resource: str,
) -> None:
    h, w, worker, attrs, _ = scene(28)
    neutral_attrs = Node(SCHEMA.model_id("PlayerAttributes"), {})
    w.fields[W.W_PLAYERS][0] = Node(SCHEMA.model_id("Player"), {W.P_ATTR: neutral_attrs})
    attr(neutral_attrs, resource + "Bonus", 1)
    attr(attrs, resource + "Bonus", 1.2)
    worker.fields[W.E_HELD_TYPE] = resource_index
    # There are no farms in this scene. The multiplier applies to any resource.
    tick(h, w, 0, handicaps={1: 120})
    worker.fields[W.E_HELD_AMT] = 120
    tick(h, w, 1000, handicaps={1: 120})
    result = h.player(1, 1000)
    assert result["extra_yield"][resource] == 0
    assert result["handicap_yield"][resource] == 20
    assert result["effects"][0]["category"] == "handicap"
    assert result["effects"][0]["source"] == "Handicap · 120%"
    assert result["bonus"][resource] == 0
    assert h.player(1, 500)["handicap_yield"][resource] == 0


@pytest.mark.parametrize("recorded_handicap,factor", [(None, 1.2), (120, 1.0)])
def test_unproven_global_multiplier_does_not_become_a_bonus(
    recorded_handicap: int | None,
    factor: float,
) -> None:
    h, w, worker, attrs, _ = scene(28)
    neutral_attrs = Node(SCHEMA.model_id("PlayerAttributes"), {})
    w.fields[W.W_PLAYERS][0] = Node(SCHEMA.model_id("Player"), {W.P_ATTR: neutral_attrs})
    attr(neutral_attrs, "goldBonus", 1)
    attr(attrs, "goldBonus", factor)
    handicaps = {1: recorded_handicap} if recorded_handicap is not None else None
    tick(h, w, 0, handicaps=handicaps)
    worker.fields[W.E_HELD_AMT] = 120
    tick(h, w, 1000, handicaps=handicaps)
    assert not h.player(1, 1000)["effects"]


def test_lobby_handicap_uses_world_owner_identity_not_slot_order() -> None:
    def info(owner: int, percent: int) -> Node:
        return Node(
            SCHEMA.model_id("PlayerGameOptions"),
            {
                W.PGO_INDEX: owner,
                W.PGO_HANDICAP: percent,
            },
        )

    root = Node(
        SCHEMA.model_id("Root"),
        {
            W.ROOT_OPTIONS: Node(
                SCHEMA.model_id("GameOptions"),
                {W.GO_PLAYERS: [info(6, 120), info(2, 100), info(8, 0)]},
            )
        },
    )
    assert W.lobby_handicaps(root) == {6: 120, 2: 100}


def test_cancelled_research_does_not_reuse_its_old_discount_when_requeued() -> None:
    h, w, _, _, _ = scene()
    state = Node(SCHEMA.model_id("ResearchState"), {W.R_STATE: 2, 6: -20})
    w.fields[W.W_PLAYERS][1].fields[W.P_RESEARCH] = {14: state}
    w.fields[W.W_TECHS] = {
        14: Node(
            SCHEMA.model_id("Technology"),
            {
                W.T_COST: [
                    Node(SCHEMA.model_id("AttributeValue"), {W.AV_TYPE: 0, W.AV_AMOUNT: 100}),
                ]
            },
        )
    }
    tick(h, w, 0)
    state.fields[W.R_STATE] = 1
    tick(h, w, 1000)
    assert not h.player(1, 1000)["effects"]
    state.fields.update({W.R_STATE: 2, 6: -40})
    tick(h, w, 2000)
    state.fields.update({W.R_STATE: W.RESEARCH_DONE, 6: 0})
    tick(h, w, 3000)
    assert h.player(1, 3000)["savings"]["food"] == 40


def test_building_discount_is_counted_on_completion_not_on_foundation() -> None:
    h, w, _, _, _ = scene(26)
    economic_baseline(w, 109, {"wood": 100}, {"wood": 85})
    for owner in (0, 1):
        w.fields[W.W_PLAYERS][owner].fields[W.P_MASTERS][109].fields[W.M_TYPE] = 80
    site = w.fields[W.W_ENTITIES][200]
    site.fields[W.B_BUILT] = False
    tick(h, w, 0)
    assert not h.player(1, 0)["effects"]
    site.fields[W.B_BUILT] = True
    tick(h, w, 1000)
    tick(h, w, 2000)
    assert h.player(1, 2000)["savings"]["wood"] == 15
    assert h.player(1, 2000)["total"] == 0


def completion_storage(master: Node, resource: int, amount: float, flag: int = 8) -> None:
    master.fields.setdefault(W.M_HELD, []).append(
        Node(
            SCHEMA.model_id("AttributeValue"),
            {W.AV_TYPE: resource, W.AV_AMOUNT: amount, W._fid("AttributeValue", "flag"): flag},
        )
    )


def finish_tech(world: Node, tid: int) -> None:
    world.fields[W.W_PLAYERS][1].fields.setdefault(W.P_RESEARCH, {})[tid] = Node(
        SCHEMA.model_id("ResearchState"), {W.R_STATE: W.RESEARCH_DONE}
    )


@pytest.mark.parametrize(
    "civ,mid,grants",
    [
        (60, 562, {0: 35, 2: 10}),
        (60, 129, {0: 35, 2: 10}),
        (50, 49, {0: 55}),
        (50, 45, {0: 55}),
        (35, 109, {0: 100}),
        (1, 888, {0: 100}),
    ],
)
def test_construction_grants_use_owner_storage_without_collected_counters(civ, mid, grants) -> None:
    h, w, _, attrs, _ = scene(civ)
    player = w.fields[W.W_PLAYERS][1]
    master = player.fields[W.P_MASTERS][109]
    player.fields[W.P_MASTERS][mid] = master
    site = w.fields[W.W_ENTITIES][200]
    site.fields.update({W.E_MASTER: mid, W.B_BUILT: False})
    for resource, amount in grants.items():
        completion_storage(master, resource, amount)
    tick(h, w, 0)
    site.fields[W.B_BUILT] = True
    # The player can spend more than the grant in this frame. Neither
    # collected totals nor positive stockpile changes prove these payouts.
    attr(attrs, "food", 1)
    tick(h, w, 1000)
    expected = {r: grants.get(i, 0) for i, r in enumerate(("food", "wood", "stone", "gold"))}
    assert h.player(1, 1000)["bonus"] == expected
    tick(h, w, 2000)
    assert h.player(1, 2000)["bonus"] == expected
    assert h.player(1, 500)["total"] == 0
    assert h.entity(200, 2000)["dropped_off"]["food"] == 0


@pytest.mark.parametrize("change", ["starting", "gap", "cancelled", "conversion"])
def test_construction_grants_do_not_count_initial_or_uncompleted_buildings(change) -> None:
    h, w, _, _, _ = scene(60)
    site = w.fields[W.W_ENTITIES][200]
    completion_storage(w.fields[W.W_PLAYERS][1].fields[W.P_MASTERS][109], 0, 35)
    site.fields[W.B_BUILT] = change == "starting"
    if change == "conversion":
        site.fields[W.E_OWNER] = 0
    tick(h, w, 0)
    site.fields[W.B_BUILT] = True
    site.fields[W.E_OWNER] = 1
    if change == "cancelled":
        del w.fields[W.W_ENTITIES][200]
    tick(h, w, 1000, discontinuity=change == "gap")
    assert h.player(1, 1000)["total"] == 0


def test_population_and_non_completion_storage_are_not_resource_income() -> None:
    h, w, _, _, _ = scene(23)
    site = w.fields[W.W_ENTITIES][200]
    site.fields[W.B_BUILT] = False
    master = w.fields[W.W_PLAYERS][1].fields[W.P_MASTERS][109]
    completion_storage(master, 4, 5)
    completion_storage(master, 0, 100, flag=1)
    tick(h, w, 0)
    site.fields[W.B_BUILT] = True
    tick(h, w, 1000)
    assert h.player(1, 1000)["total"] == 0


def test_construction_grants_do_not_steal_same_frame_villager_receipts() -> None:
    h, w, worker, attrs, _ = scene(60)
    site = w.fields[W.W_ENTITIES][200]
    site.fields[W.B_BUILT] = False
    completion_storage(w.fields[W.W_PLAYERS][1].fields[W.P_MASTERS][109], 0, 35)
    worker.fields.update({W.E_HELD_TYPE: 0, W.E_HELD_AMT: 10})
    tick(h, w, 0)
    site.fields[W.B_BUILT] = True
    worker.fields[W.E_HELD_AMT] = 0
    attr(attrs, "foodTotal", 10)
    tick(h, w, 1000)
    assert h.player(1, 1000)["bonus"]["food"] == 35
    assert h.entity(100, 1000)["credited"]["food"] == 10
    assert h.entity(200, 1000)["dropped_off"]["food"] == 10


@pytest.mark.parametrize(
    "civ,tids,resources",
    [
        (40, [851, 852, 853], {"wood": 600}),
        (25, [587, 588, 589], {"food": 300, "gold": 300}),
        (40, [872], {"wood": 200}),
        (25, [871], {"food": 100, "gold": 100}),
    ],
)
def test_age_grants_track_executed_bonus_techs_not_gathering(civ, tids, resources) -> None:
    h, w, _, _, _ = scene(civ)
    tick(h, w, 0)
    for i, tid in enumerate(tids, 1):
        finish_tech(w, tid)
        tick(h, w, i * 1000)
    end = len(tids) * 1000
    assert h.player(1, end)["bonus"] == {
        r: resources.get(r, 0) for r in ("food", "wood", "stone", "gold")
    }
    tick(h, w, end + 1000)
    assert h.player(1, end + 1000)["bonus"] == h.player(1, end)["bonus"]


@pytest.mark.parametrize("civ,gap", [(1, False), (40, True)])
def test_age_bonus_cannot_be_imported_from_another_civ_or_gap(civ, gap) -> None:
    h, w, _, _, _ = scene(civ)
    finish_tech(w, 851)
    tick(h, w, 0)
    finish_tech(w, 852)
    tick(h, w, 1000, discontinuity=gap)
    assert h.player(1, 1000)["total"] == 0


def test_spanish_reward_counts_actual_research_not_hidden_effects_or_ages() -> None:
    h, w, _, _, _ = scene(14)
    tick(h, w, 0)
    finish_tech(w, 186)
    h.sample(
        w,
        1000,
        [
            {"kind": "researched", "player": 1, "tech": 22},
            {"kind": "researched", "player": 1, "tech": 22},
            {"kind": "researched", "player": 1, "tech": 202},
            {"kind": "researched", "player": 1, "tech": 101},
            {"kind": "researched", "player": 2, "tech": 55},
        ],
    )
    h.checkpoint(1000)
    assert h.player(1, 1000)["bonus"]["gold"] == 40


def wei_upgrade(world: Node, bonus: int = 1039) -> None:
    world.fields.setdefault(W.W_TECHS, {}).update(
        {
            bonus: Node(
                SCHEMA.model_id("Technology"),
                {
                    W._fid("Technology", "techPrerequisites"): [
                        Node(SCHEMA.model_id("TechnologyPrerequisite"), {0: 202})
                    ],
                },
            ),
            202: Node(SCHEMA.model_id("Technology"), {W.T_NAME: "Double-Bit Axe"}),
        }
    )
    finish_tech(world, bonus)


def test_wei_free_villager_uses_observed_spawn_and_separate_unit_value() -> None:
    h, w, worker, _, master = scene(51)
    master.fields[W.M_COST] = [
        Node(SCHEMA.model_id("AttributeValue"), {W.AV_TYPE: 0, W.AV_AMOUNT: 50})
    ]
    tick(h, w, 0)
    wei_upgrade(w)
    w.fields[W.W_ENTITIES][300] = deepcopy(worker)
    tick(h, w, 1000)
    data = h.player(1, 1000)
    row = next(r for r in data["effects"] if r["category"] == "assets")
    assert row["source"] == "Free villager · Double-Bit Axe"
    assert row["count"] == 1
    assert row["resources"]["food"] == 50
    assert data["total"] == 0 and data["savings"]["food"] == 0
    tick(h, w, 2000)
    assert h.player(1, 2000)["effects"] == data["effects"]
    assert not h.player(1, 500)["effects"]


@pytest.mark.parametrize(
    "reason", ["no_spawn", "conversion", "trained", "gap", "wrong_civ", "no_bonus"]
)
def test_wei_does_not_invent_villager_grants(reason) -> None:
    h, w, worker, _, master = scene(51 if reason != "wrong_civ" else 1)
    master.fields[W.M_COST] = [Node(SCHEMA.model_id("AttributeValue"), {W.AV_AMOUNT: 50})]
    if reason == "conversion":
        w.fields[W.W_ENTITIES][300] = deepcopy(worker)
        w.fields[W.W_ENTITIES][300].fields[W.E_OWNER] = 0
    tick(h, w, 0)
    if reason != "no_bonus":
        wei_upgrade(w)
    if reason != "no_spawn":
        w.fields[W.W_ENTITIES][300] = deepcopy(worker)
    h.sample(
        w,
        1000,
        [],
        discontinuity=reason == "gap",
        raw_events=[{"kind": "notificationtraindone", "ownerid": 1, "masterid": 83, "objid": 300}]
        if reason == "trained"
        else [],
    )
    h.checkpoint(1000)
    assert not [r for r in h.player(1, 1000)["effects"] if r["category"] == "assets"]


def test_paper_money_trickles_on_chopping_without_a_wood_delivery() -> None:
    h, w, worker, attrs, master = scene(31)
    worker.fields.update({W.E_HELD_TYPE: 1, W.E_HELD_AMT: 5})
    tree_master = Node(SCHEMA.model_id("MasterEntity"), {W.M_CLASS: W.CLASS_TREE})
    w.fields[W.W_PLAYERS][1].fields[W.P_MASTERS][349] = tree_master
    w.fields[W.W_ENTITIES][999] = Node(SCHEMA.model_id("Entity"), {W.E_OWNER: 1, W.E_MASTER: 349})
    attr(attrs, "choppingGoldProductivity", 2.16)
    carry_bonus(master, 266, 3)
    finish_tech(w, 629)
    tick(h, w, 0)
    worker.fields[W.E_HELD_AMT] = 5.5
    attr(attrs, "goldTotal", 0.35)
    tick(h, w, 500)
    assert h.player(1, 500)["bonus"]["gold"] == 0.3  # normal decimal rounding
    assert (
        next(r for r in h.player(1, 500)["sources"] if r["source"] == "Paper Money")["total"] == 0.3
    )
    assert h.entity(100, 500)["credited"]["gold"] == 0.3
    assert not h.workers[100].bonus  # no invented gold at the later wood drop
    assert h.entity(200, 500)["dropped_off"]["gold"] == 0
    worker.fields[W.E_ACTION].fields[W.A_STATE] = 0
    attr(attrs, "goldTotal", 0.7)
    tick(h, w, 1000)
    assert h.player(1, 1000)["bonus"]["gold"] == 0.7
    tick(h, w, 1500)
    assert h.player(1, 1500)["bonus"]["gold"] == 0.7


@pytest.mark.parametrize("reason", ["no_tech", "idle", "wrong_civ", "no_rate"])
def test_paper_money_requires_an_active_proven_source(reason) -> None:
    h, w, worker, attrs, _ = scene(1 if reason == "wrong_civ" else 31)
    worker.fields[W.E_HELD_TYPE] = 1
    w.fields[W.W_PLAYERS][1].fields[W.P_MASTERS][349] = Node(
        SCHEMA.model_id("MasterEntity"), {W.M_CLASS: W.CLASS_TREE}
    )
    w.fields[W.W_ENTITIES][999] = Node(SCHEMA.model_id("Entity"), {W.E_OWNER: 1, W.E_MASTER: 349})
    if reason != "no_rate":
        attr(attrs, "choppingGoldProductivity", 2.16)
    if reason != "no_tech":
        finish_tech(w, 629)
    if reason == "idle":
        worker.fields[W.E_ACTION].fields[W.A_STATE] = 0
    tick(h, w, 0)
    attr(attrs, "goldTotal", 1)
    tick(h, w, 500)
    assert h.player(1, 500)["total"] == 0
    assert h.player(1, 500)["sources"][0]["source"] == "Unattributed"


@pytest.mark.parametrize("resource", ["food", "wood", "stone", "gold"])
def test_deleted_cargo_is_a_return_not_bonus_or_camp_delivery(resource) -> None:
    h, w, worker, attrs, _ = scene()
    worker.fields.update(
        {W.E_HELD_TYPE: ("food", "wood", "stone", "gold").index(resource), W.E_HELD_AMT: 20}
    )
    tick(h, w, 0)
    worker.fields.update({W.E_STATE: 4, W.E_HELD_AMT: 0})
    attr(attrs, resource + "Total", 20)
    # Same-frame spending is independent of the receipt.
    attr(attrs, resource, 1)
    h.sample(w, 500, [], commands=[{"kind": "deleteobjects", "playerid": 1, "unitids": [100, 100]}])
    h.checkpoint(500)
    data = h.player(1, 500)
    assert data["total"] == 0 and not data["sources"]
    assert data["exchanges"][0]["category"] == "return"
    assert data["exchanges"][0]["count"] == 1
    assert data["exchanges"][0]["resources"][resource] == 20
    assert h.entity(100, 500)["credited"][resource] == 20
    assert h.entity(200, 500)["dropped_off"][resource] == 0
    assert not h.player(1, 0)["exchanges"]


@pytest.mark.parametrize(
    "reason", ["no_command", "wrong_owner", "alive", "no_receipt", "gap", "still_carried"]
)
def test_death_or_delete_request_alone_does_not_prove_cargo_return(reason) -> None:
    h, w, worker, attrs, _ = scene()
    worker.fields[W.E_HELD_AMT] = 20
    tick(h, w, 0)
    worker.fields.update(
        {
            W.E_STATE: 2 if reason == "alive" else 4,
            W.E_HELD_AMT: 20 if reason == "still_carried" else 0,
        }
    )
    if reason != "no_receipt":
        attr(attrs, "goldTotal", 20)
    commands = (
        []
        if reason == "no_command"
        else [
            {
                "kind": "deleteobjects",
                "playerid": 2 if reason == "wrong_owner" else 1,
                "unitids": [100],
            }
        ]
    )
    h.sample(w, 500, [], commands=commands, discontinuity=reason == "gap")
    h.checkpoint(500)
    assert not h.player(1, 500)["exchanges"]


def test_secondary_delivery_tail_uses_observed_receipts_after_other_deliveries() -> None:
    h, w, worker, attrs, master = scene(24)
    carry_bonus(master, 267, 1)
    worker.fields.update({W.E_HELD_TYPE: 0, W.E_HELD_AMT: 9})
    tick(h, w, 0)
    worker.fields[W.E_HELD_AMT] = 0
    attr(attrs, "foodTotal", 10)
    attr(attrs, "woodTotal", 3.4)
    tick(h, w, 500)
    rows = {r["source"]: r for r in h.player(1, 500)["sources"]}
    assert rows["Foraging wood"]["resources"]["wood"] == 3.4
    assert "Unattributed" not in rows
    assert h.entity(100, 500)["credited"]["wood"] == 3.4


def test_secondary_yield_follows_carried_berries_when_forager_becomes_builder() -> None:
    h, w, worker, attrs, master = scene(24)
    carry_bonus(master, 267, 1)
    worker.fields.update({W.E_HELD_TYPE: 16, W.E_HELD_AMT: 5})
    tick(h, w, 0)
    w.fields[W.W_PLAYERS][1].fields[W.P_MASTERS][118] = Node(
        SCHEMA.model_id("MasterCombatEntity"), {W.M_CLASS: 4, W.M_TYPE: 70}
    )
    worker.fields[W.E_MASTER] = 118
    # One more ordinary food is mixed into the five carried berries.
    worker.fields[W.E_HELD_AMT] = 6
    tick(h, w, 500)
    assert dict(h.workers[100].bonus)["wood"] == pytest.approx(5 / 18, abs=0.0001)
    worker.fields[W.E_HELD_AMT] = 0
    attr(attrs, "foodTotal", 6)
    attr(attrs, "woodTotal", 5 / 3)
    tick(h, w, 1000)
    assert h.player(1, 1000)["bonus"]["wood"] == 1.7
    assert not [r for r in h.player(1, 1000)["sources"] if r["category"] == "unattributed"]
    worker.fields[W.E_HELD_AMT] = 10
    tick(h, w, 1500)
    worker.fields[W.E_HELD_AMT] = 0
    attr(attrs, "foodTotal", 16)
    tick(h, w, 2000)
    assert h.player(1, 2000)["bonus"]["wood"] == 1.7


def test_query_state_roundtrip_answers_every_query_the_same() -> None:
    """The playback index stores query_state() and a fresh history restored from it
    answers entity() and player() as the original did (no frames replayed)."""
    from collections import defaultdict

    from vantage.resource_review import ResourceHistory

    data = type("Data", (), {"mode": None, "game_dir": None})()
    history = ResourceHistory.__new__(ResourceHistory)
    restored = ResourceHistory.__new__(ResourceHistory)
    for h in (history, restored):
        h.gather_log = defaultdict(list)
        h.deposit_log = defaultdict(list)
        h.credit_log = defaultdict(list)
        h.source_log = defaultdict(list)
        h.exchange_log = defaultdict(list)
        h.ambiguous_sites = defaultdict(list)
        h._sites = set()
        h.coverage = []
        h.benefits = type("B", (), {})()
        h.benefits.logs = defaultdict(list)
        h.benefits.player = lambda owner, t, b=h.benefits: {"effects": list(b.logs.get(owner, []))}
    history.gather_log[7].append((1000, [1.0, 2.0, 0.0, 0.0]))
    history.deposit_log[7].append((1000, [1.0, 0.0, 0.0, 0.0]))
    history.source_log[1].append((1000, {"villagers": [3.0, 0.0, 0.0, 0.0]}))
    history.exchange_log[1].append((1000, [{"resources": [1.0, 0, 0, 0], "spent": [0, 1.0, 0, 0]}]))
    history.ambiguous_sites[9] = [500]
    history._sites = {9}
    history.coverage = [(0, None), (2000, 1500)]
    history.benefits.logs[1].append((1000, {"x": 1}))
    del data
    restored.restore_query_state(history.query_state())
    for t in (0, 1000, 2500):
        assert restored.entity(7, t) == history.entity(7, t)
        assert restored.entity(9, t) == history.entity(9, t)
        assert restored.player(1, t) == history.player(1, t)
    # Unknown ids still answer (the logs keep their default factories).
    assert restored.entity(123, 1000) == history.entity(123, 1000)


def test_saved_maya_longevity_rows_are_not_reported():
    from vantage.economy_benefits import EconomyBenefits

    benefits = EconomyBenefits(None)
    benefits.logs[1].append(
        (
            0,
            {
                "Maya resource longevity": {
                    "source": "Maya resource longevity",
                    "category": "yield",
                    "resources": [15.0, 0.0, 0.0, 0.0],
                    "count": 1,
                }
            },
        )
    )
    report = benefits.player(1, 1000)
    assert report["effects"] == []
    assert report["extra_yield"]["food"] == 0
