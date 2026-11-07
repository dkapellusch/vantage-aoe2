"""Original native InfoAI spans, state correspondence, and bounded failures."""

from __future__ import annotations

import gzip
import json
import struct
from pathlib import Path

import pytest

from vantage.replay_ai_modules import read_simple_ai
from vantage.replay_binary import SaveDecodeError, SaveReader
from vantage.replay_info_ai import read_info_ai

FIXTURE = Path(__file__).parent / "fixtures/native_saved_info_ai_54800.json.gz"


def _cases():
    return json.loads(gzip.decompress(FIXTURE.read_bytes()))["cases"]


def test_seven_native_modules_and_following_modules_at_exact_cursor() -> None:
    objects = coordinate_matches = stale_positions = 0
    for case in _cases():
        raw = bytes.fromhex(case["raw_hex"])
        following = bytes.fromhex(case["following_resource_strategy_hex"])
        reader = SaveReader(b"prefix" + raw + following, 6)
        ai = read_info_ai(reader, case["num_players_including_gaia"])
        assert ai.offset == 6 and ai.end_offset == reader.pos == 6 + len(raw)
        assert ai.raw == raw
        assert ai.fields == {
            int(k, 16): v for k, v in case["scalar_words_by_native_offset"].items()
        }
        assert {hex(k): len(v) for k, v in ai.arrays.items()} == case["array_lengths"]
        assert [ai.fields[0x10518], ai.fields[0x1051C]] == case["native_map_size"]
        assert [ai.grid.fields[8], ai.grid.fields[0xC]] == [480, 480]
        assert len(ai.grid.cells) == 480 * 480
        assert ai.technology_count == 1024
        assert len(ai.player_technology_words) == ai.num_players
        assert all(len(words) == 1024 for words in ai.player_technology_words)
        assert len(ai.search.group_ids) == 20
        assert len(ai.search.data_words) == 3
        for obj, native in zip(ai.objects, case["native_objects"], strict=True):
            assert obj.object_id == native["id"]
            assert obj.fields[0] == native["master"]
            assert obj.fields[0x10] == native["owner"]
            assert [obj.fields[4], obj.fields[8]] == native["saved_ai_xy"]
            assert len(obj.raw) == 54
            if native["saved_ai_xy"] == [int(v) for v in native["xy"]]:
                coordinate_matches += 1
            else:
                # Saved AI knowledge can precede the object's actual position.
                assert (case["sample"], case["owner"], obj.object_id) == ("6p", 5, 9700)
                assert native["saved_ai_xy"] == [108, 169]
                stale_positions += 1
            objects += 1
        resource = read_simple_ai(reader, "resource")
        strategy = read_simple_ai(reader, "strategy")
        assert resource.end_offset - 6 + case["offset"] == case["resource_end"]
        assert strategy.end_offset - 6 + case["offset"] == case["strategy_end_tactical_start"]
        assert reader.remaining == 0
    assert (objects, coordinate_matches, stale_positions) == (64, 63, 1)


