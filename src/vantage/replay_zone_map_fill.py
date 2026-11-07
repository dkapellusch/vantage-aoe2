"""Build54800 zone flood fill and pair/float-buffer release over owned storage.

Complete993B1414eca00,113B1414e9ff0 and85B1410565b0:
tc-unit-ai15-zone-fill-release-source-v1. Queue operations, final counting,
current imports and shared-control virtuals remain actual required effects.
Native FPstatus, faults, threading, stack/cookies and C++ unwinding are excluded.
"""

from __future__ import annotations

from .replay_binary32 import compare_binary32
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
from .replay_unit_ai_map import ReplayUnitAIMapAtomics, _release

_U64 = (1 << 64) - 1
_U32 = (1 << 32) - 1


def release_replay_zone_pairs(
    context: ReplayTaskRebuildStorage,
    begin: int,
    end: int,
    *,
    calls: ReplayTaskRebuildCalls,
    atomics: ReplayUnitAIMapAtomics,
) -> None:
    """Full113B1414e9ff0; an empty range performs no storage/atomic access."""
    _validate(context, calls, begin, end)
    if not isinstance(atomics, ReplayUnitAIMapAtomics):
        raise ValueError("actual zone shared-count bindings required")
    while begin != end:
        control = _read(context, begin + 8, 8)
        if control:
            _release(context, control, calls, atomics)
        begin = begin + 16 & _U64


def release_replay_zone_mask(
    context: ReplayTaskRebuildStorage,
    vector: int,
    begin: int,
    capacity: int,
    *,
    calls: ReplayTaskRebuildCalls,
    imports: ReplayTaskRebuildCalls | None = None,
) -> None:
    """Full85B1410565b0; incomingRCX ignored, RDX begin and R8 count consumed."""
    _validate(context, calls, vector, begin, capacity)
    terminal = calls if imports is None else imports
    _validate(context, terminal)
    size = capacity * 4 & _U64
    pointer = begin
    if size >= 0x1000:
        pointer = _read(context, begin - 8, 8)
        size = size + 0x27 & _U64
        if (begin - pointer - 8) & _U64 > 31:
            _call(terminal, _read(context, 0x14319A060, 8), (0, 0, 0, 0, 0))
            raise UnresolvedReplayTaskRebuild("nonreturning mask Watson returned before INT3")
    _call(calls, 0x142D6BAB4, (pointer, size))


