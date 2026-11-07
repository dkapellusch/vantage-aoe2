"""Source-derived owned Python controls; no native/recording/World claims."""

from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from vantage.replay_memory import ReplayMemory, ReplayMemoryError
from vantage.replay_player_construction_support import (
    ReplayPlayerMarkerCall,
    ReplayPlayerSupportFloatingCalls,
    ReplayPlayerSupportScratch,
    bind_replay_player_construction_support,
    bind_replay_player_marker,
    construct_replay_player_array,
    construct_replay_player_dual_arrays,
    construct_replay_player_hash,
    construct_replay_player_list,
    construct_replay_player_rows,
    count_replay_player_world_entries,
    read_replay_player_marker,
    reindex_replay_player_resources,
    release_replay_player_hash_buckets,
)
from vantage.replay_saved_apply import bind_replay_saved_apply
from vantage.replay_saved_input import ReplaySavedInput, bind_replay_saved_input
from vantage.replay_saved_result import bind_replay_saved_result
from vantage.replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
)
from vantage.replay_unit_ai_map import ReplayUnitAIMapAtomics
from vantage.replay_unit_constructor_support import bind_replay_unit_constructor_support
from vantage.replay_zone_map_construction import bind_replay_zone_map_construction

U64, IO, CALLOC = (1 << 64) - 1, 0xCA01, 0xCA02
SCRATCH = ReplayPlayerSupportScratch(bytes([0xA5]) * 0xB8, bytes([0x71]) * 0x48)


def setup(*, after=None, on_read=None, on_write=None, wire=b"\x2a"):
    h = SimpleNamespace()
    h.m = m = ReplayMemory()
    h.obj, h.out, h.stream, h.vptr = (m.allocate(n) for n in (0x800, 48, 8, 32))
    m.write_bytes(h.obj, b"\xa5" * 0x800)
    m.write_bytes(h.out, b"O" * 48)
    m.write(h.stream, 8, h.vptr)
    m.write(h.vptr + 24, 8, IO)
    h.frames, h.finished, h.events, h.import_events, h.ops = [], [], [], [], []
    h.handlers, h.missing, h.overrides = {}, set(), {}
    for address, width, value in (
        (0x143199DC0, 8, CALLOC),
        (0x143199DD0, 8, 0x142D6BAB4),
        (0x143199930, 8, 0x142D6E3DB),
        (0x143199938, 8, 0x142D6E3B7),
        (0x14319A060, 8, 0xCA03),
        (0x143235268, 4, 0x47800000),
        (0x1440A0D94, 4, 0x44E666),
    ):
        m.map_bytes(address, value.to_bytes(width, "little"), writable=True)
    m.map_bytes(0x1431F7FA0, b"\x9c" * 16)
    for pair in range(0x143296810, 0x143296850, 8):
        m.map_bytes(pair, (0x7FFFFFFC).to_bytes(4, "little") + bytes(4), writable=True)

    def read(address, width):
        value = m.read(address, width)
        h.ops.append(("read", address, width, value))
        if on_read:
            changed = on_read(h, address, width, value)
            if changed is not None:
                return changed
        return value

    def write(address, width, value):
        m.write(address, width, value)
        h.ops.append(("write", address, width, value))
        if on_write:
            on_write(h, address, width, value)

    h.ctx = ReplayTaskRebuildStorage(h.obj, read, write)
    h.atomics = ReplayUnitAIMapAtomics(m.compare_exchange_u32, m.fetch_add_u32)

    @contextmanager
    def local(view):
        with m.bind_local(view) as pointer:
            h.frames.append((pointer, view))
            try:
                yield pointer
            finally:
                h.finished.append((pointer, bytes(view)))
                h.frames.pop()

    h.local = local
    runtime = m.runtime_calls(calloc_target=CALLOC)

    def terminal(target, args, data):
        h.import_events.append((target, args))
        if target in h.overrides:
            return h.overrides[target](target, args, data)
        assert runtime.call
        return runtime.call(target, args, data)

    h.imports = ReplayTaskRebuildCalls(terminal)

    def dispatch(target, args, data):
        h.events.append((target, args))
        if target in h.missing:
            raise UnresolvedReplayTaskRebuild(f"missing child{target:x}")
        if target in h.overrides:
            result = h.overrides[target](target, args, data)
        elif target in h.handlers:
            result = h.handlers[target](target, args, data)
        else:
            assert runtime.call
            result = runtime.call(target, args, data)
        if after:
            changed = after(h, target, args, result)
            if changed is not None:
                result = changed
        return result

    h.calls = ReplayTaskRebuildCalls(dispatch)

    def register(bound, targets):
        assert bound.call
        for target in targets:
            h.handlers[target] = bound.call

    register(
        bind_replay_unit_constructor_support(h.ctx, h.calls, bind_local=local, imports=h.imports),
        (0x142D6C268, 0x142D6C270, 0x142D6E3B1),
    )
    register(
        bind_replay_zone_map_construction(h.ctx, h.calls, atomics=h.atomics, imports=h.imports),
        (0x142D6E3B7, 0x142D6BAB4),
    )
    register(
        bind_replay_saved_result(h.ctx, h.calls, atomics=h.atomics, imports=h.imports),
        (0x1402BD7F0, 0x1402BD890, 0x140900620),
    )
    register(
        bind_replay_saved_apply(h.ctx, h.calls, atomics=h.atomics, imports=h.imports),
        (0x1409076B0, 0x1402B9080),
    )
    h.source = ReplaySavedInput(wire)
    register(
        bind_replay_saved_input(
            h.ctx, h.calls, h.source, stream=h.stream, target=IO, result_bytes=bytes(48)
        ),
        (IO,),
    )
    h.bound = bind_replay_player_construction_support(
        h.ctx, h.calls, bind_local=local, scratch=SCRATCH, imports=h.imports
    )
    register(
        h.bound,
        (
            0x141712B50,
            0x140C2AE90,
            0x140C2D4D0,
            0x14115D200,
            0x141143DF0,
            0x141603EF0,
            0x141227140,
            0x140FDDCE0,
        ),
    )
    h.fp = bind_replay_player_marker(
        h.ctx,
        h.calls,
        ReplayPlayerSupportFloatingCalls(None),
        atomics=h.atomics,
        bind_local=local,
        scratch=SCRATCH,
        mxcsr=0x1F80,
    )
    return h


