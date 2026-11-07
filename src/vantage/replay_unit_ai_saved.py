"""Normal build54800 common/AI15 saved-reader callers over current storage.

Retained140d267d0/140cf9dc0 C/ASM and unit-ai15-zero-groups-source-review-v1
establish the read/store/call phases. All positive groups, version gates and
normal descendants remain actual required effects. Returned-error logging,
security cookies, physical stack/register identity, faults and EH are excluded.
This does not infer native IStream identity or a restored World.
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
    _write,
)
from .replay_unit_ai_base import _validate
from .replay_unit_ai_construction import _local
from .replay_unit_ai_map import ReplayUnitAIMapAtomics, _release

_U64 = (1 << 64) - 1
_U32 = (1 << 32) - 1
_VERSION = 0x1440A0D94
_PREFIX = (
    (0x10, 0x90),
    (0x3C, 0xC0),
    (0x40, 0xF0),
    (0x44, 0x120),
    (0x48, 0x150),
    (0x4C, 0x180),
    (0x50, 0x1B0),
    (0x54, 0x1E0),
    (0x58, 0x210),
    (0x5C, 0x240),
    (0x68, 0x270),
    (0x64, 0x840),
    (0x6C, 0xBD0),
    (0x70, 0x2D0),
    (0x164, 0x300),
    (0x168, 0x330),
    (0x170, 0x360),
    (0x16C, 0x390),
    (0x174, 0x3C0),
    (0x178, 0x3F0),
    (0x17C, 0x420),
)


@dataclass(frozen=True, slots=True)
class ReplaySavedAIScratch:
    """Explicit seeds for local slots, including native unwritten padding.

    Slot offsets preserve common/derived local aliases and reuse. Saved argument
    metadata, cookie/register saves and an executable native stack are not
    modeled. Providers must keep each coherent writable view live until exit.
    """

    common: bytes
    derived: bytes

    def __post_init__(self) -> None:
        if any(
            type(value) is not bytes or len(value) != size
            for value, size in ((self.common, 0xD70), (self.derived, 0xD0))
        ):
            raise ValueError("explicit0xd70/0xd0-byte saved AI local seeds required")


def _zero(context: ReplayTaskRebuildStorage, result: int) -> None:
    for offset in (0, 16, 32):
        _write(context, result + offset, 16, 0)


def _output(context: ReplayTaskRebuildStorage, output: int) -> int:
    for offset in (0, 8, 16, 24, 32):
        _write(context, output + offset, 8, 0)
    _write(context, output + 40, 1, 0)
    return output


def _release_result(
    context: ReplayTaskRebuildStorage,
    result: int,
    cleanup: int,
    calls: ReplayTaskRebuildCalls,
    atomics: ReplayUnitAIMapAtomics,
) -> None:
    control = _read(context, result + 32, 8)
    if control:
        _release(context, control, calls, atomics)
    _call(calls, cleanup, (result,))


def _finish(
    context: ReplayTaskRebuildStorage,
    result: int,
    calls: ReplayTaskRebuildCalls,
    atomics: ReplayUnitAIMapAtomics,
    cleanup: int = 0x140900620,
) -> None:
    if _read(context, result + 24, 8):
        raise UnresolvedReplayTaskRebuild("saved AI reached returned-error/logging frontier")
    _write(context, result + 40, 1, 1)
    if cleanup == 0x140900620:
        _call(calls, cleanup, (result,))
    elif cleanup == 0x1408EE150:
        _call(calls, cleanup, ((result + 24) & _U64,))
        _call(calls, 0x1402BD890, (result,))
    else:
        _release_result(context, result, cleanup, calls, atomics)


def _request(
    context: ReplayTaskRebuildStorage,
    stream: int,
    result: int,
    destination: int,
    count: int,
    calls: ReplayTaskRebuildCalls,
    atomics: ReplayUnitAIMapAtomics,
    cleanup: int = 0x140900620,
) -> None:
    _zero(context, result)
    target = _read(context, _read(context, stream, 8) + 24, 8)
    _call(calls, target, (stream, result & _U64, destination & _U64, count))
    _finish(context, result, calls, atomics, cleanup)


def _record(
    context: ReplayTaskRebuildStorage,
    destination: int,
    first: int,
    floats: int,
) -> None:
    for offset, width, value in (
        (0, 16, first),
        (16, 4, _U32),
        (20, 16, floats),
        (36, 4, 0xBF800000),
        (40, 4, 0xBF800000),
        (44, 1, 0),
        (48, 4, _U32),
    ):
        _write(context, destination + offset, width, value)


def _admit(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    atomics: ReplayUnitAIMapAtomics,
    bind_local: LocalBinding,
    scratch: ReplaySavedAIScratch,
    *arguments: int,
) -> None:
    _validate(context, calls, *arguments)
    if not isinstance(atomics, ReplayUnitAIMapAtomics) or not callable(bind_local):
        raise ValueError("actual saved AI atomic/local effects required")
    if not isinstance(scratch, ReplaySavedAIScratch):
        raise ValueError("explicit saved AI local seeds required")


def read_replay_saved_unit_ai_common(
    context: ReplayTaskRebuildStorage,
    address: int,
    output: int,
    stream: int,
    *,
    calls: ReplayTaskRebuildCalls,
    atomics: ReplayUnitAIMapAtomics,
    bind_local: LocalBinding,
    scratch: ReplaySavedAIScratch,
) -> int:
    """Normal140d267d0 phases, with required positive-group and path effects.

    All local slots remain mapped through return and source reuse is preserved.
    Counts are current signedDWORDs; no negative-count validation or vector
    replacement is invented. Earlier I/O/callee/stores survive failures. Native
    logging/error-result construction stops at its reached frontier.
    """
    _admit(context, calls, atomics, bind_local, scratch, address, output, stream)
    with _local(memoryview(bytearray(scratch.common)), bind_local) as frame:
        bp = frame + 0x100
        _write(context, bp + 0x70, 8, output)

        def read(result: int, destination: int, width: int = 4, cleanup: int = 0x140900620) -> None:
            _request(
                context, stream, (bp + result) & _U64, destination, width, calls, atomics, cleanup
            )

        def version() -> int:
            return _signed(_read(context, _VERSION, 4), 4)

        for i, (offset, result) in enumerate(_PREFIX):
            read(result, address + offset, cleanup=0x1402BD890 if i < 10 else 0x140900620)
        if (_read(context, _VERSION, 4) - 0x1407AE) & _U32 <= 0x62B84:
            read(0x450, bp + 0x60)
            read(0x480, bp + 0x60)
        read(0x4B0, address + 0x60)
        read(0x4E0, address + 0x194)
        read(0x510, address + 0x184, 16)
        read(0x540, bp + 12)
        index = 0
        if _signed(_read(context, bp + 12, 4), 4) > 0:
            floats, first = _read(context, 0x14324ABA0, 16), _read(context, 0x14324B1D0, 16)
            while True:
                descriptor = bp + 0x28
                _record(context, descriptor, first, floats)
                current_version = version()
                if current_version >= 0x324CCC:
                    read(0x570, descriptor, 52)
                    tail = _read(context, descriptor + 48, 4)
                else:
                    if current_version >= 0xC9EB8:
                        read(0x5A0, descriptor, 48)
                    else:
                        read(0x5D0, descriptor, 36)
                        _write(context, descriptor + 36, 4, _read(context, descriptor + 20, 4))
                        _write(context, descriptor + 40, 4, _read(context, descriptor + 24, 4))
                        _write(context, descriptor + 44, 1, 1)
                    tail = _U32
                    _write(context, descriptor + 48, 4, tail)
                # Source builds stack arguments in reverse order, retaining
                # tail in ECX before those later current descriptor reads.
                flag = _read(context, descriptor + 44, 1)
                y, x = _read(context, descriptor + 40, 4), _read(context, descriptor + 36, 4)
                identifier = _read(context, descriptor + 8, 4)
                f32 = [_read(context, descriptor + offset, 4) for offset in (32, 28, 24, 20)]
                kind = _read(context, descriptor + 16, 4)
                a, b, c = (_read(context, descriptor + offset, 4) for offset in (12, 4, 0))
                _call(
                    calls,
                    0x140D1ADF0,
                    (address, c, b, a, tail, kind, *reversed(f32), 0, identifier, x, y, flag),
                )
                index = index + 1 & _U32
                if _signed(index, 4) >= _signed(_read(context, bp + 12, 4), 4):
                    break
        read(0x600, bp + 16)
        index = 0
        while _signed(index, 4) < _signed(_read(context, bp + 16, 4), 4):
            read(0x630, bp + 0x78, 24)
            words = [_read(context, bp + 0x78 + offset, 4) for offset in (20, 16, 12, 8, 4, 0)]
            _call(calls, 0x140D1AC10, (address, *reversed(words)))
            index = index + 1 & _U32
        read(0x660, bp + 20)
        index = 0
        while _signed(index, 4) < _signed(_read(context, bp + 20, 4), 4):
            read(0x2A0, bp + 0x64, cleanup=0x1408EE150)
            _call(calls, 0x140C27270, ((address + 0xC8) & _U64, _read(context, bp + 0x64, 4)))
            index = index + 1 & _U32
        for result, offset, width in (
            (0x690, 0x1B0, 1),
            (0x6C0, 0x1B1, 1),
            (0x6F0, 0x1B4, 4),
            (0x720, 0x1B8, 4),
            (0x750, 0x1BC, 4),
            (0x780, 0x1C0, 1),
            (0x7B0, 0x1C4, 4),
        ):
            read(result, address + offset, width)
        _write(context, bp + 24, 4, 0)
        read(0x7E0, bp + 24)
        if _read(context, bp + 24, 4) == 1:
            allocation = _call(calls, 0x142D6BA78, (0x548,), width=8)
            path = 0
            if allocation:
                _call(calls, 0x142D6E3B7, (allocation, 0, 0x548))
                path = _call(calls, 0x14106A110, (allocation, _U32), width=8)
            _write(context, address + 0x1C8, 8, path)
            if path:
                _zero(context, bp + 0x810)
                current_path = _read(context, address + 0x1C8, 8)
                _call(calls, 0x14106E770, (current_path, (bp + 0x810) & _U64, stream))
                _finish(context, bp + 0x810, calls, atomics)
        read(0xA20, address + 0x1D0)
        _call(calls, 0x140D36FE0, (address,))
        held_version = version()
        if held_version >= 0xA7AE1:
            read(0x870, bp + 28)
            index = 0
            while _signed(index, 4) < _signed(_read(context, bp + 28, 4), 4):
                node = _call(calls, 0x142D6BA78, (64,), width=8)
                if node:
                    for offset in (0, 16, 32, 48):
                        _write(context, node + offset, 16, 0)
                    for offset, width, value in (
                        (0, 8, _U64),
                        (8, 8, 0),
                        (16, 8, 0),
                        (24, 8, _U64),
                        (32, 8, 0),
                        (40, 4, 0),
                        (56, 8, node),
                        (48, 8, node),
                    ):
                        _write(context, node + offset, width, value)
                    for result, offset, width in (
                        (0x9C0, 0, 4),
                        (0x990, 4, 4),
                        (0x960, 8, 4),
                        (0x930, 12, 12),
                        (0x900, 24, 4),
                    ):
                        read(result, node + offset, width)
                    if version() >= 0xA8000:
                        read(0x8A0, node + 28)
                    else:
                        _write(context, node + 28, 4, _U32)
                    read(0x8D0, node + 32, 12)
                    _write(context, node + 48, 8, address + 0x78)
                    tail_node = _read(context, address + 0xB0, 8)
                    _write(context, node + 56, 8, tail_node)
                    _write(context, tail_node + 48, 8, node)
                    _write(context, address + 0xB0, 8, node)
                    _write(context, address + 0xB8, 4, _read(context, address + 0xB8, 4) + 1)
                index = index + 1 & _U32
            held_version = version()
        if held_version >= 0xA8000:
            read(0x9F0, address + 0xBC)
        else:
            _write(context, address + 0xBC, 4, 0)
        if version() >= 0xB0A3D:
            read(0xC00, address + 0x1D4)
        else:
            _call(calls, 0x140D3ECE0, (address, 1000, 0x14324B4F0, 0x3B7))
        if version() >= 0xB0CCC:
            read(0xA50, bp + 32)
            index = 0
            while _signed(index, 4) < _signed(_read(context, bp + 32, 4), 4):
                read(0xAB0, bp + 0x70)
                read(0xA80, bp + 0x68)
                second, first_word = _read(context, bp + 0x68, 4), _read(context, bp + 0x70, 4)
                _call(calls, 0x140D1AAC0, (address, first_word, second))
                index = index + 1 & _U32
        for threshold, result, offset, width, fallback in (
            (0xB23D7, 0xAE0, 0x1D8, 4, _U32),
            (0xB70A3, 0xB10, 0x1DC, 1, 0),
            (0xBF0A3, 0xB40, 0x180, 4, 0),
        ):
            if version() >= threshold:
                read(result, address + offset, width)
            else:
                _write(context, address + offset, width, fallback)
        held_version = version()
        if held_version >= 0x19170A:
            read(0xB70, address + 0x1DE, 1)
            held_version = version()
        if held_version >= 0x430000:
            _write(context, bp + 8, 1, 0)
            _zero(context, bp + 0xBA0)
            _call(
                calls,
                0x140D07EE0,
                ((bp + 0xBA0) & _U64, 0x14324B4F0, 0x3E5, 0x14324B588, stream, (bp + 8) & _U64),
            )
            _finish(context, bp + 0xBA0, calls, atomics)
            if _read(context, bp + 8, 1):
                position = _read(context, address + 0xC0, 8)
                _call(calls, 0x140C29890, (position, (bp - 0x28) & _U64, stream))
                _call(calls, 0x140900620, ((bp - 0x28) & _U64,))
        return _output(context, output)


def read_replay_saved_unit_ai15(
    context: ReplayTaskRebuildStorage,
    address: int,
    output: int,
    stream: int,
    *,
    calls: ReplayTaskRebuildCalls,
    atomics: ReplayUnitAIMapAtomics,
    bind_local: LocalBinding,
    scratch: ReplaySavedAIScratch,
) -> int:
    """Normal140cf9dc0: common call, unconditional cleanup, current derived tail.

    Common Result status is not checked before continuation. Count lowDWORD is
    reset without clearing the saved output pointer's upperDWORD in its slot.
    Derived record append preserves all52bytes and increments CURRENT end.
    """
    _admit(context, calls, atomics, bind_local, scratch, address, output, stream)
    with _local(memoryview(bytearray(scratch.derived)), bind_local) as frame:
        result, descriptor, count = frame + 0x30, frame + 0x60, frame + 0x28
        _write(context, count, 8, output)
        _call(calls, 0x140D267D0, (address, result, stream))
        _release_result(context, result, 0x1402BD7F0, calls, atomics)
        if _signed(_read(context, _VERSION, 4), 4) >= 0x3E6666:
            _write(context, count, 4, 0)
            _request(context, stream, result, count, 4, calls, atomics, 0x1402BD7F0)
            index = 0
            if _signed(_read(context, count, 4), 4) > 0:
                floats = _read(context, 0x14324ABA0, 16)
                first = _read(context, 0x14324B1D0, 16)
                while True:
                    _record(context, descriptor, first, floats)
                    _request(context, stream, result, descriptor, 52, calls, atomics, 0x1402BD7F0)
                    vector = address + 0x1F8 & _U64
                    end = _read(context, vector + 8, 8)
                    if end == _read(context, vector + 16, 8):
                        _call(calls, 0x140CEDD60, (vector, end, descriptor))
                    else:
                        for offset, width in ((0, 16), (16, 16), (32, 16), (48, 4)):
                            _write(
                                context,
                                end + offset,
                                width,
                                _read(context, descriptor + offset, width),
                            )
                        _write(context, vector + 8, 8, _read(context, vector + 8, 8) + 52)
                    index = index + 1 & _U32
                    if _signed(index, 4) >= _signed(_read(context, count, 4), 4):
                        break
        return _output(context, output)


def bind_replay_saved_unit_ai(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    *,
    atomics: ReplayUnitAIMapAtomics,
    bind_local: LocalBinding,
    scratch: ReplaySavedAIScratch,
    imports: ReplayTaskRebuildCalls | None = None,
) -> ReplayTaskRebuildCalls:
    """Bind normal common/AI15 callers; unknown descendants remain mandatory."""
    _admit(context, calls, atomics, bind_local, scratch)
    terminal = calls if imports is None else imports
    _validate(context, terminal)

    def dispatch(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        arities = {0x140D267D0: 3, 0x140CF9DC0: 3, 0x142D6E3B7: 3}
        if target not in arities:
            if calls.call is None:
                raise UnresolvedReplayTaskRebuild(f"reached{target:x} is unavailable")
            return calls.call(target, args, data)
        if len(args) != arities[target] or data is not None:
            raise ValueError("malformed saved AI reader call")
        _validate(context, calls, *args)
        if target == 0x142D6E3B7:
            selected = _read(context, 0x143199938, 8)
            if terminal.call is None:
                raise UnresolvedReplayTaskRebuild(f"reached{selected:x} is unavailable")
            return terminal.call(selected, args, None)
        body = (
            read_replay_saved_unit_ai_common
            if target == 0x140D267D0
            else read_replay_saved_unit_ai15
        )
        return body(
            context, *args, calls=bound, atomics=atomics, bind_local=bind_local, scratch=scratch
        )

    bound = ReplayTaskRebuildCalls(dispatch)
    return bound
