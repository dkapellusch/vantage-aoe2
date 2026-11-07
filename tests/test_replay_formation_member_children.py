"""Controls derived from six complete originals, before candidate inspection."""

import struct
from contextlib import contextmanager

import pytest

from vantage.replay_formation_member_children import (
    ReplayFormationMemberChildrenProfile,
    bind_replay_formation_member_children,
)
from vantage.replay_memory import ReplayMemory, ReplayMemoryError
from vantage.replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
)

TAIL, RECOMPUTE, LEADER = 0x140B88AF0, 0x1410D9990, 0x1410DC6B0
REMOVE, RESERVE, MODE = 0x1410F6A50, 0x1410F78E0, 0x141252DA0
WORLD, LOOKUP, CLASSIFY, CHILD = 0x140D6ACC0, 0x141617DB0, 0x1410D95F0, 0x1410F69C0
ALLOC, FREE, CLEAR, DISTANCE = 0x142D6C268, 0x142D6C270, 0x142D6E3B7, 0x14096D4D0
GAME, IDS, COUNTS, MINIMUM = 0x144353698, 0x144376530, 0x144376600, 0x1436A030C
K1, K2 = 0x6A586EB28AC201FC, 0x0CF19788B2554E70
K3, K4 = 0x349E37847AD69F19, 0x47E37DFF0616CE4F
U32, U64 = (1 << 32) - 1, (1 << 64) - 1
VIRTUAL_MODE, VIRTUAL_POSITION = 0xA100, 0xA200


def f32(value):
    return int.from_bytes(struct.pack("<f", value), "little")


class Rig:
    def __init__(self):
        self.memory = ReplayMemory()
        self.events, self.locals, self.allocations = [], [], []
        self.after_read, self.after_write, self.after_free = None, None, None
        self.fail_alloc = False
        self.game, self.world = self.alloc(8), self.alloc(8)
        self.units, self.handlers = {}, {}
        self.memory.map_bytes(GAME, self.game.to_bytes(8, "little"))
        self.memory.map_bytes(IDS, b"\x7a" * 0xD0)
        self.memory.map_bytes(COUNTS, b"\xa6" * 0xD0)
        self.memory.map_bytes(MINIMUM, f32(1e30).to_bytes(4, "little"))
        runtime = self.memory.runtime_calls()

        def read(address, width):
            self.events.append(("read", address, width))
            value = self.memory.read(address, width)
            if self.after_read:
                self.after_read(address, width)
            return value

        def write(address, width, value):
            self.events.append(("write", address, width, value))
            self.memory.write(address, width, value)
            if self.after_write:
                self.after_write(address, width, value)

        def call(target, args, data):
            self.events.append(("call", target, args, data))
            if target in self.handlers:
                return self.handlers[target](args, data)
            assert data is None
            if target == WORLD:
                return self.world
            if target == LOOKUP:
                return self.units.get(args[1], 0)
            if target == CLEAR:
                return runtime.call(target, args, data)
            if target == ALLOC:
                if self.fail_alloc:
                    return 0
                address = self.memory.allocate(args[0])
                self.allocations.append((address, args[0]))
                return address
            if target == FREE:
                if self.after_free:
                    self.after_free(args[0])
                self.memory.free(args[0])
                return None
            raise UnresolvedReplayTaskRebuild(f"authored child {target:x} unavailable")

        self.storage = ReplayTaskRebuildStorage(1, read, write)
        self.calls = ReplayTaskRebuildCalls(call)
        self.profile = ReplayFormationMemberChildrenProfile(
            b"\xb1" * 0x58,
            b"\xc2" * 0x40,
            b"\xd3" * 0x48,
        )
        self.bound = bind_replay_formation_member_children(
            self.storage,
            self.calls,
            bind_local=self.local,
            profile=self.profile,
            mxcsr=0x1F80,
        )

    def alloc(self, size, byte=0):
        address = self.memory.allocate(size)
        self.memory.write_bytes(address, bytes([byte]) * size)
        return address

    def put(self, address, width, value):
        self.memory.write(address, width, value & ((1 << (width * 8)) - 1))

    def get(self, address, width=4):
        return self.memory.read(address, width)

    @contextmanager
    def local(self, view):
        with self.memory.bind_local(view) as address:
            self.locals.append((address, len(view), memoryview(view)))
            yield address

    def invoke(self, target, *args):
        return self.bound.call(target, args, None)

    def calls_to(self, target):
        return [event[2] for event in self.events if event[0] == "call" and event[1] == target]

    def node(self, members=(), *, capacity=None):
        capacity = len(members) if capacity is None else capacity
        node = self.alloc(0x1C8)
        array = self.alloc(max(1, capacity, len(members)) * 4, 0xE4)
        for offset, width, value in [
            (0x14, 4, len(members)),
            (0x18, 4, capacity),
            (0x20, 8, array),
        ]:
            self.put(node + offset, width, value)
        for index, ident in enumerate(members):
            self.put(array + index * 4, 4, ident)
        return node, array

    def unit(self, ident, kind=1):
        unit, master, vptr = self.alloc(0x240), self.alloc(0x90), self.alloc(0x570)
        self.put(unit, 8, vptr)
        self.put(unit + 8, 4, ident)
        self.put(unit + 0x10, 8, master + K1 + K2)
        self.put(master + 0x18, 8, ((kind & U64) + K4 & U64) ^ K3)
        for offset in (0x78, 0x7C, 0x80):
            self.put(master + offset, 4, f32(1.0))
        self.put(vptr + 0x220, 8, VIRTUAL_MODE)
        self.put(vptr + 0x568, 8, VIRTUAL_POSITION)
        self.units[ident] = unit
        return unit, master

    def group(self, members):
        group, array = self.alloc(0x400), self.alloc(max(1, len(members)) * 4)
        self.put(group + 0xE4, 4, len(members))
        self.put(group + 0xF0, 8, array)
        for index, ident in enumerate(members):
            self.put(array + index * 4, 4, ident)
        return group


