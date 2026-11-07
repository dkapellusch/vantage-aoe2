"""Fresh typed registry, complete actual snapshot and original numerical expectations."""

from __future__ import annotations

import gzip
import hashlib
import json
import struct
from dataclasses import fields, is_dataclass, replace
from functools import cache
from pathlib import Path
from types import UnionType
from typing import Any, Literal, Union, get_args, get_origin, get_type_hints

import pytest

from vantage.replay_binary import SaveReader
from vantage.replay_game_data import read_game_data_graphics, read_game_data_master
from vantage.replay_initial_occupancy import (
    ReplayInitialOccupancyError,
    _plan,
    _registration_rectangles,
    build_replay_initial_modern_occupancy,
)
from vantage.replay_initial_player import SavedInitialPlayer
from vantage.replay_masters import SavedMasterTable, read_master
from vantage.replay_object_lists import (
    SavedObjectList,
    SavedPlayerObjectLists,
    SavedPlayerObjectTrailer,
)
from vantage.replay_object_order import restore_runtime_object_lists
from vantage.replay_objects import read_saved_object
from vantage.replay_occupancy import OccupancyRegistry
from vantage.replay_players import read_player_header
from vantage.replay_saved_world import SavedReplayWorld
from vantage.replay_world_assembly import assemble_replay_initial_world

FIXTURE = Path(__file__).parent / "fixtures/native_initial_occupancy_54800.json.gz"
NONE = 0xFFFFFFFF


@cache
def _fixture():
    raw = FIXTURE.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == (
        "339d8c76baff48738f4adfd507e54fff445e0374c6a7c8cea596ff8adcc2756a"
    )
    return json.loads(gzip.decompress(raw))


def _empty(kind):
    """Typed unrelated-world/unused-slot scaffolding, not serialized native bytes."""
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
    return None if kind is Any else kind()


def _lists(*groups):
    wire = tuple(SavedObjectList(0, 0, 0, 0, tuple(group), 0, b"") for group in groups)
    return SavedPlayerObjectLists(
        0, 0, *wire, SavedPlayerObjectTrailer(0, 0, 0, (), 0, 0, 0, 0, 0, 0, 0, b""), b""
    )


@cache
def _assembly():
    fixture = _fixture()
    players, selected = [], []
    for row in fixture["players"]:
        reader = SaveReader(bytes.fromhex(row["header_hex"]))
        header = read_player_header(reader, len(fixture["players"]), player_id=row["owner"])
        assert reader.remaining == 0
        masters, baseline = {}, {}
        for entry in row["masters"]:
            reader = SaveReader(bytes.fromhex(entry["saved_hex"]))
            masters[entry["index"]] = read_master(
                reader, master_id=entry["index"], type_group=entry["type_group"]
            )
            assert reader.remaining == 0
        for key, value in row["baselines"].items():
            reader = SaveReader(bytes.fromhex(value), version=0x43E666)
            baseline[int(key)] = read_game_data_master(reader)
            assert reader.remaining == 0
        groups = {name: [] for name in ("ordinary", "sleeping", "dopple")}
        for entry in row["objects"]:
            reader = SaveReader(bytes.fromhex(entry["raw_hex"]))
            obj = read_saved_object(reader)
            assert reader.remaining == 0 and obj.object_id == entry["raw_id"]
            groups[entry["wire_list"]].append(obj)
        table = SavedMasterTable(
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
                masters=table,
                object_lists=_lists(*(groups[name] for name in groups)),
            )
        )
        selected.append(baseline)
    saved = _empty(SavedReplayWorld)
    width, height = fixture["map_dimensions"]
    world = replace(
        saved.prefix.world,
        players=tuple(players),
        prefix=replace(saved.prefix.world.prefix, num_players=len(players)),
        map=replace(saved.prefix.world.map, width=width, height=height),
    )
    saved = replace(saved, prefix=replace(saved.prefix, world=world))
    reader = SaveReader(bytes.fromhex(fixture["graphics_hex"]), version=0x43E666)
    graphics = read_game_data_graphics(reader).graphics
    assert reader.remaining == 0
    return assemble_replay_initial_world(saved, selected, graphics=graphics)