def flood_replay_zone_map(
    context: ReplayTaskRebuildStorage,
    address: int,
    x: int,
    y: int,
    positive: int,
    region: int,
    *,
    calls: ReplayTaskRebuildCalls,
) -> None:
    """Full993B1414eca00; exact neighbor, mark/get/link and read/pop order.

    Captured signed32 width/height-minus-one only gate right/down. Each reached
    neighbor uses current context and source-specific repeated bounds reads.
    The queue-get child must initialize its returned link: this caller never
    writes a new node's next field. Only effective input BYTE/WORD are claimed.
    """
    _validate(context, calls, address, x, y, positive, region)
    x, y = _signed(x & _U32, 4), _signed(y & _U32, 4)
    positive, region = int(bool(positive & 0xFF)), region & 0xFFFF
    dimensions = _read(context, address + 0x830, 8)
    right = _signed(_read(context, dimensions + 0x30, 4) - 1 & _U32, 4)
    down = _signed(_read(context, dimensions + 0x34, 4) - 1 & _U32, 4)
    head = tail = 0

    def tile_at(current: int, nx: int, ny: int) -> tuple[int, bool]:
        base = _read(context, current + 8, 8)
        if base and ny >= 0 and ny < _signed(_read(context, current + 0x34, 4), 4) and nx >= 0:
            width = _read(context, current + 0x30, 4)
            if nx < _signed(width, 4):
                index = _signed(width * ny & _U32, 4) + nx
                return base + index * 64 & _U64, True
        return 0, False

    def neighbor(nx: int, ny: int, *, vertical: bool, mask_first: bool = False) -> None:
        nonlocal head, tail
        current = _read(context, address + 0x830, 8)
        tile, valid_tile = tile_at(current, nx, ny)
        # Left/right omit repeated y checks only on the valid tile branch.
        if (vertical or not valid_tile) and (
            ny < 0 or ny >= _signed(_read(context, current + 0x34, 4), 4)
        ):
            return
        if nx < 0 or nx >= _signed(_read(context, current + 0x30, 4), 4):
            return
        row = _read(context, _read(context, address + 0x810, 8) + ny * 8, 8)
        cell = row + nx * 2 & _U64
        if _read(context, cell, 2) != 0x200:
            return
        if mask_first:
            mask = _read(context, address + 0x818, 8)
            kind = _read(context, tile + 9, 1)
        else:
            kind = _read(context, tile + 9, 1)
            mask = _read(context, address + 0x818, 8)
        if int(compare_binary32(_read(context, mask + kind * 4, 4), 0) == 1) != positive:
            return
        _write(context, cell, 2, region)
        node = _call(calls, 0x14096E150, (_read(context, address + 0x850, 8),), width=8)
        if tail:
            _write(context, tail + 8, 8, node)
        _write(context, node, 4, nx)
        _write(context, node + 4, 4, ny)
        tail = node
        if not head:
            head = node

    while True:
        if x > 0:
            neighbor(_signed(x - 1 & _U32, 4), y, vertical=False)
        if y > 0:
            neighbor(x, _signed(y - 1 & _U32, 4), vertical=True, mask_first=True)
        if x < right:
            neighbor(_signed(x + 1 & _U32, 4), y, vertical=False)
        if y < down:
            neighbor(x, _signed(y + 1 & _U32, 4), vertical=True)
        if not head:
            _call(calls, 0x1414ED250, (address, region))
            return
        x = _signed(_read(context, head, 4), 4)
        y = _signed(_read(context, head + 4, 4), 4)
        scratch = _read(context, address + 0x850, 8)
        old_head, head = head, _read(context, head + 8, 8)
        _call(calls, 0x14096E260, (scratch, old_head))
        if not head:
            tail = 0


def bind_replay_zone_map_fill(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    *,
    atomics: ReplayUnitAIMapAtomics,
    imports: ReplayTaskRebuildCalls | None = None,
) -> ReplayTaskRebuildCalls:
    """Bind full fill/releases; effective ignored pair-ownerR8 may be forwarded."""
    _validate(context, calls)
    terminal = calls if imports is None else imports
    _validate(context, terminal)
    if not isinstance(atomics, ReplayUnitAIMapAtomics):
        raise ValueError("actual zone shared-count bindings required")

    def dispatch(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        arities = {0x1414ECA00: (5,), 0x1414E9FF0: (2, 3), 0x1410565B0: (3,), 0x142D6BAB4: (2,)}
        if target not in arities:
            if calls.call is None:
                raise UnresolvedReplayTaskRebuild(f"reached{target:x} is unavailable")
            return calls.call(target, args, data)
        if len(args) not in arities[target] or data is not None:
            raise ValueError("malformed zone fill/release call")
        if target == 0x1414ECA00:
            flood_replay_zone_map(context, *args, calls=bound)
        elif target == 0x1414E9FF0:
            _validate(context, calls, *args)
            release_replay_zone_pairs(context, *args[:2], calls=bound, atomics=atomics)
        elif target == 0x1410565B0:
            release_replay_zone_mask(context, *args, calls=bound, imports=terminal)
        else:
            _validate(context, calls, *args)
            imported = _read(context, 0x143199DD0, 8)
            if terminal.call is None:
                raise UnresolvedReplayTaskRebuild(f"reached{imported:x} is unavailable")
            return terminal.call(imported, args, None)
        return None

    bound = ReplayTaskRebuildCalls(dispatch)
    return bound
