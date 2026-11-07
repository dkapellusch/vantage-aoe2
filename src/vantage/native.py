"""Recording-only client for an explicitly imported experimental native worker.

The worker retains replay-family selection, simulation and original admission.
This module does not import a game SDK or the research repository. A configured
command must implement native_engine_convert's version 1 file-result contract.
"""

from __future__ import annotations

import contextlib
import gzip
import hashlib
import json
import os
import re
import signal
import struct
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from vantage.replay import read_replay

PROTOCOL = 1
CAPTURE_PROTOCOL = "v32-streams-1"
FAMILY_KEYS = {
    "build",
    "save_version",
    "options_version",
    "dataset_id",
    "game_mode",
    "selected_content_mode",
}
FINAL = {"ready", "failed", "cancelled"}


class NativeError(ValueError):
    """The imported engine or this replay cannot be used."""


def require(condition: Any, message: str) -> None:
    if not condition:
        raise NativeError(message)


def file_pin(path: Path) -> dict[str, Any]:
    path = path.resolve(strict=True)
    before = path.stat()
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    after = path.stat()
    require(
        (before.st_ino, before.st_size, before.st_mtime_ns)
        == (after.st_ino, after.st_size, after.st_mtime_ns),
        "A conversion input changed",
    )
    return {"path": str(path), "bytes": after.st_size, "sha256": digest.hexdigest()}


def pin_shape(value: Any) -> Path:
    require(
        type(value) is dict and set(value) == {"path", "bytes", "sha256"},
        "Invalid native worker file identity",
    )
    require(
        type(value["path"]) is str
        and Path(value["path"]).is_absolute()
        and type(value["bytes"]) is int
        and value["bytes"] >= 0
        and type(value["sha256"]) is str
        and re.fullmatch("[0-9a-f]{64}", value["sha256"]),
        "Invalid native worker file identity",
    )
    return Path(value["path"])


def check_pin(value: Any) -> Path:
    path = pin_shape(value)
    require(file_pin(path) == value, "A native worker file changed: " + str(path))
    return path


def read_json(path: Path, maximum: int = 2 * 1024 * 1024) -> Any:
    with path.open("rb") as stream:
        raw = stream.read(maximum + 1)
    require(len(raw) <= maximum, "Native worker metadata is too large")
    return decode_json(raw)


