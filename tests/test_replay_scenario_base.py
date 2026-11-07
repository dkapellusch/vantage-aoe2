"""Original native BaseScenario slices plus nonempty wire variants and rollback."""

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
from vantage.replay_scenario_base import read_scenario_base

FIXTURE = Path(__file__).parent / "fixtures/native_scenario_bases_159.json.gz"


@lru_cache(maxsize=1)
def _cases() -> list[dict[str, Any]]:
    return list(json.loads(gzip.decompress(FIXTURE.read_bytes()))["cases"])


def _raw(index: int = 0) -> bytes:
    case = _cases()[index]
    raw = bytes.fromhex(case["raw_hex"])
    assert hashlib.sha256(raw).hexdigest() == case["raw_sha256"]
    return raw


def _patch(name: str, value: bytes) -> bytes:
    start, end = _cases()[0]["spans"][name]
    raw = _raw()
    return raw[:start] + value + raw[end:]


def _short(value: bytes) -> bytes:
    return struct.pack("<h", len(value)) + value


def _de(value: bytes, *, reverse: bool = False) -> bytes:
    words = (len(value), 0x0A60) if reverse else (0x0A60, len(value))
    return struct.pack("<HH", *words) + value


def _synthetic(*, active: tuple[int, ...] = (1, 1), width: int = 3, height: int = 2) -> bytes:
    """Independent encoder for native current branches; no shipping DTO/fields used."""
    count = len(active)
    data = bytearray(struct.pack("<III", 0x3FCB851F, count, 8))
    for i in range(count):
        data.extend(bytes((i, 0, 255, 65)) * 64)
    data.extend(struct.pack("<" + "I" * count, *[0xFFFFFFFF - i for i in range(count)]))
    for i, flag in enumerate(active):
        data.extend(struct.pack("<II", flag, 0x80000000 + i))
        data.extend(_de(b"civ\0\xff" + bytes((i,)), reverse=bool(i % 2)))
        data.extend(_de(b"arch\0\xfe" + bytes((i,))))
        data.extend(struct.pack("<I", 0xABCDEF00 + i))
    for tag in (0x100, 0x200):
        data.extend(struct.pack("<" + "I" * count, *[tag + i for i in range(count)]))
    data.extend(struct.pack("<BhHI", 0xFE, -1, 0xFEDC, 0x7FC01234))
    data.extend(_short(b"caption\0\xff"))
    data.extend(struct.pack("<6I", 0xFFFFFFFF, 0xFFFFFFFE, 0, 1, 0x80000000, 123456789))
    for i in range(6):
        data.extend(_short(b"resource text\0" + bytes((i,))))
    for i in range(4):
        data.extend(_short(b"member\0" + bytes((i,))))
    data.extend(struct.pack("<IiiH", 3, width, height, 0xFEDC))
    if width > 0 and height > 0:
        size = height * ((width + 3) & ~3) + 0x428
        data.extend(bytes(i % 256 for i in range(size)))
    # Native has three complete filename arrays, then per-player size/blob rows.
    for tag in (b"build", b"city", b"rules"):
        for i in range(count):
            data.extend(_short(tag + b"\0\xff" + bytes((i,))))
    for i in range(count):
        blobs = (b"build\0" + bytes((i,)), b"", b"(defrule)\xff" + bytes((i,)))
        data.extend(struct.pack("<iii", *[len(blob) for blob in blobs]))
        for blob in blobs:
            data.extend(blob)
    data.extend(bytes(0xF0 + i for i in range(count)))
    data.extend(struct.pack("<I", 0x87654321))
    return bytes(data)


