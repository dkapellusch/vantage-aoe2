"""Typed reading of the decoded state tree, and the view model the UI consumes.

:mod:`vantage.patch` keeps the world as a generic tree keyed by field id.
This module names the parts a spectator needs -- players, their economy and
army, buildings and what they produce, research, the map -- and flattens one
moment of the game into a JSON-ready :func:`view` plus a few aggregates for the
time series. Field ids come from :mod:`vantage.schema` by name, so a
schema change shows up as a ``KeyError`` here rather than as silently wrong data.

Classification tables (unit ids per villager task, unit class ids) are AoE2
game-data facts.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Iterable, Iterator, Sequence
from dataclasses import dataclass, field
from typing import Any

from vantage.gamedata import SETTLEMENT_MASTERS, GameData
from vantage.patch import Node
from vantage.schema import SCHEMA
from vantage.sprites import damage_graphics, sprite_deltas


def _fid(model: str, name: str) -> int:
    return SCHEMA.fid(SCHEMA.model_id(model), name)


# -- field ids, resolved once -------------------------------------------------

ROOT_WORLD = _fid("Root", "world")
ROOT_OPTIONS = _fid("Root", "gameOptions")
W_TIME = _fid("World", "time")
W_ENTITIES = _fid("World", "entities")
W_PLAYERS = _fid("World", "players")
W_TECHS = _fid("World", "technologies")
W_MAP_W = _fid("World", "mapWidth")
W_MAP_H = _fid("World", "mapHeight")
W_TILES = _fid("World", "mapTiles")
W_TERRAINS = _fid("World", "terrainTypes")
W_VISIBLE = _fid("World", "unifiedVisibleMap")
W_GAME_ENDED = _fid("World", "gameEnded")
W_PRICES = (_fid("World", "foodPrice"), _fid("World", "woodPrice"), _fid("World", "stonePrice"))
W_COUNTDOWN = _fid("World", "countdownClock")
W_COUNTDOWN_VICTORY = _fid("World", "countdownVictory")
W_RELIC_COUNTDOWN = _fid("World", "relicCountdownGoingOn")
W_VICTORY_TYPE = _fid("World", "victoryType")

P_ID = _fid("Player", "id")
P_NAME = _fid("Player", "name")
P_ATTR = _fid("Player", "attributes")
P_RESEARCH = _fid("Player", "researchStates")
P_MASTERS = _fid("Player", "masterEntities")
P_CIV = _fid("Player", "civId")
#: The lobby colour (0 blue, 1 red, 2 green, 3 yellow, 4 teal, 5 purple, 6 grey,
#: 7 orange). ``colorIdCurrent`` is the recorder's ally/enemy colour mode
#: (every enemy reads as red), so it is not the player's colour.
P_COLOR = _fid("Player", "colorIdChosen")
P_STATUS = _fid("Player", "gameStatus")
P_RESIGNED = _fid("Player", "resigned")
P_DROPPED = _fid("Player", "dropped")
P_RELATIONS = _fid("Player", "relations")
P_TRADE_GOLD = _fid("Player", "tradeGoldReceived")
P_FARM_QUEUE = _fid("Player", "farmQueueCount")
P_VP = _fid("Player", "victoryPoints")
P_VP_MAP = _fid("Player", "victoryPointMap")
VP_GROUP = _fid("VictoryPointEntry", "group")
VP_POINTS = _fid("VictoryPointEntry", "currPoints")
W_TREATY = _fid("World", "treatyMode")
TM_LEFT = _fid("TreatyMode", "timeLeftInSeconds")
TM_TOTAL = _fid("TreatyMode", "treatyTimeInSeconds")

E_ID = _fid("Entity", "id")
E_MASTER = _fid("Entity", "masterId")
E_OWNER = _fid("Entity", "ownerId")
E_X = _fid("Entity", "worldX")
E_Y = _fid("Entity", "worldY")
E_HELD_AMT = _fid("Entity", "heldAttributeAmount")
E_HELD_TYPE = _fid("Entity", "heldAttributeType")
E_STATE = _fid("Entity", "state")
E_DOPPLE = _fid("Entity", "doppleFlag")
E_HP = _fid("Entity", "hp")
E_SPRITE = _fid("Entity", "spriteId")
E_FACET = _fid("Entity", "facet")
E_SPRITES = _fid("Entity", "spriteList")
AS_SPRITE = _fid("ActiveSprite", "spriteId")
AS_OX = _fid("ActiveSprite", "offsetX")
AS_OY = _fid("ActiveSprite", "offsetY")
AS_FRAME = _fid("ActiveSprite", "frame")
AS_ORDER = _fid("ActiveSprite", "order")
SP_NAME = _fid("Sprite", "pictName")
SP_FRAMES = _fid("Sprite", "frameNum")
SP_FACETS = _fid("Sprite", "facetNum")
SP_DURATION = _fid("Sprite", "duration")
W_SPRITES = _fid("World", "sprites")
E_OWN_MASTER = _fid("Entity", "ownMaster")
E_INSIDE = _fid("Entity", "insideObjId")
E_ACTION = _fid("ActionEntity", "currentAction")
B_QUEUE_ACTION = _fid("BuildingEntity", "currentProductionQueueAction")
B_QUEUE = _fid("BuildingEntity", "productionQueue")
B_BUILT = _fid("BuildingEntity", "built")
B_BUILD_PTS = _fid("BuildingEntity", "buildPts")
B_RELICS = _fid("BuildingEntity", "relicCount")
B_GARRISON_ID = _fid("BuildingEntity", "linkedOwnerId")

M_TYPE = _fid("MasterEntity", "type")
M_STRING = _fid("MasterEntity", "stringId")
M_CLASS = _fid("MasterEntity", "objectGroup")
M_HP = _fid("MasterEntity", "hp")
M_ICON = _fid("MasterEntity", "buttonPict")
M_RADIUS_X = _fid("MasterEntity", "radiusX")
M_BUILD_TIME = _fid("MasterCombatEntity", "buildPtsRequired")
M_COST = _fid("MasterCombatEntity", "buildInventory")
M_RANGE = _fid("MasterCombatEntity", "weaponRange")
M_SPEED = _fid("MasterCombatEntity", "speed")
M_ARMOR = _fid("MasterCombatEntity", "armor")
M_WEAPON = _fid("MasterCombatEntity", "weapon")
M_RELOAD = _fid("MasterCombatEntity", "speedOfAttack")
M_MAP_COLOR = _fid("MasterEntity", "mapColor")
M_SPRITE = _fid("MasterEntity", "spriteId")
MODEL_MASTER_MISSILE = SCHEMA.model_id("MasterMissileEntity")
MM_TRAIL = _fid("MasterMissileEntity", "objTrailId")
MM_TRAIL_SPACING = _fid("MasterMissileEntity", "objTrailSpacing")
SP_EFFECT = _fid("Sprite", "particleEffectName")
M_CAPACITY = _fid("MasterEntity", "objCapacity")
M_WORK_RATE = _fid("MasterCombatEntity", "workRate")
M_MIN_RANGE = _fid("MasterCombatEntity", "minimumWeaponRange")
M_ACCURACY = _fid("MasterCombatEntity", "baseHitChance")
M_VOLLEY = _fid("MasterCombatEntity", "volleyFireAmount")
M_MAX_VOLLEY = _fid("MasterCombatEntity", "maxAttacksInVolley")
M_BLAST_WIDTH = _fid("MasterCombatEntity", "areaEffectRange")
M_BLAST_LEVEL = _fid("MasterCombatEntity", "areaEffectLevel")
M_BLAST_DAMAGE = _fid("MasterCombatEntity", "areaDamage")
M_MAX_CHARGE = _fid("MasterCombatEntity", "maxCharge")
M_RECHARGE = _fid("MasterCombatEntity", "rechargeRate")
M_CHARGE_TYPE = _fid("MasterCombatEntity", "chargeType")
M_REGEN = _fid("MasterCombatEntity", "regenerationRate")
M_TASKS = _fid("MasterActionEntity", "tasks")
M_HELD = _fid("MasterEntity", "attributesHeld")
AV_TYPE = _fid("AttributeValue", "type")
AV_AMOUNT = _fid("AttributeValue", "amount")
TASK_ACTION = _fid("Task", "actionType")
TASK_RANGE = _fid("Task", "workRange")
#: ``Task.actionType`` of an aura (e.g. a Centurion's or a Khan's buff).
AURA_ACTION = 155
E_CHARGE = _fid("CombatEntity", "charge")
B_GATE_LOCKED = _fid("BuildingEntity", "gateLocked")

AV_TYPE = _fid("AttributeValue", "type")
AV_AMOUNT = _fid("AttributeValue", "amount")

T_NAME = _fid("Technology", "name")
T_STRING = _fid("Technology", "stringId")
T_HELP = _fid("Technology", "stringId2")
T_ICON = _fid("Technology", "icon")
T_TIME = _fid("Technology", "timeToResearch")
T_COST = _fid("Technology", "cost")
T_BUILDING = _fid("Technology", "buildObjId")

R_PROGRESS = _fid("ResearchState", "researchDone")
R_STATE = _fid("ResearchState", "state")
R_BUILDING = _fid("ResearchState", "buildObjId")
R_ADJUST = _fid("ResearchState", "researchAdjustment")

A_TYPE = _fid("Action", "type")
A_STATE = _fid("Action", "state")
A_TARGET = _fid("Action", "targetId")
MO_OBJ = _fid("MakeObjectAction", "objId")
MO_WORK = _fid("MakeObjectAction", "workDone")
MT_TECH = _fid("MakeTechAction", "techId")
MT_PROGRESS = _fid("MakeTechAction", "researchProgress")
Q_UNIT = _fid("ProductionQueueRecord", "unitId")
Q_TECH = _fid("ProductionQueueRecord", "techId")
Q_COUNT = _fid("ProductionQueueRecord", "unitCount")

TILE_TERRAIN = _fid("MapTile", "terrainType")
TILE_ELEV = _fid("MapTile", "elevLevel")
TILE_LAYER = _fid("MapTile", "layerType")
TILE_SHAPE = _fid("MapTile", "shape")
E_Z = _fid("Entity", "worldZ")
TT_MASK = _fid("TerrainType", "overlayMaskName")
TT_COLOR = _fid("TerrainType", "mapFlatColor")
TT_NAME = _fid("TerrainType", "name")
TT_PICT = _fid("TerrainType", "pictName")
TT_ROWS = _fid("TerrainType", "rows")

GO_PLAYERS = _fid("GameOptions", "playerInfo")
GO_MAP = _fid("GameOptions", "resolvedMapType")
GO_MAP_FILE = _fid("GameOptions", "customRandomMapFile")
GO_POP = _fid("GameOptions", "populationLimit")
GO_RANKED = _fid("GameOptions", "isRanked")
GO_SPEED = _fid("GameOptions", "gameSpeed")
GO_SEED = _fid("GameOptions", "randomMapSeed")
GO_GAME_ID = _fid("GameOptions", "gameId")
GO_GAME_MODE = _fid("GameOptions", "gameMode")
GO_SPEC_DELAY = _fid("GameOptions", "spectatorDelay")
GO_VICTORY = _fid("GameOptions", "victoryType")
GO_TREATY = _fid("GameOptions", "treatyLength")
GO_BR_MINUTES = _fid("GameOptions", "battleRoyaleLengthMinutes")
#: ``GameOptions.gameMode`` (the lobby's game-mode list). 0 is confirmed on
#: captured random-map games (absent = 0) and 3 matches the replay header's
#: scenario id; the rest follow the lobby order and are unverified.
GAME_MODES = {
    0: "Random Map",
    1: "Regicide",
    2: "Death Match",
    3: "Scenario",
    5: "King of the Hill",
    6: "Wonder Race",
    7: "Defend the Wonder",
    8: "Turbo Random Map",
    9: "Capture the Relic",
    10: "Sudden Death",
    11: "Battle Royale",
    12: "Empire Wars",
}
PGO_TEAM = _fid("PlayerGameOptions", "resolvedTeamId")
PGO_HUMAN = _fid("PlayerGameOptions", "humanPlayerName")
PGO_AI = _fid("PlayerGameOptions", "aiScriptBaseName")
PGO_AI_NAME = _fid("PlayerGameOptions", "aiPlayerName")
PGO_ELO_RM = _fid("PlayerGameOptions", "playerRmElo")
PGO_ELO_DM = _fid("PlayerGameOptions", "playerDmElo")
PGO_INDEX = _fid("PlayerGameOptions", "worldPlayerIndexIncludingGaia")
PGO_HANDICAP = _fid("PlayerGameOptions", "handicap")

_ATTR = {s.name: s.fid for s in SCHEMA.fields(SCHEMA.model_id("PlayerAttributes")).values()}

# -- model ids ----------------------------------------------------------------

MODEL_BUILDING = SCHEMA.model_id("BuildingEntity")
MODEL_DOPPLE = SCHEMA.model_id("DoppleEntity")
MODEL_MAKE_OBJECT = SCHEMA.model_id("MakeObjectAction")
MODEL_MAKE_TECH = SCHEMA.model_id("MakeTechAction")

# -- game facts -----------------------------------------------------------------

ENTITY_ALIVE = 2
ENTITY_RESOURCE = 3  # gatherable remains: mines, bushes, carcasses (Gaia)
ENTITY_DYING = 4  # playing its death animation
ENTITY_DECAYING = 5  # a corpse fading out (``*_decayA`` sprites)
#: Row flag of :func:`remains_rows`: death, decay and destruction animations play
#: once and hold their last frame (the game does not loop them).
FLAG_REMAINS = 256
#: Flares a player places (state 3 like rubble, but not drawn on the map).
FLARE_MASTERS = frozenset({112, 274})
RESEARCH_DONE = 3
RESEARCH_ACTIVE = 2

TYPE_COMBAT = 70
TYPE_BUILDING = 80

# Unit class ids (``MasterEntity.objectGroup``).
CLASS_CIVILIAN = 4
CLASS_BUILDING = 3
CLASS_WALL = 27
CLASS_GATE = 39
CLASS_TOWER = 52
CLASS_TRADE_BOAT = 2
CLASS_TRADE_CART = 19
CLASS_FISHING_BOAT = 21
CLASS_RELIC = 42  # master 285 "Relic" (DE data)
#: Relics by class: DE's 42, and 1 (the older numbering this code first assumed).
RELIC_CLASSES = frozenset({CLASS_RELIC, 1})
CLASS_KING = 59
CLASS_LIVESTOCK = 58
CLASS_MONK_RELIC = 43
#: Livestock and domestic animals: Gaia's keep their last owner in the panel.
LIVESTOCK_CLASSES = frozenset({58, 29})
#: The regicide King's master id (also recognised by its class, CLASS_KING).
KING_MASTERS = frozenset({434})
#: The King of the Hill monument (master id, plus a name fallback in
#: :func:`is_monument` for data versions that renumber it).
MONUMENT_MASTERS = frozenset({826})
#: Bridge pieces are Gaia buildings; ids 602-617 plus a name fallback.
BRIDGE_MASTERS = frozenset(range(602, 618))
_NON_MILITARY_CLASSES = frozenset(
    {
        CLASS_KING,  # a regicide King is not army (no military count or value)
        CLASS_CIVILIAN,
        CLASS_BUILDING,
        CLASS_WALL,
        CLASS_GATE,
        CLASS_TOWER,
        CLASS_TRADE_BOAT,
        CLASS_TRADE_CART,
        CLASS_FISHING_BOAT,
        *RELIC_CLASSES,
        CLASS_LIVESTOCK,
        5,
        7,
        8,
        9,
        10,
        11,
        14,
        15,
        29,
        30,
        31,
        32,
        33,
        34,
        37,
        38,
        40,
        41,
        48,
        49,
        60,
        61,
    }
)
_ECO_CLASSES = frozenset({CLASS_CIVILIAN, CLASS_FISHING_BOAT, CLASS_TRADE_CART, CLASS_TRADE_BOAT})
ECO_CLASSES = _ECO_CLASSES
#: Gaia objects drawn as map rows (resources, relics, animals).
#: Cliffs (scenery: drawn in depth order with everything else, never picked or
#: counted; row flag :data:`FLAG_SCENERY`).
CLASS_CLIFF = 34
FLAG_SCENERY = 512
_GAIA_ROW_CLASSES = frozenset(
    {5, 7, 8, 32, 33, 9, 10, 31, 48, *RELIC_CLASSES, 29, CLASS_LIVESTOCK, CLASS_CLIFF}
)

# Villager master ids by task (male/female pairs).
TASK_BY_MASTER: dict[int, str] = {}
for _task, _ids in {
    "food": (120, 354, 122, 216, 214, 259, 56, 57, 590, 592),
    "wood": (123, 218),
    "gold": (579, 581),
    "stone": (124, 220),
    "build": (118, 212),
    "repair": (156, 222),
}.items():
    for _i in _ids:
        TASK_BY_MASTER[_i] = _task
#: Name-based fallback for task-specific villager masters not in the table above
#: (newer civs add variants, e.g. Khitan herders).
_TASK_WORDS = (
    ("forager", "food", "berries"),
    ("hunter", "food", "hunt"),
    ("farmer", "food", "farm"),
    ("fisher", "food", "fish"),
    ("shepherd", "food", "sheep"),
    ("herder", "food", "sheep"),
    ("lumberjack", "wood", None),
    ("woodcutter", "wood", None),  # Return of Rome
    ("gold miner", "gold", None),
    ("stone miner", "stone", None),
    ("builder", "build", None),
    ("repairer", "repair", None),
)


def villager_task(mid: int, name: str) -> tuple[str | None, str | None]:
    """(task, food subtask) for a villager master id."""
    task = TASK_BY_MASTER.get(mid)
    if task is not None:
        return task, FOOD_SUBTASK.get(mid) if task == "food" else None
    low = name.lower()
    for word, t, sub in _TASK_WORDS:
        if word in low:
            return t, sub
    return None, None


FOOD_SUBTASK = {
    120: "berries",
    354: "berries",
    122: "hunt",
    216: "hunt",
    214: "farm",
    259: "farm",
    56: "fish",
    57: "fish",
    590: "sheep",
    592: "sheep",
}
#: Town centre masters. 618-620 are the annex parts a TC is built from; they are
#: drawn but must not count as extra town centres.
TOWN_CENTER_MASTERS = frozenset({109, 71, 141, 142, 444})
TOWN_CENTER_PARTS = frozenset({618, 619, 620})
CASTLE_MASTERS = frozenset({82, 1251})  # castle, krepost
AGE_TECHS = {101: 1, 102: 2, 103: 3}  # Feudal, Castle, Imperial research ids -> target era

RESOURCE_NAMES = ("food", "wood", "stone", "gold")

# -- activity ----------------------------------------------------------------------
# What a unit or building is doing, as a small code carried on each entity row.
ACT_IDLE = 0
ACT_MOVING = 1
ACT_GATHER = {"food": 2, "wood": 3, "gold": 4, "stone": 5}
ACT_BUILDING = 6
ACT_REPAIRING = 7
ACT_FIGHTING = 8
ACT_GARRISONED = 9
ACT_PRODUCING = 10
ACT_RESEARCHING = 11
ACT_OTHER = 12
ACT_PACKING = 13  # trebuchets and other packed siege (PackAction)
ACT_UNPACKING = 14  # (UnpackAction)
ACT_HEALING = 15
ACT_HOUSED = 16
ACT_POP_LIMIT = 17
ACTIVITY_NAMES = (
    "idle",
    "moving",
    "gather_food",
    "gather_wood",
    "gather_gold",
    "gather_stone",
    "building",
    "repairing",
    "fighting",
    "garrisoned",
    "producing",
    "researching",
    "other",
    "packing",
    "unpacking",
    "healing",
    "housed",
    "population_limit",
)
_PACK_MODEL = SCHEMA.model_id("PackAction")
_UNPACK_MODEL = SCHEMA.model_id("UnpackAction")
#: Action types (``Action.type``) by meaning; observed in captured games.
_MOVE_ACTIONS = frozenset({1, 3, 4, 12, 13, 14})
_GATHER_ACTIONS = frozenset({5, 110, 111, 6})
_ATTACK_ACTIONS = frozenset({7, 9, 104})
_BUILD_ACTION = 101
_REPAIR_ACTION = 106
#: Gather/hunt action state while actually working (other states are walking
#: to the resource or back to a drop site).
_WORKING_STATE = 7


def unit_activity(e: Node, task: str | None, garrisoned: bool) -> int:
    if garrisoned:
        return ACT_GARRISONED
    act = _action_node(e, E_ACTION)
    if act is None:
        return ACT_IDLE
    if act.model == _PACK_MODEL:
        return ACT_PACKING
    if act.model == _UNPACK_MODEL:
        return ACT_UNPACKING
    atype = int(act.fields.get(A_TYPE, 0) or 0)
    if atype == 105:
        return ACT_HEALING if act.fields.get(A_STATE) == _WORKING_STATE else ACT_MOVING
    if atype == _BUILD_ACTION:
        return ACT_BUILDING
    if atype == _REPAIR_ACTION:
        return ACT_REPAIRING
    if atype in _GATHER_ACTIONS:
        if int(act.fields.get(A_STATE, 0) or 0) != _WORKING_STATE:
            return ACT_MOVING
        return ACT_GATHER.get(task or "", ACT_GATHER["food"])
    if atype in _ATTACK_ACTIONS:
        return ACT_FIGHTING
    if atype in _MOVE_ACTIONS:
        return ACT_MOVING
    return ACT_OTHER


@dataclass(slots=True)
class MasterInfo:
    """What the UI needs to label one unit/building type."""

    id: int
    name: str
    icon: int
    cls: int
    type: int
    hp: int
    kind: str  # unit | building | other
    cost: dict[str, float] = field(default_factory=dict)
    train_time: float = 0.0
    stats: dict[str, float] = field(default_factory=dict)
    size: float = 1.0  # footprint edge in tiles
    string_id: int = -1
    #: Wwise event ids: created / death / selected / damage (0 = none).
    sounds: dict[str, int] = field(default_factory=dict)
    sprite: int = -1  # standing sprite id
    #: Building damage graphics (:func:`vantage.sprites.damage_graphics`).
    damage_sprites: list[dict[str, Any]] = field(default_factory=list)
    garrison_capacity: int = 0
    #: Building masters that train this unit (``idOfBuildingObj`` + ``trainLocationIds``).
    train_locations: list[int] = field(default_factory=list)
    #: Aura description string ids (combatAbility & 32 masters).
    aura_ids: list[int] = field(default_factory=list)
    #: A projectile's trail: {"particle": effect name, "spacing": tiles}. The game
    #: drops a trail object every ``spacing`` tiles of flight and draws it itself
    #: (it is never streamed), so the view draws the trail from the flight path.
    trail: dict[str, Any] | None = None
    #: What a resource object holds when untouched: ``[resource, amount]`` (a gold
    #: mine's 800 gold, a tree's 100 wood), from the master's first ``attributesHeld``.
    storage: list[Any] | None = None


def master_storage(f: dict[int, Any]) -> list[Any] | None:
    """``[resource, amount]`` a fresh object of this master holds, or None.

    The first ``attributesHeld`` entry is the resource store (type absent = food,
    as everywhere zero values are omitted); villagers list attribute 4 first."""
    held = f.get(M_HELD)
    first = held[0] if isinstance(held, list) and held else None
    if not isinstance(first, Node):
        return None
    ht = int(first.fields.get(AV_TYPE, 0) or 0)
    amount = float(first.fields.get(AV_AMOUNT, 0.0) or 0.0)
    if not 0 <= ht < 4 or amount <= 0:
        return None
    return [RESOURCE_NAMES[ht], round(amount, 1)]


#: Armour/attack class ``c`` is named by the game string ``ARMOR_CLASS_STRING + c``.
ARMOR_CLASS_STRING = 12400
#: Armour/attack class ids for the two headline numbers (game data facts).
ARMOR_MELEE = 4
ARMOR_PIERCE = 3


def _class_values(items: Any) -> dict[int, int]:
    out: dict[int, int] = {}
    for it in items or ():
        if isinstance(it, Node):
            out[int(it.fields.get(0, 0) or 0)] = int(it.fields.get(1, 0) or 0)
    return out


_SE_ID = _fid("SoundEvent", "eventId")
_SOUND_FIELDS = (
    ("created", _fid("MasterEntity", "createdSoundEvent")),
    ("death", _fid("MasterEntity", "deathSoundEvent")),
    ("selected", _fid("MasterEntity", "selectedSoundEvent")),
    ("damage", _fid("MasterEntity", "damageSoundEvent")),
)


def _sound_events(f: dict[int, Any]) -> dict[str, int]:
    out: dict[str, int] = {}
    for key, fid in _SOUND_FIELDS:
        se = f.get(fid)
        if isinstance(se, Node) and se.fields.get(_SE_ID):
            out[key] = int(se.fields[_SE_ID])
    return out


def _unit_stats(f: dict[int, Any], mid: int | None = None) -> dict[str, float]:
    weapon = _class_values(f.get(M_WEAPON))
    armor = _class_values(f.get(M_ARMOR))
    stats: dict[str, float] = {}
    attack = max(weapon.get(ARMOR_MELEE, 0), weapon.get(ARMOR_PIERCE, 0))
    if attack:
        stats["attack"] = attack
    if armor:
        stats["melee_armor"] = armor.get(ARMOR_MELEE, 0)
        stats["pierce_armor"] = armor.get(ARMOR_PIERCE, 0)
    for key, fid in (
        ("range", M_RANGE),
        ("min_range", M_MIN_RANGE),
        ("speed", M_SPEED),
        ("reload", M_RELOAD),
    ):
        v = f.get(fid)
        if v:
            stats[key] = round(float(v) * (speed_factor(mid) if fid == M_SPEED else 1.0), 2)
    aura, work = task_ranges(f)
    if aura:
        stats["aura_range"] = aura
    if work:
        stats["work_range"] = work
    return stats


def task_ranges(f: dict[int, Any]) -> tuple[float, float]:
    """(aura range, work range): the largest ``Task.workRange`` of the master's
    aura tasks (action type :data:`AURA_ACTION`) and of its other tasks."""
    aura = work = 0.0
    for task in f.get(M_TASKS) or ():
        if not isinstance(task, Node):
            continue
        rng = float(task.fields.get(TASK_RANGE, 0.0) or 0.0)
        if int(task.fields.get(TASK_ACTION, 0) or 0) == AURA_ACTION:
            aura = max(aura, rng)
        else:
            work = max(work, rng)
    return round(aura, 2), round(work, 2)


def master_cost(f: dict[int, Any]) -> dict[str, float]:
    """A master's cost (``buildInventory``) as ``{resource: amount}``."""
    cost: dict[str, float] = {}
    for av in f.get(M_COST) or ():
        if isinstance(av, Node):
            t = int(av.fields.get(AV_TYPE, 0) or 0)  # absent type = food (zero omitted)
            amt = float(av.fields.get(AV_AMOUNT, 0.0) or 0.0)
            if 0 <= t < 4 and amt > 0:
                cost[RESOURCE_NAMES[t]] = amt
    return cost


