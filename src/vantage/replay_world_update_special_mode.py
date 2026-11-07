"""World selector12 caller interval [141629793,141629b2a), 919B/219 rows.

The accepted command bridge's frame and held metadata remain live. Actual
options, clock, tile, logger and Game children are required when reached.
This returns a continuation, never a completed World tick or status.
"""

from __future__ import annotations

from dataclasses import dataclass

from .replay_binary32 import divide_binary32, multiply_binary32, signed32_binary32
from .replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
    _cvtt,
    _read,
    _signed,
    _unsigned,
    _write,
)
from .replay_unit_ai_base import _validate
from .replay_world_update_command_bridge import ReplayWorldUpdateCommandBridge

_U32, _U64 = (1 << 32) - 1, (1 << 64) - 1
_GAME, _OPTIONS, _RELEASE, _CLOCK = 0x144353698, 0x140D6A530, 0x140990140, 0x140E68F70


@dataclass(frozen=True, slots=True)
class ReplayWorldUpdateSpecialMode:
    """Same-frame29b2a handoff; control flags differ from historical status."""

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


def _master(context: ReplayTaskRebuildStorage, unit: int, scratch: int) -> int:
    _write(context, scratch, 8, _read(context, unit + 0x10, 8))
    _write(context, scratch, 8, _read(context, scratch, 8) - 0x6A586EB28AC201FC)
    _write(context, scratch, 8, _read(context, scratch, 8) - 0x0CF19788B2554E70)
    return _read(context, scratch, 8)


def _scan(context: ReplayTaskRebuildStorage, world: int, frame: int) -> None:
    if _read(context, world + 0x234, 4):
        return
    player = _read(context, _read(context, world + 0x768, 8), 8)
    if not player:
        return
    row = _read(context, player + 0x30, 8)
    array = _read(context, row + 8, 8)
    if _signed(_read(context, row + 0x10, 4), 4) <= 0:
        return
    index, cursor = 0, array
    scratch = (frame + 0x68) & _U64
    while True:
        unit = _read(context, cursor, 8)
        if unit and _read(context, unit + 0xF, 1) == 0x46:
            master = _master(context, unit, scratch)
            _write(context, scratch, 8, _read(context, master + 0x38, 8))
            _write(context, scratch, 8, _read(context, scratch, 8) - 0x50A06BCECEBEF905)
            _write(context, scratch, 8, _read(context, scratch, 8) + 0x5B32AA7995D95916)
            if _read(context, scratch, 8) & 0xFFFF != 1:
                selected = _read(context, array + _signed(index, 4) * 8, 8)
                master = _master(context, selected, scratch)
                _write(context, scratch, 8, _read(context, master + 0x18, 8))
                _write(context, scratch, 8, _read(context, scratch, 8) ^ 0x349E37847AD69F19)
                _write(context, scratch, 8, _read(context, scratch, 8) - 0x47E37DFF0616CE4F)
                identifier = _signed(_read(context, scratch, 8) & 0xFFFF, 2)
                _write(context, world + 0x234, 4, identifier)
                return
        index = (index + 1) & _U32
        cursor = (cursor + 8) & _U64
        current_player = _read(context, _read(context, world + 0x768, 8), 8)
        current_row = _read(context, current_player + 0x30, 8)
        if _signed(index, 4) >= _signed(_read(context, current_row + 0x10, 4), 4):
            return


def _divide(numerator: int, divisor: int, site: int) -> int:
    if not divisor:
        raise UnresolvedReplayTaskRebuild(f"unsigned DIV zero at{site:x} after source prefix")
    # Source EDX=0: a nonzero DWORD divisor cannot overflow the quotient.
    return numerator // divisor


def _half(raw: int) -> int:
    sign = _U32 if raw & 0x80000000 else 0
    return (_signed((raw - sign) & _U32, 4) >> 1) & _U32


