"""Whole build54800 Building141281600 update over explicit owned storage.

Source/API: building-object-update-source-v1,7363B/1682 assembly rows. Unit,
clock,top,clear and memmove remain delegated to existing owners. All reached
registration,member,resource,repair,graphics and production effects are required.
This does not restore a recording World or commit a complete game tick.
"""

from __future__ import annotations

from dataclasses import dataclass

from .replay_binary32 import (
    add_binary32,
    compare_binary32,
    divide_binary32,
    multiply_binary32,
    signed16_binary32,
    signed32_binary32,
    subtract_binary32,
)
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
from .replay_world_postpasses import _widen

_BUILDING, _UNIT, _TOP = 0x141281600, 0x1412BD4C0, 0x140B88AF0
_U32, _U64 = (1 << 32) - 1, (1 << 64) - 1
_MA, _MB = 0x6A586EB28AC201FC, 0x0CF19788B2554E70
_HX, _HA = 0x0F2A55F7A61DD00E, 0x147B5E081EC087D9
_MAX_A, _MAX_B = 0xD978539418047C54, 0xABAA7F7397F61E6C
_RA, _RB, _RC, _RD = (
    0x6AE24D3352F04511,
    0xC22D6B496D833977,
    0x042AC42976FCCEF5,
    0xA9834B738A7DD167,
)


@dataclass(frozen=True, slots=True)
class ReplayBuildingObjectUpdateProfile:
    """Explicit50h semantic view; native saves50..c7/return homes excluded."""

    building: bytes

    def __post_init__(self) -> None:
        if type(self.building) is not bytes or len(self.building) != 0x50:
            raise ValueError("explicit50-hex-byte Building update seed required")


def _raw(value: int | None, label: str) -> int:
    if value is None:
        raise ValueError(f"{label} requires actual rawu64 annotation")
    _unsigned(value, 8, label)
    return value


def _count12(begin: int, end: int) -> int:
    """Source signed64 IMUL high/SAR/sign adjustment on a wrapped span."""
    delta = _signed((end - begin) & _U64, 8)
    high = (delta * 0x2AAAAAAAAAAAAAAB) >> 64
    half = high >> 1
    return (half + ((half & _U64) >> 63)) & _U64


