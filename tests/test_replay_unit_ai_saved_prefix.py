"""Actual saved-AI input/Result composition and native dispatch frontiers."""

from __future__ import annotations

import pytest

from vantage.replay_memory import ReplayMemory
from vantage.replay_saved_input import ReplaySavedInput, bind_replay_saved_input
from vantage.replay_saved_result import bind_replay_saved_result
from vantage.replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
)
from vantage.replay_unit_ai_map import ReplayUnitAIMapAtomics
from vantage.replay_unit_ai_saved_prefix import read_replay_unit_ai_saved_prefix

FIELDS = (
    0x10,
    0x3C,
    0x40,
    0x44,
    0x48,
    0x4C,
    0x50,
    0x54,
    0x58,
    0x5C,
    0x68,
    0x64,
    0x6C,
    0x70,
    0x164,
    0x168,
    0x170,
    0x16C,
    0x174,
    0x178,
    0x17C,
)


def setup(data, version=0x44E666):
    memory = ReplayMemory()
    ai, stream, table = memory.allocate(0x210), memory.allocate(8), memory.allocate(32)
    memory.write_bytes(ai, b"\x5a" * 0x210)
    memory.write(stream, 8, table)
    memory.write(table + 24, 8, 0xA110)
    memory.map_bytes(0x1440A0D94, version.to_bytes(4, "little"))
    storage = ReplayTaskRebuildStorage(ai, memory.read, memory.write)
    atomics = ReplayUnitAIMapAtomics(memory.compare_exchange_u32, memory.fetch_add_u32)
    source = ReplaySavedInput(data)
    return memory, ai, stream, table, storage, atomics, source


def run(parts, calls):
    memory, ai, stream, _, storage, atomics, _ = parts
    read_replay_unit_ai_saved_prefix(
        storage,
        ai,
        stream,
        calls=calls,
        atomics=atomics,
        bind_local=memory.bind_local,
        legacy_scratch=b"old!",
    )


def test_modern_prefix_copies_exact108_bytes_with_one16B_read_and_native_cleanup_split():
    raw = bytes(range(108))
    parts = setup(raw + b"count")
    memory, ai, stream, _, storage, atomics, source = parts
    seen, processed = [], []
    runtime = memory.runtime_calls()
    io = bind_replay_saved_input(
        storage, runtime, source, stream=stream, target=0xA110, result_bytes=bytes(48)
    )
    clean = bind_replay_saved_result(storage, io, atomics=atomics, imports=runtime)

    def call(target, args, data):
        seen.append((target, args))
        if target in (0x1402BD890, 0x140900620):
            processed.append(memory.read(args[0] + 40, 1))
        assert clean.call is not None
        answer = clean.call(target, args, data)
        return 0xDEAD if target == 0xA110 else answer

    run(parts, ReplayTaskRebuildCalls(call))
    reads = [args for target, args in seen if target == 0xA110]
    assert [args[3] for args in reads] == [4] * 23 + [16]
    assert [args[2] - ai for args in reads] == [*FIELDS, 0x60, 0x194, 0x184]
    assert [target for target, _ in seen if target != 0xA110] == (
        [0x1402BD890] * 10 + [0x140900620] * 14
    )
    assert len({args[1] for args in reads}) == 24 and processed == [1] * 24
    assert source.position == 108 and source.remaining == 5
    for index, offset in enumerate(FIELDS):
        assert memory.read_bytes(ai + offset, 4) == raw[index * 4 : index * 4 + 4]
    assert memory.read_bytes(ai + 0x60, 4) == raw[84:88]
    assert memory.read_bytes(ai + 0x194, 4) == raw[88:92]
    assert memory.read_bytes(ai + 0x184, 16) == raw[92:108]
    assert memory.read_bytes(ai + 0x14, 4) == b"\x5a" * 4
    assert memory.read_bytes(ai + 0x18, 0x24) == b"\x5a" * 0x24
    assert memory.read_bytes(ai + 0x1F8, 24) == b"\x5a" * 24


@pytest.mark.parametrize(
    ("version", "legacy"),
    [
        (0x1407AD, False),
        (0x1407AE, True),
        (0x1A3332, True),
        (0x1A3333, False),
        (0xFFFFFFFF, False),
        (0, False),
    ],
)
def test_unsigned_legacy_interval_uses_two_reads_to_same_private_word(version, legacy):
    parts = setup(bytes(range(116)), version)
    memory, ai, stream, _, storage, atomics, source = parts
    seen = []
    runtime = memory.runtime_calls()
    io = bind_replay_saved_input(
        storage, runtime, source, stream=stream, target=0xA110, result_bytes=bytes(48)
    )
    clean = bind_replay_saved_result(storage, io, atomics=atomics)

    def call(target, args, data):
        if target == 0xA110:
            seen.append(args)
        assert clean.call is not None
        return clean.call(target, args, data)

    run(parts, ReplayTaskRebuildCalls(call))
    assert len(seen) == (26 if legacy else 24)
    assert source.position == (116 if legacy else 108)
    if legacy:
        assert seen[21][2] == seen[22][2]
        assert not ai <= seen[21][2] < ai + 0x210
    assert memory.read_bytes(ai + 0x60, 4) == bytes(
        range(92 if legacy else 84, 96 if legacy else 88)
    )


