"""Complete native decision wrappers and transactional module composition."""

from __future__ import annotations

import gzip
import hashlib
import json
from pathlib import Path

import pytest

from vantage.replay_binary import SaveDecodeError, SaveReader
from vantage.replay_player_ai import read_player_ai

FIXTURE = Path(__file__).parent / "fixtures/native_saved_player_ai_54800.json.gz"
MODULES = (
    "main",
    "build",
    "construction",
    "diplomacy",
    "emotional",
    "information",
    "resource",
    "strategy",
    "tactical",
    "trade",
)


def _cases():
    return json.loads(gzip.decompress(FIXTURE.read_bytes()))["cases"]


@pytest.mark.parametrize("case", _cases(), ids=lambda c: f"{c['sample']}-p{c['player_id']}")
def test_native_wrappers_join_all_ten_modules_and_stop_before_world_player_state(case) -> None:
    raw, following = bytes.fromhex(case["raw_hex"]), bytes.fromhex(case["next_bytes_hex"])
    reader = SaveReader(b"prefix" + raw + following, 6)
    ai = read_player_ai(reader, case["num_players"])
    parts = [getattr(ai, name) for name in MODULES]
    assert ai.offset == 6 and ai.end_offset == reader.pos == 6 + len(raw)
    assert len(raw) == case["end"] - case["start"]
    assert ai.raw == raw and hashlib.sha256(raw).hexdigest() == case["sha256"]
    assert reader.data[reader.pos :] == following
    assert [len(part.raw) for part in parts] == case["module_lengths"]
    assert b"".join(part.raw for part in parts) + ai.trailer.raw == raw
    assert len(ai.trailer.raw) == case["trailer_length"] == 90 + 4 * ai.num_players
    assert len(ai.trailer.player_words) == ai.num_players
    assert set(ai.trailer.fields) == set(range(0x28F50, 0x28F7C, 4)) | set(
        range(0x28F98, 0x28FC0, 4)
    )
    cursor = ai.offset
    for part in parts:
        assert part.offset == cursor
        cursor = part.end_offset
    assert cursor + len(ai.trailer.raw) == ai.end_offset


def test_truncation_in_each_module_and_trailer_restores_entire_wrapper() -> None:
    case = _cases()[0]
    raw = bytes.fromhex(case["raw_hex"])
    cursor = 0
    cuts = {0, len(raw) - 1, len(raw) - 2, len(raw) - case["trailer_length"]}
    for length in case["module_lengths"]:
        cuts.update((cursor, cursor + 1, cursor + length - 1))
        cursor += length
    for cut in cuts:
        reader = SaveReader(b"prefix" + raw[:cut], 6)
        with pytest.raises(SaveDecodeError):
            read_player_ai(reader, case["num_players"])
        assert reader.pos == 6


@pytest.mark.parametrize("count", [0, -1, 3, 7, 2**31])
def test_wrong_world_player_count_is_not_guessed_or_resynchronized(count: int) -> None:
    raw = bytes.fromhex(_cases()[0]["raw_hex"])
    reader = SaveReader(b"prefix" + raw, 6)
    with pytest.raises(SaveDecodeError):
        read_player_ai(reader, count)
    assert reader.pos == 6


@pytest.mark.parametrize("marker", [0, -44, -2])
def test_corrupt_trailer_marker_rolls_back_previous_modules(marker: int) -> None:
    case = _cases()[0]
    raw = bytearray.fromhex(case["raw_hex"])
    trailer_start = len(raw) - case["trailer_length"]
    at = trailer_start if marker == 0 else len(raw) + marker
    raw[at : at + 2] = b"\xff\xff"
    reader = SaveReader(bytes(raw))
    with pytest.raises(SaveDecodeError, match="player-AI marker"):
        read_player_ai(reader, case["num_players"])
    assert reader.pos == 0


def test_save_version_guard_precedes_module_loading() -> None:
    raw = bytes.fromhex(_cases()[0]["raw_hex"])
    reader = SaveReader(raw, version=0x450000)
    with pytest.raises(SaveDecodeError, match="player-AI save version"):
        read_player_ai(reader, 4)
    assert reader.pos == 0