@pytest.mark.parametrize("value", [0, 1, 1 << 63, U64])
def test_descriptor_leaf_returns_actual_qword_and_null_inner_skips_dereference(value):
    rig = Rig()
    receiver, inner = rig.alloc(0x18), rig.alloc(8)
    rig.put(receiver + 0x10, 8, inner)
    rig.put(inner, 8, value)
    assert rig.invoke(TAIL, receiver) == value
    assert rig.events == [("read", receiver + 0x10, 8), ("read", inner, 8)]
    rig.events.clear()
    rig.put(receiver + 0x10, 8, 0)
    assert rig.invoke(TAIL, receiver) == 0
    assert rig.events == [("read", receiver + 0x10, 8)]
    assert not rig.locals


@pytest.mark.parametrize(
    "mode,expected", [(0, 0), (3, 1), (4, 1), (5, 0), (U32, 0), ((1 << 32) | 3, 1)]
)
def test_modes_without_data_do_not_touch_unbacked_receiver_or_scratch(mode, expected):
    rig = Rig()
    assert rig.invoke(MODE, 0xDEADBEEF, mode) == expected
    assert not rig.events and not rig.locals


@pytest.mark.parametrize(
    "word,expected",
    [
        (0, 1),
        (1 << 31, 1),
        (f32(1.0), 0),
        (f32(-1.0), 0),
        (0x7FC00123, 0),
        (0x7F800001, 0),
        (0x7F800000, 0),
    ],
)
def test_mode_two_consumes_raw_xmm_word_and_accepts_only_ordered_zero(word, expected):
    rig = Rig()
    unit, _ = rig.unit(7)
    rig.handlers[VIRTUAL_MODE] = lambda args, data: word
    assert rig.invoke(MODE, unit, 2) == expected
    assert rig.calls_to(VIRTUAL_MODE) == [(unit,)]
    assert not rig.locals


