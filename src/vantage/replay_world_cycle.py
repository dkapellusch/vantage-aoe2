"""Source-backed build54800 cycle selection and thirteen supporting bodies.

world-cycle-source-v1 retains complete originals, closed returning-error traps
and the prepared-call API. This owns caller behavior over supplied storage;
real queue, I/O, mutex, virtual and notification services remain mandatory.
"""

from __future__ import annotations

from dataclasses import dataclass

from .replay_manager_queues import _Frame
from .replay_task_group_storage import LocalBinding
from .replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
    _read,
    _unsigned,
    _write,
)
from .replay_unit_ai_base import _validate
from .replay_unit_ai_map import ReplayUnitAIMapAtomics, _release

_U32, _U64 = (1 << 32) - 1, (1 << 64) - 1
_MAIN, _MESSAGE, _PEEK, _CONSUME = 0x140E0E530, 0x140E50B80, 0x140E63600, 0x140E63610
_STEP, _COPY, _COMMIT, _READY = 0x140E63920, 0x140E66530, 0x140E68CF0, 0x140E68FC0
_STATS, _ELIGIBLE, _ELAPSED, _MODE = 0x140E159E0, 0x140E157D0, 0x140F3E8F0, 0x140E03790
_ROW_A, _ROW_B, _CLOCK, _HOST = 0x140E50540, 0x140E506E0, 0x140E68F80, 0x140A71140
_SETTINGS, _FIRST, _SECOND, _LOGGER = 0x1442DA8A0, 0x1431F7470, 0x143266E00, 0x144355068
_ARITIES = {
    _MAIN: 1,
    _MESSAGE: 3,
    _PEEK: 1,
    _CONSUME: 2,
    _STEP: 1,
    _COPY: 2,
    _COMMIT: 1,
    _READY: 1,
    _STATS: 2,
    _ELIGIBLE: 1,
    _ELAPSED: 1,
    _MODE: 1,
    _ROW_A: 1,
    _ROW_B: 1,
}


@dataclass(frozen=True, slots=True)
class ReplayWorldCycleProfile:
    """Explicit live prefixes; native cookies, saves and EH-only slots excluded."""

    cycle: bytes
    consume: bytes
    commit: bytes
    eligible: bytes
    mode: bytes
    row_a: bytes
    row_b: bytes

    def __post_init__(self) -> None:
        for seed, size in (
            (self.cycle, 0xF8),
            (self.consume, 0xD8),
            (self.commit, 0x30),
            (self.eligible, 0x44),
            (self.mode, 0x14),
            (self.row_a, 0x38),
            (self.row_b, 0x40),
        ):
            if type(seed) is not bytes or len(seed) != size:
                raise ValueError("explicit F8/D8/30/44/14/38/40-hex-byte cycle seeds required")


def _raw(value: int | None, label: str) -> int:
    if value is None:
        raise ValueError(f"{label} requires its actual rawu64 annotation")
    _unsigned(value, 8, label)
    return value


def _eax(value: int | None, label: str) -> int:
    return _raw(value, label) & _U32


def _al(value: int | None, label: str) -> int:
    return _raw(value, label) & 255


