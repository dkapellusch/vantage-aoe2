"""Rehash links and actual source-address fill controls over current backing."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from vantage.replay_task_buckets import (
    fill_replay_task_buckets,
    rehash_replay_task_byte,
    rehash_replay_task_pair,
)
from vantage.replay_task_containers import ReplayTaskContainerCalls
from vantage.replay_task_rebuild import ReplayTaskRebuildStorage

MAP, HEAD, TABLE, NODES, FILL, SOURCE = 0x10000, 0x20000, 0x30000, 0x40000, 0x50000, 0x60000
U64 = (1 << 64) - 1
Hook = Callable[[tuple[int, ...], memoryview | None], int | None]


class Probe:
    def __init__(self, keys: tuple[int, ...] = (), *, pair: bool = True) -> None:
        self.memory: dict[int, int] = {}
        self.events: list[tuple[object, ...]] = []
        self.hook: Hook | None = None
        self.after_write: Callable[[], None] | None = None
        for base, size in (
            (MAP, 0x40),
            (HEAD, 0x100),
            (TABLE, 0x800),
            (NODES, 0x1000),
            (FILL - 8, 0x100),
            (SOURCE, 16),
        ):
            self.put(base, size, 0)
        for offset, value in (
            (8, HEAD),
            (0x10, len(keys)),
            (0x18, TABLE),
            (0x20, TABLE + 16),
            (0x28, TABLE + 16),
            (0x30, 0),
            (0x38, 1),
        ):
            self.put(MAP + offset, 8, value)
        self.put(HEAD, 8, NODES if keys else HEAD)
        self.put(HEAD + 8, 8, NODES + 32 * (len(keys) - 1) if keys else HEAD)
        for index, key in enumerate(keys):
            node = NODES + 32 * index
            self.put(node, 8, node + 32 if index + 1 < len(keys) else HEAD)
            self.put(node + 8, 8, node - 32 if index else HEAD)
            self.put(node + 0x10, 8, key if pair else 0xA5A5A5A5A5A5A500 | key)
            self.put(node + 0x18, 8, 0x123456789ABCDEF0 + index)

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
        if self.after_write is not None:
            self.after_write()

    @property
    def context(self) -> ReplayTaskRebuildStorage:
        return ReplayTaskRebuildStorage(MAP, self.read, self.write)

    @property
    def calls(self) -> ReplayTaskContainerCalls:
        return ReplayTaskContainerCalls(self.call, 0x1F80)

    def call(self, target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        self.events.append(("call", target, args))
        if self.hook is not None:
            return self.hook(args, data)
        assert target in (0x14114D5C0, 0x14114D690)
        header, qwords, sentinel = args
        assert header == MAP + 0x18
        # A controlled bucket-storage leaf, not evidence of enormous allocation.
        for i in range(min(qwords, 256)):
            self.put(TABLE + i * 8, 8, sentinel)
        return None

    def walk(self) -> list[int]:
        node = self.get(HEAD, 8)
        result = []
        while node != HEAD:
            assert node not in result
            result.append(node)
            node = self.get(node, 8)
        return result


@pytest.mark.parametrize("pair", [False, True])
@pytest.mark.parametrize(
    ("requested", "count"),
    [
        (0, 1),
        (1, 2),
        (2, 2),
        (3, 4),
        (4, 4),
        (7, 8),
        (8, 8),
        (9, 16),
        (512, 512),
        (1 << 59, 1 << 59),
    ],
)
def test_empty_rehash_count_and_real_leaf_arguments(pair: bool, requested: int, count: int) -> None:
    p = Probe(pair=pair)
    run = rehash_replay_task_pair if pair else rehash_replay_task_byte
    run(p.context, MAP, requested, calls=p.calls)
    assert ("call", 0x14114D5C0 if pair else 0x14114D690, (MAP + 0x18, 2 * count, HEAD)) in p.events
    assert p.get(MAP + 0x38, 8) == count and p.get(MAP + 0x30, 8) == count - 1
    assert p.get(MAP + 0x10, 8) == 0


@pytest.mark.parametrize("pair", [False, True])
@pytest.mark.parametrize(
    ("keys", "requested", "order"),
    [
        ((1,), 0, (0,)),
        ((1, 1), 0, (0, 1)),
        ((1, 2, 1), 2, (0, 2, 1)),
        ((1, 3), 0, (1, 0)),
        ((1, 3, 3), 0, (1, 2, 0)),
    ],
)
def test_all_rehash_link_paths_preserve_payload_and_current_count(
    pair: bool,
    keys: tuple[int, ...],
    requested: int,
    order: tuple[int, ...],
) -> None:
    p = Probe(keys, pair=pair)
    payload = [p.get(NODES + i * 32 + 0x10, 16) for i in range(len(keys))]
    run = rehash_replay_task_pair if pair else rehash_replay_task_byte
    run(p.context, MAP, requested, calls=p.calls)
    assert p.walk() == [NODES + i * 32 for i in order]
    assert p.get(MAP + 0x10, 8) == len(keys)
    assert [p.get(NODES + i * 32 + 0x10, 16) for i in range(len(keys))] == payload
    for node in p.walk():
        following, previous = p.get(node, 8), p.get(node + 8, 8)
        assert p.get(following + 8, 8) == node and p.get(previous, 8) == node


def test_pair_second_dword_and_compiler_read_order() -> None:
    p = Probe((1, 1 | 1 << 32))
    rehash_replay_task_pair(p.context, MAP, 0, calls=p.calls)
    assert p.walk() == [NODES + 32, NODES]
    first = p.events.index(("read", NODES + 0x15, 1))
    assert p.events[first : first + 9] == [
        ("read", NODES + offset, width)
        for offset, width in (
            (0x15, 1),
            (0x14, 1),
            (0x10, 1),
            (0, 8),
            (0x16, 1),
            (0x17, 1),
            (0x11, 1),
            (0x12, 1),
            (0x13, 1),
        )
    ]


@pytest.mark.parametrize("pair", [False, True])
def test_current_proxy_head_traversal_still_stops_at_held_old_head(pair: bool) -> None:
    p = Probe(pair=pair)

    def leaf(args: tuple[int, ...], data: memoryview | None) -> None:
        p.put(MAP + 8, 8, HEAD + 64)
        p.put(HEAD + 64, 8, HEAD)

    p.hook = leaf
    run = rehash_replay_task_pair if pair else rehash_replay_task_byte
    run(p.context, MAP, 2, calls=p.calls)
    assert p.events[-4:] == [
        ("write", MAP + 0x38, 8, 2),
        ("write", MAP + 0x30, 8, 1),
        ("read", MAP + 8, 8),
        ("read", HEAD + 64, 8),
    ]


@pytest.mark.parametrize("pair", [False, True])
def test_storage_failure_preserves_leaf_effect_before_metadata_commit(pair: bool) -> None:
    p = Probe(pair=pair)

    def leaf(args: tuple[int, ...], data: memoryview | None) -> None:
        p.put(MAP + 0x10, 8, 9)
        raise LookupError("actual storage failure")

    p.hook = leaf
    run = rehash_replay_task_pair if pair else rehash_replay_task_byte
    with pytest.raises(LookupError):
        run(p.context, MAP, 8, calls=p.calls)
    assert p.get(MAP + 0x10, 8) == 9
    assert (p.get(MAP + 0x30, 8), p.get(MAP + 0x38, 8)) == (0, 1)


@pytest.mark.parametrize("pair", [False, True])
def test_over_limit_calls_error_before_any_map_read(pair: bool) -> None:
    p = Probe(pair=pair)
    p.hook = lambda args, data: None
    run = rehash_replay_task_pair if pair else rehash_replay_task_byte
    with pytest.raises(RuntimeError, match="unexpectedly returned"):
        run(p.context, MAP, (1 << 59) + 1, calls=p.calls)
    assert p.events == [("call", 0x142D66698, (0x143682938,))]


@pytest.mark.parametrize(
    ("count", "offset", "reads"),
    [
        (0, 100, 0),
        (1, 100, 1),
        (2, 100, 1),
        (3, 100, 2),
        (2, 0, 3),
        (3, 0, 4),
        (3, 16, 4),
        (3, 17, 2),
    ],
)
def test_fill_eager_read_and_inclusive_start_address_alias_check(
    count: int,
    offset: int,
    reads: int,
) -> None:
    p = Probe()
    p.put(FILL + offset, 8, 0x12345678)
    fill_replay_task_buckets(p.context, FILL, FILL + count * 8, FILL + offset)
    assert sum(e[0] == "read" for e in p.events) == reads
    assert sum(e[0] == "write" for e in p.events) == count


def test_partial_overlap_outside_interval_odd_tail_reads_changed_bytes() -> None:
    p = Probe()
    for i in range(32):
        p.put(FILL - 1 + i, 1, i + 1)
    fill_replay_task_buckets(p.context, FILL, FILL + 24, FILL - 1)
    assert p.get(FILL, 8) == p.get(FILL + 8, 8) == 0x0807060504030201
    assert p.get(FILL + 16, 8) == 0x0706050403020101


def test_bulk_caches_source_but_odd_tail_reads_current_value() -> None:
    p = Probe()
    p.put(SOURCE, 8, 1)
    p.after_write = lambda: p.put(SOURCE, 8, 2)
    fill_replay_task_buckets(p.context, FILL, FILL + 24, SOURCE)
    assert [p.get(FILL + i * 8, 8) for i in range(3)] == [1, 1, 2]


@pytest.mark.parametrize(("begin", "end"), [(FILL, FILL - 8), (FILL, FILL + 7), (U64 - 7, 8)])
def test_non_admitted_fill_ranges_refused_before_effects(begin: int, end: int) -> None:
    p = Probe()
    with pytest.raises(ValueError):
        fill_replay_task_buckets(p.context, begin, end, SOURCE)
    assert not p.events
