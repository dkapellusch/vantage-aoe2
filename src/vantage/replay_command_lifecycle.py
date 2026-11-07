"""Nineteen complete command lifecycle/GUID/event source bodies.

Source: world-command-reader-source-v1. No GUID, mutex, event, TLS, File,
callback, vector or error success/backing is supplied by this binder.
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
from .replay_unit_ai_map import ReplayUnitAIMapAtomics, _atomic, _release

_U32, _U64 = (1 << 32) - 1, (1 << 64) - 1
_STOP, _ABORT, _WRITER = 0x140DF2670, 0x140DF2240, 0x140DEE940
_DISPATCH, _VECTOR, _EVENT_CLEAN = 0x140A8FB50, 0x140A8E1A0, 0x1409053D0
_STRONG, _CTOR, _GUID, _COPY16, _COPY_FIELDS = (
    0x140990140,
    0x140A3E250,
    0x140900030,
    0x1408FFF50,
    0x140900050,
)
_SETTINGS, _SERVICE, _CONVERT, _POST = 0x140E15890, 0x140A6CB50, 0x140A70250, 0x140A6D200
_GLOBAL, _PRESENT, _CELL, _COGUID = 0x140A69450, 0x140A694D0, 0x140E57AB0, 0x141758280
_CLEAR, _FREE, _STRING = 0x1402BD7F0, 0x142D6BAB4, 0x1402A88A0
_WRITE, _SEEK, _LOCK, _UNLOCK, _THROW = (
    0x140918D20,
    0x1409179E0,
    0x142D6AA5B,
    0x142D6AA61,
    0x142D6AA67,
)


@dataclass(frozen=True, slots=True)
class ReplayCommandLifecycleProfile:
    """Required coherent semantic local prefixes; no state/backing defaults.

    stop160h; abort50h; writer68h; dispatcher78h; vector/event_cleanup28h.
    Vector/event28 excludes the native30h tail; HOME20 stays current. Native
    cookies, spills, physical stack adjacency/EH/faults/concurrency excluded.
    Optional gs_base is an explicit engine address, never host/native GS.
    """

    stop: bytes
    abort: bytes
    writer: bytes
    dispatcher: bytes
    vector: bytes
    event_cleanup: bytes
    gs_base: int | None

    def __post_init__(self) -> None:
        if any(
            type(value) is not bytes or len(value) != size
            for value, size in (
                (self.stop, 0x160),
                (self.abort, 0x50),
                (self.writer, 0x68),
                (self.dispatcher, 0x78),
                (self.vector, 0x28),
                (self.event_cleanup, 0x28),
            )
        ):
            raise ValueError("explicit160/50/68/78/28/28-hex-byte lifecycle seeds required")
        if self.gs_base is not None:
            _unsigned(self.gs_base, 8, "engine GS base")


def _invoke(
    calls: ReplayTaskRebuildCalls,
    target: int,
    args: tuple[int, ...],
) -> int | None:
    if calls.call is None:
        raise UnresolvedReplayTaskRebuild(f"reached{target:x} is unavailable")
    return calls.call(target, tuple(value & _U64 for value in args), None)


def _raw(value: int | None, label: str) -> int:
    if value is None:
        raise ValueError(f"{label} requires rawRAX at source consumption")
    _unsigned(value, 8, label)
    return value


def _cleanup(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    atomics: ReplayUnitAIMapAtomics,
    result: int,
    control: int,
) -> None:
    if control:
        _release(context, control, calls, atomics)
    _call(calls, _CLEAR, (result,))


def _finish_write(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    atomics: ReplayUnitAIMapAtomics,
    result: int,
) -> int:
    control = _read(context, result + 0x20, 8)
    status = _read(context, result + 0x18, 8)
    _write(context, result + 0x28, 1, 1)
    _cleanup(context, calls, atomics, result, control)
    return status


def _watson(
    context: ReplayTaskRebuildStorage,
    channel: ReplayTaskRebuildCalls,
    frame: int,
) -> None:
    _write(context, frame + 0x20, 8, 0)
    target = _read(context, 0x14319A060, 8)
    _invoke(channel, target, (0, 0, 0, 0, frame + 0x20))
    raise UnresolvedReplayTaskRebuild("command Watson returned before source INT3")


def _vector(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    watson: ReplayTaskRebuildCalls,
    subject: int,
    *,
    frame: int,
) -> None:
    pointer = _read(context, subject, 8)
    if not pointer:
        return  # Source skips capacity reads AND all resets.
    size = (_read(context, subject + 0x10, 8) - pointer) & (_U64 - 7)
    allocation = pointer
    if size >= 0x1000:
        allocation = _read(context, pointer - 8, 8)
        size = size + 0x27 & _U64
        if (pointer - allocation - 8) & _U64 > 31:
            _watson(context, watson, frame)
    _call(calls, _FREE, (allocation, size))
    for offset in (0, 8, 16):
        _write(context, subject + offset, 8, 0)


def _event_cleanup(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    watson: ReplayTaskRebuildCalls,
    subject: int,
    *,
    frame: int,
) -> int | None:
    _call(calls, _STRING, (subject + 0xA0,))
    _call(calls, _STRING, (subject + 0x80,))
    _vector(context, calls, watson, subject + 0x58, frame=frame)
    head = _read(context, subject + 0x48, 8)
    tail = _read(context, head + 8, 8)
    _write(context, tail, 8, 0)
    node = _read(context, head, 8)
    while node:
        following = _read(context, node, 8)
        _call(calls, _STRING, (node + 0x30,))
        _call(calls, _STRING, (node + 0x10,))
        _call(calls, _FREE, (node, 0x50))
        node = following
    _call(calls, _FREE, (_read(context, subject + 0x48, 8), 0x50))
    _vector(context, calls, watson, subject + 0x18, frame=frame)
    tree = _read(context, subject + 8, 8)
    _call(calls, 0x140905300, (subject + 8, tree))
    return _invoke(calls, _FREE, (_read(context, subject + 8, 8), 0x58))


def _bad_function(calls: ReplayTaskRebuildCalls, *, first: bool) -> None:
    _call(calls, 0x142D6669E, ())
    if first:
        # First error CALL atfc82 falls through NOP to second error atfc88.
        _call(calls, 0x142D6669E, ())
    raise UnresolvedReplayTaskRebuild("command bad-function returned before INT3fc8d")


def _dispatch_callbacks(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    subject: int,
    *,
    frame: int,
) -> None:
    mutex = _read(context, subject, 8)
    _write(context, frame + 0x20, 8, mutex)
    locked = _call(calls, _LOCK, (mutex,), width=8) & _U32
    if locked:
        _call(calls, _THROW, (5,))
        raise UnresolvedReplayTaskRebuild("command lock error returned before INT3fc98")
    if _read(context, mutex + 0x4C, 4) == 0x7FFFFFFF:
        _write(context, mutex + 0x4C, 4, 0x7FFFFFFE)
        _call(calls, _THROW, (6,))
        raise UnresolvedReplayTaskRebuild("command lock overflow returned before INT3fcaa")
    current_owner = _read(context, subject, 8)
    _write(context, frame + 0x30, 8, 0x1432189D0)
    _write(context, frame + 0x38, 8, subject)
    functor = frame + 0x30
    _write(context, frame + 0x68, 8, functor)
    node = _read(context, current_owner + 0x50, 8)
    while node:
        _write(context, frame + 0x70, 8, node)
        if not functor:
            _bad_function(calls, first=True)
        vptr = _read(context, functor, 8)
        method = _read(context, vptr + 0x10, 8)
        _call(calls, method, (functor, frame + 0x70))
        node = _read(context, node + 0x48, 8)
        functor = _read(context, frame + 0x68, 8)
    if functor:
        deleting = int(functor != frame + 0x30)
        vptr = _read(context, functor, 8)
        _call(calls, _read(context, vptr + 0x20, 8), (functor, deleting))
    _call(calls, _UNLOCK, (mutex,))
    end = _read(context, subject + 0x10, 8)
    begin = _read(context, subject + 8, 8)
    while _signed((end - begin) & _U64, 8) >> 3:
        count = _signed((end - begin) & _U64, 8) >> 3
        node = _read(context, begin + count * 8 - 8, 8)
        _write(context, subject + 0x10, 8, _read(context, subject + 0x10, 8) - 8)
        callback = _read(context, node + 0x38, 8)
        if not callback:
            _bad_function(calls, first=False)
        vptr = _read(context, callback, 8)
        _call(calls, _read(context, vptr + 0x10, 8), (callback,))
        end = _read(context, subject + 0x10, 8)
        begin = _read(context, subject + 8, 8)
    if begin != end:
        _write(context, subject + 0x10, 8, begin)


def _writer(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    descriptor: int,
    payload: int,
    length: int,
    tail: int,
    *,
    atomics: ReplayUnitAIMapAtomics,
    frame: int,
) -> int:
    # Source samples gate BEFORE local arg stores, but even inactive path stores them.
    active = _read(context, descriptor, 1)
    _write(context, frame + 0x50, 4, length)
    _write(context, frame + 0x60, 4, tail)
    if not active:
        return 7
    result = frame + 0x20
    stream = _read(context, descriptor + 0x48, 8)
    _write(context, frame + 0x58, 4, 1)
    _call(calls, _WRITE, (stream, result, frame + 0x58, 4))
    if _finish_write(context, calls, atomics, result):
        return _U32
    header = _call(calls, 0x140DEED70, (descriptor,), width=8) & _U32
    if header != 1:
        return header
    _call(
        calls,
        _WRITE,
        (
            _read(context, descriptor + 0x48, 8),
            result,
            frame + 0x50,
            4,
        ),
    )
    if _finish_write(context, calls, atomics, result):
        return _U32
    current_length = _read(context, frame + 0x50, 4)
    stream = _read(context, descriptor + 0x48, 8)
    _call(calls, _WRITE, (stream, result, payload, current_length))
    if _finish_write(context, calls, atomics, result):
        return _U32
    _call(
        calls,
        _WRITE,
        (
            _read(context, descriptor + 0x48, 8),
            result,
            frame + 0x60,
            4,
        ),
    )
    if _finish_write(context, calls, atomics, result):
        return _U32
    if _read(context, descriptor + 0x8C, 1):
        _call(calls, 0x140915B30, (_read(context, descriptor + 0x48, 8), result))
        # Flush has no caller status read or processed-byte store.
        control = _read(context, result + 0x20, 8)
        _cleanup(context, calls, atomics, result, control)
    return 1


def _abort(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    descriptor: int,
    *,
    atomics: ReplayUnitAIMapAtomics,
    frame: int,
) -> None:
    result = frame + 0x20
    stream = _read(context, descriptor + 0x48, 8)
    if stream:
        returned = _call(calls, _SEEK, (stream, result, 0), width=8)
        _write(context, returned + 0x28, 1, 1)
        control = _read(context, result + 0x20, 8)
        _cleanup(context, calls, atomics, result, control)
        _call(
            calls,
            _WRITE,
            (
                _read(context, descriptor + 0x48, 8),
                result,
                descriptor + 0x84,
                4,
            ),
        )
        control = _read(context, result + 0x20, 8)
        _write(context, result + 0x28, 1, 1)
        _cleanup(context, calls, atomics, result, control)
        stream = _read(context, descriptor + 0x48, 8)
        if stream:
            _call(calls, _STRONG, (stream,))
        _write(context, descriptor + 0x48, 8, 0)
    control = _read(context, descriptor + 0x128, 8)
    _write(context, descriptor + 0x120, 8, 0)
    _write(context, descriptor + 0x128, 8, 0)
    if control:
        _release(context, control, calls, atomics)
    _write(context, descriptor, 1, 0)


def _service(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    gs_base: int | None,
) -> int:
    if gs_base is None:
        raise UnresolvedReplayTaskRebuild("command service reached missing engine GS58 backing")
    array = _read(context, gs_base + 0x58, 8)
    index = _read(context, 0x144C9C828, 4)
    thread = _read(context, array + index * 8, 8)
    epoch = _read(context, thread + 0x3B4, 4)
    guard = 0x14428F4D8
    if _signed(_read(context, guard, 4), 4) > _signed(epoch, 4):
        _call(calls, 0x142D6BF80, (guard,))
        if _read(context, guard, 4) == _U32:
            _call(calls, 0x140A6BBD0, (0x14428EEA0,))
            _call(calls, 0x142D6BD04, (0x14305F220,))
            _call(calls, 0x142D6BF14, (guard,))
    return 0x14428EEA0


def _stop(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    descriptor: int,
    *,
    exchange_byte: Callable[[int, int], int | None] | None,
    frame: int,
) -> None:
    stream = _read(context, descriptor + 0x48, 8)
    if stream:
        _call(calls, _STRONG, (stream,))
        _write(context, descriptor + 0x48, 8, 0)
    if exchange_byte is None:
        raise UnresolvedReplayTaskRebuild("command stop reached missing atomic byte exchange")
    exchange_byte((descriptor + 1) & _U64, 0)  # Source old AL is never consumed.
    _write(context, descriptor + 0x80, 1, 0)
    _call(calls, _CTOR, (frame + 0x118,))
    _write(context, frame + 0x110, 8, 0x143214E58)
    _write(context, frame + 0x144, 16, 0)
    _call(calls, _GUID, (frame + 0x144,))
    _call(calls, _COPY16, (frame + 0x28, frame + 0x118))
    _call(calls, _COPY_FIELDS, (frame + 0x144, frame + 0x28))
    cell = _call(calls, _SETTINGS, (_read(context, 0x1442DA8A0, 8),), width=8)
    source = _read(context, cell, 8)
    _call(calls, _COPY_FIELDS, (frame + 0x118, source + 0xA8))
    service = _call(calls, _SERVICE, (), width=8)
    vptr = _read(context, frame + 0x110, 8)
    method = _read(context, vptr, 8)
    converted = _call(calls, method, (frame + 0x110, frame + 0x40), width=8)
    _call(calls, _POST, (service, converted))
    _call(calls, _EVENT_CLEAN, (frame + 0x40,))
    current = _call(calls, _GLOBAL, (), width=8)
    _write(context, current + 0xA24, 4, 0)


def bind_replay_command_lifecycle(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    *,
    imports: ReplayTaskRebuildCalls,
    watson_home_calls: ReplayTaskRebuildCalls,
    atomics: ReplayUnitAIMapAtomics,
    exchange_byte: Callable[[int, int], int | None] | None,
    bind_local: LocalBinding,
    profile: ReplayCommandLifecycleProfile,
) -> ReplayTaskRebuildCalls:
    """Own19 bodies, mandatory actual descendants/current backing at reach.

    Current CoCreateGuid IAT target uses imports; current Watson target uses
    separate4register+HOME20ADDRESS channel. All direct/virtual/runtime/lock/
    sized-free calls use regular bound calls. Large writer/event children
    remain external, never synthesized successful or empty. Byte exchange is
    one explicit operation with ignored return, not Storage read+write.

    Argfree GLOBAL/PRESENT/SERVICE accept0or1 incidental RCX annotations.
    PRESENT defines AL only. Other incidental RAX values are excluded where
    no scalar return is source-owned; real tail calls delegate opaque results.
    Functor deletion argument defines its lowBYTE; volatile highRDX excluded.
    Unknown target/args/data/result delegates unchanged. Finite terminating
    valid structures/callbacks required; no iteration cap/fallback supplied.
    """
    for channel in (calls, imports, watson_home_calls):
        _validate(context, channel)
    if (
        not isinstance(atomics, ReplayUnitAIMapAtomics)
        or not callable(bind_local)
        or not isinstance(profile, ReplayCommandLifecycleProfile)
        or (exchange_byte is not None and not callable(exchange_byte))
    ):
        raise ValueError("actual lifecycle atomics/local effects and explicit profile required")
    arities = {
        _STOP: 1,
        _ABORT: 1,
        _WRITER: 4,
        _DISPATCH: 1,
        _VECTOR: 1,
        _EVENT_CLEAN: 1,
        _STRONG: 1,
        _CTOR: 1,
        _GUID: 1,
        _COPY16: 2,
        _COPY_FIELDS: 2,
        _SETTINGS: 1,
        _SERVICE: 0,
        _CONVERT: 2,
        _POST: 2,
        _GLOBAL: 0,
        _PRESENT: 0,
        _CELL: 1,
        _COGUID: 1,
    }
    seeds = {
        _STOP: profile.stop,
        _ABORT: profile.abort,
        _WRITER: profile.writer,
        _DISPATCH: profile.dispatcher,
        _VECTOR: profile.vector,
        _EVENT_CLEAN: profile.event_cleanup,
    }

    def dispatch(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        if target not in arities:
            if calls.call is None:
                raise UnresolvedReplayTaskRebuild(f"reached{target:x} is unavailable")
            return calls.call(target, args, data)
        count = arities[target]
        if (
            len(args) != count and not (target in (_SERVICE, _GLOBAL, _PRESENT) and len(args) == 1)
        ) or data is not None:
            raise ValueError("malformed command lifecycle call")
        _validate(context, calls, *args)
        if target in (_STOP, _ABORT) and not _read(context, args[0] + int(target == _STOP), 1):
            return None
        if target in seeds:
            with _local(memoryview(bytearray(seeds[target])), bind_local) as frame:
                if target == _STOP:
                    _stop(context, bound, *args, exchange_byte=exchange_byte, frame=frame)
                elif target == _ABORT:
                    _abort(context, bound, *args, atomics=atomics, frame=frame)
                elif target == _WRITER:
                    return _writer(context, bound, *args, atomics=atomics, frame=frame)
                elif target == _DISPATCH:
                    _dispatch_callbacks(context, bound, *args, frame=frame)
                elif target == _VECTOR:
                    _vector(context, bound, watson_home_calls, *args, frame=frame)
                else:
                    return _event_cleanup(context, bound, watson_home_calls, *args, frame=frame)
            return None
        if target == _GLOBAL:
            return _read(context, 0x14428ECD8, 8)
        if target == _PRESENT:
            return int(_read(context, 0x14428ECD8, 8) != 0)
        if target == _SERVICE:
            return _service(context, bound, profile.gs_base)
        if target == _COGUID:
            return _invoke(imports, _read(context, 0x14319A758, 8), args)
        if target == _SETTINGS:
            return _invoke(bound, _CELL, ((args[0] + 0xCB8) & _U64,))
        if target == _CELL:
            return args[0] + 0x58 & _U64
        if target == _STRONG:
            prior = _atomic(atomics, args[0] + 8, _U32)
            if prior == 1:
                vptr = _read(context, args[0], 8)
                return _invoke(bound, _read(context, vptr, 8), args)
            return prior
        if target == _GUID:
            _call(bound, _COGUID, args)
            return args[0]
        if target == _CTOR:
            subject = args[0]
            _write(context, subject, 16, 0)
            _call(bound, _GUID, (subject,))
            _write(context, subject + 0x10, 16, 0)
            _call(bound, _GUID, (subject + 0x10,))
            _write(context, subject + 0x20, 8, _U64)
            _write(context, subject + 0x28, 4, _U32)
            if _call(bound, _PRESENT, (), width=8) & 255:
                current = _call(bound, _GLOBAL, (), width=8)
                _call(bound, 0x140A670B0, (current, subject))
            return subject
        if target == _COPY16:
            value = _read(context, args[1], 16)
            _write(context, args[0], 16, value)
            return args[0]
        if target == _COPY_FIELDS:
            for offset, width in ((0, 4), (4, 2), (6, 2), (8, 8)):
                value = _read(context, args[1] + offset, width)
                _write(context, args[0] + offset, width, value)
            return args[0]
        if target == _CONVERT:
            _call(bound, 0x140A31630, (args[0], args[1], 0x143214E60))
            return args[1]
        # POST skip means no follow-up. Both tests read the actual event returned
        # by conversion; its source may be distinct from the fixed cleanup slot.
        event = args[1]
        if _read(context, event + 0xC0, 1) and _read(context, event + 0x90, 8):
            _call(bound, 0x140A60D20, (args[0] + 0x180, event))
            return _invoke(bound, 0x1409046D0, (args[0] + 0x10,))
        return None

    bound = ReplayTaskRebuildCalls(dispatch)
    return bound
