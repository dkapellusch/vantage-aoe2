"""Source-led wrapper controls; core/math/CRT capabilities are authored.

No core implementation is imported or tested. Numeric oracle uses Python's
independent finite-float truncation, not the candidate's exponent-bit routine.
"""

from __future__ import annotations

import math
import struct
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from typing import cast

import pytest

from vantage.replay_file_decoder import (
    ReplayFileDecoderProfile,
    _cvtt64,
    _double_u32,
    bind_replay_file_decoder_homes,
)
from vantage.replay_memory import ReplayMemory, ReplayMemoryError
from vantage.replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
)

WRAPPER, CORE, COPY = 0x14178AE30, 0x14257FC20, 0x142D6E3B1
FMIN_IAT, COPY_IAT, MATH, COPY_OS = 0x143199E80, 0x143199930, 0xFA01, 0xFA02
U32, U64, INDEFINITE = (1 << 32) - 1, (1 << 64) - 1, 1 << 63
READ_INDEX, WRITE_INDEX, COMPLETE, RING = 0xA0B8, 0xA0BC, 0xA0C0, 0x20B8
INPUT_HIGH, OUTPUT_HIGH = 0xAABBCCDD00000000, 0x1122334400000000

type _Event = tuple[object, ...]
type _Handler = Callable[[tuple[int, ...]], int | None]
type _ReadHook = Callable[[int, int], None]
type _WriteHook = Callable[[int, int, int], None]


def double_word(value: float) -> int:
    return int.from_bytes(struct.pack("<d", value), "little")


def double_value(word: int) -> float:
    return float(struct.unpack("<d", word.to_bytes(8, "little"))[0])


def mathematical_cvtt(word: int) -> int:
    """Separate oracle: exact IEEE64 value, finite test, then mathematical truncation."""
    value = double_value(word)
    if not math.isfinite(value) or value < -(1 << 63) or value >= 1 << 63:
        return INDEFINITE
    return math.trunc(value) & U64


@dataclass(frozen=True)
class Step:
    status: int | None
    consumed: int
    produced: int
    payload: bytes = b""