def entry(h, target, *args):
    assert h.bound.call
    return h.bound.call(target, args, None)


@pytest.mark.parametrize("capacity", (0, 1, 200, 1 << 32, (1 << 32) + 2))
@pytest.mark.parametrize("bound", (False, True))
def test_array_saturated_alloc_separate_fill_and_defined_guards(capacity, bound):
    h = setup()
    answer = (
        entry(h, 0x141712B50, h.obj, capacity)
        if bound
        else construct_replay_player_array(h.ctx, h.obj, capacity, calls=h.calls)
    )
    assert answer == h.obj
    count = capacity & 0xFFFFFFFF
    assert h.m.read(h.obj, 4) == count
    assert h.m.read_bytes(h.obj + 4, 16) == bytes(16)
    assert h.m.read(h.obj + 0x18, 4) == 2
    assert h.m.read_bytes(h.obj + 0x1C, 4) == b"\xa5" * 4
    pointer = h.m.read(h.obj + 0x68, 8)
    assert h.m.read_bytes(pointer, count * 8) == bytes(count * 8)
    assert (0x142D6C268, (count * 8,)) in h.events
    assert (0x142D6E3B7, (pointer, 0, count * 8)) in h.import_events


@pytest.mark.parametrize("capacity", (0xFFFFFFFF, 0x80000000, U64))
def test_array_negative_count_saturates_before_required_allocator_refusal(capacity):
    h = setup()
    h.missing.add(0x142D6C268)
    with pytest.raises(UnresolvedReplayTaskRebuild):
        entry(h, 0x141712B50, h.obj, capacity)
    assert h.events[-1] == (0x142D6C268, (U64,))
    assert h.m.read(h.obj + 0x60, 4) == 0xFFFFFFFF
    assert h.m.read(h.obj + 0x68, 8) == 0xA5A5A5A5A5A5A5A5
    assert h.m.read_bytes(h.obj, 4) == b"\xa5" * 4


