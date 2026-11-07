"""Source-led constructor controls; explicit reader responses are authored seams.

The35008B reader is unavailable by default and is never implemented here.
Tests explicitly choose its output/return effects to isolate this218B caller.
Existing source-backed pair/vector/finalizer/string bodies perform actual effects.
"""

from __future__ import annotations

from contextlib import contextmanager

import pytest

from vantage import replay_player_auxiliary as auxiliary
from vantage.replay_memory import ReplayMemory, ReplayMemoryError
from vantage.replay_saved_apply import bind_replay_saved_apply
from vantage.replay_saved_pair import bind_replay_saved_pair
from vantage.replay_saved_result import bind_replay_saved_result
from vantage.replay_saved_string import bind_replay_saved_string
from vantage.replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
)
from vantage.replay_unit_ai_map import ReplayUnitAIMapAtomics

CTOR, READER, PAIR, COPY, CLEANUP = 0x14149D9A0, 0x1414AEA70, 0x14090D270, 0x1402B9080, 0x1402BD890
FREE, ELEMENT = 0x142D6BAB4, 0x1402A88A0
U64 = (1 << 64) - 1
STORES = (
    (8, 8, 0),
    (24, 8, 0),
    (40, 8, 0),
    (56, 8, 0),
    (0, 1, 0),
    (16, 1, 0),
    (32, 2, 0),
    (48, 1, 0),
    (64, 4, 0xFFFFFFFF),
    (68, 4, 0),
)


class Fixture:
    def __init__(self, *, seed=b"\xa5" * 48, subject_defined=True):
        self.memory = ReplayMemory(max_bytes=2 << 20)
        self.subject, self.output, self.stream = (
            self.memory.allocate(72),
            self.memory.allocate(48),
            self.memory.allocate(8),
        )
        if subject_defined:
            self.memory.fill(self.subject, 0xA5, 72)
        self.memory.fill(self.output, 0xA5, 48)
        self.result(self.output)
        self.events, self.effects, self.routes, self.active, self.closed = [], {}, {}, {}, []
        self.reader = None
        self.on_read = self.on_write = None
        self.temporary = 0
        self.context = ReplayTaskRebuildStorage(self.subject, self.read, self.write)
        self.calls, self.imports = (
            ReplayTaskRebuildCalls(self.dispatch),
            ReplayTaskRebuildCalls(self.terminal),
        )
        self.primitive = self.memory.runtime_calls()
        self.atomics = ReplayUnitAIMapAtomics(None, self.atomic)
        self.scratch = auxiliary.ReplayPlayerAuxiliaryScratch(seed)
        self.bound = auxiliary.bind_replay_player_auxiliary(
            self.context,
            self.calls,
            atomics=self.atomics,
            bind_local=self.bind_local,
            scratch=self.scratch,
        )
        self.routes[PAIR] = bind_replay_saved_pair(self.context, self.calls, atomics=self.atomics)
        self.routes[COPY] = bind_replay_saved_apply(
            self.context, self.calls, atomics=self.atomics, imports=self.imports
        )
        finalizer = bind_replay_saved_result(
            self.context, self.calls, atomics=self.atomics, imports=self.imports
        )
        for target in (CLEANUP, 0x1402BD7F0):
            self.routes[target] = finalizer
        self.routes[ELEMENT] = bind_replay_saved_string(
            self.context, self.calls, imports=self.imports
        )
        self.memory.map_bytes(0x143199DD0, FREE.to_bytes(8, "little"))

    def result(self, address, *, status=0, control=0, vector=0, count=0, capacity=0):
        for offset, value in (
            (0, vector),
            (8, vector + count * 32),
            (16, vector + capacity * 32),
            (24, status),
            (32, control),
        ):
            self.memory.write(address + offset, 8, value)
        self.memory.write(address + 40, 1, 0)

    def extra_result(self, **kwargs):
        address = self.memory.allocate(48)
        self.memory.fill(address, 0xC7, 48)
        self.result(address, **kwargs)
        return address

    def control(self, strong=1, weak=1, destroy=0xD0, dispose=0xD8):
        control, table = self.memory.allocate(16), self.memory.allocate(16)
        self.memory.write(control, 8, table)
        self.memory.write(control + 8, 4, strong)
        self.memory.write(control + 12, 4, weak)
        self.memory.write(table, 8, destroy)
        self.memory.write(table + 8, 8, dispose)
        return control, table

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
        previous = self.memory.fetch_add_u32(address, value)
        self.events.append(("a", address, value, previous))
        return previous

    @contextmanager
    def bind_local(self, view):
        with self.memory.bind_local(view) as address:
            self.temporary = address
            self.active[address] = view
            self.events.append(("local", address, bytes(view)))
            try:
                yield address
            finally:
                self.closed.append((address, bytes(view)))
                del self.active[address]

    def terminal(self, target, args, data):
        self.events.append(("i", target, args))
        if target in self.effects:
            return self.effects[target](args)
        assert self.primitive.call is not None
        return self.primitive.call(target, args, data)

    def real(self, target, args):
        assert self.routes[target].call is not None
        return self.routes[target].call(target, args, None)

    def dispatch(self, target, args, data):
        self.events.append(("c", target, args))
        if target in self.effects:
            return self.effects[target](args)
        if target == READER:
            if self.reader is None:
                raise UnresolvedReplayTaskRebuild("actual1414aea70 unavailable")
            return self.reader(args)
        if target in self.routes:
            assert self.routes[target].call is not None
            return self.routes[target].call(target, args, data)
        assert self.primitive.call is not None
        return self.primitive.call(target, args, data)

    def respond(self, *, returned=None, status=0, control=0):
        """Explicit authored child seam; never an implementation of1414aea70."""

        def reader(args):
            assert args == (self.subject, self.temporary, self.stream)
            assert self.memory.read_bytes(self.temporary, 48) == self.scratch.frame
            assert self.active[self.temporary]
            self.result(self.temporary, status=status, control=control)
            return self.temporary if returned is None else returned

        self.reader = reader

    def run(self, *, stream=None, output=None):
        assert self.bound.call is not None
        return self.bound.call(
            CTOR,
            (
                self.subject,
                self.output if output is None else output,
                self.stream if stream is None else stream,
            ),
            None,
        )


