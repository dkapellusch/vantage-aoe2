"""Build54800 full168B Player DWORD-array append140b53800.

The32B header is data/capacity/count/quantum, not a STDvector. Actual reserve,
current backing and reached import effects are mandatory. Source reads follow
reserve; payload aliases affect the later current-count increment. Native
register returns/flags, stack, faults/EH and concurrency are excluded. Wrapped
doubling that cannot terminate is an explicit finite-profile refusal.
"""

from __future__ import annotations

from vantage.replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
    _call,
    _read,
    _write,
)
from vantage.replay_unit_ai_base import _validate

_U64 = (1 << 64) - 1
_ENTRY, _RESERVE = 0x140B53800, 0x140B55580


def append_replay_player_dependency(
    context: ReplayTaskRebuildStorage,
    header: int,
    source: int,
    *,
    calls: ReplayTaskRebuildCalls,
) -> None:
    """Append a reached current DWORD and increment CURRENT count, including skips.

    Capacity and initial count are held through the growth calculation. The
    actual140b55580 binding may mutate storage; count/data and source payload
    are read afterward. Null source or computed destination skips the copy;
    the current count still increments modulo64. No residual RAX is claimed.
    """
    _validate(context, calls, header, source)
    capacity = _read(context, header + 8, 8)
    used = _read(context, header + 16, 8)
    if (used + 1) & _U64 > capacity:
        increase = (used - capacity + 1) & _U64
        if increase:
            quantum = _read(context, header + 24, 8) or 1
            required = (capacity + increase) & _U64
            geometric = capacity or 1
            while geometric < required:
                geometric = geometric * 2 & _U64
                if geometric == 0:
                    raise UnresolvedReplayTaskRebuild(
                        "nonterminating wrapped Player dependency growth excluded"
                    )
            rounded = (increase - 1 + quantum) & _U64
            rounded = (rounded - rounded % quantum + capacity) & _U64
            _call(calls, _RESERVE, (header, min(geometric, rounded)))
    count = _read(context, header + 16, 8)
    begin = _read(context, header, 8)
    destination = (begin + count * 4) & _U64
    if source and destination:
        _write(context, destination, 4, _read(context, source, 4))
    _write(context, header + 16, 8, _read(context, header + 16, 8) + 1)


def bind_replay_player_dependency_append(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
) -> ReplayTaskRebuildCalls:
    """Bind only140b53800; its actual140b55580 child remains required."""
    _validate(context, calls)

    def dispatch(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        if target != _ENTRY:
            if calls.call is None:
                raise UnresolvedReplayTaskRebuild(f"reached{target:x} is unavailable")
            return calls.call(target, args, data)
        if len(args) != 2 or data is not None:
            raise ValueError("malformed Player dependency append call")
        append_replay_player_dependency(context, *args, calls=calls)
        return None

    return ReplayTaskRebuildCalls(dispatch)
