"""Explicit SDK audio validation keeps the original replay gates intact."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from native_sdk_fixtures import fixture as cadence_fixture

from vantage import native_conversion as native
from vantage import native_sdk_admission as sdk
from vantage.native_sdk_admission import SDK_COMPLETION, SDK_STARTUP


def fixture(positive: bool, ended: bool):
    descriptor, events = cadence_fixture(positive, ended)
    completion = next(e for e in events if e.get("stage") == "native_simulation_prefix_complete")
    del completion["audio_requests"]
    completion.update(copy.deepcopy(SDK_COMPLETION))
    events.insert(0, copy.deepcopy(SDK_STARTUP))
    return descriptor, events


def save(tmp_path: Path, events: list[dict]):
    capture = tmp_path / "capture.jsonl"
    capture.write_text("".join(json.dumps(e) + "\n" for e in events))
    receipt = tmp_path / "receipt.json"
    receipt.write_text(
        json.dumps(
            {
                "receipt_kind": "ordinary_owned_subprocess",
                "exit_code": 0,
                "timed_out": False,
                "cancelled": False,
                "all_input_pins_unchanged": True,
                "stdout_sha256": native.pin(capture)["sha256"],
            }
        )
    )
    return capture, receipt


@pytest.mark.parametrize("positive", [False, True])
@pytest.mark.parametrize("ended", [False, True])
def test_explicit_sdk_gate_preserves_terminal_mode_and_default_rejects(tmp_path, positive, ended):
    descriptor, events = fixture(positive, ended)
    capture, receipt = save(tmp_path, events)
    with pytest.raises(native.ConversionError, match="Completion contract rejected"):
        native.terminal_evidence_for_input(capture, receipt, descriptor)
    result = sdk.terminal_evidence_for_input(capture, receipt, descriptor)
    assert result["expected_frames"] == 3 + int(positive)
    assert result["game_ended"] is ended and not result["game_end_inferred_from_EOF"]
    assert result["original_sdk_audio_startup"] == SDK_STARTUP


@pytest.mark.parametrize("positive", [False, True])
@pytest.mark.parametrize(
    "problem",
    [
        "missing",
        "duplicate",
        "late",
        "wrong_threads",
        "wrong_bank",
        "extra_startup",
        "extra_audio",
        "disabled_counter",
        "disabled_event",
        "checksum",
        "cadence",
    ],
)
def test_sdk_gate_rejects_invalid_audio_and_original_guards(tmp_path, positive, problem):
    descriptor, events = fixture(positive, False)
    completion = next(e for e in events if e.get("stage") == "native_simulation_prefix_complete")
    if problem == "missing":
        events.pop(0)
    elif problem == "duplicate":
        events.insert(1, copy.deepcopy(SDK_STARTUP))
    elif problem == "late":
        events.append(events.pop(0))
    elif problem == "wrong_threads":
        events[0]["audio_threads"] = [False, 1]
    elif problem == "wrong_bank":
        events[0]["bank_ids"][1] += 1
    elif problem == "extra_startup":
        events[0]["unexpected"] = 0
    elif problem == "extra_audio":
        completion["native_audio_unknown"] = 1
    elif problem == "disabled_counter":
        completion["audio_requests"] = 0
    elif problem == "disabled_event":
        events.insert(1, {"stage": "headless_audio_request"})
    elif problem == "checksum":
        next(e for e in events if e.get("stage") == "native_replay_terminal_state")[
            "checksum_ignore_global"
        ] = 1
    elif problem == "cadence":
        next(e for e in events if e.get("stage") == "native_world_frame")["time_ms"] = 9
    capture, receipt = save(tmp_path, events)
    with pytest.raises(native.ConversionError):
        sdk.terminal_evidence_for_input(capture, receipt, descriptor)
