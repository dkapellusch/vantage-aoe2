"""Source-led controls for the six queue callers, using owned Python memory.

The clock, memcpy thunk, row cleanup, Result validation and Result cleanup
compose with existing implementations. Other named children are explicit
authored capabilities; this fixture does not establish a restored World.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager, suppress
from typing import cast

import pytest

from vantage.replay_clock_storage import bind_replay_clock_storage
from vantage.replay_command_batch import (
    ReplayCommandBatchProfile,
    bind_replay_command_batch,
)
from vantage.replay_command_reader import (
    ReplayCommandReaderProfile,
    bind_replay_command_reader,
)
from vantage.replay_manager_queues import (
    ReplayManagerQueuesProfile,
    bind_replay_manager_queues,
)
from vantage.replay_memory import ReplayMemory, ReplayMemoryError
from vantage.replay_saved_result import bind_replay_saved_result
from vantage.replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
)
from vantage.replay_unit_ai_map import ReplayUnitAIMapAtomics
from vantage.replay_unit_constructor_support import bind_replay_unit_constructor_support

U64 = (1 << 64) - 1
DRAIN, CLEAR, PREPARE = 0x140F558A0, 0x140F52130, 0x140F52140
DISPATCH, CLOCK, LOG = 0x140E05440, 0x140D6A880, 0x140F55A30
MANAGER, DISPATCHER, GAME, TIME = 0x20000, 0x30000, 0x40000, 0x50000
SETTINGS, PLAYER, WORLD, INPUT = 0x60000, 0x70000, 0x80000, 0xF0000
SERVICE, FORMATTER, RECEIVER, CONTROL = 0xA0000, 0xB0000, 0xC0000, 0xD0000
STATS, ORDINAL, INDEX, FIFTH = 0xE0000, 0xE1000, 0xF1000, 0xF2000
ALLOC, FREE, COPY, NAME = 0xFF0001, 0xFF0002, 0xFF0003, 0xFF0004
VFORMAT, VSERVICE, VSEND, VDESTROY, VWEAK = 0xFE0008, 0xFE0018, 0xFE00E8, 0xFE0000, 0xFE0001
Handler = Callable[[tuple[int, ...]], int | None]


class StopHere(RuntimeError):
    """An explicit finite child refusal, retaining the reached prefix."""


def refuse(_args: tuple[int, ...]) -> int | None:
    raise StopHere("finite source boundary")


class Rig:
    def __init__(self) -> None:
        self.mem = ReplayMemory()
        for address, size in (
            (MANAGER, 0x2800),
            (DISPATCHER, 0x2800),
            (GAME, 0x1000),
            (TIME, 0x100),
            (SETTINGS, 0x400),
            (PLAYER, 0x700),
            (WORLD, 0x900),
            (INPUT, 8),
            (INDEX, 8),
            (FIFTH, 8),
            (STATS, 0x20),
            (ORDINAL, 0x30),
        ):
            self.mem.map_bytes(address, bytes(size))
        for obj in (SERVICE, FORMATTER, RECEIVER, CONTROL):
            self.mem.map_bytes(obj, bytes(0x100))
            self.mem.map_bytes(obj + 0x1000, bytes(0x100))
            self.mem.write(obj, 8, obj + 0x1000)
        self.mem.write(SERVICE + 0x1018, 8, VSERVICE)
        self.mem.write(FORMATTER + 0x1008, 8, VFORMAT)
        self.mem.write(RECEIVER + 0x10E8, 8, VSEND)
        self.mem.write(CONTROL + 0x1000, 8, VDESTROY)
        self.mem.write(CONTROL + 0x1008, 8, VWEAK)
        self.mem.write(MANAGER + 0x114, 1, 0x7B)
        self.mem.write(MANAGER + 0x2008, 8, DISPATCHER)
        self.mem.write(DISPATCHER + 0x358, 8, TIME)
        self.mem.write(DISPATCHER + 0x2E8, 8, RECEIVER)
        self.mem.write(GAME + 0x5C0, 8, WORLD)
        self.mem.write(GAME + 0xD0, 4, 9001)
        self.mem.write(WORLD + 0x228, 8, TIME)
        self.mem.write(TIME + 0x30, 4, 1234)
        self.mem.write(TIME + 0x18, 4, 7654)
        self.mem.write(INPUT, 8, 0x12345678)
        self.mem.write(FIFTH, 8, 0xAABBCCDD11223344)
        self.mem.map_bytes(0x144353698, GAME.to_bytes(8, "little"))
        self.mem.map_bytes(0x1442DA8A0, SETTINGS.to_bytes(8, "little"))
        self.mem.map_bytes(0x143DA5054, bytes.fromhex("ffffffff"))
        self.mem.map_bytes(0x1443559B0, bytes(8))
        self.mem.map_bytes(0x144355057, b"\x01")
        self.mem.map_bytes(0x144355068, (0x44556677).to_bytes(8, "little"))
        self.mem.map_bytes(0x143266E00, b"".join(v.to_bytes(4, "little") for v in (99, 98, 97, 96)))
        self.mem.map_bytes(0x143199DB0, bytes(0x28))
        self.mem.write(0x143199DB0, 8, ALLOC)
        self.mem.write(0x143199DD0, 8, FREE)
        self.mem.map_bytes(0x143199930, COPY.to_bytes(8, "little"))
        self.mem.map_bytes(0x1431999B8, NAME.to_bytes(8, "little"))
        self.handlers: dict[tuple[str, int], Handler] = {}
        self.events: list[tuple[str, int, int, int]] = []
        self.calls: list[tuple[str, int, tuple[int, ...]]] = []
        self.live: list[tuple[int, int]] = []
        self.snapshots: list[tuple[int, bytes]] = []
        self.packets: list[bytes] = []
        self.read_hook: Callable[[int, int, int], None] | None = None
        self.write_hook: Callable[[int, int, int], None] | None = None
        self.storage = ReplayTaskRebuildStorage(MANAGER, self.read, self.write)
        self.atomics = ReplayUnitAIMapAtomics(self.mem.compare_exchange_u32, self.mem.fetch_add_u32)
        self.profile = ReplayManagerQueuesProfile(
            bytes([0xA1]) * 0x6C, bytes([0xB2]) * 0x58, bytes([0xC3]) * 0x1C0, bytes([0xD4]) * 0xA8
        )
        self.imports = ReplayTaskRebuildCalls(self.import_call)
        ordinary = ReplayTaskRebuildCalls(self.ordinary)
        self.reader = bind_replay_command_reader(
            self.storage,
            ordinary,
            imports=self.imports,
            logger_home_calls=ordinary,
            atomics=self.atomics,
            bind_local=self.local,
            profile=ReplayCommandReaderProfile(bytes(0x58), bytes(0x50), bytes(0x90)),
        )
        self.support = bind_replay_unit_constructor_support(
            self.storage, ordinary, bind_local=self.local, imports=self.imports
        )
        self.clock = bind_replay_clock_storage(self.storage, ordinary, mxcsr=0x1F80)
        self.batch = bind_replay_command_batch(
            self.storage,
            self.mem.runtime_calls(ordinary),
            watson_home_calls=ordinary,
            error_home_calls=ordinary,
            atomics=self.atomics,
            bind_local=self.local,
            profile=ReplayCommandBatchProfile(bytes(0x28), bytes(0x28), bytes(0x50), bytes(0xB0)),
            mxcsr=0x1F80,
        )
        self.result = bind_replay_saved_result(
            self.storage, ordinary, atomics=self.atomics, imports=self.imports
        )
        self.bound = self.bind()

    def bind(self, **overrides: ReplayTaskRebuildCalls) -> ReplayTaskRebuildCalls:
        providers = {
            "calls": ReplayTaskRebuildCalls(self.ordinary),
            "imports": self.imports,
            "writer_home_calls": ReplayTaskRebuildCalls(self.writer),
            "flag_calls": ReplayTaskRebuildCalls(self.flag),
            "virtual_calls": ReplayTaskRebuildCalls(self.virtual),
            "logger_home_calls": ReplayTaskRebuildCalls(self.logger),
            "error_home_calls": ReplayTaskRebuildCalls(self.error),
        }
        providers.update(overrides)
        return bind_replay_manager_queues(
            self.storage,
            providers["calls"],
            imports=providers["imports"],
            writer_home_calls=providers["writer_home_calls"],
            flag_calls=providers["flag_calls"],
            virtual_calls=providers["virtual_calls"],
            logger_home_calls=providers["logger_home_calls"],
            error_home_calls=providers["error_home_calls"],
            atomics=self.atomics,
            bind_local=self.local,
            profile=self.profile,
        )

    def read(self, address: int, width: int) -> int:
        value = self.mem.read(address, width)
        self.events.append(("r", address, width, value))
        if self.read_hook is not None:
            self.read_hook(address, width, value)
        return value

    def write(self, address: int, width: int, value: int) -> None:
        self.mem.write(address, width, value)
        self.events.append(("w", address, width, value))
        if self.write_hook is not None:
            self.write_hook(address, width, value)

    @contextmanager
    def local(self, view: memoryview) -> Iterator[int]:
        with self.mem.bind_local(view) as address:
            self.live.append((len(view), address))
            try:
                yield address
            finally:
                self.snapshots.append((len(view), bytes(view)))
                self.live.pop()

    def frame(self, size: int) -> int:
        return next(address for length, address in reversed(self.live) if length == size)

    def recorded(self, channel: str, target: int, args: tuple[int, ...]) -> Handler | None:
        self.calls.append((channel, target, args))
        return self.handlers.get((channel, target))

    def import_call(
        self, target: int, args: tuple[int, ...], data: memoryview | None
    ) -> int | None:
        assert data is None
        handler = self.recorded("imports", target, args)
        if handler is not None:
            return handler(args)
        if target == ALLOC:
            return self.mem.allocate(args[0])
        if target == FREE:
            self.mem.free(args[0])
            return None
        if target == COPY:
            return self.mem.move(*args)
        if target == NAME:
            assert args == (0x1441216B0, 0x144C9CDB0)
            return 0xABCDEF1234
        raise UnresolvedReplayTaskRebuild(f"unprovided import{target:x}")

    def ordinary(self, target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        assert data is None
        handler = self.recorded("calls", target, args)
        if handler is not None:
            return handler(args)
        owner: ReplayTaskRebuildCalls | None = None
        if target in (0x140E68F80, 0x1416041F0):
            owner = self.reader
        elif target == 0x140E68F70:
            owner = self.clock
        elif target == 0x142D6E3B1:
            owner = self.support
        elif target in (0x1402A8630, 0x14096B890):
            owner = self.batch
        elif target == 0x1402BD7F0:
            owner = self.result
        if owner is not None:
            assert owner.call is not None
            return owner.call(target, args, data)
        if target == 0x140D6ACC0:
            return self.mem.read(args[0] + 0x5C0, 8)
        if target == 0x141603FC0:
            return 0
        if target == 0x140E15A80:
            return INPUT
        if target == 0x1402DA470:
            pointer = self.mem.allocate(args[1])
            self.mem.write(args[0], 8, pointer)
            self.mem.write(args[0] + 0x10, 8, pointer + args[1])
            return None
        if target == 0x142D6E3DB:
            return self.mem.move(*args)
        if target == 0x1402D89A0:
            begin = self.mem.read(args[1], 8)
            count = self.mem.read(args[1] + 8, 8) - begin
            cloned = self.mem.allocate(count) if count else 0
            self.mem.move(cloned, begin, count)
            for offset, value in ((0, cloned), (8, cloned + count), (16, cloned + count)):
                self.mem.write(args[0] + offset, 8, value)
            return None
        if target == 0x14098F250:
            return 0x5566
        if target == 0x140942110:
            return SERVICE
        if target == 0x142D6E3ED:
            imported = self.mem.read(0x1431999B8, 8)
            return self.import_call(imported, args, None)
        if target == 0x140A71140:
            return 5432
        if target == 0x140A47100:
            return 0
        if target == 0x142D6BA78:
            return self.mem.allocate(args[0])
        if target == 0x140E4FD00:
            return ORDINAL
        if target == 0x140A6CB50:
            return 0x7777
        if target == 0x140A45440:
            return 0x8888
        if target in (0x140A6D200, 0x1409053D0, 0x140A1B220):
            return None
        if target == 0x141021E00:
            return 0x1122
        if target == 0x141021F00:
            return STATS
        if target == 0x1410221D0:
            return 1
        if target == 0x140F467C0:
            return FORMATTER
        if target == 0x140A1BA10:
            self.mem.write(args[0], 8, 0x445566)
            return None
        raise UnresolvedReplayTaskRebuild(f"unprovided child{target:x}")

    def writer(self, target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        assert data is None and target == 0x140E62450 and len(args) == 6
        handler = self.recorded("writer", target, args)
        return handler(args) if handler is not None else None

    def flag(self, target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        assert data is None and target == 0x140DF5B00 and args[3:] == (1, 255)
        self.packets.append(self.mem.read_bytes(args[1], 0x28))
        handler = self.recorded("flag", target, args)
        return handler(args) if handler is not None else None

    def virtual(self, target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        assert data is None
        handler = self.recorded("virtual", target, args)
        if handler is not None:
            return handler(args)
        if target == VFORMAT:
            assert args[3] == VFORMAT
            self.mem.write(args[1], 8, 0)
            return 0xCAFEBABE
        if target == VSERVICE:
            self.mem.fill(args[1], 0, 0x30)
            return None
        if target in (VSEND, VDESTROY, VWEAK):
            return None
        raise UnresolvedReplayTaskRebuild(f"unprovided virtual{target:x}")

    def logger(self, target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        assert data is None and target == 0x14101ADB0
        assert len(args) == 6 and args[1:3] == (0x1F, 255) and args[4] == 1
        handler = self.recorded("logger", target, args)
        return handler(args) if handler is not None else None

    def error(self, target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        assert data is None and target == 0x140A08840
        handler = self.recorded("error", target, args)
        if handler is not None:
            return handler(args)
        self.mem.fill(args[0], 0, 0x30)
        return None

    def run(self, target: int, *args: int) -> int | None:
        assert self.bound.call is not None
        return self.bound.call(target, args, None)

    def ring(
        self,
        index: int = 0,
        *,
        pending: int = 0,
        payload_bytes: bytes = b"\x10\x11\x12\x13\x14\x15\x16\x17",
    ) -> tuple[int, int]:
        payload = self.mem.allocate(len(payload_bytes))
        self.mem.write_bytes(payload, payload_bytes)
        row, array = self.mem.allocate(16), self.mem.allocate(8)
        self.mem.write(row, 8, payload)
        self.mem.write(row + 8, 8, len(payload_bytes))
        self.mem.write(array, 8, row)
        header = MANAGER + 0x210 + index * 0x30
        for offset, value in ((8, array), (16, 1), (24, 0), (32, 1)):
            self.mem.write(header + offset, 8, value)
        self.mem.write(MANAGER + 0x1FE0 + index * 4, 4, pending)
        return row, payload

    def submit(self, length: int = 0, payload: int = 0) -> None:
        self.run(DISPATCH, DISPATCHER, payload, length, INDEX, FIFTH)

    def enable_late(self) -> None:
        self.mem.write(DISPATCHER + 0x318, 4, 99)
        self.handlers["calls", 0x140A47100] = lambda _args: 1
        array = self.mem.allocate(16)
        self.mem.fill(array, 0, 16)
        self.mem.write(DISPATCHER + 0x2600, 8, array)
        self.mem.write(DISPATCHER + 0x2608, 8, 2)


@pytest.mark.parametrize(
    "field,size", [("drain", 0x6C), ("prepare", 0x58), ("dispatch", 0x1C0), ("log", 0xA8)]
)
def test_profile_requires_exact_explicit_bytes(field: str, size: int) -> None:
    fields = {
        "drain": bytes(0x6C),
        "prepare": bytes(0x58),
        "dispatch": bytes(0x1C0),
        "log": bytes(0xA8),
    }
    for value in (bytes(size - 1), bytes(size + 1), cast(bytes, bytearray(size))):
        fields[field] = value
        with pytest.raises(ValueError):
            ReplayManagerQueuesProfile(**fields)


@pytest.mark.parametrize(
    "target,arity", [(DRAIN, 1), (CLEAR, 1), (PREPARE, 2), (DISPATCH, 5), (CLOCK, 1), (LOG, 5)]
)
@pytest.mark.parametrize("bad", [True, -1, 1 << 64])
def test_owned_raw_argument_domains_precede_effects(target: int, arity: int, bad: int) -> None:
    r = Rig()
    with pytest.raises(ValueError):
        r.run(target, bad, *([0] * (arity - 1)))
    assert r.events == [] and r.calls == [] and r.snapshots == []


@pytest.mark.parametrize(
    "target,arity", [(DRAIN, 1), (CLEAR, 1), (PREPARE, 2), (DISPATCH, 5), (CLOCK, 1), (LOG, 5)]
)
def test_owned_arity_and_data_validation(target: int, arity: int) -> None:
    r = Rig()
    assert r.bound.call is not None
    for count in (arity - 1, arity + 1):
        with pytest.raises(ValueError):
            r.bound.call(target, (0,) * count, None)
    with pytest.raises(ValueError):
        r.bound.call(target, (0,) * arity, memoryview(bytearray(1)))
    assert r.events == [] and r.calls == []


def test_unknown_call_preserves_argument_data_and_result_identity() -> None:
    r = Rig()
    args, data, result = (1, 2, 3), memoryview(bytearray(b"opaque")), object()

    def lower(target: int, actual: tuple[int, ...], view: memoryview | None) -> int | None:
        assert target == 0x123 and actual is args and view is data
        return cast(int, result)

    bound = r.bind(calls=ReplayTaskRebuildCalls(lower))
    assert bound.call is not None and bound.call(0x123, args, data) is result
    assert r.events == []


def test_byte_clear_and_real_clock_owner() -> None:
    r = Rig()
    before = r.mem.read_bytes(MANAGER + 0x110, 12)
    assert r.run(CLEAR, MANAGER) is None
    after = r.mem.read_bytes(MANAGER + 0x110, 12)
    assert after == before[:4] + b"\0" + before[5:]
    assert r.run(CLOCK, GAME) == 9001
    r.mem.map_bytes(0x30, (123).to_bytes(4, "little"))
    assert r.run(CLOCK, (1 << 64) - 0xA0) == 123
    assert r.snapshots == []


@pytest.mark.parametrize("pending", [0, 1, 0x80000000, 0xFFFFFFFF])
def test_prepare_signed_admission_and_final_current_index(pending: int) -> None:
    r = Rig()
    r.mem.write(MANAGER + 0x1FE0, 4, pending)
    r.mem.write(MANAGER + 0x1FE8, 4, 55)

    def change_index(address: int, width: int, _value: int) -> None:
        if address == MANAGER + 0x1FE0 and width == 4:
            r.mem.write(INDEX, 4, 2)

    r.read_hook = change_index
    assert r.run(PREPARE, MANAGER, INDEX) == 2
    assert r.mem.read(MANAGER + 0x1FE8, 4) == 0
    assert r.mem.read(MANAGER + 0x1FE0, 4) == pending
    assert r.calls == [] and r.snapshots == []


def test_prepare_real_copies_free_and_publication() -> None:
    r = Rig()
    row, old = r.ring(pending=3)
    r.mem.write_bytes(MANAGER + 0x3C0, b"abcdefghijkl")
    assert r.run(PREPARE, MANAGER, INDEX) == 0
    new = r.mem.read(row, 8)
    assert new != old and r.mem.read(row + 8, 8) == 20
    assert r.mem.read_bytes(new, 20) == b"\x10\x11\x34\x00\x03\x00\x16\x17abcdefghijkl"
    with pytest.raises(ReplayMemoryError):
        r.mem.read(old, 1)
    assert r.mem.read(MANAGER + 0x1FE0, 4) == 0
    assert [a for ch, t, a in r.calls if ch == "imports" and t == COPY] == [
        (new, old, 8),
        (new + 8, MANAGER + 0x3C0, 12),
    ]


def test_prepare_current_home50_survives_free_and_remains_live_through_metrics() -> None:
    r = Rig()
    row, old = r.ring(pending=2)
    r.mem.write(0x1443559B0, 8, 1)

    def free(args: tuple[int, ...]) -> int | None:
        assert args == (old,)
        r.mem.free(old)
        r.mem.write(r.frame(0x58) + 0x50, 8, 0x45)
        return None

    def stats(_args: tuple[int, ...]) -> int | None:
        assert r.mem.read(r.frame(0x58) + 0x50, 8) == 0x45
        return STATS

    r.handlers["imports", FREE] = free
    r.handlers["calls", 0x141021F00] = stats
    r.run(PREPARE, MANAGER, INDEX)
    assert r.mem.read(row + 8, 8) == 0x45
    assert r.mem.read(STATS, 4) == 2
    assert r.mem.read(STATS + 0xC, 4) == 2
    assert r.mem.read(STATS + 0x10, 4) == 9001


def test_prepare_null_allocation_keeps_prior_word_stores_and_clears_counter() -> None:
    r = Rig()
    row, payload = r.ring(pending=0x10002)
    r.handlers["imports", ALLOC] = lambda _args: 0
    r.run(PREPARE, MANAGER, INDEX)
    assert r.mem.read(payload + 4, 2) == 2
    assert r.mem.read(payload + 2, 2) == 48
    assert r.mem.read(row, 8) == payload and r.mem.read(row + 8, 8) == 8
    assert not any(ch == "imports" and t in (COPY, FREE) for ch, t, _a in r.calls)
    assert r.mem.read(MANAGER + 0x1FE0, 4) == 0


def test_prepare_distinct_initial_second_and_final_indices() -> None:
    r = Rig()
    row0, payload0 = r.ring(0, pending=3)
    row1, payload1 = r.ring(1, pending=7, payload_bytes=b"12345678")
    r.mem.write_bytes(MANAGER + 0x6E0, b"ABCDEFGHIJKL")
    r.mem.write(MANAGER + 0x1FE8, 4, 99)

    def word_written(address: int, width: int, _value: int) -> None:
        if address == payload0 + 4 and width == 2:
            r.mem.write(INDEX, 4, 1)

    def free(args: tuple[int, ...]) -> int | None:
        assert args == (payload1,)
        r.mem.free(payload1)
        r.mem.write(INDEX, 4, 2)
        return None

    r.write_hook = word_written
    r.handlers["imports", FREE] = free
    assert r.run(PREPARE, MANAGER, INDEX) == 2
    assert r.mem.read(row0, 8) == payload0
    assert r.mem.read_bytes(r.mem.read(row1, 8), 20) == b"12345678ABCDEFGHIJKL"
    assert [r.mem.read(MANAGER + 0x1FE0 + i * 4, 4) for i in range(3)] == [3, 7, 0]


@pytest.mark.parametrize(
    "pending,delta", [(0x20000000, 0xFFFFFFFF80000000), (0x40000000, 0), (0x7FFFFFFF, U64 - 3)]
)
def test_prepare_signed_delta_preserved_without_huge_allocation(pending: int, delta: int) -> None:
    r = Rig()
    r.ring(pending=pending)
    seen: list[int] = []

    def allocation(args: tuple[int, ...]) -> int | None:
        seen.append(args[0])
        raise StopHere("allocator request only")

    r.handlers["imports", ALLOC] = allocation
    with pytest.raises(StopHere):
        r.run(PREPARE, MANAGER, INDEX)
    assert seen == [(8 + delta) & U64]
    assert r.mem.read(MANAGER + 0x1FE0, 4) == pending


def test_metrics_invalid_stats_defers_until_after_current_game_read() -> None:
    r = Rig()
    r.ring(pending=2)
    r.mem.write(0x1443559B0, 8, 1)
    r.handlers["calls", 0x141021F00] = lambda _args: None
    with pytest.raises(ValueError, match="metrics object"):
        r.run(PREPARE, MANAGER, INDEX)
    assert r.events[-1] == ("r", 0x144353698, 8, GAME)
    assert not any(t == 0x140E68F80 for _ch, t, _a in r.calls)


def test_drain_all_nine_empty_helpers_without_clearing_heads_or_flag() -> None:
    r = Rig()
    for i in range(9):
        r.mem.write(MANAGER + 0x228 + i * 0x30, 8, 100 + i)
    r.run(DRAIN, MANAGER)
    assert [v for kind, _a, width, v in r.events if kind == "w" and width == 4][:9] != []
    counter_writes = [
        (a, v)
        for kind, a, width, v in r.events
        if kind == "w" and width == 4 and MANAGER + 0x1FE0 <= a < MANAGER + 0x2004
    ]
    assert counter_writes == [(MANAGER + 0x1FE0 + i * 4, 0) for i in range(9)]
    assert [r.mem.read(MANAGER + 0x228 + i * 0x30, 8) for i in range(9)] == list(range(100, 109))
    assert r.mem.read(MANAGER + 0x114, 1) == 0x7B
    assert r.calls == []


def test_positive_drain_actual_children_share_late_fifth_home_and_free_payload() -> None:
    r = Rig()
    row, payload = r.ring()

    def resize(args: tuple[int, ...]) -> int | None:
        pointer = r.mem.allocate(args[1])
        r.mem.write(args[0], 8, pointer)
        r.mem.write(args[0] + 16, 8, pointer + args[1])
        r.mem.write(r.frame(0x6C) + 0x20, 4, 0x1234)
        return None

    r.handlers["calls", 0x1402DA470] = resize
    r.run(DRAIN, MANAGER)
    flag = next(args for ch, _t, args in r.calls if ch == "flag")
    assert flag[2:] == (0x1234, 1, 255)
    assert r.packets[0][0] == 0x3E
    assert int.from_bytes(r.packets[0][4:8], "little") == 1236
    assert r.mem.read(MANAGER + 0x230, 8) == 0
    assert r.mem.read(MANAGER + 0x228, 8) == 0
    assert r.mem.read(row, 8) == payload
    with pytest.raises(ReplayMemoryError):
        r.mem.read(payload, 1)


def test_drain_held_sub_flags_override_postwrite_count_mutation() -> None:
    r = Rig()
    r.ring()

    def count_written(address: int, width: int, value: int) -> None:
        if address == MANAGER + 0x230 and width == 8 and value == 0:
            r.mem.write(address, 8, 7)
            r.mem.write(MANAGER + 0x228, 8, 9)

    r.write_hook = count_written
    r.run(DRAIN, MANAGER)
    assert r.mem.read(MANAGER + 0x230, 8) == 7
    assert r.mem.read(MANAGER + 0x228, 8) == 0
    assert len(r.packets) == 1


def test_drain_free_mutated_zero_count_underflows_then_increments_current_head() -> None:
    r = Rig()
    _row, payload = r.ring()
    r.mem.write(SETTINGS + 0x318, 4, 7)
    r.mem.write(DISPATCHER + 0x31C, 4, 1)
    lookups = 0

    def lookup(_args: tuple[int, ...]) -> int | None:
        nonlocal lookups
        lookups += 1
        if lookups == 2:
            raise StopHere("next actual child after underflow")
        return 0

    def free(args: tuple[int, ...]) -> int | None:
        assert args == (payload,)
        r.mem.free(payload)
        r.mem.write(MANAGER + 0x230, 8, 0)
        r.mem.write(MANAGER + 0x228, 8, 4)
        return None

    r.handlers["calls", 0x141603FC0] = lookup
    r.handlers["imports", FREE] = free
    with pytest.raises(StopHere):
        r.run(DRAIN, MANAGER)
    assert r.mem.read(MANAGER + 0x230, 8) == U64
    assert r.mem.read(MANAGER + 0x228, 8) == 5


def test_dispatch_blocked_gate_has_no_packet_counter_or_cleanup_effects() -> None:
    r = Rig()
    payload = r.mem.allocate(1)
    r.mem.write(payload, 1, 0x10)
    r.mem.write(SETTINGS + 0x318, 4, 7)
    r.mem.write(DISPATCHER + 0x31C, 4, 1)
    r.submit(1, payload)
    assert not any(t in (0x140E68F80, 0x1402A8630, 0x142D6E3DB) for _ch, t, _a in r.calls)
    assert not any(
        kind == "w" and DISPATCHER <= a < DISPATCHER + 0x2800 for kind, a, _w, _v in r.events
    )


def test_dispatch_bad_world_return_preserves_index_home_publication() -> None:
    r = Rig()
    r.handlers["calls", 0x140D6ACC0] = lambda _args: None
    with pytest.raises(ValueError, match="Game World"):
        r.submit()
    state = next(data for size, data in r.snapshots if size == 0x1C0)
    assert state[0x30:0x34] == bytes(4)
    assert not any(t == 0x141603FC0 for _ch, t, _a in r.calls)


@pytest.mark.parametrize("length,raw64", [(0x80000000, 0xFFFFFFFF80000000), (0xFFFFFFFF, U64)])
def test_dispatch_signed_length_refuses_after_counter_prefix(length: int, raw64: int) -> None:
    r = Rig()
    captured: list[int] = []

    def resize(args: tuple[int, ...]) -> int | None:
        captured.append(args[1])
        raise StopHere("finite resize request")

    r.handlers["calls", 0x1402DA470] = resize
    with pytest.raises(StopHere):
        r.submit(length)
    assert captured == [raw64]
    assert r.mem.read(DISPATCHER + 0x400, 4) == 1
    assert r.mem.read(DISPATCHER + 0x404, 4) == 1
    assert not any(t == 0x1402A8630 for _ch, t, _a in r.calls)


def test_zero_length_calls_real_memmove_with_zero_destination() -> None:
    r = Rig()
    r.submit()
    assert ("calls", 0x142D6E3DB, (0, 0, 0)) in r.calls
    assert r.mem.read(DISPATCHER + 0x404, 4) == 1


def test_optional_writer_live_homes_and_later_current_sequence() -> None:
    r = Rig()
    r.mem.write(DISPATCHER + 0x318, 4, 1)
    r.mem.write(DISPATCHER + 0x400, 4, 42)

    def writer(args: tuple[int, ...]) -> int | None:
        assert args[:4] == (DISPATCHER + 0x360, 1236, 42, 0)
        assert r.mem.read(args[4], 4) == 0
        assert r.mem.read(args[4] + 4, 4) == 0xC3C3C3C3
        assert r.mem.read(r.mem.read(args[5], 8), 8) == 0x12345678
        r.mem.write(DISPATCHER + 0x400, 4, 99)
        r.mem.write(DISPATCHER + 0x410, 4, 7)
        r.mem.write(FIFTH, 4, 0x8765)
        return None

    r.handlers["writer", 0x140E62450] = writer
    r.submit()
    assert int.from_bytes(r.packets[0][4:8], "little") == 1243
    assert int.from_bytes(r.packets[0][8:12], "little") == 99
    assert r.mem.read(DISPATCHER + 0x400, 4) == 100
    assert r.mem.read(DISPATCHER + 0x408, 4) == 1
    assert next(args for ch, _t, args in r.calls if ch == "flag")[2] == 0x8765


def test_pending_inline_move_zeros_sources_before_destination_and_uses_current_end() -> None:
    r = Rig()
    r.mem.write(DISPATCHER + 0x26B8, 1, 1)
    destination = r.mem.allocate(0x80)
    r.mem.fill(destination, 0xA5, 0x80)
    r.mem.write(DISPATCHER + 0x26A8, 8, destination)
    r.mem.write(DISPATCHER + 0x26B0, 8, destination + 0x80)

    def published(address: int, _width: int, _value: int) -> None:
        if address == destination:
            f = r.frame(0x1C0)
            assert r.mem.read_bytes(f + 0x170, 24) == bytes(24)
            r.mem.write(DISPATCHER + 0x26A8, 8, destination + 0x40)

    r.write_hook = published
    r.submit()
    assert r.mem.read(DISPATCHER + 0x26A8, 8) == destination + 0x60
    assert r.mem.read_bytes(destination + 0x1C, 4) == b"\xa5" * 4
    assert not any(ch == "flag" or t == 0x140DF77F0 for ch, t, _a in r.calls)


def test_mode2_result_cleanup_and_true_strong_weak_release() -> None:
    r = Rig()
    r.mem.write(TIME + 8, 4, 2)
    r.mem.write(CONTROL + 8, 4, 1)
    r.mem.write(CONTROL + 12, 4, 1)

    def service(args: tuple[int, ...]) -> int | None:
        r.mem.fill(args[1], 0, 0x30)
        r.mem.write(args[1] + 0x20, 8, CONTROL)
        return None

    r.handlers["virtual", VSERVICE] = service
    r.submit()
    assert r.mem.read(CONTROL + 8, 4) == r.mem.read(CONTROL + 12, 4) == 0
    targets = [t for ch, t, _a in r.calls if ch == "virtual"]
    assert targets == [VSERVICE, VDESTROY, VWEAK, VSEND]
    assert r.mem.read(TIME + 0x50, 4) == 5432
    assert not any(ch == "flag" for ch, _t, _a in r.calls)


def test_missing_service_rtti_pointer_and_live_error_homes() -> None:
    r = Rig()
    r.mem.write(TIME + 8, 4, 2)
    r.handlers["calls", 0x140942110] = lambda _args: 0
    captured: list[tuple[int, int]] = []

    def error(args: tuple[int, ...]) -> int | None:
        assert args[1:4] == (0, 0x1431FAC00, 0x2F5)
        captured.append((r.mem.read(args[4], 8), r.mem.read(args[5], 8)))
        r.mem.fill(args[0], 0, 0x30)
        return None

    r.handlers["error", 0x140A08840] = error
    r.mem.write(0x1431999B8, 8, CLOCK)
    r.handlers["imports", CLOCK] = lambda args: (
        0xFEDCBA if args == (0x1441216B0, 0x144C9CDB0) else None
    )
    r.submit()
    assert captured == [(0x1431FAC58, 0xFEDCBA)]


def test_late_type_publication_precedes_failing_clock() -> None:
    r = Rig()
    r.enable_late()
    calls = 0

    def clock(_args: tuple[int, ...]) -> int | None:
        nonlocal calls
        calls += 1
        if calls == 2:
            f = r.frame(0x1C0)
            assert r.mem.read(f + 0x174, 4) == 0x3E
            assert r.mem.read(f + 0x178, 4) == 0xC3C3C3C3
            raise StopHere("third time path")
        return 1234

    r.handlers["calls", 0x140E68F80] = clock
    with pytest.raises(StopHere):
        r.submit()
    assert r.mem.read(DISPATCHER + 0x2618, 8) == 1
    assert not any(t == 0x140E4FD00 for _ch, t, _a in r.calls)


def test_timestamp_allocation_current_array_and_full_event_chain() -> None:
    r = Rig()
    r.enable_late()
    old_array = r.mem.read(DISPATCHER + 0x2600, 8)
    new_array = r.mem.allocate(16)
    r.mem.fill(new_array, 0, 16)

    def allocate(args: tuple[int, ...]) -> int | None:
        assert args == (16,)
        result = r.mem.allocate(16)
        r.mem.write(DISPATCHER + 0x2600, 8, new_array)
        return result

    r.handlers["calls", 0x142D6BA78] = allocate
    r.submit()
    assert r.mem.read(old_array, 8) == 0
    bucket = r.mem.read(new_array, 8)
    assert r.mem.read(bucket, 8) == 5432
    assert r.mem.read(DISPATCHER + 0x2618, 8) == 1
    assert ("calls", 0x140A6D200, (0x7777, 0x8888)) in r.calls
    cleanup = next(args for _ch, t, args in r.calls if t == 0x1409053D0)
    assert cleanup != (0x8888,)


@pytest.mark.parametrize("raw,accepted", [(0, False), (0x100, False), (0x101, True), (U64, True)])
def test_feature_rawu64_projects_low_al(raw: int, accepted: bool) -> None:
    r = Rig()
    r.enable_late()
    r.handlers["calls", 0x140A47100] = lambda _args: raw
    r.submit()
    assert bool(r.mem.read(DISPATCHER + 0x2618, 8)) is accepted


@pytest.mark.parametrize("bad", [None, True, -1, 1 << 64])
def test_feature_invalid_annotation_keeps_packet_counter_prefix(bad: int | None) -> None:
    r = Rig()
    r.enable_late()
    r.handlers["calls", 0x140A47100] = lambda _args: bad
    with pytest.raises(ValueError):
        r.submit()
    assert r.mem.read(DISPATCHER + 0x400, 4) == 1
    assert not any(t == 0x140A71140 for _ch, t, _a in r.calls)


@pytest.mark.parametrize("gate", ["global", "predicate", "level"])
def test_three_log_gates_do_not_map_or_read_incoming_clock(gate: str) -> None:
    r = Rig()
    if gate != "global":
        r.mem.write(0x1443559B0, 8, 1)
    if gate == "predicate":
        r.handlers["calls", 0x1410221D0] = lambda _args: 0x100
    if gate == "level":
        r.mem.write(0x144355057, 1, 0)
    r.run(LOG, MANAGER + 0x2010, 5, 0, 11, 0)
    assert r.snapshots == []
    assert not any(a == 0 for _k, a, _w, _v in r.events)


def test_log_late_clock_and_formatter_r9_target_annotation() -> None:
    r = Rig()
    r.mem.write(0x1443559B0, 8, 1)

    def accessor(_args: tuple[int, ...]) -> int | None:
        r.mem.write(FIFTH, 4, 0x87654321)
        return FORMATTER

    def formatter(args: tuple[int, ...]) -> int | None:
        assert args == (FORMATTER, r.frame(0xA8) + 0x60, 0xABC, VFORMAT)
        assert r.mem.read(r.frame(0xA8) + 0x50, 4) == 0x87654321
        assert r.mem.read(r.frame(0xA8) + 0x54, 4) == 0xD4D4D4D4
        return 0xCAFEBABE

    r.handlers["calls", 0x140F467C0] = accessor
    r.handlers["virtual", VFORMAT] = formatter
    r.run(LOG, MANAGER + 0x2010, (1 << 40) | 5, 0xABC, 0, FIFTH)
    logs = [args for ch, _t, args in r.calls if ch == "logger"]
    assert len(logs) == 1 and logs[0][3] == 0x14328F2C0


def test_formatter_invalid_result_retains_preceding_type_store() -> None:
    r = Rig()
    r.mem.write(0x1443559B0, 8, 1)
    r.handlers["virtual", VFORMAT] = lambda _args: None
    with pytest.raises(ValueError, match="formatted descriptor"):
        r.run(LOG, MANAGER, 1, 0, 0, FIFTH)
    state = next(data for size, data in r.snapshots if size == 0xA8)
    assert state[0x48:0x4C] == b"\x0e\0\0\0"
    assert state[0x40:0x48] == b"\xd4" * 8
    assert not any(t in (0x140A1BA10, 0x140A1B220) for _ch, t, _a in r.calls)


@pytest.mark.parametrize("kind,format_address", [(11, 0x14328F2D8), (12, 0x14328F308)])
def test_log_kind_time_descriptors_and_second_store_order(kind: int, format_address: int) -> None:
    r = Rig()
    r.mem.write(0x1443559B0, 8, 1)
    observations: list[tuple[int, int]] = []

    def logged(args: tuple[int, ...]) -> int | None:
        table = r.mem.read(args[5], 8)
        descriptor = r.mem.read(table, 8)
        observations.append((args[3], r.mem.read(descriptor + 8, 4)))
        if args[3] == format_address:
            assert r.mem.read(descriptor, 4) == 7654
        return None

    r.handlers["logger", 0x14101ADB0] = logged
    r.run(LOG, MANAGER, 1, 0, (1 << 40) | kind, FIFTH)
    assert observations == [(0x14328F2C0, 15), (format_address, 7)]
    frame = (
        next(
            address
            for kind_, address, _width, _value in r.events
            if kind_ == "w" and _width == 1 and _value == 1
        )
        - 0x78
    )
    writes = [
        (a - frame, width, value)
        for k, a, width, value in r.events
        if k == "w" and frame <= a < frame + 0xA8
    ]
    last_type = max(i for i, row in enumerate(writes) if row == (0x38, 4, 7))
    assert writes[last_type - 1][0] == 0x20 and writes[last_type - 2][0] == 0x98


def test_log_disabled_after_world_clock_keeps_unused_return_opaque() -> None:
    r = Rig()
    r.mem.write(0x1443559B0, 8, 1)

    def time(_args: tuple[int, ...]) -> int | None:
        r.mem.write(0x144355057, 1, 0)
        return None

    r.handlers["calls", 0x1416041F0] = time
    r.run(LOG, MANAGER, 1, 0, 11, FIFTH)
    assert len([1 for ch, _t, _a in r.calls if ch == "logger"]) == 1
    assert len([1 for _ch, t, _a in r.calls if t == 0x140A1B220]) == 2


@pytest.mark.parametrize(
    "channel",
    [
        "flag_calls",
        "writer_home_calls",
        "virtual_calls",
        "error_home_calls",
        "logger_home_calls",
        "imports",
    ],
)
def test_missing_channel_refuses_at_reach_and_retains_prefix(channel: str) -> None:
    r = Rig()
    r.bound = r.bind(**{channel: ReplayTaskRebuildCalls(None)})
    if channel == "writer_home_calls":
        r.mem.write(DISPATCHER + 0x318, 4, 1)
    elif channel in ("virtual_calls", "error_home_calls"):
        r.mem.write(TIME + 8, 4, 2)
        if channel == "error_home_calls":
            r.handlers["calls", 0x140942110] = lambda _args: 0
    elif channel == "logger_home_calls":
        r.mem.write(0x1443559B0, 8, 1)
    elif channel == "imports":
        r.ring()
    with pytest.raises(UnresolvedReplayTaskRebuild):
        if channel == "logger_home_calls":
            r.run(LOG, MANAGER, 1, 0, 0, FIFTH)
        elif channel == "imports":
            r.run(DRAIN, MANAGER)
        else:
            r.submit()
    if channel in ("flag_calls", "virtual_calls", "error_home_calls", "imports"):
        assert r.mem.read(DISPATCHER + 0x400, 4) == 1
    assert r.snapshots


@pytest.mark.parametrize("capacity,head,selected", [(0, 1, 1), (1, U64, 0), (3, 3, 2)])
def test_drain_literal_capacity_mask_with_finite_child_refusal(
    capacity: int,
    head: int,
    selected: int,
) -> None:
    r = Rig()
    row, _payload = r.ring()
    array = r.mem.allocate(24)
    r.mem.fill(array, 0, 24)
    r.mem.write(array + selected * 8, 8, row)
    r.mem.write(MANAGER + 0x218, 8, array)
    r.mem.write(MANAGER + 0x220, 8, capacity)
    r.mem.write(MANAGER + 0x228, 8, head)
    r.handlers["calls", 0x141603FC0] = refuse
    with pytest.raises(StopHere):
        r.run(DRAIN, MANAGER)
    assert ("r", array + selected * 8, 8, row) in r.events
    assert r.mem.read(MANAGER + 0x230, 8) == 1


def test_prepare_first_null_row_skips_payload_metrics_and_mapping() -> None:
    r = Rig()
    _row, _payload = r.ring(pending=2)
    array = r.mem.read(MANAGER + 0x218, 8)
    r.mem.write(array, 8, 0)
    r.mem.write(0x1443559B0, 8, 1)
    assert r.run(PREPARE, MANAGER, INDEX) == 0
    assert r.calls == [] and r.snapshots == []
    assert r.mem.read(MANAGER + 0x1FE0, 4) == 0


def test_prepare_second_null_row_refuses_after_payload_word_prefix() -> None:
    r = Rig()
    _row, payload = r.ring(pending=2)
    array = r.mem.read(MANAGER + 0x218, 8)

    def changed(address: int, width: int, _value: int) -> None:
        if address == payload + 2 and width == 2:
            r.mem.write(array, 8, 0)

    r.write_hook = changed
    with pytest.raises(ReplayMemoryError):
        r.run(PREPARE, MANAGER, INDEX)
    assert r.mem.read(payload + 4, 2) == 2 and r.mem.read(payload + 2, 2) == 48
    assert r.mem.read(MANAGER + 0x1FE0, 4) == 2
    assert r.calls == []


def test_copy_import_alias_does_not_reenter_owned_clock() -> None:
    r = Rig()
    row, _payload = r.ring(pending=2)
    r.mem.write(0x143199930, 8, CLOCK)
    observed: list[tuple[int, ...]] = []

    def copy(args: tuple[int, ...]) -> int | None:
        observed.append(args)
        return r.mem.move(*args)

    r.handlers["imports", CLOCK] = copy
    r.run(PREPARE, MANAGER, INDEX)
    assert len(observed) == 2 and all(len(args) == 3 for args in observed)
    assert r.mem.read(row + 8, 8) == 16


def test_drain_reads_row_length_as_dword() -> None:
    r = Rig()
    row, _payload = r.ring()
    r.mem.write(row + 8, 8, 0xFFFFFFFF00000000)
    r.run(DRAIN, MANAGER)
    assert ("r", row + 8, 4, 0) in r.events
    assert not any(k == "r" and a == row + 8 and width == 8 for k, a, width, _v in r.events)
    assert not any(t == 0x1402DA470 for _ch, t, _a in r.calls)


def test_two_player_slots_and_related_flag_skip_only_final_event() -> None:
    r = Rig()
    r.enable_late()
    r.mem.write(PLAYER + 0x648, 4, 1)
    first, second = r.mem.allocate(8), r.mem.allocate(8)
    r.mem.write(first, 8, 0x1111)
    r.mem.write(second, 8, 0x2222)
    r.handlers["calls", 0x141603FC0] = lambda _args: PLAYER
    slots = iter((first, second))
    r.handlers["calls", 0x1417326E0] = lambda _args: next(slots)

    def relation(args: tuple[int, ...]) -> int | None:
        assert args == (0x2222,)
        return (1 << 40) | 4

    r.handlers["calls", 0x140E4FC90] = relation
    r.submit()
    assert len([1 for _ch, t, _a in r.calls if t == 0x1417326E0]) == 2
    assert r.mem.read(DISPATCHER + 0x2620, 1) == 1
    assert r.mem.read(DISPATCHER + 0x2618, 8) == 1
    assert not any(t == 0x140E4FD00 for _ch, t, _a in r.calls)


def test_pending_growth_uses_actual_live_clone_and_cleanup() -> None:
    r = Rig()
    r.mem.write(DISPATCHER + 0x26B8, 1, 1)
    destination = r.mem.allocate(32)
    r.mem.fill(destination, 0xA5, 32)
    r.mem.write(DISPATCHER + 0x26A8, 8, destination)
    r.mem.write(DISPATCHER + 0x26B0, 8, destination)
    captured: list[tuple[int, ...]] = []

    def grow(args: tuple[int, ...]) -> int | None:
        captured.append(args)
        assert args == (DISPATCHER + 0x26A0, destination, r.frame(0x1C0) + 0x170)
        r.mem.move(destination, args[2], 28)
        r.mem.fill(args[2], 0, 24)
        r.mem.write(DISPATCHER + 0x26A8, 8, destination + 32)
        return None

    r.handlers["calls", 0x140DF77F0] = grow
    r.submit()
    assert len(captured) == 1
    assert r.mem.read(DISPATCHER + 0x26A8, 8) == destination + 32
    assert r.mem.read_bytes(destination + 28, 4) == b"\xa5" * 4


def test_service_captures_vptr_before_data_but_reads_slot_after_data() -> None:
    r = Rig()
    r.mem.write(TIME + 8, 4, 2)
    new_vptr = r.mem.allocate(0x100)
    r.mem.fill(new_vptr, 0, 0x100)
    r.mem.write(new_vptr + 0xE8, 8, 0xBAD)
    observed: list[tuple[int, ...]] = []

    def service(args: tuple[int, ...]) -> int | None:
        r.mem.fill(args[1], 0, 0x30)
        r.mem.write(args[2] + 0x10, 8, 0x100000005)
        r.mem.write(args[2] + 0x18, 4, 9)
        return None

    def data_read(address: int, width: int, _value: int) -> None:
        if r.live and address == r.frame(0x1C0) + 0x180 and width == 8:
            r.mem.write(RECEIVER, 8, new_vptr)
            r.mem.write(RECEIVER + 0x10E8, 8, 0xFE00E9)

    def sent(args: tuple[int, ...]) -> int | None:
        observed.append(args)
        raise StopHere("after actual current slot selection")

    r.handlers["virtual", VSERVICE] = service
    r.handlers["virtual", 0xFE00E9] = sent
    r.read_hook = data_read
    with pytest.raises(StopHere):
        r.submit()
    assert observed == [(RECEIVER, 0x100000005, 4)]


def test_control_destroy_can_replace_weak_virtual_table() -> None:
    r = Rig()
    r.mem.write(TIME + 8, 4, 2)
    r.mem.write(CONTROL + 8, 4, 1)
    r.mem.write(CONTROL + 12, 4, 1)
    next_table = r.mem.allocate(16)
    r.mem.fill(next_table, 0, 16)
    r.mem.write(next_table + 8, 8, 0xFE0002)
    disposed: list[int] = []

    def service(args: tuple[int, ...]) -> int | None:
        r.mem.fill(args[1], 0, 0x30)
        r.mem.write(args[1] + 0x20, 8, CONTROL)
        return None

    def destroy(args: tuple[int, ...]) -> int | None:
        assert args == (CONTROL,)
        r.mem.write(CONTROL, 8, next_table)
        return None

    def weak(args: tuple[int, ...]) -> int | None:
        disposed.append(args[0])
        return None

    r.handlers["virtual", VSERVICE] = service
    r.handlers["virtual", VDESTROY] = destroy
    r.handlers["virtual", 0xFE0002] = weak
    r.submit()
    assert disposed == [CONTROL]
    assert not any(ch == "virtual" and t == VWEAK for ch, t, _a in r.calls)


@pytest.mark.parametrize("bad", [None, True, -1, 1 << 64])
def test_log_predicate_domain_refuses_before_mapping(bad: int | None) -> None:
    r = Rig()
    r.mem.write(0x1443559B0, 8, 1)
    r.handlers["calls", 0x1410221D0] = lambda _args: bad
    with pytest.raises(ValueError):
        r.run(LOG, MANAGER, 1, 0, 0, FIFTH)
    assert r.snapshots == []


def test_local_binding_cannot_suppress_real_child_refusal() -> None:
    r = Rig()

    @contextmanager
    def swallowing_binding(view: memoryview) -> Iterator[int]:
        with r.mem.bind_local(view) as address, suppress(StopHere):
            yield address

    bound = bind_replay_manager_queues(
        r.storage,
        ReplayTaskRebuildCalls(r.ordinary),
        imports=r.imports,
        writer_home_calls=ReplayTaskRebuildCalls(r.writer),
        flag_calls=ReplayTaskRebuildCalls(r.flag),
        virtual_calls=ReplayTaskRebuildCalls(r.virtual),
        logger_home_calls=ReplayTaskRebuildCalls(r.logger),
        error_home_calls=ReplayTaskRebuildCalls(r.error),
        atomics=r.atomics,
        bind_local=swallowing_binding,
        profile=r.profile,
    )
    r.handlers["calls", 0x141603FC0] = refuse
    assert bound.call is not None
    with pytest.raises(StopHere):
        bound.call(DISPATCH, (DISPATCHER, 0, 0, INDEX, FIFTH), None)
    assert any(k == "w" and width == 4 and value == 0 for k, _a, width, value in r.events)
    assert r.mem.read(DISPATCHER + 0x400, 4) == 0
