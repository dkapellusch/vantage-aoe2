"""Portable native initial headers, nonempty variable records, and rollback."""

from __future__ import annotations

import gzip
import hashlib
import json
import math
import struct
from functools import lru_cache
from pathlib import Path
from typing import Any

import pytest

from vantage.replay_binary import SaveDecodeError, SaveReader
from vantage.replay_file_header import read_file_header

# Original 2321/2482-byte native header slices, reconstructed byte-contiguously
# from the retained original field report. No game/data directory is required.
# Provenance, input hashes, all932 original field comparisons, and generator:
# artifacts/game-internals/2026-10-18-world-envelope/header/.
FIXTURE = Path(__file__).parent / "fixtures/native_saved_file_headers_54800.json.gz"


@lru_cache(maxsize=1)
def _cases() -> list[dict[str, Any]]:
    return list(json.loads(gzip.decompress(FIXTURE.read_bytes()))["cases"])


def _raw(case: dict[str, Any]) -> bytes:
    value = bytes.fromhex(case["raw_hex"])
    assert hashlib.sha256(value).hexdigest() == case["raw_sha256"]
    return value


def _replace(case: dict[str, Any], changes: dict[str, bytes]) -> bytes:
    """Splice original native oracle spans, applying original offsets from right."""
    raw = _raw(case)
    spans = [(case["spans"][name], value) for name, value in changes.items()]
    for (start, end), value in sorted(spans, reverse=True):
        raw = raw[:start] + value + raw[end:]
    return raw


def _string(raw: bytes, *, reversed_marker: bool = False) -> bytes:
    words = (len(raw), 0x0A60) if reversed_marker else (0x0A60, len(raw))
    return struct.pack("<HH", *words) + raw


def _unique(crc: int, path: bytes, raw_data: int) -> bytes:
    return struct.pack("<I", crc) + _string(path) + struct.pack("<I", raw_data)


@pytest.mark.parametrize("index", (0, 1))
def test_native_header_reaches_exact_world_boundary_and_keeps_all_wire_spans(index: int) -> None:
    case = _cases()[index]
    raw = _raw(case)
    following = bytes.fromhex(case["following_hex"])
    prefix = b"prefix!"
    reader = SaveReader(prefix + raw + following, len(prefix))
    header = read_file_header(reader)
    assert (header.offset, header.end_offset) == (len(prefix), len(prefix) + case["end_offset"])
    assert header.raw == raw and reader.pos == header.end_offset
    assert reader.take(len(following)) == following  # OuterWorld flag remains unread.
    assert header.game_version == b"VER 9.4\0"
    assert (header.save_version, header.build_word, header.build) == (0x44E666, 0x2D610, 54800)
    assert header.date_time_played == header.time_of_save == case["date_time_played"]
    assert header.save_game_name == b"" and header.random_seed == header.game_duration_word == 0
    options = header.options
    assert options.version_word == 0x448C6000
    assert (options.dlc.version, options.dlc.dataset_id) == (1000, 1)
    assert options.dlc.ids.values == tuple(range(2, 11)) + tuple(range(12, 20))
    assert options.dlc.ids.count_width == 4 and options.dlc.ids.count == 17
    assert options.num_players_excluding_gaia == case["num_players"]
    assert options.max_players_for_lobby == len(options.players) == 8
    assert [player.random_civ_choices.count for player in options.players] == case["choice_counts"]
    assert [player.civilization_id for player in options.players] == case["civilization_ids"]
    assert all(player.version == 15 for player in options.players)
    assert len(options.custom_map_pool) == 10
    assert options.standard_map_pool.values == ()
    assert options.custom_ai_files.capacity == options.custom_xs_files.capacity == 0
    assert options.civilizations.values == (62, 52, 53, 58, 57, 60, 49, 59, 61, 11, 51, 50)
    assert options.civilizations.count_width == options.civilizations_pompeii.count_width == 8
    assert options.civilizations_pompeii.values == ()
    reference = options.resource_files[1]
    assert reference.crc == 0xCB108738
    assert reference.path_bytes == (
        b"SUBSCRIBEDMODS:RANDOM_MAPS:ZN@HyperRandomExtreme.rms:829_Zetnus HyperRandom:false"
    )
    # Every wire field is retained once, in order, with no opaque gaps.
    cursor = len(prefix)
    for field in header.fields.values():
        assert field.offset == cursor
        assert field.raw == reader.data[field.offset : field.end_offset]
        cursor = field.end_offset
    assert cursor == header.end_offset
    for section in header.sections.values():
        assert header.offset <= section.offset <= section.end_offset <= header.end_offset
        assert section.raw == reader.data[section.offset : section.end_offset]
        assert section.native_reader > 0x140000000
    for name, (start, end) in case["spans"].items():
        if name in header.fields:
            field = header.fields[name]
            assert (field.offset, field.end_offset) == (len(prefix) + start, len(prefix) + end)
    assert header.sections["options"].native_reader == 0x1413D2300
    assert header.sections["options.body"].native_reader == 0x1413D88F0
    assert header.sections["header.prefix"].end_offset == len(prefix) + 24
    assert header.options.section.end_offset == header.fields["save_game_name"].offset
    assert header.options.players[0].section.native_reader == 0x1413EDC90