# -- unit panel: base vs current stats and per-entity modifiers --------------------
# Field ids are checked against ``cade_schema.json``.

M_ORIG_ARMOR = _fid("MasterCombatEntity", "origArmor")
M_ORIG_PIERCE = _fid("MasterCombatEntity", "origPierceArmor")
M_ORIG_WEAPON = _fid("MasterCombatEntity", "origWeapon")
M_ORIG_RANGE = _fid("MasterCombatEntity", "origWeaponRange")
M_ORIG_RELOAD = _fid("MasterCombatEntity", "origSpeedOfAttack")
M_ABILITY = _fid("MasterCombatEntity", "combatAbility")
M_CHARGE_EVENT = _fid("MasterCombatEntity", "chargeEvent")
M_CHARGE_TARGET = _fid("MasterCombatEntity", "chargeTarget")
M_CHARGE_PROJECTILE = _fid("MasterCombatEntity", "chargeProjectileUnit")
M_TRAIN_LOCATIONS = _fid("MasterCombatEntity", "trainLocationIds")
M_BUILDING_OBJ = _fid("MasterCombatEntity", "idOfBuildingObj")

TASK_OBJECT_GROUP = _fid("Task", "objectGroup")
TASK_OBJECT_ID = _fid("Task", "objectId")
TASK_HOLDING = _fid("Task", "holdingAttr")
TASK_ATTR = _fid("Task", "attributeType")
TASK_ATTR2 = _fid("Task", "attributeType2")
TASK_ATTR3 = _fid("Task", "attributeType3")
TASK_VAL1 = _fid("Task", "workVal1")
TASK_VAL2 = _fid("Task", "workVal2")
TASK_WAIT = _fid("Task", "searchWaitTime")
TASK_FLAG = _fid("Task", "workFlag")
TASK_FLAG2 = _fid("Task", "workFlag2")
TASK_DEPOSIT_SOUND = _fid("Task", "depositSoundEvent")

_CE = {
    name: _fid("CombatEntity", name)
    for name in (
        "meleeArmorRemoved",
        "pierceArmorRemoved",
        "attackPowerUp",
        "speedPowerUp",
        "reloadPowerUp",
        "regenerationRatePowerUp",
        "hitpointsMaxPowerUp",
        "meleeArmorPowerUp",
        "pierceArmorPowerUp",
        "numUnitsPoweredUpBy",
        "maxRangePowerup",
        "isCharging",
        "speedStinger",
        "regenerationStinger",
        "reloadStinger",
        "hitpointsMaxStinger",
        "attackStinger",
        "meleeArmorStinger",
        "pierceArmorStinger",
    )
}
E_TRANSIENT_TYPE = _fid("Entity", "transientHeldAttributeType")
E_TRANSIENT_AMT = _fid("Entity", "transientHeldAttributeAmount")
#: Entity fields whose presence means the unit may differ from its master.
_MOD_FIDS = frozenset(_CE.values())

#: ``Task.actionType`` values the unit panel reads.
ACTION_CHARGE_SPEED = 133
ACTION_KILL_STACK = 154
ACTION_DOT = 157
ACTION_HP_LOSS = 160
ACTION_CARRY_BONUS = 164
#: ``Task.searchWaitTime`` that marks a damage-over-time task.
DOT_WAIT = 109
#: ``MasterEntity.combatAbility`` bit of the aura (bicep) indicator.
ABILITY_AURA = 32
CLASS_HEROES = 36  # armour class of heroes and kings
CLASS_GARRISON_HIDDEN = 12  # objectGroup whose garrison count is not shown
CLASS_BUILDING_ARMOR = 31  # shown only when class 4 is absent
REGEN_HERO = 30.0
#: Masters that keep their own regeneration despite carrying armour class 36.
REGEN_EXEMPT = frozenset({299, 434, 923, 1292, 2329, 2330, 2708, 2709})
#: ``chargeTarget`` bit -> the object groups it covers.
CHARGE_TARGET_BITS = {
    1: (6,),
    2: (12, 47),
    4: (0, 44),
    8: (36, 23),
    16: (18, 43),
    32: (4, 19, 59),
    64: (21, 20, 22, 2, 53),
    128: (13, 51, 54, 55, 35),
    256: (3, 27, 39, 49, 52, 60),
}
#: Carried resources: types 0-3 and the food variants 15-17 (34 is ignored).
_HELD_RESOURCE = {0: "food", 1: "wood", 2: "stone", 3: "gold", 15: "food", 16: "food", 17: "food"}
#: Civ carry bonuses (task 164): civ id -> {Task.attributeType2: (value, tech id
#: that must be researched or None)}.
CARRY_BONUS: dict[int, dict[int, tuple[float, int | None]]] = {
    24: {267: (33.3333, None)},
    26: {276: (10.0, None)},
    31: {266: (1.5, 629)},
    36: {236: (2.0, 754)},
    38: {241: (33.3333, None)},
    47: {502: (15.0, None)},
    48: {521: (2.25, 1133)},
    49: {502: (7.0, None)},
    51: {287: (3.0, 1061)},
    55: {563: (1.0, None)},
    56: {512: (1.0, None)},
    58: {215: (25.0, None)},
    61: {298: (10.01, None)},
    62: {299: (5.01, None)},
}


def _tasks(f: dict[int, Any]) -> list[dict[int, Any]]:
    return [t.fields for t in f.get(M_TASKS) or () if isinstance(t, Node)]


def _n(v: Any) -> float:
    return float(v or 0)


def _tidy(v: float) -> int | float:
    """An int when whole, else rounded to two places (JSON-friendly)."""
    r = round(v, 2)
    return int(r) if r == int(r) else r


@dataclass(slots=True)
class MasterRules:
    """The task-derived unit-panel rules of one master node."""

    dot: int = 0
    #: (bonus per step, step size, applies to the unit's own hp) of task 160
    hp_loss: tuple[float, float, bool] | None = None
    #: ``{stat: 'hp'|'attack', groups: [...], increment, cap}`` of task 154
    kill_stack: list[dict[str, Any]] = field(default_factory=list)
    charge_speed: float = 1.0
    #: aura description string ids (``combatAbility`` & 32 masters only)
    aura_ids: list[int] = field(default_factory=list)
    #: task 164 rows: (attributeType, attributeType2, attributeType3, workVal1)
    carry: list[tuple[int, int, int, float]] = field(default_factory=list)


