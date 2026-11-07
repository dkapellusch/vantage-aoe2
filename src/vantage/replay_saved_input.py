"""Owned saved-game bytes behind an explicit engine read capability.

The native caller ABI is stream/result48/destination/u64count, selected from
the current stream vptr+18. This service supplies actual bytes and a cursor;
it does not identify or emulate a native IStream class. Result bytes must be
supplied explicitly by the engine profile. Native truncation diagnostics,
partial reads, faults, asynchronous I/O and C++ unwinding are not inferred.
"""

from __future__ import annotations

from .replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
    _unsigned,
    _write,
)
from .replay_unit_ai_base import _validate


class ReplaySavedInput:
    """Finite immutable input with a committed engine-owned byte cursor.

    Exact reads are admitted only when the whole source span exists. The cursor
    advances after the destination write succeeds, before the Result write.
    A later failure retains both the copied bytes and committed cursor. This
    is an explicit engine I/O policy, not observed native failure behavior.
    """

    def __init__(self, data: bytes, *, position: int = 0) -> None:
        if type(data) is not bytes or type(position) is not int or not 0 <= position <= len(data):
            raise ValueError("saved input requires immutable bytes and an in-range cursor")
        self._data = data
        self._position = position

    @property
    def position(self) -> int:
        return self._position

    @property
    def remaining(self) -> int:
        return len(self._data) - self._position

    def read_into(self, context: ReplayTaskRebuildStorage, destination: int, count: int) -> None:
        """Copy the requested span exactly; truncation refuses without mutation."""
        _validate(context, ReplayTaskRebuildCalls(None), destination, count)
        if count > self.remaining:
            raise UnresolvedReplayTaskRebuild("saved input exact span exceeds remaining bytes")
        end = self._position + count
        if count:
            _write(
                context,
                destination,
                count,
                int.from_bytes(self._data[self._position : end], "little"),
            )
        self._position = end


def bind_replay_saved_input(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    source: ReplaySavedInput,
    *,
    stream: int,
    target: int,
    result_bytes: bytes,
) -> ReplayTaskRebuildCalls:
    """Bind one explicit engine token and stream, with a declared48B Result.

    The token is nonzero u32 in the engine capability namespace, distinct from
    build54800 native body addresses. The reader still must fetch its current
    virtual method. Unknown tokens delegate normally; a selected token with a
    different stream refuses. No default successful Result is supplied.
    """
    _validate(context, calls, stream)
    _unsigned(target, 4, "saved input engine capability")
    if not stream or not target or not isinstance(source, ReplaySavedInput):
        raise ValueError("nonnull stream, engine capability and owned saved input required")
    if type(result_bytes) is not bytes or len(result_bytes) != 48:
        raise ValueError("explicit saved input48B Result profile required")
    result_word = int.from_bytes(result_bytes, "little")

    def dispatch(selected: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        if selected != target:
            if calls.call is None:
                raise UnresolvedReplayTaskRebuild(f"reached{selected:x} is unavailable")
            return calls.call(selected, args, data)
        if len(args) != 4 or data is not None:
            raise ValueError("malformed saved input read call")
        _validate(context, calls, *args)
        if args[0] != stream:
            raise UnresolvedReplayTaskRebuild("selected saved input capability has another stream")
        source.read_into(context, args[2], args[3])
        _write(context, args[1], 48, result_word)
        return args[1]

    return ReplayTaskRebuildCalls(dispatch)
