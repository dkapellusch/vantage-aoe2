"""Task graphics component of native master-copy virtual slot+10.

The caller must select a compatible source master and resolve its graphics
references. This performs only ActionMaster141169aa0's task-list component;
common/unit/building graphics and source selection remain separate.
Evidence: world-envelope/master-task-graphics/README.md.
"""

from __future__ import annotations

from dataclasses import replace

from .replay_master_tasks import ReplayMasterTasks, ReplayMasterTasksError

_SPRITES = (0x40, 0x48, 0x50, 0x58)


def copy_replay_task_graphics(
    target: ReplayMasterTasks | None, source: ReplayMasterTasks | None
) -> ReplayMasterTasks | None:
    """Copy four graphic references by position when both lists have equal length.

    None represents an actual null TaskList pointer, independently of an empty
    list. Null or unequal lists preserve the target. Equal lists copy just
    task+40/+48/+50/+58; task IDs, holding attributes, sounds, task definitions,
    default indices and all list metadata survive. Values are returned without
    mutating either input. Source civilization, family and class checks occur
    in the enclosing native master factory and must already be established.
    """
    if target is None or source is None or len(target.tasks) != len(source.tasks):
        return target
    if not target.tasks:
        return target
    for task in source.tasks:
        if any(offset not in task.fields for offset in _SPRITES):
            raise ReplayMasterTasksError("source task has unresolved graphic references")
    return replace(
        target,
        tasks=tuple(
            replace(old, fields={**old.fields, **{o: new.fields[o] for o in _SPRITES}})
            for old, new in zip(target.tasks, source.tasks, strict=True)
        ),
    )
