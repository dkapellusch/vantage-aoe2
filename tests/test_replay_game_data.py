"""Original small DAT envelopes; no game assets are needed by these tests."""

from __future__ import annotations

import gzip
import hashlib
import struct
import zlib
from collections.abc import Callable

import pytest

from vantage.replay_binary import SaveDecodeError, SaveReader
from vantage.replay_game_data import (
    GameDataDecodeError,
    read_game_data,
    read_game_data_civilization,
    read_game_data_civilization_prefix,
    read_game_data_colors,
    read_game_data_configuration,
    read_game_data_effects,
    read_game_data_graphics,
    read_game_data_map,
    read_game_data_master,
    read_game_data_master_common,
    read_game_data_research_catalog,
    read_game_data_sounds,
    read_game_data_tail,
    read_game_data_tasks,
    read_game_data_terrain_set,
    read_terrain_restrictions,
)


def _compress(data: bytes) -> bytes:
    encoder = zlib.compressobj(level=9, wbits=-15)
    return encoder.compress(data) + encoder.flush()


def test_original_raw_deflate_envelope_preserves_bytes_hashes_and_definition_cursor() -> None:
    data = b"VER 8.9\0" + bytes(range(256)) + b"\0raw definitions\xff"
    raw = _compress(data)
    result = read_game_data(raw)
    assert result.version_bytes == b"VER 8.9\0"
    assert result.data == data
    assert result.definition_offset == 8
    assert result.data[result.definition_offset :] == data[8:]
    assert result.compressed_size == len(raw)
    assert result.compressed_sha256 == hashlib.sha256(raw).hexdigest()
    assert result.data_sha256 == hashlib.sha256(data).hexdigest()


def test_header_only_is_a_complete_envelope_without_claiming_complete_definitions() -> None:
    result = read_game_data(_compress(b"VER 8.9\0"), max_inflated_bytes=8)
    assert result.data[result.definition_offset :] == b""


def test_every_compressed_truncation_is_rejected() -> None:
    raw = _compress(b"VER 8.9\0" + bytes(range(256)))
    for cut in range(len(raw)):
        with pytest.raises(GameDataDecodeError):
            read_game_data(raw[:cut])


@pytest.mark.parametrize("suffix", (b"\0", b"trailing", _compress(b"VER 8.9\0")))
def test_trailing_bytes_or_a_second_stream_are_rejected(suffix: bytes) -> None:
    with pytest.raises(GameDataDecodeError, match="trailing bytes"):
        read_game_data(_compress(b"VER 8.9\0") + suffix)


@pytest.mark.parametrize(
    "raw", (b"", b"not a data file", zlib.compress(b"VER 8.9\0"), gzip.compress(b"VER 8.9\0"))
)
def test_wrong_compression_and_invalid_streams_fail_explicitly(raw: bytes) -> None:
    with pytest.raises(GameDataDecodeError):
        read_game_data(raw)


@pytest.mark.parametrize("version", (b"VER 8.8\0", b"VER 8.9!", b"VER 9.0\0", bytes(8)))
def test_other_data_versions_fail_explicitly(version: bytes) -> None:
    with pytest.raises(GameDataDecodeError, match="unsupported game data version"):
        read_game_data(_compress(version + b"body"))


@pytest.mark.parametrize("size", range(8))
def test_incomplete_inflated_version_tags_are_rejected(size: int) -> None:
    with pytest.raises(GameDataDecodeError, match="truncated game data version"):
        read_game_data(_compress(b"VER 8.9\0"[:size]))


def test_inflate_limit_is_enforced_before_an_oversized_body_is_exposed() -> None:
    data = b"VER 8.9\0" + bytes(1_000_000)
    raw = _compress(data)
    with pytest.raises(GameDataDecodeError, match="exceeds inflate limit"):
        read_game_data(raw, max_inflated_bytes=4096)
    with pytest.raises(GameDataDecodeError, match="exceeds inflate limit"):
        read_game_data(raw, max_inflated_bytes=len(data) - 1)
    assert read_game_data(raw, max_inflated_bytes=len(data)).data == data


@pytest.mark.parametrize("limit", (-1, 0, 7))
def test_invalid_inflate_limit_is_a_caller_error(limit: int) -> None:
    with pytest.raises(ValueError, match="limit must allow"):
        read_game_data(_compress(b"VER 8.9\0"), max_inflated_bytes=limit)


def _terrain_record() -> bytes:
    return (
        struct.pack("<hh4I", 2, 3, 1, 0x7FA01234, 0xFFFFFFFF, 0x80000000)
        + struct.pack("<3I", 0, 0x80000000, 0x7FC01234)
        + bytes(range(48))
        + struct.pack("<3I", 1, 2, 3)
        + bytes(range(100, 148))
    )


def test_native_terrain_section_grammar_preserves_both_placeholder_arrays_and_records() -> None:
    raw = _terrain_record()
    reader = SaveReader(b"prefix" + raw + b"next", 6, version=0x43E666)
    saved = read_terrain_restrictions(reader)
    assert (saved.offset, saved.end_offset, reader.pos) == (6, 146, 146)
    assert saved.raw == raw == b"".join(saved.sections.values())
    assert saved.restriction_count == 2 and saved.terrain_count == 3
    assert saved.first_placeholders == (1, 0x7FA01234)
    assert saved.second_placeholders == (0xFFFFFFFF, 0x80000000)
    first, second = saved.restrictions
    assert first.terrain_words == (0, 0x80000000, 0x7FC01234)
    assert second.terrain_words == (1, 2, 3)
    assert first.records_16 == (bytes(range(16)), bytes(range(16, 32)), bytes(range(32, 48)))
    assert second.records_16 == (
        bytes(range(100, 116)),
        bytes(range(116, 132)),
        bytes(range(132, 148)),
    )
    for index, entry in enumerate(saved.restrictions):
        assert entry.offset == 6 + 4 + 16 + index * 60
        assert entry.end_offset - entry.offset == 60
        assert entry.raw == reader.data[entry.offset : entry.end_offset]
    assert reader.data[reader.pos :] == b"next"


@pytest.mark.parametrize("counts", ((0, 0), (2, 0), (0, 3)))
def test_native_zero_count_branch_has_neither_arrays_nor_entries(counts: tuple[int, int]) -> None:
    raw = struct.pack("<hh", *counts)
    reader = SaveReader(raw + b"next", version=0x43E666)
    saved = read_terrain_restrictions(reader)
    assert (saved.restriction_count, saved.terrain_count) == counts
    assert saved.first_placeholders == saved.second_placeholders == ()
    assert saved.restrictions == () and saved.raw == raw
    assert reader.pos == 4


def test_every_small_terrain_section_truncation_rolls_back() -> None:
    raw = _terrain_record()
    for cut in range(len(raw)):
        reader = SaveReader(b"pad" + raw[:cut], 3, version=0x43E666)
        with pytest.raises(SaveDecodeError):
            read_terrain_restrictions(reader)
        assert reader.pos == 3


@pytest.mark.parametrize("counts", ((-1, 3), (3, -1), (-1, -1), (32767, 32767), (1, 3)))
def test_invalid_terrain_counts_are_bounded_and_transactional(counts: tuple[int, int]) -> None:
    reader = SaveReader(b"pad" + struct.pack("<hh", *counts), 3, version=0x43E666)
    with pytest.raises(SaveDecodeError):
        read_terrain_restrictions(reader)
    assert reader.pos == 3


def test_terrain_data_rejects_replay_save_version_instead_of_reusing_its_layout() -> None:
    reader = SaveReader(b"pad" + _terrain_record(), 3, version=0x44E666)
    with pytest.raises(SaveDecodeError, match="terrain data version"):
        read_terrain_restrictions(reader)
    assert reader.pos == 3


def _colors() -> bytes:
    return struct.pack("<h18I", 2, *range(9), *(0xFFFFFFF0 + i for i in range(9)))


