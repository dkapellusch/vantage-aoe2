"""Structural records verified against independent t=0 native entities."""

from __future__ import annotations

import gzip
import json
import struct
from collections import Counter
from pathlib import Path

import pytest

from vantage.replay_binary import SaveDecodeError, SaveReader
from vantage.replay_objects import UnsupportedSavedObject, read_saved_object

FIXTURE = Path(__file__).parent / "fixtures" / "native_saved_object_prefixes_54800.json.gz"
COMPONENT_FIXTURE = (
    Path(__file__).parent / "fixtures" / "native_saved_object_components_54800.json.gz"
)


def _samples():
    return json.loads(gzip.decompress(FIXTURE.read_bytes()))["samples"]


def test_contiguous_records_against_independent_game_entities() -> None:
    total = 0
    resource_objects = sounds = zero_ids = 0
    for sample in _samples():
        cases = sample["cases"]
        reader = SaveReader(b"".join(bytes.fromhex(c["raw_hex"]) for c in cases))
        for case in cases:
            start = reader.pos
            obj = read_saved_object(reader)
            expected = case["expected"]
            assert {
                "owner": obj.owner,
                "master_id": obj.master_id,
                "sprite_id": obj.sprite_id,
                "hp": obj.hp,
                "xy": list(obj.position[:2]),
                "held_resource_type": obj.held_resource_type,
                "held_resource_amount": obj.held_resource_amount,
            } == expected
            assert obj.raw == bytes.fromhex(case["raw_hex"])
            assert obj.object_id == case["serialized_id"]
            assert reader.pos - start == case["end_offset"] - case["offset"]
            total += 1
            resource_objects += obj.held_resource_amount > 0
            sounds += sum(len(group) for group in obj.sounds)
            zero_ids += obj.object_id == 0
        assert reader.remaining == 0
    assert total == 8161
    assert resource_objects > 100
    assert sounds > 100
    assert zero_ids == 2


def test_every_truncation_of_a_real_record_fails_without_consuming_it() -> None:
    case = _samples()[0]["cases"][0]
    raw = bytes.fromhex(case["raw_hex"])
    for length in range(len(raw)):
        reader = SaveReader(b"prefix" + raw[:length], len(b"prefix"))
        with pytest.raises(SaveDecodeError):
            read_saved_object(reader)
        assert reader.pos == len(b"prefix")


def test_unknown_type_is_not_resynchronized_to_a_later_object() -> None:
    raw = bytes.fromhex(_samples()[0]["cases"][0]["raw_hex"])
    reader = SaveReader(bytes([90]) + raw[1:] + raw)
    with pytest.raises(UnsupportedSavedObject, match="type group 90"):
        read_saved_object(reader)
    assert reader.pos == 0


def test_unverified_save_version_stops_at_the_record_boundary() -> None:
    raw = bytes.fromhex(_samples()[0]["cases"][0]["raw_hex"])
    reader = SaveReader(raw, version=0x450000)
    with pytest.raises(UnsupportedSavedObject, match="version"):
        read_saved_object(reader)
    assert reader.pos == 0


def test_combat_parent_prefixes_against_native_entities_and_read_boundaries() -> None:
    """339 actual unit/building prefixes, explicitly exercised as parent50.

    The fixture is clipped at the recovered combat boundary and its type byte
    is changed only in this test. It does not pretend that derived unit and
    building records end there. Native snapshot fields are independent of the
    saved-reader recipes used to establish the intermediate boundaries.
    """
    samples = json.loads(gzip.decompress(COMPONENT_FIXTURE.read_bytes()))["samples"]
    total = sprite_nodes = normalized_hp = 0
    for sample in samples:
        for case in sample["cases"]:
            original = bytes.fromhex(case["raw_prefix_hex"])
            assert original[0] == case["kind"]
            raw = bytes([50]) + original[1:]
            reader = SaveReader(raw + b"trailing data")
            obj = read_saved_object(reader)
            native = case["native"]
            assert reader.pos == len(raw) == case["combat_end"] - case["offset"]
            assert obj.raw == raw
            assert obj.object_id == case["id"]
            assert obj.master_id == native["master"] == case["master"]
            assert obj.owner == native["owner"]
            assert obj.sprite_id == native["sprite"]
            assert list(obj.position[:2]) == native["xy"]
            assert obj.held_resource_type == native["held_type"]
            assert obj.held_resource_amount == native["held_amount"]
            # Eight invisible helpers save HP=-1; native emits default HP=0.
            # Retain the saved value rather than quietly rewriting it.
            if obj.hp != native["hp"]:
                assert (obj.hp, native["hp"]) == (-1, 0)
                normalized_hp += 1
            assert obj.movement is not None
            assert obj.action is not None
            assert obj.combat is not None
            assert len(obj.movement.raw) == case["moving_end"] - case["common_end"]
            assert len(obj.action.raw) == case["action_end_or_first_payload"] - case["moving_end"]
            assert len(obj.combat.raw) == case["combat_end"] - case["action_end_or_first_payload"]
            for fields, expected in (
                (obj.movement.fields, case["moving"]),
                (obj.action.fields, case["action"]),
                (obj.combat.fields, case["combat"]),
            ):
                assert all(value == expected[hex(offset)] for offset, value in fields.items())
            assert obj.movement.paths_wire_order == ()
            assert obj.movement.waypoints == ()
            assert obj.action.object_map == ()
            assert obj.combat.recharge_map_wire_order == ()
            assert obj.combat.transform_back_master_id == case["combat"]["transform_back_master_id"]
            sprite_nodes += len(obj.sprites)
            total += 1
    assert (total, normalized_hp) == (339, 8)
    assert sprite_nodes > 300


