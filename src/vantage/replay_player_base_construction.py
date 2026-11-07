"""Build54800 full14649B141713f70 normal Base Player saved constructor.

This staged authored Python port preserves current storage, actual child calls,
Result/control lifetimes and the coherent4770-byte logical data frame. It does
not supply successful effects for missing children, an observed World identity,
or native physical stack/register/cookie/fault/EH/thread/FP-status parity. The
held effective fifth pointer is read only at the source's1417141d3 phase;
aliasing its excluded physical incoming home47f0 is outside this API profile.
"""

from __future__ import annotations

from dataclasses import dataclass

from .replay_player_construction_support import (
    ReplayPlayerMarkerCall,
    ReplayPlayerSupportFloatingCalls,
)
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

_U32, _U64 = (1 << 32) - 1, (1 << 64) - 1
_VERSION = 0x1440A0D94
_FILE = 0x1432F4B40
_EMPTY = 0x14428BB30
_CIPHER = (0xA9834B738A7DD167, 0x042AC42976FCCEF5, 0xC22D6B496D833977, 0x6AE24D3352F04511)


class _ReturnedStatus(Exception):
    """Private control transfer for a reached, cleaned, nonzero output status."""


@dataclass(slots=True)
class _PlayerConstruction:
    context: ReplayTaskRebuildStorage
    calls: ReplayTaskRebuildCalls
    imports: ReplayTaskRebuildCalls
    atomics: ReplayUnitAIMapAtomics
    floating: ReplayPlayerSupportFloatingCalls
    address: int
    output: int
    stream: int
    frame: int
    marker_word: int = 0

    def read(self, address: int, width: int = 8) -> int:
        return _read(self.context, address, width)

    def write(self, address: int, width: int, value: int) -> None:
        _write(self.context, address, width, value)

    def invoke(self, target: int, *args: int, result: bool = False) -> int:
        return _call(self.calls, target, args, width=8 if result else None)

    def imported(self, slot: int, *args: int, result: bool = False) -> int:
        return _call(self.imports, self.read(slot), args, width=8 if result else None)

    def local(self, offset: int) -> int:
        return (self.frame + offset) & _U64

    def field(self, offset: int) -> int:
        return (self.address + offset) & _U64

    def version(self) -> int:
        return _signed(self.read(_VERSION, 4), 4)

    def check(self) -> None:
        if self.read(self.output + 24):
            raise _ReturnedStatus

    def zero_result(self, offset: int) -> None:
        for delta in (0, 16, 32):
            self.write(self.local(offset + delta), 16, 0)

    def inline_cleanup(self, offset: int) -> None:
        control = self.read(self.local(offset + 32))
        if control:
            _release(self.context, control, self.calls, self.atomics)
        self.invoke(0x1402BD7F0, self.local(offset))

    def cleanup(self, kind: str, offset: int = 0x40) -> None:
        if kind == "inline":
            self.inline_cleanup(offset)
        elif kind == "pair":
            self.invoke(0x1408EE150, self.local(offset + 24))
            self.invoke(0x1402BD7F0, self.local(offset))
        else:
            self.invoke(0x140900620, self.local(offset))

    def adopt(self, source: int, *, end_first: bool = False) -> None:
        self.write(source + 40, 1, 1)
        self.invoke(0x14090D270, self.output + 24, source + 24)
        if self.output != source:
            if end_first:
                end = self.read(source + 8)
                begin = self.read(source)
            else:
                begin = self.read(source)
                end = self.read(source + 8)
            count = (_signed((end - begin) & _U64, 8) >> 5) & _U64
            self.invoke(0x1402B9080, self.output, begin, count)
        self.write(self.output + 40, 1, 0)

    def finish(
        self, returned: int, *, manual: bool = False, cleanup: str = "finalize", check: bool = True
    ) -> None:
        if manual:
            self.adopt(returned)
        else:
            self.invoke(0x140991CE0, self.output, returned)
        self.cleanup(cleanup)
        if check:
            self.check()

    def input(
        self,
        destination: int,
        width: int,
        *,
        output: int | None = None,
        selected: int | None = None,
        result: bool = True,
    ) -> int:
        target = selected
        if target is None:
            table = self.read(self.stream)
            target = self.read(table + 24)
        return self.invoke(
            target,
            self.stream,
            self.local(0x40) if output is None else output,
            destination,
            width,
            result=result,
        )

    def read_field(
        self, offset: int, width: int, *, cleanup: str = "finalize", manual: bool = False
    ) -> None:
        returned = self.input(self.field(offset), width)
        self.finish(returned, manual=manual, cleanup=cleanup)

    def marker(
        self,
        byte_offset: int = 0,
        label: int = 0x1432F2510,
        *,
        first: bool = False,
        manual: bool = False,
        cleanup: str = "finalize",
    ) -> None:
        expected = self.read(0x1440A0EE0 + byte_offset, 1)
        self.write(self.local(0x20), 1, expected)
        if first:
            self.marker_word = self.read(0x1432ED700, 4)
        invocation = ReplayPlayerMarkerCall(
            self.local(0x40),
            self.stream,
            label,
            self.marker_word,
            expected,
        )
        if self.floating.call is None:
            raise UnresolvedReplayTaskRebuild("reached14162cd70 mixed-FP provider unavailable")
        returned = self.floating.call(0x14162CD70, invocation)
        if returned is None:
            raise ValueError("Player marker must return its raw RAX")
        _unsigned(returned, 8, "Player marker raw RAX")
        self.finish(returned, manual=manual, cleanup=cleanup)

    def typed(
        self, target: int, line: int, detail: int, destination: int, *, check: bool = True
    ) -> None:
        # Every typed caller stores the sixth pointer before the fifth stream.
        self.write(self.local(0x28), 8, destination)
        self.write(self.local(0x20), 8, self.stream)
        returned = self.invoke(
            target, self.local(0x40), _FILE, line, detail, self.stream, destination, result=True
        )
        self.finish(returned, check=check)

    def secondary(self, line: int, detail: int) -> None:
        """Called after its real child; destination40 is zeroed after that child."""
        self.zero_result(0x40)
        self.write(self.local(0x110), 1, 1)
        if self.read(self.local(0x100)):
            self.invoke(0x140900ED0, self.local(0xE8), _FILE, line, detail)
        self.invoke(0x1409076B0, self.local(0x40), self.local(0xE8))
        self.cleanup("pair", 0xE8)
        # The source consumes the fixed forwarded40, not the forwarder's RAX.
        self.finish(self.local(0x40), check=False)

    def cipher(self, *, decode: bool = False, local_keys: bool = False) -> None:
        slot = self.local(0x30)
        if decode:
            for operation, constant in (
                ("xor", _CIPHER[3]),
                ("xor", _CIPHER[2]),
                ("sub", _CIPHER[1]),
                ("xor", _CIPHER[0]),
            ):
                value = self.read(slot)
                value = value ^ constant if operation == "xor" else value - constant
                self.write(slot, 8, value)
            return
        for index, operation in enumerate(("xor", "add", "xor", "xor")):
            value = self.read(slot)
            constant = (
                self.read(self.local(0x78 if index == 0 else 0x38))
                if local_keys and index < 2
                else _CIPHER[index]
            )
            self.write(slot, 8, value ^ constant if operation == "xor" else value + constant)

    def initial_fields(self, world: int, index_pointer: int) -> None:
        self.write(self.local(0xB0), 8, self.address)
        self.write(self.address, 8, 0x1432F47D0)
        for offset, width, value in (
            (0x10, 4, _U32),
            (0x14, 4, 0),
            (0x18, 8, 0),
            (0x20, 4, 0),
            *((offset, 8, 0) for offset in range(0x28, 0x78, 8)),
            (0x80, 8, 0),
            (0x8A, 1, 0),
        ):
            self.write(self.field(offset), width, value)
        self.invoke(0x141712B50, self.field(0xA0), 512)
        self.invoke(0x141712B50, self.field(0x110), 512)
        for offset, width, value in (
            *(
                (offset, 8, 0)
                for offset in (0x180, 0x188, 0x190, 0x198, 0x1A0, 0x1A8, 0x210, 0x218, 0x220, 0x238)
            ),
            (0x280, 4, _U32),
            (0x288, 8, 0),
            (0x290, 8, 0),
            (0x298, 8, 0),
            (0x490, 1, 0),
            (0x518, 8, 0),
            (0x520, 8, 0),
            (0x528, 8, 0),
            (0x530, 8, 0x20),
            (0x538, 4, 100),
            (0x53C, 8, 100),
            (0x544, 4, _U32),
            (0x548, 4, 100),
            (0x550, 4, 0x10100),
            (0x554, 4, 10000),
            (0x558, 1, 0),
            (0x55C, 4, _U32 - 1),
            (0x560, 8, _EMPTY),
            (0x568, 8, 0),
            (0x570, 8, 0),
            (0x578, 1, 0),
            (0x57C, 8, 0),
            (0x588, 8, 0),
            (0x590, 1, 0),
            (0x598, 8, 0),
            (0x5A0, 1, 0),
            (0x5A4, 4, 6),
            (0x5A8, 8, 2),
            (0x62C, 4, 0),
            (0x630, 8, _EMPTY),
            (0x638, 8, 0),
            (0x640, 8, 0),
            (0x64C, 4, 0),
            (0x65C, 4, 0),
        ):
            self.write(self.field(offset), width, value)
        self.invoke(0x140C2AE90, self.field(0x660))
        for offset, width, value in (
            (0x6B0, 8, 0),
            (0x6B8, 8, 0),
            (0x6C0, 8, 0),
            (0x6C8, 4, _U32),
            (0x6CC, 4, 300),
        ):
            self.write(self.field(offset), width, value)
        self.write(self.field(0x648), 4, self.read(index_pointer, 4))
        self.write(self.field(8), 8, world)
        self.write(self.field(0x5A4), 4, self.read(0x143DAE278, 4))
        self.write(self.field(0x244), 8, _U64)
        self.write(self.field(0x510), 1, 0)
        literal = 0x1436A02E4 if self.read(self.field(0x10), 4) == 3 else 0x1436A02F8
        self.write(self.field(0x54C), 4, self.read(literal, 4))
        self.write(self.field(0x1B0), 8, 0)
        self.write(self.field(0x1B8), 1, 0)
        pointer = self.invoke(0x142D6BA78, 24, result=True)
        self.write(self.local(0x38), 8, pointer)
        if pointer:
            self.write(pointer, 16, 0)
            self.write(pointer + 16, 8, 0)
            pointer = self.invoke(0x14115D200, pointer, self.address, 100, result=True)
        self.write(self.field(0x78), 8, pointer)
        pointer = self.invoke(0x142D6BA78, 32, result=True)
        self.write(self.local(0x38), 8, pointer)
        if pointer:
            self.write(pointer, 16, 0)
            self.write(pointer + 16, 16, 0)
            pointer = self.invoke(0x141143DF0, pointer, self.address, result=True)
        self.write(self.field(0x80), 8, pointer)
        self.marker(first=True, manual=True, cleanup="inline")

    def relations(self) -> None:
        count = self.invoke(0x141603EF0, self.read(self.field(8)), result=True)
        requested = _signed(count & _U32, 4) & _U64
        self.write(self.local(0x30), 8, requested)
        header = self.field(0x180)
        begin = self.read(header)
        end = self.read(header + 8)
        self.write(self.local(0xC0), 8, end)
        old_length = (end - begin) & _U64
        self.write(self.local(0xB8), 8, old_length)
        if requested < old_length:
            self.write(header + 8, 8, begin + requested)
        elif requested > old_length:
            capacity = (self.read(header + 16) - begin) & _U64
            if requested > capacity:
                limit = (1 << 63) - 1
                self.write(self.local(0xC0), 8, limit)
                if requested > limit:
                    self.invoke(0x1402DBEA0)
                    raise UnresolvedReplayTaskRebuild(
                        "Player length error returned before body end",
                    )
                replacement_capacity = limit
                if capacity <= limit - (capacity >> 1):
                    replacement_capacity = max(capacity + (capacity >> 1), requested)
                    self.write(self.local(0xC0), 8, replacement_capacity)
                replacement = self.invoke(0x1402A94D0, replacement_capacity, result=True)
                new_count = self.read(self.local(0x30))
                old_count = self.read(self.local(0xB8))
                self.invoke(0x142D6E3B7, replacement + old_count, 0, new_count - old_count)
                current_begin = self.read(header)
                current_end = self.read(header + 8)
                self.invoke(0x142D6E3DB, replacement, current_begin, current_end - current_begin)
                current_capacity = self.read(self.local(0xC0))
                current_size = self.read(self.local(0x30))
                self.invoke(0x1402DBEF0, header, replacement, current_size, current_capacity)
            else:
                added = requested - old_length
                self.invoke(0x142D6E3B7, end, 0, added)
                self.write(header + 8, 8, self.read(self.local(0xC0)) + added)
        cursor = self.read(header)
        end = self.read(self.field(0x188))
        self.write(self.local(0xC0), 8, end)
        if cursor != end:
            while True:
                self.zero_result(0xE8)
                self.input(cursor, 1, output=self.local(0xE8), result=False)
                self.zero_result(0x80)
                self.write(self.local(0x110), 1, 1)
                if self.read(self.local(0x100)):
                    self.invoke(0x140900ED0, self.local(0xE8), _FILE, 0x11E, 0x1432F4B28)
                self.invoke(0x1409076B0, self.local(0x80), self.local(0xE8))
                self.inline_cleanup(0xE8)
                self.adopt(self.local(0x80), end_first=True)
                self.inline_cleanup(0x80)
                self.check()
                cursor = cursor + 1 & _U64
                if cursor == self.read(self.local(0xC0)):
                    break
        self.write(self.local(0xB8), 4, _U32)
        held_count = self.read(self.local(0x30))
        self.invoke(0x140C4DDE0, self.field(0x198), held_count, self.local(0xB8))
        table = self.read(self.stream)
        target = self.read(table + 24)  # Selected before this current version read.
        if self.version() >= 0x3D0000:
            destination = self.read(self.field(0x198))
            returned = self.input(destination, held_count * 4, selected=target)
            self.finish(returned, manual=True, cleanup="inline")
        else:
            returned = self.input(self.local(0xE8), 36, selected=target)
            self.finish(returned, manual=True, cleanup="inline")
            destination = self.read(self.field(0x198))
            self.invoke(0x142D6E3B1, destination, self.local(0xE8), held_count * 4)
        self.read_field(0x1EC, 4, manual=True, cleanup="inline")
        self.read_field(0x1F0, 1, manual=True, cleanup="inline")
        returned = self.invoke(
            0x140A1D990, self.field(0x630), self.local(0x40), self.stream, result=True
        )
        self.finish(returned, manual=True, cleanup="inline")
        self.marker(1, 0x1432F2690, cleanup="inline")
        self.read_field(0x90, 4)
        self.marker(2, 0x1432F26A0)

    def zero_auxiliary(self, pointer: int, chosen: int) -> None:
        cursor = 0
        count = _signed(self.read(self.local(0xB8), 4), 4)
        if count > 0 and count >= 4:
            last = pointer + _signed((count - 1) & _U32, 4) * 4 & _U64
            member = self.field(0x588)
            if pointer > member or last < member:
                rounded = count - (count & 3)
                cursor = 4
                while _signed(cursor, 4) < rounded:
                    cursor = cursor + 4 & _U32
                numerator = (rounded + 3) & _U32
                correction = 3 if _signed(numerator, 4) < 0 else 0
                quotient = _signed((numerator + correction) & _U32, 4) >> 2
                self.invoke(0x142D6E3B7, pointer, 0, (quotient << 4) & _U64 & ~3)
        index = _signed(cursor, 4)
        if index < chosen:
            if chosen - index >= 4:
                limit = chosen - 3
                while True:
                    for delta in (0, 1, 2, 3):
                        current = self.read(self.field(0x588))
                        self.write(current + (index + delta) * 4, 4, 0)
                    index += 4
                    if index >= limit:
                        break
            while index < chosen:
                current = self.read(self.field(0x588))
                self.write(current + index * 4, 4, 0)
                index += 1

    def copy_auxiliary(self, chosen: int) -> None:
        source = self.imported(0x143199DC0, chosen, 4, result=True)
        self.write(self.local(0x30), 8, source)
        width = _signed(self.read(self.field(0x90), 4), 4) * 4 & _U64
        self.finish(self.input(source, width))
        cursor = 0
        count = _signed(self.read(self.local(0xB8), 4), 4)
        if count > 0:
            source = self.read(self.local(0x30))
            if count >= 4:
                destination = self.read(self.field(0x588))
                last_destination = destination + _signed((count - 1) & _U32, 4) * 4 & _U64
                last_source = source + _signed((count - 1) & _U32, 4) * 4 & _U64
                member = self.field(0x588)
                if (destination > last_source or last_destination < source) and (
                    destination > member or last_destination < member
                ):
                    self.invoke(0x142D6E3B1, destination, source, count * 4)
                    current_count = _signed(self.read(self.local(0xB8), 4), 4)
                    cursor = 1
                    while _signed(cursor, 4) < current_count:
                        cursor = cursor + 1 & _U32
                    source = self.read(self.local(0x30))
        else:
            source = self.read(self.local(0x30))
        index = _signed(cursor, 4)
        if index < chosen:
            if chosen - index >= 4:
                groups = ((chosen - index - 4) >> 2) + 1
                for _ in range(groups):
                    for delta in (0, 1, 2, 3):
                        destination = self.read(self.field(0x588))
                        value = self.read(source + (index + delta) * 4, 4)
                        self.write(destination + (index + delta) * 4, 4, value)
                    index += 4
            while index < chosen:
                destination = self.read(self.field(0x588))
                value = self.read(source + index * 4, 4)
                self.write(destination + index * 4, 4, value)
                index += 1
        if source:
            self.imported(0x143199DD0, source)

    def encoded_default(self, threshold: int, offset: int, word: int) -> None:
        if _signed(self.read(self.field(0x90), 4), 4) > threshold:
            return
        table = self.read(self.field(0x98))
        self.write(self.local(0x38), 4, word)
        self.write(self.local(0x30), 8, self.read(self.local(0x38)))
        self.cipher()
        self.write(self.local(0x38), 8, self.read(self.local(0x30)))
        self.write(table + offset, 8, self.read(self.local(0x38)))

    def resources(self) -> None:
        original_count = _signed(self.read(self.field(0x90), 4), 4)
        if original_count <= 0:
            self.write(self.field(0x98), 8, 0)
            return
        world = self.read(self.field(8))
        descriptor = self.read(self.read(world + 0x110))
        minimum = max(_signed(self.read(descriptor + 0x30, 2), 2), 601)
        self.write(self.local(0xC0), 4, minimum)
        chosen = max(minimum, original_count)
        self.write(self.local(0xB8), 4, chosen)
        source = self.imported(0x143199DC0, chosen, 4, result=True)
        table = self.imported(0x143199DC0, chosen, 8, result=True)
        self.write(self.field(0x98), 8, table)
        width = _signed(self.read(self.field(0x90), 4), 4) * 4 & _U64
        self.finish(self.input(source, width))
        self.write(self.local(0x78), 8, _CIPHER[0])
        self.write(self.local(0x38), 8, _CIPHER[1])
        counter = 0
        index = 0
        while counter < chosen:
            table = self.read(self.field(0x98))
            self.write(self.local(0x70), 4, self.read(source + counter * 4, 4))
            self.write(self.local(0x30), 8, self.read(self.local(0x70)))
            self.cipher(local_keys=True)
            self.write(self.local(0x30), 8, self.read(self.local(0x30)))
            self.write(table + _signed(index, 4) * 8, 8, self.read(self.local(0x30)))
            index = index + 1 & _U32
            counter += 1
        if source:
            self.imported(0x143199DD0, source)
        auxiliary = self.imported(0x143199DC0, chosen, 4, result=True)
        self.write(self.field(0x588), 8, auxiliary)
        self.zero_auxiliary(auxiliary, chosen)
        if self.version() >= 0x140F5C:
            self.copy_auxiliary(chosen)
        defaults = (
            (0xBD, 0x5E8, 0x3F800000),
            (0xBE, 0x5F0, 0x3F800000),
            (0xBF, 0x5F8, 0x41A00000),
            (0xE6, 0x730, 0),
            (0xE7, 0x738, 0),
            (0xE8, 0x740, 0),
            (0xE9, 0x748, 0),
            (0xEA, 0x750, 0xBF800000),
            (0xEB, 0x758, 0),
            (0xED, 0x768, 0),
            (0xEE, 0x770, 0xBF800000),
            (0xEF, 0x778, 0xBF800000),
            (0xF0, 0x780, 0),
            (0xFB, 0x7D8, 0),
            (0xFC, 0x7E0, 0),
            (0xFD, 0x7E8, 0),
            (0x10E, 0x870, 0x3F000000),
            (0x10F, 0x878, 0x3F000000),
            (0x110, 0x880, 0),
            (0x111, 0x888, 0),
        )
        for threshold, offset, word in defaults:
            self.encoded_default(threshold, offset, word)
        if self.version() < 0x3D0000:
            self.legacy_resources()
            self.invoke(0x140FDDCE0, self.address, self.read(self.local(0xB8), 4))
        minimum = _signed(self.read(self.local(0xC0), 4), 4)
        if minimum > _signed(self.read(self.field(0x90), 4), 4):
            self.write(self.field(0x90), 4, minimum)
        table = self.read(self.field(0x98))
        self.write(self.local(0x30), 8, self.read(table + 0x58))
        self.cipher(decode=True)
        self.write(self.local(0x38), 8, self.read(self.local(0x30)))
        self.write(self.field(0x62C), 4, self.read(self.local(0x38), 4))

    def legacy_resources(self) -> None:
        if _signed(self.read(self.field(0x90), 4), 4) > 0xD9:
            table = self.read(self.field(0x98))
            self.write(self.local(0x30), 8, self.read(table + 0x6C8))
            self.cipher(decode=True)
            decoded = self.read(self.local(0x30))
            self.write(self.local(0x38), 8, decoded)
            value = decoded & 0xFFFF
            table = self.read(self.field(0x98))
            self.write(self.local(0x38), 4, value)
        else:
            value = 0
            table = self.read(self.field(0x98))
            self.write(self.local(0x38), 4, 0)
        self.write(self.local(0x30), 8, self.read(self.local(0x38)))
        self.cipher()
        self.write(self.local(0x38), 8, self.read(self.local(0x30)))
        encoded = self.read(self.local(0x38))
        self.write(self.local(0x38), 4, value)
        self.write(table + 0x8E8, 8, encoded)
        table = self.read(self.field(0x98))
        self.write(self.local(0x30), 8, self.read(self.local(0x38)))
        self.cipher()
        self.write(self.local(0x38), 8, self.read(self.local(0x30)))
        self.write(table + 0x8F0, 8, self.read(self.local(0x38)))
        table = self.read(self.field(0x98))
        self.write(self.local(0x38), 4, 0)
        self.write(self.local(0x30), 8, self.read(self.local(0x38)))
        self.cipher()
        self.write(self.local(0x38), 8, self.read(self.local(0x30)))
        self.write(table + 0x6C8, 8, self.read(self.local(0x38)))

    def basic_and_named_fields(self) -> None:
        self.marker(manual=True, cleanup="inline")
        self.read_field(0x228, 4, cleanup="inline")
        self.read_field(0x22C, 4)
        pointer = self.invoke(0x142D6C268, 80, result=True)
        self.write(self.field(0x238), 8, pointer)
        if self.version() >= 0xB9EB8:
            self.read_field(0x240, 4)
            count = self.read(self.field(0x240), 4)
            if ((count - 1) & _U32) <= 9 and _signed(count, 4) > 0:
                index = 0
                while True:
                    held_index = _signed(index, 4)
                    destination = self.read(self.field(0x238)) + held_index * 8
                    self.finish(self.input(destination, 4), cleanup="pair")
                    destination = self.read(self.field(0x238)) + 4 + held_index * 8
                    self.finish(self.input(destination, 4), cleanup="pair")
                    index = index + 1 & _U32
                    if _signed(index, 4) >= _signed(self.read(self.field(0x240), 4), 4):
                        break
        else:
            self.write(self.field(0x240), 4, 0)
        for offset, width in ((0x230, 2), (0x232, 2), (0x88, 1)):
            self.read_field(offset, width)
        if self.version() >= 0x42B333:
            self.initialize_string()
            self.zero_result(0xE8)
            self.invoke(0x140A1BDF0, self.local(0xD0), self.local(0xE8), self.stream)
            self.secondary(0x20C, 0x1432F4BA0)
            if self.read(self.output + 24):
                self.invoke(0x140A1B220, self.local(0xD0))
                raise _ReturnedStatus
            value = self.invoke(0x140F6A4B0, self.local(0xD0), result=True)
            self.invoke(0x14174A0C0, self.address, value)
            self.invoke(0x140A1B220, self.local(0xD0))
        else:
            self.typed(0x141711C20, 0x212, 0x1432F4BB4, self.local(0xC0))
            value = self.invoke(0x140F6BCE0, self.read(self.local(0xC0), 4), result=True)
            self.invoke(0x14174A0C0, self.address, value)
        if self.version() >= 0x14170A:
            self.zero_result(0xE8)
            self.invoke(0x140E33410, self.local(0xE8), self.stream, self.field(0x6B0))
            self.secondary(0x21B, 0x1432F4BC0)
            self.check()
        self.read_field(0x89, 1)
        self.read_field(0x8B, 1)
        bit = self.read(self.field(0x8B), 1) >> 1 & 1
        self.write(self.field(0x8C), 1, bit)
        if bit:
            self.write(self.field(0x8B), 1, 0)
        self.marker()
        self.typed(0x140DAF040, 0x230, 0x1432F4BD0, self.local(0xC8))
        self.invoke(0x14174A2C0, self.address, self.read(self.local(0xC8), 1))
        self.marker()
        self.read_field(0x5A4, 4)
        self.read_field(0x5A8, 4)

    def initialize_string(self) -> None:
        self.write(self.local(0xD0), 16, 0)
        self.write(self.local(0xD0), 8, _EMPTY)
        self.write(self.local(0xD8), 8, 0)
        self.write(self.local(0xE0), 8, 0)

    def legacy_groups(self) -> None:
        version = self.version()
        for threshold in (0xCC28F, 0x190A3D, 0xD0000):
            if version < threshold or (threshold != 0xD0000 and version >= 0x1A30A3):
                continue
            self.finish(self.input(self.local(0xB8), 4))
            index = 0
            if _signed(self.read(self.local(0xB8), 4), 4) > 0:
                while True:
                    self.finish(self.input(self.local(0xC0), 4), cleanup="pair")
                    if threshold == 0xD0000:
                        self.invoke(0x140B53800, self.field(0x518), self.local(0xC0))
                    index = index + 1 & _U32
                    if _signed(index, 4) >= _signed(self.read(self.local(0xB8), 4), 4):
                        break
            # Source refreshes EAX only after a group that was actually entered.
            version = self.version()
        if version >= 0x1A30A3:
            return
        width = 0x5DC
        for threshold, candidate in (
            (0xCA666, 0x4650),
            (0xC8000, 0xAF0),
            (0xC51EB, 0x960),
            (0xBF333, 0x76C),
            (0xBA666, 0x708),
            (0xB828F, 0x6A4),
        ):
            if version >= threshold:
                width = candidate
                break
        for count in (width, 200, width, 200):
            self.finish(self.input(self.local(0x120), count))
        if self.version() < 0x1A30A3:
            for _ in range(4):
                self.finish(self.input(self.local(0x120), 2))

    def preference_fields(self) -> None:
        for offset in (0x5E0, 0x5E4, 0x5E8, 0x5EC, 0x5F0, 0x5F4):
            self.read_field(offset, 4)
        if self.version() >= 0xACF5C:
            self.read_field(0x5F8, 4)
        else:
            self.write(self.field(0x5F8), 4, 0)
        for offset in (0x5FC, 0x60C, 0x61C):
            self.read_field(offset, 16)
        if self.version() >= 0xA828F:
            for offset in range(0x24C, 0x26C, 4):
                self.read_field(offset, 4)
        else:
            self.write(self.field(0x264), 4, 0)
        version = self.version()
        if version >= 0x1A2147:
            self.read_field(0x26C, 4)
            version = self.version()
        if version >= 0xB7333:
            self.read_field(0x538, 4)
            self.read_field(0x53C, 4)
            self.read_field(0x540, 1)
            version = self.version()
            if version >= 0xC3333:
                self.read_field(0x541, 1)
                self.read_field(0x542, 1)
                version = self.version()
        if version >= 0xC5C28:
            for target, line, detail, offset in (
                (0x140D07EE0, 0x2D4, 0x1432F4BE0, 0x543),
                (0x140B81D60, 0x2D5, 0x1432F4BF8, 0x544),
                (0x140B81D60, 0x2D6, 0x1432F4C10, 0x548),
            ):
                self.typed(target, line, detail, self.field(offset))
            version = self.version()
        if version >= 0xCAB85:
            self.typed(0x140D07EE0, 0x2DA, 0x1432F4C30, self.field(0x551))
            if self.version() >= 0xD0A3D:
                self.typed(0x140D07EE0, 0x2DD, 0x1432F4C48, self.field(0x552))
            self.typed(0x140DAF040, 0x2DF, 0x1432F4C60, self.field(0x553))
            version = self.version()
        if version >= 0xD028F:
            self.typed(0x140B81D60, 0x2E3, 0x1432F4C78, self.field(0x554))
            version = self.version()
        if version >= 0xC91EB:
            self.named_identifier()
            version = self.version()
        if version >= 0xC7333:
            self.typed(0x141712390, 0x2F7, 0x1432F4CA0, self.field(0x14))

    def named_identifier(self) -> None:
        self.initialize_string()
        self.typed(0x140B81D60, 0x2E9, 0x1432F4C90, self.local(0xC0), check=False)
        if self.read(self.output + 24):
            self.invoke(0x140A1B220, self.local(0xD0))
            raise _ReturnedStatus
        returned = self.invoke(
            0x140A1CF00, self.local(0xD0), self.local(0x40), self.stream, result=True
        )
        self.finish(returned, check=False)
        if self.read(self.output + 24):
            self.invoke(0x140A1B220, self.local(0xD0))
            raise _ReturnedStatus
        identifier = self.read(self.local(0xC0), 4)
        if identifier != 0xFFFFFFFE:
            self.write(self.field(0x558), 1, 1)
            self.write(self.field(0x55C), 4, identifier)
            self.invoke(0x140A1A7E0, self.field(0x560), 0)
        else:
            self.write(self.local(0xE8), 8, _EMPTY)
            self.write(self.local(0xF0), 8, 0)
            self.write(self.local(0xF8), 8, 0)
            self.invoke(0x140A15B60, self.local(0xE8), self.local(0xD0))
            self.invoke(0x1416607B0, self.field(0x558), self.local(0xE8))
        self.invoke(0x140A1B220, self.local(0xD0))

    def final_fields(self) -> None:
        self.invoke(0x1417394D0, self.address)
        version = self.version()
        if version >= 0xBB851:
            self.read_field(0x48C, 4)
            if _signed(self.read(self.field(0x48C), 4), 4) > 0:
                self.write(self.local(0xB8), 4, 0)
                self.finish(self.input(self.local(0xB8), 4))
                value = _signed(self.read(self.local(0xB8), 4), 4)
                self.write(self.field(0x2A0), 8, value)
                self.read_field(0x488, 4)
                if _signed(self.read(self.field(0x48C), 4), 4) > 0:
                    index = 0
                    cursor = self.field(0x2A8)
                    while True:
                        self.finish(self.input(self.local(0xB8), 4))
                        value = _signed(self.read(self.local(0xB8), 4), 4)
                        self.write(cursor, 8, value)
                        index = index + 1 & _U32
                        cursor = cursor + 8 & _U64
                        if _signed(index, 4) >= _signed(self.read(self.field(0x48C), 4), 4):
                            break
            version = self.version()
        for threshold, target, line, detail, offset in (
            (0xCB851, 0x140B81E60, 0x318, 0x1432F4CB0, 0x54C),
            (0xCDC28, 0x140D07EE0, 0x31C, 0x1432F4CC8, 0x550),
            (0xD170A, 0x140D07EE0, 0x320, 0x1432F4CE0, 0x578),
            (0xD1EB8, 0x141712290, 0x324, 0x1432F4CF0, 0x57C),
            (0xD547A, 0x140B81D60, 0x328, 0x1432F4D00, 0x580),
            (0x1907AE, 0x140D07EE0, 0x32C, 0x1432F4D20, 0x590),
            (0x191999, 0x140D07EE0, 0x330, 0x1432F4D38, 0x5A0),
        ):
            if version >= threshold:
                self.typed(target, line, detail, self.field(offset))
                # There is no version fetch after the last typed field.
                if threshold != 0x191999:
                    version = self.version()
        returned = self.invoke(0x141712AE0, self.local(0x30), self.field(0x20), result=True)
        self.invoke(0x141711BF0, self.field(0x18), returned)
        pointer = self.read(self.local(0x30))
        if pointer:
            self.invoke(0x141727C80, self.local(0x30), pointer)
        self.marker()
        self.write(self.field(0x5DC), 1, 0)
        self.write(self.field(0x5B0), 16, 0)
        self.write(self.field(0x5C0), 16, 0)
        self.write(self.field(0x5D0), 8, 0)
        self.write(self.field(0x5D8), 4, 0)


