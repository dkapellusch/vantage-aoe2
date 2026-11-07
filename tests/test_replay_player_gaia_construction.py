"""Source-led Gaia outer controls, using actual owned storage and small ports.

Derived and stream Input are explicitly authored service seams, not a native
oracle. No full World, recording restoration, native protection or EH is claimed.
"""

from __future__ import annotations

from contextlib import contextmanager

import pytest

from vantage import replay_player_gaia_construction as gaia
from vantage.replay_base_saved_leaves import bind_replay_base_saved_leaves
from vantage.replay_memory import ReplayMemory, ReplayMemoryError
from vantage.replay_player_construction_support import (
    ReplayPlayerSupportScratch,
    bind_replay_player_construction_support,
)
from vantage.replay_player_saved_children import bind_replay_player_saved_children
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

ENTRY, DERIVED = 0x14174FA70, 0x1416C2440
INPUT, INPUT2, VERSION = 0xAA10, 0xAA20, 0x1440A0D94
MALLOC, MEMSET, LIST = 0x142D6BA78, 0x142D6E3B7, 0x141227140
PAIR, COPY, FORWARD, FINAL = 0x14090D270, 0x1402B9080, 0x140991CE0, 0x1402BD890
U32, U64 = (1 << 32) - 1, (1 << 64) - 1
FIRST, SECOND = 0x14174FC5F, 0x14174FCF5
LOOP = (0x14174FED5, 0x14174FF74, 0x141750013)
EXTENSION = (0x1417500E1, 0x141750174, 0x1417501E1, 0x14175024E, 0x1417502BB, 0x141750328)
LAST = (0x1417503CF, 0x14175043C, 0x1417504A8, 0x141750515, 0x141750582, 0x1417505EE, 0x141750657)
GUARDED = (FIRST, SECOND, 0x14174FD98, 0x14174FE05, *LOOP, *EXTENSION, *LAST[:-1])


def protocol(version):
    """Independent literal successful fixed-version prediction from original ASM."""
    result = [(FIRST, 4, "field", 0x13F0), (SECOND, 4, "field", 0x13F4)]
    if version <= 0x911EB:
        result.extend([(0x14174FD98, 4, "local", 0xE8), (0x14174FE05, 4, "local", 0xE8)])
    else:
        for index in range(5):
            result.extend(
                (site, 4, "field", 0x1400 + 24 * index + 4 * n) for n, site in enumerate(LOOP)
            )
    if version >= 0x9F851:
        result.extend(
            zip(
                EXTENSION,
                (4, 4, 4, 4, 36, 36),
                ("field",) * 6,
                (0x1474, 0x1478, 0x147C, 0x1480, 0x1484, 0x14A8),
                strict=True,
            )
        )
    if version > 0x9FAE1:
        result.extend(
            zip(
                LAST,
                (4, 40, 4, 4, 200, 4, 40),
                ("field",) * 7,
                (0x14CC, 0x14D0, 0x14F8, 0x14FC, 0x1500, 0x1690, 0x1694),
                strict=True,
            )
        )
    return result


