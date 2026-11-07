"""Native conversion oracle and original paired replay/capture clock regressions."""

from __future__ import annotations

import gzip
import json
import struct
from functools import lru_cache
from pathlib import Path
from typing import Any

import pytest

from vantage.replay_clock import advance_replay_clock

FIXTURE = Path(__file__).parent / "fixtures/native_replay_clock_54800.json.gz"


@lru_cache(maxsize=1)
def _fixture() -> dict[str, Any]:
    return dict(json.loads(gzip.decompress(FIXTURE.read_bytes())))


def test_native_original_instruction_conversion_oracle() -> None:
    oracle = _fixture()["native"]
    assert oracle["address"] == "0x1416296dd"
    assert oracle["constant_hex"] == "00007a44"  # Native divisor1000.0f.
    assert len(oracle["cases"]) == 726
    for case in oracle["cases"]:
        step = advance_replay_clock(0, case["delta_ms"])
        assert step.seconds_bits == case["seconds_bits"], case
        assert struct.unpack("<I", struct.pack("<f", step.seconds))[0] == case["seconds_bits"]


@pytest.mark.parametrize(
    ("previous", "delta", "current"),
    (
        (0, 0, 0),
        (0, 13, 13),
        (695410, 15, 695425),
        (0xFFFFFFFF, 1, 0),
        (0xFFFFFFFE, 5, 3),
        (0xFFFFFFFF, 0xFFFFFFFF, 0xFFFFFFFE),
        (1, 0xFFFFFFFF, 0),
    ),
)
def test_native_game_millisecond_clock_wraps_u32(
    previous: int,
    delta: int,
    current: int,
) -> None:
    step = advance_replay_clock(previous, delta)
    assert (step.previous_ms, step.time_ms, step.delta_ms) == (previous, current, delta)


@pytest.mark.parametrize("index", (0, 1))
def test_original_replay_sync_prefix_matches_native_capture_boundaries(index: int) -> None:
    sample = _fixture()["paired"][index]
    syncs = sample["first_syncs"]
    clock = syncs[0]["time_ms"] - syncs[0]["delta_ms"]
    times = set()
    for sync in syncs:
        step = advance_replay_clock(clock, sync["delta_ms"])
        assert step.time_ms == sync["time_ms"]
        clock = step.time_ms
        times.add(clock)
    captures = [time for time in sample["first_capture_times"] if time <= clock]
    assert len(captures) >= 7
    assert all(time in times for time in captures)
    assert len(syncs) > len(captures) * 5
    # The original simulation steps are variable. The sampled capture interval
    # cannot replace sync deltas even when all capture clocks are correct.
    assert len({sync["delta_ms"] for sync in syncs}) > 4
    assert any(0 < sync["delta_ms"] < 20 for sync in syncs)


def test_nonzero_clock_origin_uses_same_recorded_deltas() -> None:
    clock = 1234567
    elapsed = 0
    for sync in _fixture()["paired"][0]["first_syncs"]:
        elapsed += sync["delta_ms"]
        step = advance_replay_clock(clock, sync["delta_ms"])
        clock = step.time_ms
        assert clock == 1234567 + elapsed


@pytest.mark.parametrize("delta", (-1, 0x100000000, 1.5, "13", None))
def test_invalid_delta_has_no_implicit_rounding_or_unsigned_coercion(delta: Any) -> None:
    with pytest.raises(ValueError, match=r"delta.*u32"):
        advance_replay_clock(0, delta)


@pytest.mark.parametrize("clock", (-1, 0x100000000, 1.5, "0", None))
def test_invalid_clock_has_no_implicit_rounding_or_unsigned_coercion(clock: Any) -> None:
    with pytest.raises(ValueError, match=r"clock.*u32"):
        advance_replay_clock(clock, 13)


def test_zero_delta_keeps_exact_zero_seconds_and_origin() -> None:
    step = advance_replay_clock(123, 0)
    assert (step.time_ms, step.delta_ms, step.seconds, step.seconds_bits) == (123, 0, 0.0, 0)
