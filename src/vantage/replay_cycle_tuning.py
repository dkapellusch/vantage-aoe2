"""Seventeen logical build54800 cycle tuning and queue helper bodies.

Originals and the pre-code ABI are retained in world-cycle-queue-source-v1.
This supplies addressed caller behavior; metric, tree-link/unlink, notification
and other unclosed effects remain mandatory. It does not restore a World.
"""

from __future__ import annotations

from dataclasses import dataclass

from .replay_binary32 import divide_binary32, unsigned64_binary32
from .replay_manager_queues import _Frame
from .replay_task_containers import _cvtt64
from .replay_task_group_storage import LocalBinding
from .replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
    _read,
    _signed,
    _unsigned,
    _write,
)
from .replay_unit_ai_base import _validate

_U32, _U64 = (1 << 32) - 1, (1 << 64) - 1
_TUNE, _MODE2, _ADVANCE, _RESET = 0x140E63280, 0x140E634C0, 0x140E63BD0, 0x140E64030
_REJECT, _STATS, _ROLE_A, _ROLE_B = 0x140E64150, 0x140E65420, 0x140E158C0, 0x140E15A50
_GATE, _WIDTH, _FUTURE = 0x140E63820, 0x140E64040, 0x140E157A0
_SCHEDULE, _ROLE, _TIMER = 0x140E63E70, 0x140E15A80, 0x140F3EA40
_GAME_TOKEN, _ENTRY, _ERASE = 0x140D6ACC0, 0x140E630C0, 0x140E64160
_METRIC, _EXTERNAL, _GAME = 0x1409738C0, 0x1442846F0, 0x144353698
_LOGGER, _DEBUG, _LOG, _HOST = 0x144355068, 0x144355062, 0x14101ADB0, 0x140A71140
_ARITIES = {
    _TUNE: 4,
    _MODE2: 4,
    _ADVANCE: 1,
    _RESET: 1,
    _REJECT: 1,
    _STATS: 2,
    _ROLE_A: 2,
    _ROLE_B: 2,
    _GATE: 1,
    _WIDTH: 1,
    _FUTURE: 1,
    _SCHEDULE: 4,
    _ROLE: 2,
    _TIMER: 1,
    _GAME_TOKEN: 1,
    _ENTRY: 2,
    _ERASE: 2,
}


@dataclass(frozen=True, slots=True)
class ReplayCycleTuningProfile:
    """Explicit live prefixes; physical saves, cookies and EH slots excluded."""

    tune: bytes
    advance: bytes
    schedule: bytes
    entry: bytes
    role_wrapper: bytes
    role: bytes
    timer: bytes

    def __post_init__(self) -> None:
        for seed, size in (
            (self.tune, 0x24),
            (self.advance, 0x70),
            (self.schedule, 0x98),
            (self.entry, 0x40),
            (self.role_wrapper, 0x40),
            (self.role, 0x44),
            (self.timer, 0x28),
        ):
            if type(seed) is not bytes or len(seed) != size:
                raise ValueError("explicit24/70/98/40/40/44/28-hex-byte tuning seeds required")


def _raw(value: int | None, label: str) -> int:
    if value is None:
        raise ValueError(f"{label} requires actual rawu64 annotation")
    _unsigned(value, 8, label)
    return value


def _eax(value: int | None, label: str) -> int:
    return _raw(value, label) & _U32


def _al(value: int | None, label: str) -> int:
    return _raw(value, label) & 255


def _abs32(value: int) -> int:
    return abs(_signed(value & _U32, 4)) & _U32


def _div(value: int, denominator: int, at: int) -> int:
    if not denominator:
        raise UnresolvedReplayTaskRebuild(f"source DIV fault at{at:x}; native faults excluded")
    return (value & _U32) // denominator


