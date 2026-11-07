"""Complete568B/143instruction decoder wrapper14178ae30.

Source: replay-file-read-seek-contract-v1. Current fmin/copy and inner codec
effects are mandatory. No initialized ring/state or successful codec supplied.
"""

from __future__ import annotations

import struct
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

_U64 = (1 << 64) - 1
_U32 = (1 << 32) - 1
_WRAPPER, _CORE, _COPY, _FMIN_IAT = 0x14178AE30, 0x14257FC20, 0x142D6E3B1, 0x143199E80


@dataclass(frozen=True, slots=True)
class ReplayFileDecoderProfile:
    """Explicit68h logical prefix, excluding cookie68/native save areas.

    Inner HOME20Q/28Q/30D, saved pointer40/48/50Q and count58/60Q are live
    current backing. Incoming HOME5/6/7/8 locations are supplied separately.
    Unwritten bytes retain seed; physical frame adjacency is not inferred.
    """

    frame: bytes

    def __post_init__(self) -> None:
        if type(self.frame) is not bytes or len(self.frame) != 0x68:
            raise ValueError("explicit68-hex-byte decoder-wrapper seed required")


def _invoke(
    calls: ReplayTaskRebuildCalls,
    target: int,
    args: tuple[int, ...],
) -> int | None:
    if calls.call is None:
        raise UnresolvedReplayTaskRebuild(f"reached{target:x} is unavailable")
    return calls.call(target, tuple(value & _U64 for value in args), None)


def _raw(value: int | None, description: str) -> int:
    if value is None:
        raise ValueError(f"{description} requires its raw word at source consumption")
    _unsigned(value, 8, description)
    return value


def _double_u32(value: int) -> int:
    # Both source CVTSI2SD64 inputs are zero-extended EAX: all are exact in f64.
    return int(struct.unpack("<Q", struct.pack("<d", float(value & _U32)))[0])


def _cvtt64(word: int | None) -> int:
    """Masked CVTTSD2SI64, including integer-indefinite; no MXCSR flag model."""
    bits = _raw(word, "fmin XMM0 binary64 result")
    exponent, fraction = bits >> 52 & 0x7FF, bits & ((1 << 52) - 1)
    if exponent == 0x7FF:
        return 1 << 63
    significand = fraction | (1 << 52) if exponent else fraction
    shift = exponent - 1075 if exponent else -1074
    magnitude = significand << shift if shift >= 0 else significand >> -shift
    value = -magnitude if bits >> 63 else magnitude
    return value & _U64 if -(1 << 63) <= value < 1 << 63 else 1 << 63


def _decode(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    math_calls: ReplayTaskRebuildCalls,
    core_home_calls: ReplayTaskRebuildCalls,
    input_base: int,
    input_offset: int,
    input_count: int,
    output_base: int,
    offset_home: int,
    output_count_home: int,
    state_home: int,
    final_home: int,
    *,
    frame: int,
) -> int:
    state = _read(context, state_home, 8)
    offset = _signed(_read(context, offset_home, 4), 4) & _U64
    output_count = _read(context, output_count_home, 8)
    input_offset &= _U32
    held_input_base = input_base
    _write(context, frame + 0x40, 8, input_base)
    pending = (_read(context, state + 0xA0BC, 4) - _read(context, state + 0xA0B8, 4)) & _U32
    _write(context, frame + 0x48, 8, output_base)
    _write(context, frame + 0x50, 8, input_count)
    consumed, copied = 0, 0
    pending &= 0x7FFF

    def minimum(first: int, second: int) -> int | None:
        target = _read(context, _FMIN_IAT, 8)
        return _invoke(math_calls, target, (_double_u32(first), _double_u32(second)))

    def finish() -> int:
        _write(context, input_count, 4, consumed)
        _write(context, output_count, 4, copied)
        return 0

    if pending:
        raw = minimum(pending, (_read(context, output_count, 4) - offset) & _U32)
        read_index = _read(context, state + 0xA0B8, 4)
        destination = (offset + output_base) & _U64
        copied = _cvtt64(raw)
        _call(calls, _COPY, (destination, (state + 0x20B8 + read_index) & _U64, copied & _U32))
        read_index = _read(context, state + 0xA0B8, 4)
        offset = (offset + copied) & _U32
        held_input_base = _read(context, frame + 0x40, 8)
        _write(context, state + 0xA0B8, 4, (read_index + copied) & 0x7FFF)

    if offset & _U32 == _read(context, output_count, 4):
        return finish()
    while True:
        if _read(context, state + 0xA0C0, 1):
            return finish()
        write_index = _read(context, state + 0xA0BC, 4)
        remaining = (_read(context, input_count, 4) - input_offset) & _U32
        _write(context, frame + 0x58, 8, _signed(remaining, 4) & _U64)
        capacity = (0x8000 - write_index) & _U32
        final = _read(context, final_home, 4)
        _write(context, frame + 0x60, 8, capacity)
        _write(context, frame + 0x30, 4, 0 if final else 2)
        _write(context, frame + 0x28, 8, (frame + 0x60) & _U64)
        input_pointer = (held_input_base + _signed(input_offset, 4)) & _U64
        _write(context, frame + 0x20, 8, (state + 0x20B8 + write_index) & _U64)
        raw = _invoke(
            core_home_calls,
            _CORE,
            (
                state,
                input_pointer,
                (frame + 0x58) & _U64,
                (state + 0x20B8) & _U64,
                (frame + 0x20) & _U64,
                (frame + 0x28) & _U64,
                (frame + 0x30) & _U64,
            ),
        )
        status = _raw(raw, "inner codec EAX result") & _U32
        if status & (1 << 31):
            return 0xFFFFFFFE
        actual_input = _read(context, frame + 0x58, 8)
        produced = _read(context, frame + 0x60, 8)
        input_offset = (input_offset + actual_input) & _U32
        consumed = (consumed + actual_input) & _U32
        write_index = _read(context, state + 0xA0BC, 4)
        _write(context, state + 0xA0BC, 4, (write_index + produced) & 0x7FFF)
        if produced:
            raw = minimum(produced, (_read(context, output_count, 4) - offset) & _U32)
            read_index = _read(context, state + 0xA0B8, 4)
            chunk = _cvtt64(raw)
            destination = (_signed(offset & _U32, 4) + _read(context, frame + 0x48, 8)) & _U64
            _call(
                calls,
                _COPY,
                (
                    destination,
                    (state + 0x20B8 + read_index) & _U64,
                    chunk & _U32,
                ),
            )
            read_index = _read(context, state + 0xA0B8, 4)
            copied = (copied + chunk) & _U32
            offset = (offset + chunk) & _U32
            _write(context, state + 0xA0B8, 4, (read_index + chunk) & 0x7FFF)
            input_count = _read(context, frame + 0x50, 8)
        if status == 0:
            _write(context, state + 0xA0C0, 1, 1)
            return finish()
        if status == 1:
            return finish()
        held_input_base = _read(context, frame + 0x40, 8)
        if offset & _U32 == _read(context, output_count, 4):
            return finish()


