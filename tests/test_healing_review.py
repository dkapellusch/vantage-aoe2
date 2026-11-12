"""HP restored is observed once and valued at the patient's contemporaneous cost."""

from __future__ import annotations

import pytest

from vantage import world as W
from vantage.healing_review import NUM_HEALERS, HealingHistory
from vantage.patch import Node
from vantage.schema import SCHEMA


def scene() -> tuple[HealingHistory, Node, Node, Node, Node]:
    def cost(resource: int, amount: float) -> Node:
        return Node(
            SCHEMA.model_id("AttributeValue"),
            {W.AV_TYPE: resource, W.AV_AMOUNT: amount, W._fid("AttributeValue", "flag"): 1},
        )

    patient_master = Node(
        SCHEMA.model_id("MasterCombatEntity"),
        {W.M_TYPE: 70, W.M_CLASS: 12, W.M_HP: 120, W.M_COST: [cost(0, 60), cost(3, 75)]},
    )
    monk_master = Node(
        SCHEMA.model_id("MasterCombatEntity"), {W.M_TYPE: 70, W.M_CLASS: 18, W.M_HP: 30}
    )
    attributes = Node(
        SCHEMA.model_id("PlayerAttributes"), {W._fid("PlayerAttributes", "healRange"): 4}
    )
    player = Node(
        SCHEMA.model_id("Player"),
        {W.P_MASTERS: {38: patient_master, 125: monk_master}, W.P_ATTR: attributes},
    )
    monk = Node(
        SCHEMA.model_id("CombatEntity"),
        {
            W.E_ID: 100,
            W.E_OWNER: 1,
            W.E_MASTER: 125,
            W.E_HP: 30,
            W.E_STATE: 2,
            W.E_X: 0,
            W.E_Y: 0,
            W.E_ACTION: Node(
                SCHEMA.model_id("Action"), {W.A_TYPE: 105, W.A_STATE: 7, W.A_TARGET: 200}
            ),
        },
    )
    patient = Node(
        SCHEMA.model_id("CombatEntity"),
        {
            W.E_ID: 200,
            W.E_OWNER: 1,
            W.E_MASTER: 38,
            W.E_HP: 60,
            W.E_STATE: 2,
            W.E_X: 1,
            W.E_Y: 1,
            NUM_HEALERS: 1,
        },
    )
    world = Node(
        SCHEMA.model_id("World"),
        {W.W_ENTITIES: {100: monk, 200: patient}, W.W_PLAYERS: {1: player}},
    )
    return HealingHistory(), world, monk, patient, patient_master


def test_healing_half_a_knight_is_half_its_owner_specific_resource_cost() -> None:
    h, w, _, patient, _ = scene()
    h.sample(w, 0, [])
    patient.fields[W.E_HP] = 120
    h.sample(w, 1000, [])
    result = h.totals([100], 1000)
    assert result["hp"] == 60
    assert result["resources"] == {"food": 30, "wood": 0, "stone": 0, "gold": 37.5}
    assert result["value"] == 67.5


def test_final_tick_is_credited_after_the_monk_returns_to_idle() -> None:
    h, w, monk, patient, _ = scene()
    patient.fields[W.E_HP] = 119
    h.sample(w, 0, [])
    patient.fields[W.E_HP] = 120
    patient.fields[NUM_HEALERS] = 0
    monk.fields.pop(W.E_ACTION)
    h.sample(w, 1000, [])
    assert h.totals([100], 1000)["hp"] == 1


def test_damage_during_healing_does_not_hide_the_healed_hp() -> None:
    h, w, _, patient, _ = scene()
    h.sample(w, 0, [])
    patient.fields[W.E_HP] = 55
    h.sample(w, 1000, [{"kind": "damage", "entityid": 200, "damage": 10}])
    result = h.totals([100], 1000)
    assert result["hp"] == 5  # ten damage, five healed; net HP fell by five
    assert result["value"] == 5.62


def test_two_monks_do_not_both_receive_the_full_heal_value() -> None:
    h, w, monk, patient, _ = scene()
    other = Node(monk.model, dict(monk.fields))
    other.fields[W.E_ID] = 101
    w.fields[W.W_ENTITIES][101] = other
    patient.fields[NUM_HEALERS] = 2
    h.sample(w, 0, [])
    patient.fields[W.E_HP] = 70
    h.sample(w, 1000, [])
    assert h.totals([100], 1000)["hp"] == 5
    assert h.totals([101], 1000)["hp"] == 5
    group = h.totals([100, 101, 100], 1000)
    assert group["hp"] == 10 and group["shared_hp"] == 10
    assert group["value"] == 11.25


