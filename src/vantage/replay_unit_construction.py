"""Build54800 whole Base/Animated/Moving/Action/Combat/Unit constructor callers.

Source: unit-constructor-chronology-source-v1, six complete original bodies.
Every reached parent, subobject, Result, reader, destructor and runtime child
requires real effects. Explicit local seeds do not imply an initialized input
Result, owner/World identity, complete saved restore or successful construction.
Native save registers, physical cross-frame stack aliases, cookies, faults,
concurrency and C++ EH are outside this logical normal-call profile.
"""

from __future__ import annotations

from collections.abc import Callable
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

_U64 = (1 << 64) - 1
_U32 = (1 << 32) - 1
_BASE, _ANIMATED, _MOVING = 0x14122E1B0, 0x141141760, 0x141206510
_ACTION, _COMBAT, _UNIT = 0x141136EC0, 0x141143C30, 0x1412A5D60
# entry: (seed name, late fifth-slot offset, local Result offset, reader, parent)
_ENTRIES = {
    _BASE: ("base", 0xC0, 0x30, 0x14125D730, None),
    _ANIMATED: ("animated", 0xB0, 0x30, 0x141142A70, _BASE),
    _MOVING: ("moving", 0xB0, 0x30, 0x14121F910, _ANIMATED),
    _ACTION: ("action", 0xB0, 0x30, 0x14113E920, _MOVING),
    _COMBAT: ("combat", 0xD0, 0x40, 0x1411587A0, _ACTION),
    _UNIT: ("unit", 0xD0, 0x40, 0x1412D4F50, _COMBAT),
}


@dataclass(frozen=True, slots=True)
class ReplayUnitConstructionScratch:
    """Six explicit coherent logical frames, including each late fifth DWORD.

    Offsets use each constructor's post-prologue RSP. Result locals and the
    reused scalar temporaries remain addressable until that caller returns.
    The low32 input flag is materialized once at entry, then read from current
    storage at its actual late gate. Local/argument aliases within a caller
    require coherent supplied backing. Physical argument homes, saved-register
    areas, nested machine-stack overlap and escaped use after return are not
    represented; untouched bytes retain their supplied seeds.
    """

    base: bytes
    animated: bytes
    moving: bytes
    action: bytes
    combat: bytes
    unit: bytes

    def __post_init__(self) -> None:
        for name, flag, _result, _reader, _parent in _ENTRIES.values():
            value = getattr(self, name)
            if type(value) is not bytes or len(value) != flag + 4:
                raise ValueError(f"explicit {name} construction frame requires {flag + 4} bytes")


@dataclass(frozen=True, slots=True)
class ReplayUnitConstructionFloatingCalls:
    """Mandatory selected E8/F0 effects with the caller's raw XMM boundary.

    call(target, scalar_args, xmm1) returns raw128 XMM0 for the first call;
    None on that return is unavailable. The second call receives that exact
    raw128 value in XMM1 and its return is ignored. None input means this
    caller supplies no admitted XMM1 operand, not that unknown callees cannot
    inspect residual native registers. Those selected signatures/effects are
    provider premises, not newly source-closed callback implementations.
    """

    call: Callable[[int, tuple[int, ...], int | None], int | None] | None

    def __post_init__(self) -> None:
        if self.call is not None and not callable(self.call):
            raise ValueError(
                "actual constructor floating-call provider or unavailable binding required"
            )


def _stores(
    context: ReplayTaskRebuildStorage,
    address: int,
    fields: tuple[tuple[int, int, int], ...],
) -> None:
    for offset, width, value in fields:
        _write(context, address + offset, width, value)


def _step(context: ReplayTaskRebuildStorage, slot: int, operation: str, value: int) -> None:
    current = _read(context, slot, 8)
    result = current + value if operation == "+" else current - value
    if operation == "^":
        result = current ^ value
    _write(context, slot, 8, result)


