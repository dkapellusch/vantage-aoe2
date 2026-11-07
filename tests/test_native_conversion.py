"""No target executable, compiler, Wine, encoder or historical capture is run here."""

import json
import signal
import subprocess
import threading
from pathlib import Path

import pytest

from vantage import native_conversion as N


def capture_events(*, ended=False):
    events = []
    for ordinal, clock in enumerate((0, 20, 31), 1):
        events.append(
            dict(
                stage="native_world_update_returned",
                ordinal=ordinal,
                world_time_ms=clock,
                status=int(ended and ordinal == 3),
            )
        )
        for stage in (
            "native_entity_frame",
            "native_player_frame",
            "native_world_frame",
            "native_entity_presentation_frame",
        ):
            events.append(dict(stage=stage, time_ms=clock))
    events += [
        dict(
            stage="owned_recording_postgame_close",
            marker=6,
            position=100,
            file_bytes=108,
            unread_tail_bytes=8,
            source_final_clock=31,
            native_log_ms=31,
            native_file_fields_changed=False,
        ),
        dict(
            stage="native_original_terminal_status_admitted"
            if ended
            else "native_recording_eof_admitted",
            returned_status=int(ended),
            world_status=int(ended),
            game_ended=ended,
            recording_completed=True,
            world_time_ms=31,
            completed_updates=3,
            native_replay_closed=True,
            checksum_ignore_global=0,
            host_native_status_write=False,
        ),
        dict(
            stage="native_replay_terminal_state",
            world_time_ms=31,
            native_log_ms=31,
            world_status=int(ended),
            original_terminal_status_observed=ended,
            recording_eof_observed=not ended,
            recording_end_reason="world_terminal" if ended else "recording_eof",
            replay_active=0,
            replay_file_present=False,
            owned_recording_closed=True,
            file_cursor=100,
            checksum_ignore_global=0,
        ),
        dict(
            stage="native_simulation_prefix_complete",
            completed_world_updates=3,
            world_time_ms=31,
            projected_frames=3,
            audio_requests=0,
            native_audio_initialized=False,
        ),
        dict(ok=True),
    ]
    return events


def synthetic_capture(tmp_path, *, events=None, receipt_changes=None):
    capture = tmp_path / "capture.jsonl"
    capture.write_text(
        "\n".join(json.dumps(row) for row in (capture_events() if events is None else events))
        + "\n"
    )
    receipt = dict(
        receipt_kind="ordinary_owned_subprocess",
        exit_code=0,
        timed_out=False,
        cancelled=False,
        all_input_pins_unchanged=True,
        stdout_sha256=N.pin(capture)["sha256"],
    )
    receipt.update(receipt_changes or {})
    receipt_path = tmp_path / "receipt.json"
    receipt_path.write_text(json.dumps(receipt))
    descriptor = dict(
        final_clock_ms=31, postgame_marker_end=100, recording_bytes=108, postgame_remaining_bytes=8
    )
    return capture, receipt_path, descriptor


@pytest.mark.parametrize("ended", [False, True])
def test_eof_and_game_end_are_distinct_success_outcomes(tmp_path, ended):
    args = synthetic_capture(tmp_path, events=capture_events(ended=ended))
    result = N.terminal_evidence(*args)
    assert result["expected_frames"] == 3
    assert result["game_ended"] is ended
    assert result["recording_end_reason"] == ("native_game_end" if ended else "recording_eof")
    assert result["game_end_inferred_from_EOF"] is False


@pytest.mark.parametrize(
    "changes",
    [
        {"receipt_kind": "recovered_outer_runner"},
        {"exit_code": 1},
        {"exit_code": False},
        {"timed_out": True},
        {"cancelled": True},
        {"all_input_pins_unchanged": False},
        {"stdout_sha256": "0" * 64},
    ],
)
def test_receipt_must_be_ordinary_observed_and_input_bound(tmp_path, changes):
    args = synthetic_capture(tmp_path, receipt_changes=changes)
    with pytest.raises(N.ConversionError, match="receipt rejected"):
        N.terminal_evidence(*args)


