"""vantage.replay: DE .aoe2record lobby header + game clock.

The two fixtures are real build-54800 replays cut down to stay small: the
first few KB of the decompressed header (re-deflated), the start of the body
(through the first 360-byte checksum sync in the 3-player one) and the real
final action + post-game record. Ground truth is from the live game stream.
"""

from __future__ import annotations

import gzip
import json
import struct
import zlib
from pathlib import Path

import pytest

from vantage.gamedata import GameData
from vantage.replay import ReplayError, load_map_names, read_replay

FIXTURES = Path(__file__).parent / "fixtures"


def _unpack(tmp_path: Path, name: str) -> Path:
    out = tmp_path / name.removesuffix(".gz")
    out.write_bytes(gzip.decompress((FIXTURES / name).read_bytes()))
    return out


@pytest.fixture
def three(tmp_path: Path) -> Path:
    return _unpack(tmp_path, "replay_3p_54800.aoe2record.gz")


@pytest.fixture
def six(tmp_path: Path) -> Path:
    return _unpack(tmp_path, "replay_6p_54800.aoe2record.gz")


def _header(path: Path) -> bytes:
    data = path.read_bytes()
    end = struct.unpack_from("<I", data)[0]
    return zlib.decompressobj(-15).decompress(data[8:end])


def _replay(tmp_path: Path, header: bytes, body: bytes, next_chapter: int = 0) -> Path:
    comp = zlib.compressobj(9, zlib.DEFLATED, -15)
    packed = comp.compress(header) + comp.flush()
    path = tmp_path / "synthetic.aoe2record"
    path.write_bytes(struct.pack("<II", 8 + len(packed), next_chapter) + packed + body)
    return path


def _sync(ms: int) -> bytes:
    return struct.pack("<II", 2, ms)


def _action(game_ms: int, payload: bytes = b"\x0b\x02\x01\x00\x00") -> bytes:
    return struct.pack("<II", 1, len(payload)) + payload + struct.pack("<I", game_ms)


META = struct.pack("<8I", 5, 500, 0, 1, 1, 0, 0, 0)


def test_three_player_ground_truth(three: Path) -> None:
    info = read_replay(three)
    assert info.warnings == ()
    assert info.version == "VER 9.4"
    assert info.save_version == 68.9
    assert info.build == 54800
    assert info.compatible == "VER 9.4 / save 68.9 / build 54800"
    assert info.started_at == 1791858425
    assert info.map_id == 216
    assert info.map_size == 144
    assert info.rms_file == "ZN@HyperRandomExtreme.rms"
    assert (info.difficulty, info.game_type, info.speed_name) == ("Extreme", "Random Map", "Normal")
    assert (info.population, info.num_players, info.treaty_minutes) == (200, 3, 0)
    assert info.multiplayer is False and info.ranked is False
    assert (info.lock_teams, info.turbo, info.all_techs, info.random_positions) == (
        False,
        False,
        False,
        False,
    )
    assert info.handicap is True

    p1, p2, p3 = info.players
    assert (p1.number, p1.name, p1.civ_id, p1.color_id, p1.is_human) == (1, "Shazama", 53, 3, True)
    assert p1.profile_id == 4791747 and p1.ai_script == ""
    assert (p2.name, p2.civ_id, p2.color_id, p2.ai_script, p2.custom_ai) == (
        "Knut the Great",
        62,
        0,
        "PromiDE",
        False,
    )
    assert (p3.name, p3.civ_id, p3.color_id, p3.ai_script, p3.custom_ai) == (
        "Immortal v0d10f",
        12,
        1,
        "Immortal v0d10f",
        True,
    )
    assert [p.team for p in info.players] == [1, 2, 3]
    assert all(p.handicap == 100 for p in info.players)
    # The post-game record carries the human's own ladders (rank -1: unranked game).
    assert info.players[0].ratings == ((3, -1, 1345), (4, -1, 1101))
    assert [p.elo for p in info.players] == [1101, None, None]

    # Real post-game record: 2494.2 s of game time; the excerpt's syncs (including
    # one checksum-carrying sync) cover 6.5 s.
    assert info.duration_ms == 2494234
    assert info.recorded_ms == 6543
    assert info.has_postgame and info.chapters == 0


