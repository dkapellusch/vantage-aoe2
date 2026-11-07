"""World entry source order with real owned clocks and explicit phase handoff."""

from __future__ import annotations

import struct

import pytest

from vantage.replay_clock_storage import bind_replay_clock_storage
from vantage.replay_command_batch import (
    ReplayCommandBatchProfile,
    bind_replay_command_batch,
)
from vantage.replay_memory import ReplayMemory, ReplayMemoryError
from vantage.replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
)
from vantage.replay_unit_ai_map import ReplayUnitAIMapAtomics
from vantage.replay_world_update_prelude import run_replay_world_update_prelude

GAME, DEBUG, EXTERNAL = 0x144353698, 0x1442C3FC4, 0x1442846E8
TIME, RATE, ADVANCE = 0x140E68F70, 0x140E68F50, 0x140E68C40
HOST, CYCLE, PREDICATE = 0x140A71140, 0x140E0E530, 0x140E7E9C0


def f32(value):
    return int.from_bytes(struct.pack("<f", value), "little")


class Rig:
    def __init__(self, *, cycle=13, special=0, previous_host=100, clock_time=1000):
        self.memory = ReplayMemory()
        self.world = self.memory.allocate(0x900)
        self.clock = self.memory.allocate(0x1C)
        self.manager = self.memory.allocate(0x2010)
        self.cycler = self.memory.allocate(1)
        self.game = self.memory.allocate(0x226)
        self.frame = self.memory.allocate(0xE40)
        self.descriptor = self.memory.allocate(1)
        self.events, self.after_read, self.after_write = [], None, None
        self.host_times = iter([100, 107, 200])
        self.predicates = iter([0, 0])
        for address, width, value in [
            (self.world + 0x228, 8, self.clock),
            (self.world + 0x130, 8, self.manager),
            (self.manager + 0x2008, 8, self.cycler),
            (self.game + 0x225, 1, special),
            (self.world + 0x768, 8, 0x9000),
            (self.world + 0x770, 8, 0x9010),
            (self.world + 0x7D4, 4, 7),
            (self.world + 0x84, 4, previous_host),
            (self.world + 0x7C, 4, 777),
            (self.world + 0x88, 4, 7),
            (self.world + 0x90, 4, 0),
            (self.clock + 8, 4, 1),
            (self.clock + 0xC, 4, f32(1.5)),
            (self.clock + 0x10, 4, f32(1.5)),
            (self.clock + 0x18, 4, clock_time),
            (self.descriptor, 1, 1),
        ]:
            self.memory.write(address, width, value)
        for address, raw in [
            (GAME, self.game.to_bytes(8, "little")),
            (DEBUG, bytes(4)),
            (EXTERNAL, bytes(8)),
            (0x1436A0294, bytes.fromhex("0000803f")),
            (0x1436A02E0, bytes.fromhex("00007042")),
            (0x143DAE26C, bytes.fromhex("0000803f")),
            (0x1431FE898, (60).to_bytes(4, "little")),
            (0x1442C40F0, bytes(4)),
            (0x144355062, bytes(1)),
            (0x144355068, (0xCC00).to_bytes(8, "little")),
            (0x144418594, (99).to_bytes(4, "little")),
            (0x144418DC8, bytes(1)),
            (0x144418E98, bytes(1)),
            (0x1442C3F98, (0xDD00).to_bytes(8, "little")),
        ]:
            self.memory.map_bytes(address, raw)

        def read(address, width):
            self.events.append(("read", address, width))
            value = self.memory.read(address, width)
            if self.after_read is not None:
                self.after_read(address, width)
            return value

        def write(address, width, value):
            self.events.append(("write", address, width, value))
            self.memory.write(address, width, value)
            if self.after_write is not None:
                self.after_write(address, width, value)

        self.storage = ReplayTaskRebuildStorage(0xABCD, read, write)
        self.handlers = {
            0x14151E9C0: lambda args: None,
            HOST: lambda args: next(self.host_times),
            CYCLE: lambda args: cycle,
            0x140D68190: lambda args: None,
            PREDICATE: lambda args: next(self.predicates),
            0x1409033B0: lambda args: None,
            0x1409733F0: lambda args: None,
            0x140E15770: lambda args: self.descriptor,
            0x140D6ACC0: lambda args: self.world,
            0x140F4AD30: lambda args: None,
            0x14101ADB0: lambda args: None,
        }

        def call(target, args, data):
            assert data is None
            self.events.append(("call", target, args))
            if target in (TIME, RATE, ADVANCE, 0x140E68FA0, 0x140973630):
                return self.clock_binding.call(target, args, data)
            if target not in self.handlers:
                raise UnresolvedReplayTaskRebuild(f"actual test provider{target:x} unavailable")
            return self.handlers[target](args)

        self.calls = ReplayTaskRebuildCalls(call)
        self.clock_binding = bind_replay_clock_storage(self.storage, self.calls, mxcsr=0x1F80)

    def run(self, incoming=0xABCDEF0100000003):
        return run_replay_world_update_prelude(
            self.storage,
            self.calls,
            self.world,
            incoming,
            logical_frame=self.frame,
            mxcsr=0x1F80,
        )

    def call_events(self):
        return [event for event in self.events if event[0] == "call"]


