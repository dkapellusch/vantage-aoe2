"""Owned data initialization through real source query/insertion providers.

The small JSON inputs are authored engine datasets, not native snapshots.
No unknown callback supplies construction, registry lookup or default success.
"""

from __future__ import annotations

import json

import pytest

from vantage.replay_civilization_data import (
    ReplayCivilizationData,
    ReplayCivilizationDefinition,
    build_replay_civilization_registry,
    read_replay_civilization_data,
)
from vantage.replay_civilization_providers import bind_replay_civilization_providers
from vantage.replay_civilization_registry_insert import (
    bind_replay_civilization_registry_insert,
)
from vantage.replay_era_data import read_replay_era_data
from vantage.replay_memory import ReplayMemory, ReplayMemoryError
from vantage.replay_memory_compare import (
    bind_replay_memcmp_thunk,
    replay_memory_comparison_calls,
)
from vantage.replay_player_civilization_lookup import bind_replay_player_civilization_lookup
from vantage.replay_player_research_rows import bind_replay_player_research_rows
from vantage.replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
)
from vantage.replay_unit_ai_map import ReplayUnitAIMapAtomics


def _raw(*names: str) -> bytes:
    return json.dumps(
        {
            "civilization_list": [
                {"data_name": name, "unused_nested": {"values": [index, None, True]}}
                for index, name in enumerate(names)
            ]
        }
    ).encode()


