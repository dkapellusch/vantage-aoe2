"""Source-shaped World recording/playback caller phase.

Build54800 [141628f0c,14162951f):1555B/323 instructions. This owns the
caller's complete branch/effect order, not its actual stream/UI/manager
children or the World tick. The same explicitly seeded logical frame and
held prelude entry time are required. No normal return claims a complete step.
"""

from __future__ import annotations

from dataclasses import dataclass

from .replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildStorage,
    _call,
    _read,
    _unsigned,
    _write,
)
from .replay_unit_ai_base import _validate
from .replay_world_update_prelude import ReplayWorldUpdatePrelude

_U32, _U64 = (1 << 32) - 1, (1 << 64) - 1
_SCREEN, _EMPTY = 0x144415600, 0x14428BB30


@dataclass(frozen=True, slots=True)
class ReplayWorldUpdateReplayPhase:
    """Real early status or explicit2951f handoff, with held continuation state.

    status is the latest writer/incoming DWORD before diagnostic selection;
    default_time is the held raw XMM7 word sampled even without playback.
    Logical backing and all earlier effects remain current after refusal.
    """

    world: int
    logical_frame: int
    entry_time: int
    cycle: int
    status: int
    default_time: int
    next_address: int | None
    returned_status: int | None


def _descriptor(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    world: int,
) -> int:
    return _call(calls, 0x140E15770, (_read(context, world + 0x70, 8),), width=8)


def _time(context: ReplayTaskRebuildStorage, calls: ReplayTaskRebuildCalls, world: int) -> int:
    return _call(calls, 0x140E68F70, (_read(context, world + 0x228, 8),), width=4)


def _cleanup(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    frame: int,
    inline: int,
    owner: int,
    *,
    clear: bool,
) -> None:
    pointer = _read(context, frame + owner, 8)
    if pointer:
        target = _read(context, _read(context, pointer, 8) + 0x20, 8)
        _call(calls, target, (pointer, int(pointer != ((frame + inline) & _U64))))
        if clear:
            _write(context, frame + owner, 8, 0)


def _empty(context: ReplayTaskRebuildStorage, frame: int) -> None:
    _write(context, frame + 0x218, 8, _EMPTY)
    _write(context, frame + 0x220, 8, 0)
    _write(context, frame + 0x228, 8, 0)


def _writer_failure(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    world: int,
    frame: int,
    *,
    op3: bool,
) -> None:
    settings = _call(calls, 0x141603AC0, (world,), width=8)
    if _call(calls, 0x1413D3910, (settings,), width=8) & 0xFF:
        _write(context, 0x1442C40F4, 4, 1)
    else:
        screen = _read(context, _SCREEN, 8)
        _write(context, frame + 0x64, 1, 0)
        inline, owner, vptr = (0x100, 0x138, 0x1432EA8E0) if op3 else (0xC0, 0xF8, 0x1432EA8A8)
        _write(context, frame + inline, 8, vptr)
        _write(context, frame + owner, 8, frame + inline)
        localized = _call(calls, 0x140803E30, (0x2333,), width=8)
        _write(context, frame + 0x80, 4, 15)
        _write(context, frame + 0x78, 8, localized)
        _empty(context, frame)
        _write(context, frame + 0x2B0, 8, frame + 0x78)
        _call(calls, 0x140A1BA10, (frame + 0x218, 0x143679A90, 1, frame + 0x2B0))
        flags = _read(context, frame + 0x60, 8)
        _call(calls, 0x141581360, (screen, frame + 0x218, frame + inline, flags))
        _call(calls, 0x140A1B220, (frame + 0x218,))
        _cleanup(context, calls, frame, inline, owner, clear=True)
    _call(calls, 0x140DF2240, (_descriptor(context, calls, world),))


def _playback_failure(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    world: int,
    frame: int,
    code: int,
    *,
    reader: bool,
) -> None:
    if not reader:
        _write(context, _read(context, _SCREEN, 8) + 0x1252, 1, 1)
    _write(context, frame + 0x218, 16, 0)
    _write(context, frame + 0x228, 8, 0)
    timestamp = _time(context, calls, world)
    _write(context, frame + 0x258, 4, 7)
    _write(context, frame + 0x250, 4, timestamp)
    localized = _call(calls, 0x140803E30, (code,), width=8)
    _write(context, frame + 0x80, 4, 15)
    _write(context, frame + 0x78, 8, localized)
    _empty(context, frame)
    _write(context, frame + 0x238, 8, frame + 0x78)
    _write(context, frame + 0x240, 8, frame + 0x250)
    _call(calls, 0x140A1BA10, (frame + 0x218, 0x1432EA160, 2, frame + 0x238))
    _write(context, frame + 0x2B0, 4, 1)
    _write(context, frame + 0x2B4, 1, 1)
    inline, owner, vptr = (0x180, 0x1B8, 0x1432EA950) if reader else (0x140, 0x178, 0x1432EA918)
    _write(context, frame + inline, 8, vptr)
    _write(context, frame + owner, 8, frame + inline)
    flags = _read(context, frame + 0x2B0, 8)
    screen = _read(context, _SCREEN, 8)
    _call(calls, 0x141581360, (screen, frame + 0x218, frame + inline, flags))
    _cleanup(context, calls, frame, inline, owner, clear=False)
    if reader:
        _write(context, _read(context, _SCREEN, 8) + 0x1252, 1, 1)
    _call(calls, 0x140A1B220, (frame + 0x218,))