def test_array_fill_failure_keeps_alloc_publication_before_final_initialization():
    h = setup()
    h.missing.add(0x142D6E3B7)
    with pytest.raises(UnresolvedReplayTaskRebuild):
        entry(h, 0x141712B50, h.obj, 2)
    assert h.m.read(h.obj + 0x68, 8) != 0xA5A5A5A5A5A5A5A5
    assert h.m.read(h.obj, 4) == 0xA5A5A5A5


@pytest.mark.parametrize("bound", (False, True))
def test_hash_actual_node_and_buckets_with_unwritten_payload(bound):
    h = setup()
    answer = (
        entry(h, 0x140C2AE90, h.obj)
        if bound
        else construct_replay_player_hash(h.ctx, h.obj, calls=h.calls)
    )
    node, buckets = h.m.read(h.obj + 8, 8), h.m.read(h.obj + 24, 8)
    assert answer == h.obj
    assert h.m.read(node, 8) == h.m.read(node + 8, 8) == node
    with pytest.raises(ReplayMemoryError):
        h.m.read(node + 16, 8)
    assert h.m.read_bytes(buckets, 128) == node.to_bytes(8, "little") * 16
    assert h.m.read(h.obj + 32, 8) == h.m.read(h.obj + 40, 8) == buckets + 128
    assert h.m.read(h.obj + 48, 8) == 7 and h.m.read(h.obj + 56, 8) == 8
    assert h.m.read(h.obj, 4) == 0x3F800000


def test_hash_second_allocation_uses_current_capacity_but_held_sentinel():
    old = []

    def after(h, target, args, result):
        if target == 0x142D6BA78 and args == (128,):
            pointer = h.m.allocate(32)
            old.append(pointer)
            h.m.write(h.obj + 24, 8, pointer)
            h.m.write(h.obj + 40, 8, pointer + 32)
            h.m.write(h.obj + 8, 8, 0xABCD)

    h = setup(after=after)
    entry(h, 0x140C2AE90, h.obj)
    assert (0x142D6BAB4, (old[0], 32)) in h.events
    with pytest.raises(ReplayMemoryError):
        h.m.read(old[0], 1)
    buckets = h.m.read(h.obj + 24, 8)
    assert h.m.read(buckets, 8) != 0xABCD
    assert h.m.read_bytes(buckets, 128) == h.m.read(buckets, 8).to_bytes(8, "little") * 16


@pytest.mark.parametrize("count", (0, 1, 511, 1 << 61))
def test_hash_release_ignores_header_and_wraps_size(count):
    h = setup()
    pointer = h.m.allocate(16)
    release_replay_player_hash_buckets(h.ctx, U64, pointer, count, calls=h.calls)
    assert (0x142D6BAB4, (pointer, count * 8 & U64)) in h.events
    assert [op[1] for op in h.ops if op[0] == "read"] == [0x143199DD0]


@pytest.mark.parametrize("gap,valid", ((8, True), (39, True), (7, False), (40, False)))
def test_hash_release_large_guard_current_watson_and_terminal_alias(gap, valid):
    h = setup()
    raw = h.m.allocate(0x1100)
    pointer = raw + gap
    h.m.write(pointer - 8, 8, raw)
    h.m.write(0x14319A060, 8, 0x140C2D4D0)  # Owned body token must go terminal once.
    seen = []
    h.overrides[0x140C2D4D0] = lambda target, args, data: seen.append(args)
    if valid:
        release_replay_player_hash_buckets(h.ctx, 0, pointer, 512, calls=h.calls, imports=h.imports)
        assert (0x142D6BAB4, (raw, 4135)) in h.events
    else:
        with pytest.raises(UnresolvedReplayTaskRebuild, match="INT3"):
            release_replay_player_hash_buckets(
                h.ctx, 0, pointer, 512, calls=h.calls, imports=h.imports
            )
        assert seen == [(0, 0, 0, 0, 0)]
        assert not any(target == 0x142D6BAB4 for target, _ in h.events)


