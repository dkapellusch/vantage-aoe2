"""Owned semantic comparison and original current-IAT thunk contracts."""

from __future__ import annotations

import pytest

from vantage import replay_memory_compare as compare
from vantage.replay_memory import ReplayMemory, ReplayMemoryError
from vantage.replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
)

CMP, CALLOC, STRLEN = 0xC0A4, 0xCA110C, 0x57A1E0
THUNK, IAT, U64 = 0x142D6E3BD, 0x143199940, (1 << 64) - 1


@pytest.mark.parametrize(
    ("left", "right", "count", "result"),
    [
        (b"a", b"a", 1, 0),
        (b"a", b"b", 1, 0xFFFFFFFF),
        (b"b", b"a", 1, 1),
        (b"\x80", b"\x7f", 1, 1),
        (b"\xff", b"\0", 1, 1),
        (b"\0", b"\xff", 1, 0xFFFFFFFF),
        (b"a\0x", b"a\0y", 3, 0xFFFFFFFF),
        (b"abX", b"abY", 2, 0),
        (b"\xc3\xa9", b"zz", 2, 1),
        (b"\xff\0", b"\xff\0", 2, 0),
    ],
)
def test_defined_unsigned_byte_order_has_normalized_raw_eax(left, right, count, result):
    memory = ReplayMemory()
    memory.map_bytes(0x100, left, writable=False)
    memory.map_bytes(0x200, right, writable=False)
    before = memory.snapshot()
    actual = compare.compare_replay_memory_bytes(memory, 0x100, 0x200, count)
    assert actual == result and 0 <= actual <= 0xFFFFFFFF
    assert memory.snapshot() == before


def test_adjacent_readonly_and_current_live_borrowed_bytes():
    memory = ReplayMemory()
    memory.map_bytes(0x100, b"ab", writable=False)
    memory.map_bytes(0x102, b"c\0", writable=False)
    raw = bytearray(b"abc\0")
    with memory.bind_local(memoryview(raw)) as address:
        assert compare.compare_replay_memory_bytes(memory, 0x100, address, 4) == 0
        raw[2] = ord("d")
        assert compare.compare_replay_memory_bytes(memory, 0x100, address, 4) == 0xFFFFFFFF
        assert compare.compare_replay_memory_bytes(memory, address, 0x100, 4) == 1
    with pytest.raises(ReplayMemoryError, match="unmapped"):
        compare.compare_replay_memory_bytes(memory, address, 0x100, 4)


def test_zero_count_validates_scalars_without_any_backing_read():
    class NoReadMemory(ReplayMemory):
        def read_bytes(self, address, size):
            raise AssertionError("zero count performed a backing read")

    memory = NoReadMemory()
    assert compare.compare_replay_memory_bytes(memory, 0, U64, 0) == 0
    assert memory.mapped_bytes == 0


@pytest.mark.parametrize("side", ["left", "right", "self"])
def test_full_definedness_admission_even_after_earlier_difference_or_self_alias(side):
    memory = ReplayMemory()
    unknown = memory.allocate(2)
    memory.write(unknown, 1, ord("a"))
    memory.map_bytes(0x100, b"zz")
    args = (unknown, 0x100) if side == "left" else (0x100, unknown)
    if side == "self":
        args = (unknown, unknown)
    before = memory.snapshot()
    with pytest.raises(ReplayMemoryError, match="undefined"):
        compare.compare_replay_memory_bytes(memory, *args, 2)
    assert memory.snapshot() == before


@pytest.mark.parametrize("kind", ["missing", "gap", "freed"])
def test_missing_gapped_and_freed_storage_never_fabricates_a_result(kind):
    memory = ReplayMemory()
    memory.map_bytes(0x100, b"zz")
    if kind == "gap":
        address = 0x200
        memory.map_bytes(address, b"a")
        memory.map_bytes(address + 2, b"b")
    elif kind == "freed":
        address = memory.allocate(2)
        memory.write_bytes(address, b"ab")
        memory.free(address)
    else:
        address = 0xBAD
    before = memory.snapshot()
    with pytest.raises(ReplayMemoryError, match="unmapped"):
        compare.compare_replay_memory_bytes(memory, 0x100, address, 2)
    assert memory.snapshot() == before


def test_high_u64_last_byte_and_nonwrapping_span_bounds():
    memory = ReplayMemory()
    memory.map_bytes(U64, b"\xff", writable=False)
    memory.map_bytes(0, b"\xff\xff", writable=False)
    before = memory.snapshot()
    assert compare.compare_replay_memory_bytes(memory, U64, 0, 1) == 0
    for left, right in ((U64, 0), (0, U64)):
        with pytest.raises(ReplayMemoryError, match="wraps"):
            compare.compare_replay_memory_bytes(memory, left, right, 2)
    assert compare.compare_replay_memory_bytes(memory, U64, U64, 0) == 0
    assert memory.snapshot() == before


