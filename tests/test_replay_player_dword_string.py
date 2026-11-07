"""Source-led owned-storage controls, with explicit opaque mutation effects."""

from __future__ import annotations

from contextlib import contextmanager

import pytest

from vantage import replay_player_dword_string as reader
from vantage.replay_memory import ReplayMemory
from vantage.replay_player_name_skins import (
    ReplayPlayerNameSkinsScratch,
    bind_replay_player_name_skins,
)
from vantage.replay_player_name_skins_storage import bind_replay_player_name_skins_storage
from vantage.replay_player_name_validation import bind_replay_player_name_validation
from vantage.replay_saved_apply import bind_replay_saved_apply
from vantage.replay_saved_input import ReplaySavedInput, bind_replay_saved_input
from vantage.replay_saved_pair import bind_replay_saved_pair
from vantage.replay_saved_result import bind_replay_saved_result
from vantage.replay_saved_string import bind_replay_saved_string
from vantage.replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
)
from vantage.replay_unit_ai_map import ReplayUnitAIMapAtomics
from vantage.replay_unit_constructor_support import bind_replay_unit_constructor_support

IO, STRLEN = 0xF001, 0xF002
FORWARD, CLEANUP, BYTE, REPAIR = 0x1409076B0, 0x1402BD890, 0x140A150F0, 0x140A09540
GETTER, GROW, COPY, DTOR = 0x140A13780, 0x140A1A5E0, 0x142D6E3B1, 0x1402A8920


class Fixture:
    """Actual owned Input/Result/SSO/repair/validation/CRT bindings, no default success."""

    def __init__(self, wire: bytes) -> None:
        self.memory = ReplayMemory(max_bytes=8 << 20)
        self.object = self.memory.allocate(64)
        self.memory.fill(self.object, 0xA5, 64)
        self.memory.write_bytes(self.object, bytes(24))
        self.output = self.memory.allocate(48)
        self.memory.fill(self.output, 0xA5, 48)
        self.stream, self.vtable = self.memory.allocate(8), self.memory.allocate(32)
        self.memory.write(self.stream, 8, self.vtable)
        self.memory.write(self.vtable + 24, 8, IO)
        self.memory.map_bytes(0x14428BB30, b"\0")  # Explicit owned empty-byte profile.
        for slot, target in (
            (0x143199DD0, 0x142D6BAB4),
            (0x143199930, 0x142D6E3DB),
            (0x143199938, 0x142D6E3B7),
            (0x14319A290, STRLEN),
        ):
            self.memory.map_bytes(slot, target.to_bytes(8, "little"))
        self.events, self.frame, self.frame_after = [], 0, b""
        self.on_read = self.on_write = self.before_call = self.after_call = None
        self.blocked, self.effects, self.routes = set(), {}, {}
        self.returned = None
        self.source = ReplaySavedInput(wire)
        self.context = ReplayTaskRebuildStorage(self.object, self.read, self.write)
        self.atomics = ReplayUnitAIMapAtomics(
            self.memory.compare_exchange_u32, self.memory.fetch_add_u32
        )
        self.calls = ReplayTaskRebuildCalls(self.dispatch)
        self.imports = self.memory.runtime_calls(strlen_target=STRLEN)
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
            (0x14090D270,), bind_replay_saved_pair(self.context, self.calls, atomics=self.atomics)
        )
        self.register(
            (FORWARD, 0x1402B9080),
            bind_replay_saved_apply(
                self.context, self.calls, atomics=self.atomics, imports=self.imports
            ),
        )
        self.register(
            (0x1402BD7F0, CLEANUP, 0x140900620),
            bind_replay_saved_result(
                self.context, self.calls, atomics=self.atomics, imports=self.imports
            ),
        )
        self.register(
            (DTOR, 0x1402A88A0),
            bind_replay_saved_string(self.context, self.calls, imports=self.imports),
        )
        self.register(
            (GETTER, GROW, 0x142D6C268, 0x142D6C270, COPY, 0x142D6E44D),
            bind_replay_unit_constructor_support(
                self.context, self.calls, bind_local=self.bind_local, imports=self.imports
            ),
        )
        self.register(
            (0x140A84390, 0x140A830B0),
            bind_replay_player_name_validation(
                self.context, self.calls, bind_local=self.bind_local, scratch=bytes(0x44)
            ),
        )
        self.register(
            (0x1402BB300,),
            bind_replay_player_name_skins_storage(self.context, self.calls, imports=self.imports),
        )
        self.register(
            (BYTE, REPAIR),
            bind_replay_player_name_skins(
                self.context,
                self.calls,
                atomics=self.atomics,
                bind_local=self.bind_local,
                scratch=ReplayPlayerNameSkinsScratch(
                    *(b"\xa5" * size for size in (0xE8, 0xA0, 0x60, 0xB8))
                ),
                imports=self.imports,
            ),
        )

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
            raise UnresolvedReplayTaskRebuild(f"explicit required-child refusal {target:x}")
        if target in self.effects:
            result = self.effects[target](args)
        else:
            binding = self.routes.get(target, self.imports).call
            assert binding is not None
            result = binding(target, args, data)
        if self.after_call is not None:
            self.after_call(target, args, result)
        return self.returned if target == IO and self.returned is not None else result

    @contextmanager
    def bind_local(self, view):
        with self.memory.bind_local(view) as address:
            if len(view) == 0xE0:
                self.frame = address
            try:
                yield address
            finally:
                if len(view) == 0xE0:
                    self.frame_after = bytes(view)

    def run(self, *, bound=False, output=None):
        output = self.output if output is None else output
        scratch = reader.ReplayPlayerDwordStringScratch(b"\xa5" * 0xE0)
        if bound:
            binding = reader.bind_replay_player_dword_string(
                self.context,
                self.calls,
                atomics=self.atomics,
                bind_local=self.bind_local,
                scratch=scratch,
            )
            assert binding.call is not None
            return binding.call(0x140A1CF00, (self.object, output, self.stream), None)
        return reader.read_replay_player_dword_string(
            self.context,
            self.object,
            output,
            self.stream,
            calls=self.calls,
            atomics=self.atomics,
            bind_local=self.bind_local,
            scratch=scratch,
        )

    def targets(self, target):
        return [event[2] for event in self.events if event[:2] == ("c", target)]