@pytest.mark.parametrize("count", (0, 1, 3, (1 << 32) + 2))
def test_rows_current_calloc_full_order_and_upper_count_bits(count):
    h = setup()
    assert (
        construct_replay_player_rows(h.ctx, h.obj, U64, count, calls=h.calls, imports=h.imports)
        == h.obj
    )
    pointer = h.m.read(h.obj + 16, 8)
    assert h.m.read_bytes(pointer, (count & 0xFFFFFFFF) * 32) == bytes((count & 0xFFFFFFFF) * 32)
    assert h.m.read(h.obj + 8, 4) == count & 0xFFFFFFFF
    assert h.m.read(h.obj, 8) == U64
    writes = [(a, w) for op, a, w, _ in h.ops if op == "write"]
    assert writes == [(h.obj + 16, 8), (h.obj + 8, 4), (h.obj + 12, 4), (h.obj, 8)]


def test_rows_current_iat_alias_terminal_and_failure_before_fields():
    h = setup()
    h.m.write(0x143199DC0, 8, 0x14115D200)
    pointer = h.m.allocate(32)
    h.overrides[0x14115D200] = lambda target, args, data: pointer
    assert entry(h, 0x14115D200, h.obj, 7, 1) == h.obj
    assert h.import_events == [(0x14115D200, (1, 32))]
    h2 = setup()
    h2.overrides[CALLOC] = lambda target, args, data: (_ for _ in ()).throw(RuntimeError("calloc"))
    with pytest.raises(RuntimeError, match="calloc"):
        construct_replay_player_rows(
            h2.ctx, h2.obj, 1, 0xFFFFFFFF, calls=h2.calls, imports=h2.imports
        )
    assert h2.import_events == [(CALLOC, (U64, 32))]
    assert h2.m.read_bytes(h2.obj, 24) == b"\xa5" * 24


def test_dual_arrays_current_copies_frees_and_commit_order():
    allocated = []
    saved = []

    def after(h, target, args, result):
        if target == 0x142D6C268:
            allocated.append(result)
            if len(allocated) == 2:
                first, second, redirect = (h.m.allocate(n) for n in (48, 4, 4))
                h.m.write_bytes(first, bytes(range(48)))
                h.m.write_bytes(second, b"ABCD")
                h.m.write_bytes(redirect, b"WXYZ")
                saved[:] = [first, second, redirect]
                h.m.write(h.obj + 12, 4, 1)
                h.m.write(h.obj + 16, 8, first)
                h.m.write(h.obj + 24, 8, second)
        if target == 0x142D6E3B1 and args[0] == allocated[0]:
            h.m.write(h.obj + 12, 4, 2)
        if target == 0x142D6C270 and args == (saved[0],):
            h.m.write(h.obj + 24, 8, saved[2])

    h = setup(after=after)
    assert construct_replay_player_dual_arrays(h.ctx, h.obj, 123, calls=h.calls) == h.obj
    assert h.m.read_bytes(allocated[0], 24) == bytes(range(24))
    assert h.m.read_bytes(allocated[1], 2) == b"AB"
    frees = [args for target, args in h.events if target == 0x142D6C270]
    assert frees == [(saved[0],), (saved[2],)]
    assert h.m.read(h.obj + 12, 4) == 2
    assert h.m.read(h.obj + 8, 4) == 256
    writes = [(a, w, v) for op, a, w, v in h.ops if op == "write"]
    assert writes[-3:] == [
        (h.obj + 24, 8, allocated[1]),
        (h.obj + 16, 8, allocated[0]),
        (h.obj + 8, 4, 256),
    ]


def test_dual_arrays_second_allocation_failure_preserves_prefix_no_commit():
    h = setup()

    def fail(target, args, data):
        if args == (256,):
            raise RuntimeError("second allocation")
        assert h.imports.call
        return h.imports.call(0x142D6BA78, args, data)

    h.overrides[0x142D6C268] = fail
    with pytest.raises(RuntimeError, match="second allocation"):
        entry(h, 0x141143DF0, h.obj, 123)
    assert h.m.read(h.obj, 8) == 123
    assert h.m.read_bytes(h.obj + 8, 24) == bytes(24)


@pytest.mark.parametrize("end,begin,answer", ((32, 0, 2), (0, 16, U64), (0, U64, 0)))
def test_world_count_end_before_begin_wrapped_signed_sar(end, begin, answer):
    h = setup()
    h.m.write(h.obj + 0x770, 8, end)
    h.m.write(h.obj + 0x768, 8, begin)
    assert count_replay_player_world_entries(h.ctx, h.obj) == answer
    assert [op[1] for op in h.ops] == [h.obj + 0x770, h.obj + 0x768]


