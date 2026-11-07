"""The V32 command only marks a recording successful after all three phases."""

import json
from pathlib import Path

import pytest

from vantage import native_v32_pipeline as pipeline
from vantage.native_v32_encode import V32EncodeError


def test_pipeline_publishes_result_only_after_encoder_success(tmp_path: Path, monkeypatch, capsys):
    job = tmp_path / "job"
    calls = []

    def prepare(_replay, out, **_kwargs):
        calls.append("prepare")
        out.mkdir()
        (out / "stage.json").write_text("{}")
        return {"worker": {"sha256": "worker"}}

    class Runtime:
        def __init__(self, **_kwargs):
            pass

        def run(self, *_args, **_kwargs):
            calls.append("runtime")
            return {"capture": "raw"}

    class Encoder:
        def __init__(self, **_kwargs):
            pass

        def encode(self, _job, result, **_kwargs):
            assert result == {"capture": "raw"}
            calls.append("encode")
            return {"recording": {"path": "recording.vrec"}}

    monkeypatch.setattr(pipeline, "verify_profiles", lambda _args: None)
    monkeypatch.setattr(pipeline, "prepare_v32_worker", prepare)
    monkeypatch.setattr(pipeline, "V32Runtime", Runtime)
    monkeypatch.setattr(pipeline, "V32Encoder", Encoder)
    monkeypatch.setattr(
        pipeline.sys,
        "argv",
        [
            "v32",
            "--replay",
            str(tmp_path / "input"),
            "--job",
            str(job),
            "--source-profile",
            "a",
            "--source-profile-sha256",
            "a",
            "--runtime-profile",
            "b",
            "--runtime-profile-sha256",
            "b",
            "--encoder-config",
            "c",
            "--encoder-config-sha256",
            "c",
        ],
    )
    pipeline.main()
    assert calls == ["prepare", "runtime", "encode"]
    result = json.loads((job / "pipeline-result.json").read_text())
    assert result["status"] == "experimental_v32_recording_verified"
    assert (
        result["shipping_cache_published"] is False
        and result["general_game_parity_verified"] is False
    )
    assert "recording.vrec" in capsys.readouterr().out


def test_encoder_failure_does_not_publish_pipeline_result(tmp_path: Path, monkeypatch):
    job = tmp_path / "job"

    def prepare(_replay, out, **_kwargs):
        out.mkdir()
        (out / "stage.json").write_text("{}")
        return {"worker": {}}

    class Runtime:
        def __init__(self, **_kwargs):
            pass

        def run(self, *_args, **_kwargs):
            return {}

    class Encoder:
        def __init__(self, **_kwargs):
            pass

        def encode(self, *_args, **_kwargs):
            raise RuntimeError("rejected")

    monkeypatch.setattr(pipeline, "verify_profiles", lambda _args: None)
    monkeypatch.setattr(pipeline, "prepare_v32_worker", prepare)
    monkeypatch.setattr(pipeline, "V32Runtime", Runtime)
    monkeypatch.setattr(pipeline, "V32Encoder", Encoder)
    monkeypatch.setattr(
        pipeline.sys,
        "argv",
        [
            "v32",
            "--replay",
            str(tmp_path / "input"),
            "--job",
            str(job),
            "--source-profile",
            "a",
            "--source-profile-sha256",
            "a",
            "--runtime-profile",
            "b",
            "--runtime-profile-sha256",
            "b",
            "--encoder-config",
            "c",
            "--encoder-config-sha256",
            "c",
        ],
    )
    with pytest.raises(RuntimeError, match="rejected"):
        pipeline.main()
    assert not (job / "pipeline-result.json").exists()


