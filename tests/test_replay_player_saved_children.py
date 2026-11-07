"""Owned source-derived Result/vector controls; reserve is explicit opaque fixture."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from vantage.replay_memory import ReplayMemory, ReplayMemoryError
from vantage.replay_player_saved_children import (
    assign_replay_player_result,
    bind_replay_player_saved_children,
    commit_replay_player_bytes,
    fill_replay_player_words,
    resize_replay_player_words,
)
from vantage.replay_saved_apply import bind_replay_saved_apply
from vantage.replay_saved_pair import bind_replay_saved_pair
from vantage.replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
)
from vantage.replay_unit_ai_map import ReplayUnitAIMapAtomics
from vantage.replay_zone_map_construction import bind_replay_zone_map_construction

U64 = (1 << 64) - 1


def setup(*, on_read=None, on_write=None, after=None):
    h = SimpleNamespace()
    h.m = m = ReplayMemory()
    h.header, h.source, h.output = (m.calloc(1, n) for n in (24, 48, 48))
    h.ops, h.events, h.import_events = [], [], []
    h.handlers, h.overrides, h.missing = {}, {}, set()
    m.map_bytes(0x143199DD0, (0x142D6BAB4).to_bytes(8, "little"))
    m.map_bytes(0x143199938, (0x142D6E3B7).to_bytes(8, "little"))
    m.map_bytes(0x14319A060, (0xCA03).to_bytes(8, "little"))

    def read(address, width):
        value = m.read(address, width)
        h.ops.append(("read", address, width, value))
        if on_read:
            on_read(h, address, width, value)
        return value

    def write(address, width, value):
        m.write(address, width, value)
        h.ops.append(("write", address, width, value))
        if on_write:
            on_write(h, address, width, value)

    h.ctx = ReplayTaskRebuildStorage(h.header, read, write)
    h.atomics = ReplayUnitAIMapAtomics(m.compare_exchange_u32, m.fetch_add_u32)
    runtime = m.runtime_calls()

    def terminal(target, args, data):
        h.import_events.append((target, args))
        if target in h.overrides:
            return h.overrides[target](target, args, data)
        assert runtime.call
        return runtime.call(target, args, data)

    h.imports = ReplayTaskRebuildCalls(terminal)

    def call(target, args, data):
        h.events.append((target, args))
        if target in h.missing:
            raise UnresolvedReplayTaskRebuild(f"missing child{target:x}")
        if target in h.overrides:
            result = h.overrides[target](target, args, data)
        elif target in h.handlers:
            result = h.handlers[target](target, args, data)
        else:
            assert runtime.call
            result = runtime.call(target, args, data)
        if after:
            after(h, target, args, result)
        return result

    h.calls = ReplayTaskRebuildCalls(call)

    def register(bound, targets):
        assert bound.call
        for target in targets:
            h.handlers[target] = bound.call

    register(bind_replay_saved_pair(h.ctx, h.calls, atomics=h.atomics), (0x14090D270,))
    register(
        bind_replay_saved_apply(h.ctx, h.calls, atomics=h.atomics, imports=h.imports),
        (0x1402B9080,),
    )
    register(
        bind_replay_zone_map_construction(h.ctx, h.calls, atomics=h.atomics, imports=h.imports),
        (0x142D6BAB4, 0x142D6E3B7),
    )
    h.bound = bind_replay_player_saved_children(h.ctx, h.calls, imports=h.imports)
    register(h.bound, (0x140991CE0, 0x1402DBEF0, 0x140C4DDE0, 0x140C31B50))
    return h


def entry(h, target, *args):
    assert h.bound.call
    return h.bound.call(target, args, None)


def vector(h, length=2, capacity=8):
    pointer = h.m.allocate(capacity * 4)
    h.m.write_bytes(pointer, b"G" * (capacity * 4))
    h.m.write(h.header, 8, pointer)
    h.m.write(h.header + 8, 8, pointer + length * 4)
    h.m.write(h.header + 16, 8, pointer + capacity * 4)
    return pointer


@pytest.mark.parametrize("identity", (False, True))
@pytest.mark.parametrize("bound", (False, True))
def test_assignment_actual_pair_and_empty_vector_preserve_exact_padding(identity, bound):
    h = setup()
    destination = h.source if identity else h.output
    h.m.write(h.source + 24, 8, 0xC0DE)
    h.m.write_bytes(destination + 41, b"padding")
    result = (
        entry(h, 0x140991CE0, destination, h.source)
        if bound
        else (assign_replay_player_result(h.ctx, destination, h.source, calls=h.calls))
    )
    assert result == destination
    assert h.m.read(destination + 24, 8) == 0xC0DE
    assert h.m.read(destination + 40, 1) == 0
    assert h.m.read(h.source + 40, 1) == (0 if identity else 1)
    assert h.m.read_bytes(destination + 41, 7) == b"padding"
    assert [target for target, _ in h.events].count(0x14090D270) == 1
    assert [target for target, _ in h.events].count(0x1402B9080) == (not identity)


@pytest.mark.parametrize("difference,count", ((63, 1), (U64 - 31, U64), (0, 0)))
def test_assignment_current_vector_after_pair_and_held_begin(difference, count):
    def after(h, target, args, result):
        if target == 0x14090D270:
            h.m.write(h.source, 8, 0x1000)
            h.m.write(h.source + 8, 8, (0x1000 + difference) & U64)

    h = setup(after=after)
    seen = []

    def stop(target, args, data):
        seen.append(args)
        raise RuntimeError("actual vector frontier")

    h.overrides[0x1402B9080] = stop
    h.m.write(h.output + 40, 1, 0x55)
    with pytest.raises(RuntimeError, match="vector frontier"):
        entry(h, 0x140991CE0, h.output, h.source)
    assert seen == [(h.output, 0x1000, count)]
    assert h.m.read(h.source + 40, 1) == 1
    assert h.m.read(h.output + 40, 1) == 0x55


def test_assignment_missing_pair_preserves_source_processed_before_call():
    h = setup()
    h.missing.add(0x14090D270)
    with pytest.raises(UnresolvedReplayTaskRebuild):
        entry(h, 0x140991CE0, h.output, h.source)
    assert h.m.read(h.source + 40, 1) == 1
    assert h.m.read(h.output + 40, 1) == 0


@pytest.mark.parametrize("bound", (False, True))
def test_commit_null_skips_unavailable_capacity_and_exact_wrapped_stores(bound):
    h = setup()
    header = h.m.allocate(24)
    h.m.write(header, 8, 0)
    args = (header, U64 - 3, 9, 20)
    if bound:
        entry(h, 0x1402DBEF0, *args)
    else:
        commit_replay_player_bytes(h.ctx, *args, calls=h.calls, imports=h.imports)
    assert h.m.read(header, 8) == U64 - 3
    assert h.m.read(header + 8, 8) == 5
    assert h.m.read(header + 16, 8) == 16
    assert [op for op in h.ops if op[0] == "read"] == [("read", header, 8, 0)]


@pytest.mark.parametrize("size", (0, 32, 4095))
def test_commit_small_nonnull_actual_free_and_held_inputs(size):
    def after(h, target, args, result):
        if target == 0x142D6BAB4:
            h.m.write(h.header, 8, 0xBADBAD)
            h.m.write(h.header + 16, 8, 0xBADBAD)

    h = setup(after=after)
    old = h.m.allocate(max(1, size))
    h.m.write(h.header, 8, old)
    h.m.write(h.header + 16, 8, old + size)
    entry(h, 0x1402DBEF0, h.header, 0x12340, 3, 17)
    assert (0x142D6BAB4, (old, size)) in h.events
    assert tuple(h.m.read(h.header + delta, 8) for delta in (0, 8, 16)) == (
        0x12340,
        0x12343,
        0x12351,
    )


@pytest.mark.parametrize("gap,valid", ((8, True), (39, True), (7, False), (40, False)))
def test_commit_large_backpointer_guard_terminal_alias_and_no_late_commit(gap, valid):
    h = setup()
    raw = h.m.allocate(0x1100)
    old = raw + gap
    h.m.write(old - 8, 8, raw)
    h.m.write(h.header, 8, old)
    h.m.write(h.header + 16, 8, old + 0x1000)
    h.m.write(0x14319A060, 8, 0x1402DBEF0)
    seen = []
    h.overrides[0x1402DBEF0] = lambda target, args, data: seen.append(args)
    if valid:
        commit_replay_player_bytes(h.ctx, h.header, 1, 2, 3, calls=h.calls, imports=h.imports)
        assert (0x142D6BAB4, (raw, 4135)) in h.events
        assert h.m.read(h.header, 8) == 1
    else:
        with pytest.raises(UnresolvedReplayTaskRebuild, match="INT3"):
            commit_replay_player_bytes(h.ctx, h.header, 1, 2, 3, calls=h.calls, imports=h.imports)
        assert seen == [(0, 0, 0, 0, 0)]
        assert h.m.read(h.header, 8) == old


def test_commit_free_failure_retains_old_header():
    h = setup()
    pointer = vector(h)
    h.missing.add(0x142D6BAB4)
    with pytest.raises(UnresolvedReplayTaskRebuild):
        entry(h, 0x1402DBEF0, h.header, 123, 4, 12)
    assert h.m.read(h.header, 8) == pointer
    assert h.m.read(h.header + 8, 8) == pointer + 8


@pytest.mark.parametrize("count", (0, 1, 3, 4, 5, 7, 8, 9))
@pytest.mark.parametrize("value", (0, 7))
def test_range_fill_exact_empty_bulk_tail_and_guards(count, value):
    h = setup()
    begin = h.m.allocate(48)
    h.m.write_bytes(begin, b"G" * 48)
    h.m.write(h.source, 4, value)
    entry(h, 0x140C31B50, begin, begin + count * 4, h.source)
    assert h.m.read_bytes(begin, 48) == (
        value.to_bytes(4, "little") * count + b"G" * (48 - count * 4)
    )
    if not value:
        assert (0x142D6E3B7, (begin, 0, count * 4)) in h.events
    elif not count:
        assert not [op for op in h.ops if op[0] == "write"]
    assert next(op for op in h.ops if op[0] == "read")[1] == h.source


def test_range_fill_nonalias_bulk_holds_value_but_tail_rereads_source():
    destination = []

    def on_write(h, address, width, value):
        if destination and address == destination[0]:
            h.m.write(h.source, 4, 99)

    h = setup(on_write=on_write)
    begin = h.m.allocate(20)
    destination.append(begin)
    h.m.write(h.source, 4, 7)
    fill_replay_player_words(h.ctx, begin, begin + 20, h.source, calls=h.calls)
    assert [h.m.read(begin + index * 4, 4) for index in range(5)] == [7, 7, 7, 7, 99]
    assert [value for op, address, _, value in h.ops if op == "read" and address == h.source] == (
        [7, 7, 99]
    )


def test_range_fill_alias_fallback_keeps_unused_cached_read_and_current_each_word():
    state = []

    def on_write(h, address, width, value):
        if state and address == state[0]:
            h.m.write(state[0] + 8, 4, 9)

    h = setup(on_write=on_write)
    begin = h.m.calloc(1, 16)
    state.append(begin)
    source = begin + 8
    h.m.write(source, 4, 7)
    entry(h, 0x140C31B50, begin, begin + 16, source)
    reads = [value for op, address, _, value in h.ops if op == "read" and address == source]
    assert reads == [7, 7, 7, 9, 9, 9]
    writes = [
        value for op, address, _, value in h.ops if op == "write" and begin <= address < begin + 16
    ]
    assert writes == [7, 9, 9, 9]


@pytest.mark.parametrize("difference", (-4, 1, 3))
def test_range_fill_malformed_profile_refuses_before_source_access(difference):
    h = setup()
    with pytest.raises(ValueError):
        entry(h, 0x140C31B50, 0x1000, 0x1000 + difference, U64)
    assert not h.ops


def test_range_empty_still_requires_current_source_binding():
    h = setup()
    with pytest.raises(ReplayMemoryError):
        entry(h, 0x140C31B50, 0x1000, 0x1000, U64)


@pytest.mark.parametrize("requested", (0, 1, 2, 4))
@pytest.mark.parametrize("value", (0, 7))
def test_resize_existing_prefix_is_real_fill_including_empty(requested, value):
    h = setup()
    begin = vector(h, length=4)
    h.m.write(h.source, 4, value)
    entry(h, 0x140C4DDE0, h.header, requested, h.source)
    assert h.m.read(h.header + 8, 8) == begin + requested * 4
    assert h.m.read_bytes(begin, 32) == value.to_bytes(4, "little") * requested + (
        b"G" * (32 - requested * 4)
    )
    if not value:
        assert (0x142D6E3B7, (begin, 0, requested * 4)) in h.events


def test_resize_inplace_uses_current_end_then_current_source_after_real_prefix_fill():
    moved = []

    def after(h, target, args, result):
        if target == 0x140C31B50:
            assert len(args) == 3 and args[2] == h.source
            h.m.write(h.header + 8, 8, moved[0])
            h.m.write(h.source, 4, 99)

    h = setup(after=after)
    begin = vector(h, length=2)
    alternate = h.m.allocate(16)
    moved.append(alternate)
    h.m.write(h.source, 4, 7)
    resize_replay_player_words(h.ctx, h.header, 4, h.source, calls=h.calls)
    assert h.m.read_bytes(begin, 8) == (7).to_bytes(4, "little") * 2
    assert h.m.read_bytes(alternate, 8) == (99).to_bytes(4, "little") * 2
    assert h.m.read(h.header + 8, 8) == alternate + 8
    reads = [a for op, a, _, _ in h.ops if op == "read"]
    assert reads[-3:] == [h.source, h.source, h.source]


def test_resize_shrink_keeps_held_target_end_across_child_header_mutation():
    def after(h, target, args, result):
        if target == 0x140C31B50:
            h.m.write(h.header, 8, 0xBADBAD)

    h = setup(after=after)
    begin = vector(h, length=4)
    h.m.write(h.source, 4, 7)
    resize_replay_player_words(h.ctx, h.header, 1, h.source, calls=h.calls)
    assert h.m.read(h.header, 8) == 0xBADBAD
    assert h.m.read(h.header + 8, 8) == begin + 4


def test_resize_reserve_remains_required_and_prior_headers_unchanged_on_refusal():
    h = setup()
    with pytest.raises(UnresolvedReplayTaskRebuild):
        entry(h, 0x140C4DDE0, h.header, 3, h.source)
    assert h.m.read_bytes(h.header, 24) == bytes(24)
    assert h.events[-1] == (0x1402BA470, (h.header, 3))


def test_resize_isolated_reserve_program_source_read_before_current_begin():
    alternate = []
    state = []

    def on_read(h, address, width, value):
        if state and address == h.source:
            h.m.write(h.header, 8, alternate[0])
            h.m.write(h.source, 4, 99)

    h = setup(on_read=on_read)
    alternate.append(h.m.allocate(12))
    allocated = []

    def reserve(target, args, data):
        assert args == (h.header, 3)
        pointer = h.m.allocate(12)
        allocated.append(pointer)
        h.m.write(h.header, 8, pointer)
        h.m.write(h.header + 8, 8, pointer)
        h.m.write(h.header + 16, 8, pointer + 12)
        state.append(True)

    # This program is explicit external reserve input, not a native implementation claim.
    h.overrides[0x1402BA470] = reserve
    entry(h, 0x140C4DDE0, h.header, 3, h.source)
    assert h.m.read_bytes(alternate[0], 12) == bytes(12)
    assert h.m.read(h.header + 8, 8) == alternate[0] + 12
    with pytest.raises(ReplayMemoryError):
        h.m.read(allocated[0], 1)


def test_resize_fill_failure_keeps_earlier_prefix_stores_without_end_commit():
    state = []

    def on_write(h, address, width, value):
        if state and address == state[0] + 4:
            raise RuntimeError("actual destination callback")

    h = setup(on_write=on_write)
    begin = vector(h, length=4)
    state.append(begin)
    h.m.write(h.source, 4, 7)
    with pytest.raises(RuntimeError, match="destination callback"):
        entry(h, 0x140C4DDE0, h.header, 3, h.source)
    assert h.m.read_bytes(begin, 8) == (7).to_bytes(4, "little") * 2
    assert h.m.read(h.header + 8, 8) == begin + 16


@pytest.mark.parametrize(
    "target,arity", ((0x140991CE0, 2), (0x1402DBEF0, 4), (0x140C4DDE0, 3), (0x140C31B50, 3))
)
def test_binder_shapes_unknown_and_raw_argument_validation(target, arity):
    h = setup()
    assert h.bound.call
    with pytest.raises(ValueError):
        h.bound.call(target, (h.header,) * (arity + 1), None)
    with pytest.raises(ValueError):
        h.bound.call(target, (h.header,) * arity, memoryview(b"x"))
    with pytest.raises(ValueError):
        h.bound.call(target, (-1,) * arity, None)
    with pytest.raises(UnresolvedReplayTaskRebuild):
        h.bound.call(0xBADBAD, (), None)


@pytest.mark.parametrize("old_displacement", (-4, -8))
def test_resize_unsigned_signed_sar_length_keeps_native_branch(old_displacement):
    h = setup()
    begin = vector(h)
    h.m.write(h.header + 8, 8, begin + old_displacement)
    h.m.write(h.source, 4, 9)
    entry(h, 0x140C4DDE0, h.header, 1, h.source)
    assert h.m.read(begin, 4) == 9
    assert h.m.read(h.header + 8, 8) == begin + 4
    assert not any(target == 0x1402BA470 for target, _ in h.events)