def _sound_record(names: tuple[bytes, ...] = (), *, swapped: bool = False) -> bytes:
    raw = struct.pack("<HHhIH", 0xFFFF, 0xFFFE, len(names), 0x7FC01234, 0x8000)
    for index, name in enumerate(names):
        header = (len(name), 0xA60) if swapped else (0xA60, len(name))
        raw += struct.pack("<HH", *header) + name
        raw += struct.pack("<I3H", 0xFFFFFFFF - index, 0x8000, 0xFFFF, index)
    return raw


def _sounds() -> bytes:
    return struct.pack("<h", 2) + _sound_record((b"a\0\xff", b"")) + _sound_record()


def test_color_words_use_native_destination_offsets_and_preserve_all_bits() -> None:
    raw = _colors()
    reader = SaveReader(b"pad" + raw + b"following", 3, version=0x43E666)
    saved = read_game_data_colors(reader)
    assert saved.count == 2 and saved.raw == raw
    assert (saved.offset, saved.end_offset, reader.pos) == (3, 77, 77)
    offsets = (0, 0x10, 0x14, 0x18, 0x1C, 0x20, 0x24, 0x28, 4)
    for index, entry in enumerate(saved.colors):
        assert entry.offset == 5 + index * 36 and entry.end_offset - entry.offset == 36
        assert entry.raw == reader.data[entry.offset : entry.end_offset]
        assert entry.fields == {
            offset: value + (0xFFFFFFF0 if index else 0) for value, offset in enumerate(offsets)
        }
    assert reader.data[reader.pos :] == b"following"


@pytest.mark.parametrize("swapped", (False, True))
def test_sound_headers_items_and_de_string_bytes_are_preserved(swapped: bool) -> None:
    first = _sound_record((b"a\0\xff", b""), swapped=swapped)
    second = _sound_record()
    raw = struct.pack("<h", 2) + first + second
    reader = SaveReader(b"prefix" + raw + b"following", 6, version=0x43E666)
    saved = read_game_data_sounds(reader)
    assert saved.raw == raw and saved.count == 2
    assert saved.offset == 6 and saved.end_offset == reader.pos == 6 + len(raw)
    one, two = saved.sounds
    assert one.raw == first and two.raw == second
    assert (one.id_bits, one.word16, one.item_count, one.word32, one.total_probability_bits) == (
        0xFFFF,
        0xFFFE,
        2,
        0x7FC01234,
        0x8000,
    )
    assert two.item_count == 0 and two.items == ()
    assert [item.filename_bytes for item in one.items] == [b"a\0\xff", b""]
    for index, item in enumerate(one.items):
        assert item.word32 == 0xFFFFFFFF - index
        assert item.words16 == (0x8000, 0xFFFF, index)
        assert item.raw == reader.data[item.offset : item.end_offset]
        assert len(item.raw) == 14 + len(item.filename_bytes)
    assert reader.data[reader.pos :] == b"following"


@pytest.mark.parametrize(
    "read,raw", ((read_game_data_colors, _colors()), (read_game_data_sounds, _sounds()))
)
def test_every_color_and_sound_section_truncation_rolls_back(read, raw: bytes) -> None:
    for cut in range(len(raw)):
        reader = SaveReader(b"pad" + raw[:cut], 3, version=0x43E666)
        with pytest.raises(SaveDecodeError):
            read(reader)
        assert reader.pos == 3


@pytest.mark.parametrize("read", (read_game_data_colors, read_game_data_sounds))
def test_zero_color_or_sound_count_has_no_records(read) -> None:
    reader = SaveReader(b"\0\0following", version=0x43E666)
    saved = read(reader)
    assert saved.count == 0 and saved.raw == b"\0\0" and reader.pos == 2


@pytest.mark.parametrize("read", (read_game_data_colors, read_game_data_sounds))
@pytest.mark.parametrize("count", (-1, 32767, 1))
def test_invalid_color_or_sound_count_rolls_back(read, count: int) -> None:
    reader = SaveReader(b"pad" + struct.pack("<h", count), 3, version=0x43E666)
    with pytest.raises(SaveDecodeError, match="count"):
        read(reader)
    assert reader.pos == 3


@pytest.mark.parametrize("count", (-1, 32767))
def test_invalid_sound_item_count_rolls_back_the_whole_section(count: int) -> None:
    raw = bytearray(_sounds())
    struct.pack_into("<h", raw, 6, count)
    reader = SaveReader(b"pad" + raw, 3, version=0x43E666)
    with pytest.raises(SaveDecodeError, match="sound item count"):
        read_game_data_sounds(reader)
    assert reader.pos == 3


def test_bad_de_string_in_a_later_sound_restores_the_section_start() -> None:
    raw = struct.pack("<h", 2) + _sound_record() + _sound_record((b"abc",))
    bad = bytearray(raw)
    bad[26:30] = bytes(4)
    reader = SaveReader(b"pad" + bad, 3, version=0x43E666)
    with pytest.raises(SaveDecodeError, match="DE string"):
        read_game_data_sounds(reader)
    assert reader.pos == 3


@pytest.mark.parametrize("read", (read_game_data_colors, read_game_data_sounds))
def test_color_and_sound_data_require_the_supported_dat_version(read) -> None:
    reader = SaveReader(b"pad\0\0", 3, version=0x44E666)
    with pytest.raises(SaveDecodeError, match="data version"):
        read(reader)
    assert reader.pos == 3


def _graphic_record(
    *, deltas: int = 1, rows: int = 2, flag: int = 2, swapped: bool = False
) -> bytes:
    names = (b"graphic\xff", b"path\0", b"soundset")
    strings = b"".join(
        struct.pack("<HH", len(name), 0xA60) + name
        if swapped
        else struct.pack("<HH", 0xA60, len(name)) + name
        for name in names
    )
    # Native destination order is intentionally different from memory order.
    before = struct.pack(
        "<IBBBHB5H",
        0x7FC01234,
        0xF1,
        0xF2,
        0xF3,
        0xF401,
        0xF5,
        0xF601,
        0xF701,
        0xF801,
        0xF901,
        deltas & 0xFFFF,
    )
    local_sound = struct.pack("<H", 0xFFFF)
    after = struct.pack(
        "<IBHHIIIBHBB",
        0x80000000,
        flag,
        0x8001,
        rows & 0xFFFF,
        0x7FC0ABCD,
        0x80000000,
        0xFFFFFFFF,
        0xFA,
        0xFB01,
        0xFC,
        0xFD,
    )
    assert len(before + local_sound + after) == 48
    links = b"".join(bytes(range(i, i + 16)) for i in range(max(deltas, 0)))
    sounds = b"".join(
        struct.pack("<HHI", 0x8000 + row * 3 + item, 0xFFFF - item, 0x7FC01234 + row)
        for row in range(max(rows, 0) if flag else 0)
        for item in range(3)
    )
    return strings + before + local_sound + after + links + sounds


@pytest.mark.parametrize("swapped", (False, True))
def test_graphic_presence_fields_links_and_sound_rows_preserve_wire_bits(swapped: bool) -> None:
    first = _graphic_record(swapped=swapped)
    second = _graphic_record(deltas=0, rows=-1, flag=0, swapped=swapped)
    raw = struct.pack("<h3I", 3, 2, 0, 0xFFFFFFFF) + first + second
    reader = SaveReader(b"prefix" + raw + b"following", 6, version=0x43E666)
    saved = read_game_data_graphics(reader)
    assert saved.offset == 6 and saved.end_offset == reader.pos == 6 + len(raw)
    assert saved.body_offset == 20 and saved.count == 3
    assert saved.placeholders == (2, 0, 0xFFFFFFFF)
    assert list(saved.graphics) == [0, 2]
    assert saved.raw == raw == b"".join(saved.sections.values())
    one, two = saved.graphics.values()
    assert one.raw == first and two.raw == second
    assert one.strings == (b"graphic\xff", b"path\0", b"soundset")
    assert one.sound_id_bits == 0xFFFF
    assert one.fields == {
        0x78: 0x7FC01234,
        0x7F: 0xF1,
        0x7C: 0xF2,
        0x7D: 0xF3,
        0x82: 0xF401,
        0x7E: 0xF5,
        0x84: 0xF601,
        0x86: 0xF701,
        0x88: 0xF801,
        0x8A: 0xF901,
        0x8C: 1,
        0xA0: 0x80000000,
        0x80: 2,
        8: 0x8001,
        0xA: 2,
        0xC: 0x7FC0ABCD,
        0x10: 0x80000000,
        0x14: 0xFFFFFFFF,
        0x1A: 0xFA,
        0x18: 0xFB01,
        0x1B: 0xFC,
        0x1C: 0xFD,
    }
    assert one.deltas_16 == (bytes(range(16)),)
    assert two.deltas_16 == two.sound_rows == () and two.fields[0xA] == 0xFFFF
    assert len(one.sound_rows) == 2
    for row, items in enumerate(one.sound_rows):
        assert len(items) == 3
        for index, item in enumerate(items):
            assert item.words == (0x8000 + row * 3 + index, 0xFFFF - index, 0x7FC01234 + row)
            assert item.end_offset - item.offset == 8
            assert item.raw == reader.data[item.offset : item.end_offset]
    assert reader.data[reader.pos :] == b"following"


