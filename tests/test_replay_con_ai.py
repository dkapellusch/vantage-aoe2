"""Con AI native slices and offline edge cases, without local game files."""

from __future__ import annotations

import hashlib
import struct

import pytest

from vantage.replay_binary import SaveDecodeError, SaveReader
from vantage.replay_con_ai import read_con_ai

# Original v54800 recording slices; exact input hashes and offsets are retained
# by artifacts/game-internals/2026-10-18-player-ai/con/report.json.
_SAMPLES = (
    (
        8180643,
        0x42DF0000,
        0x42930000,
        144,
        "7e4d2be038c4c62b823a322baa06a4ea4c5e5448c959e8c2c157f6e231590f64",
    ),
    (
        10067553,
        0x425A0000,
        0x42DB0000,
        144,
        "a8fb8ce9ebdde273177344d48d2a6309247311fcbf654a30d9a91d20c453ff43",
    ),
    (
        15126071,
        0x41D40000,
        0x42A50000,
        200,
        "7837f22d3d8b9eda571513235bd006c2ce68176a0a7d760719c66f2e2166b41f",
    ),
    (
        16970154,
        0x42B30000,
        0x419C0000,
        200,
        "52e980d7ceeb37049fa8626aa798e98be9329e5537f9b9fcc078b4ff5b412f5a",
    ),
    (
        18551812,
        0x43168000,
        0x42760000,
        200,
        "eaa1591d40a2107b5891775637b7368156058f6637e4729f30154dadb51dbe48",
    ),
    (
        20395978,
        0x42CB0000,
        0x432A8000,
        200,
        "674d22b310fdd4e458e002cd7f4df1cb1e519fc8ce810130a155d48804517156",
    ),
    (
        21978133,
        0x42120000,
        0x43098000,
        200,
        "e7bb0494e65fa92eddaffa2ffaae9391a84ea9249a69f8e55b7c622a5fb78d8c",
    ),
)


def _record(
    *,
    first: tuple[tuple[bytes, tuple[int, ...]], ...] = (),
    second: tuple[tuple[bytes, tuple[int, ...]], ...] = (),
    text: bytes = b"",
    words: tuple[int, ...] = (0, 0, 0, 0, 0),
    counts: tuple[int, int] | None = None,
) -> bytes:
    count1, count2 = counts if counts is not None else (len(first), len(second))
    out = struct.pack("<Hii", 0xA10, count1, len(text)) + text
    out += struct.pack("<5IH", *words, 0xAA0)
    for name, values in first:
        out += struct.pack("<i", len(name)) + name + struct.pack("<13I", *values)
    out += struct.pack("<Hi", 0xAA0, count2)
    for name, values in second:
        out += struct.pack("<i", len(name)) + name + struct.pack("<13I", *values)
    return out + struct.pack("<H", 0xA20)


@pytest.mark.parametrize("offset,x_word,y_word,size,digest", _SAMPLES)
def test_native_con_ai_slices(
    offset: int, x_word: int, y_word: int, size: int, digest: str
) -> None:
    raw = _record(words=(x_word, y_word, 0, size, size))
    assert len(raw) == 40
    assert hashlib.sha256(raw).hexdigest() == digest
    # The original offset is asserted from the durable report. A small local
    # prefix also verifies the parser honors its caller's cursor.
    reader = SaveReader(b"prefix" + raw + b"\x10\x0a\x31\0\0\0", 6)
    saved = read_con_ai(reader)
    assert offset + len(saved.raw) in {
        8180683,
        10067593,
        15126111,
        16970194,
        18551852,
        20396018,
        21978173,
    }
    assert (saved.offset, saved.end_offset, reader.pos) == (6, 46, 46)
    assert saved.raw == raw
    assert saved.text == "" and saved.text_bytes == b""
    assert saved.first_list_count == saved.second_list_count == 0
    assert saved.first_list == saved.second_list == ()
    assert saved.fields == {
        0xB0: 0,
        0x1F8: x_word,
        0x1FC: y_word,
        0x200: 0,
        0x204: size,
        0x208: size,
        0x148: 0,
    }
    assert reader.u16() == 0xA10  # Following Diplomacy AI remains untouched.