class _Building:
    def __init__(
        self,
        context: ReplayTaskRebuildStorage,
        calls: ReplayTaskRebuildCalls,
        channels: tuple[ReplayTaskRebuildCalls, ...],
        bind_local: LocalBinding,
        profile: ReplayBuildingObjectUpdateProfile,
    ) -> None:
        self.context, self.calls = context, calls
        (
            self.virtual,
            self.member,
            self.task,
            self.resource_calls,
            self.events,
            self.repair,
            self.rectangle,
        ) = channels
        self.bind_local, self.profile = bind_local, profile

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

    def pointer(self, target: int, *args: int) -> int:
        return _raw(self.call(target, *args), f"{target:x} RAX")

    def al(self, target: int, *args: int) -> int:
        return _raw(self.call(target, *args), f"{target:x} AL") & 255

    def vcall(self, obj: int, slot: int, *args: int) -> int | None:
        return self.invoke(self.virtual, self.r(self.r(obj) + slot), obj, *args)

    def finish_master(self, f: _Frame) -> int:
        f.w(0x40, 8, f.r(0x40, 8) - _MA)
        f.w(0x40, 8, f.r(0x40, 8) - _MB)
        return f.r(0x40, 8)

    def master(self, f: _Frame, obj: int) -> int:
        f.w(0x40, 8, self.r(obj + 0x10))
        return self.finish_master(f)

    def object_class(self, f: _Frame, obj: int) -> int:
        master = self.master(f, obj)
        f.w(0x40, 8, self.r(master + 0x38))
        f.w(0x40, 8, f.r(0x40, 8) - 0x50A06BCECEBEF905)
        f.w(0x40, 8, f.r(0x40, 8) + 0x5B32AA7995D95916)
        return f.r(0x40, 8) & 0xFFFF

    def kind_current_master(self, f: _Frame, master: int) -> int:
        f.w(0x40, 8, self.r(master + 0x18))
        f.w(0x40, 8, f.r(0x40, 8) ^ 0x349E37847AD69F19)
        f.w(0x40, 8, f.r(0x40, 8) - 0x47E37DFF0616CE4F)
        return f.r(0x40, 8) & 0xFFFF

    def kind(self, f: _Frame, obj: int) -> int:
        return self.kind_current_master(f, self.master(f, obj))

    def health(self, f: _Frame, obj: int) -> int:
        f.w(0x40, 8, self.r(obj + 0x130))
        f.w(0x40, 8, f.r(0x40, 8) ^ _HX)
        f.w(0x40, 8, f.r(0x40, 8) - _HA)
        return f.r(0x40, 8)

    def maximum(self, f: _Frame, master: int) -> int:
        f.w(0x40, 8, self.r(master + 0x68))
        f.w(0x40, 8, f.r(0x40, 8) ^ _MAX_A)
        f.w(0x40, 8, f.r(0x40, 8) ^ _MAX_B)
        return _signed(f.r(0x40, 8) & 0xFFFF, 2)

    def resource(self, f: _Frame, encoded: int) -> int:
        f.w(0x40, 8, encoded)
        f.w(0x40, 8, f.r(0x40, 8) ^ _RA)
        f.w(0x40, 8, f.r(0x40, 8) ^ _RB)
        f.w(0x40, 8, f.r(0x40, 8) - _RC)
        f.w(0x40, 8, f.r(0x40, 8) ^ _RD)
        return f.r(0x40, 8)

    def coordinate(self, f: _Frame, obj: int, member: int) -> int:
        first, second = (
            (0x183CAC30D2441D0E, 0x4C3FBA69E4EA7FD1)
            if member == 0x170
            else (0x61501AA6ECFD980A, 0x6C5EAB60B426DD28)
        )
        f.w(0x40, 8, self.r(obj + member))
        f.w(0x40, 8, f.r(0x40, 8) - first)
        f.w(0x40, 8, f.r(0x40, 8) + second)
        return f.r(0x40, 8)

    def register(self, obj: int) -> None:
        if self.r(obj + 0x18B, 1):
            tag = self.r(obj + 0x18A, 1)
            self.w(obj + 0x18B, 1, 0)
            self.w(obj + 0x189, 1, 1)
            owner = self.r(obj + 0x18)
            self.vcall(owner, 0x2E0, obj, 0, tag)
            owner = self.r(obj + 0x18)
            tag = self.r(obj + 0x18A, 1)
            self.vcall(owner, 0x2D8, obj, 1, tag)

    def detach_homes(self, f: _Frame) -> None:
        f.w(0x30, 1, 0)
        f.w(0x28, 1, 1)
        f.w(0x20, 8, 0)

    def detach(self, f: _Frame, obj: int, member: int, minus_one: int) -> None:
        self.invoke(
            self.member,
            0x1412A2170,
            obj,
            member,
            minus_one,
            minus_one,
            f.h(0x20),
            f.h(0x28),
            f.h(0x30),
        )

    def low_health(self, f: _Frame, obj: int, minus_one: int) -> None:
        master = self.master(f, obj)
        f.w(0x48, 8, self.health(f, obj))
        maximum = self.maximum(f, master)
        limit = multiply_binary32(signed16_binary32(maximum), self.r(0x1431FBFE0, 4))
        comparison = compare_binary32(limit, f.r(0x48, 4))
        if comparison is None or comparison < 0:
            return
        self.vcall(self.master(f, obj), 0x118, 1)
        container = self.r(obj + 0x150)
        if not container:
            return
        index = _signed((self.r(container + 8, 4) - 1) & _U32, 4)
        while index >= 0:
            container = self.r(obj + 0x150)
            self.detach_homes(f)
            member = self.r(self.r(container) + index * 8)
            self.detach(f, obj, member, minus_one)
            index -= 1
        container = self.r(obj + 0x150)
        index = _signed((self.r(container + 8, 4) - 1) & _U32, 4)
        while index >= 0:
            container = self.r(obj + 0x150)
            member = self.r(self.r(container) + index * 8)
            self.vcall(member, 0x1C0)
            self.vcall(member, 0xD8)
            index -= 1

    def task_delta(self, f: _Frame, obj: int) -> None:
        if not self.r(obj + 0x95C, 1) or self.r(obj + 0x188, 1) != 2:
            return
        task = self.pointer(_TOP, self.r(obj + 0x420))
        if not task:
            return
        resource = self.r(self.r(obj + 0x18) + 0x98)
        value = self.resource(f, self.r(resource + 0x768))
        amount = self.r(task + 0x44, 4)
        f.w(0x48, 8, value)
        amount = subtract_binary32(amount, f.r(0x48, 4))
        self.invoke(self.task, 0x140B67D10, task, amount)
        self.w(obj + 0x95C, 1, 0)

    def credit(self, f: _Frame, obj: int, index: int, amount: int, mask: int) -> None:
        owner = self.r(obj + 0x18)
        f.w(0x20, 1, 1)
        target = self.r(self.r(owner) + 0xF8)
        self.invoke(self.resource_calls, target, owner, index, amount, 1, mask, f.h(0x20))

    def resources(self, f: _Frame, obj: int, seconds: int) -> None:
        if self.kind(f, obj) != 0x68:
            return
        owner = self.r(obj + 0x18)
        if self.r(owner + 0x89, 1):
            return
        second_count = self.r(obj + 0x8D4, 4)
        first_count = self.r(obj + 0x8D0, 4)
        sixty = self.r(0x1436A02E0, 4)
        quantity = ((first_count + second_count * 2) * seconds) & _U32
        resource = self.r(owner + 0x98)
        f.w(0x48, 8, self.resource(f, self.r(resource + 0x708)))
        owner = self.r(obj + 0x18)
        first = f.r(0x48, 4)
        count = signed32_binary32(_signed(quantity, 4))
        resource = self.r(owner + 0x98)
        first = divide_binary32(first, sixty)
        f.w(0x48, 8, self.resource(f, self.r(resource + 0x840)))
        owner = self.r(obj + 0x18)
        resource = self.r(owner + 0x98)
        f.w(0x40, 8, self.r(resource + 0x848))
        f.w(0x40, 8, f.r(0x40, 8) ^ _RA)
        f.w(0x40, 8, f.r(0x40, 8) ^ _RB)
        second = f.r(0x48, 4)
        held = f.r(0x40, 8) - _RC
        first = multiply_binary32(first, count)
        f.w(0x40, 8, held)
        f.w(0x40, 8, f.r(0x40, 8) ^ _RD)
        f.w(0x48, 8, f.r(0x40, 8))
        owner = self.r(obj + 0x18)
        third = f.r(0x48, 4)
        third = divide_binary32(third, sixty)
        resource = self.r(owner + 0x98)
        f.w(0x40, 8, self.r(resource + 0x5F8))
        held = f.r(0x40, 8) ^ _RA
        second = divide_binary32(second, sixty)
        third = multiply_binary32(third, count)
        second = multiply_binary32(second, count)
        f.w(0x40, 8, held)
        held = f.r(0x40, 8) ^ _RB
        f.w(0x20, 1, 1)
        f.w(0x40, 8, held)
        f.w(0x40, 8, f.r(0x40, 8) - _RC)
        f.w(0x40, 8, f.r(0x40, 8) ^ _RD)
        value = f.r(0x40, 8)
        owner = self.r(obj + 0x18)
        f.w(0x48, 8, value)
        fourth = divide_binary32(f.r(0x48, 4), sixty)
        table = self.r(owner)
        fourth = multiply_binary32(fourth, count)
        self.invoke(
            self.resource_calls,
            self.r(table + 0xF8),
            owner,
            0,
            first,
            0xA9834B738A7DD101,
            _U64,
            f.h(0x20),
        )
        self.credit(f, obj, 1, second, _U64)
        self.credit(f, obj, 2, third, 255)
        self.credit(f, obj, 3, fourth, 255)
        for index, amount in enumerate((first, second, third, fourth)):
            bus = self.call(0x140A69450)
            owner = self.r(obj + 0x18)
            identifier = self.r(owner + 0x648, 4)
            f.w(0x40, 4, identifier)
            f.w(0x20, 8, _widen(amount))
            self.invoke(
                self.events,
                0x140A635D0,
                _raw(bus, "resource bus RAX"),
                f.h(0x40),
                index,
                1,
                f.h(0x20),
            )
        self.credit(f, obj, 100, fourth, 255)

    def expire_members(self, f: _Frame, obj: int, minus_one: int) -> None:
        container = self.r(obj + 0x150)
        count = self.r(container + 8, 4) if container else 0
        index = _signed((count - 1) & _U32, 4)
        while index >= 0:
            container = self.r(obj + 0x150)
            member = self.r(self.r(container) + index * 8)
            if self.r(self.master(f, member) + 8, 1) == 0x46:
                remaining = self.r(member + 0x628, 4)
                if _signed(remaining, 4) > 0:
                    if remaining == 1:
                        script = self.r(member + 0x1F0)
                        if script:
                            self.vcall(script, 0xB0, 1)
                        self.detach_homes(f)
                        self.detach(f, obj, member, minus_one)
                    else:
                        self.w(member + 0x628, 4, remaining - 1)
            index -= 1

    def repair_members(self, f: _Frame, obj: int) -> None:
        container = self.r(obj + 0x150)
        if not container or _signed(self.r(container + 8, 4), 4) <= 0:
            return
        enabled = compare_binary32(self.r(self.master(f, obj) + 0x460, 4), 0) == 1
        workers, index, offset = 0, 0, 0
        container = self.r(obj + 0x150)
        if _signed(self.r(container + 8, 4), 4) <= 0:
            return
        while True:
            member = self.r(self.r(container) + offset)
            if self.object_class(f, member) == 4:
                workers = (workers + 1) & _U32
            if enabled:
                maximum = self.maximum(f, self.master(f, member))
                f.w(0x48, 8, self.health(f, member))
                if compare_binary32(signed16_binary32(maximum), f.r(0x48, 4)) == 1:
                    if self.r(member + 0xF, 1) >= 0x50:
                        target = 0x1412C8D20
                    else:
                        target = self.r(self.r(member) + 0x120)
                    amount = self.r(self.master(f, obj) + 0x460, 4)
                    result = self.invoke(self.repair, target, member, amount)
                    if (
                        self.r(member + 0xF, 1) >= 0x46
                        and _raw(result, "member repair AL") & 255 == 1
                    ):
                        self.call(0x1412BAED0, member)
            container = self.r(obj + 0x150)
            index, offset = (index + 1) & _U32, (offset + 8) & _U64
            if _signed(index, 4) >= _signed(self.r(container + 8, 4), 4):
                break
        if _signed(workers, 4) <= 0:
            return
        amount = self.r(self.master(f, obj) + 0x464, 4)
        if compare_binary32(amount, 0) != 1:
            return
        f.w(0x48, 8, self.health(f, obj))
        maximum = self.maximum(f, self.master(f, obj))
        if compare_binary32(signed16_binary32(maximum), f.r(0x48, 4)) == 1:
            table = self.r(obj)
            count = signed32_binary32(_signed(workers, 4))
            target = self.r(table + 0x120)
            amount = multiply_binary32(count, self.r(self.master(f, obj) + 0x464, 4))
            self.invoke(self.repair, target, obj, amount)

    def regular(self, f: _Frame, obj: int, minus_one: int) -> None:
        self.call(0x14127CC00, obj)
        world = self.r(self.r(obj + 0x18) + 8)
        time = self.call(0x1416041F0, world)
        previous = self.r(obj + 0x890, 4)
        elapsed = ((_raw(time, "Building clock EAX") & _U32) - previous) & _U32
        seconds = ((elapsed * 0x10624DD3) >> 32) >> 6
        if _signed(seconds, 4) <= 0:
            return
        self.w(obj + 0x890, 4, previous + seconds * 1000)
        value = self.r(obj + 0x165, 1)
        if value:
            self.w(obj + 0x165, 1, value - 1)
        self.resources(f, obj, seconds)
        self.expire_members(f, obj, minus_one)
        self.repair_members(f, obj)

    def records(self, f: _Frame, obj: int) -> tuple[int, int]:
        master = self.master(f, obj)
        begin = self.r(master + 0x338)
        end = self.r(master + 0x340)
        return begin, _count12(begin, end)

    def finish_rectangle(
        self, f: _Frame, obj: int, min_x: int, min_y: int, max_x: int, max_y_word: int
    ) -> None:
        owner = self.r(obj + 0x18)
        max_y = _cvtt(max_y_word)
        f.w(0x28, 1, 0)
        world = self.r(owner + 8)
        terrain = self.r(world + 0x98)
        f.w(0x20, 4, max_y)
        self.invoke(self.rectangle, 0x141046E50, terrain, min_x, min_y, max_x, f.h(0x20), f.h(0x28))

    def rectangle_common(self, f: _Frame, obj: int, encoded: int) -> None:
        """The plain graphic routes2500/2de0 share this read/store sequence."""
        f.w(0x40, 8, encoded)
        master = self.finish_master(f)
        f.w(0x48, 8, self.coordinate(f, obj, 0x170))
        encoded = self.r(obj + 0x10)
        left = subtract_binary32(f.r(0x48, 4), self.r(master + 0x78, 4))
        f.w(0x40, 8, encoded)
        f.w(0x40, 8, f.r(0x40, 8) - _MA)
        held = f.r(0x40, 8)
        left = subtract_binary32(left, self.r(0x1436A0294, 4))
        f.w(0x40, 8, held - _MB)
        master = f.r(0x40, 8)
        f.w(0x48, 8, self.coordinate(f, obj, 0x178))
        encoded = self.r(obj + 0x10)
        min_x = _cvtt(left)
        lower = subtract_binary32(f.r(0x48, 4), self.r(master + 0x7C, 4))
        f.w(0x40, 8, encoded)
        f.w(0x40, 8, f.r(0x40, 8) - _MA)
        held = f.r(0x40, 8)
        lower = subtract_binary32(lower, self.r(0x1436A0294, 4))
        f.w(0x40, 8, held - _MB)
        master = f.r(0x40, 8)
        f.w(0x48, 8, self.coordinate(f, obj, 0x170))
        encoded_y = self.r(obj + 0x178)
        min_y = _cvtt(lower)
        right = add_binary32(f.r(0x48, 4), self.r(master + 0x78, 4))
        f.w(0x40, 8, encoded_y)
        f.w(0x40, 8, f.r(0x40, 8) - 0x61501AA6ECFD980A)
        f.w(0x40, 8, f.r(0x40, 8) + 0x6C5EAB60B426DD28)
        max_x = _cvtt(right)
        f.w(0x48, 8, f.r(0x40, 8))
        encoded = self.r(obj + 0x10)
        upper = f.r(0x48, 4)
        f.w(0x40, 8, encoded)
        master = self.finish_master(f)
        upper = add_binary32(upper, self.r(master + 0x7C, 4))
        self.finish_rectangle(f, obj, min_x, min_y, max_x, upper)

    def rectangle_excluded_animation(self, f: _Frame, obj: int, encoded: int) -> None:
        """Source3031 holds the fourth master before its final Y decode."""
        f.w(0x40, 8, encoded)
        master = self.finish_master(f)
        f.w(0x48, 8, self.coordinate(f, obj, 0x170))
        encoded = self.r(obj + 0x10)
        left = subtract_binary32(f.r(0x48, 4), self.r(master + 0x78, 4))
        f.w(0x40, 8, encoded)
        f.w(0x40, 8, f.r(0x40, 8) - _MA)
        held = f.r(0x40, 8)
        left = subtract_binary32(left, self.r(0x1436A0294, 4))
        f.w(0x40, 8, held - _MB)
        master = f.r(0x40, 8)
        f.w(0x48, 8, self.coordinate(f, obj, 0x178))
        encoded = self.r(obj + 0x10)
        min_x = _cvtt(left)
        lower = subtract_binary32(f.r(0x48, 4), self.r(master + 0x7C, 4))
        f.w(0x40, 8, encoded)
        f.w(0x40, 8, f.r(0x40, 8) - _MA)
        held = f.r(0x40, 8)
        lower = subtract_binary32(lower, self.r(0x1436A0294, 4))
        f.w(0x40, 8, held - _MB)
        master = f.r(0x40, 8)
        f.w(0x48, 8, self.coordinate(f, obj, 0x170))
        encoded = self.r(obj + 0x10)
        min_y = _cvtt(lower)
        right = add_binary32(f.r(0x48, 4), self.r(master + 0x78, 4))
        f.w(0x40, 8, encoded)
        max_x = _cvtt(right)
        master = self.finish_master(f)
        f.w(0x48, 8, self.coordinate(f, obj, 0x178))
        upper = add_binary32(f.r(0x48, 4), self.r(master + 0x7C, 4))
        self.finish_rectangle(f, obj, min_x, min_y, max_x, upper)

    def rectangle_animation(self, f: _Frame, obj: int, encoded: int) -> None:
        """Source287c has a distinct live coordinate/master sampling order."""
        f.w(0x40, 8, encoded)
        master = self.finish_master(f)
        f.w(0x48, 8, self.coordinate(f, obj, 0x170))
        encoded_y = self.r(obj + 0x178)
        left = subtract_binary32(f.r(0x48, 4), self.r(master + 0x78, 4))
        f.w(0x40, 8, encoded_y)
        f.w(0x40, 8, f.r(0x40, 8) - 0x61501AA6ECFD980A)
        held = f.r(0x40, 8)
        left = subtract_binary32(left, self.r(0x1436A0294, 4))
        f.w(0x40, 8, held + 0x6C5EAB60B426DD28)
        f.w(0x48, 8, f.r(0x40, 8))
        master = self.master(f, obj)
        min_x = _cvtt(left)
        lower = subtract_binary32(f.r(0x48, 4), self.r(master + 0x7C, 4))
        encoded = self.r(obj + 0x10)
        f.w(0x40, 8, encoded)
        f.w(0x40, 8, f.r(0x40, 8) - _MA)
        held = f.r(0x40, 8)
        lower = subtract_binary32(lower, self.r(0x1436A0294, 4))
        f.w(0x40, 8, held - _MB)
        master = f.r(0x40, 8)
        f.w(0x48, 8, self.coordinate(f, obj, 0x170))
        encoded = self.r(obj + 0x10)
        min_y = _cvtt(lower)
        right = add_binary32(f.r(0x48, 4), self.r(master + 0x78, 4))
        f.w(0x40, 8, encoded)
        max_x = _cvtt(right)
        master = self.finish_master(f)
        f.w(0x48, 8, self.coordinate(f, obj, 0x178))
        upper = add_binary32(f.r(0x48, 4), self.r(master + 0x7C, 4))
        self.finish_rectangle(f, obj, min_x, min_y, max_x, upper)

    def graphic_progress(self, f: _Frame, obj: int, excluded: bool) -> None:
        if not excluded and not self.r(obj + 0x20):
            return
        master = self.master(f, obj)
        graphic = self.r(obj + 0x20)
        count = _signed(self.r(graphic + 0xA, 2), 2)
        value = multiply_binary32(signed16_binary32(count), self.r(obj + 0x900, 4))
        denominator = _signed(
            _raw(self.call(0x140BB9290, master, 0), "graphic threshold AX") & 0xFFFF, 2
        )
        value = divide_binary32(value, signed16_binary32(denominator))
        stage = _cvtt(value) & 255
        if stage >= count or stage == self.r(obj + 0xE, 1):
            return
        encoded = self.r(obj + 0x10)
        self.w(obj + 0xE, 1, stage)
        self.rectangle_common(f, obj, encoded)

    def animation_progress(self, f: _Frame, obj: int, excluded: bool) -> None:
        if not excluded and (not self.r(obj + 0x28) or not self.r(obj + 0x20)):
            return
        master = self.master(f, obj)
        graphic = self.r(obj + 0x20)
        count = _signed(self.r(graphic + 8, 2), 2)
        value = multiply_binary32(signed16_binary32(count), self.r(obj + 0x900, 4))
        denominator = _signed(
            _raw(self.call(0x140BB9290, master, 0), "animation threshold AX") & 0xFFFF, 2
        )
        stage = _cvtt(divide_binary32(value, signed16_binary32(denominator))) & 255
        if stage >= count:
            return
        animation = self.r(obj + 0x28)
        old = _raw(self.vcall(animation, 8, graphic), "animation stage AX") & 0xFFFF
        if stage == _signed(old, 2):
            return
        animation = self.r(obj + 0x28)
        self.vcall(animation, 0x28, self.r(obj + 0x20), stage)
        encoded = self.r(obj + 0x10)
        if excluded:
            self.rectangle_excluded_animation(f, obj, encoded)
        else:
            self.rectangle_animation(f, obj, encoded)

    def staged_progress(self, f: _Frame, obj: int) -> None:
        master = self.master(f, obj)
        value = multiply_binary32(self.r(obj + 0x900, 4), self.r(0x1431FF5B8, 4))
        denominator = _signed(
            _raw(self.call(0x140BB9290, master, 0), "staged threshold AX") & 0xFFFF, 2
        )
        stage = _cvtt(divide_binary32(value, signed16_binary32(denominator))) & 255
        encoded = self.r(obj + 0x10)
        f.w(0x40, 8, encoded)
        stage = min(stage, 2)
        kind = self.kind_current_master(f, self.finish_master(f))
        if kind == 0x32:
            byte = 0x1D + stage
        elif self.r(obj + 0x980, 1):
            byte = 0x41 + stage
        else:
            byte = self.r(self.master(f, obj) + 0x428, 1) + 2 + stage
        self.call(0x141286D70, obj, byte & 255)

    def construction(self, f: _Frame, obj: int, excluded: bool) -> None:
        begin, count = self.records(f, obj)
        if count and _signed(self.r(begin + 2, 2), 2) > 0:
            if excluded and (not self.r(obj + 0x28) or not self.r(obj + 0x20)):
                return
            kind = self.kind(f, obj) if not excluded else 0
            special = self.object_class(f, obj) == 0x1B or self.object_class(f, obj) == 0x43
            if special:
                self.animation_progress(f, obj, excluded)
            elif not excluded and kind in (0x32, 0x4A3, 0x761):
                self.staged_progress(f, obj)
            else:
                self.graphic_progress(f, obj, excluded)

    def complete_construction(self, f: _Frame, obj: int, excluded: bool) -> None:
        begin, count = self.records(f, obj)
        threshold = _signed(self.r(begin + 2, 2), 2) if count else 0
        value = self.r(obj + 0x900, 4)
        comparison = compare_binary32(value, signed16_binary32(threshold))
        if comparison is None or comparison < 0:
            return
        if excluded:
            if self.r(obj + 0x188, 1) != 0:
                return
        elif self.r(obj + 0x868):
            return
        self.vcall(obj, 0xA8, 2)

    def aggregate(self, f: _Frame, obj: int) -> None:
        kind = self.kind(f, obj)
        if kind not in (0x769, 0x765):
            return
        begin = self.r(obj + 0x828)
        end = self.r(obj + 0x830)
        count = _signed((end - begin) & _U64, 8) >> 2
        total, index, offset = 0, 0, 0
        if count:
            while True:
                owner = self.r(obj + 0x18)
                identifier = self.r(begin + offset, 4)
                world = self.r(owner + 8)
                member = self.pointer(0x141617DB0, world, identifier)
                if member:
                    total = add_binary32(total, self.r(member + 0x168, 4))
                else:
                    begin = self.r(obj + 0x828)
                    end = self.r(obj + 0x830)
                    destination = (begin + _signed(index, 4) * 4) & _U64
                    source = (destination + 4) & _U64
                    self.call(0x142D6E3DB, destination, source, (end - source) & _U64)
                    self.w(obj + 0x830, 8, self.r(obj + 0x830) - 4)
                begin = self.r(obj + 0x828)
                index, offset = (index + 1) & _U32, (offset + 4) & _U64
                end = self.r(obj + 0x830)
                count = (_signed((end - begin) & _U64, 8) >> 2) & _U64
                if (_signed(index, 4) & _U64) >= count:
                    break
        stack = self.r(obj + 0x420)
        self.w(obj + 0x168, 4, 0)
        action = self.pointer(_TOP, stack)
        if action:
            self.invoke(self.task, 0x140B67D10, action, total)

    def production(self, obj: int) -> int:
        raw_parent = self.call(_UNIT, obj)
        state = self.r(obj + 0x188, 1)
        parent = _raw(raw_parent, "Unit AL") & 255
        queue = self.r(obj + 0x850)
        if state > 2:
            if self.r(queue + 0x10):
                self.call(0x140B88A20, queue)
            self.call(0x141288160, obj)
        else:
            result = self.call(0x140BB83E0, queue)
            self.w(obj + 0x84D, 1, _raw(result, "production AL") & 255)
            self.call(0x1412A2C70, obj)
        return parent

    def update(self, obj: int) -> int | None:
        if self.r(obj + 0x948, 1):
            self.register(obj)
            return 0
        state_two = self.r(obj + 0x188, 1) == 2
        minus_one = self.r(0x1431B7520, 4)
        with _Frame(self.context, self.bind_local, self.profile.building) as f:
            if state_two:
                self.low_health(f, obj, minus_one)
            self.task_delta(f, obj)
            excluded = (
                self.object_class(f, obj) == 0x1B
                or self.object_class(f, obj) == 0x43
                or self.kind(f, obj) == 0x46
            )
            if excluded:
                if self.r(obj + 0x188, 1) == 0:
                    self.construction(f, obj, True)
                self.complete_construction(f, obj, True)
                return self.call(_UNIT, obj)
            for member in (0x868, 0x870, 0x878, 0x880, 0x888):
                pointer = self.r(obj + member)
                if pointer and self.r(pointer + 0x188, 1) >= 7:
                    self.w(obj + member, 8, 0)
            state = self.r(obj + 0x188, 1)
            if state == 0:
                self.construction(f, obj, False)
                self.complete_construction(f, obj, False)
            elif state == 2:
                self.regular(f, obj, minus_one)
            elif state == 7:
                self.vcall(self.master(f, obj), 0x118, 0)
            parent = self.production(obj)
            self.aggregate(f, obj)
            return parent