def test_nonempty_native_width_lists_and_file_arrays_reach_the_following_world_flag() -> None:
    case = _cases()[0]
    changes = {
        "dlc_options.ids": struct.pack("<I3I", 3, 2, 7, 19),
        "player[0].random_civ_choices": struct.pack("<I2I", 2, 49, 62),
        "mStandardMapPool": struct.pack("<I2I", 2, 9, 108),
        "mCustomAIFiles.capacity": struct.pack("<Q", 2)
        + _unique(0x11223344, b"AI:first.per", 0xAABBCCDD)
        + _unique(0x87654321, b"AI:second.per", 0x12345678),
        "mCustomXSFiles.capacity": struct.pack("<Q", 1)
        + _unique(0xA1B2C3D4, b"XS:probe.xs", 0x99887766),
        "civilizations": struct.pack("<Q3I", 3, 49, 62, 0xFFFFFFFF),
        "civilizations_pompeii": struct.pack("<Q2I", 2, 11, 50),
        "mMatchType": struct.pack("<Q", 0x8877665544332211),
    }
    raw = _replace(case, changes)
    reader = SaveReader(raw + b"WORLD")
    header = read_file_header(reader)
    options = header.options
    assert header.raw == raw and reader.take(5) == b"WORLD"
    assert options.dlc.ids.values == (2, 7, 19)
    assert options.players[0].random_civ_choices.values == (49, 62)
    assert options.standard_map_pool.values == (9, 108)
    assert options.custom_ai_files.capacity == 2
    assert [entry.reference.path_bytes for entry in options.custom_ai_files.entries] == [
        b"AI:first.per",
        b"AI:second.per",
    ]
    first = options.custom_ai_files.entries[0]
    assert (first.reference.crc, first.raw_data) == (0x11223344, 0xAABBCCDD)
    assert options.custom_xs_files.capacity == 1
    assert options.custom_xs_files.entries[0].reference.path_bytes == b"XS:probe.xs"
    assert options.custom_xs_files.entries[0].raw_data == 0x99887766
    assert options.civilizations.values == (49, 62, 0xFFFFFFFF)
    assert options.civilizations_pompeii.values == (11, 50)
    assert header.fields["mMatchType"].value == 0x8877665544332211
    assert header.fields["mMatchType"].end_offset - header.fields["mMatchType"].offset == 8
    assert header.fields["mModdedDatasetTitle"].kind == "de_string"


@pytest.mark.parametrize("reversed_marker", (False, True))
def test_unique_file_crc_precedes_raw_de_string_with_either_native_marker_order(
    reversed_marker: bool,
) -> None:
    case = _cases()[0]
    path = b"USER:XS:\xff\x00probe.xs::false"
    raw = _replace(
        case,
        {
            "mCustomScenarioOrCampaignFile": struct.pack("<I", 0x12345678)
            + _string(path, reversed_marker=reversed_marker)
        },
    )
    header = read_file_header(SaveReader(raw))
    reference = header.options.resource_files[0]
    assert (reference.crc, reference.path_bytes) == (0x12345678, path)
    assert reference.section.raw == struct.pack("<I", 0x12345678) + _string(
        path, reversed_marker=reversed_marker
    )
    assert header.options.resource_files[1].crc == 0xCB108738
    assert header.fields["mCustomScenarioOrCampaignFile.PathSpec"].value == path


def test_float_flags_signed_words_guid_and_profile_id_keep_original_bits() -> None:
    case = _cases()[0]
    guid = bytes.fromhex("ffeeddccbbaa99887766554433221100")
    raw = _replace(
        case,
        {
            "mGameSpeed": struct.pack("<I", 0x80000000),
            "mVersion": struct.pack("<I", 0x7F800000),
            "game_duration": struct.pack("<I", 0x7FC01234),
            "mTradingEnabled": b"\xfe",
            "mGameId": guid,
            "mGameSessionId": guid[::-1],
            "player[0].mRlProfileId": struct.pack("<Q", 0xFEDCBA9876543210),
            "player[0].mSlotColorOverride": struct.pack("<i", -123),
            "player[0].mAiScriptBaseName": _string(b"\xffraw\x00script"),
        },
    )
    saved = read_file_header(SaveReader(raw))
    assert saved.raw == raw
    assert saved.fields["mGameSpeed"].value == 0x80000000
    assert math.copysign(1, saved.fields["mGameSpeed"].float_value) == -1
    assert saved.fields["mVersion"].float_value == math.inf
    assert saved.game_duration_word == 0x7FC01234
    assert math.isnan(saved.fields["game_duration"].float_value)
    assert saved.fields["mTradingEnabled"].value == 254
    assert saved.fields["mGameId"].value == guid
    assert saved.fields["mGameSessionId"].value == guid[::-1]
    assert saved.options.players[0].fields["mRlProfileId"].value == 0xFEDCBA9876543210
    assert saved.options.players[0].fields["mSlotColorOverride"].value == -123
    assert saved.options.players[0].fields["mAiScriptBaseName"].value == b"\xffraw\x00script"
    with pytest.raises(ValueError, match="not a saved f32"):
        _ = saved.fields["mTradingEnabled"].float_value