def test_real_clock_is_advanced_and_normal_result_requires_recording_phase():
    rig = Rig()
    rig.memory.write(rig.frame + 0x20C, 4, 0xAABBCCDD)
    result = rig.run()
    assert (result.entry_time, result.cycle, result.incoming_status) == (1000, 13, 3)
    assert (result.next_address, result.returned_status) == (0x141628F0C, None)
    assert (result.world, result.logical_frame) == (rig.world, rig.frame)
    assert rig.memory.read(rig.clock + 0x18, 4) == 1019
    assert rig.memory.read(rig.world + 0x78, 4) == 1000
    assert rig.memory.read(rig.world + 0x84, 4) == 200
    assert rig.memory.read(rig.world + 0x7D8, 4) == 10
    assert rig.memory.read(rig.world + 0x7C, 4) == 777  # Later replay phase owns delta.
    assert rig.memory.read(rig.frame + 0x208, 8) == 0xAABBCCDD00000000
    with pytest.raises(ReplayMemoryError):
        rig.memory.read(rig.frame + 0x218, 8)
    assert rig.call_events() == [
        ("call", 0x14151E9C0, ()),
        ("call", TIME, (rig.clock,)),
        ("call", RATE, (rig.clock,)),
        ("call", HOST, ()),
        ("call", CYCLE, (rig.cycler,)),
        ("call", HOST, ()),
        ("call", 0x140D68190, (rig.game, 14, 7)),
        ("call", HOST, ()),
        ("call", TIME, (rig.clock,)),
        ("call", PREDICATE, ()),
        ("call", ADVANCE, (rig.clock, f32(13.0))),
        ("call", TIME, (rig.clock,)),
        ("call", 0x1409033B0, (1019,)),
    ]


@pytest.mark.parametrize(("force", "expected"), [(0, 7), (1, 1), (0xFFFFFFFF, 1)])
def test_zero_cycle_idle_uses_current_status_and_skips_vector_reads(force, expected):
    rig = Rig(cycle=0)
    rig.memory.write(0x1442C40F0, 4, force)
    result = rig.run()
    assert (result.next_address, result.returned_status) == (None, expected)
    assert rig.memory.read(rig.world + 0x7C, 4) == 0
    assert ("read", rig.world + 0x768, 8) not in rig.events
    assert ("read", rig.world + 0x770, 8) not in rig.events
    assert not any(event[1] == PREDICATE for event in rig.call_events())
    assert len(rig.call_events()) == 7


@pytest.mark.parametrize(("cycle", "special"), [(13, 0), (0, 1), (0xFFFFFFFF, 0)])
def test_empty_vector_takes_real_idle_path_even_with_nonzero_cycle(cycle, special):
    rig = Rig(cycle=cycle, special=special)
    rig.memory.write(rig.world + 0x770, 8, 0x900F)  # SAR64 count is0.
    result = rig.run()
    assert result.returned_status == 7
    assert rig.memory.read(rig.world + 0x7C, 4) == 0
    assert not any(event[1] == PREDICATE for event in rig.call_events())


def test_negative_nonzero_header_count_is_admitted_without_invented_vector_validation():
    rig = Rig()
    rig.memory.write(rig.world + 0x770, 8, 0x8FF0)
    assert rig.run().next_address == 0x141628F0C


@pytest.mark.parametrize("missing", ["world_manager", "cycle_manager"])
def test_null_cycle_service_is_zero_and_not_a_fake_successful_provider(missing):
    rig = Rig(special=0)
    address = rig.world + 0x130 if missing == "world_manager" else rig.manager + 0x2008
    rig.memory.write(address, 8, 0)
    rig.handlers.pop(CYCLE)
    result = rig.run()
    assert result.cycle == 0 and result.returned_status == 7
    assert all(event[1] != CYCLE for event in rig.call_events())


