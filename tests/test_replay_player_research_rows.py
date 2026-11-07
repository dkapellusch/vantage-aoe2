"""Source-led research-row controls over actual engine-owned byte storage.

Callbacks below are explicit mutation/error seams, not a native execution
oracle. Literal expected events distinguish held registers from current reads.
"""

from __future__ import annotations

from contextlib import contextmanager

import pytest

from vantage.replay_memory import ReplayMemory, ReplayMemoryError, ReplayMemoryRuntimeError
from vantage.replay_player_research_rows import bind_replay_player_research_rows
from vantage.replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
)

WRAPPER, COPY, RELEASE, LENGTH = 0x140F92850, 0x140F92070, 0x1402A8790, 0x140F6BBF0
ALLOC, MOVE, FREE, THROW = 0x1402A94D0, 0x142D6E3DB, 0x142D6BAB4, 0x142D66698
IAT, INVALID, U64 = 0x14319A060, 0xF00D, (1 << 64) - 1
ENTRIES = (WRAPPER, COPY, RELEASE, LENGTH)


class Fixture:
    def __init__(self):
        self.memory = ReplayMemory(max_bytes=1 << 20)
        self.source, self.destination = self.memory.allocate(24), self.memory.allocate(24)
        self.memory.fill(self.destination, 0xA5, 24)
        self.memory.map_bytes(IAT, INVALID.to_bytes(8, "little"))
        self.runtime = self.memory.runtime_calls()
        self.events, self.closed = [], []
        self.effects, self.unavailable = {}, set()
        self.on_read = self.on_write = None
        self.local, self.live = 0, False
        self.context = ReplayTaskRebuildStorage(self.source, self.read, self.write)
        self.calls = ReplayTaskRebuildCalls(self.dispatch)
        self.imports = ReplayTaskRebuildCalls(self.terminal)
        self.bound = bind_replay_player_research_rows(
            self.context,
            self.calls,
            bind_local=self.bind_local,
            error_seed=b"\xa5" * 8,
            imports=self.imports,
        )

    def read(self, address, width):
        value = self.memory.read(address, width)
        self.events.append(("r", address, width, value))
        if self.on_read:
            self.on_read(address, width, value)
        return value

    def write(self, address, width, value):
        self.memory.write(address, width, value)
        self.events.append(("w", address, width, value))
        if self.on_write:
            self.on_write(address, width, value)

    @contextmanager
    def bind_local(self, view):
        with self.memory.bind_local(view) as address:
            self.local, self.live = address, True
            try:
                yield address
            finally:
                self.closed.append(bytes(view))
                self.live = False

    def dispatch(self, target, args, data):
        self.events.append(("c", target, args))
        if target in self.unavailable:
            raise UnresolvedReplayTaskRebuild(f"authored missing child {target:x}")
        if target in self.effects:
            return self.effects[target](args)
        if target in ENTRIES:
            return self.invoke(target, *args, data=data)
        assert self.runtime.call
        return self.runtime.call(target, args, data)

    def terminal(self, target, args, data):
        self.events.append(("i", target, args))
        assert self.live
        assert data is None
        if target in self.effects:
            return self.effects[target](args)
        raise UnresolvedReplayTaskRebuild(f"authored terminal {target:x}")

    def invoke(self, target, *args, data=None):
        assert self.bound.call
        return self.bound.call(target, args, data)

    def span(self, begin, size, *, header=None):
        header = self.source if header is None else header
        self.memory.write(header, 8, begin)
        self.memory.write(header + 8, 8, (begin + size) & U64)
        # Capacity is intentionally undefined: COPY must never read it.

    def payload(self, size):
        address = self.memory.allocate(size)
        raw = bytes((n * 17 + 3) & 255 for n in range(size))
        self.memory.write_bytes(address, raw)
        return address, raw

    def header(self, address=None):
        address = self.destination if address is None else address
        return tuple(self.memory.read(address + offset, 8) for offset in (0, 8, 16))

    def children(self):
        return [(event[1], event[2]) for event in self.events if event[0] == "c"]


