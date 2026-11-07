"""Actual callback and independent native components joined at the motion boundary."""

from __future__ import annotations

import gzip
import hashlib
import json
import math
import struct
from pathlib import Path
from typing import Any

import pytest

from vantage.replay_motion_phase import (
    ReplayMotionPhaseResult,
    UnsupportedReplayMotionPhase,
    advance_replay_motion_phase,
)

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def native_cases() -> dict[str, Any]:
    raw = (FIXTURES / "native_replay_motion_phase_54800.json.gz").read_bytes()
    assert hashlib.sha256(raw).hexdigest() == (
        "673bccd7676657da9dbd7e7e3196728f667f70f83fb3688589c862c7bfd07861"
    )
    return json.loads(gzip.decompress(raw))


def advance_case(case: dict[str, Any]) -> ReplayMotionPhaseResult:
    return advance_replay_motion_phase(
        bytes.fromhex(case["motion_before_hex"]),
        tuple(case["stored_position"]),
        tuple(case["stored_direction"]),
        case["elapsed_bits"],
        case["multiplier414_bits"],
        case["speed_cap_bits"],
        formation_id=case["formation_id"],
    )


def test_actual_moving_callback_motion_and_intended_endpoint(native_cases: dict[str, Any]) -> None:
    case = native_cases["actual"]
    assert native_cases["provenance"]["actual_moving_call_evidence"] == (
        "ev_97108025d6f26fdab88418bc065977fb20619d020e8c255aafbb3e48435cbd03"
    )
    assert case["stored_position"] == [0x431D6444, 0, 0x42FFF9D6]
    assert case["expected_setter_position"] == [0x431D6649, 0, 0x42FFF784]
    result = advance_case(case)
    assert result.motion_record == bytes.fromhex(case["motion_after_hex"])
    assert result.intended_setter_position == tuple(case["expected_setter_position"])


def test_original_component_composition_and_opaque_byte_preservation(
    native_cases: dict[str, Any],
) -> None:
    cases = native_cases["composed"]
    assert len(cases) == 605
    reached = changes_without_setter = 0
    for case in cases:
        before = bytes.fromhex(case["motion_before_hex"])
        result = advance_case(case)
        assert len(result.motion_record) == 24
        assert result.motion_record[:8] == before[:8]
        assert result.motion_record[12:] == before[12:]
        assert (
            struct.unpack_from("<I", result.motion_record, 8)[0] == (case["expected_velocity_bits"])
        )
        expected = case["expected_setter_position"]
        assert result.intended_setter_position == (None if expected is None else tuple(expected))
        reached += expected is not None
        changes_without_setter += expected is None and result.motion_record != before
    assert reached == 385
    assert changes_without_setter == 143


def test_composed_expectations_are_unmodified_original_outputs(
    native_cases: dict[str, Any],
) -> None:
    provenance = native_cases["provenance"]
    assert provenance["composition_is_whole_native_caller_execution"] is False
    assert provenance["new_native_execution"] is False
    assert provenance["shipping_code_imported"] is False
    raw_velocity = (FIXTURES / "native_replay_controller_velocity_54800.json.gz").read_bytes()
    raw_translation = (FIXTURES / "native_replay_translation_54800.json.gz").read_bytes()
    assert hashlib.sha256(raw_velocity).hexdigest() == provenance["velocity_fixture_sha256"]
    assert hashlib.sha256(raw_translation).hexdigest() == provenance["translation_fixture_sha256"]
    velocities = json.loads(gzip.decompress(raw_velocity))
    translations = json.loads(gzip.decompress(raw_translation))["rows"]
    assert len(velocities) == 73728
    assert len(translations) == 5307
    boundaries = set()
    for case in native_cases["composed"]:
        original_velocity = velocities[case["velocity_ordinal"]]
        old, acceleration, elapsed, cap, expected = original_velocity
        before = bytes.fromhex(case["motion_before_hex"])
        assert struct.unpack_from("<I", before, 8)[0] == old
        assert struct.unpack_from("<I", before, 20)[0] == acceleration
        assert case["elapsed_bits"] == elapsed
        assert case["speed_cap_bits"] == cap
        assert case["expected_velocity_bits"] == expected
        original_translation = translations[case["translation_ordinal"]]
        displacement, multiplier, *vectors = original_translation["input"]
        assert original_translation["mxcsr"] & 0xE040 == 0
        assert case["boundary_displacement_bits"] == displacement
        assert case["multiplier414_bits"] == multiplier
        assert case["stored_position"] == vectors[:3]
        assert case["stored_direction"] == vectors[3:]
        assert case["expected_setter_position"] == (
            original_translation["endpoint"] if original_translation["setter_checkpoint"] else None
        )
        # This only qualifies the shared MULSS input boundary. Both expected
        # component outputs above are retained from unchanged original code.
        values = [struct.unpack("<f", struct.pack("<I", word))[0] for word in original_velocity]
        assert all(math.isfinite(value) for value in values)
        product = values[2] * values[4]
        try:
            raw_product = struct.pack("<f", product)
        except OverflowError:
            raw_product = struct.pack("<I", 0xFF800000 if product < 0 else 0x7F800000)
        assert struct.unpack("<I", raw_product)[0] == displacement
        boundaries.add(displacement)
    assert len(boundaries) == 11


