"""Every resource in a real recording's stockpile is accounted for, once.

The fixtures replay the calls the timeline made to ``ResourceHistory.sample``
on real recordings (tools/extract_resource_fixture.py), pruned to the economy.
The ground truth here is independent of the accounting: the stockpile and the
game's collected counters, frame by frame.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any, ClassVar

import pytest

from vantage import world as W
from vantage.gamedata import GameData
from vantage.resource_review import ResourceHistory

RES = ("food", "wood", "stone", "gold")
FIXTURES = Path(__file__).parent / "fixtures"
_spec = importlib.util.spec_from_file_location(
    "extract_resource_fixture",
    Path(__file__).parent.parent / "tools" / "extract_resource_fixture.py",
)
assert _spec and _spec.loader
fixture_tool = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fixture_tool)


class DatFacts(GameData):
    """What ``GameData.starting_resource_techs`` reads from the installed dat
    (build 188329), so that the tests need no game."""

    starting_resource_techs: ClassVar = {  # type: ignore[misc]
        223: (8, [50.0, 50.0, 0.0, 0.0]),  # Persians
        224: (15, [0.0, 0.0, 0.0, 50.0]),  # Aztecs
        225: (17, [0.0, -100.0, 0.0, 0.0]),  # Huns
        226: (6, [-200.0, -50.0, 0.0, 0.0]),  # Chinese
        227: (16, [-50.0, 0.0, 0.0, 0.0]),  # Maya
        228: (37, [0.0, 0.0, 100.0, 0.0]),  # Sicilians
        1394: (59, [25.0, 25.0, 25.0, 25.0]),  # Tupi
    }


def replay(
    name: str, data: GameData | None = None
) -> tuple[ResourceHistory, dict[int, dict[str, Any]], int]:
    """Feed a fixture; returns the history, per-player ground truth, and the end time.

    Ground truth per player: the first and last stockpile and counter, and
    every per-frame stockpile change the counter does not explain, split
    into increases and decreases.
    """
    history = ResourceHistory(data or DatFacts(None))
    cache: dict[int, Any] = {}
    truth: dict[int, dict[str, Any]] = {}
    t = 0
    recorded = fixture_tool.load(FIXTURES / name)
    for frame in recorded["frames"]:
        world = fixture_tool.restore(frame, recorded["pool"], cache)
        t = frame["t"]
        history.sample(
            world,
            t,
            frame["events"],
            raw_events=frame["raw_events"],
            commands=frame["commands"],
            discontinuity=frame["discontinuity"],
        )
        history.checkpoint(t)
        for pid, player in W.players_of(world).items():
            stock = [W.attr(player, r) for r in RES]
            counter = [W.attr(player, r + "Total") for r in RES]
            row = truth.setdefault(
                pid,
                {"first": stock, "first_counter": counter, "up": [0.0] * 4, "down": [0.0] * 4},
            )
            if "stock" in row:
                for i in range(4):
                    other = stock[i] - row["stock"][i] - (counter[i] - row["counter"][i])
                    row["up" if other > 0 else "down"][i] += abs(other)
            row["stock"], row["counter"] = stock, counter
    return history, truth, t


def income_reported(history: ResourceHistory, pid: int, t: int) -> list[float]:
    """Everything the accounting says the player received, per resource."""
    return [sum(row["resources"][r] for row in history.player(pid, t)["sources"]) for r in RES]


def test_nomad_persians_starting_bonus_arrives_with_the_town_center() -> None:
    """2v2 Nomad, first 170 s. The Persian +50 food and wood is paid when the
    first Town Center is finished (2:35), outside the collected counters."""
    history, _, t = replay("nomad-persians-start.json.gz")
    persians = history.player(4, t)
    assert persians["bonus"] == {"food": 50, "wood": 50, "stone": 0, "gold": 0}
    assert [row["source"] for row in persians["sources"] if row["category"] == "bonus"] == [
        "Starting bonus"
    ]
    assert history.player(4, 155_000)["total"] == 0
    assert history.player(4, 156_000)["total"] == 100
    # Nomad starts with the Town Center's cost on top; no civilization share at 0:00.
    assert persians["starting"] == {"food": 200, "wood": 475, "stone": 300, "gold": 100}
    assert persians["starting_bonus"] == {r: 0 for r in RES}
    for pid in (1, 2, 3):
        assert history.player(pid, t)["total"] == 0


def test_nomad_starting_bonus_is_also_found_without_the_dat() -> None:
    """Then the stream's starting attributes stand in for the dat's techs."""
    history, _, t = replay("nomad-persians-start.json.gz", GameData(None))
    assert history.player(4, t)["bonus"] == {"food": 50, "wood": 50, "stone": 0, "gold": 0}


def test_chinese_start_with_less_food_and_wood_as_a_negative_starting_bonus() -> None:
    """A Chinese mirror: both start on 0 food and 150 wood. The stream's starting
    attributes read 0 here; the executed dat tech (226) carries the amounts."""
    history, truth, t = replay("chinese-mirror-start.json.gz")
    for pid in (1, 2):
        assert truth[pid]["first"] == [0, 150, 200, 100]
        income = history.player(pid, t)
        assert income["starting"] == {"food": 200, "wood": 200, "stone": 200, "gold": 100}
        assert income["starting_bonus"] == {"food": -200, "wood": -50, "stone": 0, "gold": 0}
        assert income["bonus"] == income["starting_bonus"] and income["total"] == -250
        assert income["not_gathered"] == {r: 0 for r in RES}


def test_persians_start_a_regular_map_with_the_bonus_inside_the_stockpile() -> None:
    """Six players, first frame at 0.05 s. Persians hold 50 food and wood more
    than the two other players who have spent the same; nobody else has a bonus."""
    history, truth, t = replay("persians-regular-start.json.gz")
    persians = history.player(6, t)
    assert persians["starting_bonus"] == {"food": 50, "wood": 50, "stone": 0, "gold": 0}
    assert [a - b for a, b in zip(truth[6]["first"], truth[5]["first"], strict=True)] == [
        50,
        50,
        0,
        0,
    ]
    assert persians["bonus"]["food"] == 50 and persians["bonus"]["wood"] == 50
    # In the starting stockpile already: never a later receipt, never collected.
    assert history.direct.get(6, [0.0] * 4) == [0.0] * 4
    for pid in (1, 2, 3, 4, 5):
        assert history.player(pid, t)["starting_bonus"] == {r: 0 for r in RES}


@pytest.mark.parametrize(
    "name,players",
    [
        ("chinese-mirror-start.json.gz", (1, 2)),
        ("persians-regular-start.json.gz", (1, 2, 3, 4, 5, 6)),
        ("nomad-persians-start.json.gz", (1, 2, 3, 4)),
        ("dravidians-age-up.json.gz", (1,)),
        ("khmer-farm-counter-drift.json.gz", (3,)),
    ],
)
def test_real_recording_stockpiles_reconcile(name: str, players: tuple[int, ...]) -> None:
    history, truth, t = replay(name)
    for pid in players:
        income = history.player(pid, t)
        row = truth[pid]
        assert income["unexplained"] == {r: 0 for r in RES}, (pid, income["unexplained"])
        for i, r in enumerate(RES):
            counted = row["counter"][i] - row["first_counter"][i]
            # Paid past the counters: direct grants and counter-lost farm food.
            direct = history.direct.get(pid, [0.0] * 4)[i]
            market = income["market_in"][r] - income["market_out"][r]
            assert row["first"][i] + counted + direct + market + income["refunds"][r] - income[
                "spent"
            ][r] == pytest.approx(row["stock"][i], abs=0.5), (pid, r)
            # Nothing is spent that the stockpile did not lose, and nothing is
            # granted or refunded that it did not gain.
            assert income["spent"][r] - income["market_out"][r] <= row["down"][i] + 0.5
            assert direct + income["refunds"][r] <= row["up"][i] + 0.5
            # Collected and Bonus never overlap: together with trade and sales
            # they are the counter, plus what was paid past it.
            in_counter = sum(
                s["resources"][r]
                for s in income["sources"]
                if s["category"] in ("regular", "unattributed")
            )
            assert in_counter + income["not_gathered"][r] == pytest.approx(
                counted + income["uncounted"][r], abs=0.5
            ), (pid, r)


def test_dravidian_age_up_wood_is_bonus_not_collected() -> None:
    """1v1, 9:00-9:30. Feudal Age pays 200 wood straight into the stockpile."""
    history, truth, t = replay("dravidians-age-up.json.gz")
    income = history.player(1, t)
    assert income["bonus"]["wood"] == 200
    assert income["not_gathered"]["wood"] == 0  # the counter never saw it
    assert truth[1]["up"][1] >= 200


def test_khmer_direct_farming_food_lost_by_the_counter_is_still_collected() -> None:
    """2v2, 52:00-53:00. Once foodTotal passes 8192 the game's float counter
    drops the per-tick food of direct (Khmer) farming; the stockpile keeps it."""
    history, truth, t = replay("khmer-farm-counter-drift.json.gz")
    income = history.player(3, t)
    row = truth[3]
    assert row["first_counter"][0] < 8192 < row["counter"][0]
    assert 2 < income["uncounted"]["food"] < 30
    assert income["unexplained"]["food"] == 0
    counted = row["counter"][0] - row["first_counter"][0]
    assert income_reported(history, 3, t)[0] == pytest.approx(
        counted + income["uncounted"]["food"], abs=0.5
    )
