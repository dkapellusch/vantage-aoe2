"""vantage.cli: the ``vantage`` command."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

from tests.helpers import game_frames
from vantage.cli import main, serve_banner
from vantage.frames import RecordingWriter


def _recording(tmp_path: Path) -> Path:
    path = tmp_path / "g.vrec"
    with RecordingWriter(path, {"source": "test"}) as w:
        for f in game_frames(6):
            w.write(f)
    return path


def test_info_text_and_json(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VANTAGE_GAME_DIR", str(tmp_path / "none"))
    path = _recording(tmp_path)
    assert main(["info", str(path)]) == 0
    out = capsys.readouterr().out
    assert "13 frames" in out and "Arabia.rms" in out and "Alice" in out
    assert main(["info", str(path), "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["status"]["errors"] == 0 and data["events"] == 6


def test_parser_rejects_conflicting_sources() -> None:
    with pytest.raises(SystemExit):
        main(["serve", "--live", "--recording", "x.vrec"])


def test_spectate_url_parsing() -> None:
    from vantage.cli import parse_spectate_url, replay_windows_path

    assert parse_spectate_url("captureage://spectate/?lobbyid=123&source=x") == {
        "lobbyid": "123",
        "source": "x",
    }
    got = parse_spectate_url("captureage://spectate/?aoe2record=rec%201&game_lang=en")
    assert got["aoe2record"] == "rec 1"
    assert replay_windows_path("C:\\x\\y.aoe2record") == "C:\\x\\y.aoe2record"
    assert replay_windows_path("no-such-replay").endswith("no-such-replay")


def test_serve_accepts_start_file_alias_and_positional_recording() -> None:
    from vantage.cli import build_parser

    root = build_parser()
    a = root.parse_args(["serve", "--start-file=x.vrec"])
    assert a.recording == Path("x.vrec") and a.start_file is None
    b = root.parse_args(["serve", "y.vrec", "--replay-dir", "/a", "--replay-dir", "/b"])
    assert b.start_file == Path("y.vrec") and b.replay_dir == [Path("/a"), Path("/b")]
    assert main(["serve", "--live", "y.vrec"]) == 2  # one source only


def test_live_request_links() -> None:
    from vantage.cli import live_request, replay_game

    assert live_request("vantage://spectate/?lobbyid=7&source=steam") == {
        "confirm": False,
        "lobby": "7",
        "lobby_source": "steam",
    }
    cloud = live_request("captureage://?aoe2record=abc&cloud=true")
    assert cloud == {"confirm": False, "replay": "abc", "cloud": True}
    local = live_request("vantage://?aoe2record=C:\\p\\modes\\Pompeii\\savegame\\r.aoe2record")
    assert local is not None and local["game"] == 1 and local["cloud"] is False
    assert replay_game("C:\\p\\savegame\\r.aoe2record") == 2 and replay_game("x") is None
    assert live_request("vantage://") == {"confirm": False}
    assert live_request("/tmp/not-a-link") is None


def test_register_handler_writes_desktop_entry_and_mime_type(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("sys.platform", "linux")  # the freedesktop handler
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "share"))
    assert main(["register-handler", "--no-update", "--port", "8799"]) == 0
    desktop = (tmp_path / "share" / "applications" / "vantage.desktop").read_text()
    assert "x-scheme-handler/vantage;application/x-vantage-recording;" in desktop
    assert "open-url --port 8799 %u" in desktop and "captureage" not in desktop
    mime = (tmp_path / "share" / "mime" / "packages" / "vantage-recording.xml").read_text()
    assert '<glob pattern="*.vrec"/>' in mime
    ran: list[list[str]] = []
    monkeypatch.setattr("shutil.which", lambda name: "/bin/" + name)
    monkeypatch.setattr(
        "subprocess.run", lambda cmd, **kw: ran.append(cmd) or type("R", (), {"returncode": 0})
    )
    assert main(["register-handler"]) == 0
    assert ["xdg-mime", "default", "vantage.desktop", "x-scheme-handler/vantage"] in ran
    assert "captureage" not in capsys.readouterr().out


def test_register_handler_can_take_and_release_captureage_links(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("sys.platform", "linux")  # the freedesktop handler
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "share"))
    ran: list[list[str]] = []

    class Done:
        returncode = 0
        stdout = "captureage-bridge.desktop\n"

    def fake_run(cmd: list[str], **kw: object) -> Done:
        ran.append(cmd)
        return Done()

    monkeypatch.setattr("shutil.which", lambda name: "/bin/" + name)
    monkeypatch.setattr("subprocess.run", fake_run)
    assert main(["register-handler", "--captureage"]) == 0
    desktop = (tmp_path / "share" / "applications" / "vantage.desktop").read_text()
    assert "x-scheme-handler/captureage;" in desktop
    # Runs in its own scope, not inside the URL portal's memory-capped cgroup.
    assert "Exec=systemd-run --user --scope --slice=app.slice --quiet " in desktop
    assert ["xdg-mime", "default", "vantage.desktop", "x-scheme-handler/captureage"] in ran
    portal = next(c for c in ran if c[0] == "busctl")  # the portal remembers Vantage: no chooser
    assert portal[4] == "/org/freedesktop/impl/portal/PermissionStore"
    assert portal[-8:] == [
        "desktop-used-apps", "true", "x-scheme-handler/captureage", "", "3", "vantage", "3", "3"
    ]  # fmt: skip
    remembered = tmp_path / "share" / "vantage" / "captureage-previous-handler"
    assert remembered.read_text().strip() == "captureage-bridge.desktop"
    ran.clear()
    assert main(["register-handler", "--release-captureage"]) == 0
    previous = "captureage-bridge.desktop"
    assert ran[0] == ["xdg-mime", "default", previous, "x-scheme-handler/captureage"]
    assert ran[1][-4:] == ["sss", "desktop-used-apps", "x-scheme-handler/captureage", ""]


def test_open_url_hands_off_to_a_running_server(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import threading

    from vantage.cli import _post_running
    from vantage.gamedata import GameData
    from vantage.server import Session, serve

    monkeypatch.setenv("VANTAGE_DATA_DIR", str(tmp_path / "data"))
    session = Session(GameData(None), tmp_path)
    srv = serve("127.0.0.1", 0, session, [])
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    port = srv.server_address[1]
    opened: list[str] = []
    monkeypatch.setattr("webbrowser.open", opened.append)
    try:
        rec = _recording(tmp_path)
        assert main(["open-url", str(rec), "--port", str(port)]) == 0
        assert session.mode == "recording"
        assert opened == [f"http://127.0.0.1:{port}/"]  # the click brings Vantage up
    finally:
        session.stop()
        srv.shutdown()
        srv.server_close()
    assert _post_running(port, "/api/open_url", {"url": "x"}) is None  # nobody there now


@pytest.mark.skipif(sys.platform == "win32", reason="os.kill(SIGINT) terminates on Windows")
def test_record_stops_cleanly_on_sigint(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import os
    import signal
    import threading
    from types import SimpleNamespace

    from vantage import live
    from vantage.frames import read_frames

    frames = game_frames(6)
    asked: dict[str, Any] = {}

    class FakeGame:
        def connect(self, timeout: float = 5.0) -> FakeGame:
            return self

        def info(self) -> Any:
            return SimpleNamespace(game_version=1, api_version=20, selected_mode="")

        def frames(self, resolution_ms: int = 0, **kw: Any) -> Any:
            asked.update(kw)
            yield from frames
            threading.Timer(0.2, os.kill, (os.getpid(), signal.SIGINT)).start()
            threading.Event().wait()  # an open stream that never ends

        def close(self) -> None:
            pass

    monkeypatch.setattr(live, "LiveGame", FakeGame)
    before = signal.getsignal(signal.SIGINT)
    out = tmp_path / "r.vrec"
    monkeypatch.setattr(
        "vantage.gamedata.GameData.particle_definitions", ["fire_large", "smoke_chimney"]
    )
    assert main(["record", "--quiet-seconds", "30", str(out)]) == 0
    assert len(list(read_frames(out))) == len(frames)
    # Effects are recorded unless --no-particles: every effect the game defines.
    assert asked == {"particles": True, "particle_whitelist": ["fire_large", "smoke_chimney"]}
    assert signal.getsignal(signal.SIGINT) is before


def _windows(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Any, list[int]]:
    """A fake registry and Explorer notifications, as on Windows."""
    import sys

    from tests.helpers import FakeWinreg
    from vantage import cli

    reg = FakeWinreg()
    monkeypatch.setitem(sys.modules, "winreg", reg)
    monkeypatch.setattr("sys.platform", "win32")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local"))
    monkeypatch.setattr("shutil.which", lambda name: "C:\\Py\\Scripts\\vantage.exe")
    notified: list[int] = []
    monkeypatch.setattr(cli, "_notify_associations_changed", lambda: notified.append(1))
    return reg, notified


def test_register_handler_on_windows_writes_per_user_classes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reg, notified = _windows(tmp_path, monkeypatch)
    hkcu = reg.HKEY_CURRENT_USER
    assert main(["register-handler", "--port", "8799"]) == 0
    command = '"C:\\Py\\Scripts\\vantage.exe" open-url --port 8799 "%1"'
    assert reg.get(hkcu, r"Software\Classes\vantage", "URL Protocol") == ""
    assert reg.get(hkcu, r"Software\Classes\vantage\shell\open\command") == command
    assert reg.get(hkcu, r"Software\Classes\.vrec") == "Vantage.Recording"
    assert reg.get(hkcu, r"Software\Classes\Vantage.Recording\shell\open\command") == command
    assert not any("captureage" in path for _, path in reg.keys)
    assert notified == [1]
    assert main(["register-handler", "--no-update"]) == 0
    assert notified == [1]
    assert main(["register-handler", "--release-captureage"]) == 1  # nothing taken


def test_register_handler_on_windows_takes_and_releases_captureage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reg, _ = _windows(tmp_path, monkeypatch)
    hkcu = reg.HKEY_CURRENT_USER
    key = r"Software\Classes\captureage\shell\open\command"
    theirs = '"C:\\CaptureAge\\CaptureAge.exe" "%1"'
    reg.set(hkcu, key, "", theirs)
    assert main(["register-handler", "--captureage"]) == 0
    assert reg.get(hkcu, key) == '"C:\\Py\\Scripts\\vantage.exe" open-url --port 8740 "%1"'
    assert main(["register-handler", "--captureage"]) == 0  # again: theirs stays remembered
    remembered = tmp_path / "Local" / "Vantage" / "captureage-previous-handler"
    assert remembered.read_text().strip() == theirs
    assert main(["register-handler", "--release-captureage"]) == 0
    assert reg.get(hkcu, key) == theirs and not remembered.exists()

    # No per-user handler before: releasing removes the key Vantage made.
    reg.keys.clear()
    assert main(["register-handler", "--captureage"]) == 0
    assert reg.get(hkcu, r"Software\Classes\captureage", "URL Protocol") == ""
    assert main(["register-handler", "--release-captureage"]) == 0
    assert not any("captureage" in path for _, path in reg.keys)
    assert reg.get(hkcu, r"Software\Classes\vantage\shell\open\command") is not None


def test_no_command_prints_help(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([]) == 2
    out = capsys.readouterr().out
    assert "usage: vantage" in out and "doctor" in out and "vantage serve --open" in out


def test_serve_banner_says_where_to_go_and_what_is_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VANTAGE_CERTS", str(tmp_path / "certs"))
    text = serve_banner("http://127.0.0.1:8740/", None, tmp_path, opening=False)
    assert text.startswith("Vantage is running at http://127.0.0.1:8740/")
    assert "--open" in text and "Game install: not found" in text
    assert "certificate files missing" in text and "wiki/Live-games" in text
    certs = tmp_path / "certs"
    certs.mkdir()
    for name in ("certificate-authority.pem", "cade-client.pem", "cade-client.key"):
        (certs / name).write_text("x")
    text = serve_banner("http://127.0.0.1:8740/", tmp_path, tmp_path, opening=True)
    assert "--open" not in text and "certificate" not in text
    assert f"no AoE2DE_s.exe in {tmp_path}" in text
    (tmp_path / "AoE2DE_s.exe").write_bytes(b"")
    text = serve_banner("http://127.0.0.1:8740/", tmp_path, tmp_path, opening=True)
    assert f"Game install: {tmp_path}\n" in text