def decode_json(raw: bytes) -> Any:

    def unique(rows: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in rows:
            require(key not in result, "Duplicate native worker metadata key")
            result[key] = value
        return result

    def invalid(_value: str) -> Any:
        raise NativeError("Nonfinite native worker metadata")

    return json.loads(raw, object_pairs_hook=unique, parse_constant=invalid)


def recording_header(path: Path) -> dict[str, Any]:
    from vantage.frames import MAGIC

    with gzip.open(path, "rb") as stream:
        require(stream.read(len(MAGIC)) == MAGIC, "Native worker did not produce a VREC")
        size = stream.read(4)
        require(len(size) == 4, "Native recording header is truncated")
        length = struct.unpack("<I", size)[0]
        require(length <= 2 * 1024 * 1024, "Native recording header is too large")
        raw = stream.read(length)
        require(len(raw) == length, "Native recording header is truncated")
    value = decode_json(raw)
    require(type(value) is dict, "Native recording header is invalid")
    header: dict[str, Any] = value
    return header


class NativeWorker:
    """An explicit local command, pinned registry and its experimental scope."""

    def __init__(self, descriptor: Path, expected_sha256: str):
        require(hasattr(os, "sched_getaffinity"), "This native engine runtime requires Linux")
        self.descriptor = file_pin(descriptor)
        require(self.descriptor["sha256"] == expected_sha256, "Native worker descriptor changed")
        document = read_json(descriptor)
        require(
            type(document) is dict
            and document.get("kind") == "vantage_native_worker_client"
            and type(document.get("version")) is int
            and document["version"] == 1,
            "Unsupported native worker descriptor",
        )
        self.command = document.get("command")
        require(
            type(self.command) is list
            and self.command
            and all(type(word) is str and word and "\0" not in word for word in self.command)
            and Path(self.command[0]).is_absolute(),
            "Native worker needs an explicit command",
        )
        self.inputs = document.get("inputs")
        require(type(self.inputs) is list and self.inputs, "Native worker inputs must be pinned")
        for row in self.inputs:
            check_pin(row)
        require(
            len({row["path"] for row in self.inputs}) == len(self.inputs),
            "Native worker input identities are ambiguous",
        )
        require(
            str(Path(self.command[0]).resolve(strict=True)) in {row["path"] for row in self.inputs},
            "Native worker executable is not pinned",
        )
        pinned_paths = {row["path"] for row in self.inputs}
        for word in self.command:
            path = Path(word)
            if path.is_absolute() and path.is_file():
                require(
                    str(path.resolve(strict=True)) in pinned_paths,
                    "Native worker command file is not pinned: " + word,
                )
        self.registry_pin = document.get("registry")
        registry = read_json(check_pin(self.registry_pin))
        require(
            type(registry) is dict
            and registry.get("kind") == "vantage_native_engine_registry"
            and type(registry.get("version")) is int
            and registry["version"] == 1,
            "Unsupported native engine registry",
        )
        engines = registry.get("engines")
        require(type(engines) is list and engines, "The native registry has no engines")
        self.engines: dict[str, dict[str, Any]] = {}
        for engine in engines:
            require(
                type(engine) is dict
                and type(engine.get("engine_id")) is str
                and re.fullmatch("[0-9a-f]{64}", engine["engine_id"])
                and engine["engine_id"] not in self.engines
                and type(engine.get("protocol_version")) is int
                and engine["protocol_version"] == PROTOCOL
                and engine.get("backend") == "v32-sdk-1"
                and engine.get("capture_protocol") == CAPTURE_PROTOCOL
                and engine.get("qualification") == "experimental",
                "Unsupported engine contract",
            )
            families = engine.get("families")
            require(
                type(families) is list
                and families
                and all(
                    type(row) is dict
                    and set(row) == FAMILY_KEYS
                    and all(type(value) is int for value in row.values())
                    for row in families
                ),
                "Native engine needs exact replay families",
            )
            caps = engine.get("capabilities")
            require(
                type(caps) is list
                and "world_frames" in caps
                and all(type(cap) is str and cap for cap in caps)
                and caps == sorted(set(caps)),
                "Native engine cannot produce viewer frames",
            )
            require(
                type(engine.get("profiles")) is dict
                and set(engine["profiles"]) == {"source", "runtime", "encoder"},
                "Native engine profile identities are missing",
            )
            for row in engine["profiles"].values():
                pin_shape(row)  # Logical package aliases need not exist on the viewer's host.
                require(row["bytes"] > 0, "Native engine profile is empty")
            identity = {
                key: engine[key]
                for key in (
                    "protocol_version",
                    "capture_protocol",
                    "backend",
                    "qualification",
                    "families",
                    "capabilities",
                )
            }
            identity["profiles"] = {
                key: {name: row[name] for name in ("bytes", "sha256")}
                for key, row in engine["profiles"].items()
            }
            require(
                hashlib.sha256(
                    json.dumps(
                        identity, sort_keys=True, separators=(",", ":"), allow_nan=False
                    ).encode()
                ).hexdigest()
                == engine["engine_id"],
                "Native engine contract identity differs",
            )
            self.engines[engine["engine_id"]] = engine
        self.runtime_timeout = document.get("runtime_timeout_seconds", 3600)
        self.encoder_timeout = document.get("encoder_timeout_seconds", 3600)
        self.timeout = document.get("timeout_seconds", 7500)
        require(
            all(
                type(value) is int and 0 < value <= 86400
                for value in (self.runtime_timeout, self.encoder_timeout, self.timeout)
            ),
            "Invalid native worker time limit",
        )
        self.verify()

    def verify(self) -> None:
        check_pin(self.descriptor)
        check_pin(self.registry_pin)
        for row in self.inputs:
            check_pin(row)

    def describe(self) -> dict[str, Any]:
        return {
            "available": True,
            "experimental": True,
            "builds": sorted(
                {row["build"] for engine in self.engines.values() for row in engine["families"]}
            ),
            "capabilities": ["world_frames"],
            "maximum_cpus": 1,
        }


class NativeJobs:
    """One owned conversion at a time; cancellation never publishes a ready path."""

    def __init__(self, worker: NativeWorker, cache: Path):
        self.worker = worker
        self.cache = cache.resolve()
        self.cache.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._jobs: dict[str, dict[str, Any]] = {}
        self._threads: dict[str, threading.Thread] = {}
        self._cancel: dict[str, threading.Event] = {}

    def describe(self) -> dict[str, Any]:
        return self.worker.describe()

    def start(self, replay: str, *, experimental: bool = False) -> dict[str, Any]:
        require(experimental is True, "This engine requires experimental opt-in")
        path = Path(replay).expanduser().resolve(strict=True)
        header = read_replay(path, with_duration=False)
        require(
            header.build in self.worker.describe()["builds"],
            f"No imported engine supports replay build {header.build}",
        )
        self.worker.verify()
        replay_pin = file_pin(path)
        require(
            read_replay(path, with_duration=False).build == header.build
            and file_pin(path) == replay_pin,
            "Replay changed during identification",
        )
        with self._lock:
            require(
                not any(job["status"] not in FINAL for job in self._jobs.values()),
                "A replay conversion is already running",
            )
            job_id = uuid.uuid4().hex
            folder = self.cache / "client-jobs" / job_id
            folder.mkdir(parents=True)
            self._jobs[job_id] = {
                "id": job_id,
                "status": "queued",
                "phase": "Queued",
                "replay": str(path),
                "build": header.build,
                "experimental": True,
                "started": time.time(),
                "elapsed_seconds": 0,
                "message": None,
                "recording": None,
                "complete_match": None,
                "frames": None,
                "end_ms": None,
            }
            self._cancel[job_id] = threading.Event()
            thread = threading.Thread(
                target=self._run,
                args=(job_id, folder, replay_pin),
                name="vantage-native-conversion",
                daemon=True,
            )
            self._threads[job_id] = thread
            thread.start()
        return self.get(job_id)

    def get(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            require(job_id in self._jobs, "Unknown replay conversion")
            result = dict(self._jobs[job_id])
        if result["status"] not in FINAL:
            result["elapsed_seconds"] = round(time.time() - result["started"], 1)
        return result

    def cancel(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            require(job_id in self._jobs, "Unknown replay conversion")
            if self._jobs[job_id]["status"] not in FINAL:
                self._cancel[job_id].set()
                self._jobs[job_id]["phase"] = "Cancelling"
        return self.get(job_id)

    def close(self) -> None:
        with self._lock:
            for event in self._cancel.values():
                event.set()
            threads = list(self._threads.values())
        for thread in threads:
            thread.join(timeout=12)

    def ready_path(self, job_id: str) -> Path:
        job = self.get(job_id)
        require(job["status"] == "ready" and job["recording"], "Conversion is not ready")
        return check_pin(job["recording"])

    def _update(self, job_id: str, **values: Any) -> None:
        with self._lock:
            self._jobs[job_id].update(values)

    def _ready(self, value: Any, replay: dict[str, Any], build: int) -> dict[str, Any]:
        require(
            type(value) is dict
            and type(value.get("protocol_version")) is int
            and value["protocol_version"] == PROTOCOL
            and value.get("capture_protocol") == CAPTURE_PROTOCOL,
            "Native worker protocol differs",
        )
        require(
            value.get("status") == "ready", str(value.get("message") or "Replay conversion failed")
        )
        engine = self.worker.engines.get(value.get("engine_id"))
        require(engine is not None, "Native worker selected an unlisted engine")
        assert engine is not None  # require() raised otherwise; narrows the type
        identity = value.get("replay")
        require(
            type(identity) is dict
            and set(identity) == FAMILY_KEYS | {"sha256", "bytes"}
            and all(type(identity[key]) is int for key in FAMILY_KEYS | {"bytes"})
            and identity["sha256"] == replay["sha256"]
            and identity["bytes"] == replay["bytes"]
            and identity["build"] == build
            and {key: identity[key] for key in FAMILY_KEYS} in engine["families"],
            "Converted replay identity differs",
        )
        require(
            type(value.get("capabilities")) is list
            and "world_frames" in value["capabilities"]
            and set(value["capabilities"]) <= set(engine["capabilities"]),
            "Native worker capabilities differ",
        )
        for key in ("recording", "conversion_report"):
            row = value.get(key)
            require(
                type(row) is dict and type(row.get("path")) is str,
                "Native worker omitted accepted output provenance",
            )
            require(
                Path(row["path"]).resolve(strict=True).is_relative_to(self.cache),
                "Native worker output is outside its conversion cache",
            )
            check_pin(row)
        report_pin = value["conversion_report"]
        report = read_json(Path(report_pin["path"]))
        require(
            report.get("status") == "conversion_verified"
            and report.get("recording_end_reason") in {"native_game_end", "recording_eof"}
            and type(report.get("game_ended")) is bool
            and report["game_ended"] == (report["recording_end_reason"] == "native_game_end"),
            "Recording has no admitted terminal outcome",
        )
        require(
            type(report.get("capture_frames")) is int
            and report["capture_frames"] > 0
            and type(report.get("capture_end_ms")) is int
            and report["capture_end_ms"] >= 0
            and report.get("all_serialized_Frame_bytes_readback_digest_checked") is True
            and report.get("recording_ingestion_complete") is True,
            "Recording readback admission is incomplete",
        )
        header = recording_header(Path(value["recording"]["path"]))
        require(
            type(header.get("expected_frames")) is int
            and header["expected_frames"] == report["capture_frames"]
            and type(header.get("end_ms")) is int
            and header["end_ms"] == report["capture_end_ms"]
            and header.get("recording_end_reason") == report["recording_end_reason"]
            and type(header.get("observed_worker_exit_code")) is int
            and header["observed_worker_exit_code"] == 0
            and header.get("observed_timeout") is False,
            "Recording header differs from original admission",
        )
        original = report.get("recording", {})
        require(
            all(original.get(key) == value["recording"][key] for key in ("bytes", "sha256")),
            "Recording differs from its original admission",
        )
        receipt = report.get("native_receipt_preserved", {})
        require(
            receipt.get("receipt_kind") == "ordinary_owned_subprocess"
            and type(receipt.get("exit_code")) is int
            and receipt["exit_code"] == 0
            and receipt.get("timed_out") is False
            and receipt.get("cancelled") is False
            and receipt.get("private_namespace") is True
            and receipt.get("private_xvfb") is True
            and receipt.get("all_input_pins_unchanged") is True
            and receipt.get("runtime_profile") == engine["profiles"]["runtime"],
            "Original native process admission is incomplete",
        )
        terminal = report.get("terminal_evidence", {})
        require(
            type(terminal.get("expected_frames")) is int
            and type(terminal.get("expected_end_ms")) is int
            and terminal.get("expected_frames") == report["capture_frames"]
            and terminal.get("expected_end_ms") == report["capture_end_ms"]
            and terminal.get("game_ended") is report["game_ended"]
            and terminal.get("recording_end_reason") == report["recording_end_reason"]
            and type(terminal.get("native_terminal_state", {}).get("checksum_ignore_global")) is int
            and terminal.get("native_terminal_state", {}).get("checksum_ignore_global") == 0,
            "Original checksum or terminal evidence differs",
        )
        if report["game_ended"]:
            event = terminal.get("original_terminal_event", {})
            require(
                type(event.get("returned_status")) is int
                and event["returned_status"] == 1
                and type(event.get("world_status")) is int
                and event["world_status"] == 1
                and type(event.get("checksum_ignore_global")) is int
                and event["checksum_ignore_global"] == 0
                and event.get("host_native_status_write") is False,
                "Native game end was not admitted by the original engine",
            )
        check_pin(report_pin)
        return {
            "recording": value["recording"],
            "complete_match": report["game_ended"],
            "frames": report["capture_frames"],
            "end_ms": report["capture_end_ms"],
        }

    def _run(self, job_id: str, folder: Path, replay: dict[str, Any]) -> None:
        cancel = self._cancel[job_id]
        result_path = folder / "result.json"
        command = [
            sys.executable,
            "-I",
            "-S",
            "-B",
            str(Path(__file__).with_name("native_process.py")),
            "--",
            *self.worker.command,
            "--registry",
            self.worker.registry_pin["path"],
            "--registry-sha256",
            self.worker.registry_pin["sha256"],
            "--replay",
            replay["path"],
            "--cache-dir",
            str(self.cache),
            "--output",
            str(result_path),
            "--experimental",
            "--require-capability",
            "world_frames",
            "--runtime-timeout",
            str(self.worker.runtime_timeout),
            "--encoder-timeout",
            str(self.worker.encoder_timeout),
        ]
        process = None
        try:
            self.worker.verify()
            require(file_pin(Path(replay["path"])) == replay, "Replay changed before conversion")
            if cancel.is_set():
                self._update(job_id, status="cancelled", phase="Cancelled")
                return
            self._update(job_id, status="running", phase="Converting replay")
            (folder / "request.json").write_text(
                json.dumps(
                    {
                        "command": command,
                        "replay": replay,
                        "worker": self.worker.descriptor,
                        "maximum_cpus": 1,
                        "nice": 19,
                    },
                    indent=2,
                )
                + "\n"
            )
            with (
                (folder / "stdout.log").open("xb") as stdout,
                (folder / "stderr.log").open("xb") as stderr,
            ):
                process = subprocess.Popen(
                    command,
                    stdin=subprocess.DEVNULL,
                    stdout=stdout,
                    stderr=stderr,
                    start_new_session=True,
                )
                (folder / "process-start.json").write_text(
                    json.dumps({"pid": process.pid, "pgid": process.pid, "command": command}) + "\n"
                )
                deadline = time.monotonic() + self.worker.timeout
                signalled = None
                timed_out = False
                while process.poll() is None:
                    if cancel.is_set() or time.monotonic() >= deadline:
                        timed_out = not cancel.is_set()
                        if signalled is None:
                            with contextlib.suppress(ProcessLookupError):
                                os.killpg(process.pid, signal.SIGINT)
                            signalled = time.monotonic()
                        elif time.monotonic() - signalled >= 8:
                            with contextlib.suppress(ProcessLookupError):
                                os.killpg(process.pid, signal.SIGKILL)
                    time.sleep(0.05)
                (folder / "process-exit.json").write_text(
                    json.dumps(
                        {
                            "exit_code": process.returncode,
                            "timed_out": timed_out,
                            "cancel_requested": cancel.is_set(),
                        }
                    )
                    + "\n"
                )
            if cancel.is_set():
                self._update(job_id, status="cancelled", phase="Cancelled")
                return
            require(not timed_out, "Replay conversion timed out")
            require(result_path.is_file(), "Native worker did not return a conversion result")
            value = read_json(result_path)
            if value.get("status") == "cancelled":
                self._update(job_id, status="cancelled", phase="Cancelled")
                return
            require(
                process.returncode == 0, str(value.get("message") or "Replay conversion failed")
            )
            self._update(job_id, phase="Checking accepted recording")
            accepted = self._ready(value, replay, self.get(job_id)["build"])
            self.worker.verify()
            require(file_pin(Path(replay["path"])) == replay, "Replay changed during conversion")
            with self._lock:
                if cancel.is_set():
                    self._jobs[job_id].update(status="cancelled", phase="Cancelled")
                else:
                    self._jobs[job_id].update(status="ready", phase="Ready", **accepted)
        except Exception as exc:
            self._update(
                job_id,
                status="cancelled" if cancel.is_set() else "failed",
                phase="Cancelled" if cancel.is_set() else "Failed",
                message=str(exc),
                recording=None,
            )
        finally:
            if process is not None and process.poll() is None:
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(process.pid, signal.SIGKILL)
                process.wait()
            with self._lock:
                job = self._jobs[job_id]
                job["elapsed_seconds"] = round(time.time() - job["started"], 1)
