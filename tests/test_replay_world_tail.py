"""Native tail boundaries, counted branches and whole-record failure semantics."""

from __future__ import annotations

import gzip
import hashlib
import json
import struct
from pathlib import Path

import pytest

from vantage.replay_binary import SaveDecodeError, SaveReader
from vantage.replay_world_tail import (
    read_base_world_tail,
    read_outer_world_tail,
    read_world_tail,
)


def _w(*values: int) -> bytes:
    return struct.pack(f"<{len(values)}I", *values)


def _s(value: bytes) -> bytes:
    return _w(len(value)) + value


def _de(value: bytes) -> bytes:
    return struct.pack("<HH", 0x0A60, len(value)) + value


def _q(value: int) -> bytes:
    return struct.pack("<Q", value)


def _record():
    data = bytearray()
    positions = {}

    def add(name: str, raw: bytes) -> None:
        positions[name] = len(data)
        data.extend(raw)

    add("base_start", _w(0xFFFFFFFF, 0x7FC01234))
    for i in range(9):
        add(f"slot{i}", _w(i, 0x80000000 + i) + _s(b"p\0" + bytes([i])))
    add("player_flags", _w(*range(9)))
    add("base_values", _w(4, 0x7FA01234, 2, 3))
    add("words238", _w(2, 71, 0xFFFFFFFF))
    add("command_cache", struct.pack("<HI", 2, 0x87654321) + _w(125, 0xFFFFFFFF))
    for i in range(9):
        add(f"selection{i}", struct.pack("<H", i % 3) + _w(*range(i % 3)))
    add("paths", _w(1, 0xFFFFFFFF, 2, 1, 2, 3, 4, 5, 6, 11, 12, 13, 14, 2, 100, 200))
    add("groups", _w(0, 1))
    add("color", _de(b"Spring\0x"))
    add("base_flags", b"\xfe" + _w(2, 4, 5, 3, 6, 7, 8, 9, 10, 0x7FC01234))
    add("outer_start", bytes(range(129)))
    add("trigger_version", struct.pack("<d", 5.0))
    add("trigger_count", b"\xfe" + _w(1))
    # 1416430b0 fields, in exact wire order rather than member order.
    add(
        "trigger_body",
        _w(1)
        + b"\x02\x03"
        + _w(4)
        + b"\x05"
        + _w(6)
        + b"\x07"
        + _w(8)
        + b"\x09\x0a"
        + _w(11)
        + b"\x0c",
    )
    add("trigger_string", _s(b"description\0x") + _s(b"\0") + _s(b""))
    add("effect_count", _w(2))
    add(
        "effect1",
        _w(104, 5, 0x7FC01234, 2, 3, 4, 2)
        + _s(b"text\0x")
        + _s(b"sound")
        + _w(321, 0xFFFFFFFF)
        + _s(b"extra1")
        + _s(b"extra\0two"),
    )
    add("effect2", _w(1, 0) + _s(b"") + _s(b"") + _s(b"") + _s(b""))
    add("effect_order", _w(1, 0))
    add(
        "conditions", _w(2, 71, 2, 0x7FA01234, 0xFFFFFFFF) + _s(b"condition\0") + _w(5, 0) + _s(b"")
    )
    add("condition_order", _w(1, 0))
    add("trigger_order", _w(0))
    add("trigger256", _w(*range(256)))
    add("trigger_words", _w(2, 51, 52))
    add("trigger_strings", _w(2, 7) + _s(b"first\0") + _w(7) + _s(b"second"))
    add("trigger_fields", _w(61, 62) + b"\x80")
    add("pairs35", _q(2) + _w(17) + b"\x80" + _w(17) + b"\xff")
    add("pairs40", _q(1) + _w(88) + b"\x81")
    add("records41", _q(2) + _w(9) + _q(2) + _w(*range(12)) + _w(10) + _q(0))
    add("trigger_end", b"\xfc")
    add("xs1_flag", b"\0")
    add("strings64", _q(2) + _de(b"a\0b") + _de(b""))
    add("xs2_flag", b"\0")
    add("teams", bytes(range(8)))
    add("game_values", _w(1, 2, 3, 0xFFFFFFFF) + b"\x80\x01\x00\xfe")
    add("legacy_fields", _w(13, 14))
    add("strings32", _w(2) + _s(b"") + _s(b"legacy\0x"))
    add("world85c", _w(0x7FC01234) + b"\x81")
    add(
        "message",
        b"\x02"
        + _w(25, 26)
        + b"\x80"
        + _w(0xFFFFFFFF)
        + b"\x81\xfe"
        + _s(b"message\0x")
        + b"\0" * 9,
    )
    add("words938", _w(2, 71, 0xFFFFFFFF))
    add("records", _w(1, 1, 2, 0x7FC01234, 0xFFFFFFFF) + b"\x81" + _w(6))
    add("world980", _w(123))
    add(
        "terrain",
        b"\x02" + _w(2, 700) + _q(4) + b"a\0bc" + _w(0xFFFFFFFF, 701) + _q(0) + _w(0x7FA01234),
    )
    return bytes(data), positions


