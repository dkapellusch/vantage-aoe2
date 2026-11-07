"""Twelve complete formation admission/lookup/AI scalar caller bodies.

Source: world-formation-transfer-descendants-source-v1. Quiet physical shadow
spills and unread callee incidental registers are explicit profile exclusions.
Extent maps native XMM0 to a raw owned DWORD; no native RAX identity is claimed.
Deeper actual tail/virtual/admission effects and current backing stay mandatory.
"""

from __future__ import annotations

from dataclasses import dataclass

from .replay_binary32 import multiply_binary32
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
_LOOKUP, _TAIL, _GROUP = 0x141617DB0, 0x141139140, 0x141604060
_CLASSIFY, _EXTENT, _QUIET = 0x1410D95F0, 0x1410EEF50, 0x140B6EF80
_GET44, _GET3C = 0x140D23D40, 0x140D23D50
_SET44, _SET3C, _RESET, _ADDRESS = 0x140D3EA00, 0x140D3EA10, 0x140D36E70, 0x140A4B870
_MASTER_A, _MASTER_B = 0x6A586EB28AC201FC, 0x0CF19788B2554E70
_CASES = {
    0x1410D992A: 1,
    0x1410D9931: 2,
    0x1410D9938: 3,
    0x1410D993F: 4,
    0x1410D9946: 5,
    0x1410D994D: 0,
    0x1410D9951: _U32,
}


@dataclass(frozen=True, slots=True)
class ReplayFormationAdmissionProfile:
    """Two explicit38h prefixes and a required physical-shadow exclusion.

    Both live scratch QWORDs occupy postRSP30..37. Unwritten seed bytes stay
    untouched; native saved registers/return slots are not initialized objects.
    The four quiet-leaf shadow spills are excluded, never converted into an
    event. Descriptor tail supplies only its proven prepared receiver; unread
    callee incidental GP/stack consumption requires a separate capability.
    """

    classify: bytes
    extent: bytes
    exclude_quiet_shadow_spills: bool

    def __post_init__(self) -> None:
        if any(
            type(seed) is not bytes or len(seed) != 0x38 for seed in (self.classify, self.extent)
        ):
            raise ValueError("explicit38/38-hex-byte admission seeds required")
        if (
            type(self.exclude_quiet_shadow_spills) is not bool
            or not self.exclude_quiet_shadow_spills
        ):
            raise ValueError("explicitTrue physical quiet-shadow exclusion required")


def _invoke(
    calls: ReplayTaskRebuildCalls,
    target: int,
    args: tuple[int, ...],
) -> int | None:
    if calls.call is None:
        raise UnresolvedReplayTaskRebuild(f"reached{target:x} is unavailable")
    return calls.call(target, tuple(value & _U64 for value in args), None)


def _eax(calls: ReplayTaskRebuildCalls, target: int, args: tuple[int, ...]) -> int:
    result = _invoke(calls, target, args)
    if result is None:
        raise ValueError(f"helper{target:x} must supply raw RAX at EAX consumer")
    _unsigned(result, 8, f"helper{target:x} raw RAX")
    return result & _U32


def _decode(context: ReplayTaskRebuildStorage, unit: int, scratch: int) -> int:
    _write(context, scratch, 8, _read(context, unit + 0x10, 8))
    _write(context, scratch, 8, _read(context, scratch, 8) - _MASTER_A)
    _write(context, scratch, 8, _read(context, scratch, 8) - _MASTER_B)
    return _read(context, scratch, 8)


def _identifier(context: ReplayTaskRebuildStorage, unit: int, scratch: int) -> int:
    master = _decode(context, unit, scratch)
    _write(context, scratch, 8, _read(context, master + 0x18, 8))
    _write(context, scratch, 8, _read(context, scratch, 8) ^ 0x349E37847AD69F19)
    _write(context, scratch, 8, _read(context, scratch, 8) - 0x47E37DFF0616CE4F)
    return _read(context, scratch, 8) & 0xFFFF


