"""Owned-storage source controls for Action and its concrete controllers.

Object methods, lookups and notification effects are authored capabilities;
composite controls separately use actual Base/Moving/motion/clock ports.
No original instructions or real recording World are executed here.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import fields, replace
from pathlib import Path
from typing import cast

import pytest

from vantage.replay_action_object_update import (
    ReplayActionObjectUpdateProfile,
    bind_replay_action_object_update,
)
from vantage.replay_base_object_update import (
    ReplayBaseObjectUpdateProfile,
    bind_replay_base_object_update,
)
from vantage.replay_clock_storage import bind_replay_clock_storage
from vantage.replay_command_reader import (
    ReplayCommandReaderProfile,
    bind_replay_command_reader,
)
from vantage.replay_memory import ReplayMemory, ReplayMemoryError
from vantage.replay_moving_update import (
    ReplayMovingUpdateProfile,
    bind_replay_moving_update,
)
from vantage.replay_object_update import (
    ReplayObjectUpdateProfile,
    bind_replay_object_update,
)
from vantage.replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
)
from vantage.replay_unit_ai_map import ReplayUnitAIMapAtomics
from vantage.replay_unit_ai_variants import (
    ReplayUnitAIVariantScratch,
    bind_replay_unit_ai_variants,
)

ACTION, CLEAR, CANCEL, POP, QUERY = (
    0x1411399A0,
    0x140B88A20,
    0x140B88B90,
    0x140B893D0,
    0x140B899F0,
)
WORKER, NOTIFY, PAUSE, ABORT, CLEANUP = (
    0x141140430,
    0x141226E30,
    0x140B68080,
    0x140B68090,
    0x140B680B0,
)
MOVING, BASE, CLOCK, LOOKUP, NAME, LOG = (
    0x14120E560,
    0x141249740,
    0x1416041F0,
    0x141617DB0,
    0x140A4B870,
    0x14101ADB0,
)
DESTROY, RESUME, UPDATE, DETACH, RELEASE, TASK, ACTIVE, KIND = (
    0xFF0000,
    0xFF0028,
    0xFF0030,
    0xFF0068,
    0xF00190,
    0xF008A8,
    0xF002E8,
    0xF00610,
)
FREE_IMPORT, OTHER_FREE = 0xFE0001, 0xFE0002
U32, U64 = (1 << 32) - 1, (1 << 64) - 1
MA, MB = 0x6A586EB28AC201FC, 0x0CF19788B2554E70
A, B, C, D = 0x6AE24D3352F04511, 0xC22D6B496D833977, 0x042AC42976FCCEF5, 0xA9834B738A7DD167
DATA = Path(__file__).resolve().parents[1] / "artifacts/game-internals/2026-10-18-world-envelope"
Handler = Callable[[tuple[int, ...]], int | None]


def encoded(value: int) -> int:
    return ((((value ^ D) + C) & U64) ^ B) ^ A


def decoded(value: int) -> int:
    return (((value ^ A ^ B) - C) & U64) ^ D


class Rig:
    def __init__(self) -> None:
        self.mem = ReplayMemory()
        self.events: list[tuple[str, int, int, int]] = []
        self.calls: list[tuple[str, int, tuple[int, ...]]] = []
        self.handlers: dict[tuple[str, int], Handler] = {}
        self.live: list[tuple[int, int]] = []
        self.snapshots: list[tuple[int, bytes]] = []
        self.statuses: dict[int, int] = {}
        self.after_read: Callable[[int, int, int], None] | None = None
        self.after_write: Callable[[int, int, int], None] | None = None
        self.real_parent = False
        self.parent_result = 0
        self.obj, self.owner, self.world = self.alloc(0xA00), self.alloc(0xA00), self.alloc(0x300)
        self.clock, self.master, self.resource = (
            self.alloc(0x200),
            self.alloc(0x600),
            self.alloc(0x900),
        )
        self.table, self.action_table = self.alloc(0x900), self.alloc(0x80)
        self.other, self.animation, self.anim_table = (
            self.alloc(0xA00),
            self.alloc(8),
            self.alloc(0x50),
        )
        self.game, self.name, self.motion = self.alloc(0x700), self.alloc(8), self.alloc(24)
        self.stack = self.alloc(0x20)
        for at, size in (
            (0x144353698, 8),
            (0x1443563C0, 8),
            (0x144355050, 0x20),
            (0x143199DD0, 8),
            (0x14435A264, 4),
        ):
            self.mem.map_bytes(at, bytes(size))
        files = (
            ("action-object-update-source-v1/worker-scale-1436a02f8.bin", 0x1436A02F8),
            ("base-object-update-source-v1/state-jump-table-14124aa10.bin", 0x14124AA10),
            ("base-object-update-source-v1/threshold-1436a0294.bin", 0x1436A0294),
            ("object-virtual-update-source-v1/sqrt-table-143218010.bin", 0x143218010),
            ("object-virtual-update-source-v1/sqrt-normalize-143217ea0.bin", 0x143217EA0),
            ("object-virtual-update-source-v1/moving-threshold-1431fe590.bin", 0x1431FE590),
        )
        for file, at in files:
            self.mem.map_bytes(at, (DATA / file).read_bytes())
        for at, width, value in (
            (self.obj, 8, self.table),
            (self.obj + 8, 4, 100),
            (self.obj + 0x10, 8, (self.master + MA + MB) & U64),
            (self.obj + 0x18, 8, self.owner),
            (self.obj + 0x28, 8, self.animation),
            (self.obj + 0x188, 1, 1),
            (self.obj + 0x198, 4, 100),
            (self.obj + 0x420, 8, self.stack),
            (self.obj + 0x42A, 2, 0xFFFF),
            (self.obj + 0x430, 4, 123),
            (self.obj + 0x434, 4, 99),
            (self.obj + 0x3A0, 4, U32),
            (self.owner + 8, 8, self.world),
            (self.owner + 0x10, 4, 3),
            (self.owner + 0x98, 8, self.resource),
            (self.world + 0x228, 8, self.clock),
            (self.world + 0x7C, 4, 7),
            (self.world + 0x164, 4, 0x3E800000),
            (self.clock + 0x18, 4, 100),
            (self.stack + 8, 8, self.obj),
            (self.master + 0x230, 2, 0xFFFF),
            (self.animation, 8, self.anim_table),
            (self.anim_table + 0x10, 8, 0xFA0010),
            (self.other, 8, self.table),
            (self.name, 8, 0x12345678),
            (self.resource + 0x800, 8, encoded(0x40000000)),
            (self.resource + 0x7D0, 8, encoded(0)),
            (self.resource + 0x7C8, 8, encoded(0)),
            (self.game + 0x5C0, 8, self.world),
            (0x144353698, 8, self.game),
            (0x1443563C0, 8, 0xBBB0),
            (0x143199DD0, 8, FREE_IMPORT),
            (0x144355068, 8, 0xABC0),
            (self.motion + 8, 4, 0x3F800000),
            (self.motion + 0x14, 4, 0x40000000),
            (self.obj + 0x130, 8, ((0x3F800000 + 0x147B5E081EC087D9) & U64) ^ 0x0F2A55F7A61DD00E),
        ):
            self.mem.write(at, width, value)
        self.mem.write(self.obj + 0x170, 8, (-0x4C3FBA69E4EA7FD1 + 0x183CAC30D2441D0E) & U64)
        self.mem.write(self.obj + 0x178, 8, (-0x6C5EAB60B426DD28 + 0x61501AA6ECFD980A) & U64)
        self.mem.write(self.obj + 0x180, 8, (-0x21D14A25ED7C802C - 0x2B3719EF44DE99FF) & U64)
        self.kind(0)
        self.object_class(0)
        for slot, target in (
            (0x8A8, TASK),
            (0x2E8, ACTIVE),
            (0x610, KIND),
            (0x190, RELEASE),
            (0x620, 0xF00620),
            (0x568, 0xF00568),
            (0x628, 0xF00628),
            (0x5F8, 0xF005F8),
            (0x600, 0xF00600),
        ):
            self.mem.write(self.table + slot, 8, target)
        for slot, target in ((0, DESTROY), (0x28, RESUME), (0x30, UPDATE), (0x68, DETACH)):
            self.mem.write(self.action_table + slot, 8, target)
        self.context = ReplayTaskRebuildStorage(self.obj, self.read, self.write)
        self.ordinary_calls = ReplayTaskRebuildCalls(self.ordinary)
        self.runtime = self.mem.runtime_calls(self.ordinary_calls)
        self.clock_body = bind_replay_clock_storage(self.context, self.ordinary_calls, mxcsr=0x1F80)
        unavailable = ReplayTaskRebuildCalls(None)
        atomics = ReplayUnitAIMapAtomics(self.mem.compare_exchange_u32, self.mem.fetch_add_u32)
        self.reader = bind_replay_command_reader(
            self.context,
            self.ordinary_calls,
            imports=unavailable,
            logger_home_calls=unavailable,
            atomics=atomics,
            bind_local=self.local,
            profile=ReplayCommandReaderProfile(bytes(0x58), bytes(0x50), bytes(0x90)),
        )
        self.variants = bind_replay_unit_ai_variants(
            self.context,
            self.ordinary_calls,
            atomics=atomics,
            bind_local=self.local,
            scratch=ReplayUnitAIVariantScratch(bytes(0x140), bytes(0xC0), bytes(0xD0)),
        )
        self.base = bind_replay_base_object_update(
            self.context,
            self.ordinary_calls,
            virtual_calls=ReplayTaskRebuildCalls(self.channel("virtual_calls")),
            logger_home_calls=unavailable,
            position_fp_home_calls=unavailable,
            rtti_home_calls=unavailable,
            bind_local=self.local,
            mxcsr=0x1F80,
            profile=ReplayBaseObjectUpdateProfile(bytes(0xC0)),
        )
        self.moving = bind_replay_moving_update(
            self.context,
            self.ordinary_calls,
            virtual_calls=ReplayTaskRebuildCalls(self.channel("virtual_calls")),
            scalar_fp_calls=ReplayTaskRebuildCalls(self.channel("scalar_fp_calls")),
            motion_fp_calls=ReplayTaskRebuildCalls(self.channel("motion_fp_calls")),
            virtual_fp_calls=ReplayTaskRebuildCalls(self.channel("virtual_fp_calls")),
            virtual_fp_home_calls=ReplayTaskRebuildCalls(self.channel("virtual_fp_home_calls")),
            logger_home_calls=ReplayTaskRebuildCalls(self.channel("motion_logger")),
            bind_local=self.local,
            mxcsr=0x1F80,
            profile=ReplayMovingUpdateProfile(bytes(0x40), bytes(0x48), bytes(0xF0)),
        )
        self.profile = ReplayActionObjectUpdateProfile(
            bytes([0xA1]) * 0x90, bytes([0xA2]) * 0x48, bytes([0xA3]) * 0x38
        )
        self.bound = self.bind()

    def alloc(self, size: int) -> int:
        at = self.mem.allocate(size)
        self.mem.fill(at, 0, size)
        return at

    def kind(self, value: int) -> None:
        self.mem.write(
            self.master + 0x18, 8, ((value + 0x47E37DFF0616CE4F) & U64) ^ 0x349E37847AD69F19
        )

    def object_class(self, value: int) -> None:
        self.mem.write(
            self.master + 0x38, 8, (value - 0x5B32AA7995D95916 + 0x50A06BCECEBEF905) & U64
        )

    def nodes(self, statuses: list[int]) -> tuple[list[int], list[int]]:
        nodes, actions = [], []
        for status in statuses:
            node, action = self.alloc(16), self.alloc(0x80)
            self.mem.write(action, 8, self.action_table)
            self.mem.write(action + 0x10, 8, self.obj)
            self.mem.write(action + 0x34, 4, U32)
            self.statuses[action] = status
            self.mem.write(node, 8, action)
            if nodes:
                self.mem.write(nodes[-1] + 8, 8, node)
            nodes.append(node)
            actions.append(action)
        self.mem.write(self.stack + 0x10, 8, nodes[0] if nodes else 0)
        return nodes, actions

    def read(self, at: int, width: int) -> int:
        value = self.mem.read(at, width)
        self.events.append(("r", at, width, value))
        if self.after_read:
            self.after_read(at, width, value)
        return value

    def write(self, at: int, width: int, value: int) -> None:
        self.mem.write(at, width, value)
        self.events.append(("w", at, width, value))
        if self.after_write:
            self.after_write(at, width, value)

    @contextmanager
    def local(self, view: memoryview) -> Iterator[int]:
        with self.mem.bind_local(view) as at:
            self.live.append((len(view), at))
            try:
                yield at
            finally:
                self.snapshots.append((len(view), bytes(view)))
                self.live.pop()

    def frame(self, size: int) -> int:
        return next(at for length, at in reversed(self.live) if length == size)

    def bind(self, **overrides: ReplayTaskRebuildCalls) -> ReplayTaskRebuildCalls:
        channels = {
            key: ReplayTaskRebuildCalls(self.channel(key))
            for key in ("virtual_calls", "imports", "logger_home_calls", "scalar_fp_calls")
        }
        channels.update(overrides)
        return bind_replay_action_object_update(
            self.context,
            self.ordinary_calls,
            **channels,
            bind_local=self.local,
            profile=self.profile,
            mxcsr=0x1F80,
        )

    def record(self, channel: str, target: int, args: tuple[int, ...]) -> Handler | None:
        self.calls.append((channel, target, args))
        self.events.append(("call", target, 0, len(self.calls)))
        return self.handlers.get((channel, target))

    def channel(
        self, channel: str
    ) -> Callable[[int, tuple[int, ...], memoryview | None], int | None]:
        def dispatch(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
            assert data is None
            if handler := self.record(channel, target, args):
                return handler(args)
            if channel == "virtual_calls":
                if target == DESTROY:
                    assert args[1] == 1 and self.runtime.call is not None
                    return self.runtime.call(0x142D6BAB4, (args[0], 0x80), None)
                if target in (RESUME, DETACH, TASK, RELEASE, 0xF00600):
                    return None
                if target == UPDATE:
                    return self.statuses[args[0]]
                if target in (ACTIVE, KIND):
                    return 1
                if target == 0xF00620:
                    return 0
                if target == 0xF00568:
                    self.mem.fill(args[1], 0, 12)
                    return args[1]
            if channel == "imports" and target in (FREE_IMPORT, OTHER_FREE):
                assert self.runtime.call is not None
                return self.runtime.call(0x142D6BAB4, args, None)
            if channel == "logger_home_calls" and target == LOG:
                return None
            if channel == "scalar_fp_calls":
                if target == 0x14124E840:
                    return 0x3F800000
                if target in (0x140A82E00, 0x141604200):
                    assert self.moving.call is not None
                    return self.moving.call(target, args, None)
            if channel == "motion_fp_calls" and target == 0x141075310:
                assert self.moving.call is not None
                return self.moving.call(target, args, None)
            if channel == "virtual_fp_calls" and target in (0xF005F8, 0xFA0010):
                return None
            if channel == "virtual_fp_home_calls" and target == 0xF00628:
                return 0x40400000
            if channel == "motion_logger" and target == 0x140B6EF80:
                return None
            raise UnresolvedReplayTaskRebuild(f"authored {channel} missing{target:x}")

        return dispatch

    def ordinary(self, target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        assert data is None
        if handler := self.record("calls", target, args):
            return handler(args)
        if target == CLOCK:
            assert self.reader.call is not None
            return self.reader.call(target, args, None)
        if target == 0x140E68F70:
            assert self.clock_body.call is not None
            return self.clock_body.call(target, args, None)
        if target in (0x14172AC80, 0x140D6ACC0):
            assert self.variants.call is not None
            return self.variants.call(target, args, None)
        if target == MOVING:
            if self.real_parent:
                assert self.moving.call is not None
                return self.moving.call(target, args, None)
            return self.parent_result
        if target == BASE:
            assert self.base.call is not None
            return self.base.call(target, args, None)
        if target == NAME:
            return self.name
        if target == LOOKUP:
            return 0
        if target == 0x140D6A880:
            return None
        if target == 0x141121110:
            return 0xABCDEF012345
        raise UnresolvedReplayTaskRebuild(f"authored child missing{target:x}")

    def run(self, target: int = ACTION, obj: int | None = None) -> int | None:
        assert self.bound.call is not None
        return self.bound.call(target, (self.obj if obj is None else obj,), None)

    def called(self, target: int, channel: str = "calls") -> list[tuple[int, ...]]:
        return [args for key, at, args in self.calls if key == channel and at == target]


@pytest.mark.parametrize("field", [f.name for f in fields(ReplayActionObjectUpdateProfile)])
def test_explicit_immutable_prefixes(field: str) -> None:
    r = Rig()
    for value in (b"", bytearray(getattr(r.profile, field))):
        with pytest.raises(ValueError):
            replace(r.profile, **{field: value})


@pytest.mark.parametrize(
    "target", [ACTION, CLEAR, CANCEL, POP, QUERY, WORKER, NOTIFY, PAUSE, ABORT, CLEANUP]
)
def test_bad_addressed_shape_refuses_before_effects(target: int) -> None:
    r = Rig()
    assert r.bound.call is not None
    for args, data in (((), None), ((-1,), None), ((r.obj,), memoryview(b"raw"))):
        with pytest.raises(ValueError):
            r.bound.call(target, args, data)
    assert not r.events


def test_unknown_calls_preserve_identity() -> None:
    r = Rig()
    args, data, result = (-1, 2), memoryview(b"raw"), 123456789012345

    def unknown(target: int, given: tuple[int, ...], payload: memoryview | None) -> int:
        assert target == 42 and given is args and payload is data
        return result

    r.ordinary_calls = ReplayTaskRebuildCalls(unknown)
    bound = r.bind()
    assert bound.call is not None and bound.call(42, args, data) is result


def test_initial_name_clock_and_clear_precede_parent_and_hold_return() -> None:
    r = Rig()
    r.parent_result = 0x1234000000FE

    def parent(args: tuple[int, ...]) -> int:
        assert r.called(NAME) and r.called(CLOCK)
        assert r.mem.read(r.obj + 0x42A, 2) == 0
        return r.parent_result

    r.handlers["calls", MOVING] = parent
    assert r.run() == 254
    assert r.called(0x141121110) == [(0xBBB0, r.obj, 0x10)]


def test_initial_name_dereference_keeps_owner_read_before_it() -> None:
    r = Rig()
    other_owner, other_world = r.alloc(0xA00), r.alloc(0x300)
    r.mem.write(other_owner + 8, 8, other_world)
    r.mem.write(other_owner + 0x98, 8, r.resource)
    r.mem.write(other_world + 0x228, 8, r.clock)

    def mutate(at: int, width: int, value: int) -> None:
        if at == r.name:
            r.mem.write(r.obj + 0x18, 8, other_owner)

    r.after_read = mutate
    r.run()
    assert r.called(CLOCK)[0] == (r.world,)


def test_missing_moving_annotation_refuses_after_next_master_load() -> None:
    r = Rig()
    r.handlers["calls", MOVING] = lambda args: None
    with pytest.raises(ValueError, match="Moving update AL"):
        r.run()
    parent = next(i for i, e in enumerate(r.events) if e[:2] == ("call", MOVING))
    assert r.events[parent + 1] == ("r", r.obj + 0x10, 8, (r.master + MA + MB) & U64)
    assert not r.called(LOOKUP) and not r.live


def test_initial_log_uses_partial_typed_nodes_and_held_logger() -> None:
    r = Rig()
    r.mem.write(0x14435505B, 1, 1)

    def mutate(at: int, width: int, value: int) -> None:
        if r.live and at == r.frame(0x90) + 0x40 and width == 4:
            r.mem.write(0x144355068, 8, 0xEEEE)

    def logger(args: tuple[int, ...]) -> None:
        if args[2] == 0x1432A6290:
            assert args[:4] == (0xABC0, 0x23, 0x1432A6290, 4)
            array = r.mem.read(args[4], 8)
            nodes = [r.mem.read(array + i * 8, 8) for i in range(4)]
            assert [r.mem.read(at + 8, 4) for at in nodes] == [5, 7, 10, 15]
            assert r.mem.read(nodes[0], 1) == 1
            assert r.mem.read(nodes[1], 4) == 100
            assert r.mem.read(nodes[3], 8) == 0x12345678

    r.after_write = mutate
    r.handlers["logger_home_calls", LOG] = logger
    r.run()


@pytest.mark.parametrize(
    ("kind", "state", "cleared"), [(0, 3, True), (0x114, 3, False), (0x114, 6, True), (0, 2, False)]
)
def test_type_specific_state_threshold(kind: int, state: int, cleared: bool) -> None:
    r = Rig()
    r.kind(kind)
    r.mem.write(r.obj + 0x188, 1, state)
    nodes, _ = r.nodes([0])
    r.run()
    assert r.mem.read(r.stack + 0x10, 8) == (0 if cleared else nodes[0])


@pytest.mark.parametrize("status", [0, 1, 2, 3, 4, 0x100000003])
def test_action_query_only_one_or_three_pops(status: int) -> None:
    r = Rig()
    nodes, _ = r.nodes([status])
    r.run()
    assert r.mem.read(r.stack + 0x10, 8) == (0 if status & 255 in (1, 3) else nodes[0])


def test_default_task_id_is_held_across_log_and_uses_late_vptr_slot() -> None:
    r = Rig()
    r.mem.write(r.obj + 0x188, 1, 2)
    r.mem.write(r.master + 0x230, 2, 77)
    r.mem.write(0x14435505B, 1, 1)

    def logger(args: tuple[int, ...]) -> None:
        if args[2] == 0x1432A6350:
            r.mem.write(r.master + 0x230, 2, 88)
            r.mem.write(r.table + 0x8A8, 8, 0xEE08A8)

    r.handlers["logger_home_calls", LOG] = logger
    r.handlers["virtual_calls", 0xEE08A8] = lambda args: None
    r.run()
    assert r.called(0xEE08A8, "virtual_calls") == [(r.obj, 77)]


def test_clear_frees_real_nodes_and_actions_and_resumes_each_next_node() -> None:
    r = Rig()
    nodes, actions = r.nodes([0, 0, 0])
    assert r.run(CLEAR, r.stack) is None
    assert r.mem.read(r.stack + 0x10, 8) == 0
    assert r.called(FREE_IMPORT, "imports") == [(at,) for at in nodes]
    assert r.called(RESUME, "virtual_calls") == [(at, 0) for at in actions[1:]]
    for at in nodes + actions:
        with pytest.raises(ReplayMemoryError):
            r.mem.read(at, 1)


def test_pop_reads_current_iat_after_destructor_and_current_head_after_free() -> None:
    r = Rig()
    nodes, actions = r.nodes([0, 0])

    def destroy(args: tuple[int, ...]) -> None:
        assert r.mem.read(r.stack + 0x10, 8) == nodes[1]
        r.mem.write(0x143199DD0, 8, OTHER_FREE)

    r.handlers["virtual_calls", DESTROY] = destroy
    r.run(POP, r.stack)
    assert r.called(OTHER_FREE, "imports") == [(nodes[0],)]
    assert not r.called(FREE_IMPORT, "imports")
    assert r.called(RESUME, "virtual_calls") == [(actions[1], 0)]


def test_query_holds_top_status_while_actual_cleanup_clears_subordinate_reference() -> None:
    r = Rig()
    _, actions = r.nodes([0x100000005, 0])
    r.mem.write(r.other + 0x188, 1, 7)
    r.mem.write(actions[1] + 0x28, 8, r.other)
    r.mem.write(actions[1] + 0x34, 4, 77)
    assert r.run(QUERY, r.stack) == 5
    assert r.mem.read(actions[1] + 0x28, 8) == 0
    assert r.mem.read(actions[1] + 0x34, 4) == U32
    assert not r.called(DESTROY, "virtual_calls")


def test_cancel_calls_actual_cleanup_wrappers_then_removes_current_head() -> None:
    r = Rig()
    nodes, actions = r.nodes([0, 0])
    r.mem.write(r.other + 0x188, 1, 7)
    for action in actions:
        r.mem.write(action + 0x28, 8, r.other)
    assert r.run(CANCEL, r.stack) == 1
    assert r.mem.read(r.stack + 0x10, 8) == nodes[1]
    assert r.mem.read(actions[1] + 0x28, 8) == 0
    assert r.called(DESTROY, "virtual_calls") == [(actions[0], 1)]


def test_action_linked_path_runs_actual_cancel_cleanup_and_keeps_parent_al() -> None:
    r = Rig()
    nodes, actions = r.nodes([0, 0])
    r.mem.write(r.obj + 0x148, 8, 1)
    r.parent_result = 0x12340000A5
    assert r.run() == 0xA5
    assert r.mem.read(r.stack + 0x10, 8) == nodes[1]
    assert not r.called(UPDATE, "virtual_calls")
    assert r.called(DESTROY, "virtual_calls") == [(actions[0], 1)]


def test_cancel_does_not_add_null_guard_after_actual_abort_callback() -> None:
    r = Rig()
    _, actions = r.nodes([0])
    nested = r.alloc(0x20)
    r.mem.write(nested + 0x10, 8, 123)
    r.mem.write(actions[0] + 0x50, 8, nested)

    def nested_cleanup(args: tuple[int, ...]) -> None:
        r.mem.write(r.stack + 0x10, 8, 0)

    r.handlers["calls", 0x140B890D0] = nested_cleanup
    with pytest.raises(ReplayMemoryError):
        r.run(CANCEL, r.stack)
    assert not r.called(DESTROY, "virtual_calls")
    assert not r.called(FREE_IMPORT, "imports")


def test_clear_rereads_head_after_resume_replaces_it() -> None:
    r = Rig()
    nodes, actions = r.nodes([0, 0, 0])

    def resume(args: tuple[int, ...]) -> None:
        assert args == (actions[1], 0)
        r.mem.write(r.stack + 0x10, 8, nodes[2])

    r.handlers["virtual_calls", RESUME] = resume
    r.run(CLEAR, r.stack)
    assert r.called(FREE_IMPORT, "imports") == [(nodes[0],), (nodes[2],)]
    assert r.mem.read(nodes[1], 8) == actions[1]
    assert r.mem.read(actions[1], 8) == r.action_table
    assert r.mem.read(r.stack + 0x10, 8) == 0


@pytest.mark.parametrize("disappeared", [False, True])
def test_query_empty_and_callback_removed_head_use_distinct_logs(disappeared: bool) -> None:
    r = Rig()
    if disappeared:
        r.nodes([0])

        def update(args: tuple[int, ...]) -> int:
            r.mem.write(r.stack + 0x10, 8, 0)
            return 0x123400000005

        r.handlers["virtual_calls", UPDATE] = update
    r.mem.write(0x144355056, 1, 1)
    assert r.run(QUERY, r.stack) == (5 if disappeared else 1)
    formats = [args[2] for args in r.called(LOG, "logger_home_calls")]
    assert formats == (
        [0x1432269A8, 0x1432269D8, 0x1432269F8] if disappeared else [0x1432269A8, 0x1432269C0]
    )
    assert not r.called(DESTROY, "virtual_calls") and not r.live


def test_query_reads_debug_after_update_before_consuming_raw_al() -> None:
    r = Rig()
    r.nodes([0])
    r.handlers["virtual_calls", UPDATE] = lambda args: None
    with pytest.raises(ValueError, match="action virtual30 AL"):
        r.run(QUERY, r.stack)
    assert r.events[-1][:3] == ("r", 0x144355056, 1)
    assert not r.live


def test_cleanup_current_target_recheck_and_late_held_target_vptr_slot() -> None:
    r = Rig()
    _, actions = r.nodes([0])
    action = actions[0]
    r.mem.write(action + 0x28, 8, r.other)
    r.mem.write(action + 0x34, 4, 77)
    r.mem.write(action + 8, 2, 0xFFFF)
    r.mem.write(r.other + 0x188, 1, 7)
    r.handlers["calls", LOOKUP] = lambda args: r.other

    def release(args: tuple[int, ...]) -> None:
        assert args == (r.other, r.obj, 0xFFFF)
        r.mem.write(action + 0x28, 8, 0)

    r.handlers["virtual_calls", RELEASE] = release
    assert r.run(CLEANUP, action) is None
    assert r.mem.read(action + 0x34, 4) == 77


@pytest.mark.parametrize("entry", [PAUSE, ABORT])
def test_cleanup_wrappers_return_one_after_required_nested_tail(entry: int) -> None:
    r = Rig()
    _, actions = r.nodes([0])
    nested = r.alloc(0x20)
    r.mem.write(nested + 0x10, 8, 123)
    r.mem.write(actions[0] + 0x50, 8, nested)
    r.handlers["calls", 0x140B890D0] = lambda args: 0xFEDCBA
    assert r.run(entry, actions[0]) == 1
    assert r.called(0x140B890D0) == [(nested,)]


def test_query_log_exposes_partial_status_node_and_keeps_held_return() -> None:
    r = Rig()
    r.nodes([3])
    r.mem.write(0x144355056, 1, 1)

    def logger(args: tuple[int, ...]) -> None:
        if args[2] == 0x1432269D8:
            node = r.mem.read(r.mem.read(args[4], 8), 8)
            assert r.mem.read_bytes(node, 8) == b"\x03" + bytes([0xA2]) * 7
            assert r.mem.read(node + 8, 4) == 5
            r.mem.write(node, 1, 99)

    r.handlers["logger_home_calls", LOG] = logger
    assert r.run(QUERY, r.stack) == 3


@pytest.mark.parametrize(
    ("time", "count", "time_word", "count_word"),
    [(2000, 3, 0x40000000, 0x40400000), (0, U32, 0, 0xBF800000), (U32, 0, 0x4A83126F, 0)],
)
def test_worker_unsigned_time_signed_count_and_preserved_high_halves(
    time: int, count: int, time_word: int, count_word: int
) -> None:
    r = Rig()
    r.mem.write(r.obj + 0x43C, 4, time)
    r.mem.write(r.obj + 0x440, 4, count)
    r.mem.write(r.resource + 0x7D0, 8, encoded(0x1122334400000000))
    r.mem.write(r.resource + 0x7C8, 8, encoded(0x5566778800000000))
    assert r.run(WORKER) == 0
    assert decoded(r.mem.read(r.resource + 0x7D0, 8)) == 0x1122334400000000 | time_word
    assert decoded(r.mem.read(r.resource + 0x7C8, 8)) == 0x5566778800000000 | count_word
    assert r.mem.read(r.obj + 0x43C, 8) == 0


def test_worker_holds_owner_before_elapsed_store_and_uses_second_clock_sample() -> None:
    r = Rig()
    other_owner, other_world, other_clock = r.alloc(0xA00), r.alloc(0x300), r.alloc(0x200)
    r.mem.write(other_owner + 8, 8, other_world)
    r.mem.write(other_owner + 0x98, 8, r.resource)
    r.mem.write(other_world + 0x228, 8, other_clock)
    r.mem.write(other_clock + 0x18, 4, 900)
    r.mem.write(r.obj + 0x438, 4, 50)

    def mutate(at: int, width: int, value: int) -> None:
        if at == r.obj + 0x43C and width == 4:
            r.mem.write(r.obj + 0x18, 8, other_owner)
            r.mem.write(r.clock + 0x18, 4, 200)

    r.after_write = mutate
    r.run(WORKER)
    assert r.mem.read(r.obj + 0x438, 4) == 200
    assert r.called(CLOCK) == [(r.world,), (r.world,)]


def test_worker_holds_decoded_operand_resource_and_count_owner_across_reads() -> None:
    r = Rig()
    other_resource, other_owner, third_resource = r.alloc(0x900), r.alloc(0xA00), r.alloc(0x900)
    r.mem.write(other_owner + 0x98, 8, third_resource)
    for resource in (other_resource, third_resource):
        r.mem.write(resource + 0x7C8, 8, encoded(0))
    r.mem.write(r.obj + 0x43C, 4, 2000)
    r.mem.write(r.obj + 0x440, 4, 3)

    def mutate(at: int, width: int, value: int) -> None:
        if at == 0x1436A02F8:
            r.mem.write(r.frame(0x38) + 0x30, 8, 0)
            r.mem.write(r.owner + 0x98, 8, other_resource)
        elif at == r.obj + 0x440:
            r.mem.write(r.obj + 0x18, 8, other_owner)

    r.after_read = mutate
    r.run(WORKER)
    assert decoded(r.mem.read(r.resource + 0x7D0, 8)) == 0x40000000
    assert decoded(r.mem.read(other_resource + 0x7C8, 8)) == 0x40400000
    assert decoded(r.mem.read(third_resource + 0x7C8, 8)) == 0
    assert r.events[-1] == ("w", r.obj + 0x43C, 8, 0)


def test_worker_null_owner_skips_fp_and_still_clears_time_and_count() -> None:
    r = Rig()
    r.mem.write(r.obj + 0x18, 8, 0)
    r.mem.write(r.obj + 0x43C, 8, U64)
    assert r.run(WORKER) == 0
    assert r.mem.read(r.obj + 0x43C, 8) == 0
    assert not r.snapshots


def test_class_four_starts_and_stops_timer_through_actual_clock_storage() -> None:
    r = Rig()
    r.object_class(4)
    r.mem.write(r.obj + 0x188, 1, 2)
    r.mem.write(r.clock + 0x18, 4, 1000)
    r.run()
    assert r.mem.read(r.obj + 0x438, 4) == 1000
    assert r.mem.read(r.obj + 0x440, 4) == 1
    r.mem.write(r.clock + 0x18, 4, 2000)
    r.handlers["virtual_calls", ACTIVE] = lambda args: 0
    r.run()
    assert r.mem.read(r.obj + 0x438, 4) == 0
    assert r.mem.read(r.obj + 0x43C, 4) == 1000


def test_action_class_four_commits_elapsed_work_through_actual_worker() -> None:
    r = Rig()
    r.object_class(4)
    r.mem.write(r.obj + 0x188, 1, 3)
    r.mem.write(r.obj + 0x438, 4, 50)
    r.mem.write(r.obj + 0x440, 4, 2)
    r.mem.write(r.clock + 0x18, 4, 2050)
    r.run()
    assert decoded(r.mem.read(r.resource + 0x7D0, 8)) == 0x40000000
    assert decoded(r.mem.read(r.resource + 0x7C8, 8)) == 0x40000000
    assert r.mem.read(r.obj + 0x438, 4) == 0
    assert r.mem.read(r.obj + 0x43C, 8) == 0
    assert r.called(CLOCK) == [(r.world,), (r.world,)]


@pytest.mark.parametrize(
    ("distance", "found", "cleared"),
    [
        (0x407FFFFF, True, False),
        (0x40800000, True, True),
        (0x40800001, True, True),
        (0x7FC12345, True, False),
        (0, False, True),
    ],
)
def test_target_strict_boundary_unordered_and_null(
    distance: int, found: bool, cleared: bool
) -> None:
    r = Rig()
    r.handlers["calls", LOOKUP] = lambda args: r.other if found else 0
    r.handlers["scalar_fp_calls", 0x14124E840] = lambda args: distance
    r.run()
    assert r.mem.read(r.obj + 0x430, 4) == (U32 if cleared else 123)
    assert r.mem.read(r.obj + 0x434, 4) == (0 if cleared else 99)


def test_target_reads_current_limit_after_distance_and_decodes_even_for_null() -> None:
    r = Rig()
    r.handlers["calls", LOOKUP] = lambda args: r.other

    def distance(args: tuple[int, ...]) -> int:
        r.mem.write(r.frame(0x90) + 0x60, 4, 0x3F800000)
        return 0x40000000

    r.handlers["scalar_fp_calls", 0x14124E840] = distance
    r.run()
    assert r.mem.read(r.obj + 0x430, 4) == U32
    r = Rig()
    r.mem.write(r.obj + 0x430, 4, U32)
    r.run()
    assert r.called(LOOKUP) == [(r.world, U32)]
    assert any(e[:3] == ("r", r.resource + 0x800, 8) for e in r.events)


def test_target_holds_owner_but_loads_world_after_current_id() -> None:
    r = Rig()
    other_world = r.alloc(0x300)

    def mutate(at: int, width: int, value: int) -> None:
        if at == r.obj + 0x430:
            r.mem.write(r.owner + 8, 8, other_world)

    r.after_read = mutate
    r.run()
    assert r.called(LOOKUP) == [(other_world, 123)]


@pytest.mark.parametrize(("kind", "flag"), [(1, 0x10), (0x100000001, 0x10), (0x101, 0), (0, 0)])
def test_notification_eax_projection_late_bus_and_tail_identity(kind: int, flag: int) -> None:
    r = Rig()
    r.handlers["virtual_calls", KIND] = lambda args: kind

    def clock(args: tuple[int, ...]) -> None:
        assert args == (r.game,)
        r.mem.write(0x1443563C0, 8, 0xDDD0)

    result = 123456789012345
    r.handlers["calls", 0x140D6A880] = clock
    r.handlers["calls", 0x141121110] = lambda args: result
    assert r.run(NOTIFY) is result
    assert r.called(0x141121110) == [(0xDDD0, r.obj, flag)]


def test_notification_reads_game_before_missing_eax_refusal() -> None:
    r = Rig()
    r.handlers["virtual_calls", KIND] = lambda args: None
    with pytest.raises(ValueError, match="notification virtual610 EAX"):
        r.run(NOTIFY)
    assert r.events[-1] == ("r", 0x144353698, 8, r.game)
    assert not r.called(0x140D6A880)


@pytest.mark.parametrize(
    "channel", ["virtual_calls", "imports", "logger_home_calls", "scalar_fp_calls"]
)
def test_missing_category_refuses_at_reached_prefix(channel: str) -> None:
    r = Rig()
    if channel == "imports":
        nodes, _ = r.nodes([0])
        target, obj = POP, r.stack
    elif channel == "logger_home_calls":
        r.mem.write(0x144355056, 1, 1)
        target, obj = QUERY, r.stack
    elif channel == "scalar_fp_calls":
        r.handlers["calls", LOOKUP] = lambda args: r.other
        target, obj = ACTION, r.obj
    else:
        r.nodes([0])
        target, obj = QUERY, r.stack
    r.bound = r.bind(**{channel: ReplayTaskRebuildCalls(None)})
    with pytest.raises(UnresolvedReplayTaskRebuild):
        r.run(target, obj)
    if channel == "imports":
        assert r.mem.read(r.stack + 0x10, 8) == 0
        assert r.mem.read(nodes[0], 8)
    assert not r.live


def test_object_list_composes_actual_action_controllers_base_and_movement_chain() -> None:
    r = Rig()
    r.real_parent = True
    r.mem.write(r.obj + 0x400, 8, r.motion)
    r.mem.write(r.table + 0x30, 8, ACTION)
    header, data = r.alloc(0x20), r.alloc(8)
    r.mem.write(header + 8, 8, data)
    r.mem.write(header + 0x10, 4, 1)
    r.mem.write(data, 8, r.obj)
    objects = bind_replay_object_update(r.context, r.bound, profile=ReplayObjectUpdateProfile(1))
    assert objects.call is not None and objects.call(0x141229A20, (header,), None) is None
    assert r.mem.read(r.obj + 0x198, 4) == 93
    assert r.mem.read(r.obj + 0x350, 4) == 0x40400000
    assert r.mem.read(r.obj + 0x42A, 2) == 0
    assert r.called(BASE) == [(r.obj,)]
    assert r.called(CLOCK) == [(r.world,)]
    assert r.called(0x141121110) == [(0xBBB0, r.obj, 0x10)]


def test_invalid_services_and_mxcsr_refuse_before_effects() -> None:
    r = Rig()
    with pytest.raises(ValueError):
        r.bind(imports=cast(ReplayTaskRebuildCalls, None))
    for mxcsr in (True, 0, 0x1F81, 0x3F80):
        with pytest.raises(ValueError):
            bind_replay_action_object_update(
                r.context,
                r.ordinary_calls,
                **{
                    name: ReplayTaskRebuildCalls(None)
                    for name in ("virtual_calls", "imports", "logger_home_calls", "scalar_fp_calls")
                },
                bind_local=r.local,
                profile=r.profile,
                mxcsr=mxcsr,
            )
    assert not r.events