class Fixture:
    def __init__(self, version=0xA0000, *, budget=5):
        self.memory = ReplayMemory(max_bytes=4 << 20)
        self.subject = self.memory.allocate(0x16E8)
        self.output, self.stream, self.table, self.index = (
            self.memory.allocate(48),
            self.memory.allocate(8),
            self.memory.allocate(32),
            self.memory.allocate(4),
        )
        self.memory.fill(self.subject, 0xCD, 0x16E8)
        self.memory.fill(self.output, 0xC7, 48)
        self.memory.write(self.index, 4, 0x12345678)
        self.memory.write(self.stream, 8, self.table)
        self.memory.write(self.table + 24, 8, INPUT)
        self.memory.map_bytes(VERSION, version.to_bytes(4, "little", signed=version < 0))
        self.memory.map_bytes(0x143199DD0, (0x142D6BAB4).to_bytes(8, "little"))
        self.primitive = self.memory.runtime_calls()
        self.events, self.inputs, self.allocations, self.closed = [], [], [], []
        self.pending = protocol(version)
        self.frame, self.active = 0, False
        self.on_read = self.on_write = self.on_input = self.on_derived = self.on_malloc = None
        self.effects, self.routes, self.unavailable = {}, {}, set()
        self.fail_site = None
        self.derived_return = None
        self.returned_result = None
        self.derived_status = 0
        self.seen_derived_index = None
        self.context = ReplayTaskRebuildStorage(self.subject, self.read, self.write)
        self.calls, self.imports = (
            ReplayTaskRebuildCalls(self.dispatch),
            ReplayTaskRebuildCalls(self.terminal),
        )
        self.atomics = ReplayUnitAIMapAtomics(None, self.atomic)
        self.result(self.output)
        pair = bind_replay_saved_pair(self.context, self.calls, atomics=self.atomics)
        self.routes[PAIR] = pair
        self.routes[COPY] = bind_replay_saved_apply(
            self.context, self.calls, atomics=self.atomics, imports=self.imports
        )
        self.routes[FORWARD] = bind_replay_player_saved_children(self.context, self.calls)
        self.routes[LIST] = bind_replay_player_construction_support(
            self.context,
            self.calls,
            bind_local=self.bind_local,
            scratch=ReplayPlayerSupportScratch(bytes(0xB8), bytes(0x48)),
        )
        final = bind_replay_saved_result(
            self.context, self.calls, atomics=self.atomics, imports=self.imports
        )
        for target in (FINAL, 0x1402BD7F0, 0x140900620):
            self.routes[target] = final
        strings = bind_replay_saved_string(self.context, self.calls, imports=self.imports)
        self.routes[0x1402A88A0] = self.routes[0x1402A8920] = strings
        self.routes[0x1408EE150] = bind_replay_base_saved_leaves(
            self.context,
            self.calls,
            atomics=self.atomics,
            bind_local=self.bind_local,
            scratch=bytes(8),
        )
        self.scratch = gaia.ReplayPlayerGaiaScratch(b"\xa5" * 208)
        self.profile = gaia.ReplayPlayerGaiaProfile(budget)
        self.bound = gaia.bind_replay_saved_gaia_player(
            self.context,
            self.calls,
            atomics=self.atomics,
            bind_local=self.bind_local,
            scratch=self.scratch,
            profile=self.profile,
        )

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
        return prior

    @contextmanager
    def bind_local(self, view):
        with self.memory.bind_local(view) as address:
            self.frame, self.active = address, True
            try:
                yield address
            finally:
                self.closed.append(bytes(view))
                self.active = False

    def home(self, offset):
        return self.frame + offset - 0x20

    def result(self, address, *, status=0, control=0, vector=0, count=0, capacity=0):
        for offset, value in (
            (0, vector),
            (8, vector + 32 * count),
            (16, vector + 32 * capacity),
            (24, status),
            (32, control),
        ):
            self.memory.write(address + offset, 8, value)
        self.memory.write(address + 40, 1, 0)

    def control(self, *, strong=1, weak=1, destroy=0xD0, dispose=0xD8):
        address, table = self.memory.allocate(16), self.memory.allocate(16)
        for offset, value, width in ((0, table, 8), (8, strong, 4), (12, weak, 4)):
            self.memory.write(address + offset, width, value)
        self.memory.write(table, 8, destroy)
        self.memory.write(table + 8, 8, dispose)
        return address, table

    def terminal(self, target, args, data):
        self.events.append(("i", target, args))
        assert self.primitive.call is not None
        return self.primitive.call(target, args, data)

    def dispatch(self, target, args, data):
        self.events.append(("c", target, args))
        if target in self.unavailable:
            raise UnresolvedReplayTaskRebuild(f"authored required service {target:x} unavailable")
        if target in self.effects:
            return self.effects[target](args)
        if target == DERIVED:
            assert self.active and data is None
            subject, output, stream, world, pointer = args
            assert (subject, output, stream, world) == (
                self.subject,
                self.output,
                self.stream,
                0x7700,
            )
            assert pointer == self.home(0x30) and pointer != self.index
            assert self.memory.read(self.home(0x20), 8) == pointer
            self.seen_derived_index = self.memory.read(pointer, 4)
            self.memory.write(self.output + 24, 8, self.derived_status)
            if self.on_derived:
                self.on_derived(args)
            return self.derived_return
        if target in (INPUT, INPUT2):
            assert self.active and data is None
            stream, temporary, destination, width = args
            assert stream == self.stream and temporary == self.home(0x38)
            site, size, kind, offset = self.pending.pop(0)
            assert width == size
            expected_destination = (
                self.subject + offset
                if kind == "field"
                else self.home(offset)
                if kind == "local"
                else offset
            )
            assert destination == expected_destination, (
                hex(site),
                destination,
                expected_destination,
            )
            before = self.memory.read_bytes(temporary, 48)
            payload = bytes([(len(self.inputs) % 239) + 1]) * width
            self.memory.write_bytes(destination, payload)
            returned = temporary if self.returned_result is None else self.returned_result
            self.result(temporary)
            if returned != temporary:
                self.result(returned)
            self.memory.write(returned + 24, 8, 0xBAD if site == self.fail_site else 0)
            self.inputs.append((site, target, temporary, destination, width, returned, before))
            if self.on_input:
                self.on_input(site, temporary, returned)
            return returned
        if target == MALLOC:
            assert self.primitive.call is not None
            allocated = self.primitive.call(target, args, data)
            self.allocations.append(allocated)
            if self.on_malloc:
                self.on_malloc(allocated)
            return allocated
        if target in self.routes:
            bound = self.routes[target]
            assert bound.call is not None
            return bound.call(target, args, data)
        assert self.primitive.call is not None
        return self.primitive.call(target, args, data)

    def run(self):
        assert self.bound.call is not None
        return self.bound.call(
            ENTRY, (self.subject, self.output, self.stream, 0x7700, self.index), None
        )


