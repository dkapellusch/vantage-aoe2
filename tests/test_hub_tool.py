"""The upload hub's own logic (tools/hub/hub.py): storage, routing and what a viewer
may be asked. No game, no farm, no Vantage server."""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

HUB = Path(__file__).resolve().parents[1] / "tools/hub/hub.py"


@pytest.fixture(scope="module")
def hub():
    spec = importlib.util.spec_from_file_location("hub_tool", HUB)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["hub_tool"] = module
    spec.loader.exec_module(module)
    return module


def test_store_keeps_one_match_per_file(hub, tmp_path):
    store = hub.Store(tmp_path)
    first, new = store.create(b"a" * 5000, "one.aoe2record", {"build": 1})
    again, new_again = store.create(b"a" * 5000, "renamed.aoe2record", {"build": 1})
    other, _ = store.create(b"b" * 5000, "two.aoe2record", {"build": 1})
    assert new and not new_again and first == again != other
    assert hub.ID_RE.fullmatch(first)
    assert store.meta(first)["status"] == "queued"
    assert store.update(first, status="ready")["name"] == "one.aoe2record"
    # A second store over the same folder (a restart) knows the files it has.
    assert hub.Store(tmp_path).create(b"a" * 5000, "x.aoe2record", {})[0] == first


def test_store_refuses_ids_that_are_not_its_own(hub, tmp_path):
    store = hub.Store(tmp_path)
    assert store.meta("../../etc") is None
    assert store.meta("m" + "a" * 12) is None


@pytest.mark.parametrize(
    "path",
    ["/", "/static/app.js", "/api/view", "/api/unit/-12", "/api/techtree/7", "/sprite/1/2/3.png",
     "/api/stream", "/sse", "/particle_atlas.png", "/api/skins/merged", "/terrain/3.png"],
)  # fmt: skip
def test_viewer_paths_the_hub_passes_on(hub, path):
    assert hub.VIEWER_GET.match(path)


@pytest.mark.parametrize(
    "path",
    ["/api/recordings", "/api/replays", "/api/launch_game", "/native", "/api/native",
     "/stats-dump", "/api/open", "/api/game_dir", "/api/profile/mine", "/api/viewx"],
)  # fmt: skip
def test_viewer_paths_the_hub_refuses(hub, path):
    assert not hub.VIEWER_GET.match(path)


def test_installed_build_is_read_from_the_games_session_file(hub, tmp_path):
    logs = tmp_path / "pfx/drive_c/users/steamuser/Games/Age of Empires 2 DE/logs"
    logs.mkdir(parents=True)
    (logs / "Age2SessionData.txt").write_text("Version = 101.103.57257.0 #(188329)\n")
    assert hub.installed_build(tmp_path) == 57257
    assert hub.installed_build(tmp_path / "missing") is None
    assert hub.installed_build(None) is None


@pytest.fixture
def served(hub, tmp_path, monkeypatch):
    """A hub over a temporary folder whose converter queues nothing."""
    opts = argparse.Namespace(
        data_dir=str(tmp_path), port=0, host="127.0.0.1", public_host=None, public_scheme="https",
        trust_proxy=False, jobs=1, idle_seconds=1, viewers=1, viewer_idle=60, max_mb=1,
        uploads_per_hour=2, build=57257, any_build=False, game_art=False,
    )  # fmt: skip
    monkeypatch.setattr(hub.Converter, "submit", lambda self, match_id: None)
    monkeypatch.setattr(hub, "replay_summary", lambda path: {"build": 57257, "players": []})
    app = hub.Hub(opts)
    server = ThreadingHTTPServer(("127.0.0.1", 0), hub.make_handler(app))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}", app
    server.shutdown()


def call(url, data=None, host=None):
    request = urllib.request.Request(url, data=data, method="POST" if data is not None else "GET")
    if host:
        request.add_header("Host", host)
    try:
        with urllib.request.urlopen(request, timeout=5) as answer:
            return answer.status, json.loads(answer.read() or b"{}")
    except urllib.error.HTTPError as err:
        return err.code, json.loads(err.read() or b"{}")


def test_upload_checks_and_limits(served):
    base, _ = served
    assert call(f"{base}/api/upload?name=a.txt", b"x" * 5000)[0] == 400  # not a replay name
    assert call(f"{base}/api/upload?name=a.aoe2record", b"x" * 10)[0] == 400  # too small
    assert call(f"{base}/api/upload?name=a.aoe2record", b"x" * (2 << 20))[0] == 413  # too large
    status, body = call(f"{base}/api/upload?name=..%2F..%2Fa.aoe2record", b"x" * 5000)
    assert status == 200 and body["new"]
    status, meta = call(f"{base}/api/match/{body['id']}")
    assert status == 200 and meta["status"] == "queued" and "/" not in meta["name"]
    assert meta["viewer"] is None if "viewer" in meta else True
    assert call(f"{base}/api/upload?name=b.aoe2record", b"y" * 5000)[0] == 200
    assert call(f"{base}/api/upload?name=c.aoe2record", b"z" * 5000)[0] == 429  # two an hour


def test_upload_of_another_build_is_refused_up_front(served, hub, monkeypatch):
    base, _ = served
    monkeypatch.setattr(hub, "replay_summary", lambda path: {"build": 54800, "players": []})
    status, body = call(f"{base}/api/upload?name=old.aoe2record", b"o" * 5000)
    assert status == 422 and "54800" in body["error"] and "57257" in body["error"]


def test_a_match_host_reaches_only_the_viewer_routes(served):
    base, app = served
    match_id, _ = app.store.create(b"q" * 5000, "q.aoe2record", {})
    host = f"{match_id}.localhost"
    assert call(f"{base}/api/recordings", host=host) == (200, [])
    assert call(f"{base}/api/launch_game", host=host)[0] == 404
    assert call(f"{base}/api/open", b"{}", host=host) == (200, {"ok": False, "error": "read-only"})
    assert call(f"{base}/api/view", host=host)[0] == 503  # no recording yet: nothing started
    assert call(f"{base}/api/view", host="m" + "a" * 12 + ".localhost")[0] == 404
    assert app.viewers.running == {}


def test_viewer_address_follows_the_request_or_the_public_name(served, hub):
    _, app = served

    request = argparse.Namespace(headers={"Host": "127.0.0.1:8750"})

    assert app.viewer_url("mabc", request) == "http://mabc.localhost:8750/"
    app.opts.public_host = "example.org"
    assert app.viewer_url("mabc", request) == "https://mabc.example.org/"
    assert app.match_of_host("m" + "b" * 12 + ".example.org") == "m" + "b" * 12
    assert app.match_of_host("example.org") is None and app.match_of_host("m" + "b" * 12) is None