def wire(payload):
    return len(payload).to_bytes(4, "little") + payload


@pytest.mark.parametrize(
    "payload",
    [b"", b"\0", b"a\0", b"Hello\0", b"x" * 15 + b"\0", b"x" * 16 + b"\0", b"x" * 31 + b"\0"],
)
@pytest.mark.parametrize("bound", [False, True])
def test_actual_owned_all_normal_children_and_41_byte_result(payload, bound):
    f = Fixture(wire(payload))
    assert f.run(bound=bound) == f.output
    assert f.source.position == 4 + len(payload)
    assert f.memory.read_bytes(f.output, 48) == bytes(41) + b"\xa5" * 7
    assert len(f.targets(IO)) == 1 + len(payload)
    if payload and payload[0]:
        assert f.memory.read(f.object + 8, 8) == len(payload) - 1
        assert f.memory.read_bytes(f.memory.read(f.object, 8), len(payload)) == payload
    else:
        assert f.memory.read_bytes(f.object, 24) == bytes(24)
    assert bool(f.targets(DTOR)) == bool(payload)
    if not payload:
        assert f.frame_after[0x90:0xB0] == b"\xa5" * 32


def test_unsigned_maximum_2800_is_admitted_by_real_byte_loop():
    payload = b"x" * 0x27FF + b"\0"
    f = Fixture(wire(payload))
    assert f.run() == f.output and f.source.remaining == 0
    assert f.memory.read(f.object + 8, 8) == 0x27FF
    assert not f.targets(0x140A08840)


@pytest.mark.parametrize("size", [0x2801, 0x80000000, 0xFFFFFFFF])
def test_unsigned_oversize_requires_actual_six_argument_error_provider(size):
    f = Fixture(size.to_bytes(4, "little"))
    with pytest.raises(UnresolvedReplayTaskRebuild, match="140a08840"):
        f.run()
    assert f.source.position == 4 and not f.targets(BYTE)
    assert f.targets(0x140A08840) == [(f.frame + 0x60, 0, 0x1432098D0, 0x9E9, 0x143209980, size)]
    assert int.from_bytes(f.frame_after[0x28:0x2C], "little") == size
    assert f.frame_after[0x2C:0x30] == b"\xa5" * 4


def test_first_input_return_is_ignored_in_favor_of_fixed_B0_result():
    f = Fixture(wire(b""))
    f.returned = 0xBAD000  # Deliberately unbacked RAX, no dereference is allowed.
    assert f.run() == f.output and f.source.position == 4
    assert f.targets(FORWARD)[0] == (f.frame + 0x60, f.frame + 0xB0)