def test_every_small_graphics_section_truncation_rolls_back() -> None:
    raw = struct.pack("<hI", 1, 1) + _graphic_record()
    for cut in range(len(raw)):
        reader = SaveReader(b"pad" + raw[:cut], 3, version=0x43E666)
        with pytest.raises(SaveDecodeError):
            read_game_data_graphics(reader)
        assert reader.pos == 3


@pytest.mark.parametrize("count", (0, 3))
def test_absent_graphics_consume_only_the_index(count: int) -> None:
    raw = struct.pack("<h", count) + bytes(count * 4)
    reader = SaveReader(raw + b"following", version=0x43E666)
    saved = read_game_data_graphics(reader)
    assert saved.raw == raw and saved.graphics == {} and reader.pos == len(raw)


@pytest.mark.parametrize("count", (-1, 32767, 1))
def test_invalid_graphics_count_rolls_back(count: int) -> None:
    reader = SaveReader(b"pad" + struct.pack("<h", count), 3, version=0x43E666)
    with pytest.raises(SaveDecodeError, match="graphic count"):
        read_game_data_graphics(reader)
    assert reader.pos == 3


@pytest.mark.parametrize("deltas,rows", ((-1, 0), (0, -1)))
def test_negative_graphic_nested_counts_roll_back(deltas: int, rows: int) -> None:
    raw = struct.pack("<hI", 1, 1) + _graphic_record(deltas=deltas, rows=rows)
    reader = SaveReader(b"pad" + raw, 3, version=0x43E666)
    with pytest.raises(SaveDecodeError, match=r"graphic (delta|sound row) count"):
        read_game_data_graphics(reader)
    assert reader.pos == 3


def test_bad_string_in_later_graphic_rolls_back_the_entire_section() -> None:
    raw = struct.pack("<h2I", 2, 1, 1) + _graphic_record() + bytes(60)
    reader = SaveReader(b"pad" + raw, 3, version=0x43E666)
    with pytest.raises(SaveDecodeError, match="DE string"):
        read_game_data_graphics(reader)
    assert reader.pos == 3


def test_graphics_require_the_exact_supported_dat_version() -> None:
    reader = SaveReader(b"pad\0\0", 3, version=0x44E666)
    with pytest.raises(SaveDecodeError, match="graphic data version"):
        read_game_data_graphics(reader)
    assert reader.pos == 3


def _terrain_set_record() -> bytes:
    def string(data: bytes) -> bytes:
        return struct.pack("<HH", 0xA60, len(data)) + data

    result = (
        struct.pack("<4BI", 0, 0x80, 2, 1, 0x7FC01234)
        + string(b"name\xff")
        + string(b"resource\0")
        + struct.pack("<7I", 0x80000000, 0x1234ABCD, 0xFFFFFFFF, 0x7FC01234, 0x80000000, 7, 8)
        + string(b"overlay")
        + bytes(range(0x80, 0x88))
        + struct.pack(
            "<HHIIHHIBB",
            0x8001,
            0xFFFF,
            0x7FC0ABCD,
            0x80000000,
            0x8002,
            0xFFFE,
            0xFFFFFFFF,
            0xF1,
            0xF2,
        )
        + bytes(range(114))
        + struct.pack("<3H", 0xFFFF, 0x8000, 3)
        + struct.pack("<30H", *range(100, 130))
        + struct.pack("<30H", *range(0x8000, 0x801E))
        + struct.pack("<30H", *(0xFFFF - i for i in range(30)))
        + bytes(range(30))
        + b"\xff\xff\x7f\x80"
    )
    assert len(result) == 412 + 5 + 9 + 7
    return result


def test_terrain_set_preserves_all_current_fields_arrays_and_ignored_bytes() -> None:
    raw = _terrain_set_record()
    reader = SaveReader(b"prefix" + raw + b"following", 6, version=0x43E666)
    saved = read_game_data_terrain_set(reader)
    assert saved.offset == 6 and saved.end_offset == reader.pos == 6 + len(raw)
    assert saved.raw == raw
    assert saved.string_bytes == (b"name\xff", b"resource\0", b"overlay")
    assert saved.ptr32_bits == 0x1234ABCD
    assert saved.tile_geometry == bytes(range(114))
    assert saved.padding == b"\x7f\x80"
    assert saved.fields == {
        0: 0,
        1: 0x80,
        2: 2,
        3: 1,
        4: 0x7FC01234,
        0x50: 0x80000000,
        0x5C: 0xFFFFFFFF,
        0x54: 0x7FC01234,
        0x58: 0x80000000,
        0x60: 7,
        0x64: 8,
        **{
            offset: value
            for offset, value in zip(range(0x68, 0x70), range(0x80, 0x88), strict=True)
        },
        0x70: 0x8001,
        0x72: 0xFFFF,
        0x74: 0x7FC0ABCD,
        0x78: 0x80000000,
        0x7C: 0x8002,
        0x7E: 0xFFFE,
        0x80: 0xFFFFFFFF,
        0x84: 0xF1,
        0x85: 0xF2,
        0xF8: 0xFFFF,
        0xFA: 0x8000,
        0xFC: 3,
        0x1EA: 0xFFFF,
    }
    assert saved.object_arrays16 == {
        0x190: tuple(range(100, 130)),
        0x118: tuple(range(0x8000, 0x801E)),
        0x154: tuple(0xFFFF - i for i in range(30)),
    }
    assert saved.object_placement == tuple(range(30))
    assert reader.data[reader.pos :] == b"following"


def test_every_small_terrain_set_truncation_rolls_back() -> None:
    raw = _terrain_set_record()
    for cut in range(len(raw)):
        reader = SaveReader(b"pad" + raw[:cut], 3, version=0x43E666)
        with pytest.raises(SaveDecodeError):
            read_game_data_terrain_set(reader)
        assert reader.pos == 3


def _data_map() -> bytes:
    header = (
        b"ignored!"
        + struct.pack("<4I", 0x12345678, 1, 0x80000000, 2)
        + bytes(range(114))
        + b"\xaa\xbb"
    )
    tail = (
        struct.pack("<6Ih", 0, 1, 0x7FC01234, 0x80000000, 4, 0xFFFFFFFF, 134)
        + struct.pack("<13H", *range(0xFFF0, 0xFFFD))
        + b"padding!"
        + b"\x80\xff\0"
        + b"derived!"
    )
    assert len(header) == 140 and len(tail) == 71
    return header + _terrain_set_record() * 200 + tail


