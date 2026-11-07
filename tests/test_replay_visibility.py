"""Native-framed visibility spans and malformed manager framing."""

from __future__ import annotations

import gzip
import json
import struct
from pathlib import Path

import pytest

from vantage.replay_binary import SaveDecodeError, SaveReader
from vantage.replay_visibility import read_visibility

FIXTURE = Path(__file__).parent / "fixtures/native_saved_visibility_54800.json.gz"


def test_native_visibility_spans_end_at_the_independent_object_list_marker() -> None:
    for case in json.loads(gzip.decompress(FIXTURE.read_bytes()))["cases"]:
        raw = bytes.fromhex(case["raw_hex"])
        reader = SaveReader(raw + b"\x0bnext section")
        obj = read_visibility(reader)
        assert obj.width == obj.height == case["width"]
        assert obj.player_id == 0
        assert len(obj.cells_i16_le) == obj.width * obj.height * 2
        assert [(s.capacity, len(s.entries)) for s in obj.slots] == [(32, 0)] * 6
        assert obj.raw == raw
        assert reader.pos == len(raw) == case["end"] - case["start"]
        assert reader.u8() == 11


def _two_slot_manager() -> bytes:
    # Native25-byte VISIBLE_RESOURCE_REC v1. Both slot headers precede entries.
    entry = struct.pack("<IIII BII", 0x56524543, 1, 71, 0x3F800000, 2, 0x40000000, 0x40400000)
    return struct.pack("<iii h iiiii", 0, 0, 3359, 1, 2, 4, 1, 32, 0) + entry


def test_all_slot_headers_precede_the_nonempty_entry_lists() -> None:
    raw = _two_slot_manager()
    reader = SaveReader(raw)
    obj = read_visibility(reader)
    assert [(s.capacity, len(s.entries)) for s in obj.slots] == [(4, 1), (32, 0)]
    assert obj.slots[0].entries[0].fields == {
        0xC: 71,
        0x10: 0x3F800000,
        0x14: 2,
        0x18: 0x40000000,
        0x1C: 0x40400000,
    }
    assert len(obj.slots[0].entries[0].raw) == 25
    assert obj.raw == raw and reader.remaining == 0


def test_every_truncated_manager_rolls_back() -> None:
    raw = _two_slot_manager()
    for length in range(len(raw)):
        reader = SaveReader(b"prefix" + raw[:length], 6)
        with pytest.raises(SaveDecodeError):
            read_visibility(reader)
        assert reader.pos == 6


@pytest.mark.parametrize(
    ("offset", "value", "message"),
    [
        (0, -1, "dimensions"),
        (14, -1, "array count"),
        (22, 5, "capacity/used"),
        (34, 0, "magic"),
        (38, 2, "version"),
    ],
)
def test_invalid_dimensions_counts_and_entry_tags_stop_without_resynchronizing(
    offset: int, value: int, message: str
) -> None:
    raw = bytearray(_two_slot_manager())
    struct.pack_into("<i", raw, offset, value)
    reader = SaveReader(bytes(raw))
    with pytest.raises(SaveDecodeError, match=message):
        read_visibility(reader)
    assert reader.pos == 0


def test_unknown_save_version_rolls_back() -> None:
    reader = SaveReader(_two_slot_manager(), version=0x450000)
    with pytest.raises(SaveDecodeError, match="save version"):
        read_visibility(reader)
    assert reader.pos == 0