def run_replay_world_update_replay_phase(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    prelude: ReplayWorldUpdatePrelude,
) -> ReplayWorldUpdateReplayPhase:
    """Execute the complete caller slice with actual reached helper services.

    The lower dispatcher must supply the real descriptor, writer/reader,
    settings, UI/string, manager and position children when reached. The
    existing clock, observer and localized-string binders can be composed.
    Missing reached services refuse after earlier effects. No successful
    stream, settings flag, callback cleanup or diagnostic is supplied here.

    FP arguments/returns use raw binary32 words in their effective positional
    ABI; predicates test raw AL. The manager's reached(-1,-1) branch ignores
    stack5, but its caller home20 still receives held XMM7 and preserves its
    upper DWORD. Its five effective arguments explicitly include stack5.
    Current backing must cover reached homes through2b7 with explicit padding,
    using the same frame as the prelude; no blanket initialization occurs.
    Physical registers/stack/cookie, escaped local pointers, native fault/EH,
    concurrency and later World phases are outside this component.
    """
    if not isinstance(prelude, ReplayWorldUpdatePrelude):
        raise ValueError("actual World prelude handoff required")
    if prelude.returned_status is not None or prelude.next_address != 0x141628F0C:
        raise ValueError("World prelude must hand off at141628f0c")
    world, frame = prelude.world, prelude.logical_frame
    _validate(context, calls, world, frame)
    for value in (prelude.entry_time, prelude.cycle, prelude.incoming_status):
        _unsigned(value, 4, "World held DWORD")
    status = prelude.incoming_status

    if _read(context, _descriptor(context, calls, world), 1):
        descriptor = _descriptor(context, calls, world)
        first_time = _time(context, calls, world)
        second_time = _time(context, calls, world)
        delta = (second_time - _read(context, world + 0x78, 4)) & _U32
        status = _call(calls, 0x140DEF190, (descriptor, delta, first_time), width=4)
        if status != 1:
            _writer_failure(context, calls, world, frame, op3=False)
        if not _call(calls, 0x140E053D0, (_read(context, 0x1442C3F98, 8),), width=8) & 0xFF:
            player = _call(calls, 0x141603D70, (world,), width=8)
            descriptor = _descriptor(context, calls, world)
            _write(context, frame + 0x210, 4, _read(context, world + 0x6B0, 4))
            y = _read(context, player + 0x22C, 4)
            x = _read(context, player + 0x228, 4)
            status = _call(calls, 0x140DEF370, (descriptor, x, y, frame + 0x210), width=4)
            if status != 1:
                _writer_failure(context, calls, world, frame, op3=True)

    playback = _read(context, _descriptor(context, calls, world) + 1, 1)
    default = _read(context, 0x1431B7520, 4)

    def result(returned: int | None) -> ReplayWorldUpdateReplayPhase:
        return ReplayWorldUpdateReplayPhase(
            world,
            frame,
            prelude.entry_time,
            prelude.cycle,
            status,
            default,
            0x14162951F if returned is None else None,
            returned,
        )

    if playback:
        _write(context, world + 0x78, 4, prelude.entry_time)
        clock = _read(context, world + 0x228, 8)
        delta = _read(context, _descriptor(context, calls, world) + 0x94, 4)
        _call(calls, 0x140E68FA0, (clock, (prelude.entry_time + delta) & _U32))
        if not status:
            _call(calls, 0x140DF2670, (_descriptor(context, calls, world),))
            return result(4)
        if status != 1:
            code = 0x2336 if status == 2 else 0x2335 if status == 3 else 0x2334
            _playback_failure(context, calls, world, frame, code, reader=False)
            return result(4)
        _write(context, frame + 0x20, 4, default)
        _call(calls, 0x140F55400, (_read(context, world + 0x130, 8), _U32, _U32, default, default))
        descriptor = _descriptor(context, calls, world)
        read_status = _call(
            calls,
            0x140DEC960,
            (
                descriptor,
                frame + 0x200,
                frame + 0x210,
                frame + 0x270,
            ),
            width=4,
        )
        if read_status == 2:
            _playback_failure(context, calls, world, frame, 0x2336, reader=True)
            return result(4)
        if not read_status:
            _call(calls, 0x140DF2670, (_descriptor(context, calls, world),))
            return result(4)
        if read_status == 1 and _read(context, _descriptor(context, calls, world) + 0x6C, 4):
            index = _read(context, _descriptor(context, calls, world) + 0x78, 4)
            if _read(context, world + 0x6B0, 4) == index:
                player = _call(calls, 0x141603D70, (world,), width=8)
                y = _read(context, frame + 0x210, 4)
                x = _read(context, frame + 0x200, 4)
                _call(calls, 0x14174A970, (player, x, y, 1))
    now = _time(context, calls, world)
    _write(context, world + 0x7C, 4, now - _read(context, world + 0x78, 4))
    return result(None)
