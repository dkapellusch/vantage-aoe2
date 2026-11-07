"""Source-derived shared-pair controls over owned storage and real atomics."""

from __future__ import annotations

import pytest

from vantage.replay_memory import ReplayMemory, ReplayMemoryError
from vantage.replay_saved_pair import assign_replay_saved_pair, bind_replay_saved_pair
from vantage.replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
)
from vantage.replay_unit_ai_map import ReplayUnitAIMapAtomics

ENTRY, DESTROY, DELETE, REPLACEMENT = 0x14090D270, 0xD1, 0xD2, 0xD3
U32, U64 = 0xFFFFFFFF, 0xFFFFFFFFFFFFFFFF


class Harness:
    def __init__(self):
        self.memory = ReplayMemory()
        self.events = []
        self.after_read = lambda address, width, value: None
        self.after_atomic = lambda address, addend, previous: None
        self.before_write = lambda address, width, value: None
        self.on_call = lambda target, args, data: None
        self.context = ReplayTaskRebuildStorage(1, self.read, self.write)
        self.atomics = ReplayUnitAIMapAtomics(None, self.atomic)
        self.calls = ReplayTaskRebuildCalls(self.call)

    def read(self, address, width):
        value = self.memory.read(address, width)
        self.events.append(("read", address, width, value))
        self.after_read(address, width, value)
        return value

    def write(self, address, width, value):
        self.events.append(("write", address, width, value))
        self.before_write(address, width, value)
        self.memory.write(address, width, value)

    def atomic(self, address, addend):
        previous = self.memory.fetch_add_u32(address, addend)
        self.events.append(("atomic", address, addend, previous))
        self.after_atomic(address, addend, previous)
        return previous

    def call(self, target, args, data):
        self.events.append(("call", target, args, data))
        return self.on_call(target, args, data)

    def pair(self, status=0, control=0):
        block = self.memory.allocate(48)
        self.memory.write_bytes(block, b"\xa5" * 48)
        address = block + 16
        self.memory.write(address, 8, status)
        self.memory.write(address + 8, 8, control)
        return address

    def control(self, strong=1, weak=1):
        control = self.memory.allocate(32)
        table = self.memory.allocate(16)
        self.memory.write_bytes(control, b"\xcc" * 32)
        for address, width, value in (
            (control, 8, table),
            (control + 8, 4, strong),
            (control + 12, 4, weak),
            (table, 8, DESTROY),
            (table + 8, 8, DELETE),
        ):
            self.memory.write(address, width, value)
        return control, table

    def run(self, destination, source, *, bound=False, calls=None, atomics=None):
        calls = self.calls if calls is None else calls
        atomics = self.atomics if atomics is None else atomics
        if bound:
            actual = bind_replay_saved_pair(self.context, calls, atomics=atomics)
            assert actual.call is not None
            return actual.call(ENTRY, (destination, source), None)
        return assign_replay_saved_pair(
            self.context, destination, source, calls=calls, atomics=atomics
        )


@pytest.mark.parametrize("bound", [False, True])
@pytest.mark.parametrize("word", [0, 1, 0x8000000000000000, U64])
def test_null_controls_exact_order_guards_and_held_return(bound, word) -> None:
    h = Harness()
    destination, source = h.pair(0x777), h.pair(word)
    before = h.memory.snapshot()
    assert h.run(destination, source, bound=bound) == destination
    assert h.events == [
        ("read", source + 8, 8, 0),
        ("read", destination + 8, 8, 0),
        ("read", source + 8, 8, 0),
        ("read", source, 8, word),
        ("write", destination, 8, word),
        ("write", destination + 8, 8, 0),
    ]
    assert h.memory.read_bytes(destination - 16, 16) == b"\xa5" * 16
    assert h.memory.read_bytes(destination + 16, 16) == b"\xa5" * 16
    assert h.memory.read_bytes(source - 16, 48) == before.regions[1].data
    assert all(set(region.defined) == {1} for region in h.memory.snapshot().regions)


@pytest.mark.parametrize("strong", [0, 2, 0x80000000, U32])
def test_old_strong_nonone_wraps_and_skips_virtuals_and_weak(strong) -> None:
    h = Harness()
    control, _ = h.control(strong, 3)
    destination, source = h.pair(1, control), h.pair(2)
    before = h.memory.read_bytes(control, 32)
    h.run(destination, source)
    expected = bytearray(before)
    expected[8:12] = ((strong - 1) & U32).to_bytes(4, "little")
    assert h.memory.read_bytes(control, 32) == expected
    assert h.events[-1] == ("atomic", control + 8, U32, strong)
    assert not any(event[0] == "call" for event in h.events)


