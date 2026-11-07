"""Whole native blocked requests, including all defined intermediate search state."""

from __future__ import annotations

import gzip
import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from vantage.replay_clear_corridor import ClearCorridorContext
from vantage.replay_isolated_path import (
    IsolatedPathNode,
    IsolatedPathRuntime,
    UnsupportedIsolatedPath,
    find_isolated_replay_path,
)
from vantage.replay_path_search import PathSearchGrid

Q = 1 << 22
FIXTURE = Path(__file__).parent / "fixtures/native_isolated_paths_54800.json.gz"


def cases() -> list[dict[str, Any]]:
    return json.loads(gzip.decompress(FIXTURE.read_bytes()))["cases"]  # type: ignore[no-any-return]


def grid_for(case: dict[str, Any]) -> PathSearchGrid:
    stride = case["input"][9]
    rectangles = tuple(tuple(rect) for rect in case["rectangles"])
    masks = [case["base_mask"]] * stride**2
    for index, word in case["overrides"]:
        masks[index] = word
    cells = tuple(
        tuple(
            i
            for i, (left, bottom, right, top) in enumerate(rectangles)
            if left // Q <= x <= right // Q and bottom // Q <= y <= top // Q
        )
        for y in range(stride)
        for x in range(stride)
    )
    return PathSearchGrid(
        ClearCorridorContext(
            stride, tuple(masks), rectangles, tuple(case["ignored"]), case["selector_mask"]
        ),
        cells,
    )


def runtime_for(grid: PathSearchGrid) -> IsolatedPathRuntime:
    return IsolatedPathRuntime(-Q, 2000, ((b"", b"", b"", b""),) * len(grid.occupancy.obstacles))


def node_words(node: IsolatedPathNode) -> list[int | None]:
    words: list[int | None] = [
        node.cost_bits,
        node.priority_bits,
        node.index,
        node.parent_index,
        *node.point,
        node.flag,
    ]
    if node.flag == 2:
        words += [node.obstacle_index, node.side]
    if node.flag == 3:
        words += [
            node.direction,
            node.left_index,
            node.right_index,
            node.contour_index,
            node.previous_side,
            node.current_side,
        ]
    return words


def test_all_original_full_requests_and_intermediate_state() -> None:
    evidence = json.loads(gzip.decompress(FIXTURE.read_bytes()))
    assert evidence["rea_evidence_id"] == (
        "ev_6af4ceff617125b6a16e931b88cfeabc8827fecf127334b1f616451be16e7deb"
    )
    assert len(evidence["functions"]) == 73
    assert evidence["executable_holes"].startswith("0xcc INT3")
    assert evidence["original_instructions_changed"] is False
    assert evidence["full_request_completed"] is True
    assert len(evidence["cases"]) == 192
    for index, case in enumerate(evidence["cases"]):
        row = case["input"]
        grid = grid_for(case)
        before = hash(grid)
        result = find_isolated_replay_path(
            grid,
            (row[0], row[1]),
            (row[2], row[3]),
            row[4],
            runtime=runtime_for(grid),
            heuristic_mode=bool(row[8]),
            length_bits=0xA5A5A5A5,
            clock_bits=0xA5A5A5A5,
        )
        assert hash(grid) == before
        native = case["native"]
        assert result.status == native[0] == 1, index
        assert len(result.points) == native[1], index
        assert (result.length_bits, result.clock_bits) == tuple(native[2:4]), index
        assert len(result.queue_indices) == native[4] == 0, index
        assert len(result.nodes) == native[5], index
        assert len(result.reconstruction) == native[6], index
        assert len(result.contours) == native[7] == 1, index
        assert [word for point in result.points for word in point] == native[10:], index
        assert [len(result.nodes)] + [
            word for node in result.nodes for word in node_words(node)
        ] == case["state"]["nodes"], index
        contours = [len(result.contours)]
        for contour in result.contours:
            contours += [len(contour.points), int(contour.closed)]
            for point, side, obstacle, cost in zip(
                contour.points,
                contour.sides,
                contour.obstacle_indices,
                contour.cost_bits,
                strict=True,
            ):
                contours += [*point, side, obstacle, cost]
        assert contours == case["state"]["contours"], index


