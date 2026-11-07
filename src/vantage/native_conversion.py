"""Experimental local, headless recording conversion with a pinned native profile.

The profile depends on reviewed research artifacts and locally installed assets.
Only committed cache entries are usable results. Recording EOF is not game end.
This module has no game launcher, GameAPI, display or HTTP fallback.
"""

from __future__ import annotations

import argparse
import contextlib
import fcntl
import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterator
    from typing import TYPE_CHECKING


class ConversionError(RuntimeError):
    """A failed conversion has no ready output, even if a VREC prefix exists."""


class ConversionCancelled(ConversionError):
    pass


def pin(path: Path) -> dict[Any, Any]:
    path = path.resolve(strict=True)
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    return {"path": str(path), "bytes": path.stat().st_size, "sha256": digest}


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise ConversionError(reason)


def write_json(path: Path, value: dict[Any, Any]) -> None:
    with path.open("x") as stream:
        json.dump(value, stream, indent=2, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def verify_pins(pins: list[dict[Any, Any]]) -> None:
    seen: dict[Any, Any] = {}
    for expected in pins:
        path = Path(expected["path"])
        require(pin(path) == expected, f"Pinned input changed: {path}")
        require(seen.get(str(path), expected) == expected, f"Conflicting pin: {path}")
        seen[str(path)] = expected


def load_profile(path: Path, expected_sha: str) -> tuple[dict[Any, Any], dict[Any, Any]]:
    require(bool(re.fullmatch(r"[0-9a-f]{64}", expected_sha)), "Exact profile SHA required")
    actual = pin(path)
    require(actual["sha256"] == expected_sha, "Profile SHA differs")
    profile = json.loads(path.read_text())
    require(profile.get("kind") == "vantage_experimental_local_native", "Unsupported profile")
    require(profile.get("version") == 1, "Unsupported profile version")
    verify_pins(profile["pins"])
    pinned = {row["path"]: row for row in profile["pins"]}
    for key in ("renderer", "template", "encoder", "encoder_profile", "compiler", "wine"):
        require(profile[key] == pinned.get(profile[key]["path"]), f"Unpinned role: {key}")
    require(
        pinned.get(str(Path(__file__).resolve())) == pin(Path(__file__)),
        "Backend source is not profile-pinned",
    )
    require(
        profile["compiler"]["path"] == str(Path("/usr/bin/x86_64-w64-mingw32-g++").resolve()),
        "Unsupported compiler",
    )
    require(profile["wine"]["path"] == str(Path("/usr/bin/wine").resolve()), "Unsupported Wine")
    root = Path(profile["artifact_root"]).resolve(strict=True)
    prefix = root / "native-image-host-v1/owned-prefix"
    runtime = root / "native-image-host-v1/owned-runtime"
    require(
        Path(profile["prefix"]) == prefix and Path(profile["runtime"]) == runtime,
        "Only the task-owned private prefix/runtime are supported",
    )
    require(prefix.is_dir() and not prefix.is_symlink(), "Private prefix is missing or a symlink")
    require(
        runtime.is_dir() and not runtime.is_symlink(), "Private runtime is missing or a symlink"
    )
    return profile, actual


def profile_repository(profile: dict[Any, Any]) -> Path:
    """The repository whose pinned renderer and encoder scripts the profile runs.

    The profile's research scripts (renderer, encoder) import the development
    copy's modules, and the profile pins those modules where they are: the
    repository that holds the profile's artifact root (artifacts/game-internals/X).
    In the development copy this is the backend's own repository; elsewhere the
    scripts still run, unchanged, against the code they were pinned with.
    """
    if "artifact_root" not in profile:
        return Path(__file__).resolve().parents[2]
    return Path(profile["artifact_root"]).resolve().parents[2]


def headless_environment(profile: dict[Any, Any]) -> dict[Any, Any]:
    result = dict(os.environ)
    for key in ("DISPLAY", "WAYLAND_DISPLAY", "PYTHONHOME", "WINELOADER", "WINESERVER"):
        result.pop(key, None)
    result.update(
        WINEPREFIX=profile["prefix"],
        XDG_RUNTIME_DIR=profile["runtime"],
        WINEDEBUG="-all",
        WINEDLLOVERRIDES=(
            "winemenubuilder.exe=d;mscoree,mshtml=d;winex11.drv,winemac.drv,winewayland.drv=d"
        ),
        PYTHONDONTWRITEBYTECODE="1",
        PYTHONPATH=str(profile_repository(profile)),
    )
    return result


class NativeConversion:
    """One synchronous job. cancel() only terminates this object's owned child group."""

    def __init__(
        self, profile: Path, profile_sha256: str, cache_dir: Path, *, timeout: float = 900
    ) -> None:
        require(0 < timeout <= 86400, "Timeout must be in (0, 86400] seconds")
        self.profile_path = profile.resolve()
        self.profile_sha256 = profile_sha256
        self.cache_dir = cache_dir.resolve()
        self.timeout = timeout
        self._cancelled = threading.Event()
        self._child_lock = threading.Lock()
        self._child: Any = None

    def cancel(self) -> None:
        self._cancelled.set()
        with self._child_lock:
            if self._child is not None and self._child.poll() is None:
                self._signal_owned(self._child, signal.SIGTERM)

    @staticmethod
    def _signal_owned(child: Any, sig: int) -> None:
        # Every owned child was created with start_new_session=True. Never search
        # by executable name, kill a shared wineserver, or touch a game prefix.
        with contextlib.suppress(ProcessLookupError):
            os.killpg(child.pid, sig)

    def _check_cancel(self) -> None:
        if self._cancelled.is_set():
            raise ConversionCancelled("Conversion cancelled; no cache entry committed")

    @contextlib.contextmanager
    def _prefix_lock(self, profile: dict[Any, Any]) -> Iterator[Any]:
        lock_path = Path(profile["prefix"]).parent / ".vantage-native-conversion.lock"
        started = time.monotonic()
        with lock_path.open("a") as stream:
            while True:
                self._check_cancel()
                require(time.monotonic() - started < self.timeout, "Private prefix lock timed out")
                try:
                    fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    self._cancelled.wait(0.1)
            try:
                yield
            finally:
                fcntl.flock(stream, fcntl.LOCK_UN)

    def _run(
        self,
        command: list[str],
        directory: Path,
        name: str,
        *,
        cwd: Path,
        environment: dict[Any, Any],
    ) -> dict[Any, Any]:
        self._check_cancel()
        started = time.monotonic()
        timed_out = False
        stdout, stderr = directory / f"{name}.stdout.log", directory / f"{name}.stderr.log"
        with stdout.open("xb") as out, stderr.open("xb") as err:
            with self._child_lock:
                self._check_cancel()
                child = subprocess.Popen(
                    command,
                    cwd=cwd,
                    env=environment,
                    stdout=out,
                    stderr=err,
                    start_new_session=True,
                )
                self._child = child
            try:
                while child.poll() is None:
                    if self._cancelled.is_set() or time.monotonic() - started >= self.timeout:
                        timed_out = not self._cancelled.is_set()
                        self._signal_owned(child, signal.SIGTERM)
                        try:
                            child.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            self._signal_owned(child, signal.SIGKILL)
                            child.wait()
                        break
                    self._cancelled.wait(0.05)
            except BaseException:
                self._signal_owned(child, signal.SIGKILL)
                child.wait()
                raise
            finally:
                with self._child_lock:
                    self._child = None
        receipt = dict(
            command=command,
            exit_code=child.returncode,
            timed_out=timed_out,
            cancelled=self._cancelled.is_set(),
            seconds=time.monotonic() - started,
            receipt_kind="ordinary_owned_subprocess",
            stdout_sha256=pin(stdout)["sha256"],
            stderr_sha256=pin(stderr)["sha256"],
        )
        # Preserve the observed exit before hashing the native producer inputs.
        write_json(directory / f"{name}.process-exit.json", receipt)
        self._check_cancel()
        require(
            not timed_out and child.returncode == 0,
            f"{name} failed (exit={child.returncode}, timed_out={timed_out}); see {stderr}",
        )
        return receipt

    def convert(self, replay: Path, *, out: Path | None = None) -> Path:
        replay = replay.resolve(strict=True)
        require(replay.suffix.lower() == ".aoe2record", "Expected an .aoe2record input")
        profile, profile_pin = load_profile(self.profile_path, self.profile_sha256)
        input_pin = pin(replay)
        identity = dict(
            input_sha256=input_pin["sha256"],
            profile_sha256=profile_pin["sha256"],
            engine=profile["engine_sha256"],
            encoder=profile["encoder"]["sha256"],
            capabilities=profile["capabilities"],
            backend_version=1,
        )
        key = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
        with self._prefix_lock(profile):
            self._check_cancel()
            verify_pins(profile["pins"] + [profile_pin, input_pin])
            entry = self.cache_dir / "entries" / key
            if entry.exists():
                result = checked_cache(entry, identity)
            else:
                job = self.cache_dir / "jobs" / uuid.uuid4().hex
                job.mkdir(parents=True)
                write_json(
                    job / "job.json",
                    dict(identity=identity, input=input_pin, profile=profile_pin, state="pending"),
                )
                result = self._produce(
                    replay, job, entry, identity, profile, profile_pin, input_pin
                )
            self._check_cancel()
            if out is not None:
                out = out.resolve()
                require(not out.exists(), f"Output already exists: {out}")
                out.parent.mkdir(parents=True, exist_ok=True)
                pending = out.with_name(out.name + "." + uuid.uuid4().hex + ".pending")
                try:
                    shutil.copyfile(result, pending)
                    require(pin(pending)["sha256"] == pin(result)["sha256"], "Output copy differs")
                    # Hard-link publication refuses to overwrite a concurrently created output.
                    os.link(pending, out)
                finally:
                    pending.unlink(missing_ok=True)
                return out
            return result

    def _produce(
        self,
        replay: Path,
        job: Path,
        entry: Path,
        identity: dict[Any, Any],
        profile: dict[Any, Any],
        profile_pin: dict[Any, Any],
        input_pin: dict[Any, Any],
    ) -> Path:
        environment = headless_environment(profile)
        repo = profile_repository(profile)
        source = job / "source"
        python = [sys.executable, "-B", "-P"]
        self._run(
            [*python, profile["renderer"]["path"], "--replay", str(replay), "--out", str(source)],
            job,
            "render",
            cwd=repo,
            environment=environment,
        )
        prepared = json.loads((source / "source-prepared.json").read_text())
        require(
            prepared["prefix"] == profile["prefix"] and prepared["runtime"] == profile["runtime"],
            "Renderer changed private prefix/runtime",
        )
        require(
            pin(source / "host.cpp")["sha256"] == profile["template"]["sha256"],
            "Renderer changed reviewed host",
        )
        descriptor = json.loads((source / "descriptor.json").read_text())
        require(
            descriptor["recording_sha256"] == input_pin["sha256"]
            and descriptor["recording_bytes"] == input_pin["bytes"],
            "Rendered input changed",
        )
        verify_pins(prepared["source_pins"] + prepared["asset_pins"] + prepared["local_inputs"])
        worker = source / "vantage-native-input-derived.exe"
        command = [
            profile["compiler"]["path"],
            "-std=c++17",
            "-O2",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-static",
            "-municode",
            "-Wl,--image-base,0x180000000",
            str(source / "host.cpp"),
            "-lbcrypt",
            "-o",
            str(worker),
        ]
        build = self._run(command, job, "compile", cwd=repo, environment=environment)
        pins = prepared["source_pins"] + prepared["asset_pins"] + prepared["local_inputs"]
        pins += [pin(source / "source-prepared.json"), input_pin, profile_pin, pin(worker)]
        unique = {row["path"]: row for row in pins}
        verify_pins(list(unique.values()) + profile["pins"])
        prepared.update(
            worker=str(worker),
            build_exit_code=build["exit_code"],
            compile_command=command,
            compiled=True,
            pins=list(unique.values()),
        )
        write_json(source / "prepared.json", prepared)
        compiled_manifest_pin = pin(source / "prepared.json")
        native = [profile["wine"]["path"], str(worker)]
        asset_order = (
            "image",
            "inflated_dat",
            "shadow_asset",
            "unitlines_asset",
            "saved_world",
            "eras_asset",
            "civilizations_asset",
            "pompeii_eras_asset",
            "pompeii_civilizations_asset",
            "constants_asset",
            "color_asset",
            "original_recording",
        )
        native += ["Z:" + prepared[key].replace("/", "\\") for key in asset_order]
        native += ["Z:" + path.replace("/", "\\") for path in prepared["technology_assets"]]
        receipt = self._run(
            native, job, "native", cwd=Path(prepared["image"]).parent, environment=environment
        )
        verify_pins(prepared["pins"] + [compiled_manifest_pin] + profile["pins"])
        receipt["all_input_pins_unchanged"] = True
        write_json(job / "execution.json", receipt)
        evidence = terminal_evidence_for_input(
            job / "native.stdout.log", job / "execution.json", descriptor
        )
        evidence["source_contracts"] = profile["source_contracts"]
        write_json(job / "terminal-evidence.json", evidence)
        encoded = job / "encoded"
        encode = [
            *python,
            profile["encoder"]["path"],
            "--confirmed-terminal",
            "--capture",
            str(job / "native.stdout.log"),
            "--receipt",
            str(job / "execution.json"),
            "--receipt-sha",
            pin(job / "execution.json")["sha256"],
            "--descriptor",
            str(source / "descriptor.json"),
            "--descriptor-sha",
            pin(source / "descriptor.json")["sha256"],
            "--saved-world",
            prepared["saved_world"],
            "--profile",
            profile["encoder_profile"]["path"],
            "--profile-sha",
            profile["encoder_profile"]["sha256"],
            "--producer-bundle",
            str(source),
            "--out",
            str(encoded),
            "--expected-frames",
            str(evidence["expected_frames"]),
            "--expected-end-ms",
            str(evidence["expected_end_ms"]),
            "--terminal-evidence",
            str(job / "terminal-evidence.json"),
            "--terminal-evidence-sha",
            pin(job / "terminal-evidence.json")["sha256"],
        ]
        self._run(encode, job, "encode", cwd=repo, environment=environment)
        report = json.loads((encoded / "conversion.json").read_text())
        ready = encoded / "recording.vrec"
        require(
            report.get("status") == "conversion_verified"
            and report.get("observed_worker_exit_code") == 0
            and report.get("capture_frames") == evidence["expected_frames"]
            and report.get("capture_end_ms") == descriptor["final_clock_ms"]
            and report.get("recording_end_reason") == evidence["recording_end_reason"]
            and report.get("game_ended") is evidence["game_ended"]
            and report.get("all_serialized_Frame_bytes_readback_digest_checked") is True
            and report.get("recording") == pin(ready),
            "Encoder has no verified committed output",
        )
        verify_pins(
            prepared["pins"] + profile["pins"] + [compiled_manifest_pin, profile_pin, input_pin]
        )
        self._check_cancel()
        return publish_cache(entry, identity, ready, encoded / "conversion.json", job)


def terminal_evidence(
    capture: Path, receipt_path: Path, descriptor: dict[Any, Any]
) -> dict[Any, Any]:
    """Check source-pinned closure and actual update/projection cadence, not sync counts."""
    receipt = json.loads(receipt_path.read_text())
    capture_pin = pin(capture)
    require(
        receipt.get("receipt_kind") == "ordinary_owned_subprocess"
        and type(receipt.get("exit_code")) is int
        and receipt["exit_code"] == 0
        and receipt.get("timed_out") is False
        and receipt.get("cancelled") is False
        and receipt.get("all_input_pins_unchanged") is True
        and receipt.get("stdout_sha256") == capture_pin["sha256"],
        "Native receipt rejected",
    )
    stages = (
        "native_entity_frame",
        "native_world_frame",
        "native_player_frame",
        "native_entity_presentation_frame",
    )
    cadence = {name: hashlib.sha256() for name in (*stages, "updates")}
    counts = dict.fromkeys(cadence, 0)
    selected = {}
    audio_bindings, audio_requests, audio_after_updates = [], [], []
    last_update: Any = None
    ok = 0
    recovered_prefixes = []
    # Exact bounded grammar already used by reviewed v8/v11 capture readers.
    resign_prefix = re.compile(r"^(?:[0-9]+ ResignPlayer)+")
    for number, raw in enumerate(capture.open(), 1):
        match = resign_prefix.match(raw)
        line = raw
        if match:
            recovered_prefixes.append(dict(line=number, prefix=match[0], characters=match.end()))
            line = raw[match.end() :]
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError as error:
            raise ConversionError(f"Malformed native output at line {number}") from error
        require(isinstance(event, dict), f"Non-object native event at line {number}")
        require("error" not in event and event.get("ok") is not False, "Native failure event")
        stage = event.get("stage")
        if stage == "headless_audio_adapter_bound":
            audio_bindings.append(event)
        elif stage == "headless_audio_request":
            audio_requests.append(event)
        elif stage == "headless_audio_state_after_update":
            audio_after_updates.append(event)
        if event.get("ok") is True:
            ok += 1
        if stage == "native_world_update_returned":
            ordinal, clock = event["ordinal"], event["world_time_ms"]
            require(
                ordinal == counts["updates"] + 1
                and type(clock) is int
                and 0 <= clock <= descriptor["final_clock_ms"]
                and (last_update is None or clock >= last_update["world_time_ms"])
                and event["status"] in (0, 1),
                "Native update sequence rejected",
            )
            if last_update is not None:
                require(last_update["status"] == 0, "Updates continued after game terminal")
            last_update = event
            counts["updates"] += 1
            cadence["updates"].update(f"{clock},".encode())
        elif stage in stages:
            counts[stage] += 1
            cadence[stage].update(f"{event['time_ms']},".encode())
        if stage in (
            "native_recording_eof_admitted",
            "native_original_terminal_status_admitted",
            "native_replay_terminal_state",
            "native_simulation_prefix_complete",
            "owned_recording_postgame_close",
        ):
            require(stage not in selected, f"Duplicate terminal event: {stage}")
            selected[stage] = event
    count, end = counts["updates"], descriptor["final_clock_ms"]
    require(
        count > 0 and last_update is not None and last_update["world_time_ms"] == end and ok == 1,
        "Native completion is absent",
    )
    require(
        all(
            counts[name] == count and cadence[name].digest() == cadence["updates"].digest()
            for name in stages
        ),
        "Native projection cadence differs from actual updates",
    )
    completion = selected.get("native_simulation_prefix_complete", {})
    require(
        completion.get("completed_world_updates") == count
        and completion.get("world_time_ms") == end
        and completion.get("projected_frames") == count
        and type(completion.get("audio_requests")) is int
        and 0 <= completion["audio_requests"] <= 0xFFFFFFFF
        and completion.get("native_audio_initialized") is False,
        "Completion contract rejected",
    )
    if completion["audio_requests"]:
        # The source-bound adapter counts disabled requests and returns no playing
        # ID. Only its first sixteen requests are logged. A zero counter retains
        # the existing fixture contract without requiring diagnostic events.
        require(
            len(audio_bindings) == 1 and len(audio_after_updates) == 1,
            "Disabled audio adapter observations rejected",
        )
        binding, after_update = audio_bindings[0], audio_after_updates[0]
        require(
            binding
            == dict(
                stage="headless_audio_adapter_bound",
                native_entry="140b277d0",
                playing_id_on_disabled_output=0,
                native_audio_initialized=False,
                native_audio_success_claim=False,
            )
            and type(binding.get("playing_id_on_disabled_output")) is int
            and binding.get("native_audio_initialized") is False
            and binding.get("native_audio_success_claim") is False
            and after_update.get("native_audio_initialized") is False
            and type(after_update.get("requests")) is int
            and 0 <= after_update["requests"] <= completion["audio_requests"]
            and len(audio_requests) == min(completion["audio_requests"], 16),
            "Disabled audio adapter evidence rejected",
        )
        for ordinal, request in enumerate(audio_requests, 1):
            require(
                type(request.get("ordinal")) is int
                and request["ordinal"] == ordinal
                and request.get("backend") == "disabled"
                and type(request.get("playing_id")) is int
                and request["playing_id"] == 0,
                "Disabled audio request evidence rejected",
            )
    close = selected.get("owned_recording_postgame_close", {})
    require(
        close.get("marker") == 6
        and close.get("position") == descriptor["postgame_marker_end"]
        and close.get("file_bytes") == descriptor["recording_bytes"]
        and close.get("unread_tail_bytes") == descriptor["postgame_remaining_bytes"]
        and close.get("source_final_clock") == end
        and close.get("native_log_ms") == end
        and close.get("native_file_fields_changed") is False,
        "Original recording close rejected",
    )
    terminal = selected.get("native_replay_terminal_state", {})
    ended = terminal.get("world_status") == 1
    require(
        type(terminal.get("world_status")) is int
        and terminal["world_status"] in (0, 1)
        and terminal.get("world_time_ms") == end
        and terminal.get("native_log_ms") == end
        and terminal.get("replay_active") == 0
        and terminal.get("replay_file_present") is False
        and terminal.get("owned_recording_closed") is True
        and terminal.get("file_cursor") == descriptor["postgame_marker_end"]
        and terminal.get("checksum_ignore_global") == 0
        and terminal.get("original_terminal_status_observed") is ended
        and terminal.get("recording_eof_observed") is (not ended)
        and terminal.get("recording_end_reason")
        == ("world_terminal" if ended else "recording_eof"),
        "Actual native terminal state rejected",
    )
    name = "native_original_terminal_status_admitted" if ended else "native_recording_eof_admitted"
    other = "native_recording_eof_admitted" if ended else "native_original_terminal_status_admitted"
    admission = selected.get(name, {})
    require(
        other not in selected
        and admission.get("returned_status") == int(ended)
        and last_update["status"] == int(ended)
        and admission.get("world_status") == int(ended)
        and admission.get("world_time_ms") == end
        and admission.get("completed_updates") == count
        and admission.get("native_replay_closed") is True
        and admission.get("checksum_ignore_global") == 0
        and admission.get("host_native_status_write") is False,
        "Source closure admission rejected",
    )
    if not ended:
        require(
            admission.get("game_ended") is False and admission.get("recording_completed") is True,
            "EOF was confused with game end",
        )
    return dict(
        capture=capture_pin,
        terminal_receipt=pin(receipt_path),
        expected_frames=count,
        expected_end_ms=end,
        game_ended=ended,
        game_end_inferred_from_EOF=False,
        recording_end_reason="native_game_end" if ended else "recording_eof",
        original_EOF_event=admission if not ended else None,
        original_terminal_event=admission,
        original_capture_completion=completion,
        native_terminal_state=terminal,
        original_close_event=close,
        source_guard_qualification="refs0/byte80/registry ownership checked by pinned host; "
        "closure event is not an independent native field dump",
        recovered_known_resign_prefixes=recovered_prefixes,
    )


def terminal_evidence_for_input(
    capture: Path, receipt_path: Path, descriptor: dict[Any, Any]
) -> dict[Any, Any]:
    """Full-descriptor conversion path; public zero-first terminal_evidence is unchanged."""
    from .native_bootstrap_policy import is_positive_first

    try:
        positive = is_positive_first(descriptor)
    except ValueError as error:
        raise ConversionError(str(error)) from error
    if not positive:
        return terminal_evidence(capture, receipt_path, descriptor)
    from .native_bootstrap_admission import positive_terminal_evidence

    try:
        return positive_terminal_evidence(capture, receipt_path, descriptor)
    except ValueError as error:
        raise ConversionError(str(error)) from error


def checked_cache(entry: Path, identity: dict[Any, Any]) -> Path:
    require(entry.is_dir() and not entry.is_symlink(), "Invalid cache entry")
    marker = entry / "success.json"
    require(marker.is_file(), "Cache entry is pending or incomplete; no success marker")
    success = json.loads(marker.read_text())
    require(
        success.get("identity") == identity and success.get("status") == "ready",
        "Cache identity differs",
    )
    ready = entry / "recording.vrec"
    require(
        success.get("recording") == pin(ready)
        and success.get("conversion") == pin(entry / "conversion.json"),
        "Cache bytes changed",
    )
    return ready


def publish_cache(
    entry: Path, identity: dict[Any, Any], ready: Path, report: Path, job: Path
) -> Path:
    entry.parent.mkdir(parents=True, exist_ok=True)
    pending = entry.with_name(f".{entry.name}.{uuid.uuid4().hex}.pending")
    pending.mkdir()
    shutil.copyfile(ready, pending / "recording.vrec")
    shutil.copyfile(report, pending / "conversion.json")
    recording_pin, conversion_pin = (
        pin(pending / "recording.vrec"),
        pin(pending / "conversion.json"),
    )
    recording_pin["path"], conversion_pin["path"] = (
        str(entry / "recording.vrec"),
        str(entry / "conversion.json"),
    )
    write_json(
        pending / "success.json",
        dict(
            status="ready",
            identity=identity,
            job=str(job),
            recording=recording_pin,
            conversion=conversion_pin,
        ),
    )
    require(not entry.exists(), "Cache entry appeared concurrently")
    pending.rename(entry)
    return checked_cache(entry, identity)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("replay", type=Path)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--profile-sha256", required=True)
    parser.add_argument(
        "--cache-dir", type=Path, default=Path.home() / ".cache/vantage/native-local"
    )
    parser.add_argument("--out", type=Path)
    parser.add_argument("--timeout", type=float, default=900)
    args = parser.parse_args()
    job = NativeConversion(args.profile, args.profile_sha256, args.cache_dir, timeout=args.timeout)
    try:
        result = job.convert(args.replay, out=args.out)
    except KeyboardInterrupt:
        job.cancel()
        raise SystemExit("Conversion cancelled; no unverified output accepted") from None
    except (ConversionError, OSError, ValueError, KeyError) as error:
        raise SystemExit(str(error)) from error
    print(result)


if __name__ == "__main__":
    main()
