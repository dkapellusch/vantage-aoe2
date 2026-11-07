"""Build54800 four saved Player handlers and three thin Player constructors.

Authority: player-registry-factory-source-v1; seven complete bodies(7,156B).
Handlers publish to the current World table before checking constructor status,
then select a current row again before calling its current Player reader.
Large Player construction/readers, allocation, shared counts and Result effects
remain mandatory. No registry population or current class identity is inferred.
Native stack identity, faults/EH/concurrency and reached error TLS are excluded.
"""

from __future__ import annotations

from dataclasses import dataclass

from .replay_saved_object_factory import _check_result, _copy_check, _initial_result
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
from .replay_unit_ai_map import ReplayUnitAIMapAtomics, _atomic, _release

_HANDLERS = {
    0x14174DF30: (0x16E8, 0x1432F6C30, 0x14174FA70),
    0x14174D850: (0x1400, 0x1432F6C08, 0x14174B740),
    0x14174E610: (0x1400, 0x1432F6BE0, 0x141755040),
    0x14174ECF0: (0x1400, 0x1432F6BB8, 0x1417551B0),
}
_CONSTRUCTORS = {
    0x14174B740: 0x1432F6628,
    0x141755040: 0x1432F72D8,
    0x1417551B0: 0x1432F76C8,
}


@dataclass(frozen=True, slots=True)
class ReplayPlayerSavedFactoryScratch:
    """Explicit D0/48-byte handler/constructor frames with live local aliases.

    Cookie and saved registers are excluded. The constructor's this home at40
    is explicitly stored before its low DWORD becomes the copied index. Other
    untouched bytes keep their supplied seed. Incoming argument homes and
    nested physical stack aliases are outside this logical interface.
    """

    handler: bytes
    constructor: bytes

    def __post_init__(self) -> None:
        for value, size in ((self.handler, 0xD0), (self.constructor, 0x48)):
            if type(value) is not bytes or len(value) != size:
                raise ValueError("explicit D0/48-byte saved Player frames required")


def construct_replay_saved_player_variant(
    context: ReplayTaskRebuildStorage,
    entry: int,
    subject: int,
    output: int,
    stream: int,
    world: int,
    index_pointer: int,
    *,
    calls: ReplayTaskRebuildCalls,
    bind_local: LocalBinding,
    scratch: ReplayPlayerSavedFactoryScratch,
) -> int:
    """Complete three60B wrappers; parent RAX does not replace held this."""
    _validate(context, calls, entry, subject, output, stream, world, index_pointer)
    if entry not in _CONSTRUCTORS:
        raise ValueError("unsupported saved Player wrapper constructor")
    if not isinstance(scratch, ReplayPlayerSavedFactoryScratch) or not callable(bind_local):
        raise ValueError("explicit saved Player frame and local binding required")
    with _local(memoryview(bytearray(scratch.constructor)), bind_local) as frame:
        _write(context, frame + 0x40, 8, subject)
        index = _read(context, index_pointer, 4)
        _write(context, frame + 0x20, 8, frame + 0x40)
        _write(context, frame + 0x40, 4, index)
        _call(calls, 0x1416C2440, (subject, output, stream, world, frame + 0x40))
        _write(context, subject, 8, _CONSTRUCTORS[entry])
        return subject


def _finish_result(
    context: ReplayTaskRebuildStorage,
    result: int,
    *,
    calls: ReplayTaskRebuildCalls,
    atomics: ReplayUnitAIMapAtomics,
) -> None:
    _write(context, result + 40, 1, 1)
    control = _read(context, result + 32, 8)
    if control:
        _release(context, control, calls, atomics)
    _call(calls, 0x1402BD890, (result,))


