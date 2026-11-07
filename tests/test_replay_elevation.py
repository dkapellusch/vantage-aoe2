"""Portable output of unchanged native elevation policy and grounded wrapper."""

from __future__ import annotations

import gzip
import json
from pathlib import Path

import pytest

from vantage.replay_elevation import update_replay_elevation


def test_all_native_elevation_cases_match_exact_words_and_flags() -> None:
    path = Path(__file__).parent / "fixtures/native_replay_elevation_54800.json.gz"
    fixture = json.loads(gzip.decompress(path.read_bytes()))
    assert fixture["target_sha256"] == (
        "69832b9d51145a4bb280da876880198ee0347947098e77098016b9bcbb8d8788"
    )
    assert {row[0] for row in fixture["cases"]} == set(range(256))
    assert len(fixture["cases"]) > 10000
    for mode, height, terrain, tile, result, grounded in fixture["cases"]:
        actual = update_replay_elevation(height, terrain, mode, has_tile=bool(tile))
        assert (actual.height_bits, actual.grounded) == (result, bool(grounded))


def test_raise_only_preserves_airborne_height_and_signed_zero() -> None:
    assert update_replay_elevation(0x41100000, 0x3F800000, 1, has_tile=True).height_bits == (
        0x41100000
    )
    result = update_replay_elevation(0x80000000, 0, 1, has_tile=True)
    assert result.height_bits == 0x80000000
    assert result.grounded


def test_grounded_needs_tile_and_nan_never_compares_equal() -> None:
    assert not update_replay_elevation(0, 0, 0, has_tile=False).grounded
    result = update_replay_elevation(0, 0x7F800001, 0, has_tile=True)
    assert result.height_bits == 0x7F800001
    assert not result.grounded


@pytest.mark.parametrize("bad", [-1, 0x100000000, 1.0, None])
@pytest.mark.parametrize("field", ["height", "terrain"])
def test_invalid_height_words_are_rejected(bad: int, field: str) -> None:
    with pytest.raises(ValueError, match="binary32 u32"):
        update_replay_elevation(
            bad if field == "height" else 0, bad if field == "terrain" else 0, 0, has_tile=True
        )


@pytest.mark.parametrize("bad", [-1, 256, 1.0, None])
def test_invalid_modes_are_rejected(bad: int) -> None:
    with pytest.raises(ValueError, match="native byte"):
        update_replay_elevation(0, 0, bad, has_tile=True)


@pytest.mark.parametrize("bad", [0, 1, None, "yes"])
def test_tile_presence_must_be_explicit_bool(bad: bool) -> None:
    with pytest.raises(ValueError, match="must be a bool"):
        update_replay_elevation(0, 0, 0, has_tile=bad)