def test_map_definitions_preserve_200_complete_terrain_sets_and_exact_tail() -> None:
    raw = _data_map()
    reader = SaveReader(b"pad" + raw + b"following", 3, version=0x43E666)
    saved = read_game_data_map(reader)
    assert saved.raw == raw == b"".join(saved.sections.values())
    assert (saved.offset, saved.end_offset, reader.pos) == (3, 3 + len(raw), 3 + len(raw))
    assert saved.ignored_prefix == b"ignored!"
    assert saved.dimension_words == (0x12345678, 1, 0x80000000, 2)
    assert saved.tile_size_bytes == bytes(range(114)) and saved.header_padding == b"\xaa\xbb"
    assert len(saved.terrain_sets) == 200
    for index, record in enumerate(saved.terrain_sets):
        assert record.offset == 3 + 140 + index * len(_terrain_set_record())
        assert record.raw == _terrain_set_record()
    assert saved.bounds_words == (0, 1, 0x7FC01234, 0x80000000, 4, 0xFFFFFFFF)
    assert saved.valid_terrain_count == 134
    assert saved.tail_words16 == tuple(range(0xFFF0, 0xFFFD))
    assert saved.tail_padding == b"padding!" and saved.tail_flags == (0x80, 0xFF, 0)
    assert saved.derived_bytes == b"derived!" and reader.data[reader.pos :] == b"following"


def test_map_header_each_tail_truncation_and_selected_record_boundaries_roll_back() -> None:
    raw = _data_map()
    cuts = set(range(140)) | set(range(len(raw) - 71, len(raw)))
    cuts.update(140 + index * len(_terrain_set_record()) for index in (0, 1, 2, 99, 199))
    for cut in sorted(cuts):
        reader = SaveReader(b"pad" + raw[:cut], 3, version=0x43E666)
        with pytest.raises(SaveDecodeError):
            read_game_data_map(reader)
        assert reader.pos == 3


def test_invalid_de_string_in_the_last_terrain_set_restores_the_map_start() -> None:
    raw = bytearray(_data_map())
    at = 140 + 199 * len(_terrain_set_record()) + 8
    raw[at : at + 4] = bytes(4)
    reader = SaveReader(b"pad" + raw, 3, version=0x43E666)
    with pytest.raises(SaveDecodeError, match="DE string"):
        read_game_data_map(reader)
    assert reader.pos == 3


@pytest.mark.parametrize("count", (-1, 201))
def test_unsupported_valid_terrain_count_rolls_back(count: int) -> None:
    raw = bytearray(_data_map())
    at = 140 + 200 * len(_terrain_set_record()) + 24
    struct.pack_into("<h", raw, at, count)
    reader = SaveReader(b"pad" + raw, 3, version=0x43E666)
    with pytest.raises(SaveDecodeError, match="valid terrain count"):
        read_game_data_map(reader)
    assert reader.pos == 3


@pytest.mark.parametrize("read", (read_game_data_map, read_game_data_terrain_set))
def test_map_and_terrain_sets_require_the_exact_dat_version(read) -> None:
    reader = SaveReader(b"pad", 3, version=0x44E666)
    with pytest.raises(SaveDecodeError, match="data version"):
        read(reader)
    assert reader.pos == 3


def _data_effects() -> bytes:
    return (
        struct.pack("<iHH", 3, 0xA60, 9)
        + b"research\xff"
        + struct.pack(
            "<hBHHHIBHHHI", 2, 1, 0xFFFF, 0x8000, 2, 0x7FC01234, 0xFF, 3, 4, 0xFFFE, 0x80000000
        )
        + struct.pack("<HHh", 0xA60, 0, 0)
        + struct.pack("<HH", 0xA60, 7)
        + b"repeat\0"
        + struct.pack("<hBHHHI", 1, 0, 1, 2, 3, 0xFFFFFFFF)
    )


def test_effect_commands_have_11_wire_bytes_and_preserve_names_ids_and_float_bits() -> None:
    raw = _data_effects()
    reader = SaveReader(b"pad" + raw + b"following", 3, version=0x43E666)
    saved = read_game_data_effects(reader)
    assert saved.raw == raw and saved.count == 3
    assert (saved.offset, saved.end_offset, reader.pos) == (3, 3 + len(raw), 3 + len(raw))
    assert [effect.name_bytes for effect in saved.effects] == [b"research\xff", b"", b"repeat\0"]
    assert [effect.command_count for effect in saved.effects] == [2, 0, 1]
    commands = [command for effect in saved.effects for command in effect.commands]
    assert [(c.kind, c.words16, c.value_bits) for c in commands] == [
        (1, (0xFFFF, 0x8000, 2), 0x7FC01234),
        (0xFF, (3, 4, 0xFFFE), 0x80000000),
        (0, (1, 2, 3), 0xFFFFFFFF),
    ]
    for effect in saved.effects:
        assert effect.raw == reader.data[effect.offset : effect.end_offset]
    for command in commands:
        assert len(command.raw) == command.end_offset - command.offset == 11
        assert command.raw == reader.data[command.offset : command.end_offset]
    assert reader.data[reader.pos :] == b"following"


def test_every_small_effect_table_truncation_rolls_back() -> None:
    raw = _data_effects()
    for cut in range(len(raw)):
        reader = SaveReader(b"pad" + raw[:cut], 3, version=0x43E666)
        with pytest.raises(SaveDecodeError):
            read_game_data_effects(reader)
        assert reader.pos == 3


@pytest.mark.parametrize("count", (-1, 2147483647, 1))
def test_invalid_effect_table_count_rolls_back(count: int) -> None:
    reader = SaveReader(b"pad" + struct.pack("<i", count), 3, version=0x43E666)
    with pytest.raises(SaveDecodeError, match="effect count"):
        read_game_data_effects(reader)
    assert reader.pos == 3


@pytest.mark.parametrize("count", (-1, 32767))
def test_invalid_effect_command_count_rolls_back(count: int) -> None:
    raw = bytearray(_data_effects())
    struct.pack_into("<h", raw, 17, count)
    reader = SaveReader(b"pad" + raw, 3, version=0x43E666)
    with pytest.raises(SaveDecodeError, match="effect command count"):
        read_game_data_effects(reader)
    assert reader.pos == 3


def test_bad_later_effect_name_rolls_back_the_whole_table() -> None:
    raw = bytearray(_data_effects())
    raw[41:45] = bytes(4)
    reader = SaveReader(b"pad" + raw, 3, version=0x43E666)
    with pytest.raises(SaveDecodeError, match="DE string"):
        read_game_data_effects(reader)
    assert reader.pos == 3


def test_zero_effect_table_consumes_only_the_count() -> None:
    reader = SaveReader(b"\0\0\0\0following", version=0x43E666)
    saved = read_game_data_effects(reader)
    assert saved.effects == () and saved.raw == bytes(4) and reader.pos == 4


def test_effects_require_the_exact_supported_data_version() -> None:
    reader = SaveReader(b"pad\0\0\0\0", 3, version=0x44E666)
    with pytest.raises(SaveDecodeError, match="effect data version"):
        read_game_data_effects(reader)
    assert reader.pos == 3


def _data_tasks() -> bytes:
    first = struct.pack("<H", 0x1234) + bytes(range(67))
    second = struct.pack("<H", 0xFFFF) + bytes(range(100, 167))
    return struct.pack("<iBBh", 3, 0, 2, 2) + first + second + struct.pack("<Bh", 255, 0)


def test_task_presence_is_interleaved_and_shared_task_records_remain_unchanged() -> None:
    raw = _data_tasks()
    reader = SaveReader(b"pad" + raw + b"following", 3, version=0x43E666)
    saved = read_game_data_tasks(reader)
    assert saved.raw == raw and saved.count == 3
    assert saved.presence == (0, 2, 255) and list(saved.task_lists) == [1, 2]
    assert (saved.offset, saved.end_offset, reader.pos) == (3, 3 + len(raw), 3 + len(raw))
    one, two = saved.task_lists.values()
    assert one.task_count == 2 and two.task_count == 0 and two.tasks == ()
    assert [task.type_id for task in one.tasks] == [0x1234, 0xFFFF]
    for table in saved.task_lists.values():
        assert table.raw == reader.data[table.offset : table.end_offset]
    for task in one.tasks:
        assert len(task.raw) == task.end_offset - task.offset == 69
        assert task.raw == reader.data[task.offset : task.end_offset]
        assert task.fields[0xA] == int.from_bytes(task.raw[2:4], "little", signed=True)
        assert task.fields[0x38] == int.from_bytes(task.raw[-2:], "little", signed=True)
        assert len(task.sprite_ids) == 4 and len(task.sound_numbers) == 2
    assert reader.data[reader.pos :] == b"following"