def _encoded_zero(
    context: ReplayTaskRebuildStorage,
    slot: int,
    destination: int,
    operations: tuple[tuple[str, int], ...],
    *,
    first: bool = False,
) -> None:
    # Later DWORD clears intentionally preserve the then-current upper word.
    _write(context, slot, 8 if first else 4, 0)
    if not first:
        _write(context, slot, 8, _read(context, slot, 8))
    for operation, value in operations:
        _step(context, slot, operation, value)
    _write(context, destination, 8, _read(context, slot, 8))


def _sentinel(
    context: ReplayTaskRebuildStorage,
    destination: int,
    calls: ReplayTaskRebuildCalls,
) -> None:
    pointer = _call(calls, 0x142D6BA78, (40,), width=8)
    # No successful null-allocation branch exists in these caller instructions.
    for offset in (0, 8, 16):
        _write(context, pointer + offset, 8, pointer)
    _write(context, pointer + 24, 2, 0x101)
    _write(context, destination, 8, pointer)


def _base(
    context: ReplayTaskRebuildStorage,
    obj: int,
    frame: int,
    calls: ReplayTaskRebuildCalls,
) -> None:
    _write(context, frame + 0x28, 8, obj)
    _stores(context, obj, ((0, 8, 0x1432B4078), (8, 4, _U32), (12, 4, 0)))
    slot = frame + 0x20
    _encoded_zero(
        context, slot, obj + 0x10, (("+", 0xCF19788B2554E70), ("+", 0x6A586EB28AC201FC)), first=True
    )
    _stores(
        context,
        obj,
        (
            (0x18, 8, 0),
            (0x20, 8, 0),
            (0x28, 8, 0),
            (0x30, 4, _U32),
            (0x38, 16, 0),
            (0x48, 8, 0),
            (0x50, 8, 15),
            (0x38, 1, 0),
            *((offset, 8, 0) for offset in range(0x58, 0xC0, 8)),
        ),
    )
    _call(calls, 0x14122DC70, ((obj + 0xC0) & _U64,))
    _write(context, obj + 0x100, 4, 0)
    _call(calls, 0x1410B2A40, ((obj + 0x108) & _U64, 2000))
    _encoded_zero(context, slot, obj + 0x130, (("+", 0x147B5E081EC087D9), ("^", 0xF2A55F7A61DD00E)))
    _stores(
        context,
        obj,
        (
            (0x138, 8, 0),
            (0x141, 1, 0),
            (0x148, 8, 0),
            (0x150, 8, 0),
            (0x158, 8, 0),
            (0x160, 4, _U32),
            (0x164, 2, 0),
            (0x168, 8, 0),
        ),
    )
    _encoded_zero(
        context, slot, obj + 0x170, (("-", 0x4C3FBA69E4EA7FD1), ("+", 0x183CAC30D2441D0E))
    )
    _encoded_zero(
        context, slot, obj + 0x178, (("-", 0x6C5EAB60B426DD28), ("+", 0x61501AA6ECFD980A))
    )
    _encoded_zero(
        context, slot, obj + 0x180, (("-", 0x21D14A25ED7C802C), ("-", 0x2B3719EF44DE99FF))
    )
    _stores(
        context,
        obj,
        (
            (0x188, 4, 0),
            (0x18C, 8, 0),
            (0x194, 4, _U32),
            (0x198, 4, 0),
            (0x1A0, 8, 0),
            (0x1A8, 8, 0),
            (0x1B0, 8, 0),
            (0x1B8, 8, 0),
            (0x1C0, 4, 0),
            (0x1C4, 4, 0x1000001),
            (0x1C8, 4, 0x1010100),
            (0x1CC, 1, 0),
            (0x1D0, 8, 0),
            (0x1D8, 8, 0),
            (0x1E0, 8, 0),
            (0x1E8, 2, 0xFFFF),
            (0x1F0, 8, 0),
            (0x1F8, 8, 0),
            (0x200, 8, 0),
            (0x210, 4, _U32),
            (0x214, 4, 0xFFFFFFFE),
            *((offset, 8, 0) for offset in range(0x218, 0x290, 8)),
            (0x290, 4, _U32),
            (0x294, 2, 0),
        ),
    )
    for offset in (0x298, 0x2B0):
        _stores(context, obj + offset, ((0, 8, 0x14428BB30), (8, 8, 0), (16, 8, 0)))
        _call(calls, 0x140A1A660, ((obj + offset) & _U64, 0x143676DC8))
    _stores(
        context,
        obj,
        (
            (0x2C8, 2, 0xFFFF),
            (0x2CA, 1, 0),
            (0x2CC, 4, 0),
            (0x2D0, 8, _U64),
            (0x2D8, 8, 0),
            (0x2E0, 8, 0),
            (0x2E8, 8, 0),
        ),
    )
    _sentinel(context, obj + 0x2E0, calls)
    _write(context, obj + 0x2F0, 4, 0)
    _call(calls, 0x14122DBF0, ((obj + 0x2F8) & _U64,))
    _stores(context, obj, ((0x338, 8, 0), (0x340, 8, 0), (0x348, 8, 0)))


