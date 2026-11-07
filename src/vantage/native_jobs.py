"""Artifact-only asynchronous coordinator around the frozen local converter."""

from __future__ import annotations

import re
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any

from vantage.native_conversion import ConversionCancelled, NativeConversion

if TYPE_CHECKING:
    from collections.abc import Callable
    from typing import TYPE_CHECKING

    from vantage.native_session import SessionPort


@dataclass(frozen=True)
class NativeConfig:
    profile: Path
    profile_sha256: str
    cache_dir: Path
    replay_roots: tuple[Path, ...]
    timeout: float = 900

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[0-9a-f]{64}", self.profile_sha256):
            raise ValueError("explicit native profile SHA required")
        profile = self.profile.expanduser().resolve(strict=True)
        if not profile.is_file() or not 0 < self.timeout <= 86400:
            raise ValueError("invalid native profile/timeout")
        roots = tuple(root.expanduser().resolve(strict=True) for root in self.replay_roots)
        if any(not root.is_dir() for root in roots) or len(set(roots)) != len(roots):
            raise ValueError("native replay roots must be distinct configured directories")
        object.__setattr__(self, "profile", profile)
        object.__setattr__(self, "cache_dir", self.cache_dir.expanduser().resolve())
        object.__setattr__(self, "replay_roots", roots)

    def converter(self) -> Any:
        # This is the only backend. Errors never enter a live/game/launcher path.
        return NativeConversion(
            self.profile, self.profile_sha256, self.cache_dir, timeout=self.timeout
        )


def http_replay(config: NativeConfig, name: str, directory: str | None) -> Path:
    """HTTP may select only relative files in explicit configured roots."""
    if not isinstance(name, str) or not name or any(c in name for c in ("\\", "\0", ":")):
        raise ValueError("invalid replay name")
    relative = PurePosixPath(name)
    if relative.is_absolute() or ".." in relative.parts or relative.suffix.lower() != ".aoe2record":
        raise ValueError("expected a relative .aoe2record inside a configured replay root")
    # A client directory string is a selector, never a newly trusted filesystem root.
    roots = [root for root in config.replay_roots if directory is None or directory == str(root)]
    if not roots:
        raise ValueError("replay directory is not configured")
    found = []
    for root in roots:
        try:
            candidate = (root / relative).resolve(strict=True)
        except FileNotFoundError:
            continue
        if not candidate.is_relative_to(root):
            raise ValueError("replay symlink escapes its configured root")
        if candidate.is_file():
            found.append(candidate)
    if len(found) != 1:
        raise ValueError("replay is missing or ambiguous; choose a configured directory")
    return found[0]


@dataclass
class Job:
    ticket: Any
    replay: Path
    converter: Any
    state: str = "queued"
    cancelled: threading.Event = field(default_factory=threading.Event)
    future: Any = None


class Coordinator:
    """One selected request; Session port performs the final atomic generation CAS.

    Session ports share one selection RLock. Blocking I/O, cancellation and old
    worker joins run outside it; final adoption and close are atomic under it.
    """

    def __init__(
        self, port: SessionPort, factory: Callable[..., Any], *, executor: Any = None
    ) -> None:
        self.port, self.factory = port, factory
        self.executor = executor or ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="vantage-native"
        )
        self.lock = getattr(port, "lock", threading.RLock())
        self.current: Job | None = None
        self.closed = False

    def start(self, replay: Path) -> dict[Any, Any]:
        replay = replay.expanduser().resolve(strict=True)
        if not replay.is_file() or replay.suffix.lower() != ".aoe2record":
            raise ValueError("expected a local .aoe2record")
        converter = self.factory()
        with self.lock:
            if self.closed:
                raise ValueError("native coordinator is closed")
            old = self._cancel_locked()
        if old is not None:
            old.cancel()
        # begin reserves the selection atomically, but joins old workers outside
        # the shared lock. A newer reservation/close can win during that cleanup.
        ticket = self.port.begin(replay)
        with self.lock:
            if self.closed:
                self.port.update(ticket, "cancelled")
                raise ConversionCancelled("native coordinator closed while queueing replay")
            if not self.port.update(ticket, "queued"):
                raise ConversionCancelled("selection changed while queueing native replay")
            job = self.current = Job(ticket, replay, converter)
            try:
                job.future = self.executor.submit(self._work, job)
            except Exception as error:
                job.state = "failed"
                self.port.update(ticket, "failed", error=str(error))
                raise
            return dict(generation=ticket.generation, state="queued")

    def _cancel_locked(self, generation: Any = None) -> Any:
        """Mark only; callers invoke the returned backend outside selection lock."""
        job = self.current
        if not job or job.state not in ("queued", "converting"):
            return None
        if generation is not None and generation != job.ticket.generation:
            return None
        job.cancelled.set()
        job.state = "cancelled"
        self.port.update(job.ticket, "cancelled")
        return job.converter

    def cancel(self, generation: int | None = None) -> bool:
        with self.lock:
            converter = self._cancel_locked(generation)
        if converter is None:
            return False
        converter.cancel()  # Only its stored owned process group; no process search.
        return True

    def _active(self, job: Job) -> bool:
        return self.current is job and not job.cancelled.is_set()

    def _work(self, job: Job) -> None:
        try:
            with self.lock:
                if not self._active(job):
                    return
                if not self.port.update(job.ticket, "converting", phase="conversion"):
                    job.state = "cancelled"
                    return
                job.state = "converting"
            recording = job.converter.convert(job.replay)
            with self.lock:
                if not self._active(job):
                    return
                if not self.port.update(job.ticket, "converting", phase="loading"):
                    job.state = "cancelled"
                    return
            # Header, data-mode selection and complete Timeline I/O all precede CAS.
            loaded = self.port.prepare(job.ticket, recording, job.cancelled)
            with self.lock:
                if self._active(job):
                    job.state = (
                        "ready" if self.port.adopt(job.ticket, recording, loaded) else "cancelled"
                    )
        except Exception as error:
            with self.lock:
                if self.current is job:
                    cancelled = job.cancelled.is_set() or isinstance(error, ConversionCancelled)
                    job.state = "cancelled" if cancelled else "failed"
                    self.port.update(job.ticket, job.state, error=None if cancelled else str(error))

    def close(self) -> None:
        with self.lock:
            self.closed = True
            converter = self._cancel_locked()
        if converter is not None:
            converter.cancel()
        self.executor.shutdown(wait=False, cancel_futures=True)
