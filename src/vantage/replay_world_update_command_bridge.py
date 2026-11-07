"""World caller bridge [14162951f,141629793):628B/138 source instructions.

The existing World frame and held replay-phase state remain live. Actual
notification/logger/manager/queue/formation/batch effects are mandatory. This
returns an explicit continuation, never a completed World tick or success.
"""

from __future__ import annotations

from dataclasses import dataclass

from .replay_binary32 import (
    divide_binary32,
    multiply_binary32,
    signed32_binary32,
    unsigned64_binary32,
)
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
from .replay_world_update_replay_phase import ReplayWorldUpdateReplayPhase

_U32, _U64 = (1 << 32) - 1, (1 << 64) - 1


@dataclass(frozen=True, slots=True)
class ReplayWorldUpdateCommandBridge:
    """Explicit29793 handoff carrying the same frame and held phase state."""

    world: int
    logical_frame: int
    entry_time: int
    cycle: int
    status: int
    default_time: int
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
        raise ValueError(f"helper{target:x} must supply raw RAX at consumer")
    _unsigned(value, 8, f"helper{target:x} raw RAX")
    return value


def run_replay_world_update_command_bridge(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    phase: ReplayWorldUpdateReplayPhase,
    *,
    notification_home_calls: ReplayTaskRebuildCalls,
    logger_home_calls: ReplayTaskRebuildCalls,
    mxcsr: int,
) -> ReplayWorldUpdateCommandBridge:
    """Complete caller bridge using actual services and the same live frame.

    Notification/logger channels receive four effective prepared arguments
    (only low DL is supplied) and the fifth annotation is caller HOME20's
    ADDRESS. Its late DWORD/early QWORD consumption belongs to the real child.
    No eager home value, formatted message, camera default or child success is
    supplied. Current pointers/counts/constants and finite valid backing are
    mandatory. Native physical GP/stack, faults/EH/concurrency, upper XMM lanes
    and FP status/traps are outside the exact masked MXCSR1f80 profile.
    """
    if not isinstance(phase, ReplayWorldUpdateReplayPhase):
        raise ValueError("actual World replay-phase handoff required")
    if phase.returned_status is not None or phase.next_address != 0x14162951F:
        raise ValueError("World replay phase must hand off at14162951f")
    world, frame = phase.world, phase.logical_frame
    entry, cycle, status, default = phase.entry_time, phase.cycle, phase.status, phase.default_time
    _validate(context, calls, world, frame)
    for value in (entry, cycle, status, default):
        _unsigned(value, 4, "held World phase DWORD")
    if not isinstance(notification_home_calls, ReplayTaskRebuildCalls) or not isinstance(
        logger_home_calls, ReplayTaskRebuildCalls
    ):
        raise ValueError("actual notification/logger HOME channels required")
    if type(mxcsr) is not int or mxcsr != 0x1F80:
        raise ValueError("exact masked MXCSR1f80 profile required")

    notification = _rax(calls, 0x141021E00, ())
    if _rax(calls, 0x1410221C0, (notification,)) & 255:
        notification = _rax(calls, 0x141021E00, ())
        _write(context, frame + 0x20, 4, 0xF8C)
        _invoke(
            notification_home_calls,
            0x1410242D0,
            (
                notification,
                1,
                0x1432EA178,
                0x1432E98F0,
                frame + 0x20,
            ),
        )
    _invoke(calls, 0x140FDDBF0, (_read(context, world + 0x7D0, 4),))
    if _read(context, 0x14435505D, 1) >= 1:
        _write(context, frame + 0x80, 4, 2)
        _write(context, frame + 0x78, 4, _read(context, world + 0x188, 4))
        _write(context, frame + 0x2B0, 8, frame + 0x78)
        _write(context, frame + 0x20, 8, frame + 0x2B0)
        logger = _read(context, 0x144355068, 8)
        _invoke(
            logger_home_calls,
            0x14101ADB0,
            (
                logger,
                0x25,
                0x1432EA190,
                1,
                frame + 0x20,
            ),
        )
    _invoke(calls, 0x14148C300, (_read(context, world + 0x138, 8),))
    _invoke(calls, 0x140F55750, (_read(context, world + 0x130, 8),))
    _invoke(calls, 0x140F54480, (_read(context, world + 0x130, 8),))

    index = _read(context, world + 0x6B0, 4)
    if index == _read(context, 0x143DA5054, 4):
        first_player = 0
    else:
        begin = _read(context, world + 0x768, 8)
        end = _read(context, world + 0x770, 8)
        count = (_signed((end - begin) & _U64, 8) >> 4) & _U64
        first_player = _read(context, begin + index * 16, 8) if index < count else 0
    second_begin = _read(context, world + 0x768, 8)
    _write(context, world + 0x158, 4, _read(context, first_player + 0x228, 4))
    if index == _read(context, 0x143DA5054, 4):
        second_player = 0
    else:
        end = _read(context, world + 0x770, 8)
        count = (_signed((end - second_begin) & _U64, 8) >> 4) & _U64
        second_player = _read(context, second_begin + index * 16, 8) if index < count else 0
    _write(context, world + 0x15C, 4, _read(context, second_player + 0x22C, 4))

    game = _read(context, 0x144353698, 8)
    divisor = 2000
    if game and _rax(calls, 0x140D6ADB0, (game,)):
        game = _read(context, 0x144353698, 8)
        pair_source = _rax(calls, 0x140D6ADB0, (game,))
        second = _read(context, pair_source + 0x5D0, 4)
        first = _read(context, pair_source + 0x5CC, 4)
        _invoke(calls, 0x140A80160, (frame + 0x2B0, first, second))
        divisor = _rax(calls, 0x140A801F0, (frame + 0x2B0,)) & _U32
    data = _read(context, world + 0x98, 8)
    numerator = signed32_binary32(_signed(_read(context, data + 0x5B5C, 4), 4))
    numerator = multiply_binary32(numerator, _read(context, 0x1431FE88C, 4))
    denominator = signed32_binary32(_signed(divisor, 4))
    _write(context, world + 0x160, 4, divide_binary32(numerator, denominator))
    elapsed = unsigned64_binary32(_read(context, world + 0x7C, 4))
    _write(context, world + 0x164, 4, divide_binary32(elapsed, _read(context, 0x1436A02F8, 4)))
    _invoke(calls, 0x140F51FC0, (_read(context, world + 0x130, 8),))
    _write(context, 0x1444185CC, 4, _read(context, 0x1444185CC, 4) + 1)
    _invoke(calls, 0x14162BAB0, (world,))

    _write(context, frame + 0x98, 4, 0)
    _write(context, frame + 0x9C, 4, 0)
    cursor = 0
    while True:
        left = _read(context, frame + 0x98 + cursor, 1)
        cursor = (cursor + 1) & _U64
        right = _read(context, frame + 0x9C + cursor - 1, 1)
        if left != right:
            comparison = _U32 if left < right else 1
            break
        if cursor == 4:
            comparison = 0
            break
    if not comparison:
        _write(context, frame + 0x278, 16, 0)
        _write(context, frame + 0x288, 16, 0)
        _write(context, frame + 0x298, 4, 0)
    else:
        _write(context, frame + 0x278, 16, 0)
        _write(context, frame + 0x288, 16, 0)
        _write(context, frame + 0x298, 4, 0)
    _invoke(calls, 0x140E08860, (_read(context, 0x1442DA8A0, 8),))
    return ReplayWorldUpdateCommandBridge(
        world,
        frame,
        entry,
        cycle,
        status,
        default,
        0x141629793,
        None,
    )
