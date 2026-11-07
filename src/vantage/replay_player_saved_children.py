"""Build54800 four Player Result/vector helpers,697 source bytes.

Current storage and reached children stay real. There are no semantic unwritten
locals requiring a scratch seed in these four bodies; native saves/argument
homes/fences/fault/EH/thread parity and incidental CPU return registers are not
modeled. DWORD fill admits ordered nonwrapping ranges of whole DWORDs only.
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

_U64 = (1 << 64) - 1


def assign_replay_player_result(
    context: ReplayTaskRebuildStorage,
    destination: int,
    source: int,
    *,
    calls: ReplayTaskRebuildCalls,
) -> int:
    """78B140991ce0; source processed BEFORE real pair and conditional vector.

    Self identity still calls the actual status/control-pair body. This caller
    does not release the source Result; its enclosing caller owns that lifetime.
    Held destination returns after its processed byte is cleared.
    """
    _validate(context, calls, destination, source)
    _write(context, source + 40, 1, 1)
    _call(calls, 0x14090D270, ((destination + 24) & _U64, (source + 24) & _U64))
    if destination != source:
        begin = _read(context, source, 8)
        end = _read(context, source + 8, 8)
        count = (_signed((end - begin) & _U64, 8) >> 5) & _U64
        _call(calls, 0x1402B9080, (destination, begin, count))
    _write(context, destination + 40, 1, 0)
    return destination


def commit_replay_player_bytes(
    context: ReplayTaskRebuildStorage,
    header: int,
    pointer: int,
    size: int,
    capacity: int,
    *,
    calls: ReplayTaskRebuildCalls,
    imports: ReplayTaskRebuildCalls | None = None,
) -> None:
    """153B1402dbef0; current old capacity/free before held replacement commits.

    The old null pointer skips even the old capacity read. A large allocation
    uses the current backpointer and exact unsigned delta guard. A returned
    Watson call refuses before its adjacent INT3; prior effects are retained.
    """
    _validate(context, calls, header, pointer, size, capacity)
    terminal = calls if imports is None else imports
    _validate(context, terminal)
    previous = _read(context, header, 8)
    if previous:
        byte_count = (_read(context, header + 16, 8) - previous) & _U64
        allocation = previous
        if byte_count >= 0x1000:
            allocation = _read(context, previous - 8, 8)
            byte_count = byte_count + 0x27 & _U64
            if (previous - allocation - 8) & _U64 > 0x1F:
                _call(terminal, _read(context, 0x14319A060, 8), (0, 0, 0, 0, 0))
                raise UnresolvedReplayTaskRebuild("Player byte commit Watson returned before INT3")
        _call(calls, 0x142D6BAB4, (allocation, byte_count))
    _write(context, header, 8, pointer)
    _write(context, header + 8, 8, pointer + size)
    _write(context, header + 16, 8, pointer + capacity)


def fill_replay_player_words(
    context: ReplayTaskRebuildStorage,
    begin: int,
    end: int,
    source: int,
    *,
    calls: ReplayTaskRebuildCalls,
) -> None:
    """164B140c31b50, actual DWORD fill; current/held source phases and aliasing.

    Ordered nonwrapping whole-DWORD ranges are an explicit admission profile;
    excluded malformed ranges refuse before body effects, not native fault
    parity. Every admitted range, including empty, first reads sourceDWORD.
    Zero dispatches real memset even for zero bytes. Nonzero >=4-element paths
    load a held source once before alias testing; only nonoverlapping bulk uses
    it. Aliased writes and every scalar tail reload the source DWORD each time.
    """
    _validate(context, calls, begin, end, source)
    if end < begin or (end - begin) & 3:
        raise ValueError("Player DWORD fill requires ordered nonwrapping whole-DWORD range")
    count_bytes = end - begin
    if _read(context, source, 4) == 0:
        _call(calls, 0x142D6E3B7, (begin, 0, count_bytes & ~3))
        return
    count = (count_bytes + 3) >> 2
    cursor = begin
    if count >= 4:
        last = (begin - 4 + count * 4) & _U64
        held = _read(context, source, 4)
        if begin > source or last < source:
            bulk = count & ~3
            for _ in range(bulk):
                _write(context, cursor, 4, held)
                cursor += 4
    while cursor != end:
        _write(context, cursor, 4, _read(context, source, 4))
        cursor += 4


def resize_replay_player_words(
    context: ReplayTaskRebuildStorage,
    header: int,
    requested: int,
    source: int,
    *,
    calls: ReplayTaskRebuildCalls,
) -> None:
    """302B140c4dde0; fill existing prefixes and append current source words.

    Reserve1402ba470(header,heldrequest) is a mandatory real child, not an
    inferred allocation callback. This module binds the actual164B range fill;
    both prefix calls carry all three consumed registers, including sourceR8.
    Zero fills hold the selected destination over memset. Nonzero appends read
    the current source for each store. Only final end publication is performed.
    """
    _validate(context, calls, header, requested, source)
    begin = _read(context, header, 8)
    capacity = (_signed((_read(context, header + 16, 8) - begin) & _U64, 8) >> 2) & _U64
    if requested > capacity:
        _call(calls, 0x1402BA470, (header, requested))
        zero = _read(context, source, 4) == 0
        cursor = _read(context, header, 8)
        remaining = requested
    else:
        old_end = _read(context, header + 8, 8)
        length = (_signed((old_end - begin) & _U64, 8) >> 2) & _U64
        if requested <= length:
            replacement = (begin + requested * 4) & _U64
            _call(calls, 0x140C31B50, (begin, replacement, source))
            _write(context, header + 8, 8, replacement)
            return
        _call(calls, 0x140C31B50, (begin, old_end, source))
        remaining = (requested - length) & _U64
        cursor = _read(context, header + 8, 8)
        zero = _read(context, source, 4) == 0
    if zero:
        byte_count = remaining * 4 & _U64
        _call(calls, 0x142D6E3B7, (cursor, 0, byte_count))
        cursor = cursor + byte_count & _U64
    else:
        while remaining:
            _write(context, cursor, 4, _read(context, source, 4))
            cursor = cursor + 4 & _U64
            remaining = remaining - 1 & _U64
    _write(context, header + 8, 8, cursor)


def bind_replay_player_saved_children(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    *,
    imports: ReplayTaskRebuildCalls | None = None,
) -> ReplayTaskRebuildCalls:
    """Four exact entries. Unknown children delegate or refuse at actual reach."""
    _validate(context, calls)
    terminal = calls if imports is None else imports
    _validate(context, terminal)

    def dispatch(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        arities = {0x140991CE0: 2, 0x1402DBEF0: 4, 0x140C4DDE0: 3, 0x140C31B50: 3}
        if target not in arities:
            if calls.call is None:
                raise UnresolvedReplayTaskRebuild(f"reached{target:x} is unavailable")
            return calls.call(target, args, data)
        if len(args) != arities[target] or data is not None:
            raise ValueError("malformed Player saved-child call")
        if target == 0x140991CE0:
            return assign_replay_player_result(context, *args, calls=bound)
        if target == 0x1402DBEF0:
            commit_replay_player_bytes(context, *args, calls=bound, imports=terminal)
        elif target == 0x140C4DDE0:
            resize_replay_player_words(context, *args, calls=bound)
        else:
            fill_replay_player_words(context, *args, calls=bound)
        return None

    bound = ReplayTaskRebuildCalls(dispatch)
    return bound
