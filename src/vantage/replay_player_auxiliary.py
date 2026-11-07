"""Build54800 complete218B auxiliary constructor14149d9a0.

The actual35008B1414aea70 reader remains a mandatory unprovided child. Ten
ordered stores initialize45 of72 object bytes; no implicit memset, null-stream
Result or reader success is invented. Source: player-derived-post-flags-source-v1.
Native physical stack/EH/fault/concurrency parity and full restoration are excluded.
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
class ReplayPlayerAuxiliaryScratch:
    """Explicit live48B logical Result seed; no zero or padding values inferred."""

    frame: bytes

    def __post_init__(self) -> None:
        if type(self.frame) is not bytes or len(self.frame) != 48:
            raise ValueError("explicit48-byte auxiliary Result scratch required")


def construct_replay_player_auxiliary(
    context: ReplayTaskRebuildStorage,
    address: int,
    output: int,
    stream: int,
    *,
    calls: ReplayTaskRebuildCalls,
    atomics: ReplayUnitAIMapAtomics,
    bind_local: LocalBinding,
    scratch: ReplayPlayerAuxiliaryScratch,
) -> int:
    """Whole218B14149d9a0; actual returned Result and fixed-local cleanup differ.

    Null stream skips explicit output access and local binding. Subject/output
    aliases still observe the ten source stores. Nonnull stream preserves the
    current returned begin/end after pair mutation, current fixed-local control,
    actual atomics/virtuals and finalizer, with no output-status guard.
    """
    _validate(context, calls, address, output, stream)
    if not isinstance(atomics, ReplayUnitAIMapAtomics) or not callable(bind_local):
        raise ValueError("actual auxiliary atomic and local bindings required")
    if not isinstance(scratch, ReplayPlayerAuxiliaryScratch):
        raise ValueError("explicit auxiliary Result scratch required")
    for offset, width, value in (
        (8, 8, 0),
        (24, 8, 0),
        (40, 8, 0),
        (56, 8, 0),
        (0, 1, 0),
        (16, 1, 0),
        (32, 2, 0),
        (48, 1, 0),
        (64, 4, 0xFFFFFFFF),
        (68, 4, 0),
    ):
        _write(context, address + offset, width, value)
    if not stream:
        return address
    with _local(memoryview(bytearray(scratch.frame)), bind_local) as temporary:
        returned = _call(calls, 0x1414AEA70, (address, temporary, stream), width=8)
        _write(context, returned + 0x28, 1, 1)
        _call(calls, 0x14090D270, ((output + 0x18) & _U64, (returned + 0x18) & _U64))
        if output != returned:
            begin = _read(context, returned, 8)
            end = _read(context, returned + 8, 8)
            count = (_signed((end - begin) & _U64, 8) >> 5) & _U64
            _call(calls, 0x1402B9080, (output, begin, count))
        _write(context, output + 0x28, 1, 0)
        control = _read(context, temporary + 0x20, 8)
        if control:
            _release(context, control, calls, atomics)
        _call(calls, 0x1402BD890, (temporary,))
        return address


def bind_replay_player_auxiliary(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    *,
    atomics: ReplayUnitAIMapAtomics,
    bind_local: LocalBinding,
    scratch: ReplayPlayerAuxiliaryScratch,
) -> ReplayTaskRebuildCalls:
    """Bind only14149d9a0; the large reader and every reached child delegate."""
    _validate(context, calls)
    if not isinstance(atomics, ReplayUnitAIMapAtomics) or not callable(bind_local):
        raise ValueError("actual auxiliary atomic and local bindings required")
    if not isinstance(scratch, ReplayPlayerAuxiliaryScratch):
        raise ValueError("explicit auxiliary Result scratch required")

    def dispatch(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        if target != 0x14149D9A0:
            if calls.call is None:
                raise UnresolvedReplayTaskRebuild(f"reached{target:x} is unavailable")
            return calls.call(target, args, data)
        if len(args) != 3 or data is not None:
            raise ValueError("malformed auxiliary constructor call")
        return construct_replay_player_auxiliary(
            context, *args, calls=bound, atomics=atomics, bind_local=bind_local, scratch=scratch
        )

    bound = ReplayTaskRebuildCalls(dispatch)
    return bound
