"""Shared test configuration.

Some native-replay tests check the replay engine against research captures
(artifacts/game-internals/...) that live with the development copy and are too
large to ship. Where artifacts/ is missing, a test module that reads them
(directly, or through a test module it imports) is skipped with that reason,
rather than failing on a missing file.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT / "artifacts" / "game-internals"
_READS = re.compile(r"""["']artifacts/game-internals""")
_IMPORTS = re.compile(r"^(?:from|import) (test_\w+)", re.M)


def _needs_artifacts(path: Path, seen: dict[Path, bool]) -> bool:
    if path in seen:
        return seen[path]
    seen[path] = False  # cycles: decided by the rest of the graph
    text = path.read_text(encoding="utf-8", errors="replace") if path.is_file() else ""
    needs = bool(_READS.search(text)) or any(
        _needs_artifacts(path.with_name(f"{name}.py"), seen) for name in _IMPORTS.findall(text)
    )
    seen[path] = needs
    return needs


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if ARTIFACTS.is_dir():
        return
    skip = pytest.mark.skip(reason=f"needs the research captures in {ARTIFACTS}")
    seen: dict[Path, bool] = {}
    for item in items:
        path = Path(str(item.fspath))
        if path.suffix == ".py" and _needs_artifacts(path, seen):
            item.add_marker(skip)
