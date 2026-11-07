"""Build54800 World zone-vector getter and shared zone-map registry lookup.

Complete8B141604030/692B1414ecf90 source is retained in
tc-unit-ai15-map-acquisition-children-source-v1. Positive-float prefix matching
is not equality of float values or lengths. Missing constructors, growth and
refresh remain actual reached effects. Native FPstatus/EH/faults are excluded.
"""

from __future__ import annotations

from .replay_binary32 import compare_binary32
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
from .replay_unit_ai_base import _count, _validate
from .replay_unit_ai_construction import _local
from .replay_unit_ai_map import ReplayUnitAIMapAtomics, _atomic, _release

_U64 = (1 << 64) - 1


def _pairs(end: int, begin: int) -> int:
    return (_signed((end - begin) & _U64, 8) >> 4) & _U64


def _publish(
    context: ReplayTaskRebuildStorage,
    output: int,
    index: int,
    obj: int,
    control: int,
    calls: ReplayTaskRebuildCalls,
    atomics: ReplayUnitAIMapAtomics,
) -> int:
    _write(context, output, 2, index)
    _write(context, output + 8, 8, 0)
    _write(context, output + 16, 8, 0)
    if control:
        _atomic(atomics, control + 8, 1)
    _write(context, output + 8, 8, obj)
    _write(context, output + 16, 8, control)
    if control:
        _release(context, control, calls, atomics)
    return output


def acquire_replay_zone_map(
    context: ReplayTaskRebuildStorage,
    manager: int,
    output: int,
    input_range: int,
    refresh: int,
    *,
    calls: ReplayTaskRebuildCalls,
    atomics: ReplayUnitAIMapAtomics,
    bind_local: LocalBinding,
) -> int:
    """Full692B1414ecf90 with current vector backing and shared ownership.

    A candidate's positivity pattern must be a prefix of the supplied vector.
    Empty candidates match. Candidate vectors are held; registry headers are
    reread after each rejected candidate's release. Output bytes2..7 stay
    untouched. The new shared allocation is only initialized in its first16B
    before the mandatory real zone constructor. Null allocation retains the
    source's object token0x10/control0 result, not an invented null pair.
    Finite valid backing/ranges and sequential atomic operations required.
    """
    _validate(context, calls, manager, output, input_range, refresh)
    if not isinstance(atomics, ReplayUnitAIMapAtomics) or not callable(bind_local):
        raise ValueError("actual zone shared-count/local bindings required")
    index, offset = 0, 0
    begin = _read(context, manager, 8)
    count = _pairs(_read(context, manager + 8, 8), begin)
    while index < count:
        initial = _read(context, begin + offset + 8, 8)
        if initial:
            _atomic(atomics, initial + 8, 1)
        obj = _read(context, begin + offset, 8)
        control = _read(context, begin + offset + 8, 8)
        candidate = _read(context, obj + 0x818, 8)
        length = _count(_read(context, obj + 0x820, 8), candidate)
        source = _read(context, input_range, 8)
        available = _count(_read(context, input_range + 8, 8), source)
        matches = length <= available
        item = 0
        while matches and item < length:
            # COMISS/SETA maps every unordered value to false. Each native
            # operand read is retained, candidate before source.
            positive = compare_binary32(_read(context, candidate + item * 4, 4), 0) == 1
            matches = (compare_binary32(_read(context, source + item * 4, 4), 0) == 1) == positive
            item = (item + 1) & 0xFFFFFFFF
        if matches:
            if refresh & 255:
                _call(calls, 0x1414EC840, (obj,))
            return _publish(context, output, index, obj, control, calls, atomics)
        if control:
            _release(context, control, calls, atomics)
        index = (index + 1) & _U64
        offset = (offset + 16) & _U64
        begin = _read(context, manager, 8)
        count = _pairs(_read(context, manager + 8, 8), begin)
    control = _call(calls, 0x142D6BA78, (0x868,), width=8)
    if control:
        _write(context, control, 16, 0)
        _write(context, control + 8, 4, 1)
        _write(context, control + 12, 4, 1)
        _write(context, control, 8, 0x1432D91C0)
        _call(
            calls,
            0x1414EA4A0,
            ((control + 16) & _U64, _read(context, manager + 24, 8), input_range),
        )
    obj = (control + 16) & _U64
    end = _read(context, manager + 8, 8)
    if end == _read(context, manager + 16, 8):
        raw = bytearray(obj.to_bytes(8, "little") + control.to_bytes(8, "little"))
        with _local(memoryview(raw), bind_local) as pair:
            _call(calls, 0x1414EA070, (manager, end, pair))
            # Both values are current only here, then held through publication.
            control = _read(context, pair + 8, 8)
            obj = _read(context, pair, 8)
            return _finish_new(context, manager, output, obj, control, calls, atomics)
    _write(context, end, 8, 0)
    _write(context, end + 8, 8, 0)
    if control:
        _atomic(atomics, control + 8, 1)
    _write(context, end, 8, obj)
    _write(context, end + 8, 8, control)
    _write(context, manager + 8, 8, _read(context, manager + 8, 8) + 16)
    return _finish_new(context, manager, output, obj, control, calls, atomics)


def _finish_new(
    context: ReplayTaskRebuildStorage,
    manager: int,
    output: int,
    obj: int,
    control: int,
    calls: ReplayTaskRebuildCalls,
    atomics: ReplayUnitAIMapAtomics,
) -> int:
    # The original final size uses two DWORD loads, SUB EAX, zero extension,
    # SAR RAX4 and DEC AX. Full64 header subtraction is observably different.
    size = ((_read(context, manager + 8, 4) - _read(context, manager, 4)) & 0xFFFFFFFF) >> 4
    return _publish(context, output, size - 1, obj, control, calls, atomics)


def bind_replay_zone_map_registry(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    *,
    atomics: ReplayUnitAIMapAtomics,
    bind_local: LocalBinding,
) -> ReplayTaskRebuildCalls:
    """Bind the World descriptor getter and full registry caller, with real descendants."""
    _validate(context, calls)
    if not isinstance(atomics, ReplayUnitAIMapAtomics) or not callable(bind_local):
        raise ValueError("actual zone shared-count/local bindings required")

    def dispatch(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        if target not in (0x141604030, 0x1414ECF90):
            if calls.call is None:
                raise UnresolvedReplayTaskRebuild(f"reached{target:x} is unavailable")
            return calls.call(target, args, data)
        if len(args) != (1 if target == 0x141604030 else 4) or data is not None:
            raise ValueError("malformed zone registry call")
        if target == 0x141604030:
            _validate(context, calls, args[0])
            return (args[0] + 0x788) & _U64
        return acquire_replay_zone_map(
            context, *args, calls=bound, atomics=atomics, bind_local=bind_local
        )

    bound = ReplayTaskRebuildCalls(dispatch)
    return bound
