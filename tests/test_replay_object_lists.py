"""Native list framing, complete raw coverage and independent Gaia oracles."""

from __future__ import annotations

import gzip
import hashlib
import json
import math
import struct
from collections import Counter
from functools import cache
from pathlib import Path

import pytest

from vantage.replay_binary import SaveDecodeError, SaveReader
from vantage.replay_object_lists import (
    STAT_MODIFIER_NAMES,
    read_object_list,
    read_player_object_lists,
)

FIXTURE = Path(__file__).parent / "fixtures" / "native_saved_object_lists_54800.json.gz"


@cache
def _fixture():
    return json.loads(gzip.decompress(FIXTURE.read_bytes()))


def _object() -> bytes:
    sample = _fixture()["samples"][0]
    # Its first static object has a native-proven 134-byte record length.
    return bytes.fromhex(sample["raw_hex"])[9 : 9 + 134]


def _list(raw_objects: bytes = b"", capacity: int = 0, growth: int = 0) -> bytes:
    return struct.pack("<ii", capacity, growth) + raw_objects + b"\0"


def _trailer(present: int = 1) -> bytes:
    return (
        b"\x0b"
        + bytes([present])
        + (struct.pack("<10I", *([0x3F800000] * 10)) if present else b"")
        + b"\x0b"
        + struct.pack("<iiBiiii", -1, -1, 0, 0, 0, 0, 0)
        + b"\x0b"
    )


def _group(ordinary: bytes = b"", present: int = 1) -> bytes:
    return b"\x0b" + _list(ordinary) + b"\x0b" + _list() + b"\x0b" + _list() + _trailer(present)


def test_all_19103_gaia_records_against_independent_native_snapshots() -> None:
    total = zero_ids = 0
    fixture = _fixture()
    assert fixture["oracle_struct_little_endian"] == "<qiiifffifBB"
    oracle = struct.Struct(fixture["oracle_struct_little_endian"])
    for sample in fixture["samples"]:
        raw = bytes.fromhex(sample["raw_hex"])
        following = bytes.fromhex(sample["following_hex"])
        reader = SaveReader(b"prefix" + raw + following, len(b"prefix"))
        group = read_player_object_lists(reader)
        assert reader.data[reader.pos :] == following
        assert group.raw == raw
        assert hashlib.sha256(raw).hexdigest() == sample["raw_sha256"]
        assert group.end_offset - group.offset == sample["end_offset"] - sample["offset"]
        assert group.offset == len(b"prefix")
        assert raw == (
            b"\x0b"
            + group.ordinary.raw
            + b"\x0b"
            + group.sleeping.raw
            + b"\x0b"
            + group.dopple.raw
            + group.trailer.raw
        )
        assert group.trailer.raw == bytes.fromhex(sample["trailer"]["raw_hex"])
        assert len(group.trailer.raw) == 69
        assert group.trailer.have_stat_modifiers == 1
        assert group.trailer.stat_modifier_bits == (0x3F800000,) * 10
        assert group.trailer.stat_modifiers == (1.0,) * 10
        assert group.trailer.preset_mask == group.trailer.active_preset == -1
        assert (
            group.trailer.auto_farms,
            group.trailer.wood,
            group.trailer.food,
            group.trailer.gold,
            group.trailer.stone,
        ) == (0, 0, 0, 0, 0)
        ids = set()
        digest = hashlib.sha256()
        for expected in sample["lists"]:
            name = expected["name"]
            saved = getattr(group, name)
            assert (saved.capacity, saved.growth_increment) == (
                expected["capacity"],
                expected["growth_increment"],
            )
            assert len(saved.objects) == expected["record_count"]
            assert Counter(obj.type_group for obj in saved.objects) == {
                int(key): count for key, count in expected["type_counts"].items()
            }
            assert saved.raw == (
                struct.pack("<ii", saved.capacity, saved.growth_increment)
                + b"".join(obj.raw for obj in saved.objects)
                + b"\0"
            )
            assert hashlib.sha256(saved.raw).hexdigest() == expected["raw_sha256"]
            assert saved.end_offset - saved.offset == expected["raw_bytes"]
            assert saved.terminator_offset == saved.end_offset - 1
            pos = saved.offset + 8
            for obj in saved.objects:
                assert obj.offset == pos
                assert obj.end_offset - obj.offset == len(obj.raw)
                pos = obj.end_offset
                native_id = obj.object_id
                if native_id == 0:
                    zero_ids += 1
                    mapping = sample["zero_id_correspondence"][0]
                    assert (obj.master_id, list(obj.position[:2])) == (
                        mapping["master_id"],
                        mapping["xy"],
                    )
                    native_id = mapping["native_id"]
                assert native_id not in ids
                ids.add(native_id)
                assert obj.attributes == ()
                digest.update(
                    oracle.pack(
                        native_id,
                        obj.owner,
                        obj.master_id,
                        obj.sprite_id,
                        obj.hp,
                        *obj.position[:2],
                        obj.held_resource_type,
                        obj.held_resource_amount,
                        name == "sleeping",
                        name == "dopple",
                    )
                )
                total += 1
            assert pos == saved.terminator_offset
        assert len(ids) == sample["record_count"]
        assert digest.hexdigest() == sample["native_semantics_sha256"]
        id_bytes = json.dumps(sorted(ids), separators=(",", ":")).encode()
        assert hashlib.sha256(id_bytes).hexdigest() == sample["native_id_set_sha256"]
    assert total == 19103
    assert zero_ids == 2


