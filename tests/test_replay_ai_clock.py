"""Portable original-instruction oracles for the per-owner UnitAI clock."""

from __future__ import annotations

import gzip
import json
from functools import lru_cache
from pathlib import Path
from typing import Any

import pytest

from vantage.replay_ai_clock import ReplayAIClock, advance_replay_ai_clock
from vantage.replay_binary import SaveReader
from vantage.replay_clock import advance_replay_clock
from vantage.replay_world_prefix import read_world_prefix

FIXTURE = Path(__file__).parent / "fixtures/native_replay_ai_clock_54800.json.gz"


@lru_cache(maxsize=1)
def _fixture() -> dict[str, Any]:
    return dict(json.loads(gzip.decompress(FIXTURE.read_bytes())))


def _assert_native_case(case: dict[str, Any], clock: ReplayAIClock) -> ReplayAIClock:
    before = (clock.selected_owner, clock.elapsed_words)
    step = advance_replay_ai_clock(clock, case["delta_ms"])
    assert step.previous is clock
    assert step.delta_ms == case["delta_ms"]
    assert len(step.phases) == len(case["phases"])
    for phase, native in zip(step.phases, case["phases"], strict=True):
        assert phase.player_index == native["player_index"]
        assert phase.clock.selected_owner == clock.selected_owner
        assert phase.clock.elapsed_words == tuple(native["elapsed_words"])
        for owner in range(len(clock.elapsed_words)):
            assert phase.clock.elapsed_i32(owner) == native["elapsed_i32"][owner]
            assert phase.clock.is_selected_owner(owner) == native["selected_predicate"][owner]
        assert phase.clock.is_selected_owner(len(clock.elapsed_words)) is False
        assert phase.clock.is_selected_owner(0xFFFFFFFF) is False
    assert (step.after.selected_owner, step.after.elapsed_words) == (
        case["after"]["selected_owner"],
        tuple(case["after"]["elapsed_words"]),
    )
    assert (clock.selected_owner, clock.elapsed_words) == before
    return step.after


def test_original_instruction_oracle_covers_order_wrap_and_all_owner_positions() -> None:
    fixture = _fixture()
    assert fixture["pe_sha256"] == (
        "69832b9d51145a4bb280da876880198ee0347947098e77098016b9bcbb8d8788"
    )
    native = fixture["native"]
    assert native["add"]["address"] == "0x141629cde"
    assert native["add"]["bytes"] == "448be78b467c420184a68c010000"
    assert native["clear_rotate"]["size"] == 54
    assert native["elapsed_getter"]["bytes"] == "4863c28b84818c010000c3"
    assert native["selected_predicate"]["bytes"] == "33c03991880100000f94c0c3"
    assert len(fixture["cases"]) == 186
    assert {len(case["elapsed_words"]) for case in fixture["cases"]} == {1, 2, 4, 7, 17}
    for case in fixture["cases"]:
        clock = ReplayAIClock(case["selected_owner"], tuple(case["elapsed_words"]))
        _assert_native_case(case, clock)


@pytest.mark.parametrize("index", (0, 1))
def test_original_saved_banks_and_sync_inputs_match_isolated_native_kernel(index: int) -> None:
    """The inputs are paired recordings; owner banks were not runtime-captured."""
    sample = _fixture()["paired"][index]
    reader = SaveReader(bytes.fromhex(sample["raw_prefix_hex"]))
    prefix = read_world_prefix(reader)
    assert reader.remaining == 0
    assert prefix.num_players == sample["num_players"] == (4, 7)[index]
    clock = ReplayAIClock(prefix.fields[0x188], prefix.player_words)
    assert clock.selected_owner == 0
    assert not any(clock.elapsed_words)
    time_ms = prefix.clock_fields[0x18]
    assert len(sample["sequence"]) == 64
    for case in sample["sequence"]:
        assert case["selected_owner"] == clock.selected_owner
        assert case["elapsed_words"] == list(clock.elapsed_words)
        clock = _assert_native_case(case, clock)
        game_clock = advance_replay_clock(time_ms, case["sync"]["delta_ms"])
        assert game_clock.time_ms == case["sync"]["time_ms"]
        time_ms = game_clock.time_ms
    assert clock.selected_owner == 64 % sample["num_players"]


def test_later_owner_does_not_receive_delta_before_its_player_phase() -> None:
    clock = ReplayAIClock(2, (10, 20, 30, 40))
    step = advance_replay_ai_clock(clock, 13)
    assert [phase.player_index for phase in step.phases] == [0, 1, 2, 3]
    assert [phase.clock.elapsed_words for phase in step.phases] == [
        (23, 20, 30, 40),
        (23, 33, 30, 40),
        (23, 33, 43, 40),
        (23, 33, 43, 53),
    ]
    assert [phase.clock.elapsed_i32(2) for phase in step.phases] == [30, 30, 43, 43]
    # The full-bank final phase also covers the later all-player phases.
    assert step.phases[-1].clock.selected_owner == 2
    assert step.after == ReplayAIClock(3, (23, 33, 0, 53))


