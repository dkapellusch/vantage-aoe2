"""Authored whole-history caller controls using real owned Input/marker/cleanup/storage.

These controls are not native snapshots or recording replay results. Fault/status
injection and mutation callbacks are explicit owned effects; no unknown child is
allowed to succeed by default. All native bodies remain independently source-bound.
"""

from __future__ import annotations

from contextlib import contextmanager

import pytest

from vantage import replay_player_history_stream as history
from vantage.replay_base_saved_leaves import bind_replay_base_saved_leaves
from vantage.replay_memory import ReplayMemory, ReplayMemoryError
from vantage.replay_player_construction_support import (
    ReplayPlayerSupportFloatingCalls,
    ReplayPlayerSupportScratch,
    bind_replay_player_marker,
)
from vantage.replay_player_history import (
    ReplayPlayerHistoryScratch,
    bind_replay_player_history,
)
from vantage.replay_saved_apply import bind_replay_saved_apply
from vantage.replay_saved_input import ReplaySavedInput, bind_replay_saved_input
from vantage.replay_saved_pair import bind_replay_saved_pair
from vantage.replay_saved_result import bind_replay_saved_result
from vantage.replay_task_list_storage import bind_replay_task_list_storage
from vantage.replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
)
from vantage.replay_unit_ai_map import ReplayUnitAIMapAtomics

ENTRY, INPUT, CALLOC = 0x141634B00, 0xC011, 0xCA1101
FREE, MEMSET, MOVE = 0x142D6BAB4, 0x142D6E3B7, 0x142D6E3DB
U64, VERSION = (1 << 64) - 1, 0x1440A0D94
VERSIONS = (
    -1,
    0x947AD,
    0x947AE,
    0x951EA,
    0x951EB,
    0x95709,
    0x9570A,
    0x95998,
    0x95999,
    0x95EB7,
    0x95EB8,
    0x9D479,
    0x9D47A,
    0xA91EA,
    0xA91EB,
    0xAD479,
    0xAD47A,
    0x3CFFFF,
    0x3D0000,
)


def word(value, width=4):
    return (value & ((1 << (width * 8)) - 1)).to_bytes(width, "little")


def wire(version, *, rows=0, deaths=0, slots=2):
    """Independent source grammar for unchanged finite counts and version."""
    marker = version >= 608174
    parts = [
        b"\x0b" if marker else b"",
        word(rows),
        word(17),
        word(max(rows, 0)),
        b"\x16" if marker else b"",
    ]
    for index in range(max(rows, 0)):
        parts.append(word(index + 0x1122, 2 if version >= 0x9D47A else 1))
        if version >= 0xA91EB:
            parts.append(word(index + 0x3344, 2))
    parts.append(word(deaths))
    for index in range(max(deaths, 0)):
        parts += [word(5 + index, 1), word(0x101 + index)]
        if version >= 0x951EB:
            parts += [word(0x202 + index), word(0x303 + index)]
        if version >= 0x95999:
            parts.append(word(0x404 + index))
        elif version >= 0x9570A:
            parts.append(word(0x54 + index, 1))
        if version >= 0x95EB8:
            parts.append(word(0x606 + index))
    if version >= 0xA91EB:
        parts += [word(i) for i in range(1, 16)]
    if version >= 0xAD47A:
        parts += [word(16), word(17)]
        if version >= 0x3D0000:
            parts.append(word(slots))
            start = 0
        else:
            slots, start = 9, 1
            parts += [word(0x70 + i, 2) for i in range(start, slots)]
        parts += [word(0x1000 + i) for i in range(start, slots)]
        if version < 0x3D0000:
            parts += [word(0x80 + i, 2) for i in range(start, slots)]
        parts += [word(0x2000 + i) for i in range(start, slots)]
        parts += [word(0x3000 + i) for i in range(3)]
        parts += [word(0x4000 + i, 2) for i in range(2)]
    parts.append(b"\x21" if marker else b"")
    return b"".join(parts)


