"""Current backing for build54800 UnitAI position, classes, timer and stat leaves.

Source: tc-unit-ai15-normal-leaves-source-v1, native/intelligent-movement and
native/object-stat-modifier. The83B building getter is an exact tail range,
not a claimed complete Ghidra function. Shared map acquisition stays separate.
"""

from __future__ import annotations

from .replay_binary32 import add_binary32, compare_binary32, multiply_binary32
from .replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
    _call,
    _read,
    _unsigned,
    _write,
)
from .replay_unit_ai_base import _count, _validate

_U64 = (1 << 64) - 1
_U32 = (1 << 32) - 1
_MAX_CLASSES = (1 << 62) - 1


def construct_replay_ai_position(
    context: ReplayTaskRebuildStorage,
    address: int,
    x: int,
    y: int,
    z: int,
    kind: int,
) -> int:
    """Full27B140c285f0; kindWORD first, raw float words, padding14..15 untouched."""
    _validate(context, ReplayTaskRebuildCalls(None), address, x, y, z, kind)
    _write(context, address + 12, 2, kind)
    for offset, word in ((0, x), (4, y), (8, z)):
        _write(context, address + offset, 4, word)
    return address


def reserve_replay_ai_classes(
    context: ReplayTaskRebuildStorage,
    vector: int,
    requested: int,
    *,
    calls: ReplayTaskRebuildCalls,
) -> None:
    """Full177B1402ba470; release old backing, then allocate and publish all headers.

    No element copy occurs here. A nonempty old allocation requires the real
    release helper. Nonreturning runtime errors must raise; unexpected returns
    refuse before subsequent effects. Native EH and allocation failure omitted.
    """
    _validate(context, calls, vector, requested)
    if requested > _MAX_CLASSES:
        _call(calls, 0x1402BA950, ())
        raise UnresolvedReplayTaskRebuild("nonreturning class length error returned")
    begin = _read(context, vector, 8)
    capacity = _count(_read(context, vector + 16, 8), begin)
    half = capacity >> 1
    growth = _MAX_CLASSES if capacity > _MAX_CLASSES - half else max(requested, capacity + half)
    if begin:
        _call(calls, 0x1402BD690, (vector, begin))
        for offset in (0, 8, 16):
            _write(context, vector + offset, 8, 0)
    if growth > _MAX_CLASSES:
        _call(calls, 0x1402A9460, ())
        raise UnresolvedReplayTaskRebuild("nonreturning class allocation error returned")
    size = growth * 4
    allocation = _call(calls, 0x1402A94D0, (size,), width=8)
    _write(context, vector, 8, allocation)
    _write(context, vector + 8, 8, allocation)
    _write(context, vector + 16, 8, allocation + size)


def update_replay_ai_idle_time(
    context: ReplayTaskRebuildStorage,
    address: int,
    *,
    calls: ReplayTaskRebuildCalls,
) -> None:
    """Full80B140d1a2f0; held idle time and mandatory current AI-stream draw.

    This is the fourth draw during AI15 setup. A later change to idle time by
    the RNG callback does not affect this invocation's divisor or base value.
    """
    _validate(context, calls, address)
    idle = _read(context, address + 0x170, 4)
    draw = _call(calls, 0x140903E40, (0x1443530F0, 0x14324D5B0, 0x1A6C), width=4)
    if not idle >> 1:
        raise UnresolvedReplayTaskRebuild("UnitAI adjusted idle-time divisor is zero")
    _write(context, address + 0x16C, 4, draw % (idle >> 1) + ((idle * 3 & _U32) >> 2))


def apply_replay_stat_record(
    context: ReplayTaskRebuildStorage,
    record: int,
    word: int,
) -> int:
    """Full60B1414c47e0 low-lane result; unknown operations never read amount."""
    _validate(context, ReplayTaskRebuildCalls(None), record)
    _unsigned(word, 4, "stat input word")
    operation = _read(context, record, 4)
    if operation not in (1, 2, 3, 4):
        return word
    amount = _read(context, record + 8, 4)
    if operation == 1:
        return add_binary32(word, amount)
    if operation == 2:
        return multiply_binary32(word, amount)
    comparison = compare_binary32(amount, word)
    return amount if comparison == (-1 if operation == 3 else 1) else word


