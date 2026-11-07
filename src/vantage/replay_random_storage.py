"""Build54800 masked RNG draw over current owned stream storage.

Full140903e40 scalar phases from native/path-backend-and-random. Its reached
140902700 logger has an explicit logging-disabled binding; enabled formatting
requires a separate implementation. Security-cookie/stack/FPstatus effects and
native faults are outside this effective storage interface.
"""

from __future__ import annotations

from .replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
    _call,
    _read,
    _unsigned,
    _write,
)

_U32 = (1 << 32) - 1


def _validate(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    *values: int,
) -> None:
    if not isinstance(context, ReplayTaskRebuildStorage):
        raise ValueError("explicit current random storage required")
    if not isinstance(calls, ReplayTaskRebuildCalls):
        raise ValueError("actual reached random effects required")
    for value in values:
        _unsigned(value, 8, "random argument")


def draw_replay_random_i15_storage(
    context: ReplayTaskRebuildStorage,
    stream: int,
    label: int,
    source_line: int,
    *,
    calls: ReplayTaskRebuildCalls,
) -> int:
    """Full140903e40 caller, including current repeated reads and logger effects.

    Increment calls first. Reread current index after each word publication;
    read the selected old words twice where the original does. The held masked
    result survives logging and is stored at88 only after the logger returns.
    Stream validity/backing and actual reached logger effects remain explicit.
    """
    _validate(context, calls, stream, label, source_line)
    _write(context, stream + 0x18, 4, _read(context, stream + 0x18, 4) + 1)
    index = _read(context, stream + 0x64, 4)
    old = _read(context, stream + 0x24 + index * 4, 4)
    third = ((index - 3) & 15) * 4 + stream + 0x24
    b = (((old * 2) & _U32) ^ _read(context, third, 4)) << 15 & _U32
    b ^= _read(context, third, 4)
    seventh = ((index - 7) & 15) * 4 + stream + 0x24
    b ^= old
    c = (_read(context, seventh, 4) >> 11) ^ _read(context, seventh, 4)
    combined = c ^ b
    transformed = (((c << 10) ^ b) << 13) & _U32
    _write(context, stream + 0x24 + index * 4, 4, combined)
    next_index = (_read(context, stream + 0x64, 4) - 1) & 15
    _write(context, stream + 0x64, 4, next_index)
    selected = stream + 0x24 + next_index * 4
    transformed = ((transformed ^ (combined & 0xFED22169)) << 3) & _U32
    transformed ^= _read(context, selected, 4)
    transformed = (transformed << 2) & _U32
    transformed ^= _read(context, selected, 4) ^ combined ^ b
    _write(context, selected, 4, transformed)
    current_index = _read(context, stream + 0x64, 4)
    masked = _read(context, stream + 0x24 + current_index * 4, 4) & 0x7FFF
    _call(calls, 0x140902700, (stream, masked, label, source_line & _U32))
    _write(context, stream + 0x88, 4, masked)
    return masked


def log_replay_random_draw_disabled(
    context: ReplayTaskRebuildStorage,
    stream: int,
) -> None:
    """140902700's explicit disabled-formatting profile, with exact gate reads.

    If stream20 is nonzero, both current globals are read before the global
    enable comparison, including when14435505e is zero. Enabled formatting
    refuses; no formatter, hidden stack structure or successful log is faked.
    """
    if not isinstance(context, ReplayTaskRebuildStorage):
        raise ValueError("explicit current random storage required")
    _unsigned(stream, 8, "random log stream")
    if not _read(context, stream + 0x20, 1):
        return
    enabled = _read(context, 0x14435505E, 1)
    _read(context, 0x14427C9B0, 1)
    if enabled:
        raise UnresolvedReplayTaskRebuild(
            "enabled random logging requires formatter implementation"
        )


def bind_replay_random_storage(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
) -> ReplayTaskRebuildCalls:
    """Bind full masked draw and the explicitly disabled logging profile."""
    _validate(context, calls)

    def dispatch(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        if target not in (0x140903E40, 0x140902700):
            if calls.call is None:
                raise UnresolvedReplayTaskRebuild(f"reached{target:x} is unavailable")
            return calls.call(target, args, data)
        if len(args) != (3 if target == 0x140903E40 else 4) or data is not None:
            raise ValueError("malformed random storage call")
        if target == 0x140903E40:
            return draw_replay_random_i15_storage(context, *args, calls=bound)
        for value in args:
            _unsigned(value, 8, "random log argument")
        log_replay_random_draw_disabled(context, args[0])
        return None

    bound = ReplayTaskRebuildCalls(dispatch)
    return bound
