"""Actual native records composed in explicit sparse containers, plus failures."""

from __future__ import annotations

import copy
import gzip
import json
from dataclasses import fields, is_dataclass, replace
from functools import cache
from pathlib import Path
from types import UnionType
from typing import Any, Literal, Union, get_args, get_origin, get_type_hints

import pytest

from vantage.replay_binary import SaveReader
from vantage.replay_game_data import read_game_data_graphics, read_game_data_master
from vantage.replay_initial_player import SavedInitialPlayer
from vantage.replay_masters import SavedMasterTable, read_master
from vantage.replay_object_lists import (
    SavedObjectList,
    SavedPlayerObjectLists,
    SavedPlayerObjectTrailer,
)
from vantage.replay_objects import read_saved_object
from vantage.replay_players import read_player_header
from vantage.replay_saved_world import SavedReplayWorld
from vantage.replay_world_assembly import (
    ReplayWorldAssemblyError,
    assemble_replay_initial_world,
)

FIXTURE = Path(__file__).parent / "fixtures/native_initial_world_assembly_54800.json.gz"


@cache
def _fixture():
    return json.loads(gzip.decompress(FIXTURE.read_bytes()))


def _empty(kind):
    """Typed empty scaffolding only; never presented as native saved-wire data.

    The assembler preserves and does not inspect unrelated scenario/AI/map
    sections. Real object/master/header/graphics records replace these empty
    container members below. Exhaustive complete-world coverage is separate.
    """
    origin, args = get_origin(kind), get_args(kind)
    if origin in (Union, UnionType):
        return None if type(None) in args else _empty(args[0])
    if origin is Literal:
        return args[0]
    if origin in (dict, list, tuple):
        return origin()
    if is_dataclass(kind):
        hints = get_type_hints(kind)
        return kind(**{field.name: _empty(hints[field.name]) for field in fields(kind)})
    if kind is Any:
        return None
    return kind()


def _lists(*wire):
    lists = tuple(SavedObjectList(0, 0, 0, 0, tuple(group), 0, b"") for group in wire)
    trailer = SavedPlayerObjectTrailer(0, 0, 0, (), 0, 0, 0, 0, 0, 0, 0, b"")
    return SavedPlayerObjectLists(0, 0, *lists, trailer, b"")


def _decode(case):
    count = len(case["players"])
    players, selected = [], []
    for row in case["players"]:
        header_reader = SaveReader(bytes.fromhex(row["header_hex"]))
        header = read_player_header(header_reader, count, player_id=row["owner"])
        assert header_reader.remaining == 0
        masters = {}
        for master in row["masters"]:
            reader = SaveReader(bytes.fromhex(master["saved_hex"]))
            masters[master["index"]] = read_master(
                reader, master_id=master["index"], type_group=master["type_group"]
            )
            assert reader.remaining == 0
        table = {}
        for index, raw in row["baselines"].items():
            reader = SaveReader(bytes.fromhex(raw), version=0x43E666)
            table[int(index)] = read_game_data_master(reader)
            assert reader.remaining == 0
        groups = {name: [] for name in ("ordinary", "sleeping", "dopple")}
        for obj in row["objects"]:
            reader = SaveReader(bytes.fromhex(obj["raw_hex"]))
            groups[obj["wire_list"]].append(read_saved_object(reader))
            assert reader.remaining == 0
        current = SavedMasterTable(
            0,
            0,
            row["master_count"],
            tuple(int(i in masters) for i in range(row["master_count"])),
            masters,
            b"",
        )
        players.append(
            replace(
                _empty(SavedInitialPlayer),
                header=header,
                masters=current,
                object_lists=_lists(*(groups[name] for name in groups)),
            )
        )
        selected.append(table)
    saved = _empty(SavedReplayWorld)
    world = replace(
        saved.prefix.world,
        players=tuple(players),
        prefix=replace(saved.prefix.world.prefix, num_players=count),
    )
    saved = replace(saved, prefix=replace(saved.prefix, world=world))
    reader = SaveReader(bytes.fromhex(case["graphics_hex"]), version=0x43E666)
    graphics = read_game_data_graphics(reader).graphics
    assert reader.remaining == 0
    return saved, selected, graphics


def _replace_player(saved, owner, **changes):
    players = list(saved.prefix.world.players)
    players[owner] = replace(players[owner], **changes)
    world = replace(saved.prefix.world, players=tuple(players))
    return replace(saved, prefix=replace(saved.prefix, world=world))


