"""Build54800 complete normal history constructor and four DWORD-vector helpers.

Source: player-derived-history-source-v1 and its children-source-v1. The large
141634b00 stream reader remains a real mandatory child, never an empty/success
replacement. Coherent explicit90B locals preserve current scalar/full-QWORD
staging and distinct returned/fixed Results. Masked MXCSR1f80, DAZ/FTZ off;
FPstatus/traps, physical stack/register homes, native fault/EH/concurrency and
complete Player/World restoration are excluded. Reached children must be real.
"""

from __future__ import annotations

from dataclasses import dataclass

from .replay_base_saved_registration import _cvtt32
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
from .replay_unit_ai_map import ReplayUnitAIMapAtomics, _release

_U64 = (1 << 64) - 1
_MAX = (1 << 62) - 1


@dataclass(frozen=True, slots=True)
class ReplayPlayerHistoryScratch:
    """Explicit90B logical data frame, RBP=frame50; scalar88, Result20.

    Scalar high4 incoming bytes remain live through both vector calls; only
    lowDWORD is cleared. The source's incoming history-home store maps80.
    FixedResult20 is NOT initialized by this constructor. Native save-register
    values/physical aliases are excluded; all unwritten logical bytes retain
    these explicit seeds, and both published regions remain live until return.
    """

    frame: bytes

    def __post_init__(self) -> None:
        if type(self.frame) is not bytes or len(self.frame) != 0x90:
            raise ValueError("explicit90-byte history logical frame required")


def _count(end: int, begin: int) -> int:
    return (_signed((end - begin) & _U64, 8) >> 2) & _U64


def _growth(capacity: int, requested: int) -> int:
    half = capacity >> 1
    return _MAX if capacity > _MAX - half else max(capacity + half, requested)


def _error(calls: ReplayTaskRebuildCalls, target: int) -> None:
    _call(calls, target, ())
    raise UnresolvedReplayTaskRebuild(f"nonreturning history error{target:x} returned before INT3")


def _watson(context: ReplayTaskRebuildStorage, imports: ReplayTaskRebuildCalls) -> None:
    target = _read(context, 0x14319A060, 8)
    _call(imports, target, (0, 0, 0, 0, 0))
    raise UnresolvedReplayTaskRebuild("nonreturning history Watson returned before INT3")


def fill_replay_history_words(
    context: ReplayTaskRebuildStorage,
    begin: int,
    end: int,
    source: int,
    *,
    calls: ReplayTaskRebuildCalls,
) -> None:
    """Whole164B14162ccc0 memory/call projection, direct zero-extended bulk word.

    Ordered nonwrapping wholeDWORD ranges are the explicit logical profile.
    Malformed reverse/unaligned/wrapping native loops refuse before effects.
    Empty ranges still read current source and zero-source tailcalls memset0.
    Nonaliasing bulk holds its second source read; alias/scalar tail rereads.
    Incidental volatile-register/return bits are not an effective return value.
    """
    _validate(context, calls, begin, end, source)
    if end < begin or (end - begin) & 3:
        raise ValueError("history fill requires ordered wholeDWORD range")
    if _read(context, source, 4) == 0:
        _call(calls, 0x142D6E3B7, (begin, 0, (end - begin) & (_U64 - 3)))
        return
    count = ((end - begin + 3) & _U64) >> 2
    if count >= 4:
        word = _read(context, source, 4)
        last = (begin - 4 + count * 4) & _U64
        if begin > source or last < source:
            for _ in range(count & ~3):
                _write(context, begin, 4, word)
                begin = (begin + 4) & _U64
    while begin != end:
        word = _read(context, source, 4)
        _write(context, begin, 4, word)
        begin = (begin + 4) & _U64


def release_replay_history_words(
    context: ReplayTaskRebuildStorage,
    ignored_header: int,
    begin: int,
    capacity: int,
    *,
    calls: ReplayTaskRebuildCalls,
    imports: ReplayTaskRebuildCalls | None = None,
) -> None:
    """Whole85B1402bbc40: raw capacity*4, current large header and terminal Watson.

    RCX is ignored. No null skip or header reset is added. Current free remains
    an actual direct target; its genuine thunk/import implementation is supplied
    by the composed calls provider. Current Watson-selected aliases go terminal.
    """
    _validate(context, calls, ignored_header, begin, capacity)
    terminal = calls if imports is None else imports
    _validate(context, terminal)
    size = capacity * 4 & _U64
    pointer = begin
    if size >= 0x1000:
        pointer = _read(context, begin - 8, 8)
        size = (size + 0x27) & _U64
        if (begin - pointer - 8) & _U64 > 31:
            _watson(context, terminal)
    _call(calls, 0x142D6BAB4, (pointer, size))


