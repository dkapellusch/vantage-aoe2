"""The indexed server only adopts a completed recording with the expected extent."""

import io
import sys
import threading
from types import SimpleNamespace

import pytest

from vantage import native_v32_indexed_serve as indexed


def test_preview_notice_only_wraps_preview_index():
    calls = []
    app = SimpleNamespace(_static=lambda _handler, name: calls.append(name))
    server = SimpleNamespace(app=app)
    original = app._static
    indexed._mark_incomplete_preview(server, {"title": "ordinary recording"})
    assert app._static is original
    indexed._mark_incomplete_preview(server, {"title": "INCOMPLETE-checksum-prefix"})

    class Handler:
        def __init__(self):
            self.wfile = io.BytesIO()
            self.status = None

        def send_response(self, status):
            self.status = status

        def send_header(self, _key, _value):
            pass

        def end_headers(self):
            pass

    handler = Handler()
    app._static(handler, "index.html")
    body = handler.wfile.getvalue()
    assert handler.status == 200
    assert b"vantage-incomplete-preview" in body and b"the match continues" in body
    assert b"state.source?.header?.title" in body
    app._static(handler, "style.css")
    assert calls == ["style.css"]


@pytest.mark.parametrize("bad_status", [None, {"frames": 9}, {"errors": 1}, {"desynced": True}])
def test_adoption_requires_complete_expected_recording(tmp_path, monkeypatch, bad_status):
    recording = tmp_path / "recording.vrec"
    recording.touch()
    calls = []
    source = {}
    data = SimpleNamespace(game="test", with_mode=lambda _mode: data)

    class Session:
        def __init__(self, _data, _directory):
            self.generation = 1
            self.source = source
            self.lock = threading.Lock()
            self.ended = threading.Event()
            self.timeline = None

        def _reserve(self, _kind, _source):
            ticket = SimpleNamespace(data=data, stop=threading.Event(), generation=1, source=source)
            return ticket, None

        def stop(self):
            calls.append("stop")

        def close_native(self):
            calls.append("close_native")

    status = {"complete": True, "errors": 0, "desynced": False, "frames": 10, "time": 50}
    status.update(bad_status or {})
    timeline = SimpleNamespace(status=lambda: status)
    server = SimpleNamespace(
        serve_forever=lambda: calls.append("serve_forever"),
        server_close=lambda: calls.append("server_close"),
    )

    def serve(_host, _port, session, *_args, **_kwargs):
        assert session.timeline is timeline and session.ended.is_set()
        assert session.source["status"] == "ready"
        calls.append("serve")
        return server

    monkeypatch.setattr(indexed, "GameData", lambda _path: data)
    monkeypatch.setattr(indexed, "NativeSession", Session)
    monkeypatch.setattr(indexed, "read_header", lambda _path: {"expected_frames": 10, "end_ms": 50})
    monkeypatch.setattr(indexed, "load_completed", lambda *_args: (data, timeline))
    monkeypatch.setattr(indexed, "serve", serve)
    monkeypatch.setattr(indexed, "_drop_pool", lambda: calls.append("drop_pool"))
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "indexed",
            "--recording",
            str(recording),
            "--index-root",
            str(tmp_path / "index"),
            "--recordings-dir",
            str(tmp_path / "recordings"),
            "--game-dir",
            str(tmp_path),
        ],
    )
    result = indexed.main()
    assert result == (0 if bad_status is None else 2)
    assert ("serve" in calls) == (bad_status is None)
    assert "stop" in calls and "close_native" in calls and "drop_pool" in calls
