"""vantage.world: reading the decoded tree into the spectator view."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.helpers import (
    BRIDGE,
    GOLD_MINE,
    HERDER,
    HOUSE,
    KING,
    KNIGHT,
    LUMBERJACK,
    TOWN_CENTER,
    VILLAGER,
    PatchBuilder,
    delta,
    fid,
    produce,
    set_attr,
    set_entity,
    set_master,
    set_master_cost,
    set_treaty,
    snapshot_frame,
    spawn,
)
from vantage import world as W
from vantage.gamedata import GameData
from vantage.patch import Node, Patcher
from vantage.schema import SCHEMA


@pytest.fixture
def data(tmp_path: Path) -> GameData:
    kv = tmp_path / "g" / "resources" / "en" / "strings" / "key-value"
    kv.mkdir(parents=True)
    (kv / "key-value-strings-utf8.txt").write_text(
        '5121 "Villager"\n5122 "Lumberjack"\n9999 "Herder"\n5132 "Knight"\n5164 "Town Center"\n'
    )
    (tmp_path / "g" / "resources" / "_common").mkdir(parents=True, exist_ok=True)
    return GameData(tmp_path / "g", cache_dir=tmp_path / "c")


def _patcher() -> Patcher:
    p = Patcher()
    p.apply(snapshot_frame(0).patch)
    return p


def test_view_players_economy_and_entities(data: GameData) -> None:
    cat = W.Catalog(data)
    v = W.view(_patcher().root, cat)
    assert v is not None
    alice = v["players"]["1"]
    assert alice["resources"] == {"food": 200.0, "wood": 150.0, "stone": 100.0, "gold": 0.0}
    assert (alice["pop"], alice["pop_cap"]) == (4, 5)  # cap = pop + headroom
    assert alice["villagers"] == 4  # doppelganger excluded, garrisoned one counted
    assert alice["idle_villagers"] == 1
    assert alice["tasks"] == {"idle": 1, "wood": 1, "food": 1, "garrisoned": 1}
    assert alice["food_tasks"] == {"sheep": 1}  # herder classified by its name
    assert alice["units"] == {str(VILLAGER): 2, str(LUMBERJACK): 1, str(HERDER): 1}
    assert alice["garrisons"] == {"100": [VILLAGER]}
    assert alice["buildings"] == {str(TOWN_CENTER): 1} and alice["town_centers"] == 1
    assert alice["research_done"] == [22]
    assert alice["activity"] == {"idle": 1, "moving": 1, "gather_food": 1, "garrisoned": 1}
    assert alice["idle_town_centers"] == 1 and not alice["housed"]
    assert alice["diplomacy"] == {"2": "enemy"}  # never a stance towards itself
    no_offset = [0.0, 0.0]  # the emitter's spot on its object's picture
    assert v["particles"] == [
        [2.0, 3.0, 0.0, 7, 1.0, 2.0, 1.0, 0.75, 1.0, 1.0, 1.0, -1, 0, 0, 0.0, *no_offset]
    ]
    assert ids_activity(v, 103) == W.ACT_GATHER["food"]
    bob = v["players"]["2"]
    assert bob["military"] == 1 and bob["army_value"] == 135 and bob["army_gold"] == 75
    ids = {r[0]: r for r in v["entities"]}
    assert 107 not in ids  # doppelganger
    assert 108 not in ids  # inside the town centre
    assert ids[105][1] == 0 and ids[105][6] & 32  # gold mine (state 3 is alive for Gaia)
    assert 106 not in ids  # trees are a map layer, not entity rows
    assert ids[101][6] & 8 and ids[104][6] & 2 and ids[100][6] & 1
    assert not ids[100][6] & 16  # built
    assert ids[100][7] == 0 and ids[100][8] == []  # facet, no active sprites
    assert cat.masters[KNIGHT].cost == {"food": 60.0, "gold": 75.0}
    assert cat.masters[VILLAGER].train_time == 25
    assert cat.techs[101]["name"] == "Feudal Age" and cat.techs[22]["icon"] == 6


def ids_activity(v: dict[str, object], eid: int) -> int:
    rows = v["entities"]
    assert isinstance(rows, list)
    return int(next(r for r in rows if r[0] == eid)[9])


def test_production_and_research_progress(data: GameData) -> None:
    p = _patcher()
    p.apply(delta(500, produce(100, VILLAGER, 12.5, 2)).forward())
    cat = W.Catalog(data)
    v = W.view(p.root, cat)
    assert v is not None
    prod = v["players"]["1"]["production"]
    assert prod == [
        {
            "id": 100,
            "master": TOWN_CENTER,
            "x": 1.0,
            "y": 1.0,
            "current": {"unit": VILLAGER, "progress": 0.5, "remaining": 12.5},
            "queue": [{"unit": VILLAGER, "tech": -1, "count": 2}],
        }
    ]


def test_match_info_map_layers_and_resources(data: GameData) -> None:
    p = _patcher()
    info = W.match_info(p.root, data)
    assert info["map_file"] == "Arabia.rms" and info["map_size"] == [4, 4]
    assert info["players"][1]["elo"] == 1200 and info["players"][1]["team_key"] == 2
    assert info["players"][2]["color"] == "#ff0000"
    world = W.world_of(p.root)
    assert world is not None
    layer = W.map_layer(world, data)
    assert layer["width"] == 4 and len(layer["terrain"]) == 16 and layer["elevation"][5] == 2
    cat = W.Catalog(data)
    trees = W.tree_tiles(world, cat)
    tiles, kinds = trees
    assert len(tiles) == 32  # kind per tile, then facet per tile
    assert tiles[0 * 4 + 3] == 1 and sum(tiles[:16]) == 1 and kinds == [411]
    left = W.resources_left(world, cat)
    assert left["gold"] == 800 and left["relics"] == 0
    assert W.villager_task(GOLD_MINE, "Gold Mine") == (None, None)
    assert W.villager_task(579, "") == ("gold", None)
    assert W.villager_task(1, "Female Fisherman") == ("food", "fish")


def test_view_without_world_is_none(data: GameData) -> None:
    assert W.view(Patcher().root, W.Catalog(data)) is None


def _apply(p: Patcher, *steps: object) -> None:
    p.apply(delta(500, *steps).forward())


def test_military_value_uses_the_owners_own_master(data: GameData) -> None:
    p = _patcher()
    cat = W.Catalog(data)
    W.view(p.root, cat)  # the catalog caches player 1's knight first
    # Player 2's knights get cheaper (a civilisation discount) and stronger.
    _apply(
        p,
        set_master_cost(2, KNIGHT, ((0, 30.0), (3, 50.0))),
        set_master(2, KNIGHT, "MasterEntity", "hp", "Int16", 140),
    )
    v = W.view(p.root, cat)
    assert v is not None
    bob = v["players"]["2"]
    assert (bob["army_value"], bob["army_gold"]) == (80, 50)
    assert cat.masters[KNIGHT].cost == {"food": 60.0, "gold": 75.0}  # labels only
    row = next(r for r in v["entities"] if r[0] == 104)
    assert row[5] == round(100 / 140, 3)  # hp fraction of the owner's max hp


def test_kings_are_not_army_and_are_listed(data: GameData) -> None:
    p = _patcher()
    _apply(p, spawn(200, KING, 2, 3.5, 3.5, hp=60.0, action=False))
    v = W.view(p.root, W.Catalog(data))
    assert v is not None
    bob = v["players"]["2"]
    assert bob["military"] == 1 and bob["army_value"] == 135  # the knight only
    assert bob["units"][str(KING)] == 1  # still in the composition
    (king,) = v["kings"]
    assert king == {
        "pid": 2,
        "id": 200,
        "master": KING,
        "x": 3.5,
        "y": 3.5,
        "hp": 0.8,
        "garrisoned": False,
        "inside": -1,
    }
    row = next(r for r in v["entities"] if r[0] == 200)
    assert row[6] & 128 and not row[6] & 2
    assert W.is_king(9999, W.CLASS_KING) and W.is_king(KING, 0) and not W.is_king(1, 4)


def test_housed_is_false_at_the_population_limit(data: GameData) -> None:
    p = _patcher()
    b = PatchBuilder().push(fid("Root", "gameOptions"))
    b.assign(fid("GameOptions", "populationLimit"), "Int32", 4).pop()
    p.apply(b.forward())
    _apply(
        p, set_attr(1, "maxPop", 0.0), set_attr(2, "maxPop", 0.0), set_attr(2, "population", 3.0)
    )
    v = W.view(p.root, W.Catalog(data))
    assert v is not None
    assert v["players"]["1"]["housed"] is False  # 4/4 at a limit of 4
    assert v["players"]["2"]["housed"] is True  # 3/3, below the limit


def test_scene_construction_gates_bridges_and_charge(data: GameData) -> None:
    p = _patcher()
    _apply(
        p,
        spawn(300, HOUSE, 1, 0.5, 0.5, model="BuildingEntity", built=False, action=False),
        set_entity(300, "BuildingEntity", "buildPts", "Float", 10.0),
        spawn(301, HOUSE, 1, 1.5, 0.5, model="BuildingEntity", action=False),
        set_entity(301, "BuildingEntity", "gateLocked", "Boolean", True),
        spawn(302, BRIDGE, 0, 2.5, 0.5, model="BuildingEntity", action=False),
        set_entity(104, "CombatEntity", "charge", "Float", 5.0),
    )
    v = W.view(p.root, W.Catalog(data))
    assert v is not None
    assert v["construction"] == {"300": 0.4}  # 10 of 25 build points
    assert v["gates_locked"] == [301]
    assert v["charge"] == {"104": 5.0}
    bridge = next(r for r in v["entities"] if r[0] == 302)
    assert bridge[1] == 0 and bridge[6] & 64 and bridge[6] & 1
    assert v["koth"] is None and v["treaty"] is None


def test_score_parts_new_player_fields_and_elos(data: GameData) -> None:
    p = _patcher()
    _apply(
        p,
        set_attr(1, "unitsKilled", 3.0),
        set_attr(1, "razings", 1.0),
        set_attr(1, "unitsConverted", 2.0),
        set_attr(1, "buildValueTotalUnits", 500.0),
        set_attr(1, "buildValueTotalBuildings", 300.0),
        set_attr(1, "techCostSummation", 200.0),
        set_attr(1, "totalCastlesBuilt", 1.0),
        set_treaty(120, 600),
    )
    b = PatchBuilder().push(fid("Root", "world")).push_key(fid("World", "players"), 1)
    b.assign(fid("Player", "tradeGoldReceived"), "Float", 45.5).pop().pop()
    p.apply(b.forward())
    v = W.view(p.root, W.Catalog(data))
    assert v is not None
    alice = v["players"]["1"]
    parts = {"military": 10, "economy": 20, "technology": 5, "society": 1}
    assert alice["score"] == parts and alice["score_parts"] == parts
    assert alice["score_total"] == 36
    assert (alice["kills_total"], alice["value_spent"], alice["desertions"]) == (4, 1000, 2)
    assert (alice["castles_built"], alice["trade_profit"]) == (1, 46)
    assert (alice["elo_rm"], alice["elo_dm"]) == (1200, None)
    assert v["treaty"] == {"time_left_s": 120, "total_s": 600, "active": True}
    info = W.match_info(p.root, data)
    assert info["game_mode"] == "Random Map" and info["players"][2]["elo_rm"] == 1150


def test_master_detail_reads_every_unit_panel_number() -> None:
    p = _patcher()
    _apply(
        p,
        set_master(2, KNIGHT, "MasterCombatEntity", "minimumWeaponRange", "Float", 1.0),
        set_master(2, KNIGHT, "MasterCombatEntity", "baseHitChance", "Int16", 80),
        set_master(2, KNIGHT, "MasterCombatEntity", "volleyFireAmount", "Float", 3.0),
        set_master(2, KNIGHT, "MasterCombatEntity", "areaEffectRange", "Float", 0.5),
        set_master(2, KNIGHT, "MasterCombatEntity", "maxCharge", "Float", 20.0),
        set_master(2, KNIGHT, "MasterCombatEntity", "rechargeRate", "Float", 0.25),
        set_master(2, KNIGHT, "MasterCombatEntity", "regenerationRate", "Float", 15.0),
    )
    world = W.world_of(p.root)
    assert world is not None
    node = W.players_of(world)[2].fields[W.P_MASTERS][KNIGHT]
    d = W.master_detail(node.fields)
    assert (d["min_range"], d["accuracy"], d["projectiles"], d["blast_width"]) == (
        1.0,
        80,
        3.0,
        0.5,
    )
    assert (d["charge"]["attack"], d["charge"]["recharge"], d["charge"]["type"]) == (20.0, 0.25, 0)
    assert d["regen"] == 15.0
    assert d["hp"] == 100 and d["cost"] == {"food": 60.0, "gold": 75.0}
    assert d["attacks"] == [] and d["armors"] == []


def test_aura_and_work_ranges_from_tasks(data: GameData) -> None:
    p = _patcher()
    b = PatchBuilder().push(fid("Root", "world")).push_key(fid("World", "players"), 2)
    b.push_key(fid("Player", "masterEntities"), KNIGHT)
    for i, (action, rng) in enumerate(((155, 4.0), (7, 1.5), (155, 6.0))):
        b.create_insert(fid("MasterActionEntity", "tasks"), SCHEMA.model_id("Task"), i)
        b.assign(fid("Task", "actionType"), "Int16", action)
        b.assign(fid("Task", "workRange"), "Float", rng).pop()
    p.apply(b.pop().pop().pop().forward())
    world = W.world_of(p.root)
    assert world is not None
    node = W.players_of(world)[2].fields[W.P_MASTERS][KNIGHT]
    assert W.task_ranges(node.fields) == (6.0, 1.5)
    d = W.master_detail(node.fields)
    assert (d["aura_range"], d["work_range"]) == (6.0, 1.5)
    cat = W.Catalog(data)
    W.view(p.root, cat)
    unit = cat.to_json()["units"][str(KNIGHT)]
    assert unit["damage_sprites"] == []  # catalog from player 1's knight: no tasks


def test_pack_and_unpack_are_activities() -> None:
    from vantage.patch import Node
    from vantage.schema import SCHEMA

    for model, act in (("PackAction", W.ACT_PACKING), ("UnpackAction", W.ACT_UNPACKING)):
        e = Node(SCHEMA.model_id("Entity"), {W.E_ACTION: Node(SCHEMA.model_id(model), {})})
        assert W.unit_activity(e, None, garrisoned=False) == act
        assert W.ACTIVITY_NAMES[act] in ("packing", "unpacking")


# -- unit panel: base vs current, bonuses, charge, carry, lines --------------------

_M_TASK = SCHEMA.model_id("Task")
_M_MASTER = SCHEMA.model_id("MasterCombatEntity")
_M_COMBAT = SCHEMA.model_id("CombatEntity")
_M_ACTION = SCHEMA.model_id("Action")
_M_CLASSVAL = SCHEMA.model_id("AttributeValue")
_M_SOUND = SCHEMA.model_id("SoundEvent")


def _f(model: str, name: str) -> int:
    return SCHEMA.fid(SCHEMA.model_id(model), name)


def _task(action: int, **kw: object) -> Node:
    return Node(
        _M_TASK, {_f("Task", "actionType"): action, **{_f("Task", k): v for k, v in kw.items()}}
    )


def _classes(*pairs: tuple[int, int]) -> list[Node]:
    return [Node(_M_CLASSVAL, {0: c, 1: v} if v else {0: c}) for c, v in pairs]


def _master(**kw: object) -> Node:
    fields = {_f("MasterCombatEntity", k): v for k, v in kw.items()}
    return Node(_M_MASTER, fields)


def _unit(eid: int = 1, **kw: object) -> Node:
    return Node(
        _M_COMBAT,
        {_f("CombatEntity", "id"): eid, **{_f("CombatEntity", k): v for k, v in kw.items()}},
    )


def _ctx(*ents: Node, kills: list[int] | None = None) -> W.ModContext:
    table = {int(e.fields[W.E_ID]): e for e in ents}
    return W.ModContext(table, {}, (lambda eid: kills or []) if kills is not None else None)


def test_damage_over_time_from_task_157() -> None:
    f = _master(tasks=[
        _task(157, workVal1=-0.15, workVal2=10.0, searchWaitTime=5.0),  # not the DoT wait
        _task(157, workVal1=-180.0, workVal2=3.0, searchWaitTime=109.0),
        _task(157, workVal1=-60.0, workVal2=60.0, searchWaitTime=109.0),  # later: ignored
    ]).fields  # fmt: skip
    assert W.master_rules(f).dot == 9  # floor(180 * 3 / 60)
    assert W.master_detail(f)["dot"] == 9
    assert (
        W.master_rules(
            _master(tasks=[_task(157, workVal1=5, workVal2=3, searchWaitTime=109)]).fields
        ).dot
        == 0
    )
    assert W.master_detail(_master().fields)["dot"] == 0


def test_attack_and_armor_rows_follow_game_order_and_hide_class_31() -> None:
    f = _master(
        weapon=_classes((29, 1), (4, 5), (31, 5), (15, 2), (8, 0)),
        armor=_classes((27, 0), (1, 2), (4, 3), (31, 0)),
        origWeapon=3,
        origArmor=1,
    ).fields
    assert W.attack_rows(f) == [[29, 1, 1], [4, 3, 5], [15, 2, 2]]  # 31 hidden, zeros dropped
    # classes 4 and 3 always listed (3 is added), the game's order otherwise
    assert W.armor_rows(f) == [[3, 0, 0], [1, 2, 2], [4, 1, 3]]
    d = W.master_detail(f)
    assert d["attacks"][0] == [29, 1] and d["armors"][0] == [27, 0]  # not sorted
    assert d["base"]["attacks"][1] == [4, 3] and d["base"]["armors"][2] == [4, 1]
    # a pierce unit: class 3 takes the orig weapon, melee (lower) its own value
    pierce = _master(weapon=_classes((3, 6), (4, 2)), origWeapon=4).fields
    assert [r[1] for r in W.weapon_rows(pierce)] == [4, 2]


def test_regen_override_for_class_36_with_exempt_masters() -> None:
    f = _master(armor=_classes((36, 0), (4, 0)), regenerationRate=0.0).fields
    assert W.regen_display(f, 5000) == 30.0 and W.regen_display(f) == 30.0
    assert W.regen_display(f, 434) == 0.0  # exempt master keeps its own regen
    assert W.master_detail(f, 5000)["regen_display"] == 30


def test_speed_boost_masters_and_flat_regen_ignore_power_ups() -> None:
    f = _master(speed=1.0, armor=_classes((36, 0), (4, 0)), regenerationRate=0.0).fields
    boosted = W.master_detail(f, 936)
    assert boosted["base"]["speed"] == 1.2 and boosted["speed"] == 1.2
    assert W.master_detail(f, 5000)["base"]["speed"] == 1.0
    # power-ups add to the boosted speed; a unit exactly like its master has no mods
    e = _unit(speedPowerUp=0.1)
    rules = W.master_rules(f)
    assert W.entity_mods(e, f, rules, _ctx(e), {}, 1301)[0]["speed"] == 1.3
    assert "speed" not in W.entity_mods(_unit(), f, rules, _ctx(), {}, 1301)[0]
    # class-36 regeneration is a flat 30: power-ups and stingers never add to it
    r = _unit(regenerationRatePowerUp=5.0, regenerationStinger=2.0)
    assert "regen" not in W.entity_mods(r, f, rules, _ctx(r), {}, 5000)[0]
    plain = _master(regenerationRate=1.0).fields
    assert W.entity_mods(r, plain, W.master_rules(plain), _ctx(r), {}, 5000)[0]["regen"] == 8


def test_kill_stack_rules_group_by_values_and_apply_cap() -> None:
    hp = {"holdingAttr": 1, "workFlag": 10, "workFlag2": 6}
    f = _master(tasks=[
        _task(154, objectGroup=0, **hp),  # searchWaitTime absent = HP
        _task(154, objectGroup=6, **hp),
        _task(154, objectGroup=2, workFlag=1, workFlag2=4, searchWaitTime=9.0, holdingAttr=2),
        # a task with workVal1 set is a resource bonus, not a stack
        _task(154, objectGroup=2, workVal1=20.0, attributeType2=274, attributeType3=3),
    ]).fields  # fmt: skip
    rules = W.master_rules(f).kill_stack
    assert rules == [
        {"stat": "hp", "groups": [0, 6], "increment": 10, "cap": 6},
        {"stat": "attack", "groups": [2], "increment": 1, "cap": 4},
    ]
    assert W.kill_stack_bonus(rules, []) == {"hp": 0, "attack": 0}
    assert W.kill_stack_bonus(rules, [0]) == {"hp": 0, "attack": 0}  # (1 - 1) * inc
    assert W.kill_stack_bonus(rules, [0, 6, 6, 21]) == {"hp": 20, "attack": 0}
    assert W.kill_stack_bonus(rules, [0] * 20 + [2] * 9) == {"hp": 50, "attack": 3}  # capped


def test_entity_mods_apply_powerups_stingers_and_kill_stack() -> None:
    master = _master(
        hp=100, speed=1.0, speedOfAttack=2.0, weaponRange=4.0, regenerationRate=0.0,
        weapon=_classes((3, 6), (4, 2), (15, 1)), origWeapon=6,
        armor=_classes((4, 2), (3, 4), (8, 1)), origArmor=1, origPierceArmor=2,
        tasks=[_task(154, objectGroup=6, holdingAttr=1, workFlag=2, workFlag2=5,
                     searchWaitTime=9.0)],
    ).fields  # fmt: skip
    e = _unit(
        attackPowerUp=2.6, attackStinger=1, meleeArmorPowerUp=1, pierceArmorRemoved=2,
        pierceArmorStinger=1, maxRangePowerup=1.0, reloadPowerUp=0.5, reloadStinger=0.1,
        speedPowerUp=0.1, speedStinger=0.05, hitpointsMaxPowerUp=10.9, hitpointsMaxStinger=5,
        numUnitsPoweredUpBy=3, hp=80.0,
    )  # fmt: skip
    rules = W.master_rules(master)
    mods, hp_bonus, hpmax_bonus = W.entity_mods(e, master, rules, _ctx(e, kills=[6, 6, 6]), {})
    # floor(2.6) + 1 stinger + (3 kills - 1) * 2 stack = 7 on classes 3 and 4 only
    assert mods["attacks"] == [[3, 13], [4, 9], [15, 1]]
    assert mods["kill_bonus"] == {"hp": 0, "attack": 4}
    assert mods["armors"] == [[4, 3], [3, 3], [8, 1]]  # 2+1 melee, 4-2+1 pierce
    assert (mods["range"], mods["reload"], mods["speed"]) == (5, 1.6, 1.15)
    assert (mods["hp_max"], mods["hp"], mods["powered_by"]) == (115, 95, 3)
    assert (hp_bonus, hpmax_bonus) == (15.0, 15.0)
    # a unit exactly like its master produces nothing
    assert W.entity_mods(_unit(), master, rules, _ctx(), {}) == ({}, 0.0, 0.0)


def test_kill_stack_hp_goes_to_max_hp_only() -> None:
    master = _master(hp=100, tasks=[_task(154, objectGroup=0, workFlag=10, workFlag2=6)]).fields
    mods, hp_bonus, hpmax_bonus = W.entity_mods(
        _unit(hp=90.0), master, W.master_rules(master), _ctx(kills=[0, 0, 0]), {}
    )
    assert mods["hp_max"] == 120 and "hp" in mods and mods["hp"] == 90
    assert (hp_bonus, hpmax_bonus) == (0.0, 20.0)


def test_hp_loss_bonus_from_self_or_target() -> None:
    target_master = _master(hp=100, type=70)
    tgt = Node(
        _M_COMBAT,
        {W.E_ID: 9, W.E_HP: 40.0, W.E_MASTER: 7, W.E_OWNER: 2, W.E_OWN_MASTER: target_master},
    )
    act = Node(_M_ACTION, {W.A_TYPE: 9, W.A_TARGET: 9})
    own = _master(hp=100, tasks=[_task(160, workVal1=1.0, workVal2=0.15, workRange=1.0)]).fields
    e = _unit(1)
    e.fields[W.E_ACTION] = act
    mods, _, _ = W.entity_mods(e, own, W.master_rules(own), _ctx(e, tgt), {})
    assert mods["hp_loss"] == 4  # 1 * floor((1 - 0.4) / 0.15)
    assert W.master_detail(own)["hp_loss_bonus"] == {"amount": 1, "step": 0.15, "self": False}
    # a building target is ignored
    tgt.fields[W.E_OWN_MASTER] = _master(hp=100, type=80)
    assert "hp_loss" not in W.entity_mods(e, own, W.master_rules(own), _ctx(e, tgt), {})[0]
    # workRange 0: the unit's own hp, only while attacking
    selfm = _master(hp=100, tasks=[_task(160, workVal1=2.0, workVal2=0.25)]).fields
    e2 = _unit(2, hp=50.0)
    assert "hp_loss" not in W.entity_mods(e2, selfm, W.master_rules(selfm), _ctx(e2), {})[0]
    e2.fields[W.E_ACTION] = Node(_M_ACTION, {W.A_TYPE: 9})
    mods2, _, _ = W.entity_mods(e2, selfm, W.master_rules(selfm), _ctx(e2), {})
    assert mods2["hp_loss"] == 4  # 2 * floor(0.5 / 0.25)


def test_charge_rules_instant_recharge_and_target_masks() -> None:
    f = _master(maxCharge=20.0, rechargeRate=0.5, chargeType=1, chargeEvent=0).fields
    ch = W.charge_info(f)
    assert (ch["show"], ch["value"], ch["recharge_time"], ch["instant"]) == (
        True,
        20.0,
        40.0,
        False,
    )
    inst = W.charge_info(_master(maxCharge=1.0, rechargeRate=100.0, chargeType=1).fields)
    assert inst["instant"] and not inst["show"] and inst["recharge_time"] is None
    assert not W.charge_info(_master(maxCharge=5.0, chargeType=0).fields)["show"]
    assert (
        W.charge_info(_master(maxCharge=5.0, chargeType=1, chargeEvent=-1).fields)["recharge_time"]
        is None
    )
    assert W.charge_applies(-1, 3) and W.charge_applies(0, 6) and not W.charge_applies(0, 52)
    assert W.charge_applies(1, 6) and not W.charge_applies(1, 12)  # infantry bit only
    assert W.charge_applies(2 | 64, 21) and W.charge_applies(256, 27)


def test_charged_weapon_projectile_and_charge_speed() -> None:
    projectile = _master(weapon=_classes((3, 10), (15, 3)), origWeapon=10)
    own = _master(
        hp=60, speed=1.0, maxCharge=10.0, rechargeRate=0.5, chargeType=6, chargeEvent=3,
        chargeProjectileUnit=99, chargeTarget=0, weapon=_classes((4, 4)), origWeapon=4,
        tasks=[_task(133, workRange=1.5, workFlag2=2001)],
    ).fields  # fmt: skip
    e = _unit(charge=5.0, isCharging=1)
    rules = W.master_rules(own)
    assert rules.charge_speed == 1.5
    mods, _, _ = W.entity_mods(e, own, rules, _ctx(e), {99: projectile})
    assert mods["charge_fill"] == 0.5 and mods["charge_applies"] is True
    assert mods["charge_value"] == 6  # projectile 10 - own 4
    # base of class 3: the unit has none, so the projectile's; class 4 is dropped (own only)
    assert mods["charged_weapon"] == [[3, 10, 10], [15, 3, 3]]
    assert mods["range"] == 3 and mods["speed"] == 1.5 and mods["charging"] is True
    # a 6/7 charge does not apply to a target outside chargeTarget (here: 0 = not buildings)
    e.fields[W.E_ACTION] = Node(_M_ACTION, {W.A_TARGET: 8})
    wall = Node(_M_COMBAT, {W.E_ID: 8, W.E_OWN_MASTER: _master(objectGroup=27, type=80)})
    m2, _, _ = W.entity_mods(e, own, rules, _ctx(e, wall), {99: projectile})
    assert m2["charge_applies"] is False and "range" not in m2


def test_aura_ids_need_the_ability_bit_and_resolve_a_string() -> None:
    se = Node(_M_SOUND, {_f("SoundEvent", "eventId"): 777})
    tasks = [
        _task(155, objectGroup=6, depositSoundEvent=se, workRange=4.0),
        _task(155, objectGroup=-1, objectId=-1, depositSoundEvent=Node(_M_SOUND, {0: 5})),
    ]
    f = _master(tasks=tasks, combatAbility=32 | 1).fields
    assert W.master_rules(f).aura_ids == [777]
    assert W.master_detail(f)["aura"] == {"string_ids": [777]}
    assert W.master_rules(_master(tasks=tasks, combatAbility=1).fields).aura_ids == []
    assert W.aura_description([5, 777], {777: "Shield Wall"}) == "Shield Wall"
    assert W.aura_description([5], {}) == ""


def test_carried_resources_secondary_and_civ_bonus() -> None:
    task = _task(164, attributeType=-1, attributeType2=276, attributeType3=1, workVal1=0.5)
    rules = W.master_rules(_master(tasks=[task]).fields)
    ef = _unit(heldAttributeType=3, heldAttributeAmount=10.0).fields
    ef[W.E_TRANSIENT_TYPE] = -1
    assert W.carry_amount(ef, rules, 26, lambda t: False) == [
        "gold",
        10.0,
        "wood",
        50.0,
    ]
    assert W.carry_amount(ef, rules, 1, lambda t: False) == ["gold", 10.0]  # no bonus for civ 1
    # a tech-gated bonus (civ 31, attribute 266) only with the tech researched
    gated = W.master_rules(
        _master(
            tasks=[_task(164, attributeType=-1, attributeType2=266, attributeType3=0, workVal1=1.0)]
        ).fields
    )
    assert W.carry_amount(ef, gated, 31, lambda t: False) == ["gold", 10.0]
    assert W.carry_amount(ef, gated, 31, lambda t: t == 629) == ["gold", 10.0, "food", 15.0]
    # the game's own transient value wins; types 15-17 read as food
    ef[W.E_TRANSIENT_TYPE], ef[W.E_TRANSIENT_AMT] = 16, 2.5
    assert W.carry_amount(ef, rules, 26, lambda t: False) == ["gold", 10.0, "food", 2.5]
    assert W.carry_amount(_unit().fields, rules, 26, lambda t: False) == 0


def test_unit_lines_identity_military_and_train_locations() -> None:
    lines = {93: "l5", 13: "l7"}
    assert W.unit_line(93, 6, lines) == "l5"
    assert W.unit_line(2999, W.CLASS_FISHING_BOAT, lines) == "l7"  # any fishing ship = ship 13
    assert W.unit_line(2999, W.CLASS_FISHING_BOAT, {}) == "m13"
    assert W.unit_line(500, 12, lines) == "m500" and W.unit_identity(500, 12) == 500
    assert W.is_military_master(70, 12) and not W.is_military_master(70, W.CLASS_CIVILIAN)
    assert not W.is_military_master(80, 3) and not W.is_military_master(70, W.CLASS_KING)
    assert W.train_locations(_master(idOfBuildingObj=12, trainLocationIds=[12, 1665]).fields) == [
        12,
        1665,
    ]
    assert W.train_locations(_master().fields) == []


def test_master_detail_garrison_summary_and_object_group() -> None:
    d = W.master_detail(_master(objCapacity=5, objectGroup=12, combatAbility=7).fields)
    assert d["garrison_capacity"] == 5 and d["garrison_summary"] is False
    assert (d["object_group"], d["combat_ability"]) == (12, 7)
    assert W.master_detail(_master(objCapacity=5, objectGroup=3).fields)["garrison_summary"] is True


def _mini_world(entities: dict[int, Node], masters: dict[int, Node], civ: int = 26) -> Node:
    player = Node(
        SCHEMA.model_id("Player"),
        {W.P_ID: 1, W.P_CIV: civ, W.P_MASTERS: masters, W.P_RESEARCH: {}},
    )
    gaia = Node(SCHEMA.model_id("Player"), {W.P_ID: 0})
    return Node(
        SCHEMA.model_id("World"),
        {W.W_ENTITIES: entities, W.W_PLAYERS: {0: gaia, 1: player}},
    )


def test_tally_reports_mods_livestock_owner_and_secondary_carry(data: GameData) -> None:
    sheep_master = _master(type=70, objectGroup=58, hp=7)
    vill = _master(
        type=70, objectGroup=W.CLASS_CIVILIAN, hp=25,
        tasks=[_task(164, attributeType=-1, attributeType2=276, attributeType3=1, workVal1=1.0)],
    )  # fmt: skip
    ents: dict[int, Node] = {
        5: Node(_M_COMBAT, {W.E_ID: 5, W.E_MASTER: 100, W.E_OWNER: 1, W.E_STATE: 2}),
        6: Node(
            _M_COMBAT,
            {W.E_ID: 6, W.E_MASTER: 101, W.E_OWNER: 1, W.E_STATE: 2, W.E_HELD_TYPE: 3,
             W.E_HELD_AMT: 4.0, W.E_TRANSIENT_TYPE: -1,
             _f("CombatEntity", "hitpointsMaxPowerUp"): 5.0},
        ),
    }  # fmt: skip
    cat = W.Catalog(data)
    world = _mini_world(ents, {100: sheep_master, 101: vill})
    scene = W.Scene()
    _, rows = W.tally(world, cat, scene)
    assert cat.last_owner == {5: 1}
    by_id = {r[0]: r for r in rows}
    assert by_id[6][-1] == ["gold", 4.0, "wood", 40.0]
    assert by_id[5][-1] == 0  # nothing held or in transit: no carry
    assert scene.unit_mods["6"]["hp_max"] == 30 and "5" not in scene.unit_mods
    # the sheep is captured back by Gaia: the panel keeps the last owner
    ents[5].fields[W.E_OWNER] = 0
    scene2 = W.Scene()
    _, rows2 = W.tally(world, cat, scene2)
    assert scene2.livestock_owner == {"5": 1}
    assert any(r[0] == 5 and r[1] == 0 for r in rows2)  # Gaia livestock is a map row


def test_resources_report_what_is_left_and_who_gathers(data: GameData) -> None:
    """Gaia rows carry what a resource still holds; trees (a tile layer) are listed
    only once cut; villagers' gather targets are counted per player; the catalog
    gives each resource master its full store."""

    def held(res: int, amount: float) -> list[Node]:
        return [Node(_M_CLASSVAL, {0: res, 1: amount} if res else {1: amount})]

    gold = _master(type=10, objectGroup=32, hp=1, attributesHeld=held(3, 800.0))
    tree = _master(type=10, objectGroup=15, hp=1, attributesHeld=held(1, 100.0))
    vill = _master(type=70, objectGroup=W.CLASS_CIVILIAN, hp=25)
    gather = Node(_M_ACTION, {W.A_TYPE: 5, W.A_TARGET: 10})
    chop = Node(_M_ACTION, {W.A_TYPE: 5, W.A_TARGET: 12})

    def ent(eid: int, mid: int, owner: int, x: float, **f: object) -> Node:
        fields: dict[int, object] = {W.E_ID: eid, W.E_MASTER: mid, W.E_OWNER: owner,
                                     W.E_STATE: 2, W.E_X: x, W.E_Y: 3.5}  # fmt: skip
        fields.update({int(k[1:]): v for k, v in f.items()})
        return Node(_M_COMBAT, fields)

    ents = {
        10: ent(10, 66, 0, 1.5, **{f"f{W.E_HELD_TYPE}": 3, f"f{W.E_HELD_AMT}": 640.0}),
        11: ent(11, 411, 0, 2.5, **{f"f{W.E_HELD_TYPE}": 1, f"f{W.E_HELD_AMT}": 100.0}),
        12: ent(12, 411, 0, 3.5, **{f"f{W.E_HELD_TYPE}": 1, f"f{W.E_HELD_AMT}": 61.5,
                                    f"f{W.E_STATE}": W.ENTITY_RESOURCE}),
        20: ent(20, 579, 1, 1.0, **{f"f{W.E_ACTION}": gather}),
        21: ent(21, 579, 1, 1.2, **{f"f{W.E_ACTION}": gather}),
        22: ent(22, 123, 1, 3.0, **{f"f{W.E_ACTION}": chop}),
    }  # fmt: skip
    masters = {579: vill, 123: vill}
    player = Node(
        SCHEMA.model_id("Player"), {W.P_ID: 1, W.P_CIV: 1, W.P_MASTERS: masters, W.P_RESEARCH: {}}
    )
    gaia = Node(SCHEMA.model_id("Player"), {W.P_ID: 0, W.P_MASTERS: {66: gold, 411: tree}})
    world = Node(SCHEMA.model_id("World"), {W.W_ENTITIES: ents, W.W_PLAYERS: {0: gaia, 1: player}})
    cat = W.Catalog(data)
    scene = W.Scene()
    _, rows = W.tally(world, cat, scene)
    by_id = {r[0]: r for r in rows}
    assert by_id[10][10] == ["gold", 640.0]
    assert 11 not in by_id and 12 not in by_id  # trees are the forest layer
    assert scene.trees_left == [[3.5, 3.5, 61.5, 12]]  # the full tree is not listed
    assert scene.gatherers == {"10": {"1": 2}, "12": {"1": 1}}
    assert scene.gather_targets == {"20": 10, "21": 10, "22": 12}
    units = cat.to_json()["units"]
    assert units["66"]["storage"] == ["gold", 800.0] and units["411"]["storage"] == ["wood", 100.0]
    assert "storage" not in units["579"]


def test_master_storage_reads_the_first_held_attribute() -> None:
    def held(*pairs: tuple[int, float]) -> dict[int, object]:
        return {W.M_HELD: [Node(_M_CLASSVAL, {0: t, 1: a} if t else {1: a}) for t, a in pairs]}

    assert W.master_storage(held((0, 125.0))) == ["food", 125.0]  # type absent = food
    assert W.master_storage(held((2, 350.0), (1, 5.0))) == ["stone", 350.0]
    assert W.master_storage(held((4, -1.0))) is None  # a villager's attribute 4, not a store
    assert W.master_storage({}) is None


def test_catalog_json_carries_lines_armor_names_and_civ_eras(data: GameData) -> None:
    cat = W.Catalog(data)
    mnode = _master(type=70, objectGroup=W.CLASS_FISHING_BOAT, hp=60, stringId=5121,
                    objCapacity=3, idOfBuildingObj=45, trainLocationIds=[45, 1])  # fmt: skip
    info = cat.master(2999, mnode)
    assert info is not None
    j = cat.to_json()
    row = j["units"]["2999"]
    assert (row["line"], row["identity"], row["military"]) == ("m13", 13, False)
    assert row["most_created_ok"] is False and row["garrison_capacity"] == 3
    assert row["train_locations"] == [45, 1] and row["string_id"] == 5121
    assert j["building_groups"] == {"settlement": [2556, 2558, 2560]}
    for key in ("unit_lines", "armor_classes", "civ_eras", "eras", "unique_techs", "power_techs"):
        assert key in j
    knight = cat.master(77, _master(type=70, objectGroup=12, hp=100))
    assert knight is not None
    assert cat.to_json()["units"]["77"]["most_created_ok"] is True
    cat.master(1252, _master(type=70, objectGroup=12, hp=1))
    assert cat.to_json()["units"]["1252"]["most_created_ok"] is False


def test_folwark_rule_comes_from_the_owner_attributes(data: GameData) -> None:
    p = _patcher()
    _apply(p, set_attr(2, "folwarkBuildingId", 68.0), set_attr(2, "folwarkCollectAmount", 37.5))
    v = W.view(p.root, W.Catalog(data))
    assert v is not None
    assert v["players"]["2"]["folwark_building"] == 68
    assert v["players"]["2"]["folwark_food"] == 37.5
    assert v["players"]["2"]["folwark_reach"] == W.FOLWARK_REACH == 4
    assert v["players"]["1"]["folwark_building"] is None  # civs without a Folwark


def test_catalog_keeps_each_owners_own_name_for_a_master(data: GameData) -> None:
    cat = W.Catalog(data)
    cat.master(68, _master(type=80, hp=600, stringId=5157, buttonPict=19))
    assert cat.own_master(1, 68, _master(type=80, hp=600, stringId=5157, buttonPict=19)) is None
    folwark = _master(type=80, hp=600, stringId=5581, buttonPict=86)
    assert cat.own_master(2, 68, folwark) == (5581, 86)
    assert cat.own_master(0, 68, folwark) is None  # Gaia keeps the catalog's
    j = cat.to_json()
    assert j["units"]["68"]["string_id"] == 5157
    assert j["unit_names"] == {"5581": data.string(5581, "")}


def test_view_names_a_players_own_master_at_that_time(data: GameData) -> None:
    p = _patcher()
    v = W.view(p.root, W.Catalog(data))
    assert v is not None and v["owner_units"] == {}
    cat = W.Catalog(data)
    W.view(p.root, cat)
    _apply(p, set_master(2, KNIGHT, "MasterEntity", "stringId", "Int32", 5070))
    v = W.view(p.root, cat)
    assert v is not None
    assert v["owner_units"]["2"][str(KNIGHT)][0] == 5070
    assert "5070" in cat.to_json()["unit_names"]


def test_projectiles_are_neither_units_nor_military(data: GameData) -> None:
    cat = W.Catalog(data)
    arrow = cat.master(746, _master(type=60, objectGroup=11, hp=1))
    archer = cat.master(4, _master(type=70, objectGroup=0, hp=30))
    assert arrow is not None and archer is not None
    assert (arrow.kind, archer.kind) == ("other", "unit")
    assert not W.is_military_master(60, 0) and W.is_military_master(70, 0)


def test_terrain_tiles_follow_the_game(data: GameData) -> None:
    p = _patcher()
    world = W.world_of(p.root)
    assert world is not None
    before = W.terrain_tiles(world)
    layer = W.map_layer(world, data)
    assert len(before) == 32 and before[:16] == layer["terrain"] and before[16:] == layer["layers"]
    assert set(before[16:]) == {0}  # native fresh exports omit layer0

    def farm(b: PatchBuilder) -> None:
        b.push_key(fid("World", "mapTiles"), 5).assign(fid("MapTile", "terrainType"), "UInt8", 7)
        b.assign(fid("MapTile", "layerType"), "Int16", 12)
        b.pop()

    _apply(p, farm)
    now = W.terrain_tiles(world)
    assert now[5] == 7 and now[4] == before[4]
    assert now[16 + 5] == 12 and now[16 + 4] == 0  # grass laid over tile 5


def test_terrain_cache_rereads_only_the_tiles_patches_reached(data: GameData) -> None:
    p = _patcher()
    world = W.world_of(p.root)
    assert world is not None
    cache = W.TerrainTiles()
    assert cache(world) == W.terrain_tiles(world)

    def farm(b: PatchBuilder) -> None:
        b.push_key(fid("World", "mapTiles"), 5).assign(fid("MapTile", "terrainType"), "UInt8", 7)
        b.pop()

    _apply(p, farm)  # the patch marks tile 5 touched
    assert cache(world)[5] == 7 and cache(world) == W.terrain_tiles(world)
    tiles = world.fields[W.W_TILES]
    # Only touched tiles are read again: an edit no patch made is not seen...
    tiles[6].fields[W.TILE_TERRAIN] = 9
    assert cache(world)[6] != 9
    tiles[6].touched = True  # ...until the tile is marked, as a patch marks it
    assert cache(world)[6] == 9
    tiles[7] = None  # a tile that is not an object: base 0, no layer
    assert cache(world) == W.terrain_tiles(world)
    world.fields[W.W_TILES] = [Node(SCHEMA.model_id("MapTile"), {W.TILE_TERRAIN: 3})] * 16
    assert cache(world) == W.terrain_tiles(world)  # a new tile list: read whole
    assert cache(world)[:16] == bytes([3] * 16)


def test_tally_collects_remains_and_air_in_its_one_walk(data: GameData) -> None:
    ent, spr = SCHEMA.model_id("Entity"), SCHEMA.model_id("ActiveSprite")
    tile = SCHEMA.model_id("MapTile")

    def entity(eid: int, state: int, z: float = 0.0, dopple: int = 0) -> Node:
        return Node(ent, {
            W.E_ID: eid, W.E_OWNER: 2, W.E_MASTER: 502, W.E_X: 1.5, W.E_Y: 0.5, W.E_Z: z,
            W.E_STATE: state, W.E_DOPPLE: dopple,
            W.E_SPRITES: [Node(spr, {W.AS_SPRITE: 77, W.AS_FRAME: 3})],
        })  # fmt: skip

    ents = {
        1: entity(1, W.ENTITY_DECAYING),
        2: entity(2, W.ENTITY_ALIVE, z=9.0),
        3: entity(3, W.ENTITY_DYING, z=8.0),
        4: entity(4, W.ENTITY_DECAYING, z=7.0, dopple=1),  # in the air list, not remains
        5: entity(5, W.ENTITY_RESOURCE),
    }
    world = Node(
        SCHEMA.model_id("World"),
        {W.W_MAP_W: 2, W.W_MAP_H: 2, W.W_ENTITIES: ents,
         W.W_TILES: [Node(tile, {W.TILE_ELEV: 2}) for _ in range(4)]},
    )  # fmt: skip
    scene = W.Scene()
    W.tally(world, W.Catalog(data), scene)
    assert scene.remains == W.remains_rows(world) and [r[0] for r in scene.remains] == [1, 3, 5]
    assert scene.air == W.air_heights(world) == {"2": 9.0, "3": 8.0, "4": 7.0}


def test_terrain_tiles_distinguish_omitted_zero_from_explicit_no_layer() -> None:
    tiles = [
        Node(SCHEMA.model_id("MapTile"), fields)
        for fields in ({}, {W.TILE_LAYER: 0}, {W.TILE_LAYER: -1}, {W.TILE_LAYER: 12})
    ]
    world = Node(SCHEMA.model_id("World"), {W.W_MAP_W: 4, W.W_MAP_H: 1, W.W_TILES: tiles})
    assert W.terrain_tiles(world) == bytes((0, 0, 0, 0, 0, 0, W.NO_LAYER, 12))


def test_pop_cap_is_housing_clamped_to_the_lobby_limit() -> None:
    assert W.pop_cap(164, 271, 200) == 200  # five TCs and many houses: still 200
    assert W.pop_cap(40, 5, 200) == 45
    assert W.pop_cap(205, 0, 200) == 205  # above the limit (conversions): never below pop
    assert W.pop_cap(40, 5, None) == 45


def test_research_time_applies_the_players_adjustment(data: GameData) -> None:
    cat = W.Catalog(data)
    cat.techs[101] = {"time": 130, "name": "Feudal Age"}
    rs = Node(SCHEMA.model_id("ResearchState"), {W.R_ADJUST: -52})
    assert W.research_time(cat, 101, {101: rs}) == 78  # the Malay bonus
    assert W.research_time(cat, 101, {}) == 130
    assert W.research_time(cat, 999, {999: rs}) == 0  # unknown tech: no time


def test_remains_rows_carry_the_dead_left_on_the_ground() -> None:
    """Dying units and decaying corpses/rubble are drawn (view.remains) but are not
    entity rows; living units and doppelgangers are not remains."""
    ent, spr = SCHEMA.model_id("Entity"), SCHEMA.model_id("ActiveSprite")

    def entity(eid: int, state: int, **extra: object) -> Node:
        fields: dict[int, object] = {
            W.E_ID: eid, W.E_OWNER: 2, W.E_MASTER: 502, W.E_X: 10.5, W.E_Y: 4.25,
            W.E_STATE: state, W.E_SPRITES: [Node(spr, {W.AS_SPRITE: 77, W.AS_FRAME: 3})],
        }  # fmt: skip
        fields.update({int(k[1:]): v for k, v in extra.items()})
        return Node(ent, fields)

    dopple = entity(4, W.ENTITY_DECAYING, **{f"f{W.E_DOPPLE}": 1})
    flare = entity(6, W.ENTITY_RESOURCE, **{f"f{W.E_MASTER}": 274})
    states = {1: W.ENTITY_DECAYING, 2: W.ENTITY_ALIVE, 3: W.ENTITY_DYING, 5: W.ENTITY_RESOURCE}
    ents = {k: entity(k, st) for k, st in states.items()}  # 5: a player's rubble
    world = Node(SCHEMA.model_id("World"), {W.W_ENTITIES: {**ents, 4: dopple, 6: flare}})
    rows = W.remains_rows(world)
    assert [r[0] for r in rows] == [1, 3, 5]
    assert all(r[10] == 0 for r in rows)  # a player's dead hold nothing to gather
    carcass = entity(7, W.ENTITY_DECAYING, **{f"f{W.E_OWNER}": 0, f"f{W.E_HELD_AMT}": 22.5})
    world.fields[W.W_ENTITIES][7] = carcass
    assert W.remains_rows(world)[-1][10] == ["food", 22.5]  # a hunted animal's carcass
    assert rows[0][1:5] == [2, 502, 10.5, 4.25] and rows[0][8] == [[77, 3, 0, 0]]
    assert rows[0][6] == W.FLAG_REMAINS  # plays once: the browser holds the last frame


def test_air_heights_list_only_objects_above_the_ground() -> None:
    ent, tile = SCHEMA.model_id("Entity"), SCHEMA.model_id("MapTile")
    tiles = [Node(tile, {W.TILE_ELEV: 2}) for _ in range(4)]

    def entity(eid: int, z: float) -> Node:
        return Node(ent, {W.E_ID: eid, W.E_X: 1.5, W.E_Y: 0.5, W.E_Z: z})

    world = Node(
        SCHEMA.model_id("World"),
        {W.W_MAP_W: 2, W.W_MAP_H: 2, W.W_TILES: tiles,
         W.W_ENTITIES: {1: entity(1, 2.4), 2: entity(2, 9.0), 3: entity(3, 3.0)}},
    )  # fmt: skip
    # On a level-2 tile the ground is at most level 3: only the bird (9) is in the air.
    assert W.air_heights(world) == {"2": 9.0}


def _missile(x: float, y: float, state: int | None = None, sprite: int = 10, mid: int = 3) -> Node:
    f: dict[int, object] = {
        W.E_OWNER: 1,
        W.E_MASTER: mid,
        W.E_X: x,
        W.E_Y: y,
        W.E_Z: 0.126,
        W.E_SPRITE: sprite,
    }
    if state is not None:
        f[W.E_STATE] = state
    return Node(W.MODEL_MISSILE, f)


def test_missile_rows_list_live_projectiles_with_sprites_only() -> None:
    plain = Node(SCHEMA.model_id("CombatEntity"), {W.E_X: 1.0, W.E_SPRITE: 10})
    ents = {
        -1: _missile(1.234, 5.678),
        -2: _missile(2.0, 2.0, state=W.ENTITY_ALIVE),
        -3: _missile(3.0, 3.0, state=W.ENTITY_ALIVE + 1),  # dead
        -4: _missile(4.0, 4.0, sprite=-1),  # nothing to draw
        -5: plain,  # not a missile
        7: _missile(7.0, 7.0),  # positive ids are ordinary entities
    }
    world = Node(0, {W.W_ENTITIES: ents})
    rows = W.missile_rows(world)
    assert [r[0] for r in rows] == [-1, -2]
    assert rows[0] == [-1, 1, 3, 1.23, 5.68, 0.13, 0, [[10, 0, 0, 0]]]


def _trail_catalog(effect: str, trail_id: int = 77, spacing: float = 0.4) -> tuple[W.Catalog, Node]:
    mm = SCHEMA.model_id("MasterMissileEntity")
    sprite = Node(0, {W.SP_EFFECT: effect} if effect else {})
    trail_master = Node(0, {W.M_SPRITE: 1})
    player = Node(0, {W.P_MASTERS: {77: trail_master}})
    cat = W.Catalog(GameData(None))
    cat.world_sprites = [None, sprite]
    cat.world_players = {1: player}
    arrow = Node(mm, {W.MM_TRAIL: trail_id, W.MM_TRAIL_SPACING: spacing})
    return cat, arrow


def test_missile_master_trail_names_the_particle_and_spacing() -> None:
    cat, arrow = _trail_catalog("smoke_trail")
    assert cat._trail(arrow) == {"particle": "smoke_trail", "spacing": 0.4}
    info = cat.master(3, arrow)
    assert info is not None and info.trail == {"particle": "smoke_trail", "spacing": 0.4}
    assert cat.to_json()["units"]["3"]["trail"] == info.trail


def test_missile_master_without_a_trail_has_none() -> None:
    cat, arrow = _trail_catalog("smoke_trail", trail_id=-1)
    assert cat._trail(arrow) is None
    cat, arrow = _trail_catalog("smoke_trail", spacing=0.0)
    assert cat._trail(arrow) is None
    cat, arrow = _trail_catalog("")  # the trail's sprite has no effect
    assert cat._trail(arrow) is None
    cat, _ = _trail_catalog("smoke_trail")
    assert cat._trail(Node(SCHEMA.model_id("MasterCombatEntity"), {})) is None
