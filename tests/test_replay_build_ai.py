"""Native saved BuildAI fixtures and constructed nonempty-list coverage."""

from __future__ import annotations

import gzip
import hashlib
import json
import struct
from functools import cache
from pathlib import Path

import pytest

from vantage.replay_binary import SaveDecodeError, SaveReader
from vantage.replay_build_ai import BUILD_ENTRY_WORD_LOCALS, read_build_ai

FIXTURE = Path(__file__).parent / "fixtures" / "native_saved_build_ai_54800.json.gz"


@cache
def _samples():
    return json.loads(gzip.decompress(FIXTURE.read_bytes()))["samples"]


def _string(value: bytes) -> bytes:
    return struct.pack("<i", len(value)) + value


def _entry(name: bytes, number: int) -> bytes:
    words = tuple((0x80000000 + number + index) & 0xFFFFFFFF for index in range(22))
    return (
        b"\xa0\x0a"
        + _string(name)
        + struct.pack("<22I", *words)
        + struct.pack("<BBIBB", 2, 255, 0x7FC01234, 3, 1)
    )


def _constructed(entries: tuple[bytes, ...] = (), name: bytes = b"name") -> tuple[bytes, bytes]:
    base = (
        b"\x10\x0a"
        + struct.pack("<I", 73)
        + b"".join(_string(value) for value in (name, b"\xff\0", b"", b"four"))
        + b"\xa0\x0a"
        + struct.pack("<Ii", 0xFF800000, len(entries))
        + b"".join(entries)
        + b"\x20\x0a"
    )
    words = tuple((index * 257) & 0xFFFFFFFF for index in range(9000))
    flags = bytes(index % 256 for index in range(9000))
    derived = (
        b"\x10\x0a"
        + struct.pack("<9000I", *words)
        + flags
        + struct.pack("<II", 0xFFFFFFFF, 0x80000000)
        + b"\x20\x0a"
    )
    return base, derived


def test_all_seven_native_build_modules_end_at_the_next_con_ai_marker() -> None:
    observed = set()
    for sample in _samples():
        raw = bytes.fromhex(sample["raw_hex"])
        following = bytes.fromhex(sample["following_con_ai_hex"])
        reader = SaveReader(b"prefix" + raw + following, len(b"prefix"))
        saved = read_build_ai(reader)
        assert reader.data[reader.pos :] == following
        assert following[:2] == b"\x10\x0a"
        assert saved.raw == raw == b"".join(saved.sections.values())
        assert hashlib.sha256(raw).hexdigest() == sample["raw_sha256"]
        assert saved.end_offset - saved.offset == sample["con_ai_start"] - sample["build_start"]
        assert saved.base_end_offset - saved.offset == sample["base_bytes"] == 46
        assert len(saved.sections["derived"]) == sample["derived_bytes"] == 45012
        assert len(saved.raw) == sample["raw_bytes"] == 45058
        assert saved.sections["base"] == bytes.fromhex(sample["base_raw_hex"])
        assert saved.fields == {int(key): value for key, value in sample["fields"].items()}
        assert saved.fields == {0x170: 0, 0x578: 0, 0x9268: 0, 0x926C: 0}
        assert saved.strings == (b"", b"None", b"None", b"None")
        assert saved.entries == ()
        assert saved.words_5c8 == (0,) * 9000
        assert saved.bytes_9270 == b"\xfe" * 9000
        observed.add((sample["sample"], sample["player_id"], sample["con_ai_start"]))
    assert observed == {
        ("3p", 2, 8180643),
        ("3p", 3, 10067553),
        ("6p", 2, 15126071),
        ("6p", 3, 16970154),
        ("6p", 4, 18551812),
        ("6p", 5, 20395978),
        ("6p", 6, 21978133),
    }


