"""Source-led addressed clock order, raw FP words and current-storage controls."""

from __future__ import annotations

import struct

import pytest

from vantage.replay_clock_storage import bind_replay_clock_storage
from vantage.replay_memory import ReplayMemory, ReplayMemoryError
from vantage.replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
)

ADVANCE, RATE, TIME, SET_TIME = 0x140E68C40, 0x140E68F50, 0x140E68F70, 0x140E68FA0
FACTOR = 0x140973630
DEBUG, EXTERNAL, ONE, NUMERATOR = 0x1442C3FC4, 0x1442846E8, 0x1436A0294, 0x1436A02E0


def f32(value):
    return int.from_bytes(struct.pack("<f", value), "little")


def f64(value):
    return int.from_bytes(struct.pack("<d", value), "little")


class Rig:
    def __init__(self, *, debug=0, mode=1, scale=1.0, time=0, external=None):
        self.memory = ReplayMemory()
        self.clock = self.memory.allocate(0x1C)
        self.other = self.memory.allocate(0x28)
        self.memory.write(self.clock + 8, 4, mode)
        self.memory.write(self.clock + 0x10, 4, f32(scale))
        self.memory.write(self.clock + 0x18, 4, time)
        self.memory.map_bytes(DEBUG, debug.to_bytes(4, "little"))
        self.memory.map_bytes(
            EXTERNAL, (self.other if external is not None else 0).to_bytes(8, "little")
        )
        self.memory.map_bytes(ONE, bytes.fromhex("0000803f"))
        self.memory.map_bytes(NUMERATOR, bytes.fromhex("00007042"))
        if external is not None:
            self.memory.write(self.other + 0x20, 8, f64(external))
        self.events = []
        self.before_call = None
        self.after_read = None
        self.after_write = None

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

        def dispatch(target, args, data):
            self.events.append(("call", target, args, data))
            if self.before_call is not None:
                self.before_call(target, args, data)
            return self.binding.call(target, args, data)

        self.binding = bind_replay_clock_storage(
            ReplayTaskRebuildStorage(0x1234, read, write),
            ReplayTaskRebuildCalls(dispatch),
            mxcsr=0x1F80,
        )

    def run(self, value, *, clock=None):
        return self.binding.call(ADVANCE, (self.clock if clock is None else clock, value), None)


@pytest.mark.parametrize(
    ("mode", "external", "scale", "delta", "start", "rate", "end"),
    [
        (1, None, 1.5, 13.0, 100, 1.5, 119),
        (2, 120.0, 1.5, 20.5, 7, 0.75, 22),
        (1, 30.0, 2.0, -3.75, 2, 4.0, 0xFFFFFFF3),
        (2, None, 1.0, 4294967808.0, 0, 1.0, 512),
        (1, None, 1.0, -4294967808.0, 0, 1.0, 0xFFFFFE00),
    ],
)
def test_ordinary_mode_uses_held_binary32_rate_then_cvtt64_low_dword(
    mode,
    external,
    scale,
    delta,
    start,
    rate,
    end,
):
    rig = Rig(mode=mode, external=external, scale=scale, time=start)
    assert rig.run(f32(delta)) is None
    assert rig.memory.read(rig.clock + 0xC, 4) == f32(rate)
    assert rig.memory.read(rig.clock + 0x18, 4) == end


@pytest.mark.parametrize(
    ("delta", "end"),
    [
        (13.75, 26),
        (-13.75, 0xFFFFFFE4),
        (0.0, 0xFFFFFFFF),
        (4294967808.0, 1023),
    ],
)
def test_debug_ignores_mode_and_rate_for_increment_but_publishes_rate(delta, end):
    rig = Rig(debug=0xFFFFFFFF, mode=99, external=40.0, scale=2.0, time=0xFFFFFFFF)
    assert rig.run(f32(delta)) is None
    assert rig.memory.read(rig.clock + 0x14, 4) == f32(1.5)
    assert rig.memory.read(rig.clock + 0xC, 4) == f32(3.0)
    assert rig.memory.read(rig.clock + 0x18, 4) == end
    assert ("read", rig.clock + 8, 4) not in rig.events


