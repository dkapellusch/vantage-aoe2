"""Pin actual farm stream fields and compare the same replay's desktop capture."""

from __future__ import annotations

import gzip
import json
from functools import lru_cache
from pathlib import Path
from typing import Any

import pytest

from vantage.building_activity import BuildingHistory
from vantage.gamedata import GameData
from vantage.patch import Node
from vantage.schema import SCHEMA
from vantage.timeline import Timeline


def captured(name: str) -> Timeline:
    data = json.loads(gzip.decompress((Path(__file__).parent / "fixtures" / name).read_bytes()))

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

    history = BuildingHistory()
    for sample in data["samples"]:
        history.sample(decode(sample["world"]), sample["time"], discontinuity=sample["skipped"])
    history.finish()
    timeline = Timeline(GameData(None))
    timeline.time = data["samples"][-1]["time"]
    timeline.building_history = history
    node.cache_clear()
    return timeline


@pytest.mark.parametrize(
    "name,eid,idle",
    [
        ("monoz-farm-moykyzcd4ivqs-buildings.json.gz", 2367, 1.0),
        ("monoz-farm-mqbf7pgwd76jh-buildings.json.gz", 2865, 6.0),
    ],
)
def test_monoz_farm_tc_is_working_at_12m07_not_idle_its_entire_age(
    name: str,
    eid: int,
    idle: float,
) -> None:
    timeline = captured(name)
    stats = timeline.group_stats([eid], 727000)
    assert stats["activity_kind"] == "building"
    assert stats["activity_scope"].get("idle", 0) == pytest.approx(idle, abs=0.1)
    assert stats["activity_scope"].get("producing", 0) > 500
    assert stats["activity_scope"].get("researching", 0) > 100
    assert timeline.unit_stats(eid, 727000, 667000)["activity_scope"] == {"producing": 60.0}


def test_same_real_replay_farm_and_desktop_building_activity_match() -> None:
    farm = captured("dan-nov11-farm-buildings.json.gz")
    desktop = captured("dan-nov11-building-panels.json.gz")
    # Both fixtures are separately decoded recordings of Dan's exact replay.
    # Pin the TC, continuously training Barracks and an initially unused one,
    # with lifetime, last-minute and Fight queries at real replay times.
    for eid, end, since in [
        (9129, 3508724, None),
        (9129, 1500000, 1200000),
        (9129, 3508724, 3448724),
        (21721, 2630055, None),
        (11959, 3286054, 3215071),
        (11959, 1000000, None),
    ]:
        a = farm.group_stats([eid], end, since)["activity_scope"]
        b = desktop.group_stats([eid], end, since)["activity_scope"]
        assert a.keys() == b.keys()
        for activity in a:
            assert a[activity] == pytest.approx(b[activity], abs=1.5), (eid, activity, a, b)
    assert farm.building_history.tc_idle_stats(1, farm.time)["tc_idle_seconds"] == 210