def test_no_setter_call_still_returns_updated_velocity(native_cases: dict[str, Any]) -> None:
    case = next(
        case
        for case in native_cases["composed"]
        if case["expected_setter_position"] is None
        and struct.unpack_from("<I", bytes.fromhex(case["motion_before_hex"]), 8)[0]
        != case["expected_velocity_bits"]
    )
    result = advance_case(case)
    assert result.intended_setter_position is None
    assert result.motion_record != bytes.fromhex(case["motion_before_hex"])
    assert struct.unpack_from("<I", result.motion_record, 8)[0] == case["expected_velocity_bits"]


@pytest.mark.parametrize("formation", [0, 1, -2, True, -1.0, None])
def test_formation_admission_is_explicit_and_exact(formation: Any) -> None:
    with pytest.raises(UnsupportedReplayMotionPhase, match="formation_id=-1"):
        advance_replay_motion_phase(
            bytes(24), (0, 0, 0), (0, 0, 0), 0, 0, 0, formation_id=formation
        )


def test_omitting_formation_context_is_not_an_implicit_null_formation() -> None:
    with pytest.raises(TypeError, match="formation_id"):
        advance_replay_motion_phase(bytes(24), (0, 0, 0), (0, 0, 0), 0, 0, 0)


@pytest.mark.parametrize(
    "record", [b"", bytes(23), bytes(25), bytearray(24), memoryview(bytes(24))]
)
def test_motion_record_requires_exact_immutable_bytes(record: Any) -> None:
    with pytest.raises(ValueError, match="24-byte immutable"):
        advance_replay_motion_phase(record, (0, 0, 0), (0, 0, 0), 0, 0, 0, formation_id=-1)


@pytest.mark.parametrize("field", ["elapsed_bits", "multiplier414_bits", "speed_cap_bits"])
@pytest.mark.parametrize("value", [-1, 0x100000000, 1.5])
def test_scalar_word_validation_reaches_existing_arithmetic_helpers(field: str, value: Any) -> None:
    arguments = {"elapsed_bits": 0, "multiplier414_bits": 0, "speed_cap_bits": 0}
    arguments[field] = value
    with pytest.raises(ValueError):
        advance_replay_motion_phase(bytes(24), (0, 0, 0), (0, 0, 0), **arguments, formation_id=-1)


@pytest.mark.parametrize("field", ["stored_position", "stored_direction"])
def test_vector_validation_is_preserved_even_when_translation_would_be_zero(field: str) -> None:
    arguments = {"stored_position": (0, 0, 0), "stored_direction": (0, 0, 0)}
    arguments[field] = (0, 0)
    with pytest.raises(ValueError):
        advance_replay_motion_phase(
            bytes(24),
            **arguments,
            elapsed_bits=0,
            multiplier414_bits=0,
            speed_cap_bits=0,
            formation_id=-1,
        )