@pytest.mark.parametrize(
    "problem", ["cadence", "duplicate", "cursor", "world", "ignore", "failure"]
)
def test_no_acceptance_from_completion_line_alone(tmp_path, problem):
    events = capture_events()
    if problem == "cadence":
        next(e for e in events if e.get("stage") == "native_player_frame")["time_ms"] = 1
    elif problem == "duplicate":
        events.append(next(e for e in events if e.get("stage") == "native_recording_eof_admitted"))
    elif problem == "cursor":
        next(e for e in events if e.get("stage") == "owned_recording_postgame_close")[
            "position"
        ] = 99
    elif problem in ("world", "ignore"):
        event = next(e for e in events if e.get("stage") == "native_replay_terminal_state")
        event["world_status" if problem == "world" else "checksum_ignore_global"] = 1
    else:
        events.append(dict(ok=False, error="native_prefix_completion"))
    with pytest.raises(N.ConversionError):
        N.terminal_evidence(*synthetic_capture(tmp_path, events=events))


def test_pending_vrec_is_not_a_cache_hit(tmp_path):
    entry = tmp_path / "entry"
    entry.mkdir()
    (entry / "recording.vrec").write_bytes(b"readable prefix is not completion")
    with pytest.raises(N.ConversionError, match="pending or incomplete"):
        N.checked_cache(entry, {})


def test_cache_publishes_marker_last_and_verifies_bytes(tmp_path):
    ready, report = tmp_path / "ready.vrec", tmp_path / "conversion.json"
    ready.write_bytes(b"verified VREC stand-in")
    report.write_text("{}")
    identity = {"input_sha256": "a", "profile_sha256": "b"}
    entry = tmp_path / "cache" / "entry"
    result = N.publish_cache(entry, identity, ready, report, tmp_path)
    assert result == entry / "recording.vrec"
    assert N.checked_cache(entry, identity) == result
    result.write_bytes(b"changed")
    with pytest.raises(N.ConversionError, match="Cache bytes changed"):
        N.checked_cache(entry, identity)


def test_input_pin_change_is_rejected(tmp_path):
    replay = tmp_path / "selected.aoe2record"
    replay.write_bytes(b"original")
    expected = N.pin(replay)
    replay.write_bytes(b"changed input")
    with pytest.raises(N.ConversionError, match="Pinned input changed"):
        N.verify_pins([expected])


def test_known_resign_prefix_is_recovered_and_reported(tmp_path):
    capture, receipt, descriptor = synthetic_capture(tmp_path, events=capture_events(ended=True))
    capture.write_text("4 ResignPlayer7 ResignPlayer" + capture.read_text())
    record = json.loads(receipt.read_text())
    record["stdout_sha256"] = N.pin(capture)["sha256"]
    receipt.write_text(json.dumps(record))
    evidence = N.terminal_evidence(capture, receipt, descriptor)
    assert evidence["game_ended"] is True
    assert evidence["recovered_known_resign_prefixes"] == [
        dict(line=1, prefix="4 ResignPlayer7 ResignPlayer", characters=28)
    ]


def test_unknown_non_json_output_is_rejected(tmp_path):
    capture, receipt, descriptor = synthetic_capture(tmp_path)
    capture.write_text("not a reviewed native prefix\n" + capture.read_text())
    record = json.loads(receipt.read_text())
    record["stdout_sha256"] = N.pin(capture)["sha256"]
    receipt.write_text(json.dumps(record))
    with pytest.raises(N.ConversionError, match="Malformed native output at line 1"):
        N.terminal_evidence(capture, receipt, descriptor)


def test_environment_has_only_private_prefix_and_no_display(monkeypatch):
    monkeypatch.setenv("DISPLAY", ":0")
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    monkeypatch.setenv("WINEPREFIX", "/ordinary/game/prefix")
    monkeypatch.setenv("WINESERVER", "/unrelated/wineserver")
    profile = dict(
        prefix="/owned/prefix",
        runtime="/owned/runtime",
        artifact_root="/research/repo/artifacts/game-internals/envelope",
    )
    env = N.headless_environment(profile)
    assert "DISPLAY" not in env and "WAYLAND_DISPLAY" not in env and "WINESERVER" not in env
    assert env["WINEPREFIX"] == "/owned/prefix"
    assert "winewayland.drv=d" in env["WINEDLLOVERRIDES"]
    # The profile's pinned scripts import the repository holding its artifacts.
    assert env["PYTHONPATH"] == "/research/repo"
    assert N.profile_repository(profile) == Path("/research/repo")


