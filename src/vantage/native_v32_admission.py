"""Source-bind an experimental V32 capture to the explicit offline SDK gate.

This does not launch a worker or publish a recording. The caller supplies exact
stage and runtime-profile hashes and must choose a compatible binary and assets.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from vantage import native_sdk_admission
from vantage.native_conversion import pin
from vantage.native_v32_runtime import V32RuntimeError, _verify


class V32AdmissionError(RuntimeError):
    """The capture cannot be bound to its staged worker and process receipt."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise V32AdmissionError(message)


def admit_v32_capture(
    stage_dir: Path,
    result: dict[Any, Any],
    *,
    stage_sha256: str,
    runtime_profile: Path,
    runtime_profile_sha256: str,
) -> dict[Any, Any]:
    """Validate a raw V32 capture, then return the SDK terminal evidence.

    Process isolation is an assertion from the checked private-runner receipt;
    this function does not independently observe OS namespaces. It deliberately
    does not accept reconstructed stdout as raw process output.
    """
    try:
        return _admit(stage_dir, result, stage_sha256, runtime_profile, runtime_profile_sha256)
    except (KeyError, TypeError, ValueError, OSError, V32RuntimeError) as error:
        raise V32AdmissionError(f"Invalid or changed V32 admission input: {error}") from error


def _admit(
    stage_dir: Path, result: dict[Any, Any], stage_sha256: str, profile: Path, profile_sha256: str
) -> dict[Any, Any]:
    admission_source = pin(Path(__file__).resolve())
    stage_dir = stage_dir.resolve(strict=True)
    source = stage_dir / "source"
    stage_path = stage_dir / "stage.json"
    profile = profile.resolve(strict=True)
    stage_pin, profile_pin = pin(stage_path), pin(profile)
    _require(stage_pin["sha256"] == stage_sha256, "Stage hash differs")
    _require(profile_pin["sha256"] == profile_sha256, "Runtime profile hash differs")
    stage, runtime = json.loads(stage_path.read_bytes()), json.loads(profile.read_bytes())
    _require(stage.get("kind") == "vantage_experimental_v32_staged_worker", "Unsupported stage")
    _require(
        runtime.get("kind") == "vantage_experimental_v32_runtime"
        and type(runtime.get("version")) is int
        and runtime["version"] == 1,
        "Unsupported runtime profile",
    )
    _require(stage["profile"] == runtime["staging_profile"], "Staging profile differs")
    _require(
        stage["source_root"] == str(source) == stage["runtime_source_root"], "Wrong source root"
    )
    _require(source.resolve(strict=True) == source, "Source root is not canonical")
    run_dir = Path(result["run_dir"])
    _require(
        run_dir.is_absolute()
        and run_dir.resolve(strict=True) == run_dir
        and run_dir.parent == stage_dir / "runs",
        "Run directory differs",
    )
    capture, receipt_path = (
        run_dir / "native.stdout.log",
        run_dir / "native.verified-process-exit.json",
    )
    _require(
        result["capture"] == pin(capture) and result["receipt"] == pin(receipt_path),
        "Result pins differ",
    )
    receipt = json.loads(receipt_path.read_bytes())
    _require(
        receipt.get("stage") == stage_pin and receipt.get("runtime_profile") == profile_pin,
        "Process receipt is not bound to this stage and profile",
    )
    _require(
        receipt.get("private_namespace") is True
        and receipt.get("private_xvfb") is True
        and receipt.get("standard_owned_display_admission_used") is False
        and receipt.get("all_input_pins_unchanged") is True
        and not receipt.get("stdout_is_derived", False),
        "Private runtime receipt rejected",
    )
    process_receipt = run_dir / "native.process-exit.json"
    _require(receipt["source_process_receipt"] == pin(process_receipt), "Process receipt changed")
    observed = json.loads(process_receipt.read_bytes())
    for key in (
        "receipt_kind",
        "exit_code",
        "timed_out",
        "cancelled",
        "stop_reason",
        "stdout_sha256",
        "stderr_sha256",
        "stage",
        "runtime_profile",
        "private_namespace",
        "private_xvfb",
    ):
        _require(receipt.get(key) == observed.get(key), f"Process observation differs: {key}")
    stderr = run_dir / "native.stderr.log"
    stderr_pin = pin(stderr)
    _require(stderr_pin["sha256"] == receipt["stderr_sha256"], "Worker stderr differs")
    static = [
        runtime["staging_profile"],
        runtime["raw_dat"],
        *runtime["system"].values(),
        *runtime["assets"].values(),
        *runtime["technology_assets"],
    ]
    staged = [
        stage["profile"],
        stage["recording"],
        stage["host"],
        stage["worker"],
        *stage["stager_sources"],
        *stage["copied_sources"],
        *stage["generated"],
    ]
    for row in static + staged:
        _verify(row)
    recipe = json.loads(Path(stage["profile"]["path"]).read_bytes())
    _require(stage["host"]["sha256"] == recipe["host"]["sha256"], "Host recipe differs")
    _require(
        Path(stage["host"]["path"]) == source / "host.cpp"
        and Path(stage["worker"]["path"]) == source / "vantage-native-input-derived.exe",
        "Worker source differs",
    )
    expected_names = {
        "prepared_config.h",
        "entity_expectations.h",
        "input-save.inflated.bin",
        "native_input_profile.h",
        "descriptor.json",
    }
    _require(
        len(stage["generated"]) == len(expected_names)
        and {Path(row["path"]).name for row in stage["generated"]} == expected_names,
        "Generated input set differs",
    )

    def verify_generated_copies() -> None:
        for row in stage["generated"]:
            original = Path(row["path"])
            _require(original.parent == stage_dir / "generated", "Generated input is outside stage")
            copied = source / original.name
            _require(copied.resolve(strict=True) == copied, "Generated copy is not canonical")
            actual = pin(copied)
            _require(
                (actual["bytes"], actual["sha256"]) == (row["bytes"], row["sha256"]),
                "Generated copy differs",
            )

    verify_generated_copies()
    descriptor = json.loads((source / "descriptor.json").read_bytes())
    _require(
        descriptor.get("recording_sha256") == stage["recording"]["sha256"]
        and descriptor.get("recording_bytes") == stage["recording"]["bytes"],
        "Descriptor recording differs",
    )
    # Approximate mode is an explicit profile property, never part of the descriptor identity.
    approximate = {"approximate_checksums": True} if recipe.get("approximate_checksums") else {}
    evidence = native_sdk_admission.terminal_evidence_for_input(
        capture, receipt_path, descriptor, **approximate
    )
    for row in static + staged:
        _verify(row)
    verify_generated_copies()
    _verify(admission_source)
    _require(
        pin(stage_path) == stage_pin and pin(profile) == profile_pin, "Stage or profile changed"
    )
    _require(
        result["capture"] == pin(capture)
        and result["receipt"] == pin(receipt_path)
        and stderr_pin == pin(stderr)
        and receipt["source_process_receipt"] == pin(process_receipt),
        "Run changed",
    )
    evidence["v32_producer"] = {
        "stage": stage_pin,
        "runtime_profile": profile_pin,
        "worker": stage["worker"],
        "staging_profile": stage["profile"],
        "raw_process_receipt": pin(process_receipt),
        "admission_source": admission_source,
        "isolation_observed_independently": False,
        "qualification": "Pinned producer and process receipt; not an ordinary-game parity oracle.",
    }
    return evidence
