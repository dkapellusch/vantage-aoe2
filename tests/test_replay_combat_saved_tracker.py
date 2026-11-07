"""Source-derived tracker controls using real owned allocation and tree bodies."""

from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from vantage.replay_combat_saved_tracker import (
    ReplayCombatTrackerScratch,
    bind_replay_combat_saved_tracker,
    fail_replay_combat_tracker_length,
    insert_replay_combat_tracker,
    lookup_replay_combat_tracker,
)
from vantage.replay_memory import ReplayMemory, ReplayMemoryError
from vantage.replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
)

LOOKUP, INSERT, LENGTH, MALLOC = 0x1411445A0, 0x14114DB00, 0x1402AB280, 0x142D6BA78
SEED = ReplayCombatTrackerScratch(bytes(range(64)))


def setup(*, after_read=None, after_write=None, before_call=None):
    h = SimpleNamespace()
    h.m = m = ReplayMemory()
    h.header, h.nil, h.key = (m.allocate(n) for n in (16, 40, 4))
    m.write_bytes(h.nil, b"N" * 40)
    for offset in (0, 8, 16):
        m.write(h.nil + offset, 8, h.nil)
    m.write(h.nil + 24, 2, 0x101)
    m.write(h.header, 8, h.nil)
    m.write(h.header + 8, 8, 0)
    h.events, h.frames, h.finished = [], [], []

    def read(address, width):
        value = m.read(address, width)
        h.events.append(("read", address, width, value))
        if after_read:
            after_read(h, address, width, value)
        return value

    def write(address, width, value):
        m.write(address, width, value)
        h.events.append(("write", address, width, value))
        if after_write:
            after_write(h, address, width, value)

    h.context = ReplayTaskRebuildStorage(h.header, read, write)

    @contextmanager
    def local(view):
        with m.bind_local(view) as pointer:
            h.frames.append(pointer)
            try:
                yield pointer
            finally:
                h.finished.append(bytes(view))
                h.frames.pop()

    h.local = local
    runtime = m.runtime_calls()

    def call(target, args, data):
        h.events.append(("call", target, args))
        if before_call:
            returned = before_call(h, target, args)
            if returned is not None:
                return returned
        assert runtime.call
        return runtime.call(target, args, data)

    h.lower = ReplayTaskRebuildCalls(call)
    h.bound = bind_replay_combat_saved_tracker(
        h.context,
        h.lower,
        bind_local=local,
        scratch=SEED,
    )
    return h


def lookup(h, key, *, direct=False):
    h.m.write(h.key, 4, key & 0xFFFFFFFF)
    if direct:
        return lookup_replay_combat_tracker(
            h.context,
            h.header,
            h.key,
            calls=h.bound,
            bind_local=h.local,
            scratch=SEED,
        )
    assert h.bound.call
    return h.bound.call(LOOKUP, (h.header, h.key), None)


def signed(raw):
    return raw if raw < 0x80000000 else raw - (1 << 32)


def check_tree(h):
    m, nil = h.m, h.nil
    root = m.read(nil + 8, 8)
    visited = []

    def descend(node, parent, lower, upper):
        if node == nil:
            return 1
        assert node not in visited
        visited.append(node)
        assert m.read(node + 8, 8) == parent
        key = signed(m.read(node + 28, 4))
        assert lower < key < upper
        left, right = m.read(node, 8), m.read(node + 16, 8)
        if m.read(node + 24, 1) == 0:
            assert m.read(left + 24, 1) == m.read(right + 24, 1) == 1
        a = descend(left, node, lower, key)
        b = descend(right, node, key, upper)
        assert a == b
        return a + m.read(node + 24, 1)

    if root != nil:
        assert m.read(root + 24, 1) == 1
    descend(root, nil, -(1 << 31) - 1, 1 << 31)
    assert len(visited) == m.read(h.header + 8, 8)
    if visited:
        order = sorted(visited, key=lambda p: signed(m.read(p + 28, 4)))
        assert m.read(nil, 8) == order[0]
        assert m.read(nil + 16, 8) == order[-1]
    return visited


