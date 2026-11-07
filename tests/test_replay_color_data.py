"""Authored typed DAT fixtures and actual color-consumer/17B mode composition."""

from __future__ import annotations

from dataclasses import replace

import pytest

from vantage.replay_base_saved_registration import (
    ReplayBaseSavedRegistrationFP,
    ReplayBaseSavedRegistrationScratch,
    bind_replay_base_saved_registration,
)
from vantage.replay_binary import SaveReader
from vantage.replay_color_data import build_replay_color_backing
from vantage.replay_game_data import GameDataColors, read_game_data_colors
from vantage.replay_memory import ReplayMemory, ReplayMemoryError
from vantage.replay_player_base_children import set_replay_player_color
from vantage.replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
)


def _colors(*indices: int) -> GameDataColors:
    rows = [
        b"".join(
            value.to_bytes(4, "little") for value in (ordinal, 10, 11, 12, 13, 14, 15, 16, index)
        )
        for ordinal, index in enumerate(indices)
    ]
    return read_game_data_colors(
        SaveReader(len(rows).to_bytes(2, "little") + b"".join(rows), version=0x43E666)
    )


def test_distinct_descriptors_define_only_ninth_serialized_dword() -> None:
    memory = ReplayMemory()
    data = _colors(2, 0, 0xFFFFFFFF, 1)
    backing = build_replay_color_backing(memory, data)
    assert backing.palette_indices == (2, 0, 0xFFFFFFFF, 1)
    assert backing.raw_rows == tuple(row.raw for row in data.colors)
    assert len(set(backing.descriptors)) == 4
    for index, descriptor in enumerate(backing.descriptors):
        assert memory.read(backing.table + index * 8, 8) == descriptor
        assert memory.read(descriptor + 4, 4) == backing.palette_indices[index]
        for offset, size in ((0, 4), (8, 48)):
            with pytest.raises(ReplayMemoryError, match="undefined"):
                memory.read_bytes(descriptor + offset, size)


def test_empty_data_has_no_allocations_or_world_publication() -> None:
    memory = ReplayMemory()
    backing = build_replay_color_backing(memory, _colors())
    assert backing.table == 0 and not backing.descriptors and not backing.raw_rows
    assert memory.mapped_bytes == 0


@pytest.mark.parametrize("index,expected", [(0, 103), (1, 101), (2, 100)])
def test_actual_color_setter_consumes_data_field4_with_signed_palette_index(
    index: int,
    expected: int,
) -> None:
    memory = ReplayMemory()
    player, world, game, mode = (memory.allocate(size) for size in (0x660, 0x108, 0x568, 12))
    memory.write(player + 8, 8, world)
    memory.write(player + 0x648, 4, 1)
    memory.write(game + 0x560, 8, mode)
    memory.write(mode + 8, 4, 4)  # Explicit authored mode fixture, not a replay/native observation.
    memory.map_bytes(0x144353698, game.to_bytes(8, "little"))
    memory.map_bytes(0x14425B930, bytes(8))  # Explicit no-settings fixture, never inferred.
    memory.map_bytes(0x1444167AF, b"\xa5")
    memory.map_bytes(
        0x1432F46B0, b"".join(value.to_bytes(4, "little") for value in range(100, 117))
    )
    backing = build_replay_color_backing(memory, _colors(2, 0, 0xFFFFFFFF))
    memory.write(
        world + 0xE8, 8, backing.table
    )  # Explicit owner publication, no header construction.
    context = ReplayTaskRebuildStorage(player, memory.read, memory.write)
    calls = bind_replay_base_saved_registration(
        context,
        ReplayTaskRebuildCalls(None),
        imports=ReplayTaskRebuildCalls(None),
        fp_calls=ReplayBaseSavedRegistrationFP(None),
        bind_local=memory.bind_local,
        scratch=ReplayBaseSavedRegistrationScratch(b"\xa5" * 0xB0),
    )
    set_replay_player_color(context, player, index, calls=calls)
    assert memory.read(player + 0x1F4, 4) == index
    assert memory.read(player + 0x200, 8) == backing.descriptors[index]
    assert memory.read(player + 0x1F8, 8) == backing.descriptors[index]
    assert memory.read(player + 0x650, 4) == memory.read(player + 0x658, 4) == expected
    assert memory.read(player + 0x654, 4) == 0xA5
    memory.write(backing.descriptors[index] + 4, 4, 1)
    set_replay_player_color(context, player, index, calls=calls)
    assert memory.read(player + 0x658, 4) == 102  # Current backing, not cached metadata.
    for offset in (0xF0, 0xF8, 0x100):
        with pytest.raises(ReplayMemoryError, match="undefined"):
            memory.read(world + offset, 8)


def test_populated_color_table_does_not_invent_game_mode_success() -> None:
    memory = ReplayMemory()
    player, world = memory.allocate(0x660), memory.allocate(0xF0)
    memory.write(player + 8, 8, world)
    memory.write(player + 0x648, 4, 1)
    memory.map_bytes(0x144353698, (0x1234).to_bytes(8, "little"))
    backing = build_replay_color_backing(memory, _colors(7))
    memory.write(world + 0xE8, 8, backing.table)
    context = ReplayTaskRebuildStorage(player, memory.read, memory.write)
    with pytest.raises(UnresolvedReplayTaskRebuild, match="140d6a940"):
        set_replay_player_color(context, player, 0, calls=ReplayTaskRebuildCalls(None))
    assert memory.read(player + 0x200, 8) == backing.descriptors[0]
    with pytest.raises(ReplayMemoryError, match="undefined"):
        memory.read(player + 0x650, 4)


@pytest.mark.parametrize(
    "mutation",
    [
        "count",
        "bool-count",
        "rows",
        "section",
        "fields",
        "field-bool",
        "row-size",
        "row-value",
        "field-key",
    ],
)
def test_inconsistent_typed_wire_data_refuses_before_any_memory_effect(mutation: str) -> None:
    memory = ReplayMemory()
    data = _colors(4)
    row = data.colors[0]
    if mutation == "count":
        data = replace(data, count=2)
    elif mutation == "bool-count":
        data = replace(data, count=True)
    elif mutation == "rows":
        data = replace(data, colors=())
    elif mutation == "section":
        data = replace(data, raw=data.raw + b"X")
    else:
        fields = dict(row.fields)
        raw = row.raw
        if mutation == "fields":
            fields.pop(4)
        elif mutation == "field-bool":
            fields[4] = True
        elif mutation == "row-size":
            raw = raw[:-1]
        elif mutation == "row-value":
            fields[4] = 5
        else:
            fields[False] = fields.pop(0)
        data = replace(data, colors=(replace(row, fields=fields, raw=raw),))
    before = memory.snapshot()
    with pytest.raises(ValueError):
        build_replay_color_backing(memory, data)
    assert memory.snapshot() == before


def test_allocation_failure_keeps_real_partial_table_and_descriptor() -> None:
    memory = ReplayMemory(max_bytes=80)
    with pytest.raises(MemoryError):
        build_replay_color_backing(memory, _colors(9, 3))
    snapshot = memory.snapshot()
    assert memory.mapped_bytes == 16 + 0x38
    table, descriptor = snapshot.regions[0].address, snapshot.regions[1].address
    assert memory.read(table, 8) == descriptor and memory.read(descriptor + 4, 4) == 9
    with pytest.raises(ReplayMemoryError, match="undefined"):
        memory.read(table + 8, 8)