@pytest.mark.parametrize("position", range(3))
@pytest.mark.parametrize("invalid", [-1, 1 << 64, True, 1.5, None])
def test_arguments_require_raw_u64_before_backing(position, invalid):
    memory = ReplayMemory()
    args = [0, U64, 0]
    args[position] = invalid
    with pytest.raises(ValueError, match="comparison argument"):
        compare.compare_replay_memory_bytes(memory, *args)
    assert memory.mapped_bytes == 0


def test_runtime_composition_keeps_actual_malloc_calloc_strlen_free_and_delegate():
    memory = ReplayMemory()
    memory.map_bytes(0x100, b"ab\0", writable=False)
    seen = []

    def delegate(target, args, data):
        seen.append((target, args, data))
        return 17

    calls = compare.replay_memory_comparison_calls(
        memory,
        ReplayTaskRebuildCalls(delegate),
        comparison_target=CMP,
        calloc_target=CALLOC,
        strlen_target=STRLEN,
    ).call
    address = calls(0x142D6BA78, (3,), None)
    memory.write_bytes(address, b"ab\0")
    assert calls(CMP, (0x100, address, 3), None) == 0
    assert calls(STRLEN, (address,), None) == 2
    zero = calls(CALLOC, (1, 3), None)
    assert memory.read_bytes(zero, 3) == bytes(3)
    assert calls(CMP, (zero, address, 3), None) == 0xFFFFFFFF
    calls(0x142D6BAB4, (zero, 3), None)
    payload = memoryview(bytearray(b"x"))
    assert calls(0xFEED, (1, 2), payload) == 17
    assert seen == [(0xFEED, (1, 2), payload)] and seen[0][2] is payload
    with pytest.raises(ReplayMemoryError, match="unmapped"):
        memory.read(IAT, 8)  # The capability factory never installs an IAT.
    with pytest.raises(UnresolvedReplayTaskRebuild, match="c0a4"):
        memory.runtime_calls().call(CMP, (0x100, address, 3), None)


@pytest.mark.parametrize(
    "target",
    [
        0,
        0x142D6BA78,
        0x1402A94D0,
        0x142D6BAB4,
        0x142D6E3DB,
        0x142D6E3B7,
        0x142D6E453,
        0x1402A9460,
        0x14113A7A0,
        0x14114DD60,
        0x142D66698,
        THUNK,
        CALLOC,
        STRLEN,
    ],
)
def test_comparison_identity_cannot_collide_with_composed_owned_targets(target):
    with pytest.raises(ValueError, match="distinct engine comparison"):
        compare.replay_memory_comparison_calls(
            ReplayMemory(), comparison_target=target, calloc_target=CALLOC, strlen_target=STRLEN
        )


@pytest.mark.parametrize("target", [-1, 1 << 64, True, 1.5, None])
def test_comparison_identity_requires_explicit_raw_nonzero_token(target):
    with pytest.raises(ValueError, match="comparison target"):
        compare.replay_memory_comparison_calls(ReplayMemory(), comparison_target=target)


def test_no_implicit_comparison_identity_and_unknown_provider_refuses():
    with pytest.raises(TypeError, match="comparison_target"):
        compare.replay_memory_comparison_calls(ReplayMemory())
    calls = compare.replay_memory_comparison_calls(ReplayMemory(), comparison_target=CMP).call
    with pytest.raises(UnresolvedReplayTaskRebuild, match="feed"):
        calls(0xFEED, (1, 2, 3), None)
    high = compare.replay_memory_comparison_calls(ReplayMemory(), comparison_target=U64)
    assert high.call(U64, (0, U64, 0), None) == 0


@pytest.mark.parametrize(
    ("args", "payload"),
    [
        ((), None),
        ((0, 0), None),
        ((0, 0, 0, 0), None),
        ((0, 0, 0), memoryview(bytearray())),
    ],
)
def test_provider_and_thunk_arity_payload_refuse_before_any_read(args, payload):
    memory = ReplayMemory()
    context = ReplayTaskRebuildStorage(1, memory.read, memory.write)
    provider = compare.replay_memory_comparison_calls(memory, comparison_target=CMP)
    bound = compare.bind_replay_memcmp_thunk(context, provider)
    for target, calls in ((CMP, provider), (THUNK, bound)):
        with pytest.raises(ValueError, match="malformed"):
            calls.call(target, args, payload)
    assert memory.mapped_bytes == 0