@pytest.mark.parametrize("offset", [0x80, 0x78, 0x7C])
@pytest.mark.parametrize(
    "word,expected", [(f32(2.0), 1), (0, 0), (1 << 31, 0), (f32(-1.0), 0), (0x7FC01234, 1)]
)
def test_mode_one_keeps_literal_ordered_and_unordered_comiss_branches(offset, word, expected):
    rig = Rig()
    unit, master = rig.unit(7)
    rig.put(master + offset, 4, word)
    assert rig.invoke(MODE, unit, 1) == expected
    assert [size for _, size, _ in rig.locals] == [0x48]


def test_mode_one_decodes_current_pointer_three_times_through_live_spill():
    rig = Rig()
    unit, first = rig.unit(7)
    _, second = rig.unit(8)
    _, third = rig.unit(9)
    rig.put(first + 0x78, 4, 0)
    rig.put(second + 0x7C, 4, 0)
    reads = 0

    def mutate(address, width):
        nonlocal reads
        if address == unit + 0x10:
            reads += 1
            rig.put(address, 8, (second if reads == 1 else third) + K1 + K2)

    rig.after_read = mutate
    assert rig.invoke(MODE, unit, 1) == 1
    assert reads == 3
    _, _, view = rig.locals[0]
    assert int.from_bytes(view[0x40:0x48], "little") == third


@pytest.mark.parametrize("requested,capacity", [(0, 0), (U32, 0), (0x80000000, 0), (3, 3), (2, 4)])
def test_node_reserve_signed_guards_precede_allocator(requested, capacity):
    rig = Rig()
    node, array = rig.node(capacity=capacity)
    assert rig.invoke(RESERVE, node, requested) == 0
    assert not rig.calls_to(ALLOC) and not rig.calls_to(FREE)
    assert rig.get(node + 0x20, 8) == array


@pytest.mark.parametrize("old_capacity", [0, 1, 3])
def test_node_reserve_fills_only_old_capacity_and_leaves_new_tail_undefined(old_capacity):
    rig = Rig()
    node, old = rig.node(capacity=old_capacity)
    assert rig.invoke(RESERVE, node, 5) == 1
    new = rig.get(node + 0x20, 8)
    assert rig.calls_to(ALLOC) == [(20,)] and rig.calls_to(FREE) == [(old,)]
    assert rig.get(node + 0x18) == 5 and rig.get(node + 0x14) == 0
    if old_capacity:
        assert rig.memory.read_bytes(new, old_capacity * 4) == b"\xff" * (old_capacity * 4)
    with pytest.raises(ReplayMemoryError):
        rig.get(new + old_capacity * 4)


def test_node_reserve_rereads_source_each_copy_and_current_capacity_after_free():
    rig = Rig()
    node, old = rig.node([10, 20], capacity=2)
    replacement = rig.alloc(8)
    rig.put(replacement, 4, 30)
    rig.put(replacement + 4, 4, 40)

    def mutate(address, width):
        if address == old:
            rig.put(node + 0x20, 8, replacement)

    def free(pointer):
        assert pointer == replacement
        rig.put(node + 0x18, 4, 4)

    rig.after_read, rig.after_free = mutate, free
    assert rig.invoke(RESERVE, node, (1 << 32) | 5) == 1
    new = rig.get(node + 0x20, 8)
    assert [rig.get(new + 4 * i) for i in range(4)] == [10, 40, U32, U32]
    with pytest.raises(ReplayMemoryError):
        rig.get(new + 16)
    assert rig.get(node + 0x18) == 5 and rig.get(node + 0x14) == 2
    assert rig.calls_to(FREE) == [(replacement,)]


def test_node_reserve_null_allocation_preserves_header_and_never_frees():
    rig = Rig()
    node, old = rig.node([9], capacity=1)
    rig.fail_alloc = True
    assert rig.invoke(RESERVE, node, 4) == 0
    assert rig.get(node + 0x20, 8) == old
    assert rig.get(node + 0x18) == 1 and not rig.calls_to(FREE)


