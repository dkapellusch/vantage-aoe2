"""Ten complete World queue/poll/command-reader source bodies.

Source: world-command-reader-source-v1. Reached I/O, Result, allocation,
virtual, logger and lifecycle effects remain actual mandatory capabilities.
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
    _unsigned,
    _write,
)
from .replay_unit_ai_base import _validate
from .replay_unit_ai_construction import _local
from .replay_unit_ai_map import ReplayUnitAIMapAtomics, _release

_U32, _U64 = (1 << 32) - 1, (1 << 64) - 1
_READER, _QUEUE, _POLL = 0x140DEC2C0, 0x140F51FC0, 0x140E15C00
_RELEASE, _DONE = 0x140E0E0D0, 0x140E085A0
_FIRST, _SELECT, _CLOCK, _GAME_TIME, _WORLD_TIME = (
    0x140E62B90,
    0x140E62A10,
    0x140E68F80,
    0x140D6AD50,
    0x1416041F0,
)
_READ, _SEEK, _TELL, _HEADER, _CLEAR = (
    0x140916DB0,
    0x1409179E0,
    0x140915F00,
    0x140DF03C0,
    0x1402BD7F0,
)


@dataclass(frozen=True, slots=True)
class ReplayCommandReaderProfile:
    """Explicit coherent58/50/90h seeds; physical cookies/saves excluded.

    Reader Result20, operation50 and tail54; poller pointer40/count48 and
    dispatcher20/vector28; selector partial descriptors30..68, pointers70..88
    and outgoing HOME20 all retain live backing through actual children.
    Finite valid vectors/terminating callbacks are premises, not loop caps.
    """

    reader: bytes
    poller: bytes
    selector: bytes

    def __post_init__(self) -> None:
        if any(
            type(value) is not bytes or len(value) != size
            for value, size in (
                (self.reader, 0x58),
                (self.poller, 0x50),
                (self.selector, 0x90),
            )
        ):
            raise ValueError("explicit58/50/90-hex-byte command local seeds required")


def _invoke(
    calls: ReplayTaskRebuildCalls,
    target: int,
    args: tuple[int, ...],
) -> int | None:
    if calls.call is None:
        raise UnresolvedReplayTaskRebuild(f"reached{target:x} is unavailable")
    return calls.call(target, tuple(value & _U64 for value in args), None)


def _raw(value: int | None, label: str) -> int:
    if value is None:
        raise ValueError(f"{label} requires rawRAX at source consumption")
    _unsigned(value, 8, label)
    return value


def _cleanup(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    atomics: ReplayUnitAIMapAtomics,
    result: int,
    control: int,
) -> None:
    if control:
        _release(context, control, calls, atomics)
    _call(calls, _CLEAR, (result,))


def _finish_input(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    atomics: ReplayUnitAIMapAtomics,
    result: int,
) -> int:
    control = _read(context, result + 0x20, 8)
    status = _read(context, result + 0x18, 8)
    _write(context, result + 0x28, 1, 1)
    _cleanup(context, calls, atomics, result, control)
    return status


def _command(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    imports: ReplayTaskRebuildCalls,
    descriptor: int,
    output: int,
    count_output: int,
    *,
    atomics: ReplayUnitAIMapAtomics,
    bind_local: LocalBinding,
    seed: bytes,
) -> int:
    if not _read(context, descriptor + 1, 1):
        return 6
    with _local(memoryview(bytearray(seed)), bind_local) as frame:
        result, marker, tail = frame + 0x20, frame + 0x50, frame + 0x54
        stream = _read(context, descriptor + 0x48, 8)
        _write(context, marker, 4, _U32)
        raw_position = _invoke(calls, _TELL, (stream,))
        stream = _read(context, descriptor + 0x48, 8)
        position = _raw(raw_position, "command tell")
        _call(calls, _READ, (stream, result, marker, 4))
        # Initial site differs from all later Input sites: processed precedes
        # the held bad flag, whose marker comparison is short-circuited.
        _write(context, result + 0x28, 1, 1)
        bad = bool(_read(context, result + 0x18, 8)) or _read(context, marker, 4) == 6
        control = _read(context, result + 0x20, 8)
        _cleanup(context, calls, atomics, result, control)
        if bad:
            return _U32
        if _read(context, marker, 4) != 1:
            returned = _call(
                calls,
                _SEEK,
                (
                    _read(context, descriptor + 0x48, 8),
                    result,
                    position,
                ),
                width=8,
            )
            status = _read(context, returned + 0x18, 8)
            _write(context, returned + 0x28, 1, 1)
            control = _read(context, result + 0x20, 8)
            _cleanup(context, calls, atomics, result, control)
            if status:
                return _U32
            _write(context, output, 8, 0)
            return 4
        header = _call(calls, _HEADER, (descriptor,), width=8) & _U32
        if header != 1:
            return header
        _call(
            calls,
            _READ,
            (
                _read(context, descriptor + 0x48, 8),
                result,
                count_output,
                4,
            ),
        )
        if _finish_input(context, calls, atomics, result):
            return _U32
        allocation_size = _read(context, count_output, 4)
        malloc = _read(context, 0x143199DB0, 8)
        allocated = _raw(_invoke(imports, malloc, (allocation_size,)), "command malloc")
        _write(context, output, 8, allocated)
        count = _read(context, count_output, 4)
        stream = _read(context, descriptor + 0x48, 8)
        _call(calls, _READ, (stream, result, allocated, count))
        failed = bool(_finish_input(context, calls, atomics, result))
        if not failed:
            _call(
                calls,
                _READ,
                (
                    _read(context, descriptor + 0x48, 8),
                    result,
                    tail,
                    4,
                ),
            )
            failed = bool(_finish_input(context, calls, atomics, result))
        if not failed:
            return 1
        pointer = _read(context, output, 8)
        free = _read(context, 0x143199DD0, 8)
        _invoke(imports, free, (pointer,))
        _write(context, output, 8, 0)
        return _U32


def _first(
    context: ReplayTaskRebuildStorage,
    container: int,
    count_output: int,
) -> int:
    row = _read(context, container, 8)
    end = _read(context, container + 8, 8)
    while row != end:
        count = _read(context, row + 0x18, 4)
        if count and _read(context, row + 0x1C, 1):
            command = _read(context, row, 8)
            _write(context, count_output, 4, count)
            _write(context, row + 0x1C, 1, 0)
            return command
        row = row + 32 & _U64
    return 0


def _select(
    context: ReplayTaskRebuildStorage,
    logger: ReplayTaskRebuildCalls,
    container: int,
    time: int,
    count_output: int,
    *,
    frame: int,
) -> int:
    begin = _read(context, container, 8)
    extent = (_read(context, container + 8, 8) - begin) & _U64
    rows = _signed(extent, 8) >> 5 & _U64
    selected, index, best, tie = _U32, 0, _U64, _U32
    cursor = begin + 0x1C & _U64
    time &= _U32
    if rows:
        while True:
            if (
                _read(context, cursor - 4, 4)
                and _read(context, cursor, 1)
                and _read(context, cursor - 12, 4) == time
            ):
                key = _read(context, cursor - 20, 4)
                if key < best or (key == best and _read(context, cursor - 8, 4) < tie):
                    tie = _read(context, cursor - 8, 4)
                    best, selected = key, index
            index = index + 1 & _U32
            cursor = cursor + 32 & _U64
            if (_signed(index, 4) & _U64) >= rows:
                break
    if selected == _U32:
        return 0
    row = ((_signed(selected, 4) << 5) + _read(context, container, 8)) & _U64
    count = _read(context, row + 0x18, 4)
    held_tie = _read(context, row + 0x14, 4)
    command = _read(context, row, 8)
    _write(context, count_output, 4, count)
    held_key = _read(context, row + 8, 8)
    _write(context, row + 0x1C, 1, 0)
    if _read(context, 0x144355062, 1) >= 1:
        _write(context, frame + 0x60, 4, held_key)
        opcode = _read(context, command, 1)
        _write(context, frame + 0x30, 1, opcode)
        _write(context, frame + 0x40, 4, held_tie)
        receiver = _read(context, 0x144355068, 8)
        for offset, address in ((0x70, 0x30), (0x78, 0x40), (0x80, 0x50), (0x88, 0x60)):
            _write(context, frame + offset, 8, frame + address)
        _write(context, frame + 0x20, 8, frame + 0x70)
        for offset, value in ((0x68, 2), (0x58, 7), (0x50, time), (0x48, 7), (0x38, 5)):
            _write(context, frame + offset, 4, value)
        # Source MOV DL,2a preserves upper RDX from the selected row address.
        _invoke(
            logger,
            0x14101ADB0,
            (
                receiver,
                row & ~255 | 0x2A,
                0x14326A5E0,
                4,
                frame + 0x20,
            ),
        )
    return command


def _poll(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    receiver: int,
    *,
    frame: int,
) -> int:
    pointer, count = frame + 0x40, frame + 0x48
    _write(context, pointer, 8, 0)
    _write(context, count, 4, 1)
    if _read(context, receiver + 0x318, 4) == 10:
        status = (
            _call(
                calls,
                _READER,
                (
                    _read(context, receiver + 0x398, 8),
                    pointer,
                    count,
                ),
                width=8,
            )
            & _U32
        )
        if status not in (1, 4):
            _call(calls, 0x140DF2670, (_read(context, receiver + 0x398, 8),))
            _write(context, frame + 0x20, 8, receiver + 0x70)
            _write(context, frame + 0x28, 16, 0)
            _write(context, frame + 0x38, 8, 0)
            _call(calls, 0x140A8FB50, (frame + 0x20,))
            _call(calls, 0x140A8E1A0, (frame + 0x28,))
        return _read(context, pointer, 8)
    if _read(context, receiver + 0x318, 4) == 3:
        command = _call(calls, _FIRST, (receiver + 0x360, count), width=8)
    else:
        time = _call(calls, _CLOCK, (_read(context, receiver + 0x358, 8),), width=8) & _U32
        command = _call(calls, _SELECT, (receiver + 0x360, time, count), width=8)
    _write(context, pointer, 8, command)
    if command:
        descriptor = _read(context, receiver + 0x398, 8)
        if _read(context, descriptor, 1):
            time = _call(calls, _GAME_TIME, (_read(context, 0x144353698, 8),), width=8) & _U32
            count_value = _read(context, count, 4)
            current_command = _read(context, pointer, 8)
            status = (
                _call(
                    calls,
                    0x140DEE940,
                    (
                        descriptor,
                        current_command,
                        count_value,
                        time,
                    ),
                    width=8,
                )
                & _U32
            )
            if status == 0:
                _call(calls, 0x140DF2240, (_read(context, receiver + 0x398, 8),))
    return _read(context, pointer, 8)


def bind_replay_command_reader(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    *,
    imports: ReplayTaskRebuildCalls,
    logger_home_calls: ReplayTaskRebuildCalls,
    atomics: ReplayUnitAIMapAtomics,
    bind_local: LocalBinding,
    profile: ReplayCommandReaderProfile,
) -> ReplayTaskRebuildCalls:
    """Own ten complete bodies; all other effects delegate or refuse at reach.

    malloc/free current IATs use imports; direct/virtual children use bound
    calls. Logger takes4raw registers+HOME20 ADDRESS, never an eager fifth
    value. Unknown targets/args/data/results delegate unchanged. Only source
    lowEAX returns are defined; queue/done incidental RAX is excluded (None).
    No defaults, dictionary parser, timestamps, native identity or tick result.
    Finite terminating vectors/callbacks and valid reached backing are required;
    physical stack/cookies, faults/EH/concurrency/escaped locals are excluded.
    """
    for channel in (calls, imports, logger_home_calls):
        _validate(context, channel)
    if (
        not isinstance(atomics, ReplayUnitAIMapAtomics)
        or not callable(bind_local)
        or not isinstance(profile, ReplayCommandReaderProfile)
    ):
        raise ValueError("actual command atomic/local effects and explicit profile required")
    arities = {
        _READER: 3,
        _QUEUE: 1,
        _POLL: 1,
        _RELEASE: 2,
        _DONE: 1,
        _FIRST: 2,
        _SELECT: 3,
        _CLOCK: 1,
        _GAME_TIME: 1,
        _WORLD_TIME: 1,
    }

    def dispatch(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        if target not in arities:
            if calls.call is None:
                raise UnresolvedReplayTaskRebuild(f"reached{target:x} is unavailable")
            return calls.call(target, args, data)
        if len(args) != arities[target] or data is not None:
            raise ValueError("malformed command reader/queue call")
        _validate(context, calls, *args)
        if target == _READER:
            return _command(
                context,
                bound,
                imports,
                *args,
                atomics=atomics,
                bind_local=bind_local,
                seed=profile.reader,
            )
        if target in (_POLL, _SELECT):
            seed = profile.poller if target == _POLL else profile.selector
            with _local(memoryview(bytearray(seed)), bind_local) as frame:
                return (
                    _poll(context, bound, *args, frame=frame)
                    if target == _POLL
                    else _select(context, logger_home_calls, *args, frame=frame)
                )
        if target == _FIRST:
            return _first(context, *args)
        if target == _CLOCK:
            return _read(context, args[0] + 0x30, 4)
        if target == _WORLD_TIME:
            return _invoke(bound, 0x140E68F70, (_read(context, args[0] + 0x228, 8),))
        if target == _GAME_TIME:
            world = _read(context, args[0] + 0x5C0, 8)
            return _invoke(bound, _WORLD_TIME, (world,)) if world else 0
        if target == _DONE:
            _write(context, args[0] + 0x380, 1, 1)
            return None
        if target == _RELEASE:
            mode = _read(context, args[0] + 0x318, 4)
            if mode == 10 and args[1]:
                free = _read(context, 0x143199DD0, 8)
                return _invoke(imports, free, (args[1],))
            return mode
        manager = args[0]
        receiver = _read(context, manager + 0x2008, 8)
        if not receiver:
            return None
        command = _call(bound, _POLL, (receiver,), width=8)
        while command:
            vptr = _read(context, manager, 8)
            method = _read(context, vptr + 0x20, 8)
            _call(bound, method, (manager, command))
            receiver = _read(context, manager + 0x2008, 8)
            _call(bound, _RELEASE, (receiver, command))
            receiver = _read(context, manager + 0x2008, 8)
            command = _call(bound, _POLL, (receiver,), width=8)
        _call(bound, _DONE, (_read(context, manager + 0x2008, 8),))
        return None

    bound = ReplayTaskRebuildCalls(dispatch)
    return bound
