"""Source-shaped BaseWorld entry, clock admission and maintenance phase.

Build54800 source141628bf0..141628f0c and idle14162ba3c..14162ba59;
825B/182 instructions including the excluded physical prologue. This component
returns the real idle status or an explicit recording-phase handoff. It owns
no complete World entry, replay processing, player work or successful tick.
"""

from __future__ import annotations

from dataclasses import dataclass

from .replay_binary32 import multiply_binary32, unsigned64_binary32
from .replay_task_containers import _cvtt64
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

_U32, _U64 = (1 << 32) - 1, (1 << 64) - 1
_GAME, _CLOCK = 0x144353698, 0x228


@dataclass(frozen=True, slots=True)
class ReplayWorldUpdatePrelude:
    """Held prefix results; a normal handoff is never a completed World step.

    The same current logical frame must continue into later phases. Its
    reached homes retain their stores and untouched bytes remain undefined.
    entry_time, cycle and incoming_status are raw DWORDs. Only an idle return
    has returned_status; otherwise next_address is141628f0c.
    """

    world: int
    logical_frame: int
    entry_time: int
    cycle: int
    incoming_status: int
    next_address: int | None
    returned_status: int | None


def _time(context: ReplayTaskRebuildStorage, calls: ReplayTaskRebuildCalls, world: int) -> int:
    return _call(calls, 0x140E68F70, (_read(context, world + _CLOCK, 8),), width=4)


