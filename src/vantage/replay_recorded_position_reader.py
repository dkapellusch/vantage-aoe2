"""Addressed recording position reader, byte header and tell leaf.

Build54800 complete140dec960/140df03c0/140915f00:930B/254instructions.
Native File read140916db0 and seek1409179e0 remain mandatory actual children.
Saved-input capabilities do not implement those native wrapper identities.
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
    _write,
)
from .replay_unit_ai_base import _validate
from .replay_unit_ai_construction import _local
from .replay_unit_ai_map import ReplayUnitAIMapAtomics, _release

_U32 = (1 << 32) - 1
_READER, _HEADER, _TELL = 0x140DEC960, 0x140DF03C0, 0x140915F00
_INPUT, _SEEK, _CLEAR = 0x140916DB0, 0x1409179E0, 0x1402BD7F0


@dataclass(frozen=True, slots=True)
class ReplayRecordedPositionScratch:
    """Explicit current logical seeds, without native cookie/register slots.

    Reader uses post-RSP+20 Result48 and+50 markerDWORD; header uses+28
    Result48 and+58 markerBYTE. Neither caller zeroes the Result. Source's
    processed byte and partial stores retain all other supplied/current bytes.
    Each active invocation owns a distinct live mapping, including nested header.
    """

    reader: bytes
    header: bytes

    def __post_init__(self) -> None:
        if any(
            type(value) is not bytes or len(value) != size
            for value, size in (
                (self.reader, 0x58),
                (self.header, 0x60),
            )
        ):
            raise ValueError("explicit58/60-hex-byte recording local seeds required")


def _finish_input(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    atomics: ReplayUnitAIMapAtomics,
    result: int,
) -> int:
    # Input RAX is ignored. Source holds control BEFORE status BEFORE marking.
    control = _read(context, result + 0x20, 8)
    status = _read(context, result + 0x18, 8)
    _write(context, result + 0x28, 1, 1)
    if control:
        _release(context, control, calls, atomics)
    _call(calls, _CLEAR, (result,))
    return status


def _read_header(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    descriptor: int,
    *,
    atomics: ReplayUnitAIMapAtomics,
    bind_local: LocalBinding,
    scratch: bytes,
) -> int:
    if not _read(context, descriptor + 0x5C, 4):
        return 1
    _write(context, descriptor + 0x58, 1, _read(context, descriptor + 0x58, 1) + 1)
    with _local(memoryview(bytearray(scratch)), bind_local) as frame:
        result, marker = frame + 0x28, frame + 0x58
        _call(calls, _INPUT, (_read(context, descriptor + 0x48, 8), result, marker, 1))
        if _finish_input(context, calls, atomics, result):
            return _U32
        counter = _read(context, descriptor + 0x58, 1)
        return 1 + int(_read(context, marker, 1) != counter)


def _read_position(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    descriptor: int,
    x_output: int,
    y_output: int,
    wire_output: int,
    *,
    atomics: ReplayUnitAIMapAtomics,
    bind_local: LocalBinding,
    scratch: bytes,
) -> int:
    if not _read(context, descriptor + 1, 1):
        return 6
    with _local(memoryview(bytearray(scratch)), bind_local) as frame:
        result, marker = frame + 0x20, frame + 0x50
        stream = _read(context, descriptor + 0x48, 8)
        _write(context, marker, 4, _U32)
        position = _call(calls, _TELL, (stream,), width=8)
        _call(calls, _INPUT, (_read(context, descriptor + 0x48, 8), result, marker, 4))
        if _finish_input(context, calls, atomics, result):
            return _U32
        if _read(context, marker, 4) != 3:
            returned = _call(
                calls,
                _SEEK,
                (
                    _read(context, descriptor + 0x48, 8),
                    result,
                    position,
                ),
                width=8,
            )
            # Seek uses returned status/processed, but FIXED Result control/vector.
            status = _read(context, returned + 0x18, 8)
            _write(context, returned + 0x28, 1, 1)
            control = _read(context, result + 0x20, 8)
            if control:
                _release(context, control, calls, atomics)
            _call(calls, _CLEAR, (result,))
            return _U32 if status else 4
        header = _call(calls, _HEADER, (descriptor,), width=4)
        if header != 1:
            return header
        for destination in (x_output, y_output, wire_output):
            _call(calls, _INPUT, (_read(context, descriptor + 0x48, 8), result, destination, 4))
            if _finish_input(context, calls, atomics, result):
                return _U32
        return 1


def bind_replay_recorded_position_reader(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    *,
    atomics: ReplayUnitAIMapAtomics,
    bind_local: LocalBinding,
    scratch: ReplayRecordedPositionScratch,
) -> ReplayTaskRebuildCalls:
    """Own three complete bodies; preserve actual child ABI and earlier effects.

    Known arguments are raw u64, native scalars are narrowed by their source
    accesses. Unknown targets/arguments/payload/results delegate unchanged.
    Child read/seek services must supply their actual native File behavior and
    current Result backing. Tell reads the current stream40 QWORD. This binder
    supplies no bytes/cursor/global/Result success or stream-class identity.

    Inline held-control release uses mandatory actual engine XADD and current
    control vptrs. Real1402bd7f0 vector destruction remains a mandatory call;
    generic140900620 finalization has a different source shape. The existing
    saved-result/string/free binders can compose when their actual children
    are provided. Output writes and Result/control/marker mutations persist
    through failures; no caller transaction or invented error cleanup occurs.

    Active local mappings survive all reached callbacks and expire on owned
    return/refusal. Inactive reader/header skip their mapping and I/O. Physical
    native stack/register/cookie, escaped local pointers, native faults/EH and
    concurrent atomic ordering are excluded. No replay/World readiness follows.
    """
    _validate(context, calls)
    if not isinstance(atomics, ReplayUnitAIMapAtomics) or not callable(bind_local):
        raise ValueError("actual recording atomic/local effects required")
    if not isinstance(scratch, ReplayRecordedPositionScratch):
        raise ValueError("explicit recording reader/header scratch required")

    def dispatch(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        arity = {_READER: 4, _HEADER: 1, _TELL: 1}
        if target not in arity:
            if calls.call is None:
                raise UnresolvedReplayTaskRebuild(f"reached{target:x} is unavailable")
            return calls.call(target, args, data)
        if len(args) != arity[target] or data is not None:
            raise ValueError("malformed recording reader/header/tell call")
        _validate(context, calls, *args)
        if target == _TELL:
            return _read(context, args[0] + 0x40, 8)
        if target == _HEADER:
            return _read_header(
                context,
                bound,
                args[0],
                atomics=atomics,
                bind_local=bind_local,
                scratch=scratch.header,
            )
        return _read_position(
            context, bound, *args, atomics=atomics, bind_local=bind_local, scratch=scratch.reader
        )

    bound = ReplayTaskRebuildCalls(dispatch)
    return bound
