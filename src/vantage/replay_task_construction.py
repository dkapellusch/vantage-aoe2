"""Build54800 TaskList/task constructors, factories and ordered task clone.

Source: world-envelope/task-record-construction-source-v1, including complete
factory/constructor objdumps and14112f830 C/ASM. Addresses are current owned
storage tokens. These bodies do not restore a whole master, list or World.
"""

from __future__ import annotations

from .replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
    _call,
    _read,
    _unsigned,
    _write,
)


def _validate(context: ReplayTaskRebuildStorage, *values: int) -> None:
    if not isinstance(context, ReplayTaskRebuildStorage):
        raise ValueError("explicit current task storage required")
    for value in values:
        _unsigned(value, 8, "task construction argument")


def _validate_calls(calls: ReplayTaskRebuildCalls) -> None:
    if not isinstance(calls, ReplayTaskRebuildCalls):
        raise ValueError("explicit actual construction effects required")


def construct_replay_task_descriptor(context: ReplayTaskRebuildStorage, address: int) -> int:
    """Full14147b480: define20B, preserving the trailing4B descriptor padding."""
    _validate(context, address)
    for offset, width in ((0, 8), (8, 8), (16, 4)):
        _write(context, address + offset, width, 0)
    return address


def construct_replay_task_list(context: ReplayTaskRebuildStorage, address: int) -> int:
    """Full1412686d0: install base vtable and three null vector pointers."""
    _validate(context, address)
    _write(context, address, 8, 0x1432B5EE8)
    for offset in (8, 16, 24):
        _write(context, address + offset, 8, 0)
    return address


def construct_replay_task(
    context: ReplayTaskRebuildStorage,
    address: int,
    ordinal: int,
    *,
    calls: ReplayTaskRebuildCalls,
) -> int:
    """Full14112aa40; standalone ctor leaves its ordinary/descriptor padding alone."""
    _validate(context, address, ordinal)
    _validate_calls(calls)
    _write(context, address, 8, 0x1432A4EF8)
    _call(calls, 0x14147B480, ((address + 0x60) & ((1 << 64) - 1),))
    _call(calls, 0x14147B480, ((address + 0x78) & ((1 << 64) - 1),))
    for offset, width, value in (
        (0xA, 2, ordinal),
        (0x38, 2, 0xFFFF),
        (8, 2, 1),
        (0xC, 1, 0),
        (0xE, 8, 0),
        (0x16, 4, 0xFFFF),
        (0x20, 8, (1 << 64) - 1),
        (0x28, 8, 0),
        (0x30, 8, 0),
        (0x1A, 2, 0),
        (0x1C, 4, 0),
        (0x40, 8, 0),
        (0x48, 8, 0),
        (0x50, 8, 0),
        (0x58, 8, 0),
    ):
        _write(context, address + offset, width, value)
    return address


def create_replay_task(
    context: ReplayTaskRebuildStorage,
    task_list: int,
    external_tag: int,
    ordinal: int,
    *,
    calls: ReplayTaskRebuildCalls,
) -> int:
    """Full1412691b0; tag1 alone allocates/prezeros144B before the actual ctor.

    task_list is the unused native RCX argument. The external tag is DX, not
    action type at task+e. Unsupported low16 tags return0 without any access.
    Actual reached allocation/constructor effects are required, including0
    allocator results. Native new-handler/C++EH semantics remain external.
    """
    _validate(context, task_list, external_tag, ordinal)
    _validate_calls(calls)
    if external_tag & 0xFFFF != 1:
        return 0
    allocation = _call(calls, 0x142D6BA78, (0x90,), width=8)
    if not allocation:
        return 0
    for offset in range(0, 0x90, 16):
        _write(context, allocation + offset, 16, 0)
    return _call(calls, 0x14112AA40, (allocation, ordinal & 0xFFFF), width=8)


def create_replay_task_list(
    context: ReplayTaskRebuildStorage,
    master: int,
    *,
    derived: bool,
    calls: ReplayTaskRebuildCalls,
) -> int:
    """Full14116ba60/141323ae0: allocate32B; actual base ctor; optional vtable.

    master is the unused RCX input to these particular factory bodies. Choosing
    this entry does not infer the target of an unobserved current virtual call.
    Nonnull-empty lists remain allocated objects with their own identities.
    """
    _validate(context, master)
    _validate_calls(calls)
    if type(derived) is not bool:
        raise ValueError("explicit base/derived factory choice required")
    allocation = _call(calls, 0x142D6BA78, (32,), width=8)
    if not allocation:
        return 0
    _write(context, allocation, 16, 0)
    _write(context, allocation + 16, 16, 0)
    if derived:
        _call(calls, 0x1412686D0, (allocation,))
        _write(context, allocation, 8, 0x1432BC398)
        return allocation
    return _call(calls, 0x1412686D0, (allocation,), width=8)


def copy_replay_task(
    context: ReplayTaskRebuildStorage,
    destination: int,
    source: int,
) -> None:
    """Full14112f830, including ordered16+8B copies of both sound descriptors.

    Vtable/tag/ordinal and ordinary padding are not copied. The complete24B
    sound descriptors are shallow copies, including native pointers/padding.
    Each source read precedes its matching store; overlap and partial failures
    retain earlier effects. No literal native fault/store-atomicity claim.
    """
    _validate(context, destination, source)
    for offset, width in (
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
        (0x40, 8),
        (0x48, 8),
        (0x50, 8),
        (0x58, 8),
        (0x60, 16),
        (0x70, 8),
        (0x78, 16),
        (0x88, 8),
        (0x38, 2),
    ):
        _write(context, destination + offset, width, _read(context, source + offset, width))


def bind_replay_task_construction(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
) -> ReplayTaskRebuildCalls:
    """Bind the seven actual ctor/factory/clone entries; unknown leaves delegate."""
    _validate(context)
    _validate_calls(calls)

    def dispatch(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        arities = {
            0x14147B480: 1,
            0x1412686D0: 1,
            0x14112AA40: 2,
            0x1412691B0: 3,
            0x14116BA60: 1,
            0x141323AE0: 1,
            0x14112F830: 2,
        }
        if target not in arities:
            if calls.call is None:
                raise UnresolvedReplayTaskRebuild(f"reached{target:x} is unavailable")
            return calls.call(target, args, data)
        if len(args) != arities[target] or data is not None:
            raise ValueError("malformed task construction call")
        if target == 0x14147B480:
            return construct_replay_task_descriptor(context, args[0])
        if target == 0x1412686D0:
            return construct_replay_task_list(context, args[0])
        if target == 0x14112AA40:
            return construct_replay_task(context, *args, calls=bound)
        if target == 0x1412691B0:
            return create_replay_task(context, *args, calls=bound)
        if target in (0x14116BA60, 0x141323AE0):
            return create_replay_task_list(
                context, args[0], derived=target == 0x141323AE0, calls=bound
            )
        copy_replay_task(context, *args)
        return None

    bound = ReplayTaskRebuildCalls(dispatch)
    return bound