class Fixture:
    def __init__(self, version=0x3D0000, *, rows=0, deaths=0, slots=2, zeros=False):
        self.memory = ReplayMemory(max_bytes=8 << 20)
        self.object = self.memory.allocate(0xF8)
        self.memory.fill(self.object, 0xA5, 0xF8)
        self.memory.write(self.object + 8, 8, 0)
        for base in (0xB0, 0xC8):
            for offset in (0, 8, 16):
                self.memory.write(self.object + base + offset, 8, 0)
        self.output = self.memory.allocate(48)
        self.memory.fill(self.output, 0xA5, 48)
        self.stream, self.vtable = self.memory.allocate(8), self.memory.allocate(32)
        self.memory.write(self.stream, 8, self.vtable)
        self.memory.write(self.vtable + 24, 8, INPUT)
        self.memory.map_bytes(VERSION, word(version))
        self.memory.map_bytes(0x1440A0DAE, b"\0\0\0" if zeros else b"\x0b\x16\x21")
        self.memory.map_bytes(0x1432ED700, bytes.fromhex("e17a1441"))
        self.memory.map_bytes(0x143235268, bytes.fromhex("00008047"))
        for slot, target in (
            (0x143199DC0, CALLOC),
            (0x143199DD0, FREE),
            (0x143199938, MEMSET),
            (0x1431999A0, MOVE),
        ):
            self.memory.map_bytes(slot, word(target, 8))
        self.payload = (
            bytes(8192) if zeros else wire(version, rows=rows, deaths=deaths, slots=slots)
        )
        self.source = ReplaySavedInput(self.payload)
        self.events, self.routes, self.effects, self.blocked = [], {}, {}, set()
        self.on_read = self.on_write = self.after_call = self.after_marker = None
        self.frame, self.frame_after, self.active = 0, b"", False
        self.fail_offset, self.fail_marker = None, None
        self.refusal_event_index = None
        self.marker_return, self.input_return = "actual", "actual"
        self.context = ReplayTaskRebuildStorage(self.object, self.read, self.write)
        self.calls = ReplayTaskRebuildCalls(self.dispatch)
        self.primitive = self.memory.runtime_calls(calloc_target=CALLOC)
        self.imports = ReplayTaskRebuildCalls(self.import_call)
        self.atomics = ReplayUnitAIMapAtomics(
            self.memory.compare_exchange_u32, self.memory.fetch_add_u32
        )
        self.input = bind_replay_saved_input(
            self.context,
            ReplayTaskRebuildCalls(None),
            self.source,
            stream=self.stream,
            target=INPUT,
            result_bytes=bytes(48),
        )
        self.register(
            (FREE, MEMSET, MOVE), bind_replay_task_list_storage(self.context, self.imports)
        )
        self.register(
            (0x1408EE150,),
            bind_replay_base_saved_leaves(
                self.context,
                self.calls,
                atomics=self.atomics,
                bind_local=self.bind_local,
                scratch=b"\xa5" * 8,
            ),
        )
        self.register(
            (0x14090D270,), bind_replay_saved_pair(self.context, self.calls, atomics=self.atomics)
        )
        self.register(
            (0x1409076B0, 0x1402B9080),
            bind_replay_saved_apply(
                self.context, self.calls, atomics=self.atomics, imports=self.imports
            ),
        )
        self.register(
            (0x140900620, 0x1402BD890),
            bind_replay_saved_result(
                self.context, self.calls, atomics=self.atomics, imports=self.imports
            ),
        )
        self.register(
            (0x14162CB30,),
            bind_replay_player_history(
                self.context,
                self.calls,
                atomics=self.atomics,
                bind_local=self.bind_local,
                scratch=ReplayPlayerHistoryScratch(b"\xa5" * 0x90),
                imports=self.imports,
            ),
        )
        self.real_floating = bind_replay_player_marker(
            self.context,
            self.calls,
            ReplayPlayerSupportFloatingCalls(None),
            atomics=self.atomics,
            bind_local=self.bind_local,
            scratch=ReplayPlayerSupportScratch(b"\xa5" * 0xB8, b"\xa5" * 0x48),
            mxcsr=0x1F80,
        )
        self.floating = ReplayPlayerSupportFloatingCalls(self.marker)
        self.scratch = history.ReplayHistoryStreamScratch(b"\xa5" * 0x958)
        self.bound = history.bind_replay_history_stream(
            self.context,
            self.calls,
            atomics=self.atomics,
            bind_local=self.bind_local,
            scratch=self.scratch,
            floating=self.floating,
            imports=self.imports,
        )

    def register(self, targets, binding):
        for target in targets:
            self.routes[target] = binding

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

    def import_call(self, target, args, data):
        self.events.append(("i", target, args))
        if target in self.effects:
            return self.effects[target](args)
        assert self.primitive.call is not None
        return self.primitive.call(target, args, data)

    def dispatch(self, target, args, data):
        self.events.append(("c", target, args))
        if target in self.blocked:
            raise UnresolvedReplayTaskRebuild(f"test mandatory blocked{target:x}")
        if target in self.effects:
            result = self.effects[target](args)
        elif target == INPUT:
            assert self.input.call is not None
            result = self.input.call(target, args, data)
            if self.fail_offset is not None and args[1] == self.frame + self.fail_offset:
                self.memory.write(args[1] + 24, 8, 1)
                self.refusal_event_index = len(self.events)
            if self.input_return != "actual":
                result = self.input_return
        elif target in self.routes:
            result = self.routes[target].call(target, args, data)
        else:
            assert self.primitive.call is not None
            result = self.primitive.call(target, args, data)
        if self.after_call:
            self.after_call(target, args, result)
        return result

    def marker(self, target, invocation):
        self.events.append(("m", invocation))
        assert self.real_floating.call is not None
        result = self.real_floating.call(target, invocation)
        if self.fail_marker == invocation.label:
            self.memory.write(invocation.output + 24, 8, 1)
            self.refusal_event_index = len(self.events)
        if self.after_marker:
            self.after_marker(invocation)
        return result if self.marker_return == "actual" else self.marker_return

    @contextmanager
    def bind_local(self, view):
        with self.memory.bind_local(view) as address:
            outer = len(view) == 0x958
            if outer:
                self.frame, self.active = address, True
            try:
                yield address
            finally:
                if outer:
                    self.frame_after = self.memory.read_bytes(address, len(view))
                    self.active = False

    def run(self, bound=False):
        if bound:
            assert self.bound.call is not None
            return self.bound.call(ENTRY, (self.object, self.output, self.stream), None)
        return history.read_replay_history_stream(
            self.context,
            self.object,
            self.output,
            self.stream,
            calls=self.calls,
            atomics=self.atomics,
            bind_local=self.bind_local,
            scratch=self.scratch,
            floating=self.floating,
            imports=self.imports,
        )

    def arrays(self, address=None):
        address = self.object if address is None else address
        result = []
        for offset in (0xB0, 0xC8):
            begin = self.memory.read(address + offset, 8)
            end = self.memory.read(address + offset + 8, 8)
            result.append([self.memory.read(p, 4) for p in range(begin, end, 4)])
        return result


