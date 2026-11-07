"""Build54800 complete normal Player name/repair/byte/skins saved callers.

Four source-closed bodies total6284 listed/6290 physical bytes. Actual Input,
Result, shared control, predicate/conversion, storage and CRT effects remain
mandatory. Coherent E8/A0/60/B8 logical frames are explicit; native physical
stack/register/cookie/fault/EH/concurrency and reached error TLS/detail bodies
are excluded. No Unicode validity or successful unknown callback is inferred.
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
    _signed,
    _write,
)
from vantage.replay_unit_ai_base import _validate
from vantage.replay_unit_ai_construction import _local
from vantage.replay_unit_ai_map import ReplayUnitAIMapAtomics, _release

_U64, _U32 = (1 << 64) - 1, (1 << 32) - 1
_MAX_STRING, _MAX_SKINS = (1 << 63) - 1, (1 << 61) - 1
_EMPTY = 0x14428BB30


@dataclass(frozen=True, slots=True)
class ReplayPlayerNameSkinsScratch:
    """Explicit logical data frames; native cookies/saved registers excluded."""

    name: bytes
    byte_loop: bytes
    repair: bytes
    skins: bytes

    def __post_init__(self) -> None:
        for value, width in (
            (self.name, 0xE8),
            (self.byte_loop, 0xA0),
            (self.repair, 0x60),
            (self.skins, 0xB8),
        ):
            if type(value) is not bytes or len(value) != width:
                raise ValueError("explicit E8/A0/60/B8-byte logical frame seeds required")


def _frame_inputs(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    bind_local: LocalBinding,
    scratch: bytes,
    width: int,
    atomics: ReplayUnitAIMapAtomics | None = None,
) -> None:
    _validate(context, calls)
    if not callable(bind_local) or type(scratch) is not bytes or len(scratch) != width:
        raise ValueError("actual local binder and exact logical frame bytes required")
    if atomics is not None and not isinstance(atomics, ReplayUnitAIMapAtomics):
        raise ValueError("actual shared-control atomic bindings required")


@dataclass(slots=True)
class _Frame:
    context: ReplayTaskRebuildStorage
    calls: ReplayTaskRebuildCalls
    imports: ReplayTaskRebuildCalls
    frame: int
    atomics: ReplayUnitAIMapAtomics | None = None

    def at(self, offset: int) -> int:
        return (self.frame + offset) & _U64

    def read(self, address: int, width: int = 8) -> int:
        return _read(self.context, address, width)

    def write(self, address: int, width: int, value: int) -> None:
        _write(self.context, address, width, value)

    def call(self, target: int, *args: int, width: int | None = None) -> int:
        return _call(self.calls, target, args, width=width)

    def zero(self, offset: int) -> None:
        for delta in (0, 16, 32):
            self.write(self.at(offset + delta), 16, 0)

    def success(self, output: int) -> None:
        for delta in (0, 8, 16, 24, 32):
            self.write(output + delta, 8, 0)
        self.write(output + 40, 1, 0)

    def cleanup(self, offset: int, target: int) -> None:
        control = self.read(self.at(offset + 32))
        if control:
            if self.atomics is None:
                raise UnresolvedReplayTaskRebuild("shared-control atomic provider unavailable")
            _release(self.context, control, self.calls, self.atomics)
        self.call(target, self.at(offset))

    def finish(self, offset: int, target: int, frontier: str) -> None:
        if self.read(self.at(offset + 24)):
            raise UnresolvedReplayTaskRebuild(frontier)
        self.write(self.at(offset + 40), 1, 1)
        self.cleanup(offset, target)

    def read_round(
        self,
        stream: int,
        destination: int,
        size: int,
        raw: int,
        forwarded: int,
        file: int,
        line: int,
        detail: int,
        cleanup: int,
        frontier: str,
    ) -> None:
        self.zero(forwarded)
        self.zero(raw)
        table = self.read(stream)
        selected = self.read(table + 24)
        self.call(selected, stream, self.at(raw), destination, size)
        self.zero(forwarded)
        self.write(self.at(raw + 40), 1, 1)
        if self.read(self.at(raw + 24)):
            self.call(0x140900ED0, self.at(raw), file, line, detail)
        self.call(0x1409076B0, self.at(forwarded), self.at(raw))
        self.cleanup(raw, cleanup)
        self.finish(forwarded, cleanup, frontier)

    def watson(self, *, trap: str | None = None, second: bool = False) -> None:
        # The current IAT is read once per actual reached indirect call.
        self.write(self.at(0x20), 8, 0)
        _call(self.imports, self.read(0x14319A060), (0, 0, 0, 0, 0))
        if trap is not None:
            raise UnresolvedReplayTaskRebuild(f"Watson returned before genuine INT3{trap}")
        if second:
            # Repair's first bad-header call returns across a genuine NOP,
            # then reaches another independently selected zero-argument call.
            self.write(self.at(0x20), 8, 0)
            _call(self.imports, self.read(0x14319A060), (0, 0, 0, 0, 0))
        raise UnresolvedReplayTaskRebuild(
            "repair Watson returned across NOP; subsequent volatile free ABI unavailable"
        )

    def temporary_free(self, address: int) -> None:
        capacity = self.read(address + 24)
        if capacity <= 15:
            return
        size = capacity + 1 & _U64
        pointer = self.read(address)
        if size >= 0x1000:
            size = size + 0x27 & _U64
            original = pointer
            pointer = self.read(pointer - 8)
            if (original - pointer - 8) & _U64 > 31:
                self.watson(second=True)
        self.call(0x142D6BAB4, pointer, size)


def read_replay_player_name_bytes(
    context: ReplayTaskRebuildStorage,
    output: int,
    metadata: int,
    line: int,
    detail: int,
    stream: int,
    buffer: int,
    length: int,
    *,
    calls: ReplayTaskRebuildCalls,
    atomics: ReplayUnitAIMapAtomics,
    bind_local: LocalBinding,
    scratch: bytes,
) -> int:
    """Full1130B140a150f0; seven scalar args, incoming metadata registers unused.

    Held buffer/stream/length and wrapping DWORD index reach actual one-byte
    Inputs. Zero length still writes only the41-byte success result. Error
    detail/TLS paths refuse before their first unported instruction.
    """
    _validate(context, calls, output, metadata, line, detail, stream, buffer, length)
    _frame_inputs(context, calls, bind_local, scratch, 0xA0, atomics)
    if not isinstance(atomics, ReplayUnitAIMapAtomics):
        raise ValueError("actual shared-control atomic bindings required")
    with _local(memoryview(bytearray(scratch)), bind_local) as frame:
        state = _Frame(context, calls, calls, frame, atomics)
        state.write(state.at(0x28), 8, output)
        if length > 0xA00000:
            raise UnresolvedReplayTaskRebuild("140a15151 byte-length TLS frontier")
        index = 0
        while index < length:
            state.read_round(
                stream,
                (buffer + index) & _U64,
                1,
                0x30,
                0x70,
                0x143209830,
                0x1D4,
                0x1432098A0,
                0x1402BD890,
                "140a153af byte forwarded-error detail frontier",
            )
            index = index + 1 & _U32
        state.success(output)
    return output


def read_replay_player_name(
    context: ReplayTaskRebuildStorage,
    address: int,
    output: int,
    stream: int,
    *,
    calls: ReplayTaskRebuildCalls,
    atomics: ReplayUnitAIMapAtomics,
    bind_local: LocalBinding,
    scratch: bytes,
) -> int:
    """Whole2317B140a1d990 normal signed-WORD name reader, held output return.

    The temporary buffer, both Results and outgoing slots share the E8-byte
    frame. CMOVA memory operands are read even when the inline buffer wins.
    Predicate/repair and the final descriptor getter remain actual calls.
    """
    _validate(context, calls, address, output, stream)
    _frame_inputs(context, calls, bind_local, scratch, 0xE8, atomics)
    if not isinstance(atomics, ReplayUnitAIMapAtomics):
        raise ValueError("actual shared-control atomic bindings required")
    with _local(memoryview(bytearray(scratch)), bind_local) as frame:
        state = _Frame(context, calls, calls, frame, atomics)
        state.write(state.at(0x48), 8, output)
        if state.read(address + 16):
            pointer = state.read(address)
            if pointer:
                state.call(0x142D6C270, pointer)
                for offset, value in ((0, _EMPTY), (16, 0), (8, 0)):
                    state.write(address + offset, 8, value)
        state.write(state.at(0x64), 2, 0)
        state.read_round(
            stream,
            state.at(0x64),
            2,
            0xB8,
            0x68,
            0x1432098D0,
            0x9AF,
            0x143209948,
            0x1402BD890,
            "140a1dac6 name-size forwarded-error detail frontier",
        )
        required = _signed(state.read(state.at(0x64), 2), 2)
        if required < 1:
            raise UnresolvedReplayTaskRebuild("140a1dc59 signed name-size TLS frontier")
        temporary = state.at(0x98)
        state.write(temporary, 16, 0)
        state.write(state.at(0xA8), 8, 0)
        state.write(state.at(0xB0), 8, 15)
        state.write(temporary, 1, 0)
        count = required - 1
        if count == 0:
            state.write(state.at(0xA8), 8, count)
            state.write(temporary + count, 1, count)
        elif count <= 15:
            state.write(state.at(0xA8), 8, count)
            state.call(0x142D6E3B7, temporary, 0, count)
            state.write(temporary + count, 1, 0)
        else:
            state.write(state.at(0x20), 1, 0)
            state.call(0x1402BB300, temporary, count, 0, count, 0)
        state.zero(0x68)
        current_required = _signed(state.read(state.at(0x64), 2), 2) & _U64
        capacity = state.read(state.at(0xB0))
        pointer = state.read(temporary)
        buffer = pointer if capacity > 15 else temporary
        state.write(state.at(0x30), 8, current_required)
        state.write(state.at(0x28), 8, buffer)
        state.write(state.at(0x20), 8, stream)
        state.call(
            0x140A150F0,
            state.at(0x68),
            0x1432098D0,
            0x9B8,
            0x14320995C,
            stream,
            buffer,
            current_required,
        )
        state.finish(0x68, 0x1402BD890, "140a1dda1 name-buffer error detail frontier")
        state.zero(0x68)
        state.call(0x140A09540, state.at(0x68), temporary)
        state.finish(0x68, 0x1402BD890, "140a1dfb5 name-repair TLS frontier")
        capacity = state.read(state.at(0xB0))
        pointer = state.read(temporary)
        source = pointer if capacity > 15 else temporary
        destination = state.read(address)
        if destination:
            if state.read(address + 16):
                state.call(0x142D6C270, destination)
            for offset, value in ((0, _EMPTY), (16, 0), (8, 0)):
                state.write(address + offset, 8, value)
        if source and state.read(source, 1):
            state.write(state.at(0x48), 8, source)
            length = state.call(0x142D6E44D, source, width=8)
            state.write(state.at(0x50), 8, length)
            length = state.call(0x140A13780, state.at(0x48), width=8)
            if length:
                state.call(0x140A1A5E0, address, length + 1)
                destination = state.read(address)
                state.call(0x142D6E3B1, destination, source, length)
                destination = state.read(address)
                state.write(destination + length, 1, 0)
                state.write(address + 8, 8, length)
        state.success(output)
        state.call(0x1402A8920, temporary)
    return output


def repair_replay_player_name(
    context: ReplayTaskRebuildStorage,
    output: int,
    address: int,
    *,
    calls: ReplayTaskRebuildCalls,
    bind_local: LocalBinding,
    scratch: bytes,
    imports: ReplayTaskRebuildCalls | None = None,
) -> int:
    """Whole715B140a09540 normal predicate/registry/conversion/copy caller.

    Registry bounds and selected conversion length/buffer are held. Storage
    reads, sized frees and output effects are current and preserve aliases.
    Returned Watson crosses real NOPs, not a fabricated trap; its later
    volatile free ABI refuses explicitly. No conversion result is assumed.
    """
    _validate(context, calls, output, address)
    _frame_inputs(context, calls, bind_local, scratch, 0x60)
    terminal = calls if imports is None else imports
    _validate(context, terminal)
    with _local(memoryview(bytearray(scratch)), bind_local) as frame:
        state = _Frame(context, calls, terminal, frame)
        state.write(state.at(0x38), 8, output)
        selected = address
        if state.read(address + 24) > 15:
            selected = state.read(address)
        if state.call(0x140A84390, selected, 0, width=1):
            state.success(output)
            return output
        cursor = state.read(0x14428B910)
        end = state.read(0x14428B918)
        temporary = state.at(0x40)
        while cursor != end:
            state.write(temporary, 16, 0)
            state.write(temporary + 16, 8, 0)
            state.write(temporary + 24, 8, 15)
            state.write(temporary, 1, 0)
            selected = address
            if state.read(address + 24) > 15:
                selected = state.read(address)
            code = state.read(cursor, 4)
            converted = state.call(0x140960630, code, selected, temporary, width=1)
            if converted:
                if address != temporary:
                    length = state.read(temporary + 16)
                    capacity = state.read(temporary + 24)
                    pointer = state.read(temporary)
                    source = pointer if capacity > 15 else temporary
                    old_capacity = state.read(address + 24)
                    if length <= old_capacity:
                        destination = address if old_capacity <= 15 else state.read(address)
                        state.write(address + 16, 8, length)
                        state.call(0x142D6E3DB, destination, source, length)
                        state.write(destination + length, 1, 0)
                    else:
                        if length > _MAX_STRING:
                            state.call(0x1402A91E0)
                            raise UnresolvedReplayTaskRebuild(
                                "repair length error returned before terminal INT3"
                            )
                        rounded = length | 15
                        half = old_capacity >> 1
                        capacity = _MAX_STRING
                        if rounded <= _MAX_STRING and old_capacity <= _MAX_STRING - half:
                            capacity = max(rounded, old_capacity + half)
                        replacement = state.call(0x1402A94D0, capacity + 1, width=8)
                        state.write(address + 16, 8, length)
                        state.write(address + 24, 8, capacity)
                        state.call(0x142D6E3B1, replacement, source, length)
                        state.write(replacement + length, 1, 0)
                        if old_capacity > 15:
                            pointer = state.read(address)
                            size = old_capacity + 1 & _U64
                            if size >= 0x1000:
                                size = size + 0x27 & _U64
                                original = pointer
                                pointer = state.read(pointer - 8)
                                if (original - pointer - 8) & _U64 > 31:
                                    state.watson()
                            state.call(0x142D6BAB4, pointer, size)
                        state.write(address, 8, replacement)
                state.success(output)
                state.temporary_free(temporary)
                return output
            state.temporary_free(temporary)
            cursor = cursor + 4 & _U64
        state.write(state.at(0x20), 8, 0x143208930)
        state.call(0x140A08840, output, 0, 0x1432088D0, 0x27, 0x143208930)
    return output


def _count_qwords(end: int, begin: int) -> int:
    return (_signed((end - begin) & _U64, 8) >> 3) & _U64


def read_replay_player_skins(
    context: ReplayTaskRebuildStorage,
    output: int,
    stream: int,
    header: int,
    *,
    calls: ReplayTaskRebuildCalls,
    atomics: ReplayUnitAIMapAtomics,
    bind_local: LocalBinding,
    scratch: bytes,
    imports: ReplayTaskRebuildCalls | None = None,
) -> int:
    """Whole2128B140e33410; count/Input/clear/reserve/append/growth chronology.

    Zero count still reads and conditionally clears current vector headers.
    Non-growth retains the incoming stream; growth alone reloads its frame40
    home. Every real memmove and commit remains mandatory, even for zero bytes.
    """
    _validate(context, calls, output, stream, header)
    _frame_inputs(context, calls, bind_local, scratch, 0xB8, atomics)
    if not isinstance(atomics, ReplayUnitAIMapAtomics):
        raise ValueError("actual shared-control atomic bindings required")
    terminal = calls if imports is None else imports
    _validate(context, terminal)
    with _local(memoryview(bytearray(scratch)), bind_local) as frame:
        state = _Frame(context, calls, terminal, frame, atomics)
        state.write(state.at(0x40), 8, stream)
        state.write(state.at(0x80), 8, output)
        state.write(state.at(0x48), 4, 0)
        state.read_round(
            stream,
            state.at(0x48),
            4,
            0x88,
            0x50,
            0x14325F510,
            0x2A5,
            0x14325FAF0,
            0x1402BD7F0,
            "140e3351f skins-count forwarded-error detail frontier",
        )
        count = state.read(state.at(0x48), 4)
        byte_count = count * 8
        if byte_count > 0x6400000:
            raise UnresolvedReplayTaskRebuild("140e336f5 skins-count TLS frontier")
        end = state.read(header + 8)
        begin = state.read(header)
        if begin != end:
            state.write(header + 8, 8, begin)
            end = begin
        capacity = state.read(header + 16)
        gate_count = count
        if count > _count_qwords(capacity, begin):
            old_size = _count_qwords(end, begin)
            if not byte_count:
                replacement = 0  # Unreachable from the unsigned count/capacity guard.
            elif byte_count < 0x1000:
                replacement = state.call(0x142D6BA78, byte_count, width=8)
            else:
                extent = byte_count + 0x27 & _U64
                if extent <= byte_count:
                    state.call(0x1402A9460)
                    raise UnresolvedReplayTaskRebuild(
                        "allocation error returned before INT3 at140e33c5a"
                    )
                allocation = state.call(0x142D6BA78, extent, width=8)
                if not allocation:
                    state.watson(trap="140e33807")
                replacement = (allocation + 0x27) & (_U64 & ~31)
                state.write(replacement - 8, 8, allocation)
            current_begin = state.read(header)
            current_end = state.read(header + 8)
            state.call(0x142D6E3DB, replacement, current_begin, current_end - current_begin)
            state.call(0x1402BA970, header, replacement, old_size, count)
            gate_count = state.read(state.at(0x48), 4)
        state.write(state.at(0x34), 4, 0)
        if gate_count:
            while True:
                state.read_round(
                    stream,
                    state.at(0x80),
                    8,
                    0x88,
                    0x50,
                    0x14325F510,
                    0x2B3,
                    0x14325FB00,
                    0x1402BD7F0,
                    "140e33a9f skins-item forwarded-error detail frontier",
                )
                capacity = state.read(header + 16)
                insertion = state.read(header + 8)
                if insertion != capacity:
                    item = state.read(state.at(0x80))
                    state.write(insertion, 8, item)
                    current_end = state.read(header + 8)
                    state.write(header + 8, 8, current_end + 8)
                else:
                    begin = state.read(header)
                    size = _count_qwords(insertion, begin)
                    if size == _MAX_SKINS:
                        state.call(0x1402BB990)
                        raise UnresolvedReplayTaskRebuild("skins length error returned before INT3")
                    next_size = size + 1 & _U64
                    capacity_count = _count_qwords(capacity, begin)
                    half = capacity_count >> 1
                    grown = _MAX_SKINS
                    if capacity_count <= (_MAX_SKINS - half) & _U64:
                        grown = max((capacity_count + half) & _U64, next_size)
                        if grown > _MAX_SKINS:
                            state.call(0x1402A9460)
                            raise UnresolvedReplayTaskRebuild(
                                "allocation error returned before terminal INT3"
                            )
                    replacement = state.call(0x1402A94D0, grown * 8, width=8)
                    item = state.read(state.at(0x80))
                    state.write(replacement + size * 8, 8, item)
                    current_end = state.read(header + 8)
                    current_begin = state.read(header)
                    if insertion == current_end:
                        state.call(
                            0x142D6E3DB, replacement, current_begin, current_end - current_begin
                        )
                    else:
                        state.call(
                            0x142D6E3DB, replacement, current_begin, insertion - current_begin
                        )
                        current_end = state.read(header + 8)
                        state.call(
                            0x142D6E3DB,
                            replacement + next_size * 8,
                            insertion,
                            current_end - insertion,
                        )
                    state.call(0x1402BA970, header, replacement, next_size, grown)
                    stream = state.read(state.at(0x40))
                index = state.read(state.at(0x34), 4) + 1 & _U32
                state.write(state.at(0x34), 4, index)
                if index >= state.read(state.at(0x48), 4):
                    break
        state.success(output)
    return output


def bind_replay_player_name_skins(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    *,
    atomics: ReplayUnitAIMapAtomics,
    bind_local: LocalBinding,
    scratch: ReplayPlayerNameSkinsScratch,
    imports: ReplayTaskRebuildCalls | None = None,
) -> ReplayTaskRebuildCalls:
    """Bind all four callers; actual descendants and terminal imports stay explicit."""
    _validate(context, calls)
    if (
        not isinstance(atomics, ReplayUnitAIMapAtomics)
        or not callable(bind_local)
        or not isinstance(scratch, ReplayPlayerNameSkinsScratch)
    ):
        raise ValueError("actual atomics/local bindings and four frame seeds required")
    terminal = calls if imports is None else imports
    _validate(context, terminal)

    def dispatch(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        arities = {0x140A1D990: 3, 0x140A150F0: 7, 0x140A09540: 2, 0x140E33410: 3}
        if target not in arities:
            if calls.call is None:
                raise UnresolvedReplayTaskRebuild(f"reached{target:x} is unavailable")
            return calls.call(target, args, data)
        if len(args) != arities[target] or data is not None:
            raise ValueError("malformed Player name/skins call")
        if target == 0x140A1D990:
            return read_replay_player_name(
                context,
                *args,
                calls=bound,
                atomics=atomics,
                bind_local=bind_local,
                scratch=scratch.name,
            )
        if target == 0x140A150F0:
            return read_replay_player_name_bytes(
                context,
                *args,
                calls=bound,
                atomics=atomics,
                bind_local=bind_local,
                scratch=scratch.byte_loop,
            )
        if target == 0x140A09540:
            return repair_replay_player_name(
                context,
                *args,
                calls=bound,
                bind_local=bind_local,
                scratch=scratch.repair,
                imports=terminal,
            )
        return read_replay_player_skins(
            context,
            *args,
            calls=bound,
            atomics=atomics,
            bind_local=bind_local,
            scratch=scratch.skins,
            imports=terminal,
        )

    bound = ReplayTaskRebuildCalls(dispatch)
    return bound
