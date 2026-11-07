"""Build54800 full SSO growth, QWORD commit and old-string release callers.

516 source bytes:278B1402bb300,157B1402ba970,81B1402a8840. Reached
allocator/memcpy/memset/free/error effects remain mandatory. Explicit current
logical backing is required; native physical stack/home/fence/fault/EH/thread
parity and actual allocation/import identity are not inferred.
"""

from __future__ import annotations

from vantage.replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
    _call,
    _read,
    _signed,
    _write,
)
from vantage.replay_unit_ai_base import _validate

_U32, _U64 = (1 << 32) - 1, (1 << 64) - 1
_MAX = (1 << 63) - 1


def _watson(
    context: ReplayTaskRebuildStorage,
    terminal: ReplayTaskRebuildCalls,
) -> None:
    _call(terminal, _read(context, 0x14319A060, 8), (0, 0, 0, 0, 0))
    raise UnresolvedReplayTaskRebuild("Player storage Watson returned before original INT3")


def grow_replay_player_sso(
    context: ReplayTaskRebuildStorage,
    header: int,
    increment: int,
    ignored_r8: int,
    fill_count: int,
    character: int,
    *,
    calls: ReplayTaskRebuildCalls,
) -> int:
    """Full278B1402bb300; five native effective arguments including unusedR8.

    Increment controls the held new length; independent fill_count controls the
    memset and terminator. Old capacity chooses the branch after allocation;
    the old heap pointer is current only after length/capacity stores. The fifth
    input is a raw logical argument whose lowBYTE is signextended at the native
    post-allocation load phase. Changes to physical incoming home+70 by a nested
    callee are outside this flattened-ABI profile. There is no implicit equality
    between counts, null-allocation shortcut, header rollback or unknown success.
    """
    _validate(context, calls, header, increment, ignored_r8, fill_count, character)
    old_length = _read(context, header + 0x10, 8)
    if ((_MAX - old_length) & _U64) < increment:
        _call(calls, 0x1402A91E0, ())
        raise UnresolvedReplayTaskRebuild("Player SSO length error returned before original INT3")
    old_capacity = _read(context, header + 0x18, 8)
    new_length = (old_length + increment) & _U64
    rounded = new_length | 15
    capacity = _MAX
    if rounded <= _MAX:
        half = old_capacity >> 1
        if old_capacity <= ((_MAX - half) & _U64):
            capacity = max(rounded, (old_capacity + half) & _U64)
    allocated = _call(calls, 0x1402A94D0, ((capacity + 1) & _U64,), width=8)
    signed_character = _signed(character & 255, 1) & _U32
    _write(context, header + 0x10, 8, new_length)
    _write(context, header + 0x18, 8, capacity)
    tail = (allocated + old_length) & _U64
    if old_capacity > 15:
        previous = _read(context, header, 8)
        _call(calls, 0x142D6E3B1, (allocated, previous, old_length))
        _call(calls, 0x142D6E3B7, (tail, signed_character, fill_count))
        _write(context, tail + fill_count, 1, 0)
        _call(calls, 0x1402A8840, (header, previous, old_capacity))
    else:
        _call(calls, 0x142D6E3B1, (allocated, header, old_length))
        _call(calls, 0x142D6E3B7, (tail, signed_character, fill_count))
        _write(context, tail + fill_count, 1, 0)
    _write(context, header, 8, allocated)
    return header


def commit_replay_player_skins(
    context: ReplayTaskRebuildStorage,
    header: int,
    replacement: int,
    size_qwords: int,
    capacity_qwords: int,
    *,
    calls: ReplayTaskRebuildCalls,
    imports: ReplayTaskRebuildCalls | None = None,
) -> None:
    """Full157B1402ba970; real old release before three held header publications."""
    _validate(context, calls, header, replacement, size_qwords, capacity_qwords)
    terminal = calls if imports is None else imports
    _validate(context, terminal)
    previous = _read(context, header, 8)
    if previous:
        size = (_read(context, header + 0x10, 8) - previous) & _U64 & ~7
        released = previous
        if size >= 0x1000:
            released = _read(context, previous - 8, 8)
            size = (size + 0x27) & _U64
            if ((previous - released - 8) & _U64) > 31:
                _watson(context, terminal)
        _call(calls, 0x142D6BAB4, (released, size))
    _write(context, header, 8, replacement)
    _write(context, header + 8, 8, replacement + size_qwords * 8)
    _write(context, header + 16, 8, replacement + capacity_qwords * 8)


def release_replay_player_sso(
    context: ReplayTaskRebuildStorage,
    ignored_holder: int,
    previous: int,
    old_capacity: int,
    *,
    calls: ReplayTaskRebuildCalls,
    imports: ReplayTaskRebuildCalls | None = None,
) -> None:
    """Full81B1402a8840; RCXunused, raw RDX/R8, real2arg free tail, no resets."""
    _validate(context, calls, ignored_holder, previous, old_capacity)
    terminal = calls if imports is None else imports
    _validate(context, terminal)
    size = (old_capacity + 1) & _U64
    released = previous
    if size >= 0x1000:
        released = _read(context, previous - 8, 8)
        size = (size + 0x27) & _U64
        if ((previous - released - 8) & _U64) > 31:
            _watson(context, terminal)
    _call(calls, 0x142D6BAB4, (released, size))


def bind_replay_player_name_skins_storage(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    *,
    imports: ReplayTaskRebuildCalls | None = None,
) -> ReplayTaskRebuildCalls:
    """Bind only3 whole storage entries; current Watson uses explicit terminal."""
    _validate(context, calls)
    terminal = calls if imports is None else imports
    _validate(context, terminal)

    def dispatch(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        arities = {0x1402BB300: 5, 0x1402BA970: 4, 0x1402A8840: 3}
        if target not in arities:
            if calls.call is None:
                raise UnresolvedReplayTaskRebuild(f"reached{target:x} unavailable")
            return calls.call(target, args, data)
        if len(args) != arities[target] or data is not None:
            raise ValueError("malformed Player name/skins storage call")
        if target == 0x1402BB300:
            return grow_replay_player_sso(context, *args, calls=bound)
        if target == 0x1402BA970:
            commit_replay_player_skins(context, *args, calls=bound, imports=terminal)
        else:
            release_replay_player_sso(context, *args, calls=bound, imports=terminal)
        return None

    bound = ReplayTaskRebuildCalls(dispatch)
    return bound
