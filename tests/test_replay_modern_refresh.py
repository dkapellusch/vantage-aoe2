"""Actual whole native refresh outputs and strict snapshot/preflight admissions."""

from __future__ import annotations

import base64
import gzip
import hashlib
import json
import struct
from dataclasses import replace
from functools import cache
from pathlib import Path

import pytest

from vantage.replay_modern_refresh import (
    UnsupportedModernRefresh,
    import_occupancy_snapshot,
    refresh_action_end,
)
from vantage.replay_occupancy import (
    OccupancyCell,
    OccupancyEdge,
    OccupancyRegistry,
    OccupancySlot,
    OccupancySnapshot,
)

Q, NONE = 1 << 22, 0xFFFFFFFF
FIXTURE = Path(__file__).parent / "fixtures/native_modern_refresh_4.json.gz"
POSITION = (0x431C8000, 0x43008000)
RADII = (0x3E99999A, 0x3E99999A)
RAW = (653053133, 535612621, 659764019, 542323507)


def _s32(value):
    return value if value < 0x80000000 else value - 0x100000000


@cache
def _fixture():
    raw = FIXTURE.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == (
        "236af4cc6ee1bfe3ae59b94a161acefdb5e11ef53ac37243bf63d63f142cad8e"
    )
    return json.loads(gzip.decompress(raw))


@cache
def _decode(digest):
    packet = _fixture()["buffers"][digest]
    raw = base64.b64decode(packet["data"], validate=True)
    assert len(raw) == packet["bytes"] == 1642928
    assert hashlib.sha256(raw).hexdigest() == digest
    offset = 0

    def words(n):
        nonlocal offset
        value = struct.unpack_from(f"<{n}I", raw, offset)
        offset += n * 4
        return value

    header = words(16)
    n, rect_capacity, group_capacity, stride, head, bits, used, capacity = header[:8]
    rectangles = tuple(words(4) for _ in range(n))
    visited = words(used)
    free, index = set(), head
    while index != NONE:
        assert index not in free and index < n
        free.add(index)
        index = rectangles[index][0]
    slots = []
    for index in range(n):
        edges, capacities = [], []
        for _ in range(4):
            count, cap = words(2)
            rows = []
            for _ in range(count):
                a, side, x, y, axis, flag, half = words(7)
                rows.append(
                    OccupancyEdge(a, side, (_s32(x), _s32(y)), _s32(axis), flag, _s32(half))
                )
            edges.append(tuple(rows))
            capacities.append(cap)
        rectangle = rectangles[index]
        if index not in free:
            rectangle = tuple(map(_s32, rectangle))
        slots.append(OccupancySlot(rectangle, index not in free, tuple(edges), tuple(capacities)))
    cells = []
    for index in range(stride**2):
        count, cap = words(2)
        indices = words(count)
        if cap:
            cells.append(OccupancyCell(index, cap, indices))
        else:
            assert not indices
    flag = words(1)[0]
    assert offset == len(raw)
    return (
        OccupancySnapshot(
            stride, tuple(slots), tuple(cells), head, rect_capacity, group_capacity, bits, capacity
        ),
        visited,
        header,
        flag,
    )


def _actual_input():
    case = _fixture()["cases"][0]
    snapshot, visited, header, flag = _decode(case["input_before_sha256"])
    assert tuple(header[12:14]) == POSITION and tuple(header[14:16]) == RADII
    return snapshot, visited, header, flag


def _actual_registry():
    snapshot, visited, _, _ = _actual_input()
    return import_occupancy_snapshot(snapshot, visited_words=visited)


def test_fixture_contains_actual_outputs_and_exact_closure_controls():
    source = _fixture()
    assert source["evidence_id"] == (
        "ev_271c171b1ea1a0d0ca5bc4822ad7ed46a774ffdd16bad7c7b91e378812682b4c"
    )
    assert source["original_instruction_changes"] is False
    assert source["native_game_launched"] is False
    assert source["actual_output_bytes_verified"] == 6571712
    assert len(source["cases"]) == 4 and len(source["buffers"]) == 2
    for case in source["cases"]:
        _decode(case["actual_output_sha256"])
    assert [
        (c["exit"], c["metadata"]["signal"], c["metadata"]["pc_rva"], c["metadata"]["ra_rva"])
        for c in source["controls"]
    ] == [
        (101, 11, 0x1120E80, 0),
        (102, 11, 0x10B8830, 0x11210F2),
        (103, 11, 0x2000000, 0x10B85FE),
    ]