@pytest.mark.parametrize("size", [20, 40, 60])
def test_real_copy_publishes_header_and_preserves_all_row_bytes(size):
    f = Fixture()
    begin, raw = f.payload(size)
    f.span(begin, size)
    assert f.invoke(WRAPPER, f.source - 0x38, f.destination) == f.destination
    allocated, end, capacity = f.header()
    assert f.memory.read_bytes(allocated, size) == raw
    assert end == capacity == allocated + size
    assert f.children() == [
        (COPY, (f.destination, f.source)),
        (ALLOC, (size,)),
        (MOVE, (allocated, begin, size)),
    ]
    assert f.events[1:6] == [
        ("w", f.destination, 8, 0),
        ("w", f.destination + 8, 8, 0),
        ("w", f.destination + 16, 8, 0),
        ("r", f.source + 8, 8, begin + size),
        ("r", f.source, 8, begin),
    ]


@pytest.mark.parametrize("size", [0, 1, 19, -1, -19])
def test_signed_subrow_spans_return_zero_header_without_children(size):
    f = Fixture()
    f.span(0x2000, size)
    assert f.invoke(COPY, f.destination, f.source) == f.destination
    assert f.header() == (0, 0, 0)
    assert f.children() == []


@pytest.mark.parametrize("offset,expected", [(0, (0, 0)), (8, (0, 0x9000))])
def test_header_overlap_takes_effect_before_initial_reads(offset, expected):
    f = Fixture()
    block = f.memory.allocate(40)
    f.span(0x9000, 40, header=block)
    # destination=source or destination=source+8 overwrites the source first.
    if offset:
        f.effects[LENGTH] = lambda args: None
        with pytest.raises(UnresolvedReplayTaskRebuild, match="140f92141"):
            f.invoke(COPY, block + offset, block)
    else:
        assert f.invoke(COPY, block, block) == block
    reads = [event[3] for event in f.events if event[0] == "r"]
    assert tuple(reads) == expected


@pytest.mark.parametrize("initial,later", [(40, 21), (40, 0), (21, 19)])
def test_allocator_changes_later_copy_span_and_end_truncates_only_after_move(initial, later):
    f = Fixture()
    original, _ = f.payload(60)
    changed, changed_raw = f.payload(60)
    f.span(original, initial)
    allocated = f.memory.allocate(60)

    def allocate(args):
        assert args == (40 if initial == 40 else 20,)
        f.span(changed, later)
        return allocated

    f.effects[ALLOC] = allocate
    assert f.invoke(COPY, f.destination, f.source) == f.destination
    assert (MOVE, (allocated, changed, later)) in f.children()
    assert f.memory.read_bytes(allocated, later) == changed_raw[:later]
    assert f.header() == (
        allocated,
        allocated + (20 if later == 21 else 0),
        allocated + (40 if initial == 40 else 20),
    )


def test_publications_precede_current_begin_then_end_reads_and_hold_move_arguments():
    f = Fixture()
    begin, raw = f.payload(60)
    f.span(begin, 40)
    allocated = f.memory.allocate(60)
    f.effects[ALLOC] = lambda args: allocated
    reads = 0

    def read(address, width, value):
        nonlocal reads
        if address == f.source:
            reads += 1
            if reads == 2:
                assert f.header() == (allocated, allocated, allocated + 40)
                f.memory.write(f.source + 8, 8, begin + 60)
        if address == f.source + 8 and reads == 2:
            f.memory.write(f.source, 8, 0xDEAD)

    f.on_read = read
    f.invoke(COPY, f.destination, f.source)
    assert f.children()[-1] == (MOVE, (allocated, begin, 60))
    assert f.memory.read_bytes(allocated, 60) == raw
    assert f.header() == (allocated, allocated + 60, allocated + 40)


