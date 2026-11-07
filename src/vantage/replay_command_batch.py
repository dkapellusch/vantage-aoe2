"""Nine complete batch/cleanup/selector/Result/clock caller bodies.

Sources: world-formation-batch-{children-,}source-v1. Serialization, current
virtuals/imports, counter, allocation, diagnostic and Result children are real
mandatory capabilities; this module supplies no initialized manager or stream.
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
    _unsigned,
    _write,
)
from .replay_unit_ai_base import _validate
from .replay_unit_ai_construction import _local
from .replay_unit_ai_map import ReplayUnitAIMapAtomics, _release

_U32, _U64 = (1 << 32) - 1, (1 << 64) - 1
_BEGIN, _END, _ROW, _VECTOR = 0x140E08860, 0x140E07CC0, 0x1402A8630, 0x140E0B2A0
_LENGTH, _GET, _SELECT, _RESULT, _CLOCK = (
    0x140E0B920,
    0x14098F250,
    0x140942110,
    0x14096B890,
    0x140A71140,
)
_FREE, _COMPARE, _CLEAR = 0x142D6BAB4, 0x142D6E3E7, 0x1402BD7F0
_SIGN64, _INF64, _INVALID64 = 1 << 63, 0x7FF0000000000000, 0xFFF8000000000000


@dataclass(frozen=True, slots=True)
class ReplayCommandBatchProfile:
    """Explicit live prefixes28/28/50/B0h, with no inferred initialization.

    Cleanup HOME20 is mapped only when Watson is reached; Result30..4f
    diagnostic string only for nonzero status. End38 Result, record68/vector70,
    descriptor88/vector98 and HOME20/28 share one seeded B0h prefix. Physical
    cookie/save tails and unused registers/stack/EH/concurrency are excluded.
    """

    row_cleanup: bytes
    batch_cleanup: bytes
    result: bytes
    end: bytes

    def __post_init__(self) -> None:
        if any(
            type(value) is not bytes or len(value) != size
            for value, size in (
                (self.row_cleanup, 0x28),
                (self.batch_cleanup, 0x28),
                (self.result, 0x50),
                (self.end, 0xB0),
            )
        ):
            raise ValueError("explicit28/28/50/B0-hex-byte batch seeds required")


def _invoke(
    calls: ReplayTaskRebuildCalls,
    target: int,
    args: tuple[int, ...],
) -> int | None:
    if calls.call is None:
        raise UnresolvedReplayTaskRebuild(f"reached{target:x} is unavailable")
    return calls.call(target, tuple(value & _U64 for value in args), None)


def _round64(magnitude: int, exponent: int, negative: bool) -> int:
    """Exact integer magnitude*2**exponent rounded once to binary64, RN-even."""
    sign = _SIGN64 if negative else 0
    if not magnitude:
        return sign
    shift = max(magnitude.bit_length() - 53, -1074 - exponent)
    if shift > 0:
        rounded, remainder = divmod(magnitude, 1 << shift)
        half = 1 << (shift - 1)
        if remainder > half or (remainder == half and rounded & 1):
            rounded += 1
    else:
        rounded = magnitude << -shift
    if not rounded:
        return sign
    scale = exponent + shift
    top = rounded.bit_length() - 1 + scale
    if top > 1023:
        return sign | _INF64
    if top < -1022:
        return sign | rounded << (scale + 1074)
    align = rounded.bit_length() - 53
    significand = rounded >> align if align >= 0 else rounded << -align
    return sign | (top + 1023) << 52 | significand & ((1 << 52) - 1)


def _parts64(word: int) -> tuple[int, int]:
    exponent, fraction = word >> 52 & 0x7FF, word & ((1 << 52) - 1)
    return (fraction | (1 << 52), exponent - 1075) if exponent else (fraction, -1074)


def _unsigned64_double(word: int) -> int:
    if word < _SIGN64:
        return _round64(word, 0, False)
    half = _round64((word >> 1) | (word & 1), 0, False)
    significand, exponent = _parts64(half)
    # The source ADDSD of two equal finite nonnegative conversion results.
    return _round64(significand, exponent + 1, False)


def _multiply64(left: int, right: int) -> int:
    """Legacy MULSD, destination-first quiet NaNs, signed zero and subnormals."""
    a, b = left & (_SIGN64 - 1), right & (_SIGN64 - 1)
    if a > _INF64:
        return left | (1 << 51)
    if b > _INF64:
        return right | (1 << 51)
    sign = (left ^ right) & _SIGN64
    if a == _INF64 or b == _INF64:
        return _INVALID64 if not a or not b else sign | _INF64
    x, xe = _parts64(left)
    y, ye = _parts64(right)
    return _round64(x * y, xe + ye, bool(sign))


def _cvtt64(word: int) -> int:
    exponent = word >> 52 & 0x7FF
    if exponent == 0x7FF:
        return _SIGN64
    significand, scale = _parts64(word)
    magnitude = significand << scale if scale >= 0 else significand >> -scale
    value = -magnitude if word & _SIGN64 else magnitude
    return value & _U64 if -_SIGN64 <= value < _SIGN64 else _SIGN64


def _clock(context: ReplayTaskRebuildStorage, calls: ReplayTaskRebuildCalls) -> int:
    counter = _call(calls, 0x140973210, (), width=8)
    value = _unsigned64_double(counter)
    value = _multiply64(value, _read(context, 0x14428FA88, 8))
    value = _multiply64(value, _read(context, 0x1431FED08, 8))
    return _cvtt64(value)


def _watson_at(
    context: ReplayTaskRebuildStorage,
    channel: ReplayTaskRebuildCalls,
    frame: int,
) -> None:
    _write(context, frame + 0x20, 8, 0)
    target = _read(context, 0x14319A060, 8)
    _invoke(channel, target, (0, 0, 0, 0, (frame + 0x20) & _U64))
    raise UnresolvedReplayTaskRebuild("batch Watson returned before source INT3")


def _watson(
    context: ReplayTaskRebuildStorage,
    channel: ReplayTaskRebuildCalls,
    bind_local: LocalBinding,
    seed: bytes,
) -> None:
    with _local(memoryview(bytearray(seed)), bind_local) as frame:
        _watson_at(context, channel, frame)


def _row(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    watson: ReplayTaskRebuildCalls,
    subject: int,
    *,
    bind_local: LocalBinding,
    seed: bytes,
) -> None:
    begin = _read(context, subject, 8)
    if not begin:
        return
    size = _read(context, subject + 0x10, 8) - begin & _U64
    allocation = begin
    if size >= 0x1000:
        allocation = _read(context, begin - 8, 8)
        size = size + 0x27 & _U64
        if (begin - allocation - 8) & _U64 > 31:
            _watson(context, watson, bind_local, seed)
    _call(calls, _FREE, (allocation, size))
    for offset in (0, 8, 16):
        _write(context, subject + offset, 8, 0)


def _vector(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    watson: ReplayTaskRebuildCalls,
    subject: int,
    *,
    bind_local: LocalBinding,
    seed: bytes,
) -> None:
    begin = _read(context, subject, 8)
    if not begin:
        return
    end = _read(context, subject + 8, 8)
    cursor = begin
    while cursor != end:
        _call(calls, _ROW, (cursor,))
        cursor = cursor + 32 & _U64
    begin = _read(context, subject, 8)
    size = (_read(context, subject + 0x10, 8) - begin) & (_U64 - 31)
    allocation = begin
    if size >= 0x1000:
        allocation = _read(context, begin - 8, 8)
        size = size + 0x27 & _U64
        if (begin - allocation - 8) & _U64 > 31:
            _watson(context, watson, bind_local, seed)
    _call(calls, _FREE, (allocation, size))
    for offset in (0, 8, 16):
        _write(context, subject + offset, 8, 0)


def _rows(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    owner: int,
    active: int,
) -> None:
    end = _read(context, owner + 0x26A8, 8)
    cursor = _read(context, owner + 0x26A0, 8)
    if cursor != end:
        while True:
            _call(calls, _ROW, (cursor,))
            cursor = cursor + 32 & _U64
            if cursor == end:
                break
        _write(context, owner + 0x26A8, 8, _read(context, owner + 0x26A0, 8))
    _write(context, owner + 0x26B8, 1, active)


def _type_descriptor(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    node: int,
) -> int:
    receiver = node - 0x28 & _U64
    vptr = _read(context, receiver, 8)
    target = _read(context, vptr + 8, 8)
    return _call(calls, target, (receiver,), width=8)


def _select(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    tree: int,
    key: int,
) -> int:
    node = _read(context, tree + 8, 8)
    sentinel = tree + 0x20 & _U64
    if node == sentinel:
        return 0
    query = key + 8 & _U64
    while True:
        descriptor = _type_descriptor(context, calls, node) + 8 & _U64
        compared = _call(calls, _COMPARE, (descriptor, query), width=8) & _U32
        if compared == 0:
            break
        compared = _call(calls, _COMPARE, (descriptor, query), width=8) & _U32
        node = _read(context, node + (16 if compared & 0x80000000 else 8), 8)
        if node == sentinel:
            return 0
    while True:
        candidate = _read(context, node + 8, 8)
        if candidate != sentinel:
            following = _read(context, candidate + 16, 8)
            while following != sentinel:
                candidate = following
                following = _read(context, following + 16, 8)
        else:
            candidate = _read(context, node + 24, 8)
            if node == _read(context, candidate + 8, 8):
                while True:
                    if candidate == tree:
                        return node - 0x28 & _U64
                    previous = candidate
                    candidate = _read(context, candidate + 24, 8)
                    if previous != _read(context, candidate + 8, 8):
                        break
        if candidate == sentinel:
            return node - 0x28 & _U64
        descriptor = _type_descriptor(context, calls, candidate) + 8 & _U64
        compared = _call(calls, _COMPARE, (descriptor, query), width=8) & _U32
        if compared == 0:
            node = candidate
            continue
        _call(calls, _COMPARE, (descriptor, query))  # Required second call; result unused.
        return node - 0x28 & _U64


def _result_error(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    watson: ReplayTaskRebuildCalls,
    result: int,
    *,
    frame: int,
) -> None:
    _call(calls, 0x140A08AE0, (result, (frame + 0x30) & _U64))
    capacity = _read(context, frame + 0x48, 8)
    pointer = _read(context, frame + 0x30, 8)  # CMOVA memory operand is always fetched.
    selected = pointer if capacity > 15 else frame + 0x30 & _U64
    _call(calls, 0x1408FCD50, (selected,))
    capacity = _read(context, frame + 0x48, 8)
    if capacity > 15:
        size = capacity + 1 & _U64
        pointer = _read(context, frame + 0x30, 8)
        allocation = pointer
        if size >= 0x1000:
            size = size + 0x27 & _U64
            allocation = _read(context, pointer - 8, 8)
            if (pointer - allocation - 8) & _U64 > 31:
                _watson_at(context, watson, frame)
        _call(calls, _FREE, (allocation, size))
    _write(context, result + 0x28, 1, 1)


def _end(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    error: ReplayTaskRebuildCalls,
    atomics: ReplayUnitAIMapAtomics,
    owner: int,
    count: int,
    *,
    frame: int,
) -> None:
    record, vector, result = frame + 0x68, frame + 0x70, frame + 0x38
    source = owner + 0x26A0 & _U64
    _write(context, record, 16, 0)
    _write(context, frame + 0x78, 16, 0)
    _write(context, record, 1, 0x62)
    _write(context, vector, 16, 0)
    _write(context, frame + 0x80, 8, 0)
    if count > 0x7FFFFFFFFFFFFFF:
        _call(calls, _LENGTH, ())
        raise UnresolvedReplayTaskRebuild("batch length child returned before source INT3")
    byte_count = count << 5 & _U64
    allocation = _call(calls, 0x1402A94D0, (byte_count,), width=8)
    _write(context, vector, 8, allocation)
    _write(context, frame + 0x80, 8, allocation + byte_count)
    cursor = allocation
    remaining = count
    while remaining:
        for offset, width in ((0, 8), (8, 8), (16, 8), (24, 4)):
            _write(context, cursor + offset, width, 0)
        cursor = cursor + 32 & _U64
        remaining -= 1
    _write(context, frame + 0x78, 8, cursor)
    if (vector & _U64) != source:
        _call(calls, _VECTOR, (vector & _U64,))
        for source_offset, home in ((0, 0x70), (8, 0x78), (16, 0x80)):
            _write(context, frame + home, 8, _read(context, source + source_offset, 8))
        for source_offset in (0, 8, 16):
            _write(context, source + source_offset, 8, 0)
    _write(context, frame + 0x88, 16, 0)
    _write(context, frame + 0x90, 4, 0)
    _write(context, frame + 0x88, 8, 0x143218B60)
    _write(context, frame + 0x98, 16, 0)
    _write(context, frame + 0xA8, 8, 0)
    registry = _call(calls, _GET, (), width=8)
    provider = _call(calls, _SELECT, (registry, 0x144121990), width=8)
    if provider:
        vptr = _read(context, provider, 8)
        target = _read(context, vptr + 0x18, 8)
        _call(calls, target, (provider, result & _U64, (frame + 0x88) & _U64, record & _U64))
    else:
        value = _call(calls, 0x142D6E3ED, (0x144121998, 0x144C9CDB0), width=8)
        _write(context, frame + 0x28, 8, value)
        _write(context, frame + 0x20, 8, 0x1431FAC58)
        _invoke(
            error,
            0x140A08840,
            (result & _U64, 0, 0x1431FAC00, 0x2F5, (frame + 0x20) & _U64, (frame + 0x28) & _U64),
        )
    _call(calls, _RESULT, (result & _U64,))
    control = _read(context, result + 0x20, 8)
    if control:
        _release(context, control, calls, atomics)
    _call(calls, _CLEAR, (result & _U64,))
    receiver = _read(context, owner + 0x2E8, 8)
    size = _read(context, frame + 0xA0, 4)
    size = size - _read(context, frame + 0x98, 4) & _U32
    vptr = _read(context, receiver, 8)
    data = _read(context, frame + 0x98, 8)
    target = _read(context, vptr + 0xE8, 8)
    _call(calls, target, (receiver, data, size))
    clock = _read(context, owner + 0x358, 8)
    now = _call(calls, _CLOCK, (), width=8) & _U32
    _write(context, clock + 0x50, 4, now)
    _call(calls, _ROW, ((frame + 0x98) & _U64,))
    _call(calls, _VECTOR, (vector & _U64,))
    _rows(context, calls, owner, 0)


def bind_replay_command_batch(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    *,
    watson_home_calls: ReplayTaskRebuildCalls,
    error_home_calls: ReplayTaskRebuildCalls,
    atomics: ReplayUnitAIMapAtomics,
    bind_local: LocalBinding,
    profile: ReplayCommandBatchProfile,
    mxcsr: int,
) -> ReplayTaskRebuildCalls:
    """Own9 bodies with source live homes/current calls and opaque delegation.

    Watson gets4zero registers+HOME20 address; variadic constructor gets its
    first4register args+HOME20/28 addresses. Clock/getter have zero effective
    explicit args. Counter/deeper children remain mandatory actual effects;
    unclosed incidental-register consumption is excluded, not fabricated.
    Binary64 arithmetic is integer RN-even with masked exceptions/DAZFTZ off;
    FP flags, native cookies/faults/EH/concurrency and escaped locals excluded.
    """
    for channel in (calls, watson_home_calls, error_home_calls):
        _validate(context, channel)
    _unsigned(mxcsr, 4, "MXCSR")
    if (
        mxcsr != 0x1F80
        or not isinstance(atomics, ReplayUnitAIMapAtomics)
        or not callable(bind_local)
        or not isinstance(profile, ReplayCommandBatchProfile)
    ):
        raise ValueError("actual batch atomic/local effects and MXCSR1f80 profile required")
    arities = {
        _BEGIN: 1,
        _END: 1,
        _ROW: 1,
        _VECTOR: 1,
        _LENGTH: 0,
        _GET: 0,
        _SELECT: 2,
        _RESULT: 1,
        _CLOCK: 0,
    }

    def dispatch(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        if target not in arities:
            if calls.call is None:
                raise UnresolvedReplayTaskRebuild(f"reached{target:x} is unavailable")
            return calls.call(target, args, data)
        if len(args) != arities[target] or data is not None:
            raise ValueError("malformed command batch call")
        _validate(context, calls, *args)
        if target == _GET:
            return _read(context, 0x144287608, 8)
        if target == _CLOCK:
            return _clock(context, bound)
        if target == _SELECT:
            return _select(context, bound, *args)
        if target == _LENGTH:
            _call(bound, 0x142D66698, (0x1436794B0,))
            raise UnresolvedReplayTaskRebuild("batch length error returned before source INT3")
        if target == _BEGIN:
            _rows(context, bound, args[0], 1)
        elif target == _ROW:
            _row(
                context,
                bound,
                watson_home_calls,
                args[0],
                bind_local=bind_local,
                seed=profile.row_cleanup,
            )
        elif target == _VECTOR:
            _vector(
                context,
                bound,
                watson_home_calls,
                args[0],
                bind_local=bind_local,
                seed=profile.batch_cleanup,
            )
        elif target == _RESULT:
            if _read(context, args[0] + 0x18, 8):
                with _local(memoryview(bytearray(profile.result)), bind_local) as frame:
                    _result_error(context, bound, watson_home_calls, args[0], frame=frame)
            else:
                _write(context, args[0] + 0x28, 1, 1)
        else:
            end = _read(context, args[0] + 0x26A8, 8)
            begin = _read(context, args[0] + 0x26A0, 8)
            count = _signed((end - begin) & _U64, 8) >> 5 & _U64
            if count:
                with _local(memoryview(bytearray(profile.end)), bind_local) as frame:
                    _end(context, bound, error_home_calls, atomics, args[0], count, frame=frame)
            else:
                _rows(context, bound, args[0], 0)
        return None

    bound = ReplayTaskRebuildCalls(dispatch)
    return bound
