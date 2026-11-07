"""World caller [141629c59,141629e00),423B/92 instructions.

Primary c59 and source-qualified c90 re-entry share the existing World frame.
The result preserves held words at e00/ab9e; neither is a completed tick.
"""

from __future__ import annotations

from dataclasses import dataclass

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
from .replay_world_update_control_flags import ReplayWorldUpdateControlFlags

_U32, _U64 = (1 << 32) - 1, (1 << 64) - 1
_LITERAL = 0x61501AA6ECFD980A
_RELATIONSHIP = 0x141734D70


@dataclass(frozen=True, slots=True)
class ReplayWorldUpdatePlayerLinksReentry:
    """Actual ab8e -> c90 held state; R14zero is a source-profile premise."""

    world: int
    logical_frame: int
    entry_time: int
    cycle: int
    status: int
    default_time: int
    control_flags: int
    outer_index: int
    xmm8_word: int
    next_address: int | None
    returned_status: int | None


@dataclass(frozen=True, slots=True)
class ReplayWorldUpdatePlayerLinks:
    """Same-frame boundary state, with None for unprovided incoming words."""

    world: int
    logical_frame: int
    entry_time: int
    cycle: int
    status: int
    default_time: int
    control_flags: int
    outer_index: int
    held_r13: int
    raw_count: int
    held_begin: int | None
    xmm8_word: int | None
    inner_index: int | None
    marker_address: int | None
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


def _count(end: int, begin: int) -> int:
    return (_signed((end - begin) & _U64, 8) >> 4) & _U64


