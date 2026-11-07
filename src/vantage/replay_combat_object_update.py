"""Five complete build54800 Combat update/getter bodies over owned storage.

Source/API: combat-object-update-source-v1,4691B/1020 assembly rows,including
the live-home addendum. Action,clocks,mask/top and player getters are delegated
to their existing owners; all other reached effects are required capabilities.
This does not restore a recording World or commit a complete game tick.
"""

from __future__ import annotations

from dataclasses import dataclass

from .replay_binary32 import (
    add_binary32,
    compare_binary32,
    multiply_binary32,
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

_COMBAT, _HAS, _OBSERVER, _SELECTED, _ELAPSED = (
    0x14114C3A0,
    0x140B88B30,
    0x140D6AED0,
    0x141608320,
    0x141604210,
)
_ARITIES = {_COMBAT: 1, _HAS: 1, _OBSERVER: 1, _SELECTED: 2, _ELAPSED: 2}
_U32, _U64, _MASK = (1 << 32) - 1, (1 << 64) - 1, 0x01FFFFFF01FFFFFF
_MA, _MB = 0x6A586EB28AC201FC, 0x0CF19788B2554E70
_GAME, _CLOCK, _DEBUG, _LOG = 0x144353698, 0x1416041F0, 0x14435505B, 0x14101ADB0


@dataclass(frozen=True, slots=True)
class ReplayCombatObjectUpdateProfile:
    """Explicit120h semantic prefix; cookie120 and saved FP lanes excluded."""

    combat: bytes

    def __post_init__(self) -> None:
        if type(self.combat) is not bytes or len(self.combat) != 0x120:
            raise ValueError("explicit120-hex-byte Combat update seed required")


def _raw(value: int | None, label: str) -> int:
    if value is None:
        raise ValueError(f"{label} requires actual rawu64 annotation")
    _unsigned(value, 8, label)
    return value


def _eax(value: int | None, label: str) -> int:
    return _raw(value, label) & _U32


class _Combat:
    def __init__(
        self,
        context: ReplayTaskRebuildStorage,
        calls: ReplayTaskRebuildCalls,
        channels: tuple[ReplayTaskRebuildCalls, ...],
        bind_local: LocalBinding,
        profile: ReplayCombatObjectUpdateProfile,
    ) -> None:
        self.context, self.calls = context, calls
        (self.virtual, self.logger, self.config, self.virtual_home, self.visibility) = channels
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

    def eax(self, target: int, *args: int) -> int:
        return _eax(self.call(target, *args), f"{target:x} EAX")

    def al(self, target: int, *args: int) -> int:
        return _raw(self.call(target, *args), f"{target:x} AL") & 255

    def vcall(self, obj: int, slot: int, *args: int) -> int | None:
        return self.invoke(self.virtual, self.r(self.r(obj) + slot), obj, *args)

    def world(self, obj: int) -> int:
        return self.r(self.r(obj + 0x18) + 8)

    def game_call(self, target: int) -> int | None:
        return self.call(target, self.r(_GAME))

    def decode(self, f: _Frame, home: int, value: int, first: int, second: int) -> int:
        f.w(home, 8, value)
        f.w(home, 8, f.r(home, 8) + first)
        f.w(home, 8, f.r(home, 8) + second)
        return f.r(home, 8)

    def master(self, f: _Frame, obj: int, home: int = 0xB8) -> int:
        return self.decode(f, home, self.r(obj + 0x10), -_MA, -_MB)

    def kind(self, f: _Frame, obj: int, home: int) -> int:
        master = self.master(f, obj, home)
        f.w(home, 8, self.r(master + 0x18))
        f.w(home, 8, f.r(home, 8) ^ 0x349E37847AD69F19)
        f.w(home, 8, f.r(home, 8) - 0x47E37DFF0616CE4F)
        return f.r(home, 8)

    def coordinate(self, f: _Frame, obj: int, member: int, home: int) -> int:
        first, second = {
            0x170: (-0x183CAC30D2441D0E, 0x4C3FBA69E4EA7FD1),
            0x178: (-0x61501AA6ECFD980A, 0x6C5EAB60B426DD28),
            0x180: (0x2B3719EF44DE99FF, 0x21D14A25ED7C802C),
        }[member]
        return self.decode(f, home, self.r(obj + member), first, second)

    def log(self, f: _Frame, text: int, count: int) -> None:
        self.invoke(self.logger, _LOG, self.r(0x144355068), 0x23, text, count, f.h(0x20))

    def initial(self, f: _Frame, obj: int) -> int:
        f.w(0xB8, 4, 0)
        debug = self.r(_DEBUG, 1)
        if debug >= 1:
            f.w(0x20, 8, 0)
            self.log(f, 0x1432A7D00, 0)
            debug = self.r(_DEBUG, 1)
        graphic = self.r(obj + 0x20)
        rate = self.r(graphic + 0xC, 4) if graphic else self.r(0x1432A85D8, 4)
        if debug >= 1:
            f.w(0x70, 4, 10)
            f.w(0x68, 4, rate)
            f.w(0xD0, 4, 10)
            f.w(0xC8, 4, self.r(obj + 0x350, 4))
            f.w(0xB8, 8, f.h(0xC8))
            f.w(0xC0, 8, f.h(0x68))
            f.w(0x20, 8, f.h(0xB8))
            self.log(f, 0x1432A7D20, 2)
        previous_state = self.r(obj + 0x188, 1)
        f.w(0x61, 1, previous_state)
        time = self.call(_CLOCK, self.world(obj))
        f.w(0x68, 8, self.coordinate(f, obj, 0x180, 0xB8))
        f.w(0xC8, 8, self.coordinate(f, obj, 0x178, 0xB8))
        f.w(0xB8, 8, self.coordinate(f, obj, 0x170, 0xB8))
        if self.r(_DEBUG, 1) >= 1:
            f.w(0x80, 4, 7)
            f.w(0x78, 4, _eax(time, "initial diagnostic clock EAX"))
            f.w(0xA0, 4, 10)
            f.w(0x98, 4, f.r(0x68, 4))
            f.w(0x90, 4, 10)
            f.w(0x88, 4, f.r(0xC8, 4))
            f.w(0xB0, 4, 10)
            f.w(0xA8, 4, f.r(0xB8, 4))
            f.w(0x70, 4, 5)
            f.w(0x68, 1, self.r(obj + 0x188, 1))
            f.w(0xD0, 4, 2)
            f.w(0xC8, 4, self.r(obj + 8, 4))
            for home, node in (
                (0xF0, 0xC8),
                (0xF8, 0x68),
                (0x100, 0xA8),
                (0x108, 0x88),
                (0x110, 0x98),
                (0x118, 0x78),
            ):
                f.w(home, 8, f.h(node))
            f.w(0x20, 8, f.h(0xF0))
            self.log(f, 0x1432A7D58, 6)
        return previous_state

    def cooldown(self, obj: int) -> None:
        remaining = self.r(obj + 0x514, 4)
        if compare_binary32(remaining, 0) == 1:
            elapsed = self.r(self.world(obj) + 0x164, 4)
            amount = multiply_binary32(elapsed, self.r(obj + 0x418, 4))
            remaining = subtract_binary32(remaining, amount)
            self.w(obj + 0x514, 4, remaining)
            if compare_binary32(0, remaining) == 1:
                self.w(obj + 0x514, 4, 0)
        time = self.call(_CLOCK, self.world(obj))
        expiry = _eax(self.vcall(obj, 0x268), "virtual268 EAX")
        if expiry and _eax(time, "expiry clock EAX") > expiry:
            if self.r(obj + 0xF, 1) >= 0x46:
                self.w(obj + 0x68C, 1, 0)
            self.vcall(obj, 0x260, 0)

    def expire_master(self, f: _Frame, obj: int) -> None:
        if not self.r(obj + 0x50C, 4):
            return
        time = self.game_call(0x140D6AD50)
        start = self.r(obj + 0x510, 4)
        elapsed = (_eax(time, "master expiry time EAX") - start) & _U32
        if elapsed < self.r(obj + 0x50C, 4) or not self.r(obj + 0x500):
            return
        master = self.master(f, obj)
        if self.r(obj + 0x500) == master or not self.r(obj + 0x50C, 4):
            return
        start = self.r(obj + 0x510, 4)
        time = self.game_call(0x140D6AD50)
        elapsed = (_eax(time, "master repeated time EAX") - start) & _U32
        if elapsed < self.r(obj + 0x50C, 4):
            return
        world = self.game_call(0x140D6ACC0)
        identifier = self.r(obj + 0x210, 4)
        group = self.pointer(0x141604060, _raw(world, "master group World RAX"), identifier)
        if group:
            self.call(0x1410F6800, group, self.r(obj + 8, 4), _U32, 0)
        old = self.r(obj + 0x500)
        self.w(obj + 0x500, 8, 0)
        self.vcall(obj, 0x98, old, 1)
        if group:
            self.call(0x1410D3AB0, group, self.r(obj + 8, 4), _U32, 0)
            self.call(0x14110DF30, group, self.r(obj + 8, 4))
        if self.al(_HAS, self.r(obj + 0x420)):
            action = self.pointer(0x140B88AF0, self.r(obj + 0x420))
            self.vcall(action, 0x28, 0)

    def status_log(self, f: _Frame, obj: int, time: int | None, text: int) -> None:
        f.w(0x90, 4, 10)
        f.w(0x88, 4, self.r(obj + 0x168, 4))
        f.w(0xA0, 4, 7)
        f.w(0x98, 4, _eax(time, "status clock EAX"))
        f.w(0x80, 4, 5)
        f.w(0x78, 1, self.r(obj + 0x188, 1))
        for home, node in ((0xD8, 0x78), (0xE0, 0x98), (0xE8, 0x88)):
            f.w(home, 8, f.h(node))
        f.w(0x20, 8, f.h(0xD8))
        self.log(f, text, 3)

    def grid(self, obj: int) -> int:
        return self.r(self.r(self.world(obj) + 0x98) + 0x5BC8)

    def tile(self, f: _Frame, grid: int, x: int, y: int) -> int:
        row = _cvtt(y) * self.r(grid + 0x10, 4)
        index = _signed((row + _cvtt(x)) & _U32, 4)
        cell = self.r(self.r(grid) + index * 8)
        f.w(0xC8, 8, cell)
        return self.pointer(0x14188E440, f.h(0xC8))

    def visibility_mask(self, f: _Frame, obj: int, previous_state: int) -> int:
        master = self.master(f, obj)
        other = self.r(obj + 0x868) if self.r(master + 8, 1) == 0x50 else 0
        other_path = bool(other) and self.r(obj + 0x188, 1) < 7
        source = other if other_path else obj
        f.w(0xC8, 8, self.coordinate(f, source, 0x170, 0xB8))
        x = f.r(0xC8, 4)
        f.w(0xC8, 8, self.coordinate(f, source, 0x178, 0xB8))
        y = f.r(0xC8, 4)
        old = self.r(obj + 0x4F0)
        if not other_path:
            f.w(0x68, 8, old)
        mask = self.tile(f, self.grid(obj), x, y) & _MASK
        self.w(obj + 0x4F0, 8, mask)
        footprint = self.r(source + 0x4FC, 1)
        if footprint:
            resource = self.r(self.world(obj) + 0x98)
            offsets = self.r(self.r(resource + 0x5BA8) + footprint * 8 - 8)
            if other_path:
                count = _signed(self.r(offsets, 4), 4)
                for index in range(1, count + 1):
                    grid = self.grid(obj)
                    yy = add_binary32(
                        signed32_binary32(_signed(self.r(offsets + index * 8 + 4, 4), 4)), y
                    )
                    row = _cvtt(yy) * self.r(grid + 0x10, 4)
                    xx = add_binary32(
                        signed32_binary32(_signed(self.r(offsets + index * 8, 4), 4)), x
                    )
                    cell_index = _signed((row + _cvtt(xx)) & _U32, 4)
                    cell = self.r(self.r(grid) + cell_index * 8)
                    f.w(0xC8, 8, cell)
                    mask = (self.pointer(0x14188E440, f.h(0xC8)) & _MASK) | mask
                    self.w(obj + 0x4F0, 8, mask)
            else:
                grid = self.r(resource + 0x5BC8)
                height, width = self.r(grid + 0x14, 4), self.r(grid + 0x10, 4)
                count = _signed(self.r(offsets, 4), 4)
                for index in range(1, count + 1):
                    xx = add_binary32(
                        signed32_binary32(_signed(self.r(offsets + index * 8, 4), 4)), x
                    )
                    yy = add_binary32(
                        signed32_binary32(_signed(self.r(offsets + index * 8 + 4, 4), 4)), y
                    )
                    if compare_binary32(0, xx) == 1 or compare_binary32(0, yy) == 1:
                        continue
                    limit = signed32_binary32(_signed(width, 4))
                    comparison = compare_binary32(xx, limit)
                    if comparison is not None and comparison >= 0:
                        continue
                    limit = signed32_binary32(_signed(height, 4))
                    comparison = compare_binary32(yy, limit)
                    if comparison is not None and comparison >= 0:
                        continue
                    held = self.r(obj + 0x4F0)
                    mask = (self.tile(f, self.grid(obj), xx, yy) & _MASK) | held
                    self.w(obj + 0x4F0, 8, mask)
        if not other_path:
            old = f.r(0x68, 8)
        if other_path or footprint:
            previous_state = f.r(0x61, 1)
        current = self.r(obj + 0x4F0)
        if current != old:
            self.publish(f, obj, x, y, old, current)
            if self.r(obj + 0x51C, 1) == 1:
                self.owners(f, obj, current)
        return previous_state

    def publish(self, f: _Frame, obj: int, x: int, y: int, old: int, current: int) -> None:
        master = self.master(f, obj)
        kind = self.decode(f, 0xB8, self.r(master + 0x38), -0x50A06BCECEBEF905, 0x5B32AA7995D95916)
        master = self.master(f, obj)
        radius = self.r(master + 0x7C, 4)
        master = self.master(f, obj)
        owner = self.r(obj + 0x18)
        f.w(0x50, 8, obj + 0x4A8)
        f.w(0x48, 8, current)
        f.w(0x40, 8, old)
        f.w(0x38, 4, _signed(kind & 0xFFFF, 2))
        f.w(0x30, 4, radius)
        f.w(0x28, 4, self.r(master + 0x78, 4))
        f.w(0x20, 4, y)
        owner_id = self.r(owner + 0x648, 4)
        identifier = self.r(obj + 8, 4)
        receiver = self.r(0x1443C9920)
        self.invoke(
            self.visibility,
            0x141357E10,
            receiver,
            identifier,
            owner_id,
            x,
            *(f.h(home) for home in (0x20, 0x28, 0x30, 0x38, 0x40, 0x48, 0x50)),
        )

    def config_cell(self, f: _Frame) -> int | None:
        return self.invoke(self.config, 0x140D6A530, self.r(_GAME), f.h(0xC8))

    def release_config(self, f: _Frame) -> None:
        control = f.r(0xC8, 8)
        if control:
            self.call(0x140990140, control)

    def eligible(self, f: _Frame, obj: int, player: int) -> bool:
        result = self.config_cell(f)
        cell = self.r(_raw(result, "player config cell RAX"))
        enabled = self.al(0x1413D5580, cell)
        self.release_config(f)
        if enabled:
            return True
        if self.r(player + 0x648, 4) and not self.eax(0x14172AC80, player):
            return True
        setting = self.r(0x1442C3FA3, 1)
        if self.eax(0x14172AC80, player) and setting:
            world = self.pointer(0x1416F3150, player)
            cell = self.pointer(0x141604010, world)
            if self.r(cell):
                cell = self.pointer(0x141604010, self.world(obj))
                observer = self.r(cell)
                target = self.r(self.r(player) + 0xA8)
                descriptor = self.invoke(self.virtual_home, target, player, f.h(0xB8))
                if (
                    self.eax(0x140D866C0, observer, _raw(descriptor, "alliance descriptor RAX"))
                    != 1
                ):
                    return True
        return bool(self.eax(0x14172AC80, player) and self.r(player + 0x5A0, 1))

    def transfer(self, f: _Frame, obj: int, owner: int, index: int) -> None:
        if _signed(index, 4) < 0:
            return
        player = self.pointer(0x141603F60, self.r(owner + 8), index)
        masters = self.r(player + 0x28)
        kind = _signed(self.kind(f, obj, 0xB8) & 0xFFFF, 2)
        if not self.r(masters + kind * 8):
            return
        self.vcall(obj, 0x78, player)
        observer = self.game_call(_OBSERVER)
        if player == _raw(observer, "current observer RAX"):
            master = self.master(f, obj)
            if self.r(master + 8, 1) != 0x50 or not self.r(obj + 0x868):
                self.call(0x140B27590, 0x1432A7DC8, 7, 0)
                hud = self.game_call(0x140FFD0A0)
                if _raw(hud, "ownership HUD RAX"):
                    self.call(0x1415A3480, _raw(hud, "ownership HUD RAX"), self.r(obj + 8, 4))
        self.w(obj + 0x51C, 1, 0)

    def owners(self, f: _Frame, obj: int, mask: int) -> None:
        index = 1
        if _signed(self.eax(0x141603EF0, self.world(obj)), 4) <= index:
            return
        while True:
            player = self.pointer(0x141603F60, self.world(obj), index)
            if self.eligible(f, obj, player):
                owner = self.r(obj + 0x18)
                if index != self.r(owner + 0x648, 4) and mask & (1 << (index & 63)):
                    self.transfer(f, obj, owner, index)
                    return
            index = (index + 1) & _U32
            if _signed(index, 4) >= _signed(self.eax(0x141603EF0, self.world(obj)), 4):
                return

    def special_owner(self, f: _Frame, obj: int) -> None:
        if self.r(obj + 0x51C, 1) == 2:
            player = self.pointer(0x14114A140, obj, 0)
            if player:
                self.vcall(obj, 0x78, player)
                result = self.config_cell(f)
                f.w(0xB8, 4, 1)
                cell = self.r(_raw(result, "special owner config cell RAX"))
                flag = False
                if (
                    self.r(cell + 0x34, 4) == 12
                    and self.kind(f, obj, 0x68) & 0xFFFF == 0x52
                    and self.r(player + 0x648, 4)
                ):
                    world = self.game_call(0x140D6ACC0)
                    flag = not self.r(_raw(world, "special owner World RAX") + 0x8E0, 1)
                self.release_config(f)
                if flag:
                    world = self.game_call(0x140D6ACC0)
                    self.w(_raw(world, "special owner flag World RAX") + 0x8E0, 1, 1)
        if self.kind(f, obj, 0x68) & 0xFFFF == 0x6DE:
            owner = self.r(obj + 0x18)
            if self.r(owner + 0x648, 4):
                target = self.r(self.r(obj) + 0x78)
                raw_player = self.call(0x141603F60, self.r(owner + 8), 0)
                self.invoke(self.virtual, target, obj, _raw(raw_player, "neutral player RAX"))

    def script(self, f: _Frame, obj: int, parent: int) -> None:
        script = self.r(obj + 0x1F0)
        if not script:
            return
        if self.r(obj + 0xF, 1) < 0x46 or not self.r(obj + 0x148):
            active = self.al(_HAS, self.r(obj + 0x420))
            self.call(0x140D42470, script, int(active != 0))
        owner = self.r(obj + 0x18)
        index = self.r(owner + 0x648, 4)
        if self.eax(_SELECTED, self.r(owner + 8), index):
            script = self.r(obj + 0x1F0)
            target = self.r(self.r(script) + 0x20)
            owner = self.r(obj + 0x18)
            index = self.r(owner + 0x648, 4)
            elapsed = self.eax(_ELAPSED, self.r(owner + 8), index)
            self.invoke(self.virtual, target, script, elapsed)
        time = self.call(_CLOCK, self.world(obj))
        if self.r(_DEBUG, 1) >= 1:
            self.status_log(f, obj, time, 0x1432A7DE0)
            if self.r(_DEBUG, 1) >= 1:
                f.w(0x80, 4, 12)
                f.w(0x78, 1, parent)
                f.w(0xC8, 8, f.h(0x78))
                f.w(0x20, 8, f.h(0xC8))
                self.log(f, 0x1432A7E28, 1)
        time = self.call(_CLOCK, self.world(obj))
        if self.r(_DEBUG, 1) >= 1:
            self.status_log(f, obj, time, 0x1432A7E50)

    def final(self, f: _Frame, obj: int, previous_state: int) -> None:
        world = self.world(obj)
        changed = previous_state != self.r(obj + 0x188, 1)
        time = self.call(_CLOCK, world)
        if self.r(_DEBUG, 1) >= 1:
            f.w(0x98, 4, _eax(time, "final diagnostic clock EAX"))
            f.w(0x78, 1, self.r(obj + 0x188, 1))
            for home, node in ((0xD8, 0x78), (0xE0, 0x98), (0xE8, 0x88)):
                f.w(home, 8, f.h(node))
            speed = self.r(obj + 0x168, 4)
            f.w(0x20, 8, f.h(0xD8))
            f.w(0x90, 4, 10)
            f.w(0x88, 4, speed)
            f.w(0xA0, 4, 7)
            f.w(0x80, 4, 5)
            self.log(f, 0x1432A7EA0 if changed else 0x1432A7EF0, 3)
        f.w(0xC8, 8, self.coordinate(f, obj, 0x180, 0x68))
        f.w(0xB8, 8, self.coordinate(f, obj, 0x178, 0x68))
        f.w(0x68, 8, self.coordinate(f, obj, 0x170, 0x68))
        if self.r(_DEBUG, 1) >= 1:
            f.w(0xE0, 4, 10)
            f.w(0xD8, 4, f.r(0xC8, 4))
            f.w(0xB0, 4, 10)
            f.w(0xA8, 4, f.r(0xB8, 4))
            f.w(0x90, 4, 10)
            f.w(0x88, 4, f.r(0x68, 4))
            f.w(0xA0, 4, 5)
            f.w(0x98, 1, self.r(obj + 0x188, 1))
            f.w(0x80, 4, 2)
            f.w(0x78, 4, self.r(obj + 8, 4))
            for home, node in (
                (0xF0, 0x78),
                (0xF8, 0x98),
                (0x100, 0x88),
                (0x108, 0xA8),
                (0x110, 0xD8),
            ):
                f.w(home, 8, f.h(node))
            f.w(0x20, 8, f.h(0xF0))
            self.log(f, 0x1432A7F40, 5)

    def update(self, obj: int) -> int:
        with _Frame(self.context, self.bind_local, self.profile.combat) as f:
            previous_state = self.initial(f, obj)
            self.cooldown(obj)
            self.expire_master(f, obj)
            parent = self.al(0x1411399A0, obj)
            f.w(0x60, 1, parent)
            time = self.call(_CLOCK, self.world(obj))
            if self.r(_DEBUG, 1) >= 1:
                self.status_log(f, obj, time, 0x1432A7D80)
            if _signed(self.r(obj + 8, 4), 4) >= 0 and self.r(obj + 0x138):
                previous_state = self.visibility_mask(f, obj, previous_state)
                parent = f.r(0x60, 1)
            self.special_owner(f, obj)
            self.script(f, obj, parent)
            self.final(f, obj, previous_state)
            return parent


def bind_replay_combat_object_update(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    *,
    virtual_calls: ReplayTaskRebuildCalls,
    logger_home_calls: ReplayTaskRebuildCalls,
    config_home_calls: ReplayTaskRebuildCalls,
    virtual_home_calls: ReplayTaskRebuildCalls,
    visibility_fp_home_calls: ReplayTaskRebuildCalls,
    bind_local: LocalBinding,
    profile: ReplayCombatObjectUpdateProfile,
    mxcsr: int,
) -> ReplayTaskRebuildCalls:
    """Bind whole Combat update and four leaves with actual reached effects.

    Mixed visibility annotations omit unknown R9; native registers,stack/faults,
    EH,FPstatus/upperlanes and concurrency are outside this logical API.
    Unknown calls and their argument/payload/return identities pass unchanged.
    """
    channels = (
        virtual_calls,
        logger_home_calls,
        config_home_calls,
        virtual_home_calls,
        visibility_fp_home_calls,
    )
    for channel in (calls, *channels):
        _validate(context, channel)
    if (
        not callable(bind_local)
        or not isinstance(profile, ReplayCombatObjectUpdateProfile)
        or type(mxcsr) is not int
        or mxcsr != 0x1F80
    ):
        raise ValueError("actual locals/profile and exact MXCSR1f80 Combat update required")

    def dispatch(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        if target not in _ARITIES:
            if calls.call is None:
                raise UnresolvedReplayTaskRebuild(f"reached{target:x} is unavailable")
            return calls.call(target, args, data)
        if len(args) != _ARITIES[target] or data is not None:
            raise ValueError("malformed addressed Combat update call")
        _validate(context, calls, *args)
        body = _Combat(context, bound, channels, bind_local, profile)
        subject = args[0]
        if target == _COMBAT:
            return body.update(subject)
        if target == _HAS:
            return int(body.r(subject + 0x10) != 0)
        if target == _OBSERVER:
            world = body.r(subject + 0x5C0)
            return body.call(0x141603D70, world) if world else 0
        if target == _SELECTED:
            return int(body.r(subject + 0x188, 4) == args[1] & _U32)
        return body.r(subject + _signed(args[1] & _U32, 4) * 4 + 0x18C, 4)

    bound = ReplayTaskRebuildCalls(dispatch)
    return bound
