"""vantage-native.py's launcher starts this package's own server with the isolated converter."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

from vantage import native_isolated_launch, native_jobs


def test_launcher_serves_the_replay_with_the_isolated_converter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    replay = tmp_path / "replays" / "game.aoe2record"
    replay.parent.mkdir()
    replay.write_bytes(b"x")
    profile = tmp_path / "profile.json"
    profile.write_text("{}")
    seen: dict[str, Any] = {}

    def serve(argv: list[str]) -> int:
        seen["argv"] = argv
        seen["converter"] = native_jobs.NativeConfig.converter
        return 0

    monkeypatch.setattr("vantage.cli.main", serve)
    monkeypatch.setattr(native_jobs.NativeConfig, "converter", native_jobs.NativeConfig.converter)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "launch",
            "--replay",
            str(replay),
            "--profile",
            str(profile),
            "--profile-sha256",
            "a" * 64,
            "--cache-dir",
            str(tmp_path / "cache"),
            "--port",
            "9123",
        ],
    )
    for name in ("XDG_CACHE_HOME", "VANTAGE_DATA_DIR"):
        monkeypatch.delenv(name, raising=False)
    assert native_isolated_launch.main() == 0
    argv = seen["argv"]
    assert argv[0] == "serve" and argv[argv.index("--port") + 1] == "9123"
    assert argv[argv.index("--native-replay") + 1] == str(replay.resolve())
    assert argv[argv.index("--native-replay-root") + 1] == str(replay.resolve().parent)
    # The frozen converter is replaced by the isolated (Bubblewrap) one for this process.
    converter = seen["converter"](object())
    assert type(converter).__module__ == "vantage.native_isolated"


def test_cache_inside_the_repository_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    replay = tmp_path / "game.aoe2record"
    replay.write_bytes(b"x")
    profile = tmp_path / "profile.json"
    profile.write_text("{}")
    repo = Path(native_isolated_launch.__file__).resolve().parents[2]
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "launch",
            "--replay",
            str(replay),
            "--profile",
            str(profile),
            "--profile-sha256",
            "a" * 64,
            "--cache-dir",
            str(repo),
        ],
    )
    with pytest.raises(SystemExit) as error:
        native_isolated_launch.main()
    assert error.value.code == 2
