"""Vantage's per-user folders, by operating system."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def config_dir() -> Path:
    """Vantage's per-user configuration folder."""
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(base) / "Vantage"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Vantage"
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "vantage"


def local_data_dir() -> Path:
    """Vantage's per-user data folder (recordings, caches, user content); local,
    not roaming, on Windows because recordings and caches are large."""
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "Vantage"
    return Path("~/.local/share/vantage").expanduser()
