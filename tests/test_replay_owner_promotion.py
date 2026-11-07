"""Original whole-entry promotion observations and logical API boundaries."""

from __future__ import annotations

import gzip
import json
from collections.abc import MutableMapping
from pathlib import Path
from typing import Any, cast

import pytest

from vantage.replay_owner_promotion import (
    ReplayOwnerClassification,
    promote_replay_owner_object,
)

FIXTURE = Path(__file__).parent / "fixtures/native_owner_promotion_54800.json.gz"


def _signed(word: int) -> int:
    return word - 0x100000000 if word & 0x80000000 else word


def _classification(words: list[int]) -> ReplayOwnerClassification:
    return ReplayOwnerClassification(_signed(words[0]), _signed(words[1]), words[2])


def _groups(entries: list[dict[str, Any]]) -> dict[int, tuple[int, ...]]:
    return {entry["key"]: tuple(entry["ids"]) for entry in entries}


def _cases() -> list[dict[str, Any]]:
    return cast(list[dict[str, Any]], json.loads(gzip.decompress(FIXTURE.read_bytes()))["cases"])


@pytest.mark.parametrize("case", _cases(), ids=lambda case: case["name"])
def test_original_whole_entry(case: dict[str, Any]) -> None:
    catalog = _groups(case["before"])
    before = dict(catalog)
    result = promote_replay_owner_object(
        catalog, case["object_id"], _classification(case["old"]), _classification(case["new"])
    )
    assert dict(result.groups) == _groups(case["after"])
    assert result.tracked is case["tracked_from_input"]
    assert catalog == before


def test_untracked_missing_key_retains_the_native_lookup_insertion() -> None:
    catalog = {2: (7,)}
    result = promote_replay_owner_object(
        catalog, 0, ReplayOwnerClassification(-2, 3), ReplayOwnerClassification(2, 4)
    )
    assert not result.tracked
    assert dict(result.groups) == {2: (7,), 0xFFFFFFFE: ()}
    assert catalog == {2: (7,)}


def test_creating_missing_groups_uses_ordinary_keys_and_allows_zero_id() -> None:
    result = promote_replay_owner_object(
        {1649: (0,), 900: (0,)},
        0,
        ReplayOwnerClassification(1649, 0, 1),
        ReplayOwnerClassification(1652, 1, 1),
    )
    assert result.tracked
    assert dict(result.groups) == {1649: (), 900: (), 1652: (0,), 901: (0,)}
    assert 91652 not in result.groups


def test_result_is_independent_of_subsequent_input_mapping_changes() -> None:
    catalog = {1: (9,)}
    result = promote_replay_owner_object(
        catalog, 9, ReplayOwnerClassification(1), ReplayOwnerClassification(2)
    )
    catalog[1] = (10,)
    assert dict(result.groups) == {1: (), 2: (9,)}
    with pytest.raises(TypeError):
        cast(MutableMapping[int, tuple[int, ...]], result.groups)[1] = ()


@pytest.mark.parametrize("value", [True, 1.5, -2147483649, 2147483648])
@pytest.mark.parametrize("field", ["master_id", "class_id"])
def test_classification_rejects_non_i32_fields(field: str, value: Any) -> None:
    words: dict[str, Any] = dict(master_id=1, class_id=-1)
    words[field] = value
    with pytest.raises(ValueError):
        ReplayOwnerClassification(**words)


@pytest.mark.parametrize("value", [True, -1, 0x100000000, 1.5])
def test_classification_flags_are_raw_u32(value: Any) -> None:
    with pytest.raises(ValueError):
        ReplayOwnerClassification(1, flags=value)


@pytest.mark.parametrize("value", [True, -1, 0x100000000, 1.5])
def test_object_ids_are_raw_words(value: Any) -> None:
    with pytest.raises(ValueError):
        promote_replay_owner_object(
            {}, value, ReplayOwnerClassification(1), ReplayOwnerClassification(2)
        )


@pytest.mark.parametrize(
    "catalog", [None, [], {-1: ()}, {True: ()}, {1: [2]}, {1: (True,)}, {1: (-1,)}]
)
def test_catalog_requires_raw_keys_and_ordered_raw_id_tuples(catalog: Any) -> None:
    with pytest.raises(ValueError):
        promote_replay_owner_object(
            catalog, 2, ReplayOwnerClassification(1), ReplayOwnerClassification(2)
        )


@pytest.mark.parametrize(
    "old,new", [(None, ReplayOwnerClassification(2)), (ReplayOwnerClassification(1), None)]
)
def test_classifications_must_be_explicit(old: Any, new: Any) -> None:
    with pytest.raises(ValueError):
        promote_replay_owner_object({}, 0, old, new)
