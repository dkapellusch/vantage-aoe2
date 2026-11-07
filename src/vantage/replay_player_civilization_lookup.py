"""Build54800 civilization lookup124B, DEString cleanup55B and equality54B.

These whole callers require actual selector/search/free/memcmp descendants.
No registry contents, initialized globals, default resource or successful name
lookup is fabricated. The live8B descriptor home is explicitly seeded; native
physical incoming-home/register/fault/EH/concurrency parity is excluded.
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


def lookup_replay_player_civilization(
    context: ReplayTaskRebuildStorage,
    name: int,
    *,
    calls: ReplayTaskRebuildCalls,
    bind_local: LocalBinding,
    scratch: bytes,
) -> int:
    """Full124B140f6a4b0; held input, actual descriptorRAX and held DWORDs.

    The descriptor helper may write only5 of its8 bytes. Its actual returned
    pointer, rather than an assumed fixed local, reaches the selector. Nonzero
    lookup ID returns the held resource even when null; IDzero needs actual
    equality only if the returned resource is nonnull. Missing providers refuse.
    """
    _validate(context, calls, name)
    if not callable(bind_local) or type(scratch) is not bytes or len(scratch) != 8:
        raise ValueError("actual local binding and explicit8B descriptor-home seed required")
    with _local(memoryview(bytearray(scratch)), bind_local) as descriptor_home:
        descriptor = _call(calls, 0x140FA3420, (descriptor_home,), width=8)
        selector = _call(calls, 0x140FA36A0, (descriptor,), width=4)
        index = _call(calls, 0x140F6A690, (name, selector), width=4)
        resource = _call(calls, 0x140F6A320, (index, selector), width=8)
        if index:
            return resource
        if not resource:
            return 0
        equal = _call(calls, 0x140A15CA0, ((resource + 0x58) & _U64, name), width=1)
        return resource if equal else 0


def clear_replay_player_de_string(
    context: ReplayTaskRebuildStorage,
    address: int,
    *,
    calls: ReplayTaskRebuildCalls,
) -> None:
    """Full55B140a1b220; pointer-first null gate and ordered current cleanup.

    Null pointer skips capacity, free and resets. A nonnull pointer is freed
    only with nonzero current capacity. The source consumes no returned scalar;
    native RAX on its null branch is not represented as a fabricated value.
    """
    _validate(context, calls, address)
    pointer = _read(context, address, 8)
    if not pointer:
        return
    if _read(context, address + 16, 8):
        _call(calls, 0x142D6C270, (pointer,))
    _write(context, address, 8, 0x14428BB30)
    _write(context, address + 16, 8, 0)
    _write(context, address + 8, 8, 0)


def equal_replay_player_de_strings(
    context: ReplayTaskRebuildStorage,
    left: int,
    right: int,
    *,
    calls: ReplayTaskRebuildCalls,
) -> int:
    """Full54B140a15ca0; consumed AL, actual memcmp when equal nonzero lengths.

    Hold left length before the current right length. Unequal or equalzero
    lengths skip both pointers. Otherwise read right pointer before left;
    the held length reaches142d6e3bd and its raw EAX is compared with zero.
    This does not bypass that thunk's required current import/provider effect.
    """
    _validate(context, calls, left, right)
    length = _read(context, left + 8, 8)
    if length != _read(context, right + 8, 8):
        return 0
    if not length:
        return 1
    right_pointer = _read(context, right, 8)
    left_pointer = _read(context, left, 8)
    result = _call(calls, 0x142D6E3BD, (left_pointer, right_pointer, length), width=4)
    return int(result == 0)


def bind_replay_player_civilization_lookup(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    *,
    bind_local: LocalBinding,
    scratch: bytes,
) -> ReplayTaskRebuildCalls:
    """Bind exactly the233B callers; opaque registry/runtime effects delegate."""
    _validate(context, calls)
    if not callable(bind_local) or type(scratch) is not bytes or len(scratch) != 8:
        raise ValueError("actual local binding and explicit8B descriptor-home seed required")

    def dispatch(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        arities = {0x140F6A4B0: 1, 0x140A1B220: 1, 0x140A15CA0: 2}
        if target not in arities:
            if calls.call is None:
                raise UnresolvedReplayTaskRebuild(f"reached{target:x} is unavailable")
            return calls.call(target, args, data)
        if len(args) != arities[target] or data is not None:
            raise ValueError("malformed Player civilization lookup/cleanup/equality call")
        if target == 0x140F6A4B0:
            return lookup_replay_player_civilization(
                context, *args, calls=bound, bind_local=bind_local, scratch=scratch
            )
        if target == 0x140A1B220:
            clear_replay_player_de_string(context, *args, calls=bound)
            return None
        return equal_replay_player_de_strings(context, *args, calls=bound)

    bound = ReplayTaskRebuildCalls(dispatch)
    return bound
