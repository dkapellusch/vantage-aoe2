"""The plugin hooks: code outside this package extending ``serve`` and the server."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path
from threading import Thread
from types import SimpleNamespace
from typing import Any

import pytest

from vantage import cli, gamedata, server
from vantage.gamedata import GameData


class RoutePlugin:
    config_keys = ("claimed",)

    def config(self, app: Any, config: dict[str, Any]) -> None:
        config["claimed"] = "by the server"

    def get(self, app: Any, handler: Any, path: str, query: dict[str, str]) -> bool:
        if path != "/api/extra":
            return False
        server.json_response(handler, {"extra": query.get("x")})
        return True

    def post(self, app: Any, handler: Any, path: str, body: dict[str, Any]) -> bool:
        if path == "/api/extra":
            server.json_response(handler, {"got": body})
            return True
        if path == "/api/broken":
            raise ValueError("said no")
        return False


@pytest.fixture
def served(tmp_path: Path):
    session = server.Session(GameData(None), tmp_path)
    bound = server.serve(
        "127.0.0.1", 0, session, [], {"claimed": "by the browser"}, plugins=[RoutePlugin()]
    )
    Thread(target=bound.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{bound.server_address[1]}"
    bound.shutdown()
    bound.server_close()


def fetch(url: str, body: Any = None) -> tuple[int, Any]:
    data = None if body is None else json.dumps(body).encode()
    try:
        with urllib.request.urlopen(urllib.request.Request(url, data=data), timeout=5) as answer:
            return answer.status, json.loads(answer.read())
    except urllib.error.HTTPError as error:
        raw = error.read()
        try:
            return error.code, json.loads(raw or b"{}")
        except ValueError:
            return error.code, None  # the server's plain error page


def test_server_plugin_adds_routes_and_config(served: str) -> None:
    assert fetch(f"{served}/api/extra?x=1") == (200, {"extra": "1"})
    assert fetch(f"{served}/api/extra", {"a": 1}) == (200, {"got": {"a": 1}})
    # A key the plugin reserves cannot be set by a forced browser configuration.
    assert fetch(f"{served}/api/config")[1]["claimed"] == "by the server"
    # Routes the plugin leaves alone are the server's own.
    assert fetch(f"{served}/api/session")[0] == 200


def test_server_plugin_errors_are_reported_like_the_servers_own(served: str) -> None:
    status, body = fetch(f"{served}/api/broken", {})
    assert status == 400 and body["ok"] is False and "said no" in body["error"]


def test_server_without_plugins_has_no_extra_routes(tmp_path: Path) -> None:
    session = server.Session(GameData(None), tmp_path)
    bound = server.serve("127.0.0.1", 0, session, [])
    Thread(target=bound.serve_forever, daemon=True).start()
    try:
        base = f"http://127.0.0.1:{bound.server_address[1]}"
        assert fetch(f"{base}/api/extra")[0] == 404
        assert fetch(f"{base}/native")[0] == 404
    finally:
        bound.shutdown()
        bound.server_close()


class SourcePlugin:
    """A ``serve`` plugin that opens a source of its own (``--thing``)."""

    source_flags = ("--thing",)

    def __init__(self, problem: str | None = None, dirs: list[Path] | None = None) -> None:
        self.calls: list[str] = []
        self.problem, self.dirs = problem, dirs

    @property
    def session_class(self) -> Any:
        calls = self.calls

        class Session:
            def __init__(self, *unused: Any) -> None:
                calls.append("session")

            def stop(self) -> None:
                calls.append("stop")

        return Session

    def add_arguments(self, serve: Any, source: Any) -> None:
        source.add_argument("--thing")

    def has_source(self, args: Any) -> bool:
        return args.thing is not None

    def prepare(self, args: Any, recordings: Path) -> str | None:
        self.calls.append("prepare")
        return self.problem

    def configure(self, args: Any, session: Any) -> None:
        self.calls.append("configure")

    def replay_dirs(self, session: Any) -> list[Path] | None:
        return self.dirs

    def server_plugins(self) -> list[Any]:
        return ["route-plugin"]

    def open(self, args: Any, session: Any) -> bool:
        self.calls.append("open")
        return args.thing is not None

    def close(self, session: Any) -> None:
        self.calls.append("close")


def run_serve(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, plugin: Any, *extra: str) -> Any:
    seen: dict[str, Any] = {}

    def serve(host: str, port: int, session: Any, dirs: list[Path], config: Any, **kw: Any) -> Any:
        plugin.calls.append("bind")
        seen.update(kw, dirs=dirs)
        return SimpleNamespace(serve_forever=lambda: None, server_close=lambda: None)

    monkeypatch.setattr(gamedata, "find_game_dir", lambda: None)
    monkeypatch.setattr(server, "default_replay_dirs", lambda: [Path("/usual")])
    monkeypatch.setattr(server, "serve", serve)
    argv = ["serve", "--recordings-dir", str(tmp_path / "recordings"), *extra]
    return cli.main(argv, plugin=plugin), seen


def test_serve_plugin_opens_its_source_once_the_server_is_bound(monkeypatch, tmp_path) -> None:
    plugin = SourcePlugin(dirs=[tmp_path])
    code, seen = run_serve(monkeypatch, tmp_path, plugin, "--thing", "x")
    assert code == 0
    assert plugin.calls == ["prepare", "session", "configure", "bind", "open", "close", "stop"]
    # Its own replay folders replace the usual ones, and no live game is followed.
    assert seen["dirs"] == [tmp_path] and seen["follow_live"] is False
    assert seen["plugins"] == ["route-plugin"]


def test_serve_plugin_without_folders_keeps_the_usual_ones(monkeypatch, tmp_path) -> None:
    plugin = SourcePlugin()
    code, seen = run_serve(monkeypatch, tmp_path, plugin)
    assert code == 0 and seen["dirs"] == [Path("/usual")] and seen["follow_live"] is True


def test_serve_plugin_problem_stops_before_anything_opens(monkeypatch, tmp_path, capsys) -> None:
    plugin = SourcePlugin(problem="not today")
    code, _ = run_serve(monkeypatch, tmp_path, plugin)
    assert code == 2 and plugin.calls == ["prepare"]
    assert "not today" in capsys.readouterr().err


def test_serve_names_the_plugins_source_when_two_are_given(monkeypatch, tmp_path, capsys) -> None:
    recording = tmp_path / "a.vrec"
    recording.write_bytes(b"")
    plugin = SourcePlugin()
    argv = ["serve", str(recording), "--thing", "x"]
    assert cli.main(argv, plugin=plugin) == 2
    assert "--thing" in capsys.readouterr().err


def test_serve_without_a_plugin_has_no_native_options() -> None:
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(["serve", "--native-replay", "x"])