def _view(registry):
    snapshot = registry.snapshot()
    cells = {cell.index: cell for cell in snapshot.cells}
    chain, index = [], snapshot.free_head
    while index != NONE:
        chain.append(index)
        index = snapshot.slots[index].words[0]
    return dict(
        stride=snapshot.stride,
        rectangles=[list(slot.words) for slot in snapshot.slots],
        edge_groups=[
            [
                dict(
                    capacity=slot.edge_capacities[side],
                    edges=[
                        [
                            edge.other_index,
                            edge.other_side,
                            *edge.point,
                            edge.axis,
                            edge.flag,
                            edge.halfspan,
                        ]
                        for edge in slot.edges[side]
                    ],
                )
                for side in range(4)
            ]
            for slot in snapshot.slots
        ],
        cells=[
            dict(capacity=cells[i].capacity, indices=list(cells[i].indices))
            if i in cells
            else dict(capacity=0, indices=[])
            for i in range(snapshot.stride**2)
        ],
        rectangle_capacity=snapshot.rectangle_capacity,
        group_capacity=snapshot.edge_group_capacity,
        free_head=snapshot.free_head,
        free_chain=chain,
        visited_bits=snapshot.visited_bit_count,
        visited_capacity=snapshot.visited_word_capacity,
        visited_words=[0] * snapshot.visited_word_count,
    )


def _source_state(assembly):
    return (
        id(assembly.saved),
        id(assembly.pending),
        tuple(
            (
                id(player),
                id(player.saved),
                id(player.selected_baseline),
                tuple(
                    (
                        id(binding.saved),
                        binding.saved.position,
                        binding.saved.flags,
                        tuple(sorted(binding.saved.fields.items())),
                    )
                    for binding in player.bindings
                ),
                tuple(
                    (id(master), tuple(sorted(master.common.fields.items())))
                    for master in player.masters
                    if master is not None
                ),
            )
            for player in assembly.players
        ),
        tuple((key, id(value)) for key, value in assembly.objects_by_raw_id.items()),
    )


def test_complete_actual6p_registry_and_all_memberships_from_real_typed_assembler():
    assembly = _assembly()
    before = _source_state(assembly)
    result = build_replay_initial_modern_occupancy(
        assembly, modern_gate=True, before_regular_updates=True
    )
    fixture = _fixture()
    assert fixture["actual_evidence"] == (
        "ev_d41f23cda8d9a02dc11cdbd50691a09b1b3d07229185378e19c3f4e504e9d460"
    )
    assert _view(result.registry) == fixture["actual_modern"]
    expected = {row["id"]: row["index194"] for row in fixture["actual_memberships"]}
    assert len(expected) == len(result.indices_by_raw_id) == 12264
    assert dict(result.indices_by_raw_id) == expected and 0 in expected
    assert len(result.registry.snapshot().slots) == 4205
    assert result.registry.snapshot().visited_bit_count == 4332
    assert result.source is assembly and result.conditional_saved_input_recipe is True
    assert assembly.pending.reference_callbacks is True
    assert (
        assembly.pending.lifecycle_updates is True and assembly.pending.spatial_registries is True
    )
    assert _source_state(assembly) == before
    for owner, player in enumerate(assembly.players):
        actual = {row["id"]: row for row in fixture["actual_memberships"] if row["player"] == owner}
        for which, name in enumerate(("ordinary", "sleeping", "dopple")):
            for ordinal, obj in enumerate(getattr(player.objects, name)):
                assert (
                    actual[obj.object_id]["list"],
                    actual[obj.object_id]["ordinal"],
                    actual[obj.object_id]["family"],
                ) == (which, ordinal, obj.type_group)
    with pytest.raises(TypeError):
        result.indices_by_raw_id[10449] = 999


def test_all13274_original_native_geometry_expectations_in_original_f32_order():
    source = _fixture()
    assert source["geometry_evidence"] == (
        "ev_1815072448da0455184822e6bf47e34bc1889a61ed1bdf991a5e1126ae72c6f8"
    )
    checked = fractional_counterexamples = 0
    for row in source["geometry"]:
        if row["initial"] is None:
            assert row["refresh"] is None
            continue
        _, _, _, kind, _, x, y, _, rx, ry, _, _, _ = row["input"]
        assert kind in (2, 5)
        first, second = _registration_rectangles((x, y), (rx, ry), 200)
        assert list(first) == row["initial"] and list(second) == row["refresh"]
        checked += 2
        xy = [struct.unpack("<f", struct.pack("<I", word))[0] for word in (x, y)]
        integers = tuple(struct.unpack("<I", struct.pack("<f", float(int(v))))[0] for v in xy)
        if all(v >= 1 for v in xy):
            fractional_counterexamples += _registration_rectangles(integers, (rx, ry), 200) != (
                first,
                second,
            )
    assert len(source["geometry"]) == 19257 and checked == 13274
    assert fractional_counterexamples > 6000


