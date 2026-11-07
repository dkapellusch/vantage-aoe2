"""Completed replay reuse must retain its recording and terminal evidence."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from vantage import native_v32_reuse as reuse
from vantage.native_conversion import pin


def completed_job(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    job = tmp_path / "job"
    encoded = job / "encodes" / "1" / "encoded"
    encoded.mkdir(parents=True)
    profile, config = tmp_path / "runtime.json", tmp_path / "config.json"
    profile.write_text("{}")
    config.write_text(json.dumps({"encoder": {"path": "/retained/convert.py"}}))
    (job / "stage.json").write_text(json.dumps({"worker": {"sha256": "worker"}}))
    checkpoint = {"capture": {"sha256": "capture"}, "receipt": {"sha256": "receipt"}}
    (job / "simulation-result.json").write_text(json.dumps(checkpoint))
    evidence = {
        "capture": checkpoint["capture"],
        "terminal_receipt": checkpoint["receipt"],
        "expected_frames": 3,
        "expected_end_ms": 31,
        "recording_end_reason": "recording_eof",
    }
    terminal = encoded.parent / "terminal.json"
    terminal.write_text(json.dumps(evidence))
    recording = encoded / "recording.vrec"
    recording.write_bytes(b"verified recording")
    report = {
        "status": "conversion_verified",
        "recording": pin(recording),
        "capture_frames": 3,
        "capture_end_ms": 31,
        "all_serialized_Frame_bytes_readback_digest_checked": True,
        "terminal_evidence": evidence,
    }
    (encoded / "conversion.json").write_text(json.dumps(report))
    stdout, stderr = encoded.parent / "encode.stdout", encoded.parent / "encode.stderr"
    stdout.write_text("")
    stderr.write_text("")
    process = encoded.parent / "encoder.process-exit.json"
    process.write_text(
        json.dumps(
            {
                "exit_code": 0,
                "stop_reason": None,
                "terminal": pin(terminal),
                "config": pin(config),
                "stdout": pin(stdout),
                "stderr": pin(stderr),
            }
        )
    )
    encoding = {
        "recording": pin(recording),
        "conversion": pin(encoded / "conversion.json"),
        "terminal": pin(terminal),
        "process_receipt": pin(process),
        "encoder_config": pin(config),
    }
    result = {
        "status": "experimental_v32_recording_verified",
        "shipping_cache_published": False,
        "general_game_parity_verified": False,
        "stage": pin(job / "stage.json"),
        "worker": {"sha256": "worker"},
        "run": checkpoint,
        "recording": pin(recording),
        "encoding": encoding,
    }
    monkeypatch.setattr(reuse, "admit_v32_capture", lambda *_args, **_kwargs: evidence)
    return job, profile, config, result


def verify(job, profile, config, result):
    return reuse.verified_recording(
        job,
        result,
        runtime_profile=profile,
        runtime_profile_sha256=pin(profile)["sha256"],
        encoder_config=config,
        encoder_config_sha256=pin(config)["sha256"],
    )


def test_completed_job_is_rechecked_without_a_worker(tmp_path: Path, monkeypatch):
    job, profile, config, result = completed_job(tmp_path, monkeypatch)
    assert verify(job, profile, config, result)["frames"] == 3


@pytest.mark.parametrize(
    "changed", ["recording", "report", "terminal", "process", "stdout", "checkpoint"]
)
def test_reuse_rejects_changed_artifacts(tmp_path: Path, monkeypatch, changed):
    job, profile, config, result = completed_job(tmp_path, monkeypatch)
    target = {
        "recording": result["recording"]["path"],
        "report": result["encoding"]["conversion"]["path"],
        "terminal": result["encoding"]["terminal"]["path"],
        "process": result["encoding"]["process_receipt"]["path"],
        "stdout": str(Path(result["encoding"]["process_receipt"]["path"]).parent / "encode.stdout"),
        "checkpoint": str(job / "simulation-result.json"),
    }[changed]
    Path(target).write_text("{}")
    with pytest.raises(reuse.V32ReuseError):
        verify(job, profile, config, result)