@pytest.mark.parametrize("bound", [False, True])
@pytest.mark.parametrize("version", VERSIONS)
def test_all_normal_version_branches_actual_owned_providers(version, bound):
    f = Fixture(version, rows=1, deaths=1)
    assert f.run(bound) == f.output
    assert f.source.position == len(f.payload)
    assert f.memory.read_bytes(f.output, 48) == bytes(41) + b"\xa5" * 7
    assert f.memory.read(f.object + 0x6C, 8) == 0xA5A5A5A5A5A5A5A5
    row = f.memory.read(f.memory.read(f.object, 8), 4)
    assert row == (0x33441122 if version >= 0xA91EB else 0x1122 if version >= 0x9D47A else 0x22)
    node = f.memory.read(f.object + 8, 8)
    assert f.memory.read(node, 1) == 5 and f.memory.read(node + 4, 4) == 0x101
    assert f.memory.read(node + 12, 4) == (0x202 if version >= 0x951EB else 0)
    assert f.memory.read(node + 16, 4) == (0x303 if version >= 0x951EB else 0)
    assert f.memory.read(node + 20, 4) == (
        0x404 if version >= 0x95999 else 0x54 if version >= 0x9570A else 0
    )
    assert f.memory.read(node + 8, 4) == (0x606 if version >= 0x95EB8 else 0)
    assert f.memory.read(node + 24, 8) == 0
    if version >= 0xAD47A:
        start, count = (0, 2) if version >= 0x3D0000 else (1, 9)
        assert f.arrays() == [
            ([0] * start) + [base + i for i in range(start, count)] for base in (0x1000, 0x2000)
        ]
        assert f.memory.read(f.object + 0xEC, 2) == 0x4000
    assert f.active is False
    with pytest.raises(ReplayMemoryError):
        f.memory.read(f.frame, 1)