def test_six_player_ground_truth(six: Path) -> None:
    info = read_replay(six)
    assert info.warnings == ()
    got = [(p.name, p.civ_id, p.color_id, p.ai_script) for p in info.players]
    assert got == [
        ("Shazama", 60, 3, ""),
        ("Yelu Xian", 53, 0, "PromiDE"),
        ("Immortal v0d10f", 12, 1, "Immortal v0d10f"),
        ("Sultan Mansur Shah", 29, 2, "PromiDE"),
        ("Immortal v0d10f", 16, 4, "Immortal v0d10f"),
        ("Guacolda", 58, 5, "PromiDE"),
    ]
    # A custom script's lobby persona is a random leader; the game shows the script.
    assert info.players[2].ai_name == "Jamukha"
    assert [p.team for p in info.players] == [1, 0, 0, 0, 0, 0]
    assert info.map_size == 200 and info.num_players == 6
    assert info.duration_ms == 7492806 and info.has_postgame


def test_to_json_is_serializable(three: Path) -> None:
    doc = read_replay(three).to_json()
    assert json.loads(json.dumps(doc)) == doc
    assert doc["players"][0]["name"] == "Shazama"
    assert doc["compatible"].startswith("VER 9.4")


def test_without_duration_skips_body(three: Path) -> None:
    info = read_replay(three, with_duration=False)
    assert info.duration_ms is None and info.recorded_ms is None
    assert len(info.players) == 3


def test_map_names_resolve_and_custom_fallback(three: Path) -> None:
    assert read_replay(three, False, map_names={216: "Arabian Desert"}).map_name == "Arabian Desert"
    custom = read_replay(three, False, map_names={9: "Arabia"})
    assert custom.custom_map and custom.map_name == "ZN@HyperRandomExtreme"
    assert read_replay(three, False).map_name is None


def test_game_version_from_filename(three: Path, tmp_path: Path) -> None:
    named = tmp_path / "SP Replay v101.103.54800.0 @2026.10.12 192705.aoe2record"
    named.write_bytes(three.read_bytes())
    assert read_replay(named, False).game_version == "101.103.54800.0"
    assert read_replay(three, False).game_version is None


def test_truncated_header_keeps_what_was_read(three: Path, tmp_path: Path) -> None:
    header = _header(three)
    cut = header.index(b"Knut the Great")  # inside player 2
    info = read_replay(_replay(tmp_path, header[:cut], META + _sync(10)))
    assert info.map_id == 216 and info.population == 200
    assert [p.name for p in info.players] == ["Shazama"]
    assert any(w.startswith("players:") for w in info.warnings)
    assert info.duration_ms == 10


def test_lost_lobby_sync_is_a_warning(three: Path, tmp_path: Path) -> None:
    header = bytearray(_header(three))
    sep = header.index(struct.pack("<I", 155555))
    header[sep] ^= 0xFF
    info = read_replay(_replay(tmp_path, bytes(header), META), with_duration=False)
    assert info.version == "VER 9.4" and info.map_id == 216
    assert info.players == ()
    assert any("separator" in w for w in info.warnings)


def test_resumed_recording_anchors_on_action_time(three: Path, tmp_path: Path) -> None:
    body = META + _sync(100) + _action(5_000_100) + _sync(400) + _sync(500)
    info = read_replay(_replay(tmp_path, _header(three), body))
    assert info.recorded_ms == 1000
    assert info.duration_ms == 5_000_000 + 1000
    assert not info.has_postgame