class _Tuning:
    def __init__(
        self,
        context: ReplayTaskRebuildStorage,
        calls: ReplayTaskRebuildCalls,
        ceil: ReplayTaskRebuildCalls,
        virtual: ReplayTaskRebuildCalls,
        logger: ReplayTaskRebuildCalls,
        timer_logger: ReplayTaskRebuildCalls,
        bind_local: LocalBinding,
        profile: ReplayCycleTuningProfile,
    ) -> None:
        self.context, self.calls, self.ceil = context, calls, ceil
        self.virtual, self.logger, self.timer_logger = virtual, logger, timer_logger
        self.bind_local, self.profile = bind_local, profile

    def r(self, address: int, width: int = 8) -> int:
        return _read(self.context, address, width)

    def w(self, address: int, width: int, value: int) -> None:
        _write(self.context, address, width, value)

    def frame(self, seed: bytes) -> _Frame:
        return _Frame(self.context, self.bind_local, seed)

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

    def future(self, manager: int) -> int:
        clock = self.r(manager + 0x358)
        mode = self.r(clock + 8, 4)
        now = self.eax(0x140E68F80, clock)
        return (now + (8 if mode == 2 else 2)) & _U32

    def gate(self, queue: int) -> int:
        if not self.al(0x140E051E0, self.r(queue + 0x3D0)):
            return 0
        game = self.r(_GAME)
        if self.r(game + 0xA8, 4) == 2 and self.r(queue + 0x13B8, 1):
            return 0
        if self.r(queue + 0x7B0) and self.r(self.r(self.r(queue + 0x7A8)) + 0x1C, 4):
            return 0
        raw_time = self.call(_FUTURE, self.r(queue + 0x3D0))
        external = self.r(_EXTERNAL)
        time = _eax(raw_time, "future EAX")
        if external and time < self.eax(_METRIC, external, 7):
            return 0
        self.w(queue + 0x4B4, 4, self.r(queue + 0x4B4, 4) + 1)
        raw_threshold = self.call(_METRIC, external, 0)
        current = self.r(queue + 0x4B4, 4)
        return int(current >= _eax(raw_threshold, "gate threshold EAX"))

    def width(self, queue: int) -> int:
        external = self.r(_EXTERNAL)
        game = self.r(_GAME)
        widest = 0
        for index in range(8):
            row = 0x1442DE068 + index * 0x30
            if self.r(row + 8):
                ordinal = self.r(row + 0x20, 4)
                now = self.r(game + 0xD0, 4)
                if self.r(game + 0x1D8 + ordinal * 4, 4) >= now:
                    widest = max(widest, self.r(queue + 0x47C + (index + 1) * 4, 4))
        if not widest:
            return self.r(queue + 0x3F0, 4)
        if external:
            widest = max(widest, self.eax(_METRIC, external, 1))
        minimum = self.eax(_METRIC, external, 1)
        proposed = min(self.eax(_METRIC, external, 2), widest)
        distance = _abs32(proposed - self.r(queue + 0x3F0, 4))
        if distance < self.eax(_METRIC, external, 10):
            proposed = self.r(queue + 0x3F0, 4)
        return max(minimum, proposed)

    def tune(self, queue: int, width_out: int, count_out: int, publish: int) -> int:
        with self.frame(self.profile.tune) as f:
            f.w(0x20, 4, publish)
            if not self.al(_GATE, queue):
                return 0
            external = self.r(_EXTERNAL)
            if external:
                kind = self.r(external + 8, 4)
                if kind in (2, 3):
                    offset = 0x268 if kind == 2 else 0x2C8
                    self.w(width_out, 4, self.r(self.r(external) + offset, 4))
                    self.w(count_out, 4, self.r(self.r(external) + offset + 0x30, 4))
                    raw_time = self.call(_FUTURE, self.r(queue + 0x3D0))
                    width = self.r(width_out, 4)
                    time = _eax(raw_time, "direct future EAX")
                    count = self.r(count_out, 4)
                    self.call(_SCHEDULE, queue, count, width, time)
                    width = self.r(width_out, 4)
                    count = self.r(count_out, 4)
                    self.call(0x140E08110, self.r(queue + 0x3D0), count, width)
                    return 1
            self.call(_METRIC, external, 5)  # This first value is genuinely unconsumed.
            quantum = self.eax(_WIDTH, queue)
            raw_initial = self.call(_METRIC, external, 4)
            current_external = self.r(_EXTERNAL)
            initial = _div(
                (_eax(raw_initial, "initial budget EAX") + 10) & _U32, quantum, 0x140E63374
            )
            ceiling = min(self.eax(_METRIC, current_external, 6), _div(1000, quantum, 0x140E63390))
            floor = _div(500, quantum, 0x140E633A1) + 1
            raw_floor = self.call(_METRIC, current_external, 5)
            previous_width = self.r(queue + 0x3F0, 4)
            cap = _eax(raw_floor, "minimum budget EAX")
            previous_count = self.r(queue + 0x3E4, 4)
            floor = max(cap, floor)
            count = max(min(initial, ceiling), floor)
            prior_product = previous_width * previous_count & _U32
            proposed_product = count * quantum & _U32
            distance = _abs32(proposed_product - prior_product)
            if prior_product > proposed_product and distance > 1000:
                adjusted = max(_abs32(prior_product - 1000), 500)
                count = max(_div(adjusted, quantum, 0x140E63421), floor)
            elif prior_product < proposed_product and distance > 100:
                adjusted = min(_abs32(prior_product + 100), 1000)
                count = min(_div(adjusted, quantum, 0x140E6344F), ceiling)
            if quantum == previous_width and count == previous_count:
                return 0
            publish = f.r(0x20, 4)
            self.w(width_out, 4, quantum)
            self.w(count_out, 4, count)
            if publish and self.r(queue + 0x3E0, 4):
                time = self.eax(_FUTURE, self.r(queue + 0x3D0))
                self.call(_SCHEDULE, queue, count, quantum, time)
                self.call(0x140E08110, self.r(queue + 0x3D0), count, quantum)
            return 1

    def mode2(self, queue: int, width_out: int, count_out: int, stamp_out: int) -> int:
        if not self.al(_GATE, queue):
            return 0
        quantum = self.eax(_WIDTH, queue)
        self.w(width_out, 4, quantum)
        if quantum == self.r(queue + 0x3F0, 4):
            return 0
        external = self.r(_EXTERNAL)
        first = self.eax(_METRIC, external, 5)
        raw_cap = self.call(_METRIC, external, 6)
        product = ((first + 1) & _U32) * self.r(width_out, 4) & _U32
        cap = _eax(raw_cap, "mode2 count cap EAX")
        numerator = unsigned64_binary32(product)
        period = self.eax(_METRIC, self.r(_EXTERNAL), 18)
        quotient = divide_binary32(numerator, unsigned64_binary32(period))
        ceiling = _raw(self.invoke(self.ceil, 0x142D6E453, quotient), "ceil XMM0 word")
        _unsigned(ceiling, 4, "ceil XMM0 word")
        stamp = _cvtt64(ceiling) & _U32
        self.w(stamp_out, 4, stamp)
        required = stamp * period & _U32
        count = (_div(required, self.r(width_out, 4), 0x140E63581) - 1) & _U32
        count = min(cap, count)
        self.w(count_out, 4, count)
        width = self.r(width_out, 4)
        following = (count + 1) & _U32
        if width * following & _U32 < required:
            width = _div(required, following, 0x140E635AA)
            self.w(width_out, 4, width)
        changed = 1
        if width == self.r(queue + 0x3F0, 4):
            previous_count = self.r(queue + 0x3E4, 4)
            changed = int(self.r(count_out, 4) != previous_count)
        self.w(queue + 0x13B8, 1, changed)
        return changed

    def schedule(self, queue: int, count: int, width: int, time: int) -> None:
        with self.frame(self.profile.schedule) as f:
            nonempty = self.r(queue + 0x7B0)
            count, width = count & _U32, width & _U32
            f.w(0x30, 4, time)
            accepted = True
            if (
                nonempty
                and self.r(self.r(self.r(queue + 0x7A8)) + 0x1C, 4)
                and not self.al(0x140E053D0, self.r(0x1442C3F98))
            ):
                accepted = self.r(self.r(_GAME) + 0xA8, 4) == 2
            if accepted:
                f.w(0x38, 4, count)
                f.w(0x3C, 4, width)
                raw_slot = self.call(_ENTRY, queue + 0x7A8, f.h(0x30))
                pair = f.r(0x38, 8)
                self.w(_raw(raw_slot, "scheduled entry RAX"), 8, pair)
                self.w(queue + 0x13B8, 1, 0)
            elif self.r(_DEBUG, 1) >= 1:
                time = f.r(0x30, 4)
                logger = self.r(_LOGGER)
                f.w(0x58, 4, time)
                f.w(0x70, 4, 8)
                for home, value in ((0x78, 0x38), (0x80, 0x48), (0x88, 0x58), (0x90, 0x68)):
                    f.w(home, 8, f.h(value))
                f.w(0x20, 8, f.h(0x78))
                for home, value in (
                    (0x68, 1),
                    (0x60, 8),
                    (0x50, 7),
                    (0x48, width),
                    (0x40, 7),
                    (0x38, count),
                ):
                    f.w(home, 4, value)
                self.invoke(self.logger, _LOG, logger, 0x2A, 0x14326A670, 4, f.h(0x20))

    def entry(self, tree: int, key_home: int) -> int:
        with self.frame(self.profile.entry) as f:
            header = self.r(tree)
            current = self.r(header + 8)
            f.w(0x30, 8, current)
            f.w(0x38, 4, 0)
            candidate = header
            if not self.r(current + 0x19, 1):
                key = self.r(key_home, 4)
                while True:
                    f.w(0x30, 8, current)
                    if self.r(current + 0x1C, 4) >= key:
                        f.w(0x38, 4, 1)
                        candidate = current
                        current = self.r(current)
                    else:
                        f.w(0x38, 4, 0)
                        current = self.r(current + 0x10)
                    if self.r(current + 0x19, 1):
                        break
            missing = bool(self.r(candidate + 0x19, 1))
            if not missing:
                comparison = self.r(candidate + 0x1C, 4)
                missing = self.r(key_home, 4) < comparison
            if missing:
                if self.r(tree + 8) == 0x666666666666666:
                    self.call(0x1402AB280)
                    raise UnresolvedReplayTaskRebuild("source INT3 at140e6319c after length return")
                f.w(0x20, 8, tree)
                f.w(0x28, 8, 0)
                node = _raw(self.call(0x142D6BA78, 0x28), "tree allocation RAX")
                self.w(node + 0x1C, 4, self.r(key_home, 4))
                for home in (0, 8, 0x10):
                    self.w(node + home, 8, header)
                self.w(node + 0x18, 2, 0)
                f.w(0x20, 16, f.r(0x30, 16))
                candidate = _raw(self.call(0x140E646E0, tree, f.h(0x20), node), "tree linker RAX")
            return (candidate + 0x20) & _U64

    def successor(self, node: int) -> int:
        right = self.r(node + 0x10)
        if self.r(right + 0x19, 1):
            parent = self.r(node + 8)
            if not self.r(parent + 0x19, 1):
                while node == self.r(parent + 0x10):
                    node = parent
                    parent = self.r(parent + 8)
                    if self.r(parent + 0x19, 1):
                        break
            return parent
        node, child = right, self.r(right)
        while not self.r(child + 0x19, 1):
            node, child = child, self.r(child)
        return node

    def erase_successor(self, node: int) -> int:
        right = self.r(node + 0x10)
        if self.r(right + 0x19, 1):
            parent = self.r(node + 8)
            cursor = node
            if not self.r(parent + 0x19, 1):
                while cursor == self.r(parent + 0x10):
                    cursor = parent
                    parent = self.r(parent + 8)
                    if self.r(parent + 0x19, 1):
                        break
            following = parent
            parent = self.r(node + 8)
            if not self.r(parent + 0x19, 1):
                while node == self.r(parent + 0x10):
                    node = parent
                    parent = self.r(parent + 8)
                    if self.r(parent + 0x19, 1):
                        break
            return following
        child, following = self.r(right), right
        if not self.r(child + 0x19, 1):
            while True:
                further = self.r(child)
                following, child = child, further
                if self.r(child + 0x19, 1):
                    break
        child = self.r(right)
        if not self.r(child + 0x19, 1):
            while True:
                child = self.r(child)
                if self.r(child + 0x19, 1):
                    break
        return following

    def erase(self, tree: int, endpoints: int) -> int:
        begin, end = self.r(endpoints), self.r(endpoints + 8)
        current, count = begin, 0
        while current != end:
            current = self.successor(current)
            count = (count + 1) & _U64
        if begin == self.r(self.r(tree)) and self.r(end + 0x19, 1):
            self.call(0x140E64A00, tree)
        elif begin != end:
            current = begin
            while True:
                following = self.erase_successor(current)
                removed = _raw(self.call(0x140E642F0, tree, current), "tree unlink RAX")
                self.call(0x142D6BAB4, removed, 0x28)
                current = following
                if current == end:
                    break
        return count

    def bounds(self, queue: int, key: int) -> tuple[int, int]:
        header = self.r(queue + 0x7A8)
        begin = stop = header
        root = self.r(header + 8)
        current = root
        if not self.r(root + 0x19, 1):
            while True:
                current_key = self.r(current + 0x1C, 4)
                if current_key >= key:
                    if self.r(stop + 0x19, 1) and key < current_key:
                        stop = current
                    begin = current
                    current = self.r(current)
                else:
                    current = self.r(current + 0x10)
                if self.r(current + 0x19, 1):
                    break
        current = self.r(stop) if not self.r(stop + 0x19, 1) else root
        if not self.r(current + 0x19, 1):
            while True:
                if key < self.r(current + 0x1C, 4):
                    stop = current
                    current = self.r(current)
                else:
                    current = self.r(current + 0x10)
                if self.r(current + 0x19, 1):
                    break
        return begin, stop

    def advance(self, queue: int) -> None:
        with self.frame(self.profile.advance) as f:
            self.call(_TIMER, self.r(queue + 0x100))
            self.w(queue + 0x4C4, 4, 0)
            if self.r(queue + 0x7B0):
                first = self.r(self.r(queue + 0x7A8))
                key = self.r(first + 0x1C, 4)
                f.w(0x30, 4, key)
                if key:
                    self.w(queue + 0x4B4, 4, 0)
                    raw_time = self.call(0x140D6A880, self.r(_GAME))
                    key = f.r(0x30, 4)
                    if _eax(raw_time, "Game clock EAX") >= key:
                        if _raw(self.call(_GAME_TOKEN, self.r(_GAME)), "Game token RAX"):
                            self.call(0x140D6AD50, self.r(_GAME))
                        self.w(queue + 0x4C8, 4, self.r(queue + 0x4C8, 4) + 1)
                        raw_slot = self.call(_ENTRY, queue + 0x7A8, f.h(0x30))
                        key = f.r(0x30, 4)
                        pair = self.r(_raw(raw_slot, "advance entry RAX"))
                        self.w(queue + 0x3E4, 4, pair)
                        self.w(queue + 0x3F0, 4, pair >> 32)
                        begin, end = self.bounds(queue, key)
                        f.w(0x58, 8, end)
                        f.w(0x50, 8, begin)
                        self.call(_ERASE, queue + 0x7A8, f.h(0x50))
            count = self.r(queue + 0x3E4, 4)
            self.w(queue + 0x3E8, 4, count)
            external = self.r(_EXTERNAL)
            target = ((count + 1) & _U32) * self.r(queue + 0x3F0, 4) & _U32
            raw_period = self.call(_METRIC, external, 18) if external else 125
            padding = 0
            if target:
                period = _eax(raw_period, "advance period EAX")
                while True:
                    padding = (padding + period) & _U32
                    if padding >= target:
                        break
            slack = (padding - target) & _U32
            accumulated = (self.r(queue + 0x400, 4) + slack) & _U32
            self.w(queue + 0x400, 4, accumulated)
            if self.r(_DEBUG, 1) >= 1:
                f.w(0x38, 4, accumulated)
                logger = self.r(_LOGGER)
                f.w(0x60, 8, f.h(0x50))
                f.w(0x40, 4, 7)
                f.w(0x68, 8, f.h(0x38))
                f.w(0x58, 4, 7)
                f.w(0x20, 8, f.h(0x60))
                f.w(0x50, 4, slack)
                self.invoke(self.logger, _LOG, logger, 0x2A, 0x14326A6E0, 2, f.h(0x20))
            accumulated = self.r(queue + 0x400, 4)
            width = self.r(queue + 0x3F0, 4)
            while accumulated >= width:
                accumulated = (accumulated - width) & _U32
                pending = (self.r(queue + 0x3E8, 4) + 1) & _U32
                self.w(queue + 0x400, 4, accumulated)
                self.w(queue + 0x3E8, 4, pending)
                if self.r(_DEBUG, 1) >= 1:
                    f.w(0x60, 4, pending)
                    f.w(0x38, 4, accumulated)
                    logger = self.r(_LOGGER)
                    f.w(0x50, 8, f.h(0x60))
                    f.w(0x40, 4, 7)
                    f.w(0x58, 8, f.h(0x38))
                    f.w(0x20, 8, f.h(0x50))
                    f.w(0x68, 4, 7)
                    self.invoke(self.logger, _LOG, logger, 0x2A, 0x14326A730, 2, f.h(0x20))
                accumulated = self.r(queue + 0x400, 4)
                width = self.r(queue + 0x3F0, 4)

    def role(self, manager: int, output: int) -> int:
        with self.frame(self.profile.role) as f:
            table = self.r(0x143266E00, 16)
            mode = self.r(manager + 0x318, 4)
            f.w(0x40, 4, 8)
            f.w(0x30, 16, table)
            fallback = not f.contains(0x30, 5, mode)
            if not fallback:
                mode = self.r(manager + 0x318, 4)
                f.w(0x20, 4, 7)
                f.w(0x24, 4, 8)
                fallback = f.contains(0x20, 2, mode)
            if not fallback:
                slot = _raw(self.call(0x140E57AC0, manager + 0xCB8), "role session slot RAX")
                session = self.r(slot)
                fallback = not session
            if fallback:
                self.w(output, 8, self.r(0x143DAE440))
                return output
            for index in range(8):
                f.w(0x28, 8, 0)
                raw_record = self.call(0x1413D3FA0, session, f.h(0x28))
                receiver = self.r(manager + 0x2E8)
                record = _raw(raw_record, "role record RAX")
                raw_identity = (
                    self.invoke(self.virtual, self.r(self.r(receiver) + 0x18), receiver)
                    if receiver
                    else _U64
                )
                identity = self.r(record + 0x48)
                if identity == _raw(raw_identity, "role virtual18 RAX"):
                    self.w(output, 8, index + 1)
                    return output
            self.w(output, 8, self.r(0x143DADE30))
            return output

    def role_wrapper(self, manager: int, output: int) -> int:
        with self.frame(self.profile.role_wrapper) as f:
            slot = _raw(self.call(_ROLE, manager, f.h(0x38)), "role selector RAX")
            value = (self.r(slot, 4) - 1) & _U32
            self.w(output, 8, value)
            return output

    def timer(self, timer: int) -> int:
        with self.frame(self.profile.timer) as f:
            raw_now = self.call(_HOST)
            previous = self.r(timer + 0x2A4, 4)
            now = _eax(raw_now, "timer host EAX")
            if now == previous:
                return 0
            self.w(timer + 0x2A0, 4, self.r(timer + 0x2A0, 4) + 1)
            elapsed = (now - previous) & _U32
            self.w(timer + 0x2A4, 4, now)
            capacity = self.r(timer + 0x2C0, 4)
            index = self.r(timer + 0x2A0, 4)
            self.w(timer + 0x108, 4, elapsed)
            self.w(timer + 0x2C0, 4, min((capacity + 1) & _U32, 100))
            if _signed(index, 4) > 100:
                index = 0
                self.w(timer + 0x2A0, 4, 0)
            self.w(timer + _signed(index, 4) * 4 + 0x10C, 4, elapsed)
            index = _signed(self.r(timer + 0x2A0, 4), 4)
            sample = timer + index * 4 + 0x10C
            minimum = self.r(timer + 0x100, 4)
            self.w(timer + 0x100, 4, min(minimum, self.r(sample, 4)))
            maximum = self.r(timer + 0x104, 4)
            self.w(timer + 0x104, 4, max(maximum, self.r(sample, 4)))
            if self.r(timer + 0x2B0):
                receiver = _raw(self.call(0x140E16870, self.r(0x1442C3F98)), "timer metric RAX")
                raw_value = self.call(0x140E64A70, receiver)
                counter = self.r(timer + 0x2BC, 4)
                elapsed = self.r(timer + 0x108, 4)
                logger = self.r(timer + 0x2B0)
                f.w(0x20, 8, _raw(raw_value, "timer metric value RAX"))
                self.invoke(
                    self.timer_logger, 0x140F3EB40, logger, 0x14328DC50, elapsed, counter, f.h(0x20)
                )
            return self.r(timer + 0x108, 4)


