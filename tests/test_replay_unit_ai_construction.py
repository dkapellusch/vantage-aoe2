"""UnitAI factory publication, current dispatch and live constructor-local backing."""

from __future__ import annotations

import json
import struct
from pathlib import Path

import pytest

from vantage.replay_memory import ReplayMemory, ReplayMemoryError
from vantage.replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
)
from vantage.replay_unit_ai_construction import (
    bind_replay_unit_ai_construction,
    construct_replay_unit_ai15,
    replace_replay_unit_ai,
)

STATIC = json.loads(
    (Path(__file__).parent / "fixtures/native_unit_ai_construction_54800.json").read_text()
)


def context(memory: ReplayMemory) -> ReplayTaskRebuildStorage:
    return ReplayTaskRebuildStorage(1, memory.read, memory.write)


def static(memory: ReplayMemory) -> None:
    memory.map_bytes(0x1412CAD60, bytes.fromhex(STATIC["jump_table"]["raw_hex"]))
    for row in STATIC["constants"]:
        memory.map_bytes(int(row["address"], 16), bytes.fromhex(row["raw_hex"]))
    memory.map_bytes(0x143199938, (0x142D6E3B7).to_bytes(8, "little"))


def subject(memory: ReplayMemory) -> int:
    result = memory.allocate(0x1F8)
    memory.write(result + 0x1F0, 8, 0)
    return result