def expected_subject(seed=0xA5):
    result = bytearray([seed] * 72)
    for offset, width, value in STORES:
        result[offset : offset + width] = value.to_bytes(width, "little")
    return bytes(result)


def test_null_stream_exact_ordered45bytes_and27_untouched_bytes_output_preserved():
    f = Fixture()
    before = f.memory.read_bytes(f.output, 48)
    assert f.run(stream=0) == f.subject
    assert f.memory.read_bytes(f.subject, 72) == expected_subject()
    assert f.memory.read_bytes(f.output, 48) == before
    assert f.events == [("w", f.subject + off, width, value) for off, width, value in STORES]
    selected = {i for off, width, _ in STORES for i in range(off, off + width)}
    assert len(selected) == 45 and 72 - len(selected) == 27
    assert not f.active and not f.closed


def test_null_stream_leaves_unwritten_subject_bytes_undefined():
    f = Fixture(subject_defined=False)
    f.run(stream=0, output=U64)
    assert f.memory.read(f.subject + 64, 4) == 0xFFFFFFFF
    with pytest.raises(ReplayMemoryError, match="undefined"):
        f.memory.read(f.subject + 1, 1)


def test_null_stream_output_subject_alias_retains_actual_initial_store_effects():
    f = Fixture()
    f.run(stream=0, output=f.subject)
    assert f.memory.read_bytes(f.subject, 72) == expected_subject()


def test_missing_reader_refuses_after_initialization_without_output_synthesis():
    f = Fixture()
    output = f.memory.read_bytes(f.output, 48)
    with pytest.raises(UnresolvedReplayTaskRebuild, match="actual1414aea70"):
        f.run()
    assert f.memory.read_bytes(f.subject, 72) == expected_subject()
    assert f.memory.read_bytes(f.output, 48) == output
    assert f.closed[-1][1] == b"\xa5" * 48
    assert [e[1] for e in f.events if e[0] == "c"] == [READER]


@pytest.mark.parametrize("seed", [bytes(48), b"\xa5" * 48, bytes(range(48))])
def test_explicit_live_seed_real_empty_pair_copy_and_finalizer(seed):
    f = Fixture(seed=seed)
    f.respond()
    assert f.run() == f.subject
    assert f.memory.read_bytes(f.output, 41) == bytes(41)
    assert f.memory.read_bytes(f.output + 41, 7) == b"\xa5" * 7
    assert f.closed[-1][1][41:] == seed[41:]
    assert not f.active
    assert [e[1] for e in f.events if e[0] == "c"] == [READER, PAIR, COPY, CLEANUP]


