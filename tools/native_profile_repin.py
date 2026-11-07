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

--freeze-repo / --freeze-tree keep a profile on the exact code it was verified
with instead: every pin a profile actually verifies that lies in that
repository (outside its artifacts/) is restored byte for byte, from the
repository's git history or the --search folders, into a read-only tree, and
those pins point there with their hashes unchanged. The copy records the tree
as "research_root", which the backend puts first on the research scripts'
PYTHONPATH. With --scope, only inputs under those prefixes (system binaries,
the backend) are re-pinned when they changed; other rows, such as historical
records inside a profile, are kept exactly as written.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import subprocess
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

PIN_KEYS = {"path", "bytes", "sha256"}
ROLE_KEYS = ("renderer", "template", "encoder", "encoder_profile", "compiler", "wine")
RESEARCH_KINDS = {"vantage_experimental_local_native", "vantage_experimental_v32_encoder"}
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


def _walk_pins(value: Any) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    if is_pin(value):
        found.append(value)
    if isinstance(value, dict):
        for item in value.values():
            found += _walk_pins(item)
    elif isinstance(value, list):
        for item in value:
            found += _walk_pins(item)
    return found


def verified_rows(document: Any) -> list[dict[str, Any]]:
    """The pins a profile's loader actually checks (others are historical records)."""
    if not isinstance(document, dict):
        return []
    if document.get("kind") == "vantage_experimental_local_native":
        roles = [document[k] for k in ROLE_KEYS if is_pin(document.get(k))]
        return [*document.get("pins", []), *roles]
    if {"source_evidence", "source_contracts", "codec_pins"} <= document.keys():
        contracts = [*document["source_contracts"], *document["codec_pins"]]
        return [document["source_evidence"], *contracts]
    return _walk_pins(document)


@dataclass
class Freeze:
    """Exact sources restored into a read-only tree, keyed by (original path, sha256)."""

    repo: Path
    tree: Path
    search: list[Path]
    base: str | None = None  # commit the rest of the --fill folders comes from
    fill: list[str] = field(default_factory=list)  # repository folders to make complete
    rows: dict[tuple[str, str], str] = field(default_factory=dict)
    paths: dict[str, str] = field(default_factory=dict)
    fill_rows: list[dict[str, Any]] = field(default_factory=list)
    _index: dict[str, list[Path]] | None = None

    def _from_git(self, rel: str, sha: str) -> bytes | None:
        git = ["git", "-C", str(self.repo)]
        log = subprocess.run(
            [*git, "log", "--all", "--format=%H", "--", rel], capture_output=True, text=True
        )
        for commit in log.stdout.split():
            blob = subprocess.run([*git, "show", f"{commit}:{rel}"], capture_output=True)
            if blob.returncode == 0 and hashlib.sha256(blob.stdout).hexdigest() == sha:
                return blob.stdout
        return None

    def _from_search(self, name: str, sha: str) -> bytes | None:
        if self._index is None:
            self._index = defaultdict(list)
            for root in self.search:
                for folder, _dirs, files in os.walk(root):
                    for file in files:
                        self._index[file].append(Path(folder) / file)
        for candidate in self._index.get(name, []):
            data = candidate.read_bytes()
            if hashlib.sha256(data).hexdigest() == sha:
                return data
        return None

    def add(self, documents: list[Any]) -> None:
        wanted: dict[str, set[str]] = defaultdict(set)
        artifacts = self.repo / "artifacts"
        for document in documents:
            for row in verified_rows(document):
                where = Path(row["path"])
                if where.is_relative_to(self.repo) and not where.is_relative_to(artifacts):
                    wanted[row["path"]].add(row["sha256"])
        for path, shas in sorted(wanted.items()):
            if len(shas) != 1:
                raise SystemExit(f"profiles pin {path} at {len(shas)} versions; freeze separately")
            sha = next(iter(shas))
            rel = str(Path(path).relative_to(self.repo))
            data = self._from_git(rel, sha) or self._from_search(Path(path).name, sha)
            if data is None:
                raise SystemExit(f"no exact copy of {path} ({sha}) in git or the search folders")
            self._write(rel, data)
            self.rows[(path, sha)] = str(self.tree / rel)
            self.paths[path] = str(self.tree / rel)
        self._fill()

    def _write(self, rel: str, data: bytes) -> None:
        target = self.tree / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            target.chmod(0o644)
        target.write_bytes(data)
        target.chmod(0o444)

    def _fill(self) -> None:
        """Complete each --fill folder from --base, so the tree is a whole package.

        A partial tree would be a namespace portion that an installed regular
        package of the same name shadows. The filled files are pinned too.
        """
        if not self.fill:
            return
        if self.base is None:
            raise SystemExit("--fill needs --base")
        git = ["git", "-C", str(self.repo)]
        listing = subprocess.run(
            [*git, "ls-tree", "-r", "--name-only", self.base, "--", *self.fill],
            capture_output=True,
            text=True,
            check=True,
        )
        restored = {str(Path(p).relative_to(self.tree)) for p in self.paths.values()}
        for rel in listing.stdout.split():
            if rel in restored:
                continue
            blob = subprocess.run([*git, "show", f"{self.base}:{rel}"], capture_output=True)
            if blob.returncode != 0:
                raise SystemExit(f"cannot read {rel} at {self.base}")
            self._write(rel, blob.stdout)
            self.fill_rows.append(pin(self.tree / rel))