def run_replay_world_update_special_mode(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    bridge: ReplayWorldUpdateCommandBridge,
    *,
    logger_home_calls: ReplayTaskRebuildCalls,
    mxcsr: int,
) -> ReplayWorldUpdateSpecialMode:
    """Complete source caller phase, with exact1f80 arithmetic and live homes.

    Actual raw64 helper returns are validated before explicit lowEAX uses.
    Ignored results remain opaque. Logger receives only defined lowDL27 and
    HOME20's address, never an eager home value. Finite backed loops/callbacks
    are required; no loop cap, default service, frame seed or success is added.
    Native physical registers/faults/EH/concurrency, FP status and upper lanes
    are excluded. Zero integer divisors refuse only at their source consumers.
    """
    if not isinstance(bridge, ReplayWorldUpdateCommandBridge):
        raise ValueError("actual command-bridge handoff required")
    if bridge.returned_status is not None or bridge.next_address != 0x141629793:
        raise ValueError("command bridge must hand off at141629793")
    world, frame = bridge.world, bridge.logical_frame
    entry, cycle = bridge.entry_time, bridge.cycle
    status, default = bridge.status, bridge.default_time
    _validate(context, calls, world, frame)
    for value in (entry, cycle, status, default):
        _unsigned(value, 4, "held World bridge DWORD")
    if not isinstance(logger_home_calls, ReplayTaskRebuildCalls):
        raise ValueError("actual logger HOME channel required")
    if type(mxcsr) is not int or mxcsr != 0x1F80:
        raise ValueError("exact masked MXCSR1f80 profile required")

    output = (frame + 0x2B0) & _U64
    returned = _rax(calls, _OPTIONS, (_read(context, _GAME, 8), output))
    selector = _read(context, _read(context, returned, 8) + 0x34, 4)
    token = _read(context, output, 8)
    if token:
        _invoke(calls, _RELEASE, (token,))
    flags = 0
    if selector == 12:
        _scan(context, world, frame)
        time = _rax(calls, _CLOCK, (_read(context, world + 0x228, 8),)) & _U32
        first = (0x10624DD3 * time >> 32) >> 6
        second = (0x88888889 * first >> 32) >> 5
        numerator = second << 3 & _U32
        data = _read(context, world + 0x98, 8)
        quotient = _divide(numerator, _read(context, data + 0x30, 4), 0x14162994A)

        returned = _rax(calls, _OPTIONS, (_read(context, _GAME, 8), output))
        scalar = _rax(calls, 0x1413D2980, (_read(context, returned, 8),)) & _U32
        token = _read(context, output, 8)
        if token:
            _invoke(calls, _RELEASE, (token,))
        scaled = (1000 - quotient) & _U32
        scaled = scaled * scalar & _U32
        scaled = scaled * 120 & _U32
        fraction = signed32_binary32(_signed(scaled, 4))
        fraction = multiply_binary32(fraction, _read(context, 0x1432EA9DC, 4))
        data = _read(context, world + 0x98, 8)
        width_float = signed32_binary32(_signed(_read(context, data + 0x30, 4), 4))
        denominator = _cvtt(divide_binary32(fraction, width_float))

        time = _rax(calls, _CLOCK, (_read(context, world + 0x228, 8),)) & _U32
        data = _read(context, world + 0x98, 8)
        width = _read(context, data + 0x30, 4)
        quotient = _divide(time, denominator, 0x1416299CB)
        width_float = signed32_binary32(_signed(width, 4))
        deduction = _cvtt(multiply_binary32(width_float, _read(context, 0x1432EA9D8, 4)))
        delta = (quotient - deduction) & _U32
        _write(context, frame + 0x94, 4, delta)
        lower = (delta - 8) & _U32
        if _signed(lower, 4) < 0:
            lower = 0
        _write(context, frame + 0x210, 4, lower)
        upper_x = (width - lower) & _U32
        _write(context, frame + 0x200, 4, upper_x)
        height = _read(context, data + 0x34, 4)
        upper_y = (height - lower) & _U32
        center_x = _half(width)
        _write(context, frame + 0x90, 4, center_x)
        center_y = _half(height)
        product = ((center_y - delta) & _U32) * ((center_x - delta) & _U32) & _U32
        outer = lower
        if _signed(outer, 4) < _signed(upper_x, 4):
            while True:
                inner = lower
                if _signed(inner, 4) < _signed(upper_y, 4):
                    row_delta = (outer - center_x) & _U32
                    row_square = row_delta * row_delta & _U32
                    while True:
                        column_delta = (inner - center_y) & _U32
                        total = (column_delta * column_delta + row_square) & _U32
                        if _signed(total, 4) >= _signed(product, 4):
                            _invoke(calls, 0x1415F9740, (0, world, outer, inner))
                        inner = (inner + 1) & _U32
                        if _signed(inner, 4) >= _signed(upper_y, 4):
                            break
                    lower = _read(context, frame + 0x210, 4)
                    upper_x = _read(context, frame + 0x200, 4)
                    center_x = _read(context, frame + 0x90, 4)
                outer = (outer + 1) & _U32
                if _signed(outer, 4) >= _signed(upper_x, 4):
                    break
            delta = _read(context, frame + 0x94, 4)
        if delta != _read(context, world + 0x148, 4):
            if _read(context, 0x14435505F, 1) >= 1:
                _write(context, frame + 0x258, 4, 2)
                _write(context, frame + 0x250, 4, product)
                _write(context, frame + 0x80, 4, 2)
                _write(context, frame + 0x78, 4, delta)
                _write(context, frame + 0x238, 8, frame + 0x78)
                _write(context, frame + 0x240, 8, frame + 0x250)
                _write(context, frame + 0x20, 8, frame + 0x238)
                logger = _read(context, 0x144355068, 8)
                _invoke(
                    logger_home_calls,
                    0x14101ADB0,
                    (
                        logger,
                        0x27,
                        0x1432EA1B0,
                        2,
                        (frame + 0x20) & _U64,
                    ),
                )
            _invoke(calls, 0x140D66C40, (_read(context, _GAME, 8),))
            _invoke(calls, 0x140D63400, (_read(context, _GAME, 8),))
        _write(context, world + 0x148, 4, delta)
        flags = _read(context, frame + 0x208, 4)
    return ReplayWorldUpdateSpecialMode(
        world,
        frame,
        entry,
        cycle,
        status,
        default,
        flags,
        0x141629B2A,
        None,
    )