@pytest.mark.parametrize(
    "version,count,size",
    [
        (-1, 4, 16),
        (0x911EA, 4, 16),
        (0x911EB, 4, 16),
        (0x911EC, 17, 68),
        (0x9F850, 17, 68),
        (0x9F851, 23, 156),
        (0x9F852, 23, 156),
        (0x9FAE0, 23, 156),
        (0x9FAE1, 23, 156),
        (0x9FAE2, 30, 452),
    ],
)
def test_complete_literal_fixed_version_protocol_and_actual_list_helpers(version, count, size):
    f = Fixture(version)
    assert f.run() == f.subject and not f.pending
    assert len(f.inputs) == count and sum(row[4] for row in f.inputs) == size
    assert len(f.allocations) == 5
    for index, address in enumerate(f.allocations):
        assert f.memory.read(f.subject + 0x13F8 + index * 24, 8) == address
        assert f.memory.read(address, 8) == 0x1432B3DA8
        assert f.memory.read_bytes(address + 8, 16) == bytes(16)
    assert f.memory.read_bytes(f.subject + 0x1471, 3) == b"\xcd" * 3
    assert f.memory.read_bytes(f.subject + 0x16D8, 16) == b"\xcd" * 16
    assert f.inputs[0][6] == b"\xa5" * 48
    assert f.memory.read_bytes(f.output + 41, 7) == b"\xc7" * 7
    assert not f.active
    with pytest.raises(ReplayMemoryError):
        f.memory.read(f.home(0x68), 8)


@pytest.mark.parametrize("site", GUARDED)
def test_each_of_19_static_guards_returns_current_home_only_after_finalization(site):
    f = Fixture(0x911EB if site in (0x14174FD98, 0x14174FE05) else 0xA0000)
    f.fail_site = site
    replacement = 0x112233445566

    def change_home(at, temporary, returned):
        if at == site:
            f.memory.write(f.home(0x68), 8, replacement)

    f.on_input = change_home
    assert f.run() == replacement
    assert f.inputs[-1][0] == site and f.memory.read(f.output + 24, 8) == 0xBAD
    final = max(i for i, event in enumerate(f.events) if event[:2] == ("c", FINAL))
    status = max(i for i, event in enumerate(f.events) if event[:3] == ("r", f.output + 24, 8))
    assert final < status and f.events[-1][:3] == ("r", f.home(0x68), 8)
    assert f.closed[-1][0x18 + 40] == 1


def test_final_Input_has_no_additional_status_guard_but_does_finalize():
    f = Fixture()
    f.fail_site = LAST[-1]
    assert f.run() == f.subject and not f.pending
    assert f.memory.read(f.output + 24, 8) == 0xBAD
    last = max(i for i, event in enumerate(f.events) if event[:2] == ("c", FINAL))
    assert f.events[last + 1 :] == [
        ("r", f.home(0x38), 8, 0),
        ("r", f.home(0x68), 8, f.subject),
    ]


