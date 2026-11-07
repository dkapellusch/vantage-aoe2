"""Encode an explicitly pinned, terminal-admitted V32 capture in a private job.

This is an experimental adapter to the retained V32 encoder. It does not select
compatible game assets, publish a cache, or certify ordinary-game parity.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import signal
import subprocess
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from vantage.native_conversion import pin
from vantage.native_v32_admission import admit_v32_capture
from vantage.native_v32_runtime import _verify


class V32EncodeError(RuntimeError):
    """The experimental encoder did not produce a verified recording."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise V32EncodeError(message)


def _write_new(path: Path, value: dict[Any, Any]) -> None:
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, allow_nan=False)
        stream.write("\n")


def _tracked_join_contract(config: dict[Any, Any]) -> dict[Any, Any] | None:
    """Bind the reviewed in-memory encoder substitution to its real sources."""
    runtime = config.get("experimental_runtime")
    if runtime is None:
        _require(
            Path(config["encoder"]["path"]).name != "encoder_wrapper.py",
            "The tracked-join wrapper requires an explicit runtime profile",
        )
        return None
    _require(
        type(runtime) is dict
        and set(runtime) == {"kind", "original", "candidate"}
        and runtime["kind"] == "tracked_geometry_join_v1",
        "Unsupported experimental encoder runtime",
    )
    wrapper = Path(config["encoder"]["path"])
    original, candidate = runtime["original"], runtime["candidate"]
    _verify(original)
    _verify(candidate)
    _require(
        wrapper.name == "encoder_wrapper.py"
        and Path(candidate["path"]) == wrapper.parent / "candidate.py"
        and Path(original["path"])
        == wrapper.parent.parent / "native-positive-sync-encoder-source-v3/encoder/convert.py",
        "Experimental encoder dependencies differ",
    )
    original_bytes = Path(original["path"]).read_bytes()
    _require(
        hashlib.sha256(original_bytes).hexdigest() == original["sha256"], "Original encoder changed"
    )
    source = original_bytes.decode("utf-8")
    before = "    geometry, presentation = {}, {}\n"
    after = "    geometry, presentation = TrackedGeometry(), {}\n"
    _require(source.count(before) == 1 and after not in source, "Encoder substitution differs")
    derived = source.replace(before, after, 1)
    _require(derived.replace(after, before, 1) == source, "Encoder substitution is not reversible")
    return {
        "kind": runtime["kind"],
        "wrapper": config["encoder"],
        "original": original,
        "candidate": candidate,
        "derived_source_sha256": hashlib.sha256(derived.encode("utf-8")).hexdigest(),
    }


def _verify_tracked_join_output(path: Path, contract: dict[Any, Any]) -> dict[Any, Any]:
    """Require both the wrapper's source declaration and completed verification."""
    records = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    before = [row for row in records if row.get("stage") == "incremental_join_provenance"]
    after = [row for row in records if row.get("stage") == "incremental_join_verified"]
    _require(len(before) == len(after) == 1, "Experimental encoder provenance is missing")
    _require(
        before[0].get("original_encoder_sha256") == contract["original"]["sha256"]
        and before[0].get("candidate_sha256") == contract["candidate"]["sha256"]
        and before[0].get("derived_source_sha256") == contract["derived_source_sha256"]
        and before[0].get("original_file_pin_represents_runtime_source") is False
        and before[0].get("shipping_profile_adopted") is False
        and after[0].get("candidate_sha256") == contract["candidate"]["sha256"]
        and after[0].get("inputs_unchanged") is True
        and records.index(before[0]) < records.index(after[0]),
        "Experimental encoder provenance differs",
    )
    return {"declared": before[0], "verified": after[0]}


def research_repository(config: dict[Any, Any]) -> Path:
    """The repository the pinned encoder runs in (its PYTHONPATH and working folder).

    The encoder script is a research artifact importing the development copy's
    modules; it lives in that repository's artifacts/ folder. Without that layout
    (or for an encoder of this repository) it is this package's own repository.
    """
    encoder = Path(config["encoder"]["path"])
    for folder in encoder.parents:
        if folder.name == "artifacts":
            return folder.parent
    return Path(__file__).resolve().parents[2]


