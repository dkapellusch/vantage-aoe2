"""The experimental runtime refuses unpinned inputs and scopes cancellation."""

import signal
from pathlib import Path

import pytest

from vantage import native_v32_runtime as runtime
from vantage.native_conversion import pin


def test_pin_rejects_mutation_and_invalid_digest(tmp_path: Path) -> None:
    source = tmp_path / "asset"
    source.write_bytes(b"original")
    expected = pin(source)
    runtime._verify(expected)
    source.write_bytes(b"modified")
    with pytest.raises(runtime.V32RuntimeError, match="Pinned input changed"):
        runtime._verify(expected)
    with pytest.raises(runtime.V32RuntimeError, match="Invalid input digest"):
        runtime._verify(dict(expected, sha256="not-a-digest"))


def test_cancel_signals_only_its_owned_process_group(monkeypatch: pytest.MonkeyPatch) -> None:
    worker = runtime.V32Runtime()
    signals = []

    class Child:
        pid = 424242

        def poll(self):
            return None

    worker._child = Child()
    monkeypatch.setattr(runtime.os, "killpg", lambda pid, sig: signals.append((pid, sig)))
    worker.cancel()
    assert signals == [(424242, signal.SIGTERM)]
    assert worker._cancelled.is_set()


def test_runtime_cannot_be_reused_after_a_failed_attempt(tmp_path: Path) -> None:
    worker = runtime.V32Runtime()
    with pytest.raises(FileNotFoundError):
        worker.run(tmp_path, stage_sha256="0" * 64, profile=tmp_path, profile_sha256="0" * 64)
    with pytest.raises(runtime.V32RuntimeError, match="single-use"):
        worker.run(tmp_path, stage_sha256="0" * 64, profile=tmp_path, profile_sha256="0" * 64)


def test_stages_are_claimed_once_and_legacy_runs_are_not_reused(tmp_path: Path) -> None:
    fresh = tmp_path / "fresh"
    fresh.mkdir()
    runtime._claim_stage(fresh)
    with pytest.raises(runtime.V32RuntimeError, match="already consumed"):
        runtime._claim_stage(fresh)
    legacy = tmp_path / "legacy"
    (legacy / "runs" / "previous").mkdir(parents=True)
    with pytest.raises(runtime.V32RuntimeError, match="previous runs"):
        runtime._claim_stage(legacy)
