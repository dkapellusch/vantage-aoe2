"""Build54800 name byte-structure validation over current scalar storage.

Complete22B140a84390 and394B140a830b0 are source-closed in
player-name-validation-predicate-source-v1. This is the original structural
predicate, including accepted overlong/non-Unicode sequences. It is not a
Unicode decoder. Logical results consume AL; physical upper registers,
incoming homes, stack, faults/EH and concurrency are outside this profile.
"""

from __future__ import annotations

from vantage.replay_task_group_storage import LocalBinding
from vantage.replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
    _call,
    _read,
    _write,
)
from vantage.replay_unit_ai_base import _validate
from vantage.replay_unit_ai_construction import _local

_U64 = (1 << 64) - 1
_U32 = (1 << 32) - 1


def _lead(byte: int) -> bool:
    return byte < 0x80 or 0xC0 <= byte <= 0xF7


def scan_replay_player_name_bytes(
    context: ReplayTaskRebuildStorage,
    address: int,
    count_output: int,
    error_output: int,
) -> int:
    """Full394B140a830b0: ordered DWORD outputs and current-byte rereads.

    Counts complete structural sequences, wrapping DWORD count. Required count
    and optional error pointers are held, and their writes precede all byte
    reads. Failure writes only the optional error index; complete success
    stores the count. The selected initial lead and the reread sequence bytes
    are separate source phases, including with output/input aliases.
    """
    _validate(context, ReplayTaskRebuildCalls(None), address, count_output, error_output)
    _write(context, count_output, 4, 0)
    if error_output:
        _write(context, error_output, 4, _U32)
    sampled = _read(context, address, 1)
    count = 0
    while sampled:
        if sampled < 0x80:
            # EAX is zero at this entry; its other loop edge is unreachable
            # without an external change to native registers.
            current = _read(context, address, 1)
            valid = current != 0 and _lead(current)
            if valid:
                address = address + 1 & _U64
        else:
            if 0xC0 <= sampled <= 0xDF:
                length = 2
            elif 0xE0 <= sampled <= 0xEF:
                length = 3
            elif 0xF0 <= sampled <= 0xF7:
                length = 4
            else:
                if error_output:
                    _write(context, error_output, 4, count)
                return 0
            cursor = address
            valid = True
            for index in range(length):
                current = _read(context, cursor, 1)
                if not current or (not _lead(current) if index == 0 else current & 0xC0 != 0x80):
                    valid = False
                    break
                cursor = cursor + 1 & _U64
            if valid:
                address = cursor
        if not valid:
            if error_output:
                _write(context, error_output, 4, count)
            return 0
        sampled = _read(context, address, 1)
        count = count + 1 & _U32
    _write(context, count_output, 4, count)
    return 1


def validate_replay_player_name_bytes(
    context: ReplayTaskRebuildStorage,
    address: int,
    error_output: int,
    *,
    calls: ReplayTaskRebuildCalls,
    bind_local: LocalBinding,
    scratch: bytes,
) -> int:
    """Full22B140a84390 with actual child and explicit logical home local.

    Frame+0x40 supplies the required count DWORD. Its selected 0x44-byte logical
    frame does not establish alias parity with the physical incoming stack
    home. The actual child's low AL is returned, including noncanonical values.
    """
    _validate(context, calls, address, error_output)
    if not callable(bind_local) or type(scratch) is not bytes or len(scratch) != 0x44:
        raise ValueError("explicit0x44-byte name-validator logical frame/local binding required")
    with _local(memoryview(bytearray(scratch)), bind_local) as frame:
        return _call(calls, 0x140A830B0, (address, frame + 0x40, error_output), width=1)


def bind_replay_player_name_validation(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    *,
    bind_local: LocalBinding,
    scratch: bytes,
) -> ReplayTaskRebuildCalls:
    """Bind both original entries; delegate unknown calls to actual providers."""
    _validate(context, calls)
    if not callable(bind_local) or type(scratch) is not bytes or len(scratch) != 0x44:
        raise ValueError("explicit0x44-byte name-validator logical frame/local binding required")

    def dispatch(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        arities = {0x140A84390: 2, 0x140A830B0: 3}
        if target not in arities:
            if calls.call is None:
                raise UnresolvedReplayTaskRebuild(f"reached{target:x} is unavailable")
            return calls.call(target, args, data)
        if len(args) != arities[target] or data is not None:
            raise ValueError("malformed Player name-validation call")
        if target == 0x140A830B0:
            return scan_replay_player_name_bytes(context, *args)
        return validate_replay_player_name_bytes(
            context, *args, calls=bound, bind_local=bind_local, scratch=scratch
        )

    bound = ReplayTaskRebuildCalls(dispatch)
    return bound
