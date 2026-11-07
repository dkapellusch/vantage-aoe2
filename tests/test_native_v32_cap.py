"""Focused tests against the isolated candidate package; no worker execution."""

import importlib.util
import json
import os
import signal
import struct
import subprocess
import sys
import time
from dataclasses import replace
from pathlib import Path

import pytest
from replay_fixtures import complete_world_case
from test_native_input import _replay

from vantage import native_v32_backend as backend
from vantage import native_v32_cap_stage_entry as cap_stage
from vantage import native_v32_input
from vantage.native_conversion import ConversionError
from vantage.native_input import NativeInputError

pytest_plugins = ["test_native_v32_backend"]


def test_real_synthetic_long_input_requires_and_accepts_explicit_cap(tmp_path):
    raw, _ = complete_world_case("3p")
    count = 262143
    body = struct.pack("<II", 2, 0) + struct.pack("<II", 2, 1) * (count - 1)
    body += struct.pack("<II", 6, count - 1)
    replay = _replay(tmp_path, raw, body=body)
    template = tmp_path / "template.h"
    template.write_text(
        'static constexpr const char* PREPARED_SAVED_SHA256 = "' + "0" * 64 + '";\n'
    )
    with pytest.raises(NativeInputError) as error:
        native_v32_input.prepare_v32_input(replay, tmp_path / "default", config_template=template)
    assert error.value.code == "INVALID_UPDATE_CAP" and not (tmp_path / "default").exists()
    descriptor = cap_stage.describe_native_input(replay)
    auto = cap_stage.automatic_cap(dict(descriptor.operation_counts)["sync"])
    assert auto == count + 2
    native_v32_input.prepare_v32_input(
        replay, tmp_path / "large", config_template=template, update_cap=auto
    )
    generated = (tmp_path / "large/native_input_profile.h").read_text()
    assert f"#define INPUT_UPDATE_CAP {count + 2}\n" in generated
    descriptor = json.loads((tmp_path / "large/descriptor.json").read_text())
    assert dict(descriptor["operation_counts"])["sync"] == count


def test_automatic_floor_and_positive_first_overflow():
    assert cap_stage.automatic_cap(3) == 262144
    assert cap_stage.automatic_cap(262142) == 262144
    assert cap_stage.automatic_cap(262143) == 262145
    assert cap_stage.automatic_cap(0xFFFFFFFC) == 0xFFFFFFFE
    for value in (0, 2, True, -1, 0xFFFFFFFD):
        with pytest.raises(ValueError):
            cap_stage.automatic_cap(value)


def test_positive_first_projection_guard_uses_dword_limit(tmp_path):
    raw, _ = complete_world_case("3p")
    replay = _replay(tmp_path, raw, body=struct.pack("<10I", 2, 13, 2, 27, 2, 13, 2, 7, 6, 60))
    template = tmp_path / "template.h"
    template.write_text(
        'static constexpr const char* PREPARED_SAVED_SHA256 = "' + "0" * 64 + '";\n'
    )
    with pytest.raises(NativeInputError) as error:
        native_v32_input.prepare_v32_input(
            replay, tmp_path / "overflow", config_template=template, update_cap=0xFFFFFFFF
        )
    assert error.value.code == "INVALID_UPDATE_CAP"
    native_v32_input.prepare_v32_input(
        replay, tmp_path / "safe", config_template=template, update_cap=0xFFFFFFFE
    )
    header = (tmp_path / "safe/native_input_profile.h").read_text()
    assert "#define INPUT_FIRST_SYNC_DELTA 13\n" in header
    assert "#define INPUT_UPDATE_CAP 4294967294\n" in header


def test_owned_stager_auto_and_manual_forwarding(monkeypatch, tmp_path):
    import sys
    from types import SimpleNamespace

    calls = []
    replay = tmp_path / "replay.aoe2record"
    monkeypatch.setattr(
        cap_stage,
        "describe_native_input",
        lambda path: SimpleNamespace(operation_counts=(("sync", 262143),)),
    )
    monkeypatch.setattr(cap_stage.native_v32_stage_entry, "main", lambda: calls.append(sys.argv[:]))
    monkeypatch.setattr(sys, "argv", ["owned", "--replay", str(replay)])
    cap_stage.main()
    assert calls[-1][-2:] == ["--update-cap", "262145"]
    monkeypatch.setattr(sys, "argv", ["owned", "--replay", str(replay), "--update-cap", "300000"])
    monkeypatch.setattr(
        cap_stage, "describe_native_input", lambda path: pytest.fail("manual parsed")
    )
    cap_stage.main()
    assert calls[-1][-2:] == ["--update-cap", "300000"]


