"""The convenient V32 entry must preserve its profile and headless boundary."""

import importlib.util
import os
from pathlib import Path
from unittest.mock import patch

import pytest

ENTRY = Path(__file__).resolve().parents[1] / "vantage-v32.py"
SPEC = importlib.util.spec_from_file_location("vantage_v32_entry", ENTRY)
entry = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(entry)


class ExecIntercept(Exception):
    pass


def test_entry_forwards_replay_profiles_and_optional_arguments_headlessly(tmp_path):
    replay = tmp_path / "match.aoe2record"
    replay.write_bytes(b"fixture")
    (tmp_path / "other").mkdir()
    captured = {}

    def intercept(executable, argv, env):
        captured.update(executable=executable, argv=argv, env=env)
        raise ExecIntercept

    options = [
        str(ENTRY),
        str(replay),
        "--game-dir",
        str(tmp_path / "game"),
        "--replay-root",
        str(tmp_path / "other"),
        "--reuse-job",
        str(tmp_path / "job"),
        "--cache-dir",
        str(tmp_path / "cache"),
        "--port",
        "9876",
    ]
    with (
        patch("sys.argv", options),
        patch.dict(os.environ, {"DISPLAY": ":0", "WAYLAND_DISPLAY": "wayland-0"}),
        patch.object(entry.os, "execve", side_effect=intercept),
        pytest.raises(ExecIntercept),
    ):
        entry.main()
    argv = captured["argv"]
    assert argv[1:4] == ["-B", "-m", "vantage.native_v32_serve"]
    assert argv[argv.index("--replay") + 1] == str(replay)
    assert argv[argv.index("--source-profile-sha256") + 1] == entry.SOURCE_SHA
    assert argv[argv.index("--runtime-profile-sha256") + 1] == entry.RUNTIME_SHA
    assert argv[argv.index("--encoder-config-sha256") + 1] == entry.ENCODER_SHA
    roots = [argv[i + 1] for i, v in enumerate(argv) if v == "--replay-root"]
    assert roots == [str(tmp_path), str(tmp_path / "other")]
    for flag, value in (("--game-dir", "game"), ("--reuse-job", "job"), ("--cache-dir", "cache")):
        assert argv[argv.index(flag) + 1] == str(tmp_path / value)
    assert argv[argv.index("--port") + 1] == "9876"
    assert "--runtime-timeout" not in argv and "--encoder-timeout" not in argv
    assert "DISPLAY" not in captured["env"] and "WAYLAND_DISPLAY" not in captured["env"]


def test_replay_parent_and_duplicate_roots_are_forwarded_once(tmp_path):
    replay = tmp_path / "match.aoe2record"
    replay.write_bytes(b"fixture")
    options = [
        str(ENTRY),
        str(replay),
        "--replay-root",
        str(tmp_path),
        "--replay-root",
        str(tmp_path / "."),
    ]
    with (
        patch("sys.argv", options),
        patch.object(entry.os, "execve", side_effect=ExecIntercept) as execute,
        pytest.raises(ExecIntercept),
    ):
        entry.main()
    argv = execute.call_args.args[1]
    roots = [argv[i + 1] for i, value in enumerate(argv) if value == "--replay-root"]
    assert roots == [str(tmp_path)]


@pytest.mark.parametrize("name", ["missing.aoe2record", "not-a-replay.txt"])
def test_invalid_replay_never_starts_server(tmp_path, name):
    path = tmp_path / name
    if path.suffix == ".txt":
        path.write_bytes(b"fixture")
    with patch("sys.argv", [str(ENTRY), str(path)]), patch.object(entry.os, "execve") as execute:
        with pytest.raises(SystemExit) as exc:
            entry.main()
        assert exc.value.code == 2
        execute.assert_not_called()


def test_timeout_overrides_are_forwarded(tmp_path):
    replay = tmp_path / "match.aoe2record"
    replay.write_bytes(b"fixture")
    options = [str(ENTRY), str(replay), "--runtime-timeout", "25", "--encoder-timeout", "30"]
    with (
        patch("sys.argv", options),
        patch.object(entry.os, "execve", side_effect=ExecIntercept) as execute,
        pytest.raises(ExecIntercept),
    ):
        entry.main()
    argv = execute.call_args.args[1]
    assert argv[argv.index("--runtime-timeout") + 1] == "25.0"
    assert argv[argv.index("--encoder-timeout") + 1] == "30.0"


def test_fast_encoder_requires_explicit_opt_in(tmp_path):
    replay = tmp_path / "match.aoe2record"
    replay.write_bytes(b"fixture")
    with (
        patch("sys.argv", [str(ENTRY), str(replay), "--fast-encoder"]),
        patch.object(entry.os, "execve", side_effect=ExecIntercept) as execute,
        pytest.raises(ExecIntercept),
    ):
        entry.main()
    argv = execute.call_args.args[1]
    selected = argv[argv.index("--encoder-config") + 1]
    assert selected == str(entry.PROFILES / "encoder-fast-config.json")
    assert argv[argv.index("--encoder-config-sha256") + 1] == entry.FAST_ENCODER_SHA
