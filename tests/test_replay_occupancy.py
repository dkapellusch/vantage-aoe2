"""Original constructor/registration corpus, ordered associations and bounded inputs."""

from __future__ import annotations

import gzip
import hashlib
import json
from dataclasses import FrozenInstanceError
from functools import cache
from pathlib import Path

import pytest

from vantage.replay_occupancy import (
    OccupancyRegistry,
    OccupancySnapshot,
    UnsupportedOccupancy,
)

Q = 1 << 22
NONE = 0xFFFFFFFF
RECT = (4 * Q, 4 * Q, 8 * Q, 8 * Q)
FIXTURE = Path(__file__).parent / "fixtures/native_occupancy_registry_7788.json.gz"


@cache
def _fixture():
    return json.loads(gzip.decompress(FIXTURE.read_bytes()))


def _native_view(s: OccupancySnapshot) -> dict:
    return dict(
        free_head=s.free_head,
        counts=[
            len(s.slots),
            s.rectangle_capacity,
            len(s.slots),
            s.edge_group_capacity,
            s.visited_word_count,
            s.visited_word_capacity,
            s.visited_bit_count,
        ],
        slots=[[int(slot.active), *(w & 0xFFFFFFFF for w in slot.words)] for slot in s.slots],
        cells=[[cell.index, cell.capacity, *cell.indices] for cell in s.cells],
        edges=[
            [
                i,
                side,
                capacity,
                *[
                    [
                        e.other_index,
                        e.other_side,
                        *(w & 0xFFFFFFFF for w in e.point),
                        e.axis & 0xFFFFFFFF,
                        e.flag,
                        e.halfspan,
                    ]
                    for e in edges
                ],
            ]
            for i, slot in enumerate(s.slots)
            for side, (edges, capacity) in enumerate(
                zip(slot.edges, slot.edge_capacities, strict=True)
            )
            if capacity
        ],
    )