def test_reader_returned_output_alias_still_calls_pair_but_skips_vector():
    f = Fixture()
    control, _ = f.control(strong=3)
    f.result(f.output, status=7, control=control)
    f.respond(returned=f.output)
    assert f.run() == f.subject
    assert f.memory.read(f.output + 24, 8) == 7
    assert f.memory.read(f.output + 40, 1) == 0
    assert f.memory.read(control + 8, 4) == 3
    assert [e[1] for e in f.events if e[0] == "c"] == [READER, PAIR, CLEANUP]


def test_actual_returned_result_differs_from_fixed_local_and_error_status_still_returns():
    f = Fixture()
    control, _ = f.control(strong=2)
    returned = f.extra_result(status=0xDEAD, control=control)
    f.respond(returned=returned)
    assert f.run() == f.subject
    assert f.memory.read(f.output + 24, 8) == 0xDEAD
    assert f.memory.read(f.output + 32, 8) == control
    assert f.memory.read(f.output + 40, 1) == 0
    assert f.memory.read(returned + 40, 1) == 1
    assert f.memory.read(control + 8, 4) == 3
    assert not any(e[0] == "a" and e[1] == control + 12 for e in f.events)


def test_fixed_local_control_released_instead_of_distinct_returned_control():
    f = Fixture()
    fixed, _ = f.control()
    different, _ = f.control(strong=3, destroy=0xE0, dispose=0xE8)
    returned = f.extra_result(status=9, control=different)
    f.effects[0xD0] = f.effects[0xD8] = lambda args: None
    f.respond(returned=returned, control=fixed)
    f.run()
    assert f.memory.read(fixed + 8, 4) == f.memory.read(fixed + 12, 4) == 0
    assert f.memory.read(different + 8, 4) == 4
    assert f.memory.read(different + 12, 4) == 1
    assert [e[1] for e in f.events if e[0] == "c" and e[1] in (0xD0, 0xD8)] == [0xD0, 0xD8]


def test_pair_old_control_callback_can_replace_current_fixed_control_before_cleanup():
    f = Fixture()
    old, _ = f.control()
    original, _ = f.control(strong=2)
    replacement, _ = f.control(destroy=0xE0, dispose=0xE8)
    f.result(f.output, control=old)

    def old_destroy(args):
        f.memory.write(f.temporary + 32, 8, replacement)

    f.effects[0xD0] = old_destroy
    for target in (0xD8, 0xE0, 0xE8):
        f.effects[target] = lambda args: None
    f.respond(control=original)
    f.run()
    assert f.memory.read(original + 8, 4) == 3
    assert f.memory.read(replacement + 8, 4) == 0
    assert f.memory.read(replacement + 12, 4) == 0


def test_release_holds_control_and_reloads_current_weak_vptr():
    f = Fixture()
    held, _ = f.control()
    replacement, new_table = f.control(destroy=0xE0, dispose=0xE8)
    returned = f.extra_result()

    def destroy(args):
        assert args == (held,)
        assert f.temporary in f.active
        f.memory.write(held, 8, new_table)
        f.memory.write(f.temporary + 32, 8, replacement)

    f.effects[0xD0] = destroy
    f.effects[0xE8] = lambda args: None
    f.respond(returned=returned, control=held)
    f.run()
    assert ("c", 0xE8, (held,)) in f.events
    assert f.memory.read(replacement + 8, 4) == 1
    assert f.memory.read(replacement + 12, 4) == 1


@pytest.mark.parametrize("strong,weak,expected", [(3, 1, []), (1, 2, [0xD0]), (1, 1, [0xD0, 0xD8])])
def test_constructor_shared_cleanup_strong_weak_branches(strong, weak, expected):
    f = Fixture()
    fixed, _ = f.control(strong, weak)
    returned = f.extra_result()
    for target in expected:
        f.effects[target] = lambda args: None
    f.respond(returned=returned, control=fixed)
    f.run()
    assert [e[1] for e in f.events if e[0] == "c" and e[1] in (0xD0, 0xD8)] == expected
    assert f.memory.read(fixed + 8, 4) == strong - 1
    assert f.memory.read(fixed + 12, 4) == weak - (strong == 1)


def test_current_returned_vector_header_is_read_after_real_pair_callback():
    f = Fixture()
    old, _ = f.control()
    f.result(f.output, control=old)
    returned = f.extra_result(vector=0x500, count=1, capacity=1)

    def mutate(args):
        f.memory.write(returned, 8, 0x400)
        f.memory.write(returned + 8, 8, 0x400)

    f.effects[0xD0] = mutate
    f.effects[0xD8] = lambda args: None
    f.respond(returned=returned)
    f.run()
    assert ("c", COPY, (f.output, 0x400, 0)) in f.events


