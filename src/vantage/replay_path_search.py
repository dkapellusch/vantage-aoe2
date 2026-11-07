"""Modern path search through the first blocked ray and pending node append.

Inputs are an explicitly initialized ordered cell grid. Native Q22 rounding,
shared callback fraction, contact side and defined48-byte node fields are
preserved. Contour expansion, terrain insertion and final routes are unported.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .replay_clear_corridor import ClearCorridorContext
from .replay_clear_path import _distance_squared, _heuristic, _outcode, _point, _s32
from .replay_path_geometry import (
    PathCellContact,
    Q22Point,
    Q22Rectangle,
    first_containing_path_obstacle,
    intersect_path_rectangle,
    path_cell_contacts,
)

_Q = 1 << 22


class UnsupportedPathSearch(ValueError):
    """The supplied request requires a search branch not yet reconstructed."""


def _word(value: int) -> None:
    if not isinstance(value, int) or not 0 <= value <= 0xFFFFFFFF:
        raise ValueError("path node fields require u32 words")


def _signed(value: int) -> None:
    if not isinstance(value, int) or not -(1 << 31) <= value < 1 << 31:
        raise ValueError("path geometry requires signed32 words")


def _byte(value: int) -> None:
    if not isinstance(value, int) or not 0 <= value <= 255:
        raise ValueError("path side requires a byte")


def _cell(word: int) -> int:
    return (word + (_Q - 1 if word < 0 else 0)) >> 22


@dataclass(frozen=True, slots=True)
class PathSearchGrid:
    occupancy: ClearCorridorContext
    cell_indices: tuple[tuple[int, ...], ...]

    def __post_init__(self) -> None:
        if not isinstance(self.occupancy, ClearCorridorContext):
            raise ValueError("path search requires explicit initialized occupancy")
        if (
            not isinstance(self.cell_indices, tuple)
            or len(self.cell_indices) != self.occupancy.stride**2
        ):
            raise ValueError("path search requires one ordered tuple per cell")
        for indices in self.cell_indices:
            if not isinstance(indices, tuple):
                raise ValueError("path cell indices must be immutable tuples")
            if any(
                not isinstance(i, int) or not 0 <= i < len(self.occupancy.obstacles)
                for i in indices
            ):
                raise ValueError("path cell contains an invalid obstacle index")


@dataclass(frozen=True, slots=True)
class PathSearchCellVisit:
    cell_index: int
    contact: PathCellContact


@dataclass(frozen=True, slots=True)
class PathSearchRay:
    result: int
    fraction: int
    obstacle_index: int
    side: int
    visits: tuple[PathSearchCellVisit, ...]


@dataclass(frozen=True, slots=True)
class PathSearchNode:
    cost_bits: int
    priority_bits: int
    index: int
    parent_index: int
    point: Q22Point
    obstacle_index: int
    side: int
    flag: int


@dataclass(frozen=True, slots=True)
class FirstHitSearchState:
    phase: Literal["strict-hit-pending", "tolerant-hit-pending"]
    ray: PathSearchRay
    nodes: tuple[PathSearchNode, ...]
    queue_indices: tuple[int, ...]
    snapped_point: Q22Point | None
    path: None = None


def trace_path_search_segment(
    grid: PathSearchGrid,
    start: Q22Point,
    end: Q22Point,
    margin: int,
    *,
    fraction_limit: int = 0x466666,
    obstacle_index: int = -1,
    side: int = -1,
) -> PathSearchRay:
    """Original141083a70 composition with ordered cell callbacks.

    A hit limits remaining cell visits; it does not immediately stop traversal.
    Repeated rectangle visits can change strict result1 to tolerant result2.
    The shared fraction, last nonzero result, index and side retain that order.
    """
    if not isinstance(grid, PathSearchGrid):
        raise ValueError("an explicit ordered path grid is required")
    for point in (start, end):
        _point(point)
    for value in (margin, fraction_limit, obstacle_index, side):
        _signed(value)
    stride = grid.occupancy.stride
    sx, sy = start
    dx, dy = _s32(end[0] - sx), _s32(end[1] - sy)
    if dx == -(1 << 31) or dy == -(1 << 31):
        raise ValueError("native signed abs overflow is unsupported")
    ax, ay = abs(dx), abs(dy)
    x, y = _cell(sx), _cell(sy)
    step_x, step_y = (dx > 0) - (dx < 0), (dy > 0) - (dy < 0)
    remaining = abs(_cell(end[0]) - x) + abs(_cell(end[1]) - y) + 1
    distance_x = (x + 1) * _Q - sx if dx > 0 else sx - x * _Q
    distance_y = (y + 1) * _Q - sy if dy > 0 else sy - y * _Q
    error = (distance_x * ay) >> 22 if dx else 0x7FC00000
    error = _s32(error - (distance_y * ax >> 22)) if dy else -(1 << 31)
    result, fraction = 0, fraction_limit
    visits = []
    while remaining > 0:
        index = (y * stride + x) & 0xFFFFFFFF
        if index >= stride**2:
            raise ValueError("native path traversal would dereference an invalid cell")
        contact = path_cell_contacts(
            start,
            end,
            grid.occupancy.obstacles,
            grid.cell_indices[index],
            grid.occupancy.ignored,
            margin,
            fraction_limit=fraction,
            obstacle_index=obstacle_index,
            side=side,
        )
        fraction, obstacle_index, side = contact.fraction, contact.obstacle_index, contact.side
        visits.append(PathSearchCellVisit(index, contact))
        if contact.result:
            hit_x = _cell(_s32(sx + (dx * fraction >> 22)))
            hit_y = _cell(_s32(sy + (dy * fraction >> 22)))
            remaining = min(remaining, abs(hit_x - x) + abs(hit_y - y) + 1)
            result = contact.result
        remaining -= 1
        if error <= 0:
            x += step_x
            error = _s32(error + ay)
        else:
            y += step_y
            error = _s32(error - ax)
    return PathSearchRay(result, fraction, obstacle_index, side, tuple(visits))


def snap_path_search_point(
    point: Q22Point, rectangle: Q22Rectangle, side: int, margin: int
) -> Q22Point:
    """Original14107d190 including reversed inset bounds and invalid side no-op."""
    _point(point)
    if not isinstance(rectangle, tuple) or len(rectangle) != 4:
        raise ValueError("path rectangle requires four signed32 words")
    _point(rectangle[:2])
    _point(rectangle[2:])
    _byte(side)
    _signed(margin)
    x, y = point
    left, bottom, right, top = rectangle
    lo_x, lo_y = _s32(left + margin), _s32(bottom + margin)
    hi_x, hi_y = _s32(right - margin), _s32(top - margin)

    def clamp(value: int, lo: int, hi: int) -> int:
        return lo if value < lo else min(value, hi)

    if side == 0:
        return clamp(x, lo_x, hi_x), lo_y
    if side == 1:
        return hi_x, clamp(y, lo_y, hi_y)
    if side == 2:
        return clamp(x, lo_x, hi_x), hi_y
    if side == 3:
        return lo_x, clamp(y, lo_y, hi_y)
    return point


def inset_path_search_corner(rectangle: Q22Rectangle, corner: int, margin: int) -> Q22Point:
    """Original141081770/14096bac0; unsupported corner values return raw corner0."""
    if not isinstance(rectangle, tuple) or len(rectangle) != 4:
        raise ValueError("path rectangle requires four signed32 words")
    _point(rectangle[:2])
    _point(rectangle[2:])
    _signed(corner)
    _signed(margin)
    left, bottom, right, top = rectangle
    if corner == 0:
        return _s32(left + margin), _s32(bottom + margin)
    if corner == 1:
        return _s32(right - margin), _s32(bottom + margin)
    if corner == 2:
        return _s32(right - margin), _s32(top - margin)
    if corner == 3:
        return _s32(left + margin), _s32(top - margin)
    return left, bottom


def make_flag2_path_search_node(
    index: int,
    cost_bits: int,
    parent_index: int,
    point: Q22Point,
    obstacle_index: int,
    side: int,
    goal: Q22Point,
    *,
    extents: Q22Point = (0, 0),
    heuristic_mode: bool = False,
) -> PathSearchNode:
    """Defined fields of14107d730's48-byte append; native stack padding omitted."""
    for word in (index, cost_bits, parent_index, obstacle_index):
        _word(word)
    _byte(side)
    for position in (point, goal, extents):
        _point(position)
    if min(extents) < 0 or not isinstance(heuristic_mode, bool):
        raise ValueError("node extents must be nonnegative and heuristic mode Boolean")
    priority = (_s32(cost_bits) + _heuristic(point, goal, extents, heuristic_mode)) & 0xFFFFFFFF
    return PathSearchNode(cost_bits, priority, index, parent_index, point, obstacle_index, side, 2)