def test_cancel_signals_only_the_owned_session(tmp_path, monkeypatch):
    started = threading.Event()
    signals, calls = [], []

    class Child:
        pid = 123456
        returncode = None

        def poll(self):
            return self.returncode

        def wait(self, timeout=None):
            self.returncode = -signal.SIGTERM
            return self.returncode

    child = Child()

    def popen(command, **kwargs):
        calls.append((command, kwargs))
        started.set()
        return child

    monkeypatch.setattr(subprocess, "Popen", popen)
    monkeypatch.setattr(N.os, "killpg", lambda pid, sig: signals.append((pid, sig)))
    job = N.NativeConversion(tmp_path / "profile", "0" * 64, tmp_path / "cache")
    errors = []

    def run():
        try:
            job._run(["fake-worker"], tmp_path, "native", cwd=tmp_path, environment={})
        except N.ConversionCancelled as error:
            errors.append(error)

    worker = threading.Thread(target=run)
    worker.start()
    assert started.wait(2)
    job.cancel()
    worker.join(2)
    assert not worker.is_alive() and errors
    assert calls[0][1]["start_new_session"] is True
    assert signals and all(pid == child.pid for pid, _ in signals)
    receipt = json.loads((tmp_path / "native.process-exit.json").read_text())
    assert receipt["cancelled"] is True and receipt["exit_code"] == -signal.SIGTERM
    assert not (tmp_path / "success.json").exists()


def test_child_error_keeps_failure_receipt_and_no_success(tmp_path, monkeypatch):
    class FailedChild:
        pid, returncode = 111, 37

        def poll(self):
            return self.returncode

    monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: FailedChild())
    job = N.NativeConversion(tmp_path / "profile", "0" * 64, tmp_path / "cache")
    with pytest.raises(N.ConversionError, match="exit=37"):
        job._run(["fake-worker"], tmp_path, "compile", cwd=tmp_path, environment={})
    receipt = json.loads((tmp_path / "compile.process-exit.json").read_text())
    assert receipt["exit_code"] == 37 and receipt["timed_out"] is False
    assert not (tmp_path / "cache").exists()


def test_timeout_terminates_owned_process_and_keeps_receipt(tmp_path, monkeypatch):
    signals = []

    class SlowChild:
        pid, returncode = 222, None

        def poll(self):
            return self.returncode

        def wait(self, timeout=None):
            self.returncode = -signal.SIGTERM
            return self.returncode

    monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: SlowChild())
    monkeypatch.setattr(N.os, "killpg", lambda pid, sig: signals.append((pid, sig)))
    job = N.NativeConversion(tmp_path / "profile", "0" * 64, tmp_path / "cache", timeout=0.001)
    with pytest.raises(N.ConversionError, match="timed_out=True"):
        job._run(["fake-worker"], tmp_path, "native", cwd=tmp_path, environment={})
    assert signals == [(222, signal.SIGTERM)]
    assert json.loads((tmp_path / "native.process-exit.json").read_text())["timed_out"] is True