@pytest.mark.parametrize("indexed", [False, True])
def test_serve_opens_recording_without_live_game(tmp_path: Path, monkeypatch, indexed):
    job = tmp_path / "job"
    calls = []

    def prepare(_replay, out, **_kwargs):
        out.mkdir()
        (out / "stage.json").write_text("{}")
        return {"worker": {}}

    class Runtime:
        def __init__(self, **_kwargs):
            pass

        def run(self, *_args, **_kwargs):
            return {}

    class Encoder:
        def __init__(self, **_kwargs):
            pass

        def encode(self, *_args, **_kwargs):
            return {"recording": {"path": "/private/recording.vrec"}}

    def fake_exec(_exe, command):
        calls.append(command)

    monkeypatch.setattr(pipeline, "verify_profiles", lambda _args: None)
    monkeypatch.setattr(pipeline, "prepare_v32_worker", prepare)
    monkeypatch.setattr(pipeline, "V32Runtime", Runtime)
    monkeypatch.setattr(pipeline, "V32Encoder", Encoder)
    monkeypatch.setattr(pipeline.os, "execv", fake_exec)
    monkeypatch.setattr(
        pipeline.sys,
        "argv",
        [
            "v32",
            "--replay",
            str(tmp_path / "input"),
            "--job",
            str(job),
            "--source-profile",
            "a",
            "--source-profile-sha256",
            "a",
            "--runtime-profile",
            "b",
            "--runtime-profile-sha256",
            "b",
            "--encoder-config",
            "c",
            "--encoder-config-sha256",
            "c",
            "--serve",
            "--port",
            "9123",
            "--game-dir",
            "/assets",
        ],
    )
    if indexed:
        pipeline.sys.argv.append("--indexed")
    pipeline.main()
    command = calls[0]
    if indexed:
        assert command[1:3] == ["-m", "vantage.native_v32_indexed_serve"]
        assert command[command.index("--index-root") + 1] == str(job / "playback-index-v2")
    else:
        assert command[1:4] == ["-m", "vantage", "serve"]
    assert command[command.index("--recording") + 1] == "/private/recording.vrec"
    assert command[command.index("--port") + 1] == "9123"
    assert "--live" not in command and "--native-replay" not in command and "--open" not in command


def test_indexed_requires_serve(monkeypatch, capsys):
    monkeypatch.setattr(
        pipeline.sys,
        "argv",
        [
            "v32",
            "--resume",
            "--job",
            "/job",
            "--source-profile",
            "a",
            "--source-profile-sha256",
            "a",
            "--runtime-profile",
            "b",
            "--runtime-profile-sha256",
            "b",
            "--encoder-config",
            "c",
            "--encoder-config-sha256",
            "c",
            "--indexed",
        ],
    )
    with pytest.raises(SystemExit):
        pipeline.main()
    assert "--indexed requires --serve" in capsys.readouterr().err


def test_resume_uses_checkpoint_without_preparing_or_running(tmp_path: Path, monkeypatch):
    job = tmp_path / "job"
    job.mkdir()
    profile = tmp_path / "source.json"
    profile.write_text("{}")
    (job / "stage.json").write_text(json.dumps({"profile": pipeline.pin(profile), "worker": {}}))
    (job / "simulation-result.json").write_text(json.dumps({"capture": "checkpoint"}))
    calls = []

    def forbidden(*_args, **_kwargs):
        raise AssertionError("resume must not prepare or run a worker")

    class Runtime:
        def __init__(self, **_kwargs):
            pass

        run = forbidden

    class Encoder:
        def __init__(self, **_kwargs):
            pass

        def encode(self, _job, result, **_kwargs):
            calls.append(result)
            return {"recording": {"path": "recording.vrec"}}

    monkeypatch.setattr(pipeline, "verify_profiles", lambda _args: None)
    monkeypatch.setattr(pipeline, "prepare_v32_worker", forbidden)
    monkeypatch.setattr(pipeline, "V32Runtime", Runtime)
    monkeypatch.setattr(pipeline, "V32Encoder", Encoder)
    monkeypatch.setattr(
        pipeline.sys,
        "argv",
        [
            "v32",
            "--resume",
            "--job",
            str(job),
            "--source-profile",
            str(profile),
            "--source-profile-sha256",
            pipeline.pin(profile)["sha256"],
            "--runtime-profile",
            "b",
            "--runtime-profile-sha256",
            "b",
            "--encoder-config",
            "c",
            "--encoder-config-sha256",
            "c",
        ],
    )
    pipeline.main()
    assert calls == [{"capture": "checkpoint"}]
    result = json.loads((job / "pipeline-result.json").read_text())
    assert result["resumed_capture"] is True


