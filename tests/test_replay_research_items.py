"""Source-derived owned effects and explicitly opaque mutation/failure controls."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager

import pytest

from vantage import replay_research_items as items
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

U64 = (1 << 64) - 1
H, INPUT = 0x1000, 0x2000
APPEND, COMMIT, CLEAR = 0x14148CDD0, 0x141493AA0, 0x141493B50
ALLOC, MOVE, FREE = 0x1402A94D0, 0x142D6E3DB, 0x142D6BAB4
WATSON_SLOT, WATSON = 0x14319A060, 0xE0000001


class Fixture:
    """Owned bytes; any substituted effect is named as an opaque phase fixture."""

    def __init__(self) -> None:
        self.memory = ReplayMemory(max_bytes=1 << 20)
        self.events: list[tuple[object, ...]] = []
        self.before: Callable[[int, tuple[int, ...]], None] | None = None
        self.after: Callable[[int, tuple[int, ...], int | None], None] | None = None
        self.on_read: Callable[[int, int, int], None] | None = None
        self.on_write: Callable[[int, int, int], None] | None = None
        self.effects: dict[int, Callable[[tuple[int, ...]], int | None]] = {}
        self.local: int | None = None
        self.context = ReplayTaskRebuildStorage(H, self.read, self.write)
        self.memory.map_bytes(INPUT, bytes.fromhex("2211443385000000efcdab899899c0ff"))

    def read(self, address: int, width: int) -> int:
        value = self.memory.read(address, width)
        self.events.append(("r", address, width, value))
        if self.on_read:
            self.on_read(address, width, value)
        return value

    def write(self, address: int, width: int, value: int) -> None:
        self.memory.write(address, width, value)
        self.events.append(("w", address, width, value))
        if self.on_write:
            self.on_write(address, width, value)

    @contextmanager
    def bind_local(self, view: memoryview) -> Iterator[int]:
        with self.memory.bind_local(view) as address:
            self.local = address
            try:
                yield address
            finally:
                self.local = None

    def lower(self, target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        self.events.append(("c", target, args))
        if self.before:
            self.before(target, args)
        if target in self.effects:
            result = self.effects[target](args)
        else:
            provider = self.memory.runtime_calls().call
            assert provider is not None
            result = provider(target, args, data)
        if self.after:
            self.after(target, args, result)
        return result

    def bound(self) -> ReplayTaskRebuildCalls:
        return items.bind_replay_research_items(
            self.context,
            ReplayTaskRebuildCalls(self.lower),
            imports=ReplayTaskRebuildCalls(self.lower),
            bind_local=self.bind_local,
            scratch=items.ReplayResearchItemsScratch(b"\xa5" * 0x90),
        )

    def invoke(self, target: int, *args: int) -> int | None:
        call = self.bound().call
        assert call is not None
        return call(target, args, None)

    def append(self) -> int:
        result = self.invoke(APPEND, H, INPUT, INPUT + 2, INPUT + 4, INPUT + 8, INPUT + 12)
        assert type(result) is int
        return result

    def header(self, begin: int = 0, count: int = 0, capacity: int = 0) -> None:
        self.memory.map_bytes(
            H,
            b"".join(
                value.to_bytes(8, "little")
                for value in (begin, (begin + 16 * count) & U64, (begin + 16 * capacity) & U64)
            ),
        )

    def block(self, count: int, fill: int = 0xA5) -> int:
        begin = self.memory.allocate_aligned(count * 16)
        self.memory.fill(begin, fill, count * 16)
        return begin

    def fields(self) -> tuple[int, ...]:
        return tuple(self.memory.read(H + offset, 8) for offset in (0, 8, 16))

    def calls(self) -> list[tuple[int, tuple[int, ...]]]:
        return [(row[1], row[2]) for row in self.events if row[0] == "c"]


def assert_item(memory: ReplayMemory, address: int, padding: bytes | None) -> None:
    assert memory.read(address, 2) == 0x1122
    assert memory.read(address + 2, 2) == 0x3344
    assert memory.read(address + 4, 1) == 0x85
    assert memory.read(address + 8, 4) == 0x89ABCDEF
    assert memory.read(address + 12, 4) == 0xFFC09998
    if padding is None:
        with pytest.raises(ReplayMemoryError, match="undefined"):
            memory.read_bytes(address + 5, 3)
    else:
        assert memory.read_bytes(address + 5, 3) == padding


@pytest.mark.parametrize("count,capacity", [(0, 1), (1, 2), (2, 4), (4, 6)])
def test_room_preserves_padding_and_source_store_order(count: int, capacity: int) -> None:
    f = Fixture()
    begin = f.block(capacity)
    f.header(begin, count, capacity)
    result = f.append()
    assert result == begin + count * 16
    assert f.fields() == (begin, result + 16, begin + capacity * 16)
    assert_item(f.memory, result, b"\xa5" * 3)
    stores = [
        (row[1] - result, row[2])
        for row in f.events
        if row[0] == "w" and result <= row[1] < result + 16
    ]
    assert stores == [(2, 2), (0, 2), (12, 4), (4, 1), (8, 4)]
    assert f.calls() == []


@pytest.mark.parametrize("count,capacity", [(0, 1), (1, 2), (2, 3), (3, 4), (4, 6), (6, 9)])
def test_full_growth_uses_real_owned_allocator_move_free(count: int, capacity: int) -> None:
    f = Fixture()
    begin = f.block(count) if count else 0
    f.header(begin, count, count)
    result = f.append()
    allocation, end, cap = f.fields()
    assert result == allocation + count * 16
    assert end == allocation + (count + 1) * 16 and cap == allocation + capacity * 16
    assert f.memory.read_bytes(allocation, count * 16) == b"\xa5" * (count * 16)
    assert_item(f.memory, result, None)
    assert [target for target, _args in f.calls()] == (
        [ALLOC, MOVE, FREE] if count else [ALLOC, MOVE]
    )
    assert f.calls()[0] == (ALLOC, (capacity * 16,))
    stores = [
        (row[1] - result, row[2])
        for row in f.events
        if row[0] == "w" and result <= row[1] < result + 16
    ]
    assert stores == [(0, 2), (12, 4), (2, 2), (4, 1), (8, 4)]


def test_repeated_real_appends_keep_fields_and_undefined_padding() -> None:
    f = Fixture()
    f.header()
    for value in range(40):
        f.memory.write(INPUT, 2, value)
        result = f.append()
        assert f.memory.read(result, 2) == value
    begin, end, capacity = f.fields()
    assert end == begin + 640 and capacity >= end
    assert [f.memory.read(begin + i * 16, 2) for i in range(40)] == list(range(40))
    with pytest.raises(ReplayMemoryError, match="undefined"):
        f.memory.read(begin + 5, 1)


def test_room_loads_all_payload_before_stores() -> None:
    f = Fixture()
    begin = f.block(1)
    f.header(begin, 0, 1)
    f.append()
    payload = [
        (row[1] - INPUT, row[2])
        for row in f.events
        if row[0] == "r" and INPUT <= row[1] < INPUT + 16
    ]
    assert payload == [(2, 2), (4, 1), (12, 4), (8, 4), (0, 2)]
    final_read = max(
        i for i, row in enumerate(f.events) if row[0] == "r" and INPUT <= row[1] < INPUT + 16
    )
    first_store = min(
        i for i, row in enumerate(f.events) if row[0] == "w" and begin <= row[1] < begin + 16
    )
    assert final_read < first_store


def test_allocator_mutation_changes_payload_and_live_pointer_homes() -> None:
    f = Fixture()
    f.header()
    alternate = 0x3000
    f.memory.map_bytes(alternate, bytes.fromhex("6655000078563412efbeadde"))

    def after(target: int, _args: tuple[int, ...], _result: int | None) -> None:
        if target == ALLOC:
            assert f.local is not None
            f.memory.write(f.local + 0x20, 8, alternate)
            f.memory.write(f.local + 0x80, 8, alternate + 4)
            f.memory.write(f.local + 0x88, 8, alternate + 8)
            f.memory.write(INPUT + 2, 2, 0x7788)
            f.memory.write(INPUT + 4, 1, 0xEE)

    f.after = after
    result = f.append()
    assert f.memory.read(result, 2) == 0x5566
    assert f.memory.read(result + 2, 2) == 0x7788
    assert f.memory.read(result + 4, 1) == 0xEE
    assert f.memory.read(result + 8, 4) == 0x12345678
    assert f.memory.read(result + 12, 4) == 0xDEADBEEF
    first_alloc = next(i for i, row in enumerate(f.events) if row[:2] == ("c", ALLOC))
    assert all(
        i > first_alloc
        for i, row in enumerate(f.events)
        if row[0] == "r" and INPUT <= row[1] < INPUT + 16
    )


def test_room_returns_late_current_end_but_writes_held_destination() -> None:
    f = Fixture()
    begin = f.block(3)
    f.header(begin, 0, 3)

    def on_write(address: int, _width: int, _value: int) -> None:
        if address == begin + 8:
            f.memory.write(H + 8, 8, begin + 16)

    f.on_write = on_write
    assert f.append() == begin + 16
    assert f.fields() == (begin, begin + 32, begin + 48)
    assert_item(f.memory, begin, b"\xa5" * 3)
    assert f.memory.read_bytes(begin + 16, 16) == b"\xa5" * 16


def test_room_keeps_second_register_pointer_but_reads_late_fifth_home() -> None:
    f = Fixture()
    begin = f.block(1)
    f.header(begin, 0, 1)
    alternate = 0x3000
    f.memory.map_bytes(alternate, bytes.fromhex("6655000078563412"))

    def on_read(address: int, _width: int, _value: int) -> None:
        if address == INPUT + 2:
            assert f.local is not None
            f.memory.write(f.local + 0x20, 8, alternate)
            f.memory.write(f.local + 0x80, 8, alternate + 4)

    f.on_read = on_read
    result = f.append()
    assert f.memory.read(result, 2) == 0x1122
    assert f.memory.read(result + 8, 4) == 0x12345678


def test_growth_split_copy_reloads_end_after_first_actual_move() -> None:
    f = Fixture()
    begin = f.block(8, 0x33)
    f.header(begin, 6, 6)

    def after(target: int, args: tuple[int, ...], _result: int | None) -> None:
        if target == ALLOC:
            f.memory.write(H + 8, 8, begin + 112)
        if target == MOVE and args[1] == begin:
            f.memory.write(H + 8, 8, begin + 128)

    f.after = after
    result = f.append()
    moves = [args for target, args in f.calls() if target == MOVE]
    assert len(moves) == 2 and moves[0][2] == 96
    assert moves[1] == (result + 16, begin + 96, 32)
    assert f.memory.read_bytes(result + 16, 32) == b"\x33" * 32
    assert f.fields()[1] == result + 16


@pytest.mark.parametrize("raw", [0, 0x80000000, 0x7F800000, 0xFF800000, 0x7FC12345])
def test_movss_preserves_every_raw_float_word(raw: int) -> None:
    f = Fixture()
    begin = f.block(1)
    f.header(begin, 0, 1)
    f.memory.write(INPUT + 12, 4, raw)
    assert f.memory.read(f.append() + 12, 4) == raw


@pytest.mark.parametrize("entry", [COMMIT, CLEAR])
def test_null_begin_skips_missing_descriptor_words(entry: int) -> None:
    f = Fixture()
    f.memory.map_bytes(H, bytes(8))
    if entry == COMMIT:
        f.memory.map_bytes(H + 8, bytes(16))
        assert f.invoke(entry, H, 0x9000, 2, 3) is None
        assert f.fields() == (0x9000, 0x9020, 0x9030)
    else:
        assert f.invoke(entry, H) is None
    assert [(row[1], row[2]) for row in f.events if row[0] == "r"] == [(H, 8)]
    assert not f.calls()


@pytest.mark.parametrize("entry", [COMMIT, CLEAR])
@pytest.mark.parametrize("capacity", [1, 255, 256, 257])
def test_release_small_and_large_real_allocations(entry: int, capacity: int) -> None:
    f = Fixture()
    begin = f.block(capacity)
    f.header(begin, 0, capacity)
    old_raw = f.memory.read(begin - 8, 8) if capacity >= 256 else begin
    args = (H, 0x9000, 2, 3) if entry == COMMIT else (H,)
    assert f.invoke(entry, *args) is None
    size = capacity * 16 + (0x27 if capacity >= 256 else 0)
    assert f.calls() == [(FREE, (old_raw, size))]
    assert f.fields() == ((0x9000, 0x9020, 0x9030) if entry == COMMIT else (0, 0, 0))


@pytest.mark.parametrize("entry", [COMMIT, CLEAR])
def test_release_uses_masked_wrapped_size_and_no_end_read(entry: int) -> None:
    f = Fixture()
    f.memory.map_bytes(H, (0x5000).to_bytes(8, "little"))
    f.memory.map_bytes(H + 8, b"\xa5" * 16)
    f.memory.write(H + 16, 8, 0x501F)
    f.effects[FREE] = lambda _args: None  # Explicit opaque release boundary.
    f.invoke(entry, *((H, 0, 0, 0) if entry == COMMIT else (H,)))
    assert f.calls() == [(FREE, (0x5000, 16))]
    assert not any(row[0] == "r" and row[1] == H + 8 for row in f.events)


@pytest.mark.parametrize("entry", [COMMIT, CLEAR])
@pytest.mark.parametrize("displacement,valid", [(0, True), (31, True), (32, False), (U64, False)])
def test_large_backpointer_unsigned_guard_current_watson(
    entry: int,
    displacement: int,
    valid: bool,
) -> None:
    f = Fixture()
    begin = 0x8000
    raw = (begin - 8 - displacement) & U64
    f.header(begin, 0, 256)
    f.memory.map_bytes(begin - 8, raw.to_bytes(8, "little"))
    f.memory.map_bytes(WATSON_SLOT, WATSON.to_bytes(8, "little"))
    f.effects[FREE] = lambda _args: None  # Inspect true raw pointer/size without foreign free.
    f.effects[WATSON] = lambda _args: None  # Returned terminal must refuse, never succeed.
    args = (H, 1, 2, 3) if entry == COMMIT else (H,)
    before = f.fields()
    if valid:
        f.invoke(entry, *args)
        assert f.calls() == [(FREE, (raw, 0x1027))]
    else:
        with pytest.raises(UnresolvedReplayTaskRebuild, match="Watson returned"):
            f.invoke(entry, *args)
        assert f.calls() == [(WATSON, (0, 0, 0, 0, 0))]
        assert f.fields() == before


@pytest.mark.parametrize("entry", [COMMIT, CLEAR])
def test_actual_free_failure_keeps_header_and_previous_effects(entry: int) -> None:
    f = Fixture()
    begin = f.block(1)
    f.header(begin, 1, 1)
    old = f.fields()

    def failure(_args: tuple[int, ...]) -> None:
        f.memory.write(INPUT, 1, 0xEE)
        raise LookupError("free-boundary")

    f.effects[FREE] = failure
    with pytest.raises(LookupError, match="free-boundary"):
        f.invoke(entry, *((H, 5, 6, 7) if entry == COMMIT else (H,)))
    assert f.fields() == old and f.memory.read(INPUT, 1) == 0xEE


@pytest.mark.parametrize("entry", [COMMIT, CLEAR])
def test_current_free_callback_mutation_is_overwritten_only_by_ordered_stores(entry: int) -> None:
    f = Fixture()
    begin = f.block(1)
    f.header(begin, 1, 1)

    def after(target: int, _args: tuple[int, ...], _result: int | None) -> None:
        if target == FREE:
            f.memory.write(H, 8, 99)
            f.memory.write(H + 8, 8, 98)
            f.memory.write(H + 16, 8, 97)

    f.after = after
    f.invoke(entry, *((H, 0x9000, 2, 3) if entry == COMMIT else (H,)))
    writes = [row[1] for row in f.events if row[0] == "w"]
    assert writes == [H, H + 8, H + 16]
    assert f.fields() == ((0x9000, 0x9020, 0x9030) if entry == COMMIT else (0, 0, 0))


@pytest.mark.parametrize("count,capacity", [(0, 0), (1 << 60, U64), (U64, 1 << 63)])
def test_commit_held_products_wrap_to_raw_u64(count: int, capacity: int) -> None:
    f = Fixture()
    f.header()
    f.invoke(COMMIT, H, U64 - 7, count, capacity)
    assert f.fields() == (U64 - 7, (U64 - 7 + count * 16) & U64, (U64 - 7 + capacity * 16) & U64)


@pytest.mark.parametrize("entry", [COMMIT, CLEAR])
def test_header_write_failure_keeps_prior_free_and_first_store(entry: int) -> None:
    f = Fixture()
    begin = f.block(1)
    f.memory.map_bytes(H, begin.to_bytes(8, "little"))
    f.memory.map_bytes(H + 8, (begin + 16).to_bytes(8, "little"), writable=False)
    f.memory.map_bytes(H + 16, (begin + 16).to_bytes(8, "little"))
    with pytest.raises(ReplayMemoryError, match="readonly"):
        f.invoke(entry, *((H, 0x9000, 2, 3) if entry == COMMIT else (H,)))
    assert f.calls() == [(FREE, (begin, 16))]
    assert f.memory.read(H, 8) == (0x9000 if entry == COMMIT else 0)
    assert f.memory.read(H + 8, 8) == begin + 16
    assert f.memory.read(H + 16, 8) == begin + 16


def test_watson_target_is_current_after_guard_reads() -> None:
    f = Fixture()
    f.header(0x8000, 0, 256)
    f.memory.map_bytes(0x7FF8, (0x7000).to_bytes(8, "little"))
    f.memory.map_bytes(WATSON_SLOT, WATSON.to_bytes(8, "little"))
    alternate = WATSON + 1
    f.effects[alternate] = lambda _args: None

    def on_read(address: int, _width: int, _value: int) -> None:
        if address == 0x7FF8:
            f.memory.write(WATSON_SLOT, 8, alternate)

    f.on_read = on_read
    with pytest.raises(UnresolvedReplayTaskRebuild, match="Watson returned"):
        f.invoke(CLEAR, H)
    assert f.calls() == [(alternate, (0, 0, 0, 0, 0))]


def test_index_maximum_error_is_unreachable_after_signed_sar_of_raw64_difference() -> None:
    # Complete source retains this error arm, but no fabricated register mutation
    # or monkeypatch is used to claim a body-level reachable outcome for it.
    maximum = (1 << 60) - 1
    positive_ceiling = ((1 << 63) - 1) >> 4
    negative_floor = (-(1 << 63) >> 4) & U64
    assert positive_ceiling == 0x07FFFFFFFFFFFFFF < maximum < negative_floor


def test_raw_signed_sar_then_unsigned_capacity_saturates_before_real_allocator() -> None:
    f = Fixture()
    f.header(16, U64, U64)
    # Exact raw descriptor end=0 after wrapped multiplication; no enormous backing is fabricated.
    f.memory.write(H + 8, 8, 0)
    f.memory.write(H + 16, 8, 0)

    def reject(_args: tuple[int, ...]) -> None:
        raise LookupError("huge-allocation-refused")

    f.effects[ALLOC] = reject
    with pytest.raises(LookupError, match="huge-allocation-refused"):
        f.append()
    assert f.calls() == [(ALLOC, (0xFFFFFFFFFFFFFFF0,))]


@pytest.mark.parametrize("failed", [ALLOC, MOVE, COMMIT])
def test_append_reached_unknown_children_refuse_without_success(failed: int) -> None:
    f = Fixture()
    f.header()
    lower = ReplayTaskRebuildCalls(f.lower)
    if failed == COMMIT:
        # Direct body retains actual commit boundary; binder would supply this known body.
        f.effects[COMMIT] = lambda _args: (_ for _ in ()).throw(LookupError("commit"))
    else:
        f.effects[failed] = lambda _args: (_ for _ in ()).throw(LookupError("boundary"))
    with pytest.raises(LookupError):
        items.append_replay_research_item(
            f.context,
            H,
            INPUT,
            INPUT + 2,
            INPUT + 4,
            INPUT + 8,
            INPUT + 12,
            calls=lower,
            bind_local=f.bind_local,
            scratch=items.ReplayResearchItemsScratch(bytes(0x90)),
        )
    assert f.fields() == (0, 0, 0)
    assert f.local is None


@pytest.mark.parametrize("entry,args", [(APPEND, (H,)), (COMMIT, (H, 0)), (CLEAR, (H, 0))])
def test_binder_requires_actual_entry_arity(entry: int, args: tuple[int, ...]) -> None:
    f = Fixture()
    with pytest.raises(ValueError, match="malformed"):
        f.invoke(entry, *args)
    assert f.events == []


@pytest.mark.parametrize(
    "entry,args",
    [
        (APPEND, (H, INPUT, INPUT + 2, INPUT + 4, INPUT + 8, INPUT + 12)),
        (COMMIT, (H, 0, 0, 0)),
        (CLEAR, (H,)),
    ],
)
def test_scalar_entries_reject_extra_live_data(entry: int, args: tuple[int, ...]) -> None:
    f = Fixture()
    call = f.bound().call
    assert call is not None
    with pytest.raises(ValueError, match="malformed"):
        call(entry, args, memoryview(bytearray(1)))
    assert f.events == []


def test_unknown_body_cannot_be_invented_by_binder() -> None:
    f = Fixture()
    bound = items.bind_replay_research_items(
        f.context,
        ReplayTaskRebuildCalls(None),
        bind_local=f.bind_local,
        scratch=items.ReplayResearchItemsScratch(bytes(0x90)),
    )
    assert bound.call is not None
    with pytest.raises(UnresolvedReplayTaskRebuild, match="unavailable"):
        bound.call(0x12345678, (), None)


@pytest.mark.parametrize("seed", [b"", bytes(0x8F), bytes(0x91), bytearray(0x90)])
def test_frame_seed_has_exact_type_and_width(seed: bytes) -> None:
    with pytest.raises(ValueError, match="90B"):
        items.ReplayResearchItemsScratch(seed)


def test_real_row_clear_composes_this_vector_destructor() -> None:
    f = Fixture()
    row = f.block(10, 0)
    vector = row + 0x80
    allocation = f.block(2, 0xCC)
    f.memory.write(vector, 8, allocation)
    f.memory.write(vector + 8, 8, allocation + 16)
    f.memory.write(vector + 16, 8, allocation + 32)
    # The3 real DE-string null branches are concrete source ports, not cleanup noops.
    from vantage.replay_player_civilization_lookup import (
        bind_replay_player_civilization_lookup,
    )

    lower = bind_replay_player_civilization_lookup(
        f.context, f.bound(), bind_local=f.bind_local, scratch=bytes(8)
    )
    bound = bind_replay_research_storage(
        f.context,
        lower,
        imports=ReplayTaskRebuildCalls(f.lower),
        bind_local=f.bind_local,
        scratch=ReplayResearchStorageScratch(bytes(8)),
    )
    f.memory.map_bytes(H, b"".join(value.to_bytes(8, "little") for value in (row, 1, 1)))
    assert bound.call is not None
    assert bound.call(0x141491C50, (H,), None) is None
    assert f.memory.read(H + 16, 8) == 0
    assert f.memory.read_bytes(vector, 24) == bytes(24)
    assert f.calls() == [(FREE, (allocation, 32))]