def bind_replay_file_decoder_homes(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    *,
    math_calls: ReplayTaskRebuildCalls,
    core_home_calls: ReplayTaskRebuildCalls,
    bind_local: LocalBinding,
    profile: ReplayFileDecoderProfile,
) -> ReplayTaskRebuildCalls:
    """Own complete14178ae30 through4registers+4current HOME LOCATIONS.

    Effective args: inputbase,raw inputoffset,inputcountPTR,outputbase, then
    addresses HOME5offsetDWORD/HOME6outputcountPTR/HOME7statePTR/HOME8flagDWORD.
    Entry reads7Q then5signedDWORD then6Q; flag8DWORD is current each iteration.
    This ABI composes with replay_file_read's explicit decoder_calls channel.

    Separate math_calls samples current fminIAT and receives binary64 words in
    effectiveXMM0/XMM1 order; its raw returned word is XMM0, not nativeRAX.
    CVTT consumes it after the source's current read-index read. Conversions
    model masked SIMD integer-indefinite; MXCSR status/unmasked faults excluded.
    COPY142d6e3b1 is an actual required child through calls, with ignored return.

    CoreHOME calls get4register args then addresses20/28/30, never eager values.
    No core/fmin/copy success, initialized ring, pointer data or zero state is
    inferred. Negative innerEAX returnslogicalEAXfffffffe without final counts;
    normal paths store inputDWORD thenoutputDWORD and returnlogicalEAX0. Both
    count upperDWORDs stay current. No dynamic iteration cap is introduced.

    Logical68h locals retain seed, callbacks and admitted coherent aliases.
    Finite valid backing/source progress are premises; physicalprologue/cookie/
    register saves/nativefault/EH/concurrency/escapedframe equivalence excluded.
    Unknown targets delegate original args/data unchanged or refuse at reach.
    """
    _validate(context, calls)
    _validate(context, math_calls)
    _validate(context, core_home_calls)
    if not callable(bind_local) or not isinstance(profile, ReplayFileDecoderProfile):
        raise ValueError("explicit decoder-wrapper local binding/profile required")

    def dispatch(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        if target != _WRAPPER:
            if calls.call is None:
                raise UnresolvedReplayTaskRebuild(f"reached{target:x} is unavailable")
            return calls.call(target, args, data)
        if len(args) != 8 or data is not None:
            raise ValueError("decoder wrapper requires4registers and4HOMElocations")
        _validate(context, calls, *args)
        with _local(memoryview(bytearray(profile.frame)), bind_local) as frame:
            return _decode(context, calls, math_calls, core_home_calls, *args, frame=frame)

    return ReplayTaskRebuildCalls(dispatch)