def bind_replay_building_object_update(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    *,
    virtual_calls: ReplayTaskRebuildCalls,
    member_fp_home_calls: ReplayTaskRebuildCalls,
    task_fp_calls: ReplayTaskRebuildCalls,
    resource_fp_home_calls: ReplayTaskRebuildCalls,
    resource_event_home_calls: ReplayTaskRebuildCalls,
    repair_fp_calls: ReplayTaskRebuildCalls,
    rectangle_home_calls: ReplayTaskRebuildCalls,
    bind_local: LocalBinding,
    profile: ReplayBuildingObjectUpdateProfile,
    mxcsr: int,
) -> ReplayTaskRebuildCalls:
    """Bind the complete Building body with current storage and real effects.

    Raw FP/partial GP/home annotations follow the frozen source API. Native
    saves/physicalstack,FPstatus/upperlanes,faults/EH andconcurrency are excluded.
    Unknown arguments,payloads and returned identities pass through unchanged.
    """
    channels = (
        virtual_calls,
        member_fp_home_calls,
        task_fp_calls,
        resource_fp_home_calls,
        resource_event_home_calls,
        repair_fp_calls,
        rectangle_home_calls,
    )
    for channel in (calls, *channels):
        _validate(context, channel)
    if (
        not callable(bind_local)
        or not isinstance(profile, ReplayBuildingObjectUpdateProfile)
        or type(mxcsr) is not int
        or mxcsr != 0x1F80
    ):
        raise ValueError("actual locals/profile and exact MXCSR1f80 Building update required")

    def dispatch(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        if target != _BUILDING:
            if calls.call is None:
                raise UnresolvedReplayTaskRebuild(f"reached{target:x} is unavailable")
            return calls.call(target, args, data)
        if len(args) != 1 or data is not None:
            raise ValueError("malformed addressed Building update call")
        _validate(context, calls, *args)
        return _Building(context, calls, channels, bind_local, profile).update(args[0])

    return ReplayTaskRebuildCalls(dispatch)
