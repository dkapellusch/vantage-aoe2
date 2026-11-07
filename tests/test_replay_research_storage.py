"""Source-led caller controls; opaque effects never claim original child success."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager

import pytest

from vantage import replay_research_storage as research
from vantage.replay_memory import ReplayMemory, ReplayMemoryError
from vantage.replay_player_civilization_lookup import bind_replay_player_civilization_lookup
from vantage.replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
)
from vantage.replay_unit_constructor_support import bind_replay_unit_constructor_support
from vantage.replay_zone_queue import bind_replay_zone_queue

U64 = (1 << 64) - 1
H = 0x1000
CLEAR, REVERSE, ROWS, WORDS, RESERVE = (
    0x141491C50,
    0x141492AE0,
    0x1414929F0,
    0x140B55580,
    0x1414938A0,
)
ALLOC, FREE, MOVE, FILL = 0x142D6BA78, 0x142D6BAB4, 0x142D6E3DB, 0x142D6E3B7
MALLOC_SLOT, FREE_SLOT = 0x143199DB0, 0x143199DD0
VECTOR, TRANSFER, RANGE = 0x141493B50, 0x1414904C0, 0x141493840


class Fixture:
    """Actual owned backing plus explicit mutation fixtures for opaque call boundaries."""

    def __init__(self) -> None:
        self.memory = ReplayMemory(max_bytes=1 << 20)
        self.events: list[tuple[object, ...]] = []
        self.effects: dict[int, Callable[[tuple[int, ...]], int | None]] = {}
        self.import_effects: dict[int, Callable[[tuple[int, ...]], int | None]] = {}
        self.on_read: Callable[[int, int, int], None] | None = None
        self.on_write: Callable[[int, int, int], None] | None = None
        self.before_import: Callable[[int, tuple[int, ...]], None] | None = None
        self.after_import: Callable[[int, tuple[int, ...], int | None], None] | None = None
        self.locals: list[int] = []
        self.context = ReplayTaskRebuildStorage(H, self.read, self.write)
        self.terminal = ReplayTaskRebuildCalls(self.import_call)
        for slot, target in (
            (MALLOC_SLOT, ALLOC),
            (FREE_SLOT, FREE),
            (0x143199930, MOVE),
            (0x143199938, FILL),
        ):
            self.memory.map_bytes(slot, target.to_bytes(8, "little"))

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

    def ordinary(self, target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        self.events.append(("c", target, args, data))
        if target not in self.effects:
            raise UnresolvedReplayTaskRebuild(f"fixture has no original body{target:x}")
        return self.effects[target](args)

    def import_call(
        self,
        target: int,
        args: tuple[int, ...],
        data: memoryview | None,
    ) -> int | None:
        self.events.append(("i", target, args, data))
        if self.before_import is not None:
            self.before_import(target, args)
        if target in self.import_effects:
            result = self.import_effects[target](args)
        else:
            call = self.memory.runtime_calls().call
            assert call is not None
            result = call(target, args, data)
        if self.after_import is not None:
            self.after_import(target, args, result)
        return result

    @contextmanager
    def bind_local(self, view: memoryview) -> Iterator[int]:
        with self.memory.bind_local(view) as address:
            self.locals.append(address)
            yield address

    def bound(self, *, real_children: bool = True) -> ReplayTaskRebuildCalls:
        lower = ReplayTaskRebuildCalls(self.ordinary)
        if real_children:
            lower = bind_replay_zone_queue(self.context, lower, imports=self.terminal)
            lower = bind_replay_unit_constructor_support(
                self.context, lower, imports=self.terminal, bind_local=self.bind_local
            )
            lower = bind_replay_player_civilization_lookup(
                self.context, lower, bind_local=self.bind_local, scratch=b"\xa5" * 8
            )
        return research.bind_replay_research_storage(
            self.context,
            lower,
            imports=self.terminal,
            bind_local=self.bind_local,
            scratch=research.ReplayResearchStorageScratch(b"\xa5" * 8),
        )

    def invoke(self, entry: int, *args: int, real_children: bool = True) -> None:
        call = self.bound(real_children=real_children).call
        assert call is not None
        assert call(entry, args, None) is None

    def header(self, begin: int = 0, capacity: int = 0, count: int = 0, quantum: int = 77) -> None:
        self.memory.map_bytes(
            H, b"".join(v.to_bytes(8, "little") for v in (begin, capacity, count, quantum))
        )

    def block(self, size: int, fill: int = 0) -> int:
        address = self.memory.allocate(size)
        self.memory.fill(address, fill, size)
        return address

    def fields(self) -> tuple[int, ...]:
        return tuple(self.memory.read(H + offset, 8) for offset in (0, 8, 16, 24))

    def imports(self) -> list[tuple[int, tuple[int, ...]]]:
        return [(row[1], row[2]) for row in self.events if row[0] == "i"]


def assert_source_row(memory: ReplayMemory, row: int, padding: int | None) -> None:
    """Independent source ranges, including the seven bytes the initializer never writes."""
    assert memory.read_bytes(row, 15) == bytes(15)
    for offset in (0x10, 0x28, 0x40):
        assert memory.read(row + offset, 8) == 0x14428BB30
        assert memory.read_bytes(row + offset + 8, 16) == bytes(16)
    assert memory.read(row + 0x58, 1) == 0
    assert memory.read_bytes(row + 0x5A, 24) == bytes(24)
    assert memory.read_bytes(row + 0x74, 5) == bytes(5)
    assert memory.read(row + 0x7A, 4) == 0xFFFFFFFF
    assert memory.read_bytes(row + 0x80, 24) == bytes(24)
    for offset in (0xF, 0x59, 0x72, 0x73, 0x79, 0x7E, 0x7F):
        if padding is None:
            with pytest.raises(ReplayMemoryError, match="undefined"):
                memory.read(row + offset, 1)
        else:
            assert memory.read(row + offset, 1) == padding


def test_clear_zero_count_does_not_access_begin_or_reset_late_mutation() -> None:
    f = Fixture()
    f.memory.map_bytes(H + 16, bytes(8))
    f.on_read = lambda a, _w, _v: f.memory.write(H + 16, 8, 7) if a == H + 16 else None
    f.invoke(CLEAR, H)
    assert f.events == [("r", H + 16, 8, 0)]
    assert f.memory.read(H + 16, 8) == 7


def test_clear_nonzero_count_null_begin_only_resets_count() -> None:
    f = Fixture()
    f.header(0, 99, 3)
    f.invoke(CLEAR, H)
    assert f.events == [("r", H + 16, 8, 3), ("r", H, 8, 0), ("w", H + 16, 8, 0)]
    assert f.fields() == (0, 99, 0, 77)


def test_clear_opaque_vector_effects_do_not_replace_held_walk_and_real_strings() -> None:
    f = Fixture()
    rows, redirected = f.block(0x130), f.block(0x130, 0xC7)
    f.header(rows, 2, 2)
    marker = f.block(8)

    def vector(args: tuple[int, ...]) -> None:
        f.memory.write(marker, 8, f.memory.read(marker, 8) + 1)
        f.memory.write(H, 8, redirected)
        f.memory.write(H + 16, 8, 99)

    f.effects[VECTOR] = vector
    f.invoke(CLEAR, H)
    assert [row[2] for row in f.events if row[:2] == ("c", VECTOR)] == [
        (rows + 0x80,),
        (rows + 0x118,),
    ]
    string_reads = [
        row[1]
        for row in f.events
        if row[0] == "r"
        and row[1] in {rows + 0x40, rows + 0x28, rows + 0x10, rows + 0xD8, rows + 0xC0, rows + 0xA8}
    ]
    assert string_reads == [
        rows + 0x40,
        rows + 0x28,
        rows + 0x10,
        rows + 0xD8,
        rows + 0xC0,
        rows + 0xA8,
    ]
    assert f.memory.read(marker, 8) == 2 and f.fields() == (redirected, 2, 0, 77)


@pytest.mark.parametrize("entry,args", [(CLEAR, (H,)), (RESERVE, (H, 0))])
def test_nonempty_cleanup_never_infers_empty_vector_destructor_success(entry, args) -> None:
    f = Fixture()
    rows = f.block(0x98)
    f.header(rows, 1, 1)
    before = f.memory.snapshot()
    with pytest.raises(UnresolvedReplayTaskRebuild, match="141493b50"):
        f.invoke(entry, *args)
    assert f.memory.snapshot() == before
    assert [row[2] for row in f.events if row[:2] == ("c", VECTOR)] == [(rows + 0x80,)]


def test_reset_rows_zero_still_calls_real_clear_before_the_count_test() -> None:
    f = Fixture()
    f.header(0, 5, 4)
    f.invoke(ROWS, H, 0)
    assert f.events == [("r", H + 16, 8, 4), ("r", H, 8, 0), ("w", H + 16, 8, 0)]


def test_reset_rows_refuses_unprovided_clear_before_even_zero_count_or_header_reads() -> None:
    f = Fixture()
    with pytest.raises(UnresolvedReplayTaskRebuild, match="141491c50"):
        research.reset_replay_research_rows(
            f.context, H, 0, calls=ReplayTaskRebuildCalls(f.ordinary)
        )
    assert f.events == [("c", CLEAR, (H,), None)]


@pytest.mark.parametrize("count", [1, 3])
def test_fresh_owned_rows_compose_clear_and_reserve_without_opaque_children(count: int) -> None:
    f = Fixture()
    f.header()
    f.invoke(ROWS, H, count)
    begin, capacity, used, quantum = f.fields()
    assert capacity == used == count and quantum == 77
    for index in range(count):
        assert_source_row(f.memory, begin + index * 0x98, None)
    assert f.imports() == [(ALLOC, (count * 0x98,))]
    assert not any(row[0] == "c" for row in f.events)
    assert f.effects == {}  # No successful placeholder for row transfer or destruction.


def test_rows_reuse_poisoned_backing_preserves_padding_and_holds_loop_base() -> None:
    f = Fixture()
    rows, redirected = f.block(0x130, 0xA5), f.block(0x130, 0xC7)
    f.header(rows, 2, 0)
    f.on_write = lambda a, _w, _v: f.memory.write(H, 8, redirected) if a == rows else None
    f.invoke(ROWS, H, 2)
    assert_source_row(f.memory, rows, 0xA5)
    assert_source_row(f.memory, rows + 0x98, 0xA5)
    assert f.memory.read_bytes(redirected, 0x130) == bytes([0xC7]) * 0x130
    assert f.fields() == (redirected, 2, 2, 77) and f.imports() == []


def test_rows_sample_current_capacity_and_begin_after_real_clear_effect() -> None:
    f = Fixture()
    rows = f.block(0x130, 0xA5)
    f.header(0, 0, 1)

    def after_clear(address: int, _width: int, value: int) -> None:
        if address == H + 16 and value == 0:
            f.memory.write(H, 8, rows)
            f.memory.write(H + 8, 8, 2)

    f.on_write = after_clear
    f.invoke(ROWS, H, 2)
    assert f.imports() == []
    assert_source_row(f.memory, rows + 0x98, 0xA5)


@pytest.mark.parametrize("count", [0, 1, 4])
def test_fresh_reverse_array_uses_real_allocator_and_exact32byte_headers(count: int) -> None:
    f = Fixture()
    f.header()
    f.invoke(REVERSE, H, count)
    begin, capacity, used, quantum = f.fields()
    assert used == count and quantum == 77
    if count:
        assert capacity == count
        expected = bytes(24) + (32).to_bytes(8, "little")
        assert f.memory.read_bytes(begin, count * 32) == expected * count
        assert f.imports() == [(ALLOC, (count * 32,))]
    else:
        assert (begin, capacity) == (0, 0) and f.imports() == []
    assert not any(row[0] == "c" for row in f.events)


def test_reverse_clear_real_free_is_capacity_gated_and_leaves_stale_fields() -> None:
    f = Fixture()
    rows, first, retained = f.block(96), f.block(8), f.block(8)
    f.header(rows, 3, 3)
    for index, pointer, cap in ((0, first, 1), (1, retained, 0), (2, 0, 99)):
        f.memory.write(rows + index * 32, 8, pointer)
        f.memory.write(rows + index * 32 + 8, 8, cap)
        f.memory.write(rows + index * 32 + 16, 8, 13)
    f.invoke(REVERSE, H, 0)
    assert f.imports() == [(FREE, (first,))]
    for index in range(3):
        assert f.memory.read(rows + index * 32, 8) == 0
        assert f.memory.read(rows + index * 32 + 16, 8) == 13
    assert f.fields() == (rows, 3, 0, 77)
    with pytest.raises(ReplayMemoryError, match="unmapped"):
        f.memory.read(first, 1)
    assert f.memory.read(retained, 1) == 0
    assert not any(row[:3] == ("r", rows + 72, 8) for row in f.events)


def test_reverse_reuses_capacity_and_reinitializes_only_requested_rows() -> None:
    f = Fixture()
    rows = f.block(96, 0xA5)
    f.header(rows, 3, 0)
    f.invoke(REVERSE, H, 2)
    assert f.memory.read_bytes(rows, 64) == (bytes(24) + (32).to_bytes(8, "little")) * 2
    assert f.memory.read_bytes(rows + 64, 32) == bytes([0xA5]) * 32
    assert f.fields() == (rows, 3, 2, 77) and f.imports() == []


def test_reverse_controlled_allocator_mutation_uses_real_memcpy_then_memset() -> None:
    f = Fixture()
    old = f.block(64, 0xA5)
    f.header(old, 2, 0)

    def after(target: int, _args: tuple[int, ...], _result: int | None) -> None:
        if target == ALLOC:
            f.memory.write(H + 16, 8, 1)  # Explicit allocator-side mutation fixture.

    def before(target: int, args: tuple[int, ...]) -> None:
        if target == FREE:
            assert args == (old,) and f.memory.read_bytes(old, 32) == bytes(32)

    f.after_import, f.before_import = after, before
    f.invoke(REVERSE, H, 3)
    allocation = f.memory.read(H, 8)
    assert f.imports() == [
        (ALLOC, (96,)),
        (MOVE, (allocation, old, 32)),
        (FILL, (old, 0, 32)),
        (FREE, (old,)),
    ]
    for slot in (0x143199930, 0x143199938):
        assert sum(row[:3] == ("r", slot, 8) for row in f.events) == 1
    assert f.memory.read_bytes(allocation, 96) == (bytes(24) + (32).to_bytes(8, "little")) * 3


def test_reverse_excess_walk_holds_cursor_then_reloads_outer_free_pointer() -> None:
    f = Fixture()
    old, selected, freed_outer = f.block(128), f.block(128), f.block(8)
    first, second = f.block(8), f.block(8)
    f.header(old, 1, 0)
    for offset, pointer in ((64, first), (96, second)):
        f.memory.write(selected + offset, 8, pointer)
        f.memory.write(selected + offset + 8, 8, 1)

    def after(target: int, args: tuple[int, ...], _result: int | None) -> None:
        if target == ALLOC:
            f.memory.write(H + 16, 8, 4)
        elif target == FILL:
            f.memory.write(H, 8, selected)
        elif target == FREE and args == (first,):
            f.memory.write(H, 8, freed_outer)

    f.after_import = after
    f.invoke(REVERSE, H, 2)
    assert [args for target, args in f.imports() if target == FREE] == [
        (first,),
        (second,),
        (freed_outer,),
    ]
    assert f.fields()[1:] == (2, 2, 77)
    assert f.memory.read(selected + 64, 8) == f.memory.read(selected + 96, 8) == 0


def test_reverse_publication_uses_current_begin_after_capacity_store() -> None:
    f = Fixture()
    selected = f.block(32, 0xA5)
    f.header()
    f.on_write = lambda a, _w, _v: f.memory.write(H, 8, selected) if a == H + 8 else None
    f.invoke(REVERSE, H, 1)
    assert f.fields() == (selected, 1, 1, 77)
    assert f.memory.read_bytes(selected, 32) == bytes(24) + (32).to_bytes(8, "little")


@pytest.mark.parametrize("capacity", [1, 3])
def test_owned_word_resize_has_real_copy_free_and_undefined_new_tail(capacity: int) -> None:
    f = Fixture()
    old = f.block(8)
    f.memory.write_bytes(old, b"ABCDEFGH")
    f.header(old, 2, 2)
    f.invoke(WORDS, H, capacity)
    allocation = f.memory.read(H, 8)
    assert f.fields() == (allocation, capacity, min(capacity, 2), 77)
    assert f.memory.read_bytes(allocation, min(capacity, 2) * 4) == b"ABCDEFGH"[: capacity * 4]
    if capacity > 2:
        with pytest.raises(ReplayMemoryError, match="undefined"):
            f.memory.read(allocation + 8, 1)
    assert f.imports() == [
        (ALLOC, (capacity * 4,)),
        (MOVE, (allocation, old, min(capacity, 2) * 4)),
        (FREE, (old,)),
    ]


@pytest.mark.parametrize("entry", [WORDS, RESERVE])
def test_capacity_equality_only_reads_capacity_without_local_binding(entry: int) -> None:
    f = Fixture()
    f.memory.map_bytes(H + 8, (9).to_bytes(8, "little"))
    f.invoke(entry, H, 9)
    assert f.events == [("r", H + 8, 8, 9)] and f.locals == []


def test_word_zero_capacity_uses_initial_capacity_and_free_before_three_stores() -> None:
    f = Fixture()
    old = f.block(4)
    f.header(old, 1, 11)
    f.on_read = lambda a, _w, _v: f.memory.write(H + 8, 8, 0) if a == H + 8 else None
    f.invoke(WORDS, H, 0)
    assert f.imports() == [(FREE, (old,))]
    assert [row for row in f.events if row[0] == "w"] == [
        ("w", H, 8, 0),
        ("w", H + 16, 8, 0),
        ("w", H + 8, 8, 0),
    ]


@pytest.mark.parametrize("entry", [WORDS, RESERVE])
def test_positive_capacity_null_old_begin_skips_undefined_count(entry: int) -> None:
    f = Fixture()
    f.memory.map_bytes(H, bytes(16))
    f.invoke(entry, H, 2)
    assert f.memory.read(H + 8, 8) == 2
    with pytest.raises(ReplayMemoryError, match="unmapped"):
        f.memory.read(H + 16, 8)
    assert not any(row[:3] == ("r", H + 16, 8) for row in f.events)


def test_word_copy_mutation_uses_held_count_and_current_free_pointer() -> None:
    f = Fixture()
    old, late = f.block(20, 0xA5), f.block(4)
    f.header(old, 5, 5)

    def after(target: int, _args: tuple[int, ...], _result: int | None) -> None:
        if target == MOVE:
            f.memory.write(H, 8, late)
            f.memory.write(H + 16, 8, 99)
            f.memory.write(H + 8, 8, 1)

    f.after_import = after
    f.invoke(WORDS, H, 3)
    assert f.fields()[1:] == (3, 3, 77)
    assert f.imports()[-1] == (FREE, (late,))
    assert f.memory.read(old, 1) == 0xA5


def test_word_copy_reloads_source_after_first_nonnull_begin_test() -> None:
    f = Fixture()
    initial, selected = f.block(8, 0xA5), f.block(8, 0xC7)
    f.header(initial, 2, 2)
    touched = False

    def read(address: int, _width: int, _value: int) -> None:
        nonlocal touched
        if address == H and not touched:
            touched = True
            f.memory.write(H, 8, selected)

    f.on_read = read
    f.invoke(WORDS, H, 3)
    assert f.memory.read_bytes(f.memory.read(H, 8), 8) == bytes([0xC7]) * 8
    assert f.imports()[-1] == (FREE, (selected,))
    assert f.memory.read(initial, 1) == 0xA5


def test_reserve_zero_null_begin_resets_after_count_before_pointer_read() -> None:
    f = Fixture()
    f.header(0, 2, 7)
    f.invoke(RESERVE, H, 0)
    assert f.events[:3] == [("r", H + 8, 8, 2), ("r", H + 16, 8, 7), ("r", H, 8, 0)]
    assert f.fields() == (0, 0, 0, 77) and f.imports() == []


def test_reserve_zero_opaque_vector_mutation_does_not_replace_held_free_pointer() -> None:
    f = Fixture()
    old, redirected, marker = f.block(0x98), f.block(4), f.block(8)
    f.header(old, 2, 1)

    def vector(_args: tuple[int, ...]) -> None:
        f.memory.write(marker, 8, 1)
        f.memory.write(H, 8, redirected)
        f.memory.write(H + 8, 8, 0)

    f.effects[VECTOR] = vector
    f.invoke(RESERVE, H, 0)
    assert f.memory.read(marker, 8) == 1
    assert f.imports() == [(FREE, (old,))] and f.fields() == (0, 0, 0, 77)
    assert f.memory.read(redirected, 1) == 0


def test_reserve_positive_requires_real_transfer_and_keeps_prior_allocation() -> None:
    f = Fixture()
    old = f.block(0x98)
    f.header(old, 1, 1)
    previous_bytes = f.memory.mapped_bytes
    with pytest.raises(UnresolvedReplayTaskRebuild, match="1414904c0"):
        f.invoke(RESERVE, H, 2)
    assert f.fields() == (old, 1, 1, 77)
    assert f.memory.mapped_bytes == previous_bytes + 0x130
    assert [row[1] for row in f.events if row[0] == "c"] == [TRANSFER]


def test_reserve_opaque_effects_preserve_held_rows_then_current_range_and_local() -> None:
    f = Fixture()
    old, selected, freed, marker = f.block(0x130), f.block(0x400), f.block(8), f.block(8)
    f.header(old, 2, 2)

    def transfer(args: tuple[int, ...]) -> None:
        f.memory.write(args[0], 4, 0x12345678)  # Explicit partial opaque effect, not real row copy.
        f.memory.write(H, 8, selected)
        f.memory.write(H + 16, 8, 5)

    def vector(_args: tuple[int, ...]) -> None:
        f.memory.write(marker, 8, f.memory.read(marker, 8) + 1)
        f.memory.write(f.locals[-1], 8, 0x20)

    def excess(args: tuple[int, ...]) -> None:
        assert args == (H, selected + 0x20, 2)
        f.memory.write(H, 8, freed)
        f.memory.write(H + 16, 8, 99)

    f.effects.update({TRANSFER: transfer, VECTOR: vector, RANGE: excess})
    f.invoke(RESERVE, H, 3)
    ordinary = [row for row in f.events if row[0] == "c"]
    assert [row[1] for row in ordinary] == [TRANSFER, TRANSFER, VECTOR, VECTOR, RANGE]
    allocation = f.memory.read(H, 8)
    assert ordinary[0][2] == (allocation, old)
    assert ordinary[1][2] == (allocation + 0x98, old + 0x98)
    assert ordinary[2][2] == (old + 0x80,) and ordinary[3][2] == (old + 0x118,)
    assert f.memory.read(marker, 8) == 2 and f.fields()[1:] == (3, 3, 77)
    assert f.imports()[-1] == (FREE, (freed,))


def test_reserve_null_allocation_keeps_held_size_and_base_for_range() -> None:
    f = Fixture()
    old, late, marker = f.block(0x1C8), f.block(8), f.block(8)
    f.header(old, 3, 3)
    f.import_effects[ALLOC] = lambda _args: 0  # Explicit source null-return control.

    def after(target: int, _args: tuple[int, ...], _result: int | None) -> None:
        if target == ALLOC:
            f.memory.write(f.locals[-1], 8, 1)

    def read(address: int, _width: int, _value: int) -> None:
        if address == H + 16:
            f.memory.write(H, 8, late)

    def excess(args: tuple[int, ...]) -> None:
        assert args == (H, old + 0x130, 1)
        f.memory.write(marker, 8, 1)

    f.after_import, f.on_read, f.effects[RANGE] = after, read, excess
    f.invoke(RESERVE, H, 2)
    assert f.memory.read(marker, 8) == 1 and f.fields() == (0, 2, 2, 77)
    assert not any(row[:2] in (("c", TRANSFER), ("c", VECTOR)) for row in f.events)
    assert f.imports()[-1] == (FREE, (late,))


@pytest.mark.parametrize(
    ("entry", "capacity", "size"),
    [
        (WORDS, (1 << 62) + 1, 4),
        (RESERVE, (1 << 61) + 1, 0x98),
    ],
)
def test_capacity_byte_products_wrap_without_invented_overflow_leaf(entry, capacity, size) -> None:
    f = Fixture()
    f.header()
    f.invoke(entry, H, capacity)
    assert f.imports() == [(ALLOC, (size,))]
    assert f.fields()[1:] == (capacity, 0, 77)


def test_reverse_wrapped_product_with_explicit_null_return_publishes_count_not_backing() -> None:
    f = Fixture()
    f.header()
    count = (1 << 59) + 1
    f.import_effects[ALLOC] = lambda _args: 0
    f.invoke(REVERSE, H, count)
    assert f.imports() == [(ALLOC, (32,))] and f.fields() == (0, count, count, 77)


@pytest.mark.parametrize("entry", [WORDS, REVERSE, RESERVE])
def test_none_allocator_result_is_unavailable_not_an_invented_null(entry: int) -> None:
    f = Fixture()
    f.header()
    f.import_effects[ALLOC] = lambda _args: None
    with pytest.raises(ValueError, match="raw scalar result"):
        f.invoke(entry, H, 1)
    assert f.fields() == (0, 0, 0, 77)


@pytest.mark.parametrize("entry", [WORDS, REVERSE, RESERVE])
def test_selected_import_token_equal_to_owned_entry_never_reenters_ordinary_dispatch(entry) -> None:
    f = Fixture()
    f.header()
    f.memory.write(MALLOC_SLOT, 8, CLEAR)
    f.import_effects[CLEAR] = lambda args: f.memory.allocate(args[0])
    f.invoke(entry, H, 1)
    assert f.imports()[0][0] == CLEAR
    assert not any(row[0] == "c" for row in f.events)
    assert sum(row[:3] == ("r", MALLOC_SLOT, 8) for row in f.events) == 1


def test_free_selected_token_equal_to_clear_is_one_terminal_call() -> None:
    f = Fixture()
    old = f.block(4)
    f.header(old, 1, 0)
    f.memory.write(FREE_SLOT, 8, CLEAR)
    f.import_effects[CLEAR] = lambda args: f.memory.free(args[0])
    f.invoke(WORDS, H, 0)
    assert f.imports() == [(CLEAR, (old,))] and f.fields() == (0, 0, 0, 77)
    assert sum(row[:3] == ("r", FREE_SLOT, 8) for row in f.events) == 1


def test_failed_later_allocation_preserves_real_earlier_dependency_free_and_resets() -> None:
    f = Fixture()
    rows, inner = f.block(32), f.block(4)
    f.header(rows, 1, 1)
    f.memory.write(rows, 8, inner)
    f.memory.write(rows + 8, 8, 1)
    f.memory.write(MALLOC_SLOT, 8, 0x9999)
    with pytest.raises(UnresolvedReplayTaskRebuild, match="9999"):
        f.invoke(REVERSE, H, 2)
    assert f.fields() == (rows, 1, 0, 77) and f.memory.read(rows, 8) == 0
    with pytest.raises(ReplayMemoryError, match="unmapped"):
        f.memory.read(inner, 1)


@pytest.mark.parametrize(
    ("entry", "args"),
    [
        (CLEAR, (H, 1)),
        (REVERSE, ()),
        (ROWS, (H,)),
        (WORDS, (H, 1, 2)),
        (RESERVE, (H,)),
    ],
)
def test_owned_entries_reject_wrong_arity_before_any_source_access(entry, args) -> None:
    f = Fixture()
    call = f.bound().call
    assert call is not None
    with pytest.raises(ValueError, match="malformed"):
        call(entry, args, None)
    assert f.events == []


@pytest.mark.parametrize("invalid", [True, -1, 1 << 64])
def test_owned_entry_requires_raw_u64_arguments_without_effects(invalid: int) -> None:
    f = Fixture()
    call = f.bound().call
    assert call is not None
    with pytest.raises(ValueError, match="argument"):
        call(ROWS, (H, invalid), None)
    assert f.events == []


@pytest.mark.parametrize("seed", [b"", bytes(7), bytes(9), bytearray(8)])
def test_reserve_local_requires_explicit_exact_eight_byte_seed(seed) -> None:
    with pytest.raises(ValueError, match="explicit8B"):
        research.ReplayResearchStorageScratch(seed)


def test_bound_payload_rejection_and_unknown_delegate_identity() -> None:
    f = Fixture()
    call = f.bound(real_children=False).call
    assert call is not None
    payload = memoryview(bytearray(b"opaque"))
    with pytest.raises(ValueError, match="malformed"):
        call(CLEAR, (H,), payload)
    f.effects[0xABCD] = lambda args: len(args)
    assert call(0xABCD, (1, 2), payload) == 2
    assert f.events == [("c", 0xABCD, (1, 2), payload)] and f.events[0][3] is payload


def test_direct_clear_storage_failures_do_not_invent_header_defaults() -> None:
    f = Fixture()
    with pytest.raises(ReplayMemoryError, match="unmapped"):
        research.clear_replay_research_rows(f.context, H, calls=ReplayTaskRebuildCalls(None))
    undefined = f.memory.allocate(32)
    with pytest.raises(ReplayMemoryError, match="undefined"):
        research.clear_replay_research_rows(
            f.context, undefined, calls=ReplayTaskRebuildCalls(None)
        )


def test_real_string_free_failure_preserves_prior_opaque_effect_and_old_count() -> None:
    f = Fixture()
    rows, text, marker = f.block(0x98), f.block(8), f.block(8)
    f.header(rows, 1, 1)
    f.memory.write(rows + 0x40, 8, text)
    f.memory.write(rows + 0x50, 8, 1)
    f.effects[VECTOR] = lambda _args: f.memory.write(marker, 8, 0xA5)

    def fail(target: int, args: tuple[int, ...]) -> None:
        if target == FREE:
            assert args == (text,)
            raise RuntimeError("declared terminal free failure")

    f.before_import = fail
    with pytest.raises(RuntimeError, match="terminal free failure"):
        f.invoke(CLEAR, H)
    assert f.memory.read(marker, 8) == 0xA5
    assert f.fields() == (rows, 1, 1, 77)
    assert f.memory.read(rows + 0x40, 8) == text
    assert not any(row[:3] == ("r", rows + 0x28, 8) for row in f.events)


def test_row_initializer_partial_backing_keeps_prior_three_stores_without_final_count() -> None:
    f = Fixture()
    row = f.block(15, 0xA5)
    f.header(row, 1, 0)
    with pytest.raises(ReplayMemoryError, match="unmapped"):
        f.invoke(ROWS, H, 1)
    assert f.memory.read_bytes(row, 15) == bytes(14) + b"\xa5"
    assert f.fields() == (row, 1, 0, 77)
    assert [event for event in f.events if event[0] == "w"] == [
        ("w", row, 4, 0),
        ("w", row + 4, 2, 0),
        ("w", row + 6, 8, 0),
    ]
    assert f.imports() == []
