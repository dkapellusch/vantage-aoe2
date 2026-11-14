"""A whole match's views (``/api/view``) packed for the browser to keep.

A view is the complete state of one keyframe: a few hundred KB of JSON late in a
team game, one a second of game time. Consecutive views are nearly the same
document, so a *chunk* holds the first view of a run in full and each later one
as a structural delta against the one before; chunks are gzip-compressed and
independent, so any moment is rebuilt from one chunk (``timeline-pack.js`` does
that in a worker, without the network).

The delta is generic JSON, not a schema of the view: whatever the view holds
today or gains tomorrow round-trips, and :func:`encode_chunk` checks every delta
by applying it (:func:`apply`) before it is written. A delta is one of

``[0, value]``
    replace with ``value``;
``[1, {key: delta, ...}, [removed keys]]``
    an object: the keys named are patched or (new ones, in this order) appended;
``[2, ops]``
    a list of rows, each a list starting with its unique id. ``ops`` is flat:
    ``0, i, n`` copies ``n`` rows from the old list starting at ``i``;
    ``1, i, [col, value, ...]`` copies old row ``i`` with those columns replaced;
    ``2, i, length, [col, value, ...]`` the same for a row whose length changed;
    ``3, row`` is a new row;
``[3, [index, delta, ...]]``
    a list of the same length, patched by position.

A chunk also carries the forest and terrain snapshots (``/api/trees``,
``/api/terrain``) of its stretch of game time, so a seek needs neither request:
``[time, mode, base64, kinds?]`` rows, ``mode`` 0 for the tile bytes themselves
and 1 for their XOR with the snapshot before (nearly all zero: a few trees fell).
"""

from __future__ import annotations

import base64
import gzip
import json
from collections.abc import Callable, Sequence
from itertools import pairwise
from typing import Any

#: Format version, in the index and in every chunk.
VERSION = 1
#: Views per chunk: the first in full, the rest as deltas. A chunk is what the
#: browser downloads, stores and opens, so it is sized by how long it takes to
#: open: 10 views of a late 4v4 (360 KB of JSON each) open in ~20 ms where 30
#: took ~60 ms and saved only 3 % of the bytes (a full view compresses nearly as
#: well as the delta of a busy second); 30 views of a 1v1 open in ~7 ms and its
#: pack is 30 % smaller than in tens.
CHUNK_VIEWS = (30, 20, 10)


def chunk_views(mean_keyframe_bytes: float) -> int:
    """Views per chunk for a match whose stored (compressed) keyframes average
    this many bytes: fewer the larger its views are."""
    if mean_keyframe_bytes < 20_000:
        return CHUNK_VIEWS[0]
    if mean_keyframe_bytes < 40_000:
        return CHUNK_VIEWS[1]
    return CHUNK_VIEWS[2]


_SAME: Any = object()


def _keyed(rows: list[Any]) -> dict[Any, int] | None:
    """Row index by id for a list of rows with unique scalar ids, else None."""
    index: dict[Any, int] = {}
    for i, r in enumerate(rows):
        if not isinstance(r, list) or not r:
            return None
        k = r[0]
        # bool is an int in Python and 1 == 1.0: keep ids to plain ints and strings.
        if type(k) not in (int, str) or k in index:
            return None
        index[k] = i
    return index


Equal = Callable[[Any, Any], bool]


def _fast_equal(a: Any, b: Any) -> bool:
    """Python's own equality: fast (C), but 1 == 1.0 == True. :func:`encode_chunk`
    checks what it built with it and falls back to :func:`_equal`."""
    return bool(a == b)


def _row_patch(old: list[Any], new: list[Any], eq: Equal) -> list[Any]:
    patch: list[Any] = []
    for c in range(len(new)):
        if c >= len(old) or not eq(old[c], new[c]):
            patch += [c, new[c]]
    return patch


def _equal(a: Any, b: Any) -> bool:
    """Equality as JSON sees it: 1 and 1.0 are the same number, True is not 1."""
    if a is b:
        return True
    ta, tb = type(a), type(b)
    if ta is not tb and (bool in (ta, tb) or not (ta in (int, float) and tb in (int, float))):
        return False
    if ta is list:
        return len(a) == len(b) and all(_equal(x, y) for x, y in zip(a, b, strict=True))
    if ta is dict:
        return len(a) == len(b) and all(
            ka == kb and _equal(va, vb)
            for (ka, va), (kb, vb) in zip(a.items(), b.items(), strict=True)
        )
    return bool(a == b)


def diff(old: Any, new: Any, eq: Equal = _equal) -> Any:
    """The delta that turns ``old`` into ``new``; ``_SAME`` when they are equal."""
    if eq(old, new):
        return _SAME
    if isinstance(old, dict) and isinstance(new, dict):
        # Patching keeps the old key order and appends new keys: only usable when
        # that is the order the new object has.
        kept = [k for k in old if k in new]
        added = [k for k in new if k not in old]
        if list(new) == kept + added:
            patch = {}
            for k, v in new.items():
                d = diff(old[k], v, eq) if k in old else [0, v]
                if d is not _SAME:
                    patch[k] = d
            return [1, patch, [k for k in old if k not in new]]
        return [0, new]
    if isinstance(old, list) and isinstance(new, list):
        if new and old:
            index = _keyed(old)
            if index is not None and _keyed(new) is not None:
                return [2, _rows_delta(old, new, index, eq)]
        if len(old) == len(new) and len(new) > 1:
            patch_list: list[Any] = []
            for i, (a, b) in enumerate(zip(old, new, strict=True)):
                d = diff(a, b, eq)
                if d is not _SAME:
                    patch_list += [i, d]
            if len(patch_list) < len(new):  # fewer than half changed
                return [3, patch_list]
    return [0, new]


