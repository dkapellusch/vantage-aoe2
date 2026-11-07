"""Owned source contracts with real allocation, shared counts and Results.

Large Player construction/readers are declared finite effects. These tests
exercise the actual wrappers and handlers, without claiming full World restore.
"""

from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from vantage.replay_base_saved_registration import (
    ReplayBaseSavedRegistrationFP,
    ReplayBaseSavedRegistrationScratch,
    bind_replay_base_saved_registration,
)
from vantage.replay_memory import ReplayMemory, ReplayMemoryError
from vantage.replay_player_saved_factory import (
    ReplayPlayerSavedFactoryScratch,
    bind_replay_player_saved_factory,
    construct_replay_saved_player_variant,
    create_replay_saved_player,
)
from vantage.replay_saved_apply import bind_replay_saved_apply
from vantage.replay_saved_result import bind_replay_saved_result
from vantage.replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
)
from vantage.replay_unit_ai_map import ReplayUnitAIMapAtomics

ALLOC, PARENT, KEY2, GETTER = 0x142D6BA78, 0x1416C2440, 0x14174FA70, 0x141603FF0
COPY, CLEAR, READER = 0x1402B9080, 0x1402BD890, 0x1416F7980
CASES = (
    (0x14174DF30, 0x16E8, 0x1432F6C30, KEY2, 0x1432F6C88),
    (0x14174D850, 0x1400, 0x1432F6C08, 0x14174B740, 0x1432F6628),
    (0x14174E610, 0x1400, 0x1432F6BE0, 0x141755040, 0x1432F72D8),
    (0x14174ECF0, 0x1400, 0x1432F6BB8, 0x1417551B0, 0x1432F76C8),
)
SCRATCH = ReplayPlayerSavedFactoryScratch(bytes(range(0xD0)), bytes(range(0x48)))


def setup(
    *,
    effect=None,
    read_effect=None,
    write_effect=None,
    atomic_effect=None,
    constructors=True,
    reader=True,
):
    h = SimpleNamespace()
    h.memory = m = ReplayMemory()
    h.receiver, h.out, h.stream, h.aux, h.world, h.index, h.rows = (
        m.allocate(n) for n in (8, 48, 8, 8, 0x800, 4, 64)
    )
    m.write_bytes(h.out, b"O" * 48)
    m.write(h.index, 4, 0)
    m.write_bytes(h.rows, bytes(64))
    m.write(h.world + 0x768, 8, h.rows)
    for _, _, _, _, table in CASES:
        m.map_bytes(table + 0xE8, READER.to_bytes(8, "little"))
    h.frames, h.completed, h.events, h.accesses, h.atomics_log = [], [], [], [], []
    h.objects, h.readers = [], []

    def read(address, width):
        value = m.read(address, width)
        h.accesses.append(("read", address, width, value))
        if read_effect:
            alternate = read_effect(h, address, width, value)
            if alternate is not None:
                return alternate
        return value

    def write(address, width, value):
        h.accesses.append(("write", address, width, value))
        m.write(address, width, value)
        if write_effect:
            write_effect(h, address, width, value)

    def atomic(address, value):
        prior = m.fetch_add_u32(address, value)
        h.atomics_log.append((address, value, prior))
        if atomic_effect:
            atomic_effect(h, address, value, prior)
        return prior

    h.context = ReplayTaskRebuildStorage(h.receiver, read, write)
    h.atomics = ReplayUnitAIMapAtomics(m.compare_exchange_u32, atomic)

    @contextmanager
    def local(view):
        with m.bind_local(view) as address:
            h.frames.append((address, view))
            try:
                yield address
            finally:
                h.completed.append((address, view.tobytes()))
                h.frames.pop()

    h.local = local
    runtime = m.runtime_calls()

    def terminal(target, args, data):
        if target in (PARENT, KEY2) and constructors:
            subject, result, stream, world, index = args
            assert (stream, world) == (h.stream, h.world)
            assert m.read(index, 4) == m.read(h.index, 4)
            h.objects.append((subject, result, index))
            # Declared large-constructor effect; the real thin wrapper installs
            # its own table after this deliberately different parent table.
            m.write(subject, 8, 0x1432F6C88)
            m.write(subject + 8, 8, world)
            return 0xDEADBEEF
        if target == READER and reader:
            h.readers.append(args)
            assert args[2] == h.stream and len(args) == 3
            assert m.read_bytes(args[1], 48) == bytes(48)
            return h.out  # Its address/status must not replace the fixed local.
        assert runtime.call
        return runtime.call(target, args, data)

    h.terminal = ReplayTaskRebuildCalls(terminal)
    lower = bind_replay_saved_apply(h.context, h.terminal, atomics=h.atomics)
    lower = bind_replay_saved_result(h.context, lower, atomics=h.atomics)
    lower = bind_replay_base_saved_registration(
        h.context,
        lower,
        imports=h.terminal,
        fp_calls=ReplayBaseSavedRegistrationFP(None),
        bind_local=local,
        scratch=ReplayBaseSavedRegistrationScratch(bytes(0xB0)),
    )

    def observe(target, args, data):
        h.events.append((target, args))
        if effect:
            result = effect(h, target, args, data)
            if result is not NotImplemented:
                return result
        assert lower.call
        return lower.call(target, args, data)

    h.lower = ReplayTaskRebuildCalls(observe)
    h.bound = bind_replay_player_saved_factory(
        h.context, h.lower, atomics=h.atomics, bind_local=local, scratch=SCRATCH
    )
    return h


