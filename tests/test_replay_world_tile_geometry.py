"""Native-source coordinate boundaries; no full position-setter claim."""

from __future__ import annotations

import pytest

from vantage.replay_movement_geometry import _bits
from vantage.replay_world_tile_geometry import (
    clamp_replay_moving_tile_xy,
    replay_world_tile_coordinates,
    replay_world_tile_plane_coordinates,
)
from vantage.replay_world_tiles import ReplayWorldTileRegistry


def test_common_selects_tile_and_keeps_native_fraction_order():
    result = replay_world_tile_coordinates(
        (_bits(2.75), _bits(1.5)),
        width=7,
        height=3,
        upper_bounds_bits=(_bits(7), _bits(3)),
    )
    assert result.xy_bits == (_bits(2.75), _bits(1.5))
    assert result.fraction_bits == (_bits(0.75), _bits(0.5))
    assert result.tile_coordinates == result.plane_coordinates == (2, 1)
    assert result.tile_index == result.plane_index == 9


def test_common_clamps_negative_and_each_independent_float_upper_bound():
    result = replay_world_tile_coordinates(
        (_bits(-100), _bits(10)),
        width=200,
        height=10,
        upper_bounds_bits=(_bits(200), _bits(10)),
    )
    assert result.xy_bits == (0, 0x411FFBE7)
    assert result.tile_coordinates == (0, 9)
    assert result.fraction_bits == (0, 0x3F7FBE70)


def test_float_bounds_do_not_replace_integer_dimensions_or_plane_address():
    result = replay_world_tile_coordinates(
        (_bits(3.5), _bits(2.5)),
        width=3,
        height=2,
        upper_bounds_bits=(_bits(4), _bits(4)),
    )
    assert result.tile_coordinates == (2, 1) and result.tile_index == 5
    assert result.plane_coordinates == (3, 2) and result.plane_index == 9
    registry = ReplayWorldTileRegistry.empty(3, 2, {7: _bits(1)})
    before = registry.snapshot()
    with pytest.raises(ValueError, match="plane address"):
        registry.append(result.tile_index, 7, plane_coordinates=result.plane_coordinates)
    assert registry.snapshot() == before


def test_large_map_float_margin_can_round_back_to_the_upper_bound():
    result = replay_world_tile_coordinates(
        (_bits(1 << 20), 0),
        width=1 << 20,
        height=1,
        upper_bounds_bits=(_bits(1 << 20), _bits(1)),
    )
    assert result.xy_bits == (_bits(1 << 20), 0)
    assert result.plane_coordinates == (1 << 20, 0)
    assert result.tile_index == (1 << 20) - 1
    assert result.plane_index == 1 << 20


def test_common_maxss_keeps_negative_zero_in_position_and_fraction():
    result = replay_world_tile_coordinates(
        (0x80000000, 0x80000000),
        width=2,
        height=2,
        upper_bounds_bits=(_bits(2), _bits(2)),
    )
    assert result.xy_bits == result.fraction_bits == (0x80000000, 0x80000000)
    assert result.plane_coordinates == result.tile_coordinates == (0, 0)


@pytest.mark.parametrize("nan", [0x7F800001, 0x7FC12345, 0xFF800001, 0xFFC12345])
def test_common_maxss_preserves_nan_word_but_fraction_arithmetic_quiets_it(nan):
    result = replay_world_tile_coordinates(
        (nan, nan),
        width=3,
        height=2,
        upper_bounds_bits=(_bits(3), _bits(2)),
    )
    assert result.xy_bits == (nan, nan)
    assert result.fraction_bits == (nan | 0x400000, nan | 0x400000)
    assert result.plane_coordinates == (-(1 << 31), -(1 << 31))
    assert result.tile_index == result.plane_index == 0
    even = replay_world_tile_coordinates(
        (nan, nan),
        width=2,
        height=2,
        upper_bounds_bits=(_bits(2), _bits(2)),
    )
    assert even.tile_index == 0 and even.plane_index == -(1 << 31)


@pytest.mark.parametrize(
    "word,converted",
    [
        (0x7F800000, -(1 << 31)),
        (0xFF800000, -(1 << 31)),
        (0x4F000000, -(1 << 31)),
        (0xCF000000, -(1 << 31)),
        (0x4EFFFFFF, 2147483520),
        (0xCEFFFFFF, -2147483520),
        (_bits(-1.75), -1),
        (1, 0),
        (0x80000001, 0),
    ],
)
def test_old_tile_removal_converts_without_common_clamping(word, converted):
    assert replay_world_tile_plane_coordinates((word, word)) == (converted, converted)