@pytest.mark.parametrize("payload", [b"\xc0\x80\0", b"\xed\xa0\x80\0", b"\xf5\x80\x80\x80\0"])
def test_real_structural_predicate_does_not_become_strict_unicode(payload):
    f = Fixture(wire(payload))
    assert f.run() == f.output and f.source.remaining == 0
    assert f.memory.read_bytes(f.memory.read(f.object, 8), len(payload)) == payload


def test_all_declared_bytes_read_but_actual_strlen_stops_at_early_nul():
    f = Fixture(wire(b"a\0tail"))
    assert f.run() == f.output and f.source.position == 10
    assert f.memory.read(f.object + 8, 8) == 1
    assert f.memory.read_bytes(f.memory.read(f.object, 8), 2) == b"a\0"


def test_initial_selected_input_target_is_held_and_later_byte_targets_are_current():
    f = Fixture(wire(b"ab\0"))
    alternate = IO + 10
    f.register(
        (alternate,),
        bind_replay_saved_input(
            f.context, f.calls, f.source, stream=f.stream, target=alternate, result_bytes=bytes(48)
        ),
    )

    def mutate(address, _width, _value):
        if address == f.vtable + 24:
            f.memory.write(address, 8, alternate)

    f.on_read = mutate
    assert f.run() == f.output and f.source.remaining == 0
    assert [args[3] for args in f.targets(IO)] == [4]
    assert [args[3] for args in f.targets(alternate)] == [1, 1, 1]


def test_real_atomic_release_holds_control_and_reloads_changed_virtual_table():
    f = Fixture(wire(b""))
    control, old_table, new_table = (f.memory.allocate(16) for _ in range(3))
    destroy, old_weak, new_weak = 0xFE01, 0xFE02, 0xFE03
    f.memory.write(control, 8, old_table)
    f.memory.write(control + 8, 4, 1)
    f.memory.write(control + 12, 4, 1)
    f.memory.write(old_table, 8, destroy)
    f.memory.write(old_table + 8, 8, old_weak)
    f.memory.write(new_table + 8, 8, new_weak)

    def annotate(target, _args, _result):
        if target == FORWARD:
            f.memory.write(f.frame + 0x80, 8, control)

    def destroy_effect(args):
        assert args == (control,)
        f.memory.write(control, 8, new_table)
        f.memory.write(f.frame + 0x80, 8, 0xBAD)

    def weak_effect(args):
        assert args == (control,)

    # Explicit opaque polymorphic effects; actual count/dispatch work is real.
    f.after_call = annotate
    f.effects[destroy], f.effects[new_weak] = destroy_effect, weak_effect
    assert f.run() == f.output
    assert f.targets(destroy) == [(control,)] and f.targets(new_weak) == [(control,)]
    assert not f.targets(old_weak)
    assert f.memory.read(control + 8, 4) == f.memory.read(control + 12, 4) == 0


def test_opaque_range_effect_holds_control_before_status_mutation_and_rereads_size():
    f = Fixture((0x2801).to_bytes(4, "little"))
    control = f.memory.allocate(16)
    f.memory.write(control + 8, 4, 2)  # Real release2->1 avoids unknown virtuals.
    armed = False

    def range_effect(args):
        nonlocal armed
        assert args[-1] == 0x2801
        f.memory.write_bytes(f.frame + 0x60, bytes(48))
        f.memory.write(f.frame + 0x80, 8, control)
        f.memory.write(f.frame + 0x58, 4, 0)
        armed = True

    def mutate(address, _width, _value):
        if armed and address == f.frame + 0x78:
            f.memory.write(f.frame + 0x80, 8, 0xBAD)

    f.effects[0x140A08840] = range_effect  # Authored effect, not native error success proof.
    f.on_read = mutate
    assert f.run() == f.output
    assert f.memory.read(control + 8, 4) == 1 and not f.targets(BYTE)


@pytest.mark.parametrize("pointer,capacity", [(0, 0), (0, 9), (1, 0)])
def test_zero_size_preserves_source_conditional_old_descriptor(pointer, capacity):
    f = Fixture(wire(b""))
    actual = f.memory.allocate(8) if pointer else 0
    f.memory.write(f.object, 8, actual)
    f.memory.write(f.object + 8, 8, 77)
    f.memory.write(f.object + 16, 8, capacity)
    before = f.memory.read_bytes(f.object, 24)
    assert f.run() == f.output
    assert f.memory.read_bytes(f.object, 24) == before and not f.targets(0x142D6C270)


