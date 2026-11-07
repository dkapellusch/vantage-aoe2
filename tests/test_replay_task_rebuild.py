"""Control/storage probes; observer helpers do not establish native lifecycle parity."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from vantage.replay_health_transforms import (
    ReplayHealthTransformCallbacks,
    ReplayHealthTransformStorage,
    run_replay_health_transforms,
)
from vantage.replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildScratch,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
    run_replay_task_rebuild,
)

SUBJECT, LIST, POINTERS = 0x10000, 0x20000, 0x21000
MASTER, OWNER, TABLE, TARGET = 0x40000, 0x50000, 0x51000, 0x52000
RULES, HEALTH, GROUP, SUBGROUP = 0x60000, 0x70000, 0x80000, 0x90000
CLASSES, GROUP_SLOT, SUBGROUP_SLOT, NEW = 0xA0000, 0xB0000, 0xB0010, 0xD0000
MASTER_ADD = 0x6A586EB28AC201FC + 0x0CF19788B2554E70
U64 = (1 << 64) - 1
SEED = bytes(range(48))
SCRATCH = ReplayTaskRebuildScratch(SEED, b"xyz", b"abc")


class Probe:
    """Explicit scalar backing and controllable helper observers, not a World."""

    def __init__(self) -> None:
        self.memory: dict[int, int] = {}
        self.events: list[tuple[object, ...]] = []
        self.calls: list[tuple[int, tuple[int, ...], bytes | None]] = []
        self.hooks: dict[int, Callable[[tuple[int, ...], memoryview | None], int | None]] = {}
        self.find_result: int | None = None
        self.mask = 0
        for base, size in (
            (SUBJECT, 0x1000),
            (LIST, 0x20),
            (POINTERS, 0x200),
            (0x30000, 0x3000),
            (MASTER, 0x300),
            (OWNER, 0x100),
            (TABLE, 0x100),
            (TARGET, 0x100),
            (RULES, 0x1000),
            (HEALTH, 0x1000),
            (GROUP, 0x100),
            (SUBGROUP, 0x100),
            (CLASSES, 0x1000),
            (GROUP_SLOT, 0x20),
            (NEW, 0x1000),
        ):
            self.memory.update((base + i, 0) for i in range(size))
        self.put(SUBJECT + 0x10, 8, MASTER + MASTER_ADD)
        self.put(SUBJECT + 0x18, 8, OWNER)
        self.put(OWNER + 0x20, 4, 16)
        self.put(OWNER + 0x28, 8, TABLE)
        self.put(TABLE + 4 * 8, 8, TARGET)
        self.put(TARGET + 0x38, 8, 7 - 0x0A923EAAC71A6011)
        self.vector(SUBJECT + 0x730, RULES, RULES, RULES + 0x1000)
        self.vector(SUBJECT + 0x7A8, HEALTH, HEALTH, HEALTH + 0x1000)
        self.vector(GROUP + 0x60, CLASSES, CLASSES, CLASSES + 0x1000)
        self.put(GROUP_SLOT, 8, GROUP)
        self.put(SUBGROUP_SLOT, 8, SUBGROUP)
        self.put(LIST + 8, 8, POINTERS)
        self.put(LIST + 0x10, 8, POINTERS)
        self.events.clear()

    def put(self, address: int, width: int, value: int) -> None:
        for i in range(width):
            self.memory[(address + i) & U64] = value >> (8 * i) & 255

    def get(self, address: int, width: int) -> int:
        return sum(self.memory[(address + i) & U64] << (8 * i) for i in range(width))

    def raw(self, address: int, width: int) -> bytes:
        return self.get(address, width).to_bytes(width, "little")

    def read(self, address: int, width: int) -> int:
        self.events.append(("read", address, width))
        return self.get(address, width)

    def write(self, address: int, width: int, value: int) -> None:
        self.events.append(("write", address, width, value))
        self.put(address, width, value)

    def vector(self, address: int, begin: int, end: int, capacity: int) -> None:
        for offset, value in ((0, begin), (8, end), (16, capacity)):
            self.put(address + offset, 8, value)

    def task(self, index: int, kind: int, fields: dict[int, tuple[int, int]] | None = None) -> int:
        address = 0x30000 + index * 0x100
        self.put(address + 0xE, 2, kind)
        if fields:
            for offset, (width, value) in fields.items():
                self.put(address + offset, width, value)
        return address

    def tasks(self, *values: int) -> None:
        for i, value in enumerate(values):
            self.put(POINTERS + i * 8, 8, value)
        self.put(LIST + 0x10, 8, POINTERS + len(values) * 8)

    def call(self, target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        raw = bytes(data) if data is not None else None
        self.calls.append((target, args, raw))
        self.events.append(("call", target, args, raw))
        if target in self.hooks:
            return self.hooks[target](args, data)
        if target == 0x1410B9F00:
            return (args[0] + 900) & 0xFFFFFFFF
        if target == 0x1410BA3D0:
            return int(900 <= args[0] <= 999)
        if target == 0x1410BD060:
            return (args[0] - 900) & 0xFFFFFFFF
        if target == 0x1412A4560:
            return GROUP_SLOT
        if target == 0x1412A4220:
            return SUBGROUP_SLOT
        if target == 0x142D6A0D0:
            return self.find_result if self.find_result is not None else self.get(GROUP + 0x68, 8)
        if target == 0x141320720:
            return self.mask
        if target == 0x1402A94D0:
            return NEW
        if target == 0x142D6E3DB:
            destination, source, count = args
            raw_copy = self.raw(source, count)
            for i, value in enumerate(raw_copy):
                self.put(destination + i, 1, value)
        if target == 0x1402BA840:
            vector, allocation, count, capacity = args
            self.vector(vector, allocation, allocation + count * 4, allocation + capacity * 4)
        return None

    def run(self, task_list: int = LIST, *, scratch: ReplayTaskRebuildScratch = SCRATCH) -> None:
        run_replay_task_rebuild(
            ReplayTaskRebuildStorage(SUBJECT, self.read, self.write),
            task_list,
            mxcsr=0x1F80,
            scratch=scratch,
            calls=ReplayTaskRebuildCalls(self.call),
        )

    def matching(self, target: int) -> list[tuple[int, tuple[int, ...], bytes | None]]:
        return [call for call in self.calls if call[0] == target]


def transform(probe: Probe, index: int = 0, **fields: int) -> int:
    values = {
        0x10: (2, 4),
        0x12: (2, 4),
        0x1C: (4, 0x40400000),
        0x28: (4, 0x40A00000),
        0x2C: (4, 0x3F800000),
        0x30: (4, 0x40000000),
    }
    for name, value in fields.items():
        offset = int(name[1:], 16)
        width = {0x10: 2, 0x12: 2, 0x15: 1, 0x18: 1, 0x1B: 1, 0x34: 2, 0x38: 2, 0x48: 8}.get(
            offset, 4
        )
        values[offset] = (width, value)
    return probe.task(index, 155, values)


def test_unconditional_prefix_and_clears_even_null_list() -> None:
    p = Probe()

    def prefix(args: tuple[int, ...], data: memoryview | None) -> None:
        assert args == (SUBJECT, 0) and data is None
        p.put(SUBJECT + 0x730, 8, RULES + 40)
        p.put(SUBJECT + 0x738, 8, RULES + 80)
        p.put(SUBJECT + 0x7B0, 8, HEALTH + 48)

    p.hooks[0x14114BF70] = prefix
    p.run(0)
    assert p.get(SUBJECT + 0x738, 8) == RULES + 40
    assert p.get(SUBJECT + 0x7B0, 8) == HEALTH
    assert [c[0] for c in p.calls] == [0x14114BF70, 0x1412C5270]
    assert p.events[-1] == ("call", 0x1412C5270, (SUBJECT + 0x6E0,), None)


def test_empty_list_and_equal_vectors_do_not_store() -> None:
    p = Probe()
    p.run()
    assert not [e for e in p.events if e[0] == "write"]
    assert p.events[-2:] == [("read", LIST + 0x10, 8), ("read", LIST + 8, 8)]


def test_null_unknown_six_and_resource_task_in_order() -> None:
    p = Probe()
    six = p.task(0, 6, {0x30: (4, 0xFFC12345), 0x1C: (4, 0x80000000)})
    resource = p.task(1, 164)
    p.tasks(0, p.task(2, 156), six, resource)
    p.run()
    assert p.get(SUBJECT + 0x80C, 4) == 0xFFC12345
    assert p.get(SUBJECT + 0x810, 4) == 0x80000000
    assert p.matching(0x1412B7850) == [(0x1412B7850, (SUBJECT, resource), None)]


@pytest.mark.parametrize(
    ("mode", "selector", "expected"),
    [
        (0, 3, True),
        (8, 13, True),
        (9, 3, False),
        (255, 13, False),
        (0, 2, False),
    ],
)
def test_type_three_exact_gates_and_double_master_read(
    mode: int,
    selector: int,
    expected: bool,
) -> None:
    p = Probe()
    p.put(MASTER + 0x1FC, 1, mode)
    p.tasks(p.task(0, 3, {0x10: (2, selector)}))
    p.run()
    assert bool(p.matching(0x1412483F0)) is expected
    assert p.events.count(("read", SUBJECT + 0x10, 8)) == 2


def test_tail_rereads_original_list_after_helper_relocation() -> None:
    p = Probe()
    first = p.task(0, 164)
    second = p.task(1, 6, {0x30: (4, 123)})
    p.tasks(first)

    def relocate(args: tuple[int, ...], data: memoryview | None) -> None:
        p.put(LIST + 8, 8, POINTERS + 0x80)
        p.put(LIST + 0x10, 8, POINTERS + 0x90)
        p.put(POINTERS + 0x88, 8, second)

    p.hooks[0x1412B7850] = relocate
    p.run()
    assert p.get(SUBJECT + 0x80C, 4) == 123
    assert ("read", POINTERS + 0x88, 8) in p.events


@pytest.mark.parametrize(
    ("raw", "converted"),
    [
        (0, 0),
        (0x80000000, 0),
        (0x00000001, 0),
        (0x3FC00000, 1),
        (0xBFC00000, 0xFFFFFFFF),
        (0x4EFFFFFF, 0x7FFFFF80),
        (0x4F000000, 0x80000000),
        (0xCF000000, 0x80000000),
        (0xCF000001, 0x80000000),
        (0x7F800000, 0x80000000),
        (0xFF800000, 0x80000000),
        (0x7F812345, 0x80000000),
        (0xFFC12345, 0x80000000),
    ],
)
def test_health_cvtt_and_uninitialized_padding(raw: int, converted: int) -> None:
    p = Probe()
    p.tasks(
        p.task(
            0,
            158,
            {
                0x28: (4, raw),
                0x2C: (4, 0x7F812345),
                0x22: (2, 0xFFFE),
                0x24: (2, 0xFFFF),
                0x60: (16, int.from_bytes(bytes(range(80, 96)), "little")),
                0x70: (8, 0x123456789ABCDEF0),
            },
        )
    )
    p.run()
    row = p.raw(HEALTH, 48)
    assert int.from_bytes(row[:4], "little") == converted
    assert row[4:12] == bytes.fromhex("4523817ffeffffff")
    assert row[13:16] == SEED[13:16] and row[20:24] == SEED[20:24]
    assert row[16:20] == b"\xff" * 4
    assert row[24:40] == bytes(range(80, 96))
    assert row[40:48] == bytes.fromhex("f0debc9a78563412")
    assert p.get(SUBJECT + 0x7B0, 8) == HEALTH + 48


@pytest.mark.parametrize("flags", [0, 1, 2, 3, 128, 255])
def test_health_scale_requires_exact_byte_one(flags: int) -> None:
    p = Probe()
    p.put(TARGET + 0x18, 2, 0xFFFA)
    p.tasks(p.task(0, 158, {0x15: (1, flags), 0x48: (8, TARGET)}))
    p.run()
    assert p.get(HEALTH + 12, 1) == int(flags == 1)
    assert p.get(HEALTH + 16, 4) == 0xFFFFFFFA


def test_descriptor_scratch_inherits_prior_health_bytes() -> None:
    p = Probe()
    health = p.task(0, 158, {0x60: (16, int.from_bytes(bytes(range(80, 96)), "little"))})
    p.tasks(health, transform(p, 1, f1b=255, f38=-3, f18=6))
    p.run()
    row = p.raw(RULES, 40)
    assert row[23] == SEED[23]
    assert row[37:40] == bytes(range(93, 96))
    assert row[22] == 1 and row[36] == 0
    assert p.get(RULES, 4) == 904
    assert p.get(RULES + 32, 4) == 0xFFFFFFFD


def test_health_capacity_helper_mutates_shared_descriptor() -> None:
    p = Probe()
    p.put(SUBJECT + 0x7B8, 8, HEALTH)

    def append(args: tuple[int, ...], data: memoryview | None) -> None:
        assert args == (SUBJECT + 0x7A8, HEALTH) and data is not None
        data[23] = 221

    p.hooks[0x1412A3AB0] = append
    p.tasks(p.task(0, 158), transform(p, 1))
    p.run()
    assert p.get(RULES + 23, 1) == 221
    assert not [e for e in p.events if e[0] == "write" and e[1] == HEALTH]


@pytest.mark.parametrize(
    ("selector", "fallback", "descriptor", "group", "resolve"),
    [
        (-1000, 4, -1000, -1000, False),
        (-999, 4, 4, 7, False),
        (-1, -1, -1, None, False),
        (0, 4, 900, 0, True),
        (99, 4, 999, 99, True),
        (100, 4, 1000, None, True),
        (999, 4, 1899, None, True),
        (1000, 4, 1000, 1000, False),
    ],
)
def test_transform_selector_modes(
    selector: int, fallback: int, descriptor: int, group: int | None, resolve: bool
) -> None:
    p = Probe()
    p.tasks(transform(p, f10=selector, f12=fallback))
    p.run()
    assert bool(p.matching(0x1410B9F00)) is resolve
    if group is None:
        assert p.get(SUBJECT + 0x738, 8) == RULES
    else:
        assert p.get(RULES, 4) == descriptor & 0xFFFFFFFF
        assert p.matching(0x142D6A0D0)[0][1][2] == group & 0xFFFFFFFF


@pytest.mark.parametrize("threshold", [0, 0x80000000, 0xBF800000, 0x7FC12345, 0x7F812345])
def test_nonpositive_unordered_transform_still_keeps_first_nonzero_fields(threshold: int) -> None:
    p = Probe()
    p.tasks(transform(p, f2c=threshold, f60=0x80000000, f78=5, f34=-9))
    p.run()
    assert (p.get(SUBJECT + 0x750, 4), p.get(SUBJECT + 0x754, 4), p.get(SUBJECT + 0x74C, 4)) == (
        0x80000000,
        5,
        0xFFFFFFF7,
    )
    assert not p.matching(0x1412A4560)


def test_first_nonzero_local_flags_survive_object_callback_changes() -> None:
    p = Probe()
    p.tasks(
        transform(p, 0, f60=0, f78=2, f34=0, f2c=0),
        transform(p, 1, f60=4, f78=5, f34=-1, f15=0x40, f2c=0),
        transform(p, 2, f60=8, f78=9, f34=10, f2c=0),
    )

    def clear_fields(args: tuple[int, ...], data: memoryview | None) -> None:
        for member in (0x750, 0x754, 0x74C):
            p.put(SUBJECT + member, 4, 0)

    p.hooks[0x141244C90] = clear_fields
    p.run()
    assert [p.get(SUBJECT + member, 4) for member in (0x750, 0x754, 0x74C)] == [0, 0, 0]


def test_bit_eight_skips_fields_and_flag40_fields_refresh_after_callback() -> None:
    p = Probe()
    task = transform(p, f15=0x48, f60=5, f78=6, f34=7)
    p.tasks(task)

    def mutate(args: tuple[int, ...], data: memoryview | None) -> None:
        p.put(task + 0x28, 4, 0xC0000000)
        p.put(task + 0x1B, 1, 8)

    p.hooks[0x141244C90] = mutate
    p.run()
    assert [p.get(SUBJECT + member, 4) for member in (0x750, 0x754, 0x74C)] == [0, 0, 0]
    assert p.get(RULES + 8, 4) == 0xC0000000 and p.get(RULES + 22, 1) == 1


@pytest.mark.parametrize(
    ("kind", "bucket"),
    [(0, 31), (1, 2), (2, 24), (3, 1), (4, 7), (5, 25), (6, 29), (7, 31), (255, 31)],
)
def test_group_and_criterion_raw_keys(kind: int, bucket: int) -> None:
    p = Probe()
    p.tasks(transform(p, f18=kind, f15=3, f48=0x123456789ABCDEF0))
    p.run()
    expected = bytes.fromhex("0000004000000000") + bytes([bucket]) + b"xyz"
    assert p.matching(0x1412A4560)[0][2] == expected
    assert p.matching(0x1412A4220)[0][2] == (
        b"\x01abc" + bytes.fromhex("030000000000a0400000803f") + bytes.fromhex("f0debc9a78563412")
    )
    row = p.matching(0x1412A57E0)[0]
    assert row[1:] == ((SUBGROUP + 0x28,), b"\0" * 4)


def test_find_result_compares_against_refreshed_end_and_index_precedes_find() -> None:
    p = Probe()
    p.tasks(transform(p))

    def find(args: tuple[int, ...], data: memoryview | None) -> int:
        p.put(GROUP + 0x68, 8, CLASSES + 4)
        return CLASSES

    p.hooks[0x142D6A0D0] = find
    p.run()
    assert p.get(GROUP + 0x68, 8) == CLASSES + 4
    ids = [c[0] for c in p.calls]
    assert ids.index(0x1412A57E0) < ids.index(0x142D6A0D0)


def test_returned_lookup_slots_are_dereferenced_and_owner_class_decoded() -> None:
    p = Probe()
    p.tasks(transform(p, f10=-1, f12=4))
    p.run()
    assert p.matching(0x1412A4220)[0][1] == (GROUP + 0x20,)
    assert p.get(CLASSES, 4) == 7
    assert p.get(RULES, 4) == 4
    assert ("read", GROUP_SLOT, 8) in p.events and ("read", SUBGROUP_SLOT, 8) in p.events


@pytest.mark.parametrize("owner", [0, OWNER])
def test_missing_owner_or_slot_drops_regular_rule(owner: int) -> None:
    p = Probe()
    p.put(SUBJECT + 0x18, 8, owner)
    p.tasks(transform(p, f10=-1, f12=5))
    p.run()
    assert not p.matching(0x1412A4560)


@pytest.mark.parametrize(
    ("bit", "expected", "literals"),
    [
        (0, [50, 6, 28, 45, 46, 56, 9, 10, 29, 58, 61, 35], [0x1432B8254]),
        (1, [12, 47, 57, 24], []),
        (2, [0, 44], []),
        (3, [36, 23], []),
        (4, [18, 43, 17], []),
        (5, [4, 19, 59], [0x1432B8258]),
        (6, [20, 21, 22, 2, 53], []),
        (7, [13, 54, 55], [0x1432B8260, 0x1432B8250]),
        (8, [3, 27, 39, 49, 52, 60], [0x1432B825C]),
    ],
)
def test_class_mask_full_order_and_distinct_literal_helpers(
    bit: int, expected: list[int], literals: list[int]
) -> None:
    p = Probe()
    p.mask = 1 << bit
    p.tasks(transform(p, f10=1000))
    p.run()
    stack_calls = p.matching(0x1412A57E0)[1:]
    assert [int.from_bytes(c[2] or b"", "little") for c in stack_calls] == expected
    assert [c[1][1] for c in p.matching(0x1412A56C0)] == literals
    assert p.matching(0x141320720) == [(0x141320720, (MASTER, 1000), None)]


def test_regular_class_growth_allocates_copies_then_commits() -> None:
    p = Probe()
    p.vector(GROUP + 0x60, CLASSES, CLASSES + 8, CLASSES + 8)
    p.put(CLASSES, 8, 0x1122334455667788)
    p.tasks(transform(p))
    p.run()
    assert p.matching(0x1402A94D0) == [(0x1402A94D0, (12,), None)]
    assert p.raw(NEW, 12) == bytes.fromhex("887766554433221104000000")
    assert p.matching(0x1402BA840) == [(0x1402BA840, (GROUP + 0x60, NEW, 3, 3), None)]
    assert p.get(GROUP + 0x60, 8) == NEW


def test_growth_reloads_vectors_after_allocator_and_splits_moves() -> None:
    p = Probe()
    p.vector(GROUP + 0x60, CLASSES, CLASSES + 4, CLASSES + 4)
    p.put(CLASSES, 8, 0x1122334455667788)
    p.tasks(transform(p))

    def allocate(args: tuple[int, ...], data: memoryview | None) -> int:
        p.put(GROUP + 0x68, 8, CLASSES + 8)
        return NEW

    p.hooks[0x1402A94D0] = allocate
    p.run()
    assert [c[1] for c in p.matching(0x142D6E3DB)] == [(NEW, CLASSES, 4), (NEW + 8, CLASSES + 4, 4)]
    assert p.raw(NEW, 12) == bytes.fromhex("887766550400000044332211")


def test_transform_capacity_helper_gets_shared40_bytes() -> None:
    p = Probe()
    p.put(SUBJECT + 0x740, 8, RULES)
    p.tasks(transform(p))
    p.run()
    call = p.matching(0x1412A3CA0)[0]
    assert call[1] == (SUBJECT + 0x730, RULES)
    assert len(call[2] or b"") == 40
    assert p.get(SUBJECT + 0x738, 8) == RULES


def test_failure_retains_prior_scalar_writes_and_does_not_append_rule() -> None:
    p = Probe()
    p.tasks(transform(p, f60=5))

    def unavailable(args: tuple[int, ...], data: memoryview | None) -> None:
        raise UnresolvedReplayTaskRebuild("actual map helper unavailable")

    p.hooks[0x1412A4560] = unavailable
    with pytest.raises(UnresolvedReplayTaskRebuild, match="map helper"):
        p.run()
    assert p.get(SUBJECT + 0x750, 4) == 5
    assert p.get(SUBJECT + 0x738, 8) == RULES


def test_rebuilt_health_rows_feed_actual_health_gate() -> None:
    p = Probe()
    p.tasks(p.task(0, 158, {0x22: (2, -1), 0x24: (2, -1), 0x2C: (4, 0x42C80000)}))
    p.put(SUBJECT + 0x130, 8, ((0x42480000 + 0x147B5E081EC087D9) & U64) ^ 0x0F2A55F7A61DD00E)
    p.run()
    before = p.raw(HEALTH, 48)
    run_replay_health_transforms(
        ReplayHealthTransformStorage(SUBJECT, p.read),
        mxcsr=0x1F80,
        callbacks=ReplayHealthTransformCallbacks(None, None, None, None, None, None),
    )
    assert p.raw(HEALTH, 48) == before
    assert ("read", SUBJECT + 0x130, 8) in p.events


def test_unavailable_dispatch_fails_at_unconditional_prefix() -> None:
    p = Probe()
    with pytest.raises(UnresolvedReplayTaskRebuild, match="14114bf70"):
        run_replay_task_rebuild(
            ReplayTaskRebuildStorage(SUBJECT, p.read, p.write),
            0,
            mxcsr=0x1F80,
            scratch=SCRATCH,
            calls=ReplayTaskRebuildCalls(None),
        )
    assert p.events == []


@pytest.mark.parametrize("mxcsr", [0, 0x1F00, 0x3F80, 0x1FC0, 0x9F80, True, -1])
def test_mxcsr_admission_precedes_native_effects(mxcsr: int) -> None:
    p = Probe()
    with pytest.raises(ValueError):
        run_replay_task_rebuild(
            ReplayTaskRebuildStorage(SUBJECT, p.read, p.write),
            LIST,
            mxcsr=mxcsr,
            scratch=SCRATCH,
            calls=ReplayTaskRebuildCalls(p.call),
        )
    assert p.events == []


@pytest.mark.parametrize(
    ("descriptor", "group", "criterion"),
    [
        (b"", b"abc", b"def"),
        (SEED, b"", b"def"),
        (SEED, b"abc", b""),
    ],
)
def test_scratch_requires_all_explicit_bytes(
    descriptor: bytes,
    group: bytes,
    criterion: bytes,
) -> None:
    with pytest.raises(ValueError):
        ReplayTaskRebuildScratch(descriptor, group, criterion)