class Rig:
    """Explicit fixture records, current homes and owned copy; no unknown success."""

    def __init__(self) -> None:
        self.memory = ReplayMemory()
        self.state = self.memory.allocate(0xA0C8)
        self.input_allocation = self.memory.allocate(64)
        self.input_base = self.input_allocation + 8
        self.memory.write_bytes(self.input_allocation, b"authored-input".ljust(64, b"."))
        self.output_allocation = self.memory.allocate(96)
        self.output_base = self.output_allocation + 16
        self.memory.write_bytes(self.output_allocation, b"." * 96)
        self.input_count = self.memory.allocate(8)
        self.output_count = self.memory.allocate(8)
        self.memory.write(self.input_count, 8, INPUT_HIGH | 12)
        self.memory.write(self.output_count, 8, OUTPUT_HIGH | 8)
        self.home = self.memory.allocate(32)
        self.homes = (self.home, self.home + 8, self.home + 16, self.home + 24)
        self.memory.fill(self.home, 0xC6, 32)
        for address, width, value in (
            (self.homes[0], 4, 0),
            (self.homes[1], 8, self.output_count),
            (self.homes[2], 8, self.state),
            (self.homes[3], 4, 0),
            (self.state + READ_INDEX, 4, 0),
            (self.state + WRITE_INDEX, 4, 0),
            (self.state + COMPLETE, 1, 0),
        ):
            self.memory.write(address, width, value)
        self.memory.write_bytes(self.state + RING, b"?" * 0x8000)
        self.memory.map_bytes(FMIN_IAT, MATH.to_bytes(8, "little"))
        self.memory.map_bytes(COPY_IAT, COPY_OS.to_bytes(8, "little"))
        self.events: list[_Event] = []
        self.locals: list[tuple[int, int, bytes]] = []
        self.active: list[int] = []
        self.final_frames: dict[int, bytes] = {}
        self.after_read: _ReadHook | None = None
        self.after_write: _WriteHook | None = None
        self.input_offset = 0
        self.steps = [Step(0, 3, 8, b"ABCDEFGH")]
        self.core_invocations = self.copy_invocations = 0
        self.copy_return: int | None = None
        self.profile = ReplayFileDecoderProfile(b"\xa5" * 0x68)

        def read(address: int, width: int) -> int:
            self.events.append(("r", address, width))
            value = self.memory.read(address, width)
            if self.after_read is not None:
                self.after_read(address, width)
            return value

        def write(address: int, width: int, value: int) -> None:
            self.events.append(("w", address, width, value))
            self.memory.write(address, width, value)
            if self.after_write is not None:
                self.after_write(address, width, value)

        self.storage = ReplayTaskRebuildStorage(1, read, write)
        self.math_handlers: dict[int, _Handler] = {MATH: self.minimum}
        self.copy_handler: _Handler = self.copy
        self.core_handler: _Handler = self.core

        def call(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
            assert data is None
            self.events.append(("c", target, args))
            if target != COPY:
                raise UnresolvedReplayTaskRebuild(f"authored child{target:x} unavailable")
            return self.copy_handler(args)

        def floating(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
            assert data is None
            self.events.append(("m", target, args))
            if target not in self.math_handlers:
                raise UnresolvedReplayTaskRebuild(f"authored math{target:x} unavailable")
            return self.math_handlers[target](args)

        def core_call(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
            assert target == CORE and data is None
            self.events.append(("core", target, args))
            self.core_invocations += 1
            return self.core_handler(args)

        self.calls = ReplayTaskRebuildCalls(call)
        self.math_calls = ReplayTaskRebuildCalls(floating)
        self.core_calls = ReplayTaskRebuildCalls(core_call)
        self.bind()

    @property
    def frame(self) -> int:
        return self.locals[0][0]

    def bind(
        self,
        *,
        calls: ReplayTaskRebuildCalls | None = None,
        math_calls: ReplayTaskRebuildCalls | None = None,
        core_calls: ReplayTaskRebuildCalls | None = None,
    ) -> None:
        self.bound = bind_replay_file_decoder_homes(
            self.storage,
            self.calls if calls is None else calls,
            math_calls=self.math_calls if math_calls is None else math_calls,
            core_home_calls=self.core_calls if core_calls is None else core_calls,
            bind_local=self.bind_local,
            profile=self.profile,
        )

    @contextmanager
    def bind_local(self, view: memoryview) -> Iterator[int]:
        with self.memory.bind_local(view) as address:
            self.locals.append((address, len(view), bytes(view)))
            self.active.append(address)
            self.events.append(("map", address, len(view)))
            try:
                yield address
            finally:
                self.final_frames[address] = self.memory.read_bytes(address, len(view))
                self.events.append(("unmap", address, len(view)))
                self.active.remove(address)

    def minimum(self, args: tuple[int, ...]) -> int:
        assert len(args) == 2
        first, second = (double_value(word) for word in args)
        assert first.is_integer() and second.is_integer() and 0 <= first <= U32
        assert 0 <= second <= U32
        # Explicit finite-u32 fmin fixture, not a default native math provider.
        return double_word(first if first <= second else second)

    def copy(self, args: tuple[int, ...]) -> int | None:
        assert len(args) == 3
        target = self.storage.read(COPY_IAT, 8)  # Actual6B thunk's current transfer.
        self.events.append(("copy", target, args))
        if target != COPY_OS:
            raise UnresolvedReplayTaskRebuild(f"authored memcpy{target:x} unavailable")
        destination, source, size = args
        self.memory.move(destination, source, size)  # Nonoverlapping fixture domain.
        self.copy_invocations += 1
        return self.copy_return  # Opaque ignored return; byte effects are real.

    def core(self, args: tuple[int, ...]) -> int | None:
        assert len(args) == 7
        if not self.steps:
            raise UnresolvedReplayTaskRebuild("no further authored core record")
        step = self.steps.pop(0)
        assert args[0] == self.state and args[3] == self.state + RING
        assert args[2] == self.frame + 0x58
        assert args[4:] == (self.frame + 0x20, self.frame + 0x28, self.frame + 0x30)
        output = self.memory.read(args[4], 8)
        actual_pointer = self.memory.read(args[5], 8)
        if step.payload:
            self.memory.write_bytes(output, step.payload)
        self.memory.write(args[2], 8, step.consumed)
        self.memory.write(actual_pointer, 8, step.produced)
        return step.status

    def invoke(self, *, output_base: int | None = None) -> int | None:
        return self.bound.call(
            WRAPPER,
            (
                self.input_base,
                self.input_offset,
                self.input_count,
                self.output_base if output_base is None else output_base,
                *self.homes,
            ),
            None,
        )

    def calls_to(self, target: int) -> list[tuple[int, ...]]:
        return [
            cast(tuple[int, ...], event[2])
            for event in self.events
            if event[0] in ("c", "m", "core", "copy") and event[1] == target
        ]

    def pending(self, payload: bytes) -> None:
        self.memory.write(self.state + WRITE_INDEX, 4, len(payload))
        self.memory.write_bytes(self.state + RING, payload)

    def assert_expired(self) -> None:
        assert not self.active
        for address, _, _ in self.locals:
            with pytest.raises(ReplayMemoryError, match="unmapped"):
                self.memory.read(address, 1)


@pytest.mark.parametrize(
    "word",
    [
        0,
        0x8000000000000000,
        1,
        0x8000000000000001,
        0x000FFFFFFFFFFFFF,
        0x800FFFFFFFFFFFFF,
        0x3FEFFFFFFFFFFFFF,
        0xBFEFFFFFFFFFFFFF,
        0x3FF0000000000000,
        0xBFF0000000000000,
        0x3FF8000000000000,
        0xBFF8000000000000,
        0x43DFFFFFFFFFFFFF,
        0xC3DFFFFFFFFFFFFF,
        0x43E0000000000000,
        0xC3E0000000000000,
        0x43E0000000000001,
        0xC3E0000000000001,
        0x7FEFFFFFFFFFFFFF,
        0xFFEFFFFFFFFFFFFF,
        0x7FF0000000000000,
        0xFFF0000000000000,
        0x7FF0000000000001,
        0xFFF8000000001234,
    ],
)
def test_masked_CVTT64_matches_independent_mathematical_truncation(word: int) -> None:
    assert _cvtt64(word) == mathematical_cvtt(word)


@pytest.mark.parametrize(
    "word,expected",
    [
        (0x3FF8000000000000, 1),
        (0xBFF8000000000000, U64),
        (0x43DFFFFFFFFFFFFF, 0x7FFFFFFFFFFFFC00),
        (0x43E0000000000000, INDEFINITE),
        (0xC3E0000000000000, INDEFINITE),
    ],
)
def test_CVTT64_literal_boundary_oracles(word: int, expected: int) -> None:
    assert _cvtt64(word) == expected


@pytest.mark.parametrize("value", [None, -1, True, 1 << 64])
def test_CVTT_requires_valid_raw_XMM_word_at_consumer(value: int | None) -> None:
    with pytest.raises(ValueError):
        _cvtt64(value)


@pytest.mark.parametrize(
    "value,word",
    [
        (0, 0),
        (1, 0x3FF0000000000000),
        (0x80000000, 0x41E0000000000000),
        (U32, 0x41EFFFFFFFE00000),
        (0x100000001, 0x3FF0000000000000),
    ],
)
def test_source_zeroextended_DWORD_to_binary64_has_literal_exact_words(
    value: int,
    word: int,
) -> None:
    assert _double_u32(value) == word


def test_positive_authored_core_math_and_real_copy_preserve_upper_count_DWORDs() -> None:
    r = Rig()
    assert r.invoke() == 0
    assert r.memory.read_bytes(r.output_base, 8) == b"ABCDEFGH"
    assert r.memory.read(r.input_count, 8) == INPUT_HIGH | 3
    assert r.memory.read(r.output_count, 8) == OUTPUT_HIGH | 8
    assert r.memory.read(r.state + COMPLETE, 1) == 1
    assert r.memory.read(r.state + WRITE_INDEX, 4) == 8
    assert r.memory.read(r.state + READ_INDEX, 4) == 8
    assert r.calls_to(MATH) == [(0x4020000000000000, 0x4020000000000000)]
    assert r.calls_to(COPY) == [(r.output_base, r.state + RING, 8)]
    assert r.copy_return is None  # Ignored copy return never fabricates bytes.
    completed = r.events.index(("w", r.state + COMPLETE, 1, 1))
    assert (
        completed
        < r.events.index(("w", r.input_count, 4, 3))
        < r.events.index(("w", r.output_count, 4, 8))
    )
    r.assert_expired()


def test_pending_only_copy_uses_masked_difference_and_final_DWORD_stores() -> None:
    r = Rig()
    r.memory.write(r.state + WRITE_INDEX, 4, 0x8004)
    r.memory.write_bytes(r.state + RING, b"RING")
    r.memory.write(r.output_count, 4, 4)
    assert r.invoke() == 0
    assert not r.calls_to(CORE)
    assert r.memory.read_bytes(r.output_base, 4) == b"RING"
    assert r.memory.read(r.input_count, 8) == INPUT_HIGH
    assert r.memory.read(r.output_count, 8) == OUTPUT_HIGH | 4
    assert r.memory.read(r.state + READ_INDEX, 4) == 4
    r.assert_expired()


def test_entry_HOME_order_holds_state_and_captures_later_current_output_pointer() -> None:
    r = Rig()
    other = r.memory.allocate(8)
    r.memory.write(other, 8, 0x8877665500000008)
    r.memory.write(r.state + COMPLETE, 1, 1)

    def read(address: int, width: int) -> None:
        if address == r.homes[2]:
            r.memory.write(r.homes[2], 8, 0xBAD)
            r.memory.write(r.homes[0], 4, U32)
        elif address == r.homes[0]:
            r.memory.write(r.homes[1], 8, other)
        elif address == r.homes[1]:
            r.memory.write(r.homes[1], 8, r.output_count)

    r.after_read = read
    assert r.invoke() == 0
    assert r.events[1:4] == [("r", r.homes[2], 8), ("r", r.homes[0], 4), ("r", r.homes[1], 8)]
    assert r.memory.read(other, 8) == 0x8877665500000000
    assert r.memory.read(r.output_count, 8) == OUTPUT_HIGH | 8
    assert not r.calls_to(CORE)
    r.assert_expired()


def test_equal_initial_offset_count_skips_even_completed_byte_and_preserves_seed() -> None:
    r = Rig()
    r.memory.write(r.output_count, 4, 0)
    assert r.invoke() == 0
    assert ("r", r.state + COMPLETE, 1) not in r.events
    assert not r.calls_to(MATH) and not r.calls_to(CORE) and not r.calls_to(COPY)
    expected = bytearray(b"\xa5" * 0x68)
    for offset, value in ((0x40, r.input_base), (0x48, r.output_base), (0x50, r.input_count)):
        expected[offset : offset + 8] = value.to_bytes(8, "little")
    assert r.final_frames[r.frame] == bytes(expected)
    assert r.events[:9] == [
        ("map", r.frame, 0x68),
        ("r", r.homes[2], 8),
        ("r", r.homes[0], 4),
        ("r", r.homes[1], 8),
        ("w", r.frame + 0x40, 8, r.input_base),
        ("r", r.state + WRITE_INDEX, 4),
        ("r", r.state + READ_INDEX, 4),
        ("w", r.frame + 0x48, 8, r.output_base),
        ("w", r.frame + 0x50, 8, r.input_count),
    ]
    r.assert_expired()


@pytest.mark.parametrize(
    "offset,pending,output_bias,expected_count",
    [
        (U32, True, 1, 1),
        (0x80000000, False, 0x80000000, 1),
    ],
)
def test_initial_signed64_and_loop_signed32_destination_offsets(
    offset: int,
    pending: bool,
    output_bias: int,
    expected_count: int,
) -> None:
    r = Rig()
    r.memory.write(r.homes[0], 4, offset)
    if pending:
        r.pending(b"P")
        r.memory.write(r.output_count, 4, 0)  # -1 + one copied byte reaches offset0.
    else:
        r.steps = [Step(0, 0, 1, b"L")]
    base = r.output_base + output_bias
    assert r.invoke(output_base=base) == 0
    assert r.calls_to(COPY)[0][0] == r.output_base
    assert r.memory.read(r.output_count, 4) == expected_count
    assert r.memory.read_bytes(r.output_base, 1) == (b"P" if pending else b"L")
    r.assert_expired()


@pytest.mark.parametrize(
    "input_offset,count,remaining,delta",
    [
        (0x100000001, 5, 4, 1),
        (U32, 0, 1, -1),
        (0, 0x80000000, 0xFFFFFFFF80000000, 0),
    ],
)
def test_inner_input_pointer_and_remaining_use_signed_low_DWORD_rules(
    input_offset: int,
    count: int,
    remaining: int,
    delta: int,
) -> None:
    r = Rig()
    r.input_offset = input_offset
    r.memory.write(r.input_count, 4, count)

    def core(args: tuple[int, ...]) -> int:
        assert args[1] == (r.input_base + delta) & U64
        assert r.memory.read(args[2], 8) == remaining
        return U32  # Deliberate negative authored core: no count postprocessing.

    r.core_handler = core
    assert r.invoke() == 0xFFFFFFFE
    r.assert_expired()


@pytest.mark.parametrize("flag,expected", [(0, 2), (1, 0), (0x80000000, 0)])
def test_late_outerflag_read_and_inner_live_partial_HOME_order(flag: int, expected: int) -> None:
    r = Rig()

    def write(address: int, width: int, value: int) -> None:
        if address == r.frame + 0x58:
            r.memory.write(r.homes[3], 4, flag)

    def read(address: int, width: int) -> None:
        if address == r.homes[3]:
            r.memory.write(r.homes[3], 4, 0 if flag else 1)

    def core(args: tuple[int, ...]) -> int:
        assert args[4:] == (r.frame + 0x20, r.frame + 0x28, r.frame + 0x30)
        assert r.memory.read(args[4], 8) == r.state + RING
        assert r.memory.read(args[5], 8) == r.frame + 0x60
        assert r.memory.read(args[6], 8) == 0xA5A5A5A500000000 | expected
        return U32

    r.after_write, r.after_read, r.core_handler = write, read, core
    assert r.invoke() == 0xFFFFFFFE
    ordered = [
        ("w", r.frame + 0x58, 8, 12),
        ("r", r.homes[3], 4),
        ("w", r.frame + 0x60, 8, 0x8000),
        ("w", r.frame + 0x30, 4, expected),
        ("w", r.frame + 0x28, 8, r.frame + 0x60),
        ("w", r.frame + 0x20, 8, r.state + RING),
    ]
    start = r.events.index(ordered[0])
    assert r.events[start : start + len(ordered)] == ordered
    r.assert_expired()


def test_outgoing_inner_HOME_addresses_remain_live_during_core_capability() -> None:
    r = Rig()
    other = r.memory.allocate(8)
    r.memory.write(other, 8, 0x123)

    def write(address: int, width: int, value: int) -> None:
        if address == r.frame + 0x20:
            r.memory.write(r.frame + 0x28, 8, other)
            r.memory.write(r.frame + 0x30, 4, 77)

    def core(args: tuple[int, ...]) -> int:
        assert r.memory.read(args[5], 8) == other
        assert r.memory.read(args[6], 4) == 77
        return U32

    r.after_write, r.core_handler = write, core
    assert r.invoke() == 0xFFFFFFFE
    assert r.memory.read(other, 8) == 0x123
    r.assert_expired()


@pytest.mark.parametrize("status", [0x80000000, U32, 0x100000000 | 0x80000000, U64 - 1])
def test_negative_inner_EAX_keeps_earlier_copy_but_skips_count_reads_and_final_stores(
    status: int,
) -> None:
    r = Rig()
    r.pending(b"P")
    r.steps = [Step(status, 0x123, 0x456, b"Q")]
    assert r.invoke() == 0xFFFFFFFE
    assert r.memory.read_bytes(r.output_base, 1) == b"P"
    assert r.memory.read(r.state + READ_INDEX, 4) == 1
    assert r.memory.read(r.state + WRITE_INDEX, 4) == 1
    assert r.memory.read(r.input_count, 8) == INPUT_HIGH | 12
    assert r.memory.read(r.output_count, 8) == OUTPUT_HIGH | 8
    barrier = next(i for i, e in enumerate(r.events) if e[0] == "core")
    assert ("r", r.frame + 0x58, 8) not in r.events[barrier + 1 :]
    assert ("r", r.frame + 0x60, 8) not in r.events[barrier + 1 :]
    assert not any(e[0] == "w" and e[1] in (r.input_count, r.output_count) for e in r.events)
    r.assert_expired()


@pytest.mark.parametrize("raw", [None, -1, True, 1 << 64])
def test_invalid_inner_raw_refuses_before_post_core_count_reads(raw: int | None) -> None:
    r = Rig()
    r.steps = [Step(raw, 3, 2, b"XY")]
    with pytest.raises(ValueError):
        r.invoke()
    assert ("r", r.frame + 0x58, 8) not in r.events
    assert ("r", r.frame + 0x60, 8) not in r.events
    assert r.memory.read_bytes(r.state + RING, 2) == b"XY"
    r.assert_expired()


def test_wholeQ_production_gate_and_separate_current58_60_samples_use_lowD_totals() -> None:
    r = Rig()
    r.steps = [Step(0x8000000000000001, 0x100000003, 0)]

    def read(address: int, width: int) -> None:
        if address == r.frame + 0x58:
            r.memory.write(r.frame + 0x58, 8, 0x999)
            r.memory.write(r.frame + 0x60, 8, 0x100000000)

    r.after_read = read
    assert r.invoke() == 0
    assert r.calls_to(MATH) == [(0, double_word(8.0))]
    assert r.calls_to(COPY) == [(r.output_base, r.state + RING, 0)]
    assert r.memory.read(r.input_count, 8) == INPUT_HIGH | 3
    assert r.memory.read(r.output_count, 8) == OUTPUT_HIGH
    assert r.memory.read(r.state + WRITE_INDEX, 4) == 0
    assert r.memory.read(r.state + COMPLETE, 1) == 0
    barrier = next(i for i, e in enumerate(r.events) if e[0] == "core")
    assert r.events[barrier + 1 : barrier + 5] == [
        ("r", r.frame + 0x58, 8),
        ("r", r.frame + 0x60, 8),
        ("r", r.state + WRITE_INDEX, 4),
        ("w", r.state + WRITE_INDEX, 4, 0),
    ]
    r.assert_expired()


@pytest.mark.parametrize("status,completed", [(0xFFFFFFFF00000000, 1), (0x8000000000000001, 0)])
def test_only_low_EAX_controls_normal_completion_or_input_suspend(
    status: int,
    completed: int,
) -> None:
    r = Rig()
    r.steps = [Step(status, 1, 1, b"X")]
    assert r.invoke() == 0
    assert r.memory.read(r.state + COMPLETE, 1) == completed
    assert r.memory.read(r.input_count, 4) == r.memory.read(r.output_count, 4) == 1
    r.assert_expired()


@pytest.mark.parametrize("status", [2, 3, 7, 0x7FFFFFFF])
def test_other_nonnegative_statuses_continue_with_fresh_flag_and_no_status2_restriction(
    status: int,
) -> None:
    r = Rig()
    r.steps = [Step(status, 1, 1, b"a"), Step(1, 2, 1, b"b")]
    modes: list[int] = []
    original = r.core_handler

    def core(args: tuple[int, ...]) -> int | None:
        modes.append(r.memory.read(args[6], 4))
        r.memory.write(r.homes[3], 4, 1)
        return original(args)

    r.core_handler = core
    assert r.invoke() == 0
    assert modes == [2, 0]
    assert r.memory.read_bytes(r.output_base, 2) == b"ab"
    assert r.memory.read(r.input_count, 4) == 3
    assert r.memory.read(r.output_count, 4) == 2
    assert r.core_invocations == 2
    r.assert_expired()


def test_loopback_compares_output_once_then_goes_directly_to_current_completed_gate() -> None:
    r = Rig()
    r.steps = [Step(2, 1, 1, b"X")]

    def read(address: int, width: int) -> None:
        if address == r.output_count and r.copy_invocations:
            r.memory.write(r.state + COMPLETE, 1, 1)

    r.after_read = read
    assert r.invoke() == 0
    assert r.core_invocations == 1
    last_count = max(i for i, e in enumerate(r.events) if e == ("r", r.output_count, 4))
    assert r.events[last_count + 1] == ("r", r.state + COMPLETE, 1)
    assert r.memory.read(r.input_count, 4) == 1
    r.assert_expired()


@pytest.mark.parametrize("produced", [0, 1])
def test_saved50_input_pointer_reloads_only_after_positive_copy_index_store(produced: int) -> None:
    r = Rig()
    other, latest = r.memory.allocate(8), r.memory.allocate(8)
    r.memory.write(other, 8, 0x5566778800000009)
    r.memory.write(latest, 8, 0x99AABBCC0000000A)
    r.steps = [Step(1, 2, produced, b"X" if produced else b"")]
    original = r.core_handler

    def core(args: tuple[int, ...]) -> int | None:
        r.memory.write(r.frame + 0x50, 8, other)
        return original(args)

    def write(address: int, width: int, value: int) -> None:
        if address == r.state + READ_INDEX and r.copy_invocations:
            r.memory.write(r.frame + 0x50, 8, latest)

    r.core_handler, r.after_write = core, write
    assert r.invoke() == 0
    if produced:
        assert r.memory.read(r.input_count, 8) == INPUT_HIGH | 12
        assert r.memory.read(latest, 8) == 0x99AABBCC00000002
        assert ("r", r.frame + 0x50, 8) in r.events
    else:
        assert r.memory.read(r.input_count, 8) == INPUT_HIGH | 2
        assert r.memory.read(latest, 8) == 0x99AABBCC0000000A
        assert ("r", r.frame + 0x50, 8) not in r.events
        assert not r.calls_to(MATH) and not r.calls_to(COPY)
    assert r.memory.read(other, 8) == 0x5566778800000009
    r.assert_expired()


def test_initial_copy_reloads_saved40_before_its_index_store_callback() -> None:
    r = Rig()
    r.pending(b"P")
    first, later = r.memory.allocate(16), r.memory.allocate(16)
    original_copy = r.copy_handler

    def copy(args: tuple[int, ...]) -> int | None:
        value = original_copy(args)
        r.memory.write(r.frame + 0x40, 8, first)
        return value

    def write(address: int, width: int, value: int) -> None:
        if address == r.state + READ_INDEX:
            r.memory.write(r.frame + 0x40, 8, later)

    def core(args: tuple[int, ...]) -> int:
        assert args[1] == first
        return U32

    r.copy_handler, r.after_write, r.core_handler = copy, write, core
    assert r.invoke() == 0xFFFFFFFE
    assert r.events.index(("r", r.frame + 0x40, 8)) < r.events.index(
        ("w", r.state + READ_INDEX, 4, 1)
    )
    r.assert_expired()


def test_loop_saved48_and_current_indices_follow_actual_child_barriers() -> None:
    r = Rig()
    other = r.memory.allocate(8)
    r.memory.write_bytes(other, b"........")
    r.steps = [Step(1, 1, 2, b"zz")]
    original_core, original_copy = r.core_handler, r.copy_handler

    def core(args: tuple[int, ...]) -> int | None:
        raw = original_core(args)
        r.memory.write(r.state + WRITE_INDEX, 4, 100)
        r.memory.write(r.state + READ_INDEX, 4, 5)
        r.memory.write_bytes(r.state + RING + 5, b"XY")
        return raw

    def read(address: int, width: int) -> None:
        if address == r.state + READ_INDEX and r.core_invocations:
            r.memory.write(r.frame + 0x48, 8, other)

    def copy(args: tuple[int, ...]) -> int | None:
        raw = original_copy(args)
        r.memory.write(r.state + READ_INDEX, 4, 7)
        return raw

    def write(address: int, width: int, value: int) -> None:
        if address == r.state + WRITE_INDEX:
            r.memory.write(r.frame + 0x60, 8, 0)  # ProducedQ already held before publication.

    r.core_handler, r.copy_handler, r.after_read, r.after_write = core, copy, read, write
    assert r.invoke() == 0
    assert r.calls_to(COPY) == [(other, r.state + RING + 5, 2)]
    assert r.memory.read_bytes(other, 2) == b"XY"
    assert r.memory.read(r.state + WRITE_INDEX, 4) == 102
    assert r.memory.read(r.state + READ_INDEX, 4) == 9
    assert r.memory.read_bytes(r.output_base, 2) == b".."
    r.assert_expired()


def test_other_status_reloads_saved40_before_comparison_then_holds_it_into_next_core() -> None:
    r = Rig()
    first, late = r.memory.allocate(16), r.memory.allocate(16)
    r.steps = [Step(2, 1, 0), Step(1, 2, 0)]
    original = r.core_handler

    def core(args: tuple[int, ...]) -> int | None:
        if r.core_invocations == 1:
            r.memory.write(r.frame + 0x40, 8, first)
        else:
            assert args[1] == first + 1
        return original(args)

    def read(address: int, width: int) -> None:
        if address == r.output_count and r.core_invocations == 1:
            r.memory.write(r.frame + 0x40, 8, late)

    r.core_handler, r.after_read = core, read
    assert r.invoke() == 0
    assert r.core_invocations == 2
    assert r.memory.read(r.input_count, 4) == 3
    assert r.memory.read(r.output_count, 4) == 0
    assert not r.calls_to(MATH) and not r.calls_to(COPY)
    r.assert_expired()


def test_initial_math_samples_current_IAT_and_read_index_before_consuming_opaque_word() -> None:
    r = Rig()
    r.pending(b"P")
    r.math_handlers[0xFA99] = lambda args: None

    def read(address: int, width: int) -> None:
        if address == r.output_count:
            r.memory.write(FMIN_IAT, 8, 0xFA99)
        elif address == r.state + READ_INDEX and r.calls_to(0xFA99):
            r.memory.write(r.state + COMPLETE, 1, 1)

    r.after_read = read
    with pytest.raises(ValueError, match="XMM0"):
        r.invoke()
    assert r.calls_to(0xFA99) == [(double_word(1.0), double_word(8.0))]
    barrier = next(i for i, e in enumerate(r.events) if e[0] == "m")
    assert r.events[barrier + 1] == ("r", r.state + READ_INDEX, 4)
    assert r.memory.read(r.state + COMPLETE, 1) == 1
    assert not r.calls_to(COPY)
    r.assert_expired()


def test_final_input_output_count_alias_keeps_order_and_upper_DWORD() -> None:
    r = Rig()
    r.memory.write(r.homes[1], 8, r.input_count)
    r.steps = [Step(1, 3, 2, b"XY")]
    assert r.invoke() == 0
    assert r.memory.read(r.input_count, 8) == INPUT_HIGH | 2
    writes = [event for event in r.events if event[0:3] == ("w", r.input_count, 4)]
    assert writes == [("w", r.input_count, 4, 3), ("w", r.input_count, 4, 2)]
    r.assert_expired()


@pytest.mark.parametrize("missing", ["math", "copy", "copy-import", "core"])
def test_missing_reached_capabilities_preserve_prefix_and_expire_local(missing: str) -> None:
    r = Rig()
    if missing != "core":
        r.pending(b"P")
    if missing == "math":
        r.bind(math_calls=ReplayTaskRebuildCalls(None))
    elif missing == "copy":
        r.bind(calls=ReplayTaskRebuildCalls(None))
    elif missing == "copy-import":
        r.memory.write(COPY_IAT, 8, 0xFA99)
    else:
        r.bind(core_calls=ReplayTaskRebuildCalls(None))
    with pytest.raises(UnresolvedReplayTaskRebuild):
        r.invoke()
    assert ("w", r.frame + 0x40, 8, r.input_base) in r.events
    assert ("w", r.frame + 0x48, 8, r.output_base) in r.events
    assert ("w", r.frame + 0x50, 8, r.input_count) in r.events
    if missing == "core":
        assert ("w", r.frame + 0x20, 8, r.state + RING) in r.events
    assert r.memory.read(r.input_count, 8) == INPUT_HIGH | 12
    r.assert_expired()


def test_copy_effects_survive_late_copy_exception_without_index_or_count_publication() -> None:
    r = Rig()
    r.pending(b"P")
    original = r.copy_handler

    def copy(args: tuple[int, ...]) -> int | None:
        original(args)
        raise RuntimeError("authored copy failure after effect")

    r.copy_handler = copy
    with pytest.raises(RuntimeError, match="after effect"):
        r.invoke()
    assert r.memory.read_bytes(r.output_base, 1) == b"P"
    assert r.memory.read(r.state + READ_INDEX, 4) == 0
    assert r.memory.read(r.input_count, 8) == INPUT_HIGH | 12
    assert r.memory.read(r.output_count, 8) == OUTPUT_HIGH | 8
    r.assert_expired()


@pytest.mark.parametrize(
    "args,data",
    [((1,), None), ((1,) * 7, None), ((1,) * 7 + (-1,), None), ((1,) * 8, memoryview(b"x"))],
)
def test_malformed_owned_ABI_refuses_before_mapping(
    args: tuple[int, ...],
    data: memoryview | None,
) -> None:
    r = Rig()
    with pytest.raises(ValueError):
        r.bound.call(WRAPPER, args, data)
    assert not r.locals and not r.events


def test_unknown_delegate_preserves_args_data_identity_and_opaque_result() -> None:
    r = Rig()
    seen: list[tuple[int, tuple[int, ...], memoryview | None]] = []
    args, data = (1, 2), memoryview(b"x")

    def call(target: int, actual_args: tuple[int, ...], actual_data: memoryview | None) -> None:
        seen.append((target, actual_args, actual_data))

    r.bind(calls=ReplayTaskRebuildCalls(call))
    assert r.bound.call(0x123, args, data) is None
    assert seen[0][1] is args and seen[0][2] is data
    assert not r.locals and not r.events


@pytest.mark.parametrize("frame", [bytes(0x67), bytearray(0x68), None])
def test_profile_requires_explicit_exact_immutable_seed(frame: bytes | bytearray | None) -> None:
    with pytest.raises(ValueError):
        replace(ReplayFileDecoderProfile(bytes(0x68)), frame=frame)
