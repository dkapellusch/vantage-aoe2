"""Civilization research-row copy and release, four complete source bodies.

Source: player-derived-copy-independent-source-v1/source-note.json and the
original bodies it pins. The vector stride is twenty bytes. Allocation and
copy spans are separate current reads; overlap and callbacks retain their
source order. Actual allocator, memmove, free and error children are required.
Native stack, fault, exception-unwind and concurrency behavior are excluded.
"""

from __future__ import annotations

from .replay_task_group_storage import LocalBinding
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
from .replay_unit_ai_construction import _local

_U64 = (1 << 64) - 1
_ARITIES = {0x140F92850: 2, 0x140F92070: 2, 0x1402A8790: 2, 0x140F6BBF0: 0}


def _count(raw_bytes: int) -> int:
    """The signed reciprocal multiply gives division by twenty toward zero."""
    signed = _signed(raw_bytes, 8)
    return (abs(signed) // 20 * (-1 if signed < 0 else 1)) & _U64


def _copy(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    destination: int,
    source: int,
) -> int:
    for offset in (0, 8, 16):
        _write(context, destination + offset, 8, 0)
    end = _read(context, source + 8, 8)
    begin = _read(context, source, 8)
    count = _count((end - begin) & _U64)
    if not count:
        return destination
    if count > 0x0CCCCCCCCCCCCCCC:
        _call(calls, 0x140F6BBF0, ())
        raise UnresolvedReplayTaskRebuild("length error returned before INT3 140f92141")
    size = (20 * count) & _U64
    allocated = _call(calls, 0x1402A94D0, (size,), width=8)
    _write(context, destination, 8, allocated)
    _write(context, destination + 8, 8, allocated)
    _write(context, destination + 16, 8, allocated + size)
    begin = _read(context, source, 8)
    end = _read(context, source + 8, 8)
    copied_bytes = (end - begin) & _U64
    _call(calls, 0x142D6E3DB, (allocated, begin, copied_bytes))
    _write(context, destination + 8, 8, allocated + 20 * _count(copied_bytes))
    return destination


def bind_replay_player_research_rows(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    *,
    bind_local: LocalBinding,
    error_seed: bytes,
    imports: ReplayTaskRebuildCalls | None = None,
) -> ReplayTaskRebuildCalls:
    """Bind 140f92850/140f92070/1402a8790/140f6bbf0, delegate all children.

    error_seed explicitly backs the release error's live eight-byte fifth
    argument home. Reached storage and child failures preserve earlier effects.
    This supplies no civilization data, Player restoration or native identity.
    The owned storage and providers must bound admitted allocation/copy spans.
    """
    _validate(context, calls)
    terminal = calls if imports is None else imports
    _validate(context, terminal)
    if not callable(bind_local) or type(error_seed) is not bytes or len(error_seed) != 8:
        raise ValueError("actual local binding and explicit eight-byte error seed required")

    def release(pointer: int, size: int) -> int | None:
        if size >= 0x1000:
            base = _read(context, pointer - 8, 8)
            size = (size + 0x27) & _U64
            if (pointer - base - 8) & _U64 > 0x1F:
                with _local(memoryview(bytearray(error_seed)), bind_local) as fifth:
                    _write(context, fifth, 8, 0)
                    target = _read(context, 0x14319A060, 8)
                    _call(terminal, target, (0, 0, 0, 0, _read(context, fifth, 8)))
                    raise UnresolvedReplayTaskRebuild(
                        "invalid-parameter error returned before INT3 1402a87d7"
                    )
            pointer = base
        if calls.call is None:
            raise UnresolvedReplayTaskRebuild("reached142d6bab4 is unavailable")
        return calls.call(0x142D6BAB4, (pointer, size), None)

    def dispatch(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        if target not in _ARITIES:
            if calls.call is None:
                raise UnresolvedReplayTaskRebuild(f"reached{target:x} is unavailable")
            return calls.call(target, args, data)
        if len(args) != _ARITIES[target] or data is not None:
            raise ValueError("malformed research-row call")
        _validate(context, calls, *args)
        if target == 0x140F92850:
            source, destination = args
            _call(calls, 0x140F92070, (destination, (source + 0x38) & _U64))
            return destination
        if target == 0x140F92070:
            return _copy(context, calls, *args)
        if target == 0x1402A8790:
            return release(*args)
        _call(calls, 0x142D66698, (0x1436794B0,))
        raise UnresolvedReplayTaskRebuild("length error returned before INT3 140f6bc00")

    return ReplayTaskRebuildCalls(dispatch)
