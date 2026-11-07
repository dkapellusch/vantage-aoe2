"""Run a pinned experimental V32 worker in an owned headless namespace.

This produces an unadmitted capture, not a VREC. Original checksum failures,
terminal verification and encoding remain separate gates.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import signal
import subprocess
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from vantage.native_conversion import pin


class V32RuntimeError(RuntimeError):
    """The worker did not produce an admissible capture."""


_ASSET_ORDER = (
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
_SYSTEM_ROLES = {
    "bwrap": "/usr/bin/bwrap",
    "wine": "/usr/bin/wine",
    "xvfb_run": "/usr/bin/xvfb-run",
    "xvfb": "/usr/bin/Xvfb",
    "xauth": "/usr/bin/xauth",
    "xdpyinfo": "/usr/bin/xdpyinfo",
}
_HELPER = b'#!/bin/sh\nset -eu\n/usr/bin/xdpyinfo >/dev/null\nexec "$@"\n'


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise V32RuntimeError(message)


def _verify(row: dict[Any, Any]) -> None:
    _require(
        type(row) is dict
        and set(row) == {"path", "bytes", "sha256"}
        and type(row["path"]) is str
        and type(row["bytes"]) is int
        and row["bytes"] >= 0
        and type(row["sha256"]) is str,
        "Invalid input pin",
    )
    _require(re.fullmatch(r"[0-9a-f]{64}", row["sha256"]) is not None, "Invalid input digest")
    path = Path(row["path"])
    _require(path.is_absolute() and path.resolve(strict=True) == path, "Noncanonical input")
    _require(pin(path) == row, f"Pinned input changed: {path}")


def _z(path: Path) -> str:
    return "Z:" + str(path).replace("/", "\\")


def _claim_stage(stage_dir: Path) -> None:
    """A worker may leave mutable source outputs, so a stage is single-use."""
    marker = stage_dir / ".v32-runtime-consumed"
    try:
        with marker.open("x", encoding="utf-8") as stream:
            stream.write("This staged worker may have produced mutable outputs.\n")
    except FileExistsError as error:
        raise V32RuntimeError("Staged worker is already consumed") from error
    runs = stage_dir / "runs"
    _require(
        not runs.exists() or (not runs.is_symlink() and runs.is_dir() and not any(runs.iterdir())),
        "Staged worker has previous runs and must be rebuilt",
    )


class V32Runtime:
    """One cancellable worker. Only its stored child process group is signalled."""

    def __init__(self, *, timeout: float = 1800, disk_floor_bytes: int = 5 * 1024**3):
        _require(type(timeout) in (int, float) and 0 < timeout <= 86400, "Invalid timeout")
        _require(type(disk_floor_bytes) is int and disk_floor_bytes > 0, "Invalid disk floor")
        self.timeout = timeout
        self.disk_floor_bytes = disk_floor_bytes
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

    def run(
        self, stage_dir: Path, *, stage_sha256: str, profile: Path, profile_sha256: str
    ) -> dict[Any, Any]:
        """Run a caller-pinned stage and runtime profile, preserving failure receipts."""
        with self._lock:
            _require(not self._used, "Runtime instances are single-use")
            self._used = True
        stage_dir = stage_dir.resolve(strict=True)
        stage_path = stage_dir / "stage.json"
        stage_pin = pin(stage_path)
        _require(stage_pin["sha256"] == stage_sha256, "Stage hash differs")
        stage_bytes = stage_path.read_bytes()
        _require(hashlib.sha256(stage_bytes).hexdigest() == stage_pin["sha256"], "Stage changed")
        stage = json.loads(stage_bytes)
        _require(stage.get("kind") == "vantage_experimental_v32_staged_worker", "Unsupported stage")
        source = stage_dir / "source"
        _require(
            source.resolve(strict=True) == source
            and stage.get("source_root") == str(source)
            and stage.get("runtime_source_root") == str(source),
            "Stage requires its actual source path; mount aliases are not supported",
        )
        profile = profile.resolve(strict=True)
        profile_pin = pin(profile)
        _require(profile_pin["sha256"] == profile_sha256, "Runtime profile hash differs")
        profile_bytes = profile.read_bytes()
        _require(
            hashlib.sha256(profile_bytes).hexdigest() == profile_pin["sha256"], "Profile changed"
        )
        runtime = json.loads(profile_bytes)
        _require(
            type(runtime) is dict
            and runtime.get("kind") == "vantage_experimental_v32_runtime"
            and type(runtime.get("version")) is int
            and runtime["version"] == 1,
            "Unsupported runtime profile",
        )
        _require(stage["profile"] == runtime["staging_profile"], "Staging profile differs")
        system = runtime["system"]
        _require(type(system) is dict and set(system) == set(_SYSTEM_ROLES), "Invalid system roles")
        for name, expected_path in _SYSTEM_ROLES.items():
            _verify(system[name])
            _require(
                Path(system[name]["path"]) == Path(expected_path).resolve(), "System role differs"
            )
        assets = runtime["assets"]
        fixed_names = set(_ASSET_ORDER) - {"saved_world", "original_recording"}
        _require(type(assets) is dict and set(assets) == fixed_names, "Invalid asset roles")
        technologies = runtime["technology_assets"]
        _require(type(technologies) is list and len(technologies) == 2, "Invalid technology assets")
        static_pins = [
            runtime["staging_profile"],
            runtime["raw_dat"],
            *system.values(),
            *assets.values(),
            *technologies,
        ]
        stage_pins = [
            stage["profile"],
            stage["recording"],
            stage["host"],
            stage["worker"],
            *stage["stager_sources"],
            *stage["copied_sources"],
            *stage["generated"],
        ]
        for row in static_pins + stage_pins:
            _verify(row)
        recipe = json.loads(Path(stage["profile"]["path"]).read_bytes())
        _require(stage["host"]["sha256"] == recipe["host"]["sha256"], "Staged host differs")
        _require(Path(stage["host"]["path"]) == source / "host.cpp", "Host is outside stage")
        worker = source / "vantage-native-input-derived.exe"
        _require(Path(stage["worker"]["path"]) == worker, "Worker is outside stage")
        _require(
            all(Path(row["path"]).is_relative_to(source) for row in stage["copied_sources"]),
            "Copied input is outside stage",
        )
        _require(
            {Path(row["path"]).name for row in stage["generated"]}
            == {
                "prepared_config.h",
                "entity_expectations.h",
                "input-save.inflated.bin",
                "native_input_profile.h",
                "descriptor.json",
            }
            and len(stage["generated"]) == 5,
            "Generated inputs differ",
        )
        for row in stage["generated"]:
            _require(
                Path(row["path"]).parent == stage_dir / "generated",
                "Generated input is outside stage",
            )
            actual = pin(source / Path(row["path"]).name)
            _require(
                (actual["bytes"], actual["sha256"]) == (row["bytes"], row["sha256"]),
                "Generated input differs",
            )
        raw_placeholder = source / "resources/_common/dat/empires2_x2_p1.dat"
        _require(
            raw_placeholder.is_file() and raw_placeholder.stat().st_size == 0,
            "Raw DAT placeholder differs",
        )
        for row in static_pins:
            _require(
                not Path(row["path"]).is_relative_to(stage_dir),
                "Static input overlaps writable job",
            )
        if self._cancelled.is_set():
            raise V32RuntimeError("Worker cancelled before launch")
        fs = os.statvfs(stage_dir)
        _require(fs.f_bavail * fs.f_frsize >= self.disk_floor_bytes, "Insufficient disk space")
        _claim_stage(stage_dir)
        run_dir = stage_dir / "runs" / uuid.uuid4().hex
        run_dir.mkdir(parents=True, mode=0o700, exist_ok=False)
        prefix, runtime_dir = run_dir / "prefix", run_dir / "runtime"
        prefix.mkdir(mode=0o700)
        runtime_dir.mkdir(mode=0o700)
        helper = run_dir / "display-preflight.sh"
        helper.write_bytes(_HELPER)
        paths = []
        for name in _ASSET_ORDER:
            if name == "saved_world":
                paths.append(source / "input-save.inflated.bin")
            elif name == "original_recording":
                paths.append(Path(stage["recording"]["path"]))
            else:
                paths.append(Path(assets[name]["path"]))
        paths.extend(Path(row["path"]) for row in technologies)
        wine_argv = [
            system["wine"]["path"],
            _z(worker),
            *(_z(path) for path in paths),
            stage["worker"]["sha256"],
        ]
        command = [
            system["bwrap"]["path"],
            "--die-with-parent",
            "--unshare-all",
            "--unshare-user",
            "--disable-userns",
            "--cap-drop",
            "ALL",
            "--clearenv",
            "--ro-bind",
            "/",
            "/",
            "--proc",
            "/proc",
            "--dev",
            "/dev",
            "--tmpfs",
            "/tmp",
            "--dir",
            "/tmp/.X11-unix",
            "--bind",
            str(stage_dir),
            str(stage_dir),
            "--ro-bind",
            runtime["raw_dat"]["path"],
            str(raw_placeholder),
            "--setenv",
            "HOME",
            "/tmp",
            "--setenv",
            "USER",
            "vantage-private",
            "--setenv",
            "PATH",
            "/usr/bin:/bin",
            "--setenv",
            "LANG",
            "C.UTF-8",
            "--setenv",
            "VANTAGE_NATIVE_ISOLATION",
            "private-linux-namespace-v1",
            "--setenv",
            "WINEPREFIX",
            str(prefix),
            "--setenv",
            "XDG_RUNTIME_DIR",
            str(runtime_dir),
            "--setenv",
            "WINEDEBUG",
            "-all",
            "--setenv",
            "LIBGL_ALWAYS_SOFTWARE",
            "1",
            "--setenv",
            "__EGL_VENDOR_LIBRARY_FILENAMES",
            "/usr/share/glvnd/egl_vendor.d/50_mesa.json",
            "--setenv",
            "PULSE_SERVER",
            "unix:/tmp/no-audio",
            "--setenv",
            "PIPEWIRE_REMOTE",
            "/tmp/no-audio",
            "--setenv",
            "PIPEWIRE_RUNTIME_DIR",
            "/tmp/no-audio",
            "--setenv",
            "WINEDLLOVERRIDES",
            "winemenubuilder.exe=d;mscoree,mshtml=d;winemac.drv,winewayland.drv=d;winealsa.drv,winepulse.drv=d",
            "--chdir",
            str(Path(assets["image"]["path"]).parent),
            "--",
            system["xvfb_run"]["path"],
            "-a",
            "-e",
            # xvfb-run redirects cleanup output with truncation. A separate
            # file keeps that from erasing the worker's captured stderr.
            str(run_dir / "xvfb.log"),
            "-s",
            "-screen 0 1024x768x24 -nolisten tcp -extension GLX",
            "/bin/sh",
            str(helper),
            *wine_argv,
        ]
        stdout_path, stderr_path = run_dir / "native.stdout.log", run_dir / "native.stderr.log"
        started = time.monotonic()
        reason = None
        with stdout_path.open("xb") as stdout, stderr_path.open("xb") as stderr:
            with self._lock:
                if self._cancelled.is_set():
                    raise V32RuntimeError("Worker cancelled before launch")
                child = subprocess.Popen(
                    command,
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
                    elif time.monotonic() - started >= self.timeout:
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
        receipt = {
            "receipt_kind": "ordinary_owned_subprocess",
            "exit_code": child.returncode,
            "timed_out": reason == "timeout",
            "cancelled": reason == "cancelled",
            "stop_reason": reason,
            "seconds": time.monotonic() - started,
            "stdout_sha256": pin(stdout_path)["sha256"],
            "stderr_sha256": pin(stderr_path)["sha256"],
            "stage": stage_pin,
            "runtime_profile": profile_pin,
            "private_namespace": True,
            "private_xvfb": True,
            "standard_owned_display_admission_used": False,
            "all_input_pins_unchanged": False,
        }
        # Save the observed exit even if a subsequent input check fails.
        receipt_path = run_dir / "native.process-exit.json"
        with receipt_path.open("x") as stream:
            json.dump(receipt, stream, indent=2)
            stream.write("\n")
        for row in static_pins + stage_pins:
            _verify(row)
        _require(
            pin(stage_path) == stage_pin and pin(profile) == profile_pin, "Stage or profile changed"
        )
        for row in stage["generated"]:
            actual = pin(source / Path(row["path"]).name)
            _require(
                (actual["bytes"], actual["sha256"]) == (row["bytes"], row["sha256"]),
                "Generated input changed",
            )
        _require(not self._cancelled.is_set(), "Worker cancelled")
        _require(reason is None and child.returncode == 0, f"Worker failed; see {stderr_path}")
        verified = dict(
            receipt, all_input_pins_unchanged=True, source_process_receipt=pin(receipt_path)
        )
        verified_path = run_dir / "native.verified-process-exit.json"
        with verified_path.open("x") as stream:
            json.dump(verified, stream, indent=2)
            stream.write("\n")
        return {
            "capture": pin(stdout_path),
            "receipt": pin(verified_path),
            "run_dir": str(run_dir),
            "terminal_verified": False,
            "native_compatibility_verified": False,
        }
