"""Portable unchanged-instruction oracles for bounded Q22 path geometry."""

from __future__ import annotations

import gzip
import hashlib
import json
from pathlib import Path

import pytest

from vantage.replay_path_geometry import (
    PathCellContact,
    PathRectangleContact,
    first_containing_path_obstacle,
    intersect_path_rectangle,
    path_cell_contacts,
)

FIXTURE = Path(__file__).parent / "fixtures/native_path_contacts_54800.json.gz"
ORACLE = json.loads(gzip.decompress(FIXTURE.read_bytes()))
Q = 1 << 22
BOX = (4 * Q, 4 * Q, 6 * Q, 6 * Q)


def test_oracle_identity_and_scope() -> None:
    assert hashlib.sha256(FIXTURE.read_bytes()).hexdigest() == (
        "3544829f22db8600674a0ab6a0ebc59c14ee84489ba16ce31554fca6a8b37e1c"
    )
    assert ORACLE["target_sha256"] == (
        "69832b9d51145a4bb280da876880198ee0347947098e77098016b9bcbb8d8788"
    )
    assert not ORACLE["original_instructions_changed"]
    assert not ORACLE["game_launched"]
    assert not ORACLE["original_imports_executed"]
    assert not ORACLE["original_heap_allocation_executed"]


@pytest.mark.parametrize("mode", (0, 1, 2), ids=("rectangle", "cell-contacts", "contains"))
def test_matches_original_native_contacts(mode: int) -> None:
    count = 0
    for row, expected in ORACLE["cases"]:
        kind, sx, sy, ex, ey, fraction, margin, raw, indices, ignored = row
        if kind != mode:
            continue
        rectangles = [tuple(value) for value in raw]
        if kind == 0:
            hit = intersect_path_rectangle(
                (sx, sy), (ex, ey), rectangles[0], fraction_limit=fraction
            )
            actual = [hit.result, hit.fraction, -1, hit.side]
        elif kind == 1:
            contact = path_cell_contacts(
                (sx, sy),
                (ex, ey),
                rectangles,
                indices,
                ignored,
                margin,
                fraction_limit=fraction,
            )
            actual = [contact.result, contact.fraction, contact.obstacle_index, contact.side]
        else:
            index = first_containing_path_obstacle((sx, sy), rectangles, indices, ignored, margin)
            actual = [index, fraction, -1, -1]
        assert actual == expected, (row, actual, expected)
        count += 1
    assert count == (32652, 28762, 10208)[mode]