def test_second_timer_can_replace_game_but_instrumentation_uses_held_game():
    rig = Rig(cycle=0)
    new_game = rig.memory.allocate(0x226)
    rig.memory.write(new_game + 0x225, 1, 1)
    calls = 0

    def host(args):
        nonlocal calls
        calls += 1
        if calls == 2:
            rig.memory.write(GAME, 8, new_game)
        return [100, 107, 200][calls - 1]

    rig.handlers[HOST] = host
    rig.predicates = iter([0, 0])
    result = rig.run()
    assert result.next_address == 0x141628F0C
    assert ("call", 0x140D68190, (rig.game, 14, 7)) in rig.events
    assert rig.memory.read(rig.clock + 0x18, 4) == 1024  # Forced16 *1.5.


def test_each_clock_pointer_is_current_while_entry_time_remains_held():
    rig = Rig()
    replacement = rig.memory.allocate(0x1C)
    for offset, value in [(8, 1), (0xC, f32(2.0)), (0x10, f32(2.0)), (0x18, 2000)]:
        rig.memory.write(replacement + offset, 4, value)

    def read(address, width):
        if address == rig.world + 0x228:
            rig.memory.write(address, 8, replacement)

    rig.after_read = read
    result = rig.run()
    assert result.entry_time == 1000
    assert rig.memory.read(rig.world + 0x7D8, 4) == 14
    assert rig.memory.read(rig.world + 0x78, 4) == 2000
    assert rig.memory.read(replacement + 0x18, 4) == 2026
    assert rig.memory.read(rig.clock + 0x18, 4) == 1000


@pytest.mark.parametrize(
    ("previous", "now", "expected"),
    [
        (0, 200, 0),
        (100, 150, 50),
        (100, 250, 100),
        (0xFFFFFFF0, 5, 21),
    ],
)
def test_sentinel_cycle_uses_unsigned_elapsed_zero_origin_and_cap(previous, now, expected):
    rig = Rig(cycle=0xFFFFFFFF, previous_host=previous)
    rig.host_times = iter([1, 2, now])
    rig.run()
    assert ("call", ADVANCE, (rig.clock, f32(float(expected)))) in rig.events
    assert rig.memory.read(rig.world + 0x84, 4) == now


def test_sentinel_cycle_and_nonzero_al_skip_advance_but_continue_other_effects():
    rig = Rig(cycle=0xFFFFFFFF)
    rig.predicates = iter([0x123401])
    rig.run()
    assert rig.memory.read(rig.clock + 0x18, 4) == 1000
    assert all(event[1] != ADVANCE for event in rig.call_events())
    assert ("call", 0x1409033B0, (1000,)) in rig.events


@pytest.mark.parametrize(
    ("first", "second", "divisor", "expected"),
    [
        (0x100, 1, 50, 20),
        (1, 0x100, 50, 13),
        (0, 0, -60, 0xFFFFFFF0),
    ],
)
def test_independent_al_calls_and_current_signed_divisor(first, second, divisor, expected):
    rig = Rig(special=1)
    rig.predicates = iter([first, second])
    rig.memory.write(0x1431FE898, 4, divisor & 0xFFFFFFFF)
    rig.run()
    assert ("call", ADVANCE, (rig.clock, f32(float(expected)))) in rig.events
    assert sum(event[1] == PREDICATE for event in rig.call_events()) == 2


def test_debug_override_reads_current_product_and_uses_low_cvtt64_word_as_unsigned():
    rig = Rig()
    rig.memory.write(DEBUG, 4, 1)
    rig.memory.write(0x143DAE26C, 4, f32(-0.25))
    rig.run()
    assert ("call", ADVANCE, (rig.clock, f32(float(0xFFFFFFF1)))) in rig.events
    # Clock's own debug branch doubles its input independently of World override.
    assert rig.memory.read(rig.clock + 0x18, 4) == 1000