def test_nonempty_native_entry_grammar_preserves_wire_order_and_all_bits() -> None:
    entries = (_entry(b"\xff\0First", 11), _entry(b"Second", 91))
    base, derived = _constructed(entries)
    reader = SaveReader(b"prefix" + base + derived + b"next", len(b"prefix"))
    saved = read_build_ai(reader)
    assert reader.data[reader.pos :] == b"next"
    assert saved.raw == base + derived
    assert saved.sections == {"base": base, "derived": derived}
    assert saved.fields == {0x170: 73, 0x578: 0xFF800000, 0x9268: 0xFFFFFFFF, 0x926C: 0x80000000}
    assert saved.strings == (b"name", b"\xff\0", b"", b"four")
    assert len(saved.entries) == 2
    assert len(BUILD_ENTRY_WORD_LOCALS) == 22
    for index, entry in enumerate(saved.entries):
        number = (11, 91)[index]
        assert entry.raw == entries[index]
        assert entry.end_offset - entry.offset == len(entry.raw)
        assert entry.words == tuple(0x80000000 + number + word for word in range(22))
        assert entry.extra_word == 0x7FC01234
        assert entry.flags == (2, 255, 3, 1)
    assert saved.entries[0].end_offset == saved.entries[1].offset
    assert saved.words_5c8 == tuple(index * 257 for index in range(9000))
    assert saved.bytes_9270 == bytes(index % 256 for index in range(9000))


def test_all_base_truncations_and_each_derived_section_boundary_roll_back() -> None:
    base, derived = _constructed((_entry(b"First", 7), _entry(b"Second", 8)))
    raw = base + derived
    lengths = set(range(len(base)))
    for boundary in (
        len(base),
        len(base) + 2,
        len(base) + 36002,
        len(base) + 45002,
        len(base) + 45006,
        len(raw) - 2,
        len(raw),
    ):
        lengths.update({boundary - 1, boundary, boundary + 1})
    for end in sorted(lengths):
        if end >= len(raw):
            continue
        reader = SaveReader(b"prefix" + raw[:end], len(b"prefix"))
        with pytest.raises(SaveDecodeError):
            read_build_ai(reader)
        assert reader.pos == len(b"prefix")


@pytest.mark.parametrize("length", [-1, 257, 0x7FFFFFFF])
def test_invalid_string_lengths_stop_at_the_module_boundary(length: int) -> None:
    raw = b"\x10\x0a" + struct.pack("<Ii", 0, length) + b"later plausible data"
    reader = SaveReader(raw)
    with pytest.raises(SaveDecodeError, match="string length"):
        read_build_ai(reader)
    assert reader.pos == 0


def test_full_256_byte_names_have_no_extra_wire_terminator() -> None:
    name = bytes(range(256))
    base, derived = _constructed((_entry(name, 0),), name)
    saved = read_build_ai(SaveReader(base + derived))
    assert saved.strings[0] == name
    assert saved.entries[0].name_bytes == name
    assert saved.raw == base + derived


@pytest.mark.parametrize("length", [-1, 257])
def test_invalid_later_entry_name_rolls_back_the_whole_module(length: int) -> None:
    entry = _entry(b"", 0)
    base, derived = _constructed((entry,))
    raw = bytearray(base + derived)
    entry_start = len(base) - len(entry) - 2
    struct.pack_into("<i", raw, entry_start + 2, length)
    reader = SaveReader(b"prefix" + bytes(raw), len(b"prefix"))
    with pytest.raises(SaveDecodeError, match="string length"):
        read_build_ai(reader)
    assert reader.pos == len(b"prefix")


@pytest.mark.parametrize("count", [-1, 0x7FFFFFFF])
def test_invalid_entry_counts_roll_back_before_looping(count: int) -> None:
    raw = b"\x10\x0a" + bytes(20) + b"\xa0\x0a" + struct.pack("<Ii", 0, count)
    reader = SaveReader(raw)
    with pytest.raises(SaveDecodeError, match="array count"):
        read_build_ai(reader)
    assert reader.pos == 0


def test_every_module_and_entry_marker_is_required_without_scanning() -> None:
    entry = _entry(b"", 0)
    base, derived = _constructed((entry,))
    marker_positions = [0, 4 + 2 + sum(len(_string(v)) for v in (b"name", b"\xff\0", b"", b"four"))]
    marker_positions.extend(
        (len(base) - len(entry) - 2, len(base) - 2, len(base), len(base + derived) - 2)
    )
    for at in marker_positions:
        raw = bytearray(base + derived)
        assert raw[at : at + 2] in (b"\x10\x0a", b"\xa0\x0a", b"\x20\x0a")
        raw[at] ^= 1
        reader = SaveReader(bytes(raw) + base + derived)
        with pytest.raises(SaveDecodeError, match="AI marker"):
            read_build_ai(reader)
        assert reader.pos == 0


def test_unverified_version_consumes_nothing() -> None:
    reader = SaveReader(b"prefix", len(b"prefix"), version=0x450000)
    with pytest.raises(SaveDecodeError, match="Build AI save version"):
        read_build_ai(reader)
    assert reader.pos == len(b"prefix")
