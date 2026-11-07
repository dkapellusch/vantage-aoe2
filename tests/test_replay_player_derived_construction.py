"""Derived Player caller controls with explicit test-only descendants.

The ordinary production module is imported normally. The finite byte carrier
and opaque Base/master/AI/resource/map/descriptor fixtures establish authored
caller behavior, not native identity, a complete Player/World or playback.
"""

from __future__ import annotations

from contextlib import contextmanager

import pytest

from vantage import replay_player_derived_construction as PORT
from vantage.replay_base_saved_leaves import (
    release_replay_base_saved_pair_control,
)
from vantage.replay_player_construction_support import (
    ReplayPlayerSupportFloatingCalls,
)
from vantage.replay_player_saved_children import assign_replay_player_result
from vantage.replay_saved_apply import (
    assign_replay_saved_result_vector,
    forward_replay_saved_result,
)
from vantage.replay_saved_pair import assign_replay_saved_pair
from vantage.replay_saved_result import (
    clear_replay_saved_result_vector,
    finalize_replay_saved_result,
)
from vantage.replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
)
from vantage.replay_unit_ai_map import ReplayUnitAIMapAtomics, _release

U64 = (1 << 64) - 1


class Carrier:
    """Finite byte/defined storage with live frame aliases and explicit hooks."""

    def __init__(self, version=0x44E666, kind=0):
        self.cells, self.locals, self.events = {}, {}, []
        self.calls, self.inputs, self.markers, self.typed = [], [], [], []
        self.hook = None
        self.extra, self.values, self.statuses = {}, {}, {}
        self.refuse = None
        self.kind = kind
        self.counter = 0
        self.world_count = 0
        self.next_allocation = 0x500000
        self.null_sizes = set()
        self.s, self.out, self.stream, self.frame = 0x10000, 0x20000, 0x30000, 0x900000
        self.world, self.game, self.game_world, self.stats = 0x60000, 0x70000, 0x80000, 0xA0000
        for pointer, width, seed in (
            (self.s, 0x1400, 0xA3),
            (self.out, 48, 0),
            (self.stream, 8, 0),
            (0x31000, 32, 0),
            (0x40000, 4, 0),
            (self.world, 0x830, 0),
            (self.game, 8, 0),
            (self.game_world, 8, 0),
            (self.stats, 0x800, 0),
            (0xB0000, 0x110, 0),
        ):
            self.map(pointer, width, seed)
        self.put(0x40000, 4, 7)
        self.put(self.stream, 8, 0x31000)
        self.put(0x31018, 8, 0xABC0)
        self.put(self.world + 0x828, 8, 0xBEEF)
        for address, width, value in (
            (0x1440A0D94, 4, version),
            (0x1440A0EA8, 1, 9),
            (0x1432ED700, 4, 0x41147AE1),
            (0x144353698, 8, self.game),
        ):
            self.map(address, width)
            self.put(address, width, value)
        self.context = ReplayTaskRebuildStorage(self.s, self.read, self.write)
        self.effects = ReplayTaskRebuildCalls(self.effect)
        self.atomics = ReplayUnitAIMapAtomics(None, self.fetch_add)
        self.floating = ReplayPlayerSupportFloatingCalls(self.marker)

    def map(self, address, width, seed=0):
        for index in range(width):
            self.cells[(address + index) & U64] = seed

    def put(self, address, width, value):
        for index, byte in enumerate((value & ((1 << (width * 8)) - 1)).to_bytes(width, "little")):
            target = (address + index) & U64
            for begin, view in self.locals.items():
                if begin <= target < begin + len(view):
                    view[target - begin] = byte
                    break
            else:
                assert target in self.cells, f"unmapped write{target:x}"
                self.cells[target] = byte

    def get(self, address, width):
        raw = []
        for index in range(width):
            target = (address + index) & U64
            for begin, view in self.locals.items():
                if begin <= target < begin + len(view):
                    raw.append(view[target - begin])
                    break
            else:
                if target not in self.cells:
                    raise UnresolvedReplayTaskRebuild(f"unbacked fixture byte{target:x}")
                raw.append(self.cells[target])
        return int.from_bytes(bytes(raw), "little")

    def read(self, address, width):
        value = self.get(address, width)
        self.events.append(["read", address, width, value])
        if self.hook:
            self.hook("read", address, width, value)
        return value

    def write(self, address, width, value):
        self.put(address, width, value)
        self.events.append(["write", address, width, value])
        if self.hook:
            self.hook("write", address, width, value)

    def allocate(self, size):
        if size in self.null_sizes:
            return 0
        pointer = self.next_allocation
        self.next_allocation += max(size, 1) + 64
        self.map(pointer, size, 0xC7)
        return pointer

    def fetch_add(self, address, delta):
        old = self.read(address, 4)
        self.write(address, 4, (old + delta) & 0xFFFFFFFF)
        self.events.append(["atomic", address, delta, old])
        return old

    def zero_result(self, output, status=0):
        self.put(output, 48, 0)
        self.put(output + 24, 8, status)

    def marker(self, target, request):
        assert target == 0x14162CD70
        self.markers.append([request.output, request.label, request.xmm3_u32, request.expected_u8])
        self.zero_result(request.output, self.statuses.get(("marker", len(self.markers)), 0))
        callback = self.extra.get("marker")
        return callback(request) if callback else request.output

    def effect(self, target, args, data):
        assert data is None
        self.calls.append([target, list(args)])
        if target == self.refuse:
            raise UnresolvedReplayTaskRebuild(f"explicit missing{target:x}")
        if target in self.extra:
            return self.extra[target](args)
        context, calls, atomics = self.context, self.effects, self.atomics
        if target == 0x140991CE0:
            return assign_replay_player_result(context, *args, calls=calls)
        if target == 0x14090D270:
            return assign_replay_saved_pair(context, *args, calls=calls, atomics=atomics)
        if target == 0x1402B9080:
            return assign_replay_saved_result_vector(context, *args, calls=calls)
        if target == 0x1409076B0:
            return forward_replay_saved_result(context, *args, calls=calls, atomics=atomics)
        if target == 0x1402BD7F0:
            return clear_replay_saved_result_vector(context, *args, calls=calls)
        if target == 0x140900620:
            return finalize_replay_saved_result(context, *args, calls=calls, atomics=atomics)
        if target == 0x1408EE150:
            return release_replay_base_saved_pair_control(
                context, *args, calls=calls, atomics=atomics
            )
        if target == 0x1402AAA80:
            return _release(context, *args, calls, atomics)
        # The following are explicit opaque fixtures, never native child proofs.
        if target == 0x141713F70:
            assert args[:4] == (self.s, self.out, self.stream, self.world)
            assert self.get(args[4], 4) == 7
            self.put(self.s + 8, 8, self.world)
            self.put(self.s + 0x98, 8, self.stats)
            self.put(self.s + 0x648, 4, 7)
            self.put(self.s + 0x6A8, 8, 0xB0000)
            return self.s
        if target == 0x142D6BA78:
            return self.allocate(args[0])
        if target == 0x142D6E3B7:
            value = int.from_bytes(bytes([args[1] & 255]) * args[2], "little")
            self.put(args[0], args[2], value)
            return args[0]
        if target == 0xABC0:
            _, output, destination, width = args
            self.counter += 1
            self.inputs.append([destination, width])
            self.write(destination, width, self.values.get(destination, 0))
            self.zero_result(output, self.statuses.get(("input", self.counter), 0))
            return output
        if target in (0x1415E5830, 0x140B81D60, 0x140D94310, 0x140D07EE0, 0x140B81E60):
            output, source, line, detail, stream, destination = args
            assert source == 0x1432F2520 and stream == self.stream
            width = 1 if target == 0x140D07EE0 else 4
            value = self.kind if target == 0x1415E5830 else self.values.get(destination, 0)
            self.typed.append([target, line, detail, destination, width])
            self.write(destination, width, value)
            self.zero_result(output, self.statuses.get(("typed", len(self.typed)), 0))
            return output
        if target == 0x14148D110:
            assert len(args) == 6 and args[4:] == (self.s, 0)
            self.put(args[0], 8, self.allocate(0x400))
            return args[0]
        if target in (0x14162D370, 0x14149D9A0):
            self.zero_result(args[2] if target == 0x14162D370 else args[1])
            return args[0]
        if target == 0x140D6ACC0:
            assert args == (self.game,)
            return self.game_world
        if target == 0x141603EF0:
            assert args == (self.game_world,)
            return self.world_count & 0xFFFFFFFF
        if target == 0x1416E4C30:
            header, count, source = args
            count = count if count < 1 << 63 else count - (1 << 64)
            width = max(1, (max(count, 0) + 31) // 32) * 4
            pointer = self.allocate(width)
            self.put(pointer, width, 0)
            self.put(header, 8, pointer)
            return None
        if target in (0x141027450, 0x141227140, 0x140C2AE90):
            return args[0]
        if target in (0x141028560, 0x14134B780):
            self.zero_result(args[1])
            return args[1]
        if target == 0x140D6A530:
            pointer = self.allocate(0x50)
            self.put(pointer, 0x50, 0)
            self.put(args[1], 8, pointer)
            return args[1]
        if target == 0x141732B10:
            self.put(args[1], 32, 0)
            return args[1]
        if target == 0x140C7EBE0:
            assert args[1] == 7 and args[3:] == (self.s, self.out, self.stream)
            return args[0]
        if target == 0x1416C2180:
            self.put(args[0], 16, 0)
            return args[0]
        if target == 0x1416BFE70:
            self.put(args[0], 8, 0)
            return args[0]
        if target == 0x141603CB0:
            self.put(args[1], 16, 0)
            return args[1]
        if target == 0x140F92850:
            self.put(args[1], 24, 0)
            return None
        if target in (0x1416C6A40, 0x140A1B220, 0x140990140, 0x1402A8790, 0x1416DFCA0):
            return None
        raise UnresolvedReplayTaskRebuild(f"unbound test child{target:x}")

    @contextmanager
    def binding(self, view):
        assert self.frame not in self.locals
        self.locals[self.frame] = view
        try:
            yield self.frame
        finally:
            del self.locals[self.frame]

    @contextmanager
    def phase(self, seed=0):
        with self.binding(memoryview(bytearray([seed] * 0xD8))):
            yield PORT._DerivedConstruction(
                self.context,
                self.effects,
                self.atomics,
                self.floating,
                self.s,
                self.out,
                self.stream,
                self.frame,
                0x41147AE1,
            )

    def whole(self, bound=False, seed=0):
        kwargs = dict(
            calls=self.effects,
            atomics=self.atomics,
            bind_local=self.binding,
            scratch=bytes([seed] * 0xD8),
            floating=self.floating,
        )
        args = (self.s, self.out, self.stream, self.world, 0x40000)
        if bound:
            return PORT.bind_replay_saved_derived_player(self.context, **kwargs).call(
                0x1416C2440, args, None
            )
        return PORT.construct_replay_saved_derived_player(self.context, *args, **kwargs)


def refusal(function, text):
    try:
        function()
    except (ValueError, UnresolvedReplayTaskRebuild) as error:
        assert text in str(error), str(error)
        return
    raise AssertionError("required refusal missing")


@pytest.mark.parametrize(
    "version,kind",
    [
        pytest.param(-0x1, 0x0, id="whole--1-kind0"),
        pytest.param(-0x1, 0x1, id="whole--1-kind1"),
        pytest.param(-0x1, 0x3, id="whole--1-kind3"),
        pytest.param(0x0, 0x0, id="whole-0-kind0"),
        pytest.param(0x0, 0x1, id="whole-0-kind1"),
        pytest.param(0x0, 0x3, id="whole-0-kind3"),
        pytest.param(0x50000, 0x0, id="whole-50000-kind0"),
        pytest.param(0x50000, 0x1, id="whole-50000-kind1"),
        pytest.param(0x50000, 0x3, id="whole-50000-kind3"),
        pytest.param(0x54CCC, 0x0, id="whole-54ccc-kind0"),
        pytest.param(0x54CCC, 0x1, id="whole-54ccc-kind1"),
        pytest.param(0x54CCC, 0x3, id="whole-54ccc-kind3"),
        pytest.param(0x92147, 0x0, id="whole-92147-kind0"),
        pytest.param(0x92147, 0x1, id="whole-92147-kind1"),
        pytest.param(0x92147, 0x3, id="whole-92147-kind3"),
        pytest.param(0x93851, 0x0, id="whole-93851-kind0"),
        pytest.param(0x93851, 0x1, id="whole-93851-kind1"),
        pytest.param(0x93851, 0x3, id="whole-93851-kind3"),
        pytest.param(0xA051E, 0x0, id="whole-a051e-kind0"),
        pytest.param(0xA051E, 0x1, id="whole-a051e-kind1"),
        pytest.param(0xA051E, 0x3, id="whole-a051e-kind3"),
        pytest.param(0xC547A, 0x0, id="whole-c547a-kind0"),
        pytest.param(0xC547A, 0x1, id="whole-c547a-kind1"),
        pytest.param(0xC547A, 0x3, id="whole-c547a-kind3"),
        pytest.param(0xC8000, 0x0, id="whole-c8000-kind0"),
        pytest.param(0xC8000, 0x1, id="whole-c8000-kind1"),
        pytest.param(0xC8000, 0x3, id="whole-c8000-kind3"),
        pytest.param(0xD0CCC, 0x0, id="whole-d0ccc-kind0"),
        pytest.param(0xD0CCC, 0x1, id="whole-d0ccc-kind1"),
        pytest.param(0xD0CCC, 0x3, id="whole-d0ccc-kind3"),
        pytest.param(0xD11EB, 0x0, id="whole-d11eb-kind0"),
        pytest.param(0xD11EB, 0x1, id="whole-d11eb-kind1"),
        pytest.param(0xD11EB, 0x3, id="whole-d11eb-kind3"),
        pytest.param(0x194CCC, 0x0, id="whole-194ccc-kind0"),
        pytest.param(0x194CCC, 0x1, id="whole-194ccc-kind1"),
        pytest.param(0x194CCC, 0x3, id="whole-194ccc-kind3"),
        pytest.param(0x328000, 0x0, id="whole-328000-kind0"),
        pytest.param(0x328000, 0x1, id="whole-328000-kind1"),
        pytest.param(0x328000, 0x3, id="whole-328000-kind3"),
        pytest.param(0x434CCD, 0x0, id="whole-434ccd-kind0"),
        pytest.param(0x434CCD, 0x1, id="whole-434ccd-kind1"),
        pytest.param(0x434CCD, 0x3, id="whole-434ccd-kind3"),
        pytest.param(0x449999, 0x0, id="whole-449999-kind0"),
        pytest.param(0x449999, 0x1, id="whole-449999-kind1"),
        pytest.param(0x449999, 0x3, id="whole-449999-kind3"),
        pytest.param(0x44CCCD, 0x0, id="whole-44cccd-kind0"),
        pytest.param(0x44CCCD, 0x1, id="whole-44cccd-kind1"),
        pytest.param(0x44CCCD, 0x3, id="whole-44cccd-kind3"),
        pytest.param(0x44E666, 0x0, id="whole-44e666-kind0"),
        pytest.param(0x44E666, 0x1, id="whole-44e666-kind1"),
        pytest.param(0x44E666, 0x3, id="whole-44e666-kind3"),
    ],
)
def test_complete_saved_derived_player_versions(version, kind):
    c = Carrier(version, kind)
    c.values[c.frame + 0x88] = 0  # Explicit saved AI-present flag for kind3.
    returned = c.whole(bound=bool(kind & 1), seed=0xA3)
    assert returned == c.s and c.get(c.s, 8) == 0x1432F2128
    assert c.get(c.s + 0x10, 4) == kind
    assert c.get(c.out + 24, 8) == 0 and not c.locals
    assert next(call for call in c.calls if call[0] == 0x141713F70)[1] == [
        c.s,
        c.out,
        c.stream,
        c.world,
        c.frame + 0x88,
    ]


def test_nonnull_ai_name_index_actual_sixargs():
    c = Carrier(kind=3)
    c.values[c.frame + 0x88] = 1
    c.values[c.frame + 0x78] = 1
    c.whole()
    assert any(row[0] == 0x140C7EBE0 for row in c.calls)
    assert any(row[0] == 0x1416DFCA0 for row in c.calls)
    assert any(row[0] == 0x141603CB0 for row in c.calls)


def test_initial_input_abi_width_and_order():
    c = Carrier(version=0)
    with c.phase() as state:
        state.initial(c.world, 0x40000)
    assert c.inputs == [[c.s + 0x6DC, 4], [c.s + 0x710, 4], [c.s + 0x6D8, 4], [c.s + 0x714, 4]]
    assert c.typed[0] == [0x1415E5830, 0xC2, 0x1432E9944, c.frame + 0x88, 4]


@pytest.mark.parametrize(
    "target",
    [
        pytest.param(0x141713F70, id="required-child-141713f70"),
        pytest.param(0x14148D110, id="required-child-14148d110"),
        pytest.param(0x14162D370, id="required-child-14162d370"),
        pytest.param(0x14149D9A0, id="required-child-14149d9a0"),
        pytest.param(0x1416C2180, id="required-child-1416c2180"),
        pytest.param(0x14134B780, id="required-child-14134b780"),
        pytest.param(0x140F92850, id="required-child-140f92850"),
    ],
)
def test_required_children_refuse(target):
    c = Carrier()
    c.refuse = target
    refusal(c.whole, f"missing{target:x}")
    assert not c.locals


def test_first_marker_error():
    c = Carrier()
    c.statuses["marker", 1] = 5
    assert c.whole() == c.s and not c.inputs and c.get(c.out + 24, 8) == 5
    assert c.calls[-1][0] == 0x1402BD7F0


def test_type_error_before_publication():
    c = Carrier()
    c.statuses["typed", 1] = 7
    assert c.whole() == c.s and c.get(c.s + 0x10, 4) == 0xA3A3A3A3


def test_nine_positive_names():
    c = Carrier()
    c.values[c.frame + 0x78] = 3
    c.whole()
    for index in range(9):
        assert [c.s + 0xDB8 + 0x80 * index, 3] in c.inputs
        assert c.get(c.s + 0xDB8 + 0x80 * index + 3, 1) == 0


def test_name_terminator_current_after_cleanup():
    c = Carrier()
    with c.phase() as state:
        c.values[c.frame + 0x78] = 3
        c.values[c.s + 0xDB8] = 0xFFFFFF
        c.put(c.frame + 0x88, 4, 0)

        def changed_length(args):
            assert args[0] == c.frame + 0x50
            if c.inputs and c.inputs[-1] == [c.s + 0xDB8, 3]:
                c.put(c.frame + 0x78, 1, 2)
            return release_replay_base_saved_pair_control(
                c.context, *args, calls=c.effects, atomics=c.atomics
            )

        c.extra[0x1408EE150] = changed_length
        state.records()
        assert c.get(c.s + 0xDB8 + 2, 1) == 0
        assert c.get(c.s + 0xDB8 + 1, 1) == 0xFF
        assert [c.s + 0xDB8, 3] in c.inputs


def test_raw_byte_name_length_no_clamp():
    c = Carrier()
    with c.phase() as state:
        c.values[c.frame + 0x78] = 255
        state.records()
        assert [c.s + 0xDB8 + 8 * 0x80, 255] in c.inputs
        assert c.get(c.s + 0xDB8 + 8 * 0x80 + 255, 1) == 0


def test_held_version_skipped_edge():
    c = Carrier()
    with c.phase() as state:
        c.put(c.frame + 0x88, 4, 0)
        c.put(0x1440A0D94, 4, 0xD0000)
        changed = [False]

        def held_version(kind, address, width, value):
            if not changed[0] and kind == "read" and address == 0x1440A0D94:
                changed[0] = True
                c.put(address, 4, 0x44E666)

        c.hook = held_version
        state.kind_and_ai()
        assert [row[3] for row in c.typed] == [c.s + 0x12F8]


def test_inherited_status_no_immediate_check():
    c = Carrier()
    original_base = c.effect

    def inherited_error(args):
        del c.extra[0x141713F70]
        result = original_base(0x141713F70, args, None)
        c.put(c.out + 24, 8, 9)
        return result

    c.extra[0x141713F70] = inherited_error
    c.whole()
    assert c.inputs and c.get(c.out + 24, 8) == 0


def test_global_game_world_count_is_distinct():
    c = Carrier()
    c.world_count = 3
    c.values[c.frame + 0x78] = 1
    c.whole()
    pointer = c.get(c.s + 0x1310, 8)
    assert c.get(pointer, 4) == 7
    assert sum(call[0] == 0x141603EF0 for call in c.calls) == 5


def test_master_current_saved_world_local():
    c = Carrier()
    replacement = 0xC0000
    c.map(replacement, 0x830)
    c.put(replacement + 0x828, 8, 0xFEED)
    count = [0]

    def change_world(kind, address, width, value):
        if kind == "write" and address == c.s + 0x13AE:
            c.put(c.frame + 0x30, 8, replacement)
        if kind == "read" and address == replacement + 0x828:
            count[0] += 1

    c.hook = change_world
    c.whole()
    master = next(args for target, args in c.calls if target == 0x14148D110)
    assert master[3] == 0xFEED and count[0] == 1


def test_protected_zero_preserves_current_highword():
    c = Carrier()
    with c.phase(0xA3) as state:
        c.put(c.s + 0x98, 8, c.stats)
        c.put(c.frame + 0x30, 8, 0x12345678FFFFFFFF)
        state.encode_zero(0x710)
        value = 0x1234567800000000
        value ^= 0xA9834B738A7DD167
        value = (value + 0x042AC42976FCCEF5) & U64
        value ^= 0xC22D6B496D833977
        value ^= 0x6AE24D3352F04511
        assert c.get(c.stats + 0x710, 8) == value
        assert c.get(c.frame + 0x30, 8) == value


def test_manual_loop_source_spill_reload():
    c = Carrier()
    c.map(0xD0000, 48)
    c.map(0xD1000, 48)
    c.put(0xD0000 + 24, 8, 1)
    c.put(0xD1000 + 24, 8, 2)
    with c.phase() as state:

        def replace_source(args):
            assign_replay_saved_pair(c.context, *args, calls=c.effects, atomics=c.atomics)
            c.put(c.frame + 0x30, 8, 0xD1000)
            return args[0]

        c.extra[0x14090D270] = replace_source
        state.adopt(0xD0000, spill_source=True)
        assert [0x1402B9080, [c.out, 0, 0]] in c.calls
        assert c.get(0xD0000 + 40, 1) == 1 and c.get(c.out + 24, 8) == 1
        reads = [event[1] for event in c.events if event[0] == "read"]
        assert 0xD1000 in reads and 0xD0000 not in reads


def test_held_control_spill_and_xadd_r12():
    c = Carrier()
    for control, table in ((0xE0000, 0xE1000), (0xE2000, 0xE3000)):
        c.map(control, 16)
        c.map(table, 16)
        c.put(control, 8, table)
        c.put(control + 8, 4, 1)
        c.put(control + 12, 4, 7)
        c.put(table, 8, 0xDD10)
        c.put(table + 8, 8, 0xDD20)
    with c.phase() as state:
        c.put(c.frame + 0x58, 8, 0xE0000)
        c.extra[0xDD10] = lambda _: c.put(c.frame + 0x30, 8, 0xE2000)
        state.cleanup(0x38, spill_control=True, weak_capture=True)
        assert c.get(0xE000C, 4) == 7 and c.get(0xE200C, 4) == 6
        assert state.decrement == 7


def test_final_positive_vector_current_row_held_end():
    c = Carrier()
    rows_pointer = 0xD0000
    old_table, new_table = 0xD1000, 0xD2000
    master = 0xD3000
    for pointer, width in ((rows_pointer, 40), (old_table, 0x300), (new_table, 0x300), (master, 8)):
        c.map(pointer, width)
    c.put(c.s + 0x6A8, 8, 0xB0000)
    c.put(c.s + 0x6D0, 8, master)
    c.put(master, 8, old_table)
    c.put(rows_pointer + 4, 4, 101)
    c.put(rows_pointer + 8, 2, 33)
    c.put(rows_pointer + 20, 4, 2)
    c.put(new_table + 0x98 + 0x6C, 2, 0xFFFF)
    c.put(new_table + 2 * 0x98 + 0x18, 8, 1)
    c.put(new_table + 2 * 0x98 + 0x6C, 2, 4)

    def final_collection(args):
        assert args[0] == 0xB0100
        for offset, value in ((0, rows_pointer), (8, rows_pointer + 40), (16, rows_pointer + 40)):
            c.put(args[1] + offset, 8, value)

    def current_row_and_table(args):
        assert args == (101,)
        c.put(rows_pointer, 4, 1)
        c.put(master, 8, new_table)
        c.put(c.frame + 0xC8, 8, 0)  # Held end must stillvisit second row.
        return 0xC0FFEE

    c.extra[0x140F92850] = final_collection
    c.extra[0x140803E30] = current_row_and_table
    c.extra[0x140A15BF0] = lambda _: None  # Explicit descriptor-assignment observer fixture.
    with c.phase() as state:
        state.final_records()
    assert [0x140A15BF0, [new_table + 0x98 + 0x10, 0xC0FFEE]] in c.calls
    assert c.get(new_table + 0x98 + 0x6C, 2) == 33
    assert c.get(new_table + 2 * 0x98 + 0x6C, 2) == 4
    assert c.calls[-1] == [0x1402A8790, [rows_pointer, 40]]


def test_final_status_still_releases_current_vector():
    rows_pointer, new_table, master = 0xD0000, 0xD2000, 0xD3000
    c = Carrier()
    c.map(rows_pointer, 20)
    c.map(new_table, 0x98)
    c.map(master, 8)
    c.put(master, 8, new_table)
    c.put(c.s + 0x6A8, 8, 0xB0000)
    c.put(c.s + 0x6D0, 8, master)
    c.put(new_table + 0x18, 8, 1)
    c.put(new_table + 0x6C, 2, 1)
    c.extra[0x140F92850] = lambda args: [
        c.put(args[1] + offset, 8, value)
        for offset, value in ((0, rows_pointer), (8, rows_pointer + 20), (16, rows_pointer + 20))
    ]
    c.statuses["typed", 1] = 9
    with c.phase() as state:
        try:
            state.final_records()
        except PORT._ReturnedStatus:
            pass
        else:
            raise AssertionError("expected final returned status")
    assert c.calls[-1] == [0x1402A8790, [rows_pointer, 20]]
    assert c.get(c.out + 24, 8) == 9


@pytest.mark.parametrize(
    "status_site",
    [
        pytest.param(0x1, id="input-error-1"),
        pytest.param(0x2, id="input-error-2"),
        pytest.param(0x4, id="input-error-4"),
        pytest.param(0x5, id="input-error-5"),
        pytest.param(0x14, id="input-error-20"),
    ],
)
def test_input_error_cleanup_and_partial_return(status_site):
    c = Carrier()
    c.statuses["input", status_site] = 11
    c.whole()
    assert c.counter == status_site and c.get(c.out + 24, 8) == 11
    assert not any(target == 0x140F92850 for target, _ in c.calls)


def test_ai_child_failure_keeps_prior_effects():
    c = Carrier(kind=3)
    c.values[c.frame + 0x88] = 1
    c.refuse = 0x140C7EBE0
    refusal(c.whole, "missing140c7ebe0")
    assert not any(target == 0x140A1B220 for target, _ in c.calls)


@pytest.mark.parametrize(
    "size",
    [
        pytest.param(0x58, id="null-allocation-58"),
        pytest.param(0xF8, id="null-allocation-f8"),
        pytest.param(0x48, id="null-allocation-48"),
        pytest.param(0x18, id="null-allocation-18"),
    ],
)
def test_null_allocation_publication(size):
    c = Carrier()
    c.null_sizes.add(size)
    c.whole()
    fields = {0x58: (0x6D0,), 0xF8: (0xD28,), 0x48: (0xD78,), 0x18: (0x12A0, 0x12D8, 0x12A8)}[size]
    assert all(c.get(c.s + field, 8) == 0 for field in fields)


def test_nonnull_flag_null_map_still_required_reader():
    c = Carrier(kind=1)
    c.values[c.s + 0x12E8] = 1
    c.null_sizes.add(0x38)
    c.whole()
    assert next(args for target, args in c.calls if target == 0x141028560)[0] == 0


@pytest.mark.parametrize(
    "length",
    [
        pytest.param(0x0, id="final-vector-reciprocal-0"),
        pytest.param(0x1, id="final-vector-reciprocal-1"),
        pytest.param(0x13, id="final-vector-reciprocal-19"),
        pytest.param(0x14, id="final-vector-reciprocal-20"),
        pytest.param(0x15, id="final-vector-reciprocal-21"),
        pytest.param(-0x1, id="final-vector-reciprocal--1"),
        pytest.param(-0x14, id="final-vector-reciprocal--20"),
        pytest.param(-0x15, id="final-vector-reciprocal--21"),
    ],
)
def test_final_vector_signed_reciprocal(length):
    c = Carrier()
    with c.phase() as state:
        c.put(c.frame + 0xD0, 8, 0x1000 + length & U64)
        state.release_vector(0x1000)
    expected = (abs(length) // 20) * (1 if length >= 0 else -1) * 20 & U64
    assert c.calls[-1] == [0x1402A8790, [0x1000, expected]]


def test_binder_arity_data_and_unknown():
    c = Carrier()
    bound = PORT.bind_replay_saved_derived_player(
        c.context,
        c.effects,
        atomics=c.atomics,
        bind_local=c.binding,
        scratch=bytes(0xD8),
        floating=c.floating,
    )
    refusal(lambda: bound.call(0x1416C2440, (c.s,), None), "malformed")
    refusal(
        lambda: bound.call(0x1416C2440, (c.s, c.out, c.stream, c.world, 0x40000), memoryview(b"x")),
        "malformed",
    )
    refusal(lambda: bound.call(0xDEAD, (), None), "unbound")


def test_frame_width_before_effects():
    c = Carrier()
    refusal(
        lambda: PORT.construct_replay_saved_derived_player(
            c.context,
            c.s,
            c.out,
            c.stream,
            c.world,
            0x40000,
            calls=c.effects,
            atomics=c.atomics,
            bind_local=c.binding,
            scratch=bytes(0xD7),
            floating=c.floating,
        ),
        "D8",
    )
    assert not c.events
