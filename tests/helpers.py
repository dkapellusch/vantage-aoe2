"""Test helpers: an encoder for ``Frame.patch`` instructions and a small world.

The encoder is the inverse of :mod:`vantage.patch` and exists so tests
can build exact byte streams (forward and reverse) without a running game.
"""

from __future__ import annotations

import struct
import types
from typing import Any

from vantage import patch as P
from vantage.frames import Frame
from vantage.schema import SCHEMA

_FMT = {
    "Int8": "<b",
    "UInt8": "<B",
    "Boolean": "<B",
    "Int16": "<h",
    "UInt16": "<H",
    "Int32": "<i",
    "UInt32": "<I",
    "Int64": "<q",
    "UInt64": "<Q",
    "Float": "<f",
}


Unit = tuple[bytes, bytes]  # (forward layout, backward layout) of one operand


def enc(wire: str, value: Any) -> Unit:
    """One operand. A string is length-then-bytes forward, bytes-then-length backward."""
    if wire == "String":
        raw = value.encode()
        n = struct.pack("<I", len(raw))
        return (n + raw, raw + n)
    b = struct.pack(_FMT[wire], int(value) if wire == "Boolean" else value)
    return (b, b)


def u8(v: int) -> Unit:
    return (bytes([v]), bytes([v]))


def i32(v: int) -> Unit:
    b = struct.pack("<i", v)
    return (b, b)


class PatchBuilder:
    """Collects instructions; ``forward()``/``backward()`` serialise them."""

    def __init__(self) -> None:
        self.instrs: list[list[Unit]] = []

    def _op(self, op: int, *units: Unit) -> PatchBuilder:
        self.instrs.append([u8(op), *units])
        return self

    def pop(self) -> PatchBuilder:
        return self._op(P.POP)

    def assign(self, fid: int, wire: str, value: Any) -> PatchBuilder:
        return self._op(P.ASSIGN_FIELD, u8(fid), enc(wire, value))

    def push(self, fid: int) -> PatchBuilder:
        return self._op(P.PUSH_FIELD, u8(fid))

    def create(self, fid: int, model: int) -> PatchBuilder:
        return self._op(P.PUSH_CREATE_FIELD, u8(fid), u8(model))

    def reset(self, fid: int) -> PatchBuilder:
        return self._op(P.RESET_FIELD, u8(fid))

    def assign_key(self, fid: int, key: int, wire: str, value: Any) -> PatchBuilder:
        return self._op(P.ASSIGN_KEY, u8(fid), i32(key), enc(wire, value))

    def push_key(self, fid: int, key: int) -> PatchBuilder:
        return self._op(P.PUSH_KEY, u8(fid), i32(key))

    def create_key(self, fid: int, model: int, key: int) -> PatchBuilder:
        return self._op(P.PUSH_CREATE_KEY, u8(fid), u8(model), i32(key))

    def reset_key(self, fid: int, key: int) -> PatchBuilder:
        return self._op(P.RESET_KEY, u8(fid), i32(key))

    def insert(self, fid: int, idx: int, wire: str, value: Any) -> PatchBuilder:
        return self._op(P.INSERT, u8(fid), i32(idx), enc(wire, value))

    def create_insert(self, fid: int, model: int, idx: int) -> PatchBuilder:
        return self._op(P.PUSH_CREATE_INSERT, u8(fid), u8(model), i32(idx))

    def remove(self, fid: int, idx: int) -> PatchBuilder:
        return self._op(P.REMOVE, u8(fid), i32(idx))

    def swap(self, fid: int, a: int, b: int) -> PatchBuilder:
        return self._op(P.SWAP, u8(fid), i32(a), i32(b))

    def resize(self, fid: int, n: int) -> PatchBuilder:
        return self._op(P.RESIZE, u8(fid), i32(n))

    def forward(self) -> bytes:
        return b"".join(u[0] for ins in self.instrs for u in ins)

    def backward(self) -> bytes:
        """Reverse encoding: marker byte, then instructions last-first, each laid
        out so a back-to-front reader meets opcode, fid, operands in order."""
        out = [b"\x00"]
        for ins in reversed(self.instrs):
            out.extend(u[1] for u in reversed(ins))
        return b"".join(out)


# -- a small but complete world ----------------------------------------------------

M = SCHEMA.model_id
F = SCHEMA.fid


def fid(model: str, name: str) -> int:
    return F(M(model), name)


