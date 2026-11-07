"""Original whole ActionMaster copy results and retained task identities."""

from __future__ import annotations

import gzip
import json
import struct
from dataclasses import replace
from pathlib import Path

import pytest

from vantage.replay_master_tasks import (
    ReplayMasterTask,
    ReplayMasterTasks,
    ReplayMasterTasksError,
)
from vantage.replay_masters import SavedMasterTask
from vantage.replay_task_graphics import copy_replay_task_graphics

_SPRITES = (0x40, 0x48, 0x50, 0x58)


def _task(sprite: int, holding: int = 0) -> ReplayMasterTask:
    fields = {0xA: 17, 0x19: holding, 0x28: 0x7FC01234, 0x60: 91, 0x78: 92}
    fields.update({offset: sprite + i for i, offset in enumerate(_SPRITES)})
    saved = SavedMasterTask(
        0, 69, 1, dict(fields), tuple(sprite + i for i in range(4)), (), bytes(69)
    )
    return ReplayMasterTask(saved, dict(fields))


def _list(n: int, sprite: int = 1) -> ReplayMasterTasks:
    return ReplayMasterTasks(125, -1, tuple(_task(sprite + i * 4, i & 1) for i in range(n)), True)


def test_original_whole_action_master_copy_all_native_task_bytes() -> None:
    fixture = Path(__file__).parent / "fixtures/native_replay_task_graphics_54800.json.gz"
    data = json.loads(gzip.decompress(fixture.read_bytes()))
    assert data["rea_evidence_id"] == (
        "ev_432dbb2e4798536727e41b789469201948f7fcaec6d6c1a0c1e44efcfd10dfcd"
    )
    assert data["native_exit"] == 0 and not data["original_instructions_changed"]
    compared = full_bytes = changed = 0
    for case in data["rows"]:
        dn, sn, _, _, alias = case["input"]
        before, source, after = (bytes.fromhex(case[k]) for k in ("before", "source", "after"))
        # Native pointers are opaque 64-bit tokens. This explicit bijection
        # converts references into logical IDs without deriving expected copy
        # results from a Python algorithm.
        tokens = sorted(
            {
                struct.unpack_from("<Q", raw, i * 0x88 + offset)[0]
                for raw in (before, source)
                for i in range(32)
                for offset in _SPRITES
            }
        )
        ids = {token: i for i, token in enumerate(tokens)}

        def restore(count: int, raw: bytes, references: dict[int, int]) -> ReplayMasterTasks | None:
            if count < 0:
                return None
            tasks = []
            for i in range(count):
                task = _task(0, raw[i * 0x88 + 0x19])
                fields = dict(task.fields)
                fields.update(
                    {
                        o: references[struct.unpack_from("<Q", raw, i * 0x88 + o)[0]]
                        for o in _SPRITES
                    }
                )
                tasks.append(replace(task, fields=fields))
            return ReplayMasterTasks(125, -1, tuple(tasks), True)

        target = restore(dn, before, ids)
        source_list = target if alias else restore(sn, source, ids)
        result = copy_replay_task_graphics(target, source_list)
        rendered = bytearray(before)
        if result is not None:
            for i, task in enumerate(result.tasks):
                for offset in _SPRITES:
                    struct.pack_into("<Q", rendered, i * 0x88 + offset, tokens[task.fields[offset]])
                assert task.fields[0x19] == before[i * 0x88 + 0x19]
        assert rendered == after, case["input"]
        compared += 1
        full_bytes += len(rendered)
        changed += before != after
    assert compared == 284 and full_bytes == 1235968 and changed == 24


def test_only_graphics_change_and_original_definitions_and_metadata_survive() -> None:
    target, source = _list(2), replace(_list(2, 101), default_index=1, inherited=False)
    result = copy_replay_task_graphics(target, source)
    assert result is not None
    assert (result.baseline_index, result.default_index, result.inherited) == (125, -1, True)
    for old, new, template in zip(target.tasks, result.tasks, source.tasks, strict=True):
        assert new.definition is old.definition
        assert new.sprite_ids == template.sprite_ids
        assert {k: v for k, v in new.fields.items() if k not in _SPRITES} == {
            k: v for k, v in old.fields.items() if k not in _SPRITES
        }
        assert old.fields[0x40] < 100
        new.fields[0x19] = 9
        assert old.fields[0x19] in (0, 1) and template.fields[0x19] in (0, 1)


@pytest.mark.parametrize("dn,sn", [(None, None), (None, 1), (1, None), (0, 0), (0, 1), (2, 1)])
def test_null_empty_and_unequal_lists_preserve_target(dn: int | None, sn: int | None) -> None:
    target = None if dn is None else _list(dn)
    source = None if sn is None else _list(sn, 101)
    assert copy_replay_task_graphics(target, source) is target


def test_source_missing_a_resolved_graphic_fails_without_mutation() -> None:
    target, source = _list(1), _list(1, 101)
    del source.tasks[0].fields[0x58]
    before = dict(target.tasks[0].fields)
    with pytest.raises(ReplayMasterTasksError, match="unresolved"):
        copy_replay_task_graphics(target, source)
    assert target.tasks[0].fields == before
