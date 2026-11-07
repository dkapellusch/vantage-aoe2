"""Build54800 zone float-vector assignment, refresh and shared-pair transfers.

Five complete bodies (1098B): tc-unit-ai15-zone-normal-children-source-v1.
Flood fill, range release and nonnull vector growth remain mandatory real calls.
Current field reloads, held iteration bounds and byte/word ordering follow ASM;
native FPstatus, faults, concurrency, stack and C++ unwinding are excluded.
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
from .replay_unit_ai_base import _count, _validate

_U64 = (1 << 64) - 1
_U32 = (1 << 32) - 1
_MAX_FLOATS = (1 << 62) - 1


def _copy_words(context: ReplayTaskRebuildStorage, dest: int, source: int, count: int) -> int:
    for _ in range(count):
        _write(context, dest, 4, _read(context, source, 4))
        source, dest = source + 4 & _U64, dest + 4 & _U64
    return dest


def assign_replay_zone_mask(
    context: ReplayTaskRebuildStorage,
    vector: int,
    source: int,
    requested: int,
    *,
    calls: ReplayTaskRebuildCalls,
) -> None:
    """Full362B14104eb10; ordered DWORD tail copies, not an inferred bulk move."""
    _validate(context, calls, vector, source, requested)
    begin = _read(context, vector, 8)
    capacity = _count(_read(context, vector + 16, 8), begin)
    if requested > capacity:
        if requested > _MAX_FLOATS:
            _call(calls, 0x140B747A0, ())
            raise UnresolvedReplayTaskRebuild("nonreturning float length error returned")
        half = capacity >> 1
        grown = _MAX_FLOATS if capacity > _MAX_FLOATS - half else max(requested, capacity + half)
        if begin:
            # R8 retains the raw element capacity at14104eb7f; the release
            # child consumes it despite its omission from the caller's C.
            _call(calls, 0x1410565B0, (vector, begin, capacity))
            for offset in (0, 8, 16):
                _write(context, vector + offset, 8, 0)
        if grown > _MAX_FLOATS:
            _call(calls, 0x1402A9460, ())
            raise UnresolvedReplayTaskRebuild("nonreturning float allocation error returned")
        begin = _call(calls, 0x1402A94D0, (grown * 4,), width=8)
        _write(context, vector, 8, begin)
        _write(context, vector + 8, 8, begin)
        _write(context, vector + 16, 8, begin + grown * 4)
        end = _copy_words(context, begin, source, requested)
    else:
        length = _count(_read(context, vector + 8, 8), begin)
        if requested > length:
            prefix = length * 4 & _U64
            _call(calls, 0x142D6E3DB, (begin, source, prefix))
            destination = _read(context, vector + 8, 8)
            end = _copy_words(context, destination, source + prefix & _U64, requested - length)
        else:
            size = requested * 4 & _U64
            _call(calls, 0x142D6E3DB, (begin, source, size))
            end = begin + size & _U64
    _write(context, vector + 8, 8, end)


def initialize_replay_zone_scratch(
    context: ReplayTaskRebuildStorage,
    address: int,
    width: int,
    sentinel: int,
    enabled: int,
) -> int:
    """Full14B14096e250, DWORD8 then DWORDc then BYTE20; effective AL1 only."""
    _validate(context, ReplayTaskRebuildCalls(None), address, width, sentinel, enabled)
    _write(context, address + 8, 4, width)
    _write(context, address + 12, 4, sentinel)
    _write(context, address + 32, 1, enabled)
    return 1


def move_replay_zone_pairs(
    context: ReplayTaskRebuildStorage,
    begin: int,
    end: int,
    destination: int,
    owner: int,
    *,
    calls: ReplayTaskRebuildCalls,
) -> int:
    """Full100B1414ea3e0; move-and-zero each pair, then mandatory even-empty release."""
    _validate(context, calls, begin, end, destination, owner)
    while begin != end:
        _write(context, destination, 8, 0)
        _write(context, destination + 8, 8, 0)
        _write(context, destination, 8, _read(context, begin, 8))
        _write(context, destination + 8, 8, _read(context, begin + 8, 8))
        _write(context, begin, 8, 0)
        _write(context, begin + 8, 8, 0)
        begin, destination = begin + 16 & _U64, destination + 16 & _U64
    _call(calls, 0x1414E9FF0, (destination, destination, owner))
    return destination


def commit_replay_zone_pairs(
    context: ReplayTaskRebuildStorage,
    vector: int,
    allocation: int,
    size: int,
    capacity: int,
    *,
    calls: ReplayTaskRebuildCalls,
    imports: ReplayTaskRebuildCalls | None = None,
) -> None:
    """Full175B1414ec140; release current old range/free before held new headers."""
    _validate(context, calls, vector, allocation, size, capacity)
    terminal = calls if imports is None else imports
    _validate(context, terminal)
    begin = _read(context, vector, 8)
    if begin:
        _call(calls, 0x1414E9FF0, (begin, _read(context, vector + 8, 8), vector))
        begin = _read(context, vector, 8)
        byte_capacity = (_read(context, vector + 16, 8) - begin) & (_U64 ^ 15)
        to_free = begin
        if byte_capacity >= 0x1000:
            to_free = _read(context, begin - 8, 8)
            byte_capacity = byte_capacity + 0x27 & _U64
            if (begin - to_free - 8) & _U64 > 31:
                target = _read(context, 0x14319A060, 8)
                _call(terminal, target, (0, 0, 0, 0, 0))
                raise UnresolvedReplayTaskRebuild("nonreturning pair Watson returned before INT3")
        _call(calls, 0x142D6BAB4, (to_free, byte_capacity))
    _write(context, vector, 8, allocation)
    _write(context, vector + 8, 8, allocation + (size << 4))
    _write(context, vector + 16, 8, allocation + (capacity << 4))


def refresh_replay_zone_map(
    context: ReplayTaskRebuildStorage,
    address: int,
    *,
    calls: ReplayTaskRebuildCalls,
) -> None:
    """Full447B1414ec840 caller, including its captured outer/inner dimensions.

    Do not swap the captured width/height loops. Seed bounds and terrain use
    current context, while rows/columns retain their captured limits. The seed
    WORD is committed before the mandatory flood fill. Only effective R9B and
    stackWORD arguments are passed, without inventing unconsumed upper bits.
    """
    _validate(context, calls, address)
    dimensions = _read(context, address + 0x830, 8)
    width = _signed(_read(context, dimensions + 0x30, 4), 4)
    height = _signed(_read(context, dimensions + 0x34, 4), 4)
    count, saturated = 0, False
    for outer in range(max(0, width)):
        for inner in range(max(0, height)):
            row = _read(context, _read(context, address + 0x810, 8) + outer * 8, 8)
            _write(context, row + inner * 2, 2, 0x200)
    for y in range(max(0, width)):
        for x in range(max(0, height)):
            dimensions = _read(context, address + 0x830, 8)
            if y >= _signed(_read(context, dimensions + 0x34, 4), 4):
                continue
            current_width = _read(context, dimensions + 0x30, 4)
            if x >= _signed(current_width, 4):
                continue
            row = _read(context, _read(context, address + 0x810, 8) + y * 8, 8)
            if _read(context, row + x * 2, 2) != 0x200:
                continue
            if _signed(count, 4) >= 0x200:
                saturated = True
            terrain = _read(context, dimensions + 8, 8)
            zone = count if _signed(count, 4) < 0x200 else 0
            tile = 0
            if terrain:
                index = _signed(current_width * y & _U32, 4) + x
                tile = terrain + index * 64 & _U64
            kind = _read(context, tile + 9, 1)
            mask = _read(context, address + 0x818, 8)
            positive = compare_binary32(_read(context, mask + kind * 4, 4), 0) == 1
            _write(context, row + x * 2, 2, zone)
            _call(calls, 0x1414ECA00, (address, x, y, int(positive), zone & 0xFFFF))
            count = zone + 1 & _U32
    _write(context, address + 0x838, 4, 0x200 if saturated else count)


def bind_replay_zone_map_support(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    *,
    imports: ReplayTaskRebuildCalls | None = None,
) -> ReplayTaskRebuildCalls:
    """Bind five full callers and current memmove/free thunk effects."""
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
            0x14104EB10: 3,
            0x14096E250: 4,
            0x1414EA3E0: 4,
            0x1414EC140: 4,
            0x1414EC840: 1,
            0x142D6E3DB: 3,
            0x142D6BAB4: 2,
        }
        if target not in arities:
            return delegate(target, args, data)
        if len(args) != arities[target] or data is not None:
            raise ValueError("malformed zone support call")
        if target == 0x14104EB10:
            assign_replay_zone_mask(context, *args, calls=bound)
        elif target == 0x14096E250:
            return initialize_replay_zone_scratch(context, *args)
        elif target == 0x1414EA3E0:
            return move_replay_zone_pairs(context, *args, calls=bound)
        elif target == 0x1414EC140:
            commit_replay_zone_pairs(context, *args, calls=bound, imports=terminal)
        elif target == 0x1414EC840:
            refresh_replay_zone_map(context, *args, calls=bound)
        else:
            for value in args:
                _validate(context, calls, value)
            slot = 0x1431999A0 if target == 0x142D6E3DB else 0x143199DD0
            return delegate(_read(context, slot, 8), args, None, imported=True)
        return None

    bound = ReplayTaskRebuildCalls(dispatch)
    return bound
