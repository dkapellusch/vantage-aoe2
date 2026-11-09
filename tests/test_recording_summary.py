"""vantage.recording_summary: what the recordings list says about each file."""

from __future__ import annotations

import json
import os
import urllib.request
from pathlib import Path
from typing import Any

import pytest

from tests.helpers import game_frames
from vantage import recording_summary as rs
from vantage.frames import RecordingWriter
from vantage.gamedata import GameData


def _recording(path: Path, seconds: int = 3) -> Path:
    with RecordingWriter(path, {"source": "test"}) as w:
        for f in game_frames(seconds):
            w.write(f)
    return path


def test_summary_names_the_players_and_the_map(tmp_path: Path) -> None:
    summary = rs.summarize(_recording(tmp_path / "game.vrec"), GameData(None, tmp_path / "cache"))
    assert summary is not None
    assert summary["map"] == "Arabia"
    names = [p["name"] for p in summary["players"]]
    assert len(names) >= 2 and all(names)
    assert all(p["id"] > 0 for p in summary["players"])  # Gaia is not a player
    assert all(p["color"].startswith("#") for p in summary["players"])


def test_a_recording_without_a_snapshot_has_no_summary(tmp_path: Path) -> None:
    path = tmp_path / "empty.vrec"
    with RecordingWriter(path, {"source": "test"}):
        pass
    assert rs.summarize(path, GameData(None, tmp_path / "cache")) is None


def test_the_cache_answers_only_for_the_file_as_it_is(tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    path = _recording(tmp_path / "game.vrec")
    assert rs.load(cache, path) is None
    rs.store(cache, path, {"players": [], "map": "Arabia"})
    assert rs.load(cache, path) == {"players": [], "map": "Arabia"}
    # A recording that grew (a live session still being written) is read again.
    with path.open("ab") as fh:
        fh.write(b"more")
    assert rs.load(cache, path) is None
    # A damaged cache entry is a miss, not an error.
    rs.store(cache, path, {"players": [], "map": "Arabia"})
    rs.cache_file(cache, path).write_text("{not json", "utf-8")
    assert rs.load(cache, path) is None


def test_the_helper_fills_the_cache_and_remembers_unreadable_files(tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    good = _recording(tmp_path / "good.vrec")
    bad = tmp_path / "bad.vrec"
    bad.write_bytes(b"not a recording")
    assert rs.main(["--cache-dir", str(cache), str(good), str(bad)]) == 0
    assert rs.load(cache, good)["map"] == "Arabia"  # type: ignore[index]
    assert rs.load(cache, bad) == {"players": [], "map": "", "unreadable": True}


def test_one_helper_at_a_time_and_none_while_disabled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    started: list[list[str]] = []

    class Child:
        def __init__(self, cmd: list[str], **_: Any) -> None:
            started.append(cmd)
            self.done = False

        def poll(self) -> int | None:
            return 0 if self.done else None

        def terminate(self) -> None:
            self.done = True

    monkeypatch.setattr(rs.subprocess, "Popen", Child)
    paths = [tmp_path / f"{i}.vrec" for i in range(rs.BATCH + 5)]
    off = rs.Summarizer()
    assert off.request(tmp_path, None, paths) is False and not started
    on = rs.Summarizer(enabled=True)
    assert on.request(tmp_path, tmp_path / "game", paths) is True
    assert on.request(tmp_path, None, paths) is True  # still running: no second helper
    assert len(started) == 1
    cmd = started[0]
    assert cmd[1:3] == ["-m", "vantage.recording_summary"]
    assert cmd[cmd.index("--game-dir") + 1] == str(tmp_path / "game")
    assert cmd[-rs.BATCH :] == [str(p) for p in paths[: rs.BATCH]]  # a batch, newest first
    on.stop()
    assert on.busy() is False
    assert on.request(tmp_path, None, []) is False  # nothing left to read


def test_the_recordings_list_carries_the_summary_once_opened(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import threading

    from vantage.server import Session, serve

    monkeypatch.setenv("VANTAGE_DATA_DIR", str(tmp_path / "data"))
    rec = tmp_path / "recs"
    rec.mkdir()
    path = _recording(rec / "game.vrec", 6)
    session = Session(GameData(None, tmp_path / "cache"), rec)
    session.summaries.enabled = True
    # No helper process in the test: only what opening the recording learns.
    monkeypatch.setattr(session.summaries, "request", lambda *a: False)
    srv = serve("127.0.0.1", 0, session, [])
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"

    def recordings() -> Any:
        with urllib.request.urlopen(base + "/api/recordings", timeout=5) as r:
            return json.loads(r.read())

    try:
        first = recordings()[0]
        assert first["summary"] is None and first["summary_pending"] is True
        session.open_recording(str(path))
        session._thread.join(5)  # type: ignore[union-attr]
        listed = recordings()[0]
        assert listed["summary_pending"] is False
        assert listed["summary"]["map"] == "Arabia"
        assert listed["summary"]["duration_ms"] == 6000
        assert os.path.exists(rs.cache_file(tmp_path / "cache", path))
    finally:
        session.stop()
        srv.shutdown()
        srv.server_close()
