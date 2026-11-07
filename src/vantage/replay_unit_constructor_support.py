"""Build54800 Base/Moving support over current scalar storage and real imports.

Complete source bodies are retained in unit-constructor-support-source-v1.
String locals require coherent live backing; allocation, byte scanning/copying,
free and opaque children remain actual reached effects. Native stack/register,
fault/EH/concurrency and complete object restoration are outside this interface.
"""

from __future__ import annotations

from .replay_task_group_storage import LocalBinding
from .replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
    _call,
    _read,
    _write,
)
from .replay_unit_ai_base import _validate
from .replay_unit_ai_construction import _local

_U64 = (1 << 64) - 1


def initialize_replay_unit_support_header(
    context: ReplayTaskRebuildStorage,
    address: int,
    value: int,
) -> int:
    """Full44B1410b2a40: ordered widths, lowEDX and held-address return."""
    _validate(context, ReplayTaskRebuildCalls(None), address, value)
    _write(context, address + 0x14, 4, value)
    _write(context, address + 8, 8, 0)
    _write(context, address, 8, 0x14329FE18)
    _write(context, address + 0x10, 4, 0)
    _write(context, address + 0x18, 8, _U64)
    _write(context, address + 0x20, 8, _U64)
    return address


def read_replay_constructor_string_length(
    context: ReplayTaskRebuildStorage,
    descriptor: int,
) -> int:
    """Full5B140a13780: read descriptor+8; no CString inference or scan."""
    _validate(context, ReplayTaskRebuildCalls(None), descriptor)
    return _read(context, descriptor + 8, 8)


def grow_replay_constructor_string(
    context: ReplayTaskRebuildStorage,
    address: int,
    requested: int,
    *,
    calls: ReplayTaskRebuildCalls,
) -> None:
    """Full113B140a1a5e0, including the exact five right-shift spreading steps.

    Zero requested returns without accesses. Nonzero always allocates; existing
    capacity is not consulted. Store capacity before the returned pointer, even
    for a null allocation. Incidental native RAX is not a logical return here.
    """
    _validate(context, calls, address, requested)
    if not requested:
        return
    capacity = 32
    if requested >= 16:
        spread = requested - 1
        for shift in (1, 2, 4, 8, 16):
            spread |= spread >> shift
        capacity = (spread + 1) & _U64
    pointer = _call(calls, 0x142D6C268, (capacity,), width=8)
    _write(context, address + 0x10, 8, capacity)
    _write(context, address, 8, pointer)


def assign_replay_constructor_string(
    context: ReplayTaskRebuildStorage,
    address: int,
    source: int,
    *,
    calls: ReplayTaskRebuildCalls,
    bind_local: LocalBinding,
) -> None:
    """Full155B140a1a660 with concrete descriptor getter and growth body.

    Old nonnull pointer resets to the empty-address token after conditional
    free. Its BSS bytes are never inferred. A null old pointer skips all three
    resets. The initialized16B source/length local remains coherently mapped
    through its actual getter read; source and nonzero length are then held.
    Memcpy and terminator use separately current destination-pointer reads.
    """
    _validate(context, calls, address, source)
    if not callable(bind_local):
        raise ValueError("actual constructor string local binding required")
    previous = _read(context, address, 8)
    if previous:
        if _read(context, address + 0x10, 8):
            _call(calls, 0x142D6C270, (previous,))
        _write(context, address, 8, 0x14428BB30)
        _write(context, address + 0x10, 8, 0)
        _write(context, address + 8, 8, 0)
    if not source:
        return
    length = _call(calls, 0x142D6E44D, (source,), width=8)
    local = bytearray(source.to_bytes(8, "little") + length.to_bytes(8, "little"))
    with _local(memoryview(local), bind_local) as descriptor:
        length = read_replay_constructor_string_length(context, descriptor)
        if length:
            grow_replay_constructor_string(context, address, (length + 1) & _U64, calls=calls)
            destination = _read(context, address, 8)
            _call(calls, 0x142D6E3B1, (destination, source, length))
            destination = _read(context, address, 8)
            _write(context, destination + length, 1, 0)
            _write(context, address + 8, 8, length)


def reset_replay_unit_moving_buffer(
    context: ReplayTaskRebuildStorage,
    address: int,
    *,
    calls: ReplayTaskRebuildCalls,
) -> int:
    """Full63B141219f20: held-pointer free then conditional388 and final394 reset."""
    _validate(context, calls, address)
    previous = _read(context, address + 0x388, 8)
    if previous:
        _call(calls, 0x142D6C270, (previous,))
        _write(context, address + 0x388, 8, 0)
    _write(context, address + 0x394, 8, 0)
    return 0


def clear_replay_unit_support_tree(
    context: ReplayTaskRebuildStorage,
    address: int,
    *,
    calls: ReplayTaskRebuildCalls,
) -> None:
    """Full15B14106a330; the reached141071ec0 child remains mandatory."""
    _validate(context, calls, address)
    _call(calls, 0x141071EC0, (address,))


