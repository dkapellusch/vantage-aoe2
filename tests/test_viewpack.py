"""vantage.viewpack: a match's views as delta-coded chunks, and the timeline's pack."""

from __future__ import annotations

import gzip
import json
import random
from pathlib import Path
from typing import Any

import pytest

from tests.helpers import game_frames
from vantage import viewpack
from vantage.gamedata import GameData
from vantage.timeline import Timeline


def _norm(value: Any) -> Any:
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, list):
        return [_norm(v) for v in value]
    if isinstance(value, dict):
        return {k: _norm(v) for k, v in value.items()}
    return value


def _text(value: Any) -> str:
    """The value as a browser reads it: 1.0 is the number 1, true is not; key
    order and everything else as written."""
    return json.dumps(_norm(value), separators=(",", ":"))


def _check(old: Any, new: Any) -> Any:
    """The delta between two values, having checked both equalities rebuild ``new``."""
    for eq in (viewpack._equal, viewpack._fast_equal):
        d = viewpack.diff(old, new, eq)
        if d is not viewpack._SAME:
            assert viewpack._equal(viewpack.apply(old, d), new)
    d = viewpack._delta({"x": old}, {"x": new})
    assert _text(viewpack.apply({"x": old}, d)) == _text({"x": new})
    return viewpack.diff(old, new)


def test_rows_are_copied_patched_added_and_dropped_by_id() -> None:
    old = [
        [1, 0, 5.0, [[7, 0]]],
        [2, 0, 6.0, [[7, 1]]],
        [3, 1, 1.0, 0],
        [4, 1, 2.0, 0],
        [-9, 1, 0.0, 0],
    ]
    new = [
        [1, 0, 5.0, [[7, 0]]],
        [2, 0, 6.5, [[7, 2]]],
        [4, 1, 2.0, 0, "x"],
        [5, 2, 0.0, 0],
        [-9, 1, 0.0, 0],
    ]
    d = _check(old, new)
    assert d[0] == 2
    # one copy, a patch of two columns, a longer row, a new row, a copy
    assert d[1] == [
        0,
        0,
        1,
        1,
        1,
        [2, 6.5, 3, [[7, 2]]],
        2,
        3,
        5,
        [4, "x"],
        3,
        [5, 2, 0.0, 0],
        0,
        4,
        1,
    ]
    assert _check(new, old)[0] == 2  # and a row that got shorter


def test_objects_keep_their_key_order_or_are_sent_whole() -> None:
    old = {"a": 1, "b": {"x": 1, "y": [1, 2]}, "c": 3}
    assert _check(old, {"a": 1, "b": {"x": 2, "y": [1, 2]}, "d": 4}) == [
        1,
        {"b": [1, {"x": [0, 2]}, []], "d": [0, 4]},
        ["c"],
    ]
    # "c" before "a": patching would keep the old order, so the object goes whole
    assert _check(old, {"c": 3, "a": 1, "b": old["b"]})[0] == 0
    assert viewpack.diff(old, json.loads(_text(old))) is viewpack._SAME


def test_lists_without_ids_are_patched_by_position_or_sent_whole() -> None:
    old = [[1.5, 2.5, "a"], [1.5, 2.5, "b"], [3.0, 1.0, "c"], [4.0, 1.0, "d"]]
    new = [[1.5, 2.5, "a"], [1.5, 2.5, "x"], [3.0, 1.0, "c"], [4.0, 1.0, "d"]]
    assert _check(old, new) == [3, [1, [3, [2, [0, "x"]]]]]
    assert _check(old, new[:3])[0] == 0
    assert _check([], new)[0] == 0 and _check(new, [])[0] == 0


def test_numbers_that_python_calls_equal_are_not_confused() -> None:
    # True == 1 == 1.0 in Python; JSON tells true from 1, and 1 from 1.0 in its text.
    assert not viewpack._equal(True, 1) and viewpack._equal(1, 1.0)
    old = {"rows": [[1, True, 2], [2, 0, 2]], "n": 1}
    new = {"rows": [[1, 1, 2], [2, False, 2]], "n": 1.0}
    d = viewpack._delta(old, new)
    assert _text(viewpack.apply(old, d)) == _text(new)


def test_random_documents_round_trip() -> None:
    rng = random.Random(7)

    def value(depth: int = 0) -> Any:
        r = rng.random()
        if depth > 3 or r < 0.35:
            return rng.choice([0, 1, 2.5, -3, "a", "b", None, True, False, 1.0])
        if r < 0.6:
            return {rng.choice("abcdefg"): value(depth + 1) for _ in range(rng.randrange(4))}
        if r < 0.8:
            ids = rng.sample(range(-5, 12), rng.randrange(8))
            return [[i, value(depth + 1), rng.randrange(3)] for i in ids]
        return [value(depth + 1) for _ in range(rng.randrange(5))]

    for _ in range(400):
        old, new = {"v": value()}, {"v": value()}
        assert _text(viewpack.apply(old, viewpack._delta(old, new))) == _text(new)
        if rng.random() < 0.5:  # a small change to the same document
            new = json.loads(_text(old))
            new["w"] = value()
            assert _text(viewpack.apply(old, viewpack._delta(old, new))) == _text(new)


