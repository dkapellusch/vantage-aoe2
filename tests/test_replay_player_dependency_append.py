"""Source-derived append controls over actual owned backing and real reserve."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager

import pytest

from vantage import replay_player_dependency_append as append
from vantage.replay_memory import ReplayMemory, ReplayMemoryError
from vantage.replay_research_storage import (
    ReplayResearchStorageScratch,
    bind_replay_research_storage,
)
from vantage.replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
)
from vantage.replay_unit_constructor_support import bind_replay_unit_constructor_support

H, S, U64 = 0x1000, 0x2000, (1 << 64) - 1
ENTRY, RESERVE = 0x140B53800, 0x140B55580
ALLOC, FREE, COPY = 0x142D6BA78, 0x142D6BAB4, 0x142D6E3DB


class Fixture:
    def __init__(self) -> None:
        self.memory = ReplayMemory(max_bytes=1 << 20)
        self.events: list[tuple[object, ...]] = []
        self.on_read: Callable[[int, int, int], None] | None = None
        self.on_write: Callable[[int, int, int], None] | None = None
        self.after_reserve: Callable[[], None] | None = None
        self.before_import: Callable[[int, tuple[int, ...]], None] | None = None
        self.context = ReplayTaskRebuildStorage(H, self.read, self.write)
        self.terminal = ReplayTaskRebuildCalls(self.import_call)
        self.have_reserve = True
        for slot, target in ((0x143199DB0, ALLOC), (0x143199DD0, FREE), (0x143199930, COPY)):
            self.memory.map_bytes(slot, target.to_bytes(8, "little"))
        self.lower = bind_replay_unit_constructor_support(
            self.context,
            ReplayTaskRebuildCalls(None),
            bind_local=self.bind_local,
            imports=self.terminal,
        )
        self.reserve = bind_replay_research_storage(
            self.context,
            self.lower,
            imports=self.terminal,
            bind_local=self.bind_local,
            scratch=ReplayResearchStorageScratch(b"\xa5" * 8),
        )
        self.calls = ReplayTaskRebuildCalls(self.dispatch)

    def read(self, address: int, width: int) -> int:
        value = self.memory.read(address, width)
        self.events.append(("r", address, width, value))
        if self.on_read is not None:
            self.on_read(address, width, value)
        return value

    def write(self, address: int, width: int, value: int) -> None:
        self.memory.write(address, width, value)
        self.events.append(("w", address, width, value))
        if self.on_write is not None:
            self.on_write(address, width, value)

    def import_call(
        self,
        target: int,
        args: tuple[int, ...],
        data: memoryview | None,
    ) -> int | None:
        self.events.append(("i", target, args))
        if self.before_import is not None:
            self.before_import(target, args)
        assert self.memory.runtime_calls().call is not None
        return self.memory.runtime_calls().call(target, args, data)

    def dispatch(self, target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        self.events.append(("c", target, args))
        if target != RESERVE or not self.have_reserve:
            raise UnresolvedReplayTaskRebuild(f"actual helper{target:x} unavailable")
        assert self.reserve.call is not None
        result = self.reserve.call(target, args, data)
        if self.after_reserve is not None:
            self.after_reserve()
        return result

    @contextmanager
    def bind_local(self, view: memoryview) -> Iterator[int]:
        with self.memory.bind_local(view) as address:
            yield address

    def header(
        self,
        begin: int = 0,
        capacity: int = 0,
        count: int = 0,
        quantum: int | None = 32,
        *,
        writable: bool = True,
    ) -> None:
        values = (begin, capacity, count) if quantum is None else (begin, capacity, count, quantum)
        self.memory.map_bytes(
            H, b"".join(value.to_bytes(8, "little") for value in values), writable=writable
        )

    def source(self, value: int = 7, *, writable: bool = True) -> None:
        self.memory.map_bytes(S, value.to_bytes(4, "little"), writable=writable)

    def block(self, count: int, fill: int = 0) -> int:
        address = self.memory.allocate(count * 4)
        self.memory.fill(address, fill, count * 4)
        return address

    def run(self, source: int = S, *, bound: bool = False) -> None:
        if bound:
            call = append.bind_replay_player_dependency_append(self.context, self.calls).call
            assert call is not None and call(ENTRY, (H, source), None) is None
        else:
            assert (
                append.append_replay_player_dependency(self.context, H, source, calls=self.calls)
                is None
            )

    def children(self) -> list[tuple[int, ...]]:
        return [row[2] for row in self.events if row[:2] == ("c", RESERVE)]


@pytest.mark.parametrize("bound", [False, True])
@pytest.mark.parametrize("value", [0, 7, 0x80000000, 0xFFFFFFFF])
def test_fast_path_exact_order_and_unsigned_payload_without_quantum_backing(bound, value) -> None:
    f = Fixture()
    data = f.block(2, 0xC7)
    f.header(data, 2, 1, None)
    f.source(value, writable=False)
    f.run(bound=bound)
    assert f.events == [
        ("r", H + 8, 8, 2),
        ("r", H + 16, 8, 1),
        ("r", H + 16, 8, 1),
        ("r", H, 8, data),
        ("r", S, 4, value),
        ("w", data + 4, 4, value),
        ("r", H + 16, 8, 1),
        ("w", H + 16, 8, 2),
    ]
    assert f.memory.read(data, 4) == 0xC7C7C7C7


@pytest.mark.parametrize(
    "begin,capacity,count,source",
    [
        (0xBADC0DE, 2, 0, 0),
        (U64 - 3, 2, 1, 0xBAD),
        (0x8888, 0, U64, 0),
    ],
)
def test_null_source_or_wrapped_null_destination_skips_copy_but_increments(
    begin, capacity, count, source
) -> None:
    f = Fixture()
    f.header(begin, capacity, count, None)
    f.run(source)
    assert f.memory.read(H + 16, 8) == (count + 1) & U64
    assert [row[:3] for row in f.events] == [
        ("r", H + 8, 8),
        ("r", H + 16, 8),
        ("r", H + 16, 8),
        ("r", H, 8),
        ("r", H + 16, 8),
        ("w", H + 16, 8),
    ]


@pytest.mark.parametrize(
    "capacity,count,quantum,expected",
    [
        (0, 0, 0, 1),
        (0, 0, 32, 1),
        (3, 3, 1, 4),
        (3, 3, 0, 4),
        (3, 4, 2, 5),
        (4, 5, 3, 7),
        (4, 4, 32, 8),
        (8, 9, 4, 12),
        (0, 0, U64, 1),
    ],
)
def test_growth_rounding_constants_use_real_reserve_and_owned_allocation(
    capacity,
    count,
    quantum,
    expected,
) -> None:
    f = Fixture()
    # Deliberately count>capacity rows remain fully backed for the source copy.
    data = f.block(count) if count else 0
    f.header(data, capacity, count, quantum)
    f.source(0x89ABCDEF)
    f.run(bound=True)
    assert f.children() == [(H, expected)]
    assert f.memory.read(H + 8, 8) == expected and f.memory.read(H + 16, 8) == count + 1
    assert f.memory.read(f.memory.read(H, 8) + count * 4, 4) == 0x89ABCDEF
    assert ("i", ALLOC, (expected * 4,)) in f.events


def test_rounding_numerator_wrap_can_call_actual_zero_reserve_without_allocation() -> None:
    f = Fixture()
    f.header(0, 0, 1, U64)
    f.run(0)
    assert f.children() == [(H, 0)]
    assert f.memory.read(H + 16, 8) == 2 and f.memory.read(H, 8) == 0
    assert not [row for row in f.events if row[0] == "i"]


def test_doubling_nontermination_refuses_after_only_required_prefix_reads() -> None:
    f = Fixture()
    f.header(0, 1 << 63, 1 << 63, 1)
    before = f.memory.snapshot()
    with pytest.raises(UnresolvedReplayTaskRebuild, match="nonterminating"):
        f.run(0)
    assert f.memory.snapshot() == before
    assert [row[:3] for row in f.events] == [("r", H + 8, 8), ("r", H + 16, 8), ("r", H + 24, 8)]


def test_growth_missing_reserve_refuses_before_source_or_header_mutation() -> None:
    f = Fixture()
    f.header()
    f.have_reserve = False
    before = f.memory.snapshot()
    with pytest.raises(UnresolvedReplayTaskRebuild, match="140b55580"):
        f.run()
    assert f.memory.snapshot() == before and f.children() == [(H, 1)]
    assert not [row for row in f.events if row[:2] == ("r", S)]


def test_repeated_appends_use_real_copy_free_and_leave_unused_tail_undefined() -> None:
    f = Fixture()
    f.header()
    f.source()
    for value in range(40):
        f.memory.write(S, 4, value + 100)
        f.run(bound=True)
    begin = f.memory.read(H, 8)
    assert [f.memory.read(begin + index * 4, 4) for index in range(40)] == list(range(100, 140))
    assert f.memory.read(H + 8, 8) == 64 and f.memory.read(H + 16, 8) == 40
    assert f.memory.read(H + 24, 8) == 32
    assert [args[1] for args in f.children()] == [1, 2, 4, 8, 16, 32, 64]
    assert len([row for row in f.events if row[:2] == ("i", FREE)]) == 6
    with pytest.raises(ReplayMemoryError, match="undefined"):
        f.memory.read(begin + 40 * 4, 4)


def test_source_alias_to_capacity_is_read_after_real_growth_publishes_new_capacity() -> None:
    f = Fixture()
    data = f.block(1, 0x11)
    f.header(data, 1, 1)
    f.run(H + 8)
    grown = f.memory.read(H, 8)
    assert grown != data and f.memory.read(grown + 4, 4) == 2
    payload_read = [index for index, row in enumerate(f.events) if row == ("r", H + 8, 4, 2)]
    capacity_write = [index for index, row in enumerate(f.events) if row == ("w", H + 8, 8, 2)]
    assert len(payload_read) == len(capacity_write) == 1 and payload_read[0] > capacity_write[0]


def test_old_allocation_source_is_not_snapshotted_before_its_real_free() -> None:
    f = Fixture()
    data = f.block(1, 0x11)
    f.header(data, 1, 1)
    with pytest.raises(ReplayMemoryError):
        f.run(data)
    assert f.memory.read(H, 8) != data
    assert f.memory.read(H + 8, 8) == 2 and f.memory.read(H + 16, 8) == 1
    assert ("i", FREE, (data,)) in f.events


def test_after_actual_reserve_mutations_feed_current_count_data_and_source_reads() -> None:
    f = Fixture()
    f.header()
    f.source(7)
    redirected = f.block(3, 0x22)

    def mutate() -> None:
        f.memory.write(H, 8, redirected)
        f.memory.write(H + 16, 8, 1)
        f.memory.write(S, 4, 9)

    f.after_reserve = mutate
    f.run()
    assert f.memory.read(redirected, 4) == 0x22222222
    assert f.memory.read(redirected + 4, 4) == 9 and f.memory.read(H + 16, 8) == 2


@pytest.mark.parametrize("high,payload", [(0, 7), (5, 7), (5, 0xFFFFFFFF)])
def test_payload_alias_to_count_keeps_upper_word_then_current_INC_carries(high, payload) -> None:
    f = Fixture()
    used = high << 32
    begin = (H + 16 - used * 4) & U64
    f.header(begin, U64, used, None)
    f.source(payload)
    f.run()
    assert f.memory.read(H + 16, 8) == (((high << 32) | payload) + 1) & U64
    assert ("w", H + 16, 4, payload) in f.events


def test_payload_write_callback_can_change_current_count_before_increment() -> None:
    f = Fixture()
    data = f.block(1)
    f.header(data, 1, 0, None)
    f.source()
    f.on_write = lambda address, _width, _value: (
        f.memory.write(H + 16, 8, U64) if address == data else None
    )
    f.run()
    assert f.memory.read(data, 4) == 7 and f.memory.read(H + 16, 8) == 0


def test_initial_count_controls_capacity_but_later_count_controls_actual_destination() -> None:
    f = Fixture()
    data = f.block(5)
    f.header(data, 5, 1, None)
    f.source()
    count_reads = 0

    def mutate(address, _width, _value):
        nonlocal count_reads
        if address == H + 16:
            count_reads += 1
            if count_reads == 1:
                f.memory.write(H + 16, 8, 3)

    f.on_read = mutate
    f.run()
    assert f.memory.read(data + 12, 4) == 7 and f.memory.read(data + 4, 4) == 0
    assert f.memory.read(H + 16, 8) == 4 and not f.children()


def test_selected_data_pointer_is_held_after_its_current_read() -> None:
    f = Fixture()
    first, second = f.block(1), f.block(1)
    f.header(first, 1, 0, None)
    f.source()
    f.on_read = lambda address, _width, _value: (
        f.memory.write(H, 8, second) if address == H else None
    )
    f.run()
    assert f.memory.read(first, 4) == 7 and f.memory.read(second, 4) == 0
    assert f.memory.read(H, 8) == second


def test_capacity_sample_is_held_even_if_backing_changes_before_reserve() -> None:
    f = Fixture()
    f.header(f.block(1), 1, 1)
    f.source()
    sampled = False

    def mutate(address, width, _value):
        nonlocal sampled
        if address == H + 8 and width == 8 and not sampled:
            sampled = True
            f.memory.write(H + 8, 8, 100)

    f.on_read = mutate
    f.run()
    assert f.children() == [(H, 2)] and f.memory.read(H + 8, 8) == 2


@pytest.mark.parametrize("failure", ["source", "destination", "count"])
def test_owned_read_or_write_refusals_preserve_exact_prior_effects(failure) -> None:
    f = Fixture()
    data = f.block(1) if failure != "destination" else 0xBAD
    f.header(data, 1, 0, None, writable=failure != "count")
    if failure != "source":
        f.source()
    with pytest.raises(ReplayMemoryError):
        f.run()
    assert f.memory.read(H + 16, 8) == 0
    if failure == "count":
        assert f.memory.read(data, 4) == 7
    assert not f.children()


@pytest.mark.parametrize("target", [ALLOC, FREE])
def test_reached_real_import_failure_retains_prior_allocation_and_header_effects(target) -> None:
    f = Fixture()
    old = f.block(1)
    f.header(old, 1, 1)
    f.source()

    def fail(selected, _args):
        if selected == target:
            raise RuntimeError("explicit import failure")

    f.before_import = fail
    before = len(f.memory.snapshot().regions)
    with pytest.raises(RuntimeError, match="explicit import failure"):
        f.run()
    assert f.memory.read(H, 8) == old
    assert f.memory.read(H + 8, 8) == 1 and f.memory.read(H + 16, 8) == 1
    assert len(f.memory.snapshot().regions) == before + (target == FREE)


@pytest.mark.parametrize(
    "args,data",
    [
        ((H,), None),
        ((H, S, 3), None),
        ((H, S), memoryview(bytearray(1))),
        ((H, -1), None),
        ((H, 1 << 64), None),
        ((H, True), None),
    ],
)
def test_bound_arity_data_and_raw_word_admission_reject_before_access(args, data) -> None:
    f = Fixture()
    call = append.bind_replay_player_dependency_append(f.context, f.calls).call
    assert call is not None
    with pytest.raises(ValueError):
        call(ENTRY, args, data)
    assert f.events == []


def test_unknown_bound_target_delegates_data_identity_and_raw_return() -> None:
    f = Fixture()
    seen, payload = [], memoryview(bytearray(b"abc"))

    def lower(target, args, data):
        seen.append((target, args, data))
        return U64

    call = append.bind_replay_player_dependency_append(
        f.context, ReplayTaskRebuildCalls(lower)
    ).call
    assert call is not None and call(9, (4, 5), payload) == U64
    assert seen == [(9, (4, 5), payload)] and f.events == []


def test_unknown_bound_target_has_no_default_success_without_dispatcher() -> None:
    f = Fixture()
    call = append.bind_replay_player_dependency_append(f.context, ReplayTaskRebuildCalls(None)).call
    assert call is not None
    with pytest.raises(UnresolvedReplayTaskRebuild, match="1234"):
        call(0x1234, (), None)
    assert f.events == []