def invoke(h, entry=0x14174E610, *, direct=False):
    args = (h.receiver, h.out, h.stream, h.aux, h.world, h.index)
    if direct:
        return create_replay_saved_player(
            h.context,
            entry,
            *args,
            calls=h.bound,
            atomics=h.atomics,
            bind_local=h.local,
            scratch=SCRATCH,
        )
    assert h.bound.call
    return h.bound.call(entry, args, None)


def shared(h, strong=1, weak=1, first=0x1234, second=0x2345):
    m = h.memory
    control, table = m.allocate(16), m.allocate(16)
    m.write(control, 8, table)
    m.write(table, 8, first)
    m.write(table + 8, 8, second)
    m.write(control + 8, 4, strong)
    m.write(control + 12, 4, weak)
    return control


@pytest.mark.parametrize("entry,size,table,constructor,player_table", CASES)
@pytest.mark.parametrize("direct", [False, True])
def test_real_allocation_wrappers_publication_and_fixed_reader_Result(
    entry,
    size,
    table,
    constructor,
    player_table,
    direct,
):
    h = setup()
    assert invoke(h, entry, direct=direct) == h.out
    m = h.memory
    subject, raw, _ = h.objects[0]
    assert m.read(h.rows, 8) == subject
    assert m.read(h.rows + 8, 8) == subject - 16
    assert m.read(subject - 16, 8) == table
    assert m.read(subject - 8, 4) == 1 and m.read(subject - 4, 4) == 1
    assert m.read(subject, 8) == player_table
    assert m.read(subject + 8, 8) == h.world
    assert h.events[0] == (ALLOC, (size,))
    assert h.readers == [(subject, raw - 48, h.stream)]
    assert m.read_bytes(h.out, 48) == bytes(41) + b"O" * 7
    assert [target for target, _ in h.events].count(GETTER) == 2
    assert [target for target, _ in h.events].count(CLEAR) == 3
    assert not h.frames
    frame, snapshot = h.completed[-1]
    assert len(snapshot) == 0xD0
    assert snapshot[0x48:0x50] == (h.out & ~0xFFFFFFFF).to_bytes(8, "little")
    assert snapshot[0x50:0x70] == SCRATCH.handler[0x50:0x70]
    assert snapshot[0xC8] == 1
    assert snapshot[0x20:0x28] == (frame + 0x48).to_bytes(8, "little")


