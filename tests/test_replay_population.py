"""Original unchanged native population helper and saved restoration boundary."""

from __future__ import annotations

import gzip
import json
from dataclasses import replace
from functools import lru_cache
from pathlib import Path

import pytest

from vantage.replay_binary import SaveReader
from vantage.replay_master_tasks import ReplayMasterTask, ReplayMasterTasks
from vantage.replay_masters import SavedMaster, SavedMasterTask, read_master_table
from vantage.replay_population import (
    ReplayPopulationAttribute as Attribute,
)
from vantage.replay_population import (
    ReplayPopulationMaster as Master,
)
from vantage.replay_population import (
    ReplayPopulationTask as Task,
)
from vantage.replay_population import (
    replay_unit_population,
    restore_replay_population_master,
)

_NONE = Attribute(-1, 0)


def _master(amount: int = 0xBF800000, *, kind: int = 70, tasks: tuple[Task, ...] = ()) -> Master:
    return Master(kind, (Attribute(4, amount), _NONE, _NONE), tasks)


def _i16(value: int) -> int:
    return value if value < 0x8000 else value - 0x10000


def test_complete_original_helper_all_binary32_outputs() -> None:
    path = Path(__file__).parent / "fixtures/native_replay_population_54800.json.gz"
    data = json.loads(gzip.decompress(path.read_bytes()))
    for row, expected in data["rows"]:
        masters: list[Master | None] = []
        for m in range(4):
            r = row[2 + 34 * m : 2 + 34 * (m + 1)]
            if not r[0]:
                masters.append(None)
                continue
            attrs = [Attribute(_i16(r[2 + 2 * i] & 0xFFFF), r[3 + 2 * i]) for i in range(3)]
            tasks = tuple(
                Task(_i16(r[10 + 3 * i] & 0xFFFF), r[11 + 3 * i], r[12 + 3 * i])
                for i in range(r[9] if r[8] else 0)
            )
            masters.append(Master(r[1], (attrs[0], attrs[1], attrs[2]), tasks))
        before = tuple(masters)
        assert replay_unit_population(masters, row[0], include_tasks=bool(row[1])) == expected, row
        assert tuple(masters) == before
    assert len(data["rows"]) == 16576


def test_all_three_attributes_subtract_in_slot_order() -> None:
    master = Master(
        10, (Attribute(4, 0xBF800000), Attribute(4, 0xC0000000), Attribute(4, 0x3E800000))
    )
    assert replay_unit_population([master], 0) == 0x40300000  # 1+2-0.25


def test_null_slot_is_positive_zero() -> None:
    assert replay_unit_population([None], 0) == 0


def test_matching_tasks_visit_linked_attributes_once() -> None:
    masters = [
        _master(tasks=(Task(156, 0x3F800000, 0x40000000),)),
        _master(0xC0400000, tasks=(Task(156, 0, 0x42C80000),)),
    ]
    assert replay_unit_population(masters, 0) == 0x40E00000  # 1 + 3*2, no linked recursion
    assert replay_unit_population(masters, 0, include_tasks=False) == 0x3F800000


def test_self_reference_terminates_after_one_level() -> None:
    assert replay_unit_population([_master(tasks=(Task(156, 0, 0x40000000),))], 0) == 0x40400000


@pytest.mark.parametrize("kind", (0, 10, 40, 69))
def test_low_type_does_not_read_tasks(kind: int) -> None:
    master = _master(kind=kind, tasks=(Task(156, 0x7F800000, 0x7F801234),))
    assert replay_unit_population([master], 0) == 0x3F800000


def test_nonmatching_task_does_not_convert_invalid_link() -> None:
    assert replay_unit_population([_master(tasks=(Task(155, 0x7F801234, 0),))], 0) == 0x3F800000


@pytest.mark.parametrize("reference", (0x3F400000, 0xBF400000))
def test_fractional_link_ids_truncate_toward_zero(reference: int) -> None:
    assert (
        replay_unit_population([_master(tasks=(Task(156, reference, 0x3F800000),))], 0)
        == 0x40000000
    )