def test_world_count_current_begin_after_end_read_and_list_padding():
    def on_read(h, address, width, value):
        if address == h.obj + 0x770:
            h.m.write(h.obj + 0x768, 8, 16)

    h = setup(on_read=on_read)
    h.m.write(h.obj + 0x770, 8, 48)
    assert entry(h, 0x141603EF0, h.obj) == 2
    assert construct_replay_player_list(h.ctx, h.obj) == h.obj
    assert h.m.read(h.obj, 8) == 0x1432B3DA8
    assert h.m.read_bytes(h.obj + 8, 10) == bytes(10)
    assert h.m.read_bytes(h.obj + 18, 6) == b"\xa5" * 6


def encoded_zero(seed):
    return (
        (((seed ^ 0xA9834B738A7DD167) + 0x042AC42976FCCEF5) & U64)
        ^ 0xC22D6B496D833977
        ^ 0x6AE24D3352F04511
    )


def test_resource_reindex_exact_copy_highword_and_current_pointer_reload():
    shifted = []

    def on_write(h, address, width, value):
        if shifted and address == shifted[0][0] + 11 * 8:
            h.m.write(h.obj + 0x98, 8, shifted[0][1])

    h = setup(on_write=on_write)
    first, second = h.m.allocate(512), h.m.allocate(512)
    h.m.write_bytes(first, b"F" * 512)
    h.m.write_bytes(second, b"S" * 512)
    shifted.append((first, second))
    h.m.write(h.obj + 0x98, 8, first)
    h.m.write(0x143296810, 4, 2)
    h.m.write(0x143296814, 4, 10)
    reindex_replay_player_resources(h.ctx, h.obj, 64, bind_local=h.local, scratch=SCRATCH.reindex)
    assert h.m.read(first + 11 * 8, 8) == int.from_bytes(b"F" * 8, "little")
    expected = encoded_zero(0x7171717100000000)
    assert h.m.read(second + 2 * 8, 8) == expected
    assert h.finished[-1][1][0x44:0x48] == b"\x71" * 4


def test_resource_null_skips_local_binding_and_dynamic_pair_terminates_after_one():
    h = setup()
    reindex_replay_player_resources(h.ctx, 0, 1, bind_local=None, scratch=b"")
    assert not h.ops and not h.frames
    array = h.m.calloc(64, 8)
    h.m.write(h.obj + 0x98, 8, array)
    h.m.write(0x143296810, 4, 2)
    h.m.write(0x143296814, 4, 10)

    def change(h, address, width, value):
        if address == array + 2 * 8:
            h.m.write(0x143296810, 4, 0x80000000)

    h2 = setup(on_write=change)
    arr2 = h2.m.calloc(64, 8)
    assert arr2 == array
    h2.m.write(h2.obj + 0x98, 8, arr2)
    h2.m.write(0x143296810, 4, 2)
    h2.m.write(0x143296814, 4, 10)
    entry(h2, 0x140FDDCE0, h2.obj, 64)
    assert sum(op == "write" and address == arr2 + 2 * 8 for op, address, _, _ in h2.ops) == 1


def marker(h, *, version=0x41147AE1, expected=42, direct=False):
    invocation = ReplayPlayerMarkerCall(h.out, h.stream, 0xABCDEF, version, expected)
    if direct:
        return read_replay_player_marker(
            h.ctx,
            invocation,
            calls=h.calls,
            atomics=h.atomics,
            bind_local=h.local,
            scratch=SCRATCH.marker,
            mxcsr=0x1F80,
        )
    assert h.fp.call
    return h.fp.call(0x14162CD70, invocation)


@pytest.mark.parametrize("direct", (False, True))
@pytest.mark.parametrize("version", (0, 0x41147AE1, 0x7F800001, 0x4F800000))
def test_marker_real_input_forward_cleanup_and_mixed_word(direct, version):
    h = setup()
    assert marker(h, direct=direct, version=version) == h.out
    assert h.m.read_bytes(h.out, 48) == bytes(41) + b"O" * 7
    targets = [target for target, _ in h.events]
    assert targets.count(IO) == 1
    assert targets.count(0x1409076B0) == 1
    assert targets.count(0x1402BD890) == 2
    assert h.finished[-1][1][0x50] == 42


