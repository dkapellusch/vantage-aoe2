"""Normal build54800 saved object-list loader14122b360 (2,454 bytes).

Source: saved-object-factories-source-v1. Current Input/Result, allocation,
free and current virtual factory effects are required. Object publication is
the constructor's responsibility. Metadata/TLS returned-error branches and
physical stack/register/fault/EH/concurrency behavior remain outside this
logical profile; no complete Player/World restoration is inferred.
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
    _write,
)
from .replay_unit_ai_base import _validate
from .replay_unit_ai_construction import _local
from .replay_unit_ai_map import ReplayUnitAIMapAtomics, _release

_U64 = (1 << 64) - 1


@dataclass(frozen=True, slots=True)
class ReplaySavedObjectListScratch:
    """Explicit B0-byte frame, before cookie and saved XMM/register storage.

    Native RBP is post-prologue RSP+C9. The output slot70, uninitialized tag78,
    Result80..AF and outgoing fifth argument20 share live backing. Untouched
    bytes retain the seed; physical nested-call stack aliasing is excluded.
    """

    reader: bytes

    def __post_init__(self) -> None:
        if type(self.reader) is not bytes or len(self.reader) != 0xB0:
            raise ValueError("explicit B0-byte saved object-list frame required")


def _zero(context: ReplayTaskRebuildStorage, result: int) -> None:
    for offset in (0, 16, 32):
        _write(context, result + offset, 16, 0)


def _finish(
    context: ReplayTaskRebuildStorage,
    result: int,
    site: int,
    *,
    calls: ReplayTaskRebuildCalls,
    atomics: ReplayUnitAIMapAtomics,
) -> None:
    if _read(context, result + 24, 8):
        raise UnresolvedReplayTaskRebuild(
            f"saved object-list source{site:x} reached Result error metadata/TLS frontier"
        )
    _write(context, result + 40, 1, 1)
    control = _read(context, result + 32, 8)
    if control:
        _release(context, control, calls, atomics)
    _call(calls, 0x1402BD7F0, (result,))


def _input(
    context: ReplayTaskRebuildStorage,
    stream: int,
    result: int,
    destination: int,
    size: int,
    site: int,
    *,
    calls: ReplayTaskRebuildCalls,
    atomics: ReplayUnitAIMapAtomics,
) -> None:
    _zero(context, result)
    table = _read(context, stream, 8)
    _call(calls, _read(context, table + 24, 8), (stream, result, destination, size))
    _finish(context, result, site, calls=calls, atomics=atomics)


def read_replay_saved_object_list(
    context: ReplayTaskRebuildStorage,
    address: int,
    output: int,
    stream: int,
    resolver: int,
    *,
    calls: ReplayTaskRebuildCalls,
    atomics: ReplayUnitAIMapAtomics,
    bind_local: LocalBinding,
    scratch: ReplaySavedObjectListScratch,
) -> int:
    """Read allocation fields and terminating BYTE tags through actual factories.

    One signed current version gate controls both header reads and replacement
    allocation. Cleanup precedes the current capacity/old-array reads. The
    context is held for this whole list; each factory still loads current
    virtual dispatch. Constructor RAX is ignored and the fixed local Result is
    checked. No record-count limit, array zero fill or publication is invented.
    """
    _validate(context, calls, address, output, stream, resolver)
    if not isinstance(atomics, ReplayUnitAIMapAtomics) or not callable(bind_local):
        raise ValueError("actual saved object-list atomic/local providers required")
    if not isinstance(scratch, ReplaySavedObjectListScratch):
        raise ValueError("explicit saved object-list scratch required")
    with _local(memoryview(bytearray(scratch.reader)), bind_local) as frame:
        _write(context, frame + 0x70, 8, output)
        result = frame + 0x80
        if _signed(_read(context, 0x1440A0D94, 4), 4) >= 0xAFAE1:
            _input(
                context,
                stream,
                result,
                address + 0x14,
                4,
                0x14122B3DD,
                calls=calls,
                atomics=atomics,
            )
            _input(
                context,
                stream,
                result,
                address + 0x18,
                4,
                0x14122B5CF,
                calls=calls,
                atomics=atomics,
            )
            previous = _read(context, address + 8, 8)
            if previous:
                _call(calls, 0x142D6C270, (previous,))
            capacity = _signed(_read(context, address + 0x14, 4), 4) & _U64
            allocation = _call(calls, 0x142D6C268, (min(capacity * 8, _U64),), width=8)
            _write(context, address + 8, 8, allocation)
            _write(context, address + 0x1C, 1, 0)
        _write(context, address + 0x10, 4, 0)
        site = 0x14122B7AA
        while True:
            _input(context, stream, result, frame + 0x78, 1, site, calls=calls, atomics=atomics)
            kind = _read(context, frame + 0x78, 1)
            if not kind:
                for offset in (0, 8, 16, 24, 32):
                    _write(context, output + offset, 8, 0)
                _write(context, output + 40, 1, 0)
                return output
            _zero(context, result)
            table = _read(context, address, 8)
            _write(context, frame + 0x20, 8, resolver)
            _call(calls, _read(context, table, 8), (address, result, kind, stream, resolver))
            _finish(context, result, 0x14122B82E, calls=calls, atomics=atomics)
            site = 0x14122B89E


def bind_replay_saved_object_list(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    *,
    atomics: ReplayUnitAIMapAtomics,
    bind_local: LocalBinding,
    scratch: ReplaySavedObjectListScratch,
) -> ReplayTaskRebuildCalls:
    """Bind the complete normal reader; required current child effects delegate."""
    _validate(context, calls)
    if not isinstance(atomics, ReplayUnitAIMapAtomics) or not callable(bind_local):
        raise ValueError("actual saved object-list atomic/local providers required")
    if not isinstance(scratch, ReplaySavedObjectListScratch):
        raise ValueError("explicit saved object-list scratch required")

    def dispatch(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        if target != 0x14122B360:
            if calls.call is None:
                raise UnresolvedReplayTaskRebuild(f"reached{target:x} is unavailable")
            return calls.call(target, args, data)
        if len(args) != 4 or data is not None:
            raise ValueError("malformed saved object-list read call")
        return read_replay_saved_object_list(
            context, *args, calls=bound, atomics=atomics, bind_local=bind_local, scratch=scratch
        )

    bound = ReplayTaskRebuildCalls(dispatch)
    return bound
