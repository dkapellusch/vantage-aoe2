"""Whole build54800 Base-object update141249740,4816 bytes/1124 rows.

Source/API: base-object-update-source-v1. Actual virtual, registration, graphics,
allocation, RNG, cleanup and script effects remain mandatory. Logical semantic
homes are coherent; native saves/cookie/faults/EH/threads/FP flags are excluded.
This does not restore a World or commit a recording tick.
"""

from __future__ import annotations

from dataclasses import dataclass

from .replay_binary32 import compare_binary32, multiply_binary32, subtract_binary32
from .replay_manager_queues import _Frame
from .replay_task_group_storage import LocalBinding
from .replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
    _cvtt,
    _read,
    _signed,
    _unsigned,
    _write,
)
from .replay_unit_ai_base import _validate

_ENTRY, _U32, _U64 = 0x141249740, (1 << 32) - 1, (1 << 64) - 1
_MASTER_A, _MASTER_B = 0x6A586EB28AC201FC, 0x0CF19788B2554E70
_TYPE_XOR, _TYPE_SUB = 0x349E37847AD69F19, 0x47E37DFF0616CE4F
_HP_XOR, _HP_SUB = 0x0F2A55F7A61DD00E, 0x147B5E081EC087D9
_COORDS = {
    0x180: (0x2B3719EF44DE99FF, 0x21D14A25ED7C802C),
    0x178: (-0x61501AA6ECFD980A, 0x6C5EAB60B426DD28),
    0x170: (-0x183CAC30D2441D0E, 0x4C3FBA69E4EA7FD1),
}
_ARMS = {0x1412499B3, 0x141249A86, 0x141249EC0, 0x141249ED4, 0x14124A044, 0x14124A075, 0x14124A14E}


@dataclass(frozen=True, slots=True)
class ReplayBaseObjectUpdateProfile:
    """Explicit C0-byte logical prefix; RBP=logicalRSP+99, cookieC0 excluded."""

    frame: bytes

    def __post_init__(self) -> None:
        if type(self.frame) is not bytes or len(self.frame) != 0xC0:
            raise ValueError("explicitC0-hex-byte Base update seed required")


def _raw(value: int | None, label: str) -> int:
    if value is None:
        raise ValueError(f"{label} requires actual rawu64 annotation")
    _unsigned(value, 8, label)
    return value


