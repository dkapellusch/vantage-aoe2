"""Build54800 complete normal1141B behavior-list saved reader140b88c50.

Authority: action-saved-reader-source-review-v1 and full original C/ASM.
Current stream, payload/manager virtuals, IAT allocation/free, Result forwarding
and atomic cleanup require actual bindings. Tag errors refuse before excluded
metadata/TLS decoration. Native physical stack/register/cookie/fault/EH and
concurrent behavior, full object restoration and World parity are not inferred.
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

_ENTRY = 0x140B88C50


@dataclass(frozen=True, slots=True)
class ReplayBehaviorSavedScratch:
    """Explicit D0-byte logical frame; RBP=post-prologue RSP+D9.

    Held output is also stored at60, the initially unwritten tag WORD is68,
    tag Result48 is70 and item Result48 isA0. Unwritten bytes retain the seed.
    Cookie/FP/register saves, physical nested-frame overlap and escaped locals
    after return are excluded; no initial tag0 or frame-padding0 is assumed.
    """

    reader: bytes

    def __post_init__(self) -> None:
        if type(self.reader) is not bytes or len(self.reader) != 0xD0:
            raise ValueError("explicit D0-byte behavior reader local seed required")


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


def _tag(
    context: ReplayTaskRebuildStorage,
    stream: int,
    result: int,
    destination: int,
    calls: ReplayTaskRebuildCalls,
    atomics: ReplayUnitAIMapAtomics,
) -> int:
    for offset in (0, 16, 32):
        _write(context, result + offset, 16, 0)
    vptr = _read(context, stream, 8)
    _call(calls, _read(context, vptr + 0x18, 8), (stream, result, destination, 2))
    if _read(context, result + 0x18, 8):
        raise UnresolvedReplayTaskRebuild(
            "behavior tag read reached error metadata/TLS decoration frontier"
        )
    _write(context, result + 0x28, 1, 1)
    _cleanup(context, result, calls, atomics)
    return _read(context, destination, 2)


def read_replay_saved_behavior(
    context: ReplayTaskRebuildStorage,
    manager: int,
    output: int,
    stream: int,
    *,
    calls: ReplayTaskRebuildCalls,
    atomics: ReplayUnitAIMapAtomics,
    bind_local: LocalBinding,
    scratch: ReplayBehaviorSavedScratch,
) -> int:
    """Complete normal293-instruction reader, with real reached child effects.

    Old head publication precedes destruction/free and current owner/next-head
    activation. Append holds payload and tail across callbacks. Item errors
    invoke real1409076b0, release/890 and return without fake output success.
    Partial effects survive failures; no list rollback or blanket cleanup is
    added. Finite current lists and a terminating actual tag stream are inputs.
    """
    _validate(context, calls, manager, output, stream)
    if not isinstance(atomics, ReplayUnitAIMapAtomics) or not callable(bind_local):
        raise ValueError("actual behavior atomic/local providers required")
    if not isinstance(scratch, ReplayBehaviorSavedScratch):
        raise ValueError("explicit behavior reader local seed required")
    with _local(memoryview(bytearray(scratch.reader)), bind_local) as frame:
        _write(context, frame + 0x60, 8, output)
        node = _read(context, manager + 0x10, 8)
        while node:
            following = _read(context, node + 8, 8)
            _write(context, manager + 0x10, 8, following)
            payload = _read(context, node, 8)
            if payload:
                target = _read(context, _read(context, payload, 8), 8)
                _call(calls, target, (payload, 1))
            _call(calls, _read(context, 0x143199DD0, 8), (node,))
            current_head = _read(context, manager + 0x10, 8)
            if current_head:
                owner = _read(context, manager + 8, 8)
                if _read(context, owner + 0x188, 1) < 3:
                    payload = _read(context, current_head, 8)
                    target = _read(context, _read(context, payload, 8) + 0x28, 8)
                    _call(calls, target, (payload, 0))
            node = _read(context, manager + 0x10, 8)
        tail = 0
        tag_result, item_result = frame + 0x70, frame + 0xA0
        tag = _tag(context, stream, tag_result, frame + 0x68, calls, atomics)
        while tag:
            # Actual nonascending preclear and two redundant scalar stores.
            for offset in (32, 0, 16):
                _write(context, item_result + offset, 16, 0)
            _write(context, item_result + 32, 8, 0)
            _write(context, item_result + 40, 1, 0)
            target = _read(context, _read(context, manager, 8) + 8, 8)
            payload = _call(calls, target, (manager, item_result, stream, tag), width=8)
            _write(context, item_result + 40, 1, 1)
            if _read(context, item_result + 24, 8):
                _call(calls, 0x1409076B0, (output, item_result))
                _cleanup(context, item_result, calls, atomics)
                return output
            node = _call(calls, _read(context, 0x143199DC0, 8), (1, 16), width=8)
            _write(context, node, 8, payload)
            _write(context, node + 8, 8, 0)
            if tail:
                _write(context, tail + 8, 8, node)
            else:
                _write(context, manager + 0x10, 8, node)
            tail = node
            _cleanup(context, item_result, calls, atomics)
            tag = _tag(context, stream, tag_result, frame + 0x68, calls, atomics)
        for offset in (0, 8, 16, 24, 32):
            _write(context, output + offset, 8, 0)
        _write(context, output + 40, 1, 0)
        return output


def bind_replay_behavior_saved(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    *,
    atomics: ReplayUnitAIMapAtomics,
    bind_local: LocalBinding,
    scratch: ReplayBehaviorSavedScratch,
) -> ReplayTaskRebuildCalls:
    """Bind only140b88c50; current IAT and all other children delegate/refuse."""
    _validate(context, calls)
    if not isinstance(atomics, ReplayUnitAIMapAtomics) or not callable(bind_local):
        raise ValueError("actual behavior atomic/local providers required")
    if not isinstance(scratch, ReplayBehaviorSavedScratch):
        raise ValueError("explicit behavior reader local seed required")

    def dispatch(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        if target != _ENTRY:
            if calls.call is None:
                raise UnresolvedReplayTaskRebuild(f"reached{target:x} is unavailable")
            return calls.call(target, args, data)
        if len(args) != 3 or data is not None:
            raise ValueError("malformed behavior saved reader call")
        return read_replay_saved_behavior(
            context,
            *args,
            calls=bound,
            atomics=atomics,
            bind_local=bind_local,
            scratch=scratch,
        )

    bound = ReplayTaskRebuildCalls(dispatch)
    return bound