def test_list_allocation_fields_do_not_determine_record_count() -> None:
    raw = _list(_object(), capacity=0, growth=0)
    reader = SaveReader(raw + b"untouched")
    saved = read_object_list(reader)
    assert len(saved.objects) == 1
    assert saved.capacity == saved.growth_increment == 0
    assert saved.objects[0].object_id == 0
    assert saved.raw == raw
    assert reader.data[reader.pos :] == b"untouched"
    empty = read_object_list(SaveReader(_list(capacity=0x7FFFFFFF, growth=8192)))
    assert empty.objects == ()
    assert empty.capacity == 0x7FFFFFFF


def test_single_list_every_truncation_rolls_back() -> None:
    raw = _list(_object(), capacity=3072, growth=512)
    for end in range(len(raw)):
        reader = SaveReader(b"before" + raw[:end], len(b"before"))
        with pytest.raises(SaveDecodeError):
            read_object_list(reader)
        assert reader.pos == len(b"before")


@pytest.mark.parametrize("present", [0, 1])
def test_group_every_truncation_rolls_back(present: int) -> None:
    raw = _group(present=present)
    for end in range(len(raw)):
        reader = SaveReader(b"before" + raw[:end], len(b"before"))
        with pytest.raises(SaveDecodeError):
            read_player_object_lists(reader)
        assert reader.pos == len(b"before")
    reader = SaveReader(raw + b"next player")
    group = read_player_object_lists(reader)
    assert reader.data[reader.pos :] == b"next player"
    assert group.trailer.have_stat_modifiers == present
    assert len(group.trailer.stat_modifier_bits) == (10 if present else 0)
    assert len(group.trailer.raw) == (69 if present else 29)


@pytest.mark.parametrize("marker_offset", [0, 10, 20, 30, 72, 98])
def test_each_group_marker_is_required_without_resynchronization(marker_offset: int) -> None:
    raw = bytearray(_group())
    assert raw[marker_offset] == 11
    raw[marker_offset] = 12
    reader = SaveReader(bytes(raw) + _group())
    with pytest.raises(SaveDecodeError, match="expected marker 11"):
        read_player_object_lists(reader)
    assert reader.pos == 0


def test_later_unsupported_actor_rolls_back_the_entire_group() -> None:
    raw = b"\x0b" + _list(_object()) + b"\x0b" + _list(b"\x5a")
    reader = SaveReader(b"prefix" + raw, len(b"prefix"))
    with pytest.raises(SaveDecodeError, match="type group 90"):
        read_player_object_lists(reader)
    assert reader.pos == len(b"prefix")


@pytest.mark.parametrize("read", [read_object_list, read_player_object_lists])
def test_unverified_version_rolls_back_before_reading(read) -> None:
    reader = SaveReader(b"prefix" + _group(), len(b"prefix"), version=0x450000)
    with pytest.raises(SaveDecodeError, match="save version"):
        read(reader)
    assert reader.pos == len(b"prefix")


def test_trailer_preserves_modifier_bits_flags_and_preset_resource_order() -> None:
    words = (
        0x7FC01234,
        0xFFC05678,
        0x7F800000,
        0xFF800000,
        0x80000000,
        0,
        0x3F800000,
        0x40000000,
        0x40400000,
        0x40800000,
    )
    trailer = (
        b"\x0b\x02"
        + struct.pack("<10I", *words)
        + b"\x0b"
        + struct.pack("<iiBiiii", -2147483648, 17, 255, 1, -2, 3, -4)
        + b"\x0b"
    )
    raw = b"\x0b" + _list() + b"\x0b" + _list() + b"\x0b" + _list() + trailer
    group = read_player_object_lists(SaveReader(raw))
    saved = group.trailer
    assert saved.raw == trailer
    assert saved.have_stat_modifiers == 2
    assert saved.stat_modifier_bits == words
    assert len(STAT_MODIFIER_NAMES) == len(words) == 10
    assert math.isnan(saved.stat_modifiers[0])
    assert math.isnan(saved.stat_modifiers[1])
    assert saved.stat_modifiers[2:4] == (math.inf, -math.inf)
    assert math.copysign(1, saved.stat_modifiers[4]) == -1
    assert (saved.preset_mask, saved.active_preset, saved.auto_farms) == (-2147483648, 17, 255)
    assert (saved.wood, saved.food, saved.gold, saved.stone) == (1, -2, 3, -4)