class _Base:
    def __init__(
        self,
        context: ReplayTaskRebuildStorage,
        calls: ReplayTaskRebuildCalls,
        virtual: ReplayTaskRebuildCalls,
        logger: ReplayTaskRebuildCalls,
        position: ReplayTaskRebuildCalls,
        rtti: ReplayTaskRebuildCalls,
        bind_local: LocalBinding,
        profile: ReplayBaseObjectUpdateProfile,
    ) -> None:
        self.context, self.calls, self.virtual, self.logger = context, calls, virtual, logger
        self.position, self.rtti = position, rtti
        self.bind_local, self.profile, self.result = bind_local, profile, 0

    def r(self, at: int, width: int = 8) -> int:
        return _read(self.context, at, width)

    def w(self, at: int, width: int, value: int) -> None:
        _write(self.context, at, width, value)

    def invoke(self, channel: ReplayTaskRebuildCalls, target: int, *args: int) -> int | None:
        if channel.call is None:
            raise UnresolvedReplayTaskRebuild(f"reached{target:x} is unavailable")
        return channel.call(target, tuple(value & _U64 for value in args), None)

    def call(self, target: int, *args: int) -> int | None:
        return self.invoke(self.calls, target, *args)

    def raw(self, target: int, *args: int) -> int:
        return _raw(self.call(target, *args), f"{target:x} RAX")

    def eax(self, target: int, *args: int) -> int:
        return self.raw(target, *args) & _U32

    def virtual_call(self, obj: int, slot: int, *args: int) -> int | None:
        return self.invoke(self.virtual, self.r(self.r(obj) + slot), obj, *args)

    def vr(self, obj: int, slot: int, *args: int) -> int:
        return _raw(self.virtual_call(obj, slot, *args), f"virtual{slot:x} RAX")

    def master(self, f: _Frame, obj: int, home: int = 0x30) -> int:
        f.w(home, 8, self.r(obj + 0x10))
        f.w(home, 8, f.r(home, 8) - _MASTER_A)
        f.w(home, 8, f.r(home, 8) - _MASTER_B)
        return f.r(home, 8)

    def kind(self, f: _Frame, obj: int, home: int = 0x30) -> int:
        master = self.master(f, obj, home)
        f.w(home, 8, self.r(master + 0x18))
        f.w(home, 8, f.r(home, 8) ^ _TYPE_XOR)
        f.w(home, 8, f.r(home, 8) - _TYPE_SUB)
        return f.r(home, 8) & 0xFFFF

    def coords(self, f: _Frame, obj: int, homes: tuple[int, int, int]) -> None:
        for field, home in zip((0x180, 0x178, 0x170), homes, strict=True):
            f.w(0x30, 8, self.r(obj + field))
            for value in _COORDS[field]:
                f.w(0x30, 8, f.r(0x30, 8) + value)
            f.w(home, 8, f.r(0x30, 8))

    def hp(self, f: _Frame, obj: int) -> None:
        f.w(0x30, 8, self.r(obj + 0x130))
        f.w(0x30, 8, f.r(0x30, 8) ^ _HP_XOR)
        f.w(0x30, 8, f.r(0x30, 8) - _HP_SUB)
        f.w(0x60, 8, f.r(0x30, 8))

    def initial(self, f: _Frame, obj: int) -> None:
        index = self.r(self.r(obj + 0x18) + 0x648, 4)
        self.coords(f, obj, (0x48, 0x68, 0x60))
        name = self.raw(0x140A4B870, self.master(f, obj))
        name = self.r(name)
        if self.r(0x14435505B, 1) >= 2:
            f.w(0x90, 4, 2)
            f.w(0x88, 4, index)
            f.w(0x38, 4, 10)
            f.w(0x30, 4, f.r(0x48, 4))
            f.w(0x50, 4, 10)
            f.w(0x48, 4, f.r(0x68, 4))
            f.w(0x70, 4, 10)
            f.w(0x68, 4, f.r(0x60, 4))
            f.w(0x80, 4, 15)
            f.w(0x78, 8, name)
            for home, target in (
                (0x98, 0x78),
                (0xA0, 0x68),
                (0xA8, 0x48),
                (0xB0, 0x30),
                (0xB8, 0x88),
            ):
                f.w(home, 8, f.h(target))
            f.w(0x20, 8, f.h(0x98))
            logger = self.r(0x144355068)
            self.invoke(self.logger, 0x14101ADB0, logger, 0x23, 0x1432B4A40, 5, f.h(0x20))
        self.result = 0
        f.w(0x40, 1, 0)

    def registration(self, obj: int) -> bool:
        if not self.r(obj + 0x18B, 1):
            return False
        self.w(obj + 0x18B, 1, 0)
        self.w(obj + 0x189, 1, 1)
        for slot, flag in ((0x2E0, 0), (0x2D8, 1)):
            owner = self.r(obj + 0x18)
            state = self.r(obj + 0x18A, 1)
            table = self.r(owner)
            self.invoke(self.virtual, self.r(table + slot), owner, obj, flag, state)
        return True

    def linked(self, f: _Frame, obj: int, link: int) -> None:
        state = self.r(link + 0x188, 1)
        if state > 2:
            self.virtual_call(obj, 0xA8, state)
            if self.r(obj + 0x188, 1) == 5:
                target = self.vr(obj, 0x170)
                if target:
                    self.virtual_call(target, 0xA8, 7)
        else:
            self.hp(f, obj)
            if (
                compare_binary32(self.r(0x1436A0294, 4), f.r(0x60, 4)) == 1
                and not self.r(self.master(f, obj) + 0x60, 1) & 4
            ):
                self.virtual_call(obj, 0x1C0)

    def state_two(self, f: _Frame, obj: int) -> None:
        self.call(0x141243980, obj)
        self.call(0x141248340, obj)
        if (
            self.kind(f, obj) == 0x3D
            and not self.r(self.master(f, obj) + 0x50)
            and not self.r(self.r(obj + 0x18) + 0x648, 4)
            and self.r(self.master(f, obj) + 0xAA, 2) == 0x11
        ):
            self.virtual_call(obj, 0xA8, 5)
        self.death(f, obj)

    def death(self, f: _Frame, obj: int) -> None:
        self.hp(f, obj)
        if compare_binary32(self.r(0x1436A0294, 4), f.r(0x60, 4)) != 1:
            return
        if self.r(obj + 0xF, 1) == 0x50:
            for index in range(4):
                slot = (obj + 0x870 + index * 8) & _U64
                link = self.r(slot)
                if link:
                    if self.r(link + 0xF, 1) == 0x50:
                        self.w(link + 0x868, 8, 0)
                    self.hp(f, obj)
                    link = self.r(slot)
                    f.w(0x68, 4, f.r(0x60, 4))
                    f.w(0x30, 8, f.r(0x68, 8))
                    f.w(0x30, 8, f.r(0x30, 8) + _HP_SUB)
                    f.w(0x30, 8, f.r(0x30, 8) ^ _HP_XOR)
                    f.w(0x60, 8, f.r(0x30, 8))
                    self.w(link + 0x130, 8, f.r(0x60, 8))
                    self.w(slot, 8, 0)
        self.virtual_call(obj, 0xA8, 3)
        if self.r(obj + 0xF, 1) != 0x50:
            selected = self.vr(obj, 0x850)
            if selected:
                self.virtual_call(obj, 0x70, selected)
        else:
            self.building_death(f, obj)
        self.call(0x1412493C0, obj)
        if not self.r(obj + 0x28):
            graphic = self.r(obj + 0x20)
            if graphic and self.r(graphic + 0x1A, 1) & 4:
                count = _signed(self.r(graphic + 0xA, 2), 2)
                if count > 1:
                    draw = self.eax(0x140903E40, 0x144353180, 0x14329E98C, 0xF3A)
                    product = draw * count & _U32
                    high = (_signed(0x80010003, 4) * _signed(product, 4)) >> 32
                    quotient = _signed((high + product) & _U32, 4) >> 14
                    value = (quotient + ((quotient & _U32) >> 31)) & 255
                    self.w(obj + 0xE, 1, value)
                    count = self.r(self.r(obj + 0x20) + 0xA, 2)
                    if value >= _signed(count, 2):
                        self.w(obj + 0xE, 1, count - 1)
        target = self.r(self.r(obj) + 0x4F8)
        master = self.master(f, obj)
        self.invoke(self.virtual, target, obj, master + 0x170)

    def building_death(self, f: _Frame, obj: int) -> None:
        master = self.master(f, obj)
        count = self.raw(0x140BB9290, master, 0) & 0xFFFF
        frame = _cvtt(self.r(obj + 0x900, 4)) & 0xFFFF
        if _signed(frame, 2) >= _signed(count, 2):
            graphic = self.r(obj + 0x20)
            if graphic and self.r(graphic + 0xA, 2) == 1:
                self.w(obj + 0xE, 1, self.vr(self.r(obj + 0x28), 8) & 255)
                table = self.r(obj)
                selected = _raw(
                    self.invoke(self.virtual, self.r(table + 0x850), obj), "Building virtual850 RAX"
                )
                self.invoke(self.virtual, self.r(table + 0x70), obj, selected)
                self.call(0x14125CC30, obj, self.r(obj + 0xE, 1))
            else:
                table = self.r(obj)
                selected = _raw(
                    self.invoke(self.virtual, self.r(table + 0x850), obj), "Building virtual850 RAX"
                )
                self.invoke(self.virtual, self.r(table + 0x70), obj, selected)
        else:
            selected = self.r(master + 0x400)
            target = self.r(self.r(obj) + 0x70)
            if not selected:
                selected = self.r(self.master(f, obj) + 0x50)
            self.invoke(self.virtual, target, obj, selected)
        if _signed(self.r(self.master(f, obj) + 0x86, 2), 2) < 0:
            return
        graphics = self.r(self.r(obj + 0x18) + 0x28)
        index = _signed(self.r(self.master(f, obj) + 0x86, 2), 2)
        graphic = self.r(graphics + index * 8)
        if not graphic:
            return
        target = self.r(self.r(graphic) + 0x40)
        f.w(0x58, 1, 1)
        self.coords(f, obj, (0x60, 0x68, 0x48))
        f.w(0x28, 8, f.h(0x58))
        f.w(0x20, 4, f.r(0x60, 4))
        y, x = f.r(0x68, 4), f.r(0x48, 4)
        owner = self.r(obj + 0x18)
        created = _raw(
            self.invoke(self.position, target, graphic, owner, x, y, f.h(0x20), f.h(0x28)),
            "position factory RAX",
        )
        f.w(0x20, 4, 0)
        created = _raw(
            self.invoke(self.rtti, 0x142D6E3D5, created, 0, 0x14411D848, 0x1441290A0, f.h(0x20)),
            "RTTI RAX",
        )
        if created:
            self.call(0x14125CC30, created, self.r(obj + 0xE, 1))
            self.call(0x14120E0F0, created)

    def timer(self, f: _Frame, obj: int) -> None:
        active = self.r(obj + 0x160, 2) != 0xFFFF
        if active:
            active = compare_binary32(self.r(obj + 0x168, 4), 0) == 1
        if active:
            master = self.master(f, obj)
            if compare_binary32(self.r(master + 0xC0, 4), 0) != 1:
                return
            master = self.master(f, obj)
            clock = self.r(self.r(obj + 0x18) + 8)
            amount = multiply_binary32(self.r(clock + 0x164, 4), self.r(master + 0xC0, 4))
            value = subtract_binary32(self.r(obj + 0x168, 4), amount)
            self.w(obj + 0x168, 4, value)
            if compare_binary32(0, value) == 1:
                self.w(obj + 0x168, 4, 0)
            return
        master = self.master(f, obj)
        target = self.r(self.r(obj) + 0xA8)
        if self.r(master + 0x60, 1) & 1:
            self.invoke(self.virtual, target, obj, 6)
            table = self.r(obj)
            selected = _raw(
                self.invoke(self.virtual, self.r(table + 0x858), obj), "timer virtual858 RAX"
            )
            self.invoke(self.virtual, self.r(table + 0x70), obj, selected)
        else:
            self.invoke(self.virtual, target, obj, 7)
            other = self.vr(obj, 0x170)
            if not other or not self.vr(obj, 0x858):
                return
            target = self.r(self.r(other) + 0x70)
            selected = self.vr(obj, 0x858)
            self.invoke(self.virtual, target, other, selected)
            self.call(0x14125CC30, other, self.r(obj + 0xE, 1))

    def state(self, f: _Frame, obj: int) -> None:
        link = self.r(obj + 0x148)
        if link:
            self.linked(f, obj, link)
            return
        state = self.r(obj + 0x188, 1)
        if state > 8:
            return
        target = 0x140000000 + self.r(0x14124AA10 + state * 4, 4)
        if target not in _ARMS:
            raise UnresolvedReplayTaskRebuild(f"unprovided Base update state target{target:x}")
        if target == 0x1412499B3:
            self.state_two(f, obj)
        elif target == 0x141249A86:
            self.death(f, obj)
        elif target in (0x141249EC0, 0x141249ED4):
            if target == 0x141249EC0 and self.eax(0x141252300, obj):
                self.call(0x141243980, obj)
            self.timer(f, obj)
        elif target == 0x14124A044:
            index = self.eax(0x1410B9490, _signed(self.r(obj + 0x160, 2), 2) & _U32)
            if _signed(index, 4) >= 0:
                self.call(0x14172C8D0, self.r(obj + 0x18), index, obj)
            self.virtual_call(obj, 0xA8, 8)
        elif target == 0x14124A075:
            self.result = 1
            f.w(0x40, 1, 1)

    def effects(self, f: _Frame, obj: int) -> None:
        cursor = self.r(obj + 0x248)
        if cursor == self.r(obj + 0x250):
            return
        index = 0
        while True:
            effect = self.r(cursor)
            if effect:
                if self.r(effect + 0x24, 1) and self.r(effect + 0x25, 1):
                    bitmap_index = (_signed(index, 4) & _U64) >> 5
                    bitmap = self.r(obj + 0x260)
                    bit = index & 31
                    if self.r(bitmap + bitmap_index * 4, 4) & (1 << bit):
                        self.coords(f, obj, (0x48, 0x68, 0x60))
                        f.w(0x78, 4, f.r(0x60, 4))
                        f.w(0x7C, 4, f.r(0x68, 4))
                        f.w(0x80, 4, f.r(0x48, 4))
                        self.call(0x1409B5F00, effect, f.h(0x78))
                else:
                    self.call(0x1409B5F80, effect, 1)
                    self.call(0x1409B5E80, self.r(cursor))
                    self.w(cursor, 8, 0)
            cursor = (cursor + 8) & _U64
            index = (index + 1) & _U32
            if cursor == self.r(obj + 0x250):
                break
        self.result = f.r(0x40, 1)

    def count_members(self, f: _Frame, obj: int) -> int:
        vector = self.r(obj + 0x150)
        if not vector or _signed(self.r(vector + 8, 4), 4) <= 0:
            return 0
        index, offset, count = 0, 0, 0
        f.w(0x30, 4, 0x42F)
        while True:
            member = self.r(self.r(vector) + offset)
            if member:
                kind = self.kind(f, member, 0x48)
                matched = kind in (0xEF, 0x22E, 0x369, 0x36B)
                if not matched:
                    delta = (kind - f.r(0x30, 2)) & 0xFFFF
                    matched = delta <= 0x3F and bool(0xA00A000000000001 & (1 << delta))
                    if not matched:
                        matched = kind in (0x6D0, 0x6D2)
                if matched:
                    count = (count + 1) & 0xFFFF
            index = (index + 1) & _U32
            offset = (offset + 8) & _U64
            vector = self.r(obj + 0x150)
            if _signed(index, 4) >= _signed(self.r(vector + 8, 4), 4):
                break
        self.result = f.r(0x40, 1)
        return count

    def game(self) -> int:
        return self.raw(0x140D6ACC0, self.r(0x144353698))

    def grow_graphics(self, header: int) -> None:
        capacity = self.r(header + 8)
        count = self.r(header + 0x10)
        if ((count + 1) & _U64) <= capacity:
            return
        needed = (count - capacity + 1) & _U64
        if not needed:
            return
        growth = self.r(header + 0x18) or 1
        goal = (needed + capacity) & _U64
        doubled = capacity or 1
        while doubled < goal:
            doubled = doubled * 2 & _U64
        rounded = (needed - 1 + growth) & _U64
        rounded = (rounded - rounded % growth + capacity) & _U64
        self.call(0x141248170, header, min(rounded, doubled))

    def graphic_attributes(self, graphic: int, replacement: int) -> None:
        count = _signed(self.r(graphic + 0x8C, 2), 2)
        if count <= 0:
            return
        index = 0
        while True:
            offset = (_signed(index, 4) << 4) & _U64
            entry = (self.r(graphic + 0x90) + offset) & _U64 if _signed(index, 4) < count else 0
            if self.r(self.r(entry) + 0x18, 2) == 0x1002:
                entry = (self.r(graphic + 0x90) + offset) & _U64 if _signed(index, 4) < count else 0
                self.w(entry, 8, replacement)
            index = (index + 1) & _U32
            count = _signed(self.r(graphic + 0x8C, 2), 2)
            if _signed(index, 4) >= count:
                break

    def create_graphic(self, f: _Frame, obj: int) -> None:
        stamp = self.r(self.game() + 0xD0, 4)
        allocated = self.raw(0x142D6BA78, 0xF8)
        f.w(0x60, 8, allocated)
        if allocated:
            self.call(0x142D6E3B7, allocated, 0, 0xF8)
            graphic = self.raw(0x1409CBEF0, allocated, stamp & 0xFFFF)
        else:
            graphic = 0
        replacement = self.r(self.r(self.game() + 0xC0) + 0x180B0)
        if not graphic or not replacement:
            return
        header = (self.game() + 0xC0) & _U64
        self.grow_graphics(header)
        count = self.r(header + 0x10)
        slot = (self.r(header) + count * 8) & _U64
        if slot:
            self.w(slot, 8, graphic)
        self.w(header + 0x10, 8, self.r(header + 0x10) + 1)
        self.w(obj + 0x290, 4, _signed(self.r(graphic + 0x18, 2), 2))
        self.call(0x1409CD830, graphic, self.r(obj + 0x20))
        self.graphic_attributes(graphic, replacement)

    def install_graphic(self, f: _Frame, obj: int) -> None:
        self.w(obj + 0x294, 1, 1)
        world = self.game()
        index = _signed(self.r(obj + 0x290, 4), 4) & _U64
        if index >= self.r(world + 0xD0):
            return
        if not self.r(obj + 0x200):
            master = self.master(f, obj, 0x48)
            cloned = self.vr(master, 0x48)
            if not cloned:
                return
            f.w(0x48, 8, cloned)
            f.w(0x48, 8, f.r(0x48, 8) + _MASTER_B)
            f.w(0x48, 8, f.r(0x48, 8) + _MASTER_A)
            self.w(obj + 0x10, 8, f.r(0x48, 8))
            self.call(0x1412429D0, obj + 0x200, obj)
        world = self.game()
        index = _signed(self.r(obj + 0x290, 4), 4)
        graphic = self.r(self.r(world + 0xC0) + index * 8)
        master = self.master(f, obj, 0x48)
        self.w(master + 0x40, 8, graphic)
        master = self.master(f, obj, 0x48)
        self.w(master + 0x1E8, 8, graphic)
        self.virtual_call(obj, 0x70, graphic)

    def sync_graphic(self, obj: int) -> None:
        if self.r(obj + 0x188, 1) != 2:
            return
        index = self.r(obj + 0x290, 4)
        current = _signed(self.r(self.r(obj + 0x20) + 0x18, 2), 2) & _U32
        if current == index or index == _U32:
            return
        world = self.game()
        index = _signed(self.r(obj + 0x290, 4), 4) & _U64
        if index >= self.r(world + 0xD0):
            return
        world = self.game()
        index = _signed(self.r(obj + 0x290, 4), 4)
        graphic = self.r(self.r(world + 0xC0) + index * 8)
        if graphic:
            self.virtual_call(obj, 0x70, graphic)

    def special_graphics(self, f: _Frame, obj: int) -> None:
        if self.kind(f, obj) != 0x221 or self.r(self.master(f, obj) + 0x74, 1) < 10:
            return
        if self.eax(0x140FA36A0, self.r(0x144353698) + 0x680) != 2:
            return
        if self.r(obj + 0x294, 1):
            master = self.master(f, obj)
            table = self.r(self.r(obj + 0x18) + 0x28)
            other = self.r(self.r(table + 0x1108) + 0x74, 1)
            if self.r(master + 0x74, 1) != other:
                self.virtual_call(obj, 0x178)
                self.w(obj + 0x294, 1, 0)
        count = self.count_members(f, obj)
        flag = self.r(obj + 0x294, 1)
        if _signed(count, 2) >= 10:
            if not flag:
                if self.r(obj + 0x290, 4) == _U32:
                    self.create_graphic(f, obj)
                self.install_graphic(f, obj)
            self.sync_graphic(obj)
        elif flag and self.r(obj + 0x188, 1) == 2:
            self.virtual_call(obj, 0x178)
            self.w(obj + 0x294, 1, 0)
            table = self.r(obj)
            graphic = _raw(
                self.invoke(self.virtual, self.r(table + 0x848), obj), "graphic virtual848 RAX"
            )
            self.invoke(self.virtual, self.r(table + 0x70), obj, graphic)

    def final_script(self, f: _Frame, obj: int) -> None:
        if self.eax(0x14172AC80, self.r(obj + 0x18)) or self.kind(f, obj, 0x48) != 0x671:
            return
        owner = self.r(obj + 0x18)
        current = self.raw(0x141603D70, self.game())
        if owner != current or self.eax(0x140FA36A0, self.r(0x144353698) + 0x680) != 2:
            return
        value = self.eax(0x141694610, self.game())
        world = self.game()
        if ((value - 1) & _U32) <= 8:
            owner_index = self.r(self.r(obj + 0x18) + 0x648, 4)
            receiver = self.r(world + 0x130)
            mode = 0x672
            f.w(0x30, 4, owner_index)
        elif ((value - 10) & _U32) <= 8:
            f.w(0x30, 4, self.r(self.r(obj + 0x18) + 0x648, 4))
            mode, receiver = 0x673, self.r(world + 0x130)
        elif ((value - 19) & _U32) <= 7:
            f.w(0x30, 4, self.r(self.r(obj + 0x18) + 0x648, 4))
            mode, receiver = 0x674, self.r(world + 0x130)
        elif _signed(value, 4) >= 27:
            owner_index = self.r(self.r(obj + 0x18) + 0x648, 4)
            receiver = self.r(world + 0x130)
            mode = 0x675
            f.w(0x30, 4, owner_index)
        else:
            return
        current_id = self.r(obj + 8, 4)
        self.call(0x140F49E90, receiver, f.h(0x30), mode, current_id)

    def run(self, obj: int) -> int:
        with _Frame(self.context, self.bind_local, self.profile.frame) as f:
            self.initial(f, obj)
            if self.registration(obj):
                return 0
            self.state(f, obj)
            self.effects(f, obj)
            self.special_graphics(f, obj)
            self.final_script(f, obj)
            return self.result


