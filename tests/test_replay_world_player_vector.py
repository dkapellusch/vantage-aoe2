"""Owned source-led pair-vector controls; no original Game or native oracle."""

from __future__ import annotations

import pytest

from vantage import replay_world_player_vector as vector
from vantage.replay_memory import ReplayMemory, ReplayMemoryError
from vantage.replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
)
from vantage.replay_unit_ai_map import ReplayUnitAIMapAtomics

RELEASE, APPEND, GROW, RESIZE = 0x141344F50, 0x1415E7D40, 0x1415E7B70, 0x14161DBE0
ALLOC, FREE, LENGTH, FATAL, WATSON = 0x1402A94D0, 0x142D6BAB4, 0x141345000, 0x1402A9460, 0xF0A1
U64, MAX = (1 << 64) - 1, (1 << 60) - 1


class Fixture:
    def __init__(self, size=0, capacity=0, *, source=(0, 0)):
        self.memory = ReplayMemory(max_bytes=2 << 20)
        self.header, self.source = self.memory.allocate(24), self.memory.allocate(16)
        self.rows = self.memory.allocate_aligned(capacity * 16) if capacity else 0
        if capacity:
            self.memory.fill(self.rows, 0xA5, capacity * 16)
            for i in range(size):
                self.pair(self.rows + i * 16, (0xAB00 + i, 0))
        for offset, value in (
            (0, self.rows),
            (8, self.rows + size * 16),
            (16, self.rows + capacity * 16),
        ):
            self.memory.write(self.header + offset, 8, value)
        self.pair(self.source, source)
        self.memory.map_bytes(0x14319A060, WATSON.to_bytes(8, "little"))
        self.events, self.effects = [], {}
        self.on_read = self.on_write = self.on_atomic = None
        self.primitive = self.memory.runtime_calls()
        self.context = ReplayTaskRebuildStorage(self.header, self.read, self.write)
        self.calls = ReplayTaskRebuildCalls(self.dispatch)
        self.imports = ReplayTaskRebuildCalls(self.terminal)
        self.atomics = ReplayUnitAIMapAtomics(None, self.atomic)
        self.bound = vector.bind_replay_world_player_vector(
            self.context, self.calls, atomics=self.atomics, imports=self.imports
        )

    def pair(self, address, pair):
        self.memory.write(address, 8, pair[0])
        self.memory.write(address + 8, 8, pair[1])

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

    def atomic(self, address, value):
        prior = self.memory.fetch_add_u32(address, value)
        self.events.append(("a", address, value, prior))
        if self.on_atomic:
            return self.on_atomic(address, value, prior)
        return prior

    def terminal(self, target, args, data):
        self.events.append(("i", target, args))
        if target in self.effects:
            return self.effects[target](args)
        assert self.primitive.call is not None
        return self.primitive.call(target, args, data)

    def dispatch(self, target, args, data):
        self.events.append(("c", target, args))
        if target in self.effects:
            return self.effects[target](args)
        if target in (RELEASE, APPEND, GROW, RESIZE):
            assert self.bound.call is not None
            return self.bound.call(target, args, data)
        assert self.primitive.call is not None
        return self.primitive.call(target, args, data)

    def run(self, target, *args):
        assert self.bound.call is not None
        return self.bound.call(target, args, None)

    def resize(self, count):
        return self.run(RESIZE, self.header, count, self.source)

    def header_values(self):
        return tuple(self.memory.read(self.header + offset, 8) for offset in (0, 8, 16))

    def pairs(self, begin, count):
        return [
            tuple(self.memory.read(begin + i * 16 + o, 8) for o in (0, 8)) for i in range(count)
        ]

    def control(self, strong=1, weak=1, destroy=0xD0, dispose=0xD8):
        control, table = self.memory.allocate(16), self.memory.allocate(16)
        self.memory.write(control, 8, table)
        self.memory.write(control + 8, 4, strong)
        self.memory.write(control + 12, 4, weak)
        self.pair(table, (destroy, dispose))
        return control, table


@pytest.mark.parametrize("count", [4, 7])
def test_fresh_world_slot_count(count):
    f = Fixture()
    assert f.resize(count) is None
    begin, end, cap = f.header_values()
    assert end == cap == begin + count * 16
    assert f.pairs(begin, count) == [(0, 0)] * count
    assert [(e[1], e[2]) for e in f.events if e[0] == "c"] == [(ALLOC, (count * 16,))]
    assert not any(e[0] == "a" for e in f.events)


def test_equal_reads_only_held_end_then_begin():
    f = Fixture(2, 2)
    f.resize(2)
    assert f.events == [("r", f.header + 8, 8, f.rows + 32), ("r", f.header, 8, f.rows)]


