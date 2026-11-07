"""Review persistence retains context without changing legacy numeric bookmarks."""

import pytest

from vantage.review_moments import normalize_moments


def test_review_moment_context_round_trip():
    item = dict(
        id="raid",
        name="Raid",
        note="Check the workers",
        time=90000,
        player=2,
        fog="standard",
        camera=dict(x=30, y=40, zoom=1.2),
        selection=[9, 10, 9],
        range={"from": 80000, "to": 100000},
    )
    result = normalize_moments([item])[0]
    assert result == {**item, "selection": [9, 10]}
    assert normalize_moments([result]) == [result]


@pytest.mark.parametrize(
    "change",
    [
        {"time": float("nan")},
        {"time": -1},
        {"time": True},
        {"selection": [-1]},
        {"camera": {"zoom": float("inf")}},
        {"range": {"from": 100, "to": 50}},
        {"selection": [1] * 601},
    ],
)
def test_reject_invalid_review_context(change):
    with pytest.raises(ValueError):
        normalize_moments([{"time": 1000, **change}])


def test_tree_selections_and_camera_outside_map_remain_restorable():
    rows = normalize_moments(
        [
            dict(
                time=1000,
                camera=dict(x=-5, y=500, zoom=0.05),
                selection=[-2_000_000_010],
                selection_info={"-2000000010": {"mid": 411, "owner": 0}},
            )
        ]
    )
    assert rows[0]["camera"]["x"] == -5
    assert rows[0]["selection_info"]["-2000000010"]["owner"] == 0