def bind_replay_base_object_update(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    *,
    virtual_calls: ReplayTaskRebuildCalls,
    logger_home_calls: ReplayTaskRebuildCalls,
    position_fp_home_calls: ReplayTaskRebuildCalls,
    rtti_home_calls: ReplayTaskRebuildCalls,
    bind_local: LocalBinding,
    profile: ReplayBaseObjectUpdateProfile,
    mxcsr: int,
) -> ReplayTaskRebuildCalls:
    """Bind the complete logical caller; every reached external effect is real.

    Partial BYTE/DWORD homes and current/held vtables follow the originals.
    Unknown switch RVAs refuse. Unknown calls preserve raw args/data/result.
    No object initialization, loop cutoff, restore readiness or success inferred.
    """
    for channel in (
        calls,
        virtual_calls,
        logger_home_calls,
        position_fp_home_calls,
        rtti_home_calls,
    ):
        _validate(context, channel)
    if (
        not callable(bind_local)
        or not isinstance(profile, ReplayBaseObjectUpdateProfile)
        or type(mxcsr) is not int
        or mxcsr != 0x1F80
    ):
        raise ValueError("actual locals/profile and exact MXCSR1f80 Base update required")

    def dispatch(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        if target != _ENTRY:
            if calls.call is None:
                raise UnresolvedReplayTaskRebuild(f"reached{target:x} is unavailable")
            return calls.call(target, args, data)
        if len(args) != 1 or data is not None:
            raise ValueError("malformed addressed Base update call")
        _validate(context, calls, *args)
        return _Base(
            context,
            calls,
            virtual_calls,
            logger_home_calls,
            position_fp_home_calls,
            rtti_home_calls,
            bind_local,
            profile,
        ).run(args[0])

    return ReplayTaskRebuildCalls(dispatch)
