"""Complete188B141734d70 relationship check with an explicit live count home.

Returns only the source-defined AL annotation, never native full RAX identity.
Actual count/predicate children and their current backing remain mandatory.
"""

from __future__ import annotations

from .replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
    _call,
    _read,
    _unsigned,
)
from .replay_unit_ai_base import _validate

_CHECK, _COUNT, _PREDICATE = 0x141734D70, 0x141603F30, 0x1416B69F0
_U64 = (1 << 64) - 1


def _invoke(
    calls: ReplayTaskRebuildCalls,
    target: int,
    args: tuple[int, ...],
) -> int | None:
    if calls.call is None:
        raise UnresolvedReplayTaskRebuild(f"reached{target:x} is unavailable")
    return calls.call(target, tuple(value & _U64 for value in args), None)


def check_replay_player_relationship(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    receiver: int,
    index_address: int,
    flag: int,
    *,
    count_home: int,
) -> int:
    """Run complete188B with actual R8B and only defined AL0/1 output.

    count_home is the real coherent childpostRSP30 location: the World caller
    explicitly supplies its logical_frame (parent0). No mapping, seed, native
    GP spill or substitute output is introduced. Early arms do not access it.
    Count return remains opaque through the mandatory current-index reread;
    actual RAX validation belongs to its following DWORD-pointee consumer.

    Native GP/save/stack identity, faults/EH/concurrency and unread descendant
    incidental ABI are excluded. Actual children/current backing are required;
    no null skip, count clamp or fabricated helper success is supplied.
    """
    _validate(context, calls, receiver, index_address, count_home)
    _unsigned(flag, 1, "actual R8B annotation")
    initial_index = _read(context, index_address, 4)
    if _read(context, receiver + 0x648, 4) == initial_index:
        return 1
    if not initial_index:
        return 0

    owner = _read(context, receiver + 8, 8)
    returned = _invoke(calls, _COUNT, (owner, count_home))
    index = _read(context, index_address, 4)
    if returned is None:
        raise ValueError("count helper must supply actual RAX at its pointee consumer")
    _unsigned(returned, 8, "count helper actual RAX")
    count = _read(context, returned, 4)
    if index >= count:
        return 0
    if _read(context, receiver + 0x648, 4) == index:
        return 0

    if flag:
        base = _read(context, receiver + 0x180, 8)
        if _read(context, base + index, 1) == 4:
            return 1
    base = _read(context, receiver + 0x180, 8)
    if _read(context, base + index, 1) == 0:
        return 1
    owner = _read(context, receiver + 8, 8)
    predicate = _call(calls, _PREDICATE, (owner,), width=4)
    if not predicate or not flag:
        return 0
    base = _read(context, receiver + 0x180, 8)
    index = _read(context, index_address, 4)
    return int(_read(context, base + index, 1) == 1)


def bind_replay_player_relationship_check(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    *,
    count_home: int,
) -> ReplayTaskRebuildCalls:
    """Own141734d70 prepared annotations, preserving unknown dispatch identity.

    Owned tuple(receiver,indexAddress,knownR8value,knownR8mask) is not a native
    four-argument signature. Require a fully known low byte and consume just
    value&ff; outside-mask bits are unasserted, with no upper R8 invention.
    The explicit count_home binding is per actual caller/nested scope, never
    inferred from Worldframe94/90. Deeper incidental consumption stays unclosed.
    """
    _validate(context, calls, count_home)

    def dispatch(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        if type(target) is not int or target != _CHECK:
            if calls.call is None:
                raise UnresolvedReplayTaskRebuild(f"reached{target:x} is unavailable")
            return calls.call(target, args, data)
        if not isinstance(args, tuple) or len(args) != 4 or data is not None:
            raise ValueError("actual relationship prepared arity4/no data required")
        for value in args:
            _unsigned(value, 8, "relationship prepared raw word")
        if args[3] & 0xFF != 0xFF:
            raise ValueError("complete known R8B annotation required")
        return check_replay_player_relationship(
            context,
            calls,
            args[0],
            args[1],
            args[2] & 0xFF,
            count_home=count_home,
        )

    return ReplayTaskRebuildCalls(dispatch)
