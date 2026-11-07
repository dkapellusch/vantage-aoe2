"""Build54800 TaskList clear, pointer-vector resize/commit and direct task dtor.

Source: world-envelope/task-list-storage-source-v1 (five complete bodies,
765 bytes). Pointers are owned runtime tokens. Current CRT import targets must
be explicitly backed and bound; these bodies do not restore a master or World.
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

_U64 = (1 << 64) - 1
_MAXIMUM = 0x1FFFFFFFFFFFFFFF


def _validate(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    *values: int,
) -> None:
    if not isinstance(context, ReplayTaskRebuildStorage):
        raise ValueError("explicit current TaskList storage required")
    if not isinstance(calls, ReplayTaskRebuildCalls):
        raise ValueError("explicit actual TaskList effects required")
    for value in values:
        _unsigned(value, 8, "TaskList argument")


def _count(end: int, begin: int) -> int:
    return (_signed((end - begin) & _U64, 8) >> 3) & _U64


def _error(calls: ReplayTaskRebuildCalls, target: int, args: tuple[int, ...] = ()) -> None:
    _call(calls, target, args)
    raise RuntimeError(f"nonreturning helper{target:x} unexpectedly returned")


def destroy_replay_task(context: ReplayTaskRebuildStorage, task: int) -> None:
    """Full14112aad0: write the task vptr only; no virtual dispatch or free."""
    if not isinstance(context, ReplayTaskRebuildStorage):
        raise ValueError("explicit current TaskList storage required")
    _unsigned(task, 8, "task address")
    _write(context, task, 8, 0x1432A4EF8)


def fill_replay_task_pointers(
    context: ReplayTaskRebuildStorage,
    destination: int,
    count: int,
    source: int,
    *,
    calls: ReplayTaskRebuildCalls,
) -> int:
    """Full1412684d0, with source read even for count0 and live per-slot rereads.

    Zero source calls the actual memset thunk even for zero bytes. Nonzero
    source is read again before each QWORD store, preserving source aliases.
    The fourth native scalar is unused and need not be backed.
    """
    _validate(context, calls, destination, count, source)
    if _read(context, source, 8) == 0:
        size = (count * 8) & _U64
        _call(calls, 0x142D6E3B7, (destination, 0, size))
        return (destination + size) & _U64
    while count:
        _write(context, destination, 8, _read(context, source, 8))
        destination = (destination + 8) & _U64
        count -= 1
    return destination


def commit_replay_task_pointers(
    context: ReplayTaskRebuildStorage,
    vector: int,
    new_begin: int,
    length: int,
    capacity: int,
    *,
    calls: ReplayTaskRebuildCalls,
) -> None:
    """Full141268dd0: current old release first, then held new header values.

    Large allocations validate the current backpointer/gap and current Watson
    import. A returned error stops at the verified adjacent CC. Free callbacks
    can change old storage but cannot replace the held new values.
    """
    _validate(context, calls, vector, new_begin, length, capacity)
    old = _read(context, vector, 8)
    if old:
        size = ((_read(context, vector + 16, 8) - old) & _U64) & ~7
        pointer = old
        if size >= 0x1000:
            pointer = _read(context, old - 8, 8)
            size = (size + 0x27) & _U64
            if (old - pointer - 8) & _U64 > 31:
                target = _read(context, 0x14319A060, 8)
                _error(calls, target, (0, 0, 0, 0, 0))
        _call(calls, 0x142D6BAB4, (pointer, size))
    _write(context, vector, 8, new_begin)
    _write(context, vector + 8, 8, new_begin + length * 8)
    _write(context, vector + 16, 8, new_begin + capacity * 8)


def resize_replay_task_pointers(
    context: ReplayTaskRebuildStorage,
    vector: int,
    desired: int,
    source: int,
    *,
    calls: ReplayTaskRebuildCalls,
) -> None:
    """Full141268370: shrink only changes end; growth fills before old copy.

    Allocation precedes fill-source reads. Old copy and release headers are
    reloaded after the reached callbacks. Capacity grows by 1.5 with the exact
    unsigned SAR-derived count and saturating bound. No implicit task deletion.
    """
    _validate(context, calls, vector, desired, source)
    end = _read(context, vector + 8, 8)
    begin = _read(context, vector, 8)
    old_count = _count(end, begin)
    if desired < old_count:
        _write(context, vector + 8, 8, begin + desired * 8)
        return
    if desired == old_count:
        return
    old_capacity = _count(_read(context, vector + 16, 8), begin)
    amount = (desired - old_count) & _U64
    if desired <= old_capacity:
        result = _call(calls, 0x1412684D0, (end, amount, source, vector), width=8)
        _write(context, vector + 8, 8, result)
        return
    if desired > _MAXIMUM:
        _error(calls, 0x14116B8C0)
    half = old_capacity >> 1
    if old_capacity > (_MAXIMUM - half) & _U64:
        capacity = _MAXIMUM
    else:
        capacity = max(desired, (old_capacity + half) & _U64)
        if capacity > _MAXIMUM:
            _error(calls, 0x1402A9460)
    new_begin = _call(calls, 0x1402A94D0, ((capacity * 8) & _U64,), width=8)
    destination = (new_begin + old_count * 8) & _U64
    if _read(context, source, 8) == 0:
        _call(calls, 0x142D6E3B7, (destination, 0, (amount * 8) & _U64))
    else:
        while amount:
            _write(context, destination, 8, _read(context, source, 8))
            destination = (destination + 8) & _U64
            amount -= 1
    current_begin = _read(context, vector, 8)
    current_end = _read(context, vector + 8, 8)
    _call(calls, 0x142D6E3DB, (new_begin, current_begin, (current_end - current_begin) & _U64))
    _call(calls, 0x141268DD0, (vector, new_begin, desired, capacity))


def clear_replay_task_list(
    context: ReplayTaskRebuildStorage,
    task_list: int,
    *,
    calls: ReplayTaskRebuildCalls,
) -> None:
    """Full141269220: direct dtor/free, zero current slot, retain vector capacity.

    The original signed16 counter is sign-extended for its unsigned comparison
    with current SAR-derived count. Coherent lists longer than32768 therefore
    stop after32768 slots. Saved positive signed16 counts fit below that limit.
    """
    _validate(context, calls, task_list)
    end = _read(context, task_list + 16, 8)
    begin = _read(context, task_list + 8, 8)
    index = 0
    if _count(end, begin):
        while True:
            offset = (index * 8) & _U64
            task = _read(context, begin + offset, 8)
            if task:
                _call(calls, 0x14112AAD0, (task,))
                _call(calls, 0x142D6BAB4, (task, 0x90))
                current_begin = _read(context, task_list + 8, 8)
                _write(context, current_begin + offset, 8, 0)
            end = _read(context, task_list + 16, 8)
            index = _signed((index + 1) & 0xFFFF, 2)
            begin = _read(context, task_list + 8, 8)
            if index & _U64 >= _count(end, begin):
                break
    if begin != end:
        _write(context, task_list + 16, 8, begin)


def bind_replay_task_list_storage(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
) -> ReplayTaskRebuildCalls:
    """Bind five bodies and three CRT thunks with current import reads at reach.

    The lower dispatcher binds resolved import targets to actual effects. It
    receives those resolved targets directly, including when an explicit owned
    runtime uses the thunk's address as its primitive identity. No native DLL
    identity is inferred. All other unknown leaves delegate/refuse at reach.
    """
    _validate(context, calls)
    imports = {
        0x142D6BAB4: (0x143199DD0, 2),
        0x142D6E3DB: (0x1431999A0, 3),
        0x142D6E3B7: (0x143199938, 3),
    }
    arities = {
        0x141269220: (1,),
        0x141268DD0: (4,),
        0x141268370: (3,),
        0x14112AAD0: (1,),
        0x1412684D0: (3, 4),
    }

    def delegate(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        if calls.call is None:
            raise UnresolvedReplayTaskRebuild(f"reached{target:x} is unavailable")
        return calls.call(target, args, data)

    def dispatch(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        if target in imports:
            iat, arity = imports[target]
            if len(args) != arity or data is not None:
                raise ValueError("malformed TaskList import call")
            _validate(context, calls, *args)
            return delegate(_read(context, iat, 8), args, None)
        if target not in arities:
            return delegate(target, args, data)
        if len(args) not in arities[target] or data is not None:
            raise ValueError("malformed TaskList storage call")
        _validate(context, calls, *args)
        if target == 0x14112AAD0:
            destroy_replay_task(context, args[0])
        elif target == 0x141269220:
            clear_replay_task_list(context, args[0], calls=bound)
        elif target == 0x141268DD0:
            commit_replay_task_pointers(context, *args, calls=bound)
        elif target == 0x141268370:
            resize_replay_task_pointers(context, *args, calls=bound)
        else:
            return fill_replay_task_pointers(context, *args[:3], calls=bound)
        return None

    bound = ReplayTaskRebuildCalls(dispatch)
    return bound