@pytest.mark.parametrize("begin,end,count", [(0x1000, 0x1060, 3), (0x200, 0x1E0, U64)])
def test_vector_count_boundary_uses_current_ordered_reads_and_wrapped_SAR5(begin, end, count):
    f = Fixture()
    returned = f.extra_result(vector=begin)
    f.memory.write(returned + 8, 8, begin)

    def mutate(address, width, value):
        if address == returned and width == 8:
            f.memory.write(returned + 8, 8, end)

    f.on_read = mutate
    captured = []
    # Explicit child-boundary capture; no complete vector restoration is claimed.
    f.effects[COPY] = lambda args: captured.append(args)
    f.respond(returned=returned)
    f.run()
    assert captured == [(f.output, begin, count)]


@pytest.mark.parametrize("target", [PAIR, COPY, CLEANUP])
def test_incidental_children_returns_ignored_with_real_effects(target):
    f = Fixture()

    def effect(args):
        f.real(target, args)
        return -7

    f.effects[target] = effect
    f.respond()
    assert f.run() == f.subject


def test_real_finalizer_frees_nonnull_empty_fixed_vector_while_local_live():
    f = Fixture()
    vector = f.memory.allocate(32)
    returned = f.extra_result()

    def reader(args):
        f.result(f.temporary, vector=vector, capacity=1)
        return returned

    def free(args):
        assert args == (vector, 32) and f.temporary in f.active
        f.memory.free(vector)

    f.reader, f.effects[FREE] = reader, free
    f.run()
    assert f.closed[-1][1][:24] == bytes(24)


def test_real_finalizer_destroys_SSO_element_before_free_and_preserves_padding():
    f = Fixture()
    vector = f.memory.allocate(32)
    f.memory.fill(vector, 0xA5, 32)
    f.memory.write_bytes(vector, b"abc\0")
    f.memory.write(vector + 16, 8, 3)
    f.memory.write(vector + 24, 8, 15)

    def reader(args):
        f.result(f.temporary, vector=vector, count=1, capacity=1)
        return f.output

    def free(args):
        assert f.memory.read(vector, 1) == 0
        assert f.memory.read(vector + 16, 8) == 0
        assert f.memory.read(vector + 24, 8) == 15
        assert f.memory.read_bytes(vector + 4, 12) == b"\xa5" * 12
        f.memory.free(vector)

    f.reader, f.effects[FREE] = reader, free
    f.run()
    assert ("c", ELEMENT, (vector,)) in f.events
    assert f.closed[-1][1][:24] == bytes(24)


@pytest.mark.parametrize("target", [PAIR, COPY, CLEANUP])
def test_missing_result_children_stop_at_actual_frontier_preserving_prior_effects(target):
    f = Fixture()
    returned = f.extra_result(status=7)
    f.memory.write(f.output + 40, 1, 0xAA)

    def fail(args):
        raise UnresolvedReplayTaskRebuild(f"actual{target:x} unavailable")

    f.effects[target] = fail
    f.respond(returned=returned)
    with pytest.raises(UnresolvedReplayTaskRebuild, match=f"actual{target:x}"):
        f.run()
    assert f.memory.read(returned + 40, 1) == 1
    assert f.memory.read(f.output + 24, 8) == (0 if target == PAIR else 7)
    assert f.memory.read(f.output + 40, 1) == (0 if target == CLEANUP else 0xAA)
    assert not f.active


def test_missing_deeper_vector_copy_provider_is_not_replaced_with_success():
    f = Fixture()
    returned = f.extra_result(vector=0x500, count=1, capacity=1)
    f.respond(returned=returned)
    with pytest.raises(UnresolvedReplayTaskRebuild, match="1402ba380"):
        f.run()
    assert f.memory.read(returned + 40, 1) == 1


@pytest.mark.parametrize("missing", ["atomic", "destroy", "dispose"])
def test_missing_cleanup_effects_preserve_exact_prior_decrements(missing):
    f = Fixture()
    control, _ = f.control()
    returned = f.extra_result()
    f.respond(returned=returned, control=control)
    if missing == "atomic":
        f.bound = auxiliary.bind_replay_player_auxiliary(
            f.context,
            f.calls,
            atomics=ReplayUnitAIMapAtomics(None, None),
            bind_local=f.bind_local,
            scratch=f.scratch,
        )
    elif missing == "dispose":
        f.effects[0xD0] = lambda args: None
    with pytest.raises(UnresolvedReplayTaskRebuild):
        f.run()
    assert f.memory.read(control + 8, 4) == (1 if missing == "atomic" else 0)
    assert f.memory.read(control + 12, 4) == (0 if missing == "dispose" else 1)
    assert f.memory.read(f.output + 40, 1) == 0
    assert not any(e[0] == "c" and e[1] == CLEANUP for e in f.events)


