"""Build54800 zone pool, region count and recursive scratch-chain cleanup.

Complete535B source: tc-unit-ai15-zone-queue-finalize-source-v1 and
tc-unit-ai15-zone-scratch-cleanup-source-v1. Current backing and real allocator,
free and memset effects are required. Native faults, EH, concurrent memory and
host stack parity are excluded; recursive calls use ordinary Python recursion.
No restored map/World or successful missing runtime effect is inferred.
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
_U32 = (1 << 32) - 1


def get_replay_zone_node(
    context: ReplayTaskRebuildStorage,
    scratch: int,
    *,
    calls: ReplayTaskRebuildCalls,
) -> int:
    """Full248B14096e150, including current pool growth and clear-on-get.

    Growth frees the old pointer array before allocating its replacement.
    Header/pointer reloads and partial effects survive any reached failure.
    Null list-node allocation is not converted into a successful null result.
    """
    _validate(context, calls, scratch)
    if _read(context, scratch + 0x10, 4) == 0:
        growth = _read(context, scratch + 0xC, 4)
        _write(context, scratch + 0x14, 4, _read(context, scratch + 0x14, 4) + growth)
        _call(calls, 0x142D6C270, (_read(context, scratch + 0x18, 8),))
        capacity = _read(context, scratch + 0x14, 4)
        # MUL64 of zeroextended DWORD capacity by8 cannot carry.
        pointers = _call(calls, 0x142D6C268, (capacity * 8,), width=8)
        _write(context, scratch + 0x18, 8, pointers)
        node = _call(calls, 0x142D6BA78, (16,), width=8)
        if node:
            _write(context, node, 16, 0)
            _write(context, node, 8, 0)
            _write(context, node + 8, 8, 0)
        count = _read(context, scratch + 0xC, 4)
        stride = _read(context, scratch + 8, 4)
        data = _call(calls, 0x142D6C268, (count * stride & _U32,), width=8)
        _write(context, node, 8, data)
        _write(context, node + 8, 8, _read(context, scratch, 8))
        growth = _read(context, scratch + 0xC, 4)
        _write(context, scratch, 8, node)
        cursor = _read(context, node, 8)
        if growth == 0:
            return 0
        index = 0
        while True:
            available = _read(context, scratch + 0x10, 4)
            index = index + 1 & _U32
            pointers = _read(context, scratch + 0x18, 8)
            _write(context, pointers + available * 8, 8, cursor)
            stride = _read(context, scratch + 8, 4)
            _write(context, scratch + 0x10, 4, _read(context, scratch + 0x10, 4) + 1)
            cursor = cursor + stride & _U64
            if index >= _read(context, scratch + 0xC, 4):
                break
    _write(context, scratch + 0x10, 4, _read(context, scratch + 0x10, 4) - 1)
    clear = _read(context, scratch + 0x20, 1)
    available = _read(context, scratch + 0x10, 4)
    pointers = _read(context, scratch + 0x18, 8)
    selected = _read(context, pointers + available * 8, 8)
    if clear:
        _call(calls, 0x142D6E3B7, (selected, 0, _read(context, scratch + 8, 4)))
    return selected


def return_replay_zone_node(
    context: ReplayTaskRebuildStorage,
    scratch: int,
    node: int,
) -> None:
    """Full16B14096e260: store raw RDX, then increment the current count."""
    _validate(context, ReplayTaskRebuildCalls(None), scratch, node)
    available = _read(context, scratch + 0x10, 4)
    pointers = _read(context, scratch + 0x18, 8)
    _write(context, pointers + available * 8, 8, node)
    _write(context, scratch + 0x10, 4, _read(context, scratch + 0x10, 4) + 1)


def count_replay_zone_region(
    context: ReplayTaskRebuildStorage,
    address: int,
    region: int,
) -> int:
    """Full196B1414ed250; positive signed cache skips all context/grid reads.

    Nonpositive cache scans captured width outside captured height, with current
    row pointers per cell. Counters wrap32; the held cache address is committed
    only after the scan. Region indexing uses lowDX without an invented bound.
    """
    _validate(context, ReplayTaskRebuildCalls(None), address, region)
    region &= 0xFFFF
    entry = address + region * 4 & _U64
    cached = _read(context, entry, 4)
    if _signed(cached, 4) > 0:
        return cached
    dimensions = _read(context, address + 0x830, 8)
    width = _signed(_read(context, dimensions + 0x30, 4), 4)
    height = _signed(_read(context, dimensions + 0x34, 4), 4)
    count = 0
    for column in range(max(0, width)):
        for row in range(max(0, height)):
            pointer = _read(context, _read(context, address + 0x810, 8) + row * 8, 8)
            if _read(context, pointer + column * 2, 2) == region:
                count = count + 1 & _U32
    _write(context, entry, 4, count)
    return count


def cleanup_replay_zone_chain(
    context: ReplayTaskRebuildStorage,
    node: int,
    flags: int,
    *,
    calls: ReplayTaskRebuildCalls,
) -> int:
    """Full75B14096e100; data forward, nodes on recursive unwinding.

    Read next after the data free; descendants always receive flag1. Return
    the held node token even if freed. The real self call remains visible in
    the dispatcher; no synthetic recursion guard or blanket cleanup is added.
    """
    _validate(context, calls, node, flags)
    _call(calls, 0x142D6C270, (_read(context, node, 8),))
    linked = _read(context, node + 8, 8)
    if linked:
        _call(calls, 0x14096E100, (linked, 1))
    if flags & 1:
        _call(calls, 0x142D6BAB4, (node, 16))
    return node


def bind_replay_zone_queue(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    *,
    imports: ReplayTaskRebuildCalls | None = None,
) -> ReplayTaskRebuildCalls:
    """Bind four bodies plus genuine allocator and current free/memset aliases.

    Ordinary unknown entries delegate below; current IAT targets use explicit
    terminal imports so a target equal to a bound thunk cannot recurse here.
    """
    _validate(context, calls)
    terminal = calls if imports is None else imports
    _validate(context, terminal)

    def delegate(
        target: int,
        args: tuple[int, ...],
        data: memoryview | None,
        *,
        imported: bool = False,
    ) -> int | None:
        receiver = terminal if imported else calls
        if receiver.call is None:
            raise UnresolvedReplayTaskRebuild(f"reached{target:x} is unavailable")
        return receiver.call(target, args, data)

    def dispatch(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        arities = {
            0x14096E150: 1,
            0x14096E260: 2,
            0x1414ED250: 2,
            0x14096E100: 2,
            0x142D6C268: 1,
            0x142D6C270: 1,
            0x142D6BAB4: 2,
            0x142D6E3B7: 3,
        }
        if target not in arities:
            return delegate(target, args, data)
        if len(args) != arities[target] or data is not None:
            raise ValueError("malformed zone queue call")
        for value in args:
            _validate(context, calls, value)
        if target == 0x14096E150:
            return get_replay_zone_node(context, *args, calls=bound)
        if target == 0x14096E260:
            return_replay_zone_node(context, *args)
            return None
        if target == 0x1414ED250:
            return count_replay_zone_region(context, *args)
        if target == 0x14096E100:
            return cleanup_replay_zone_chain(context, *args, calls=bound)
        if target == 0x142D6C268:
            return _call(bound, 0x142D6BA78, args, width=8)
        slot = 0x143199938 if target == 0x142D6E3B7 else 0x143199DD0
        return delegate(_read(context, slot, 8), args, None, imported=True)

    bound = ReplayTaskRebuildCalls(dispatch)
    return bound