def master_rules(f: dict[int, Any]) -> MasterRules:
    """DoT, HP-loss and kill-stack bonuses, charge speed, aura and carry tasks."""
    rules = MasterRules()
    stacks: dict[tuple[Any, ...], dict[str, Any]] = {}
    seen_aura: set[int] = set()
    for t in _tasks(f):
        action = int(t.get(TASK_ACTION, 0) or 0)
        v1, v2 = _n(t.get(TASK_VAL1)), _n(t.get(TASK_VAL2))
        wait = _n(t.get(TASK_WAIT))
        if action == ACTION_DOT and not rules.dot:
            if wait == DOT_WAIT and v1 < 0 and v2 > 0:
                rules.dot = int(abs(v1) * v2 / 60)
        elif action == ACTION_HP_LOSS and rules.hp_loss is None:
            rules.hp_loss = (v1, v2, _n(t.get(TASK_RANGE)) == 0)
        elif action == ACTION_CHARGE_SPEED and rules.charge_speed == 1.0:
            rules.charge_speed = _n(t.get(TASK_RANGE)) or 1.0
        elif action == ACTION_KILL_STACK:
            flag, cap = _n(t.get(TASK_FLAG)), _n(t.get(TASK_FLAG2))
            if flag > 0 and cap > 0 and v1 == 0 and wait in (0.0, 9.0):
                key = (t.get(TASK_HOLDING), wait, flag, cap)
                s = stacks.setdefault(
                    key,
                    {
                        "stat": "hp" if wait == 0 else "attack",
                        "groups": [],
                        "increment": _tidy(flag),
                        "cap": int(cap),
                    },
                )
                grp = int(t.get(TASK_OBJECT_GROUP, 0) or 0)
                if grp not in s["groups"]:
                    s["groups"].append(grp)
        elif action == ACTION_CARRY_BONUS:
            rules.carry.append(
                (
                    int(t.get(TASK_ATTR, 0) or 0),
                    int(t.get(TASK_ATTR2, 0) or 0),
                    int(t.get(TASK_ATTR3, 0) or 0),
                    v1,
                )
            )
        elif action == AURA_ACTION and (
            int(t.get(TASK_OBJECT_ID, -1) if t.get(TASK_OBJECT_ID) is not None else -1) > 0
            or int(t.get(TASK_OBJECT_GROUP, 0) or 0) >= 0
        ):
            se = t.get(TASK_DEPOSIT_SOUND)
            sid = int(se.fields.get(_SE_ID, 0) or 0) if isinstance(se, Node) else 0
            if sid > 0 and sid not in seen_aura:
                seen_aura.add(sid)
                rules.aura_ids.append(sid)
    rules.kill_stack = list(stacks.values())
    if not int(f.get(M_ABILITY, 0) or 0) & ABILITY_AURA:
        rules.aura_ids = []
    return rules


def kill_stack_bonus(rules: list[dict[str, Any]], victim_groups: Iterable[int]) -> dict[str, int]:
    """``{"hp": n, "attack": n}`` bonus of a unit's kill stacking after killing
    units of ``victim_groups`` (their ``objectGroup`` ids, one per kill):
    ``max(0, min(kills, cap) - 1) * increment`` per rule."""
    groups = list(victim_groups)
    out = {"hp": 0, "attack": 0}
    for rule in rules:
        wanted = set(rule["groups"])
        kills = sum(1 for g in groups if g in wanted)
        n = max(0, min(kills, int(rule["cap"])) - 1)
        out[str(rule["stat"])] += int(n * float(rule["increment"]))
    return out


def weapon_rows(f: dict[int, Any]) -> list[list[Any]]:
    """``[class, base, current]`` per attack class in the game's order. The base
    is the master's ``origWeapon`` for class 3 / 31 (and for class 4 when its
    melee value beats the pierce value), else the value itself."""
    rows = _class_pairs(f.get(M_WEAPON))
    vals = dict(rows)
    orig = int(f.get(M_ORIG_WEAPON, 0) or 0)
    melee_wins = vals.get(ARMOR_MELEE, 0) > vals.get(ARMOR_PIERCE, 0)
    uses_orig = (ARMOR_PIERCE, CLASS_BUILDING_ARMOR)
    return [
        [c, orig if c in uses_orig or (c == ARMOR_MELEE and melee_wins) else v, v] for c, v in rows
    ]


def armor_table(f: dict[int, Any]) -> list[list[Any]]:
    """``[class, base, current]`` per armour class in the game's order; the base
    of classes 4 and 3 is ``origArmor`` / ``origPierceArmor`` when the master
    lists the class."""
    out: list[list[Any]] = []
    for c, v in _class_pairs(f.get(M_ARMOR)):
        base = v
        if c == ARMOR_MELEE:
            base = int(f.get(M_ORIG_ARMOR, 0) or 0)
        elif c == ARMOR_PIERCE:
            base = int(f.get(M_ORIG_PIERCE, 0) or 0)
        out.append([c, base, v])
    return out


def _class_pairs(items: Any) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    for it in items or ():
        if isinstance(it, Node):
            out.append((int(it.fields.get(0, 0) or 0), int(it.fields.get(1, 0) or 0)))
    return out


def attack_rows(f: dict[int, Any]) -> list[list[Any]]:
    """Attack rows for the panel: the game's order, class 31 hidden when class 4
    is present, rows that are 0 both base and current dropped."""
    rows = weapon_rows(f)
    has4 = any(r[0] == ARMOR_MELEE for r in rows)
    return [r for r in rows if (r[1] or r[2]) and not (r[0] == CLASS_BUILDING_ARMOR and has4)]


def armor_rows(f: dict[int, Any]) -> list[list[Any]]:
    """Armour rows: the game's order; classes 4 and 3 are always present (added
    first with 0 when missing), other all-zero rows are dropped."""
    rows = armor_table(f)
    have = {r[0] for r in rows}
    head = [[c, 0, 0] for c in (ARMOR_MELEE, ARMOR_PIERCE) if c not in have]
    return head + [r for r in rows if r[1] or r[2] or r[0] in (ARMOR_MELEE, ARMOR_PIERCE)]


#: Masters whose displayed speed is multiplied by 1.2.
SPEED_BOOST_MASTERS = frozenset({48, 936, 1139, 1140, 1301})
SPEED_BOOST = 1.2


def speed_factor(mid: int | None) -> float:
    return SPEED_BOOST if mid in SPEED_BOOST_MASTERS else 1.0


def regen_is_flat(f: dict[int, Any], mid: int | None = None) -> bool:
    """Armour class 36 masters (heroes, kings) show a flat 30 regeneration,
    except the :data:`REGEN_EXEMPT` masters."""
    return any(c == CLASS_HEROES for c, _ in _class_pairs(f.get(M_ARMOR))) and (
        mid is None or mid not in REGEN_EXEMPT
    )


def regen_display(f: dict[int, Any], mid: int | None = None) -> float:
    """What the panel shows as regeneration: heroes and kings (armour class 36)
    always read 30 except the :data:`REGEN_EXEMPT` masters."""
    if regen_is_flat(f, mid):
        return REGEN_HERO
    return _num(f, M_REGEN)


def charge_info(f: dict[int, Any]) -> dict[str, Any]:
    """The master's charge rules (see ``master_detail``'s ``charge``)."""
    ctype = int(f.get(M_CHARGE_TYPE, 0) or 0)
    mx = _n(f.get(M_MAX_CHARGE))
    rate = _n(f.get(M_RECHARGE))
    event = int(f.get(M_CHARGE_EVENT, 0) or 0)
    instant = rate > 0 and mx / rate < 0.1
    show = mx > 0 and ctype > 0 and not instant
    proj = f.get(M_CHARGE_PROJECTILE)
    projectile = int(proj) if proj is not None else -1
    return {
        "attack": round(mx, 2),
        "recharge": round(rate, 2),
        "type": ctype,
        "max": round(mx, 2),
        "rate": round(rate, 2),
        "recharge_time": round(mx / rate, 2) if rate > 0 and event >= 0 and not instant else None,
        "instant": instant,
        "event": event,
        "target": int(f.get(M_CHARGE_TARGET, 0) or 0),
        "projectile": projectile,
        "value": round(mx, 2) if show and ctype <= 3 else 0,
        "show": show,
    }  # fmt: skip


def charge_applies(mask: int, target_group: int | None) -> bool:
    """Whether a charge with ``chargeTarget`` ``mask`` affects an object group:
    negative = everything, 0 = everything but buildings, else a group bit test."""
    if mask < 0 or target_group is None:
        return True
    if mask == 0:
        return target_group not in CHARGE_TARGET_BITS[256]
    return any(mask & bit and target_group in groups for bit, groups in CHARGE_TARGET_BITS.items())


def aura_description(ids: Iterable[int], strings: dict[int, str]) -> str:
    """The first aura string id that resolves in the game string table."""
    for sid in ids:
        if strings.get(sid):
            return strings[sid]
    return ""


def unit_identity(mid: int, cls: int) -> int:
    """The master id a unit counts as: every fishing ship is Fishing Ship (13)."""
    return 13 if cls == CLASS_FISHING_BOAT else mid


def unit_line(mid: int, cls: int, lines: dict[int, str]) -> str:
    """The unit-line key a master belongs to (``l<LineID>`` from the game's
    ``unitlines.json``), else ``m<identity>``."""
    ident = unit_identity(mid, cls)
    return lines.get(ident) or f"m{ident}"


def is_military_master(mtype: int, cls: int) -> bool:
    """The "military" classification: a unit that is not civilian,
    king, animal, building or other non-army class."""
    return mtype >= TYPE_COMBAT and cls not in _NON_MILITARY_CLASSES


#: Masters never counted in "most created".
MOST_CREATED_EXCLUDED = frozenset({1252, 1253})


def train_locations(f: dict[int, Any]) -> list[int]:
    """Building masters that train this unit: ``idOfBuildingObj`` plus
    ``trainLocationIds``."""
    out: list[int] = []
    b = f.get(M_BUILDING_OBJ)
    if b is not None and int(b) > 0:
        out.append(int(b))
    for i in f.get(M_TRAIN_LOCATIONS) or ():
        if int(i) >= 0 and int(i) not in out:
            out.append(int(i))
    return out


def _num(f: dict[int, Any], fid: int) -> float:
    return round(float(f.get(fid, 0.0) or 0.0), 2)


def master_detail(f: dict[int, Any], mid: int | None = None) -> dict[str, Any]:
    """Every unit-panel number of one master node, as that node's owner has it.

    Masters are per player (``Player.masterEntities``), so upgrades and civ
    bonuses are already applied: read the *owner's* node, never a cached one.
    Zero values are omitted from the stream, so an absent field reads as 0.
    ``mid`` (the master id, which the node does not carry) selects the regen
    exemptions of :func:`regen_display`.
    """
    weapon = _class_values(f.get(M_WEAPON))
    rng = _num(f, M_RANGE)
    volley = _num(f, M_VOLLEY)
    aura, work = task_ranges(f)
    rules = master_rules(f)
    weapons = weapon_rows(f)
    base_rng = _num(f, M_ORIG_RANGE) if f.get(M_ORIG_RANGE) is not None else rng
    base_reload = _num(f, M_ORIG_RELOAD) if f.get(M_ORIG_RELOAD) is not None else _num(f, M_RELOAD)
    regen = regen_display(f, mid)
    out: dict[str, Any] = {
        **_unit_stats(f, mid),
        "hp": int(f.get(M_HP, 0) or 0),
        "aura_range": aura,
        "work_range": work,
        "min_range": _num(f, M_MIN_RANGE),
        "accuracy": int(f.get(M_ACCURACY, 0) or 0),
        # Total projectiles per shot: the volley amount, else one for a ranged unit.
        "projectiles": volley if volley > 0 else (1 if rng > 0 and weapon else 0),
        "blast_width": _num(f, M_BLAST_WIDTH),
        "blast_level": int(f.get(M_BLAST_LEVEL, 0) or 0),
        "blast_damage": _num(f, M_BLAST_DAMAGE),
        "charge": charge_info(f),
        "regen": _num(f, M_REGEN),
        "regen_display": _tidy(regen),
        "work_rate": _num(f, M_WORK_RATE),
        "garrison_capacity": int(f.get(M_CAPACITY, 0) or 0),
        "garrison_summary": int(f.get(M_CLASS, -1) or -1) != CLASS_GARRISON_HIDDEN,
        # The game's order (not sorted by label).
        "attacks": [[r[0], r[2]] for r in weapons],
        "armors": [[c, v] for c, v in _class_pairs(f.get(M_ARMOR))],
        "attack_rows": attack_rows(f),
        "armor_rows": armor_rows(f),
        "base": {
            "attacks": [[r[0], r[1]] for r in weapons],
            "armors": [[r[0], r[1]] for r in armor_table(f)],
            "range": base_rng,
            "reload": base_reload,
            "speed": round(_num(f, M_SPEED) * speed_factor(mid), 2),
            "regen": _tidy(regen),
            "hp": int(f.get(M_HP, 0) or 0),
        },
        "dot": rules.dot,
        "hp_loss_bonus": (
            {
                "amount": _tidy(rules.hp_loss[0]),
                "step": _tidy(rules.hp_loss[1]),
                "self": rules.hp_loss[2],
            }
            if rules.hp_loss is not None
            else None
        ),
        "kill_stack": rules.kill_stack,
        "charge_speed": rules.charge_speed,
        "aura": {"string_ids": rules.aura_ids} if rules.aura_ids else None,
        "train_locations": train_locations(f),
        "object_group": int(f.get(M_CLASS, -1) or -1),
        "combat_ability": int(f.get(M_ABILITY, 0) or 0),
        "cost": master_cost(f),
        "train_time": _num(f, M_BUILD_TIME),
    }
    return out


@dataclass(slots=True)
class ModContext:
    """What :func:`entity_mods` needs besides the entity and its master."""

    entities: dict[int, Node]
    players: dict[int, Node]
    #: entity id -> ``objectGroup`` of every unit it has killed so far
    kill_groups: Callable[[int], Sequence[int]] | None = None


def _projectile_rows(f: dict[int, Any], masters: dict[int, Node]) -> list[list[Any]] | None:
    """The charged weapon (chargeType 6 / 7): the projectile master's attack rows
    as ``[class, base, current-at-master]``, when it has a melee/pierce attack."""
    ctype = int(f.get(M_CHARGE_TYPE, 0) or 0)
    pid = f.get(M_CHARGE_PROJECTILE)
    if ctype not in (6, 7) or pid is None or int(pid) <= 0:
        return None
    node = masters.get(int(pid))
    if node is None:
        return None
    rows = weapon_rows(node.fields)
    if not any(r[0] in (ARMOR_MELEE, ARMOR_PIERCE) and r[2] for r in rows):
        return None
    own = {r[0]: r for r in weapon_rows(f)}
    # Base: the unit's own base for classes 3/4 it has, else the projectile's.
    return [[r[0], own[r[0]][1] if r[0] in own and r[0] in (3, 4) else r[1], r[2]] for r in rows]


def _weapon_sum(f: dict[int, Any]) -> float:
    v = dict(_class_pairs(f.get(M_WEAPON)))
    return float(v.get(ARMOR_MELEE, 0) + v.get(ARMOR_PIERCE, 0))