def test_scoped_queries_and_rewinds_never_use_future_healing_or_costs() -> None:
    h, w, _, patient, master = scene()
    h.sample(w, 0, [])
    patient.fields[W.E_HP] = 70
    h.sample(w, 1000, [])
    master.fields[W.M_COST][1].fields[W.AV_AMOUNT] = 30  # owner now pays less gold
    patient.fields[W.E_HP] = 80
    h.sample(w, 2000, [])
    assert h.totals([100], 0)["hp"] == 0
    assert h.totals([100], 1000)["resources"]["gold"] == 6.25
    assert h.totals([100], 2000, since=1500)["resources"]["gold"] == 2.5
    assert h.totals([100], 2000)["resources"]["gold"] == 8.75


@pytest.mark.parametrize(
    "cause", ["regeneration", "garrison", "repair", "missing_healer", "building"]
)
def test_other_hp_restoration_is_not_attributed_to_a_monk(cause: str) -> None:
    h, w, monk, patient, master = scene()
    if cause == "regeneration":
        master.fields[W.M_REGEN] = 30
    if cause == "garrison":
        patient.fields[W.E_INSIDE] = 900
    if cause == "repair":
        worker = Node(monk.model, dict(monk.fields))
        worker.fields[W.E_ACTION] = Node(
            SCHEMA.model_id("Action"), {W.A_TYPE: 106, W.A_TARGET: 200}
        )
        w.fields[W.W_ENTITIES][102] = worker
    if cause == "missing_healer":
        patient.fields[NUM_HEALERS] = 2
    if cause == "building":
        master.fields[W.M_TYPE] = 80
    h.sample(w, 0, [])
    patient.fields[W.E_HP] = 70
    h.sample(w, 1000, [])
    assert h.totals([100], 1000)["hp"] == 0


@pytest.mark.parametrize("cause", ["upgrade", "conversion", "death", "gap", "snapshot", "walking"])
def test_changes_that_make_hp_attribution_unsafe_are_excluded(cause: str) -> None:
    h, w, monk, patient, master = scene()
    h.sample(w, 0, [])
    patient.fields[W.E_HP] = 70
    if cause == "upgrade":
        master.fields[W.M_HP] = 140
    if cause == "conversion":
        patient.fields[W.E_OWNER] = 0
    if cause == "death":
        monk.fields[W.E_STATE] = 3
    if cause == "walking":
        monk.fields[W.E_ACTION].fields[W.A_STATE] = 4
    end = 10000 if cause == "gap" else 1000
    h.sample(w, end, [], discontinuity=cause == "snapshot")
    assert h.totals([100], end)["hp"] == 0


def test_unknown_cost_retains_hp_and_does_not_invent_a_zero_value() -> None:
    h, w, _, patient, master = scene()
    master.fields.pop(W.M_COST)
    h.sample(w, 5000, [])
    patient.fields[W.E_HP] = 70
    h.sample(w, 6000, [])
    result = h.totals([100], 6000)
    assert result["hp"] == 10 and result["unpriced_hp"] == 10
    assert result["value"] is None
    assert result["partial"] is True


def test_healing_activity_has_its_own_label_instead_of_fighting() -> None:
    _, _, monk, _, _ = scene()
    assert W.unit_activity(monk, None, False) == W.ACT_HEALING
    assert W.ACTIVITY_NAMES[W.ACT_HEALING] == "healing"
    monk.fields[W.E_ACTION].fields[W.A_STATE] = 4
    assert W.unit_activity(monk, None, False) == W.ACT_MOVING