def assign_replay_history_words(
    context: ReplayTaskRebuildStorage,
    header: int,
    requested: int,
    source: int,
    *,
    calls: ReplayTaskRebuildCalls,
) -> None:
    """Whole420B1416347f0: all elements assigned, current source/read/release order."""
    _validate(context, calls, header, requested, source)
    begin = _read(context, header, 8)
    capacity = _count(_read(context, header + 16, 8), begin)
    if requested > capacity:
        if requested > _MAX:
            _error(calls, 0x1402BA820)
        growth = _growth(capacity, requested)
        if begin:
            _call(calls, 0x1402BBC40, (header, begin, capacity))
            for offset in (0, 8, 16):
                _write(context, header + offset, 8, 0)
        if growth > _MAX:
            _error(calls, 0x1402A9460)
        allocated = _call(calls, 0x1402A94D0, (growth * 4 & _U64,), width=8)
        _write(context, header, 8, allocated)
        _write(context, header + 8, 8, allocated)
        _write(context, header + 16, 8, allocated + growth * 4)
        cursor = allocated
        if _read(context, source, 4) == 0:
            size = requested * 4 & _U64
            _call(calls, 0x142D6E3B7, (allocated, 0, size))
            cursor = (cursor + size) & _U64
        else:
            remaining = requested
            while remaining:
                _write(context, cursor, 4, _read(context, source, 4))
                cursor = (cursor + 4) & _U64
                remaining -= 1
        _write(context, header + 8, 8, cursor)
        return
    end = _read(context, header + 8, 8)
    old_size = _count(end, begin)
    if requested > old_size:
        _call(calls, 0x14162CCC0, (begin, end, source))
        remaining = (requested - old_size) & _U64
        cursor = _read(context, header + 8, 8)
        if _read(context, source, 4) == 0:
            size = remaining * 4 & _U64
            _call(calls, 0x142D6E3B7, (cursor, 0, size))
            cursor = (cursor + size) & _U64
        else:
            while remaining:
                _write(context, cursor, 4, _read(context, source, 4))
                cursor = (cursor + 4) & _U64
                remaining -= 1
    else:
        cursor = (begin + requested * 4) & _U64
        _call(calls, 0x14162CCC0, (begin, cursor, source))
    _write(context, header + 8, 8, cursor)


def resize_replay_history_words(
    context: ReplayTaskRebuildStorage,
    header: int,
    requested: int,
    ignored_source: int,
    *,
    calls: ReplayTaskRebuildCalls,
    imports: ReplayTaskRebuildCalls | None = None,
) -> None:
    """Whole391B14162cb30 resize, preserving old words with actual current memmove.

    Incoming R8 is not consumed; no source or Input access is inferred. Initial
    oldend/size remain held through allocation/memset; copy/free headers reload
    at their exact phases. Commit follows free, and all prior effects survive
    a missing provider or nonreturning error. No native vector identity inferred.
    """
    _validate(context, calls, header, requested, ignored_source)
    terminal = calls if imports is None else imports
    _validate(context, terminal)
    old_end = _read(context, header + 8, 8)
    begin = _read(context, header, 8)
    old_size = _count(old_end, begin)
    if requested < old_size:
        _write(context, header + 8, 8, begin + requested * 4)
        return
    if requested == old_size:
        return
    capacity = _count(_read(context, header + 16, 8), begin)
    if requested <= capacity:
        size = (requested - old_size) * 4 & _U64
        _call(calls, 0x142D6E3B7, (old_end, 0, size))
        _write(context, header + 8, 8, old_end + size)
        return
    if requested > _MAX:
        _error(calls, 0x1402BA820)
    growth = _growth(capacity, requested)
    if growth > _MAX:
        _error(calls, 0x1402A9460)
    byte_capacity = growth * 4 & _U64
    replacement = _call(calls, 0x1402A94D0, (byte_capacity,), width=8)
    tail = (replacement + old_size * 4) & _U64
    _call(calls, 0x142D6E3B7, (tail, 0, (requested - old_size) * 4 & _U64))
    copy_begin = _read(context, header, 8)
    copy_end = _read(context, header + 8, 8)
    _call(calls, 0x142D6E3DB, (replacement, copy_begin, (copy_end - copy_begin) & _U64))
    current_begin = _read(context, header, 8)
    if current_begin:
        size = (_read(context, header + 16, 8) - current_begin) & (_U64 - 3)
        pointer = current_begin
        if size >= 0x1000:
            pointer = _read(context, current_begin - 8, 8)
            size = (size + 0x27) & _U64
            if (current_begin - pointer - 8) & _U64 > 31:
                _watson(context, terminal)
        _call(calls, 0x142D6BAB4, (pointer, size))
    _write(context, header, 8, replacement)
    _write(context, header + 8, 8, replacement + requested * 4)
    _write(context, header + 16, 8, replacement + byte_capacity)


