"""Baseline/override task binding with original saved-master records."""

from __future__ import annotations

import gzip
import json
from dataclasses import replace
from functools import lru_cache
from pathlib import Path

import pytest

from vantage.replay_binary import SaveReader
from vantage.replay_game_data import GameDataMaster, GameDataMasterCommon
from vantage.replay_master_tasks import ReplayMasterTasksError, restore_replay_master_tasks
from vantage.replay_masters import SavedMaster, SavedMasterTask, read_master_table


@lru_cache(maxsize=1)
def _saved() -> SavedMaster:
    fixture = Path(__file__).parent / "fixtures/native_saved_master_tables_54800.json.gz"
    data = json.loads(gzip.decompress(fixture.read_bytes()))
    raw = bytes.fromhex(data["table_blobs_by_sha256"][data["samples"][0]["raw_sha256"]])
    return read_master_table(SaveReader(raw)).masters[96]


def _task(task_id: int, action: int = 10) -> SavedMasterTask:
    return SavedMasterTask(
        0,
        69,
        1,
        {0xA: task_id, 0xE: action, 0x19: 0, 0x40: -1, 0x48: 1597, 0x50: -1, 0x58: -1},
        (-1, 1597, -1, -1),
        (),
        bytes(69),
    )


def _baseline(default: int = 0, *, kind: int = 70) -> GameDataMaster:
    common = GameDataMasterCommon(0, 0, {}, 0, b"", (), (), {}, {}, b"", {}, b"")
    return GameDataMaster(
        offset=0,
        end_offset=0,
        type_group=kind,
        common=common,
        fields={0x230: default},
        sprite_id_bits={},
        sound_numbers={},
        sound_events={},
        action_sprite_bits=(),
        tasks=(_task(7), _task(99, 1)),
        combat_pairs={},
        cost_records_6=(),
        definition_records_9=(),
        building_piece_records_10=(),
        sections={},
        raw=b"",
    )


def test_inherited_clone_assigns_positional_ids_and_retains_raw_definition() -> None:
    saved, baseline = _saved(), _baseline()
    assert saved.task_count is None
    result = restore_replay_master_tasks(saved, {saved.base.baseline_id: baseline})
    assert result.inherited and result.default_index == 0
    assert [task.fields[0xA] for task in result.tasks] == [0, 1]
    assert [task.definition.fields[0xA] for task in result.tasks] == [7, 99]
    assert result.default_task is result.tasks[0]
    assert result.tasks[0].sprite_ids == (-1, 1597, -1, -1)
    # The later Gaia/map-specific holdingAttr/sprite adjustments are separate;
    # this copy stage must not substitute captured final values for them.
    assert result.tasks[0].fields[0x19] == 0
    result.tasks[0].fields[0x19] = 1
    assert baseline.tasks[0].fields[0x19] == 0


def test_inline_save_overrides_inherited_list_and_preserves_read_back_ids() -> None:
    task = _task(42)
    saved = replace(_saved(), task_count=1, tasks=(task,))
    result = restore_replay_master_tasks(saved, {saved.base.baseline_id: _baseline()})
    assert not result.inherited and len(result.tasks) == 1
    assert result.default_task is not None and result.default_task.fields[0xA] == 42
    assert result.default_task.definition is task
    result.default_task.fields[0xE] = 99
    assert task.fields[0xE] == 10


@pytest.mark.parametrize("count", [0, -1, -32768])
def test_nonpositive_override_replaces_baseline_with_empty_list(count: int) -> None:
    saved = replace(_saved(), task_count=count, tasks=())
    result = restore_replay_master_tasks(saved, {saved.base.baseline_id: _baseline()})
    assert not result.inherited and result.tasks == () and result.default_task is None


@pytest.mark.parametrize("raw,index", [(768, 420), (770, 691), (96, 96)])
def test_only_lookup_remaps_baseline_selector(raw: int, index: int) -> None:
    saved = replace(_saved(), base=replace(_saved().base, baseline_id=raw))
    result = restore_replay_master_tasks(saved, {index: _baseline()})
    assert result.baseline_index == index
    assert saved.base.baseline_id == raw


@pytest.mark.parametrize("word", [0xFFFF, 0x8000, 2, 32767])
def test_default_index_is_signed_and_positional_with_no_fallback(word: int) -> None:
    saved = _saved()
    result = restore_replay_master_tasks(saved, {saved.base.baseline_id: _baseline(word)})
    assert result.default_task is None
    assert result.default_index == (word if word < 32768 else word - 65536)


@pytest.mark.parametrize("index", [-32768, -1, 0, 1, 2, 32767])
def test_native_task_lookup_bounds(index: int) -> None:
    saved = _saved()
    result = restore_replay_master_tasks(saved, {saved.base.baseline_id: _baseline()})
    assert result.lookup(index) is (result.tasks[index] if 0 <= index < 2 else None)


def test_missing_or_non_action_baseline_fails_explicitly() -> None:
    saved = _saved()
    for baselines in ({}, {saved.base.baseline_id: _baseline(kind=30)}):
        with pytest.raises(ReplayMasterTasksError, match="missing action baseline"):
            restore_replay_master_tasks(saved, baselines)
    with pytest.raises(ReplayMasterTasksError, match="no action-task component"):
        restore_replay_master_tasks(replace(saved, type_group=30), {})


@pytest.mark.parametrize("count,tasks", [(None, (_task(0),)), (1, ()), (-1, (_task(0),))])
def test_inconsistent_manual_records_are_rejected(
    count: int | None, tasks: tuple[SavedMasterTask, ...]
) -> None:
    saved = replace(_saved(), task_count=count, tasks=tasks)
    with pytest.raises(ReplayMasterTasksError):
        restore_replay_master_tasks(saved, {saved.base.baseline_id: _baseline()})
