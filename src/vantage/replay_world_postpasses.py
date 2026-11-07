"""Seven build54800 World/player postpass bodies over owned replay memory.

Source/ABI: world-update-postpass-children-source-v1. Actual notification,
lookup, resource, allocation and virtual children remain mandatory. Native
physical saves/cookies, faults/EH, incidental registers and concurrency are
outside the logical profile; no restored World or tick is supplied here.
"""

from __future__ import annotations

from dataclasses import dataclass

from .replay_binary32 import multiply_binary32, subtract_binary32
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

_U32, _U64 = (1 << 32) - 1, (1 << 64) - 1
_HOOK, _VISIBLE, _SEEN = 0x14151E9C0, 0x14114B470, 0x14115F240
_RESET, _TIMING, _RULES, _BITS = 0x141731F00, 0x140E27920, 0x1416938B0, 0x14188E440
_ARITIES = {_HOOK: 0, _VISIBLE: 1, _SEEN: 1, _RESET: 1, _TIMING: 2, _RULES: 1, _BITS: 1}
_MASK = 0x01FFFFFF01FFFFFF
_MASTER_A, _MASTER_B = 0x6A586EB28AC201FC, 0x0CF19788B2554E70


@dataclass(frozen=True, slots=True)
class ReplayWorldPostpassesProfile:
    """Explicit logical F0/D0/34/54h seeds; no inferred physical adjacency."""

    visibility: bytes
    seen: bytes
    timing: bytes
    rules: bytes

    def __post_init__(self) -> None:
        for value, size in (
            (self.visibility, 0xF0),
            (self.seen, 0xD0),
            (self.timing, 0x34),
            (self.rules, 0x54),
        ):
            if type(value) is not bytes or len(value) != size:
                raise ValueError("explicit F0/D0/34/54-hex-byte postpass seeds required")


def _raw(value: int | None, label: str) -> int:
    if value is None:
        raise ValueError(f"{label} requires its actual rawu64 annotation")
    _unsigned(value, 8, label)
    return value


def _eax(value: int | None, label: str) -> int:
    return _raw(value, label) & _U32


def _widen(word: int) -> int:
    """Low CVTPS2PD word, exact finite widening and source NaN quieting."""
    sign, exponent, fraction = (word & 0x80000000) << 32, word >> 23 & 255, word & 0x7FFFFF
    if exponent == 255:
        return sign | 0x7FF0000000000000 | (fraction << 29) | (1 << 51 if fraction else 0)
    if exponent:
        return sign | ((exponent + 896) << 52) | (fraction << 29)
    if not fraction:
        return sign
    top = fraction.bit_length() - 1
    return sign | ((top + 874) << 52) | ((fraction - (1 << top)) << (52 - top))