def test_a_chunk_holds_views_and_tile_snapshots() -> None:
    views = [{"time": t, "entities": [[1, t / 4], [2, 5]], "fog": "x" * t} for t in range(0, 5)]
    trees = [(0, bytes(8), [3]), (3, bytes([0, 1, 0, 0, 0, 0, 2, 0]), [3, 4]), (4, b"abc", [5])]
    terrain = [(2, bytes(range(6)), None)]
    blob = viewpack.encode_chunk(views, trees, terrain)
    assert viewpack.decode_chunk(blob) == (views, trees, terrain)
    doc = json.loads(gzip.decompress(blob))
    assert doc["times"] == [0, 1, 2, 3, 4] and len(doc["deltas"]) == 4
    # the second forest is stored as its difference, the third (another size) whole
    assert [row[1] for row in doc["trees"]] == [0, 1, 0]
    assert viewpack.encode_chunk(views, trees, terrain) == blob  # the same bytes every time
    with pytest.raises(ValueError):
        viewpack.encode_chunk([])
    with pytest.raises(ValueError):
        viewpack.decode_chunk(gzip.compress(b'{"v":99}'))


def _timeline(seconds: int = 25, complete: bool = True) -> Timeline:
    tl = Timeline(GameData(None))
    tl.pack_dir = None
    tl.pack_chunk_views = 10
    if complete:
        tl.feed_all(game_frames(seconds))
    else:
        for f in game_frames(seconds):
            tl.feed(f)
    return tl


def test_the_timelines_pack_rebuilds_every_view_and_tile_request() -> None:
    tl = _timeline()
    index = tl.pack_index()
    assert index is not None and index["v"] == viewpack.VERSION
    times = index["times"]
    assert times == [k.time for k in tl.keyframes] and len(times) == 26
    n = index["chunk_views"]
    chunks = [tl.pack_chunk(i) for i in range(3)]
    assert all(chunks) and tl.pack_chunk(3) is None and tl.pack_chunk(-1) is None
    assert tl.pack_chunk(1) is chunks[1]  # kept
    decoded = [viewpack.decode_chunk(c) for c in chunks if c]
    views = [v for d in decoded for v in d[0]]
    assert len(views) == len(times)
    for k, t in enumerate(times):
        assert _text(views[k]) == _text(json.loads(tl.view_json(t) or b"{}"))
    # Any time asked for: the tiles in force then are in the chunk of that time.
    for t in [-5, 0, 1, 2999, 3000, 3001, 9999, 10000, 12345, 20000, 24999, 25000, 99999]:
        k = max(0, sum(1 for x in times if x <= t) - 1)
        _, trees, terrain = decoded[k // n]
        for got, want in ((trees, tl.trees_at(t)), (terrain, tl.terrain_at(t))):
            mine = [s for s in got if s[0] <= t]
            if want is None:
                assert not mine
            else:
                assert mine[-1][0] == want[0] and mine[-1][1] == want[1]
                if len(want) > 2:
                    assert mine[-1][2] == want[2]


def test_chunks_hold_fewer_views_the_larger_the_views_are() -> None:
    assert [viewpack.chunk_views(n) for n in (0, 12_000, 25_000, 60_000)] == [30, 30, 20, 10]
    tl = _timeline()
    tl.pack_chunk_views = None
    index = tl.pack_index()
    assert index is not None and index["chunk_views"] == 30  # small views
    assert tl.pack_chunk(0) and tl.pack_chunk(1) is None  # 26 views: one chunk
    other = _timeline().pack_index()
    assert other is not None and other["key"] != index["key"]  # cut differently


def test_a_growing_timeline_has_no_pack_and_another_match_another_key() -> None:
    growing = _timeline(complete=False)
    assert growing.pack_index() is None and growing.pack_chunk(0) is None
    a, b, c = _timeline(), _timeline(), _timeline(24)
    ka, kb, kc = (t.pack_index()["key"] for t in (a, b, c))  # type: ignore[index]
    assert ka == kb != kc


def test_chunks_are_kept_on_disk_and_old_packs_removed(tmp_path: Path, monkeypatch: Any) -> None:
    import vantage.timeline as T

    tl = _timeline()
    tl.pack_dir = tmp_path
    key = tl.pack_index()["key"]  # type: ignore[index]
    blob = tl.pack_chunk(1)
    assert (tmp_path / key / "1.gz").read_bytes() == blob
    # Another process reading the same recording takes the stored chunk.
    again = _timeline()
    again.pack_dir = tmp_path
    (tmp_path / key / "2.gz").write_bytes(b"stored")
    assert again.pack_chunk(2) == b"stored" and again.pack_chunk(1) == blob
    monkeypatch.setattr(T, "PACKS_KEPT", 2)
    for name in ("old1", "old2", "old3"):
        (tmp_path / name).mkdir()
        (tmp_path / name / "0.gz").write_bytes(b"x")
    assert again.pack_chunk(0)  # writing chunk 0 prunes
    left = sorted(p.name for p in tmp_path.iterdir())
    assert key in left and len(left) == 2


FIXTURE = Path(__file__).parent / "fixtures" / "viewpack-chunk.json"


def test_the_browser_decoders_fixture_is_what_the_encoder_writes() -> None:
    """tests/timeline_pack.test.mjs rebuilds this chunk with timeline-pack.js: the
    two decoders are held to the same bytes. Regenerate with VIEWPACK_FIXTURE=1."""
    import base64
    import os

    tl = _timeline()
    blob = tl.pack_chunk(1)
    assert blob is not None
    views, trees, terrain = viewpack.decode_chunk(blob)
    doc = {
        "index": tl.pack_index(),
        "chunk": 1,
        "gzip": base64.b64encode(blob).decode(),
        "views": views,
        "trees": [[t, base64.b64encode(b).decode(), kinds] for t, b, kinds in trees],
        "terrain": [[t, base64.b64encode(b).decode()] for t, b, _ in terrain],
    }
    text = json.dumps(doc, separators=(",", ":"))
    if os.environ.get("VIEWPACK_FIXTURE"):
        FIXTURE.write_text(text)
    assert FIXTURE.read_text() == text
