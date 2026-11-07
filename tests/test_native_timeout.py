"""Serve CLI forwards the configured phase limit through the real NativeConfig."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from vantage import cli, gamedata, native_session, server


def run_serve(tmp_path, monkeypatch, value, *, configured=True):
    parser = cli.build_parser()
    profile = tmp_path / "profile.json"
    profile.write_text("{}")
    arguments = ["serve", "--recordings-dir", str(tmp_path / "recordings")]
    if configured:
        arguments += [
            "--native-profile",
            str(profile),
            "--native-profile-sha256",
            "a" * 64,
            "--native-cache-dir",
            str(tmp_path / "cache"),
            "--native-replay-root",
            str(tmp_path),
        ]
    if value is not None:
        arguments.append(f"--native-timeout={value}")
    args = parser.parse_args(arguments)
    configured_values, calls = [], []

    class Session:
        native = None

        def __init__(self, *unused):
            pass

        def configure_native(self, config):
            configured_values.append(config)
            self.native, self.native_config = object(), config

        def close_native(self):
            calls.append("close")

        def stop(self):
            calls.append("stop")

    def serve(*unused, **unused_keywords):
        calls.append("bind")
        return SimpleNamespace(
            serve_forever=lambda: calls.append("serve"),
            server_close=lambda: calls.append("server_close"),
        )

    monkeypatch.setattr(gamedata, "GameData", lambda *_: object())
    monkeypatch.setattr(gamedata, "find_game_dir", lambda: None)
    monkeypatch.setattr(native_session, "NativeSession", Session)
    monkeypatch.setattr(server, "serve", serve)
    return cli._serve(args), configured_values, calls


@pytest.mark.parametrize("value,expected", [(None, 900), (3600, 3600), (0.1, 0.1), (86400, 86400)])
def test_native_phase_timeout_reaches_real_config(tmp_path, monkeypatch, value, expected):
    result, configured, calls = run_serve(tmp_path, monkeypatch, value)
    assert result == 0 and len(configured) == 1
    assert configured[0].timeout == expected
    assert calls == ["bind", "serve", "close", "stop", "server_close"]


@pytest.mark.parametrize("value", [0, -1, 86400.1, "nan", "inf", "-inf"])
def test_invalid_timeout_fails_before_binding_or_conversion(tmp_path, monkeypatch, value):
    result, configured, calls = run_serve(tmp_path, monkeypatch, value)
    assert result == 2 and configured == []
    assert calls == ["close", "stop"]


def test_timeout_alone_requires_explicit_native_profile(tmp_path, monkeypatch):
    result, configured, calls = run_serve(tmp_path, monkeypatch, 3600, configured=False)
    assert result == 2 and configured == []
    assert calls == ["close", "stop"]
