"""Native Q22 rectangle contacts and ordered cell predicates.

Inputs are signed32 integers with22 fractional bits. The helpers preserve
native integer rounding, contact tolerances, side codes and ignore-byte rules.
Callers supply the already selected cell's ordered obstacle indices; these
functions do not build occupancy, search routes, steer or move an object.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

Q22Point = tuple[int, int]
Q22Rectangle = tuple[int, int, int, int]
_Q = 1 << 22


@dataclass(frozen=True, slots=True)
class PathRectangleContact:
    result: int
    fraction: int
    side: int


@dataclass(frozen=True, slots=True)
class PathCellContact:
    result: int
    fraction: int
    obstacle_index: int
    side: int


def _int32(value: int) -> None:
    if not isinstance(value, int) or not -(1 << 31) <= value < (1 << 31):
        raise ValueError("path geometry requires signed32 integer words")


def _coordinates(value: tuple[int, ...], count: int) -> None:
    if not isinstance(value, tuple) or len(value) != count:
        raise ValueError(f"path geometry requires a tuple of {count} signed32 words")
    for component in value:
        _int32(component)


def _s32(value: int) -> int:
    return ((value + (1 << 31)) & 0xFFFFFFFF) - (1 << 31)


def _s64(value: int) -> int:
    return ((value + (1 << 63)) & 0xFFFFFFFFFFFFFFFF) - (1 << 63)


def _divide(numerator: int, denominator: int) -> int:
    # IDIV truncates toward zero. A quotient outside signed64 would trap in
    # the native instruction; reject it rather than inventing a wrapped result.
    quotient = abs(numerator) // abs(denominator)
    if (numerator < 0) != (denominator < 0):
        quotient = -quotient
    if not -(1 << 63) <= quotient < (1 << 63):
        raise OverflowError("native path intersection signed64 division would overflow")
    return quotient


def _edge_contact(
    start: Q22Point, end: Q22Point, edge_start: Q22Point, edge_end: Q22Point, fraction: int
) -> tuple[int, int]:
    """Original141083370, including distinct strict and tolerant contacts."""
    dx, dy = _s32(end[0] - start[0]), _s32(end[1] - start[1])
    ex, ey = _s32(edge_end[0] - edge_start[0]), _s32(edge_end[1] - edge_start[1])
    px, py = _s32(start[0] - edge_start[0]), _s32(start[1] - edge_start[1])
    denominator = _s64(((ey * dx) >> 22) - ((dy * ex) >> 22))
    if denominator == 0:
        return 0, fraction
    t = _divide(_s64((py * ex & -_Q) - (ey * px & -_Q)), denominator)
    u = _divide(_s64((py * dx & -_Q) - (dy * px & -_Q)), denominator)
    if 0x1A3 <= t <= 0x3FFE5D and t < fraction and 0x1A3 <= u <= 0x3FFE5D:
        return 1, _s32(t)
    if -0x1062 <= t <= 0x401062 and t < fraction + 0xA3D7 and -0x1062 <= u <= 0x401062:
        backed_off = max(min(t, fraction) - 0xA3D7, 0)
        return (3 if t == 0 and u in (0, _Q) else 2), _s32(backed_off)
    return 0, fraction


def _rectangle_contact(
    start: Q22Point,
    end: Q22Point,
    rectangle: Q22Rectangle,
    fraction: int,
    side: int,
) -> PathRectangleContact:
    sx, sy = start
    ex, ey = end
    left, bottom, right, top = rectangle
    dx, dy = _s32(ex - sx), _s32(ey - sy)
    result = 0
    # The native edge order is observable when tolerant corner contacts tie.
    edges: list[tuple[int, Q22Point, Q22Point, bool, int, int]] = []
    if dx > 0:
        edges.append(
            (
                3,
                (left, bottom),
                (left, top),
                bottom < sy < top and left < ex and sx <= left,
                left,
                sx,
            )
        )
    if dx < 0:
        edges.append(
            (
                1,
                (right, bottom),
                (right, top),
                bottom < sy < top and ex < right and right <= sx,
                right,
                sx,
            )
        )
    if dy > 0:
        edges.append(
            (
                0,
                (left, bottom),
                (right, bottom),
                left < sx < right and bottom < ey and sy <= bottom,
                bottom,
                sy,
            )
        )
    if dy < 0:
        edges.append(
            (2, (left, top), (right, top), left < sx < right and ey < top and top <= sy, top, sy)
        )
    for edge_side, a, b, axis_inside, boundary, source in edges:
        if dx == 0 or dy == 0:
            hit = 0
            if axis_inside:
                delta = dx if dy == 0 else dy
                candidate = _s32(_divide(_s32(boundary - source) << 22, delta))
                if candidate < fraction:
                    fraction, hit = candidate, 1
        else:
            hit, fraction = _edge_contact(start, end, a, b, fraction)
        if hit:
            result, side = hit, edge_side
    return PathRectangleContact(result, fraction, side)


def intersect_path_rectangle(
    start: Q22Point,
    end: Q22Point,
    rectangle: Q22Rectangle,
    *,
    fraction_limit: int = 0x466666,
    side: int = -1,
) -> PathRectangleContact:
    """Original141083510: preserve raw result0..3, fraction and side0..3.

    An axial segment uses strict interior tests without diagonal tolerances.
    Diagonal near-corner/endpoint contacts can back the fraction off by0xa3d7.
    Result0 preserves the supplied fraction and side; an interior start does
    not automatically produce a contact. Reversed/degenerate bounds retain
    the native comparisons rather than being normalized.
    """
    _coordinates(start, 2)
    _coordinates(end, 2)
    _coordinates(rectangle, 4)
    _int32(fraction_limit)
    _int32(side)
    return _rectangle_contact(start, end, rectangle, fraction_limit, side)


def _validate_cell(
    obstacles: Sequence[Q22Rectangle], cell_indices: Sequence[int], ignore_bytes: Sequence[int]
) -> None:
    if len(obstacles) != len(ignore_bytes):
        raise ValueError("each path obstacle requires one ignore byte")
    for rectangle in obstacles:
        _coordinates(rectangle, 4)
    for value in ignore_bytes:
        if not isinstance(value, int) or not 0 <= value <= 255:
            raise ValueError("path ignore values must be bytes")
    for index in cell_indices:
        if not isinstance(index, int) or not 0 <= index < len(obstacles):
            raise ValueError("path cell contains an invalid obstacle index")


def path_cell_contacts(
    start: Q22Point,
    end: Q22Point,
    obstacles: Sequence[Q22Rectangle],
    cell_indices: Sequence[int],
    ignore_bytes: Sequence[int],
    margin: int,
    *,
    fraction_limit: int = 0x466666,
    obstacle_index: int = -1,
    side: int = -1,
) -> PathCellContact:
    """Original14107a580/14107c2c0 for an already selected cell.

    Ignore byte exactly1 suppresses a contact candidate. Obstacles retain
    their supplied order, including duplicates. Insetting uses signed32 wrap;
    diagonal rectangle result3 is exposed as cell result2, as in the native
    callback. This helper neither selects a cell nor builds terrain rectangles.
    """
    _coordinates(start, 2)
    _coordinates(end, 2)
    for word in (margin, fraction_limit, obstacle_index, side):
        _int32(word)
    _validate_cell(obstacles, cell_indices, ignore_bytes)
    left, right = min(start[0], end[0]), max(start[0], end[0])
    bottom, top = min(start[1], end[1]), max(start[1], end[1])
    if start[0] == end[0]:
        left, right = _s32(left - 1), _s32(right + 1)
    if start[1] == end[1]:
        bottom, top = _s32(bottom - 1), _s32(top + 1)
    result = 0
    fraction = fraction_limit
    for index in cell_indices:
        if ignore_bytes[index] == 1:
            continue
        a, b, c, d = obstacles[index]
        inset = _s32(a + margin), _s32(b + margin), _s32(c - margin), _s32(d - margin)
        if max(left, inset[0]) >= min(right, inset[2]) or max(bottom, inset[1]) >= min(
            top, inset[3]
        ):
            continue
        contact = _rectangle_contact(start, end, inset, fraction, side)
        fraction = contact.fraction
        if contact.result:
            result = 2 if contact.result == 3 else contact.result
            obstacle_index, side = index, contact.side
    return PathCellContact(result, fraction, obstacle_index, side)


def first_containing_path_obstacle(
    point: Q22Point,
    obstacles: Sequence[Q22Rectangle],
    cell_indices: Sequence[int],
    ignore_bytes: Sequence[int],
    margin: int,
) -> int:
    """Original14107d520's selected-cell predicate, returning index or-1.

    This point test ignores every nonzero byte and uses strict interior
    comparisons. Its ignore rule intentionally differs from segment contacts.
    Cell lookup and map bounds are the caller's responsibility.
    """
    _coordinates(point, 2)
    _int32(margin)
    _validate_cell(obstacles, cell_indices, ignore_bytes)
    x, y = point
    for index in cell_indices:
        a, b, c, d = obstacles[index]
        if (
            ignore_bytes[index] == 0
            and _s32(a + margin) < x < _s32(c - margin)
            and _s32(b + margin) < y < _s32(d - margin)
        ):
            return index
    return -1
