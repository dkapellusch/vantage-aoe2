"""vantage.assetcache: one conversion per asset at a time, and whole cache files."""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from vantage.assetcache import SingleFlight, atomic_write


def test_concurrent_callers_of_one_key_share_one_run() -> None:
    flight: SingleFlight[int] = SingleFlight()
    started, release = threading.Event(), threading.Event()
    runs: list[str] = []

    def work(key: str) -> int:
        runs.append(key)
        started.set()
        release.wait(5)
        return len(runs)

    got: list[int] = []
    threads = [
        threading.Thread(target=lambda: got.append(flight.run("a", lambda: work("a"))))
        for _ in range(5)
    ]
    threads[0].start()
    assert started.wait(5)
    for th in threads[1:]:
        th.start()
    # Another key is not held up by the one in flight.
    assert flight.run("b", lambda: 42) == 42
    release.set()
    for th in threads:
        th.join(5)
    assert runs == ["a"] and got == [1] * 5
    # Once finished the key runs again (the caller's disk cache answers then).
    assert flight.run("a", lambda: 7) == 7


def test_a_failure_reaches_every_waiter_and_is_not_kept() -> None:
    flight: SingleFlight[int] = SingleFlight()
    started, release = threading.Event(), threading.Event()
    errors: list[BaseException] = []

    def boom() -> int:
        started.set()
        release.wait(5)
        raise ValueError("bad file")

    def call() -> None:
        try:
            flight.run("k", boom)
        except ValueError as exc:
            errors.append(exc)

    first = threading.Thread(target=call)
    first.start()
    assert started.wait(5)
    second = threading.Thread(target=call)
    second.start()
    release.set()
    first.join(5)
    second.join(5)
    assert len(errors) == 2
    assert flight.run("k", lambda: 1) == 1


def test_atomic_write_replaces_whole_files_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out = tmp_path / "sub" / "a.png"
    assert atomic_write(out, b"one") and out.read_bytes() == b"one"
    assert atomic_write(out, b"two") and out.read_bytes() == b"two"

    def fail(src: str, dst: str) -> None:
        raise PermissionError("target in use")

    monkeypatch.setattr("os.replace", fail)
    # A cache file that cannot be written is not an error: the asset is still served.
    assert atomic_write(out, b"three") is False
    assert out.read_bytes() == b"two" and [p.name for p in out.parent.iterdir()] == ["a.png"]
