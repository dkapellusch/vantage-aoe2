"""Native player second-pass boundaries, raw fields and transactional failures."""

from __future__ import annotations

import gzip
import hashlib
import json
import struct
from functools import cache
from pathlib import Path

import pytest

from vantage.replay_binary import SaveDecodeError, SaveReader
from vantage.replay_player_restore import read_player_restore

FIXTURE = Path(__file__).parent / "fixtures/native_saved_player_restore_54800.json.gz"


@cache
def _fixture():
    return json.loads(gzip.decompress(FIXTURE.read_bytes()))


def _record(*, first: tuple[bytes, ...] = (), second: tuple[bytes, ...] = ()) -> bytes:
    return (
        struct.pack("<IiB", 0x40066666, len(first), 0xD3)
        + b"".join(first)
        + struct.pack("<IiII", 0x80000000, len(second), 0xFFFFFFFF, 0x7FA01234)
        + b"".join(second)
    )


def _first() -> bytes:
    return struct.pack(
        "<BIi6IiiBBB",
        0xF1,
        0x7FC01234,
        -7,
        0xFFFFFFFF,
        0x80000000,
        3,
        4,
        5,
        6,
        123456,
        0x7FFFFFFF,
        0x80,
        0xFE,
        0xFF,
    )


def _second() -> bytes:
    return struct.pack(
        "<BB4IBB3I",
        0xD4,
        0xA7,
        1,
        2,
        0xFFFFFFFF,
        0x7FC01234,
        0xFE,
        0xFF,
        0x80000000,
        0x7FA01234,
        0xDEADBEEF,
    )


@pytest.mark.parametrize("case", _fixture()["cases"])
def test_native_all_eleven_player_restore_boundaries(case) -> None:
    raw = bytes.fromhex(_fixture()["bodies"][case["body_sha256"]])
    reader = SaveReader(b"prefix" + raw + b"next world section", 6)
    saved = read_player_restore(reader)
    assert saved.offset == 6 and saved.end_offset == reader.pos == 6 + len(raw)
    assert case["start"] + len(raw) == case["end"]
    assert hashlib.sha256(saved.raw).hexdigest() == case["raw_sha256"]
    assert saved.raw == raw == b"".join(saved.sections.values())
    assert len(raw) == 25 + 44 * saved.first_count + 32 * saved.second_count
    assert saved.version_bits == 0x40066666
    assert saved.first_count == case["first_count"] == 0
    assert saved.first_records == ()
    assert saved.second_count == case["second_count"] == (0 if case["player_id"] == 0 else 108)
    assert len(saved.second_records) == saved.second_count
    assert saved.fields == {0x10: 0, 0x20: 0, 0x38: 0, 0x40: 0, 0x44: 0xFFFFFFFF}
    for name in ("first", "second"):
        assert (
            hashlib.sha256(saved.sections[f"{name}_records"]).hexdigest()
            == case[f"{name}_records_sha256"]
        )
    for entry in saved.second_records:
        assert len(entry.raw) == 32
        assert entry.raw == reader.data[entry.offset : entry.end_offset]
        assert entry.raw == struct.pack(
            "<BB4IBB3I",
            *(
                entry.fields[offset]
                for offset in (0, 1, 8, 0x10, 0x14, 0x18, 2, 4, 0x1C, 0xC, 0x20)
            ),
        )
    assert reader.data[reader.pos :] == b"next world section"


def test_portable_corpus_has_two_bodies_and_exact_native_section_ends() -> None:
    fixture = _fixture()
    assert len(fixture["bodies"]) == 2
    assert sum(case["second_count"] for case in fixture["cases"]) == 972
    assert sum(case["end"] - case["start"] for case in fixture["cases"]) == 31379
    assert [(sample["start"], sample["end"]) for sample in fixture["samples"]] == [
        (11451902, 11462370),
        (23782218, 23803129),
    ]


