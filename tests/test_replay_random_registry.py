"""Original native registry-loop oracle and engine-only checkpoint contracts."""

from __future__ import annotations

import gzip
import json
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest

from vantage.replay_random import (
    ReplayRandomState,
    draw_replay_random_i15,
    draw_replay_random_u32,
    seed_replay_random,
)
from vantage.replay_random_registry import (
    REPLAY_RANDOM_STREAM_ADDRESSES,
    REPLAY_RANDOM_STREAM_NAMES,
    ReplayRandomCheckpoint,
    ReplayRandomRegistry,
    pop_replay_random_registry,
    push_replay_random_registry,
    seed_replay_random_registry,
)

FIXTURE = Path(__file__).parent / "fixtures/native_replay_random_registry_54800.json.gz"
ORACLE = json.loads(gzip.decompress(FIXTURE.read_bytes()))


def _decode(words: list[int]) -> ReplayRandomRegistry:
    cursor = 1
    states = []
    stacks = []
    for _ in range(words[0]):
        present = words[cursor]
        cursor += 1
        if not present:
            states.append(None)
            stacks.append(())
            continue
        calls, last, index = words[cursor : cursor + 3]
        state_words = tuple(words[cursor + 3 : cursor + 19])
        depth = words[cursor + 19]
        cursor += 20
        stack = []
        for _ in range(depth):
            stack.append(
                ReplayRandomCheckpoint(tuple(words[cursor : cursor + 16]), words[cursor + 16])
            )
            cursor += 17
        states.append(ReplayRandomState(state_words, index, calls, last))
        stacks.append(tuple(stack))
    assert cursor == len(words)
    return ReplayRandomRegistry(tuple(states), tuple(stacks))


@pytest.mark.parametrize("case", ORACLE["cases"], ids=lambda case: str(case["op"]))
def test_original_native_registry_loops(case) -> None:
    before = _decode(case["before"])
    original = _decode(case["before"])
    if case["op"] == 0:
        after = seed_replay_random_registry(before, case["seed"])
    elif case["op"] == 1:
        after = push_replay_random_registry(before)
    elif case["op"] == 2:
        after = pop_replay_random_registry(before)
    else:
        pushed = push_replay_random_registry(before)
        seeded = seed_replay_random_registry(pushed, case["seed"])
        draws = tuple(
            None if state is None else draw_replay_random_i15(state).state
            for state in seeded.streams
        )
        after = pop_replay_random_registry(replace(seeded, streams=draws))
    assert after == _decode(case["after"])
    assert before == original


def test_stream_names_and_addresses_follow_original_crt_table_order() -> None:
    assert tuple(ORACLE["stream_names"]) == REPLAY_RANDOM_STREAM_NAMES
    assert tuple(ORACLE["stream_addresses"]) == REPLAY_RANDOM_STREAM_ADDRESSES
    assert len(set(REPLAY_RANDOM_STREAM_ADDRESSES)) == len(REPLAY_RANDOM_STREAM_NAMES) == 11


def test_seed_chain_uses_full_word_and_skips_null_slot() -> None:
    old = seed_replay_random(7)
    seeded = seed_replay_random_registry(ReplayRandomRegistry((old, None, old)), 21976)
    first = draw_replay_random_u32(seed_replay_random(21976, previous=old))
    assert first.value > 32767
    assert seeded.streams[0] == first.state
    assert seeded.streams[1] is None
    assert (
        seeded.streams[2]
        == draw_replay_random_u32(seed_replay_random(first.value, previous=old)).state
    )
    assert (
        seeded.streams[2]
        != draw_replay_random_u32(seed_replay_random(first.value & 32767, previous=old)).state
    )


def test_pop_restores_engine_but_keeps_draw_count_and_last_masked() -> None:
    state = replace(seed_replay_random(1150), calls=0xFFFFFFFF, last_masked=0xDEADBEEF)
    pushed = push_replay_random_registry(ReplayRandomRegistry((state,)))
    draw = draw_replay_random_i15(state)
    live = replace(pushed, streams=(draw.state,))
    restored = pop_replay_random_registry(live)
    assert restored.streams == (replace(state, calls=0, last_masked=draw.value),)
    assert restored.checkpoints == ((),)
    assert live.checkpoints[0][0] == ReplayRandomCheckpoint(state.words, state.index)


def test_independent_depths_empty_pop_and_nested_checkpoint_order() -> None:
    first, second = seed_replay_random(1), seed_replay_random(2)
    pushed = push_replay_random_registry(ReplayRandomRegistry((first, second)))
    only_first = replace(pushed, checkpoints=(pushed.checkpoints[0], ()))
    assert pop_replay_random_registry(only_first) == ReplayRandomRegistry((first, second))
    changed = replace(pushed, streams=(second, first))
    nested = push_replay_random_registry(changed)
    changed_again = replace(nested, streams=(first, second))
    one = pop_replay_random_registry(changed_again)
    assert one.streams == (second, first)
    assert pop_replay_random_registry(one).streams == (first, second)
    empty = ReplayRandomRegistry((None, first))
    assert pop_replay_random_registry(empty) == empty


def test_empty_registry_has_no_engine_transition() -> None:
    empty = ReplayRandomRegistry(())
    assert seed_replay_random_registry(empty, 0xFFFFFFFF) == empty
    assert push_replay_random_registry(empty) == pop_replay_random_registry(empty) == empty


@pytest.mark.parametrize("seed", [-1, 0x100000000, 1.5, "1", None])
def test_invalid_seed_rejected_even_for_empty_registry(seed) -> None:
    with pytest.raises(ValueError, match="u32"):
        seed_replay_random_registry(ReplayRandomRegistry(()), seed)


@pytest.mark.parametrize(
    "streams,checkpoints",
    [
        ([], ()),
        ((1,), ()),
        ((None,), []),
        ((None,), None),
        ((None,), ((), ())),
        ((None,), ([],)),
        ((None,), ((ReplayRandomCheckpoint((0,) * 16, 0),),)),
        ((seed_replay_random(0),), ((None,),)),
    ],
)
def test_invalid_registry_structure_rejected(streams, checkpoints) -> None:
    with pytest.raises(ValueError):
        ReplayRandomRegistry(streams, checkpoints)


@pytest.mark.parametrize(
    "words,index",
    [
        ((0,) * 15, 0),
        ((0,) * 16, -1),
        ((0,) * 16, 16),
        ((-1,) * 16, 0),
    ],
)
def test_checkpoint_validates_engine_bits(words, index) -> None:
    with pytest.raises(ValueError):
        ReplayRandomCheckpoint(words, index)


def test_registry_is_immutable() -> None:
    registry = ReplayRandomRegistry((seed_replay_random(0),))
    with pytest.raises(FrozenInstanceError):
        registry.streams = ()