def entity_mods(
    e: Node,
    mf: dict[int, Any],
    rules: MasterRules,
    ctx: ModContext,
    masters: dict[int, Node],
    mid: int | None = None,
    charge: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], float, float]:
    """Live values of one unit that differ from its master, as the unit panel shows them.

    Returns ``(mods, hp_bonus, hp_max_bonus)`` -- ``mods`` is empty when the unit
    is exactly its master. Keys (all optional): ``attacks`` / ``armors``
    (``[[class, current]]``), ``range``, ``reload``, ``speed``, ``regen``,
    ``hp``, ``hp_max``, ``powered_by``, ``charging``, ``hp_loss``,
    ``kill_bonus``, ``charge_fill``, ``charge_applies``, ``charge_value``,
    ``charged_weapon`` (``[[class, base, current]]``). ``charge`` is
    ``charge_info(mf)`` when the caller already has it.
    """
    ef = e.fields
    ch = charge if charge is not None else charge_info(mf)
    has_charge = bool(ch["show"])
    if _MOD_FIDS.isdisjoint(ef) and not (
        rules.hp_loss or rules.kill_stack or has_charge or rules.charge_speed != 1.0
    ):
        return {}, 0.0, 0.0

    def g(name: str) -> float:
        return _n(ef.get(_CE[name]))

    mods: dict[str, Any] = {}
    eid = int(ef.get(E_ID, 0) or 0)
    kills = ctx.kill_groups(eid) if ctx.kill_groups is not None else ()
    ks = kill_stack_bonus(rules.kill_stack, kills) if rules.kill_stack else {"hp": 0, "attack": 0}
    if ks["hp"] or ks["attack"]:
        mods["kill_bonus"] = ks

    act = ef.get(E_ACTION)
    target: Node | None = None
    target_info: tuple[int, int] | None = None  # (objectGroup, master type)
    if isinstance(act, Node):
        tid = act.fields.get(A_TARGET)
        cand = ctx.entities.get(int(tid)) if tid is not None else None
        if cand is not None:
            target = cand
            tm = master_node(cand, ctx.players)
            if tm is not None:
                target_info = (
                    int(tm.fields.get(M_CLASS, -1) or -1),
                    int(tm.fields.get(M_TYPE, 0) or 0),
                )

    # HP-loss bonus (task 160): grows as the unit (or its current target) loses hp.
    hp_loss = 0.0
    if rules.hp_loss is not None:
        amount, step, own = rules.hp_loss
        ratio: float | None = None
        if own:
            if isinstance(act, Node) and int(act.fields.get(A_TYPE, 0) or 0) == 9:
                top = _n(mf.get(M_HP))
                ratio = _n(ef.get(E_HP, top)) / top if top else None
        elif target is not None and target_info is not None and target_info[1] != TYPE_BUILDING:
            tmn = master_node(target, ctx.players)
            top = _n(tmn.fields.get(M_HP)) if tmn is not None else 0.0
            if top:
                ratio = _n(target.fields.get(E_HP, top)) / top
        if ratio is not None and step > 0:
            hp_loss = amount * int(max(0.0, 1.0 - ratio) / step)
        if hp_loss:
            mods["hp_loss"] = _tidy(hp_loss)

    attack_bonus = int(g("attackPowerUp")) + int(g("attackStinger")) + ks["attack"]
    changed = False
    attacks = []
    for cls, _base, cur in weapon_rows(mf):
        v = cur + hp_loss + (attack_bonus if cls in (ARMOR_MELEE, ARMOR_PIERCE) else 0)
        changed = changed or v != cur
        attacks.append([cls, _tidy(v)])
    if changed:
        mods["attacks"] = attacks
    changed = False
    armors = []
    for cls, _base, cur in armor_table(mf):
        v = float(cur)
        if cls == ARMOR_MELEE:
            v += g("meleeArmorPowerUp") + g("meleeArmorStinger") - g("meleeArmorRemoved")
        elif cls == ARMOR_PIERCE:
            v += g("pierceArmorPowerUp") + g("pierceArmorStinger") - g("pierceArmorRemoved")
        changed = changed or v != cur
        armors.append([cls, _tidy(v)])
    if changed:
        mods["armors"] = armors

    # Charge: bar fill, whether it applies to the current target, the charged weapon.
    charging = bool(ef.get(_CE["isCharging"]))
    if charging:
        mods["charging"] = True
    applies = True
    if ch["type"] in (6, 7) and target_info is not None:
        applies = charge_applies(int(ch["target"]), target_info[0])
    fill = 0.0
    if has_charge and ch["event"] >= 0:
        fill = min(1.0, _n(ef.get(E_CHARGE)) / ch["max"]) if ch["max"] else 0.0
        mods["charge_fill"] = round(fill, 3)
        mods["charge_applies"] = applies
    cvalue: float = ch["value"]
    if has_charge and ch["type"] in (6, 7) and ch["projectile"] > 0:
        pnode = masters.get(int(ch["projectile"]))
        if pnode is not None:
            diff = _weapon_sum(pnode.fields)
            if diff > 0:
                cvalue = diff - _weapon_sum(mf)
        rows = _projectile_rows(mf, masters)
        if rows is not None:
            charged = [
                [c, _tidy(b), _tidy(v + (attack_bonus if c in (ARMOR_MELEE, ARMOR_PIERCE) else 0))]
                for c, b, v in rows
            ]
            mods["charged_weapon"] = [r for r in charged if r[1] or r[2]]
    if cvalue > 0:
        mods["charge_value"] = _tidy(cvalue)

    rng = _n(mf.get(M_RANGE)) + g("maxRangePowerup")
    if ch["type"] in (6, 7) and ch["event"] > 0 and applies and has_charge:
        rng += ch["event"]
    if rng != _n(mf.get(M_RANGE)):
        mods["range"] = _tidy(rng)
    reload_ = _n(mf.get(M_RELOAD)) - g("reloadPowerUp") + g("reloadStinger")
    if reload_ != _n(mf.get(M_RELOAD)):
        mods["reload"] = _tidy(reload_)
    base_speed = _n(mf.get(M_SPEED)) * speed_factor(mid)
    speed = base_speed * (rules.charge_speed if charging else 1.0)
    speed += g("speedPowerUp") + g("speedStinger")
    if speed != base_speed:
        mods["speed"] = _tidy(speed)
    regen = regen_display(mf, mid)
    if not regen_is_flat(mf, mid):  # class 36 reads a flat 30: no power-up/stinger on top
        regen += g("regenerationRatePowerUp") + g("regenerationStinger")
    if regen != regen_display(mf, mid):
        mods["regen"] = _tidy(regen)
    pu_hp = int(g("hitpointsMaxPowerUp") + g("hitpointsMaxStinger"))
    hp_max_bonus = float(pu_hp + ks["hp"])
    if pu_hp or ks["hp"]:
        top = _n(mf.get(M_HP))
        mods["hp_max"] = _tidy(top + hp_max_bonus)
        mods["hp"] = _tidy(_n(ef.get(E_HP, top)) + pu_hp)
    pwr = int(g("numUnitsPoweredUpBy"))
    if pwr > 0:
        mods["powered_by"] = pwr
    return mods, float(pu_hp), hp_max_bonus


def carry_amount(
    ef: dict[int, Any],
    rules: MasterRules,
    civ: int,
    done: Callable[[int], bool],
) -> list[Any] | int:
    """What a unit carries: ``[res, amount]`` or ``[res, amount, res2, amount2]``
    with the transient/secondary resource (synthesised from the civ's carry-bonus
    tasks when the game left it unset), or 0."""
    amount = _n(ef.get(E_HELD_AMT))
    ht = int(ef.get(E_HELD_TYPE, 0) or 0)
    out: list[Any] = []
    if amount > 0 and ht in _HELD_RESOURCE:
        out = [_HELD_RESOURCE[ht], round(amount, 1)]
    t2 = ef.get(E_TRANSIENT_TYPE)
    a2 = _n(ef.get(E_TRANSIENT_AMT))
    res2: str | None = None
    if t2 is not None and int(t2) in _HELD_RESOURCE and a2 > 0:
        res2 = _HELD_RESOURCE[int(t2)]
    elif (t2 is None or int(t2) == -1) and amount > 0 and rules.carry:
        for attr, attr2, attr3, v1 in rules.carry:
            if attr not in (-1, ht):
                continue
            bonus = CARRY_BONUS.get(civ, {}).get(attr2)
            if bonus is None or (bonus[1] is not None and not done(bonus[1])):
                continue
            if attr3 in _HELD_RESOURCE:
                res2, a2 = _HELD_RESOURCE[attr3], amount * v1 * bonus[0]
                break
    if res2 is not None and a2 > 0:
        out += [res2, round(a2, 1)]
    return out or 0


def is_king(mid: int, cls: int) -> bool:
    return cls == CLASS_KING or mid in KING_MASTERS


def is_monument(mid: int, name: str) -> bool:
    return mid in MONUMENT_MASTERS or name.strip().lower() == "monument"


def is_bridge(mid: int, name: str) -> bool:
    return mid in BRIDGE_MASTERS or "bridge" in name.lower()


class Catalog:
    """Names/icons for master entities and technologies, filled from the stream."""

    def __init__(self, data: GameData) -> None:
        self.data = data
        self.masters: dict[int, MasterInfo] = {}
        self.techs: dict[int, dict[str, Any]] = {}
        self.terrain_colors: list[tuple[int, int, int]] = []
        self.version = 0
        #: ``World.sprites`` of the current world, for damage graphics.
        self.world_sprites: list[Any] = []
        #: The current world's players (their master tables: projectile trails).
        self.world_players: dict[int, Node] = {}
        #: Livestock/domestic animal id -> last player that owned it (Gaia
        #: animals keep their last owner in the panel).
        self.last_owner: dict[int, int] = {}
        #: String ids of player-specific master names seen so far (the catalog
        #: sends them localized; views say which player uses which).
        self.owner_names: set[int] = set()
        #: Composite sprites' draw lists (computed once per sprite table).
        self._deltas: dict[int, list[list[int]]] = {}
        self._deltas_for: Any = None

    def own_master(self, owner: int, mid: int, node: Node | None) -> tuple[int, int] | None:
        """``owner``'s own ``(string id, icon)`` for ``mid`` when it differs from
        the catalog's: the Poles' Mill is their Folwark, an upgraded Archer is
        that player's Crossbowman, building icons change with the age."""
        info = self.masters.get(mid)
        if info is None or node is None or owner <= 0:
            return None
        f = node.fields
        sid, icon = int(f.get(M_STRING, -1)), int(f.get(M_ICON, 0))
        if (sid, icon) == (info.string_id, info.icon):
            return None
        if sid not in self.owner_names:
            self.owner_names.add(sid)
            self.version += 1
        return sid, icon

    def master(
        self, mid: int, node: Node | None, *, private: bool = False, owner: int | None = None
    ) -> MasterInfo | None:
        info = None if private else self.masters.get(mid)
        if info is not None or node is None:
            return info
        f = node.fields
        mtype = int(f.get(M_TYPE, 0) or 0)
        cls = int(f.get(M_CLASS, -1) or -1)
        name = self.data.string(f.get(M_STRING), "") or f"#{mid}"
        cost = master_cost(f)
        kind = "building" if mtype == TYPE_BUILDING else "unit" if mtype >= TYPE_COMBAT else "other"
        info = MasterInfo(
            id=mid,
            name=name,
            icon=int(f.get(M_ICON, 0)),
            cls=cls,
            type=mtype,
            hp=int(f.get(M_HP, 0) or 0),
            kind=kind,
            cost=cost,
            train_time=float(f.get(M_BUILD_TIME, 0) or 0),
            stats=_unit_stats(f, mid),
            size=round(2 * float(f.get(M_RADIUS_X, 0.5) or 0.5), 2),
            string_id=int(f.get(M_STRING, -1)),
            sounds=_sound_events(f),
            sprite=int(f.get(M_SPRITE, -1)),
            damage_sprites=damage_graphics(node, self.world_sprites),
            garrison_capacity=int(f.get(M_CAPACITY, 0) or 0),
            train_locations=train_locations(f),
            aura_ids=master_rules(f).aura_ids,
            trail=self._trail(node, owner=owner) if private else self._trail(node),
            storage=master_storage(f),
        )
        if not private:
            self.masters[mid] = info
            self.version += 1
        return info

    def entity_master(self, entity: Node, players: dict[int, Node]) -> MasterInfo | None:
        """A private node is complete and never seeds or reads the shared catalog cache."""
        raw_mid = entity.fields.get(E_MASTER)
        mid = int(raw_mid) if raw_mid is not None else -1
        if not isinstance(entity.fields.get(E_OWN_MASTER), Node):
            # Both lookups below answer from the shared cache once it holds the
            # master: skip finding the Player's node twice (every tree, every pass).
            known = self.masters.get(mid)
            if known is not None:
                return known
        # Populate shared names/icons from the real Player table even if the first
        # observed entity of this master has a private shadow.
        self.master(mid, player_master_node(entity, players))
        return self.master(
            mid,
            master_node(entity, players),
            private=isinstance(entity.fields.get(E_OWN_MASTER), Node),
            owner=int(entity.fields.get(E_OWNER, 0) or 0),
        )

    def private_presentation(self, info: MasterInfo, owner: int, mid: int) -> dict[str, Any]:
        """Complete private values already derived by the normal reader; no shared merge.

        String IDs are registered for the existing localized catalog channel.
        The renderer's active Entity layers still take precedence over sprite.
        """
        if info.string_id not in self.owner_names:
            self.owner_names.add(info.string_id)
            self.version += 1
        return {
            "owner": owner,
            "master": mid,
            "name": info.name,
            "string_id": info.string_id,
            "icon": info.icon,
            "cls": info.cls,
            "type": info.type,
            "kind": info.kind,
            "hp": info.hp,
            "cost": info.cost,
            "train_time": info.train_time,
            "stats": info.stats,
            "size": info.size,
            "sprite": info.sprite,
            "sounds": info.sounds,
            "damage_sprites": info.damage_sprites,
            "trail": info.trail,
            "storage": info.storage,
            "garrison_capacity": info.garrison_capacity,
            "train_locations": info.train_locations,
        }

    def _trail(self, node: Node | None, *, owner: int | None = None) -> dict[str, Any] | None:
        if node is None or node.model != MODEL_MASTER_MISSILE:
            return None
        f = node.fields
        tid = int(f.get(MM_TRAIL, -1) if f.get(MM_TRAIL) is not None else -1)
        spacing = float(f.get(MM_TRAIL_SPACING, 0.0) or 0.0)
        if tid < 0 or spacing <= 0:
            return None
        candidates = (
            (self.world_players.get(owner),) if owner is not None else self.world_players.values()
        )
        for p in candidates:
            if not isinstance(p, Node):
                continue
            ms = p.fields.get(P_MASTERS)
            tn = ms.get(tid) if isinstance(ms, dict) else None
            if not isinstance(tn, Node):
                continue
            sid = int(tn.fields.get(M_SPRITE, -1) if tn.fields.get(M_SPRITE) is not None else -1)
            sp = self.world_sprites[sid] if 0 <= sid < len(self.world_sprites) else None
            effect = str(sp.fields.get(SP_EFFECT, "") or "") if isinstance(sp, Node) else ""
            if effect:
                return {"particle": effect, "spacing": round(spacing, 3)}
        return None

    def load_techs(self, world: Node) -> None:
        techs = world.fields.get(W_TECHS)
        if not isinstance(techs, dict) or len(techs) == len(self.techs):
            return
        for tid, t in techs.items():
            if tid in self.techs:
                continue
            f = t.fields
            cost = {}
            for av in f.get(T_COST) or ():
                if isinstance(av, Node):
                    ty = av.fields.get(AV_TYPE, 0)
                    amt = float(av.fields.get(AV_AMOUNT, 0.0) or 0.0)
                    if 0 <= ty < 4 and amt > 0:
                        cost[RESOURCE_NAMES[ty]] = amt
            self.techs[tid] = {
                "id": tid,
                "name": self.data.string(f.get(T_STRING), "") or str(f.get(T_NAME, tid)),
                "string_id": int(f.get(T_STRING, -1)),
                "help_id": int(f.get(T_HELP, -1)),
                # Zero-valued fields are absent from the stream: no icon field means icon 0.
                "icon": int(f.get(T_ICON, 0)),
                "time": float(f.get(T_TIME, 0) or 0),
                "building": int(f.get(T_BUILDING, -1) or -1),
                "cost": cost,
            }
        self.version += 1

    def to_json(self, lang: str = "en") -> dict[str, Any]:
        strings = self.data.strings_for(lang) if lang != "en" else {}
        table = self.data.strings_for(lang)
        lines = self.data.unit_lines

        def name(sid: int, fallback: str) -> str:
            return strings.get(sid, fallback) if strings else fallback

        units: dict[str, Any] = {}
        for m in self.masters.values():
            ident = unit_identity(m.id, m.cls)
            military = is_military_master(m.type, m.cls)
            row: dict[str, Any] = {
                "name": name(m.string_id, m.name),
                "string_id": m.string_id,
                "icon": m.icon,
                "cls": m.cls,
                "kind": m.kind,
                "hp": m.hp,
                "cost": m.cost,
                "train_time": m.train_time,
                "stats": m.stats,
                "size": m.size,
                "sprite": m.sprite,
                "sounds": m.sounds,
                "damage_sprites": m.damage_sprites,
                "trail": m.trail,
                # Group composition, production queues and "most created".
                "line": unit_line(m.id, m.cls, lines),
                "identity": ident,
                "military": military,
                "most_created_ok": military and m.id not in MOST_CREATED_EXCLUDED,
                "train_locations": m.train_locations,
                "garrison_capacity": m.garrison_capacity,
            }
            if m.storage is not None:
                row["storage"] = m.storage

            if m.aura_ids:
                row["aura_description"] = aura_description(m.aura_ids, table)
            units[str(m.id)] = row
        civ_eras = {str(i): self.data.civ_era(i) for i in range(len(self.data.civs))}
        if self._deltas_for is not self.world_sprites:
            self._deltas = sprite_deltas(self.world_sprites)
            self._deltas_for = self.world_sprites
        return {
            "units": units,
            "sprite_deltas": {str(k): v for k, v in self._deltas.items()},
            "unit_names": {
                str(sid): name(sid, self.data.string(sid, "")) for sid in self.owner_names
            },
            "techs": {
                str(k): {
                    **v,
                    "name": name(int(v.get("string_id", -1)), v["name"]),
                    "help": table.get(int(v.get("help_id", -1)), ""),
                }
                for k, v in self.techs.items()
            },
            "civs": self._civ_names(strings),
            "unit_lines": {
                k: {"name": v["name"], "ids": v["ids"], "building": v["building"]}
                for k, v in self.data.unit_line_table().items()
            },
            "armor_classes": {
                str(c): table[ARMOR_CLASS_STRING + c]
                for c in range(64)
                if table.get(ARMOR_CLASS_STRING + c)
            },
            "building_groups": {"settlement": list(SETTLEMENT_MASTERS)},
            "civ_eras": civ_eras,
            "eras": self.data.eras(lang),
            "unique_techs": {str(k): v for k, v in self.data.unique_tech_ids.items()},
            "power_techs": self.data.power_tech_ids(),
            "pasture_civs": self.data.pasture_civs(),
            # The sprite colours by colour index, as the server tints strips with
            # them (a GPU-tinted strip takes its colour from here).
            "player_colors": [list(c) for c in self.data.player_colors],
            # Facings per sprite (those with several): the browser turns a moving
            # unit towards where it goes between two snapshots.
            "sprite_facets": {
                str(sid): int(sp.fields.get(SP_FACETS, 1) or 1)
                for sid, sp in enumerate(self.world_sprites or ())
                if isinstance(sp, Node) and int(sp.fields.get(SP_FACETS, 1) or 1) > 1
            },
        }

    def _civ_names(self, strings: dict[int, str]) -> dict[str, str]:
        out: dict[str, str] = {}
        for i, c in enumerate(self.data.civs):
            sid = c.get("name_string_id")
            out[str(i)] = (strings.get(int(sid)) if strings and sid is not None else None) or (
                self.data.civ_name(i)
            )
        return out


