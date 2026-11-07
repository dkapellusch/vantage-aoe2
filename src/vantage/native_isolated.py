"""Isolated local replay conversion (Bubblewrap), for vantage-native.py.

Ported from the development copy's research launcher
(artifacts/.../native-isolated-session-v1/isolated_converter.py, whose pinned
original stays with the artifacts). Differences: imports name ``vantage``, and
the sandboxed child gets this package's source folder (src/) on its path.
"""

import contextlib
import hashlib
import json
import os
import shutil
import signal
import subprocess
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from vantage import native_conversion
from vantage.native_conversion import (
    ConversionCancelled,
    ConversionError,
    checked_cache,
    load_profile,
    pin,
)
from vantage.replay_stream import ReplayStreamError, iter_replay_operations

_CHILD = """from pathlib import Path
import json,sys
from vantage.native_conversion import NativeConversion
c=NativeConversion(Path(sys.argv[1]),sys.argv[2],Path(sys.argv[3]),timeout=float(sys.argv[5]))
result=c.convert(Path(sys.argv[4]))
print(json.dumps({'output':str(result)}),flush=True)
"""


def has_recorded_taunt(replay: Any, cancelled: Any = None) -> Any:
    """Recognize structured taunts without treating ordinary chat as a taunt.

    Unknown or malformed records keep the existing profile selection; the
    native converter remains responsible for validating the replay itself.
    """
    try:
        for operation in iter_replay_operations(replay):
            if cancelled is not None and cancelled.is_set():
                raise ConversionCancelled("isolated conversion cancelled")
            if operation.kind != "chat" or operation.payload[:4] != b"\xff" * 4:
                continue
            try:
                chat = json.loads(operation.payload[4:])
            except (ValueError, UnicodeDecodeError, RecursionError):
                continue
            if (
                isinstance(chat, dict)
                and type(chat.get("tauntNumber")) is int
                and chat["tauntNumber"] > 0
            ):
                return True
    except ReplayStreamError:
        return False
    return False