@pytest.mark.parametrize("returned", [None, True, -9, 1 << 90])
def test_Derived_return_is_ignored_copied_index_is_live_and_inherited_error_does_not_skip(returned):
    f = Fixture()
    f.derived_return, f.derived_status = returned, 0xBAD

    def mutate(args):
        f.memory.write(args[-1], 4, 0x87654321)

    f.on_derived = mutate
    f.run()
    assert f.seen_derived_index == 0x12345678
    assert f.memory.read(f.index, 4) == 0x12345678
    assert f.inputs[0][0] == FIRST and not f.pending


def test_frame_seed_is_coherent_and_unreached_cells_are_not_zeroed_on_missing_Derived():
    f = Fixture()
    f.unavailable.add(DERIVED)
    with pytest.raises(UnresolvedReplayTaskRebuild, match="1416c2440"):
        f.run()
    raw = bytearray(b"\xa5" * 208)
    for native, width, value in (
        (0x20, 8, f.home(0x30)),
        (0x30, 4, 0x12345678),
        (0x68, 8, f.subject),
        (0xD8, 8, f.subject),
    ):
        raw[native - 0x20 : native - 0x20 + width] = value.to_bytes(width, "little")
    assert f.closed == [bytes(raw)] and not f.active
    assert f.memory.read_bytes(f.subject, 0x16E8) == b"\xcd" * 0x16E8
    with pytest.raises(ReplayMemoryError):
        f.memory.read(f.home(0x30), 4)


def test_missing_memset_preserves_exact_preceding_sparse_initialization():
    f = Fixture()
    f.unavailable.add(MEMSET)
    with pytest.raises(UnresolvedReplayTaskRebuild, match="142d6e3b7"):
        f.run()
    assert f.memory.read(f.subject, 8) == 0x1432F6C88
    assert f.memory.read_bytes(f.subject + 0x13F0, 0x80) == bytes(0x80)
    assert f.memory.read_bytes(f.subject + 0x1528, 0x168) == b"\xcd" * 0x168
    assert f.memory.read(f.subject + 0x1690, 4) == 0xCDCDCDCD
    assert f.memory.read(f.subject + 0x10, 4) == 0xCDCDCDCD and not f.inputs


def test_allocation_home_is_live_but_held_RAX_controls_zero_constructor_and_publication():
    f = Fixture(0x911EB)
    altered = f.memory.allocate(24)

    def home_write(address, width, value):
        if address == f.home(0xE0):
            f.memory.write(address, width, altered)

    f.on_write = home_write
    f.run()
    assert len(f.allocations) == 5
    assert f.memory.read(f.subject + 0x13F8, 8) == f.allocations[0]
    assert f.memory.read(f.allocations[0], 8) == 0x1432B3DA8
    assert int.from_bytes(f.closed[-1][0xC0:0xC8], "little") == altered


def test_null_malloc_skips_constructor_and_publishes_null_before_version():
    f = Fixture(0x911EB)
    f.effects[MALLOC] = lambda args: 0
    f.run()
    assert not any(event[:2] == ("c", LIST) for event in f.events)
    assert all(f.memory.read(f.subject + 0x13F8 + n * 24, 8) == 0 for n in range(5))
    assert len([event for event in f.events if event[:2] == ("c", MALLOC)]) == 5


def test_constructor_actual_return_is_published_and_version_is_current_after_it():
    f = Fixture(0xA0000)
    sentinel = f.memory.allocate(24)

    def construct(args):
        f.memory.write(VERSION, 4, 0x911EB)
        return sentinel

    f.effects[LIST] = construct
    f.pending = protocol(0xA0000)[:2]
    f.run()
    assert not f.pending
    assert all(f.memory.read(f.subject + 0x13F8 + n * 24, 8) == sentinel for n in range(5))


def test_old_path_uses_held_EBX_despite_home30_alias_mutation():
    f = Fixture(0x911EB)

    def mutate(allocated):
        f.memory.write(f.home(0x30), 4, U32)

    f.on_malloc = mutate
    f.run()
    assert len(f.allocations) == 5
    assert int.from_bytes(f.closed[-1][0x10:0x14], "little") == 5