@pytest.mark.parametrize("entry,table", [(row[3], row[4]) for row in CASES[1:]])
def test_wrapper_copies_current_index_keeps_home_upper_word_and_ignores_parent_RAX(entry, table):
    h = setup()
    m = h.memory
    subject = m.allocate(32)
    m.write(h.index, 4, 0xFEDCBA98)
    result = construct_replay_saved_player_variant(
        h.context,
        entry,
        subject,
        h.out,
        h.stream,
        h.world,
        h.index,
        calls=h.lower,
        bind_local=h.local,
        scratch=SCRATCH,
    )
    assert result == subject and m.read(subject, 8) == table
    frame, snapshot = h.completed[-1]
    assert snapshot[0x40:0x48] == ((subject & ~0xFFFFFFFF) | 0xFEDCBA98).to_bytes(8, "little")
    assert snapshot[0x20:0x28] == (frame + 0x40).to_bytes(8, "little")
    assert snapshot[:0x20] == SCRATCH.constructor[:0x20]


def test_constructor_failure_is_checked_after_publication_without_rollback():
    def effect(h, target, args, data):
        if target == PARENT:
            h.memory.write(args[1] + 24, 8, 99)
            return 0
        return NotImplemented

    h = setup(effect=effect)
    with pytest.raises(UnresolvedReplayTaskRebuild, match="constructor Result error TLS"):
        invoke(h)
    m = h.memory
    assert m.read(h.rows, 8) == m.read(h.rows + 8, 8) + 16
    assert m.read(h.rows, 8) != 0 and not h.readers
    assert m.read_bytes(h.out, 48) == b"O" * 48
    assert h.completed[-1][1][0xC8] == 1


def test_null_allocation_publishes_literal_10h_then_reaches_real_access():
    h = setup(effect=lambda h, target, args, data: 0 if target == ALLOC else NotImplemented)
    with pytest.raises(ReplayMemoryError):
        invoke(h)
    assert h.memory.read(h.rows, 8) == 16
    assert h.memory.read(h.rows + 8, 8) == 0
    assert h.objects == [] and h.readers == []
    assert h.memory.read_bytes(h.out, 48) == b"O" * 48


def test_constructor_can_change_original_index_before_publication():
    def effect(h, target, args, data):
        if target == PARENT:
            h.memory.write(h.index, 4, 2)
            h.memory.write(args[0], 8, 0x1432F6C88)
            return 0
        return NotImplemented

    h = setup(effect=effect)
    assert invoke(h) == h.out
    assert h.memory.read(h.rows, 8) == 0
    assert h.readers[0][0] == h.memory.read(h.rows + 32, 8)


def test_old_control_release_sees_published_pair_and_reselects_current_world_row():
    h = setup()
    m = h.memory
    old = shared(h)
    m.write(h.rows + 8, 8, old)
    alternate, control, rows2 = m.allocate(16), shared(h, strong=3), m.allocate(64)
    m.write(alternate, 8, 0x1432F6C88)
    m.write_bytes(rows2, bytes(64))
    m.write(rows2 + 32, 8, alternate)
    m.write(rows2 + 40, 8, control)
    lower = h.lower.call

    def effect(target, args, data):
        if target in (0x1234, 0x2345):
            assert m.read(h.rows, 8) == m.read(h.rows + 8, 8) + 16
            if target == 0x1234:
                m.write(h.world + 0x768, 8, rows2)
                m.write(h.index, 4, 2)
            return None
        assert lower
        return lower(target, args, data)

    h.bound = bind_replay_player_saved_factory(
        h.context,
        ReplayTaskRebuildCalls(effect),
        atomics=h.atomics,
        bind_local=h.local,
        scratch=SCRATCH,
    )
    assert invoke(h) == h.out
    assert h.readers[0][0] == alternate
    assert m.read(old + 8, 4) == 0 and m.read(old + 12, 4) == 0
    assert m.read(control + 8, 4) == 3


