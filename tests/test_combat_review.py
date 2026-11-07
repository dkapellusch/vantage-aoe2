"""Military review calculations use event-time costs and non-overlapping intervals."""

from __future__ import annotations

import pytest

from tests.helpers import (
    KNIGHT,
    delta,
    kill_entity,
    set_master_cost,
    snapshot_frame,
)
from vantage import world as W
from vantage.combat_review import PressureTracker, PressureWorker, military_review
from vantage.frames import Frame
from vantage.gamedata import GameData
from vantage.timeline import Timeline


def test_destruction_values_are_scoped_and_unknown_is_not_zero() -> None:
    log = [
        (1000, "destroyed_food", 60.0, 38),
        (1000, "destroyed_gold", 75.0, 38),
        (3000, "destroyed_unknown", 1.0, -1),
    ]
    known = military_review(log, 2000)
    assert known["destroyed_value"] == 135
    assert known["resources_destroyed"] == {"food": 60, "wood": 0, "stone": 0, "gold": 75}
    all_time = military_review(log, 4000)
    assert all_time["destroyed_value"] is None
    assert all_time["destroyed_known_value"] == 135 and all_time["destroyed_unknown"] == 1
    assert military_review(log, 4000, since=2000)["destroyed_known_value"] == 0


@pytest.mark.parametrize(
    "since,end,seconds", [(None, 5000, 4), (2000, 4000, 2), (6000, 7000, 0), (0, 2000, 1)]
)
def test_pressure_intervals_clip_at_both_ends(since: int | None, end: int, seconds: int) -> None:
    # The end of the recorded interval can be later than the requested replay time.
    result = military_review([(5000, "forced_idle", 4.0, 9)], end, since)
    assert result["forced_idle_seconds"] == seconds
    assert result["forced_idle_estimated"] is True


def test_pressure_requires_a_working_victim_and_observed_disruption() -> None:
    tracker = PressureTracker()
    assert tracker.hit(9, 1, 0, working=False) == []
    assert not tracker.active
    tracker.hit(9, 1, 100, working=True)
    working = PressureWorker(True, True, 1, 1)
    assert tracker.sample(1000, {9: working}, {1: (1, 2)}) == []
    assert not tracker.active


def test_pressure_credit_switches_without_double_counting() -> None:
    tracker = PressureTracker()
    tracker.hit(9, 1, 0, working=True)
    worker = PressureWorker(False, True, 1, 1)
    assert tracker.sample(1000, {9: worker}, {1: (1, 2)}) == []
    first = tracker.sample(2000, {9: worker}, {1: (1, 2)})
    switch = tracker.hit(9, 2, 2500, working=False)
    last = tracker.sample(4000, {9: worker}, {2: (1, 2)})
    assert first + switch + last == [(1, 1000, 2000, 9), (1, 2000, 2500, 9), (2, 2500, 4000, 9)]


@pytest.mark.parametrize(
    "worker,attackers",
    [
        (PressureWorker(False, False, 1, 1), {1: (1, 2)}),
        (PressureWorker(True, True, 1, 1), {1: (1, 2)}),
        (PressureWorker(False, True, 100, 100), {1: (1, 2)}),
        (PressureWorker(False, True, 1, 1), {}),
    ],
)
def test_pressure_stops_on_death_work_distance_or_missing_attacker(
    worker: PressureWorker, attackers: dict[int, tuple[float, float]]
) -> None:
    tracker = PressureTracker()
    tracker.hit(9, 1, 0, working=True)
    tracker.sample(1000, {9: PressureWorker(False, True, 1, 1)}, {1: (1, 2)})
    assert tracker.sample(2000, {9: worker}, attackers) == []
    assert not tracker.active


def test_pressure_expires_at_threat_timeout() -> None:
    tracker = PressureTracker()
    tracker.hit(9, 1, 0, working=True)
    workers = {9: PressureWorker(False, True, 1, 1)}
    tracker.sample(1000, workers, {1: (1, 2)})
    assert tracker.sample(20_000, workers, {1: (1, 2)}) == [(1, 1000, 15_000, 9)]
    assert not tracker.active


def test_killing_blow_and_entitykilled_count_once_and_freeze_victim_cost() -> None:
    timeline = Timeline(GameData(None))
    timeline.feed(snapshot_frame())
    # Kill the opponent's knight. Its cost must come from the victim, not the attacker.
    events = [
        {
            "kind": "damage",
            "attackerid": 101,
            "entityid": 104,
            "damage": 100,
            "iskillingblow": True,
        },
        {"kind": "entitykilled", "id": 104, "killerid": 101},
    ]
    timeline.feed(Frame(1000, delta(1000, kill_entity(104)).forward(), b"", events, []))
    result = timeline.unit_stats(101, 1000)
    assert result["kills"] == 1 and result["destroyed_value"] == 135
    assert timeline.unit_stats(104, 1000)["died"] == 1
    assert timeline.group_stats([101, 101], 1000)["destroyed_value"] == 135
    timeline.feed(
        Frame(2000, delta(2000, set_master_cost(2, KNIGHT, ((0, 1.0),))).forward(), b"", [], [])
    )
    assert timeline.unit_stats(101)["destroyed_value"] == 135
    assert timeline.unit_stats(101, 500)["destroyed_value"] == 0
    assert timeline.unit_stats(101, 2000, 1500)["kills"] == 0


