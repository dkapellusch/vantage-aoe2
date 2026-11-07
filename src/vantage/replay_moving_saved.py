"""Build54800 complete normal Moving saved reader and its distinct reset.

Authority: moving-saved-reader-source-review-v1, full22904B14121f910 and
289B141218e80. Reached parent, current virtuals, stream/Result, path/controller,
point allocation and logging children require actual effects. Error decoration
and TLS initialization refuse before their unported effects. Native stack,
register saves, cookie/fault/EH/concurrency parity and full restore are outside
this logical normal-call profile. No skipped field receives a guessed default.
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
_READER, _RESET = 0x14121F910, 0x141218E80
_VERSION = 0x1440A0D94


@dataclass(frozen=True, slots=True)
class ReplayMovingSavedScratch:
    """Explicit D8-byte logical frame through the last DWORD count at D4.

    Offsets use the reader's post-prologue RSP; logical RBP is RSP+100. The
    Result at78, tuple atB8 and aliased B0/C8 slots stay coherent until return
    or failure. Unwritten bytes retain their seeds. Native cookie/FP saves,
    parameter homes, saved registers, physical nested-stack overlap and escaped
    local use after return are not represented.
    """

    reader: bytes

    def __post_init__(self) -> None:
        if type(self.reader) is not bytes or len(self.reader) != 0xD8:
            raise ValueError("explicit D8-byte Moving reader local seed required")


def _fields(
    context: ReplayTaskRebuildStorage,
    obj: int,
    fields: tuple[tuple[int, int, int], ...],
) -> None:
    for offset, width, value in fields:
        _write(context, obj + offset, width, value)


def reset_replay_saved_moving(
    context: ReplayTaskRebuildStorage,
    address: int,
    *,
    calls: ReplayTaskRebuildCalls,
) -> None:
    """Full289B141218e80, not the constructor's different inline reset.

    Hold the vptr before stores, but read that held table's current490 slot at
    the actual call. Hold3b0 before408/3b9/410 resets. Destruction/free failures
    keep preceding effects; slots clear only after their real children return.
    """
    _validate(context, calls, address)
    vptr = _read(context, address, 8)
    _fields(context, address, ((0x370, 8, 0), (0x378, 8, 0), (0x380, 8, 0), (0x391, 2, 0)))
    _call(calls, _read(context, vptr + 0x490, 8), (address,))
    _fields(
        context,
        address,
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
        pointer = _read(context, address + offset, 8)
        if pointer:
            _call(calls, 0x14106A330, (pointer,))
            _call(calls, 0x142D6BAB4, (pointer, 72))
            _write(context, address + offset, 8, 0)
    pointer = _read(context, address + 0x400, 8)
    if pointer:
        _call(calls, 0x142D6BAB4, (pointer, 24))
        _write(context, address + 0x400, 8, 0)
    pointer = _read(context, address + 0x3B0, 8)
    _fields(context, address, ((0x408, 8, 0), (0x3B9, 1, 0), (0x410, 4, 0)))
    if pointer:
        _call(calls, 0x140B2CFC0, (pointer,))
        _call(calls, 0x142D6BAB4, (pointer, 8))
        _write(context, address + 0x3B0, 8, 0)


def _zero(context: ReplayTaskRebuildStorage, result: int) -> None:
    for offset in (0, 16, 32):
        _write(context, result + offset, 16, 0)


def _finish(
    context: ReplayTaskRebuildStorage,
    result: int,
    calls: ReplayTaskRebuildCalls,
    atomics: ReplayUnitAIMapAtomics,
    *,
    inline: bool,
) -> None:
    if _read(context, result + 24, 8):
        raise UnresolvedReplayTaskRebuild(
            "Moving saved reader reached returned-error decoration/TLS frontier"
        )
    _write(context, result + 40, 1, 1)
    if inline:
        control = _read(context, result + 32, 8)
        if control:
            _release(context, control, calls, atomics)
        _call(calls, 0x1402BD890, (result,))
    else:
        _call(calls, 0x140900620, (result,))


def _raw(
    context: ReplayTaskRebuildStorage,
    stream: int,
    result: int,
    destination: int,
    width: int,
    calls: ReplayTaskRebuildCalls,
    atomics: ReplayUnitAIMapAtomics,
    *,
    inline: bool = False,
    target: int | None = None,
) -> None:
    _zero(context, result)
    if target is None:
        vptr = _read(context, stream, 8)
        target = _read(context, vptr + 24, 8)
    _call(calls, target, (stream, result, destination & _U64, width))
    _finish(context, result, calls, atomics, inline=inline)


def _version(context: ReplayTaskRebuildStorage) -> int:
    return _signed(_read(context, _VERSION, 4), 4)


def _path(context: ReplayTaskRebuildStorage, slot: int, calls: ReplayTaskRebuildCalls) -> int:
    allocation = _call(calls, 0x142D6BA78, (72,), width=8)
    _write(context, slot, 8, allocation)
    if not allocation:
        return 0
    for offset in (0, 16, 32, 48):
        _write(context, allocation + offset, 16, 0)
    _write(context, allocation + 64, 8, 0)
    return _call(calls, 0x14106A180, (allocation,), width=8)


def read_replay_saved_moving(
    context: ReplayTaskRebuildStorage,
    address: int,
    output: int,
    stream: int,
    opaque: int,
    *,
    calls: ReplayTaskRebuildCalls,
    atomics: ReplayUnitAIMapAtomics,
    bind_local: LocalBinding,
    scratch: ReplayMovingSavedScratch,
) -> int:
    """Full normal14121f910, including all historical/current stream sites.

    R9 remains opaque. Version skip edges retain held EAX where native code
    bypasses a reload. Current counts/pointers/tuple reads happen after real
    cleanup and helper effects. Positive path/point branches require their
    actual descendants; there is no missing-child successful fallback. Finite
    valid linked/loop storage and ordinary preserved scalar registers are
    premises. No native loop/cycle guard or transactional rollback is invented.
    """
    _validate(context, calls, address, output, stream, opaque)
    if not isinstance(atomics, ReplayUnitAIMapAtomics) or not callable(bind_local):
        raise ValueError("actual Moving atomic/local providers required")
    if not isinstance(scratch, ReplayMovingSavedScratch):
        raise ValueError("explicit Moving reader local seed required")
    with _local(memoryview(bytearray(scratch.reader)), bind_local) as frame:
        _write(context, frame + 0xB0, 8, output)
        _call(calls, _RESET, (address,))
        result = (frame + 0x78) & _U64
        _zero(context, result)
        _call(calls, 0x141142A70, (address, result, stream, opaque))
        _finish(context, result, calls, atomics, inline=True)
        _fields(context, address, ((15, 1, 30), (0x39C, 4, 0xBF800000)))

        def raw(
            destination: int, width: int, *, inline: bool = False, target: int | None = None
        ) -> None:
            _raw(
                context,
                stream,
                result,
                destination,
                width,
                calls,
                atomics,
                inline=inline,
                target=target,
            )

        for offset in (0x370, 0x374, 0x378, 0x37C, 0x380, 0x384):
            raw(address + offset, 4, inline=True)
        if _version(context) < 0x240000:
            for offset, inline in ((0xB0, True), (0xC8, True), (0xC8, True), (0xC8, False)):
                raw(frame + offset, 4, inline=inline)
        raw(address + 0x391, 1, inline=True)
        raw(address + 0x392, 1, inline=True)
        version = _version(context)
        if 0xCE3D7 <= version < 0xD3333:
            raw(frame + 0x75, 1)
            raw(frame + 0x75, 1)
            _write(context, address + 0x393, 1, int(_read(context, frame + 0x75, 1) != 0))
            version = _version(context)
        # Skipping either block also skips its following native version load.
        if version >= 0x9947A:
            raw(address + 0x390, 1)
            version = _version(context)
        if version >= 0xD3333:
            raw(address + 0x393, 1)

        head = 0
        _write(context, frame + 0xB0, 8, 0)
        raw(frame + 0xD0, 4)
        counter = 0
        if _signed(_read(context, frame + 0xD0, 4), 4) > 0:
            while True:
                path = _path(context, frame + 0xC8, calls)
                _zero(context, result)
                _call(calls, 0x14106FC40, (path, result, stream))
                _finish(context, result, calls, atomics, inline=True)
                previous = _read(context, frame + 0xB0, 8)
                _write(context, path + 8, 8, previous)
                head = path
                _write(context, frame + 0xB0, 8, path)
                counter = (counter + 1) & _U32
                if _signed(counter, 4) >= _signed(_read(context, frame + 0xD0, 4), 4):
                    break
        _write(context, address + 0x3F0, 8, head)
        if _version(context) >= 0xA1999:
            raw(frame + 0xC8, 4)
            if _read(context, frame + 0xC8, 4) == 1:
                path = _path(context, frame + 0xB0, calls)
                _write(context, address + 0x3F8, 8, path)
                _zero(context, result)
                _call(calls, 0x14106FC40, (path, result, stream))
                _finish(context, result, calls, atomics, inline=False)

        _write(context, frame + 0xB8, 8, 0)
        _write(context, frame + 0xC0, 4, 0)
        raw(frame + 0xD4, 4, inline=True)
        if _read(context, frame + 0xD4, 4) == 1:
            allocation = _call(calls, 0x142D6BA78, (24,), width=8)
            _write(context, frame + 0xB0, 8, allocation)
            controller = _call(calls, 0x14106A0F0, (allocation,), width=8) if allocation else 0
            _write(context, address + 0x400, 8, controller)
            for target, line in ((0x141075100, 0x327), (0x141074E50, 0x329)):
                raw(frame + 0xB8, 12)
                current = _read(context, address + 0x400, 8)
                # Caller-explicit four args; these retained tiny leaf bodies
                # consume RCX/RDX only. Do not collapse their actual call.
                _call(calls, target, (current, (frame + 0xB8) & _U64, 0x1432B30E0, line))

        for offset in (0x3BC, 0x3C8, 0x3D4):
            raw(address + offset, 12)
        raw(address + 0x408, 4)
        if _version(context) >= 0x446666:
            raw(address + 0x40C, 4)
        raw(frame + 0xA8, 4)
        count = _read(context, frame + 0xA8, 4)
        if _signed(count, 4) > 0:
            if not _call(calls, 0x14121A010, (address, count), width=4):
                raise UnresolvedReplayTaskRebuild(
                    "Moving positive-point helper reached failure decoration/TLS frontier"
                )
            counter, offset = 0, 0
            count = _read(context, frame + 0xA8, 4)
            if _signed(count, 4) > 0:
                while True:
                    raw(frame + 0xB8, 12)
                    destination = _read(context, address + 0x388, 8)
                    _write(context, destination + offset, 8, _read(context, frame + 0xB8, 8))
                    _write(context, destination + offset + 8, 4, _read(context, frame + 0xC0, 4))
                    counter = (counter + 1) & _U32
                    offset = (offset + 12) & _U64
                    count = _read(context, frame + 0xA8, 4)
                    if _signed(counter, 4) >= _signed(count, 4):
                        break
        _write(context, address + 0x394, 4, count)

        version = _version(context)
        if version < 0xA0CCC:
            _write(context, address + 0x3B9, 1, 0)
            _write(context, address + 0x410, 4, 0)
        else:
            selected = _read(context, _read(context, stream, 8) + 24, 8)
            raw(address + 0x3B9, 1 if version >= 0x250000 else 4, target=selected)
            raw(address + 0x3E0, 12)
            if _version(context) >= 0xA0F5C:
                raw(address + 0x410, 4)
            else:
                _write(context, address + 0x410, 4, 0)
        version = _version(context)
        if version == 0xAA3D7:
            raw(frame + 0xB0, 4)
            version = _version(context)
        if 0xC1999 <= version < 0xD3333:
            raw(frame + 0x74, 1)
            version = _version(context)
        if version >= 0xC9EB8:
            for offset in (0x358, 0x35C, 0x360, 0x364):
                raw(address + offset, 4)
            version = _version(context)
        if version >= 0x1A0A3D:
            raw(address + 0x3A0, 4)
            raw(address + 0x3A4, 4)
        if _read(context, 0x14435505B, 1) >= 1:
            _write(context, frame + 0x20, 8, 0)
            logger = _read(context, 0x144355068, 8)
            # Native MOV DL,23 defines low8 only. A reached provider must
            # consume admitted lowDL or independently supply wider ABI context.
            _call(calls, 0x14101ADB0, (logger, 0x23, 0x1432B31F8, 0, 0))
        for offset in (0, 8, 16, 24, 32):
            _write(context, output + offset, 8, 0)
        _write(context, output + 40, 1, 0)
        return output


def bind_replay_moving_saved(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    *,
    atomics: ReplayUnitAIMapAtomics,
    bind_local: LocalBinding,
    scratch: ReplayMovingSavedScratch,
) -> ReplayTaskRebuildCalls:
    """Bind only the two actual entries; all other children delegate/refuse."""
    _validate(context, calls)
    if not isinstance(atomics, ReplayUnitAIMapAtomics) or not callable(bind_local):
        raise ValueError("actual Moving atomic/local providers required")
    if not isinstance(scratch, ReplayMovingSavedScratch):
        raise ValueError("explicit Moving reader local seed required")

    def dispatch(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        if target not in (_READER, _RESET):
            if calls.call is None:
                raise UnresolvedReplayTaskRebuild(f"reached{target:x} is unavailable")
            return calls.call(target, args, data)
        if len(args) != (1 if target == _RESET else 4) or data is not None:
            raise ValueError("malformed Moving reset/reader call")
        if target == _RESET:
            reset_replay_saved_moving(context, *args, calls=bound)
            return None
        return read_replay_saved_moving(
            context,
            *args,
            calls=bound,
            atomics=atomics,
            bind_local=bind_local,
            scratch=scratch,
        )

    bound = ReplayTaskRebuildCalls(dispatch)
    return bound