@pytest.mark.parametrize("count", [0, U32])
def test_empty_recompute_clears_only_counts_copies_stale_ids_and_publishes_zero(count):
    rig = Rig()
    node, _ = rig.node()
    rig.put(node + 0x14, 4, count)
    rig.put(node + 0x20, 8, 0xDEADBEEF)
    rig.put(node + 0x34, 4, 99)
    assert rig.invoke(RECOMPUTE, node) is None
    assert rig.calls_to(CLEAR) == [(COUNTS, 0, 200)]
    assert not rig.calls_to(LOOKUP)
    assert rig.memory.read_bytes(node + 0x38, 200) == b"\x7a" * 200
    assert rig.memory.read_bytes(node + 0x100, 200) == bytes(200)
    assert rig.memory.read_bytes(IDS, 200) == b"\x7a" * 200
    assert rig.get(node + 0x34) == 0


def test_recompute_signed_word_keys_duplicates_and_null_members():
    rig = Rig()
    rig.unit(1, -2)
    rig.unit(2, -2)
    rig.unit(3, 7)
    node, _ = rig.node([1, 99, 2, 3])
    assert rig.invoke(RECOMPUTE, node) is None
    assert rig.get(node + 0x34) == 2
    assert [rig.get(node + 0x38 + 4 * i) for i in range(3)] == [0xFFFFFFFE, 7, 0x7A7A7A7A]
    assert [rig.get(node + 0x100 + 4 * i) for i in range(3)] == [2, 1, 0]
    assert [args[1] for args in rig.calls_to(LOOKUP)] == [1, 99, 2, 3]
    assert [size for _, size, _ in rig.locals] == [0x58]


@pytest.mark.parametrize("members,unique", [(50, 50), (51, 51), (52, 51)])
def test_recompute_inserts_fifty_first_entry_before_stopping_but_copies_fifty(members, unique):
    rig = Rig()
    for ident in range(1, members + 1):
        rig.unit(ident, ident)
    node, _ = rig.node(range(1, members + 1))
    rig.invoke(RECOMPUTE, node)
    assert rig.get(node + 0x34) == unique
    assert len(rig.calls_to(LOOKUP)) == unique
    assert rig.get(node + 0x38 + 49 * 4) == 50
    assert rig.get(node + 0x100 + 49 * 4) == 1
    if unique == 51:
        assert rig.get(IDS + 200) == 51 and rig.get(COUNTS + 200) == 1


def test_recompute_decodes_again_for_each_comparison_and_new_insertion():
    rig = Rig()
    _, a = rig.unit(1, 10)
    _, b = rig.unit(2, 20)
    third, _ = rig.unit(3, 20)
    node, _ = rig.node([1, 2, 3])
    rig.put(third + 0x10, 8, b + K1 + K2)

    def mutate(address, width):
        if address == third + 0x10:
            rig.put(address, 8, a + K1 + K2)

    rig.after_read = mutate
    rig.invoke(RECOMPUTE, node)
    assert rig.get(node + 0x34) == 3
    assert [rig.get(node + 0x38 + i * 4) for i in range(3)] == [10, 20, 10]
    assert [rig.get(node + 0x100 + i * 4) for i in range(3)] == [1, 1, 1]


def test_leader_uses_virtual_returned_pointer_and_strict_ordered_improvement():
    rig = Rig()
    for ident in (1, 2, 3, 4):
        rig.unit(ident)
    group = rig.group([1, 2, 3, 4])
    vectors = {
        1: (3.0, 0.0, 0.0),
        2: (1.0, 0.0, 0.0),
        3: (1.0, 0.0, 0.0),
        4: (float("nan"), 0.0, 0.0),
    }
    points = {}
    for ident, values in vectors.items():
        point = rig.alloc(16)
        for i, value in enumerate(values):
            rig.put(point + i * 4, 4, f32(value))
        points[rig.units[ident]] = point

    def position(args, data):
        unit, home = args
        rig.memory.write_bytes(home, b"\xcc" * 16)
        return points[unit]

    def difference(args, data):
        source, output, reference = args
        assert source in points.values() and reference == group + 0x3D0
        rig.memory.write_bytes(output, rig.memory.read_bytes(source, 12))
        return None

    rig.handlers[VIRTUAL_POSITION], rig.handlers[DISTANCE] = position, difference
    assert rig.invoke(LEADER, group) is None
    assert rig.get(group + 0xC4) == 2
    assert [size for _, size, _ in rig.locals] == [0x40]
    assert len(rig.calls_to(DISTANCE)) == 4
    writes = [e[3] for e in rig.events if e[:3] == ("write", group + 0xC4, 4)]
    assert writes == [U32, 1, 2]


