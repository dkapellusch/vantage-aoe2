"""Provenance for persisted analysis, independent of the package release number.

Editable installs often keep the same version across many changes. Fingerprint
the installed Python sources and decoding schema so consumers can invalidate
derived statistics when their actual implementation changes.
"""

from __future__ import annotations

import hashlib
from functools import lru_cache
from pathlib import Path
from typing import Any

from vantage.gamedata import GameData

ANALYSIS_SCHEMA = 1


def source_revision(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted([*root.glob("*.py"), *root.glob("*.json")]):
        digest.update(path.name.encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
    return digest.hexdigest()


@lru_cache(maxsize=1)
def engine_revision() -> str:
    return source_revision(Path(__file__).parent)


@lru_cache(maxsize=32)
def _file_revision(path: str, size: int, modified: int) -> str:
    del size, modified  # cache identity; neither alone substitutes for content
    with Path(path).open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def analysis_provenance(data: GameData, *, tc_idle_villagers: int = 120) -> dict[str, Any]:
    if tc_idle_villagers < 1:
        raise ValueError("TC idle villager target must be positive")
    files: dict[str, str] = {}
    for name in ("empires2_x2_p1.dat", "civilizations.json", "eras.json", "unitlines.json"):
        path = data.dat_path(name)
        if path is not None:
            stat = path.stat()
            files[name] = _file_revision(str(path.resolve()), stat.st_size, stat.st_mtime_ns)
    return {
        "schema": ANALYSIS_SCHEMA,
        "engine": engine_revision(),
        "game_build": data.build,
        "game_mode": data.mode,
        "game_data": files,
        "tc_idle_villagers": tc_idle_villagers,
    }
