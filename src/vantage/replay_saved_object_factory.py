"""Build54800 saved-object factories and their concrete object-list constructors.

Sources: saved-object-factories-source-v1; four complete bodies (2,887 bytes).
Constructors, Result vector effects, atomics and allocation remain mandatory.
The factories return a Result address; object publication belongs to reached
constructors. Normal logical calls exclude physical stack/register identity,
native faults/EH/concurrency and the reached error metadata/TLS branches.
"""

from __future__ import annotations

from dataclasses import dataclass

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
from .replay_unit_ai_map import ReplayUnitAIMapAtomics, _atomic, _release

_U64 = (1 << 64) - 1
_GENERIC, _SPECIAL = 0x1412292A0, 0x14133C030
_LIST, _UNIT_LIST = 0x141227160, 0x14133BEA0
# Actual current jump-table case entries, rather than inferred class labels.
_BRANCHES = {
    0x141229324: (0x350, 0x14122E1B0),
    0x14122936D: (0x358, 0x141141760),
    0x1412293B6: (0x398, 0x14115D4F0),
    0x1412293FF: (0x420, 0x141206510),
    0x141229448: (0x628, 0x1412015F0),
    0x141229491: (0x4A0, 0x141136EC0),
    0x1412294D3: (0x618, 0x141143C30),
}


@dataclass(frozen=True, slots=True)
class ReplaySavedObjectFactoryScratch:
    """Explicit A8/B8-byte coherent frames, with each cookie region excluded.

    Each factory retains two distinct48-byte Results and an allocation/output
    slot. Stores and callbacks share their live backing; untouched padding
    keeps its supplied seed. Incoming fifth arguments are held values, without
    claiming physical caller argument-home or nested machine-stack aliases.
    """

    generic: bytes
    special: bytes

    def __post_init__(self) -> None:
        for value, size in ((self.generic, 0xA8), (self.special, 0xB8)):
            if type(value) is not bytes or len(value) != size:
                raise ValueError("explicit A8/B8 saved-object factory frames required")


def construct_replay_saved_object_list(
    context: ReplayTaskRebuildStorage,
    entry: int,
    address: int,
    capacity: int,
    growth: int,
    *,
    calls: ReplayTaskRebuildCalls,
) -> int:
    """Full80B/33B list constructors; required allocation and held destination.

    Capacity is signed low32 for the unsigned64 multiply; overflow saturates
    the allocation request to all ones. Zero still calls the allocator. The
    backing array is not initialized here. The specialized constructor calls
    the real parent before installing its own table, ignoring parent RAX.
    """
    _validate(context, calls, entry, address, capacity, growth)
    if entry == _UNIT_LIST:
        _call(calls, _LIST, (address, capacity, growth))
        _write(context, address, 8, 0x1432BEBB8)
        return address
    if entry != _LIST:
        raise ValueError("unsupported saved object-list constructor")
    _write(context, address + 0x14, 4, capacity)
    _write(context, address, 8, 0x1432B3DC0)
    _write(context, address + 0x18, 4, growth)
    size = (_signed(capacity & 0xFFFFFFFF, 4) & _U64) * 8
    allocation = _call(calls, 0x142D6C268, (min(size, _U64),), width=8)
    _write(context, address + 8, 8, allocation)
    _write(context, address + 0x10, 4, 0)
    _write(context, address + 0x1C, 1, 0)
    return address


def _initial_result(context: ReplayTaskRebuildStorage, raw: int) -> None:
    for offset in (32, 0, 16):
        _write(context, raw + offset, 16, 0)
    _write(context, raw + 32, 8, 0)
    _write(context, raw + 40, 1, 0)


def _check_result(context: ReplayTaskRebuildStorage, temporary: int) -> None:
    for offset in (16, 32, 0):
        _write(context, temporary + offset, 16, 0)
    _write(context, temporary + 16, 8, 0)
    _write(context, temporary + 24, 16, 0)
    _write(context, temporary + 40, 1, 0)


def _copy_check(
    context: ReplayTaskRebuildStorage,
    raw: int,
    temporary: int,
    control: int,
    *,
    calls: ReplayTaskRebuildCalls,
    atomics: ReplayUnitAIMapAtomics,
) -> None:
    if control:
        _atomic(atomics, control + 8, 1)
        control = _read(context, raw + 32, 8)
    status = _read(context, raw + 24, 8)
    _write(context, temporary + 24, 8, status)
    previous = _read(context, temporary + 32, 8)
    _write(context, temporary + 32, 8, control)
    if previous:
        _release(context, previous, calls, atomics)
    end = _read(context, raw + 8, 8)
    begin = _read(context, raw, 8)
    count = (_signed((end - begin) & _U64, 8) >> 5) & _U64
    _call(calls, 0x1402B9080, (temporary, begin, count))
    _write(context, raw + 40, 1, 1)


def _finish(
    context: ReplayTaskRebuildStorage,
    entry: int,
    output: int,
    raw: int,
    temporary: int,
    *,
    calls: ReplayTaskRebuildCalls,
    atomics: ReplayUnitAIMapAtomics,
) -> int:
    if _read(context, temporary + 24, 8):
        raise UnresolvedReplayTaskRebuild(
            f"saved-object factory{entry:x} reached Result error metadata/TLS frontier"
        )
    clear = 0x1402BD7F0 if entry == _GENERIC else 0x1402BD890
    _write(context, temporary + 40, 1, 1)
    control = _read(context, temporary + 32, 8)
    if control:
        _release(context, control, calls, atomics)
    _call(calls, clear, (temporary,))
    for offset in (0, 8, 16, 24, 32):
        _write(context, output + offset, 8, 0)
    _write(context, output + 40, 1, 0)
    control = _read(context, raw + 32, 8)
    if control:
        _release(context, control, calls, atomics)
    _call(calls, clear, (raw,))
    return output


