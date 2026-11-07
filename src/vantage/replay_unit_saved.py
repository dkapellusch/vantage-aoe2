"""Build54800 complete normal saved Unit caller1412d4f50.

Authority: unit-saved-reader-source-v1;36410B/6834 original instructions.
All historical gates and positive loops are represented. Actual Combat,
Input/Result, master/AI, vector/map/ownership and runtime children are required.
Returned-error metadata/TLS refuses at reached caller checks. No physical
stack/register/cookie/fault/EH/concurrency or full restored World is inferred.
"""

from __future__ import annotations

from dataclasses import dataclass

from .replay_binary32 import multiply_binary32
from .replay_task_group_storage import LocalBinding
from .replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
    _call,
    _cvtt,
    _read,
    _signed,
    _unsigned,
    _write,
)
from .replay_unit_ai_base import _validate
from .replay_unit_ai_construction import _local
from .replay_unit_ai_map import ReplayUnitAIMapAtomics, _release

_ENTRY = 0x1412D4F50
_VERSION = 0x1440A0D94
_U32, _U64 = (1 << 32) - 1, (1 << 64) - 1
_KEY1, _KEY2 = 0x6A586EB28AC201FC, 0x0CF19788B2554E70


@dataclass(frozen=True, slots=True)
class ReplayUnitSavedReaderScratch:
    """Explicit F18-byte working-RSP data seed, logical RBP=frame+100.

    Includes distinct Result48 lifetimes, legacy master Results, output-local90,
    scratch40, counts, map key/value, optional flag and partially assigned56B
    stinger descriptor. Unwritten bytes retain caller seeds. CookieF18, homes,
    physical nested-frame overlap and escaped pointers after return are excluded.
    """

    reader: bytes

    def __post_init__(self) -> None:
        if type(self.reader) is not bytes or len(self.reader) != 0xF18:
            raise ValueError("explicit F18-byte Unit reader data seed required")


def _admit(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    atomics: ReplayUnitAIMapAtomics,
    bind_local: LocalBinding,
    scratch: ReplayUnitSavedReaderScratch,
    mxcsr: int,
    *arguments: int,
) -> None:
    _validate(context, calls, *arguments)
    if not isinstance(atomics, ReplayUnitAIMapAtomics) or not callable(bind_local):
        raise ValueError("actual Unit reader atomic/local bindings required")
    if not isinstance(scratch, ReplayUnitSavedReaderScratch):
        raise ValueError("explicit Unit reader data seed required")
    _unsigned(mxcsr, 4, "Unit reader MXCSR")
    if mxcsr & ~0x3F != 0x1F80:
        raise ValueError("Unit reader requires masked nearest MXCSR, DAZ/FTZ off")


def _zero(context: ReplayTaskRebuildStorage, result: int) -> None:
    for offset in (0, 16, 32):
        _write(context, result + offset, 16, 0)


def _status(context: ReplayTaskRebuildStorage, result: int) -> None:
    if _read(context, result + 24, 8):
        raise UnresolvedReplayTaskRebuild(
            "Unit saved reader reached returned-error metadata/TLS frontier"
        )


def _version(context: ReplayTaskRebuildStorage) -> int:
    return _signed(_read(context, _VERSION, 4), 4)


