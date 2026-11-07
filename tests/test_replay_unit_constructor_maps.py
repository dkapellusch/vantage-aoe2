"""Owned composition of the source-proven Action/Unit/Base map families."""

from __future__ import annotations

import pytest

from vantage.replay_memory import ReplayMemory, ReplayMemoryError
from vantage.replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
)
from vantage.replay_unit_ai_vector_growth import bind_replay_unit_ai_vector_growth
from vantage.replay_unit_constructor_maps import (
    bind_replay_unit_constructor_maps,
    construct_replay_unit_map,
    release_replay_unit_map_buckets,
    resize_replay_unit_map_buckets,
)

# Independent original entry/operand inventory, not imported dispatch metadata.
FAMILIES = [
    (0x141136CA0, 0x14113A360, 0x141136C10, 0x14113B410, 24),
    (0x1412A5C60, 0x1412BF190, 0x14126D9A0, 0x1412C6370, 24),
    (0x14122DC70, 0x14124AF90, 0x14122DAD0, 0x14124E0B0, 32),
    (0x14122DBF0, 0x14124B060, 0x14122DB60, 0x14124E110, 48),
]


def owned() -> tuple[ReplayMemory, int, ReplayTaskRebuildStorage, ReplayTaskRebuildCalls]:
    memory = ReplayMemory()
    address = memory.allocate(0x50)
    memory.write_bytes(address, b"\xa5" * 0x50)
    context = ReplayTaskRebuildStorage(address, memory.read, memory.write)
    terminal = memory.runtime_calls()
    # Actual existing free-thunk chain, with an explicit engine terminal IAT.
    memory.map_bytes(0x143199DD0, (0x142D6BAB4).to_bytes(8, "little"))
    lower = bind_replay_unit_ai_vector_growth(context, terminal, imports=terminal)
    return memory, address, context, lower


@pytest.mark.parametrize("family", FAMILIES)
@pytest.mark.parametrize("route", ["direct", "bound"])
def test_complete_family_constructs_real_sentinel_and_sixteen_buckets(
    family: tuple[int, ...],
    route: str,
) -> None:
    constructor, _, _, _, size = family
    memory, address, context, lower = owned()
    bound = bind_replay_unit_constructor_maps(context, lower, bind_local=memory.bind_local)
    assert bound.call is not None
    if route == "direct":
        result = construct_replay_unit_map(context, constructor, address, calls=bound)
    else:
        result = bound.call(constructor, (address,), None)
    assert result == address
    assert memory.read(address, 4) == 0x3F800000
    assert memory.read_bytes(address + 4, 4) == b"\xa5" * 4
    sentinel = memory.read(address + 8, 8)
    assert memory.read(sentinel, 8) == sentinel
    assert memory.read(sentinel + 8, 8) == sentinel
    with pytest.raises(ReplayMemoryError, match="undefined"):
        memory.read_bytes(sentinel + 16, size - 16)
    assert memory.read(address + 16, 8) == 0
    begin, end, capacity = (memory.read(address + offset, 8) for offset in (24, 32, 40))
    assert end == capacity == begin + 128
    assert [memory.read(begin + n * 8, 8) for n in range(16)] == [sentinel] * 16
    assert memory.read(address + 48, 8) == 7
    assert memory.read(address + 56, 8) == 8
    assert memory.read_bytes(address + 64, 16) == b"\xa5" * 16
    assert ReplayMemory.from_snapshot(memory.snapshot()).snapshot() == memory.snapshot()


@pytest.mark.parametrize("family", FAMILIES)
def test_constructor_reloads_current_published_sentinel(family: tuple[int, ...]) -> None:
    constructor = family[0]
    memory, address, _, lower = owned()

    def write(at: int, width: int, value: int) -> None:
        memory.write(at, width, value)
        if (at, width, value) == (address, 4, 0x3F800000):
            memory.write(address + 8, 8, 0xDADA)

    context = ReplayTaskRebuildStorage(address, memory.read, write)
    bound = bind_replay_unit_constructor_maps(context, lower, bind_local=memory.bind_local)
    construct_replay_unit_map(context, constructor, address, calls=bound)
    begin = memory.read(address + 24, 8)
    assert [memory.read(begin + n * 8, 8) for n in range(16)] == [0xDADA] * 16


