"""HTTP/client wiring using authored recordings and an authored Python worker."""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from tests.test_native import setup_worker, wait
from vantage.gamedata import GameData
from vantage.server import Session, serve


def request(base: str, path: str, body: dict | None = None) -> tuple[int, object]:
    req = urllib.request.Request(
        base + path,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Content-Type": "application/json"},
    )
    try:
        response = urllib.request.urlopen(req, timeout=4)
    except urllib.error.HTTPError as error:
        response = error
    with response:
        raw = response.read()
        return response.status, json.loads(
            raw
        ) if response.headers.get_content_type() == "application/json" else raw


@pytest.fixture
def native_server(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("VANTAGE_DATA_DIR", str(tmp_path / "ui-data"))
    monkeypatch.setattr(
        "vantage.server.port_open", lambda *a, **k: pytest.fail("Game API was probed")
    )
    jobs, replay, _ = setup_worker(tmp_path)
    session = Session(GameData(None), tmp_path / "recordings")
    monkeypatch.setattr(session, "open_live", lambda *a, **k: pytest.fail("Live game was opened"))
    server = serve(
        "127.0.0.1",
        0,
        session,
        [tmp_path],
        follow_live=False,
        native_jobs=jobs,
        recording_only=True,
    )
    thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=0.05))
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}", session, jobs, replay
    finally:
        jobs.close()
        session.stop()
        server.shutdown()
        server.server_close()
        thread.join(2)


def test_conversion_and_open_through_standalone_http(native_server) -> None:
    base, session, jobs, replay = native_server
    code, page = request(base, "/native")
    assert code == 200 and b"without the game" in page
    code, info = request(base, "/api/native")
    assert code == 200 and info["available"] is True and info["builds"] == [54800]
    code, probe = request(base, "/api/session?probe=1")
    assert code == 200 and probe["game_api_open"] is False
    code, _ = request(base, "/api/native/convert", {"path": str(replay), "experimental": 1})
    assert code == 400
    code, job = request(base, "/api/native/convert", {"path": str(replay), "experimental": True})
    assert code == 202
    result = wait(jobs, job["id"])
    assert result["status"] == "ready", result
    code, status = request(base, "/api/native?id=" + job["id"])
    assert code == 200 and status["complete_match"] is True
    code, opened = request(base, "/api/native/open", {"id": job["id"]})
    assert code == 200 and opened["ok"] is True
    assert session.ended.wait(2) and session.error is None
    assert session.mode == "recording" and session.source["native_conversion"] == job["id"]


@pytest.mark.parametrize(
    "path",
    [
        "/api/live",
        "/api/play_replay",
        "/api/launch_game",
        "/api/record",
        "/api/game_dir",
        "/api/open_url",
    ],
)
def test_recording_only_routes_cannot_open_game(native_server, path: str) -> None:
    base, session, _jobs, _replay = native_server
    code, result = request(base, path, {})
    assert code == 400 and "without the game" in result["error"] and session.mode == "idle"


def test_unknown_job_does_not_change_session(native_server) -> None:
    base, session, _jobs, _replay = native_server
    code, _ = request(base, "/api/native?id=unknown")
    assert code == 400
    code, _ = request(base, "/api/native/open", {"id": "unknown"})
    assert code == 400 and session.mode == "idle"


def test_recording_only_accepts_local_vrec_but_rejects_game_links(native_server) -> None:
    base, session, jobs, _replay = native_server
    template = jobs.cache.parent / "template.vrec"
    code, value = request(base, "/api/open_url", {"url": str(template)})
    assert code == 200 and value["ok"] is True and session.mode == "recording"
    code, _ = request(base, "/api/open_url", {"url": "captureage://spectate?lobbyid=123"})
    assert code == 400
    code, _ = request(base, "/api/launch_game")
    assert code == 400


def test_cli_recording_only_rejects_live_before_game_detection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from vantage.cli import build_parser, run

    monkeypatch.setattr(
        "vantage.gamedata.find_game_dir", lambda: pytest.fail("Game install was searched")
    )
    assert run(build_parser().parse_args(["serve", "--recording-only", "--live"])) == 2


def test_cli_native_import_requires_explicit_identity_and_opt_in(tmp_path: Path) -> None:
    from vantage.cli import build_parser, run

    assert (
        run(
            build_parser().parse_args(
                ["serve", "--recording-only", "--native-worker", str(tmp_path / "absent")]
            )
        )
        == 2
    )


def test_cli_recording_only_import_does_not_find_or_contact_game(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from types import SimpleNamespace

    from vantage.cli import build_parser, run
    from vantage.native import file_pin

    jobs, _replay, descriptor = setup_worker(tmp_path)
    jobs.close()
    seen = {}
    monkeypatch.setattr(
        "vantage.gamedata.find_game_dir", lambda: pytest.fail("Game install was searched")
    )
    monkeypatch.setattr("vantage.server.default_replay_dirs", lambda: [])

    def server(host, port, session, dirs, config, **kwargs):
        seen.update(kwargs)
        seen["game_dir"] = session.data.game_dir
        return SimpleNamespace(serve_forever=lambda: None, server_close=lambda: None)

    monkeypatch.setattr("vantage.server.serve", server)
    args = build_parser().parse_args(
        [
            "serve",
            "--recording-only",
            "--recordings-dir",
            str(tmp_path / "recs"),
            "--native-worker",
            str(descriptor),
            "--native-worker-sha256",
            file_pin(descriptor)["sha256"],
            "--experimental-native",
        ]
    )
    assert run(args) == 0
    assert (
        seen["recording_only"] is True and seen["follow_live"] is False and seen["game_dir"] is None
    )
    assert seen["native_jobs"].describe()["available"] is True