def test_encoder_profile_is_checked_before_any_worker_is_prepared(tmp_path: Path, monkeypatch):
    job = tmp_path / "job"
    source, runtime, config = (
        tmp_path / name for name in ("source.json", "runtime.json", "encoder.json")
    )
    source.write_text("{}")
    runtime.write_text(json.dumps({"staging_profile": pipeline.pin(source)}))
    config.write_text("{}")
    monkeypatch.setattr(
        pipeline.sys,
        "argv",
        [
            "v32",
            "--replay",
            str(tmp_path / "input"),
            "--job",
            str(job),
            "--source-profile",
            str(source),
            "--source-profile-sha256",
            pipeline.pin(source)["sha256"],
            "--runtime-profile",
            str(runtime),
            "--runtime-profile-sha256",
            pipeline.pin(runtime)["sha256"],
            "--encoder-config",
            str(config),
            "--encoder-config-sha256",
            "0" * 64,
        ],
    )
    with pytest.raises(V32EncodeError, match="Encoder configuration differs"):
        pipeline.main()
    assert not job.exists()


def test_resume_reuses_verified_recording_without_encoder(tmp_path: Path, monkeypatch, capsys):
    job = tmp_path / "job"
    job.mkdir()
    profile = tmp_path / "source.json"
    profile.write_text("{}")
    (job / "stage.json").write_text(json.dumps({"profile": pipeline.pin(profile), "worker": {}}))
    (job / "simulation-result.json").write_text(json.dumps({"capture": "checkpoint"}))
    (job / "pipeline-result.json").write_text(json.dumps({"prior": "result"}))

    def forbidden(*_args, **_kwargs):
        raise AssertionError("verified reuse must not prepare, run or encode")

    class Runtime:
        def __init__(self, **_kwargs):
            pass

        run = forbidden

    class Encoder:
        def __init__(self, **_kwargs):
            pass

        encode = forbidden

    def verify(_job, result, **_kwargs):
        assert result == {"prior": "result"}
        return {
            "recording": {"path": "existing.vrec"},
            "frames": 3,
            "end_ms": 31,
            "general_game_parity_verified": False,
        }

    monkeypatch.setattr(pipeline, "verify_profiles", lambda _args: None)
    monkeypatch.setattr(pipeline, "prepare_v32_worker", forbidden)
    monkeypatch.setattr(pipeline, "V32Runtime", Runtime)
    monkeypatch.setattr(pipeline, "V32Encoder", Encoder)
    monkeypatch.setattr(pipeline, "verified_recording", verify)
    monkeypatch.setattr(
        pipeline.sys,
        "argv",
        [
            "v32",
            "--resume",
            "--job",
            str(job),
            "--source-profile",
            str(profile),
            "--source-profile-sha256",
            pipeline.pin(profile)["sha256"],
            "--runtime-profile",
            "b",
            "--runtime-profile-sha256",
            "b",
            "--encoder-config",
            "c",
            "--encoder-config-sha256",
            "c",
        ],
    )
    pipeline.main()
    assert json.loads(capsys.readouterr().out)["status"] == "experimental_v32_recording_reused"
    assert json.loads((job / "pipeline-result.json").read_text()) == {"prior": "result"}