@pytest.mark.parametrize("mode", [0, 3, 0xFFFFFFFF, 0x80000000])
def test_unadmitted_mode_reads_no_factor_scale_time_or_other_backing(mode):
    memory = ReplayMemory()
    memory.map_bytes(DEBUG, bytes(4))
    memory.map_bytes(0x1008, mode.to_bytes(4, "little"))
    events = []

    def read(address, width):
        events.append((address, width))
        return memory.read(address, width)

    binding = bind_replay_clock_storage(
        ReplayTaskRebuildStorage(1, read, memory.write),
        ReplayTaskRebuildCalls(None),
        mxcsr=0x1F80,
    )
    assert binding.call(ADVANCE, (0x1000, 0x7FA01234), None) is None
    assert events == [(DEBUG, 4), (0x1008, 4)]


def test_literal_current_storage_and_actual_child_order():
    rig = Rig(external=120.0, scale=3.0, time=11)
    rig.run(f32(20.0))
    c, e = rig.clock, rig.other
    assert rig.events == [
        ("read", DEBUG, 4),
        ("read", c + 8, 4),
        ("read", EXTERNAL, 8),
        ("call", FACTOR, (e,), None),
        ("read", e + 0x20, 8),
        ("read", NUMERATOR, 4),
        ("write", c + 0x14, 4, f32(0.5)),
        ("read", c + 0x10, 4),
        ("write", c + 0xC, 4, f32(1.5)),
        ("read", c + 0x18, 4),
        ("write", c + 0x18, 4, 41),
    ]


def test_child_can_change_globals_mode_and_fields_without_reselecting_held_path():
    rig = Rig(external=120.0)

    def child(target, args, data):
        assert (target, args, data) == (FACTOR, (rig.other,), None)
        rig.memory.write(DEBUG, 4, 1)
        rig.memory.write(EXTERNAL, 8, 0)
        rig.memory.write(rig.clock + 8, 4, 99)
        rig.memory.write(rig.clock + 0x10, 4, f32(3.0))
        rig.memory.write(rig.clock + 0x18, 4, 50)

    rig.before_call = child
    rig.run(f32(20.0))
    assert rig.memory.read(rig.clock + 0xC, 4) == f32(1.5)
    assert rig.memory.read(rig.clock + 0x18, 4) == 80
    assert sum(event == ("read", DEBUG, 4) for event in rig.events) == 1
    assert sum(event == ("read", EXTERNAL, 8) for event in rig.events) == 1


def test_scale_is_current_after_factor_store_and_rate_is_held_after_rate_store():
    rig = Rig(scale=9.0, time=1)

    def wrote(address, width, value):
        if address == rig.clock + 0x14:
            rig.memory.write(rig.clock + 0x10, 4, f32(2.0))
        if address == rig.clock + 0xC:
            rig.memory.write(rig.clock + 0xC, 4, f32(100.0))
            rig.memory.write(rig.clock + 0x18, 4, 5)

    rig.after_write = wrote
    rig.run(f32(3.75))
    assert rig.memory.read(rig.clock + 0xC, 4) == f32(100.0)
    assert rig.memory.read(rig.clock + 0x18, 4) == 12


def test_null_external_loads_current_one_word_without_hardcoded_factor():
    rig = Rig(scale=2.0)
    rig.memory.write(ONE, 4, f32(0.25))
    rig.run(f32(10.0))
    assert rig.memory.read(rig.clock + 0x14, 4) == f32(0.25)
    assert rig.memory.read(rig.clock + 0x18, 4) == 5
    assert all(event[0] != "call" for event in rig.events)


def test_separate_binary32_multiplies_do_not_fuse_or_use_host_double_product():
    rig = Rig(scale=1.0 + 2.0**-23)
    rig.memory.write(ONE, 4, 0x3F800001)
    rig.run(f32(8388607.5))
    # First MULSS rounds to1+2**-22. The second product is just below
    # 8388609.5 and rounds to8388609, before signed64 truncation.
    assert rig.memory.read(rig.clock + 0xC, 4) == 0x3F800002
    assert rig.memory.read(rig.clock + 0x18, 4) == 8388609