def _classify(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    unit: int,
    other: int,
    scratch: int,
) -> int:
    master = _decode(context, unit, scratch)
    if _read(context, master + 8, 1) < 0x46:
        return _U32
    master = _decode(context, unit, scratch)
    if _read(context, master + 8, 1) == 0x46:
        master = _decode(context, unit, scratch)
        flags = _read(context, master + 0x379, 1)
        if flags & 0x11 and (_signed(flags, 1) >= 0 or not flags & 0x10):
            return 5
    if other:
        master = _decode(context, unit, scratch)
        _write(context, scratch, 8, _read(context, master + 0x38, 8))
        _write(context, scratch, 8, _read(context, scratch, 8) - 0x50A06BCECEBEF905)
        _write(context, scratch, 8, _read(context, scratch, 8) + 0x5B32AA7995D95916)
        if (
            _read(context, scratch, 8) & 0xFFFF == 0xD
            and _eax(calls, 0x14172AC80, (_read(context, unit + 0x18, 8),)) == 0
        ):
            selected = False
            for identifier in (0x4EA, 0x23, 0x1A6, 0x224):
                if _identifier(context, unit, scratch) == identifier:
                    selected = True
                    break
            if (
                selected
                and _read(context, other + 0xF, 1) == 0x50
                and _read(context, 0x14434D647, 1) == 1
            ):
                return 0
    master = _decode(context, unit, scratch)
    selector = _read(context, master + 0x35C, 1)
    if selector > 6:
        return _U32
    branch = 0x140000000 + _read(context, 0x1410D996C + selector * 4, 4)
    if branch not in _CASES:
        raise UnresolvedReplayTaskRebuild(f"unprovided classifier code entry{branch:x}")
    return _CASES[branch]


def _extent(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    unit: int,
    scratch: int,
) -> int:
    master = _decode(context, unit, scratch)
    if _read(context, master + 8, 1) < 0x46:
        return _read(context, 0x1431B2420, 4)
    if not _eax(calls, 0x141252DA0, (unit, 1)):
        return _read(context, 0x1431B2420, 4)
    first = _decode(context, unit, scratch)
    second = _decode(context, unit, scratch)
    left = _read(context, second + 0x358, 4)
    right = _read(context, first + 0x78, 4)
    return multiply_binary32(left, right)


def _lookup(context: ReplayTaskRebuildStorage, world: int, identifier: int) -> int:
    identifier &= _U32
    signed = _signed(identifier, 4)
    if signed < 0:
        if identifier == 0x80000000:
            return 0
        index = (-identifier) & _U32
        if _signed(index, 4) < _signed(_read(context, world + 0x184, 4), 4):
            begin = _read(context, world + 0x178, 8)
            return _read(context, begin + _signed(index, 4) * 8, 8)
    if signed <= -1:
        return 0
    if signed >= _signed(_read(context, world + 0x174, 4), 4):
        return 0
    begin = _read(context, world + 0x168, 8)
    return _read(context, begin + signed * 8, 8) if begin else 0


def _group(context: ReplayTaskRebuildStorage, world: int, identifier: int) -> int:
    identifier &= _U32
    if identifier == _U32:
        return 0
    sentinel = _read(context, world + 0x50, 8)
    row = _read(context, sentinel + 0xC8, 8)
    while row != sentinel:
        if _read(context, row + 0xD8, 4) == identifier:
            return row
        row = _read(context, row + 0xC8, 8)
    return 0


def _set3c(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    ai: int,
    new_value: int,
    save_old: int,
) -> None:
    current = _read(context, ai + 0x3C, 4)
    if current in (0x2C7, 0x2DD) and new_value != current:
        if _read(context, ai + 0x16C, 4) == 0x2EE:
            vptr = _read(context, ai, 8)
            target = _read(context, vptr + 0x1A8, 8)
            _invoke(calls, target, (ai,))
        if _signed(_read(context, ai + 0x174, 4), 4) > 0x2EE:
            _write(context, ai + 0x174, 4, 0x2EE)
    if save_old:
        _write(context, ai + 0x64, 4, _read(context, ai + 0x3C, 4))
    _write(context, ai + 0x3C, 4, new_value)


