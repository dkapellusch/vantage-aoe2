"""Build54800 task-group destruction and its source-identical bucket fill.

Sources: task-group-clear-source-v1, task-group-child-source-v1 and
task-group-member-source-v1. Successful current storage/CRT bindings are
explicit. Native heap identity, LFENCE/fault behavior, C++ unwinding and trap
resumption are outside this scalar interface.
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager

from .replay_task_buckets import fill_replay_task_buckets
from .replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
    _call,
    _read,
    _unsigned,
    _write,
)

_U64 = (1 << 64) - 1
LocalBinding = Callable[[memoryview], AbstractContextManager[int]]


def _validate(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    address: int,
) -> None:
    if not isinstance(context, ReplayTaskRebuildStorage):
        raise ValueError("explicit current task storage required")
    if not isinstance(calls, ReplayTaskRebuildCalls):
        raise ValueError("explicit cleanup calls required")
    _unsigned(address, 8, "task cleanup address")


def _destroy_vector(
    context: ReplayTaskRebuildStorage,
    header: int,
    calls: ReplayTaskRebuildCalls,
    mask: int,
) -> None:
    begin = _read(context, header, 8)
    if not begin:
        return
    byte_count = (_read(context, header + 0x10, 8) - begin) & _U64 & mask
    pointer = begin
    if byte_count >= 0x1000:
        pointer = _read(context, begin - 8, 8)
        byte_count = (byte_count + 0x27) & _U64
        if (begin - pointer - 8) & _U64 > 31:
            target = _read(context, 0x14319A060, 8)
            _call(calls, target, (0, 0, 0, 0, 0))
            raise RuntimeError(f"nonreturning helper{target:x} unexpectedly returned")
    _call(calls, 0x142D6BAB4, (pointer, byte_count))
    _write(context, header, 8, 0)
    _write(context, header + 8, 8, 0)
    _write(context, header + 0x10, 8, 0)


def destroy_replay_task_vector4(
    context: ReplayTaskRebuildStorage,
    header: int,
    *,
    calls: ReplayTaskRebuildCalls,
) -> None:
    """Full1402bd6f0; null begin preserves all fields without reading end/cap.

    Nonnull capacity bytes round down to4, with the actual large-allocation
    backpointer and unsigned delta guard. Free precedes all three zero stores;
    the end field is never read. Native LFENCE is outside the scalar profile.
    """
    _validate(context, calls, header)
    _destroy_vector(context, header, calls, ~3)


def destroy_replay_task_vector8(
    context: ReplayTaskRebuildStorage,
    header: int,
    *,
    calls: ReplayTaskRebuildCalls,
) -> None:
    """Full1412a6710 and1412a66a0, with verified equivalent ordered effects.

    These distinct108B bodies differ in relative call operands. Neither has
    LFENCE. Capacity rounds down to8; all other scalar phases match vector4.
    """
    _validate(context, calls, header)
    _destroy_vector(context, header, calls, ~7)


def destroy_replay_task_group_child(
    context: ReplayTaskRebuildStorage,
    child: int,
    *,
    calls: ReplayTaskRebuildCalls,
) -> None:
    """Full1412a71d0; current head follows member48 destruction.

    Detach, save next before each18B node free, then free the reread current
    sentinel. Vector18 destruction precedes the final vector0 tail call.
    Head/count fields are not reset, and effects are not rolled back on error.
    """
    _validate(context, calls, child)
    _call(calls, 0x1412A66A0, (child + 0x48,))
    head = _read(context, child + 0x38, 8)
    last = _read(context, head + 8, 8)
    _write(context, last, 8, 0)
    node = _read(context, head, 8)
    while node:
        following = _read(context, node, 8)
        _call(calls, 0x142D6BAB4, (node, 0x18))
        node = following
    head = _read(context, child + 0x38, 8)
    _call(calls, 0x142D6BAB4, (head, 0x18))
    _call(calls, 0x1402BD6F0, (child + 0x18,))
    _call(calls, 0x1402BD6F0, (child,))


def destroy_replay_task_group_map(
    context: ReplayTaskRebuildStorage,
    head_address: int,
    *,
    calls: ReplayTaskRebuildCalls,
) -> None:
    """Full1412a6be0; no null/count gate or header reset.

    Detach the original sentinel, hold next before child28 destruction/freea0,
    then tail-free the current sentinel reread from the original input address.
    """
    _validate(context, calls, head_address)
    head = _read(context, head_address, 8)
    last = _read(context, head + 8, 8)
    _write(context, last, 8, 0)
    node = _read(context, head, 8)
    while node:
        following = _read(context, node, 8)
        _call(calls, 0x1412A71D0, (node + 0x28,))
        _call(calls, 0x142D6BAB4, (node, 0xA0))
        node = following
    head = _read(context, head_address, 8)
    _call(calls, 0x142D6BAB4, (head, 0xA0))


def bind_replay_task_group_cleanup(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    *,
    bind_local: LocalBinding,
) -> ReplayTaskRebuildCalls:
    """Bind all six reached bodies, preserving current storage and unknown leaves.

    Fill1412a5bd0 has the exact132B body of the existing141143790 fill. Its
    current writable8B local is mapped for the full call, without eager reads
    or exception suppression. Unknown targets delegate or refuse at reach.
    """
    _validate(context, calls, context.subject)
    if not callable(bind_local):
        raise ValueError("actual scoped live-local binding required")
    bodies = {
        0x1402BD6F0: destroy_replay_task_vector4,
        0x1412A6710: destroy_replay_task_vector8,
        0x1412A66A0: destroy_replay_task_vector8,
        0x1412A71D0: destroy_replay_task_group_child,
        0x1412A6BE0: destroy_replay_task_group_map,
    }

    def dispatch(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        if target in bodies:
            if len(args) != 1 or data is not None:
                raise ValueError("cleanup body requires one pointer argument")
            bodies[target](context, args[0], calls=bound)
        elif target == 0x1412A5BD0:
            if (
                len(args) != 2
                or data is None
                or data.ndim != 1
                or data.format != "B"
                or not data.c_contiguous
                or data.readonly
                or len(data) != 8
            ):
                raise ValueError("group fill requires begin/end and writable contiguous8B view")
            manager = bind_local(data)
            address = manager.__enter__()
            try:
                _unsigned(address, 8, "bound group fill address")
                fill_replay_task_buckets(context, args[0], args[1], address)
            except BaseException as error:
                manager.__exit__(type(error), error, error.__traceback__)
                raise
            else:
                manager.__exit__(None, None, None)
        else:
            if calls.call is None:
                raise UnresolvedReplayTaskRebuild(f"reached{target:x} is unavailable")
            return calls.call(target, args, data)
        return None

    bound = ReplayTaskRebuildCalls(dispatch)
    return bound
