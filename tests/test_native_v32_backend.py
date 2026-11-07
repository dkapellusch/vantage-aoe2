"""V32 Session bridge tests use fake stages, never a game or native worker."""

import json
import os
import signal
import subprocess
import sys
import threading
import time
from dataclasses import replace
from types import SimpleNamespace

import pytest

from vantage import native_v32_backend as backend
from vantage import native_v32_serve
from vantage.native_conversion import ConversionCancelled, ConversionError, pin
from vantage.native_v32_config import V32Config


@pytest.fixture
def setup(tmp_path, monkeypatch):
    profiles = []
    for name in ("source", "runtime", "encoder"):
        path = tmp_path / name
        path.write_text(name)
        profiles.append(path)
    config = V32Config(
        profiles[0],
        pin(profiles[0])["sha256"],
        tmp_path / "cache",
        (tmp_path,),
        profiles[1],
        pin(profiles[1])["sha256"],
        profiles[2],
        pin(profiles[2])["sha256"],
    )
    replay = tmp_path / "test.aoe2record"
    replay.write_bytes(b"replay")
    calls = []
    monkeypatch.setattr(
        backend.V32Conversion, "_profiles", lambda self, job: [pin(p) for p in profiles]
    )

    def stage(self, recording, job):
        calls.append("stage")
        job.mkdir(parents=True)
        (job / "stage.json").write_text(
            json.dumps(
                {
                    "recording": pin(recording),
                    "profile": pin(profiles[0]),
                    "worker": {"sha256": "worker"},
                }
            )
        )

    class Runtime:
        def __init__(self, **kwargs):
            pass

        def run(self, job, **kwargs):
            calls.append("runtime")
            return {"capture": "raw"}

        def cancel(self):
            calls.append("runtime-cancel")

    class Encoder:
        def __init__(self, **kwargs):
            pass

        def encode(self, job, run, **kwargs):
            calls.append("encode")
            out = job / "encodes" / "fake" / "encoded"
            out.mkdir(parents=True)
            (out / "recording.vrec").write_bytes(b"frame")
            (out / "conversion.json").write_text(
                json.dumps(
                    {
                        "status": "conversion_verified",
                        "capture_frames": 1,
                        "capture_end_ms": 1,
                        "game_ended": False,
                        "recording_end_reason": "recording_eof",
                        "recording": pin(out / "recording.vrec"),
                    }
                )
            )
            return {
                "recording": pin(out / "recording.vrec"),
                "conversion": pin(out / "conversion.json"),
            }

        def cancel(self):
            calls.append("encoder-cancel")

    def verify(job, result, **kwargs):
        calls.append("verify")
        return {
            "recording": result["recording"],
            "frames": 1,
            "end_ms": 1,
            "recording_end_reason": "recording_eof",
        }

    monkeypatch.setattr(backend.V32Conversion, "_stage", stage)
    monkeypatch.setattr(backend, "V32Runtime", Runtime)
    monkeypatch.setattr(backend, "V32Encoder", Encoder)
    monkeypatch.setattr(backend, "verified_recording", verify)
    return config, replay, calls


def test_verified_output_is_committed_and_reused(setup):
    config, replay, calls = setup
    result = backend.V32Conversion(config).convert(replay)
    assert result.read_bytes() == b"frame"
    marker = json.loads((result.parent / "success.json").read_text())
    assert marker["status"] == "ready" and marker["identity"]["backend"] == "v32-sdk-1"
    assert calls == ["stage", "runtime", "encode", "verify"]
    again = backend.V32Conversion(config).convert(replay)
    assert again == result and calls == ["stage", "runtime", "encode", "verify", "verify"]


def test_retained_job_revalidates_and_binds_replay_without_running_worker(setup, tmp_path):
    config, replay, calls = setup
    old = tmp_path / "old-job"
    old.mkdir()
    recording = old / "recording.vrec"
    recording.write_bytes(b"old frames")
    conversion = old / "conversion.json"
    conversion.write_text(
        json.dumps(
            {
                "capture_frames": 1,
                "capture_end_ms": 1,
                "game_ended": False,
                "recording_end_reason": "recording_eof",
            }
        )
    )
    (old / "stage.json").write_text(
        json.dumps({"recording": pin(replay), "profile": pin(config.profile)})
    )
    (old / "pipeline-result.json").write_text(
        json.dumps({"recording": pin(recording), "encoding": {"conversion": pin(conversion)}})
    )
    config = replace(config, reuse_job=old)
    result = backend.V32Conversion(config).convert(replay)
    assert result.read_bytes() == b"old frames" and calls == ["verify"]
    assert backend.V32Conversion(config).convert(replay) == result and calls == ["verify", "verify"]
    replay.write_bytes(b"different replay")
    with pytest.raises(ConversionError, match="does not match"):
        backend.V32Conversion(config).convert(replay)
    assert calls == ["verify", "verify"]


