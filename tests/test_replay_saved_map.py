"""Full native map fixtures, independent capture hashes, and malformed streams."""

from __future__ import annotations

import gzip
import hashlib
import json
import struct
from functools import lru_cache
from pathlib import Path
from typing import Any

import pytest

from vantage.replay_binary import SaveDecodeError, SaveReader
from vantage.replay_saved_map import read_post_map_world, read_saved_map


@lru_cache(maxsize=1)
def _cases() -> list[dict[str, Any]]:
    path = Path(__file__).parent / "fixtures/native_saved_maps_54800.json.gz"
    return list(json.loads(gzip.decompress(path.read_bytes()))["cases"])


@pytest.mark.parametrize("index", (0, 1))
def test_full_native_maps_reach_exact_first_player_and_match_captured_tiles(index: int) -> None:
    case = _cases()[index]
    raw = bytes.fromhex(case["raw_hex"])
    assert hashlib.sha256(raw).hexdigest() == case["raw_sha256"]
    tail = bytes.fromhex(case["post_map"]["raw_hex"])
    following = bytes.fromhex(case["post_map"]["first_player_bytes"])
    reader = SaveReader(b"prefix" + raw + tail + following, 6)
    saved = read_saved_map(reader)
    assert saved.raw == raw and saved.offset == 6 and saved.end_offset == 6 + len(raw)
    assert len(raw) == case["raw_size"] == case["end_offset"] - case["offset"]
    assert (saved.width, saved.height, saved.format_version) == (case["width"], case["height"], 3)
    assert saved.tile_offset == 6 + case["tile_offset"] - case["offset"]
    assert len(saved.tiles) == case["independent_captured_tile_count"]
    assert hashlib.sha256(saved.tile_bytes).hexdigest() == case["tile_bytes_sha256"]
    for label, actual in (
        ("terrain", bytes(t.terrain_type for t in saved.tiles)),
        ("elevations", bytes(t.elevation for t in saved.tiles)),
        ("slopes", bytes(saved.slopes)),
    ):
        assert hashlib.sha256(actual).hexdigest() == case["independent_captured_sha256"][label]
    assert len(saved.zones) == case["zone_count"] == 8
    assert [len(z.values) for z in saved.zones] == case["zone_value_counts"]
    assert [hashlib.sha256(z.raw).hexdigest() for z in saved.zones] == case["zone_raw_sha256"]
    assert all(len(z.counters) == 512 for z in saved.zones)
    assert all(len(z.grid_u16) == saved.width * saved.height * 2 for z in saved.zones)
    assert saved.additional.count == case["additional"]["count"]
    assert saved.additional.capacity == case["additional"]["capacity"]
    assert saved.additional.ids == tuple(case["additional"]["ids"])
    assert saved.additional.vectors == tuple(
        tuple(tuple(pair) for pair in vector) for vector in case["additional"]["vectors"]
    )
    assert (saved.visibility.width, saved.visibility.height) == (saved.width, saved.height)
    assert (
        hashlib.sha256(saved.visibility.cells_u64).hexdigest() == case["visibility"]["cells_sha256"]
    )
    assert (saved.visible_flag, saved.fog_flag) == (0, 1)
    post = read_post_map_world(reader)
    assert post.raw == tail and post.conditional_word is None
    assert post.research_word == post.research_count == 0 and post.research_records_27 == ()
    assert post.global_word == 40600
    assert case["offset"] + reader.pos - 6 == case["post_map"]["end_offset"]
    assert reader.take(len(following)) == following  # First player is untouched.


def _synthetic_map() -> tuple[bytes, dict[str, int]]:
    """Original format3 fixture with nonempty variable blocks and signed fields."""
    out = bytearray(struct.pack("<Iiii", 0xDEADDEAD, 3, 2, 1))
    marks = {"zone_count": len(out)}
    out.extend(struct.pack("<i512I2H", 1, *range(512), 3, 65535))
    marks["zone_values"] = len(out)
    out.extend(struct.pack("<i3I", 2, 0xFFFFFFFF, 0x7FC01234, 7))
    out.extend(b"\xfe\x80")  # Preserve flag bytes rather than normalizing bools.
    marks["tiles"] = len(out)
    out.extend(struct.pack("<BBBBhhh", 4, 5, 255, 2, -1, 32767, -32768))
    out.extend(struct.pack("<BBBBhhh", 3, 4, 2, 2, -7, -2, 1234))
    marks["additional"] = len(out)
    out.extend(struct.pack("<ii2I", 2, 4, 17, 18))
    marks["additional_values"] = len(out)
    out.extend(struct.pack("<i4Ii", 2, 0x80000000, 1, 2, 0xFFFFFFFF, 0))
    marks["visibility"] = len(out)
    out.extend(struct.pack("<ii2Q", 2, 1, 0xFFFFFFFFFFFFFFFF, 0x123456789ABCDEF0))
    return bytes(out), marks


