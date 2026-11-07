"""V32 admission binds the terminal gate to the staged private run."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from test_native_sdk_admission import fixture

from vantage.native_conversion import pin
from vantage.native_v32_admission import V32AdmissionError, admit_v32_capture


@pytest.fixture
def staged_capture(tmp_path: Path):
    stage_dir = tmp_path / "job"
    source, generated, run = stage_dir / "source", stage_dir / "generated", stage_dir / "runs" / "a"
    for path in (source, generated, run):
        path.mkdir(parents=True)
    recording = tmp_path / "recording.aoe2record"
    recording.write_bytes(b"fixture replay")
    descriptor, events = fixture(False, False)
    descriptor["recording_sha256"] = pin(recording)["sha256"]
    descriptor["recording_bytes"] = pin(recording)["bytes"]
    # Keep the existing close contract in agreement with the synthetic input.
    descriptor["postgame_remaining_bytes"] = descriptor["recording_bytes"] - 4
    descriptor["postgame_marker_end"] = 4
    for event in events:
        if event.get("stage") == "owned_recording_postgame_close":
            event.update(
                position=4,
                file_bytes=descriptor["recording_bytes"],
                unread_tail_bytes=descriptor["postgame_remaining_bytes"],
            )
        elif event.get("stage") == "native_replay_terminal_state":
            event["file_cursor"] = 4
    generated_pins = []
    for name in (
        "prepared_config.h",
        "entity_expectations.h",
        "input-save.inflated.bin",
        "native_input_profile.h",
        "descriptor.json",
    ):
        content = json.dumps(descriptor).encode() if name == "descriptor.json" else name.encode()
        (generated / name).write_bytes(content)
        (source / name).write_bytes(content)
        generated_pins.append(pin(generated / name))
    (source / "host.cpp").write_text("host")
    (source / "vantage-native-input-derived.exe").write_text("worker")
    staging_profile = tmp_path / "staging.json"
    staging_profile.write_text(json.dumps({"host": pin(source / "host.cpp")}))
    stage = {
        "kind": "vantage_experimental_v32_staged_worker",
        "profile": pin(staging_profile),
        "recording": pin(recording),
        "host": pin(source / "host.cpp"),
        "worker": pin(source / "vantage-native-input-derived.exe"),
        "source_root": str(source),
        "runtime_source_root": str(source),
        "stager_sources": [],
        "copied_sources": [],
        "generated": generated_pins,
    }
    stage_path = stage_dir / "stage.json"
    stage_path.write_text(json.dumps(stage))
    profile = tmp_path / "runtime.json"
    profile.write_text(
        json.dumps(
            {
                "kind": "vantage_experimental_v32_runtime",
                "version": 1,
                "staging_profile": pin(staging_profile),
                "raw_dat": pin(recording),
                "system": {},
                "assets": {},
                "technology_assets": [],
            }
        )
    )
    capture = run / "native.stdout.log"
    capture.write_text("".join(json.dumps(event) + "\n" for event in events))
    (run / "native.stderr.log").write_text("")
    raw = {
        "receipt_kind": "ordinary_owned_subprocess",
        "exit_code": 0,
        "timed_out": False,
        "cancelled": False,
        "stop_reason": None,
        "stdout_sha256": pin(capture)["sha256"],
        "stderr_sha256": pin(run / "native.stderr.log")["sha256"],
        "stage": pin(stage_path),
        "runtime_profile": pin(profile),
        "private_namespace": True,
        "private_xvfb": True,
        "standard_owned_display_admission_used": False,
        "all_input_pins_unchanged": False,
    }
    raw_path = run / "native.process-exit.json"
    raw_path.write_text(json.dumps(raw))
    receipt = dict(raw, all_input_pins_unchanged=True, source_process_receipt=pin(raw_path))
    receipt_path = run / "native.verified-process-exit.json"
    receipt_path.write_text(json.dumps(receipt))
    result = {"run_dir": str(run), "capture": pin(capture), "receipt": pin(receipt_path)}
    return stage_dir, profile, result


def admit(stage: Path, profile: Path, result: dict):
    return admit_v32_capture(
        stage,
        result,
        stage_sha256=pin(stage / "stage.json")["sha256"],
        runtime_profile=profile,
        runtime_profile_sha256=pin(profile)["sha256"],
    )


def test_binds_capture_to_stage_runtime_and_terminal(staged_capture):
    stage, profile, result = staged_capture
    evidence = admit(stage, profile, result)
    assert evidence["expected_frames"] == 3 and evidence["recording_end_reason"] == "recording_eof"
    assert evidence["v32_producer"]["isolation_observed_independently"] is False


@pytest.mark.parametrize(
    "problem", ["capture", "stderr", "descriptor", "profile", "raw_receipt", "derived"]
)
def test_changed_or_derived_input_is_rejected(staged_capture, problem):
    stage, profile, result = staged_capture
    run = Path(result["run_dir"])
    if problem == "capture":
        (run / "native.stdout.log").write_text("changed")
    elif problem == "stderr":
        (run / "native.stderr.log").write_text("changed")
    elif problem == "descriptor":
        (stage / "source/descriptor.json").write_text("{}")
    elif problem == "profile":
        profile.write_text("{}")
    elif problem == "raw_receipt":
        (run / "native.process-exit.json").write_text("{}")
    elif problem == "derived":
        receipt_path = run / "native.verified-process-exit.json"
        receipt = json.loads(receipt_path.read_text())
        receipt["stdout_is_derived"] = True
        receipt_path.write_text(json.dumps(receipt))
        result["receipt"] = pin(receipt_path)
    with pytest.raises(V32AdmissionError):
        admit(stage, profile, result)
