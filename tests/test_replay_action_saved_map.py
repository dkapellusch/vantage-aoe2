"""Owned Action-map construction, mutation, collision and actual rehash effects."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from vantage.replay_action_saved_map import (
    bind_replay_action_saved_map,
    lookup_replay_action_saved_map,
    rehash_replay_action_saved_map,
)
from vantage.replay_memory import ReplayMemory, ReplayMemoryError, ReplayMemoryRuntimeError
from vantage.replay_task_containers import (
    ReplayTaskContainerCalls,
    UnresolvedReplayTaskContainer,
)
from vantage.replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
)
from vantage.replay_unit_ai_vector_growth import bind_replay_unit_ai_vector_growth
from vantage.replay_unit_constructor_maps import (
    bind_replay_unit_constructor_maps,
    construct_replay_unit_map,
)

_CEIL = 0xEA1101
_LENGTH = 0xEA1102
_MASK = (1 << 64) - 1


class Harness:
    def __init__(self) -> None:
        self.memory = ReplayMemory()
        self.header = self.memory.allocate(0x50)
        self.output = self.memory.allocate(16)
        self.key = self.memory.allocate(4)
        self.memory.write_bytes(self.header, b"\xa5" * 0x50)
        self.memory.write_bytes(self.output, b"\xa3" * 16)
        self.memory.map_bytes(0x143199DD0, (0x142D6BAB4).to_bytes(8, "little"))
        self.memory.map_bytes(0x143199EF0, _CEIL.to_bytes(8, "little"))
        self.memory.map_bytes(0x1431992A0, _LENGTH.to_bytes(8, "little"))
        self.memory.map_bytes(0x1436A0308, bytes.fromhex("0000005f"))
        self.trace: list[tuple[str, int, int, int]] = []
        self.calls: list[tuple[int, tuple[int, ...]]] = []
        self.after_read: Callable[[int, int, int], None] | None = None
        self.after_write: Callable[[int, int, int], None] | None = None
        self.after_call: Callable[[int, tuple[int, ...], int | None], None] | None = None
        self.context = ReplayTaskRebuildStorage(self.header, self.read, self.write)
        runtime = self.memory.runtime_calls()

        def terminal(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
            self.calls.append((target, args))
            assert runtime.call is not None
            result = runtime.call(
                0x142D6E453 if target == _CEIL else 0x142D66698 if target == _LENGTH else target,
                args,
                data,
            )
            if self.after_call is not None:
                self.after_call(target, args, result)
            return result

        lower = ReplayTaskRebuildCalls(terminal)
        lower = bind_replay_unit_ai_vector_growth(self.context, lower, imports=lower)
        lower = bind_replay_unit_constructor_maps(
            self.context, lower, bind_local=self.memory.bind_local
        )
        self.bound = bind_replay_action_saved_map(self.context, lower, mxcsr=0x1F80)
        self.container = ReplayTaskContainerCalls(self.bound.call, 0x1F80)
        construct_replay_unit_map(self.context, 0x141136CA0, self.header, calls=self.bound)
        self.trace.clear()
        self.calls.clear()

    def read(self, address: int, width: int) -> int:
        value = self.memory.read(address, width)
        self.trace.append(("read", address, width, value))
        if self.after_read is not None:
            self.after_read(address, width, value)
        return value

    def write(self, address: int, width: int, value: int) -> None:
        self.memory.write(address, width, value)
        self.trace.append(("write", address, width, value))
        if self.after_write is not None:
            self.after_write(address, width, value)

    def insert(self, key: int, *, direct: bool = False) -> tuple[int, bool]:
        self.memory.write(self.key, 4, key)
        result: int | None
        if direct:
            result = lookup_replay_action_saved_map(
                self.context, self.header, self.output, self.key, calls=self.container
            )
        else:
            assert self.bound.call is not None
            result = self.bound.call(0x1411369A0, (self.header, self.output, self.key), None)
        assert result == self.output
        assert self.memory.read_bytes(self.output + 9, 7) == b"\xa3" * 7
        return self.memory.read(self.output, 8), bool(self.memory.read(self.output + 8, 1))

    def rehash(self, requested: int, *, direct: bool = False) -> None:
        if direct:
            rehash_replay_action_saved_map(
                self.context, self.header, requested, calls=self.container
            )
        else:
            assert self.bound.call is not None
            self.bound.call(0x14113A430, (self.header, requested), None)

    def nodes(self) -> list[int]:
        sentinel = self.memory.read(self.header + 8, 8)
        node = self.memory.read(sentinel, 8)
        result = []
        while node != sentinel:
            assert node not in result
            result.append(node)
            following = self.memory.read(node, 8)
            assert self.memory.read(following + 8, 8) == node
            node = following
        assert len(result) == self.memory.read(self.header + 0x10, 8)
        return result


def _bucket(key: int, mask: int) -> int:
    # Independent FNV-1a recipe from the original four byte-load instructions.
    value = 14695981039346656037
    for byte in key.to_bytes(4, "little"):
        value = (value ^ byte) * 1099511628211 % (1 << 64)
    return value & mask


@pytest.mark.parametrize("direct", [False, True])
@pytest.mark.parametrize("key", [0, 1, 0xFFFFFFFF, 0x80000000, 0x01020304])
def test_real_constructor_lookup_and_duplicate_preserve_existing_raw_payload(
    direct: bool,
    key: int,
) -> None:
    case = Harness()
    node, inserted = case.insert(key, direct=direct)
    assert inserted and case.memory.read(node + 0x10, 4) == key
    assert case.memory.read(node + 0x14, 4) == 0
    case.memory.write(node + 0x14, 4, 0x7FC12345)
    before_calls = list(case.calls)
    assert case.insert(key, direct=direct) == (node, False)
    assert case.calls == before_calls
    assert case.memory.read(node + 0x14, 4) == 0x7FC12345
    assert case.nodes() == [node]
    # Only four key bytes exist. Native C's wider local is not an eight-byte key.
    with pytest.raises(ReplayMemoryError, match="unmapped"):
        case.memory.read(case.key, 8)


@pytest.mark.parametrize("count", [2, 8, 9, 17, 70])
def test_collision_growth_and_rehash_keep_all_keys_and_values(count: int) -> None:
    case = Harness()
    nodes = {}
    # Deliberate low-mask collisions, followed by actual growth/rehash.
    keys = [value for value in range(4096) if _bucket(value, 7) == 3][:count]
    for index, key in enumerate(keys):
        node, inserted = case.insert(key)
        assert inserted
        case.memory.write(node + 0x14, 4, 0x3F800000 + index)
        nodes[key] = node
    assert set(case.nodes()) == set(nodes.values())
    for index, key in enumerate(keys):
        assert case.insert(key) == (nodes[key], False)
        assert case.memory.read(nodes[key] + 0x14, 4) == 0x3F800000 + index
    buckets = case.memory.read(case.header + 0x38, 8)
    assert buckets == (8 if count <= 8 else 64 if count <= 64 else 512)
    assert case.memory.read(case.header + 0x30, 8) == buckets - 1
    assert any(target == _CEIL for target, _ in case.calls) == (count > 8)
    snapshot = case.memory.snapshot()
    assert ReplayMemory.from_snapshot(snapshot).snapshot() == snapshot


@pytest.mark.parametrize("direct", [False, True])
@pytest.mark.parametrize("requested,expected", [(0, 1), (1, 2), (2, 2), (3, 4), (8, 8), (9, 16)])
def test_rehash_uses_actual_storage_and_source_masked_shift_rounding(
    direct: bool,
    requested: int,
    expected: int,
) -> None:
    case = Harness()
    old_begin = case.memory.read(case.header + 0x18, 8)
    case.rehash(requested, direct=direct)
    assert case.memory.read(case.header + 0x38, 8) == expected
    assert case.memory.read(case.header + 0x30, 8) == expected - 1
    begin, end = (case.memory.read(case.header + offset, 8) for offset in (24, 32))
    sentinel = case.memory.read(case.header + 8, 8)
    # Reuse fills the whole current storage, retaining its original extent.
    assert begin == old_begin if expected <= 8 else begin != old_begin
    assert end - begin == max(16, expected * 2) * 8
    assert {case.memory.read(at, 8) for at in range(begin, end, 8)} == {sentinel}


def test_duplicate_shortcut_does_not_read_count_or_float_state() -> None:
    case = Harness()
    node, _ = case.insert(23)

    def forbid(address: int, width: int, value: int) -> None:
        assert address not in (case.header, case.header + 0x10, case.header + 0x38)

    case.after_read = forbid
    assert case.insert(23) == (node, False)


def test_allocator_mutation_changes_copied_key_but_keeps_preallocation_hash() -> None:
    case = Harness()
    old_key, new_key = 10, 11
    assert _bucket(old_key, 7) != _bucket(new_key, 7)

    def mutate(target: int, args: tuple[int, ...], result: int | None) -> None:
        if target == 0x142D6BA78:
            assert args == (24,)
            case.memory.write(case.key, 4, new_key)

    case.after_call = mutate
    node, _ = case.insert(old_key)
    assert case.memory.read(node + 0x10, 4) == new_key
    buckets = case.memory.read(case.header + 0x18, 8)
    assert case.memory.read(buckets + 16 * _bucket(old_key, 7), 8) == node
    sentinel = case.memory.read(case.header + 8, 8)
    assert case.memory.read(buckets + 16 * _bucket(new_key, 7), 8) == sentinel


@pytest.mark.parametrize("load", [0x7FC12345, 0x7F800000, 0x80000000])
def test_float_compare_preserves_unordered_and_infinite_skip_paths(load: int) -> None:
    case = Harness()
    case.memory.write(case.header, 4, load)
    if load == 0x80000000:
        # Negative zero reaches ceil(-infinity), conversion, then the real
        # excessive-bucket error. It cannot promise a completed insertion.
        with pytest.raises(ReplayMemoryRuntimeError) as error:
            case.insert(33)
        assert error.value.args_words == (0x143682938,)
        assert case.memory.read(case.header + 0x10, 8) == 0
    else:
        node, inserted = case.insert(33)
        assert inserted and case.memory.read(node + 0x14, 4) == 0
    assert any(target == _CEIL for target, _ in case.calls) == (load == 0x80000000)


def test_initial_four_hash_bytes_are_read_in_order_then_held_search_key() -> None:
    case = Harness()
    case.insert(0x01020304)
    case.trace.clear()
    case.insert(0x01020304)
    reads = [(address, width) for mode, address, width, _ in case.trace if mode == "read"]
    assert reads[:4] == [(case.key + n, 1) for n in range(4)]
    assert reads[4:9] == [
        (case.header + 0x30, 8),
        (case.header + 0x18, 8),
        (case.memory.read(case.header + 0x18, 8) + _bucket(0x01020304, 7) * 16 + 8, 8),
        (case.header + 8, 8),
        (case.memory.read(case.header + 0x18, 8) + _bucket(0x01020304, 7) * 16, 8),
    ]
    assert reads[9] == (case.key, 4)


def test_rehash_hash_reads_byte1_byte0_next_byte2_byte3() -> None:
    case = Harness()
    node, _ = case.insert(0x01020304)
    case.trace.clear()
    case.rehash(8)
    reads = [(address, width) for mode, address, width, _ in case.trace if mode == "read"]
    index = reads.index((node + 0x11, 1))
    assert reads[index : index + 5] == [
        (node + 0x11, 1),
        (node + 0x10, 1),
        (node, 8),
        (node + 0x12, 1),
        (node + 0x13, 1),
    ]


def test_rehash_holds_initial_sentinel_but_reloads_current_header_after_initializer() -> None:
    case = Harness()
    held = case.memory.read(case.header + 8, 8)
    replacement = case.memory.allocate(24)
    case.memory.write(replacement, 8, held)

    def mutate(address: int, width: int, value: int) -> None:
        if (address, width) == (case.header + 0x38, 8):
            case.memory.write(case.header + 8, 8, replacement)

    case.after_write = mutate
    case.rehash(8)
    assert case.memory.read(case.header + 8, 8) == replacement
    assert case.memory.read(case.memory.read(case.header + 0x18, 8), 8) == held


@pytest.mark.parametrize(
    "entry,args,message",
    [
        (0x1411369A0, (), "malformed"),
        (0x14113A430, (1,), "malformed"),
        (0x142D6E453, (), "malformed"),
        (0x142D66698, (), "malformed"),
    ],
)
def test_known_arity_rejected_before_effects(
    entry: int,
    args: tuple[int, ...],
    message: str,
) -> None:
    case = Harness()
    before = case.memory.snapshot()
    assert case.bound.call is not None
    with pytest.raises(ValueError, match=message):
        case.bound.call(entry, args, None)
    assert case.memory.snapshot() == before


@pytest.mark.parametrize("requested", [1 << 59 | 1, _MASK])
def test_rehash_excess_request_reaches_actual_current_length_error(requested: int) -> None:
    case = Harness()
    before = case.memory.snapshot()
    with pytest.raises(ReplayMemoryRuntimeError) as error:
        case.rehash(requested)
    assert error.value.target == 0x142D66698
    assert error.value.args_words == (0x143682938,)
    assert case.memory.snapshot() == before


def test_exact_count_limit_errors_before_allocation_or_output_writes() -> None:
    case = Harness()
    case.memory.write(case.header + 0x10, 8, 0x0AAAAAAAAAAAAAAA)
    case.memory.write(case.key, 4, 99)
    before = case.memory.snapshot()
    with pytest.raises(ReplayMemoryRuntimeError) as error:
        lookup_replay_action_saved_map(
            case.context, case.header, case.output, case.key, calls=case.container
        )
    assert error.value.args_words == (0x143682918,)
    assert case.memory.snapshot() == before
    assert case.calls == [(_LENGTH, (0x143682918,))]


def test_unbound_allocator_retains_no_map_output_stores() -> None:
    case = Harness()
    case.memory.write(case.key, 4, 99)
    before = case.memory.snapshot()
    with pytest.raises(UnresolvedReplayTaskContainer, match="142d6ba78"):
        lookup_replay_action_saved_map(
            case.context,
            case.header,
            case.output,
            case.key,
            calls=ReplayTaskContainerCalls(None, 0x1F80),
        )
    assert case.memory.snapshot() == before


@pytest.mark.parametrize("requested", [8, 16, 64])
def test_rehash_groups_duplicate_keys_into_contiguous_bucket_runs(requested: int) -> None:
    case = Harness()
    original = [case.insert(key)[0] for key in range(20)]
    # Existing duplicate nodes are explicit current state, not deduplicated.
    for index, node in enumerate(original):
        case.memory.write(node + 0x10, 4, index % 5)
        case.memory.write(node + 0x14, 4, 0x7FC00000 + index)
    case.rehash(requested)
    assert set(case.nodes()) == set(original)
    mask = case.memory.read(case.header + 0x30, 8)
    buckets = case.memory.read(case.header + 0x18, 8)
    sentinel = case.memory.read(case.header + 8, 8)
    for bucket in range(mask + 1):
        first, last = (case.memory.read(buckets + bucket * 16 + offset, 8) for offset in (0, 8))
        expected = {
            node for node in original if _bucket(case.memory.read(node + 0x10, 4), mask) == bucket
        }
        if not expected:
            assert first == last == sentinel
            continue
        seen = set()
        node = first
        while True:
            assert node not in seen
            seen.add(node)
            if node == last:
                break
            node = case.memory.read(node, 8)
        assert seen == expected
    for index, node in enumerate(original):
        assert case.memory.read(node + 0x14, 4) == 0x7FC00000 + index


def test_output_partial_failure_keeps_published_node_and_count() -> None:
    case = Harness()

    def fail(address: int, width: int, value: int) -> None:
        if (address, width) == (case.output, 8):
            raise RuntimeError("OUT pointer published")

    case.after_write = fail
    with pytest.raises(RuntimeError, match="OUT pointer published"):
        case.insert(12)
    node = case.memory.read(case.output, 8)
    assert case.nodes() == [node]
    assert case.memory.read(case.output + 8, 1) == 0xA3


def test_nonreturning_length_target_that_returns_is_guarded() -> None:
    case = Harness()
    case.memory.write(case.header + 0x10, 8, 0x0AAAAAAAAAAAAAAA)
    case.memory.write(case.key, 4, 99)
    seen: list[tuple[int, tuple[int, ...]]] = []

    def returns(target: int, args: tuple[int, ...], data: memoryview | None) -> None:
        assert data is None
        seen.append((target, args))

    bound = bind_replay_action_saved_map(
        case.context, ReplayTaskRebuildCalls(returns), mxcsr=0x1F80
    )
    assert bound.call is not None
    before = case.memory.snapshot()
    with pytest.raises(RuntimeError, match="unexpectedly returned"):
        bound.call(0x1411369A0, (case.header, case.output, case.key), None)
    assert seen == [(_LENGTH, (0x143682918,))]
    assert case.memory.snapshot() == before


def test_ceil_uses_current_IAT_after_node_allocation() -> None:
    case = Harness()
    case.memory.write(case.header, 4, 0)

    def mutate(target: int, args: tuple[int, ...], result: int | None) -> None:
        if target == 0x142D6BA78:
            case.memory.write(0x143199EF0, 8, 0xDEAD)

    case.after_call = mutate
    with pytest.raises(UnresolvedReplayTaskRebuild, match="dead"):
        case.insert(99)
    assert case.calls[-1][0] == 0xDEAD
    assert case.memory.read(case.header + 0x10, 8) == 0


def test_reached_rehash_child_failure_preserves_initialized_unlinked_node() -> None:
    case = Harness()
    case.memory.write(case.header, 4, 0)
    allocated: list[int | None] = []

    def fail(target: int, args: tuple[int, ...], result: int | None) -> None:
        if target == 0x142D6BA78:
            allocated.append(result)
        if target == _CEIL:
            raise RuntimeError("actual ceiling failure")

    case.after_call = fail
    before = case.memory.read_bytes(case.output, 16)
    with pytest.raises(RuntimeError, match="actual ceiling failure"):
        case.insert(99)
    assert len(allocated) == 1 and allocated[0] is not None
    node = allocated[0]
    assert case.memory.read(node + 0x10, 8) == 99
    with pytest.raises(ReplayMemoryError, match="undefined"):
        case.memory.read(node, 16)
    assert case.memory.read(case.header + 0x10, 8) == 0
    assert case.memory.read_bytes(case.output, 16) == before


@pytest.mark.parametrize("mxcsr", [0, 0x9F80, 0x3F80, 0x1FC0, True])
def test_float_profile_validation(mxcsr: int) -> None:
    case = Harness()
    before = case.memory.snapshot()
    with pytest.raises(ValueError):
        bind_replay_action_saved_map(case.context, case.bound, mxcsr=mxcsr)
    assert case.memory.snapshot() == before


def test_unknown_dispatch_preserves_view_and_unbound_target_refuses() -> None:
    case = Harness()
    view = memoryview(bytearray(b"ab"))

    def actual(target: int, args: tuple[int, ...], data: memoryview | None) -> int:
        assert target == 0xDEAD and args == (1, 2) and data is view
        data[0] = 90
        return 9

    bound = bind_replay_action_saved_map(case.context, ReplayTaskRebuildCalls(actual), mxcsr=0x1F80)
    assert bound.call is not None and bound.call(0xDEAD, (1, 2), view) == 9
    assert bytes(view) == b"Zb"
    unbound = bind_replay_action_saved_map(case.context, ReplayTaskRebuildCalls(None), mxcsr=0x1F80)
    assert unbound.call is not None
    with pytest.raises(UnresolvedReplayTaskRebuild):
        unbound.call(0xDEAD, (1, 2), view)
