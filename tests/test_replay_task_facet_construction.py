"""Fresh task maps, partial failures and a real saved TownCenter rebuild."""

from __future__ import annotations

import hashlib
import json
import struct
import zipfile
from pathlib import Path

import pytest

from vantage.replay_binary import SaveReader
from vantage.replay_game_data import read_game_data_master
from vantage.replay_master_tasks import restore_replay_master_tasks
from vantage.replay_memory import ReplayMemory, ReplayMemoryError
from vantage.replay_saved_world import load_replay_world
from vantage.replay_task_construction import bind_replay_task_construction
from vantage.replay_task_effects import bind_replay_task_execution
from vantage.replay_task_facet_construction import (
    bind_replay_task_facet_construction,
    construct_replay_task_byte_map,
    construct_replay_task_group_map,
    construct_replay_task_pair_map,
    initialize_fresh_replay_task_facets,
)
from vantage.replay_task_list_storage import bind_replay_task_list_storage
from vantage.replay_task_materialization import (
    ReplayTaskReferenceContexts,
    materialize_replay_task_definitions,
)
from vantage.replay_task_prefix import ReplayTaskPrefixScratch
from vantage.replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildScratch,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
    run_replay_task_rebuild,
)
from vantage.replay_task_references import bind_replay_task_references

CONSTRUCTORS = (
    (0x1411438B0, construct_replay_task_pair_map, 32, 0x14114D5C0),
    (0x141143930, construct_replay_task_byte_map, 32, 0x14114D690),
    (0x1412A5CE0, construct_replay_task_group_map, 120, 0x1412BF400),
)
SELECTORS = [0, 4, 6, 12, 13, 22, 36, 44, 47, 54, 55, 19, 20, 21, 2]


def context(memory: ReplayMemory, subject: int = 1) -> ReplayTaskRebuildStorage:
    return ReplayTaskRebuildStorage(subject, memory.read, memory.write)


def bound(memory: ReplayMemory, subject: int = 1) -> ReplayTaskRebuildCalls:
    return bind_replay_task_facet_construction(
        context(memory, subject), memory.runtime_calls(), bind_local=memory.bind_local, mxcsr=0x1F80
    )


def invoke(calls: ReplayTaskRebuildCalls, target: int, *args: int) -> int | None:
    assert calls.call is not None
    return calls.call(target, args, None)


@pytest.mark.parametrize("target,body,size,initializer", CONSTRUCTORS)
def test_complete_constructors_use_real_buckets_and_preserve_undefined_padding(
    target,
    body,
    size: int,
    initializer: int,
) -> None:
    memory = ReplayMemory()
    header = memory.allocate(64)
    initial = memory.snapshot()
    assert invoke(bound(memory), target, header) == header
    sentinel = memory.read(header + 8, 8)
    buckets = memory.read(header + 0x18, 8)
    assert memory.read(header, 4) == 0x3F800000
    assert [memory.read(header + offset, 8) for offset in (0x10, 0x20, 0x28, 0x30, 0x38)] == [
        0,
        buckets + 128,
        buckets + 128,
        7,
        8,
    ]
    assert memory.read_bytes(sentinel, 16) == struct.pack("<QQ", sentinel, sentinel)
    assert memory.read_bytes(buckets, 128) == sentinel.to_bytes(8, "little") * 16
    assert memory.mapped_bytes == 64 + size + 128
    for address, count in ((header + 4, 4), (sentinel + 16, size - 16)):
        with pytest.raises(ReplayMemoryError, match="undefined"):
            memory.read_bytes(address, count)
    restored = ReplayMemory.from_snapshot(initial)
    assert body(context(restored), header, calls=bound(restored)) == header
    assert restored.snapshot() == memory.snapshot()