# -- tree accessors ---------------------------------------------------------------


def world_of(root: Node) -> Node | None:
    w = root.fields.get(ROOT_WORLD)
    return w if isinstance(w, Node) else None


def players_of(world: Node) -> dict[int, Node]:
    p = world.fields.get(W_PLAYERS)
    return p if isinstance(p, dict) else {}


def entities_of(world: Node) -> dict[int, Node]:
    e = world.fields.get(W_ENTITIES)
    return e if isinstance(e, dict) else {}


def attr(player: Node, name: str, default: float = 0.0) -> float:
    a = player.fields.get(P_ATTR)
    if not isinstance(a, Node):
        return default
    v = a.fields.get(_ATTR[name])
    return float(v) if v is not None else default


#: Folwark reach, measured on recorded replays: a newly built farm pays the
#: player ``folwarkCollectAmount`` food when its centre is at most this many
#: tiles (Chebyshev) from the Folwark's centre. 160 + 7 farms at 3 and 4 tiles
#: paid; 1 + 38 farms at 5..24 tiles did not.
FOLWARK_REACH = 4


def folwark(player: Node) -> dict[str, Any]:
    """The player's Folwark rule as the game sends it: which building master
    counts as the Folwark (``folwarkBuildingId``, -1 for civs without one) and
    the food a new farm next to it pays (``folwarkCollectAmount``)."""
    building = int(attr(player, "folwarkBuildingId", -1))
    if building < 0:
        return {"folwark_building": None, "folwark_food": None}
    return {
        "folwark_building": building,
        "folwark_food": round(attr(player, "folwarkCollectAmount"), 1),
        "folwark_reach": FOLWARK_REACH,
    }


def player_master_node(entity: Node, players: dict[int, Node]) -> Node | None:
    """The shared Player table only; never an entity's private shadow."""
    owner = players.get(int(entity.fields.get(E_OWNER, 0) or 0))
    masters = owner.fields.get(P_MASTERS) if owner is not None else None
    raw_mid = entity.fields.get(E_MASTER)
    mid = int(raw_mid) if raw_mid is not None else -1
    node = masters.get(mid) if isinstance(masters, dict) else None
    return node if isinstance(node, Node) else None


def master_node(entity: Node, players: dict[int, Node]) -> Node | None:
    own = entity.fields.get(E_OWN_MASTER)
    if isinstance(own, Node):
        return own
    return player_master_node(entity, players)


def live_entities(world: Node) -> Iterator[Node]:
    """Entities that exist on the map (not doppelgangers, not dying/dead).

    State 3 is alive for Gaia only -- it is how mines, bushes and carcasses
    persist while they still hold resources.
    """
    for e in entities_of(world).values():
        f = e.fields
        if e.model == MODEL_DOPPLE or f.get(E_DOPPLE):
            continue
        st = f.get(E_STATE)
        if (
            st is not None
            and st > ENTITY_ALIVE
            and (st != ENTITY_RESOURCE or (f.get(E_OWNER) or 0) != 0)
        ):
            continue
        yield e


MODEL_MISSILE = SCHEMA.model_id("MissileEntity")


def missile_rows(world: Node, cat: Catalog | None = None) -> list[list[Any]]:
    """Projectiles in flight: ``[id, owner, master, x, y, z, facet, layers]`` (z in
    elevation levels, absolute). They live a second or two, so the timeline keeps
    them per stream frame rather than per keyframe. Projectiles have negative ids."""
    out: list[list[Any]] = []
    for k, e in entities_of(world).items():
        if k >= 0 or e.model != MODEL_MISSILE:
            continue
        f = e.fields
        if f.get(E_STATE) not in (None, ENTITY_ALIVE):
            continue
        facet, layers = sprite_cols(e)
        if not layers:
            continue
        out.append(
            [
                int(k),
                int(f.get(E_OWNER, 0) or 0),
                int(f.get(E_MASTER, -1) if f.get(E_MASTER) is not None else -1),
                round(float(f.get(E_X, 0.0) or 0.0), 2),
                round(float(f.get(E_Y, 0.0) or 0.0), 2),
                round(float(f.get(E_Z, 0.0) or 0.0), 2),
                facet,
                layers,
            ]
        )
        if cat is not None:
            # Snapshot derived trail data now: never consult a later private shadow.
            players = players_of(world)
            out[-1].append(
                {"trail": cat._trail(master_node(e, players), owner=int(f.get(E_OWNER, 0) or 0))}
            )
    return out


def air_heights(world: Node) -> dict[str, float]:
    """Heights (``worldZ``, in elevation levels) of objects above the ground: birds,
    projectiles. Everything else stands on the terrain surface, whose height the
    view computes from the elevation grid (it is never more than one level above
    the tile's own elevation)."""
    w = int(world.fields.get(W_MAP_W, 0) or 0)
    tiles = world.fields.get(W_TILES) or []
    out: dict[str, float] = {}
    for e in entities_of(world).values():
        f = e.fields
        z = f.get(E_Z)
        if z:
            _note_air(f, z, w, tiles, out)
    return out


def _note_air(f: dict[int, Any], z: Any, w: int, tiles: list[Any], out: dict[str, float]) -> None:
    """Add an object at height ``z`` to ``out`` when it is above the ground."""
    x, y = int(f.get(E_X, 0.0) or 0.0), int(f.get(E_Y, 0.0) or 0.0)
    i = y * w + x
    t = tiles[i] if 0 <= i < len(tiles) else None
    elev = int(t.fields.get(TILE_ELEV, 0) or 0) if isinstance(t, Node) else 0
    if float(z) > elev + 1.05:
        out[str(int(f.get(E_ID, 0)))] = round(float(z), 2)


def remains_rows(world: Node) -> list[list[Any]]:
    """What the dead leave on the ground: dying units (their death animation),
    corpses decaying away and destroyed buildings' rubble. The game draws them
    under everything else; they are not units, so they are kept out of the
    entity rows (statistics, selection, minimap) and only drawn. Same columns as
    an entity row."""
    out: list[list[Any]] = []
    for e in entities_of(world).values():
        f = e.fields
        if e.model == MODEL_DOPPLE or f.get(E_DOPPLE):
            continue
        _note_remains(e, f.get(E_STATE), int(f.get(E_OWNER, 0) or 0), out)
    return out


def _note_remains(e: Node, st: Any, owner: int, out: list[list[Any]]) -> None:
    """Add a non-doppelganger entity's remains row to ``out`` when it is remains."""
    f = e.fields
    # A destroyed building's rubble stays as a player-owned "resource" object
    # (state 3, like the Flares a player places, which are not drawn).
    rubble = st == ENTITY_RESOURCE and owner > 0 and f.get(E_MASTER) not in FLARE_MASTERS
    if st not in (ENTITY_DYING, ENTITY_DECAYING) and not rubble:
        return
    if f.get(E_SPRITE) is None and not f.get(E_SPRITES):
        return
    out.append(
        [
            int(f.get(E_ID, 0)),
            owner,
            int(f.get(E_MASTER, -1) if f.get(E_MASTER) is not None else -1),
            round(float(f.get(E_X, 0.0) or 0.0), 2),
            round(float(f.get(E_Y, 0.0) or 0.0), 2),
            0.0,
            FLAG_REMAINS,
            *sprite_cols(e),
            ACT_IDLE,
            # A hunted animal's carcass is Gaia remains that still holds food.
            _carry(f) if owner == 0 else 0,
        ]
    )


# -- metadata ---------------------------------------------------------------------


def match_info(root: Node, data: GameData) -> dict[str, Any]:
    """Static facts about the match: map, players, teams, ratings."""
    opts = root.fields.get(ROOT_OPTIONS)
    world = world_of(root)
    info: dict[str, Any] = {"players": {}}
    if isinstance(opts, Node):
        o = opts.fields
        mapfile = str(o.get(GO_MAP_FILE, "") or "")
        info.update(
            # The colour grade the map script sets (None: chosen at random/by condition).
            color_grade=data.map_color_grade(mapfile.replace("\\", "/").rsplit("/", 1)[-1]),
            color_grades=data.color_grades,
            map_file=mapfile.replace("\\", "/").rsplit("/", 1)[-1],
            map_type=o.get(GO_MAP),
            pop_limit=o.get(GO_POP),
            ranked=bool(o.get(GO_RANKED)),
            speed=o.get(GO_SPEED),
            seed=o.get(GO_SEED),
            game_id=o.get(GO_GAME_ID),
            game_mode_id=int(o.get(GO_GAME_MODE, 0) or 0),
            game_mode=GAME_MODES.get(int(o.get(GO_GAME_MODE, 0) or 0), ""),
            victory_type=int(o.get(GO_VICTORY, 0) or 0),
            spectator_delay=int(o.get(GO_SPEC_DELAY, 0) or 0),
            treaty_minutes=int(o.get(GO_TREATY, 0) or 0),
            battle_royale_minutes=int(o.get(GO_BR_MINUTES, 0) or 0),
        )
        for pinfo in o.get(GO_PLAYERS) or ():
            if not isinstance(pinfo, Node):
                continue
            pf = pinfo.fields
            idx = pf.get(PGO_INDEX)
            if idx is None:
                continue
            ai = str(pf.get(PGO_AI, "") or "")
            elo = pf.get(PGO_ELO_RM)
            if elo is None or elo < 0:
                elo = pf.get(PGO_ELO_DM)
            info["players"][int(idx)] = {
                "team": int(pf.get(PGO_TEAM, 0) or 0),
                "human": str(pf.get(PGO_HUMAN, "") or ""),
                "ai": ai,
                "elo": int(elo) if elo is not None and elo > 0 else None,
                **_elos(pf),
            }
    if world is not None:
        info["map_size"] = [world.fields.get(W_MAP_W, 0), world.fields.get(W_MAP_H, 0)]
        for pid, p in players_of(world).items():
            entry = info["players"].setdefault(pid, {"team": 0, "ai": "", "elo": None})
            civ = p.fields.get(P_CIV)
            color = int(p.fields.get(P_COLOR, 0) or 0)
            rgb = data.player_colors[color % 8] if pid > 0 else (200, 200, 200)
            entry.update(
                id=pid,
                name=str(p.fields.get(P_NAME, f"Player {pid}")),
                civ=civ,
                civ_name=data.civ_name(civ) if pid > 0 else "Gaia",
                color_id=color,
                color="#{:02x}{:02x}{:02x}".format(*rgb),
            )
    # Teams: in AoE2 team 1 means "no team"; give each such player its own team.
    for pid, p in info["players"].items():
        if p.get("team", 0) <= 1:
            p["team_key"] = 100 + int(pid)
        else:
            p["team_key"] = int(p["team"])
    return info


def _elos(pf: dict[int, Any]) -> dict[str, int | None]:
    """Random-map and death-match ratings of one lobby slot (None when unrated)."""
    out: dict[str, int | None] = {}
    for key, fid in (("elo_rm", PGO_ELO_RM), ("elo_dm", PGO_ELO_DM)):
        v = pf.get(fid)
        out[key] = int(v) if v is not None and v > 0 else None
    return out


def lobby_elos(root: Node) -> dict[int, dict[str, int | None]]:
    """Player id -> ``{elo_rm, elo_dm}`` from the lobby options."""
    opts = root.fields.get(ROOT_OPTIONS)
    out: dict[int, dict[str, int | None]] = {}
    if isinstance(opts, Node):
        for pinfo in opts.fields.get(GO_PLAYERS) or ():
            if isinstance(pinfo, Node) and pinfo.fields.get(PGO_INDEX) is not None:
                out[int(pinfo.fields[PGO_INDEX])] = _elos(pinfo.fields)
    return out


def lobby_handicaps(root: Node) -> dict[int, int]:
    """Recorded lobby percentages; never infer handicap from a yield multiplier."""
    opts = root.fields.get(ROOT_OPTIONS)
    out: dict[int, int] = {}
    if isinstance(opts, Node):
        for info in opts.fields.get(GO_PLAYERS) or ():
            if not isinstance(info, Node):
                continue
            owner = info.fields.get(PGO_INDEX)
            percent = info.fields.get(PGO_HANDICAP)
            if isinstance(owner, int) and owner > 0 and isinstance(percent, int) and percent > 0:
                out[owner] = percent
    return out


def pop_limit(root: Node) -> int | None:
    opts = root.fields.get(ROOT_OPTIONS)
    if not isinstance(opts, Node):
        return None
    v = opts.fields.get(GO_POP)
    return int(v) if v else None


def map_layer(world: Node, data: GameData) -> dict[str, Any]:
    """Terrain + elevation grids for the minimap/world view."""
    w = int(world.fields.get(W_MAP_W, 0) or 0)
    h = int(world.fields.get(W_MAP_H, 0) or 0)
    tiles = world.fields.get(W_TILES) or []
    ttypes = world.fields.get(W_TERRAINS) or []
    pal = data.interface_palette
    colors = []
    textures: list[list[Any]] = []
    if not ttypes:
        # Native recordings carry terrain IDs but no table; the game's data file has it.
        for row in data.terrain_types:
            textures.append([row.pict, row.rows, row.mask.removesuffix(".png")])
            colors.append("#{:02x}{:02x}{:02x}".format(*pal[row.color % len(pal)]))
    for tt in ttypes:
        if isinstance(tt, Node):
            mask = str(tt.fields.get(TT_MASK, "") or "")
            textures.append(
                [
                    str(tt.fields.get(TT_PICT, "") or ""),
                    int(tt.fields.get(TT_ROWS, 10) or 10),
                    mask.removesuffix(".png"),  # the mask it is drawn through as a layer
                ]
            )
        else:
            textures.append(["", 10, ""])
        idx = int(tt.fields.get(TT_COLOR, 0) or 0) if isinstance(tt, Node) else 0
        colors.append("#{:02x}{:02x}{:02x}".format(*pal[idx % len(pal)]))
    elev = bytearray(w * h)
    shapes = bytearray(w * h)
    for i, t in enumerate(tiles[: w * h]):
        if isinstance(t, Node):
            elev[i] = int(t.fields.get(TILE_ELEV, 0) or 0) & 0xFF
            shapes[i] = int(t.fields.get(TILE_SHAPE, 0) or 0) & 0xFF
    tl = terrain_tiles(world)
    return {
        "width": w,
        "height": h,
        "terrain": tl[: w * h],
        "layers": tl[w * h :],
        "elevation": bytes(elev),
        # The tile's slope shape: which diagonal its two triangles share.
        "shapes": bytes(shapes),
        "terrain_colors": colors,
        "terrain_textures": textures,
    }


