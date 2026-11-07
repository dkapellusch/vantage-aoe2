"""Owned Animated phases; Base is a declared isolated fixture until composed.

Input, Result vector destruction, allocation/free and atomic counts below are
actual existing Python implementations. No fixture Base success is native or
whole-object restoration evidence.
"""

from __future__ import annotations

from contextlib import contextmanager

import pytest

from vantage.replay_animated_saved import (
    bind_replay_animated_saved,
    read_replay_saved_animated,
)
from vantage.replay_memory import ReplayMemory, ReplayMemoryError
from vantage.replay_saved_input import ReplaySavedInput, bind_replay_saved_input
from vantage.replay_saved_result import bind_replay_saved_result
from vantage.replay_saved_string import bind_replay_saved_string
from vantage.replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
)
from vantage.replay_unit_ai_map import ReplayUnitAIMapAtomics

ENTRY, BASE, CLEANUP = 0x141142A70, 0x14125D730, 0x1402BD7F0
IO, SECOND_IO, DESTROY, DISPOSE, NEW_DISPOSE = 0xB510, 0xB520, 0xB530, 0xB540, 0xB550
U64 = (1 << 64) - 1


class Harness:
    def __init__(self, raw=b"\x34\x12\xc0\x7f", *, scratch=b"\xa3" * 0x98):
        self.memory = m = ReplayMemory()
        self.address, self.output, self.stream, self.table = (
            m.allocate(size) for size in (0x380, 48, 8, 32)
        )
        m.write_bytes(self.address, b"D" * 0x380)
        m.write_bytes(self.output, b"O" * 48)
        m.write(self.stream, 8, self.table)
        m.write(self.table + 24, 8, IO)
        m.map_bytes(0x143199DD0, (0x142D6BAB4).to_bytes(8, "little"))
        self.opaque = 0xFEDCBA9876543210
        self.scratch = scratch
        self.events, self.storage, self.locals, self.completed = [], [], [], []
        self.missing, self.providers = set(), {}
        self.before = lambda target, args: None
        self.after = lambda target, args: None
        self.parent_effect = lambda args: None
        self.parent_status, self.input_status = 0, 0
        self.parent_control, self.input_control = 0, 0
        self.context = ReplayTaskRebuildStorage(self.address, self.read, self.write)
        self.atomics = ReplayUnitAIMapAtomics(m.compare_exchange_u32, m.fetch_add_u32)
        self.source = ReplaySavedInput(raw)
        runtime = m.runtime_calls()
        self.io = bind_replay_saved_input(
            self.context,
            runtime,
            self.source,
            stream=self.stream,
            target=IO,
            result_bytes=bytes(48),
        )
        strings = bind_replay_saved_string(self.context, self.io, imports=runtime)
        self.lower = bind_replay_saved_result(
            self.context, strings, atomics=self.atomics, imports=runtime
        )
        self.calls = ReplayTaskRebuildCalls(self.call)
        self.bound = bind_replay_animated_saved(
            self.context,
            self.calls,
            atomics=self.atomics,
            bind_local=self.bind_local,
            scratch=scratch,
        )

    def read(self, address, width):
        value = self.memory.read(address, width)
        self.storage.append(("read", address, width, value))
        return value

    def write(self, address, width, value):
        self.storage.append(("write", address, width, value))
        self.memory.write(address, width, value)

    @contextmanager
    def bind_local(self, view):
        with self.memory.bind_local(view) as address:
            self.locals.append((address, view))
            try:
                yield address
            finally:
                self.completed.append(view.tobytes())

    def call(self, target, args, data):
        self.events.append((target, args, data))
        self.before(target, args)
        if target in self.missing:
            raise UnresolvedReplayTaskRebuild(f"declared missing{target:x}")
        if target == BASE:
            assert data is None and len(args) == 4
            # Deliberately isolated parent effect; production composition must
            # replace this entire fixture with the actual Base implementation.
            assert self.memory.read_bytes(args[1], 48) == bytes(48)
            self.memory.write(self.address + 15, 1, 10)
            self.memory.write(args[1] + 24, 8, self.parent_status)
            self.memory.write(args[1] + 32, 8, self.parent_control)
            self.parent_effect(args)
            answer = 0xBAD0  # Native caller ignores Base's RAX.
        elif target in self.providers:
            answer = self.providers[target](args, data)
        else:
            assert self.lower.call is not None
            answer = self.lower.call(IO if target == SECOND_IO else target, args, data)
            if target in (IO, SECOND_IO):
                self.memory.write(args[1] + 24, 8, self.input_status)
                self.memory.write(args[1] + 32, 8, self.input_control)
        self.after(target, args)
        return answer

    def invoke(self, *, direct=False, **changes):
        values = dict(
            context=self.context,
            address=self.address,
            output=self.output,
            stream=self.stream,
            opaque=self.opaque,
            calls=self.calls,
            atomics=self.atomics,
            bind_local=self.bind_local,
            scratch=self.scratch,
        )
        values.update(changes)
        if direct or changes:
            return read_replay_saved_animated(**values)
        assert self.bound.call is not None
        return self.bound.call(ENTRY, (self.address, self.output, self.stream, self.opaque), None)

    def control(self, strong=1, weak=1):
        m = self.memory
        control, table, replacement = (m.allocate(16) for _ in range(3))
        m.write(control, 8, table)
        m.write(control + 8, 4, strong)
        m.write(control + 12, 4, weak)
        m.write(table, 8, DESTROY)
        m.write(table + 8, 8, DISPOSE)
        m.write(replacement + 8, 8, NEW_DISPOSE)
        self.providers[DESTROY] = lambda args, data: None
        self.providers[DISPOSE] = lambda args, data: None
        self.providers[NEW_DISPOSE] = lambda args, data: None
        return control, replacement


