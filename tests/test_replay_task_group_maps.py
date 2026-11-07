"""Task map identity, real growth/free, current thunks and partial effects."""

from __future__ import annotations

import struct
from dataclasses import dataclass

import pytest

from vantage.replay_memory import ReplayMemory, ReplayMemoryError, ReplayMemoryRuntimeError
from vantage.replay_task_containers import ReplayTaskContainerCalls
from vantage.replay_task_effects import bind_replay_task_execution
from vantage.replay_task_group_maps import (
    bind_replay_task_group_maps,
    call_replay_task_group_ceil,
    call_replay_task_group_length,
    hash_replay_task_group_float,
)
from vantage.replay_task_prefix import ReplayTaskPrefixScratch
from vantage.replay_task_rebuild import ReplayTaskRebuildCalls, ReplayTaskRebuildStorage

CEIL_SLOT, LENGTH_SLOT = 0x143199EF0, 0x1431992A0
CEIL, LENGTH = 0x7FF010001000, 0x7FF020002000


def zero(memory: ReplayMemory, size: int) -> int:
    address = memory.allocate(size)
    memory.write_bytes(address, bytes(size))
    return address


def key(group: bool, *, value: int = 0x3F800000, integer: int = 3, padding: int = 0xA5) -> bytes:
    return (
        struct.pack("<IIB3B", value, integer, 2, padding, padding, padding)
        if group
        else struct.pack("<B3BIIIQ", 2, padding, padding, padding, integer, value, 0x40000000, 4)
    )