def test_add_final_only_control_loses_seven_capacities_and_historical_visited_bits():
    final_only = OccupancyRegistry(200)
    for player in _assembly().players:
        for binding in player.bindings:
            if geometry := _plan(binding, 200):
                final_only.add(geometry[1])
    actual, candidate = _fixture()["actual_modern"], _view(final_only)
    assert candidate["rectangles"] == actual["rectangles"]
    assert candidate["cells"] == actual["cells"]
    differences = [
        (a, b)
        for aa, bb in zip(candidate["edge_groups"], actual["edge_groups"], strict=True)
        for a, b in zip(aa, bb, strict=True)
        if a != b
    ]
    assert len(differences) == 7
    assert all(a["edges"] == b["edges"] and a["capacity"] != b["capacity"] for a, b in differences)
    assert candidate["visited_bits"] == 4205 and actual["visited_bits"] == 4332
    assert candidate["visited_words"] != actual["visited_words"]


@cache
def _one():
    """A small typed component context from actual PIG records; no native-world claim."""
    source = _assembly()
    pig = source.objects_by_raw_id[10449]
    players, saved_players = [], []
    for owner, player in enumerate(source.players):
        wire = _lists((pig.saved,) if owner == 1 else (), (), ())
        saved = replace(player.saved, object_lists=wire)
        saved_players.append(saved)
        players.append(
            replace(
                player,
                saved=saved,
                objects=restore_runtime_object_lists(wire),
                bindings=(pig,) if owner == 1 else (),
            )
        )
    world = replace(source.saved.prefix.world, players=tuple(saved_players))
    saved = replace(source.saved, prefix=replace(source.saved.prefix, world=world))
    return replace(source, saved=saved, players=tuple(players), objects_by_raw_id={10449: pig})


def _changed_object(change=None, master_changes=None):
    source = _one()
    player = source.players[1]
    old = player.bindings[0]
    obj = old.saved if change is None else change(old.saved)
    master = old.master
    if master_changes is not None:
        common = replace(master.common, fields={**master.common.fields, **master_changes})
        master = replace(master, common=common)
    binding = replace(old, saved=obj, master=master)
    wire = _lists((obj,), (), ())
    saved_player = replace(player.saved, object_lists=wire)
    masters = list(player.masters)
    masters[obj.master_id] = master
    player = replace(
        player,
        saved=saved_player,
        masters=tuple(masters),
        objects=restore_runtime_object_lists(wire),
        bindings=(binding,),
    )
    players = (*source.players[:1], player, *source.players[2:])
    saved_players = (
        *source.saved.prefix.world.players[:1],
        saved_player,
        *source.saved.prefix.world.players[2:],
    )
    world = replace(source.saved.prefix.world, players=saved_players)
    saved = replace(source.saved, prefix=replace(source.saved.prefix, world=world))
    return replace(source, saved=saved, players=players, objects_by_raw_id={obj.object_id: binding})


@pytest.mark.parametrize(
    "argument,value,code",
    [
        ("modern_gate", False, "modern_gate"),
        ("modern_gate", 1, "modern_gate"),
        ("before_regular_updates", False, "phase"),
        ("before_regular_updates", 1, "phase"),
    ],
)
def test_explicit_phase_and_actual_gate_are_required(argument, value, code):
    source = _one()
    before = _source_state(source)
    kwargs = dict(modern_gate=True, before_regular_updates=True)
    kwargs[argument] = value
    with pytest.raises(ReplayInitialOccupancyError) as exc:
        build_replay_initial_modern_occupancy(source, **kwargs)
    assert exc.value.code == code and _source_state(source) == before