def create_replay_saved_player(
    context: ReplayTaskRebuildStorage,
    entry: int,
    receiver: int,
    output: int,
    stream: int,
    auxiliary: int,
    world: int,
    index_pointer: int,
    *,
    calls: ReplayTaskRebuildCalls,
    atomics: ReplayUnitAIMapAtomics,
    bind_local: LocalBinding,
    scratch: ReplayPlayerSavedFactoryScratch,
) -> int:
    """Normal four1744B handlers with actual publication and current reselection.

    No bounds or null-object check is added. A null allocation publishes10h
    and reaches its subsequent real reader access. Reached error TLS refuses
    after prior effects, without rollback. The fixed local reader Result is
    checked even when the reader returns another address.
    """
    _validate(context, calls, entry, receiver, output, stream, auxiliary, world, index_pointer)
    if entry not in _HANDLERS:
        raise ValueError("unsupported saved Player handler")
    if not isinstance(atomics, ReplayUnitAIMapAtomics) or not callable(bind_local):
        raise ValueError("actual saved Player shared counts and local binding required")
    if not isinstance(scratch, ReplayPlayerSavedFactoryScratch):
        raise ValueError("explicit saved Player factory scratch required")
    size, table, constructor = _HANDLERS[entry]
    with _local(memoryview(bytearray(scratch.handler)), bind_local) as frame:
        raw, temporary = frame + 0xA0, frame + 0x70
        _write(context, frame + 0x48, 8, output)
        _initial_result(context, raw)
        control = _call(calls, 0x142D6BA78, (size,), width=8)
        _write(context, frame + 0x38, 8, control)
        if control:
            _write(context, control, 16, 0)
            _write(context, control + 8, 4, 1)
            _write(context, control + 12, 4, 1)
            _write(context, control, 8, table)
            index = _read(context, index_pointer, 4)
            _write(context, frame + 0x48, 4, index)
            _write(context, frame + 0x20, 8, frame + 0x48)
            _call(calls, constructor, (control + 16, raw, stream, world, frame + 0x48))
        _write(context, frame + 0x38, 16, 0)
        obj = (control + 16) & ((1 << 64) - 1)
        _write(context, frame + 0x38, 8, obj)
        _write(context, frame + 0x40, 8, control)
        header = _call(calls, 0x141603FF0, (world,), width=8)
        index = _read(context, index_pointer, 4)
        row = _read(context, header, 8) + index * 16
        _write(context, row, 8, obj)
        old = _read(context, row + 8, 8)
        _write(context, row + 8, 8, control)
        if old:
            _release(context, old, calls, atomics)
        _check_result(context, temporary)
        acquired = _read(context, raw + 32, 8)
        _copy_check(context, raw, temporary, acquired, calls=calls, atomics=atomics)
        if _read(context, temporary + 24, 8):
            raise UnresolvedReplayTaskRebuild("saved Player constructor Result error TLS frontier")
        _finish_result(context, temporary, calls=calls, atomics=atomics)
        _write(context, frame + 0x38, 16, 0)
        header = _call(calls, 0x141603FF0, (world,), width=8)
        index = _read(context, index_pointer, 4)
        row = _read(context, header, 8) + index * 16
        acquired = _read(context, row + 8, 8)
        if acquired:
            _atomic(atomics, acquired + 8, 1)
        selected = _read(context, row, 8)
        _write(context, frame + 0x38, 8, selected)
        held_control = _read(context, row + 8, 8)
        _write(context, frame + 0x40, 8, held_control)
        for offset in (0, 16, 32):
            _write(context, temporary + offset, 16, 0)
        target = _read(context, _read(context, selected, 8) + 0xE8, 8)
        _call(calls, target, (selected, temporary, stream))
        if _read(context, temporary + 24, 8):
            raise UnresolvedReplayTaskRebuild("saved Player reader Result error TLS frontier")
        _finish_result(context, temporary, calls=calls, atomics=atomics)
        for offset in (0, 8, 16, 24, 32):
            _write(context, output + offset, 8, 0)
        _write(context, output + 40, 1, 0)
        if held_control:
            _release(context, held_control, calls, atomics)
        original = _read(context, raw + 32, 8)
        if original:
            _release(context, original, calls, atomics)
        _call(calls, 0x1402BD890, (raw,))
        return output


def bind_replay_player_saved_factory(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    *,
    atomics: ReplayUnitAIMapAtomics,
    bind_local: LocalBinding,
    scratch: ReplayPlayerSavedFactoryScratch,
) -> ReplayTaskRebuildCalls:
    """Bind seven entries, retaining every mandatory constructor/reader child."""
    _validate(context, calls)
    if not isinstance(atomics, ReplayUnitAIMapAtomics) or not callable(bind_local):
        raise ValueError("actual saved Player shared counts and local binding required")
    if not isinstance(scratch, ReplayPlayerSavedFactoryScratch):
        raise ValueError("explicit saved Player factory scratch required")

    def dispatch(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        if target not in _HANDLERS and target not in _CONSTRUCTORS:
            if calls.call is None:
                raise UnresolvedReplayTaskRebuild(f"reached{target:x} is unavailable")
            return calls.call(target, args, data)
        if len(args) != (6 if target in _HANDLERS else 5) or data is not None:
            raise ValueError("malformed saved Player handler/constructor call")
        if target in _CONSTRUCTORS:
            return construct_replay_saved_player_variant(
                context, target, *args, calls=bound, bind_local=bind_local, scratch=scratch
            )
        return create_replay_saved_player(
            context,
            target,
            *args,
            calls=bound,
            atomics=atomics,
            bind_local=bind_local,
            scratch=scratch,
        )

    bound = ReplayTaskRebuildCalls(dispatch)
    return bound
