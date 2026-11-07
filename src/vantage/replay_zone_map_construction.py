"""Build54800 zone constructor and shared-pair vector growth over current memory.

Complete480B1414ea4a0/309B1414ea070 source: tc-unit-ai15-zone-construction-source-v1.
Actual current calloc/memset/free imports and all reached vector/refresh/update
children are required. Native stack, faults, allocation failure/EH and thread
ordering are excluded. This does not infer a restored World or map context.
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
from .replay_unit_ai_base import _count, _validate
from .replay_unit_ai_map import ReplayUnitAIMapAtomics, _atomic
from .replay_zone_map_registry import _pairs

_U64 = (1 << 64) - 1
_U32 = (1 << 32) - 1
_MAX_PAIRS = (1 << 60) - 1


def construct_replay_zone_map(
    context: ReplayTaskRebuildStorage,
    address: int,
    dimensions: int,
    source: int,
    *,
    calls: ReplayTaskRebuildCalls,
    imports: ReplayTaskRebuildCalls | None = None,
) -> int:
    """Full480B caller with distinct initial overflow and current wrapping area.

    Row links use current context/base/header reads each iteration. The first
    memset passes0x200 unchanged and only current signed32 area bytes. Later
    cleanup follows current850, holding child identities across frees; no
    blanket cleanup/rollback or successful missing child is supplied.
    """
    _validate(context, calls, address, dimensions, source)
    terminal = calls if imports is None else imports
    _validate(context, terminal)
    vector = (address + 0x818) & _U64
    for offset in (0x818, 0x820, 0x828, 0x850):
        _write(context, address + offset, 8, 0)
    _write(context, address + 0x830, 8, dimensions)
    width = _signed(_read(context, dimensions + 0x30, 4), 4)
    height = _signed(_read(context, dimensions + 0x34, 4), 4)
    product = width * height
    count = product & _U64 if -(1 << 31) <= product < 1 << 31 else _U64
    target = _read(context, 0x143199DC0, 8)
    data = _call(terminal, target, (count, 2), width=8)
    _write(context, address + 0x808, 8, data)
    current = _read(context, address + 0x830, 8)
    height = _read(context, current + 0x34, 4)
    width = _read(context, current + 0x30, 4)
    area_bytes = _signed(height * width & _U32, 4) & _U64
    _call(calls, 0x142D6E3B7, (data, 0x200, area_bytes))
    current = _read(context, address + 0x830, 8)
    height = _signed(_read(context, current + 0x34, 4), 4) & _U64
    target = _read(context, 0x143199DC0, 8)
    rows = _call(terminal, target, (height, 8), width=8)
    _write(context, address + 0x810, 8, rows)
    index, displacement = 0, 0
    current = _read(context, address + 0x830, 8)
    while _signed(index, 4) < _signed(_read(context, current + 0x34, 4), 4):
        width = _read(context, current + 0x30, 4)
        offset = _signed(index * width & _U32, 4)
        row = _read(context, address + 0x808, 8) + offset * 2
        rows = _read(context, address + 0x810, 8)
        _write(context, rows + displacement, 8, row)
        index = index + 1 & _U32
        displacement = displacement + 8 & _U64
        current = _read(context, address + 0x830, 8)
    _call(calls, 0x142D6E3B7, (address, 0, 0x800))
    if source != vector:
        begin = _read(context, source, 8)
        count = _count(_read(context, source + 8, 8), begin)
        _call(calls, 0x14104EB10, (vector, begin, count))
    scratch = _call(calls, 0x142D6BA78, (40,), width=8)
    if scratch:
        _write(context, scratch, 16, 0)
        _write(context, scratch + 16, 16, 0)
        _write(context, scratch + 32, 8, 0)
        for offset in (0, 8, 16, 24):
            _write(context, scratch + offset, 8, 0)
        _write(context, scratch + 32, 1, 0)
    _write(context, address + 0x850, 8, scratch)
    # Only the effective low byte of the original R9B assignment is claimed.
    _call(calls, 0x14096E250, (scratch, 0x10, 0x201, 1))
    _call(calls, 0x1414EC840, (address,))
    _call(calls, 0x1414EC280, (address,))
    scratch = _read(context, address + 0x850, 8)
    if scratch:
        _call(calls, 0x142D6C270, (_read(context, scratch + 24, 8),))
        nested = _read(context, scratch, 8)
        if nested:
            _call(calls, 0x142D6C270, (_read(context, nested, 8),))
            linked = _read(context, nested + 8, 8)
            if linked:
                _call(calls, 0x14096E100, (linked, 1))
            _call(calls, 0x142D6BAB4, (nested, 16))
        _call(calls, 0x142D6BAB4, (scratch, 40))
    _write(context, address + 0x850, 8, 0)
    return address


def grow_replay_zone_pairs(
    context: ReplayTaskRebuildStorage,
    vector: int,
    insertion: int,
    source: int,
    *,
    calls: ReplayTaskRebuildCalls,
    atomics: ReplayUnitAIMapAtomics,
) -> int:
    """Full309B1414ea070; real ownership transfers and commit remain mandatory.

    Source pair reads follow allocation and new-slot zeroing. Hold the rounded
    insertion displacement; reread manager/source fields at source sites. Tail
    transfer is always called, including empty ranges. Runtime errors must not
    return; unexpected returns refuse before the verified original trap bytes.
    """
    _validate(context, calls, vector, insertion, source)
    if not isinstance(atomics, ReplayUnitAIMapAtomics):
        raise ValueError("actual shared-count operations required")
    end = _read(context, vector + 8, 8)
    begin = _read(context, vector, 8)
    length = _pairs(end, begin)
    displacement = (insertion - begin) & _U64
    if length == _MAX_PAIRS:
        _call(calls, 0x1414EC260, ())
        raise UnresolvedReplayTaskRebuild("nonreturning pair length error returned before INT3")
    capacity = _pairs(_read(context, vector + 16, 8), begin)
    requested = length + 1 & _U64
    half = capacity >> 1
    grown = _MAX_PAIRS if capacity > _MAX_PAIRS - half else max(requested, capacity + half)
    if grown > _MAX_PAIRS:
        _call(calls, 0x1402A9460, ())
        raise UnresolvedReplayTaskRebuild("nonreturning pair allocation error returned before INT3")
    allocation = _call(calls, 0x1402A94D0, (grown << 4,), width=8)
    slot = allocation + (displacement & ~15) & _U64
    _write(context, slot, 8, 0)
    _write(context, slot + 8, 8, 0)
    control = _read(context, source + 8, 8)
    if control:
        _atomic(atomics, control + 8, 1)
    _write(context, slot, 8, _read(context, source, 8))
    _write(context, slot + 8, 8, _read(context, source + 8, 8))
    end = _read(context, vector + 8, 8)
    begin = _read(context, vector, 8)
    tail_destination = allocation
    if insertion != end:
        _call(calls, 0x1414EA3E0, (begin, insertion, allocation, vector))
        end = _read(context, vector + 8, 8)
        begin = insertion
        tail_destination = slot + 16 & _U64
    _call(calls, 0x1414EA3E0, (begin, end, tail_destination, vector))
    _call(calls, 0x1414EC140, (vector, allocation, requested, grown))
    return slot


def bind_replay_zone_map_construction(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    *,
    atomics: ReplayUnitAIMapAtomics,
    imports: ReplayTaskRebuildCalls | None = None,
) -> ReplayTaskRebuildCalls:
    """Bind both complete callers and verified current CRT import thunk chains."""
    _validate(context, calls)
    terminal = calls if imports is None else imports
    _validate(context, terminal)
    if not isinstance(atomics, ReplayUnitAIMapAtomics):
        raise ValueError("actual shared-count operations required")

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
        arities = {0x1414EA4A0: 3, 0x1414EA070: 3, 0x142D6E3B7: 3, 0x142D6C270: 1, 0x142D6BAB4: 2}
        if target not in arities:
            return delegate(target, args, data)
        if len(args) != arities[target] or data is not None:
            raise ValueError("malformed zone constructor call")
        if target == 0x1414EA4A0:
            return construct_replay_zone_map(context, *args, calls=bound, imports=terminal)
        if target == 0x1414EA070:
            return grow_replay_zone_pairs(context, *args, calls=bound, atomics=atomics)
        for value in args:
            # _validate only checks raw unsigned arguments; no data access.
            _validate(context, calls, value)
        slot = 0x143199938 if target == 0x142D6E3B7 else 0x143199DD0
        return delegate(_read(context, slot, 8), args, None, imported=True)

    bound = ReplayTaskRebuildCalls(dispatch)
    return bound