def test_logger_sees_actual_partially_written_aliased_homes_and_mutation_persists():
    rig = Rig()
    rig.memory.write(0x144355062, 1, 255)
    rig.memory.write(rig.frame + 0x7C, 4, 0xAABBCCDD)

    def log(args):
        assert args == (0xCC00, 0x2A, 0x1432EA140, 1, rig.frame + 0x2B0)
        assert rig.memory.read(rig.frame + 0x80, 4) == 7
        assert rig.memory.read(rig.frame + 0x78, 8) == 0xAABBCCDD0000000D
        assert rig.memory.read(rig.frame + 0x20, 8) == rig.frame + 0x2B0
        assert rig.memory.read(rig.frame + 0x2B0, 8) == rig.frame + 0x78
        rig.memory.write(rig.frame + 0x78, 4, 999)

    rig.handlers[0x14101ADB0] = log
    result = rig.run()
    assert result.cycle == 13
    assert rig.memory.read(rig.frame + 0x78, 4) == 999
    assert ("call", ADVANCE, (rig.clock, f32(13.0))) in rig.events


@pytest.mark.parametrize(("elapsed", "saves"), [(600000, False), (600001, True)])
def test_maintenance_threshold_is_strict_and_save_uses_actual_returned_world(elapsed, saves):
    rig = Rig(clock_time=elapsed)
    rig.memory.write(0x144418DC8, 1, 1)
    rig.memory.write(rig.clock + 0x10, 4, 0)  # Native clock still runs, rate0.
    other_world = rig.memory.allocate(0x138)
    rig.memory.write(other_world + 0x130, 8, 0xABBA)
    rig.handlers[0x140D6ACC0] = lambda args: other_world

    def save(args):
        assert args == (0xABBA,)
        rig.memory.write(rig.clock + 0x18, 4, 987654)

    rig.handlers[0x140F4AD30] = save
    rig.run()
    assert any(event[1] == 0x140F4AD30 for event in rig.call_events()) is saves
    assert rig.memory.read(rig.world + 0x90, 4) == (987654 if saves else 0)


def test_parsed_maintenance_threshold_is_held_across_real_cleanup_and_clock_wrap():
    rig = Rig(clock_time=10)
    rig.memory.write(0x144418DC8, 1, 1)
    rig.memory.write(0x144418E98, 1, 1)
    rig.memory.write(rig.world + 0x90, 4, 0xFFFFFFF0)
    rig.memory.write(rig.clock + 0x10, 4, 0)
    string = rig.frame + 0x218

    def construct(args):
        assert args == (string, 0x144418EA0)
        assert [rig.memory.read(string + i, 8) for i in (0, 8, 16)] == [0x14428BB30, 0, 0]

    def cleanup(args):
        assert args == (string,)
        rig.memory.write(string, 4, f32(999999.0))

    def parse(args):
        assert args == (string, 0)  # Explicit native XMM1 fallback is+0.0f.
        return f32(25.9)

    rig.handlers[0x140A15B60] = construct
    rig.handlers[0x140A1FDF0] = parse
    rig.handlers[0x140A1B220] = cleanup
    rig.run()
    assert ("call", 0x140F4AD30, (rig.manager,)) in rig.events  # u32elapsed26 >25.
    assert rig.memory.read(rig.world + 0x90, 4) == 10
    selected = [
        event[1]
        for event in rig.call_events()
        if event[1] in (0x140A15B60, 0x140A1FDF0, 0x140A1B220, 0x140D6ACC0, 0x140F4AD30)
    ]
    assert selected == [0x140A15B60, 0x140A1FDF0, 0x140A1B220, 0x140D6ACC0, 0x140F4AD30]


def test_descriptor_inactive_skips_unbacked_string_and_threshold_fields():
    rig = Rig()
    rig.memory.write(0x144418DC8, 1, 1)
    rig.memory.write(rig.descriptor, 1, 0)
    rig.run()
    assert ("read", 0x144418E98, 1) not in rig.events
    assert all(event[1] != 0x140D6ACC0 for event in rig.call_events())


def test_missing_mandatory_child_and_zero_divisor_retain_prior_effects():
    rig = Rig(special=1)
    rig.memory.write(0x1431FE898, 4, 0)
    with pytest.raises(UnresolvedReplayTaskRebuild, match="divisor is zero"):
        rig.run()
    assert rig.memory.read(rig.world + 0x7D8, 4) == 10
    assert rig.memory.read(0x144418594, 4) == 0
    assert rig.memory.read(rig.world + 0x84, 4) == 100
    with pytest.raises(ReplayMemoryError):
        rig.memory.read(rig.world + 0x78, 4)
    other = Rig()
    other.handlers.pop(0x1409033B0)
    with pytest.raises(UnresolvedReplayTaskRebuild, match="1409033b0"):
        other.run()
    assert other.memory.read(other.clock + 0x18, 4) == 1019
    assert other.memory.read(other.world + 0x84, 4) == 200