def _propagate(
    context: ReplayTaskRebuildStorage,
    output: int,
    local: int,
    returned: int,
    cleanup: int,
    calls: ReplayTaskRebuildCalls,
    atomics: ReplayUnitAIMapAtomics,
) -> None:
    _write(context, returned + 40, 1, 1)
    _call(calls, 0x14090D270, ((output + 24) & _U64, (returned + 24) & _U64))
    if output != returned:
        begin = _read(context, returned, 8)
        end = _read(context, returned + 8, 8)
        count = (_signed((end - begin) & _U64, 8) >> 5) & _U64
        _call(calls, 0x1402B9080, (output, begin, count))
    _write(context, output + 40, 1, 0)
    control = _read(context, local + 32, 8)
    if control:
        _release(context, control, calls, atomics)
    _call(calls, cleanup, (local,))


def _moving_initial(context: ReplayTaskRebuildStorage, obj: int) -> None:
    _stores(
        context,
        obj,
        (
            (0, 8, 0x1432B2838),
            *((offset, 8, 0) for offset in range(0x368, 0x390, 8)),
            (0x390, 4, 0),
            (0x3A0, 4, _U32),
            (0x3A4, 4, 0),
            (0x3B0, 8, 0),
            (0x3B8, 2, 0),
            (0x3BC, 8, 0),
            (0x3C4, 4, 0),
            (0x3C8, 8, 0x3F800000),
            (0x3D0, 8, 0),
            (0x3D8, 4, 0),
            (0x3DC, 4, 0xBF800000),
            (0x3E0, 8, 0),
            (0x3E8, 4, 0),
            (0x3F0, 8, 0),
            (0x3F8, 8, 0),
            (0x400, 8, 0),
            (0x408, 8, 0),
            (0x410, 4, 0),
            (0x414, 4, 0x3F800000),
            (0x418, 4, 0x3F800000),
        ),
    )


def _moving_success(
    context: ReplayTaskRebuildStorage,
    obj: int,
    calls: ReplayTaskRebuildCalls,
) -> None:
    _stores(context, obj, ((0x370, 8, 0), (0x378, 8, 0), (0x380, 8, 0), (0x391, 2, 0)))
    target = _read(context, _read(context, obj, 8) + 0x490, 8)
    # Native distinguishes equal/direct and other/virtual; both real routes
    # dispatch the once-held selected target with the same explicit RCX.
    _call(calls, 0x141219F20 if target == 0x141219F20 else target, (obj,))
    _stores(
        context,
        obj,
        (
            (0x3BC, 8, 0),
            (0x3C4, 4, 0),
            (0x3C8, 8, 0x3F800000),
            (0x3D0, 8, 0),
            (0x3D8, 4, 0),
            (0x3DC, 4, 0xBF800000),
        ),
    )
    for offset in (0x3F0, 0x3F8):
        pointer = _read(context, obj + offset, 8)
        if pointer:
            _call(calls, 0x14106A330, (pointer,))
            _call(calls, 0x142D6BAB4, (pointer, 72))
            _write(context, obj + offset, 8, 0)
    pointer = _read(context, obj + 0x400, 8)
    if pointer:
        _call(calls, 0x142D6BAB4, (pointer, 24))
        _write(context, obj + 0x400, 8, 0)
    _stores(context, obj, ((0x408, 8, 0), (0x3B9, 1, 0), (0x410, 4, 0)))
    pointer = _read(context, obj + 0x3B0, 8)
    if pointer:
        _call(calls, 0x140B2CFC0, (pointer,))
        _call(calls, 0x142D6BAB4, (pointer, 8))
        _write(context, obj + 0x3B0, 8, 0)