class _Postpasses:
    def __init__(
        self,
        context: ReplayTaskRebuildStorage,
        calls: ReplayTaskRebuildCalls,
        channels: tuple[ReplayTaskRebuildCalls, ...],
        bind_local: LocalBinding,
        profile: ReplayWorldPostpassesProfile,
    ) -> None:
        self.context, self.calls = context, calls
        (
            self.visibility,
            self.fog,
            self.player_event,
            self.resource,
            self.state_byte,
            self.rule_event,
        ) = channels
        self.bind_local, self.profile = bind_local, profile

    def r(self, address: int, width: int = 8) -> int:
        return _read(self.context, address, width)

    def w(self, address: int, width: int, value: int) -> None:
        _write(self.context, address, width, value)

    def invoke(self, channel: ReplayTaskRebuildCalls, target: int, *args: int) -> int | None:
        if channel.call is None:
            raise UnresolvedReplayTaskRebuild(f"reached{target:x} is unavailable")
        return channel.call(target, tuple(value & _U64 for value in args), None)

    def call(self, target: int, *args: int) -> int | None:
        return self.invoke(self.calls, target, *args)

    def frame(self, seed: bytes) -> _Frame:
        return _Frame(self.context, self.bind_local, seed)

    def decode(self, f: _Frame, home: int, word: int, first: int, second: int) -> int:
        f.w(home, 8, word)
        f.w(home, 8, f.r(home, 8) + first)
        f.w(home, 8, f.r(home, 8) + second)
        return f.r(home, 8)

    def master(self, f: _Frame, home: int, unit: int) -> int:
        return self.decode(f, home, self.r(unit + 0x10), -_MASTER_A, -_MASTER_B)

    def tile(self, f: _Frame, grid: int, x: int, y: int, home: int) -> int:
        product = y * self.r(grid + 0x10, 4) & _U32
        index = _signed((product + x) & _U32, 4)
        array = self.r(grid)
        f.w(home, 8, self.r(array + index * 8))
        return _raw(self.call(_BITS, f.h(home)), "tile mask RAX")

    def visible(self, manager: int) -> None:
        with self.frame(self.profile.visibility) as f:
            player = self.r(manager)
            row = self.r(manager + 0x10)
            world = self.r(player + 8)
            terrain = self.r(world + 0x98)
            grid = self.r(terrain + 0x5BC8)
            if _signed(self.r(manager + 0xC, 4), 4) <= 0:
                return
            counter, flag_index = 0, 0
            one = self.r(0x1436A0294, 4)
            while True:
                flags = self.r(manager + 0x18)
                held_y = self.r(row + 0xC, 4)
                if self.r(flags + flag_index, 1):
                    y = _cvtt(subtract_binary32(held_y, one))
                    x = _cvtt(subtract_binary32(self.r(row + 8, 4), one))
                    first = self.tile(f, grid, x, y, 0xD8)
                    x = _cvtt(self.r(row + 8, 4))
                    y = _cvtt(subtract_binary32(self.r(row + 0xC, 4), one))
                    second = self.tile(f, grid, x, y, 0xE0)
                    y = _cvtt(self.r(row + 0xC, 4))
                    x = _cvtt(subtract_binary32(self.r(row + 8, 4), one))
                    third = self.tile(f, grid, x, y, 0xE8)
                    y = _cvtt(self.r(row + 0xC, 4))
                    x = _cvtt(self.r(row + 8, 4))
                    current = first | second | third | self.tile(f, grid, x, y, 0x60)
                else:
                    x, y = _cvtt(self.r(row + 8, 4)), _cvtt(held_y)
                    current = self.tile(f, grid, x, y, 0x68)
                previous = self.r(row + 0x10)
                current &= _MASK
                if current != previous:
                    self.publish_visibility(f, row, current, previous)
                counter = (counter + 1) & _U32
                flag_index = (flag_index + 1) & _U64
                row = (row + 0x18) & _U64
                if not _signed(counter, 4) < _signed(self.r(manager + 0xC, 4), 4):
                    return

    def publish_visibility(self, f: _Frame, row: int, current: int, previous: int) -> None:
        unit = self.r(row)
        master = self.master(f, 0xD0, unit)
        kind = self.decode(f, 0xD0, self.r(master + 0x38), -0x50A06BCECEBEF905, 0x5B32AA7995D95916)
        master = self.master(f, 0xD0, unit)
        radius = self.r(master + 0x7C, 4)
        master = self.master(f, 0xD0, unit)
        owner = self.r(unit + 0x18)
        y = self.r(row + 0xC, 4)
        x = self.r(row + 8, 4)
        f.w(0x50, 8, unit + 0x4A8)
        owner_id = self.r(owner + 0x648, 4)
        f.w(0x48, 8, current)
        f.w(0x40, 8, previous)
        f.w(0x38, 4, _signed(kind & 0xFFFF, 2))
        receiver = self.r(0x1443C9920)
        f.w(0x30, 4, radius)
        height = self.r(master + 0x78, 4)
        identifier = self.r(unit + 8, 4)
        f.w(0x28, 4, height)
        f.w(0x20, 4, y)
        self.invoke(
            self.visibility,
            0x141357E10,
            receiver,
            identifier,
            owner_id,
            previous,
            x,
            *(f.h(offset) for offset in (0x20, 0x28, 0x30, 0x38, 0x40, 0x48, 0x50)),
        )
        self.w(row + 0x10, 8, current)
        self.w(unit + 0x4F0, 8, current)

    def seen(self, manager: int) -> None:
        with self.frame(self.profile.seen) as f:
            f.w(0xC8, 8, 0)
            if _signed(self.r(manager + 0xC, 4), 4) <= 0:
                return
            counter, offset, invalid = 0, 0, 0
            f.w(0xB8, 4, 0)
            while True:
                rows = self.r(manager + 0x10)
                pointer = self.r(rows + offset + 8)
                current = _raw(self.call(_BITS, pointer), "seen mask RAX") & _MASK
                f.w(0x50, 8, current)
                rows = self.r(manager + 0x10)
                if current != self.r(rows + offset + 0x10):
                    if self.r(rows + offset):
                        player = self.r(manager)
                        identifier = self.r(rows + offset + 0x18, 4)
                        world = self.r(player + 8)
                        raw_unit = self.call(0x141617DB0, world, identifier)
                        rows = self.r(manager + 0x10)
                        actual = self.r(rows + offset)
                        valid = _raw(raw_unit, "seen lookup RAX") == actual
                    else:
                        valid = False
                    if valid:
                        previous = self.r(rows + offset + 0x10)
                        lost = ((previous ^ current) >> 1) & (previous >> 1) & 0x7FFFFFFF
                        index = 1
                        while lost:
                            if lost & 1:
                                player = self.r(manager)
                                if self.r(player + 0x648, 4) != index:
                                    self.notify_seen(f, manager, offset, index)
                            index = (index + 1) & _U32
                            lost >>= 1
                        invalid = f.r(0xC8, 8)
                    else:
                        invalid = self.r(rows + offset)
                        f.w(0xC8, 8, invalid)
                    rows = self.r(manager + 0x10)
                    self.w(rows + offset + 0x10, 8, current)
                held_count = _signed(self.r(manager + 0xC, 4), 4)
                counter = (counter + 1) & _U32
                offset = (offset + 0x20) & _U64
                f.w(0xB8, 4, counter)
                if not _signed(counter, 4) < held_count:
                    break
            if invalid and held_count > 0:
                self.remove_seen(manager, invalid, held_count)

    def notify_seen(self, f: _Frame, manager: int, offset: int, index: int) -> None:
        player = self.r(manager)
        rows = self.r(manager + 0x10)
        world = self.r(player + 8)
        unit = self.r(rows + offset)
        raw_header = self.call(0x141603FF0, world)
        f.w(0xB0, 1, 1)
        begin = self.r(_raw(raw_header, "seen player header RAX"))
        other = self.r(begin + index * 16)
        system = self.r(other + 0x28)
        receiver = self.r(system + 0x798)
        target = self.r(self.r(receiver) + 0xF8)
        z = self.decode(f, 0xC0, self.r(unit + 0x180), 0x2B3719EF44DE99FF, 0x21D14A25ED7C802C)
        f.w(0x40, 8, z)
        x = self.decode(f, 0xC0, self.r(unit + 0x178), -0x61501AA6ECFD980A, 0x6C5EAB60B426DD28)
        f.w(0x48, 8, x)
        y = self.decode(f, 0xC0, self.r(unit + 0x170), -0x183CAC30D2441D0E, 0x4C3FBA69E4EA7FD1)
        player = self.r(manager)
        f.w(0xC0, 8, y)
        raw_other = self.call(0x141603F60, self.r(player + 8), index)
        z_word, x_word = f.r(0x40, 4), f.r(0x48, 4)
        other_arg = _raw(raw_other, "seen player RAX")
        y_word = f.r(0xC0, 4)
        f.w(0x30, 8, f.h(0xB0))
        f.w(0x28, 8, unit)
        f.w(0x20, 4, z_word)
        self.invoke(
            self.fog, target, receiver, other_arg, y_word, x_word, f.h(0x20), f.h(0x28), f.h(0x30)
        )
        player = self.r(manager)
        header = _raw(self.call(0x141603FF0, self.r(player + 8)), "seen current header RAX")
        begin = self.r(header)
        other = self.r(begin + index * 16)
        if _eax(self.call(0x14172AC80, other), "seen player type EAX"):
            player = self.r(manager)
            header = _raw(self.call(0x141603FF0, self.r(player + 8)), "seen event header RAX")
            begin = self.r(header)
            receiver = self.r(begin + index * 16)
            target = self.r(self.r(receiver) + 0x2F8)
            f.w(0x30, 4, 0)
            f.w(0x28, 4, 0)
            f.w(0x20, 4, self.r(unit + 8, 4))
            self.invoke(
                self.player_event,
                target,
                receiver,
                _U32,
                index,
                0x20D,
                f.h(0x20),
                f.h(0x28),
                f.h(0x30),
            )

    def remove_seen(self, manager: int, invalid: int, count: int) -> None:
        array = self.r(manager + 0x10)
        index = 0
        while self.r(array + index * 0x20) != invalid:
            index = (index + 1) & _U32
            if not _signed(index, 4) < count:
                return
        last = (count - 1) & _U32
        self.w(manager + 0xC, 4, last)
        if _signed(index, 4) < _signed(last, 4):
            destination = array + _signed(index, 4) * 0x20
            source = array + (count - 1) * 0x20
            self.w(destination, 16, self.r(source, 16))
            self.w(destination + 16, 16, self.r(source + 16, 16))
        for member, width in ((0, 8), (8, 8), (0x18, 4), (0x10, 8)):
            current = _signed(self.r(manager + 0xC, 4), 4)
            current_array = self.r(manager + 0x10)
            self.w(current_array + current * 0x20 + member, width, 0)

    def reset(self, subject: int) -> None:
        if self.r(subject + 0x10, 4):
            return
        old_count = self.r(subject + 0xC, 4)
        self.w(subject + 4, 8, 0)
        if not old_count:
            return
        if _signed(self.r(subject, 4), 4) > 0x200:
            self.call(0x142D6C270, self.r(subject + 0x68))
            self.w(subject, 4, 0x200)
            raw_allocation = self.call(0x142D6C268, 0x1000)
            count = _signed(self.r(subject, 4), 4)
            allocation = _raw(raw_allocation, "reset allocation RAX")
            self.w(subject + 0x68, 8, allocation)
            self.call(0x142D6E3B7, allocation, 0, count << 3)
        self.w(subject + 0xC, 4, 0)

    def timing(self, subject: int, incoming: int) -> None:
        with self.frame(self.profile.timing) as f:
            f.w(0x20, 4, incoming)
            for address, line, home in (
                (0x1443530F0, 0xF5A, 0x24),
                (0x144352EB0, 0xF5B, 0x28),
                (0x144353180, 0xF5C, 0x2C),
            ):
                raw = self.call(0x140903E40, address, 0x143265AB0, line)
                f.w(home, 4, _eax(raw, "timing sample EAX"))
            raw = self.call(0x140903E40, 0x144353210, 0x143265AB0, 0xF5D)
            receiver = self.r(subject + 0x390)
            f.w(0x30, 4, _eax(raw, "fourth timing EAX"))
            self.call(0x140E66530, receiver, f.h(0x20))

    def rules(self, world: int) -> None:
        with self.frame(self.profile.rules) as f:
            if _signed(self.r(world + 0x8E2, 2), 2) <= -1:
                return
            count = _eax(self.call(0x141603EF0, world), "rule count EAX")
            index = 1
            while _signed(index, 4) < _signed(count, 4):
                player = _raw(self.call(0x141603F60, world, index), "rule player RAX")
                if not self.r(player + 0x89, 1):
                    self.rule_player(f, world, player)
                index = (index + 1) & _U32
                count = _eax(self.call(0x141603EF0, world), "current rule count EAX")

    def rule_player(self, f: _Frame, world: int, player: int) -> None:
        rule = _signed(self.r(world + 0x8E2, 2), 2) & _U32
        raw_query = self.call(0x14111AC10, self.r(player + 0x18), rule)
        flags = self.r(world + 0x8EC, 2)
        if flags & 1 and not _eax(raw_query, "rule query EAX"):
            self.invoke(self.state_byte, 0x14170E660, player, 2, 255)
            return
        if not flags & 2:
            return
        positive = _signed(_eax(raw_query, "rule query EAX"), 4) > 0
        if not (not positive if flags & 4 else positive):
            return
        amount = multiply_binary32(self.r(world + 0x8E8, 4), self.r(world + 0x164, 4))
        vptr = self.r(player)
        resource = self.r(world + 0x8E4, 2)
        f.w(0x20, 1, 1)
        target = self.r(vptr + 0xF8)
        self.invoke(self.resource, target, player, resource, amount, 1, 255, f.h(0x20))
        if not _raw(self.call(0x141734F30, player), "rule predicate AL") & 255 and not _eax(
            self.call(0x14172AC80, player), "rule player type EAX"
        ):
            return
        raw_bus = self.call(0x140A69450)
        identifier = self.r(player + 0x648, 4)
        resource = _signed(self.r(world + 0x8E4, 2), 2) & _U32
        widened = _widen(amount)
        f.w(0x50, 4, identifier)
        bus = _raw(raw_bus, "rule bus RAX")
        f.w(0x20, 8, widened)
        self.invoke(self.rule_event, 0x140A635D0, bus, f.h(0x50), resource, 1, f.h(0x20))


