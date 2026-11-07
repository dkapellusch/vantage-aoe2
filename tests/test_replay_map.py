"""Terrain geometry compared with native snapshots, including all 17 shapes."""

from __future__ import annotations

import gzip
import json
from pathlib import Path

import pytest

from vantage.replay_map import slope_shapes


def test_saved_elevations_reproduce_all_native_slope_shapes() -> None:
    path = Path(__file__).parent / "fixtures" / "native_replay_terrain_54800.json.gz"
    cases = json.loads(gzip.decompress(path.read_bytes()))["cases"]
    total = 0
    shapes = set()
    for case in cases:
        actual = slope_shapes(case["elevations"], case["width"], case["height"])
        assert actual == tuple(case["expected_shapes"])
        shapes.update(actual)
        total += len(actual)
    assert total == 60_736
    assert shapes == set(range(17))


@pytest.mark.parametrize(
    "levels,width,height",
    [([], 0, 0), ([0], 0, 1), ([0], 1, -1), ([0], 2, 1), ([256], 1, 1), ([-1], 1, 1)],
)
def test_invalid_grid_is_rejected(levels: list[int], width: int, height: int) -> None:
    with pytest.raises(ValueError):
        slope_shapes(levels, width, height)


@pytest.mark.parametrize("width,height", [(1, 1), (1, 10), (10, 1), (2, 3)])
def test_flat_rectangles_and_borders_have_no_slope(width: int, height: int) -> None:
    assert slope_shapes([7] * (width * height), width, height) == (0,) * (width * height)