@pytest.mark.parametrize("bound", [False, True])
@pytest.mark.parametrize("rows", [0, 1])
def test_actual_modern_wire_arithmetic_is_conditional_not_native_oracle(bound, rows):
    f = Fixture(rows=rows, slots=9)
    assert f.run(bound) == f.output
    assert f.source.position == 179 + 4 * rows
    assert len([e for e in f.events if e[:2] == ("c", INPUT)]) == 48 + 2 * rows


@pytest.mark.parametrize("returned", [None, -1, 1 << 100])
def test_both_marker_and_Input_RAX_ignored(returned):
    f = Fixture()
    f.marker_return = f.input_return = returned
    assert f.run() == f.output
    assert f.source.remaining == 0


@pytest.mark.parametrize("bound", [False, True])
def test_negative_counts_skip_death_and_row_loops(bound):
    f = Fixture(rows=-1, deaths=-1, slots=0)
    assert f.run(bound) == f.output
    assert f.source.remaining == 0
    assert f.memory.read(f.object + 8, 8) == 0


def test_unknown_resize_refuses_after_prior_wire_effects():
    f = Fixture()
    f.blocked.add(0x14162CB30)
    with pytest.raises(UnresolvedReplayTaskRebuild, match="blocked14162cb30"):
        f.run()
    assert f.memory.read(f.object + 0x68, 4) == 17
    assert f.memory.read(f.object + 0x24, 4) == 2
    assert f.memory.read_bytes(f.output, 48) == b"\xa5" * 48


def test_marker_missing_provider_refuses_after_local_and_literal_effects():
    f = Fixture()
    with pytest.raises(UnresolvedReplayTaskRebuild, match="mixed-FP"):
        history.read_replay_history_stream(
            f.context,
            f.object,
            f.output,
            f.stream,
            calls=f.calls,
            atomics=f.atomics,
            bind_local=f.bind_local,
            scratch=f.scratch,
            floating=ReplayPlayerSupportFloatingCalls(None),
            imports=f.imports,
        )
    assert f.source.position == 0
    assert f.frame_after[0xB8:0xE8] == bytes(48)
    assert f.frame_after[0x20:0x28] == b"\x0b" + b"\xa5" * 7


def test_current_calloc_target_goes_terminal_even_when_equal_known_reader():
    f = Fixture()
    f.memory.write(0x143199DC0, 8, ENTRY)
    f.effects[ENTRY] = lambda args: f.memory.calloc(*args)
    assert f.run(True) == f.output
    assert ("i", ENTRY, (0, 4)) in f.events


def test_calloc_refusal_preserves_prior_processed_and_allocated_fields():
    f = Fixture()
    f.memory.write(0x143199DC0, 8, 0xCA1102)
    with pytest.raises(UnresolvedReplayTaskRebuild):
        f.run()
    assert f.source.position == 14
    assert f.memory.read(f.object, 8) == 0xA5A5A5A5A5A5A5A5
    assert f.frame_after[0x4A0] == 1


