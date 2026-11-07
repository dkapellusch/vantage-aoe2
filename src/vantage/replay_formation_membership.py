"""Complete group reserve/removal and auxiliary node append caller bodies.

Source: world-formation-transfer-descendants-source-v1. Current backing, actual
allocation/free, Game/lookup/admission/FP/AI/list children stay mandatory.
Reserve's live A0h prefix preserves saved request and unrolled offset aliases.
Physical saves, native faults/EH/concurrency and unread incidental ABI are excluded.
"""

from __future__ import annotations

from dataclasses import dataclass

from .replay_binary32 import add_binary32, compare_binary32
from .replay_task_group_storage import LocalBinding
from .replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
    _read,
    _signed,
    _unsigned,
    _write,
)
from .replay_unit_ai_base import _validate
from .replay_unit_ai_construction import _local

_U32, _U64 = (1 << 32) - 1, (1 << 64) - 1
_RESERVE, _REMOVE, _APPEND = 0x1410F7C20, 0x1410F6800, 0x1410D43A0
_ALLOC, _FREE = 0x142D6C268, 0x142D6C270
_GET_WORLD, _LOOKUP, _EXTENT = 0x140D6ACC0, 0x141617DB0, 0x1410EEF50


@dataclass(frozen=True, slots=True)
class ReplayFormationMembershipProfile:
    """Explicit coherent A0h logical prefix for complete1410f7c20.

    Entry spill88 is DWORD;20/28/30/90/98 are source-used QWORD homes. The
    highest homes exceed nativeSUB40 because incoming homes are also live.
    Unwritten bytes retain seed; physical spills/return slots are excluded.
    """

    reserve: bytes

    def __post_init__(self) -> None:
        if type(self.reserve) is not bytes or len(self.reserve) != 0xA0:
            raise ValueError("explicitA0-hex-byte membership reserve seed required")


def _invoke(
    calls: ReplayTaskRebuildCalls,
    target: int,
    args: tuple[int, ...],
) -> int | None:
    if calls.call is None:
        raise UnresolvedReplayTaskRebuild(f"reached{target:x} is unavailable")
    return calls.call(target, tuple(value & _U64 for value in args), None)


def _rax(calls: ReplayTaskRebuildCalls, target: int, args: tuple[int, ...]) -> int:
    result = _invoke(calls, target, args)
    if result is None:
        raise ValueError(f"helper{target:x} must supply raw RAX at consumer")
    _unsigned(result, 8, f"helper{target:x} raw RAX")
    return result


def _eax(calls: ReplayTaskRebuildCalls, target: int, args: tuple[int, ...]) -> int:
    return _rax(calls, target, args) & _U32


def _record(context: ReplayTaskRebuildStorage, address: int) -> None:
    _write(context, address, 4, 0)
    _write(context, address + 4, 8, _U64)
    _write(context, address + 0xC, 8, 0)
    _write(context, address + 0x14, 8, 0)
    _write(context, address + 0x1C, 8, 0)
    _write(context, address + 0x24, 8, 0)
    _write(context, address + 0x2C, 4, 0)


def _copy_record(context: ReplayTaskRebuildStorage, source: int, destination: int) -> None:
    for offset in (0, 0x10, 0x20):
        _write(context, destination + offset, 16, _read(context, source + offset, 16))