def verify_encoder_config(
    encoder_config: Path, encoder_config_sha256: str, *, stage_dir: Path | None = None
) -> tuple[Any, ...]:
    """Check encoder assets and overlay bindings before spending time simulating."""
    encoder_config = encoder_config.resolve(strict=True)
    config_pin = pin(encoder_config)
    _require(config_pin["sha256"] == encoder_config_sha256, "Encoder configuration differs")
    config_bytes = encoder_config.read_bytes()
    _require(
        hashlib.sha256(config_bytes).hexdigest() == config_pin["sha256"],
        "Encoder configuration changed",
    )
    config = json.loads(config_bytes)
    _require(
        config.get("kind") == "vantage_experimental_v32_encoder"
        and type(config.get("version")) is int
        and config["version"] == 1,
        "Unsupported encoder configuration",
    )
    static_pins = [
        config["encoder"],
        config["parent_profile"],
        config["bwrap"],
        config["python_target"],
        *(o["source"] for o in config["overlays"]),
    ]
    for row in static_pins:
        _verify(row)
    tracked = _tracked_join_contract(config)
    if tracked is not None:
        static_pins.extend((tracked["original"], tracked["candidate"]))
    _require(Path(config["bwrap"]["path"]) == Path("/usr/bin/bwrap").resolve(), "Wrong sandbox")
    python_path = Path(config["python_path"])
    _require(
        python_path.is_absolute() and pin(python_path) == config["python_target"],
        "Python executable differs",
    )
    parent_bytes = Path(config["parent_profile"]["path"]).read_bytes()
    _require(
        hashlib.sha256(parent_bytes).hexdigest() == config["parent_profile"]["sha256"],
        "Encoder parent profile changed",
    )
    parent = json.loads(parent_bytes)
    contracts = [parent["source_evidence"], *parent["source_contracts"], *parent["codec_pins"]]
    desired = {row["path"]: row for row in contracts}
    overlays = []
    seen = set()
    for row in config["overlays"]:
        target = Path(row["target"])
        _require(
            target.is_absolute()
            and target.resolve(strict=True) == target
            and (stage_dir is None or not target.is_relative_to(stage_dir))
            and str(target) not in seen,
            "Invalid overlay target",
        )
        expected = desired[str(target)]
        _require(
            row["expected_sha256"] == expected["sha256"] == row["source"]["sha256"]
            and row["source"]["bytes"] == expected["bytes"],
            "Overlay source differs",
        )
        seen.add(str(target))
        overlays.append((pin(target), row["source"]))
    sources = {target["path"]: retained for target, retained in overlays}
    for row in contracts:
        if row["path"] in sources:
            retained = sources[row["path"]]
            _require(
                (retained["bytes"], retained["sha256"]) == (row["bytes"], row["sha256"]),
                "Conflicting overlay source contract",
            )
        else:
            _verify(row)
    return config_pin, config, static_pins, python_path, parent, overlays