@pytest.mark.parametrize("entry", [0, 1, 2])
def test_full_actual_native_refresh_output_including_all_ordered_vectors(entry):
    before, visited, header, flag = _actual_input()
    registry = import_occupancy_snapshot(before, visited_words=visited)
    assert registry.snapshot() == before
    assert before.visited_bit_count == 4332 > len(before.slots) == 4199
    result = refresh_action_end(
        registry,
        native_index=header[8],
        modern_gate=True,
        mode=0,
        legacy_flag3=flag,
        position_xy_bits=POSITION,
        effective_radius_xy_bits=RADII,
    )
    case = _fixture()["cases"][entry]
    expected, expected_visited, _, expected_flag = _decode(case["actual_output_sha256"])
    assert registry.snapshot() == expected
    assert visited == expected_visited == (0,) * 136
    assert result.native_index == 4168 and result.legacy_flag3 == expected_flag == 1
    assert result.raw_rectangle == RAW and result.enabled and result.registry_changed
    assert case["metadata"]["copy_calls"] == 11
    assert expected.free_head == before.free_head == 328
    changed = [
        (a.index, a.indices, b.indices)
        for a, b in zip(before.cells, expected.cells, strict=True)
        if a.indices != b.indices
    ]
    assert [row[0] for row in changed] == [25555, 25556, 25755, 25756, 25955, 25956]
    assert all(old[0] == new[-1] == 4168 and old[1:] == new[:-1] for _, old, new in changed)


def test_native_case3_is_direct_equal_raw_change_not_a_new_quantizer_context():
    before, visited, _, _ = _actual_input()
    registry = import_occupancy_snapshot(before, visited_words=visited)
    index = registry.change(4168, before.slots[4168].words)
    case = _fixture()["cases"][3]
    expected, _, _, _ = _decode(case["actual_output_sha256"])
    assert index == 4168 and registry.snapshot() == expected == before
    assert case["metadata"]["copy_calls"] == 0


def _small():
    registry = OccupancyRegistry(20)
    registry.add((4 * Q, 4 * Q, 8 * Q, 8 * Q))
    registry.add((6 * Q, 5 * Q, 9 * Q, 9 * Q))
    registry.add((12 * Q, 12 * Q, 13 * Q, 13 * Q))
    return registry


def _replace_edge(snapshot, transform):
    slots = list(snapshot.slots)
    for owner, slot in enumerate(slots):
        for side, rows in enumerate(slot.edges):
            if rows:
                vectors = list(slot.edges)
                vectors[side] = (transform(rows[0]), *rows[1:])
                slots[owner] = replace(slot, edges=tuple(vectors))
                return replace(snapshot, slots=tuple(slots))
    raise AssertionError("small fixture requires an edge")


@pytest.mark.parametrize(
    "field,value",
    [
        ("other_index", 2),
        ("other_index", 999),
        ("other_side", 4),
        ("other_side", 1),
        ("point", (0, 0)),
        ("axis", 123),
        ("halfspan", 1),
        ("flag", 2),
        ("flag", True),
    ],
)
def test_import_rejects_dangling_nonoverlapping_or_geometrically_impossible_edge(field, value):
    snapshot = _small().snapshot()
    bad = _replace_edge(snapshot, lambda edge: replace(edge, **{field: value}))
    with pytest.raises(ValueError):
        import_occupancy_snapshot(bad, visited_words=(0,))


def test_import_rejects_missing_contour_even_when_all_cross_references_are_in_range():
    snapshot = _small().snapshot()
    bad = _replace_edge(snapshot, lambda edge: replace(edge, flag=1 - edge.flag))
    with pytest.raises(ValueError, match="contours"):
        import_occupancy_snapshot(bad, visited_words=(0,))
    slots = list(snapshot.slots)
    for owner, slot in enumerate(slots):
        for side, rows in enumerate(slot.edges):
            if rows:
                vectors = list(slot.edges)
                vectors[side] = rows[1:]
                slots[owner] = replace(slot, edges=tuple(vectors))
                with pytest.raises(ValueError, match="contours"):
                    import_occupancy_snapshot(
                        replace(snapshot, slots=tuple(slots)), visited_words=(0,)
                    )
                return


