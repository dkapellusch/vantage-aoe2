"""vantage.server: the HTTP API over a session."""

from __future__ import annotations

import http.client
import json
import socket
import sys
import threading
import urllib.error
import urllib.request
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from typing import Any

import pytest

import vantage
from tests.helpers import game_frames
from vantage.frames import RecordingWriter
from vantage.gamedata import GameData
from vantage.server import (
    App,
    Session,
    serve,
)
from vantage.timeline import Timeline


@pytest.fixture
def server(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[str, Session, Path]]:
    monkeypatch.setenv("VANTAGE_DATA_DIR", str(tmp_path / "data"))
    rec = tmp_path / "recs"
    rec.mkdir()
    path = rec / "game.vrec"
    with RecordingWriter(path, {"source": "test"}) as w:
        for f in game_frames(6):
            w.write(f)
    replays = tmp_path / "pfx" / "drive_c" / "users" / "steamuser" / "savegame"
    replays.mkdir(parents=True)
    (replays / "a.aoe2record").write_bytes(b"x")
    session = Session(GameData(None), rec)
    srv = serve("127.0.0.1", 0, session, [replays])
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    try:
        yield base, session, path
    finally:
        session.stop()
        srv.shutdown()
        srv.server_close()


def _get(url: str) -> Any:
    with urllib.request.urlopen(url, timeout=5) as r:
        body = r.read()
        return json.loads(body) if r.headers.get_content_type() == "application/json" else body


