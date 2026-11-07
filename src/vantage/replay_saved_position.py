"""Build54800 normal saved scalar wrappers and ObjectSpawnData position read.

Retained252B140d07ee0/140b81e60 and2134B140c29890 supply the ordering.
unit-component-wrapper-source-v1 proves the full normal4B wrapper bodies at
140b81d60 and140d94310 equivalent to140b81e60 after relocation normalization.
Current stream calls, Result forwarding1409076b0, control atomics/virtuals and
vector cleanup1402bd890 are mandatory effects. Returned-error/TLS diagnostic
branches refuse at their frontier; native stream identity, stack/cookies,
faults, concurrency and C++ unwinding are outside this successful-call profile.
"""

from __future__ import annotations

from contextlib import ExitStack

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

_U64 = (1 << 64) - 1
_METADATA = 0x1432364E0


def _bindings(atomics: ReplayUnitAIMapAtomics, bind_local: LocalBinding) -> None:
    if not isinstance(atomics, ReplayUnitAIMapAtomics) or not callable(bind_local):
        raise ValueError("actual saved position shared-count and local bindings required")


def _zero(context: ReplayTaskRebuildStorage, result: int) -> None:
    for offset in (0, 16, 32):
        _write(context, result + offset, 16, 0)


def _raw_read(
    context: ReplayTaskRebuildStorage,
    stream: int,
    result: int,
    destination: int,
    width: int,
    calls: ReplayTaskRebuildCalls,
) -> None:
    table = _read(context, stream, 8)
    target = _read(context, table + 0x18, 8)
    _call(calls, target, (stream, result, destination & _U64, width))


def _cleanup(
    context: ReplayTaskRebuildStorage,
    result: int,
    calls: ReplayTaskRebuildCalls,
    atomics: ReplayUnitAIMapAtomics,
) -> None:
    control = _read(context, result + 0x20, 8)
    if control:
        _release(context, control, calls, atomics)
    _call(calls, 0x1402BD890, (result,))


def _scalar(
    context: ReplayTaskRebuildStorage,
    output: int,
    metadata: int,
    line: int,
    detail: int,
    stream: int,
    destination: int,
    width: int,
    *,
    calls: ReplayTaskRebuildCalls,
    atomics: ReplayUnitAIMapAtomics,
    bind_local: LocalBinding,
) -> int:
    _validate(context, calls, output, metadata, line, detail, stream, destination)
    _bindings(atomics, bind_local)
    with _local(memoryview(bytearray(48)), bind_local) as raw:
        _raw_read(context, stream, raw, destination, width, calls)
        # Native wrappers clear the external output only AFTER the raw read.
        _zero(context, output)
        _write(context, raw + 0x28, 1, 1)
        if _read(context, raw + 0x18, 8):
            _call(calls, 0x140900ED0, (raw, metadata, line & 0xFFFFFFFF, detail))
        _call(calls, 0x1409076B0, (output, raw))
        _cleanup(context, raw, calls, atomics)
        return output


def read_replay_saved_byte(
    context: ReplayTaskRebuildStorage,
    output: int,
    metadata: int,
    line: int,
    detail: int,
    stream: int,
    destination: int,
    *,
    calls: ReplayTaskRebuildCalls,
    atomics: ReplayUnitAIMapAtomics,
    bind_local: LocalBinding,
) -> int:
    """Normal252B140d07ee0; six scalar inputs, current virtual18 reads one byte.

    Metadata/detail retain raw64 bits; only line's low32 bits reach900ed0.
    The live48B raw Result is fully initialized before I/O. Forwarding remains
    required for status zero; returned RAX is ignored. Cleanup reads the raw
    current control after forwarding and destroys its current vector afterward.
    """
    return _scalar(
        context,
        output,
        metadata,
        line,
        detail,
        stream,
        destination,
        1,
        calls=calls,
        atomics=atomics,
        bind_local=bind_local,
    )


def read_replay_saved_u32(
    context: ReplayTaskRebuildStorage,
    output: int,
    metadata: int,
    line: int,
    detail: int,
    stream: int,
    destination: int,
    *,
    calls: ReplayTaskRebuildCalls,
    atomics: ReplayUnitAIMapAtomics,
    bind_local: LocalBinding,
) -> int:
    """Normal252B140b81e60; same effective six-input ABI with a four-byte read."""
    return _scalar(
        context,
        output,
        metadata,
        line,
        detail,
        stream,
        destination,
        4,
        calls=calls,
        atomics=atomics,
        bind_local=bind_local,
    )