def test_marker_threshold_skip_uses_current_factor_low_ecx_and_no_input():
    h = setup(wire=b"")
    h.m.write(0x1440A0D94, 4, 0xFFFFFFFF)
    marker(h, version=0x7FC00001)
    assert h.events == []
    assert h.m.read_bytes(h.out, 48) == bytes(41) + b"O" * 7
    assert h.finished[-1][1][0x50] == 0xA5


def test_marker_byte_is_reloaded_after_second_cleanup():
    def after(h, target, args, result):
        if target == 0x1402BD890 and h.frames and args == (h.frames[-1][0] + 0x58,):
            h.m.write(h.frames[-1][0] + 0x50, 1, 99)

    h = setup(after=after)
    seen = []
    h.overrides[0x140A08840] = lambda target, args, data: seen.append(args)
    marker(h)
    assert seen == [(h.out, 0, 0x1432351D0, 0x26, 0x143235238, 0xABCDEF, 99, 42)]
    assert h.m.read_bytes(h.out, 48) == b"O" * 48
    _frame, raw = h.finished[-1]
    assert raw[0x30:0x34] == (99).to_bytes(4, "little")
    assert raw[0x38:0x3C] == (42).to_bytes(4, "little")


def test_marker_mismatch_required_error_builder_refuses_after_prior_real_read():
    h = setup(wire=b"\x01")
    with pytest.raises(UnresolvedReplayTaskRebuild):
        marker(h)
    assert any(target == IO for target, _ in h.events)
    assert h.m.read_bytes(h.out, 48) == b"O" * 48
    assert h.frames == []


def test_marker_nonzero_raw_status_reaches_actual_annotation_after_processed():
    def after(h, target, args, result):
        if target == IO:
            h.m.write(args[1] + 24, 8, 7)  # Explicit returned-status fixture after real read.

    h = setup(after=after)
    seen = []

    def annotate(target, args, data):
        assert h.m.read(args[0] + 40, 1) == 1
        seen.append(args)
        raise RuntimeError("metadata boundary")

    h.overrides[0x140900ED0] = annotate
    with pytest.raises(RuntimeError, match="metadata boundary"):
        marker(h)
    assert seen[0][1:] == (0x1432351D0, 0x21, 0x143235228)
    assert not any(target == 0x1409076B0 for target, _ in h.events)


@pytest.mark.parametrize("flags", ((0, 0), (1, 0), (0, 1), (1, 1)))
def test_marker_forwarded_error_actual_detail_decoding_and_final_forward(flags):
    h = setup()
    first, second = h.m.allocate(96), h.m.allocate(96)
    h.m.write_bytes(first, b"A" * 96)
    h.m.write_bytes(second, b"B" * 96)
    h.m.write(first + 0x59, 1, flags[0])
    h.m.write(second + 0x53, 1, flags[1])
    forwards = []
    ordinary = h.handlers[0x1409076B0]

    def forward(target, args, data):
        answer = ordinary(target, args, data)
        forwards.append(args)
        if len(forwards) == 1:
            h.m.write(args[0] + 24, 8, 0xC0DE)
        return answer

    h.overrides[0x1409076B0] = forward
    h.overrides[0x14162F810] = lambda target, args, data: first
    h.overrides[0x14162E8D0] = lambda target, args, data: second
    details = []

    def annotate(target, args, data):
        details.append(args)
        h.m.write(args[0] + 24, 8, 0)

    h.overrides[0x140900ED0] = annotate
    original_first, original_second = h.m.read_bytes(first, 96), h.m.read_bytes(second, 96)
    marker(h)
    expected_first = bytes(v ^ 0x9C for v in original_first[:90]) + original_first[90:]
    expected_second = bytes(v ^ 0x9C for v in original_second[:84]) + original_second[84:]
    assert h.m.read_bytes(first, 96) == (expected_first if flags[0] else original_first)
    assert h.m.read_bytes(second, 96) == (expected_second if flags[1] else original_second)
    assert details[-1][1:] == (second, 0x21, first)
    assert forwards[-1][0] == h.out