def test_gaia_is_a_real_turn_and_full_rotation_accumulates_each_recorded_delta() -> None:
    clock = ReplayAIClock(0, (0, 0, 0, 0))
    received = []
    for delta in (28, 27, 13, 43, 13):
        step = advance_replay_ai_clock(clock, delta)
        elapsed = step.phases[-1].clock.elapsed_i32(clock.selected_owner)
        received.append((clock.selected_owner, elapsed))
        clock = step.after
    assert received == [(0, 28), (1, 55), (2, 68), (3, 111), (0, 96)]
    assert clock == ReplayAIClock(1, (0, 69, 56, 13))


def test_completed_zero_delta_pass_rotates_and_clears_existing_selected_bank() -> None:
    clock = ReplayAIClock(1, (5, 9, 13))
    step = advance_replay_ai_clock(clock, 0)
    assert all(phase.clock == clock for phase in step.phases)
    assert step.after == ReplayAIClock(2, (5, 0, 13))


def test_one_owner_clears_then_returns_to_itself() -> None:
    step = advance_replay_ai_clock(ReplayAIClock(0, (0xFFFFFFFF,)), 1)
    assert step.phases[0].clock == ReplayAIClock(0, (0,))
    assert step.after == ReplayAIClock(0, (0,))


def test_unsigned_state_signed_getter_and_wrapping_add_are_separate() -> None:
    clock = ReplayAIClock(2, (0xFFFFFFFF, 0x7FFFFFFF, 0x80000000))
    assert [clock.elapsed_i32(owner) for owner in range(3)] == [-1, 0x7FFFFFFF, -0x80000000]
    step = advance_replay_ai_clock(clock, 1)
    bank = step.phases[-1].clock
    assert bank.elapsed_words == (0, 0x80000000, 0x80000001)
    assert [bank.elapsed_i32(owner) for owner in range(3)] == [0, -0x80000000, -0x7FFFFFFF]
    assert step.after.elapsed_words == (0, 0x80000000, 0)


def test_invalid_native_selected_index_has_no_safe_normalization_contract() -> None:
    unsafe = {case["selected_owner"]: case for case in _fixture()["invalid_native_states"]}
    # Sign-extending -1 clears world188 itself, then INC produces1. Sign-
    # extending -2 clears world184 and retains -1 under the signed comparison.
    assert unsafe[0xFFFFFFFF]["after"][1] == 1
    assert unsafe[0xFFFFFFFE]["after"][:2] == [0, 0xFFFFFFFF]
    # Out-of-bank +4 clears the first word past four valid owners before wrap.
    assert unsafe[4]["after"][1] == 0
    assert unsafe[4]["after"][6] == 0


@pytest.mark.parametrize("selected", (-2, -1, 3, 4, 0xFFFFFFFF, 1.5, "1", None))
def test_invalid_selected_owner_is_rejected_without_clamping_or_modulo(selected: Any) -> None:
    with pytest.raises(ValueError, match="selected owner"):
        ReplayAIClock(selected, (10, 20, 30))


@pytest.mark.parametrize("words", ((), [], [1, 2], (-1,), (0x100000000,), (1.5,), (None,)))
def test_invalid_or_mutable_bank_is_rejected(words: Any) -> None:
    with pytest.raises(ValueError, match="bank"):
        ReplayAIClock(0, words)


@pytest.mark.parametrize("delta", (-1, 0x100000000, 1.5, "13", None))
def test_invalid_delta_does_not_mutate_clock(delta: Any) -> None:
    clock = ReplayAIClock(0, (10, 20, 30))
    with pytest.raises(ValueError, match=r"delta.*u32"):
        advance_replay_ai_clock(clock, delta)
    assert clock == ReplayAIClock(0, (10, 20, 30))


@pytest.mark.parametrize("owner", (-1, 3, 0xFFFFFFFF, 1.5, None))
def test_elapsed_getter_rejects_unsafe_indices(owner: Any) -> None:
    with pytest.raises(ValueError, match="elapsed owner"):
        ReplayAIClock(1, (10, 20, 30)).elapsed_i32(owner)


@pytest.mark.parametrize("owner", (-1, 0x100000000, 1.5, None))
def test_predicate_accepts_word_equality_without_indexing_but_rejects_non_words(owner: Any) -> None:
    with pytest.raises(ValueError, match=r"comparison.*u32"):
        ReplayAIClock(1, (10, 20, 30)).is_selected_owner(owner)
