"""Owned localization services: exact admitted effects and explicit refusals."""

from __future__ import annotations

import pytest

from vantage.replay_localization_runtime import (
    ReplayLocalizationRuntime,
    ReplayLocalizationTargets,
)
from vantage.replay_memory import ReplayMemory, ReplayMemoryError, ReplayMemoryRuntimeError
from vantage.replay_task_rebuild import ReplayTaskRebuildCalls, UnresolvedReplayTaskRebuild

TARGETS = ReplayLocalizationTargets(0xAB10, 0xAB20, 0xAB30, 0xAB40, 0xAB50)
U64 = (1 << 64) - 1


def invoke(runtime, target, *args, data=None):
    calls = runtime.calls()
    assert calls.call
    return calls.call(target, args, data)


@pytest.mark.parametrize(
    "raw,expected",
    [
        (0, b"0"),
        (1, b"1"),
        (0x7FFFFFFF, b"2147483647"),
        (0x80000000, b"-2147483648"),
        (0xFFFFFFFF, b"-1"),
        (U64, b"-1"),
        (0x1234567800000010, b"16"),
    ],
)
def test_decimal_conversion_consumes_signed_low_dword_and_changes_only_text_prefix(raw, expected):
    memory = ReplayMemory()
    runtime = ReplayLocalizationRuntime(memory, TARGETS)
    buffer = memory.allocate(16)
    memory.fill(buffer, 0xA5, 16)
    assert invoke(runtime, TARGETS.conversion, raw, buffer, 16, 10) == 0
    assert memory.read_bytes(buffer, 16) == expected + b"\0" + b"\xa5" * (15 - len(expected))


@pytest.mark.parametrize("size,radix", [(15, 10), (17, 10), (16, 16), (0, 10)])
def test_unadmitted_conversion_profile_refuses_without_writes(size, radix):
    memory = ReplayMemory()
    runtime = ReplayLocalizationRuntime(memory, TARGETS)
    buffer = memory.allocate(16)
    memory.fill(buffer, 0xA5, 16)
    with pytest.raises(UnresolvedReplayTaskRebuild, match="decimal conversion"):
        invoke(runtime, TARGETS.conversion, 1, buffer, size, radix)
    assert memory.read_bytes(buffer, 16) == b"\xa5" * 16


def test_conversion_requires_actual_writable_backing():
    memory = ReplayMemory()
    runtime = ReplayLocalizationRuntime(memory, TARGETS)
    memory.map_bytes(0x1000, bytes(16), writable=False)
    with pytest.raises(ReplayMemoryError):
        invoke(runtime, TARGETS.conversion, 123, 0x1000, 16, 10)
    assert memory.read_bytes(0x1000, 16) == bytes(16)


@pytest.mark.parametrize(
    "left,right,result",
    [
        (b"", b"", 0),
        (b"A", b"A", 0),
        (b"A", b"B", 0xFFFFFFFF),
        (b"AB", b"A", 1),
        (b"\x80", b"\x7f", 1),
        (b"\xff", b"\x80", 1),
    ],
)
def test_comparison_is_unsigned_bytes_and_returns_normalized_raw_eax(left, right, result):
    memory = ReplayMemory()
    runtime = ReplayLocalizationRuntime(memory, TARGETS)
    lhs, rhs = memory.allocate(len(left) + 1), memory.allocate(len(right) + 1)
    memory.write_bytes(lhs, left + b"\0")
    memory.write_bytes(rhs, right + b"\0")
    before = memory.snapshot()
    assert invoke(runtime, TARGETS.comparison, lhs, rhs) == result
    assert memory.snapshot() == before


def test_comparison_requires_complete_cstrings_even_after_an_early_mismatch():
    memory = ReplayMemory(max_bytes=256)
    runtime = ReplayLocalizationRuntime(memory, TARGETS)
    lhs, rhs = memory.allocate(2), memory.allocate(2)
    memory.write(lhs, 1, ord("A"))
    memory.write_bytes(rhs, b"B\0")
    with pytest.raises(ReplayMemoryError):
        invoke(runtime, TARGETS.comparison, lhs, rhs)


def test_mutex_registration_requires_fresh_defined_zero_and_is_unique():
    memory = ReplayMemory()
    runtime = ReplayLocalizationRuntime(memory, TARGETS)
    mutex = memory.allocate(80)
    with pytest.raises(ReplayMemoryError):
        runtime.register_mutex(mutex)
    memory.write(mutex + 0x4C, 4, 1)
    with pytest.raises(ValueError, match="fresh defined zero"):
        runtime.register_mutex(mutex)
    memory.write(mutex + 0x4C, 4, 0)
    runtime.register_mutex(mutex)
    with pytest.raises(ValueError, match="already registered"):
        runtime.register_mutex(mutex)


