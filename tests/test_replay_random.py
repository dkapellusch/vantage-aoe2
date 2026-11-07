"""Exact original-code random-stream oracle and boundary contracts."""

from __future__ import annotations

import gzip
import json
from pathlib import Path

import pytest

from vantage.replay_random import (
    ReplayRandomState,
    draw_replay_random_i15,
    draw_replay_random_range,
    draw_replay_random_u32,
    draw_replay_random_u64,
    seed_replay_random,
)


@pytest.mark.parametrize("operation", range(4))
def test_original_native_random_oracle(operation: int) -> None:
    fixture = Path(__file__).parent / "fixtures/native_replay_random_54800.json.gz"
    rows = json.loads(gzip.decompress(fixture.read_bytes()))
    count = 0
    for inputs, expected in rows:
        op, param, calls, last, index, *words = inputs
        if op != operation:
            continue
        before = ReplayRandomState(tuple(words), index, calls, last)
        if op == 0:
            after = seed_replay_random(param, previous=before)
            value = 0
        else:
            if op == 1:
                draw = draw_replay_random_i15(before)
            elif op == 2:
                draw = draw_replay_random_u32(before)
            else:
                draw = draw_replay_random_range(before, param)
            value, after = draw.value, draw.state
        assert [value, after.calls, after.last_masked, after.index, *after.words] == expected
        assert before.words == tuple(words)
        count += 1
    assert count == (256, 3840, 3712, 3712)[operation]


def test_zero_limit_counts_without_advancing_or_changing_last() -> None:
    before = ReplayRandomState(tuple(range(16)), 7, 0xFFFFFFFF, 12345)
    result = draw_replay_random_range(before, 0)
    assert result.value == 0
    assert result.state == ReplayRandomState(before.words, 7, 0, 12345)


def test_original_native_u64_random_oracle() -> None:
    path = Path(__file__).parent / "fixtures/native_replay_random_u64_54800.json.gz"
    rows = json.loads(gzip.decompress(path.read_bytes()))["rows"]
    assert len(rows) == 8320
    for inputs, expected in rows:
        calls, last, index, *words = inputs
        before = ReplayRandomState(tuple(words), index, calls, last)
        result = draw_replay_random_u64(before)
        after = result.state
        assert [result.value, after.calls, after.last_masked, after.index, *after.words] == expected
        assert before == ReplayRandomState(tuple(words), index, calls, last)


def test_u64_zero_engine_counts_once_and_preserves_last_masked() -> None:
    before = ReplayRandomState((0,) * 16, 0, 0xFFFFFFFF, 0x12345678)
    result = draw_replay_random_u64(before)
    assert result.value == 0
    assert result.state == ReplayRandomState((0,) * 16, 14, 0, 0x12345678)


def test_reseed_and_full_draw_preserve_diagnostic_last_value() -> None:
    before = ReplayRandomState(tuple(range(16)), 4, 17, 0xAABBCCDD)
    after = seed_replay_random(1150, previous=before)
    assert (after.index, after.calls, after.last_masked) == (0, 17, 0xAABBCCDD)
    assert draw_replay_random_u32(after).state.last_masked == before.last_masked
    assert draw_replay_random_i15(after).state.last_masked <= 32767


@pytest.mark.parametrize("value", [-1, 0x100000000, 1.5, "0"])
def test_reject_non_wire_seed_and_range(value: int) -> None:
    with pytest.raises(ValueError):
        seed_replay_random(value)
    with pytest.raises(ValueError):
        draw_replay_random_range(seed_replay_random(0), value)


@pytest.mark.parametrize(
    "words,index,calls,last",
    [
        ((), 0, 0, 0),
        ((0,) * 15, 0, 0, 0),
        ((0,) * 17, 0, 0, 0),
        ((0,) * 15 + (-1,), 0, 0, 0),
        ((0,) * 16, 16, 0, 0),
        ((0,) * 16, -1, 0, 0),
        ((0,) * 16, 0, -1, 0),
        ((0,) * 16, 0, 0, 0x100000000),
    ],
)
def test_reject_invalid_stream_state(
    words: tuple[int, ...], index: int, calls: int, last: int
) -> None:
    with pytest.raises(ValueError):
        ReplayRandomState(words, index, calls, last)