def test_first_marker_threshold_is_held_but_expected_bytes_are_current():
    f = Fixture()
    invocations = []

    def after(inv):
        invocations.append(inv)
        if len(invocations) == 1:
            f.memory.write(0x1432ED700, 4, 0x7FC01234)

    f.after_marker = after
    assert f.run() == f.output
    assert [i.xmm3_u32 for i in invocations] == [0x41147AE1] * 3
    assert [i.expected_u8 for i in invocations] == [11, 22, 33]
    assert len([e for e in f.events if e[:3] == ("r", 0x1432ED700, 4)]) == 1


def test_fixed_Result_error_refuses_before_processed_or_cleanup():
    f = Fixture()
    f.fail_offset = 0xE8
    with pytest.raises(UnresolvedReplayTaskRebuild, match="141634db6"):
        f.run()
    assert f.source.position == 5
    assert f.memory.read(f.object + 0x1C, 4) == 0
    assert f.frame_after[0x110] == 0
    assert f.frame_after[0x100:0x108] == word(1, 8)


def test_skipped_fixed_group_reuses_held_version_even_when_global_read_changes_it():
    f = Fixture(0xA0000, zeros=True)
    reads = 0

    def on_read(address, width, value):
        nonlocal reads
        if address == VERSION:
            reads += 1
            # Actual markers read version too. The third parent version read
            # here is its post-death read (after marker1/marker2 and row read).
            if reads == 4:
                f.memory.write(VERSION, 4, 0x3D0000)

    f.on_read = on_read
    assert f.run() == f.output
    assert f.memory.read(f.object + 0x64, 4) == 0xA5A5A5A5


@pytest.mark.parametrize("count", [0, 1])
def test_death_positive_only_reloads_history_home(count):
    f = Fixture(0x3D0000, zeros=True)
    other = f.memory.allocate(0xF8)
    f.memory.fill(other, 0, 0xF8)
    injected = False

    def after(target, args, result):
        nonlocal injected
        if target == INPUT and args[2] == f.frame + 0xAC and not injected:
            injected = True
            f.memory.write(f.frame + 0xAC, 4, count)
            f.memory.write(f.frame + 0x98, 8, other)

    f.after_call = after
    assert f.run() == f.output
    # Post-death fixed2c is zero only on the held/selected object actually used.
    assert f.memory.read(f.object + 0x2C, 4) == (0xA5A5A5A5 if count else 0)
    assert any(e[:3] == ("r", f.frame + 0x98, 8) for e in f.events)  # later second-header restore


def test_second_resize_uses_held_EAX_count_before_current_home_reload():
    f = Fixture(zeros=True)
    reads, resizes = 0, []

    def on_read(address, width, value):
        nonlocal reads
        if address == VERSION:
            reads += 1
            # marker1+marker2, row, postdeath, after15fields, countgate,
            # discard1gate, then discard2gate. There are no death fields.
            if reads == 8:
                f.memory.write(f.object + 0x24, 4, 3)

    def after(target, args, result):
        if target == 0x14162CB30:
            resizes.append(args)
            if len(resizes) == 2:
                # Stop later loop from requiring storage beyond the held size0.
                f.memory.write(f.object + 0x24, 4, 0)

    f.on_read, f.after_call = on_read, after
    assert f.run() == f.output
    assert [args[1] for args in resizes] == [0, 0]


def test_current_virtual18_reselected_after_each_Input():
    f = Fixture()
    alternate = f.memory.allocate(32)
    f.memory.write(alternate + 24, 8, INPUT)
    changed = False

    def after(target, args, result):
        nonlocal changed
        if target == INPUT and args[2] == f.object + 0x1C and not changed:
            changed = True
            f.memory.write(f.stream, 8, alternate)

    f.after_call = after
    assert f.run() == f.output
    assert any(e[:3] == ("r", alternate + 24, 8) for e in f.events)