# -- the per-moment view ------------------------------------------------------------


@dataclass(slots=True)
class PlayerTally:
    """Aggregates over one player's entities at one moment."""

    villagers: int = 0
    military: int = 0
    eco_units: int = 0
    idle_villagers: int = 0
    tasks: Counter[str] = field(default_factory=Counter)
    food_tasks: Counter[str] = field(default_factory=Counter)
    units: Counter[int] = field(default_factory=Counter)
    buildings: Counter[int] = field(default_factory=Counter)
    army_value: float = 0.0
    army_gold: float = 0.0
    town_centers: int = 0
    castles: int = 0
    relics: int = 0
    trade_units: int = 0
    fishing_ships: int = 0
    held: dict[str, float] = field(default_factory=lambda: dict.fromkeys(RESOURCE_NAMES, 0.0))
    production: list[dict[str, Any]] = field(default_factory=list)
    #: Villager count per activity code (see ACTIVITY_NAMES).
    activity: Counter[int] = field(default_factory=Counter)
    idle_town_centers: int = 0
    #: building id -> master ids of the units inside it
    garrisons: dict[int, list[int]] = field(default_factory=dict)
    #: building id -> ``[unit id, master, hp, max hp]`` of the units inside it
    garrison_units: dict[int, list[list[Any]]] = field(default_factory=dict)
    trade_workshops: int = 0
    #: master id -> this player's own master node (per-player upgrades/bonuses)
    master_nodes: dict[int, Node] = field(default_factory=dict)


@dataclass(slots=True)
class ViewExtras:
    """What :func:`view` saw besides the JSON view, for the timeline's logs."""

    #: (owner, master id) -> shared Player master only, for every live entity
    master_nodes: dict[tuple[int, int], Node] = field(default_factory=dict)
    #: entity id -> (owner, master id, private shadow or None, shared source present).
    entity_masters: dict[int, tuple[int, int, Node | None, bool]] = field(default_factory=dict)
    #: entity id -> (owner, master id), garrisoned units included
    entities: dict[int, tuple[int, int]] = field(default_factory=dict)


def _action_node(e: Node, fid: int) -> Node | None:
    a = e.fields.get(fid)
    return a if isinstance(a, Node) else None


def research_time(cat: Catalog, tid: int, research: Any) -> float:
    """Seconds this player needs for tech ``tid``: the catalog time plus the player's
    ``researchAdjustment`` (civ bonuses: the Malay Feudal Age is 130 - 52 = 78 s)."""
    base = float(cat.techs.get(tid, {}).get("time", 0) or 0)
    rs = research.get(tid) if isinstance(research, dict) else None
    adj = rs.fields.get(R_ADJUST) if isinstance(rs, Node) else None
    return max(0.0, base + float(adj or 0)) if base else 0.0


def production_state(e: Node) -> dict[str, Any] | None:
    """Raw queue identity, shared by the HUD and frame-resolution idle history.

    A missing current action is meaningful: retain the queue without making up
    a progress value. This occurs during queue handoffs and population blocks.
    """
    f = e.fields
    queue = [
        {
            "unit": int(q.fields.get(Q_UNIT, -1)),
            "tech": int(q.fields.get(Q_TECH, -1)),
            "count": int(q.fields.get(Q_COUNT, 1)),
        }
        for q in f.get(B_QUEUE) or ()
        if isinstance(q, Node)
    ]
    act = _action_node(e, B_QUEUE_ACTION)
    current = None
    if act is not None:
        if act.model == MODEL_MAKE_TECH:
            current = {"tech": int(act.fields.get(MT_TECH, -1))}
        elif act.model == MODEL_MAKE_OBJECT:
            current = {"unit": int(act.fields.get(MO_OBJ, -1))}
    if not queue and current is None:
        return None
    return {"id": int(f.get(E_ID, 0)), "current": current, "queue": queue}


def _production(
    e: Node, cat: Catalog, masters: dict[int, Node], research: Any = None
) -> dict[str, Any] | None:
    prod = production_state(e)
    if prod is None:
        return None
    act = _action_node(e, B_QUEUE_ACTION)
    current = prod["current"]
    if act is not None and current is not None:
        if "tech" in current:
            total = research_time(cat, current["tech"], research)
            done = float(act.fields.get(MT_PROGRESS, 0.0) or 0.0)
        else:
            uid = current["unit"]
            done = float(act.fields.get(MO_WORK, 0.0) or 0.0)
            master = masters.get(uid)
            info = cat.master(uid, master)
            total = (
                float(master.fields.get(M_BUILD_TIME, 0) or 0)
                if isinstance(master, Node)
                else info.train_time
                if info is not None
                else 0.0
            )
        current.update(
            {
                "progress": min(1.0, done / total) if total else 0.0,
                "remaining": max(0.0, total - done) if total else None,
            }
        )
    return {
        **prod,
        "master": int(e.fields.get(E_MASTER, -1)),
        "x": e.fields.get(E_X, 0.0),
        "y": e.fields.get(E_Y, 0.0),
    }


def production_head(production: dict[str, Any]) -> dict[str, Any]:
    """First real queue item; an empty transition slot is not queued work."""
    return next(
        (
            q
            for q in production.get("queue", ())
            if int(q.get("count", 0)) > 0
            and (int(q.get("unit", -1)) >= 0 or int(q.get("tech", -1)) >= 0)
        ),
        {},
    )


def building_activity(production: dict[str, Any] | None, population_status: int = 0) -> int:
    """Queue intent survives the gap where the game removes its current action.

    Do not invent progress for that gap. A queued technology is research; a
    queued unit is production or a population block, never an empty building.
    """
    if not production:
        return ACT_IDLE
    current = production.get("current") or {}
    if int(current.get("tech", -1)) >= 0:
        return ACT_RESEARCHING
    if int(current.get("unit", -1)) >= 0:
        return ACT_PRODUCING
    head = production_head(production)
    if int(head.get("tech", -1)) >= 0:
        return ACT_RESEARCHING
    if int(head.get("unit", -1)) >= 0:
        return (
            ACT_HOUSED
            if population_status == 1
            else ACT_POP_LIMIT
            if population_status == 2
            else ACT_PRODUCING
        )
    return ACT_IDLE


def population_state(
    player: Node, production: Iterable[dict[str, Any]], limit: int = 0
) -> tuple[bool, int]:
    """Housing needs queued units, not merely zero headroom (which includes
    units in training). The overall population limit is a separate state."""
    pop = attr(player, "population")
    headroom = attr(player, "maxPop")
    cap = attr(player, "unitLimit") or float(limit or 0)
    heads = 0
    for b in production:
        first = production_head(b)
        if first:
            heads += int(int(first.get("unit", -1)) >= 0)
        elif (b.get("current") or {}).get("unit") is not None:
            heads += 1
    housed = bool(
        player_status(player) == "playing"
        and heads > 0
        and (not cap or pop + heads <= cap)
        and heads > headroom
    )
    return (True, 1) if housed else (False, 2 if cap and pop >= cap else 0)


def _carry(f: dict[int, Any]) -> list[Any] | int:
    """What a unit carries: ``[resource, amount]`` or 0."""
    amount = float(f.get(E_HELD_AMT, 0.0) or 0.0)
    ht = int(f.get(E_HELD_TYPE, 0) or 0)
    if amount <= 0 or not 0 <= ht < 4:
        return 0
    return [RESOURCE_NAMES[ht], round(amount, 1)]


def sprite_cols(e: Node) -> tuple[int, list[list[int]]]:
    """(facet, [[sprite, frame, offset_x, offset_y], ...]) in draw order."""
    f = e.fields
    sprites = f.get(E_SPRITES)
    if sprites and len(sprites) == 1 and isinstance(sprites[0], Node):
        # One active sprite (nearly every object): nothing to order.
        af = sprites[0].fields
        sid = int(af.get(AS_SPRITE, -1))
        if sid >= 0:
            one = [sid, int(af.get(AS_FRAME, 0)), int(af.get(AS_OX, 0)), int(af.get(AS_OY, 0))]
            return int(f.get(E_FACET, 0)), [one]
    layers: list[tuple[int, list[int]]] = []
    for a in f.get(E_SPRITES) or ():
        if isinstance(a, Node):
            af = a.fields
            sid = int(af.get(AS_SPRITE, -1))
            if sid >= 0:
                layers.append(
                    (
                        int(af.get(AS_ORDER, 0)),
                        [
                            sid,
                            int(af.get(AS_FRAME, 0)),
                            int(af.get(AS_OX, 0)),
                            int(af.get(AS_OY, 0)),
                        ],
                    )
                )
    layers.sort(key=lambda kv: kv[0])
    out = [layer for _, layer in layers]
    if not out:
        sid = int(f.get(E_SPRITE, -1))
        if sid >= 0:
            out = [[sid, 0, 0, 0]]
    return int(f.get(E_FACET, 0)), out


def sprite_table(world: Node) -> dict[int, tuple[str, int, int, float]]:
    """Sprite id -> (file name, frames per facing, facings, seconds per frame)."""
    out: dict[int, tuple[str, int, int, float]] = {}
    for sid, sp in enumerate(world.fields.get(W_SPRITES) or ()):
        if isinstance(sp, Node):
            f = sp.fields
            name = str(f.get(SP_NAME, "") or "")
            if name:
                out[sid] = (
                    name,
                    int(f.get(SP_FRAMES, 1) or 1),
                    int(f.get(SP_FACETS, 1) or 1),
                    float(f.get(SP_DURATION, 0.0) or 0.0),
                )
    return out


@dataclass(slots=True)
class Scene:
    """Map-wide facts :func:`tally` collects alongside the per-player tallies."""

    #: ``{pid, id, master, x, y, hp, garrisoned, inside}`` per living King
    kings: list[dict[str, Any]] = field(default_factory=list)
    #: foundation id -> build progress 0..1
    construction: dict[str, float] = field(default_factory=dict)
    gates_locked: list[int] = field(default_factory=list)
    #: entity id -> current charge (only entities that carry one)
    charge: dict[str, float] = field(default_factory=dict)
    #: the King of the Hill monument: ``{id, owner, x, y}``
    monument: dict[str, Any] | None = None
    #: entity id -> live values that differ from its master (:func:`entity_mods`)
    unit_mods: dict[str, dict[str, Any]] = field(default_factory=dict)
    #: Gaia livestock id -> the last player that owned it
    livestock_owner: dict[str, int] = field(default_factory=dict)
    #: player -> master id -> [string id, icon] where the player's own master
    #: differs from the catalog's (names via the catalog's ``unit_names``)
    owner_units: dict[str, dict[str, list[int]]] = field(default_factory=dict)
    #: Entity-keyed complete private presentation, never an owner/master override.
    entity_units: dict[str, dict[str, Any]] = field(default_factory=dict)
    #: ``[x, y, wood, id]`` per tree that is no longer full (felled or being cut);
    #: trees are a tile layer, not rows, and an untouched one holds its master's storage
    trees_left: list[list[float]] = field(default_factory=list)
    #: resource object id -> ``{player: villagers gathering from it}``
    gatherers: dict[str, dict[str, int]] = field(default_factory=dict)
    gather_targets: dict[str, int] = field(default_factory=dict)
    #: :func:`remains_rows` and :func:`air_heights`, gathered in the same walk
    remains: list[list[Any]] = field(default_factory=list)
    air: dict[str, float] = field(default_factory=dict)


#: A dictionary miss, told apart from a stored None in one lookup.
_MISSING: Any = object()