def test_every_small_task_table_truncation_rolls_back() -> None:
    raw = _data_tasks()
    for cut in range(len(raw)):
        reader = SaveReader(b"pad" + raw[:cut], 3, version=0x43E666)
        with pytest.raises(SaveDecodeError):
            read_game_data_tasks(reader)
        assert reader.pos == 3


@pytest.mark.parametrize("count", (-1, 2147483647, 1))
def test_invalid_task_table_count_rolls_back(count: int) -> None:
    reader = SaveReader(b"pad" + struct.pack("<i", count), 3, version=0x43E666)
    with pytest.raises(SaveDecodeError, match="task table count"):
        read_game_data_tasks(reader)
    assert reader.pos == 3


@pytest.mark.parametrize("count", (-1, 32767))
def test_invalid_nested_task_list_count_rolls_back(count: int) -> None:
    raw = bytearray(_data_tasks())
    struct.pack_into("<h", raw, 6, count)
    reader = SaveReader(b"pad" + raw, 3, version=0x43E666)
    with pytest.raises(SaveDecodeError, match="task list count"):
        read_game_data_tasks(reader)
    assert reader.pos == 3


def test_truncated_task_in_a_later_list_restores_the_table_start() -> None:
    raw = bytearray(_data_tasks())
    struct.pack_into("<h", raw, 147, 1)
    reader = SaveReader(b"pad" + raw, 3, version=0x43E666)
    with pytest.raises(SaveDecodeError, match="task list count"):
        read_game_data_tasks(reader)
    assert reader.pos == 3


def test_zero_task_table_consumes_only_the_count() -> None:
    reader = SaveReader(b"\0\0\0\0following", version=0x43E666)
    saved = read_game_data_tasks(reader)
    assert saved.task_lists == {} and saved.presence == () and reader.pos == 4


def test_task_table_requires_exact_dat_version_even_when_primitive_supports_save_version() -> None:
    reader = SaveReader(b"pad\0\0\0\0", 3, version=0x44E666)
    with pytest.raises(SaveDecodeError, match="task data version"):
        read_game_data_tasks(reader)
    assert reader.pos == 3


def _de(value: bytes) -> bytes:
    return struct.pack("<HH", 0xA60, len(value)) + value


def _data_civilization_prefix(type_id: int = 1) -> bytes:
    return (
        bytes([type_id])
        + _de(b"civilization\xff\0")
        + struct.pack("<hHH", 3, 0xFFFF, 0x1234)
        + struct.pack("<III", 0x7FC01234, 0x80000000, 0xFFFFFFFF)
        + struct.pack("<BhIIII", 255, 4, 0, 1, 0xFFFFFFFF, 7)
    )


@pytest.mark.parametrize("type_id", (0, 1))
def test_civilization_prefix_preserves_resources_and_stops_before_master_bodies(
    type_id: int,
) -> None:
    raw = _data_civilization_prefix(type_id)
    reader = SaveReader(b"pad" + raw + b"master bodies", 3, version=0x43E666)
    saved = read_game_data_civilization_prefix(reader)
    assert (saved.offset, saved.end_offset, reader.pos) == (3, 3 + len(raw), 3 + len(raw))
    assert saved.raw == raw and saved.type_id == type_id
    assert saved.name_bytes == b"civilization\xff\0"
    assert saved.resource_count == 3
    assert saved.resource_words == (0x7FC01234, 0x80000000, 0xFFFFFFFF)
    assert saved.fields16 == {0x42: 0xFFFF, 0x44: 0x1234}
    assert saved.field40_bits == 255 and saved.master_count == 4
    assert saved.placeholders == (0, 1, 0xFFFFFFFF, 7)
    assert saved.sections["resource_words"] == struct.pack("<III", *saved.resource_words)
    assert saved.sections["header"] + saved.sections["master_presence"] == raw
    assert reader.data[reader.pos :] == b"master bodies"


def test_every_small_civilization_prefix_truncation_rolls_back() -> None:
    raw = _data_civilization_prefix()
    for cut in range(len(raw)):
        reader = SaveReader(b"pad" + raw[:cut], 3, version=0x43E666)
        with pytest.raises(SaveDecodeError):
            read_game_data_civilization_prefix(reader)
        assert reader.pos == 3


@pytest.mark.parametrize("count", (-1, 32767))
@pytest.mark.parametrize("field", ("resource", "master"))
def test_invalid_civilization_prefix_count_rolls_back(count: int, field: str) -> None:
    raw = bytearray(_data_civilization_prefix())
    at = 1 + len(_de(b"civilization\xff\0")) if field == "resource" else len(raw) - 18
    struct.pack_into("<h", raw, at, count)
    reader = SaveReader(b"pad" + raw, 3, version=0x43E666)
    with pytest.raises(SaveDecodeError, match=f"{field} count"):
        read_game_data_civilization_prefix(reader)
    assert reader.pos == 3


@pytest.mark.parametrize("type_id", (2, 255))
def test_unsupported_civilization_types_roll_back_before_their_unknown_bodies(type_id: int) -> None:
    reader = SaveReader(b"pad" + _data_civilization_prefix(type_id), 3, version=0x43E666)
    with pytest.raises(SaveDecodeError, match="civilization type"):
        read_game_data_civilization_prefix(reader)
    assert reader.pos == 3


def test_empty_civilization_prefix_has_no_resource_or_master_arrays() -> None:
    raw = b"\0" + _de(b"") + struct.pack("<hHHBh", 0, 3, 4, 5, 0)
    reader = SaveReader(raw + b"following", version=0x43E666)
    saved = read_game_data_civilization_prefix(reader)
    assert saved.raw == raw and saved.master_count == saved.resource_count == 0
    assert saved.resource_words == saved.placeholders == ()
    assert reader.data[reader.pos :] == b"following"


def test_civilization_prefix_requires_exact_dat_profile() -> None:
    reader = SaveReader(b"pad" + _data_civilization_prefix(), 3, version=0x44E666)
    with pytest.raises(SaveDecodeError, match="civilization data version"):
        read_game_data_civilization_prefix(reader)
    assert reader.pos == 3


def _data_master_common(*, string: bytes = b"raw\xff\0", sprites: int = 2) -> bytes:
    resources = b"".join(
        struct.pack("<HIB", type_id, value, flag)
        for type_id, value, flag in (
            (0xFFFF, 0x7FC01234, 2),
            (7, 0x80000000, 255),
            (1, 0xFFFFFFFF, 0),
        )
    )
    return (
        bytes(range(127))
        + struct.pack("<II", 0xDEADBEEF, len(string))
        + string
        + resources
        + bytes([sprites])
        + b"".join(struct.pack("<HBBB", 0xFFFF - index, 33, 255, index) for index in range(sprites))
        + struct.pack("<HH4IBB", 0x1234, 0xFFFF, 0x7FC00001, 0x80000000, 0, 0xFFFFFFFF, 255, 2)
        + _de(b"unit\xff\0")
        + struct.pack("<HH", 0x300, 0x302)
    )


