"""Farm inspection never confuses the production buffer with lifetime supply."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

from vantage import world as W
from vantage.farms import FarmHistory
from vantage.gamedata import GameData
from vantage.patch import Node
from vantage.resource_review import ResourceHistory
from vantage.schema import SCHEMA


def node(model: str, **fields):
    mid = SCHEMA.model_id(model)
    return Node(mid, {SCHEMA.fid(mid, k): v for k, v in fields.items()})


def scene():
    attributes = node(
        "PlayerAttributes",
        farmDeathRate=250.0,
        folwarkCollectAmount=25.0,
        folwarkBuildingId=68.0,
        foodTotal=100.0,
    )
    owner = node(
        "Player",
        attributes=attributes,
        civId=38,
        researchStates={14: node("ResearchState", state=3)},
    )
    farm = node(
        "BuildingEntity",
        id=1,
        ownerId=1,
        masterId=50,
        worldX=4.0,
        worldY=4.0,
        heldAttributeAmount=15.0,
        built=False,
        ownMaster=node("MasterBuildingEntity", objectGroup=49, type=80),
    )
    site = node(
        "BuildingEntity",
        id=2,
        ownerId=1,
        masterId=68,
        built=True,
        ownMaster=node("MasterBuildingEntity", objectGroup=3, type=80),
    )
    world = node("World", players={1: owner}, entities={1: farm, 2: site})
    return world, owner, farm, site, attributes


def tick(h, w, t, baseline=False):
    grants = h.sample(w, t, baseline=baseline)
    h.confirm(grants, {1: 1000})
    return grants


def test_capacity_chips_dates_age_and_buffer_are_distinct():
    w, p, farm, _, attrs = scene()
    h = FarmHistory()
    tick(h, w, 0, True)
    farm.fields[W.B_BUILT] = True
    tick(h, w, 1000)
    p.fields[W.P_RESEARCH][13] = node("ResearchState", state=3)
    attrs.fields[W._ATTR["farmDeathRate"]] = 375.0
    tick(h, w, 2000)
    detail = h.entity(1, 1, 50, 2500)["farm"]
    assert detail["remaining"] is None  # never the 15-food buffer
    assert detail["capacity_at_build"] == 250
    assert detail["capacity"] == 375
    assert detail["age_ms"] == 1500
    assert [(u["tech"], u["done"], u["researched_ms"]) for u in detail["upgrades"]] == [
        (14, True, None),
        (13, True, 2000),
        (12, False, None),
    ]
    assert h.entity(1, 1, 50, 1500)["farm"]["capacity"] == 250
    assert h.entity(2, 1, 68, 999)["folwark"]["food"] == 0
    assert h.entity(2, 1, 68, 1000)["folwark"]["food"] == 25


def test_range_ownership_overlap_no_double_credit_and_no_initial_or_gap_grants():
    w, _p, farm, site, _ = scene()
    h = FarmHistory()
    tick(h, w, 0, True)
    second = node("BuildingEntity", id=3, masterId=68, ownerId=1, built=True)
    w.fields[W.W_ENTITIES][3] = second
    farm.fields[W.B_BUILT] = True
    tick(h, w, 1000)
    assert h.bonus(1, 1000) == 25
    assert h.entity(2, 1, 68, 1000)["folwark"]["food"] == 0
    assert h.entity(2, 1, 68, 1000)["folwark"]["shared_food"] == 25
    tick(h, w, 1500)
    assert h.bonus(1, 1500) == 25
    for mode in ("outside", "enemy", "unfinished", "baseline"):
        w, _p, farm, site, _ = scene()
        h = FarmHistory()
        tick(h, w, 0, True)
        if mode == "outside":
            farm.fields[W.E_X] = 5.0
        if mode == "enemy":
            site.fields[W.E_OWNER] = 2
        if mode == "unfinished":
            site.fields[W.B_BUILT] = False
        farm.fields[W.B_BUILT] = True
        tick(h, w, 1000, mode == "baseline")
        assert h.bonus(1, 1000) == 0


def test_receipt_required_for_all_farms_in_a_frame():
    w, _, farm, _, _ = scene()
    h = FarmHistory()
    second = deepcopy(farm)
    second.fields[W.E_ID] = 3
    w.fields[W.W_ENTITIES][3] = second
    h.sample(w, 0, baseline=True)
    farm.fields[W.B_BUILT] = second.fields[W.B_BUILT] = True
    grants = h.sample(w, 1000, baseline=False)
    h.confirm(grants, {1: 49})
    assert not h.grants
    h.confirm(grants, {1: 50})
    assert h.bonus(1, 1000) == 50


def test_civilisation_chips_require_recorded_research():
    w, p, _, _, _ = scene()
    h = FarmHistory()
    p.fields[W.P_CIV] = 37  # Sicilian eligibility, not proof of earning it
    tick(h, w, 0, True)
    assert not h.rules[1][-1][1]["upgrades"][-1]["done"]
    p.fields[W.P_RESEARCH][772] = node("ResearchState", state=3)
    p.fields[W.P_RESEARCH][232] = node("ResearchState", state=3)  # allied Chinese bonus
    tick(h, w, 1000)
    upgrades = h.rules[1][-1][1]["upgrades"]
    assert {u["tech"] for u in upgrades if u["done"]} == {14, 772, 232}


def test_real_poles_receipt_is_25_food_not_worker_gathering():
    fixture = json.loads((Path(__file__).parent / "fixtures/poles-farm-receipt.json").read_text())
    h = ResourceHistory(GameData(None))
    for row in fixture["frames"]:
        p = node(
            "Player",
            civId=fixture["civ"],
            attributes=node("PlayerAttributes", **row["attributes"]),
            researchStates={tid: node("ResearchState", state=3) for tid in row["done"]},
        )
        entities = {}
        for e in row["entities"]:
            fields = {int(k): v for k, v in e["fields"].items()}
            fields[W.E_OWN_MASTER] = Node(
                SCHEMA.model_id("MasterBuildingEntity"), {int(k): v for k, v in e["master"].items()}
            )
            entities[e["id"]] = Node(SCHEMA.model_id("BuildingEntity"), fields)
        w = node("World", players={2: p}, entities=entities)
        h.sample(w, row["time"], [])
        h.checkpoint(row["time"])
    assert h.farms.grants == [
        {"time": 1483516, "farm": 14117, "owner": 2, "food": 25.0, "folwarks": [11861]}
    ]
    before, after = fixture["frames"][-2:]
    assert abs(after["attributes"]["foodTotal"] - before["attributes"]["foodTotal"] - 25) < 0.001
    assert abs(after["attributes"]["food"] - before["attributes"]["food"] - 25) < 0.001
    income = h.player(2, after["time"])
    assert income["bonus"]["food"] == 25
    assert not any(s["source"] == "villagers" for s in income["sources"])
    restored = ResourceHistory(GameData(None))
    restored.restore_query_state(h.query_state())
    assert restored.farms.entity(11861, 2, 68, after["time"]) == h.farms.entity(
        11861, 2, 68, after["time"]
    )
