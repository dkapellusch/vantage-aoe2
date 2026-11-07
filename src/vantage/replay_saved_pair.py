"""Build54800 shared status/control-pair assignment, full131B14090d270.

Current scalar backing, explicit engine DWORD atomic effects and reached
control virtuals are required. This sequential logical interface excludes
native CPU flags, fault/EH ordering, concurrency and complete restore claims.
"""

from __future__ import annotations

from .replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
    _read,
    _write,
)
from .replay_unit_ai_base import _validate
from .replay_unit_ai_map import ReplayUnitAIMapAtomics, _atomic, _release


def assign_replay_saved_pair(
    context: ReplayTaskRebuildStorage,
    destination: int,
    source: int,
    *,
    calls: ReplayTaskRebuildCalls,
    atomics: ReplayUnitAIMapAtomics,
) -> int:
    """Copy the current pair with strong acquisition before old-control release.

    The initial source control is incremented; a later current source-control
    read supplies the copied word. The old destination control is held between
    those reads. Both destination stores precede release of that held control.
    Identity and overlapping pairs follow the same accesses. Earlier writes,
    atomic effects and callbacks remain visible if a later operation raises.
    """
    _validate(context, calls, destination, source)
    if not isinstance(atomics, ReplayUnitAIMapAtomics):
        raise ValueError("actual saved-pair shared-count bindings required")
    control = _read(context, source + 8, 8)
    if control:
        _atomic(atomics, control + 8, 1)
    previous = _read(context, destination + 8, 8)
    current = _read(context, source + 8, 8)
    status = _read(context, source, 8)
    _write(context, destination, 8, status)
    _write(context, destination + 8, 8, current)
    if previous:
        _release(context, previous, calls, atomics)
    return destination


def bind_replay_saved_pair(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    *,
    atomics: ReplayUnitAIMapAtomics,
) -> ReplayTaskRebuildCalls:
    """Bind the complete assignment body; delegate unknown targets unchanged."""
    _validate(context, calls)
    if not isinstance(atomics, ReplayUnitAIMapAtomics):
        raise ValueError("actual saved-pair shared-count bindings required")

    def dispatch(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        if target != 0x14090D270:
            if calls.call is None:
                raise UnresolvedReplayTaskRebuild(f"reached{target:x} is unavailable")
            return calls.call(target, args, data)
        if len(args) != 2 or data is not None:
            raise ValueError("malformed saved-pair assignment call")
        return assign_replay_saved_pair(context, *args, calls=bound, atomics=atomics)

    bound = ReplayTaskRebuildCalls(dispatch)
    return bound
