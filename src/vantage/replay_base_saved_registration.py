"""Build54800 complete1462B Base registration caller and79B helper graph.

Authority: base-saved-registration-frontier-source-v1. Actual RTTI and current
virtual effects remain mandatory. The positive callback has genuine mixed FP
positions, represented explicitly rather than as an integer-register call.
The B0 logical frame preserves current encoded scratch and live local aliases.
Native saved registers/cookies/stack identity, faults/EH/concurrency, FP status
and unmasked traps are excluded. Numerical branches use masked MXCSR1f80 with
DAZ/FTZ off; no host floating-point conversion is used. This is not full restore.
"""

from __future__ import annotations

from collections.abc import Callable
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

_U32 = (1 << 32) - 1
_U64 = (1 << 64) - 1
_ENTRY = 0x1412488E0
_RTTI = 0x142D6E3D5
_HELPERS = (0x140D6A940, 0x140D6ACC0, 0x141603FF0, 0x140A81440, 0x1410B9EE0, _RTTI)


@dataclass(frozen=True, slots=True)
class ReplayBaseSavedRegistrationScratch:
    """Explicit B0-byte logical post-prologue frame, live until exit.

    Encoded words at98/a0/a8 and40 alias their subsequent reads; BYTE98 writes
    retain the actual preceding seven bytes. Stack argument slots20/28/30 use
    their original widths. Saved-register spills and physical stack aliases
    are excluded; unwritten bytes retain these caller-supplied seeds.
    """

    frame: bytes

    def __post_init__(self) -> None:
        if type(self.frame) is not bytes or len(self.frame) != 0xB0:
            raise ValueError("explicit B0-byte Base registration frame required")


@dataclass(frozen=True, slots=True)
class ReplayBaseSavedRegistrationFPCall:
    """Actual positional ABI at141248e3e; R8 itself holds the call target.

    xmm2/xmm3 are raw low binary32 words for positional arguments3/4.
    stack5/6/7 describe the caller's stores, also available in live storage
    at stack_address(+0/+8/+16). A provider needing current stack contents
    must consume that backing in its own callee phase. Upper DWORD padding
    of stack5/6 is not an extra inferred integer argument.
    """

    target: int
    receiver: int
    command: int
    xmm2_u32: int
    xmm3_u32: int
    stack5_u32: int
    stack6_u32: int
    stack7_address: int
    stack_address: int

    def __post_init__(self) -> None:
        for value in (self.target, self.receiver, self.stack7_address, self.stack_address):
            _unsigned(value, 8, "mixed-FP pointer")
        for value in (self.command, self.xmm2_u32, self.xmm3_u32, self.stack5_u32, self.stack6_u32):
            _unsigned(value, 4, "mixed-FP raw DWORD")


@dataclass(frozen=True, slots=True)
class ReplayBaseSavedRegistrationFP:
    """Actual mixed-FP effect provider, or unavailable until reached."""

    call: Callable[[ReplayBaseSavedRegistrationFPCall], None] | None

    def __post_init__(self) -> None:
        if self.call is not None and not callable(self.call):
            raise ValueError("actual mixed-FP effect provider required")


def _cvtt32(word: int) -> int:
    """Masked CVTTSS2SI32 of raw binary32, including indefinite80000000."""
    exponent = word >> 23 & 255
    if exponent == 255:
        return 0x80000000
    if exponent < 127:
        return 0
    significand = (word & 0x7FFFFF) | 0x800000
    shift = exponent - 150
    value = significand << shift if shift >= 0 else significand >> -shift
    negative = bool(word & 0x80000000)
    if value > (0x80000000 if negative else 0x7FFFFFFF):
        return 0x80000000
    return (-value if negative else value) & _U32


def _stage(
    context: ReplayTaskRebuildStorage,
    slot: int,
    word: int,
    operations: tuple[tuple[str, int], ...],
) -> None:
    _write(context, slot, 8, word)
    for operation, literal in operations:
        current = _read(context, slot, 8)
        if operation == "xor":
            value = current ^ literal
        elif operation == "add":
            value = current + literal
        else:
            value = current - literal
        _write(context, slot, 8, value)


def _master(context: ReplayTaskRebuildStorage, subject: int, slot: int) -> int:
    _stage(
        context,
        slot,
        _read(context, subject + 16, 8),
        (
            ("sub", 0x6A586EB28AC201FC),
            ("sub", 0x0CF19788B2554E70),
        ),
    )
    return _read(context, slot, 8)


def _reject(context: ReplayTaskRebuildStorage, master: int) -> None:
    _write(context, master + 0x1D4, 4, 1)