def test_import_rejects_an_incoming_subject_edge_owned_outside_its_scanned_cells():
    snapshot = _small().snapshot()
    distant = snapshot.slots[2]
    edge = OccupancyEdge(0, 0, (4 * Q, 4 * Q), 4 * Q, 1, Q)
    distant = replace(distant, edges=((edge,), (), (), ()), edge_capacities=(1, 0, 0, 0))
    bad = replace(snapshot, slots=(*snapshot.slots[:2], distant))
    with pytest.raises(ValueError, match="sharing cells"):
        import_occupancy_snapshot(bad, visited_words=(0,))


@pytest.mark.parametrize("kind", ["missing", "extra", "duplicate", "reordered_headers"])
def test_import_rejects_incorrect_complete_cell_membership(kind):
    snapshot = _small().snapshot()
    cells = list(snapshot.cells)
    cell = cells[0]
    if kind == "missing":
        cells.pop(0)
    elif kind == "extra":
        cells[0] = replace(cell, indices=(2,), capacity=max(1, cell.capacity))
    elif kind == "duplicate":
        cells[0] = replace(cell, indices=cell.indices * 2, capacity=2 * len(cell.indices))
    else:
        cells[:2] = reversed(cells[:2])
    with pytest.raises(ValueError):
        import_occupancy_snapshot(replace(snapshot, cells=tuple(cells)), visited_words=(0,))


@pytest.mark.parametrize(
    "kind",
    [
        "cycle",
        "missing_hole",
        "active_head",
        "free_words",
        "free_edges",
    ],
)
def test_import_rejects_invalid_free_chain_and_payload(kind):
    registry = _small()
    registry.remove(0)
    snapshot = registry.snapshot()
    free = snapshot.slots[0]
    if kind == "cycle":
        free = replace(free, words=(0, 0, 0, 0))
    elif kind == "missing_hole":
        snapshot = replace(snapshot, free_head=NONE)
    elif kind == "active_head":
        snapshot = replace(snapshot, free_head=1)
    elif kind == "free_words":
        free = replace(free, words=(NONE, 1, 0, 0))
    else:
        edge = OccupancyEdge(1, 0, (6 * Q, 5 * Q), 6 * Q, 0, Q)
        free = replace(free, edges=((edge,), (), (), ()), edge_capacities=(1, 0, 0, 0))
    snapshot = replace(snapshot, slots=(free, *snapshot.slots[1:]))
    with pytest.raises(ValueError):
        import_occupancy_snapshot(snapshot, visited_words=(0,))


@pytest.mark.parametrize(
    "change,visited",
    [
        ({}, ()),
        ({}, (1,)),
        ({"visited_word_capacity": 0}, (0,)),
        ({"visited_bit_count": 2}, (0,)),
        ({"rectangle_capacity": 2}, (0,)),
        ({"rectangle_capacity": 1 << 30}, (0,)),
        ({"visited_bit_count": True}, (0,)),
    ],
)
def test_import_requires_real_visited_extent_widths_and_capacity_budget(change, visited):
    with pytest.raises(ValueError):
        import_occupancy_snapshot(replace(_small().snapshot(), **change), visited_words=visited)


def test_import_supports_empty_state_and_preserves_historical_visited_words_after_tail_pop():
    empty = OccupancyRegistry(20).snapshot()
    assert import_occupancy_snapshot(empty, visited_words=()).snapshot() == empty
    registry = _small()
    registry.remove(2)
    state = registry.snapshot()
    assert state.visited_bit_count == 3 > len(state.slots) == 2
    assert import_occupancy_snapshot(state, visited_words=(0,)).snapshot() == state


def test_import_rejects_excessive_pair_work_before_constructing_dense_contours():
    slot = OccupancySlot((4 * Q, 4 * Q, 4 * Q + 2, 4 * Q + 2), True, ((), (), (), ()), (0, 0, 0, 0))
    state = OccupancySnapshot(
        20,
        (slot,) * 8192,
        (OccupancyCell(84, 8192, tuple(range(8192))),),
        NONE,
        8192,
        8192,
        8192,
        256,
    )
    with pytest.raises(UnsupportedModernRefresh, match="pair budget"):
        import_occupancy_snapshot(state, visited_words=(0,) * 256)


@pytest.mark.parametrize("mode", [0, 0x10])
@pytest.mark.parametrize("gate", [False, True])
def test_source_null_record_branch_skips_both_registry_and_flag_store(mode, gate):
    registry = _small()
    before = registry.snapshot()
    result = refresh_action_end(
        registry, native_index=NONE, modern_gate=gate, mode=mode, legacy_flag3=None
    )
    assert result.native_index == NONE and result.legacy_flag3 is None
    assert result.raw_rectangle is None and not result.registry_changed
    assert registry.snapshot() == before