def apply_replay_object_stat(
    context: ReplayTaskRebuildStorage,
    subject: int,
    category: int,
    word: int,
    *,
    calls: ReplayTaskRebuildCalls,
) -> int:
    """Full245B1412428d0 with current native hash backing and held traversal bounds.

    Bucket pointer and terminal are loaded once, including terminal before
    the first key read. Head and modifier begin/end are held through callbacks.
    Finite well-formed chains/ranges required; no missing category is invented.
    """
    _validate(context, calls, subject, category)
    _unsigned(word, 4, "stat input word")
    category &= _U32
    hashed = 0xCBF29CE484222325
    for shift in (0, 8, 16, 24):
        hashed = ((hashed ^ ((category >> shift) & 255)) * 0x100000001B3) & _U64
    head = _read(context, subject + 0x300, 8)
    buckets = _read(context, subject + 0x310, 8)
    bucket = (hashed & _read(context, subject + 0x328, 8)) * 16
    node = _read(context, (buckets + bucket + 8) & _U64, 8)
    if node == head:
        return word
    terminal = _read(context, (buckets + bucket) & _U64, 8)
    while _read(context, node + 0x10, 4) != category:
        if node == terminal:
            return word
        node = _read(context, node + 8, 8)
    if not node or node == head:
        return word
    begin = _read(context, node + 0x18, 8)
    end = _read(context, node + 0x20, 8)
    while begin != end:
        word = _call(calls, 0x1414C47E0, (begin, word), width=4)
        begin = (begin + 12) & _U64
    return word


def replay_building_ai_stat(
    context: ReplayTaskRebuildStorage,
    subject: int,
    *,
    calls: ReplayTaskRebuildCalls,
) -> int:
    """Exact83B1412b6520 tail range, category1 modifier lookup after raw ADDSS."""
    _validate(context, calls, subject)
    master = (_read(context, subject + 0x10, 8) - 0x6A586EB28AC201FC - 0xCF19788B2554E70) & _U64
    word = add_binary32(_read(context, subject + 0x75C, 4), _read(context, master + 0x70, 4))
    return _call(calls, 0x1412428D0, (subject, 1, word), width=4)


def bind_replay_unit_ai_support(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
) -> ReplayTaskRebuildCalls:
    """Bind the complete position/reserve/timer/stat bodies and exact building range."""
    _validate(context, calls)

    def dispatch(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        arities = {
            0x140C285F0: 5,
            0x1402BA470: 2,
            0x140D1A2F0: 1,
            0x1414C47E0: 2,
            0x1412428D0: 3,
            0x1412B6520: 1,
        }
        if target not in arities:
            if calls.call is None:
                raise UnresolvedReplayTaskRebuild(f"reached{target:x} is unavailable")
            return calls.call(target, args, data)
        # The timer wrapper tail-forwards raw RDX, although this leaf consumes
        # only RCX. Direct calls may supply the consumed argument alone.
        expected = (1, 2) if target == 0x140D1A2F0 else (arities[target],)
        if len(args) not in expected or data is not None:
            raise ValueError("malformed UnitAI support call")
        if target == 0x140C285F0:
            return construct_replay_ai_position(context, *args)
        if target == 0x1402BA470:
            reserve_replay_ai_classes(context, *args, calls=bound)
        elif target == 0x140D1A2F0:
            if len(args) == 2:
                _unsigned(args[1], 8, "forwarded idle callback RDX")
            update_replay_ai_idle_time(context, args[0], calls=bound)
        elif target == 0x1414C47E0:
            return apply_replay_stat_record(context, *args)
        elif target == 0x1412428D0:
            return apply_replay_object_stat(context, *args, calls=bound)
        else:
            return replay_building_ai_stat(context, *args, calls=bound)
        return None

    bound = ReplayTaskRebuildCalls(dispatch)
    return bound
