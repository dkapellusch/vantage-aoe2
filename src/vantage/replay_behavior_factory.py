"""Build54800 complete small behavior factories and manager constructors.

Authority: action-behavior-factory-source-v1;67+67+26+33 original bytes.
Allocation is real and required; factories return actual constructor RAX.
The installed manager virtual8 action dispatchers remain mandatory external
children when reached by the list reader. No full World/current-recording,
physical stack/register, native fault/EH/CPU or threading parity is inferred.
"""

from __future__ import annotations

from .replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
    _call,
    _write,
)
from .replay_unit_ai_base import _validate

_FACTORIES = {0x14113B370: 0x140B875A0, 0x1412C5A30: 0x140BB6EC0}
_BASE, _UNIT = 0x140B875A0, 0x140BB6EC0


def create_replay_behavior_manager(
    context: ReplayTaskRebuildStorage,
    entry: int,
    subject: int,
    *,
    calls: ReplayTaskRebuildCalls,
) -> int:
    """Full67B Action/Combat or Unit factory with held subject and actual child.

    A null allocation returns0 without stores or construction. Nonnull backing
    receives separate16-byte and8-byte zero stores, then the actual constructor
    call. Its raw RAX is returned. Prior allocation/stores survive exceptions;
    no native exception guard cleanup or fallback success is invented.
    """
    _validate(context, calls, entry, subject)
    if entry not in _FACTORIES:
        raise ValueError("unsupported behavior manager factory entry")
    allocation = _call(calls, 0x142D6BA78, (24,), width=8)
    if not allocation:
        return 0
    _write(context, allocation, 16, 0)
    _write(context, allocation + 16, 8, 0)
    return _call(calls, _FACTORIES[entry], (allocation, subject), width=8)


def construct_replay_behavior_manager(
    context: ReplayTaskRebuildStorage,
    entry: int,
    address: int,
    subject: int,
    *,
    calls: ReplayTaskRebuildCalls,
) -> int:
    """Full26B base and33B Unit manager constructors, returning held this.

    Base publishes subject8 before vptr0 and head10. Unit calls actual base
    before its own vptr override; the base return never replaces held this.
    No current owner read or action-factory/list effects are synthesized.
    """
    _validate(context, calls, entry, address, subject)
    if entry == _BASE:
        _write(context, address + 8, 8, subject)
        _write(context, address, 8, 0x143226988)
        _write(context, address + 16, 8, 0)
    elif entry == _UNIT:
        _call(calls, _BASE, (address, subject))
        _write(context, address, 8, 0x1432284C8)
    else:
        raise ValueError("unsupported behavior manager constructor entry")
    return address


def bind_replay_behavior_factory(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
) -> ReplayTaskRebuildCalls:
    """Bind exactly four closed entries; unknown reached work delegates/refuses."""
    _validate(context, calls)

    def dispatch(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        if target not in _FACTORIES and target not in (_BASE, _UNIT):
            if calls.call is None:
                raise UnresolvedReplayTaskRebuild(f"reached{target:x} is unavailable")
            return calls.call(target, args, data)
        if len(args) != (1 if target in _FACTORIES else 2) or data is not None:
            raise ValueError("malformed behavior factory/constructor call")
        if target in _FACTORIES:
            return create_replay_behavior_manager(context, target, *args, calls=bound)
        return construct_replay_behavior_manager(context, target, *args, calls=bound)

    bound = ReplayTaskRebuildCalls(dispatch)
    return bound