def test_move_header_mutations_preserve_held_allocation_and_span_for_final_end():
    f = Fixture()
    begin, _ = f.payload(40)
    f.span(begin, 40)
    allocated = f.memory.allocate(40)
    f.effects[ALLOC] = lambda args: allocated

    def move(args):
        f.memory.move(*args)
        f.memory.write(f.destination, 8, 0xAAAA)
        f.memory.write(f.destination + 8, 8, 0xBBBB)
        f.memory.write(f.destination + 16, 8, 0xCCCC)
        f.span(0xDDDD, 0)
        return 0xEEEE

    f.effects[MOVE] = move
    f.invoke(COPY, f.destination, f.source)
    assert f.header() == (0xAAAA, allocated + 40, 0xCCCC)


def test_actual_memmove_retains_overlapping_payload_snapshot():
    f = Fixture()
    block, raw = f.payload(60)
    f.span(block, 40)
    f.effects[ALLOC] = lambda args: block + 4
    f.invoke(COPY, f.destination, f.source)
    assert f.memory.read_bytes(block + 4, 40) == raw[:40]
    assert f.header() == (block + 4, block + 44, block + 44)


@pytest.mark.parametrize("size", [-20, -40, -(1 << 63)])
def test_negative_nonzero_quotient_reaches_actual_length_literal_and_refuses(size):
    f = Fixture()
    f.span(0, size)
    with pytest.raises(ReplayMemoryRuntimeError):
        f.invoke(COPY, f.destination, f.source)
    assert f.header() == (0, 0, 0)
    assert f.children() == [(LENGTH, ()), (THROW, (0x1436794B0,))]


@pytest.mark.parametrize("entry,trap", [(COPY, "140f92141"), (LENGTH, "140f6bc00")])
def test_returning_length_provider_refuses_at_its_actual_adjacent_trap(entry, trap):
    f = Fixture()
    if entry == COPY:
        f.span(0, -20)
        f.effects[LENGTH] = lambda args: 123
        args = (f.destination, f.source)
    else:
        f.effects[THROW] = lambda args: 123
        args = ()
    with pytest.raises(UnresolvedReplayTaskRebuild, match=trap):
        f.invoke(entry, *args)


@pytest.mark.parametrize("child", [ALLOC, MOVE, LENGTH])
def test_missing_child_preserves_reached_zeroing_and_publications(child):
    f = Fixture()
    begin, _ = f.payload(40)
    f.span(begin, -20 if child == LENGTH else 40)
    f.unavailable.add(child)
    with pytest.raises(UnresolvedReplayTaskRebuild, match="authored missing child"):
        f.invoke(COPY, f.destination, f.source)
    if child == MOVE:
        allocated, end, capacity = f.header()
        assert allocated and end == allocated and capacity == allocated + 40
    else:
        assert f.header() == (0, 0, 0)


def test_wrapper_returns_held_destination_ignoring_child_rax_without_source_reads():
    f = Fixture()
    f.effects[COPY] = lambda args: 0xBAD
    assert f.invoke(WRAPPER, U64 - 0x20, f.destination) == f.destination
    assert f.events == [("c", COPY, (f.destination, 0x17))]


@pytest.mark.parametrize("size", [0, 1, 0xFFF])
def test_small_release_mandatorily_frees_including_zero_without_header_reset(size):
    f = Fixture()
    pointer, _ = f.payload(40)
    f.span(pointer, 40)
    before = f.memory.read_bytes(f.source, 16)
    assert f.invoke(RELEASE, pointer, size) is None
    assert f.children() == [(FREE, (pointer, size))]
    assert not any(event[0] in ("r", "w") for event in f.events)
    assert f.memory.read_bytes(f.source, 16) == before
    with pytest.raises(ReplayMemoryError):
        f.memory.read(pointer, 1)


