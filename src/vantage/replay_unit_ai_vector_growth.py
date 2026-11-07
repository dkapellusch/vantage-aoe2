"""Build54800 UnitAI DWORD append and52-byte row growth over current storage.

Source: unit-ai-vector-growth-source-v1, frozen before this port. Full bodies
1402b89c0/140cedd60 and commit140cf3320 preserve reached allocation, copy,
release, error and partial-write effects. Current backing and actual children
are required; no original heap, native stack, C++ EH or concurrency is implied.
"""

from __future__ import annotations

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
from .replay_unit_ai_base import _validate

_U64 = (1 << 64) - 1
_MAX4 = _U64 >> 2
_MAX52 = 0x04EC4EC4EC4EC4EC
_MAGIC52 = 0x4EC4EC4EC4EC4EC5


def _count52(end: int, begin: int) -> int:
    high = (_signed((end - begin) & _U64, 8) * _MAGIC52) >> 64
    shifted = high >> 4
    return (shifted + ((shifted & _U64) >> 63)) & _U64


def _error(calls: ReplayTaskRebuildCalls, target: int, args: tuple[int, ...] = ()) -> None:
    _call(calls, target, args)
    raise UnresolvedReplayTaskRebuild(f"nonreturning helper{target:x} returned to INT3")


def _capacity(used: int, capacity: int, maximum: int, calls: ReplayTaskRebuildCalls) -> int:
    half = capacity >> 1
    if capacity > (maximum - half) & _U64:
        return maximum
    result = max((used + 1) & _U64, (capacity + half) & _U64)
    if result > maximum:
        _error(calls, 0x1402A9460)
    return result


def _move(
    context: ReplayTaskRebuildStorage,
    vector: int,
    position: int,
    inserted: int,
    allocation: int,
    stride: int,
    calls: ReplayTaskRebuildCalls,
) -> None:
    end = _read(context, vector + 8, 8)
    begin = _read(context, vector, 8)
    if position == end:
        _call(calls, 0x142D6E3DB, (allocation, begin, end - begin))
    else:
        _call(calls, 0x142D6E3DB, (allocation, begin, position - begin))
        end = _read(context, vector + 8, 8)
        _call(calls, 0x142D6E3DB, (inserted + stride, position, end - position))


def append_replay_unit_ai_class(
    context: ReplayTaskRebuildStorage,
    vector: int,
    source: int,
    *,
    calls: ReplayTaskRebuildCalls,
) -> int | None:
    """Full1402b89c0: append current DWORD, without search or deduplication.

    Reuse returns residual EAX (the source DWORD). Growth tail-forwards the
    actual1402ba840 binding's effective result, which may be None for its
    mutation-only API. Initial-AI callers ignore this residual scalar. The
    value is read after allocation on growth; fast-path end uses a current
    read-modify-write after the payload store. No local addresses escape.
    """
    _validate(context, calls, vector, source)
    capacity_end = _read(context, vector + 16, 8)
    end = _read(context, vector + 8, 8)
    if end != capacity_end:
        value = _read(context, source, 4)
        _write(context, end, 4, value)
        _write(context, vector + 8, 8, _read(context, vector + 8, 8) + 4)
        return value
    begin = _read(context, vector, 8)
    used = (_signed((end - begin) & _U64, 8) >> 2) & _U64
    if used == _MAX4:
        _error(calls, 0x1402BA950)
    old_capacity = (_signed((capacity_end - begin) & _U64, 8) >> 2) & _U64
    capacity = _capacity(used, old_capacity, _MAX4, calls)
    allocation = _call(calls, 0x1402A94D0, (capacity * 4,), width=8)
    inserted = (allocation + used * 4) & _U64
    _write(context, inserted, 4, _read(context, source, 4))
    _move(context, vector, end, inserted, allocation, 4, calls)
    if calls.call is None:
        raise UnresolvedReplayTaskRebuild("reached1402ba840 is unavailable")
    result = calls.call(0x1402BA840, (vector, allocation, (used + 1) & _U64, capacity), None)
    if result is not None:
        _unsigned(result, 8, "UnitAI append tail return")
    return result