@pytest.mark.parametrize("plan", STATIC["factory_cases"], ids=lambda row: str(row["tag"]))
def test_all_original_case_targets_zero_actual_allocation_and_publish_ctor_result_last(plan):
    memory = ReplayMemory()
    static(memory)
    owner = subject(memory)
    runtime = memory.runtime_calls()
    effects = []

    def call(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        effects.append((target, args, data))
        if target == int(plan["constructor"], 16):
            allocation, same, mode = args
            assert same == owner and mode == plan["mode"]
            assert memory.read(owner + 0x1F0, 8) == 0
            assert memory.read_bytes(allocation, plan["size"]) == bytes(plan["size"])
            memory.write(owner + 0x1F0, 8, 0xBAD)
            return 0xDEADBEEF01234567  # Raw constructor RAX, deliberately not allocation.
        assert runtime.call is not None
        return runtime.call(target, args, data)

    replace_replay_unit_ai(
        context(memory), owner, plan["tag"] + (0xC0FFEE << 32), calls=ReplayTaskRebuildCalls(call)
    )
    assert [entry for entry, _, _ in effects] == [
        0x142D6BA78,
        0x142D6E3B7,
        int(plan["constructor"], 16),
    ]
    assert memory.read(owner + 0x1F0, 8) == 0xDEADBEEF01234567


@pytest.mark.parametrize("tag", [0, 1, 20, 0xFFFFFFFF, 0xFFFF0000])
def test_invalid_low_selector_needs_no_table_and_deletes_held_old_identity(tag: int) -> None:
    memory = ReplayMemory()
    owner = subject(memory)
    old, replacement, table = (memory.allocate(size) for size in (8, 8, 8))
    memory.write(owner + 0x1F0, 8, old)
    memory.write(old, 8, table)
    memory.write(table, 8, 0xFA00)
    seen = []

    def read(address: int, width: int) -> int:
        value = memory.read(address, width)
        if address == owner + 0x1F0:
            memory.write(owner + 0x1F0, 8, replacement)
        return value

    def call(target: int, args: tuple[int, ...], data: memoryview | None) -> None:
        seen.append((target, args, data))
        assert memory.read(owner + 0x1F0, 8) == replacement
        memory.free(old)

    current = ReplayTaskRebuildStorage(1, read, memory.write)
    replace_replay_unit_ai(current, owner, tag, calls=ReplayTaskRebuildCalls(call))
    assert seen == [(0xFA00, (old, 1), None)]
    assert memory.read(owner + 0x1F0, 8) == 0
    with pytest.raises(ReplayMemoryError, match="unmapped"):
        memory.read(old, 1)


def test_current_table_remap_and_unsupported_entry_are_not_inferred_from_tag() -> None:
    memory = ReplayMemory()
    static(memory)
    owner = subject(memory)
    alternate = STATIC["factory_cases"][-1]
    memory.write(0x1412CAD60, 4, int(alternate["branch"], 16) - 0x140000000)
    seen = []

    def call(target: int, args: tuple[int, ...], data: memoryview | None) -> int:
        seen.append((target, args, data))
        return 0

    replace_replay_unit_ai(context(memory), owner, 2, calls=ReplayTaskRebuildCalls(call))
    assert seen == [(0x142D6BA78, (alternate["size"],), None)]
    memory.write(0x1412CAD60, 4, 0xFFFFFFFF)
    with pytest.raises(UnresolvedReplayTaskRebuild, match="branch23fffffff"):
        replace_replay_unit_ai(context(memory), owner, 2, calls=ReplayTaskRebuildCalls(call))
    assert len(seen) == 1


def test_known_ai15_binder_never_delegates_ctor_and_retains_unpublished_allocation() -> None:
    memory = ReplayMemory()
    static(memory)
    owner = subject(memory)
    runtime = memory.runtime_calls()
    allocations = []

    def call(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        assert target != 0x140CEF620
        assert runtime.call is not None
        result = runtime.call(target, args, data)
        if target == 0x142D6BA78:
            allocations.append(result)
        return result

    calls = bind_replay_unit_ai_construction(
        context(memory), ReplayTaskRebuildCalls(call), bind_local=memory.bind_local
    )
    assert calls.call is not None
    with pytest.raises(UnresolvedReplayTaskRebuild, match="reached140d094c0"):
        calls.call(0x1412CA880, (owner, 15), None)
    assert memory.read(owner + 0x1F0, 8) == 0 and len(allocations) == 1
    assert memory.read_bytes(allocations[0], 528) == bytes(528)


def test_ctor_locals_remain_mutable_live_until_final_callback_and_then_expire() -> None:
    memory = ReplayMemory()
    static(memory)
    ai = memory.allocate(528)
    current = context(memory)
    saved = []
    calls_seen = []

    def call(target: int, args: tuple[int, ...], data: memoryview | None) -> int:
        calls_seen.append((target, args, data))
        if target == 0x140D094C0:
            assert args == (ai, 0xCAFE, 0xFFFFFFFF0000000A, 0)
            memory.write(ai + 0x1B1, 1, 9)
        elif target == 0x140CEFB30:
            assert args[0] == ai + 0x198
            header = args[1]
            begin, end = struct.unpack("<QQ", memory.read_bytes(header, 16))
            assert end == begin + 168
            assert (
                list(struct.unpack("<42I", memory.read_bytes(begin, 168)))
                == (STATIC["ordered_u32_constants"])
            )
            memory.write(begin, 4, 0xC0FFEE)
            memory.write(header + 8, 8, begin + 4)
            saved.extend((header, begin))
        else:
            assert target == 0x140D19DD0 and args == (ai, 1000)
            header, begin = saved
            assert memory.read(begin, 4) == 0xC0FFEE
            assert memory.read(header + 8, 8) == begin + 4
            assert memory.read(ai + 0x1B1, 1) == 0
            memory.write(ai, 8, 0xBEEF)
            memory.write(ai + 0x1B1, 1, 7)
        return 0xDEAD  # Every child return is ignored by this ctor caller.

    assert (
        construct_replay_unit_ai15(
            current,
            ai,
            0xCAFE,
            0xFFFFFFFF0000000A,
            calls=ReplayTaskRebuildCalls(call),
            bind_local=memory.bind_local,
        )
        == ai
    )
    assert len(calls_seen) == 3 and memory.read(ai, 8) == 0xBEEF
    assert memory.read(ai + 0x1B1, 1) == 7
    assert memory.read(ai + 0x1F8, 24) == 0
    for address in saved:
        with pytest.raises(ReplayMemoryError, match="unmapped"):
            memory.read(address, 1)
    with pytest.raises(ReplayMemoryError, match="undefined"):
        memory.read(ai + 8, 1)
    memory.snapshot()


@pytest.mark.parametrize("failure_target", [0x140D094C0, 0x140CEFB30, 0x140D19DD0])
def test_ctor_failures_preserve_prior_fields_and_truthy_exits_cannot_suppress(failure_target):
    memory = ReplayMemory()
    static(memory)
    ai = memory.allocate(528)
    error = RuntimeError("body failed")
    exits = []

    def call(target: int, args: tuple[int, ...], data: memoryview | None) -> None:
        if target == 0x140D094C0:
            memory.write(ai + 0x1B1, 1, 9)
        if target == failure_target:
            raise error

    def local(view):
        actual = memory.bind_local(view)

        class Manager:
            def __enter__(self):
                return actual.__enter__()

            def __exit__(self, kind, failure, traceback):
                exits.append(len(view))
                actual.__exit__(kind, failure, traceback)
                return True

        return Manager()

    with pytest.raises(RuntimeError) as caught:
        construct_replay_unit_ai15(
            context(memory), ai, 0, 10, calls=ReplayTaskRebuildCalls(call), bind_local=local
        )
    assert caught.value is error
    assert exits == ([] if failure_target == 0x140D094C0 else [16, 168])
    assert memory.read(ai + 0x1B1, 1) == (0 if failure_target == 0x140D19DD0 else 9)
    if failure_target == 0x140D094C0:
        with pytest.raises(ReplayMemoryError, match="undefined"):
            memory.read(ai, 8)
    else:
        assert memory.read(ai, 8) == 0x143247958
    memory.snapshot()