def _action(context: ReplayTaskRebuildStorage, obj: int, calls: ReplayTaskRebuildCalls) -> None:
    _stores(
        context,
        obj,
        (
            (0, 8, 0x1432A5708),
            (0x429, 1, 0),
            (0x430, 4, _U32),
            (0x434, 4, 0),
            (0x448, 8, 0),
            (0x450, 8, 0),
            (0x458, 8, 0),
        ),
    )
    _call(calls, 0x141136CA0, ((obj + 0x460) & _U64,))


def _combat(context: ReplayTaskRebuildStorage, obj: int, calls: ReplayTaskRebuildCalls) -> None:
    _stores(
        context,
        obj,
        (
            (0, 8, 0x1432A70D0),
            (0x4A1, 1, 0),
            (0x500, 8, 0),
            (0x508, 8, 0),
            (0x510, 4, 0),
            (0x520, 8, 0),
            (0x528, 8, 0),
        ),
    )
    _sentinel(context, obj + 0x520, calls)
    _stores(context, obj, ((0x530, 8, 0), (0x538, 8, 0), (0x540, 8, 0)))
    _call(calls, 0x1411438B0, ((obj + 0x548) & _U64,))
    _stores(
        context,
        obj,
        (
            (0x58C, 1, 0),
            (0x590, 4, 0),
            (0x594, 1, 0),
            (0x598, 4, 0),
            (0x59C, 4, _U32),
            (0x5A0, 4, 0),
            *((offset, 8, 0) for offset in range(0x5A8, 0x5D8, 8)),
        ),
    )
    _call(calls, 0x141143930, ((obj + 0x5D8) & _U64,))


def _unit(context: ReplayTaskRebuildStorage, obj: int, calls: ReplayTaskRebuildCalls) -> None:
    _stores(
        context,
        obj,
        (
            (0, 8, 0x1432B8270),
            (0x618, 8, 0),
            (0x620, 4, 0),
            (0x624, 2, 0),
            (0x628, 8, 0),
            (0x630, 1, 0),
            (0x634, 8, _U64),
            (0x63C, 8, _U64),
            (0x644, 4, 0xBF800000),
            (0x648, 8, 0xFFFFFFFFBF800000),
            (0x650, 8, _U64),
            (0x658, 4, _U32),
            (0x65C, 4, 0xBF800000),
            (0x660, 4, 0xBF800000),
            (0x664, 1, 0),
            (0x668, 8, 0),
            (0x670, 2, 0),
            (0x674, 4, 0),
            (0x678, 8, 0),
            (0x680, 8, 0),
            (0x688, 4, 0),
            (0x68C, 2, 0),
            (0x690, 4, 0),
            (0x694, 1, 0),
            (0x698, 4, 0),
            (0x69C, 1, 1),
            (0x69E, 2, 0xFFFF),
            (0x6A0, 8, _U64),
            (0x6A8, 2, 0xFFFF),
            *((offset, 8, 0) for offset in range(0x6AC, 0x6DC, 8)),
            (0x6DC, 4, 0),
        ),
    )
    _call(calls, 0x1412A5CE0, ((obj + 0x6E0) & _U64,))
    _stores(context, obj, ((0x720, 8, 0), (0x728, 8, 0)))
    _sentinel(context, obj + 0x720, calls)
    _stores(
        context,
        obj,
        (
            (0x730, 8, 0),
            (0x738, 8, 0),
            (0x740, 8, 0),
            (0x748, 8, 0),
            (0x750, 8, 0),
            (0x758, 1, 0),
            (0x75C, 8, 0),
        ),
    )
    _call(calls, 0x1412A5C60, ((obj + 0x768) & _U64,))
    _stores(
        context,
        obj,
        (
            *((offset, 8, 0) for offset in range(0x7A8, 0x7D8, 8)),
            (0x7D8, 4, 0),
            (0x7DC, 1, 0),
            (0x7E0, 8, 0),
            (0x7E8, 4, 0),
            (0x7F0, 8, 0),
            (0x7F8, 8, 0),
            (0x800, 8, 0),
            (0x808, 2, 0),
            (0x80C, 8, 0),
            (0x818, 8, 0),
            (0x820, 8, 0),
        ),
    )