@pytest.mark.parametrize("gap", [0, 1, 31])
def test_large_release_uses_current_backpointer_and_adjusted_byte_size(gap):
    f = Fixture()
    base = f.memory.allocate(0x1050)
    pointer = base + 8 + gap
    f.memory.write(pointer - 8, 8, base)
    assert f.invoke(RELEASE, pointer, 0x1000) is None
    assert f.children() == [(FREE, (base, 0x1027))]
    assert f.events[0] == ("r", pointer - 8, 8, base)
    with pytest.raises(ReplayMemoryError):
        f.memory.read(base, 1)


def test_release_byte_size_adjustment_wraps_and_tailcall_raw_return_is_preserved():
    f = Fixture()
    pointer = f.memory.allocate(24) + 8
    f.memory.write(pointer - 8, 8, pointer - 8)
    f.effects[FREE] = lambda args: 0xBEEF
    assert f.invoke(RELEASE, pointer, U64) == 0xBEEF
    assert f.children() == [(FREE, (pointer - 8, 0x26))]


@pytest.mark.parametrize("gap", [32, -1])
def test_invalid_large_gap_reads_current_iat_and_live_fifth_after_zero_store(gap):
    f = Fixture()
    block = f.memory.allocate(96)
    pointer, base = block + 48, block + 48 - 8 - gap
    f.memory.write(pointer - 8, 8, base)
    updated = INVALID + 1
    f.memory.write(IAT, 8, updated)

    def read(address, width, value):
        if address == IAT:
            assert f.live and f.memory.read(f.local, 8) == 0
            f.memory.write(f.local, 8, 0xABCDEF)

    f.on_read = read
    with pytest.raises(UnresolvedReplayTaskRebuild, match=f"authored terminal {updated:x}"):
        f.invoke(RELEASE, pointer, 0x1000)
    assert ("i", updated, (0, 0, 0, 0, 0xABCDEF)) in f.events
    assert f.children() == []
    assert f.closed == [(0xABCDEF).to_bytes(8, "little")]
    assert not f.live
    with pytest.raises(ReplayMemoryError):
        f.memory.read(f.local, 8)
    assert f.memory.read(pointer - 8, 8) == base


def test_returning_invalid_parameter_provider_refuses_before_free_and_unmaps_home():
    f = Fixture()
    pointer = f.memory.allocate(80) + 48
    f.memory.write(pointer - 8, 8, pointer - 41)
    f.effects[INVALID] = lambda args: 9
    with pytest.raises(UnresolvedReplayTaskRebuild, match="1402a87d7"):
        f.invoke(RELEASE, pointer, 0x1000)
    assert f.children() == [] and not f.live


@pytest.mark.parametrize(
    "entry,args", [(WRAPPER, (1,)), (COPY, (1,)), (RELEASE, (1,)), (LENGTH, (1,))]
)
def test_effective_arity_is_validated_before_any_effect(entry, args):
    f = Fixture()
    with pytest.raises(ValueError, match="malformed"):
        f.invoke(entry, *args)
    assert f.events == []


def test_unknown_target_delegates_data_and_raw_return_without_reinterpretation():
    f = Fixture()
    view = memoryview(bytearray(b"abc"))
    seen = []

    def delegate(target, args, data):
        seen.append((target, args, data))
        return 0x456

    bound = bind_replay_player_research_rows(
        f.context,
        ReplayTaskRebuildCalls(delegate),
        bind_local=f.bind_local,
        error_seed=bytes(8),
    )
    assert bound.call and bound.call(0x123, (7,), view) == 0x456
    assert seen == [(0x123, (7,), view)]
    assert seen[0][2] is view
    assert f.events == []


def test_null_zero_byte_release_is_a_real_tailcall():
    f = Fixture()
    assert f.invoke(RELEASE, 0, 0) is None
    assert f.events == [("c", FREE, (0, 0))]


@pytest.mark.parametrize("seed", [b"", bytes(7), bytes(9), bytearray(8)])
def test_error_seed_is_explicit_and_exact(seed):
    f = Fixture()
    with pytest.raises(ValueError, match="eight-byte"):
        bind_replay_player_research_rows(
            f.context,
            f.calls,
            bind_local=f.bind_local,
            error_seed=seed,
        )