def test_initial_free_and_reset_order_before_first_input():
    f = Fixture(wire(b""))
    old = f.memory.allocate(8)
    f.memory.write(f.object, 8, old)
    f.memory.write(f.object + 8, 8, 7)
    f.memory.write(f.object + 16, 8, 8)
    assert f.run() == f.output
    relevant = [
        event[:3] for event in f.events if event[0] == "w" and f.object <= event[1] < f.object + 24
    ]
    assert relevant == [("w", f.object, 8), ("w", f.object + 16, 8), ("w", f.object + 8, 8)]
    assert f.targets(0x142D6C270) == [(old,)]
    assert f.memory.read(f.object, 8) == 0x14428BB30


def test_failed_initial_free_retains_descriptor_and_only_held_output_frame_store():
    f = Fixture(wire(b""))
    f.memory.write(f.object, 8, 0xBAD)
    f.memory.write(f.object + 16, 8, 8)
    before = f.memory.read_bytes(f.object, 24)
    f.blocked.add(0x142D6C270)
    with pytest.raises(UnresolvedReplayTaskRebuild):
        f.run()
    assert f.memory.read_bytes(f.object, 24) == before and f.source.position == 0
    assert int.from_bytes(f.frame_after[0x58:0x60], "little") == f.output


@pytest.mark.parametrize("child", [FORWARD, CLEANUP, BYTE, REPAIR, GETTER, GROW, DTOR])
def test_required_child_refusal_keeps_reached_partial_effects(child):
    f = Fixture(wire(b"ab\0"))
    f.blocked.add(child)
    with pytest.raises(UnresolvedReplayTaskRebuild):
        f.run()
    assert f.targets(child)
    assert f.source.position >= 4
    if child == DTOR:
        assert f.memory.read_bytes(f.output, 48) == bytes(41) + b"\xa5" * 7
    else:
        assert f.memory.read_bytes(f.output, 48) == b"\xa5" * 48


def test_cmova_unconditionally_reads_pointer_but_uses_held_capacity():
    f = Fixture(wire(b"\0"))
    replacement = f.memory.allocate(32)
    seen = False

    def mutate(address, width, _value):
        nonlocal seen
        if address == f.frame + 0xA8 and width == 8 and not seen:
            seen = True
            f.memory.write(address, 8, 31)
            f.memory.write(f.frame + 0x90, 8, replacement)

    f.on_read = mutate
    f.blocked.add(BYTE)
    with pytest.raises(UnresolvedReplayTaskRebuild):
        f.run()
    assert f.targets(BYTE)[0][-2] == f.frame + 0x90
    assert ("r", f.frame + 0x90, 8, replacement) in f.events


def test_current_count_after_fill_and_current_strict_terminator_not_assumed():
    f = Fixture(wire(b"abc\0"))

    def mutate(target, _args, _result):
        if target == 0x142D6E3B7:
            f.memory.write(f.frame + 0x58, 4, 2)

    f.after_call = mutate
    assert f.run() == f.output
    assert f.targets(BYTE)[0][-1] == 2 and f.source.position == 6
    assert f.memory.read_bytes(f.memory.read(f.object, 8), 3) == b"ab\0"


def test_descriptor_pointer_precedes_strlen_and_getter_length_is_authoritative():
    f = Fixture(wire(b"abcd\0"))
    alternate = f.memory.allocate(8)
    f.memory.write_bytes(alternate, b"zz\0")

    def mutate(target, args):
        if target == 0x142D6E44D:
            assert f.memory.read(f.frame + 0x48, 8) == args[0]
        if target == GETTER:
            f.memory.write(f.frame + 0x48, 8, alternate)
            f.memory.write(f.frame + 0x50, 8, 2)

    f.before_call = mutate
    assert f.run() == f.output
    assert f.memory.read_bytes(f.memory.read(f.object, 8), 3) == b"ab\0"


def test_memcpy_then_terminator_rereads_current_object_pointer():
    f = Fixture(wire(b"ab\0"))
    alternate = f.memory.allocate(8)
    f.memory.fill(alternate, 0xCC, 8)
    copied = []

    def mutate(target, args, _result):
        if target == COPY:
            copied.append(args[0])
            f.memory.write(f.object, 8, alternate)

    f.after_call = mutate
    assert f.run() == f.output
    assert len(copied) == 1 and f.memory.read_bytes(copied[0], 2) == b"ab"
    assert f.memory.read_bytes(alternate, 4) == b"\xcc\xcc\0\xcc"
    assert f.memory.read(f.object + 8, 8) == 2


