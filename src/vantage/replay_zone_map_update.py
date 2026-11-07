"""Build54800 zone adjacency/bridge update with exact current-memory chronology.

Full1421B1414ec280: world-tile-map-postdecode-source-v1. The54B lookup is
reused from replay_unit_ai_map. Allocations and current memset imports remain
real effects; unwritten buffer bytes are not inferred initialized. Native
faults, stack/cookies, threading and C++ exception behavior are excluded.
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
from .replay_unit_ai_map import lookup_replay_ai_zone

_U64 = (1 << 64) - 1
_U32 = (1 << 32) - 1
_NEIGHBORS = ((-1, -1), (0, -1), (1, -1), (-1, 0), (0, 0), (1, 0), (-1, 1), (0, 1), (1, 1))


def _index(size: int, row: int, column: int) -> int:
    return _signed(size * row + column & _U32, 4)


def update_replay_zone_map(
    context: ReplayTaskRebuildStorage,
    address: int,
    *,
    calls: ReplayTaskRebuildCalls,
) -> None:
    """Full1421B caller: held area, nine ordered neighbors and bridge scan.

    The second allocation is made even if the first is null. Initialization
    uses the same held byte count for both planes, despite their different
    allocation sizes. Neighbor prechecks intentionally use width on both axes;
    the actual getter separately checks height. Loop-end tests retain the last
    neighbor's context; each completed getter retains its preceding region count
    while the adjacency pointer is reloaded before the byte store.
    """
    _validate(context, calls, address)
    count = _read(context, address + 0x838, 4)
    area = _signed(count * count & _U32, 4) & _U64
    first = _call(calls, 0x142D6C268, (area,), width=8)
    _write(context, address + 0x840, 8, first)
    doubled = area * 2
    second = _call(calls, 0x142D6C268, (doubled if doubled <= _U64 else _U64,), width=8)
    first = _read(context, address + 0x840, 8)
    _write(context, address + 0x848, 8, second)
    if not first or not second:
        return
    _call(calls, 0x142D6E3B7, (first, 0, area))
    _call(calls, 0x142D6E3B7, (_read(context, address + 0x848, 8), 0x200, area))
    current = _read(context, address + 0x830, 8)
    if _signed(_read(context, current + 0x34, 4), 4) > 0:
        row_bytes, outer = 0, 1
        while True:
            if _signed(_read(context, current + 0x30, 4), 4) > 0:
                cell_bytes, column, inner = 0, 0, 1
                while True:
                    y = _signed(outer - 1 & _U32, 4)
                    x = _signed(inner - 1 & _U32, 4)
                    zone = 0
                    if (
                        y >= 0
                        and y < _signed(_read(context, current + 0x34, 4), 4)
                        and _signed(column, 4) >= 0
                        and x < _signed(_read(context, current + 0x30, 4), 4)
                    ):
                        row = _read(context, _read(context, address + 0x810, 8) + row_bytes, 8)
                        zone = _read(context, row + cell_bytes, 2)
                    for position, (dx, dy) in enumerate(_NEIGHBORS):
                        if position:
                            current = _read(context, address + 0x830, 8)
                        width = _signed(_read(context, current + 0x30, 4), 4)
                        nx = _signed(inner + dx - 1 & _U32, 4)
                        ny = _signed(outer + dy - 1 & _U32, 4)
                        if nx < width and nx >= 0 and ny < width and ny >= 0:
                            count = _read(context, address + 0x838, 4)
                            if zone <= _signed(count, 4):
                                other = (
                                    _call(
                                        calls, 0x1414ECF50, (address, nx & _U32, ny & _U32), width=8
                                    )
                                    & 0xFFFF
                                )
                                offset = _index(count, zone, other)
                                _write(context, _read(context, address + 0x840, 8) + offset, 1, 1)
                                if position == 8:
                                    current = _read(context, address + 0x830, 8)
                    previous = inner
                    inner, column = inner + 1 & _U32, column + 1 & _U32
                    cell_bytes = cell_bytes + 2 & _U64
                    if _signed(previous, 4) >= _signed(_read(context, current + 0x30, 4), 4):
                        break
            previous = outer
            outer, row_bytes = outer + 1 & _U32, row_bytes + 8 & _U64
            if _signed(previous, 4) >= _signed(_read(context, current + 0x34, 4), 4):
                break
    count = _read(context, address + 0x838, 4)
    outer = 0
    while _signed(outer, 4) < _signed(count, 4):
        inner = 0
        row = outer & 0xFFFF
        while _signed(inner, 4) < _signed(count, 4):
            column = inner & 0xFFFF
            if row <= _signed(count, 4) and column <= _signed(count, 4):
                byte = _read(
                    context, _read(context, address + 0x840, 8) + _index(count, row, column), 1
                )
                if (
                    not byte
                    and row <= _signed(count, 4)
                    and column <= _signed(count, 4)
                    and _signed(count, 4) > 0
                ):
                    bridge = 0
                    while _signed(bridge, 4) < _signed(count, 4):
                        candidate = bridge & 0xFFFF
                        if candidate <= _signed(count, 4):
                            left = _read(
                                context,
                                _read(context, address + 0x840, 8) + _index(count, row, candidate),
                                1,
                            )
                            if left:
                                right = _read(
                                    context,
                                    _read(context, address + 0x840, 8)
                                    + _index(count, column, candidate),
                                    1,
                                )
                                if right:
                                    _write(
                                        context,
                                        _read(context, address + 0x848, 8)
                                        + _index(count, row, column) * 2,
                                        2,
                                        candidate,
                                    )
                                    break
                        bridge = bridge + 1 & _U32
            count = _read(context, address + 0x838, 4)
            inner = inner + 1 & _U32
        outer = outer + 1 & _U32


def bind_replay_zone_map_update(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    *,
    imports: ReplayTaskRebuildCalls | None = None,
) -> ReplayTaskRebuildCalls:
    """Bind update/getter and genuine allocator/current-memset thunk paths."""
    _validate(context, calls)
    terminal = calls if imports is None else imports
    _validate(context, terminal)

    def dispatch(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        arities = {0x1414EC280: 1, 0x1414ECF50: 3, 0x142D6C268: 1, 0x142D6E3B7: 3}
        if target not in arities:
            if calls.call is None:
                raise UnresolvedReplayTaskRebuild(f"reached{target:x} is unavailable")
            return calls.call(target, args, data)
        if len(args) != arities[target] or data is not None:
            raise ValueError("malformed zone update call")
        if target == 0x1414EC280:
            update_replay_zone_map(context, args[0], calls=bound)
        elif target == 0x1414ECF50:
            return lookup_replay_ai_zone(context, *args)
        elif target == 0x142D6C268:
            _validate(context, calls, *args)
            return _call(calls, 0x142D6BA78, args, width=8)
        else:
            _validate(context, calls, *args)
            imported = _read(context, 0x143199938, 8)
            if terminal.call is None:
                raise UnresolvedReplayTaskRebuild(f"reached{imported:x} is unavailable")
            return terminal.call(imported, args, None)
        return None

    bound = ReplayTaskRebuildCalls(dispatch)
    return bound