class Repinner:
    def __init__(
        self,
        alias: tuple[Path, Path] | None,
        drop: list[Path],
        replaced: dict[str, dict[str, Any]],
        freeze: Freeze | None = None,
        scope: list[Path] | None = None,
    ) -> None:
        self.alias, self.drop, self.replaced = alias, drop, replaced
        self.freeze, self.scope = freeze, scope
        self.changes: list[dict[str, Any]] = []

    def _row(self, row: dict[str, Any]) -> Any:
        path = row["path"]
        if path in self.replaced:
            new = self.replaced[path]
            self.changes.append({"kind": "profile", "from": path, "to": new["path"]})
            return {**row, **new}
        frozen = self.freeze.rows.get((path, row["sha256"])) if self.freeze else None
        if frozen is not None:
            self.changes.append({"kind": "frozen", "from": path, "to": frozen})
            return {**row, "path": frozen}
        source = Path(path)
        if self.scope is not None and not any(source.is_relative_to(p) for p in self.scope):
            return row  # outside --scope: kept exactly as written
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
        if (
            self.freeze is not None
            and isinstance(value, dict)
            and isinstance(value.get("target"), str)
            and value["target"] in self.freeze.paths
            and is_pin(value.get("source"))
        ):
            # An encoder overlay is bound over the frozen copy of its target.
            frozen = self.freeze.paths[value["target"]]
            self.changes.append({"kind": "overlay", "from": value["target"], "to": frozen})
            value = {**value, "target": frozen}
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
    freeze: Freeze | None = None,
    scope: list[Path] | None = None,
    add_pins: list[Path] | None = None,
) -> dict[str, dict[str, Any]]:
    """Write re-pinned copies of the stale profiles; returns {original path: pin of the copy}.

    A profile whose pins all still hold is not copied.
    """
    profiles = [p.resolve(strict=True) for p in profiles]
    names = [p.name for p in profiles]
    if len(set(names)) != len(names):
        raise SystemExit("profiles must have distinct file names")
    documents = {str(p): json.loads(p.read_text()) for p in profiles}
    if freeze is not None:
        freeze.add(list(documents.values()))
    pending = set(documents)
    out_dir.mkdir(parents=True, exist_ok=True)
    replaced: dict[str, dict[str, Any]] = {}
    while pending:
        ready = [p for p in sorted(pending) if not (references(documents[p]) & (pending - {p}))]
        if not ready:
            raise SystemExit(f"profiles reference each other in a cycle: {sorted(pending)}")
        for path in ready:
            original = Path(path)
            work = Repinner(alias, drop, replaced, freeze, scope)
            document = work.rewrite(documents[path])
            if (
                add_pins
                and isinstance(document, dict)
                and document.get("kind") == "vantage_experimental_local_native"
            ):
                have = {row["path"] for row in document["pins"]}
                for extra in add_pins:
                    row = pin(extra)
                    if row["path"] not in have:
                        # The loader requires its own backend source to be pinned.
                        document["pins"].append(row)
                        work.changes.append({"kind": "added", "path": row["path"]})
            pending.discard(path)
            if not work.changes:
                continue  # still valid as it is: keep the original (and its hash)
            if freeze is not None and isinstance(document, dict):
                if document.get("kind") in RESEARCH_KINDS:
                    document["research_root"] = str(freeze.tree)
                # The filled files are checked like every other verified pin.
                if document.get("kind") == "vantage_experimental_local_native":
                    listed: str | None = "pins"
                elif "source_contracts" in document:
                    listed = "source_contracts"
                else:
                    listed = None
                frozen_here = any(c["kind"] == "frozen" for c in work.changes)
                if listed and freeze.fill_rows and frozen_here:
                    document[listed] = [*document[listed], *freeze.fill_rows]
                    work.changes.append({"kind": "filled", "files": len(freeze.fill_rows)})
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
    parser.add_argument("--freeze-repo", type=Path, help="restore this repository's pinned files")
    parser.add_argument("--freeze-tree", type=Path, help="...into this read-only tree")
    parser.add_argument("--search", type=Path, action="append", default=[], help="more sources")
    parser.add_argument("--base", help="commit to complete the --fill folders from")
    parser.add_argument("--fill", action="append", default=[], help="folder to make complete")
    parser.add_argument("--scope", type=Path, action="append", help="only re-pin under these")
    parser.add_argument("--add-pin", type=Path, action="append", default=[], help="pin this too")
    args = parser.parse_args(argv)
    if (args.freeze_repo is None) != (args.freeze_tree is None):
        parser.error("--freeze-repo and --freeze-tree go together")
    freeze = (
        Freeze(
            args.freeze_repo.resolve(),
            args.freeze_tree.resolve(),
            [p.resolve() for p in args.search],
            args.base,
            args.fill,
        )
        if args.freeze_repo
        else None
    )
    if (args.alias_from is None) != (args.alias_to is None):
        parser.error("--alias-from and --alias-to go together")
    alias = (args.alias_from.resolve(), args.alias_to.resolve()) if args.alias_from else None
    result = repin(
        args.profiles,
        args.out_dir.resolve(),
        alias,
        [p.resolve() for p in args.drop],
        dt.date.today().isoformat(),
        freeze,
        [p.resolve() for p in args.scope] if args.scope else None,
        [p.resolve() for p in args.add_pin],
    )
    for original, copy in result.items():
        print(f"{copy['sha256']}  {copy['path']}  (from {original})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