@pytest.mark.parametrize(
    "target,frontier", [(FORWARD, "140a1d03e"), (BYTE, "140a1d50a"), (REPAIR, "140a1d6db")]
)
def test_error_status_refuses_before_unported_detail_without_fake_cleanup(target, frontier):
    f = Fixture(wire(b"ab\0"))

    def annotate(actual, _args, _result):
        if actual == target:
            f.memory.write(f.frame + 0x78, 8, 0xBAD)

    f.after_call = annotate
    with pytest.raises(UnresolvedReplayTaskRebuild, match=frontier):
        f.run()
    assert f.memory.read_bytes(f.output, 48) == b"\xa5" * 48
    assert not f.targets(DTOR)


def test_range_success_holds_zero_control_across_processed_write_hook():
    f = Fixture(wire(b""))
    count = 0

    def mutate(address, width, value):
        nonlocal count
        if address == f.frame + 0x88 and width == 1 and value == 1:
            count += 1
            if count == 2:
                f.memory.write(f.frame + 0x80, 8, 0xBAD)

    f.on_write = mutate

    # Actual cleanup then sees the changed control pointer; the caller must not
    # read it itself for release. Refuse that real child before it dereferences.
    def before(target, args):
        if target == CLEANUP and args == (f.frame + 0x60,) and count == 2:
            raise UnresolvedReplayTaskRebuild("actual cleanup boundary")

    f.before_call = before
    with pytest.raises(UnresolvedReplayTaskRebuild, match="actual cleanup boundary"):
        f.run()
    assert not any(row[:3] == ("r", 0xBAD, 8) for row in f.events)


def test_output_object_alias_preserves_41_byte_publication_before_real_dtor():
    f = Fixture(wire(b"ab\0"))
    assert f.run(output=f.object) == f.object
    assert f.memory.read_bytes(f.object, 48) == bytes(41) + b"\xa5" * 7
    assert f.targets(DTOR)


@pytest.mark.parametrize("wire_bytes", [b"", b"\0", b"\0\0\0", wire(b"ab\0")[:-1]])
def test_truncated_input_refuses_without_inventing_padding_or_cleanup(wire_bytes):
    f = Fixture(wire_bytes)
    with pytest.raises(UnresolvedReplayTaskRebuild):
        f.run()
    assert f.memory.read_bytes(f.output, 48) == b"\xa5" * 48
    assert not f.targets(DTOR)


def test_unterminated_payload_is_not_assumed_to_have_length_minus_one():
    f = Fixture(wire(b"abc"))
    assert f.run() == f.output
    # Current source scanning reaches a defined initializer NUL after all3
    # payload bytes, rather than inventing N-1=2 or an encoding rejection.
    assert f.source.remaining == 0 and f.memory.read(f.object + 8, 8) == 3
    assert f.memory.read_bytes(f.memory.read(f.object, 8), 4) == b"abc\0"


@pytest.mark.parametrize("seed", [bytes(0), bytes(223), bytes(225), bytearray(224)])
def test_exact_explicit_frame_seed_is_required(seed):
    with pytest.raises(ValueError):
        reader.ReplayPlayerDwordStringScratch(seed)


@pytest.mark.parametrize(
    "args,data",
    [
        ((1, 2), None),
        ((1, 2, 3, 4), None),
        ((1, 2, -1), None),
        ((1, 2, 3), memoryview(bytearray(1))),
    ],
)
def test_known_binder_admission_fails_before_effects(args, data):
    f = Fixture(b"")
    bound = reader.bind_replay_player_dword_string(
        f.context,
        f.calls,
        atomics=f.atomics,
        bind_local=f.bind_local,
        scratch=reader.ReplayPlayerDwordStringScratch(bytes(224)),
    )
    with pytest.raises(ValueError):
        bound.call(0x140A1CF00, args, data)
    assert not f.events


def test_unknown_binder_target_delegates_exact_args_payload_and_return():
    f = Fixture(b"")
    seen, payload = [], memoryview(bytearray(b"xy"))

    def lower(target, args, data):
        seen.append((target, args, data))
        return 19

    bound = reader.bind_replay_player_dword_string(
        f.context,
        ReplayTaskRebuildCalls(lower),
        atomics=f.atomics,
        bind_local=f.bind_local,
        scratch=reader.ReplayPlayerDwordStringScratch(bytes(224)),
    )
    assert bound.call(7, (8,), payload) == 19
    assert seen == [(7, (8,), payload)] and not f.events