@pytest.mark.parametrize("size,requested,capacity", [(3, 1, 5), (3, 0, 3), (1, 3, 5), (0, 4, 5)])
def test_shrink_and_in_capacity_growth(size, requested, capacity):
    f = Fixture(size, capacity, source=(0xCAFE, 0))
    f.resize(requested)
    assert f.header_values() == (f.rows, f.rows + requested * 16, f.rows + capacity * 16)
    assert f.pairs(f.rows, min(size, requested)) == [
        (0xAB00 + i, 0) for i in range(min(size, requested))
    ]
    if requested > size:
        assert f.pairs(f.rows + size * 16, requested - size) == [(0xCAFE, 0)] * (requested - size)
    assert not any(e[0] == "c" and e[1] in (ALLOC, FREE) for e in f.events)


def test_shrink_release_precedes_held_end_commit_even_header_mutates():
    f = Fixture(3, 4)

    def release(args):
        assert args == (f.rows + 16, f.rows + 48, f.header)
        assert f.memory.read(f.header + 8, 8) == f.rows + 48
        f.memory.write(f.header, 8, 0x9990)
        f.memory.write(f.header + 8, 8, 0x7770)
        return -123

    f.effects[RELEASE] = release
    vector.resize_replay_world_players(f.context, f.header, 1, f.source, calls=f.calls)
    assert f.header_values() == (0x9990, f.rows + 16, f.rows + 64)


def test_resize_uses_actual_append_return_not_recomputed_end():
    f = Fixture(1, 3)
    f.effects[APPEND] = lambda args: 0x1234
    vector.resize_replay_world_players(f.context, f.header, 2, f.source, calls=f.calls)
    assert ("c", APPEND, (f.rows + 16, 1, f.source, f.header)) in f.events
    assert f.memory.read(f.header + 8, 8) == 0x1234


def test_resize_forwards_growth_without_post_commit():
    f = Fixture(1, 1)

    def grow(args):
        assert args == (f.header, 2, f.source)
        f.memory.write(f.header + 8, 8, 0x1234)
        return -1

    f.effects[GROW] = grow
    vector.resize_replay_world_players(f.context, f.header, 2, f.source, calls=f.calls)
    assert f.memory.read(f.header + 8, 8) == 0x1234


def test_append_empty_calls_real_release_and_ignores_return():
    f = Fixture()
    f.effects[RELEASE] = lambda args: -7
    assert (
        vector.append_replay_world_players(
            f.context, f.source, 0, U64, f.header, calls=f.calls, atomics=f.atomics
        )
        == f.source
    )
    assert f.events == [("c", RELEASE, (f.source, f.source, f.header))]


def test_append_source_destination_alias_is_zero_before_source_read():
    f = Fixture()
    control, _ = f.control()
    f.pair(f.source, (0xFADE, control))
    assert f.run(APPEND, f.source, 1, f.source, f.header) == f.source + 16
    assert f.pairs(f.source, 1) == [(0, 0)]
    assert f.memory.read(control + 8, 4) == 1
    assert [e[:3] for e in f.events[:3]] == [
        ("w", f.source, 8),
        ("w", f.source + 8, 8),
        ("r", f.source + 8, 8),
    ]


def test_append_atomic_can_mutate_current_source_and_return_is_ignored():
    f = Fixture(0, 2)
    first, _ = f.control(strong=5)
    second, _ = f.control(strong=9)
    f.pair(f.source, (0x1111, first))

    def mutate(address, value, prior):
        if address == first + 8:
            f.pair(f.source, (0x2222, second))
        return None

    f.on_atomic = mutate
    f.run(APPEND, f.rows, 2, f.source, f.header)
    assert f.pairs(f.rows, 2) == [(0x2222, second)] * 2
    assert f.memory.read(first + 8, 4) == 6
    assert f.memory.read(second + 8, 4) == 10


@pytest.mark.parametrize("strong,weak,expected", [(3, 1, []), (1, 2, [0xD0]), (1, 1, [0xD0, 0xD8])])
def test_release_actual_strong_weak_lifetimes(strong, weak, expected):
    f = Fixture(1, 1)
    control, _ = f.control(strong, weak)
    f.pair(f.rows, (0xFFFF, control))
    for target in expected:
        f.effects[target] = lambda args: None
    f.run(RELEASE, f.rows, f.rows + 16, 0)
    assert [e[1] for e in f.events if e[0] == "c"] == expected
    assert f.pairs(f.rows, 1) == [(0xFFFF, control)]
    assert f.memory.read(control + 8, 4) == strong - 1
    assert f.memory.read(control + 12, 4) == weak - (strong == 1)