@pytest.mark.parametrize("index", (0, 1))
def test_original_native_scenario_fields_and_exact_derived_boundary(index: int) -> None:
    case = _cases()[index]
    raw = _raw(index)
    following = bytes.fromhex(case["following_hex"])
    prefix = b"prefix!"
    reader = SaveReader(prefix + raw + following, len(prefix))
    saved = read_scenario_base(reader)
    assert saved.offset == len(prefix)
    assert saved.end_offset == len(prefix) + case["end"] - case["start"]
    assert saved.raw == raw
    assert reader.take(len(following)) == following
    assert saved.version_bits == 0x3FCB851F
    assert saved.max_players == 16 and saved.gaia_player_index == 8
    assert len(saved.players) == 16
    assert all(len(player.name_256) == 256 for player in saved.players)
    assert len(saved.fields) == 392
    cursor = saved.offset
    for field in saved.fields:
        start, end = case["spans"][field.name]
        assert (field.offset, field.end_offset) == (len(prefix) + start, len(prefix) + end)
        assert field.offset == cursor
        assert field.raw == raw[start:end]
        cursor = field.end_offset
    assert cursor == saved.end_offset
    assert saved.bitmap.version_word == 3
    assert (saved.bitmap.width, saved.bitmap.height, saved.bitmap.orientation_word) == (0, 0, 1)
    assert saved.resource_texts[0].startswith(b"Conquest Game:")
    assert saved.resource_texts[1:] == (b"",) * 5
    assert all(player.ai_rules_type_byte == 1 for player in saved.players)
    assert saved.tail_word == 0xFFFFFF9D  # Last Base checksum, preceding derived resource rows.


def test_nonempty_arrays_strings_files_bitmap_and_original_bits() -> None:
    raw = _synthetic()
    reader = SaveReader(raw + b"following")
    saved = read_scenario_base(reader)
    assert reader.pos == len(raw) and saved.raw == raw
    assert reader.take(9) == b"following"
    assert saved.list_num == -1 and saved.avail_id_word == 0xFEDC
    assert saved.old_time_bits == 0x7FC01234  # NaN payload remains exact.
    assert saved.victory_conquest_byte == 0xFE
    assert saved.member_248 == b"caption\0\xff"
    assert saved.resource_string_id_words == (
        0xFFFFFFFF,
        0xFFFFFFFE,
        0,
        1,
        0x80000000,
        123456789,
    )
    assert saved.resource_texts == tuple(b"resource text\0" + bytes((i,)) for i in range(6))
    assert (saved.member_290, saved.member_260, saved.member_278, saved.member_2a8) == tuple(
        b"member\0" + bytes((i,)) for i in range(4)
    )
    for i, player in enumerate(saved.players):
        assert player.name_256 == bytes((i, 0, 255, 65)) * 64
        assert player.name_string_id_word == 0xFFFFFFFF - i
        assert player.type_word == 0x80000000 + i
        assert player.posture_word == 0xABCDEF00 + i
        assert player.civilization == b"civ\0\xff" + bytes((i,))
        assert player.architecture == b"arch\0\xfe" + bytes((i,))
        assert player.civilization_lock_word == 0x100 + i
        assert player.personality_lock_word == 0x200 + i
        assert player.build_list_filename == b"build\0\xff" + bytes((i,))
        assert player.city_plan_filename == b"city\0\xff" + bytes((i,))
        assert player.ai_rules_filename == b"rules\0\xff" + bytes((i,))
        assert player.build_list_data == b"build\0" + bytes((i,))
        assert player.city_plan_data == b""
        assert player.ai_rules_data == b"(defrule)\xff" + bytes((i,))
        assert player.ai_rules_type_byte == 0xF0 + i
    assert saved.tail_word == 0x87654321
    assert (saved.bitmap.width, saved.bitmap.height, saved.bitmap.orientation_word) == (
        3,
        2,
        0xFEDC,
    )
    assert saved.bitmap.payload == bytes(i % 256 for i in range(2 * 4 + 0x428))


@pytest.mark.parametrize(("width", "height"), ((0, 0), (-1, 1), (1, -1), (0, 2), (2, 0)))
def test_bitmap_nonpositive_dimension_consumes_no_payload(width: int, height: int) -> None:
    raw = _synthetic(width=width, height=height)
    saved = read_scenario_base(SaveReader(raw))
    assert saved.raw == raw and saved.bitmap.payload == b""
    assert (saved.bitmap.width, saved.bitmap.height) == (width, height)


