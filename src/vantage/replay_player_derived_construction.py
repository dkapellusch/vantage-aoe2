"""Build54800 complete12089B1416c2440 derived Player saved constructor.

Only authored Python executes. Every reached parent, Input, constructor,
resource/AI/map/descriptor operation, allocation and cleanup remains a real
required child. The D8-byte coherent logical frame is supplied, including all
unassigned bytes. Physical argument homes, register saves, cookie/EH/fault and
concurrency parity are excluded. Distinct World identities are never unified.
"""

from __future__ import annotations

from dataclasses import dataclass

from vantage.replay_player_construction_support import (
    ReplayPlayerMarkerCall,
    ReplayPlayerSupportFloatingCalls,
)
from vantage.replay_task_group_storage import LocalBinding
from vantage.replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
    _call,
    _read,
    _signed,
    _unsigned,
    _write,
)
from vantage.replay_unit_ai_base import _validate
from vantage.replay_unit_ai_construction import _local
from vantage.replay_unit_ai_map import ReplayUnitAIMapAtomics, _atomic

_U32, _U64 = (1 << 32) - 1, (1 << 64) - 1
_VERSION = 0x1440A0D94
_FILE = 0x1432F2520
_CIPHER = (0xA9834B738A7DD167, 0x042AC42976FCCEF5, 0xC22D6B496D833977, 0x6AE24D3352F04511)


class _ReturnedStatus(Exception):
    """Reached, normally cleaned nonzero output status; return held Player."""