def test_manual_release_holds_control_but_reloads_its_weak_virtual_and_real_vector():
    f = Fixture()
    control, replacement = f.memory.allocate(16), f.memory.allocate(16)
    first_vptr, second_vptr = f.memory.allocate(16), f.memory.allocate(16)
    allocation = f.memory.allocate(32)
    for pointer, count in ((control, 1), (replacement, 7)):
        f.memory.write(pointer, 8, first_vptr)
        f.memory.write(pointer + 8, 4, count)
        f.memory.write(pointer + 12, 4, count)
    f.memory.write(first_vptr, 8, 0xF101)
    f.memory.write(first_vptr + 8, 8, 0xF102)
    f.memory.write(second_vptr, 8, 0xF103)
    f.memory.write(second_vptr + 8, 8, 0xF104)
    callbacks = []

    def strong(args):
        callbacks.append(("strong", args, f.memory.read(control + 8, 4)))
        f.memory.write(f.frame + 0xE8 + 32, 8, replacement)
        f.memory.write(control, 8, second_vptr)

    def weak(args):
        callbacks.append(("weak", args, f.memory.read(control + 12, 4)))

    def after(target, args, result):
        if target == INPUT and args[2] == f.object + 0x1C:
            f.memory.write(args[1] + 32, 8, control)
            for offset, value in ((0, allocation), (8, allocation), (16, allocation + 32)):
                f.memory.write(args[1] + offset, 8, value)

    f.effects[0xF101], f.effects[0xF104], f.after_call = strong, weak, after
    assert f.run() == f.output
    assert callbacks == [("strong", (control,), 0), ("weak", (control,), 0)]
    assert f.memory.read(replacement + 8, 4) == 7
    assert ("i", FREE, (allocation, 32)) in f.events
    with pytest.raises(ReplayMemoryError):
        f.memory.read(allocation, 1)
    assert not any(e[0] == "c" and e[1] in (0xF102, 0xF103) for e in f.events)


def test_first_vector_current_A0_and_current_counter90_skip_index():
    f = Fixture(zeros=True)
    alternate, array = f.memory.allocate(24), f.memory.allocate(12)
    f.memory.fill(array, 0xA5, 12)
    for offset, value in ((0, array), (8, array + 12), (16, array + 12)):
        f.memory.write(alternate + offset, 8, value)
    first_destination = None

    def after(target, args, result):
        nonlocal first_destination
        if target != INPUT:
            return
        if args[2] == f.object + 0x24:
            f.memory.write(f.object + 0x24, 4, 3)
        if args[1] == f.frame + 0x178 and first_destination is None:
            first_destination = args[2]
            f.memory.write(f.frame + 0xA0, 8, alternate)
            f.memory.write(f.frame + 0x90, 4, 1)

    f.after_call = after
    assert f.run() == f.output
    destinations = [
        e[2][2] for e in f.events if e[:2] == ("c", INPUT) and e[2][1] == f.frame + 0x178
    ]
    assert destinations == [first_destination, array + 8]
    assert f.memory.read_bytes(array, 12) == b"\xa5" * 8 + bytes(4)
    assert f.frame_after[0xA0:0xA8] == word(alternate, 8)
    assert f.frame_after[0x90:0x94] == word(3)


def test_second_vector_holds_restored_history_and_original_count_pointer():
    f = Fixture(zeros=True)
    other, later = f.memory.allocate(0xF8), f.memory.allocate(0xF8)
    f.memory.fill(other, 0, 0xF8)
    f.memory.fill(later, 0xA5, 0xF8)
    first_rows, second_rows = [], []

    def after(target, args, result):
        if target != INPUT:
            return
        if args[2] == f.object + 0x24:
            f.memory.write(f.object + 0x24, 4, 2)
        if args[1] == f.frame + 0x178:
            first_rows.append(args[2])
            if len(first_rows) == 2:
                f.memory.write(f.frame + 0x98, 8, other)
        if args[1] == f.frame + 0x1D8:
            second_rows.append(args[2])
            f.memory.write(f.frame + 0x98, 8, later)

    f.after_call = after
    assert f.run() == f.output
    begin = f.memory.read(other + 0xC8, 8)
    assert second_rows == [begin, begin + 4]
    assert f.memory.read(other + 0x24, 4) == 0
    assert f.memory.read(other + 0xE0, 4) == 0
    assert f.memory.read(f.object + 0xE0, 4) == 0xA5A5A5A5
    assert f.memory.read(later + 0xE0, 4) == 0xA5A5A5A5