def _rows_delta(old: list[Any], new: list[Any], index: dict[Any, int], eq: Equal) -> list[Any]:
    ops: list[Any] = []
    run_start = run_len = 0
    for row in new:
        i = index.get(row[0])
        if i is not None and eq(old[i], row):
            if run_len and i == run_start + run_len:
                run_len += 1
            else:
                if run_len:
                    ops += [0, run_start, run_len]
                run_start, run_len = i, 1
            continue
        if run_len:
            ops += [0, run_start, run_len]
            run_len = 0
        if i is None:
            ops += [3, row]
        elif len(old[i]) == len(row):
            ops += [1, i, _row_patch(old[i], row, eq)]
        else:
            ops += [2, i, len(row), _row_patch(old[i], row, eq)]
    if run_len:
        ops += [0, run_start, run_len]
    return ops


def apply(old: Any, delta: Any) -> Any:
    """``old`` with ``delta`` applied (a new value; ``old`` is not changed)."""
    kind = delta[0]
    if kind == 0:
        return delta[1]
    if kind == 1:
        gone = set(delta[2])
        patch = delta[1]
        out = {}
        for k, v in old.items():
            if k in gone:
                continue
            out[k] = apply(v, patch[k]) if k in patch else v
        for k, d in patch.items():
            if k not in old:
                out[k] = d[1]
        return out
    if kind == 2:
        ops = delta[1]
        rows: list[Any] = []
        p = 0
        while p < len(ops):
            op = ops[p]
            if op == 0:
                rows += old[ops[p + 1] : ops[p + 1] + ops[p + 2]]
                p += 3
            elif op == 3:
                rows.append(ops[p + 1])
                p += 2
            else:
                row = list(old[ops[p + 1]])
                if op == 2:
                    n = ops[p + 2]
                    row = row[:n] + [None] * (n - len(row))
                    p += 1
                patch = ops[p + 2]
                for c in range(0, len(patch), 2):
                    row[patch[c]] = patch[c + 1]
                rows.append(row)
                p += 3
        return rows
    if kind == 3:
        out_list = list(old)
        patch = delta[1]
        for c in range(0, len(patch), 2):
            out_list[patch[c]] = apply(old[patch[c]], patch[c + 1])
        return out_list
    raise ValueError(f"unknown delta kind {kind!r}")


def _dumps(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False)


def _delta(old: dict[str, Any], new: dict[str, Any]) -> Any:
    """A delta from ``old`` to ``new`` that is known to rebuild ``new``."""
    want = _dumps(new)
    # Fast first; its result is exact unless a value changed between 1, 1.0 and
    # True (equal to Python, not always to JSON), which the text comparison shows.
    d = diff(old, new, _fast_equal)
    if d is _SAME:
        d = [1, {}, []]
    if _dumps(apply(old, d)) == want:
        return d
    d = diff(old, new)
    if d is _SAME:
        d = [1, {}, []]
    if _equal(apply(old, d), new):
        return d
    return [0, new]  # never ship a delta that does not rebuild the view


#: A tile snapshot for a chunk: (time, tile bytes, tree kinds or None for terrain).
Tiles = tuple[int, bytes, list[int] | None]


def _tile_rows(snapshots: Sequence[Tiles]) -> list[list[Any]]:
    rows: list[list[Any]] = []
    prev: bytes | None = None
    for t, tiles, kinds in snapshots:
        if prev is not None and len(prev) == len(tiles):
            n = len(tiles)
            x = (int.from_bytes(prev, "little") ^ int.from_bytes(tiles, "little")).to_bytes(
                n, "little"
            )
            row: list[Any] = [t, 1, base64.b64encode(x).decode()]
        else:
            row = [t, 0, base64.b64encode(tiles).decode()]
        if kinds is not None:
            row.append(kinds)
        rows.append(row)
        prev = tiles
    return rows


def _tiles_of(rows: list[list[Any]]) -> list[Tiles]:
    out: list[Tiles] = []
    prev = b""
    for row in rows:
        raw = base64.b64decode(row[2])
        if row[1] == 1:
            raw = (int.from_bytes(prev, "little") ^ int.from_bytes(raw, "little")).to_bytes(
                len(raw), "little"
            )
        out.append((row[0], raw, row[3] if len(row) > 3 else None))
        prev = raw
    return out


def encode_chunk(
    views: list[dict[str, Any]],
    trees: Sequence[Tiles] = (),
    terrain: Sequence[Tiles] = (),
    *,
    level: int = 6,
) -> bytes:
    """One chunk: ``views`` (consecutive keyframes' views) and the tile snapshots of
    their stretch of time, as gzip-compressed JSON ``{"v", "times", "base",
    "deltas", "trees", "terrain"}``. Every delta is verified by applying it."""
    if not views:
        raise ValueError("a chunk needs at least one view")
    doc = {
        "v": VERSION,
        "times": [v["time"] for v in views],
        "base": views[0],
        "deltas": [_delta(old, new) for old, new in pairwise(views)],
        "trees": _tile_rows(trees),
        "terrain": _tile_rows(terrain),
    }
    return gzip.compress(_dumps(doc).encode(), compresslevel=level, mtime=0)


def decode_chunk(blob: bytes) -> tuple[list[dict[str, Any]], list[Tiles], list[Tiles]]:
    """A chunk's views, forest snapshots and terrain snapshots (the reference
    decoder; the browser's is timeline-pack.js)."""
    doc = json.loads(gzip.decompress(blob))
    if doc.get("v") != VERSION:
        raise ValueError(f"unsupported pack version {doc.get('v')!r}")
    views = [doc["base"]]
    for d in doc["deltas"]:
        views.append(apply(views[-1], d))
    return views, _tiles_of(doc.get("trees") or []), _tiles_of(doc.get("terrain") or [])