def test_every_truncation_of_native_combat_parent_rolls_back() -> None:
    case = json.loads(gzip.decompress(COMPONENT_FIXTURE.read_bytes()))["samples"][0]["cases"][0]
    original = bytes.fromhex(case["raw_prefix_hex"])
    raw = bytes([50]) + original[1:]
    for length in range(len(raw)):
        reader = SaveReader(b"prefix" + raw[:length], 6)
        with pytest.raises(SaveDecodeError):
            read_saved_object(reader)
        assert reader.pos == 6


def test_complete_zero_ai_units_end_at_independently_captured_next_objects() -> None:
    samples = json.loads(gzip.decompress(COMPONENT_FIXTURE.read_bytes()))["samples"]
    total = 0
    for sample in samples:
        for case in sample["zero_ai_units"]:
            raw = bytes.fromhex(case["raw_hex"])
            following = bytes.fromhex(case["next_bytes"])
            reader = SaveReader(raw + following)
            obj = read_saved_object(reader)
            assert obj.type_group == 70
            assert obj.object_id == case["id"]
            assert obj.raw == raw
            assert reader.pos == len(raw) == case["unit_end"] - case["offset"]
            assert reader.data[reader.pos :] == following
            assert case["next_capture_prefix_matches_at_computed_end"]
            assert obj.unit is not None
            assert obj.unit.ai_type == 0
            assert len(obj.unit.raw) == case["unit"]["extension_bytes"] == 166
            assert obj.unit.stingers == ()
            assert obj.unit.powerup_map_wire_order == ()
            assert obj.unit.unpack_timer is None
            expected = {**case["unit"], **case["unit"]["post_ai"]}
            assert all(value == expected[hex(offset)] for offset, value in obj.unit.fields.items())
            total += 1
    assert total == 56


def test_complete_unit_and_building_records_reach_native_boundaries() -> None:
    samples = json.loads(gzip.decompress(COMPONENT_FIXTURE.read_bytes()))["samples"]
    kinds: Counter[int] = Counter()
    boundaries: Counter[str] = Counter()
    for sample in samples:
        for case in sample["cases"]:
            raw = bytes.fromhex(case["raw_complete_hex"])
            following = bytes.fromhex(case["next_prefix_hex"])
            reader = SaveReader(raw + following)
            obj = read_saved_object(reader)
            assert reader.pos == len(raw) == case["complete_end"] - case["offset"]
            assert obj.raw == raw
            assert obj.object_id == case["id"]
            assert obj.unit is not None
            assert (obj.unit.ai is None) == (obj.unit.ai_type == 0)
            if obj.type_group == 80:
                assert obj.building is not None
                assert len(obj.building.raw) == 154
                assert obj.building.production_queue == ()
                assert all(not entries for entries in obj.building.arrays.values())
            else:
                assert obj.building is None
            if case["boundary"] == "list_terminator":
                assert following[0] == 0
            else:
                assert struct.unpack_from("<I", following, 18)[0] == case["next_native_id"]
            kinds[obj.type_group] += 1
            boundaries[case["boundary"]] += 1
    assert kinds == {70: 285, 80: 54}
    assert boundaries == {"next_native_entity": 338, "list_terminator": 1}


@pytest.mark.parametrize("kind", [70, 80])
def test_every_truncation_of_a_complete_native_unit_or_building_rolls_back(kind: int) -> None:
    cases = json.loads(gzip.decompress(COMPONENT_FIXTURE.read_bytes()))["samples"][0]["cases"]
    raw = bytes.fromhex(next(c for c in cases if c["kind"] == kind)["raw_complete_hex"])
    for length in range(len(raw)):
        reader = SaveReader(b"prefix" + raw[:length], 6)
        with pytest.raises(SaveDecodeError):
            read_saved_object(reader)
        assert reader.pos == 6
