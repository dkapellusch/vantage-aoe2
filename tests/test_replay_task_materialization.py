"""Real parsed TaskLists, asset contexts, current baseline clones and ownership."""

from __future__ import annotations

import gzip
import hashlib
import json
import struct
import zipfile
from dataclasses import replace
from pathlib import Path

import pytest

from vantage.replay_binary import SaveReader
from vantage.replay_game_data import read_game_data_master
from vantage.replay_master_tasks import ReplayMasterTask, restore_replay_master_tasks
from vantage.replay_masters import SavedMasterTask, read_master_task
from vantage.replay_memory import ReplayMemory, ReplayMemoryError
from vantage.replay_saved_world import load_replay_world
from vantage.replay_task_construction import bind_replay_task_construction
from vantage.replay_task_list_deletion import bind_replay_task_list_deletion
from vantage.replay_task_list_storage import bind_replay_task_list_storage
from vantage.replay_task_materialization import (
    ReplayTaskReferenceContexts,
    clone_current_replay_task_list,
    materialize_replay_master_tasks,
    materialize_replay_task_definitions,
)
from vantage.replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
)
from vantage.replay_task_references import bind_replay_task_references

FIXTURES = Path(__file__).parent / "fixtures"


def bindings(memory: ReplayMemory) -> tuple[ReplayTaskRebuildStorage, ReplayTaskRebuildCalls]:
    current = ReplayTaskRebuildStorage(1, memory.read, memory.write)
    construction = bind_replay_task_construction(current, memory.runtime_calls())
    storage = bind_replay_task_list_storage(current, construction)
    deletion = bind_replay_task_list_deletion(current, storage)
    return current, bind_replay_task_references(current, deletion)


def setup(memory: ReplayMemory) -> None:
    for address, entry in ((0x1432B5EE8, 0x141268D80), (0x1432BC398, 0x141320510)):
        memory.map_bytes(address, struct.pack("<QQ", entry, 0x1412691B0), writable=False)
    for iat, target in (
        (0x143199DD0, 0x142D6BAB4),
        (0x143199938, 0x142D6E3B7),
        (0x1431999A0, 0x142D6E3DB),
    ):
        memory.map_bytes(iat, struct.pack("<Q", target))


def task_definition() -> SavedMasterTask:
    raw = bytearray(69)
    struct.pack_into("<H", raw, 0, 1)
    struct.pack_into("<6h", raw, 47, -1, -1, -1, -1, -1, -1)
    return read_master_task(SaveReader(bytes(raw), version=0x44E666))


def create(memory: ReplayMemory, tasks, *, references=None, calls=None):
    current, actual = bindings(memory)
    return materialize_replay_task_definitions(
        current,
        tasks,
        master=0,
        factory_target=0x141323AE0,
        references=references if references is not None else ReplayTaskReferenceContexts(0, 0),
        calls=calls if calls is not None else actual,
        bind_local=memory.bind_local,
    )


def clone(memory: ReplayMemory, source: int):
    current, calls = bindings(memory)
    return clone_current_replay_task_list(
        current,
        source,
        master=0,
        factory_target=0x141323AE0,
        calls=calls,
        bind_local=memory.bind_local,
    )


@pytest.fixture(scope="module")
def actual_records(tmp_path_factory):
    directory = tmp_path_factory.mktemp("task-materialization-records")
    expected = json.loads(
        gzip.decompress(
            (FIXTURES / "native_task_materialization_contract_54800.json.gz").read_bytes()
        )
    )
    assert expected["authority"].startswith("Source-derived")
    result = {}
    with zipfile.ZipFile(FIXTURES / "native_replay_program_54800.zip") as archive:
        manifest = json.loads(archive.read("manifest.json"))
        bodies = archive.read("bodies.bin")
        for case in manifest["cases"]:
            key = case["selected_baselines"][1]["109"]
            at, size = manifest["bodies"][key]
            raw = bodies[at : at + size]
            assert hashlib.sha256(raw).hexdigest() == key
            reader = SaveReader(raw, version=0x43E666)
            baseline = read_game_data_master(reader)
            assert not reader.remaining
            path = directory / case["window_member"]
            window = archive.read(case["window_member"])
            assert hashlib.sha256(window).hexdigest() == case["window_sha256"]
            path.write_bytes(window)
            saved = load_replay_world(path).prefix.world.players[1].masters.masters[109]
            logical = restore_replay_master_tasks(saved, {109: baseline})
            golden = next(c for c in expected["cases"] if c["sample"] == case["sample"])
            assert hashlib.sha256(saved.raw).hexdigest() == golden["saved_master_sha256"]
            result[case["sample"]] = (baseline, logical, golden)
    return result