@pytest.mark.parametrize(
    ("word", "expected"),
    [
        (0x404E000000000000, 0x3F800000),  # 60 -> factor1.
        (0x405E000000000000, 0x3F000000),  # 120 -> factor.5.
        (0x0000000000000000, 0x7F800000),
        (0x8000000000000000, 0xFF800000),
        (0x7FF0000000000000, 0x00000000),
        (0xFFF0000000000000, 0x80000000),
        (0x7FF8000020000000, 0x7FC00001),
        (0x7FF0000020000000, 0x7FC00001),
        (0xFFF8000020000000, 0xFFC00001),
        (0x0000000000000001, 0x7F800000),  # Smallest double narrows to0.
        (0x47F0000000000000, 0x00000000),  # 2**128 narrows to infinity.
    ],
)
def test_complete_factor_child_narrows_binary64_then_divides(word, expected):
    rig = Rig()
    rig.memory.write(rig.other + 0x20, 8, word)
    assert rig.binding.call(FACTOR, (rig.other,), None) == expected
    assert rig.events == [("read", rig.other + 0x20, 8), ("read", NUMERATOR, 4)]


@pytest.mark.parametrize(
    ("word", "expected"),
    [
        (0x3FF0000010000000, 0x3F800000),  # 1+2**-24 -> even1.
        (0x3FF0000030000000, 0x3F7FFFFC),  # 1+3*2**-24 -> even1+2**-22.
        (0x3690000000000000, 0x7F800000),  # 2**-150 -> even0.
        (0xB690000000000000, 0xFF800000),
    ],
)
def test_factor_uses_two_roundings_including_even_ties_and_underflow(word, expected):
    rig = Rig()
    rig.memory.write(NUMERATOR, 4, f32(1.0))
    rig.memory.write(rig.other + 0x20, 8, word)
    assert rig.binding.call(FACTOR, (rig.other,), None) == expected


def test_factor_holds_binary64_before_current_numerator_load():
    rig = Rig()
    rig.memory.write(rig.other + 0x20, 8, f64(2.0))

    def read(address, width):
        if address == rig.other + 0x20:
            rig.memory.write(rig.other + 0x20, 8, f64(100.0))
            rig.memory.write(NUMERATOR, 4, f32(4.0))

    rig.after_read = read
    assert rig.binding.call(FACTOR, (rig.other,), None) == f32(2.0)


def test_factor_division_preserves_current_destination_nan_priority():
    rig = Rig()
    rig.memory.write(rig.other + 0x20, 8, 0x7FF8000020000000)
    rig.memory.write(NUMERATOR, 4, 0xFFA01234)
    assert rig.binding.call(FACTOR, (rig.other,), None) == 0xFFE01234


@pytest.mark.parametrize(
    "delta", [0x7FC00000, 0x7FA01234, 0x7F800000, 0xFF800000, 0x5F000000, 0xDF000000]
)
@pytest.mark.parametrize("debug", [0, 1])
def test_cvtt64_indefinite_and_int64_min_have_zero_low_dword(delta, debug):
    rig = Rig(debug=debug, time=37)
    rig.run(delta)
    assert rig.memory.read(rig.clock + 0x18, 4) == 37
    assert rig.memory.read(rig.clock + 0x14, 4) == f32(1.0)


def test_synchronous_reentry_keeps_outer_receiver_delta_and_current_accumulator():
    rig = Rig(external=60.0, time=10)
    inner = rig.memory.allocate(0x1C)
    rig.memory.write(inner + 8, 4, 1)
    rig.memory.write(inner + 0x10, 4, f32(2.0))
    rig.memory.write(inner + 0x18, 4, 100)
    depth = 0

    def child(target, args, data):
        nonlocal depth
        depth += 1
        if depth == 1:
            rig.run(f32(3.0), clock=inner)
            rig.memory.write(rig.clock + 0x18, 4, 20)
        depth -= 1

    rig.before_call = child
    rig.run(f32(7.0))
    assert rig.memory.read(inner + 0x18, 4) == 106
    assert rig.memory.read(rig.clock + 0x18, 4) == 27


def test_leaves_need_only_their_reached_field_and_setter_uses_low_edx():
    memory = ReplayMemory()
    memory.map_bytes(0x100C, bytes.fromhex("3412a07f"))
    memory.map_bytes(0x1018, bytes.fromhex("ffffffff"))
    binding = bind_replay_clock_storage(
        ReplayTaskRebuildStorage(7, memory.read, memory.write),
        ReplayTaskRebuildCalls(None),
        mxcsr=0x1FBF,
    )
    assert binding.call(RATE, (0x1000,), None) == 0x7FA01234
    assert binding.call(TIME, (0x1000,), None) == 0xFFFFFFFF
    assert binding.call(SET_TIME, (0x1000, 0xABCDEF0100000003), None) is None
    assert binding.call(TIME, (0x1000,), None) == 3


