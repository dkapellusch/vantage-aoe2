"""Finite era-data projection, with independent literal row byte expectations."""

from __future__ import annotations

import hashlib
import json

import pytest

from vantage.replay_era_data import (
    ReplayEraData,
    ReplayEraDefinition,
    read_replay_era_data,
)


def raw(rows):
    return json.dumps(rows).encode()


def test_missing_and_empty_override_properties_are_explicit_empty_rows():
    data = read_replay_era_data(
        raw(
            [
                {"Name": "base", "Ages": [1, 2]},
                {"Name": "empty", "TechDisplayOverrides": []},
            ]
        )
    )
    assert data.research_rows("base") == data.research_rows("empty") == b""
    assert len(data.definitions) == 2


def test_five_dwords_use_exact_order_and_independent_missing_defaults():
    supplied = raw(
        [
            {
                "Name": "antiquity",
                "TechDisplayOverrides": [
                    {"TechId": 104, "NameId": 407089, "IconId": 150},
                    {
                        "TechId": 101,
                        "NameId": 407090,
                        "IconId": 151,
                        "DescriptionId": 408090,
                        "ExtendedDescriptionId": 428090,
                    },
                    {},
                ],
            }
        ]
    )
    data = read_replay_era_data(supplied)
    assert data.source_sha256 == hashlib.sha256(supplied).hexdigest()
    assert data.research_rows("antiquity") == bytes.fromhex(
        "680000003136060096000000fefffffffeffffff"
        "6500000032360600970000001a3a06003a880600"
        "fffffffffefffffffffffffffefffffffeffffff"
    )


def test_signed32_boundaries_are_serialized_as_exact_raw_dwords():
    data = read_replay_era_data(
        raw(
            [
                {
                    "Name": "limits",
                    "TechDisplayOverrides": [
                        {
                            "TechId": -(1 << 31),
                            "NameId": (1 << 31) - 1,
                            "IconId": -1,
                            "DescriptionId": 0,
                            "ExtendedDescriptionId": -2,
                        },
                    ],
                }
            ]
        )
    )
    assert data.research_rows("limits") == bytes.fromhex("00000080ffffff7fffffffff00000000feffffff")


def test_first_exact_case_sensitive_era_match_wins_in_source_order():
    data = read_replay_era_data(
        raw(
            [
                {"Name": "same"},
                {"Name": "same", "TechDisplayOverrides": [{}]},
            ]
        )
    )
    assert data.research_rows("same") == b""
    with pytest.raises(ValueError, match="exact match"):
        data.research_rows("SAME")
    with pytest.raises(ValueError, match="exact match"):
        data.research_rows("unknown")


@pytest.mark.parametrize(
    "document",
    [
        {},
        None,
        [1],
        [{}],
        [{"Name": 1}],
        [{"Name": ""}],
        [{"Name": "x\0y"}],
        [{"Name": "base", "TechDisplayOverrides": None}],
        [{"Name": "base", "TechDisplayOverrides": {}}],
        [{"Name": "base", "TechDisplayOverrides": [1]}],
    ],
)
def test_unadmitted_document_shapes_refuse(document):
    with pytest.raises(ValueError):
        read_replay_era_data(raw(document))


@pytest.mark.parametrize(
    "key",
    [
        "TechId",
        "NameId",
        "IconId",
        "DescriptionId",
        "ExtendedDescriptionId",
    ],
)
@pytest.mark.parametrize("value", [None, True, False, 1.5, "1", -(1 << 31) - 1, 1 << 31])
def test_only_actual_signed32_integer_fields_are_admitted(key, value):
    with pytest.raises(ValueError, match="signed32"):
        read_replay_era_data(raw([{"Name": "base", "TechDisplayOverrides": [{key: value}]}]))


def test_empty_era_array_does_not_invent_a_default_era():
    data = read_replay_era_data(b"[]")
    assert data.definitions == ()
    with pytest.raises(ValueError):
        data.research_rows("base")


@pytest.mark.parametrize("rows", [b"x", bytearray(20), None])
def test_explicit_rows_require_whole_immutable_twenty_byte_records(rows):
    with pytest.raises(ValueError):
        ReplayEraDefinition("base", rows)


def test_era_data_requires_explicit_ordered_definitions_and_digest():
    with pytest.raises(ValueError):
        ReplayEraData([], "0" * 64)
    with pytest.raises(ValueError):
        ReplayEraData((), "not-a-digest")