@pytest.mark.parametrize("change_input", [False, True])
def test_fresh_bundle_pipeline_and_changed_input_publication_gate(
    tmp_path, monkeypatch, change_input
):
    """Exercise orchestration with fake phases; no subprocess is launched."""
    replay = tmp_path / "selected.aoe2record"
    replay.write_bytes(b"synthetic selected recording")
    host = tmp_path / "host-template.cpp"
    host.write_text("synthetic reviewed host")
    asset = tmp_path / "asset"
    asset.write_bytes(b"synthetic local asset")
    profile_path = tmp_path / "profile.json"
    profile_path.write_text("{}")
    prefix = tmp_path / "private" / "owned-prefix"
    prefix.mkdir(parents=True)
    profile = dict(
        prefix=str(prefix),
        runtime=str(tmp_path),
        pins=[N.pin(asset)],
        renderer=dict(path="fake-renderer"),
        template=N.pin(host),
        compiler=dict(path="fake-compiler"),
        wine=dict(path="fake-wine"),
        encoder=dict(path="fake-encoder", sha256="encoder"),
        encoder_profile=dict(path="fake-encoder-profile", sha256="encoder-profile"),
        engine_sha256="engine",
        capabilities=["recording_eof_is_not_game_end"],
        source_contracts=[],
    )
    monkeypatch.setattr(N, "load_profile", lambda *args: (profile, N.pin(profile_path)))
    job = N.NativeConversion(profile_path, "0" * 64, tmp_path / "cache")
    phases = []

    def phase(command, directory, name, *, cwd, environment):
        phases.append(name)
        source = directory / "source"
        if name == "render":
            assert command[3] == "fake-renderer"
            source.mkdir()
            (source / "host.cpp").write_bytes(host.read_bytes())
            (source / "input-save.inflated.bin").write_bytes(b"saved world")
            descriptor = dict(
                recording_sha256=N.pin(replay)["sha256"],
                recording_bytes=N.pin(replay)["bytes"],
                final_clock_ms=31,
                postgame_marker_end=100,
                postgame_remaining_bytes=8,
                bootstrap_syncs=[
                    dict(offset=0, delta_ms=0, time_ms=0, payload_bytes=4),
                    dict(offset=8, delta_ms=20, time_ms=20, payload_bytes=4),
                    dict(offset=16, delta_ms=11, time_ms=31, payload_bytes=4),
                ],
            )
            (source / "descriptor.json").write_text(json.dumps(descriptor))
            keys = (
                "image",
                "inflated_dat",
                "shadow_asset",
                "unitlines_asset",
                "eras_asset",
                "civilizations_asset",
                "pompeii_eras_asset",
                "pompeii_civilizations_asset",
                "constants_asset",
                "color_asset",
            )
            prepared = dict.fromkeys(keys, str(asset))
            prepared.update(
                prefix=profile["prefix"],
                runtime=profile["runtime"],
                source_pins=[],
                asset_pins=[N.pin(asset)],
                local_inputs=[N.pin(p) for p in source.iterdir()],
                saved_world=str(source / "input-save.inflated.bin"),
                original_recording=str(replay),
                technology_assets=[str(asset)] * 2,
            )
            (source / "source-prepared.json").write_text(json.dumps(prepared))
        elif name == "compile":
            assert "-Werror" in command
            (source / "vantage-native-input-derived.exe").write_bytes(b"fake compiled worker")
        elif name == "native":
            prepared = json.loads((source / "prepared.json").read_text())
            assert prepared["compiled"] is True and prepared["build_exit_code"] == 0
            assert prepared["worker"] == str(source / "vantage-native-input-derived.exe")
            assert len(prepared["pins"]) == len({row["path"] for row in prepared["pins"]})
            descriptor = json.loads((source / "descriptor.json").read_text())
            events = capture_events()
            close = next(e for e in events if e.get("stage") == "owned_recording_postgame_close")
            close["file_bytes"] = descriptor["recording_bytes"]
            (directory / "native.stdout.log").write_text("\n".join(map(json.dumps, events)))
            return dict(
                receipt_kind="ordinary_owned_subprocess",
                exit_code=0,
                timed_out=False,
                cancelled=False,
                stdout_sha256=N.pin(directory / "native.stdout.log")["sha256"],
            )
        elif name == "encode":
            assert "--confirmed-terminal" in command and "--terminal-evidence-sha" in command
            encoded = directory / "encoded"
            encoded.mkdir()
            ready = encoded / "recording.vrec"
            ready.write_bytes(b"verified fake encoder output")
            report = dict(
                status="conversion_verified",
                observed_worker_exit_code=0,
                capture_frames=3,
                capture_end_ms=31,
                recording_end_reason="recording_eof",
                game_ended=False,
                all_serialized_Frame_bytes_readback_digest_checked=True,
                recording=N.pin(ready),
            )
            (encoded / "conversion.json").write_text(json.dumps(report))
            if change_input:
                replay.write_bytes(b"changed during encoding")
        else:
            pytest.fail(f"Unexpected phase {name}")
        return dict(exit_code=0)

    monkeypatch.setattr(job, "_run", phase)
    if change_input:
        with pytest.raises(N.ConversionError, match="Pinned input changed"):
            job.convert(replay)
        assert not (tmp_path / "cache" / "entries").exists()
    else:
        output = job.convert(replay)
        assert output.read_bytes() == b"verified fake encoder output"
        assert phases == ["render", "compile", "native", "encode"]
        assert job.convert(replay) == output
        assert len(phases) == 4  # A verified cache hit launches no child.
