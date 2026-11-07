"""Build54800 TaskList virtual deletion and pointer-vector release.

Source: world-envelope/task-list-delete-source-v1, three newly closed bodies
(198 bytes) and the separately verified71-byte base deleting wrapper. The
current clear/import effects remain real reached bindings; no World is restored.
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

_U64 = (1 << 64) - 1


def _validate(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    *values: int,
) -> None:
    if not isinstance(context, ReplayTaskRebuildStorage):
        raise ValueError("explicit current TaskList storage required")
    if not isinstance(calls, ReplayTaskRebuildCalls):
        raise ValueError("explicit actual TaskList deletion effects required")
    for value in values:
        _unsigned(value, 8, "TaskList deletion argument")


def release_replay_task_pointers(
    context: ReplayTaskRebuildStorage,
    vector: int,
    *,
    calls: ReplayTaskRebuildCalls,
) -> None:
    """Full1412686f0: null begin preserves tail; otherwise free before resetting.

    End is never read. Rounded current capacity bytes select ordinary or large
    release. Invalid metadata calls the current Watson target, with a returned
    error stopped before the verified CC. Earlier effects survive failures.
    """
    _validate(context, calls, vector)
    begin = _read(context, vector, 8)
    if not begin:
        return
    size = ((_read(context, vector + 16, 8) - begin) & _U64) & ~7
    pointer = begin
    if size >= 0x1000:
        pointer = _read(context, begin - 8, 8)
        size = (size + 0x27) & _U64
        if (begin - pointer - 8) & _U64 > 31:
            target = _read(context, 0x14319A060, 8)
            _call(calls, target, (0, 0, 0, 0, 0))
            raise RuntimeError(f"nonreturning helper{target:x} unexpectedly returned")
    _call(calls, 0x142D6BAB4, (pointer, size))
    for offset in (0, 8, 16):
        _write(context, vector + offset, 8, 0)


def destruct_replay_task_list(
    context: ReplayTaskRebuildStorage,
    task_list: int,
    *,
    calls: ReplayTaskRebuildCalls,
) -> None:
    """Full141268760: base vptr, actual clear, then vector release at held list+8."""
    _validate(context, calls, task_list)
    _write(context, task_list, 8, 0x1432B5EE8)
    _call(calls, 0x141269220, (task_list,))
    _call(calls, 0x1412686F0, ((task_list + 8) & _U64,))


def delete_replay_task_list(
    context: ReplayTaskRebuildStorage,
    task_list: int,
    flags: int,
    *,
    derived: bool,
    calls: ReplayTaskRebuildCalls,
) -> int:
    """Full141320510/141268d80: destroy first, bit0 optionally frees32B list.

    The returned held pointer remains the same token even after free. Choosing
    this entry does not resolve an unobserved current vtable. The base wrapper
    performs its vptr/clear/release inline; the derived wrapper calls141268760.
    """
    _validate(context, calls, task_list, flags)
    if type(derived) is not bool:
        raise ValueError("explicit base/derived deleting entry required")
    if derived:
        _call(calls, 0x141268760, (task_list,))
    else:
        _write(context, task_list, 8, 0x1432B5EE8)
        _call(calls, 0x141269220, (task_list,))
        _call(calls, 0x1412686F0, ((task_list + 8) & _U64,))
    if flags & 1:
        _call(calls, 0x142D6BAB4, (task_list, 32))
    return task_list


def bind_replay_task_list_deletion(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
) -> ReplayTaskRebuildCalls:
    """Bind four deletion entries over actual clear/current import bindings.

    Normally the lower dispatcher is bind_replay_task_list_storage, which
    implements clear and reads the current free IAT when reached. This layer
    does not cache/import-resolve a second time. Unknown targets delegate or
    refuse at reach; no supplied callback is silently replaced with success.
    """
    _validate(context, calls)
    arities = {0x1412686F0: 1, 0x141268760: 1, 0x141320510: 2, 0x141268D80: 2}

    def dispatch(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        if target not in arities:
            if calls.call is None:
                raise UnresolvedReplayTaskRebuild(f"reached{target:x} is unavailable")
            return calls.call(target, args, data)
        if len(args) != arities[target] or data is not None:
            raise ValueError("malformed TaskList deletion call")
        if target == 0x1412686F0:
            release_replay_task_pointers(context, args[0], calls=bound)
        elif target == 0x141268760:
            destruct_replay_task_list(context, args[0], calls=bound)
        else:
            return delete_replay_task_list(
                context, *args, derived=target == 0x141320510, calls=bound
            )
        return None

    bound = ReplayTaskRebuildCalls(dispatch)
    return bound