def _decoded_master(context: ReplayTaskRebuildStorage, obj: int, slot: int) -> int:
    _write(context, slot, 8, _read(context, obj + 0x10, 8))
    _step(context, slot, "-", 0x6A586EB28AC201FC)
    _step(context, slot, "-", 0xCF19788B2554E70)
    return _read(context, slot, 8)


def _unit_post(
    context: ReplayTaskRebuildStorage,
    obj: int,
    slot: int,
    floating: ReplayUnitConstructionFloatingCalls | None,
) -> None:
    if not _read(context, obj + 0x200, 8):
        return
    master = _decoded_master(context, obj, slot)
    _write(context, slot, 8, _read(context, master + 0x38, 8))
    _step(context, slot, "-", 0x50A06BCECEBEF905)
    _step(context, slot, "+", 0x5B32AA7995D95916)
    if _read(context, slot, 8) & 0xFFFF != 13:
        return
    master = _decoded_master(context, obj, slot)
    target = _read(context, _read(context, master, 8) + 0xF0, 8)
    owner = _read(context, obj + 0x18, 8)
    array = _read(context, owner + 0x28, 8)
    current = _decoded_master(context, obj, slot)
    _write(context, slot, 8, _read(context, current + 0x18, 8))
    _step(context, slot, "^", 0x349E37847AD69F19)
    _step(context, slot, "-", 0x47E37DFF0616CE4F)
    index = _signed(_read(context, slot, 8) & 0xFFFF, 2)
    entry = _read(context, array + index * 8, 8)
    selected = _read(context, _read(context, entry, 8) + 0xE8, 8)
    if floating is None or floating.call is None:
        raise UnresolvedReplayTaskRebuild("selected constructor floating calls are unavailable")
    xmm0 = floating.call(selected, (entry,), None)
    if xmm0 is None:
        raise UnresolvedReplayTaskRebuild("selected constructor E8 XMM0 result is unavailable")
    _unsigned(xmm0, 16, "constructor callback XMM0")
    floating.call(target, (master,), xmm0)


