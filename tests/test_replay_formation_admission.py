"""Independent controls from retained original ASM, before candidate code."""

from contextlib import contextmanager

import pytest

from vantage.replay_formation_admission import (
    ReplayFormationAdmissionProfile,
    bind_replay_formation_admission,
    bind_replay_formation_quiet_home_calls,
)
from vantage.replay_memory import ReplayMemory, ReplayMemoryError
from vantage.replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
)

LOOKUP, FIND, TAIL = 0x141617DB0, 0x141604060, 0x141139140
CLASSIFY, EXTENT, PRED = 0x1410D95F0, 0x1410EEF50, 0x141252DA0
GET44, GET3C, SET44, SET3C, RESET = (
    0x140D23D40,
    0x140D23D50,
    0x140D3EA00,
    0x140D3EA10,
    0x140D36E70,
)
DESCRIPTOR, QUIET, PLAYER = 0x140A4B870, 0x140B6EF80, 0x14172AC80
U32, U64 = 0xFFFFFFFF, 0xFFFFFFFFFFFFFFFF
ENCODE = 0x6A586EB28AC201FC + 0x0CF19788B2554E70
TABLE = 0x1410D996C
JUMPS = (0x10D9946, 0x10D992A, 0x10D9931, 0x10D9938, 0x10D993F, 0x10D9946, 0x10D994D)


class Rig:
    def __init__(self):
        self.memory = ReplayMemory()
        self.events, self.locals, self.active = [], [], []
        self.after_read, self.after_write = None, None
        self.handlers, self.tail_handlers = {}, {}

        def read(address, width):
            self.events.append(("read", address, width))
            result = self.memory.read(address, width)
            if self.after_read:
                self.after_read(address, width)
            return result

        def write(address, width, value):
            self.events.append(("write", address, width, value))
            self.memory.write(address, width, value)
            if self.after_write:
                self.after_write(address, width, value)

        def call(target, args, data):
            self.events.append(("call", target, args, data))
            if target not in self.handlers:
                raise UnresolvedReplayTaskRebuild(f"authored child {target:x} absent")
            return self.handlers[target](args, data)

        def tail(target, args, data):
            self.events.append(("tail", target, args, data))
            if target not in self.tail_handlers:
                raise UnresolvedReplayTaskRebuild("required explicit descriptor tail")
            return self.tail_handlers[target](args, data)

        self.storage = ReplayTaskRebuildStorage(1, read, write)
        self.calls, self.tail_calls = ReplayTaskRebuildCalls(call), ReplayTaskRebuildCalls(tail)
        self.profile = ReplayFormationAdmissionProfile(b"\xa6" * 0x38, b"\xb7" * 0x38, True)
        self.bound = bind_replay_formation_admission(
            self.storage,
            self.calls,
            descriptor_tail_calls=self.tail_calls,
            bind_local=self.local,
            profile=self.profile,
            mxcsr=0x1F80,
        )

    def alloc(self, size, byte=0):
        pointer = self.memory.allocate(size)
        self.memory.write_bytes(pointer, bytes([byte]) * size)
        return pointer

    def put(self, address, width, value):
        self.memory.write(address, width, value & ((1 << (8 * width)) - 1))

    def get(self, address, width=4):
        return self.memory.read(address, width)

    @contextmanager
    def local(self, view):
        with self.memory.bind_local(view) as pointer:
            self.locals.append((pointer, len(view), view))
            self.active.append(pointer)
            try:
                yield pointer
            finally:
                self.active.remove(pointer)

    def invoke(self, target, *args):
        return self.bound.call(target, args, None)

    def unit(self, *, kind=0x47, category=3, flags=0):
        unit, master = self.alloc(0x428), self.alloc(0x380)
        self.put(unit + 0x10, 8, master + ENCODE)
        self.put(master + 8, 1, kind)
        self.put(master + 0x35C, 1, category)
        self.put(master + 0x379, 1, flags)
        return unit, master

    def map_table(self):
        self.memory.map_bytes(TABLE, b"".join(x.to_bytes(4, "little") for x in JUMPS))


