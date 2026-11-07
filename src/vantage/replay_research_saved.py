"""Full build54800 saved research caller14148d110 (Player+6d0, not masters).

All catalog/storage, current Input, Result, strings and effect callbacks require
actual backing/providers. No default World/DAT or successful unknown child is
supplied. Logical frame256B is explicit; native homes, cookie/register/fault/EH
and concurrent execution parity are excluded. Raw MOVSS payloads use no host FP.
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

_U64 = (1 << 64) - 1
_U32 = (1 << 32) - 1
_VERSION = 0x1440A0D94
_ENTRY = 0x14148D110
_MAX = (1 << 60) - 1


@dataclass(frozen=True, slots=True)
class ReplayResearchSavedScratch:
    """Working-RSP256B seed; logical RBP=frame+100hex, cookie outside.

    Preserves unwritten Result/count/padding bytes and current saved homes.
    Incoming fifth/sixth homes are outside this frame: flattened arguments
    exclude their physical mutation. Mapping metadata is not native stack I/O.
    """

    reader: bytes

    def __post_init__(self) -> None:
        if type(self.reader) is not bytes or len(self.reader) != 0x100:
            raise ValueError("explicit256B research reader frame seed required")


def read_replay_saved_research(
    context: ReplayTaskRebuildStorage,
    address: int,
    output: int,
    stream: int,
    catalog: int,
    player: int,
    mode: int,
    *,
    calls: ReplayTaskRebuildCalls,
    atomics: ReplayUnitAIMapAtomics,
    bind_local: LocalBinding,
    scratch: ReplayResearchSavedScratch,
) -> int:
    """Complete normal6arg caller; returns CURRENT frame70 object home.

    Mode consumes lowBYTE. Player/mode retain incoming argument values at their
    late uses; physical incoming-home mutation is excluded. All exposed data
    frame homes remain current, with held register identities following source.
    Unknown/error children refuse or fail after prior effects, never succeed
    by default. Outgoing stack slots retain source-written pointer values;
    physical nested-frame/argument overlap and provider stack clobbers excluded.
    """
    _validate(context, calls, address, output, stream, catalog, player, mode)
    if (
        not isinstance(atomics, ReplayUnitAIMapAtomics)
        or not callable(bind_local)
        or not isinstance(scratch, ReplayResearchSavedScratch)
    ):
        raise ValueError("actual research atomic/local bindings and scratch required")
    with _local(memoryview(bytearray(scratch.reader)), bind_local) as frame:

        def get(offset: int, width: int = 8) -> int:
            return _read(context, frame + offset, width)

        def put(offset: int, width: int, value: int) -> None:
            _write(context, frame + offset, width, value)

        def version() -> int:
            return _signed(_read(context, _VERSION, 4), 4)

        def target(current_stream: int) -> int:
            return _read(context, _read(context, current_stream, 8) + 0x18, 8)

        def release(local: int) -> None:
            control = _read(context, local + 0x20, 8)
            if control:
                _release(context, control, calls, atomics)
            _call(calls, 0x1402BD7F0, (local,))

        def manual(
            current_stream: int, destination: int, width: int, selected: int | None = None
        ) -> bool:
            local = (frame + 0x38) & _U64
            chosen = target(current_stream) if selected is None else selected
            returned = _call(
                calls, chosen, (current_stream, local, destination & _U64, width), width=8
            )
            _write(context, returned + 0x28, 1, 1)
            _call(calls, 0x14090D270, ((output + 0x18) & _U64, (returned + 0x18) & _U64))
            if output != returned:
                begin = _read(context, returned, 8)
                end = _read(context, returned + 8, 8)
                count = (_signed((end - begin) & _U64, 8) >> 5) & _U64
                _call(calls, 0x1402B9080, (output, begin, count))
            _write(context, output + 0x28, 1, 0)
            release(local)
            return bool(_read(context, output + 0x18, 8))

        def compact(
            current_stream: int,
            destination: int,
            width: int,
            *,
            selected: int | None = None,
            secondary: bool = False,
            pair: bool = True,
        ) -> bool:
            local = (frame + (0xB8 if secondary else 0x38)) & _U64
            chosen = target(current_stream) if selected is None else selected
            returned = _call(
                calls, chosen, (current_stream, local, destination & _U64, width), width=8
            )
            _call(calls, 0x140991CE0, (output, returned))
            if pair:
                _call(calls, 0x1408EE150, ((local + 0x18) & _U64,))
                _call(calls, 0x1402BD7F0, (local,))
            else:
                release(local)
            return bool(_read(context, output + 0x18, 8))

        def row_field(owner: int, offset: int, row_offset: int) -> int:
            return (_read(context, owner, 8) + offset + row_offset) & _U64

        def finish() -> int:
            return get(0x70)

        put(0x88, 8, catalog)
        put(0x80, 8, stream)
        put(0x70, 8, address)
        put(0xB0, 8, address)
        for base in (address, address + 0x38):
            for offset in (0, 8, 16):
                _write(context, base + offset, 8, 0)
            _write(context, base + 24, 8, 32)
        reverse = (address + 0x38) & _U64
        put(0x78, 8, address + 0x20)
        if manual(stream, address + 0x20, 2):
            return finish()
        _write(context, address + 0x28, 8, catalog)
        _write(context, address + 0x30, 8, player)
        for offset, value in ((0x98, 0), (0xA0, 0), (0xA8, 32), (0x90, 0)):
            put(offset, 8, value)
        if address != (frame + 0x90) & _U64:
            begin = _read(context, address, 8)
            if begin:
                remaining = _read(context, address + 0x10, 8)
                if remaining:
                    cursor = (begin + 0x40) & _U64
                    while remaining:
                        _call(calls, 0x141493B50, ((cursor + 0x40) & _U64,))
                        for offset in (0, -0x18, -0x30):
                            _call(calls, 0x140A1B220, ((cursor + offset) & _U64,))
                        cursor = (cursor + 0x98) & _U64
                        remaining = (remaining - 1) & _U64
                    _write(context, address + 0x10, 8, 0)
                _write(context, address + 0x18, 8, 32)
                _call(calls, 0x1414938A0, (address, 0))
                _write(context, address + 0x10, 8, 0)
        current_catalog = _read(context, address + 0x28, 8)
        count = _signed(_read(context, current_catalog + 8, 2), 2)
        _call(calls, 0x141492AE0, (reverse, count & _U64))
        current_catalog = _read(context, address + 0x28, 8)
        if _signed(_read(context, current_catalog + 8, 2), 2) > 0:
            prerequisite_offset, definition = 0x18, 0
            current_owner = get(0x70)
            while True:
                for inner in range(6):
                    current_catalog = _read(context, current_owner + 0x28, 8)
                    definitions = _read(context, current_catalog, 8)
                    prerequisite = _signed(
                        _read(context, definitions + prerequisite_offset + inner * 2, 2), 2
                    )
                    if prerequisite < 0:
                        continue
                    header = (_read(context, reverse, 8) + prerequisite * 32) & _U64
                    capacity = _read(context, header + 8, 8)
                    used = _read(context, header + 16, 8)
                    if (used + 1) & _U64 > capacity:
                        increase = (used - capacity + 1) & _U64
                        if increase:
                            quantum = _read(context, header + 24, 8) or 1
                            required = (capacity + increase) & _U64
                            geometric = capacity or 1
                            while geometric < required:
                                doubled = geometric * 2 & _U64
                                if doubled == 0:
                                    raise UnresolvedReplayTaskRebuild(
                                        "excluded nonterminating wrapped dependency doubling"
                                    )
                                geometric = doubled
                            remainder = ((increase - 1 + quantum) & _U64) % quantum
                            rounded = (quantum + capacity - remainder + increase - 1) & _U64
                            _call(calls, 0x140B55580, (header, min(geometric, rounded)))
                    used = _read(context, header + 16, 8)
                    data = _read(context, header, 8)
                    destination = (data + used * 4) & _U64
                    if destination:
                        _write(context, destination, 4, definition)
                    _write(context, header + 16, 8, _read(context, header + 16, 8) + 1)
                    current_owner = get(0x70)
                definition = (definition + 1) & _U32
                prerequisite_offset = (prerequisite_offset + 0x88) & _U64
                current_catalog = _read(context, current_owner + 0x28, 8)
                if _signed(definition, 4) >= _signed(_read(context, current_catalog + 8, 2), 2):
                    break
        saved_count_pointer = get(0x78)
        last_count = _read(context, saved_count_pointer, 2)
        if _signed(last_count, 2) <= 0:
            return finish()
        current_catalog = get(0x88)
        dat_count = _read(context, current_catalog + 8, 2)
        count = max(_signed(dat_count, 2), _signed(last_count, 2))
        owner = get(0x70)
        _call(calls, 0x1414929F0, (owner, count & _U64))
        index_word = 0
        put(0x30, 2, index_word)
        last_count = _read(context, saved_count_pointer, 2)
        if _signed(last_count, 2) > 0:
            current_stream = get(0x80)
            while True:
                index = _signed(index_word, 2)
                offset = index * 0x98 & _U64
                put(0x68, 8, offset)
                selected = target(current_stream)
                destination = row_field(owner, 0, offset)
                width = 2 if version() <= 0x707AE else 4
                if manual(current_stream, destination, width, selected):
                    return finish()
                if manual(current_stream, row_field(owner, 4, offset), 2):
                    return finish()
                half_offset = index * 0x4C & _U64
                put(0x78, 8, half_offset)
                if version() >= 0xA170A:
                    for cost in range(3):
                        base = _read(context, owner, 8)
                        destination = (base + (cost + 3 + get(0x78)) * 2) & _U64
                        if manual(current_stream, destination, 2):
                            return finish()
                    half_offset = get(0x78)
                else:
                    for cost in (6, 8, 10):
                        _write(context, row_field(owner, cost, half_offset * 2), 2, 0)
                for at, width, value in (
                    (0xF0, 2, 0xFFFF),
                    (0xEC, 2, 0xFFFF),
                    (0xE8, 1, 0),
                    (0xFC, 4, _U32),
                    (0xF8, 4, 0),
                ):
                    put(at, width, value)
                held_version = version()
                if 0xA7333 <= held_version < 0x41B333:
                    if manual(current_stream, frame + 0xF8, 2):
                        return finish()
                    held_version = version()
                if held_version < 0xCEE14:
                    current_catalog = _read(context, owner + 0x28, 8)
                    current_index = get(0x30, 2)
                    dat_limit = _signed(_read(context, current_catalog + 8, 2), 2)
                    if _signed(current_index, 2) < dat_limit:
                        definitions = _read(context, current_catalog, 8)
                        legacy = _read(context, definitions + index * 0x88 + 0x70, 8)
                        put(0xE8, 1, _read(context, legacy + 4, 1))
                        put(0xEC, 2, _read(context, legacy, 2))
                elif held_version < 0x41B333:
                    if manual(current_stream, frame + 0xE8, 1):
                        return finish()
                    if manual(current_stream, frame + 0xEC, 2):
                        return finish()
                    held_version = version()
                offset = get(0x68)
                if held_version >= 0xD170A:
                    if manual(current_stream, row_field(owner, 0xC, offset), 2):
                        return finish()
                else:
                    base = _read(context, owner, 8)
                    _write(
                        context,
                        base + offset + 0xC,
                        2,
                        int(_read(context, base + offset + 4, 2) == 3),
                    )
                if version() >= 0xD1C28:
                    if manual(current_stream, row_field(owner, 0xE, offset), 1):
                        return finish()
                else:
                    _write(context, row_field(owner, 0xE, offset), 1, 1)
                for field, threshold, fallback in (
                    (0x10, 0xD451E, 0x140A15BF0),
                    (0x28, 0xD47AE, 0x140A15BF0),
                    (0x40, 0x441999, 0x140A1A7E0),
                ):
                    destination = row_field(owner, field, offset)
                    if version() >= threshold:
                        _call(
                            calls, 0x140A1BDF0, (destination, (frame + 0x38) & _U64, current_stream)
                        )
                        release((frame + 0x38) & _U64)
                    else:
                        _call(calls, fallback, (destination, 0 if field == 0x40 else 0x143676DC8))
                if version() >= 0xD4A3D:
                    if manual(current_stream, row_field(owner, 0x58, offset), 1):
                        return finish()
                else:
                    _write(context, row_field(owner, 0x58, offset), 1, 0)
                if version() >= 0x193D70:
                    if manual(current_stream, row_field(owner, 0x6E, offset), 2):
                        return finish()
                    if compact(current_stream, row_field(owner, 0x70, offset), 2):
                        return finish()
                else:
                    for field in (0x6E, 0x70):
                        _write(context, row_field(owner, field, offset), 2, 0xFFFF)
                if version() >= 0x14170A:
                    for cost in range(3):
                        current_offset = get(0x68)
                        if manual(
                            current_stream, row_field(owner, 0x5A + cost * 2, current_offset), 2
                        ):
                            return finish()
                        half_offset = get(0x78)
                        base = _read(context, owner, 8)
                        if manual(current_stream, base + (half_offset + cost + 0x30) * 2, 2):
                            return finish()
                        current_offset = get(0x68)
                        selected = target(current_stream)
                        destination = row_field(owner, 0x66 + cost * 2, current_offset)
                        modern_word = version() >= 0x1911EB
                        if compact(
                            current_stream,
                            destination,
                            2 if modern_word else 1,
                            selected=selected,
                            secondary=modern_word,
                        ):
                            return finish()
                    offset = get(0x68)
                    if manual(current_stream, row_field(owner, 0x6C, offset), 2):
                        return finish()
                else:
                    for cost in range(3):
                        for field, value in ((0x5A, 0xFFFF), (0x60, 0xFFFF), (0x66, 0xFFFE)):
                            _write(
                                context,
                                row_field(owner, field + cost * 2, half_offset * 2),
                                2,
                                value,
                            )
                    _write(context, row_field(owner, 0x6C, offset), 2, 0xFFFF)
                if version() >= 0x1A0F5C:
                    if manual(current_stream, row_field(owner, 0x74, offset), 4):
                        return finish()
                else:
                    _write(context, row_field(owner, 0x74, offset), 4, 1)
                if version() >= 0x281999:
                    if manual(current_stream, row_field(owner, 0x78, offset), 1):
                        return finish()
                else:
                    _write(context, row_field(owner, 0x78, offset), 1, 0)
                if version() >= 0x3FB333:
                    if manual(current_stream, row_field(owner, 0x7A, offset), 2):
                        return finish()
                else:
                    _write(context, row_field(owner, 0x7A, offset), 2, 0xFFFF)
                if version() >= 0x41B333:
                    if manual(current_stream, frame + 0xF4, 2):
                        return finish()
                    item = 0
                    while _signed(item, 2) < _signed(get(0xF4, 2), 2):
                        for at, size in ((0xEC, 2), (0xF0, 2)):
                            if manual(current_stream, frame + at, size):
                                return finish()
                        if compact(current_stream, frame + 0xE8, 1, pair=False):
                            return finish()
                        for at in (0xFC, 0xF8):
                            if compact(current_stream, frame + at, 4):
                                return finish()
                        header = row_field(owner, 0x80, offset)
                        put(0x28, 8, frame + 0xF8)
                        put(0x20, 8, frame + 0xFC)
                        _call(
                            calls,
                            0x14148CDD0,
                            (
                                header,
                                (frame + 0xEC) & _U64,
                                (frame + 0xF0) & _U64,
                                (frame + 0xE8) & _U64,
                                (frame + 0xFC) & _U64,
                                (frame + 0xF8) & _U64,
                            ),
                        )
                        item = (item + 1) & 0xFFFF
                    if manual(current_stream, row_field(owner, 0x7C, offset), 2):
                        return finish()
                else:
                    header = row_field(owner, 0x80, _signed(get(0x30, 2), 2) * 0x98)
                    capacity_end = _read(context, header + 16, 8)
                    insertion = _read(context, header + 8, 8)
                    if insertion != capacity_end:
                        raw_float, integer = get(0xF8, 4), get(0xFC, 4)
                        tag, second, first = get(0xE8, 1), get(0xF0, 2), get(0xEC, 2)
                        for at, size, value in (
                            (0, 2, first),
                            (2, 2, second),
                            (4, 1, tag),
                            (8, 4, integer),
                            (12, 4, raw_float),
                        ):
                            _write(context, insertion + at, size, value)
                        _write(context, header + 8, 8, _read(context, header + 8, 8) + 16)
                    else:
                        begin = _read(context, header, 8)
                        size = (_signed((insertion - begin) & _U64, 8) >> 4) & _U64
                        if size == _MAX:
                            _call(calls, 0x141493BC0, ())
                            raise RuntimeError(
                                "research length helper returned before adjacent INT3"
                            )
                        new_count = (size + 1) & _U64
                        old_capacity = (_signed((capacity_end - begin) & _U64, 8) >> 4) & _U64
                        half = old_capacity >> 1
                        if old_capacity > (_MAX - half) & _U64:
                            new_capacity = _MAX
                        else:
                            new_capacity = max(new_count, (old_capacity + half) & _U64)
                            if new_capacity > _MAX:
                                _call(calls, 0x1402A9460, ())
                                _call(calls, 0x141493BC0, ())
                                raise RuntimeError("research returned errors reached adjacent INT3")
                        allocation = _call(calls, 0x1402A94D0, (new_capacity << 4 & _U64,), width=8)
                        raw_float, integer = get(0xF8, 4), get(0xFC, 4)
                        tag, second = get(0xE8, 1), get(0xF0, 2)
                        displacement, first = size << 4 & _U64, get(0xEC, 2)
                        for at, width, value in (
                            (0, 2, first),
                            (2, 2, second),
                            (4, 1, tag),
                            (8, 4, integer),
                            (12, 4, raw_float),
                        ):
                            _write(context, allocation + displacement + at, width, value)
                        current_end = _read(context, header + 8, 8)
                        current_begin = _read(context, header, 8)
                        destination, source = allocation, current_begin
                        if insertion != current_end:
                            _call(
                                calls,
                                0x142D6E3DB,
                                (allocation, current_begin, (insertion - current_begin) & _U64),
                            )
                            current_end = _read(context, header + 8, 8)
                            destination = (allocation + displacement + 16) & _U64
                            source = insertion
                        _call(
                            calls, 0x142D6E3DB, (destination, source, (current_end - source) & _U64)
                        )
                        _call(calls, 0x141493AA0, (header, allocation, new_count, new_capacity))
                        current_stream = get(0x80)
                        owner = get(0x70)
                index_word = (get(0x30, 2) + 1) & 0xFFFF
                put(0x30, 2, index_word)
                last_count = _read(context, owner + 0x20, 2)
                if _signed(index_word, 2) >= _signed(last_count, 2):
                    break
        held_catalog = get(0x88)
        dat_count = _read(context, held_catalog + 8, 2)
        if last_count != dat_count:
            if _signed(last_count, 2) < _signed(dat_count, 2):
                _call(calls, 0x141492790, (owner, last_count))
            last_count = _read(context, held_catalog + 8, 2)
            _write(context, owner + 0x20, 2, last_count)
        if mode & 0xFF:
            index_word = 0
            while _signed(index_word, 2) < _signed(last_count, 2):
                base = _read(context, owner, 8)
                state = (base + _signed(index_word, 2) * 0x98 + 4) & _U64
                if _read(context, state, 2) == 3:
                    _write(context, state, 2, 1)
                    _call(calls, 0x141494EA0, (owner, index_word, 0, 0))
                index_word = (index_word + 1) & 0xFFFF
                last_count = _read(context, owner + 0x20, 2)
            _call(calls, 0x141493E60, (owner, _U32))
        return finish()


def bind_replay_research_saved(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    *,
    atomics: ReplayUnitAIMapAtomics,
    bind_local: LocalBinding,
    scratch: ReplayResearchSavedScratch,
) -> ReplayTaskRebuildCalls:
    """Own only14148d110; every actual child/current provider remains required."""
    _validate(context, calls)
    if (
        not isinstance(atomics, ReplayUnitAIMapAtomics)
        or not callable(bind_local)
        or not isinstance(scratch, ReplayResearchSavedScratch)
    ):
        raise ValueError("actual research atomic/local bindings and scratch required")

    def call(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        if target != _ENTRY:
            if calls.call is None:
                raise UnresolvedReplayTaskRebuild(f"reached{target:x} is unavailable")
            return calls.call(target, args, data)
        if len(args) != 6 or data is not None:
            raise ValueError("malformed research saved reader")
        return read_replay_saved_research(
            context, *args, calls=calls, atomics=atomics, bind_local=bind_local, scratch=scratch
        )

    return ReplayTaskRebuildCalls(call)
