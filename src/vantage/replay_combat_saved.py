"""Build54800 complete normal Combat saved reader1411587a0.

All inherited readers, Input, Result forwarding/cleanup, tracker and current
virtual960 effects require real bindings. Error decoration/TLS refuses at its
reached frontier. Coherent successful backing, live explicit locals and finite
loops are premises; physical stack/register/cookie, fault/EH/concurrency and
whole World restoration are outside this logical source-derived profile.
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
_ENTRY = 0x1411587A0
_VERSION = 0x1440A0D94


@dataclass(frozen=True, slots=True)
class ReplayCombatSavedScratch:
    """C8-byte seed at native working-RSP offsets, with no inferred zeros.

    Raw Result48 occupies48..77, secondary Result48 occupies78..a7. Tuple38,
    key/priorMasterb0, second/decodeb8, countc0 and firstc4 are reused live.
    The native cookie atc8, register homes, nested native-stack overlap and
    escaped pointers after return are excluded. R9 is an opaque fourth input.
    """

    reader: bytes

    def __post_init__(self) -> None:
        if type(self.reader) is not bytes or len(self.reader) != 0xC8:
            raise ValueError("explicit C8-byte Combat reader seed required")


def _zero(context: ReplayTaskRebuildStorage, result: int) -> None:
    for offset in (0, 16, 32):
        _write(context, result + offset, 16, 0)


def _status(context: ReplayTaskRebuildStorage, result: int) -> None:
    if _read(context, result + 24, 8):
        raise UnresolvedReplayTaskRebuild(
            "Combat saved reader reached returned-error decoration/TLS frontier"
        )


def _dispose(
    context: ReplayTaskRebuildStorage,
    result: int,
    calls: ReplayTaskRebuildCalls,
    atomics: ReplayUnitAIMapAtomics,
) -> None:
    control = _read(context, result + 32, 8)
    if control:
        _release(context, control, calls, atomics)
    _call(calls, 0x1402BD7F0, (result,))


def _version(context: ReplayTaskRebuildStorage) -> int:
    return _signed(_read(context, _VERSION, 4), 4)


def read_replay_saved_combat(
    context: ReplayTaskRebuildStorage,
    address: int,
    output: int,
    stream: int,
    opaque: int,
    *,
    calls: ReplayTaskRebuildCalls,
    atomics: ReplayUnitAIMapAtomics,
    bind_local: LocalBinding,
    scratch: ReplayCombatSavedScratch,
) -> int:
    """Full normal caller, preserving held-version skips and current aliases.

    The Action parent receives all four original inputs. Wrapper RAX is ignored;
    the caller always checks its own Result. Tracker returns a direct value slot.
    Protected-master decoding uses raw integer qword arithmetic. Missing work or
    read/callback failure retains all prior effects; no default success exists.
    """
    _validate(context, calls, address, output, stream, opaque)
    if not isinstance(atomics, ReplayUnitAIMapAtomics) or not callable(bind_local):
        raise ValueError("actual Combat atomic/local providers required")
    if not isinstance(scratch, ReplayCombatSavedScratch):
        raise ValueError("explicit Combat reader seed required")
    with _local(memoryview(bytearray(scratch.reader)), bind_local) as frame:
        _write(context, frame + 0x38, 8, output)
        for offset in range(0x4A8, 0x4F0, 8):
            _write(context, address + offset, 8, 0)
        _write(context, address + 0x4FC, 2, 0)
        _write(context, address + 0x4F0, 8, 0)
        _write(context, address + 0x4A0, 1, 0)
        result = (frame + 0x48) & _U64
        secondary = (frame + 0x78) & _U64
        _zero(context, result)
        _call(calls, 0x14113E920, (address, result, stream, opaque))
        _status(context, result)
        _write(context, result + 40, 1, 1)
        _dispose(context, result, calls, atomics)
        _write(context, address + 15, 1, 0x32)

        def request(destination: int, width: int) -> None:
            _zero(context, result)
            target = _read(context, _read(context, stream, 8) + 24, 8)
            _call(calls, target, (stream, result, destination & _U64, width))

        def raw(destination: int, width: int, mode: str = "ordinary") -> None:
            request(destination, width)
            _status(context, result)
            _write(context, result + 40, 1, 1)
            if mode == "count":
                _call(calls, 0x140900620, (result,))
            elif mode == "key":
                _call(calls, 0x1408EE150, (result + 24,))
                _call(calls, 0x1402BD7F0, (result,))
            else:
                _dispose(context, result, calls, atomics)

        def forwarded(destination: int, width: int, mode: str) -> None:
            _zero(context, secondary)
            request(destination, width)
            _zero(context, secondary)
            # These two raw sites mark processed BEFORE checking raw status.
            _write(context, result + 40, 1, 1)
            _status(context, result)
            _call(calls, 0x1409076B0, (secondary, result))
            _dispose(context, result, calls, atomics)
            _status(context, secondary)
            _write(context, secondary + 40, 1, 1)
            if mode == "refund":
                _call(calls, 0x140900620, (secondary,))
            else:
                _dispose(context, secondary, calls, atomics)

        def wrapped(destination: int, byte: bool, line: int, detail: int) -> None:
            _zero(context, result)
            _write(context, frame + 0x28, 8, destination)
            _write(context, frame + 0x20, 8, stream)
            _call(
                calls,
                0x140D07EE0 if byte else 0x140D94310,
                (result, 0x1432A7A60, line, detail, stream, destination),
            )
            _status(context, result)
            _write(context, result + 40, 1, 1)
            _call(calls, 0x140900620, (result,))

        if _version(context) >= 0x90CCC:
            for offset in (0x51D, 0x51E, 0x51F):
                raw(address + offset, 1)
        else:
            _write(context, address + 0x51D, 2, 0)
            _write(context, address + 0x51F, 1, 0)
        raw(address + 0x514, 4)
        version = _version(context)
        if version >= 0x423333:
            raw(address + 0x518, 4)
            version = _version(context)
        if version >= 0x2028F:
            raw(address + 0x51C, 1)
            version = _version(context)
        if version >= 0x9170A:
            raw(address + 0x4FC, 1)
            raw(address + 0x4FD, 1)
            version = _version(context)
        if version >= 0xA051E:
            raw(address + 0x4F8, 4)
            version = _version(context)
        if version >= 0x1A2E14:
            raw(address + 0x4A0, 1)
            version = _version(context)
        if version >= 0x3D0A3D:
            raw(frame + 0xC0, 4, "count")
            counter = 0
            if _signed(_read(context, frame + 0xC0, 4), 4) > 0:
                while True:
                    raw(frame + 0xC4, 4)
                    raw(frame + 0xB8, 4)
                    _write(context, frame + 0xB0, 4, 0xFFFFFFFF)
                    entry_version = _version(context)
                    if entry_version >= 0x3EE666 and entry_version != 0x3F0000:
                        raw(frame + 0xB0, 4, "key")
                    first = _read(context, frame + 0xC4, 4)
                    _write(context, frame + 0x38, 4, first)
                    second = _read(context, frame + 0xB8, 4)
                    _write(context, frame + 0x3C, 4, second)
                    slot = _call(calls, 0x1411445A0, (address + 0x520, frame + 0xB0), width=8)
                    value = _read(context, frame + 0x38, 8)
                    _write(context, slot, 8, value)
                    counter = (counter + 1) & 0xFFFFFFFF
                    if _signed(counter, 4) >= _signed(_read(context, frame + 0xC0, 4), 4):
                        break
            version = _version(context)
        if version >= 0x3F8000:
            raw(address + 0x590, 4)
            version = _version(context)
        if version >= 0x3F9999:
            forwarded(frame + 0xB0, 2, "master")
            index = _signed(_read(context, frame + 0xB0, 2), 2)
            previous = 0
            if index != -1:
                owner = _read(context, address + 24, 8)
                table = _read(context, owner + 40, 8)
                previous = _read(context, table + index * 8, 8)
            _write(context, address + 0x500, 8, previous)
            wrapped(address + 0x508, False, 0x1B7, 0x1432A7AC0)
            wrapped(address + 0x50C, False, 0x1B8, 0x1432A7AD8)
            wrapped(address + 0x510, False, 0x1B9, 0x1432A7AF8)
            version = _version(context)
        if version >= 0x403333:
            wrapped(address + 0x594, True, 0x1BE, 0x1432A7B18)
            version = _version(context)
        if version >= 0x44B333:
            forwarded(address + 0x59C, 4, "refund")
            wrapped(address + 0x5A0, False, 0x1C3, 0x1432A7B48)
        _write(context, frame + 0xB8, 8, _read(context, address + 16, 8))
        for key in (0x6A586EB28AC201FC, 0x0CF19788B2554E70):
            _write(context, frame + 0xB8, 8, _read(context, frame + 0xB8, 8) - key)
        master = _read(context, frame + 0xB8, 8)
        vptr = _read(context, address, 8)
        task_list = _read(context, master + 0x228, 8)
        _call(calls, _read(context, vptr + 0x960, 8), (address, task_list))
        for offset in (0, 8, 16, 24, 32):
            _write(context, output + offset, 8, 0)
        _write(context, output + 40, 1, 0)
        return output


def bind_replay_combat_saved(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    *,
    atomics: ReplayUnitAIMapAtomics,
    bind_local: LocalBinding,
    scratch: ReplayCombatSavedScratch,
) -> ReplayTaskRebuildCalls:
    """Bind only1411587a0 with four integer inputs and no data-view surrogate."""
    _validate(context, calls)
    if not isinstance(atomics, ReplayUnitAIMapAtomics) or not callable(bind_local):
        raise ValueError("actual Combat atomic/local providers required")
    if not isinstance(scratch, ReplayCombatSavedScratch):
        raise ValueError("explicit Combat reader seed required")

    def dispatch(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        if target != _ENTRY:
            if calls.call is None:
                raise UnresolvedReplayTaskRebuild(f"reached{target:x} is unavailable")
            return calls.call(target, args, data)
        if len(args) != 4 or data is not None:
            raise ValueError("malformed Combat saved-reader call")
        return read_replay_saved_combat(
            context,
            *args,
            calls=bound,
            atomics=atomics,
            bind_local=bind_local,
            scratch=scratch,
        )

    bound = ReplayTaskRebuildCalls(dispatch)
    return bound