def _object_world(saved, owner, *wire):
    for index in range(len(saved.prefix.world.players)):
        saved = _replace_player(
            saved, index, object_lists=_lists(*(wire if index == owner else ((), (), ())))
        )
    return saved


def _prototype():
    return _decode(_fixture()["cases"][0])


@pytest.mark.parametrize("case", _fixture()["cases"], ids=lambda row: row["sample"])
def test_actual_records_match_native_bindings_and_all_ninety_building_edges(case):
    saved, tables, graphics = _decode(case)
    before = copy.deepcopy((saved, tables, graphics))
    result = assemble_replay_initial_world(saved, tables, graphics=graphics)
    assert result.saved is saved and result.graphics is graphics
    assert result.saved.scenario is saved.scenario and result.saved.tail is saved.tail
    direct = inverse = hp_differences = z_differences = 0
    expected_objects = {obj["raw_id"]: obj for p in case["players"] for obj in p["objects"]}
    assert set(result.objects_by_raw_id) == set(expected_objects)
    assert 0 in result.objects_by_raw_id
    assert all(
        obj["native_key"] not in result.objects_by_raw_id
        for obj in expected_objects.values()
        if obj["native_key"] < 0
    )
    for owner, player in enumerate(result.players):
        assert player.saved is saved.prefix.world.players[owner]
        assert player.selected_baseline is tables[owner]
        assert len(player.masters) == player.saved.masters.count
        for index, master in enumerate(player.masters):
            if index not in player.saved.masters.masters:
                assert master is None
                continue
            assert master is not None and master.saved is player.saved.masters.masters[index]
            assert master.common.saved is master.saved.base
            assert master.common.baseline is tables[owner][master.baseline_index]
            expected_master = next(
                m for m in case["players"][owner]["masters"] if m["index"] == index
            )
            for _fid, offset, representation, expected in expected_master["native_common"]:
                value = (
                    master.saved.type_group
                    if representation == "type"
                    else master.common.fields[offset]
                )
                assert (bool(value) if representation == "bool" else value) == expected
        assert tuple(binding.saved for binding in player.bindings) == player.objects.update_order
        for group in (player.objects.ordinary, player.objects.sleeping, player.objects.dopple):
            keys = [
                obj.object_id if obj.object_id < 0x80000000 else obj.object_id - (1 << 32)
                for obj in group
            ]
            assert keys == sorted(set(keys))
        for binding in player.bindings:
            obj = binding.saved
            expected = expected_objects[obj.object_id]
            assert result.objects_by_raw_id[obj.object_id] is binding
            assert binding.master is player.masters[obj.master_id]
            assert (obj.owner, obj.master_id, *obj.position[:2]) == (
                expected["native_owner"],
                expected["native_master"],
                expected["native_x"],
                expected["native_y"],
            )
            assert binding.unresolved_common_reference_id is None
            hp_differences += obj.hp != expected["native_hp"]
            z_differences += obj.position[2] != expected["native_z"]
            if obj.building is None:
                assert binding.building_links is binding.building_reference_ids is None
                continue
            assert binding.building_links is not None and len(binding.building_links) == 5
            for slot, (raw, reference, target) in enumerate(
                zip(
                    obj.building.linked_references,
                    binding.building_reference_ids,
                    binding.building_links,
                    strict=True,
                )
            ):
                assert reference == (raw if raw < 0x80000000 else raw - (1 << 32))
                if raw == 0xFFFFFFFF:
                    assert reference == -1 and target is None
                else:
                    assert target is result.objects_by_raw_id[raw].saved
                    if slot == 0:
                        assert target.object_id == expected["native_linked_owner"]
                        direct += 1
                    else:
                        assert (
                            expected_objects[target.object_id]["native_linked_owner"]
                            == obj.object_id
                        )
                        inverse += 1
    assert direct == inverse == (15 if case["sample"] == "3p" else 30)
    assert hp_differences == (3 if case["sample"] == "3p" else 5)
    assert z_differences == 1  # One actual saved0/native9 bird per compact sample, left unchanged.
    assert result.pending.reference_callbacks and result.pending.lifecycle_updates
    assert result.pending.spatial_registries and not hasattr(result, "step")
    with pytest.raises(TypeError):
        result.objects_by_raw_id[999] = result.objects_by_raw_id[0]
    assert (saved, tables, graphics) == before


