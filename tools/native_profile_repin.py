#!/usr/bin/env python3
"""Re-pin native conversion profiles after their pinned inputs changed.

A profile pins every input it runs with: {"path", "bytes", "sha256"} rows for
research scripts, the backend sources, Wine, bwrap, Xvfb, and other profiles.
A system upgrade, or the development copy's forge/spectate becoming an alias of
this package, makes those rows stale and the conversion refuses to start.

This writes re-pinned copies of a set of profiles to --out-dir (the originals
stay as the evidence they are):

- a changed file is pinned as it is now;
- a missing ``<alias-from>/X`` is pinned as ``<alias-to>/X``, the file the
  alias now loads;
- a missing file under one of the --drop prefixes (deleted duplicate tests)
  is removed from its list;
- a row naming another profile of the set points at that profile's re-pinned
  copy, so the set stays consistent (profiles are written leaves first).

Anything else that is missing is an error: nothing is silently unpinned. Each
copy records what changed under "repinned". Re-pinning accepts the current
inputs; run a conversion afterwards to show they still produce the original
game's checksums.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

PIN_KEYS = {"path", "bytes", "sha256"}
_DROP = object()


def pin(path: Path) -> dict[str, Any]:
    path = path.resolve(strict=True)
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    return {"path": str(path), "bytes": path.stat().st_size, "sha256": digest}


def is_pin(value: Any) -> bool:
    return isinstance(value, dict) and value.keys() >= PIN_KEYS and isinstance(value["path"], str)


def references(document: Any) -> set[str]:
    found: set[str] = set()

    def walk(value: Any) -> None:
        if is_pin(value):
            found.add(value["path"])
        if isinstance(value, dict):
            for item in value.values():
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(document)
    return found


class Repinner:
    def __init__(
        self,
        alias: tuple[Path, Path] | None,
        drop: list[Path],
        replaced: dict[str, dict[str, Any]],
    ) -> None:
        self.alias, self.drop, self.replaced = alias, drop, replaced
        self.changes: list[dict[str, Any]] = []

    def _row(self, row: dict[str, Any]) -> Any:
        path = row["path"]
        if path in self.replaced:
            new = self.replaced[path]
            self.changes.append({"kind": "profile", "from": path, "to": new["path"]})
            return {**row, **new}
        source = Path(path)
        if source.exists():
            now = pin(source)
            if (now["bytes"], now["sha256"]) == (row["bytes"], row["sha256"]):
                return row
            self.changes.append({"kind": "changed", "path": path, "was": row["sha256"]})
            return {**row, "bytes": now["bytes"], "sha256": now["sha256"]}
        if self.alias is not None and source.is_relative_to(self.alias[0]):
            target = self.alias[1] / source.relative_to(self.alias[0])
            if target.exists():
                self.changes.append({"kind": "alias", "from": path, "to": str(target)})
                return {**row, **pin(target)}
        if any(source.is_relative_to(prefix) for prefix in self.drop):
            self.changes.append({"kind": "dropped", "path": path})
            return _DROP
        raise SystemExit(f"pinned input is missing and cannot be resolved: {path}")

    def rewrite(self, value: Any) -> Any:
        if is_pin(value):
            row = self._row(value)
            if row is _DROP:
                return _DROP
            value = row
        if isinstance(value, dict):
            out = {}
            for key, item in value.items():
                new = self.rewrite(item)
                if new is _DROP:
                    raise SystemExit(f"cannot drop a pin that is not a list item: {key}")
                out[key] = new
            return out
        if isinstance(value, list):
            return [new for new in (self.rewrite(item) for item in value) if new is not _DROP]
        return value


def repin(
    profiles: list[Path],
    out_dir: Path,
    alias: tuple[Path, Path] | None,
    drop: list[Path],
    today: str,
) -> dict[str, dict[str, Any]]:
    """Write re-pinned copies of the stale profiles; returns {original path: pin of the copy}.

    A profile whose pins all still hold is not copied.
    """
    profiles = [p.resolve(strict=True) for p in profiles]
    names = [p.name for p in profiles]
    if len(set(names)) != len(names):
        raise SystemExit("profiles must have distinct file names")
    documents = {str(p): json.loads(p.read_text()) for p in profiles}
    pending = set(documents)
    out_dir.mkdir(parents=True, exist_ok=True)
    replaced: dict[str, dict[str, Any]] = {}
    while pending:
        ready = [p for p in sorted(pending) if not (references(documents[p]) & (pending - {p}))]
        if not ready:
            raise SystemExit(f"profiles reference each other in a cycle: {sorted(pending)}")
        for path in ready:
            original = Path(path)
            work = Repinner(alias, drop, replaced)
            document = work.rewrite(documents[path])
            pending.discard(path)
            if not work.changes:
                continue  # still valid as it is: keep the original (and its hash)
            if isinstance(document, dict):
                document["repinned"] = {
                    "date": today,
                    "from": pin(original),
                    "changes": work.changes,
                    "note": "Re-pinned copy; the original is unchanged. Run a conversion to "
                    "confirm the current inputs still reproduce the original checksums.",
                }
            target = out_dir / original.name
            target.write_text(json.dumps(document, indent=2, sort_keys=False) + "\n")
            replaced[path] = pin(target)
    return replaced


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("profiles", type=Path, nargs="+")
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--alias-from", type=Path, help="a package directory that became an alias")
    parser.add_argument("--alias-to", type=Path, help="the package directory it aliases")
    parser.add_argument("--drop", type=Path, action="append", default=[], help="prefix to drop")
    args = parser.parse_args(argv)
    if (args.alias_from is None) != (args.alias_to is None):
        parser.error("--alias-from and --alias-to go together")
    alias = (args.alias_from.resolve(), args.alias_to.resolve()) if args.alias_from else None
    result = repin(
        args.profiles,
        args.out_dir.resolve(),
        alias,
        [p.resolve() for p in args.drop],
        dt.date.today().isoformat(),
    )
    for original, copy in result.items():
        print(f"{copy['sha256']}  {copy['path']}  (from {original})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
