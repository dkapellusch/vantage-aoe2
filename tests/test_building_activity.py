"""Actual Dan queue captures, plus explicit idle/housing/handoff controls."""

from __future__ import annotations

import gzip
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from tests.helpers import VILLAGER, delta, fid, produce, set_attr, snapshot_frame
from vantage import world as W
from vantage.building_activity import BuildingHistory
from vantage.frames import Frame
from vantage.gamedata import GameData
from vantage.patch import Node
from vantage.schema import SCHEMA
from vantage.timeline import Timeline


def decode(value: Any) -> Any:
    if isinstance(value, dict):
        if "model" in value:
            model = SCHEMA.model_id(value["model"])
            return Node(
                model, {SCHEMA.fid(model, k): decode(v) for k, v in value["fields"].items()}
            )
        return {int(k): decode(v) for k, v in value.items()}
    return [decode(v) for v in value] if isinstance(value, list) else value


def fixture(name: str) -> dict[str, Any]:
    path = Path(__file__).parent / "fixtures" / name
    return json.loads(gzip.decompress(path.read_bytes()))


def test_real_dan_tc_research_and_housing_is_not_idle() -> None:
    data = fixture("dan-tc-research-housed.json.gz")
    assert data["recording_header"]["replay"].endswith("rec.aoe2record")
    history = BuildingHistory()
    catalog = W.Catalog(GameData(None))
    catalog.techs = {int(k): v for k, v in data["techs"].items()}
    legacy_false_idle = researched = housed = 0
    first, last = data["samples"][0], data["samples"][-1]
    for sample in data["samples"]:
        world = decode(sample["world"])
        history.sample(world, sample["time"])
        player = W.players_of(world)[1]
        for e in W.live_entities(world):
            if e.fields[W.E_MASTER] not in W.TOWN_CENTER_MASTERS:
                continue
            prod = W._production(
                e, catalog, player.fields[W.P_MASTERS], player.fields[W.P_RESEARCH]
            )
            assert prod and prod["queue"]  # TC stays queued throughout this real window
            legacy_false_idle += int(prod["current"] is None)
            researched += int("tech" in (prod["current"] or {}))
            housed += int(history.states[e.fields[W.E_ID]].activity == W.ACT_HOUSED)
    history.finish()
    assert researched > 100 and housed > 0 and legacy_false_idle > 0
    assert history.tc_idle(1, last["time"]) == 0
    assert first["villagers_created"] < last["villagers_created"]
    assert 101 not in first["research_done"] and 101 in last["research_done"]
    # Progress is never fabricated for a queued/housed action that is absent.
    assert any(a == W.ACT_HOUSED for log in history.logs.values() for _, a in log)


def test_real_dan_queue_handoff_has_near_zero_idle() -> None:
    data = fixture("dan-tc-handoff.json.gz")
    history = BuildingHistory()
    missing = 0
    for sample in data["samples"]:
        world = decode(sample["world"])
        history.sample(world, sample["time"])
        for e in W.live_entities(world):
            if e.fields[W.E_MASTER] in W.TOWN_CENTER_MASTERS:
                prod = W.production_state(e)
                missing += int(bool(prod and prod["queue"] and not prod["current"]))
    history.finish()
    assert missing > 0
    assert history.tc_idle(1, data["samples"][-1]["time"]) == 0
    assert data["samples"][-1]["villagers_created"] > data["samples"][0]["villagers_created"]


def scene() -> tuple[BuildingHistory, Node, Node]:
    world = decode(fixture("dan-tc-handoff.json.gz")["samples"][0]["world"])
    tc = next(e for e in W.live_entities(world) if e.fields[W.E_MASTER] in W.TOWN_CENTER_MASTERS)
    return BuildingHistory(), world, tc


def clear(tc: Node) -> None:
    tc.fields.pop(W.B_QUEUE_ACTION, None)
    tc.fields[W.B_QUEUE] = []


