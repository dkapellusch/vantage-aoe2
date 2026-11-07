"""Restore the task/default-task portion of a saved master from selected DAT data.

Native MasterActionObject141170b50 copies list228/default-index230 from its
baseline before applying optional task overrides. This does not merge other
master fields, choose a civilization, resolve graphics or install actions.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from vantage.replay_game_data import GameDataMaster
from vantage.replay_masters import SavedMaster, SavedMasterTask


class ReplayMasterTasksError(ValueError):
    """The selected baseline cannot supply a supported action-master task list."""


@dataclass(frozen=True, slots=True)
class ReplayMasterTask:
    """Copied task scalar values with its original definition retained separately."""

    definition: SavedMasterTask
    fields: dict[int, int]

    @property
    def type_id(self) -> int:
        return self.definition.type_id

    @property
    def sprite_ids(self) -> tuple[int, ...]:
        return tuple(self.fields[offset] for offset in (0x40, 0x48, 0x50, 0x58))


@dataclass(frozen=True, slots=True)
class ReplayMasterTasks:
    baseline_index: int
    default_index: int
    tasks: tuple[ReplayMasterTask, ...]
    inherited: bool

    def lookup(self, index: int) -> ReplayMasterTask | None:
        """Native14116a5b0 indexes by vector position, not task field0xa."""
        if not isinstance(index, int) or not -32768 <= index <= 32767:
            raise ValueError("master task index must be an i16")
        return self.tasks[index] if 0 <= index < len(self.tasks) else None

    @property
    def default_task(self) -> ReplayMasterTask | None:
        return self.lookup(self.default_index)


def restore_replay_master_tasks(
    saved: SavedMaster, selected_baseline: Mapping[int, GameDataMaster]
) -> ReplayMasterTasks:
    """Resolve one parsed master's task portion using an explicitly selected DAT table.

    Native common restoration remaps baseline selector768→420 and770→691.
    The saved/raw selector is preserved; only this lookup uses the remap.
    Explicit nonpositive task counts override with an empty list. Inherited
    task scalar values are cloned so later runtime edits do not change the DAT.
    Native clone constructors assign inherited task IDs by vector position;
    the original definition retains its wire ID. Inline save IDs are read back
    from the save. Later map/game task adjustments and references are separate.
    Missing or incompatible baselines fail without inventing ctor defaults.
    """
    if saved.type_group < 40:
        raise ReplayMasterTasksError("saved master has no action-task component")
    index = {768: 420, 770: 691}.get(saved.base.baseline_id, saved.base.baseline_id)
    baseline = selected_baseline.get(index)
    if baseline is None or baseline.type_group < 40 or 0x230 not in baseline.fields:
        raise ReplayMasterTasksError(f"missing action baseline at master index {index}")
    word = baseline.fields[0x230]
    if not 0 <= word <= 0xFFFF:
        raise ReplayMasterTasksError("baseline default task index must be a u16 word")
    default_index = word if word < 0x8000 else word - 0x10000
    if saved.task_count is None:
        if saved.tasks:
            raise ReplayMasterTasksError("inherited saved task list contains inline tasks")
        tasks = baseline.tasks
    else:
        if len(saved.tasks) != max(0, saved.task_count):
            raise ReplayMasterTasksError("saved task count does not match inline entries")
        tasks = saved.tasks
    return ReplayMasterTasks(
        index,
        default_index,
        tuple(
            ReplayMasterTask(
                task,
                {**task.fields, 0xA: position} if saved.task_count is None else dict(task.fields),
            )
            for position, task in enumerate(tasks)
        ),
        saved.task_count is None,
    )
