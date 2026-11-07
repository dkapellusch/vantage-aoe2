"""Build54800 group/criterion bucket storage, with real current backing/effects.

Sources: task-group-lookup-frontier-v1, task-group-lookup-leaves-source-v1,
task-group-rehash-release-source-v1 and retained bf400/a5bd0 siblings. The nine
full bodies have verified scalar phases; current runtime/locals remain explicit.
Native stack aliases, heap identity, faults, traps and C++ EH are excluded.
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
    _signed,
    _unsigned,
    _write,
)

_U64 = (1 << 64) - 1
LocalBinding = Callable[[memoryview], AbstractContextManager[int]]


def _validate(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    *addresses: int,
) -> None:
    if not isinstance(context, ReplayTaskRebuildStorage):
        raise ValueError("explicit current task storage required")
    if not isinstance(calls, ReplayTaskRebuildCalls):
        raise ValueError("explicit bucket storage calls required")
    for address in addresses:
        _unsigned(address, 8, "group storage address")


def _error(calls: ReplayTaskRebuildCalls, target: int, args: tuple[int, ...] = ()) -> None:
    _call(calls, target, args)
    raise RuntimeError(f"nonreturning helper{target:x} unexpectedly returned")


def _resize(
    context: ReplayTaskRebuildStorage,
    header: int,
    requested: int,
    value: int,
    calls: ReplayTaskRebuildCalls,
    fill_target: int,
    release_target: int,
) -> None:
    local = bytearray(value.to_bytes(8, "little"))
    begin = _read(context, header, 8)
    end = _read(context, header + 8, 8)
    size = (_signed((end - begin) & _U64, 8) >> 3) & _U64
    if size >= requested:
        _call(calls, fill_target, (begin, end), memoryview(local))
        return
    if requested > 0x1FFFFFFFFFFFFFFF:
        _error(calls, 0x1402A9460)
    byte_count = (requested * 8) & _U64
    allocation = _call(calls, 0x1402A94D0, (byte_count,), width=8)
    current_begin = _read(context, header, 8)
    capacity_end = _read(context, header + 0x10, 8)
    capacity = (_signed((capacity_end - current_begin) & _U64, 8) >> 3) & _U64
    if capacity:
        _call(calls, release_target, (header, current_begin, capacity))
    new_end = (allocation + byte_count) & _U64
    _write(context, header, 8, allocation)
    _write(context, header + 8, 8, new_end)
    _write(context, header + 0x10, 8, new_end)
    while allocation != new_end:
        _write(context, allocation, 8, value)
        allocation = (allocation + 8) & _U64


def resize_replay_task_group_buckets(
    context: ReplayTaskRebuildStorage,
    header: int,
    requested: int,
    value: int,
    *,
    calls: ReplayTaskRebuildCalls,
) -> None:
    """Full1412bf330: R8 VALUE; current release inputs follow allocation.

    Reuse fills the entire held range without resizing, even for requested0.
    Growth calls release with header/currentbegin/SARcapacity, commits all three
    header words, then fills the held allocation with the held VALUE. Callback
    effects and public aliases follow those phases. Returned error stops before
    verified adjacent CC; native exception/unwinding behavior is excluded.
    """
    _validate(context, calls, header)
    _unsigned(requested, 8, "requested group bucket qwords")
    _unsigned(value, 8, "group bucket fill value")
    _resize(context, header, requested, value, calls, 0x1412A5B40, 0x1412C6430)


def resize_replay_task_criterion_buckets(
    context: ReplayTaskRebuildStorage,
    header: int,
    requested: int,
    value: int,
    *,
    calls: ReplayTaskRebuildCalls,
) -> None:
    """Full1412bf260, using its distinct exact fill/release entries."""
    _validate(context, calls, header)
    _unsigned(requested, 8, "requested criterion bucket qwords")
    _unsigned(value, 8, "criterion bucket fill value")
    _resize(context, header, requested, value, calls, 0x1412A5AB0, 0x1412C63D0)


def resize_replay_task_group_rehash_buckets(
    context: ReplayTaskRebuildStorage,
    header: int,
    requested: int,
    value: int,
    *,
    calls: ReplayTaskRebuildCalls,
) -> None:
    """Full1412bf400, the group rehash's actual storage initializer."""
    _validate(context, calls, header)
    _unsigned(requested, 8, "requested group rehash bucket qwords")
    _unsigned(value, 8, "group rehash bucket fill value")
    _resize(context, header, requested, value, calls, 0x1412A5BD0, 0x1412C6490)


