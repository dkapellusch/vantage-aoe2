"""Standalone client checks with an authored Python worker; no native execution."""

from __future__ import annotations

import gzip
import hashlib
import json
import sys
import threading
import time
from pathlib import Path

import pytest

from tests.helpers import game_frames
from vantage.frames import RecordingWriter
from vantage.native import NativeError, NativeJobs, NativeWorker, file_pin

FIXTURES = Path(__file__).parent / "fixtures"


def write(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, sort_keys=True))


def setup_worker(tmp_path: Path, mode: str = "good") -> tuple[NativeJobs, Path, Path]:
    script = tmp_path / "fixture-worker.py"
    script.write_bytes((FIXTURES / "native_worker.py").read_bytes())
    template = tmp_path / "template.vrec"
    frames = game_frames(1)
    with RecordingWriter(
        template,
        {
            "source": "authored client fixture",
            "expected_frames": len(frames),
            "end_ms": frames[-1].time,
            "recording_end_reason": "native_game_end",
            "game_ended": None,
            "observed_worker_exit_code": 0,
            "observed_timeout": False,
        },
    ) as writer:
        for frame in frames:
            writer.write(frame)
    profile = tmp_path / "profile.json"
    write(profile, {"fixture_not_native": True})
    engine = {
        "protocol_version": 1,
        "capture_protocol": "v32-streams-1",
        "backend": "v32-sdk-1",
        "qualification": "experimental",
        "families": [
            {
                "build": 54800,
                "save_version": 4515430,
                "options_version": 1150050304,
                "dataset_id": 1,
                "game_mode": 0,
                "selected_content_mode": 2,
            }
        ],
        "capabilities": ["world_frames"],
        "profiles": {role: file_pin(profile) for role in ("source", "runtime", "encoder")},
    }
    identity = {
        **engine,
        "profiles": {
            role: {k: v for k, v in row.items() if k != "path"}
            for role, row in engine["profiles"].items()
        },
    }
    engine["engine_id"] = hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    registry = tmp_path / "registry.json"
    write(registry, {"kind": "vantage_native_engine_registry", "version": 1, "engines": [engine]})
    descriptor = tmp_path / "worker.json"
    write(
        descriptor,
        {
            "kind": "vantage_native_worker_client",
            "version": 1,
            "command": [
                sys.executable,
                "-B",
                str(script),
                "--fixture-template",
                str(template),
                "--fixture-mode",
                mode,
            ],
            "inputs": [file_pin(Path(sys.executable)), file_pin(script), file_pin(template)],
            "registry": file_pin(registry),
            "timeout_seconds": 10,
        },
    )
    replay = tmp_path / "fixture.aoe2record"
    replay.write_bytes(gzip.decompress((FIXTURES / "replay_3p_54800.aoe2record.gz").read_bytes()))
    return (
        NativeJobs(NativeWorker(descriptor, file_pin(descriptor)["sha256"]), tmp_path / "cache"),
        replay,
        descriptor,
    )


def wait(jobs: NativeJobs, job_id: str) -> dict:
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        value = jobs.get(job_id)
        if value["status"] in ("ready", "failed", "cancelled"):
            return value
        time.sleep(0.01)
    pytest.fail("Authored worker did not complete")


def test_ready_and_preview_are_distinct_and_resource_limited(tmp_path: Path) -> None:
    for mode, complete in [("good", True), ("eof", False)]:
        folder = tmp_path / mode
        folder.mkdir()
        jobs, replay, _ = setup_worker(folder, mode)
        try:
            value = wait(jobs, jobs.start(str(replay), experimental=True)["id"])
            assert value["status"] == "ready", value
            assert value["complete_match"] is complete
            assert jobs.ready_path(value["id"]).is_file()
            resource = json.loads((jobs.cache / "fixture-resource.json").read_text())
            assert len(resource["affinity"]) == 1 and resource["nice"] == 19
            assert value["experimental"] is True
        finally:
            jobs.close()


