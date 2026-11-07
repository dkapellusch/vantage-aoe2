"""Source-led owned Input/Result controls; opaque effects are explicitly labeled."""

from __future__ import annotations

from contextlib import contextmanager

import pytest

from vantage import replay_player_fixed_dword_serializer as reader
from vantage.replay_memory import ReplayMemory, ReplayMemoryError
from vantage.replay_saved_apply import bind_replay_saved_apply
from vantage.replay_saved_input import ReplaySavedInput, bind_replay_saved_input
from vantage.replay_saved_position import bind_replay_saved_position
from vantage.replay_saved_result import bind_replay_saved_result
from vantage.replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
)
from vantage.replay_unit_ai_map import ReplayUnitAIMapAtomics

WRAPPER, CHILD, WORD = 0x140E6A9C0, 0x140D77490, 0x140B81D60
IO, FORWARD, CLEANUP = 0xF001, 0x1409076B0, 0x1402BD890


class Fixture:
    """Real owned Input/4B wrapper/Result forward+cleanup; no default child success."""

    def __init__(self, wire=b"\x78\x56\x34\x12", *, seed=0xA5):
        self.memory = ReplayMemory(max_bytes=1 << 20)
        self.output, self.destination = self.memory.allocate(48), self.memory.allocate(8)
        self.memory.fill(self.output, 0xA5, 48)
        self.memory.fill(self.destination, 0xA5, 8)
        self.stream, self.vtable = self.memory.allocate(8), self.memory.allocate(32)
        self.memory.write(self.stream, 8, self.vtable)
        self.memory.write(self.vtable + 24, 8, IO)
        self.source = ReplaySavedInput(wire)
        self.events, self.frames, self.closed, self.active = [], [], {}, set()
        self.on_read = self.on_write = self.before_call = self.after_call = None
        self.blocked, self.effects, self.routes, self.returns = set(), {}, {}, {}
        self.context = ReplayTaskRebuildStorage(self.output, self.read, self.write)
        self.calls = ReplayTaskRebuildCalls(self.dispatch)
        self.atomics = ReplayUnitAIMapAtomics(
            self.memory.compare_exchange_u32, self.memory.fetch_add_u32
        )
        self.scratch = reader.ReplayPlayerFixedDwordScratch(
            bytes([seed]) * 0x70, bytes([seed]) * 0x70
        )
        self.imports = self.memory.runtime_calls()
        self.terminal = ReplayTaskRebuildCalls(self.import_call)
        self.register(
            (IO,),
            bind_replay_saved_input(
                self.context,
                self.calls,
                self.source,
                stream=self.stream,
                target=IO,
                result_bytes=bytes(48),
            ),
        )
        self.register(
            (WORD,),
            bind_replay_saved_position(
                self.context, self.calls, atomics=self.atomics, bind_local=self.bind_local
            ),
        )
        self.register(
            (FORWARD, 0x1402B9080),
            bind_replay_saved_apply(
                self.context, self.calls, atomics=self.atomics, imports=self.terminal
            ),
        )
        self.register(
            (CLEANUP, 0x1402BD7F0, 0x140900620),
            bind_replay_saved_result(
                self.context, self.calls, atomics=self.atomics, imports=self.terminal
            ),
        )
        self.bound = reader.bind_replay_player_fixed_dword_serializer(
            self.context,
            self.calls,
            atomics=self.atomics,
            bind_local=self.bind_local,
            scratch=self.scratch,
        )
        self.register((WRAPPER, CHILD), self.bound)

    def import_call(self, target, args, data):
        self.events.append(("i", target, args))
        assert self.imports.call is not None
        return self.imports.call(target, args, data)

    def register(self, targets, binding):
        for target in targets:
            self.routes[target] = binding

    def read(self, address, width):
        value = self.memory.read(address, width)
        self.events.append(("r", address, width, value))
        if self.on_read is not None:
            self.on_read(address, width, value)
        return value

    def write(self, address, width, value):
        self.memory.write(address, width, value)
        self.events.append(("w", address, width, value))
        if self.on_write is not None:
            self.on_write(address, width, value)

    def dispatch(self, target, args, data):
        self.events.append(("c", target, args))
        if self.before_call is not None:
            self.before_call(target, args)
        if target in self.blocked:
            raise UnresolvedReplayTaskRebuild(f"explicit required child{target:x}")
        if target in self.effects:
            result = self.effects[target](args)
        else:
            function = self.routes.get(target, self.imports).call
            assert function is not None
            result = function(target, args, data)
        if self.after_call is not None:
            self.after_call(target, args, result)
        return self.returns.get(target, result)

    @contextmanager
    def bind_local(self, view):
        with self.memory.bind_local(view) as address:
            if len(view) == 0x70:
                self.frames.append(address)
                self.active.add(address)
            try:
                yield address
            finally:
                if len(view) == 0x70:
                    self.closed[address] = bytes(view)
                    self.active.remove(address)

    def run(
        self,
        *,
        child=False,
        bound=False,
        output=None,
        destination=None,
        metadata=0xFEDCBA9876543210,
        line=0xDEADBEEF00000017,
        detail=0x8877665544332211,
    ):
        output = self.output if output is None else output
        destination = self.destination if destination is None else destination
        args = (
            (output, metadata, line, detail, self.stream, destination)
            if child
            else (output, self.stream, destination)
        )
        if bound:
            assert self.bound.call is not None
            return self.bound.call(CHILD if child else WRAPPER, args, None)
        function = (
            reader.read_replay_fixed_dword_scalar
            if child
            else reader.read_replay_player_fixed_dword
        )
        return function(
            self.context,
            *args,
            calls=self.calls,
            atomics=self.atomics,
            bind_local=self.bind_local,
            scratch=self.scratch,
        )

    def targets(self, target):
        return [event[2] for event in self.events if event[:2] == ("c", target)]


