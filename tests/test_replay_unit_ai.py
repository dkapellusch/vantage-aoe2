"""Native UnitAI layouts, independent record boundaries, and bounded failures."""

from __future__ import annotations

import gzip
import json
import struct
from pathlib import Path

import pytest

from vantage.replay_binary import SaveDecodeError, SaveReader
from vantage.replay_unit_ai import UnsupportedSavedUnitAI, read_unit_ai

FIXTURE = Path(__file__).parent / "fixtures" / "native_saved_unit_ai_54800.json.gz"


def _samples():
    return json.loads(gzip.decompress(FIXTURE.read_bytes()))["samples"]


def test_native_ai_spans_with_complete_unit_boundary_evidence() -> None:
    total = next_prefixes = terminators = specialized = 0
    for sample in _samples():
        for case in sample["cases"]:
            raw = bytes.fromhex(case["raw_hex"])
            reader = SaveReader(b"prefix" + raw + b"following record", 6)
            ai = read_unit_ai(reader, case["ai_type"])
            assert ai.raw == raw
            assert ai.offset == 6
            assert ai.end_offset == reader.pos == 6 + len(raw)
            assert len(raw) == case["end_offset"] - case["offset"]
            assert ai.fields == {int(key): value for key, value in case["fields"].items()}
            assert ai.path_flag == 0 and ai.path is None
            assert ai.spawn_flag == 1 and len(ai.spawn_data or b"") == 14
            assert (ai.records_52, ai.records_24, ai.ids) == ((), (), ())
            assert (ai.records_44, ai.pairs, ai.variant_records_52) == ((), (), ())
            if case["next_capture_prefix_matches_at_computed_end"]:
                next_prefixes += 1
            else:
                assert case["id"] == 6940
                assert bytes.fromhex(case["next_bytes"])[:2] == b"\x00\x0b"
                terminators += 1
            specialized += ai.ai_type == 4
            total += 1
    assert (total, next_prefixes, terminators, specialized) == (229, 228, 1, 18)


def test_every_truncation_of_native_derived_ai_rolls_back() -> None:
    case = next(c for c in _samples()[0]["cases"] if c["ai_type"] == 4)
    raw = bytes.fromhex(case["raw_hex"])
    for length in range(len(raw)):
        reader = SaveReader(b"prefix" + raw[:length], 6)
        with pytest.raises(SaveDecodeError):
            read_unit_ai(reader, 4)
        assert reader.pos == 6


def _payload(ai_type: int = 2, *, rich: bool = False, path_flag: int = 0):
    """Encode the native read contract with distinctive words and list bodies.

    The expected member order is specified separately in the assertions. This
    exercises branches absent from the initial-world native fixture.
    """
    raw = bytearray()
    marks = {}

    def word(value: int) -> None:
        raw.extend(struct.pack("<I", value))

    def records(name: str, width: int) -> None:
        marks[name] = len(raw)
        word(1 if rich else 0)
        if rich:
            raw.extend(bytes(range(width)))

    for value in range(1, 28):
        word(value)
    records("records_52", 52)
    records("records_24", 24)
    marks["ids"] = len(raw)
    word(2 if rich else 0)
    if rich:
        word(0xFFFFFFFF)
        word(17)
    raw.extend(b"\x80\x81")
    for value in (0x82, 0x83, 0x84):
        word(value)
    raw.append(0x85)
    word(0x86)
    word(path_flag)
    if path_flag == 1:
        marks["path_start"] = len(raw)
        word(0x87)
        marks["path_points"] = len(raw)
        word(1 if rich else 0)
        if rich:
            for value in (0x7FC12345, 0x80000000, 0xFFFFFFFF):
                word(value)
        for value in (0x88, 0x89, 0x8A, 0x8B):
            word(value)
        marks["path_references"] = len(raw)
        word(2 if rich else 0)
        if rich:
            word(0x8C)
            word(0x8D)
        marks["path_end"] = len(raw)
    word(0x90)
    records("records_44", 44)
    word(0x91)
    word(0x92)
    marks["pairs"] = len(raw)
    word(1 if rich else 0)
    if rich:
        word(0x93)
        word(0x94)
    word(0x95)
    raw.append(0x96)
    word(0x97)
    raw.append(0x98)
    # Any nonzero flag has a payload in the native reader; preserve the byte.
    raw.append(0xFF if rich else 0)
    if rich:
        raw.extend(bytes(range(14)))
    if ai_type == 4:
        for value in (0x99, 0x9A, 0x9B):
            word(value)
        raw.append(0x9C)
    elif ai_type in (15, 17):
        records("variant_records_52", 52)
    return bytes(raw), marks


