"""Retained unchanged native cap/ordered modifier outputs and bounded branch tests."""

from __future__ import annotations

import gzip
import json
from pathlib import Path

import pytest

from vantage.replay_movement_cap import (
    ReplayStatModifier,
    UnsupportedReplaySpeedCap,
    apply_replay_stat_modifiers,
    replay_movement_base_speed,
    replay_unit_speed_cap,
)

FIXTURE = Path(__file__).parent / "fixtures/native_replay_speed_cap_54800.json.gz"


def _signed(word: int) -> int:
    return word if word < 0x80000000 else word - 0x100000000


def _check_native(cases: list[list], *, gate_cases: bool = False) -> None:
    for index, (row, raw_modifiers, expected) in enumerate(cases):
        modifiers = tuple(
            ReplayStatModifier(op, amount, unused) for op, unused, amount in raw_modifiers
        )
        base = replay_movement_base_speed(
            row[0],
            sprite_speed_bits=row[2] if row[1] else None,
            reference_id=_signed(row[3]),
            reference_factor_bits=row[4],
        )
        cap = replay_unit_speed_cap(
            row[0],
            master_target_boost_bits=row[12] if gate_cases else 0,
            sprite_speed_bits=row[2] if row[1] else None,
            reference_id=_signed(row[3]),
            reference_factor_bits=row[4],
            stop_count=_signed(row[5]),
            unit_addend_bits=row[6],
            secondary_addend_bits=row[7],
            bonus_bits=row[9] if row[8] else None,
            modifiers=modifiers if row[10] in (1, 2) else (),
        )
        assert [base, cap] == expected, (index, row, raw_modifiers)


def test_original_cap_chain_all_19143_cases() -> None:
    report = json.loads(gzip.decompress(FIXTURE.read_bytes()))
    assert len(report["cases"]) == 19143
    assert report["target_sha256"] == (
        "69832b9d51145a4bb280da876880198ee0347947098e77098016b9bcbb8d8788"
    )
    assert report["retained_evidence"] == [
        "ev_8ba11472e5319fc4f2b449d2572aaddebe9ed64ef895722ce4d698e483f4d871"
    ]
    assert report["original_instructions_changed"] is False
    assert report["original_imports_executed"] is False
    _check_native(report["cases"])


def test_original_gate_bypass_all_891_cases() -> None:
    report = json.loads(gzip.decompress(FIXTURE.read_bytes()))
    assert len(report["gate_cases"]) == 891
    assert report["gate_evidence"] == [
        "ev_d686b4e7c65b93dfe30b269ef663cc0365b3d385274c61e033b966a62663dad0"
    ]
    _check_native(report["gate_cases"], gate_cases=True)


@pytest.mark.parametrize("operation", [3, 4])
@pytest.mark.parametrize("current,amount", [(0, 0x80000000), (0x80000000, 0)])
def test_min_max_keep_current_zero_sign(operation: int, current: int, amount: int) -> None:
    assert apply_replay_stat_modifiers(current, (ReplayStatModifier(operation, amount),)) == current


@pytest.mark.parametrize("operation", [3, 4])
@pytest.mark.parametrize("current", [0x7FA12345, 0xFFC54321])
def test_min_max_keep_unordered_current_payload(operation: int, current: int) -> None:
    assert (
        apply_replay_stat_modifiers(current, (ReplayStatModifier(operation, 0x3F800000),))
        == current
    )


@pytest.mark.parametrize("operation", [3, 4])
def test_unordered_amount_selects_current(operation: int) -> None:
    assert apply_replay_stat_modifiers(
        0x3F800000, (ReplayStatModifier(operation, 0x7FA12345),)
    ) == (0x3F800000)


def test_noncommuting_modifiers_stay_in_vector_order() -> None:
    add, multiply = ReplayStatModifier(1, 0x3F800000), ReplayStatModifier(2, 0x40000000)
    assert apply_replay_stat_modifiers(0x3F800000, (add, multiply)) == 0x40800000
    assert apply_replay_stat_modifiers(0x3F800000, (multiply, add)) == 0x40400000


@pytest.mark.parametrize("operation", [0, 5, 0xFFFFFFFF])
def test_unknown_operation_preserves_raw_signaling_nan(operation: int) -> None:
    assert apply_replay_stat_modifiers(
        0x7FA12345, (ReplayStatModifier(operation, 0x7F800000),)
    ) == (0x7FA12345)


def test_reference_bonus_uses_original_master_speed() -> None:
    assert (
        replay_movement_base_speed(
            0x40000000,
            sprite_speed_bits=0x40400000,
            reference_id=0,
            reference_factor_bits=0x3F000000,
        )
        == 0x40E00000
    )  # 2*3 +2*.5 =7


def test_addends_round_in_native_order() -> None:
    assert (
        replay_unit_speed_cap(
            0x60AD78EC,
            master_target_boost_bits=0,
            unit_addend_bits=0xE0AD78EC,
            secondary_addend_bits=0x3F800000,
        )
        == 0x3F800000
    )
    assert (
        replay_unit_speed_cap(
            0x60AD78EC,
            master_target_boost_bits=0,
            unit_addend_bits=0x3F800000,
            secondary_addend_bits=0xE0AD78EC,
        )
        == 0
    )


def test_positive_stop_returns_zero_before_bonus_boost_and_modifiers() -> None:
    assert (
        replay_unit_speed_cap(
            0x7FA12345,
            master_target_boost_bits=0x7F800000,
            stop_count=1,
            bonus_bits=0x7F800000,
            modifiers=(ReplayStatModifier(1, 0x3F800000),),
        )
        == 0
    )


def test_zero_speed_bypasses_positive_boost_before_modifiers() -> None:
    assert (
        replay_unit_speed_cap(
            0,
            master_target_boost_bits=0x3F800000,
            modifiers=(ReplayStatModifier(1, 0x3F800000),),
        )
        == 0x3F800000
    )


@pytest.mark.parametrize("speed", [0x3F800000, 0xBF800000, 0x7FC12345])
def test_nonzero_or_unordered_speed_rejects_target_boost(speed: int) -> None:
    with pytest.raises(UnsupportedReplaySpeedCap, match="target-dependent"):
        replay_unit_speed_cap(speed, master_target_boost_bits=0x3F800000)


@pytest.mark.parametrize("gate", [0x80000000, 0xBF800000, 0xFF800000, 0x7FA12345])
def test_nonpositive_or_unordered_master_gate_bypasses_boost(gate: int) -> None:
    assert replay_unit_speed_cap(0x3F800000, master_target_boost_bits=gate) == 0x3F800000


@pytest.mark.parametrize(
    "kwargs",
    [
        {"master_target_boost_bits": -1},
        {"sprite_speed_bits": 0x100000000},
        {"reference_factor_bits": -1},
        {"reference_id": 0x80000000},
        {"reference_id": -0x80000001},
        {"stop_count": 0x80000000},
        {"stop_count": -0x80000001},
        {"unit_addend_bits": -1},
        {"secondary_addend_bits": 0x100000000},
        {"bonus_bits": -1},
        {"modifiers": []},
        {"modifiers": (None,)},
        {"modifiers": (ReplayStatModifier(1, -1),)},
        {"modifiers": (ReplayStatModifier(-1, 0),)},
        {"modifiers": (ReplayStatModifier(1, 0, 0x100000000),)},
    ],
)
def test_invalid_inputs_rejected(kwargs: dict) -> None:
    with pytest.raises(ValueError):
        replay_unit_speed_cap(0x3F800000, **{"master_target_boost_bits": 0, **kwargs})