def bind_replay_cycle_tuning(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    *,
    ceil_calls: ReplayTaskRebuildCalls,
    virtual_calls: ReplayTaskRebuildCalls,
    logger_home_calls: ReplayTaskRebuildCalls,
    timer_home_calls: ReplayTaskRebuildCalls,
    bind_local: LocalBinding,
    profile: ReplayCycleTuningProfile,
    mxcsr: int,
) -> ReplayTaskRebuildCalls:
    """Bind17 callers with live storage/homes and explicit actual child effects.

    ceil uses raw low-XMM0 words under masked nearest-even MXCSR1f80. Native
    status flags, saves/cookies, faults/EH/concurrency and unused registers are
    excluded. Source modular loops are retained, with no invented cutoffs.
    Unknown target arguments/payload/result pass through unchanged.
    """
    for channel in (calls, ceil_calls, virtual_calls, logger_home_calls, timer_home_calls):
        _validate(context, channel)
    _unsigned(mxcsr, 4, "MXCSR")
    if (
        mxcsr != 0x1F80
        or not callable(bind_local)
        or not isinstance(profile, ReplayCycleTuningProfile)
    ):
        raise ValueError("actual local/profile and MXCSR1f80 tuning context required")

    def dispatch(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        if target not in _ARITIES:
            if calls.call is None:
                raise UnresolvedReplayTaskRebuild(f"reached{target:x} is unavailable")
            return calls.call(target, args, data)
        if len(args) != _ARITIES[target] or data is not None:
            raise ValueError("malformed addressed cycle tuning call")
        _validate(context, calls, *args)
        body = _Tuning(
            context,
            bound,
            ceil_calls,
            virtual_calls,
            logger_home_calls,
            timer_home_calls,
            bind_local,
            profile,
        )
        if target == _TUNE:
            return body.tune(*args)
        if target == _MODE2:
            return body.mode2(*args)
        if target == _ADVANCE:
            body.advance(args[0])
        elif target == _RESET:
            body.w(args[0] + 0x4CC, 4, 0)
        elif target == _REJECT:
            body.w(args[0] + 0x4A0, 4, body.r(args[0] + 0x4A0, 4) + 1)
            return body.r(args[0] + 0x4A0, 4)
        elif target == _STATS:
            pointer = (args[0] + 0x2C) & _U64
            body.w(args[1], 8, pointer)
            return pointer
        elif target == _ROLE_A:
            body.w(args[1], 8, body.r(args[0] + 0xD18) - 1)
            return args[1]
        elif target == _ROLE_B:
            return body.role_wrapper(*args)
        elif target == _GATE:
            return body.gate(args[0])
        elif target == _WIDTH:
            return body.width(args[0])
        elif target == _FUTURE:
            return body.future(args[0])
        elif target == _SCHEDULE:
            body.schedule(*args)
        elif target == _ROLE:
            return body.role(*args)
        elif target == _TIMER:
            return body.timer(args[0])
        elif target == _GAME_TOKEN:
            return body.r(args[0] + 0x5C0)
        elif target == _ENTRY:
            return body.entry(*args)
        else:
            return body.erase(*args)
        return None

    bound = ReplayTaskRebuildCalls(dispatch)
    return bound
