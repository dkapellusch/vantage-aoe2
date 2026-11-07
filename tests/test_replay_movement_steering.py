"""Native one-step steering and the first recorded PIG movement's actual ticks."""

from __future__ import annotations

import gzip
import json
from pathlib import Path
from typing import Any

import pytest

from vantage.replay_clock import advance_replay_clock
from vantage.replay_movement_controller import advance_unformed_replay_velocity
from vantage.replay_movement_geometry import (
    Float32Vector,
    _op,
    replay_movement_direction,
)
from vantage.replay_movement_steering import advance_replay_steering

FIXTURE = Path(__file__).parent / "fixtures/native_replay_steering_54800.json.gz"


@pytest.fixture(scope="module")
def original() -> Any:
    return json.loads(gzip.decompress(FIXTURE.read_bytes()))


def _vector(values: list[int]) -> Float32Vector:
    return values[0], values[1], values[2]


@pytest.mark.parametrize(("name", "count"), [("sweep", 6144), ("turn_sweep", 12288)])
def test_independent_original_steering_cases(original: Any, name: str, count: int) -> None:
    cases = original[name]["cases"]
    assert len(cases) == count
    for row, expected in cases:
        goal, position = _vector(row[:3]), _vector(row[3:6])
        direction, perpendicular = _vector(row[6:9]), _vector(row[9:12])
        desired = replay_movement_direction(position, goal, direction)
        assert list(desired) == expected[19:]
        result = advance_replay_steering(
            position,
            goal,
            desired,
            direction,
            perpendicular,
            row[16],
            row[17],
            row[19],
            row[12],
            row[15],
            row[13],
            row[14],
        )
        assert [
            row[18],
            *position,
            *result.direction,
            *result.perpendicular,
            result.velocity,
            result.acceleration,
            result.yaw,
            result.limited,
        ] == expected[:14], row


def test_connected_recorded_ticks_and_ten_native_position_samples(original: Any) -> None:
    native = original["connected"]
    initial = native["initial_words"]
    position, direction, perpendicular = (
        _vector(initial[:3]),
        _vector(initial[3:6]),
        _vector(initial[6:9]),
    )
    goal = _vector(native["goal_words"])
    cap = native["speed_cap_bits"]
    velocity, acceleration = 0, 0
    positions = {}
    deltas = original["connected_sync_deltas"]
    clock = native["inputs"][0][0] - deltas[0]
    for (time, dt, translate), delta, expected in zip(
        native["inputs"], deltas, native["outputs"], strict=True
    ):
        tick = advance_replay_clock(clock, delta)
        assert (tick.time_ms, tick.seconds_bits) == (time, dt)
        clock = time
        if translate:
            velocity = advance_unformed_replay_velocity(velocity, acceleration, dt, cap)
            distance = _op(dt, velocity, "*")
            position = tuple(
                _op(_op(distance, direction[i], "*"), position[i], "+") for i in range(3)
            )
        desired = replay_movement_direction(position, goal, direction)
        result = advance_replay_steering(
            position,
            goal,
            desired,
            direction,
            perpendicular,
            velocity,
            acceleration,
            dt,
            cap,
            0x7F7FFFFF,
            0,
            0x7F7FFFFF,
        )
        assert [
            time,
            *position,
            *result.direction,
            *result.perpendicular,
            result.velocity,
            result.acceleration,
            result.yaw,
            result.limited,
        ] == expected[:14]
        direction, perpendicular = result.direction, result.perpendicular
        velocity, acceleration = result.velocity, result.acceleration
        positions[time] = [position[0], position[2]]
    assert len(native["inputs"]) == 79 and len(native["observed"]) == 10
    for sample in native["observed"]:
        assert positions[sample["time_ms"]] == sample["actual_xy"]


def test_original_yaw_is_not_direct_waypoint_normalization(original: Any) -> None:
    native = original["connected"]
    initial = native["initial_words"]
    desired = replay_movement_direction(
        _vector(initial[:3]), _vector(native["goal_words"]), _vector(initial[3:6])
    )
    assert native["outputs"][0][4:7] == [1063126395, 0, 3204375649]
    assert list(desired) != native["outputs"][0][4:7]
    assert native["direct_direction_comparison"]["differing"] == 79


def test_zero_elapsed_native_limited_turn_stops_velocity(original: Any) -> None:
    _row, expected = next(
        (row, out)
        for row, out in original["sweep"]["cases"]
        if row[19] == 0 and row[16] != 0 and out[13] == 1
    )
    assert expected[10:12] == [0, 0xFF7FFFFF]


def test_cap_branch_preserves_existing_acceleration(original: Any) -> None:
    row, expected = next(
        (row, out)
        for row, out in original["sweep"]["cases"]
        if out[13] == 0 and out[18] == 0 and row[17] != 0
    )
    assert expected[10:12] == [row[16], row[17]]


def _valid() -> list[Any]:
    return [
        (0, 0, 0),
        (0x3F800000, 0, 0),
        (0x3F800000, 0, 0),
        (0x3F800000, 0, 0),
        (0, 0, 0xBF800000),
        0,
        0,
        0x3C54FDF4,
        0x3F333333,
        0x7F7FFFFF,
        0,
        0x7F7FFFFF,
    ]


@pytest.mark.parametrize("index", range(5, 12))
@pytest.mark.parametrize("invalid", [0x7F800000, 0x7FC00001])
def test_unproved_nonfinite_scalar_domain_is_rejected(index: int, invalid: int) -> None:
    arguments = _valid()
    arguments[index] = invalid
    with pytest.raises(ValueError, match="finite"):
        advance_replay_steering(*arguments)


@pytest.mark.parametrize("index", range(5))
def test_nonfinite_vectors_are_rejected(index: int) -> None:
    arguments = _valid()
    arguments[index] = (0x7F800000, 0, 0)
    with pytest.raises(ValueError, match="finite"):
        advance_replay_steering(*arguments)


@pytest.mark.parametrize("denominator", [0, 0x80000000, 0xBF800000])
def test_nonpositive_turn_denominator_is_explicitly_unsupported(denominator: int) -> None:
    arguments = _valid()
    arguments[-1] = denominator
    with pytest.raises(ValueError, match="positive turn denominator"):
        advance_replay_steering(*arguments)


def test_half_pi_yaw_uses_proved_normal_turn_domain() -> None:
    arguments = _valid()
    arguments[1] = (0, 0, 0xBF800000)
    arguments[2] = (0, 0, 0xBF800000)
    result = advance_replay_steering(*arguments)
    assert result.yaw == 0x3FC90FDB and result.limited == 0


def test_nonstandard_negative_turn_cap_outside_proved_domain_is_rejected() -> None:
    arguments = _valid()
    arguments[7] = 0x3F800000
    arguments[9] = 0xC0800000
    with pytest.raises(ValueError, match="turn-angle"):
        advance_replay_steering(*arguments)
