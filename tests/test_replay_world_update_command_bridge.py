"""Source-first World caller controls; all deeper children are explicit."""

from dataclasses import replace

import pytest

from vantage.replay_memory import ReplayMemory, ReplayMemoryError
from vantage.replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
)
from vantage.replay_world_update_command_bridge import (
    run_replay_world_update_command_bridge,
)
from vantage.replay_world_update_replay_phase import ReplayWorldUpdateReplayPhase

GET, PRED, NOTIFY, LOG = 0x141021E00, 0x1410221C0, 0x1410242D0, 0x14101ADB0
REGISTRY, MAINTAIN, MARK, CLEAR = 0x140FDDBF0, 0x14148C300, 0x140F55750, 0x140F54480
GAME_CONFIG, PAIR, FIRST = 0x140D6ADB0, 0x140A80160, 0x140A801F0
QUEUE, FORMATION, BEGIN = 0x140F51FC0, 0x14162BAB0, 0x140E08860
U32 = 0xFFFFFFFF


class Rig:
    def __init__(self):
        self.memory = ReplayMemory()
        self.events, self.handlers, self.home_handlers = [], {}, {}
        self.after_read, self.after_write = None, None
        self.world, self.frame = self.alloc(0x800), self.alloc(0x2B8, 0xA5)
        self.player, self.vector = self.alloc(0x230), self.alloc(16)
        self.settings = self.alloc(0x5B60)
        for offset, width, value in (
            (0x130, 8, 0xBB),
            (0x138, 8, 0xAA),
            (0x6B0, 4, 0),
            (0x768, 8, self.vector),
            (0x770, 8, self.vector + 16),
            (0x98, 8, self.settings),
            (0x7C, 4, 250),
            (0x7D0, 4, 777),
            (0x188, 4, 88),
        ):
            self.put(self.world + offset, width, value)
        self.put(self.vector, 8, self.player)
        self.put(self.player + 0x228, 4, 0x3F800000)
        self.put(self.player + 0x22C, 4, 0x40000000)
        self.put(self.settings + 0x5B5C, 4, 1000)
        for address, width, value in (
            (0x14435505D, 1, 0),
            (0x143DA5054, 4, U32),
            (0x144353698, 8, 0),
            (0x1431FE88C, 4, 0x3F800000),
            (0x1436A02F8, 4, 0x447A0000),
            (0x1444185CC, 4, U32),
            (0x1442DA8A0, 8, 0xCC),
        ):
            self.memory.map_bytes(address, value.to_bytes(width, "little"))

        def read(address, width):
            self.events.append(("read", address, width))
            value = self.memory.read(address, width)
            if self.after_read:
                self.after_read(address, width)
            return value

        def write(address, width, value):
            self.events.append(("write", address, width, value))
            self.memory.write(address, width, value)
            if self.after_write:
                self.after_write(address, width, value)

        def call(target, args, data):
            self.events.append(("call", target, args))
            assert data is None
            if target not in self.handlers:
                raise UnresolvedReplayTaskRebuild(f"actual authored bridge child{target:x} absent")
            return self.handlers[target](args)

        def home(target, args, data):
            self.events.append(("home", target, args))
            assert data is None
            if target not in self.home_handlers:
                raise UnresolvedReplayTaskRebuild(f"required HOME child{target:x} absent")
            return self.home_handlers[target](args)

        self.storage = ReplayTaskRebuildStorage(1, read, write)
        self.calls, self.homes = ReplayTaskRebuildCalls(call), ReplayTaskRebuildCalls(home)
        self.handlers = {
            GET: lambda args: 0xABC,
            PRED: lambda args: 0x100,
            REGISTRY: lambda args: None,
            MAINTAIN: lambda args: None,
            MARK: lambda args: None,
            CLEAR: lambda args: None,
            QUEUE: lambda args: None,
            FORMATION: lambda args: None,
            BEGIN: lambda args: None,
        }
        self.phase = ReplayWorldUpdateReplayPhase(
            self.world,
            self.frame,
            1000,
            13,
            1,
            0xBF800000,
            0x14162951F,
            None,
        )

    def alloc(self, size, byte=0):
        address = self.memory.allocate(size)
        self.memory.write_bytes(address, bytes([byte]) * size)
        return address

    def put(self, address, width, value):
        self.memory.write(address, width, value & ((1 << (8 * width)) - 1))

    def get(self, address, width=4):
        return self.memory.read(address, width)

    def run(self, phase=None, mxcsr=0x1F80):
        return run_replay_world_update_command_bridge(
            self.storage,
            self.calls,
            self.phase if phase is None else phase,
            notification_home_calls=self.homes,
            logger_home_calls=self.homes,
            mxcsr=mxcsr,
        )

    def calls_to(self, target):
        return [e[2] for e in self.events if e[0] in ("call", "home") and e[1] == target]

    def targets(self):
        return [e[1] for e in self.events if e[0] in ("call", "home")]

    def config(self, divisor):
        game, config = self.alloc(1), self.alloc(0x5D4)
        self.put(0x144353698, 8, game)
        self.put(config + 0x5CC, 4, divisor)
        self.put(config + 0x5D0, 4, 0x12345678)
        self.handlers[GAME_CONFIG] = lambda args: config

        def pair(args):
            self.put(args[0], 4, args[1])
            self.put(args[0] + 4, 4, args[2])

        self.handlers[PAIR] = pair
        self.handlers[FIRST] = lambda args: self.get(args[0])
        return game, config