class _Cycle:
    def __init__(
        self,
        context: ReplayTaskRebuildStorage,
        calls: ReplayTaskRebuildCalls,
        virtual: ReplayTaskRebuildCalls,
        logger: ReplayTaskRebuildCalls,
        error: ReplayTaskRebuildCalls,
        runtime: ReplayTaskRebuildCalls,
        atomics: ReplayUnitAIMapAtomics,
        bind_local: LocalBinding,
        profile: ReplayWorldCycleProfile,
    ) -> None:
        self.context, self.calls = context, calls
        self.virtual, self.logger, self.error, self.runtime = virtual, logger, error, runtime
        self.atomics, self.bind_local, self.profile = atomics, bind_local, profile

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

    def eax(self, target: int, *args: int) -> int:
        return _eax(self.call(target, *args), f"{target:x} EAX")

    def al(self, target: int, *args: int) -> int:
        return _al(self.call(target, *args), f"{target:x} AL")

    def frame(self, seed: bytes) -> _Frame:
        return _Frame(self.context, self.bind_local, seed)

    def log(self, f: _Frame, level: int, format_address: int, count: int) -> None:
        self.invoke(
            self.logger, 0x14101ADB0, self.r(_LOGGER), level, format_address, count, f.h(0x20)
        )

    def fail(self, code: int, trap: int) -> None:
        self.invoke(self.runtime, 0x142D6AA67, code)
        raise UnresolvedReplayTaskRebuild(f"source INT3 at{trap:x} after returning runtime error")

    def lock(self, address: int, bad: int, overflow: int) -> None:
        result = self.invoke(self.runtime, 0x142D6AA5B, address)
        if _eax(result, "mutex lock EAX"):
            self.fail(5, bad)
        if self.r(address + 0x4C, 4) == 0x7FFFFFFF:
            self.w(address + 0x4C, 4, 0x7FFFFFFE)
            self.fail(6, overflow)

    def unlock(self, address: int) -> None:
        self.invoke(self.runtime, 0x142D6AA61, address)

    def lower_bound(self, root: int, header: int, nil: int, key: int) -> int:
        candidate, current = header, root
        if not nil:
            while True:
                if self.r(current + 0x1C, 4) >= key:
                    candidate = current
                    current = self.r(current)
                else:
                    current = self.r(current + 0x10)
                if self.r(current + 0x19, 1):
                    break
        return candidate

    def ready(self, clock: int) -> int:
        following = (self.r(clock + 0x30, 4) + 1) & _U32
        if self.r(clock + 0x54, 4) < following:
            return 0
        lock = (clock + 0x70) & _U64
        self.lock(lock, 0x140E690C3, 0x140E690D5)
        header = self.r(clock + 0x60)
        root = self.r(header + 8)
        nil = self.r(root + 0x19, 1)
        first = self.lower_bound(root, header, nil, following)
        if self.r(first + 0x19, 1) or following < self.r(first + 0x1C, 4):
            result = 1
        else:
            second = self.lower_bound(root, header, nil, following)
            if self.r(second + 0x19, 1) or following < self.r(second + 0x1C, 4):
                self.invoke(self.runtime, 0x142D6AA55, 0x1436802B0)
                self.fail(5, 0x140E690C3)
            result = int(self.r(second + 0x20, 4) == 0)
        self.unlock(lock)
        return result

    def commit(self, clock: int) -> None:
        with self.frame(self.profile.commit) as f:
            previous = self.r(clock + 0x30, 4)
            current = (previous + 1) & _U32
            self.w(clock + 0x30, 4, current)
            if current == previous:
                return
            self.w(clock + 0x28, 8, self.r(clock + 0x54, 4))
            self.w(clock + 0x20, 4, self.r(clock + 0x18, 4))
            settings = self.r(_SETTINGS)
            f.w(0x28, 8, 0)
            self.call(_STATS, settings, f.h(0x28))
            stats = f.r(0x28, 8)
            self.w(clock + 0x38, 16, self.r(stats, 16))
            self.w(clock + 0x48, 4, self.r(stats + 0x10, 4))
            if self.r(clock + 0x130):
                lock = (clock + 0xC0) & _U64
                self.lock(lock, 0x140E68E3E, 0x140E68E33)
                head = self.r(clock + 0x128)
                capacity = self.r(clock + 0x120)
                array = self.r(clock + 0x118)
                bucket = self.r(array + ((head >> 2) & ((capacity - 1) & _U64)) * 8)
                stamp = self.r(bucket + (head & 3) * 4, 4)
                remaining = (self.r(clock + 0x130) - 1) & _U64
                self.w(clock + 0x130, 8, remaining)
                self.w(clock + 0x128, 8, head + 1 if remaining else 0)
                self.unlock(lock)
                bus = _raw(self.call(0x140A69450), "clock event bus RAX")
                elapsed = (self.eax(_HOST) - stamp) & _U32
                self.call(0x140A70000, bus + 0x818, elapsed)

    def eligible(self, manager: int) -> int:
        with self.frame(self.profile.eligible) as f:
            table = self.r(_FIRST, 16)
            mode = self.r(manager + 0x318, 4)
            f.w(0x20, 16, table)
            if not f.contains(0x20, 4, mode):
                return 0
            mode = self.r(manager + 0x318, 4)
            table = self.r(_SECOND, 16)
            f.w(0x30, 16, table)
            f.w(0x40, 4, 8)
            if not f.contains(0x30, 5, mode):
                return 1
            return int(self.eax(_CLOCK, self.r(manager + 0x358)) >= 6)

    def mode(self, manager: int) -> int:
        with self.frame(self.profile.mode) as f:
            mode = self.r(manager + 0x318, 4)
            f.w(0, 16, self.r(_SECOND, 16))
            f.w(0x10, 4, 8)
            return int(f.contains(0, 5, mode))

    def row_a(self, row: int) -> int:
        with self.frame(self.profile.row_a) as f:
            home = f.h(0x30)
            slot = self.call(0x140E158C0, self.r(_SETTINGS), home)
            value = self.r(_raw(slot, "row role slot RAX"))
            return int(value == self.r(row + 0x20))

    def row_b(self, row: int) -> int:
        with self.frame(self.profile.row_b) as f:
            if self.al(0x140E053D0, self.r(_SETTINGS)):
                return 0
            settings = self.r(_SETTINGS)
            slot = self.call(0x140E15A50, settings, f.h(0x38))
            value = self.r(row + 0x20)
            return int(self.r(_raw(slot, "row selection slot RAX")) == value)

    def message(self, output: int, state: int, row: int) -> int:
        self.w(output, 1, state)
        self.w(output + 8, 8, _U64)
        self.w(output + 0x10, 1, self.al(_ROW_A, row))
        self.w(output + 0x11, 1, self.al(_ROW_B, row))
        self.w(output + 0x18, 8, row)
        receiver = self.r(row + 8)
        if receiver:
            target = self.r(self.r(receiver) + 0x38)
            result = self.invoke(self.virtual, target, receiver)
            self.w(output + 8, 8, _raw(result, "row virtual38 RAX"))
        return output

    def step(self, queue: int) -> int:
        self.w(queue + 0x4CC, 4, 1)
        if self.al(_ELIGIBLE, self.r(queue + 0x3D0)):
            external = self.r(0x1442846F0)
            raw_cap = self.call(0x1409738C0, external, 1) if external else 0
            previous = self.r(queue + 0x3F0, 4)
            cap = _eax(raw_cap, "cycle cap EAX")
            if previous < cap:
                self.w(queue + 0x3F0, 4, cap)
        return self.r(queue + 0x3F0, 4)

    def consume(self, queue: int, now: int) -> int:
        with self.frame(self.profile.consume) as f:
            now &= _U32
            self.w(queue + 0x4CC, 4, 0)
            if not self.r(queue + 0x3E8, 4):
                if self.r(0x144355062, 1) >= 1:
                    logger = self.r(_LOGGER)
                    f.w(0x20, 8, 0)
                    self.invoke(self.logger, 0x14101ADB0, logger, 0x2A, 0x14326A7C0, 0, f.h(0x20))
                self.w(queue + 0x4CC, 4, 0)
                return 0
            raw_timer = self.call(_ELAPSED, self.r(queue + 0x100))
            descriptor = self.r(queue + 0x3D0)
            self.w(queue + 0x4B8, 4, _eax(raw_timer, "queue timer EAX"))
            if self.al(_MODE, descriptor):
                pending = self.r(queue + 0x3E8, 4)
                self.w(queue + 0x4B0, 4, self.r(queue + 0x4B0, 4) + pending)
            credits = self.r(queue + 0x3E4, 4)
            pending = self.r(queue + 0x3E8, 4)
            left = (credits - min(credits, pending)) & _U32
            timer = self.r(queue + 0x4B8, 4)
            required = left * self.r(queue + 0x3F0, 4) & _U32
            elapsed = (timer + self.r(queue + 0x3F4, 4)) & _U32
            self.w(queue + 0x4BC, 4, required)
            if elapsed < required and not self.al(0x140E05160, self.r(0x1442C3F98)):
                if now > 6:
                    self.w(queue + 0x4C0, 4, self.r(queue + 0x4C0, 4) + 1)
                    self.w(queue + 0x4C4, 4, self.r(queue + 0x4C4, 4) + 1)
                if self.r(0x144355062, 1) >= 1:
                    self.consume_log(f, queue, now)
                self.w(queue + 0x4CC, 4, 0)
                return 0
            self.w(queue + 0x3E8, 4, self.r(queue + 0x3E8, 4) - 1)
            result = self.r(queue + 0x3F0, 4)
            self.w(queue + 0x4CC, 4, 1)
            return result

    def consume_log(self, f: _Frame, queue: int, now: int) -> None:
        failures = self.r(queue + 0x4C4, 4)
        extra = self.r(queue + 0x3F4, 4)
        timer = self.r(queue + 0x4B8, 4)
        f.w(0x80, 4, failures)
        f.w(0x70, 4, self.r(queue + 0x4C0, 4))
        f.w(0x60, 4, self.r(queue + 0x4BC, 4))
        f.w(0x50, 4, extra + timer)
        for home, data in zip(range(0xA0, 0xD8, 8), range(0x30, 0xA0, 0x10), strict=True):
            f.w(home, 8, f.h(data))
        f.w(0x40, 4, timer)
        logger = self.r(_LOGGER)
        f.w(0x30, 4, extra)
        f.w(0x20, 8, f.h(0xA0))
        f.w(0x98, 4, 8)
        f.w(0x90, 4, now)
        for home, kind in ((0x88, 7), (0x78, 7), (0x68, 8), (0x58, 8), (0x48, 8), (0x38, 7)):
            f.w(home, 4, kind)
        self.invoke(self.logger, 0x14101ADB0, logger, 0x2A, 0x14326A810, 7, f.h(0x20))

    def metrics(self, manager: int) -> None:
        first = _raw(self.call(0x141021E00), "cycle metrics receiver RAX")
        self.call(0x1410231D0, first, 2)
        second = _raw(self.call(0x141021E00), "cycle metrics second RAX")
        time = self.eax(_CLOCK, self.r(manager + 0x358))
        self.call(0x1410224A0, second, time)

    def clear_wait(self, manager: int) -> int:
        self.call(0x140E64030, self.r(manager + 0x388))
        return 0

    def admission(self, manager: int) -> int:
        ready = self.al(_READY, self.r(manager + 0x358))
        if not ready:
            clock = self.r(manager + 0x358)
            timeout = False
            if self.r(clock + 8, 4) != 2 and not self.al(0x140E053D0, manager):
                previous = self.r(manager + 0x3A8, 4)
                timeout = ((self.eax(_HOST) - previous) & _U32) > 5000
            if not timeout:
                settings = self.r(_SETTINGS)
                receiver = self.r(settings + 0x2E8)
                target = self.r(self.r(receiver) + 0x1D0)
                if not _al(self.invoke(self.virtual, target, receiver), "virtual1d0 AL"):
                    return 0
                ready = self.al(_READY, self.r(manager + 0x358))
                if not ready:
                    return 0
        clock = self.r(manager + 0x358)
        if (
            self.r(clock + 8, 4) != 2
            and not self.al(0x140E053D0, manager)
            and not self.al(0x140E469E0, manager + 0x320)
        ):
            self.call(0x140E64150, self.r(manager + 0x388))
            return 0
        return ready

    def pick(self, manager: int) -> int:
        with self.frame(self.profile.cycle) as f:
            mode = self.r(manager + 0x318, 4)
            f.w(0x48, 16, self.r(_FIRST, 16))
            if not f.contains(0x48, 4, mode):
                return 0
            mode = self.r(manager + 0x318, 4)
            f.w(0x58, 16, self.r(_SECOND, 16))
            f.w(0x68, 4, 8)
            if not f.contains(0x58, 5, mode):
                return self.uncapped(manager)
            if self.r(0x1443559B0):
                registry = _raw(self.call(0x141021E00), "cycle diagnostic registry RAX")
                if self.al(0x1410221D0, registry, 15):
                    receiver = self.r(manager + 0x2E8)
                    self.invoke(self.virtual, self.r(self.r(receiver) + 0x100), receiver)
            mode = self.r(manager + 0x318, 4)
            f.w(0x30, 4, 7)
            f.w(0x34, 4, 8)
            if not f.contains(0x30, 2, mode):
                self.call(0x140E0CA00, manager)
            if self.r(manager + 0x380, 1):
                queue = self.r(manager + 0x390)
                time = self.eax(_CLOCK, self.r(manager + 0x358))
                if self.al(0x140E67F40, queue, time):
                    queue = self.r(manager + 0x390)
                    time = self.eax(_CLOCK, self.r(manager + 0x358))
                    self.call(0x140E67FC0, queue, time)
            if self.r(0x1442C40F0, 4):
                return 0
            if (
                self.eax(_PEEK, self.r(manager + 0x388))
                and self.eax(_CLOCK, self.r(manager + 0x358)) > 6
            ):
                return self.pending(f, manager)
            if not self.r(manager + 0x414, 4):
                self.w(manager + 0x414, 4, self.eax(_HOST))
            if not self.admission(manager):
                return self.clear_wait(manager)
            self.w(manager + 0x3A8, 4, self.eax(_HOST))
            if self.r(manager + 0x3A0, 1) or self.r(manager + 0x3A1, 1):
                return 0
            clock = self.r(manager + 0x358)
            if self.r(clock + 8, 4) != 2 and self.r(manager + 0x418, 4):
                now = (self.eax(_CLOCK, clock) + 1) & _U32
                if self.r(manager + 0x418, 4) <= now:
                    self.w(manager + 0x418, 4, 0)
            queue = self.r(manager + 0x388)
            now = self.eax(_CLOCK, self.r(manager + 0x358))
            self.call(_CONSUME, queue, now)
            self.call(0x140E63BD0, self.r(manager + 0x388))
            self.w(manager + 0x404, 4, self.r(manager + 0x408, 4))
            self.w(manager + 0x408, 8, 0)
            self.w(manager + 0x410, 4, 0)
            self.call(_COMMIT, self.r(manager + 0x358))
            self.w(manager + 0x380, 1, 0)
            if self.al(0x140E169D0, manager) and not self.al(0x140E16E00, manager):
                self.call(0x140E090A0, manager)
            if self.al(0x140E051E0, manager):
                self.io(f, manager)
            if self.r(0x1443559B0):
                self.metrics(manager)
            previous = self.r(manager + 0x414, 4)
            elapsed = (self.eax(_HOST) - previous) & _U32
            index = self.r(manager + 0x3FC, 4)
            self.w(manager + 0x3AC + index * 4, 4, elapsed)
            following = (self.r(manager + 0x3FC, 4) + 1) & _U32
            quotient = ((following * 0xCCCCCCCCCCCCCCCD) >> 64) >> 4
            self.w(manager + 0x3FC, 4, following - quotient * 20)
            self.w(manager + 0x414, 4, 0)
            held = self.eax(_CLOCK, self.r(manager + 0x358))
            self.rows(f, manager, held)
            result = self.eax(_STEP, self.r(manager + 0x388))
            if self.r(0x144355066, 1) >= 1:
                f.w(0xC0, 4, 7)
                f.w(0xB8, 4, result)
                f.w(0xA8, 8, f.h(0xB8))
                f.w(0x20, 8, f.h(0xA8))
                self.log(f, 0x2E, 0x143265490, 1)
            return result

    def uncapped(self, manager: int) -> int:
        if self.r(manager + 0x3A0, 1) or self.r(manager + 0x3A1, 1):
            return 0
        if self.r(0x1443559B0):
            self.metrics(manager)
        self.call(0x140E66FF0, self.r(manager + 0x390))
        self.call(0x140E67A10, self.r(manager + 0x390))
        self.call(_COMMIT, self.r(manager + 0x358))
        self.w(manager + 0x380, 1, 0)
        descriptor = self.r(manager + 0x398)
        if self.r(descriptor + 2, 1) and self.r(self.r(0x144415600) + 0xC4C, 4):
            return 0
        return _U32

    def pending(self, f: _Frame, manager: int) -> int:
        queue = self.r(manager + 0x388)
        time = self.eax(_CLOCK, self.r(manager + 0x358))
        result = self.eax(_CONSUME, queue, time)
        raw_peek = self.call(_PEEK, self.r(manager + 0x388))
        if self.r(0x144355062, 1) >= 1:
            f.w(0x40, 4, 7)
            f.w(0x38, 4, _eax(raw_peek, "pending diagnostic EAX"))
            f.w(0xB0, 4, 7)
            f.w(0xA8, 4, result)
            f.w(0xB8, 8, f.h(0xA8))
            f.w(0xC0, 8, f.h(0x38))
            f.w(0x20, 8, f.h(0xB8))
            self.log(f, 0x2A, 0x143265450, 2)
        return result

    def io(self, f: _Frame, manager: int) -> None:
        queue = self.r(manager + 0x388)
        clock = self.r(manager + 0x358)
        if self.r(clock + 8, 4) != 2:
            self.call(0x140E63280, queue, f.h(0x74), f.h(0xA8), 1)
            return
        if not self.eax(0x140E634C0, queue, f.h(0x74), f.h(0xA8), f.h(0x78)):
            return
        clock = self.r(manager + 0x358)
        value = f.r(0x78, 4)
        if value != self.r(clock + 0x5C, 4):
            self.send(f, manager, value)
        third = f.r(0x74, 4)
        second = f.r(0xA8, 4)
        self.call(0x140E08110, manager, second, third)

    def send(self, f: _Frame, manager: int, value: int) -> None:
        f.w(0x70, 1, 0x72)
        f.w(0x71, 1, value)
        f.w(0x80, 16, 0)
        f.w(0x88, 4, 0)
        f.w(0x80, 8, 0x143218B60)
        f.w(0x90, 16, 0)
        f.w(0xA0, 8, 0)
        registry = _raw(self.call(0x14098F250), "cycle registry RAX")
        service = _raw(self.call(0x140942110, registry, 0x144121880), "cycle service RAX")
        if service:
            target = self.r(self.r(service) + 0x18)
            self.invoke(self.virtual, target, service, f.h(0xC8), f.h(0x80), f.h(0x70))
        else:
            name = self.call(0x142D6E3ED, 0x144121888, 0x144C9CDB0)
            f.w(0x28, 8, _raw(name, "cycle RTTI name RAX"))
            f.w(0x20, 8, 0x1431FAC58)
            self.invoke(
                self.error, 0x140A08840, f.h(0xC8), 0, 0x1431FAC00, 0x2F5, f.h(0x20), f.h(0x28)
            )
        self.call(0x14096B890, f.h(0xC8))
        control = f.r(0xE8, 8)
        if control:
            _release(self.context, control, self.virtual, self.atomics)
        self.call(0x1402BD7F0, f.h(0xC8))
        receiver = self.r(manager + 0x2E8)
        count = (f.r(0x98, 4) - f.r(0x90, 4)) & _U32
        vptr = self.r(receiver)
        data = f.r(0x90, 8)
        target = self.r(vptr + 0xE8)
        self.invoke(self.virtual, target, receiver, data, count)
        clock = self.r(manager + 0x358)
        self.w(clock + 0x50, 4, self.eax(_HOST))
        self.call(0x1402A8630, f.h(0x90))

    def rows(self, f: _Frame, manager: int, held: int) -> None:
        row = 0x1442DE068
        for index in range(8):
            clock = self.r(manager + 0x358)
            ordinal = self.r(row + 0x20, 4)
            current = self.r(clock + 0x30, 4)
            threshold = self.r(clock + ordinal * 4 + 0x138, 4)
            stale = threshold < current and not self.al(0x140E50470, row)
            if held and self.al(0x140E504E0, row):
                allowed = True
                if self.al(0x140E50390, row):
                    allowed = not self.al(0x140E50300, row) and stale
                if allowed:
                    row_value = self.r(row, 4)
                    if row_value == held or stale:
                        if self.r(0x14435505D, 1) >= 1:
                            self.row_log(f, index, row_value, bool(stale))
                        f.w(0x80, 16, 0)
                        f.w(0x90, 16, 0)
                        # R14's high bits are unprovided. The owned85B callee
                        # consumes only DL, whose doubled boolean is known.
                        self.call(_MESSAGE, f.h(0x80), 0 if stale else 2, row)
                        f.w(0xC8, 8, manager + 0xD0)
                        f.w(0xD0, 16, 0)
                        f.w(0xE0, 8, 0)
                        self.call(0x140E03BE0, f.h(0xC8), f.h(0x80))
                        self.call(0x140DFC910, f.h(0xD0))
            row += 0x30

    def row_log(self, f: _Frame, index: int, value: int, stale: bool) -> None:
        f.w(0xB0, 4, 0xF)
        f.w(0xA8, 8, 0x143265408 if stale else 0x143265410)
        f.w(0x40, 4, 7)
        f.w(0x38, 4, value)
        f.w(0xC0, 4, 7)
        f.w(0xB8, 4, index + 1)
        for home, target in ((0xC8, 0xB8), (0xD0, 0x38), (0xD8, 0xA8)):
            f.w(home, 8, f.h(target))
        f.w(0x20, 8, f.h(0xC8))
        self.log(f, 0x25, 0x1432654E0, 3)


