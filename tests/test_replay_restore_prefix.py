"""End-to-end portable native restoration prefix, with no scans or offsets as inputs."""

from __future__ import annotations

import hashlib
import struct

import pytest
from replay_fixtures import restore_prefix_case

from vantage.replay_binary import SaveDecodeError, SaveReader
from vantage.replay_restore_prefix import read_replay_restore_prefix


@pytest.mark.parametrize(
    "sample,end,digest",
    [
        ("3p", 11462370, "5552de00a8177992ed99393ad2fa1d6df89fb614d0046b33eff0148931eb3afa"),
        ("6p", 23803129, "fec92dcedb66c2b249fdd73fbe8137fa22e3c1b9448abd5d6f2d011f75a5c393"),
    ],
)
def test_native_restoration_reads_from_byte_zero_through_every_second_pass(
    sample: str, end: int, digest: str
) -> None:
    raw, spans, players, restores = restore_prefix_case(sample)
    assert hashlib.sha256(raw).hexdigest() == digest
    following = bytes.fromhex("1f85cb3f1000000008000000")
    before = b"prefix!"
    reader = SaveReader(before + raw + following, len(before))
    saved = read_replay_restore_prefix(reader)
    shift = len(before)
    assert saved.offset == shift and saved.end_offset == reader.pos == end + shift
    assert saved.raw == raw and reader.data[reader.pos :] == following
    assert saved.header.end_offset == spans[0][1] + shift
    assert saved.rules.end_offset == saved.world.offset == spans[1][1] + shift
    assert saved.world.end_offset == restores[0]["start"] + shift
    assert len(saved.world.players) == len(saved.player_restores) == len(players)
    assert [p.end_offset - shift for p in saved.player_restores] == [p["end"] for p in restores]
    assert saved.world.prefix.num_players == saved.header.options.num_players_excluding_gaia + 1
    assert (
        saved.header.raw
        + saved.rules.raw
        + saved.world.raw
        + b"".join(p.raw for p in saved.player_restores)
        == raw
    )


@pytest.mark.parametrize("section", ["header", "rules", "last_restore"])
def test_nested_version_failures_restore_the_whole_prefix_cursor(section: str) -> None:
    raw, spans, _, restores = restore_prefix_case("3p")
    damaged = bytearray(raw)
    at = {"header": 24, "rules": spans[1][1] - 8364, "last_restore": restores[-1]["start"]}[section]
    struct.pack_into("<I", damaged, at, 0xFFFFFFFF)
    reader = SaveReader(b"prefix!" + damaged, 7)
    with pytest.raises(SaveDecodeError):
        read_replay_restore_prefix(reader)
    assert reader.pos == 7 and reader.version == 0x44E666


def test_truncated_last_player_restoration_restores_the_whole_prefix() -> None:
    raw = restore_prefix_case("3p")[0]
    reader = SaveReader(b"prefix!" + raw[:-1], 7)
    with pytest.raises(SaveDecodeError):
        read_replay_restore_prefix(reader)
    assert reader.pos == 7