def test_modern_counter_reset_changes_wire_index_but_held_cursor_advances_and_budget_bounds():
    f = Fixture(budget=2)
    f.pending = protocol(0xA0000)[:5] + protocol(0xA0000)[2:5]

    def reset(site, temporary, returned):
        if site == LOOP[2]:
            f.memory.write(f.home(0x30), 4, 0)

    f.on_input = reset
    # Reload0 then INC1; second iteration wireindex1; reset0 then INC1 again.
    f.pending[-3:] = [(site, 4, "field", 0x1418 + 4 * n) for n, site in enumerate(LOOP)]
    with pytest.raises(UnresolvedReplayTaskRebuild, match="budget"):
        f.run()
    assert not f.pending and len(f.allocations) == 2
    assert f.memory.read(f.subject + 0x13F8, 8) == f.allocations[0]
    assert f.memory.read(f.subject + 0x1410, 8) == f.allocations[1]


@pytest.mark.parametrize("counter", [0x80000000, U32, 0x7FFFFFFF])
def test_modern_negative_or_wrapping_current_counter_refuses_after_completed_three_inputs(counter):
    f = Fixture()

    def mutate(site, temporary, returned):
        if site == LOOP[0]:
            f.memory.write(f.home(0x30), 4, counter)

    f.on_input = mutate
    with pytest.raises(UnresolvedReplayTaskRebuild, match="counter"):
        f.run()
    assert [row[0] for row in f.inputs][-3:] == list(LOOP)
    assert int.from_bytes(f.closed[-1][0x10:0x14], "little") == counter
    assert len(f.allocations) == 1


def test_held_wire_index_survives_counter_mutation_and_current_base_is_reloaded_each_input():
    f = Fixture()
    other = f.memory.allocate(0x16E8)

    def change(site, temporary, returned):
        if site == LOOP[0]:
            f.memory.write(f.home(0x30), 4, 4)
            f.memory.write(f.home(0x68), 8, other)

    f.on_input = change
    f.pending = protocol(0xA0000)[:5] + protocol(0xA0000)[17:]
    f.pending[3:5] = [
        (LOOP[1], 4, "absolute", other + 0x1404),
        (LOOP[2], 4, "absolute", other + 0x1408),
    ]
    assert f.run() == other and not f.pending
    assert len(f.allocations) == 1


def test_current_saved_destination_read_can_replace_held_vptr_slot_before_actual_call():
    f = Fixture()
    seen = []

    def change(address, width, value):
        if address == f.home(0x88):
            f.memory.write(f.table + 24, 8, INPUT2)
            seen.append(True)

    f.on_read = change
    f.run()
    assert seen
    row = next(item for item in f.inputs if item[0] == EXTENSION[0])
    assert row[1] == INPUT2
    destination_read = f.events.index(("r", f.home(0x88), 8, f.subject + 0x1474))
    assert any(event[:3] == ("r", f.stream, 8) for event in f.events[:destination_read])
    assert f.events[destination_read + 1] == ("r", f.table + 24, 8, INPUT2)


def test_modern_loop_destination_read_precedes_stream_vptr_capture():
    f = Fixture()
    table2 = f.memory.allocate(32)
    f.memory.write(table2 + 24, 8, INPUT2)
    changed = []

    def change(address, width, value):
        if address == f.home(0x68) and len(f.inputs) == 2 and not changed:
            f.memory.write(f.stream, 8, table2)
            changed.append(True)

    f.on_read = change
    f.run()
    assert changed and f.inputs[2][1] == INPUT2


def test_input_returned_Result_differs_from_fixed_control_and_is_forwarded_actual():
    f = Fixture()
    returned = f.memory.calloc(1, 48)
    f.returned_result = returned
    control, _ = f.control(strong=2)

    def supply(site, temporary, result):
        if site == FIRST:
            f.memory.write(temporary + 32, 8, control)

    f.on_input = supply
    f.run()
    assert f.memory.read(control + 8, 4) == 1
    assert f.inputs[0][5] == returned and returned != f.home(0x38)
    assert f.memory.read(returned + 40, 1) == 1


def test_same_output_returned_identity_still_assigns_pair_but_skips_vector_copy():
    f = Fixture()
    f.returned_result = f.output
    f.run()
    assert not any(event[:2] == ("c", COPY) for event in f.events)
    assert len([event for event in f.events if event[:2] == ("c", PAIR)]) == 30
    assert f.memory.read(f.output + 40, 1) == 0


