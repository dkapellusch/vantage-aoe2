"""Build54800 complete212B Player postfactory reset1417394d0.

Authority: player-postfactory-source-v1. The World loader reaches this reset
before checking its factory Result. Ordered partial stores are observable;
native faults, physical registers, EH and concurrent access are excluded.
"""

from __future__ import annotations

from .replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
    _write,
)
from .replay_unit_ai_base import _validate


def reset_replay_player_postfactory(context: ReplayTaskRebuildStorage, subject: int) -> None:
    """Apply all46 original stores, preserving unwritten bytes and store order."""
    _validate(context, ReplayTaskRebuildCalls(None), subject)
    _write(context, subject + 0x270, 8, (1 << 64) - 1)
    _write(context, subject + 0x27C, 2, 0xFFFF)
    _write(context, subject + 0x278, 4, 0xFFFFFFFF)
    _write(context, subject + 0x48C, 4, 0)
    _write(context, subject + 0x2A0, 8, 0)
    base = subject + 0x2A8
    for _ in range(3):
        for offset in range(0, 0x70, 0x10):
            _write(context, base + offset, 16, 0)
        base += 0x80
        _write(context, base - 0x10, 16, 0)
    for offset in range(0, 0x60, 0x10):
        _write(context, base + offset, 16, 0)
    for offset in range(0x491, 0x501, 0x10):
        _write(context, subject + offset, 16, 0)
    for offset, width in ((0x501, 8), (0x509, 4), (0x50D, 2), (0x50F, 1)):
        _write(context, subject + offset, width, 0)


def bind_replay_player_postfactory(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
) -> ReplayTaskRebuildCalls:
    """Bind the exact leaf; retain required delegates for all other targets."""
    _validate(context, calls)

    def dispatch(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        if target != 0x1417394D0:
            if calls.call is None:
                raise UnresolvedReplayTaskRebuild(f"reached{target:x} is unavailable")
            return calls.call(target, args, data)
        if len(args) != 1 or data is not None:
            raise ValueError("malformed Player postfactory reset call")
        reset_replay_player_postfactory(context, args[0])
        return None

    return ReplayTaskRebuildCalls(dispatch)
