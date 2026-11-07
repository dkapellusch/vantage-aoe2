"""Build54800 saved Result string destruction over current owned storage.

Full116B1402a88a0 and5B1402a8920 alias from
tc-unit-ai-saved-result-element-source-v1. Current CRT effects are mandatory;
native LFENCE, faults, threading, native stack and C++ unwinding are excluded.
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

_U64 = (1 << 64) - 1


def destroy_replay_saved_string(
    context: ReplayTaskRebuildStorage,
    address: int,
    *,
    calls: ReplayTaskRebuildCalls,
    imports: ReplayTaskRebuildCalls | None = None,
) -> None:
    """Full116B1402a88a0: capacity gate, real sized free, then three resets.

    Capacity<=15 skips the data-pointer read/free. Otherwise capacity+1 wraps
    u64 before its large-allocation threshold. Length is never read. Resets
    write only lengthQWORD0, capacityQWORD15 and firstBYTE0, in that order.
    """
    _validate(context, calls, address)
    terminal = calls if imports is None else imports
    _validate(context, terminal)
    capacity = _read(context, address + 0x18, 8)
    if capacity > 15:
        pointer = _read(context, address, 8)
        size = capacity + 1 & _U64
        if size >= 0x1000:
            original = pointer
            pointer = _read(context, pointer - 8, 8)
            size = size + 0x27 & _U64
            if (original - pointer - 8) & _U64 > 31:
                _call(terminal, _read(context, 0x14319A060, 8), (0, 0, 0, 0, 0))
                raise UnresolvedReplayTaskRebuild(
                    "nonreturning saved string Watson returned before INT3"
                )
        _call(calls, 0x142D6BAB4, (pointer, size))
    _write(context, address + 0x10, 8, 0)
    _write(context, address + 0x18, 8, 15)
    _write(context, address, 1, 0)


def bind_replay_saved_string(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    *,
    imports: ReplayTaskRebuildCalls | None = None,
) -> ReplayTaskRebuildCalls:
    """Bind full string body/alias and a once-sampled current free import."""
    _validate(context, calls)
    terminal = calls if imports is None else imports
    _validate(context, terminal)

    def dispatch(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        arities = {0x1402A88A0: 1, 0x1402A8920: 1, 0x142D6BAB4: 2}
        if target not in arities:
            if calls.call is None:
                raise UnresolvedReplayTaskRebuild(f"reached{target:x} is unavailable")
            return calls.call(target, args, data)
        if len(args) != arities[target] or data is not None:
            raise ValueError("malformed saved string destruction call")
        _validate(context, calls, *args)
        if target != 0x142D6BAB4:
            destroy_replay_saved_string(context, *args, calls=bound, imports=terminal)
            return None
        imported = _read(context, 0x143199DD0, 8)
        if terminal.call is None:
            raise UnresolvedReplayTaskRebuild(f"reached{imported:x} is unavailable")
        return terminal.call(imported, args, None)

    bound = ReplayTaskRebuildCalls(dispatch)
    return bound