def test_registered_mutex_lock_and_unlock_mutate_current_recursive_count():
    memory = ReplayMemory()
    runtime = ReplayLocalizationRuntime(memory, TARGETS)
    mutex = memory.allocate(80)
    memory.write(mutex + 0x4C, 4, 0)
    runtime.register_mutex(mutex)
    for expected in (1, 2):
        assert invoke(runtime, TARGETS.lock, mutex) == 0
        assert memory.read(mutex + 0x4C, 4) == expected
    for expected in (1, 0):
        assert invoke(runtime, TARGETS.unlock, mutex) == 0
        assert memory.read(mutex + 0x4C, 4) == expected
    with pytest.raises(UnresolvedReplayTaskRebuild, match="unlock exceeds"):
        invoke(runtime, TARGETS.unlock, mutex)
    assert memory.read(mutex + 0x4C, 4) == 0


@pytest.mark.parametrize("target", [TARGETS.lock, TARGETS.unlock])
def test_unknown_mutex_never_manufactures_success(target):
    memory = ReplayMemory()
    runtime = ReplayLocalizationRuntime(memory, TARGETS)
    mutex = memory.allocate(80)
    memory.write(mutex + 0x4C, 4, 0)
    with pytest.raises(UnresolvedReplayTaskRebuild, match="unregistered"):
        invoke(runtime, target, mutex)
    assert memory.read(mutex + 0x4C, 4) == 0


@pytest.mark.parametrize("count", [0x7FFFFFFF, 0x80000000, 0xFFFFFFFF])
def test_unsupported_current_lock_counts_refuse_without_mutation(count):
    memory = ReplayMemory()
    runtime = ReplayLocalizationRuntime(memory, TARGETS)
    mutex = memory.allocate(80)
    memory.write(mutex + 0x4C, 4, 0)
    runtime.register_mutex(mutex)
    memory.write(mutex + 0x4C, 4, count)
    with pytest.raises(UnresolvedReplayTaskRebuild, match="count exceeds"):
        invoke(runtime, TARGETS.lock, mutex)
    assert memory.read(mutex + 0x4C, 4) == count


def test_lock_can_reach_source_overflow_sentinel_for_the_callers_real_error_path():
    memory = ReplayMemory()
    runtime = ReplayLocalizationRuntime(memory, TARGETS)
    mutex = memory.allocate(80)
    memory.write(mutex + 0x4C, 4, 0)
    runtime.register_mutex(mutex)
    memory.write(mutex + 0x4C, 4, 0x7FFFFFFE)
    assert invoke(runtime, TARGETS.lock, mutex) == 0
    assert memory.read(mutex + 0x4C, 4) == 0x7FFFFFFF


def test_error_service_terminates_with_actual_owned_target_and_raw_code():
    runtime = ReplayLocalizationRuntime(ReplayMemory(), TARGETS)
    with pytest.raises(ReplayMemoryRuntimeError) as raised:
        invoke(runtime, TARGETS.error, 6)
    assert raised.value.target == TARGETS.error and raised.value.args_words == (6,)


@pytest.mark.parametrize(
    "target,args",
    [
        (TARGETS.conversion, (1, 2, 16)),
        (TARGETS.comparison, (1,)),
        (TARGETS.lock, ()),
        (TARGETS.unlock, ()),
        (TARGETS.error, ()),
    ],
)
def test_service_arity_validation_precedes_backing_effects(target, args):
    memory = ReplayMemory()
    runtime = ReplayLocalizationRuntime(memory, TARGETS)
    before = memory.snapshot()
    with pytest.raises(ValueError, match="malformed"):
        invoke(runtime, target, *args)
    assert memory.snapshot() == before


def test_unknown_delegate_preserves_data_identity_arguments_and_raw_return():
    seen, view = [], memoryview(bytearray(b"abc"))

    def delegate(target, args, data):
        seen.append((target, args, data))
        return 0xCAFE

    runtime = ReplayLocalizationRuntime(ReplayMemory(), TARGETS, ReplayTaskRebuildCalls(delegate))
    assert invoke(runtime, 0x123, 7, data=view) == 0xCAFE
    assert seen == [(0x123, (7,), view)] and seen[0][2] is view


@pytest.mark.parametrize(
    "values",
    [
        (0, 2, 3, 4, 5),
        (1, 1, 3, 4, 5),
        (1, 2, 3, 4, 0x142D6BA78),
        (True, 2, 3, 4, 5),
        (-1, 2, 3, 4, 5),
    ],
)
def test_service_targets_are_explicit_distinct_valid_raw_tokens(values):
    with pytest.raises(ValueError):
        ReplayLocalizationTargets(*values)


def test_owned_body_token_is_valid_in_the_separate_terminal_namespace():
    memory = ReplayMemory()
    targets = ReplayLocalizationTargets(0x140803E30, 2, 3, 4, 5)
    runtime = ReplayLocalizationRuntime(memory, targets)
    buffer = memory.allocate(16)
    assert invoke(runtime, targets.conversion, 1, buffer, 16, 10) == 0
    assert memory.read_bytes(buffer, 2) == b"1\0"