@pytest.mark.parametrize("direct", [False, True])
@pytest.mark.parametrize("seed", [0, 0xA3])
def test_full_normal_phase_order_exact_fourargs_and_padding(direct, seed):
    h = Harness(scratch=bytes([seed]) * 0x98)
    assert h.invoke(direct=direct) == h.output
    frame = h.locals[0][0]
    result = frame + 0x68
    assert [target for target, _, _ in h.events] == [BASE, CLEANUP, IO, CLEANUP]
    assert h.events[0][1] == (h.address, result, h.stream, h.opaque)
    assert h.events[2][1] == (h.stream, result, h.address + 0x350, 4)
    assert all(data is None for _, _, data in h.events)
    assert h.memory.read(h.address + 15, 1) == 20
    assert h.memory.read(h.address + 0x350, 4) == 0x7FC01234
    assert h.source.position == 4
    assert h.memory.read_bytes(h.output, 41) == bytes(41)
    assert h.memory.read_bytes(h.output + 41, 7) == b"O" * 7
    assert h.memory.read_bytes(h.address + 0x354, 0x2C) == b"D" * 0x2C
    assert h.completed[0][:0x60] == bytes([seed]) * 0x60
    assert h.completed[0][0x60:0x68] == h.output.to_bytes(8, "little")
    assert h.completed[0][0x68:0x90] == bytes(40)
    assert h.completed[0][0x90] == 1
    assert h.completed[0][0x91:] == bytes(7)
    with pytest.raises(ReplayMemoryError, match="unmapped"):
        h.memory.read(frame, 1)


@pytest.mark.parametrize("opaque", [0, U64, 0x8000000000000000])
def test_opaque_fourth_argument_is_not_dereferenced_or_narrowed(opaque):
    h = Harness()
    h.invoke(opaque=opaque)
    assert h.events[0][1][3] == opaque


def test_missing_parent_does_not_initialize_subject_or_report_success():
    h = Harness()
    h.missing.add(BASE)
    with pytest.raises(UnresolvedReplayTaskRebuild, match="14125d730"):
        h.invoke()
    assert h.memory.read_bytes(h.address, 0x380) == b"D" * 0x380
    assert h.memory.read_bytes(h.output, 48) == b"O" * 48
    assert h.source.position == 0
    assert h.completed[0][0x68:] == bytes(48)