VILLAGER = 83
LUMBERJACK = 123
HERDER = 1880  # not in the static task table: classified by name
KNIGHT = 38
TOWN_CENTER = 109
SHEEP = 594
GOLD_MINE = 66
KING = 434
MONK = 125
HOUSE = 70
BRIDGE = 602
MONUMENT = 826
TREASON = 461
HERESY = 439
#: Each player's victory-point map: (group, current points); group 0 omitted.
VP_ENTRIES = ((0, 10), (1, 20), (3, 5), (5, 1))


def _master(
    b: PatchBuilder,
    mid: int,
    mtype: int,
    cls: int,
    string_id: int,
    hp: int,
    icon: int,
    model: str = "MasterCombatEntity",
    train: int = 0,
    cost: tuple[tuple[int, float], ...] = (),
) -> None:
    b.create_key(fid("Player", "masterEntities"), M(model), mid)
    b.assign(fid("MasterEntity", "id"), "Int16", mid)
    b.assign(fid("MasterEntity", "type"), "UInt8", mtype)
    b.assign(fid("MasterEntity", "objectGroup"), "Int16", cls)
    b.assign(fid("MasterEntity", "stringId"), "Int32", string_id)
    b.assign(fid("MasterEntity", "hp"), "Int16", hp)
    b.assign(fid("MasterEntity", "buttonPict"), "Int16", icon)
    if train:
        b.assign(fid("MasterCombatEntity", "buildPtsRequired"), "Int16", train)
    for i, (rtype, amount) in enumerate(cost):
        b.create_insert(fid("MasterCombatEntity", "buildInventory"), M("AttributeValue"), i)
        if rtype:
            b.assign(fid("AttributeValue", "type"), "Int16", rtype)
        b.assign(fid("AttributeValue", "amount"), "Float", amount)
        b.assign(fid("AttributeValue", "flag"), "UInt8", 1)
        b.pop()
    b.pop()


def _entity(
    b: PatchBuilder,
    eid: int,
    mid: int,
    owner: int,
    x: float,
    y: float,
    model: str = "CombatEntity",
    hp: float = 25.0,
    state: int = 2,
    action: bool = True,
    built: bool = True,
) -> None:
    b.create_key(fid("World", "entities"), M(model), eid)
    b.assign(fid("Entity", "id"), "Int32", eid)
    b.assign(fid("Entity", "masterId"), "Int16", mid)
    if owner:
        b.assign(fid("Entity", "ownerId"), "Int8", owner)
    b.assign(fid("Entity", "worldX"), "Float", x)
    b.assign(fid("Entity", "worldY"), "Float", y)
    b.assign(fid("Entity", "state"), "UInt8", state)
    b.assign(fid("Entity", "hp"), "Float", hp)
    b.assign(fid("Entity", "insideObjId"), "Int32", 0 if eid % 2 else -1)  # both mean "outside"
    if model == "BuildingEntity" and built:
        b.assign(fid("BuildingEntity", "built"), "Boolean", True)
    if action and model in ("CombatEntity", "ActionEntity"):
        b.create(fid("ActionEntity", "currentAction"), M("GatherAction"))
        b.assign(fid("Action", "type"), "Int16", 110)
        if mid == HERDER:
            b.assign(fid("Action", "state"), "UInt8", 7)  # working
        b.pop()
    b.pop()


def snapshot_frame(t: int = 0) -> Frame:
    """A full-state frame: map, two players, technologies, entities, options."""
    return Frame(time=t, patch=snapshot_builder(t).forward())


