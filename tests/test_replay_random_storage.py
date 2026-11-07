"""Owned RNG effects against retained native outputs, current reads and failures."""

from __future__ import annotations

import gzip
import json
import struct
from pathlib import Path

import pytest

from vantage.replay_memory import ReplayMemory, ReplayMemoryError
from vantage.replay_random_storage import (
    bind_replay_random_storage,
    draw_replay_random_i15_storage,
    log_replay_random_draw_disabled,
)
from vantage.replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
)

STREAM = 0x1443530F0
WORDS = tuple(range(1, 17))


def context(memory: ReplayMemory) -> ReplayTaskRebuildStorage:
    return ReplayTaskRebuildStorage(1, memory.read, memory.write)


def stream(memory: ReplayMemory, words=WORDS, index=0, calls=0, last=0xAABBCCDD):
    memory.map_bytes(STREAM + 0x18, calls.to_bytes(4, "little"))
    memory.map_bytes(STREAM + 0x20, b"\0")  # Explicit disabled logging profile.
    memory.map_bytes(STREAM + 0x24, struct.pack("<17I", *words, index))
    memory.map_bytes(STREAM + 0x88, last.to_bytes(4, "little"))


def draw(memory: ReplayMemory) -> int:
    calls = bind_replay_random_storage(context(memory), ReplayTaskRebuildCalls(None))
    assert calls.call is not None
    result = calls.call(0x140903E40, (STREAM, 0xCAFE, 0xFFFFFFFF00000184), None)
    assert result is not None
    return result


def test_all3840_retained_native_masked_draws_match_value_and_actual_memory_state() -> None:
    raw = (Path(__file__).parent / "fixtures/native_replay_random_54800.json.gz").read_bytes()
    count = 0
    for inputs, expected in json.loads(gzip.decompress(raw)):
        operation, _, calls, last, index, *words = inputs
        if operation != 1:
            continue
        memory = ReplayMemory()
        stream(memory, words, index, calls, last)
        value = draw(memory)
        actual = [
            value,
            memory.read(STREAM + 0x18, 4),
            memory.read(STREAM + 0x88, 4),
            memory.read(STREAM + 0x64, 4),
            *struct.unpack("<16I", memory.read_bytes(STREAM + 0x24, 64)),
        ]
        assert actual == expected
        count += 1
    assert count == 3840


def test_logger_failure_retains_engine_and_call_count_but_not_last_mask_commit() -> None:
    memory = ReplayMemory()
    stream(memory, calls=0xFFFFFFFF)
    before = memory.read_bytes(STREAM + 0x24, 68)
    failure = RuntimeError("logger failed")
    seen = []

    def logger(target: int, args: tuple[int, ...], data: memoryview | None) -> None:
        seen.append((target, args, data))
        assert memory.read(STREAM + 0x18, 4) == 0
        assert memory.read(STREAM + 0x88, 4) == 0xAABBCCDD
        raise failure

    with pytest.raises(RuntimeError) as caught:
        draw_replay_random_i15_storage(
            context(memory), STREAM, 0xCAFE, 0x123400000184, calls=ReplayTaskRebuildCalls(logger)
        )
    assert caught.value is failure
    assert len(seen) == 1 and seen[0][0] == 0x140902700
    assert seen[0][1][0] == STREAM and seen[0][1][2:] == (0xCAFE, 0x184)
    assert memory.read_bytes(STREAM + 0x24, 68) != before
    assert memory.read(STREAM + 0x88, 4) == 0xAABBCCDD


def test_repeated_word_operands_are_current_reads_not_a_cached_functional_snapshot() -> None:
    memory = ReplayMemory()
    words = tuple(range(1, 17))
    stream(memory, words)
    third = STREAM + 0x24 + 13 * 4
    reads = []

    def read(address: int, width: int) -> int:
        value = memory.read(address, width)
        reads.append((address, width))
        if address == third and reads.count((third, 4)) == 1:
            memory.write(third, 4, 0x11223344)
        return value

    current = ReplayTaskRebuildStorage(1, read, memory.write)
    actual = draw_replay_random_i15_storage(
        current, STREAM, 0, 0, calls=ReplayTaskRebuildCalls(lambda *_: None)
    )
    b = (((words[0] * 2 ^ words[13]) << 15) ^ 0x11223344 ^ words[0]) & 0xFFFFFFFF
    c = words[9] >> 11 ^ words[9]
    combined = b ^ c
    expected = (
        ((((c << 10 ^ b) << 13 ^ (combined & 0xFED22169)) << 3 ^ words[15]) << 2)
        ^ words[15]
        ^ combined
        ^ b
    ) & 0xFFFFFFFF
    assert memory.read(STREAM + 0x24, 4) == combined
    assert memory.read(STREAM + 0x24 + 15 * 4, 4) == expected
    assert actual == expected & 0x7FFF
    assert reads.count((third, 4)) == reads.count((STREAM + 0x24 + 9 * 4, 4)) == 2


def test_index_is_reread_after_both_word_publications_and_held_mask_survives_logger() -> None:
    memory = ReplayMemory()
    stream(memory)

    def write(address: int, width: int, value: int) -> None:
        memory.write(address, width, value)
        if address == STREAM + 0x24:
            memory.write(STREAM + 0x64, 4, 2)
        elif address == STREAM + 0x24 + 4:
            memory.write(STREAM + 0x64, 4, 6)

    def logger(target: int, args: tuple[int, ...], data: memoryview | None) -> None:
        assert target == 0x140902700 and args[1] == 7
        memory.write(STREAM + 0x24 + 24, 4, 0xDEADBEEF)
        memory.write(STREAM + 0x88, 4, 0xBAD)

    current = ReplayTaskRebuildStorage(1, memory.read, write)
    assert (
        draw_replay_random_i15_storage(current, STREAM, 0, 0, calls=ReplayTaskRebuildCalls(logger))
        == 7
    )
    assert memory.read(STREAM + 0x64, 4) == 6 and memory.read(STREAM + 0x88, 4) == 7


def test_missing_stream_stops_at_initial_call_count_rmw() -> None:
    memory = ReplayMemory()
    with pytest.raises(ReplayMemoryError, match="unmapped replay address144353108"):
        draw(memory)
    assert memory.mapped_bytes == 0


def test_disabled_logger_global_gate_reads_secondary_byte_even_when_global_enable_is_zero() -> None:
    memory = ReplayMemory()
    memory.map_bytes(STREAM + 0x20, b"\1")
    memory.map_bytes(0x14435505E, b"\0")
    with pytest.raises(ReplayMemoryError, match="unmapped replay address14427c9b0"):
        log_replay_random_draw_disabled(context(memory), STREAM)
    memory.map_bytes(0x14427C9B0, b"\1")
    log_replay_random_draw_disabled(context(memory), STREAM)
    memory.write(0x14435505E, 1, 2)
    with pytest.raises(UnresolvedReplayTaskRebuild, match="enabled random logging"):
        log_replay_random_draw_disabled(context(memory), STREAM)


def test_snapshot_continuation_reproduces_owned_rng_bytes_and_metadata() -> None:
    memory = ReplayMemory()
    stream(memory)
    for _ in range(3):
        draw(memory)
    saved = memory.snapshot()
    values = [draw(memory) for _ in range(10)]
    restored = ReplayMemory.from_snapshot(saved)
    assert [draw(restored) for _ in range(10)] == values
    assert restored.snapshot() == memory.snapshot()