@pytest.mark.parametrize("sample", ["3p", "6p"])
def test_real_saved_and_inherited_town_center_tasks_match_all144_source_bytes(
    actual_records,
    sample: str,
) -> None:
    baseline, logical, golden = actual_records[sample]
    memory = ReplayMemory()
    setup(memory)
    source = create(memory, baseline.tasks)
    current, calls = bindings(memory)
    result = materialize_replay_master_tasks(
        current,
        logical,
        baseline_list=source.address,
        master=0,
        factory_target=0x141323AE0,
        references=ReplayTaskReferenceContexts(0, 0),
        calls=calls,
        bind_local=memory.bind_local,
    )
    assert result and result.address != source.address and logical.default_index == -1
    assert len(result.task_addresses) == len(golden["tasks"])
    assert not set(result.task_addresses) & set(source.task_addresses)
    begin = memory.read(result.address + 8, 8)
    assert memory.read(result.address + 16, 8) == begin + len(result.task_addresses) * 8
    assert memory.read(result.address + 24, 8) == memory.read(result.address + 16, 8)
    for i, (address, row) in enumerate(zip(result.task_addresses, golden["tasks"], strict=True)):
        assert memory.read(begin + i * 8, 8) == address
        expected = bytes.fromhex(row["source_derived_runtime144_hex"])
        assert memory.read_bytes(address, 144) == expected
        assert hashlib.sha256(logical.tasks[i].definition.raw).hexdigest() == row["wire_sha256"]
    assert calls.call is not None
    assert calls.call(0x141320510, (result.address, 1), None) == result.address
    assert memory.read(source.address, 8) == 0x1432BC398
    with pytest.raises(ReplayMemoryError, match="unmapped"):
        memory.read(result.address, 1)


def test_current_clone_preserves_resolved_references_descriptor_padding_and_fresh_ordinal() -> None:
    memory = ReplayMemory()
    setup(memory)
    source = create(memory, [task_definition()])
    original = source.task_addresses[0]
    graphic = memory.allocate(32)
    memory.write(original + 0x40, 8, graphic)
    memory.write(original + 0xA, 2, 1234)
    memory.write(original + 0xD, 1, 0xEE)
    memory.write_bytes(original + 0x3A, b"abcdef")
    memory.write_bytes(original + 0x60, bytes(range(24)))
    memory.write_bytes(original + 0x78, bytes(range(24, 48)))
    copied = clone(memory, source.address)
    assert copied and copied.task_addresses[0] != original
    target = copied.task_addresses[0]
    assert memory.read(target + 0x40, 8) == graphic
    assert memory.read(target + 0xA, 2) == 0
    assert memory.read(target + 0xD, 1) == 0
    assert memory.read_bytes(target + 0x3A, 6) == bytes(6)
    assert memory.read_bytes(target + 0x60, 48) == bytes(range(48))
    assert memory.read(original + 0xA, 2) == 1234


def test_fresh_resolves_actual_graphic_slots_and_sound_before_applying_flag_predicate() -> None:
    memory = ReplayMemory()
    setup(memory)
    graphics, slots = memory.allocate(8), memory.allocate(32)
    pointers = [memory.allocate(24) for _ in range(3)]
    memory.write(graphics, 8, slots + 16)
    for offset, value in ((0, pointers[0]), (16, pointers[1]), (24, pointers[2])):
        memory.write(slots + offset, 8, value)
    sounds, sound_slots, sound = memory.allocate(20), memory.allocate(8), memory.allocate(56)
    memory.write(sounds, 8, sound_slots)
    memory.write(sounds + 16, 4, 1)
    memory.write(sound_slots, 8, sound)
    memory.write(sound + 8, 8, 0)
    memory.write(sound + 16, 8, 1)
    definition = replace(task_definition(), sound_numbers=(0, -1))
    fields = {
        **definition.fields,
        0x40: 0,
        0x48: -1,
        0x50: -2,
        0x58: 1,
        0x60: 0,
        0x78: 0x76835F7D,
        0x38: -7,
        0xA: 42,
    }
    result = create(
        memory,
        [ReplayMasterTask(definition, fields)],
        references=ReplayTaskReferenceContexts(graphics, sounds),
    )
    address = result.task_addresses[0]
    assert [memory.read(address + i, 8) for i in (0x40, 0x48, 0x50, 0x58)] == [
        pointers[1],
        0,
        pointers[0],
        pointers[2],
    ]
    assert memory.read(address + 0x60, 4) == memory.read(address + 0x64, 4) == 0x62D4B3EC
    assert memory.read(address + 0x68, 8) == sound
    assert memory.read(address + 0x70, 4) == 1
    assert memory.read(address + 0x78, 4) == 0x76835F7D
    assert memory.read(address + 0x80, 8) == 0 and memory.read(address + 0x88, 4) == 5
    assert memory.read(address + 0x74, 4) == memory.read(address + 0x8C, 4) == 0
    assert memory.read(address + 0x38, 2) == 0xFFF9 and memory.read(address + 0xA, 2) == 42


