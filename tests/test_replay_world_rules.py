"""Native full rule spans, preserved bytes, optional grammar and atomic failures."""

from __future__ import annotations

import gzip
import hashlib
import json
import struct
import zipfile
from functools import lru_cache
from pathlib import Path

import pytest

from vantage.replay_binary import SaveDecodeError, SaveReader
from vantage.replay_world_rules import SavedExpertEngine, read_world_rules

FIXTURE = Path(__file__).parent / "fixtures/native_saved_world_rules_54800.zip"


@lru_cache(maxsize=1)
def _cases():
    with zipfile.ZipFile(FIXTURE) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        return tuple(
            (case, gzip.decompress(archive.read(case["fixture_member"])))
            for case in manifest["cases"]
        )


def _rebuild_expert(ai: SavedExpertEngine) -> bytes:
    """Rebuild every saved section from decoded values, including discarded locals."""
    raw = bytearray(struct.pack("<hhI", ai.string_capacity, len(ai.strings), ai.discarded_word))
    for value in ai.strings:
        raw.extend(struct.pack("<i", len(value)) + value)
    raw.extend(
        struct.pack(
            "<hhBh", ai.member28_capacity, ai.member40_capacity, ai.script_debugging, len(ai.lists)
        )
    )
    for saved_list in ai.lists:
        raw.extend(struct.pack("<IIhhI", *saved_list.header))
        for rule in saved_list.rules:
            body = bytearray(rule.descriptor + b"".join(rule.elements))
            if rule.debug_string is not None:
                body.extend(bytes([len(rule.debug_string) - 1]) + rule.debug_string)
            assert bytes(body) == rule.raw
            raw.extend(body)
    for links in ai.links:
        raw.extend(struct.pack("<hhI", links.capacity, links.count, links.discarded_word))
        for value in links.values:
            raw.extend(struct.pack("<H", value))
    return bytes(raw)


@pytest.mark.parametrize("case_index", [0, 1])
def test_full_native_spans_end_exactly_at_baseworld_and_preserve_all_sections(case_index) -> None:
    case, raw = _cases()[case_index]
    expected = case["outer_world"]
    reader = SaveReader(b"before" + raw + b"next", 6)
    saved = read_world_rules(reader)
    assert saved.offset == 6 and saved.end_offset == reader.pos == 6 + len(raw)
    assert saved.raw == raw
    assert saved.present_word == expected["flag"] == 1
    assert len(raw) == expected["end_offset"] - expected["offset"]
    assert hashlib.sha256(raw).hexdigest() == expected["raw_archive"]["raw_sha256"]
    ai, globals_ = saved.expert, saved.globals
    assert ai is not None and globals_ is not None
    assert ai.offset == 10
    assert ai.end_offset - 6 + expected["offset"] == expected["expert_end"]
    assert globals_.end_offset - 6 + expected["offset"] == case["global_end"]
    assert ai.string_capacity == expected["string_capacity"] == 10000
    assert len(ai.strings) == expected["string_count"]
    assert sum(map(len, ai.strings)) == expected["string_bytes"]
    assert [ai.member28_capacity, ai.member40_capacity] == [480, 460]
    assert ai.script_debugging == 0
    assert [list(ls.header) for ls in ai.lists] == expected["list_headers"]
    assert [len(ls.rules) for ls in ai.lists] == expected["list_rule_counts"]
    assert [sum(len(v.elements) for v in ls.rules) for ls in ai.lists] == (
        expected["list_element_counts"]
    )
    assert sum(len(ls.rules) for ls in ai.lists) == expected["rule_count"]
    assert sum(len(v.elements) for ls in ai.lists for v in ls.rules) == expected["element_count"]
    assert [hashlib.sha256(ls.raw).hexdigest() for ls in ai.lists] == expected["list_raw_sha256"]
    assert [hashlib.sha256(v.raw).hexdigest() for v in ai.links] == expected["links_raw_sha256"]
    assert [[v.capacity, v.count, len(v.values)] for v in ai.links] == expected["links"]
    assert _rebuild_expert(ai) == ai.raw
    assert hashlib.sha256(ai.raw).hexdigest() == expected["expert_sha256"]
    assert len(globals_.raw) == 8364
    assert globals_.version_bits == 0x3E0F5C29
    assert globals_.second_version_bits == 0x3E947AE1
    assert globals_.globals == {int(k, 16): v for k, v in case["globals"].items()}
    words = [globals_.version_bits, globals_.second_version_bits, *globals_.globals.values()]
    for row in globals_.player_words:
        assert len(row) == 100
        words.extend(row)
    for row in globals_.global_arrays.values():
        assert len(row) == 256
        words.extend(row)
    rebuilt = b"".join(struct.pack("<I", v) for v in words)
    assert len(globals_.player_byte_arrays) == 8
    assert all(len(row) == 256 for row in globals_.player_byte_arrays)
    rebuilt += b"".join(globals_.player_byte_arrays)
    assert rebuilt == globals_.raw
    assert hashlib.sha256(rebuilt).hexdigest() == case["global_sha256"]
    assert reader.take(4) == b"next" and reader.remaining == 0