def test_selected_control_is_reloaded_after_increment_and_object_after_increment():
    h = setup()
    m = h.memory
    old, replacement = shared(h, strong=3), shared(h, strong=5)
    alternate = m.allocate(16)
    m.write(alternate, 8, 0x1432F6C88)
    original_atomic = h.atomics.fetch_add

    def atomic(address, value):
        assert original_atomic
        prior = original_atomic(address, value)
        if value == 1 and address != replacement + 8:
            m.write(h.rows, 8, alternate)
            m.write(h.rows + 8, 8, replacement)
        return prior

    # A finite callback after actual constructor Result copy selects a distinct
    # current pair, then the acquire callback changes it again.
    getter_count = 0
    lower = h.lower.call

    def observe(target, args, data):
        nonlocal getter_count
        if target == GETTER:
            getter_count += 1
            if getter_count == 2:
                m.write(h.rows + 8, 8, old)
        assert lower
        return lower(target, args, data)

    h.bound = bind_replay_player_saved_factory(
        h.context,
        ReplayTaskRebuildCalls(observe),
        atomics=ReplayUnitAIMapAtomics(None, atomic),
        bind_local=h.local,
        scratch=SCRATCH,
    )
    assert invoke(h) == h.out
    assert h.readers[0][0] == alternate
    assert m.read(old + 8, 4) == 4  # acquired old identity is not the released held identity
    assert m.read(replacement + 8, 4) == 4


def test_current_selected_vptr_is_read_after_full_temporary_zeroing():
    changed = []

    def write_effect(h, address, width, value):
        frame = h.frames[0][0]
        if address == frame + 0x90 and width == 16 and h.objects:
            subject = h.memory.read(h.rows, 8)
            if subject:
                alternate = h.memory.allocate(0xF0)
                h.memory.write(alternate + 0xE8, 8, READER)
                h.memory.write(subject, 8, alternate)
                changed.append(alternate)

    h = setup(write_effect=write_effect)
    assert invoke(h) == h.out
    assert changed and h.memory.read(h.readers[0][0], 8) == changed[-1]


@pytest.mark.parametrize("stage", ["constructor", "reader"])
def test_result_control_lifetimes_use_real_atomics_and_current_destructors(stage):
    controls = []

    def effect(h, target, args, data):
        if target == (PARENT if stage == "constructor" else READER):
            control = shared(h)
            controls.append(control)
            h.memory.write(args[1] + 32, 8, control)
            if target == PARENT:
                h.memory.write(args[0], 8, 0x1432F6C88)
            return h.out
        if target in (0x1234, 0x2345):
            return None
        return NotImplemented

    h = setup(effect=effect)
    assert invoke(h) == h.out
    control = controls[0]
    values = [value for address, value, _ in h.atomics_log if address == control + 8]
    assert values == ([1, 0xFFFFFFFF, 0xFFFFFFFF] if stage == "constructor" else [0xFFFFFFFF])
    assert h.memory.read(control + 8, 4) == 0 and h.memory.read(control + 12, 4) == 0
    assert [target for target, _ in h.events if target in (0x1234, 0x2345)] == [0x1234, 0x2345]


def test_reader_failure_keeps_published_player_and_does_not_clear_output():
    def effect(h, target, args, data):
        if target == READER:
            h.memory.write(args[1] + 24, 8, 7)
            return h.out
        return NotImplemented

    h = setup(effect=effect)
    with pytest.raises(UnresolvedReplayTaskRebuild, match="reader Result error TLS"):
        invoke(h)
    assert h.memory.read(h.rows, 8) and h.memory.read_bytes(h.out, 48) == b"O" * 48
    assert h.memory.read(h.memory.read(h.rows + 8, 8) + 8, 4) == 2


