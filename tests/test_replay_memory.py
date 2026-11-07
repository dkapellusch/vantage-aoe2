"""Concrete replay memory ownership, definedness, aliasing and runtime effects."""

from __future__ import annotations

import math
import random
import struct
from dataclasses import replace

import pytest

from vantage.replay_memory import (
    ReplayMemory,
    ReplayMemoryError,
    ReplayMemoryRegionSnapshot,
    ReplayMemoryRuntimeError,
)
from vantage.replay_task_rebuild import ReplayTaskRebuildCalls, UnresolvedReplayTaskRebuild


def test_adjacent_regions_support_scalar_access_and_atomic_write_checks() -> None:
    memory = ReplayMemory()
    memory.map_bytes(0x100, b"abcd")
    memory.map_bytes(0x104, b"efgh")
    assert memory.read(0x102, 4) == int.from_bytes(b"cdef", "little")
    memory.write(0x102, 4, int.from_bytes(b"WXYZ", "little"))
    assert memory.read_bytes(0x100, 8) == b"abWXYZgh"
    memory.map_bytes(0x108, b"ijkl", writable=False)
    before = memory.snapshot()
    with pytest.raises(ReplayMemoryError, match="readonly"):
        memory.write_bytes(0x106, b"1234")
    assert memory.snapshot() == before
    with pytest.raises(ReplayMemoryError, match="unmapped"):
        memory.write_bytes(0x0FF, b"1234")
    assert memory.snapshot() == before


def test_allocations_do_not_invent_zero_values_and_copy_preserves_undefined_bytes() -> None:
    memory = ReplayMemory()
    source, dest = memory.allocate(8), memory.allocate(8)
    memory.write_bytes(dest, b"xxxxxxxx")
    memory.write_bytes(source + 2, b"yes")
    memory.move(dest, source, 8)
    assert memory.read_bytes(dest + 2, 3) == b"yes"
    for offset in (0, 1, 5, 6, 7):
        with pytest.raises(ReplayMemoryError, match="undefined"):
            memory.read(dest + offset, 1)
    memory.write_bytes(dest, b"ABCDEFGH")
    assert memory.read_bytes(dest, 8) == b"ABCDEFGH"


@pytest.mark.parametrize(
    ("source", "destination", "size"),
    [
        (0, 1, 15),
        (1, 0, 15),
        (0, 0, 16),
        (4, 8, 4),
        (8, 4, 4),
        (0, 15, 1),
        (15, 0, 1),
    ],
)
def test_memmove_matches_bytearray_snapshot_across_region_boundaries(
    source: int,
    destination: int,
    size: int,
) -> None:
    memory = ReplayMemory()
    initial = bytes(range(16))
    for i in range(0, 16, 4):
        memory.map_bytes(0x100 + i, initial[i : i + 4])
    expected = bytearray(initial)
    expected[destination : destination + size] = bytes(expected[source : source + size])
    assert memory.move(0x100 + destination, 0x100 + source, size) == 0x100 + destination
    assert memory.read_bytes(0x100, 16) == expected
    assert memory.move(0, 0, 0) == 0


@pytest.mark.parametrize("size", [0, 1, 15, 4095, 4096, 4100, 8192])
def test_aligned_allocator_layout_and_release(size: int) -> None:
    memory = ReplayMemory(max_bytes=1 << 20)
    address = memory.allocate_aligned(size)
    if not size:
        assert address == 0 and memory.mapped_bytes == 0
        return
    base = memory.read(address - 8, 8) if size >= 4096 else address
    if size >= 4096:
        assert address % 32 == 0 and 0 <= address - base - 8 <= 31
        assert memory.mapped_bytes == size + 39
    else:
        assert address % 16 == 0 and memory.mapped_bytes == size
    with pytest.raises(ReplayMemoryError, match="undefined"):
        memory.read(address, 1)
    memory.write_bytes(address, b"Z" * size)
    memory.free(base)
    assert memory.mapped_bytes == 0
    with pytest.raises(ReplayMemoryError, match="unmapped"):
        memory.read(address, 1)


def test_allocator_failure_does_not_advance_cursor_and_skips_explicit_mappings() -> None:
    memory = ReplayMemory(start=0x1000, max_bytes=64)
    memory.map_bytes(0x1000, bytes(16))
    memory.map_bytes(0x1020, bytes(16))
    first = memory.allocate(32)
    assert first == 0x1030
    before = memory.snapshot()
    with pytest.raises(MemoryError):
        memory.allocate(1)
    assert memory.snapshot() == before
    with pytest.raises(MemoryError):
        memory.map_bytes(0x2000, b"x")
    assert memory.snapshot() == before