def test_entitykilled_without_damage_records_the_death() -> None:
    timeline = Timeline(GameData(None))
    timeline.feed(snapshot_frame())
    timeline.feed(
        Frame(
            1000,
            delta(1000, kill_entity(104)).forward(),
            b"",
            [{"kind": "entitykilled", "id": 104, "killerid": 101}],
            [],
        )
    )
    assert timeline.unit_stats(104)["died"] == 1


def test_friendly_kills_do_not_destroy_enemy_resource_value() -> None:
    timeline = Timeline(GameData(None))
    timeline.feed(snapshot_frame())
    timeline.feed(
        Frame(
            1000,
            delta(1000, kill_entity(102)).forward(),
            b"",
            [{"kind": "entitykilled", "id": 102, "killerid": 101}],
            [],
        )
    )
    assert timeline.unit_stats(101)["friendly_kills"] == 1
    assert timeline.unit_stats(101)["destroyed_value"] == 0
    assert timeline.unit_stats(102)["died"] == 1


def test_group_activity_and_combat_are_clipped_to_requested_interval() -> None:
    timeline = Timeline(GameData(None))
    timeline.time = 10_000
    timeline.unit_log[7] = [(1000, "kill", 1, 38), (8000, "kill", 1, 38)]
    timeline.activity_log[7] = [(0, W.ACT_IDLE), (6000, W.ACT_MOVING)]
    group = timeline.group_stats([7, 7], 10_000, since=5000)
    assert group["totals"]["kills"] == 1
    assert group["activity_scope"] == {"idle": 1, "moving": 4}


def test_expired_pressure_cannot_be_revived_by_hitting_an_idle_worker():
    tracker = PressureTracker()
    tracker.hit(9, 1, 0, working=True)
    tracker.sample(1000, {9: PressureWorker(False, True, 1, 1)}, {1: (1, 2)})
    assert tracker.hit(9, 2, 20000, working=False) == []
    assert not tracker.active


def test_idle_stops_at_death_and_excludes_missing_stream_intervals():
    timeline = Timeline(GameData(None))
    timeline.time = 20000
    timeline.activity_log[101] = [(0, W.ACT_IDLE)]
    timeline.unit_log[101] = [(10000, "died", 1.0, -1)]
    timeline.skips = [[2000, 5000]]
    assert timeline.group_stats([101], 20000)["activity_scope"] == {"idle": 7.0}
    assert timeline.group_stats([101], 20000, 8000)["activity_scope"] == {"idle": 2.0}


def test_timeline_attack_records_garrisoned_worker_downtime_and_stops_on_work():
    from tests.helpers import set_entity

    timeline = Timeline(GameData(None))
    timeline.feed(snapshot_frame())
    hit = [{"kind": "damage", "attackerid": 104, "entityid": 103, "damage": 1}]
    timeline.feed(
        Frame(
            1000,
            delta(1000, set_entity(103, "Entity", "insideObjId", "Int32", 100)).forward(),
            events=hit,
        )
    )
    timeline.feed(Frame(2000, delta(2000).forward()))
    assert timeline.unit_stats(104, 2000)["forced_idle_seconds"] == 1
    assert timeline.unit_stats(104, 2000, 1500)["forced_idle_seconds"] == 0.5
    timeline.feed(
        Frame(3000, delta(3000, set_entity(103, "Entity", "insideObjId", "Int32", -1)).forward())
    )
    timeline.feed(Frame(4000, delta(4000).forward()))
    assert timeline.unit_stats(104, 4000)["forced_idle_seconds"] == 1
    assert timeline.unit_stats(103, 4000)["activity"]["garrisoned"] == 2


def test_kill_uses_victim_owner_discount_at_the_time_of_death():
    timeline = Timeline(GameData(None))
    timeline.feed(snapshot_frame())
    timeline.feed(
        Frame(500, delta(500, set_master_cost(2, KNIGHT, ((0, 30.0), (3, 40.0)))).forward())
    )
    timeline.feed(
        Frame(
            1000,
            delta(1000, kill_entity(104)).forward(),
            events=[{"kind": "entitykilled", "id": 104, "killerid": 101}],
        )
    )
    assert timeline.unit_stats(101)["destroyed_value"] == 70