def test_axis_contact_fraction_and_side() -> None:
    assert intersect_path_rectangle((3 * Q, 5 * Q), (7 * Q, 5 * Q), BOX) == (
        PathRectangleContact(1, Q // 4, 3)
    )
    assert intersect_path_rectangle((7 * Q, 5 * Q), (3 * Q, 5 * Q), BOX) == (
        PathRectangleContact(1, Q // 4, 1)
    )


def test_axis_grazing_and_equal_fraction_preserve_supplied_outputs() -> None:
    assert intersect_path_rectangle((3 * Q, 4 * Q), (7 * Q, 4 * Q), BOX, side=91) == (
        PathRectangleContact(0, 0x466666, 91)
    )
    assert intersect_path_rectangle(
        (3 * Q, 5 * Q), (7 * Q, 5 * Q), BOX, fraction_limit=Q // 4, side=91
    ) == PathRectangleContact(0, Q // 4, 91)


@pytest.mark.parametrize(
    ("distance", "expected"),
    [(-0x1063, (0, 0x466666)), (-0x1062, (2, 0)), (0x1A2, (2, 0)), (0x1A3, (1, 0x1A3))],
)
def test_diagonal_tolerance_thresholds(distance: int, expected: tuple[int, int]) -> None:
    hit = intersect_path_rectangle(
        (-distance, 5 * Q - distance), (Q - distance, 6 * Q - distance), (0, 0, Q, 10 * Q)
    )
    assert (hit.result, hit.fraction) == expected


def test_equal_diagonal_fraction_can_back_off() -> None:
    hit = intersect_path_rectangle(
        (-Q // 4, 5 * Q - Q // 4),
        (3 * Q // 4, 6 * Q - Q // 4),
        (0, 0, Q, 10 * Q),
        fraction_limit=Q // 4,
    )
    assert hit == PathRectangleContact(2, Q // 4 - 0xA3D7, 3)


def test_corner_status_and_edge_order_are_preserved() -> None:
    assert intersect_path_rectangle((4 * Q, 4 * Q), (5 * Q, 5 * Q), BOX) == (
        PathRectangleContact(3, 0, 0)
    )
    assert path_cell_contacts((4 * Q, 4 * Q), (5 * Q, 5 * Q), [BOX], [0], [0], 0) == (
        PathCellContact(2, 0, 0, 0)
    )


def test_cell_bounding_box_filters_endpoint_only_contact() -> None:
    assert intersect_path_rectangle((3 * Q, 3 * Q), (4 * Q, 4 * Q), BOX).result == 2
    assert path_cell_contacts((3 * Q, 3 * Q), (4 * Q, 4 * Q), [BOX], [0], [0], 0) == (
        PathCellContact(0, 0x466666, -1, -1)
    )


def test_ordered_duplicate_obstacles_keep_first_axis_contact() -> None:
    start, end = (3 * Q, 5 * Q), (7 * Q, 5 * Q)
    a = path_cell_contacts(start, end, [BOX, BOX], [0, 1], [0, 0], 0)
    b = path_cell_contacts(start, end, [BOX, BOX], [1, 0], [0, 0], 0)
    assert a == PathCellContact(1, Q // 4, 0, 3)
    assert b == PathCellContact(1, Q // 4, 1, 3)


def test_point_and_segment_ignore_bytes_have_distinct_native_rules() -> None:
    assert path_cell_contacts((3 * Q, 5 * Q), (7 * Q, 5 * Q), [BOX], [0], [2], 0).result == 1
    assert first_containing_path_obstacle((5 * Q, 5 * Q), [BOX], [0], [2], 0) == -1
    assert path_cell_contacts((3 * Q, 5 * Q), (7 * Q, 5 * Q), [BOX], [0], [1], 0).result == 0


def test_point_containment_is_strict_and_preserves_cell_order() -> None:
    assert first_containing_path_obstacle((4 * Q, 5 * Q), [BOX], [0], [0], 0) == -1
    assert first_containing_path_obstacle((5 * Q, 5 * Q), [BOX, BOX], [1, 0], [0, 0], 0) == 1
    assert first_containing_path_obstacle((5 * Q, 5 * Q), [BOX], [0], [0], Q) == -1


def test_empty_cell_preserves_caller_state() -> None:
    assert path_cell_contacts((0, 0), (Q, Q), [], [], [], 0, obstacle_index=42, side=17) == (
        PathCellContact(0, 0x466666, 42, 17)
    )
    assert first_containing_path_obstacle((0, 0), [], [], [], 0) == -1


@pytest.mark.parametrize(
    ("obstacles", "indices", "ignored"),
    [([BOX], [-1], [0]), ([BOX], [1], [0]), ([BOX], [0], []), ([BOX], [0], [256])],
)
def test_invalid_cell_data_is_rejected_without_mutation(obstacles, indices, ignored) -> None:
    original = [list(obstacles), list(indices), list(ignored)]
    with pytest.raises(ValueError):
        path_cell_contacts((0, 0), (Q, Q), obstacles, indices, ignored, 0)
    with pytest.raises(ValueError):
        first_containing_path_obstacle((0, 0), obstacles, indices, ignored, 0)
    assert [obstacles, indices, ignored] == original


def test_signed_word_and_tuple_shapes_are_validated() -> None:
    with pytest.raises(ValueError, match="signed32"):
        intersect_path_rectangle((1 << 31, 0), (0, 0), BOX)
    with pytest.raises(ValueError, match="tuple"):
        intersect_path_rectangle([0, 0], (0, 0), BOX)
    with pytest.raises(ValueError, match="signed32"):
        path_cell_contacts((0, 0), (Q, Q), [BOX], [0], [0], 1 << 31)