def snapshot_builder(t: int = 0) -> PatchBuilder:
    b = PatchBuilder()
    b.create(fid("Root", "world"), M("World"))
    b.assign(fid("World", "time"), "UInt32", t)
    b.assign(fid("World", "mapWidth"), "Int32", 4)
    b.assign(fid("World", "mapHeight"), "Int32", 4)
    b.resize(fid("World", "terrainTypes"), 0)
    b.create_insert(fid("World", "terrainTypes"), M("TerrainType"), 0)
    b.assign(fid("TerrainType", "mapFlatColor"), "UInt8", 7)
    b.pop()
    b.resize(fid("World", "mapTiles"), 16)
    b.push_key(fid("World", "mapTiles"), 5)
    b.assign(fid("MapTile", "elevLevel"), "UInt8", 2)
    b.pop()
    b.resize(fid("World", "unifiedVisibleMap"), 16)
    for i in range(16):
        # player 1 sees tiles 0-7, everyone explored everything; bit 15 is always set
        vis = (1 << 1) if i < 8 else 0
        b.assign_key(
            fid("World", "unifiedVisibleMap"), i, "UInt32", 0x80008000 | vis | (0b110 << 16)
        )
    for tid, name, ttr in (
        (101, "Feudal Age", 130),
        (22, "Loom", 25),
        (TREASON, "Treason", 1),
        (HERESY, "Heresy", 60),
    ):
        b.create_key(fid("World", "technologies"), M("Technology"), tid)
        b.assign(fid("Technology", "name"), "String", name)
        b.assign(fid("Technology", "timeToResearch"), "Int16", ttr)
        b.assign(fid("Technology", "icon"), "Int16", 30 if tid == 101 else 6)
        b.pop()
    for pid in (0, 1, 2):
        b.create_key(fid("World", "players"), M("Player"), pid)
        if pid:
            b.assign(fid("Player", "id"), "Int8", pid)
        b.assign(fid("Player", "name"), "String", ["Gaia", "Alice", "Bob"][pid])
        if pid:
            b.assign(fid("Player", "civId"), "UInt32", pid)
            if pid > 1:  # zero (blue) is omitted, like the game does
                b.assign(fid("Player", "colorIdChosen"), "Int32", pid - 1)
            b.assign(fid("Player", "colorIdCurrent"), "Int32", 1)  # recorder view: ignored
        b.create(fid("Player", "attributes"), M("PlayerAttributes"))
        for name, v in (
            ("food", 200.0),
            ("wood", 150.0),
            ("stone", 100.0),
            ("gold", 0.0),
            ("population", 4.0),
            ("maxPop", 1.0),
            ("currentEra", 0.0),
        ):
            if pid and v:
                b.assign(F(M("PlayerAttributes"), name), "Float", v)
        b.pop()
        if pid:
            b.resize(fid("Player", "relations"), 3)
            for other in range(3):
                b.create_key(fid("Player", "relations"), M("Relation"), other)
                if other not in (0, pid):
                    b.assign(fid("Relation", "enumValue"), "UInt8", 3)  # enemy
                b.pop()
            b.create_key(fid("Player", "researchStates"), M("ResearchState"), 22)
            b.assign(fid("ResearchState", "state"), "Int16", 3)
            b.pop()
            b.create_key(fid("Player", "researchStates"), M("ResearchState"), 101)
            b.assign(fid("ResearchState", "state"), "Int16", 1)
            b.pop()
            _master(b, VILLAGER, 70, 4, 5121, 25, 15, train=25, cost=((0, 50.0),))
            _master(b, LUMBERJACK, 70, 4, 5122, 25, 15)
            _master(b, HERDER, 70, 4, 9999, 25, 15)
            _master(b, KNIGHT, 70, 12, 5132, 100, 30, train=30, cost=((0, 60.0), (3, 75.0)))
            _master(b, TOWN_CENTER, 80, 3, 5164, 2400, 28, model="MasterBuildingEntity")
            _master(b, SHEEP, 70, 58, 5498, 7, 1)
            _master(b, KING, 70, 59, 5300, 75, 40, cost=((3, 50.0),))
            _master(b, MONK, 70, 18, 5301, 30, 41, train=51, cost=((3, 100.0),))
            _master(b, HOUSE, 80, 3, 5302, 550, 42, model="MasterBuildingEntity", train=25)
            b.create_key(fid("Player", "victoryPointMap"), M("VictoryPointEntry"), 0)
            b.pop()
            for i, (group, points) in enumerate(VP_ENTRIES, 1):
                b.create_key(fid("Player", "victoryPointMap"), M("VictoryPointEntry"), i)
                if group:
                    b.assign(fid("VictoryPointEntry", "group"), "Int32", group)
                b.assign(fid("VictoryPointEntry", "currPoints"), "Int32", points)
                b.pop()
            b.assign(fid("Player", "victoryPoints"), "Int32", sum(p for _, p in VP_ENTRIES))
        else:
            _master(b, GOLD_MINE, 30, 32, 5167, 1, 0, model="MasterEntity")
            _master(b, 411, 10, 15, 5171, 30, 0, model="MasterEntity")
            _master(b, BRIDGE, 80, 3, 5400, 1000, 0, model="MasterBuildingEntity")
            _master(b, MONUMENT, 80, 3, 5401, 3000, 0, model="MasterBuildingEntity")
        b.pop()
    _entity(b, 100, TOWN_CENTER, 1, 1.0, 1.0, model="BuildingEntity", hp=2400.0, action=False)
    _entity(b, 101, VILLAGER, 1, 1.5, 1.5, action=False)  # idle
    _entity(b, 102, LUMBERJACK, 1, 2.0, 1.0)
    _entity(b, 103, HERDER, 1, 2.0, 2.0)
    _entity(b, 104, KNIGHT, 2, 3.0, 3.0, hp=100.0)
    _entity(b, 105, GOLD_MINE, 0, 0.5, 3.5, model="Entity", hp=1.0, state=3, action=False)
    _entity(b, 106, 411, 0, 3.5, 0.5, model="Entity", hp=30.0, state=3, action=False)
    _entity(b, 107, VILLAGER, 1, 2.5, 2.5, model="DoppleEntity", action=False)
    _entity(b, 108, VILLAGER, 1, 1.0, 1.0, action=False)
    b.push_key(fid("World", "entities"), 108).assign(
        fid("Entity", "insideObjId"), "Int32", 100
    ).pop()
    b.resize(fid("World", "particleInstances"), 1)
    b.create_key(fid("World", "particleInstances"), M("ParticleInstance"), 0)
    for name, wire, value in (
        ("active", "Boolean", True),
        ("spriteUsed", "Boolean", True),
        ("spriteId", "Int16", 7),
        ("spritePositionX", "Float", 2.0),
        ("spritePositionY", "Float", 3.0),
        ("spriteDuration", "Float", 2.0),
        ("spriteAge", "Float", 1.0),
        ("spriteAlphaStart", "Float", 1.0),
        ("spriteAlphaEnd", "Float", 0.5),
        ("spriteFadeAlpha", "Float", 1.0),
    ):
        b.assign(fid("ParticleInstance", name), wire, value)
    b.pop()
    b.pop()  # world
    # gold mine resource amount; held type 3 (gold)
    b2 = PatchBuilder().push(fid("Root", "world")).push_key(fid("World", "entities"), 105)
    b2.assign(fid("Entity", "heldAttributeType"), "Int16", 3)
    b2.assign(fid("Entity", "heldAttributeAmount"), "Float", 800.0).pop().pop()
    b.instrs.extend(b2.instrs)
    b.create(fid("Root", "gameOptions"), M("GameOptions"))
    b.assign(fid("GameOptions", "customRandomMapFile"), "String", "C:\\maps\\Arabia.rms")
    b.assign(fid("GameOptions", "gameSpeed"), "Float", 1.7)
    for i, (team, elo) in enumerate(((2, 1200), (3, 1150))):
        b.create_insert(fid("GameOptions", "playerInfo"), M("PlayerGameOptions"), i)
        b.assign(fid("PlayerGameOptions", "resolvedTeamId"), "Int8", team)
        b.assign(fid("PlayerGameOptions", "playerRmElo"), "Int32", elo)
        b.assign(fid("PlayerGameOptions", "worldPlayerIndexIncludingGaia"), "Int8", i + 1)
        b.pop()
    b.pop()
    return b