@pytest.mark.parametrize("weak", [0, 1, 2, U32])
@pytest.mark.parametrize("bound", [False, True])
def test_last_strong_releases_and_only_last_weak_deletes(weak, bound) -> None:
    h = Harness()
    control, table = h.control(1, weak)
    destination, source = h.pair(1, control), h.pair(2)
    assert h.run(destination, source, bound=bound) == destination
    expected = [
        ("atomic", control + 8, U32, 1),
        ("read", control, 8, table),
        ("read", table, 8, DESTROY),
        ("call", DESTROY, (control,), None),
        ("atomic", control + 12, U32, weak),
    ]
    if weak == 1:
        expected += [
            ("read", control, 8, table),
            ("read", table + 8, 8, DELETE),
            ("call", DELETE, (control,), None),
        ]
    assert h.events[6:] == expected
    assert h.memory.read(control + 8, 4) == 0
    assert h.memory.read(control + 12, 4) == (weak - 1) & U32


@pytest.mark.parametrize("strong", [0, 1, U32])
def test_source_increment_wraps_before_later_reads(strong) -> None:
    h = Harness()
    control, _ = h.control(strong, 8)
    destination, source = h.pair(), h.pair(0x123, control)
    h.run(destination, source)
    assert h.events[:3] == [
        ("read", source + 8, 8, control),
        ("atomic", control + 8, 1, strong),
        ("read", destination + 8, 8, 0),
    ]
    assert h.memory.read(control + 8, 4) == (strong + 1) & U32
    assert h.memory.read(destination + 8, 8) == control


@pytest.mark.parametrize("bound", [False, True])
def test_self_assignment_still_increments_copies_and_releases(bound) -> None:
    h = Harness()
    control, _ = h.control(1, 4)
    pair = h.pair(0x345, control)
    before = h.memory.snapshot()
    assert h.run(pair, pair, bound=bound) == pair
    assert h.memory.snapshot() == before
    assert [event for event in h.events if event[0] == "atomic"] == [
        ("atomic", control + 8, 1, 1),
        ("atomic", control + 8, U32, 2),
    ]
    assert len([event for event in h.events if event[0] == "write"]) == 2


@pytest.mark.parametrize("offset", [-8, 8])
def test_partial_pair_overlap_holds_source_words_before_writes(offset) -> None:
    h = Harness()
    block = h.memory.allocate(64)
    h.memory.write_bytes(block, bytes(64))
    source = block + 24
    destination = source + offset
    status = 0 if offset == -8 else 0x123
    h.memory.write(source, 8, status)
    assert h.run(destination, source) == destination
    assert h.memory.read(destination, 8) == status
    assert h.memory.read(destination + 8, 8) == 0
    assert h.events[:4] == [
        ("read", source + 8, 8, 0),
        ("read", destination + 8, 8, 0),
        ("read", source + 8, 8, 0),
        ("read", source, 8, status),
    ]


def test_increment_mutations_are_seen_by_destination_and_source_rereads() -> None:
    h = Harness()
    acquired, _ = h.control(4, 2)
    copied, _ = h.control(8, 2)
    released, _ = h.control(3, 2)
    destination, source = h.pair(), h.pair(1, acquired)

    def mutate(address, addend, previous):
        if address == acquired + 8:
            h.memory.write(source + 8, 8, copied)
            h.memory.write(source, 8, 0xBEEF)
            h.memory.write(destination + 8, 8, released)

    h.after_atomic = mutate
    h.run(destination, source)
    assert h.memory.read(destination, 8) == 0xBEEF
    assert h.memory.read(destination + 8, 8) == copied
    assert h.memory.read(acquired + 8, 4) == 5
    assert h.memory.read(copied + 8, 4) == 8
    assert h.memory.read(released + 8, 4) == 2


def test_initial_null_control_does_not_increment_later_nonnull_control() -> None:
    h = Harness()
    later, _ = h.control(7, 8)
    destination, source = h.pair(), h.pair(4)

    def mutate(address, width, value):
        if address == destination + 8:
            h.memory.write(source + 8, 8, later)

    h.after_read = mutate
    h.run(destination, source)
    assert h.memory.read(destination + 8, 8) == later
    assert h.memory.read(later + 8, 4) == 7
    assert not any(event[0] == "atomic" for event in h.events)


