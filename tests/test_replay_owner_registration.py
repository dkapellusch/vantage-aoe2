"""Actual whole-entry owner catalog sequences and logical API boundaries."""

from __future__ import annotations

import gzip
import hashlib
import json
from collections.abc import MutableMapping
from pathlib import Path
from typing import Any, cast

import pytest

from vantage.replay_owner_promotion import ReplayOwnerClassification
from vantage.replay_owner_registration import (
    ReplayOwnerCatalogState,
    add_replay_owner_counter6c,
    complete_replay_owner_object,
    register_replay_owner_object,
)

FIXTURE = Path(__file__).parent / "fixtures/native_owner_registration_54800.json.gz"
FIXTURE_SHA = "f1a0c57ef6b0321c4ee18fffd490a1d4cfecf9187daead166805c2845ecebb3f"


def _cases() -> list[dict[str, Any]]:
    raw = FIXTURE.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == FIXTURE_SHA
    value = json.loads(gzip.decompress(raw))
    assert value["schema"] == "native-owner-registration-54800-v1"
    return cast(list[dict[str, Any]], value["cases"])


def _state(endpoint: dict[str, Any]) -> ReplayOwnerCatalogState:
    counters = endpoint["counters_u32"]
    return ReplayOwnerCatalogState(
        {row["key"]: tuple(row["ids"]) for row in endpoint["groups"]},
        *(counters[key] for key in ("0x60", "0x64", "0x68", "0x6c")),
    )


def _signed(word: int) -> int:
    return word - 0x100000000 if word & 0x80000000 else word


@pytest.mark.parametrize("case", _cases(), ids=lambda case: case["name"])
def test_actual_original_sequence(case: dict[str, Any]) -> None:
    # Continue each sequence from the prior result, without resetting per call.
    state = _state(case["steps"][0]["before"])
    for step in case["steps"]:
        assert state == _state(step["before"])
        before = _state(step["before"])
        words = step["classification_words_u32"]
        classification = ReplayOwnerClassification(_signed(words[0]), _signed(words[1]), words[2])
        if step["kind"] == 1:
            result = register_replay_owner_object(state, step["object_id"], classification)
        elif step["kind"] == 2:
            result = complete_replay_owner_object(state, step["object_id"], classification)
        else:
            assert step["kind"] == 3
            low = step["delta_u32"] & 0xFFFF
            delta = low - 0x10000 if low & 0x8000 else low
            assert delta == step["delta_i16"]
            result = add_replay_owner_counter6c(state, delta)
        assert result == _state(step["after"])
        assert state == before
        state = result


def test_fixture_has_all_original_returns_and_complete_endpoint_storage() -> None:
    cases = _cases()
    steps = [step for case in cases for step in case["steps"]]
    assert len(cases) == 68 and len(steps) == 88
    assert [sum(step["kind"] == kind for step in steps) for kind in (1, 2, 3)] == [37, 38, 13]
    assert all(step["returned"] for step in steps)
    assert all(
        step[phase]["complete_raw_endpoint_bytes"] == 4352
        for step in steps
        for phase in ("before", "after")
    )


def test_missing_groups_follow_successful_allocation_logical_contract() -> None:
    # Missing-key allocation is source-derived; the native fixture prebacks keys.
    initial = ReplayOwnerCatalogState({}, 0, 0, 0, 0)
    registered = register_replay_owner_object(initial, 0, ReplayOwnerClassification(1649, 4, 1))
    assert dict(registered.groups) == {91649: (0,), 90904: (0,)}
    completed = complete_replay_owner_object(initial, 0, ReplayOwnerClassification(1649, 4, 1))
    assert dict(completed.groups) == {91649: (), 1649: (0,), 90904: (), 904: (0,)}
    assert dict(initial.groups) == {}


def test_zero_low_flags_byte_skips_missing_key_insertion() -> None:
    state = ReplayOwnerCatalogState({}, 1, 2, 3, 4)
    assert (
        complete_replay_owner_object(state, 0, ReplayOwnerClassification(900, 4, 0x80000100))
        is state
    )


@pytest.mark.parametrize("master_id", [900, 950, 999])
def test_reserved_registration_formatter_is_explicitly_unsupported(master_id: int) -> None:
    state = ReplayOwnerCatalogState({}, 0, 0, 0, 0)
    with pytest.raises(ValueError, match="formatting"):
        register_replay_owner_object(state, 0, ReplayOwnerClassification(master_id))
    assert dict(state.groups) == {}


def test_state_copies_the_mapping_and_exposes_immutable_groups() -> None:
    groups = {1: (2,)}
    state = ReplayOwnerCatalogState(groups, 0, 0, 0, 0)
    groups[1] = (3,)
    assert dict(state.groups) == {1: (2,)}
    with pytest.raises(TypeError):
        cast(MutableMapping[int, tuple[int, ...]], state.groups)[1] = ()


@pytest.mark.parametrize(
    "groups", [None, [], {-1: ()}, {True: ()}, {1: [2]}, {1: (True,)}, {1: (-1,)}]
)
def test_groups_require_raw_keys_and_immutable_raw_id_tuples(groups: Any) -> None:
    with pytest.raises(ValueError):
        ReplayOwnerCatalogState(groups, 0, 0, 0, 0)


@pytest.mark.parametrize("field", ["counter60", "counter64", "counter68", "counter6c"])
@pytest.mark.parametrize("value", [True, -1, 0x100000000, 1.5])
def test_counters_require_raw_u32_words(field: str, value: Any) -> None:
    counters = dict(counter60=0, counter64=0, counter68=0, counter6c=0)
    counters[field] = value
    with pytest.raises(ValueError):
        ReplayOwnerCatalogState({}, **counters)


@pytest.mark.parametrize("operation", [register_replay_owner_object, complete_replay_owner_object])
@pytest.mark.parametrize("value", [True, -1, 0x100000000, 1.5])
def test_object_id_is_a_raw_word(operation: Any, value: Any) -> None:
    with pytest.raises(ValueError):
        operation(ReplayOwnerCatalogState({}, 0, 0, 0, 0), value, ReplayOwnerClassification(1))


@pytest.mark.parametrize("operation", [register_replay_owner_object, complete_replay_owner_object])
def test_resolved_classification_is_required(operation: Any) -> None:
    with pytest.raises(ValueError):
        operation(ReplayOwnerCatalogState({}, 0, 0, 0, 0), 0, None)


@pytest.mark.parametrize("delta", [True, -32769, 32768, 0xFFFF, 1.5])
def test_delta_requires_an_already_decoded_signed16(delta: Any) -> None:
    with pytest.raises(ValueError):
        add_replay_owner_counter6c(ReplayOwnerCatalogState({}, 0, 0, 0, 0), delta)
