"""Cycle caller controls from the retained originals, over owned offline memory.

Unknown services are explicit authored capabilities. These controls do not
execute native instructions, restore a recording or establish game parity.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import fields, replace
from typing import cast

import pytest

from vantage.replay_command_batch import (
    ReplayCommandBatchProfile,
    bind_replay_command_batch,
)
from vantage.replay_command_reader import (
    ReplayCommandReaderProfile,
    bind_replay_command_reader,
)
from vantage.replay_cycle_services import (
    ReplayCycleServicesProfile,
    bind_replay_cycle_services,
)
from vantage.replay_cycle_tree import bind_replay_cycle_tree
from vantage.replay_cycle_tuning import (
    ReplayCycleTuningProfile,
    bind_replay_cycle_tuning,
)
from vantage.replay_memory import ReplayMemory, ReplayMemoryError
from vantage.replay_saved_result import bind_replay_saved_result
from vantage.replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
)
from vantage.replay_unit_ai_map import ReplayUnitAIMapAtomics
from vantage.replay_world_cycle import (
    ReplayWorldCycleProfile,
    bind_replay_world_cycle,
)

MAIN, MESSAGE, PEEK, CONSUME = 0x140E0E530, 0x140E50B80, 0x140E63600, 0x140E63610
STEP, COPY, COMMIT, READY = 0x140E63920, 0x140E66530, 0x140E68CF0, 0x140E68FC0
STATS, ELIGIBLE, ELAPSED, MODE = 0x140E159E0, 0x140E157D0, 0x140F3E8F0, 0x140E03790
ROW_A, ROW_B, CLOCK, HOST = 0x140E50540, 0x140E506E0, 0x140E68F80, 0x140A71140
LOCK, UNLOCK, THROW, ASSERT = 0x142D6AA5B, 0x142D6AA61, 0x142D6AA67, 0x142D6AA55
SETTINGS, FIRST, SECOND, LOGGER = 0x1442DA8A0, 0x1431F7470, 0x143266E00, 0x144355068
ROWS, LOG, VREADY, VDIAG, VSERIAL, VSEND, VID = (
    0x1442DE068,
    0x14101ADB0,
    0xFF01D0,
    0xFF0100,
    0xFF0018,
    0xFF00E8,
    0xFF0038,
)
U32, U64 = (1 << 32) - 1, (1 << 64) - 1
Handler = Callable[[tuple[int, ...]], int | None]


class Rig:
    def __init__(self) -> None:
        self.mem = ReplayMemory()
        self.events: list[tuple[str, int, int, int]] = []
        self.calls: list[tuple[str, int, tuple[int, ...]]] = []
        self.handlers: dict[tuple[str, int], Handler] = {}
        self.live: list[tuple[int, int]] = []
        self.snapshots: list[tuple[int, bytes]] = []
        self.after_read: Callable[[int, int, int], None] | None = None
        self.after_write: Callable[[int, int, int], None] | None = None
        self.manager = self.alloc(0x1000)
        self.queue, self.clock = self.alloc(0x500), self.alloc(0x200)
        self.timer, self.descriptor = self.alloc(0x2B0), self.alloc(0x400)
        self.settings, self.stats = self.alloc(0x400), self.alloc(0x50)
        self.header, self.node = self.alloc(0x28), self.alloc(0x28)
        self.receiver, self.vtable, self.service = self.alloc(8), self.alloc(0x200), self.alloc(8)
        self.payload, self.bus, self.output = self.alloc(32), self.alloc(0x900), self.alloc(0x50)
        self.row = ROWS
        for address, size in (
            (FIRST, 16),
            (SECOND, 16),
            (SETTINGS, 8),
            (0x144355050, 0x970),
            (0x1442846F0, 8),
            (0x1442C3F98, 8),
            (0x1442C40F0, 4),
            (0x144415600, 8),
            (ROWS, 8 * 0x30),
        ):
            self.mem.map_bytes(address, bytes(size))
        for address, width, value in (
            (
                FIRST,
                16,
                int.from_bytes(bytes.fromhex("0300000006000000080000000a000000"), "little"),
            ),
            (
                SECOND,
                16,
                int.from_bytes(bytes.fromhex("04000000050000000600000007000000"), "little"),
            ),
            (SETTINGS, 8, self.settings),
            (LOGGER, 8, 0xABC000),
            (self.manager + 0x318, 4, 8),
            (self.manager + 0x358, 8, self.clock),
            (self.manager + 0x388, 8, self.queue),
            (self.manager + 0x390, 8, self.queue),
            (self.manager + 0x398, 8, self.descriptor),
            (self.manager + 0x2E8, 8, self.receiver),
            (self.settings + 0x2E8, 8, self.receiver),
            (self.settings + 0x390, 8, self.queue),
            (self.clock + 8, 4, 1),
            (self.clock + 0x18, 4, 80),
            (self.clock + 0x30, 4, 8),
            (self.clock + 0x54, 4, 88),
            (self.clock + 0x60, 8, self.header),
            (self.header + 8, 8, self.header),
            (self.header + 0x19, 1, 1),
            (self.queue + 0x100, 8, self.timer),
            (self.queue + 0x3D0, 8, self.descriptor),
            (self.queue + 0x3F0, 4, 16),
            (self.timer + 0x2A4, 4, 90),
            (self.receiver, 8, self.vtable),
            (self.service, 8, self.vtable),
            (self.vtable + 0x1D0, 8, VREADY),
            (self.vtable + 0x100, 8, VDIAG),
            (self.vtable + 0x18, 8, VSERIAL),
            (self.vtable + 0xE8, 8, VSEND),
            (self.vtable + 0x38, 8, VID),
        ):
            self.mem.write(address, width, value)
        for i in range(8):
            self.mem.write(ROWS + i * 0x30, 4, 9)
            self.mem.write(ROWS + i * 0x30 + 0x20, 8, i)
            self.mem.write(self.clock + 0x138 + i * 4, 4, 9)
        for i in range(5):
            self.mem.write(self.stats + i * 4, 4, 0x10203040 + i)
        self.context = ReplayTaskRebuildStorage(self.manager, self.read, self.write)
        self.ordinary_calls = ReplayTaskRebuildCalls(self.ordinary)
        self.atomics = ReplayUnitAIMapAtomics(self.mem.compare_exchange_u32, self.mem.fetch_add_u32)
        self.profile = ReplayWorldCycleProfile(
            *(
                bytes([0xA1 + i]) * size
                for i, size in enumerate((0xF8, 0xD8, 0x30, 0x44, 0x14, 0x38, 0x40))
            )
        )
        self.reader = bind_replay_command_reader(
            self.context,
            self.ordinary_calls,
            imports=self.ordinary_calls,
            logger_home_calls=self.ordinary_calls,
            atomics=self.atomics,
            bind_local=self.local,
            profile=ReplayCommandReaderProfile(bytes(0x58), bytes(0x50), bytes(0x90)),
        )
        self.batch = bind_replay_command_batch(
            self.context,
            self.ordinary_calls,
            watson_home_calls=ReplayTaskRebuildCalls(None),
            error_home_calls=ReplayTaskRebuildCalls(None),
            atomics=self.atomics,
            bind_local=self.local,
            mxcsr=0x1F80,
            profile=ReplayCommandBatchProfile(bytes(0x28), bytes(0x28), bytes(0x50), bytes(0xB0)),
        )
        self.results = bind_replay_saved_result(
            self.context, self.ordinary_calls, atomics=self.atomics
        )
        self.memory_runtime = self.mem.runtime_calls(self.ordinary_calls)
        self.bound = self.bind()

    def alloc(self, size: int) -> int:
        address = self.mem.allocate(size)
        self.mem.fill(address, 0, size)
        return address

    def read(self, address: int, width: int) -> int:
        value = self.mem.read(address, width)
        self.events.append(("r", address, width, value))
        if self.after_read:
            self.after_read(address, width, value)
        return value

    def write(self, address: int, width: int, value: int) -> None:
        self.mem.write(address, width, value)
        self.events.append(("w", address, width, value))
        if self.after_write:
            self.after_write(address, width, value)

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

    def bind(self, **overrides: ReplayTaskRebuildCalls) -> ReplayTaskRebuildCalls:
        channels = {
            name: ReplayTaskRebuildCalls(self.channel(name))
            for name in ("virtual_calls", "logger_home_calls", "error_home_calls", "runtime_calls")
        }
        channels.update(overrides)
        return bind_replay_world_cycle(
            self.context,
            self.ordinary_calls,
            **channels,
            atomics=self.atomics,
            bind_local=self.local,
            profile=self.profile,
        )

    def record(self, channel: str, target: int, args: tuple[int, ...]) -> Handler | None:
        self.calls.append((channel, target, args))
        self.events.append(("call", target, 0, len(self.calls)))
        return self.handlers.get((channel, target))

    def channel(self, name: str) -> Callable[[int, tuple[int, ...], memoryview | None], int | None]:
        def call(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
            assert data is None
            handler = self.record(name, target, args)
            if handler:
                return handler(args)
            if name == "runtime_calls" and target in (LOCK, UNLOCK, THROW, ASSERT):
                return 0 if target == LOCK else None
            if name == "logger_home_calls" and target == LOG:
                return None
            if name == "virtual_calls":
                if target in (VREADY, VDIAG, VSEND):
                    return 0 if target == VREADY else None
                if target == VID:
                    return 0xCAFEBABE12345678
                if target == VSERIAL:
                    self.serialize(args[1], args[2])
                    return None
            if name == "error_home_calls" and target == 0x140A08840:
                self.mem.fill(args[0], 0, 0x28)
                return None
            raise UnresolvedReplayTaskRebuild(f"unprovided authored {name} service{target:x}")

        return call

    def ordinary(self, target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        assert data is None
        handler = self.record("calls", target, args)
        if handler:
            return handler(args)
        if target == CLOCK:
            assert self.reader.call is not None
            return self.reader.call(target, args, data)
        for entries, owner in (
            ((0x14096B890, 0x1402A8630), self.batch),
            ((0x1402BD7F0,), self.results),
            ((0x142D6BAB4,), self.memory_runtime),
        ):
            if target in entries:
                assert owner.call is not None
                return owner.call(target, args, data)
        if target == HOST:
            return 100
        if target == 0x140E65420:
            assert args[0] == self.queue
            self.mem.write(args[1], 8, self.stats)
            return None
        if target in (0x140E158C0, 0x140E15A50):
            self.mem.write(args[1], 8, int(target == 0x140E15A50))
            return args[1]
        if target in (
            0x140E053D0,
            0x140E05160,
            0x140E169D0,
            0x140E16E00,
            0x140E051E0,
            0x140E50470,
            0x140E504E0,
            0x140E50390,
            0x140E50300,
            0x140E67F40,
        ):
            return 0
        if target == 0x140E469E0:
            return 1
        if target == 0x140A69450:
            return self.bus
        if target == 0x14098F250:
            return 0xABC000
        if target == 0x140942110:
            return self.service
        if target == 0x142D6E3ED:
            return 0xF00D1234
        if target in (
            0x140E64030,
            0x140E64150,
            0x140E63BD0,
            0x140E66FF0,
            0x140E67A10,
            0x140E67FC0,
            0x140E0CA00,
            0x140A70000,
            0x140E090A0,
            0x140E63280,
            0x140E08110,
            0x140E03BE0,
            0x140DFC910,
            0x1410231D0,
            0x1410224A0,
        ):
            return None
        if target == 0x141021E00:
            return 0xD1A60000
        if target == 0x1410221D0:
            return 1
        raise UnresolvedReplayTaskRebuild(f"unprovided authored child{target:x}")

    def serialize(self, result: int, descriptor: int) -> None:
        self.mem.fill(result, 0, 0x28)
        self.mem.write(descriptor + 0x10, 8, self.payload)
        self.mem.write(descriptor + 0x18, 8, self.payload + 5)
        self.mem.write(descriptor + 0x20, 8, self.payload + 32)

    def run(self, target: int, *args: int) -> int | None:
        assert self.bound.call is not None
        return self.bound.call(target, args, None)

    def called(self, target: int, channel: str = "calls") -> list[tuple[int, ...]]:
        return [args for ch, t, args in self.calls if ch == channel and t == target]

    def tree(self, key: int = 9, value: int = 0) -> None:
        for at, width, word in (
            (self.header + 8, 8, self.node),
            (self.node, 8, self.header),
            (self.node + 0x10, 8, self.header),
            (self.node + 0x1C, 4, key),
            (self.node + 0x20, 4, value),
        ):
            self.mem.write(at, width, word)

    def pending(self, count: int = 1, credits: int = 1, step: int = 16) -> None:
        for at, value in ((0x3E8, count), (0x3E4, credits), (0x3F0, step)):
            self.mem.write(self.queue + at, 4, value)


@pytest.mark.parametrize("field", [f.name for f in fields(ReplayWorldCycleProfile)])
def test_profiles_require_exact_explicit_immutable_prefixes(field: str) -> None:
    r = Rig()
    for bad in (b"", bytearray(getattr(r.profile, field))):
        with pytest.raises(ValueError, match="explicit"):
            replace(r.profile, **{field: bad})


@pytest.mark.parametrize(
    ("target", "arity"),
    [
        (MAIN, 1),
        (MESSAGE, 3),
        (PEEK, 1),
        (CONSUME, 2),
        (STEP, 1),
        (COPY, 2),
        (COMMIT, 1),
        (READY, 1),
        (STATS, 2),
        (ELIGIBLE, 1),
        (ELAPSED, 1),
        (MODE, 1),
        (ROW_A, 1),
        (ROW_B, 1),
    ],
)
def test_addressed_call_contract_rejects_bad_arity_payload_and_scalars(
    target: int,
    arity: int,
) -> None:
    r = Rig()
    assert r.bound.call is not None
    for args, payload in (
        ((0,) * (arity + 1), None),
        ((0,) * arity, memoryview(b"x")),
        ((-1,) + (0,) * (arity - 1), None),
    ):
        with pytest.raises(ValueError):
            r.bound.call(target, args, payload)
    assert not r.events and not r.calls


def test_unknown_delegation_preserves_argument_payload_and_result_identity() -> None:
    r = Rig()
    args, payload, result = (1, 2), memoryview(b"opaque"), 123456789012345

    def delegate(target: int, received: tuple[int, ...], data: memoryview | None) -> int:
        assert target == 42 and received is args and data is payload
        return result

    bound = bind_replay_world_cycle(
        r.context,
        ReplayTaskRebuildCalls(delegate),
        virtual_calls=ReplayTaskRebuildCalls(None),
        logger_home_calls=ReplayTaskRebuildCalls(None),
        error_home_calls=ReplayTaskRebuildCalls(None),
        runtime_calls=ReplayTaskRebuildCalls(None),
        atomics=r.atomics,
        bind_local=r.local,
        profile=r.profile,
    )
    assert bound.call is not None and bound.call(42, args, payload) is result


def test_elapsed_wraps_and_holds_start_before_host_mutation() -> None:
    r = Rig()
    r.mem.write(r.timer + 0x2A4, 4, U32 - 2)

    def host(args: tuple[int, ...]) -> int:
        r.mem.write(r.timer + 0x2A4, 4, 0)
        return (17 << 32) | 4

    r.handlers["calls", HOST] = host
    assert r.run(ELAPSED, r.timer) == 7
    assert not r.live and not r.snapshots


def test_packet_copy_reads_fifth_word_after_overlapping_simd_store() -> None:
    r = Rig()
    source = r.output + 0x20
    for i in range(5):
        r.mem.write(source + i * 4, 4, i + 1)
    assert r.run(COPY, r.output, source) is None
    assert [r.mem.read(r.output + 0x2C + i * 4, 4) for i in range(5)] == [1, 2, 3, 4, 2]
    assert [event[:3] for event in r.events] == [
        ("r", source, 16),
        ("w", r.output + 0x2C, 16),
        ("r", source + 0x10, 4),
        ("w", r.output + 0x3C, 4),
    ]


def test_stats_getter_passes_original_output_and_tail_result_unchanged() -> None:
    r = Rig()
    result = 0x8877665544332211
    r.handlers["calls", 0x140E65420] = lambda args: result
    assert r.run(STATS, r.settings, r.output) is result
    assert r.called(0x140E65420) == [(r.queue, r.output)]


@pytest.mark.parametrize(
    ("mode", "tick", "expected"),
    [(0, 99, 0), (3, 0, 1), (10, 0, 1), (6, 5, 0), (6, 6, 1), (8, 6, 1), (8, 0xFFFFFFFF, 1)],
)
def test_eligible_distinguishes_uncapped_and_unsigned_clock_modes(
    mode: int,
    tick: int,
    expected: int,
) -> None:
    r = Rig()
    r.mem.write(r.manager + 0x318, 4, mode)
    r.mem.write(r.clock + 0x30, 4, tick)
    assert r.run(ELIGIBLE, r.manager) == expected
    assert r.events[0][:3] == ("r", FIRST, 16)
    assert bool(r.called(CLOCK)) == (mode in (6, 8))


def test_mode_and_eligible_read_current_local_cells_and_stop_at_match() -> None:
    r = Rig()
    r.mem.write(r.manager + 0x318, 4, 22)

    def mutate(address: int, width: int, value: int) -> None:
        if r.live and address == r.frame(0x14) and width == 4:
            r.mem.write(address + 4, 4, 22)

    r.after_read = mutate
    assert r.run(MODE, r.manager) == 1
    frame = next(address for kind, address, width, _ in r.events if kind == "w" and width == 16)
    assert [
        a for kind, a, w, _ in r.events if kind == "r" and frame <= a < frame + 0x14 and w == 4
    ] == [frame, frame + 4]
    assert r.events[0][:3] == ("r", r.manager + 0x318, 4)


@pytest.mark.parametrize(
    ("key", "pending", "expected"),
    [(8, 3, 1), (9, 0, 1), (9, 1, 0), (10, 3, 1), (0xFFFFFFFF, 3, 1)],
)
def test_ready_lower_bound_and_pending_values(key: int, pending: int, expected: int) -> None:
    r = Rig()
    r.tree(key, pending)
    assert r.run(READY, r.clock) == expected
    assert r.called(LOCK, "runtime_calls") == [(r.clock + 0x70,)]
    assert r.called(UNLOCK, "runtime_calls") == [(r.clock + 0x70,)]
    assert not r.snapshots


def test_ready_below_threshold_short_circuits_and_cycle_wrap_uses_zero() -> None:
    r = Rig()
    r.mem.write(r.clock + 0x54, 4, 8)
    assert r.run(READY, r.clock) == 0
    assert not r.calls
    r.mem.write(r.clock + 0x30, 4, U32)
    r.mem.write(r.clock + 0x54, 4, 0)
    assert r.run(READY, r.clock) == 1


def test_ready_holds_next_root_initial_nil_and_result_across_callbacks() -> None:
    r = Rig()
    r.tree(9, 0)
    key_reads = 0

    def mutate(address: int, width: int, value: int) -> None:
        nonlocal key_reads
        if address == r.node + 0x1C:
            key_reads += 1
            if key_reads == 2:
                r.mem.write(r.header + 8, 8, 0xBAD)
                r.mem.write(r.node + 0x19, 1, 1)

    def lock(args: tuple[int, ...]) -> int:
        r.mem.write(r.clock + 0x30, 4, 99)
        return 0

    def unlock(args: tuple[int, ...]) -> None:
        r.mem.write(r.node + 0x20, 4, 1)

    r.after_read = mutate
    r.handlers["runtime_calls", LOCK] = lock
    r.handlers["runtime_calls", UNLOCK] = unlock
    # Root nil is sampled once; the second walk still visits the held root.
    # Its candidate nil is fresh, so this mutation reaches the source assertion.
    with pytest.raises(UnresolvedReplayTaskRebuild, match="140e690c3"):
        r.run(READY, r.clock)
    assert key_reads == 3
    assert r.called(ASSERT, "runtime_calls") == [(0x1436802B0,)]
    assert r.called(THROW, "runtime_calls") == [(5,)]
    assert not r.called(UNLOCK, "runtime_calls")


def test_ready_result_is_held_across_unlock_and_two_walks_reread_keys() -> None:
    r = Rig()
    r.tree(9, 0)
    r.handlers["runtime_calls", UNLOCK] = lambda args: r.mem.write(r.node + 0x20, 4, 1)
    assert r.run(READY, r.clock) == 1
    assert sum(a == r.node + 0x1C for kind, a, _, _ in r.events if kind == "r") == 4


@pytest.mark.parametrize(
    ("target", "field", "bad", "overflow"),
    [(READY, 0x70, 0x140E690C3, 0x140E690D5), (COMMIT, 0xC0, 0x140E68E3E, 0x140E68E33)],
)
@pytest.mark.parametrize("guard", ["lock", "overflow"])
def test_mutex_returning_errors_stop_at_literal_traps_after_source_prefix(
    target: int,
    field: int,
    bad: int,
    overflow: int,
    guard: str,
) -> None:
    r = Rig()
    if target == COMMIT:
        r.mem.write(r.clock + 0x130, 8, 1)
    if guard == "lock":
        r.handlers["runtime_calls", LOCK] = lambda args: 0x100000001
    else:
        r.mem.write(r.clock + field + 0x4C, 4, 0x7FFFFFFF)
    trap = bad if guard == "lock" else overflow
    with pytest.raises(UnresolvedReplayTaskRebuild, match=f"{trap:x}"):
        r.run(target, r.clock)
    assert r.called(THROW, "runtime_calls") == [(5 if guard == "lock" else 6,)]
    if guard == "overflow":
        assert r.mem.read(r.clock + field + 0x4C, 4) == 0x7FFFFFFE
    if target == COMMIT:
        assert r.mem.read(r.clock + 0x30, 4) == 9
        assert r.mem.read(r.clock + 0x48, 4) == 0x10203044
    assert not r.called(UNLOCK, "runtime_calls")


def test_commit_wraps_and_copies_aliasing_stats_with_late_fifth_word() -> None:
    r = Rig()
    r.mem.write(r.clock + 0x30, 4, U32)
    r.mem.write(r.clock + 0x54, 4, U32)
    source = r.clock + 0x2C
    for i in range(5):
        r.mem.write(source + i * 4, 4, 0x90 + i)
    # Keep cycle wrap independent of the overlapping packet fixture.
    r.mem.write(r.clock + 0x30, 4, U32)
    r.handlers["calls", 0x140E65420] = lambda args: r.mem.write(args[1], 8, source)
    assert r.run(COMMIT, r.clock) is None
    assert r.mem.read(r.clock + 0x30, 4) == 0
    assert r.mem.read(r.clock + 0x28, 8) == U32
    assert r.mem.read(r.clock + 0x20, 4) == 80
    assert r.mem.read(r.clock + 0x48, 4) == 0
    assert not r.called(LOCK, "runtime_calls")
    assert r.snapshots[0][0] == 0x30


@pytest.mark.parametrize(("count", "expected_head"), [(1, 0), (2, 8), (0, 8)])
def test_commit_deque_bucket_index_held_head_current_count_and_unlock_order(
    count: int,
    expected_head: int,
) -> None:
    r = Rig()
    array, bucket = r.alloc(32), r.alloc(16)
    for at, value in ((0x118, array), (0x120, 4), (0x128, 7), (0x130, 1)):
        r.mem.write(r.clock + at, 8, value)
    r.mem.write(array + 8, 8, bucket)
    r.mem.write(bucket + 12, 4, U32 - 1)

    def lock(args: tuple[int, ...]) -> int:
        r.mem.write(r.clock + 0x130, 8, count)
        return 0

    def mutate(address: int, width: int, value: int) -> None:
        if address == bucket + 12:
            r.mem.write(r.clock + 0x128, 8, 100)

    r.handlers["runtime_calls", LOCK] = lock
    r.after_read = mutate
    assert r.run(COMMIT, r.clock) is None
    assert r.mem.read(r.clock + 0x130, 8) == ((count - 1) & U64)
    assert r.mem.read(r.clock + 0x128, 8) == expected_head
    assert r.called(0x140A70000) == [(r.bus + 0x818, 102)]
    order = [target for _, target, _ in r.calls]
    assert order.index(UNLOCK) < order.index(0x140A69450) < order.index(HOST)


def test_missing_mutex_refuses_after_cycle_stats_writes_without_default_success() -> None:
    r = Rig()
    r.mem.write(r.clock + 0x130, 8, 1)
    r.bound = r.bind(runtime_calls=ReplayTaskRebuildCalls(None))
    with pytest.raises(UnresolvedReplayTaskRebuild, match="142d6aa5b"):
        r.run(COMMIT, r.clock)
    assert r.mem.read(r.clock + 0x30, 4) == 9
    assert r.mem.read(r.clock + 0x48, 4) == 0x10203044
    assert r.mem.read(r.clock + 0x130, 8) == 1
    assert not r.live


def test_empty_consume_clears_flag_before_gate_and_again_after_live_logger() -> None:
    r = Rig()
    r.mem.write(0x144355062, 1, 1)
    r.mem.write(r.queue + 0x4CC, 4, 99)

    def logger(args: tuple[int, ...]) -> None:
        assert args[:4] == (0xABC000, 0x2A, 0x14326A7C0, 0)
        assert r.mem.read(args[4], 8) == 0
        assert r.mem.read(r.queue + 0x4CC, 4) == 0
        r.mem.write(r.queue + 0x4CC, 4, 44)

    r.handlers["logger_home_calls", LOG] = logger
    assert r.run(CONSUME, r.queue, 7) == 0
    assert r.mem.read(r.queue + 0x4CC, 4) == 0
    assert r.events[0] == ("w", r.queue + 0x4CC, 4, 0)
    assert not r.called(HOST)
    assert r.snapshots[0][0] == 0xD8


@pytest.mark.parametrize(
    ("credits", "pending", "step", "extra", "expected"),
    [
        (1, 1, 16, 0, 16),
        (0, 1, 16, 0, 16),
        (3, 1, 16, 0, 0),
        (3, 1, 16, 22, 16),
        (0x80000001, 1, 2, 0, 2),
        (2, 1, 0xFFFFFFFF, 0xFFFFFFFE, 0),
    ],
)
def test_consume_unsigned_budget_product_and_elapsed_wrap(
    credits: int,
    pending: int,
    step: int,
    extra: int,
    expected: int,
) -> None:
    r = Rig()
    r.pending(pending, credits, step)
    r.mem.write(r.queue + 0x3F4, 4, extra)
    assert r.run(CONSUME, r.queue, 7) == expected
    success = expected != 0
    assert r.mem.read(r.queue + 0x4CC, 4) == int(success)
    assert r.mem.read(r.queue + 0x3E8, 4) == (pending - int(success))
    assert r.mem.read(r.queue + 0x4BC, 4) == ((credits - min(credits, pending)) * step & U32)


def test_consume_uses_current_descriptor_before_publishing_held_timer() -> None:
    r = Rig()
    r.pending(1, 1)
    r.mem.write(r.descriptor + 0x318, 4, 8)
    r.mem.write(r.queue + 0x4B0, 4, U32)

    def mutate(address: int, width: int, value: int) -> None:
        if address == r.queue + 0x3D0:
            assert r.mem.read(r.queue + 0x4B8, 4) == 0
            r.mem.write(r.queue + 0x3E8, 4, 2)
        if address == r.queue + 0x3F0:
            r.mem.write(r.queue + 0x4B8, 4, 999)

    r.after_read = mutate
    assert r.run(CONSUME, r.queue, 7) == 16
    assert r.mem.read(r.queue + 0x4B0, 4) == 1
    assert r.mem.read(r.queue + 0x4B8, 4) == 999
    assert r.mem.read(r.queue + 0x3E8, 4) == 1


def test_consume_held_timer_precedes_step_read_and_can_still_reject() -> None:
    r = Rig()
    r.pending(1, 2)

    def mutate(address: int, width: int, value: int) -> None:
        if address == r.queue + 0x3F0:
            r.mem.write(r.queue + 0x4B8, 4, 1000)

    r.after_read = mutate
    assert r.run(CONSUME, r.queue, 7) == 0
    assert r.mem.read(r.queue + 0x4B8, 4) == 1000
    assert r.mem.read(r.queue + 0x3E8, 4) == 1


@pytest.mark.parametrize("now", [6, 7, 0xFFFFFFFF, 0x100000006])
def test_rejected_consume_counters_obey_low32_unsigned_now(now: int) -> None:
    r = Rig()
    r.pending(1, 4)
    r.mem.write(r.queue + 0x4C0, 4, U32)
    r.mem.write(r.queue + 0x4C4, 4, 5)
    assert r.run(CONSUME, r.queue, now) == 0
    increment = int((now & U32) > 6)
    assert r.mem.read(r.queue + 0x4C0, 4) == ((U32 + increment) & U32)
    assert r.mem.read(r.queue + 0x4C4, 4) == 5 + increment
    stores = [address for kind, address, _, _ in r.events if kind == "w"]
    if increment:
        assert stores.index(r.queue + 0x4C0) < stores.index(r.queue + 0x4C4)


def test_consume_override_decrements_current_pending_and_returns_held_current_step() -> None:
    r = Rig()
    r.pending(1, 4)

    def override(args: tuple[int, ...]) -> int:
        r.mem.write(r.queue + 0x3E8, 4, 0)
        r.mem.write(r.queue + 0x3F0, 4, 23)
        return 0xAABBCC01

    def mutate(address: int, width: int, value: int) -> None:
        if address == r.queue + 0x4CC and value == 1:
            r.mem.write(r.queue + 0x3F0, 4, 99)

    r.handlers["calls", 0x140E05160] = override
    r.after_write = mutate
    assert r.run(CONSUME, r.queue, 7) == 23
    assert r.mem.read(r.queue + 0x3E8, 4) == U32
    assert r.mem.read(r.queue + 0x3F0, 4) == 99


def test_consume_failure_logger_has_seven_live_typed_records_and_source_store_order() -> None:
    r = Rig()
    r.pending(1, 3)
    r.mem.write(r.queue + 0x3F4, 4, 3)
    r.mem.write(0x144355062, 1, 1)

    def logger(args: tuple[int, ...]) -> None:
        assert args[:4] == (0xABC000, 0x2A, 0x14326A810, 7)
        vector = r.mem.read(args[4], 8)
        data = [r.mem.read(vector + i * 8, 8) for i in range(7)]
        assert [r.mem.read(address, 4) for address in data] == [3, 10, 13, 32, 1, 1, 7]
        assert [r.mem.read(address + 8, 4) for address in data] == [7, 8, 8, 8, 7, 7, 8]
        frame = r.frame(0xD8)
        stores = [
            (at - frame, width)
            for kind, at, width, _ in r.events
            if kind == "w" and frame <= at < frame + 0xD8
        ]
        assert stores == [
            (0x80, 4),
            (0x70, 4),
            (0x60, 4),
            (0x50, 4),
            *((offset, 8) for offset in range(0xA0, 0xD8, 8)),
            (0x40, 4),
            (0x30, 4),
            (0x20, 8),
            (0x98, 4),
            (0x90, 4),
            (0x88, 4),
            (0x78, 4),
            (0x68, 4),
            (0x58, 4),
            (0x48, 4),
            (0x38, 4),
        ]
        r.mem.write(r.queue + 0x4CC, 4, 100)

    r.handlers["logger_home_calls", LOG] = logger
    assert r.run(CONSUME, r.queue, 7) == 0
    assert r.mem.read(r.queue + 0x4CC, 4) == 0


@pytest.mark.parametrize(
    ("external", "cap", "initial", "expected"),
    [(0, 10, 16, 16), (7, 9, 16, 16), (7, 0xFFFFFFFF, 16, 0xFFFFFFFF)],
)
def test_step_cap_uses_unsigned_current_value_and_final_reload(
    external: int,
    cap: int,
    initial: int,
    expected: int,
) -> None:
    r = Rig()
    r.mem.write(r.descriptor + 0x318, 4, 3)
    r.mem.write(0x1442846F0, 8, external)
    r.mem.write(r.queue + 0x3F0, 4, initial)
    r.handlers["calls", 0x1409738C0] = lambda args: cap
    assert r.run(STEP, r.queue) == expected
    assert r.mem.read(r.queue + 0x4CC, 4) == 1
    assert bool(r.called(0x1409738C0)) == bool(external)


@pytest.mark.parametrize("bad", [None, -1, U64 + 1])
def test_consumed_scalar_refusal_preserves_earlier_step_flag(bad: int | None) -> None:
    r = Rig()
    r.mem.write(r.descriptor + 0x318, 4, 3)
    r.mem.write(0x1442846F0, 8, 7)
    r.handlers["calls", 0x1409738C0] = lambda args: bad
    with pytest.raises(ValueError):
        r.run(STEP, r.queue)
    assert r.mem.read(r.queue + 0x4CC, 4) == 1
    assert r.mem.read(r.queue + 0x3F0, 4) == 16


def test_row_roles_use_qword_identity_and_opposite_source_read_orders() -> None:
    r = Rig()
    slot = r.alloc(8)
    identity = 0x123400000001
    r.mem.write(slot, 8, identity)
    r.mem.write(r.row + 0x20, 8, identity)
    r.handlers["calls", 0x140E158C0] = lambda args: slot
    r.handlers["calls", 0x140E15A50] = lambda args: slot
    assert r.run(ROW_A, r.row) == 1
    first = [address for kind, address, _, _ in r.events if kind == "r"]
    assert first.index(slot) < first.index(r.row + 0x20)
    r.events.clear()
    assert r.run(ROW_B, r.row) == 1
    second = [address for kind, address, _, _ in r.events if kind == "r"]
    assert second.index(r.row + 0x20) < second.index(slot)
    r.mem.write(slot, 8, 1)
    assert r.run(ROW_A, r.row) == 0
    assert r.run(ROW_B, r.row) == 0


def test_row_b_gate_skips_mapping_and_uses_current_settings_after_predicate() -> None:
    r = Rig()
    r.handlers["calls", 0x140E053D0] = lambda args: 0xABCD01
    assert r.run(ROW_B, r.row) == 0
    assert not r.snapshots and not r.called(0x140E15A50)
    other = r.alloc(0x400)

    def predicate(args: tuple[int, ...]) -> int:
        r.mem.write(SETTINGS, 8, other)
        return 0

    r.handlers["calls", 0x140E053D0] = predicate
    assert r.run(ROW_B, r.row) == 0
    assert r.called(0x140E15A50)[0][0] == other


def test_message_consumes_only_dl_and_keeps_output_across_late_virtual_call() -> None:
    r = Rig()

    def map_role(args: tuple[int, ...]) -> int:
        assert r.mem.read(r.output, 1) == 0xBE
        assert r.mem.read(r.output + 8, 8) == U64
        r.mem.write(args[1], 8, 0)
        r.mem.write(r.row + 8, 8, r.receiver)
        return args[1]

    r.handlers["calls", 0x140E158C0] = map_role
    assert r.run(MESSAGE, r.output, 0xFEDCBA98765432BE, r.row) == r.output
    assert r.mem.read(r.output + 0x10, 1) == 1
    assert r.mem.read(r.output + 0x11, 1) == 0
    assert r.mem.read(r.output + 0x18, 8) == r.row
    assert r.mem.read(r.output + 8, 8) == 0xCAFEBABE12345678
    assert r.called(VID, "virtual_calls") == [(r.receiver,)]
    assert [size for size, _ in r.snapshots] == [0x38, 0x40]


def test_mode_rejection_needs_no_child_services_and_first_mode_is_held() -> None:
    r = Rig()
    r.mem.write(r.manager + 0x318, 4, 77)

    def mutate(address: int, width: int, value: int) -> None:
        if address == FIRST:
            r.mem.write(r.manager + 0x318, 4, 8)

    r.after_read = mutate
    assert r.run(MAIN, r.manager) == 0
    assert not r.calls
    assert r.events[0][:3] == ("r", r.manager + 0x318, 4)


@pytest.mark.parametrize(
    ("descriptor_flag", "screen_flag", "expected"), [(0, 7, U32), (1, 0, U32), (1, 1, 0)]
)
def test_uncapped_path_runs_real_commit_and_current_screen_gates(
    descriptor_flag: int,
    screen_flag: int,
    expected: int,
) -> None:
    r = Rig()
    screen = r.alloc(0xC50)
    r.mem.write(r.manager + 0x318, 4, 3)
    r.mem.write(r.manager + 0x380, 1, 1)
    r.mem.write(r.descriptor + 2, 1, descriptor_flag)
    r.mem.write(0x144415600, 8, screen)
    r.mem.write(screen + 0xC4C, 4, screen_flag)
    assert r.run(MAIN, r.manager) == expected
    assert r.mem.read(r.clock + 0x30, 4) == 9
    assert r.mem.read(r.manager + 0x380, 1) == 0
    assert r.called(0x140E66FF0) == [(r.queue,)]
    assert r.called(0x140E67A10) == [(r.queue,)]
    assert not r.called(HOST) and not r.called(LOCK, "runtime_calls")
    assert any(a == screen + 0xC4C for kind, a, _, _ in r.events if kind == "r") == bool(
        descriptor_flag
    )


@pytest.mark.parametrize("field", [0x3A0, 0x3A1])
def test_uncapped_blocked_flag_stops_before_queue_or_commit(field: int) -> None:
    r = Rig()
    r.mem.write(r.manager + 0x318, 4, 3)
    r.mem.write(r.manager + field, 1, 1)
    assert r.run(MAIN, r.manager) == 0
    assert not r.calls and r.mem.read(r.clock + 0x30, 4) == 8


def test_pending_fast_path_uses_actual_consume_and_live_logger_return_is_held() -> None:
    r = Rig()
    r.pending()
    r.mem.write(0x144355062, 1, 1)

    def logger(args: tuple[int, ...]) -> None:
        assert args[:4] == (0xABC000, 0x2A, 0x143265450, 2)
        vector = r.mem.read(args[4], 8)
        first, second = r.mem.read(vector, 8), r.mem.read(vector + 8, 8)
        assert (r.mem.read(first, 4), r.mem.read(second, 4)) == (16, 0)
        assert (r.mem.read(first + 8, 4), r.mem.read(second + 8, 4)) == (7, 7)
        r.mem.write(first, 4, 99)

    r.handlers["logger_home_calls", LOG] = logger
    assert r.run(MAIN, r.manager) == 16
    assert r.mem.read(r.queue + 0x3E8, 4) == 0
    assert r.mem.read(r.queue + 0x4CC, 4) == 1
    assert r.mem.read(r.clock + 0x30, 4) == 8
    assert not r.called(LOCK, "runtime_calls")


def test_normal_cycle_commits_actual_clock_ignores_empty_consume_and_wraps_ring20() -> None:
    r = Rig()
    r.mem.write(r.manager + 0x3FC, 4, 19)
    r.mem.write(r.manager + 0x408, 8, 0xAABBCCDD12345678)
    r.mem.write(r.manager + 0x410, 4, 55)
    assert r.run(MAIN, r.manager) == 16
    assert r.mem.read(r.clock + 0x30, 4) == 9
    assert r.mem.read(r.clock + 0x20, 4) == 80
    assert r.mem.read(r.manager + 0x404, 4) == 0x12345678
    assert r.mem.read(r.manager + 0x408, 8) == 0
    assert r.mem.read(r.manager + 0x410, 4) == 0
    assert r.mem.read(r.manager + 0x3FC, 4) == 0
    assert r.mem.read(r.manager + 0x414, 4) == 0
    assert r.mem.read(r.manager + 0x3A8, 4) == 100
    assert r.mem.read(r.queue + 0x4CC, 4) == 1
    assert len(r.called(0x140E504E0)) == 8


def test_ring_uses_distinct_current_indices_and_held_start_before_host() -> None:
    r = Rig()
    r.mem.write(r.manager + 0x3FC, 4, 3)
    r.mem.write(r.manager + 0x414, 4, U32 - 4)

    def mutate(address: int, width: int, value: int) -> None:
        if address == r.manager + 0x3AC + 3 * 4:
            r.mem.write(r.manager + 0x3FC, 4, 39)

    r.after_write = mutate
    assert r.run(MAIN, r.manager) == 16
    assert r.mem.read(r.manager + 0x3AC + 3 * 4, 4) == 105
    assert r.mem.read(r.manager + 0x3FC, 4) == 0


@pytest.mark.parametrize("field", [0x3A0, 0x3A1])
def test_admitted_blocked_return_retains_host_publication_and_skips_commit(field: int) -> None:
    r = Rig()
    r.mem.write(r.manager + field, 1, 1)
    assert r.run(MAIN, r.manager) == 0
    assert r.mem.read(r.manager + 0x3A8, 4) == 100
    assert r.mem.read(r.manager + 0x414, 4) == 100
    assert r.mem.read(r.clock + 0x30, 4) == 8
    assert not r.called(0x140E64030)


@pytest.mark.parametrize(
    ("elapsed", "cross", "virtual_calls"), [(5000, 1, 1), (5001, 1, 0), (0xFFFFFFFF, 0, 0)]
)
def test_not_ready_timeout_keeps_false_ready_and_obeys_cross_gate(
    elapsed: int,
    cross: int,
    virtual_calls: int,
) -> None:
    r = Rig()
    r.mem.write(r.clock + 0x54, 4, 8)
    r.mem.write(r.manager + 0x3A8, 4, (100 - elapsed) & U32)
    r.handlers["calls", 0x140E469E0] = lambda args: cross
    assert r.run(MAIN, r.manager) == 0
    assert len(r.called(VREADY, "virtual_calls")) == virtual_calls
    assert bool(r.called(0x140E64150)) == (elapsed > 5000 and not cross)
    assert r.called(0x140E64030) == [(r.queue,)]
    assert r.mem.read(r.clock + 0x30, 4) == 8


def test_virtual_ready_rechecks_current_clock_and_uses_low_al() -> None:
    r = Rig()
    r.mem.write(r.clock + 0x54, 4, 8)

    def resume(args: tuple[int, ...]) -> int:
        r.mem.write(r.clock + 0x54, 4, 20)
        return 0xAABBCC01

    r.handlers["virtual_calls", VREADY] = resume
    assert r.run(MAIN, r.manager) == 16
    assert r.mem.read(r.clock + 0x30, 4) == 9
    assert len(r.called(LOCK, "runtime_calls")) == 1


def test_pre_ready_cross_gate_reloads_queue_between_reject_and_clear() -> None:
    r = Rig()
    other = r.alloc(0x500)
    r.handlers["calls", 0x140E469E0] = lambda args: 0
    r.handlers["calls", 0x140E64150] = lambda args: r.mem.write(r.manager + 0x388, 8, other)
    assert r.run(MAIN, r.manager) == 0
    assert r.called(0x140E64150) == [(r.queue,)]
    assert r.called(0x140E64030) == [(other,)]
    assert r.mem.read(r.manager + 0x3A8, 4) == 0


def test_shutdown_gate_keeps_prefix_queue_callback_effects() -> None:
    r = Rig()
    other = r.alloc(0x500)
    r.mem.write(r.manager + 0x380, 1, 1)
    r.mem.write(0x1442C40F0, 4, 1)

    def callback(args: tuple[int, ...]) -> int:
        assert args == (r.queue, 8)
        r.mem.write(r.manager + 0x390, 8, other)
        return 1

    r.handlers["calls", 0x140E67F40] = callback
    assert r.run(MAIN, r.manager) == 0
    assert r.called(0x140E67FC0) == [(other, 8)]
    assert not r.called(LOCK, "runtime_calls")
    assert r.mem.read(r.manager + 0x414, 4) == 0


def test_metrics_use_two_registries_and_normal_diagnostic_virtual_then_metrics() -> None:
    r = Rig()
    r.mem.write(0x1443559B0, 8, 1)
    assert r.run(MAIN, r.manager) == 16
    assert r.called(0x1410221D0) == [(0xD1A60000, 15)]
    assert r.called(VDIAG, "virtual_calls") == [(r.receiver,)]
    assert r.called(0x1410231D0) == [(0xD1A60000, 2)]
    assert r.called(0x1410224A0) == [(0xD1A60000, 9)]
    assert len(r.called(0x141021E00)) == 3


def test_missing_logger_refuses_with_pending_consumed_and_homes_still_written() -> None:
    r = Rig()
    r.pending()
    r.mem.write(0x144355062, 1, 1)
    r.bound = r.bind(logger_home_calls=ReplayTaskRebuildCalls(None))
    with pytest.raises(UnresolvedReplayTaskRebuild, match="14101adb0"):
        r.run(MAIN, r.manager)
    assert r.mem.read(r.queue + 0x3E8, 4) == 0
    snapshot = next(raw for size, raw in r.snapshots if size == 0xF8)
    assert int.from_bytes(snapshot[0xA8:0xAC], "little") == 16
    assert int.from_bytes(snapshot[0x38:0x3C], "little") == 0
    assert not r.live


def test_all_eight_rows_obey_lazy_gates_and_emit_live_messages_then_cleanup() -> None:
    r = Rig()
    r.mem.write(0x14435505D, 1, 1)
    for i in (1, 3, 5):
        r.mem.write(r.clock + 0x138 + i * 4, 4, 0)
    for i in (1, 6):
        r.mem.write(ROWS + i * 0x30, 4, 77)
    r.handlers["calls", 0x140E504E0] = lambda args: int((args[0] - ROWS) // 0x30 != 2)
    r.handlers["calls", 0x140E50390] = lambda args: int((args[0] - ROWS) // 0x30 in (3, 4, 5))
    r.handlers["calls", 0x140E50300] = lambda args: int((args[0] - ROWS) // 0x30 == 3)
    emitted: list[tuple[int, int, int, int]] = []
    logs: list[tuple[int, int, int]] = []

    def logger(args: tuple[int, ...]) -> None:
        assert args[:4] == (0xABC000, 0x25, 0x1432654E0, 3)
        vector = r.mem.read(args[4], 8)
        pointers = [r.mem.read(vector + i * 8, 8) for i in range(3)]
        assert [r.mem.read(p + 8, 4) for p in pointers] == [7, 7, 15]
        logs.append(
            (r.mem.read(pointers[0], 4), r.mem.read(pointers[1], 4), r.mem.read(pointers[2], 8))
        )

    def emit(args: tuple[int, ...]) -> None:
        holder, message = args
        assert r.mem.read(holder, 8) == r.manager + 0xD0
        assert r.mem.read(holder + 8, 16) == 0 and r.mem.read(holder + 24, 8) == 0
        emitted.append(
            (
                r.mem.read(message + 0x18, 8),
                r.mem.read(message, 1),
                r.mem.read(message + 0x10, 1),
                r.mem.read(message + 0x11, 1),
            )
        )
        r.mem.write(holder + 8, 8, 0xCAFE)

    def cleanup(args: tuple[int, ...]) -> None:
        assert r.mem.read(args[0], 8) == 0xCAFE

    r.handlers["logger_home_calls", LOG] = logger
    r.handlers["calls", 0x140E03BE0] = emit
    r.handlers["calls", 0x140DFC910] = cleanup
    assert r.run(MAIN, r.manager) == 16
    assert emitted == [
        (ROWS, 2, 1, 0),
        (ROWS + 0x30, 0, 0, 1),
        (ROWS + 5 * 0x30, 0, 0, 0),
        (ROWS + 7 * 0x30, 2, 0, 0),
    ]
    assert logs == [
        (1, 9, 0x143265410),
        (2, 77, 0x143265408),
        (6, 9, 0x143265408),
        (8, 9, 0x143265410),
    ]
    assert len(r.called(0x140E504E0)) == 8
    assert len(r.called(0x140E50470)) == 3
    assert len(r.called(0x140E50300)) == 3
    assert len(r.called(0x140DFC910)) == 4


def test_rows_reload_current_clock_but_compare_values_with_held_tick() -> None:
    r = Rig()
    for i in range(8):
        r.mem.write(r.clock + 0x138 + i * 4, 4, U32)

    def eligible(args: tuple[int, ...]) -> int:
        r.mem.write(r.clock + 0x30, 4, 99)
        return 1

    r.handlers["calls", 0x140E504E0] = eligible
    assert r.run(MAIN, r.manager) == 16
    assert len(r.called(0x140E03BE0)) == 8
    assert not r.called(0x140E50470)


def test_zero_held_tick_still_checks_all_thresholds_but_skips_eligibility() -> None:
    r = Rig()
    r.mem.write(r.clock + 0x30, 4, U32)
    r.mem.write(r.clock + 0x54, 4, U32)
    assert r.run(MAIN, r.manager) == 16
    assert r.mem.read(r.clock + 0x30, 4) == 0
    assert not r.called(0x140E504E0)
    assert (
        sum(kind == "r" and r.clock + 0x138 <= at < r.clock + 0x158 for kind, at, _, _ in r.events)
        == 8
    )


@pytest.mark.parametrize(
    ("mode", "status", "changed", "expected_calls"),
    [(1, 1, 0, (1, 0, 0)), (2, 0, 0, (0, 1, 0)), (2, 1, 0, (0, 1, 1))],
)
def test_io_modes_zero_response_and_unchanged_clock_skip_send(
    mode: int,
    status: int,
    changed: int,
    expected_calls: tuple[int, int, int],
) -> None:
    r = Rig()
    r.mem.write(r.clock + 8, 4, mode)
    r.handlers["calls", 0x140E051E0] = lambda args: 1

    def read(args: tuple[int, ...]) -> int:
        r.mem.write(args[1], 4, 10)
        r.mem.write(args[2], 4, 20)
        r.mem.write(args[3], 4, changed)
        return status

    r.handlers["calls", 0x140E634C0] = read
    assert r.run(MAIN, r.manager) == 16
    assert (
        tuple(len(r.called(t)) for t in (0x140E63280, 0x140E634C0, 0x140E08110)) == expected_calls
    )
    assert not r.called(VSERIAL, "virtual_calls")
    if expected_calls[2]:
        assert r.called(0x140E08110) == [(r.manager, 20, 10)]


def test_io_reads_live_74_before_a8_at_final_callback() -> None:
    r = Rig()
    r.mem.write(r.clock + 8, 4, 2)
    r.handlers["calls", 0x140E051E0] = lambda args: 1

    def read(args: tuple[int, ...]) -> int:
        for address, value in zip(args[1:], (10, 20, 0), strict=True):
            r.mem.write(address, 4, value)
        return 1

    def mutate(address: int, width: int, value: int) -> None:
        if r.live and address == r.frame(0xF8) + 0x74:
            r.mem.write(r.frame(0xF8) + 0xA8, 4, 99)

    r.handlers["calls", 0x140E634C0] = read
    r.after_read = mutate
    assert r.run(MAIN, r.manager) == 16
    assert r.called(0x140E08110) == [(r.manager, 99, 10)]


def prepare_changed_io(r: Rig) -> None:
    r.mem.write(r.clock + 8, 4, 2)
    r.handlers["calls", 0x140E051E0] = lambda args: 1

    def read(args: tuple[int, ...]) -> int:
        for address, value in zip(args[1:], (10, 20, 0x12345678), strict=True):
            r.mem.write(address, 4, value)
        return 0xFFEEDD0000000001

    r.handlers["calls", 0x140E634C0] = read


def test_changed_io_serializes_record_72_validates_result_and_frees_actual_vector() -> None:
    r = Rig()
    prepare_changed_io(r)

    def serialize(args: tuple[int, ...]) -> None:
        service, result, descriptor, record = args
        assert service == r.service
        assert r.mem.read(record, 2) == 0x7872
        assert r.mem.read(descriptor, 8) == 0x143218B60
        assert r.mem.read(descriptor + 8, 8) == 0
        assert r.mem.read(descriptor + 0x10, 16) == 0
        assert r.mem.read(descriptor + 0x20, 8) == 0
        r.serialize(result, descriptor)

    r.handlers["virtual_calls", VSERIAL] = serialize
    assert r.run(MAIN, r.manager) == 16
    assert r.called(VSEND, "virtual_calls") == [(r.receiver, r.payload, 5)]
    assert r.called(0x142D6BAB4) == [(r.payload, 32)]
    with pytest.raises(ReplayMemoryError):
        r.mem.read(r.payload, 1)
    assert r.called(0x140E08110) == [(r.manager, 20, 10)]
    frame = next(raw for size, raw in r.snapshots if size == 0xF8)
    assert frame[0xF0] == 1
    assert frame[0x90:0xA8] == bytes(24)
    targets = [target for _, target, _ in r.calls]
    assert targets.index(0x14096B890) < targets.index(0x1402BD7F0) < targets.index(VSEND)
    assert targets.index(VSEND) < targets.index(0x1402A8630) < targets.index(0x140E08110)


def test_changed_io_releases_control_with_current_destroy_and_dispose_vtables() -> None:
    r = Rig()
    prepare_changed_io(r)
    control, first, second = r.alloc(16), r.alloc(16), r.alloc(16)
    r.mem.write(control, 8, first)
    r.mem.write(control + 8, 4, 1)
    r.mem.write(control + 12, 4, 1)
    r.mem.write(first, 8, 0xF100)
    r.mem.write(second + 8, 8, 0xF108)

    def serialize(args: tuple[int, ...]) -> None:
        r.serialize(args[1], args[2])
        r.mem.write(args[1] + 0x20, 8, control)

    def destroy(args: tuple[int, ...]) -> None:
        assert r.mem.read(r.frame(0xF8) + 0xF0, 1) == 1
        r.mem.write(control, 8, second)

    r.handlers["virtual_calls", VSERIAL] = serialize
    r.handlers["virtual_calls", 0xF100] = destroy
    r.handlers["virtual_calls", 0xF108] = lambda args: None
    assert r.run(MAIN, r.manager) == 16
    assert r.called(0xF100, "virtual_calls") == [(control,)]
    assert r.called(0xF108, "virtual_calls") == [(control,)]
    assert r.mem.read(control + 8, 8) == 0


def test_send_holds_vptr_but_reads_current_slot_after_data_and_holds_clock_before_host() -> None:
    r = Rig()
    prepare_changed_io(r)
    other_table, other_clock = r.alloc(0x200), r.alloc(0x200)
    changed = False

    def mutate(address: int, width: int, value: int) -> None:
        if r.live and address == r.frame(0xF8) + 0x90 and width == 8:
            r.mem.write(r.receiver, 8, other_table)
            r.mem.write(r.vtable + 0xE8, 8, 0xF0E8)

    def host(args: tuple[int, ...]) -> int:
        nonlocal changed
        if r.called(0xF0E8, "virtual_calls") and not changed:
            for offset in range(0, 0x200, 8):
                r.mem.write(other_clock + offset, 8, r.mem.read(r.clock + offset, 8))
            r.mem.write(r.manager + 0x358, 8, other_clock)
            changed = True
            return 321
        return 100

    r.after_read = mutate
    r.handlers["calls", HOST] = host
    r.handlers["virtual_calls", 0xF0E8] = lambda args: None
    assert r.run(MAIN, r.manager) == 16
    assert r.called(0xF0E8, "virtual_calls") == [(r.receiver, r.payload, 5)]
    assert r.mem.read(r.clock + 0x50, 4) == 321
    assert r.mem.read(other_clock + 0x50, 4) == 0


def test_missing_service_error_exposes_live_homes_and_still_validates_provider_result() -> None:
    r = Rig()
    prepare_changed_io(r)
    r.handlers["calls", 0x140942110] = lambda args: 0

    def error(args: tuple[int, ...]) -> None:
        assert args[1:4] == (0, 0x1431FAC00, 0x2F5)
        assert r.mem.read(args[4], 8) == 0x1431FAC58
        assert r.mem.read(args[5], 8) == 0xF00D1234
        r.mem.fill(args[0], 0, 0x28)

    r.handlers["error_home_calls", 0x140A08840] = error
    assert r.run(MAIN, r.manager) == 16
    assert r.called(VSEND, "virtual_calls") == [(r.receiver, 0, 0)]
    assert len(r.called(0x14096B890)) == 1
    assert not r.called(0x142D6BAB4)


@pytest.mark.parametrize("channel", ["virtual_calls", "error_home_calls"])
def test_missing_io_category_keeps_commit_and_prepared_message_prefix(channel: str) -> None:
    r = Rig()
    prepare_changed_io(r)
    if channel == "error_home_calls":
        r.handlers["calls", 0x140942110] = lambda args: 0
    r.bound = r.bind(**{channel: ReplayTaskRebuildCalls(None)})
    with pytest.raises(UnresolvedReplayTaskRebuild):
        r.run(MAIN, r.manager)
    assert r.mem.read(r.clock + 0x30, 4) == 9
    snapshot = next(raw for size, raw in r.snapshots if size == 0xF8)
    assert snapshot[0x70:0x72] == b"\x72\x78"
    assert not r.called(0x14096B890)
    assert not r.live


def test_binding_requires_actual_service_objects_and_does_not_invent_profile() -> None:
    r = Rig()
    with pytest.raises(ValueError):
        r.bind(virtual_calls=cast(ReplayTaskRebuildCalls, None))
    assert not r.events


def test_scheduler_composes_actual_queue_refresh_timer_stats_and_pending_consumption() -> None:
    r = Rig()
    r.queue, r.timer = r.alloc(0x1400), r.alloc(0x2C8)
    for at, width, value in (
        (r.manager + 0x388, 8, r.queue),
        (r.manager + 0x390, 8, r.queue),
        (r.settings + 0x390, 8, r.queue),
        (r.queue + 0x100, 8, r.timer),
        (r.queue + 0x3D0, 8, r.descriptor),
        (r.queue + 0x3F0, 4, 16),
        (r.timer + 0x2A4, 4, 90),
    ):
        r.mem.write(at, width, value)
    for i in range(5):
        r.mem.write(r.queue + 0x2C + i * 4, 4, i + 1)
    unavailable = ReplayTaskRebuildCalls(None)
    tuning = bind_replay_cycle_tuning(
        r.context,
        r.ordinary_calls,
        ceil_calls=unavailable,
        virtual_calls=unavailable,
        logger_home_calls=unavailable,
        timer_home_calls=unavailable,
        bind_local=r.local,
        mxcsr=0x1F80,
        profile=ReplayCycleTuningProfile(
            bytes(0x24),
            bytes(0x70),
            bytes(0x98),
            bytes(0x40),
            bytes(0x40),
            bytes(0x44),
            bytes(0x28),
        ),
    )
    for target in (
        0x140E63280,
        0x140E634C0,
        0x140E63BD0,
        0x140E64030,
        0x140E64150,
        0x140E65420,
        0x140E158C0,
        0x140E15A50,
        0x140E63820,
        0x140E64040,
        0x140E157A0,
        0x140E63E70,
        0x140E15A80,
        0x140F3EA40,
        0x140D6ACC0,
        0x140E630C0,
        0x140E64160,
    ):

        def child(args: tuple[int, ...], entry: int = target) -> int | None:
            assert tuning.call is not None
            return tuning.call(entry, args, None)

        r.handlers["calls", target] = child
    assert r.run(MAIN, r.manager) == 16
    assert r.mem.read(r.clock + 0x30, 4) == 9
    assert [r.mem.read(r.clock + 0x38 + i * 4, 4) for i in range(5)] == [1, 2, 3, 4, 5]
    assert r.mem.read(r.timer + 0x2A4, 4) == 100
    assert r.mem.read(r.queue + 0x3E8, 4) == 6
    assert r.mem.read(r.queue + 0x400, 4) == 13
    # The next scheduler call drains an actual pending cycle without committing again.
    assert r.run(MAIN, r.manager) == 16
    assert r.mem.read(r.queue + 0x3E8, 4) == 5
    assert r.mem.read(r.queue + 0x4CC, 4) == 1
    assert r.mem.read(r.clock + 0x30, 4) == 9
    assert len(r.called(0x140E63BD0)) == 1


def test_scheduler_uses_source_modes_metrics_and_queued_tree_change() -> None:
    r = Rig()
    r.queue, r.timer = r.alloc(0x1800), r.alloc(0x2C8)
    tree_header, game = r.alloc(0x28), r.alloc(0x600)
    config, metric_data = r.alloc(16), r.alloc(0x500)
    r.mem.map_bytes(0x144353698, game.to_bytes(8, "little"))
    for at, width, value in (
        (r.manager + 0x388, 8, r.queue),
        (r.manager + 0x390, 8, r.queue),
        (r.settings + 0x390, 8, r.queue),
        (r.queue + 0x100, 8, r.timer),
        (r.queue + 0x3D0, 8, r.descriptor),
        (r.queue + 0x3F0, 4, 16),
        (r.timer + 0x2A4, 4, 90),
        (r.queue + 0x7A8, 8, tree_header),
        (tree_header, 8, tree_header),
        (tree_header + 8, 8, tree_header),
        (tree_header + 0x10, 8, tree_header),
        (tree_header + 0x18, 2, 0x101),
        (0x1442846F0, 8, config),
        (config, 8, metric_data),
        (metric_data + 18 * 48 + 0x2C, 4, 125),
    ):
        r.mem.write(at, width, value)
    for i in range(5):
        r.mem.write(r.queue + 0x2C + i * 4, 4, i + 1)
    unavailable = ReplayTaskRebuildCalls(None)
    tuning = bind_replay_cycle_tuning(
        r.context,
        r.ordinary_calls,
        ceil_calls=unavailable,
        virtual_calls=unavailable,
        logger_home_calls=unavailable,
        timer_home_calls=unavailable,
        bind_local=r.local,
        mxcsr=0x1F80,
        profile=ReplayCycleTuningProfile(
            bytes(0x24),
            bytes(0x70),
            bytes(0x98),
            bytes(0x40),
            bytes(0x40),
            bytes(0x44),
            bytes(0x28),
        ),
    )
    services = bind_replay_cycle_services(
        r.context,
        r.ordinary_calls,
        imports=unavailable,
        virtual_calls=unavailable,
        logger_home_calls=unavailable,
        error_home_calls=unavailable,
        popup_home_calls=unavailable,
        send_home_calls=unavailable,
        format_calls=unavailable,
        atomics=r.atomics,
        bind_local=r.local,
        profile=ReplayCycleServicesProfile(
            bytes(0x30),
            bytes(8),
            bytes(0xB8),
            bytes(0x38),
            bytes(0x14),
            bytes(8),
            bytes(0x38),
            bytes(0x40),
            bytes(0x24),
            bytes(0x28),
            bytes(0x90),
            gs_base=0,
        ),
    )
    tree = bind_replay_cycle_tree(r.context, r.ordinary_calls)
    groups = (
        (
            tuning,
            (
                0x140E63280,
                0x140E634C0,
                0x140E63BD0,
                0x140E64030,
                0x140E64150,
                0x140E65420,
                0x140E158C0,
                0x140E15A50,
                0x140E63820,
                0x140E64040,
                0x140E157A0,
                0x140E63E70,
                0x140E15A80,
                0x140F3EA40,
                0x140D6ACC0,
                0x140E630C0,
                0x140E64160,
            ),
        ),
        (
            services,
            (
                0x1409738C0,
                0x140E05160,
                0x140E051E0,
                0x140E053D0,
                0x140E08110,
                0x140E0CA00,
                0x140E16870,
                0x140E169D0,
                0x140E16E00,
                0x140E469E0,
                0x140E64A70,
                0x140E68F60,
                0x140E57AC0,
                0x140E16880,
                0x140E4FD40,
                0x140E50750,
                0x140E50490,
                0x140DF6100,
                0x1413D3E20,
                0x1413D3FA0,
                0x140E4FB80,
                0x1413D3F30,
            ),
        ),
        (tree, (0x140E642F0, 0x140E646E0, 0x140E64A00, 0x140E62D90, 0x140E64940, 0x140E649A0)),
        (r.memory_runtime, (0x142D6BA78, 0x142D6BAB4)),
    )
    for owner, entries in groups:
        for entry in entries:

            def child(
                args: tuple[int, ...], target: int = entry, bound: ReplayTaskRebuildCalls = owner
            ) -> int | None:
                assert bound.call is not None
                return bound.call(target, args, None)

            r.handlers["calls", entry] = child
    # The Game-clock capability is authored; all mode/metric/tree answers below
    # come from supplied owned state and the addressed source-backed ports.
    r.handlers["calls", 0x140D6A880] = lambda args: r.mem.read(r.clock + 0x30, 4)
    assert tuning.call is not None
    assert tuning.call(0x140E63E70, (r.queue, 0, 16, 8), None) is None
    node = r.mem.read(tree_header, 8)
    assert r.mem.read(r.queue + 0x7B0, 8) == 1
    assert r.run(MAIN, r.manager) == 16
    assert r.mem.read(r.clock + 0x30, 4) == 9
    assert r.mem.read(r.queue + 0x7B0, 8) == 0
    assert r.called(0x142D6BAB4) == [(node, 40)]
    with pytest.raises(ReplayMemoryError):
        r.mem.read(node, 1)
    assert [r.mem.read(r.clock + 0x38 + i * 4, 4) for i in range(5)] == [1, 2, 3, 4, 5]
    assert r.mem.read(r.timer + 0x2A4, 4) == 100
    assert r.mem.read(r.queue + 0x3E8, 4) == 6
    assert r.mem.read(r.queue + 0x400, 4) == 13
    assert r.called(0x1409738C0) == [(config, 18)]
    for target in (0x140E053D0, 0x140E169D0, 0x140E16E00, 0x140E051E0):
        assert r.called(target)
    assert r.run(MAIN, r.manager) == 16
    assert r.mem.read(r.queue + 0x3E8, 4) == 5
    assert r.mem.read(r.clock + 0x30, 4) == 9
    assert len(r.called(0x140E63BD0)) == 1