@pytest.mark.parametrize(
    "name,value",
    (
        ("legacy_save_version", 0),
        ("save_version", 0x44E665),
        ("build", 0x2D611),
        ("build", 54800),
        ("options_version", 0x448C4000),
        ("dlc_options.version", 1001),
        ("player[0].version", 14),
        ("player[0].version", 16),
    ),
)
def test_profile_mismatch_rolls_back_the_whole_header(name: str, value: int) -> None:
    raw = _replace(_cases()[0], {name: struct.pack("<I", value)})
    reader = SaveReader(b"pad" + raw, 3)
    with pytest.raises(SaveDecodeError):
        read_file_header(reader)
    assert reader.pos == 3 and reader.version == 0x44E666


@pytest.mark.parametrize(
    "name,width",
    (
        ("dlc_options.ids.count", 4),
        ("player[0].random_civ_choices.count", 4),
        ("mStandardMapPool.count", 4),
        ("mCustomAIFiles.capacity", 8),
        ("mCustomXSFiles.capacity", 8),
        ("civilizations.count", 8),
        ("civilizations_pompeii.count", 8),
    ),
)
def test_count_bounds_fail_at_the_count_and_restore_the_caller(name: str, width: int) -> None:
    case = _cases()[0]
    raw = _replace(case, {name: b"\xff" * width})
    reader = SaveReader(b"pad" + raw, 3)
    with pytest.raises(SaveDecodeError) as caught:
        read_file_header(reader)
    assert caught.value.offset == 3 + case["spans"][name][0]
    assert reader.pos == 3 and reader.version == 0x44E666


@pytest.mark.parametrize(
    "marker",
    (
        "after_game_mode",
        "after_legacy_resource_names",
        "after_victory_amount",
        "after_game_flags",
        "after_lobby_players",
    ),
)
def test_native_u32_markers_are_checked_without_resynchronization(marker: str) -> None:
    case = _cases()[0]
    raw = _replace(case, {"marker." + marker: struct.pack("<I", 155556)})
    reader = SaveReader(b"pad" + raw, 3)
    with pytest.raises(SaveDecodeError):
        read_file_header(reader)
    assert reader.pos == 3


@pytest.mark.parametrize("bad_prefix", (b"VER 9.3\0", b"VER 9.4X"))
def test_fixed_eight_game_version_bytes_are_required(bad_prefix: bytes) -> None:
    raw = _raw(_cases()[0])
    reader = SaveReader(b"pad" + bad_prefix + raw[8:], 3)
    with pytest.raises(SaveDecodeError, match="game-version"):
        read_file_header(reader)
    assert reader.pos == 3


def test_reader_version_must_match_the_proven_saved_version_and_is_not_changed() -> None:
    reader = SaveReader(b"pad" + _raw(_cases()[0]), 3, version=0x44E665)
    with pytest.raises(SaveDecodeError, match="save version"):
        read_file_header(reader)
    assert (reader.pos, reader.version) == (3, 0x44E665)


@pytest.mark.parametrize("capacity", (9, 255))
def test_lobby_capacity_cannot_exceed_the_native_eight_slots(capacity: int) -> None:
    reader = SaveReader(_replace(_cases()[0], {"mMaxPlayersForLobby": bytes([capacity])}))
    with pytest.raises(SaveDecodeError, match="lobby player capacity"):
        read_file_header(reader)
    assert reader.pos == 0


@pytest.mark.parametrize("framing", (b"\x01\0\x02\0", struct.pack("<HH", 0x0A60, 65535)))
def test_invalid_or_truncated_de_string_framing_rolls_back(framing: bytes) -> None:
    case = _cases()[0]
    start, end = case["spans"]["mCustomScenarioOrCampaignFile.PathSpec"]
    raw = _raw(case)
    reader = SaveReader(b"pad" + raw[:start] + framing + raw[start + 4 : end] + raw[end:], 3)
    with pytest.raises(SaveDecodeError):
        read_file_header(reader)
    assert reader.pos == 3


def test_every_truncated_native_header_prefix_rolls_back_and_exact_header_needs_no_lookahead() -> (
    None
):
    raw = _raw(_cases()[0])
    for cut in range(len(raw)):
        reader = SaveReader(b"pad" + raw[:cut], 3)
        with pytest.raises(SaveDecodeError):
            read_file_header(reader)
        assert reader.pos == 3
    reader = SaveReader(raw)
    assert read_file_header(reader).raw == raw and reader.remaining == 0
