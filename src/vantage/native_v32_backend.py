"""Opt-in V32 converter for the normal native Session cache contract."""

from __future__ import annotations

import contextlib
import fcntl
import hashlib
import json
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .native_conversion import ConversionCancelled, ConversionError, checked_cache, pin, write_json
from .native_v32_encode import V32Encoder, verify_encoder_config
from .native_v32_pipeline import _checksum_stop
from .native_v32_reuse import verified_recording
from .native_v32_runtime import V32Runtime

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path
    from typing import TYPE_CHECKING

    from vantage.native_v32_config import V32Config


_SOURCES = (
    "native_v32_backend.py",
    "native_v32_config.py",
    "native_v32_stage_entry.py",
    "native_v32_cap_stage_entry.py",
    "native_v32_prepare.py",
    "native_v32_input.py",
    "native_v32_runtime.py",
    "native_v32_admission.py",
    "native_v32_encode.py",
    "native_v32_reuse.py",
    "native_sdk_admission.py",
    "native_bootstrap_policy.py",
    "native_input.py",
    "native_conversion.py",
    "native_v32_pipeline.py",
)


class V32Conversion:
    """A single-use conversion; cancellation signals only owned process groups."""

    def __init__(self, config: V32Config) -> None:
        self.config = config
        self._cancelled = threading.Event()
        self._lock = threading.Lock()
        self._active: Any = None
        self._used = False

    def _check(self) -> None:
        if self._cancelled.is_set():
            raise ConversionCancelled("V32 replay conversion cancelled")

    def cancel(self) -> None:
        with self._lock:
            self._cancelled.set()
            active = self._active
            if isinstance(active, subprocess.Popen):
                if active.poll() is None:
                    with contextlib.suppress(ProcessLookupError):
                        os.killpg(active.pid, signal.SIGTERM)
            elif active is not None:
                active.cancel()

    def _set_active(self, component: Any) -> None:
        with self._lock:
            self._check()
            self._active = component

    def _clear_active(self, component: Any) -> None:
        with self._lock:
            if self._active is component:
                self._active = None

    @staticmethod
    def _check_report(report_path: Path, verified: Any) -> None:
        report = json.loads(report_path.read_bytes())
        reason = verified["recording_end_reason"]
        if (
            reason not in ("native_game_end", "recording_eof")
            or report.get("recording_end_reason") != reason
            or report.get("game_ended") is not (reason == "native_game_end")
            or report.get("capture_frames") != verified["frames"]
            or report.get("capture_end_ms") != verified["end_ms"]
        ):
            raise ConversionError(
                "V32 encoded ending or frame extent differs from terminal admission"
            )

    def _profiles(self, job: Any) -> Any:
        c = self.config
        source, runtime, encoder = (pin(c.profile), pin(c.runtime_profile), pin(c.encoder_config))
        if (source["sha256"], runtime["sha256"], encoder["sha256"]) != (
            c.profile_sha256,
            c.runtime_profile_sha256,
            c.encoder_config_sha256,
        ):
            raise ConversionError("V32 profile changed; check the configured profile hashes")
        runtime_doc = json.loads(c.runtime_profile.read_bytes())
        if pin(c.runtime_profile) != runtime or runtime_doc.get("staging_profile") != source:
            raise ConversionError("V32 runtime and source profiles do not match")
        verify_encoder_config(c.encoder_config, c.encoder_config_sha256, stage_dir=job)
        return [source, runtime, encoder]

    @contextlib.contextmanager
    def _entry_lock(self, key: str) -> Iterator[Any]:
        locks = self.config.cache_dir / "v32-locks"
        locks.mkdir(parents=True, exist_ok=True)
        with (locks / key).open("a") as f:
            started = time.monotonic()
            while True:
                self._check()
                if time.monotonic() - started >= self.config.runtime_timeout:
                    raise ConversionError("V32 cache lock timed out")
                try:
                    fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    self._cancelled.wait(0.1)
            try:
                yield
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)

    def _stage(self, replay: Any, job: Any) -> None:
        c = self.config
        logs = self.config.cache_dir / "v32-stage-logs"
        logs.mkdir(parents=True, exist_ok=True)
        output = logs / (job.name + ".stdout")
        error = logs / (job.name + ".stderr")
        command = [
            sys.executable,
            "-B",
            "-m",
            "vantage.native_v32_cap_stage_entry",
            "--replay",
            str(replay),
            "--out",
            str(job),
            "--profile",
            str(c.profile),
            "--profile-sha256",
            c.profile_sha256,
            "--compile-timeout",
            str(c.compile_timeout),
        ]
        if c.update_cap is not None:
            command += ["--update-cap", str(c.update_cap)]
        # Stage startup and registration share the same lock as cancellation.
        with output.open("xb") as out, error.open("xb") as err:
            with self._lock:
                self._check()
                child = subprocess.Popen(
                    command,
                    stdin=subprocess.DEVNULL,
                    stdout=out,
                    stderr=err,
                    start_new_session=True,
                )
                self._active = child
            started = time.monotonic()
            timed_out = False
            try:
                while child.poll() is None:
                    if self._cancelled.is_set() or time.monotonic() - started >= c.stage_timeout:
                        timed_out = not self._cancelled.is_set()
                        with contextlib.suppress(ProcessLookupError):
                            os.killpg(child.pid, signal.SIGTERM)
                        try:
                            child.wait(timeout=10)
                        except subprocess.TimeoutExpired:
                            # The wrapper owns the compiler cleanup; do not kill
                            # it while it may still be reaping its child group.
                            child.wait()
                        break
                    self._cancelled.wait(0.05)
            except BaseException:
                if child.poll() is None:
                    with contextlib.suppress(ProcessLookupError):
                        os.killpg(child.pid, signal.SIGTERM)
                    child.wait()
                raise
            finally:
                self._clear_active(child)
            self._check()
            if timed_out or child.returncode != 0:
                raise ConversionError(
                    f"V32 staging {'timed out' if timed_out else 'failed'}; see {error}"
                )

    def _publish(
        self,
        entry: Path,
        identity: Any,
        ready: Path,
        report: Path,
        job: Path,
        expected_recording: Any,
        expected_report: Any,
    ) -> Path:
        entry.parent.mkdir(parents=True, exist_ok=True)
        pending = entry.with_name(f".{entry.name}.{uuid.uuid4().hex}.pending")
        pending.mkdir()
        try:
            if pin(ready) != expected_recording or pin(report) != expected_report:
                raise ConversionError("V32 output changed before cache publication")
            shutil.copyfile(ready, pending / "recording.vrec")
            shutil.copyfile(report, pending / "conversion.json")
            rp, cp = pin(pending / "recording.vrec"), pin(pending / "conversion.json")
            if (rp["bytes"], rp["sha256"]) != (
                expected_recording["bytes"],
                expected_recording["sha256"],
            ) or (cp["bytes"], cp["sha256"]) != (
                expected_report["bytes"],
                expected_report["sha256"],
            ):
                raise ConversionError("V32 cache copy differs from verified output")
            if pin(ready) != expected_recording or pin(report) != expected_report:
                raise ConversionError("V32 output changed during cache publication")
            rp["path"], cp["path"] = str(entry / "recording.vrec"), str(entry / "conversion.json")
            write_json(
                pending / "success.json",
                {
                    "status": "ready",
                    "identity": identity,
                    "job": str(job),
                    "recording": rp,
                    "conversion": cp,
                },
            )
            with self._lock:
                self._check()
                if entry.exists():
                    raise ConversionError("V32 cache entry appeared concurrently")
                pending.rename(entry)
            return checked_cache(entry, identity)
        finally:
            if pending.exists():
                shutil.rmtree(pending)

    def convert(self, replay: Path) -> Path:
        with self._lock:
            self._check()
            if self._used:
                raise ConversionError("V32 converter is single-use")
            self._used = True
        replay = Path(replay).resolve(strict=True)
        if not replay.is_file() or replay.suffix.lower() != ".aoe2record":
            raise ConversionError("Expected a local .aoe2record replay")
        c = self.config
        job = c.cache_dir / "v32-jobs" / uuid.uuid4().hex
        try:
            profiles = self._profiles(c.reuse_job or job)
            source_pins = [pin(Path(__file__).parent / name) for name in _SOURCES]
            input_pin = pin(replay)
            identity = {
                "backend": "v32-sdk-1",
                "replay_sha256": input_pin["sha256"],
                "profiles": profiles,
                "sources": source_pins,
                "runtime_timeout": c.runtime_timeout,
                "encoder_timeout": c.encoder_timeout,
                "stage_timeout": c.stage_timeout,
                "compile_timeout": c.compile_timeout,
                "requested_update_cap": c.update_cap,
                "update_cap_policy": "auto-sync-count-plus-two-floor-262144-v1",
                "reuse_stage": pin(c.reuse_job / "stage.json") if c.reuse_job else None,
            }
            key = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
            entry = c.cache_dir / "v32-entries" / key
            with self._entry_lock(key):
                self._check()
                if entry.exists():
                    ready = checked_cache(entry, identity)
                    marker = json.loads((entry / "success.json").read_bytes())
                    saved = Path(marker["job"]).resolve(strict=True)
                    if (
                        saved != c.reuse_job
                        and saved.parent != (c.cache_dir / "v32-jobs").resolve()
                    ):
                        raise ConversionError("V32 cache job is outside the configured cache")
                    result = json.loads((saved / "pipeline-result.json").read_bytes())
                    verified = verified_recording(
                        saved,
                        result,
                        runtime_profile=c.runtime_profile,
                        runtime_profile_sha256=c.runtime_profile_sha256,
                        encoder_config=c.encoder_config,
                        encoder_config_sha256=c.encoder_config_sha256,
                    )
                    self._check_report(Path(result["encoding"]["conversion"]["path"]), verified)
                    if (verified["recording"]["bytes"], verified["recording"]["sha256"]) != (
                        pin(ready)["bytes"],
                        pin(ready)["sha256"],
                    ):
                        raise ConversionError("V32 cached recording differs from verified output")
                    cached_report = pin(entry / "conversion.json")
                    original_report = result["encoding"]["conversion"]
                    if (cached_report["bytes"], cached_report["sha256"]) != (
                        original_report["bytes"],
                        original_report["sha256"],
                    ):
                        raise ConversionError("V32 cached report differs from verified output")
                    self._check()
                    return ready
                if c.reuse_job is not None:
                    saved = c.reuse_job
                    stage = json.loads((saved / "stage.json").read_bytes())
                    if stage["profile"] != profiles[0] or any(
                        stage["recording"].get(k) != input_pin[k] for k in ("bytes", "sha256")
                    ):
                        raise ConversionError(
                            "Retained V32 job does not match the selected replay or profile"
                        )
                    output = json.loads((saved / "pipeline-result.json").read_bytes())
                    verified = verified_recording(
                        saved,
                        output,
                        runtime_profile=c.runtime_profile,
                        runtime_profile_sha256=c.runtime_profile_sha256,
                        encoder_config=c.encoder_config,
                        encoder_config_sha256=c.encoder_config_sha256,
                    )
                    self._check_report(Path(output["encoding"]["conversion"]["path"]), verified)
                    self._check()
                    if (
                        pin(replay) != input_pin
                        or self._profiles(saved) != profiles
                        or any(pin(Path(row["path"])) != row for row in source_pins)
                        or pin(saved / "stage.json") != identity["reuse_stage"]
                    ):
                        raise ConversionError("Retained V32 job or selected replay changed")
                    return self._publish(
                        entry,
                        identity,
                        Path(verified["recording"]["path"]),
                        Path(output["encoding"]["conversion"]["path"]),
                        saved,
                        verified["recording"],
                        output["encoding"]["conversion"],
                    )
                self._stage(replay, job)
                stage_pin = pin(job / "stage.json")
                stage = json.loads((job / "stage.json").read_bytes())
                if stage["recording"] != input_pin or stage["profile"] != profiles[0]:
                    raise ConversionError("V32 staged input or source profile differs")
                runtime = V32Runtime(timeout=c.runtime_timeout)
                self._set_active(runtime)
                try:
                    try:
                        run = runtime.run(
                            job,
                            stage_sha256=stage_pin["sha256"],
                            profile=c.runtime_profile,
                            profile_sha256=c.runtime_profile_sha256,
                        )
                    except Exception as exc:
                        self._check()
                        stop = _checksum_stop(job)
                        if stop:
                            raise ConversionError(
                                f"Replay checksum mismatch at {stop['world_time_ms']} ms; "
                                "this recording is not yet supported"
                            ) from exc
                        raise ConversionError(f"V32 simulation failed: {exc}") from exc
                finally:
                    self._clear_active(runtime)
                self._check()
                write_json(job / "simulation-result.json", run)
                encoder = V32Encoder(timeout=c.encoder_timeout)
                self._set_active(encoder)
                try:
                    try:
                        encoded = encoder.encode(
                            job,
                            run,
                            stage_sha256=stage_pin["sha256"],
                            runtime_profile=c.runtime_profile,
                            runtime_profile_sha256=c.runtime_profile_sha256,
                            encoder_config=c.encoder_config,
                            encoder_config_sha256=c.encoder_config_sha256,
                        )
                    except Exception as exc:
                        self._check()
                        raise ConversionError(f"V32 admission or encoding failed: {exc}") from exc
                finally:
                    self._clear_active(encoder)
                self._check()
                output = {
                    "status": "experimental_v32_recording_verified",
                    "recording": encoded["recording"],
                    "stage": stage_pin,
                    "worker": stage["worker"],
                    "run": run,
                    "encoding": encoded,
                    "shipping_cache_published": False,
                    "general_game_parity_verified": False,
                }
                write_json(job / "pipeline-result.json", output)
                verified = verified_recording(
                    job,
                    output,
                    runtime_profile=c.runtime_profile,
                    runtime_profile_sha256=c.runtime_profile_sha256,
                    encoder_config=c.encoder_config,
                    encoder_config_sha256=c.encoder_config_sha256,
                )
                self._check_report(Path(encoded["conversion"]["path"]), verified)
                self._check()
                if (
                    pin(replay) != input_pin
                    or self._profiles(job) != profiles
                    or any(pin(Path(row["path"])) != row for row in source_pins)
                ):
                    raise ConversionError(
                        "V32 replay, profile or backend changed during conversion"
                    )
                if verified["recording"] != encoded["recording"]:
                    raise ConversionError("V32 verified recording differs from encoder output")
                return self._publish(
                    entry,
                    identity,
                    Path(encoded["recording"]["path"]),
                    Path(encoded["conversion"]["path"]),
                    job,
                    encoded["recording"],
                    encoded["conversion"],
                )
        except ConversionCancelled:
            raise
        except ConversionError:
            raise
        except Exception as exc:
            self._check()
            raise ConversionError(f"V32 replay is unsupported or conversion failed: {exc}") from exc