def _release(
    context: ReplayTaskRebuildStorage,
    begin: int,
    capacity: int,
    calls: ReplayTaskRebuildCalls,
) -> None:
    byte_count = (capacity * 8) & _U64
    pointer = begin
    if byte_count >= 0x1000:
        pointer = _read(context, begin - 8, 8)
        byte_count = (byte_count + 0x27) & _U64
        if (begin - pointer - 8) & _U64 > 31:
            target = _read(context, 0x14319A060, 8)
            _error(calls, target, (0, 0, 0, 0, 0))
    _call(calls, 0x142D6BAB4, (pointer, byte_count))


def release_replay_task_group_buckets(
    context: ReplayTaskRebuildStorage,
    header: int,
    begin: int,
    capacity: int,
    *,
    calls: ReplayTaskRebuildCalls,
) -> None:
    """Full1412c6430: ignores RCX/header; no null guard or header reset.

    RDX/begin and R8/capacity determine the real free pointer/byte count. A
    reached invalid large header reads the current Watson target before call.
    Returned error stops before its verified CC; tail free has no later stores.
    """
    _validate(context, calls, header, begin)
    _unsigned(capacity, 8, "group bucket capacity qwords")
    _release(context, begin, capacity, calls)


def release_replay_task_criterion_buckets(
    context: ReplayTaskRebuildStorage,
    header: int,
    begin: int,
    capacity: int,
    *,
    calls: ReplayTaskRebuildCalls,
) -> None:
    """Full1412c63d0 with the same separately verified scalar phases."""
    _validate(context, calls, header, begin)
    _unsigned(capacity, 8, "criterion bucket capacity qwords")
    _release(context, begin, capacity, calls)


def release_replay_task_group_rehash_buckets(
    context: ReplayTaskRebuildStorage,
    header: int,
    begin: int,
    capacity: int,
    *,
    calls: ReplayTaskRebuildCalls,
) -> None:
    """Full1412c6490 with the same separately verified scalar phases."""
    _validate(context, calls, header, begin)
    _unsigned(capacity, 8, "group rehash bucket capacity qwords")
    _release(context, begin, capacity, calls)


def bind_replay_task_group_storage(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    *,
    bind_local: LocalBinding,
) -> ReplayTaskRebuildCalls:
    """Bind all nine entries with live scoped locals and actual runtime leaves.

    All three132B fills have byte-identical bodies, admitted here through the
    existing finite nonwrapping qword-range API with DF0. Their input local must
    remain the actual supplied writable8B view in current backing. Enter does
    not read its bytes; exit cannot suppress body errors. Unknown targets still
    delegate or refuse at reach. This does not restore a World or its identities.
    """
    _validate(context, calls, context.subject)
    if not callable(bind_local):
        raise ValueError("actual scoped live-local binding required")
    initializers = {
        0x1412BF330: resize_replay_task_group_buckets,
        0x1412BF260: resize_replay_task_criterion_buckets,
        0x1412BF400: resize_replay_task_group_rehash_buckets,
    }
    releases = {
        0x1412C6430: release_replay_task_group_buckets,
        0x1412C63D0: release_replay_task_criterion_buckets,
        0x1412C6490: release_replay_task_group_rehash_buckets,
    }

    def dispatch(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        if target in initializers or target in releases:
            if len(args) != 3 or data is not None:
                raise ValueError("bucket initializer/release requires three scalar arguments")
            body = initializers[target] if target in initializers else releases[target]
            body(context, *args, calls=bound)
        elif target in (0x1412A5B40, 0x1412A5AB0, 0x1412A5BD0):
            if (
                len(args) != 2
                or data is None
                or data.ndim != 1
                or data.format != "B"
                or not data.c_contiguous
                or data.readonly
                or len(data) != 8
            ):
                raise ValueError("bucket fill requires begin/end and writable contiguous8B view")
            manager = bind_local(data)
            address = manager.__enter__()
            try:
                _unsigned(address, 8, "bound bucket fill address")
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