def test_address_wrap_and_low_float_lane():
    rig = Rig()
    rig.memory.map_bytes(0, bytes(0x14))
    rig.memory.write(0, 4, 1)
    rig.memory.write(8, 4, f32(2.0))
    rig.memory.write(0x10, 4, 5)
    assert rig.run((0x12345678 << 32) | f32(3.75), clock=(1 << 64) - 8) is None
    assert rig.memory.read(4, 4) == f32(2.0)
    assert rig.memory.read(0x10, 4) == 12


def test_missing_scale_retains_the_preceding_factor_store():
    rig = Rig()
    clock = rig.memory.allocate(0x1C)
    rig.memory.write(clock + 8, 4, 1)
    with pytest.raises(ReplayMemoryError):
        rig.run(f32(1.0), clock=clock)
    assert rig.memory.read(clock + 0x14, 4) == f32(1.0)
    with pytest.raises(ReplayMemoryError):
        rig.memory.read(clock + 0xC, 4)


@pytest.mark.parametrize("result", [None, True, -1, 1 << 32])
def test_invalid_actual_factor_result_refuses_before_clock_stores(result):
    rig = Rig(external=60.0)
    calls = ReplayTaskRebuildCalls(lambda target, args, data: result)
    binding = bind_replay_clock_storage(
        ReplayTaskRebuildStorage(5, rig.memory.read, rig.memory.write),
        calls,
        mxcsr=0x1F80,
    )
    with pytest.raises(ValueError):
        binding.call(ADVANCE, (rig.clock, f32(1.0)), None)
    with pytest.raises(ReplayMemoryError):
        rig.memory.read(rig.clock + 0x14, 4)


def test_missing_actual_child_and_exception_preserve_prior_real_child_effects():
    rig = Rig(external=60.0)
    storage = ReplayTaskRebuildStorage(5, rig.memory.read, rig.memory.write)
    binding = bind_replay_clock_storage(storage, ReplayTaskRebuildCalls(None), mxcsr=0x1F80)
    with pytest.raises(UnresolvedReplayTaskRebuild, match="140973630"):
        binding.call(ADVANCE, (rig.clock, f32(1.0)), None)

    def fail(target, args, data):
        rig.memory.write(rig.clock + 0x18, 4, 91)
        raise RuntimeError("actual child failed")

    binding = bind_replay_clock_storage(storage, ReplayTaskRebuildCalls(fail), mxcsr=0x1F80)
    with pytest.raises(RuntimeError, match="actual child failed"):
        binding.call(ADVANCE, (rig.clock, f32(1.0)), None)
    assert rig.memory.read(rig.clock + 0x18, 4) == 91
    with pytest.raises(ReplayMemoryError):
        rig.memory.read(rig.clock + 0x14, 4)


@pytest.mark.parametrize("mxcsr", [-1, True, None, 1 << 32, 0, 0x3F80, 0x1FC0, 0x9F80])
def test_explicit_fp_profile_rejects_invalid_or_unowned_control_modes(mxcsr):
    memory = ReplayMemory()
    with pytest.raises(ValueError):
        bind_replay_clock_storage(
            ReplayTaskRebuildStorage(1, memory.read, memory.write),
            ReplayTaskRebuildCalls(None),
            mxcsr=mxcsr,
        )


@pytest.mark.parametrize("target", [ADVANCE, RATE, TIME, SET_TIME, FACTOR])
def test_malformed_known_abi_fails_before_reads_or_writes(target):
    rig = Rig()
    args = (rig.clock, 0) if target in (ADVANCE, SET_TIME) else (rig.clock,)
    for bad_args, data in [
        ((), None),
        (args, memoryview(b"x")),
        ((*args, 0), None),
        ((True, *args[1:]), None),
    ]:
        with pytest.raises(ValueError):
            rig.binding.call(target, bad_args, data)
    assert rig.events == []


def test_unknown_target_preserves_raw_arguments_payload_and_result_identity():
    memory = ReplayMemory()
    marker = object()
    args, payload = (1, 2), memoryview(b"payload")
    seen = []

    def call(target, incoming, data):
        seen.append((target, incoming, data))
        return marker

    binding = bind_replay_clock_storage(
        ReplayTaskRebuildStorage(1, memory.read, memory.write),
        ReplayTaskRebuildCalls(call),
        mxcsr=0x1F80,
    )
    assert binding.call(0xABCD, args, payload) is marker
    assert seen[0][1] is args and seen[0][2] is payload