def test_null_current_slots_are_not_filled_from_explicit_baseline_and_masters_are_shared():
    saved, tables, graphics = _prototype()
    player = saved.prefix.world.players[0]
    empty = next(i for i, present in enumerate(player.masters.presence) if not present)
    tables[0][empty] = next(iter(tables[0].values()))
    result = assemble_replay_initial_world(saved, tables, graphics=graphics)
    assert result.players[0].masters[empty] is None
    bindings = result.players[1].bindings
    first, other = next(
        (a, b)
        for a in bindings
        for b in bindings
        if a.saved is not b.saved and a.saved.master_id == b.saved.master_id
    )
    assert first.master is other.master


def test_effective_order_duplicate_suppression_and_original_wire_identity():
    saved, tables, graphics = _prototype()
    template = saved.prefix.world.players[0].object_lists.ordinary.objects[0]
    first = replace(template, object_id=3, flags=(2, 0, 0, 0))
    duplicate = replace(first, hp=12)
    negative = replace(template, object_id=0x80000000, flags=(2, 0, 0, 0))
    zero_sleep = replace(template, object_id=0, flags=(2, 1, 1, 0))
    dopple = replace(template, object_id=2, flags=(2, 1, 1, 1))
    saved = _object_world(saved, 0, (first, zero_sleep), (duplicate, negative), (dopple,))
    result = assemble_replay_initial_world(saved, tables, graphics=graphics)
    player = result.players[0]
    assert player.objects.ordinary == (negative, first)
    assert player.objects.sleeping == (zero_sleep,) and player.objects.dopple == (dopple,)
    assert result.objects_by_raw_id[3].saved is first
    assert player.saved.object_lists.sleeping.objects[0] is duplicate
    assert [b.saved.object_id for b in player.bindings] == [0x80000000, 3, 0, 2]


@pytest.mark.parametrize("reference", [0, 3, -2, -(1 << 31), (1 << 31) - 1])
def test_common148_is_explicitly_unresolved_even_when_target_exists(reference):
    saved, tables, graphics = _prototype()
    template = saved.prefix.world.players[0].object_lists.ordinary.objects[0]
    obj = replace(template, object_id=0, reference_id=reference)
    saved = _object_world(saved, 0, (obj,), (), ())
    result = assemble_replay_initial_world(saved, tables, graphics=graphics)
    assert result.objects_by_raw_id[0].unresolved_common_reference_id == reference
    assert result.objects_by_raw_id[0].saved.reference_id == reference
    assert result.pending.reference_callbacks


@pytest.mark.parametrize(
    "code,change",
    [
        ("owner", {"owner": 1}),
        ("family", {"type_group": 20}),
        ("master_index", {"master_id": -1}),
        ("master_index", {"master_id": 4000}),
        ("object", {"object_id": -50}),
        ("object", {"object_id": 1 << 32}),
        ("object", {"flags": (2, 0, 0, 999)}),
        ("common_reference", {"reference_id": 1 << 31}),
    ],
)
def test_object_errors_retain_context_and_inputs(code, change):
    saved, tables, graphics = _prototype()
    template = saved.prefix.world.players[0].object_lists.ordinary.objects[0]
    obj = replace(template, **change)
    saved = _object_world(saved, 0, (obj,), (), ())
    before = copy.deepcopy((saved, tables, graphics))
    with pytest.raises(ReplayWorldAssemblyError) as caught:
        assemble_replay_initial_world(saved, tables, graphics=graphics)
    assert caught.value.code == code and caught.value.player_index == 0
    assert caught.value.object_id == obj.object_id and caught.value.master_index == obj.master_id
    assert (saved, tables, graphics) == before


@pytest.mark.parametrize("where", ["other_list", "other_player"])
def test_ambiguous_global_raw_ids_are_rejected(where):
    saved, tables, graphics = _prototype()
    first = saved.prefix.world.players[0].object_lists.ordinary.objects[0]
    first = replace(first, flags=(2, 0, 0, 0))
    saved = _object_world(saved, 0, (first,), (), ())
    if where == "other_list":
        saved = _replace_player(
            saved, 0, object_lists=_lists((first,), (replace(first, flags=(2, 1, 0, 0)),), ())
        )
    else:
        other = _prototype()[0].prefix.world.players[1].object_lists.ordinary.objects[0]
        saved = _replace_player(
            saved, 1, object_lists=_lists((replace(other, object_id=first.object_id),), (), ())
        )
    with pytest.raises(ReplayWorldAssemblyError, match="duplicate_id"):
        assemble_replay_initial_world(saved, tables, graphics=graphics)