def test_common_master_keeps_native_raw_bits_dynamic_arrays_and_unfixed_ids() -> None:
    raw = _data_master_common()
    reader = SaveReader(b"pad" + raw + b"derived body", 3, version=0x43E666)
    saved = read_game_data_master_common(reader)
    assert (saved.offset, saved.end_offset, reader.pos) == (3, 3 + len(raw), 3 + len(raw))
    assert saved.raw == raw and b"".join(saved.sections.values()) == raw
    assert saved.sections["scalar_prefix"] == bytes(range(127))
    assert saved.fields[0x18] == 0x0100 and saved.fields[0x0C] == 0x05040302
    assert saved.fields[0x10] == 0x09080706 and saved.fields[0x38] == 0x0B0A
    assert saved.fields[0x40] == 0x0D0C and saved.fields[0x58] == 0x1312
    assert saved.fields[0x70] == 0x1A191817 and saved.fields[0x130] == 0x7E7D7C7B
    assert 0x11C not in saved.fields  # Current DAT gate removes this old float.
    assert saved.string_word32 == 0xDEADBEEF and saved.string_bytes == b"raw\xff\0"
    assert [(r.type_bits, r.amount_bits, r.flag) for r in saved.resources] == [
        (0xFFFF, 0x7FC01234, 2),
        (7, 0x80000000, 255),
        (1, 0xFFFFFFFF, 0),
    ]
    assert [(s.sprite_bits, s.threshold, s.word8, s.flag) for s in saved.damage_sprites] == [
        (0xFFFF, 33, 255, 0),
        (0xFFFE, 33, 255, 1),
    ]
    assert saved.sound_numbers == {0x158: 0x2928, 0x1A0: 0x2B2A, 0x188: 0x1234, 0x170: 0xFFFF}
    assert saved.sound_events == {0x158: 0x7FC00001, 0x1A0: 0x80000000, 0x188: 0, 0x170: 0xFFFFFFFF}
    assert (saved.fields[0xD1], saved.fields[0xD2]) == (255, 2)
    assert saved.name_bytes == b"unit\xff\0"
    assert saved.fields[0x20] == 0x300 and saved.fields[0x28] == 0x302
    for record in (*saved.resources, *saved.damage_sprites):
        assert record.raw == reader.data[record.offset : record.end_offset]
    assert reader.data[reader.pos :] == b"derived body"


def test_every_small_common_master_truncation_rolls_back() -> None:
    raw = _data_master_common()
    for cut in range(len(raw)):
        reader = SaveReader(b"pad" + raw[:cut], 3, version=0x43E666)
        with pytest.raises(SaveDecodeError):
            read_game_data_master_common(reader)
        assert reader.pos == 3


@pytest.mark.parametrize("size", (0x2801, 0xFFFFFFFF))
def test_common_master_counted_string_is_bounded_before_reading(size: int) -> None:
    raw = bytearray(_data_master_common())
    struct.pack_into("<I", raw, 131, size)
    reader = SaveReader(b"pad" + raw, 3, version=0x43E666)
    with pytest.raises(SaveDecodeError, match="master string size"):
        read_game_data_master_common(reader)
    assert reader.pos == 3


def test_common_master_counted_string_retains_all_bytes_and_rejects_missing_nul() -> None:
    raw = _data_master_common(string=b"raw\xff!")
    reader = SaveReader(b"pad" + raw, 3, version=0x43E666)
    with pytest.raises(SaveDecodeError, match="unterminated"):
        read_game_data_master_common(reader)
    assert reader.pos == 3


def test_common_master_empty_string_and_damage_array_still_consume_the_complete_body() -> None:
    raw = _data_master_common(string=b"", sprites=0)
    reader = SaveReader(raw + b"following", version=0x43E666)
    saved = read_game_data_master_common(reader)
    assert saved.raw == raw and saved.string_bytes == b"" and saved.damage_sprites == ()
    assert reader.data[reader.pos :] == b"following"


def test_common_master_oversized_damage_array_rolls_back() -> None:
    raw = bytearray(_data_master_common())
    raw[127 + 8 + 5 + 21] = 255
    reader = SaveReader(b"pad" + raw, 3, version=0x43E666)
    with pytest.raises(SaveDecodeError, match="damage sprite count"):
        read_game_data_master_common(reader)
    assert reader.pos == 3


def test_common_master_bad_late_de_name_restores_the_original_start() -> None:
    raw = bytearray(_data_master_common())
    raw[-14:-10] = bytes(4)
    reader = SaveReader(b"pad" + raw, 3, version=0x43E666)
    with pytest.raises(SaveDecodeError, match="DE string"):
        read_game_data_master_common(reader)
    assert reader.pos == 3


def test_common_master_requires_exact_dat_profile() -> None:
    reader = SaveReader(b"pad" + _data_master_common(), 3, version=0x44E666)
    with pytest.raises(SaveDecodeError, match="common master data version"):
        read_game_data_master_common(reader)
    assert reader.pos == 3


def _data_master(kind: int) -> bytes:
    raw = bytes([kind]) + _data_master_common()
    if kind not in (10, 15):
        raw += struct.pack("<I", 0x7FC01234)
    if kind in (30, 40, 50, 60, 70, 80):
        raw += bytes(range(41))
    if kind in (40, 50, 60, 70, 80):
        task = struct.pack("<H", 1) + bytes(range(67))
        raw += (
            struct.pack(
                "<HIIhHHBHHIIBh",
                0x1234,
                0x7FC00001,
                0x80000000,
                2,
                0xFFFF,
                7,
                255,
                0x1234,
                0xFFFF,
                0xDEADBEEF,
                0x80000000,
                1,
                1,
            )
            + task
        )
    if kind in (50, 60, 70, 80):
        raw += struct.pack("<Hh4Hh2H", 0xABCD, 2, 0xFFFF, 4, 1, 7, 1, 3, 0xFFFF)
        raw += bytes(range(80))
    if kind == 60:
        raw += bytes(range(9))
    if kind in (70, 80):
        raw += bytes(range(18)) + struct.pack("<h", 2) + bytes(range(100, 118))
        raw += bytes(range(97))
    if kind == 80:
        raw += bytes(range(12)) + bytes(range(13)) + bytes(range(40))
        raw += struct.pack(
            "<HHHHIIBIIH",
            3,
            7,
            0xFFFF,
            0x4321,
            0x7FC00001,
            0xDEADBEEF,
            255,
            0x80000000,
            0xFFFFFFFF,
            0x1234,
        )
        raw += bytes(range(6))
    return raw


@pytest.mark.parametrize("kind", (10, 15, 20, 25, 30, 40, 50, 60, 70, 80))
def test_complete_data_master_factory_hierarchy_keeps_fields_and_stops_exactly(kind: int) -> None:
    raw = _data_master(kind)
    reader = SaveReader(b"pad" + raw + b"following", 3, version=0x43E666)
    saved = read_game_data_master(reader)
    assert saved.type_group == kind and saved.raw == raw
    assert (saved.offset, saved.end_offset, reader.pos) == (3, 3 + len(raw), 3 + len(raw))
    assert b"".join(saved.sections.values()) == raw
    assert saved.common.raw == _data_master_common()
    if kind not in (10, 15):
        assert saved.fields[0x1E0] == 0x7FC01234
    if kind in (30, 40, 50, 60, 70, 80):
        assert len(saved.sections["moving30"]) == 41
        assert saved.fields[0x220] == 0x28272625
        assert saved.sprite_id_bits[0x1E8] == 0x0100
    if kind in (40, 50, 60, 70, 80):
        assert saved.fields[0x230] == 0x1234 and saved.action_sprite_bits == (0xFFFF, 7)
        assert len(saved.tasks) == 1 and saved.tasks[0].fields[0xE] == 0x0403
        assert saved.sound_numbers[0x260] == 0x1234 and saved.sound_events[0x260] == 0xDEADBEEF
        assert saved.sound_numbers[0x278] == 0xFFFF and saved.sound_events[0x278] == 0x80000000
    if kind in (50, 60, 70, 80):
        assert saved.combat_pairs == {0x2B0: ((0xFFFF, 4), (1, 7)), 0x2A2: ((3, 0xFFFF),)}
        assert saved.fields[0x2A0] == 0xABCD
        assert saved.sprite_id_bits[0x318] == 0x4F4E
    if kind == 60:
        assert saved.sections["projectile60"] == bytes(range(9))
        assert saved.fields[0x328] == 0x08070605
    if kind in (70, 80):
        assert b"".join(saved.cost_records_6) == bytes(range(18))
        assert saved.definition_records_9 == (bytes(range(100, 109)), bytes(range(109, 118)))
        assert saved.fields[0x350] == 0x605F
    if kind == 80:
        assert len(saved.sections["building80"]) == 98
        assert b"".join(saved.building_piece_records_10) == bytes(range(40))
        assert saved.sprite_id_bits[0x418] == 0x0B0A
        assert saved.sound_numbers[0x488] == 0xFFFF and saved.sound_events[0x488] == 0x7FC00001
        assert saved.sound_numbers[0x470] == 0x4321 and saved.sound_events[0x470] == 0xDEADBEEF
        assert saved.fields[0x46F] == 5
    assert reader.data[reader.pos :] == b"following"