@pytest.mark.parametrize(
    "keys,root",
    [
        ([30, 20, 10], 20),
        ([10, 20, 30], 20),
        ([30, 10, 20], 20),
        ([10, 30, 20], 20),
        ([4, 2, 6, 1, 3, 5, 7, 0, 8], 4),
        ([-1, -2147483648, 2147483647, 0, -2], -1),
    ],
)
@pytest.mark.parametrize("direct", [False, True])
def test_real_allocation_balancing_and_duplicate_lookup(keys, root, direct):
    h = setup()
    slots = {}
    for index, key in enumerate(keys):
        slot = lookup(h, key, direct=direct)
        assert slot is not None and h.m.read(slot, 8) == 0
        h.m.write(slot, 8, index + 100)
        slots[key] = slot
        check_tree(h)
    assert signed(h.m.read(h.m.read(h.nil + 8, 8) + 28, 4)) == root
    allocations = len([e for e in h.events if e[:2] == ("call", MALLOC)])
    for key, slot in slots.items():
        assert lookup(h, key) == slot
    assert len([e for e in h.events if e[:2] == ("call", MALLOC)]) == allocations
    assert h.m.read(h.nil + 26, 2) == int.from_bytes(b"NN", "little")


def test_empty_tree_does_not_read_key_until_after_allocator_and_copies_padding():
    def effect(h, target, args):
        if target == MALLOC:
            assert not any(e[:3] == ("read", h.key, 4) for e in h.events)
            h.m.write(h.key, 4, 0x80000000)
            h.m.write(h.frames[-1] + 0x3C, 4, 0xDEADBEEF)

    h = setup(before_call=effect)
    slot = lookup(h, 7)
    assert h.m.read(slot - 4, 4) == 0x80000000
    frame = h.finished[-1]
    assert frame[0x2C:0x30] == bytes.fromhex("efbeadde")
    reads16 = [e for e in h.events if e[0] == "read" and e[2] == 16]
    assert len(reads16) == 1
    assert reads16[0][3] >> 96 == 0xDEADBEEF


def test_key_is_held_during_search_then_reread_for_candidate_comparison():
    h = setup()
    low = lookup(h, 1)
    high = lookup(h, 3)
    mutated = False

    def mutate(h, address, width, value):
        nonlocal mutated
        if address == h.key and not mutated:
            mutated = True
            h.m.write(h.key, 4, 1)

    h2 = h
    # Rebind only the scalar reader; tree and allocator remain real.
    old = h2.context.read

    def read(address, width):
        value = old(address, width)
        mutate(h2, address, width, value)
        return value

    context = ReplayTaskRebuildStorage(h.header, read, h.context.write)
    bound = bind_replay_combat_saved_tracker(context, h.lower, bind_local=h.local, scratch=SEED)
    h.m.write(h.key, 4, 3)
    assert bound.call
    inserted = bound.call(LOOKUP, (h.header, h.key), None)
    assert inserted not in (low, high)
    assert h.m.read(inserted - 4, 4) == 1
    assert h.m.read(h.header + 8, 8) == 3
    # Held3 traverses right; current1>=candidate3 is false, so a new1 is inserted.


def test_allocator_failure_retains_frame_but_no_tree_changes():
    def fail(h, target, args):
        if target == MALLOC:
            raise RuntimeError("owned allocator failure")

    h = setup(before_call=fail)
    with pytest.raises(RuntimeError, match="allocator failure"):
        lookup(h, 9)
    assert h.m.read(h.header + 8, 8) == 0
    assert h.m.read(h.nil + 8, 8) == h.nil
    assert h.finished[-1][0x20:0x28] == h.header.to_bytes(8, "little")
    assert not any(e[0] == "write" and e[1] == h.header + 8 for e in h.events)


def test_null_allocation_is_not_silently_treated_as_empty_or_success():
    h = setup(before_call=lambda h, target, args: 0 if target == MALLOC else None)
    with pytest.raises(ReplayMemoryError):
        lookup(h, 9)
    assert h.m.read(h.header + 8, 8) == 0


def test_new_node_unwritten_padding_stays_undefined_and_limit_is_exact_equality():
    h = setup()
    h.m.write(h.header + 8, 8, 0x0666666666666667)
    slot = lookup(h, 9)
    assert h.m.read(h.header + 8, 8) == 0x0666666666666668
    assert h.m.read(slot - 8, 2) == 1
    with pytest.raises(ReplayMemoryError, match="undefined"):
        h.m.read(slot - 6, 2)