def bind_replay_world_cycle(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    *,
    virtual_calls: ReplayTaskRebuildCalls,
    logger_home_calls: ReplayTaskRebuildCalls,
    error_home_calls: ReplayTaskRebuildCalls,
    runtime_calls: ReplayTaskRebuildCalls,
    atomics: ReplayUnitAIMapAtomics,
    bind_local: LocalBinding,
    profile: ReplayWorldCycleProfile,
) -> ReplayTaskRebuildCalls:
    """Bind14 callers, with actual current data and explicit reached services.

    logger's lowDL and live HOME20, and error HOME20/28, follow api.json.
    AL-return bodies expose only their known byte annotation. Ignored child
    returns stay opaque; consumed scalar returns require actual rawu64. Native
    physical saves/cookies, EH-only slots, faults/unwind and threads excluded.
    No clock, frame seed, mutex success, loop budget or World readiness added.
    """
    for channel in (calls, virtual_calls, logger_home_calls, error_home_calls, runtime_calls):
        _validate(context, channel)
    if (
        not isinstance(atomics, ReplayUnitAIMapAtomics)
        or not callable(bind_local)
        or not isinstance(profile, ReplayWorldCycleProfile)
    ):
        raise ValueError("actual cycle atomics, local binding and explicit profile required")

    def dispatch(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        if target not in _ARITIES:
            if calls.call is None:
                raise UnresolvedReplayTaskRebuild(f"reached{target:x} is unavailable")
            return calls.call(target, args, data)
        if len(args) != _ARITIES[target] or data is not None:
            raise ValueError("malformed addressed World cycle call")
        _validate(context, calls, *args)
        body = _Cycle(
            context,
            bound,
            virtual_calls,
            logger_home_calls,
            error_home_calls,
            runtime_calls,
            atomics,
            bind_local,
            profile,
        )
        if target == _MAIN:
            return body.pick(args[0])
        if target == _MESSAGE:
            return body.message(*args)
        if target == _PEEK:
            return body.r(args[0] + 0x3E8, 4)
        if target == _CONSUME:
            return body.consume(*args)
        if target == _STEP:
            return body.step(args[0])
        if target == _COPY:
            body.w(args[0] + 0x2C, 16, body.r(args[1], 16))
            body.w(args[0] + 0x3C, 4, body.r(args[1] + 0x10, 4))
        elif target == _COMMIT:
            body.commit(args[0])
        elif target == _READY:
            return body.ready(args[0])
        elif target == _STATS:
            return body.call(0x140E65420, body.r(args[0] + 0x390), args[1])
        elif target == _ELIGIBLE:
            return body.eligible(args[0])
        elif target == _ELAPSED:
            previous = body.r(args[0] + 0x2A4, 4)
            return (body.eax(_HOST) - previous) & _U32
        elif target == _MODE:
            return body.mode(args[0])
        elif target == _ROW_A:
            return body.row_a(args[0])
        else:
            return body.row_b(args[0])
        return None

    bound = ReplayTaskRebuildCalls(dispatch)
    return bound
