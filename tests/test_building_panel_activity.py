"""Inspector /api/group activity pinned to Dan's decoded November 11 queues."""

from __future__ import annotations

import gzip
import json
from functools import lru_cache
from pathlib import Path
from typing import Any

import pytest

from vantage import world as W
from vantage.building_activity import BuildingHistory
from vantage.gamedata import GameData
from vantage.patch import Node
from vantage.schema import SCHEMA
from vantage.timeline import Timeline


@pytest.fixture(scope="module")
def dan() -> Timeline:
    data = json.loads(
        gzip.decompress(
            (Path(__file__).parent / "fixtures" / "dan-nov11-building-panels.json.gz").read_bytes()
        )
    )
    assert data["sha256"] == "232dcd37eaf72b66acb1332b456894957b307a77e85ce46644df26a21e16877a"

    @lru_cache(None)
    def node(index: int) -> Node:
        row = data["nodes"][index]
        model = SCHEMA.model_id(row["model"])
        return Node(model, {SCHEMA.fid(model, k): decode(v) for k, v in row["fields"].items()})

    def decode(value: Any) -> Any:
        if isinstance(value, dict):
            return (
                node(value["$"]) if "$" in value else {int(k): decode(v) for k, v in value.items()}
            )
        return [decode(v) for v in value] if isinstance(value, list) else value

    # Feed authentic queue, completion, research and population fields at every
    # original sample. Other Timeline subsystems need no fabricated world/HUD.
    history = BuildingHistory()
    for sample in data["samples"]:
        history.sample(decode(sample["world"]), sample["time"], discontinuity=sample["skipped"])
    history.finish()
    timeline = Timeline(GameData(None))
    timeline.time = data["samples"][-1]["time"]
    timeline.building_history = history
    timeline.activity_log.update(history.logs)
    node.cache_clear()
    return timeline


def test_tc_9129_inspector_life_and_growth_are_queue_time_not_age(dan: Timeline) -> None:
    life = dan.group_stats([9129])
    assert life["activity_kind"] == "building"
    assert life["activity_scope"] == {
        "idle": 955.7,
        "producing": 1912.5,
        "researching": 570.0,
        "housed": 69.0,
        "population_limit": 1.5,
    }
    assert life["activity_scope"] == dan.unit_stats(9129)["activity"]
    assert sum(life["activity_scope"].values()) == pytest.approx(3508.7, abs=0.1)
    # Its own growth-window idle is 34s, distinct from the player's 210s union.
    cutoff = dan.building_history.cutoffs[1][0]
    assert dan.group_stats([9129], cutoff)["activity_scope"]["idle"] == 34.0
    assert dan.building_history.tc_idle_stats(1, dan.time)["tc_idle_seconds"] == 210


@pytest.mark.parametrize("since,end,idle", [(3448724, 3508724, 60.0), (1200000, 1500000, 8.5)])
def test_tc_minute_and_fight_scopes(dan: Timeline, since: int, end: int, idle: float) -> None:
    group = dan.group_stats([9129], end, since)
    unit = dan.unit_stats(9129, end, since)
    assert group["activity_scope"] == unit["activity_scope"]
    assert group["activity_scope"].get("idle", 0) == idle
    assert sum(group["activity_scope"].values()) == pytest.approx((end - since) / 1000, abs=0.2)


def test_continuously_training_real_barracks_has_zero_idle_in_all_scopes(dan: Timeline) -> None:
    # Barracks 21721 works immediately on completion, with no lifetime idle.
    life = dan.group_stats([21721], 2630055)["activity_scope"]
    assert life.get("idle", 0) == 0
    assert life["producing"] > 35
    # Real Barracks 11959 trains throughout 53:35.071-54:46.055.
    for start in (3215071, 3226054):
        stats = dan.group_stats([11959], 3286054, start)
        assert stats["activity_scope"] == {"producing": round((3286054 - start) / 1000, 1)}
        assert stats["activity_kind"] == "building"


def test_unused_building_counts_from_completion_not_its_foundation(dan: Timeline) -> None:
    log = dan.building_history.logs[11959]
    completed = next(t for t, act in log if act == W.ACT_IDLE)
    first_work = next(t for t, act in log if act in (W.ACT_PRODUCING, W.ACT_RESEARCHING))
    result = dan.group_stats([11959], first_work - 1)["activity_scope"]
    assert result["idle"] == round((first_work - 1 - completed) / 1000, 1)
    assert result.get("producing", 0) == result.get("researching", 0) == 0


def test_destroyed_building_does_not_move_minute_or_fight_window_back_to_death() -> None:
    tl = Timeline(GameData(None))
    tl.time = 200000
    tl.building_history.logs[1] = [(0, W.ACT_IDLE)]
    tl.building_history.ended[1] = 100000
    assert tl.group_stats([1], 200000)["activity_scope"] == {"idle": 100}
    assert tl.group_stats([1], 200000, 140000)["activity_scope"] == {}
    assert tl.group_stats([1], 200000, 90000)["activity_scope"] == {"idle": 10}


def test_building_queue_history_wins_over_generic_unit_task_fallback() -> None:
    tl = Timeline(GameData(None))
    tl.time = 60000
    tl.activity_log[1] = [(0, W.ACT_IDLE)]
    tl.building_history.logs[1] = [
        (0, W.ACT_PRODUCING),
        (30000, W.ACT_RESEARCHING),
        (45000, W.ACT_HOUSED),
    ]
    expected = {"producing": 30, "researching": 15, "housed": 15}
    assert tl.group_stats([1])["activity_scope"] == expected
    assert tl.unit_stats(1)["activity"] == expected
    assert tl.group_stats([1], 120000, 60000)["activity_scope"] == {}  # no future extrapolation