def test_old_control_and_second_source_control_remain_held_across_later_reads() -> None:
    h = Harness()
    old, _ = h.control(3, 9)
    replacement, _ = h.control(7, 9)
    destination, source = h.pair(0, old), h.pair(0xBAD)

    def mutate(address, width, value):
        if address == destination + 8:
            h.memory.write(destination + 8, 8, replacement)
        if address == source:
            h.memory.write(source + 8, 8, replacement)
            h.memory.write(source, 8, 0xBEEF)

    h.after_read = mutate
    h.run(destination, source)
    assert h.memory.read(destination, 8) == 0xBAD
    assert h.memory.read(destination + 8, 8) == 0
    assert h.memory.read(old + 8, 4) == 2
    assert h.memory.read(replacement + 8, 4) == 7


def test_release_reads_current_virtual_after_strong_atomic_effect() -> None:
    h = Harness()
    old, _ = h.control(1, 2)
    current_table = h.memory.allocate(16)
    h.memory.write_bytes(current_table, bytes(16))
    h.memory.write(current_table, 8, REPLACEMENT)
    destination, source = h.pair(1, old), h.pair(2)

    def mutate(address, addend, previous):
        if address == old + 8:
            h.memory.write(old, 8, current_table)

    h.after_atomic = mutate
    h.run(destination, source)
    assert [event for event in h.events if event[0] == "call"] == [
        ("call", REPLACEMENT, (old,), None),
    ]
    assert h.memory.read(old + 12, 4) == 1


def test_first_virtual_mutation_refreshes_weak_and_virtual_table_but_holds_control() -> None:
    h = Harness()
    old, _ = h.control(1, 9)
    replacement, _ = h.control(8, 8)
    new_table = h.memory.allocate(16)
    h.memory.write_bytes(new_table, bytes(16))
    h.memory.write(new_table + 8, 8, REPLACEMENT)
    destination, source = h.pair(1, old), h.pair(2)

    def mutate(target, args, data):
        if target == DESTROY:
            assert h.memory.read(destination, 8) == 2
            assert h.memory.read(destination + 8, 8) == 0
            h.memory.write(old, 8, new_table)
            h.memory.write(old + 12, 4, 1)
            h.memory.write(destination + 8, 8, replacement)
            h.memory.write(source, 8, 0xEEEE)
        else:
            assert target == REPLACEMENT and args == (old,)

    h.on_call = mutate
    assert h.run(destination, source, bound=True) == destination
    assert [e[1] for e in h.events if e[0] == "call"] == [DESTROY, REPLACEMENT]
    assert h.memory.read(old + 12, 4) == 0
    assert h.memory.read(replacement + 12, 4) == 8
    assert h.memory.read(destination + 8, 8) == replacement


@pytest.mark.parametrize("phase", ["destroy", "delete"])
def test_virtual_failure_keeps_copy_counts_and_actual_callback_writes(phase) -> None:
    h = Harness()
    old, _ = h.control()
    destination, source = h.pair(1, old), h.pair(2)

    def fail(target, args, data):
        if target == (DESTROY if phase == "destroy" else DELETE):
            h.memory.write(destination, 8, 0x1234)
            raise RuntimeError(phase)

    h.on_call = fail
    with pytest.raises(RuntimeError, match=phase):
        h.run(destination, source)
    assert h.memory.read(destination, 8) == 0x1234
    assert h.memory.read(destination + 8, 8) == 0
    assert h.memory.read(old + 8, 4) == 0
    assert h.memory.read(old + 12, 4) == (1 if phase == "destroy" else 0)


def test_missing_virtual_refuses_after_copy_and_strong_decrement() -> None:
    h = Harness()
    old, _ = h.control()
    destination, source = h.pair(1, old), h.pair(2)
    with pytest.raises(UnresolvedReplayTaskRebuild):
        h.run(destination, source, calls=ReplayTaskRebuildCalls(None))
    assert h.memory.read(destination, 8) == 2
    assert h.memory.read(destination + 8, 8) == 0
    assert h.memory.read(old + 8, 4) == 0
    assert h.memory.read(old + 12, 4) == 1


def test_missing_increment_binding_refuses_before_destination_access() -> None:
    h = Harness()
    control, _ = h.control()
    destination, source = h.pair(), h.pair(7, control)
    before = h.memory.snapshot()
    with pytest.raises(UnresolvedReplayTaskRebuild):
        h.run(destination, source, atomics=ReplayUnitAIMapAtomics(None, None))
    assert h.events == [("read", source + 8, 8, control)]
    assert h.memory.snapshot() == before


def test_missing_release_binding_retains_completed_pair_stores() -> None:
    h = Harness()
    control, _ = h.control()
    destination, source = h.pair(1, control), h.pair(2)
    with pytest.raises(UnresolvedReplayTaskRebuild):
        h.run(destination, source, atomics=ReplayUnitAIMapAtomics(None, None))
    assert h.memory.read(destination, 8) == 2
    assert h.memory.read(destination + 8, 8) == 0
    assert h.memory.read(control + 8, 4) == 1