@pytest.mark.parametrize("ident", [0x80000000, 0x1234567880000000])
def test_int_min_lookup_returns_without_world_reads(ident):
    rig = Rig()
    assert rig.invoke(LOOKUP, 0, ident) == 0
    assert rig.events == []


@pytest.mark.parametrize("ident,index", [(U32, 1), (U32 - 1, 2), (0x12345678FFFFFFFF, 1)])
def test_negative_lookup_can_resolve_minus_one(ident, index):
    rig = Rig()
    world, table = rig.alloc(0x188), rig.alloc(24)
    rig.put(world + 0x184, 4, 3)
    rig.put(world + 0x178, 8, table)
    rig.put(table + index * 8, 8, 0xBADBEEF)
    assert rig.invoke(LOOKUP, world, ident) == 0xBADBEEF
    assert rig.events == [
        ("read", world + 0x184, 4),
        ("read", world + 0x178, 8),
        ("read", table + index * 8, 8),
    ]


def test_negative_table_null_is_a_reached_dereference():
    rig = Rig()
    world = rig.alloc(0x188)
    rig.put(world + 0x184, 4, 4)
    with pytest.raises(ReplayMemoryError):
        rig.invoke(LOOKUP, world, U32)
    assert rig.events[-1] == ("read", 8, 8)


@pytest.mark.parametrize(
    "ident,bound,pointer,expected",
    [
        (0, 2, True, 99),
        (1, 2, True, 100),
        (2, 2, True, 0),
        (0, U32, True, 0),
        (0, 2, False, 0),
        (U32, 1, True, 0),
    ],
)
def test_positive_lookup_bounds_and_null_header(ident, bound, pointer, expected):
    rig = Rig()
    world, table = rig.alloc(0x188), rig.alloc(16)
    rig.put(world + 0x174, 4, bound)
    rig.put(world + 0x168, 8, table if pointer else 0)
    rig.put(table, 8, 99)
    rig.put(table + 8, 8, 100)
    assert rig.invoke(LOOKUP, world, ident) == expected


def test_group_minus_one_does_not_touch_receiver():
    rig = Rig()
    assert rig.invoke(FIND, 0, U32) == 0
    assert rig.events == []


def test_group_lookup_holds_sentinel_and_follows_current_links():
    rig = Rig()
    world, sentinel, first, second = (rig.alloc(0xE0) for _ in range(4))
    rig.put(world + 0x50, 8, sentinel)
    rig.put(sentinel + 0xC8, 8, first)
    rig.put(first + 0xC8, 8, second)
    rig.put(second + 0xC8, 8, sentinel)
    rig.put(first + 0xD8, 4, 3)
    rig.put(second + 0xD8, 4, 5)
    assert rig.invoke(FIND, world, 5) == second
    assert rig.invoke(FIND, world, 7) == 0


def test_descriptor_tail_is_current_and_mandatory_on_distinct_channel():
    rig = Rig()
    unit = rig.alloc(0x428)
    rig.put(unit + 0x420, 8, 0xABCDEF)
    with pytest.raises(UnresolvedReplayTaskRebuild):
        rig.invoke(TAIL, unit)
    rig.tail_handlers[0x140B88AF0] = lambda args, data: 0xFEDCBA9876543210
    assert rig.invoke(TAIL, unit) == 0xFEDCBA9876543210
    assert rig.events[-1] == ("tail", 0x140B88AF0, (0xABCDEF,), None)


def test_leaf_getters_and_ordered_backup():
    rig = Rig()
    ai = rig.alloc(0x70, 0xA5)
    rig.put(ai + 0x44, 4, 0x87654321)
    rig.put(ai + 0x3C, 4, 0xFEDCBA98)
    assert rig.invoke(GET44, ai) == 0x87654321
    assert rig.invoke(GET3C, ai) == 0xFEDCBA98
    rig.events.clear()
    assert rig.invoke(SET44, ai, 0x123400000001) == 0x87654321
    assert rig.events == [
        ("read", ai + 0x44, 4),
        ("write", ai + 0x68, 4, 0x87654321),
        ("write", ai + 0x44, 4, 1),
    ]
    rig.invoke(RESET, ai)
    assert rig.get(ai + 0x18) == 0