@pytest.mark.parametrize("word", [0, 1, 0x7FFFFFFF, 0x80000000, 0xFFFFFFFF])
@pytest.mark.parametrize(
    "child,bound", [(False, False), (False, True), (True, False), (True, True)]
)
def test_actual_composed_owned_input_and_results(word, child, bound):
    f = Fixture(word.to_bytes(4, "little"))
    assert f.run(child=child, bound=bound) == f.output
    assert f.source.position == 4
    assert f.memory.read_bytes(f.destination, 8) == word.to_bytes(4, "little") + b"\xa5" * 4
    assert f.memory.read_bytes(f.output, 48) == bytes(41) + b"\xa5" * 7
    assert len(f.targets(IO)) == 1 and len(f.targets(FORWARD)) == 1
    assert len(f.targets(CLEANUP)) == (2 if child else 3)
    assert not f.active


def test_source_metadata_six_args_and_exact_nested_local_layout():
    f = Fixture()
    assert f.run() == f.output
    wrapper, scalar = f.frames
    assert f.targets(CHILD) == [
        (wrapper + 0x40, 0x14325F510, 0x17, 0x14326B458, f.stream, f.destination)
    ]
    assert f.targets(WORD) == [
        (scalar + 0x40, 0x14325F510, 0x17, 0x14326B458, f.stream, scalar + 0x38)
    ]
    for frame in f.frames:
        saved = f.closed[frame]
        assert int.from_bytes(saved[0x20:0x28], "little") == f.stream
        assert saved[:0x20] == b"\xa5" * 0x20 and saved[0x30:0x38] == b"\xa5" * 8
        assert saved[0x68] == 1
    assert (
        int.from_bytes(f.closed[scalar][0x38:0x40], "little")
        == ((wrapper + 0x40) & 0xFFFFFFFF00000000) | 0x12345678
    )


def test_direct_child_keeps_raw_metadata_until_real_four_byte_wrapper_consumes_line():
    f = Fixture()
    assert f.run(child=True) == f.output
    args = f.targets(WORD)[0]
    assert args[1:4] == (0xFEDCBA9876543210, 0xDEADBEEF00000017, 0x8877665544332211)


@pytest.mark.parametrize("target", [IO, WORD, CHILD])
def test_returned_pointer_is_ignored_at_each_fixed_local_boundary(target):
    f = Fixture()
    f.returns[target] = 0xBAD000  # Explicit unbacked RAX, never a successful substitute Result.
    assert f.run() == f.output and f.source.position == 4


def test_actual_input_target_held_after_current_vtable_lookup():
    f = Fixture()
    alternate = IO + 1

    def mutate(address, _width, _value):
        if address == f.vtable + 24:
            f.memory.write(address, 8, alternate)

    f.on_read = mutate
    assert f.run() == f.output
    assert len(f.targets(IO)) == 1 and not f.targets(alternate)


