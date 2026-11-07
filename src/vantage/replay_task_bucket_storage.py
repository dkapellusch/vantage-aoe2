"""Build54800 bucket-vector resize/release and concrete container leaf routing.

Sources: world-envelope/task-bucket-storage-source-v1 and
task-bucket-release-source-v1. Actual allocator/CRT/error implementations and
live local-address bindings remain mandatory; no initialized World is inferred.
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager

from .replay_task_buckets import (
    fill_replay_task_buckets,
    rehash_replay_task_byte,
    rehash_replay_task_pair,
)
from .replay_task_containers import (
    ReplayTaskContainerCalls,
    UnresolvedReplayTaskContainer,
    _call,
    _error,
    _validate,
    _view,
)
from .replay_task_rebuild import ReplayTaskRebuildStorage, _read, _signed, _unsigned, _write

_U64 = (1 << 64) - 1


def _resize(
    context: ReplayTaskRebuildStorage,
    header: int,
    requested: int,
    value: int,
    calls: ReplayTaskContainerCalls,
    *,
    pair: bool,
) -> None:
    local = bytearray(value.to_bytes(8, "little"))
    begin = _read(context, header, 8)
    end = _read(context, header + 8, 8)
    size = (_signed((end - begin) & _U64, 8) >> 3) & _U64
    if size >= requested:
        _call(calls, 0x141143790 if pair else 0x141143820, (begin, end), memoryview(local))
        return
    if requested > 0x1FFFFFFFFFFFFFFF:
        _error(calls, 0x1402A9460)
    byte_count = (requested * 8) & _U64
    allocation = _call(calls, 0x1402A94D0, (byte_count,), width=8)
    current_begin = _read(context, header, 8)
    capacity_end = _read(context, header + 0x10, 8)
    capacity = (_signed((capacity_end - current_begin) & _U64, 8) >> 3) & _U64
    if capacity:
        _call(calls, 0x1411526A0 if pair else 0x141152700, (header, current_begin, capacity))
    new_end = (allocation + byte_count) & _U64
    _write(context, header, 8, allocation)
    _write(context, header + 8, 8, new_end)
    _write(context, header + 0x10, 8, new_end)
    while allocation != new_end:
        _write(context, allocation, 8, value)
        allocation = (allocation + 8) & _U64


def resize_replay_task_pair_buckets(
    context: ReplayTaskRebuildStorage,
    header: int,
    requested: int,
    value: int,
    *,
    calls: ReplayTaskContainerCalls,
) -> None:
    """Full14114d5c0; R8 is a scalar VALUE, not a source-address argument.

    Reuse fills the whole held old range without resizing. Growth holds the
    requested byte count/value, rereads begin/capacity after allocation, releases
    using all three actual arguments, commits the header, then scalar-fills.
    Successful coherent backing/ABI calls are premises; native faults, stack
    aliases and C++ exceptional allocation cleanup are excluded.
    """
    _validate(context, calls, header)
    _unsigned(requested, 8, "requested bucket qword count")
    _unsigned(value, 8, "bucket fill value")
    _resize(context, header, requested, value, calls, pair=True)


def resize_replay_task_byte_buckets(
    context: ReplayTaskRebuildStorage,
    header: int,
    requested: int,
    value: int,
    *,
    calls: ReplayTaskContainerCalls,
) -> None:
    """Full14114d690 under the same effective backing/leaf premises as pair."""
    _validate(context, calls, header)
    _unsigned(requested, 8, "requested bucket qword count")
    _unsigned(value, 8, "bucket fill value")
    _resize(context, header, requested, value, calls, pair=False)


def _release(
    context: ReplayTaskRebuildStorage,
    begin: int,
    capacity_count: int,
    calls: ReplayTaskContainerCalls,
) -> None:
    byte_count = (capacity_count * 8) & _U64
    pointer = begin
    if byte_count >= 0x1000:
        pointer = _read(context, begin - 8, 8)
        byte_count = (byte_count + 0x27) & _U64
        if (begin - pointer - 8) & _U64 > 31:
            target = _read(context, 0x14319A060, 8)
            _error(calls, target, (0, 0, 0, 0, 0))
    _call(calls, 0x142D6BAB4, (pointer, byte_count))


def release_replay_task_pair_buckets(
    context: ReplayTaskRebuildStorage,
    header: int,
    begin: int,
    capacity_count: int,
    *,
    calls: ReplayTaskContainerCalls,
) -> None:
    """Full1411526a0: ignores RCX/header; consumes RDX/begin and R8/count.

    No null guard or header read/reset exists. The known free chain receives
    the current original/aligned pointer and computed byte count. Returned free
    completes normally. Unexpected Watson return raises before the native INT3;
    native traps/exception cleanup are excluded, as in the container interface.
    """
    _validate(context, calls, header, begin)
    _unsigned(capacity_count, 8, "bucket capacity qword count")
    _release(context, begin, capacity_count, calls)


def release_replay_task_byte_buckets(
    context: ReplayTaskRebuildStorage,
    header: int,
    begin: int,
    capacity_count: int,
    *,
    calls: ReplayTaskContainerCalls,
) -> None:
    """Full141152700; same RDX/R8 consumption and ignored header as pair."""
    _validate(context, calls, header, begin)
    _unsigned(capacity_count, 8, "bucket capacity qword count")
    _release(context, begin, capacity_count, calls)


def bind_replay_task_bucket_leaves(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskContainerCalls,
    *,
    bind_local: Callable[[memoryview], AbstractContextManager[int]],
) -> ReplayTaskContainerCalls:
    """Route real rehash/resize/release/fill bodies into the prefix containers.

    bind_local(view) must expose that LIVE8B view at its yielded u64 address in
    this context's read/write backing for the full call scope. A detached copy
    or unbacked token is not a binding. Nested mappings must restore their prior
    bindings and preserve unrelated backing. No source address is invented and
    no alias path is skipped. The generic fill still reads its actual address.

    Mapping exit runs on success/failure; a truthy exit cannot suppress a body
    error. Exit failures propagate with preceding effects intact. Native stack
    addresses/faults/unwinding are excluded. Unknown leaves delegate to actual
    supplied allocator/free/move/ceil/error bindings, or fail when unavailable.
    """
    _validate(context, calls)
    if not callable(bind_local):
        raise ValueError("actual scoped live local-address binding required")

    def dispatch(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        if target in (0x14114D760, 0x14114D970):
            if len(args) != 2 or data is not None:
                raise ValueError("rehash requires map/count arguments")
            rehash = rehash_replay_task_pair if target == 0x14114D760 else rehash_replay_task_byte
            rehash(context, args[0], args[1], calls=bound)
        elif target in (0x14114D5C0, 0x14114D690):
            if len(args) != 3 or data is not None:
                raise ValueError("bucket resize requires header/count/value arguments")
            resize = (
                resize_replay_task_pair_buckets
                if target == 0x14114D5C0
                else resize_replay_task_byte_buckets
            )
            resize(context, args[0], args[1], args[2], calls=bound)
        elif target in (0x1411526A0, 0x141152700):
            if len(args) != 3 or data is not None:
                raise ValueError("bucket release requires header/begin/capacity arguments")
            release = (
                release_replay_task_pair_buckets
                if target == 0x1411526A0
                else release_replay_task_byte_buckets
            )
            release(context, args[0], args[1], args[2], calls=bound)
        elif target in (0x141143790, 0x141143820):
            if len(args) != 2 or data is None:
                raise ValueError("bucket fill requires begin/end and current8B local view")
            _view(data, 8)
            manager = bind_local(data)
            address = manager.__enter__()
            try:
                _unsigned(address, 8, "bound local address")
                fill_replay_task_buckets(context, args[0], args[1], address)
            except BaseException as error:
                manager.__exit__(type(error), error, error.__traceback__)
                raise
            else:
                manager.__exit__(None, None, None)
        else:
            if calls.call is None:
                raise UnresolvedReplayTaskContainer(f"reached{target:x} is unavailable")
            return calls.call(target, args, data)
        return None

    bound = ReplayTaskContainerCalls(dispatch, calls.mxcsr)
    return bound
