"""Build54800 master TaskList rebuild1412bb630 over explicit current storage.

The prefix and reached native helpers require real bindings. This module ports
all five task branches, dynamic iteration, descriptor bytes and inline stores;
it does not infer helper success, restored initialization or a runnable World.
Source: world-envelope/first-building-transform-postreader-frontier/native-three-
20261018/1412bb630.asm.tsv. Literal stack addresses/fault order are excluded.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from .replay_binary32 import compare_binary32

_U64 = (1 << 64) - 1
_U32 = (1 << 32) - 1
_MASTER_ADD = 0x6A586EB28AC201FC + 0x0CF19788B2554E70
_CLASS_ADD = 0x0A923EAAC71A6011
# A positive entry is passed by stack value to1412a57e0. A negative entry
# denotes a literal address passed to the distinct1412a56c0 overload.
_MASK_CLASSES = (
    (50, 6, 28, 45, 46, 56, 9, 10, 29, 58, 61, -0x1432B8254, 35),
    (12, 47, 57, 24),
    (0, 44),
    (36, 23),
    (18, 43, 17),
    (4, 19, 59, -0x1432B8258),
    (20, 21, 22, 2, 53),
    (-0x1432B8260, 13, -0x1432B8250, 54, 55),
    (3, 27, 39, 49, 52, 60, -0x1432B825C),
)


class UnresolvedReplayTaskRebuild(ValueError):
    """A reached native helper has no actual implementation binding."""


def _unsigned(value: int, width: int, name: str) -> None:
    if type(value) is not int or not 0 <= value < 1 << (width * 8):
        raise ValueError(f"{name} must be a raw unsigned{width * 8} word")


def _signed(value: int, width: int) -> int:
    sign = 1 << (width * 8 - 1)
    return value - (sign << 1) if value & sign else value


def _trunc_div(value: int, divisor: int) -> int:
    magnitude = abs(value) // divisor
    return -magnitude if value < 0 else magnitude


def _cvtt(value: int) -> int:
    """Low EAX of masked CVTTSS2SI32, using integer arithmetic only."""
    exponent = (value >> 23) & 255
    significand = value & 0x7FFFFF
    if exponent == 255:
        return 0x80000000
    if exponent:
        significand |= 0x800000
    shift = exponent - 150 if exponent else -149
    magnitude = significand << shift if shift >= 0 else significand >> -shift
    result = -magnitude if value & 0x80000000 else magnitude
    return result & _U32 if -(1 << 31) <= result < 1 << 31 else 0x80000000


@dataclass(frozen=True, slots=True)
class ReplayTaskRebuildStorage:
    """Current subject and scalar address reader/writer, with coherent backing.

    read(address,width) returns an unsigned scalar; write(address,width,value)
    stores it. Address arithmetic wraps u64. Actual master/owner/tasks/vectors,
    returned helper slots and allocations must be backed whenever reached.
    Successful accesses, aligned valid vectors and synchronous helper mutation
    are premises; concurrent storage and native fault equivalence are excluded.
    """

    subject: int
    read: Callable[[int, int], int]
    write: Callable[[int, int, int], None]

    def __post_init__(self) -> None:
        _unsigned(self.subject, 8, "subject")
        if not self.subject or not callable(self.read) or not callable(self.write):
            raise ValueError("nonnull subject and actual scalar read/write bindings required")


@dataclass(frozen=True, slots=True)
class ReplayTaskRebuildScratch:
    """Explicit initial bytes for native locals that are not fully initialized.

    descriptor is48 bytes shared by155/158 (native stack+b8..e7). group_padding
    is stack39..3b; criterion_padding is51..53. No zero initialization is implied.
    Helper key copies are separate; mutations to a copied key do not change its
    staging padding. Descriptor append helpers receive a shared mutable view.
    Stack aliasing, escaped local pointers and access beyond these views are
    outside this effective-call interface.
    """

    descriptor: bytes
    group_padding: bytes
    criterion_padding: bytes

    def __post_init__(self) -> None:
        if any(
            type(value) is not bytes or len(value) != size
            for value, size in (
                (self.descriptor, 48),
                (self.group_padding, 3),
                (self.criterion_padding, 3),
            )
        ):
            raise ValueError("explicit48/3/3-byte task rebuild scratch seeds required")


@dataclass(frozen=True, slots=True)
class ReplayTaskRebuildCalls:
    """Dispatcher for actual reached helpers, identified by their native target.

    call(target,args,data) uses effective scalar arguments. Pointer arithmetic
    and register-width truncation happen before dispatch. data is a mutable
    local-input view when supplied:12B group key,24B criterion,4B row/class value,
    or40/48B descriptor. Local addresses and output-iterator storage are abstracted:
    lookups4560/4220 return raw RAX pointing to a readable result-slot qword.
    Other pointer returns are raw u64; selector returns are raw EAX/AL/AX.

    56c0 receives a literal address in args;57e0 receives a4B local view. Append
    3ab0/3ca0 args are(vector,current_end). Allocator94d0, memmove6e3db and vector
    commitba840 retain their native scalar arguments. The dispatcher must bind
    real helpers/current dispatch, or raise UnresolvedReplayTaskRebuild when a
    target is unavailable. None marks the whole dispatcher unavailable. Prior
    writes and helper effects survive exceptions; no successful effect is faked.
    """

    call: Callable[[int, tuple[int, ...], memoryview | None], int | None] | None

    def __post_init__(self) -> None:
        if self.call is not None and not callable(self.call):
            raise ValueError("actual helper dispatcher or unavailable binding required")


def _read(context: ReplayTaskRebuildStorage, address: int, width: int) -> int:
    value = context.read(address & _U64, width)
    _unsigned(value, width, "task rebuild read")
    return value


def _write(context: ReplayTaskRebuildStorage, address: int, width: int, value: int) -> None:
    context.write(address & _U64, width, value & ((1 << (width * 8)) - 1))


def _call(
    calls: ReplayTaskRebuildCalls,
    target: int,
    args: tuple[int, ...],
    data: memoryview | None = None,
    *,
    width: int | None = None,
) -> int:
    if calls.call is None:
        raise UnresolvedReplayTaskRebuild(f"reached{target:x} is unavailable")
    value = calls.call(target, tuple(arg & _U64 for arg in args), data)
    if width is None:
        return 0
    if value is None:
        raise ValueError(f"helper{target:x} must return its raw scalar result")
    _unsigned(value, width, f"helper{target:x} return")
    return value


def _put(raw: bytearray, offset: int, width: int, value: int) -> None:
    raw[offset : offset + width] = (value & ((1 << (width * 8)) - 1)).to_bytes(width, "little")


def _get(raw: bytearray, offset: int, width: int) -> int:
    return int.from_bytes(raw[offset : offset + width], "little")


def _master(context: ReplayTaskRebuildStorage) -> int:
    return (_read(context, context.subject + 0x10, 8) - _MASTER_ADD) & _U64


def _append_record(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    descriptor: bytearray,
    vector: int,
    end: int,
    size: int,
    target: int,
) -> None:
    if end == _read(context, vector + 0x10, 8):
        _call(calls, target, (vector, end), memoryview(descriptor)[:size])
        return
    for offset, width in ((0, 16), (16, 16), (32, size - 32)):
        _write(context, end + offset, width, _get(descriptor, offset, width))
    _write(context, vector + 8, 8, _read(context, vector + 8, 8) + size)


def _health_task(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    descriptor: bytearray,
    task: int,
) -> None:
    graphic = _read(context, task + 0x48, 8)
    graphic_id = _signed(_read(context, graphic + 0x18, 2), 2) if graphic else -1
    selector = _cvtt(_read(context, task + 0x28, 4))
    scaled = int(_read(context, task + 0x15, 1) == 1)
    vector = (context.subject + 0x7A8) & _U64
    end = _read(context, vector + 8, 8)
    threshold = _read(context, task + 0x2C, 4)
    payload_tail = _read(context, task + 0x70, 8)
    _put(descriptor, 0, 4, selector)
    _put(descriptor, 4, 4, threshold)
    _put(descriptor, 8, 2, _read(context, task + 0x22, 2))
    payload_head = _read(context, task + 0x60, 16)
    _put(descriptor, 0xA, 2, _read(context, task + 0x24, 2))
    _put(descriptor, 0xC, 1, scaled)
    _put(descriptor, 0x10, 4, graphic_id)
    _put(descriptor, 0x18, 16, payload_head)
    _put(descriptor, 0x28, 8, payload_tail)
    _append_record(context, calls, descriptor, vector, end, 48, 0x1412A3AB0)


def _class_growth(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    group: int,
    position: int,
    capacity_end: int,
    selector: int,
) -> None:
    vector = (group + 0x60) & _U64
    begin = _read(context, vector, 8)
    count = _signed((position - begin) & _U64, 8) >> 2
    maximum = 0x3FFFFFFFFFFFFFFF
    if count == maximum:
        _call(calls, 0x1402BA950, ())
        raise RuntimeError("nonreturning vector length-error helper returned")
    capacity = (_signed((capacity_end - begin) & _U64, 8) >> 2) & _U64
    new_count = (count + 1) & _U64
    half = capacity >> 1
    if capacity > maximum - half:
        grown = maximum
    else:
        grown = max(new_count, (capacity + half) & _U64)
        if grown > maximum:
            _call(calls, 0x1402A9460, ())
            raise RuntimeError("nonreturning allocation-error helper returned")
    allocation = _call(calls, 0x1402A94D0, ((grown * 4) & _U64,), width=8)
    _write(context, allocation + count * 4, 4, selector)
    end = _read(context, vector + 8, 8)
    begin = _read(context, vector, 8)
    if position == end:
        _call(calls, 0x142D6E3DB, (allocation, begin, (end - begin) & _U64))
    else:
        _call(calls, 0x142D6E3DB, (allocation, begin, (position - begin) & _U64))
        end = _read(context, vector + 8, 8)
        _call(
            calls,
            0x142D6E3DB,
            (
                (allocation + new_count * 4) & _U64,
                position,
                (end - position) & _U64,
            ),
        )
    _call(calls, 0x1402BA840, (vector, allocation, new_count, grown))


def _group_task(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    scratch: ReplayTaskRebuildScratch,
    descriptor: bytearray,
    selector: int,
    class_mode: bool,
) -> None:
    key = bytearray(12)
    key[:4] = descriptor[0x10:0x14]
    _put(key, 4, 4, (~(descriptor[0x15] >> 1)) & 1)
    kind = descriptor[0x14]
    key[8] = (31, 2, 24, 1, 7, 25, 29)[kind] if kind <= 6 else 31
    key[9:] = scratch.group_padding
    group_slot = _call(
        calls, 0x1412A4560, ((context.subject + 0x6E0) & _U64,), memoryview(key), width=8
    )
    # These descriptor reloads occur after the group lookup, before4220.
    criterion = bytearray(24)
    criterion[0] = descriptor[0x15] & 1
    criterion[1:4] = scratch.criterion_padding
    criterion[4:16] = descriptor[4:16]
    criterion[16:24] = descriptor[24:32]
    group = _read(context, group_slot, 8)
    subgroup_slot = _call(
        calls, 0x1412A4220, ((group + 0x20) & _U64,), memoryview(criterion), width=8
    )
    end = _read(context, context.subject + 0x738, 8)
    begin = _read(context, context.subject + 0x730, 8)
    row_index = _trunc_div(_signed((end - begin) & _U64, 8), 40) & _U32
    subgroup = _read(context, subgroup_slot, 8)
    index = bytearray(row_index.to_bytes(4, "little"))
    _call(calls, 0x1412A57E0, ((subgroup + 0x28) & _U64,), memoryview(index))
    end = _read(context, group + 0x68, 8)
    begin = _read(context, group + 0x60, 8)
    found = _call(calls, 0x142D6A0D0, (begin, end, selector & _U32), width=8)
    current_end = _read(context, group + 0x68, 8)
    if found == current_end:
        if class_mode:
            mask = _call(calls, 0x141320720, (_master(context), selector & _U32), width=2)
            for bit, classes in enumerate(_MASK_CLASSES):
                if not mask & (1 << bit):
                    continue
                for member in classes:
                    vector = (group + 0x60) & _U64
                    if member < 0:
                        _call(calls, 0x1412A56C0, (vector, -member))
                    else:
                        value = bytearray(member.to_bytes(4, "little"))
                        _call(calls, 0x1412A57E0, (vector,), memoryview(value))
        else:
            capacity_end = _read(context, group + 0x70, 8)
            if current_end != capacity_end:
                _write(context, current_end, 4, selector)
                _write(context, group + 0x68, 8, _read(context, group + 0x68, 8) + 4)
            else:
                _class_growth(context, calls, group, current_end, capacity_end, selector)
    vector = (context.subject + 0x730) & _U64
    end = _read(context, vector + 8, 8)
    _append_record(context, calls, descriptor, vector, end, 40, 0x1412A3CA0)


def _transform_task(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    scratch: ReplayTaskRebuildScratch,
    descriptor: bytearray,
    task: int,
    first: list[bool],
) -> None:
    original = _signed(_read(context, task + 0x10, 2), 2)
    class_mode = ((original + 999) & 0xFFFF) > 1998
    if class_mode:
        selector = original
    elif original < 0:
        fallback = _signed(_read(context, task + 0x12, 2), 2)
        selector = fallback if fallback >= 0 else -1
    else:
        selector = _signed(_call(calls, 0x1410B9F00, (original, 1998), width=4), 4)
    if not _read(context, task + 0x15, 1) & 8:
        for i, (offset, width, destination) in enumerate(
            (
                (0x60, 4, 0x750),
                (0x78, 4, 0x754),
                (0x34, 2, 0x74C),
            )
        ):
            if not first[i]:
                value = _read(context, task + offset, width)
                if value:
                    _write(context, context.subject + destination, 4, _signed(value, width))
                    first[i] = True
    if _read(context, task + 0x15, 1) & 0x40:
        _call(calls, 0x141244C90, (context.subject,))
    converted = _cvtt(_read(context, task + 0x1C, 4))
    normalized = int(_read(context, task + 0x1B, 1) != 0)
    kind = _read(context, task + 0x18, 1)
    _put(descriptor, 0, 4, selector)
    descriptor[0x14] = kind
    descriptor[0x24] = int(class_mode)
    amount = _read(context, task + 0x28, 4)
    descriptor[0x16] = normalized
    threshold = _read(context, task + 0x2C, 4)
    _put(descriptor, 4, 4, converted)
    descriptor[0x15] = _read(context, task + 0x15, 1)
    _put(descriptor, 0x18, 8, _read(context, task + 0x48, 8))
    _put(descriptor, 0x20, 4, _signed(_read(context, task + 0x38, 2), 2))
    _put(descriptor, 8, 4, amount)
    group_amount = _read(context, task + 0x30, 4)
    _put(descriptor, 0xC, 4, threshold)
    _put(descriptor, 0x10, 4, group_amount)
    if not class_mode:
        if _call(calls, 0x1410BA3D0, (selector & _U32,), width=1):
            selector = _signed(_call(calls, 0x1410BD060, (_get(descriptor, 0, 4),), width=4), 4)
        else:
            owner = _read(context, context.subject + 0x18, 8)
            count = _signed(_read(context, owner + 0x20, 4), 4) if owner else 0
            original_selector = _signed(_get(descriptor, 0, 4), 4)
            if not 0 <= original_selector < count:
                return
            table = _read(context, owner + 0x28, 8)
            master = _read(context, table + original_selector * 8, 8)
            if not master:
                return
            raw_class = _read(context, master + 0x38, 8)
            selector = _signed((raw_class + _CLASS_ADD) & 0xFFFF, 2)
    if compare_binary32(_get(descriptor, 0xC, 4), 0) == 1:
        _group_task(context, calls, scratch, descriptor, selector, class_mode)


def run_replay_task_rebuild(
    context: ReplayTaskRebuildStorage,
    task_list: int,
    *,
    mxcsr: int,
    scratch: ReplayTaskRebuildScratch,
    calls: ReplayTaskRebuildCalls,
) -> None:
    """Run1412bb630 including its prefix, clears and all five task branches.

    Prefix14114bf70 receives the original held TaskList even when null. Both
    vector clears and1412c5270 happen before the null/empty test. Task3 conditionally
    calls2483f0;6 stores raw fields;155 builds/group-indexes40B rules;158 appends
    health48B rules;164 calls2b7850. Other/null tasks skip. First-nonzero flags
    are local to this invocation and survive callback changes to object fields.
    TaskList begin/end are reread after each task, with separate u64 byte offset
    and wrapping signed32 ordinal used by the source's unsigned comparison.

    MXCSR requires masked nearest-even, DAZ/FTZ off. CVTT truncates independently
    of rounding; NaN/out-of-range produce INT_MIN. FP status/traps are excluded.
    This entry point does not automatically clear World initialization flags.
    """
    if not isinstance(context, ReplayTaskRebuildStorage):
        raise ValueError("explicit current task rebuild storage required")
    if not isinstance(scratch, ReplayTaskRebuildScratch):
        raise ValueError("explicit native scratch seeds required")
    if not isinstance(calls, ReplayTaskRebuildCalls):
        raise ValueError("explicit actual helper bindings required")
    _unsigned(task_list, 8, "TaskList")
    _unsigned(mxcsr, 4, "MXCSR")
    if mxcsr & ~0x3F != 0x1F80:
        raise ValueError("masked nearest-even MXCSR, DAZ/FTZoff required")
    descriptor = bytearray(scratch.descriptor)
    _call(calls, 0x14114BF70, (context.subject, task_list))
    for member in (0x730, 0x7A8):
        begin = _read(context, context.subject + member, 8)
        end = _read(context, context.subject + member + 8, 8)
        if begin != end:
            _write(context, context.subject + member + 8, 8, begin)
    _call(calls, 0x1412C5270, ((context.subject + 0x6E0) & _U64,))
    if not task_list:
        return
    end = _read(context, task_list + 0x10, 8)
    begin = _read(context, task_list + 8, 8)
    if end == begin or not (_signed((end - begin) & _U64, 8) >> 3):
        return
    ordinal = offset = 0
    first = [False, False, False]
    while True:
        task = _read(context, begin + offset, 8)
        if task:
            kind = _signed(_read(context, task + 0xE, 2), 2)
            if kind == 3:
                _master(context)  # Native performs this unused first decode too.
                if _read(context, _master(context) + 0x1FC, 1) <= 8:
                    selector = _read(context, task + 0x10, 2)
                    if selector in (3, 13):
                        _call(calls, 0x1412483F0, (context.subject, 1))
            elif kind == 6:
                _write(context, context.subject + 0x80C, 4, _read(context, task + 0x30, 4))
                _write(context, context.subject + 0x810, 4, _read(context, task + 0x1C, 4))
            elif kind == 155:
                _transform_task(context, calls, scratch, descriptor, task, first)
            elif kind == 158:
                _health_task(context, calls, descriptor, task)
            elif kind == 164:
                _call(calls, 0x1412B7850, (context.subject, task))
        ordinal = (ordinal + 1) & _U32
        begin = _read(context, task_list + 8, 8)
        offset = (offset + 8) & _U64
        end = _read(context, task_list + 0x10, 8)
        count = (_signed((end - begin) & _U64, 8) >> 3) & _U64
        if (_signed(ordinal, 4) & _U64) >= count:
            return
