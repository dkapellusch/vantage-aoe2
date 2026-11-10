"""vantage.paths: per-user folders by operating system."""

from __future__ import annotations

from pathlib import Path

import pytest

from vantage.paths import config_dir, local_data_dir


def test_local_data_dir_per_os(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sys.platform", "linux")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))  # Path.home() on Windows
    assert local_data_dir() == tmp_path / ".local" / "share" / "vantage"
    monkeypatch.setattr("sys.platform", "win32")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local"))
    monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))
    assert local_data_dir() == tmp_path / "Local" / "Vantage"
    assert config_dir() == tmp_path / "Roaming" / "Vantage"
    monkeypatch.delenv("LOCALAPPDATA")
    assert local_data_dir() == tmp_path / "AppData" / "Local" / "Vantage"