def run_replay_world_update_player_links(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    phase: ReplayWorldUpdateControlFlags | ReplayWorldUpdatePlayerLinksReentry,
    *,
    logger_home_calls: ReplayTaskRebuildCalls,
    relationship_calls: ReplayTaskRebuildCalls,
    virtual_calls: ReplayTaskRebuildCalls,
) -> ReplayWorldUpdatePlayerLinks:
    """Complete423B caller over current storage and explicit real services.

    Relationship args annotate RCX/RDX and known R8value/mask (1,ff), with
    an actual AL-byte result. Its real188 provider must explicitly bind the
    per-invocation count_home=phase.logical_frame; frame94/90 do not identify
    that shared parent0 home. Logger's fifth annotation is HOME20's address.
    The virtual channel receives prepared RCX/RDX only and must refuse if
    other required ABI is unavailable. There is no normal-channel fallback.

    Ignored returns stay opaque. Current backing, actual descendants and
    finite source-loop progress are premises; no mapping, seed, count clamp,
    loop cap, fabricated success or next-phase effect is supplied. Native
    physical GP/stack, faults/EH/concurrency and other unowned lanes are
    excluded. The raw MOVSS load requires no FP arithmetic policy.
    """
    if not isinstance(phase, (ReplayWorldUpdateControlFlags, ReplayWorldUpdatePlayerLinksReentry)):
        raise ValueError("actual ControlFlags or source-qualified player-links reentry required")
    primary = isinstance(phase, ReplayWorldUpdateControlFlags)
    expected = 0x141629C59 if primary else 0x141629C90
    if (
        type(phase.next_address) is not int
        or phase.next_address != expected
        or phase.returned_status is not None
    ):
        raise ValueError("player-links phase must hand off at actual c59 or c90 entry")
    world, frame = phase.world, phase.logical_frame
    entry, cycle = phase.entry_time, phase.cycle
    status, default, flags = phase.status, phase.default_time, phase.control_flags
    _validate(context, calls, world, frame)
    for value in (entry, cycle, status, default, flags):
        _unsigned(value, 4, "held World player-links DWORD")
    if any(
        not isinstance(channel, ReplayTaskRebuildCalls)
        for channel in (
            logger_home_calls,
            relationship_calls,
            virtual_calls,
        )
    ):
        raise ValueError("actual logger HOME, relationship and virtual channels required")
    if isinstance(phase, ReplayWorldUpdatePlayerLinksReentry):
        _unsigned(phase.outer_index, 4, "held reentry outer index")
        _unsigned(phase.xmm8_word, 4, "held reentry XMM8 word")

    def handoff(
        outer_index: int,
        held_r13: int,
        raw_count: int,
        held_begin: int | None,
        xmm8_word: int | None,
        inner_index: int | None,
        marker_address: int | None,
        next_address: int,
    ) -> ReplayWorldUpdatePlayerLinks:
        return ReplayWorldUpdatePlayerLinks(
            world,
            frame,
            entry,
            cycle,
            status,
            default,
            flags,
            outer_index,
            held_r13,
            raw_count,
            held_begin,
            xmm8_word,
            inner_index,
            marker_address,
            next_address,
            None,
        )

    if isinstance(phase, ReplayWorldUpdateControlFlags):
        outer = 0
        _write(context, frame + 0x210, 4, 0)
        end = _read(context, world + 0x770, 8)
        begin = _read(context, world + 0x768, 8)
        raw_count = _count(end, begin)
        held_r13 = _LITERAL
        if not raw_count & _U32:
            return handoff(outer, held_r13, raw_count, None, None, None, None, 0x14162AB9E)
        xmm8 = _read(context, 0x143219E04, 4)
    else:
        outer, xmm8 = phase.outer_index, phase.xmm8_word

    if _read(context, 0x14435505D, 1) >= 1:
        _write(context, frame + 0x220, 4, 7)
        _write(context, frame + 0x218, 4, outer)
        _write(context, frame + 0x2B0, 8, frame + 0x218)
        _write(context, frame + 0x20, 8, frame + 0x2B0)
        logger = _read(context, 0x144355068, 8)
        _invoke(
            logger_home_calls,
            0x14101ADB0,
            (
                logger,
                0x25,
                0x1432EA200,
                1,
                frame + 0x20,
            ),
        )
    increment = _read(context, world + 0x7C, 4)
    accumulator = world + outer * 4 + 0x18C
    previous = _read(context, accumulator, 4)
    _write(context, accumulator, 4, previous + increment)
    begin = _read(context, world + 0x768, 8)
    end = _read(context, world + 0x770, 8)
    raw_count = _count(end, begin)
    held_r13 = _read(context, begin + outer * 16, 8) if outer < raw_count else 0
    _write(context, frame + 0x2B0, 8, held_r13)
    if not _read(context, held_r13 + 0x648, 4):
        return handoff(outer, held_r13, raw_count, begin, xmm8, None, None, 0x141629E00)
    receiver = _read(context, begin + outer * 16, 8)
    _invoke(calls, 0x141711B80, (receiver,))
    inner = 1
    begin = _read(context, world + 0x768, 8)
    end = _read(context, world + 0x770, 8)
    raw_count = _count(end, begin)
    if raw_count & _U32 <= inner:
        return handoff(outer, held_r13, raw_count, begin, xmm8, inner, None, 0x141629E00)
    while True:
        marker = (frame + 0x278 + inner * 4) & _U64
        if not _read(context, marker, 4):
            permitted = outer == inner
            if not permitted:
                receiver = _read(context, begin + outer * 16, 8)
                _write(context, frame + 0x94, 4, inner)
                permitted = bool(
                    _call(
                        relationship_calls,
                        _RELATIONSHIP,
                        (
                            receiver,
                            (frame + 0x94) & _U64,
                            1,
                            0xFF,
                        ),
                        width=1,
                    )
                )
                if permitted:
                    current_begin = _read(context, world + 0x768, 8)
                    receiver = _read(context, current_begin + inner * 16, 8)
                    _write(context, frame + 0x90, 4, outer)
                    permitted = bool(
                        _call(
                            relationship_calls,
                            _RELATIONSHIP,
                            (
                                receiver,
                                (frame + 0x90) & _U64,
                                1,
                                0xFF,
                            ),
                            width=1,
                        )
                    )
            if permitted:
                doubled_inner = (inner + inner) & _U64
                current_begin = _read(context, world + 0x768, 8)
                receiver = _read(context, current_begin + doubled_inner * 8, 8)
                vtable = _read(context, receiver, 8)
                _write(context, frame + 0xA0, 4, outer)
                target = _read(context, vtable + 0x328, 8)
                _invoke(virtual_calls, target, (receiver, frame + 0xA0))
                _write(context, marker, 4, 1)
        inner = (inner + 1) & _U32
        begin = _read(context, world + 0x768, 8)
        end = _read(context, world + 0x770, 8)
        raw_count = _count(end, begin)
        if inner >= raw_count & _U32:
            break
    return handoff(outer, held_r13, raw_count, begin, xmm8, inner, marker, 0x141629E00)