@pytest.mark.parametrize("position", range(3))
@pytest.mark.parametrize("invalid", [-1, 1 << 64, True])
def test_bound_provider_and_thunk_reject_raw_argument_errors_before_iat_access(position, invalid):
    memory = ReplayMemory()
    args = [0, 0, 0]
    args[position] = invalid
    runtime = compare.replay_memory_comparison_calls(memory, comparison_target=CMP)
    context = ReplayTaskRebuildStorage(1, memory.read, memory.write)
    bound = compare.bind_replay_memcmp_thunk(context, runtime)
    for target, calls in ((CMP, runtime), (THUNK, bound)):
        with pytest.raises(ValueError, match="argument"):
            calls.call(target, tuple(args), None)
    assert memory.mapped_bytes == 0


def test_actual_thunk_provider_composition_and_current_slot_reload():
    memory = ReplayMemory()
    memory.map_bytes(IAT, CMP.to_bytes(8, "little"))
    memory.map_bytes(0x100, b"a")
    memory.map_bytes(0x200, b"b")
    reads, selected = [], []

    def read(address, width):
        value = memory.read(address, width)
        reads.append((address, width))
        if len(reads) == 1:
            memory.write(IAT, 8, 0xFEED)
        return value

    def other(target, args, data):
        selected.append((target, args, data))
        return 0x7FFFFFFF

    runtime = compare.replay_memory_comparison_calls(
        memory, ReplayTaskRebuildCalls(other), comparison_target=CMP
    )
    context = ReplayTaskRebuildStorage(1, read, memory.write)
    bound = compare.bind_replay_memcmp_thunk(context, runtime)
    assert bound.call(THUNK, (0x100, 0x200, 1), None) == 0xFFFFFFFF
    assert bound.call(THUNK, (0x100, 0x200, 1), None) == 0x7FFFFFFF
    assert reads == [(IAT, 8), (IAT, 8)]
    assert selected == [(0xFEED, (0x100, 0x200, 1), None)]


def test_explicit_terminal_import_alias_is_dispatched_once_not_recursively_rebound():
    memory = ReplayMemory()
    memory.map_bytes(IAT, THUNK.to_bytes(8, "little"))
    seen = []

    def terminal(target, args, data):
        seen.append((target, args, data))
        return 0x80000000

    context = ReplayTaskRebuildStorage(1, memory.read, memory.write)
    bound = compare.bind_replay_memcmp_thunk(
        context, ReplayTaskRebuildCalls(None), imports=ReplayTaskRebuildCalls(terminal)
    )
    assert bound.call(THUNK, (0, U64, 0), None) == 0x80000000
    assert seen == [(THUNK, (0, U64, 0), None)]


def test_missing_slot_and_missing_terminal_provider_preserve_actual_reached_order():
    memory = ReplayMemory()
    reads = []

    def read(address, width):
        reads.append((address, width))
        return memory.read(address, width)

    context = ReplayTaskRebuildStorage(1, read, memory.write)
    imports = ReplayTaskRebuildCalls(None)
    with pytest.raises(ReplayMemoryError, match="unmapped"):
        compare.call_replay_memcmp_thunk(context, 0, 0, 0, imports=imports)
    memory.map_bytes(IAT, CMP.to_bytes(8, "little"))
    with pytest.raises(UnresolvedReplayTaskRebuild, match="c0a4"):
        compare.call_replay_memcmp_thunk(context, 0, 0, 0, imports=imports)
    assert reads == [(IAT, 8), (IAT, 8)]


@pytest.mark.parametrize("returned", [None, -1, 1 << 32, True, 1.5])
def test_thunk_requires_raw_eax_not_a_signed_python_integer_or_full_rax(returned):
    memory = ReplayMemory()
    memory.map_bytes(IAT, CMP.to_bytes(8, "little"))
    context = ReplayTaskRebuildStorage(1, memory.read, memory.write)
    before = memory.snapshot()
    with pytest.raises(ValueError, match=r"raw scalar|unsigned"):
        compare.call_replay_memcmp_thunk(
            context, 0, 0, 0, imports=ReplayTaskRebuildCalls(lambda *_: returned)
        )
    assert memory.snapshot() == before


def test_thunk_unknown_body_delegation_and_backing_errors_never_fallback():
    memory = ReplayMemory()
    memory.map_bytes(IAT, CMP.to_bytes(8, "little"))
    seen = []

    def delegate(target, args, data):
        seen.append((target, args, data))
        return 99

    runtime = compare.replay_memory_comparison_calls(
        memory, ReplayTaskRebuildCalls(delegate), comparison_target=CMP
    )
    context = ReplayTaskRebuildStorage(1, memory.read, memory.write)
    bound = compare.bind_replay_memcmp_thunk(context, runtime)
    payload = memoryview(bytearray(b"z"))
    assert bound.call(0xFEED, (1, 2), payload) == 99
    assert seen == [(0xFEED, (1, 2), payload)]
    with pytest.raises(ReplayMemoryError, match="unmapped"):
        bound.call(THUNK, (0xBAD, 0xBAD, 1), None)
    assert len(seen) == 1
