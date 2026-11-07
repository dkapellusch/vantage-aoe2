"""Build54800 saved-AI list clearing and Result forwarding/vector assignment.

Full96B140d36fe0,192B1409076b0 and334B1402b9080 source is retained in
tc-unit-ai-saved-{apply,result-forward,result-copy}-source-v1. Reached element,
reserve/range, control, atomic and CRT effects require actual bindings. This
does not infer stream success. Native stack tracking, fences, faults, C++ EH
and concurrent execution are outside the logical current-storage profile.
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
from .replay_unit_ai_map import ReplayUnitAIMapAtomics, _atomic, _release

_U64 = (1 << 64) - 1


def _count(end: int, begin: int) -> int:
    return (_signed((end - begin) & _U64, 8) >> 5) & _U64


def clear_replay_saved_ai_list(
    context: ReplayTaskRebuildStorage,
    ai: int,
    *,
    calls: ReplayTaskRebuildCalls,
) -> None:
    """Full96B140d36fe0: held-next traversal, free before final header resets.

    Null head is not empty. No count/cycle guard or per-node destructor is
    invented; finite readable links and actual reached free effects are inputs.
    """
    _validate(context, calls, ai)
    node = _read(context, ai + 0xA8, 8)
    sentinel = (ai + 0x78) & _U64
    while node != sentinel:
        following = _read(context, node + 0x30, 8)
        _call(calls, 0x142D6BAB4, (node, 0x40))
        node = following
    _write(context, ai + 0xA8, 8, sentinel)
    _write(context, ai + 0xB0, 8, sentinel)
    _write(context, ai + 0xB8, 4, 0)


def _assign_element(
    context: ReplayTaskRebuildStorage,
    destination: int,
    source: int,
    calls: ReplayTaskRebuildCalls,
) -> None:
    if destination == source:
        return
    buffer = source
    if _read(context, source + 0x18, 8) > 15:
        buffer = _read(context, source, 8)
    length = _read(context, source + 0x10, 8)
    _call(calls, 0x1402A8FB0, (destination, buffer, length))


def assign_replay_saved_result_vector(
    context: ReplayTaskRebuildStorage,
    header: int,
    source: int,
    count: int,
    *,
    calls: ReplayTaskRebuildCalls,
) -> None:
    """Full334B1402b9080, all normal raw-count branches and current reads.

    Children are mandatory, including reserve on growth. Its tuple carries
    explicit RCX/RDX(header,count) plus proven incidental incoming R8=count;
    that third register's consumption is unproved. Other child tuples retain
    source-explicit arguments. No complete missing-child ABI is inferred.
    """
    _validate(context, calls, header, source, count)
    begin = _read(context, header, 8)
    capacity = _count(_read(context, header + 16, 8), begin)
    if count > capacity:
        _call(calls, 0x1402BA380, (header, count, count))
        current_begin = _read(context, header, 8)
        end = _call(calls, 0x1402B9B40, (source, count, current_begin, header), width=8)
        _write(context, header + 8, 8, end)
        return

    end = _read(context, header + 8, 8)
    old_size = _count(end, begin)
    if count > old_size:
        while begin != end:
            _assign_element(context, begin, source, calls)
            begin = (begin + 32) & _U64
            source = (source + 32) & _U64
            end = _read(context, header + 8, 8)
        remaining = (count - old_size) & _U64
        while remaining:
            _call(calls, 0x1402A9630, (end, source))
            end = (end + 32) & _U64
            source = (source + 32) & _U64
            remaining = (remaining - 1) & _U64
    else:
        target_end = (begin + (count << 5)) & _U64
        remaining = count
        while remaining:
            _assign_element(context, begin, source, calls)
            begin = (begin + 32) & _U64
            source = (source + 32) & _U64
            remaining = (remaining - 1) & _U64
        held_old_end = _read(context, header + 8, 8)
        cursor = target_end
        while cursor != held_old_end:
            _call(calls, 0x1402A88A0, (cursor,))
            cursor = (cursor + 32) & _U64
        end = target_end
    _write(context, header + 8, 8, end)


def forward_replay_saved_result(
    context: ReplayTaskRebuildStorage,
    destination: int,
    source: int,
    *,
    calls: ReplayTaskRebuildCalls,
    atomics: ReplayUnitAIMapAtomics,
) -> int:
    """Full192B1409076b0; resets precede source reads and self-alias comparison.

    Padding29..2f is preserved. The source processed byte is set only after
    mandatory vector assignment returns, or after the identity branch skips it.
    Partial writes, atomic changes and child effects survive failures.
    """
    _validate(context, calls, destination, source)
    if not isinstance(atomics, ReplayUnitAIMapAtomics):
        raise ValueError("actual saved Result shared-count bindings required")
    for offset in (0, 8, 16, 24, 32):
        _write(context, destination + offset, 8, 0)
    _write(context, destination + 40, 1, 0)
    control = _read(context, source + 32, 8)
    if control:
        _atomic(atomics, control + 8, 1)
    held_control = _read(context, source + 32, 8)
    status = _read(context, source + 24, 8)
    _write(context, destination + 24, 8, status)
    old_control = _read(context, destination + 32, 8)
    _write(context, destination + 32, 8, held_control)
    if old_control:
        _release(context, old_control, calls, atomics)
    if destination != source:
        begin = _read(context, source, 8)
        end = _read(context, source + 8, 8)
        _call(calls, 0x1402B9080, (destination, begin, _count(end, begin)))
    _write(context, source + 40, 1, 1)
    return destination


def bind_replay_saved_apply(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    *,
    atomics: ReplayUnitAIMapAtomics,
    imports: ReplayTaskRebuildCalls | None = None,
) -> ReplayTaskRebuildCalls:
    """Bind three complete scalar callers and genuine current sized-free import.

    Unprovided element/reserve/range bodies delegate or refuse when reached.
    The current free target uses the terminal dispatcher, never this new binder.
    """
    _validate(context, calls)
    terminal = calls if imports is None else imports
    _validate(context, terminal)
    if not isinstance(atomics, ReplayUnitAIMapAtomics):
        raise ValueError("actual saved Result shared-count bindings required")

    def dispatch(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        arities = {0x140D36FE0: 1, 0x1409076B0: 2, 0x1402B9080: 3, 0x142D6BAB4: 2}
        if target not in arities:
            if calls.call is None:
                raise UnresolvedReplayTaskRebuild(f"reached{target:x} is unavailable")
            return calls.call(target, args, data)
        if len(args) != arities[target] or data is not None:
            raise ValueError("malformed saved apply call")
        _validate(context, calls, *args)
        if target == 0x140D36FE0:
            clear_replay_saved_ai_list(context, *args, calls=bound)
        elif target == 0x1409076B0:
            return forward_replay_saved_result(context, *args, calls=bound, atomics=atomics)
        elif target == 0x1402B9080:
            assign_replay_saved_result_vector(context, *args, calls=bound)
        else:
            imported = _read(context, 0x143199DD0, 8)
            if terminal.call is None:
                raise UnresolvedReplayTaskRebuild(f"reached{imported:x} is unavailable")
            return terminal.call(imported, args, None)
        return None

    bound = ReplayTaskRebuildCalls(dispatch)
    return bound
