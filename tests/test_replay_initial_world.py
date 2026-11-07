"""Native world/map/player boundaries composed from portable paired fixtures."""

from __future__ import annotations

import gzip
import json
import struct
from functools import lru_cache
from itertools import pairwise
from pathlib import Path

import pytest

from vantage.replay_binary import SaveDecodeError, SaveReader
from vantage.replay_initial_world import read_initial_world


@lru_cache(maxsize=2)
def _case(sample: str):
    root = Path(__file__).parent / "fixtures"
    prefixes = json.loads((root / "native_saved_world_prefix_54800.json").read_text())["cases"]
    maps = json.loads(gzip.decompress((root / "native_saved_maps_54800.json.gz").read_bytes()))[
        "cases"
    ]
    players = json.loads(
        gzip.decompress((root / "native_saved_initial_players_54800.json.gz").read_bytes())
    )["cases"]
    prefix = next(c for c in prefixes if c["sample"] == sample)
    saved_map = next(c for c in maps if c["sample"] == sample)
    owners = [c for c in players if c["sample"] == sample]
    assert prefix["end_offset"] == saved_map["offset"]
    assert saved_map["post_map"]["end_offset"] == owners[0]["start"]
    for first, second in pairwise(owners):
        assert first["end"] == second["start"]
    raw = b"".join(
        bytes.fromhex(c["raw_hex"]) for c in (prefix, saved_map, saved_map["post_map"], *owners)
    )
    following = bytes.fromhex(owners[-1]["next_prefix_hex"])
    assert following[:4] == bytes.fromhex("66660640")
    assert len(raw) == owners[-1]["end"] - prefix["offset"]
    return raw, following, prefix, saved_map, owners


@pytest.mark.parametrize("sample,objects", [("3p", 6993), ("6p", 12264)])
def test_native_first_pass_uses_its_own_count_and_stops_before_second_pass(
    sample: str, objects: int
) -> None:
    raw, following, prefix, saved_map, owners = _case(sample)
    reader = SaveReader(b"prefix" + raw + following, 6)
    world = read_initial_world(reader)
    assert world.offset == 6 and world.end_offset == reader.pos == 6 + len(raw)
    assert world.raw == raw and reader.data[reader.pos :] == following
    assert world.prefix.raw == bytes.fromhex(prefix["raw_hex"])
    assert world.map.raw == bytes.fromhex(saved_map["raw_hex"])
    assert world.post_map.raw == bytes.fromhex(saved_map["post_map"]["raw_hex"])
    assert len(world.players) == world.prefix.num_players == len(owners)
    assert [p.header.player_id for p in world.players] == list(range(len(owners)))
    assert [p.raw for p in world.players] == [bytes.fromhex(c["raw_hex"]) for c in owners]
    assert (
        world.prefix.raw
        + world.map.raw
        + world.post_map.raw
        + b"".join(p.raw for p in world.players)
        == raw
    )
    assert (
        sum(
            len(getattr(p.object_lists, name).objects)
            for p in world.players
            for name in ("ordinary", "sleeping", "dopple")
        )
        == objects
    )
    assert all(p.player_ai is not None for p in world.players[2:])


@pytest.mark.parametrize("section", ["prefix", "map", "post_map", "last_player"])
def test_failure_in_any_first_pass_section_restores_world_cursor(section: str) -> None:
    raw, _, prefix, saved_map, _ = _case("3p")
    cuts = {
        "prefix": len(bytes.fromhex(prefix["raw_hex"])) - 1,
        "map": saved_map["end_offset"] - prefix["offset"] - 1,
        "post_map": saved_map["post_map"]["end_offset"] - prefix["offset"] - 1,
        "last_player": len(raw) - 1,
    }
    reader = SaveReader(b"prefix" + raw[: cuts[section]], 6)
    with pytest.raises(SaveDecodeError):
        read_initial_world(reader)
    assert reader.pos == 6


def test_empty_world_is_rejected_before_reading_a_map() -> None:
    raw = bytearray.fromhex(_case("3p")[2]["raw_hex"])
    struct.pack_into("<H", raw, 47, 0)
    reader = SaveReader(bytes(raw[:74]))
    with pytest.raises(SaveDecodeError, match="no players"):
        read_initial_world(reader)
    assert reader.pos == 0