@pytest.mark.parametrize("family", FAMILIES)
def test_missing_allocator_retains_only_reached_initial_writes(family: tuple[int, ...]) -> None:
    memory, address, context, _ = owned()
    before = bytearray(memory.read_bytes(address, 0x50))
    before[0:4] = bytes(4)
    before[8:24] = bytes(16)
    with pytest.raises(UnresolvedReplayTaskRebuild, match="142d6ba78"):
        construct_replay_unit_map(context, family[0], address, calls=ReplayTaskRebuildCalls(None))
    assert memory.read_bytes(address, 0x50) == before


@pytest.mark.parametrize("family", FAMILIES)
def test_growth_reads_current_header_after_allocator(family: tuple[int, ...]) -> None:
    _, initializer, _, _, _ = family
    memory, header, context, lower = owned()
    original = memory.allocate(8)
    replacement = memory.allocate(32)
    memory.write(original, 8, 0x1111)
    memory.write_bytes(replacement, b"\x55" * 32)
    for offset, value in ((0, original), (8, original), (16, original + 8)):
        memory.write(header + offset, 8, value)
    events: list[tuple[int, tuple[int, ...]]] = []
    assert lower.call is not None

    def current(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        events.append((target, args))
        assert lower.call is not None
        result = lower.call(target, args, data)
        if target == 0x1402A94D0:
            memory.write(header, 8, replacement)
            memory.write(header + 16, 8, replacement + 32)
        return result

    bound = bind_replay_unit_constructor_maps(
        context, ReplayTaskRebuildCalls(current), bind_local=memory.bind_local
    )
    resize_replay_unit_map_buckets(context, initializer, header, 3, 0xDEADBEEF, calls=bound)
    begin = memory.read(header, 8)
    assert memory.read(header + 8, 8) == memory.read(header + 16, 8) == begin + 24
    assert [memory.read(begin + n * 8, 8) for n in range(3)] == [0xDEADBEEF] * 3
    assert memory.read(original, 8) == 0x1111
    with pytest.raises(ReplayMemoryError, match="unmapped"):
        memory.read(replacement, 8)
    assert (0x142D6BAB4, (replacement, 32)) in events


@pytest.mark.parametrize("family", FAMILIES)
def test_reuse_fills_whole_held_range_without_changing_headers(family: tuple[int, ...]) -> None:
    memory, header, context, lower = owned()
    storage = memory.allocate(32)
    for offset, value in ((0, storage), (8, storage + 32), (16, storage + 32)):
        memory.write(header + offset, 8, value)
    bound = bind_replay_unit_constructor_maps(context, lower, bind_local=memory.bind_local)
    before = memory.read_bytes(header, 24)
    resize_replay_unit_map_buckets(context, family[1], header, 0, 0x7788, calls=bound)
    assert memory.read_bytes(header, 24) == before
    assert [memory.read(storage + n * 8, 8) for n in range(4)] == [0x7788] * 4


@pytest.mark.parametrize("family", FAMILIES)
@pytest.mark.parametrize("returns", [False, True])
def test_growth_capacity_error_is_mandatory_before_allocation_or_stores(
    family: tuple[int, ...],
    returns: bool,
) -> None:
    memory, header, context, _ = owned()
    memory.write_bytes(header, bytes(24))
    before = memory.snapshot()
    seen: list[tuple[int, tuple[int, ...]]] = []

    def error(target: int, args: tuple[int, ...], data: memoryview | None) -> None:
        seen.append((target, args))
        assert data is None
        if not returns:
            raise RuntimeError("actual capacity error")

    message = "unexpectedly returned" if returns else "actual capacity error"
    with pytest.raises(RuntimeError, match=message):
        resize_replay_unit_map_buckets(
            context, family[1], header, 0x2000000000000000, 0, calls=ReplayTaskRebuildCalls(error)
        )
    assert seen == [(0x1402A9460, ())]
    assert memory.snapshot() == before


@pytest.mark.parametrize("family", FAMILIES)
def test_native_fill_preloads_before_overlap_then_reloads_source(family: tuple[int, ...]) -> None:
    memory, _, _, lower = owned()
    begin = memory.allocate(24)
    for n in range(3):
        memory.write(begin + n * 8, 8, n + 1)
    source_reads = 0

    def read(at: int, width: int) -> int:
        nonlocal source_reads
        result = memory.read(at, width)
        if at == begin + 8:
            source_reads += 1
            if source_reads == 1:
                memory.write(at, width, 99)
        return result

    context = ReplayTaskRebuildStorage(begin, read, memory.write)
    bound = bind_replay_unit_constructor_maps(context, lower, bind_local=memory.bind_local)
    assert bound.call is not None
    bound.call(family[2], (begin, begin + 24, begin + 8), None)
    assert source_reads == 4
    assert [memory.read(begin + n * 8, 8) for n in range(3)] == [99] * 3


@pytest.mark.parametrize("family", FAMILIES)
def test_empty_native_fill_does_not_read_unmapped_source(family: tuple[int, ...]) -> None:
    memory, address, _, lower = owned()

    def forbidden(at: int, width: int) -> int:
        raise AssertionError((at, width))

    context = ReplayTaskRebuildStorage(address, forbidden, memory.write)
    bound = bind_replay_unit_constructor_maps(context, lower, bind_local=memory.bind_local)
    assert bound.call is not None
    bound.call(family[2], (0x10, 0x10, 0xDEAD), None)


@pytest.mark.parametrize("family", FAMILIES)
def test_large_release_uses_real_back_pointer_and_preserves_header(family: tuple[int, ...]) -> None:
    memory, header, context, lower = owned()
    allocation = memory.allocate_aligned(0x1000)
    memory.write_bytes(allocation, bytes(0x1000))
    before = memory.read_bytes(header, 0x50)
    release_replay_unit_map_buckets(context, family[3], header, allocation, 0x200, calls=lower)
    assert memory.read_bytes(header, 0x50) == before
    with pytest.raises(ReplayMemoryError, match="unmapped"):
        memory.read(allocation, 1)


@pytest.mark.parametrize("family", FAMILIES)
def test_invalid_large_header_reads_current_watson_and_keeps_effects(
    family: tuple[int, ...],
) -> None:
    memory, header, context, _ = owned()
    memory.map_bytes(0x14319A060, (0xD00D).to_bytes(8, "little"))
    allocation = memory.allocate(64)
    memory.write(allocation, 8, allocation - 64)
    seen: list[tuple[int, tuple[int, ...]]] = []

    def watson(target: int, args: tuple[int, ...], data: memoryview | None) -> None:
        seen.append((target, args))
        assert data is None
        memory.write(header, 4, 77)
        raise RuntimeError("actual Watson capability")

    with pytest.raises(RuntimeError, match="actual Watson capability"):
        release_replay_unit_map_buckets(
            context, family[3], header, allocation + 8, 0x200, calls=ReplayTaskRebuildCalls(watson)
        )
    assert seen == [(0xD00D, (0, 0, 0, 0, 0))]
    assert memory.read(header, 4) == 77


@pytest.mark.parametrize("family", FAMILIES)
def test_known_entry_arity_and_view_validation_precede_effects(family: tuple[int, ...]) -> None:
    memory, _, context, lower = owned()
    before = memory.snapshot()
    bound = bind_replay_unit_constructor_maps(context, lower, bind_local=memory.bind_local)
    assert bound.call is not None
    for target in family[:4]:
        with pytest.raises(ValueError):
            bound.call(target, (), None)
    with pytest.raises(ValueError):
        bound.call(family[2], (1, 2), memoryview(b"12345678"))
    assert memory.snapshot() == before


def test_unknown_target_keeps_live_view_and_original_arguments() -> None:
    memory, _, context, _ = owned()
    view = memoryview(bytearray(b"abc"))

    def lower(target: int, args: tuple[int, ...], data: memoryview | None) -> int:
        assert target == 0xDEAD and args == (7, 8) and data is view
        data[0] = 90
        return 77

    bound = bind_replay_unit_constructor_maps(
        context, ReplayTaskRebuildCalls(lower), bind_local=memory.bind_local
    )
    assert bound.call is not None
    assert bound.call(0xDEAD, (7, 8), view) == 77
    assert bytes(view) == b"Zbc"
    unavailable = bind_replay_unit_constructor_maps(
        context, ReplayTaskRebuildCalls(None), bind_local=memory.bind_local
    )
    assert unavailable.call is not None
    with pytest.raises(UnresolvedReplayTaskRebuild):
        unavailable.call(0xDEAD, (7, 8), view)