def _synthetic(*, debug: int = 1, elements: int = 2):
    """Encode the native paths absent from the two ordinary native recordings."""
    raw = bytearray(struct.pack("<I", 0x80000001))
    marks = {"string_capacity": len(raw)}
    raw.extend(struct.pack("<hhI", 7, 3, 0xFFFFFFFF))
    for i, value in enumerate((b"", b"a\0b", b"\xff\0")):
        marks[f"string_{i}"] = len(raw)
        raw.extend(struct.pack("<i", len(value)) + value)
    marks["capacity28"] = len(raw)
    raw.extend(struct.pack("<hhB", 12, 14, debug))
    marks["list_count"] = len(raw)
    raw.extend(struct.pack("<h", 3))
    # Inactive lists retain header bits but have neither descriptors nor link payloads.
    raw.extend(struct.pack("<IIhhI", 0, 0xFFFFFFFF, -1, -1, 0xDEADBEEF))
    marks["active_header"] = len(raw)
    raw.extend(struct.pack("<IIhhI", 2, 0x80000000, 4, 2, 0xABCDEF01))

    def rule(count: int, value: int, text: bytes):
        start = len(raw)
        descriptor = bytearray(range(24))
        descriptor[0], descriptor[13] = value, count
        raw.extend(descriptor)
        for i in range(count):
            raw.extend(bytes((v + i) & 0xFF for v in range(24)))
        if debug == 1:
            raw.extend(bytes([len(text) - 1]) + text)
        return start

    marks["descriptor"] = rule(elements, 42, b"x\0y\0")
    rule(0, 43, b"\0")
    raw.extend(struct.pack("<IIhhI", 0x80000000, 19, 1, 1, 0x80000000))
    rule(1, 44, bytes(256))  # Maximum u8 debug length255 plus the saved terminator.
    raw.extend(struct.pack("<hhI", -1, -1, 0xFEEDFACE))
    marks["active_links"] = len(raw)
    raw.extend(struct.pack("<hhI2H", 4, 2, 0xFFFFFFFF, 0xFFFF, 0x8000))
    raw.extend(struct.pack("<hhIH", 1, 1, 0x80000000, 3))
    marks["global"] = len(raw)
    raw.extend(struct.pack("<II", 0x3E0F5C29, 0x7FC12345))
    for value in range(9 + 800 + 768):
        raw.extend(struct.pack("<I", 0xFFFFFFFF - value))
    raw.extend(bytes(range(256)) * 8)
    return bytes(raw), marks


@pytest.mark.parametrize("debug", [0, 1, 2, 255])
def test_optional_debug_rule_elements_links_embedded_zeros_and_raw_bits(debug: int) -> None:
    raw, _ = _synthetic(debug=debug)
    reader = SaveReader(raw + b"next")
    saved = read_world_rules(reader)
    ai, globals_ = saved.expert, saved.globals
    assert ai is not None and globals_ is not None
    assert saved.present_word == 0x80000001
    assert ai.strings == (b"", b"a\0b", b"\xff\0")
    assert ai.discarded_word == 0xFFFFFFFF
    assert ai.lists[0].header == (0, 0xFFFFFFFF, -1, -1, 0xDEADBEEF)
    assert ai.lists[0].rules == ()
    rule = ai.lists[1].rules[0]
    assert rule.descriptor[0] == 42 and rule.descriptor[13] == 2
    assert rule.elements == (bytes(range(24)), bytes(range(1, 25)))
    assert rule.debug_string == (b"x\0y\0" if debug == 1 else None)
    assert ai.lists[1].rules[1].debug_string == (b"\0" if debug == 1 else None)
    assert ai.lists[2].rules[0].debug_string == (bytes(256) if debug == 1 else None)
    assert ai.links[0].capacity == ai.links[0].count == -1 and ai.links[0].values == ()
    assert ai.links[1].values == (0xFFFF, 0x8000) and ai.links[2].values == (3,)
    assert globals_.second_version_bits == 0x7FC12345  # This word never selects wire layout.
    assert globals_.globals[0x1442A7480] == 0xFFFFFFFF
    assert globals_.player_byte_arrays == (bytes(range(256)),) * 8
    assert _rebuild_expert(ai) == ai.raw
    assert saved.raw == raw
    assert reader.take(4) == b"next" and reader.remaining == 0


