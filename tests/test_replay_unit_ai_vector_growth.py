"""Owned-memory controls for exact current UnitAI append/grow/commit phases."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from vantage.replay_memory import ReplayMemory, ReplayMemoryError, ReplayMemoryRuntimeError
from vantage.replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
)
from vantage.replay_task_rows import commit_replay_task_vector4
from vantage.replay_unit_ai_vector_growth import (
    append_replay_unit_ai_class,
    bind_replay_unit_ai_vector_growth,
    commit_replay_unit_ai_rows,
    grow_replay_unit_ai_rows,
)

U64 = (1 << 64) - 1


class Harness:
    def __init__(self):
        self.memory = ReplayMemory()
        self.events = []
        self.overrides: dict[int, Callable[[tuple[int, ...]], int | None]] = {}
        self.after_read = None
        self.after_write = None
        self.context = ReplayTaskRebuildStorage(1, self.read, self.write)
        self.runtime = self.memory.runtime_calls()
        self.ordinary = ReplayTaskRebuildCalls(self.call)
        self.bound = bind_replay_unit_ai_vector_growth(
            self.context, self.ordinary, imports=ReplayTaskRebuildCalls(self.imported)
        )
        self.memory.map_bytes(0x1431999A0, (0x142D6E3DB).to_bytes(8, "little"))
        self.memory.map_bytes(0x143199DD0, (0x142D6BAB4).to_bytes(8, "little"))

    def read(self, address, width):
        value = self.memory.read(address, width)
        self.events.append(("read", address, width, value))
        if self.after_read:
            self.after_read(address, width)
        return value

    def write(self, address, width, value):
        self.memory.write(address, width, value)
        self.events.append(("write", address, width, value))
        if self.after_write:
            self.after_write(address, width, value)

    def call(self, target, args, data):
        assert data is None
        self.events.append(("call", target, args))
        if target in self.overrides:
            return self.overrides[target](args)
        if target == 0x1402BA840:
            commit_replay_task_vector4(self.context, *args, calls=self.bound)
            return (args[1] + args[3] * 4) & U64
        assert self.runtime.call is not None
        return self.runtime.call(target, args, data)

    def imported(self, target, args, data):
        assert data is None
        self.events.append(("import", target, args))
        if target in self.overrides:
            return self.overrides[target](args)
        assert self.runtime.call is not None
        return self.runtime.call(target, args, data)

    def invoke(self, target, *args):
        assert self.bound.call is not None
        return self.bound.call(target, args, None)

    def header(self, begin=0, end=0, capacity=0):
        address = self.memory.allocate(24)
        for offset, value in ((0, begin), (8, end), (16, capacity)):
            self.memory.write(address + offset, 8, value & U64)
        return address

    def calls(self, kind, target):
        return [event[2] for event in self.events if event[:2] == (kind, target)]


def source(h, data):
    address = h.memory.allocate(len(data))
    h.memory.write_bytes(address, data)
    return address


def test_append_repeated_real_growth_preserves_duplicates_and_snapshot():
    h = Harness()
    vector = h.header()
    value = source(h, bytes(4))
    values = [7, 7, 0xFFFFFFFF, *range(20)]
    capacities = []
    for word in values:
        h.memory.write(value, 4, word)
        h.invoke(0x1402B89C0, vector, value)
        begin = h.memory.read(vector, 8)
        capacities.append((h.memory.read(vector + 16, 8) - begin) // 4)
    assert h.memory.read_bytes(begin, len(values) * 4) == b"".join(
        word.to_bytes(4, "little") for word in values
    )
    assert capacities[:7] == [1, 2, 3, 4, 6, 6, 9]
    assert h.memory.read(vector + 8, 8) == begin + len(values) * 4
    restored = ReplayMemory.from_snapshot(h.memory.snapshot())
    assert restored.snapshot() == h.memory.snapshot()
    assert h.calls("call", 0x1402BA840)


def test_append_fast_current_end_rmw_and_residual_source_word_no_begin_read():
    h = Harness()
    data = source(h, bytes(16))
    vector = h.header(0xDEAD, data, data + 16)
    value = source(h, (0xAABBCCDD).to_bytes(4, "little"))

    def changed(address, width, _value):
        if (address, width) == (data, 4):
            h.memory.write(vector + 8, 8, data + 8)

    h.after_write = changed
    assert h.invoke(0x1402B89C0, vector, value) == 0xAABBCCDD
    assert h.memory.read(vector + 8, 8) == data + 12
    assert h.memory.read(data, 4) == 0xAABBCCDD
    assert [event[1:3] for event in h.events if event[0] == "read"] == [
        (vector + 16, 8),
        (vector + 8, 8),
        (value, 4),
        (vector + 8, 8),
    ]


def test_append_growth_value_is_current_after_allocator_and_tail_return_is_forwarded():
    h = Harness()
    vector = h.header()
    value = source(h, (5).to_bytes(4, "little"))

    def allocate(args):
        h.memory.write(value, 4, 91)
        return h.memory.allocate_aligned(args[0])

    def commit(args):
        commit_replay_task_vector4(h.context, *args, calls=h.bound)
        return 0xC0FFEE

    h.overrides.update({0x1402A94D0: allocate, 0x1402BA840: commit})
    assert h.invoke(0x1402B89C0, vector, value) == 0xC0FFEE
    begin = h.memory.read(vector, 8)
    assert h.memory.read(begin, 4) == 91
    assert h.calls("import", 0x142D6E3DB) == [(begin, 0, 0)]


@pytest.mark.parametrize("position", [0, 1, 2])
def test_growth52_actual_insertion_copy_free_and_complete_padding(position):
    h = Harness()
    old = source(h, bytes(range(104)) + bytes(52))
    vector = h.header(old, old + 104, old + 156)
    row = source(h, bytes(range(170, 222)))
    inserted = h.invoke(0x140CEDD60, vector, old + position * 52, row)
    begin = h.memory.read(vector, 8)
    expected = bytes(range(104))[: position * 52] + bytes(range(170, 222))
    expected += bytes(range(104))[position * 52 :]
    assert inserted == begin + position * 52
    assert h.memory.read_bytes(begin, 156) == expected
    assert h.memory.read(vector + 8, 8) == begin + 156
    assert h.memory.read(vector + 16, 8) == begin + 208
    assert h.calls("call", 0x1402A94D0) == [(208,)]
    assert h.calls("import", 0x142D6BAB4) == [(old, 156)]
    with pytest.raises(ReplayMemoryError, match="unmapped"):
        h.memory.read(old, 1)
    copy_events = [
        (event[0], event[1], event[2])
        for event in h.events
        if (event[0] == "read" and row <= event[1] < row + 52)
        or (event[0] == "write" and inserted <= event[1] < inserted + 52)
    ]
    assert copy_events == [
        item
        for offset, width in ((0, 16), (16, 16), (32, 16), (48, 4))
        for item in [("read", row + offset, width), ("write", inserted + offset, width)]
    ]


def test_growth52_source_after_allocation_and_interleaved_overlap_not_eager_snapshot():
    h = Harness()
    vector = h.header()
    row = source(h, bytes(range(104)))

    def allocate(_args):
        h.memory.write_bytes(row, bytes(range(200, 216)))
        return row + 16

    h.overrides[0x1402A94D0] = allocate
    inserted = h.invoke(0x140CEDD60, vector, 0, row)
    assert inserted == row + 16
    assert h.memory.read_bytes(inserted, 52) == bytes(range(200, 216)) * 3 + bytes(range(200, 204))


def test_growth52_nonmultiple_position_truncates_index_but_moves_exact_byte_ranges():
    h = Harness()
    old = source(h, b"A" * 52 + b"B" * 52)
    vector = h.header(old, old + 104, old + 104)
    row = source(h, b"N" * 52)
    inserted = h.invoke(0x140CEDD60, vector, old + 53, row)
    begin = h.memory.read(vector, 8)
    assert inserted == begin + 52  # Signed magic division truncates53/52 to1.
    assert h.calls("import", 0x142D6E3DB) == [(begin, old, 53), (begin + 104, old + 53, 51)]
    assert h.memory.read_bytes(begin, 155) == b"A" * 52 + b"B" + b"N" * 51 + b"B" * 51
    with pytest.raises(ReplayMemoryError, match="undefined"):
        h.memory.read(begin + 155, 1)
    assert h.memory.read(vector + 8, 8) == begin + 156


def test_append_missing_commit_refuses_after_actual_allocation_payload_and_zero_move():
    h = Harness()
    vector = h.header()
    value = source(h, (99).to_bytes(4, "little"))
    allocation = []

    def missing_commit(args):
        allocation.append(args[1])
        assert h.memory.read(args[1], 4) == 99
        raise UnresolvedReplayTaskRebuild("actual commit unavailable")

    h.overrides[0x1402BA840] = missing_commit
    with pytest.raises(UnresolvedReplayTaskRebuild, match="actual commit unavailable"):
        h.invoke(0x1402B89C0, vector, value)
    assert h.calls("import", 0x142D6E3DB) == [(allocation[0], 0, 0)]
    assert h.memory.read_bytes(vector, 24) == bytes(24)
    assert h.memory.read(allocation[0], 4) == 99


def test_growth52_held_count_and_reload_end_after_first_move():
    h = Harness()
    old = source(h, b"A" * 52 + b"B" * 52 + b"C" * 52)
    vector = h.header(old, old + 104, old + 156)
    row = source(h, b"N" * 52)
    moves = []

    def move(args):
        moves.append(args)
        result = h.memory.move(*args)
        if len(moves) == 1:
            h.memory.write(vector + 8, 8, old + 156)
        return result

    h.overrides[0x142D6E3DB] = move
    inserted = h.invoke(0x140CEDD60, vector, old + 52, row)
    begin = h.memory.read(vector, 8)
    assert inserted == begin + 52
    assert moves == [(begin, old, 52), (begin + 104, old + 52, 104)]
    assert h.memory.read_bytes(begin, 208) == b"A" * 52 + b"N" * 52 + b"B" * 52 + b"C" * 52
    assert h.memory.read(vector + 8, 8) == begin + 156  # Pre-allocation used+1 is held.


def test_growth52_current_end_before_begin_can_force_split_after_allocator():
    h = Harness()
    old = source(h, b"A" * 52 + b"B" * 52 + b"C" * 52)
    vector = h.header(old, old + 104, old + 156)
    row = source(h, b"N" * 52)

    def allocate(args):
        result = h.memory.allocate_aligned(args[0])
        h.memory.write(vector + 8, 8, old + 156)
        return result

    h.overrides[0x1402A94D0] = allocate
    h.invoke(0x140CEDD60, vector, old + 104, row)
    begin = h.memory.read(vector, 8)
    assert h.calls("import", 0x142D6E3DB) == [(begin, old, 104), (begin + 156, old + 104, 52)]
    fields = [
        event[1]
        for event in h.events
        if event[0] == "read" and event[1] in (vector, vector + 8, vector + 16)
    ]
    assert fields == [
        vector,
        vector + 8,
        vector + 16,
        vector + 8,
        vector,
        vector + 8,
        vector,
        vector + 16,
    ]
    assert h.memory.read_bytes(begin, 208) == b"A" * 52 + b"B" * 52 + b"N" * 52 + b"C" * 52


def test_growth52_undefined_later_chunk_preserves_prior_writes_and_allocated_backing():
    h = Harness()
    vector = h.header()
    row = h.memory.allocate(52)
    h.memory.write_bytes(row, b"R" * 32)
    allocations = []

    def allocate(args):
        result = h.memory.allocate_aligned(args[0])
        allocations.append(result)
        return result

    h.overrides[0x1402A94D0] = allocate
    with pytest.raises(ReplayMemoryError, match="undefined"):
        h.invoke(0x140CEDD60, vector, 0, row)
    assert h.memory.read_bytes(allocations[0], 32) == b"R" * 32
    with pytest.raises(ReplayMemoryError, match="undefined"):
        h.memory.read(allocations[0] + 32, 16)
    assert h.memory.read_bytes(vector, 24) == bytes(24)
    assert not h.calls("import", 0x142D6E3DB)


@pytest.mark.parametrize("target,width", [(0x1402B89C0, 4), (0x140CEDD60, 52)])
def test_null_allocator_is_not_success_and_preserves_its_effect(target, width):
    h = Harness()
    vector = h.header()
    row = source(h, bytes(width))

    def allocate(_args):
        h.memory.write(row, 1, 0xA5)
        return 0

    h.overrides[0x1402A94D0] = allocate
    with pytest.raises(ReplayMemoryError, match="unmapped"):
        h.invoke(target, vector, *(() if width == 4 else (0,)), row)
    assert h.memory.read(row, 1) == 0xA5
    assert h.memory.read_bytes(vector, 24) == bytes(24)


@pytest.mark.parametrize("returns", [False, True])
def test_reachable_growth52_capacity_error_before_allocation_or_source(returns):
    h = Harness()
    vector = h.header(0x1000, 0x1000 - 104, 0x1000)
    if returns:
        h.overrides[0x1402A9460] = lambda _args: 7
    expected = UnresolvedReplayTaskRebuild if returns else ReplayMemoryRuntimeError
    with pytest.raises(expected):
        h.invoke(0x140CEDD60, vector, 0x1000, 0xDEAD)
    assert h.calls("call", 0x1402A9460) == [()]
    assert not h.calls("call", 0x1402A94D0)
    assert not [event for event in h.events if event[0] == "write"]


@pytest.mark.parametrize("target,width", [(0x1402B89C0, 4), (0x140CEDD60, 52)])
def test_negative_capacity_saturates_then_reaches_actual_allocator_overflow(target, width):
    h = Harness()
    vector = h.header(0x1000, 0x1000 - width if width == 4 else 0x1000, 0x1000 - width)
    with pytest.raises(ReplayMemoryRuntimeError) as error:
        h.invoke(target, vector, *(() if width == 4 else (0x1000,)), 0xDEAD)
    assert error.value.target == 0x1402A9460
    maximum = U64 // width
    assert h.calls("call", 0x1402A94D0) == [(maximum * width,)]


@pytest.mark.parametrize("count,capacity", [(0, 0), (2, 3), (U64, U64)])
def test_commit_null_skips_old_capacity_and_uses_held_wrapping_values(count, capacity):
    h = Harness()
    vector = h.memory.allocate(24)
    h.memory.write(vector, 8, 0)
    allocation = U64 - 20
    assert (
        h.invoke(0x140CF3320, vector, allocation, count, capacity)
        == (allocation + capacity * 52) & U64
    )
    assert h.memory.read(vector + 8, 8) == (allocation + count * 52) & U64
    assert [event[1:3] for event in h.events if event[0] == "read"] == [(vector, 8)]
    assert [event[1] for event in h.events if event[0] == "write"] == [
        vector,
        vector + 8,
        vector + 16,
    ]


def test_commit_held_begin_current_capacity_and_free_before_ordered_commits():
    h = Harness()
    old, alternate, new = (h.memory.allocate(128) for _ in range(3))
    vector = h.header(old, old + 52, old + 105)  # Truncating52 quotient gives104 size.

    def after_read(address, width):
        if (address, width) == (vector + 16, 8):
            h.memory.write(vector, 8, alternate)

    def free(args):
        assert args == (old, 104)
        assert h.memory.read(vector, 8) == alternate
        h.memory.free(args[0])
        h.memory.write_bytes(vector, b"X" * 24)

    h.after_read = after_read
    h.overrides[0x142D6BAB4] = free
    assert h.invoke(0x140CF3320, vector, new, 1, 2) == new + 104
    assert h.memory.read_bytes(vector, 24) == b"".join(
        item.to_bytes(8, "little") for item in (new, new + 52, new + 104)
    )
    with pytest.raises(ReplayMemoryError, match="undefined"):
        h.memory.read(alternate, 1)


def test_commit_large_real_allocation_releases_actual_header_base():
    h = Harness()
    old = h.memory.allocate_aligned(80 * 52)
    raw = h.memory.read(old - 8, 8)
    vector = h.header(old, old, old + 80 * 52)
    assert h.invoke(0x140CF3320, vector, 0xAA, 1, 3) == 0xAA + 156
    assert h.calls("import", 0x142D6BAB4) == [(raw, 80 * 52 + 0x27)]
    with pytest.raises(ReplayMemoryError, match="unmapped"):
        h.memory.read(raw, 1)


@pytest.mark.parametrize("direct", [False, True])
def test_watson_reads_current_target_once_and_terminal_alias_bypasses_owned_body(direct):
    h = Harness()
    backing = h.memory.allocate(5000)
    begin = backing + 40
    h.memory.write(begin - 8, 8, begin - 40)  # Gap32 is invalid.
    vector = h.header(begin, begin, begin + 4160)
    h.memory.map_bytes(0x14319A060, (0x1402B89C0).to_bytes(8, "little"))

    def watson(args):
        assert args == (0, 0, 0, 0, 0)
        h.memory.write(backing, 1, 0xAA)
        return 5

    def current_after_read(address, width):
        if (address, width) == (0x14319A060, 8):
            h.memory.write(address, 8, 0xBAD)

    h.overrides[0x1402B89C0] = watson
    h.after_read = current_after_read
    with pytest.raises(UnresolvedReplayTaskRebuild, match="returned to INT3"):
        if direct:
            commit_replay_unit_ai_rows(
                h.context,
                vector,
                0xAA,
                1,
                2,
                calls=h.ordinary,
                imports=ReplayTaskRebuildCalls(h.imported),
            )
        else:
            h.invoke(0x140CF3320, vector, 0xAA, 1, 2)
    assert h.calls("import", 0x1402B89C0) == [(0, 0, 0, 0, 0)]
    assert len([event for event in h.events if event[:3] == ("read", 0x14319A060, 8)]) == 1
    assert h.memory.read(vector, 8) == begin
    assert h.memory.read(backing, 1) == 0xAA


def test_invalid_large_header_requires_reached_iat_before_any_free_or_commit():
    h = Harness()
    raw = source(h, bytes(5000))
    begin = raw + 40
    h.memory.write(begin - 8, 8, raw)
    vector = h.header(begin, begin, begin + 4160)
    with pytest.raises(ReplayMemoryError, match="14319a060"):
        h.invoke(0x140CF3320, vector, 0, 0, 0)
    assert not h.calls("import", 0x142D6BAB4)
    assert h.memory.read(vector, 8) == begin


def test_free_failure_and_late_header_write_failure_keep_prior_effects():
    h = Harness()
    old = source(h, bytes(104))
    vector = h.header(old, old, old + 104)

    def fail(args):
        h.memory.write(old, 1, 0xAA)
        raise RuntimeError("free failed")

    h.overrides[0x142D6BAB4] = fail
    with pytest.raises(RuntimeError, match="free failed"):
        h.invoke(0x140CF3320, vector, 0xAA, 2, 2)
    assert h.memory.read(vector, 8) == old and h.memory.read(old, 1) == 0xAA
    header = 0x5000
    for offset, value, writable in ((0, 0, True), (8, 0xBBBB, False), (16, 0xCCCC, True)):
        h.memory.map_bytes(header + offset, value.to_bytes(8, "little"), writable=writable)
    with pytest.raises(ReplayMemoryError, match="readonly"):
        h.invoke(0x140CF3320, header, 0xAA, 2, 2)
    assert h.memory.read(header, 8) == 0xAA
    assert h.memory.read(header + 8, 8) == 0xBBBB
    assert h.memory.read(header + 16, 8) == 0xCCCC


@pytest.mark.parametrize("target", [0x142D6BAB4, 0x142D6C90C, 0x142D6E47D])
@pytest.mark.parametrize("with_size", [False, True])
def test_genuine_free_jump_chain_forwards_effective_arity_and_ignores_size(target, with_size):
    h = Harness()
    pointer = h.memory.allocate(1)
    args = (pointer, U64) if with_size else (pointer,)
    assert h.invoke(target, *args) is None
    assert h.calls("import", 0x142D6BAB4) == [args]
    with pytest.raises(ReplayMemoryError, match="unmapped"):
        h.memory.read(pointer, 1)


@pytest.mark.parametrize(
    "target,iat,args",
    [
        (0x142D6E3DB, 0x1431999A0, (1, 2, 0)),
        (0x142D6BAB4, 0x143199DD0, (0, 5)),
    ],
)
def test_import_alias_current_routing_and_default_terminal(target, iat, args):
    h = Harness()
    h.memory.write(iat, 8, 0x140CF3320)
    calls = []

    def terminal(selected, actual, data):
        calls.append((selected, actual, data))
        return 0xA5

    delegate = ReplayTaskRebuildCalls(terminal)
    for binder in (
        bind_replay_unit_ai_vector_growth(h.context, delegate),
        bind_replay_unit_ai_vector_growth(
            h.context, ReplayTaskRebuildCalls(None), imports=delegate
        ),
    ):
        assert binder.call is not None
        assert binder.call(target, args, None) == 0xA5
    assert calls == [(0x140CF3320, args, None)] * 2


@pytest.mark.parametrize(
    "target,args,data",
    [
        (0x1402B89C0, (), None),
        (0x140CEDD60, (1, 2), None),
        (0x140CF3320, (1, 2, 3), None),
        (0x142D6E3DB, (1, 2, 3), memoryview(bytearray())),
        (0x142D6BAB4, (), None),
        (0x1402B89C0, (True, 2), None),
        (0x140CEDD60, (1, 2, -1), None),
        (0x140CF3320, (1, 2, 3, 1 << 64), None),
    ],
)
def test_binding_refuses_malformed_known_calls_before_storage(target, args, data):
    h = Harness()
    assert h.bound.call is not None
    with pytest.raises(ValueError):
        h.bound.call(target, args, data)
    assert not h.events


def test_unknown_delegate_and_unavailable_current_children_refuse_at_reach():
    h = Harness()
    data = memoryview(bytearray(b"live"))
    received = []

    def delegate(target, args, current):
        received.append((target, args, current))
        raise UnresolvedReplayTaskRebuild("unknown actual child")

    calls = bind_replay_unit_ai_vector_growth(h.context, ReplayTaskRebuildCalls(delegate))
    assert calls.call is not None
    with pytest.raises(UnresolvedReplayTaskRebuild):
        calls.call(0xABC, (1, 2), data)
    assert received == [(0xABC, (1, 2), data)]
    vector = h.header()
    row = source(h, bytes(52))
    with pytest.raises(UnresolvedReplayTaskRebuild, match="1402a94d0"):
        grow_replay_unit_ai_rows(h.context, vector, 0, row, calls=ReplayTaskRebuildCalls(None))
    with pytest.raises(UnresolvedReplayTaskRebuild, match="1402a94d0"):
        append_replay_unit_ai_class(h.context, vector, row, calls=ReplayTaskRebuildCalls(None))