@pytest.mark.parametrize(
    "mode",
    [
        "failed",
        "wrong-protocol",
        "wrong-replay",
        "wrong-family",
        "no-report",
        "wrong-digest",
        "corrupt-recording",
        "ignored-checksum",
        "forced-status",
        "changed-worker",
    ],
)
def test_invalid_result_never_opens_recording(tmp_path: Path, mode: str) -> None:
    jobs, replay, _ = setup_worker(tmp_path, mode)
    try:
        value = wait(jobs, jobs.start(str(replay), experimental=True)["id"])
        assert value["status"] == "failed", value
        assert value["recording"] is None
        with pytest.raises(NativeError):
            jobs.ready_path(value["id"])
    finally:
        jobs.close()


def test_explicit_opt_in_and_unknown_build_reject_before_worker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from types import SimpleNamespace

    jobs, replay, _ = setup_worker(tmp_path)
    try:
        with pytest.raises(NativeError, match="opt-in"):
            jobs.start(str(replay))
        monkeypatch.setattr(
            "vantage.native.read_replay", lambda *a, **k: SimpleNamespace(build=99999)
        )
        with pytest.raises(NativeError, match="99999"):
            jobs.start(str(replay), experimental=True)
        assert not (jobs.cache / "client-jobs").exists()
        assert not (jobs.cache / "fixture-resource.json").exists()
    finally:
        jobs.close()


def test_cancel_and_single_worker(tmp_path: Path) -> None:
    jobs, replay, _ = setup_worker(tmp_path, "wait")
    try:
        job = jobs.start(str(replay), experimental=True)
        deadline = time.monotonic() + 3
        while not (jobs.cache / "fixture-resource.json").exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert (jobs.cache / "fixture-resource.json").exists()
        with pytest.raises(NativeError, match="already running"):
            jobs.start(str(replay), experimental=True)
        jobs.cancel(job["id"])
        value = wait(jobs, job["id"])
        assert value["status"] == "cancelled" and value["recording"] is None
    finally:
        jobs.close()


def test_cancel_during_ready_validation_cannot_lose_to_cache_result(tmp_path: Path) -> None:
    jobs, replay, _ = setup_worker(tmp_path)
    entered, release = threading.Event(), threading.Event()
    original = jobs._ready

    def ready(*args):
        value = original(*args)
        entered.set()
        release.wait(3)
        return value

    jobs._ready = ready
    try:
        job = jobs.start(str(replay), experimental=True)
        assert entered.wait(3)
        jobs.cancel(job["id"])
        release.set()
        value = wait(jobs, job["id"])
        assert value["status"] == "cancelled" and value["recording"] is None
    finally:
        release.set()
        jobs.close()


def test_pinned_input_change_rejected_before_worker_and_after_ready(tmp_path: Path) -> None:
    jobs, replay, _ = setup_worker(tmp_path)
    try:
        job = wait(jobs, jobs.start(str(replay), experimental=True)["id"])
        assert job["status"] == "ready", job
        jobs.ready_path(job["id"]).write_bytes(b"changed fixture output")
        with pytest.raises(NativeError, match="changed"):
            jobs.ready_path(job["id"])
        (tmp_path / "fixture-worker.py").write_text("# changed before start\n")
        with pytest.raises(NativeError, match="changed"):
            jobs.start(str(replay), experimental=True)
    finally:
        jobs.close()


def test_descriptor_and_engine_contract_must_match(tmp_path: Path) -> None:
    jobs, _replay, descriptor = setup_worker(tmp_path)
    jobs.close()
    with pytest.raises(NativeError, match="descriptor changed"):
        NativeWorker(descriptor, "0" * 64)
    registry = tmp_path / "registry.json"
    doc = json.loads(registry.read_text())
    doc["engines"][0]["families"][0]["build"] = 99999
    write(registry, doc)
    config = json.loads(descriptor.read_text())
    config["registry"] = file_pin(registry)
    write(descriptor, config)
    with pytest.raises(NativeError, match="contract identity"):
        NativeWorker(descriptor, file_pin(descriptor)["sha256"])


def test_command_script_cannot_be_omitted_from_pins(tmp_path: Path) -> None:
    jobs, _replay, descriptor = setup_worker(tmp_path)
    jobs.close()
    value = json.loads(descriptor.read_text())
    value["inputs"] = [
        row for row in value["inputs"] if not row["path"].endswith("fixture-worker.py")
    ]
    write(descriptor, value)
    with pytest.raises(NativeError, match="command file is not pinned"):
        NativeWorker(descriptor, file_pin(descriptor)["sha256"])
