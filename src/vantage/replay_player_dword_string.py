"""Build54800 full normal2701B unsigned DWORD-length string reader140a1cf00.

Current Input/Result, control, byte-reader, repair, allocation and CRT effects
remain mandatory. Explicit E0-byte logical data frame excludes physical native
stack/home/register/cookie/fault/EH/concurrency parity. Reached error-detail/TLS
branches refuse before unported work; no encoding, termination or child success
is inferred. The distinct signed-WORD readers cannot substitute for this body.
"""

from __future__ import annotations

from dataclasses import dataclass

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
from vantage.replay_unit_ai_map import ReplayUnitAIMapAtomics, _release

_U64 = (1 << 64) - 1
_EMPTY = 0x14428BB30
_ENTRY = 0x140A1CF00


@dataclass(frozen=True, slots=True)
class ReplayPlayerDwordStringScratch:
    """Exact E0 live data bytes; logical RBP=frame+100hex, cookie outside."""

    reader: bytes

    def __post_init__(self) -> None:
        if type(self.reader) is not bytes or len(self.reader) != 0xE0:
            raise ValueError("explicit E0-byte DWORD string frame seed required")


def read_replay_player_dword_string(
    context: ReplayTaskRebuildStorage,
    address: int,
    output: int,
    stream: int,
    *,
    calls: ReplayTaskRebuildCalls,
    atomics: ReplayUnitAIMapAtomics,
    bind_local: LocalBinding,
    scratch: ReplayPlayerDwordStringScratch,
) -> int:
    """Complete normal3arg caller; return held output after actual child effects.

    All source-addressable logical data stays live through the last child.
    Flattened child arguments exclude physical outgoing-stack/home overlap and
    provider register clobbers. Error refusal preserves earlier source effects;
    it does not invent later error forwarding, cleanup or a successful return.
    """
    _validate(context, calls, address, output, stream)
    if (
        not isinstance(atomics, ReplayUnitAIMapAtomics)
        or not callable(bind_local)
        or not isinstance(scratch, ReplayPlayerDwordStringScratch)
    ):
        raise ValueError("actual atomic/local bindings and DWORD string scratch required")
    with _local(memoryview(bytearray(scratch.reader)), bind_local) as frame:

        def at(offset: int) -> int:
            return (frame + offset) & _U64

        def read(pointer: int, width: int = 8) -> int:
            return _read(context, pointer, width)

        def write(pointer: int, width: int, value: int) -> None:
            _write(context, pointer, width, value)

        def call(target: int, *args: int, width: int | None = None) -> int:
            return _call(calls, target, args, width=width)

        def zero(offset: int) -> None:
            for delta in (0, 16, 32):
                write(at(offset + delta), 16, 0)

        def release(control: int) -> None:
            if control:
                _release(context, control, calls, atomics)

        def cleanup(offset: int) -> None:
            release(read(at(offset + 32)))
            call(0x1402BD890, at(offset))

        def finish_primary(frontier: str) -> None:
            if read(at(0x78)):
                raise UnresolvedReplayTaskRebuild(frontier)
            write(at(0x88), 1, 1)
            cleanup(0x60)

        def success() -> None:
            for offset in (0, 8, 16, 24, 32):
                write(output + offset, 8, 0)
            write(output + 40, 1, 0)

        write(at(0x58), 8, output)
        if read(address + 16):
            previous = read(address)
            if previous:
                call(0x142D6C270, previous)
                for offset, value in ((0, _EMPTY), (16, 0), (8, 0)):
                    write(address + offset, 8, value)
        write(at(0x58), 4, 0)
        zero(0x60)
        zero(0xB0)
        selected = read(read(stream) + 24)
        call(selected, stream, at(0xB0), at(0x58), 4)  # Actual RAX is ignored.
        zero(0x60)
        write(at(0xD8), 1, 1)
        if read(at(0xC8)):
            call(0x140900ED0, at(0xB0), 0x1432098D0, 0x9F5, 0x143209948)
        call(0x1409076B0, at(0x60), at(0xB0))
        cleanup(0xB0)
        finish_primary("140a1d03e DWORD-size forwarded-error detail frontier")
        zero(0x60)
        size = read(at(0x58), 4)
        if size > 0x2800:
            write(at(0x28), 4, size)
            write(at(0x20), 8, 0x143209980)
            call(0x140A08840, at(0x60), 0, 0x1432098D0, 0x9E9, 0x143209980, size)
            range_control = read(at(0x80))
        else:
            write(at(0x60), 16, 0)
            write(at(0x70), 16, 0)
            range_control = 0
            write(at(0x80), 8, 0)
            write(at(0x88), 1, 0)
        if read(at(0x78)):
            raise UnresolvedReplayTaskRebuild("140a1d270 DWORD-size range error/TLS frontier")
        write(at(0x88), 1, 1)
        release(range_control)  # Held BEFORE status/processed writes, not current80.
        call(0x1402BD890, at(0x60))
        size = read(at(0x58), 4)
        if not size:
            success()
            return output
        temporary = at(0x90)
        write(temporary, 16, 0)
        write(at(0xA0), 8, 0)
        write(at(0xA8), 8, 15)
        write(temporary, 1, 0)
        fill = (size - 1) & 0xFFFFFFFF
        if not fill:
            write(at(0xA0), 8, fill)
            write(temporary + fill, 1, 0)
        elif fill <= 15:
            write(at(0xA0), 8, fill)
            call(0x142D6E3B7, temporary, 0, fill)
            write(temporary + fill, 1, 0)
        else:
            write(at(0x20), 1, 0)
            call(0x1402BB300, temporary, fill, 0, fill, 0)
        zero(0x60)
        count = read(at(0x58), 4)
        capacity = read(at(0xA8))
        current_pointer = read(temporary)  # Memory CMOVA operand read even inline.
        buffer = current_pointer if capacity > 15 else temporary
        write(at(0x30), 8, count)
        write(at(0x28), 8, buffer)
        write(at(0x20), 8, stream)
        call(0x140A150F0, at(0x60), 0x1432098D0, 0xA03, 0x14320995C, stream, buffer, count)
        finish_primary("140a1d50a DWORD-byte forwarded-error detail frontier")
        zero(0x60)
        call(0x140A09540, at(0x60), temporary)
        finish_primary("140a1d6db DWORD-string repair error/TLS frontier")
        capacity = read(at(0xA8))
        current_pointer = read(temporary)
        source = current_pointer if capacity > 15 else temporary
        previous = read(address)
        if previous:
            if read(address + 16):
                call(0x142D6C270, previous)
            for offset, value in ((0, _EMPTY), (16, 0), (8, 0)):
                write(address + offset, 8, value)
        if source and read(source, 1):
            write(at(0x48), 8, source)
            length = call(0x142D6E44D, source, width=8)
            write(at(0x50), 8, length)
            length = call(0x140A13780, at(0x48), width=8)
            if length:
                call(0x140A1A5E0, address, (length + 1) & _U64)
                destination = read(address)
                call(0x142D6E3B1, destination, source, length)
                destination = read(address)
                write(destination + length, 1, 0)
                write(address + 8, 8, length)
        success()
        call(0x1402A8920, temporary)
    return output


def bind_replay_player_dword_string(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    *,
    atomics: ReplayUnitAIMapAtomics,
    bind_local: LocalBinding,
    scratch: ReplayPlayerDwordStringScratch,
) -> ReplayTaskRebuildCalls:
    """Bind only140a1cf00; all ordinary children remain actual delegate effects."""
    _validate(context, calls)
    if (
        not isinstance(atomics, ReplayUnitAIMapAtomics)
        or not callable(bind_local)
        or not isinstance(scratch, ReplayPlayerDwordStringScratch)
    ):
        raise ValueError("actual atomic/local bindings and DWORD string scratch required")

    def call(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        if target != _ENTRY:
            if calls.call is None:
                raise UnresolvedReplayTaskRebuild(f"reached{target:x} is unavailable")
            return calls.call(target, args, data)
        if len(args) != 3 or data is not None:
            raise ValueError("malformed DWORD string reader call")
        return read_replay_player_dword_string(
            context, *args, calls=calls, atomics=atomics, bind_local=bind_local, scratch=scratch
        )

    return ReplayTaskRebuildCalls(call)
