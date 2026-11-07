"""Source-derived owned-storage controls, not original native execution."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from vantage.replay_memory import ReplayMemory, ReplayMemoryError
from vantage.replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
)
from vantage.replay_unit_ai_base import set_replay_unit_ai_retarget_timer
from vantage.replay_unit_ai_current import (
    bind_replay_unit_ai_current,
    read_replay_unit_word80c,
    set_replay_unit_ai_timeout,
    update_replay_unit_ai2_timeout,
)


def owned() -> tuple[ReplayMemory, int, ReplayTaskRebuildStorage]:
    memory = ReplayMemory()
    address = memory.allocate(0x820)
    memory.write_bytes(address, b"\xa5" * 0x820)
    return memory, address, ReplayTaskRebuildStorage(address, memory.read, memory.write)


def observed(
    memory: ReplayMemory,
    address: int,
    events: list[tuple[object, ...]],
) -> ReplayTaskRebuildStorage:
    def read(at: int, width: int) -> int:
        events.append(("read", at, width))
        return memory.read(at, width)

    def write(at: int, width: int, value: int) -> None:
        events.append(("write", at, width, value))
        memory.write(at, width, value)

    return ReplayTaskRebuildStorage(address, read, write)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (0, 0),
        (1, 1),
        (2, 2),
        (3, 3),
        (4, 5),
        (4000, 5000),
        (0x33333333, 0x3FFFFFFF),
        (0x40000000, 0x10000000),
        (0x7FFFFFFF, 0x1FFFFFFE),
        (0x80000000, 0x20000000),
        (0xFFFFFFFF, 0x3FFFFFFE),
    ],
)
@pytest.mark.parametrize("route", ["direct", "bound", "timer-rdx"])
def test_unsigned_product_wraps_before_logical_shift(
    value: int,
    expected: int,
    route: str,
) -> None:
    memory, address, context = owned()
    memory.write(address + 0x170, 4, value)
    before = bytearray(memory.read_bytes(address, 0x820))
    seen: list[tuple[int, tuple[int, ...]]] = []

    def setter(target: int, args: tuple[int, ...], data: memoryview | None) -> int:
        assert target == 0x140D19DC0 and data is None
        seen.append((target, args))
        set_replay_unit_ai_timeout(context, *args)
        return 0xDEADBEEF  # Ignored native-register value; actual store still required.

    if route == "direct":
        assert (
            update_replay_unit_ai2_timeout(context, address, calls=ReplayTaskRebuildCalls(setter))
            is None
        )
        assert seen == [(0x140D19DC0, (address, expected))]
    else:
        bound = bind_replay_unit_ai_current(context, ReplayTaskRebuildCalls(None))
        args = (address,) if route == "bound" else (address, 0xFFFFFFFFFFFFFFFF)
        assert bound.call is not None
        assert bound.call(0x140CF3300, args, None) is None
    before[0x16C:0x170] = expected.to_bytes(4, "little")
    assert memory.read_bytes(address, 0x820) == before


@pytest.mark.parametrize("value", [0, 0xFFFFFFFF, 0x12345678FFFFFFFF])
def test_setter_stores_only_low_edx(value: int) -> None:
    memory, address, context = owned()
    before = bytearray(memory.read_bytes(address, 0x820))
    assert set_replay_unit_ai_timeout(context, address, value) is None
    before[0x16C:0x170] = (value & 0xFFFFFFFF).to_bytes(4, "little")
    assert memory.read_bytes(address, 0x820) == before


@pytest.mark.parametrize(
    "word",
    [
        0,
        0x80000000,
        1,
        0x3F800000,
        0x7F800000,
        0xFF800000,
        0x7FC12345,
        0x7F812345,
        0xDEADBEEF,
    ],
)
def test_getter_transports_all_raw_xmm_word_bits(word: int) -> None:
    memory, address, context = owned()
    memory.write(address + 0x80C, 4, word)
    before = memory.snapshot()
    assert read_replay_unit_word80c(context, address) == word
    bound = bind_replay_unit_ai_current(context, ReplayTaskRebuildCalls(None))
    assert bound.call is not None
    assert bound.call(0x1412B6240, (address,), None) == word
    assert memory.snapshot() == before


def test_current_source_is_captured_before_actual_tail_effects() -> None:
    memory, address, _ = owned()
    memory.write(address + 0x170, 4, 4000)
    events: list[tuple[object, ...]] = []

    def read(at: int, width: int) -> int:
        value = memory.read(at, width)
        events.append(("read", at, width, value))
        memory.write(address + 0x170, 4, 1)
        return value

    def write(at: int, width: int, value: int) -> None:
        events.append(("write", at, width, value))
        memory.write(at, width, value)

    context = ReplayTaskRebuildStorage(address, read, write)

    def setter(target: int, args: tuple[int, ...], data: memoryview | None) -> None:
        events.append(("tail", target, args, data))
        set_replay_unit_ai_timeout(context, *args)

    update_replay_unit_ai2_timeout(context, address, calls=ReplayTaskRebuildCalls(setter))
    assert events == [
        ("read", address + 0x170, 4, 4000),
        ("tail", 0x140D19DC0, (address, 5000), None),
        ("write", address + 0x16C, 4, 5000),
    ]
    assert memory.read(address + 0x170, 4) == 1


def test_getter_reads_current_word_once_and_preserves_held_bits() -> None:
    memory, address, _ = owned()
    memory.write(address + 0x80C, 4, 0x80000000)
    reads: list[tuple[int, int]] = []

    def read(at: int, width: int) -> int:
        reads.append((at, width))
        value = memory.read(at, width)
        memory.write(address + 0x80C, 4, 0)
        return value

    context = ReplayTaskRebuildStorage(address, read, memory.write)
    assert read_replay_unit_word80c(context, address) == 0x80000000
    assert reads == [(address + 0x80C, 4)]
    assert memory.read(address + 0x80C, 4) == 0


def test_missing_setter_refuses_after_source_read_without_inline_store() -> None:
    memory, address, _ = owned()
    events: list[tuple[int, int]] = []

    def read(at: int, width: int) -> int:
        events.append((at, width))
        return memory.read(at, width)

    context = ReplayTaskRebuildStorage(address, read, memory.write)
    before = memory.snapshot()
    with pytest.raises(UnresolvedReplayTaskRebuild):
        update_replay_unit_ai2_timeout(context, address, calls=ReplayTaskRebuildCalls(None))
    assert events == [(address + 0x170, 4)]
    assert memory.snapshot() == before


def test_setter_callback_failure_retains_its_prior_effects() -> None:
    memory, address, context = owned()
    memory.write(address + 0x170, 4, 4000)

    def failing(target: int, args: tuple[int, ...], data: memoryview | None) -> None:
        assert target == 0x140D19DC0 and args == (address, 5000) and data is None
        memory.write(address + 0x16C, 4, 77)
        raise RuntimeError("actual setter binding failed")

    with pytest.raises(RuntimeError, match="actual setter binding failed"):
        update_replay_unit_ai2_timeout(context, address, calls=ReplayTaskRebuildCalls(failing))
    assert memory.read(address + 0x16C, 4) == 77


def test_actual_timer_wrapper_composes_two_argument_override_and_real_setter() -> None:
    memory, address, context = owned()
    table = memory.allocate(0x1B0)
    memory.write(table + 0x1A8, 8, 0x140CF3300)
    memory.write(address, 8, table)
    bound = bind_replay_unit_ai_current(context, ReplayTaskRebuildCalls(None))
    assert set_replay_unit_ai_retarget_timer(context, address, 0x123400000FA0, calls=bound) is None
    assert memory.read(address + 0x170, 4) == 4000
    assert memory.read(address + 0x16C, 4) == 5000


def test_bound_setter_is_the_actual_store_body() -> None:
    memory, address, context = owned()
    bound = bind_replay_unit_ai_current(context, ReplayTaskRebuildCalls(None))
    assert bound.call is not None
    assert bound.call(0x140D19DC0, (address, 0x80000000DEADBEEF), None) is None
    assert memory.read(address + 0x16C, 4) == 0xDEADBEEF


@pytest.mark.parametrize(
    ("target", "args"),
    [
        (0x140CF3300, ()),
        (0x140CF3300, (1, 2, 3)),
        (0x140D19DC0, (1,)),
        (0x1412B6240, (1, 2)),
        (0x140CF3300, (1, -1)),
        (0x140CF3300, (1, 1 << 64)),
        (0x140CF3300, (1, True)),
    ],
)
def test_bound_arity_and_ignored_raw_rdx_refuse_before_access(
    target: int,
    args: tuple[int, ...],
) -> None:
    memory, address, _ = owned()
    events: list[tuple[object, ...]] = []
    context = observed(memory, address, events)
    before = memory.snapshot()
    bound = bind_replay_unit_ai_current(context, ReplayTaskRebuildCalls(None))
    assert bound.call is not None
    with pytest.raises(ValueError):
        bound.call(target, args, None)
    assert memory.snapshot() == before
    assert not events


@pytest.mark.parametrize(
    ("target", "arity"),
    [
        (0x140CF3300, 1),
        (0x140D19DC0, 2),
        (0x1412B6240, 1),
    ],
)
def test_owned_entries_reject_data_before_effects(target: int, arity: int) -> None:
    memory, address, _ = owned()
    events: list[tuple[object, ...]] = []
    context = observed(memory, address, events)
    before = memory.snapshot()
    bound = bind_replay_unit_ai_current(context, ReplayTaskRebuildCalls(None))
    assert bound.call is not None
    with pytest.raises(ValueError):
        bound.call(target, (address,) * arity, memoryview(bytearray(b"x")))
    assert memory.snapshot() == before
    assert not events


def test_unknown_target_delegates_original_view_and_refuses_when_unavailable() -> None:
    _, _, context = owned()
    view = memoryview(bytearray(b"abc"))

    def lower(target: int, args: tuple[int, ...], data: memoryview | None) -> int:
        assert target == 0xDEAD and args == (1, 2) and data is view
        data[1] = 0x7A
        return 19

    bound = bind_replay_unit_ai_current(context, ReplayTaskRebuildCalls(lower))
    assert bound.call is not None
    assert bound.call(0xDEAD, (1, 2), view) == 19 and view.tobytes() == b"azc"
    unavailable = bind_replay_unit_ai_current(context, ReplayTaskRebuildCalls(None))
    assert unavailable.call is not None
    with pytest.raises(UnresolvedReplayTaskRebuild):
        unavailable.call(0xDEAD, (1, 2), view)


@pytest.mark.parametrize("operation", ["read-source", "write-tail", "read-getter"])
def test_unavailable_backing_is_not_success(operation: str) -> None:
    memory = ReplayMemory()
    address = memory.allocate(0x820)
    context = ReplayTaskRebuildStorage(address, memory.read, memory.write)
    if operation == "write-tail":
        memory.write(address + 0x170, 4, 4000)
        # A readonly destination, supplied as actual owned input backing.
        protected = ReplayMemory()
        protected.map_bytes(address + 0x170, (4000).to_bytes(4, "little"))
        protected.map_bytes(address + 0x16C, b"\xa5" * 4, writable=False)
        context = ReplayTaskRebuildStorage(address, protected.read, protected.write)
    bound = bind_replay_unit_ai_current(context, ReplayTaskRebuildCalls(None))
    assert bound.call is not None
    with pytest.raises(ReplayMemoryError):
        if operation == "read-getter":
            read_replay_unit_word80c(context, address)
        else:
            bound.call(0x140CF3300, (address,), None)


@pytest.mark.parametrize("operation", [set_replay_unit_ai_timeout, read_replay_unit_word80c])
def test_direct_argument_validation_precedes_effects(operation: Callable[..., object]) -> None:
    memory, address, _ = owned()
    events: list[tuple[object, ...]] = []
    context = observed(memory, address, events)
    before = memory.snapshot()
    with pytest.raises(ValueError):
        if operation is set_replay_unit_ai_timeout:
            operation(context, address, -1)
        else:
            operation(context, -1)
    assert memory.snapshot() == before
    assert not events