@pytest.mark.parametrize("sample", ["3p", "6p"])
def test_real_tails_end_at_inflated_eof_using_full_xs_grammar(sample: str) -> None:
    path = Path(__file__).parent / "fixtures/native_saved_world_tails_54800.json.gz"
    fixture = json.loads(gzip.decompress(path.read_bytes()))
    case = next(c for c in fixture["cases"] if c["sample"] == sample)
    raw = bytes.fromhex(fixture["bodies"][case["body_sha256"]])
    reader = SaveReader(b"before" + raw + b"following", 6)
    saved = read_world_tail(reader)
    base, outer = saved.base, saved.outer
    assert saved.raw == raw == base.raw + outer.raw
    assert outer.raw == b"".join(outer.sections.values())
    assert saved.end_offset == reader.pos == 6 + len(raw)
    assert reader.data[reader.pos :] == b"following"
    assert hashlib.sha256(raw).hexdigest() == case["body_sha256"]
    assert len(raw) == case["end_offset"] - case["offset"]
    assert case["end_offset"] == case["inflated_bytes"]
    assert len(base.raw) == case["base_end"] - case["offset"]
    assert hashlib.sha256(base.raw).hexdigest() == case["base_sha256"]
    assert [p.name_bytes.hex() for p in base.slots] == case["slot_names"]
    assert base.slots[0].name_bytes == b"Gaia\0"
    assert base.saved_player_count == case["saved_player_count"]
    assert base.group_header == (0, 1) and base.paths == ()
    assert base.color_correction.hex() == case["color"]
    assert outer.triggers.version_bits == 0x4014000000000000
    assert outer.triggers.triggers == ()
    assert len(outer.triggers.raw) == 1079
    assert outer.xs_flag1 == 1 and outer.xs1 is not None
    assert len(outer.xs1.raw) == 351061
    assert hashlib.sha256(outer.xs1.raw).hexdigest() == case["xs_sha256"]
    # This is a parsed XS module, with its full saved data, not a blob skip.
    assert outer.xs1.end_offset - outer.xs1.offset == 351061
    assert any(slot is not None and slot.functions and slot.raw for slot in outer.xs1.data_slots)
    assert outer.xs_flag2 == 0 and outer.xs2 is None
    assert outer.strings64 == ()
    assert outer.strings32 == tuple(bytes.fromhex(v) for v in case["strings32"])
    assert outer.player_teams == tuple(case["teams"])
    assert outer.terrain_present == 0 and outer.terrain_effects is None
    for name, expected in case["sections"].items():
        actual = outer.sections[name]
        assert len(actual) == expected["bytes"]
        assert hashlib.sha256(actual).hexdigest() == expected["sha256"]