def _copy_existing(
    context: ReplayTaskRebuildStorage,
    group: int,
    frame: int,
    requested: int,
    identifiers: int,
    records: int,
    auxiliary: int,
) -> int:
    """Literal four-way copy then scalar tail; return held copied R9D.

    Row count gates, three16B pairs, lane offsets and live HOME reloads follow
    the original instruction order. No range snapshot or bulk copy is used.
    """
    copied, index = 0, 0
    if requested >= 4:
        row_cursor = (records + 0x60) & _U64
        aux_cursor = (auxiliary + 4) & _U64
        id_delta = (identifiers - auxiliary) & _U64
        _write(context, frame + 0x90, 8, 4 - auxiliary)
        _write(context, frame + 0x98, 8, 8 - auxiliary)
        offset = (-4 - auxiliary) & _U64
        _write(context, frame + 0x28, 8, offset)
        _write(context, frame + 0x20, 8, 0x30 - records)
        record_offset = (-0x60 - records) & _U64
        _write(context, frame + 0x30, 8, record_offset)
        while True:
            if _signed(copied, 4) >= _signed(_read(context, group + 0xE4, 4), 4):
                return copied
            first_offset = (offset + aux_cursor) & _U64
            old_ids = _read(context, group + 0xF0, 8)
            value = _read(context, old_ids + first_offset, 4)
            _write(context, aux_cursor + id_delta - 4, 4, value)
            record_offset = (record_offset + row_cursor) & _U64
            old_records = _read(context, group + 0xF8, 8)
            _copy_record(context, old_records + record_offset, row_cursor - 0x60)
            old_aux = _read(context, group + 0x490, 8)
            _write(context, aux_cursor - 4, 4, _read(context, old_aux + first_offset, 4))
            copied = (copied + 1) & _U32
            if _signed(copied, 4) >= _signed(_read(context, group + 0xE4, 4), 4):
                return copied
            old_ids = _read(context, group + 0xF0, 8)
            value = _read(context, old_ids + first_offset + 4, 4)
            _write(context, aux_cursor + id_delta, 4, value)
            old_records = _read(context, group + 0xF8, 8)
            _copy_record(context, old_records + record_offset + 0x30, row_cursor - 0x30)
            old_aux = _read(context, group + 0x490, 8)
            _write(context, aux_cursor, 4, _read(context, old_aux + first_offset + 4, 4))
            copied = (copied + 1) & _U32
            if _signed(copied, 4) >= _signed(_read(context, group + 0xE4, 4), 4):
                return copied
            record_offset = _read(context, frame + 0x90, 8)
            record_offset = (record_offset + aux_cursor) & _U64
            old_ids = _read(context, group + 0xF0, 8)
            value = _read(context, old_ids + record_offset, 4)
            _write(context, aux_cursor + id_delta + 4, 4, value)
            old_records = _read(context, group + 0xF8, 8)
            old_records = (old_records - records) & _U64
            _copy_record(context, old_records + row_cursor, row_cursor)
            old_aux = _read(context, group + 0x490, 8)
            _write(context, aux_cursor + 4, 4, _read(context, old_aux + record_offset, 4))
            copied = (copied + 1) & _U32
            if _signed(copied, 4) >= _signed(_read(context, group + 0xE4, 4), 4):
                return copied
            record_offset = _read(context, frame + 0x98, 8)
            record_offset = (record_offset + aux_cursor) & _U64
            old_ids = _read(context, group + 0xF0, 8)
            value = _read(context, old_ids + record_offset, 4)
            _write(context, aux_cursor + id_delta + 8, 4, value)
            old_records = _read(context, group + 0xF8, 8)
            old_records = (old_records + row_cursor) & _U64
            offset = _read(context, frame + 0x20, 8)
            _copy_record(context, old_records + offset, row_cursor + 0x30)
            old_aux = _read(context, group + 0x490, 8)
            _write(context, aux_cursor + 8, 4, _read(context, old_aux + record_offset, 4))
            copied = (copied + 1) & _U32
            index = (index + 4) & _U64
            row_cursor = (row_cursor + 0xC0) & _U64
            aux_cursor = (aux_cursor + 0x10) & _U64
            repeat = _signed(index, 8) < requested - 3
            offset = _read(context, frame + 0x28, 8)
            record_offset = _read(context, frame + 0x30, 8)
            if not repeat:
                break
    if _signed(index, 8) >= requested:
        return copied
    row_offset = (index * 3 << 4) & _U64
    id_delta = (identifiers - auxiliary) & _U64
    while True:
        if _signed(copied, 4) >= _signed(_read(context, group + 0xE4, 4), 4):
            return copied
        aux_slot = (auxiliary + index * 4) & _U64
        old_ids = _read(context, group + 0xF0, 8)
        value = _read(context, old_ids + index * 4, 4)
        _write(context, id_delta + aux_slot, 4, value)
        old_records = _read(context, group + 0xF8, 8)
        _copy_record(context, old_records + row_offset, row_offset + records)
        old_aux = _read(context, group + 0x490, 8)
        _write(context, aux_slot, 4, _read(context, old_aux + index * 4, 4))
        copied = (copied + 1) & _U32
        index = (index + 1) & _U64
        row_offset = (row_offset + 0x30) & _U64
        if _signed(index, 8) >= requested:
            return copied