def bind_replay_formation_admission(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    *,
    descriptor_tail_calls: ReplayTaskRebuildCalls,
    bind_local: LocalBinding,
    profile: ReplayFormationAdmissionProfile,
    mxcsr: int,
) -> ReplayTaskRebuildCalls:
    """Bind12 complete entries; no Game getter duplicate or fake child effects.

    Current tables/constants/objects are mandatory. Internal jumps admit only
    actual scalar-return case starts; other current table code entries refuse.
    Classifier null and extent null gates use no unreached local mapping.
    FP state/traps, native physical shadow/saves and deeper incidental GP/stack
    consumption are excluded. Unknown target/args/data/results delegate exactly.
    """
    _validate(context, calls)
    if not isinstance(descriptor_tail_calls, ReplayTaskRebuildCalls) or not callable(bind_local):
        raise ValueError("actual descriptor tail channel and local binding required")
    if not isinstance(profile, ReplayFormationAdmissionProfile):
        raise ValueError("explicit formation admission profile required")
    if type(mxcsr) is not int or mxcsr != 0x1F80:
        raise ValueError("exact masked MXCSR1f80 profile required")
    arities = {
        _LOOKUP: 2,
        _TAIL: 1,
        _GROUP: 2,
        _CLASSIFY: 2,
        _EXTENT: 1,
        _GET44: 1,
        _GET3C: 1,
        _SET44: 2,
        _SET3C: 3,
        _RESET: 1,
        _ADDRESS: 1,
        _QUIET: 4,
    }

    def dispatch(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        if target not in arities:
            if calls.call is None:
                raise UnresolvedReplayTaskRebuild(f"reached{target:x} is unavailable")
            return calls.call(target, args, data)
        if len(args) != arities[target] or data is not None:
            raise ValueError("malformed formation admission call")
        _validate(context, calls, *args)
        unit = args[0]
        if target == _LOOKUP:
            return _lookup(context, unit, args[1])
        if target == _GROUP:
            return _group(context, unit, args[1])
        if target == _TAIL:
            receiver = _read(context, unit + 0x420, 8)
            return _invoke(descriptor_tail_calls, 0x140B88AF0, (receiver,))
        if target == _QUIET:
            # Its only four physical shadow spills are explicitly excluded.
            return None
        if target in (_CLASSIFY, _EXTENT):
            if not unit:
                return _U32 if target == _CLASSIFY else _read(context, 0x1431B2420, 4)
            seed = profile.classify if target == _CLASSIFY else profile.extent
            with _local(memoryview(bytearray(seed)), bind_local) as frame:
                if target == _CLASSIFY:
                    return _classify(context, bound, unit, args[1], frame + 0x30)
                return _extent(context, bound, unit, frame + 0x30)
        if target == _ADDRESS:
            return (unit + 0x1B8) & _U64
        if target in (_GET44, _GET3C):
            return _read(context, unit + (0x44 if target == _GET44 else 0x3C), 4)
        if target == _SET44:
            previous = _read(context, unit + 0x44, 4)
            _write(context, unit + 0x68, 4, previous)
            _write(context, unit + 0x44, 4, args[1])
            return previous
        if target == _RESET:
            _write(context, unit + 0x18, 4, 0)
            return None
        _set3c(context, bound, unit, args[1] & _U32, args[2] & _U32)
        return None

    bound = ReplayTaskRebuildCalls(dispatch)
    return bound


def bind_replay_formation_quiet_home_calls(calls: ReplayTaskRebuildCalls) -> ReplayTaskRebuildCalls:
    """Explicit transfer HOME9-to-register4 adapter for the real quiet leaf.

    The five annotated home ADDRESSES are validated as words but never read.
    The actual leaf performs no event emission and consumes no such homes.
    Unknown calls retain target/args/data/result unchanged. The underlying
    admission profile must declare its physical-shadow spill exclusion.
    """
    if not isinstance(calls, ReplayTaskRebuildCalls):
        raise ValueError("actual quiet-leaf calls required")

    def dispatch(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        if target != _QUIET:
            if calls.call is None:
                raise UnresolvedReplayTaskRebuild(f"reached{target:x} is unavailable")
            return calls.call(target, args, data)
        if len(args) != 9 or data is not None:
            raise ValueError("quiet HOME adapter requires exactly9 scalar annotations")
        for value in args:
            _unsigned(value, 8, "quiet HOME annotation")
        return _invoke(calls, target, args[:4])

    return ReplayTaskRebuildCalls(dispatch)
