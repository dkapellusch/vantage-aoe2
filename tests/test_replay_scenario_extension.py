"""Current native extension grammar, including variable counts and raw field bits."""

from __future__ import annotations

import gzip
import hashlib
import json
import struct
from pathlib import Path

import pytest

from vantage.replay_binary import SaveDecodeError, SaveReader
from vantage.replay_scenario_extension import read_scenario_extension


def _words(*values: int) -> bytes:
    return struct.pack(f"<{len(values)}I", *values)


def _string(value: bytes) -> bytes:
    return struct.pack("<HH", 0x0A60, len(value)) + value


def _record():
    """Native current branches with two slots and deliberately nonempty vectors."""
    data = bytearray()
    offsets = {}

    def add(name: str, value: bytes) -> None:
        offsets[name] = len(data)
        data.extend(value)

    add("player_info", _words(*range(14)))
    add("checksum1", _words(0x12345678))
    add("victory", _words(0x7FC01234, 2, 3, 4, 5, 6))
    add("fields", _words(7, 8, 9, 10))
    add("attitudes", _words(0, 0xFFFFFFFF, 2, 3))
    add("raw_records", bytes(range(256)) * 5 + bytes(range(160)))  # 2*0x2d0
    add("checksum2", _words(0x23456789))
    add("allied_victory", _words(0xFFFFFFFF, 1))
    add("flags", b"\x80\x01\xff\x04")
    add("disabled_techs", _words(2, 0, 71, 72))
    add("disabled_units", _words(0, 1, 1234))
    add("disabled_buildings", _words(0x7FFF, 0x7FFFFFFF))
    add("options", _words(21, 22, 23))
    add("ages", _words(0xFFFFFFFF, 5))
    add("checksum3", _words(0x3456789A))
    add("global_ages", _words(31, 32, 33))
    add("base_priorities", b"\x00\xff")
    add("trigger_count", _words(0x10203040))
    add("strings", _string(b"water\0x") + _string(b"") + _string(b"weather"))
    add("new_flags", b"\xfe\x02")
    add("player_words", _words(41, 42, 43, 44))
    add("new_flag", b"\x81")
    add("final_player_words", _words(51, 52))
    add("secondary_modes", _words(0x87654321))
    return bytes(data), offsets


@pytest.mark.parametrize("sample", ["3p", "6p"])
def test_native_extensions_reach_the_independent_baseworld_tail(sample: str) -> None:
    path = Path(__file__).parent / "fixtures/native_saved_scenario_extensions_54800.json.gz"
    fixture = json.loads(gzip.decompress(path.read_bytes()))
    case = next(c for c in fixture["cases"] if c["sample"] == sample)
    raw = bytes.fromhex(fixture["bodies"][case["body_sha256"]])
    following = bytes.fromhex(case["following_hex"])
    reader = SaveReader(b"before" + raw + following, 6)
    saved = read_scenario_extension(reader, version_bits=0x3FCB851F, max_players=16)
    assert hashlib.sha256(raw).hexdigest() == case["body_sha256"]
    assert saved.end_offset == reader.pos == len(raw) + 6
    assert len(raw) == 13623 == case["end_offset"] - case["offset"]
    assert saved.raw == raw == b"".join(saved.sections.values())
    assert reader.data[reader.pos :] == following
    assert saved.player_info == tuple((0, 0, 0, 0, 0, 0, p) for p in range(16))
    assert saved.checksums == (0xFFFFFF9D,) * 3
    assert saved.fields[0x45C] == 900 and saved.fields[0x460] == 9000
    assert saved.opponent_attitudes == ((3,) * 16,) * 16
    assert all(c.counts == (0,) * 16 and c.rows == ((),) * 16 for c in saved.disabled.values())
    assert saved.word_arrays[0x430] == (0, 0, 0)
    assert saved.word_arrays[0x440] == (2,) * 16
    assert [saved.byte_arrays[k] for k in (0x468, 0x480, 0x498)] == [b"", b"", b""]
    for name, expected in case["sections"].items():
        actual = saved.sections[name]
        assert len(actual) == expected["bytes"]
        assert hashlib.sha256(actual).hexdigest() == expected["sha256"]


def test_nonempty_current_native_branches_preserve_fields_and_exact_boundaries() -> None:
    raw, _ = _record()
    reader = SaveReader(b"prefix" + raw + b"following", 6)
    saved = read_scenario_extension(reader, version_bits=0x3FCB851F, max_players=2)
    assert (saved.offset, saved.end_offset) == (6, 6 + len(raw))
    assert reader.pos == saved.end_offset and reader.data[reader.pos :] == b"following"
    assert saved.raw == raw == b"".join(saved.sections.values())
    assert saved.player_info == (tuple(range(7)), tuple(range(7, 14)))
    assert saved.checksums == (0x12345678, 0x23456789, 0x3456789A)
    assert saved.word_arrays[0x3A0] == (0x7FC01234, 2, 3, 4, 5, 6)
    assert saved.fields[0x400] == 7 and saved.fields[0x460] == 10
    assert saved.opponent_attitudes == ((0, 0xFFFFFFFF), (2, 3))
    assert all(len(record) == 0x2D0 for record in saved.raw_player_records)
    assert saved.word_arrays[0x3E8] == (0xFFFFFFFF, 1)
    assert [saved.fields[offset] for offset in (0x40C, 0x40D, 0x40E, 0x40F)] == [128, 1, 255, 4]
    assert saved.disabled[0x2D8].counts == (2, 0)
    assert saved.disabled[0x2D8].rows == ((71, 72), ())
    assert saved.disabled[0x308].rows == ((), (1234,))
    assert saved.disabled[0x338].counts == (0x7FFF, 0x7FFFFFFF)
    assert saved.disabled[0x338].rows == ((), ())
    assert saved.word_arrays[0x430] == (21, 22, 23)
    assert saved.word_arrays[0x440] == (0xFFFFFFFF, 5)
    assert saved.byte_arrays == {
        0x350: b"\0\xff",
        0x468: b"water\0x",
        0x480: b"",
        0x498: b"weather",
    }
    assert saved.word_arrays[0x368] == (41, 42, 43, 44)
    assert saved.player_info_final_words == (51, 52)
    assert saved.fields[0x410] == 0x10203040 and saved.fields[0x4B4] == 0x87654321


def test_every_truncated_prefix_fails_with_whole_record_rollback() -> None:
    raw, _ = _record()
    for end in range(len(raw)):
        reader = SaveReader(b"before" + raw[:end], 6)
        with pytest.raises(SaveDecodeError):
            read_scenario_extension(reader, version_bits=0x3FCB851F, max_players=2)
        assert reader.pos == 6


@pytest.mark.parametrize(
    "version,players", [(0x3FCB851E, 2), (0x3FCB851F, -1), (0x3FCB851F, 10**9)]
)
def test_unsupported_context_fails_before_consuming(version: int, players: int) -> None:
    reader = SaveReader(_record()[0])
    with pytest.raises(SaveDecodeError):
        read_scenario_extension(reader, version_bits=version, max_players=players)
    assert reader.pos == 0


@pytest.mark.parametrize("count", [0xFFFFFFFF, 32766])
def test_invalid_disabled_counts_restore_cursor(count: int) -> None:
    raw, offsets = _record()
    damaged = bytearray(raw)
    struct.pack_into("<I", damaged, offsets["disabled_techs"], count)
    reader = SaveReader(b"before" + damaged, 6)
    with pytest.raises(SaveDecodeError):
        read_scenario_extension(reader, version_bits=0x3FCB851F, max_players=2)
    assert reader.pos == 6