def _payload(num_players: int = 2, *, rich: bool = True):
    """Encode the independently recovered native read order, including holes."""
    raw = bytearray()
    marks = {}

    def word(value: int) -> None:
        raw.extend(struct.pack("<I", value))

    def marker(value: int = 0xAA0) -> None:
        marks[f"marker_{len(marks)}"] = len(raw)
        raw.extend(struct.pack("<H", value))

    def records(name: str, width: int) -> None:
        marks[name] = len(raw)
        word(int(rich))
        if rich:
            raw.extend(bytes(range(width)))

    def ids(name: str, value: int) -> None:
        marks[name] = len(raw)
        word(int(rich))
        if rich:
            word(value)

    def search_data(seed: int) -> None:
        marker(0xA10)
        for value in range(seed, seed + 15):
            word(value)
        marker(0xA20)

    marker(0xA10)
    word(0xFFFFFFFF)
    word(0x80000000)
    records("first_words", 4)
    for player in range(num_players):
        for value in range(8):
            word(player * 8 + value)
    marker()
    for group in range(4):
        ids(f"shared_{group}", 0x100 + group)
    for value in (144, 144, 9):
        word(value)
    marks["objects"] = len(raw)
    word(int(rich))
    marker()
    if rich:
        raw.extend(
            struct.pack(
                "<IHHIIIBHIBIIIIIHI",
                123,
                448,
                47,
                10,
                20,
                0,
                2,
                45,
                55,
                7,
                18,
                19,
                20,
                21,
                22,
                12,
                0xABCDEF,
            )
        )
    marker()
    records("records_16", 16)
    marker()
    for index in range(2):
        word(77 + index)
        marks[f"block_{index}"] = len(raw)
        word(int(rich))
        for value in range(7):
            word(value + 0x20)
        if rich:
            raw.extend(bytes(range(40)))
    marker()
    records("records_40", 40)
    for index in range(6):
        ids(f"list_{index}", 0xAA + index)
    marker()
    raw.extend(b"\x45\x23\xc1\x7f" + bytes(36000 - 4))
    marker()
    word(6)
    marks["grid"] = len(raw)
    for value in (3, 2, 0, 1) if rich else (0, 0, 0, 0):
        word(value)
    raw.append(0xFF)
    if rich:
        raw.extend(bytes(range(6)))
    raw.extend(struct.pack("<QQ", 0xFFFFFFFFFFFFFFFE, 0x8000000000000000))
    word(8)
    marks["profile"] = len(raw)
    profile = b"ab\x00cd" if rich else b""
    word(len(profile))
    raw.extend(profile)
    raw.extend(bytes(range(192)))
    marker()
    for index in range(4):
        marks[f"grouped_{index}"] = len(raw)
        word(int(rich))
    for value in range(100, 104):
        word(value)
    if rich:
        for index in range(4):
            raw.extend(bytes([index]) * 29)
    marker()
    raw.extend(bytes(range(64)))
    raw.extend(bytes([0x70]) * 32)
    raw.extend(bytes([0x80]) * 32)
    word(9)
    raw.extend(bytes(range(num_players)))
    raw.extend(bytes(range(127, 127 + num_players)))
    for value in range(10, 15):
        word(value)
    marker()
    word(7)
    marks["technologies"] = len(raw)
    word(2 if rich else 0)
    if rich:
        for player in range(num_players):
            word(200 + player * 2)
            word(201 + player * 2)
    for index in range(3):
        for player in range(num_players):
            word(300 + index * 10 + player)
    word(1001)
    word(1002)
    marker()
    records("records_44", 44)
    marks["short_map"] = len(raw)
    raw.extend(struct.pack("<h", 2 if rich else 0))
    if rich:
        raw.extend(struct.pack("<hIhI", -1, 0xABC, 7, 0xFFFFFFFF))
    marks["search"] = len(raw)
    marker(0xA10)
    search_data(100)
    for index in range(2):
        marker(0xA10)
        ids(f"search_subgroup_{index}", 1000 + index)
        for value in range(200 + index * 10, 204 + index * 10):
            word(value)
        search_data(300 + index * 100)
        marker(0xA20)
    for index in range(20):
        ids(f"search_group_{index}", 2000 + index)
    word(0xDEADBEEF)
    marker(0xA20)
    for player in range(num_players):
        word(4000 + player)
    marks["triples"] = len(raw)
    word(int(rich))
    if rich:
        for value in (0xAB, 0xCD, 0xEF):
            word(value)
    marker(0xA20)
    return bytes(raw), marks


def test_dynamic_sections_preserve_native_wire_order_and_opaque_bytes() -> None:
    raw, _ = _payload()
    reader = SaveReader(b"prefix" + raw + b"next", 6)
    ai = read_info_ai(reader, 2)
    assert ai.raw == raw and reader.pos == len(raw) + 6
    assert ai.fields[0x4E0] == 0xFFFFFFFF
    assert ai.fields[0x104E4] == 0x80000000
    assert ai.fields[0x192EC] == 0xFFFFFFFFFFFFFFFE
    assert ai.fields[0x192F4] == 0x8000000000000000
    assert ai.sections["words_10648"][:4] == bytes.fromhex("4523c17f")
    assert ai.player_words == (tuple(range(8)), tuple(range(8, 16)))
    assert ai.shared_id_lists == ((0x100,), (0x101,), (0x102,), (0x103,))
    assert ai.profile_bytes == b"ab\x00cd"
    (obj,) = ai.objects
    assert obj.object_id == 123 and obj.fields[0] == 448 and obj.fields[0x10] == 2
    assert obj.fields[0x11] == 7 and obj.fields[0x12] == 45 and obj.fields[0x14] == 55
    assert obj.fields[0x30] == 12 and obj.fields[0x2C] == 0xABCDEF
    assert ai.arrays[0x19338] == ai.arrays[0x19368] == (bytes(range(40)),)
    assert ai.arrays[0x19300] == (bytes(range(16)),)
    assert ai.arrays[0x19378] == (bytes(range(40)),)
    assert ai.grouped_records == tuple((bytes([i]) * 29,) for i in range(4))
    assert ai.arrays[0x19808] == (bytes(range(44)),)
    assert ai.grid.fields == {8: 3, 0xC: 2, 0x10: 0, 0x14: 1, 0x30: 0xFF}
    assert ai.grid.cells == bytes(range(6))
    assert ai.technology_count == 2
    assert ai.player_technology_words == ((200, 201), (202, 203))
    assert ai.short_map == ((-1, 0xABC), (7, 0xFFFFFFFF))
    assert ai.search.data_words == (
        tuple(range(100, 115)),
        tuple(range(300, 315)),
        tuple(range(400, 415)),
    )
    assert ai.search.subgroup_ids == ((1000,), (1001,))
    assert ai.search.subgroup_words == (tuple(range(200, 204)), tuple(range(210, 214)))
    assert ai.search.group_ids == tuple((2000 + i,) for i in range(20))
    assert ai.search.state_word == 0xDEADBEEF
    assert ai.triples == ((0xAB, 0xCD, 0xEF),)


