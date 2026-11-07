"""Build54800 complete262B Moving saved-point buffer caller14121a010.

Source: moving-positive-point-source-v1. Actual allocator142d6c268 and
one-argument free142d6c270 effects remain mandatory. The existing source-proven
constructor-support/zone-queue binders can provide those genuine alias/current
IAT routes. No numeric FP, stream or point-count update is invented. Native
physical spills/EH tracking, faults, threading and whole restore are excluded.
"""

from __future__ import annotations

from .replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
    _call,
    _read,
    _signed,
    _write,
)
from .replay_unit_ai_base import _validate

_U32 = (1 << 32) - 1
_U64 = (1 << 64) - 1
_ENTRY = 0x14121A010


def resize_replay_saved_moving_points(
    context: ReplayTaskRebuildStorage,
    subject: int,
    requested: int,
    *,
    calls: ReplayTaskRebuildCalls,
) -> int:
    """Full70-instruction normal entry; return1 only after new publication.

    Nonpositive lowEDX or sufficient positive current capacity returns0. That
    surprising zero is the original convention, not generic ensure success.
    Each copied record holds its current source base across the QWORD store,
    then reads that same base's current DWORD tail. Capacity398 publishes
    before pointer388; pointcount394 is never written. Partial effects survive
    failures, without synthetic cleanup/rollback. Stack40 is EH-only metadata
    whose address is never passed to a normal child; it is not a logical frame.
    """
    _validate(context, calls, subject, requested)
    count = _signed(requested & _U32, 4)
    if count <= 0:
        return 0
    capacity = _signed(_read(context, subject + 0x398, 4), 4)
    if capacity >= count and capacity > 0:
        return 0
    # MUL/CMOVB saturates on overflow, although positive signed32 count bounds
    # make this product at most5fffffff4 in the admitted actual entry ABI.
    allocation = _call(calls, 0x142D6C268, (min(count * 12, _U64),), width=8)
    if not allocation:
        return 0
    for index in range(count):
        destination = (allocation + index * 12) & _U64
        _write(context, destination, 8, 0)
        _write(context, destination + 8, 4, 0)
    if _read(context, subject + 0x388, 8):
        counter, ordinal, offset = 0, 0, 0
        while _signed(ordinal, 8) < count:
            if _signed(counter, 4) >= _signed(_read(context, subject + 0x394, 4), 4):
                break
            source = _read(context, subject + 0x388, 8)
            _write(context, allocation + offset, 8, _read(context, source + offset, 8))
            _write(context, allocation + offset + 8, 4, _read(context, source + offset + 8, 4))
            counter = (counter + 1) & _U32
            ordinal = (ordinal + 1) & _U64
            offset = (offset + 12) & _U64
        _call(calls, 0x142D6C270, (_read(context, subject + 0x388, 8),))
    _write(context, subject + 0x398, 4, count)
    _write(context, subject + 0x388, 8, allocation)
    return 1


def bind_replay_moving_saved_points(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
) -> ReplayTaskRebuildCalls:
    """Bind only14121a010; actual allocator/free/other children delegate/refuse."""
    _validate(context, calls)

    def dispatch(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        if target != _ENTRY:
            if calls.call is None:
                raise UnresolvedReplayTaskRebuild(f"reached{target:x} is unavailable")
            return calls.call(target, args, data)
        if len(args) != 2 or data is not None:
            raise ValueError("malformed Moving saved-point call")
        return resize_replay_saved_moving_points(context, *args, calls=bound)

    bound = ReplayTaskRebuildCalls(dispatch)
    return bound