def create_replay_saved_object(
    context: ReplayTaskRebuildStorage,
    entry: int,
    receiver: int,
    output: int,
    kind: int,
    stream: int,
    resolver: int,
    *,
    calls: ReplayTaskRebuildCalls,
    atomics: ReplayUnitAIMapAtomics,
    bind_local: LocalBinding,
    scratch: ReplaySavedObjectFactoryScratch,
) -> int:
    """Normal1377B/1397B factories; real construction and Result lifetimes.

    Generic dispatch reads current byte/RVA tables and accepts their proven
    case starts. Unknown targets refuse. Special fallback consumes the child's
    actual Result RAX, which can differ from its supplied local. Allocations,
    Result status/control changes and partial effects survive a later refusal.
    """
    _validate(context, calls, entry, receiver, output, kind, stream, resolver)
    if entry not in (_GENERIC, _SPECIAL):
        raise ValueError("unsupported saved-object factory")
    if not isinstance(atomics, ReplayUnitAIMapAtomics) or not callable(bind_local):
        raise ValueError("actual saved-object shared counts and local binding required")
    if not isinstance(scratch, ReplaySavedObjectFactoryScratch):
        raise ValueError("explicit saved-object factory scratch required")
    seed = scratch.generic if entry == _GENERIC else scratch.special
    with _local(memoryview(bytearray(seed)), bind_local) as frame:
        raw = frame + (0x48 if entry == _GENERIC else 0x58)
        temporary = raw + 48
        _write(context, frame + 0x38, 8, output)
        _initial_result(context, raw)
        allocation_case: tuple[int, int] | None = None
        control = 0
        if entry == _GENERIC:
            index = ((kind & 255) - 10) & 0xFFFFFFFF
            if index <= 50:
                selector = _read(context, 0x141229824 + index, 1)
                branch = 0x140000000 + _read(context, 0x141229804 + selector * 4, 4)
                if branch != 0x141229518:
                    if branch not in _BRANCHES:
                        raise UnresolvedReplayTaskRebuild(
                            f"unsupported saved-object factory branch{branch:x}"
                        )
                    allocation_case = _BRANCHES[branch]
        elif kind & 255 in (70, 80):
            allocation_case = (0x828, 0x1412A5D60) if kind & 255 == 70 else (0x9F8, 0x14126DAA0)
        else:
            _write(context, frame + 0x20, 8, resolver)
            returned = _call(
                calls, _GENERIC, (receiver, temporary, kind, stream, resolver), width=8
            )
            _write(context, returned + 40, 1, 1)
            acquired = _read(context, returned + 32, 8)
            if acquired:
                _atomic(atomics, acquired + 8, 1)
            acquired = _read(context, returned + 32, 8)
            status = _read(context, returned + 24, 8)
            _write(context, raw + 24, 8, status)
            previous = _read(context, raw + 32, 8)
            _write(context, raw + 32, 8, acquired)
            if previous:
                _release(context, previous, calls, atomics)
            if raw != returned:
                begin = _read(context, returned, 8)
                end = _read(context, returned + 8, 8)
                count = (_signed((end - begin) & _U64, 8) >> 5) & _U64
                _call(calls, 0x1402B9080, (raw, begin, count))
            _write(context, raw + 40, 1, 0)
            control = _read(context, temporary + 32, 8)
            if control:
                _release(context, control, calls, atomics)
            _call(calls, 0x1402BD890, (temporary,))
        if allocation_case is not None:
            size, constructor = allocation_case
            allocation = _call(calls, 0x142D6BA78, (size,), width=8)
            _write(context, frame + 0x38, 8, allocation)
            if allocation:
                _call(calls, 0x142D6E3B7, (allocation, 0, size))
                _write(context, frame + 0x20, 4, 1)
                _call(calls, constructor, (allocation, raw, stream, resolver, 1))
            if entry == _GENERIC:
                control = _read(context, raw + 32, 8)
        # Generic captures RDX before staging; special loads raw control after it.
        _check_result(context, temporary)
        if entry == _SPECIAL:
            control = _read(context, raw + 32, 8)
        _copy_check(context, raw, temporary, control, calls=calls, atomics=atomics)
        return _finish(context, entry, output, raw, temporary, calls=calls, atomics=atomics)


def bind_replay_saved_object_factory(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    *,
    atomics: ReplayUnitAIMapAtomics,
    bind_local: LocalBinding,
    scratch: ReplaySavedObjectFactoryScratch,
) -> ReplayTaskRebuildCalls:
    """Bind four normal entries; actual constructors/runtime/Result effects delegate."""
    _validate(context, calls)
    if not isinstance(atomics, ReplayUnitAIMapAtomics) or not callable(bind_local):
        raise ValueError("actual saved-object shared counts and local binding required")
    if not isinstance(scratch, ReplaySavedObjectFactoryScratch):
        raise ValueError("explicit saved-object factory scratch required")

    def dispatch(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        arities = {_GENERIC: 5, _SPECIAL: 5, _LIST: 3, _UNIT_LIST: 3}
        if target not in arities:
            if calls.call is None:
                raise UnresolvedReplayTaskRebuild(f"reached{target:x} is unavailable")
            return calls.call(target, args, data)
        if len(args) != arities[target] or data is not None:
            raise ValueError("malformed saved-object factory/list call")
        if target in (_LIST, _UNIT_LIST):
            return construct_replay_saved_object_list(context, target, *args, calls=bound)
        return create_replay_saved_object(
            context,
            target,
            *args,
            calls=bound,
            atomics=atomics,
            bind_local=bind_local,
            scratch=scratch,
        )

    bound = ReplayTaskRebuildCalls(dispatch)
    return bound