@pytest.mark.parametrize("active", ((0, 1), (1, 0, 1), (1,) * 9))
def test_native_active_player_invariants_rollback(active: tuple[int, ...]) -> None:
    reader = SaveReader(b"prefix" + _synthetic(active=active), 6)
    with pytest.raises(SaveDecodeError, match="active-player"):
        read_scenario_base(reader)
    assert reader.pos == 6


@pytest.mark.parametrize("active", ((1, 1, 0, 0), (2, 0), (0, 0)))
def test_native_active_words_are_nonzero_flags_with_contiguous_prefix(
    active: tuple[int, ...],
) -> None:
    saved = read_scenario_base(SaveReader(_synthetic(active=active)))
    assert tuple(player.active_word for player in saved.players) == active


@pytest.mark.parametrize(
    ("name", "value", "message"),
    (
        ("version_bits", struct.pack("<I", 0x3FCB851E), "version"),
        ("MaxPlayers", b"\xff" * 4, "player count"),
        ("list_num", struct.pack("<h", 1), "list_num"),
        ("member_248.length", b"\xff\xff", "short-string"),
        ("resource_text_228.length", b"\x00\x80", "short-string"),
        ("ai_rules_filename[15].length", b"\xff\xff", "short-string"),
        ("build_list_size[0]", b"\xff" * 4, "file size"),
        ("ai_rules_size[15]", struct.pack("<i", 0xA00001), "file size"),
    ),
)
def test_malformed_lengths_versions_and_counts_rollback(
    name: str,
    value: bytes,
    message: str,
) -> None:
    reader = SaveReader(b"prefix" + _patch(name, value), 6)
    with pytest.raises(SaveDecodeError, match=message):
        read_scenario_base(reader)
    assert reader.pos == 6 and reader.version == 0x44E666


def test_invalid_de_marker_rolls_back_entire_scenario() -> None:
    raw = _raw()
    start, _ = _cases()[0]["spans"]["architecture[15]"]
    raw = raw[:start] + b"\0" * 4 + raw[start + 4 :]
    reader = SaveReader(raw)
    with pytest.raises(SaveDecodeError, match="DE string marker"):
        read_scenario_base(reader)
    assert reader.pos == 0


def test_save_version_guard_precedes_all_wire_reads() -> None:
    reader = SaveReader(b"prefix", 6, version=0x44E665)
    with pytest.raises(SaveDecodeError, match=r"save68\.9"):
        read_scenario_base(reader)
    assert reader.pos == 6 and reader.version == 0x44E665


def test_bitmap_overflow_is_bounded_and_rolls_back() -> None:
    raw = _patch("bitmap.width", struct.pack("<i", 0x7FFFFFFF))
    start, end = _cases()[0]["spans"]["bitmap.height"]
    raw = raw[:start] + struct.pack("<i", 2) + raw[end:]
    reader = SaveReader(raw)
    with pytest.raises(SaveDecodeError, match="bitmap byte count"):
        read_scenario_base(reader)
    assert reader.pos == 0


def test_every_original_native_truncation_rolls_back() -> None:
    raw = _raw()
    for cut in range(len(raw)):
        reader = SaveReader(b"prefix" + raw[:cut], 6)
        with pytest.raises(SaveDecodeError):
            read_scenario_base(reader)
        assert reader.pos == 6, cut


def test_nonempty_file_and_bitmap_truncation_roll_back() -> None:
    raw = _synthetic()
    saved = read_scenario_base(SaveReader(raw))
    for field in saved.fields:
        if field.name in ("bitmap.payload", "ai_rules_data[1]"):
            reader = SaveReader(raw[: field.end_offset - 1])
            with pytest.raises(SaveDecodeError):
                read_scenario_base(reader)
            assert reader.pos == 0