def runtime(memory: ReplayMemory) -> ReplayTaskRebuildCalls:
    actual = memory.runtime_calls()

    def call(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        assert actual.call is not None
        # Declared logical runtime identities; actual arithmetic/error effects,
        # separate from proving a native DLL/heap identity.
        if target == CEIL:
            return actual.call(0x142D6E453, args, data)
        if target == LENGTH:
            return actual.call(0x142D66698, args, data)
        return actual.call(target, args, data)

    return ReplayTaskRebuildCalls(call)


@dataclass
class Fixture:
    memory: ReplayMemory
    group: bool
    header: int
    head: int
    out: int
    other_out: int
    key_address: int
    context: ReplayTaskRebuildStorage
    calls: ReplayTaskRebuildCalls

    @property
    def entry(self) -> int:
        return 0x1412A4560 if self.group else 0x1412A4220

    def invoke(self, target: int, args: tuple[int, ...], data: memoryview | None = None) -> int:
        assert self.calls.call is not None
        value = self.calls.call(target, args, data)
        return 0 if value is None else value

    def lookup(self, raw: bytes, *, view: bool = False) -> int:
        if view:
            result = self.invoke(self.entry, (self.header,), memoryview(bytearray(raw)))
        else:
            self.memory.write_bytes(self.key_address, raw)
            result = self.invoke(self.entry, (self.header, self.out, self.key_address))
        assert result == self.out
        return self.memory.read(result, 8)


def fixture(group: bool, *, full: bool = False) -> Fixture:
    memory = ReplayMemory()
    memory.map_bytes(CEIL_SLOT, CEIL.to_bytes(8, "little"))
    memory.map_bytes(LENGTH_SLOT, LENGTH.to_bytes(8, "little"))
    memory.map_bytes(0x1436A0308, (0x5F000000).to_bytes(4, "little"), writable=False)
    # Explicit source-defined map fields; padding/sentinel payload stay undefined.
    header = memory.allocate(64)
    head = memory.allocate(0x78 if group else 0xA0)
    buckets = memory.allocate_aligned(128)
    memory.write(header, 4, 0x3F800000)
    for offset, value in (
        (8, head),
        (16, 0),
        (24, buckets),
        (32, buckets + 128),
        (40, buckets + 128),
        (48, 7),
        (56, 8),
    ):
        memory.write(header + offset, 8, value)
    memory.write(head, 8, head)
    memory.write(head + 8, 8, head)
    memory.write_bytes(buckets, head.to_bytes(8, "little") * 16)
    out, other_out = zero(memory, 9), zero(memory, 9)
    key_address = memory.allocate(12 if group else 24)
    context = ReplayTaskRebuildStorage(header, memory.read, memory.write)
    if full:
        calls = bind_replay_task_execution(
            context,
            runtime(memory),
            bind_local=memory.bind_local,
            pair_out=out if group else other_out,
            byte_out=other_out if group else out,
            mxcsr=0x1F80,
            prefix_scratch=ReplayTaskPrefixScratch(bytes(64), b"abc", b"xyz"),
        )
    else:
        calls = bind_replay_task_group_maps(
            context,
            runtime(memory),
            bind_local=memory.bind_local,
            group_out=out if group else other_out,
            criterion_out=other_out if group else out,
            mxcsr=0x1F80,
        )
    return Fixture(memory, group, header, head, out, other_out, key_address, context, calls)


@pytest.mark.parametrize(
    "word,expected",
    [
        (0, 0x4D25767F9DCE13F5),
        (0x80000000, 0x4D25767F9DCE13F5),
        (1, 0xAD2ACA7747985764),
        (0x80000001, 0xAD2B4A77479930E4),
        (0x3F800000, 0x4B72477F9C5C2F98),
        (0x7F800000, 0x4B72877F9C5C9C58),
        (0xFF800000, 0x4B73077F9C5D75D8),
        (0x7FC00042, 0x8C9FB5A5D8622736),
        (0x7FA00001, 0xABE43177468290C9),
    ],
)
def test_float_hash_source_golden_words(word: int, expected: int) -> None:
    assert hash_replay_task_group_float(word) == expected


@pytest.mark.parametrize(
    "group,expected", [(True, 0x436B21DDA50EFC5C), (False, 0x41098C43056972A5)]
)
@pytest.mark.parametrize("padding", [0, 0xA5, 0xFF])
def test_complete_hash_golden_ignores_padding(group: bool, expected: int, padding: int) -> None:
    f = fixture(group)
    f.memory.write_bytes(f.key_address, key(group, padding=padding))
    assert (
        f.invoke(0x1412A36C0 if group else 0x1412A3560, (0xDEAD, f.key_address)) == expected
    )  # Unused map is not dereferenced.


@pytest.mark.parametrize("group", [True, False])
@pytest.mark.parametrize("full", [False, True])
def test_growth_preserves_identity_hits_links_and_snapshot_continuation(
    group: bool,
    full: bool,
) -> None:
    f = fixture(group, full=full)
    m = f.memory
    initial = m.snapshot()

    def run(current: Fixture) -> None:
        old_buckets = current.memory.read(current.header + 24, 8)
        nodes = [current.lookup(key(group, integer=i), view=True) for i in range(20)]
        assert len(set(nodes)) == 20
        assert current.memory.read(current.header + 16, 8) == 20
        assert current.memory.read(current.header + 56, 8) == 64
        with pytest.raises(ReplayMemoryError, match="unmapped"):
            current.memory.read(old_buckets, 8)
        for i, node in enumerate(nodes):
            assert current.lookup(key(group, integer=i, padding=0x77)) == node
            assert current.memory.read(current.out + 8, 1) == 0
        seen = []
        node = current.memory.read(current.head, 8)
        while node != current.head:
            assert node not in seen
            following = current.memory.read(node, 8)
            assert current.memory.read(following + 8, 8) == node
            seen.append(node)
            node = following
        assert set(seen) == set(nodes)
        # Scoped key/local bindings are gone; a full Memory snapshot is legal.
        assert all(
            region.owned or region.address < current.header
            for region in current.memory.snapshot().regions
        )

    run(f)
    expected = m.snapshot()
    restored = ReplayMemory.from_snapshot(initial)
    context = ReplayTaskRebuildStorage(f.header, restored.read, restored.write)
    calls = (
        bind_replay_task_execution(
            context,
            runtime(restored),
            bind_local=restored.bind_local,
            pair_out=f.out if group else f.other_out,
            byte_out=f.other_out if group else f.out,
            mxcsr=0x1F80,
            prefix_scratch=ReplayTaskPrefixScratch(bytes(64), b"abc", b"xyz"),
        )
        if full
        else bind_replay_task_group_maps(
            context,
            runtime(restored),
            bind_local=restored.bind_local,
            group_out=f.out if group else f.other_out,
            criterion_out=f.other_out if group else f.out,
            mxcsr=0x1F80,
        )
    )
    rerun = Fixture(
        restored, group, f.header, f.head, f.out, f.other_out, f.key_address, context, calls
    )
    run(rerun)
    assert restored.snapshot() == expected


@pytest.mark.parametrize("group", [True, False])
@pytest.mark.parametrize(
    "first,second,same",
    [
        (0, 0x80000000, True),
        (0x7FC00042, 0x7FC00042, False),
        (0x7FA00001, 0x7FA00001, False),
    ],
)
def test_ordered_float_equality_and_nan_nonidentity(
    group: bool,
    first: int,
    second: int,
    same: bool,
) -> None:
    f = fixture(group)
    a, b = f.lookup(key(group, value=first)), f.lookup(key(group, value=second))
    assert (a == b) == same
    assert f.memory.read(f.header + 16, 8) == (1 if same else 2)


@pytest.mark.parametrize("group", [True, False])
def test_integer_field_is_exact_even_for_signed_zero_bit_patterns(group: bool) -> None:
    f = fixture(group)
    assert f.lookup(key(group, integer=0)) != f.lookup(key(group, integer=0x80000000))


@pytest.mark.parametrize("group", [True, False])
def test_raw_unknown_padding_can_hit_but_miss_stops_after_actual_node_allocation(
    group: bool,
) -> None:
    f = fixture(group)
    existing = f.lookup(key(group))
    raw = key(group, integer=3)
    address = f.memory.allocate(len(raw))
    padding = (9, 10, 11) if group else (1, 2, 3)
    for i, byte in enumerate(raw):
        if i not in padding:
            f.memory.write(address + i, 1, byte)
    assert f.invoke(f.entry, (f.header, f.out, address)) == f.out
    assert f.memory.read(f.out, 8) == existing
    f.memory.write(address + 4, 4, 99)
    before = f.memory.snapshot()
    with pytest.raises(ReplayMemoryError, match="undefined"):
        f.invoke(f.entry, (f.header, f.out, address))
    after = f.memory.snapshot()
    old_addresses = {region.address for region in before.regions}
    allocated = [r for r in after.regions if r.address not in old_addresses]
    assert len(allocated) == 1 and len(allocated[0].data) == (0x78 if group else 0xA0)
    assert f.memory.read(f.header + 16, 8) == 1
    assert f.memory.read(f.out, 8) == existing


@pytest.mark.parametrize("group", [True, False])
def test_readonly_output_flag_preserves_insert_and_pointer_store(group: bool) -> None:
    f = fixture(group)
    f.memory.write_bytes(f.key_address, key(group))
    out = zero(f.memory, 8)
    f.memory.map_bytes(out + 8, b"\xa5", writable=False)
    with pytest.raises(ReplayMemoryError, match="readonly"):
        f.invoke(f.entry, (f.header, out, f.key_address))
    node = f.memory.read(out, 8)
    assert node != 0 and f.memory.read(f.header + 16, 8) == 1
    assert f.memory.read(f.head, 8) == node and f.memory.read(out + 8, 1) == 0xA5


@pytest.mark.parametrize("group", [True, False])
def test_allocation_mutates_key_before_copy_without_recomputing_held_hash(group: bool) -> None:
    f = fixture(group)
    original, changed = key(group), key(group, integer=99, padding=0x77)
    f.memory.write_bytes(f.key_address, original)
    hashed = f.invoke(0x1412A36C0 if group else 0x1412A3560, (f.header, f.key_address))
    actual = runtime(f.memory)
    first = True

    def call(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        nonlocal first
        assert actual.call is not None
        result = actual.call(target, args, data)
        if target == 0x142D6BA78 and first:
            first = False
            f.memory.write_bytes(f.key_address, changed)
        return result

    bound = bind_replay_task_group_maps(
        f.context,
        ReplayTaskRebuildCalls(call),
        bind_local=f.memory.bind_local,
        group_out=f.out,
        criterion_out=f.out,
        mxcsr=0x1F80,
    )
    assert bound.call is not None
    assert bound.call(f.entry, (f.header, f.out, f.key_address), None) == f.out
    node = f.memory.read(f.out, 8)
    assert f.memory.read_bytes(node + 16, len(changed)) == changed
    buckets = f.memory.read(f.header + 24, 8)
    assert f.memory.read(buckets + (hashed & 7) * 16, 8) == node


@pytest.mark.parametrize("group", [True, False])
def test_overlapping_first_copy_store_changes_later_key_load(group: bool) -> None:
    f = fixture(group)
    raw = key(group)
    backing = f.memory.allocate(0x120)
    address = backing + 0x20
    node = address - (12 if group else 8)
    f.memory.write_bytes(address, raw)
    actual = runtime(f.memory)
    first = True

    def call(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        nonlocal first
        if target == 0x142D6BA78 and first:
            first = False
            return node  # Explicit backed public alias, not a native heap claim.
        assert actual.call is not None
        return actual.call(target, args, data)

    bound = bind_replay_task_group_maps(
        f.context,
        ReplayTaskRebuildCalls(call),
        bind_local=f.memory.bind_local,
        group_out=f.out,
        criterion_out=f.out,
        mxcsr=0x1F80,
    )
    assert bound.call is not None
    bound.call(f.entry, (f.header, f.out, address), None)
    expected = raw[:8] + raw[4:8] if group else raw[:16] + raw[8:16]
    assert f.memory.read_bytes(node + 16, len(raw)) == expected


@pytest.mark.parametrize("group", [True, False])
@pytest.mark.parametrize("requested,expected", [(0, 1), (1, 2), (3, 4), (9, 16)])
def test_rehash_rounding_reuses_or_grows_actual_owned_buckets(
    group: bool,
    requested: int,
    expected: int,
) -> None:
    f = fixture(group)
    nodes = [f.lookup(key(group, integer=i)) for i in range(5)]
    f.invoke(0x1412BFB10 if group else 0x1412BF920, (f.header, requested))
    assert f.memory.read(f.header + 56, 8) == expected
    assert f.memory.read(f.header + 48, 8) == expected - 1
    for i, node in enumerate(nodes):
        assert f.lookup(key(group, integer=i)) == node


@pytest.mark.parametrize("group", [True, False])
def test_full_executor_creates_nested_maps_then_cleanup_releases_every_node(group: bool) -> None:
    f = fixture(True, full=True)
    parent = f.lookup(key(True), view=True)
    if group:
        for i in range(10):
            f.lookup(key(True, integer=i + 10), view=True)
    else:
        child_map = parent + 0x20
        for i in range(10):
            raw = memoryview(bytearray(key(False, integer=i)))
            f.invoke(0x1412A4220, (child_map,), raw)
    assert f.memory.read(f.header + 16, 8) > 0
    node_addresses = [r.address for r in f.memory.snapshot().regions if len(r.data) in (0x78, 0xA0)]
    f.invoke(0x1412C5270, (f.header,))
    assert f.memory.read(f.header + 16, 8) == 0
    assert f.memory.read(f.head, 8) == f.head and f.memory.read(f.head + 8, 8) == f.head
    for node in node_addresses:
        if node != f.head:
            with pytest.raises(ReplayMemoryError, match="unmapped"):
                f.memory.read(node, 8)


@pytest.mark.parametrize("ceil", [True, False])
@pytest.mark.parametrize("present", [True, False])
def test_thunk_missing_or_unknown_current_slot_refuses_before_any_selected_call(
    ceil: bool,
    present: bool,
) -> None:
    slot = CEIL_SLOT if ceil else LENGTH_SLOT
    memory = ReplayMemory(start=slot)
    if present:
        assert memory.allocate(8) == slot
    context = ReplayTaskRebuildStorage(0x1000, memory.read, memory.write)
    calls = ReplayTaskContainerCalls(None, 0x1F80)
    with pytest.raises(ReplayMemoryError, match="undefined" if present else "unmapped"):
        (call_replay_task_group_ceil if ceil else call_replay_task_group_length)(
            context, 0, calls=calls
        )


def test_ceil_uses_selected_target_and_does_not_reread_removed_slot_after_return() -> None:
    memory = ReplayMemory(start=CEIL_SLOT)
    assert memory.allocate(8) == CEIL_SLOT
    memory.write(CEIL_SLOT, 8, CEIL)
    context = ReplayTaskRebuildStorage(0x1000, memory.read, memory.write)
    seen = []

    def call(target: int, args: tuple[int, ...], data: memoryview | None) -> int:
        seen.append((target, args, data))
        memory.free(CEIL_SLOT)
        return 0x3F800000

    assert (
        call_replay_task_group_ceil(
            context, 0x3E800000, calls=ReplayTaskContainerCalls(call, 0x1F80)
        )
        == 0x3F800000
    )
    assert seen == [(CEIL, (0x3E800000,), None)] and memory.mapped_bytes == 0


@pytest.mark.parametrize("group", [True, False])
def test_rehash_length_error_reads_current_thunk_before_any_header_access(group: bool) -> None:
    f = fixture(group)
    before = f.memory.snapshot()
    with pytest.raises(ReplayMemoryRuntimeError) as error:
        f.invoke(0x1412BFB10 if group else 0x1412BF920, (0xDEAD, (1 << 59) + 1))
    assert error.value.args_words == (0x143682938,)
    assert f.memory.snapshot() == before
