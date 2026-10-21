"""vantage.doctor: the setup checklist."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from vantage.certs import CERT_FILES
from vantage.cli import main
from vantage.doctor import FAIL, OK, WARN, Check, report, run_checks


def _by_label(checks: list[Check]) -> dict[str, Check]:
    return {c.label: c for c in checks}


def test_a_bare_machine_can_still_play_recordings(tmp_path: Path) -> None:
    checks = run_checks(
        tmp_path / "recs",
        None,
        [tmp_path / "nowhere"],
        certs=tmp_path / "certs",
        probe=lambda: False,
    )
    got = _by_label(checks)
    assert got["Python"].status == OK
    assert got["Game install"].status == WARN
    assert got["Certificates"].status == WARN
    assert all(name in got["Certificates"].detail for name in CERT_FILES)
    assert "wiki/Live-games" in got["Certificates"].hint
    assert got["Game running"].status == WARN
    assert got["Replay folders"].status == WARN
    assert got["Recordings folder"].status == OK
    assert "created on first use" in got["Recordings folder"].detail
    text, code = report(checks)
    assert code == 0
    assert "Ready for recordings" in text
    assert "-> start Age of Empires II" in text


def test_everything_in_place_is_ready_for_live_games(tmp_path: Path) -> None:
    certs = tmp_path / "certs"
    certs.mkdir()
    for name in CERT_FILES:
        (certs / name).write_text("x")
    replays = tmp_path / "savegame"
    replays.mkdir()
    (replays / "a.aoe2record").write_bytes(b"")
    recs = tmp_path / "recs"
    recs.mkdir()
    (recs / "g.vrec").write_bytes(b"")
    (tmp_path / "AoE2DE_s.exe").write_bytes(b"")
    checks = run_checks(recs, tmp_path, [replays], certs=certs, probe=lambda: True)
    assert {c.status for c in checks} == {OK}
    got = _by_label(checks)
    assert got["Replay folders"].detail == "1 folder, 1 replays"
    assert got["Recordings folder"].detail.endswith("(1 recordings)")
    text, code = report(checks)
    assert code == 0 and "Ready: recordings, live games and replays." in text
    assert "->" not in text  # no hints when nothing is wrong


def test_an_old_python_or_an_unusable_recordings_folder_fails(tmp_path: Path) -> None:
    blocker = tmp_path / "recs"
    blocker.write_text("not a folder")
    checks = run_checks(blocker, None, [], certs=tmp_path, probe=lambda: False, version=(3, 11, 9))
    got = _by_label(checks)
    assert got["Python"].status == FAIL and "3.12" in got["Python"].hint
    assert got["Recordings folder"].status == FAIL
    text, code = report(checks)
    assert code == 1 and "cannot run here yet" in text


def test_a_game_dir_without_the_game_is_flagged(tmp_path: Path) -> None:
    got = _by_label(run_checks(tmp_path, tmp_path, [], certs=tmp_path, probe=lambda: True))
    assert got["Game install"].status == WARN
    assert got["Game install"].detail == f"no AoE2DE_s.exe in {tmp_path}"


def test_missing_grpc_is_a_warning(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "grpc", None)  # import grpc -> ImportError
    got = _by_label(run_checks(tmp_path, None, [], certs=tmp_path, probe=lambda: True))
    assert got["gRPC and protobuf"].status == WARN
    assert "grpc" in got["gRPC and protobuf"].detail


def test_doctor_command(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VANTAGE_CERTS", str(tmp_path / "certs"))
    monkeypatch.setenv("VANTAGE_GAME_DIR", str(tmp_path / "none"))
    monkeypatch.setattr("vantage.doctor.port_open", lambda: False)
    monkeypatch.setattr("vantage.server.default_replay_dirs", lambda: [])
    assert main(["doctor", "--recordings-dir", str(tmp_path / "recs")]) == 0
    out = capsys.readouterr().out
    assert out.startswith("Vantage ")
    assert "Certificates: missing" in out and str(tmp_path / "certs") in out