def test_config_rejects_invalid_caps(setup):
    config, _, _ = setup
    for value in (-1, 0, 4, 0xFFFFFFFF, True, 1.5):
        with pytest.raises(ValueError, match="update cap"):
            replace(config, update_cap=value)
    assert replace(config, update_cap=5).update_cap == 5
    assert replace(config, update_cap=0xFFFFFFFE).update_cap == 0xFFFFFFFE


def test_stage_forwards_cap_to_owned_stager(setup, monkeypatch, tmp_path):
    config, replay, _ = setup
    observed = []

    class Child:
        returncode = 0

        def poll(self):
            return 0

    def spawn(argv, **kwargs):
        observed.append((argv, kwargs))
        return Child()

    monkeypatch.undo()  # restore the real _stage patched by the shared fixture
    monkeypatch.setattr(backend.subprocess, "Popen", spawn)
    backend.V32Conversion(replace(config, update_cap=300000))._stage(replay, tmp_path / "job")
    argv, kwargs = observed[0]
    assert argv[argv.index("--update-cap") + 1] == "300000"
    assert kwargs["start_new_session"] is True
    backend.V32Conversion(config)._stage(replay, tmp_path / "other-job")
    argv, kwargs = observed[-1]
    assert "vantage.native_v32_cap_stage_entry" in argv and "--update-cap" not in argv
    assert kwargs["start_new_session"] is True


def test_serve_parser_accepts_cap():
    from vantage.native_v32_serve import build_parser

    args = build_parser().parse_args(
        [
            "--source-profile",
            "a",
            "--source-profile-sha256",
            "x",
            "--runtime-profile",
            "b",
            "--runtime-profile-sha256",
            "x",
            "--encoder-config",
            "c",
            "--encoder-config-sha256",
            "x",
            "--cache-dir",
            "d",
            "--update-cap",
            "300000",
            "--runtime-timeout",
            "5000",
        ]
    )
    assert args.update_cap == 300000 and args.runtime_timeout == 5000


def test_shortcut_forwards_optional_cap_and_runtime_timeout(monkeypatch, tmp_path):
    entry_path = Path(__file__).resolve().parents[1] / "vantage-v32.py"
    spec = importlib.util.spec_from_file_location("staged_vantage_v32", entry_path)
    entry = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(entry)
    replay = tmp_path / "x.aoe2record"
    replay.write_bytes(b"fixture")
    argv = []

    class Intercept(Exception):
        pass

    def fake_exec(_exe, args, _env):
        argv.extend(args)
        raise Intercept

    monkeypatch.setattr(entry.os, "execve", fake_exec)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(entry_path),
            str(replay),
            "--update-cap",
            "300000",
            "--runtime-timeout",
            "5000",
            "--fast-encoder",
        ],
    )
    with pytest.raises(Intercept):
        entry.main()
    assert argv[argv.index("--update-cap") + 1] == "300000"
    assert argv[argv.index("--runtime-timeout") + 1] == "5000.0"
    assert argv[argv.index("--encoder-config-sha256") + 1] == entry.FAST_ENCODER_SHA


def test_cap_separates_new_cache_and_retained_job_cache(setup):
    config, replay, calls = setup
    first = backend.V32Conversion(config).convert(replay)
    second = backend.V32Conversion(replace(config, update_cap=262145)).convert(replay)
    assert first != second and first.read_bytes() == second.read_bytes()
    marker = json.loads((second.parent / "success.json").read_text())
    assert marker["identity"]["requested_update_cap"] == 262145
    assert calls.count("stage") == calls.count("runtime") == calls.count("encode") == 2
    saved_job = Path(marker["job"])
    retained = replace(config, reuse_job=saved_job, update_cap=300000)
    reused = backend.V32Conversion(retained).convert(replay)
    assert reused.read_bytes() == first.read_bytes()
    assert calls.count("stage") == calls.count("runtime") == calls.count("encode") == 2
    assert (
        json.loads((reused.parent / "success.json").read_text())["identity"]["requested_update_cap"]
        == 300000
    )