@pytest.mark.parametrize("ai_type", range(1, 20))
def test_verified_factory_types_and_empty_minimum_lengths(ai_type: int) -> None:
    raw, _ = _payload(ai_type)
    ai = read_unit_ai(SaveReader(raw), ai_type)
    assert ai.ai_type == ai_type and ai.raw == raw
    assert len(raw) == 174 + (13 if ai_type == 4 else 4 if ai_type in (15, 17) else 0)
    assert ai.fields[0x68] == 11
    assert ai.fields[0x64] == 12
    assert ai.fields[0x170] == 17
    assert ai.fields[0x16C] == 18
    assert ai.fields[0x60] == 22
    assert ai.fields[0x194] == 23
    assert ai.fields[0x184] == 24
    assert ai.fields[0x190] == 27
    assert ai.fields[0x1B0] == 0x80
    assert ai.fields[0x1C4] == 0x86
    assert ai.fields[0x1D0] == 0x90
    assert ai.fields[0xBC] == 0x91
    assert ai.fields[0x180] == 0x97
    assert ai.fields[0x1DE] == 0x98
    assert ai.spawn_data is None


@pytest.mark.parametrize("ai_type", (2, 4, 15, 17))
def test_nonempty_arrays_saved_path_and_derived_payloads(ai_type: int) -> None:
    raw, marks = _payload(ai_type, rich=True, path_flag=1)
    reader = SaveReader(raw + b"next")
    ai = read_unit_ai(reader, ai_type)
    assert reader.pos == len(raw)
    assert ai.raw == raw
    assert ai.records_52 == (bytes(range(52)),)
    assert ai.records_24 == (bytes(range(24)),)
    assert ai.ids == (0xFFFFFFFF, 17)
    assert ai.records_44 == (bytes(range(44)),)
    assert ai.pairs == ((0x93, 0x94),)
    assert ai.spawn_flag == 0xFF and ai.spawn_data == bytes(range(14))
    assert ai.path_flag == 1 and ai.path is not None
    assert ai.path.fields == {0: 0x87, 4: 0x88, 8: 0x89, 0xC: 0x8A, 0x10: 0x8B}
    assert ai.path.points == ((0x7FC12345, 0x80000000, 0xFFFFFFFF),)
    assert ai.path.reference_words == (0x8C, 0x8D)
    assert ai.path.raw == raw[marks["path_start"] : marks["path_end"]]
    if ai_type == 4:
        assert [ai.fields[offset] for offset in (0x1F8, 0x1FC, 0x200, 0x204)] == [
            0x99,
            0x9A,
            0x9B,
            0x9C,
        ]
    assert ai.variant_records_52 == ((bytes(range(52)),) if ai_type in (15, 17) else ())


def test_only_path_flag_one_introduces_a_path() -> None:
    raw, _ = _payload(path_flag=2)
    ai = read_unit_ai(SaveReader(raw), 2)
    assert len(ai.raw) == 174
    assert ai.path_flag == 2 and ai.path is None


@pytest.mark.parametrize("bad_count", (-1, 0x7FFFFFFF))
def test_all_counted_sections_reject_invalid_lengths_transactionally(bad_count: int) -> None:
    raw, marks = _payload(15, rich=True, path_flag=1)
    for name in (
        "records_52",
        "records_24",
        "ids",
        "records_44",
        "pairs",
        "variant_records_52",
        "path_points",
        "path_references",
    ):
        damaged = bytearray(raw)
        struct.pack_into("<i", damaged, marks[name], bad_count)
        reader = SaveReader(b"prefix" + damaged, 6)
        with pytest.raises(SaveDecodeError, match="array count"):
            read_unit_ai(reader, 15)
        assert reader.pos == 6


def test_every_truncation_in_dynamic_branches_rolls_back() -> None:
    raw, _ = _payload(17, rich=True, path_flag=1)
    for length in range(len(raw)):
        reader = SaveReader(b"prefix" + raw[:length], 6)
        with pytest.raises(SaveDecodeError):
            read_unit_ai(reader, 17)
        assert reader.pos == 6


@pytest.mark.parametrize("ai_type", (-1, 0, 20, 999))
def test_unknown_factory_type_stops_at_boundary(ai_type: int) -> None:
    raw, _ = _payload()
    reader = SaveReader(b"prefix" + raw, 6)
    with pytest.raises(UnsupportedSavedUnitAI, match="type"):
        read_unit_ai(reader, ai_type)
    assert reader.pos == 6


def test_unverified_version_stops_at_boundary() -> None:
    raw, _ = _payload()
    reader = SaveReader(b"prefix" + raw, 6, version=0x450000)
    with pytest.raises(UnsupportedSavedUnitAI, match="version"):
        read_unit_ai(reader, 2)
    assert reader.pos == 6
