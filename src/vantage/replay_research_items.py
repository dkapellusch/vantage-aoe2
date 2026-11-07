"""Build54800 modern research item append and16-byte POD-vector storage.

Source: player-research-items-source-v1,689listed/690physical bytes. Real
allocator/memmove/sized-free and reached error effects remain mandatory. This
does not provide DAT catalog backing, stream I/O or603B reconciliation. Native
private stack/spills, cookie, instruction/fault/EH/concurrency parity excluded.
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
    _signed,
    _write,
)
from vantage.replay_unit_ai_base import _validate
from vantage.replay_unit_ai_construction import _local

_U64 = (1 << 64) - 1
_MAX = _U64 >> 4
_APPEND, _COMMIT, _CLEAR = 0x14148CDD0, 0x141493AA0, 0x141493B50


@dataclass(frozen=True, slots=True)
class ReplayResearchItemsScratch:
    """Explicit90B append frame, with live pointer homes20/80/88.

    Fifth/sixth pointer homes80/88 are published at logical ABI ingress, before
    the body. Native entry saves the second pointer at20. Only these source
    data homes are modeled; preserved-register spill homes/private physical
    incoming stack aliases are outside this coherent logical frame profile.
    """

    append: bytes

    def __post_init__(self) -> None:
        if type(self.append) is not bytes or len(self.append) != 0x90:
            raise ValueError("explicit90B research item append frame seed required")


def _error(calls: ReplayTaskRebuildCalls, target: int) -> None:
    _call(calls, target, ())
    raise UnresolvedReplayTaskRebuild(f"research error{target:x} returned before original INT3")


def _release(
    context: ReplayTaskRebuildStorage,
    header: int,
    calls: ReplayTaskRebuildCalls,
    terminal: ReplayTaskRebuildCalls,
) -> None:
    begin = _read(context, header, 8)
    if not begin:
        return
    size = (_read(context, header + 16, 8) - begin) & _U64 & ~15
    pointer = begin
    if size >= 0x1000:
        pointer = _read(context, begin - 8, 8)
        size = (size + 0x27) & _U64
        if ((begin - pointer - 8) & _U64) > 31:
            _call(terminal, _read(context, 0x14319A060, 8), (0, 0, 0, 0, 0))
            raise UnresolvedReplayTaskRebuild("research Watson returned before original INT3")
    _call(calls, 0x142D6BAB4, (pointer, size))


def commit_replay_research_items(
    context: ReplayTaskRebuildStorage,
    header: int,
    allocation: int,
    count: int,
    capacity: int,
    *,
    calls: ReplayTaskRebuildCalls,
    imports: ReplayTaskRebuildCalls | None = None,
) -> None:
    """Full160B141493aa0: real current release before three held-value stores."""
    _validate(context, calls, header, allocation, count, capacity)
    terminal = calls if imports is None else imports
    _validate(context, terminal)
    _release(context, header, calls, terminal)
    _write(context, header, 8, allocation)
    _write(context, header + 8, 8, allocation + (count << 4))
    _write(context, header + 16, 8, allocation + (capacity << 4))


def clear_replay_research_items(
    context: ReplayTaskRebuildStorage,
    header: int,
    *,
    calls: ReplayTaskRebuildCalls,
    imports: ReplayTaskRebuildCalls | None = None,
) -> None:
    """Full108B141493b50: null begin preserves all descriptor words.

    Read begin only once, then current capacity; there is no end read. To avoid
    duplicating that first read, the caller-specific release phases are inline.
    Free must complete before any ordered zero publication. No element callback
    or status reset is invented.
    """
    _validate(context, calls, header)
    terminal = calls if imports is None else imports
    _validate(context, terminal)
    begin = _read(context, header, 8)
    if not begin:
        return
    size = (_read(context, header + 16, 8) - begin) & _U64 & ~15
    pointer = begin
    if size >= 0x1000:
        pointer = _read(context, begin - 8, 8)
        size = (size + 0x27) & _U64
        if ((begin - pointer - 8) & _U64) > 31:
            _call(terminal, _read(context, 0x14319A060, 8), (0, 0, 0, 0, 0))
            raise UnresolvedReplayTaskRebuild("research Watson returned before original INT3")
    _call(calls, 0x142D6BAB4, (pointer, size))
    _write(context, header, 8, 0)
    _write(context, header + 8, 8, 0)
    _write(context, header + 16, 8, 0)


def append_replay_research_item(
    context: ReplayTaskRebuildStorage,
    header: int,
    word0: int,
    word2: int,
    byte4: int,
    dword8: int,
    raw_float_c: int,
    *,
    calls: ReplayTaskRebuildCalls,
    bind_local: LocalBinding,
    scratch: ReplayResearchItemsScratch,
) -> int:
    """Full422B14148cdd0 (421 indexed); six consumed POINTER arguments.

    Raw MOVSS bits are copied without numeric conversion. Growth reads payload
    only after allocation, copies using current headers, then requires actual
    commit. Non-growth writes at held end but returns pre-increment CURRENT end.
    Padding5..7 remains untouched. Native wrapped arithmetic/unsigned branches
    are preserved; successful backing and mandatory callees are not presumed.
    """
    _validate(context, calls, header, word0, word2, byte4, dword8, raw_float_c)
    if not callable(bind_local) or not isinstance(scratch, ReplayResearchItemsScratch):
        raise ValueError("live local binding and research item frame required")
    with _local(memoryview(bytearray(scratch.append)), bind_local) as frame:
        _write(context, frame + 0x80, 8, dword8)
        _write(context, frame + 0x88, 8, raw_float_c)
        _write(context, frame + 0x20, 8, word0)
        capacity_end = _read(context, header + 16, 8)
        end = _read(context, header + 8, 8)
        if end != capacity_end:
            value2 = _read(context, word2, 2)
            value4 = _read(context, byte4, 1)
            value_c = _read(context, _read(context, frame + 0x88, 8), 4)
            value8 = _read(context, _read(context, frame + 0x80, 8), 4)
            value0 = _read(context, word0, 2)
            _write(context, end + 2, 2, value2)
            _write(context, end, 2, value0)
            _write(context, end + 12, 4, value_c)
            _write(context, end + 4, 1, value4)
            _write(context, end + 8, 4, value8)
            current_end = _read(context, header + 8, 8)
            _write(context, header + 8, 8, current_end + 16)
            return current_end
        begin = _read(context, header, 8)
        length = (_signed((end - begin) & _U64, 8) >> 4) & _U64
        if length == _MAX:
            _error(calls, 0x141493BC0)
        old_capacity = (_signed((capacity_end - begin) & _U64, 8) >> 4) & _U64
        half = old_capacity >> 1
        count = (length + 1) & _U64
        capacity = _MAX
        if old_capacity <= ((_MAX - half) & _U64):
            capacity = max(count, (old_capacity + half) & _U64)
            if capacity > _MAX:
                _error(calls, 0x1402A9460)
        allocation = _call(calls, 0x1402A94D0, (capacity << 4,), width=8)
        value4 = _read(context, byte4, 1)
        value2 = _read(context, word2, 2)
        inserted = (allocation + (length << 4)) & _U64
        value_c = _read(context, _read(context, frame + 0x88, 8), 4)
        value8 = _read(context, _read(context, frame + 0x80, 8), 4)
        value0 = _read(context, _read(context, frame + 0x20, 8), 2)
        _write(context, inserted, 2, value0)
        _write(context, inserted + 12, 4, value_c)
        _write(context, inserted + 2, 2, value2)
        _write(context, inserted + 4, 1, value4)
        _write(context, inserted + 8, 4, value8)
        current_end = _read(context, header + 8, 8)
        current_begin = _read(context, header, 8)
        if end == current_end:
            _call(calls, 0x142D6E3DB, (allocation, current_begin, current_end - current_begin))
        else:
            _call(calls, 0x142D6E3DB, (allocation, current_begin, end - current_begin))
            current_end = _read(context, header + 8, 8)
            _call(calls, 0x142D6E3DB, (inserted + 16, end, current_end - end))
        _call(calls, _COMMIT, (header, allocation, count, capacity))
        return inserted


def bind_replay_research_items(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    *,
    bind_local: LocalBinding,
    scratch: ReplayResearchItemsScratch,
    imports: ReplayTaskRebuildCalls | None = None,
) -> ReplayTaskRebuildCalls:
    """Own three whole entries; real ordinary leaves delegate, never succeed unknown.

    Current Watson target uses the explicit terminal imports provider. Existing
    allocator/memmove/free thunk binders or the owned CRT capability may supply
    the actual ordinary effects; this binder does not reinterpret their target.
    """
    _validate(context, calls)
    terminal = calls if imports is None else imports
    _validate(context, terminal)
    if not callable(bind_local) or not isinstance(scratch, ReplayResearchItemsScratch):
        raise ValueError("live local binding and research item frame required")

    def dispatch(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        arities = {_APPEND: 6, _COMMIT: 4, _CLEAR: 1}
        if target not in arities:
            if calls.call is None:
                raise UnresolvedReplayTaskRebuild(f"reached{target:x} unavailable")
            return calls.call(target, args, data)
        if len(args) != arities[target] or data is not None:
            raise ValueError("malformed research item call")
        if target == _APPEND:
            return append_replay_research_item(
                context, *args, calls=bound, bind_local=bind_local, scratch=scratch
            )
        if target == _COMMIT:
            commit_replay_research_items(context, *args, calls=bound, imports=terminal)
        else:
            clear_replay_research_items(context, *args, calls=bound, imports=terminal)
        return None

    bound = ReplayTaskRebuildCalls(dispatch)
    return bound