def test_raw_zero_allocate_is_nonnull_and_free_checks_ownership() -> None:
    memory = ReplayMemory()
    first, second = memory.allocate(0), memory.allocate(0)
    assert first and second != first
    memory.map_bytes(0x100, b"x")
    before = memory.snapshot()
    for invalid in (first + 1, 0x100, 0x200):
        with pytest.raises(ReplayMemoryError, match="owned"):
            memory.free(invalid)
        assert memory.snapshot() == before
    memory.free(0)
    memory.free(first)
    with pytest.raises(ReplayMemoryError, match="owned"):
        memory.free(first)


def test_live_local_aliases_external_writes_nested_cleanup_and_released_input_view() -> None:
    memory = ReplayMemory()
    original = bytearray(b"abcdefgh")
    view = memoryview(original)
    with memory.bind_local(view) as first:
        with memory.bind_local(view[2:6]) as second:
            view.release()
            memory.write(second, 2, int.from_bytes(b"XY", "little"))
            assert memory.read_bytes(first, 8) == b"abXYefgh"
            original[4] = ord("Q")
            assert memory.read_bytes(second, 4) == b"XYQf"
            with pytest.raises(ReplayMemoryError, match="borrowed"):
                memory.snapshot()
            with pytest.raises(ReplayMemoryError, match="owned"):
                memory.free(first)
        with pytest.raises(ReplayMemoryError, match="unmapped"):
            memory.read(second, 1)
        assert memory.read_bytes(first, 8) == b"abXYQfgh"
    assert memory.mapped_bytes == 0 and memory.snapshot().regions == ()
    original.extend(b"!")  # The retained binding released its independent buffer pin.


def test_local_error_exit_retains_bytes_and_unmaps_without_suppressing_error() -> None:
    memory = ReplayMemory()
    data = bytearray(b"1234")
    with (
        pytest.raises(OSError, match="body failed"),
        memory.bind_local(memoryview(data)) as address,
    ):
        memory.write_bytes(address, b"abcd")
        raise OSError("body failed")
    assert data == b"abcd" and memory.mapped_bytes == 0
    with pytest.raises(ReplayMemoryError, match="unmapped"):
        memory.read(address, 1)


def test_undefined_transfer_into_borrowed_aliases_refuses_before_any_destination_effect() -> None:
    memory = ReplayMemory()
    source = memory.allocate(4)
    memory.write_bytes(source, b"AB")
    dest = bytearray(b"1234")
    with (
        memory.bind_local(memoryview(dest)) as first,
        memory.bind_local(memoryview(dest)[1:]) as second,
    ):
        with pytest.raises(ReplayMemoryError, match="undefined transfer"):
            memory.move(first, source, 4)
        assert dest == b"1234"
        dest[1] = ord("z")
        assert memory.read_bytes(first, 4) == b"1z34"
        assert memory.read_bytes(second, 3) == b"z34"
        memory.move(first, source, 2)
        assert memory.read_bytes(second, 3) == b"B34"


def test_snapshot_preserves_unknown_bytes_ownership_flags_and_future_allocation_order() -> None:
    memory = ReplayMemory(start=0x1000)
    memory.map_bytes(0x100, b"const", writable=False)
    address = memory.allocate(8)
    memory.write(address + 2, 2, 0xBEEF)
    snapshot = memory.snapshot()
    restored = ReplayMemory.from_snapshot(snapshot)
    assert restored.snapshot() == snapshot
    with pytest.raises(ReplayMemoryError, match="undefined"):
        restored.read(address, 8)
    restored.write(address, 2, 0x1234)
    assert restored.read(address, 4) == 0xBEEF1234
    with pytest.raises(ReplayMemoryError, match="undefined"):
        memory.read(address, 4)
    assert memory.allocate(9) == restored.allocate(9)
    restored.free(address)
    assert memory.read(address + 2, 2) == 0xBEEF


def test_address_space_exhausted_snapshot_round_trip_and_huge_write_preflight() -> None:
    memory = ReplayMemory(start=(1 << 64) - 16)
    address = memory.allocate(16)
    memory.write_bytes(address, bytes(16))
    restored = ReplayMemory.from_snapshot(memory.snapshot())
    assert restored.snapshot() == memory.snapshot()
    with pytest.raises(MemoryError, match="address space"):
        restored.allocate(1)
    with pytest.raises(ReplayMemoryError, match="wraps"):
        memory.write(address, (1 << 64) - 1, 1)