@pytest.mark.parametrize("width,height", [(0, 0), (201, 201), (20, 21), (True, 1)])
def test_unsupported_saved_map_does_not_publish_or_mutate(width, height):
    source = _one()
    world = source.saved.prefix.world
    world = replace(world, map=replace(world.map, width=width, height=height))
    source = replace(
        source, saved=replace(source.saved, prefix=replace(source.saved.prefix, world=world))
    )
    before = _source_state(source)
    with pytest.raises(ReplayInitialOccupancyError, match="map"):
        build_replay_initial_modern_occupancy(source, modern_gate=True, before_regular_updates=True)
    assert _source_state(source) == before


@pytest.mark.parametrize(
    "change",
    [
        lambda o: replace(o, reference_id=0),
        lambda o: replace(o, movement=replace(o.movement, endpoint_flag=1)),
        lambda o: replace(o, movement=replace(o.movement, paths_wire_order=(bytes(45),))),
        lambda o: replace(o, movement=replace(o.movement, secondary_path_flag=1)),
        lambda o: replace(o, movement=replace(o.movement, secondary_path_flag=False)),
        lambda o: replace(o, movement=replace(o.movement, waypoints=(bytes(8),))),
        lambda o: replace(o, action=replace(o.action, raw=o.action.raw[:-2] + b"\1\0")),
        lambda o: replace(o, fields={**o.fields, 0x1C6: 256}),
        lambda o: replace(o, position=(float("nan"), *o.position[1:])),
        lambda o: replace(o, position=(1.1, *o.position[1:])),
        lambda o: replace(o, position=(1e30, *o.position[1:])),
    ],
)
def test_unsupported_object_context_has_ids_and_preserves_assembly(change):
    source = _changed_object(change)
    before = _source_state(source)
    with pytest.raises(ReplayInitialOccupancyError) as exc:
        build_replay_initial_modern_occupancy(source, modern_gate=True, before_regular_updates=True)
    assert exc.value.code == "object"
    assert (exc.value.player_index, exc.value.object_id, exc.value.master_index) == (1, 10449, 1245)
    assert _source_state(source) == before


@pytest.mark.parametrize(
    "changes",
    [
        {0xF1: 1},
        {0xF1: 11},
        {0xF1: 256},
        {0xF2: True},
        {0x78: 0x7F800000},
        {0x80: 0x7F800000},
        {0x7C: 0xBF800000},
    ],
)
def test_unsupported_current_master_values_have_context_and_do_not_mutate(changes):
    source = _changed_object(master_changes=changes)
    before = _source_state(source)
    with pytest.raises(ReplayInitialOccupancyError) as exc:
        build_replay_initial_modern_occupancy(source, modern_gate=True, before_regular_updates=True)
    assert exc.value.player_index == 1 and exc.value.object_id == 10449
    assert exc.value.master_index == 1245 and _source_state(source) == before


@pytest.mark.parametrize(
    "changes", [{0xF1: 0}, {0xF1: 12}, {0xF2: 0}, {0x80: 0}, {0x80: 0x7FC12345}]
)
def test_native_rejected_current_master_admissions_keep_raw_id_with_sentinel(changes):
    source = _changed_object(master_changes=changes)
    result = build_replay_initial_modern_occupancy(
        source, modern_gate=True, before_regular_updates=True
    )
    assert dict(result.indices_by_raw_id) == {10449: NONE} and not result.registry.snapshot().slots


@pytest.mark.parametrize(
    "change",
    [
        lambda o: replace(o, flags=(7, *o.flags[1:])),
        lambda o: replace(o, fields={**o.fields, 0x1C6: 1}),
    ],
)
def test_native_rejected_object_admissions_keep_raw_id(change):
    result = build_replay_initial_modern_occupancy(
        _changed_object(change), modern_gate=True, before_regular_updates=True
    )
    assert dict(result.indices_by_raw_id) == {10449: NONE}


def test_zero_raw_id_is_valid_and_never_replaced_with_spectator_alias():
    source = _changed_object(lambda o: replace(o, object_id=0))
    result = build_replay_initial_modern_occupancy(
        source, modern_gate=True, before_regular_updates=True
    )
    assert dict(result.indices_by_raw_id) == {0: 0}