def tally(
    world: Node,
    cat: Catalog,
    scene: Scene | None = None,
    extras: ViewExtras | None = None,
    kill_groups: Callable[[int], Sequence[int]] | None = None,
) -> tuple[dict[int, PlayerTally], list[list[Any]]]:
    """Walk every live entity once: per-player aggregates + the entity table.

    Entity table rows are ``[id, owner, master, x, y, hp_fraction, flags, facet,
    sprites, activity, carry]`` (``sprites`` as in :func:`sprite_cols`, ``activity``
    an ``ACT_*`` code, ``carry`` as in :func:`_carry`: what a unit carries, or
    what a Gaia resource still holds) where
    ``flags`` bit 0 = building, bit 1 = military, bit 2 = villager, bit 3 =
    idle villager, bit 4 = under construction, bit 5 = resource/relic (Gaia),
    bit 6 = bridge (Gaia), bit 7 = King.

    Costs, hit points and build times are read from the *owner's* master node,
    so per-player upgrades and civilisation bonuses count (military value
    included); ``cat`` supplies only names and classes.

    ``kill_groups(eid)`` -- the ``objectGroup`` of each unit entity ``eid`` has
    killed so far -- feeds the kill-stacking bonus (absent: no bonus).
    """
    players = players_of(world)
    ctx = ModContext(entities_of(world), players, kill_groups)
    rules_cache: dict[tuple[int, int, int], MasterRules] = {}
    done_cache: dict[int, set[int]] = {}

    def rules_of(owner: int, mid: int, node: Node | None) -> MasterRules:
        got = rules_cache.get((owner, mid, id(node)))
        if got is None:
            got = rules_cache[(owner, mid, id(node))] = master_rules(node.fields if node else {})
        return got

    def carried_of(f: dict[int, Any], rules: MasterRules | None, owner: int) -> list[Any] | int:
        if rules is None:
            return _carry(f)
        civ = int(players[owner].fields.get(P_CIV, -1) or -1)
        return carry_amount(f, rules, civ, lambda tid: tid in done_techs(owner))

    def done_techs(owner: int) -> set[int]:
        got = done_cache.get(owner)
        if got is None:
            states = players[owner].fields.get(P_RESEARCH)
            got = {
                tid
                for tid, rs in (states.items() if isinstance(states, dict) else ())
                if rs.fields.get(R_STATE) == RESEARCH_DONE
            }
            done_cache[owner] = got
        return got

    out: dict[int, PlayerTally] = {pid: PlayerTally() for pid in players}
    rows: list[list[Any]] = []
    sc = scene if scene is not None else Scene()
    #: (owner, master) -> (total cost, gold cost, max hp, build points) this pass
    numbers: dict[tuple[int, int, int], tuple[float, float, int, float]] = {}

    def owner_numbers(owner: int, mid: int, node: Node | None) -> tuple[float, float, int, float]:
        key = (owner, mid, id(node))
        got = numbers.get(key)
        if got is None:
            nf = node.fields if node is not None else {}
            cost = master_cost(nf)
            got = (
                sum(cost.values()),
                cost.get("gold", 0.0),
                int(nf.get(M_HP, 0) or 0),
                float(nf.get(M_BUILD_TIME, 0) or 0),
            )
            numbers[key] = got
        return got

    # Gaia masters that are neither drawn as rows nor tallied (trees above all:
    # most of the map's entities) -> skipped before any per-entity work.
    gaia_skip: dict[int, bool] = {}
    #: tree master -> wood a full tree holds (trees are skipped, but cut ones are listed)
    tree_full: dict[int, float] = {}
    #: tree id -> [x, y, wood] for trees no longer full
    cut_trees: dict[int, list[float]] = {}
    #: resource id -> player -> villagers gathering from it
    gathering: dict[int, Counter[int]] = {}
    # Per pass, per node: ``charge_info`` and the owner's own name/icon (both
    # depend on the master node alone); per owner, the masters table.
    charges: dict[int, dict[str, Any]] = {}
    owns: dict[tuple[int, int, int], tuple[int, int] | None] = {}
    tables: dict[int, dict[int, Node]] = {}
    shared_nodes: dict[tuple[int, int], Node | None] = {}
    map_w = int(world.fields.get(W_MAP_W, 0) or 0)
    tiles = world.fields.get(W_TILES) or []
    # live_entities, inlined: this loop visits every object on the map (trees
    # above all) each keyframe, and collects air_heights and remains_rows on the way.
    for e in entities_of(world).values():
        f = e.fields
        fget = f.get
        z = fget(E_Z)
        if z:
            _note_air(f, z, map_w, tiles, sc.air)
        if e.model == MODEL_DOPPLE or fget(E_DOPPLE):
            continue
        st = fget(E_STATE)
        owner = int(fget(E_OWNER, 0) or 0)
        if st is not None and st > ENTITY_ALIVE and (st != ENTITY_RESOURCE or owner != 0):
            _note_remains(e, st, owner, sc.remains)
            continue
        raw_mid = fget(E_MASTER)
        mid = int(raw_mid) if raw_mid is not None else -1
        source_key = (owner, mid)
        shared = shared_nodes.get(source_key, _MISSING)
        if shared is _MISSING:
            shared = shared_nodes[source_key] = player_master_node(e, players)
        raw_private = fget(E_OWN_MASTER)
        private = raw_private if isinstance(raw_private, Node) else None
        eid = int(fget(E_ID, 0))
        # Identity/source history is independent of drawable/catalog eligibility.
        # Record every live source entity before Gaia or absent-info shortcuts.
        if extras is not None:
            extras.entities[eid] = source_key
            extras.entity_masters[eid] = (owner, mid, private, shared is not None)
            if shared is not None and owner > 0:
                extras.master_nodes.setdefault(source_key, shared)
        if owner == 0 and private is None and gaia_skip.get(mid):
            full = tree_full.get(mid)
            if full is not None:
                # _note_cut_tree's test inline: most of the map is full trees.
                amount = float(fget(E_HELD_AMT, 0.0) or 0.0)
                if st == ENTITY_RESOURCE or amount < full - 0.05:
                    _note_cut_tree(f, full, cut_trees)
            continue
        mnode = private if private is not None else shared
        if private is None:
            # Both catalog lookups answer from the shared cache once it holds the
            # master (as Catalog.entity_master).
            info = cat.masters.get(mid)
            if info is None:
                cat.master(mid, shared)
                info = cat.master(mid, mnode, private=False, owner=owner)
        else:
            cat.master(mid, shared)  # seed only the actual shared Player prototype
            info = cat.master(mid, mnode, private=True, owner=owner)
        if info is None:
            continue
        if private is not None:
            sc.entity_units[str(eid)] = cat.private_presentation(info, owner, mid)
        if owner == 0 and private is None and mid not in gaia_skip:
            gaia_skip[mid] = (
                info.type != TYPE_BUILDING
                and info.cls not in _GAIA_ROW_CLASSES
                and info.cls not in LIVESTOCK_CLASSES
            )
            if gaia_skip[mid]:
                if info.cls == CLASS_TREE:
                    tree_full[mid] = (info.storage or [None, 0.0])[1]
                    _note_cut_tree(f, tree_full[mid], cut_trees)
                continue
        okey = (owner, mid, id(shared))
        if okey in owns:
            own = owns[okey]
        else:
            own = owns[okey] = cat.own_master(owner, mid, shared)
        if own is not None and scene is not None:
            scene.owner_units.setdefault(str(owner), {})[str(mid)] = list(own)
        value = gold = build_pts = 0.0
        own_hp = 0
        if owner > 0:
            value, gold, own_hp, build_pts = owner_numbers(owner, mid, mnode)
        # Not inside anything reads as -1 *or* 0 (the starting units carry 0).
        inside = int(f.get(E_INSIDE, -1) or -1)
        garrisoned = inside > 0
        hpmax = own_hp or info.hp or 1
        hp = float(f.get(E_HP, hpmax) or 0.0)
        rules: MasterRules | None = None
        if owner > 0 and info.type >= TYPE_COMBAT and mnode is not None:
            rules = rules_of(owner, mid, mnode)
            ch = charges.get(id(mnode))
            if ch is None:
                ch = charges[id(mnode)] = charge_info(mnode.fields)
            # entity_mods' own early exit, without the call (most units).
            if not _MOD_FIDS.isdisjoint(f) or (
                rules.hp_loss or rules.kill_stack or ch["show"] or rules.charge_speed != 1.0
            ):
                masters_of = tables.get(owner)
                if masters_of is None:
                    owner_masters = players[owner].fields.get(P_MASTERS)
                    masters_of = tables[owner] = (
                        owner_masters if isinstance(owner_masters, dict) else {}
                    )
                mods, hp_bonus, hpmax_bonus = entity_mods(
                    e, mnode.fields, rules, ctx, masters_of, mid, ch
                )
                if mods:
                    sc.unit_mods[str(eid)] = mods
                    hp += hp_bonus
                    hpmax += int(hpmax_bonus)
        flags = 0
        x, y = f.get(E_X, 0.0) or 0.0, f.get(E_Y, 0.0) or 0.0
        charge = f.get(E_CHARGE)
        if charge:
            sc.charge[str(eid)] = round(float(charge), 2)
        if info.type == TYPE_BUILDING and f.get(B_GATE_LOCKED):
            sc.gates_locked.append(eid)
        if info.type == TYPE_BUILDING and is_monument(mid, info.name):
            sc.monument = {"id": eid, "owner": owner, "x": round(x, 2), "y": round(y, 2)}
        if info.cls in LIVESTOCK_CLASSES:
            if owner > 0:
                cat.last_owner[eid] = owner
            elif eid in cat.last_owner:
                sc.livestock_owner[str(eid)] = cat.last_owner[eid]
        if owner == 0:
            bridge = info.type == TYPE_BUILDING and is_bridge(mid, info.name)
            if info.cls in _GAIA_ROW_CLASSES or bridge or private is not None:
                flags |= (1 | 64) if bridge else 32
                if info.cls == CLASS_CLIFF:
                    flags |= FLAG_SCENERY
                rows.append(
                    [
                        eid,
                        0,
                        mid,
                        round(x, 2),
                        round(y, 2),
                        round(min(1.0, hp / hpmax), 3),
                        flags,
                        *sprite_cols(e),
                        ACT_IDLE,
                        _carry(f),
                    ]
                )
            continue
        t = out.get(owner)
        if t is None:
            continue
        if shared is not None:
            t.master_nodes.setdefault(mid, shared)
        activity = ACT_OTHER
        carry: list[Any] | int | None = None  # a villager's, already worked out
        if garrisoned:
            t.garrisons.setdefault(inside, []).append(mid)
            t.garrison_units.setdefault(inside, []).append([eid, mid, round(hp, 1), hpmax])
        if info.type == TYPE_BUILDING:
            flags |= 1
            # ``built`` is omitted while false (zero values are not streamed).
            if not f.get(B_BUILT):
                flags |= 16
                done = float(f.get(B_BUILD_PTS, 0.0) or 0.0)
                pct = min(1.0, done / build_pts) if build_pts else 0.0
                sc.construction[str(eid)] = round(pct, 3)
            if not flags & 16:  # completed buildings only: a foundation is not a castle yet
                t.buildings[mid] += 1
                if mid in TOWN_CENTER_MASTERS:
                    t.town_centers += 1
                if mid in CASTLE_MASTERS:
                    t.castles += 1
                if "trade workshop" in info.name.lower():
                    t.trade_workshops += 1
            t.relics += int(f.get(B_RELICS, 0) or 0)
            owner_masters = players[owner].fields.get(P_MASTERS)
            # A foundation produces nothing yet (its queue is the builders' work).
            prod = (
                None
                if flags & 16
                else _production(
                    e,
                    cat,
                    owner_masters if isinstance(owner_masters, dict) else {},
                    players[owner].fields.get(P_RESEARCH),
                )
            )
            if prod is not None:
                t.production.append(prod)
            activity = ACT_BUILDING if flags & 16 else building_activity(prod)
            if mid in TOWN_CENTER_MASTERS and activity == ACT_IDLE and not flags & 16:
                t.idle_town_centers += 1
        elif info.type >= TYPE_COMBAT:  # type 60 is projectiles (negative ids), not units
            t.units[mid] += 1
            if is_king(mid, info.cls):
                flags |= 128
                activity = unit_activity(e, None, garrisoned)
                sc.kings.append(
                    {
                        "pid": owner,
                        "id": eid,
                        "master": mid,
                        "x": round(x, 2),
                        "y": round(y, 2),
                        "hp": round(min(1.0, hp / hpmax), 3),
                        "garrisoned": garrisoned,
                        "inside": inside if garrisoned else -1,
                    }
                )
            elif info.cls == CLASS_CIVILIAN:
                t.villagers += 1
                flags |= 4
                task, sub = villager_task(mid, info.name)
                act = _action_node(e, E_ACTION)
                if garrisoned:
                    task = "garrisoned"
                elif task is None or act is None:
                    if act is None:
                        t.idle_villagers += 1
                        flags |= 8
                        task = "idle"
                    else:
                        task = task or "other"
                t.tasks[task] += 1
                activity = unit_activity(e, task, garrisoned)
                t.activity[activity] += 1
                if (
                    not garrisoned
                    and act is not None
                    and int(act.fields.get(A_TYPE, 0) or 0) in _GATHER_ACTIONS
                ):
                    tid = act.fields.get(A_TARGET)
                    if tid is not None and tid >= 0:
                        gathering.setdefault(int(tid), Counter())[owner] += 1
                        sc.gather_targets[str(eid)] = int(tid)
                if task == "food":
                    t.food_tasks[sub or "other"] += 1
                carried = carry = carried_of(f, rules, owner)
                if isinstance(carried, list):
                    for k in range(0, len(carried), 2):
                        t.held[str(carried[k])] += float(carried[k + 1])
            elif info.cls in _ECO_CLASSES:
                t.eco_units += 1
                activity = unit_activity(e, None, garrisoned)
                if info.cls == CLASS_FISHING_BOAT:
                    t.fishing_ships += 1
                    t.tasks["food"] += 1
                    t.food_tasks["fish"] += 1
                else:
                    t.trade_units += 1
                    t.tasks["trade"] += 1
            else:
                activity = unit_activity(e, None, garrisoned)
                if info.cls not in _NON_MILITARY_CLASSES:
                    t.military += 1
                    flags |= 2
                    t.army_value += value
                    t.army_gold += gold
        if garrisoned:
            continue
        rows.append(
            [
                eid,
                owner,
                mid,
                round(x, 2),
                round(y, 2),
                round(min(1.0, hp / hpmax), 3),
                flags,
                *sprite_cols(e),
                activity,
                carry
                if carry is not None
                # Nothing held or in transit: both carry readers give 0 (most units).
                else carried_of(f, rules, owner)
                if f.get(E_HELD_AMT) or f.get(E_TRANSIENT_AMT)
                else 0,
            ]
        )
    for tid, by in gathering.items():
        sc.gatherers[str(tid)] = {str(o): n for o, n in by.items()}
    sc.trees_left = [[*xyw, tid] for tid, xyw in cut_trees.items()]
    return out, rows


def _note_cut_tree(f: dict[int, Any], full: float, out: dict[int, list[float]]) -> None:
    """List a tree that is felled (state 3) or holds less than a full tree."""
    amount = float(f.get(E_HELD_AMT, 0.0) or 0.0)
    if f.get(E_STATE) == ENTITY_RESOURCE or amount < full - 0.05:
        x, y = float(f.get(E_X, 0.0) or 0.0), float(f.get(E_Y, 0.0) or 0.0)
        out[int(f.get(E_ID, 0))] = [round(x, 2), round(y, 2), round(amount, 1)]


def research(player: Node, cat: Catalog) -> tuple[list[int], list[dict[str, Any]]]:
    """(completed tech ids, in-progress techs with progress) for one player."""
    states = player.fields.get(P_RESEARCH)
    done: list[int] = []
    active: list[dict[str, Any]] = []
    if not isinstance(states, dict):
        return done, active
    for tid, rs in states.items():
        st = rs.fields.get(R_STATE)
        if st == RESEARCH_DONE:
            done.append(tid)
        elif st == RESEARCH_ACTIVE:
            total = research_time(cat, tid, states)
            prog = float(rs.fields.get(R_PROGRESS, 0.0) or 0.0)
            active.append(
                {
                    "tech": tid,
                    "progress": min(1.0, prog / total) if total else 0.0,
                    "remaining": max(0.0, total - prog) if total else None,
                }
            )
    return done, active


#: ``VictoryPointEntry.group`` -> score category. The game's score is the sum of
#: every entry's ``currPoints``; the sum equals ``Player.victoryPoints``
#: (checked on two captured games at several times). Group 0 is omitted on the
#: wire (zero values are not streamed). Unseen groups count as society.
SCORE_GROUPS = {0: "military", 1: "economy", 3: "technology", 5: "society"}


def score_parts(p: Node) -> dict[str, int] | None:
    """The game's own score by category, from ``Player.victoryPointMap``."""
    vpm = p.fields.get(P_VP_MAP)
    entries = vpm.values() if isinstance(vpm, dict) else vpm if isinstance(vpm, list) else ()
    out = dict.fromkeys(("military", "economy", "technology", "society"), 0)
    seen = False
    for e in entries:
        if not isinstance(e, Node):
            continue
        seen = True
        group = int(e.fields.get(VP_GROUP, 0) or 0)
        out[SCORE_GROUPS.get(group, "society")] += int(e.fields.get(VP_POINTS, 0) or 0)
    return out if seen else None


VP_ID = _fid("VictoryPointEntry", "id")
VP_AMOUNT = _fid("VictoryPointEntry", "currAttributeAmount")
#: ``victoryPointMap`` entry whose ``currAttributeAmount`` is the running total of
#: gold the player's relics produced (shown as ``relicGold``).
#: The ``PlayerAttributes.relicGold`` attribute (#181) is only the per-relic rate
#: (a constant 30 in every recording), not an accumulator.
VP_RELIC_GOLD = 27


def vp_amount(p: Node, entry_id: int) -> float:
    """``currAttributeAmount`` of one ``victoryPointMap`` entry (0 when absent)."""
    vpm = p.fields.get(P_VP_MAP)
    items = (
        vpm.items() if isinstance(vpm, dict) else enumerate(vpm if isinstance(vpm, list) else ())
    )
    total = 0.0
    for key, e in items:
        if not isinstance(e, Node):
            continue
        eid = e.fields.get(VP_ID)
        if (int(key) if eid is None else int(eid)) == entry_id:
            total += float(e.fields.get(VP_AMOUNT, 0) or 0)
    return total


def pop_cap(pop: int, headroom: float, pop_limit: int | None) -> int:
    """The population cap the game shows: housing, clamped to the lobby limit."""
    cap = int(pop + headroom)
    return min(cap, max(pop_limit, pop)) if pop_limit else cap


def player_stats(p: Node, t: PlayerTally, pop_limit: int | None = None) -> dict[str, Any]:
    """Every per-player number the dashboard, graphs and end screen read.

    ``pop_limit`` is the lobby population limit: at the limit a player is not
    housed, even though the game's headroom attribute reads 0 there.
    """
    a = {
        n: attr(p, n)
        for n in (
            "food",
            "wood",
            "stone",
            "gold",
            "population",
            "maxPop",
            "civilianPop",
            "militaryPop",
            "currentEra",
            "unitsKilled",
            "razings",
            "unitsKilledByOthers",
            "buildingsRazedByOthers",
            "foodTotal",
            "woodTotal",
            "stoneTotal",
            "goldTotal",
            "totalValuesOfKills",
            "buildValueCurrentUnits",
            "buildValueCurrentBuildings",
            "villagerIdleSecondsTotal",
            "villagersCreatedTotal",
            "relicGold",
            "tributeScore",
            "totalTributeReceived",
            "unitsConverted",
            "convesions",
            "foodScore",
            "woodScore",
            "stoneScore",
            "goldScore",
            "techCostSummation",
            "buildCostCurrentStuff",
            "hitPointsKilled",
            "hitPointRazings",
            "tribute",
            "exploration",
            "technology",
            "queuedPopCount",
            "trainingPopCount",
            "totalCastlesBuilt",
            "totalWondersBuilt",
            "artifacts",
            "ruins",
            "buildValueTotalUnits",
            "buildValueTotalBuildings",
        )
    }
    collected = a["foodTotal"] + a["woodTotal"] + a["stoneTotal"] + a["goldTotal"]
    pop, headroom = int(a["population"]), a["maxPop"]
    at_limit = pop_limit is not None and pop_limit > 0 and pop >= pop_limit
    parts = score_parts(p) or {
        # Older streams without a victory-point map: the attribute-based estimate.
        "military": round(a["hitPointsKilled"] + a["hitPointRazings"]),
        "economy": round(a["foodScore"] + a["woodScore"] + a["stoneScore"] + a["goldScore"]),
        "technology": round(a["techCostSummation"]),
        "society": 0,
    }
    vp = p.fields.get(P_VP)
    return {
        "resources": {n: round(a[n], 1) for n in RESOURCE_NAMES},
        "collected": {
            "food": round(a["foodTotal"]),
            "wood": round(a["woodTotal"]),
            "stone": round(a["stoneTotal"]),
            "gold": round(a["goldTotal"]),
            "total": round(collected),
        },
        "pop": int(a["population"]),
        # Attribute 4 is pop *headroom*; the cap the UI shows is pop + headroom,
        # which the game clamps to the lobby limit (houses past 200 add nothing).
        "pop_cap": pop_cap(pop, headroom, pop_limit),
        "civilian_pop": int(a["civilianPop"]),
        "military_pop": int(a["militaryPop"]),
        "age": int(a["currentEra"]),
        "kills": int(a["unitsKilled"]),
        "deaths": int(a["unitsKilledByOthers"]),
        "razings": int(a["razings"]),
        "buildings_lost": int(a["buildingsRazedByOthers"]),
        "kill_value": round(a["totalValuesOfKills"]),
        "units_value": round(a["buildValueCurrentUnits"]),
        "buildings_value": round(a["buildValueCurrentBuildings"]),
        "idle_seconds_total": round(a["villagerIdleSecondsTotal"]),
        "villagers_created": int(a["villagersCreatedTotal"]),
        "relic_gold": round(vp_amount(p, VP_RELIC_GOLD)),
        "tribute_received": round(a["totalTributeReceived"]),
        "conversions": int(a["convesions"]),
        "techs_researched": int(a["technology"]),
        "tech_spend": round(a["techCostSummation"]),
        "score": parts,
        "score_parts": dict(parts),
        "score_total": int(vp) if vp is not None else sum(parts.values()),
        "kills_total": int(a["unitsKilled"] + a["razings"]),
        "deaths_total": int(a["unitsKilledByOthers"] + a["buildingsRazedByOthers"]),
        # Everything trained, built and researched so far (the game's own sums).
        "value_spent": round(
            a["buildValueTotalUnits"] + a["buildValueTotalBuildings"] + a["techCostSummation"]
        ),
        # Own units lost to enemy monks (``conversions`` is the reverse).
        "desertions": int(a["unitsConverted"]),
        "castles_built": int(a["totalCastlesBuilt"]),
        "wonders_built": int(a["totalWondersBuilt"]),
        "trade_workshops": t.trade_workshops,
        # Gold delivered by trade carts and cogs (``Player.tradeGoldReceived``).
        "trade_profit": round(float(p.fields.get(P_TRADE_GOLD, 0.0) or 0.0)),
        "villagers": t.villagers,
        "military": t.military,
        "eco_units": t.villagers + t.eco_units,
        "idle_villagers": t.idle_villagers,
        "fishing_ships": t.fishing_ships,
        "trade_units": t.trade_units,
        "tasks": dict(t.tasks),
        "food_tasks": dict(t.food_tasks),
        "army_value": round(t.army_value),
        "army_gold": round(t.army_gold),
        "town_centers": t.town_centers,
        "castles": t.castles,
        "relics": t.relics,
        "held": {k: round(v, 1) for k, v in t.held.items()},
        "units": {str(k): v for k, v in t.units.items()},
        "buildings": {str(k): v for k, v in t.buildings.items()},
        "production": t.production,
        "activity": {ACTIVITY_NAMES[k]: v for k, v in t.activity.items()},
        "idle_town_centers": t.idle_town_centers,
        "garrisons": {str(k): v for k, v in t.garrisons.items()},
        "garrison_units": {str(k): v for k, v in t.garrison_units.items()},
        "housed": headroom <= 0 and not at_limit,
    }