def test_memset_defines_adjacent_backing_and_live_views_with_low_byte_value() -> None:
    memory = ReplayMemory()
    address = memory.allocate(4)
    memory.map_bytes(address + 4, b"abcd")
    assert memory.fill(address + 2, 0x123456789ABCDEF0, 5) == address + 2
    assert memory.read_bytes(address + 2, 6) == b"\xf0" * 5 + b"d"
    with pytest.raises(ReplayMemoryError, match="undefined"):
        memory.read(address, 1)
    data = bytearray(b"1234")
    with memory.bind_local(memoryview(data)) as local:
        memory.fill(local + 1, 0x100, 2)
        assert data == b"1\x00\x004"


def test_memset_preflights_before_effects_and_zero_size_never_accesses_backing() -> None:
    memory = ReplayMemory()
    memory.map_bytes(0x100, b"abcd")
    memory.map_bytes(0x104, b"efgh", writable=False)
    before = memory.snapshot()
    for address, size, message in (
        (0x102, 4, "readonly"),
        (0xFF, 2, "unmapped"),
        ((1 << 64) - 1, 2, "wraps"),
    ):
        with pytest.raises(ReplayMemoryError, match=message):
            memory.fill(address, 0, size)
        assert memory.snapshot() == before
    assert memory.fill((1 << 64) - 1, 7, 0) == (1 << 64) - 1
    for value in (-1, 1 << 64, True):
        with pytest.raises(ValueError, match="fill value"):
            memory.fill(0x100, value, 1)
    assert memory.snapshot() == before


@pytest.mark.parametrize("defined", [b"", b"\x00\x00", b"\x02"])
def test_invalid_snapshot_definedness_is_rejected(defined: bytes) -> None:
    snapshot = ReplayMemory().snapshot()
    invalid = ReplayMemoryRegionSnapshot(0x100, b"x", defined, True, True)
    with pytest.raises(ValueError, match="snapshot region"):
        ReplayMemory.from_snapshot(replace(snapshot, regions=(invalid,)))


@pytest.mark.parametrize(
    "view", [memoryview(b"abc"), memoryview(bytearray()), memoryview(bytearray(b"abcd"))[::2]]
)
def test_invalid_borrowed_view_refuses_without_memory_effect(view: memoryview) -> None:
    memory = ReplayMemory()
    before = memory.snapshot()
    with pytest.raises(ValueError), memory.bind_local(view):
        pytest.fail("invalid view admitted")
    assert memory.snapshot() == before


def test_runtime_dispatch_performs_real_memory_effects_and_preserves_delegate_identity() -> None:
    memory = ReplayMemory()
    seen = []

    def delegate(target: int, args: tuple[int, ...], data: memoryview | None) -> int:
        seen.append((target, args, data))
        return 0xCAFE

    calls = memory.runtime_calls(ReplayTaskRebuildCalls(delegate)).call
    assert calls is not None
    source = calls(0x1402A94D0, (4096,), None)
    assert source is not None
    memory.write_bytes(source, b"abcdef")
    dest = calls(0x142D6BA78, (6,), None)
    assert dest is not None
    assert calls(0x142D6E3DB, (dest, source, 6), None) == dest
    assert memory.read_bytes(dest, 6) == b"abcdef"
    assert calls(0x142D6E3B7, (dest + 1, 0x1234, 3), None) == dest + 1
    assert memory.read_bytes(dest, 6) == b"a444ef"
    calls(0x142D6BAB4, (memory.read(source - 8, 8), 0xBAD), None)
    data = memoryview(bytearray(b"xx"))
    assert calls(0xCAFE, (1, 2), data) == 0xCAFE
    assert seen == [(0xCAFE, (1, 2), data)] and seen[0][2] is data