def test_chapter_is_skipped(three: Path, tmp_path: Path) -> None:
    header = _header(three)
    probe = _replay(tmp_path, header, b"")
    body_at = probe.stat().st_size
    chapter_at = body_at + len(META) + 8
    junk = b"\xff" * 40  # stands in for the chapter's compressed save
    resume = chapter_at + 8 + len(junk)
    body = META + _sync(250) + struct.pack("<II", resume, 0) + junk + _sync(750)
    info = read_replay(_replay(tmp_path, header, body, next_chapter=chapter_at))
    assert info.warnings == ()
    assert (info.recorded_ms, info.chapters) == (1000, 1)


def test_unknown_operation_keeps_partial_clock(three: Path, tmp_path: Path) -> None:
    body = META + _sync(300) + struct.pack("<I", 99) + _sync(700)
    info = read_replay(_replay(tmp_path, _header(three), body))
    assert info.duration_ms == 300
    assert any("unknown operation 99" in w for w in info.warnings)


def test_chat_viewlock_and_checksum_sync(three: Path, tmp_path: Path) -> None:
    chat = json.dumps({"player": 1, "message": "gg"}).encode()
    body = (
        META
        + struct.pack("<IiI", 4, -1, len(chat))
        + chat
        + struct.pack("<IffI", 3, 45.0, 29.0, 1)
        + _sync(20)
        + struct.pack("<I", 0)
        + b"\x01" * 356
        + _sync(30)
        + struct.pack("<II", 6, 50)
        + b"\x00" * 62
    )
    info = read_replay(_replay(tmp_path, _header(three), body))
    assert info.warnings == ()
    assert (info.recorded_ms, info.duration_ms, info.has_postgame) == (50, 50, True)


@pytest.mark.parametrize(
    "raw",
    [
        b"",
        b"\x01\x02\x03",
        struct.pack("<II", 0xFFFFFFF0, 0) + b"x" * 32,
        struct.pack("<II", 40, 0) + b"\xff" * 32,
    ],
)
def test_not_a_replay(tmp_path: Path, raw: bytes) -> None:
    path = tmp_path / "bad.aoe2record"
    path.write_bytes(raw)
    with pytest.raises(ReplayError):
        read_replay(path)


def test_no_ver_tag(tmp_path: Path) -> None:
    with pytest.raises(ReplayError, match="VER"):
        read_replay(_replay(tmp_path, b"NOPE" * 20, META))


def test_missing_file(tmp_path: Path) -> None:
    with pytest.raises(ReplayError):
        read_replay(tmp_path / "absent.aoe2record")


def test_load_map_names(tmp_path: Path) -> None:
    dat = tmp_path / "resources" / "_common" / "dat"
    dat.mkdir(parents=True)
    maps = {
        "map_list": [
            {"storage_id": 9, "name_string_id": 10875, "script_filename": "Arabia.rms"},
            {"storage_id": 216, "name_string_id": 99999, "script_filename": "Arabian Desert.rms"},
        ]
    }
    (dat / "maps.json").write_text(json.dumps(maps), encoding="utf-8")
    kv = tmp_path / "resources" / "en" / "strings" / "key-value"
    kv.mkdir(parents=True)
    (kv / "key-value-strings-utf8.txt").write_text('10875 "Arabia"\n', encoding="utf-8")
    assert load_map_names(GameData(tmp_path)) == {9: "Arabia", 216: "Arabian Desert"}
    assert load_map_names(GameData(None)) == {}
    assert load_map_names(GameData(tmp_path / "nowhere")) == {}


def _resign(game_ms: int, player: int) -> bytes:
    return _action(game_ms, bytes([0x0B, player, 1, 0, 0]))


def test_winner_is_the_side_left_after_resignations(three: Path, tmp_path: Path) -> None:
    body = META + _sync(1000) + _resign(1000, 3) + _sync(1000) + _resign(2000, 2)
    info = read_replay(_replay(tmp_path, _header(three), body + struct.pack("<II", 6, 2000)))
    assert info.resigned == ((3, False, 1000), (2, False, 2000))
    assert info.winners == (1,)
    assert info.to_json()["winners"] == [1]
    assert info.to_json()["resigned"] == [[3, False, 1000], [2, False, 2000]]