@pytest.mark.parametrize("first,second", ((1, 0), (0, 1), (2, 2)))
def test_constructed_nonempty_records_preserve_native_offsets_ids_and_bits(
    first: int, second: int
) -> None:
    first_raw, second_raw = _first(), _second()
    assert len(first_raw) == 44 and len(second_raw) == 32
    raw = _record(first=(first_raw,) * first, second=(second_raw,) * second)
    reader = SaveReader(b"pad" + raw + b"tail", 3)
    saved = read_player_restore(reader)
    assert saved.raw == raw == b"".join(saved.sections.values())
    assert saved.first_count == first and saved.second_count == second
    assert saved.fields == {
        0x10: first,
        0x20: 0xD3,
        0x38: 0x80000000,
        0x40: 0xFFFFFFFF,
        0x44: 0x7FA01234,
    }
    for index, entry in enumerate(saved.first_records):
        assert entry.offset == saved.offset + 9 + 44 * index
        assert entry.end_offset - entry.offset == 44
        assert entry.raw == first_raw == reader.data[entry.offset : entry.end_offset]
        assert entry.reference_ids == {8: -7, 0x28: 123456, 0x30: 0x7FFFFFFF}
        assert entry.fields == {
            0: 0xF1,
            4: 0x7FC01234,
            0x10: 0xFFFFFFFF,
            0x14: 0x80000000,
            0x18: 3,
            0x1C: 4,
            0x20: 5,
            0x24: 6,
            0x38: 0x80,
            0x39: 0xFE,
            0x3A: 0xFF,
        }
    for index, entry in enumerate(saved.second_records):
        assert entry.offset == saved.offset + 25 + 44 * first + 32 * index
        assert entry.end_offset - entry.offset == 32
        assert entry.raw == second_raw == reader.data[entry.offset : entry.end_offset]
        assert entry.fields == {
            0: 0xD4,
            1: 0xA7,
            8: 1,
            0x10: 2,
            0x14: 0xFFFFFFFF,
            0x18: 0x7FC01234,
            2: 0xFE,
            4: 0xFF,
            0x1C: 0x80000000,
            0xC: 0x7FA01234,
            0x20: 0xDEADBEEF,
        }
    assert reader.data[reader.pos :] == b"tail"


def test_every_truncation_of_both_native_profiles_and_nonempty_first_list_rolls_back() -> None:
    bodies = [bytes.fromhex(raw) for raw in _fixture()["bodies"].values()]
    bodies.append(_record(first=(_first(), _first()), second=(_second(),)))
    for raw in bodies:
        for cut in range(len(raw)):
            reader = SaveReader(b"prefix" + raw[:cut], 6)
            with pytest.raises(SaveDecodeError):
                read_player_restore(reader)
            assert reader.pos == 6, (len(raw), cut)


@pytest.mark.parametrize("offset", (4, 13))
@pytest.mark.parametrize("count", (-2147483648, -1, 1, 0x7FFFFFFF))
def test_negative_or_impossible_counts_roll_back(offset: int, count: int) -> None:
    raw = bytearray(_record())
    struct.pack_into("<i", raw, offset, count)
    reader = SaveReader(b"pad" + raw, 3)
    with pytest.raises(SaveDecodeError, match="array count") as error:
        read_player_restore(reader)
    assert error.value.offset == 3 + offset and reader.pos == 3


@pytest.mark.parametrize("version", (0, 0x3F800000, 0x40000000, 0x40066665, 0x40066667, 0x7FC01234))
def test_other_subsystem_versions_are_explicit_and_transactional(version: int) -> None:
    raw = bytearray(_record())
    struct.pack_into("<I", raw, 0, version)
    reader = SaveReader(b"pad" + raw, 3)
    with pytest.raises(SaveDecodeError, match="restore version bits") as error:
        read_player_restore(reader)
    assert error.value.offset == reader.pos == 3


def test_other_outer_save_version_rolls_back_without_reading() -> None:
    reader = SaveReader(b"prefix" + _record(), 6, version=0x44E667)
    with pytest.raises(SaveDecodeError, match="restore save version") as error:
        read_player_restore(reader)
    assert error.value.offset == reader.pos == 6