def test_basic_bridge_retains_held_phase_and_exact_call_order():
    rig = Rig()
    result = rig.run()
    assert (
        result.world,
        result.logical_frame,
        result.entry_time,
        result.cycle,
        result.status,
        result.default_time,
        result.next_address,
        result.returned_status,
    ) == (
        rig.world,
        rig.frame,
        1000,
        13,
        1,
        0xBF800000,
        0x141629793,
        None,
    )
    assert rig.targets() == [GET, PRED, REGISTRY, MAINTAIN, MARK, CLEAR, QUEUE, FORMATION, BEGIN]
    assert rig.calls_to(REGISTRY) == [(777,)]
    assert rig.calls_to(MAINTAIN) == [(0xAA,)]
    assert rig.calls_to(QUEUE) == [(0xBB,)] and rig.calls_to(BEGIN) == [(0xCC,)]
    assert rig.get(rig.world + 0x158) == 0x3F800000
    assert rig.get(rig.world + 0x15C) == 0x40000000
    assert rig.get(rig.world + 0x160) == 0x3F000000
    assert rig.get(rig.world + 0x164) == 0x3E800000
    assert rig.get(0x1444185CC) == 0
    assert rig.memory.read_bytes(rig.frame + 0x278, 36) == bytes(36)
    assert rig.memory.read_bytes(rig.frame + 0x98, 8) == bytes(8)
    assert rig.memory.read_bytes(rig.frame, 0x20) == b"\xa5" * 0x20


def test_notification_uses_second_getter_and_live_dword_home_location():
    rig = Rig()
    gets = iter((0xABC, 0xDEF))
    rig.handlers[GET] = lambda args: next(gets)
    rig.handlers[PRED] = lambda args: 0x101

    def notify(args):
        assert args == (0xDEF, 1, 0x1432EA178, 0x1432E98F0, rig.frame + 0x20)
        assert rig.get(args[4]) == 0xF8C
        assert rig.get(args[4] + 4) == 0xA5A5A5A5

    rig.home_handlers[NOTIFY] = notify
    rig.run()
    assert rig.targets()[:5] == [GET, PRED, GET, NOTIFY, REGISTRY]


def test_logger_receives_low_byte_and_nested_current_home_pointer():
    rig = Rig()
    rig.put(0x14435505D, 1, 0xFF)
    rig.memory.map_bytes(0x144355068, (0x987).to_bytes(8, "little"))

    def log(args):
        assert args == (0x987, 0x25, 0x1432EA190, 1, rig.frame + 0x20)
        assert rig.get(args[4], 8) == rig.frame + 0x2B0
        assert rig.get(rig.frame + 0x2B0, 8) == rig.frame + 0x78
        assert rig.get(rig.frame + 0x78) == 88 and rig.get(rig.frame + 0x80) == 2
        rig.put(rig.world + 0x138, 8, 0x456)

    rig.home_handlers[LOG] = log
    rig.run()
    assert rig.targets()[2:5] == [REGISTRY, LOG, MAINTAIN]
    assert rig.calls_to(MAINTAIN) == [(0x456,)]


def test_command_manager_is_reloaded_between_mandatory_children():
    rig = Rig()
    rig.handlers[MARK] = lambda args: rig.put(rig.world + 0x130, 8, 0xDDD)
    rig.run()
    assert rig.calls_to(MARK) == [(0xBB,)]
    assert rig.calls_to(CLEAR) == [(0xDDD,)] and rig.calls_to(QUEUE) == [(0xDDD,)]


@pytest.mark.parametrize("invalid", ["sentinel", "past_end"])
def test_invalid_player_still_reaches_unconditional_pointer_read(invalid):
    rig = Rig()
    rig.put(rig.world + 0x6B0, 4, U32 if invalid == "sentinel" else 1)
    with pytest.raises(ReplayMemoryError):
        rig.run()
    assert rig.events[-1] == ("read", 0x228, 4)
    assert rig.calls_to(QUEUE) == []


def test_camera_uses_second_begin_sample_taken_before_first_coordinate_store():
    rig = Rig()
    second, third = rig.alloc(0x230), rig.alloc(0x230)
    second_vector, third_vector = rig.alloc(16), rig.alloc(16)
    rig.put(second_vector, 8, second)
    rig.put(third_vector, 8, third)
    rig.put(second + 0x22C, 4, 0xAABBCCDD)
    rig.put(third + 0x22C, 4, 0x11223344)
    reads = 0

    def read(address, width):
        nonlocal reads
        if address == rig.world + 0x768:
            reads += 1
            if reads == 1:
                rig.put(address, 8, second_vector)
                rig.put(rig.world + 0x770, 8, second_vector + 16)

    def write(address, width, value):
        if address == rig.world + 0x158:
            rig.put(rig.world + 0x768, 8, third_vector)
            rig.put(rig.world + 0x770, 8, second_vector + 16)

    rig.after_read, rig.after_write = read, write
    rig.run()
    assert reads == 2
    assert rig.get(rig.world + 0x158) == 0x3F800000
    assert rig.get(rig.world + 0x15C) == 0xAABBCCDD


