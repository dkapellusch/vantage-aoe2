"""Group storage with actual owned allocation/free and explicit alias callbacks."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from vantage.replay_memory import ReplayMemory, ReplayMemoryError, ReplayMemoryRuntimeError
from vantage.replay_task_effects import bind_replay_task_execution
from vantage.replay_task_group_storage import (
    bind_replay_task_group_storage,
    release_replay_task_criterion_buckets,
    release_replay_task_group_buckets,
    release_replay_task_group_rehash_buckets,
    resize_replay_task_criterion_buckets,
    resize_replay_task_group_buckets,
    resize_replay_task_group_rehash_buckets,
)
from vantage.replay_task_prefix import ReplayTaskPrefixScratch
from vantage.replay_task_rebuild import ReplayTaskRebuildCalls, ReplayTaskRebuildStorage

RESIZERS = (
    resize_replay_task_group_buckets,
    resize_replay_task_criterion_buckets,
    resize_replay_task_group_rehash_buckets,
)
RELEASES = (
    release_replay_task_group_buckets,
    release_replay_task_criterion_buckets,
    release_replay_task_group_rehash_buckets,
)
U64 = (1 << 64) - 1
VALUE = 0xDEADBEEF01234567


def zero(memory: ReplayMemory, size: int) -> int:
    address = memory.allocate(size)
    memory.write_bytes(address, bytes(size))
    return address


def backing(memory: ReplayMemory, subject: int) -> ReplayTaskRebuildStorage:
    return ReplayTaskRebuildStorage(subject, memory.read, memory.write)


def calls(memory: ReplayMemory, context: ReplayTaskRebuildStorage) -> ReplayTaskRebuildCalls:
    return bind_replay_task_group_storage(
        context, memory.runtime_calls(), bind_local=memory.bind_local
    )


@pytest.mark.parametrize("resize", RESIZERS)
def test_fresh_growth_fills_raw_value_and_snapshot_replays_exactly(
    resize: Callable[..., None],
) -> None:
    memory = ReplayMemory()
    header = zero(memory, 24)
    initial = memory.snapshot()
    context = backing(memory, header)
    resize(context, header, 16, VALUE, calls=calls(memory, context))
    begin = memory.read(header, 8)
    assert memory.read(header + 8, 8) == begin + 128
    assert memory.read(header + 16, 8) == begin + 128
    assert memory.read_bytes(begin, 128) == VALUE.to_bytes(8, "little") * 16
    assert memory.mapped_bytes == 24 + 128
    restored = ReplayMemory.from_snapshot(initial)
    restored_context = backing(restored, header)
    resize(restored_context, header, 16, VALUE, calls=calls(restored, restored_context))
    assert restored.snapshot() == memory.snapshot()


@pytest.mark.parametrize("resize", RESIZERS)
@pytest.mark.parametrize("requested", [0, 3])
def test_reuse_fills_entire_old_range_without_reading_capacity_or_shrinking(
    resize: Callable[..., None],
    requested: int,
) -> None:
    memory = ReplayMemory()
    memory.map_bytes(0x1000, (0x2000).to_bytes(8, "little") + (0x2040).to_bytes(8, "little"))
    memory.map_bytes(0x2000, bytes(64))
    context = backing(memory, 0x1000)
    resize(context, 0x1000, requested, VALUE, calls=calls(memory, context))
    assert memory.read_bytes(0x2000, 64) == VALUE.to_bytes(8, "little") * 8
    assert memory.read(0x1000, 8) == 0x2000 and memory.read(0x1008, 8) == 0x2040
    assert memory.mapped_bytes == 16 + 64  # Scoped source has been removed.


@pytest.mark.parametrize("resize", RESIZERS)
def test_growth_uses_post_allocator_current_begin_and_capacity_then_commits(
    resize: Callable[..., None],
) -> None:
    memory = ReplayMemory()
    header = zero(memory, 24)
    original = memory.allocate_aligned(8)
    replacement = memory.allocate_aligned(16)
    for offset, value in ((0, original), (8, original + 8), (16, original + 8)):
        memory.write(header + offset, 8, value)
    context = backing(memory, header)
    runtime = memory.runtime_calls()
    effects = []

    def effect(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        assert runtime.call is not None and data is None
        effects.append((target, args))
        if target == 0x1402A94D0:
            allocation = runtime.call(target, args, data)
            memory.write(header, 8, replacement)
            memory.write(header + 16, 8, replacement + 16)
            return allocation
        assert target == 0x142D6BAB4 and args == (replacement, 16)
        # Release effects may rewrite the header; the later commit overwrites them.
        memory.write_bytes(header, b"\xff" * 24)
        return runtime.call(target, args, data)

    bound = bind_replay_task_group_storage(
        context, ReplayTaskRebuildCalls(effect), bind_local=memory.bind_local
    )
    resize(context, header, 4, VALUE, calls=bound)
    assert effects[0] == (0x1402A94D0, (32,)) and len(effects) == 2
    begin = memory.read(header, 8)
    assert memory.read_bytes(begin, 32) == VALUE.to_bytes(8, "little") * 4
    assert memory.read(header + 8, 8) == begin + 32
    assert memory.read(header + 16, 8) == begin + 32
    with pytest.raises(ReplayMemoryError, match="unmapped"):
        memory.read(replacement, 8)
    # The callback replaced the header. The original allocation is not guessed free.
    memory.write(original, 8, 7)
    assert memory.mapped_bytes == 24 + 8 + 32


@pytest.mark.parametrize("resize", RESIZERS)
def test_large_growth_releases_actual_aligned_old_base(resize: Callable[..., None]) -> None:
    memory = ReplayMemory()
    header = zero(memory, 24)
    old = memory.allocate_aligned(0x1000)
    base = memory.read(old - 8, 8)
    for offset, value in ((0, old), (8, old + 0x1000), (16, old + 0x1000)):
        memory.write(header + offset, 8, value)
    context = backing(memory, header)
    resize(context, header, 513, VALUE, calls=calls(memory, context))
    current = memory.read(header, 8)
    assert current % 32 == 0
    assert memory.read_bytes(current, 513 * 8) == VALUE.to_bytes(8, "little") * 513
    with pytest.raises(ReplayMemoryError, match="unmapped"):
        memory.read(base, 8)
    assert memory.mapped_bytes == 24 + 513 * 8 + 0x27


@pytest.mark.parametrize("resize", RESIZERS)
def test_header_is_committed_before_fill_and_payload_alias_overwrites_it(
    resize: Callable[..., None],
) -> None:
    memory = ReplayMemory()
    header = zero(memory, 24)
    context = backing(memory, header)
    observed = []

    def allocation(target: int, args: tuple[int, ...], data: memoryview | None) -> int:
        assert target == 0x1402A94D0 and args == (16,) and data is None
        observed.append(target)
        return header  # Explicit public alias control, not a native allocator claim.

    resize(context, header, 2, VALUE, calls=ReplayTaskRebuildCalls(allocation))
    assert observed == [0x1402A94D0]
    assert memory.read(header, 8) == VALUE
    assert memory.read(header + 8, 8) == VALUE
    assert memory.read(header + 16, 8) == header + 16


@pytest.mark.parametrize("resize", RESIZERS)
def test_partial_fill_failure_keeps_committed_header_and_prior_store(
    resize: Callable[..., None],
) -> None:
    memory = ReplayMemory()
    header = zero(memory, 24)
    memory.map_bytes(0x2000, bytes(8))
    memory.map_bytes(0x2008, bytes(8), writable=False)
    context = backing(memory, header)

    def allocation(target: int, args: tuple[int, ...], data: memoryview | None) -> int:
        assert target == 0x1402A94D0 and args == (16,) and data is None
        return 0x2000

    with pytest.raises(ReplayMemoryError, match="readonly"):
        resize(context, header, 2, VALUE, calls=ReplayTaskRebuildCalls(allocation))
    assert memory.read(header, 8) == 0x2000
    assert memory.read(header + 8, 8) == 0x2010 and memory.read(header + 16, 8) == 0x2010
    assert memory.read(0x2000, 8) == VALUE and memory.read(0x2008, 8) == 0


@pytest.mark.parametrize("resize", RESIZERS)
def test_release_failure_preserves_new_allocation_and_callback_effects(
    resize: Callable[..., None],
) -> None:
    memory = ReplayMemory()
    header = zero(memory, 24)
    old = memory.allocate_aligned(8)
    for offset, value in ((0, old), (8, old + 8), (16, old + 8)):
        memory.write(header + offset, 8, value)
    context = backing(memory, header)
    runtime = memory.runtime_calls()
    allocated = []

    def effect(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        if target == 0x1402A94D0:
            assert runtime.call is not None
            result = runtime.call(target, args, data)
            allocated.append(result)
            return result
        assert target == 0x142D6BAB4 and args == (old, 8)
        memory.write(header + 8, 8, 0xBAD)
        raise RuntimeError("release stopped")

    bound = bind_replay_task_group_storage(
        context, ReplayTaskRebuildCalls(effect), bind_local=memory.bind_local
    )
    with pytest.raises(RuntimeError, match="release stopped"):
        resize(context, header, 2, VALUE, calls=bound)
    assert len(allocated) == 1 and memory.mapped_bytes == 24 + 8 + 16
    assert memory.read(header, 8) == old and memory.read(header + 8, 8) == 0xBAD
    assert memory.read(header + 16, 8) == old + 8
    memory.write(old, 8, 1)
    with pytest.raises(ReplayMemoryError, match="undefined"):
        memory.read(allocated[0], 8)


@pytest.mark.parametrize("release", RELEASES)
@pytest.mark.parametrize("size", [0, 8, 0x1000, 0x1008])
def test_release_ignores_header_and_frees_without_reset(
    release: Callable[..., None],
    size: int,
) -> None:
    memory = ReplayMemory()
    buffer = memory.allocate_aligned(size)
    context = backing(memory, 0x1000)
    release(context, 0xDEAD, buffer, size // 8, calls=memory.runtime_calls())
    assert memory.mapped_bytes == 0


@pytest.mark.parametrize("release", RELEASES)
def test_invalid_large_header_reads_current_target_and_stops_before_free(
    release: Callable[..., None],
) -> None:
    memory = ReplayMemory()
    memory.map_bytes(0x2FF8, (0x2FD0).to_bytes(8, "little"))  # delta40 >31
    memory.map_bytes(0x14319A060, (0x142D66698).to_bytes(8, "little"))
    context = backing(memory, 0x1000)
    before = memory.snapshot()
    with pytest.raises(ReplayMemoryRuntimeError) as error:
        release(context, 0xDEAD, 0x3000, 512, calls=memory.runtime_calls())
    assert error.value.target == 0x142D66698 and error.value.args_words == (0, 0, 0, 0, 0)
    assert memory.snapshot() == before
    with pytest.raises(RuntimeError, match="unexpectedly returned"):
        release(context, 0xDEAD, 0x3000, 512, calls=ReplayTaskRebuildCalls(lambda *_: None))
    assert memory.snapshot() == before


@pytest.mark.parametrize("resize", RESIZERS)
def test_growth_size_error_occurs_before_allocator_or_capacity_read(
    resize: Callable[..., None],
) -> None:
    memory = ReplayMemory()
    memory.map_bytes(0x1000, bytes(16))  # No capacity backing, and none is read.
    context = backing(memory, 0x1000)
    before = memory.snapshot()
    with pytest.raises(ReplayMemoryRuntimeError) as error:
        resize(context, 0x1000, 1 << 61, VALUE, calls=memory.runtime_calls())
    assert error.value.target == 0x1402A9460 and memory.snapshot() == before


@pytest.mark.parametrize("resize", RESIZERS)
def test_wrapping_output_uses_held_end_and_wrapping_qword_steps(
    resize: Callable[..., None],
) -> None:
    memory = ReplayMemory()
    header = zero(memory, 24)
    memory.map_bytes(U64 - 7, bytes(8))
    memory.map_bytes(0, bytes(8))
    context = backing(memory, header)

    def allocation(target: int, args: tuple[int, ...], data: memoryview | None) -> int:
        assert target == 0x1402A94D0 and args == (16,) and data is None
        return U64 - 7

    resize(context, header, 2, VALUE, calls=ReplayTaskRebuildCalls(allocation))
    assert memory.read(U64 - 7, 8) == VALUE and memory.read(0, 8) == VALUE
    assert memory.read(header + 8, 8) == 8 and memory.read(header + 16, 8) == 8


@pytest.mark.parametrize(
    "initializer,release,fill",
    [
        (0x1412BF330, 0x1412C6430, 0x1412A5B40),
        (0x1412BF260, 0x1412C63D0, 0x1412A5AB0),
        (0x1412BF400, 0x1412C6490, 0x1412A5BD0),
    ],
)
def test_execution_adapter_runs_each_triplet_with_actual_memory_and_restore(
    initializer: int,
    release: int,
    fill: int,
) -> None:
    memory = ReplayMemory()
    subject = zero(memory, 0x900)
    header = subject + 0x100
    pair_out, byte_out = zero(memory, 9), zero(memory, 9)
    initial = memory.snapshot()

    def run(current: ReplayMemory) -> None:
        context = backing(current, subject)
        bound = bind_replay_task_execution(
            context,
            current.runtime_calls(),
            bind_local=current.bind_local,
            pair_out=pair_out,
            byte_out=byte_out,
            mxcsr=0x1F80,
            prefix_scratch=ReplayTaskPrefixScratch(bytes(64), b"abc", b"xyz"),
        )
        assert bound.call is not None
        bound.call(initializer, (header, 16, VALUE), None)
        first = current.read(header, 8)
        assert current.read_bytes(first, 128) == VALUE.to_bytes(8, "little") * 16
        bound.call(initializer, (header, 0, 7), None)
        assert current.read_bytes(first, 128) == (7).to_bytes(8, "little") * 16
        assert current.read(header + 8, 8) == first + 128
        local = memoryview(bytearray((9).to_bytes(8, "little")))
        bound.call(fill, (first, first + 24), local)
        assert current.read_bytes(first, 24) == bytes(local) * 3
        bound.call(initializer, (header, 1024, VALUE), None)
        grown = current.read(header, 8)
        assert current.read_bytes(grown, 8192) == VALUE.to_bytes(8, "little") * 1024
        with pytest.raises(ReplayMemoryError, match="unmapped"):
            current.read(first, 8)
        assert current.mapped_bytes == 0x900 + 18 + 8192 + 0x27
        bound.call(release, (header, grown, 1024), None)
        assert current.mapped_bytes == 0x900 + 18
        assert current.read(header, 8) == grown  # Actual release does not reset the header.

    run(memory)
    restored = ReplayMemory.from_snapshot(initial)
    run(restored)
    assert restored.snapshot() == memory.snapshot()
