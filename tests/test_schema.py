"""vantage.schema: the cade_api state schema."""

from __future__ import annotations

import pytest

from vantage.schema import SCHEMA, Schema, load


def test_core_models_and_fields() -> None:
    world = SCHEMA.model_id("World")
    assert SCHEMA.name(world) == "World"
    spec = SCHEMA.field(world, SCHEMA.fid(world, "players"))
    assert spec is not None
    assert spec.kind == "map"
    assert SCHEMA.name(spec.model or -1) == "Player"
    attrs = SCHEMA.model_id("PlayerAttributes")
    food = SCHEMA.field(attrs, 0)
    assert food is not None and (food.name, food.wire) == ("food", "Float")
    tiles = SCHEMA.field(world, SCHEMA.fid(world, "mapTiles"))
    assert tiles is not None and tiles.contiguous_model == SCHEMA.model_id("MapTile")


def test_unknown_lookups() -> None:
    assert SCHEMA.field(SCHEMA.model_id("World"), 250) is None
    assert SCHEMA.name(999) == "Model999"
    with pytest.raises(KeyError):
        SCHEMA.model_id("NoSuchModel")
    with pytest.raises(KeyError):
        SCHEMA.fid(SCHEMA.model_id("World"), "nope")


def test_narrow_respects_kind_and_seen_fields() -> None:
    entity = SCHEMA.model_id("Entity")
    # Field 23 means different things on different Entity subtypes.
    obj = SCHEMA.narrow(entity, 23, frozenset({"object"}))
    assert obj == SCHEMA.model_id("BuildingEntity")
    scalar = SCHEMA.narrow(entity, 23, frozenset({"scalar"}))
    assert scalar is not None and scalar != obj
    # Requiring an object field 23 *and* the building-only field 33 still lands on BuildingEntity.
    assert SCHEMA.narrow(entity, 23, frozenset({"object"}), seen=[33]) == obj
    assert SCHEMA.narrow(entity, 250) is None


def test_load_is_stable_and_constructs_from_dict() -> None:
    again = load()
    assert (
        again.fields(again.model_id("Player")).keys()
        == SCHEMA.fields(SCHEMA.model_id("Player")).keys()
    )
    tiny = Schema(
        {
            "models": {
                "0": {
                    "name": "Root",
                    "fields": {"0": {"name": "x", "kind": "scalar", "type": "UInt8"}},
                }
            }
        }
    )
    assert tiny.fid(0, "x") == 0