def delta(t: int, *steps: Any) -> PatchBuilder:
    """A delta frame body that sets the world time, plus caller steps."""
    b = PatchBuilder().push(fid("Root", "world")).assign(fid("World", "time"), "UInt32", t)
    for step in steps:
        step(b)
    return b.pop()


def set_attr(pid: int, name: str, value: float) -> Any:
    def step(b: PatchBuilder) -> None:
        b.push_key(fid("World", "players"), pid).push(fid("Player", "attributes"))
        b.assign(F(M("PlayerAttributes"), name), "Float", value).pop().pop()

    return step


def spawn(
    eid: int, mid: int, owner: int, x: float, y: float, model: str = "CombatEntity", **kw: Any
) -> Any:
    """Add an entity (``_entity`` keyword options) in a delta."""

    def step(b: PatchBuilder) -> None:
        sub = PatchBuilder()
        _entity(sub, eid, mid, owner, x, y, model=model, **kw)
        b.instrs.extend(sub.instrs)

    return step


def set_entity(eid: int, model: str, name: str, wire: str, value: Any) -> Any:
    """Assign one field of an entity."""

    def step(b: PatchBuilder) -> None:
        b.push_key(fid("World", "entities"), eid).assign(fid(model, name), wire, value).pop()

    return step


def set_master(pid: int, mid: int, model: str, name: str, wire: str, value: Any) -> Any:
    """Assign one field of a player's own master (an upgrade)."""

    def step(b: PatchBuilder) -> None:
        b.push_key(fid("World", "players"), pid).push_key(fid("Player", "masterEntities"), mid)
        b.assign(fid(model, name), wire, value).pop().pop()

    return step