@pytest.mark.parametrize("phase", ["parent", "input"])
@pytest.mark.parametrize("status", [1, 0x100000000, U64])
def test_returned_error_refuses_before_metadata_processed_or_control_cleanup(phase, status):
    h = Harness()
    control, _ = h.control()
    if phase == "parent":
        h.parent_status, h.parent_control = status, control
    else:
        h.input_status, h.input_control = status, control
    with pytest.raises(UnresolvedReplayTaskRebuild, match="returned-error metadata/TLS"):
        h.invoke()
    assert h.memory.read(control + 8, 4) == 1
    assert h.completed[0][0x80:0x88] == status.to_bytes(8, "little")
    assert h.completed[0][0x90] == 0
    assert h.memory.read_bytes(h.output, 48) == b"O" * 48
    assert h.memory.read(h.address + 15, 1) == (10 if phase == "parent" else 20)
    assert h.source.position == (0 if phase == "parent" else 4)
    assert len([1 for target, _, _ in h.events if target == CLEANUP]) == (phase == "input")


@pytest.mark.parametrize("which", [1, 2])
def test_missing_current_vector_cleanup_preserves_processed_and_prior_effects(which):
    h = Harness()
    reached = 0

    def before(target, args):
        nonlocal reached
        if target == CLEANUP:
            reached += 1
            if reached == which:
                raise RuntimeError("cleanup unavailable")

    h.before = before
    with pytest.raises(RuntimeError, match="cleanup unavailable"):
        h.invoke()
    assert h.completed[0][0x90] == 1
    assert h.source.position == (0 if which == 1 else 4)
    assert h.memory.read(h.address + 15, 1) == (10 if which == 1 else 20)
    assert h.memory.read_bytes(h.output, 48) == b"O" * 48


@pytest.mark.parametrize("change_at", [BASE, CLEANUP])
def test_stream_vptr_and_slot_are_loaded_after_parent_and_its_cleanup(change_at):
    h = Harness()
    replacement = h.memory.allocate(32)
    h.memory.write(replacement + 24, 8, SECOND_IO)

    def after(target, args):
        if target == change_at:
            h.memory.write(h.stream, 8, replacement)

    h.after = after
    h.invoke()
    assert [target for target, _, _ in h.events] == [BASE, CLEANUP, SECOND_IO, CLEANUP]


def test_subject_read_is_preserved_even_when_input_result_cannot_be_written():
    h = Harness()

    def fail_result(address, width, value):
        if width == 48:
            raise RuntimeError("result write failed")
        h.write(address, width, value)

    context = ReplayTaskRebuildStorage(h.address, h.read, fail_result)
    # Bind Input to the failing context; parent/Animated use the same storage.
    h.io = bind_replay_saved_input(
        context,
        h.memory.runtime_calls(),
        h.source,
        stream=h.stream,
        target=IO,
        result_bytes=bytes(48),
    )
    strings = bind_replay_saved_string(context, h.io)
    h.lower = bind_replay_saved_result(context, strings, atomics=h.atomics)
    with pytest.raises(RuntimeError, match="result write failed"):
        h.invoke(context=context)
    assert h.source.position == 4 and h.memory.read(h.address + 0x350, 4) == 0x7FC01234
    assert h.memory.read(h.address + 15, 1) == 20
    assert h.memory.read_bytes(h.output, 48) == b"O" * 48


def test_short_input_keeps_parent_effects_and_animated_tag_without_output_success():
    h = Harness(b"\x01\x02\x03")
    with pytest.raises(UnresolvedReplayTaskRebuild, match="exceeds remaining"):
        h.invoke()
    assert h.source.position == 0
    assert h.memory.read(h.address + 15, 1) == 20
    assert h.memory.read(h.address + 0x350, 4) == 0x44444444
    assert h.memory.read_bytes(h.output, 48) == b"O" * 48


@pytest.mark.parametrize("phase", ["parent", "input"])
@pytest.mark.parametrize(
    "strong,weak,expected", [(1, 1, [DESTROY, DISPOSE]), (2, 1, []), (0, 1, []), (1, 2, [DESTROY])]
)
def test_actual_shared_count_gates_in_both_result_phases(phase, strong, weak, expected):
    h = Harness()
    control, _ = h.control(strong, weak)
    setattr(h, phase + "_control", control)
    h.invoke()
    assert [target for target, _, _ in h.events if target in (DESTROY, DISPOSE)] == expected
    assert h.memory.read(control + 8, 4) == (strong - 1) & 0xFFFFFFFF
    assert h.memory.read(control + 12, 4) == ((weak - 1) if strong == 1 else weak)