def test_no_winner_without_an_ending_or_with_two_sides_left(three: Path, tmp_path: Path) -> None:
    unfinished = read_replay(_replay(tmp_path, _header(three), META + _resign(1000, 3)))
    assert unfinished.resigned == ((3, False, 1000),) and unfinished.winners == ()
    one_left = META + _resign(1000, 3) + struct.pack("<II", 6, 1000)
    two_standing = read_replay(_replay(tmp_path, _header(three), one_left))
    assert two_standing.winners == ()  # players 1 and 2 are both still in the game
    assert read_replay(_replay(tmp_path, _header(three), META), with_duration=False).winners == ()


FLAGS = (
    "lock_teams",
    "team_positions",
    "shared_exploration",
    "handicap",
    "lock_speed",
    "cheats",
    "turbo",
    "all_techs",
)


@pytest.mark.parametrize(
    ("fixture", "expected"),
    [
        # Two real Return of Rome lobbies (build 54800): the game's defaults, then
        # the same lobby with all eight checkboxes inverted on the lobby screen.
        (
            "replay_ror_defaults_54800.header.gz",
            (False, True, False, False, False, True, False, False),
        ),
        ("replay_ror_flipped_54800.header.gz", (True, False, True, True, True, False, True, True)),
    ],
)
def test_lobby_flags_match_the_lobby_screen(
    tmp_path: Path, fixture: str, expected: tuple[bool, ...]
) -> None:
    header = gzip.decompress((FIXTURES / fixture).read_bytes())
    info = read_replay(_replay(tmp_path, header, META), with_duration=False)
    assert tuple(getattr(info, k) for k in FLAGS) == expected
    assert (info.reveal_map_id, info.victory_type_id, info.population) == (0, 9, 200)
    assert not info.multiplayer and not info.ranked


def test_ranked_multiplayer_flags_ratings_and_winner(tmp_path: Path) -> None:
    # A public ranked 1v1 (build 54800, names replaced): its lobby header and
    # the real post-game record, after a resignation by player 2.
    header = gzip.decompress((FIXTURES / "replay_mp_ranked_54800.header.gz").read_bytes())
    post = (FIXTURES / "replay_mp_ranked_54800.postgame.bin").read_bytes()
    final_ms = struct.unpack_from("<I", post, 4)[0]
    body = META + _sync(1000) + _resign(final_ms, 2) + post
    info = read_replay(_replay(tmp_path, header, body))
    assert info.multiplayer is True and info.ranked is True
    assert [p.name for p in info.players] == ["Player_A", "Player_BBBBB"]
    assert all(p.is_human for p in info.players)
    # Ratings and ladder ranks as the public ladder showed them for this match.
    assert [p.elo for p in info.players] == [3007, 2025]
    assert info.players[0].ratings == ((3, 1, 3007),)
    assert info.players[1].ratings == ((3, 653, 2025),)
    assert info.winners == (1,)
    assert info.duration_ms == final_ms


def test_single_player_ladders_give_the_humans_ratings(tmp_path: Path, three: Path) -> None:
    # Unranked games still record the human's ladders (rank -1): 1v1 and team.
    post = (
        struct.pack("<II", 6, 5000)
        + struct.pack("<III", 4, 1, 2)
        + struct.pack("<IBBI", 3, 1, 0, 1)
        + struct.pack("<iii", 0, -1, 1345)
        + struct.pack("<IBBI", 4, 1, 0, 1)
        + struct.pack("<iii", 0, -1, 1101)
        + bytes(24)
    )
    info = read_replay(_replay(tmp_path, _header(three), META + post))
    shazama = info.players[0]
    assert shazama.ratings == ((3, -1, 1345), (4, -1, 1101))
    assert shazama.elo == 1101  # a three-player game: the team ladder
    assert info.players[1].elo is None