def set_master_cost(pid: int, mid: int, cost: tuple[tuple[int, float], ...]) -> Any:
    """Replace a player's master cost (a civilisation discount)."""

    def step(b: PatchBuilder) -> None:
        b.push_key(fid("World", "players"), pid).push_key(fid("Player", "masterEntities"), mid)
        b.resize(fid("MasterCombatEntity", "buildInventory"), 0)
        for i, (rtype, amount) in enumerate(cost):
            b.create_insert(fid("MasterCombatEntity", "buildInventory"), M("AttributeValue"), i)
            if rtype:
                b.assign(fid("AttributeValue", "type"), "Int16", rtype)
            b.assign(fid("AttributeValue", "amount"), "Float", amount)
            b.pop()
        b.pop().pop()

    return step


def set_treaty(left: int, total: int) -> Any:
    """Create/update the world's truce (treaty / D3 mode) state."""

    def step(b: PatchBuilder) -> None:
        b.create(fid("World", "treatyMode"), M("TreatyMode"))
        b.assign(fid("TreatyMode", "timeLeftInSeconds"), "Int32", left)
        b.assign(fid("TreatyMode", "treatyTimeInSeconds"), "Int32", total)
        b.pop()

    return step


def set_world(name: str, wire: str, value: Any) -> Any:
    def step(b: PatchBuilder) -> None:
        b.assign(fid("World", name), wire, value)

    return step


def set_research(pid: int, tech: int, state: int = 3) -> Any:
    def step(b: PatchBuilder) -> None:
        b.push_key(fid("World", "players"), pid)
        b.create_key(fid("Player", "researchStates"), M("ResearchState"), tech)
        b.assign(fid("ResearchState", "state"), "Int16", state).pop().pop()

    return step


def kill_entity(eid: int) -> Any:
    def step(b: PatchBuilder) -> None:
        b.reset_key(fid("World", "entities"), eid)

    return step


def produce(eid: int, unit: int, work: float, queued: int) -> Any:
    def step(b: PatchBuilder) -> None:
        b.push_key(fid("World", "entities"), eid)
        b.create(fid("BuildingEntity", "currentProductionQueueAction"), M("MakeObjectAction"))
        b.assign(fid("MakeObjectAction", "objId"), "Int16", unit)
        b.assign(fid("MakeObjectAction", "workDone"), "Float", work)
        b.pop()
        b.resize(fid("BuildingEntity", "productionQueue"), 1)
        b.create_key(fid("BuildingEntity", "productionQueue"), M("ProductionQueueRecord"), 0)
        b.assign(fid("ProductionQueueRecord", "unitId"), "Int16", unit)
        b.assign(fid("ProductionQueueRecord", "techId"), "Int16", -1)
        b.assign(fid("ProductionQueueRecord", "unitCount"), "Int16", queued)
        b.pop().pop()

    return step


def game_frames(seconds: int = 12) -> list[Frame]:
    """Snapshot at t=0, then one delta per 500 ms with a little happening."""
    frames = [snapshot_frame(0)]
    for i in range(1, seconds * 2 + 1):
        t = i * 500
        steps: list[Any] = [set_attr(1, "food", 200.0 - i)]
        events: list[dict[str, Any]] = []
        commands: list[dict[str, Any]] = []
        if t == 2000:
            steps.append(produce(100, VILLAGER, 12.5, 2))
        if t == 3000:
            events.append(
                {"kind": "damage", "entityid": 102, "attackerid": 104, "iskillingblow": True}
            )
            steps.append(kill_entity(102))
        if t == 4000:
            steps.append(set_attr(1, "currentEra", 1.0))
            events.append(
                {"kind": "notificationresearchdone", "ownerid": 1, "techid": 101, "buildingid": 100}
            )
        if t == 5000:
            events.append({"kind": "playerchat", "playerid": 2, "text": "gg", "channel": 1})
            events.append(
                {
                    "kind": "tribute",
                    "senderid": 1,
                    "receiverid": 2,
                    "attributetype": 3,
                    "sendervaluechange": -125.0,
                    "receivervaluechange": 100.0,
                }
            )
            events.append(
                {
                    "kind": "markettransaction",
                    "playerid": 2,
                    "attributetype": 1,
                    "attributeexchanged": 100.0,
                    "goldexchanged": -110.0,
                }
            )
        if t % 1000 == 0:
            commands.append({"kind": "move", "commplayerid": 2})
            commands.append({"kind": "work", "commplayerid": 1})
            commands.append({"kind": "game"})  # bookkeeping: never counted
        frames.append(
            Frame(time=t, patch=delta(t, *steps).forward(), events=events, commands=commands)
        )
    return frames