def test_runtime_ceil_matches_math_for_finite_words_and_signed_zero() -> None:
    calls = ReplayMemory().runtime_calls().call
    assert calls is not None
    rng = random.Random(94164)
    words = [
        0,
        0x80000000,
        1,
        0x80000001,
        0x3F000001,
        0xBF000001,
        0x4AFFFFFF,
        0xCAFFFFFF,
        0x7F800000,
        0xFF800000,
    ]
    words.extend(rng.getrandbits(32) for _ in range(2000))
    for word in words:
        exponent, fraction = word >> 23 & 255, word & 0x7FFFFF
        if exponent == 255 and fraction:
            continue
        value = struct.unpack("<f", word.to_bytes(4, "little"))[0]
        expected = word
        if math.isfinite(value):
            result = math.ceil(value)
            expected = (
                (word & 0x80000000)
                if not result
                else int.from_bytes(struct.pack("<f", result), "little")
            )
        assert calls(0x142D6E453, (word,), None) == expected
    with pytest.raises(UnresolvedReplayTaskRebuild, match="unavailable"):
        calls(0x142D6E453, (0x7FA12345,), None)


@pytest.mark.parametrize("target", [0x1402A9460, 0x14113A7A0, 0x14114DD60, 0x142D66698])
def test_runtime_error_leaves_terminate_with_actual_engine_exception(target: int) -> None:
    calls = ReplayMemory().runtime_calls().call
    assert calls is not None
    with pytest.raises(ReplayMemoryRuntimeError) as caught:
        calls(target, (), None)
    assert caught.value.target == target


@pytest.mark.parametrize(
    "target", [0x142D6BA78, 0x1402A94D0, 0x142D6BAB4, 0x142D6E3DB, 0x142D6E3B7, 0x142D6E453]
)
def test_malformed_runtime_calls_fail_before_effects(target: int) -> None:
    memory = ReplayMemory()
    calls = memory.runtime_calls().call
    assert calls is not None
    before = memory.snapshot()
    with pytest.raises(ValueError, match="malformed"):
        calls(target, (), None)
    assert memory.snapshot() == before


def test_shared_count_operations_return_old_words_wrap_and_survive_snapshots() -> None:
    memory = ReplayMemory()
    address = memory.allocate(4)
    memory.write(address, 4, 0xFFFFFFFF)
    assert memory.compare_exchange_u32(address, 7, 100) == 0xFFFFFFFF
    assert memory.read(address, 4) == 0xFFFFFFFF
    assert memory.compare_exchange_u32(address, 0xFFFFFFFF, 1) == 0xFFFFFFFF
    snapshot = memory.snapshot()
    for candidate in (memory, ReplayMemory.from_snapshot(snapshot)):
        assert candidate.fetch_add_u32(address, 0xFFFFFFFF) == 1
        assert candidate.read(address, 4) == 0
        assert candidate.fetch_add_u32(address, 0xFFFFFFFF) == 0
        assert candidate.read(address, 4) == 0xFFFFFFFF
        assert candidate.fetch_add_u32(address, 1) == 0xFFFFFFFF
        assert candidate.read(address, 4) == 0


@pytest.mark.parametrize("method", ["compare_exchange_u32", "fetch_add_u32"])
def test_shared_count_span_preflight_and_invalid_values_never_change_memory(method) -> None:
    memory = ReplayMemory()
    memory.map_bytes(0x100, b"\x01\x00")
    memory.map_bytes(0x102, b"\x00\x00")
    memory.map_bytes(0x104, b"\x01\x00\x00\x00", writable=False)
    undefined = memory.allocate(4)
    operation = getattr(memory, method)
    args = (1, 2) if method == "compare_exchange_u32" else (1,)
    assert operation(0x100, *args) == 1  # Engine supports disjoint adjacent backing.
    before = memory.snapshot()
    for address, message in (
        (0x102, "readonly"),
        (0xFF, "unmapped"),
        (undefined, "undefined"),
        ((1 << 64) - 1, "wraps"),
    ):
        with pytest.raises(ReplayMemoryError, match=message):
            operation(address, *args)
        assert memory.snapshot() == before
    for invalid in (-1, 1 << 32, True):
        with pytest.raises(ValueError, match="raw u32"):
            operation(0x100, *((invalid, 1) if len(args) == 2 else (invalid,)))
        if len(args) == 2:
            with pytest.raises(ValueError, match="raw u32"):
                operation(0x100, 1, invalid)
        assert memory.snapshot() == before


def test_calloc_zeroes_requested_bytes_and_overflow_has_no_allocation_effect() -> None:
    memory = ReplayMemory()
    address = memory.calloc(3, 7)
    assert memory.read_bytes(address, 21) == bytes(21)
    before = memory.snapshot()
    assert memory.calloc((1 << 64) - 1, 2) == 0
    assert memory.snapshot() == before
    empty = memory.calloc(0, (1 << 64) - 1)
    assert empty
    with pytest.raises(ReplayMemoryError, match="undefined"):
        memory.read(empty, 1)
    memory.free(empty)
    for a, b in ((True, 2), (-1, 2), (2, 1 << 64)):
        with pytest.raises(ValueError, match="calloc"):
            memory.calloc(a, b)