def test_scalar_copy_observes_cleanup_mutation_and_frames_remain_live():
    f = Fixture()

    def mutate(target, args, _result):
        if target == CLEANUP and args[0] == f.frames[-1] + 0x40:
            assert set(f.frames) == f.active
            f.memory.write(f.frames[-1] + 0x38, 4, 0xCAFEBABE)

    f.after_call = mutate
    assert f.run() == f.output
    assert f.memory.read(f.destination, 4) == 0xCAFEBABE


def test_held_output_is_not_redirected_by_input_overwriting_scalar_slot():
    f = Fixture(b"\0\0\0\0")
    assert f.run(child=True) == f.output
    assert f.memory.read_bytes(f.output, 41) == bytes(41)
    assert f.closed[f.frames[0]][0x38:0x3C] == bytes(4)


def test_held_destination_is_not_reloaded_from_mutated_outgoing_home():
    f = Fixture()

    def mutate(target, args, _result):
        if target == CLEANUP and len(f.frames) == 2 and args[0] == f.frames[1] + 0x40:
            f.memory.write(f.frames[0] + 0x28, 8, 0xBAD000)

    f.after_call = mutate
    assert f.run() == f.output and f.memory.read(f.destination, 4) == 0x12345678


def test_destination_alias_output_is_stored_then_cleared_by_41_byte_success():
    f = Fixture()
    assert f.run(child=True, destination=f.output) == f.output
    writes = [row for row in f.events if row[:2] == ("w", f.output)]
    assert writes[-2:] == [("w", f.output, 4, 0x12345678), ("w", f.output, 8, 0)]


def test_destination_alias_live_scalar_slot_is_legal_owned_logical_alias():
    f = Fixture()
    # Explicit replacement of the child is not needed: direct child receives a held
    # already-live external alias, while nested scalar locals are independently mapped.
    with f.memory.bind_local(memoryview(bytearray(b"\xa5" * 8))) as alias:
        assert f.run(child=True, destination=alias) == f.output
        assert f.memory.read(alias, 8) == 0xA5A5A5A512345678


@pytest.mark.parametrize("target", [IO, WORD, FORWARD, CLEANUP, CHILD])
def test_missing_real_child_refuses_at_reach_with_prior_effects_retained(target):
    f = Fixture()
    f.blocked.add(target)
    with pytest.raises(UnresolvedReplayTaskRebuild, match="explicit required child"):
        f.run()
    assert f.memory.read_bytes(f.output, 48) == b"\xa5" * 48
    assert f.memory.read_bytes(f.destination, 8) == b"\xa5" * 8
    assert f.source.position == (4 if target in (FORWARD, CLEANUP) else 0)
    assert not f.active


@pytest.mark.parametrize("length", [0, 1, 3])
def test_actual_owned_truncation_has_no_input_copy_or_destination_publication(length):
    f = Fixture(b"X" * length)
    with pytest.raises(UnresolvedReplayTaskRebuild, match="exact span"):
        f.run()
    assert f.source.position == 0
    assert f.memory.read_bytes(f.destination, 8) == b"\xa5" * 8
    assert f.memory.read_bytes(f.output, 48) == b"\xa5" * 48


def test_late_destination_failure_preserves_four_bytes_consumed_and_actual_cleanup():
    f = Fixture()
    with pytest.raises(ReplayMemoryError):
        f.run(child=True, destination=0xBAD000)
    assert f.source.position == 4 and len(f.targets(CLEANUP)) == 2
    assert f.memory.read_bytes(f.output, 48) == b"\xa5" * 48


def test_opaque_scalar_error_reads_three_literals_then_refuses_before_tls_or_cleanup():
    f = Fixture()
    for address in (0x14325DF50, 0x14325D6D0, 0x14325DE60):
        f.memory.map_bytes(address, bytes(range(16)))

    def opaque_four_byte_wrapper(args):
        f.memory.write(args[0] + 0x18, 8, 1)
        return 0xBAD000

    # Authored error-producing child, not native success.
    f.effects[WORD] = opaque_four_byte_wrapper
    with pytest.raises(UnresolvedReplayTaskRebuild, match="140d77526"):
        f.run(child=True)
    assert [row[1] for row in f.events if row[0] == "r" and row[2] == 16] == [
        0x14325DF50,
        0x14325D6D0,
        0x14325DE60,
    ]
    assert f.closed[f.frames[0]][0x68] == 0 and not f.targets(CLEANUP)
    assert f.memory.read_bytes(f.output, 48) == b"\xa5" * 48