class IsolatedConversion:
    """A single cancellable converter; only its own Bubblewrap group is signalled."""

    def __init__(
        self, config: Any, *, minimum_free_bytes: Any = 4 * 1024**3, taunt_profile: Any = None
    ) -> None:
        self.config = config
        self.minimum_free_bytes = minimum_free_bytes
        self.taunt_profile = taunt_profile
        self.cancelled = threading.Event()
        self.lock = threading.Lock()
        self.child: Any = None

    @staticmethod
    def _signal(child: Any, sig: Any) -> None:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(child.pid, sig)

    def cancel(self) -> None:
        self.cancelled.set()
        with self.lock:
            if self.child is not None and self.child.poll() is None:
                self._signal(self.child, signal.SIGTERM)

    def convert(self, replay: Any) -> Any:
        if self.cancelled.is_set():
            raise ConversionCancelled("isolated conversion cancelled")
        replay = Path(replay).resolve(strict=True)
        if replay.suffix.lower() != ".aoe2record":
            raise ConversionError("Expected an .aoe2record input")
        replay_pin = pin(replay)
        profile_path, profile_sha256 = self.config.profile, self.config.profile_sha256
        if self.taunt_profile is not None:
            has_taunt = has_recorded_taunt(replay, self.cancelled)
            if pin(replay) != replay_pin:
                raise ConversionError("replay changed while choosing its native profile")
            if self.cancelled.is_set():
                raise ConversionCancelled("isolated conversion cancelled")
            if has_taunt:
                profile_path, profile_sha256 = self.taunt_profile
        profile, profile_pin = load_profile(profile_path, profile_sha256)
        cache = self.config.cache_dir
        cache.mkdir(parents=True, exist_ok=True)
        repo = Path(native_conversion.__file__).resolve().parents[2]
        source = Path(native_conversion.__file__).resolve().parents[1]  # src/: the package
        targets: tuple[Any, ...] = (
            repo,
            replay,
            self.config.profile,
            profile_path,
            Path(profile["prefix"]),
            Path(profile["runtime"]),
            Path("/usr"),
            Path("/etc"),
            Path("/var"),
        )
        if self.taunt_profile is not None:
            targets += (self.taunt_profile[0],)
        if cache.resolve() != cache or any(path.is_relative_to(cache) for path in targets):
            raise ConversionError("cache directory overlaps a protected input or system directory")
        if any(cache.is_relative_to(Path(profile[key])) for key in ("prefix", "runtime")):
            raise ConversionError("cache directory overlaps the private Wine mount targets")
        identity = dict(
            input_sha256=replay_pin["sha256"],
            profile_sha256=profile_pin["sha256"],
            engine=profile["engine_sha256"],
            encoder=profile["encoder"]["sha256"],
            capabilities=profile["capabilities"],
            backend_version=1,
        )
        key = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
        entry = cache / "entries" / key
        if entry.exists() or entry.is_symlink():
            # A committed, immutable cache entry needs neither a Wine prefix nor
            # the free disk reserve required to produce a new recording. Preserve
            # the native backend's source, identity, marker and content checks.
            native_conversion.verify_pins(profile["pins"] + [profile_pin, replay_pin])
            result = checked_cache(entry, identity)
            if self.cancelled.is_set():
                raise ConversionCancelled("isolated conversion cancelled")
            return result
        if shutil.disk_usage(cache).free < self.minimum_free_bytes:
            raise ConversionError("insufficient free space for isolated conversion")
        sandbox = cache / "isolated-jobs" / uuid.uuid4().hex
        sandbox.mkdir(parents=True, mode=0o700)
        prefix, runtime = sandbox / "prefix", sandbox / "runtime"
        prefix.mkdir(mode=0o700)
        runtime.mkdir(mode=0o700)
        lock = sandbox / "conversion.lock"
        lock.touch(mode=0o600, exist_ok=False)
        original_lock = Path(profile["prefix"]).parent / ".vantage-native-conversion.lock"
        if not original_lock.is_file() or original_lock.is_symlink():
            raise ConversionError("private converter lock mount target is missing")
        bwrap = Path("/usr/bin/bwrap")
        if not bwrap.is_file():
            raise ConversionError("Bubblewrap is required for isolated native playback")
        cmd = [
            str(bwrap),
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
            "--tmpfs",
            "/run",
            "--bind",
            str(prefix),
            profile["prefix"],
            "--bind",
            str(runtime),
            profile["runtime"],
            "--bind",
            str(lock),
            str(original_lock),
            "--bind",
            str(cache),
            str(cache),
            "--chdir",
            str(repo),
            "--setenv",
            "HOME",
            "/tmp",
            "--setenv",
            "USER",
            "sdk-worker",
            "--setenv",
            "LOGNAME",
            "sdk-worker",
            "--setenv",
            "PATH",
            "/usr/bin:/bin",
            "--setenv",
            "LANG",
            "C.UTF-8",
            "--setenv",
            "PYTHONPATH",
            str(source),
            "--setenv",
            "PULSE_SERVER",
            "unix:/tmp/no-audio",
            "--setenv",
            "PIPEWIRE_REMOTE",
            "/tmp/no-audio",
            "--setenv",
            "PIPEWIRE_RUNTIME_DIR",
            "/tmp/no-audio",
            "--",
            "/usr/bin/python3",
            "-B",
            "-P",
            "-c",
            _CHILD,
            str(profile_path),
            profile_sha256,
            str(cache),
            str(replay),
            str(self.config.timeout),
        ]
        stdout, stderr = sandbox / "stdout.log", sandbox / "stderr.log"
        with stdout.open("xb") as out, stderr.open("xb") as err:
            with self.lock:
                if self.cancelled.is_set():
                    raise ConversionCancelled("isolated conversion cancelled")
                child = subprocess.Popen(
                    cmd,
                    cwd=repo,
                    stdin=subprocess.DEVNULL,
                    stdout=out,
                    stderr=err,
                    start_new_session=True,
                )
                self.child = child
            reason = None
            started = time.monotonic()
            try:
                while child.poll() is None:
                    if self.cancelled.is_set():
                        reason = "cancelled"
                    elif shutil.disk_usage(cache).free < self.minimum_free_bytes:
                        reason = "disk"
                    elif time.monotonic() - started > self.config.timeout * 4 + 120:
                        reason = "timeout"
                    if reason:
                        self._signal(child, signal.SIGTERM)
                        try:
                            child.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            self._signal(child, signal.SIGKILL)
                            child.wait()
                        break
                    self.cancelled.wait(0.25)
            except BaseException:
                self._signal(child, signal.SIGKILL)
                child.wait()
                raise
            finally:
                with self.lock:
                    self.child = None
        if reason == "cancelled" or self.cancelled.is_set():
            raise ConversionCancelled("isolated conversion cancelled")
        if reason == "disk":
            raise ConversionError("isolated conversion stopped: insufficient free space")
        if reason == "timeout":
            raise ConversionError("isolated conversion exceeded its total time limit")
        if child.returncode != 0:
            raise ConversionError(
                f"isolated converter failed (exit={child.returncode}); see {stderr}"
            )
        if pin(replay) != replay_pin or pin(profile_path) != profile_pin:
            raise ConversionError("replay or profile changed during conversion")
        try:
            if stdout.stat().st_size > 65536:
                raise ValueError("oversized converter result")
            output = json.loads(stdout.read_text())["output"]
            result = Path(output).resolve(strict=True)
        except (OSError, ValueError, KeyError, TypeError) as error:
            raise ConversionError("isolated converter returned an invalid result") from error
        if result.name != "recording.vrec" or result.parent.parent != cache / "entries":
            raise ConversionError("isolated converter returned a path outside its cache")
        return checked_cache(result.parent, identity)