def test_release_holds_control_but_reloads_current_weak_vptr_and_next_row():
    f = Fixture(2, 2)
    held, _ = f.control()
    replacement, replacement_table = f.control(destroy=0xE0, dispose=0xE8)
    f.pair(f.rows, (1, held))
    f.pair(f.rows + 16, (2, 0))

    def destroy(args):
        assert args == (held,)
        f.memory.write(held, 8, replacement_table)
        f.memory.write(f.rows + 8, 8, replacement)
        f.memory.write(f.rows + 24, 8, replacement)

    f.effects[0xD0] = destroy
    f.effects[0xE0] = f.effects[0xE8] = lambda args: None
    f.run(RELEASE, f.rows, f.rows + 32, 0)
    assert [e[1:] for e in f.events if e[0] == "c"] == [
        (0xD0, (held,)),
        (0xE8, (held,)),
        (0xE0, (replacement,)),
        (0xE8, (replacement,)),
    ]


def test_empty_release_reads_nothing_even_missing_atomics():
    f = Fixture()
    vector.release_replay_world_players(
        f.context,
        U64,
        U64,
        0,
        calls=ReplayTaskRebuildCalls(None),
        atomics=ReplayUnitAIMapAtomics(None, None),
    )
    assert f.events == []


@pytest.mark.parametrize(
    "size,capacity,requested,newcap", [(1, 2, 3, 3), (2, 4, 5, 6), (0, 0, 1, 1)]
)
def test_growth_moves_old_rows_and_repeats_source_before_free(size, capacity, requested, newcap):
    f = Fixture(size, capacity, source=(0x55, 0))
    old = f.rows
    f.resize(requested)
    begin, end, cap = f.header_values()
    assert begin != old and end == begin + requested * 16 and cap == begin + newcap * 16
    assert f.pairs(begin, size) == [(0xAB00 + i, 0) for i in range(size)]
    assert f.pairs(begin + size * 16, requested - size) == [(0x55, 0)] * (requested - size)
    calls = [e[1:] for e in f.events if e[0] == "c"]
    assert calls == [(ALLOC, (newcap * 16,))] + ([(FREE, (old, capacity * 16))] if old else [])
    if old:
        with pytest.raises(ReplayMemoryError):
            f.memory.read(old, 8)


def test_growth_shared_source_acquires_only_new_tail_and_moves_without_increment():
    f = Fixture(1, 1)
    control, _ = f.control(strong=4)
    f.pair(f.source, (0xBEEF, control))
    f.pair(f.rows, (0x1111, control))
    f.resize(3)
    begin = f.header_values()[0]
    assert f.pairs(begin, 3) == [(0x1111, control), (0xBEEF, control), (0xBEEF, control)]
    assert f.memory.read(control + 8, 4) == 6
    assert len([e for e in f.events if e[0] == "a"]) == 2


def test_growth_source_alias_old_row_is_read_before_move_zeroes_it():
    f = Fixture(1, 1)
    f.pair(f.rows, (0xAFFE, 0))
    f.run(GROW, f.header, 2, f.rows)
    assert f.pairs(f.header_values()[0], 2) == [(0xAFFE, 0)] * 2


def test_growth_allocation_callback_changes_current_old_vector_but_initial_tail_size_held():
    f = Fixture(1, 1, source=(0x55, 0))
    alternate = f.memory.allocate(32)
    f.pair(alternate, (0x66, 0))
    f.pair(alternate + 16, (0x77, 0))

    def alloc(args):
        replacement = f.memory.allocate_aligned(args[0])
        f.memory.write(f.header, 8, alternate)
        f.memory.write(f.header + 8, 8, alternate + 32)
        f.memory.write(f.header + 16, 8, alternate + 32)
        return replacement

    f.effects[ALLOC] = alloc
    f.resize(3)
    begin = f.header_values()[0]
    assert f.pairs(begin, 3) == [(0x66, 0), (0x77, 0), (0x55, 0)]
    assert f.memory.read(f.rows, 8) == 0xAB00
    assert ("c", FREE, (alternate, 32)) in f.events