def test_missing_insertion_keeps_allocated_node_but_does_not_publish_it():
    h = setup()

    def direct_children(target, args, data):
        if target == INSERT:
            raise RuntimeError("required insertion missing")
        assert h.lower.call
        return h.lower.call(target, args, data)

    h.m.write(h.key, 4, 11)
    with pytest.raises(RuntimeError, match="insertion missing"):
        lookup_replay_combat_tracker(
            h.context,
            h.header,
            h.key,
            calls=ReplayTaskRebuildCalls(direct_children),
            bind_local=h.local,
            scratch=SEED,
        )
    node = h.m.snapshot().regions[-1].address
    assert h.m.read(node + 28, 4) == 11 and h.m.read(node + 32, 8) == 0
    assert h.m.read(h.header + 8, 8) == 0 and h.m.read(h.nil + 8, 8) == h.nil


def test_real_insert_first_count_effect_precedes_missing_descriptor_read():
    h = setup()
    node = h.m.allocate(40)
    with pytest.raises(ReplayMemoryError):
        insert_replay_combat_tracker(h.context, h.header, 0, node, calls=h.lower)
    assert h.m.read(h.header + 8, 8) == 1
    with pytest.raises(ReplayMemoryError, match="undefined"):
        h.m.read(node + 8, 8)


@pytest.mark.parametrize("target", [0xD012, LENGTH, LOOKUP])
def test_current_length_iat_is_terminal_even_if_aliasing_owned_entry(target):
    h = setup()
    h.m.map_bytes(0x1431992A0, target.to_bytes(8, "little"))
    events = []

    def terminal(entry, args, data):
        events.append((entry, args, data))
        raise RuntimeError("actual selected length provider")

    bound = bind_replay_combat_saved_tracker(
        h.context,
        h.lower,
        bind_local=h.local,
        scratch=SEED,
        imports=ReplayTaskRebuildCalls(terminal),
    )
    h.m.write(h.header + 8, 8, 0x0666666666666666)
    h.m.write(h.key, 4, 5)
    assert bound.call
    with pytest.raises(RuntimeError, match="selected length provider"):
        bound.call(LOOKUP, (h.header, h.key), None)
    assert events == [(target, (0x143677420,), None)]
    assert not any(e[:2] == ("call", MALLOC) for e in h.events)


def test_length_helper_return_refuses_before_trap():
    h = setup()
    h.m.map_bytes(0x1431992A0, (0xD012).to_bytes(8, "little"))
    with pytest.raises(RuntimeError, match="nonreturning"):
        fail_replay_combat_tracker_length(
            h.context,
            calls=ReplayTaskRebuildCalls(lambda target, args, data: None),
        )


def test_insert_counter_wrap_and_root_path_skip_descriptor_side():
    h = setup()
    descriptor, node = h.m.allocate(8), h.m.allocate(40)
    h.m.write(descriptor, 8, h.nil)
    h.m.write(h.header + 8, 8, (1 << 64) - 1)
    assert (
        insert_replay_combat_tracker(
            h.context,
            h.header,
            descriptor,
            node,
            calls=h.lower,
        )
        == node
    )
    assert h.m.read(h.header + 8, 8) == 0
    assert h.m.read_bytes(node + 8, 8) == h.nil.to_bytes(8, "little")
    assert h.m.read(node + 24, 1) == 1
    with pytest.raises(ReplayMemoryError, match="undefined"):
        h.m.read(node, 8)


@pytest.mark.parametrize(
    "entry,args",
    [
        (LOOKUP, (1,)),
        (LOOKUP, (1, 2, 3)),
        (INSERT, (1, 2)),
        (LENGTH, (1,)),
    ],
)
def test_arity_admission_before_any_body_effect(entry, args):
    h = setup()
    assert h.bound.call
    with pytest.raises(ValueError, match="malformed"):
        h.bound.call(entry, args, None)
    assert h.events == []


def test_unknown_delegation_and_missing_child():
    h = setup()
    with pytest.raises(UnresolvedReplayTaskRebuild):
        lookup_replay_combat_tracker(
            h.context,
            h.header,
            h.key,
            calls=ReplayTaskRebuildCalls(None),
            bind_local=h.local,
            scratch=SEED,
        )
    with pytest.raises(ValueError):
        ReplayCombatTrackerScratch(bytes(63))
