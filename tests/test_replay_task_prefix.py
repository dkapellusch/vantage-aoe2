"""Prefix scalar/call controls; observer containers do not prove lifecycle effects."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from vantage.replay_task_prefix import (
    ReplayTaskPrefixCalls,
    ReplayTaskPrefixScratch,
    UnresolvedReplayTaskPrefix,
    run_replay_task_prefix,
)
from vantage.replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildScratch,
    ReplayTaskRebuildStorage,
    run_replay_task_rebuild,
)

SUBJECT, LIST, POINTERS, TASK = 0x10000, 0x20000, 0x21000, 0x30000
ROWS, NODE157, NODE162, OUT157, OUT162 = 0x60000, 0x80000, 0x80040, 0x90000, 0x90020
U64 = (1 << 64) - 1
SEED = bytes(range(64))
SCRATCH = ReplayTaskPrefixScratch(SEED, b"abc", b"xyz")
Hook = Callable[[tuple[int, ...], memoryview | None, memoryview | None], int | None]


class Probe:
    def __init__(self) -> None:
        self.memory: dict[int, int] = {}
        self.events: list[tuple[object, ...]] = []
        self.calls: list[tuple[int, tuple[int, ...], bytes | None, bytes | None]] = []
        self.hooks: dict[int, Hook] = {}
        self.inserted157 = self.inserted162 = 1
        for base, size in (
            (SUBJECT, 0x1000),
            (LIST, 0x20),
            (POINTERS, 0x200),
            (TASK, 0x1000),
            (ROWS, 0x1000),
            (NODE157, 0x100),
            (OUT157, 0x40),
        ):
            self.memory.update((base + index, 0) for index in range(size))
        self.put(SUBJECT + 0x530, 8, ROWS)
        self.put(SUBJECT + 0x538, 8, ROWS)
        self.put(SUBJECT + 0x540, 8, ROWS + 0x1000)
        self.put(LIST + 8, 8, POINTERS)
        self.put(LIST + 0x10, 8, POINTERS)
        self.put(0x1432A70C0, 4, 0x08040201)

    def put(self, address: int, width: int, value: int) -> None:
        for index in range(width):
            self.memory[(address + index) & U64] = value >> (index * 8) & 255

    def get(self, address: int, width: int) -> int:
        return sum(self.memory[(address + i) & U64] << (i * 8) for i in range(width))

    def raw(self, address: int, width: int) -> bytes:
        return self.get(address, width).to_bytes(width, "little")

    def read(self, address: int, width: int) -> int:
        self.events.append(("read", address, width))
        return self.get(address, width)

    def write(self, address: int, width: int, value: int) -> None:
        self.events.append(("write", address, width, value))
        self.put(address, width, value)

    @property
    def context(self) -> ReplayTaskRebuildStorage:
        return ReplayTaskRebuildStorage(SUBJECT, self.read, self.write)

    def call(
        self, target: int, args: tuple[int, ...], key: memoryview | None, value: memoryview | None
    ) -> int | None:
        entry = (
            target,
            args,
            bytes(key) if key is not None else None,
            bytes(value) if value is not None else None,
        )
        self.calls.append(entry)
        self.events.append(("call", *entry))
        if target in self.hooks:
            return self.hooks[target](args, key, value)
        if target in (0x1411434C0, 0x141143260):
            out, node, inserted = (
                (OUT157, NODE157, self.inserted157)
                if target == 0x1411434C0
                else (OUT162, NODE162, self.inserted162)
            )
            self.put(out, 8, node)
            self.put(out + 8, 1, inserted)
            return out
        return None

    def task(self, index: int = 0, kind: int = 157, **fields: int) -> int:
        task = TASK + index * 0x100
        self.put(task + 0xE, 2, kind)
        for name, value in fields.items():
            offset = int(name[1:], 16)
            width = {0x10: 2, 0x12: 2, 0x15: 1, 0x19: 1, 0x22: 2, 0x34: 2, 0x36: 2, 0x48: 8}.get(
                offset, 4
            )
            self.put(task + offset, width, value)
        return task

    def tasks(self, *tasks: int) -> None:
        for index, task in enumerate(tasks):
            self.put(POINTERS + index * 8, 8, task)
        self.put(LIST + 0x10, 8, POINTERS + len(tasks) * 8)

    def run(self, task_list: int = LIST) -> None:
        run_replay_task_prefix(
            self.context,
            task_list,
            mxcsr=0x1F80,
            scratch=SCRATCH,
            calls=ReplayTaskPrefixCalls(self.call),
        )

    def matching(
        self,
        target: int,
    ) -> list[tuple[int, tuple[int, ...], bytes | None, bytes | None]]:
        return [entry for entry in self.calls if entry[0] == target]


def test_null_list_still_clears_vector_maps_and_marker_in_order() -> None:
    p = Probe()
    p.put(SUBJECT + 0x538, 8, ROWS + 64)
    p.put(SUBJECT + 0x588, 8, 0x1122334455667788)
    p.run(0)
    assert p.get(SUBJECT + 0x538, 8) == ROWS
    assert p.get(SUBJECT + 0x588, 8) == 0x1122330055667788
    assert [c[0] for c in p.calls] == [0x1411510F0, 0x141151180]
    assert p.events[-1] == ("write", SUBJECT + 0x58C, 1, 0)


def test_empty_list_entry_reads_end_before_begin() -> None:
    p = Probe()
    p.run()
    assert p.events[-2:] == [("read", LIST + 0x10, 8), ("read", LIST + 8, 8)]
    assert not [e for e in p.events if e[0] == "write" and e[1] == SUBJECT + 0x538]


def test_clear_failure_preserves_vector_clear_without_clearing_marker() -> None:
    p = Probe()
    p.put(SUBJECT + 0x538, 8, ROWS + 64)
    p.put(SUBJECT + 0x58C, 1, 9)

    def fail(args: tuple[int, ...], key: memoryview | None, value: memoryview | None) -> None:
        raise UnresolvedReplayTaskPrefix("actual map clear unavailable")

    p.hooks[0x141151180] = fail
    with pytest.raises(UnresolvedReplayTaskPrefix):
        p.run(0)
    assert p.get(SUBJECT + 0x538, 8) == ROWS
    assert p.get(SUBJECT + 0x58C, 1) == 9


def test_complete157_layout_signed_raw_fields_and_padding() -> None:
    p = Probe()
    p.tasks(
        p.task(
            f10=4,
            f22=-1,
            f1c=0x40200000,
            f28=0x7F812345,
            f2c=0xBFE00000,
            f30=0x80000000,
            f15=255,
            f60=0xDEADBEEF,
            f78=0x12345678,
            f34=-5,
            f48=0x0123456789ABCDEF,
            f36=-2,
            f19=128,
        )
    )
    p.run()
    expected = bytearray(SEED)
    for offset, width, value in (
        (0, 4, 904),
        (4, 4, 0xFFFFFFFF),
        (8, 4, 2),
        (12, 4, 0x7F812345),
        (16, 4, 0xFFFFFFFF),
        (20, 1, 1),
        (24, 4, 255),
        (28, 4, 0xDEADBEEF),
        (32, 4, 0x12345678),
        (36, 4, 0xFFFFFFFB),
        (40, 8, 0x0123456789ABCDEF),
        (48, 4, 0xFFFFFFFE),
        (52, 4, 128),
        (56, 1, 0),
    ):
        expected[offset : offset + width] = value.to_bytes(width, "little")
    assert p.raw(ROWS, 64) == bytes(expected)
    assert p.get(SUBJECT + 0x538, 8) == ROWS + 64
    assert not p.matching(0x1411434C0)


@pytest.mark.parametrize(
    ("selected", "alternate", "expected", "mode"),
    [
        (-1000, 4, -1000, 1),
        (-999, 4, 4, 0),
        (-1, -2, -1, 0),
        (-1, 0, 0, 0),
        (0, -1, 900, 0),
        (999, -1, 1899, 0),
        (1000, -1, 1000, 1),
    ],
)
def test157_selector_modes_use_concrete_arithmetic_leaf(
    selected: int, alternate: int, expected: int, mode: int
) -> None:
    p = Probe()
    p.tasks(p.task(f10=selected, f12=alternate))
    p.run()
    assert p.get(ROWS, 4) == expected & 0xFFFFFFFF and p.get(ROWS + 56, 1) == mode
    assert not p.matching(0x1410B9F00)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (0, 1),
        (0x80000000, 1),
        (1, 0),
        (0xBF800000, 0),
        (0x7F812345, 0),
        (0x7FC12345, 0),
    ],
)
def test157_zero_flag_is_ordered_equality(raw: int, expected: int) -> None:
    p = Probe()
    p.tasks(p.task(f30=raw))
    p.run()
    assert p.get(ROWS + 20, 1) == expected


@pytest.mark.parametrize(
    ("raw", "converted"),
    [
        (0, 0),
        (0x80000000, 0),
        (0x3FC00000, 1),
        (0xBFC00000, 0xFFFFFFFF),
        (0x4F000000, 0x80000000),
        (0x7F800000, 0x80000000),
        (0x7F812345, 0x80000000),
    ],
)
def test157_both_cvtt_words(raw: int, converted: int) -> None:
    p = Probe()
    p.tasks(p.task(f1c=raw, f2c=raw))
    p.run()
    assert p.get(ROWS + 8, 4) == converted and p.get(ROWS + 16, 4) == converted


@pytest.mark.parametrize(
    ("new", "old", "inserted", "expected"),
    [
        (3, 2, 0, 3),
        (2, 3, 0, 3),
        (2, 2, 0, 2),
        (3, 2, 1, 2),
    ],
)
def test157_lookup_hit_keeps_largest_signed_count(
    new: int, old: int, inserted: int, expected: int
) -> None:
    p = Probe()
    p.inserted157 = inserted
    p.put(NODE157 + 0x18, 4, old)
    p.tasks(p.task(f36=new, f19=8, f1c=0x41400000))
    p.run()
    assert p.get(NODE157 + 0x18, 4) == expected
    assert p.matching(0x1411434C0)[0][2:] == (
        bytes.fromhex("080000000c000000"),
        new.to_bytes(4, "little"),
    )
    i = p.events.index(("read", OUT157 + 8, 1))
    if not inserted:
        assert p.events[i + 1] == ("read", OUT157, 8)


def test157_mutable_count_input_affects_metadata_rounding_and_appended_row() -> None:
    p = Probe()
    p.tasks(p.task(f36=1, f1c=0x41200000, f28=0x3F800000))

    def lookup(args: tuple[int, ...], key: memoryview | None, value: memoryview | None) -> int:
        assert key is not None and value is not None
        key[4:8] = (99).to_bytes(4, "little")  # Copied key does not change descriptor+8.
        value[:] = (16777219).to_bytes(4, "little")
        p.put(OUT157 + 8, 1, 1)
        return OUT157

    p.hooks[0x1411434C0] = lookup
    p.run()
    assert p.get(ROWS + 48, 4) == 16777219 and p.get(ROWS + 8, 4) == 10
    assert p.get(SUBJECT + 0x588, 8) == int.from_bytes(bytes.fromhex("0200804b01616263"), "little")


def test157_original_positive_gate_survives_mutation_to_negative_count() -> None:
    p = Probe()
    p.tasks(p.task(f36=1, f1c=0x41200000, f28=0x40000000))

    def lookup(args: tuple[int, ...], key: memoryview | None, value: memoryview | None) -> int:
        assert value is not None
        value[:] = (0xFFFFFFFF).to_bytes(4, "little")
        p.put(OUT157 + 8, 1, 1)
        return OUT157

    p.hooks[0x1411434C0] = lookup
    p.run()
    assert p.get(SUBJECT + 0x588, 4) == 0xC0000000
    assert p.get(ROWS + 48, 4) == 0xFFFFFFFF


@pytest.mark.parametrize(
    ("current", "amount", "expected"),
    [
        (0x80000000, 0, 0x80000000),
        (0, 0x80000000, 0),
        (0x7F812345, 0x3F800000, 0x7F812345),
        (0x7FC12345, 0x3F800000, 0x7FC12345),
        (0x40000000, 0x7F812345, 0x40000000),
        (0x40000000, 0x3F800000, 0x40000000),
        (0xBF800000, 0x3F800000, 0x3F800000),
    ],
)
def test157_maxss_current_source_wins_equal_or_unordered(
    current: int, amount: int, expected: int
) -> None:
    p = Probe()
    p.tasks(p.task(f36=1, f1c=0x41200000, f28=amount))

    def lookup(args: tuple[int, ...], key: memoryview | None, value: memoryview | None) -> int:
        p.put(SUBJECT + 0x588, 4, current)
        p.put(SUBJECT + 0x58C, 1, 1)
        p.put(OUT157 + 8, 1, 1)
        return OUT157

    p.hooks[0x1411434C0] = lookup
    p.run()
    assert p.get(SUBJECT + 0x588, 4) == expected
    assert p.raw(SUBJECT + 0x58C, 4) == b"\x01xyz"


def test157_growth_view_mutations_persist_into_later_descriptor_padding() -> None:
    p = Probe()
    p.put(SUBJECT + 0x540, 8, ROWS)
    p.tasks(p.task(), p.task(1))

    def append(args: tuple[int, ...], key: memoryview | None, value: memoryview | None) -> None:
        assert key is not None and len(key) == 64 and value is None
        key[21] = 221
        key[63] = 222
        p.put(SUBJECT + 0x540, 8, ROWS + 128)

    p.hooks[0x141143090] = append
    p.run()
    assert p.get(ROWS + 21, 1) == 221 and p.get(ROWS + 63, 1) == 222
    assert p.get(SUBJECT + 0x538, 8) == ROWS + 64


@pytest.mark.parametrize(
    ("score", "expected_calls"),
    [
        (0, 4),
        (0x80000000, 4),
        (0x3F800000, 4),
        (0x7F800000, 4),
        (0xBF800000, 0),
        (0xFF800000, 0),
        (0x7F812345, 4),
        (0xFFC12345, 4),
    ],
)
def test162_first_gate_admits_unordered_scores(score: int, expected_calls: int) -> None:
    p = Probe()
    p.tasks(p.task(kind=162, f28=score))
    p.run()
    assert len(p.matching(0x141143260)) == expected_calls
    assert p.events.count(("read", TASK + 0x15, 1)) == 4
    assert p.events.count(("read", TASK + 0x28, 4)) == 4


@pytest.mark.parametrize(
    ("flags", "keys"), [(0, [1, 2, 4, 8]), (1, [1]), (5, [1, 4]), (128, []), (255, [1, 2, 4, 8])]
)
def test162_flags_select_current_literal_keys(flags: int, keys: list[int]) -> None:
    p = Probe()
    p.tasks(p.task(kind=162, f15=flags))
    p.run()
    assert [int.from_bytes(c[2] or b"", "little") for c in p.matching(0x141143260)] == keys


@pytest.mark.parametrize(
    ("old", "new", "replace"),
    [
        (0x40000000, 0x3F800000, True),
        (0x3F800000, 0x40000000, False),
        (0, 0x80000000, False),
        (0x7F812345, 0x3F800000, False),
        (0x40000000, 0x7F812345, False),
    ],
)
def test162_only_ordered_strictly_smaller_score_replaces(old: int, new: int, replace: bool) -> None:
    p = Probe()
    p.inserted162 = 0
    old_task = p.task(1, 0, f28=old)
    current = p.task(kind=162, f15=1, f28=new)
    p.put(NODE162 + 0x18, 8, old_task)
    p.tasks(current)
    p.run()
    assert p.get(NODE162 + 0x18, 8) == (current if replace else old_task)


def test162_null_old_task_uses_concrete_minus_one_without_reading_null() -> None:
    p = Probe()
    p.inserted162 = 0
    p.tasks(p.task(kind=162, f15=1, f28=0))
    p.run()
    assert p.get(NODE162 + 0x18, 8) == 0
    assert not [e for e in p.events if e[0] == "read" and e[1] == 0x28]


def test162_mutable_task_value_and_current_getter_rereads() -> None:
    p = Probe()
    old_task = p.task(1, 0, f28=0x40000000)
    replacement = p.task(2, 0)
    current = p.task(kind=162, f28=0x3F800000)
    p.tasks(current)

    def lookup(args: tuple[int, ...], key: memoryview | None, value: memoryview | None) -> int:
        assert value is not None
        value[:] = replacement.to_bytes(8, "little")
        p.put(OUT162, 8, NODE162)
        p.put(OUT162 + 8, 1, 0)
        p.put(NODE162 + 0x18, 8, old_task)
        p.put(current + 0x28, 4, 0xBF800000)  # Remaining three iterations skip.
        return OUT162

    p.hooks[0x141143260] = lookup
    p.run()
    assert p.get(NODE162 + 0x18, 8) == replacement
    assert len(p.matching(0x141143260)) == 1
    assert p.events.count(("read", current + 0x28, 4)) == 4


def test_dynamic_list_growth_and_null_unknown_tasks() -> None:
    p = Probe()
    first, second = p.task(f36=1), p.task(1, f10=5)
    p.tasks(0, first)

    def lookup(args: tuple[int, ...], key: memoryview | None, value: memoryview | None) -> int:
        p.put(LIST + 0x10, 8, POINTERS + 32)
        p.put(POINTERS + 16, 8, p.task(2, 3))
        p.put(POINTERS + 24, 8, second)
        p.put(OUT157 + 8, 1, 1)
        return OUT157

    p.hooks[0x1411434C0] = lookup
    p.run()
    assert p.get(SUBJECT + 0x538, 8) == ROWS + 128
    assert p.get(ROWS + 64, 4) == 905


def test_real_prefix_binds_into_outer_rebuild() -> None:
    p = Probe()
    p.tasks(p.task(), p.task(1, 158, f22=-1, f28=0x3F800000))
    for member, value in (
        (0x730, ROWS + 0x400),
        (0x738, ROWS + 0x400),
        (0x740, ROWS + 0x800),
        (0x7A8, ROWS + 0x800),
        (0x7B0, ROWS + 0x800),
        (0x7B8, ROWS + 0xC00),
    ):
        p.put(SUBJECT + member, 8, value)

    def outer(target: int, args: tuple[int, ...], data: memoryview | None) -> None:
        if target == 0x14114BF70:
            assert args == (SUBJECT, LIST)
            p.run(args[1])
        else:
            assert target == 0x1412C5270

    run_replay_task_rebuild(
        p.context,
        LIST,
        mxcsr=0x1F80,
        scratch=ReplayTaskRebuildScratch(bytes(48), b"abc", b"def"),
        calls=ReplayTaskRebuildCalls(outer),
    )
    assert p.get(SUBJECT + 0x538, 8) == ROWS + 64
    assert p.get(SUBJECT + 0x7B0, 8) == ROWS + 0x800 + 48
    assert p.get(ROWS + 0x800, 4) == 1


@pytest.mark.parametrize("mxcsr", [0, 0x1F00, 0x3F80, 0x1FC0, 0x9F80, True])
def test_invalid_mxcsr_has_no_effects(mxcsr: int) -> None:
    p = Probe()
    with pytest.raises(ValueError):
        run_replay_task_prefix(
            p.context, LIST, mxcsr=mxcsr, scratch=SCRATCH, calls=ReplayTaskPrefixCalls(p.call)
        )
    assert not p.events


def test_unavailable_dispatch_retains_earlier_vector_clear() -> None:
    p = Probe()
    p.put(SUBJECT + 0x538, 8, ROWS + 64)
    with pytest.raises(UnresolvedReplayTaskPrefix, match="1411510f0"):
        run_replay_task_prefix(
            p.context, LIST, mxcsr=0x1F80, scratch=SCRATCH, calls=ReplayTaskPrefixCalls(None)
        )
    assert p.get(SUBJECT + 0x538, 8) == ROWS


@pytest.mark.parametrize(
    ("descriptor", "first", "maximum"),
    [
        (b"", b"abc", b"def"),
        (SEED, b"", b"def"),
        (SEED, b"abc", b""),
    ],
)
def test_explicit_scratch_sizes(descriptor: bytes, first: bytes, maximum: bytes) -> None:
    with pytest.raises(ValueError):
        ReplayTaskPrefixScratch(descriptor, first, maximum)