@pytest.mark.parametrize("kind", (10, 15, 20, 25, 30, 40, 50, 60, 70, 80))
def test_every_small_complete_data_master_truncation_rolls_back(kind: int) -> None:
    raw = _data_master(kind)
    for cut in range(len(raw)):
        reader = SaveReader(b"pad" + raw[:cut], 3, version=0x43E666)
        with pytest.raises(SaveDecodeError):
            read_game_data_master(reader)
        assert reader.pos == 3


@pytest.mark.parametrize("kind", (0, 9, 11, 255))
def test_unsupported_data_master_groups_roll_back(kind: int) -> None:
    reader = SaveReader(b"pad" + bytes([kind]), 3, version=0x43E666)
    with pytest.raises(SaveDecodeError, match="data master type"):
        read_game_data_master(reader)
    assert reader.pos == 3


@pytest.mark.parametrize("field", ("action sprite", "task", "combat pair", "definition"))
@pytest.mark.parametrize("count", (-1, 32767))
def test_complete_master_nested_counts_are_bounded_and_transactional(
    field: str, count: int
) -> None:
    raw = bytearray(_data_master(70))
    action = 1 + len(_data_master_common()) + 4 + 41
    # The original fixture has2 action sprites,1 task,2 first combat pairs,
    # 1 second combat pair, and2 nine-byte definition records.
    combat = action + 10 + 2 + 4 + 14 + 2 + 69
    unit = combat + 2 + 2 + 8 + 2 + 4 + 80
    position = {
        "action sprite": action + 10,
        "task": action + 30,
        "combat pair": combat + 2,
        "definition": unit + 18,
    }[field]
    struct.pack_into("<h", raw, position, count)
    reader = SaveReader(b"pad" + raw, 3, version=0x43E666)
    with pytest.raises(SaveDecodeError, match=f"{field} count"):
        read_game_data_master(reader)
    assert reader.pos == 3


def test_complete_data_master_requires_exact_dat_version() -> None:
    reader = SaveReader(b"pad" + _data_master(80), 3, version=0x44E666)
    with pytest.raises(SaveDecodeError, match="master data version"):
        read_game_data_master(reader)
    assert reader.pos == 3


def _data_civilization() -> bytes:
    prefix = (
        bytes([1]) + _de(b"Synthetic") + struct.pack("<hHHBhIII", 0, 0xFFFF, 7, 2, 3, 1, 0, 255)
    )
    return prefix + _data_master(10) + _data_master(80)


def test_complete_civilization_uses_presence_indices_and_retains_nonmatching_raw_ids() -> None:
    raw = _data_civilization()
    reader = SaveReader(b"pad" + raw + b"next civilization", 3, version=0x43E666)
    saved = read_game_data_civilization(reader)
    assert saved.raw == raw and list(saved.masters) == [0, 2]
    assert saved.prefix.name_bytes == b"Synthetic" and saved.prefix.placeholders == (1, 0, 255)
    assert saved.masters[0].type_group == 10 and saved.masters[2].type_group == 80
    assert saved.masters[2].common.fields[0x18] == 0x0100
    assert reader.data[reader.pos :] == b"next civilization"


def test_every_small_civilization_truncation_restores_the_whole_civilization() -> None:
    raw = _data_civilization()
    for cut in range(len(raw)):
        reader = SaveReader(b"pad" + raw[:cut], 3, version=0x43E666)
        with pytest.raises(SaveDecodeError):
            read_game_data_civilization(reader)
        assert reader.pos == 3


def test_unsupported_master_late_in_civilization_restores_the_civilization_start() -> None:
    raw = bytearray(_data_civilization())
    raw[-len(_data_master(80))] = 255
    reader = SaveReader(b"pad" + raw, 3, version=0x43E666)
    with pytest.raises(SaveDecodeError, match="master type"):
        read_game_data_civilization(reader)
    assert reader.pos == 3


def test_base_civilization_factory_rejects_derived_only_master_groups() -> None:
    raw = bytearray(_data_civilization())
    raw[0] = 0
    reader = SaveReader(b"pad" + raw, 3, version=0x43E666)
    with pytest.raises(SaveDecodeError, match="base civilization"):
        read_game_data_civilization(reader)
    assert reader.pos == 3


def _data_research_record(name: bytes = b"research\xff\0", locations: int = 2) -> bytes:
    return (
        struct.pack("<6H", 0xFFFF, 0, 7, 0x8000, 0x1234, 3)
        + struct.pack("<HHBHHBHHB", 0xFFFF, 77, 255, 0, 0x8000, 2, 7, 0xFFFF, 0)
        + struct.pack(
            "<HHHIIHHHII",
            0xFFFF,
            3,
            7,
            0xDEADBEEF,
            0x80000000,
            0x1234,
            0xFFFF,
            2,
            0x7FC01234,
            0xFFFFFFFF,
        )
        + _de(name)
        + struct.pack("<Bh", 255, locations)
        + b"".join(
            struct.pack("<HHBI", 0xFFFF - index, 0x8000 + index, 255 - index, 0x7FC00001 + index)
            for index in range(locations)
        )
    )


def _data_research_catalog() -> bytes:
    return struct.pack("<h", 2) + _data_research_record() + _data_research_record(b"", 0)


def test_research_catalog_preserves_current_prerequisites_costs_locations_and_raw_fields() -> None:
    raw = _data_research_catalog()
    reader = SaveReader(b"pad" + raw + b"world words", 3, version=0x43E666)
    saved = read_game_data_research_catalog(reader)
    assert saved.raw == raw and saved.count == 2 and len(saved.definitions) == 2
    assert (saved.offset, saved.end_offset, reader.pos) == (3, 3 + len(raw), 3 + len(raw))
    first, second = saved.definitions
    assert first.prerequisite_bits == (0xFFFF, 0, 7, 0x8000, 0x1234, 3)
    assert [(r.type_bits, r.amount_bits, r.flag) for r in first.costs] == [
        (0xFFFF, 77, 255),
        (0, 0x8000, 2),
        (7, 0xFFFF, 0),
    ]
    assert first.fields == {
        0x24: 0xFFFF,
        0x26: 3,
        0x28: 7,
        0x40: 0xDEADBEEF,
        0x44: 0x80000000,
        0x3A: 0x1234,
        0x3C: 0xFFFF,
        0x3E: 2,
        0x4C: 0x7FC01234,
        0x68: 0xFFFFFFFF,
        0x6C: 255,
    }
    assert first.name_bytes == b"research\xff\0" and second.name_bytes == b""
    assert [(r.first16_bits, r.second16_bits, r.word8, r.word32) for r in first.locations] == [
        (0xFFFF, 0x8000, 255, 0x7FC00001),
        (0xFFFE, 0x8001, 254, 0x7FC00002),
    ]
    assert second.locations == ()
    for definition in saved.definitions:
        assert b"".join(definition.sections.values()) == definition.raw
        assert len(definition.raw) == 62 + len(definition.name_bytes) + 9 * len(
            definition.locations
        )
        for record in (*definition.costs, *definition.locations):
            assert record.raw == reader.data[record.offset : record.end_offset]
    assert reader.data[reader.pos :] == b"world words"


def test_every_small_research_catalog_truncation_rolls_back() -> None:
    raw = _data_research_catalog()
    for cut in range(len(raw)):
        reader = SaveReader(b"pad" + raw[:cut], 3, version=0x43E666)
        with pytest.raises(SaveDecodeError):
            read_game_data_research_catalog(reader)
        assert reader.pos == 3


