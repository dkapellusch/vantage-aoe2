"""Complete native player sections joined without boundary scans."""

from __future__ import annotations

import gzip
import hashlib
import json
import struct
from pathlib import Path

import pytest

from vantage.replay_binary import SaveDecodeError, SaveReader
from vantage.replay_initial_player import read_initial_player

FIXTURE = Path(__file__).parent / "fixtures/native_saved_initial_players_54800.json.gz"


def _fixture():
    return json.loads(gzip.decompress(FIXTURE.read_bytes()))


def test_complete_players_match_native_entity_sets_and_following_factory_boundaries() -> None:
    fixture = _fixture()
    oracle = struct.Struct(fixture["oracle_struct"])
    assert len(fixture["cases"]) == 11
    total = 0
    for case in fixture["cases"]:
        raw, following = bytes.fromhex(case["raw_hex"]), bytes.fromhex(case["next_prefix_hex"])
        reader = SaveReader(raw + following)
        player = read_initial_player(reader, case["num_players"], player_id=case["player_id"])
        assert player.raw == raw
        assert reader.pos == len(raw) == case["end"] - case["start"]
        assert reader.data[reader.pos :] == following
        assert following[0] == case["next_factory"]
        assert player.header.factory_type == case["factory_type"]
        assert player.header.player_id == case["player_id"]
        assert len(player.masters.masters) == case["masters"]
        assert (
            player.header.raw
            + player.prefix.raw
            + (player.player_ai.raw if player.player_ai else b"")
            + (player.ai_continuation.raw if player.ai_continuation else b"")
            + (player.gaia_extension.raw if player.gaia_extension else b"")
            + player.masters.raw
            + b"\x0b"
            + player.visibility.raw
            + player.object_lists.raw
            == raw
        )
        assert player.visibility.player_id == case["player_id"]
        digest = hashlib.sha256()
        ids = set()
        for name, count in zip(
            ("ordinary", "sleeping", "dopple"), case["object_counts"], strict=True
        ):
            objects = getattr(player.object_lists, name).objects
            assert len(objects) == count
            for obj in objects:
                key = case["id_aliases"].get(str(obj.object_id), obj.object_id)
                assert key not in ids
                ids.add(key)
                hp = case["hp_projection"].get(str(key), obj.hp)
                if hp != obj.hp:
                    assert (obj.hp, hp) == (-1, 0)
                digest.update(
                    oracle.pack(
                        key,
                        obj.owner,
                        obj.master_id,
                        obj.sprite_id,
                        hp,
                        *obj.position[:2],
                        obj.held_resource_type,
                        obj.held_resource_amount,
                        name == "sleeping",
                        name == "dopple",
                    )
                )
            total += len(objects)
        assert digest.hexdigest() == case["native_entity_digest"]
    assert total == 19257


def test_truncated_computer_prefix_rolls_back_entire_player() -> None:
    for case in _fixture()["ai_prefixes"]:
        reader = SaveReader(b"prefix" + bytes.fromhex(case["raw_hex"]), 6)
        with pytest.raises(SaveDecodeError):
            read_initial_player(reader, case["num_players"], player_id=2)
        assert reader.pos == 6


def test_failure_in_final_trailer_restores_the_entire_player() -> None:
    case = _fixture()["cases"][1]
    raw = bytes.fromhex(case["raw_hex"])
    reader = SaveReader(b"prefix" + raw[:-1], 6)
    with pytest.raises(SaveDecodeError):
        read_initial_player(reader, case["num_players"])
    assert reader.pos == 6
