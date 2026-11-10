"""Shared plumbing for assets converted from the game and cached on disk.

* :class:`SingleFlight`: concurrent requests for the same asset do the work once.
  A cold battle scene asks for hundreds of sprite strips over six connections, and
  the browser's look-ahead asks for many of them twice; each duplicate was another
  ~30 ms decode.
* :func:`atomic_write`: a cache file appears whole or not at all. With plain
  ``write_bytes`` a request arriving mid-write (or a crash) read a truncated PNG
  that then stayed in the cache.
"""

from __future__ import annotations

import contextlib
import os
import tempfile
import threading
from collections.abc import Callable, Hashable
from concurrent.futures import Future
from pathlib import Path


class SingleFlight[T]:
    """Run ``fn`` once per key at a time; callers arriving meanwhile get its result
    (or its exception). Nothing is remembered once a run finishes: the disk cache
    is what answers the next request."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._running: dict[Hashable, Future[T]] = {}

    def run(self, key: Hashable, fn: Callable[[], T]) -> T:
        with self._lock:
            running = self._running.get(key)
            if running is None:
                mine: Future[T] = Future()
                self._running[key] = mine
        if running is not None:
            return running.result()
        try:
            result = fn()
        except BaseException as exc:
            mine.set_exception(exc)
            raise
        else:
            mine.set_result(result)
            return result
        finally:
            with self._lock:
                del self._running[key]


def atomic_write(path: Path, data: bytes) -> bool:
    """Write ``data`` to ``path`` through a temporary file in the same folder.

    False when it could not be written (a full disk, or on Windows a reader holding
    the old file open): the cache is only an optimisation, the caller still has the
    data to serve.
    """
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    except OSError:
        return False
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        os.replace(tmp, path)
    except OSError:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        return False
    return True
