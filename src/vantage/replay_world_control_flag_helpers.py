"""Complete322B/4B World control-flag helpers over explicit current storage.

Live source postRSP50 has an actual supplied address, preserving caller alias.
Prepared-register channels retain known bits; deeper consumed ABI is not inferred.
"""

from __future__ import annotations

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

_U32, _U64 = (1 << 32) - 1, (1 << 64) - 1
_ROW, _GETTER, _SETTER = 0x1416DFB20, 0x1413F7A00, 0x1412473E0


def _invoke(
    channel: ReplayTaskRebuildCalls,
    target: int,
    args: tuple[int, ...],
) -> int | None:
    if channel.call is None:
        raise UnresolvedReplayTaskRebuild(f"reached{target:x} channel is unavailable")
    return channel.call(target, tuple(value & _U64 for value in args), None)


def _al(channel: ReplayTaskRebuildCalls, target: int, args: tuple[int, ...]) -> int:
    value = _invoke(channel, target, args)
    if value is None:
        raise ValueError(f"helper{target:x} must supply its actual AL annotation")
    _unsigned(value, 1, f"helper{target:x} actual AL")
    return value


def read_replay_control_flag_dword(context: ReplayTaskRebuildStorage, receiver: int) -> int:
    """Complete4B1413f7a00; current DWORD7c zero-extended to full RAX."""
    _validate(context, ReplayTaskRebuildCalls(None), receiver)
    return _read(context, receiver + 0x7C, 4)


def _row(
    context: ReplayTaskRebuildStorage,
    receiver: int,
    value: int,
    *,
    decode_home: int,
    virtual_calls: ReplayTaskRebuildCalls,
    setter_calls: ReplayTaskRebuildCalls,
) -> int:
    held_list = _read(context, receiver + 0x30, 8)
    index, enabled = 0, value & 0xFF
    if _signed(_read(context, held_list + 0x10, 4), 4) <= 0:
        return held_list
    offset = 0
    while True:
        array = _read(context, held_list + 8, 8)
        unit = _read(context, array + offset, 8)
        encoded = _read(context, unit + 0x10, 8)
        _write(context, decode_home, 8, encoded)
        _write(context, decode_home, 8, _read(context, decode_home, 8) - 0x6A586EB28AC201FC)
        _write(context, decode_home, 8, _read(context, decode_home, 8) - 0x0CF19788B2554E70)
        master = _read(context, decode_home, 8)
        _write(context, decode_home, 8, _read(context, master + 0x38, 8))
        _write(context, decode_home, 8, _read(context, decode_home, 8) - 0x50A06BCECEBEF905)
        _write(context, decode_home, 8, _read(context, decode_home, 8) + 0x5B32AA7995D95916)
        word = _read(context, decode_home, 8)
        if word & 0xFFFF <= 0x15 and (0x280014 >> (word & 31)) & 1:
            known_value, known_mask = 0, _U64
            if enabled:
                vptr = _read(context, unit, 8)
                target = _read(context, vptr + 0x2F8, 8)
                if _al(virtual_calls, target, (unit, 0x50A06BCECEBEF901, _U64)):
                    known_value, known_mask = 1, 0xFF
            _invoke(setter_calls, _SETTER, (unit, known_value, known_mask))
        held_list = _read(context, receiver + 0x30, 8)
        index = (index + 1) & _U32
        offset = (offset + 8) & _U64
        if _signed(index, 4) >= _signed(_read(context, held_list + 0x10, 4), 4):
            return held_list


def bind_replay_world_control_flag_helpers(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    *,
    decode_home: int,
    virtual_calls: ReplayTaskRebuildCalls,
    setter_calls: ReplayTaskRebuildCalls,
) -> ReplayTaskRebuildCalls:
    """Bind only322B1416dfb20 and4B1413f7a00, preserving unknown identity.

    decode_home is actual coherent current8B backing for source postRSP50.
    World303 supplies its logical_frame (native child50 aliases parentRSP0).
    It is accessed only after the reached unit10 load; no seed/mapping is added.
    Distinct nested callers require correctly scoped home/capability bindings.

    Dedicated channel args are (unit,knownRDXvalue,knownRDXmask) annotations,
    never native positional arguments. Virtual receives full-known...f901/U64
    and returns only actual ALu8. Setter receives full0/U64 or lowDL1/FF and
    has an opaque ignored return. Providers must refuse if any truly consumed
    ABI bits/registers/stack are unavailable; no only-DL callee claim is made.

    Native GP save/restore20/28/58/60/68 and physical register/stack/EH/fault/
    concurrency identity are excluded, with no fabricated stores. Live50 alias
    and every semantic read/store remain owned. Actual current backing and
    source-terminating callbacks are required; no count cap or success is added.
    """
    _validate(context, calls, decode_home)
    if any(
        not isinstance(channel, ReplayTaskRebuildCalls) for channel in (virtual_calls, setter_calls)
    ):
        raise ValueError("explicit prepared-register virtual and setter channels required")

    def dispatch(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        if target not in (_ROW, _GETTER):
            if calls.call is None:
                raise UnresolvedReplayTaskRebuild(f"reached{target:x} is unavailable")
            return calls.call(target, args, data)
        expected = 2 if target == _ROW else 1
        if len(args) != expected or data is not None:
            raise ValueError(f"actual{target:x} prepared arity/data required")
        _validate(context, calls, *args)
        if target == _GETTER:
            return read_replay_control_flag_dword(context, args[0])
        return _row(
            context,
            args[0],
            args[1],
            decode_home=decode_home,
            virtual_calls=virtual_calls,
            setter_calls=setter_calls,
        )

    return ReplayTaskRebuildCalls(dispatch)
