"""vantage.timeline: keyframes, series, events and summaries."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tests.helpers import (
    HERESY,
    KING,
    KNIGHT,
    LUMBERJACK,
    VILLAGER,
    M,
    delta,
    game_frames,
    kill_entity,
    produce,
    set_attr,
    set_entity,
    set_master,
    set_player,
    set_relation,
    set_research,
    set_treaty,
    set_vp,
    set_world,
    snapshot_frame,
    spawn,
)
from vantage.frames import Frame, RecordingWriter
from vantage.gamedata import GameData
from vantage.timeline import KEYFRAME_MS, Timeline, load_recording


def _timeline() -> Timeline:
    tl = Timeline(GameData(None))
    tl.feed_all(game_frames(12))
    return tl


def test_keyframes_and_seek() -> None:
    tl = _timeline()
    st = tl.status()
    assert st["complete"] and st["errors"] == 0 and not st["desynced"]
    assert [k.time for k in tl.keyframes][:3] == [0, 1000, 2000]
    assert tl.start == 0 and tl.end == 12000
    v = tl.view_at(4300)
    assert v is not None and v["time"] == 4000
    assert v["players"]["1"]["resources"]["food"] == 192.0
    assert v["players"]["1"]["age"] == 1
    assert "fog" in v and "trees_t" in v
    assert tl.view_at(None)["time"] == 12000  # type: ignore[index]
    assert tl.view_at(-5)["time"] == 0  # type: ignore[index]
    assert tl.trees_at(0) is not None


def test_events_are_resolved_before_the_dead_are_removed() -> None:
    tl = _timeline()
    kinds = [e["kind"] for e in tl.events]
    assert kinds == ["kill", "researched", "age_up", "chat", "tribute", "buy"]
    kill = tl.events[0]
    assert kill["victim"]["master"] == LUMBERJACK and kill["victim"]["owner"] == 1
    assert kill["killer"]["master"] == KNIGHT and kill["player"] == 2
    assert kill["victim"]["eco"] is True
    researched = tl.events[1]
    assert researched["cat"] == "age" and researched["tech"] == 101
    tribute = tl.events[4]
    assert (tribute["to"], tribute["resource"], tribute["amount"]) == (2, "gold", 100)
    assert (tribute["tax"], tribute["sent"]) == (25, 125)
    assert tl.events[5]["gold"] == 110
    assert tl.events_between(3500, 4500) == tl.events[1:3]
    knight = tl.unit_stats(104)
    assert (knight["kills"], knight["eco_kills"], knight["died"]) == (1.0, 1.0, 0.0)
    assert knight["activity"] == {"moving": 12.0}  # its action is a plain gather (state 0)
    herder = tl.unit_stats(103)
    assert herder["activity"] == {"gather_food": 12.0} and herder["activity_lm"] == {
        "gather_food": 12.0
    }
    assert tl.unit_stats(102)["died"] == 1.0
    assert tl.unit_stats(104, t=1000)["kills"] == 0.0


def test_series_apm_and_summary() -> None:
    tl = _timeline()
    rows = tl.series["1"]
    assert [r["t"] for r in rows] == [0, 5000, 10000]
    assert rows[-1]["villagers"] == 3 and rows[-1]["deaths"] == 0
    assert tl.series["0"][0]["gold"] == 800
    v = tl.view_at(None)
    assert v is not None
    # The same "work" order every second is spam: effective APM counts it once.
    assert v["apm"]["1"] == {
        "total": 12,
        "eco": 12,
        "military": 0,
        "effective": 1,
        "effective_eco": 1,
        "effective_military": 0,
    }
    assert v["apm"]["2"]["military"] == 12
    summary = tl.summary()
    assert set(summary) == {"1", "2", "teams_most_created"}
    assert summary["1"]["age_times"] == {"1": 4000}
    assert summary["2"]["most_created"] == []


def test_snapshot_resyncs_and_desync_stops_ingestion() -> None:
    tl = Timeline(GameData(None))
    tl.feed(Frame(time=0, patch=b"\x03\x00\x01"))  # delta before any snapshot: missing object
    assert tl.desynced and tl.errors == 1
    tl.feed(Frame(time=10, patch=delta(10).forward()))
    assert tl.frames == 0  # ignored until a snapshot arrives
    for f in game_frames(2):
        tl.feed(f)
    assert not tl.desynced and tl.frames == 5


def test_wait_change_and_recording(tmp_path: Path) -> None:
    tl = Timeline(GameData(None))
    v0 = tl.version
    for f in game_frames(1):
        tl.feed(f)
    assert tl.wait_change(v0, 0.01) > v0
    path = tmp_path / "g.vrec"
    with RecordingWriter(path) as w:
        for f in game_frames(3):
            w.write(f)
        w.write(Frame(time=3500, patch=delta(3500, set_attr(2, "wood", 1.0)).forward()))
    seen: list[int] = []
    loaded = load_recording(str(path), GameData(None), progress=lambda t: seen.append(t.frames))
    assert loaded.complete and loaded.end == 3500 and seen == [1]
    assert loaded.view_at(None)["players"]["2"]["resources"]["wood"] == 1.0  # type: ignore[index]
    assert KEYFRAME_MS == 1000


def test_diplomacy_change_is_an_event() -> None:
    from tests.helpers import M, PatchBuilder, fid

    tl = Timeline(GameData(None))
    for f in game_frames(2):
        tl.feed(f)
    b = PatchBuilder().push(fid("Root", "world")).assign(fid("World", "time"), "UInt32", 2000)
    b.push_key(fid("World", "players"), 1).push_key(fid("Player", "relations"), 2)
    b.assign(fid("Relation", "enumValue"), "UInt8", 0).pop().pop().pop()
    tl.feed(Frame(time=2000, patch=b.forward()))
    tl.feed(Frame(time=3000, patch=delta(3000).forward()))
    dip = [e for e in tl.events if e["kind"] == "diplomacy"]
    assert dip == [
        {
            "t": 3000,
            "cat": "diplomacy",
            "kind": "diplomacy",
            "player": 1,
            "to": 2,
            "stance": "ally",
            "previous": "enemy",
        }
    ]
    assert M("Relation") > 0


# -- events, statistics and rules --------------------------------------------------


def _feed(
    tl: Timeline, t: int, *steps: Any, events: Any = (), commands: Any = (), more: Any = ()
) -> None:
    patch = delta(t, *steps, *more).forward()
    tl.feed(Frame(time=t, patch=patch, events=list(events), commands=list(commands)))


def _start(**kw: Any) -> Timeline:
    tl = Timeline(GameData(None), **kw)
    tl.feed(snapshot_frame(0))
    return tl


def test_fog_and_exploration_read_every_tile_at_once() -> None:
    """The whole-map bit operations give what the per-tile loop gives (the loop
    stays for a map that is not plain UInt32s)."""
    import random
    import zlib

    from vantage import timeline as T
    from vantage import world as W
    from vantage.patch import Node
    from vantage.schema import SCHEMA

    rng = random.Random(7)
    for n in (0, 1, 5, 1000):
        vm = [rng.getrandbits(32) for _ in range(n)]
        fast = Node(SCHEMA.model_id("World"), {W.W_VISIBLE: vm})
        loop = Node(SCHEMA.model_id("World"), {W.W_VISIBLE: [float(v) for v in vm]})
        assert zlib.decompress(T._fog_blob(fast)) == zlib.decompress(T._fog_blob(loop))
        assert T._exploration(fast) == T._exploration(loop)
    # Tile 0: player 2 sees it (bit 2), players 1 and 3 explored it (bits 17, 19);
    # in the fog bytes bit n-1 is player n.
    world = Node(SCHEMA.model_id("World"), {W.W_VISIBLE: [(1 << 2) | (1 << 17) | (1 << 19), 0]})
    assert zlib.decompress(T._fog_blob(world)) == bytes([0b10, 0b101, 0, 0])
    explored = T._exploration(world)
    assert (explored[1], explored[3]) == (50.0, 50.0)
    assert {p for p, pct in explored.items() if pct} == {1, 3} and len(explored) == 8


def test_ingestion_settles_the_heap_every_few_keyframes(monkeypatch: Any) -> None:
    from vantage import timeline as T

    calls: list[int] = []
    monkeypatch.setattr(T, "settle_heap", lambda: calls.append(1))
    tl = _start()
    for k in range(1, 2 * T.SETTLE_KEYFRAMES + 2):
        _feed(tl, k * KEYFRAME_MS)
    assert len(tl.keyframes) >= 2 * T.SETTLE_KEYFRAMES
    assert len(calls) == len(tl.keyframes) // T.SETTLE_KEYFRAMES


def test_effective_apm_drops_repeated_unit_orders_only() -> None:
    tl = _start()
    order = {"kind": "move", "commplayerid": 2, "unitids": [104], "location": {"x": 3.2, "y": 3.9}}
    same_tile = {**order, "location": {"x": 3.8, "y": 3.1}, "unitids": [104]}
    queue = {"kind": "multiqueue", "playerid": 2, "trainid": 83, "buildingids": [100]}
    _feed(tl, 500, commands=[order, same_tile, queue, queue])  # 1 order spam, 2 real queues
    _feed(tl, 3000, commands=[order])  # 2.5 s later: counts again
    _feed(tl, 4000, commands=[{**order, "unitids": [105]}])  # other units: counts
    apm = tl.view_at(None)["apm"]["2"]  # type: ignore[index]
    assert apm["total"] == 6 and apm["effective"] == 5
    v = tl.view_at(None)
    assert v is not None and v["players"]["2"]["eapm"] == 5 and v["players"]["2"]["apm_peak"] == 6


def test_kill_conversion_market_tribute_and_chat_details() -> None:
    from vantage.timeline import chat_recipients

    tl = _start()
    _feed(
        tl,
        500,
        events=[
            # player 2 kills its own knight's neighbour? no: a friendly kill of its own unit
            {"kind": "damage", "entityid": 104, "attackerid": 104, "damage": 5.0},
            {"kind": "damage", "entityid": 102, "attackerid": 104, "damage": 25.0,
             "iskillingblow": True},
            {"kind": "monkconversion", "monkid": 104, "monkownerid": 2, "targetid": 101,
             "targetownerid": 1},
            {"kind": "markettransaction", "playerid": 1, "attributetype": 1,
             "attributeexchanged": -100.0, "goldexchanged": 81.0},
            {"kind": "markettransaction", "playerid": 1, "attributeexchanged": 100.0,
             "goldexchanged": -120.0},
            {"kind": "tribute", "senderid": 1, "receiverid": 2, "attributetype": 3,
             "sendervaluechange": -50.0},
            {"kind": "playerchat", "playerid": 1, "text": "psst", "destinationmap": 0b100},
        ],
        more=[kill_entity(102)],
    )  # fmt: skip
    _feed(tl, 1000)
    kill = next(e for e in tl.events if e["kind"] == "kill")
    assert kill["friendly"] is False and kill["victim"]["eco"]
    conv = next(e for e in tl.events if e["kind"] == "conversion")
    assert conv["converter"] == 104 and conv["heresy"] is False
    chat = next(e for e in tl.events if e["kind"] == "chat")
    assert chat["to"] == [2] and chat_recipients(None) == []
    v = tl.view_at(None)
    assert v is not None
    alice, bob = v["players"]["1"], v["players"]["2"]
    assert (bob["eco_kills"], alice["eco_deaths"]) == (1, 1)
    assert (alice["market_sold"], alice["market_gold_gained"]) == (100, 81)
    assert (alice["market_bought"], alice["market_gold_spent"]) == (100, 120)
    assert alice["tribute_sent"] == 50
    knight = tl.unit_stats(104)
    assert knight["monk"] == {"conversions": 1, "eco": 1, "heresy": 0}
    assert knight["damage_by_target"] == {str(KNIGHT): 5.0, str(LUMBERJACK): 25.0}
    assert knight["damage_by_attacker"] == {str(KNIGHT): 5.0}
    assert knight["owner"] == 2 and knight["hp"] == 100 and knight["cost"]["gold"] == 75.0


def test_friendly_kills_are_flagged_and_not_counted() -> None:
    tl = _start()
    _feed(
        tl,
        500,
        events=[{"kind": "damage", "entityid": 101, "attackerid": 102, "damage": 25.0,
                 "iskillingblow": True}],
        more=[kill_entity(101)],
    )  # fmt: skip
    kill = next(e for e in tl.events if e["kind"] == "kill")
    assert kill["friendly"] is True
    s = tl.unit_stats(102)
    assert s["friendly_kills"] == 1 and s["kills"] == 0.0


def test_unit_stats_follow_the_owners_upgrades_over_time() -> None:
    tl = _start()
    _feed(tl, 1000)
    _feed(tl, 2000, set_master(2, KNIGHT, "MasterEntity", "hp", "Int16", 120))
    _feed(tl, 3000)
    assert tl.unit_stats(104, t=1500)["hp"] == 100
    assert tl.unit_stats(104)["hp"] == 120
    assert tl.master_stats(2, KNIGHT, 0)["hp"] == 100  # type: ignore[index]
    assert len(tl.master_log[(2, KNIGHT)]) == 2  # logged only on change
    # A selection of many: per-type numbers as the owner had them then.
    assert tl.group_stats([104], t=1500)["types"][f"2:{KNIGHT}"]["hp"] == 100
    group = tl.group_stats([104, 104_000])  # an unknown id adds nothing
    assert group["types"] == {f"2:{KNIGHT}": group["types"][f"2:{KNIGHT}"]}
    assert group["types"][f"2:{KNIGHT}"]["hp"] == 120 and group["totals"]["kills"] == 0


def test_regicide_events() -> None:
    tl = _start()
    _feed(tl, 1000, spawn(200, KING, 1, 2.9, 2.9, action=False))  # next to Bob's knight
    _feed(tl, 2000, set_entity(200, "Entity", "insideObjId", "Int32", 100))
    _feed(tl, 2500, events=[{"kind": "damage", "entityid": 100, "attackerid": 104, "damage": 3}])
    _feed(tl, 3000, set_entity(200, "Entity", "insideObjId", "Int32", -1))
    _feed(tl, 3500, events=[{"kind": "damage", "entityid": 200, "attackerid": 104, "damage": 75,
                             "iskillingblow": True}], more=[kill_entity(200)])  # fmt: skip
    kinds = [e["kind"] for e in tl.events if e["cat"] == "king"]
    assert kinds == [
        "king_threatened",
        "king_garrisoned",
        "refuge_attacked",
        "king_ungarrisoned",
        "king_attacked",
        "king_killed",
    ]
    prio = {e["kind"]: e.get("priority") for e in tl.events if e["cat"] == "king"}
    # Garrisoning and a voluntary ungarrison are low, the rest high.
    assert prio == {
        "king_threatened": "high",
        "king_garrisoned": None,
        "refuge_attacked": "high",
        "king_ungarrisoned": None,
        "king_attacked": "high",
        "king_killed": "high",
    }
    ung = next(e for e in tl.events if e["kind"] == "king_ungarrisoned")
    assert ung["forced"] is False and ung["attacker"] is None and ung["boarded"] is False
    hit = next(e for e in tl.events if e["kind"] == "king_attacked")
    assert hit["attacker"]["master"] == KNIGHT and hit["by"] == 2
    ref = next(e for e in tl.events if e["kind"] == "refuge_attacked")
    assert ref["building"] == 100 and ref["attacker"]["id"] == 104
    killed = next(e for e in tl.events if e["kind"] == "king_killed")
    assert killed["by"] == 2 and killed["attacker"]["id"] == 104 and "mysterious" not in killed
    assert next(e for e in tl.events if e["kind"] == "kill")["priority"] == "high"
    # The king and his killer as one selection: one kill, one death, and the time
    # both spent in each activity, over their lives and over the last minute.
    group = tl.group_stats([200, 104])
    assert group["totals"]["kills"] == 1 and group["totals"]["deaths"] == 1
    assert sum(group["activity"].values()) > 0
    assert group["activity_lm"].keys() <= group["activity"].keys()
    assert tl.group_stats([200], t=3000)["totals"]["deaths"] == 0  # not dead yet


def test_treason_countdown_and_status_priority() -> None:
    tl = _start()
    treason_cmd = {"kind": "game", "gamecommandid": 10, "var1": 2}
    wonder = {"kind": "notificationwonder", "ownerid": 1, "type": 1, "remainingtime": 550}
    _feed(tl, 500, set_attr(2, "gold", 450.0))
    _feed(tl, 1000, set_world("countdownVictory", "Boolean", True),
          set_world("countdownClock", "Float", 520.0), events=[wonder],
          commands=[treason_cmd])  # fmt: skip
    _feed(tl, 2000, set_world("countdownClock", "Float", 480.0))
    _feed(tl, 3000, set_world("countdownClock", "Float", 95.0))
    treason = next(e for e in tl.events if e["kind"] == "treason")
    assert treason["player"] == 2 and treason["priority"] == "high"
    marks = [(e["victory"], e["player"], e["years_left"]) for e in tl.events
             if e["kind"] == "countdown"]  # fmt: skip
    assert marks == [("wonder", 1, 500), ("wonder", 1, 400), ("wonder", 1, 300),
                     ("wonder", 1, 200), ("wonder", 1, 100)]  # fmt: skip
    wonder_ev = next(e for e in tl.events if e["kind"] == "wonder_completed")
    assert wonder_ev["priority"] == "high"


def test_heresy_conversion() -> None:
    tl = _start()
    _feed(tl, 1000, set_research(1, HERESY))
    _feed(tl, 1500, events=[{"kind": "monkconversion", "monkid": 104, "monkownerid": 2,
                             "targetid": 103, "targetownerid": 1}])  # fmt: skip
    assert next(e for e in tl.events if e["kind"] == "conversion")["heresy"] is True
    assert tl.unit_stats(104)["monk"]["heresy"] == 1


def test_repeat_conversion_of_the_same_target_by_the_same_owner_is_skipped() -> None:
    tl = _start()
    conv = {"kind": "monkconversion", "monkid": 104, "monkownerid": 2, "targetid": 103,
            "targetownerid": 1}  # fmt: skip
    _feed(tl, 1500, events=[conv])
    _feed(tl, 2000, events=[dict(conv, monkid=105)])  # another monk, same owner and target
    other = dict(conv, monkid=105, monkownerid=1, targetownerid=2)  # another owner: shown
    _feed(tl, 2500, events=[other])
    shown = [e for e in tl.events if e["kind"] == "conversion"]
    assert [e["player"] for e in shown] == [2, 1]
    assert tl.unit_stats(104)["monk"]["conversions"] == 1


def test_housed_streak_relics_truce_aggregate_and_series() -> None:
    tl = _start()
    _feed(tl, 1000, set_attr(1, "maxPop", 0.0), set_treaty(30, 60),
          set_attr(1, "foodTotal", 100.0), set_attr(1, "woodTotal", 50.0),
          produce(100, VILLAGER, 1.0, 2))  # fmt: skip
    _feed(tl, 4000)
    v = tl.view_at(None)
    assert v is not None
    alice = v["players"]["1"]
    assert alice["housed"] and alice["housed_ms"] == 3000
    assert alice["d3_resource_aggregate"] == 150
    _feed(tl, 5000, set_attr(1, "maxPop", 2.0), set_treaty(0, 60),
          set_attr(1, "foodTotal", 400.0))  # fmt: skip
    v = tl.view_at(None)
    assert v is not None
    alice = v["players"]["1"]
    assert alice["housed_ms"] == 0 and alice["d3_resource_aggregate"] == 150  # frozen
    assert alice["efficiency_all"]["idle"] > 0 and "peak_army_value" in alice
    row = tl.series["1"][-1]
    for key in ("gather_food_lm", "gather_wood_lm", "gather_gold_lm", "gather_stone_lm",
                "mil_pop", "eco_pop", "eapm", "actions", "actions_effective"):  # fmt: skip
        assert key in row


def test_koth_owner_changes_and_hold_time() -> None:
    from tests.helpers import MONUMENT

    tl = _start()
    _feed(tl, 1000, spawn(400, MONUMENT, 0, 2.0, 2.0, model="BuildingEntity", action=False))
    _feed(tl, 2000, set_entity(400, "Entity", "ownerId", "Int8", 2))
    _feed(tl, 5000)
    v = tl.view_at(None)
    assert v is not None and v["koth"]["owner"] == 2 and v["koth"]["held_ms"] == 3000
    ev = next(e for e in tl.events if e["kind"] == "koth_owner")
    # no previous holder counts as 550 years left: low priority
    assert (ev["player"], ev["previous"], ev.get("priority")) == (2, 0, None)


def test_skips_and_summary_at_a_time() -> None:
    tl = Timeline(GameData(None))
    for f in game_frames(12):
        if f.time == 6000:
            f.skipped = 3
        tl.feed(f)
    tl.finish()
    assert tl.end == 12000
    assert tl.status()["skips"] == [[5500, 6000]]
    full = _timeline()
    early, late = full.summary(2000), full.summary()
    assert early["2"]["eco_kills"] == 0 and late["2"]["eco_kills"] == 1
    assert {late["1"]["placing"], late["2"]["placing"]} == {1, 2}
    assert late["2"]["most_kills"] == {"unit_master": KNIGHT, "kills": 1, "id": 104}
    assert early["2"]["most_kills"] is None
    assert late["1"]["float_hrs"] > 0 and late["1"]["geapm"] == 0  # under a minute


def test_orders_to_villagers_only_are_economy() -> None:
    from vantage.gamedata import GameData
    from vantage.timeline import Timeline
    from vantage.world import CLASS_CIVILIAN, MasterInfo

    tl = Timeline(GameData(None))

    def master(mid: int, cls: int) -> MasterInfo:
        return MasterInfo(id=mid, name=f"#{mid}", icon=0, cls=cls, type=70, hp=25, kind="unit")

    tl.catalog.masters[83] = master(83, CLASS_CIVILIAN)
    tl.catalog.masters[4] = master(4, 0)  # archer
    tl.entity_meta.update({1: (1, 83), 2: (1, 83), 3: (1, 4)})
    assert tl._economic_order({"kind": "move", "unitids": [1, 2]})
    assert not tl._economic_order({"kind": "move", "unitids": [1, 3]})
    assert not tl._economic_order({"kind": "move", "unitids": [99]})  # unknown unit
    assert not tl._economic_order({"kind": "move"})


def test_score_sub_rows_and_housed_rules() -> None:
    tl = _start()
    pts = (7, 11), (30, 22), (29, 33), (24, 1), (25, 2), (26, 4), (4, 8)
    _feed(tl, 1000, *[set_vp(1, k, v) for k, v in pts])
    alice = tl.view_at(None)["players"]["1"]  # type: ignore[index]
    assert alice["score_sub"] == {
        "exploration": 11,
        "research": 22,
        "units_buildings": 33,
        "resources_banked": 15,
    }
    assert tl.view_at(None)["players"]["2"]["score_sub"]["exploration"] == 0  # type: ignore[index]
    assert tl.summary()["1"]["score_sub"]["units_buildings"] == 33
    # Housed needs a unit at a queue head: headroom 0 alone is not housed ...
    _feed(tl, 2000, set_attr(1, "maxPop", 0.0))
    assert tl.view_at(None)["players"]["1"]["housed"] is False  # type: ignore[index]
    # ... one queued unit beyond the headroom is, until the unit limit binds.
    _feed(tl, 3000, produce(100, VILLAGER, 1.0, 2))
    v = tl.view_at(None)
    assert (
        v is not None
        and v["players"]["1"]["housed"]
        and v["players"]["1"]["population_status"] == 1
    )
    p1 = v["players"]["1"]
    assert p1["idle_tc_housed"] == [p1["tc_idle_seconds"], p1["housed_seconds"]]
    _feed(tl, 4000, set_attr(1, "unitLimit", 5.0))  # pop 4 + n 1 <= 5: still housed
    assert tl.view_at(None)["players"]["1"]["housed"] is True  # type: ignore[index]
    _feed(tl, 5000, set_attr(1, "unitLimit", 4.0))  # pop 4 + 1 > 4: at the limit, not housed
    p1 = tl.view_at(None)["players"]["1"]  # type: ignore[index]
    assert p1["housed"] is False and p1["population_status"] == 2
    _feed(tl, 6000, set_attr(1, "unitLimit", 200.0))
    assert tl.view_at(None)["players"]["1"]["housed_seconds"] >= 1  # type: ignore[index]


def test_treason_needs_400_gold() -> None:
    tl = _start()
    cmd = {"kind": "game", "gamecommandid": 10, "var1": 2}
    _feed(tl, 500, commands=[cmd])  # Bob has no gold: not a treason
    assert not [e for e in tl.events if e["kind"] == "treason"]
    _feed(tl, 600, set_attr(2, "gold", 400.0))
    _feed(tl, 700, commands=[cmd, {"kind": "game", "gamecommandid": 11, "var1": 2}])
    (ev,) = [e for e in tl.events if e["kind"] == "treason"]
    assert ev["player"] == 2 and ev["priority"] == "high" and ev["t"] == 700


def test_diplomacy_after_a_long_stance_is_high_with_duration() -> None:
    tl = _start()
    _feed(tl, 1000, set_relation(1, 2, 2))
    _feed(tl, 2000, set_relation(1, 2, 2))
    _feed(tl, 3000, set_relation(1, 2, 3))  # first change seen: 'enemy' -> ... see below
    far = 3000 + 100 * 5000
    _feed(tl, far, set_relation(1, 2, 4))
    _feed(tl, far + 1000, set_relation(1, 2, 7))  # not a stance: no event
    dip = [e for e in tl.events if e["kind"] == "diplomacy"]
    assert [e["stance"] for e in dip] == ["ally", "neutral", "enemy"]
    assert "priority" not in dip[0] and "duration_ms" not in dip[0]
    assert dip[2]["previous"] == "neutral" and dip[2]["duration_years"] == 100
    assert dip[2]["duration_ms"] == 500_000 and dip[2]["priority"] == "high"


def test_monument_seized_with_previous_holders_time_left() -> None:
    from tests.helpers import MONUMENT

    tl = _start()
    _feed(tl, 1000, spawn(400, MONUMENT, 0, 2.0, 2.0, model="BuildingEntity", action=False))
    _feed(tl, 1500, set_entity(400, "Entity", "ownerId", "Int8", 2))
    _feed(tl, 2000, set_player(2, "ruinHeldTime", "Float", 551.0))  # 550 / 10 * 5000 ms left
    _feed(tl, 3000)
    v = tl.view_at(None)
    assert v is not None and v["koth"]["remaining_ms"] == 275_000
    assert v["koth"]["remaining_years"] == 55.0 and v["koth"]["holder"] == 2
    _feed(tl, 4000, set_entity(400, "Entity", "ownerId", "Int8", 1),
          set_player(2, "ruinHeldTime", "Float", -1.0),
          set_player(1, "ruinHeldTime", "Float", 5501.0))  # fmt: skip
    _feed(tl, 5000)
    ev = [e for e in tl.events if e["kind"] == "koth_owner"][-1]
    assert (ev["player"], ev["previous"]) == (1, 2)
    assert ev["previous_remaining_ms"] == 275_000 and ev["previous_remaining_years"] == 55
    assert ev["priority"] == "high"  # the loser was within 100 years of victory


def test_king_forced_ungarrison_credits_the_refuge_attacker() -> None:
    tl = _start()
    _feed(tl, 1000, spawn(200, KING, 1, 40.0, 40.0, action=False))
    _feed(tl, 2000, set_entity(200, "Entity", "insideObjId", "Int32", 100))
    _feed(tl, 2500, events=[{"kind": "damage", "entityid": 100, "attackerid": 104, "damage": 3}])
    _feed(tl, 3000, set_entity(200, "Entity", "insideObjId", "Int32", -1), kill_entity(100))
    ung = next(e for e in tl.events if e["kind"] == "king_ungarrisoned")
    assert ung["forced"] is True and ung["priority"] == "high"
    assert ung["attacker"] == {"id": 104, "owner": 2, "master": KNIGHT} and ung["by"] == 2
    gar = next(e for e in tl.events if e["kind"] == "king_garrisoned")
    assert gar["refuge"]["id"] == 100 and gar["boarded"] is False and "priority" not in gar
    ref = next(e for e in tl.events if e["kind"] == "refuge_attacked")
    assert ref["boarded"] is False and ref["building"] == 100


def test_king_attack_renews_within_15s_and_reannounces_for_a_new_attacker() -> None:
    tl = _start()
    _feed(tl, 1000, spawn(200, KING, 1, 40.0, 40.0, action=False))
    hit = {"kind": "damage", "entityid": 200, "attackerid": 104, "damage": 2}
    for t in (2000, 8000, 16000):
        _feed(tl, t, events=[hit])  # renewed each time: one announcement
    assert len([e for e in tl.events if e["kind"] == "king_attacked"]) == 1
    # Alice's own villager as the attacker: another attacking player re-announces ...
    _feed(tl, 17000, events=[{**hit, "attackerid": 103}])
    # ... but within 20 s of the first the log merges them into one row.
    assert len([e for e in tl.events if e["kind"] == "king_attacked"]) == 1


def test_king_merge_backfills_a_late_attacker() -> None:
    tl = _start()
    tl._king_emit({"t": 1000, "cat": "king", "kind": "king_attacked", "player": 1, "king": 5,
                   "attacker": None, "by": None})  # fmt: skip
    ref = {"id": 9, "owner": 2, "master": KNIGHT}
    tl._king_emit({"t": 15000, "cat": "king", "kind": "king_attacked", "player": 1, "king": 5,
                   "attacker": ref, "by": 2})  # fmt: skip
    tl._king_emit({"t": 40000, "cat": "king", "kind": "king_attacked", "player": 1, "king": 5,
                   "attacker": None, "by": None})  # fmt: skip
    rows = [e for e in tl.events if e["kind"] == "king_attacked"]
    assert len(rows) == 2 and rows[0]["attacker"] == ref and rows[0]["by"] == 2


def test_king_that_vanishes_died_mysteriously_and_no_king_found() -> None:
    tl = _start()
    _feed(tl, 1000, spawn(200, KING, 1, 40.0, 40.0, action=False))
    v = tl.view_at(None)
    assert v is not None and v["king_status"]["1"]["state"] == "alive"
    assert v["king_status"]["2"] == {"state": "none"}  # "No king found for this player"
    _feed(tl, 3000, kill_entity(200))
    ev = next(e for e in tl.events if e["kind"] == "king_killed")
    assert ev["mysterious"] is True and ev["attacker"] is None and ev["priority"] == "high"
    v = tl.view_at(None)
    assert v is not None and v["king_status"]["1"]["state"] == "dead"
    assert v["king_status"]["1"]["x"] == 40.0


def test_king_threatened_names_the_nearest_threat() -> None:
    tl = _start()
    _feed(tl, 1000, spawn(200, KING, 1, 2.9, 2.9, action=False))  # beside Bob's knight
    ev = next(e for e in tl.events if e["kind"] == "king_threatened")
    assert ev["player"] == 1 and ev["by"] == 2 and ev["priority"] == "high"
    assert ev["threat"] == {"id": 104, "owner": 2, "master": KNIGHT}


def test_market_trades_merge_within_two_seconds() -> None:
    tl = _start()
    buy = {"kind": "markettransaction", "playerid": 1, "attributetype": 1,
           "attributeexchanged": 100.0, "goldexchanged": -120.0}  # fmt: skip
    _feed(tl, 1000, events=[buy, buy])
    _feed(tl, 2500, events=[buy])  # 1.5 s after the last: still merged
    _feed(tl, 6000, events=[buy])  # 3.5 s later: a new row
    _feed(tl, 6100, events=[{**buy, "attributeexchanged": -50.0, "goldexchanged": 40.0}])
    rows = [e for e in tl.events if e["cat"] == "market"]
    assert [(r["kind"], r["amount"], r["gold"], r["count"]) for r in rows] == [
        ("buy", 300.0, 360.0, 3),
        ("buy", 100.0, 120.0, 1),
        ("sell", 50.0, 40.0, 1),
    ]
    assert rows[0]["t"] == 1000 and rows[0]["t_last"] == 2500


def test_tribute_tax_and_zero_received_is_dropped() -> None:
    tl = _start()
    tr = {"kind": "tribute", "senderid": 1, "receiverid": 2, "attributetype": 3}
    _feed(tl, 500, events=[{**tr, "sendervaluechange": -100.0, "receivervaluechange": 80.0},
                           {**tr, "sendervaluechange": -100.0}])  # fmt: skip
    (ev,) = [e for e in tl.events if e["kind"] == "tribute"]
    assert (ev["amount"], ev["tax"], ev["sent"]) == (80, 20, 100)
    _feed(tl, 1000)
    assert tl.view_at(None)["players"]["1"]["tribute_sent"] == 200  # type: ignore[index]


def test_oracle_chat_is_always_logged_and_not_doubled_by_the_frame_copy() -> None:
    tl = _start()
    _feed(tl, 1000)
    tl.oracle_chat({"playerid": 1, "text": "hello", "destinationmap": 4})
    (first,) = [e for e in tl.events if e["kind"] == "chat"]
    assert first["oracle"] is True and first["paused"] is False and first["t"] == 1000
    assert first["to"] == [2]
    chat = {"kind": "playerchat", "playerid": 1, "text": "hello", "destinationmap": 4}
    _feed(tl, 2000, events=[chat])  # the same chat arriving in the frame stream
    assert len([e for e in tl.events if e["kind"] == "chat"]) == 1
    _feed(tl, 3000, events=[{**chat, "text": "later"}])  # frame first ...
    tl.oracle_chat({"playerid": 1, "text": "later"}, paused=True)  # ... then Oracle: one row
    rows = [e for e in tl.events if e["kind"] == "chat"]
    assert [r["text"] for r in rows] == ["hello", "later"]
    tl.oracle_chat({"playerid": 1, "text": "hello"})  # a repeated line is a new chat
    assert len([e for e in tl.events if e["kind"] == "chat"]) == 3


def test_apm_classes_of_the_new_commands() -> None:
    tl = _start()
    cmds = [
        {"kind": "giveattribute", "commplayerid": 2},  # eco
        {"kind": "allbacktowork", "commplayerid": 2},  # eco
        {"kind": "offboardtrade", "commplayerid": 2},  # eco
        {"kind": "lockformation", "commplayerid": 2},  # military
        {"kind": "formationparameters", "commplayerid": 2},  # military
        {"kind": "autoformations", "commplayerid": 2},  # military
        {"kind": "breakformation", "commplayerid": 2},  # military
        {"kind": "seekshelter", "commplayerid": 2, "unitids": [101]},  # villager: eco
        {"kind": "fireactiveability", "commplayerid": 2, "unitids": [104]},  # knight: military
        {"kind": "buildingcommandqueue", "commplayerid": 2, "unitids": [102, 103]},  # eco
        {"kind": "pseudotech", "commplayerid": 2},  # automatic
        {"kind": "giveattributesrge", "commplayerid": 2},
        {"kind": "fillselection", "commplayerid": 2},
    ]
    _feed(tl, 500, commands=cmds)
    _feed(tl, 1000)
    apm = tl.view_at(None)["apm"]["2"]  # type: ignore[index]
    assert apm["total"] == 10 and apm["military"] == 5 and apm["eco"] == 5


def test_most_created_by_unit_line_per_player_and_team() -> None:
    tl = _start()
    ev = [
        {"kind": "notificationtraindone", "ownerid": 2, "masterid": m, "buildingid": 100}
        for m in (KNIGHT, KNIGHT, VILLAGER, 1252, KING)
    ]
    _feed(tl, 500, events=ev)
    _feed(tl, 1000)
    s = tl.summary()
    assert s["2"]["most_created_lines"] == [[f"m{KNIGHT}", 2, KNIGHT]]  # eco, King, 1252 skipped
    assert s["1"]["most_created_lines"] == []
    teams = s["teams_most_created"]
    assert teams["3"] == [[f"m{KNIGHT}", 2, KNIGHT]] and teams["2"] == []


def test_under_attack_names_the_victim_unit_and_drops_unknown_owners() -> None:
    tl = _start()
    _feed(tl, 500, events=[
        {"kind": "combatnotificationsound", "receiverid": 1, "attackedobjectid": 103},
        {"kind": "combatnotificationsound", "receiverid": 1, "attackedobjectid": 999},
        {"kind": "combatnotificationsound", "receiverid": 1, "attackedobjectid": 100},
    ])  # fmt: skip
    ev, tc = [e for e in tl.events if e["kind"] == "under_attack"]
    assert ev["master"] == 1880 and ev["unit"]["id"] == 103 and ev["unit"]["owner"] == 1
    assert "priority" not in ev and tc["priority"] == "high"  # a town centre under attack


def test_wonder_and_relic_events_carry_the_data_for_their_sentences() -> None:
    tl = _start()
    wonder = {"kind": "notificationwonder", "ownerid": 1, "objid": 100, "type": 0}
    relics = {"kind": "notificationwonder", "ownerid": 1, "type": 3, "remainingtime": 250}
    _feed(tl, 500, events=[wonder, relics])
    w = next(e for e in tl.events if e["kind"] == "wonder_started")
    assert w["wonder"] == 100 and "x" in w and w["priority"] == "high"
    r = next(e for e in tl.events if e["kind"] == "relics_held")
    assert r["monasteries"] == [] and r["priority"] == "high"  # none in the test world


def test_unit_born_is_the_keyframe_it_first_appeared_in() -> None:
    tl = _start()
    _feed(tl, 1000)
    _feed(tl, 4000, spawn(300, KNIGHT, 2, 3.0, 3.0))
    assert tl.unit_stats(300)["born"] == 4000
    assert tl.unit_stats(104)["born"] == 0
    late = Timeline(GameData(None))
    late.feed(snapshot_frame(7000))
    assert late.unit_stats(104)["born"] is None  # joined late: unknown


def test_refuge_hit_points_dropping_is_an_attack_without_an_attacker() -> None:
    tl = _start()
    _feed(tl, 1000, spawn(200, KING, 1, 40.0, 40.0, action=False))
    _feed(tl, 2000, set_entity(200, "Entity", "insideObjId", "Int32", 100))
    _feed(tl, 3000)
    _feed(tl, 4000, set_entity(100, "Entity", "hp", "Float", 100.0))  # building loses hit points
    _feed(tl, 5000)
    ev = next(e for e in tl.events if e["kind"] == "refuge_attacked")
    assert ev["hp_drop"] is True and ev["attacker"] is None and ev["building"] == 100
    assert ev["player"] == 1 and ev["priority"] == "high"
    # Still dropping 1 s later: renewed, not announced again.
    _feed(tl, 6000, set_entity(100, "Entity", "hp", "Float", 50.0))
    assert len([e for e in tl.events if e["kind"] == "refuge_attacked"]) == 1


def test_a_king_in_a_transport_ship_has_boarded() -> None:
    tl = _start()
    info = tl._refuge_info(100, {100: [100, 1, 545, 0.0, 0.0, 1.0]})
    assert info["boarded"] is True and info["refuge_master"] == 545
    assert info["refuge"] == {"id": 100, "owner": 1, "master": 545}
    assert tl._refuge_info(100, {100: [100, 1, 109, 0.0, 0.0, 1.0]})["boarded"] is False


def test_kill_groups_mods_and_teams_locked_are_wired() -> None:
    tl = _start()
    assert tl.match["teams_locked"] is False  # absent in the stream = unlocked
    _feed(tl, 500, events=[{"kind": "damage", "entityid": 102, "attackerid": 104, "damage": 25.0,
                            "iskillingblow": True}], more=[kill_entity(102)])  # fmt: skip
    assert tl._kill_groups_of(104) == [4]  # a villager's objectGroup
    assert tl._kill_groups_of(999) == []
    _feed(tl, 1000)
    u = tl.unit_stats(104)
    assert "mods" in u and "livestock_owner" in u  # None unless the view has an entry


def test_housed_state_requires_playing_status_and_unit_heads() -> None:
    from vantage import world as W
    from vantage.patch import Node
    from vantage.timeline import housed_state

    def player(status: int | None, **attrs: float) -> Node:
        a = Node(0, {W._ATTR[k]: v for k, v in attrs.items()})
        fields: dict[int, Any] = {W.P_ATTR: a}
        if status is not None:
            fields[W.P_STATUS] = status
        return Node(0, fields)

    unit_q = [{"queue": [{"unit": 83, "count": 1}]}]
    research_q = [{"queue": [{"unit": -1, "count": 1}]}]
    attrs = {"population": 10.0, "maxPop": 0.0, "unitLimit": 200.0}
    assert housed_state(player(None, **attrs), unit_q, {}) == (True, 1)
    assert housed_state(player(2, **attrs), unit_q, {})[0] is False  # lost
    assert housed_state(player(None, **attrs), research_q, {})[0] is False  # research head
    assert housed_state(player(None, **attrs), [], {})[0] is False  # nothing queued


def test_relic_gold_is_the_victory_point_entry_not_the_per_relic_rate() -> None:
    tl = _start()
    # Attribute 181 is the constant per-relic rate; entry 27 accumulates the gold.
    _feed(tl, 1000, set_attr(1, "relicGold", 30.0), set_vp(1, 27, 0, 84.0))
    p1 = tl.view_at(None)["players"]["1"]  # type: ignore[index]
    p2 = tl.view_at(None)["players"]["2"]  # type: ignore[index]
    assert p1["relic_gold"] == 84 and p2["relic_gold"] == 0
    _feed(tl, 2000, set_vp(1, 27, 0, 234.0))
    assert tl.view_at(None)["players"]["1"]["relic_gold"] == 234  # type: ignore[index]


def test_keyframe_step_spaces_keyframes(tmp_path: Path) -> None:
    from tests.helpers import game_frames
    from vantage.gamedata import GameData
    from vantage.timeline import Timeline

    tl = Timeline(GameData(tmp_path / "none"))
    tl.keyframe_step_ms = 2000
    for f in game_frames(12):
        tl.feed(f)
    times = [k.time for k in tl.keyframes]
    from itertools import pairwise

    assert len(times) >= 3 and all(b - a >= 2000 for a, b in pairwise(times))


def test_live_terrain_is_snapshotted_when_it_changes() -> None:
    from tests.helpers import PatchBuilder, fid
    from vantage.frames import Frame as F

    tl = Timeline(GameData(None))
    frames = game_frames(12)
    for f in frames[:3]:
        tl.feed(f)
    first = tl.terrain_at(tl.time)
    assert first is not None and len(first[1]) == 32  # base terrain, then layers
    b = PatchBuilder().push(fid("Root", "world")).assign(fid("World", "time"), "UInt32", 8000)
    b.push_key(fid("World", "mapTiles"), 5).assign(fid("MapTile", "terrainType"), "UInt8", 7)
    b.pop().pop()
    tl.feed(F(time=8000, patch=b.forward()))
    later = tl.terrain_at(8000)
    assert later is not None and later[0] > first[0] and later[1][5] == 7
    assert tl.terrain_at(first[0]) == first  # earlier moments keep their terrain
    v = tl.view_at(8000)
    assert v is not None and v["terrain_t"] == later[0]


def test_players_who_went_out_place_by_how_long_they_lasted() -> None:
    from vantage.timeline import _placings

    out = {
        "1": {"status": "won", "score": 100, "out_t": None},
        "2": {"status": "resigned", "score": 9000, "out_t": 1000},  # out first, big score
        "3": {"status": "resigned", "score": 50, "out_t": 5000},
        "4": {"status": "playing", "score": 10, "out_t": None},
    }
    _placings(out)
    assert [out[p]["placing"] for p in ("1", "4", "3", "2")] == [1, 2, 3, 4]


def test_the_games_age_up_announcement_is_not_chat() -> None:
    tl = _start()
    announce = "<player_id,1,-1> advanced to the Feudal Age."
    _feed(
        tl,
        500,
        events=[
            {"kind": "playerchat", "playerid": 1, "text": announce},
            {"kind": "playerchat", "playerid": 1, "text": "gg advanced to the next round"},
        ],
    )
    chats = [e["text"] for e in tl.events if e["kind"] == "chat"]
    assert chats == ["gg advanced to the next round"]  # a player's own line stays


def _missile_timeline() -> Timeline:
    """A shot flies from x=1 to x=3 while a new particle appears at t=300 (age 0.05 s)."""
    from tests.helpers import PatchBuilder, fid

    def particle(age: float, create: bool) -> Any:
        def step(b: PatchBuilder) -> None:
            key = fid("World", "particleInstances")
            if create:
                b.resize(key, 2)
                b.create_key(key, M("ParticleInstance"), 1)
                for name, wire, value in (
                    ("active", "Boolean", True),
                    ("spriteUsed", "Boolean", True),
                    ("spriteId", "Int16", 7),
                    ("spriteDuration", "Float", 2.0),
                ):
                    b.assign(fid("ParticleInstance", name), wire, value)
            else:
                b.push_key(key, 1)
            b.assign(fid("ParticleInstance", "spriteAge"), "Float", age).pop()

        return step

    tl = Timeline(GameData(None))
    tl.feed(snapshot_frame(0))
    shot = spawn(-5, 3, 1, 1.0, 1.0, model="MissileEntity", action=False)
    x = lambda v: set_entity(-5, "Entity", "worldX", "Float", v)  # noqa: E731
    sprite = set_entity(-5, "Entity", "spriteId", "Int16", 10)
    tl.feed(Frame(time=100, patch=delta(100, shot, sprite).forward()))
    tl.feed(Frame(time=200, patch=delta(200, x(2.0)).forward()))
    tl.feed(Frame(time=300, patch=delta(300, x(3.0), particle(0.05, True)).forward()))
    tl.feed(Frame(time=400, patch=delta(400, kill_entity(-5), particle(0.15, False)).forward()))
    tl.feed(Frame(time=1100, patch=delta(1100).forward()))  # next keyframe flushes the buffer
    return tl


def test_missile_track_follows_a_shot_between_keyframes() -> None:
    tl = _missile_timeline()
    assert [k.time for k in tl.keyframes] == [0, 1100]
    v = tl.view_at(0)
    assert v is not None
    track = v["missile_track"]
    flights = [(t, [(r[0], r[3], r[4]) for r in rows]) for t, rows, _ in track if rows]
    assert flights == [(100, [(-5, 1.0, 1.0)]), (200, [(-5, 2.0, 1.0)]), (300, [(-5, 3.0, 1.0)])]
    after = tl.view_at(1100)
    assert after is not None and after["time"] == 1100
    assert after["missile_track"][: len(track)] == track  # the previous keyframe's flight too


def test_particle_births_are_recorded_once_with_their_birth_time() -> None:
    tl = _missile_timeline()
    v = tl.view_at(0)
    assert v is not None
    births = [(t, b) for t, _, bs in v["missile_track"] for b in bs]
    assert len(births) == 1  # the same particle aging on is not born again
    t, b = births[0]
    assert t == 300 and b[0] == 250  # first sampled at 300, born 0.05 s earlier
    assert b[1:3] == [0.0, 0.0] and b[4] == 7 and b[5] == 0.05
    assert all(not bs for _, _, bs in v["missile_track"][:2])  # nothing at the first samples


def test_views_are_read_while_a_keyframe_is_being_built() -> None:
    # ``feed`` holds the lock through a whole keyframe build; view, terrain and
    # tree reads must not wait for it (they did, and stalled playback while a
    # recording loaded).
    import threading

    tl = _timeline()
    held, release = threading.Event(), threading.Event()

    def ingest() -> None:
        with tl._lock:
            held.set()
            release.wait(5)

    th = threading.Thread(target=ingest)
    th.start()
    try:
        assert held.wait(5)
        got: list[Any] = []
        reader = threading.Thread(
            target=lambda: got.append((tl.view_at(5000), tl.terrain_at(5000), tl.trees_at(5000)))
        )
        reader.start()
        reader.join(2)
        assert not reader.is_alive()
        view, _, _ = got[0]
        assert view is not None and view["time"] == 5000
    finally:
        release.set()
        th.join()


def test_unit_track_records_where_units_went_between_keyframes() -> None:
    """Moving units every UNIT_TRACK_MS between keyframes (only those that moved),
    stored with the keyframe they follow; the next keyframe starts a new track."""
    tl = _start()
    _feed(tl, 1000)  # keyframe: the knight (104) is followed from here

    def x(v: float) -> Any:
        return set_entity(104, "Entity", "worldX", "Float", v)

    _feed(tl, 1050, x(3.5))  # before UNIT_TRACK_MS: not sampled
    _feed(tl, 1100, x(4.0))
    _feed(tl, 1300, x(5.0))
    _feed(tl, 1600, x(6.0))
    _feed(tl, 1900)  # nothing moved
    _feed(tl, 2000)  # next keyframe: the track is stored
    v, after = tl.view_at(1000), tl.view_at(2000)
    assert v is not None and after is not None
    track = v["unit_track"]
    assert [s[0] for s in track] == [1100, 1300, 1600]
    moves = [[u[0], u[1]] for _, units in track for u in units]
    assert moves == [[104, 4.0], [104, 5.0], [104, 6.0]]
    assert after["unit_track"] == []


def test_a_repeated_snapshot_of_the_same_moment_is_skipped(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """A game that ended or paused answers every reconnect with the same full
    snapshot; re-applying one (seconds of CPU late in a game) changes nothing."""
    tl = Timeline(GameData(None))
    assert tl.feed(snapshot_frame(5000)) is True
    patcher, frames, version = tl.patcher, tl.frames, tl.version
    assert tl.feed(snapshot_frame(5000)) is False
    assert tl.patcher is patcher and tl.frames == frames and tl.version == version
    assert tl.repeated_snapshots == 1
    # Another state at the same moment, a snapshot after a delta, and a snapshot
    # that resynchronises a broken tree are all applied.
    assert tl.feed(Frame(time=5000, patch=snapshot_frame(4000).patch)) is True
    assert tl.feed(Frame(time=5000, patch=delta(5000, set_attr(1, "food", 5.0)).forward()))
    assert tl.feed(snapshot_frame(5000)) is True
    tl.feed(Frame(time=5000, patch=b"\xff"))  # an unknown instruction
    assert tl.desynced and tl.feed(snapshot_frame(5000)) is True and not tl.desynced
    # A later moment is never a repeat.
    assert tl.feed(snapshot_frame(6000)) is True
    assert tl.repeated_snapshots == 1

    from vantage import timeline as T

    settled: list[int] = []
    monkeypatch.setattr(T, "settle_heap", lambda: settled.append(1))
    path = tmp_path / "paused.vrec"
    with RecordingWriter(path) as w:
        for f in game_frames(2):
            w.write(f)
        for _ in range(5):
            w.write(snapshot_frame(2000))  # stream reopened on a paused game
    loaded = load_recording(str(path), GameData(None))
    # After a delta the first one applies; the four after it are skipped, and
    # the heap is settled only for snapshots that were applied.
    assert loaded.repeated_snapshots == 4
    assert loaded.frames == 6 and len(settled) == 2


def test_events_between_reads_without_the_lock_in_or_out_of_order() -> None:
    import threading

    tl = _timeline()

    def scan(t0: int, t1: int) -> list[dict[str, Any]]:
        return [e for e in tl.events if t0 <= e["t"] <= t1]

    for t0, t1 in ((0, 1 << 62), (3000, 3000), (3001, 4999), (5000, 9000), (7000, 1000)):
        assert tl.events_between(t0, t1) == scan(t0, t1)
    held, release = threading.Event(), threading.Event()

    def ingest() -> None:
        with tl._lock:
            held.set()
            release.wait(5)

    th = threading.Thread(target=ingest)
    th.start()
    try:
        assert held.wait(5)
        got: list[Any] = []
        reader = threading.Thread(target=lambda: got.append(tl.events_between(0, 1 << 62)))
        reader.start()
        reader.join(2)
        assert not reader.is_alive() and got[0] == scan(0, 1 << 62)
    finally:
        release.set()
        th.join()
    # An event logged with an earlier time than the last one still turns up.
    tl.add_event({"t": 3500, "cat": "status", "kind": "waiting", "players": []})
    tl.add_event({"t": 99_000, "cat": "status", "kind": "waiting", "players": []})
    for t0, t1 in ((3400, 3600), (0, 1 << 62), (98_000, 99_000)):
        assert tl.events_between(t0, t1) == scan(t0, t1)


def test_series_since_a_time_and_cached_between_versions() -> None:
    tl = _timeline()
    full = tl.series_json()
    assert full == {pid: list(rows) for pid, rows in tl.series.items()}
    assert tl.series_json() is full  # nothing new: the same result
    times = [r["t"] for r in full["1"]]
    assert times == sorted(times) and len(times) >= 3
    since = tl.series_json(times[1])
    assert set(since) == set(full)
    assert all(rows == [r for r in full[pid] if r["t"] >= times[1]] for pid, rows in since.items())
    assert tl.series_json(times[1] + 1)["1"] == full["1"][2:]
    assert tl.series_json(10**9) == {pid: [] for pid in full}
    tl.add_event({"t": 1, "cat": "status", "kind": "waiting", "players": []})
    assert tl.series_json() is not full and tl.series_json() == full


def _encoded(v: Any) -> bytes:
    """``/api/view`` as the server encoded the parsed view before view_json."""
    return json.dumps(v, separators=(",", ":"), default=str).encode()


def test_view_json_is_the_view_byte_for_byte_and_caches_final_keyframes(
    monkeypatch: Any,
) -> None:
    from vantage import timeline as T

    tl = _missile_timeline()
    _feed(tl, 1200, set_entity(104, "Entity", "worldX", "Float", 4.5))
    _feed(tl, 1450)  # the newest keyframe's tracks are still filling
    for t in (None, -100, 0, 50, 1099, 1100, 1300, 99_000):
        v = tl.view_at(t)
        assert v is not None and tl.view_json(t) == _encoded(v), t
    assert tl.view_at(0)["missile_track"] and tl.view_at(1100)["missile_track"]  # type: ignore[index]
    # The newest keyframe has no successor yet: its tracks may still grow.
    newest = json.loads(tl.view_json(1300) or b"")
    assert newest["final"] is False and newest["time"] == 1100
    assert "final" not in json.loads(tl.view_json(0) or b"")
    # Only final responses are kept, and the same bytes are served again.
    assert tl.view_json(0) is tl.view_json(50)
    assert set(tl._view_cache) == {(0, False)}
    tl.finish()  # nothing more comes: the newest keyframe is final too
    for t in (None, 0, 1100, 1450):
        v = tl.view_at(t)
        assert v is not None and "final" not in v and tl.view_json(t) == _encoded(v)
    monkeypatch.setattr(T, "VIEW_CACHE_SIZE", 2)
    tl._view_cache.clear()
    for t in (0, 1100, None):
        tl.view_json(t)
    assert len(tl._view_cache) == 2


def test_flushing_makes_the_newest_state_viewable_without_ending_the_timeline() -> None:
    """A game that is over sends nothing more, and its last moments (when the winners
    are decided) fall after the newest 1 s keyframe: they must still be viewable."""
    tl = _start()
    _feed(tl, 1050)  # the next keyframe is due at 2000
    _feed(tl, 1450)
    assert tl.time == 1450 and tl.keyframes[-1].time == 1050
    version = tl.version
    tl.flush_keyframe()
    assert tl.keyframes[-1].time == 1450 and tl.version > version
    view = tl.view_at(None)
    assert view is not None and view["time"] == 1450
    assert not tl.complete  # a flush is not the end: the game may still start another match
    version = tl.version
    tl.flush_keyframe()  # nothing new: no change
    assert tl.version == version
    _feed(tl, 1950)  # ingestion carries on
    assert tl.time == 1950


def test_views_of_a_whole_game_match_byte_for_byte() -> None:
    tl = Timeline(GameData(None))
    for f in game_frames(12):
        tl.feed(f)
    for t in (None, *range(-500, 13_000, 250)):
        v = tl.view_at(t)
        assert v is not None and tl.view_json(t) == _encoded(v), t
    assert Timeline(GameData(None)).view_json(0) is None


def test_unit_and_group_panels_decode_the_keyframe_outside_the_lock(monkeypatch: Any) -> None:
    tl = _timeline()
    before = (tl.unit_stats(104, 5000), tl.group_stats([104, 100], 5000), tl.unit_stats(104))
    real = tl.keyframe_at
    held: list[bool] = []

    def keyframe_at(t: int | None) -> Any:
        held.append(tl._lock._is_owned())  # type: ignore[attr-defined]
        return real(t)

    def no_view(t: int | None) -> Any:
        raise AssertionError("the whole view is not needed")

    monkeypatch.setattr(tl, "keyframe_at", keyframe_at)
    monkeypatch.setattr(tl, "view_at", no_view)
    after = (tl.unit_stats(104, 5000), tl.group_stats([104, 100], 5000), tl.unit_stats(104))
    assert after == before and held == [False, False, False]
    assert real(5000) is real(5400)  # decoded once for both


def test_a_track_stored_while_its_buffer_is_read_is_served_stored() -> None:
    """Ingestion stores a keyframe's full buffer, then starts the next keyframe's;
    a reader without the lock that sees the next buffer must not serve it."""
    import zlib

    from vantage.timeline import _track_json

    stored: dict[int, bytes] = {}
    full = [[1100, [[104, 4.0, 1.0, 0]]]]

    def buffer() -> list[Any]:
        stored[1000] = zlib.compress(json.dumps(full, separators=(",", ":")).encode())
        return [[2050, [[104, 9.0, 1.0, 0]]]]  # already the next keyframe's samples

    assert json.loads(_track_json(stored, 1000, lambda: 1000, buffer)) == full
    assert json.loads(_track_json({}, 1000, lambda: 1000, lambda: full)) == full
    assert _track_json({}, 1000, lambda: 2000, lambda: full) == b"[]"


# -- resources collected per minute ------------------------------------------------


def _gather(tl: Timeline, t: int, food: float, wood: float = 0.0) -> dict[str, Any]:
    """Feed player 1's collected totals at ``t``; return the view's ``collected_rate``."""
    _feed(tl, t, set_attr(1, "foodTotal", food), set_attr(1, "woodTotal", wood))
    v = tl.view_at(None)
    assert v is not None and v["time"] == t
    rate: dict[str, Any] = v["players"]["1"]["collected_rate"]
    return rate


def test_collected_rate_of_steady_gathering_is_per_minute() -> None:
    tl = _start()
    v = tl.view_at(0)
    assert v is not None
    assert v["players"]["1"]["collected_rate"] == dict.fromkeys(
        ("food", "wood", "stone", "gold", "total"), 0
    )
    for i in range(1, 13):  # 10 food and 5 wood a second for two minutes
        rate = _gather(tl, i * 10_000, food=100.0 * i, wood=50.0 * i)
        assert rate == {"food": 600, "wood": 300, "stone": 0, "gold": 0, "total": 900}


def test_collected_rate_before_a_full_minute_is_divided_by_the_time_so_far() -> None:
    tl = _start()
    # 100 food in the first 10 s is 600 a minute, not the 100 gathered so far.
    assert _gather(tl, 10_000, food=100.0)["food"] == 600
    assert _gather(tl, 30_000, food=200.0)["food"] == 400


def test_collected_rate_counts_only_the_last_minute() -> None:
    tl = _start()
    food = 0.0
    for t in range(10_000, 120_001, 10_000):
        food += 100.0 if t <= 60_000 else 300.0  # 10 food a second, then 30
        rate = _gather(tl, t, food=food)
        if t == 90_000:
            assert rate["food"] == 1200  # half a minute at each speed
    # The first minute's slower gathering has left the window (the whole-game
    # average would be 1200).
    assert rate["food"] == 1800 and rate["total"] == 1800
    assert [w[0] for w in tl._col_window["1"]] == list(range(60_000, 120_001, 10_000))


def test_collected_rate_restarts_after_a_step_back_in_time() -> None:
    tl = Timeline(GameData(None))
    col = dict.fromkeys(("food", "wood", "stone", "gold", "total"), 0)
    assert tl._collected_rate("1", 0, col) == col
    assert tl._collected_rate("1", 30_000, {**col, "food": 300, "total": 300})["food"] == 600
    # Rewound to 10 s: the later samples no longer describe the past.
    assert tl._collected_rate("1", 10_000, {**col, "food": 100, "total": 100}) == col
    assert tl._collected_rate("1", 20_000, {**col, "food": 150, "total": 150})["food"] == 300
    assert tl._collected_rate("1", 30_000, None) is None


def test_collected_rate_is_absent_without_collected_totals() -> None:
    tl = Timeline(GameData(None))
    v: dict[str, Any] = {"time": 1000, "players": {"1": {}}, "entities": []}
    tl._activity(v)
    assert "efficiency" in v["players"]["1"] and "collected_rate" not in v["players"]["1"]


def test_series_rows_and_summary_carry_the_collected_rate() -> None:
    tl = _start()
    for i in range(1, 4):
        _gather(tl, i * 10_000, food=100.0 * i, wood=50.0 * i)
    rows = tl.series["1"]
    assert all(f"rate_{k}" in r for r in rows for k in ("food", "wood", "stone", "gold", "total"))
    last = rows[-1]
    assert last["t"] == 30_000
    assert (last["rate_food"], last["rate_wood"], last["rate_total"]) == (600, 300, 900)
    assert rows[0]["rate_total"] == 0
    assert tl.summary()["1"]["collected_rate"]["total"] == 900


def test_average_apm_counts_only_the_time_the_timeline_observed() -> None:
    # Attached 20 minutes into a game: actions seen in the 2 observed minutes
    # must not be divided over the whole 22.
    tl = Timeline(GameData(None))
    tl.feed(snapshot_frame(1_200_000))
    tl._apm_total[1] = 240
    _feed(tl, 1_260_000)
    _feed(tl, 1_320_000)
    v = tl.view_at(None)
    assert v is not None
    assert v["players"]["1"]["apm_avg"] == round(240 / ((tl.time - tl.start) / 60_000))