def test_all_saved_map_fields_keep_widths_order_and_original_bits() -> None:
    raw, marks = _synthetic_map()
    saved = read_saved_map(SaveReader(raw + b"trailer"))
    assert saved.raw == raw and saved.end_offset == len(raw)
    assert saved.tile_offset == marks["tiles"]
    assert (saved.visible_flag, saved.fog_flag) == (254, 128)
    zone = saved.zones[0]
    assert zone.counters == tuple(range(512))
    assert zone.grid_u16 == struct.pack("<2H", 3, 65535)
    assert zone.values == (0xFFFFFFFF, 0x7FC01234) and zone.zone_count_word == 7
    first, second = saved.tiles
    assert (first.terrain_type, first.restore_terrain_type, first.previous_terrain_type) == (
        4,
        5,
        255,
    )
    assert first.elevation == 2
    assert (first.mask_type, first.layer, first.previous_layer) == (-1, 32767, -32768)
    assert (second.mask_type, second.layer, second.previous_layer) == (-7, -2, 1234)
    assert saved.slopes == (0, 0)
    assert saved.additional.ids == (17, 18)
    assert saved.additional.vectors == (((0x80000000, 1), (2, 0xFFFFFFFF)), ())
    assert saved.visibility.cells_u64 == struct.pack("<2Q", 0xFFFFFFFFFFFFFFFF, 0x123456789ABCDEF0)


@pytest.mark.parametrize(
    "where,value",
    (
        ("zone_count", -1),
        ("zone_count", 0x7FFFFFFF),
        ("zone_values", -1),
        ("zone_values", 0x7FFFFFFF),
        ("additional", -1),
        ("additional", 0x7FFFFFFF),
        ("additional_values", -1),
        ("additional_values", 0x7FFFFFFF),
        ("visibility", -1),
        ("visibility", 0x7FFFFFFF),
    ),
)
def test_invalid_map_counts_and_visibility_dimensions_roll_back(where: str, value: int) -> None:
    raw, marks = _synthetic_map()
    corrupt = bytearray(raw)
    struct.pack_into("<i", corrupt, marks[where], value)
    reader = SaveReader(b"prefix" + corrupt, 6)
    with pytest.raises(SaveDecodeError):
        read_saved_map(reader)
    assert reader.pos == 6


def test_additional_capacity_cannot_be_smaller_than_saved_count() -> None:
    raw, marks = _synthetic_map()
    corrupt = bytearray(raw)
    struct.pack_into("<i", corrupt, marks["additional"] + 4, 1)
    reader = SaveReader(corrupt)
    with pytest.raises(SaveDecodeError, match="capacity"):
        read_saved_map(reader)
    assert reader.pos == 0


@pytest.mark.parametrize(
    "at,value",
    (
        (0, 0),
        (4, 2),
        (4, 4),
        (8, 0),
        (8, -1),
        (12, 0),
        (12, 0x7FFFFFFF),
    ),
)
def test_unsupported_map_header_and_dimensions_roll_back(at: int, value: int) -> None:
    raw, _ = _synthetic_map()
    corrupt = bytearray(raw)
    struct.pack_into("<i", corrupt, at, value)
    reader = SaveReader(corrupt)
    with pytest.raises(SaveDecodeError):
        read_saved_map(reader)
    assert reader.pos == 0


def test_every_synthetic_map_truncation_rolls_back() -> None:
    raw, _ = _synthetic_map()
    for cut in range(len(raw)):
        reader = SaveReader(b"prefix" + raw[:cut], 6)
        with pytest.raises(SaveDecodeError):
            read_saved_map(reader)
        assert reader.pos == 6, cut


@pytest.mark.parametrize("flag", (0, 1, -1))
def test_post_map_world_keeps_nonempty_research_and_conditional_word(flag: int) -> None:
    records = (bytes(range(27)), struct.pack("<IIIhIIIB", 1, 2, 3, -1, 4, 5, 6, 0x20))
    conditional = struct.pack("<I", 0x7FC01234) if flag else b""
    raw = conditional + struct.pack("<Ii", 99, 2) + b"".join(records) + struct.pack("<I", 40600)
    reader = SaveReader(raw + b"\x02\x0b")
    saved = read_post_map_world(reader, load_flag=flag)
    assert saved.raw == raw and saved.end_offset == len(raw)
    assert saved.conditional_word == (0x7FC01234 if flag else None)
    assert saved.research_word == 99 and saved.research_count == 2
    assert saved.research_records_27 == records and saved.global_word == 40600
    assert reader.take(2) == b"\x02\x0b"


def test_nonpositive_world_research_count_skips_native_loop() -> None:
    raw = struct.pack("<IiI", 0, -1, 40600)
    saved = read_post_map_world(SaveReader(raw))
    assert saved.research_count == -1 and saved.research_records_27 == ()
    assert saved.global_word == 40600


def test_post_map_world_impossible_count_and_every_truncation_roll_back() -> None:
    raw = struct.pack("<Ii", 0, 1) + bytes(range(27)) + struct.pack("<I", 40600)
    invalid = struct.pack("<IiI", 0, 0x7FFFFFFF, 40600)
    for data in (invalid, *(raw[:cut] for cut in range(len(raw)))):
        reader = SaveReader(b"prefix" + data, 6)
        with pytest.raises(SaveDecodeError):
            read_post_map_world(reader)
        assert reader.pos == 6


@pytest.mark.parametrize("version", (0, 0x44E665, 0x44E667))
def test_exact_save_version_guards(version: int) -> None:
    raw, _ = _synthetic_map()
    reader = SaveReader(raw, version=version)
    with pytest.raises(SaveDecodeError, match="unsupported map save version"):
        read_saved_map(reader)
    assert reader.pos == 0
    with pytest.raises(SaveDecodeError, match="unsupported map save version"):
        read_post_map_world(reader)
    assert reader.pos == 0