def test_rows_reloads_current_base_between_two_WORDs():
    f = Fixture(rows=1, slots=0)
    replacement = f.memory.allocate(4)
    f.memory.fill(replacement, 0xA5, 4)
    first = None

    def after(target, args, result):
        nonlocal first
        if target == INPUT and args[1] == f.frame + 0x328:
            first = args[2]
            f.memory.write(f.object, 8, replacement)

    f.after_call = after
    assert f.run() == f.output
    assert first is not None and f.memory.read(first, 4) == 0x1122
    assert f.memory.read(replacement, 4) == 0x3344A5A5


def test_two_death_nodes_publish_through_held_next_link_and_current_count():
    f = Fixture(deaths=2)
    assert f.run() == f.output
    first = f.memory.read(f.object + 8, 8)
    second = f.memory.read(first + 24, 8)
    assert first != second
    assert f.memory.read(first, 1) == 5 and f.memory.read(second, 1) == 6
    assert f.memory.read(second + 24, 8) == 0
    assert f.frame_after[0xAC:0xB0] == bytes(4)
    assert f.source.remaining == 0


def test_death_counter_reloads_current_local_after_callback():
    f = Fixture(zeros=True)
    mutated = False

    def after(target, args, result):
        nonlocal mutated
        if target == INPUT and args[2] == f.frame + 0xAC:
            f.memory.write(f.frame + 0xAC, 4, 2)
        if target == INPUT and args[1] == f.frame + 0x598:
            mutated = True
            f.memory.write(f.frame + 0xAC, 4, 1)

    f.after_call = after
    assert f.run() == f.output and mutated
    first = f.memory.read(f.object + 8, 8)
    assert f.memory.read(first + 24, 8) == 0
    assert len([e for e in f.events if e[:2] == ("i", CALLOC)]) == 2


def test_executed_fixed_group_reloads_version_before_later_fields():
    f = Fixture(zeros=True)

    def after(target, args, result):
        if target == INPUT and args[2] == f.object + 0x28:
            f.memory.write(VERSION, 4, 0)

    f.after_call = after
    assert f.run() == f.output
    assert f.memory.read(f.object + 0x64, 4) == 0xA5A5A5A5
    assert f.source.position == 78


@pytest.mark.parametrize("bad", [None, bytes(0x957), bytearray(0x958)])
def test_seed_shape_precondition(bad):
    with pytest.raises(ValueError, match="958"):
        history.ReplayHistoryStreamScratch(bad)


@pytest.mark.parametrize(
    "args,data", [((1, 2), None), ((1, 2, 3, 4), None), ((1, 2, 3), memoryview(b"a"))]
)
def test_bound_entry_arity_data_preflight(args, data):
    f = Fixture()
    assert f.bound.call is not None
    with pytest.raises(ValueError, match="three-operand"):
        f.bound.call(ENTRY, args, data)
    assert f.source.position == 0


def test_bound_unowned_target_delegates_actual_effect():
    f = Fixture()
    f.effects[0xF001] = lambda args: args[0] + 1
    assert f.bound.call(0xF001, (7,), None) == 8


