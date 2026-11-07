"""Build54800 normal saved Animated141142a70, with its real Base predecessor.

Source: base-saved-reader-source-review-v1, complete1279B/300instructions.
The effective fourth argument survives into Base despite the decompiled C
signature. Returned-error metadata/TLS, native stack/register identity,
cookies, faults, concurrency and C++ EH remain outside this logical profile.
"""

from __future__ import annotations

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
_ENTRY = 0x141142A70


def _clear(context: ReplayTaskRebuildStorage, result: int) -> None:
    for offset in (0, 16, 32):
        _write(context, result + offset, 16, 0)


def _finish(
    context: ReplayTaskRebuildStorage,
    result: int,
    phase: str,
    calls: ReplayTaskRebuildCalls,
    atomics: ReplayUnitAIMapAtomics,
) -> None:
    if _read(context, result + 24, 8):
        raise UnresolvedReplayTaskRebuild(
            f"Animated saved reader reached {phase} returned-error metadata/TLS frontier"
        )
    _write(context, result + 40, 1, 1)
    held = _read(context, result + 32, 8)
    if held:
        _release(context, held, calls, atomics)
    _call(calls, 0x1402BD7F0, (result & _U64,))


def read_replay_saved_animated(
    context: ReplayTaskRebuildStorage,
    address: int,
    output: int,
    stream: int,
    opaque: int,
    *,
    calls: ReplayTaskRebuildCalls,
    atomics: ReplayUnitAIMapAtomics,
    bind_local: LocalBinding,
    scratch: bytes,
) -> int:
    """Normal four-argument141142a70; no Base or Input success is inferred.

    The98-byte explicit logical frame uses original post-prologue RSP offsets:
    output identity60 and reused Result68..97. The frame remains coherent
    through all calls, including failure; physical stack aliases, saved native
    registers and cookie storage are not represented. Only source-initialized
    fields are cleared. Opaque entryR9 is passed unchanged into actual Base.
    """
    _validate(context, calls, address, output, stream, opaque)
    if not isinstance(atomics, ReplayUnitAIMapAtomics) or not callable(bind_local):
        raise ValueError("actual Animated saved atomic/local bindings required")
    if type(scratch) is not bytes or len(scratch) != 0x98:
        raise ValueError("explicit98-byte Animated saved local seed required")
    with _local(memoryview(bytearray(scratch)), bind_local) as frame:
        _write(context, frame + 0x60, 8, output)
        result = (frame + 0x68) & _U64
        _clear(context, result)
        _call(calls, 0x14125D730, (address, result, stream, opaque))
        _finish(context, result, "Base", calls, atomics)
        _write(context, address + 15, 1, 20)
        _clear(context, result)
        target = _read(context, _read(context, stream, 8) + 24, 8)
        _call(calls, target, (stream, result, (address + 0x350) & _U64, 4))
        _finish(context, result, "Input", calls, atomics)
        for offset in (0, 8, 16, 24, 32):
            _write(context, output + offset, 8, 0)
        _write(context, output + 40, 1, 0)
    return output


def bind_replay_animated_saved(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    *,
    atomics: ReplayUnitAIMapAtomics,
    bind_local: LocalBinding,
    scratch: bytes,
) -> ReplayTaskRebuildCalls:
    """Bind the complete normal caller; preserve unknown calls and live views."""
    _validate(context, calls)
    if not isinstance(atomics, ReplayUnitAIMapAtomics) or not callable(bind_local):
        raise ValueError("actual Animated saved atomic/local bindings required")
    if type(scratch) is not bytes or len(scratch) != 0x98:
        raise ValueError("explicit98-byte Animated saved local seed required")

    def dispatch(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        if target != _ENTRY:
            if calls.call is None:
                raise UnresolvedReplayTaskRebuild(f"reached{target:x} is unavailable")
            return calls.call(target, args, data)
        if len(args) != 4 or data is not None:
            raise ValueError("malformed Animated saved call")
        return read_replay_saved_animated(
            context,
            *args,
            calls=bound,
            atomics=atomics,
            bind_local=bind_local,
            scratch=scratch,
        )

    bound = ReplayTaskRebuildCalls(dispatch)
    return bound
