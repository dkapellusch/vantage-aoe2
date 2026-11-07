"""Six complete build54800 manager queue callers over owned replay storage.

Source: world-manager-queue-source-v1; fixed API: world-manager-queue-fixed-api-v1.
All reached child services remain mandatory. Physical saves/cookies/native
stack adjacency, faults, EH and concurrent execution are outside this API.
"""

from __future__ import annotations

from contextlib import ExitStack
from dataclasses import dataclass
from types import TracebackType
from typing import Literal, Self

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
from .replay_unit_ai_construction import _local
from .replay_unit_ai_map import ReplayUnitAIMapAtomics, _release

_U32, _U64 = (1 << 32) - 1, (1 << 64) - 1
_DRAIN, _CLEAR, _PREPARE = 0x140F558A0, 0x140F52130, 0x140F52140
_DISPATCH, _CLOCK, _LOG = 0x140E05440, 0x140D6A880, 0x140F55A30
_ARITIES = {_DRAIN: 1, _CLEAR: 1, _PREPARE: 2, _DISPATCH: 5, _CLOCK: 1, _LOG: 5}


@dataclass(frozen=True, slots=True)
class ReplayManagerQueuesProfile:
    """Explicit private post-RSP prefixes; incoming fifth homes stay external."""

    drain: bytes
    prepare: bytes
    dispatch: bytes
    log: bytes

    def __post_init__(self) -> None:
        for seed, size in (
            (self.drain, 0x6C),
            (self.prepare, 0x58),
            (self.dispatch, 0x1C0),
            (self.log, 0xA8),
        ):
            if type(seed) is not bytes or len(seed) != size:
                raise ValueError("explicit6c/58/1c0/a8-hex-byte queue seeds required")


def _invoke(calls: ReplayTaskRebuildCalls, target: int, args: tuple[int, ...]) -> int | None:
    if calls.call is None:
        raise UnresolvedReplayTaskRebuild(f"reached{target:x} is unavailable")
    return calls.call(target, tuple(value & _U64 for value in args), None)


def _raw(value: int | None, label: str) -> int:
    if value is None:
        raise ValueError(f"{label} requires its actual rawu64 annotation")
    _unsigned(value, 8, label)
    return value


def _eax(value: int | None, label: str) -> int:
    return _raw(value, label) & _U32


def _al(value: int | None, label: str) -> int:
    return _raw(value, label) & 255


class _Frame:
    """Bind at the first semantic home operation, preserving earlier effects."""

    def __init__(
        self, context: ReplayTaskRebuildStorage, bind_local: LocalBinding, seed: bytes
    ) -> None:
        self.context, self.bind_local, self.seed = context, bind_local, seed
        self.stack = ExitStack()
        self.address: int | None = None

    def __enter__(self) -> Self:
        self.stack.__enter__()
        return self

    def __exit__(
        self,
        typ: type[BaseException] | None,
        error: BaseException | None,
        traceback: TracebackType | None,
    ) -> Literal[False]:
        # A local binding must not turn an actual child refusal into success.
        self.stack.__exit__(typ, error, traceback)
        return False

    def h(self, offset: int) -> int:
        if self.address is None:
            view = memoryview(bytearray(self.seed))
            self.address = self.stack.enter_context(_local(view, self.bind_local))
        return (self.address + offset) & _U64

    def r(self, offset: int, width: int) -> int:
        return _read(self.context, self.h(offset), width)

    def w(self, offset: int, width: int, value: int) -> None:
        _write(self.context, self.h(offset), width, value)

    def contains(self, offset: int, count: int, value: int) -> bool:
        # Source searches the current local cells, including callback changes.
        end = offset + count * 4
        while True:
            if self.r(offset, 4) == value:
                return True
            offset += 4
            if offset == end:
                return False