@pytest.mark.parametrize("bad", [True, -1, 1 << 64, None])
def test_bad_abi_and_profile_refuse_before_first_logical_store(bad):
    rig = Rig()
    with pytest.raises(ValueError):
        run_replay_world_update_prelude(
            rig.storage,
            rig.calls,
            bad,
            1,
            logical_frame=rig.frame,
            mxcsr=0x1F80,
        )
    assert not rig.events
    with pytest.raises(ValueError):
        run_replay_world_update_prelude(
            rig.storage,
            rig.calls,
            rig.world,
            1,
            logical_frame=rig.frame,
            mxcsr=0x9F80,
        )
    assert not rig.events


@pytest.mark.parametrize("slot", [0, 1, 2])
@pytest.mark.parametrize("upper", [1, 0x80000000, 0xFFFFFFFF])
def test_host_clock_uses_low_dword_at_each_reached_call(slot, upper):
    rig = Rig()
    words = [100, 107, 200]
    words[slot] |= upper << 32
    rig.host_times = iter(words)
    result = rig.run()
    assert result.next_address == 0x141628F0C
    assert ("call", 0x140D68190, (rig.game, 14, 7)) in rig.events
    assert rig.memory.read(rig.world + 0x84, 4) == 200
    assert rig.memory.read(rig.clock + 0x18, 4) == 1019
    assert sum(event[1] == HOST for event in rig.call_events()) == 3


@pytest.mark.parametrize("invalid", [-1, 1 << 64, True, None])
def test_host_clock_still_requires_raw_u64_and_retains_reached_prefix(invalid):
    rig = Rig()
    rig.host_times = iter([100, invalid, 200])
    with pytest.raises(ValueError):
        rig.run()
    assert rig.memory.read(rig.world + 0x7D8, 4) == 10
    assert rig.memory.read(rig.world + 0x84, 4) == 100
    assert sum(event[1] == HOST for event in rig.call_events()) == 2
    assert all(event[1] != 0x140D68190 for event in rig.call_events())
    with pytest.raises(ReplayMemoryError):
        rig.memory.read(rig.world + 0x78, 4)


@pytest.mark.parametrize(
    ("cycle", "counters", "instrument", "now", "clock_time"),
    [
        (13, [0x100000064, 0x20000006B, 0x3000000C8], 7, 200, 1019),
        (0, [0x1FFFFFFF0, 0x200000005], 21, 0xFFFFFFF0, 1000),
        (0xFFFFFFFF, [0x1FFFFFFF0, 0x200000005, 0x300000005], 21, 5, 1031),
        (0xFFFFFFFF, [1 << 63, (1 << 64) - 1, 1 << 63], 0, 0, 1150),
    ],
)
def test_prelude_composes_actual_raw64_clock(cycle, counters, instrument, now, clock_time):
    rig = Rig(cycle=cycle, previous_host=100 if now == 0 else 0xFFFFFFF0)
    rig.memory.map_bytes(0x14428FA88, struct.pack("<d", 1.0))
    rig.memory.map_bytes(0x1431FED08, struct.pack("<d", 1.0))
    remaining = iter(counters)
    counter_events = []

    def counter(args):
        assert args == ()
        value = next(remaining)
        counter_events.append(value)
        return value

    rig.handlers[0x140973210] = counter
    unused = ReplayTaskRebuildCalls(None)
    actual = bind_replay_command_batch(
        rig.storage,
        rig.calls,
        watson_home_calls=unused,
        error_home_calls=unused,
        atomics=ReplayUnitAIMapAtomics(None, rig.memory.fetch_add_u32),
        bind_local=rig.memory.bind_local,
        profile=ReplayCommandBatchProfile(
            b"\xa5" * 0x28,
            b"\xb6" * 0x28,
            b"\xc7" * 0x50,
            b"\xd8" * 0xB0,
        ),
        mxcsr=0x1F80,
    )

    def host(args):
        return actual.call(HOST, args, None)

    rig.handlers[HOST] = host
    result = rig.run()
    assert counter_events == counters
    assert ("call", 0x140D68190, (rig.game, 14, instrument)) in rig.events
    assert rig.memory.read(rig.world + 0x84, 4) == now
    assert rig.memory.read(rig.clock + 0x18, 4) == clock_time
    assert (result.next_address, result.returned_status) == (
        (None, 7) if cycle == 0 else (0x141628F0C, None)
    )