def test_manual_vector_reads_are_current_after_actual_pair_callback_and_wrapped_SAR5():
    f = Fixture()
    begin, end = 0x1000, 0xFE0
    seen = []

    def pair(args):
        f.memory.write(f.home(0x38), 8, begin)
        f.memory.write(f.home(0x38) + 8, 8, end)

    def copy(args):
        seen.append(args)
        f.memory.write(f.home(0x38), 8, 0)
        f.memory.write(f.home(0x38) + 8, 8, 0)

    f.effects[PAIR], f.effects[COPY] = pair, copy
    f.run()
    assert seen[0] == (f.output, begin, U64)


def test_strong_callback_keeps_held_control_then_reloads_its_current_weak_vptr():
    f = Fixture()
    f.returned_result = f.output
    control, table = f.control()
    other, _ = f.control(strong=7, weak=9)
    called = []

    def supply(site, temporary, returned):
        if site == FIRST:
            f.memory.write(temporary + 32, 8, control)

    def destroy(args):
        f.memory.write(f.home(0x38) + 32, 8, other)
        f.memory.write(table + 8, 8, 0xD9)
        called.append(("destroy", args))

    f.on_input = supply
    f.effects[0xD0] = destroy
    f.effects[0xD9] = lambda args: called.append(("dispose", args))
    f.run()
    assert called == [("destroy", (control,)), ("dispose", (control,))]
    assert f.memory.read(control + 12, 4) == 0
    assert f.memory.read(other + 12, 4) == 9


def test_cleanup_can_clear_error_before_current_guard_and_set_error_after_success():
    f = Fixture()
    f.fail_site = FIRST
    count = []
    actual = f.routes[FINAL]

    def finalize(args):
        assert actual.call is not None
        actual.call(FINAL, args, None)
        count.append(True)
        f.memory.write(f.output + 24, 8, 0 if len(count) == 1 else 0xBAD)

    f.effects[FINAL] = finalize
    f.run()
    assert [row[0] for row in f.inputs] == [FIRST, SECOND]
    assert f.memory.read(f.output + 24, 8) == 0xBAD


def test_missing_vector_finalizer_preserves_forwarding_and_unmaps_live_frame():
    f = Fixture()
    f.unavailable.add(FINAL)
    with pytest.raises(UnresolvedReplayTaskRebuild, match="1402bd890"):
        f.run()
    assert [row[0] for row in f.inputs] == [FIRST]
    assert f.closed[-1][0x18 + 40] == 1
    assert f.memory.read(f.output + 40, 1) == 0
    assert not f.active
    with pytest.raises(ReplayMemoryError):
        f.memory.read(f.home(0x38), 1)


def test_actual_vector_finalizer_frees_elements_without_second_control_release():
    f = Fixture()
    f.returned_result = f.output
    vector = f.memory.calloc(1, 32)
    control, _ = f.control(strong=2)

    def supply(site, temporary, returned):
        if site == FIRST:
            f.result(temporary, vector=vector, count=1, capacity=1, control=control)

    f.on_input = supply
    f.run()
    assert f.memory.read(control + 8, 4) == 1
    assert any(event[:2] == ("c", 0x1402A88A0) for event in f.events)
    with pytest.raises(ReplayMemoryError):
        f.memory.read(vector, 1)


def test_missing_actual_atomic_preserves_forwarding_before_fixed_control_release():
    f = Fixture()
    f.returned_result = f.output
    control, _ = f.control(strong=2)
    f.bound = gaia.bind_replay_saved_gaia_player(
        f.context,
        f.calls,
        atomics=ReplayUnitAIMapAtomics(None, None),
        bind_local=f.bind_local,
        scratch=f.scratch,
        profile=f.profile,
    )

    def supply(site, temporary, returned):
        f.memory.write(temporary + 32, 8, control)

    f.on_input = supply
    with pytest.raises(UnresolvedReplayTaskRebuild, match="atomic effect unavailable"):
        f.run()
    assert f.memory.read(f.output + 40, 1) == 0
    assert f.memory.read(control + 8, 4) == 2
    assert not any(event[:2] == ("c", FINAL) for event in f.events)


def test_missing_current_destroy_preserves_strong_decrement_and_does_not_decrement_weak():
    f = Fixture()
    f.returned_result = f.output
    control, _ = f.control()

    def supply(site, temporary, returned):
        f.memory.write(temporary + 32, 8, control)

    f.on_input = supply
    with pytest.raises(UnresolvedReplayTaskRebuild, match="d0"):
        f.run()
    assert f.memory.read(control + 8, 4) == 0
    assert f.memory.read(control + 12, 4) == 1