def test_opt_in_entrypoint_configures_session_before_queueing(setup, tmp_path, monkeypatch):
    config, replay, _ = setup
    events = []

    class Session:
        def __init__(self, *_args):
            pass

        def configure_native(self, selected, *, loader):
            assert isinstance(selected, V32Config)
            assert loader.func is native_v32_serve.load_with_recorded_chat
            assert loader.keywords == {"chat_cache_root": selected.cache_dir / "recorded-chat-v1"}
            events.append("configure")

        def open_native_replay(self, selected):
            assert selected == replay
            events.append("queue")

        def close_native(self):
            events.append("close")

        def stop(self):
            events.append("stop")

    monkeypatch.setattr(native_v32_serve, "GameData", lambda *_args: object())
    monkeypatch.setattr(native_v32_serve, "find_game_dir", lambda: None)
    monkeypatch.setattr(native_v32_serve, "NativeSession", Session)

    def serve(*_args, **_kwargs):
        events.append("bind")
        return SimpleNamespace(
            serve_forever=lambda: events.append("serve"),
            server_close=lambda: events.append("server-close"),
        )

    monkeypatch.setattr(native_v32_serve, "serve", serve)
    native_v32_serve.main(
        [
            "--replay",
            str(replay),
            "--source-profile",
            str(config.profile),
            "--source-profile-sha256",
            config.profile_sha256,
            "--runtime-profile",
            str(config.runtime_profile),
            "--runtime-profile-sha256",
            config.runtime_profile_sha256,
            "--encoder-config",
            str(config.encoder_config),
            "--encoder-config-sha256",
            config.encoder_config_sha256,
            "--cache-dir",
            str(config.cache_dir),
            "--recordings-dir",
            str(tmp_path / "recordings"),
        ]
    )
    assert events == ["configure", "bind", "queue", "serve", "close", "stop", "server-close"]


@pytest.mark.parametrize("phase", ["runtime", "encode", "verify"])
def test_failure_does_not_commit(setup, monkeypatch, phase):
    config, replay, _calls = setup

    def fail(*args, **kwargs):
        raise ValueError("gate refused")

    if phase == "runtime":
        monkeypatch.setattr(backend.V32Runtime, "run", fail)
    elif phase == "encode":
        monkeypatch.setattr(backend.V32Encoder, "encode", fail)
    else:
        monkeypatch.setattr(backend, "verified_recording", fail)
    with pytest.raises(ConversionError, match="gate refused"):
        backend.V32Conversion(config).convert(replay)
    assert not list((config.cache_dir / "v32-entries").glob("*/success.json"))


def test_original_checksum_stop_surfaces_without_publishing(setup, monkeypatch):
    config, replay, calls = setup

    def fail(*_args, **_kwargs):
        raise ValueError("native rejected")

    monkeypatch.setattr(backend.V32Runtime, "run", fail)
    monkeypatch.setattr(backend, "_checksum_stop", lambda _job: {"world_time_ms": 1869961})
    with pytest.raises(ConversionError, match="checksum mismatch at 1869961 ms"):
        backend.V32Conversion(config).convert(replay)
    assert "encode" not in calls
    assert not list((config.cache_dir / "v32-entries").glob("*/success.json"))


@pytest.mark.parametrize("phase", ["runtime", "encode"])
def test_cancellation_signals_active_component_and_does_not_publish(setup, monkeypatch, phase):
    config, replay, calls = setup
    entered, release = threading.Event(), threading.Event()
    cls = backend.V32Runtime if phase == "runtime" else backend.V32Encoder

    def blocked(self, *args, **kwargs):
        entered.set()
        assert release.wait(5)
        raise ValueError("stopped")

    def cancel(self):
        calls.append(phase + "-cancel")
        release.set()

    monkeypatch.setattr(cls, "run" if phase == "runtime" else "encode", blocked)
    monkeypatch.setattr(cls, "cancel", cancel)
    converter = backend.V32Conversion(config)
    errors = []

    def work():
        try:
            converter.convert(replay)
        except Exception as exc:
            errors.append(exc)

    thread = threading.Thread(target=work)
    thread.start()
    assert entered.wait(5)
    converter.cancel()
    thread.join(5)
    assert not thread.is_alive() and len(errors) == 1 and isinstance(errors[0], ConversionCancelled)
    assert phase + "-cancel" in calls
    assert not list((config.cache_dir / "v32-entries").glob("*/success.json"))