@pytest.mark.parametrize("num_players", (0, 1, 4, 7))
def test_empty_counted_arrays_and_context_dependent_lengths(num_players: int) -> None:
    raw, _ = _payload(num_players, rich=False)
    ai = read_info_ai(SaveReader(raw), num_players)
    assert ai.raw == raw and ai.end_offset == len(raw)
    assert len(ai.player_words) == num_players
    assert ai.objects == ai.triples == ai.short_map == ()
    assert all(
        array == ()
        for offset, array in ai.arrays.items()
        if offset not in (0xD8, 0x19760, 0x19778, 0x19790)
    )
    assert ai.grid.cells == b"" and ai.technology_count == 0
    # Native fixed fields, empty counts, markers, grid header and328-byte
    # empty AISearch total36949. Uncounted player vectors add50 bytes/player.
    assert len(ai.raw) == 36949 + num_players * 50


def test_truncations_at_all_variable_headers_and_payload_boundaries_roll_back() -> None:
    raw, marks = _payload()
    cuts = {0, 1, len(raw) - 1}
    for mark in marks.values():
        cuts.update(range(max(mark - 1, 0), min(mark + 60, len(raw))))
    # Include the middle of the two large fixed payloads.
    cuts.update((len(raw) // 2, marks["grid"] - 10000))
    for length in sorted(cuts):
        reader = SaveReader(b"prefix" + raw[:length], 6)
        with pytest.raises(SaveDecodeError):
            read_info_ai(reader, 2)
        assert reader.pos == 6


@pytest.mark.parametrize("bad_count", (-1, 0x7FFFFFFF))
def test_signed_counts_are_bounded_before_payload_iteration(bad_count: int) -> None:
    raw, marks = _payload()
    names = (
        "shared_0",
        "objects",
        "records_16",
        "block_0",
        "records_40",
        "list_5",
        "profile",
        "grouped_3",
        "records_44",
        "search_subgroup_1",
        "search_group_19",
        "triples",
    )
    for name in names:
        damaged = bytearray(raw)
        struct.pack_into("<i", damaged, marks[name], bad_count)
        reader = SaveReader(b"prefix" + damaged, 6)
        with pytest.raises(SaveDecodeError):
            read_info_ai(reader, 2)
        assert reader.pos == 6


@pytest.mark.parametrize("technology_count", (-1, 1025))
def test_native_technology_limit_is_enforced(technology_count: int) -> None:
    raw, marks = _payload()
    damaged = bytearray(raw)
    struct.pack_into("<i", damaged, marks["technologies"], technology_count)
    reader = SaveReader(damaged)
    with pytest.raises(SaveDecodeError, match="technology count"):
        read_info_ai(reader, 2)
    assert reader.pos == 0


def test_nested_markers_cannot_be_recovered_by_scanning_forward() -> None:
    raw, marks = _payload()
    damaged = bytearray(raw)
    struct.pack_into("<H", damaged, marks["search"] + 2, 0xABCD)
    reader = SaveReader(bytes(damaged) + raw)
    with pytest.raises(SaveDecodeError, match="AI marker"):
        read_info_ai(reader, 2)
    assert reader.pos == 0


@pytest.mark.parametrize("width,height", ((-1, 2), (2, -1), (0x7FFFFFFF, 0x7FFFFFFF)))
def test_invalid_or_truncated_grid_dimensions_roll_back(width: int, height: int) -> None:
    raw, marks = _payload()
    damaged = bytearray(raw)
    struct.pack_into("<ii", damaged, marks["grid"], width, height)
    reader = SaveReader(damaged)
    with pytest.raises(SaveDecodeError):
        read_info_ai(reader, 2)
    assert reader.pos == 0


@pytest.mark.parametrize("name,width", (("first_words", 4), ("short_map", 2)))
def test_unsigned_array_and_short_count_cannot_overrun(name: str, width: int) -> None:
    raw, marks = _payload()
    damaged = bytearray(raw)
    damaged[marks[name] : marks[name] + width] = bytes([0xFF]) * width
    reader = SaveReader(damaged)
    with pytest.raises(SaveDecodeError):
        read_info_ai(reader, 2)
    assert reader.pos == 0


@pytest.mark.parametrize("num_players", (-1, 3, 10000000))
def test_wrong_or_impossible_world_player_context_fails(num_players: int) -> None:
    raw, _ = _payload(2)
    reader = SaveReader(b"prefix" + raw, 6)
    with pytest.raises(SaveDecodeError):
        read_info_ai(reader, num_players)
    assert reader.pos == 6


def test_unsupported_version_rolls_back_before_reading() -> None:
    raw, _ = _payload()
    reader = SaveReader(b"prefix" + raw, 6, version=0x450000)
    with pytest.raises(SaveDecodeError, match="version"):
        read_info_ai(reader, 2)
    assert reader.pos == 6
