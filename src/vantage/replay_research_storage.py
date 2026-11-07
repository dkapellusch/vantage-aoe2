"""Build54800 research header clear/reset/capacity callers (1415B/401 instructions).

Source: player-research-{storage-children,row-storage}-source-v1. All reached
allocation/import, row-transfer, vector destruction and DE-string effects are
mandatory. This does not construct the World DAT catalog or fake an I/O result.
Native stack/register aliases, fault/EH and concurrent-writer parity are excluded.
"""

from __future__ import annotations

from dataclasses import dataclass

from vantage.replay_task_group_storage import LocalBinding
from vantage.replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
    _call,
    _read,
    _write,
)
from vantage.replay_unit_ai_base import _validate
from vantage.replay_unit_ai_construction import _local

_U64 = (1 << 64) - 1
_CLEAR = 0x141491C50
_RESERVE = 0x1414938A0
_REVERSE = 0x141492AE0
_ROWS = 0x1414929F0
_WORDS = 0x140B55580
_MALLOC_SLOT = 0x143199DB0
_FREE_SLOT = 0x143199DD0
_ROW_STORES = (
    (0, 4, 0),
    (4, 2, 0),
    (6, 8, 0),
    (0x10, 8, 0x14428BB30),
    (0x18, 8, 0),
    (0x20, 8, 0),
    (0x28, 8, 0x14428BB30),
    (0x30, 8, 0),
    (0x38, 8, 0),
    (0x40, 8, 0x14428BB30),
    (0x48, 8, 0),
    (0x50, 8, 0),
    (0xE, 1, 0),
    (0x58, 1, 0),
    (0x5A, 4, 0),
    (0x5E, 2, 0),
    (0x60, 4, 0),
    (0x64, 2, 0),
    (0x66, 8, 0),
    (0x6E, 4, 0),
    (0x74, 4, 0),
    (0x78, 1, 0),
    (0x7A, 4, 0xFFFFFFFF),
    (0x80, 8, 0),
    (0x88, 8, 0),
    (0x90, 8, 0),
)


@dataclass(frozen=True, slots=True)
class ReplayResearchStorageScratch:
    """Explicit8B home of reserve's workingRSP+50 byte-count local.

    The entire home is written before allocation. Only the positive prefix
    transfer/destruction path reloads it; other paths retain the held product.
    Its live address is engine storage, not a native stack or incoming home.
    """

    reserve: bytes

    def __post_init__(self) -> None:
        if type(self.reserve) is not bytes or len(self.reserve) != 8:
            raise ValueError("explicit8B research reserve local seed required")


def _import(
    context: ReplayTaskRebuildStorage,
    imports: ReplayTaskRebuildCalls,
    slot: int,
    args: tuple[int, ...],
    *,
    width: int | None = None,
) -> int:
    return _call(imports, _read(context, slot, 8), args, width=width)


def _destroy_rows(
    context: ReplayTaskRebuildStorage,
    begin: int,
    count: int,
    calls: ReplayTaskRebuildCalls,
) -> None:
    cursor = (begin + 0x40) & _U64
    while count:
        _call(calls, 0x141493B50, ((cursor + 0x40) & _U64,))
        _call(calls, 0x140A1B220, (cursor,))
        _call(calls, 0x140A1B220, ((cursor - 0x18) & _U64,))
        _call(calls, 0x140A1B220, ((cursor - 0x30) & _U64,))
        cursor = (cursor + 0x98) & _U64
        count = (count - 1) & _U64


def _clear_dependency_headers(
    context: ReplayTaskRebuildStorage,
    begin: int,
    count: int,
    imports: ReplayTaskRebuildCalls,
) -> None:
    while count:
        pointer = _read(context, begin, 8)
        if pointer and _read(context, begin + 8, 8):
            _import(context, imports, _FREE_SLOT, (pointer,))
        _write(context, begin, 8, 0)
        begin = (begin + 32) & _U64
        count = (count - 1) & _U64


def clear_replay_research_rows(
    context: ReplayTaskRebuildStorage,
    header: int,
    *,
    calls: ReplayTaskRebuildCalls,
) -> None:
    """Full124B141491c50; own ABI is RCX only, with no RDX count input."""
    _validate(context, calls, header)
    count = _read(context, header + 16, 8)
    if count:
        begin = _read(context, header, 8)
        if begin:
            _destroy_rows(context, begin, count, calls)
        _write(context, header + 16, 8, 0)


