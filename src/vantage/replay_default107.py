"""Bounded human default-107 installation, before further lifecycle updates.

Original14113e860 performs positional task lookup, an existing-type check and
factory/install/activation. The executed native profile is retained under
``default-action-fixture-v1`` and ``default-action-installation``. This module
does not allocate native objects or complete initial-world pending effects.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Literal

from vantage.replay_master_common import ReplayMasterCommon, ReplayMasterComponents
from vantage.replay_master_tasks import ReplayMasterTask, ReplayMasterTasks
from vantage.replay_masters import SavedMaster, SavedMasterTask
from vantage.replay_objects import SavedActionState, SavedObject
from vantage.replay_world_assembly import ReplayInitialObjectBinding


class ReplayDefault107Error(ValueError):
    """The binding or requested transition is outside the proved profile."""

    def __init__(
        self,
        message: str,
        *,
        object_id: int | None = None,
        owner: int | None = None,
        master_index: int | None = None,
    ) -> None:
        self.object_id, self.owner, self.master_index = object_id, owner, master_index
        context = ", ".join(
            f"{key}={value}"
            for key, value in (("object", object_id), ("owner", owner), ("master", master_index))
            if value is not None
        )
        super().__init__(message + (f" ({context})" if context else ""))


def _error(binding: object, message: str) -> ReplayDefault107Error:
    obj = binding.saved if isinstance(binding, ReplayInitialObjectBinding) else None
    return ReplayDefault107Error(
        message,
        **{
            key: value
            for key, value in (
                ("object_id", obj.object_id if isinstance(obj, SavedObject) else None),
                (
                    "owner",
                    obj.owner
                    if isinstance(obj, SavedObject)
                    else binding.player_index
                    if isinstance(binding, ReplayInitialObjectBinding)
                    else None,
                ),
                ("master_index", obj.master_id if isinstance(obj, SavedObject) else None),
            )
            if type(value) is int
        },
    )


def _default_task(task: object) -> bool:
    return (
        isinstance(task, ReplayMasterTask)
        and isinstance(task.definition, SavedMasterTask)
        and type(task.definition.type_id) is int
        and task.definition.type_id == 1
        and isinstance(task.fields, dict)
        and type(task.fields.get(0xE)) is int
        and task.fields[0xE] == 107
    )


def _initial_scalars() -> bytes:
    raw = bytearray(112)
    struct.pack_into("<H", raw, 8, 107)
    raw[0x18] = 6
    struct.pack_into("<2i3I", raw, 0x30, -1, -1, *(0xBF800000,) * 3)
    return bytes(raw)


_INITIAL_SCALARS = _initial_scalars()


@dataclass(frozen=True, slots=True)
class ReplayDefault107Action:
    """Fresh Parent107 with logical references, without native pointer storage.

    ``scalar_bytes`` preserves all112 original bytes except six qword slots:
    vtable0, owner10, target20/28, task48 and child-manager50 are zero. (The
    two target slots were already null.) Their meaning is represented by the
    binding/task and the explicitly empty child manager. No native allocation,
    address or original encoded pointer is synthesized. This is an initial
    state6 record; later candidate/timer/child-action updates are separate.
    """

    binding: ReplayInitialObjectBinding
    task_index: int
    task: ReplayMasterTask
    scalar_bytes: bytes
    child_head: None = None

    @property
    def type_id(self) -> Literal[107]:
        return 107

    @property
    def state(self) -> int:
        return self.scalar_bytes[0x18]

    @property
    def timer_bits(self) -> int:
        return int(struct.unpack_from("<I", self.scalar_bytes, 0x44)[0])


@dataclass(frozen=True, slots=True)
class ReplayDefault107Installation:
    action: ReplayDefault107Action | None
    outcome: Literal["installed", "existing", "no_task"]
    # An explicit component result never clears the assembler's pending state.
    world_initialization_pending: Literal[True] = True


def install_replay_human_default107(
    binding: ReplayInitialObjectBinding,
    *,
    owner_runtime_type: int,
    cached_options_present: bool,
    options_mode: int,
    current: ReplayDefault107Action | None = None,
    task_index: int | None = None,
) -> ReplayDefault107Installation:
    """Install a fresh human/state2 default107 or preserve its exact duplicate.

    ``binding`` supplies the saved object and the explicitly selected/restored
    current master. Owner runtime type and cached-options presence are caller
    premises, not facts inferred from the saved object alone. Supported modes
    are the five actually executed0/3/4/5/15. No Computer monitoring, nonempty
    replacement, general factory or options-fallback branch is represented.
    Empty saved behavior and empty Action.object_map are independent premises:
    this fixture deliberately also requires the latter map to be empty.

    By default this selects master.default_index. ``task_index`` exposes the
    original signed-i16 helper argument for direct no-task controls; calling
    the helper with -1 differs from the upstream default=-1 early gate. A
    duplicate must be this component's unchanged initial107 on the same
    binding. Neither call advances a clock nor runs an ordinary action update.
    """
    if not isinstance(binding, ReplayInitialObjectBinding):
        raise _error(binding, "an assembled logical object binding is required")
    obj, master = binding.saved, binding.master
    if not isinstance(obj, SavedObject) or not isinstance(master, ReplayMasterComponents):
        raise _error(binding, "saved object and current-master components are required")
    if not isinstance(master.saved, SavedMaster) or not isinstance(
        master.common, ReplayMasterCommon
    ):
        raise _error(binding, "saved master and restored common components are required")
    if (
        type(obj.type_group) is not int
        or obj.type_group != 70
        or master.saved.type_group != 70
        or type(obj.object_id) is not int
        or not 0 <= obj.object_id <= 0xFFFFFFFF
        or type(obj.owner) is not int
        or not 0 <= obj.owner <= 255
        or type(binding.player_index) is not int
        or binding.player_index != obj.owner
        or type(obj.master_id) is not int
        or type(master.saved.master_id) is not int
        or obj.master_id != master.saved.master_id
    ):
        raise _error(binding, "Unit70 owner/current-master binding is inconsistent")
    if (
        not isinstance(obj.flags, tuple)
        or len(obj.flags) != 4
        or any(type(value) is not int or not 0 <= value <= 255 for value in obj.flags)
        or obj.flags[0] != 2
    ):
        raise _error(binding, "the proved default-install lifecycle state is2")
    if (
        not isinstance(obj.action, SavedActionState)
        or not isinstance(obj.action.raw, bytes)
        or obj.action.raw[-2:] != b"\0\0"
    ):
        raise _error(binding, "the saved behavior list must be parser-empty")
    if not isinstance(obj.action.object_map, tuple) or obj.action.object_map:
        raise _error(binding, "the independent saved Action.object_map must also be empty")
    if type(owner_runtime_type) is not int or owner_runtime_type != 1:
        raise _error(binding, "only the human runtime owner type1 is proved")
    if cached_options_present is not True:
        raise _error(binding, "the nonnull cached-options path is required")
    if type(options_mode) is not int or options_mode not in (0, 3, 4, 5, 15):
        raise _error(binding, "unsupported cached-options mode")
    tasks = master.tasks
    if (
        not isinstance(tasks, ReplayMasterTasks)
        or not isinstance(tasks.tasks, tuple)
        or any(
            not isinstance(task, ReplayMasterTask)
            or not isinstance(task.definition, SavedMasterTask)
            or not isinstance(task.fields, dict)
            for task in tasks.tasks
        )
        or type(tasks.baseline_index) is not int
        or type(master.common.baseline_index) is not int
        or tasks.baseline_index != master.baseline_index
    ):
        raise _error(binding, "the current master's restored task component is required")
    index = tasks.default_index if task_index is None else task_index
    if type(index) is not int or not -32768 <= index <= 32767:
        raise _error(binding, "task index must be a signed i16")
    if current is not None and (
        not isinstance(current, ReplayDefault107Action)
        or current.binding is not binding
        or type(current.scalar_bytes) is not bytes
        or current.scalar_bytes != _INITIAL_SCALARS
        or current.child_head is not None
        or type(current.task_index) is not int
        or not 0 <= current.task_index < len(tasks.tasks)
        or current.task is not tasks.tasks[current.task_index]
        or not _default_task(current.task)
    ):
        raise _error(binding, "existing action is not this binding's fresh default107")
    task = tasks.lookup(index)
    if task is None:
        return ReplayDefault107Installation(current, "no_task")
    if not _default_task(task):
        raise _error(binding, "only task record1/action107 is supported")
    if current is not None:
        return ReplayDefault107Installation(current, "existing")
    return ReplayDefault107Installation(
        ReplayDefault107Action(binding, index, task, _INITIAL_SCALARS), "installed"
    )