@pytest.mark.parametrize("bad", (0, 0x9FC0, 0x1F81, True))
def test_marker_profile_rejection_before_any_backing_change(bad):
    h = setup()
    with pytest.raises(ValueError):
        read_replay_player_marker(
            h.ctx,
            ReplayPlayerMarkerCall(h.out, h.stream, 1, 0, 42),
            calls=h.calls,
            atomics=h.atomics,
            bind_local=h.local,
            scratch=SCRATCH.marker,
            mxcsr=bad,
        )
    assert not h.events and not h.ops


@pytest.mark.parametrize(
    "field,value", (("xmm3_u32", 1 << 32), ("expected_u8", 256), ("output", -1), ("label", True))
)
def test_mixed_marker_argument_widths(field, value):
    args = dict(output=1, stream=2, label=3, xmm3_u32=0, expected_u8=42)
    args[field] = value
    with pytest.raises(ValueError):
        ReplayPlayerMarkerCall(**args)


@pytest.mark.parametrize(
    "target,arity",
    (
        (0x141712B50, 2),
        (0x140C2AE90, 1),
        (0x140C2D4D0, 3),
        (0x14115D200, 3),
        (0x141143DF0, 2),
        (0x141603EF0, 1),
        (0x141227140, 1),
        (0x140FDDCE0, 2),
    ),
)
def test_scalar_binder_arity_data_and_unknown(target, arity):
    h = setup()
    assert h.bound.call
    with pytest.raises(ValueError):
        h.bound.call(target, (h.obj,) * (arity + 1), None)
    with pytest.raises(ValueError):
        h.bound.call(target, (h.obj,) * arity, memoryview(b"x"))
    with pytest.raises(UnresolvedReplayTaskRebuild):
        h.bound.call(0xBADBAD, (), None)


def test_floating_unknown_delegate_receives_same_raw_invocation():
    h = setup()
    seen = []
    fp = bind_replay_player_marker(
        h.ctx,
        h.calls,
        ReplayPlayerSupportFloatingCalls(lambda target, call: seen.append((target, call))),
        atomics=h.atomics,
        bind_local=h.local,
        scratch=SCRATCH,
        mxcsr=0x1F80,
    )
    invocation = ReplayPlayerMarkerCall(h.out, h.stream, 7, 0xFFC01234, 255)
    assert fp.call
    assert fp.call(0xBADBAD, invocation) is None
    assert seen == [(0xBADBAD, invocation)]


def test_dual_array_fresh_allocations_remain_uninitialized_count_zero():
    h = setup()
    entry(h, 0x141143DF0, h.obj, h.obj)
    assert h.m.read(h.obj, 8) == h.obj
    assert h.m.read(h.obj + 12, 4) == 0
    for offset in (16, 24):
        with pytest.raises(ReplayMemoryError):
            h.m.read(h.m.read(h.obj + offset, 8), 1)
    assert not any(target in (0x142D6E3B1, 0x142D6C270) for target, _ in h.events)


def test_array_memset_holds_allocation_even_after_pointer_publication_mutation():
    saved = []

    def on_write(h, address, width, value):
        if address == h.obj + 0x68:
            saved.append(value)
            h.m.write(h.obj + 0x68, 8, 0xBADBAD)

    h = setup(on_write=on_write)
    entry(h, 0x141712B50, h.obj, 3)
    assert h.m.read(h.obj + 0x68, 8) == 0xBADBAD
    assert h.m.read_bytes(saved[0], 24) == bytes(24)
    assert (0x142D6E3B7, (saved[0], 0, 24)) in h.import_events


def test_rows_null_calloc_still_initializes_exact_header():
    h = setup()
    h.overrides[CALLOC] = lambda target, args, data: 0
    entry(h, 0x14115D200, h.obj, 0xC0DE, 7)
    assert h.m.read(h.obj + 16, 8) == 0
    assert h.m.read(h.obj + 8, 4) == 7
    assert h.m.read(h.obj + 12, 4) == 0
    assert h.m.read(h.obj, 8) == 0xC0DE


