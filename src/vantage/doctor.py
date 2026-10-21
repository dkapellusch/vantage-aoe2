"""``vantage doctor``: what this machine can watch, and what is missing.

Recordings (``.vrec``) need only Python; live games and replays also need gRPC,
the client certificate (:mod:`vantage.certs`) and the game running; the game
install adds icons, sprites and sounds.
"""

from __future__ import annotations

import importlib
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from vantage.certs import LIVE_GAMES_DOCS, certs_dir, missing_cert_files
from vantage.live import GAME_HOST, GAME_PORT, port_open

MIN_PYTHON = (3, 12)
OK, WARN, FAIL = "ok", "warn", "FAIL"


@dataclass(frozen=True, slots=True)
class Check:
    label: str
    status: str
    detail: str
    hint: str = ""


def _python(version: Sequence[int]) -> Check:
    text = ".".join(str(v) for v in version[:3])
    if tuple(version[:2]) >= MIN_PYTHON:
        return Check("Python", OK, text)
    need = ".".join(map(str, MIN_PYTHON))
    return Check("Python", FAIL, text, f"Vantage needs Python {need} or newer")


def _grpc() -> Check:
    missing = []
    for name in ("grpc", "google.protobuf"):
        try:
            importlib.import_module(name)
        except ImportError:
            missing.append(name)
    if not missing:
        return Check("gRPC and protobuf", OK, "importable")
    return Check(
        "gRPC and protobuf",
        WARN,
        f"cannot import {', '.join(missing)}",
        "live games and replays need them: reinstall Vantage with its dependencies",
    )


def _game_install(game_dir: Path | None) -> Check:
    if game_dir is not None and (game_dir / "AoE2DE_s.exe").is_file():
        return Check("Game install", OK, str(game_dir))
    if game_dir is not None:
        return Check(
            "Game install", WARN, f"no AoE2DE_s.exe in {game_dir}", "is --game-dir the game folder?"
        )
    return Check(
        "Game install",
        WARN,
        "not found",
        "Vantage still works, with plainer graphics and no sounds; "
        "point it at the game with --game-dir or in Settings",
    )


def _certs(folder: Path) -> Check:
    missing = missing_cert_files(folder)
    if not missing:
        return Check("Certificates", OK, str(folder))
    return Check(
        "Certificates",
        WARN,
        f"missing {', '.join(missing)} in {folder}",
        f"live games and replays need them: {LIVE_GAMES_DOCS}",
    )


def _game_api(answering: bool) -> Check:
    where = f"{GAME_HOST}:{GAME_PORT}"
    if answering:
        return Check("Game running", OK, f"something answers on {where}")
    return Check(
        "Game running",
        WARN,
        f"nothing answers on {where}",
        "start Age of Empires II: DE to watch live games and replays",
    )


def _replays(dirs: Sequence[Path]) -> Check:
    found = [d for d in dirs if d.is_dir()]
    if not found:
        return Check("Replay folders", WARN, "none found", "use --replay-dir to add one")
    count = sum(1 for d in found for _ in d.glob("*.aoe2record"))
    folders = "folder" if len(found) == 1 else "folders"
    return Check("Replay folders", OK, f"{len(found)} {folders}, {count} replays")


def _recordings(folder: Path) -> Check:
    if folder.exists() and not folder.is_dir():
        return Check("Recordings folder", FAIL, f"{folder} is not a folder")
    if not folder.is_dir():
        return Check("Recordings folder", OK, f"{folder} (created on first use)")
    count = sum(1 for _ in folder.glob("*.vrec"))
    return Check("Recordings folder", OK, f"{folder} ({count} recordings)")


def run_checks(
    recordings_dir: Path,
    game_dir: Path | None,
    replay_dirs: Sequence[Path],
    *,
    certs: Path | None = None,
    probe: Callable[[], bool] | None = None,
    version: Sequence[int] = tuple(sys.version_info[:3]),
) -> list[Check]:
    return [
        _python(version),
        _grpc(),
        _game_install(game_dir),
        _certs(certs or certs_dir()),
        _game_api((probe or port_open)()),
        _replays(replay_dirs),
        _recordings(recordings_dir),
    ]


def report(checks: Sequence[Check]) -> tuple[str, int]:
    """The checklist as text, and the exit code: 0 when at least recordings
    can be played (no check failed)."""
    lines = []
    for c in checks:
        lines.append(f"  {c.status:<4}  {c.label}: {c.detail}")
        if c.hint and c.status != OK:
            lines.append(f"        -> {c.hint}")
    by = {c.label: c.status for c in checks}
    failed = FAIL in by.values()
    live = all(by.get(k) == OK for k in ("gRPC and protobuf", "Certificates", "Game running"))
    lines.append("")
    if failed:
        lines.append("Vantage cannot run here yet: fix the FAIL lines above.")
    elif live:
        lines.append("Ready: recordings, live games and replays.")
    else:
        lines.append("Ready for recordings (.vrec). Live games and replays: see the warnings.")
    return "\n".join(lines), 1 if failed else 0