REL_STANCE = _fid("Relation", "enumValue")
#: ``Relation.enumValue``: 0 ally (omitted when zero), 1 neutral, 3 enemy.
STANCES = {0: "ally", 1: "neutral", 2: "neutral", 3: "enemy"}


def diplomacy(p: Node) -> dict[str, str]:
    """Stance of this player towards every *other* player (index = player id)."""
    out: dict[str, str] = {}
    me = int(p.fields.get(P_ID, -1) or -1)
    for i, rel in enumerate(p.fields.get(P_RELATIONS) or ()):
        if i in (0, me) or not isinstance(rel, Node):
            continue
        out[str(i)] = STANCES.get(int(rel.fields.get(REL_STANCE, 0) or 0), "enemy")
    return out


def player_status(p: Node) -> str:
    f = p.fields
    if f.get(P_RESIGNED):
        return "resigned"
    if f.get(P_DROPPED):
        return "dropped"
    st = f.get(P_STATUS)
    return {1: "won", 2: "lost"}.get(int(st), "playing") if st is not None else "playing"


W_PARTICLES = _fid("World", "particleInstances")
W_PARTICLE_NAMES = _fid("World", "particleDefinitionNames")
_PI = {s.name: s.fid for s in SCHEMA.fields(SCHEMA.model_id("ParticleInstance")).values()}


def particles(world: Node, born_since: tuple[int, int] | None = None) -> list[list[Any]]:
    """Live particles: ``[x, y, z, sprite, age_s, duration_s, scale, alpha, r, g, b,
    owner_object, definition, image, rotation_deg, offset_x, offset_y]`` (fire,
    smoke, dust, impacts). ``definition`` indexes ``World.particleDefinitionNames``;
    the offset (screen pixels at standard graphics) places an emitter on its
    object's picture: a burning building's flames, a chimney's smoke.

    ``born_since=(t, prev)`` keeps only particles born after ``prev`` when the
    game time is ``t`` (birth = ``t`` - age in ms, from the rounded age)."""
    out: list[list[Any]] = []
    for pi in world.fields.get(W_PARTICLES) or ():
        if not isinstance(pi, Node):
            continue
        f = pi.fields
        if not f.get(_PI["active"]) or not f.get(_PI["spriteUsed"]):
            continue
        sid = int(f.get(_PI["spriteId"], -1))
        if sid < 0:
            continue
        dur = float(f.get(_PI["spriteDuration"], 0.0) or 0.0)
        age = float(f.get(_PI["spriteAge"], 0.0) or 0.0)
        if born_since is not None and born_since[0] - round(round(age, 2) * 1000) <= born_since[1]:
            continue
        frac = min(1.0, age / dur) if dur else 0.0
        s0 = float(f.get(_PI["spriteScaleStart"], 1.0) or 1.0)
        s1 = float(f.get(_PI["spriteScaleEnd"], s0) or s0)
        a0 = float(f.get(_PI["spriteAlphaStart"], 1.0) or 1.0)
        a1 = float(f.get(_PI["spriteAlphaEnd"], a0) or a0)
        out.append([
            round(float(f.get(_PI["spritePositionX"], f.get(_PI["positionX"], 0.0)) or 0.0), 2),
            round(float(f.get(_PI["spritePositionY"], f.get(_PI["positionY"], 0.0)) or 0.0), 2),
            round(float(f.get(_PI["spritePositionZ"], f.get(_PI["positionZ"], 0.0)) or 0.0), 2),
            sid, round(age, 2), round(dur, 2), round(s0 + (s1 - s0) * frac, 2),
            round((a0 + (a1 - a0) * frac) * float(f.get(_PI["spriteFadeAlpha"], 1.0) or 1.0), 2),
            round(float(f.get(_PI["spriteColorR"], 1.0) or 1.0), 2),
            round(float(f.get(_PI["spriteColorG"], 1.0) or 1.0), 2),
            round(float(f.get(_PI["spriteColorB"], 1.0) or 1.0), 2),
            int(f.get(_PI["objectId"], -1)),
            int(f.get(_PI["definitionId"], 0)),
            int(f.get(_PI["spriteIndex"], 0)),
            round(
                float(f.get(_PI["spriteRotationStart"], 0.0) or 0.0)
                + float(f.get(_PI["spriteRotationSpeed"], 0.0) or 0.0) * age,
                1,
            ),
            round(float(f.get(_PI["offset2dX"], 0.0) or 0.0), 1),
            round(float(f.get(_PI["offset2dY"], 0.0) or 0.0), 1),
        ])  # fmt: skip
    return out


def treaty(world: Node) -> dict[str, Any] | None:
    """The truce (treaty / D3 mode) state, or None when the game has none."""
    tm = world.fields.get(W_TREATY)
    if not isinstance(tm, Node):
        return None
    left = int(tm.fields.get(TM_LEFT, 0) or 0)
    total = int(tm.fields.get(TM_TOTAL, 0) or 0)
    if not total and not left:
        return None
    return {"time_left_s": max(0, left), "total_s": total, "active": left > 0}


def view(
    root: Node,
    cat: Catalog,
    extras: ViewExtras | None = None,
    kill_groups: Callable[[int], Sequence[int]] | None = None,
) -> dict[str, Any] | None:
    """The complete JSON-ready state of one moment of the game.

    ``extras``, when given, collects the owner master nodes and entity owners
    the timeline logs for the unit panel. ``kill_groups(eid)`` lists the
    ``objectGroup`` of every unit the entity has killed (kill-stacking bonus).
    """
    world = world_of(root)
    if world is None:
        return None
    cat.load_techs(world)
    cat.world_sprites = world.fields.get(W_SPRITES) or []
    cat.world_players = players_of(world)
    scene = Scene()
    tallies, rows = tally(world, cat, scene, extras, kill_groups)
    limit = pop_limit(root)
    elos = lobby_elos(root)
    players: dict[str, Any] = {}
    building_states: dict[int, int] = {}
    for pid, p in players_of(world).items():
        if pid == 0:
            continue
        stats = player_stats(p, tallies[pid], limit)
        stats["housed"], stats["population_status"] = population_state(
            p, stats["production"], limit or 0
        )
        for prod in stats["production"]:
            building_states[prod["id"]] = building_activity(prod, stats["population_status"])
        done, active = research(p, cat)
        # A building's MakeTechAction carries the live progress; ResearchState's
        # own counter is not advanced while the tech is queued in a building.
        by_tech = {a["tech"]: a for a in active}
        for prod in stats["production"]:
            cur = prod.get("current")
            if cur is not None and "tech" in cur:
                by_tech[cur["tech"]] = {**cur, "building": prod["id"]}
        stats["research_done"] = done
        stats["research_active"] = list(by_tech.values())
        stats["status"] = player_status(p)
        stats["diplomacy"] = diplomacy(p)
        stats["farm_queue"] = int(p.fields.get(P_FARM_QUEUE, 0) or 0)
        stats.update(folwark(p))
        stats.update(elos.get(pid) or {"elo_rm": None, "elo_dm": None})
        players[str(pid)] = stats
    for row in rows:
        if row[0] in building_states:
            row[9] = building_states[row[0]]
    wf = world.fields
    return {
        "time": int(wf.get(W_TIME, 0) or 0),
        "game_ended": bool(wf.get(W_GAME_ENDED)),
        "market": {
            "food": wf.get(W_PRICES[0]),
            "wood": wf.get(W_PRICES[1]),
            "stone": wf.get(W_PRICES[2]),
        },
        "countdown": wf.get(W_COUNTDOWN) if wf.get(W_COUNTDOWN_VICTORY) else None,
        "victory_type": int(wf.get(W_VICTORY_TYPE, 0) or 0),
        "players": players,
        "entities": rows,
        "remains": scene.remains,
        "air": scene.air,
        "particles": particles(world),
        "kings": scene.kings,
        "construction": scene.construction,
        "owner_units": scene.owner_units,
        "entity_units": scene.entity_units,
        "gates_locked": scene.gates_locked,
        "charge": scene.charge,
        "unit_mods": scene.unit_mods,
        "livestock_owner": scene.livestock_owner,
        "trees_left": scene.trees_left,
        "gatherers": scene.gatherers,
        "gather_targets": scene.gather_targets,
        # The timeline adds the hold timer (``held_ms``/``required_ms``).
        "koth": {**scene.monument} if scene.monument is not None else None,
        "treaty": treaty(world),
    }


CLASS_TREE = 15


#: ``layers`` byte for a tile without a layer terrain.
NO_LAYER = 255


def terrain_tiles(world: Node) -> bytes:
    """Every tile's current terrain, as the game paints it now (farms, pastures,
    foundations and buildings change it): one byte per tile for the base terrain
    (row-major), then one per tile for the layer terrain drawn over it through
    that terrain's overlay mask (:data:`NO_LAYER` for none). Random maps lay
    grass over dry grass this way; without the layer the ground reads wrong."""
    w = int(world.fields.get(W_MAP_W, 0) or 0)
    h = int(world.fields.get(W_MAP_H, 0) or 0)
    tiles = world.fields.get(W_TILES) or []
    base = bytearray(w * h)
    layer = bytearray([NO_LAYER]) * (w * h)
    for i, t in enumerate(tiles[: w * h]):
        if isinstance(t, Node):
            base[i] = int(t.fields.get(TILE_TERRAIN, 0) or 0) & 0xFF
            # Some recordings omit layer0 on a fresh export; -1 is explicit.
            # Evidence: world-envelope/terrain-layer-rebuild/README.md.
            lt = t.fields.get(TILE_LAYER, 0)
            if lt is not None and 0 <= int(lt) < NO_LAYER:
                layer[i] = int(lt)
    return bytes(base + layer)


class TerrainTiles:
    """:func:`terrain_tiles`, re-reading only the tiles a patch reached since the
    last call (a patch marks every node it edits ``touched``; this clears the flag
    on map tiles, which nothing else reads). A different tile list or map size
    reads every tile again."""

    def __init__(self) -> None:
        self._tiles: list[Any] | None = None
        self._shape = (-1, -1, -1)
        self._buf = bytearray()

    def __call__(self, world: Node) -> bytes:
        w = int(world.fields.get(W_MAP_W, 0) or 0)
        h = int(world.fields.get(W_MAP_H, 0) or 0)
        tiles: list[Any] = world.fields.get(W_TILES) or []
        n = w * h
        if tiles is not self._tiles or self._shape != (w, h, len(tiles)):
            self._tiles, self._shape = tiles, (w, h, len(tiles))
            self._buf = bytearray(terrain_tiles(world))
            for t in tiles:
                if isinstance(t, Node):
                    t.touched = False
            return bytes(self._buf)
        buf = self._buf
        for i, t in enumerate(tiles[:n]):
            if not isinstance(t, Node):
                buf[i], buf[n + i] = 0, NO_LAYER
            elif t.touched:
                t.touched = False
                buf[i] = int(t.fields.get(TILE_TERRAIN, 0) or 0) & 0xFF
                lt = t.fields.get(TILE_LAYER, 0)
                buf[n + i] = int(lt) if lt is not None and 0 <= int(lt) < NO_LAYER else NO_LAYER
        return bytes(buf)


def tree_tiles(world: Node, cat: Catalog) -> tuple[bytes, list[int]]:
    """The forest layer: one byte per tile, 0 = no tree, else 1 + an index into
    the returned list of tree master ids (so the view can draw the right tree);
    then one byte per tile for the tree's facet, the variant of its sprite the
    game draws (a forest is not one tree repeated)."""
    w = int(world.fields.get(W_MAP_W, 0) or 0)
    h = int(world.fields.get(W_MAP_H, 0) or 0)
    out = bytearray(w * h)
    facets = bytearray(w * h)
    kinds: list[int] = []
    #: kind -> its index in ``kinds``
    kind_index: dict[int, int] = {}
    players = players_of(world)
    # Gaia's shared master (no private shadow: skipped) depends on the master id
    # alone: whether it is a tree is looked up once per id, not per tree.
    is_tree: dict[Any, bool] = {}
    for e in live_entities(world):
        f = e.fields
        if (f.get(E_OWNER) or 0) != 0 or isinstance(f.get(E_OWN_MASTER), Node):
            continue
        raw_mid = f.get(E_MASTER)
        tree = is_tree.get(raw_mid)
        if tree is None:
            info = cat.entity_master(e, players)
            tree = is_tree[raw_mid] = info is not None and info.cls == CLASS_TREE
        if not tree:
            continue
        mid = int(raw_mid or -1)
        x, y = int(f.get(E_X, 0.0) or 0.0), int(f.get(E_Y, 0.0) or 0.0)
        if 0 <= x < w and 0 <= y < h:
            k = kind_index.get(mid)
            if k is None:
                if len(kinds) >= 254:
                    continue
                k = kind_index[mid] = len(kinds)
                kinds.append(mid)
            out[y * w + x] = 1 + k
            facets[y * w + x] = int(f.get(E_FACET, 0) or 0) & 0xFF
    return bytes(out + facets), kinds


def resources_left(world: Node, cat: Catalog) -> dict[str, float]:
    """Natural resources remaining on the map (Gaia entities), by kind."""
    out = {"food": 0.0, "wood": 0.0, "gold": 0.0, "stone": 0.0, "relics": 0}
    players = players_of(world)
    # As in tree_tiles: a shared Gaia master is looked up once per id.
    shared: dict[Any, MasterInfo | None] = {}
    for e in live_entities(world):
        f = e.fields
        if int(f.get(E_OWNER, 0) or 0) != 0:
            continue
        if isinstance(f.get(E_OWN_MASTER), Node):
            info = cat.entity_master(e, players)
        else:
            raw_mid = f.get(E_MASTER)
            if raw_mid in shared:
                info = shared[raw_mid]
            else:
                info = shared[raw_mid] = cat.entity_master(e, players)
        if info is None:
            continue
        if info.cls in RELIC_CLASSES:
            out["relics"] += 1
            continue
        ht = f.get(E_HELD_TYPE, 0)
        if ht is not None and 0 <= ht < 4:
            out[RESOURCE_NAMES[ht]] += float(f.get(E_HELD_AMT, 0.0) or 0.0)
    return {k: round(v) for k, v in out.items()}