def _post(url: str, body: dict[str, Any]) -> Any:
    req = urllib.request.Request(
        url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.loads(r.read())


def test_idle_then_open_recording(server: tuple[str, Session, Path]) -> None:
    base, session, path = server
    assert _get(base + "/api/session")["mode"] == "idle"
    assert _get(base + "/api/view") == {}
    assert _post(base + "/api/open", {"path": str(path)}) == {"ok": True}
    session._thread.join(5)  # type: ignore[union-attr]
    desc = _get(base + "/api/session")
    assert desc["mode"] == "recording" and desc["timeline"]["complete"]
    assert _get(base + "/api/match")["map_file"] == "Arabia.rms"
    assert _get(base + "/api/map")["width"] == 4
    assert "83" in _get(base + "/api/catalog")["units"]
    assert _get(base + "/api/view?t=2500")["time"] == 2000
    assert [e["kind"] for e in _get(base + "/api/events?from=0&to=6000")][:2] == [
        "kill",
        "researched",
    ]
    assert set(_get(base + "/api/series")) >= {"1", "2"}
    assert "1" in _get(base + "/api/summary")
    assert _get(base + "/api/trees?t=0")["t"] == 0
    assert _get(base + "/api/unit/104")["kills"] == 1.0
    group = _get(base + "/api/group?ids=104,x,-5")  # junk ids are ignored
    assert group["totals"]["kills"] == 1.0 and len(group["types"]) == 1
    assert _get(base + "/api/techtree/1") == {}  # no game install in tests
    config = _get(base + "/api/config")
    assert config.pop("asset_version")
    assert config == {
        "patch": {},
        "force_default": False,
        "version": vantage.__version__,
        "game_art": True,
    }
    assert _get(base + "/api/catalog?lang=de")["units"]["83"]["name"]
    assert _get(base + "/api/recordings")[0]["name"] == "game.vrec"
    assert _get(base + "/api/replays")[0]["name"] == "a.aoe2record"
    assert _post(base + "/api/bookmarks", {"bookmarks": [1000, 4000]}) == {"ok": True}
    assert _get(base + "/api/bookmarks") == [1000, 4000]
    assert _post(base + "/api/control", {"action": "pause", "value": True})["ok"] is False


def test_static_files_and_errors(server: tuple[str, Session, Path]) -> None:
    base, _, _ = server
    assert b"Vantage" in _get(base + "/")
    assert b"import" in _get(base + "/static/app.js")
    for bad in (
        "/static/nope.js",
        "/icon/unit/1.png",
        "/emblem/1.png",
        "/nowhere",
        "/audio/notify/age_up.ogg",
        "/audio/taunt/1.ogg",
        "/sprite/1/0/0.png",
        "/images/x.png",
    ):
        with pytest.raises(urllib.error.HTTPError) as exc:
            _get(base + bad)
        assert exc.value.code == 404
    with pytest.raises(urllib.error.HTTPError) as exc:
        _post(base + "/api/open", {"path": "/no/such.vrec"})
    assert exc.value.code == 400


def test_keep_alive_responses_disable_nagle(
    server: tuple[str, Session, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    base, _, _ = server
    options: list[int] = []
    connections: list[int] = []
    original = App.get

    def inspect_connection(app: App, handler: BaseHTTPRequestHandler) -> None:
        options.append(handler.connection.getsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY))
        connections.append(id(handler.connection))
        original(app, handler)

    monkeypatch.setattr(App, "get", inspect_connection)
    conn = http.client.HTTPConnection(base.removeprefix("http://"), timeout=5)
    try:
        for _ in range(2):
            conn.request("GET", "/api/config")
            response = conn.getresponse()
            assert response.status == 200
            assert json.loads(response.read())["patch"] == {}
    finally:
        conn.close()
    assert options == [1, 1]
    assert connections[0] == connections[1]


def test_windows_replay_path(tmp_path: Path) -> None:
    d = tmp_path / "pfx" / "drive_c" / "users" / "steamuser" / "savegame"
    d.mkdir(parents=True)
    (d / "r.aoe2record").write_bytes(b"")
    app = App(Session(GameData(None), tmp_path), [d])
    # Under Proton the game sees its prefix as C:; on Windows paths are its own.
    expected = (
        str(d / "r.aoe2record")
        if sys.platform == "win32"
        else "C:\\users\\steamuser\\savegame\\r.aoe2record"
    )
    assert app._windows_replay_path("r.aoe2record") == expected
    with pytest.raises(KeyError):
        app._windows_replay_path("missing")


def test_replay_listing_reads_headers_and_durations(tmp_path: Path) -> None:
    import gzip

    fixtures = Path(__file__).parent / "fixtures"
    d = tmp_path / "savegame"
    d.mkdir()
    for name in ("replay_3p_54800.aoe2record.gz", "replay_6p_54800.aoe2record.gz"):
        raw = gzip.decompress((fixtures / name).read_bytes())
        (d / name.removesuffix(".gz")).write_bytes(raw)
    (d / "broken.aoe2record").write_bytes(b"not a replay")
    app = App(Session(GameData(None), tmp_path), [d])

    rows = {r["name"]: r for r in app._replays()}
    assert "error" in rows["broken.aoe2record"]
    three = rows["replay_3p_54800.aoe2record"]
    assert [p["name"] for p in three["players"]] == ["Shazama", "Knut the Great", "Immortal v0d10f"]
    assert three["build"] == 54800 and three["current_build"] is True
    assert three["players"][1]["human"] is False

    assert app._replay_scan is not None
    app._replay_scan.join(timeout=30)
    rows = {r["name"]: r for r in app._replays()}
    assert rows["replay_3p_54800.aoe2record"]["duration_ms"] == 2494234
    shazama = rows["replay_3p_54800.aoe2record"]["players"][0]
    assert (shazama["elo"], shazama["ratings"]) == (1101, [[3, -1, 1345], [4, -1, 1101]])


def test_mode_paths() -> None:
    from vantage.server import _replay_dir_mode, mode_from_path

    assert mode_from_path("modes\\Pompeii\\") == "Pompeii"
    assert mode_from_path("modes/Pompeii") == "Pompeii"
    assert mode_from_path("") is None and mode_from_path("Pompeii") is None
    assert _replay_dir_mode(Path("/p/123/modes/Pompeii/savegame")) == "Pompeii"
    assert _replay_dir_mode(Path("/p/123/modes/Pompeii/savegame/multi")) == "Pompeii"
    assert _replay_dir_mode(Path("/p/123/savegame")) is None


def test_return_of_rome_replays_use_the_mode_data(tmp_path: Path) -> None:
    import gzip

    game = tmp_path / "AoE2DE"
    dat = game / "modes" / "Pompeii" / "resources" / "_common" / "dat"
    dat.mkdir(parents=True)
    civs = [{"internal_name": f"C{i}"} for i in range(63)]
    civs[53] = {"internal_name": "Palmyran"}  # player 1's civ id in the fixture
    (dat / "civilizations.json").write_text(json.dumps({"civilization_list": civs}))
    maps = {"map_list": [{"storage_id": 216, "script_filename": "highland.rms"}]}
    (dat / "maps.json").write_text(json.dumps(maps))
    d = tmp_path / "123" / "modes" / "Pompeii" / "savegame"
    d.mkdir(parents=True)
    raw = (Path(__file__).parent / "fixtures" / "replay_3p_54800.aoe2record.gz").read_bytes()
    (d / "r.aoe2record").write_bytes(gzip.decompress(raw))
    app = App(Session(GameData(game, cache_dir=tmp_path / "c"), tmp_path), [d])
    (row,) = app._replays()
    assert row["game"] == "ror" and row["map"] == "highland"
    assert (row["players"][0]["number"], row["players"][0]["civ"]) == (1, "Palmyran")
    assert row["settings"]["population"] == 200


def test_open_folder_rejects_unknown(tmp_path: Path) -> None:
    app = App(Session(GameData(None), tmp_path), [])
    assert app._open_folder("etc")["ok"] is False
    assert app._open_folder("profile")["ok"] is False  # no replay folders known


def test_settings_profiles(server: tuple[str, Session, Path], tmp_path: Path) -> None:
    base, _, _ = server
    assert _post(base + "/api/profile", {"name": "../x", "settings": {}})["ok"] is False
    assert _post(base + "/api/profile", {"name": "Caster A", "settings": {"showElo": True}})["ok"]
    assert _get(base + "/api/profiles") == ["Caster A"]
    assert _get(base + "/api/profile/Caster%20A") == {"showElo": True}
    with pytest.raises(urllib.error.HTTPError):
        _get(base + "/api/profile/missing")
    assert (tmp_path / "data" / "profiles" / "Caster A.json").is_file()


# -- views, skins, live status ----------------------------------------------------


def test_summary_at_a_time_and_new_view_fields(server: tuple[str, Session, Path]) -> None:
    base, session, path = server
    _post(base + "/api/open", {"path": str(path)})
    session._thread.join(5)  # type: ignore[union-attr]
    assert _get(base + "/api/summary?t=1000")["2"]["eco_kills"] == 0
    late = _get(base + "/api/summary")
    assert late["2"]["eco_kills"] == 1 and "placing" in late["1"]
    v = _get(base + "/api/view")
    assert {"kings", "construction", "koth", "treaty"} <= set(v)
    assert {"eco_kills", "score_parts", "eapm", "apm_peak"} <= set(v["players"]["1"])
    unit = _get(base + "/api/unit/104")
    assert unit["owner"] == 2 and "damage_by_target" in unit and "garrison" in unit
    assert _get(base + "/api/session")["timeline"]["skips"] == []
    assert _post(base + "/api/record", {"on": True})["ok"] is False  # recordings only play
    assert _post(base + "/api/playback_ended", {}) == {"ok": True, "exiting": False}


def test_images_skins_and_mods(server: tuple[str, Session, Path], tmp_path: Path) -> None:
    base, _, _ = server
    data = tmp_path / "data"
    (data / "images").mkdir(parents=True)
    (data / "images" / "flag.png").write_bytes(b"\x89PNG")
    (data / "images" / "notes.txt").write_text("x")
    assert _get(base + "/api/images") == ["flag.png"]
    skin = data / "skins" / "Gold"
    skin.mkdir(parents=True)
    (skin / "skin.json").write_text(
        json.dumps({"title": "Gold", "assets": {"logo": "logo.png", "bad": "../x"}, "x": 1})
    )
    (skin / "skin.css").write_text(":root{--accent:gold}")
    (skin / "logo.png").write_bytes(b"\x89PNG")
    (data / "skins" / "empty").mkdir()
    (got,) = _get(base + "/api/skins")
    assert got["name"] == "Gold" and got["css_url"] == "/skins/Gold/skin.css"
    assert got["assets"] == {"logo": "/skins/Gold/logo.png"} and got["x"] == 1
    assert _get(base + got["css_url"]) == b":root{--accent:gold}"
    for bad in ("/skins/Gold/../../data/images/flag.png", "/skins/Gold/missing.css"):
        with pytest.raises(urllib.error.HTTPError):
            _get(base + bad)
    mods = _post(base + "/api/mods", {"graphics": True, "dirs": [str(tmp_path / "m")]})
    assert mods["enabled"]["graphics"] is True and mods["dirs"] == [str(tmp_path / "m")]
    assert _get(base + "/api/mods")["enabled"]["terrain"] is False


def test_game_dir_is_validated_and_repoints_the_game_data(
    server: tuple[str, Session, Path], tmp_path: Path
) -> None:
    base, session, _ = server
    empty = tmp_path / "nogame"
    empty.mkdir()
    bad = _post(base + "/api/game_dir", {"path": str(empty)})
    assert bad["ok"] is False and "AoE2DE_s.exe" in bad["error"]
    game = tmp_path / "AoE2DE"
    game.mkdir()
    (game / "AoE2DE_s.exe").write_bytes(b"MZ")
    mods = session.data.mods
    got = _post(base + "/api/game_dir", {"path": str(game)})
    assert got == {"ok": True, "game_dir": str(game)}
    assert session.data.game_dir == game and session.data.mods is mods
    assert _get(base + "/api/session")["game_dir"] == str(game)
    assert _post(base + "/api/game_dir", {"path": ""})["game_dir"] == str(game)


def test_open_url_opens_recordings(server: tuple[str, Session, Path]) -> None:
    base, session, path = server
    assert _post(base + "/api/open_url", {"url": str(path)})["ok"]
    assert session.mode == "recording"
    assert _post(base + "/api/open_url", {"url": "not a link"})["ok"] is False


def test_replay_version_state_follows_the_installed_build(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import gzip

    from tests.test_gamedata import _pe

    game = tmp_path / "AoE2DE"
    game.mkdir()
    (game / "AoE2DE_s.exe").write_bytes(_pe("101.103.60000.0"))
    profile = tmp_path / "pfx" / "123"
    d = profile / "savegame"
    d.mkdir(parents=True)
    raw = (Path(__file__).parent / "fixtures" / "replay_3p_54800.aoe2record.gz").read_bytes()
    (d / "r.aoe2record").write_bytes(gzip.decompress(raw))
    session = Session(GameData(game, cache_dir=tmp_path / "c"), tmp_path)
    app = App(session, [])
    assert app._replays() == []
    session.user_dirs.append(profile)  # the live game reported its profile folder
    (row,) = app._replays()
    assert (row["build"], row["installed_build"], row["newest_build"]) == (54800, 60000, 54800)
    assert row["version_state"] == "old" and row["current_build"] is False
    assert App(session, [], follow_live=False)._replays() == []
    monkeypatch.setattr("shutil.which", lambda _: None)
    monkeypatch.setattr("sys.platform", "linux")  # the xdg-open path
    assert app._open_folder("profile")["path"] == str(profile)
    assert app._open_folder("images")["ok"] is False  # no xdg-open: folder still made
    assert app.images_dir.is_dir()


def test_oracle_messages_drive_status_lobby_and_paused_chat(tmp_path: Path) -> None:
    session = Session(GameData(None), tmp_path)
    session.timeline = Timeline(GameData(None))
    session.source = {"status": "ready", "lobby_id": "123"}
    lobby = {
        "kind": "observerlobby",
        "matchstarttime": "t0",
        "lobbyinfo": {
            "custommapname": "Arabia",
            "spectatorcount": 2,
            "slots": [{"used": {"name": "Ann", "teamid": 1, "civid": 3}}, {}],
        },
    }
    session.oracle_message(lobby)
    src = session.source
    assert src["status"] == "waiting_lobby" and src["lobby"]["id"] == "123"
    assert src["lobby"]["name"] == "Arabia" and src["lobby"]["players"][0]["name"] == "Ann"
    session.oracle_message({"kind": "observerleave"})
    assert src["lobby"] is None
    session.oracle_message({"kind": "gamepaused", "paused": True, "pausedbyplayerid": 2})
    session.oracle_message({"kind": "gamechat", "playerid": 1, "text": "hi", "destinationmap": 4})
    assert session.timeline.events[-1]["to"] == [2] and session.timeline.events[-1]["paused"]
    session.oracle_message({"kind": "gamepaused", "paused": False})
    session.oracle_message(
        {"kind": "gamechat", "playerid": 2, "text": "gg"}
    )  # not paused: logged too
    assert session.timeline.events[-1]["text"] == "gg" and not session.timeline.events[-1]["paused"]
    assert session.timeline.events[-1]["oracle"] is True
    session.oracle_message({"kind": "gamestate", "value": 3})
    assert src["status"] == "ended"
    assert session.set_recording(True)["ok"] is False  # not live


def test_a_stalled_stream_is_waiting(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import threading
    import time

    import vantage.server as S

    monkeypatch.setattr(S, "WAITING_AFTER_S", 0.0)
    session = Session(GameData(None), tmp_path)
    session.timeline = Timeline(GameData(None))
    session.source = {"status": "playing"}
    session._live = object()  # connected
    session._last_frame = time.monotonic() - 5
    stop = threading.Event()
    watcher = threading.Thread(target=session._watch_waiting, args=(stop,), daemon=True)
    watcher.start()
    deadline = time.monotonic() + 5
    while session.source.get("waiting") is None and time.monotonic() < deadline:
        time.sleep(0.05)
    session.source["paused"] = True  # a pause is not waiting
    deadline = time.monotonic() + 5
    while session.source.get("waiting") is not None and time.monotonic() < deadline:
        time.sleep(0.05)
    stop.set()
    watcher.join(5)
    assert session.source["waiting"] is None
    (ev,) = [e for e in session.timeline.events if e["kind"] == "waiting"]
    assert ev["cat"] == "status" and ev["seconds"] >= 5


def test_skin_endpoints_merge_add_and_reload(
    server: tuple[str, Session, Path], tmp_path: Path
) -> None:
    import zipfile

    base, _, _ = server
    data = tmp_path / "data"
    for name, opts in (("A", {"useT90Components": True}), ("B", {"useT90Components": False})):
        d = data / "skins" / name
        d.mkdir(parents=True)
        (d / "skin.json").write_text(
            json.dumps({"options": opts, "stylesheets": ["s.css"], "assets": {"logo": "l.png"}})
        )
        (d / "s.css").write_text(f"/* {name} */")
        (d / "l.png").write_bytes(b"\x89PNG")
    rows = _get(base + "/api/skins")
    assert [r["name"] for r in rows] == ["A", "B"] and rows[0]["status"] == "ready"
    merged = _get(base + "/api/skins/merged?enabled=A,B")
    assert merged["options"]["useT90Components"] is True
    assert merged["stylesheets"] == ["/skins/A/s.css", "/skins/B/s.css"]
    assert merged["assets"]["logo"] == "/skins/B/l.png"
    assert _get(base + "/api/skins/merged") == {
        "options": {}, "stylesheets": [], "assets": {}, "enabled": []
    }  # fmt: skip
    # add a zip from anywhere on disk, then serve its files
    z = tmp_path / "Elsewhere.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("skin.json", json.dumps({"stylesheets": ["z.css"]}))
        zf.writestr("z.css", "z{}")
    assert _post(base + "/api/skins/add", {"path": str(z), "kind": "zip"}) == {
        "ok": True, "name": "Elsewhere", "kind": "zip"
    }  # fmt: skip
    assert _get(base + "/skins/Elsewhere/z.css") == b"z{}"
    assert _post(base + "/api/skins/add", {"path": str(tmp_path / "nope")})["ok"] is False
    assert _post(base + "/api/skins/remove", {"name": "Elsewhere"}) == {"ok": True}
    # hot reload: the version moves when a skin file changes
    v0 = _get(base + "/api/skins/version")["version"]
    (data / "skins" / "A" / "s.css").write_text("/* A changed, longer */")
    import time

    time.sleep(0.6)  # the version check is rate limited to 0.5 s
    assert _get(base + "/api/skins/version")["version"] > v0


def test_sse_notifies_when_a_skin_changes(
    server: tuple[str, Session, Path], tmp_path: Path
) -> None:
    import time

    base, _, _ = server
    d = tmp_path / "data" / "skins" / "A"
    d.mkdir(parents=True)
    (d / "skin.json").write_text("{}")
    _get(base + "/api/skins/version")
    got: list[bytes] = []
    r = urllib.request.urlopen(base + "/sse?skins=1", timeout=10)

    def read() -> None:
        for _ in range(8):
            line = r.readline()
            got.append(line)
            if b"update" in line:
                return

    t = threading.Thread(target=read, daemon=True)
    t.start()
    time.sleep(0.8)
    (d / "skin.json").write_text('{"options": {"showSkinLogo": true}}')
    t.join(8)
    r.close()
    assert got[0].startswith(b"retry") and b"event: skins\n" in got and b"data: update\n" in got


def test_stats_dump_and_ready_to_watch_details(server: tuple[str, Session, Path]) -> None:
    base, session, path = server
    assert _get(base + "/stats-dump")["summary"] == {}  # nothing loaded yet
    assert "game_details" not in _get(base + "/api/session")["source"]
    _post(base + "/api/open", {"path": str(path)})
    session._thread.join(5)  # type: ignore[union-attr]
    dump = _get(base + "/stats-dump")
    assert set(dump) >= {"session", "match", "status", "summary", "series", "events"}
    assert "1" in dump["summary"] and dump["match"]["map_file"] == "Arabia.rms"
    assert dump["events"][0]["kind"] == "kill" and dump["status"]["complete"]
    desc = _get(base + "/api/session")
    assert desc["source"]["game_details"] == {"map_name": "Arabia.rms", "player_count": 2}
    assert _get(base + "/api/unit/104")["born"] == 0


def test_launch_game_uses_the_injected_runner_and_never_the_real_game(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from vantage.launcher import GameLauncher

    monkeypatch.setenv("VANTAGE_DATA_DIR", str(tmp_path / "data"))
    game = tmp_path / "AoE2DE"
    game.mkdir()
    (game / "AoE2DE_s.exe").write_bytes(b"MZ")
    session = Session(GameData(game, cache_dir=tmp_path / "c"), tmp_path)
    srv = serve("127.0.0.1", 0, session, [])
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    calls: list[list[str]] = []
    srv.app.launcher = GameLauncher(  # type: ignore[attr-defined]  # injected: no real launch
        lambda: game,
        runner=lambda argv: calls.append(argv) is None,
        app_state=lambda: "stopped",
        process_running=lambda: False,
    )
    try:
        assert _get(base + "/api/launch_game")["status"] == "unknown"
        assert _post(base + "/api/launch_game", {})["status"] == "opening"
        assert calls == [["steam", "-applaunch", "813780", "SKIPINTRO"]]
        assert _get(base + "/api/launch_game")["status"] == "opening"
    finally:
        session.stop()
        srv.shutdown()
        srv.server_close()


def test_launch_status_follows_the_live_stream_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from vantage.launcher import GameLauncher

    monkeypatch.setenv("VANTAGE_DATA_DIR", str(tmp_path / "data"))
    game = tmp_path / "AoE2DE"
    game.mkdir()
    (game / "AoE2DE_s.exe").write_bytes(b"MZ")
    session = Session(GameData(game, cache_dir=tmp_path / "c"), tmp_path)
    srv = serve("127.0.0.1", 0, session, [])
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    srv.app.launcher = GameLauncher(  # type: ignore[attr-defined]  # injected: no real launch
        lambda: game,
        runner=lambda argv: True,
        app_state=lambda: "stopped",
        process_running=lambda: False,
    )
    try:
        assert session.stream_state() is None  # not following a live game
        session.mode = "live"
        session._stream_error = "closed-player"
        assert _get(base + "/api/launch_game")["status"] == "runningPlayer"
        session._stream_error = "closed-unavailable"
        assert session.stream_state() == "closed-unavailable"
        # a live stream: the game's API newer than Vantage knows, then fine, then stalled
        session._live = object()
        session.source = {"api_version": 23}
        assert _get(base + "/api/launch_game")["status"] == "runningCadeNeedsUpdate"
        session.source = {"api_version": 22}
        assert _get(base + "/api/launch_game")["status"] == "connected"
        session.source = {"api_version": 22, "waiting": 6.0}
        assert session.stream_state() == "connected-hiccup"
        assert _get(base + "/api/launch_game")["status"] == "connected"
    finally:
        session._live = None
        session.stop()
        srv.shutdown()
        srv.server_close()


def test_launch_game_without_an_install_is_no_game_exe(server: tuple[str, Session, Path]) -> None:
    base, _, _ = server
    assert _post(base + "/api/launch_game", {})["status"] == "noGameExe"


def test_unreadable_replays_are_flagged_missing_data(tmp_path: Path) -> None:
    profile = tmp_path / "pfx" / "123"
    d = profile / "savegame"
    d.mkdir(parents=True)
    (d / "broken.aoe2record").write_bytes(b"not a replay")
    session = Session(GameData(None, cache_dir=tmp_path / "c"), tmp_path)
    session.user_dirs.append(profile)
    (row,) = App(session, [])._replays()
    assert row["missing_data"] is True and row["error"]


def test_tree_costs_reach_layout_stages() -> None:
    from tests.helpers import KNIGHT
    from vantage.server import _tree_costs

    tl = Timeline(GameData(None))
    tl.feed_all(game_frames(1))
    tree = {"nodes": [], "layout": {"rows": [{"groups": [{"stages": [
        {"kind": "unit", "id": KNIGHT}, {"kind": "tech", "id": 101}, {"kind": "unit", "id": -5}
    ]}]}]}}  # fmt: skip
    _tree_costs(tree, tl)
    stages = tree["layout"]["rows"][0]["groups"][0]["stages"]  # type: ignore[index]
    assert stages[0]["cost"]["gold"] == 75.0 and "cost" not in stages[2]


def test_keyframe_step_widens_only_while_saturated() -> None:
    from vantage.server import keyframe_step

    assert keyframe_step(0.9, 1000) == 2000  # falling behind the stream
    assert keyframe_step(0.7, 2000) == 2000  # hysteresis: stays wide
    assert keyframe_step(0.7, 1000) == 1000
    assert keyframe_step(0.3, 2000) == 1000  # headroom again


def test_fast_replay_speed_switches_to_the_light_stream(tmp_path: Path) -> None:
    from vantage.server import LIGHT_STREAM_MS

    class FakeGame:
        cancelled = 0

        def set_speed(self, speed: str) -> bool:
            return True

        def cancel_frames(self) -> None:
            FakeGame.cancelled += 1

    s = Session(GameData(None), tmp_path)
    s._live = FakeGame()
    assert s.control("speed", "NORMAL")["ok"] and not s._light_stream
    assert FakeGame.cancelled == 0  # already the full stream: nothing to reopen
    assert s.control("speed", "EXTRA_FAST")["ok"]
    assert s._light_stream and s._restart_stream and FakeGame.cancelled == 1
    s._restart_stream = False
    assert s.control("speed", "FAST")["ok"] and FakeGame.cancelled == 1  # still light
    assert s.control("speed", "NORMAL")["ok"] and not s._light_stream and FakeGame.cancelled == 2
    assert 100 < LIGHT_STREAM_MS <= 1000  # lighter than the full 100 ms stream


def test_replay_duration_is_none_for_a_missing_file(tmp_path: Path) -> None:
    from vantage.server import replay_duration

    assert replay_duration("C:\\nowhere\\x.aoe2record", GameData(None)) is None


def test_light_stream_keeps_the_particles_that_show_game_state() -> None:
    from vantage.server import light_particles

    defs = [
        "building_researching",
        "smoke_chimney",
        "fire_large",
        "blood_infantry",
        "unit_dust_trail",
        "relic_glow",
    ]
    assert light_particles(defs) == [
        "building_researching",
        "smoke_chimney",
        "fire_large",
        "relic_glow",
    ]


def test_windows_open_folder_data_dir_and_web_types(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import os

    import vantage.server as S

    monkeypatch.setattr("sys.platform", "win32")
    monkeypatch.delenv("VANTAGE_DATA_DIR", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local"))
    assert S.data_dir() == tmp_path / "Local" / "Vantage"
    monkeypatch.setenv("VANTAGE_DATA_DIR", str(tmp_path / "data"))
    assert S.data_dir() == tmp_path / "data"
    opened: list[Path] = []
    monkeypatch.setattr(os, "startfile", opened.append, raising=False)
    app = App(Session(GameData(None), tmp_path), [])
    assert app._open_folder("images") == {"ok": True, "path": str(tmp_path / "data" / "images")}
    assert opened == [tmp_path / "data" / "images"]
    assert app._open_folder("profile")["ok"] is False  # no replay folders known
    added: list[tuple[str, str]] = []
    monkeypatch.setattr("mimetypes.add_type", lambda t, ext: added.append((ext, t)))
    S._pin_web_types()
    assert (".js", "text/javascript") in added and (".css", "text/css") in added


def test_static_files_refuse_drive_and_unc_paths(server: tuple[str, Session, Path]) -> None:
    base, _, _ = server
    for name in ("C:/Windows/win.ini", "a\\b.js"):
        with pytest.raises(urllib.error.HTTPError) as err:
            _get(f"{base}/static/{name}")
        assert err.value.code == 400


def test_session_reports_certificates_and_probes_the_game(
    server: tuple[str, Session, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    base, _, _ = server
    monkeypatch.setenv("VANTAGE_CERTS", str(tmp_path / "certs"))
    certs = _get(base + "/api/session")["certs"]
    assert certs["dir"] == str(tmp_path / "certs")
    assert certs["missing"] == ["certificate-authority.pem", "cade-client.pem", "cade-client.key"]
    assert certs["docs"].endswith("/wiki/Live-games")
    assert "game_api_open" not in _get(base + "/api/session")
    monkeypatch.setattr("vantage.server.port_open", lambda *a: True)
    assert _get(base + "/api/session?probe=1")["game_api_open"] is True


def test_a_failed_first_connection_names_its_cause(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    session = Session(GameData(None), tmp_path)
    app = App(session, [])
    certs = tmp_path / "certs"
    monkeypatch.setenv("VANTAGE_CERTS", str(certs))
    source: dict[str, Any] = {"status": "connecting"}
    session.source = source
    session._explain_connect_failure(source, "127.0.0.1", 4341)
    assert source["status"] == "needs_certs"
    assert session.error is not None and "cade-client.key" in session.error
    assert app._await_load(timeout=0.2)["needs_certs"] is True
    # The files arrive while the game is running but refuses them: a hint, still retrying.
    certs.mkdir()
    for name in ("certificate-authority.pem", "cade-client.pem", "cade-client.key"):
        (certs / name).write_text("x")
    monkeypatch.setattr("vantage.server.port_open", lambda *a: True)
    session._explain_connect_failure(source, "127.0.0.1", 4341)
    assert source["status"] == "connecting"
    assert "refused the secure connection" in session.error


def test_session_stream_announces_status_changes(server: tuple[str, Session, Path]) -> None:
    base, session, _ = server
    with urllib.request.urlopen(base + "/api/stream", timeout=5) as r:

        def next_event() -> dict[str, Any]:
            while True:
                line = r.readline().decode()
                if line.startswith("data: "):
                    got: dict[str, Any] = json.loads(line[6:])
                    return got

        assert next_event()["mode"] == "idle"
        # A live source moving on (e.g. to needs_certs) between frames is news.
        session.source["status"] = "needs_certs"
        assert next_event()["source"]["status"] == "needs_certs"


def test_review_moments_persist_separately_and_reject_stale_game(server):
    base, session, path = server
    _post(base + "/api/open", {"path": str(path)})
    session._thread.join(5)
    generation = _get(base + "/api/session")["generation"]
    _post(base + "/api/bookmarks", {"bookmarks": [1000, 2000]})
    moment = dict(
        id="raid",
        name="Raid",
        note="Watch workers",
        time=2000,
        player=1,
        fog="standard",
        camera=dict(x=20, y=30, zoom=1),
        selection=[101, 102],
        range={"from": 1000, "to": 3000},
    )
    body = {"generation": generation, "moments": [moment]}
    assert _post(base + "/api/review-moments", body) == {"ok": True}
    assert _get(base + "/api/review-moments") == [moment]
    assert _get(base + "/api/bookmarks") == [1000, 2000]
    assert Path(str(path) + ".moments.json").is_file()
    with pytest.raises(urllib.error.HTTPError):
        _post(base + "/api/review-moments", {"generation": generation - 1, "moments": []})
    assert _get(base + "/api/review-moments") == [moment]
    _post(base + "/api/open", {"path": str(path)})
    session._thread.join(5)
    assert _get(base + "/api/review-moments") == [moment]


def test_group_review_interval_api(server):
    base, session, path = server
    _post(base + "/api/open", {"path": str(path)})
    session._thread.join(5)
    result = _get(base + "/api/group?ids=101,102,101&t=5000&since=4000")
    assert result["since_ms"] == 4000 and result["as_of_ms"] == 5000
    assert "resources_destroyed" in result and result["forced_idle_estimated"] is True
    assert result["generation"] == session.generation


def _raw(url: str, headers: dict[str, str] | None = None) -> tuple[int, Any, bytes]:
    """Status, headers and body, error statuses included."""
    req = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, r.headers, r.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.headers, exc.read()


def test_view_is_spliced_json_and_the_newest_is_not_final(
    server: tuple[str, Session, Path],
) -> None:
    base, session, path = server
    assert _post(base + "/api/open", {"path": str(path)}) == {"ok": True}
    session._thread.join(5)  # type: ignore[union-attr]
    tl = session.timeline
    assert tl is not None and tl.complete
    for t in ("2500", "0", "6000", ""):
        status, headers, body = _raw(base + f"/api/view?t={t}")
        expected = tl.view_at(int(t) if t else None)
        assert status == 200 and headers["Cache-Control"] == "no-store"
        assert body == json.dumps(expected, separators=(",", ":")).encode()
        assert "final" not in json.loads(body)  # a loaded recording is final throughout
    live = Timeline(GameData(None))
    for f in game_frames(3):
        live.feed(f)
    session.timeline = live  # a live game: its newest keyframe is still filling
    assert _get(base + "/api/view?t=99000")["final"] is False
    assert "final" not in _get(base + "/api/view?t=1000")


def test_series_since_a_time(server: tuple[str, Session, Path]) -> None:
    base, session, path = server
    assert _get(base + "/api/series?from=0") == {}
    assert _post(base + "/api/open", {"path": str(path)}) == {"ok": True}
    session._thread.join(5)  # type: ignore[union-attr]
    tl = session.timeline
    assert tl is not None
    full = _get(base + "/api/series")
    assert full == json.loads(json.dumps(tl.series_json()))
    since = _get(base + "/api/series?from=5000")
    assert set(since) == set(full)
    assert all(rows == [r for r in full[pid] if r["t"] >= 5000] for pid, rows in since.items())
    assert _get(base + "/api/series?from=junk") == full


def test_session_pushes_are_coalesced_to_a_few_per_second(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import io
    import time

    monkeypatch.setenv("VANTAGE_DATA_DIR", str(tmp_path / "data"))
    session = Session(GameData(None), tmp_path)
    tl = session.timeline = Timeline(GameData(None))
    app = App(session, [])

    class Closed(io.BytesIO):
        """The browser goes away at the first keep-alive (the timeline is done)."""

        def write(self, b: Any) -> int:
            if b.startswith(b": keepalive"):
                raise BrokenPipeError
            return super().write(b)

    class Handler:
        wfile = Closed()

        def send_response(self, code: int) -> None: ...
        def send_header(self, k: str, v: str) -> None: ...
        def end_headers(self) -> None: ...

    def ingest() -> None:
        # A recording loading: a new version every few milliseconds for a second.
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline:
            tl.add_event({"t": 0, "cat": "status", "kind": "waiting", "players": []})
            time.sleep(0.002)
        tl.finish()

    feeder = threading.Thread(target=ingest)
    feeder.start()
    app._stream(Handler())  # type: ignore[arg-type]
    feeder.join()
    pushes = [
        json.loads(line[6:])
        for line in Handler.wfile.getvalue().decode().splitlines()
        if line.startswith("data: ")
    ]
    assert 2 <= len(pushes) <= 7  # about 4 a second, not one per version (hundreds)
    assert pushes[-1]["timeline"]["version"] == tl.version  # the latest state arrives
    assert pushes[-1]["timeline"]["complete"] is True


def test_session_push_waits_only_for_a_version_change() -> None:
    from vantage.server import SESSION_PUSH_S, push_wait

    key = (1, 10, None, False, "playing", None)
    assert push_wait(key, key, 100.0, 100.0) is None  # nothing new
    assert push_wait((1, 11, None, False, "playing", None), key, 100.0, 100.1) == pytest.approx(
        SESSION_PUSH_S - 0.1
    )
    assert push_wait((1, 11, None, False, "playing", None), key, 100.0, 100.0 + SESSION_PUSH_S) == 0
    urgent = (
        (2, 11, None, False, "playing", None),  # a new game
        (1, 11, "boom", False, "playing", None),
        (1, 11, None, True, "playing", None),
        (1, 11, None, False, "ended", None),
    )
    for changed in urgent:
        assert push_wait(changed, key, 100.0, 100.01) == 0


def test_missing_assets_keep_the_connection_open(server: tuple[str, Session, Path]) -> None:
    base, _, _ = server
    conn = http.client.HTTPConnection(base.removeprefix("http://"), timeout=5)
    try:
        conn.request("GET", "/icon/unit/1.png")
        miss = conn.getresponse()
        assert miss.status == 404 and miss.getheader("Connection") != "close"
        miss.read()
        sock = conn.sock
        conn.request("GET", "/static/../x")
        bad = conn.getresponse()
        assert bad.status == 400
        bad.read()
        conn.request("GET", "/api/config")
        ok = conn.getresponse()
        assert ok.status == 200 and json.loads(ok.read())["patch"] == {}
        assert conn.sock is sock  # the same connection served all three
    finally:
        conn.close()


def test_sprites_and_config_allow_the_paired_loopback_origin(
    server: tuple[str, Session, Path],
) -> None:
    base, _, _ = server
    port = base.rsplit(":", 1)[1]
    for origin in (f"http://localhost:{port}", f"http://127.0.0.1:{port}", f"http://[::1]:{port}"):
        for path in ("/api/config", "/sprite/1/0/0.png", "/sprite/1/0/0.json"):
            _, headers, _ = _raw(base + path, {"Origin": origin})
            assert headers["Access-Control-Allow-Origin"] == origin, (origin, path)
            assert headers["Access-Control-Expose-Headers"] == "X-Sprite-Meta"
            assert "Origin" in headers["Vary"]
    for origin in ("http://evil.example", f"http://localhost:{int(port) + 1}", "null"):
        _, headers, _ = _raw(base + "/api/config", {"Origin": origin})
        assert "Access-Control-Allow-Origin" not in headers
    _, headers, _ = _raw(base + "/api/session", {"Origin": f"http://localhost:{port}"})
    assert "Access-Control-Allow-Origin" not in headers  # only sprites and the probe
    # The other loopback name reaches the same server: no Host check turns it away.
    status, _, body = _raw(base + "/api/config", {"Host": f"localhost:{port}"})
    assert status == 200 and json.loads(body)["version"] == vantage.__version__


def test_versioned_asset_urls_are_cached_for_good(server: tuple[str, Session, Path]) -> None:
    from vantage.server import asset_cache_control

    base, _, _ = server
    version = _get(base + "/api/config")["asset_version"]
    assert version and isinstance(version, str)
    assert asset_cache_control({"av": version}, version) == "max-age=31536000, immutable"
    # Without the version, or with another one, a URL may yet change content.
    assert asset_cache_control({}, version) == "max-age=86400"
    assert asset_cache_control({"av": "old"}, version) == "max-age=86400"