def construct_replay_unit_object(
    context: ReplayTaskRebuildStorage,
    address: int,
    output: int,
    stream: int,
    opaque: int,
    read_flag: int,
    *,
    entry: int = _UNIT,
    calls: ReplayTaskRebuildCalls,
    atomics: ReplayUnitAIMapAtomics,
    bind_local: LocalBinding,
    scratch: ReplayUnitConstructionScratch,
    floating: ReplayUnitConstructionFloatingCalls | None = None,
) -> int:
    """One of six complete normal callers, with five actual scalar arguments.

    Parent fifth flags are exactly zero. Opaque R9 is forwarded without an
    owner/World interpretation. Output status is never manufactured; child
    effects precede current checks and survive later refusal. Unconditional
    Result forwarding is real even when logical records are empty. The optional
    reader's return identifies a Result, never this function's returned object.
    """
    _validate(context, calls, address, output, stream, opaque, read_flag)
    _unsigned(entry, 8, "constructor entry")
    if entry not in _ENTRIES:
        raise ValueError("one of the six original constructor entries is required")
    if not isinstance(atomics, ReplayUnitAIMapAtomics) or not callable(bind_local):
        raise ValueError("actual constructor atomic and coherent local bindings required")
    if not isinstance(scratch, ReplayUnitConstructionScratch):
        raise ValueError("explicit constructor local seeds required")
    if floating is not None and not isinstance(floating, ReplayUnitConstructionFloatingCalls):
        raise ValueError("explicit constructor floating-call provider required")
    name, flag, local_offset, reader, parent = _ENTRIES[entry]
    with _local(memoryview(bytearray(getattr(scratch, name))), bind_local) as frame:
        _write(context, frame + flag, 4, read_flag & _U32)
        local = (frame + local_offset) & _U64
        if parent is not None:
            if entry in (_COMBAT, _UNIT):
                _write(context, frame + (0x30 if entry == _COMBAT else 0x38), 8, address)
            _write(context, frame + 0x20, 4, 0)
            _call(calls, parent, (address, output, stream, opaque, 0))
        if entry == _BASE:
            _base(context, address, frame, calls)
        elif entry == _ANIMATED:
            _write(context, address, 8, 0x1432A6748)
        elif entry == _MOVING:
            _moving_initial(context, address)
        elif entry == _ACTION:
            _action(context, address, calls)
        elif entry == _COMBAT:
            _combat(context, address, calls)
        else:
            _unit(context, address, calls)
        cleanup = 0x1402BD7F0 if entry in (_BASE, _ANIMATED, _COMBAT) else 0x1402BD890
        if entry in (_ANIMATED, _MOVING, _UNIT):
            returned = _call(calls, 0x1409076B0, (local, output), width=8)
            _propagate(context, output, local, returned, cleanup, calls, atomics)
        if entry in (_ACTION, _COMBAT):
            _write(context, output + 40, 1, 1)
        if entry != _BASE and _read(context, output + 24, 8):
            return address
        if entry == _MOVING:
            _moving_success(context, address, calls)
        elif entry == _ACTION:
            _stores(context, address, ((0x438, 8, 0), (0x440, 4, 0)))
        elif entry == _UNIT:
            _stores(context, address, ((0x618, 8, 0), (0x620, 4, 0)))
        if _read(context, frame + flag, 4):
            returned = _call(calls, reader, (address, local, stream, opaque), width=8)
            _propagate(context, output, local, returned, cleanup, calls, atomics)
            if entry in (_MOVING, _UNIT) and _read(context, output + 24, 8):
                return address
        if entry == _MOVING:
            if _read(context, 0x14435505B, 1) >= 1:
                _write(context, frame + 0x20, 8, 0)
                logger = _read(context, 0x144355068, 8)
                _call(calls, 0x14101ADB0, (logger, 0x23, 0x1432B3158, 0, 0))
        elif entry == _UNIT:
            _unit_post(context, address, frame + 0x30, floating)
        return address


def bind_replay_unit_construction(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    *,
    atomics: ReplayUnitAIMapAtomics,
    bind_local: LocalBinding,
    scratch: ReplayUnitConstructionScratch,
    floating: ReplayUnitConstructionFloatingCalls | None = None,
) -> ReplayTaskRebuildCalls:
    """Bind only six five-argument callers; every other current target delegates.

    This binder deliberately supplies no allocator, map, Result, reader or
    virtual-success stand-ins. Those children must be composed with actual
    implementations or remain explicit reached frontiers.
    """
    _validate(context, calls)
    if not isinstance(atomics, ReplayUnitAIMapAtomics) or not callable(bind_local):
        raise ValueError("actual constructor atomic and local bindings required")
    if not isinstance(scratch, ReplayUnitConstructionScratch):
        raise ValueError("explicit constructor local seeds required")
    if floating is not None and not isinstance(floating, ReplayUnitConstructionFloatingCalls):
        raise ValueError("explicit constructor floating-call provider required")

    def dispatch(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        if target not in _ENTRIES:
            if calls.call is None:
                raise UnresolvedReplayTaskRebuild(f"reached{target:x} is unavailable")
            return calls.call(target, args, data)
        if len(args) != 5 or data is not None:
            raise ValueError("malformed five-argument object constructor call")
        return construct_replay_unit_object(
            context,
            *args,
            entry=target,
            calls=bound,
            atomics=atomics,
            bind_local=bind_local,
            scratch=scratch,
            floating=floating,
        )

    bound = ReplayTaskRebuildCalls(dispatch)
    return bound
