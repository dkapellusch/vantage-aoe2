"""What a recording holds, for the recordings list: who played, and on what map.

A ``.vrec`` header says where a recording came from, not what is in it, so the
list could only show file names. The match itself is in the recording's first
snapshot. Reading that takes about two seconds for a team game, so:

* the answer is cached per file (keyed by path, checked against size and
  modification time), and
* files without one are read by a separate, low-priority process, a few at a
  time, so the list is served at once and playback is never held up. The list
  fills in as that process works through them.

A recording opened in Vantage is summarised for free from its loaded timeline,
which also knows how long the game is.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

VERSION = 1
#: Frames read before giving up on finding the match (the first is the snapshot).
_MAX_FRAMES = 20
#: Recordings one helper process reads before it exits (the next listing starts another).
BATCH = 12


def from_match(match: dict[str, Any], map_name: str = "") -> dict[str, Any]:
    """The list's view of ``Timeline.match``: players in slot order, and the map."""
    players = []
    for pid, p in sorted((match.get("players") or {}).items(), key=lambda kv: int(kv[0])):
        if int(pid) <= 0:
            continue  # Gaia
        players.append(
            {
                "id": int(pid),
                "name": str(p.get("name") or f"Player {pid}"),
                "civ": str(p.get("civ_name") or ""),
                "color": str(p.get("color") or ""),
                "team": int(p.get("team_key") or 0),
                "ai": bool(p.get("ai")),
            }
        )
    map_file = str(match.get("map_file") or "")
    stem = map_file.rsplit(".", 1)[0] if map_file.lower().endswith((".rms", ".rms2")) else map_file
    return {
        "players": players,
        "map": map_name or stem.replace("_", " "),
        "map_size": list(match.get("map_size") or []),
        "mode": str(match.get("game_mode") or ""),
    }


def describe(match: dict[str, Any], data: Any) -> dict[str, Any]:
    """``from_match`` with the map's own name from the install, when there is one."""
    from vantage.replay import load_map_names

    name = ""
    if match.get("map_type") is not None:
        try:
            name = load_map_names(data).get(int(match["map_type"]), "")
        except (OSError, ValueError, TypeError):
            name = ""
    return from_match(match, name)


def summarize(path: str | Path, data: Any) -> dict[str, Any] | None:
    """Read a recording's match from its first snapshot (None when it has none)."""
    from vantage import world as W
    from vantage.frames import read_frames
    from vantage.patch import Patcher

    patcher = Patcher()
    for i, frame in enumerate(read_frames(path)):
        patcher.apply(frame.patch)
        if W.world_of(patcher.root) is not None:
            return describe(W.match_info(patcher.root, data), data)
        if i >= _MAX_FRAMES:
            break
    return None


# -- the cache -----------------------------------------------------------------------


def cache_file(cache_dir: Path, path: str | Path) -> Path:
    key = hashlib.sha1(str(Path(path).resolve()).encode()).hexdigest()
    return cache_dir / "recording-summaries" / f"{key}.json"


def _stamp(path: str | Path) -> dict[str, int]:
    st = os.stat(path)
    return {"size": st.st_size, "mtime_ns": st.st_mtime_ns}


def load(cache_dir: Path, path: str | Path) -> dict[str, Any] | None:
    """The cached summary of ``path`` as it is now on disk, else None."""
    try:
        entry = json.loads(cache_file(cache_dir, path).read_text("utf-8"))
        stamp = _stamp(path)
    except (OSError, ValueError):
        return None
    if not isinstance(entry, dict) or entry.get("v") != VERSION:
        return None
    if entry.get("size") != stamp["size"] or entry.get("mtime_ns") != stamp["mtime_ns"]:
        return None  # the file changed (a live recording still being written)
    summary = entry.get("summary")
    return summary if isinstance(summary, dict) else None


def store(cache_dir: Path, path: str | Path, summary: dict[str, Any]) -> None:
    """Cache ``summary`` for ``path`` as it is now on disk. Failures are ignored:
    the cache only saves work."""
    target = cache_file(cache_dir, path)
    try:
        entry = {"v": VERSION, **_stamp(path), "summary": summary}
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(f".{os.getpid()}.tmp")
        tmp.write_text(json.dumps(entry, separators=(",", ":")), "utf-8")
        os.replace(tmp, target)
    except OSError:
        return


# -- filling the cache in the background ---------------------------------------------


class Summarizer:
    """Starts the helper process for recordings that have no cached summary.

    Off until ``enabled`` is set (``vantage serve`` does): a ``Session`` built
    elsewhere, as the tests build theirs, neither starts processes nor writes
    to the user's cache.
    """

    def __init__(self, enabled: bool = False) -> None:
        self.enabled = enabled
        self._lock = threading.Lock()
        self._child: subprocess.Popen[bytes] | None = None

    def busy(self) -> bool:
        with self._lock:
            return self._child is not None and self._child.poll() is None

    def request(self, cache_dir: Path, game_dir: Path | None, paths: list[Path]) -> bool:
        """Summarise ``paths`` (the first ``BATCH``) unless a helper is already
        running. Returns whether one is running afterwards."""
        with self._lock:
            if self._child is not None and self._child.poll() is None:
                return True
            if not paths or not self.enabled:
                return False
            cmd = [sys.executable, "-m", "vantage.recording_summary", "--cache-dir", str(cache_dir)]
            if game_dir is not None:
                cmd += ["--game-dir", str(game_dir)]
            cmd += [str(p) for p in paths[:BATCH]]
            try:
                self._child = subprocess.Popen(  # our own interpreter and module
                    cmd,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except OSError:
                self._child = None
                return False
            return True

    def stop(self) -> None:
        with self._lock:
            child, self._child = self._child, None
        if child is not None and child.poll() is None:
            child.terminate()


def main(argv: list[str] | None = None) -> int:
    """``python -m vantage.recording_summary``: summarise recordings into the cache."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-dir", type=Path, required=True)
    parser.add_argument("--game-dir", type=Path, default=None)
    parser.add_argument("paths", nargs="*", type=Path)
    args = parser.parse_args(argv)
    # Background work: yield the processor to playback.
    with contextlib.suppress(AttributeError, OSError):
        os.nice(10)

    from vantage.frames import read_header
    from vantage.gamedata import GameData

    base = GameData(args.game_dir, args.cache_dir)
    for path in args.paths:
        if load(args.cache_dir, path) is not None:
            continue
        try:
            data = base.with_mode(read_header(path).get("game_mode"))
            summary = summarize(path, data)
        except Exception:  # a damaged recording must not stop the others
            summary = None
        # An unreadable recording is remembered too, so it is not read again
        # on every listing.
        store(args.cache_dir, path, summary or {"players": [], "map": "", "unreadable": True})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