def test_calloc_explicit_runtime_identity_and_single_argument_free() -> None:
    memory = ReplayMemory()
    calls = memory.runtime_calls(calloc_target=0xCA110C).call
    assert calls is not None
    address = calls(0xCA110C, (5, 4), None)
    assert memory.read_bytes(address, 20) == bytes(20)
    assert calls(0x142D6BAB4, (address,), None) is None
    with pytest.raises(ReplayMemoryError, match="unmapped"):
        memory.read(address, 1)
    assert calls(0x142D6BAB4, (0,), None) is None
    for token in (0, 0x142D6BA78, 0x142D6BAB4, 0x142D66698):
        with pytest.raises(ValueError, match="distinct"):
            memory.runtime_calls(calloc_target=token)
    with pytest.raises(UnresolvedReplayTaskRebuild, match="ca110c"):
        memory.runtime_calls().call(0xCA110C, (1, 1), None)


@pytest.mark.parametrize(
    "data",
    [
        b"",
        b"a",
        b"hello",
        b"\xff\xfe",
        b"\xc3\xa9",
        bytes(range(1, 256)),
    ],
)
def test_c_string_length_counts_raw_bytes_without_writes(data: bytes) -> None:
    memory = ReplayMemory()
    memory.map_bytes(0x100, data + b"\0ignored", writable=False)
    before = memory.snapshot()
    assert memory.c_string_length(0x100) == len(data)
    assert memory.c_string_length(0x100 + len(data)) == 0
    assert memory.snapshot() == before


def test_c_string_length_crosses_adjacent_regions_and_stops_before_missing_backing() -> None:
    memory = ReplayMemory()
    memory.map_bytes(0x100, b"abc", writable=False)
    memory.map_bytes(0x103, b"de")
    memory.map_bytes(0x105, b"\0", writable=False)
    before = memory.snapshot()
    assert memory.c_string_length(0x101) == 4
    assert memory.snapshot() == before


def test_c_string_length_stops_before_undefined_bytes_but_never_treats_them_as_nul() -> None:
    memory = ReplayMemory()
    address = memory.allocate(8)
    memory.write_bytes(address, b"ab\0")
    before = memory.snapshot()
    assert memory.c_string_length(address) == 2
    with pytest.raises(ReplayMemoryError, match="undefined"):
        memory.c_string_length(address + 3)
    memory.write(address + 2, 1, ord("c"))
    unterminated = memory.snapshot()
    with pytest.raises(ReplayMemoryError, match="undefined"):
        memory.c_string_length(address)
    assert memory.snapshot() == unterminated
    assert before != unterminated


def test_c_string_length_missing_gap_or_freed_backing_has_no_effect() -> None:
    memory = ReplayMemory()
    memory.map_bytes(0x100, b"ab")
    memory.map_bytes(0x103, b"\0")
    freed = memory.allocate(2)
    memory.write_bytes(freed, b"x\0")
    memory.free(freed)
    before = memory.snapshot()
    for address in (0, 0x100, freed):
        with pytest.raises(ReplayMemoryError, match="unmapped"):
            memory.c_string_length(address)
        assert memory.snapshot() == before


def test_c_string_length_uses_current_live_locals_and_restored_snapshots() -> None:
    memory = ReplayMemory()
    local = bytearray(b"ab\0x\0")
    with memory.bind_local(memoryview(local)) as address:
        assert memory.c_string_length(address) == 2
        local[2] = ord("c")
        assert memory.c_string_length(address) == 4
    memory.map_bytes(0x100, bytes(local))
    restored = ReplayMemory.from_snapshot(memory.snapshot())
    assert restored.c_string_length(0x100) == 4


def test_c_string_length_at_address_limit_requires_no_wrapped_read_after_nul() -> None:
    memory = ReplayMemory()
    memory.map_bytes((1 << 64) - 2, b"a\0")
    before = memory.snapshot()
    assert memory.c_string_length((1 << 64) - 2) == 1
    assert memory.c_string_length((1 << 64) - 1) == 0
    memory.write((1 << 64) - 1, 1, ord("b"))
    unterminated = memory.snapshot()
    with pytest.raises(ReplayMemoryError, match="wraps"):
        memory.c_string_length((1 << 64) - 2)
    assert memory.snapshot() == unterminated
    assert before != unterminated


