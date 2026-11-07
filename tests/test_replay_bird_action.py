"""Original activation callback arguments and all32768 waiting timer inputs."""

from __future__ import annotations

import gzip
import json
from pathlib import Path

import pytest

from vantage.replay_bird_action import enter_replay_bird_wait, replay_bird_activation
from vantage.replay_random import ReplayRandomState


def test_native_bird_activation_callbacks() -> None:
    fixture = Path(__file__).parent / "fixtures/native_replay_bird_activation_54800.json.gz"
    rows = json.loads(gzip.decompress(fixture.read_bytes()))
    assert len(rows) == 6912
    for mode, enabled, flag, owner, x, y, trace, position in rows:
        callbacks = replay_bird_activation(
            x, y, enabled=enabled, elevation_mode=mode, task_flag=flag, owner_index=owner
        )
        assert [
            (f"S{event.arguments[0]}" if event.kind == "state" else "P") for event in callbacks
        ] == trace
        actual_positions = [event.arguments for event in callbacks if event.kind == "position"]
        assert actual_positions == ([tuple(position)] if "P" in trace else [])


def test_native_bird_wait_all_masked_draws() -> None:
    fixture = Path(__file__).parent / "fixtures/native_replay_bird_wait_54800.json.gz"
    rows = json.loads(gzip.decompress(fixture.read_bytes()))
    assert len(rows) == 32768
    timers = set()
    for inputs, expected in rows:
        calls, last, index, *words = inputs
        before = ReplayRandomState(tuple(words), index, calls, last)
        wait = enter_replay_bird_wait(before)
        after = wait.random_state
        assert [
            3,
            wait.timer_bits,
            after.calls,
            after.last_masked,
            after.index,
            *after.words,
        ] == expected
        timers.add(wait.timer_bits)
    assert len(timers) == 11


@pytest.mark.parametrize(
    "keyword,value",
    [
        ("x_bits", -1),
        ("y_bits", 0x100000000),
        ("owner_index", -1),
        ("enabled", 256),
        ("elevation_mode", -1),
        ("task_flag", 256),
    ],
)
def test_activation_rejects_invalid_words(keyword: str, value: int) -> None:
    arguments = dict(x_bits=0, y_bits=0, enabled=1, elevation_mode=1, task_flag=0, owner_index=0)
    arguments[keyword] = value
    with pytest.raises(ValueError):
        replay_bird_activation(**arguments)