def test_fallback_and_queued_corner_remain_separate_nodes() -> None:
    grid = grid_for(cases()[0])
    result = find_isolated_replay_path(
        grid,
        (16 * Q + Q // 2,) * 2,
        (24 * Q + Q // 2, 16 * Q + Q // 2),
        0,
        runtime=runtime_for(grid),
    )
    a, b = result.nodes[2:4]
    assert (a.cost_bits, a.priority_bits, a.point, a.parent_index) == (
        b.cost_bits,
        b.priority_bits,
        b.point,
        b.parent_index,
    )
    assert (a.previous_side, a.current_side) == (0, 0)
    assert (b.previous_side, b.current_side) == (0, 1)
    assert result.nodes[-1].parent_index == b.index


@pytest.mark.parametrize("field,value", [("cost_sentinel", 0), ("contour_budget", 3)])
def test_unknown_initialized_runtime_profile_fails(field: str, value: int) -> None:
    grid = grid_for(cases()[0])
    with pytest.raises(UnsupportedIsolatedPath, match="globals"):
        find_isolated_replay_path(
            grid,
            (16 * Q,) * 2,
            (24 * Q, 16 * Q),
            0,
            runtime=replace(runtime_for(grid), **{field: value}),
        )


def test_associated_edges_are_explicitly_unsupported() -> None:
    grid = grid_for(cases()[0])
    runtime = runtime_for(grid)
    edges = list(runtime.obstacle_edges)
    edges[1] = (bytes(28), b"", b"", b"")
    with pytest.raises(UnsupportedIsolatedPath, match="associated"):
        find_isolated_replay_path(
            grid,
            (16 * Q,) * 2,
            (24 * Q, 16 * Q),
            0,
            runtime=replace(runtime, obstacle_edges=tuple(edges)),
        )


@pytest.mark.parametrize("touch", [False, True])
def test_overlapping_or_touching_rectangles_are_unsupported(touch: bool) -> None:
    case = cases()[0]
    case["rectangles"][2] = [21 * Q + (Q // 2 if touch else 0), 15 * Q, 23 * Q, 17 * Q]
    grid = grid_for(case)
    with pytest.raises(UnsupportedIsolatedPath, match="overlapping"):
        find_isolated_replay_path(
            grid, (16 * Q,) * 2, (24 * Q, 16 * Q), 0, runtime=runtime_for(grid)
        )


def test_selected_terrain_in_working_window_is_unsupported() -> None:
    case = cases()[0]
    case["overrides"].append([16 * 32 + 20, 1])
    grid = grid_for(case)
    with pytest.raises(UnsupportedIsolatedPath, match="terrain"):
        find_isolated_replay_path(
            grid, (16 * Q,) * 2, (24 * Q, 16 * Q), 0, runtime=runtime_for(grid)
        )


def test_second_separated_blocker_is_unsupported_without_partial_result() -> None:
    case = cases()[0]
    case["rectangles"].append([22 * Q, 14 * Q, 24 * Q, 16 * Q + Q // 2])
    case["ignored"].append(0)
    grid = grid_for(case)
    before = hash(grid)
    with pytest.raises(UnsupportedIsolatedPath, match="second obstacle"):
        find_isolated_replay_path(
            grid,
            (16 * Q + Q // 2,) * 2,
            (24 * Q + Q // 2, 16 * Q + Q // 2),
            0,
            runtime=runtime_for(grid),
        )
    assert hash(grid) == before


def test_goal_inside_rectangle_is_unsupported() -> None:
    grid = grid_for(cases()[0])
    with pytest.raises(UnsupportedIsolatedPath, match="goal"):
        find_isolated_replay_path(
            grid, (16 * Q,) * 2, (20 * Q + Q // 2, 16 * Q), 0, runtime=runtime_for(grid)
        )


def test_unverified_working_window_contour_is_unsupported() -> None:
    case = cases()[0]
    case["rectangles"][1][1] = 4 * Q
    grid = grid_for(case)
    with pytest.raises(UnsupportedIsolatedPath, match="working-window"):
        find_isolated_replay_path(
            grid,
            (16 * Q + Q // 2,) * 2,
            (24 * Q + Q // 2, 16 * Q + Q // 2),
            0,
            runtime=runtime_for(grid),
        )


@pytest.mark.parametrize("value", [-1, 1 << 32])
def test_metadata_word_bounds(value: int) -> None:
    grid = grid_for(cases()[0])
    with pytest.raises(ValueError, match="metadata"):
        find_isolated_replay_path(
            grid, (16 * Q,) * 2, (24 * Q, 16 * Q), 0, runtime=runtime_for(grid), clock_bits=value
        )