def test_changed_replay_after_prepass_cannot_start_runtime(setup, monkeypatch):
    config, replay, calls = setup
    fake_stage = backend.V32Conversion._stage

    def changed(self, path, job):
        # Model a change after auto-counting but before prepare pins the input.
        path.write_bytes(b"changed replay")
        fake_stage(self, path, job)

    monkeypatch.setattr(backend.V32Conversion, "_stage", changed)
    with pytest.raises(ConversionError, match="staged input or source profile differs"):
        backend.V32Conversion(config).convert(replay)
    assert "runtime" not in calls and "encode" not in calls
    assert not list((config.cache_dir / "v32-entries").glob("*/success.json"))


def test_cancellation_during_prepass_stops_owned_process(tmp_path):
    ready = tmp_path / "prepass-ready"
    script = """
import sys,time
from vantage import native_v32_cap_stage_entry as entry
ready = sys.argv[1]
def describe(path):
    open(ready, 'w').write('ready')
    time.sleep(60)
    raise AssertionError('cancel should stop prepass')
entry.describe_native_input = describe
sys.argv = ['stager', '--replay', 'unused.aoe2record']
entry.main()
"""
    child = subprocess.Popen(
        [sys.executable, "-c", script, str(ready)],
        start_new_session=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        deadline = time.monotonic() + 10
        while not ready.exists() and child.poll() is None and time.monotonic() < deadline:
            time.sleep(0.02)
        assert ready.exists()
        os.killpg(child.pid, signal.SIGTERM)
        _, err = child.communicate(timeout=10)
        assert child.returncode == -signal.SIGTERM, err.decode()
    finally:
        if child.poll() is None:
            os.killpg(child.pid, signal.SIGKILL)
            child.wait()


def test_cancellation_after_prepass_reaps_separate_compiler_group(tmp_path):
    ready, compiler_ready = tmp_path / "compiler-pid", tmp_path / "compiler-ready"
    script = """
import os,subprocess,sys,time
from types import SimpleNamespace
from vantage import native_v32_cap_stage_entry as entry
ready, compiler_ready = sys.argv[1:]
entry.describe_native_input = lambda path: SimpleNamespace(operation_counts=(('sync', 4),))
def fake_prepare():
    child = subprocess.Popen([sys.executable, '-c',
        "import signal,sys,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); "
        "open(sys.argv[1],'w').write('ready'); time.sleep(60)", compiler_ready],
        start_new_session=True)
    while not os.path.exists(compiler_ready): time.sleep(.01)
    open(ready, 'w').write(str(child.pid))
    child.wait()
entry.native_v32_stage_entry.native_v32_prepare.main = fake_prepare
sys.argv = ['stager', '--replay', 'unused.aoe2record']
entry.main()
"""
    child = subprocess.Popen(
        [sys.executable, "-c", script, str(ready), str(compiler_ready)],
        start_new_session=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        deadline = time.monotonic() + 10
        while not ready.exists() and child.poll() is None and time.monotonic() < deadline:
            time.sleep(0.02)
        assert ready.exists()
        compiler = int(ready.read_text())
        assert os.getpgid(compiler) == compiler and os.getpgid(child.pid) != compiler
        os.killpg(child.pid, signal.SIGTERM)
        _, err = child.communicate(timeout=10)
        assert child.returncode == 130, err.decode()
        with pytest.raises(ProcessLookupError):
            os.kill(compiler, 0)
    finally:
        if child.poll() is None:
            os.killpg(child.pid, signal.SIGKILL)
            child.wait()


def test_cap_exhaustion_cannot_be_treated_as_terminal(tmp_path):
    report = tmp_path / "conversion.json"
    report.write_text(
        json.dumps(
            {
                "recording_end_reason": "cap_exhausted",
                "game_ended": False,
                "capture_frames": 1,
                "capture_end_ms": 1,
            }
        )
    )
    with pytest.raises(ConversionError):
        backend.V32Conversion._check_report(
            report, {"recording_end_reason": "cap_exhausted", "frames": 1, "end_ms": 1}
        )
