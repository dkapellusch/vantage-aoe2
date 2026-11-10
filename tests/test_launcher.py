"""vantage.launcher: the start-the-game state machine (never starts the game)."""

from __future__ import annotations

from pathlib import Path

import pytest

from vantage.launcher import (
    LAUNCH_DEADLINE_S,
    GameLauncher,
    game_process_running,
    steam_app_state,
)


class _Rig:
    """Fake runner, Steam state, process probe and clock."""

    def __init__(self, tmp_path: Path, exe: bool = True) -> None:
        self.game = tmp_path / "AoE2DE"
        self.game.mkdir()
        if exe:
            (self.game / "AoE2DE_s.exe").write_bytes(b"MZ")
        (self.game / "steam_appid.txt").write_text("813780")
        self.calls: list[list[str]] = []
        self.accept: list[bool] = [True]
        self.state = "stopped"
        self.proc = False
        self.now = 1000.0

    def run(self, argv: list[str]) -> bool:
        self.calls.append(argv)
        return self.accept.pop(0) if self.accept else False

    def launcher(self) -> GameLauncher:
        return GameLauncher(
            lambda: self.game,
            runner=self.run,
            app_state=lambda: self.state,
            process_running=lambda: self.proc,
            clock=lambda: self.now,
        )


def test_no_game_exe(tmp_path: Path) -> None:
    rig = _Rig(tmp_path, exe=False)
    assert rig.launcher().launch()["status"] == "noGameExe"
    assert rig.calls == []
    assert GameLauncher(lambda: None, runner=rig.run).launch()["status"] == "noGameExe"


def test_launch_through_steam_then_running_then_exited(tmp_path: Path) -> None:
    rig = _Rig(tmp_path)
    gl = rig.launcher()
    assert gl.status()["status"] == "unknown"
    assert gl.launch()["status"] == "opening"
    assert rig.calls == [["steam", "-applaunch", "813780", "SKIPINTRO"]]
    assert not (rig.game / "steam_appid.txt").exists()  # the legacy file goes
    rig.now += 3
    assert gl.status()["status"] == "opening"
    rig.state = "running"
    rig.now += 3
    assert gl.status()["status"] == "running"
    rig.state, rig.proc = "stopped", False
    rig.now += 3
    st = gl.status()
    assert st["status"] == "exited" and "closed" in st["detail"]


def test_fallback_url_and_launch_failed(tmp_path: Path) -> None:
    from vantage.launcher import OPEN

    rig = _Rig(tmp_path)
    rig.accept = [False, True]
    assert rig.launcher().launch()["status"] == "opening"
    assert rig.calls[1] == [OPEN, "steam://rungameid/813780"]
    (tmp_path / "b").mkdir()
    rig2 = _Rig(tmp_path / "b")
    rig2.accept = [False, False]
    out = rig2.launcher().launch()
    assert out["status"] == "launchFailed" and "Steam" in out["detail"]


def test_deadline_and_updating_restarts_it(tmp_path: Path) -> None:
    rig = _Rig(tmp_path)
    gl = rig.launcher()
    gl.launch()
    rig.state = "updating"
    rig.now += LAUNCH_DEADLINE_S - 1
    assert gl.status()["status"] == "opening"
    rig.now += 100  # past the original deadline, but updating restarted it
    assert gl.status()["status"] == "opening"
    rig.state = "stopped"
    rig.now += LAUNCH_DEADLINE_S + 1
    assert gl.status()["status"] == "launchFailed"


def test_already_running_is_not_launched_again(tmp_path: Path) -> None:
    rig = _Rig(tmp_path)
    rig.proc = True
    assert rig.launcher().launch()["status"] == "running"
    assert rig.calls == []


def test_stream_states_map_onto_statuses(tmp_path: Path) -> None:
    rig = _Rig(tmp_path)
    gl = rig.launcher()
    assert gl.launch(connected=True)["status"] == "connected" and rig.calls == []
    assert gl.status(stream="closed-player")["status"] == "runningPlayer"
    assert gl.status(stream="closed-needs-update")["status"] == "runningCadeNeedsUpdate"
    assert gl.status(connected=True)["status"] == "connected"
    # the connection drops and the game is gone
    out = gl.status(connected=False)
    assert out["status"] == "exited" and "connection lost" in out["detail"]