def _defaults(
    context: ReplayTaskRebuildStorage,
    first: int,
    requested: int,
    identifiers: int,
    records: int,
    auxiliary: int,
) -> None:
    index = _signed(first, 4)
    if index >= requested:
        return
    aux_slot = (auxiliary + index * 4) & _U64
    row = (records + index * 0x30) & _U64
    delta = (identifiers - auxiliary) & _U64
    while True:
        _write(context, aux_slot + delta, 4, _U32)
        _record(context, row)
        _write(context, aux_slot, 4, 0x7F7FFFFF)
        index = _signed((index + 1) & _U64, 8)
        row = (row + 0x30) & _U64
        aux_slot = (aux_slot + 4) & _U64
        if index >= requested:
            return


def _reserve(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    group: int,
    requested_word: int,
    frame: int,
) -> int:
    _write(context, frame + 0x88, 4, requested_word)
    requested = _signed(requested_word, 4)
    if requested <= 0:
        return 0
    if _signed(_read(context, group + 0xE8, 4), 4) >= requested:
        return 0
    identifiers = _rax(calls, _ALLOC, (min(requested * 4, _U64),))
    if not identifiers:
        return 0
    _write(context, frame + 0x90, 8, requested)
    records = _rax(calls, _ALLOC, (min(requested * 0x30, _U64),))
    _write(context, frame + 0x90, 8, records)
    if not records:
        _invoke(calls, _FREE, (identifiers,))
        return 0
    remaining, cursor = requested, records
    while remaining:
        _record(context, cursor)
        cursor = (cursor + 0x30) & _U64
        remaining -= 1
    auxiliary = _rax(calls, _ALLOC, (min(requested * 4, _U64),))
    if not auxiliary:
        _invoke(calls, _FREE, (identifiers,))
        _invoke(calls, _FREE, (records,))
        return 0
    if _read(context, group + 0xF0, 8):
        copied = _copy_existing(context, group, frame, requested, identifiers, records, auxiliary)
        _defaults(context, copied, requested, identifiers, records, auxiliary)
        for field in (0xF0, 0xF8, 0x490):
            previous = _read(context, group + field, 8)
            if previous:
                _invoke(calls, _FREE, (previous,))
                if field != 0x490:
                    _write(context, group + field, 8, 0)
    else:
        _defaults(context, 0, requested, identifiers, records, auxiliary)
    _write(context, group + 0xF0, 8, identifiers)
    _write(context, group + 0xF8, 8, records)
    _write(context, group + 0x490, 8, auxiliary)
    _write(context, group + 0xE8, 4, _read(context, frame + 0x88, 4))
    return 1


def _remove(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    group: int,
    identifier: int,
    reference: int,
    quiet: int,
) -> int:
    count = _read(context, group + 0xE4, 4)
    if _signed(count, 4) <= 0:
        return 0
    index = 0
    cursor = _read(context, group + 0xF0, 8)
    while _read(context, cursor, 4) != identifier:
        index = (index + 1) & _U32
        cursor = (cursor + 4) & _U64
        if _signed(index, 4) >= _signed(count, 4):
            return 0
    world = _rax(calls, _GET_WORLD, (_read(context, 0x144353698, 8),))
    unit = _rax(calls, _LOOKUP, (world, identifier))
    if unit:
        group_id = _read(context, group + 0xD8, 4)
        if _read(context, unit + 0x210, 4) == group_id:
            if not quiet:
                vptr = _read(context, unit, 8)
                target = _read(context, vptr + 0x5A8, 8)
                _invoke(calls, target, (unit,))
            _write(context, unit + 0x210, 4, _U32)
    count = _read(context, group + 0xE4, 4)
    if _signed(index, 4) < _signed((count - 1) & _U32, 4):
        row_offset = (index * 3 << 4) & _U64
        id_offset = (index * 4) & _U64
        while True:
            begin = _read(context, group + 0xF0, 8)
            id_offset = (id_offset + 4) & _U64
            index = (index + 1) & _U32
            row_offset = (row_offset + 0x30) & _U64
            _write(context, begin + id_offset - 4, 4, _read(context, begin + id_offset, 4))
            begin = _read(context, group + 0xF8, 8)
            _copy_record(context, begin + row_offset, begin + row_offset - 0x30)
            count = _read(context, group + 0xE4, 4)
            if _signed(index, 4) >= _signed((count - 1) & _U32, 4):
                break
    begin = _read(context, group + 0xF0, 8)
    _write(context, begin + _signed(count, 4) * 4 - 4, 4, _U32)
    last_count = _signed(_read(context, group + 0xE4, 4), 4)
    begin = _read(context, group + 0xF8, 8)
    _record(context, begin + last_count * 0x30 - 0x30)
    _write(context, group + 0xE4, 4, _read(context, group + 0xE4, 4) - 1)
    _invoke(calls, 0x1410F6A50, (group + 0x1D0, group, identifier, reference))
    if _read(context, group + 0xC4, 4) == identifier:
        _invoke(calls, 0x1410DC6B0, (group,))
    _write(context, group + 0x140, 4, _read(context, group + 0x140, 4) | 0x10002)
    return 1


