"""Content identity for a complete viewer deployment, including its web modules."""

from __future__ import annotations

import hashlib
from functools import lru_cache
from pathlib import Path


def deployment_revision() -> str:
    root = Path(__file__).parent
    paths = sorted(
        p
        for p in root.rglob("*")
        if p.is_file()
        and p.suffix in (".py", ".json", ".js", ".css", ".html")
        and "__pycache__" not in p.parts
    )
    return _revision(tuple((str(p), p.stat().st_size, p.stat().st_mtime_ns) for p in paths))


def asset_revision() -> str:
    """Identity of the code that turns game files into what the browser is sent
    (sprite strips, icons, terrain, particle atlases, sounds): the Python side
    only. A change to the interface (scripts, styles, markup, translations)
    changes no asset, and must not make every browser fetch them all again."""
    root = Path(__file__).parent
    paths = sorted(
        p
        for p in root.rglob("*.py")
        if p.is_file() and "__pycache__" not in p.parts and "web" not in p.relative_to(root).parts
    )
    return _revision(tuple((str(p), p.stat().st_size, p.stat().st_mtime_ns) for p in paths))


@lru_cache(maxsize=4)
def _revision(files: tuple[tuple[str, int, int], ...]) -> str:
    digest = hashlib.sha256()
    root = Path(__file__).parent
    for name, _, _ in files:
        path = Path(name)
        digest.update(str(path.relative_to(root)).encode() + b"\0")
        digest.update(path.read_bytes())
    return digest.hexdigest()[:16]
