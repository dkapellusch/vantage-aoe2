"""Current backing and leaf controls for the five concrete prefix containers.

Test leaves supply controlled allocations/moves/fills, not restored game state.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest

from vantage.replay_task_containers import (
    ReplayTaskContainerCalls,
    UnresolvedReplayTaskContainer,
    bind_replay_task_prefix_containers,
    clear_replay_task_byte,
    clear_replay_task_pair,
    grow_replay_task_vector64,
    lookup_replay_task_byte,
    lookup_replay_task_pair,
)
from vantage.replay_task_prefix import ReplayTaskPrefixScratch, run_replay_task_prefix
from vantage.replay_task_rebuild import ReplayTaskRebuildStorage

MAP, HEAD, BUCKETS, NODE, OUT = 0x10000, 0x20000, 0x30000, 0x40000, 0x60000
VECTOR, OLD, NEW = 0x70000, 0x80000, 0x90000
U64 = (1 << 64) - 1
Hook = Callable[[tuple[int, ...], memoryview | None], int | None]


class Probe:
    def __init__(self) -> None:
        self.memory: dict[int, int] = {}
        self.events: list[tuple[object, ...]] = []
        self.hooks: dict[int, Hook] = {}
        for base, size in (
            (MAP, 0x1000),
            (HEAD, 0x100),
            (BUCKETS, 0x1000),
            (NODE, 0x1000),
            (OUT, 0x100),
            (VECTOR, 0x100),
            (OLD, 0x2000),
            (NEW, 0x3000),
        ):
            self.memory.update((base + i, 0xA5) for i in range(size))
        self.map(MAP, HEAD, BUCKETS)
        self.put(0x1436A0308, 4, 0x5F000000)
        self.put(0x14319A060, 8, 0xABCDE)
        self.vector(1, 1)

    def put(self, address: int, width: int, value: int) -> None:
        self.memory.update(((address + i) & U64, value >> (8 * i) & 255) for i in range(width))

    def get(self, address: int, width: int) -> int:
        return sum(self.memory[(address + i) & U64] << (8 * i) for i in range(width))

    def read(self, address: int, width: int) -> int:
        self.events.append(("read", address, width))
        return self.get(address, width)

    def write(self, address: int, width: int, value: int) -> None:
        self.events.append(("write", address, width, value))
        self.put(address, width, value)

    @property
    def context(self) -> ReplayTaskRebuildStorage:
        return ReplayTaskRebuildStorage(MAP, self.read, self.write)

    @property
    def calls(self) -> ReplayTaskContainerCalls:
        return ReplayTaskContainerCalls(self.call, 0x1F80)

    def call(self, target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        self.events.append(("call", target, args, bytes(data) if data is not None else None))
        if target in self.hooks:
            return self.hooks[target](args, data)
        if target == 0x142D6BA78:
            return NODE
        if target == 0x1402A94D0:
            return NEW
        if target == 0x142D6E453:
            return 0x3F800000
        if target == 0x142D6E3DB:
            dest, source, size = args
            self.put(dest, size, self.get(source, size))
        elif target in (0x141143790, 0x141143820):
            assert data is not None
            for address in range(args[0], args[1], 8):
                self.put(address, 8, int.from_bytes(data, "little"))
        elif target not in (0x142D6BAB4, 0x14114D760, 0x14114D970):
            raise UnresolvedReplayTaskContainer(f"test leaf{target:x} unavailable")
        return None

    def map(
        self, address: int, head: int, buckets: int, count: int = 0, bucket_count: int = 8
    ) -> None:
        self.put(address, 4, 0x3F800000)
        for offset, value in (
            (8, head),
            (0x10, count),
            (0x18, buckets),
            (0x20, buckets + bucket_count * 16),
            (0x30, bucket_count - 1),
            (0x38, bucket_count),
        ):
            self.put(address + offset, 8, value)
        self.put(head, 8, head)
        self.put(head + 8, 8, head)
        for index in range(bucket_count * 2):
            self.put(buckets + index * 8, 8, head)

    def vector(self, count: int, capacity: int) -> None:
        for offset, value in ((0, OLD), (8, OLD + count * 64), (16, OLD + capacity * 64)):
            self.put(VECTOR + offset, 8, value)

    def matching(self, target: int) -> list[tuple[object, ...]]:
        return [e for e in self.events if e[:2] == ("call", target)]


def views(pair: bool) -> tuple[memoryview, memoryview]:
    return (
        memoryview(bytearray(b"abcdefgh" if pair else b"a")),
        memoryview(bytearray(b"1234" if pair else b"12345678")),
    )


@pytest.mark.parametrize("pair", [False, True])
def test_lookup_insert_then_hit_preserves_value_padding_and_out_tail(pair: bool) -> None:
    p = Probe()
    key, value = views(pair)
    lookup = lookup_replay_task_pair if pair else lookup_replay_task_byte
    assert lookup(p.context, MAP, OUT, key, value, calls=p.calls) == OUT
    assert p.get(OUT, 8) == NODE and p.get(OUT + 8, 1) == 1
    assert p.get(OUT + 9, 7) == int.from_bytes(b"\xa5" * 7, "little")
    assert p.get(NODE + 0x10, len(key)) == int.from_bytes(key, "little")
    assert p.get(NODE + 0x18, len(value)) == int.from_bytes(value, "little")
    padding = 4 if pair else 7
    address = NODE + (0x1C if pair else 0x11)
    assert p.get(address, padding) == int.from_bytes(b"\xa5" * padding, "little")
    assert p.get(MAP + 0x10, 8) == 1
    value[:] = bytes([255]) * len(value)
    lookup(p.context, MAP, OUT, key, value, calls=p.calls)
    assert p.get(OUT + 8, 1) == 0
    assert p.get(NODE + 0x18, len(value)) == int.from_bytes(
        b"1234" if pair else b"12345678", "little"
    )
    assert len(p.matching(0x142D6BA78)) == 1


@pytest.mark.parametrize("pair", [False, True])
def test_allocator_mutates_current_inputs_but_hash_stays_held(pair: bool) -> None:
    p = Probe()
    key, value = views(pair)

    def allocate(args: tuple[int, ...], data: memoryview | None) -> int:
        key[:] = (b"y" if pair else b"z") * len(key)
        value[:] = b"Z" * len(value)
        return NODE

    p.hooks[0x142D6BA78] = allocate
    lookup = lookup_replay_task_pair if pair else lookup_replay_task_byte
    lookup(p.context, MAP, OUT, key, value, calls=p.calls)
    assert p.get(NODE + 0x10, len(key)) == int.from_bytes(key, "little")
    assert p.get(NODE + 0x18, len(value)) == int.from_bytes(value, "little")
    # Initial pair/byte hash buckets7/4; allocator-mutated keys use3/5.
    index = 7 if pair else 4
    assert p.get(BUCKETS + index * 16, 8) == NODE
    assert p.get(BUCKETS + (3 if pair else 5) * 16, 8) == HEAD


@pytest.mark.parametrize("pair", [False, True])
@pytest.mark.parametrize("load", [0x7F800000, 0x7FC00001, 0x7F800001, 0x3F800000])
def test_ordered_le_or_unordered_load_gate_skips_ceil_and_rehash(pair: bool, load: int) -> None:
    p = Probe()
    p.put(MAP, 4, load)
    key, value = views(pair)
    lookup = lookup_replay_task_pair if pair else lookup_replay_task_byte
    lookup(p.context, MAP, OUT, key, value, calls=p.calls)
    assert not p.matching(0x142D6E453)
    assert not p.matching(0x14114D760 if pair else 0x14114D970)


@pytest.mark.parametrize("pair", [False, True])
@pytest.mark.parametrize(
    ("ceiling", "requested"),
    [
        (0x3F800000, 8),
        (0x43000000, 128),
        (0x7FC00001, 1 << 63),
        (0xBF800000, U64),
        (0x5F000000, 1 << 63),
        (0x5F800000, 1 << 63),
    ],
)
def test_rehash_uses_literal_float_conversion_not_clamped_math(
    pair: bool, ceiling: int, requested: int
) -> None:
    p = Probe()
    p.put(MAP, 4, 0)
    p.hooks[0x142D6E453] = lambda args, data: ceiling
    key, value = views(pair)
    lookup = lookup_replay_task_pair if pair else lookup_replay_task_byte
    lookup(p.context, MAP, OUT, key, value, calls=p.calls)
    assert p.matching(0x14114D760 if pair else 0x14114D970)[0][2] == (MAP, requested)
    assert ("read", 0x1436A0308, 4) in p.events


@pytest.mark.parametrize("pair", [False, True])
def test_length_error_keeps_out_and_does_not_allocate(pair: bool) -> None:
    p = Probe()
    p.put(MAP + 0x10, 8, 0x07FFFFFFFFFFFFFF)
    key, value = views(pair)
    lookup = lookup_replay_task_pair if pair else lookup_replay_task_byte
    with pytest.raises(UnresolvedReplayTaskContainer):
        lookup(p.context, MAP, OUT, key, value, calls=p.calls)
    assert p.matching(0x142D66698)[0][2] == (0x143682918,)
    assert not p.matching(0x142D6BA78)
    assert p.get(OUT + 8, 1) == 0xA5


@pytest.mark.parametrize("pair", [False, True])
def test_dense_clear_free_order_and_current_head_after_free(pair: bool) -> None:
    p = Probe()
    p.put(MAP + 0x10, 8, 2)
    p.put(HEAD, 8, NODE)
    p.put(HEAD + 8, 8, NODE + 32)
    p.put(NODE, 8, NODE + 32)
    p.put(NODE + 32, 8, HEAD)
    new_head = HEAD + 64

    def free(args: tuple[int, ...], data: memoryview | None) -> None:
        p.put(MAP + 8, 8, new_head)

    p.hooks[0x142D6BAB4] = free
    clear = clear_replay_task_pair if pair else clear_replay_task_byte
    clear(p.context, MAP, calls=p.calls)
    assert [e[2] for e in p.matching(0x142D6BAB4)] == [(NODE, 32), (NODE + 32, 32)]
    assert p.get(new_head, 8) == p.get(new_head + 8, 8) == new_head
    assert p.get(MAP + 0x10, 8) == 0
    assert all(p.get(BUCKETS + i * 8, 8) == new_head for i in range(16))
    assert p.matching(0x141143790 if pair else 0x141143820)[0][3] == new_head.to_bytes(8, "little")


@pytest.mark.parametrize("pair", [False, True])
def test_zero_count_clear_only_reads_count(pair: bool) -> None:
    p = Probe()
    clear = clear_replay_task_pair if pair else clear_replay_task_byte
    clear(p.context, MAP, calls=p.calls)
    assert p.events == [("read", MAP + 0x10, 8)]


def test_sparse_clear_holds_bucket_base_head_and_decrements_current_count() -> None:
    p = Probe()
    p.map(MAP, HEAD, BUCKETS, count=1, bucket_count=64)
    key, value = views(False)
    # Populate through the real insert, then choose sparse threshold again.
    p.put(MAP + 0x10, 8, 0)
    lookup_replay_task_byte(p.context, MAP, OUT, key, value, calls=p.calls)
    p.events.clear()

    def free(args: tuple[int, ...], data: memoryview | None) -> None:
        p.put(MAP + 0x18, 8, 0xDEAD)
        p.put(MAP + 8, 8, 0xBEEF)
        p.put(MAP + 0x10, 8, 8)

    p.hooks[0x142D6BAB4] = free
    clear_replay_task_byte(p.context, MAP, calls=p.calls)
    assert p.get(MAP + 0x10, 8) == 7
    assert p.get(HEAD, 8) == p.get(HEAD + 8, 8) == HEAD
    assert p.get(BUCKETS + 12 * 16, 8) == HEAD
    assert not p.matching(0x141143820)


@pytest.mark.parametrize(("position", "expected"), [(OLD, 0), (OLD + 64, 64), (OLD + 128, 128)])
def test_vector_growth_insert_order_content_and_capacity(position: int, expected: int) -> None:
    p = Probe()
    p.vector(2, 2)
    p.put(OLD, 64, int.from_bytes(b"a" * 64, "little"))
    p.put(OLD + 64, 64, int.from_bytes(b"b" * 64, "little"))
    descriptor = memoryview(bytearray(b"x" * 64))
    result = grow_replay_task_vector64(p.context, VECTOR, position, descriptor, calls=p.calls)
    assert result == NEW + expected
    raw = p.get(NEW, 192).to_bytes(192, "little")
    original = b"a" * 64 + b"b" * 64
    assert raw == original[:expected] + b"x" * 64 + original[expected:]
    assert (p.get(VECTOR, 8), p.get(VECTOR + 8, 8), p.get(VECTOR + 16, 8)) == (
        NEW,
        NEW + 192,
        NEW + 192,
    )
    assert p.matching(0x142D6BAB4)[0][2] == (OLD, 128)


def test_vector_allocation_mutation_copies_current_descriptor_before_moves() -> None:
    p = Probe()
    descriptor = memoryview(bytearray(b"a" * 64))

    def allocate(args: tuple[int, ...], data: memoryview | None) -> int:
        descriptor[:] = b"b" * 64
        return NEW

    p.hooks[0x1402A94D0] = allocate
    grow_replay_task_vector64(p.context, VECTOR, OLD + 64, descriptor, calls=p.calls)
    assert p.get(NEW + 64, 64).to_bytes(64, "little") == b"b" * 64
    move = p.events.index(p.matching(0x142D6E3DB)[0])
    assert (
        len([e for e in p.events[:move] if e[0] == "write" and NEW + 64 <= int(e[1]) < NEW + 128])
        == 4
    )


@pytest.mark.parametrize(("delta", "valid"), [(8, True), (39, True), (40, False), (0, False)])
def test_large_vector_header_free_size_and_watson(delta: int, valid: bool) -> None:
    p = Probe()
    p.vector(64, 64)
    p.put(OLD - 8, 8, OLD - delta)
    descriptor = memoryview(bytearray(64))
    if valid:
        grow_replay_task_vector64(p.context, VECTOR, OLD + 4096, descriptor, calls=p.calls)
        assert p.matching(0x142D6BAB4)[0][2] == (OLD - delta, 4096 + 39)
    else:
        with pytest.raises(UnresolvedReplayTaskContainer):
            grow_replay_task_vector64(p.context, VECTOR, OLD + 4096, descriptor, calls=p.calls)
        assert p.matching(0xABCDE)[0][2] == (0, 0, 0, 0, 0)
        assert p.get(VECTOR, 8) == OLD
        assert not p.matching(0x142D6BAB4)


def test_watson_unexpected_return_stops_at_original_int3_gap() -> None:
    p = Probe()
    p.vector(64, 64)
    p.put(OLD - 8, 8, OLD)
    p.hooks[0xABCDE] = lambda args, data: None
    with pytest.raises(RuntimeError, match="unexpectedly returned"):
        grow_replay_task_vector64(
            p.context, VECTOR, OLD + 4096, memoryview(bytearray(64)), calls=p.calls
        )
    assert not p.matching(0x14114DD60)
    assert p.get(VECTOR, 8) == OLD


def test_prefix_binds_real_lookup_and_append_body() -> None:
    p = Probe()
    subject, tasks, pointers, task = MAP, 0xA0000, 0xA0100, 0xB0000
    for base, size in ((tasks, 0x200), (task, 0x100)):
        p.memory.update((base + i, 0) for i in range(size))
    p.map(subject + 0x548, HEAD, BUCKETS)
    p.map(subject + 0x5D8, HEAD + 32, BUCKETS + 0x400)
    for offset, value in ((0x530, 0), (0x538, 0), (0x540, 0)):
        p.put(subject + offset, 8, value)
    p.put(tasks + 8, 8, pointers)
    p.put(tasks + 16, 8, pointers + 8)
    p.put(pointers, 8, task)
    p.put(task + 0xE, 2, 157)
    p.put(task + 0x36, 2, 3)
    p.put(task + 0x1C, 4, 0x41200000)
    bound = bind_replay_task_prefix_containers(
        p.context, pair_out=OUT, byte_out=OUT + 32, calls=p.calls
    )
    run_replay_task_prefix(
        p.context,
        tasks,
        mxcsr=0x1F80,
        scratch=ReplayTaskPrefixScratch(bytes(64), b"abc", b"xyz"),
        calls=bound,
    )
    assert p.get(subject + 0x558, 8) == 1
    assert p.get(NODE + 0x18, 4) == 3
    assert p.get(subject + 0x530, 8) == NEW
    assert p.get(subject + 0x538, 8) == NEW + 64
    assert p.get(NEW + 0x30, 4) == 3
    assert p.get(OUT + 8, 1) == 1


@pytest.mark.parametrize("mxcsr", [0, 0x1F40, 0x3F80, 0x9F80, True, -1, 1 << 32])
def test_refuses_unsupported_float_profile(mxcsr: int) -> None:
    with pytest.raises(ValueError):
        ReplayTaskContainerCalls(None, mxcsr)


def test_reached_unavailable_allocator_has_no_fabricated_insert() -> None:
    p = Probe()
    key, value = views(True)
    with pytest.raises(UnresolvedReplayTaskContainer):
        lookup_replay_task_pair(
            p.context, MAP, OUT, key, value, calls=ReplayTaskContainerCalls(None, 0x1F80)
        )
    assert p.get(MAP + 0x10, 8) == 0
    assert p.get(OUT + 8, 1) == 0xA5
