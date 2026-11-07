"""Build54800 common UnitAI constructor, class-range assignment and timer caller.

Complete140d094c0/140cefb30/140d19dd0 source is retained in
tc-unit-ai15-constructor-children-source-v1. Current RNG/objects/virtuals,
positions, reserve and CRT bindings are required at reach. No whole saved AI
or constructor-time random state is inferred from a logical master/seed.
"""

from __future__ import annotations

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

_U64 = (1 << 64) - 1
_U32 = (1 << 32) - 1
_MASTER_ADD = 0x6A586EB28AC201FC + 0x0CF19788B2554E70


def _validate(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    *values: int,
) -> None:
    if not isinstance(context, ReplayTaskRebuildStorage):
        raise ValueError("explicit current UnitAI storage required")
    if not isinstance(calls, ReplayTaskRebuildCalls):
        raise ValueError("actual reached UnitAI effects required")
    for value in values:
        _unsigned(value, 8, "UnitAI base argument")


def _count(end: int, begin: int) -> int:
    return (_signed((end - begin) & _U64, 8) >> 2) & _U64


def assign_replay_unit_ai_classes(
    context: ReplayTaskRebuildStorage,
    vector: int,
    source_range: int,
    *,
    calls: ReplayTaskRebuildCalls,
) -> int:
    """Full140cefb30; held source range, current reserve/second-copy destination.

    Preserve the native unsigned comparisons of signed-SAR sizes, zero-byte
    moves, split-copy order and held-pointer end commits. No removed-element
    destruction or capacity reset is invented. Successful finite valid backing
    is required; prior helper/write effects survive failures.
    """
    _validate(context, calls, vector, source_range)
    begin = _read(context, vector, 8)
    capacity_end = _read(context, vector + 16, 8)
    source = _read(context, source_range, 8)
    capacity = _count(capacity_end, begin)
    requested = _count(_read(context, source_range + 8, 8), source)
    if requested > capacity:
        _call(calls, 0x1402BA470, (vector, requested))
        begin = _read(context, vector, 8)
        byte_count = requested * 4 & _U64
        _call(calls, 0x142D6E3DB, (begin, source, byte_count))
    else:
        length = _count(_read(context, vector + 8, 8), begin)
        if length < requested:
            prefix_bytes = length * 4 & _U64
            _call(calls, 0x142D6E3DB, (begin, source, prefix_bytes))
            begin = _read(context, vector + 8, 8)
            byte_count = (requested - length) * 4 & _U64
            _call(calls, 0x142D6E3DB, (begin, (source + prefix_bytes) & _U64, byte_count))
        else:
            byte_count = requested * 4 & _U64
            _call(calls, 0x142D6E3DB, (begin, source, byte_count))
    _write(context, vector + 8, 8, begin + byte_count)
    return vector


def set_replay_unit_ai_retarget_timer(
    context: ReplayTaskRebuildStorage,
    address: int,
    timeout: int,
    *,
    calls: ReplayTaskRebuildCalls,
) -> int | None:
    """Full16B140d19dd0: hold vptr, store lowEDX, then current held-table virtual1a8.

    Forward rawRDX and the selected callback's effective scalar result. This
    is a real tail callback, not a store-only leaf. Provider side effects at
    the timer store may change the table slot; the held vptr is not reread.
    """
    _validate(context, calls, address, timeout)
    vtable = _read(context, address, 8)
    _write(context, address + 0x170, 4, timeout)
    target = _read(context, vtable + 0x1A8, 8)
    if calls.call is None:
        raise UnresolvedReplayTaskRebuild(f"reached{target:x} is unavailable")
    return calls.call(target, (address, timeout), None)


def _coordinate(context: ReplayTaskRebuildStorage, subject: int, offset: int) -> int:
    raw = _read(context, subject + offset, 8)
    if offset == 0x170:
        return (raw - 0x183CAC30D2441D0E + 0x4C3FBA69E4EA7FD1) & _U32
    if offset == 0x178:
        return (raw - 0x61501AA6ECFD980A + 0x6C5EAB60B426DD28) & _U32
    return (raw + 0x2B3719EF44DE99FF + 0x21D14A25ED7C802C) & _U32