class _Queues:
    def __init__(
        self,
        context: ReplayTaskRebuildStorage,
        calls: ReplayTaskRebuildCalls,
        imports: ReplayTaskRebuildCalls,
        writer: ReplayTaskRebuildCalls,
        flag: ReplayTaskRebuildCalls,
        virtual: ReplayTaskRebuildCalls,
        logger: ReplayTaskRebuildCalls,
        error: ReplayTaskRebuildCalls,
        atomics: ReplayUnitAIMapAtomics,
        bind_local: LocalBinding,
        profile: ReplayManagerQueuesProfile,
    ) -> None:
        self.context, self.calls, self.imports = context, calls, imports
        self.writer, self.flag, self.virtual = writer, flag, virtual
        self.logger, self.error, self.atomics = logger, error, atomics
        self.bind_local, self.profile = bind_local, profile

    def r(self, address: int, width: int) -> int:
        return _read(self.context, address, width)

    def w(self, address: int, width: int, value: int) -> None:
        _write(self.context, address, width, value)

    def call(self, target: int, *args: int) -> int | None:
        return _invoke(self.calls, target, args)

    def drain(self, manager: int) -> None:
        with _Frame(self.context, self.bind_local, self.profile.drain) as f:
            queue, index = (manager + 0x228) & _U64, 0
            while True:
                f.w(0x68, 4, index)
                self.call(_PREPARE, manager, f.h(0x68))
                if self.r(queue + 8, 8):
                    while True:
                        mask = (self.r(queue - 8, 8) - 1) & _U64
                        array = self.r(queue - 0x10, 8)
                        slot = mask & self.r(queue, 8)
                        f.w(0x68, 4, index)
                        f.w(0x20, 4, 0)
                        row = self.r(array + slot * 8, 8)
                        dispatcher = self.r(manager + 0x2008, 8)
                        payload = self.r(row, 8)
                        length = self.r(row + 8, 4)
                        self.call(_DISPATCH, dispatcher, payload, length, f.h(0x68), f.h(0x20))
                        game = self.r(0x144353698, 8)
                        tag = self.r(payload, 1)
                        clock = self.call(_CLOCK, game)
                        f.w(0x20, 4, _eax(clock, "drain clock EAX"))
                        self.call(_LOG, manager + 0x2010, tag, payload, 11, f.h(0x20))
                        current = self.r(row, 8)
                        target = self.r(0x143199DD0, 8)
                        _invoke(self.imports, target, (current,))
                        remaining = (self.r(queue + 8, 8) - 1) & _U64
                        self.w(queue + 8, 8, remaining)
                        if not remaining:
                            self.w(queue, 8, 0)
                            break
                        self.w(queue, 8, self.r(queue, 8) + 1)
                index = (index + 1) & _U32
                queue = (queue + 0x30) & _U64
                if not index < 9:
                    return

    def _last_row(self, manager: int, index: int) -> int | None:
        header = (manager + (index + 11) * 0x30) & _U64
        count = self.r(header + 0x20, 8)
        if not count:
            return None
        head = self.r(header + 0x18, 8)
        last = (count + head - 1) & _U64
        capacity = self.r(header + 0x10, 8)
        last &= (capacity - 1) & _U64
        array = self.r(header + 8, 8)
        return self.r(array + last * 8, 8)

    def prepare(self, manager: int, index_home: int) -> int:
        with _Frame(self.context, self.bind_local, self.profile.prepare) as f:
            index = self.r(index_home, 4)
            pending = self.r(manager + 0x1FE0 + index * 4, 4)
            if _signed(pending, 4) > 1:
                row = self._last_row(manager, index)
                if row:
                    payload = self.r(row, 8)
                    low = pending & 0xFFFF
                    self.w(payload + 4, 2, low)
                    extent = (low * 4 + 0x2C) & _U32
                    if extent >= 4:
                        self.w(payload + 2, 2, (extent & 0xFFFF) - 4)
                    index = self.r(index_home, 4)
                    row = self._last_row(manager, index)
                    if row is not None:
                        delta = _signed((pending * 4) & _U32, 4) & _U64
                        size = (self.r(row + 8, 8) + delta) & _U64
                        f.w(0x50, 8, size)
                        target = self.r(0x143199DB0, 8)
                        allocation = _raw(_invoke(self.imports, target, (size,)), "malloc RAX")
                        if allocation:
                            old_size = self.r(row + 8, 8)
                            old_pointer = self.r(row, 8)
                            self.call(0x142D6E3B1, allocation, old_pointer, old_size)
                            self.call(
                                0x142D6E3B1,
                                allocation + old_size,
                                manager + index * 0x320 + 0x3C0,
                                delta,
                            )
                            old_pointer = self.r(row, 8)
                            target = self.r(0x143199DD0, 8)
                            _invoke(self.imports, target, (old_pointer,))
                            self.w(row + 8, 8, f.r(0x50, 8))
                            self.w(row, 8, allocation)
                    self._prepare_metrics(pending)
            index = self.r(index_home, 4)
            self.w(manager + 0x1FE0 + index * 4, 4, 0)
            return index

    def _prepare_metrics(self, pending: int) -> None:
        if not self.r(0x1443559B0, 8):
            return
        first = _raw(self.call(0x141021E00), "metrics accessor RAX")
        raw_stats = self.call(0x141021F00, first)
        game = self.r(0x144353698, 8)
        stats = _raw(raw_stats, "metrics object RAX")
        raw_clock = self.call(_CLOCK, game)
        previous = self.r(stats + 0x10, 4)
        clock = _eax(raw_clock, "metrics clock EAX")
        if previous != clock:
            self.w(stats + 0xC, 4, 0)
            self.w(stats + 0x10, 4, clock)
        total = (self.r(stats + 0xC, 4) + pending) & _U32
        self.w(stats + 0xC, 4, total)
        if total > self.r(stats + 4, 4):
            self.w(stats + 4, 4, total)
            self.w(stats + 8, 4, clock)
        self.w(stats, 4, self.r(stats, 4) + pending)

    def _time(self, clock: int, kind: int) -> int:
        return (
            _eax(self.call(0x140E68F80, clock), "queue time EAX") + (8 if kind == 2 else 2)
        ) & _U32

    def dispatch(
        self, manager: int, payload: int, length_word: int, index_home: int, fifth_home: int
    ) -> None:
        length = _signed(length_word & _U32, 4) & _U64
        related = 0
        with _Frame(self.context, self.bind_local, self.profile.dispatch) as f:
            index = self.r(index_home, 4)
            sentinel = self.r(0x143DA5054, 4)
            if index != sentinel and index < 9:
                world = self.call(0x140D6ACC0, self.r(0x144353698, 8))
                index = self.r(index_home, 4)
                f.w(0x30, 4, index)
                player = _raw(
                    self.call(0x141603FC0, _raw(world, "Game World RAX"), f.h(0x30)), "player RAX"
                )
                if player and self.r(player + 0x648, 4):
                    first = _raw(self.call(0x1417326E0, player, f.h(0x50)), "player slot RAX")
                    if self.r(first, 8):
                        second = _raw(
                            self.call(0x1417326E0, player, f.h(0x50)), "second player slot RAX"
                        )
                        status = self.call(0x140E4FC90, self.r(second, 8))
                        related = int(_eax(status, "relation EAX") == 4)
            global_mode = self.r(self.r(0x1442DA8A0, 8) + 0x318, 4)
            f.w(0x38, 4, 7)
            f.w(0x3C, 4, 8)
            matched = f.contains(0x38, 2, global_mode)
            if (
                not related
                and matched
                and self.r(manager + 0x31C, 4) == 1
                and self.r(payload, 1) != 0x20
            ):
                return
            mode = self.r(manager + 0x318, 4)
            for offset, value in ((0x40, 1), (0x44, 2), (0x48, 3)):
                f.w(offset, 4, value)
            if f.contains(0x40, 3, mode):
                slot = _raw(self.call(0x140E15A80, manager, f.h(0x50)), "input slot RAX")
                sequence = self.r(manager + 0x400, 4)
                clock = self.r(manager + 0x358, 8)
                clock_kind = self.r(clock + 8, 4)
                time = self._time(clock, clock_kind)
                f.w(0x30, 8, self.r(slot, 8))
                f.w(0x28, 8, f.h(0x30))
                f.w(0x20, 4, length)
                _invoke(
                    self.writer,
                    0x140E62450,
                    ((manager + 0x360) & _U64, time, sequence, payload, f.h(0x20), f.h(0x28)),
                )
            self._packet(manager, payload, length, related, fifth_home, f)

    def _packet(
        self, manager: int, payload: int, length: int, related: int, fifth_home: int, f: _Frame
    ) -> None:
        f.w(0x198, 16, 0)
        f.w(0x1A8, 16, 0)
        f.w(0x1B8, 8, 0)
        sequence = self.r(manager + 0x400, 4)
        clock = self.r(manager + 0x358, 8)
        kind = self.r(clock + 8, 4)
        time = self._time(clock, kind)
        extra = self.r(manager + 0x410, 4)
        f.w(0x198, 1, 0x3E)
        f.w(0x19C, 4, time + extra)
        f.w(0x1A0, 4, sequence)
        f.w(0x1A8, 16, 0)
        f.w(0x1B8, 8, 0)
        self.w(manager + 0x400, 4, self.r(manager + 0x400, 4) + 1)
        counter = manager + (0x408 if extra else 0x404)
        self.w(counter, 4, self.r(counter, 4) + 1)
        if length:
            self.call(0x1402DA470, f.h(0x1A8), length)
            begin = f.r(0x1A8, 8)
            self.call(0x142D6E3DB, begin, payload, length)
            f.w(0x1B0, 8, begin + length)
        else:
            self.call(0x142D6E3DB, 0, payload, 0)
            f.w(0x1B0, 8, length)
        if self.r(manager + 0x26B8, 1):
            self.call(0x1402D89A0, f.h(0x170), f.h(0x1A8))
            sequence = f.r(0x1A0, 4)
            f.w(0x188, 4, sequence)
            end = self.r(manager + 0x26A8, 8)
            if end != self.r(manager + 0x26B0, 8):
                capacity = f.r(0x180, 8)
                f.w(0x180, 8, 0)
                last = f.r(0x178, 8)
                f.w(0x178, 8, 0)
                first = f.r(0x170, 8)
                f.w(0x170, 8, 0)
                self.w(end, 8, first)
                self.w(end + 8, 8, last)
                self.w(end + 0x10, 8, capacity)
                self.w(end + 0x18, 4, sequence)
                self.w(manager + 0x26A8, 8, self.r(manager + 0x26A8, 8) + 0x20)
            else:
                self.call(0x140DF77F0, manager + 0x26A0, end, f.h(0x170))
            self.call(0x1402A8630, f.h(0x170))
        else:
            clock = self.r(manager + 0x358, 8)
            if self.r(clock + 8, 4) == 2:
                self._service(manager, f)
            else:
                value = self.r(fifth_home, 4)
                _invoke(self.flag, 0x140DF5B00, (manager, f.h(0x198), value, 1, 255))
        self._late(manager, related, f)
        self.call(0x1402A8630, f.h(0x1A8))

    def _service(self, manager: int, f: _Frame) -> None:
        f.w(0x170, 16, 0)
        f.w(0x178, 4, 0)
        f.w(0x170, 8, 0x143218B60)
        f.w(0x180, 16, 0)
        f.w(0x190, 8, 0)
        registry = _raw(self.call(0x14098F250), "registry RAX")
        service = _raw(self.call(0x140942110, registry, 0x1441216A8), "service RAX")
        if service:
            vptr = self.r(service, 8)
            target = self.r(vptr + 0x18, 8)
            _invoke(self.virtual, target, (service, f.h(0x70), f.h(0x170), f.h(0x198)))
        else:
            name = self.call(0x142D6E3ED, 0x1441216B0, 0x144C9CDB0)
            f.w(0x28, 8, _raw(name, "RTTI name RAX"))
            f.w(0x20, 8, 0x1431FAC58)
            _invoke(
                self.error, 0x140A08840, (f.h(0x70), 0, 0x1431FAC00, 0x2F5, f.h(0x20), f.h(0x28))
            )
        self.call(0x14096B890, f.h(0x70))
        control = f.r(0x90, 8)
        if control:
            _release(self.context, control, self.virtual, self.atomics)
        self.call(0x1402BD7F0, f.h(0x70))
        receiver = self.r(manager + 0x2E8, 8)
        count = (f.r(0x188, 4) - f.r(0x180, 4)) & _U32
        vptr = self.r(receiver, 8)
        data = f.r(0x180, 8)
        target = self.r(vptr + 0xE8, 8)
        _invoke(self.virtual, target, (receiver, data, count))
        clock = self.r(manager + 0x358, 8)
        now = self.call(0x140A71140)
        self.w(clock + 0x50, 4, _eax(now, "host clock EAX"))
        self.call(0x1402A8630, f.h(0x180))

    def _late(self, manager: int, related: int, f: _Frame) -> None:
        mode = self.r(manager + 0x318, 4)
        table = self.r(0x143266E00, 16)
        f.w(0x58, 16, table)
        f.w(0x68, 4, 8)
        if not f.contains(0x58, 5, mode):
            return
        if not _al(self.call(0x140A47100), "feature AL"):
            return
        self.w(manager + 0x2620, 1, related)
        timestamp = _eax(self.call(0x140A71140), "timestamp EAX")
        self._timestamp(manager + 0x25F8, timestamp)
        if not related:
            f.w(0x174, 4, f.r(0x198, 1))
            clock = self.r(manager + 0x358, 8)
            kind = self.r(clock + 8, 4)
            f.w(0x178, 4, self._time(clock, kind))
            f.w(0x17C, 4, f.r(0x1A0, 4))
            f.w(0x180, 1, related)
            source = _raw(self.call(0x140E4FD00, 0x1442DE060), "event counter RAX")
            f.w(0x170, 4, self.r(source + 0x20, 8) + 1)
            bus = _raw(self.call(0x140A6CB50), "event service RAX")
            event = _raw(self.call(0x140A45440, f.h(0x170), f.h(0xA0)), "event RAX")
            self.call(0x140A6D200, bus, event)
            self.call(0x1409053D0, f.h(0xA0))

    def _timestamp(self, header: int, timestamp: int) -> None:
        count = self.r(header + 0x20, 8)
        parity = ((count & 255) + self.r(header + 0x18, 1)) & 255
        if not parity & 1:
            threshold = ((count + 2) & _U64) >> 1
            if self.r(header + 0x10, 8) <= threshold:
                self.call(0x140E0AC80, header, 1)
        capacity = self.r(header + 0x10, 8)
        self.w(header + 0x18, 8, self.r(header + 0x18, 8) & ((capacity * 2 - 1) & _U64))
        total = (self.r(header + 0x20, 8) + self.r(header + 0x18, 8)) & _U64
        half = total >> 1
        offset = (((capacity - 1) & _U64) & half) * 8 & _U64
        array = self.r(header + 8, 8)
        if not self.r(array + offset, 8):
            allocation = self.call(0x142D6BA78, 0x10)
            array = self.r(header + 8, 8)
            self.w(array + offset, 8, _raw(allocation, "timestamp block RAX"))
        capacity = self.r(header + 0x10, 8)
        index = ((capacity - 1) & _U64) & half
        array = self.r(header + 8, 8)
        bucket = self.r(array + index * 8, 8)
        self.w(bucket + (total & 1) * 8, 8, timestamp)
        self.w(header + 0x20, 8, self.r(header + 0x20, 8) + 1)

    def log(
        self, header: int, tag_word: int, payload: int, kind_word: int, clock_home: int
    ) -> None:
        tag, kind = tag_word & 255, kind_word & _U32
        if not self.r(0x1443559B0, 8):
            return
        registry = _raw(self.call(0x141021E00), "log accessor RAX")
        if not _al(self.call(0x1410221D0, registry, kind), "log predicate AL"):
            return
        if self.r(0x144355057, 1) < 1:
            return
        with _Frame(self.context, self.bind_local, self.profile.log) as f:
            f.w(0x78, 1, tag)
            formatter = self.call(0x140F467C0, header, f.h(0x78))
            f.w(0x80, 16, 0)
            f.w(0x90, 8, 0)
            f.w(0x58, 4, 7)
            f.w(0x50, 4, self.r(clock_home, 4))
            receiver = _raw(formatter, "formatter RAX")
            vptr = self.r(receiver, 8)
            target = self.r(vptr + 8, 8)
            rendered = _invoke(self.virtual, target, (receiver, f.h(0x60), payload, target))
            f.w(0x48, 4, 0xE)
            f.w(0x40, 8, _raw(rendered, "formatted descriptor RAX"))
            f.w(0x80, 8, 0x14428BB30)
            f.w(0x88, 8, 0)
            f.w(0x90, 8, 0)
            f.w(0x98, 8, f.h(0x40))
            f.w(0xA0, 8, f.h(0x50))
            self.call(0x140A1BA10, f.h(0x80), 0x14328F2A8, 2, f.h(0x98))
            self.call(0x140A1B220, f.h(0x60))
            if self.r(0x144355057, 1) >= 1:
                f.w(0x38, 4, 0xF)
                f.w(0x30, 8, f.r(0x80, 8))
                f.w(0x98, 8, f.h(0x30))
                f.w(0x20, 8, f.h(0x98))
                self._emit_log(0x14328F2C0, f)
            if kind in (11, 12):
                world = _raw(self.call(0x140D6ACC0, self.r(0x144353698, 8)), "log World RAX")
                time = self.call(0x1416041F0, world)
                if self.r(0x144355057, 1) >= 1:
                    f.w(0x30, 4, _eax(time, "log World time EAX"))
                    f.w(0x98, 8, f.h(0x30))
                    f.w(0x20, 8, f.h(0x98))
                    f.w(0x38, 4, 7)
                    self._emit_log(0x14328F2D8 if kind == 11 else 0x14328F308, f)
            self.call(0x140A1B220, f.h(0x80))

    def _emit_log(self, format_address: int, f: _Frame) -> None:
        logger = self.r(0x144355068, 8)
        _invoke(self.logger, 0x14101ADB0, (logger, 0x1F, 255, format_address, 1, f.h(0x20)))