def initialize_path_search_first_hit(
    grid: PathSearchGrid,
    start: Q22Point,
    goal: Q22Point,
    radius: int,
    *,
    heuristic_mode: bool = False,
) -> FirstHitSearchState:
    """Initialize a pending fresh blocked request with zero target extents/range.

    Supports an unclipped modern request with no terrain insertion or start
    relocation. Strict hits stop after original node/queue append; tolerant
    hits stop before dispatch. A secondary containing obstacle needs an
    unported resnap loop. This function returns no completed path or AL status.
    """
    if not isinstance(grid, PathSearchGrid):
        raise ValueError("an explicit ordered path grid is required")
    for point in (start, goal):
        _point(point)
    if not isinstance(radius, int) or not 0 <= radius <= _Q // 2:
        raise ValueError("modern first-hit radius must be in0..0.5 Q22 tiles")
    if not isinstance(heuristic_mode, bool):
        raise ValueError("heuristic mode must be Boolean")
    context = grid.occupancy
    maximum = _s32(context.stride * _Q - radius - 1)
    bounds = (
        max(radius, _s32(min(start[0], goal[0]) - 4 * _Q)),
        max(radius, _s32(min(start[1], goal[1]) - 4 * _Q)),
        min(maximum, _s32(max(start[0], goal[0]) + 4 * _Q)),
        min(maximum, _s32(max(start[1], goal[1]) + 4 * _Q)),
    )
    if _outcode(start, bounds) or _outcode(goal, bounds):
        raise UnsupportedPathSearch("first-hit initialization requires unclipped in-bounds points")
    mask = context.selector_mask & ((1 << 64) - 1)
    for y in range(bounds[1] // _Q, bounds[3] // _Q + 1):
        for x in range(bounds[0] // _Q, bounds[2] // _Q + 1):
            if context.cell_masks[y * context.stride + x] & mask:
                raise UnsupportedPathSearch("terrain rectangle insertion is not ported")
    margin = _Q // 2 - radius
    cell = _cell(start[1]) * context.stride + _cell(start[0])
    if (
        first_containing_path_obstacle(
            start, context.obstacles, grid.cell_indices[cell], context.ignored, margin
        )
        != -1
    ):
        raise UnsupportedPathSearch("start relocation is not ported")
    initial = _heuristic(start, goal, (0, 0), heuristic_mode)
    if _distance_squared(start, goal, (0, 0)) == 0 or initial < 0:
        raise UnsupportedPathSearch("request accepts the initial position before a blocked ray")
    target = (goal[0] + margin, goal[1] + margin, goal[0] - margin, goal[1] - margin)
    contact = intersect_path_rectangle(start, goal, target)
    if contact.result:
        endpoint = (
            _s32(start[0] + (_s32(goal[0] - start[0]) * contact.fraction >> 22)),
            _s32(start[1] + (_s32(goal[1] - start[1]) * contact.fraction >> 22)),
        )
        if endpoint != goal:
            raise UnsupportedPathSearch("target endpoint adjustment is outside first-hit profile")
    node0 = PathSearchNode(0, initial & 0xFFFFFFFF, 0, 0xFFFFFFFF, start, 0xFFFFFFFF, 0, 0)
    ray = trace_path_search_segment(grid, start, goal, margin)
    if ray.result == 0:
        raise UnsupportedPathSearch("clear request does not need first-hit search initialization")
    if ray.result == 2:
        return FirstHitSearchState("tolerant-hit-pending", ray, (node0,), (), None)
    if ray.result != 1 or not 0 <= ray.obstacle_index < len(context.obstacles):
        raise UnsupportedPathSearch("unverified first-ray result")
    point = (
        _s32(start[0] + (_s32(goal[0] - start[0]) * ray.fraction >> 22)),
        _s32(start[1] + (_s32(goal[1] - start[1]) * ray.fraction >> 22)),
    )
    snapped = snap_path_search_point(point, context.obstacles[ray.obstacle_index], ray.side, margin)
    cell = _cell(snapped[1]) * context.stride + _cell(snapped[0])
    if not 0 <= cell < context.stride**2:
        raise UnsupportedPathSearch("adjusted point needs an invalid native cell")
    if (
        first_containing_path_obstacle(
            snapped, context.obstacles, grid.cell_indices[cell], context.ignored, margin
        )
        != -1
    ):
        raise UnsupportedPathSearch("secondary containing obstacle needs the unported resnap loop")
    cost = _heuristic(start, snapped, (0, 0), False) & 0xFFFFFFFF
    node1 = make_flag2_path_search_node(
        1, cost, 0, snapped, ray.obstacle_index, ray.side, goal, heuristic_mode=heuristic_mode
    )
    return FirstHitSearchState("strict-hit-pending", ray, (node0, node1), (1,), snapped)