def test_second_player_selection_reads_current_invalid_index_after_first_store():
    rig = Rig()

    def hook(address, width, value):
        if address == rig.world + 0x158:
            rig.put(0x143DA5054, 4, 0)

    rig.after_write = hook
    with pytest.raises(ReplayMemoryError):
        rig.run()
    assert rig.get(rig.world + 0x158) == 0x3F800000
    assert rig.events[-1] == ("read", 0x22C, 4)


def test_two_config_getters_hold_first_gate_but_use_fresh_game_and_second_pointer():
    rig = Rig()
    game, config = rig.config(2)
    rig.put(rig.settings + 0x5B5C, 4, 3)
    calls = 0

    def getter(args):
        nonlocal calls
        calls += 1
        if calls == 1:
            assert args == (game,)
            rig.put(0x144353698, 8, 0x123456)
            return 0xFED
        assert args == (0x123456,)
        return config

    rig.handlers[GAME_CONFIG] = getter
    rig.run()
    assert rig.calls_to(PAIR) == [(rig.frame + 0x2B0, 2, 0x12345678)]
    assert rig.get(rig.world + 0x160) == 0x3FC00000


def test_config_fields_are_read_second_then_first_before_actual_pair_calls():
    rig = Rig()
    _, config = rig.config(2)

    def hook(address, width):
        if address == config + 0x5D0:
            rig.put(config + 0x5CC, 4, 4)

    rig.after_read = hook
    rig.run()
    assert rig.calls_to(PAIR) == [(rig.frame + 0x2B0, 4, 0x12345678)]
    assert rig.calls_to(FIRST) == [(rig.frame + 0x2B0,)]
    assert rig.get(rig.world + 0x160) == 0x437A0000  # 1000/4=250.


def test_zero_divisor_uses_masked_sse_infinity_and_unsigned_world_delta():
    rig = Rig()
    rig.config(0)
    rig.put(rig.world + 0x7C, 4, U32)
    rig.put(0x1436A02F8, 4, 0x3F800000)
    rig.run()
    assert rig.get(rig.world + 0x160) == 0x7F800000
    assert rig.get(rig.world + 0x164) == 0x4F800000


def test_signed_setting_and_divisor_are_converted_separately():
    rig = Rig()
    rig.config(U32)
    rig.put(rig.settings + 0x5B5C, 4, U32)
    rig.run()
    assert rig.get(rig.world + 0x160) == 0x3F800000


def test_formation_refusal_preserves_queue_counter_and_prior_float_publication():
    rig = Rig()
    del rig.handlers[FORMATION]
    with pytest.raises(UnresolvedReplayTaskRebuild):
        rig.run()
    assert rig.calls_to(QUEUE) == [(0xBB,)] and rig.get(0x1444185CC) == 0
    assert rig.get(rig.world + 0x160) == 0x3F000000
    assert rig.memory.read_bytes(rig.frame + 0x98, 8) == b"\xa5" * 8
    assert rig.calls_to(BEGIN) == []


@pytest.mark.parametrize("mutation", [None, 0x01, 0xFF])
def test_live_byte_compare_after_zero_stores_is_not_folded(mutation):
    rig = Rig()
    seen = []

    def write(address, width, value):
        if mutation is not None and address == rig.frame + 0x9C:
            rig.put(rig.frame + 0x99, 1, mutation)

    def read(address, width):
        if width == 1 and rig.frame + 0x98 <= address < rig.frame + 0xA0:
            seen.append(address - rig.frame)

    rig.after_write, rig.after_read = write, read
    rig.run()
    assert seen == (
        [0x98, 0x9C, 0x99, 0x9D]
        if mutation is not None
        else [0x98, 0x9C, 0x99, 0x9D, 0x9A, 0x9E, 0x9B, 0x9F]
    )
    assert rig.memory.read_bytes(rig.frame + 0x278, 36) == bytes(36)


@pytest.mark.parametrize("phase", ["returned", "wrong_address"])
def test_requires_exact_previous_phase_handoff(phase):
    rig = Rig()
    bad = (
        replace(rig.phase, returned_status=4, next_address=None)
        if phase == "returned"
        else replace(rig.phase, next_address=0x141629520)
    )
    with pytest.raises(ValueError):
        rig.run(bad)
    assert rig.events == []


@pytest.mark.parametrize("mxcsr", [0, 0x9F80, 0x3F80])
def test_rejects_unsupported_fp_mode_before_effects(mxcsr):
    rig = Rig()
    with pytest.raises(ValueError):
        rig.run(mxcsr=mxcsr)
    assert rig.events == []