@pytest.mark.parametrize("old,new,flag", [(3, 7, 0), (0x2C7, 0x2C7, 1), (0x2DD, 0x2DD, 0)])
def test_type_setter_nonreset_gates(old, new, flag):
    rig = Rig()
    ai = rig.alloc(0x178, 0xAA)
    rig.put(ai + 0x3C, 4, old)
    rig.invoke(SET3C, ai, new, flag)
    assert rig.get(ai + 0x3C) == new
    if flag:
        assert rig.get(ai + 0x64) == old
    assert not any(e[0] == "call" for e in rig.events)
    assert ("read", ai + 0x16C, 4) not in rig.events
    assert ("read", ai + 0x174, 4) not in rig.events


@pytest.mark.parametrize("after,expected", [(0x2EF, 0x2EE), (0x2EE, 0x2EE), (U32, U32)])
def test_type_setter_current_virtual_state_and_signed_clamp(after, expected):
    rig = Rig()
    ai, vptr = rig.alloc(0x178), rig.alloc(0x1B0)
    rig.put(ai, 8, vptr)
    rig.put(vptr + 0x1A8, 8, 0xA11)
    rig.put(ai + 0x3C, 4, 0x2DD)
    rig.put(ai + 0x16C, 4, 0x2EE)

    def child(args, data):
        assert args == (ai,) and data is None
        rig.put(ai + 0x174, 4, after)
        rig.put(ai + 0x3C, 4, 77)

    rig.handlers[0xA11] = child
    rig.invoke(SET3C, ai, 0x1234FFFFFFFF, 0x100000001)
    assert rig.get(ai + 0x174) == expected
    assert rig.get(ai + 0x64) == 77 and rig.get(ai + 0x3C) == U32


def test_quiet_leaf_declares_excluded_homes_and_does_no_event_work():
    rig = Rig()
    assert rig.invoke(DESCRIPTOR, U64 - 0x100) == 0xB7
    rig.events.clear()
    rig.invoke(QUIET, 1, 2, 3, 4)
    assert rig.events == []
    homes = bind_replay_formation_quiet_home_calls(rig.bound)
    homes.call(QUIET, (1, 2, 3, 4, 0xDEAD, 0xBEEF, 0, U64, 0xF00), None)
    assert rig.events == []  # Unmapped five annotation homes were not read.


@pytest.mark.parametrize("bad", [False, 0, 1, None])
def test_quiet_exclusion_requires_explicit_true_boolean(bad):
    with pytest.raises(ValueError):
        ReplayFormationAdmissionProfile(bytes(0x38), bytes(0x38), bad)


@pytest.mark.parametrize(
    "category,expected",
    [
        (0, 5),
        (1, 1),
        (2, 2),
        (3, 3),
        (4, 4),
        (5, 5),
        (6, 0),
        (7, U32),
    ],
)
def test_classifier_current_jump_table_cases(category, expected):
    rig = Rig()
    unit, _ = rig.unit(category=category)
    rig.map_table()
    assert rig.invoke(CLASSIFY, unit, 0) == expected
    assert rig.active == []


def test_classifier_reads_current_table_and_refuses_unknown_destination():
    rig = Rig()
    unit, _ = rig.unit(category=0)
    rig.map_table()
    rig.put(TABLE, 4, 0x10D993F)
    assert rig.invoke(CLASSIFY, unit, 0) == 4
    rig.put(TABLE, 4, 0xDEADBEEF)
    with pytest.raises(UnresolvedReplayTaskRebuild):
        rig.invoke(CLASSIFY, unit, 0)


