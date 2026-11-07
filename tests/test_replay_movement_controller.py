"""Original velocity and translation checkpoints; world commits stay outside."""

from __future__ import annotations

import gzip
import json
from pathlib import Path

import pytest

from vantage.replay_movement_controller import (
    advance_unformed_replay_velocity,
    replay_translation_setter_inputs,
)


def test_original_null_formation_velocity_cases() -> None:
    fixture = Path(__file__).parent / "fixtures/native_replay_controller_velocity_54800.json.gz"
    rows = json.loads(gzip.decompress(fixture.read_bytes()))
    assert len(rows) == 73728
    for velocity, acceleration, elapsed, cap, expected in rows:
        assert advance_unformed_replay_velocity(velocity, acceleration, elapsed, cap) == expected


def test_upper_cap_return_precedes_negative_clamp() -> None:
    assert advance_unformed_replay_velocity(0x3F800000, 0, 0, 0xBF800000) == 0xBF800000
    assert advance_unformed_replay_velocity(0xBF800000, 0, 0, 0x3F800000) == 0


def test_sse_acceleration_product_nan_has_priority_over_velocity_nan() -> None:
    assert advance_unformed_replay_velocity(0x7FC12345, 0xFFC54321, 0, 0) == 0xFFC54321


@pytest.mark.parametrize("index", range(4))
@pytest.mark.parametrize("value", [-1, 0x100000000, 1.5, "0"])
def test_controller_rejects_invalid_binary32_words(index: int, value: int) -> None:
    inputs = [0, 0, 0, 0]
    inputs[index] = value
    with pytest.raises(ValueError):
        advance_unformed_replay_velocity(*inputs)


def test_original_translation_setter_checkpoints() -> None:
    fixture = Path(__file__).parent / "fixtures/native_replay_translation_54800.json.gz"
    payload = json.loads(gzip.decompress(fixture.read_bytes()))
    assert payload["provenance"]["actual_setter_executed"] is False
    assert payload["provenance"]["c_virtual_callbacks"] is False
    assert payload["provenance"]["original_instructions_patched"] is False
    rows = payload["rows"]
    assert len(rows) == 5307
    reached = 0
    for row in rows:
        displacement, multiplier, x, height, y, dx, dh, dy = row["input"]
        actual = replay_translation_setter_inputs(
            (x, height, y), (dx, dh, dy), displacement, multiplier
        )
        expected = tuple(row["endpoint"]) if row["setter_checkpoint"] else None
        assert actual == expected, row
        reached += int(row["setter_checkpoint"])
    assert reached == 3223


def test_captured_logical_context_returns_inputs_without_mutating_position() -> None:
    position = (1125946936, 0, 1124102973)
    stored_direction = (1063126395, 0, 3204375649)
    result = replay_translation_setter_inputs(position, stored_direction, 1008015403, 0x3F800000)
    assert result == (1125947453, 0, 1124102676)
    assert position == (1125946936, 0, 1124102973)
    assert stored_direction == (1063126395, 0, 3204375649)


def test_translation_threshold_includes_exact_epsilon_and_signed_distance() -> None:
    origin, forward = (0, 0, 0), (0x3F800000, 0, 0)
    assert replay_translation_setter_inputs(origin, forward, 0x33D6BF94, 0x3F800000) is None
    assert replay_translation_setter_inputs(origin, forward, 0xB3D6BF94, 0x3F800000) is None
    assert replay_translation_setter_inputs(origin, forward, 0x33D6BF95, 0x3F800000) == (
        0x33D6BF95,
        0,
        0,
    )
    assert replay_translation_setter_inputs(origin, forward, 0xB3D6BF95, 0x3F800000) == (
        0xB3D6BF95,
        0,
        0,
    )


def test_translation_nan_reaches_setter_and_scaled_product_wins_nan_priority() -> None:
    # Original COMISS/JBE reaches the setter on unordered, and ADDSS starts
    # with the scaled direction, giving that NaN priority over position.
    position = (0x7FC00111, 0, 0)
    direction = (0x7FC00222, 0, 0x3F800000)
    assert replay_translation_setter_inputs(position, direction, 0x3F800000, 0x3F800000) == (
        0x7FC00222,
        0,
        0x3F800000,
    )
    assert replay_translation_setter_inputs(position, direction, 0x7F812345, 0x7FC34567) == (
        0x7FC12345,
        0x7FC12345,
        0x7FC12345,
    )


@pytest.mark.parametrize("value", [0, 0x80000000])
def test_zero_translation_does_not_call_setter_even_with_nan_position(value: int) -> None:
    assert (
        replay_translation_setter_inputs((0x7F812345, 0, 0), (0x7FC00222, 0, 0), value, 0x3F800000)
        is None
    )


@pytest.mark.parametrize("index", range(4))
@pytest.mark.parametrize("value", [-1, 0x100000000, 1.5, "0"])
def test_translation_rejects_invalid_scalar_words(index: int, value: int) -> None:
    if index == 0:
        position = (value, 0, 0)
        direction = (0, 0, 0)
        displacement, multiplier = 0, 0
    elif index == 1:
        position = (0, 0, 0)
        direction = (0, value, 0)
        displacement, multiplier = 0, 0
    else:
        position = direction = (0, 0, 0)
        displacement = value if index == 2 else 0
        multiplier = value if index == 3 else 0
    with pytest.raises(ValueError):
        replay_translation_setter_inputs(position, direction, displacement, multiplier)


@pytest.mark.parametrize("vector", [(), (0, 0), (0, 0, 0, 0), [0, 0, 0]])
def test_translation_rejects_invalid_vectors(vector: tuple[int, ...]) -> None:
    with pytest.raises(ValueError):
        replay_translation_setter_inputs(vector, (0, 0, 0), 0, 0)
    with pytest.raises(ValueError):
        replay_translation_setter_inputs((0, 0, 0), vector, 0, 0)