def test_missing_current_member_has_context_without_filling_from_baseline():
    source = _changed_object(master_changes={})
    source.players[1].bindings[0].master.common.fields.pop(0x128)
    before = _source_state(source)
    with pytest.raises(ReplayInitialOccupancyError, match="missing restored") as exc:
        build_replay_initial_modern_occupancy(source, modern_gate=True, before_regular_updates=True)
    assert exc.value.object_id == 10449 and exc.value.master_index == 1245
    assert _source_state(source) == before


def _many(ids):
    source = _one()
    player = source.players[1]
    binding = player.bindings[0]
    objects = tuple(replace(binding.saved, object_id=raw_id) for raw_id in ids)
    wire = _lists(objects, (), ())
    runtime = restore_runtime_object_lists(wire)
    bindings = tuple(replace(binding, saved=obj) for obj in runtime.update_order)
    saved_player = replace(player.saved, object_lists=wire)
    player = replace(player, saved=saved_player, objects=runtime, bindings=bindings)
    players = (*source.players[:1], player, *source.players[2:])
    world = replace(source.saved.prefix.world, players=tuple(p.saved for p in players))
    saved = replace(source.saved, prefix=replace(source.saved.prefix, world=world))
    return replace(
        source,
        saved=saved,
        players=players,
        objects_by_raw_id={b.saved.object_id: b for b in bindings},
    )


def test_native_signed_id_order_is_preserved_in_fresh_index_assignment():
    source = _many((0, NONE, 0x80000000))
    result = build_replay_initial_modern_occupancy(
        source, modern_gate=True, before_regular_updates=True
    )
    assert dict(result.indices_by_raw_id) == {0x80000000: 0, NONE: 1, 0: 2}


def test_slot_limit_rejects_before_any_registry_mutation_and_preserves_inputs(monkeypatch):
    source = _many(range(8193))
    before = _source_state(source)

    def unexpected_add(*args):
        raise AssertionError("registry construction occurred before complete profile validation")

    monkeypatch.setattr(OccupancyRegistry, "add", unexpected_add)
    with pytest.raises(ReplayInitialOccupancyError) as exc:
        build_replay_initial_modern_occupancy(source, modern_gate=True, before_regular_updates=True)
    assert exc.value.code == "slots" and exc.value.object_id == 8192
    assert _source_state(source) == before


def test_empty_action_behavior_does_not_require_the_independent_object_map_to_be_empty():
    source = _changed_object(
        lambda o: replace(o, action=replace(o.action, object_map=((123, 456),)))
    )
    result = build_replay_initial_modern_occupancy(
        source, modern_gate=True, before_regular_updates=True
    )
    assert dict(result.indices_by_raw_id) == {10449: 0}


@pytest.mark.parametrize(
    "kind", ["binding_object", "current_master", "extra_id", "order", "player"]
)
def test_exact_identity_joins_are_required(kind):
    source = _one()
    player = source.players[1]
    binding = player.bindings[0]
    if kind == "binding_object":
        binding = replace(binding, saved=replace(binding.saved))
    elif kind == "current_master":
        binding = replace(binding, master=replace(binding.master))
    elif kind == "extra_id":
        source = replace(source, objects_by_raw_id={10449: binding, 99: binding})
    elif kind == "order":
        player = replace(
            player, objects=replace(player.objects, ordinary=(), sleeping=(binding.saved,))
        )
    else:
        player = replace(player, saved=replace(player.saved))
    if kind in ("binding_object", "current_master"):
        player = replace(player, bindings=(binding,))
        source = replace(source, objects_by_raw_id={10449: binding})
    source = replace(source, players=(*source.players[:1], player, *source.players[2:]))
    before = _source_state(source)
    with pytest.raises(ReplayInitialOccupancyError):
        build_replay_initial_modern_occupancy(source, modern_gate=True, before_regular_updates=True)
    assert _source_state(source) == before


def test_malformed_binding_is_rejected_with_object_context_before_member_access():
    source = _one()
    player = replace(source.players[1], bindings=(None,))
    source = replace(source, players=(*source.players[:1], player, *source.players[2:]))
    before = source.players
    with pytest.raises(ReplayInitialOccupancyError, match="typed object binding") as exc:
        build_replay_initial_modern_occupancy(source, modern_gate=True, before_regular_updates=True)
    assert exc.value.player_index == 1 and exc.value.object_id == 10449
    assert exc.value.master_index == 1245 and source.players is before
    assert source.players[1].bindings == (None,)