def test_cancel_during_copy_prevents_cache_commit(setup, monkeypatch):
    config, replay, _ = setup
    converter = backend.V32Conversion(config)
    real_copy = backend.shutil.copyfile

    def copy_then_cancel(src, dst):
        result = real_copy(src, dst)
        converter.cancel()
        return result

    monkeypatch.setattr(backend.shutil, "copyfile", copy_then_cancel)
    with pytest.raises(ConversionCancelled):
        converter.convert(replay)
    assert not list((config.cache_dir / "v32-entries").glob("*/success.json"))
    assert not list((config.cache_dir / "v32-entries").glob("*.pending"))


def test_terminal_report_cannot_claim_eof_is_game_end(setup, monkeypatch):
    config, replay, _ = setup
    original = backend.verified_recording

    def inconsistent(*args, **kwargs):
        result = original(*args, **kwargs)
        result["recording_end_reason"] = "native_game_end"
        return result

    monkeypatch.setattr(backend, "verified_recording", inconsistent)
    with pytest.raises(ConversionError, match="ending or frame extent"):
        backend.V32Conversion(config).convert(replay)
    assert not list((config.cache_dir / "v32-entries").glob("*/success.json"))


def test_stage_wrapper_terminates_separate_compiler_group_and_reaps(tmp_path):
    ready, reaped = tmp_path / "ready", tmp_path / "reaped"
    script = """
import json, os, signal, subprocess, sys
from vantage import native_v32_stage_entry as entry
ready, reaped = sys.argv[1:]
def fake_main():
    child = subprocess.Popen([sys.executable, '-c',
        'import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(60)'],
        start_new_session=True)
    open(ready, 'w').write(str(child.pid))
    try:
        child.wait()
    except BaseException:
        if child.poll() is None:
            os.killpg(child.pid, signal.SIGKILL)
            child.wait()
        open(reaped, 'w').write(str(child.returncode))
        raise
entry.native_v32_prepare.main = fake_main
entry.main()
"""
    process = subprocess.Popen(
        [sys.executable, "-c", script, str(ready), str(reaped)],
        start_new_session=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        deadline = time.monotonic() + 10
        while not ready.exists() and process.poll() is None and time.monotonic() < deadline:
            time.sleep(0.02)
        assert ready.exists()
        compiler_pid = int(ready.read_text())
        assert os.getpgid(compiler_pid) == compiler_pid and os.getpgid(process.pid) != compiler_pid
        os.killpg(process.pid, signal.SIGTERM)
        os.killpg(process.pid, signal.SIGTERM)
        _, err = process.communicate(timeout=10)
        assert process.returncode == 130, err.decode()
        assert reaped.exists() and int(reaped.read_text()) < 0
        with pytest.raises(ProcessLookupError):
            os.kill(compiler_pid, 0)
    finally:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()


@pytest.mark.parametrize("during_spawn", [False, True])
def test_stage_wrapper_escalates_and_reaps_even_at_registration_race(tmp_path, during_spawn):
    ready, compiler_ready = tmp_path / "ready", tmp_path / "compiler-ready"
    script = r"""
import os, signal, subprocess, sys, time
from vantage import native_v32_stage_entry as entry
ready, compiler_ready, race = sys.argv[1:]
original = subprocess.Popen
def slow_spawn(*args, **kwargs):
    child = original(*args, **kwargs)
    while not os.path.exists(compiler_ready):
        time.sleep(.01)
    if race == '1':
        open(ready, 'w').write(str(child.pid))
        time.sleep(.4)
    return child
subprocess.Popen = slow_spawn
def fake_main():
    child = subprocess.Popen([sys.executable, '-c',
        "import signal,sys,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); "
        "open(sys.argv[1],'w').write('ready'); time.sleep(60)",
        compiler_ready], start_new_session=True)
    if race == '0':
        open(ready, 'w').write(str(child.pid))
    child.wait()
entry.native_v32_prepare.main = fake_main
entry.main()
"""
    process = subprocess.Popen(
        [
            sys.executable,
            "-c",
            script,
            str(ready),
            str(compiler_ready),
            "1" if during_spawn else "0",
        ],
        start_new_session=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        deadline = time.monotonic() + 10
        while not ready.exists() and process.poll() is None and time.monotonic() < deadline:
            time.sleep(0.02)
        assert ready.exists()
        compiler_pid = int(ready.read_text())
        assert os.getpgid(compiler_pid) == compiler_pid
        os.killpg(process.pid, signal.SIGTERM)
        _, err = process.communicate(timeout=10)
        assert process.returncode == 130, err.decode()
        with pytest.raises(ProcessLookupError):
            os.kill(compiler_pid, 0)
    finally:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()