def test_progress_reads_only_complete_update_clock_from_owned_log(tmp_path: Path, capsys):
    source = tmp_path / "source"
    source.mkdir()
    (source / "descriptor.json").write_text(json.dumps({"final_clock_ms": 120000}))
    run = tmp_path / "runs" / "owned"
    run.mkdir(parents=True)
    (run / "native.stdout.log").write_text(
        '{"stage":"native_world_update_returned","ordinal":1,"world_time_ms":61000}\n'
        '{"stage":"native_entity_frame","time_ms":61000}\n'
        '{"stage":"native_world_update_returned","ordinal":2,"world_time_ms":99000'
    )

    class Stop:
        calls = 0

        def wait(self, _seconds):
            self.calls += 1
            return self.calls > 1

    pipeline._report_simulation_progress(tmp_path, Stop())
    assert "Simulated 1:01 of 2:00" in capsys.readouterr().err


def test_checksum_failure_requires_the_native_stop_and_failure_events(tmp_path: Path):
    run = tmp_path / "runs" / "owned"
    run.mkdir(parents=True)
    log = run / "native.stdout.log"
    stop = {
        "stage": "native_sync_stopped",
        "status": 3,
        "world_time_ms": 1310937,
        "ignore_checksum_global": 0,
    }
    failure = {"ok": False, "stage": "native_prefix_sync", "error": 207}
    log.write_text(json.dumps(stop) + "\n" + json.dumps(failure) + "\n")
    assert pipeline._checksum_stop(tmp_path) == stop
    log.write_text(json.dumps(stop) + "\n")
    assert pipeline._checksum_stop(tmp_path) is None
    stop["ignore_checksum_global"] = 1
    log.write_text(json.dumps(stop) + "\n" + json.dumps(failure) + "\n")
    assert pipeline._checksum_stop(tmp_path) is None


def test_checksum_failure_reports_the_exact_clock_for_preview(tmp_path, monkeypatch, capsys):
    job = tmp_path / "job"

    def prepare(_replay, output, **_kwargs):
        output.mkdir()
        (output / "stage.json").write_text("{}")
        return {"worker": {}}

    class Runtime:
        def __init__(self, **_kwargs):
            pass

        def run(self, *_args, **_kwargs):
            raise pipeline.V32RuntimeError("checksum stopped")

    monkeypatch.setattr(pipeline, "verify_profiles", lambda _args: None)
    monkeypatch.setattr(pipeline, "prepare_v32_worker", prepare)
    monkeypatch.setattr(pipeline, "V32Runtime", Runtime)
    monkeypatch.setattr(pipeline, "_checksum_stop", lambda _job: {"world_time_ms": 1310937})
    monkeypatch.setattr(
        pipeline.sys,
        "argv",
        [
            "v32",
            "--replay",
            str(tmp_path / "input"),
            "--job",
            str(job),
            "--source-profile",
            "a",
            "--source-profile-sha256",
            "a",
            "--runtime-profile",
            "b",
            "--runtime-profile-sha256",
            "b",
            "--encoder-config",
            "c",
            "--encoder-config-sha256",
            "c",
        ],
    )
    with pytest.raises(pipeline.V32RuntimeError, match="checksum stopped"):
        pipeline.main()
    assert "21:50 (1310937 ms)" in capsys.readouterr().err
    assert not (job / "pipeline-result.json").exists()


def test_preview_rerun_argv_swaps_replay_and_job_and_drops_the_fallback_flag() -> None:
    from pathlib import Path

    from vantage.native_v32_pipeline import preview_rerun_argv

    argv = [
        "--replay",
        "/r/match.aoe2record",
        "--job=/j/one",
        "--preview-on-checksum-failure",
        "--runtime-timeout",
        "100",
        "--job",
        "/j/one",
    ]
    preview = Path("/p/INCOMPLETE.aoe2record")
    out = preview_rerun_argv(argv, replay=preview, job=Path("/j/one-preview"))
    assert out == [
        "--runtime-timeout",
        "100",
        "--replay",
        "/p/INCOMPLETE.aoe2record",
        "--job",
        "/j/one-preview",
    ]
    assert "--preview-on-checksum-failure" not in out