def bind_replay_world_postpasses(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    *,
    visibility_calls: ReplayTaskRebuildCalls,
    fog_home_calls: ReplayTaskRebuildCalls,
    player_event_home_calls: ReplayTaskRebuildCalls,
    resource_home_calls: ReplayTaskRebuildCalls,
    state_byte_calls: ReplayTaskRebuildCalls,
    rule_event_home_calls: ReplayTaskRebuildCalls,
    bind_local: LocalBinding,
    profile: ReplayWorldPostpassesProfile,
    mxcsr: int,
) -> ReplayTaskRebuildCalls:
    """Own seven complete bodies; preserve actual reads, aliases and callbacks.

    Mixed-call annotations and live HOME addresses follow the source packet's
    api.json. They are prepared known operands, not closure of unprovided callee
    ABI. Unknown calls delegate unchanged. No backing, imports, loop cap,
    successful child or restored-world status is supplied. Masked1f80 required.
    """
    channels = (
        visibility_calls,
        fog_home_calls,
        player_event_home_calls,
        resource_home_calls,
        state_byte_calls,
        rule_event_home_calls,
    )
    for channel in (calls, *channels):
        _validate(context, channel)
    if (
        not callable(bind_local)
        or not isinstance(profile, ReplayWorldPostpassesProfile)
        or type(mxcsr) is not int
        or mxcsr != 0x1F80
    ):
        raise ValueError("actual postpass locals/profile and exact MXCSR1f80 required")

    def dispatch(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        if target not in _ARITIES:
            if calls.call is None:
                raise UnresolvedReplayTaskRebuild(f"reached{target:x} is unavailable")
            return calls.call(target, args, data)
        if len(args) != _ARITIES[target] or data is not None:
            raise ValueError("malformed addressed World postpass call")
        _validate(context, calls, *args)
        body = _Postpasses(context, bound, channels, bind_local, profile)
        if target == _BITS:
            return body.r(args[0])
        if target == _HOOK:
            root = body.r(0x144414BC0)
            if root:
                return body.call(0x1414F75E0, body.r(body.r(root + 0x18) + 0x1A8))
        elif target == _VISIBLE:
            body.visible(args[0])
        elif target == _SEEN:
            body.seen(args[0])
        elif target == _RESET:
            body.reset(args[0])
        elif target == _TIMING:
            body.timing(*args)
        else:
            body.rules(args[0])
        return None

    bound = ReplayTaskRebuildCalls(dispatch)
    return bound