def read_replay_saved_position(
    context: ReplayTaskRebuildStorage,
    position: int,
    output: int,
    stream: int,
    *,
    calls: ReplayTaskRebuildCalls,
    atomics: ReplayUnitAIMapAtomics,
    bind_local: LocalBinding,
) -> int:
    """Normal2134B140c29890: X/Y/Z raw4B followed by raw2B zone.

    Position/output/stream identities stay held while each read uses the current
    stream vptr+18. The middle fields invoke the actual4B wrapper with the
    original metadata. First/last forward then release raw control/vector before
    inspecting forwarded status. Every successful field marks its forwarded
    Result processed before release. Final success writes only output's first
    41 bytes, preserving seven padding bytes. The two initialized48B private
    Results reuse explicit live bindings through return; native stack aliasing
    and error diagnostic strings/TLS transformations are not supplied.
    """
    _validate(context, calls, position, output, stream)
    _bindings(atomics, bind_local)
    with ExitStack() as locals_:
        forwarded = locals_.enter_context(_local(memoryview(bytearray(48)), bind_local))
        raw = locals_.enter_context(_local(memoryview(bytearray(48)), bind_local))
        for index, (offset, width, detail) in enumerate(
            ((0, 4, 0x1432364D0), (4, 4, 0x143236540), (8, 4, 0x143236550), (12, 2, 0x14323655C))
        ):
            if index in (0, 3):
                if index == 3:
                    _zero(context, raw)
                _raw_read(context, stream, raw, position + offset, width, calls)
                _zero(context, forwarded)
                _write(context, raw + 0x28, 1, 1)
                if _read(context, raw + 0x18, 8):
                    _call(calls, 0x140900ED0, (raw, _METADATA, 0x10 + index, detail))
                _call(calls, 0x1409076B0, (forwarded, raw))
                _cleanup(context, raw, calls, atomics)
            else:
                _call(
                    calls,
                    0x140B81E60,
                    (
                        forwarded,
                        _METADATA,
                        0x10 + index,
                        detail,
                        stream,
                        (position + offset) & _U64,
                    ),
                )
            if _read(context, forwarded + 0x18, 8):
                frontier = (0x140C2998E, 0x140C29B53, 0x140C29D33, 0x140C29F59)[index]
                raise UnresolvedReplayTaskRebuild(
                    f"saved position reached returned-error/logging frontier{frontier:x}"
                )
            _write(context, forwarded + 0x28, 1, 1)
            _cleanup(context, forwarded, calls, atomics)
            if index < 3:
                _zero(context, forwarded)
        for offset in (0, 8, 16, 24, 32):
            _write(context, output + offset, 8, 0)
        _write(context, output + 40, 1, 0)
        return output


def bind_replay_saved_position(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    *,
    atomics: ReplayUnitAIMapAtomics,
    bind_local: LocalBinding,
) -> ReplayTaskRebuildCalls:
    """Bind the normal two wrappers and position reader; real children delegate."""
    _validate(context, calls)
    _bindings(atomics, bind_local)

    def dispatch(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        arities = {0x140D07EE0: 6, 0x140B81E60: 6, 0x140B81D60: 6, 0x140D94310: 6, 0x140C29890: 3}
        if target not in arities:
            if calls.call is None:
                raise UnresolvedReplayTaskRebuild(f"reached{target:x} is unavailable")
            return calls.call(target, args, data)
        if len(args) != arities[target] or data is not None:
            raise ValueError("malformed saved position call")
        _validate(context, calls, *args)
        if target == 0x140C29890:
            return read_replay_saved_position(
                context, *args, calls=bound, atomics=atomics, bind_local=bind_local
            )
        function = read_replay_saved_byte if target == 0x140D07EE0 else read_replay_saved_u32
        return function(context, *args, calls=bound, atomics=atomics, bind_local=bind_local)

    bound = ReplayTaskRebuildCalls(dispatch)
    return bound
