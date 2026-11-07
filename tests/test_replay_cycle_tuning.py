"""Source-led cycle tuning controls with explicit authored deeper services.

Actual owned memory, clock getters, ceil and allocation/free are composed here.
Tree balancing, row/session services and metrics remain authored capabilities;
these controls neither execute native instructions nor restore a recording.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import fields, replace
from typing import cast

import pytest

from vantage.replay_command_reader import (
    ReplayCommandReaderProfile,
    bind_replay_command_reader,
)
from vantage.replay_cycle_tree import bind_replay_cycle_tree
from vantage.replay_cycle_tuning import (
    ReplayCycleTuningProfile,
    bind_replay_cycle_tuning,
)
from vantage.replay_memory import ReplayMemory, ReplayMemoryError
from vantage.replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
)
from vantage.replay_unit_ai_map import ReplayUnitAIMapAtomics

TUNE, MODE2, ADVANCE, RESET = 0x140E63280, 0x140E634C0, 0x140E63BD0, 0x140E64030
REJECT, STATS, ROLE_A, ROLE_B = 0x140E64150, 0x140E65420, 0x140E158C0, 0x140E15A50
GATE, WIDTH, FUTURE = 0x140E63820, 0x140E64040, 0x140E157A0
SCHEDULE, ROLE, TIMER = 0x140E63E70, 0x140E15A80, 0x140F3EA40
TOKEN, ENTRY, ERASE = 0x140D6ACC0, 0x140E630C0, 0x140E64160
METRIC, EXTERNAL, GAME = 0x1409738C0, 0x1442846F0, 0x144353698
CLOCK, HOST, LOG, CEIL = 0x140E68F80, 0x140A71140, 0x14101ADB0, 0x142D6E453
ROWS, VID = 0x1442DE068, 0xFF0018
U32, U64 = (1 << 32) - 1, (1 << 64) - 1
Handler = Callable[[tuple[int, ...]], int | None]


class Rig:
    def __init__(self) -> None:
        self.mem = ReplayMemory()
        self.events: list[tuple[str, int, int, int]] = []
        self.calls: list[tuple[str, int, tuple[int, ...]]] = []
        self.handlers: dict[tuple[str, int], Handler] = {}
        self.metrics: dict[int, int | None] = {
            0: 1,
            1: 10,
            2: 100,
            4: 70,
            5: 4,
            6: 100,
            7: 0,
            10: 3,
            18: 125,
        }
        self.live: list[tuple[int, int]] = []
        self.snapshots: list[tuple[int, bytes]] = []
        self.after_read: Callable[[int, int, int], None] | None = None
        self.after_write: Callable[[int, int, int], None] | None = None
        self.queue, self.manager = self.alloc(0x1400), self.alloc(0xE00)
        self.clock, self.game, self.timer = self.alloc(0x200), self.alloc(0x600), self.alloc(0x2C8)
        self.external, self.external_data = self.alloc(16), self.alloc(0x330)
        self.header = self.alloc(0x28)
        self.nodes = [self.alloc(0x28) for _ in range(3)]
        self.output, self.key, self.endpoints = self.alloc(24), self.alloc(8), self.alloc(16)
        self.receiver, self.vtable = self.alloc(8), self.alloc(0x20)
        self.session_slot, self.session = self.alloc(8), self.alloc(8)
        self.record = self.alloc(0x50)
        for at, size in (
            (EXTERNAL, 8),
            (GAME, 8),
            (ROWS, 8 * 0x30),
            (0x144355060, 16),
            (0x1442C3F98, 8),
            (0x143266E00, 16),
            (0x143DAE440, 8),
            (0x143DADE30, 8),
        ):
            self.mem.map_bytes(at, bytes(size))
        for at, width, value in (
            (EXTERNAL, 8, self.external),
            (GAME, 8, self.game),
            (0x144355068, 8, 0xABC0),
            (0x1442C3F98, 8, self.manager),
            (self.external, 8, self.external_data),
            (self.manager + 0x358, 8, self.clock),
            (self.manager + 0x318, 4, 6),
            (self.manager + 0xD18, 8, 1),
            (self.manager + 0x2E8, 8, self.receiver),
            (self.receiver, 8, self.vtable),
            (self.vtable + 0x18, 8, VID),
            (self.session_slot, 8, self.session),
            (self.game + 0xA8, 4, 1),
            (self.game + 0xD0, 4, 100),
            (self.clock + 8, 4, 1),
            (self.clock + 0x30, 4, 100),
            (self.queue + 0x100, 8, self.timer),
            (self.queue + 0x3D0, 8, self.manager),
            (self.queue + 0x3F0, 4, 16),
            (self.queue + 0x3E4, 4, 4),
            (self.queue + 0x7A8, 8, self.header),
            (self.header, 8, self.header),
            (self.header + 8, 8, self.header),
            (self.header + 0x10, 8, self.header),
            (self.header + 0x19, 1, 1),
            (self.timer + 0x2A4, 4, 90),
            (self.timer + 0x100, 4, U32),
            (0x143DAE440, 8, 0x1122334400000000),
            (0x143DADE30, 8, 0x5566778800000000),
            (
                0x143266E00,
                16,
                int.from_bytes(bytes.fromhex("04000000050000000600000007000000"), "little"),
            ),
        ):
            self.mem.write(at, width, value)
        self.context = ReplayTaskRebuildStorage(self.queue, self.read, self.write)
        self.ordinary_calls = ReplayTaskRebuildCalls(self.ordinary)
        self.runtime = self.mem.runtime_calls(self.ordinary_calls)
        self.profile = ReplayCycleTuningProfile(
            *(
                bytes([0xA0 + i]) * size
                for i, size in enumerate((0x24, 0x70, 0x98, 0x40, 0x40, 0x44, 0x28))
            )
        )
        atomics = ReplayUnitAIMapAtomics(self.mem.compare_exchange_u32, self.mem.fetch_add_u32)
        self.reader = bind_replay_command_reader(
            self.context,
            self.ordinary_calls,
            imports=self.ordinary_calls,
            logger_home_calls=self.ordinary_calls,
            atomics=atomics,
            bind_local=self.local,
            profile=ReplayCommandReaderProfile(bytes(0x58), bytes(0x50), bytes(0x90)),
        )
        self.bound = self.bind()

    def alloc(self, size: int) -> int:
        at = self.mem.allocate(size)
        self.mem.fill(at, 0, size)
        return at

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
        return next(at for length, at in reversed(self.live) if length == size)

    def bind(self, **overrides: ReplayTaskRebuildCalls) -> ReplayTaskRebuildCalls:
        channels = {
            name: ReplayTaskRebuildCalls(self.channel(name))
            for name in ("ceil_calls", "virtual_calls", "logger_home_calls", "timer_home_calls")
        }
        channels.update(overrides)
        return bind_replay_cycle_tuning(
            self.context,
            self.ordinary_calls,
            **channels,
            bind_local=self.local,
            profile=self.profile,
            mxcsr=0x1F80,
        )

    def record_call(self, channel: str, target: int, args: tuple[int, ...]) -> Handler | None:
        self.calls.append((channel, target, args))
        self.events.append(("call", target, 0, len(self.calls)))
        return self.handlers.get((channel, target))

    def channel(self, name: str) -> Callable[[int, tuple[int, ...], memoryview | None], int | None]:
        def call(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
            assert data is None
            handler = self.record_call(name, target, args)
            if handler:
                return handler(args)
            if name == "ceil_calls" and target == CEIL:
                assert self.runtime.call is not None
                return self.runtime.call(target, args, data)
            if name == "virtual_calls" and target == VID:
                return 0x1234567890
            if name == "logger_home_calls" and target == LOG:
                return None
            if name == "timer_home_calls" and target == 0x140F3EB40:
                return None
            raise UnresolvedReplayTaskRebuild(f"unprovided authored {name} target{target:x}")

        return call

    def ordinary(self, target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        assert data is None
        handler = self.record_call("calls", target, args)
        if handler:
            return handler(args)
        if target == CLOCK:
            assert self.reader.call is not None
            return self.reader.call(target, args, data)
        if target in (0x142D6BA78, 0x142D6BAB4):
            assert self.runtime.call is not None
            return self.runtime.call(target, args, data)
        if target == METRIC:
            return self.metrics[args[1]]
        if target == HOST:
            return 100
        if target == 0x140E051E0:
            return 1
        if target == 0x140E053D0:
            return 0
        if target == 0x140D6A880:
            return 100
        if target in (0x140D6AD50, 0x140E08110, 0x1402AB280):
            return None
        if target == 0x140E57AC0:
            return self.session_slot
        if target == 0x1413D3FA0:
            return self.record
        if target == 0x140E16870:
            return 0xF000
        if target == 0x140E64A70:
            return 0x1122334455667788
        raise UnresolvedReplayTaskRebuild(f"unprovided authored child{target:x}")

    def run(self, target: int, *args: int) -> int | None:
        assert self.bound.call is not None
        return self.bound.call(target, args, None)

    def called(self, target: int, channel: str = "calls") -> list[tuple[int, ...]]:
        return [args for ch, t, args in self.calls if ch == channel and t == target]

    def active_width(self, width: int = 25, index: int = 0, ordinal: int = 0) -> None:
        self.mem.write(ROWS + index * 0x30 + 8, 8, 1)
        self.mem.write(ROWS + index * 0x30 + 0x20, 4, ordinal)
        self.mem.write(self.game + 0x1D8 + ordinal * 4, 4, 100)
        self.mem.write(self.queue + 0x480 + index * 4, 4, width)

    def tree(self) -> None:
        a, b, c = self.nodes
        for at, value in (
            (self.header, a),
            (self.header + 8, b),
            (self.header + 16, c),
            (a, self.header),
            (a + 8, b),
            (a + 16, self.header),
            (b, a),
            (b + 8, self.header),
            (b + 16, c),
            (c, self.header),
            (c + 8, b),
            (c + 16, self.header),
            (self.queue + 0x7B0, 3),
        ):
            self.mem.write(at, 8, value)
        for node, key in zip(self.nodes, (10, 20, 30), strict=True):
            self.mem.write(node + 0x1C, 4, key)
            self.mem.write(node + 0x20, 8, 0x1000000000 + key)


@pytest.mark.parametrize("field", [f.name for f in fields(ReplayCycleTuningProfile)])
def test_profile_requires_explicit_exact_immutable_seed(field: str) -> None:
    r = Rig()
    for bad in (b"", bytearray(getattr(r.profile, field))):
        with pytest.raises(ValueError, match="explicit"):
            replace(r.profile, **{field: bad})


@pytest.mark.parametrize(
    ("target", "arity"),
    [
        (TUNE, 4),
        (MODE2, 4),
        (ADVANCE, 1),
        (RESET, 1),
        (REJECT, 1),
        (STATS, 2),
        (ROLE_A, 2),
        (ROLE_B, 2),
        (GATE, 1),
        (WIDTH, 1),
        (FUTURE, 1),
        (SCHEDULE, 4),
        (ROLE, 2),
        (TIMER, 1),
        (TOKEN, 1),
        (ENTRY, 2),
        (ERASE, 2),
    ],
)
def test_addressed_contract_rejects_malformed_input_before_effects(target: int, arity: int) -> None:
    r = Rig()
    assert r.bound.call is not None
    for args, payload in (
        ((0,) * (arity + 1), None),
        ((-1,) + (0,) * (arity - 1), None),
        ((0,) * arity, memoryview(b"x")),
    ):
        with pytest.raises(ValueError):
            r.bound.call(target, args, payload)
    assert not r.events and not r.calls


@pytest.mark.parametrize("mxcsr", [True, 0, 0x1F81, 0x9F80])
def test_binding_rejects_wrong_fp_profile_before_effects(mxcsr: int) -> None:
    r = Rig()
    unavailable = ReplayTaskRebuildCalls(None)
    with pytest.raises(ValueError):
        bind_replay_cycle_tuning(
            r.context,
            r.ordinary_calls,
            ceil_calls=unavailable,
            virtual_calls=unavailable,
            logger_home_calls=unavailable,
            timer_home_calls=unavailable,
            bind_local=r.local,
            profile=r.profile,
            mxcsr=mxcsr,
        )
    assert not r.events


def test_unknown_calls_preserve_objects_and_actual_result() -> None:
    r = Rig()
    args, payload, result = (1, 2), memoryview(b"raw"), 1234567890123456

    def delegate(target: int, received: tuple[int, ...], data: memoryview | None) -> int:
        assert target == 42 and received is args and data is payload
        return result

    unavailable = ReplayTaskRebuildCalls(None)
    bound = bind_replay_cycle_tuning(
        r.context,
        ReplayTaskRebuildCalls(delegate),
        ceil_calls=unavailable,
        virtual_calls=unavailable,
        logger_home_calls=unavailable,
        timer_home_calls=unavailable,
        bind_local=r.local,
        profile=r.profile,
        mxcsr=0x1F80,
    )
    assert bound.call is not None and bound.call(42, args, payload) is result


def test_plain_storage_helpers_preserve_void_pointer_and_current_counter_returns() -> None:
    r = Rig()
    r.mem.write(r.queue + 0x4CC, 4, 9)
    assert r.run(RESET, r.queue) is None and r.mem.read(r.queue + 0x4CC, 4) == 0
    r.mem.write(r.queue + 0x4A0, 4, U32)

    def mutate(address: int, width: int, value: int) -> None:
        if address == r.queue + 0x4A0:
            r.mem.write(address, 4, 77)

    r.after_write = mutate
    assert r.run(REJECT, r.queue) == 77
    assert r.run(STATS, r.queue, r.output) == r.queue + 0x2C
    assert r.mem.read(r.output, 8) == r.queue + 0x2C
    r.mem.write(r.game + 0x5C0, 8, 0xFEDCBA9876543210)
    assert r.run(TOKEN, r.game) == 0xFEDCBA9876543210


def test_future_holds_mode_before_clock_and_wraps_low32() -> None:
    r = Rig()
    r.mem.write(r.clock + 0x30, 4, U32)

    def mutate(address: int, width: int, value: int) -> None:
        if address == r.clock + 0x30:
            r.mem.write(r.clock + 8, 4, 2)

    r.after_read = mutate
    assert r.run(FUTURE, r.manager) == 1
    assert r.run(FUTURE, r.manager) == 7


@pytest.mark.parametrize("reason", ["predicate", "mode2_changed", "pending_tree", "future"])
def test_gate_rejection_stops_before_counter_and_final_metric(reason: str) -> None:
    r = Rig()
    if reason == "predicate":
        r.handlers["calls", 0x140E051E0] = lambda args: 0
    elif reason == "mode2_changed":
        r.mem.write(r.game + 0xA8, 4, 2)
        r.mem.write(r.queue + 0x13B8, 1, 1)
    elif reason == "pending_tree":
        r.tree()
    else:
        r.metrics[7] = 103
    assert r.run(GATE, r.queue) == 0
    assert r.mem.read(r.queue + 0x4B4, 4) == 0
    assert not any(args[1] == 0 for args in r.called(METRIC))


def test_gate_uses_held_external_then_current_counter_after_metric() -> None:
    r = Rig()
    r.mem.write(r.queue + 0x4B4, 4, U32)

    def metric(args: tuple[int, ...]) -> int:
        assert args[0] == r.external
        if args[1] == 7:
            r.mem.write(EXTERNAL, 8, 0)
            return 102
        assert args[1] == 0 and r.mem.read(r.queue + 0x4B4, 4) == 0
        r.mem.write(r.queue + 0x4B4, 4, 7)
        return 7

    r.handlers["calls", METRIC] = metric
    assert r.run(GATE, r.queue) == 1
    assert r.mem.read(r.queue + 0x4B4, 4) == 7


def test_width_scans_all_eight_rows_filters_thresholds_and_uses_upper_cap() -> None:
    r = Rig()
    r.active_width(60, 0, 7)
    r.active_width(U32, 3, 6)
    r.mem.write(r.game + 0x1D8 + 6 * 4, 4, 99)
    r.active_width(80, 7, 5)
    r.metrics[2] = 40
    assert r.run(WIDTH, r.queue) == 40
    assert [args[1] for args in r.called(METRIC)] == [1, 1, 2, 10]
    assert (
        sum(
            kind == "r" and ROWS <= at < ROWS + 0x180 and (at - ROWS) % 0x30 == 8
            for kind, at, _, _ in r.events
        )
        == 8
    )


def test_width_repeated_minima_are_distinct_and_smoothing_reloads_current_width() -> None:
    r = Rig()
    r.active_width(20)
    minimum_calls = 0

    def metric(args: tuple[int, ...]) -> int:
        nonlocal minimum_calls
        if args[1] == 1:
            minimum_calls += 1
            return 10 if minimum_calls == 1 else 30
        if args[1] == 10:
            r.mem.write(r.queue + 0x3F0, 4, 37)
            return 5
        return 100

    r.handlers["calls", METRIC] = metric
    assert r.run(WIDTH, r.queue) == 37
    assert minimum_calls == 2


def test_width_no_rows_returns_current_width_without_metrics_or_null_defaults() -> None:
    r = Rig()
    r.mem.write(EXTERNAL, 8, 0)
    assert r.run(WIDTH, r.queue) == 16
    assert not r.called(METRIC)
    r.active_width(20)
    assert r.run(WIDTH, r.queue) == 20
    assert r.called(METRIC) == [(0, 1), (0, 2), (0, 10)]


@pytest.mark.parametrize(
    ("credits", "initial_metric", "expected"),
    [(4, 70, 10), (100, 70, 37), (32, 70, 32), (0x10000004, 70, 10)],
)
def test_tune_literal_wrapped_budget_adjustments(
    credits: int,
    initial_metric: int,
    expected: int,
) -> None:
    r = Rig()
    r.mem.write(r.queue + 0x3E4, 4, credits)
    r.metrics[4] = initial_metric
    assert r.run(TUNE, r.queue, r.output, r.output + 4, 0) == int(credits != expected)
    if credits != expected:
        assert (r.mem.read(r.output, 4), r.mem.read(r.output + 4, 4)) == (16, expected)
    assert not r.called(0x140E08110)
    assert [args[1] for args in r.called(METRIC)] == [7, 0, 5, 4, 6, 5]


def test_tune_ignored_first_metric_and_early_gate_retains_private_fourth_home() -> None:
    r = Rig()
    r.handlers["calls", 0x140E051E0] = lambda args: 0
    assert r.run(TUNE, r.queue, r.output, r.output + 4, 0xABCDEF0000000007) == 0
    assert int.from_bytes(r.snapshots[0][1][0x20:0x24], "little") == 7
    assert not r.called(METRIC)
    del r.handlers["calls", 0x140E051E0]
    fifth_calls = 0

    def metric(args: tuple[int, ...]) -> int | None:
        nonlocal fifth_calls
        if args[1] == 5:
            fifth_calls += 1
            return None if fifth_calls == 1 else 4
        return r.metrics[args[1]]

    r.handlers["calls", METRIC] = metric
    assert r.run(TUNE, r.queue, r.output, r.output + 4, 0) == 1
    assert fifth_calls == 2


@pytest.mark.parametrize("kind", [2, 3])
def test_direct_tune_reads_current_backing_and_outputs_before_notification(kind: int) -> None:
    r = Rig()
    r.tree()
    # A zero first key allows the scheduling gate and the existing key20 avoids allocation.
    r.mem.write(r.nodes[0] + 0x1C, 4, 0)
    r.mem.write(r.clock + 0x30, 4, 18)
    r.mem.write(r.external + 8, 4, kind)
    offset = 0x268 if kind == 2 else 0x2C8
    r.mem.write(r.external_data + offset, 4, 25)
    other = r.alloc(0x330)
    r.mem.write(other + offset + 0x30, 4, 6)

    def mutate(address: int, width: int, value: int) -> None:
        if address == r.output:
            r.mem.write(r.external, 8, other)
        if address == r.queue + 0x13B8:
            r.mem.write(r.output, 4, 77)
            r.mem.write(r.output + 4, 4, 88)

    r.after_write = mutate
    assert r.run(TUNE, r.queue, r.output, r.output + 4, 0) == 1
    assert r.mem.read(r.nodes[1] + 0x20, 8) == (25 << 32) | 6
    assert r.called(0x140E08110) == [(r.manager, 88, 77)]


def test_tune_zero_divisor_refuses_at_source_div_after_gate_effects() -> None:
    r = Rig()
    r.mem.write(r.queue + 0x3F0, 4, 0)
    with pytest.raises(UnresolvedReplayTaskRebuild, match="140e63374"):
        r.run(TUNE, r.queue, r.output, r.output + 4, 0)
    assert r.mem.read(r.queue + 0x4B4, 4) == 1
    assert r.mem.read(r.output, 8) == 0


def test_general_tune_publishes_held_values_after_schedule_mutates_output_homes() -> None:
    r = Rig()
    r.tree()
    r.mem.write(r.nodes[0] + 0x1C, 4, 0)
    r.mem.write(r.clock + 0x30, 4, 18)
    r.mem.write(r.queue + 0x3E0, 4, 1)

    def mutate(address: int, width: int, value: int) -> None:
        if address == r.queue + 0x13B8:
            r.mem.write(r.output, 4, 77)
            r.mem.write(r.output + 4, 4, 88)

    r.after_write = mutate
    assert r.run(TUNE, r.queue, r.output, r.output + 4, 1) == 1
    assert r.mem.read(r.nodes[1] + 0x20, 8) == (16 << 32) | 10
    assert r.called(0x140E08110) == [(r.manager, 10, 16)]


@pytest.mark.parametrize(
    ("cap", "period", "expected"),
    [(100, 125, (25, 4, 1)), (2, 125, (41, 2, 1)), (7, 0, (25, 7, 0))],
)
def test_mode2_actual_binary32_ceil_and_integer_adjustment(
    cap: int,
    period: int,
    expected: tuple[int, int, int],
) -> None:
    r = Rig()
    r.active_width()
    r.metrics[6], r.metrics[18] = cap, period
    assert r.run(MODE2, r.queue, r.output, r.output + 4, r.output + 8) == 1
    assert tuple(r.mem.read(r.output + i * 4, 4) for i in range(3)) == expected
    assert r.mem.read(r.queue + 0x13B8, 1) == 1
    assert len(r.called(CEIL, "ceil_calls")) == 1


def test_mode2_unsigned_product_rounds_once_before_real_ceil() -> None:
    r = Rig()
    r.active_width(1)
    r.metrics.update({1: 1, 2: 1, 5: 0x1000000, 6: 1, 10: 0, 18: 1})
    assert r.run(MODE2, r.queue, r.output, r.output + 4, r.output + 8) == 1
    assert r.called(CEIL, "ceil_calls") == [(0x4B800000,)]
    assert r.mem.read(r.output + 8, 4) == 0x1000000
    assert r.mem.read(r.output, 4) == 0x800000


@pytest.mark.parametrize("mutate_count", [False, True])
def test_mode2_full_path_uses_current_count_after_adjusted_width_publication(
    mutate_count: bool,
) -> None:
    r = Rig()
    r.active_width(10)
    r.metrics[6], r.metrics[18] = 4, 80
    r.mem.write(r.queue + 0x13B8, 1, 7)

    def mutate(address: int, width: int, value: int) -> None:
        if mutate_count and address == r.output and value == 16:
            r.mem.write(r.output + 4, 4, 5)

    r.after_write = mutate
    assert r.run(MODE2, r.queue, r.output, r.output + 4, r.output + 8) == int(mutate_count)
    assert r.mem.read(r.output, 4) == 16
    assert r.mem.read(r.queue + 0x13B8, 1) == int(mutate_count)


def test_mode2_unchanged_width_keeps_changed_flag_and_other_outputs() -> None:
    r = Rig()
    r.mem.write(r.queue + 0x13B8, 1, 7)
    r.mem.write(r.output + 4, 8, U64)
    assert r.run(MODE2, r.queue, r.output, r.output + 4, r.output + 8) == 0
    assert r.mem.read(r.output, 4) == 16
    assert r.mem.read(r.output + 4, 8) == U64
    assert r.mem.read(r.queue + 0x13B8, 1) == 7
    assert not r.called(CEIL, "ceil_calls")


def test_mode2_live_width_divisor_can_fault_after_stamp_publication() -> None:
    r = Rig()
    r.active_width()

    def ceiling(args: tuple[int, ...]) -> int:
        r.mem.write(r.output, 4, 0)
        return 0x3F800000

    r.handlers["ceil_calls", CEIL] = ceiling
    with pytest.raises(UnresolvedReplayTaskRebuild, match="140e63581"):
        r.run(MODE2, r.queue, r.output, r.output + 4, r.output + 8)
    assert r.mem.read(r.output + 8, 4) == 1
    assert r.mem.read(r.queue + 0x13B8, 1) == 0


@pytest.mark.parametrize("bad", [None, -1, 1 << 32])
def test_mode2_invalid_ceil_result_retains_only_first_width_prefix(bad: int | None) -> None:
    r = Rig()
    r.active_width()
    r.handlers["ceil_calls", CEIL] = lambda args: bad
    with pytest.raises(ValueError):
        r.run(MODE2, r.queue, r.output, r.output + 4, r.output + 8)
    assert r.mem.read(r.output, 4) == 25
    assert r.mem.read(r.output + 4, 8) == 0


def test_missing_ceil_category_refuses_without_ordinary_fallback() -> None:
    r = Rig()
    r.active_width()
    r.bound = r.bind(ceil_calls=ReplayTaskRebuildCalls(None))
    with pytest.raises(UnresolvedReplayTaskRebuild, match="142d6e453"):
        r.run(MODE2, r.queue, r.output, r.output + 4, r.output + 8)
    assert r.mem.read(r.output, 4) == 25
    assert not r.called(CEIL)


@pytest.mark.parametrize(("key", "slot_index"), [(10, 0), (20, 1), (30, 2)])
def test_entry_finds_existing_key_without_allocator(key: int, slot_index: int) -> None:
    r = Rig()
    r.tree()
    r.mem.write(r.key, 4, key)
    assert r.run(ENTRY, r.queue + 0x7A8, r.key) == r.nodes[slot_index] + 0x20
    assert not r.called(0x142D6BA78)


def test_entry_initial_search_key_and_fresh_final_key_are_distinct() -> None:
    r = Rig()
    r.tree()
    r.mem.write(r.key, 4, 20)
    reads = 0

    def mutate(address: int, width: int, value: int) -> None:
        nonlocal reads
        if address == r.nodes[1] + 0x1C:
            reads += 1
            if reads == 2:
                r.mem.write(r.key, 4, 30)

    r.after_read = mutate
    assert r.run(ENTRY, r.queue + 0x7A8, r.key) == r.nodes[1] + 0x20
    assert not r.called(0x142D6BA78)


def test_entry_allocation_holds_header_but_reloads_key_and_live_path_descriptor() -> None:
    r = Rig()
    replacement = r.alloc(0x28)
    r.mem.write(r.key, 4, 20)

    def allocate(args: tuple[int, ...]) -> int:
        assert args == (40,)
        r.mem.write(r.key, 4, 30)
        r.mem.write(r.queue + 0x7A8, 8, replacement)
        frame = r.frame(0x40)
        r.mem.write(frame + 0x38, 4, 77)
        return r.mem.allocate(40)

    def link(args: tuple[int, ...]) -> int:
        tree, descriptor, node = args
        assert tree == r.queue + 0x7A8
        assert r.mem.read(descriptor, 8) == r.header
        assert r.mem.read(descriptor + 8, 4) == 77
        assert r.mem.read(descriptor + 12, 4) == int.from_bytes(bytes([0xA3]) * 4, "little")
        assert r.mem.read(node + 0x1C, 4) == 30
        assert [r.mem.read(node + at, 8) for at in (0, 8, 16)] == [r.header] * 3
        assert r.mem.read(node + 0x18, 2) == 0
        return node

    r.handlers["calls", 0x142D6BA78] = allocate
    r.handlers["calls", 0x140E646E0] = link
    slot = r.run(ENTRY, r.queue + 0x7A8, r.key)
    assert slot is not None
    with pytest.raises(ReplayMemoryError):
        r.mem.read(slot, 8)  # Native default construction leaves this payload uninitialized.


def test_entry_length_return_reaches_literal_trap_without_allocation() -> None:
    r = Rig()
    r.mem.write(r.queue + 0x7B0, 8, 0x666666666666666)
    with pytest.raises(UnresolvedReplayTaskRebuild, match="140e6319c"):
        r.run(ENTRY, r.queue + 0x7A8, r.key)
    assert r.called(0x1402AB280) == [()]
    assert not r.called(0x142D6BA78)
    assert not r.live


def test_missing_tree_linker_retains_real_allocated_initialized_node() -> None:
    r = Rig()
    r.mem.write(r.key, 4, 4)
    with pytest.raises(UnresolvedReplayTaskRebuild, match="140e646e0"):
        r.run(ENTRY, r.queue + 0x7A8, r.key)
    node = r.called(0x140E646E0)[0][2]
    assert r.mem.read(node + 0x1C, 4) == 4
    assert r.mem.read(node + 0x19, 1) == 0
    assert not r.called(0x142D6BAB4)


def test_erase_full_range_counts_successors_before_mandatory_clear() -> None:
    r = Rig()
    r.tree()
    r.mem.write(r.endpoints, 8, r.nodes[0])
    r.mem.write(r.endpoints + 8, 8, r.header)
    r.handlers["calls", 0x140E64A00] = lambda args: None
    assert r.run(ERASE, r.queue + 0x7A8, r.endpoints) == 3
    assert r.called(0x140E64A00) == [(r.queue + 0x7A8,)]
    assert not r.called(0x140E642F0)
    assert not r.called(0x142D6BAB4)


def test_erase_partial_range_preserves_end_and_frees_actual_unlink_results() -> None:
    r = Rig()
    r.tree()
    a, b, c = r.nodes
    r.mem.write(r.endpoints, 8, a)
    r.mem.write(r.endpoints + 8, 8, c)

    def unlink(args: tuple[int, ...]) -> int:
        assert args[0] == r.queue + 0x7A8
        if args[1] == a:
            r.mem.write(b, 8, r.header)
            r.mem.write(r.header, 8, b)
        else:
            assert args[1] == b
            for at, value in ((r.header, c), (r.header + 8, c), (c + 8, r.header)):
                r.mem.write(at, 8, value)
        return args[1]

    r.handlers["calls", 0x140E642F0] = unlink
    assert r.run(ERASE, r.queue + 0x7A8, r.endpoints) == 2
    assert r.called(0x142D6BAB4) == [(a, 40), (b, 40)]
    for node in (a, b):
        with pytest.raises(ReplayMemoryError):
            r.mem.read(node, 1)
    assert r.mem.read(c + 0x1C, 4) == 30


def test_erase_empty_range_still_samples_current_header_but_does_not_unlink() -> None:
    r = Rig()
    r.tree()
    r.mem.write(r.endpoints, 8, r.nodes[1])
    r.mem.write(r.endpoints + 8, 8, r.nodes[1])
    assert r.run(ERASE, r.queue + 0x7A8, r.endpoints) == 0
    assert not r.calls
    assert any(kind == "r" and at == r.queue + 0x7A8 for kind, at, _, _ in r.events)


def test_schedule_updates_existing_slot_and_resets_changed_after_payload_publication() -> None:
    r = Rig()
    r.tree()
    r.mem.write(r.game + 0xA8, 4, 2)
    r.mem.write(r.queue + 0x13B8, 1, 1)

    def mutate(address: int, width: int, value: int) -> None:
        if address == r.queue + 0x13B8:
            assert r.mem.read(r.nodes[1] + 0x20, 8) == (25 << 32) | 6

    r.after_write = mutate
    assert r.run(SCHEDULE, r.queue, 6, 25, 20) is None
    assert r.mem.read(r.queue + 0x13B8, 1) == 0
    assert not r.called(0x142D6BA78)


def test_schedule_holds_nonempty_gate_before_private_key_store_and_logs_live_records() -> None:
    r = Rig()
    r.tree()
    r.mem.write(0x144355062, 1, 1)
    r.mem.write(r.queue + 0x13B8, 1, 9)

    def mutate(address: int, width: int, value: int) -> None:
        if r.live and address == r.frame(0x98) + 0x30:
            r.mem.write(r.queue + 0x7B0, 8, 0)

    def logger(args: tuple[int, ...]) -> None:
        assert args[:4] == (0xABC0, 0x2A, 0x14326A670, 4)
        vector = r.mem.read(args[4], 8)
        pointers = [r.mem.read(vector + i * 8, 8) for i in range(4)]
        assert [r.mem.read(p, 4) for p in pointers] == [6, 25, 20, 1]
        assert [r.mem.read(p + 8, 4) for p in pointers] == [7, 7, 8, 8]

    r.after_write = mutate
    r.handlers["logger_home_calls", LOG] = logger
    assert r.run(SCHEDULE, r.queue, 6, 25, 20) is None
    assert r.mem.read(r.queue + 0x13B8, 1) == 9
    assert not r.called(0x142D6BA78)


@pytest.mark.parametrize("credits", [0, 4, 7])
def test_advance_actual_timer_and_modular_slack_generate_pending_cycles(credits: int) -> None:
    r = Rig()
    r.mem.write(r.queue + 0x3E4, 4, credits)
    r.mem.write(r.queue + 0x4C4, 4, 9)

    def host(args: tuple[int, ...]) -> int:
        assert r.mem.read(r.queue + 0x4C4, 4) == 9
        return 100

    r.handlers["calls", HOST] = host
    assert r.run(ADVANCE, r.queue) is None
    target = (credits + 1) * 16
    slack = ((target + 124) // 125) * 125 - target
    assert r.mem.read(r.queue + 0x3E8, 4) == credits + slack // 16
    assert r.mem.read(r.queue + 0x400, 4) == slack % 16
    assert r.mem.read(r.queue + 0x4C4, 4) == 0
    assert r.mem.read(r.timer + 0x108, 4) == 10


def test_advance_zero_target_does_not_consume_period_return() -> None:
    r = Rig()
    r.mem.write(r.queue + 0x3E4, 4, U32)
    r.metrics[18] = None
    assert r.run(ADVANCE, r.queue) is None
    assert r.mem.read(r.queue + 0x3E8, 4) == U32
    assert r.mem.read(r.queue + 0x400, 4) == 0
    assert r.called(METRIC) == [(r.external, 18)]


def test_advance_logs_then_reloads_current_accumulator_and_width_each_iteration() -> None:
    r = Rig()
    r.mem.write(0x144355062, 1, 1)
    formats: list[int] = []

    def logger(args: tuple[int, ...]) -> None:
        assert args[:2] == (0xABC0, 0x2A) and args[3] == 2
        formats.append(args[2])
        vector = r.mem.read(args[4], 8)
        first, second = r.mem.read(vector, 8), r.mem.read(vector + 8, 8)
        assert (r.mem.read(first + 8, 4), r.mem.read(second + 8, 4)) == (7, 7)
        values = (r.mem.read(first, 4), r.mem.read(second, 4))
        if len(formats) == 1:
            assert values == (45, 45)
            r.mem.write(r.queue + 0x400, 4, 20)
            r.mem.write(r.queue + 0x3F0, 4, 10)
        elif len(formats) == 2:
            assert values == (5, 10)
            r.mem.write(r.queue + 0x400, 4, 5)
            r.mem.write(r.queue + 0x3F0, 4, 4)
        else:
            assert values == (6, 1)

    r.handlers["logger_home_calls", LOG] = logger
    assert r.run(ADVANCE, r.queue) is None
    assert formats == [0x14326A6E0, 0x14326A730, 0x14326A730]
    assert r.mem.read(r.queue + 0x400, 4) == 1
    assert r.mem.read(r.queue + 0x3E8, 4) == 6


def test_advance_scheduled_pair_is_held_across_publications_then_actual_range_erased() -> None:
    r = Rig()
    r.tree()
    a, b, _ = r.nodes
    r.mem.write(a + 0x20, 8, (16 << 32) | 3)

    def mutate(address: int, width: int, value: int) -> None:
        if address == r.queue + 0x3E4:
            r.mem.write(a + 0x20, 8, (99 << 32) | 9)

    def unlink(args: tuple[int, ...]) -> int:
        assert args == (r.queue + 0x7A8, a)
        r.mem.write(b, 8, r.header)
        r.mem.write(r.header, 8, b)
        return a

    r.after_write = mutate
    r.handlers["calls", 0x140E642F0] = unlink
    assert r.run(ADVANCE, r.queue) is None
    assert r.mem.read(r.queue + 0x3E4, 4) == 3
    assert r.mem.read(r.queue + 0x3F0, 4) == 16
    assert r.mem.read(r.queue + 0x4C8, 4) == 1
    assert r.called(0x142D6BAB4) == [(a, 40)]


def test_missing_queue_logger_refuses_after_accumulator_and_pending_prefix() -> None:
    r = Rig()
    r.mem.write(0x144355062, 1, 1)
    r.bound = r.bind(logger_home_calls=ReplayTaskRebuildCalls(None))
    with pytest.raises(UnresolvedReplayTaskRebuild, match="14101adb0"):
        r.run(ADVANCE, r.queue)
    assert r.mem.read(r.queue + 0x400, 4) == 45
    assert r.mem.read(r.queue + 0x3E8, 4) == 4
    assert not r.live


def test_role_a_qword_decrement_differs_from_role_b_zero_extended_dword() -> None:
    r = Rig()
    r.mem.write(r.manager + 0xD18, 8, 0)
    assert r.run(ROLE_A, r.manager, r.output) == r.output
    assert r.mem.read(r.output, 8) == U64
    r.mem.write(r.manager + 0x318, 4, 8)
    assert r.run(ROLE_B, r.manager, r.output) == r.output
    assert r.mem.read(r.output, 8) == U32
    assert not r.called(0x140E57AC0)


@pytest.mark.parametrize("mode", [0, 7, 8])
def test_role_early_mode_fallback_preserves_full_qword(mode: int) -> None:
    r = Rig()
    r.mem.write(r.manager + 0x318, 4, mode)
    assert r.run(ROLE, r.manager, r.output) == r.output
    assert r.mem.read(r.output, 8) == 0x1122334400000000
    assert r.events[0][:3] == ("r", 0x143266E00, 16)
    assert not r.called(0x140E57AC0)


def test_role_keeps_eight_zero_index_homes_and_uses_late_receiver_identity() -> None:
    r = Rig()
    r.mem.write(r.record + 0x48, 8, 0xBAD)
    samples = 0

    def lookup(args: tuple[int, ...]) -> int:
        nonlocal samples
        assert args[0] == r.session and r.mem.read(args[1], 8) == 0
        samples += 1
        if samples == 3:
            r.mem.write(r.record + 0x48, 8, 0x1234567890)
        return r.record

    r.handlers["calls", 0x1413D3FA0] = lookup
    assert r.run(ROLE, r.manager, r.output) == r.output
    assert r.mem.read(r.output, 8) == 3
    assert len(r.called(VID, "virtual_calls")) == 3
    assert all(args[1] == r.called(0x1413D3FA0)[0][1] for args in r.called(0x1413D3FA0))


def test_role_eight_misses_use_distinct_current_fallback_and_null_receiver_sentinel() -> None:
    r = Rig()
    r.mem.write(r.manager + 0x2E8, 8, 0)
    r.mem.write(r.record + 0x48, 8, 3)
    assert r.run(ROLE, r.manager, r.output) == r.output
    assert r.mem.read(r.output, 8) == 0x5566778800000000
    assert len(r.called(0x1413D3FA0)) == 8
    assert not r.called(VID, "virtual_calls")
    r.mem.write(r.record + 0x48, 8, U64)
    assert r.run(ROLE, r.manager, r.output) == r.output
    assert r.mem.read(r.output, 8) == 1


def test_timer_samples_current_start_after_host_and_equal_path_has_no_writes() -> None:
    r = Rig()
    r.handlers["calls", HOST] = lambda args: r.mem.write(r.timer + 0x2A4, 4, 100) or 100
    assert r.run(TIMER, r.timer) == 0
    assert not [e for e in r.events if e[0] == "w"]
    assert not r.snapshots


@pytest.mark.parametrize(
    ("index", "capacity", "expected_index", "expected_capacity"),
    [(0, 0, 1, 1), (100, 100, 0, 100), (U32, U32, 0, 0)],
)
def test_timer_unsigned_capacity_and_signed_rolling_index(
    index: int,
    capacity: int,
    expected_index: int,
    expected_capacity: int,
) -> None:
    r = Rig()
    r.mem.write(r.timer + 0x2A0, 4, index)
    r.mem.write(r.timer + 0x2C0, 4, capacity)
    assert r.run(TIMER, r.timer) == 10
    assert r.mem.read(r.timer + 0x2A0, 4) == expected_index
    assert r.mem.read(r.timer + 0x2C0, 4) == expected_capacity
    assert r.mem.read(r.timer + 0x10C + expected_index * 4, 4) == 10


def test_timer_keeps_signed_negative_index_fault_after_published_prefix() -> None:
    r = Rig()
    r.mem.write(r.timer + 0x2A0, 4, 0x7FFFFFFF)
    with pytest.raises(ReplayMemoryError):
        r.run(TIMER, r.timer)
    assert r.mem.read(r.timer + 0x2A0, 4) == 0x80000000
    assert r.mem.read(r.timer + 0x108, 4) == 10
    assert r.mem.read(r.timer + 0x2C0, 4) == 1


def test_timer_min_and_max_reload_sample_from_held_address() -> None:
    r = Rig()

    def mutate(address: int, width: int, value: int) -> None:
        if address == r.timer + 0x100:
            r.mem.write(r.timer + 0x110, 4, 99)
            r.mem.write(r.timer + 0x2A0, 4, 5)

    r.after_write = mutate
    assert r.run(TIMER, r.timer) == 10
    assert r.mem.read(r.timer + 0x100, 4) == 10
    assert r.mem.read(r.timer + 0x104, 4) == 99


def test_timer_logger_receives_current_fields_live_fifth_home_and_current_final_elapsed() -> None:
    r = Rig()
    r.mem.write(r.timer + 0x2B0, 8, 0xCAFE)
    r.mem.write(r.timer + 0x2BC, 4, 7)

    def logger(args: tuple[int, ...]) -> None:
        assert args[:4] == (0xCAFE, 0x14328DC50, 10, 7)
        assert r.mem.read(args[4], 8) == 0x1122334455667788
        r.mem.write(r.timer + 0x108, 4, 777)

    r.handlers["timer_home_calls", 0x140F3EB40] = logger
    assert r.run(TIMER, r.timer) == 777
    assert r.snapshots[0][0] == 0x28


@pytest.mark.parametrize("channel", ["virtual_calls", "timer_home_calls"])
def test_missing_category_preserves_source_prefix_without_fallback(channel: str) -> None:
    r = Rig()
    r.bound = r.bind(**{channel: ReplayTaskRebuildCalls(None)})
    if channel == "virtual_calls":
        with pytest.raises(UnresolvedReplayTaskRebuild, match=f"{VID:x}"):
            r.run(ROLE, r.manager, r.output)
        assert r.mem.read(r.output, 8) == 0
    else:
        r.mem.write(r.timer + 0x2B0, 8, 1)
        with pytest.raises(UnresolvedReplayTaskRebuild, match="140f3eb40"):
            r.run(TIMER, r.timer)
        assert r.mem.read(r.timer + 0x2A4, 4) == 100
        assert r.mem.read(r.timer + 0x108, 4) == 10
    assert not r.live


def test_binding_requires_real_channel_objects() -> None:
    r = Rig()
    with pytest.raises(ValueError):
        r.bind(ceil_calls=cast(ReplayTaskRebuildCalls, None))
    assert not r.events


def test_scheduled_changes_insert_apply_erase_clear_and_reuse_actual_tree() -> None:
    r = Rig()
    r.mem.write(r.header + 0x18, 1, 1)
    r.mem.write(r.game + 0xA8, 4, 2)
    tree = bind_replay_cycle_tree(r.context, r.ordinary_calls)
    for entry in (0x140E642F0, 0x140E646E0, 0x140E64A00, 0x140E62D90, 0x140E64940, 0x140E649A0):

        def child(args: tuple[int, ...], target: int = entry) -> int | None:
            assert tree.call is not None
            return tree.call(target, args, None)

        r.handlers["calls", entry] = child
    for count, width, key in ((2, 10, 10), (3, 25, 20), (1, 16, 30)):
        assert r.run(SCHEDULE, r.queue, count, width, key) is None
    assert r.mem.read(r.queue + 0x7B0, 8) == 3
    nodes = {r.mem.read(args[2] + 0x1C, 4): args[2] for args in r.called(0x140E646E0)}
    for size, credits, width, pending, slack in (
        (2, 2, 10, 11, 5),
        (1, 3, 25, 4, 5),
        (0, 1, 16, 7, 2),
    ):
        assert r.run(ADVANCE, r.queue) is None
        assert r.mem.read(r.queue + 0x7B0, 8) == size
        assert r.mem.read(r.queue + 0x3E4, 4) == credits
        assert r.mem.read(r.queue + 0x3F0, 4) == width
        assert r.mem.read(r.queue + 0x3E8, 4) == pending
        assert r.mem.read(r.queue + 0x400, 4) == slack
    assert r.called(0x142D6BAB4) == [(nodes[10], 40), (nodes[20], 40), (nodes[30], 40)]
    assert [r.mem.read(r.header + at, 8) for at in (0, 8, 16)] == [r.header] * 3
    for node in nodes.values():
        with pytest.raises(ReplayMemoryError):
            r.mem.read(node, 1)
    assert r.run(SCHEDULE, r.queue, 0, 16, 40) is None
    assert r.mem.read(r.queue + 0x7B0, 8) == 1
    first = r.mem.read(r.header, 8)
    assert r.mem.read(first + 0x1C, 4) == 40
    assert r.mem.read(first + 0x20, 8) == 16 << 32
    assert r.mem.read(r.queue + 0x4C8, 4) == 3