def test_timeline_unit_and_group_endpoints_include_scoped_healing() -> None:
    from tests.helpers import _entity, _master, delta, set_entity, snapshot_frame
    from vantage.frames import Frame
    from vantage.gamedata import GameData
    from vantage.timeline import Timeline

    timeline = Timeline(GameData(None))
    timeline.feed(snapshot_frame())

    def healer(b):
        b.push_key(W.W_PLAYERS, 2)
        _master(b, 125, 70, 18, 5139, 30, 0)
        b.pop()
        _entity(b, 200, 125, 2, 3, 3, action=False)
        b.push_key(W.W_ENTITIES, 200).create(W.E_ACTION, SCHEMA.model_id("Action"))
        b.assign(W.A_TYPE, "Int16", 105).assign(W.A_STATE, "UInt8", 7)
        b.assign(W.A_TARGET, "Int32", 104).pop().pop()

    timeline.feed(
        Frame(
            1000,
            delta(
                1000,
                healer,
                set_entity(104, "Entity", "hp", "Float", 50),
                set_entity(104, "CombatEntity", "numHealers", "Int8", 1),
            ).forward(),
        )
    )
    timeline.feed(Frame(2000, delta(2000, set_entity(104, "Entity", "hp", "Float", 100)).forward()))
    unit = timeline.unit_stats(200, 2000)["healing"]
    assert unit["hp"] == 50 and unit["value"] == 67.5
    assert timeline.group_stats([200, 200], 2000)["healing"] == unit
    assert timeline.unit_stats(200, 1000)["healing"]["hp"] == 0
    assert timeline.group_stats([200], 2000, since=2500)["healing"]["hp"] == 0


def test_query_state_roundtrip_answers_totals_the_same() -> None:
    """The playback index stores query_state(); a fresh history restored from it
    answers totals() as the original did."""
    from vantage.healing_review import HealingHistory

    history, restored = HealingHistory(), HealingHistory()
    history.log[5] = [
        (1000, 10.0, (1.0, 0.0, 0.0, 0.0), 0.0, 0.0),
        (2000, 25.0, (2.0, 1.0, 0.0, 0.0), 1.0, 0.0),
    ]
    history.healers[5] = 900
    history.start, history.last, history.gaps = 500, 2000, [(1200, 1400)]
    restored.restore_query_state(history.query_state())
    for end, since in ((1500, None), (2500, 1100), (400, None)):
        assert restored.totals([5, 6], end, since) == history.totals([5, 6], end, since)


def test_real_monk_restores_damaged_knight_at_its_recorded_owner_cost() -> None:
    """Nov 11 real game: monk 13156 heals Knight 12971 (130 HP, 60f/75g).

    Raw fields retain healer links/counts, positions, actions, modifiers and
    owner masters; the fixture does not supply expected healing as input.
    """
    import json
    from pathlib import Path

    def decode(value):
        if isinstance(value, dict):
            if "model" in value:
                return Node(value["model"], decode(value["fields"]))
            return {int(k): decode(v) for k, v in value.items()}
        if isinstance(value, list):
            return [decode(v) for v in value]
        return value

    fixture = json.loads((Path(__file__).parent / "fixtures/monk-knight-healing.json").read_text())
    h = HealingHistory()
    for row in fixture["frames"]:
        entities = {}
        for eid, entry in row["entities"].items():
            entity = decode(entry["node"])
            entity.fields[W.E_OWN_MASTER] = decode(fixture["masters"][entry["master"]])
            entities[int(eid)] = entity
        world = Node(
            SCHEMA.model_id("World"),
            {W.W_ENTITIES: entities, W.W_PLAYERS: decode(row["players"])},
        )
        h.sample(world, row["time"], row["events"], discontinuity=bool(row["skipped"]))
    patient = entities[fixture["patient"]]
    master = patient.fields[W.E_OWN_MASTER]
    assert patient.fields[W.E_MASTER] == 38  # Knight
    assert master.fields[W.M_HP] == 130
    assert W.master_cost(master.fields) == {"food": 60, "gold": 75}
    result = h.totals([fixture["healer"]], row["time"])
    # First confirmed Heal link at 21:18.000: 25.225 HP; last: 52.130016 HP.
    # The initial 0.225 HP before the link was observed is conservatively excluded.
    initial = fixture["frames"][1]["entities"][str(fixture["patient"])]["node"]
    delta_hp = patient.fields[W.E_HP] - initial["fields"][str(W.E_HP)]
    assert round(delta_hp, 2) == 26.91
    assert result["hp"] == 26.91
    assert result["resources"]["food"] == round(delta_hp / 130 * 60, 2)
    assert result["resources"]["gold"] == round(delta_hp / 130 * 75, 2)
    assert result["resources"] == {"food": 12.42, "wood": 0, "stone": 0, "gold": 15.52}
    assert result["value"] == 27.94
    assert result["unpriced_hp"] == 0
    assert result["healer_count"] == 1
    restored = HealingHistory()
    restored.restore_query_state(h.query_state())
    assert restored.totals([fixture["healer"]], row["time"]) == result
