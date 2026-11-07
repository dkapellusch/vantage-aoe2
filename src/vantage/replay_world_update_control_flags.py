"""World caller interval [141629b2a,141629c59),303B/76 instructions.

The accepted SpecialMode frame and historical metadata remain live. Actual
children/current backing are mandatory; the result is a c59 handoff only.
"""

from __future__ import annotations

from dataclasses import dataclass

from .replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
    _read,
    _signed,
    _unsigned,
    _write,
)
from .replay_unit_ai_base import _validate
from .replay_world_update_special_mode import ReplayWorldUpdateSpecialMode

_U32, _U64 = (1 << 32) - 1, (1 << 64) - 1
_OPTIONS, _RELEASE = 0x140D6A530, 0x140990140


@dataclass(frozen=True, slots=True)
class ReplayWorldUpdateControlFlags:
    """Same-frame c59 continuation; held flags differ from current frame208."""

    world: int
    logical_frame: int
    entry_time: int
    cycle: int
    status: int
    default_time: int
    control_flags: int
    next_address: int | None
    returned_status: int | None


def _invoke(
    calls: ReplayTaskRebuildCalls,
    target: int,
    args: tuple[int, ...],
) -> int | None:
    if calls.call is None:
        raise UnresolvedReplayTaskRebuild(f"reached{target:x} is unavailable")
    return calls.call(target, tuple(value & _U64 for value in args), None)


def _rax(calls: ReplayTaskRebuildCalls, target: int, args: tuple[int, ...]) -> int:
    value = _invoke(calls, target, args)
    if value is None:
        raise ValueError(f"helper{target:x} must supply raw RAX at source consumer")
    _unsigned(value, 8, f"helper{target:x} raw RAX")
    return value


def run_replay_world_update_control_flags(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    phase: ReplayWorldUpdateSpecialMode,
) -> ReplayWorldUpdateControlFlags:
    """Complete303B caller, preserving source-held flags and live output cells.

    Raw64 child results are validated before explicit EAX/AL consumption;
    ignored returns remain opaque. No local mapping, seed, FP policy, default
    service or full-tick status is introduced. Physical registers/stack, native
    faults/EH/concurrency and unclosed child incidental ABI are excluded.
    Actual provider refusal preserves preceding source effects.
    """
    if not isinstance(phase, ReplayWorldUpdateSpecialMode):
        raise ValueError("actual SpecialMode handoff required")
    if phase.returned_status is not None or phase.next_address != 0x141629B2A:
        raise ValueError("SpecialMode must hand off at141629b2a")
    world, frame = phase.world, phase.logical_frame
    entry, cycle = phase.entry_time, phase.cycle
    status, default, flags = phase.status, phase.default_time, phase.control_flags
    _validate(context, calls, world, frame)
    for value in (entry, cycle, status, default, flags):
        _unsigned(value, 4, "held World SpecialMode DWORD")

    first = int((_rax(calls, 0x14097FB40, (_read(context, 0x14425B930, 8), 0x91)) & _U32) == 1)
    if _read(context, world + 0x6C7, 1) != first:
        index = _read(context, world + 0x6B0, 4)
        receiver = 0
        if _read(context, 0x143DA5054, 4) != index:
            begin = _read(context, world + 0x768, 8)
            end = _read(context, world + 0x770, 8)
            count = (_signed((end - begin) & _U64, 8) >> 4) & _U64
            if index < count:
                receiver = _read(context, begin + index * 16, 8)
        _invoke(calls, 0x1416DFB20, (receiver, first))
        _write(context, world + 0x6C7, 1, first)
    _write(context, frame + 0x70, 1, 0)
    second = False
    if _rax(calls, 0x140E68F70, (_read(context, world + 0x228, 8),)) & _U32:
        returned = _rax(calls, _OPTIONS, (_read(context, 0x144353698, 8), frame + 0x60))
        flags = 1
        _write(context, frame + 0x208, 4, flags)
        if _read(context, _read(context, returned, 8) + 0x34, 4) == 0xD:
            second = True
        else:
            returned = _rax(calls, _OPTIONS, (_read(context, 0x144353698, 8), frame + 0x2B0))
            flags = 3
            _write(context, frame + 0x208, 4, flags)
            second = bool(_rax(calls, 0x1413F7A00, (_read(context, returned, 8) + 0x18,)) & 1)
    if flags & 2:
        flags &= 0xFFFFFFFD
        _write(context, frame + 0x208, 4, flags)
        token = _read(context, frame + 0x2B0, 8)
        if token:
            _invoke(calls, _RELEASE, (token,))
    if flags & 1:
        token = _read(context, frame + 0x60, 8)
        if token:
            _invoke(calls, _RELEASE, (token,))
    if second and not _read(context, world + 0x6C6, 1):
        _write(context, world + 0x6C6, 1, 1)
        _write(context, frame + 0x70, 1, 1)
    return ReplayWorldUpdateControlFlags(
        world,
        frame,
        entry,
        cycle,
        status,
        default,
        flags,
        0x141629C59,
        None,
    )