def construct_replay_player_history(
    context: ReplayTaskRebuildStorage,
    address: int,
    player: int,
    output: int,
    stream: int,
    *,
    calls: ReplayTaskRebuildCalls,
    atomics: ReplayUnitAIMapAtomics,
    bind_local: LocalBinding,
    scratch: ReplayPlayerHistoryScratch,
) -> int:
    """Whole normal1053B14162d370; actual large stream child remains mandatory."""
    _validate(context, calls, address, player, output, stream)
    if not isinstance(atomics, ReplayUnitAIMapAtomics) or not callable(bind_local):
        raise ValueError("actual history atomics/local binding required")
    if not isinstance(scratch, ReplayPlayerHistoryScratch):
        raise ValueError("explicit history scratch required")
    with _local(memoryview(bytearray(scratch.frame)), bind_local) as frame:
        _write(context, frame + 0x80, 8, address)
        for offset, width in (
            (0, 8),
            (8, 8),
            (0x18, 8),
            (0x20, 4),
            (0x28, 8),
            (0x30, 8),
            (0x38, 8),
            (0x40, 8),
            (0x48, 8),
            (0x50, 4),
            (0x5C, 8),
            (0x64, 8),
            (0xB0, 8),
            (0xB8, 8),
            (0xC0, 8),
            (0xC8, 8),
            (0xD0, 8),
            (0xD8, 8),
            (0xE0, 8),
            (0xE8, 8),
            (0xF0, 4),
        ):
            _write(context, address + offset, width, 0)
        _write(context, address + 0x10, 8, player)
        _write(context, address + 0x24, 4, 9)
        scalar = frame + 0x88
        _write(context, scalar, 4, 0)
        _call(calls, 0x1416347F0, ((address + 0xB0) & _U64, 9, scalar))
        _write(context, scalar, 4, 0)
        count = _signed(_read(context, address + 0x24, 4), 4) & _U64
        _call(calls, 0x1416347F0, ((address + 0xC8) & _U64, count, scalar))
        for offset, destination in (
            (0xA0, 0x3C),
            (0x550, 0x40),
            (0x158, 0x2C),
            (0x560, 0x30),
            (0x4D0, 0x44),
            (0x4C0, 0x48),
            (0x4D8, 0x34),
            (0x4C8, 0x38),
        ):
            owner = _read(context, address + 0x10, 8)
            table = _read(context, owner + 0x98, 8)
            _write(context, scalar, 8, _read(context, table + offset, 8))
            for operation, constant in (
                ("xor", 0x6AE24D3352F04511),
                ("xor", 0xC22D6B496D833977),
                ("sub", 0x042AC42976FCCEF5),
                ("xor", 0xA9834B738A7DD167),
            ):
                current = _read(context, scalar, 8)
                _write(
                    context,
                    scalar,
                    8,
                    current ^ constant if operation == "xor" else current - constant,
                )
            _write(context, scalar, 8, _read(context, scalar, 8))
            _write(context, address + destination, 4, _cvtt32(_read(context, scalar, 4)))
        if stream:
            result = _call(calls, 0x141634B00, (address, frame + 0x20, stream), width=8)
            _write(context, result + 0x28, 1, 1)
            _call(calls, 0x14090D270, ((output + 0x18) & _U64, (result + 0x18) & _U64))
            if output != result:
                begin = _read(context, result, 8)
                end = _read(context, result + 8, 8)
                count = (_signed((end - begin) & _U64, 8) >> 5) & _U64
                _call(calls, 0x1402B9080, (output, begin, count))
            _write(context, output + 0x28, 1, 0)
            control = _read(context, frame + 0x40, 8)
            if control:
                _release(context, control, calls, atomics)
            _call(calls, 0x1402BD890, (frame + 0x20,))
        return address


def bind_replay_player_history(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    *,
    atomics: ReplayUnitAIMapAtomics,
    bind_local: LocalBinding,
    scratch: ReplayPlayerHistoryScratch,
    imports: ReplayTaskRebuildCalls | None = None,
) -> ReplayTaskRebuildCalls:
    """Bind all five complete bodies; actual large reader and CRT children delegate."""
    _validate(context, calls)
    terminal = calls if imports is None else imports
    _validate(context, terminal)
    if not isinstance(atomics, ReplayUnitAIMapAtomics) or not callable(bind_local):
        raise ValueError("actual history atomics/local binding required")
    if not isinstance(scratch, ReplayPlayerHistoryScratch):
        raise ValueError("explicit history scratch required")

    def dispatch(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        arities = {0x14162D370: 4, 0x1416347F0: 3, 0x14162CCC0: 3, 0x1402BBC40: 3, 0x14162CB30: 3}
        if target not in arities:
            if calls.call is None:
                raise UnresolvedReplayTaskRebuild(f"reached{target:x} is unavailable")
            return calls.call(target, args, data)
        if len(args) != arities[target] or data is not None:
            raise ValueError("malformed history call")
        _validate(context, calls, *args)
        if target == 0x14162D370:
            return construct_replay_player_history(
                context, *args, calls=bound, atomics=atomics, bind_local=bind_local, scratch=scratch
            )
        if target == 0x1416347F0:
            assign_replay_history_words(context, *args, calls=bound)
        elif target == 0x14162CCC0:
            fill_replay_history_words(context, *args, calls=bound)
        elif target == 0x1402BBC40:
            release_replay_history_words(context, *args, calls=bound, imports=terminal)
        else:
            resize_replay_history_words(context, *args, calls=bound, imports=terminal)
        return None

    bound = ReplayTaskRebuildCalls(dispatch)
    return bound