def _digest(view: dict) -> str:
    return hashlib.sha256(
        json.dumps(view, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def test_all_original_native_registry_snapshots_and_associations() -> None:
    fixture = _fixture()
    assert fixture["rea_evidence_id"] == (
        "ev_636dc5f9b10b86c65e717c49ea9f5b25bdd9677a70fc46f633fd38615610cb60"
    )
    assert fixture["native_exit"]["code"] == 0
    assert fixture["original_instructions_changed"] is False
    assert fixture["executable_holes"] == "INT3"
    assert fixture["corpus_sha256"] == (
        "23dbaded9d9db4e00bf35ff4b86d2777a370e910a2e27fd9d19baa8fa61c0b9f"
    )
    assert len(fixture["functions"]) == 44
    samples = {
        (row["case"], row["native_ordinal"]): row["snapshot"]
        for row in fixture["complete_native_samples"]
    }
    observations = operations = exact_samples = 0
    for ci, case in enumerate(fixture["cases"]):
        registry = OccupancyRegistry(case["stride"])
        handles = {}
        view = _native_view(registry.snapshot())
        assert _digest(view) == case["expected"][0], (ci, -1)
        observations += 1
        for si, operation in enumerate(case["operations"]):
            kind, handle, *words = operation
            rectangle = tuple(words)
            if kind == 0:
                handles[handle] = registry.add(rectangle)
            elif kind == 1:
                registry.remove(handles.pop(handle))
            else:
                handles[handle] = registry.change(handles[handle], rectangle)
            view = _native_view(registry.snapshot())
            assert _digest(view) == case["expected"][si + 1], (ci, si)
            if sample := samples.get((ci, si + 1)):
                assert view == sample, (ci, si)
                exact_samples += 1
            operations += 1
            observations += 1
    assert len(fixture["cases"]) == 684
    assert observations == 7788
    assert operations == 7104
    assert exact_samples > 60


def test_original_signed_map_boundary_corpus_and_sixty_four_slot_growth() -> None:
    path = FIXTURE.with_name("native_occupancy_boundaries_9565.json.gz")
    fixture = json.loads(gzip.decompress(path.read_bytes()))
    assert fixture["original_instructions_changed"] is False
    assert fixture["executable_holes"] == "INT3"
    assert [s["evidence_id"] for s in fixture["native_sources"]] == [
        "ev_6eac58e5d170871b52ed22c53014bed6b13ae4ebc9b7ce5591c6188e1cabf6fb",
        "ev_02ebff1f672b230fe1514605eddb19b3b10577b32df956d0d09c7d3f568811ac",
    ]
    samples = {
        (s["case"], s["native_ordinal"]): s["snapshot"] for s in fixture["complete_native_samples"]
    }
    observations = exact_samples = 0
    for ci, case in enumerate(fixture["cases"]):
        registry, handles = OccupancyRegistry(case["stride"]), {}
        for ordinal, expected in enumerate(case["expected"]):
            if ordinal:
                kind, handle, *words = case["operations"][ordinal - 1]
                if kind == 0:
                    handles[handle] = registry.add(tuple(words))
                elif kind == 1:
                    registry.remove(handles.pop(handle))
                else:
                    handles[handle] = registry.change(handles[handle], tuple(words))
            view = _native_view(registry.snapshot())
            assert _digest(view) == expected, (ci, ordinal)
            if (ci, ordinal) in samples:
                assert view == samples[ci, ordinal], (ci, ordinal)
                exact_samples += 1
            observations += 1
    assert len(fixture["cases"]) == 861 and observations == 9565 and exact_samples == 98


@cache
def _large_fixture():
    raw = FIXTURE.with_name("native_large_occupancy_registry_8192.json.gz").read_bytes()
    assert hashlib.sha256(raw).hexdigest() == (
        "77070bc408357bee847320b49fced591de2ea1946fafb96bb115b394e863a1b6"
    )
    return json.loads(gzip.decompress(raw))


@pytest.mark.parametrize("case_index,operation_count", [(0, 4864), (1, 8410), (2, 8608)])
def test_large_original_native_registry_trace_and_final_snapshot(case_index, operation_count):
    fixture = _large_fixture()
    assert fixture["original_instructions_changed"] is False
    assert fixture["executable_holes"] == "INT3"
    assert len(fixture["functions"]) == 44
    case = fixture["cases"][case_index]
    assert case["input"]["actual_world_chronology_claim"] is False
    registry, handles = OccupancyRegistry(case["stride"]), {}
    assert len(case["native"]) == 1
    observed = case["native"][0]
    trace = observed["operation_trace"]
    assert len(trace) == len(case["operations"]) == operation_count
    for ordinal, (operation, expected) in enumerate(zip(case["operations"], trace, strict=True)):
        kind, handle, *words = operation
        if kind == 0:
            index = handles[handle] = registry.add(tuple(words))
        elif kind == 1:
            index = handles.pop(handle)
            registry.remove(index)
        else:
            index = handles[handle] = registry.change(handles[handle], tuple(words))
        assert [index, len(registry._rectangles), registry._free_head] == expected, ordinal
    view = _native_view(registry.snapshot())
    assert view == {key: observed[key] for key in view}


def test_signed_endpoints_survive_while_cells_clip_at_both_map_edges() -> None:
    r = OccupancyRegistry(16)
    lower = (-Q // 2, -Q // 2, Q // 2, Q // 2)
    upper = (16 * Q - Q // 2, 16 * Q - Q // 2, 16 * Q + Q // 2, 16 * Q + Q // 2)
    assert r.add(lower) == 0 and r.add(upper) == 1
    assert r.registered_rectangle(0) == r.snapshot().slots[0].words == lower
    assert r.registered_rectangle(1) == r.snapshot().slots[1].words == upper
    assert [(c.index, c.indices) for c in r.snapshot().cells] == [(0, (0,)), (255, (1,))]


def test_closed_map_boundary_contact_is_retained_in_the_edge_cell() -> None:
    r = OccupancyRegistry(16)
    rectangle = (-Q, 0, 0, Q)
    r.add(rectangle)
    assert r.registered_rectangle(0) == rectangle
    assert r.cell_indices(0, 0) == r.cell_indices(0, 1) == (0,)
    assert r.cell_indices(1, 0) == ()


def test_empty_registry_is_a_constructor_boundary() -> None:
    r = OccupancyRegistry(144)
    s = r.snapshot()
    assert s.stride == 144 and s.free_head == NONE
    assert s.slots == s.cells == r.active_indices == ()
    assert s.rectangle_capacity == s.edge_group_capacity == s.visited_word_count == 0
    assert s.visited_bit_count == s.visited_word_capacity == 0
    assert r.cell_indices(10, 20) == ()


def test_shared_side_precedence_and_candidate_dedup_match_native() -> None:
    r = OccupancyRegistry(16)
    assert r.add(RECT) == 0
    assert r.add(RECT) == 1
    assert r.edge_associations(0, 0) == r.edge_associations(0, 2) == ()
    assert [
        (e.point, e.other_index, e.other_side, e.flag, e.halfspan)
        for e in r.edge_associations(0, 1)
    ] == [((8 * Q, 4 * Q), 1, 1, 1, 2 * Q), ((8 * Q, 8 * Q), 1, 1, 0, 2 * Q)]
    assert [(e.point, e.flag) for e in r.edge_associations(0, 3)] == [
        ((4 * Q, 4 * Q), 0),
        ((4 * Q, 8 * Q), 1),
    ]
    assert all(r.edge_associations(1, side) == () for side in range(4))
    assert all(r.cell_indices(x, y) == (0, 1) for y in range(4, 9) for x in range(4, 9))


def test_lifo_holes_retain_cell_order_and_capacities() -> None:
    r = OccupancyRegistry(16)
    assert [r.add(RECT) for _ in range(4)] == [0, 1, 2, 3]
    r.remove(0)
    r.remove(2)
    assert r.cell_indices(4, 4) == (1, 3)
    s = r.snapshot()
    assert s.free_head == 2 and s.slots[2].words == (0, 0, 0, 0)
    assert s.slots[0].words == (NONE, 0, 0, 0)
    assert [r.add(RECT), r.add(RECT)] == [2, 0]
    assert r.cell_indices(4, 4) == (1, 3, 2, 0)
    assert r.snapshot().visited_bit_count == 4


def test_last_remove_destroys_one_slot_and_preserves_existing_capacities() -> None:
    r = OccupancyRegistry(16)
    r.add(RECT)
    r.add(RECT)
    r.remove(1)
    s = r.snapshot()
    assert s.free_head == NONE and len(s.slots) == 1
    assert s.rectangle_capacity == s.edge_group_capacity == 2
    assert s.slots[0].edge_capacities == (0, 2, 0, 2)
    assert all(not row for row in s.slots[0].edges)
    assert r.add(RECT) == 1
    assert r.snapshot().visited_bit_count == 3
    assert r.snapshot().visited_word_count == 1


def test_tail_removal_does_not_trim_a_preexisting_free_hole() -> None:
    r = OccupancyRegistry(16)
    r.add(RECT)
    r.add(RECT)
    r.remove(0)
    r.remove(1)
    s = r.snapshot()
    assert len(s.slots) == 1 and s.free_head == 0
    assert not s.slots[0].active
    assert r.add(RECT) == 0
    assert r.snapshot().visited_bit_count == 2


def test_change_compares_raw_words_before_normalization() -> None:
    r = OccupancyRegistry(16)
    odd = (4 * Q + 1, 4 * Q + 1, 8 * Q - 1, 8 * Q - 1)
    r.add(odd)
    r.add(RECT)
    assert r.registered_rectangle(0) == RECT
    assert r.change(0, odd) == 0
    assert r.registered_rectangle(0) == RECT
    assert r.cell_indices(4, 4) == (1, 0)
    before = r.snapshot()
    assert r.change(0, RECT) == 0
    assert r.snapshot() == before


def test_touching_rectangles_share_cells_without_associations() -> None:
    r = OccupancyRegistry(16)
    r.add(RECT)
    r.add((8 * Q, 4 * Q, 9 * Q, 8 * Q))
    assert r.cell_indices(8, 4) == (0, 1)
    assert all(not edges for slot in r.snapshot().slots for edges in slot.edges)


def test_sixty_four_slot_growth_and_reuse() -> None:
    r = OccupancyRegistry(16)
    assert [r.add(RECT) for _ in range(64)] == list(range(64))
    s = r.snapshot()
    assert s.visited_bit_count == 64 and s.visited_word_count == 2
    r.remove(0)
    assert r.add(RECT) == 0
    assert r.snapshot().visited_bit_count == 64


def test_eight_thousand_slot_limit_rejects_atomically_and_allows_reuse() -> None:
    r = OccupancyRegistry(200)
    for i in range(8192):
        x, y = i % 200 * Q, i // 200 * Q
        assert r.add((x, y, x + Q // 4, y + Q // 4)) == i
    before = r.snapshot()
    assert before.visited_bit_count == 8192 and before.visited_word_count == 256
    with pytest.raises(UnsupportedOccupancy):
        r.add(RECT)
    assert r.snapshot() == before
    r.remove(0)
    assert r.add((0, 0, Q // 4, Q // 4)) == 0
    assert r.snapshot().visited_bit_count == 8192


@pytest.mark.parametrize("stride", [0, -1, 201, True, 16.0])
def test_invalid_stride_is_rejected(stride) -> None:
    with pytest.raises(ValueError):
        OccupancyRegistry(stride)


@pytest.mark.parametrize(
    "rectangle",
    [
        (),
        (0, 0, 1),
        [0, 0, 2, 2],
        (0, 0, True, 1),
        (-Q - 1, 0, 2, 2),
        (0, 0, 1 << 31, 2),
        (Q, Q, 0, 2 * Q),
        (Q, Q, Q, 2 * Q),
        (0, 0, 17 * Q + 1, Q),
        (-Q, 0, -2, Q),
        (16 * Q, 0, 17 * Q, Q),
        (0, 0, 1.0, 2),
    ],
)
def test_invalid_rectangle_add_and_change_preserve_state(rectangle) -> None:
    r = OccupancyRegistry(16)
    r.add(RECT)
    before = r.snapshot()
    with pytest.raises(ValueError):
        r.add(rectangle)
    assert r.snapshot() == before
    with pytest.raises(ValueError):
        r.change(0, rectangle)
    assert r.snapshot() == before


@pytest.mark.parametrize("index", [-1, 64, True, 0.0])
def test_invalid_indices_preserve_state(index) -> None:
    r = OccupancyRegistry(16)
    r.add(RECT)
    before = r.snapshot()
    with pytest.raises(ValueError):
        r.remove(index)
    with pytest.raises(ValueError):
        r.change(index, RECT)
    with pytest.raises(ValueError):
        r.registered_rectangle(index)
    assert r.snapshot() == before


def test_free_index_is_not_an_active_geometric_rectangle() -> None:
    r = OccupancyRegistry(16)
    r.add(RECT)
    r.add(RECT)
    r.remove(0)
    assert r.active_indices == (1,)
    with pytest.raises(ValueError):
        r.remove(0)
    with pytest.raises(ValueError):
        r.edge_associations(0, 0)
    with pytest.raises(ValueError):
        r.registered_rectangle(0)


def test_accessors_and_snapshots_do_not_alias_mutable_state() -> None:
    r = OccupancyRegistry(16)
    r.add(RECT)
    before = r.snapshot()
    with pytest.raises(FrozenInstanceError):
        before.stride = 200
    r.add(RECT)
    assert before.slots[0].edges == ((), (), (), ())
    assert before.cells[0].indices == (0,)
    with pytest.raises(ValueError):
        r.edge_associations(0, 4)
    with pytest.raises(ValueError):
        r.cell_indices(True, 0)
    with pytest.raises(ValueError):
        r.cell_indices(16, 0)
