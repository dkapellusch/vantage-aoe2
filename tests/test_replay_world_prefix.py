"""Exact native BaseWorld/map boundaries and bit-preserving bounded failures."""

from __future__ import annotations

import json
import struct
from pathlib import Path

import pytest

from vantage.replay_binary import SaveDecodeError, SaveReader
from vantage.replay_world_prefix import read_world_prefix

FIXTURE = Path(__file__).parent / "fixtures/native_saved_world_prefix_54800.json"


def _cases():
    return json.loads(FIXTURE.read_text())["cases"]


def test_two_native_world_prefixes_end_at_the_map_reader_entry() -> None:
    for case in _cases():
        raw = bytes.fromhex(case["raw_hex"])
        following = bytes.fromhex(case["following_map_header_hex"])
        reader = SaveReader(b"before" + raw + following, 6)
        saved = read_world_prefix(reader)
        assert saved.offset == 6
        assert saved.end_offset == reader.pos == 6 + len(raw)
        assert saved.end_offset - saved.offset == 74 + 4 * saved.num_players
        assert saved.raw == raw
        assert saved.fields == {int(k, 16): v for k, v in case["fields"].items()}
        assert saved.clock_fields == {int(k, 16): v for k, v in case["clock_fields"].items()}
        assert saved.num_players == case["native_capture_player_count"]
        assert saved.srand_seed == saved.fields[0x7D0] == case["srand_seed"]
        assert saved.local_player_index == case["local_player_index"] == 1
        assert [saved.option_flag, saved.scenario_flag, saved.game_state] == [0, 1, 0]
        assert saved.campaign_indices == tuple(case["campaign_indices"])
        assert saved.campaign_section == case["campaign_section"]
        assert saved.campaign_sub_index == case["campaign_sub_index"]
        assert saved.scenario_sub_index == case["scenario_sub_index"]
        assert saved.player_words == tuple(case["player_words"])
        assert list(struct.unpack("<5I", reader.take(20))) == case["map_header_words"]
        assert reader.remaining == 0


def test_every_truncated_native_prefix_rolls_back_without_scanning() -> None:
    for case in _cases():
        raw = bytes.fromhex(case["raw_hex"])
        for length in range(len(raw)):
            reader = SaveReader(b"before" + raw[:length], 6)
            with pytest.raises(SaveDecodeError):
                read_world_prefix(reader)
            assert reader.pos == 6


@pytest.mark.parametrize("version", [0, 0x3D0000, 0x44E665, 0x44E667, 0xFFFFFFFF])
def test_unknown_versions_restore_cursor(version: int) -> None:
    reader = SaveReader(b"before" + bytes(100), 6, version=version)
    with pytest.raises(SaveDecodeError, match="unsupported BaseWorld"):
        read_world_prefix(reader)
    assert reader.pos == 6


def test_native_word_and_enum_bits_survive_without_runtime_fixups() -> None:
    raw = bytearray.fromhex(_cases()[0]["raw_hex"])
    struct.pack_into("<I", raw, 0, 0xFFFFFFFF)  # old_time native may replace after load.
    struct.pack_into("<I", raw, 24, 0x7FC12345)  # Preserve the clock float's NaN payload.
    raw[28] = 0xFF  # Native discards this byte; it still occupies one byte.
    struct.pack_into("<HH", raw, 45, 0xFFFF, 4)
    raw[49:52] = b"\xff\x80\xfe"
    struct.pack_into("<III", raw, 52, 0xFFFFFFFF, 0x80000000, 0xABCDEF01)
    struct.pack_into("<4I", raw, 74, 1, 0xFFFFFFFF, 0x80000000, 0xABCDEF01)
    saved = read_world_prefix(SaveReader(bytes(raw)))
    assert saved.raw == raw
    assert saved.fields[0x84] == 0xFFFFFFFF
    assert saved.clock_fields[0x10] == 0x7FC12345
    assert saved.discarded_byte == 0xFF
    assert saved.local_player_index == saved.fields[0x6B0] == 0xFFFF
    assert (saved.option_flag, saved.scenario_flag, saved.game_state) == (0xFF, 0x80, 0xFE)
    assert saved.campaign_indices == (0xFFFFFFFF, 0x80000000, 0xABCDEF01)
    assert saved.player_words == (1, 0xFFFFFFFF, 0x80000000, 0xABCDEF01)


def test_zero_player_native_loop_consumes_no_words_and_keeps_following_data() -> None:
    raw = bytearray.fromhex(_cases()[0]["raw_hex"])
    struct.pack_into("<H", raw, 47, 0)
    reader = SaveReader(bytes(raw[:74]) + b"next")
    saved = read_world_prefix(reader)
    assert saved.num_players == 0 and saved.player_words == ()
    assert reader.pos == 74 and reader.take(4) == b"next"


def test_u16_count_requires_the_whole_player_array() -> None:
    raw = bytearray.fromhex(_cases()[0]["raw_hex"])
    struct.pack_into("<H", raw, 47, 0xFFFF)
    reader = SaveReader(bytes(raw))
    with pytest.raises(SaveDecodeError, match="truncated BaseWorld player words"):
        read_world_prefix(reader)
    assert reader.pos == 0