@pytest.mark.parametrize("address", [-1, 1 << 64, True, 1.5, None])
def test_c_string_length_rejects_invalid_addresses_before_access(address) -> None:
    memory = ReplayMemory()
    before = memory.snapshot()
    with pytest.raises(ValueError, match=r"C-string address.*raw u64"):
        memory.c_string_length(address)
    assert memory.snapshot() == before


def test_strlen_runtime_identity_is_explicit_and_coexists_with_calloc() -> None:
    memory = ReplayMemory()
    memory.map_bytes(0x100, b"\xffabc\0", writable=False)
    seen = []

    def delegate(target: int, args: tuple[int, ...], data: memoryview | None) -> int:
        seen.append((target, args, data))
        return 99

    fallback = ReplayTaskRebuildCalls(delegate)
    assert memory.runtime_calls(fallback).call(0x57A1E0, (0x100,), None) == 99
    assert seen == [(0x57A1E0, (0x100,), None)]
    calls = memory.runtime_calls(fallback, strlen_target=0x57A1E0, calloc_target=0xCA110C).call
    assert calls is not None
    before = memory.snapshot()
    assert calls(0x57A1E0, (0x100,), None) == 4
    assert memory.snapshot() == before
    assert len(seen) == 1
    address = calls(0xCA110C, (1, 3), None)
    assert address is not None and memory.read_bytes(address, 3) == bytes(3)
    assert calls(0x57A1E0, (address,), None) == 0
    calls(0x142D6BAB4, (address,), None)
    with pytest.raises(UnresolvedReplayTaskRebuild, match="57a1e0"):
        memory.runtime_calls().call(0x57A1E0, (0x100,), None)
    assert (
        memory.runtime_calls(strlen_target=(1 << 64) - 1).call((1 << 64) - 1, (0x100,), None) == 4
    )


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
        0xCA110C,
    ],
)
def test_strlen_runtime_target_cannot_replace_any_owned_runtime_or_calloc(target: int) -> None:
    memory = ReplayMemory()
    before = memory.snapshot()
    with pytest.raises(ValueError, match="distinct engine strlen"):
        memory.runtime_calls(strlen_target=target, calloc_target=0xCA110C)
    assert memory.snapshot() == before


@pytest.mark.parametrize("target", [-1, 1 << 64, True, 1.5])
def test_strlen_runtime_target_requires_raw_u64(target) -> None:
    with pytest.raises(ValueError, match=r"strlen target.*raw u64"):
        ReplayMemory().runtime_calls(strlen_target=target)


@pytest.mark.parametrize(
    ("args", "payload"),
    [
        ((), False),
        ((0x100, 1), False),
        ((0x100,), True),
    ],
)
def test_strlen_runtime_validates_call_arity_and_payload_before_access(args, payload) -> None:
    memory = ReplayMemory()
    calls = memory.runtime_calls(strlen_target=0x57A1E0).call
    assert calls is not None
    before = memory.snapshot()
    with pytest.raises(ValueError, match="malformed"):
        calls(0x57A1E0, args, memoryview(bytearray()) if payload else None)
    assert memory.snapshot() == before


@pytest.mark.parametrize("address", [-1, 1 << 64, True])
def test_strlen_runtime_validates_argument_before_access(address: int) -> None:
    memory = ReplayMemory()
    calls = memory.runtime_calls(strlen_target=0x57A1E0).call
    assert calls is not None
    before = memory.snapshot()
    with pytest.raises(ValueError, match=r"runtime argument.*raw u64"):
        calls(0x57A1E0, (address,), None)
    assert memory.snapshot() == before


def test_strlen_runtime_propagates_backing_errors_without_delegation() -> None:
    memory = ReplayMemory()
    undefined = memory.allocate(1)
    memory.map_bytes((1 << 64) - 1, b"x")
    seen = []

    def delegate(target: int, args: tuple[int, ...], data: memoryview | None) -> int:
        seen.append((target, args, data))
        return 0

    calls = memory.runtime_calls(ReplayTaskRebuildCalls(delegate), strlen_target=0x57A1E0).call
    assert calls is not None
    before = memory.snapshot()
    for address, error in ((0xBAD, "unmapped"), (undefined, "undefined"), ((1 << 64) - 1, "wraps")):
        with pytest.raises(ReplayMemoryError, match=error):
            calls(0x57A1E0, (address,), None)
        assert memory.snapshot() == before
    assert seen == []
