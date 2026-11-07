"""Build54800 complete World shared Player pair-vector helpers.

Source: game-world-link-source-v1, whole127/83/113/458B bodies. Pair rows
retain current source/header/vptr reads and real allocator/free/atomic effects.
Finite nonwrapping whole16B iteration ranges are admitted; malformed loops,
native fault/EH/concurrency/stack parity and whole World startup are excluded.
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
from .replay_unit_ai_map import ReplayUnitAIMapAtomics, _release

_U64 = (1 << 64) - 1
_MAX = (1 << 60) - 1


def _count(end: int, begin: int) -> int:
    return (_signed((end - begin) & _U64, 8) >> 4) & _U64


def _range(begin: int, end: int) -> None:
    if end < begin or (end - begin) & 15:
        raise ValueError("World Player vector requires ordered whole16B range")


def _span(begin: int, count: int) -> None:
    if begin + count * 16 > _U64:
        raise ValueError("World Player vector requires nonwrapping pair span")


def _increment(atomics: ReplayUnitAIMapAtomics, control: int) -> None:
    if atomics.fetch_add is None:
        raise UnresolvedReplayTaskRebuild("World Player strong atomic increment unavailable")
    # LOCK INC does not consume the prior DWORD or any callback return value.
    atomics.fetch_add((control + 8) & _U64, 1)


def _append_pair(
    context: ReplayTaskRebuildStorage,
    destination: int,
    source: int,
    atomics: ReplayUnitAIMapAtomics,
) -> None:
    _write(context, destination, 8, 0)
    _write(context, destination + 8, 8, 0)
    control = _read(context, source + 8, 8)
    if control:
        _increment(atomics, control)
    _write(context, destination, 8, _read(context, source, 8))
    _write(context, destination + 8, 8, _read(context, source + 8, 8))


def release_replay_world_players(
    context: ReplayTaskRebuildStorage,
    begin: int,
    end: int,
    ignored_owner: int,
    *,
    calls: ReplayTaskRebuildCalls,
    atomics: ReplayUnitAIMapAtomics,
) -> None:
    """Whole113B141344f50: held control, current vptr for each real release."""
    _validate(context, calls, begin, end, ignored_owner)
    if not isinstance(atomics, ReplayUnitAIMapAtomics):
        raise ValueError("actual World Player atomics required")
    _range(begin, end)
    while begin != end:
        control = _read(context, begin + 8, 8)
        if control:
            _release(context, control, calls, atomics)
        begin += 16


def append_replay_world_players(
    context: ReplayTaskRebuildStorage,
    begin: int,
    count: int,
    source: int,
    owner: int,
    *,
    calls: ReplayTaskRebuildCalls,
    atomics: ReplayUnitAIMapAtomics,
) -> int:
    """Whole83B1415e7d40; source aliases and atomic source mutation remain live.

    Even count0 calls the actual empty release before returning the held end.
    Source is never read when count0. Release's incidental result is ignored.
    """
    _validate(context, calls, begin, count, source, owner)
    if not isinstance(atomics, ReplayUnitAIMapAtomics):
        raise ValueError("actual World Player atomics required")
    _span(begin, count)
    for _ in range(count):
        _append_pair(context, begin, source, atomics)
        begin += 16
    _call(calls, 0x141344F50, (begin, begin, owner))
    return begin


def grow_replay_world_players(
    context: ReplayTaskRebuildStorage,
    header: int,
    requested: int,
    source: int,
    *,
    calls: ReplayTaskRebuildCalls,
    atomics: ReplayUnitAIMapAtomics,
    imports: ReplayTaskRebuildCalls | None = None,
) -> None:
    """Whole458B1415e7b70; new tail precedes current old-row move and free.

    Size is initially held, while capacity rereads begin; later phases reload
    current headers after real cleanup callbacks. Zero/copy/zero moves retain
    alias effects. Free and every release happen before held replacement commit.
    Returned fatal/Watson paths refuse at their explicit INT3/end boundary.
    """
    _validate(context, calls, header, requested, source)
    terminal = calls if imports is None else imports
    _validate(context, terminal)
    if not isinstance(atomics, ReplayUnitAIMapAtomics):
        raise ValueError("actual World Player atomics required")
    if requested > _MAX:
        _call(calls, 0x141345000, ())
        raise UnresolvedReplayTaskRebuild("World Player length error returned before INT3")
    old_end = _read(context, header + 8, 8)
    old_size = _count(old_end, _read(context, header, 8))
    capacity_end = _read(context, header + 16, 8)
    capacity = _count(capacity_end, _read(context, header, 8))
    half = capacity >> 1
    if capacity > (_MAX - half) & _U64:
        growth = _MAX
    else:
        growth = max((capacity + half) & _U64, requested)
        if growth > _MAX:
            _call(calls, 0x1402A9460, ())
            raise UnresolvedReplayTaskRebuild("World Player allocation error returned at body end")
    byte_capacity = growth * 16 & _U64
    replacement = _call(calls, 0x1402A94D0, (byte_capacity,), width=8)
    tail = (replacement + old_size * 16) & _U64
    count = (requested - old_size) & _U64
    _span(tail, count)
    for _ in range(count):
        _append_pair(context, tail, source, atomics)
        tail += 16
    _call(calls, 0x141344F50, (tail, tail, header))
    move_end = _read(context, header + 8, 8)
    move_begin = _read(context, header, 8)
    _range(move_begin, move_end)
    destination = replacement
    _span(destination, (move_end - move_begin) // 16)
    while move_begin != move_end:
        _write(context, destination, 8, 0)
        _write(context, destination + 8, 8, 0)
        _write(context, destination, 8, _read(context, move_begin, 8))
        _write(context, destination + 8, 8, _read(context, move_begin + 8, 8))
        destination += 16
        _write(context, move_begin, 8, 0)
        _write(context, move_begin + 8, 8, 0)
        move_begin += 16
    _call(calls, 0x141344F50, (destination, destination, header))
    current_begin = _read(context, header, 8)
    if current_begin:
        current_end = _read(context, header + 8, 8)
        _call(calls, 0x141344F50, (current_begin, current_end, header))
        pointer = _read(context, header, 8)
        size = (_read(context, header + 16, 8) - pointer) & (_U64 - 15)
        if size >= 0x1000:
            base = _read(context, pointer - 8, 8)
            size = (size + 0x27) & _U64
            if (pointer - base - 8) & _U64 > 31:
                _call(terminal, _read(context, 0x14319A060, 8), (0, 0, 0, 0, 0))
                raise UnresolvedReplayTaskRebuild("World Player Watson returned before INT3")
            pointer = base
        _call(calls, 0x142D6BAB4, (pointer, size))
    _write(context, header, 8, replacement)
    _write(context, header + 8, 8, replacement + requested * 16)
    _write(context, header + 16, 8, replacement + byte_capacity)


def resize_replay_world_players(
    context: ReplayTaskRebuildStorage,
    header: int,
    requested: int,
    source: int,
    *,
    calls: ReplayTaskRebuildCalls,
) -> None:
    """Whole127B14161dbe0; held end/begin and actual append-return commit."""
    _validate(context, calls, header, requested, source)
    old_end = _read(context, header + 8, 8)
    begin = _read(context, header, 8)
    old_size = _count(old_end, begin)
    if requested < old_size:
        replacement_end = (begin + requested * 16) & _U64
        _call(calls, 0x141344F50, (replacement_end, old_end, header))
        _write(context, header + 8, 8, replacement_end)
    elif requested > old_size:
        capacity = _count(_read(context, header + 16, 8), begin)
        if requested > capacity:
            _call(calls, 0x1415E7B70, (header, requested, source))
        else:
            end = _call(
                calls,
                0x1415E7D40,
                (old_end, (requested - old_size) & _U64, source, header),
                width=8,
            )
            _write(context, header + 8, 8, end)


def bind_replay_world_player_vector(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    *,
    atomics: ReplayUnitAIMapAtomics,
    imports: ReplayTaskRebuildCalls | None = None,
) -> ReplayTaskRebuildCalls:
    """Bind exactly four complete bodies; every reached external child delegates."""
    _validate(context, calls)
    terminal = calls if imports is None else imports
    _validate(context, terminal)
    if not isinstance(atomics, ReplayUnitAIMapAtomics):
        raise ValueError("actual World Player atomics required")

    def dispatch(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        arities = {0x141344F50: 3, 0x1415E7D40: 4, 0x1415E7B70: 3, 0x14161DBE0: 3}
        if target not in arities:
            if calls.call is None:
                raise UnresolvedReplayTaskRebuild(f"reached{target:x} is unavailable")
            return calls.call(target, args, data)
        if len(args) != arities[target] or data is not None:
            raise ValueError("malformed World Player vector call")
        _validate(context, calls, *args)
        if target == 0x141344F50:
            release_replay_world_players(context, *args, calls=bound, atomics=atomics)
        elif target == 0x1415E7D40:
            return append_replay_world_players(context, *args, calls=bound, atomics=atomics)
        elif target == 0x1415E7B70:
            grow_replay_world_players(
                context, *args, calls=bound, atomics=atomics, imports=terminal
            )
        else:
            resize_replay_world_players(context, *args, calls=bound)
        return None

    bound = ReplayTaskRebuildCalls(dispatch)
    return bound
