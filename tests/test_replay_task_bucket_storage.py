"""Bucket storage/release controls and real helper routing over live locals.

Allocator/free/CRT programs are test controls, not restored World/heap evidence.
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from types import TracebackType

import pytest

from vantage.replay_task_bucket_storage import (
    bind_replay_task_bucket_leaves,
    release_replay_task_byte_buckets,
    release_replay_task_pair_buckets,
    resize_replay_task_byte_buckets,
    resize_replay_task_pair_buckets,
)
from vantage.replay_task_containers import (
    ReplayTaskContainerCalls,
    bind_replay_task_prefix_containers,
)
from vantage.replay_task_prefix import ReplayTaskPrefixScratch, run_replay_task_prefix
from vantage.replay_task_rebuild import ReplayTaskRebuildStorage

HEADER, OLD, NEW, NODE, HEAD, TABLE = 0x10000, 0x20000, 0x30000, 0x40000, 0x50000, 0x60000
SUBJECT, LIST, TASK, LOCAL, OUT = 0x70000, 0x80000, 0x90000, 0x100000, 0x110000
U64 = (1 << 64) - 1
Hook = Callable[[tuple[int, ...], memoryview | None], int | None]


class Probe:
    def __init__(self) -> None:
        self.memory: dict[int, int] = {}
        self.events: list[tuple[object, ...]] = []
        self.hooks: dict[int, Hook] = {}
        self.locals: list[tuple[int, memoryview]] = []
        self.allocations = 0
        self.nodes = 0
        self.suppress = False
        self.fail_write: int | None = None
        for base, size in (
            (HEADER, 0x100),
            (OLD - 8, 0x4008),
            (NEW, 0x6000),
            (NODE, 0x1000),
            (HEAD, 0x100),
            (TABLE, 0x1000),
            (SUBJECT, 0x1000),
            (LIST, 0x1000),
            (TASK, 0x1000),
            (OUT, 0x100),
        ):
            self.put(base, size, 0)
        self.vector(4, 8)
        self.put(0x14319A060, 8, 0xFACE)
        self.put(0x1436A0308, 4, 0x5F000000)
        self.put(0x1432A70C0, 4, 0x08040201)

    def put(self, address: int, width: int, value: int) -> None:
        self.memory.update(((address + i) & U64, value >> (8 * i) & 255) for i in range(width))

    def get(self, address: int, width: int) -> int:
        result = 0
        for i in range(width):
            at = (address + i) & U64
            for base, view in reversed(self.locals):
                if base <= at < base + len(view):
                    byte = view[at - base]
                    break
            else:
                byte = self.memory[at]
            result |= byte << (8 * i)
        return result

    def read(self, address: int, width: int) -> int:
        self.events.append(("read", address, width))
        return self.get(address, width)

    def write(self, address: int, width: int, value: int) -> None:
        self.events.append(("write", address, width, value))
        if address == self.fail_write:
            raise OSError("current backing write unavailable")
        for i in range(width):
            at, byte = (address + i) & U64, value >> (8 * i) & 255
            for base, view in reversed(self.locals):
                if base <= at < base + len(view):
                    view[at - base] = byte
                    break
            else:
                self.memory[at] = byte

    @property
    def context(self) -> ReplayTaskRebuildStorage:
        return ReplayTaskRebuildStorage(SUBJECT, self.read, self.write)

    @property
    def calls(self) -> ReplayTaskContainerCalls:
        return ReplayTaskContainerCalls(self.call, 0x1F80)

    def call(self, target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        self.events.append(("call", target, args, None if data is None else bytes(data)))
        if target in self.hooks:
            return self.hooks[target](args, data)
        if target == 0x1402A94D0:
            result = NEW + 0x1000 * self.allocations
            self.allocations += 1
            return result
        if target == 0x142D6BA78:
            result = NODE + 32 * self.nodes
            self.nodes += 1
            self.put(result, 32, int.from_bytes(b"\xa5" * 32, "little"))
            return result
        if target == 0x142D6E453:
            return 0x41000000  # Explicit bound ceil response8 for the integration control.
        if target == 0x142D6E3DB:
            dest, source, count = args
            self.put(dest, count, self.get(source, count))
        elif target not in (
            0x141143790,
            0x141143820,
            0x1411526A0,
            0x141152700,
            0x142D6BAB4,
            0xFACE,
        ):
            raise LookupError(f"controlled leaf{target:x} unavailable")
        return None

    def vector(self, size: int, capacity: int) -> None:
        for offset, value in ((0, OLD), (8, OLD + 8 * size), (16, OLD + 8 * capacity)):
            self.put(HEADER + offset, 8, value)

    def matching(self, target: int) -> list[tuple[object, ...]]:
        return [event for event in self.events if event[:2] == ("call", target)]

    def bind_local(self, view: memoryview) -> LiveMapping:
        return LiveMapping(self, view)

    def bound(self) -> ReplayTaskContainerCalls:
        return bind_replay_task_bucket_leaves(self.context, self.calls, bind_local=self.bind_local)


class LiveMapping(AbstractContextManager[int]):
    def __init__(self, probe: Probe, view: memoryview) -> None:
        self.probe, self.view = probe, view
        self.address = LOCAL + 16 * len(probe.locals)

    def __enter__(self) -> int:
        self.probe.locals.append((self.address, self.view))
        self.probe.events.append(("bind", self.address))
        return self.address

    def __exit__(
        self,
        kind: type[BaseException] | None,
        value: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool:
        address, view = self.probe.locals.pop()
        assert address == self.address and view is self.view
        self.probe.events.append(("unbind", address, kind))
        return self.probe.suppress


@pytest.mark.parametrize("pair", [False, True])
@pytest.mark.parametrize("requested", [0, 1, 4])
def test_reuse_calls_fill_for_entire_old_size_without_header_stores(
    pair: bool,
    requested: int,
) -> None:
    p = Probe()
    resize = resize_replay_task_pair_buckets if pair else resize_replay_task_byte_buckets
    before = p.get(HEADER, 24)
    resize(p.context, HEADER, requested, 0x1122334455667788, calls=p.calls)
    fill = p.matching(0x141143790 if pair else 0x141143820)
    assert fill == [
        (
            "call",
            0x141143790 if pair else 0x141143820,
            (OLD, OLD + 32),
            bytes.fromhex("8877665544332211"),
        )
    ]
    assert p.get(HEADER, 24) == before
    assert not [e for e in p.events if e[0] == "write"]
    assert not p.matching(0x1402A94D0)


@pytest.mark.parametrize("pair", [False, True])
def test_growth_compares_size_not_spare_capacity_and_commits_before_fill(pair: bool) -> None:
    p = Probe()
    resize = resize_replay_task_pair_buckets if pair else resize_replay_task_byte_buckets
    resize(p.context, HEADER, 5, 0xBEEF, calls=p.calls)
    assert p.matching(0x1402A94D0)[0][2] == (40,)
    assert p.matching(0x1411526A0 if pair else 0x141152700)[0][2] == (HEADER, OLD, 8)
    writes = [e for e in p.events if e[0] == "write"]
    assert writes[:3] == [
        ("write", HEADER, 8, NEW),
        ("write", HEADER + 8, 8, NEW + 40),
        ("write", HEADER + 16, 8, NEW + 40),
    ]
    assert [p.get(NEW + i * 8, 8) for i in range(5)] == [0xBEEF] * 5
    assert not p.matching(0x141143790 if pair else 0x141143820)


@pytest.mark.parametrize("pair", [False, True])
def test_growth_reloads_current_begin_capacity_and_holds_original_value(pair: bool) -> None:
    p = Probe()

    def allocate(args: tuple[int, ...], data: memoryview | None) -> int:
        p.put(HEADER, 8, OLD + 8)
        p.put(HEADER + 16, 8, OLD + 72)
        return NEW

    def release(args: tuple[int, ...], data: memoryview | None) -> None:
        assert args == (HEADER, OLD + 8, 8)
        p.put(HEADER, 24, 0xBAD)

    p.hooks[0x1402A94D0] = allocate
    p.hooks[0x1411526A0 if pair else 0x141152700] = release
    resize = resize_replay_task_pair_buckets if pair else resize_replay_task_byte_buckets
    resize(p.context, HEADER, 5, 0xCAFEBABE, calls=p.calls)
    assert p.get(HEADER, 8) == NEW
    assert p.get(HEADER + 8, 8) == p.get(HEADER + 16, 8) == NEW + 40
    assert [p.get(NEW + i * 8, 8) for i in range(5)] == [0xCAFEBABE] * 5


@pytest.mark.parametrize("pair", [False, True])
def test_zero_current_capacity_skips_release_even_with_nonnull_begin(pair: bool) -> None:
    p = Probe()
    p.vector(0, 0)
    resize = resize_replay_task_pair_buckets if pair else resize_replay_task_byte_buckets
    resize(p.context, HEADER, 1, 7, calls=p.calls)
    assert not p.matching(0x1411526A0 if pair else 0x141152700)
    assert p.get(HEADER, 8) == NEW and p.get(NEW, 8) == 7


@pytest.mark.parametrize("pair", [False, True])
def test_negative_size_source_control_reuses_before_growth_limit(pair: bool) -> None:
    p = Probe()
    p.put(HEADER + 8, 8, OLD - 8)
    resize = resize_replay_task_pair_buckets if pair else resize_replay_task_byte_buckets
    resize(p.context, HEADER, U64, 7, calls=p.calls)
    assert p.matching(0x141143790 if pair else 0x141143820)[0][2] == (OLD, OLD - 8)
    assert not p.matching(0x1402A94D0)
    # This direct phase control does not execute the native malformed range.


@pytest.mark.parametrize("pair", [False, True])
def test_growth_limit_error_before_allocation_or_header_commit(pair: bool) -> None:
    p = Probe()
    resize = resize_replay_task_pair_buckets if pair else resize_replay_task_byte_buckets
    with pytest.raises(LookupError):
        resize(p.context, HEADER, 1 << 61, 7, calls=p.calls)
    assert p.matching(0x1402A9460)
    assert not p.matching(0x1402A94D0)
    assert not [e for e in p.events if e[0] == "write"]


@pytest.mark.parametrize("pair", [False, True])
def test_release_failure_preserves_leaf_effect_without_committing_new_header(pair: bool) -> None:
    p = Probe()

    def release(args: tuple[int, ...], data: memoryview | None) -> None:
        p.put(HEADER + 8, 8, OLD + 8)
        raise OSError("actual release unavailable")

    p.hooks[0x1411526A0 if pair else 0x141152700] = release
    resize = resize_replay_task_pair_buckets if pair else resize_replay_task_byte_buckets
    with pytest.raises(OSError):
        resize(p.context, HEADER, 5, 7, calls=p.calls)
    assert p.get(HEADER, 8) == OLD and p.get(HEADER + 8, 8) == OLD + 8
    assert not [e for e in p.events if e[0] == "write"]


@pytest.mark.parametrize("pair", [False, True])
@pytest.mark.parametrize(
    ("count", "size", "large"),
    [
        (0, 0, False),
        (1, 8, False),
        (511, 4088, False),
        (512, 4135, True),
        (1 << 61, 0, False),
        (U64, 31, True),
    ],
)
def test_release_uses_registers_not_header_with_wrapping_size(
    pair: bool,
    count: int,
    size: int,
    large: bool,
) -> None:
    p = Probe()
    p.put(OLD - 8, 8, OLD - 16)
    before = p.get(HEADER, 24)
    release = release_replay_task_pair_buckets if pair else release_replay_task_byte_buckets
    release(p.context, 0xBAD, OLD, count, calls=p.calls)
    assert p.matching(0x142D6BAB4)[0][2] == (OLD - 16 if large else OLD, size)
    assert p.get(HEADER, 24) == before
    assert [e for e in p.events if e[0] == "read"] == ([("read", OLD - 8, 8)] if large else [])


@pytest.mark.parametrize("pair", [False, True])
def test_release_has_no_null_pointer_guard(pair: bool) -> None:
    p = Probe()
    release = release_replay_task_pair_buckets if pair else release_replay_task_byte_buckets
    release(p.context, HEADER, 0, 0, calls=p.calls)
    assert p.events == [("call", 0x142D6BAB4, (0, 0), None)]


@pytest.mark.parametrize("pair", [False, True])
@pytest.mark.parametrize(("offset", "valid"), [(8, True), (39, True), (40, False), (0, False)])
def test_large_release_header_boundary_and_returned_watson(
    pair: bool,
    offset: int,
    valid: bool,
) -> None:
    p = Probe()
    p.put(OLD - 8, 8, OLD - offset)
    release = release_replay_task_pair_buckets if pair else release_replay_task_byte_buckets
    if valid:
        release(p.context, HEADER, OLD, 512, calls=p.calls)
        assert p.matching(0x142D6BAB4)[0][2] == (OLD - offset, 4096 + 39)
    else:
        with pytest.raises(RuntimeError, match="unexpectedly returned"):
            release(p.context, HEADER, OLD, 512, calls=p.calls)
        assert p.matching(0xFACE)[0][2] == (0, 0, 0, 0, 0)
        assert not p.matching(0x142D6BAB4)


@pytest.mark.parametrize("pair", [False, True])
def test_router_reuse_binds_live_local_and_executes_full_fill(pair: bool) -> None:
    p = Probe()
    resize = resize_replay_task_pair_buckets if pair else resize_replay_task_byte_buckets
    resize(p.context, HEADER, 1, 0xBEEF, calls=p.bound())
    assert [p.get(OLD + i * 8, 8) for i in range(4)] == [0xBEEF] * 4
    assert not p.locals and ("bind", LOCAL) in p.events
    assert not p.matching(0x141143790 if pair else 0x141143820)


@pytest.mark.parametrize("pair", [False, True])
def test_router_growth_runs_actual_release_before_commit(pair: bool) -> None:
    p = Probe()
    resize = resize_replay_task_pair_buckets if pair else resize_replay_task_byte_buckets
    resize(p.context, HEADER, 5, 0xBEEF, calls=p.bound())
    assert p.matching(0x142D6BAB4)[0][2] == (OLD, 64)
    assert p.get(HEADER, 8) == NEW
    assert not p.matching(0x1411526A0 if pair else 0x141152700)


def test_live_local_mapping_is_not_a_snapshot_and_nested_mapping_is_restored() -> None:
    p = Probe()
    outer = memoryview(bytearray((9).to_bytes(8, "little")))
    inner = memoryview(bytearray((1).to_bytes(8, "little")))
    bound = p.bound()
    with p.bind_local(outer) as at:
        assert p.locals == [(at, outer)]
        # Mutate the bound live source after its first fill store, before odd tail read.
        original_write = p.write

        def write(address: int, width: int, value: int) -> None:
            original_write(address, width, value)
            inner[:] = (2).to_bytes(8, "little")

        context = ReplayTaskRebuildStorage(SUBJECT, p.read, write)
        bound = bind_replay_task_bucket_leaves(context, p.calls, bind_local=p.bind_local)
        assert bound.call is not None
        bound.call(0x141143790, (OLD, OLD + 24), inner)
        assert [p.get(OLD + 8 * i, 8) for i in range(3)] == [1, 1, 2]
        assert p.locals == [(at, outer)] and p.get(at, 8) == 9
    assert not p.locals


def test_truthy_mapping_exit_cannot_suppress_a_fill_failure() -> None:
    p = Probe()
    p.suppress, p.fail_write = True, OLD + 8
    bound = p.bound()
    assert bound.call is not None
    with pytest.raises(OSError, match="current backing write unavailable"):
        bound.call(0x141143790, (OLD, OLD + 24), memoryview(bytearray((7).to_bytes(8, "little"))))
    assert p.get(OLD, 8) == 7 and not p.locals
    assert p.events[-1] == ("unbind", LOCAL, OSError)


def test_prefix_real_map_rehash_resize_release_and_vector_chain() -> None:
    p = Probe()
    for base, head, table in (
        (SUBJECT + 0x548, HEAD, TABLE),
        (SUBJECT + 0x5D8, HEAD + 32, TABLE + 0x100),
    ):
        p.put(base, 4, 0x3E000000)
        for offset, value in (
            (8, head),
            (0x10, 0),
            (0x18, table),
            (0x20, table + 16),
            (0x28, table + 16),
            (0x30, 0),
            (0x38, 1),
        ):
            p.put(base + offset, 8, value)
        p.put(head, 8, head)
        p.put(head + 8, 8, head)
        p.put(table, 8, head)
        p.put(table + 8, 8, head)
    for offset in (0x530, 0x538, 0x540):
        p.put(SUBJECT + offset, 8, 0)
    p.put(LIST + 8, 8, LIST + 0x100)
    p.put(LIST + 16, 8, LIST + 0x110)
    p.put(LIST + 0x100, 8, TASK)
    p.put(LIST + 0x108, 8, TASK + 0x100)
    p.put(TASK + 0xE, 2, 157)
    p.put(TASK + 0x36, 2, 3)
    p.put(TASK + 0x1C, 4, 0x41200000)
    p.put(TASK + 0x100 + 0xE, 2, 162)
    p.put(TASK + 0x100 + 0x15, 1, 1)
    p.put(TASK + 0x100 + 0x28, 4, 0x3F800000)
    calls = bind_replay_task_prefix_containers(
        p.context, pair_out=OUT, byte_out=OUT + 32, calls=p.bound()
    )
    run_replay_task_prefix(
        p.context,
        LIST,
        mxcsr=0x1F80,
        scratch=ReplayTaskPrefixScratch(bytes(range(64)), b"abc", b"xyz"),
        calls=calls,
    )
    assert p.get(SUBJECT + 0x558, 8) == p.get(SUBJECT + 0x5E8, 8) == 1
    assert p.get(SUBJECT + 0x580, 8) == p.get(SUBJECT + 0x610, 8) == 8
    assert p.get(NODE + 0x18, 4) == 3 and p.get(NODE + 32 + 0x18, 8) == TASK + 0x100
    assert p.get(SUBJECT + 0x538, 8) - p.get(SUBJECT + 0x530, 8) == 64
    assert [e[2] for e in p.matching(0x142D6BAB4)] == [(TABLE, 16), (TABLE + 0x100, 16)]
    assert not p.locals