def test_common_unordered_upper_bound_does_not_repair_positive_infinity():
    result = replay_world_tile_coordinates(
        (0x7F800000, 0),
        width=3,
        height=2,
        upper_bounds_bits=(0x7F800001, _bits(2)),
    )
    assert result.xy_bits == (0x7F800000, 0)
    assert result.plane_coordinates == (-(1 << 31), 0)
    assert result.tile_coordinates == (0, 0)
    assert result.fraction_bits[0] == 0x7F800000


@pytest.mark.parametrize("gate", [0, 0x80000000, 0x33D6BF95, 0xFF800000, 0x7FC12345, 0x7F800001])
def test_moving_ordered_gate_preserves_original_requested_bits(gate):
    target = (0x7F800001, _bits(-90))
    assert (
        clamp_replay_moving_tile_xy(
            target,
            map_width=3,
            radius_bits=(_bits(0.3), _bits(0.6)),
            gate_bits=gate,
        )
        == target
    )


def test_moving_upper_comparison_and_assignment_have_distinct_rounding():
    assert clamp_replay_moving_tile_xy(
        (_bits(3), 0x4018F5C2),
        map_width=3,
        radius_bits=(_bits(0.6), _bits(0.6)),
        gate_bits=0x33D6BF96,
    ) == (0x4018F5C3, 0x4018F5C2)


def test_moving_lower_branch_precedes_upper_and_both_axes_use_width():
    # An oversized radius can produce a lower result outside the map. The
    # native else-if does not immediately apply an upper clamp to that result.
    assert clamp_replay_moving_tile_xy(
        (0, _bits(1)),
        map_width=1,
        radius_bits=(_bits(3), _bits(3)),
        gate_bits=_bits(1),
    ) == (0x4040A3D7, 0x4040A3D7)
    moving = clamp_replay_moving_tile_xy(
        (_bits(9), _bits(9)),
        map_width=10,
        radius_bits=(_bits(0.3), _bits(0.3)),
        gate_bits=_bits(1),
    )
    assert moving == (_bits(9), _bits(9))
    common = replay_world_tile_coordinates(
        moving,
        width=10,
        height=3,
        upper_bounds_bits=(_bits(10), _bits(3)),
    )
    assert common.tile_coordinates == (9, 2)


def test_moving_nan_radius_or_coordinate_does_not_take_ordered_clamp_branch():
    target = (_bits(4), 0x7F800001)
    assert (
        clamp_replay_moving_tile_xy(
            target,
            map_width=3,
            radius_bits=(0x7F800001, _bits(0.6)),
            gate_bits=_bits(1),
        )
        == target
    )


def test_geometry_and_existing_registry_support_ordered_initial_append_and_remove():
    registry = ReplayWorldTileRegistry.empty(7, 3, {9: _bits(2)})
    selected = replay_world_tile_coordinates(
        (_bits(2.75), _bits(1.5)),
        width=7,
        height=3,
        upper_bounds_bits=(_bits(7), _bits(3)),
    )
    registry.append(selected.tile_index, 9, plane_coordinates=selected.plane_coordinates)
    assert registry.tokens(9) == (9,) and registry.positive_count(9) == 1
    registry.remove(9, 9, plane_coordinates=replay_world_tile_plane_coordinates(selected.xy_bits))
    assert registry.tokens(9) == () and registry.positive_count(9) == 0


@pytest.mark.parametrize("width,height", [(True, 2), (0, 2), (2, -1), (1 << 31, 1), (1 << 24, 2)])
def test_invalid_geometry_storage_dimensions_fail(width, height):
    with pytest.raises(ValueError):
        replay_world_tile_coordinates(
            (0, 0), width=width, height=height, upper_bounds_bits=(_bits(2), _bits(2))
        )


@pytest.mark.parametrize("pair", [(True, 0), (0, -1), (0, 1 << 32), (0,), [0, 0]])
def test_invalid_words_and_mutable_pairs_fail(pair):
    with pytest.raises(ValueError):
        replay_world_tile_plane_coordinates(pair)
    with pytest.raises(ValueError):
        replay_world_tile_coordinates(
            pair, width=2, height=2, upper_bounds_bits=(_bits(2), _bits(2))
        )
    with pytest.raises(ValueError):
        clamp_replay_moving_tile_xy((0, 0), map_width=2, radius_bits=pair, gate_bits=_bits(1))