def test_deliberately_idle_tc_counts_the_entire_pause_not_pause_minus_grace() -> None:
    history, world, tc = scene()
    busy = deepcopy(tc.fields)
    history.sample(world, 0)
    clear(tc)
    history.sample(world, 1000)
    history.sample(world, 1500)
    assert history.tc_idle(1, 1500) == 0  # waiting to distinguish a handoff
    history.sample(world, 2000)
    assert history.tc_idle(1, 2000) == 1  # includes the first second
    tc.fields = busy
    history.sample(world, 11000)
    assert history.tc_idle(1, 11000) == 10
    assert history.logs[tc.fields[W.E_ID]][-2:] == [(1000, W.ACT_IDLE), (11000, W.ACT_PRODUCING)]


@pytest.mark.parametrize("master", [109, 12])  # TC and barracks use identical idle rules
def test_empty_subsecond_gap_between_items_is_working_for_all_buildings(master: int) -> None:
    history, world, tc = scene()
    player = W.players_of(world)[1]
    old = tc.fields[W.E_MASTER]
    player.fields[W.P_MASTERS][master] = player.fields[W.P_MASTERS][old]
    tc.fields[W.E_MASTER] = master
    busy = deepcopy(tc.fields)
    history.sample(world, 0)
    clear(tc)
    history.sample(world, 1000)
    tc.fields = busy
    history.sample(world, 1500)
    assert all(a != W.ACT_IDLE for _, a in history.logs[tc.fields[W.E_ID]])


def test_initial_idle_and_trailing_empty_queue_are_not_bridged() -> None:
    history, world, tc = scene()
    busy = deepcopy(tc.fields)
    clear(tc)
    history.sample(world, 0)
    tc.fields = busy
    history.sample(world, 500)
    clear(tc)
    history.sample(world, 1000)
    history.sample(world, 1500)
    history.finish()
    assert history.tc_idle(1, 1500) == 1  # initial 0.5 + final 0.5, not hidden


def test_idle_tc_total_is_union_not_sum_and_stops_at_destruction() -> None:
    history, world, tc = scene()
    clear(tc)
    twin = deepcopy(tc)
    twin.fields[W.E_ID] = 999999
    world.fields[W.W_ENTITIES][999999] = twin
    history.sample(world, 0)
    history.sample(world, 5000)
    world.fields[W.W_ENTITIES] = {}
    history.sample(world, 10000)
    assert history.tc_idle(1, 20000) == 10


def test_missing_stream_time_is_not_idle_or_a_queue_handoff() -> None:
    history, world, tc = scene()
    clear(tc)
    history.sample(world, 0)
    history.sample(world, 1000)
    history.sample(world, 5000, discontinuity=True)
    history.sample(world, 6000)
    assert history.tc_idle(1, 6000) == 2


def test_empty_transition_slot_and_zero_count_do_not_hide_the_next_real_item() -> None:
    prod = {
        "current": None,
        "queue": [
            {"unit": -1, "tech": -1, "count": 1},
            {"unit": 83, "tech": -1, "count": 0},
            {"unit": -1, "tech": 101, "count": 1},
        ],
    }
    assert W.building_activity(prod) == W.ACT_RESEARCHING


def test_timeline_housed_queue_is_separate_from_idle_and_building_activity_bar() -> None:
    tl = Timeline(GameData(None))
    tl.feed(snapshot_frame())

    def drop_action(builder: Any) -> None:
        builder.push_key(fid("World", "entities"), 100)
        builder.reset(fid("BuildingEntity", "currentProductionQueueAction")).pop()

    for t in range(0, 10001, 500):
        steps = [produce(100, VILLAGER, 0, 1), drop_action, set_attr(1, "maxPop", 0)]
        tl.feed(Frame(t, delta(t, *steps).forward()))
    tl.finish()
    view = tl.view_at(None)
    assert view is not None
    stats = view["players"]["1"]
    assert stats["tc_idle_seconds"] == 0 and stats["housed_seconds"] == 10
    assert stats["idle_tc_housed"] == [0, 10]
    assert tl._unit_activity(100, None).get("idle", 0) == 0
    assert tl._unit_activity(100, None)["housed"] == 10