def test_maximum_u8_element_count_uses_full_24_byte_records() -> None:
    raw, _ = _synthetic(elements=255)
    ai = read_world_rules(SaveReader(raw)).expert
    assert ai is not None
    rule = ai.lists[1].rules[0]
    assert len(rule.elements) == 255
    assert len(rule.raw) == 24 + 255 * 24 + 1 + 4
    assert rule.debug_string == b"x\0y\0"
    assert _rebuild_expert(ai) == ai.raw


def test_absent_rule_system_consumes_only_the_presence_word() -> None:
    reader = SaveReader(b"before" + bytes(4) + b"next", 6)
    saved = read_world_rules(reader)
    assert saved.offset == 6 and saved.end_offset == reader.pos == 10
    assert saved.present_word == 0 and saved.expert is None and saved.globals is None
    assert saved.raw == bytes(4) and reader.take(4) == b"next"


def test_empty_expert_keeps_capacities_without_reading_allocated_buffer_bytes() -> None:
    # Native capacities bound allocations, not wire payloads. Used counts0
    # consume neither strings/descriptors/links nor allocation-sized padding.
    raw = struct.pack("<IhhIhhBh", 1, 32767, 0, 0x80000000, 32767, 32767, 0, 0)
    raw += struct.pack("<II", 0x3E0F5C29, 0x3E947AE1) + bytes(8364 - 8)
    reader = SaveReader(raw + b"next")
    saved = read_world_rules(reader)
    ai = saved.expert
    assert ai is not None and saved.globals is not None
    assert (ai.string_capacity, ai.member28_capacity, ai.member40_capacity) == (32767,) * 3
    assert ai.strings == ai.lists == ai.links == ()
    assert len(ai.raw) == 15 and _rebuild_expert(ai) == ai.raw
    assert saved.raw == raw and reader.take(4) == b"next"


@pytest.mark.parametrize("version", [0, 0x444CCD, 0x44E665, 0x44E667, 0xFFFFFFFF])
def test_unsupported_save_versions_restore_the_entire_cursor(version: int) -> None:
    reader = SaveReader(b"before" + bytes(4), 6, version=version)
    with pytest.raises(SaveDecodeError, match="unsupported outer World"):
        read_world_rules(reader)
    assert reader.pos == 6


@pytest.mark.parametrize("bits", [0, 0x3E0F5C28, 0x3E0F5C2A, 0x7FC12345])
def test_unknown_nested_layout_restores_cursor_before_the_outer_flag(bits: int) -> None:
    raw, marks = _synthetic()
    raw = bytearray(raw)
    struct.pack_into("<I", raw, marks["global"], bits)
    reader = SaveReader(b"before" + raw, 6)
    with pytest.raises(SaveDecodeError, match="unsupported nested rule"):
        read_world_rules(reader)
    assert reader.pos == 6


@pytest.mark.parametrize(
    ("key", "delta", "fmt", "value"),
    [
        ("string_capacity", 0, "h", -1),
        ("string_capacity", 2, "h", -1),
        ("string_capacity", 2, "h", 32767),
        ("string_0", 0, "i", -1),
        ("string_1", 0, "i", 0x7FFFFFFF),
        ("capacity28", 0, "h", -1),
        ("capacity28", 2, "h", -1),
        ("list_count", 0, "h", -1),
        ("list_count", 0, "h", 32767),
        ("active_header", 8, "h", -1),
        ("active_header", 8, "h", 1),
        ("active_header", 10, "h", -1),
        ("active_header", 10, "h", 32767),
        ("active_links", 0, "h", -1),
        ("active_links", 0, "h", 1),
        ("active_links", 2, "h", -1),
        ("active_links", 2, "h", 32767),
    ],
)
def test_invalid_counts_capacities_and_lengths_restore_cursor(key, delta, fmt, value) -> None:
    raw, marks = _synthetic()
    raw = bytearray(raw)
    struct.pack_into("<" + fmt, raw, marks[key] + delta, value)
    reader = SaveReader(b"before" + raw, 6)
    with pytest.raises(SaveDecodeError):
        read_world_rules(reader)
    assert reader.pos == 6


def test_truncations_inside_each_section_restore_outer_cursor() -> None:
    raw, marks = _synthetic()
    cuts = {0, 1, 3, len(raw) - 1, len(raw) - 2049}
    for at in marks.values():
        cuts.update((at, at + 1, at + 2, at + 3))
    # Exercise partial fixed arrays after a complete variable ExpertEngine.
    cuts.update(marks["global"] + x for x in (7, 43, 3243, 4267, 5291, 6315))
    for end in sorted(cuts):
        reader = SaveReader(b"before" + raw[:end], 6)
        with pytest.raises(SaveDecodeError):
            read_world_rules(reader)
        assert reader.pos == 6