def test_null_link_still_multiplies_infinite_quantity() -> None:
    masters = [_master(tasks=(Task(156, 0x3F800000, 0x7F800000),)), None]
    assert replay_unit_population(masters, 0) == 0xFFC00000


@pytest.mark.parametrize("reference", (0xBF800000, 0x40800000, 0x7F800000, 0x7F801234, 0x4F000000))
def test_unsafe_link_storage_fails_explicitly(reference: int) -> None:
    with pytest.raises(ValueError, match=r"master|index"):
        replay_unit_population([_master(tasks=(Task(156, reference, 0),))], 0)


@pytest.mark.parametrize("index", (-1, 1, 2147483648))
def test_missing_requested_storage_is_distinct_from_null(index: int) -> None:
    with pytest.raises(ValueError):
        replay_unit_population([None], index)


def test_task_order_preserves_binary32_rounding() -> None:
    # 2**24 + 1 - 2**24 rounds to0; 2**24 - 2**24 +1 yields1.
    big, one, negative = (
        Task(156, 0x3F800000, 0x4B800000),
        Task(156, 0x3F800000, 0x3F800000),
        Task(156, 0x3F800000, 0xCB800000),
    )
    assert replay_unit_population([_master(0, tasks=(big, one, negative)), _master()], 0) == 0
    assert (
        replay_unit_population([_master(0, tasks=(big, negative, one)), _master()], 0) == 0x3F800000
    )


@lru_cache(maxsize=1)
def _saved() -> SavedMaster:
    fixture = Path(__file__).parent / "fixtures/native_saved_master_tables_54800.json.gz"
    data = json.loads(gzip.decompress(fixture.read_bytes()))
    raw = bytes.fromhex(data["table_blobs_by_sha256"][data["samples"][0]["raw_sha256"]])
    return read_master_table(SaveReader(raw)).masters[83]


def test_saved_attributes_use_exact_final_words_and_ignore_flags() -> None:
    saved = _saved()
    explicit_empty = ReplayMasterTasks(83, -1, (), True)
    restored = restore_replay_population_master(saved, explicit_empty)
    assert tuple((a.type_id, a.amount_bits) for a in restored.attributes) == tuple(
        (a.type_id, a.amount_word) for a in saved.base.attributes
    )
    assert replay_unit_population([restored], 0) == 0x3F800000


def test_saved_high_type_requires_resolved_tasks() -> None:
    with pytest.raises(ValueError, match="resolved native task list"):
        restore_replay_population_master(_saved())


def test_saved_task_bridge_keeps_order_and_exact_fields() -> None:
    task = SavedMasterTask(0, 0, 1, {}, (), (), b"")
    fields = {0xE: 156, 0x28: 0x3F400000, 0x2C: 0x3F800000}
    resolved = ReplayMasterTasks(83, -1, (ReplayMasterTask(task, fields),), False)
    restored = restore_replay_population_master(_saved(), resolved)
    assert restored.tasks == (Task(156, 0x3F400000, 0x3F800000),)
    assert replay_unit_population([restored], 0) == 0x40000000
    assert fields == {0xE: 156, 0x28: 0x3F400000, 0x2C: 0x3F800000}


def test_missing_serialized_attribute_does_not_invent_default() -> None:
    saved = _saved()
    fields = dict(saved.fields)
    del fields[0xB4]
    with pytest.raises(ValueError, match="0xb4"):
        restore_replay_population_master(
            replace(saved, fields=fields), ReplayMasterTasks(83, -1, (), True)
        )


def test_invalid_native_scalar_or_slot_shape_fails() -> None:
    with pytest.raises(ValueError):
        Attribute(32768, 0)
    with pytest.raises(ValueError):
        Task(156, -1, 0)
    with pytest.raises(ValueError):
        Master(256, (_NONE, _NONE, _NONE))
    with pytest.raises(ValueError):
        replay_unit_population([None], 0, include_tasks=1)  # type: ignore[arg-type]  # Runtime boundary.