def construct_replay_saved_base_player(
    context: ReplayTaskRebuildStorage,
    address: int,
    output: int,
    stream: int,
    world: int,
    index_pointer: int,
    *,
    calls: ReplayTaskRebuildCalls,
    atomics: ReplayUnitAIMapAtomics,
    bind_local: LocalBinding,
    scratch: bytes,
    floating: ReplayPlayerSupportFloatingCalls,
    mxcsr: int = 0x1F80,
    imports: ReplayTaskRebuildCalls | None = None,
) -> int:
    """Complete normal141713f70, with actual reached children and held return.

    The whole4770-byte logical data frame is caller-seeded and live through the
    last marker/reset. Its overlapping scalar/QWORD/Result/DEString/discard
    areas are real shared backing. Scratch bytes that the original leaves
    unassigned are explicit inputs. RBP=frame+100. Native argument homes,
    cookies/register saves and their aliases are excluded. In particular the
    fifth operand is a held effective pointer, not a native47f0 home binding.

    Current version words use signed32 comparisons at their original fetch
    phases; passed Input/Result/current virtuals and metadata children must
    really run or refuse when reached. No failed child is converted to success,
    and no rollback/EH cleanup is synthesized. Reached returned status preserves
    the exact preceding normal cleanup and returns held address. The genuine
    marker XMM3/stack-BYTE ABI and default masked nearest-even MXCSR1f80 are
    explicit; no host floating-point operations are used here. Current IAT
    calloc/free targets are read once per source call and routed terminally.
    """
    _validate(context, calls, address, output, stream, world, index_pointer)
    terminal = calls if imports is None else imports
    _validate(context, terminal)
    if (
        not isinstance(atomics, ReplayUnitAIMapAtomics)
        or not isinstance(floating, ReplayPlayerSupportFloatingCalls)
        or not callable(bind_local)
    ):
        raise ValueError("actual atomics/local/mixed-FP providers required")
    if type(scratch) is not bytes or len(scratch) != 0x4770:
        raise ValueError("explicit4770-byte Base Player logical frame required")
    if type(mxcsr) is not int or mxcsr != 0x1F80:
        raise ValueError("Base Player normal port requires MXCSR1f80 profile")
    with _local(memoryview(bytearray(scratch)), bind_local) as frame:
        state = _PlayerConstruction(
            context, calls, terminal, atomics, floating, address, output, stream, frame
        )
        try:
            state.initial_fields(world, index_pointer)
            state.relations()
            state.resources()
            state.basic_and_named_fields()
            state.legacy_groups()
            state.preference_fields()
            state.final_fields()
        except _ReturnedStatus:
            pass
    return address


def bind_replay_saved_base_player(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    *,
    atomics: ReplayUnitAIMapAtomics,
    bind_local: LocalBinding,
    scratch: bytes,
    floating: ReplayPlayerSupportFloatingCalls,
    mxcsr: int = 0x1F80,
    imports: ReplayTaskRebuildCalls | None = None,
) -> ReplayTaskRebuildCalls:
    """Bind only141713f70; every descendant remains an actual composed call."""
    _validate(context, calls)
    terminal = calls if imports is None else imports
    _validate(context, terminal)

    def dispatch(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        if target != 0x141713F70:
            if calls.call is None:
                raise UnresolvedReplayTaskRebuild(f"reached{target:x} unavailable")
            return calls.call(target, args, data)
        if len(args) != 5 or data is not None:
            raise ValueError("malformed Base Player saved-constructor call")
        return construct_replay_saved_base_player(
            context,
            *args,
            calls=bound,
            atomics=atomics,
            bind_local=bind_local,
            scratch=scratch,
            floating=floating,
            mxcsr=mxcsr,
            imports=terminal,
        )

    bound = ReplayTaskRebuildCalls(dispatch)
    return bound