@pytest.mark.parametrize("count", [0, U32])
def test_leader_resets_before_signed_count_gate_without_looking_up_members(count):
    rig = Rig()
    group = rig.group([])
    rig.put(group + 0xE4, 4, count)
    rig.put(group + 0xC4, 4, 123)
    rig.invoke(LEADER, group)
    assert rig.get(group + 0xC4) == U32 and not rig.calls_to(LOOKUP)


def test_leader_reached_missing_virtual_refuses_after_initial_reset():
    rig = Rig()
    rig.unit(1)
    group = rig.group([1])
    with pytest.raises(UnresolvedReplayTaskRebuild, match="a200"):
        rig.invoke(LEADER, group)
    assert rig.get(group + 0xC4) == U32


def test_null_unit_removal_shifts_first_match_then_runs_actual_recompute():
    rig = Rig()
    manager = rig.alloc(0x10)
    node, ids = rig.node([5, 6, 5])
    rig.put(manager + 8, 8, node)
    rig.put(node, 8, manager + 8)
    assert rig.invoke(REMOVE, manager, 0xABC000, 5, 99) == 1
    assert [rig.get(ids + i * 4) for i in range(3)] == [6, 5, U32]
    assert rig.get(node + 0x14) == 2 and rig.get(node + 0x34) == 0
    assert rig.calls_to(CLEAR) == [(COUNTS, 0, 200)]


@pytest.mark.parametrize("result", [0, 1, (1 << 63) | 7, None])
def test_classified_removal_forwards_opaque_child_result_and_held_arguments(result):
    rig = Rig()
    unit, _ = rig.unit(5)
    peer, _ = rig.unit(99)
    manager, node = rig.alloc(0x10), rig.alloc(0x28)
    rig.put(manager + 8, 8, node)
    rig.put(node, 8, manager + 8)
    rig.put(node + 0x10, 4, 7)
    rig.handlers[CLASSIFY] = lambda args, data: 7
    rig.handlers[CHILD] = lambda args, data: result
    group = 0xABCDEF0000000B00
    assert rig.invoke(REMOVE, manager, group, (3 << 32) | 5, (2 << 32) | 99) == result
    assert rig.calls_to(CLASSIFY) == [(unit, peer)]
    assert rig.calls_to(CHILD) == [(node, group, 5)]
    assert not rig.calls_to(CLEAR)


def test_classification_minus_one_skips_unbacked_list_and_unknown_calls_delegate_identity():
    rig = Rig()
    rig.unit(5)
    rig.handlers[CLASSIFY] = lambda args, data: U32
    assert rig.invoke(REMOVE, 0xDEADBEEF, 0xAB00, 5, 99) == 0
    seen, args, payload = [], (1, 2), memoryview(bytearray(b"xyz"))

    def unknown(actual_args, data):
        seen.append((actual_args, data))
        return 0xFEDCBA9876543210

    rig.handlers[0xABCD] = unknown
    assert rig.bound.call(0xABCD, args, payload) == 0xFEDCBA9876543210
    assert seen[0][0] is args and seen[0][1] is payload


@pytest.mark.parametrize(
    "target,args",
    [
        (TAIL, (True,)),
        (MODE, (1,)),
        (RESERVE, (1, -1)),
        (REMOVE, (1, 2, 3)),
        (RECOMPUTE, (1 << 64,)),
    ],
)
def test_known_malformed_calls_refuse_before_storage(target, args):
    rig = Rig()
    with pytest.raises(ValueError):
        rig.bound.call(target, args, None)
    assert not rig.events and not rig.locals