def test_steam_registry_and_process_probes(tmp_path: Path) -> None:
    assert steam_app_state(home=tmp_path) == "unknown"
    reg = tmp_path / ".steam" / "registry.vdf"
    reg.parent.mkdir()
    reg.write_text('"Apps"\n{\n\t"813780"\n\t{\n\t\t"Running"\t\t"1"\n\t}\n}\n')
    assert steam_app_state(home=tmp_path) == "running"
    reg.write_text(
        '"Apps"\n{\n\t"813780"\n\t{\n\t\t"Updating"\t\t"1"\n\t\t"Running"\t\t"0"\n\t}\n}\n'
    )
    assert steam_app_state(home=tmp_path) == "updating"
    reg.write_text('"Apps"\n{\n\t"1"\n\t{\n\t}\n}\n')
    assert steam_app_state(home=tmp_path) == "stopped"
    proc = tmp_path / "proc"
    (proc / "42").mkdir(parents=True)
    (proc / "42" / "cmdline").write_bytes(b"/x/AoE2DE_s.exe\x00-arg")
    (proc / "self").mkdir()
    assert game_process_running(proc) is True
    (proc / "42" / "cmdline").write_bytes(b"bash")
    assert game_process_running(proc) is False


def test_no_launch_guard_blocks_the_default_runner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = _Rig(tmp_path)
    monkeypatch.setenv("VANTAGE_NO_LAUNCH", "1")
    guarded = GameLauncher(
        lambda: rig.game, app_state=lambda: "stopped", process_running=lambda: False
    )
    out = guarded.launch()
    assert out["status"] == "launchFailed" and "VANTAGE_NO_LAUNCH" in out["detail"]
    assert (rig.game / "steam_appid.txt").exists()  # nothing was touched
    assert rig.launcher().launch()["status"] == "opening"  # an injected runner is unaffected


def test_only_the_legacy_app_id_marker_is_removed(tmp_path: Path) -> None:
    rig = _Rig(tmp_path)
    marker = rig.game / "steam_appid.txt"
    marker.write_text("something the user put here\n")
    rig.launcher().launch()
    assert marker.read_text() == "something the user put here\n"


def test_windows_probes_read_steams_registry_key_and_tasklist(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import subprocess
    import sys

    from tests.helpers import FakeWinreg

    reg = FakeWinreg()
    monkeypatch.setitem(sys.modules, "winreg", reg)
    monkeypatch.setattr("sys.platform", "win32")
    hkcu = reg.HKEY_CURRENT_USER
    assert steam_app_state() == "unknown"  # no Steam
    reg.set(hkcu, r"Software\Valve\Steam", "SteamPath", "c:/program files (x86)/steam")
    assert steam_app_state() == "stopped"
    app = r"Software\Valve\Steam\Apps\813780"
    reg.set(hkcu, app, "Running", 1)
    assert steam_app_state() == "running"
    reg.set(hkcu, app, "Updating", 1)
    assert steam_app_state() == "updating"

    ran: list[list[str]] = []
    stdout = '"AoE2DE_s.exe","4242","Console","1","2,000,000 K"\r\n'

    def fake_run(cmd: list[str], **kw: object) -> subprocess.CompletedProcess[str]:
        ran.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout, "")

    monkeypatch.setattr("subprocess.run", fake_run)
    assert game_process_running(tmp_path / "no-proc") is True
    assert ran[0][:3] == ["tasklist", "/FI", "IMAGENAME eq AoE2DE_s.exe"]
    stdout = "INFO: No tasks are running which match the specified criteria.\r\n"
    assert game_process_running(tmp_path / "no-proc") is False


def test_default_runner_opens_links_with_startfile_on_windows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import os

    from vantage.launcher import default_runner

    opened: list[str] = []
    monkeypatch.setattr("sys.platform", "win32")
    monkeypatch.setattr(os, "startfile", opened.append, raising=False)
    assert default_runner(["startfile", "steam://rungameid/813780"]) is True
    assert opened == ["steam://rungameid/813780"]

    def refuse(target: str) -> None:
        raise OSError("no handler")

    monkeypatch.setattr(os, "startfile", refuse, raising=False)
    assert default_runner(["startfile", "steam://rungameid/813780"]) is False