@pytest.mark.parametrize("returned", [None, -1, 1 << 64, True])
def test_reader_must_return_actual_raw_pointer(returned):
    f = Fixture()
    f.reader = lambda args: returned
    with pytest.raises(ValueError, match=r"raw scalar|raw unsigned64"):
        f.run()
    assert f.memory.read_bytes(f.subject, 72) == expected_subject()
    assert not any(e[0] == "c" and e[1] == PAIR for e in f.events)


def test_binding_only_owns_constructor_and_delegates_unknown_data_unchanged():
    f = Fixture()
    view = memoryview(bytearray(3))
    seen = []

    def delegate(target, args, data):
        seen.append((target, args, data))
        return 17

    bound = auxiliary.bind_replay_player_auxiliary(
        f.context,
        ReplayTaskRebuildCalls(delegate),
        atomics=f.atomics,
        bind_local=f.bind_local,
        scratch=f.scratch,
    )
    assert bound.call is not None
    assert bound.call(READER, (1, 2, 3), view) == 17
    assert seen == [(READER, (1, 2, 3), view)]


def test_binding_missing_unknown_dispatcher_refuses():
    f = Fixture()
    bound = auxiliary.bind_replay_player_auxiliary(
        f.context,
        ReplayTaskRebuildCalls(None),
        atomics=f.atomics,
        bind_local=f.bind_local,
        scratch=f.scratch,
    )
    assert bound.call is not None
    with pytest.raises(UnresolvedReplayTaskRebuild, match="1414aea70"):
        bound.call(READER, (), None)


@pytest.mark.parametrize("args,data", [((1, 2), None), ((1, 2, 3), memoryview(bytearray(1)))])
def test_malformed_constructor_call_rejected_before_stores(args, data):
    f = Fixture()
    assert f.bound.call is not None
    with pytest.raises(ValueError, match="malformed"):
        f.bound.call(CTOR, args, data)
    assert not f.events


@pytest.mark.parametrize("value", [-1, 1 << 64, True])
def test_constructor_requires_raw_u64(value):
    f = Fixture()
    assert f.bound.call is not None
    with pytest.raises(ValueError, match="raw unsigned64"):
        f.bound.call(CTOR, (f.subject, f.output, value), None)
    assert not f.events


@pytest.mark.parametrize("seed", [b"", bytes(47), bytes(49), bytearray(48)])
def test_scratch_requires_explicit_exact_bytes(seed):
    with pytest.raises(ValueError, match="explicit48-byte"):
        auxiliary.ReplayPlayerAuxiliaryScratch(seed)


def test_free_callback_can_mutate_returned_output_without_recopy_or_status_guard():
    f = Fixture()
    vector = f.memory.allocate(32)
    f.result(f.output, status=7)

    def reader(args):
        f.result(f.temporary, vector=vector, capacity=1)
        return f.output

    def free(args):
        assert args == (vector, 32) and f.temporary in f.active
        f.memory.write(f.output + 24, 8, 0x99)
        f.memory.write(f.subject, 1, 0x12)
        f.memory.free(vector)

    f.reader, f.effects[FREE] = reader, free
    assert f.run() == f.subject
    assert f.memory.read(f.output + 24, 8) == 0x99
    assert f.memory.read(f.subject, 1) == 0x12
    assert f.memory.read(f.output + 40, 1) == 0


def test_strong_callback_can_replace_current_fixed_vector_before_real_cleanup():
    f = Fixture()
    control, _ = f.control()
    vector = f.memory.allocate(32)
    returned = f.extra_result()

    def destroy(args):
        assert f.temporary in f.active
        for offset, value in ((0, vector), (8, vector), (16, vector + 32)):
            f.memory.write(f.temporary + offset, 8, value)

    f.effects[0xD0], f.effects[0xD8] = destroy, lambda args: None
    f.respond(returned=returned, control=control)
    f.run()
    assert ("i", FREE, (vector, 32)) in f.events
    assert f.closed[-1][1][:24] == bytes(24)
    with pytest.raises(ReplayMemoryError):
        f.memory.read(vector, 1)
