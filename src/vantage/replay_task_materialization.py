"""Materialize fresh parsed TaskLists or shallow-clone current runtime baselines.

Build54800 successful final-state contract: task-list-materialization-contract-v1.
Fresh reads resolve current graphics/sounds; inherited tasks copy current source
bytes. This adapter omits stream Result/EH and transient master clone/delete
chronology. It does not construct a complete saved master or restored World.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass

from .replay_master_tasks import ReplayMasterTask, ReplayMasterTasks
from .replay_masters import SavedMasterTask
from .replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
    _call,
    _read,
    _signed,
    _unsigned,
    _write,
)

_U64 = (1 << 64) - 1
_SCALARS = (
    (0xA, 2),
    (0xC, 1),
    (0xE, 2),
    (0x10, 2),
    (0x12, 2),
    (0x16, 2),
    (0x20, 2),
    (0x22, 2),
    (0x24, 2),
    (0x26, 2),
    (0x28, 4),
    (0x2C, 4),
    (0x30, 4),
    (0x1B, 1),
    (0x1C, 4),
    (0x14, 1),
    (0x15, 1),
    (0x34, 2),
    (0x36, 2),
    (0x18, 1),
    (0x19, 1),
    (0x1A, 1),
)
TaskLocalBinding = Callable[[memoryview], AbstractContextManager[int]]


@dataclass(frozen=True, slots=True)
class ReplayTaskReferenceContexts:
    """Current graphic-vector and sound-table descriptor addresses.

    Zero addresses are allowed only when source branches do not dereference
    them. IDs are never substituted for runtime pointers. Registry globals
    remain current backing read by the actual membership helper when reached.
    """

    graphics: int
    sounds: int

    def __post_init__(self) -> None:
        _unsigned(self.graphics, 8, "graphic context address")
        _unsigned(self.sounds, 8, "sound context address")


@dataclass(frozen=True, slots=True)
class ReplayMaterializedTaskList:
    """Fresh list identity and occurrence-ordered task identities, not wire IDs."""

    address: int
    task_addresses: tuple[int, ...]


def _validate(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    master: int,
    factory_target: int,
    bind_local: TaskLocalBinding,
) -> None:
    if not isinstance(context, ReplayTaskRebuildStorage):
        raise ValueError("explicit current task materialization storage required")
    if not isinstance(calls, ReplayTaskRebuildCalls) or not callable(bind_local):
        raise ValueError("actual task effects and scoped local binding required")
    _unsigned(master, 8, "task-list master argument")
    _unsigned(factory_target, 8, "TaskList factory target")
    if factory_target not in (0x14116BA60, 0x141323AE0):
        raise ValueError("explicit supported TaskList factory target required")


def _field(fields: Mapping[int, int], offset: int, width: int) -> int:
    value = fields.get(offset)
    low = -32768 if width == 2 else 0
    if type(value) is not int or not low <= value < 1 << (width * 8):
        raise ValueError(f"invalid parsed task field{offset:x}/{width}")
    return value


def _new_list(
    context: ReplayTaskRebuildStorage,
    master: int,
    count: int,
    factory_target: int,
    calls: ReplayTaskRebuildCalls,
    bind_local: TaskLocalBinding,
) -> int:
    task_list = _call(calls, factory_target, (master,), width=8)
    if not task_list:
        raise UnresolvedReplayTaskRebuild("TaskList factory returned null")
    if count:
        manager = bind_local(memoryview(bytearray(8)))
        address = manager.__enter__()
        try:
            _unsigned(address, 8, "bound TaskList zero-fill address")
            _call(calls, 0x141268370, ((task_list + 8) & _U64, count, address))
        except BaseException as error:
            manager.__exit__(type(error), error, error.__traceback__)
            raise
        else:
            manager.__exit__(None, None, None)
    return task_list


def _new_task(
    context: ReplayTaskRebuildStorage,
    task_list: int,
    tag: int,
    position: int,
    calls: ReplayTaskRebuildCalls,
) -> int:
    vtable = _read(context, task_list, 8)
    target = _read(context, vtable + 8, 8)
    task = _call(calls, target, (task_list, tag & 0xFFFF, position & 0xFFFF), width=8)
    if not task:
        raise UnresolvedReplayTaskRebuild("current Task factory returned null")
    return task


def _publish(
    context: ReplayTaskRebuildStorage,
    task_list: int,
    position: int,
    task: int,
) -> None:
    begin = _read(context, task_list + 8, 8)
    _write(context, begin + position * 8, 8, task)


def materialize_replay_task_definitions(
    context: ReplayTaskRebuildStorage,
    tasks: Sequence[SavedMasterTask | ReplayMasterTask],
    *,
    master: int,
    factory_target: int,
    references: ReplayTaskReferenceContexts,
    calls: ReplayTaskRebuildCalls,
    bind_local: TaskLocalBinding,
) -> ReplayMaterializedTaskList:
    """Fresh parsed definitions, actual factories and current asset resolution.

    Parsed scalar/graphic fields may be effective ReplayMasterTask fields;
    sound IDs and factory tag come from its definition. Normal count<=32767,
    successful factories and coherent disjoint storage are required. Metadata
    preflight is an adapter boundary, not native stream-fault behavior. Pointer
    publication precedes field writes; reached failures retain prior effects.
    """
    _validate(context, calls, master, factory_target, bind_local)
    if not isinstance(references, ReplayTaskReferenceContexts) or len(tasks) > 32767:
        raise ValueError("explicit reference contexts and bounded task count required")
    prepared = []
    for parsed_task in tasks:
        if not isinstance(parsed_task, (SavedMasterTask, ReplayMasterTask)):
            raise ValueError("parsed task definition required")
        definition = (
            parsed_task.definition if isinstance(parsed_task, ReplayMasterTask) else parsed_task
        )
        if definition.type_id != 1 or len(definition.sound_numbers) != 2:
            raise ValueError("supported tag1 task and two signed sound IDs required")
        fields = dict(parsed_task.fields)
        for offset, width in (
            *_SCALARS,
            (0x38, 2),
            (0x60, 4),
            (0x78, 4),
            (0x40, 2),
            (0x48, 2),
            (0x50, 2),
            (0x58, 2),
        ):
            _field(fields, offset, width)
        if any(type(v) is not int or not -32768 <= v <= 32767 for v in definition.sound_numbers):
            raise ValueError("signed WORD sound IDs required")
        prepared.append((definition, fields))
    task_list = _new_list(context, master, len(prepared), factory_target, calls, bind_local)
    addresses = []
    for position, (definition, fields) in enumerate(prepared):
        task = _new_task(context, task_list, definition.type_id, position, calls)
        _publish(context, task_list, position, task)
        for offset, width in _SCALARS:
            _write(context, task + offset, width, fields[offset])
        for offset in (0x40, 0x48, 0x50, 0x58):
            index = _signed(fields[offset] & 0xFFFF, 2)
            pointer = (
                0
                if index == -1
                else _read(context, _read(context, references.graphics, 8) + index * 8, 8)
            )
            _write(context, task + offset, 8, pointer)
        for offset in (0x60, 0x78):
            _write(context, task + offset, 4, fields[offset])
        for offset in (0x70, 0x88):
            _write(context, task + offset, 4, 1)
        for offset, sound_id in zip((0x60, 0x78), definition.sound_numbers, strict=True):
            _call(
                calls,
                0x14147B6E0,
                ((task + offset) & _U64, references.sounds, sound_id & 0xFFFF, 0x62D4B3EC),
            )
        for primary, flags in ((0x60, 0x70), (0x78, 0x88)):
            if _call(calls, 0x140B245D0, (_read(context, task + primary, 4),), width=8) & 255:
                _write(context, task + flags, 4, _read(context, task + flags, 4) | 4)
        _write(context, task + 0x38, 2, fields[0x38])
        addresses.append(task)
    return ReplayMaterializedTaskList(task_list, tuple(addresses))


def clone_current_replay_task_list(
    context: ReplayTaskRebuildStorage,
    source_list: int,
    *,
    master: int,
    factory_target: int,
    calls: ReplayTaskRebuildCalls,
    bind_local: TaskLocalBinding,
) -> ReplayMaterializedTaskList | None:
    """Fresh final-state clone of current task bytes; explicit null stays null.

    Require a coherent nonwrapping vector with count<=32767, supported current
    source tags/factories and fully readable copied ranges. Copy14112f830 keeps
    fresh sequential ordinals/ordinary padding but shallow-copies full sound
    descriptors and graphic pointers. No asset resolution is performed again.
    Final-state parity requires stable source headers and helper behavior
    independent of the omitted transient destination end. This does not
    reproduce full clone-iterator reserve/append callback order.
    """
    _validate(context, calls, master, factory_target, bind_local)
    _unsigned(source_list, 8, "current source TaskList")
    if not source_list:
        return None
    begin = _read(context, source_list + 8, 8)
    end = _read(context, source_list + 16, 8)
    capacity = _read(context, source_list + 24, 8)
    if (
        not begin <= end <= capacity
        or (end - begin) % 8
        or (capacity - begin) % 8
        or (end - begin) // 8 > 32767
        or (not begin and capacity)
    ):
        raise ValueError("coherent bounded current TaskList vector required")
    count = (end - begin) // 8
    task_list = _new_list(context, master, count, factory_target, calls, bind_local)
    addresses = []
    for position in range(count):
        source = _read(context, begin + position * 8, 8)
        if not source:
            raise UnresolvedReplayTaskRebuild("nonnull current source Task required")
        tag = _read(context, source + 8, 2)
        task = _new_task(context, task_list, tag, position, calls)
        _call(calls, 0x14112F830, (task, source))
        _publish(context, task_list, position, task)
        addresses.append(task)
    return ReplayMaterializedTaskList(task_list, tuple(addresses))


def materialize_replay_master_tasks(
    context: ReplayTaskRebuildStorage,
    definition: ReplayMasterTasks,
    *,
    baseline_list: int,
    master: int,
    factory_target: int,
    references: ReplayTaskReferenceContexts,
    calls: ReplayTaskRebuildCalls,
    bind_local: TaskLocalBinding,
) -> ReplayMaterializedTaskList | None:
    """Resolve the saved task portion; default-index remains in definition.

    Inheritance clones the supplied current baseline list, including explicit
    null. An override materializes effective parsed tasks against current
    references. This omits the full master's transient clone-then-delete path;
    no current master pointer or default-index field is silently installed.
    """
    if not isinstance(definition, ReplayMasterTasks):
        raise ValueError("explicit restored master task definition required")
    if definition.inherited:
        return clone_current_replay_task_list(
            context,
            baseline_list,
            master=master,
            factory_target=factory_target,
            calls=calls,
            bind_local=bind_local,
        )
    return materialize_replay_task_definitions(
        context,
        definition.tasks,
        master=master,
        factory_target=factory_target,
        references=references,
        calls=calls,
        bind_local=bind_local,
    )
