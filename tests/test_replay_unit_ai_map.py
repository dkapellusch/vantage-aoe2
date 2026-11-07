"""Real shared-count/map storage, held identities and constructor composition."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from vantage.replay_memory import ReplayMemory, ReplayMemoryError
from vantage.replay_random import draw_replay_random_i15, seed_replay_random
from vantage.replay_random_storage import bind_replay_random_storage
from vantage.replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
)
from vantage.replay_unit_ai_base import bind_replay_unit_ai_base
from vantage.replay_unit_ai_construction import bind_replay_unit_ai_construction
from vantage.replay_unit_ai_map import (
    ReplayUnitAIMapAtomics,
    acquire_replay_unit_ai_map,
    bind_replay_unit_ai_map,
    lookup_replay_ai_zone,
    read_replay_unit_ai_position_kind,
)
from vantage.replay_unit_ai_support import bind_replay_unit_ai_support
from vantage.replay_zone_map_registry import bind_replay_zone_map_registry

U64 = (1 << 64) - 1
STATIC = json.loads(
    (Path(__file__).parent / "fixtures/native_unit_ai_construction_54800.json").read_bytes()
)


def context(memory):
    return ReplayTaskRebuildStorage(1, memory.read, memory.write)


def atomic(memory):
    return ReplayUnitAIMapAtomics(memory.compare_exchange_u32, memory.fetch_add_u32)


def shared(memory, strong=1, weak=2):
    control, vtable = memory.allocate(16), memory.allocate(16)
    for address, width, value in (
        (control, 8, vtable),
        (control + 8, 4, strong),
        (control + 12, 4, weak),
        (vtable, 8, 0xFA0),
        (vtable + 8, 8, 0xFA8),
    ):
        memory.write(address, width, value)
    return control, vtable


def position(memory, subject, x=0x3F800000, y=0, z=0):
    for offset, value in (
        (0x170, x + 0x183CAC30D2441D0E - 0x4C3FBA69E4EA7FD1),
        (0x178, y + 0x61501AA6ECFD980A - 0x6C5EAB60B426DD28),
        (0x180, z - 0x2B3719EF44DE99FF - 0x21D14A25ED7C802C),
    ):
        memory.write(subject + offset, 8, value & U64)


def zone(memory):
    result, dimensions, rows, row = (memory.allocate(n) for n in (0x838, 0x38, 8, 6))
    memory.write(result + 0x830, 8, dimensions)
    memory.write(result + 0x810, 8, rows)
    memory.write(dimensions + 0x30, 4, 3)
    memory.write(dimensions + 0x34, 4, 1)
    memory.write(rows, 8, row)
    memory.write_bytes(row, bytes.fromhex("0700feca0900"))
    return result


def miss_inputs(memory):
    subject, output, master, owner, world, maps, descriptor, entries = (
        memory.allocate(n) for n in (0x1E8, 16, 0xA8, 16, 0xA0, 0x5BC8, 8, 72)
    )
    for address, value in (
        (subject + 0x1E0, 0),
        (subject + 0x10, (master + 0x774A063B3D17506C) & U64),
        (subject + 0x18, owner),
        (owner + 8, world),
        (world + 0x98, maps),
        (maps + 0x5BC0, 0xCAFE),
        (descriptor, entries),
    ):
        memory.write(address, 8, value)
    memory.write(master + 0xA6, 2, 2)
    return subject, output, world, descriptor, entries


def test_cache_hit_real_outer_query_balances_strong_hold_and_skips_missing_owner() -> None:
    memory = ReplayMemory()
    subject = memory.allocate(0x1E8)
    zone_map = zone(memory)
    control, _ = shared(memory)
    memory.write(subject + 0x1D8, 8, zone_map)
    memory.write(subject + 0x1E0, 8, control)
    position(memory, subject)
    bound = bind_replay_unit_ai_map(
        context(memory),
        ReplayTaskRebuildCalls(None),
        atomics=atomic(memory),
        bind_local=memory.bind_local,
        scratch=bytes(24),
    )
    assert bound.call is not None
    assert bound.call(0x14124DD50, (subject,), None) == 0xCAFE
    assert memory.read(control + 8, 4) == 1
    assert memory.read(control + 12, 4) == 2
    memory.snapshot()  # No escaped borrowed locals.


def test_cache_cas_retries_using_returned_word_and_reloads_current_subject_pair() -> None:
    memory = ReplayMemory()
    subject, output = memory.allocate(0x1E8), memory.allocate(16)
    first, _ = shared(memory, 2)
    replacement, _ = shared(memory, 8)
    memory.write(subject + 0x1E0, 8, first)
    memory.write(subject + 0x1D8, 8, 0xAA)
    seen = []

    def compare(address, expected, desired):
        seen.append((address, expected, desired))
        if len(seen) == 1:
            memory.write(first + 8, 4, 5)
            return 5
        memory.write(subject + 0x1D8, 8, 0xBB)
        memory.write(subject + 0x1E0, 8, replacement)
        return memory.compare_exchange_u32(address, expected, desired)

    acquire_replay_unit_ai_map(
        context(memory),
        subject,
        output,
        calls=ReplayTaskRebuildCalls(None),
        atomics=ReplayUnitAIMapAtomics(compare, memory.fetch_add_u32),
        bind_local=memory.bind_local,
        scratch=bytes(24),
    )
    assert seen == [(first + 8, 2, 3), (first + 8, 5, 6)]
    assert memory.read(output, 8) == 0xBB and memory.read(output + 8, 8) == replacement
    assert memory.read(first + 8, 4) == 6 and memory.read(replacement + 8, 4) == 8


def test_miss_consumes_real_envelope_and_balances_cache_output_and_temporary_holds() -> None:
    memory = ReplayMemory()
    subject, output, world, descriptor, entries = miss_inputs(memory)
    control, _ = shared(memory, 1, 1)
    temporary = []
    seen = []

    def call(target, args, data):
        seen.append((target, args))
        if target == 0x141604030:
            assert args == (world,)
            return descriptor
        assert target == 0x1414ECF90 and args[0] == 0xCAFE and args[2:] == (entries + 48, 0)
        temporary.append(args[1])
        assert memory.read_bytes(args[1], 24) == bytes(range(24))
        memory.write(args[1] + 8, 8, 0xABC)
        memory.write(args[1] + 16, 8, control)

    acquire_replay_unit_ai_map(
        context(memory),
        subject,
        output,
        calls=ReplayTaskRebuildCalls(call),
        atomics=atomic(memory),
        bind_local=memory.bind_local,
        scratch=bytes(range(24)),
    )
    assert len(seen) == 2 and memory.read(output, 8) == 0xABC
    assert memory.read(output + 8, 8) == memory.read(subject + 0x1E0, 8) == control
    assert memory.read(subject + 0x1D8, 8) == 0xABC
    assert memory.read(control + 8, 4) == 1 and memory.read(control + 12, 4) == 2
    with pytest.raises(ReplayMemoryError, match="unmapped"):
        memory.read(temporary[0], 1)


def test_expired_cache_and_unavailable_child_preserve_output_and_prior_state() -> None:
    memory = ReplayMemory()
    subject, output, _, _, _ = miss_inputs(memory)
    control, _ = shared(memory, 0)
    memory.write(subject + 0x1E0, 8, control)
    memory.write_bytes(output, b"x" * 16)
    with pytest.raises(UnresolvedReplayTaskRebuild, match="141604030"):
        acquire_replay_unit_ai_map(
            context(memory),
            subject,
            output,
            calls=ReplayTaskRebuildCalls(None),
            atomics=ReplayUnitAIMapAtomics(None, None),
            bind_local=memory.bind_local,
            scratch=bytes(24),
        )
    assert memory.read_bytes(output, 16) == b"x" * 16
    assert memory.read(control + 8, 4) == 0 and memory.read(subject + 0x1E0, 8) == control


def test_last_release_rereads_vtable_after_actual_destructor_and_keeps_held_result() -> None:
    memory = ReplayMemory()
    subject = memory.allocate(0x1E8)
    control, table = shared(memory, 1, 1)
    replacement = memory.allocate(16)
    memory.write(replacement + 8, 8, 0xFB8)
    seen = []
    local = []

    def call(target, args, data):
        seen.append((target, args))
        if target == 0x141251F70:
            local.append(args[1])
            memory.write(args[1], 8, 0)
            memory.write(args[1] + 8, 8, control)
        elif target == 0xFA0:
            assert args == (control,)
            memory.write(control, 8, replacement)
            memory.write(local[0], 8, 0xDEAD)
        else:
            assert target == 0xFB8 and args == (control,)
            memory.free(control)

    assert (
        read_replay_unit_ai_position_kind(
            context(memory),
            subject,
            calls=ReplayTaskRebuildCalls(call),
            atomics=atomic(memory),
            bind_local=memory.bind_local,
        )
        == 0
    )
    assert seen[1:] == [(0xFA0, (control,)), (0xFB8, (control,))]
    with pytest.raises(ReplayMemoryError, match="unmapped"):
        memory.read(control, 1)
    assert memory.read(table, 8) == 0xFA0


@pytest.mark.parametrize(
    "x,y,expected",
    [(0, 0, 7), (1, 0, 0xCAFE), (3, 0, 0), (0xFFFFFFFF, 0, 0), (0, 1, 0), (0, 0xFFFFFFFF, 0)],
)
def test_zone_lookup_signed_bounds_and_current_rows(x, y, expected):
    memory = ReplayMemory()
    zone_map = zone(memory)
    assert (
        lookup_replay_ai_zone(context(memory), zone_map, x | (0xCAFE << 32), y | (0xBEEF << 32))
        == expected
    )


def test_negative_y_does_not_require_any_map_backing() -> None:
    assert lookup_replay_ai_zone(context(ReplayMemory()), 0xDEAD, 0, 0xFFFFFFFF) == 0


@pytest.mark.parametrize("cached", [True, False])
def test_full_AI15_factory_with_actual_map_chain_and_four_real_random_draws(cached) -> None:
    memory = ReplayMemory()
    subject, master, buckets = (memory.allocate(n) for n in (0x800, 0xA8, 16))
    memory.write(subject, 8, 0x1432B5FC8)
    memory.write(subject + 0x10, 8, (master + 0x774A063B3D17506C) & U64)
    memory.write(subject + 0x1F0, 8, 0)
    memory.write(subject + 0x75C, 4, 0)
    memory.write(master + 0x38, 8, (4 + 0x50A06BCECEBEF905 - 0x5B32AA7995D95916) & U64)
    memory.write(master + 0x70, 4, 0x3FC00000)
    position(memory, subject)
    for address, value in (
        (subject + 0x300, 0xBEEF),
        (subject + 0x310, buckets),
        (subject + 0x328, 0),
        (buckets + 8, 0xBEEF),
    ):
        memory.write(address, 8, value)
    zone_map, (control, _) = zone(memory), shared(memory)
    memory.write(subject + 0x1D8, 8, zone_map if cached else 0)
    memory.write(subject + 0x1E0, 8, control if cached else 0)
    if not cached:
        owner, world, maps, manager, entries, pair = (
            memory.allocate(n) for n in (16, 0x790, 0x5BC8, 32, 24, 16)
        )
        for address, value in (
            (subject + 0x18, owner),
            (owner + 8, world),
            (world + 0x98, maps),
            (world + 0x788, entries),
            (maps + 0x5BC0, manager),
            (manager, pair),
            (manager + 8, pair + 16),
            (entries, 0),
            (entries + 8, 0),
            (pair, zone_map),
            (pair + 8, control),
            (zone_map + 0x818, 0),
            (zone_map + 0x820, 0),
        ):
            memory.write(address, 8, value)
        memory.write(master + 0xA6, 2, 0)
    memory.map_bytes(0x1412CAD60, bytes.fromhex(STATIC["jump_table"]["raw_hex"]))
    for row in STATIC["constants"]:
        memory.map_bytes(int(row["address"], 16), bytes.fromhex(row["raw_hex"]))
    for address, target in (
        (0x143199938, 0x142D6E3B7),
        (0x1431999A0, 0x142D6E3DB),
        (0x1432B5FC8 + 0x228, 0x1412B6520),
        (0x143247958 + 0x1A8, 0x140D1A2F0),
    ):
        memory.map_bytes(address, target.to_bytes(8, "little"))
    rng = seed_replay_random(0x12345678)  # Explicit component input, not replay-point state.
    memory.map_bytes(0x1443530F0, bytes(0x8C))
    for index, word in enumerate(rng.words):
        memory.write(0x144353114 + index * 4, 4, word)
    current = context(memory)
    random = bind_replay_random_storage(current, memory.runtime_calls())
    registry = bind_replay_zone_map_registry(
        current, random, atomics=atomic(memory), bind_local=memory.bind_local
    )
    maps = bind_replay_unit_ai_map(
        current, registry, atomics=atomic(memory), bind_local=memory.bind_local, scratch=bytes(24)
    )
    support = bind_replay_unit_ai_support(current, maps)
    base = bind_replay_unit_ai_base(current, support)
    factory = bind_replay_unit_ai_construction(current, base, bind_local=memory.bind_local)
    assert factory.call is not None
    assert factory.call(0x1412CA880, (subject, 15), None) is None
    ai = memory.read(subject + 0x1F0, 8)
    assert ai and memory.read(ai, 8) == 0x143247958
    assert memory.read(ai + 0x194, 4) == 0x3FC00000
    assert memory.read(memory.read(ai + 0xC0, 8) + 12, 2) == 0xCAFE
    assert memory.read(ai + 0x170, 4) == 1000
    begin, end = memory.read(ai + 0x198, 8), memory.read(ai + 0x1A0, 8)
    assert end - begin == 168
    assert [memory.read(begin + index * 4, 4) for index in range(42)] == (
        STATIC["ordered_u32_constants"]
    )
    values = []
    for _ in range(4):
        draw = draw_replay_random_i15(rng)
        rng = draw.state
        values.append(draw.value)
    assert memory.read(0x144353108, 4) == 4
    assert memory.read(0x144353178, 4) == values[-1]
    assert memory.read(ai + 0x16C, 4) == values[-1] % 500 + 750
    assert memory.read(control + 8, 4) == 1
    assert memory.read(control + 12, 4) == (2 if cached else 3)
    assert ReplayMemory.from_snapshot(memory.snapshot()).snapshot() == memory.snapshot()
