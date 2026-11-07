"""Build54800 Base saved-reader attachment, sprite and notification helpers.

Complete80B141248810,65B14124dd00 and30B141868cb0 bodies are retained in
base-saved-reader-source-review-v1. Reached allocation, constructor, reset
and notification descendants require actual effects. This logical profile
excludes physical stack/register, CPU fault/EH and concurrent execution claims.
"""

from __future__ import annotations

from .replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
    _call,
    _read,
    _write,
)
from .replay_unit_ai_base import _validate


def set_replay_base_saved_attachment(
    context: ReplayTaskRebuildStorage,
    subject: int,
    target: int,
    *,
    calls: ReplayTaskRebuildCalls,
) -> None:
    """Full80B141248810, including the general nonnull attachment branches.

    Identity skips all later accesses. Otherwise publish138 first. A nonnull
    target always supplies BYTE9 after the current141 read, even when141==0;
    only an active flag reaches the current140 comparison. Changes require
    the real1412475d0 tail after the exact byte stores. No fresh default is used.
    """
    _validate(context, calls, subject, target)
    if _read(context, subject + 0x138, 8) == target:
        return
    _write(context, subject + 0x138, 8, target)
    active = _read(context, subject + 0x141, 1)
    if not target:
        if not active:
            return
        _write(context, subject + 0x141, 1, 0)
    else:
        kind = _read(context, target + 9, 1)
        if active and _read(context, subject + 0x140, 1) == kind:
            return
        _write(context, subject + 0x140, 1, kind)
        _write(context, subject + 0x141, 1, 1)
    _call(calls, 0x1412475D0, (subject,))


def create_replay_base_saved_sprite(
    context: ReplayTaskRebuildStorage,
    subject: int,
    *,
    calls: ReplayTaskRebuildCalls,
) -> int:
    """Full65B14124dd00: allocation, two16B zero stores, actual constructor RAX.

    Null allocation returns0. The original subject is held across allocation.
    A nonnull allocation is initialized by two separate MOVUPS-width effects
    before the mandatory141480d30 call. Its raw return may differ from allocation.
    The surrounding Base reader, rather than this helper, publishes the result.
    """
    _validate(context, calls, subject)
    pointer = _call(calls, 0x142D6BA78, (32,), width=8)
    if not pointer:
        return 0
    _write(context, pointer, 16, 0)
    _write(context, pointer + 16, 16, 0)
    return _call(calls, 0x141480D30, (pointer, subject), width=8)


def notify_replay_base_saved_object(
    context: ReplayTaskRebuildStorage,
    subject: int,
    *,
    calls: ReplayTaskRebuildCalls,
) -> None:
    """Full30B141868cb0: actual service getter then tail with held subject.

    Retained14185b6d0 source proves that it consumes no incoming argument.
    Its raw pointer return supplies RCX to14185ce10; held subject suppliesRDX.
    No singleton initialization, current service or notification effect is faked.
    The tail's incidental return is outside this effect-only interface.
    """
    _validate(context, calls, subject)
    service = _call(calls, 0x14185B6D0, (), width=8)
    _call(calls, 0x14185CE10, (service, subject))


def bind_replay_base_saved_support(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
) -> ReplayTaskRebuildCalls:
    """Bind the three full callers, delegating actual descendants or refusing."""
    _validate(context, calls)

    def dispatch(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        arities = {0x141248810: 2, 0x14124DD00: 1, 0x141868CB0: 1}
        if target not in arities:
            if calls.call is None:
                raise UnresolvedReplayTaskRebuild(f"reached{target:x} is unavailable")
            return calls.call(target, args, data)
        if len(args) != arities[target] or data is not None:
            raise ValueError("malformed Base saved-support call")
        if target == 0x141248810:
            set_replay_base_saved_attachment(context, *args, calls=bound)
        elif target == 0x14124DD00:
            return create_replay_base_saved_sprite(context, *args, calls=bound)
        else:
            notify_replay_base_saved_object(context, *args, calls=bound)
        return None

    bound = ReplayTaskRebuildCalls(dispatch)
    return bound
