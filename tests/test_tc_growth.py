"""Growth windows pinned to decoded source fields from Dan and Hera's games."""

from __future__ import annotations

import gzip
import json
from copy import deepcopy
from functools import lru_cache
from pathlib import Path
from typing import Any

import pytest

from tests.test_building_activity import clear, scene
from vantage import world as W
from vantage.building_activity import BuildingHistory
from vantage.patch import Node
from vantage.schema import SCHEMA


@pytest.mark.parametrize(
    "name,growth,whole,cutoff,digest",
    [
        (
            "dan-nov10",
            156,
            725,
            1912558,
            "69a1d28c9b2d1de285a0b8c75e3416a36305b3352518cc6d749774ec7af99483",
        ),
        (
            "dan-nov11",
            210,
            1193,
            2118080,
            "232dcd37eaf72b66acb1332b456894957b307a77e85ce46644df26a21e16877a",
        ),
        ("hera", 43, 43, None, "2548554b272cdfb4686cd826ba314eb2bc2c521162b0e7c776ff09355c890594"),
    ],
)
def test_real_growth_and_whole_game_totals(
    name: str, growth: int, whole: int, cutoff: int | None, digest: str
) -> None:
    data = json.loads(
        gzip.decompress(
            (Path(__file__).parent / "fixtures" / f"{name}-tc-growth.json.gz").read_bytes()
        )
    )
    assert data["sha256"] == digest

    @lru_cache(None)
    def node(index: int) -> Node:
        row = data["nodes"][index]
        model = SCHEMA.model_id(row["model"])
        return Node(model, {SCHEMA.fid(model, k): decode(v) for k, v in row["fields"].items()})

    def decode(value: Any) -> Any:
        if isinstance(value, dict):
            if "$" in value:
                return node(value["$"])
            return {int(k): decode(v) for k, v in value.items()}
        return [decode(v) for v in value] if isinstance(value, list) else value

    history = BuildingHistory()
    for sample in data["samples"]:
        history.sample(decode(sample["world"]), sample["time"], discontinuity=sample["skipped"])
    history.finish()
    stats = history.tc_idle_stats(1, data["samples"][-1]["time"])
    assert stats["tc_idle_seconds"] == growth
    assert stats["tc_idle_whole_seconds"] == whole
    assert stats["tc_idle_growth"]["cutoff_ms"] == cutoff
    assert stats["tc_idle_growth"]["reason"] == ("villagers" if cutoff else None)
    # A rewind cannot disclose a future cutoff; whole-game remains available.
    if cutoff:
        assert history.tc_idle_stats(1, cutoff - 1)["tc_idle_growth"]["cutoff_ms"] is None
    node.cache_clear()


def set_attr(world: Node, name: str, value: float) -> None:
    attrs = W.players_of(world)[1].fields[W.P_ATTR]
    attrs.fields[SCHEMA.fid(attrs.model, name)] = value


def test_population_limit_ends_window_not_house_capacity_and_never_reopens() -> None:
    history, world, tc = scene()
    clear(tc)
    set_attr(world, "unitLimit", 200)
    set_attr(world, "maxPop", 0)  # being housed does not end growth
    set_attr(world, "population", 50)
    history.sample(world, 0)
    history.sample(world, 10000)
    assert not history.cutoffs
    set_attr(world, "population", 200)
    history.sample(world, 15000)
    set_attr(world, "population", 100)
    history.sample(world, 30000)
    assert history.tc_idle_stats(1, 30000) == {
        "tc_idle_seconds": 15,
        "tc_idle_whole_seconds": 30,
        "tc_idle_growth": {
            "villager_target": 120,
            "cutoff_ms": 15000,
            "reason": "population",
            "through_ms": 15000,
        },
    }


def test_configurable_living_target_late_completion_and_overlapping_union() -> None:
    _, world, tc = scene()
    history = BuildingHistory(villager_target=2)
    # Keep a single real civilian; counts are living entities, never createdTotal.
    player = W.players_of(world)[1]
    civilian = next(
        mid for mid, m in player.fields[W.P_MASTERS].items() if m.fields.get(W.M_CLASS) == 4
    )
    villager = Node(
        tc.model, {W.E_ID: 90001, W.E_OWNER: 1, W.E_MASTER: civilian, W.E_STATE: W.ENTITY_ALIVE}
    )
    world.fields[W.W_ENTITIES] = {tc.fields[W.E_ID]: tc, 90001: villager}
    clear(tc)
    tc.fields[W.B_BUILT] = False
    history.sample(world, 0)
    tc.fields[W.B_BUILT] = True
    history.sample(world, 1000)
    twin = deepcopy(tc)
    twin.fields[W.E_ID] = 90002
    world.fields[W.W_ENTITIES][90002] = twin
    history.sample(world, 2000)
    villager2 = deepcopy(villager)
    villager2.fields[W.E_ID] = 90003
    world.fields[W.W_ENTITIES][90003] = villager2
    history.sample(world, 5000)
    assert history.tc_idle_stats(1, 5000)["tc_idle_seconds"] == 4  # union, starts at completion
    del world.fields[W.W_ENTITIES][90003]
    # Another TC completed after the cutoff only contributes to the whole game.
    twin2 = deepcopy(tc)
    twin2.fields[W.E_ID] = 90004
    world.fields[W.W_ENTITIES][90004] = twin2
    history.sample(world, 10000)
    stats = history.tc_idle_stats(1, 10000)
    assert stats["tc_idle_seconds"] == 4 and stats["tc_idle_whole_seconds"] == 9
    assert stats["tc_idle_growth"]["cutoff_ms"] == 5000


def test_invalid_target() -> None:
    with pytest.raises(ValueError, match="positive"):
        BuildingHistory(0)


def test_timeline_views_pairs_series_and_review_summary_share_configured_window() -> None:
    from tests.helpers import game_frames
    from vantage.gamedata import GameData
    from vantage.timeline import Timeline

    tl = Timeline(GameData(None), tc_idle_villagers=1)
    for frame in game_frames(12):
        assert tl.feed(frame)
    tl.finish()
    view = tl.view_at(None)
    assert view is not None
    s = view["players"]["1"]
    summary = tl.summary()["1"]
    assert s["tc_idle_growth"]["villager_target"] == 1
    assert s["tc_idle_growth"]["cutoff_ms"] == 0
    assert s["tc_idle_seconds"] == s["idle_tc_housed"][0] == summary["tc_idle_seconds"] == 0
    assert s["tc_idle_whole_seconds"] == summary["tc_idle_whole_seconds"] > 0
    assert s["tc_idle_growth"] == summary["tc_idle_growth"]
    assert all(row["tc_idle"] == 0 for row in tl.series_json()["1"])