def test_resource_original_eight_pair_profile_copies_all64_exact_slots():
    h = setup()
    pairs = (
        (69, 300),
        (136, 325),
        (118, 350),
        (144, 375),
        (110, 400),
        (126, 425),
        (102, 450),
        (156, 475),
    )
    for pair, (old, new) in zip(range(0x143296810, 0x143296850, 8), pairs, strict=True):
        h.m.write(pair, 4, old)
        h.m.write(pair + 4, 4, new)
    array = h.m.allocate(512 * 8)
    h.m.write_bytes(array, b"".join(i.to_bytes(8, "little") for i in range(512)))
    h.m.write(h.obj + 0x98, 8, array)
    entry(h, 0x140FDDCE0, h.obj, 512)
    zero = encoded_zero(0x7171717100000000)
    for old, new in pairs:
        for index in range(8):
            assert h.m.read(array + (new + index + 1) * 8, 8) == old + index
            assert h.m.read(array + (old + index) * 8, 8) == zero


@pytest.mark.parametrize("count", (0, 0xFFFFFFFF, 1 << 32))
def test_resource_signed_count_bounds_skip_unavailable_player_array(count):
    h = setup()
    for pair in range(0x143296810, 0x143296850, 8):
        h.m.write(pair, 4, 1)
        h.m.write(pair + 4, 4, 10)
    entry(h, 0x140FDDCE0, h.obj, count)
    assert not any(op == "read" and address == h.obj + 0x98 for op, address, _, _ in h.ops)
    assert len([op for op in h.ops if 0x143296810 <= op[1] < 0x143296850]) == 8 * 9


@pytest.mark.parametrize("strong,weak", ((1, 1), (1, 2), (2, 1), (2, 2)))
def test_marker_real_control_counts_and_fresh_weak_virtual(strong, weak):
    controls, callbacks = [], []

    def after(h, target, args, result):
        if target == IO:
            control, first, second = (h.m.calloc(1, 16) for _ in range(3))
            controls.extend((control, first, second))
            h.m.write(control, 8, first)
            h.m.write(control + 8, 4, strong)
            h.m.write(control + 12, 4, weak)
            h.m.write(first, 8, 0xCA11)
            h.m.write(first + 8, 8, 0xCA12)
            h.m.write(second + 8, 8, 0xCA13)
            h.m.write(args[1] + 32, 8, control)

    h = setup(after=after)

    def destroy(target, args, data):
        callbacks.append(target)
        h.m.write(args[0], 8, controls[2])

    h.overrides[0xCA11] = destroy
    h.overrides[0xCA13] = lambda target, args, data: callbacks.append(target)
    marker(h)
    control = controls[0]
    assert h.m.read(control + 8, 4) == strong - 1
    assert h.m.read(control + 12, 4) == weak - (strong == 1)
    expected = ([0xCA11, 0xCA13] if weak == 1 else [0xCA11]) if strong == 1 else []
    assert callbacks == expected


def test_marker_current_multiplier_binding_controls_threshold():
    h = setup()
    h.m.write(0x143235268, 4, 0x3F800000)
    h.m.write(0x1440A0D94, 4, 1)
    marker(h, version=0x3F800000)
    assert any(target == IO for target, _ in h.events)
    reads = [address for op, address, _, _ in h.ops if op == "read"]
    assert reads.index(0x143235268) < reads.index(0x1440A0D94)


def test_marker_second_cleanup_failure_retains_processed_without_success():
    h = setup()
    real = h.handlers[0x1402BD890]

    def cleanup(target, args, data):
        if args == (h.frames[-1][0] + 0x58,):
            raise RuntimeError("second cleanup")
        return real(target, args, data)

    h.overrides[0x1402BD890] = cleanup
    with pytest.raises(RuntimeError, match="second cleanup"):
        marker(h)
    assert h.m.read_bytes(h.out, 48) == b"O" * 48
    _frame, seed = h.finished[-1]
    assert seed[0x50] == 42 and seed[0x80] == seed[0xB0] == 1


@pytest.mark.parametrize("missing", (IO, 0x1409076B0, 0x1402BD890))
def test_marker_required_children_fail_after_prior_stores(missing):
    h = setup()
    h.missing.add(missing)
    with pytest.raises(UnresolvedReplayTaskRebuild, match="missing child"):
        marker(h)
    assert h.m.read_bytes(h.out, 48) == b"O" * 48
    assert h.frames == []