def test_nonempty_lists_preserve_every_wire_word_and_string_byte() -> None:
    first_words = (0xFFFFFFFF, 0x80000000, 0x7FC01234, *range(10))
    second_words = tuple(range(100, 113))
    raw = _record(
        first=((b"first\0\xff", first_words), (b"", second_words)),
        second=((b"second", second_words),),
        text=b"raw\0\xff",
        words=(0x7FA12345, 0x80000000, 0xFFFFFFFF, 200, 200),
    )
    reader = SaveReader(raw + b"trailing")
    saved = read_con_ai(reader)
    assert saved.raw == raw and reader.pos == len(raw)
    assert saved.text_bytes == b"raw\0\xff" and saved.text == "raw\0\ufffd"
    assert saved.fields[0x1F8] == 0x7FA12345
    assert saved.first_list_count == 2 and saved.second_list_count == 1
    first, empty = saved.first_list
    assert first.name_bytes == b"first\0\xff" and first.name == "first\0\ufffd"
    assert first.words == first_words
    assert empty.name_bytes == b"" and empty.words == second_words
    assert saved.second_list[0].words == second_words
    for entry in (*saved.first_list, *saved.second_list):
        assert entry.raw == raw[entry.offset : entry.end_offset]
        assert len(entry.raw) == 56 + len(entry.name_bytes)


def test_native_negative_counts_mean_no_entries_and_keep_original_bits() -> None:
    raw = _record(counts=(-1, -2147483648))
    saved = read_con_ai(SaveReader(raw))
    assert saved.first_list_count == -1 and saved.second_list_count == -2147483648
    assert saved.fields[0xB0] == 0xFFFFFFFF and saved.fields[0x148] == 0x80000000
    assert saved.first_list == saved.second_list == ()


def test_native_maximum_entry_name_has_no_extra_wire_nul() -> None:
    raw = _record(first=((b"x" * 256, (0,) * 13),))
    saved = read_con_ai(SaveReader(raw))
    assert saved.first_list[0].name_bytes == b"x" * 256
    assert saved.end_offset == len(raw) == 352


@pytest.mark.parametrize("marker_at", (0, 30, 32, 38))
def test_bad_ai_markers_restore_original_cursor(marker_at: int) -> None:
    raw = bytearray(_record())
    raw[marker_at] ^= 1
    reader = SaveReader(b"padding" + raw, 7)
    with pytest.raises(SaveDecodeError, match="AI marker"):
        read_con_ai(reader)
    assert reader.pos == 7


@pytest.mark.parametrize(
    "at,value",
    ((2, 1), (2, 0x7FFFFFFF), (6, -1), (6, 0x7FFFFFFF), (34, 1), (34, 0x7FFFFFFF)),
)
def test_impossible_lengths_and_counts_roll_back(at: int, value: int) -> None:
    raw = bytearray(_record())
    struct.pack_into("<i", raw, at, value)
    reader = SaveReader(raw)
    with pytest.raises(SaveDecodeError):
        read_con_ai(reader)
    assert reader.pos == 0


@pytest.mark.parametrize("length", (-1, 257, 0x7FFFFFFF))
@pytest.mark.parametrize("which", ("first", "second"))
def test_invalid_entry_name_length_rolls_back(length: int, which: str) -> None:
    raw = bytearray(_record(**{which: ((b"", (0,) * 13),)}))
    struct.pack_into("<i", raw, 32 if which == "first" else 38, length)
    reader = SaveReader(raw)
    with pytest.raises(SaveDecodeError, match="entry name length"):
        read_con_ai(reader)
    assert reader.pos == 0


def test_every_truncation_rolls_back() -> None:
    raw = _record(
        first=((b"first", tuple(range(13))),),
        second=((b"second", tuple(range(20, 33))),),
        text=b"text",
    )
    for length in range(len(raw)):
        reader = SaveReader(b"prefix" + raw[:length], 6)
        with pytest.raises(SaveDecodeError):
            read_con_ai(reader)
        assert reader.pos == 6, length


@pytest.mark.parametrize("version", (0, 0x44E665, 0x44E667))
def test_exact_save_version_guard(version: int) -> None:
    reader = SaveReader(_record(), version=version)
    with pytest.raises(SaveDecodeError, match="unsupported Con AI save version"):
        read_con_ai(reader)
    assert reader.pos == 0