@dataclass(slots=True)
class _DerivedConstruction:
    context: ReplayTaskRebuildStorage
    calls: ReplayTaskRebuildCalls
    atomics: ReplayUnitAIMapAtomics
    floating: ReplayPlayerSupportFloatingCalls
    address: int
    output: int
    stream: int
    frame: int
    marker_word: int = 0
    decrement: int = _U32

    def read(self, address: int, width: int = 8) -> int:
        return _read(self.context, address, width)

    def write(self, address: int, width: int, value: int) -> None:
        _write(self.context, address, width, value)

    def local(self, offset: int) -> int:
        return (self.frame + offset) & _U64

    def field(self, offset: int) -> int:
        return (self.address + offset) & _U64

    def invoke(self, target: int, *args: int, result: bool = False) -> int:
        return _call(self.calls, target, args, width=8 if result else None)

    def version(self) -> int:
        return _signed(self.read(_VERSION, 4), 4)

    def check(self) -> None:
        if self.read(self.output + 24):
            raise _ReturnedStatus

    def release(self, control: int, *, slot: bool = False, weak_capture: bool = False) -> None:
        if not control or _atomic(self.atomics, control + 8, self.decrement) != 1:
            return
        self.invoke(self.read(self.read(control)), control)
        # Four loop blocks explicitly spill/reload the held control through30.
        if slot:
            control = self.read(self.local(0x30))
        previous = _atomic(self.atomics, control + 12, self.decrement)
        if weak_capture:
            self.decrement = previous  # Actual XADD destination R12D,4219.
        if previous == 1:
            self.invoke(self.read(self.read(control) + 8), control)

    def cleanup(
        self,
        offset: int,
        kind: str = "inline",
        *,
        spill_control: bool = False,
        weak_capture: bool = False,
    ) -> None:
        result = self.local(offset)
        if kind == "pair":
            self.invoke(0x1408EE150, result + 24)
        elif kind == "finalize":
            self.invoke(0x140900620, result)
            return
        else:
            control = self.read(result + 32)
            if spill_control:
                self.write(self.local(0x30), 8, control)
            self.release(control, slot=spill_control, weak_capture=weak_capture)
        self.invoke(0x1402BD7F0, result)

    def adopt(self, source: int, *, spill_source: bool = False) -> None:
        if spill_source:
            self.write(self.local(0x30), 8, source)
        self.write(source + 40, 1, 1)
        self.invoke(0x14090D270, self.output + 24, source + 24)
        if spill_source:
            source = self.read(self.local(0x30))
        if self.output != source:
            begin = self.read(source)
            end = self.read(source + 8)
            count = (_signed((end - begin) & _U64, 8) >> 5) & _U64
            self.invoke(0x1402B9080, self.output, begin, count)
        self.write(self.output + 40, 1, 0)

    def finish(
        self,
        returned: int,
        offset: int,
        *,
        manual: bool = False,
        cleanup: str = "inline",
        spill: bool = False,
        weak_capture: bool = False,
        check: bool = True,
    ) -> None:
        if manual:
            self.adopt(returned, spill_source=spill)
        else:
            self.invoke(0x140991CE0, self.output, returned)
        self.cleanup(offset, cleanup, spill_control=spill, weak_capture=weak_capture)
        if check:
            self.check()

    def input(
        self,
        destination: int,
        width: int,
        *,
        offset: int = 0x38,
        cleanup: str = "finalize",
        manual: bool = False,
        spill: bool = False,
        weak_capture: bool = False,
    ) -> None:
        target = self.read(self.read(self.stream) + 24)
        returned = self.invoke(
            target, self.stream, self.local(offset), destination, width, result=True
        )
        self.finish(
            returned, offset, manual=manual, cleanup=cleanup, spill=spill, weak_capture=weak_capture
        )

    def read_field(
        self,
        field: int,
        width: int,
        *,
        offset: int = 0x38,
        cleanup: str = "finalize",
        manual: bool = False,
        weak_capture: bool = False,
    ) -> None:
        self.input(
            self.field(field),
            width,
            offset=offset,
            cleanup=cleanup,
            manual=manual,
            weak_capture=weak_capture,
        )

    def marker(
        self,
        *,
        offset: int = 0x38,
        first: bool = False,
        cleanup: str = "finalize",
        manual: bool = False,
    ) -> None:
        expected = self.read(0x1440A0EA8, 1)
        self.write(self.local(0x20), 1, expected)
        if first:
            self.marker_word = self.read(0x1432ED700, 4)
        request = ReplayPlayerMarkerCall(
            self.local(offset), self.stream, 0x1432F2510, self.marker_word, expected
        )
        if self.floating.call is None:
            raise UnresolvedReplayTaskRebuild("reached14162cd70 mixed-FP provider unavailable")
        returned = self.floating.call(0x14162CD70, request)
        if returned is None:
            raise ValueError("Player marker must return raw RAX")
        _unsigned(returned, 8, "Player marker raw RAX")
        self.finish(returned, offset, manual=manual, cleanup=cleanup)

    def typed(
        self,
        target: int,
        line: int,
        detail: int,
        destination: int,
        *,
        offset: int = 0x38,
        cleanup: str = "finalize",
        manual: bool = False,
        check: bool = True,
    ) -> None:
        self.write(self.local(0x28), 8, destination)
        self.write(self.local(0x20), 8, self.stream)
        returned = self.invoke(
            target, self.local(offset), _FILE, line, detail, self.stream, destination, result=True
        )
        self.finish(returned, offset, manual=manual, cleanup=cleanup, check=check)

    def zero_result(self) -> None:
        # Native2f08/3010/485c deliberately writes overlapping spans in this order.
        for offset, width in ((0xB0, 16), (0x90, 16), (0xA0, 16), (0xB0, 8), (0xB8, 1)):
            self.write(self.local(offset), width, 0)

    def allocate(self, size: int, *, spill: int = 0x30) -> int:
        value = self.invoke(0x142D6BA78, size, result=True)
        self.write(self.local(spill), 8, value)
        return value

    def zero_allocation(self, address: int, size: int) -> None:
        for offset in range(0, size // 16 * 16, 16):
            self.write(address + offset, 16, 0)
        if size % 16:
            self.write(address + size // 16 * 16, size % 16, 0)

    def initial(self, world: int, index_pointer: int) -> None:
        self.write(self.local(0x30), 8, world)
        self.write(self.local(0x70), 8, self.address)
        self.write(self.local(0x80), 4, 0)
        self.write(self.local(0x68), 4, 0)
        self.write(self.local(0x88), 4, self.read(index_pointer, 4))
        self.write(self.local(0x20), 8, self.local(0x88))
        self.invoke(0x141713F70, self.address, self.output, self.stream, world, self.local(0x88))
        self.write(self.address, 8, 0x1432F2128)
        for offset, width in (
            (0x6D0, 8),
            (0x6D8, 8),
            (0x6E0, 8),
            (0x6E8, 1),
            (0x6EC, 8),
            (0x6F4, 4),
            (0x6F8, 1),
            (0x6FC, 8),
            (0x708, 8),
            (0x710, 8),
            (0x718, 8),
        ):
            self.write(self.field(offset), width, 0)
        for offset in range(0x720, 0xD20, 0x100):
            self.invoke(0x142D6E3B7, self.field(offset), 0, 0x100)
        for offset, width in (
            (0xD20, 8),
            (0xD28, 8),
            (0xD30, 8),
            (0xD38, 8),
            (0xD40, 8),
            (0xD48, 8),
            (0xD50, 4),
            (0xD78, 8),
            (0xD80, 2),
            (0xD82, 8),
            (0xD8A, 1),
            (0xD8B, 8),
            (0xD93, 1),
            (0x1220, 16),
            (0x1230, 16),
            (0x1240, 4),
            (0x1244, 16),
            (0x1254, 16),
            (0x1264, 4),
            (0x1268, 8),
            (0x1270, 1),
            (0x1274, 16),
            (0x1284, 4),
            (0x1288, 16),
            (0x1298, 4),
            (0x12A0, 8),
            (0x12A8, 8),
            (0x12B0, 4),
            (0x12D8, 8),
            (0x12E0, 8),
            (0x12F0, 8),
            (0x12F8, 1),
            (0x12FC, 4),
            (0x1310, 8),
            (0x1318, 8),
            (0x1320, 8),
            (0x1328, 8),
        ):
            self.write(self.field(offset), width, 0)
        self.invoke(0x140C2AE90, self.field(0x1338))
        for offset, width, value in (
            (0x13AE, 1, 0),
            (0x13B0, 8, 0),
            (0x13B8, 8, 0),
            (0x13C0, 8, 0),
            (0x13C8, 8, 0x20),
            (0x13D0, 8, 0),
            (0x13D8, 8, 0),
            (0x13E0, 8, 0),
            (0x13E8, 8, 0),
        ):
            self.write(self.field(offset), width, value)
        self.marker(offset=0x90, first=True, manual=True, cleanup="inline")
        self.typed(
            0x1415E5830,
            0xC2,
            0x1432E9944,
            self.local(0x88),
            offset=0x90,
            manual=True,
            cleanup="inline",
        )
        kind = self.read(self.local(0x88), 4)
        self.write(self.local(0x88), 4, kind)
        self.write(self.field(0x10), 4, kind)
        self.read_field(0x6DC, 4, offset=0x90, manual=True, cleanup="inline")
        self.read_field(0x710, 4, offset=0x90, cleanup="inline")
        if self.version() >= 0xA051E:
            for offset, width in (
                (0x6E0, 4),
                (0x6E4, 4),
                (0x6E8, 1),
                (0x6EC, 4),
                (0x6F0, 4),
                (0x6F4, 4),
                (0x6F8, 1),
                (0x6FC, 4),
            ):
                self.read_field(offset, width, offset=0x90, cleanup="inline")
            self.read_field(0x700, 4)
        self.read_field(0x6D8, 4, offset=0x90, cleanup="inline")
        self.read_field(0x714, 4, offset=0x90, cleanup="inline")

    def master_and_generation(self) -> None:
        pointer = self.allocate(0x58, spill=0x68)
        if pointer:
            self.zero_allocation(pointer, 0x58)
            self.write(self.local(0x28), 1, 0)
            self.write(self.local(0x20), 8, self.address)
            world = self.read(self.local(0x30))
            source = self.read(world + 0x828)
            pointer = self.invoke(
                0x14148D110, pointer, self.output, self.stream, source, self.address, 0, result=True
            )
        self.write(self.field(0x6D0), 8, pointer)
        returned = self.invoke(0x1409076B0, self.local(0x90), self.output, result=True)
        self.finish(returned, 0x90)
        modern = self.version() > 0x50000
        if modern:
            self.read_field(0xD30, 4, cleanup="inline")
        self.zero_result()
        if not modern:
            self.write(self.field(0xD30), 4, 0)
        pointer = self.allocate(0xF8)
        if pointer:
            self.invoke(0x142D6E3B7, pointer, 0, 0xF8)
            pointer = self.invoke(
                0x14162D370,
                pointer,
                self.address,
                self.local(0x90),
                self.stream if modern else 0,
                result=True,
            )
        self.write(self.field(0xD28), 8, pointer)
        returned = self.invoke(0x1409076B0, self.local(0x38), self.local(0x90), result=True)
        self.finish(returned, 0x38, check=False)
        status = self.read(self.output + 24)
        control = self.read(self.local(0xB0))
        self.release(control, weak_capture=bool(status))
        self.invoke(0x1402BD7F0, self.local(0x90))
        if status:
            raise _ReturnedStatus

    def records(self) -> None:
        if self.version() >= 0x54CCC:
            self.read_field(0xD20, 4, cleanup="inline")
            self.read_field(0xD24, 4, cleanup="inline")
        else:
            self.write(self.field(0xD20), 4, 0xBF800000)
            self.write(self.field(0xD24), 4, 0xBF800000)
        self.marker(cleanup="inline")
        if self.version() >= 0x92147:
            for index in range(9):
                held_record = index * 0x80
                self.write(self.local(0x68), 8, self.field(index))
                self.input(self.field(index + 0xD82), 1, manual=True, cleanup="inline", spill=True)
                for offset in (0xD8B, 0xD94):
                    self.input(
                        self.read(self.local(0x68)) + offset,
                        1,
                        manual=True,
                        cleanup="inline",
                        spill=True,
                    )
                self.input(
                    self.field(0xDA0 + held_record), 1, manual=True, cleanup="inline", spill=True
                )
                for offset, width in (
                    (1, 1),
                    (8, 4),
                    (12, 1),
                    (13, 1),
                    (14, 1),
                    (15, 1),
                    (16, 1),
                    (17, 1),
                    (18, 1),
                    (19, 1),
                    (20, 4),
                ):
                    self.read_field(0xDA0 + held_record + offset, width, cleanup="pair")
                self.write(self.local(0x78), 1, 0)
                self.input(self.local(0x78), 1, cleanup="pair")
                length = self.read(self.local(0x78), 1)
                if length:
                    self.input(self.field(0xDB8 + held_record), length, cleanup="pair")
                    length = self.read(self.local(0x78), 1)
                self.write(self.field(0xDB8 + held_record + length), 1, 0)
                self.read_field(0xE1C + held_record, 1)
                if self.version() >= 0x434CCD:
                    self.input(self.read(self.local(0x68)) + 0x1268, 1)
            self.read_field(0x1272, 2, cleanup="inline")
        else:
            for offset, width in (
                (0xD82, 8),
                (0xD8A, 1),
                (0xD8B, 8),
                (0xD93, 1),
                (0xD94, 8),
                (0xD9C, 1),
            ):
                self.write(self.field(offset), width, 0)
            self.invoke(0x142D6E3B7, self.field(0xDA0), 0, 0x480)
            self.write(self.field(0x1272), 2, 0)
        self.marker(cleanup="inline")

    def preferences(self) -> None:
        for threshold, field in ((0x92B85, 0x1274), (0x92E14, 0x1288)):
            if self.version() >= threshold:
                self.read_field(field, 20, cleanup="inline")
            else:
                for delta, width in ((0, 8), (8, 8), (16, 4)):
                    self.write(self.field(field + delta), width, 0)
        self.marker(cleanup="inline")
        if self.version() >= 0x93851:
            for field in range(0x1378, 0x13A4, 4):
                self.read_field(field, 4, cleanup="inline" if field <= 0x1380 else "finalize")
        else:
            for field, value in (
                (0x1378, 1),
                (0x1394, 100),
                (0x137C, 1),
                (0x1380, 100),
                (0x1384, 100),
                (0x1388, 100),
                (0x138C, 100),
                (0x1390, 100),
                (0x13A0, 500),
                (0x1398, 0x3DCCCCCD),
                (0x139C, 501),
            ):
                self.write(self.field(field), 4, value)
        if self.version() >= 0x9AB85:
            self.read_field(0x12D0, 1, cleanup="inline")
        else:
            self.write(self.field(0x12D0), 1, 1)
        if self.version() >= 0x9E666:
            self.read_field(0xD80, 1, cleanup="inline")
            self.read_field(0xD81, 1)
        else:
            self.write(self.field(0xD80), 2, 0x6464)
        if self.version() >= 0xB6B85:
            self.read_field(0x1308, 4, cleanup="inline", weak_capture=True)
        else:
            self.write(self.field(0x1308), 4, 0)
        for threshold, field, width in ((0xB91EB, 0x13A4, 4), (0xC8A3D, 0x13AC, 1)):
            if self.version() >= threshold:
                self.read_field(field, width)
            else:
                self.write(self.field(field), width, 0)
        if self.version() >= 0xC9999:
            self.read_field(0x13A8, 4)
            self.read_field(0x13AD, 1)
        else:
            self.write(self.field(0x13A8), 4, 0)
            self.write(self.field(0x13AD), 1, 0)
        if self.version() >= 0xBC000:
            self.read_field(0x1300, 4)
        else:
            self.write(self.field(0x1300), 4, 0)
        if self.version() >= 0xC547A:
            self.marker()
            self.read_field(0x1304, 1)
        else:
            self.write(self.field(0x1304), 1, 0)

    def game_player_count(self) -> int:
        game = self.read(0x144353698)
        world = self.invoke(0x140D6ACC0, game, result=True)
        return _signed(self.invoke(0x141603EF0, world, result=True) & _U32, 4)

    def relation_and_counters(self) -> None:
        self.write(self.local(0x78), 1, 0)
        count = self.game_player_count()
        self.invoke(0x1416E4C30, self.field(0x1310), count & _U64, self.local(0x78))
        held_version = self.version()
        if held_version >= 0xC8000:
            index = 0
            count = self.game_player_count()
            while _signed(index, 4) < count:
                self.input(self.local(0x78), 1, cleanup="pair")
                row = (_signed(index, 4) & _U64) >> 5
                pointer = self.read(self.field(0x1310))
                mask = 1 << (index & 31)
                previous = self.read(pointer + row * 4, 4)
                flag = self.read(self.local(0x78), 1)
                self.write(pointer + row * 4, 4, previous | mask if flag else previous & ~mask)
                index = (index + 1) & _U32
                count = self.game_player_count()
            held_version = self.version()
        if held_version >= 0x94CCC:
            for field in (0xD34, 0xD3C, 0xD40, 0xD44, 0xD48, 0xD50):
                self.read_field(field, 4)
        else:
            for field, width in ((0xD34, 4), (0xD3C, 8), (0xD44, 8), (0xD50, 4)):
                self.write(self.field(field), width, 0)
        if self.version() >= 0x94F5C:
            self.read_field(0xD38, 4)
            self.read_field(0xD4C, 4)
        else:
            self.write(self.field(0xD38), 4, 0)
            self.write(self.field(0xD4C), 4, 0)
        if self.version() >= 0x951EB:
            for index in range(9):
                self.typed(
                    0x140B81D60, 0x1CC, 0x1432F2578, self.field(0xD54 + index * 4), cleanup="pair"
                )
        else:
            for field, width in ((0xD54, 8), (0xD5C, 8), (0xD64, 8), (0xD6C, 8), (0xD74, 4)):
                self.write(self.field(field), width, 0)
        if self.version() >= 0x96147:
            self.zero_result()
            pointer = self.allocate(0x48)
            if pointer:
                self.zero_allocation(pointer, 0x48)
                pointer = self.invoke(
                    0x14149D9A0, pointer, self.local(0x90), self.stream, result=True
                )
            self.write(self.field(0xD78), 8, pointer)
            returned = self.invoke(0x1409076B0, self.local(0x38), self.local(0x90), result=True)
            self.finish(returned, 0x38, check=False, cleanup="finalize")
            control = self.read(self.local(0xB0))
            status = self.read(self.output + 24)
            if control:
                self.invoke(0x1402AAA80, control)
            self.invoke(0x1402BD7F0, self.local(0x90))
            if status:
                raise _ReturnedStatus
        else:
            self.write(self.field(0xD78), 8, 0)

    def map_reader(self) -> None:
        pointer = self.allocate(0x38)
        if pointer:
            self.zero_allocation(pointer, 0x38)
            pointer = self.invoke(0x141027450, pointer, 0x1E0, 0x1E0, 0, result=True)
        self.write(self.field(0x12F0), 8, pointer)
        returned = self.invoke(0x141028560, pointer, self.local(0x38), self.stream, result=True)
        self.finish(returned, 0x38, cleanup="finalize")

    def kind_and_ai(self) -> int:
        kind = self.read(self.local(0x88), 4)
        if kind == 1:
            held_version = self.version()
            if held_version >= 0xD11EB:
                self.typed(0x140B81D60, 0x1E6, 0x1432F2590, self.field(0x12E8))
                if self.read(self.field(0x12E8), 4):
                    self.map_reader()
            else:
                enabled = 0
                if held_version >= 0xD0CCC:
                    returned = self.invoke(
                        0x140D6A530, self.read(0x144353698), self.local(0x30), result=True
                    )
                    enabled = self.read(self.read(returned) + 0x48, 4)
                    control = self.read(self.local(0x30))
                    if control:
                        self.invoke(0x140990140, control)
                self.write(self.field(0x12E8), 4, int(enabled != 0))
                if enabled:
                    self.map_reader()
                else:
                    self.write(self.field(0x12F0), 8, 0)
        held_version = self.version()
        if held_version >= 0xD23D7:
            self.typed(0x140D94310, 0x204, 0x1432F25A8, self.field(0x1330))
            held_version = self.version()
        if held_version >= 0x19051E:
            self.typed(0x140D07EE0, 0x209, 0x1432F25C8, self.field(0x13AE))
            held_version = self.version()
        if held_version >= 0x194CCC:
            self.typed(0x140D07EE0, 0x20E, 0x1432F25E0, self.field(0x13AF))
        else:
            self.write(self.field(0x13AF), 1, 0)
        if self.version() >= 0x281999:
            self.typed(0x140D07EE0, 0x218, 0x1432F25F0, self.field(0x12F8))
        self.marker()
        if kind == 3:
            self.write(self.local(0x88), 4, 1)
            if self.version() >= 0x707AE:
                self.input(self.local(0x88), 4)
                if self.read(self.local(0x88), 4) != 1:
                    return kind
            pointer = self.allocate(0x28FC0)
            if pointer:
                self.invoke(0x142D6E3B7, pointer, 0, 0x28FC0)
                returned = self.invoke(
                    0x141732B10, self.address, self.local(0x90), 0, 0x1432F47B0, result=True
                )
                mask = 1
                self.write(self.local(0x68), 4, mask)
                self.write(self.local(0x28), 8, self.stream)
                self.write(self.local(0x20), 8, self.output)
                name = self.read(returned)
                index = self.read(self.field(0x648), 4)
                pointer = self.invoke(
                    0x140C7EBE0,
                    pointer,
                    index,
                    name,
                    self.address,
                    self.output,
                    self.stream,
                    result=True,
                )
            else:
                mask = self.read(self.local(0x80), 4)
            self.write(self.field(0x718), 8, pointer)
            if mask & 1:
                self.invoke(0x140A1B220, self.local(0x90))
            returned = self.invoke(0x1409076B0, self.local(0x38), self.output, result=True)
            self.finish(returned, 0x38, cleanup="finalize")
            if self.version() >= 0x328000:
                self.input(self.local(0x78), 1)
                if self.read(self.local(0x78), 1):
                    self.invoke(0x1416DFCA0, self.address, self.stream)
        return kind

    def global_state(self, kind: int) -> None:
        returned = self.invoke(0x1416C2180, self.local(0x30), result=True)
        self.invoke(0x1416BFE70, self.field(0x12E0), returned)
        self.invoke(0x1416C6A40, self.local(0x30))
        if self.version() >= 0x449999:
            returned = self.invoke(
                0x14134B780,
                self.read(self.field(0x12E0)),
                self.local(0x38),
                self.stream,
                result=True,
            )
            self.finish(returned, 0x38, cleanup="finalize")
        self.marker()
        for field in (0x12A0, 0x12D8, 0x12A8):
            pointer = self.allocate(24)
            if pointer:
                self.zero_allocation(pointer, 24)
                pointer = self.invoke(0x141227140, pointer, result=True)
            self.write(self.field(field), 8, pointer)
        self.write(self.field(0x708), 8, 0)
        world = self.read(self.field(8))
        if self.read(world + 0x6B4, 4) != 1:
            self.encode_zero(0x38)
        if kind == 3 and self.read(self.field(0x718)):
            self.invoke(0x141603CB0, self.read(self.field(8)), self.local(0x80))
            control = self.read(self.local(0x80))
            if control:
                self.write(self.local(0x88), 4, 0)
                accepted = self.invoke(
                    0x1416F6B40, control + 0x90, 0, self.local(0x88), result=True
                )
                if accepted & 0xFF:
                    self.invoke(
                        0x140CE4650,
                        self.read(self.field(0x718)) + 0x25F88,
                        0xE9,
                        self.read(self.local(0x88), 4),
                    )
                control = self.read(self.local(0x80))
            if control:
                self.invoke(0x140990140, control)
        for field in (0x710, 0x718, 0x720, 0x728):
            self.encode_zero(field)

    def encode_zero(self, offset: int) -> None:
        recipient = self.read(self.field(0x98))
        self.write(self.local(0x30), 4, 0)
        self.write(self.local(0x80), 8, self.read(self.local(0x30)))
        for operation, key in zip(("xor", "add", "xor", "xor"), _CIPHER, strict=True):
            value = self.read(self.local(0x80))
            self.write(self.local(0x80), 8, value + key if operation == "add" else value ^ key)
        self.write(self.local(0x30), 8, self.read(self.local(0x80)))
        self.write(recipient + offset, 8, self.read(self.local(0x30)))

    def final_records(self) -> None:
        self.write(self.local(0xC0), 16, 0)
        self.write(self.local(0xD0), 8, 0)
        self.invoke(0x140F92850, self.read(self.field(0x6A8)) + 0x100, self.local(0xC0))
        current = self.read(self.local(0xC0))
        end = self.read(self.local(0xC8))
        if current != end:
            while current != end:
                index = _signed(self.read(current, 4), 4) * 0x98
                record = self.read(self.read(self.field(0x6D0))) + index
                if self.read(record + 0x18) == 0:
                    value = self.invoke(0x140803E30, self.read(current + 4, 4), result=True)
                    index = _signed(self.read(current, 4), 4) * 0x98
                    record = self.read(self.read(self.field(0x6D0))) + index
                    self.invoke(0x140A15BF0, record + 0x10, value)
                index = _signed(self.read(current, 4), 4) * 0x98
                record = self.read(self.read(self.field(0x6D0))) + index
                if self.read(record + 0x6C, 2) == 0xFFFF:
                    self.write(record + 0x6C, 2, self.read(current + 8, 2))
                current = (current + 20) & _U64
            current = self.read(self.local(0xC0))
        if self.version() >= 0x44CCCD:
            self.typed(0x140B81E60, 0x276, 0x1432F2608, self.field(0x12FC), check=False)
            status = self.read(self.output + 24)
            if status:
                current = self.read(self.local(0xC0))
                if current:
                    self.release_vector(current)
                raise _ReturnedStatus
            current = self.read(self.local(0xC0))
        if current:
            self.release_vector(current)

    def release_vector(self, current: int) -> None:
        capacity = self.read(self.local(0xD0))
        difference = _signed((capacity - current) & _U64, 8)
        # Signed reciprocal multiply/SAR/sign-correction in52f5/5322.
        high = (difference * 0x6666666666666667) >> 64
        quotient = high >> 3
        quotient += (quotient & _U64) >> 63
        self.invoke(0x1402A8790, current, (quotient * 20) & _U64)


def construct_replay_saved_derived_player(
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
) -> int:
    """Complete normal1416c2440, with independently scoped coherent D8 frame.

    Fifth operand is the held effective incoming pointer, not a physical stack
    home. Shared local88 is first index, then saved type, then AI flag; heldkind
    survives its reuse. Parent141713f70 receives five actual arguments. Normal
    returned errors retain preceding normal cleanup and return held address;
    failed/missing children stop without fabricated success or blanket cleanup.
    Inputs and mixed marker calls are real providers, never Python wire defaults.
    """
    _validate(context, calls, address, output, stream, world, index_pointer)
    if (
        not isinstance(atomics, ReplayUnitAIMapAtomics)
        or not isinstance(floating, ReplayPlayerSupportFloatingCalls)
        or not callable(bind_local)
    ):
        raise ValueError("actual atomics/local/mixed-FP providers required")
    if type(scratch) is not bytes or len(scratch) != 0xD8:
        raise ValueError("explicit D8-byte derived Player logical frame required")
    with _local(memoryview(bytearray(scratch)), bind_local) as frame:
        state = _DerivedConstruction(
            context, calls, atomics, floating, address, output, stream, frame
        )
        try:
            state.initial(world, index_pointer)
            state.master_and_generation()
            state.records()
            state.preferences()
            state.relation_and_counters()
            kind = state.kind_and_ai()
            state.global_state(kind)
            state.final_records()
        except _ReturnedStatus:
            pass
    return address


def bind_replay_saved_derived_player(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    *,
    atomics: ReplayUnitAIMapAtomics,
    bind_local: LocalBinding,
    scratch: bytes,
    floating: ReplayPlayerSupportFloatingCalls,
) -> ReplayTaskRebuildCalls:
    """Bind only1416c2440; actual Base and all other descendants delegate."""
    _validate(context, calls)

    def dispatch(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        if target != 0x1416C2440:
            if calls.call is None:
                raise UnresolvedReplayTaskRebuild(f"reached{target:x} unavailable")
            return calls.call(target, args, data)
        if len(args) != 5 or data is not None:
            raise ValueError("malformed derived Player saved-constructor call")
        return construct_replay_saved_derived_player(
            context,
            *args,
            calls=bound,
            atomics=atomics,
            bind_local=bind_local,
            scratch=scratch,
            floating=floating,
        )

    bound = ReplayTaskRebuildCalls(dispatch)
    return bound
