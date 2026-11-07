"""Original-source controls; deeper children are explicit authored test effects."""

from contextlib import contextmanager

import pytest

from vantage.replay_memory import ReplayMemory
from vantage.replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
)
from vantage.replay_world_formation import (
    ReplayWorldFormationProfile,
    bind_replay_world_formation,
)

DISTANCE, MISSING, COMPATIBLE, PREDICATE = (
    0x14096D4D0,
    0x1410F67B0,
    0x1410D2680,
    0x1410D2750,
)
TRANSFER, RECOMPUTE, FORMATION = 0x1410D3AB0, 0x1410D4E50, 0x14162BAB0
MANAGER, LOOKUP, SUBOBJECT = 0x140D6ACC0, 0x141617DB0, 0x141139140
ADMISSION, GROW, EXTENT = 0x1410D95F0, 0x1410F7C20, 0x1410EEF50
AI_RESET, GROUP_REMOVE, NODE_ADD = 0x140D36E70, 0x1410F6800, 0x1410D43A0
SERVICE, PLAYER, NOTIFY = 0x140A69450, 0x141603F60, 0x140A4AFD0
CHOOSE, APPLY = 0x14110CFC0, 0x1410D6670
U32 = 0xFFFFFFFF


class Rig:
    def __init__(self):
        self.memory = ReplayMemory()
        self.events, self.locals, self.active = [], [], []
        self.after_read, self.after_write = None, None
        self.handlers, self.home_handlers = {}, {}
        self.units, self.subobjects, self.groups = {}, {}, {}
        self.game, self.manager = self.alloc(0x10), self.alloc(0x10)
        self.memory.map_bytes(0x144353698, self.game.to_bytes(8, "little"))
        self.memory.map_bytes(0x144363500, bytes.fromhex("4433221188776655"))
        self.memory.map_bytes(0x1431B7530, bytes.fromhex("ffffff7f") * 4)
        self.memory.map_bytes(0x1436A0294, bytes.fromhex("00008042"))
        self.memory.map_bytes(0x14408CA88, bytes.fromhex("0000803f"))
        self.memory.map_bytes(0x14427C720, (0x12345).to_bytes(8, "little"))

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
            self.events.append(("call", target, args))
            assert data is None
            if target not in self.handlers:
                raise UnresolvedReplayTaskRebuild(f"authored child {target:x} unavailable")
            return self.handlers[target](args)

        def home(target, args, data):
            self.events.append(("home", target, args))
            assert data is None
            if target not in self.home_handlers:
                raise UnresolvedReplayTaskRebuild(f"authored HOME child {target:x} unavailable")
            return self.home_handlers[target](args)

        self.storage = ReplayTaskRebuildStorage(1, read, write)
        self.calls, self.homes = ReplayTaskRebuildCalls(call), ReplayTaskRebuildCalls(home)
        self.profile = ReplayWorldFormationProfile(
            b"\xa5" * 0xB0,
            b"\xb6" * 0xD8,
            b"\xc7" * 0x44,
        )
        self.handlers[MANAGER] = lambda args: self.manager
        self.handlers[LOOKUP] = lambda args: self.units.get(args[1], 0)
        self.handlers[SUBOBJECT] = lambda args: self.subobjects.get(args[0], 0)
        self.bound = bind_replay_world_formation(
            self.storage,
            self.calls,
            logger_home_calls=self.homes,
            event_home_calls=self.homes,
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

    def group(self, members=(), *, category=0, ident=7, capacity=8):
        group = self.alloc(0x480)
        ids = self.alloc(max(1, capacity) * 4, 0xD8)
        rows = self.alloc(max(1, capacity) * 48, 0xE9)
        neighbours = self.alloc(16, 0xFA)
        for offset, width, value in (
            (0xD8, 4, ident),
            (0xDC, 4, 0),
            (0xE4, 4, len(members)),
            (0xE8, 4, capacity),
            (0xF0, 8, ids),
            (0xF8, 8, rows),
            (0x108, 8, neighbours),
            (0x110, 4, 0),
            (0x138, 4, 0x12345678),
            (0x1D8, 8, group + 0x1D8),
            (0x1E0, 8, group + 0x1D8),
            (0x450, 8, group + 0x430),
            (0x460, 4, 0),
        ):
            self.put(group + offset, width, value)
        for i, ident in enumerate(members):
            self.put(ids + i * 4, 4, ident)
            if ident not in self.units:
                self.unit(ident, category=category)
        return group, ids, rows

    def unit(self, ident, *, category=0, kind=0):
        unit, ai, master = self.alloc(0x240), self.alloc(0x220), self.alloc(0x40)
        self.put(unit + 8, 4, ident)
        self.put(unit + 0xF, 1, kind)
        self.put(unit + 0x10, 8, master + 0x6A586EB28AC201FC + 0x0CF19788B2554E70)
        self.put(unit + 0x1F0, 8, ai)
        self.put(unit + 0x210, 4, U32)
        self.put(ai + 0x1DC, 1, category)
        self.units[ident] = unit
        return unit, ai

    def admit_transfer(self):
        descriptor, text = self.alloc(8), self.alloc(8)
        self.put(descriptor, 8, text)
        self.handlers[0x140A4B870] = lambda args: descriptor
        self.home_handlers[0x140B6EF80] = lambda args: None
        self.handlers[ADMISSION] = lambda args: 0
        self.handlers[0x140D23D40] = lambda args: 0
        self.handlers[0x140D23D50] = lambda args: 0
        self.handlers[AI_RESET] = lambda args: None
        self.handlers[EXTENT] = lambda args: 0x3F800000
        return descriptor, text

    def reset_calls(self):
        self.handlers[CHOOSE] = lambda args: None
        self.handlers[APPLY] = lambda args: None


@pytest.mark.parametrize(
    "alias,expected",
    [
        (None, [0x40400000, 0x40400000, 0x40400000]),
        (4, [0x40400000, 0x40400000, 0x40400000]),
        (8, [0x40400000, 0x40400000, 0]),
    ],
)
def test_distance_literal_alias_order(alias, expected):
    rig = Rig()
    left, right = rig.alloc(24), rig.alloc(12)
    output = rig.alloc(12) if alias is None else left + alias
    for i, value in enumerate((0x40800000, 0x40A00000, 0x40C00000)):
        rig.put(left + i * 4, 4, value)
    for i, value in enumerate((0x3F800000, 0x40000000, 0x40400000)):
        rig.put(right + i * 4, 4, value)
    assert rig.invoke(DISTANCE, left, output, right) == output
    assert [rig.get(output + i * 4) for i in range(3)] == expected
    assert rig.events == [
        ("read", left, 4),
        ("read", right, 4),
        ("read", left + 4, 4),
        ("read", right + 4, 4),
        ("write", output, 4, expected[0]),
        ("read", left + 8, 4),
        ("read", right + 8, 4),
        ("write", output + 4, 4, expected[1]),
        ("write", output + 8, 4, expected[2]),
    ]


@pytest.mark.parametrize("count", [0, U32, 0x80000000])
def test_missing_id_nonpositive_count_never_reads_array(count):
    rig = Rig()
    group = rig.alloc(0x114, 0xAA)
    rig.put(group + 0x110, 4, count)
    assert rig.invoke(MISSING, group, 77) == 0
    assert rig.events == [("read", group + 0x110, 4)]


def test_missing_id_marks_only_first_match_without_shrinking():
    rig = Rig()
    group, _, _ = rig.group()
    ids = rig.get(group + 0x108, 8)
    rig.put(group + 0x110, 4, 3)
    for i, value in enumerate((11, 22, 22)):
        rig.put(ids + i * 4, 4, value)
    assert rig.invoke(MISSING, group, 0x123400000016) == 1
    assert [rig.get(ids + i * 4) for i in range(3)] == [11, U32, 22]
    assert rig.get(group + 0x110) == 3
    assert rig.invoke(MISSING, group, 33) == 0


@pytest.mark.parametrize(
    "left,right,expected",
    [
        (7, 7, 1),
        (7, U32 - 6, 1),
        (U32 - 6, 7, 0),
        (0x80000000, 0x80000000, 1),
        (0, 0, 1),
    ],
)
def test_compatibility_positive_absolute_with_int_min(left, right, expected):
    rig = Rig()
    a, _, _ = rig.group()
    b, _, _ = rig.group()
    rig.put(a + 0x460, 4, left)
    rig.put(b + 0x460, 4, right)
    assert rig.invoke(COMPATIBLE, a, b) & 255 == expected


@pytest.mark.parametrize("original,left", [(7, 3), (U32 - 6, 7)])
def test_compatibility_cmov_reads_current_operand_even_when_not_selected(original, left):
    rig = Rig()
    a, _, _ = rig.group()
    b, _, _ = rig.group()
    rig.put(a + 0x460, 4, left)
    rig.put(b + 0x460, 4, original)
    reads = []

    def hook(address, width):
        if address == b + 0x460:
            reads.append(address)
            rig.put(address, width, 3)

    rig.after_read = hook
    assert rig.invoke(COMPATIBLE, a, b) & 255 == 1
    assert len(reads) == 2


def test_compatibility_ordered_link_pairs_and_early_tag_rejection():
    rig = Rig()
    a, _, _ = rig.group()
    b, _, _ = rig.group()
    first, second = rig.alloc(0x28), rig.alloc(0x28)
    for group, node in ((a, first), (b, second)):
        rig.put(group + 0x450, 8, node)
        rig.put(node, 4, 0x11223344)
        rig.put(node + 4, 4, 0x55667788)
        rig.put(node + 0x20, 8, group + 0x430)
    assert rig.invoke(COMPATIBLE, a, b) & 255 == 1
    rig.put(second + 4, 4, 99)
    assert rig.invoke(COMPATIBLE, a, b) & 255 == 0
    rig.put(b + 0x3B0, 4, 3)
    rig.events.clear()
    assert rig.invoke(COMPATIBLE, a, b) & 255 == 0
    assert rig.events == [("read", b + 0x3B0, 4), ("read", a + 0x3B0, 4)]


@pytest.mark.parametrize("count,manager_calls", [(0, 0), (U32, 1)])
def test_predicate_initial_zero_differs_from_initial_negative(count, manager_calls):
    rig = Rig()
    group, _, _ = rig.group()
    rig.put(group + 0xE4, 4, count)
    assert rig.invoke(PREDICATE, group) & 255 == 0
    assert len([x for x in rig.events if x[:2] == ("call", MANAGER)]) == manager_calls


@pytest.mark.parametrize("kind,expected", [(123, 0), (124, 1), (125, 1), (126, 0)])
def test_predicate_reached_subobject_kind(kind, expected):
    rig = Rig()
    group, _, _ = rig.group((12,))
    unit = rig.units[12]
    rig.put(unit + 0xF, 1, 40)
    subobject = rig.alloc(16)
    rig.put(subobject + 8, 2, kind)
    rig.subobjects[unit] = subobject
    assert rig.invoke(PREDICATE, group) & 255 == expected


def test_predicate_rereads_array_and_count_but_holds_manager():
    rig = Rig()
    group, _, _ = rig.group((11,))
    replacement = rig.alloc(8)
    rig.put(replacement, 4, 11)
    rig.put(replacement + 4, 4, 12)
    unit, _ = rig.unit(12, kind=40)
    subobject = rig.alloc(16)
    rig.put(subobject + 8, 2, 124)
    rig.subobjects[unit] = subobject

    def lookup(args):
        assert args[0] == rig.manager
        if args[1] == 11:
            rig.put(group + 0xE4, 4, 2)
            rig.put(group + 0xF0, 8, replacement)
            rig.put(0x144353698, 8, 0x987654)
            return 0
        return unit

    rig.handlers[LOOKUP] = lookup
    assert rig.invoke(PREDICATE, group) & 255 == 1
    assert len([x for x in rig.events if x[:2] == ("call", MANAGER)]) == 1


def test_transfer_missing_unit_zero_diagnostic_has_no_other_children():
    rig = Rig()
    group, _, _ = rig.group()
    assert rig.invoke(TRANSFER, group, 404, U32, 0) == 0
    assert [x[1] for x in rig.events if x[0] == "call"] == [MANAGER, LOOKUP]


def test_transfer_zero_diagnostic_still_passes_live_partial_event_homes():
    rig = Rig()
    group, ids, _ = rig.group((12,))
    _, text = rig.admit_transfer()

    def home(args):
        assert args[:4] == (0x15, 0, 0x55667788, 0x11223344)
        # The event channel receives five live home addresses after four regs.
        assert len(args) == 9
        assert [rig.get(args[i], w) for i, w in ((4, 4), (5, 4), (6, 8), (7, 4), (8, 8))] == [
            7,
            12,
            0x1432A0B00,
            12,
            text,
        ]
        assert rig.get(args[4] + 4) == 0xB6B6B6B6
        assert rig.get(args[5] + 4) == 0xB6B6B6B6

    rig.home_handlers[0x140B6EF80] = home
    before = rig.memory.read_bytes(ids, 32)
    assert rig.invoke(TRANSFER, group, 12, U32, 0) == 1
    assert rig.memory.read_bytes(ids, 32) == before
    assert rig.get(group + 0xE4) == 1
    assert [x[1] for x in rig.events if x[0] == "call"] == [
        MANAGER,
        LOOKUP,
        0x140A4B870,
        ADMISSION,
    ]


def insertion_rig():
    rig = Rig()
    group, ids, rows = rig.group((11,))
    unit, ai = rig.unit(12)
    rig.admit_transfer()
    lookups = []

    def lookup(args):
        lookups.append(args)
        return unit if len(lookups) == 1 else 0

    rig.handlers[LOOKUP] = lookup
    return rig, group, ids, rows, unit, ai


def test_transfer_publishes_literal_member_row_and_flags():
    rig, group, ids, rows, unit, _ = insertion_rig()
    assert rig.invoke(TRANSFER, group, 12, U32, 0) == 1
    assert rig.get(unit + 0x210) == 7
    assert [rig.get(ids + i * 4) for i in range(3)] == [11, 12, 0xD8D8D8D8]
    assert rig.get(group + 0xE4) == 2
    assert rig.memory.read_bytes(rows, 48) == b"\xe9" * 48
    assert rig.memory.read_bytes(rows + 48, 48) == b"\0" * 4 + b"\xff" * 8 + b"\0" * 36
    assert rig.memory.read_bytes(rows + 96, 48) == b"\xe9" * 48
    assert rig.get(group + 0x15C) == 0x40000000
    assert rig.get(group + 0x140) == 0x10002
    insertion = rig.events.index(("write", ids + 4, 4, 12))
    increment = rig.events.index(("write", group + 0xE4, 4, 2))
    assert insertion < increment
    assert rig.events[insertion - 2 : insertion] == [
        ("read", group + 0xE4, 4),
        ("read", group + 0xF0, 8),
    ]


@pytest.mark.parametrize(
    "extent,prior,expected",
    [
        (0x3F800000, 0x40000000, 0x40000000),
        (0x3F000000, 0x40000000, 0x40000000),
        (0x7FC12345, 0x40000000, 0x40000000),
        (0x40000000, 0x40000000, 0x40800000),
    ],
)
def test_transfer_binary32_extent_and_current_flag_admission(extent, prior, expected):
    rig, group, _, _, _, _ = insertion_rig()
    rig.handlers[EXTENT] = lambda args: extent
    rig.put(group + 0x15C, 4, prior)
    rig.put(group + 0xB8, 1, 2)
    rig.put(group + 0x140, 4, 0x80)
    assert rig.invoke(TRANSFER, group, 12, U32, 0) == 1
    assert rig.get(group + 0x15C) == expected
    assert rig.get(group + 0x140) == 0x82


def test_transfer_final_flags_hold_before_b8_callback():
    rig, group, _, _, _, _ = insertion_rig()

    def hook(address, width):
        if address == group + 0xB8:
            rig.put(group + 0x140, 4, 0xDEADBEEF)

    rig.after_read = hook
    rig.invoke(TRANSFER, group, 12, U32, 0)
    assert rig.get(group + 0x140) == 0x10002


def test_transfer_zero_capacity_grows_ten_then_twice_current_capacity():
    rig, group, _, _, _, _ = insertion_rig()
    rig.put(group + 0xE4, 4, 0)
    rig.put(group + 0xE8, 4, 0)
    requests = []

    def grow(args):
        requests.append(args)
        if len(requests) == 1:
            rig.put(group + 0xE8, 4, 13)
            return 1
        return 0

    rig.handlers[GROW] = grow
    assert rig.invoke(TRANSFER, group, 12, U32, 0) == 0
    assert requests == [(group, 10), (group, 26)]
    assert rig.get(group + 0xE4) == 0
    assert rig.get(group + 0xE8) == 13


def test_transfer_old_group_removal_then_new_identity_before_ai_refusal():
    rig, group, _, _, unit, _ = insertion_rig()
    old, _, _ = rig.group((12,), ident=99)
    rig.put(unit + 0x210, 4, 99)
    rig.handlers[0x141604060] = lambda args: old
    rig.handlers[GROUP_REMOVE] = lambda args: 1

    def refuse(args):
        raise UnresolvedReplayTaskRebuild("authored AI reset refuses")

    rig.handlers[AI_RESET] = refuse
    with pytest.raises(UnresolvedReplayTaskRebuild, match="AI reset refuses"):
        rig.invoke(TRANSFER, group, 12, U32, 0)
    assert ("call", GROUP_REMOVE, (old, 12, U32, 0)) in rig.events
    writes = [x for x in rig.events if x[:3] == ("write", unit + 0x210, 4)]
    assert writes == [("write", unit + 0x210, 4, U32), ("write", unit + 0x210, 4, 7)]
    assert rig.get(group + 0xE4) == 1


def test_transfer_auxiliary_allocation_uses_actual_owned_runtime_effects():
    rig = Rig()
    group, _, _ = rig.group((11,))
    unit, _ = rig.unit(12)
    rig.admit_transfer()
    rig.handlers[ADMISSION] = lambda args: 3
    runtime = rig.memory.runtime_calls()
    for target in (0x142D6BA78, 0x142D6E3B7):
        rig.handlers[target] = lambda args, target=target: runtime.call(target, args, None)
    rig.handlers[NODE_ADD] = lambda args: None
    assert rig.invoke(TRANSFER, group, 12, U32, 0) == 1
    node = rig.get(group + 0x1E0, 8)
    assert node != group + 0x1D8
    assert rig.get(node, 8) == group + 0x1D8
    assert rig.get(node + 8, 8) == group + 0x1D8
    assert rig.get(group + 0x1D8, 8) == node
    assert rig.get(node + 0x10) == 3
    assert rig.get(group + 0x1D0) == 1
    assert ("call", NODE_ADD, (node, 12)) in rig.events
    assert len([x for x in rig.events if x[:2] == ("call", 0x142D6E3B7)]) == 3
    assert rig.get(unit + 0x210) == 7


def test_positive_formation_composes_actual_membership_and_recompute():
    rig = Rig()
    world, sentinel, player, players = (rig.alloc(n) for n in (0x780, 0xD0, 0x600, 16))
    source, source_ids, _ = rig.group((11,), ident=7)
    peer, _, _ = rig.group((12,), ident=9)
    for address, width, value in (
        (world + 0x50, 8, sentinel),
        (world + 0x768, 8, players),
        (players, 8, player),
        (sentinel + 0xC8, 8, source),
        (source + 0xC8, 8, peer),
        (peer + 0xC8, 8, sentinel),
        (source + 0x110, 4, 1),
        (rig.get(source + 0x108, 8), 4, 9),
        (rig.units[12] + 0x210, 4, 9),
    ):
        rig.put(address, width, value)
    rig.admit_transfer()
    rig.reset_calls()
    rig.handlers[0x141604060] = lambda args: peer

    def remove(args):
        assert args == (peer, 12, U32, 0)
        rig.put(peer + 0xE4, 4, 0)
        return 1

    rig.handlers[GROUP_REMOVE] = remove
    runtime = rig.memory.runtime_calls()
    for target in (0x142D6BA78, 0x142D6E3B7):
        rig.handlers[target] = lambda args, target=target: runtime.call(target, args, None)
    rig.handlers[NODE_ADD] = lambda args: None
    assert rig.invoke(FORMATION, world) is None
    assert rig.get(source + 0xE4) == 2
    assert rig.get(peer + 0xE4) == 0
    assert [rig.get(source_ids + i * 4) for i in range(2)] == [11, 12]
    assert rig.get(rig.units[12] + 0x210) == 7
    assert rig.get(source + 0x138) == 0
    assert ("call", CHOOSE, (source, U32)) in rig.events
    assert not rig.active


@pytest.mark.parametrize("category", [0, 1, 2, 3, 8, 9, 255])
def test_recompute_actual_category_selection_and_reset(category):
    rig = Rig()
    group, _, _ = rig.group((11, 12), category=category)
    rig.reset_calls()
    rig.handlers[SERVICE] = lambda args: 0x888
    rig.handlers[PLAYER] = lambda args: 0x999
    rig.handlers[NOTIFY] = lambda args: None
    assert rig.invoke(RECOMPUTE, group) is None
    selected = category if 3 <= category <= 8 else 0
    assert rig.get(group + 0x138) == selected
    if selected:
        assert ("call", NOTIFY, (0x888, 0x999, 14, category)) in rig.events
        assert ("call", CHOOSE, (group, category)) in rig.events
        assert ("call", APPLY, (group, 1, category)) in rig.events
    else:
        assert ("call", CHOOSE, (group, U32)) in rig.events
        assert all(rig.get(rig.get(unit + 0x1F0, 8) + 0x1DC, 1) == 0 for unit in rig.units.values())


def test_recompute_reset_reads_current_selection_after_first_child():
    rig = Rig()
    group, _, _ = rig.group((11,), category=1)
    rig.reset_calls()

    def choose(args):
        assert args == (group, U32)
        assert rig.get(group + 0x138) == 0
        rig.put(group + 0x138, 4, 8)

    rig.handlers[CHOOSE] = choose
    rig.invoke(RECOMPUTE, group)
    assert ("call", APPLY, (group, 1, 8)) in rig.events


@pytest.mark.parametrize("categories,expected", [([3, 4], 3), ([8, 3, 8], 8), ([0, 8], 0)])
def test_recompute_strict_greatest_preserves_earliest_tie(categories, expected):
    rig = Rig()
    group, _, _ = rig.group(tuple(range(11, 11 + len(categories))))
    for ident, category in zip(range(11, 11 + len(categories)), categories, strict=True):
        rig.put(rig.get(rig.units[ident] + 0x1F0, 8) + 0x1DC, 1, category)
    rig.reset_calls()
    rig.handlers[SERVICE] = lambda args: 0x888
    rig.handlers[PLAYER] = lambda args: 0x999
    rig.handlers[NOTIFY] = lambda args: None
    rig.invoke(RECOMPUTE, group)
    assert rig.get(group + 0x138) == expected


@pytest.mark.parametrize("new_count", [0, U32])
def test_recompute_nonpositive_still_runs_reset_children(new_count):
    rig = Rig()
    group, _, _ = rig.group()
    rig.put(group + 0xE4, 4, new_count)
    rig.reset_calls()
    rig.invoke(RECOMPUTE, group)
    assert rig.get(group + 0x138) == 0
    assert [x for x in rig.events if x[0] == "call"] == [
        ("call", CHOOSE, (group, U32)),
        ("call", APPLY, (group, 1, 0)),
    ]


def test_recompute_initially_skipped_scan_retains_edx_zero():
    rig = Rig()
    group, _, _ = rig.group()
    rig.reset_calls()

    def hook(address, width, value):
        if width == 16 and rig.active and address == rig.active[-1] + 0x30:
            rig.put(rig.active[-1] + 0x40, 4, 10)

    rig.after_write = hook
    rig.invoke(RECOMPUTE, group)
    assert rig.get(group + 0x138) == 0
    assert not any(x[:2] == ("call", SERVICE) for x in rig.events)


def test_empty_world_skips_formation_constants_and_all_children():
    rig = Rig()
    world, sentinel = rig.alloc(0x780), rig.alloc(0xD0)
    rig.put(world + 0x50, 8, sentinel)
    rig.put(sentinel + 0xC8, 8, sentinel)
    assert rig.invoke(FORMATION, world) is None
    assert rig.events == [("read", world + 0x50, 8), ("read", sentinel + 0xC8, 8)]


def test_unknown_dispatch_preserves_objects_and_result():
    rig = Rig()
    args, data, answer = (1, 2), memoryview(bytearray(b"abc")), object()

    def call(target, actual_args, actual_data):
        assert (target, actual_args, actual_data) == (123, args, data)
        assert actual_args is args and actual_data is data
        return answer

    bound = bind_replay_world_formation(
        rig.storage,
        ReplayTaskRebuildCalls(call),
        logger_home_calls=rig.homes,
        event_home_calls=rig.homes,
        bind_local=rig.local,
        profile=rig.profile,
        mxcsr=0x1F80,
    )
    assert bound.call(123, args, data) is answer


@pytest.mark.parametrize(
    "target,args",
    [
        (DISTANCE, (1, 2)),
        (MISSING, (1,)),
        (COMPATIBLE, (1,)),
        (PREDICATE, ()),
        (TRANSFER, (1, 2, 3)),
        (RECOMPUTE, ()),
        (FORMATION, ()),
    ],
)
def test_owned_arities_reject_before_storage(target, args):
    rig = Rig()
    with pytest.raises(ValueError):
        rig.invoke(target, *args)
    assert not rig.events