class V32Encoder:
    """One isolated encoder; cancellation only signals its child process group."""

    def __init__(self, *, timeout: float = 1800, disk_floor_bytes: int = 5 * 1024**3):
        _require(type(timeout) in (int, float) and 0 < timeout <= 86400, "Invalid timeout")
        _require(type(disk_floor_bytes) is int and disk_floor_bytes > 0, "Invalid disk floor")
        self.timeout, self.disk_floor_bytes = timeout, disk_floor_bytes
        self._cancelled = threading.Event()
        self._lock = threading.Lock()
        self._child: subprocess.Popen[Any] | None = None
        self._used = False

    def cancel(self) -> None:
        self._cancelled.set()
        with self._lock:
            if self._child is not None and self._child.poll() is None:
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(self._child.pid, signal.SIGTERM)

    def encode(
        self,
        stage_dir: Path,
        result: dict[Any, Any],
        *,
        stage_sha256: str,
        runtime_profile: Path,
        runtime_profile_sha256: str,
        encoder_config: Path,
        encoder_config_sha256: str,
    ) -> dict[Any, Any]:
        """Admit then encode one raw capture. A nonzero exit is never success."""
        with self._lock:
            _require(not self._used, "Encoder instances are single-use")
            self._used = True
        stage_dir = stage_dir.resolve(strict=True)
        runtime_profile = runtime_profile.resolve(strict=True)
        encoder_config = encoder_config.resolve(strict=True)
        config_pin, config, static_pins, python_path, parent, overlays = verify_encoder_config(
            encoder_config, encoder_config_sha256, stage_dir=stage_dir
        )
        evidence = admit_v32_capture(
            stage_dir,
            result,
            stage_sha256=stage_sha256,
            runtime_profile=runtime_profile,
            runtime_profile_sha256=runtime_profile_sha256,
        )
        if self._cancelled.is_set():
            raise V32EncodeError("Encoder cancelled before launch")
        fs = os.statvfs(stage_dir)
        _require(fs.f_bavail * fs.f_frsize >= self.disk_floor_bytes, "Insufficient disk space")
        stage = json.loads((stage_dir / "stage.json").read_bytes())
        source = stage_dir / "source"
        profile = dict(
            parent,
            profile_id="v32-input-derived-experimental",
            own_master_host_sha256=stage["host"]["sha256"],
        )
        tracked = _tracked_join_contract(config)
        if tracked is not None:
            profile["profile_id"] = "v32-input-derived-tracked-join-experimental"
            profile["experimental_runtime"] = tracked
        filenames = {row["file"] for row in profile["functions"]} | {"native_input_profile.h"}
        _require(len(filenames) == 12, "Producer file coverage differs")
        inputs = [pin(source / name) for name in sorted(filenames)]
        # Make all output paths unique; do not overwrite a prior result.
        encode_dir = stage_dir / "encodes" / uuid.uuid4().hex
        encode_dir.mkdir(parents=True, mode=0o700, exist_ok=False)
        evidence_path, profile_path = (
            encode_dir / "terminal.json",
            encode_dir / "encoder-profile.json",
        )
        _write_new(evidence_path, evidence)
        _write_new(profile_path, profile)
        prepared = {
            "pins": inputs,
            "adapter_kind": "v32_input_derived_compiled_inputs",
            "stage_receipt": pin(stage_dir / "stage.json"),
            "capture": result["capture"],
            "terminal_receipt": result["receipt"],
            "source_profile": config["parent_profile"],
        }
        prepared_path = source / "prepared.json"
        if prepared_path.exists():
            _require(
                json.loads(prepared_path.read_bytes()) == prepared,
                "Prepared bundle already differs",
            )
        else:
            _write_new(prepared_path, prepared)
        capture, receipt = Path(result["capture"]["path"]), Path(result["receipt"]["path"])
        descriptor, saved = source / "descriptor.json", source / "input-save.inflated.bin"
        dynamic_pins = [
            pin(prepared_path),
            pin(evidence_path),
            pin(profile_path),
            pin(stage_dir / "stage.json"),
            pin(capture),
            pin(receipt),
            pin(descriptor),
            pin(saved),
            pin(Path(__file__).resolve()),
        ]
        args = [
            str(python_path),
            "-B",
            "-P",
            config["encoder"]["path"],
            "--confirmed-terminal",
            "--capture",
            str(capture),
            "--receipt",
            str(receipt),
            "--receipt-sha",
            pin(receipt)["sha256"],
            "--descriptor",
            str(descriptor),
            "--descriptor-sha",
            pin(descriptor)["sha256"],
            "--saved-world",
            str(saved),
            "--profile",
            str(profile_path),
            "--profile-sha",
            pin(profile_path)["sha256"],
            "--producer-bundle",
            str(source),
            "--out",
            str(encode_dir / "encoded"),
            "--expected-frames",
            str(evidence["expected_frames"]),
            "--expected-end-ms",
            str(evidence["expected_end_ms"]),
            "--terminal-evidence",
            str(evidence_path),
            "--terminal-evidence-sha",
            pin(evidence_path)["sha256"],
        ]
        root = research_repository(config)
        command = [
            config["bwrap"]["path"],
            "--die-with-parent",
            "--unshare-all",
            "--ro-bind",
            "/",
            "/",
            "--proc",
            "/proc",
            "--dev",
            "/dev",
            "--bind",
            str(stage_dir),
            str(stage_dir),
        ]
        for target, retained in overlays:
            command += ["--ro-bind", retained["path"], target["path"]]
        command += ["--chdir", str(root), "--", *args]
        env = {
            "PATH": "/usr/bin:/bin",
            "LANG": "C.UTF-8",
            "PYTHONPATH": str(root),
            "PYTHONDONTWRITEBYTECODE": "1",
        }
        start, reason = time.monotonic(), None
        stdout_path, stderr_path = encode_dir / "encode.stdout", encode_dir / "encode.stderr"
        with stdout_path.open("xb") as stdout, stderr_path.open("xb") as stderr:
            with self._lock:
                if self._cancelled.is_set():
                    raise V32EncodeError("Encoder cancelled before launch")
                child = subprocess.Popen(
                    command,
                    cwd=root,
                    env=env,
                    stdin=subprocess.DEVNULL,
                    stdout=stdout,
                    stderr=stderr,
                    start_new_session=True,
                )
                self._child = child
            try:
                while child.poll() is None:
                    fs = os.statvfs(stage_dir)
                    if self._cancelled.is_set():
                        reason = "cancelled"
                    elif fs.f_bavail * fs.f_frsize < self.disk_floor_bytes:
                        reason = "disk_guard"
                    elif time.monotonic() - start >= self.timeout:
                        reason = "timeout"
                    if reason:
                        with contextlib.suppress(ProcessLookupError):
                            os.killpg(child.pid, signal.SIGTERM)
                        try:
                            child.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            with contextlib.suppress(ProcessLookupError):
                                os.killpg(child.pid, signal.SIGKILL)
                            child.wait()
                        break
                    self._cancelled.wait(0.25)
            except BaseException:
                if child.poll() is None:
                    with contextlib.suppress(ProcessLookupError):
                        os.killpg(child.pid, signal.SIGKILL)
                    child.wait()
                raise
            finally:
                with self._lock:
                    self._child = None
        if self._cancelled.is_set() and reason is None:
            reason = "cancelled"
        process = {
            "exit_code": child.returncode,
            "stop_reason": reason,
            "seconds": time.monotonic() - start,
            "stdout": pin(stdout_path),
            "stderr": pin(stderr_path),
            "terminal": pin(evidence_path),
            "config": config_pin,
            "overlay_targets_before": [x[0] for x in overlays],
        }
        process_path = encode_dir / "encoder.process-exit.json"
        _write_new(process_path, process)
        for row in static_pins + inputs + dynamic_pins:
            _verify(row)
        _require(
            pin(encoder_config) == config_pin and pin(python_path) == config["python_target"],
            "Encoder configuration or Python changed",
        )
        for target, retained in overlays:
            _require(
                pin(Path(target["path"])) == target and pin(Path(retained["path"])) == retained,
                "Overlay changed",
            )
        _require(reason is None and child.returncode == 0, f"Encoder failed; see {stderr_path}")
        tracked_evidence = _verify_tracked_join_output(stdout_path, tracked) if tracked else None
        output = encode_dir / "encoded"
        report_path, recording = output / "conversion.json", output / "recording.vrec"
        report = json.loads(report_path.read_bytes())
        _require(
            report.get("status") == "conversion_verified"
            and report.get("recording") == pin(recording)
            and report.get("capture_frames") == evidence["expected_frames"]
            and report.get("capture_end_ms") == evidence["expected_end_ms"]
            and report.get("all_serialized_Frame_bytes_readback_digest_checked") is True,
            "Encoder readback contract rejected",
        )
        return {
            "recording": pin(recording),
            "conversion": pin(report_path),
            "terminal": pin(evidence_path),
            "process_receipt": pin(process_path),
            "encoder_config": config_pin,
            "experimental_runtime": tracked_evidence,
            "native_compatibility_verified": False,
            "shipping_cache_published": False,
        }