def test_destroy_uses_held_control_but_dispose_refetches_current_vptr():
    h = Harness()
    held, replacement = h.control()
    other, _ = h.control(7, 9)
    h.parent_control = held

    def destroy(args, data):
        assert args == (held,) and data is None
        result = h.events[0][1][1]
        h.memory.write(result + 32, 8, other)
        h.memory.write(held, 8, replacement)

    h.providers[DESTROY] = destroy
    h.invoke()
    assert [target for target, _, _ in h.events if target in (DESTROY, DISPOSE, NEW_DISPOSE)] == [
        DESTROY,
        NEW_DISPOSE,
    ]
    assert h.memory.read(other + 8, 4) == 7
    assert h.memory.read(other + 12, 4) == 9


def test_real_result_vector_cleanup_frees_parent_storage_and_clears_before_next_read():
    h = Harness()
    vector = h.memory.allocate(64)
    for offset in (24, 56):
        h.memory.write(vector + offset, 8, 15)  # actual inline string destructors

    def parent(args):
        for offset, value in ((0, vector), (8, vector + 64), (16, vector + 64)):
            h.memory.write(args[1] + offset, 8, value)

    h.parent_effect = parent
    h.invoke()
    with pytest.raises(ReplayMemoryError, match="unmapped"):
        h.memory.read(vector, 1)
    assert h.completed[0][0x68:0x90] == bytes(40)


def test_cleanup_mutations_do_not_trigger_a_new_status_check_or_restore_read_field():
    h = Harness()
    count = 0

    def after(target, args):
        nonlocal count
        if target == CLEANUP:
            count += 1
            h.memory.write(args[0] + 24, 8, U64)
            h.memory.write(h.address + 15, 1, 0x7F)
            if count == 2:
                h.memory.write(h.address + 0x350, 4, 0x80000000)

    h.after = after
    h.invoke()
    assert h.memory.read(h.address + 15, 1) == 0x7F
    assert h.memory.read(h.address + 0x350, 4) == 0x80000000
    assert h.memory.read_bytes(h.output, 41) == bytes(41)
    assert h.completed[0][0x80:0x88] == U64.to_bytes(8, "little")


@pytest.mark.parametrize("bad", [b"", bytes(0x97), bytes(0x99), bytearray(0x98), None])
def test_invalid_scratch_is_rejected_before_any_effect(bad):
    h = Harness()
    with pytest.raises(ValueError, match="local seed"):
        h.invoke(scratch=bad)
    assert h.events == [] and h.storage == [] and h.locals == []


@pytest.mark.parametrize("bad", [(), (1,), (1, 2, 3), (1, 2, 3, 4, 5)])
def test_bound_arity_requires_effective_four_arguments(bad):
    h = Harness()
    with pytest.raises(ValueError, match="malformed"):
        h.bound.call(ENTRY, bad, None)
    assert h.events == []


def test_unknown_bound_call_preserves_args_and_live_view():
    h = Harness()
    view = memoryview(bytearray(b"original"))
    seen = []

    def fallback(target, args, data):
        seen.append((target, args, data))
        data[0] = 0x58
        return U64

    bound = bind_replay_animated_saved(
        h.context,
        ReplayTaskRebuildCalls(fallback),
        atomics=h.atomics,
        bind_local=h.bind_local,
        scratch=h.scratch,
    )
    assert bound.call(0xABC, (7, U64), view) == U64
    assert seen == [(0xABC, (7, U64), view)] and view.tobytes() == b"Xriginal"


def test_unavailable_fallback_and_live_data_for_known_entry_refuse():
    h = Harness()
    bound = bind_replay_animated_saved(
        h.context,
        ReplayTaskRebuildCalls(None),
        atomics=h.atomics,
        bind_local=h.bind_local,
        scratch=h.scratch,
    )
    with pytest.raises(UnresolvedReplayTaskRebuild, match="abc"):
        bound.call(0xABC, (), None)
    with pytest.raises(ValueError, match="malformed"):
        bound.call(ENTRY, (h.address, h.output, h.stream, h.opaque), memoryview(bytearray(1)))
