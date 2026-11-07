"""Original-source membership controls; CRT/child effects are authored here."""

from contextlib import contextmanager

import pytest

from vantage.replay_formation_membership import (
    ReplayFormationMembershipProfile,
    bind_replay_formation_membership,
)
from vantage.replay_memory import ReplayMemory
from vantage.replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
)

RESERVE, REMOVE, APPEND = 0x1410F7C20, 0x1410F6800, 0x1410D43A0
GET_WORLD, LOOKUP, EXTENT = 0x140D6ACC0, 0x141617DB0, 0x1410EEF50
ALLOC, FREE = 0x142D6C268, 0x142D6C270
AUX_REMOVE, LEADER, GROW, RECOMPUTE = 0x1410F6A50, 0x1410DC6B0, 0x1410F78E0, 0x1410D9990
U32 = 0xFFFFFFFF
EMPTY_ROW = bytes(4) + b"\xff" * 8 + bytes(36)


class Rig:
    def __init__(self):
        self.memory = ReplayMemory()
        self.events, self.locals, self.active, self.allocations = [], [], [], []
        self.after_read, self.after_write = None, None
        self.after_alloc, self.after_free = None, None
        self.alloc_attempt, self.fail_alloc = 0, None
        self.world, self.game = self.alloc(1), self.alloc(1)
        self.memory.map_bytes(0x144353698, self.game.to_bytes(8, "little"))
        self.units = {}
        self.handlers = {
            GET_WORLD: lambda args: self.world,
            LOOKUP: lambda args: self.units.get(args[1], 0),
            AUX_REMOVE: lambda args: None,
            LEADER: lambda args: None,
            RECOMPUTE: lambda args: None,
        }

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
            assert data is None
            if target == ALLOC:
                self.alloc_attempt += 1
                if self.alloc_attempt == self.fail_alloc:
                    return 0
                address = self.alloc(args[0], 0xCD)
                self.allocations.append((address, args[0]))
                if self.after_alloc:
                    self.after_alloc(address, args[0])
                return address
            if target == FREE:
                if self.after_free:
                    self.after_free(args[0])
                return None  # Authored service records the call; no native-free claim.
            if target not in self.handlers:
                raise UnresolvedReplayTaskRebuild(f"authored child {target:x} absent")
            return self.handlers[target](args)

        self.storage = ReplayTaskRebuildStorage(1, read, write)
        self.calls = ReplayTaskRebuildCalls(call)
        self.profile = ReplayFormationMembershipProfile(b"\xc8" * 0xA0)
        self.bound = bind_replay_formation_membership(
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
            self.locals.append((address, len(view), view))
            self.active.append(address)
            try:
                yield address
            finally:
                self.active.remove(address)

    def invoke(self, target, *args):
        return self.bound.call(target, args, None)

    def calls_to(self, target):
        return [e[2] for e in self.events if e[0] == "call" and e[1] == target]

    def group(self, members=(), *, capacity=None):
        capacity = len(members) if capacity is None else capacity
        group = self.alloc(0x498)
        ids, rows, floats = (self.alloc(max(1, capacity) * size, 0xA5) for size in (4, 48, 4))
        for offset, width, value in (
            (0xD8, 4, 7),
            (0xC4, 4, U32),
            (0xE4, 4, len(members)),
            (0xE8, 4, capacity),
            (0xF0, 8, ids),
            (0xF8, 8, rows),
            (0x490, 8, floats),
            (0x140, 4, 0x80),
        ):
            self.put(group + offset, width, value)
        for i, ident in enumerate(members):
            self.put(ids + i * 4, 4, ident)
            self.memory.write_bytes(rows + i * 48, bytes([0x10 + i]) * 48)
            self.put(floats + i * 4, 4, 0x3F800000 + i)
        return group, ids, rows, floats

    def unit(self, ident, group_id=7):
        unit, vptr = self.alloc(0x214), self.alloc(0x5B0)
        self.put(unit, 8, vptr)
        self.put(vptr + 0x5A8, 8, 0xA11)
        self.put(unit + 0x210, 4, group_id)
        self.units[ident] = unit
        self.handlers[0xA11] = lambda args: None
        return unit


@pytest.mark.parametrize("requested,capacity", [(0, 0), (U32, 0), (0x80000000, 0), (3, 3), (2, 4)])
def test_reserve_signed_admission_refuses_before_allocation(requested, capacity):
    rig = Rig()
    group, _, _, _ = rig.group(capacity=capacity)
    assert rig.invoke(RESERVE, group, requested) == 0
    assert rig.calls_to(ALLOC) == [] and rig.calls_to(FREE) == []


@pytest.mark.parametrize("failure", [1, 2, 3])
def test_reserve_each_failure_releases_only_completed_allocations(failure):
    rig = Rig()
    group, _, _, _ = rig.group()
    before = rig.memory.read_bytes(group, 0x498)
    rig.fail_alloc = failure
    assert rig.invoke(RESERVE, group, 3) == 0
    assert rig.calls_to(ALLOC) == [(12,), (144,), (12,)][:failure]
    assert rig.calls_to(FREE) == [(p,) for p, _ in rig.allocations]
    assert rig.memory.read_bytes(group, 0x498) == before
    if failure == 3:
        assert rig.memory.read_bytes(rig.allocations[1][0], 144) == EMPTY_ROW * 3
    assert rig.active == []


@pytest.mark.parametrize("requested", [1, 2, 3, 4, 5, 6])
def test_reserve_null_old_ids_initializes_all_and_skips_other_old_frees(requested):
    rig = Rig()
    group, _, old_rows, old_floats = rig.group()
    rig.put(group + 0xF0, 8, 0)
    assert rig.invoke(RESERVE, group, requested) == 1
    ids, rows, floats = [rig.get(group + offset, 8) for offset in (0xF0, 0xF8, 0x490)]
    assert rig.memory.read_bytes(ids, requested * 4) == b"\xff" * (requested * 4)
    assert rig.memory.read_bytes(rows, requested * 48) == EMPTY_ROW * requested
    assert [rig.get(floats + i * 4) for i in range(requested)] == [0x7F7FFFFF] * requested
    assert rig.calls_to(FREE) == []
    assert rig.get(group + 0xE4) == 0 and rig.get(group + 0xE8) == requested
    assert old_rows != rows and old_floats != floats


@pytest.mark.parametrize("requested,count", [(1, 0), (2, 1), (3, 2), (4, 3), (5, 4), (6, 5)])
def test_reserve_copies_ids_rows_and_parallel_floats_then_initializes_tail(requested, count):
    rig = Rig()
    group, old_ids, old_rows, old_floats = rig.group(tuple(range(10, 10 + count)))
    assert rig.invoke(RESERVE, group, requested) == 1
    ids, rows, floats = [rig.get(group + offset, 8) for offset in (0xF0, 0xF8, 0x490)]
    assert [rig.get(ids + i * 4) for i in range(requested)] == [*range(10, 10 + count), U32]
    assert rig.memory.read_bytes(rows, count * 48) == rig.memory.read_bytes(old_rows, count * 48)
    assert rig.memory.read_bytes(rows + count * 48, 48) == EMPTY_ROW
    assert [rig.get(floats + i * 4) for i in range(requested)] == [
        *range(0x3F800000, 0x3F800000 + count),
        0x7F7FFFFF,
    ]
    assert rig.calls_to(FREE) == [(old_ids,), (old_rows,), (old_floats,)]
    assert rig.get(group + 0xE4) == count


def test_reserve_dynamic_count_gate_is_rechecked_inside_unrolled_copy():
    rig = Rig()
    group, _, _, _ = rig.group((10, 11, 12))

    def hook(address, width, value):
        if rig.allocations and address == rig.allocations[0][0] and width == 4:
            rig.put(group + 0xE4, 4, 1)

    rig.after_write = hook
    assert rig.invoke(RESERVE, group, 4) == 1
    ids = rig.get(group + 0xF0, 8)
    assert [rig.get(ids + i * 4) for i in range(4)] == [10, U32, U32, U32]
    assert rig.get(group + 0xE4) == 1


def test_reserve_free_callbacks_change_current_headers_and_final_saved_request():
    rig = Rig()
    group, old_ids, old_rows, old_floats = rig.group((9,))
    changed_rows, changed_floats = rig.alloc(48), rig.alloc(4)

    def free(pointer):
        assert rig.get(group + 0xF0, 8) in (old_ids, 0)
        if pointer == old_ids:
            rig.put(group + 0xF8, 8, changed_rows)
        elif pointer == changed_rows:
            rig.put(group + 0x490, 8, changed_floats)
        elif pointer == changed_floats:
            rig.put(rig.active[-1] + 0x88, 4, 99)
        else:
            pytest.fail(f"unexpected current free {pointer:x}; old {old_rows:x}/{old_floats:x}")

    rig.after_free = free
    assert rig.invoke(RESERVE, group, 4) == 1
    assert rig.calls_to(FREE) == [(old_ids,), (changed_rows,), (changed_floats,)]
    assert rig.get(group + 0xE8) == 99
    assert [size for _, size in rig.allocations] == [16, 192, 16]
    writes = [e[1] for e in rig.events if e[0] == "write"]
    assert writes[-4:] == [group + 0xF0, group + 0xF8, group + 0x490, group + 0xE8]


@pytest.mark.parametrize("members,ident", [((), 1), ((2, 3), 8)])
def test_removal_miss_never_calls_world_or_virtuals(members, ident):
    rig = Rig()
    group, _, _, _ = rig.group(members)
    assert rig.invoke(REMOVE, group, ident, 7, 0) == 0
    assert not any(e[0] == "call" for e in rig.events)


@pytest.mark.parametrize("flag,virtual_calls", [(0, 1), (1, 0), (0x100, 1), (0x101, 0)])
def test_remove_first_duplicate_compacts_rows_and_preserves_parallel490(flag, virtual_calls):
    rig = Rig()
    group, ids, rows, floats = rig.group((5, 8, 8))
    unit = rig.unit(8)
    rig.put(group + 0xC4, 4, 8)
    before_floats = rig.memory.read_bytes(floats, 12)
    assert rig.invoke(REMOVE, group, 8, 0x12340000CAFE, flag) == 1
    assert [rig.get(ids + i * 4) for i in range(3)] == [5, 8, U32]
    assert rig.memory.read_bytes(rows + 48, 48) == bytes([0x12]) * 48
    assert rig.memory.read_bytes(rows + 96, 48) == EMPTY_ROW
    assert rig.memory.read_bytes(floats, 12) == before_floats
    assert rig.get(group + 0xE4) == 2 and rig.get(unit + 0x210) == U32
    assert len(rig.calls_to(0xA11)) == virtual_calls
    assert rig.calls_to(AUX_REMOVE) == [(group + 0x1D0, group, 8, 0xCAFE)]
    assert rig.calls_to(LEADER) == [(group,)]
    assert rig.get(group + 0x140) == 0x10082
    chunks = [e[:3] for e in rig.events if e[0] in ("read", "write") and e[2] == 16]
    assert chunks == [
        ("read", rows + 96, 16),
        ("write", rows + 48, 16),
        ("read", rows + 112, 16),
        ("write", rows + 64, 16),
        ("read", rows + 128, 16),
        ("write", rows + 80, 16),
    ]


def test_removal_virtual_callback_changes_current_arrays_before_compaction():
    rig = Rig()
    group, _, _, _ = rig.group((1, 2, 3))
    unit = rig.unit(1)
    _, changed_ids, changed_rows, _ = rig.group((11, 12, 13))

    def virtual(args):
        assert args == (unit,)
        rig.put(group + 0xF0, 8, changed_ids)
        rig.put(group + 0xF8, 8, changed_rows)
        rig.put(group + 0xE4, 4, 2)

    rig.handlers[0xA11] = virtual
    assert rig.invoke(REMOVE, group, 1, 0, 0) == 1
    assert [rig.get(changed_ids + i * 4) for i in range(3)] == [12, U32, 13]
    assert rig.memory.read_bytes(changed_rows, 48) == bytes([0x11]) * 48
    assert rig.memory.read_bytes(changed_rows + 48, 48) == EMPTY_ROW
    assert rig.get(group + 0xE4) == 1


def test_removal_auxiliary_refusal_preserves_compacted_prefix_but_not_late_flags():
    rig = Rig()
    group, ids, rows, _ = rig.group((2,))
    del rig.handlers[AUX_REMOVE]
    with pytest.raises(UnresolvedReplayTaskRebuild):
        rig.invoke(REMOVE, group, 2, 0, 1)
    assert rig.get(ids) == U32 and rig.memory.read_bytes(rows, 48) == EMPTY_ROW
    assert rig.get(group + 0xE4) == 0 and rig.get(group + 0x140) == 0x80


def test_node_append_null_lookup_has_no_growth_or_extent():
    rig = Rig()
    assert rig.invoke(APPEND, 0, 9) == 0
    assert [e[1] for e in rig.events if e[0] == "call"] == [GET_WORLD, LOOKUP]


def node(rig, *, count=0, capacity=0, maximum=0):
    pointer, ids = rig.alloc(0x34), rig.alloc(64, 0xAA)
    for offset, width, value in (
        (0x14, 4, count),
        (0x18, 4, capacity),
        (0x20, 8, ids),
        (0x30, 4, maximum),
    ):
        rig.put(pointer + offset, width, value)
    return pointer, ids


@pytest.mark.parametrize("failure", [1, 2])
def test_append_two_step_zero_capacity_stops_at_each_low_eax_refusal(failure):
    rig = Rig()
    pointer, _ = node(rig)
    rig.unit(5)
    count = 0

    def grow(args):
        nonlocal count
        count += 1
        if count == failure:
            return 0x100000000
        rig.put(pointer + 0x18, 4, 6)
        return 1

    rig.handlers[GROW] = grow
    assert rig.invoke(APPEND, pointer, 5) == 0
    assert rig.calls_to(GROW) == [(pointer, 10), (pointer, 12)][:failure]
    assert rig.get(pointer + 0x14) == 0


def test_append_zero_capacity_reads_new_capacity_and_current_array_count_after_extent():
    rig = Rig()
    pointer, first_ids = node(rig)
    new_ids = rig.alloc(64, 0xBB)
    unit = rig.unit(5)

    def grow(args):
        rig.put(pointer + 0x18, 4, 6 if args[1] == 10 else 12)
        return 1

    def extent(args):
        assert args == (unit,)
        rig.put(pointer + 0x20, 8, new_ids)
        rig.put(pointer + 0x14, 4, 2)
        return 0x3FC00000  # 1.5 -> exact ADDSS doubles to3.

    rig.handlers[GROW], rig.handlers[EXTENT] = grow, extent
    assert rig.invoke(APPEND, pointer, 0x123400000005) == 1
    assert rig.calls_to(GROW) == [(pointer, 10), (pointer, 12)]
    assert rig.get(pointer + 0x30) == 0x40400000
    assert rig.get(pointer + 0x14) == 3 and rig.get(new_ids + 8) == 5
    assert rig.memory.read_bytes(first_ids, 64) == b"\xaa" * 64
    assert rig.calls_to(RECOMPUTE) == [(pointer,)]


@pytest.mark.parametrize(
    "extent,maximum,expected",
    [
        (0x3F800000, 0x40000000, 0x40000000),
        (0x7FC12345, 0x3F800000, 0x3F800000),
        (0x7F800000, 0x7F7FFFFF, 0x7F800000),
        (0x80000000, 0, 0),
    ],
)
def test_append_binary32_doubled_extent_uses_ordered_greater_only(extent, maximum, expected):
    rig = Rig()
    pointer, ids = node(rig, capacity=8, maximum=maximum)
    rig.unit(7)
    rig.handlers[EXTENT] = lambda args: extent
    assert rig.invoke(APPEND, pointer, 7) == 1
    assert rig.get(pointer + 0x30) == expected and rig.get(ids) == 7
    assert rig.calls_to(GROW) == []


def test_append_recompute_refusal_retains_publication_and_count():
    rig = Rig()
    pointer, ids = node(rig, capacity=8)
    rig.unit(7)
    rig.handlers[EXTENT] = lambda args: 0x3F800000
    del rig.handlers[RECOMPUTE]
    with pytest.raises(UnresolvedReplayTaskRebuild):
        rig.invoke(APPEND, pointer, 7)
    assert rig.get(ids) == 7 and rig.get(pointer + 0x14) == 1
    assert rig.get(pointer + 0x30) == 0x40000000
