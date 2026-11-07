"""Signal callbacks must return without re-entering the converter's lock."""

import json
import signal
import sys
import threading

import pytest

from tools import native_engine_convert as cli
from vantage.native_engine_protocol import ConversionResult, ReplayIdentity


@pytest.mark.parametrize("signum", [signal.SIGINT, signal.SIGTERM])
def test_cancel_signal_while_converter_lock_is_held(tmp_path, monkeypatch, signum):
    callbacks = {}
    cancel_threads = []
    main_thread = threading.get_ident()
    cancellation_finished = threading.Event()
    lock = threading.Lock()

    class Result:
        status = "cancelled"

        def to_json(self):
            return {"status": self.status, "recording": None}

    class FakeEngine:
        def __init__(self, *args, **kwargs):
            pass

        def cancel(self):
            cancel_threads.append(threading.get_ident())
            assert threading.get_ident() != main_thread, "signal handler re-entered main lock"
            with lock:
                cancellation_finished.set()

        def convert(self, request):
            with lock:
                # The callback runs synchronously on the thread holding lock.
                # The former callback deadlocked here by calling cancel().
                callbacks[signum](signum, None)
                assert not cancellation_finished.is_set()
            assert cancellation_finished.wait(2)
            return Result()

    old = object()

    def fake_signal(sig, handler):
        callbacks[sig] = handler
        return old

    monkeypatch.setattr(cli.signal, "signal", fake_signal)
    monkeypatch.setattr(cli.EngineRegistry, "load", lambda *args: object())
    monkeypatch.setattr(cli, "V32Engine", FakeEngine)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "native_engine_convert",
            "--registry",
            str(tmp_path / "registry.json"),
            "--registry-sha256",
            "0" * 64,
            "--replay",
            str(tmp_path / "replay.aoe2record"),
            "--cache-dir",
            str(tmp_path / "cache"),
            "--output",
            str(tmp_path / "result.json"),
            "--experimental",
        ],
    )
    with pytest.raises(SystemExit) as stopped:
        cli.main()
    assert stopped.value.code == 1
    assert json.loads((tmp_path / "result.json").read_text()) == {
        "status": "cancelled",
        "recording": None,
    }
    assert len(cancel_threads) == 1 and cancel_threads[0] != main_thread
    assert callbacks[signal.SIGINT] is old and callbacks[signal.SIGTERM] is old
    assert not any(t.name == "native-conversion-cancel" for t in threading.enumerate())


def test_immediate_ready_result_does_not_outrun_pending_cancel(tmp_path, monkeypatch):
    callbacks = {}
    cancelled = threading.Event()

    class FakeEngine:
        def __init__(self, *args, **kwargs):
            pass

        def cancel(self):
            cancelled.set()

        def convert(self, request):
            callbacks[signal.SIGTERM](signal.SIGTERM, None)
            return ConversionResult(
                "ready",
                "engine",
                ReplayIdentity(
                    "0" * 64,
                    0,
                    54800,
                    1,
                    1,
                    1,
                    0,
                    2,
                ),
                recording={"path": "ready.vrec"},
                conversion_report={"path": "report.json"},
            )

    monkeypatch.setattr(
        cli.signal, "signal", lambda sig, handler: callbacks.setdefault(sig, handler)
    )
    monkeypatch.setattr(cli.EngineRegistry, "load", lambda *args: object())
    monkeypatch.setattr(cli, "V32Engine", FakeEngine)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "native_engine_convert",
            "--registry",
            str(tmp_path / "registry.json"),
            "--registry-sha256",
            "0" * 64,
            "--replay",
            str(tmp_path / "replay.aoe2record"),
            "--cache-dir",
            str(tmp_path / "cache"),
            "--output",
            str(tmp_path / "result.json"),
            "--experimental",
        ],
    )
    with pytest.raises(SystemExit) as stopped:
        cli.main()
    assert stopped.value.code == 1 and cancelled.is_set()
    result = json.loads((tmp_path / "result.json").read_text())
    assert result["status"] == "cancelled"
    assert result["recording"] is None and result["conversion_report"] is None