def reset_replay_research_dependencies(
    context: ReplayTaskRebuildStorage,
    header: int,
    count: int,
    *,
    calls: ReplayTaskRebuildCalls,
    imports: ReplayTaskRebuildCalls,
) -> None:
    """Full413B141492ae0: clear old lists, reserve32B headers, reset requested rows."""
    _validate(context, calls, header, count)
    _validate(context, imports)
    old_count = _read(context, header + 16, 8)
    if old_count:
        begin = _read(context, header, 8)
        if begin:
            _clear_dependency_headers(context, begin, old_count, imports)
        _write(context, header + 16, 8, 0)
    if not count:
        return
    if _read(context, header + 8, 8) < count:
        size = count << 5 & _U64
        allocation = _import(context, imports, _MALLOC_SLOT, (size,), width=8)
        old_begin = _read(context, header, 8)
        if old_begin:
            free_pointer = old_begin
            current_count = _read(context, header + 16, 8)
            if current_count:
                copied = min(current_count, count)
                selected_begin = old_begin
                if copied and allocation:
                    copied_bytes = copied << 5 & _U64
                    _call(calls, 0x142D6E3B1, (allocation, old_begin, copied_bytes))
                    _call(calls, 0x142D6E3B7, (old_begin, 0, copied_bytes))
                    selected_begin = _read(context, header, 8)
                current_count = _read(context, header + 16, 8)
                free_pointer = selected_begin
                if count < current_count:
                    excess = (current_count - count) & _U64
                    cursor = (selected_begin + size) & _U64
                    if cursor and excess:
                        _clear_dependency_headers(context, cursor, excess, imports)
                        free_pointer = _read(context, header, 8)
                    _write(context, header + 16, 8, count)
            if free_pointer and _read(context, header + 8, 8):
                _import(context, imports, _FREE_SLOT, (free_pointer,))
        _write(context, header, 8, allocation)
        _write(context, header + 8, 8, count)
    begin = _read(context, header, 8)
    if begin:
        remaining = count
        while remaining:
            _write(context, begin, 8, 0)
            _write(context, begin + 8, 8, 0)
            _write(context, begin + 16, 8, 0)
            _write(context, begin + 24, 8, 32)
            begin = (begin + 32) & _U64
            remaining = (remaining - 1) & _U64
    _write(context, header + 16, 8, count)


def reset_replay_research_rows(
    context: ReplayTaskRebuildStorage,
    header: int,
    count: int,
    *,
    calls: ReplayTaskRebuildCalls,
) -> None:
    """Full234B1414929f0: real clear/reserve then26 ordered stores per0x98 row."""
    _validate(context, calls, header, count)
    _call(calls, _CLEAR, (header,))
    if not count:
        return
    if _read(context, header + 8, 8) < count:
        _call(calls, _RESERVE, (header, count))
    begin = _read(context, header, 8)
    if begin:
        remaining = count
        while remaining:
            for offset, width, value in _ROW_STORES:
                _write(context, begin + offset, width, value)
            begin = (begin + 0x98) & _U64
            remaining = (remaining - 1) & _U64
    _write(context, header + 16, 8, count)


def reserve_replay_research_dependency_words(
    context: ReplayTaskRebuildStorage,
    header: int,
    capacity: int,
    *,
    calls: ReplayTaskRebuildCalls,
    imports: ReplayTaskRebuildCalls,
) -> None:
    """Full211B140b55580; current copy/free fields and held pre-copy size clip."""
    _validate(context, calls, header, capacity)
    _validate(context, imports)
    previous_capacity = _read(context, header + 8, 8)
    if capacity == previous_capacity:
        return
    if not capacity:
        pointer = _read(context, header, 8)
        if pointer and previous_capacity:
            _import(context, imports, _FREE_SLOT, (pointer,))
        _write(context, header, 8, 0)
        _write(context, header + 16, 8, 0)
        _write(context, header + 8, 8, 0)
        return
    allocation = _import(context, imports, _MALLOC_SLOT, (capacity << 2 & _U64,), width=8)
    if _read(context, header, 8):
        old_count = _read(context, header + 16, 8)
        if old_count:
            copied = min(old_count, capacity)
            if copied and allocation:
                source = _read(context, header, 8)
                _call(calls, 0x142D6E3B1, (allocation, source, copied << 2 & _U64))
            if capacity < old_count:
                _write(context, header + 16, 8, capacity)
        if _read(context, header + 8, 8):
            _import(context, imports, _FREE_SLOT, (_read(context, header, 8),))
    _write(context, header, 8, allocation)
    _write(context, header + 8, 8, capacity)


