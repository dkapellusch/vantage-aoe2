"""vantage.patch: the full Frame.patch decoder."""

from __future__ import annotations

import base64
import json
import lzma
from pathlib import Path

import pytest

from tests.helpers import PatchBuilder, fid, snapshot_builder, snapshot_frame
from vantage.patch import Node, Patcher, PatchError
from vantage.schema import SCHEMA

FIXTURES = Path(__file__).parent / "fixtures"
M = SCHEMA.model_id


def _world_builder() -> PatchBuilder:
    return PatchBuilder().create(fid("Root", "world"), M("World"))


def _apply(b: PatchBuilder, backward: bool = False, p: Patcher | None = None) -> Patcher:
    p = p or Patcher()
    p.apply(b.backward() if backward else b.forward())
    return p


def _world(p: Patcher) -> Node:
    w = p.root.fields[fid("Root", "world")]
    assert isinstance(w, Node)
    return w


@pytest.mark.parametrize("backward", [False, True])
def test_scalars_objects_and_maps(backward: bool) -> None:
    b = _world_builder()
    b.assign(fid("World", "time"), "UInt32", 1234)
    b.assign(fid("World", "woodPrice"), "Float", 1.5)
    b.assign(fid("World", "gameEnded"), "Boolean", True)
    b.create_key(fid("World", "players"), M("Player"), 1)
    b.assign(fid("Player", "name"), "String", "Ünïcode")
    b.create(fid("Player", "attributes"), M("PlayerAttributes"))
    b.assign(fid("PlayerAttributes", "food"), "Float", 200.0)
    b.pop().pop().pop()
    w = _world(_apply(b, backward))
    assert w.fields[fid("World", "time")] == 1234
    assert w.fields[fid("World", "woodPrice")] == pytest.approx(1.5)
    assert w.fields[fid("World", "gameEnded")] is True
    pl = w.fields[fid("World", "players")][1]
    assert pl.model == M("Player")
    assert pl.fields[fid("Player", "name")] == "Ünïcode"
    attrs = pl.fields[fid("Player", "attributes")]
    assert attrs.fields[fid("PlayerAttributes", "food")] == 200.0


@pytest.mark.parametrize("backward", [False, True])
def test_array_operations(backward: bool) -> None:
    tt = fid("World", "terrainTypes")
    vm = fid("World", "unifiedVisibleMap")
    tiles = fid("World", "mapTiles")
    b = _world_builder()
    b.resize(tiles, 3)  # contiguous: filled with MapTile objects
    b.push_key(tiles, 2).assign(fid("MapTile", "terrainType"), "UInt8", 9).pop()
    b.resize(vm, 2)  # constant: filled with zeros
    b.assign_key(vm, 1, "UInt32", 77)
    b.insert(vm, 0, "UInt32", 5)
    b.swap(vm, 0, 2)
    b.remove(vm, 1)
    b.create_insert(tt, M("TerrainType"), 0).assign(fid("TerrainType", "name"), "String", "a").pop()
    b.create_insert(tt, M("TerrainType"), 0).assign(fid("TerrainType", "name"), "String", "b").pop()
    b.resize(tt, 3)  # plain: filled with null
    b.pop()
    w = _world(_apply(b, backward))
    assert [t.model for t in w.fields[tiles]] == [M("MapTile")] * 3
    assert w.fields[tiles][2].fields[fid("MapTile", "terrainType")] == 9
    assert w.fields[vm] == [77, 5]
    names = [t.fields[fid("TerrainType", "name")] if t else None for t in w.fields[tt]]
    assert names == ["b", "a", None]


def test_reset_key_and_field() -> None:
    p = Patcher()
    b = _world_builder()
    b.create_key(fid("World", "players"), M("Player"), 3)
    b.create(fid("Player", "attributes"), M("PlayerAttributes")).pop().pop().pop()
    _apply(b, p=p)
    b2 = PatchBuilder().push(fid("Root", "world")).push_key(fid("World", "players"), 3)
    b2.reset(fid("Player", "attributes")).pop().reset_key(fid("World", "players"), 3).pop()
    _apply(b2, p=p)
    assert 3 not in _world(p).fields[fid("World", "players")]


def _tree(n: object) -> object:
    if isinstance(n, Node):
        return (n.model, {k: _tree(v) for k, v in sorted(n.fields.items())})
    if isinstance(n, dict):
        return {k: _tree(v) for k, v in sorted(n.items())}
    if isinstance(n, list):
        return [_tree(v) for v in n]
    return n