def run_replay_world_update_prelude(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    world: int,
    incoming_status: int,
    *,
    logical_frame: int,
    mxcsr: int,
) -> ReplayWorldUpdatePrelude:
    """Execute the complete admitted entry/clock/maintenance phase in order.

    Actual children use their original targets and effective scalar arguments;
    floating returns/arguments are raw binary32 words, AL predicates raw u64.
    Host clock returns are raw u64; each reached EAX consumer narrows to DWORD.
    The clock/factor binding supplies its methods when routed by the caller.
    Host timing, cycle selection, logging, strings, save and pause predicates
    remain mandatory actual calls when reached. No providers/backing/defaults
    are supplied here, and every earlier effect survives reached refusal.

    logical_frame is an explicitly backed owned address corresponding to
    post-prologue RSP; logical RBP is frame+100. Current storage aliases and
    partial stores are preserved, including logging argument homes. Only the
    source's reached stores occur. Callee-save/security-cookie/physical XMM
    state, FP status/traps, native faults/unwind and threads are excluded.
    MXCSR requires masked nearest-even with DAZ/FTZ off. A reached zero signed
    divisor refuses explicitly instead of claiming native division-fault parity.
    No callback-recursion or later World-loop budget is inferred by this phase.
    """
    _validate(context, calls, world, incoming_status, logical_frame)
    _unsigned(mxcsr, 4, "MXCSR")
    if mxcsr & ~0x3F != 0x1F80:
        raise ValueError("masked nearest-even MXCSR, DAZ/FTZ off required")
    incoming_status &= _U32
    frame = logical_frame
    _write(context, frame + 0x208, 4, 0)
    _call(calls, 0x14151E9C0, ())
    entry = _time(context, calls, world)
    rate = _call(calls, 0x140E68F50, (_read(context, world + _CLOCK, 8),), width=4)
    scaled = multiply_binary32(unsigned64_binary32(_read(context, world + 0x7D4, 4)), rate)
    _write(context, world + 0x7D8, 4, _cvtt64(scaled))
    first_host = _call(calls, 0x140A71140, (), width=8) & _U32
    manager = _read(context, world + 0x130, 8)
    manager = _read(context, manager + 0x2008, 8) if manager else 0
    cycle = _call(calls, 0x140E0E530, (manager,), width=4) if manager else 0
    held_game = _read(context, _GAME, 8)
    second_host = _call(calls, 0x140A71140, (), width=8) & _U32
    _call(calls, 0x140D68190, (held_game, 0xE, (second_host - first_host) & _U32))
    admitted = bool(cycle) or bool(_read(context, _read(context, _GAME, 8) + 0x225, 1))
    if admitted:
        end = _read(context, world + 0x770, 8)
        begin = _read(context, world + 0x768, 8)
        admitted = bool(_signed((end - begin) & _U64, 8) >> 4)
    if not admitted:
        _write(context, world + 0x7C, 4, 0)
        if _read(context, 0x1442C40F0, 4):
            _write(context, world + 0x88, 4, 1)
        result = _read(context, world + 0x88, 4)
        return ReplayWorldUpdatePrelude(world, frame, entry, cycle, incoming_status, None, result)

    if _read(context, 0x144355062, 1):
        _write(context, frame + 0x80, 4, 7)
        _write(context, frame + 0x78, 4, cycle)
        _write(context, frame + 0x2B0, 8, frame + 0x78)
        _write(context, frame + 0x20, 8, frame + 0x2B0)
        _call(
            calls,
            0x14101ADB0,
            (
                _read(context, 0x144355068, 8),
                0x2A,
                0x1432EA140,
                1,
                (frame + 0x2B0) & _U64,
            ),
        )
    _write(context, 0x144418594, 4, 0)
    now = _call(calls, 0x140A71140, (), width=8) & _U32
    if cycle == _U32:
        previous = _read(context, world + 0x84, 4)
        delta = min(100, (now - previous) & _U32) if previous else 0
    else:
        delta = cycle
    if (
        _read(context, _read(context, _GAME, 8) + 0x225, 1)
        and not _call(calls, 0x140E7E9C0, (), width=8) & 0xFF
    ):
        divisor = _signed(_read(context, 0x1431FE898, 4), 4)
        if not divisor:
            raise UnresolvedReplayTaskRebuild("World clock signed divisor is zero")
        delta = (1000 // abs(divisor)) * (-1 if divisor < 0 else 1)
    if _read(context, 0x1442C3FC4, 4):
        delta = _cvtt64(
            multiply_binary32(
                _read(context, 0x143DAE26C, 4),
                _read(context, 0x1436A02E0, 4),
            )
        )
    _write(context, world + 0x84, 4, now)
    _write(context, world + 0x78, 4, _time(context, calls, world))
    if not _call(calls, 0x140E7E9C0, (), width=8) & 0xFF or cycle != _U32:
        _call(
            calls,
            0x140E68C40,
            (
                _read(context, world + _CLOCK, 8),
                unsigned64_binary32(delta & _U32),
            ),
        )
    _call(calls, 0x1409033B0, (_time(context, calls, world),))
    external = _read(context, 0x1442846E8, 8)
    if external:
        _call(calls, 0x1409733F0, (external,))
    if _read(context, 0x144418DC8, 1):
        descriptor = _call(calls, 0x140E15770, (_read(context, 0x1442C3F98, 8),), width=8)
        if _read(context, descriptor, 1):
            if _read(context, 0x144418E98, 1):
                _write(context, frame + 0x218, 8, 0x14428BB30)
                _write(context, frame + 0x220, 8, 0)
                _write(context, frame + 0x228, 8, 0)
                string = (frame + 0x218) & _U64
                _call(calls, 0x140A15B60, (string, 0x144418EA0))
                threshold_word = _call(calls, 0x140A1FDF0, (string, 0), width=4)
                _call(calls, 0x140A1B220, (string,))
                threshold = _cvtt64(threshold_word) & _U32
            else:
                threshold = 600000
            current = _time(context, calls, world)
            if ((current - _read(context, world + 0x90, 4)) & _U32) > threshold:
                returned_world = _call(calls, 0x140D6ACC0, (_read(context, _GAME, 8),), width=8)
                _call(calls, 0x140F4AD30, (_read(context, returned_world + 0x130, 8),))
                _write(context, world + 0x90, 4, _time(context, calls, world))
    return ReplayWorldUpdatePrelude(world, frame, entry, cycle, incoming_status, 0x141628F0C, None)