@pytest.mark.parametrize("mode,flag,expected", [(0, 0xF5, 5), (16, 0xF5, 21), (0, 0, 0)])
def test_source_false_gate_still_returns_later_legacy_flag_store(mode, flag, expected):
    registry = _small()
    before = registry.snapshot()
    result = refresh_action_end(
        registry, native_index=NONE, modern_gate=False, mode=mode, legacy_flag3=flag
    )
    assert result.legacy_flag3 == expected and result.native_index == NONE
    assert result.enabled == (mode != 16) and not result.registry_changed
    assert registry.snapshot() == before


@pytest.mark.parametrize(
    "change",
    [
        {"mode": 16},
        {"mode": 2},
        {"native_index": NONE},
        {"native_index": 4198},
        {"native_index": True},
        {"legacy_flag3": 256},
        {"modern_gate": 1},
        {"position_xy_bits": None},
        {"effective_radius_xy_bits": None},
        {"position_xy_bits": (0x7F7FFFFF, POSITION[1])},
        {"position_xy_bits": (0x7F800000, POSITION[1])},
        {"position_xy_bits": (0x7FC12345, POSITION[1])},
        {"effective_radius_xy_bits": (0x80000001, RADII[1])},
        {"position_xy_bits": (0x431C8001, POSITION[1])},
    ],
)
def test_refresh_rejects_unsupported_context_before_mutation(change):
    registry = _actual_registry()
    before = registry.snapshot()
    arguments = dict(
        native_index=4168,
        modern_gate=True,
        mode=0,
        legacy_flag3=1,
        position_xy_bits=POSITION,
        effective_radius_xy_bits=RADII,
    )
    arguments.update(change)
    with pytest.raises(ValueError):
        refresh_action_end(registry, **arguments)
    assert registry.snapshot() == before


def test_capacity_preflight_rejects_new_edge_ownership_without_partial_mutation():
    # Both identical rectangles originally give their shared contours to the
    # first inserted slot. Reinserting it transfers ownership to the second,
    # whose retained edge capacities are zero, despite identical final bounds.
    rectangle = (19713228, 19713228, 26424116, 26424116)
    registry = OccupancyRegistry(20)
    registry.add(rectangle)
    registry.add(rectangle)
    registry.add((12 * Q, 12 * Q, 13 * Q, 13 * Q))
    before = registry.snapshot()
    imported = import_occupancy_snapshot(before, visited_words=(0,))
    with pytest.raises(UnsupportedModernRefresh, match="grow an edge"):
        refresh_action_end(
            imported,
            native_index=0,
            modern_gate=True,
            mode=0,
            legacy_flag3=0xF1,
            position_xy_bits=(0x40B00000,) * 2,
            effective_radius_xy_bits=RADII,
        )
    assert imported.snapshot() == before


def test_preflight_rejects_more_than128_distinct_candidates_without_mutation():
    registry = OccupancyRegistry(20)
    rectangle = (19713228, 19713228, 26424116, 26424116)
    for _ in range(129):
        registry.add(rectangle)
    registry.add((12 * Q, 12 * Q, 13 * Q, 13 * Q))
    before = registry.snapshot()
    with pytest.raises(UnsupportedModernRefresh, match="scratch candidates"):
        refresh_action_end(
            registry,
            native_index=0,
            modern_gate=True,
            mode=0,
            legacy_flag3=1,
            position_xy_bits=(0x40B00000,) * 2,
            effective_radius_xy_bits=RADII,
        )
    assert registry.snapshot() == before


def test_raw_equality_through_quantizer_skips_reinsert_and_capacity_failure():
    # This source-derived arithmetic context is distinct from native case3's
    # direct raw rectangle input. Radius1.0 and center5.5 produce all-even raw.
    registry = OccupancyRegistry(20)
    rectangle = (4 * Q, 4 * Q, 7 * Q, 7 * Q)
    registry.add(rectangle)
    registry.add(rectangle)
    registry.add((12 * Q, 12 * Q, 13 * Q, 13 * Q))
    before = registry.snapshot()
    result = refresh_action_end(
        registry,
        native_index=0,
        modern_gate=True,
        mode=0,
        legacy_flag3=0xF1,
        position_xy_bits=(0x40B00000,) * 2,
        effective_radius_xy_bits=(0x3F800000,) * 2,
    )
    assert result.raw_rectangle == rectangle and not result.registry_changed
    assert result.legacy_flag3 == 1 and registry.snapshot() == before