@pytest.mark.parametrize("count", (-1, 32767, 3))
def test_research_catalog_count_is_bounded_and_transactional(count: int) -> None:
    raw = bytearray(_data_research_catalog())
    struct.pack_into("<h", raw, 0, count)
    reader = SaveReader(b"pad" + raw, 3, version=0x43E666)
    with pytest.raises(SaveDecodeError, match="research count"):
        read_game_data_research_catalog(reader)
    assert reader.pos == 3


@pytest.mark.parametrize("count", (-1, 32767))
def test_research_location_count_is_bounded_and_rolls_back_the_catalog(count: int) -> None:
    raw = bytearray(_data_research_catalog())
    struct.pack_into("<h", raw, 2 + 60 + len(b"research\xff\0"), count)
    reader = SaveReader(b"pad" + raw, 3, version=0x43E666)
    with pytest.raises(SaveDecodeError, match="research location count"):
        read_game_data_research_catalog(reader)
    assert reader.pos == 3


def test_bad_name_in_later_research_restores_the_catalog_start() -> None:
    raw = bytearray(_data_research_catalog())
    at = 2 + len(_data_research_record()) + 55
    raw[at : at + 4] = bytes(4)
    reader = SaveReader(b"pad" + raw, 3, version=0x43E666)
    with pytest.raises(SaveDecodeError, match="DE string"):
        read_game_data_research_catalog(reader)
    assert reader.pos == 3


def test_empty_research_catalog_consumes_only_the_count() -> None:
    reader = SaveReader(b"\0\0following", version=0x43E666)
    saved = read_game_data_research_catalog(reader)
    assert saved.count == 0 and saved.definitions == () and reader.pos == 2


def _data_configuration_record(group: int) -> bytes:
    header = bytes(range((5, 5, 97, 9)[group]))
    arrays = (
        ((0xDEADBEEF, 0x7FC00001),) if group == 2 else ((0xDEADBEEF, 0x7FC00001), (), (0x80000000,))
    )
    return (
        header
        + b"".join(
            bytes([len(array)]) + struct.pack("<" + "I" * len(array), *array) for array in arrays
        )
        + bytes(range((110, 103, 16, 96)[group]))
    )


def _data_configuration() -> bytes:
    return struct.pack("<BBHBI", 1, 1, 1, 1, 0xDEADBEEF) + b"".join(
        _data_configuration_record(group) for group in range(4)
    )


def test_configuration_keeps_four_native_groups_headers_arrays_and_fixed_tails() -> None:
    raw = _data_configuration()
    reader = SaveReader(b"pad" + raw + b"following", 3, version=0x43E666)
    saved = read_game_data_configuration(reader)
    assert saved.raw == raw and saved.counts == (1, 1, 1, 1) and saved.extra_bits == 0xDEADBEEF
    assert (saved.offset, saved.end_offset, reader.pos) == (3, 3 + len(raw), 3 + len(raw))
    for group, entries in enumerate(saved.groups):
        assert len(entries) == 1
        record = entries[0]
        assert record.group == group and record.raw == _data_configuration_record(group)
        assert record.raw == reader.data[record.offset : record.end_offset]
        assert record.header_bytes == bytes(range((5, 5, 97, 9)[group]))
        assert record.tail_bytes == bytes(range((110, 103, 16, 96)[group]))
        assert record.array_words[0] == (0xDEADBEEF, 0x7FC00001)
        if group == 2:
            assert len(record.array_words) == 1
        else:
            assert record.array_words[1:] == ((), (0x80000000,))
    assert reader.data[reader.pos :] == b"following"


def test_every_small_configuration_truncation_rolls_back() -> None:
    raw = _data_configuration()
    for cut in range(len(raw)):
        reader = SaveReader(b"pad" + raw[:cut], 3, version=0x43E666)
        with pytest.raises(SaveDecodeError):
            read_game_data_configuration(reader)
        assert reader.pos == 3


def test_configuration_third_group_count_is_u16_at_the_current_dat_threshold() -> None:
    record = bytes(97) + b"\0" + bytes(16)
    raw = struct.pack("<BBHBI", 0, 0, 256, 0, 7) + record * 256
    reader = SaveReader(raw + b"following", version=0x43E666)
    saved = read_game_data_configuration(reader)
    assert saved.counts == (0, 0, 256, 0) and len(saved.groups[2]) == 256
    assert saved.groups[0] == saved.groups[1] == saved.groups[3] == ()
    assert reader.data[reader.pos :] == b"following"


@pytest.mark.parametrize(
    "counts", ((255, 0, 0, 0), (0, 255, 0, 0), (0, 0, 65535, 0), (0, 0, 0, 255))
)
def test_configuration_counts_are_bounded_before_reading_records(counts: tuple[int, ...]) -> None:
    raw = struct.pack("<BBHBI", *counts, 0)
    reader = SaveReader(b"pad" + raw, 3, version=0x43E666)
    with pytest.raises(SaveDecodeError, match="configuration counts"):
        read_game_data_configuration(reader)
    assert reader.pos == 3


def test_configuration_oversized_word_array_restores_the_whole_table() -> None:
    raw = bytearray(_data_configuration())
    raw[14] = 255
    reader = SaveReader(b"pad" + raw, 3, version=0x43E666)
    with pytest.raises(SaveDecodeError, match="configuration word count"):
        read_game_data_configuration(reader)
    assert reader.pos == 3


def _data_tail() -> bytes:
    return (
        _data_research_catalog()
        + struct.pack("<7I", 0xFFFFFFFF, 7, 14, 0x80000000, 1400, 5, 10)
        + _data_configuration()
    )


def test_complete_tail_preserves_components_and_requires_exact_inflated_eof() -> None:
    raw = _data_tail()
    reader = SaveReader(b"pad" + raw, 3, version=0x43E666)
    saved = read_game_data_tail(reader)
    assert saved.raw == raw and b"".join(saved.sections.values()) == raw
    assert saved.research.raw == _data_research_catalog()
    assert saved.configuration.raw == _data_configuration()
    assert saved.world_words == (0xFFFFFFFF, 7, 14, 0x80000000, 1400, 5, 10)
    assert saved.end_offset == reader.pos == len(reader.data) and reader.remaining == 0


def test_every_complete_tail_truncation_restores_the_whole_tail() -> None:
    raw = _data_tail()
    for cut in range(len(raw)):
        reader = SaveReader(b"pad" + raw[:cut], 3, version=0x43E666)
        with pytest.raises(SaveDecodeError):
            read_game_data_tail(reader)
        assert reader.pos == 3


@pytest.mark.parametrize("suffix", (b"\0", b"unexpected", _data_configuration()))
def test_complete_tail_rejects_trailing_bytes_transactionally(suffix: bytes) -> None:
    reader = SaveReader(b"pad" + _data_tail() + suffix, 3, version=0x43E666)
    with pytest.raises(SaveDecodeError, match="trailing bytes"):
        read_game_data_tail(reader)
    assert reader.pos == 3


def test_zero_catalog_and_zero_configuration_form_a_valid_minimal_tail() -> None:
    raw = bytes(2) + bytes(28) + bytes(9)
    reader = SaveReader(raw, version=0x43E666)
    saved = read_game_data_tail(reader)
    assert saved.research.definitions == () and saved.configuration.groups == ((), (), (), ())
    assert saved.world_words == (0,) * 7 and reader.remaining == 0


@pytest.mark.parametrize(
    "read", (read_game_data_research_catalog, read_game_data_configuration, read_game_data_tail)
)
def test_tail_component_readers_require_the_exact_native_dat_profile(
    read: Callable[[SaveReader], object],
) -> None:
    reader = SaveReader(b"pad" + _data_tail(), 3, version=0x44E666)
    with pytest.raises(SaveDecodeError, match="data version"):
        read(reader)
    assert reader.pos == 3
