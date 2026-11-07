"""Terrain numerical branches and integration inputs; no full setter claim."""

from __future__ import annotations

import pytest

from vantage.replay_elevation import update_replay_elevation
from vantage.replay_movement_geometry import _bits
from vantage.replay_world_tile_geometry import replay_world_tile_coordinates
from vantage.replay_world_tile_height import replay_world_tile_height


@pytest.mark.parametrize(
    "shape,slope,flag",
    [
        (0, 0, 0),
        (1, 0.5, 0),
        (2, 0.25, 1),
        (3, 0.5, 0),
        (4, 0.25, 0),
        (5, 0.75, 0),
        (6, 0.5, 1),
        (7, 0.5, 0),
        (8, 0.25, 1),
        (9, 0.25, 0),
        (10, 0, 1),
        (11, 0.25, 0),
        (12, 0, 0),
        (13, 0.75, 0),
        (14, 0.5, 1),
        (15, 0.5, 1),
        (16, 0.75, 1),
    ],
)
def test_all_slope_shapes_on_a_tile_interior(shape, slope, flag):
    result = replay_world_tile_height(
        (_bits(0.25), _bits(0.5)),
        slope_shape=shape,
        base_elevation=3,
    )
    assert result.slope_bits == _bits(slope)
    assert result.height_bits == _bits(3 + slope)
    assert result.projection_flag_bits == _bits(flag)


@pytest.mark.parametrize(
    "shape,slope",
    [
        (1, 0.25),
        (2, 0.5),
        (3, 0.25),
        (9, 0),
        (10, 0.25),
        (11, 0),
        (12, 0.25),
        (13, 0.5),
        (14, 0.75),
        (16, 0.5),
    ],
)
def test_other_triangle_and_positive_delta(shape, slope):
    result = replay_world_tile_height(
        (_bits(0.75), _bits(0.5)),
        slope_shape=shape,
        base_elevation=255,
    )
    assert result.slope_bits == _bits(slope)
    assert result.height_bits == _bits(255 + slope)


@pytest.mark.parametrize("shape", [0, 17, 18, 127, 255])
def test_flat_and_unsigned_out_of_table_shapes_ignore_fraction_nans(shape):
    result = replay_world_tile_height(
        (0x7F800001, 0xFF800002),
        slope_shape=shape,
        base_elevation=255,
    )
    assert result.slope_bits == result.projection_flag_bits == 0
    assert result.height_bits == _bits(255)


@pytest.mark.parametrize("shape", [1, 13])
def test_rounded_sum_selects_triangle_before_using_original_fraction(shape):
    # .5 + the float immediately below .5 rounds to1.0. A host-f64 sum
    # would take the wrong branch. Shape13 returns the held y word verbatim.
    result = replay_world_tile_height(
        (_bits(0.5), 0x3EFFFFFF),
        slope_shape=shape,
        base_elevation=0,
    )
    assert result.slope_bits == (_bits(0.5) if shape == 1 else 0x3EFFFFFF)


@pytest.mark.parametrize("x,y", [(0, 0x80000000), (0x80000000, 0)])
def test_minmax_ties_keep_the_second_source_signed_zero(x, y):
    minimum = replay_world_tile_height((x, y), slope_shape=4, base_elevation=0)
    maximum = replay_world_tile_height((x, y), slope_shape=15, base_elevation=0)
    assert minimum.slope_bits == x and maximum.slope_bits == y
    assert minimum.height_bits == maximum.height_bits == 0


@pytest.mark.parametrize("shape", [9, 10, 11, 12])
def test_unordered_comparisons_select_zero_slope(shape):
    result = replay_world_tile_height(
        (0x7F800001, _bits(0.25)),
        slope_shape=shape,
        base_elevation=7,
    )
    assert result.slope_bits == 0 and result.height_bits == _bits(7)


@pytest.mark.parametrize(
    "shape,expected", [(1, 0.75), (3, None), (4, 0.25), (13, None), (15, None), (16, 0.75)]
)
def test_unordered_branches_are_not_generic_minmax_or_floor(shape, expected):
    result = replay_world_tile_height(
        (_bits(0.25), 0xFF800123),
        slope_shape=shape,
        base_elevation=2,
    )
    if expected is None:
        expected_word = 0xFFC00123 if shape == 3 else 0xFF800123
        assert result.slope_bits == expected_word
        assert result.height_bits == 0xFFC00123
    else:
        assert result.slope_bits == _bits(expected)
        assert result.height_bits == _bits(2 + expected)


@pytest.mark.parametrize("shape", [4, 8, 14])
def test_selected_original_signaling_word_is_only_quieted_by_base_addition(shape):
    result = replay_world_tile_height(
        (0x7F800321, 0xFFC00123),
        slope_shape=shape,
        base_elevation=200,
    )
    assert result.slope_bits == 0x7F800321
    assert result.height_bits == 0x7FC00321


@pytest.mark.parametrize("shape", [9, 10])
def test_delta_negative_zero_outputs_positive_zero(shape):
    result = replay_world_tile_height((0x80000000, 0), slope_shape=shape, base_elevation=0)
    assert result.slope_bits == result.height_bits == 0


def test_height_addition_rounds_at_unsigned_base_elevation():
    result = replay_world_tile_height((0x33800000, 0), slope_shape=8, base_elevation=255)
    assert result.slope_bits == 0x33800000 and result.height_bits == _bits(255)


def test_geometry_height_and_existing_elevation_policy_keep_phase_inputs_separate():
    geometry = replay_world_tile_coordinates(
        (_bits(2.25), _bits(1.5)),
        width=7,
        height=3,
        upper_bounds_bits=(_bits(7), _bits(3)),
    )
    # The selected slope and current tile's unsigned base are explicit inputs.
    # Their distinct backing and intervening callbacks belong to the caller.
    height = replay_world_tile_height(
        geometry.fraction_bits,
        slope_shape=2,
        base_elevation=201,
    )
    assert height.height_bits == _bits(201.25)
    raised = update_replay_elevation(_bits(200), height.height_bits, 1, has_tile=True)
    preserved = update_replay_elevation(_bits(202), height.height_bits, 1, has_tile=True)
    assert raised.height_bits == height.height_bits and raised.grounded
    assert preserved.height_bits == _bits(202) and not preserved.grounded


@pytest.mark.parametrize(
    "shape,base", [(True, 0), (-1, 0), (256, 0), (1.0, 0), (0, False), (0, -1), (0, 256)]
)
def test_invalid_byte_inputs_fail(shape, base):
    with pytest.raises(ValueError):
        replay_world_tile_height((0, 0), slope_shape=shape, base_elevation=base)


@pytest.mark.parametrize("fractions", [[0, 0], (0,), (0, True), (-1, 0), (0, 1 << 32), (0, 0.5)])
def test_invalid_fraction_words_fail(fractions):
    with pytest.raises(ValueError):
        replay_world_tile_height(fractions, slope_shape=0, base_elevation=0)
