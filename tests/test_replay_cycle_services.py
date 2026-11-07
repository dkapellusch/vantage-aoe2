"""Cycle-service source controls with real getters, roles, Results and memory.

Registry/policy, virtual interfaces, formatting, concatenation and TLS runtime
effects remain explicit authored capabilities. No native execution or recording
restoration is claimed by these deterministic owned-storage controls.
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
from vantage.replay_command_lifecycle import (
    ReplayCommandLifecycleProfile,
    bind_replay_command_lifecycle,
)
from vantage.replay_command_reader import (
    ReplayCommandReaderProfile,
    bind_replay_command_reader,
)
from vantage.replay_cycle_services import (
    ReplayCycleServicesProfile,
    bind_replay_cycle_services,
)
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
from vantage.replay_world_cycle import ReplayWorldCycleProfile, bind_replay_world_cycle

METRIC, OVERRIDE, OWNED, SPECIAL = 0x1409738C0, 0x140E05160, 0x140E051E0, 0x140E053D0
NOTIFY, HOUSEKEEP, QUEUE, PRIMARY = 0x140E08110, 0x140E0CA00, 0x140E16870, 0x140E169D0
FLAGS, ADMISSION, SUMMARY = 0x140E16E00, 0x140E469E0, 0x140E64A70
LIMIT, CELL, MODE, ROSTER = 0x140E68F60, 0x140E57AC0, 0x140E16880, 0x140E4FD40
ROW_READY, ROW_ACTIVE, DISPATCH = 0x140E50750, 0x140E50490, 0x140DF6100
COUNT, RECORD, LOOKUP, RECORD_ALIAS = 0x1413D3E20, 0x1413D3FA0, 0x140E4FB80, 0x1413D3F30
CLOCK, HOST, FREE, LOG = 0x140E68F80, 0x140A71140, 0x142D6BAB4, 0x14101ADB0
SETTINGS, EXTERNAL, GAME, ROWS = 0x1442DA8A0, 0x1442846F0, 0x144353698, 0x1442DE068
VID, VTOKEN, VOVERRIDE, VSERIAL, VSTREAM, VHOME = (
    0xFE0018,
    0xFE0028,
    0xFE01E0,
    0xFF0018,
    0xFE00E8,
    0xFE00E0,
)
CONCAT, OTHER_CONCAT, IDENTITY = 0xFC0001, 0xFC0002, 0x1234567890
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
        self.manager = self.alloc(0x2700)
        self.queue, self.clock = self.alloc(0x1800), self.alloc(0x200)
        self.descriptor, self.session = self.alloc(8), self.alloc(0x1200)
        self.receiver, self.vtable = self.alloc(8), self.alloc(0x200)
        self.serializer, self.serializer_table = self.alloc(8), self.alloc(0x20)
        self.config, self.config_allocation = self.alloc(16), self.alloc(0x600)
        self.config_data = self.config_allocation + 0x80
        self.game, self.subject, self.output = self.alloc(0x600), self.alloc(0x20), self.alloc(32)
        self.gs, self.vector, self.thread = self.alloc(0x80), self.alloc(16), self.alloc(0x400)
        self.payloads: list[int] = []
        for at, size in (
            (SETTINGS, 8),
            (EXTERNAL, 8),
            (GAME, 8),
            (0x1442DE000, 0x400),
            (0x144355050, 0x20),
            (0x143266E00, 16),
            (0x143DAE440, 8),
            (0x143DADE30, 8),
            (0x144C9C828, 4),
            (0x14319A2F8, 8),
            (0x144287608, 8),
            (0x14326A660, 4),
        ):
            self.mem.map_bytes(at, bytes(size))
        for at, width, value in (
            (SETTINGS, 8, self.manager),
            (EXTERNAL, 8, self.config),
            (GAME, 8, self.game),
            (self.manager + 0x318, 4, 6),
            (self.manager + 0x358, 8, self.clock),
            (self.manager + 0x388, 8, self.queue),
            (self.manager + 0x398, 8, self.descriptor),
            (self.manager + 0xD10, 8, self.session),
            (self.manager + 0xD18, 8, 1),
            (self.manager + 0x2E8, 8, self.receiver),
            (self.receiver, 8, self.vtable),
            (self.serializer, 8, self.serializer_table),
            (self.serializer_table + 0x18, 8, VSERIAL),
            (self.vtable + 0x18, 8, VID),
            (self.vtable + 0x28, 8, VTOKEN),
            (self.vtable + 0x1E0, 8, VOVERRIDE),
            (self.vtable + 0xE8, 8, VSTREAM),
            (self.vtable + 0xE0, 8, VHOME),
            (self.clock + 8, 4, 1),
            (self.clock + 0x30, 4, 100),
            (self.clock + 0x54, 4, 100),
            (self.config, 8, self.config_data),
            (self.session + 0x1148, 8, 8),
            (self.subject + 4, 1, 1),
            (self.subject + 8, 8, self.manager),
            (self.gs + 0x58, 8, self.vector),
            (self.vector, 8, self.thread),
            (self.thread + 0x3B4, 4, 0x80000000),
            (0x1442DE308, 4, 0x80000000),
            (0x1442DE1F0 + 0xB8, 4, 2),
            (0x14319A2F8, 8, CONCAT),
            (0x144355068, 8, 0xABC0),
            (0x144287608, 8, 0xAABBCC),
            (0x14326A660, 4, int.from_bytes(b"%u,\0", "little")),
            (
                0x143266E00,
                16,
                int.from_bytes(bytes.fromhex("04000000050000000600000007000000"), "little"),
            ),
        ):
            self.mem.write(at, width, value)
        for i in range(8):
            self.mem.write(ROWS + i * 0x30 + 0x20, 8, i)
            self.mem.write(self.session + 0x858 + i * 0x118 + 0x48, 8, IDENTITY + i)
        for selector in range(-1, 19):
            self.metric_value(selector, selector + 100, selector + 200)
        self.context = ReplayTaskRebuildStorage(self.manager, self.read, self.write)
        self.ordinary_calls = ReplayTaskRebuildCalls(self.ordinary)
        self.atomics = ReplayUnitAIMapAtomics(self.mem.compare_exchange_u32, self.mem.fetch_add_u32)
        self.runtime = self.mem.runtime_calls(self.ordinary_calls)
        unavailable = ReplayTaskRebuildCalls(None)
        self.lifecycle = bind_replay_command_lifecycle(
            self.context,
            self.ordinary_calls,
            imports=unavailable,
            watson_home_calls=unavailable,
            atomics=self.atomics,
            exchange_byte=None,
            bind_local=self.local,
            profile=ReplayCommandLifecycleProfile(
                bytes(0x160), bytes(0x50), bytes(0x68), bytes(0x78), bytes(0x28), bytes(0x28), None
            ),
        )
        self.reader = bind_replay_command_reader(
            self.context,
            self.ordinary_calls,
            imports=unavailable,
            logger_home_calls=unavailable,
            atomics=self.atomics,
            bind_local=self.local,
            profile=ReplayCommandReaderProfile(bytes(0x58), bytes(0x50), bytes(0x90)),
        )
        self.tuning = bind_replay_cycle_tuning(
            self.context,
            self.ordinary_calls,
            ceil_calls=unavailable,
            virtual_calls=ReplayTaskRebuildCalls(self.channel("virtual_calls")),
            logger_home_calls=unavailable,
            timer_home_calls=unavailable,
            bind_local=self.local,
            profile=ReplayCycleTuningProfile(
                bytes(0x24),
                bytes(0x70),
                bytes(0x98),
                bytes(0x40),
                bytes(0x40),
                bytes(0x44),
                bytes(0x28),
            ),
            mxcsr=0x1F80,
        )
        self.cycle = bind_replay_world_cycle(
            self.context,
            self.ordinary_calls,
            virtual_calls=ReplayTaskRebuildCalls(self.channel("virtual_calls")),
            logger_home_calls=unavailable,
            error_home_calls=unavailable,
            runtime_calls=unavailable,
            atomics=self.atomics,
            bind_local=self.local,
            profile=ReplayWorldCycleProfile(
                bytes(0xF8),
                bytes(0xD8),
                bytes(0x30),
                bytes(0x44),
                bytes(0x14),
                bytes(0x38),
                bytes(0x40),
            ),
        )
        self.batch = bind_replay_command_batch(
            self.context,
            self.ordinary_calls,
            watson_home_calls=unavailable,
            error_home_calls=unavailable,
            atomics=self.atomics,
            bind_local=self.local,
            mxcsr=0x1F80,
            profile=ReplayCommandBatchProfile(bytes(0x28), bytes(0x28), bytes(0x50), bytes(0xB0)),
        )
        self.results = bind_replay_saved_result(
            self.context, self.ordinary_calls, atomics=self.atomics
        )
        self.profile = ReplayCycleServicesProfile(
            *(
                bytes([0xA0 + i]) * size
                for i, size in enumerate(
                    (0x30, 8, 0xB8, 0x38, 0x14, 8, 0x38, 0x40, 0x24, 0x28, 0x90)
                )
            ),
            gs_base=self.gs,
        )
        self.bound = self.bind()

    def alloc(self, size: int) -> int:
        at = self.mem.allocate(size)
        self.mem.fill(at, 0, size)
        return at

    def metric_value(self, selector: int, band: int, current: int) -> None:
        self.mem.write(self.config_data + selector * 48 + 0x28, 4, band & U32)
        self.mem.write(self.config_data + selector * 48 + 0x2C, 4, current & U32)

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
            for name in (
                "imports",
                "virtual_calls",
                "logger_home_calls",
                "error_home_calls",
                "popup_home_calls",
                "send_home_calls",
                "format_calls",
            )
        }
        channels.update(overrides)
        return bind_replay_cycle_services(
            self.context,
            self.ordinary_calls,
            **channels,
            atomics=self.atomics,
            bind_local=self.local,
            profile=self.profile,
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
            if name == "virtual_calls":
                if target == VID:
                    return IDENTITY
                if target == VOVERRIDE:
                    return 0
                if target == VTOKEN:
                    assert args == (self.receiver, 1)
                    return 0xAABBCCDDEEFF0011
                if target == VSERIAL:
                    self.serialize(args)
                    return None
                if target == VSTREAM:
                    return None
            if name == "logger_home_calls" and target == LOG:
                return None
            if name == "error_home_calls" and target == 0x140A08840:
                self.mem.fill(args[0], 0, 0x30)
                return None
            if name == "popup_home_calls" and target == 0x140D6C3D0:
                return None
            if name == "send_home_calls" and target == VHOME:
                return None
            if name == "format_calls" and target == 0x1409002E0:
                self.format(args)
                return None
            if name == "imports" and target in (CONCAT, OTHER_CONCAT):
                self.concatenate(args)
                return None
            raise UnresolvedReplayTaskRebuild(f"unprovided authored {name} service{target:x}")

        return call

    def serialize(self, args: tuple[int, ...]) -> None:
        _, result, descriptor, _ = args
        self.mem.fill(result, 0, 0x30)
        data = self.alloc(16)
        self.mem.write_bytes(data, b"hello")
        self.payloads.append(data)
        self.mem.write(descriptor + 0x10, 8, data)
        self.mem.write(descriptor + 0x18, 8, data + 5)
        self.mem.write(descriptor + 0x20, 8, data + 16)

    def c_string(self, address: int) -> bytes:
        data = bytearray()
        while byte := self.mem.read(address + len(data), 1):
            data.append(byte)
        return bytes(data)

    def format(self, args: tuple[int, ...]) -> None:
        assert self.mem.read_bytes(args[1], 4) == b"%u,\0"
        self.mem.write_bytes(args[0], f"{args[2] & U32},".encode() + b"\0")

    def concatenate(self, args: tuple[int, ...]) -> None:
        joined = self.c_string(args[0]) + self.c_string(args[2])
        assert len(joined) < args[1]
        self.mem.write_bytes(args[0], joined + b"\0")

    def ordinary(self, target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        assert data is None
        handler = self.record_call("calls", target, args)
        if handler:
            return handler(args)
        owners = (
            ((0x140E15890, 0x140E57AB0), self.lifecycle),
            ((CLOCK,), self.reader),
            ((0x140E15A80, 0x140E15A50), self.tuning),
            ((0x140E03790, 0x140E506E0), self.cycle),
            ((0x14098F250, 0x14096B890, 0x1402A8630), self.batch),
            ((0x1402BD7F0,), self.results),
            ((FREE,), self.runtime),
        )
        for targets, owner in owners:
            if target in targets:
                assert owner.call is not None
                return owner.call(target, args, data)
        if target in (
            METRIC,
            OVERRIDE,
            OWNED,
            SPECIAL,
            NOTIFY,
            HOUSEKEEP,
            QUEUE,
            PRIMARY,
            FLAGS,
            ADMISSION,
            SUMMARY,
            LIMIT,
            CELL,
            MODE,
            ROSTER,
            ROW_READY,
            ROW_ACTIVE,
            DISPATCH,
            COUNT,
            RECORD,
            LOOKUP,
            RECORD_ALIAS,
        ):
            assert self.bound.call is not None
            return self.bound.call(target, args, data)
        if target == HOST:
            return 100
        if target == 0x140942110:
            return self.serializer
        if target == 0x142D6E3ED:
            return 0x1122334455667788
        if target == 0x140E462F0:
            return None
        if target in (0x140E46B80, 0x140E46E10):
            return 1
        if target == 0x140AED2D0:
            return 0xDADA
        if target == 0x140AEDA20:
            self.mem.write(args[2], 4, 5)
            return None
        raise UnresolvedReplayTaskRebuild(f"unprovided authored child{target:x}")

    def run(self, target: int, *args: int) -> int | None:
        assert self.bound.call is not None
        return self.bound.call(target, args, None)

    def called(self, target: int, channel: str = "calls") -> list[tuple[int, ...]]:
        return [args for ch, at, args in self.calls if ch == channel and at == target]


@pytest.mark.parametrize(
    "name", [f.name for f in fields(ReplayCycleServicesProfile) if f.name != "gs_base"]
)
def test_profile_requires_exact_immutable_explicit_seed(name: str) -> None:
    r = Rig()
    for value in (b"", bytearray(getattr(r.profile, name))):
        with pytest.raises(ValueError, match="explicit"):
            replace(r.profile, **{name: value})


@pytest.mark.parametrize(
    ("target", "arity"),
    [
        (METRIC, 2),
        (OVERRIDE, 1),
        (OWNED, 1),
        (SPECIAL, 1),
        (NOTIFY, 3),
        (HOUSEKEEP, 1),
        (QUEUE, 1),
        (PRIMARY, 1),
        (FLAGS, 1),
        (ADMISSION, 1),
        (SUMMARY, 1),
        (LIMIT, 1),
        (CELL, 1),
        (MODE, 1),
        (ROSTER, 2),
        (ROW_READY, 1),
        (ROW_ACTIVE, 1),
        (DISPATCH, 4),
        (COUNT, 2),
        (RECORD, 2),
        (LOOKUP, 1),
        (RECORD_ALIAS, 2),
    ],
)
def test_addressed_contract_refuses_bad_shape_before_effects(target: int, arity: int) -> None:
    r = Rig()
    assert r.bound.call is not None
    for args, data in (
        ((0,) * (arity + 1), None),
        ((-1,) + (0,) * (arity - 1), None),
        ((0,) * arity, memoryview(b"raw")),
    ):
        with pytest.raises(ValueError):
            r.bound.call(target, args, data)
    assert not r.events and not r.calls


def test_unknown_calls_preserve_arguments_payload_and_result_identity() -> None:
    r = Rig()
    args, data, result = (1, 2), memoryview(b"opaque"), 123456789012345

    def unknown(target: int, received: tuple[int, ...], payload: memoryview | None) -> int:
        assert target == 42 and received is args and payload is data
        return result

    r.ordinary_calls = ReplayTaskRebuildCalls(unknown)
    bound = r.bind()
    assert bound.call is not None and bound.call(42, args, data) is result


@pytest.mark.parametrize("kind", [0, 1, 2, 3, 4, U32])
@pytest.mark.parametrize("selector", [5, 0xFFFFFFFF])
def test_metric_kind_and_signed_low32_stride(kind: int, selector: int) -> None:
    r = Rig()
    r.mem.write(r.config + 8, 4, kind)
    index = -1 if selector == U32 else selector
    expected = index + (200 if kind == 0 else 100) if kind <= 3 else 0
    assert r.run(METRIC, r.config, (0xABCD << 32) | selector) == expected
    if kind > 3:
        assert r.events == [("r", r.config + 8, 4, kind)]


def test_metric_requires_receiver_and_uses_current_data_after_kind_read() -> None:
    r = Rig()
    with pytest.raises(ReplayMemoryError):
        r.run(METRIC, 0, 0)
    other = r.alloc(0x100)
    r.mem.write(other + 0x2C, 4, 77)

    def mutate(address: int, width: int, value: int) -> None:
        if address == r.config + 8:
            r.mem.write(r.config, 8, other)

    r.after_read = mutate
    assert r.run(METRIC, r.config, 0) == 77


@pytest.mark.parametrize(
    ("mode", "special", "primary"),
    [(0, 0, 0), (3, 0, 0), (4, 0, 1), (6, 0, 1), (7, 1, 1), (8, 1, 1), (10, 0, 0)],
)
def test_mode_predicates_use_source_lists(mode: int, special: int, primary: int) -> None:
    r = Rig()
    r.mem.write(r.manager + 0x318, 4, mode)
    assert r.run(SPECIAL, r.manager) == special
    assert r.run(PRIMARY, r.manager) == primary
    assert r.run(FLAGS, r.manager) == special
    assert r.run(MODE, r.manager) == mode


def test_flags_reload_descriptor_and_short_circuit_before_local_binding() -> None:
    r = Rig()
    other = r.alloc(8)
    r.mem.write(other + 2, 1, 1)

    def mutate(address: int, width: int, value: int) -> None:
        if address == r.descriptor + 1:
            r.mem.write(r.manager + 0x398, 8, other)

    r.after_read = mutate
    assert r.run(FLAGS, r.manager) == 1
    assert not r.snapshots


@pytest.mark.parametrize("mode", [6, 7, 8])
def test_owned_role_uses_actual_session_cell_and_role_record(mode: int) -> None:
    r = Rig()
    r.mem.write(r.manager + 0x318, 4, mode)
    assert r.run(OWNED, r.manager) == int(mode == 6)
    assert r.run(CELL, r.manager + 0xCB8) == r.manager + 0xD10
    if mode != 6:
        assert not r.called(0x140E15A80)


def test_owned_null_session_and_full_qword_identity_are_not_filled_in() -> None:
    r = Rig()
    r.mem.write(r.manager + 0xD10, 8, 0)
    assert r.run(OWNED, r.manager) == 0
    assert not r.snapshots
    r.mem.write(r.manager + 0xD10, 8, r.session)
    r.mem.write(r.manager + 0xD18, 8, 0x100000001)
    assert r.run(OWNED, r.manager) == 0


@pytest.mark.parametrize(
    ("delta", "virtual", "expected"), [(0, 0, 0), (1, 0, 0), (0, 0x100, 1), (2, 0, 1), (U32, 0, 1)]
)
def test_override_unsigned_delta_and_virtual_eax(delta: int, virtual: int, expected: int) -> None:
    r = Rig()
    r.mem.write(r.clock + 0x54, 4, (100 + delta) & U32)
    r.handlers["virtual_calls", VOVERRIDE] = lambda args: virtual
    assert r.run(OVERRIDE, r.manager) == expected
    assert bool(r.called(VOVERRIDE, "virtual_calls")) == (delta <= 1)


def test_override_retains_clock_across_first_getter_callback() -> None:
    r = Rig()
    other = r.alloc(0x200)

    def mutate(address: int, width: int, value: int) -> None:
        if address == r.clock + 0x30:
            r.mem.write(r.manager + 0x358, 8, other)

    r.after_read = mutate
    assert r.run(OVERRIDE, r.manager) == 0
    assert r.mem.read(r.clock + 0x54, 4) == 100
    assert any(kind == "r" and at == r.clock + 0x54 for kind, at, _, _ in r.events)


def test_roster_and_record_getters_use_current_storage_without_bounds_defaults() -> None:
    r = Rig()
    assert r.run(ROSTER, 0xBAD, r.output) == r.output
    assert r.mem.read(r.output, 8) == 8
    r.mem.write(r.output, 8, U64)
    for target in (RECORD, RECORD_ALIAS):
        assert r.run(target, r.session, r.output) == (r.session + 0x858 + U64 * 0x118) & U64
    assert r.run(QUEUE, r.manager) == r.queue
    assert r.run(LIMIT, r.clock) == 100


def test_lookup_session_and_row_predicates_use_exact_record_fields() -> None:
    r = Rig()
    r.mem.write(ROWS + 0x20, 8, 3)
    record = r.session + 0x858 + 3 * 0x118
    r.mem.write(record + 0xB8, 4, 4)
    assert r.run(LOOKUP, ROWS) == record
    assert r.run(ROW_READY, ROWS) == 0
    assert r.run(ROW_ACTIVE, ROWS) == 1
    r.mem.write(record + 0xB8, 4, 2)
    assert r.run(ROW_READY, ROWS) == 1


def test_lookup_signed_epoch_skip_and_actual_initialization_callbacks() -> None:
    r = Rig()
    r.mem.write(r.manager + 0xD10, 8, 0)
    r.mem.write(r.thread + 0x3B4, 4, 0)
    r.mem.write(0x1442DE308, 4, U32)
    assert r.run(LOOKUP, ROWS) == 0x1442DE1F0
    assert not r.called(0x142D6BF80)
    r.mem.write(r.thread + 0x3B4, 4, 0x80000000)
    r.handlers["calls", 0x142D6BF80] = lambda args: r.mem.write(args[0], 4, U32)
    r.handlers["calls", 0x1413E4B20] = lambda args: r.mem.write(args[0] + 0xB8, 4, 4)
    r.handlers["calls", 0x142D6BD04] = lambda args: None
    r.handlers["calls", 0x142D6BF14] = lambda args: r.mem.write(args[0], 4, 1)
    assert r.run(ROW_ACTIVE, ROWS) == 1
    assert r.called(0x142D6BD04) == [(0x143094B70,)]
    order = [target for channel, target, _ in r.calls if channel == "calls"]
    assert order.index(0x142D6BF80) < order.index(0x1413E4B20) < order.index(0x142D6BD04)
    assert order.index(0x142D6BD04) < order.index(0x142D6BF14)


def test_lookup_unavailable_tls_guard_refuses_without_constructor_success() -> None:
    r = Rig()
    r.mem.write(r.manager + 0xD10, 8, 0)
    r.mem.write(0x1442DE308, 4, 0)
    with pytest.raises(UnresolvedReplayTaskRebuild, match="142d6bf80"):
        r.run(LOOKUP, ROWS)
    assert not r.called(0x1413E4B20)
    assert not r.live


def test_summary_builds_unsigned_comma_delimited_current_values() -> None:
    r = Rig()
    for i, kind in enumerate((2, 4, 1, 0, 0, 0, 0, 0)):
        r.mem.write(r.session + 0x858 + i * 0x118 + 0xB8, 4, kind)
    for at, width, value in (
        (ROWS + 8, 8, 1),
        (ROWS + 2 * 0x30 + 8, 8, 1),
        (r.queue + 0x480, 4, U32),
        (r.queue + 0x488, 4, 16),
        (r.queue + 0x414, 4, 7),
        (r.queue + 0x418, 4, 9),
        (r.queue + 0x3E4, 4, 3),
        (r.queue + 0x3F0, 4, 20),
    ):
        r.mem.write(at, width, value)
    assert r.run(SUMMARY, r.queue) == r.queue + 0x7B8
    assert r.c_string(r.queue + 0x7B8) == b"4294967295,16,7,9,3,20,"
    assert len(r.called(0x1409002E0, "format_calls")) == 6


def test_summary_samples_iat_after_formatter_and_clears_only_first_byte_before_refusal() -> None:
    r = Rig()
    r.mem.write(ROWS + 8, 8, 1)
    r.mem.write(r.queue + 0x480, 4, 7)
    r.mem.write_bytes(r.queue + 0x7B8, b"OLD\0")

    def formatter(args: tuple[int, ...]) -> None:
        assert r.mem.read_bytes(r.queue + 0x7B8, 4) == b"\0LD\0"
        r.format(args)
        r.mem.write(0x14319A2F8, 8, OTHER_CONCAT)

    r.handlers["format_calls", 0x1409002E0] = formatter
    r.bound = r.bind(imports=ReplayTaskRebuildCalls(None))
    with pytest.raises(UnresolvedReplayTaskRebuild, match=f"{OTHER_CONCAT:x}"):
        r.run(SUMMARY, r.queue)
    assert r.c_string(r.queue + 0xFB8) == b"7,"


def test_notify_mode2_sparse_packet_result_lifetime_and_current_clock() -> None:
    r = Rig()
    r.mem.write(r.clock + 8, 4, 2)

    def serialize(args: tuple[int, ...]) -> None:
        packet = r.mem.read_bytes(args[3], 12)
        assert packet == bytes.fromhex("53a23412cdaba2a200000000")
        assert r.mem.read(args[2], 8) == 0x143218B60
        r.serialize(args)

    r.handlers["virtual_calls", VSERIAL] = serialize
    assert r.run(NOTIFY, r.manager, 0xABCD1234, 0x1234ABCD) is None
    assert r.called(VSTREAM, "virtual_calls") == [(r.receiver, r.payloads[0], 5)]
    assert r.called(FREE) == [(r.payloads[0], 16)]
    with pytest.raises(ReplayMemoryError):
        r.mem.read(r.payloads[0], 1)
    assert r.mem.read(r.clock + 0x50, 4) == 100
    assert r.mem.read(r.manager + 0x418, 4) == 108
    raw = next(raw for size, raw in r.snapshots if size == 0xB8)
    assert raw[0xA0:0xB8] == bytes(24)
    order = [target for _, target, _ in r.calls]
    assert order.index(0x14096B890) < order.index(0x1402BD7F0) < order.index(VSTREAM)
    assert order.index(VSTREAM) < order.index(HOST) < order.index(FREE)


def test_notify_other_mode_gets_time_before_packet_stores_and_composes_dispatch() -> None:
    r = Rig()

    def clock(args: tuple[int, ...]) -> int:
        frame = r.frame(0xB8)
        if len(r.called(CLOCK)) == 1:
            assert r.mem.read_bytes(frame + 0x80, 12) == bytes([0xA2]) * 12
            r.mem.write(r.clock + 8, 4, 2)
            return U32
        # Common deadline uses the clock mode held before this callback.
        r.mem.write(r.clock + 8, 4, 1)
        return U32

    def serialize(args: tuple[int, ...]) -> None:
        assert r.mem.read(args[3] + 8, 4) == 1
        r.serialize(args)

    r.handlers["calls", CLOCK] = clock
    r.handlers["virtual_calls", VSERIAL] = serialize
    assert r.run(NOTIFY, r.manager, 7, 16) is None
    send = r.called(VHOME, "send_home_calls")[0]
    assert send[:4] == (r.receiver, 0xAABBCCDDEEFF0011, r.payloads[0], 5)
    assert r.mem.read(r.manager + 0x418, 4) == 7
    assert not r.called(VSTREAM, "virtual_calls")
    raw = next(raw for size, raw in r.snapshots if size == 0x90)
    assert raw[0x20:0x28] == b"\0" * 4 + bytes([0xAA]) * 4
    assert raw[0x28:0x30] == b"\x01" + bytes([0xAA]) * 7


@pytest.mark.parametrize("reason", ["no-session", "wrong-mode"])
def test_notify_rejects_without_packet_or_deadline_effects(reason: str) -> None:
    r = Rig()
    if reason == "no-session":
        r.mem.write(r.manager + 0xD10, 8, 0)
    else:
        r.mem.write(r.manager + 0x318, 4, 3)
    assert r.run(NOTIFY, r.manager, 1, 2) is None
    assert not r.called(CLOCK) and not r.called(0x140942110)
    assert r.mem.read(r.manager + 0x418, 4) == 0


def test_dispatch_late_slot_held_vptr_and_sparse_send_homes() -> None:
    r = Rig()
    other = r.alloc(0x200)

    def mutate(address: int, width: int, value: int) -> None:
        if r.live and width == 8 and address == r.frame(0x90) + 0x78:
            r.mem.write(r.receiver, 8, other)
            r.mem.write(r.vtable + 0xE0, 8, 0xEE00E0)

    def send(args: tuple[int, ...]) -> None:
        assert args[:4] == (r.receiver, 0xAABBCCDDEEFF0011, r.payloads[0], 5)
        assert r.mem.read_bytes(args[4], 8) == bytes.fromhex("78563412aaaaaaaa")
        assert r.mem.read_bytes(args[5], 8) == bytes.fromhex("feaaaaaaaaaaaaaa")

    r.after_read = mutate
    r.handlers["send_home_calls", 0xEE00E0] = send
    assert r.run(DISPATCH, r.manager, r.output, 0xABCDEF0012345678, 0xFFFE) is None
    assert r.called(0xEE00E0, "send_home_calls")
    assert not r.called(VHOME, "send_home_calls")
    assert not r.live


def test_dispatch_releases_actual_result_control_then_frees_owned_vector() -> None:
    r = Rig()
    control, table, replacement = r.alloc(16), r.alloc(16), r.alloc(16)
    for at, width, value in (
        (control, 8, table),
        (control + 8, 4, 1),
        (control + 12, 4, 1),
        (table, 8, 0xEE00),
        (replacement + 8, 8, 0xEE08),
    ):
        r.mem.write(at, width, value)

    def serialize(args: tuple[int, ...]) -> None:
        r.serialize(args)
        r.mem.write(args[1] + 0x20, 8, control)

    r.handlers["virtual_calls", VSERIAL] = serialize
    r.handlers["virtual_calls", 0xEE00] = lambda args: r.mem.write(control, 8, replacement)
    r.handlers["virtual_calls", 0xEE08] = lambda args: None
    assert r.run(DISPATCH, r.manager, r.output, 0, 0) is None
    assert r.called(0xEE00, "virtual_calls") == [(control,)]
    assert r.called(0xEE08, "virtual_calls") == [(control,)]
    assert r.mem.read(control + 8, 8) == 0
    assert len(r.called(FREE)) == 1


def test_missing_serializer_uses_live_error_homes_then_partial_send_stores() -> None:
    r = Rig()
    r.handlers["calls", 0x140942110] = lambda args: 0

    def error(args: tuple[int, ...]) -> None:
        assert args[1:4] == (0, 0x1431FAC00, 0x2F5)
        assert r.mem.read(args[4], 8) == 0x1431FAC58
        assert r.mem.read(args[5], 8) == 0x1122334455667788
        r.mem.fill(args[0], 0, 0x30)

    def send(args: tuple[int, ...]) -> None:
        assert args[2:4] == (0, 0)
        assert r.mem.read(args[4], 8) == 0x100000001
        assert r.mem.read(args[5], 8) == 0x1122334455667702

    r.handlers["error_home_calls", 0x140A08840] = error
    r.handlers["send_home_calls", VHOME] = send
    assert r.run(DISPATCH, r.manager, r.output, 1, 2) is None
    assert not r.called(FREE)


@pytest.mark.parametrize("channel", ["virtual_calls", "error_home_calls", "send_home_calls"])
def test_missing_publication_category_refuses_at_reached_prefix(channel: str) -> None:
    r = Rig()
    if channel == "error_home_calls":
        r.handlers["calls", 0x140942110] = lambda args: 0
    r.bound = r.bind(**{channel: ReplayTaskRebuildCalls(None)})
    with pytest.raises(UnresolvedReplayTaskRebuild):
        r.run(DISPATCH, r.manager, r.output, 1, 1)
    assert not r.called(FREE)
    assert not r.live


def test_housekeeping_mode2_threshold_popup_homes_and_held_initial_time() -> None:
    r = Rig()
    r.mem.write(r.clock + 8, 4, 2)
    r.mem.write(r.clock + 0x54, 4, 500)
    r.metric_value(16, 0, 399)
    r.metric_value(17, 0, 199)
    ticks = iter((100, 200, 300))
    r.handlers["calls", HOST] = lambda args: next(ticks)

    def popup(args: tuple[int, ...]) -> None:
        assert args[:4] == (r.game, 0x9D, 0, 0)
        for home in args[4:]:
            assert r.mem.read_bytes(home, 8) == bytes(4) + bytes([0xA3]) * 4

    r.handlers["popup_home_calls", 0x140D6C3D0] = popup
    assert r.run(HOUSEKEEP, r.manager) is None
    assert r.mem.read(r.manager + 0x2590, 4) == 300
    assert r.mem.read(r.manager + 0x2594, 4) == 100


@pytest.mark.parametrize(
    ("distance", "elapsed", "expected_calls"), [(400, 201, 1), (401, 200, 2), (401, 201, 3)]
)
def test_housekeeping_mode2_thresholds_are_strict(
    distance: int, elapsed: int, expected_calls: int
) -> None:
    r = Rig()
    r.mem.write(r.clock + 8, 4, 2)
    r.mem.write(r.clock + 0x54, 4, 100 + distance)
    r.metric_value(16, 0, 400)
    r.metric_value(17, 0, 200)
    ticks = iter((100, elapsed, 300))
    r.handlers["calls", HOST] = lambda args: next(ticks)
    r.run(HOUSEKEEP, r.manager)
    assert len(r.called(HOST)) == expected_calls
    assert bool(r.called(0x140D6C3D0, "popup_home_calls")) == (expected_calls == 3)


@pytest.mark.parametrize(
    ("elapsed", "old_elapsed", "expected"),
    [(15000, 50000, 100000), (14999, 45000, 55000), (14999, 45001, 0)],
)
def test_housekeeping_warning_timer_boundaries(
    elapsed: int, old_elapsed: int, expected: int
) -> None:
    r = Rig()
    r.handlers["calls", HOST] = lambda args: 100000
    r.mem.write(r.manager + 0x2594, 4, 100000 - elapsed)
    r.mem.write(r.manager + 0x2598, 4, 100000 - old_elapsed)
    r.mem.write(r.session + 0x1148, 8, 0)
    r.run(HOUSEKEEP, r.manager)
    assert r.mem.read(r.manager + 0x2598, 4) == expected
    assert r.mem.read(r.manager + 0x2594, 4) == 100000


@pytest.mark.parametrize("answer", [0x100000001, 0x100000000, 2])
def test_housekeeping_roster_requires_low_eax_one(answer: int) -> None:
    r = Rig()
    for at, width, value in (
        (r.manager + 0x318, 4, 8),
        (r.manager + 0x2594, 4, 99000),
        (r.manager + 0x2598, 4, 1),
        (r.session + 0x1148, 8, 1),
        (r.session + 0x858 + 0xB8, 4, 2),
        (ROWS + 8, 8, r.receiver),
    ):
        r.mem.write(at, width, value)
    r.handlers["calls", HOST] = lambda args: 100000
    r.handlers["virtual_calls", VID] = lambda args: answer
    r.run(HOUSEKEEP, r.manager)
    assert r.called(VID, "virtual_calls") == [(r.receiver,)]
    assert r.mem.read(r.manager + 0x2598, 4) == (0 if answer & U32 == 1 else 1)
    assert r.mem.read(r.manager + 0x2594, 4) == 100000


def test_housekeeping_missing_popup_preserves_prefix_without_final_timestamp() -> None:
    r = Rig()
    r.mem.write(r.clock + 8, 4, 2)
    r.mem.write(r.clock + 0x54, 4, 500)
    r.metric_value(16, 0, 0)
    r.metric_value(17, 0, 0)
    r.bound = r.bind(popup_home_calls=ReplayTaskRebuildCalls(None))
    with pytest.raises(UnresolvedReplayTaskRebuild):
        r.run(HOUSEKEEP, r.manager)
    assert r.mem.read(r.manager + 0x2590, 4) == 0
    assert r.mem.read(r.manager + 0x2594, 4) == 0
    assert len(r.called(HOST)) == 2


@pytest.mark.parametrize("reason", ["no-session", "mode-zero", "policy-reject"])
def test_admission_resets_before_early_rejection_without_flag_clear(reason: str) -> None:
    r = Rig()
    if reason == "no-session":
        r.mem.write(r.manager + 0xD10, 8, 0)
    elif reason == "mode-zero":
        r.mem.write(r.manager + 0x318, 4, 0)
    else:
        r.handlers["calls", 0x140AEDA20] = lambda args: r.mem.write(args[2], 4, 7)
        r.handlers["calls", 0x140E46B80] = lambda args: 0x100
    assert r.run(ADMISSION, r.subject) == 0
    assert r.calls[0] == ("calls", 0x140E462F0, (r.subject,))
    assert r.mem.read(r.subject + 4, 1) == 1


def test_admission_resamples_registry_but_does_not_reset_choice_home() -> None:
    r = Rig()
    registries = iter((0x100, 0x200))
    r.handlers["calls", 0x140AED2D0] = lambda args: next(registries)

    def query(args: tuple[int, ...]) -> None:
        if args[0] == 0x100:
            assert r.mem.read(args[2], 4) == 8
            r.mem.write(args[2], 4, 7)
        else:
            assert args[0] == 0x200 and r.mem.read(args[2], 4) == 7

    r.handlers["calls", 0x140AEDA20] = query
    assert r.run(ADMISSION, r.subject) == 1
    assert r.mem.read(r.subject + 4, 1) == 1
    assert not r.called(0x140E46E10)


@pytest.mark.parametrize("result", [0, 1, 2])
def test_admission_preserves_low_byte_result_and_clears_flag(result: int) -> None:
    r = Rig()
    r.mem.write(r.manager + 0x318, 4, 8)
    r.handlers["calls", 0x140E46E10] = lambda args: 0x100 | result
    assert r.run(ADMISSION, r.subject) == result
    assert r.mem.read(r.subject + 4, 1) == 0


@pytest.mark.parametrize(
    ("mode", "expected", "format_address"), [(3, 0, 0x1432689A0), (8, 1, 0x1432689C0)]
)
def test_admission_log_homes_live_before_flag_clear(
    mode: int, expected: int, format_address: int
) -> None:
    r = Rig()
    r.mem.write(r.manager + 0x318, 4, mode)
    r.mem.write(0x144355057, 1, 1)

    def logger(args: tuple[int, ...]) -> None:
        assert args[:4] == (0xABC0, 0x1F, format_address, 0)
        assert r.mem.read(args[4], 8) == 0
        assert r.mem.read(r.subject + 4, 1) == 1

    r.handlers["logger_home_calls", LOG] = logger
    assert r.run(ADMISSION, r.subject) == expected
    assert r.mem.read(r.subject + 4, 1) == 0


def test_missing_logger_refuses_before_admission_flag_clear() -> None:
    r = Rig()
    r.mem.write(0x144355057, 1, 1)
    r.bound = r.bind(logger_home_calls=ReplayTaskRebuildCalls(None))
    with pytest.raises(UnresolvedReplayTaskRebuild):
        r.run(ADMISSION, r.subject)
    assert r.mem.read(r.subject + 4, 1) == 1


def test_binding_refuses_nonservice_objects_and_host_gs_inference() -> None:
    r = Rig()
    with pytest.raises(ValueError):
        r.bind(format_calls=cast(ReplayTaskRebuildCalls, None))
    for value in (True, -1, 1 << 64):
        with pytest.raises(ValueError):
            replace(r.profile, gs_base=value)
    assert not r.events