def bind_replay_manager_queues(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    *,
    imports: ReplayTaskRebuildCalls,
    writer_home_calls: ReplayTaskRebuildCalls,
    flag_calls: ReplayTaskRebuildCalls,
    virtual_calls: ReplayTaskRebuildCalls,
    logger_home_calls: ReplayTaskRebuildCalls,
    error_home_calls: ReplayTaskRebuildCalls,
    atomics: ReplayUnitAIMapAtomics,
    bind_local: LocalBinding,
    profile: ReplayManagerQueuesProfile,
) -> ReplayTaskRebuildCalls:
    """Own all six callers; preserve live fifth-home addresses and unknown calls.

    Dispatch/log fifth annotations are caller-home ADDRESSES, read late as
    DWORDs. Writer uses two live home addresses. Flag and logger channels carry
    explicit value/mask annotations for partial R9B/DL; formatter carries its
    known R9 target word. These annotations do not close unread callee ABI.

    Consumed return annotations are rawu64, projected to lowAL/EAX where source
    requires. Ignored returns stay opaque. Unknown calls delegate unchanged.
    No default backing/children, native process, queue cap or tick claim.
    """
    for channel in (
        calls,
        imports,
        writer_home_calls,
        flag_calls,
        virtual_calls,
        logger_home_calls,
        error_home_calls,
    ):
        _validate(context, channel)
    if (
        not isinstance(atomics, ReplayUnitAIMapAtomics)
        or not callable(bind_local)
        or not isinstance(profile, ReplayManagerQueuesProfile)
    ):
        raise ValueError("explicit queue atomics, local binding and profile required")

    def dispatch(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        if target not in _ARITIES:
            if calls.call is None:
                raise UnresolvedReplayTaskRebuild(f"reached{target:x} is unavailable")
            return calls.call(target, args, data)
        if len(args) != _ARITIES[target] or data is not None:
            raise ValueError("malformed addressed manager queue call")
        _validate(context, calls, *args)
        body = _Queues(
            context,
            bound,
            imports,
            writer_home_calls,
            flag_calls,
            virtual_calls,
            logger_home_calls,
            error_home_calls,
            atomics,
            bind_local,
            profile,
        )
        if target == _CLOCK:
            return body.call(0x140E68F80, args[0] + 0xA0)
        if target == _CLEAR:
            body.w(args[0] + 0x114, 1, 0)
        elif target == _PREPARE:
            return body.prepare(*args)
        elif target == _DRAIN:
            body.drain(*args)
        elif target == _DISPATCH:
            body.dispatch(*args)
        else:
            body.log(*args)
        return None

    bound = ReplayTaskRebuildCalls(dispatch)
    return bound