# Independent frozen-source status locations; no runtime site table is imported.
_ERROR_CASES = [
    (0x3D0000, 0, 0, 0xE8, 0x141634DB6),
    (0x3D0000, 0, 0, 0x118, 0x141634FBB),
    (0x3D0000, 0, 0, 0x448, 0x1416351DA),
    (0x3D0000, 1, 0, 0x328, 0x141635933),
    (0x3D0000, 1, 0, 0x2F8, 0x1416357D3),
    (0x3D0000, 0, 0, 0x4D8, 0x14163567F),
    (0xA0000, 1, 0, 0x4A8, 0x141635B27),
    (0x96000, 1, 0, 0x358, 0x141635D23),
    (0x3D0000, 0, 1, 0x148, 0x141636CB6),
    (0x3D0000, 0, 1, 0x3B8, 0x141636BAA),
    (0x3D0000, 0, 1, 0x388, 0x141636543),
    (0x3D0000, 0, 1, 0x508, 0x1416363E3),
    (0x3D0000, 0, 1, 0x538, 0x141636683),
    (0x9570A, 0, 1, 0x568, 0x1416367C3),
    (0x3D0000, 0, 1, 0x598, 0x141636913),
    (0x96000, 0, 1, 0x5C8, 0x141636A64),
    (0x3D0000, 0, 0, 0x5F8, 0x141636289),
    (0x3D0000, 0, 0, 0x628, 0x141636E7A),
    (0x3D0000, 0, 0, 0x658, 0x141636FFB),
    (0x3D0000, 0, 0, 0x688, 0x1416371B1),
    (0x3D0000, 0, 0, 0x6B8, 0x141637361),
    (0x3D0000, 0, 0, 0x6E8, 0x14163750B),
    (0x3D0000, 0, 0, 0x718, 0x1416376DB),
    (0x3D0000, 0, 0, 0x748, 0x1416378AB),
    (0x3D0000, 0, 0, 0x778, 0x141637A6B),
    (0x3D0000, 0, 0, 0x7A8, 0x141637C1B),
    (0x3D0000, 0, 0, 0x7D8, 0x141637DBB),
    (0x3D0000, 0, 0, 0x808, 0x141637F00),
    (0x3D0000, 0, 0, 0x838, 0x141638050),
    (0x3D0000, 0, 0, 0x868, 0x141638151),
    (0x3D0000, 0, 0, 0x898, 0x141638290),
    (0x3D0000, 0, 0, 0x8C8, 0x141638401),
    (0x3D0000, 0, 0, 0x8F8, 0x1416385AF),
    (0x3D0000, 0, 0, 0x928, 0x1416387A0),
    (0xAD47A, 0, 0, 0x3E8, 0x141638DFC),
    (0x3D0000, 0, 0, 0x178, 0x141638F53),
    (0xAD47A, 0, 0, 0x1A8, 0x141639103),
    (0x3D0000, 0, 0, 0x1D8, 0x14163928C),
    (0x3D0000, 0, 0, 0x208, 0x141638C57),
    (0x3D0000, 0, 0, 0x238, 0x1416394E2),
    (0x3D0000, 0, 0, 0x268, 0x141639732),
    (0x3D0000, 0, 0, 0x298, 0x141639962),
    (0x3D0000, 0, 0, 0x2C8, 0x141639B82),
]


@pytest.mark.parametrize("version,rows,deaths,offset,error", _ERROR_CASES)
def test_every_raw_Input_returned_error_frontier(version, rows, deaths, offset, error):
    f = Fixture(version, rows=rows, deaths=deaths)
    f.fail_offset = offset
    with pytest.raises(UnresolvedReplayTaskRebuild, match=f"frontier{error:x}"):
        f.run()
    assert f.source.position > 0
    assert f.frame_after[offset + 40] == 0
    assert f.memory.read_bytes(f.output, 48) == b"\xa5" * 48
    assert f.events[f.refusal_event_index :] == [("r", f.frame + offset + 24, 8, 1)]


@pytest.mark.parametrize(
    "label,error,offset",
    [
        (0x1432ED6C0, 0x141634B98, 0xB8),
        (0x1432ED6D0, 0x141635391, 0x478),
        (0x1432ED6E0, 0x141639DB5, 0x418),
    ],
)
def test_all_three_marker_error_frontiers(label, error, offset):
    f = Fixture()
    f.fail_marker = label
    with pytest.raises(UnresolvedReplayTaskRebuild, match=f"frontier{error:x}"):
        f.run(True)
    assert f.frame_after[offset + 40] == 0
    assert f.memory.read_bytes(f.output, 48) == b"\xa5" * 48
    assert f.events[f.refusal_event_index :] == [("r", f.frame + offset + 24, 8, 1)]