def test_growth_empty_release_seams_reload_headers_and_free_before_commit():
    f = Fixture(1, 1, source=(0x99, 0))
    alternate = f.memory.allocate(16)
    f.pair(alternate, (0x88, 0))
    freed = f.memory.allocate(32)
    f.memory.fill(freed, 0, 32)
    releases = []

    def release(args):
        releases.append(args)
        if len(releases) == 1:
            f.memory.write(f.header, 8, alternate)
            f.memory.write(f.header + 8, 8, alternate + 16)
        elif len(releases) == 2:
            f.memory.write(f.header, 8, freed)
            f.memory.write(f.header + 8, 8, freed + 16)
        else:
            f.memory.write(f.header + 16, 8, freed + 32)

    def free(args):
        assert args == (freed, 32)
        assert f.header_values() == (freed, freed + 16, freed + 32)
        f.memory.free(freed)
        f.memory.write(f.header, 8, 0xBAD)

    f.effects[RELEASE], f.effects[FREE] = release, free
    vector.grow_replay_world_players(
        f.context, f.header, 2, f.source, calls=f.calls, atomics=f.atomics, imports=f.imports
    )
    begin, end, cap = f.header_values()
    assert end == cap == begin + 32
    assert f.pairs(begin, 2) == [(0x88, 0), (0x99, 0)]
    assert releases[-1] == (freed, freed + 16, f.header)


def test_growth_destination_old_source_alias_uses_ordered_zero_copy_zero():
    f = Fixture(1, 2)
    f.effects[ALLOC] = lambda args: f.rows
    # An authored alias control, with genuine old allocation retained until FREE.
    f.effects[FREE] = lambda args: None
    f.run(GROW, f.header, 2, f.source)
    assert f.pairs(f.rows, 2) == [(0, 0), (0, 0)]


def test_growth_large_aligned_free_uses_current_backpointer_and_size():
    f = Fixture(1, 256, source=(0x44, 0))
    old_base = f.memory.read(f.rows - 8, 8)
    f.resize(257)
    assert ("c", FREE, (old_base, 4096 + 0x27)) in f.events
    assert f.header_values()[2] - f.header_values()[0] == 384 * 16


def test_growth_invalid_large_backpointer_calls_current_terminal_watson_before_commit():
    f = Fixture(1, 256)
    f.memory.write(f.rows - 8, 8, f.rows - 48)
    f.effects[WATSON] = lambda args: -4
    with pytest.raises(UnresolvedReplayTaskRebuild, match="Watson returned"):
        f.resize(257)
    assert ("i", WATSON, (0, 0, 0, 0, 0)) in f.events
    assert not any(e[0] == "c" and e[1] == FREE for e in f.events)
    assert f.header_values() == (f.rows, f.rows + 16, f.rows + 4096)
    assert f.pairs(f.rows, 1) == [(0, 0)]


def test_growth_missing_watson_selected_provider_keeps_prior_move_effects():
    f = Fixture(1, 256)
    f.memory.write(f.rows - 8, 8, f.rows - 48)
    with pytest.raises(UnresolvedReplayTaskRebuild, match="f0a1"):
        f.resize(257)
    assert f.pairs(f.rows, 1) == [(0, 0)]


def test_growth_too_large_calls_length_leaf_before_any_header_read_and_refuses_return():
    f = Fixture()
    f.effects[LENGTH] = lambda args: None
    with pytest.raises(UnresolvedReplayTaskRebuild, match="length error returned"):
        f.run(GROW, f.header, MAX + 1, U64)
    assert f.events == [("c", LENGTH, ())]


def test_growth_missing_length_leaf_is_not_success():
    f = Fixture()
    with pytest.raises(UnresolvedReplayTaskRebuild, match="141345000"):
        f.run(GROW, f.header, MAX + 1, U64)
    assert f.header_values() == (0, 0, 0)


@pytest.mark.parametrize("delta", [0x7FFFFFFFFFFFFFF0, 0x8000000000000000, U64 - 15])
def test_growth_capacity_extremes_saturate_or_retain_real_fatal_leaf(delta):
    f = Fixture()
    f.memory.write(f.header + 16, 8, delta)

    def stop(args):
        raise RuntimeError(f"allocated-size:{args[0]:x}")

    f.effects[ALLOC] = stop
    cap = ((delta if delta < 1 << 63 else delta - (1 << 64)) >> 4) & U64
    expected = MAX if cap > ((MAX - (cap >> 1)) & U64) else max(cap + (cap >> 1), 1)
    with pytest.raises(RuntimeError, match=f"allocated-size:{expected * 16:x}"):
        f.run(GROW, f.header, 1, f.source)
    assert not any(e[0] == "c" and e[1] == FATAL for e in f.events)


