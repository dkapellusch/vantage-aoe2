"""Portable original-instruction oracles, including raw NaN/threshold behavior."""

from __future__ import annotations

import gzip
import json
from pathlib import Path

import pytest

from vantage.replay_movement_geometry import (
    predict_replay_movement,
    replay_movement_arrival,
    replay_movement_direction,
)

FIXTURE = Path(__file__).parent / "fixtures/native_movement_geometry_54800.json.gz"
ORACLE = json.loads(gzip.decompress(FIXTURE.read_bytes()))
ZERO = (0, 0, 0)
X = (0x3F800000, 0, 0)


@pytest.mark.parametrize("operation", range(3), ids=["direction", "candidate", "arrival"])
def test_matches_unchanged_original_geometry_instructions(operation: int) -> None:
    count = 0
    for op, words, expected in ORACLE["cases"]:
        if op != operation:
            continue
        a, b, c = tuple(words[:3]), tuple(words[3:6]), tuple(words[6:9])
        if op == 0:
            actual = list(replay_movement_direction(a, b, c))
        elif op == 1:
            actual = list(
                predict_replay_movement(a, b, *words[6:10], has_controller=bool(words[10]))
            )
        else:
            actual = [replay_movement_arrival(a, b, c), 0, 0]
        assert actual == expected, (op, [hex(v) for v in words], expected, actual)
        count += 1
    assert count == (2162, 11112, 1716)[operation]


def test_equal_horizontal_position_copies_fallback_bits_without_quieting() -> None:
    fallback = (0x7F800001, 0x80000000, 0xFFC12345)
    assert replay_movement_direction(ZERO, (0x80000000, 0x7F800001, 0), fallback) == fallback


def test_direction_threshold_uses_original_binary32_constant() -> None:
    fallback = (0, 0, 0x3F800000)
    assert replay_movement_direction(ZERO, (0x33D6BF94, 0, 0), fallback) == fallback
    assert replay_movement_direction(ZERO, (0x33D6BF95, 0, 0), fallback) == X


def test_unordered_direction_normalizes_instead_of_copying_fallback() -> None:
    assert replay_movement_direction(ZERO, (0x7F800001, 0, 0), X) == (
        0x7FC00001,
        0,
        0x7FC00001,
    )


@pytest.mark.parametrize("velocity", [0, 0xBF800000, 0x40400000])
def test_nonpositive_or_excessive_predicted_speed_uses_cap(velocity: int) -> None:
    assert predict_replay_movement(ZERO, X, velocity, 0, 0x3F000000, 0x40000000) == X


def test_prediction_preserves_native_nan_operand_priority() -> None:
    result = predict_replay_movement(
        (0x7FC00002, 0, 0),
        (0x7FC00003, 0, 0),
        0x7FC00004,
        0x7FC00005,
        0x7FC00006,
        0x7FC00007,
    )
    # Native MULSS starts with elapsed, and ADDSS starts with the product.
    assert result == (0x7FC00006, 0x7FC00006, 0x7FC00006)


def test_absent_controller_copies_signaling_nan_and_negative_zero() -> None:
    position = (0x7F800001, 0x80000000, 0xFFC12345)
    assert predict_replay_movement(position, X, 0, 0, 0, 0, has_controller=False) == position


@pytest.mark.parametrize(
    ("candidate", "status"),
    [(ZERO, 0), ((0x3F800000, 0, 0), 1), ((0x3FC00000, 0, 0), 1), ((0x40400000, 0, 0), 2)],
)
def test_arrival_preserves_all_three_native_statuses(candidate, status: int) -> None:
    assert replay_movement_arrival(X, ZERO, candidate) == status


def test_arrival_flattens_goal_distance_but_keeps_vertical_step() -> None:
    goal = (0x3F800000, 0x7F800001, 0)
    assert replay_movement_arrival(goal, ZERO, (0x3F000000, 0, 0)) == 0
    assert replay_movement_arrival(goal, ZERO, (0x3F000000, 0x40000000, 0)) == 1


def test_unordered_step_comparison_uses_native_jbe_branch() -> None:
    assert replay_movement_arrival(X, ZERO, (0x7FC00001, 0, 0)) == 0


@pytest.mark.parametrize("bad", [-1, 0x100000000, 1.5, "0"])
def test_invalid_scalar_words_rejected(bad) -> None:
    with pytest.raises(ValueError, match="binary32 u32"):
        predict_replay_movement(ZERO, X, bad, 0, 0, 0)


@pytest.mark.parametrize("bad", [(), (0, 0), (0, 0, 0, 0), [0, 0, 0], (0, -1, 0)])
def test_invalid_vector_rejected(bad) -> None:
    with pytest.raises(ValueError, match="binary32 u32"):
        replay_movement_direction(bad, ZERO, X)


def test_controller_flag_requires_boolean() -> None:
    with pytest.raises(ValueError, match="has_controller"):
        predict_replay_movement(ZERO, X, 0, 0, 0, 0, has_controller=1)


def test_oracle_scope_and_original_code_identities_are_pinned() -> None:
    assert ORACLE["target_sha256"] == (
        "69832b9d51145a4bb280da876880198ee0347947098e77098016b9bcbb8d8788"
    )
    assert [row["size"] for row in ORACLE["functions"]] == [
        238,
        239,
        351,
        41,
        49,
        49,
        304,
        9,
        252,
        30,
    ]
    assert ORACLE["functions"][0]["sha256"] == (
        "8a72d724d110a8a42f596664d62e5f1644502cb1a10c220375eabb97f40bd305"
    )
    assert "0x1f80" in ORACLE["mxcsr"]
