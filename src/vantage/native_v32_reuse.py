"""Revalidate a completed experimental V32 job without rerunning its worker."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from vantage.native_conversion import pin
from vantage.native_v32_admission import admit_v32_capture
from vantage.native_v32_encode import _tracked_join_contract, _verify_tracked_join_output


class V32ReuseError(RuntimeError):
    """The retained recording or its provenance no longer matches the job."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise V32ReuseError(message)


def verified_recording(
    job: Path,
    result: dict[Any, Any],
    *,
    runtime_profile: Path,
    runtime_profile_sha256: str,
    encoder_config: Path,
    encoder_config_sha256: str,
) -> dict[Any, Any]:
    """Recheck provenance and bytes before reusing an already completed VREC."""
    try:
        return _verify(
            job,
            result,
            runtime_profile,
            runtime_profile_sha256,
            encoder_config,
            encoder_config_sha256,
        )
    except (KeyError, TypeError, ValueError, OSError) as error:
        raise V32ReuseError(f"Invalid retained V32 recording: {error}") from error


def _verify(
    job: Path,
    result: dict[Any, Any],
    runtime_profile: Path,
    runtime_sha: str,
    encoder_config: Path,
    encoder_sha: str,
) -> dict[Any, Any]:
    job = job.resolve(strict=True)
    _require(
        result.get("status") == "experimental_v32_recording_verified"
        and result.get("shipping_cache_published") is False
        and result.get("general_game_parity_verified") is False,
        "Pipeline result rejected",
    )
    stage_pin = pin(job / "stage.json")
    _require(result["stage"] == stage_pin, "Stage differs")
    stage = json.loads((job / "stage.json").read_bytes())
    _require(stage["worker"] == result["worker"], "Worker differs")
    checkpoint = json.loads((job / "simulation-result.json").read_bytes())
    _require(result["run"] == checkpoint, "Simulation checkpoint differs")
    encoding = result["encoding"]
    config_pin = pin(encoder_config.resolve(strict=True))
    _require(
        config_pin["sha256"] == encoder_sha and encoding["encoder_config"] == config_pin,
        "Encoder configuration differs",
    )
    _require(result["recording"] == encoding["recording"], "Recording identity differs")
    recording = Path(result["recording"]["path"])
    _require(
        recording.is_absolute()
        and recording.resolve(strict=True) == recording
        and recording.name == "recording.vrec"
        and recording.parent.name == "encoded"
        and recording.parent.parent.parent == job / "encodes",
        "Recording is outside job",
    )
    encode_dir = recording.parent.parent
    for name, expected in [
        ("conversion.json", encoding["conversion"]),
        ("recording.vrec", encoding["recording"]),
    ]:
        _require(pin(recording.parent / name) == expected, f"{name} differs")
    terminal_path, process_path = (
        encode_dir / "terminal.json",
        encode_dir / "encoder.process-exit.json",
    )
    _require(
        pin(terminal_path) == encoding["terminal"]
        and pin(process_path) == encoding["process_receipt"],
        "Encoder evidence differs",
    )
    process = json.loads(process_path.read_bytes())
    stdout_path, stderr_path = encode_dir / "encode.stdout", encode_dir / "encode.stderr"
    _require(
        process.get("exit_code") == 0
        and process.get("stop_reason") is None
        and process.get("terminal") == encoding["terminal"]
        and process.get("config") == config_pin
        and process.get("stdout") == pin(stdout_path)
        and process.get("stderr") == pin(stderr_path),
        "Encoder process did not finish cleanly",
    )
    config = json.loads(encoder_config.read_bytes())
    tracked = _tracked_join_contract(config)
    if tracked is not None:
        _require(
            encoding.get("experimental_runtime")
            == _verify_tracked_join_output(stdout_path, tracked),
            "Experimental encoder provenance differs",
        )
    # Revalidate raw worker, stage, assets, checksum-enabled terminal and cadence.
    evidence = admit_v32_capture(
        job,
        checkpoint,
        stage_sha256=stage_pin["sha256"],
        runtime_profile=runtime_profile,
        runtime_profile_sha256=runtime_sha,
    )
    original = json.loads(terminal_path.read_bytes())
    report = json.loads((recording.parent / "conversion.json").read_bytes())
    _require(
        original.get("capture") == evidence["capture"]
        and original.get("terminal_receipt") == evidence["terminal_receipt"]
        and original.get("expected_frames") == evidence["expected_frames"]
        and original.get("expected_end_ms") == evidence["expected_end_ms"]
        and original.get("recording_end_reason") == evidence["recording_end_reason"],
        "Saved terminal evidence differs",
    )
    _require(
        report.get("status") == "conversion_verified"
        and report.get("recording") == result["recording"]
        and report.get("capture_frames") == evidence["expected_frames"]
        and report.get("capture_end_ms") == evidence["expected_end_ms"]
        and report.get("all_serialized_Frame_bytes_readback_digest_checked") is True
        and report.get("terminal_evidence") == original,
        "Recording verification differs",
    )
    _require(
        pin(recording) == result["recording"]
        and pin(recording.parent / "conversion.json") == encoding["conversion"]
        and pin(terminal_path) == encoding["terminal"]
        and pin(process_path) == encoding["process_receipt"]
        and pin(stdout_path) == process["stdout"]
        and pin(stderr_path) == process["stderr"]
        and pin(job / "stage.json") == stage_pin
        and pin(encoder_config) == config_pin,
        "Retained output changed during verification",
    )
    return {
        "recording": result["recording"],
        "frames": evidence["expected_frames"],
        "end_ms": evidence["expected_end_ms"],
        "recording_end_reason": evidence["recording_end_reason"],
        "general_game_parity_verified": False,
    }