def test_missing_atomic_preserves_prior_destination_zeros():
    f = Fixture(0, 1)
    control, _ = f.control()
    f.pair(f.source, (0xFADE, control))
    with pytest.raises(UnresolvedReplayTaskRebuild, match="atomic increment"):
        vector.append_replay_world_players(
            f.context,
            f.rows,
            1,
            f.source,
            f.header,
            calls=f.calls,
            atomics=ReplayUnitAIMapAtomics(None, None),
        )
    assert f.pairs(f.rows, 1) == [(0, 0)]
    assert f.memory.read(control + 8, 4) == 1


def test_missing_release_callback_preserves_strong_decrement_without_weak_decrement():
    f = Fixture(1, 1)
    control, _ = f.control()
    f.pair(f.rows, (0xFADE, control))
    with pytest.raises(UnresolvedReplayTaskRebuild, match="d0"):
        f.run(RELEASE, f.rows, f.rows + 16, f.header)
    assert f.memory.read(control + 8, 4) == 0
    assert f.memory.read(control + 12, 4) == 1


def test_missing_free_preserves_old_zeroed_rows_and_uncommitted_header():
    f = Fixture(1, 1)

    def fail(args):
        raise UnresolvedReplayTaskRebuild("actual free unavailable")

    f.effects[FREE] = fail
    with pytest.raises(UnresolvedReplayTaskRebuild, match="actual free"):
        f.resize(2)
    assert f.header_values() == (f.rows, f.rows + 16, f.rows + 16)
    assert f.pairs(f.rows, 1) == [(0, 0)]


def test_missing_allocator_preserves_header_and_old_rows():
    f = Fixture(1, 1)

    def fail(args):
        raise UnresolvedReplayTaskRebuild("actual allocator unavailable")

    f.effects[ALLOC] = fail
    with pytest.raises(UnresolvedReplayTaskRebuild, match="actual allocator"):
        f.resize(2)
    assert f.header_values() == (f.rows, f.rows + 16, f.rows + 16)
    assert f.pairs(f.rows, 1) == [(0xAB00, 0)]


def test_missing_append_release_preserves_pair_effects():
    f = Fixture(0, 1, source=(0xCAFE, 0))
    with pytest.raises(UnresolvedReplayTaskRebuild, match="141344f50"):
        vector.append_replay_world_players(
            f.context,
            f.rows,
            1,
            f.source,
            f.header,
            calls=ReplayTaskRebuildCalls(None),
            atomics=f.atomics,
        )
    assert f.pairs(f.rows, 1) == [(0xCAFE, 0)]


@pytest.mark.parametrize("begin,end", [(32, 16), (16, 33), (U64 - 15, 0)])
def test_malformed_release_ranges_refuse_before_memory_access(begin, end):
    f = Fixture()
    with pytest.raises(ValueError, match="whole16B"):
        f.run(RELEASE, begin, end, f.header)
    assert f.events == []


def test_wrapping_append_span_refuses_before_writes():
    f = Fixture()
    with pytest.raises(ValueError, match="nonwrapping"):
        f.run(APPEND, U64 - 7, 1, f.source, f.header)
    assert f.events == []


@pytest.mark.parametrize(
    "target,args", [(RELEASE, (1, 2)), (APPEND, (1, 2, 3)), (GROW, (1, 2)), (RESIZE, (1, 2))]
)
def test_binding_rejects_wrong_arities(target, args):
    f = Fixture()
    with pytest.raises(ValueError, match="malformed"):
        f.run(target, *args)


@pytest.mark.parametrize(
    "target,args",
    [(RELEASE, (1, 1, 0)), (APPEND, (1, 0, 0, 0)), (GROW, (1, 0, 0)), (RESIZE, (1, 0, 0))],
)
def test_binding_rejects_data_for_native_calls(target, args):
    f = Fixture()
    assert f.bound.call is not None
    with pytest.raises(ValueError, match="malformed"):
        f.bound.call(target, args, memoryview(bytearray(1)))


def test_binding_unknown_target_delegates_exact_args_and_data():
    f = Fixture()
    f.effects[0xABCD] = lambda args: args[0]
    assert f.run(0xABCD, 17) == 17
    assert f.events == [("c", 0xABCD, (17,))]


def test_binding_unknown_target_with_missing_dispatcher_refuses():
    f = Fixture()
    bound = vector.bind_replay_world_player_vector(
        f.context, ReplayTaskRebuildCalls(None), atomics=f.atomics
    )
    assert bound.call is not None
    with pytest.raises(UnresolvedReplayTaskRebuild, match="abcd"):
        bound.call(0xABCD, (), None)


@pytest.mark.parametrize("bad", [-1, 1 << 64, True])
def test_arguments_require_raw_u64(bad):
    f = Fixture()
    with pytest.raises(ValueError, match="raw unsigned64"):
        f.run(RESIZE, f.header, bad, f.source)