@pytest.mark.parametrize("null", [False, True])
def test_missing_or_null_selected_baseline_has_master_context(null):
    saved, tables, graphics = _prototype()
    index = next(iter(tables[0]))
    if null:
        tables[0][index] = None
    else:
        del tables[0][index]
    with pytest.raises(ReplayWorldAssemblyError) as caught:
        assemble_replay_initial_world(saved, tables, graphics=graphics)
    assert caught.value.code == "master_restore" and caught.value.player_index == 0
    assert caught.value.master_index is not None and caught.value.__cause__ is not None


def test_object_current_null_master_is_distinct_from_inherited_baseline():
    saved, tables, graphics = _prototype()
    template = saved.prefix.world.players[0].object_lists.ordinary.objects[0]
    empty = next(
        i for i, present in enumerate(saved.prefix.world.players[0].masters.presence) if not present
    )
    saved = _object_world(saved, 0, (replace(template, master_id=empty),), (), ())
    with pytest.raises(ReplayWorldAssemblyError, match="current_master"):
        assemble_replay_initial_world(saved, tables, graphics=graphics)


@pytest.mark.parametrize("bad", ["missing", "short", "word", "dangling"])
def test_building_slots_are_all_preserved_or_fail_precisely(bad):
    saved, tables, graphics = _prototype()
    player = saved.prefix.world.players[1]
    obj = next(o for o in player.object_lists.ordinary.objects if o.building is not None)
    building = obj.building
    if bad == "missing":
        obj = replace(obj, building=None)
    else:
        refs = building.linked_references
        refs = (
            refs[:-1]
            if bad == "short"
            else (1 << 32, *refs[1:])
            if bad == "word"
            else (999999, *refs[1:])
        )
        obj = replace(obj, building=replace(building, linked_references=refs))
    wire = tuple(
        obj if o.object_id == obj.object_id else o for o in player.object_lists.ordinary.objects
    )
    saved = _replace_player(saved, 1, object_lists=_lists(wire, (), ()))
    with pytest.raises(ReplayWorldAssemblyError) as caught:
        assemble_replay_initial_world(saved, tables, graphics=graphics)
    assert caught.value.code == "building_reference" and caught.value.object_id == obj.object_id


@pytest.mark.parametrize("bad", ["count", "presence", "key", "definition_index"])
def test_current_master_table_consistency_errors(bad):
    saved, tables, graphics = _prototype()
    player = saved.prefix.world.players[0]
    table = player.masters
    if bad == "count":
        table = replace(table, count=-1)
    elif bad == "presence":
        table = replace(table, presence=(0,) * table.count)
    elif bad == "key":
        table = replace(
            table, masters={**table.masters, table.count: next(iter(table.masters.values()))}
        )
    else:
        index = next(iter(table.masters))
        table = replace(
            table,
            masters={**table.masters, index: replace(table.masters[index], master_id=index + 1)},
        )
    saved = _replace_player(saved, 0, masters=table)
    with pytest.raises(ReplayWorldAssemblyError) as caught:
        assemble_replay_initial_world(saved, tables, graphics=graphics)
    assert caught.value.code == ("master_index" if bad == "definition_index" else "master_table")


@pytest.mark.parametrize(
    "bad", ["tables", "unordered", "players", "header", "header_bool", "graphics", "baseline"]
)
def test_context_errors_are_not_silently_inferred(bad):
    saved, tables, graphics = _prototype()
    if bad == "tables":
        tables = tables[:-1]
    elif bad == "unordered":
        tables = None
    elif bad == "players":
        prefix = replace(saved.prefix.world.prefix, num_players=0)
        saved = replace(
            saved, prefix=replace(saved.prefix, world=replace(saved.prefix.world, prefix=prefix))
        )
    elif bad == "header":
        player = saved.prefix.world.players[0]
        saved = _replace_player(saved, 0, header=replace(player.header, player_id=7))
    elif bad == "header_bool":
        player = saved.prefix.world.players[1]
        saved = _replace_player(saved, 1, header=replace(player.header, player_id=True))
    elif bad == "graphics":
        graphics = None
    else:
        tables[0] = None
    with pytest.raises(ReplayWorldAssemblyError):
        assemble_replay_initial_world(saved, tables, graphics=graphics)


def test_empty_effective_object_lists_preserve_players_and_current_definitions():
    saved, tables, graphics = _prototype()
    saved = _object_world(saved, 0, (), (), ())
    result = assemble_replay_initial_world(saved, tables, graphics=graphics)
    assert not result.objects_by_raw_id
    assert len(result.players) == len(tables)
    assert all(not player.bindings for player in result.players)
    assert all(any(master is not None for master in player.masters) for player in result.players)
    assert result.pending.reference_callbacks and result.pending.spatial_registries