def test_error_literal_read_refuses_at_first_missing_backing_before_tls_frontier():
    f = Fixture()

    def opaque_four_byte_wrapper(args):
        f.memory.write(args[0] + 0x18, 8, 1)

    f.effects[WORD] = opaque_four_byte_wrapper
    with pytest.raises(ReplayMemoryError, match="unmapped"):
        f.run(child=True)
    assert not f.targets(CLEANUP)


def test_opaque_nested_error_refuses_before_metadata_getter_and_no_false_release():
    f = Fixture()

    def opaque_nested(args):
        f.memory.write(args[0] + 0x18, 8, 1)
        return 0xBAD000

    f.effects[CHILD] = opaque_nested  # Explicit branch control, no claimed child implementation.
    with pytest.raises(UnresolvedReplayTaskRebuild, match="140e6aa2e"):
        f.run()
    assert not f.targets(0x140E6A720) and not f.targets(CLEANUP)
    assert f.closed[f.frames[0]][0x68] == 0
    assert f.memory.read_bytes(f.output, 48) == b"\xa5" * 48


def test_actual_atomic_release_holds_control_but_reloads_changed_weak_vtable():
    f = Fixture()
    control, old_table, new_table = (f.memory.allocate(16) for _ in range(3))
    destroy, old_weak, new_weak = 0xFE01, 0xFE02, 0xFE03
    for address, width, value in (
        (control, 8, old_table),
        (control + 8, 4, 1),
        (control + 12, 4, 1),
        (old_table, 8, destroy),
        (old_table + 8, 8, old_weak),
        (new_table + 8, 8, new_weak),
    ):
        f.memory.write(address, width, value)

    def install(target, args, _result):
        if target == WORD:
            f.memory.write(args[0] + 32, 8, control)

    def destroy_effect(_args):
        f.memory.write(control, 8, new_table)
        f.memory.write(f.frames[-1] + 0x60, 8, 0)

    f.after_call = install
    f.effects[destroy] = destroy_effect
    f.effects[new_weak] = lambda _args: None  # Explicit observed disposal callback boundary.
    assert f.run(child=True) == f.output
    assert len(f.targets(destroy)) == len(f.targets(new_weak)) == 1
    assert not f.targets(old_weak)
    assert f.memory.read(control + 8, 4) == f.memory.read(control + 12, 4) == 0


def test_processed_write_precedes_current_control_lookup():
    f = Fixture()
    control = f.memory.allocate(16)
    f.memory.write(control + 8, 4, 2)  # No virtual destructor reached on decrement2->1.

    def mutate(address, width, value):
        if f.frames and address == f.frames[-1] + 0x68 and width == 1 and value == 1:
            f.memory.write(f.frames[-1] + 0x60, 8, control)

    f.on_write = mutate
    assert f.run(child=True) == f.output
    assert f.memory.read(control + 8, 4) == 1


def test_control_failure_retains_processed_bit_and_does_not_copy_scalar():
    f = Fixture()
    missing = 0xBAD000

    def mutate(target, args, _result):
        if target == WORD:
            f.memory.write(args[0] + 32, 8, missing)

    f.after_call = mutate
    with pytest.raises(ReplayMemoryError):
        f.run(child=True)
    assert f.closed[f.frames[0]][0x68] == 1
    assert f.memory.read_bytes(f.destination, 8) == b"\xa5" * 8
    assert f.targets(CLEANUP)[-1:] != [(f.frames[0] + 0x40,)]


@pytest.mark.parametrize("seed", [0, 0xA5, 0xFF])
def test_explicit_seeds_preserve_only_unassigned_data_and_local_lifetime(seed):
    f = Fixture(seed=seed)
    assert f.run() == f.output
    for frame in f.frames:
        assert f.closed[frame][:0x20] == bytes([seed]) * 0x20
        assert len(f.closed[frame]) == 0x70
    for frame in f.frames:
        with pytest.raises(ReplayMemoryError):
            f.memory.read(frame, 1)


@pytest.mark.parametrize(
    "wrapper,scalar",
    [
        (b"", bytes(0x70)),
        (bytes(0x70), b""),
        (bytes(0x71), bytes(0x70)),
        (bytearray(0x70), bytes(0x70)),
    ],
)
def test_invalid_seed_is_rejected_without_backing_effects(wrapper, scalar):
    with pytest.raises(ValueError, match="two explicit"):
        reader.ReplayPlayerFixedDwordScratch(wrapper, scalar)