@pytest.mark.parametrize("target,body,size,initializer", CONSTRUCTORS)
def test_initializer_gets_current_header_sentinel_value_after_prior_stores(
    target,
    body,
    size: int,
    initializer: int,
) -> None:
    memory = ReplayMemory()
    header, sentinel = memory.allocate(64), memory.allocate(size)
    seen = []

    def write(address: int, width: int, value: int) -> None:
        memory.write(address, width, value)
        if address == header and value == 0x3F800000:
            memory.write(header + 8, 8, 0xDEADBEEF)

    def call(entry: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        seen.append((entry, args, data))
        if entry == 0x142D6BA78:
            assert args == (size,)
            assert memory.read(header, 4) == memory.read(header + 8, 8) == 0
            return sentinel
        assert entry == initializer and args == (header + 24, 16, 0xDEADBEEF)
        return None

    current = ReplayTaskRebuildStorage(1, memory.read, write)
    assert body(current, header, calls=ReplayTaskRebuildCalls(call)) == header
    assert len(seen) == 2
    assert memory.read(sentinel, 8) == sentinel


@pytest.mark.parametrize("target,body,size,initializer", CONSTRUCTORS)
def test_failed_allocator_preserves_only_earlier_header_stores(
    target,
    body,
    size: int,
    initializer: int,
) -> None:
    memory = ReplayMemory()
    header = memory.allocate(64)
    error = RuntimeError("allocation failed")

    def call(entry: int, args: tuple[int, ...], data: memoryview | None) -> None:
        assert (entry, args, data) == (0x142D6BA78, (size,), None)
        raise error

    with pytest.raises(RuntimeError) as caught:
        body(context(memory), header, calls=ReplayTaskRebuildCalls(call))
    assert caught.value is error
    assert memory.read(header, 4) == memory.read(header + 8, 16) == 0
    with pytest.raises(ReplayMemoryError, match="undefined"):
        memory.read(header + 0x18, 8)


@pytest.mark.parametrize("target,body,size,initializer", CONSTRUCTORS)
def test_zero_allocator_result_has_no_success_guard(target, body, size, initializer) -> None:
    memory = ReplayMemory()
    header = memory.allocate(64)
    with pytest.raises(ReplayMemoryError, match="unmapped replay address0"):
        body(context(memory), header, calls=ReplayTaskRebuildCalls(lambda *_: 0))
    assert memory.read(header, 4) == memory.read(header + 8, 16) == 0
    with pytest.raises(ReplayMemoryError, match="undefined"):
        memory.read(header + 24, 8)


@pytest.mark.parametrize("target", [row[0] for row in CONSTRUCTORS])
@pytest.mark.parametrize("args,data", [((), None), ((1, 2), None), ((1,), memoryview(b"x"))])
def test_malformed_known_calls_refuse_before_effects(target, args, data) -> None:
    memory = ReplayMemory()
    calls = bound(memory)
    before = memory.snapshot()
    assert calls.call is not None
    with pytest.raises(ValueError, match="one scalar address"):
        calls.call(target, args, data)
    assert memory.snapshot() == before


def test_unknown_calls_delegate_or_refuse() -> None:
    memory = ReplayMemory()
    seen = []

    def call(target: int, args: tuple[int, ...], data: memoryview | None) -> int:
        seen.append((target, args, data))
        return 123

    calls = bind_replay_task_facet_construction(
        context(memory), ReplayTaskRebuildCalls(call), bind_local=memory.bind_local, mxcsr=0x1F80
    )
    assert invoke(calls, 0xBAD, 42) == 123
    assert seen == [(0xBAD, (42,), None)]
    missing = bind_replay_task_facet_construction(
        context(memory), ReplayTaskRebuildCalls(None), bind_local=memory.bind_local, mxcsr=0x1F80
    )
    with pytest.raises(UnresolvedReplayTaskRebuild, match="reachedbad"):
        invoke(missing, 0xBAD)


def test_fresh_facet_profile_defines_only_selected_fields_and_real_maps() -> None:
    memory = ReplayMemory()
    subject = memory.allocate(0x7C0)
    initialize_fresh_replay_task_facets(context(memory, subject), calls=bound(memory, subject))
    assert memory.mapped_bytes == 0x7C0 + 568
    for offset, size in (
        (0x448, 24),
        (0x530, 24),
        (0x58C, 1),
        (0x6AC, 52),
        (0x730, 24),
        (0x748, 16),
        (0x7A8, 24),
    ):
        assert memory.read_bytes(subject + offset, size) == bytes(size)
    for offset, size in ((0, 8), (0x10, 16), (0x588, 4), (0x58D, 3), (0x758, 4)):
        with pytest.raises(ReplayMemoryError, match="undefined"):
            memory.read_bytes(subject + offset, size)
    for offset in (0x548, 0x5D8, 0x6E0):
        assert memory.read(subject + offset, 4) == 0x3F800000
        assert memory.read(subject + offset + 0x10, 8) == 0


@pytest.fixture(scope="module")
def actual_town_center(tmp_path_factory):
    directory = tmp_path_factory.mktemp("real-town-center-task-facet")
    fixture = Path(__file__).parent / "fixtures/native_replay_program_54800.zip"
    with zipfile.ZipFile(fixture) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        case = next(row for row in manifest["cases"] if row["sample"] == "3p")
        key = case["selected_baselines"][1]["109"]
        at, size = manifest["bodies"][key]
        raw = archive.read("bodies.bin")[at : at + size]
        assert hashlib.sha256(raw).hexdigest() == key
        reader = SaveReader(raw, version=0x43E666)
        baseline = read_game_data_master(reader)
        assert not reader.remaining
        path = directory / case["window_member"]
        window = archive.read(case["window_member"])
        assert hashlib.sha256(window).hexdigest() == case["window_sha256"]
        path.write_bytes(window)
    player = load_replay_world(path).prefix.world.players[1]
    saved_object = player.object_lists.ordinary.objects[1]
    assert (
        saved_object.object_id,
        saved_object.owner,
        saved_object.master_id,
        saved_object.type_group,
    ) == (5595, 1, 109, 80)
    assert (saved_object.offset, saved_object.end_offset) == (7939900, 7940777)
    assert hashlib.sha256(saved_object.raw).hexdigest() == (
        "411cf6efe00a7333b31880763f4aa25db800a79da2af31974d20464089adfaf9"
    )
    return restore_replay_master_tasks(player.masters.masters[109], {109: baseline})


def real_task_facets(logical):
    memory = ReplayMemory()
    subject = memory.allocate(0x7C0)
    current = context(memory, subject)
    memory.map_bytes(0x1432BC3A0, (0x1412691B0).to_bytes(8, "little"), writable=False)
    memory.map_bytes(0x143199938, (0x142D6E3B7).to_bytes(8, "little"), writable=False)
    memory.map_bytes(0x1431999A0, (0x142D6E3DB).to_bytes(8, "little"), writable=False)
    constructors = bind_replay_task_construction(current, memory.runtime_calls())
    storage = bind_replay_task_list_storage(current, constructors)
    references = bind_replay_task_references(current, storage)
    task_list = materialize_replay_task_definitions(
        current,
        logical.tasks,
        master=0,
        factory_target=0x141323AE0,
        references=ReplayTaskReferenceContexts(0, 0),
        calls=references,
        bind_local=memory.bind_local,
    )
    assert len(task_list.task_addresses) == 20
    assert [memory.read(t + 0xE, 2) for t in task_list.task_addresses] == (
        [7] + [155] * 15 + [161] * 4
    )
    initialize_fresh_replay_task_facets(current, calls=bound(memory, subject))
    out = memory.allocate(32)
    # No unobserved owner/master fields, ceil IAT, static growth bound, or
    # object vtable is needed by this explicitly selected direct rebuild path.
    calls = bind_replay_task_execution(
        current,
        memory.runtime_calls(),
        bind_local=memory.bind_local,
        pair_out=out,
        byte_out=out + 16,
        mxcsr=0x1F80,
        prefix_scratch=ReplayTaskPrefixScratch(bytes(64), bytes(3), bytes(3)),
    )
    return memory, current, task_list.address, calls, out


def rebuild(current, task_list, calls) -> None:
    # Logical zero seed policy; saved records contain no native stack bytes.
    run_replay_task_rebuild(
        current,
        task_list,
        mxcsr=0x1F80,
        calls=calls,
        scratch=ReplayTaskRebuildScratch(bytes(48), bytes(3), bytes(3)),
    )


def test_real_town_center_stops_at_missing_feature_after_prior_index_effect(actual_town_center):
    memory, current, task_list, calls, _ = real_task_facets(actual_town_center)
    with pytest.raises(ReplayMemoryError, match="unmapped replay address144114154"):
        rebuild(current, task_list, calls)
    subject = current.subject
    assert memory.read(subject + 0x58C, 1) == 0
    assert memory.read(subject + 0x6F0, 8) == 1  # Actual first group published.
    head = memory.read(subject + 0x6E8, 8)
    group = memory.read(head, 8)
    criterion_head = memory.read(group + 0x28, 8)
    criterion = memory.read(criterion_head, 8)
    indices = memory.read(criterion + 0x28, 8)
    assert memory.read(indices, 4) == 0
    assert memory.read(subject + 0x730, 8) == 0  # Rule row not appended yet.


def test_real_town_center_builds_fifteen_rules_and_rebuilds_after_snapshot(actual_town_center):
    memory, current, task_list, calls, out = real_task_facets(actual_town_center)
    memory.map_bytes(0x144114154, bytes(4), writable=False)  # Explicit scalar-find profile.
    rebuild(current, task_list, calls)
    subject = current.subject
    rows = memory.read(subject + 0x730, 8)
    assert memory.read(subject + 0x738, 8) == rows + 15 * 40
    assert [memory.read(rows + i * 40, 4) for i in range(15)] == [900 + s for s in SELECTORS]
    for i in range(15):
        row = rows + i * 40
        assert memory.read(row + 4, 4) == 109
        assert memory.read(row + 8, 4) == 0x41700000
        assert memory.read(row + 12, 4) == 0x3F800000
        assert memory.read(row + 0x18, 8) == 0
        assert memory.read(row + 0x20, 4) == 0xFFFFFFFF
    head = memory.read(subject + 0x6E8, 8)
    group = memory.read(head, 8)
    classes = memory.read(group + 0x60, 8)
    assert list(struct.unpack("<15I", memory.read_bytes(classes, 60))) == SELECTORS
    criterion_head = memory.read(group + 0x28, 8)
    criterion = memory.read(criterion_head, 8)
    indices = memory.read(criterion + 0x28, 8)
    assert list(struct.unpack("<15I", memory.read_bytes(indices, 60))) == list(range(15))
    before = memory.snapshot()
    rebuild(current, task_list, calls)
    assert memory.read(subject + 0x730, 8) == rows
    with pytest.raises(ReplayMemoryError, match="unmapped"):
        memory.read(group, 1)
    restored = ReplayMemory.from_snapshot(before)
    restored_context = context(restored, subject)
    restored_calls = bind_replay_task_execution(
        restored_context,
        restored.runtime_calls(),
        bind_local=restored.bind_local,
        pair_out=out,
        byte_out=out + 16,
        mxcsr=0x1F80,
        prefix_scratch=ReplayTaskPrefixScratch(bytes(64), bytes(3), bytes(3)),
    )
    rebuild(restored_context, task_list, restored_calls)
    assert restored.snapshot() == memory.snapshot()