@pytest.mark.parametrize(
    "flags,expected",
    [(0, 3), (1, 5), (0x10, 5), (0x11, 5), (0x80, 3), (0x81, 5), (0x90, 3), (0x91, 3)],
)
def test_classifier_exact_type_flag_branch(flags, expected):
    rig = Rig()
    unit, _ = rig.unit(kind=0x46, category=3, flags=flags)
    rig.map_table()
    assert rig.invoke(CLASSIFY, unit, 0) == expected


@pytest.mark.parametrize("identifier", [0x4EA, 0x23, 0x1A6, 0x224])
def test_classifier_special_reference_branch(identifier):
    rig = Rig()
    unit, master = rig.unit(category=4)
    payload = rig.alloc(0x10)
    rig.put(master + 0x38, 8, 13 + 0x50A06BCECEBEF905 - 0x5B32AA7995D95916)
    rig.put(master + 0x18, 8, (identifier + 0x47E37DFF0616CE4F) ^ 0x349E37847AD69F19)
    rig.put(unit + 0x18, 8, 0x12345)
    rig.put(payload + 0xF, 1, 0x50)
    rig.memory.map_bytes(0x14434D647, b"\x01")
    rig.handlers[PLAYER] = lambda args, data: 0x100000000  # Only EAX is tested.
    assert rig.invoke(CLASSIFY, unit, payload) == 0
    assert ("call", PLAYER, (0x12345,), None) in rig.events


def test_classifier_early_null_and_low_type_need_no_table():
    rig = Rig()
    assert rig.invoke(CLASSIFY, 0, 0) == U32
    unit, _ = rig.unit(kind=0x45)
    assert rig.invoke(CLASSIFY, unit, 0) == U32


@pytest.mark.parametrize("subject,predicate", [("null", 1), ("low", 1), ("high", 0x100000000)])
def test_extent_fallback_reads_current_raw_word(subject, predicate):
    rig = Rig()
    rig.memory.map_bytes(0x1431B2420, bytes.fromhex("4523c1ff"))
    unit, _ = rig.unit(kind=0x45 if subject == "low" else 0x46)
    rig.handlers[PRED] = lambda args, data: predicate
    assert rig.invoke(EXTENT, 0 if subject == "null" else unit) == 0xFFC12345
    assert not any(e[0] == "read" and e[1] == TABLE for e in rig.events)


def test_extent_uses_separate_postcallback_current_masters():
    rig = Rig()
    unit, first = rig.unit(kind=0x46)
    _, second = rig.unit(kind=0x46)
    rig.put(first + 0x78, 4, 0x40000000)
    rig.put(second + 0x358, 4, 0x40400000)
    rig.handlers[PRED] = lambda args, data: 1
    reads = 0

    def hook(address, width):
        nonlocal reads
        if address == unit + 0x10:
            reads += 1
            if reads == 2:
                rig.put(address, 8, second + ENCODE)

    rig.after_read = hook
    assert rig.invoke(EXTENT, unit) == 0x40C00000
    last = [e for e in rig.events if e[0] == "read" and e[1] in (first + 0x78, second + 0x358)]
    assert last == [("read", second + 0x358, 4), ("read", first + 0x78, 4)]


def test_classifier_live_scratch_is_not_folded_to_host_decode():
    rig = Rig()
    unit, _ = rig.unit(kind=0x47, category=1)
    _, alternate = rig.unit(kind=0x45)
    changed = False

    def hook(address, width, value):
        nonlocal changed
        if not changed and rig.active and address == rig.active[-1] + 0x30:
            changed = True
            rig.put(address, width, alternate + ENCODE)

    rig.after_write = hook
    assert rig.invoke(CLASSIFY, unit, 0) == U32


def test_unowned_calls_delegate_exactly_including_data():
    rig = Rig()
    rig.handlers[0x123] = lambda args, data: 77
    assert rig.bound.call(0x123, (1, 2, 3), b"owned") == 77
    assert rig.events[-1] == ("call", 0x123, (1, 2, 3), b"owned")