def _append(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    node: int,
    identifier: int,
) -> int:
    world = _rax(calls, _GET_WORLD, (_read(context, 0x144353698, 8),))
    unit = _rax(calls, _LOOKUP, (world, identifier))
    if not unit:
        return 0
    capacity = _read(context, node + 0x18, 4)
    count = _read(context, node + 0x14, 4)
    if _signed(count, 4) >= _signed(capacity, 4) or not capacity:
        if not capacity and not _eax(calls, 0x1410F78E0, (node, 10)):
            return 0
        capacity = _read(context, node + 0x18, 4)
        if not _eax(calls, 0x1410F78E0, (node, capacity * 2 & _U32)):
            return 0
    word = _invoke(calls, _EXTENT, (unit,))
    if word is None:
        raise ValueError("extent must supply owned raw XMM0 DWORD")
    _unsigned(word, 4, "owned raw XMM0 extent")
    doubled = add_binary32(word, word)
    if compare_binary32(doubled, _read(context, node + 0x30, 4)) == 1:
        _write(context, node + 0x30, 4, doubled)
    index = _signed(_read(context, node + 0x14, 4), 4)
    begin = _read(context, node + 0x20, 8)
    _write(context, begin + index * 4, 4, identifier)
    _write(context, node + 0x14, 4, _read(context, node + 0x14, 4) + 1)
    _invoke(calls, 0x1410D9990, (node,))
    return 1


def bind_replay_formation_membership(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    *,
    bind_local: LocalBinding,
    profile: ReplayFormationMembershipProfile,
    mxcsr: int,
) -> ReplayTaskRebuildCalls:
    """Bind3 complete source callers over explicit storage/capabilities.

    Valid finite backing and list progress are premises, with no arbitrary
    dynamic cap or successful fallback. Ignored children retain opaque returns;
    consumed RAX is checked only at the actual scalar consumer. Reserve's entry
    DWORD spill is reached even on its failing size/capacity gates.
    """
    _validate(context, calls)
    if not callable(bind_local) or not isinstance(profile, ReplayFormationMembershipProfile):
        raise ValueError("explicit membership profile and local binding required")
    if type(mxcsr) is not int or mxcsr != 0x1F80:
        raise ValueError("exact masked MXCSR1f80 profile required")
    arities = {_RESERVE: 2, _REMOVE: 4, _APPEND: 2}

    def dispatch(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        if target not in arities:
            if calls.call is None:
                raise UnresolvedReplayTaskRebuild(f"reached{target:x} is unavailable")
            return calls.call(target, args, data)
        if len(args) != arities[target] or data is not None:
            raise ValueError("malformed formation membership call")
        _validate(context, calls, *args)
        if target == _RESERVE:
            with _local(memoryview(bytearray(profile.reserve)), bind_local) as frame:
                return _reserve(context, bound, args[0], args[1] & _U32, frame)
        if target == _REMOVE:
            return _remove(context, bound, args[0], args[1] & _U32, args[2] & _U32, args[3] & 255)
        return _append(context, bound, args[0], args[1] & _U32)

    bound = ReplayTaskRebuildCalls(dispatch)
    return bound
