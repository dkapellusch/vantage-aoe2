"""Actual World phase composition with explicit authored child services.

No phase is mocked. Clocks, command polling, batches and manager queues use
their existing implementations. Other services are caller-test capabilities;
these tests do not restore a recording or establish native game parity.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import fields, replace
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
from vantage.replay_object_update import ReplayObjectUpdateProfile, bind_replay_object_update
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
from vantage.replay_world_formation import (
    ReplayWorldFormationProfile,
    bind_replay_world_formation,
)
from vantage.replay_world_postpasses import (
    ReplayWorldPostpassesProfile,
    bind_replay_world_postpasses,
)
from vantage.replay_world_update import (
    ReplayWorldUpdateServices,
    run_replay_world_update,
)

FRAME = 0x300000
VPLAYER, VWORLD, VLINK, VUNLINK = 0xF00100, 0xF00070, 0xF00328, 0xF00330
Handler = Callable[[tuple[int, ...]], int | None]


class Rig:
    def __init__(self, count: int = 2) -> None:
        self.memory = ReplayMemory()
        self.events: list[tuple[str, int, tuple[int, ...]]] = []
        self.writes: list[tuple[int, int, int]] = []
        self.handlers: dict[int, Handler] = {}
        self.cycle = 16
        self.world = self.alloc(0x900)
        self.clock = self.alloc(0x100)
        self.game = self.alloc(0x1000)
        self.manager = self.alloc(0x2800)
        self.dispatcher = self.alloc(0x2800)
        self.settings = self.alloc(0x2800)
        self.descriptor = self.alloc(0x100)
        self.options = self.alloc(0x100)
        self.terrain = self.alloc(0x6000)
        self.sentinel = self.alloc(0xE0)
        self.blocks = self.alloc(0x500)
        self.world_table = self.alloc(0x400)
        self.player_table = self.alloc(0x400)
        self.players = [self.alloc(0x700) for _ in range(count)]
        self.array = self.alloc(max(1, count) * 16)
        self.memory.map_bytes(FRAME, bytes([0xA5]) * 0xE00)
        for address, size in (
            (0x1431B7000, 0x1000),
            (0x1431FE000, 0x1000),
            (0x143219000, 0x1000),
            (0x1436A0000, 0x1000),
            (0x143DA5000, 0x1000),
            (0x144284000, 0x1000),
            (0x14425B000, 0x1000),
            (0x1442C3000, 0x2000),
            (0x1442DA000, 0x1000),
            (0x144353000, 0x1000),
            (0x144355000, 0x1000),
            (0x144418000, 0x1000),
        ):
            self.memory.map_bytes(address, bytes(size))
        for address, width, value in (
            (self.world, 8, self.world_table),
            (self.world_table + 0x70, 8, VWORLD),
            (self.player_table + 0x100, 8, VPLAYER),
            (self.player_table + 0x328, 8, VLINK),
            (self.player_table + 0x330, 8, VUNLINK),
            (self.world + 0x50, 8, self.sentinel),
            (self.sentinel + 0xC8, 8, self.sentinel),
            (self.world + 0x70, 8, self.descriptor),
            (self.world + 0x88, 4, 0x55),
            (self.world + 0x98, 8, self.terrain),
            (self.world + 0x130, 8, self.manager),
            (self.world + 0x228, 8, self.clock),
            (self.world + 0x768, 8, self.array),
            (self.world + 0x770, 8, self.array + count * 16),
            (self.world + 0x7D4, 4, 3),
            (self.world + 0x800, 8, self.blocks),
            (self.manager + 0x114, 1, 0x7B),
            (self.manager + 0x2008, 8, self.dispatcher),
            (self.dispatcher + 0x318, 4, 3),
            (self.dispatcher + 0x358, 8, self.clock),
            (self.clock + 8, 4, 1),
            (self.clock + 0xC, 4, 0x3F800000),
            (self.clock + 0x10, 4, 0x3F800000),
            (self.clock + 0x18, 4, 1000),
            (self.clock + 0x30, 4, 1000),
            (FRAME + 0x20C, 4, 0xFEEDBEEF),
            (0x144353698, 8, self.game),
            (0x1442DA8A0, 8, self.settings),
            (0x1436A0294, 4, 0x3F800000),
            (0x1436A02F8, 4, 0x3F800000),
            (0x1431FE88C, 4, 0x3F800000),
            (0x143DA5054, 4, 0xFFFFFFFF),
        ):
            self.memory.write(address, width, value)
        for i, player in enumerate(self.players):
            self.memory.write(self.array + i * 16, 8, player)
            self.memory.write(player, 8, self.player_table)
            self.memory.write(player + 0x228, 4, 0x3F800000 + i)
            self.memory.write(player + 0x22C, 4, 0x40000000 + i)

        self.context = ReplayTaskRebuildStorage(self.world, self.memory.read, self.write)
        self.calls = ReplayTaskRebuildCalls(self.ordinary)
        self.atomics = ReplayUnitAIMapAtomics(
            self.memory.compare_exchange_u32, self.memory.fetch_add_u32
        )
        self.clock_calls = bind_replay_clock_storage(self.context, self.calls, mxcsr=0x1F80)
        self.reader_calls = bind_replay_command_reader(
            self.context,
            self.calls,
            imports=self.calls,
            logger_home_calls=self.calls,
            atomics=self.atomics,
            bind_local=self.memory.bind_local,
            profile=ReplayCommandReaderProfile(bytes(0x58), bytes(0x50), bytes(0x90)),
        )
        self.batch_calls = bind_replay_command_batch(
            self.context,
            self.calls,
            watson_home_calls=self.calls,
            error_home_calls=self.calls,
            atomics=self.atomics,
            bind_local=self.memory.bind_local,
            profile=ReplayCommandBatchProfile(bytes(0x28), bytes(0x28), bytes(0x50), bytes(0xB0)),
            mxcsr=0x1F80,
        )
        self.queue_calls = bind_replay_manager_queues(
            self.context,
            self.calls,
            imports=self.calls,
            writer_home_calls=self.calls,
            flag_calls=self.calls,
            virtual_calls=self.calls,
            logger_home_calls=self.calls,
            error_home_calls=self.calls,
            atomics=self.atomics,
            bind_local=self.memory.bind_local,
            profile=ReplayManagerQueuesProfile(bytes(0x6C), bytes(0x58), bytes(0x1C0), bytes(0xA8)),
        )
        self.services = ReplayWorldUpdateServices(
            **{
                f.name: ReplayTaskRebuildCalls(self.channel(f.name))
                for f in fields(ReplayWorldUpdateServices)
            }
        )

    def alloc(self, size: int) -> int:
        address = self.memory.allocate(size)
        self.memory.fill(address, 0, size)
        return address

    def write(self, address: int, width: int, value: int) -> None:
        self.writes.append((address, width, value))
        self.memory.write(address, width, value)

    def channel(self, name: str) -> Callable[[int, tuple[int, ...], memoryview | None], int | None]:
        def call(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
            assert data is None
            self.events.append((name, target, args))
            if name == "virtual_calls" and target in (VWORLD, VPLAYER, VLINK, VUNLINK):
                return None
            if name == "format_home_calls" and target == 0x1410242D0:
                return None
            raise UnresolvedReplayTaskRebuild(f"authored {name} has no service{target:x}")

        return call

    def ordinary(self, target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        assert data is None
        self.events.append(("calls", target, args))
        if target in self.handlers:
            return self.handlers[target](args)
        owner: ReplayTaskRebuildCalls | None = None
        if target in (0x140E68F50, 0x140E68F70, 0x140E68FA0, 0x140E68C40):
            owner = self.clock_calls
        elif target in (0x140F51FC0, 0x140E15C00, 0x140E62B90, 0x140E085A0, 0x140E68F80):
            owner = self.reader_calls
        elif target in (0x140E08860, 0x140E07CC0):
            owner = self.batch_calls
        elif target in (0x140F558A0, 0x140F52130, 0x140F52140, 0x140D6A880, 0x140F55A30):
            owner = self.queue_calls
        if owner is not None:
            assert owner.call is not None
            return owner.call(target, args, data)
        if target == 0x140A71140:
            return 200
        if target == 0x140E0E530:
            return self.cycle
        if target == 0x140E15770:
            return self.descriptor
        if target == 0x141021E00:
            return 0xABC0
        if target == 0x140903E40:
            return 7
        if target == 0x140D6A530:
            self.memory.write(args[1], 8, self.options)
            return args[1]
        if target in (0x140E7E9C0, 0x1410221C0, 0x140D6ADB0, 0x14097FB40, 0x1413F7A00):
            return 0
        if target in (
            0x14151E9C0,
            0x140D68190,
            0x1409033B0,
            0x140FDDBF0,
            0x14148C300,
            0x140F55750,
            0x140F54480,
            0x14162BAB0,
            0x140990140,
            0x141731F00,
            0x14114B470,
            0x141229A20,
            0x14115F240,
            0x1416938B0,
            0x140E27920,
            0x140DF2670,
            0x140F55400,
            0x141711B80,
        ):
            return None
        raise UnresolvedReplayTaskRebuild(f"authored ordinary service{target:x} is unavailable")

    def run(self, incoming: int = 1) -> int:
        return run_replay_world_update(
            self.context,
            self.calls,
            self.world,
            incoming,
            logical_frame=FRAME,
            services=self.services,
            mxcsr=0x1F80,
        )

    def called(self, target: int, channel: str = "calls") -> list[tuple[int, ...]]:
        return [args for kind, entry, args in self.events if kind == channel and entry == target]


@pytest.mark.parametrize("count", [1, 2, 3])
def test_complete_caller_uses_one_clock_admission_and_all_player_backedges(count: int) -> None:
    r = Rig(count)
    assert r.run(0xABCDEF0000000001) == 0x55
    assert r.memory.read(r.clock + 0x18, 4) == 1016
    assert r.memory.read(r.world + 0x7C, 4) == 16
    assert r.memory.read(r.world + 0x7D8, 4) == 3
    assert r.called(0x140E0E530) == [(r.dispatcher,)]
    assert len(r.called(0x140E68C40)) == 1
    assert r.called(0x141731F00) == [(p + 0xA0,) for p in r.players]
    assert r.called(VPLAYER, "virtual_calls") == [(p,) for p in r.players]
    assert [item for item in r.writes if r.manager + 0x1FE0 <= item[0] < r.manager + 0x2004] == [
        (r.manager + 0x1FE0 + i * 4, 4, 0) for i in range(9)
    ]
    assert r.memory.read(r.manager + 0x114, 1) == 0
    assert r.memory.read(r.settings + 0x26B8, 1) == 0
    assert r.memory.read(r.dispatcher + 0x380, 1) == 1
    assert r.memory.read(FRAME + 0x210, 4) == count
    assert r.memory.read(FRAME + 0x20C, 4) == 0xFEEDBEEF
    for i in range(1, count):
        assert r.memory.read(r.world + 0x18C + i * 4, 4) == 16
    with pytest.raises(ReplayMemoryError):
        r.memory.read(FRAME + 0xE00, 8)


def test_repeated_calls_advance_actual_clock_without_retaining_player_loop_state() -> None:
    r = Rig(3)
    assert r.run() == r.run() == 0x55
    assert r.memory.read(r.clock + 0x18, 4) == 1032
    assert r.memory.read(r.world + 0x188, 4) == 2
    assert r.memory.read(r.world + 0x18C + 2 * 4, 4) == 32
    assert len(r.called(0x140E68C40)) == 2
    assert r.called(0x141731F00) == [(p + 0xA0,) for p in r.players] * 2


def test_active_player_reentry_retains_live_relationship_homes_and_markers() -> None:
    r = Rig()
    for player in r.players:
        r.memory.write(player + 0x648, 4, 1)
    homes: list[tuple[int, int]] = []

    def relationship(target: int, args: tuple[int, ...], data: memoryview | None) -> int:
        assert target == 0x141734D70 and data is None and args[2:] == (1, 0xFF)
        homes.append((args[1], r.memory.read(args[1], 4)))
        return 1

    r.services = replace(r.services, relationship_calls=ReplayTaskRebuildCalls(relationship))
    assert r.run() == 0x55
    assert homes == [(FRAME + 0x94, 1), (FRAME + 0x90, 0), (FRAME + 0xA4, 1), (FRAME + 0xA8, 1)]
    assert r.called(VLINK, "virtual_calls") == [(r.players[1], FRAME + 0xA0)]
    assert r.called(VUNLINK, "virtual_calls") == [(r.players[1], FRAME + 0x270)]
    assert r.memory.read(FRAME + 0x27C, 4) == 0
    assert len(r.called(0x140E68C40)) == 1


def test_missing_relationship_refuses_before_player_work_or_queue_clear() -> None:
    r = Rig()
    for player in r.players:
        r.memory.write(player + 0x648, 4, 1)
    with pytest.raises(UnresolvedReplayTaskRebuild, match="relationship_calls"):
        r.run()
    assert not r.called(0x141734D70)
    assert not r.called(VPLAYER, "virtual_calls")
    assert r.memory.read(r.manager + 0x114, 1) == 0x7B


@pytest.mark.parametrize("refuses", [False, True])
def test_real_queue_payload_release_is_reached_through_all_world_phases(refuses: bool) -> None:
    r = Rig(1)
    payload, row, array = r.alloc(4), r.alloc(16), r.alloc(16)
    r.memory.write(payload, 4, 0x04030201)
    for address, width, value in (
        (row, 8, payload),
        (row + 8, 8, 4),
        (array, 8, row),
        (r.manager + 0x218, 8, array),
        (r.manager + 0x220, 8, 2),
        (r.manager + 0x230, 8, 1),
        (r.settings + 0x318, 4, 7),
        (r.dispatcher + 0x31C, 4, 1),
    ):
        r.memory.write(address, width, value)
    free_target = 0xFAAF
    r.memory.map_bytes(0x143199DD0, free_target.to_bytes(8, "little"))
    r.handlers[0x140D6ACC0] = lambda _args: r.world
    r.handlers[0x141603FC0] = lambda _args: 0

    def free(args: tuple[int, ...]) -> None:
        assert args == (payload,)
        if refuses:
            raise UnresolvedReplayTaskRebuild("explicit queue free refusal")
        r.memory.free(payload)

    r.handlers[free_target] = free
    if refuses:
        with pytest.raises(UnresolvedReplayTaskRebuild, match="explicit queue free refusal"):
            r.run()
        assert r.memory.read(payload, 4) == 0x04030201
        assert r.memory.read(r.manager + 0x230, 8) == 1
        assert r.memory.read(r.manager + 0x114, 1) == 0x7B
        assert r.memory.read(r.settings + 0x26B8, 1) == 1
    else:
        assert r.run() == 0x55
        with pytest.raises(ReplayMemoryError):
            r.memory.read(payload, 1)
        assert r.memory.read(r.manager + 0x230, 8) == 0
        assert r.memory.read(r.manager + 0x228, 8) == 0
        assert r.memory.read(r.manager + 0x114, 1) == 0
        assert r.memory.read(r.settings + 0x26B8, 1) == 0
    assert r.called(free_target) == [(payload,)]
    assert r.memory.read(r.clock + 0x18, 4) == 1016


def test_idle_return_never_enters_recording_or_later_phases() -> None:
    r = Rig()
    r.cycle = 0
    assert r.run() == 0x55
    assert r.memory.read(r.clock + 0x18, 4) == 1000
    assert r.memory.read(r.manager + 0x114, 1) == 0x7B
    assert not r.called(0x140E15770)
    assert not r.called(0x140F558A0)


@pytest.mark.parametrize("incoming", [0, 0x100000000])
def test_playback_stop_returns_actual_four_without_entering_bridge(incoming: int) -> None:
    r = Rig()
    r.memory.write(r.descriptor + 1, 1, 1)
    r.memory.write(r.descriptor + 0x94, 4, 32)
    assert r.run(incoming) == 4
    assert r.memory.read(r.clock + 0x18, 4) == 1032
    assert r.called(0x140DF2670) == [(r.descriptor,)]
    assert not r.called(0x141021E00)
    assert not r.called(0x140F558A0)


def test_reader_eof_early_return_is_preserved_after_its_live_home_writes() -> None:
    r = Rig()
    r.memory.write(r.descriptor + 1, 1, 1)
    r.handlers[0x140DEC960] = lambda _args: 0
    assert r.run() == 4
    assert r.called(0x140F55400)
    assert r.called(0x140DEC960) == [(r.descriptor, FRAME + 0x200, FRAME + 0x210, FRAME + 0x270)]
    assert not r.called(0x141021E00)


def test_empty_current_player_header_takes_primary_links_shortcut() -> None:
    r = Rig()

    def empty(_args: tuple[int, ...]) -> None:
        r.memory.write(r.world + 0x770, 8, r.array)

    r.handlers[0x14162BAB0] = empty
    assert r.run() == 0x55
    assert not r.called(VPLAYER, "virtual_calls")
    assert not r.called(0x141731F00)
    assert r.called(0x140F558A0) == [(r.manager,)]
    assert r.memory.read(FRAME + 0x210, 4) == 0


def test_reached_refusal_propagates_with_prior_clock_and_frame_effects() -> None:
    r = Rig()

    def unavailable(_args: tuple[int, ...]) -> int | None:
        raise UnresolvedReplayTaskRebuild("explicit missing bridge descendant")

    r.handlers[0x14162BAB0] = unavailable
    with pytest.raises(UnresolvedReplayTaskRebuild, match="explicit missing bridge descendant"):
        r.run()
    assert r.memory.read(r.clock + 0x18, 4) == 1016
    assert r.memory.read(r.world + 0x7C, 4) == 16
    assert r.memory.read(r.manager + 0x114, 1) == 0x7B
    assert not r.called(0x140F558A0)


def test_tail_category_does_not_fall_back_to_ordinary_calls() -> None:
    r = Rig()
    r.services = replace(r.services, format_home_calls=ReplayTaskRebuildCalls(None))
    with pytest.raises(UnresolvedReplayTaskRebuild, match="1410242d0"):
        r.run()
    assert r.memory.read(r.manager + 0x114, 1) == 0
    assert not r.called(0x1410242D0)


@pytest.mark.parametrize("name", [f.name for f in fields(ReplayWorldUpdateServices)])
def test_service_categories_require_explicit_calls_objects(name: str) -> None:
    r = Rig()
    with pytest.raises(ValueError, match="category-specific"):
        replace(r.services, **{name: cast(ReplayTaskRebuildCalls, None)})
    assert not r.events


@pytest.mark.parametrize("mxcsr", [0, True, 0x1F81, 0x9F80])
def test_complete_profile_refuses_before_entry_effects(mxcsr: int) -> None:
    r = Rig()
    before = r.memory.read(FRAME + 0x208, 8)
    with pytest.raises(ValueError, match="MXCSR1f80"):
        run_replay_world_update(
            r.context, r.calls, r.world, 1, logical_frame=FRAME, services=r.services, mxcsr=mxcsr
        )
    assert r.memory.read(FRAME + 0x208, 8) == before
    assert not r.events


def test_missing_service_bundle_refuses_before_entry_effects() -> None:
    r = Rig()
    before = r.memory.read(FRAME + 0x208, 8)
    with pytest.raises(ValueError, match="services required"):
        run_replay_world_update(
            r.context,
            r.calls,
            r.world,
            1,
            logical_frame=FRAME,
            services=cast(ReplayWorldUpdateServices, None),
            mxcsr=0x1F80,
        )
    assert r.memory.read(FRAME + 0x208, 8) == before
    assert not r.events


def test_driver_composes_actual_postpasses_object_dispatch_and_formation() -> None:
    r = Rig()
    unavailable = ReplayTaskRebuildCalls(None)
    r.memory.map_bytes(0x144414BC0, bytes(8))
    r.memory.write(r.world + 0x8E2, 2, 0xFFFF)
    r.memory.write(r.dispatcher + 0x390, 8, 0xD00D)
    visible: list[int] = []
    seen: list[int] = []
    for player in r.players:
        sight, observations, objects = r.alloc(0x30), r.alloc(0x30), r.alloc(0x18)
        visible.append(sight)
        seen.append(observations)
        r.memory.write(player + 8, 8, r.world)
        r.memory.write(sight, 8, player)
        r.memory.write(observations, 8, player)
        r.memory.write(player + 0x80, 8, sight)
        r.memory.write(player + 0x78, 8, observations)
        r.memory.write(player + 0x40, 8, objects)
    children = bind_replay_world_postpasses(
        r.context,
        r.calls,
        visibility_calls=unavailable,
        fog_home_calls=unavailable,
        player_event_home_calls=unavailable,
        resource_home_calls=unavailable,
        state_byte_calls=unavailable,
        rule_event_home_calls=unavailable,
        bind_local=r.memory.bind_local,
        profile=ReplayWorldPostpassesProfile(bytes(0xF0), bytes(0xD0), bytes(0x34), bytes(0x54)),
        mxcsr=0x1F80,
    )
    for entry in (0x14151E9C0, 0x14114B470, 0x14115F240, 0x141731F00, 0x140E27920, 0x1416938B0):

        def child(args: tuple[int, ...], target: int = entry) -> int | None:
            assert children.call is not None
            return children.call(target, args, None)

        r.handlers[entry] = child
    objects_binding = bind_replay_object_update(
        r.context, r.calls, profile=ReplayObjectUpdateProfile(8)
    )
    formation = bind_replay_world_formation(
        r.context,
        r.calls,
        logger_home_calls=unavailable,
        event_home_calls=unavailable,
        bind_local=r.memory.bind_local,
        profile=ReplayWorldFormationProfile(bytes(0xB0), bytes(0xD8), bytes(0x44)),
        mxcsr=0x1F80,
    )

    def update_objects(args: tuple[int, ...]) -> int | None:
        assert objects_binding.call is not None
        return objects_binding.call(0x141229A20, args, None)

    def update_formation(args: tuple[int, ...]) -> int | None:
        assert formation.call is not None
        return formation.call(0x14162BAB0, args, None)

    r.handlers[0x141229A20] = update_objects
    r.handlers[0x14162BAB0] = update_formation
    packets: list[tuple[int, list[int]]] = []

    def timings(args: tuple[int, ...]) -> None:
        packets.append((args[0], [r.memory.read(args[1] + 4 * i, 4) for i in range(5)]))

    r.handlers[0x140E66530] = timings
    assert r.run() == 0x55
    assert packets == [(0xD00D, [7] * 5)]
    assert r.called(0x14114B470) == [(address,) for address in visible]
    assert r.called(0x14115F240) == [(address,) for address in seen]
    assert r.memory.read(r.clock + 0x18, 4) == 1016
    assert r.memory.read(r.manager + 0x114, 1) == 0


def test_driver_gets_cycle_from_actual_pending_queue_instead_of_constant() -> None:
    r = Rig()
    queue, timer, descriptor = r.alloc(0x500), r.alloc(0x2A8), r.alloc(0x400)
    r.memory.map_bytes(0x1431F7470, bytes.fromhex("0300000006000000080000000a000000"))
    r.memory.map_bytes(0x143266E00, bytes.fromhex("04000000050000000600000007000000"))
    for address, width, value in (
        (r.dispatcher + 0x318, 4, 8),
        (r.dispatcher + 0x388, 8, queue),
        (queue + 0x100, 8, timer),
        (queue + 0x3D0, 8, descriptor),
        (queue + 0x3E8, 4, 1),
        (queue + 0x3E4, 4, 1),
        (queue + 0x3F0, 4, 23),
    ):
        r.memory.write(address, width, value)
    unavailable = ReplayTaskRebuildCalls(None)
    cycles = bind_replay_world_cycle(
        r.context,
        r.calls,
        virtual_calls=unavailable,
        logger_home_calls=unavailable,
        error_home_calls=unavailable,
        runtime_calls=unavailable,
        atomics=r.atomics,
        bind_local=r.memory.bind_local,
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

    def cycle(args: tuple[int, ...]) -> int | None:
        assert cycles.call is not None
        return cycles.call(0x140E0E530, args, None)

    r.handlers[0x140E0E530] = cycle
    assert r.run() == 0x55
    assert r.memory.read(queue + 0x3E8, 4) == 0
    assert r.memory.read(queue + 0x4CC, 4) == 1
    assert r.memory.read(queue + 0x4B8, 4) == 200
    assert r.memory.read(r.clock + 0x18, 4) == 1023
    assert r.memory.read(r.world + 0x7C, 4) == 23
    assert r.memory.read(r.manager + 0x114, 1) == 0
    assert r.called(0x140E0E530) == [(r.dispatcher,)]