def _positive(
    context: ReplayTaskRebuildStorage,
    subject: int,
    frame: int,
    held_begin: int,
    offset: int,
    bit: int,
    fp_calls: ReplayBaseSavedRegistrationFP,
) -> None:
    recipient = _read(context, held_begin + offset, 8)
    vptr = _read(context, recipient, 8)
    _write(context, frame + 0x98, 1, 1)
    target = _read(context, vptr + 0x1C8, 8)
    _stage(
        context,
        frame + 0xA0,
        _read(context, subject + 0x180, 8),
        (
            ("add", 0x2B3719EF44DE99FF),
            ("add", 0x21D14A25ED7C802C),
        ),
    )
    _write(context, frame + 0xA8, 8, _read(context, frame + 0xA0, 8))
    encoded_y = _read(context, subject + 0x178, 8)
    z = _read(context, frame + 0xA8, 4)
    _stage(
        context,
        frame + 0xA0,
        encoded_y,
        (
            ("sub", 0x61501AA6ECFD980A),
            ("add", 0x6C5EAB60B426DD28),
        ),
    )
    _write(context, frame + 0x40, 8, _read(context, frame + 0xA0, 8))
    encoded_x = _read(context, subject + 0x170, 8)
    y = _read(context, frame + 0x40, 4)
    _stage(
        context,
        frame + 0xA0,
        encoded_x,
        (
            ("sub", 0x183CAC30D2441D0E),
            ("add", 0x4C3FBA69E4EA7FD1),
        ),
    )
    _write(context, frame + 0xA0, 8, _read(context, frame + 0xA0, 8))
    x = _read(context, frame + 0xA0, 4)
    flag = (frame + 0x98) & _U64
    _write(context, frame + 0x30, 8, flag)
    _write(context, frame + 0x28, 4, 0)
    _write(context, frame + 0x20, 4, z)
    if fp_calls.call is None:
        raise UnresolvedReplayTaskRebuild("actual Base registration mixed-FP effect unavailable")
    fp_calls.call(
        ReplayBaseSavedRegistrationFPCall(
            target,
            recipient,
            0x2B9,
            x,
            y,
            z,
            0,
            flag,
            (frame + 0x20) & _U64,
        )
    )
    _write(context, subject + 0x2D8, 4, _read(context, subject + 0x2D8, 4) | bit)


def _selected(
    context: ReplayTaskRebuildStorage,
    subject: int,
    frame: int,
    held_begin: int,
    offset: int,
    index: int,
    converted: int,
    absolute: int,
    calls: ReplayTaskRebuildCalls,
    fp_calls: ReplayBaseSavedRegistrationFP,
) -> None:
    category = _call(calls, 0x1410B9EE0, (absolute,), width=4)
    master = _read(context, frame + 0xA0, 8)
    key = (absolute - 900) & _U32 if category == 1 else absolute
    bit = 1 << (index & 31)
    if _read(context, master + 0x1D4, 4) == 0:
        current = _master(context, subject, frame + 0x98)
        matches = False
        if category == 0:
            _stage(
                context,
                frame + 0x98,
                _read(context, current + 0x18, 8),
                (
                    ("xor", 0x349E37847AD69F19),
                    ("sub", 0x47E37DFF0616CE4F),
                ),
            )
            matches = _signed(_read(context, frame + 0x98, 8) & 0xFFFF, 2) == _signed(key, 4)
        if not matches and category == 1:
            _stage(
                context,
                frame + 0x98,
                _read(context, current + 0x38, 8),
                (
                    ("sub", 0x50A06BCECEBEF905),
                    ("add", 0x5B32AA7995D95916),
                ),
            )
            matches = _signed(_read(context, frame + 0x98, 8) & 0xFFFF, 2) == _signed(key, 4)
        if not matches:
            _reject(context, master)
            return
        _write(context, frame + 0x20, 4, 0)
        cast = _call(calls, _RTTI, (subject, 0, 0x14411D848, 0x14411FFA8, 0), width=8)
        if cast:
            word = _read(context, cast + 0x900, 4)
            # UCOMISS unordered follows JP to the same tag check as nonzero.
            if word & 0x7FFFFFFF == 0 or _read(context, subject + 0x188, 1) != 2:
                _reject(context, master)
                return
        if _read(context, subject + 0x2D8, 4) & bit:
            _reject(context, master)
            return
        _write(context, master + 0x1D4, 4, 2)
    if _signed(converted, 4) > 0:
        _positive(context, subject, frame, held_begin, offset, bit, fp_calls)
        return
    mask = _read(context, subject + 0x2DC, 4)
    owner = _read(context, subject + 0x18, 8)
    _write(context, subject + 0x2DC, 4, mask | bit)
    vptr = _read(context, subject, 8)
    _write(context, frame + 0x20, 4, 0)
    _call(calls, _read(context, vptr + 0x1E8, 8), (subject, owner, 0, _U32, 0))
    _write(context, subject + 0x2D8, 4, _read(context, subject + 0x2D8, 4) | bit)


