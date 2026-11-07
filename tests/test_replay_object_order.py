"""Native signed-ID array snapshots and effective restore-list classification."""

from __future__ import annotations

import gzip
import hashlib
import json
from dataclasses import replace
from functools import cache
from pathlib import Path

import pytest

from vantage.replay_binary import SaveReader
from vantage.replay_object_lists import (
    SavedObjectList,
    SavedPlayerObjectLists,
    SavedPlayerObjectTrailer,
)
from vantage.replay_object_order import (
    insert_runtime_object,
    restore_runtime_object_lists,
    runtime_object_list_name,
    signed_object_id,
)
from vantage.replay_objects import SavedObject, read_saved_object

FIXTURE = Path(__file__).parent / "fixtures" / "native_runtime_object_order_54800.json.gz"


@cache
def _fixture():
    return json.loads(gzip.decompress(FIXTURE.read_bytes()))


def _object(raw_id: int = 0, flags: tuple[int, ...] = (2, 0, 0, 0)) -> SavedObject:
    template = read_saved_object(SaveReader(bytes.fromhex(_fixture()["saved_object_hex"])))
    return replace(template, object_id=raw_id, flags=flags)


def _saved(*wire: tuple[SavedObject, ...]) -> SavedPlayerObjectLists:
    assert len(wire) == 3
    lists = tuple(SavedObjectList(0, 0, 0, 0, group, 0, b"") for group in wire)
    trailer = SavedPlayerObjectTrailer(0, 0, 0, (), 0, 0, 0, 0, 0, 0, 0, b"")
    return SavedPlayerObjectLists(0, 0, *lists, trailer, b"")


def test_all_original_native_insert_array_and_pointer_observations() -> None:
    fixture = _fixture()
    assert fixture["rea_evidence_id"] == (
        "ev_19579651326e2820ddbc6f83200438bfb4233a85781bf75b51a72b884b47e432"
    )
    assert fixture["original_instructions_changed"] is False
    assert fixture["executable_holes"] == "INT3"
    assert fixture["context"]["capacity"] == 129
    observations = copies = 0
    template = _object()
    for case in fixture["cases"]:
        ordered: tuple[SavedObject, ...] = ()
        inputs = tuple(replace(template, object_id=word) for word in case["ids"])
        for obj, native in zip(inputs, case["native"], strict=True):
            ordered = insert_runtime_object(ordered, obj)
            assert [item.object_id for item in ordered] == [row[0] for row in native["entries"]]
            for item, (_, ordinal) in zip(ordered, native["entries"], strict=True):
                assert item is inputs[ordinal]
            observations += 1
            copies += native["copy_calls"]
    assert len(fixture["cases"]) == 854
    assert observations == 18120
    assert copies == 6513


@pytest.mark.parametrize(
    ("raw", "signed"),
    [(0, 0), (0xFFFFFFFF, -1), (0x80000000, -(1 << 31)), (0x7FFFFFFF, (1 << 31) - 1)],
)
def test_ordering_uses_raw_signed_native_member(raw: int, signed: int) -> None:
    assert signed_object_id(raw) == signed


@pytest.mark.parametrize("bad", [-50, -1, 1 << 32, True, 1.5])
def test_synthetic_ids_and_non_u32_inputs_are_rejected(bad) -> None:
    with pytest.raises(ValueError):
        signed_object_id(bad)


def test_duplicate_keeps_existing_identity_and_returns_same_tuple() -> None:
    first = _object(17)
    duplicate = replace(first, hp=123.0)
    ordered = (first,)
    assert insert_runtime_object(ordered, duplicate) is ordered
    assert ordered[0] is first


@pytest.mark.parametrize("ids", [(2, 1), (1, 1), (0, 0xFFFFFFFF)])
def test_insertion_requires_signed_sorted_unique_input(ids) -> None:
    ordered = tuple(_object(word) for word in ids)
    with pytest.raises(ValueError):
        insert_runtime_object(ordered, _object(3))
    assert tuple(obj.object_id for obj in ordered) == ids


@pytest.mark.parametrize("sleeping", [0, 1, 255])
@pytest.mark.parametrize("dopple", [0, 1, 255])
@pytest.mark.parametrize("override", [0, 1, 255])
def test_effective_classification_preserves_four_saved_bytes(sleeping, dopple, override) -> None:
    obj = _object(flags=(2, sleeping, dopple, override))
    expected = "sleeping" if sleeping and not override else "dopple" if dopple else "ordinary"
    assert runtime_object_list_name(obj) == expected
    assert obj.flags == (2, sleeping, dopple, override)


@pytest.mark.parametrize("flags", [(), (0, 0, 0), (0, 0, 0, 256), (0, -1, 0, 0)])
def test_invalid_flag_members_are_not_silently_coerced(flags) -> None:
    with pytest.raises(ValueError):
        runtime_object_list_name(_object(flags=flags))


def test_restore_classifies_before_sorting_and_deduplicates_only_per_list() -> None:
    # Wire-list position does not force destination; byte18b cancels sleeping.
    first = _object(2)
    cancelled = _object(1, (2, 255, 0, 1))
    dopple = _object(0xFFFFFFFF, (2, 1, 1, 255))
    sleeper = _object(0, (2, 1, 1, 0))
    duplicate = replace(first, hp=100.0)
    same_id_other_list = _object(2, (2, 1, 0, 0))
    saved = _saved((first, cancelled, dopple), (sleeper, duplicate), (same_id_other_list,))
    before = saved.ordinary.objects, saved.sleeping.objects, saved.dopple.objects
    runtime = restore_runtime_object_lists(saved)
    assert runtime.ordinary == (cancelled, first)
    assert runtime.ordinary[-1] is first
    assert runtime.sleeping == (sleeper, same_id_other_list)
    assert runtime.dopple == (dopple,)
    assert runtime.update_order == (*runtime.ordinary, *runtime.sleeping, *runtime.dopple)
    assert before == (saved.ordinary.objects, saved.sleeping.objects, saved.dopple.objects)


def test_real_native_object_sample_is_unmodified() -> None:
    raw = bytes.fromhex(_fixture()["saved_object_hex"])
    obj = read_saved_object(SaveReader(raw))
    assert hashlib.sha256(raw).hexdigest() == _fixture()["saved_object_sha256"]
    assert obj.raw == raw
    assert obj.object_id == 0
    assert runtime_object_list_name(obj) == "ordinary"


def test_empty_lists_restore_without_allocations() -> None:
    runtime = restore_runtime_object_lists(_saved((), (), ()))
    assert runtime.ordinary == runtime.sleeping == runtime.dopple == runtime.update_order == ()