def reserve_replay_research_rows(
    context: ReplayTaskRebuildStorage,
    header: int,
    capacity: int,
    *,
    calls: ReplayTaskRebuildCalls,
    imports: ReplayTaskRebuildCalls,
    bind_local: LocalBinding,
    scratch: ReplayResearchStorageScratch,
) -> None:
    """Full433B1414938a0; mandatory row transfer/destruction, current8B local.

    The zero branch frees its held old pointer, the positive branch reads its
    free pointer late. Prefix transfer is actual1414904c0, never raw memcpy.
    No rollback or successful unprovided cleanup is introduced on exceptions.
    """
    _validate(context, calls, header, capacity)
    _validate(context, imports)
    if not callable(bind_local) or not isinstance(scratch, ReplayResearchStorageScratch):
        raise ValueError("actual local binding and research storage scratch required")
    previous_capacity = _read(context, header + 8, 8)
    if capacity == previous_capacity:
        return
    if not capacity:
        count = _read(context, header + 16, 8)
        begin = _read(context, header, 8)
        if begin and previous_capacity:
            if count:
                _destroy_rows(context, begin, count, calls)
            _import(context, imports, _FREE_SLOT, (begin,))
        _write(context, header, 8, 0)
        _write(context, header + 16, 8, 0)
        _write(context, header + 8, 8, 0)
        return
    byte_count = capacity * 0x98 & _U64
    with _local(memoryview(bytearray(scratch.reserve)), bind_local) as saved_size:
        _write(context, saved_size, 8, byte_count)
        allocation = _import(context, imports, _MALLOC_SLOT, (byte_count,), width=8)
        old_begin = _read(context, header, 8)
        if old_begin:
            old_count = _read(context, header + 16, 8)
            if old_count:
                copied = min(old_count, capacity)
                selected_begin, selected_bytes = old_begin, byte_count
                if copied and allocation:
                    cursor, remaining = allocation, copied
                    offset = (old_begin - allocation) & _U64
                    while remaining:
                        _call(calls, 0x1414904C0, (cursor, (offset + cursor) & _U64))
                        cursor = (cursor + 0x98) & _U64
                        remaining = (remaining - 1) & _U64
                    _destroy_rows(context, old_begin, copied, calls)
                    selected_begin = _read(context, header, 8)
                    selected_bytes = _read(context, saved_size, 8)
                current_count = _read(context, header + 16, 8)
                if capacity < current_count:
                    _call(
                        calls,
                        0x141493840,
                        (
                            header,
                            (selected_begin + selected_bytes) & _U64,
                            (current_count - capacity) & _U64,
                        ),
                    )
                    _write(context, header + 16, 8, capacity)
            pointer = _read(context, header, 8)
            if pointer and _read(context, header + 8, 8):
                _import(context, imports, _FREE_SLOT, (pointer,))
        _write(context, header, 8, allocation)
        _write(context, header + 8, 8, capacity)


def bind_replay_research_storage(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    *,
    imports: ReplayTaskRebuildCalls,
    bind_local: LocalBinding,
    scratch: ReplayResearchStorageScratch,
) -> ReplayTaskRebuildCalls:
    """Own exactly five callers; selected current imports bypass ordinary aliases."""
    _validate(context, calls)
    _validate(context, imports)
    if not callable(bind_local) or not isinstance(scratch, ReplayResearchStorageScratch):
        raise ValueError("actual local binding and research storage scratch required")

    def dispatch(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        arities = {_CLEAR: 1, _REVERSE: 2, _ROWS: 2, _WORDS: 2, _RESERVE: 2}
        if target not in arities:
            if calls.call is None:
                raise UnresolvedReplayTaskRebuild(f"reached{target:x} is unavailable")
            return calls.call(target, args, data)
        if len(args) != arities[target] or data is not None:
            raise ValueError("malformed research storage call")
        _validate(context, calls, *args)
        if target == _CLEAR:
            clear_replay_research_rows(context, *args, calls=bound)
        elif target == _REVERSE:
            reset_replay_research_dependencies(context, *args, calls=bound, imports=imports)
        elif target == _ROWS:
            reset_replay_research_rows(context, *args, calls=bound)
        elif target == _WORDS:
            reserve_replay_research_dependency_words(context, *args, calls=bound, imports=imports)
        else:
            reserve_replay_research_rows(
                context, *args, calls=bound, imports=imports, bind_local=bind_local, scratch=scratch
            )
        return None

    bound = ReplayTaskRebuildCalls(dispatch)
    return bound