def register_replay_saved_base(
    context: ReplayTaskRebuildStorage,
    subject: int,
    *,
    calls: ReplayTaskRebuildCalls,
    fp_calls: ReplayBaseSavedRegistrationFP,
    bind_local: LocalBinding,
    scratch: ReplayBaseSavedRegistrationScratch,
) -> None:
    """Complete normal1412488e0; required helper/current effects stay real.

    Bind the six provided helpers or supply their actual effects via calls.
    The World returned by the current Game getter is not inferred equal to
    subject-owner World. Current begin is reloaded per loop, while count and
    each iteration's begin survive helper callbacks. The first eligible
    nonzero absolute value ends the traversal even on rejection.
    """
    _validate(context, calls, subject)
    if not isinstance(fp_calls, ReplayBaseSavedRegistrationFP) or not callable(bind_local):
        raise ValueError("actual Base registration FP/local providers required")
    if not isinstance(scratch, ReplayBaseSavedRegistrationScratch):
        raise ValueError("explicit Base registration frame seed required")
    with _local(memoryview(bytearray(scratch.frame)), bind_local) as frame:
        game = _read(context, 0x144353698, 8)
        if _call(calls, 0x140D6A940, (game,), width=4) == 4:
            return
        initial_master = _master(context, subject, frame + 0x98)
        _write(context, frame + 0xA0, 8, initial_master)
        if _read(context, initial_master + 0x1D4, 4) == 1:
            return
        game = _read(context, 0x144353698, 8)
        world = _call(calls, 0x140D6ACC0, (game,), width=8)
        header = _call(calls, 0x141603FF0, (world,), width=8)
        end = _read(context, header + 8, 8)
        count = (_signed((end - _read(context, header, 8)) & _U64, 8) >> 4) & _U64
        index, offset = 0, 0
        while index < count:
            begin = _read(context, header, 8)
            player = _read(context, begin + offset, 8)
            if player:
                owner = _read(context, subject + 0x18, 8)
                if player != owner:
                    relations = _read(context, owner + 0x180, 8)
                    related = _read(context, relations + index, 1) != 0
                    if not related:
                        owner_id = _signed(_read(context, owner + 0x648, 4), 4)
                        reverse = _read(context, player + 0x180, 8)
                        related = _read(context, reverse + owner_id, 1) != 0
                    if related and _signed(_read(context, player + 0x90, 4), 4) > 204:
                        state = _read(context, player + 0x98, 8)
                        _stage(
                            context,
                            frame + 0x98,
                            _read(context, state + 0x660, 8),
                            (
                                ("xor", 0x6AE24D3352F04511),
                                ("xor", 0xC22D6B496D833977),
                                ("sub", 0x042AC42976FCCEF5),
                                ("xor", 0xA9834B738A7DD167),
                            ),
                        )
                        _write(context, frame + 0x98, 8, _read(context, frame + 0x98, 8))
                        converted = _cvtt32(_read(context, frame + 0x98, 4))
                        absolute = _call(calls, 0x140A81440, (converted,), width=4)
                        if absolute:
                            _selected(
                                context,
                                subject,
                                frame,
                                begin,
                                offset,
                                index,
                                converted,
                                absolute,
                                calls,
                                fp_calls,
                            )
                            return
            index, offset = (index + 1) & _U64, (offset + 16) & _U64
        _reject(context, _read(context, frame + 0xA0, 8))


def bind_replay_base_saved_registration(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    *,
    imports: ReplayTaskRebuildCalls,
    fp_calls: ReplayBaseSavedRegistrationFP,
    bind_local: LocalBinding,
    scratch: ReplayBaseSavedRegistrationScratch,
) -> ReplayTaskRebuildCalls:
    """Bind caller+six complete helpers; RTTI selected imports are terminal.

    Explicit imports bypass these internal handlers after exactly one current
    IAT read. No fixed historical import address or successful cast is supplied.
    """
    _validate(context, calls)
    if not isinstance(imports, ReplayTaskRebuildCalls):
        raise ValueError("actual terminal RTTI imports required")
    if not isinstance(fp_calls, ReplayBaseSavedRegistrationFP) or not callable(bind_local):
        raise ValueError("actual Base registration FP/local providers required")
    if not isinstance(scratch, ReplayBaseSavedRegistrationScratch):
        raise ValueError("explicit Base registration frame seed required")

    def dispatch(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        if target != _ENTRY and target not in _HELPERS:
            if calls.call is None:
                raise UnresolvedReplayTaskRebuild(f"reached{target:x} is unavailable")
            return calls.call(target, args, data)
        if len(args) != (5 if target == _RTTI else 1) or data is not None:
            raise ValueError("malformed Base registration/helper call")
        _validate(context, calls, *args)
        value = args[0]
        if target == _ENTRY:
            register_replay_saved_base(
                context,
                value,
                calls=bound,
                fp_calls=fp_calls,
                bind_local=bind_local,
                scratch=scratch,
            )
            return None
        if target == _RTTI:
            return _call(imports, _read(context, 0x143199960, 8), args, width=8)
        if target == 0x140D6A940:
            pointer = _read(context, value + 0x560, 8)
            return _read(context, pointer + 8, 4) if pointer else 0
        if target == 0x140D6ACC0:
            return _read(context, value + 0x5C0, 8)
        if target == 0x141603FF0:
            return (value + 0x768) & _U64
        signed = _signed(value & _U32, 4)
        if target == 0x140A81440:
            return abs(signed) & _U32
        return 2 if signed < 0 or signed >= 1000 else int(signed >= 900)

    bound = ReplayTaskRebuildCalls(dispatch)
    return bound