@pytest.mark.parametrize("target", [PAIR, COPY, FORWARD, MALLOC, LIST])
def test_reached_mandatory_child_refuses_without_default_success(target):
    f = Fixture(0x911EB if target == FORWARD else 0xA0000)
    f.unavailable.add(target)
    with pytest.raises(UnresolvedReplayTaskRebuild, match=f"{target:x}"):
        f.run()
    assert not f.active
    if target == LIST:
        assert f.memory.read_bytes(f.allocations[0], 24) == bytes(24)
        assert f.memory.read(f.subject + 0x13F8, 8) == 0


def test_budget_zero_refuses_first_list_after_completed_initial_inputs():
    f = Fixture(budget=0)
    with pytest.raises(UnresolvedReplayTaskRebuild, match="budget"):
        f.run()
    assert [row[0] for row in f.inputs] == [FIRST, SECOND] and not f.allocations


def test_skipped_extension_holds_EAX_despite_saved_pointer_read_mutating_current_version():
    f = Fixture(0x9F850)
    changed = []

    def change(address, width, value):
        if address == f.home(0x70):
            f.memory.write(VERSION, 4, 0xA0000)
            changed.append(True)

    f.on_read = change
    f.run()
    assert changed and len(f.inputs) == 17 and not f.pending
    assert f.memory.read(f.subject + 0x14F8, 4) == 0


def test_completed_extension_reloads_version_and_saved_default_pointers_in_source_order():
    f = Fixture(0x9F851)
    locations = [f.memory.allocate(4) for _ in range(3)]
    original = f.subject + 0x14CC

    def stores(address, width, value):
        if address == original and width == 4 and len(f.inputs) == 23:
            f.memory.write(f.home(0x78), 8, locations[1])
        if address == locations[1]:
            f.memory.write(f.home(0x80), 8, locations[2])
            f.memory.write(VERSION, 4, 0xA0000)

    f.on_write = stores
    f.pending.extend(protocol(0xA0000)[23:])
    # Held final12/13 retain the newly loaded locations across final Inputs.
    f.pending[-5] = (LAST[2], 4, "absolute", locations[1])
    f.pending[-2] = (LAST[5], 4, "absolute", locations[2])
    f.run()
    assert len(f.inputs) == 30 and not f.pending
    assert f.memory.read(locations[1], 4) != U32 and f.memory.read(locations[2], 4) != U32
    assert f.memory.read(f.subject + 0x14F8, 4) == 0


def test_final_pointer_registers_stay_held_when_saved_homes_change_after_first_final_input():
    f = Fixture()
    other = f.memory.calloc(1, 4)

    def change(site, temporary, returned):
        if site == LAST[0]:
            f.memory.write(f.home(0x78), 8, other)
            f.memory.write(f.home(0x80), 8, other)

    f.on_input = change
    f.run()
    assert not f.pending
    assert f.memory.read(other, 4) == 0


def test_unknown_router_forwards_target_args_and_same_data_identity():
    f = Fixture()
    seen = []
    data = memoryview(bytearray(b"payload"))
    f.effects[0xFF00] = lambda args: seen.append(args) or 99
    # Check raw data delegation through a separate explicit delegate.
    calls = ReplayTaskRebuildCalls(
        lambda target, args, supplied: seen.append((target, args, supplied)) or 77
    )
    bound = gaia.bind_replay_saved_gaia_player(
        f.context,
        calls,
        atomics=f.atomics,
        bind_local=f.bind_local,
        scratch=f.scratch,
        profile=f.profile,
    )
    assert bound.call is not None
    assert bound.call(0xFF00, (4, 5), data) == 77
    assert seen == [(0xFF00, (4, 5), data)] and seen[0][2] is data


@pytest.mark.parametrize("value", [-1, True, 0x80000000])
def test_profile_requires_explicit_finite_integer_budget(value):
    with pytest.raises(ValueError):
        gaia.ReplayPlayerGaiaProfile(value)


@pytest.mark.parametrize("seed", [b"", bytes(207), bytes(209), bytearray(208)])
def test_scratch_requires_exact_immutable_coherent_seed(seed):
    with pytest.raises(ValueError):
        gaia.ReplayPlayerGaiaScratch(seed)