def grow_replay_unit_ai_rows(
    context: ReplayTaskRebuildStorage,
    vector: int,
    position: int,
    source: int,
    *,
    calls: ReplayTaskRebuildCalls,
) -> int:
    """Full140cedd60: allocate/insert52 bytes, move current ranges, real commit.

    The caller decides whether growth is needed. Source chunks16+16+16+4
    load/store sequentially after allocation, including all padding. Old
    source/header aliases and partial effects remain observable. The result
    is the held inserted address, independent of the commit's scalar result.
    Signed magic-division counts and unsigned capacity comparisons are kept;
    no well-formed-header preflight replaces a reached native operation.
    """
    _validate(context, calls, vector, position, source)
    begin = _read(context, vector, 8)
    displacement = _count52(position, begin)
    used = _count52(_read(context, vector + 8, 8), begin)
    if used == _MAX52:
        _error(calls, 0x140CF3470)
    old_capacity = _count52(_read(context, vector + 16, 8), begin)
    count = (used + 1) & _U64
    capacity = _capacity(used, old_capacity, _MAX52, calls)
    allocation = _call(calls, 0x1402A94D0, (capacity * 52,), width=8)
    inserted = (allocation + displacement * 52) & _U64
    for offset, width in ((0, 16), (16, 16), (32, 16), (48, 4)):
        value = _read(context, source + offset, width)
        _write(context, inserted + offset, width, value)
    _move(context, vector, position, inserted, allocation, 52, calls)
    _call(calls, 0x140CF3320, (vector, allocation, count, capacity))
    return inserted


def commit_replay_unit_ai_rows(
    context: ReplayTaskRebuildStorage,
    vector: int,
    allocation: int,
    count: int,
    capacity: int,
    *,
    calls: ReplayTaskRebuildCalls,
    imports: ReplayTaskRebuildCalls | None = None,
) -> int:
    """Full140cf3320: release current backing before three held-value commits.

    A null old begin skips capacity reads/free. Large allocations require the
    actual header at begin-8 and unsigned gap<=31. Invalid headers call the
    current Watson IAT target with five zero args through terminal imports.
    A returning nonreturning helper refuses; hardware INT3 is not emulated.
    Free/header-store failures retain their prior effects. Return held cap end.
    """
    _validate(context, calls, vector, allocation, count, capacity)
    terminal = calls if imports is None else imports
    _validate(context, terminal)
    begin = _read(context, vector, 8)
    if begin:
        size = (_count52(_read(context, vector + 16, 8), begin) * 52) & _U64
        pointer = begin
        if size >= 0x1000:
            pointer = _read(context, begin - 8, 8)
            size = (size + 0x27) & _U64
            if (begin - pointer - 8) & _U64 > 31:
                _error(terminal, _read(context, 0x14319A060, 8), (0, 0, 0, 0, 0))
        _call(calls, 0x142D6BAB4, (pointer, size))
    _write(context, vector, 8, allocation)
    _write(context, vector + 8, 8, allocation + count * 52)
    cap_end = (allocation + capacity * 52) & _U64
    _write(context, vector + 16, 8, cap_end)
    return cap_end


def bind_replay_unit_ai_vector_growth(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    *,
    imports: ReplayTaskRebuildCalls | None = None,
) -> ReplayTaskRebuildCalls:
    """Bind three exact bodies and genuine memmove/free import thunks.

    Inputs are actual scalar addresses; no fabricated local source views are
    accepted. Allocator, commit4 and error implementations delegate at reach.
    Optional terminal imports receive current IAT-selected calls directly,
    even when a target aliases an owned body. Free's unused optional RDX is
    forwarded unchanged. Other unknown calls retain their original arguments.
    """
    _validate(context, calls)
    terminal = calls if imports is None else imports
    _validate(context, terminal)

    def delegate(
        target: int,
        args: tuple[int, ...],
        data: memoryview | None,
        *,
        imported: bool = False,
    ) -> int | None:
        receiver = terminal if imported else calls
        if receiver.call is None:
            raise UnresolvedReplayTaskRebuild(f"reached{target:x} is unavailable")
        return receiver.call(target, args, data)

    def dispatch(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        arities = {
            0x1402B89C0: (2,),
            0x140CEDD60: (3,),
            0x140CF3320: (4,),
            0x142D6E3DB: (3,),
            0x142D6BAB4: (1, 2),
            0x142D6C90C: (1, 2),
            0x142D6E47D: (1, 2),
        }
        if target not in arities:
            return delegate(target, args, data)
        if len(args) not in arities[target] or data is not None:
            raise ValueError("malformed UnitAI vector helper call")
        _validate(context, calls, *args)
        if target == 0x1402B89C0:
            return append_replay_unit_ai_class(context, *args, calls=bound)
        if target == 0x140CEDD60:
            return grow_replay_unit_ai_rows(context, *args, calls=bound)
        if target == 0x140CF3320:
            return commit_replay_unit_ai_rows(context, *args, calls=bound, imports=terminal)
        if target == 0x142D6BAB4:
            return dispatch(0x142D6C90C, args, None)
        if target == 0x142D6C90C:
            return dispatch(0x142D6E47D, args, None)
        iat = 0x1431999A0 if target == 0x142D6E3DB else 0x143199DD0
        return delegate(_read(context, iat, 8), args, None, imported=True)

    bound = ReplayTaskRebuildCalls(dispatch)
    return bound
