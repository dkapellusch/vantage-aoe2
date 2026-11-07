"""Actual input copying, cursor commits and explicit Result capability profile."""

from __future__ import annotations

import pytest

from vantage.replay_memory import ReplayMemory, ReplayMemoryError
from vantage.replay_saved_input import ReplaySavedInput, bind_replay_saved_input
from vantage.replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
)


def storage(memory):
    return ReplayTaskRebuildStorage(1, memory.read, memory.write)


def invoke(bound, *args):
    assert bound.call is not None
    return bound.call(0xA110, args, None)


def test_exact_reads_commit_only_the_requested_span_and_explicit_result_bytes() -> None:
    memory = ReplayMemory()
    destination, result = memory.allocate(20), memory.allocate(48)
    memory.write_bytes(destination, b"-" * 20)
    source = ReplaySavedInput(bytes(range(24)), position=3)
    profile = bytes(range(48))
    bound = bind_replay_saved_input(
        storage(memory),
        ReplayTaskRebuildCalls(None),
        source,
        stream=0x1000,
        target=0xA110,
        result_bytes=profile,
    )
    assert invoke(bound, 0x1000, result, destination + 2, 16) == result
    assert memory.read_bytes(destination, 20) == b"--" + bytes(range(3, 19)) + b"--"
    assert memory.read_bytes(result, 48) == profile
    assert source.position == 19 and source.remaining == 5
    invoke(bound, 0x1000, result, destination + 1, 5)
    assert memory.read_bytes(destination + 1, 5) == bytes(range(19, 24))
    assert source.position == 24 and source.remaining == 0


def test_truncated_read_retains_cursor_destination_and_result_without_partial_copy() -> None:
    memory = ReplayMemory()
    destination, result = memory.allocate(4), memory.allocate(48)
    source = ReplaySavedInput(b"ab")
    bound = bind_replay_saved_input(
        storage(memory),
        ReplayTaskRebuildCalls(None),
        source,
        stream=1,
        target=0xA110,
        result_bytes=bytes(48),
    )
    before = memory.snapshot()
    with pytest.raises(UnresolvedReplayTaskRebuild, match="exceeds remaining"):
        invoke(bound, 1, result, destination, 3)
    assert source.position == 0 and memory.snapshot() == before


def test_failed_destination_does_not_advance_but_failed_result_keeps_copy_and_cursor() -> None:
    memory = ReplayMemory()
    source = ReplaySavedInput(b"abcd")
    destination, result = memory.allocate(4), memory.allocate(48)
    bound = bind_replay_saved_input(
        storage(memory),
        ReplayTaskRebuildCalls(None),
        source,
        stream=1,
        target=0xA110,
        result_bytes=bytes(48),
    )
    with pytest.raises(ReplayMemoryError, match="unmapped"):
        invoke(bound, 1, result, 0xDEAD, 2)
    assert source.position == 0
    with pytest.raises(ReplayMemoryError, match="unmapped"):
        invoke(bound, 1, 0xDEAD, destination, 2)
    assert source.position == 2 and memory.read_bytes(destination, 2) == b"ab"


def test_zero_extent_at_eof_does_not_touch_destination_but_still_writes_result() -> None:
    memory = ReplayMemory()
    result = memory.allocate(48)
    source = ReplaySavedInput(b"")
    bound = bind_replay_saved_input(
        storage(memory),
        ReplayTaskRebuildCalls(None),
        source,
        stream=1,
        target=0xA110,
        result_bytes=b"R" * 48,
    )
    invoke(bound, 1, result, 0xDEAD, 0)
    assert source.position == 0 and memory.read_bytes(result, 48) == b"R" * 48


@pytest.mark.parametrize(("stream", "count"), [(2, 1), (1, -1), (1, 1 << 64), (True, 1)])
def test_foreign_stream_and_invalid_arguments_refuse_before_effects(stream, count) -> None:
    memory = ReplayMemory()
    source = ReplaySavedInput(b"ab")
    bound = bind_replay_saved_input(
        storage(memory),
        ReplayTaskRebuildCalls(None),
        source,
        stream=1,
        target=0xA110,
        result_bytes=bytes(48),
    )
    before = memory.snapshot()
    with pytest.raises(ValueError):
        invoke(bound, stream, 0xDEAD, 0xBAD, count)
    assert source.position == 0 and memory.snapshot() == before


@pytest.mark.parametrize("target", [0, -1, 0x140D267D0, 1 << 64, True])
def test_capability_identity_requires_explicit_nonzero_engine_namespace(target) -> None:
    memory = ReplayMemory()
    with pytest.raises(ValueError):
        bind_replay_saved_input(
            storage(memory),
            ReplayTaskRebuildCalls(None),
            ReplaySavedInput(b""),
            stream=1,
            target=target,
            result_bytes=bytes(48),
        )


def test_unknown_method_delegates_original_payload_and_preserves_cursor() -> None:
    memory = ReplayMemory()
    source = ReplaySavedInput(b"ab")
    payload = memoryview(bytearray(b"input"))
    seen = []

    def lower(target, args, data):
        seen.append((target, args, data))
        return 123

    bound = bind_replay_saved_input(
        storage(memory),
        ReplayTaskRebuildCalls(lower),
        source,
        stream=1,
        target=0xA110,
        result_bytes=bytes(48),
    )
    assert bound.call is not None
    assert bound.call(0xB1, (2, 3), payload) == 123
    assert seen == [(0xB1, (2, 3), payload)] and source.position == 0


@pytest.mark.parametrize("profile", [bytes(47), bytes(49), bytearray(48), None])
def test_result_profile_has_no_implicit_success_default(profile) -> None:
    memory = ReplayMemory()
    with pytest.raises(ValueError, match="explicit saved input48B Result"):
        bind_replay_saved_input(
            storage(memory),
            ReplayTaskRebuildCalls(None),
            ReplaySavedInput(b""),
            stream=1,
            target=0xA110,
            result_bytes=profile,
        )