def _array_size(count: int, stride: int) -> int:
    return min(count * stride, _U64)


def construct_replay_unit_ai_base(
    context: ReplayTaskRebuildStorage,
    address: int,
    subject: int,
    count: int,
    flag: int,
    *,
    calls: ReplayTaskRebuildCalls,
) -> int:
    """Full1365B140d094c0 scalar caller with actual current descendants.

    Count/flag stores truncate to DWORD; subsequent array sizes use CURRENT
    signed fields, with unsigned multiply overflow saturation. Record52 leaves
    its three padding bytes untouched; array24 has no initialization stores.
    Three RNG draws are mandatory and preserve their own effects on failure.
    Zero idle-time divisor refuses after its draw; native trap/EH parity is
    excluded. Finite valid allocations, backing and actual callbacks required.
    """
    _validate(context, calls, address, subject, count, flag)
    for offset, width, value in (
        (0, 8, 0x14324B288),
        (8, 8, subject),
        (0x10, 8, _U64),
        (0x18, 4, 0),
        (0x1C, 4, count),
        (0x28, 4, 0),
        (0x2C, 4, count),
        (0x38, 1, 0),
        (0x3C, 8, _U64),
        (0x44, 8, _U64),
        (0x4C, 4, _U32),
        (0x50, 4, 0xBF800000),
        (0x54, 4, 0xBF800000),
        (0x58, 4, 0xBF800000),
        (0x5C, 4, 0x40000000),
        (0x60, 8, _U64),
        (0x68, 8, _U64),
        (0x70, 4, _U32),
        (0x78, 8, _U64),
        (0x80, 8, 0),
        (0x88, 8, 0),
        (0x90, 8, _U64),
        (0x98, 8, 0),
        (0xA0, 4, 0),
        (0xB0, 8, address + 0x78),
        (0xA8, 8, address + 0x78),
    ):
        _write(context, address + offset, width, value)
    random = _call(calls, 0x140903E40, (0x1443530F0, 0x14324B4E0, 0x184), width=4)
    _write(context, address + 0xBC, 4, random % 500)
    for offset, width, value in (
        (0xC0, 8, 0),
        (0xC8, 8, 0),
        (0xD0, 8, 0),
        (0xD8, 4, 0),
        (0xDC, 4, 10),
        (0x160, 8, 0),
        (0x168, 4, 0),
        (0x170, 4, 3000),
        (0x174, 8, 750),
        (0x17C, 8, 1000),
        (0x194, 4, 0x3F800000),
        (0x198, 8, 0),
        (0x1A0, 8, 0),
        (0x1A8, 8, 0),
        (0x1B0, 2, 0x300),
    ):
        _write(context, address + offset, width, value)
    _write(context, address + 0x1B4, 4, _coordinate(context, subject, 0x170))
    _write(context, address + 0x1B8, 4, _coordinate(context, subject, 0x178))
    for offset, width, value in (
        (0x1BC, 4, 0),
        (0x1C0, 1, 0),
        (0x1C4, 4, _U32),
        (0x1C8, 8, 0),
        (0x1D0, 4, 0),
        (0x1D8, 4, _U32),
        (0x1DC, 2, 0),
        (0x1DE, 1, 0),
        (0x1E0, 8, 0),
        (0x1E8, 8, 0),
        (0x1F0, 4, flag),
    ):
        _write(context, address + offset, width, value)
    master = (_read(context, subject + 0x10, 8) - _MASTER_ADD) & _U64
    encoded_class = _read(context, master + 0x38, 8)
    kind = _signed((encoded_class - 0x50A06BCECEBEF905 + 0x5B32AA7995D95916) & 0xFFFF, 2)
    _write(context, address + 0x14, 4, kind)
    target = _read(context, _read(context, subject, 8) + 0x228, 8)
    _write(context, address + 0x194, 4, _call(calls, target, (subject,), width=4))
    position_kind = _call(calls, 0x14124DD50, (subject,), width=8) & 0xFFFF
    allocation = _call(calls, 0x142D6BA78, (16,), width=8)
    position = 0
    if allocation:
        z = _coordinate(context, subject, 0x180)
        y = _coordinate(context, subject, 0x178)
        x = _coordinate(context, subject, 0x170)
        position = _call(calls, 0x140C285F0, (allocation, x, y, z, position_kind), width=8)
    previous = _read(context, address + 0xC0, 8)
    _write(context, address + 0xC0, 8, position)
    if previous:
        _call(calls, 0x142D6BAB4, (previous, 16))
    current_count = _signed(_read(context, address + 0x1C, 4), 4) & _U64
    records = _call(calls, 0x142D6C268, (_array_size(current_count, 52),), width=8)
    if records:
        for index in range(current_count):
            for offset, width, value in (
                (0, 4, _U32),
                (4, 4, 706),
                (8, 8, _U64),
                (16, 4, _U32),
                (20, 4, 0xBF800000),
                (24, 4, 0xBF800000),
                (28, 4, 0xBF800000),
                (32, 4, 0),
                (36, 4, 0xBF800000),
                (40, 4, 0xBF800000),
                (44, 1, 0),
                (48, 4, _U32),
            ):
                _write(context, records + index * 52 + offset, width, value)
    _write(context, address + 0x20, 8, records)
    current_count = _signed(_read(context, address + 0x2C, 4), 4) & _U64
    slots = _call(calls, 0x142D6C268, (_array_size(current_count, 24),), width=8)
    _write(context, address + 0x30, 8, slots)
    for offset in (0x184, 0x188, 0x18C):
        _write(context, address + offset, 4, 0xBF800000)
    _write(context, address + 0xA8, 8, address + 0x78)
    _write(context, address + 0xB0, 8, address + 0x78)
    _write(context, address + 0xB8, 4, 0)
    idle = _read(context, address + 0x170, 4)
    random = _call(calls, 0x140903E40, (0x1443530F0, 0x14324D5B0, 0x1A6C), width=4)
    divisor = idle >> 1
    if not divisor:
        raise UnresolvedReplayTaskRebuild("UnitAI adjusted idle-time divisor is zero")
    _write(context, address + 0x16C, 4, random % divisor + ((idle * 3 & _U32) >> 2))
    random = _call(calls, 0x140903E40, (0x1443530F0, 0x14324D5D0, 0x1A8B), width=4)
    _write(context, address + 0x1D4, 4, random % 500 + 750)
    return address


