"""Exercise installed App/CLI/SSE methods with fake dependencies; no network/target."""

import io
import json
from types import SimpleNamespace as NS

import pytest

from vantage import cli, gamedata, native_jobs, native_session, server


@pytest.fixture(autouse=True)
def fake_http_json_response(monkeypatch):
    # Exercise the installed dispatcher methods with a fake handler, not a socket.
    monkeypatch.setattr(server, "_json", lambda h, body, status=200, **_: (status, body))
    monkeypatch.setattr(server, "_replay_dir_mode", lambda _: "aoe2")


def handler(path, body=None):
    raw = json.dumps(body).encode() if body is not None else b""
    return NS(path=path, headers={"Content-Length": str(len(raw))}, rfile=io.BytesIO(raw))


def test_configured_http_error_is_serialized_and_never_legacy(monkeypatch):
    def play(*_):
        raise ValueError("bounded native failure")

    monkeypatch.setattr(native_session, "play_replay", play)
    post = server.App.post
    session = NS(native=object(), open_live=lambda **_: pytest.fail("fallback"))
    status, body = post(NS(session=session), handler("/api/play_replay", {"name": "x"}))
    assert status == 400 and body["ok"] is False and "bounded native failure" in body["error"]


def test_unconfigured_http_watch_retains_legacy_branch(tmp_path):
    replay = tmp_path / "legacy.aoe2record"
    replay.write_bytes(b"fake")
    calls = []
    session = NS(native=None, open_live=lambda **kw: calls.append(kw))
    app = NS(
        session=session,
        _windows_replay_path=lambda *a: "Z:\\legacy.aoe2record",
        _replay_dir_list=lambda: [tmp_path],
        _await_load=lambda: {"ok": True},
    )
    post = server.App.post
    status, body = post(app, handler("/api/play_replay", {"name": replay.name}))
    assert status == 200 and body["ok"] is True
    assert calls == [
        dict(replay="Z:\\legacy.aoe2record", record=True, game=server.GAME_AOE2, confirm=False)
    ]


def test_configured_http_launch_and_status_never_probe_game():
    def forbidden(*_):
        pytest.fail("launcher access")

    app = NS(session=NS(native=object()), launcher=NS(launch=forbidden, status=forbidden))
    post = server.App.post
    assert post(app, handler("/api/launch_game", {}))[0] == 400
    launch_status = server.App._launch_status
    assert launch_status(app)["status"] == "disabled"


def test_native_config_capability_overrides_client_supplied_flags():
    get = server.App.get
    app = NS(
        session=NS(native=object(), timeline=None),
        client_config={"native_replays": False},
        asset_version=lambda: "v",
    )
    status, config = get(app, handler("/api/config"))
    # Vantage's config also carries its version and asset version.
    assert status == 200 and config["native_replays"] is True
    assert set(config) == {"native_replays", "version", "asset_version"}
    app.session.native = None
    app.client_config["native_replays"] = True
    status, config = get(app, handler("/api/config"))
    assert status == 200 and config.get("native_replays", False) is False
    assert "native_replays" not in config  # absent, as before, without local playback


def test_SSE_emits_native_phase_and_cancel_without_generation_or_timeline_change():
    stream = server.App._stream
    states = iter(
        (("converting", "conversion"), ("converting", "loading"), ("cancelled", "loading"))
    )
    source = {"status": "queued"}
    writes = []

    def wait_change(*_):
        try:
            status, phase = next(states)
            source.update(status=status, phase=phase)
        except StopIteration:
            raise BrokenPipeError from None

    tl = NS(version=0, complete=False, wait_change=wait_change)
    session = NS(
        generation=1,
        timeline=tl,
        describe=lambda: {
            "generation": 1,
            "source": source.copy(),
            "error": None,
            "live_connected": False,
        },
    )
    h = NS(
        send_response=lambda *_: None,
        send_header=lambda *_: None,
        end_headers=lambda: None,
        wfile=NS(write=writes.append, flush=lambda: None),
    )
    stream(NS(session=session, skins=NS(version=lambda: 0)), h)
    events = [
        json.loads(w.decode().split("data: ", 1)[1]) for w in writes if w.startswith(b"data: ")
    ]
    assert [(x["source"]["status"], x["source"].get("phase")) for x in events] == [
        ("queued", None),
        ("converting", "conversion"),
        ("converting", "loading"),
        ("cancelled", "loading"),
    ]
    assert len({x["generation"] for x in events}) == 1


@pytest.mark.parametrize("failure", ("bind", "config", "selection", None))
def test_cli_cleanup_boundary_binds_before_work(tmp_path, monkeypatch, failure):
    parser = cli.build_parser()
    args = parser.parse_args(
        [
            "serve",
            "--native-replay",
            str(tmp_path / "game.aoe2record"),
            "--native-profile",
            str(tmp_path / "profile"),
            "--native-profile-sha256",
            "a" * 64,
            "--native-cache-dir",
            str(tmp_path / "cache"),
            "--native-replay-root",
            str(tmp_path),
            "--recordings-dir",
            str(tmp_path / "recs"),
        ]
    )
    calls = []

    class Session:
        native = None

        def __init__(self, *a):
            calls.append("session")

        def configure_native(self, config):
            calls.append("configure")
            if failure == "config":
                raise ValueError("config failed")
            self.native, self.native_config = object(), config

        def open_native_replay(self, path):
            calls.append("submit")
            if failure == "selection":
                raise RuntimeError("submit failed")

        def close_native(self):
            calls.append("close_native")

        def stop(self):
            calls.append("stop")

    def serve(*a, **kw):
        calls.append("bind")
        if failure == "bind":
            raise OSError("occupied")
        return NS(
            serve_forever=lambda: calls.append("serve"),
            server_close=lambda: calls.append("server_close"),
        )

    monkeypatch.setattr(gamedata, "GameData", lambda *_: object())
    monkeypatch.setattr(gamedata, "find_game_dir", lambda: None)
    monkeypatch.setattr(server, "serve", serve)
    monkeypatch.setattr(native_session, "NativeSession", Session)
    monkeypatch.setattr(native_jobs, "NativeConfig", lambda *a: NS(replay_roots=a[3]))
    result = cli._serve(args)
    assert result == (2 if failure else 0)
    assert (
        calls[-2:] == ["close_native", "stop"]
        if failure in ("bind", "config")
        else calls[-3:] == ["close_native", "stop", "server_close"]
    )
    if failure in ("bind", "config"):
        assert "submit" not in calls
    else:
        assert calls.index("bind") < calls.index("submit")
        assert ("serve" in calls) == (failure is None)


def test_installed_native_entrypoints_are_the_actual_modules():
    assert native_jobs.Coordinator.__module__ == "vantage.native_jobs"
    assert native_session.NativeSession.__module__ == "vantage.native_session"
    assert server.App.post.__module__ == "vantage.server"
    assert cli._serve.__module__ == "vantage.cli"
