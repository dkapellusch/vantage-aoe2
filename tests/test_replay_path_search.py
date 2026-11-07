"""Actual original full-caller first hits and native node-body observations."""

from __future__ import annotations

import gzip
import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest

from vantage.replay_clear_corridor import ClearCorridorContext
from vantage.replay_path_geometry import path_cell_contacts
from vantage.replay_path_search import (
    PathSearchGrid,
    PathSearchNode,
    UnsupportedPathSearch,
    initialize_path_search_first_hit,
    inset_path_search_corner,
    make_flag2_path_search_node,
    snap_path_search_point,
    trace_path_search_segment,
)

Q = 1 << 22
MASK = 0xFFFFFFFF
FIXTURE = Path(__file__).parent / "fixtures/native_path_search_first_hit_54800.json.gz"


@pytest.fixture(scope="module")
def oracle() -> dict:
    blob = FIXTURE.read_bytes()
    assert hashlib.sha256(blob).hexdigest() == (
        "08c19abb1cd477309def86743dbda06a8526f7e3e3e1add03e0d54a07c4fff25"
    )
    fixture = json.loads(gzip.decompress(blob))
    assert fixture["rea_evidence_id"] == (
        "ev_fa65677c95bd17afad144e1c11220dd9926d53d8980e9b308494e20d467fa978"
    )
    assert not fixture["full_search_completed"]
    return fixture