def test_nonempty_native_branches_preserve_order_raw_bits_and_embedded_zeros() -> None:
    raw, pos = _record()
    r = SaveReader(b"prefix" + raw + b"following", 6)
    saved = read_world_tail(r)
    assert saved.raw == raw and r.data[r.pos :] == b"following"
    base, outer = saved.base, saved.outer
    assert saved.raw == base.raw + outer.raw
    assert outer.raw == b"".join(outer.sections.values())
    assert base.slots[8].name_bytes == b"p\0\x08" and base.slots[8].humanity == 0x80000008
    assert base.fields[0x224] == 0x7FA01234 and base.fields[0xC] == 0x7FC01234
    assert base.command_cache.command_units == (125, 0xFFFFFFFF)
    assert base.command_cache.member118 == 0x87654321
    assert base.command_cache.selected_units == ((), (0,), (0, 1)) * 3
    assert base.paths[0].points == ((1, 2, 3), (4, 5, 6))
    assert base.paths[0].reference_words == (100, 200)
    assert base.color_correction == b"Spring\0x" and base.global_flag == 0xFE
    assert base.trigger_ids == (4, 5) and base.values_at270 == (6, 7, 8)
    assert base.color_words == (9, 10, 0x7FC01234)
    assert base.end_offset == pos["outer_start"] + 6
    trigger = outer.triggers.triggers[0]
    assert trigger.fields == {
        0: 1,
        4: 2,
        0xB5: 3,
        0x28: 4,
        5: 5,
        8: 6,
        0x88: 7,
        0xA8: 8,
        0xAC: 9,
        0xAD: 10,
        0x78: 11,
        0xAE: 12,
    }
    assert trigger.strings == (b"description\0x", b"\0", b"")
    effect1, effect2 = trigger.effects
    assert effect1.words == (0x7FC01234, 2, 3, 4, 2)
    assert effect1.text == b"text\0x" and effect1.sound == b"sound"
    assert effect1.selected_units == (321, 0xFFFFFFFF)
    assert effect1.extra_strings == (b"extra1", b"extra\0two")
    assert effect2.words == () and effect2.selected_units == ()
    assert trigger.effect_order == trigger.condition_order == (1, 0)
    assert trigger.conditions[0].words == (0x7FA01234, 0xFFFFFFFF)
    assert trigger.conditions[0].text == b"condition\0"
    assert outer.triggers.words_atc == tuple(range(256))
    assert outer.triggers.indexed_strings == ((7, b"first\0"), (7, b"second"))
    assert outer.triggers.pairs_atce0 == ((17, 128), (17, 255))
    assert outer.triggers.pairs_atcf8 == ((88, 129),)
    assert outer.triggers.records_atd40 == ((9, (tuple(range(6)), tuple(range(6, 12)))), (10, ()))
    assert outer.strings64 == (b"a\0b", b"") and outer.strings32 == (b"", b"legacy\0x")
    assert outer.messages[0].present == 2 and outer.messages[0].text == b"message\0x"
    assert outer.messages[0].fields[0x20] == 0xFFFFFFFF  # Native later clamps; wire stays intact.
    assert outer.records == ((1, 2, 0x7FC01234, 0xFFFFFFFF, 129, 6),)
    assert outer.terrain_present == 2
    assert outer.terrain_effects == ((700, b"a\0bc", 0xFFFFFFFF), (701, b"", 0x7FA01234))


def test_separate_base_and_outer_apis_consume_identical_bytes() -> None:
    raw, _ = _record()
    r = SaveReader(raw)
    base = read_base_world_tail(r)
    outer = read_outer_world_tail(r)
    assert base.raw + outer.raw == raw and r.remaining == 0


def test_every_truncated_synthetic_prefix_rolls_back_the_whole_tail() -> None:
    raw, _ = _record()
    for end in range(len(raw)):
        r = SaveReader(b"before" + raw[:end], 6)
        with pytest.raises(SaveDecodeError):
            read_world_tail(r)
        assert r.pos == 6


