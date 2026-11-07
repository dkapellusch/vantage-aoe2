"""Known-target elevation effects, including the Projectile61c bypass."""

from __future__ import annotations

import gzip
import json
from pathlib import Path

import pytest

from vantage.replay_elevation_dispatch import dispatch_replay_elevation
from vantage.replay_movement_geometry import _bits
from vantage.replay_world_tile_height import replay_world_tile_height


def test_existing_native_leaf_cases_feed_each_established_policy_target():
    path = Path(__file__).parent / "fixtures/native_replay_elevation_54800.json.gz"
    fixture = json.loads(gzip.decompress(path.read_bytes()))
    assert fixture["target_sha256"] == (
        "69832b9d51145a4bb280da876880198ee0347947098e77098016b9bcbb8d8788"
    )
    assert len(fixture["cases"]) > 10000
    for mode, height, terrain, tile, returned, grounded in fixture["cases"]:
        base = dispatch_replay_elevation(
            height,
            terrain,
            target="base",
            elevation_mode=mode,
            has_tile=None,
        )
        assert base.height_bits == base.return_bits == returned
        assert base.grounded_write is None
        for target in ("moving", "projectile"):
            actual = dispatch_replay_elevation(
                height,
                terrain,
                target=target,
                elevation_mode=mode,
                has_tile=bool(tile),
                projectile_state61c=0,
            )
            assert actual.height_bits == actual.return_bits == returned
            assert actual.grounded_write is bool(grounded)


@pytest.mark.parametrize("state", [1, 2, 128, 255])
@pytest.mark.parametrize("height", [0x80000000, 0x7F800123, 0xFFC00321, _bits(9)])
def test_projectile_nonzero_bypasses_master_policy_and_tile_inputs(state, height):
    result = dispatch_replay_elevation(
        height,
        _bits(2),
        target="projectile",
        elevation_mode=None,
        has_tile=None,
        projectile_state61c=state,
    )
    assert result.height_bits == height
    assert result.return_bits == 0xC2C7CCCD
    assert result.grounded_write is False


def test_projectile_zero_uses_supplied_terrain_without_recomputing_it():
    terrain = replay_world_tile_height(
        (_bits(0.25), _bits(0.5)),
        slope_shape=2,
        base_elevation=3,
    )
    result = dispatch_replay_elevation(
        _bits(1),
        terrain.height_bits,
        target="projectile",
        elevation_mode=0,
        has_tile=True,
        projectile_state61c=0,
    )
    assert result.height_bits == result.return_bits == _bits(3.25)
    assert result.grounded_write is True


@pytest.mark.parametrize("height", [0x7F800001, 0x80000000, _bits(9)])
def test_base_preserves_grounded_field_and_returns_selected_raw_word(height):
    result = dispatch_replay_elevation(
        _bits(5),
        height,
        target="base",
        elevation_mode=0,
        has_tile=None,
    )
    assert result.height_bits == result.return_bits == height
    assert result.grounded_write is None


@pytest.mark.parametrize("target,state", [("moving", None), ("projectile", 0)])
def test_moving_return_can_differ_from_terrain_and_requires_a_tile_for_grounded(target, state):
    preserved = dispatch_replay_elevation(
        _bits(9),
        _bits(1),
        target=target,
        elevation_mode=1,
        has_tile=True,
        projectile_state61c=state,
    )
    assert preserved.height_bits == preserved.return_bits == _bits(9)
    assert preserved.grounded_write is False
    no_tile = dispatch_replay_elevation(
        0,
        0,
        target=target,
        elevation_mode=0,
        has_tile=False,
        projectile_state61c=state,
    )
    assert no_tile.grounded_write is False


@pytest.mark.parametrize("state", [None, True, -1, 256, 1.0])
def test_projectile_requires_an_explicit_current_state_byte(state):
    with pytest.raises(ValueError, match="byte61c"):
        dispatch_replay_elevation(
            0,
            0,
            target="projectile",
            elevation_mode=0,
            has_tile=True,
            projectile_state61c=state,
        )


@pytest.mark.parametrize("target,state", [("moving", None), ("projectile", 0)])
def test_moving_paths_reject_unknown_current_mode_or_tile_state(target, state):
    with pytest.raises(ValueError, match="current unsigned byte"):
        dispatch_replay_elevation(
            0,
            0,
            target=target,
            elevation_mode=None,
            has_tile=True,
            projectile_state61c=state,
        )
    with pytest.raises(ValueError, match="tile nullness"):
        dispatch_replay_elevation(
            0,
            0,
            target=target,
            elevation_mode=0,
            has_tile=None,
            projectile_state61c=state,
        )


@pytest.mark.parametrize("target", ["unknown", None, 60])
def test_family_tags_are_not_implicitly_used_as_dispatch_targets(target):
    with pytest.raises(ValueError, match="elevation target"):
        dispatch_replay_elevation(0, 0, target=target, elevation_mode=0, has_tile=True)


@pytest.mark.parametrize("word", [True, -1, 1 << 32, 0.5])
def test_raw_words_are_validated_even_on_projectile_bypass(word):
    with pytest.raises(ValueError, match="binary32 u32"):
        dispatch_replay_elevation(
            word,
            0,
            target="projectile",
            elevation_mode=None,
            has_tile=None,
            projectile_state61c=1,
        )