def set_player(pid: int, name: str, wire: str, value: Any) -> Any:
    """Assign one scalar field of a player."""

    def step(b: PatchBuilder) -> None:
        b.push_key(fid("World", "players"), pid).assign(fid("Player", name), wire, value).pop()

    return step


def set_vp(pid: int, entry: int, points: int, amount: float | None = None) -> Any:
    """Add (or update) a ``victoryPointMap`` entry keyed by its id."""

    def step(b: PatchBuilder) -> None:
        b.push_key(fid("World", "players"), pid)
        b.create_key(fid("Player", "victoryPointMap"), M("VictoryPointEntry"), entry)
        b.assign(fid("VictoryPointEntry", "id"), "UInt8", entry)
        b.assign(fid("VictoryPointEntry", "currPoints"), "Int32", points)
        if amount is not None:
            b.assign(fid("VictoryPointEntry", "currAttributeAmount"), "Float", amount)
        b.pop().pop()

    return step


def set_relation(pid: int, other: int, unit_diplomacy: int) -> Any:
    """Set ``Player.relations[other].unitDiplomacy`` (2 ally, 3 neutral, 4 enemy)."""

    def step(b: PatchBuilder) -> None:
        b.push_key(fid("World", "players"), pid).push_key(fid("Player", "relations"), other)
        b.assign(fid("Relation", "unitDiplomacy"), "Int32", unit_diplomacy).pop().pop()

    return step


class _RegKey:
    def __init__(self, hive: int, path: str) -> None:
        self.hive, self.path = hive, path

    def __enter__(self) -> _RegKey:
        return self

    def __exit__(self, *exc: object) -> None:
        pass


class FakeWinreg(types.ModuleType):
    """An in-memory stand-in for ``winreg`` (install it in ``sys.modules``):
    keys are ``(hive, lower-cased path)``, each a ``{value name: value}``."""

    HKEY_CURRENT_USER = 1
    HKEY_LOCAL_MACHINE = 2
    REG_SZ = 1

    def __init__(self) -> None:
        super().__init__("winreg")
        self.keys: dict[tuple[int, str], dict[str, object]] = {}

    def set(self, hive: int, path: str, name: str, value: object) -> None:
        with self.CreateKey(hive, path) as k:
            self.keys[(hive, k.path)][name] = value

    def get(self, hive: int, path: str, name: str = "") -> object | None:
        return self.keys.get((hive, path.lower()), {}).get(name)

    def OpenKey(self, hive: int, path: str) -> _RegKey:
        if (hive, path.lower()) not in self.keys:
            raise FileNotFoundError(path)
        return _RegKey(hive, path.lower())

    def CreateKey(self, hive: int, path: str) -> _RegKey:
        parts = path.lower().split("\\")
        for i in range(1, len(parts) + 1):
            self.keys.setdefault((hive, "\\".join(parts[:i])), {})
        return _RegKey(hive, path.lower())

    def QueryValueEx(self, key: _RegKey, name: str) -> tuple[object, int]:
        values = self.keys[(key.hive, key.path)]
        if name not in values:
            raise FileNotFoundError(name)
        return values[name], self.REG_SZ

    def SetValueEx(self, key: _RegKey, name: str, _: int, kind: int, value: object) -> None:
        self.keys[(key.hive, key.path)][name] = value

    def DeleteKey(self, hive: int, path: str) -> None:
        p = path.lower()
        if (hive, p) not in self.keys:
            raise FileNotFoundError(path)
        if any(h == hive and k.startswith(p + "\\") for h, k in self.keys):
            raise PermissionError(path)  # winreg deletes only keys without subkeys
        del self.keys[(hive, p)]