@pytest.mark.parametrize(
    "field,delta,value,width",
    [
        ("groups", 0, 1, 4),
        ("words238", 0, 0xFFFFFFFF, 4),
        ("command_cache", 0, 0xFFFF, 2),
        ("paths", 0, 0x7FFFFFFF, 4),
        ("trigger_version", 0, 0x7FF0000000000000, 8),
        ("trigger_version", 0, 0x4012CCCCCCCCCCCD, 8),
        ("trigger_count", 1, 0x7FFFFFFF, 4),
        ("trigger_string", 0, 0x2801, 4),
        ("effect1", 4, 84, 4),
        ("effect1", 24, 0x7FFFFFFF, 4),
        ("conditions", 8, 35, 4),
        ("pairs35", 0, 0xFFFFFFFFFFFFFFFF, 8),
        ("records41", 12, 0xFFFFFFFFFFFFFFFF, 8),
        ("strings64", 0, 0xFFFFFFFFFFFFFFFF, 8),
        ("strings32", 0, 0xFFFFFFFF, 4),
        ("records", 0, 0x7FFFFFFF, 4),
        ("terrain", 1, 0xFFFFFFFF, 4),
        ("terrain", 9, 0xFFFFFFFFFFFFFFFF, 8),
    ],
)
def test_invalid_counts_and_unsupported_forms_restore_the_start(
    field: str, delta: int, value: int, width: int
) -> None:
    raw, positions = _record()
    damaged = bytearray(raw)
    at = positions[field] + delta
    damaged[at : at + width] = value.to_bytes(width, "little")
    r = SaveReader(b"before" + damaged, 6)
    with pytest.raises(SaveDecodeError):
        read_world_tail(r)
    assert r.pos == 6


@pytest.mark.parametrize("version,flag", [(0x44E665, 0), (0x44E666, 1)])
def test_unsupported_world_context_fails_without_consuming(version: int, flag: int) -> None:
    r = SaveReader(_record()[0], version=version)
    with pytest.raises(SaveDecodeError):
        read_world_tail(r, load_flag=flag)
    assert r.pos == 0


def test_outer_api_rollback_includes_failed_nested_reader() -> None:
    raw, positions = _record()
    begin = positions["outer_start"]
    r = SaveReader(raw[:-1], begin)
    with pytest.raises(SaveDecodeError):
        read_outer_world_tail(r)
    assert r.pos == begin


@pytest.mark.parametrize("slot", [1, 2])
def test_each_outer_xs_flag_delegates_to_the_complete_saved_vm(slot: int) -> None:
    fixture_path = Path(__file__).parent / "fixtures/native_saved_world_tails_54800.json.gz"
    fixture = json.loads(gzip.decompress(fixture_path.read_bytes()))
    body = bytes.fromhex(next(iter(fixture["bodies"].values())))
    captured = read_world_tail(SaveReader(body)).outer.xs1
    assert captured is not None
    raw, positions = _record()
    insert_at = positions[f"xs{slot}_flag"] + 1
    modified = bytearray(raw[:insert_at] + captured.raw + raw[insert_at:])
    modified[insert_at - 1] = 0xFF
    reader = SaveReader(modified)
    saved = read_world_tail(reader)
    actual = saved.outer.xs1 if slot == 1 else saved.outer.xs2
    assert actual is not None and actual.raw == captured.raw
    assert actual.name_bytes == b"Scenario Triggers"
    assert len(actual.data_slots[0].functions) == 59
    assert reader.remaining == 0


def test_terrain_key_serializer_limit_is_enforced_before_large_payload_read() -> None:
    raw, positions = _record()
    at = positions["terrain"] + 9
    damaged = raw[:at] + _q(0xA00001) + bytes(0xA00001) + raw[at + 8 :]
    reader = SaveReader(damaged)
    with pytest.raises(SaveDecodeError, match="native10MiB"):
        read_world_tail(reader)
    assert reader.pos == 0


@pytest.mark.parametrize("api", [read_base_world_tail, read_outer_world_tail])
def test_separate_readers_reject_unknown_versions_atomically(api) -> None:
    raw, positions = _record()
    at = 0 if api is read_base_world_tail else positions["outer_start"]
    reader = SaveReader(raw, at, version=0x44E665)
    with pytest.raises(SaveDecodeError):
        api(reader)
    assert reader.pos == at