def bind_replay_unit_ai_base(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    *,
    imports: ReplayTaskRebuildCalls | None = None,
) -> ReplayTaskRebuildCalls:
    """Bind complete callers; optional terminal imports bypass composed body binders."""
    _validate(context, calls)
    terminal = calls if imports is None else imports
    _validate(context, terminal)

    def delegate(
        target: int,
        args: tuple[int, ...],
        data: memoryview | None,
        *,
        imported: bool = False,
    ) -> int | None:
        receiver = terminal if imported else calls
        if receiver.call is None:
            raise UnresolvedReplayTaskRebuild(f"reached{target:x} is unavailable")
        return receiver.call(target, args, data)

    def dispatch(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        arities = {
            0x140D094C0: 4,
            0x140CEFB30: 2,
            0x140D19DD0: 2,
            0x142D6C268: 1,
            0x142D6E3DB: 3,
            0x142D6BAB4: 2,
        }
        if target not in arities:
            return delegate(target, args, data)
        if len(args) != arities[target] or data is not None:
            raise ValueError("malformed UnitAI base call")
        if target == 0x140D094C0:
            return construct_replay_unit_ai_base(context, *args, calls=bound)
        if target == 0x140CEFB30:
            return assign_replay_unit_ai_classes(context, *args, calls=bound)
        if target == 0x140D19DD0:
            return set_replay_unit_ai_retarget_timer(context, *args, calls=bound)
        for value in args:
            _unsigned(value, 8, "UnitAI runtime argument")
        if target == 0x142D6C268:
            return _call(bound, 0x142D6BA78, args, width=8)
        iat = 0x1431999A0 if target == 0x142D6E3DB else 0x143199DD0
        return delegate(_read(context, iat, 8), args, None, imported=True)

    bound = ReplayTaskRebuildCalls(dispatch)
    return bound