def notify_replay_unit_support_registry(
    context: ReplayTaskRebuildStorage,
    address: int,
    *,
    calls: ReplayTaskRebuildCalls,
) -> None:
    """Full41B140b2cfc0 effective helper flow; only lowAL gates the current read.

    The predicate and getter are proven argument-free global reads. The
    predicate call retains the caller's incidental forwarded RCX annotation.
    The held address supplies currentQWORD0 after the getter returns.
    """
    _validate(context, calls, address)
    if _call(calls, 0x140B2BE40, (address,), width=1):
        owner = _call(calls, 0x140B2BD90, (), width=8)
        current = _read(context, address, 8)
        _call(calls, 0x140B24580, (owner, current))


def has_replay_unit_support_registry(context: ReplayTaskRebuildStorage) -> int:
    """Full12B140b2be40: current global pointer nonnull, rawAL only."""
    _validate(context, ReplayTaskRebuildCalls(None))
    return int(_read(context, 0x1442973E0, 8) != 0)


def read_replay_unit_support_registry(context: ReplayTaskRebuildStorage) -> int:
    """Full8B140b2bd90: a separate current global read, rawRAX."""
    _validate(context, ReplayTaskRebuildCalls(None))
    return _read(context, 0x1442973E0, 8)


def return_replay_unit_support_token(
    context: ReplayTaskRebuildStorage,
    registry: int,
    token: int,
    *,
    calls: ReplayTaskRebuildCalls,
) -> None:
    """Full62B140b24580: child, current qword decrement, reread and indexed store.

    Token zero returns without storage access. The child remains mandatory.
    Registry and token are held across it; the decremented count is reread
    before selecting the final address, with native unsigned wrapping.
    """
    _validate(context, calls, registry, token)
    if not token:
        return
    _call(calls, 0x142392890, (token,))
    count = _read(context, registry + 0x4258, 8)
    _write(context, registry + 0x4258, 8, count - 1)
    count = _read(context, registry + 0x4258, 8)
    _write(context, registry + 0x258 + count * 8, 8, token)


def bind_replay_unit_constructor_support(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    *,
    bind_local: LocalBinding,
    imports: ReplayTaskRebuildCalls | None = None,
) -> ReplayTaskRebuildCalls:
    """Own ten bodies plus proven malloc/free/strlen/memcpy thunk routes.

    Current IAT-selected targets go directly to the terminal imports dispatcher,
    even if the token equals an owned thunk. Opaque children delegate or refuse.
    """
    _validate(context, calls)
    terminal = calls if imports is None else imports
    _validate(context, terminal)
    if not callable(bind_local):
        raise ValueError("actual constructor string local binding required")

    def dispatch(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        arities = {
            0x1410B2A40: 2,
            0x140A13780: 1,
            0x140A1A5E0: 2,
            0x140A1A660: 2,
            0x141219F20: 1,
            0x14106A330: 1,
            0x140B2CFC0: 1,
            0x142D6C268: 1,
            0x142D6C270: 1,
            0x142D6C90C: 1,
            0x142D6E47D: 1,
            0x142D6E44D: 1,
            0x142D6E3B1: 3,
            0x140B2BE40: -1,
            0x140B2BD90: 0,
            0x140B24580: 2,
        }
        if target not in arities:
            if calls.call is None:
                raise UnresolvedReplayTaskRebuild(f"reached{target:x} is unavailable")
            return calls.call(target, args, data)
        valid_arity = (
            len(args) in (0, 1) if target == 0x140B2BE40 else (len(args) == arities[target])
        )
        if not valid_arity or data is not None:
            raise ValueError("malformed Unit constructor support call")
        _validate(context, calls, *args)
        if target == 0x1410B2A40:
            return initialize_replay_unit_support_header(context, *args)
        if target == 0x140A13780:
            return read_replay_constructor_string_length(context, *args)
        if target == 0x140B2BE40:
            return has_replay_unit_support_registry(context)
        if target == 0x140B2BD90:
            return read_replay_unit_support_registry(context)
        if target == 0x140A1A5E0:
            grow_replay_constructor_string(context, *args, calls=bound)
        elif target == 0x140A1A660:
            assign_replay_constructor_string(context, *args, calls=bound, bind_local=bind_local)
        elif target == 0x141219F20:
            return reset_replay_unit_moving_buffer(context, *args, calls=bound)
        elif target == 0x14106A330:
            clear_replay_unit_support_tree(context, *args, calls=bound)
        elif target == 0x140B2CFC0:
            notify_replay_unit_support_registry(context, *args, calls=bound)
        elif target == 0x140B24580:
            return_replay_unit_support_token(context, *args, calls=bound)
        elif target == 0x142D6C268:
            return _call(bound, 0x142D6BA78, args, width=8)
        else:
            slot = {0x142D6E44D: 0x14319A290, 0x142D6E3B1: 0x143199930}.get(target, 0x143199DD0)
            imported = _read(context, slot, 8)
            if terminal.call is None:
                raise UnresolvedReplayTaskRebuild(f"reached{imported:x} is unavailable")
            return terminal.call(imported, args, None)
        return None

    bound = ReplayTaskRebuildCalls(dispatch)
    return bound
