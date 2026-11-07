"""Build54800 complete394B/117instruction identifier string operations.

Source: player-named-identifier-children-source-v1. Current fields, overlapping
headers and reached free/growth/copy/destructor effects retain source order.
Native physical stack/home/register aliases, faults/EH and concurrency are
outside these effective scalar APIs. No string encoding or NUL is inferred.
"""

from __future__ import annotations

from vantage.replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
    _call,
    _read,
    _write,
)
from vantage.replay_unit_ai_base import _validate

_U64 = (1 << 64) - 1
_EMPTY = 0x14428BB30


def clear_replay_player_identifier_string(
    context: ReplayTaskRebuildStorage,
    address: int,
    keep: int,
    *,
    calls: ReplayTaskRebuildCalls,
) -> None:
    """Full77B140a1a7e0; zero capacity skips all other backing accesses."""
    _validate(context, calls, address, keep)
    if not _read(context, address + 16, 8):
        return
    if keep & 0xFF:
        _write(context, address + 8, 8, 0)
        pointer = _read(context, address, 8)
        _write(context, pointer, 1, 0)
        return
    pointer = _read(context, address, 8)
    if pointer:
        _call(calls, 0x142D6C270, (pointer,))
        for offset, value in ((0, _EMPTY), (16, 0), (8, 0)):
            _write(context, address + offset, 8, value)


def _clear_destination(
    context: ReplayTaskRebuildStorage,
    address: int,
    calls: ReplayTaskRebuildCalls,
) -> None:
    pointer = _read(context, address, 8)
    if pointer:
        if _read(context, address + 16, 8):
            _call(calls, 0x142D6C270, (pointer,))
        for offset, value in ((0, _EMPTY), (16, 0), (8, 0)):
            _write(context, address + offset, 8, value)


def copy_replay_player_identifier_string(
    context: ReplayTaskRebuildStorage,
    destination: int,
    source: int,
    *,
    calls: ReplayTaskRebuildCalls,
) -> int:
    """Full131B140a15b60; hold length, reload both pointers after actual growth."""
    _validate(context, calls, destination, source)
    if destination != source:
        _clear_destination(context, destination, calls)
        length = _read(context, source + 8, 8)
        if length:
            _call(calls, 0x140A1A5E0, (destination, (length + 1) & _U64))
            source_pointer = _read(context, source, 8)
            destination_pointer = _read(context, destination, 8)
            _call(calls, 0x142D6E3B1, (destination_pointer, source_pointer, length))
            pointer = _read(context, destination, 8)
            _write(context, pointer + length, 1, 0)
            _write(context, destination + 8, 8, length)
    return destination


def move_replay_player_identifier_string(
    context: ReplayTaskRebuildStorage,
    destination: int,
    source: int,
    *,
    calls: ReplayTaskRebuildCalls,
) -> int:
    """Full137B140a15ad0; sequential reads retain overlapping-header effects."""
    _validate(context, calls, destination, source)
    if destination != source:
        _clear_destination(context, destination, calls)
        for offset in (0, 16, 8):
            _write(context, destination + offset, 8, _read(context, source + offset, 8))
        for offset, value in ((0, _EMPTY), (16, 0), (8, 0)):
            _write(context, source + offset, 8, value)
    return destination


def assign_replay_player_named_identifier(
    context: ReplayTaskRebuildStorage,
    address: int,
    temporary: int,
    *,
    calls: ReplayTaskRebuildCalls,
) -> None:
    """Full49B1416607b0; ordered flag/value stores precede move and destruction."""
    _validate(context, calls, address, temporary)
    _write(context, address, 1, 0)
    _write(context, address + 4, 4, 0xFFFFFFFE)
    _call(calls, 0x140A15AD0, ((address + 8) & _U64, temporary))
    _call(calls, 0x140A1B220, (temporary,))


def bind_replay_player_identifier_strings(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
) -> ReplayTaskRebuildCalls:
    """Bind four complete entries; every reached child remains mandatory."""
    _validate(context, calls)

    def dispatch(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        entries = {
            0x140A1A7E0: clear_replay_player_identifier_string,
            0x140A15B60: copy_replay_player_identifier_string,
            0x140A15AD0: move_replay_player_identifier_string,
            0x1416607B0: assign_replay_player_named_identifier,
        }
        function = entries.get(target)
        if function is None:
            if calls.call is None:
                raise UnresolvedReplayTaskRebuild(f"reached{target:x} is unavailable")
            return calls.call(target, args, data)
        if len(args) != 2 or data is not None:
            raise ValueError("malformed Player identifier string call")
        return function(context, *args, calls=bound)

    bound = ReplayTaskRebuildCalls(dispatch)
    return bound