def test_snapshot_identical_forward_and_backward() -> None:
    b = snapshot_builder(0)
    fwd, bwd = Patcher(), Patcher()
    fwd.apply(b.forward())
    bwd.apply(b.backward())
    assert fwd.ops > 100
    assert len(_world(fwd).fields[fid("World", "entities")]) == 9
    assert _tree(fwd.root) == _tree(bwd.root)
    assert snapshot_frame(0).is_snapshot


@pytest.mark.parametrize(
    "blob, message",
    [
        (bytes([99]), "unknown opcode"),
        (bytes([1]), "POP at root"),
        (bytes([3, 0]), "missing object"),
        (bytes([4, 0, 1]), "without closing"),
        (bytes([4, 0, 1, 1, 1]), "POP at root"),
        (bytes([4, 0, 1, 2, 0, 1]), "ends inside"),
    ],
)
def test_malformed_patches_raise(blob: bytes, message: str) -> None:
    with pytest.raises(PatchError, match=message):
        Patcher().apply(blob)


def test_out_of_range_index_is_strict_but_lenient_extends() -> None:
    b = _world_builder().assign_key(fid("World", "unifiedVisibleMap"), 4, "UInt32", 1).pop()
    with pytest.raises(PatchError, match="out of range"):
        _apply(b)
    w = _world(_apply(b, p=Patcher(lenient=True)))
    assert w.fields[fid("World", "unifiedVisibleMap")] == [0, 0, 0, 0, 1]


def test_unknown_field_raises() -> None:
    b = _world_builder().assign(250, "UInt8", 1).pop()
    with pytest.raises(PatchError, match="has no field 250"):
        _apply(b)


def _fixture(name: str) -> list[dict[str, object]]:
    """Recorded ``Frame`` patches: one JSON object per line, the patch in base64."""
    with lzma.open(FIXTURES / f"{name}.jsonl.xz", "rt") as fh:
        return [
            {"time": int(fr["time"]), "patch": base64.b64decode(fr["patch"])}
            for fr in map(json.loads, fh)
        ]


@pytest.mark.parametrize("name", ["cade_frames_37min", "cade_frames_dense", "cade_frames_players"])
def test_real_delta_frames_decode_completely(name: str) -> None:
    """Every captured delta decodes to its last byte with balanced pushes, and
    the world clock it writes equals the proto's Frame.time."""
    p = Patcher(lenient=True)
    for fr in _fixture(name):
        p.apply(fr["patch"])
        assert _world(p).fields[fid("World", "time")] == fr["time"]


def test_real_frames_reproduce_verified_player_resources() -> None:
    """Resource curves from an earlier decoder, checked against build/research
    ground truth (``cade_frames_players.resources.json``); the full decoder must
    agree with every sample."""
    frames = _fixture("cade_frames_players")
    pairs = [(int(fr["time"]), bytes(fr["patch"])) for fr in frames]  # type: ignore[call-overload]
    p = Patcher(lenient=True)
    mine: dict[tuple[int, int, int], float] = {}
    attrs = fid("Player", "attributes")
    for t, blob in pairs:
        p.apply(blob)
        for pid, pl in _world(p).fields[fid("World", "players")].items():
            a = pl.fields.get(attrs)
            if isinstance(a, Node):
                for rid in range(4):
                    if rid in a.fields:
                        mine[(pid, rid, t)] = a.fields[rid]
    checked = 0
    expected = json.loads((FIXTURES / "cade_frames_players.resources.json").read_text())
    for pid, by_resource in expected.items():
        for rid, series in by_resource.items():
            for t, v in series:
                assert mine[(int(pid), int(rid), t)] == pytest.approx(v)
                checked += 1
    assert checked > 40


def test_fast_forward_path_matches_the_reference_interpreter() -> None:
    from tests.helpers import game_frames
    from vantage.patch import _Reader

    def tree(n: object) -> object:
        if isinstance(n, Node):
            return (n.model, {k: tree(v) for k, v in n.fields.items()})
        if isinstance(n, list):
            return [tree(x) for x in n]
        if isinstance(n, dict):
            return {k: tree(v) for k, v in n.items()}
        return n

    fast, slow = Patcher(), Patcher()
    for f in game_frames(12):
        fast.apply(f.patch)
        slow._run(_Reader(f.patch, False), slow.root, 0)
    assert tree(fast.root) == tree(slow.root) and fast.ops == slow.ops
    with pytest.raises(PatchError):
        Patcher().apply(game_frames(1)[0].patch[:-3])  # truncated mid-instruction