@pytest.mark.parametrize(
    "target,args,data",
    [
        (WRAPPER, (1, 2), None),
        (CHILD, (1, 2, 3), None),
        (WRAPPER, (1, 2, 3), memoryview(b"")),
        (CHILD, (1, 2, 3, 4, 5, -1), None),
    ],
)
def test_binder_exact_arity_scalar_validation_and_data_refusal(target, args, data):
    f = Fixture()
    assert f.bound.call is not None
    with pytest.raises(ValueError):
        f.bound.call(target, args, data)
    assert not f.events and not f.frames


def test_unknown_binding_delegates_real_target_args_and_data():
    f = Fixture()
    data = memoryview(b"route")
    seen = []
    f.effects[0xFA11] = lambda args: seen.append(args) or 9
    assert f.bound.call is not None
    assert f.bound.call(0xFA11, (17,), data) == 9 and seen == [(17,)]
    assert f.events[-1] == ("c", 0xFA11, (17,))


def test_actual_nonnull_empty_vector_is_freed_before_scalar_publication():
    f = Fixture()
    buffer = f.memory.allocate(32)
    f.memory.map_bytes(0x143199DD0, (0x142D6BAB4).to_bytes(8, "little"))

    def install(target, args, _result):
        if target == WORD:
            for offset, value in ((0, buffer), (8, buffer), (16, buffer + 32)):
                f.memory.write(args[0] + offset, 8, value)

    f.after_call = install
    assert f.run(child=True) == f.output
    free = [row[2] for row in f.events if row[:2] == ("i", 0x142D6BAB4)]
    assert free == [(buffer, 32)]
    with pytest.raises(ReplayMemoryError):
        f.memory.read(buffer, 1)
    events = f.events
    assert next(i for i, row in enumerate(events) if row[:2] == ("i", 0x142D6BAB4)) < next(
        i for i, row in enumerate(events) if row[:2] == ("w", f.destination)
    )


@pytest.mark.parametrize("child", [False, True])
def test_zero_status_value_is_held_across_read_callback_mutation(child):
    f = Fixture()

    def mutate(address, width, value):
        if f.frames and address == f.frames[0] + 0x58 and width == 8 and value == 0:
            f.memory.write(address, 8, 1)

    f.on_read = mutate
    assert f.run(child=child) == f.output
    assert int.from_bytes(f.closed[f.frames[0]][0x58:0x60], "little") == 1


@pytest.mark.parametrize("child", [False, True])
def test_partial_final_output_write_failure_preserves_prior_stores(child):
    f = Fixture()

    def write(address, width, value):
        if address == f.output + 16:
            raise RuntimeError("explicit output write refusal")
        f.write(address, width, value)

    f.context = ReplayTaskRebuildStorage(f.output, f.read, write)
    # Bind every real descendant to the same backing; only final external writes
    # need the explicit authored refusal hook, not a fake replacement child.
    with pytest.raises(RuntimeError, match="explicit output write"):
        function = (
            reader.read_replay_fixed_dword_scalar
            if child
            else reader.read_replay_player_fixed_dword
        )
        args = (
            (f.output, 1, 2, 3, f.stream, f.destination)
            if child
            else (f.output, f.stream, f.destination)
        )
        function(
            f.context,
            *args,
            calls=f.calls,
            atomics=f.atomics,
            bind_local=f.bind_local,
            scratch=f.scratch,
        )
    assert f.source.position == 4 and f.memory.read(f.destination, 4) == 0x12345678
    assert f.memory.read_bytes(f.output, 48) == bytes(16) + b"\xa5" * 32
    assert not f.active


def test_actual_four_byte_wrapper_requires_metadata_provider_on_input_error():
    f = Fixture()

    def inject_status(target, args, _result):
        if target == IO:
            f.memory.write(args[1] + 0x18, 8, 1)

    f.after_call = inject_status
    with pytest.raises(UnresolvedReplayTaskRebuild, match="140900ed0"):
        f.run()
    assert f.source.position == 4 and not f.targets(FORWARD) and not f.targets(CLEANUP)
    raw = f.targets(IO)[0][1]
    assert f.targets(0x140900ED0) == [(raw, 0x14325F510, 0x17, 0x14326B458)]
    assert f.memory.read_bytes(f.destination, 8) == b"\xa5" * 8
    assert f.memory.read_bytes(f.output, 48) == b"\xa5" * 48
