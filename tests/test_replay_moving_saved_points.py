"""Owned point-buffer effects with real lower alias/current-IAT/CRT bindings.

These are source-led logical Python caller tests, not native executions. Runtime
allocation/free effects are real owned Memory; callbacks explicitly mutate that
storage to audit current/held fields and partial failures. No full restore claim.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from vantage.replay_memory import ReplayMemory, ReplayMemoryError
from vantage.replay_moving_saved_points import (
    bind_replay_moving_saved_points,
    resize_replay_saved_moving_points,
)
from vantage.replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
)
from vantage.replay_unit_constructor_support import bind_replay_unit_constructor_support
from vantage.replay_zone_queue import bind_replay_zone_queue

ENTRY, ALLOCATE, ALIAS_ALLOCATE, ALIAS_FREE = (
    0x14121A010,
    0x142D6BA78,
    0x142D6C268,
    0x142D6C270,
)
FREE, FREE2, U32, U64 = 0xFA01, 0xFA02, (1 << 32) - 1, (1 << 64) - 1
RECORDS = (
    bytes.fromhex("01000080ff7f00000000807f"),
    bytes.fromhex("3412c07f0000008000000000"),
    bytes.fromhex("0100807f000080ff3412807f"),
    bytes.fromhex("112233445566778899aabbcc"),
    bytes.fromhex("a1a2a3a4a5a6a7a8b1b2b3b4"),
)


def setup(
    *,
    records=None,
    capacity=0,
    count=None,
    lower="constructor",
    before=None,
    after=None,
    on_read=None,
    on_write=None,
    runtime_after=None,
):
    h = SimpleNamespace()
    h.memory = m = ReplayMemory()
    h.subject = m.allocate(0x39C)
    h.old = 0
    if records is not None:
        h.old = m.calloc(1, max(12, len(records) * 12))
        for i, raw in enumerate(records):
            assert len(raw) == 12
            m.write_bytes(h.old + i * 12, raw)
    m.write(h.subject + 0x388, 8, h.old)
    m.write(h.subject + 0x394, 4, (len(records or ()) if count is None else count) & U32)
    m.write(h.subject + 0x398, 4, capacity & U32)
    m.map_bytes(0x143199DD0, FREE.to_bytes(8, "little"))
    h.operations, h.events, h.runtime_events, h.allocations, h.frees = [], [], [], [], []

    def read(pointer, width):
        value = m.read(pointer, width)
        h.operations.append(("read", pointer, width, value))
        if on_read:
            changed = on_read(h, pointer, width, value)
            if changed is not None:
                return changed
        return value

    def write(pointer, width, value):
        h.operations.append(("write", pointer, width, value))
        m.write(pointer, width, value)
        if on_write:
            on_write(h, pointer, width, value)

    h.context = ReplayTaskRebuildStorage(h.subject, read, write)
    runtime = m.runtime_calls()

    def effects(target, args, data):
        h.runtime_events.append((target, args, data))
        assert data is None
        if target in (FREE, FREE2):
            assert len(args) == 1
            h.frees.append(args[0])
            m.free(args[0])
            answer = None
        else:
            assert runtime.call
            answer = runtime.call(target, args, data)
            if target == ALLOCATE:
                h.allocations.append(answer)
        if runtime_after:
            runtime_after(h, target, args, answer)
        return answer

    provider = ReplayTaskRebuildCalls(effects)
    if lower == "constructor":
        real_children = bind_replay_unit_constructor_support(
            h.context,
            provider,
            bind_local=m.bind_local,
            imports=provider,
        )
    else:
        real_children = bind_replay_zone_queue(h.context, provider, imports=provider)

    def call(target, args, data):
        h.events.append((target, args, data))
        if before:
            before(h, target, args)
        assert real_children.call
        answer = real_children.call(target, args, data)
        if after:
            replacement = after(h, target, args, answer)
            if replacement is not None:
                return replacement
        return answer

    h.calls = ReplayTaskRebuildCalls(call)
    h.bound = bind_replay_moving_saved_points(h.context, h.calls)
    return h


def run(h, requested, *, bound=False):
    if bound:
        assert h.bound.call
        return h.bound.call(ENTRY, (h.subject, requested & U64), None)
    return resize_replay_saved_moving_points(
        h.context,
        h.subject,
        requested & U64,
        calls=h.calls,
    )


@pytest.mark.parametrize("bound", [False, True])
@pytest.mark.parametrize("lower", ["constructor", "zone"])
def test_actual_zero_new_buffer_and_capacity_before_pointer(bound, lower):
    h = setup(lower=lower)
    assert run(h, 3, bound=bound) == 1
    allocation = h.allocations[0]
    assert h.memory.read_bytes(allocation, 36) == bytes(36)
    assert h.memory.read(h.subject + 0x398, 4) == 3
    assert h.memory.read(h.subject + 0x388, 8) == allocation
    assert h.memory.read(h.subject + 0x394, 4) == 0
    assert h.events == [(ALIAS_ALLOCATE, (36,), None)]
    assert h.operations[-2:] == [
        ("write", h.subject + 0x398, 4, 3),
        ("write", h.subject + 0x388, 8, allocation),
    ]
    zero = [
        row for row in h.operations if row[0] == "write" and allocation <= row[1] < allocation + 36
    ]
    assert zero == [
        row
        for i in range(3)
        for row in (
            ("write", allocation + i * 12, 8, 0),
            ("write", allocation + i * 12 + 8, 4, 0),
        )
    ]


@pytest.mark.parametrize("requested", [0, -1, -2147483648, 0x1122334480000000, 0xFFFFFFFF00000000])
def test_nonpositive_low_edx_never_reads_subject_or_calls_child(requested):
    h = setup(records=RECORDS[:2], capacity=9)
    assert run(h, requested) == 0
    assert h.operations == [] and h.events == []


@pytest.mark.parametrize("capacity,requested", [(1, 1), (5, 2), (2147483647, 2147483647)])
def test_sufficient_positive_capacity_returns_zero_without_pointer_or_count_read(
    capacity,
    requested,
):
    h = setup(records=RECORDS[:1], capacity=capacity, count=0x80000000)
    assert run(h, requested) == 0
    assert h.operations == [("read", h.subject + 0x398, 4, capacity)]
    assert h.events == []
    assert h.memory.read(h.subject + 0x388, 8) == h.old


@pytest.mark.parametrize("capacity", [0, -1, -2147483648, 1])
def test_capacity_comparisons_are_signed(capacity):
    h = setup(capacity=capacity)
    assert run(h, 2) == 1
    assert h.memory.read(h.subject + 0x398, 4) == 2


def test_upper_requested_bits_ignored_like_movsxd_esi_edx():
    h = setup()
    assert run(h, 0x7FEDCBA900000002) == 1
    assert h.events == [(ALIAS_ALLOCATE, (24,), None)]


@pytest.mark.parametrize(
    "count,copy_records", [(-1, 0), (-2147483648, 0), (0, 0), (1, 1), (2, 2), (3, 3), (5, 3)]
)
def test_copy_bound_by_held_request_and_current_signed_count(count, copy_records):
    h = setup(records=RECORDS, count=count)
    assert run(h, 3) == 1
    expected = b"".join(RECORDS[:copy_records]) + bytes((3 - copy_records) * 12)
    assert h.memory.read_bytes(h.allocations[0], 36) == expected
    assert h.memory.read(h.subject + 0x394, 4) == count & U32
    assert h.frees == [h.old]
    with pytest.raises(ReplayMemoryError):
        h.memory.read(h.old, 8)


def test_count_reloaded_at_next_iteration_after_actual_copy_tail_store():
    def on_write(h, pointer, width, value):
        if h.allocations and pointer == h.allocations[0] + 8 and value:
            h.memory.write(h.subject + 0x394, 4, 1)

    h = setup(records=RECORDS[:3], on_write=on_write)
    run(h, 4)
    assert h.memory.read_bytes(h.allocations[0], 48) == RECORDS[0] + bytes(36)
    assert h.memory.read(h.subject + 0x394, 4) == 1


def test_copy_holds_source_base_across_qword_store_but_tail_is_current():
    def on_write(h, pointer, width, value):
        if h.allocations and pointer == h.allocations[0] and value:
            h.memory.write(h.subject + 0x388, 8, h.alternate)
            h.memory.write(h.old + 8, 4, 0xDEADBEEF)

    h = setup(records=RECORDS[:2], count=2, on_write=on_write)
    h.alternate = h.memory.calloc(1, 24)
    h.memory.write_bytes(h.alternate, RECORDS[3] + RECORDS[4])
    assert run(h, 3) == 1
    expected_first = RECORDS[0][:8] + (0xDEADBEEF).to_bytes(4, "little")
    assert h.memory.read_bytes(h.allocations[0], 36) == expected_first + RECORDS[4] + bytes(12)
    assert h.frees == [h.alternate]
    assert h.memory.read(h.old, 8) == int.from_bytes(RECORDS[0][:8], "little")


def test_zeroing_finishes_before_current_old_pointer_and_count_reads():
    h = setup(records=RECORDS[:1])
    run(h, 2)
    allocation = h.allocations[0]
    first_old_read = next(
        i for i, row in enumerate(h.operations) if row[1:3] == (h.subject + 0x388, 8)
    )
    writes = [row for row in h.operations[:first_old_read] if row[0] == "write"]
    assert writes == [
        ("write", allocation, 8, 0),
        ("write", allocation + 8, 4, 0),
        ("write", allocation + 12, 8, 0),
        ("write", allocation + 20, 4, 0),
    ]


def test_old_pointer_initially_null_never_reads_count_or_calls_free():
    def on_read(h, pointer, width, value):
        if pointer == h.subject + 0x394:
            raise AssertionError("unexpected count read")

    h = setup(count=0xFFFFFFFF, on_read=on_read)
    assert run(h, 1) == 1
    assert h.frees == []


def test_current_old_pointer_reloaded_for_free_even_if_now_null():
    def on_write(h, pointer, width, value):
        if h.allocations and pointer == h.allocations[0] + 8 and value:
            h.memory.write(h.subject + 0x388, 8, 0)

    h = setup(records=RECORDS[:1], on_write=on_write)
    assert run(h, 1) == 1
    assert h.frees == [0]
    assert h.memory.read(h.old, 8) == int.from_bytes(RECORDS[0][:8], "little")


def test_actual_free_target_current_after_copy_callback_and_fields_overwritten_after_free():
    def on_write(h, pointer, width, value):
        if h.allocations and pointer == h.allocations[0] + 8 and value:
            h.memory.write(0x143199DD0, 8, FREE2)

    def runtime_after(h, target, args, answer):
        if target == FREE2:
            h.memory.write(h.subject + 0x398, 4, 99)
            h.memory.write(h.subject + 0x388, 8, 0)

    h = setup(records=RECORDS[:1], on_write=on_write, runtime_after=runtime_after)
    assert run(h, 2) == 1
    assert (FREE2, (h.old,), None) in h.runtime_events
    assert h.memory.read(h.subject + 0x398, 4) == 2
    assert h.memory.read(h.subject + 0x388, 8) == h.allocations[0]


def test_allocator_may_populate_current_old_pointer_before_postzero_check():
    def runtime_after(h, target, args, answer):
        if target == ALLOCATE:
            h.created_old = h.memory.calloc(1, 12)
            h.memory.write_bytes(h.created_old, RECORDS[0])
            h.memory.write(h.subject + 0x388, 8, h.created_old)
            h.memory.write(h.subject + 0x394, 4, 1)

    h = setup(runtime_after=runtime_after)
    run(h, 2)
    assert h.memory.read_bytes(h.allocations[0], 24) == RECORDS[0] + bytes(12)
    assert h.frees == [h.created_old]


def test_null_allocator_profile_returns_zero_without_buffer_or_header_access():
    def after(h, target, args, answer):
        if target == ALIAS_ALLOCATE:
            h.memory.write(h.subject + 0x398, 4, 55)
            return 0

    h = setup(records=RECORDS[:1], after=after)
    assert run(h, 2) == 0
    assert h.operations == [("read", h.subject + 0x398, 4, 0)]
    assert h.memory.read(h.subject + 0x388, 8) == h.old
    assert h.memory.read(h.subject + 0x398, 4) == 55
    assert h.frees == []


def test_allocator_failure_preserves_capacity_read_and_no_object_store():
    def before(h, target, args):
        if target == ALIAS_ALLOCATE:
            raise MemoryError("declared allocation failure")

    h = setup(records=RECORDS[:1], before=before)
    with pytest.raises(MemoryError, match="declared"):
        run(h, 2)
    assert h.operations == [("read", h.subject + 0x398, 4, 0)]
    assert h.allocations == [] and h.frees == []


@pytest.mark.parametrize("stage", ["zero_tail", "copy_tail_read", "free", "capacity_publish"])
def test_partial_failure_keeps_prior_stores_and_never_invents_cleanup(stage):
    def on_write(h, pointer, width, value):
        if stage == "zero_tail" and h.allocations and pointer == h.allocations[0] + 8:
            raise RuntimeError("after zero tail")
        if stage == "capacity_publish" and pointer == h.subject + 0x398:
            raise RuntimeError("after capacity publication")

    def on_read(h, pointer, width, value):
        if stage == "copy_tail_read" and pointer == h.old + 8:
            raise RuntimeError("tail read")

    def before(h, target, args):
        if stage == "free" and target == ALIAS_FREE:
            raise RuntimeError("before free")

    h = setup(records=RECORDS[:1], on_write=on_write, on_read=on_read, before=before)
    with pytest.raises(RuntimeError):
        run(h, 2)
    allocation = h.allocations[0]
    if stage == "zero_tail":
        assert h.memory.read_bytes(allocation, 12) == bytes(12)
        with pytest.raises(ReplayMemoryError):
            h.memory.read(allocation + 12, 8)  # still undefined, no blanket zeroing
    elif stage == "copy_tail_read":
        assert h.memory.read_bytes(allocation, 12) == RECORDS[0][:8] + bytes(4)
    else:
        assert h.memory.read_bytes(allocation, 24) == RECORDS[0] + bytes(12)
    assert h.memory.read(h.subject + 0x388, 8) == h.old
    assert h.memory.read(h.subject + 0x398, 4) == (2 if stage == "capacity_publish" else 0)
    assert h.frees == ([h.old] if stage == "capacity_publish" else [])


def test_max_positive_request_bytecount_is_exact_and_stops_at_actual_allocator():
    def before(h, target, args):
        if target == ALIAS_ALLOCATE:
            assert args == (0x5FFFFFFF4,)
            raise MemoryError("bounded source argument check")

    h = setup(before=before)
    with pytest.raises(MemoryError, match="bounded"):
        run(h, 0x7FFFFFFF)
    assert h.allocations == []


def test_unknown_actual_children_mandatory_on_growth():
    h = setup()
    with pytest.raises(UnresolvedReplayTaskRebuild, match="142d6c268"):
        resize_replay_saved_moving_points(
            h.context,
            h.subject,
            2,
            calls=ReplayTaskRebuildCalls(None),
        )
    assert h.memory.read(h.subject + 0x388, 8) == 0


@pytest.mark.parametrize("args,data", [((1,), None), ((1, 2, 3), None), ((1, 2), memoryview(b"x"))])
def test_actual_binder_strict_arity(args, data):
    h = setup()
    assert h.bound.call
    with pytest.raises(ValueError, match="malformed"):
        h.bound.call(ENTRY, args, data)
    assert h.events == []


def test_unknown_binder_delegates_or_refuses():
    h = setup()
    assert h.bound.call
    with pytest.raises(UnresolvedReplayTaskRebuild, match="unavailable"):
        h.bound.call(0xDEADC0DE, (), None)
    empty = bind_replay_moving_saved_points(h.context, ReplayTaskRebuildCalls(None))
    assert empty.call
    with pytest.raises(UnresolvedReplayTaskRebuild, match="unavailable"):
        empty.call(0xDEADC0DE, (), None)


@pytest.mark.parametrize("requested", [True, -1, 1 << 64, 1.0])
def test_raw_input_width_validation(requested):
    h = setup()
    with pytest.raises(ValueError):
        resize_replay_saved_moving_points(h.context, h.subject, requested, calls=h.calls)
    assert h.events == [] and h.operations == []