def read_replay_saved_unit(
    context: ReplayTaskRebuildStorage,
    address: int,
    output: int,
    stream: int,
    opaque: int,
    *,
    calls: ReplayTaskRebuildCalls,
    atomics: ReplayUnitAIMapAtomics,
    bind_local: LocalBinding,
    scratch: ReplayUnitSavedReaderScratch,
    mxcsr: int,
) -> int:
    """Complete normal caller with raw integer and low-binary32 word semantics.

    Masked nearest rounding/DAZ-FTZ-off is explicit; sticky flags and upper SIMD
    lanes are excluded. Real child failures preserve earlier stores. Flattened
    legacy constructor stack arguments carry source-written values, without a
    physical native stack-argument alias claim. Saved zero counts never clear
    existing containers. No unknown child receives a successful default.
    """
    _admit(context, calls, atomics, bind_local, scratch, mxcsr, address, output, stream, opaque)
    with _local(memoryview(bytearray(scratch.reader)), bind_local) as frame:
        rbp = (frame + 0x100) & _U64

        def finish(result: int, mode: str = "finalize") -> None:
            _status(context, result)
            _write(context, result + 40, 1, 1)
            if mode == "finalize":
                _call(calls, 0x140900620, (result,))
            elif mode == "pair":
                _call(calls, 0x1408EE150, (result + 24,))
                _call(calls, 0x1402BD890, (result,))
            else:
                control = _read(context, result + 32, 8)
                if control:
                    _release(context, control, calls, atomics)
                _call(calls, 0x1402BD890, (result,))

        def raw(destination: int, width: int, offset: int, mode: str = "finalize") -> None:
            result = (rbp + offset) & _U64
            _zero(context, result)
            target = _read(context, _read(context, stream, 8) + 24, 8)
            _call(calls, target, (stream, result, destination & _U64, width))
            finish(result, mode)

        def fields(rows: tuple[tuple[int, int, int], ...]) -> None:
            for offset, width, result in rows:
                raw(address + offset, width, result)

        def local_arithmetic(operation: str, value: int) -> None:
            current = _read(context, frame + 0x40, 8)
            result = (
                current ^ value
                if operation == "xor"
                else (current + value if operation == "add" else current - value)
            )
            _write(context, frame + 0x40, 8, result)

        _write(context, rbp - 0x70, 8, output)
        _write(context, address + 0x1F0, 8, 0)
        _write(context, address + 0x694, 1, 0)
        _zero(context, rbp + 0x90)
        _call(calls, 0x1411587A0, (address, rbp + 0x90, stream, opaque))
        finish(rbp + 0x90, "ordinary")
        _write(context, address + 15, 1, 70)
        _write(context, frame + 0x40, 8, _read(context, address + 16, 8))
        local_arithmetic("sub", _KEY1)
        local_arithmetic("sub", _KEY2)
        master = _read(context, frame + 0x40, 8)
        _write(context, address + 0x688, 4, _read(context, master + 0x360, 4))
        if _version(context) >= 0x911EB:
            raw(address + 0x68C, 1, 0xC0, "ordinary")
        else:
            _write(context, address + 0x68C, 1, 0)
        if _version(context) >= 0x94000:
            raw(address + 0x68D, 1, 0x9C8)
        else:
            _write(context, address + 0x68D, 1, 0)

        if _version(context) < 0xCCF5C:
            raw(rbp + 1, 1, 0xD88)
            if _read(context, rbp + 1, 1):
                raw(rbp + 2, 1, 0xDB8)
                tag = _read(context, rbp + 2, 1)
                if tag in (70, 80):
                    result_offset, aggregate, size, child = (
                        (0x28, 0x278, 0x3E8, 0x14130AF90)
                        if tag == 70
                        else (0x58, 0x2A8, 0x4A0, 0x1412E1CA0)
                    )
                    result = (rbp + result_offset) & _U64
                    # Exact initialization order, including redundant tail stores.
                    _write(context, result + 32, 16, 0)
                    _write(context, result, 16, 0)
                    _write(context, result + 16, 16, 0)
                    _write(context, result + 32, 8, 0)
                    _write(context, result + 40, 1, 0)
                    allocation = _call(calls, 0x142D6BA78, (size,), width=8)
                    _write(context, frame + 0x40, 8, allocation)
                    answer = 0
                    if allocation:
                        _call(calls, 0x142D6E3B7, (allocation, 0, size))
                        owner = _read(context, address + 24, 8)
                        world = _read(context, owner + 8, 8)
                        _write(context, frame + 0x28, 4, 1)
                        _write(context, frame + 0x20, 8, world + 0xA0)
                        answer = _call(
                            calls,
                            child,
                            (
                                allocation,
                                result,
                                stream,
                                (world + 0xC0) & _U64,
                                (world + 0xA0) & _U64,
                                1,
                            ),
                            width=8,
                        )
                    _write(context, frame + 0x40, 8, answer)
                    local_arithmetic("add", _KEY2)
                    local_arithmetic("add", _KEY1)
                    _write(context, address + 16, 8, _read(context, frame + 0x40, 8))
                    _call(calls, 0x1412429D0, (address + 0x200, address))
                    _zero(context, rbp + aggregate)
                    _call(calls, 0x1409076B0, (rbp + aggregate, result))
                    finish(rbp + aggregate)
                    control = _read(context, result + 32, 8)
                    if control:
                        _call(calls, 0x1402AAA80, (control,))
                    _call(calls, 0x1402BD890, (result,))

        if _version(context) >= 0x9428F:
            for index in range(6):
                raw(address + 0x618 + index * 2, 2, 0xF0, "ordinary")
        elif _version(context) >= 0x90F5C:
            for index in range(5):
                raw(address + 0x618 + index * 2, 2, 0x248, "pair")
            _write(context, address + 0x622, 2, 0)
        else:
            _write(context, address + 0x618, 8, 0)
            _write(context, address + 0x620, 4, 0)
        if _version(context) >= 0x928F5:
            raw(address + 0x624, 2, 0x120, "ordinary")
        else:
            owner = _read(context, address + 24, 8)
            owner_state = _read(context, owner + 0x98, 8)
            _write(context, frame + 0x40, 8, _read(context, owner_state + 0x208, 8))
            for operation, key in (
                ("xor", 0x6AE24D3352F04511),
                ("xor", 0xC22D6B496D833977),
                ("sub", 0x042AC42976FCCEF5),
                ("xor", 0xA9834B738A7DD167),
            ):
                local_arithmetic(operation, key)
            _write(context, frame + 0x40, 8, _read(context, frame + 0x40, 8))
            current = _read(context, frame + 0x40, 4)
            scale = _read(context, 0x1436A02F8, 4)
            _write(context, address + 0x624, 2, _cvtt(multiply_binary32(current, scale)))
        for gate, offset, width, result in (
            (0x99C28, 0x628, 4, 0x150),
            (0x9A666, 0x690, 4, 0x180),
            (0xB8F5C, 0x630, 1, 0x1B0),
        ):
            if _version(context) >= gate:
                raw(address + offset, width, result, "ordinary")
            else:
                _write(context, address + offset, width, 0)

        raw(rbp + 0x18, 4, 0x1E0, "ordinary")
        tag = _signed(_read(context, rbp + 0x18, 4), 4)
        if tag > 1:
            _call(calls, 0x1412CA880, (address, tag))
            result = (rbp + 0x2D8) & _U64
        elif tag == 1:
            _call(calls, 0x1412CADB0, (address,))
            if _read(context, address + 0x1F0, 8) == 0:
                allocation = _call(calls, 0x142D6BA78, (0x1F8,), width=8)
                _write(context, frame + 0x40, 8, allocation)
                answer = 0
                if allocation:
                    _call(calls, 0x142D6E3B7, (allocation, 0, 0x1F8))
                    answer = _call(calls, 0x140CEF230, (allocation, address, 10), width=8)
                _write(context, address + 0x1F0, 8, answer)
            result = (rbp + 0x308) & _U64
        else:
            result = 0
        if result:
            _zero(context, result)
            ai = _read(context, address + 0x1F0, 8)
            target = _read(context, _read(context, ai, 8) + 16, 8)
            _call(calls, target, (ai, result, stream))
            finish(result)

        version = _version(context)
        if version >= 0x323333:
            fields(
                (
                    (0x664, 1, 0x338),
                    (0x634, 4, 0x368),
                    (0x644, 4, 0x398),
                    (0x648, 4, 0x3C8),
                    (0x640, 4, 0x3F8),
                    (0x638, 4, 0x428),
                    (0x63C, 4, 0x458),
                    (0x64C, 4, 0x488),
                    (0x65C, 4, 0x4B8),
                    (0x660, 4, 0x4E8),
                    (0x658, 4, 0x518),
                    (0x650, 4, 0x548),
                    (0x654, 4, 0x578),
                )
            )
        else:
            if version >= 0xA4CCC:
                fields(((0x664, 1, 0x5A8), (0x634, 4, 0x5D8), (0x644, 4, 0x608), (0x648, 4, 0x638)))
            else:
                _write(context, address + 0x664, 1, 0)
                _write(context, address + 0x634, 4, _U32)
                _write(context, address + 0x644, 4, 0xBF800000)
                _write(context, address + 0x648, 4, 0xBF800000)
            if _version(context) >= 0xBB5C2:
                fields(((0x640, 4, 0x668), (0x638, 4, 0x698)))
            else:
                _write(context, address + 0x640, 4, _U32)
                _write(context, address + 0x638, 4, _U32)
            if _version(context) >= 0xBBD70:
                raw(address + 0x63C, 4, 0x6C8)
            else:
                _write(context, address + 0x63C, 4, _U32)
        for gate, offset, width, result in (
            (0xA6B85, 0x698, 4, 0x6F8),
            (0xA75C2, 0x670, 1, 0x728),
            (0xBB0A3, 0x671, 1, 0x758),
            (0x14028F, 0x668, 4, 0x788),
        ):
            if _version(context) >= gate:
                raw(address + offset, width, result)
            else:
                _write(context, address + offset, width, 0)
        if _version(context) >= 0x190000:
            fields(((0x66C, 2, 0x7B8), (0x66E, 2, 0x7E8)))
        else:
            _write(context, address + 0x66C, 4, 0)
        if _version(context) >= 0x1A051E:
            raw(address + 0x62C, 4, 0x818)
        else:
            _write(context, address + 0x62C, 4, 0)
        if (_read(context, _VERSION, 4) + 0xFFE5F334) & _U32 <= 0x2147:
            raw(rbp + 8, 1, 0x848)
        version = _version(context)
        if 0x281999 <= version < 0x320000:
            fields(((0x6AC, 4, 0x878), (0x6B0, 4, 0x8A8), (0x6DC, 4, 0x8D8)))
            raw(rbp + 0x20, 8, 0x908)
            counter = 0
            if _read(context, rbp + 0x20, 8):
                while True:
                    raw(rbp + 0x88, 4, 0x938)
                    counter = (counter + 1) & _U64
                    if counter >= _read(context, rbp + 0x20, 8):
                        break
            raw(address + 0x6B4, 4, 0x968)
        elif version >= 0x320000 or _version(context) >= 0x320000:
            fields(
                (
                    (0x6AC, 4, 0x998),
                    (0x6B0, 4, 0xBD8),
                    (0x6DC, 4, 0x9F8),
                    (0x6B4, 4, 0xA28),
                    (0x6B8, 4, 0xA58),
                    (0x6BC, 4, 0xA88),
                )
            )

        if _version(context) >= 0x3D051E:
            fields(((0x7C0, 4, 0xAB8), (0x7C4, 4, 0xAE8), (0x7C8, 4, 0xB18)))
            _write(context, rbp + 0xC, 4, 0)
            raw(rbp + 0xC, 4, 0xB48)
            counter = 0
            if _signed(_read(context, rbp + 0xC, 4), 4) > 0:
                operand = _read(context, 0x1436A0A30, 16)
                while True:
                    for offset, width, value in (
                        (0x210, 4, 0),
                        (0x214, 4, 0xBF800000),
                        (0x218, 16, operand),
                        (0x228, 4, 0),
                        (0x238, 8, 0),
                        (0x240, 8, 0),
                    ):
                        _write(context, rbp + offset, width, value)
                    _call(calls, 0x1411281D0, (rbp + 0x210, rbp - 0x60, stream))
                    _call(calls, 0x140900620, (rbp - 0x60,))
                    end = _read(context, address + 0x7F8, 8)
                    if end != _read(context, address + 0x800, 8):
                        for offset, width in ((0, 16), (16, 16), (32, 16), (48, 8)):
                            _write(
                                context,
                                end + offset,
                                width,
                                _read(context, rbp + 0x210 + offset, width),
                            )
                        _write(context, address + 0x7F8, 8, _read(context, address + 0x7F8, 8) + 56)
                    else:
                        _call(calls, 0x1412A38C0, (address + 0x7F0, end, rbp + 0x210))
                    counter = (counter + 1) & _U32
                    if _signed(counter, 4) >= _signed(_read(context, rbp + 0xC, 4), 4):
                        break
        if _version(context) >= 0x3D1999:
            fields(
                (
                    (0x6C0, 4, 0xB78),
                    (0x6C4, 4, 0xBA8),
                    (0x6C8, 4, 0xDE8),
                    (0x6D0, 4, 0xC08),
                    (0x6D4, 4, 0xC38),
                )
            )
        if _version(context) >= 0x3D3333:
            _write(context, rbp + 0x10, 4, 0)
            raw(rbp + 0x10, 4, 0xC68)
            counter = 0
            if _read(context, rbp + 0x10, 4):
                while True:
                    _write(context, rbp + 4, 2, 0)
                    _write(context, rbp + 0x14, 4, 0)
                    raw(rbp + 4, 2, 0xCC8)
                    raw(rbp + 0x14, 4, 0xC98)
                    _call(calls, 0x1412A48D0, (address + 0x768, frame + 0x40, rbp + 4, rbp + 0x14))
                    counter = (counter + 1) & _U32
                    if counter >= _read(context, rbp + 0x10, 4):
                        break
        if _version(context) >= 0x3D6666:
            raw(address + 0x6D8, 4, 0xCF8)
        if _version(context) >= 0x404CCD:
            raw(address + 0x808, 1, 0xD28)
        if _version(context) >= 0x43B333:
            _write(context, rbp, 1, 0)
            raw(rbp, 1, 0xD58)
            if _read(context, rbp, 1):
                allocation = _call(calls, 0x142D6BA78, (8,), width=8)
                _write(context, rbp - 0x70, 8, allocation)
                if allocation:
                    _write(context, allocation, 2, 0xFFFF)
                    _write(context, allocation + 4, 4, 0)
                _write(context, rbp - 0x70, 8, allocation)
                _call(calls, 0x1412A3520, (address + 0x818, rbp - 0x70))
                leftover = _read(context, rbp - 0x70, 8)
                if leftover:
                    _call(calls, 0x142D6BAB4, (leftover, 8))
                timer = _read(context, address + 0x818, 8)
                _call(calls, 0x1410B1A40, (timer, rbp - 0x30, stream))
                _call(calls, 0x140900620, (rbp - 0x30,))
        for offset in (0, 8, 16, 24, 32):
            _write(context, output + offset, 8, 0)
        _write(context, output + 40, 1, 0)
        return output


def bind_replay_unit_saved(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    *,
    atomics: ReplayUnitAIMapAtomics,
    bind_local: LocalBinding,
    scratch: ReplayUnitSavedReaderScratch,
    mxcsr: int,
) -> ReplayTaskRebuildCalls:
    """Bind only1412d4f50 with four scalar arguments; unknown work is mandatory."""
    _admit(context, calls, atomics, bind_local, scratch, mxcsr)

    def dispatch(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        if target != _ENTRY:
            if calls.call is None:
                raise UnresolvedReplayTaskRebuild(f"reached{target:x} is unavailable")
            return calls.call(target, args, data)
        if len(args) != 4 or data is not None:
            raise ValueError("malformed Unit saved-reader call")
        return read_replay_saved_unit(
            context,
            *args,
            calls=bound,
            atomics=atomics,
            bind_local=bind_local,
            scratch=scratch,
            mxcsr=mxcsr,
        )

    bound = ReplayTaskRebuildCalls(dispatch)
    return bound