def grid_of(case: dict) -> PathSearchGrid:
    stride = case["input"][9]
    masks = [case["base_mask"]] * stride**2
    for index, value in case["overrides"]:
        masks[index] = value
    occupancy = ClearCorridorContext(
        stride,
        tuple(masks),
        tuple(tuple(r) for r in case["rectangles"]),
        tuple(case["ignored"]),
        case["selector_mask"],
    )
    # The native controlled oracle registers these positive normalized
    # rectangles in this inclusive cell range, preserving insertion order.
    cells: list[list[int]] = [[] for _ in range(stride**2)]
    for i, (left, bottom, right, top) in enumerate(case["rectangles"]):
        for y in range(bottom // Q, top // Q + 1):
            for x in range(left // Q, right // Q + 1):
                cells[y * stride + x].append(i)
    return PathSearchGrid(occupancy, tuple(tuple(indices) for indices in cells))


def node_words(node: PathSearchNode) -> list[int]:
    return [
        node.cost_bits,
        node.priority_bits,
        node.index,
        node.parent_index,
        node.point[0] & MASK,
        node.point[1] & MASK,
        node.obstacle_index,
        node.side,
        node.flag,
    ]


def test_all_original_snap_vertex_and_flag2_append_observations(oracle: dict) -> None:
    assert len(oracle["leaf"]["cases"]) == 10592
    for row, expected in oracle["leaf"]["cases"]:
        point, rectangle = tuple(row[:2]), tuple(row[2:6])
        snapped = snap_path_search_point(point, rectangle, row[6], row[7])
        assert list(snapped) == expected[:2], row
        assert list(inset_path_search_corner(rectangle, row[6], row[7])) == expected[2:4], row
        node = make_flag2_path_search_node(
            row[16],
            row[8] & MASK,
            row[9] & MASK,
            tuple(expected[:2]),
            row[10] & MASK,
            row[6],
            tuple(row[12:14]),
            extents=tuple(row[14:16]),
            heuristic_mode=bool(row[11]),
        )
        assert node_words(node) == expected[4:13], row
        assert node.index + 1 == expected[13]


def test_all_original_caller_ray_and_pending_state_boundaries(oracle: dict) -> None:
    cases = oracle["caller"]["cases"]
    assert len(cases) == 192
    phases = {"strict-hit-pending": 0, "tolerant-hit-pending": 0}
    for case in cases:
        row, original = case["input"], case["native"]
        grid = grid_of(case)
        start, goal = tuple(row[:2]), tuple(row[2:4])
        ray = trace_path_search_segment(grid, start, goal, Q // 2 - row[4])
        if original[0] == 1:
            assert [ray.result, ray.fraction, ray.obstacle_index, ray.side] == (
                [1, *original[3:6]]
            ), row
        else:
            assert [ray.result, ray.fraction, ray.obstacle_index, ray.side] == original[:4], row
        state = initialize_path_search_first_hit(
            grid, start, goal, row[4], heuristic_mode=bool(row[8])
        )
        phases[state.phase] += 1
        assert state.ray == ray
        assert state.path is None
        if original[0] == 1:
            assert list(state.snapped_point) == original[1:3], row
            assert node_words(state.nodes[1]) == original[6:15], row
            assert [len(state.queue_indices), len(state.nodes)] == original[15:17], row
            assert state.queue_indices == (1,)
        else:
            assert state.snapped_point is None
            assert [len(state.queue_indices), len(state.nodes)] == original[4:6], row
        assert state.nodes[0].index == 0 and state.nodes[0].parent_index == MASK
        assert state.nodes[0].point == start and state.nodes[0].flag == 0
    assert phases == {"strict-hit-pending": 126, "tolerant-hit-pending": 66}


def test_repeated_registered_rectangle_visit_changes_native_hit_kind(oracle: dict) -> None:
    case = oracle["caller"]["cases"][24]
    grid, row = grid_of(case), case["input"]
    start, goal = tuple(row[:2]), tuple(row[2:4])
    once = path_cell_contacts(
        start, goal, grid.occupancy.obstacles, (0, 1, 2), grid.occupancy.ignored, Q // 2 - row[4]
    )
    ray = trace_path_search_segment(grid, start, goal, Q // 2 - row[4])
    assert once.result == 1 and once.fraction == 1835008
    assert ray.result == 2 and ray.fraction == 1793065
    hits = [
        (visit.cell_index, visit.contact.result, visit.contact.fraction)
        for visit in ray.visits
        if visit.contact.result
    ]
    assert hits == [(595, 1, 1835008), (627, 2, 1793065)]
    assert ray.fraction == once.fraction - 0xA3D7


def test_zero_contact_preserves_supplied_fraction_and_sentinels() -> None:
    occupancy = ClearCorridorContext(16, (4,) * 256, (), (), 249)
    grid = PathSearchGrid(occupancy, ((),) * 256)
    result = trace_path_search_segment(
        grid, (8 * Q, 8 * Q), (10 * Q, 9 * Q), 0, fraction_limit=123, obstacle_index=-7, side=-9
    )
    assert (result.result, result.fraction, result.obstacle_index, result.side) == (0, 123, -7, -9)
    with pytest.raises(UnsupportedPathSearch, match="clear request"):
        initialize_path_search_first_hit(grid, (8 * Q, 8 * Q), (10 * Q, 9 * Q), Q // 4)


def test_unsupported_terrain_start_relocation_and_clipping_are_explicit(oracle: dict) -> None:
    case = oracle["caller"]["cases"][0]
    grid, row = grid_of(case), case["input"]
    start, goal = tuple(row[:2]), tuple(row[2:4])
    masks = list(grid.occupancy.cell_masks)
    masks[16 * 32 + 16] = 1
    terrain = replace(grid, occupancy=replace(grid.occupancy, cell_masks=tuple(masks)))
    with pytest.raises(UnsupportedPathSearch, match="terrain rectangle insertion"):
        initialize_path_search_first_hit(terrain, start, goal, row[4])
    occupied = replace(grid, occupancy=replace(grid.occupancy, ignored=(0, 0, 0)))
    with pytest.raises(UnsupportedPathSearch, match="start relocation"):
        initialize_path_search_first_hit(occupied, start, goal, row[4])
    with pytest.raises(UnsupportedPathSearch, match="unclipped"):
        initialize_path_search_first_hit(grid, start, (33 * Q, 16 * Q), Q // 4)
    with pytest.raises(UnsupportedPathSearch, match="initial position"):
        initialize_path_search_first_hit(grid, start, start, Q // 4)


def test_unsafe_native_cell_access_and_abs_overflow_are_rejected() -> None:
    grid = PathSearchGrid(ClearCorridorContext(2, (0,) * 4, (), (), 0), ((),) * 4)
    with pytest.raises(ValueError, match="invalid cell"):
        trace_path_search_segment(grid, (-Q, 0), (Q, Q), 0)
    with pytest.raises(ValueError, match="abs overflow"):
        trace_path_search_segment(grid, (0, 0), (-(1 << 31), 0), 0)


@pytest.mark.parametrize("bad", (-1, 1 << 32, 1.5))
def test_node_raw_word_domains(bad: int) -> None:
    with pytest.raises(ValueError, match="u32"):
        make_flag2_path_search_node(0, bad, 0, (Q, Q), 0, 0, (2 * Q, 2 * Q))


def test_grid_shapes_ordered_indices_and_ignore_semantics_are_preserved() -> None:
    occupancy = ClearCorridorContext(1, (0,), ((0, 0, Q, Q),), (0,), 0)
    assert PathSearchGrid(occupancy, ((0, 0),)).cell_indices == ((0, 0),)
    for cells in ((), ((1,),), ((-1,),), ([0],)):
        with pytest.raises(ValueError):
            PathSearchGrid(occupancy, cells)
    with pytest.raises(ValueError, match="byte"):
        snap_path_search_point((0, 0), (0, 0, Q, Q), 256, 0)
    with pytest.raises(ValueError, match="radius"):
        initialize_path_search_first_hit(PathSearchGrid(occupancy, ((0,),)), (0, 0), (Q, Q), -1)