def test_null_and_distinct_nonnull_empty_lists_keep_their_runtime_identity() -> None:
    memory = ReplayMemory()
    setup(memory)
    before = memory.snapshot()
    assert clone(memory, 0) is None and memory.snapshot() == before
    empty = create(memory, [])
    copied = clone(memory, empty.address)
    assert copied and copied.address != empty.address and copied.task_addresses == ()
    assert memory.read_bytes(empty.address + 8, 24) == bytes(24)
    assert memory.read_bytes(copied.address + 8, 24) == bytes(24)


def test_current_virtual_factory_slot_is_read_again_for_each_task() -> None:
    memory = ReplayMemory()
    setup(memory)
    current, core = bindings(memory)
    assert core.call is not None
    for table, target in ((0x2000, 0xF001), (0x3000, 0xF002)):
        memory.map_bytes(table, struct.pack("<QQ", 0, target))
    seen = []

    def route(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        assert core.call is not None
        if target == 0x141323AE0:
            result = core.call(target, args, data)
            assert result
            memory.write(result, 8, 0x2000)
            return result
        if target in (0xF001, 0xF002):
            seen.append((target, args[2]))
            memory.write(args[0], 8, 0x3000)
            return core.call(0x1412691B0, args, data)
        return core.call(target, args, data)

    result = materialize_replay_task_definitions(
        current,
        [task_definition()] * 2,
        master=0,
        factory_target=0x141323AE0,
        references=ReplayTaskReferenceContexts(0, 0),
        calls=ReplayTaskRebuildCalls(route),
        bind_local=memory.bind_local,
    )
    assert len(set(result.task_addresses)) == 2 and seen == [(0xF001, 0), (0xF002, 1)]


def test_missing_graphics_refuses_after_publication_and_prior_scalar_writes() -> None:
    memory = ReplayMemory()
    setup(memory)
    definition = task_definition()
    definition = replace(definition, fields={**definition.fields, 0x40: 0, 0xE: 155})
    with pytest.raises(ReplayMemoryError, match="unmapped"):
        create(memory, [definition], references=ReplayTaskReferenceContexts(0xBAD, 0))
    lists = [r for r in memory.snapshot().regions if r.owned and len(r.data) == 32]
    assert len(lists) == 1
    task = memory.read(memory.read(lists[0].address + 8, 8), 8)
    assert memory.read(task + 0xE, 2) == 155
    assert memory.read(task + 0x38, 2) == 0xFFFF
    assert memory.read(task + 0x70, 4) == 0  # Descriptor processing was not reached.


def test_clone_uses_current_source_tag_and_refuses_unsupported_factory_result() -> None:
    memory = ReplayMemory()
    setup(memory)
    source = create(memory, [task_definition()])
    memory.write(source.task_addresses[0] + 8, 2, 2)
    with pytest.raises(UnresolvedReplayTaskRebuild, match="Task factory returned null"):
        clone(memory, source.address)
    assert sum(r.owned and len(r.data) == 144 for r in memory.snapshot().regions) == 1


@pytest.mark.parametrize(
    "begin,end,capacity",
    [(0, 8, 8), (16, 15, 16), (16, 17, 24), (16, 24, 25), (16, 16 + 32768 * 8, 16 + 32768 * 8)],
)
def test_invalid_clone_vector_refuses_before_allocating_destination(
    begin: int,
    end: int,
    capacity: int,
) -> None:
    memory = ReplayMemory()
    setup(memory)
    source = memory.allocate(32)
    for offset, value in ((8, begin), (16, end), (24, capacity)):
        memory.write(source + offset, 8, value)
    before = memory.snapshot()
    with pytest.raises(ValueError, match="coherent bounded"):
        clone(memory, source)
    assert memory.snapshot() == before


def test_snapshot_continuation_repeats_materialization_and_shallow_clone() -> None:
    memory = ReplayMemory()
    setup(memory)
    source = create(memory, [task_definition(), task_definition()])
    restored = ReplayMemory.from_snapshot(memory.snapshot())
    first = clone(memory, source.address)
    second = clone(restored, source.address)
    assert first == second and memory.snapshot() == restored.snapshot()