def test_stream_method_is_current_after_read_callback_changes_vptr() -> None:
    parts = setup(bytes(range(108)))
    memory, _, stream, _, storage, atomics, source = parts
    replacement = memory.allocate(32)
    memory.write(replacement + 24, 8, 0xA111)
    seen = []
    runtime = memory.runtime_calls()
    io2 = bind_replay_saved_input(
        storage, runtime, source, stream=stream, target=0xA111, result_bytes=bytes(48)
    )
    io1 = bind_replay_saved_input(
        storage, io2, source, stream=stream, target=0xA110, result_bytes=bytes(48)
    )
    clean = bind_replay_saved_result(storage, io1, atomics=atomics)

    def call(target, args, data):
        assert clean.call is not None
        answer = clean.call(target, args, data)
        if target in (0xA110, 0xA111):
            seen.append(target)
            if target == 0xA110:
                memory.write(stream, 8, replacement)
        return answer

    run(parts, ReplayTaskRebuildCalls(call))
    assert seen == [0xA110] + [0xA111] * 23


def test_version_is_sampled_after_reached_field17c_cleanup() -> None:
    parts = setup(bytes(range(116)))
    memory, _, stream, _, storage, atomics, source = parts
    runtime = memory.runtime_calls()
    io = bind_replay_saved_input(
        storage, runtime, source, stream=stream, target=0xA110, result_bytes=bytes(48)
    )
    clean = bind_replay_saved_result(storage, io, atomics=atomics)

    def call(target, args, data):
        assert clean.call is not None
        answer = clean.call(target, args, data)
        if target == 0x140900620 and source.position == 84:
            memory.write(0x1440A0D94, 4, 0x1407AE)
        return answer

    run(parts, ReplayTaskRebuildCalls(call))
    assert source.position == 116


def test_first_inline_cleanup_and_eleventh_finalizer_are_required_after_read_effects() -> None:
    parts = setup(bytes(range(108)))
    memory, ai, stream, _, storage, atomics, source = parts
    io = bind_replay_saved_input(
        storage,
        ReplayTaskRebuildCalls(None),
        source,
        stream=stream,
        target=0xA110,
        result_bytes=bytes(48),
    )
    with pytest.raises(UnresolvedReplayTaskRebuild, match="1402bd890"):
        run(parts, io)
    assert source.position == 4 and memory.read_bytes(ai + 0x10, 4) == bytes(range(4))
    # Now run a fresh profile with the ten actual vector cleanups available,
    # while deliberately leaving the distinct eleventh finalizer unavailable.
    parts = setup(bytes(range(108)))
    memory, ai, stream, _, storage, atomics, source = parts
    io = bind_replay_saved_input(
        storage,
        ReplayTaskRebuildCalls(None),
        source,
        stream=stream,
        target=0xA110,
        result_bytes=bytes(48),
    )
    cleanup = bind_replay_saved_result(storage, io, atomics=atomics)

    def limited(target, args, data):
        if target == 0x140900620:
            raise UnresolvedReplayTaskRebuild("actual finalizer unavailable")
        assert cleanup.call is not None
        return cleanup.call(target, args, data)

    with pytest.raises(UnresolvedReplayTaskRebuild, match="actual finalizer unavailable"):
        run(parts, ReplayTaskRebuildCalls(limited))
    assert source.position == 44 and memory.read_bytes(ai + 0x68, 4) == bytes(range(40, 44))
    assert memory.read_bytes(ai + 0x64, 4) == b"\x5a" * 4


def test_nonzero_current_result_status_refuses_before_processed_store_or_cleanup() -> None:
    parts = setup(bytes(range(108)))
    memory, ai, stream, _, storage, _, source = parts
    profile = bytearray(48)
    profile[24] = 1
    profile[40] = 0xAB
    io = bind_replay_saved_input(
        storage,
        ReplayTaskRebuildCalls(None),
        source,
        stream=stream,
        target=0xA110,
        result_bytes=bytes(profile),
    )
    seen = []

    def call(target, args, data):
        assert io.call is not None
        seen.append(target)
        answer = io.call(target, args, data)
        assert memory.read(args[1] + 40, 1) == 0xAB
        return answer

    with pytest.raises(UnresolvedReplayTaskRebuild, match="returned-error/logging frontier"):
        run(parts, ReplayTaskRebuildCalls(call))
    assert seen == [0xA110] and source.position == 4
    assert memory.read_bytes(ai + 0x10, 4) == bytes(range(4))
    assert memory.read_bytes(ai + 0x3C, 4) == b"\x5a" * 4


def test_exact_input_truncation_keeps_previous_copies_without_advancing_failed_read() -> None:
    parts = setup(bytes(range(20)))
    memory, ai, stream, _, storage, atomics, source = parts
    io = bind_replay_saved_input(
        storage,
        memory.runtime_calls(),
        source,
        stream=stream,
        target=0xA110,
        result_bytes=bytes(48),
    )
    clean = bind_replay_saved_result(storage, io, atomics=atomics)
    with pytest.raises(UnresolvedReplayTaskRebuild, match="exceeds remaining"):
        run(parts, clean)
    assert source.position == 20
    assert memory.read_bytes(ai + 0x48, 4) == bytes(range(16, 20))
    assert memory.read_bytes(ai + 0x4C, 4) == b"\x5a" * 4