def test_second_store_failure_preserves_first_store_and_increment_without_release() -> None:
    h = Harness()
    new, _ = h.control(2, 8)
    old, _ = h.control(1, 8)
    destination, source = h.pair(1, old), h.pair(2, new)

    def fail(address, width, value):
        if address == destination + 8:
            raise RuntimeError("second store")

    h.before_write = fail
    with pytest.raises(RuntimeError, match="second store"):
        h.run(destination, source)
    assert h.memory.read(destination, 8) == 2
    assert h.memory.read(destination + 8, 8) == old
    assert h.memory.read(new + 8, 4) == 3
    assert h.memory.read(old + 8, 4) == 1


def test_undefined_status_refuses_after_increment_and_control_reads_before_any_copy() -> None:
    h = Harness()
    control, _ = h.control(2, 9)
    source = h.memory.allocate(16)
    h.memory.write(source + 8, 8, control)
    destination = h.pair(1)
    with pytest.raises(ReplayMemoryError, match="undefined"):
        h.run(destination, source)
    assert h.memory.read(control + 8, 4) == 3
    assert h.memory.read(destination, 8) == 1
    assert not any(event[0] == "write" for event in h.events)


def test_undefined_destination_status_becomes_defined_without_reading_it() -> None:
    h = Harness()
    destination = h.memory.allocate(24)
    h.memory.write(destination + 8, 8, 0)
    source = h.pair(U64)
    h.run(destination, source)
    assert h.memory.read(destination, 8) == U64
    region = next(r for r in h.memory.snapshot().regions if r.address == destination)
    assert region.defined == b"\x01" * 16 + bytes(8)


def test_readonly_destination_failure_does_not_undo_source_increment() -> None:
    h = Harness()
    control, _ = h.control(2, 9)
    source = h.pair(2, control)
    destination = 0x4000
    h.memory.map_bytes(destination, bytes(16), writable=False)
    with pytest.raises(ReplayMemoryError, match="readonly"):
        h.run(destination, source)
    assert h.memory.read(control + 8, 4) == 3
    assert h.memory.read(destination, 8) == 0


@pytest.mark.parametrize(
    "args,data",
    [
        ((), None),
        ((1,), None),
        ((1, 2, 3), None),
        ((1, 2), memoryview(bytearray())),
        ((True, 2), None),
        ((1, -1), None),
        ((1, U64 + 1), None),
    ],
)
def test_bound_admission_refuses_before_storage_or_atomic_access(args, data) -> None:
    h = Harness()
    bound = bind_replay_saved_pair(h.context, h.calls, atomics=h.atomics)
    assert bound.call is not None
    with pytest.raises(ValueError):
        bound.call(ENTRY, args, data)
    assert h.events == []


def test_unknown_delegate_keeps_original_live_view_arguments_and_return() -> None:
    h = Harness()
    data = memoryview(bytearray(b"abc"))

    def delegate(target, args, actual):
        assert target == 0xABC and args == (U64, 3) and actual is data
        actual[1] = 0xEE
        return 0x8000000000000001

    h.on_call = delegate
    bound = bind_replay_saved_pair(h.context, h.calls, atomics=h.atomics)
    assert bound.call is not None
    assert bound.call(0xABC, (U64, 3), data) == 0x8000000000000001
    assert data.tobytes() == b"a\xeec"
    assert h.events == [("call", 0xABC, (U64, 3), data)]


def test_unknown_without_delegate_refuses_and_null_controls_need_no_provider() -> None:
    h = Harness()
    empty = ReplayTaskRebuildCalls(None)
    unavailable = ReplayUnitAIMapAtomics(None, None)
    destination, source = h.pair(), h.pair(9)
    bound = bind_replay_saved_pair(h.context, empty, atomics=unavailable)
    assert bound.call is not None
    assert bound.call(ENTRY, (destination, source), None) == destination
    with pytest.raises(UnresolvedReplayTaskRebuild):
        bound.call(0xABC, (), None)


@pytest.mark.parametrize("where", ["direct", "binder"])
def test_invalid_atomic_context_is_rejected_before_access(where) -> None:
    h = Harness()
    with pytest.raises(ValueError, match="shared-count"):
        if where == "direct":
            h.run(1, 2, atomics=object())
        else:
            bind_replay_saved_pair(h.context, h.calls, atomics=object())
    assert h.events == []