def _engine() -> tuple[ReplayMemory, ReplayTaskRebuildCalls]:
    memory = ReplayMemory()
    context = ReplayTaskRebuildStorage(memory.allocate(1), memory.read, memory.write)
    atomics = ReplayUnitAIMapAtomics(memory.compare_exchange_u32, memory.fetch_add_u32)
    runtime = replay_memory_comparison_calls(memory, comparison_target=0xC1D001)
    memory.map_bytes(0x143199940, (0xC1D001).to_bytes(8, "little"))
    routes = {}

    def dispatch(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        if target in routes:
            return routes[target](target, args, data)
        assert runtime.call
        return runtime.call(target, args, data)

    calls = ReplayTaskRebuildCalls(dispatch)
    for bound, targets in (
        (
            bind_replay_civilization_registry_insert(context, calls, atomics=atomics),
            (0x140F6AE70, 0x140F6B790),
        ),
        (
            bind_replay_civilization_providers(context, calls),
            (0x140FA3420, 0x140FA36A0, 0x140F6A690, 0x140F6A320, 0x140A162A0),
        ),
        (bind_replay_memcmp_thunk(context, calls, imports=runtime), (0x142D6E3BD,)),
        (
            bind_replay_player_civilization_lookup(
                context, calls, bind_local=memory.bind_local, scratch=b"\xa5" * 8
            ),
            (0x140F6A4B0, 0x140A1B220, 0x140A15CA0),
        ),
        (
            bind_replay_player_research_rows(
                context, calls, bind_local=memory.bind_local, error_seed=bytes(8), imports=runtime
            ),
            (0x140F92850, 0x140F92070, 0x1402A8790, 0x140F6BBF0),
        ),
    ):
        assert bound.call
        for target in targets:
            routes[target] = bound.call
    return memory, calls


def _descriptor(memory: ReplayMemory, name: bytes) -> int:
    address = memory.allocate(24)
    pointer = memory.allocate(len(name) + 1)
    memory.write_bytes(pointer, name + b"\0")
    for offset, value in ((0, pointer), (8, len(name)), (16, len(name) + 1)):
        memory.write(address + offset, 8, value)
    return address


def test_selected_data_preserves_ordinals_complete_rows_and_source_identity() -> None:
    raw = _raw("GAIA", "KHITANS-CIV", "DANES-CIV")
    data = read_replay_civilization_data(raw, count=2)
    assert data.total_rows == 3
    assert [row.ordinal for row in data.definitions] == [0, 1]
    assert [row.data_name for row in data.definitions] == [b"GAIA", b"KHITANS-CIV"]
    assert json.loads(data.definitions[1].source_row)["unused_nested"] == {
        "values": [1, None, True]
    }
    assert data.source_sha256 != read_replay_civilization_data(_raw("GAIA"), count=1).source_sha256


@pytest.mark.parametrize(
    "raw,count",
    [
        (b"[]", 0),
        (b"{}", 0),
        (b'{"civilization_list":null}', 0),
        (b'{"civilization_list":[1]}', 1),
        (b'{"civilization_list":[{}]}', 1),
        (b'{"civilization_list":[{"data_name":3}]}', 1),
        (_raw(""), 1),
        (_raw("A\0B"), 1),
        (_raw("A"), 2),
        (_raw("A"), -1),
        (_raw("A"), True),
        (_raw("A"), 1 << 32),
    ],
)
def test_invalid_selected_input_refuses(raw: bytes, count: int) -> None:
    with pytest.raises(ValueError):
        read_replay_civilization_data(raw, count=count)


@pytest.mark.parametrize("family", [1, 2])
@pytest.mark.parametrize(
    "names",
    [
        ("GAIA",),
        ("Z", "Y", "X", "W", "V", "U", "T"),
        ("B", "A", "C", "AA", "BC", "AB"),
        ("GAIA", "KHITANS-CIV", "DANES-CIV", "MONGOL-CIV"),
    ],
)
def test_populated_indices_resolve_ids_and_names_with_real_source_bodies(
    family: int,
    names: tuple[str, ...],
) -> None:
    memory, calls = _engine()
    data = read_replay_civilization_data(_raw(*names), count=len(names))
    registry = build_replay_civilization_registry(memory, data, writer_family=family, calls=calls)
    game = memory.allocate(0x688)
    memory.write(game + 0x680, 8, family)
    memory.map_bytes(0x144353698, game.to_bytes(8, "little"))
    assert calls.call
    for definition, record in zip(data.definitions, registry.records, strict=True):
        assert calls.call(0x140F6A690, (record + 0x58, family), None) == definition.ordinal
        assert calls.call(0x140F6A320, (definition.ordinal, family), None) == record
        assert calls.call(0x140F6A4B0, (record + 0x58,), None) == record
        assert memory.read(record + 8, 4) == 1
        with pytest.raises(ReplayMemoryError):
            memory.read(record, 8)  # No fabricated native vtable or record construction.
        with pytest.raises(ReplayMemoryError):
            memory.read(record + 0x18, 4)
    missing = _descriptor(memory, b"NEVER-REGISTERED")
    assert calls.call(0x140F6A4B0, (missing,), None) == 0
    assert memory.read(registry.name_header + 8, 8) == len(names)
    assert memory.read(memory.read(registry.numeric_header + 8, 8), 4) == 0
    for record, node in zip(registry.records, registry.name_nodes, strict=True):
        assert memory.read(record + 0x58, 8) != memory.read(node + 0x20, 8)


def test_equivalent_names_keep_first_id_and_all_numeric_records() -> None:
    memory, calls = _engine()
    data = read_replay_civilization_data(_raw("GAIA", "GAIA", "OTHER"), count=3)
    registry = build_replay_civilization_registry(memory, data, writer_family=2, calls=calls)
    assert len(registry.records) == 3 and len(registry.name_nodes) == 2
    assert memory.read(registry.name_header + 8, 8) == 2
    assert calls.call
    assert calls.call(0x140F6A690, (registry.records[1] + 0x58, 2), None) == 0
    game = memory.allocate(0x688)
    memory.write(game + 0x680, 8, 2)
    memory.map_bytes(0x144353698, game.to_bytes(8, "little"))
    assert calls.call(0x140F6A4B0, (registry.records[1] + 0x58,), None) == registry.records[0]
    for index, record in enumerate(registry.records):
        assert calls.call(0x140F6A320, (index, 2), None) == record


def test_selector_zero_keeps_source_mixed_family_relationship() -> None:
    memory, calls = _engine()
    first = read_replay_civilization_data(_raw("FIRST-0", "ONLY-FIRST"), count=2)
    second = read_replay_civilization_data(_raw("SECOND-0", "ONLY-SECOND"), count=2)
    family1 = build_replay_civilization_registry(memory, first, writer_family=1, calls=calls)
    family2 = build_replay_civilization_registry(memory, second, writer_family=2, calls=calls)
    assert calls.call
    assert calls.call(0x140F6A690, (family1.records[1] + 0x58, 0), None) == 1
    assert calls.call(0x140F6A690, (family2.records[1] + 0x58, 0), None) == 0
    assert calls.call(0x140F6A320, (1, 0), None) == family2.records[1]
    assert family1.records[0] != family2.records[0]


def test_empty_prefix_and_missing_insert_provider_are_explicit() -> None:
    memory, calls = _engine()
    empty = read_replay_civilization_data(_raw("GAIA"), count=0)
    registry = build_replay_civilization_registry(memory, empty, writer_family=2, calls=calls)
    assert not registry.records and memory.read(registry.name_header + 8, 8) == 0
    assert calls.call and calls.call(0x140F6A320, (0, 2), None) == 0
    partial = ReplayMemory()
    with pytest.raises(UnresolvedReplayTaskRebuild):
        build_replay_civilization_registry(
            partial,
            read_replay_civilization_data(_raw("GAIA"), count=1),
            writer_family=2,
            calls=ReplayTaskRebuildCalls(None),
        )
    assert partial.read(0x143DB0680, 4) == 0
    assert partial.read(0x143DB0688, 8) == 0x143DB06A0
    assert partial.read(0x1442E9728, 8) == 0


def test_second_build_refuses_occupied_globals_and_preserves_existing_registry() -> None:
    memory, calls = _engine()
    data = read_replay_civilization_data(_raw("GAIA", "B"), count=2)
    registry = build_replay_civilization_registry(memory, data, writer_family=2, calls=calls)
    root = memory.read(registry.numeric_header + 8, 8)
    with pytest.raises(ReplayMemoryError):
        build_replay_civilization_registry(memory, data, writer_family=2, calls=calls)
    assert memory.read(registry.numeric_header + 8, 8) == root
    assert memory.read(registry.name_header + 8, 8) == 2
    assert calls.call
    assert calls.call(0x140F6A320, (1, 2), None) == registry.records[1]


def test_definition_and_dataset_contracts_reject_fabricated_shapes() -> None:
    with pytest.raises(ValueError):
        ReplayCivilizationDefinition(True, b"A", b"{}")
    with pytest.raises(ValueError):
        ReplayCivilizationData((ReplayCivilizationDefinition(1, b"A", b"{}"),), "0" * 64, 1)


def _eras():
    return read_replay_era_data(
        json.dumps(
            [
                {"Name": "base"},
                {
                    "Name": "antiquity",
                    "TechDisplayOverrides": [
                        {"TechId": 104, "NameId": 407089, "IconId": 150},
                        {
                            "TechId": 101,
                            "NameId": 407090,
                            "IconId": 151,
                            "DescriptionId": 408090,
                            "ExtendedDescriptionId": 428090,
                        },
                    ],
                },
            ]
        ).encode()
    )


@pytest.mark.parametrize("family", [1, 2])
def test_explicit_eras_back_only_genuine_empty_or_populated_research_rows(family):
    memory, calls = _engine()
    eras = _eras()
    raw = json.dumps(
        {
            "civilization_list": [
                {"data_name": "UNUSUAL-NAME", "era": "base"},
                {"data_name": "GAIA", "era": "antiquity"},
                {"data_name": "SECOND", "era": "antiquity"},
            ]
        }
    ).encode()
    data = read_replay_civilization_data(raw, count=3, eras=eras)
    assert data.era_source_sha256 == eras.source_sha256
    registry = build_replay_civilization_registry(memory, data, writer_family=family, calls=calls)
    first = registry.records[0]
    assert tuple(memory.read(first + offset, 8) for offset in (0x138, 0x140, 0x148)) == (0, 0, 0)
    expected = bytes.fromhex(
        "680000003136060096000000fefffffffeffffff6500000032360600970000001a3a06003a880600"
    )
    begins = []
    assert calls.call
    for index, record in enumerate(registry.records[1:], 1):
        begin = memory.read(record + 0x138, 8)
        begins.append(begin)
        assert memory.read_bytes(begin, 40) == expected
        assert memory.read(record + 0x140, 8) == begin + 40
        assert memory.read(record + 0x148, 8) == begin + 40
        assert calls.call(0x140F6A320, (index, family), None) == record
        with pytest.raises(ReplayMemoryError):
            memory.read(record + 0x130, 8)
        with pytest.raises(ReplayMemoryError):
            memory.read(record + 0x150, 8)
    assert begins[0] != begins[1]  # Each civilization owns its actual copied buffer.
    # Exercise the real Derived-tail accessor against this populated registry.
    destination = memory.allocate(24)
    assert calls.call(0x140F92850, (registry.records[1] + 0x100, destination), None) == destination
    copied = memory.read(destination, 8)
    assert copied not in begins and memory.read_bytes(copied, 40) == expected
    assert memory.read(destination + 8, 8) == copied + 40
    calls.call(0x1402A8790, (copied, 40), None)
    with pytest.raises(ReplayMemoryError):
        memory.read(copied, 1)


def test_no_eras_preserves_undefined_research_fields_despite_gaia_name():
    memory, calls = _engine()
    data = read_replay_civilization_data(_raw("GAIA"), count=1)
    registry = build_replay_civilization_registry(memory, data, writer_family=2, calls=calls)
    assert data.era_source_sha256 is None and data.definitions[0].research_rows is None
    for offset in (0x138, 0x140, 0x148):
        with pytest.raises(ReplayMemoryError):
            memory.read(registry.records[0] + offset, 8)


@pytest.mark.parametrize("era", [None, 1, "unknown", "BASE"])
def test_optional_projection_refuses_unadmitted_era_selection(era):
    raw = json.dumps({"civilization_list": [{"data_name": "GAIA", "era": era}]}).encode()
    with pytest.raises(ValueError):
        read_replay_civilization_data(raw, count=1, eras=_eras())


def test_explicit_projection_selects_only_requested_prefix():
    raw = json.dumps(
        {
            "civilization_list": [
                {"data_name": "A", "era": "base"},
                {"data_name": "B", "era": "unknown"},
            ]
        }
    ).encode()
    data = read_replay_civilization_data(raw, count=1, eras=_eras())
    assert len(data.definitions) == 1 and data.total_rows == 2
    assert data.definitions[0].research_rows == b""


def test_era_digest_and_whole_rows_are_required_together():
    row = ReplayCivilizationDefinition(0, b"A", b"{}", b"")
    with pytest.raises(ValueError, match="resolved era source"):
        ReplayCivilizationData((row,), "0" * 64, 1)
    row = ReplayCivilizationDefinition(0, b"A", b"{}")
    with pytest.raises(ValueError, match="resolved era source"):
        ReplayCivilizationData((row,), "0" * 64, 1, "1" * 64)
    with pytest.raises(ValueError, match="era source SHA256"):
        ReplayCivilizationData((), "0" * 64, 0, "bad")
    with pytest.raises(ValueError, match="twenty-byte"):
        ReplayCivilizationDefinition(0, b"A", b"{}", b"x")