def test_positive_constructor_vector_reaches_actual_copy_growth_frontier():
    def effect(h, target, args, data):
        if target == PARENT:
            begin = h.memory.allocate(32)
            h.memory.write(args[1], 8, begin)
            h.memory.write(args[1] + 8, 8, begin + 32)
            h.memory.write(args[1] + 16, 8, begin + 32)
            h.memory.write(args[0], 8, 0x1432F6C88)
            return 0
        return NotImplemented

    h = setup(effect=effect)
    with pytest.raises(UnresolvedReplayTaskRebuild, match="1402ba380"):
        invoke(h)
    assert h.memory.read(h.rows, 8) and not h.readers
    assert h.completed[-1][1][0xC8] == 0


def test_selected_hold_release_precedes_current_original_Result_control_reload():
    originals = []

    def effect(h, target, args, data):
        if target == PARENT:
            original, replacement = shared(h, strong=3), shared(h, strong=5)
            originals.extend((original, replacement, args[1]))
            h.memory.write(args[1] + 32, 8, original)
            h.memory.write(args[0], 8, 0x1432F6C88)
            return 0
        return NotImplemented

    h = setup(effect=effect)
    m = h.memory
    atomic = h.atomics.fetch_add

    def mutate(address, value):
        assert atomic
        prior = atomic(address, value)
        if value == 0xFFFFFFFF and address == m.read(h.rows + 8, 8) + 8:
            assert m.read_bytes(h.out, 48) == bytes(41) + b"O" * 7
            m.write(originals[2] + 32, 8, originals[1])
        return prior

    h.bound = bind_replay_player_saved_factory(
        h.context,
        h.lower,
        atomics=ReplayUnitAIMapAtomics(None, mutate),
        bind_local=h.local,
        scratch=SCRATCH,
    )
    assert invoke(h) == h.out
    assert m.read(originals[0] + 8, 4) == 3
    assert m.read(originals[1] + 8, 4) == 4


def test_missing_atomic_effect_refuses_after_first_world_publication():
    h = setup()
    old = shared(h, strong=3)
    h.memory.write(h.rows + 8, 8, old)
    h.bound = bind_replay_player_saved_factory(
        h.context,
        h.lower,
        atomics=ReplayUnitAIMapAtomics(None, None),
        bind_local=h.local,
        scratch=SCRATCH,
    )
    with pytest.raises(UnresolvedReplayTaskRebuild, match="atomic effect unavailable"):
        invoke(h)
    assert h.memory.read(h.rows, 8) and h.memory.read(h.rows + 8, 8) != old
    assert h.memory.read(old + 8, 4) == 3
    assert not h.readers


def test_key2_still_requires_its_actual_larger_constructor():
    h = setup(constructors=False)
    with pytest.raises(UnresolvedReplayTaskRebuild, match="14174fa70"):
        invoke(h, CASES[0][0])
    assert h.memory.read(h.rows, 8) == 0


@pytest.mark.parametrize(
    "constructors,reader,target", [(False, True, "1416c2440"), (True, False, "1416f7980")]
)
def test_unavailable_actual_large_children_refuse_at_reached_frontier(constructors, reader, target):
    h = setup(constructors=constructors, reader=reader)
    with pytest.raises(UnresolvedReplayTaskRebuild, match=target):
        invoke(h)
    assert h.memory.read_bytes(h.out, 48) == b"O" * 48


@pytest.mark.parametrize(
    "entry,args,data",
    [
        (0x14174E610, (), None),
        (0x141755040, (0,) * 6, None),
        (0x14174E610, (0,) * 6, memoryview(b"")),
    ],
)
def test_malformed_binding_refuses_without_effects(entry, args, data):
    h = setup()
    assert h.bound.call
    with pytest.raises(ValueError, match="malformed"):
        h.bound.call(entry, args, data)
    assert not h.events and not h.frames


def test_scratch_contract_and_unknown_entry_validation():
    with pytest.raises(ValueError, match="explicit"):
        ReplayPlayerSavedFactoryScratch(bytes(0xCF), bytes(0x48))
    h = setup()
    with pytest.raises(ValueError, match="unsupported"):
        invoke(h, 0x123, direct=True)
