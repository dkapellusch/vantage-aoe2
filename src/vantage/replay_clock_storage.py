"""Addressed build54800 clock methods used by the BaseWorld scheduler.

Complete bodies: c40 advance169B, f50 rate6B, f70 time4B, fa0 set4B (140e68
prefixes), plus factor14097363022B. world-clock-source-v1 retains source. Calls
use raw binary32 words for XMM scalar inputs/results. Recorded replay deltas
are applied separately by the World body; this is its actual clock storage,
including the ordinary/debug advance path, not a replay-step scheduler.
"""

from __future__ import annotations

from .replay_binary32 import _round, add_binary32, divide_binary32, multiply_binary32
from .replay_task_containers import _cvtt64
from .replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
    _call,
    _read,
    _unsigned,
    _write,
)
from .replay_unit_ai_base import _validate

_ADVANCE = 0x140E68C40
_RATE, _TIME, _SET_TIME = 0x140E68F50, 0x140E68F70, 0x140E68FA0
_FACTOR = 0x140973630
_DEBUG, _EXTERNAL, _ONE = 0x1442C3FC4, 0x1442846E8, 0x1436A0294
_U32 = (1 << 32) - 1


def _narrow(word: int) -> int:
    """Low CVTPD2PS result, including signed zero and quiet NaN payload."""
    sign = (word >> 32) & 0x80000000
    exponent, fraction = word >> 52 & 0x7FF, word & ((1 << 52) - 1)
    if exponent == 0x7FF:
        return sign | 0x7F800000 | ((fraction >> 29) | 0x400000 if fraction else 0)
    magnitude = fraction | (1 << 52) if exponent else fraction
    return _round(magnitude, exponent - 1075 if exponent else -1074, bool(sign))


def _factor(context: ReplayTaskRebuildStorage, external: int) -> int:
    word = _read(context, external + 0x20, 8)
    numerator = _read(context, 0x1436A02E0, 4)
    return divide_binary32(numerator, _narrow(word))


def _advance(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    clock: int,
    delta: int,
) -> None:
    debug = _read(context, _DEBUG, 4)
    if not debug and _read(context, clock + 8, 4) not in (1, 2):
        return
    external = _read(context, _EXTERNAL, 8)
    factor = _call(calls, _FACTOR, (external,), width=4) if external else _read(context, _ONE, 4)
    # Debug ignores mode and doubles the held input, without applying rate.
    doubled = add_binary32(delta, delta) if debug else 0
    _write(context, clock + 0x14, 4, factor)
    rate = multiply_binary32(factor, _read(context, clock + 0x10, 4))
    increment = _cvtt64(doubled) if debug else 0
    _write(context, clock + 0xC, 4, rate)
    if not debug:
        increment = _cvtt64(multiply_binary32(rate, delta))
    _write(context, clock + 0x18, 4, _read(context, clock + 0x18, 4) + increment)


def bind_replay_clock_storage(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    *,
    mxcsr: int,
) -> ReplayTaskRebuildCalls:
    """Bind five complete clock/factor methods to current owned storage.

    f50(clock) returns the raw XMM0 binary32 word; f70(clock) returns raw EAX.
    fa0(clock,value) stores low EDX; c40(clock,delta_bits) consumes low XMM1.
    Both setters return None: incidental RAX is outside this effective ABI.
    Known arguments are raw u64 words before their native width truncation.
    140973630(external) reads binary64 at+20, then the current numerator word,
    narrows the held binary64 and divides once in binary32. Its raw result is
    XMM0. Actual lower routing must reenter this binding for owned child calls.

    c40 reads the debug flag once, mode only on its ordinary path, and the
    current external pointer when admitted. A nonnull external requires actual
    140973630(pointer) returning raw binary32. A null pointer reads the current
    constant word; this binding initializes no globals or clock fields. Held
    receiver, delta and factor survive synchronous child mutations/reentry;
    scale and accumulator reads remain current in literal source order.

    Masked nearest-even MXCSR with DAZ/FTZ off is required. CVTT truncates to
    signed64 independently; NaN/overflow yield INT64_MIN, whose low DWORD is
    zero. FP status/traps, upper XMM lanes, physical stack, unwind, native
    faults and threads are excluded. Missing backing/providers refuse at the
    reached operation; prior effects remain. Unknown calls delegate unchanged.
    """
    _validate(context, calls)
    _unsigned(mxcsr, 4, "MXCSR")
    if mxcsr & ~0x3F != 0x1F80:
        raise ValueError("masked nearest-even MXCSR, DAZ/FTZ off required")

    def dispatch(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        if target not in (_ADVANCE, _RATE, _TIME, _SET_TIME, _FACTOR):
            if calls.call is None:
                raise UnresolvedReplayTaskRebuild(f"reached{target:x} is unavailable")
            return calls.call(target, args, data)
        arity = 2 if target in (_ADVANCE, _SET_TIME) else 1
        if len(args) != arity or data is not None:
            raise ValueError("malformed addressed clock call")
        _validate(context, calls, *args)
        clock = args[0]
        if target == _FACTOR:
            return _factor(context, clock)
        if target == _RATE:
            return _read(context, clock + 0xC, 4)
        if target == _TIME:
            return _read(context, clock + 0x18, 4)
        if target == _SET_TIME:
            _write(context, clock + 0x18, 4, args[1])
        else:
            _advance(context, calls, clock, args[1] & _U32)
        return None

    return ReplayTaskRebuildCalls(dispatch)
