"""Build54800 normal saved Stinger and unpack-timer reader bodies.

Full5190B1411281d0/1276B1410b1a40 source is frozen in
unit-saved-components-source-v1; unit-component-wrapper-source-v1 retains
the86B1416028d0 graphic fixup. Actual stream, Result forwarding/cleanup,
wrapper and old-graphic release children remain mandatory. Returned-error
decoration/logging, security cookies, native stack/register identity, faults,
concurrency and C++ EH are outside this logical normal profile.
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
_U32 = (1 << 32) - 1
_WRAPPED = (
    (0xC, 0x140B81D60, 0x11, 0x1432A4820),
    (0x10, 0x140B81D60, 0x12, 0x1432A482C),
    (0x14, 0x140B81D60, 0x13, 0x1432A4838),
    (0x18, 0x140D94310, 0x14, 0x1432A4848),
    (0x1C, 0x140B81D60, 0x15, 0x1432A4850),
    (0x20, 0x140B81D60, 0x16, 0x1432A4860),
    (0x24, 0x140B81D60, 0x17, 0x1432A4870),
)


@dataclass(frozen=True, slots=True)
class ReplayUnitSavedScratch:
    """Explicit local seeds, including unwritten gaps and reused Result slots.

    Logical RBP is stinger-frame+70 or timer-frame+60. All local views stay
    coherently mapped through return/failure; these are not native stack or
    register-save identities. Native cookie storage is not a simulation field.
    """

    stinger: bytes
    timer: bytes

    def __post_init__(self) -> None:
        if any(
            type(value) is not bytes or len(value) != size
            for value, size in ((self.stinger, 0x90), (self.timer, 0x80))
        ):
            raise ValueError("explicit90/80-byte Stinger/timer local seeds required")


def _admit(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    atomics: ReplayUnitAIMapAtomics,
    bind_local: LocalBinding,
    scratch: ReplayUnitSavedScratch,
    *arguments: int,
) -> None:
    _validate(context, calls, *arguments)
    if not isinstance(atomics, ReplayUnitAIMapAtomics) or not callable(bind_local):
        raise ValueError("actual saved component atomic/local bindings required")
    if not isinstance(scratch, ReplayUnitSavedScratch):
        raise ValueError("explicit saved component local seeds required")


def _zero(context: ReplayTaskRebuildStorage, result: int) -> None:
    for offset in (0, 16, 32):
        _write(context, result + offset, 16, 0)


def _release_result(
    context: ReplayTaskRebuildStorage,
    result: int,
    calls: ReplayTaskRebuildCalls,
    atomics: ReplayUnitAIMapAtomics,
) -> None:
    control = _read(context, result + 32, 8)
    if control:
        _release(context, control, calls, atomics)
    _call(calls, 0x1402BD890, (result,))


def _finish(
    context: ReplayTaskRebuildStorage,
    aggregate: int,
    calls: ReplayTaskRebuildCalls,
    atomics: ReplayUnitAIMapAtomics,
) -> None:
    if _read(context, aggregate + 24, 8):
        raise UnresolvedReplayTaskRebuild(
            "saved component reached forwarded-error/logging frontier"
        )
    _write(context, aggregate + 40, 1, 1)
    _release_result(context, aggregate, calls, atomics)


def _raw_read(
    context: ReplayTaskRebuildStorage,
    stream: int,
    destination: int,
    width: int,
    aggregate: int,
    raw: int,
    calls: ReplayTaskRebuildCalls,
    atomics: ReplayUnitAIMapAtomics,
) -> None:
    _zero(context, aggregate)
    _zero(context, raw)
    target = _read(context, _read(context, stream, 8) + 24, 8)
    _call(calls, target, (stream, raw & _U64, destination & _U64, width))
    # The second aggregate clear and raw processed store precede the test.
    _zero(context, aggregate)
    _write(context, raw + 40, 1, 1)
    if _read(context, raw + 24, 8):
        raise UnresolvedReplayTaskRebuild("saved component reached raw-error/decoration frontier")
    _call(calls, 0x1409076B0, (aggregate & _U64, raw & _U64))
    _release_result(context, raw, calls, atomics)
    _finish(context, aggregate, calls, atomics)


def _wrapped_read(
    context: ReplayTaskRebuildStorage,
    stream: int,
    destination: int,
    bp: int,
    target: int,
    line: int,
    field: int,
    calls: ReplayTaskRebuildCalls,
    atomics: ReplayUnitAIMapAtomics,
) -> None:
    aggregate = bp - 0x49
    _zero(context, aggregate)
    _write(context, bp - 0x61, 8, destination & _U64)
    _write(context, bp - 0x69, 8, stream)
    _call(calls, target, (aggregate & _U64, 0x1432A47C0, line, field, stream, destination & _U64))
    _finish(context, aggregate, calls, atomics)


def _output(context: ReplayTaskRebuildStorage, output: int) -> int:
    for offset in (0, 8, 16, 24, 32):
        _write(context, output + offset, 8, 0)
    _write(context, output + 40, 1, 0)
    return output


def read_replay_saved_stinger(
    context: ReplayTaskRebuildStorage,
    address: int,
    output: int,
    stream: int,
    *,
    calls: ReplayTaskRebuildCalls,
    atomics: ReplayUnitAIMapAtomics,
    bind_local: LocalBinding,
    scratch: ReplayUnitSavedScratch,
) -> int:
    """Normal1411281d0, preserving both local Results and real resolution.

    The current version gate occurs only after graphic resolution. Its old
    branch stores rawFFFFFFFF to record+8; the new branch requires the real
    wrapper. No record padding or graphic pointer is synthesized. Earlier
    I/O, local/control effects and mandatory child writes survive failure.
    """
    _admit(context, calls, atomics, bind_local, scratch, address, output, stream)
    with _local(memoryview(bytearray(scratch.stinger)), bind_local) as frame:
        bp = frame + 0x70
        _write(context, bp - 0x51, 8, output)
        aggregate, raw = bp - 0x49, bp - 0x11
        for offset in (0, 4):
            _raw_read(context, stream, address + offset, 4, aggregate, raw, calls, atomics)
        for offset, target, line, field in _WRAPPED:
            _wrapped_read(
                context, stream, address + offset, bp, target, line, field, calls, atomics
            )
        _write(context, bp - 0x19, 2, 0xFFFF)
        _raw_read(context, stream, bp - 0x19, 2, aggregate, raw, calls, atomics)
        game = _read(context, 0x144353698, 8)
        world = _call(calls, 0x140D6ACC0, (game,), width=8)
        sprite = _signed(_read(context, bp - 0x19, 2), 2) & _U32
        _call(calls, 0x1416028D0, (world, (address + 0x30) & _U64, sprite))
        time = (address + 8) & _U64
        if _signed(_read(context, 0x1440A0D94, 4), 4) >= 0x433333:
            _wrapped_read(context, stream, time, bp, 0x140B81D60, 0x1E, 0x1432A488C, calls, atomics)
        else:
            _write(context, time, 4, _U32)
        return _output(context, output)


def read_replay_saved_unpack_timer(
    context: ReplayTaskRebuildStorage,
    address: int,
    output: int,
    stream: int,
    *,
    calls: ReplayTaskRebuildCalls,
    atomics: ReplayUnitAIMapAtomics,
    bind_local: LocalBinding,
    scratch: ReplayUnitSavedScratch,
) -> int:
    """Normal1410b1a40: WORD0 then DWORD4; no version read or padding reset."""
    _admit(context, calls, atomics, bind_local, scratch, address, output, stream)
    with _local(memoryview(bytearray(scratch.timer)), bind_local) as frame:
        bp = frame + 0x60
        _write(context, bp - 0x51, 8, output)
        for offset, width in ((0, 2), (4, 4)):
            _raw_read(
                context, stream, address + offset, width, bp - 0x49, bp - 0x19, calls, atomics
            )
        return _output(context, output)


def fixup_replay_saved_graphic(
    context: ReplayTaskRebuildStorage,
    world: int,
    output: int,
    identifier: int,
    *,
    calls: ReplayTaskRebuildCalls,
) -> None:
    """Full86B1416028d0; old-pointer release precedes signed raw32 ID checks.

    Only a nonnull in-range current table entry causes a direct output store.
    Negative/out-of-range IDs and null entries retain the slot's current value,
    including real child mutations. The held ID/output/World identities do not
    reload, while the World bound/table and selected entry are current reads.
    """
    _validate(context, calls, world, output, identifier)
    index = _signed(identifier & _U32, 4)
    previous = _read(context, output, 8)
    if previous:
        _call(calls, 0x1409CCE80, (previous, 0))
    if index < 0:
        return
    if index >= _signed(_read(context, world + 0xD0, 4), 4):
        return
    table = _read(context, world + 0xC0, 8)
    graphic = _read(context, table + index * 8, 8)
    if graphic:
        _write(context, output, 8, graphic)


def bind_replay_unit_saved_components(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    *,
    atomics: ReplayUnitAIMapAtomics,
    bind_local: LocalBinding,
    scratch: ReplayUnitSavedScratch,
) -> ReplayTaskRebuildCalls:
    """Bind two readers and the actual three-argument graphic-fixup entry."""
    _admit(context, calls, atomics, bind_local, scratch)

    def dispatch(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        if target not in (0x1411281D0, 0x1410B1A40, 0x1416028D0):
            if calls.call is None:
                raise UnresolvedReplayTaskRebuild(f"reached{target:x} is unavailable")
            return calls.call(target, args, data)
        if len(args) != 3 or data is not None:
            raise ValueError("malformed saved component reader call")
        if target == 0x1416028D0:
            fixup_replay_saved_graphic(context, *args, calls=bound)
            return None
        function = (
            read_replay_saved_stinger if target == 0x1411281D0 else read_replay_saved_unpack_timer
        )
        return function(
            context, *args, calls=bound, atomics=atomics, bind_local=bind_local, scratch=scratch
        )

    bound = ReplayTaskRebuildCalls(dispatch)
    return bound
