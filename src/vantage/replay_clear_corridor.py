"""Direct modern clear routes in explicitly supplied populated occupancy.

This bounds14107eaa0 to requests whose working-window terrain requires no
inserted rectangles and whose start/segment clear all nonignored obstacles.
It preserves the original raw statuses, binary32 points and metadata. It does
not restore an occupancy heap, search blocked routes, steer or advance time.
"""

from __future__ import annotations

from dataclasses import dataclass

from .replay_clear_path import (
    ClearPathResult,
    EmptyPathContext,
    _clip_window,
    _distance_squared,
    _heuristic,
    _outcode,
    _point,
    _range_endpoint,
    _s32,
    find_empty_replay_path,
)
from .replay_path_geometry import (
    Q22Point,
    Q22Rectangle,
    first_containing_path_obstacle,
    intersect_path_rectangle,
    path_cell_contacts,
)

_Q = 1 << 22


class UnsupportedClearCorridor(ValueError):
    """A request needs an unported native construction/search branch."""


@dataclass(frozen=True, slots=True)
class ClearCorridorContext:
    stride: int
    cell_masks: tuple[int, ...]
    obstacles: tuple[Q22Rectangle, ...]
    ignored: tuple[int, ...]
    selector_mask: int

    def __post_init__(self) -> None:
        if not isinstance(self.stride, int) or not 1 <= self.stride <= 512:
            raise ValueError("context stride must be between1 and512")
        if not isinstance(self.cell_masks, tuple) or len(self.cell_masks) != self.stride**2:
            raise ValueError("context requires one u64 mask per cell")
        if any(not isinstance(word, int) or not 0 <= word < 1 << 64 for word in self.cell_masks):
            raise ValueError("context masks must be u64 words")
        if not isinstance(self.obstacles, tuple) or not isinstance(self.ignored, tuple):
            raise ValueError("context obstacle and ignored arrays must be immutable tuples")
        if len(self.obstacles) != len(self.ignored):
            raise ValueError("each obstacle requires one ignored byte")
        for rect in self.obstacles:
            if not isinstance(rect, tuple) or len(rect) != 4:
                raise ValueError("each obstacle requires four signed32 words")
            _point(rect[:2])
            _point(rect[2:])
            if rect[0] > rect[2] or rect[1] > rect[3]:
                raise ValueError("context requires ordered registered rectangle bounds")
        if any(not isinstance(word, int) or word not in (0, 1) for word in self.ignored):
            raise ValueError("bounded clear contexts require ignored bytes0 or1")
        if (
            not isinstance(self.selector_mask, int)
            or not -(1 << 31) <= self.selector_mask < 1 << 31
        ):
            raise ValueError("query mask must be a signed32 word")


def find_clear_corridor_path(
    context: ClearCorridorContext,
    start: Q22Point,
    goal: Q22Point,
    radius: int,
    *,
    target_extents: Q22Point = (0, 0),
    range_q22: int = 0,
    heuristic_mode: bool = False,
    length_bits: int = 0,
    clock_bits: int = 0,
) -> ClearPathResult:
    """Return the verified direct branch; reject unsupported obstacle searches.

    The caller supplies an initialized terrain mask array and the registered
    obstacle rectangles with query-specific ignored bytes. This does not infer
    those runtime values from saved entities. Every working-window tile must
    avoid the signed query mask; selected terrain elsewhere may remain present.
    All nonignored registered rectangles must clear the start and exact native
    segment. This conservative whole-vector test can reject a context that
    native cell-index filtering would accept. No partial path is synthesized.
    """
    if not isinstance(context, ClearCorridorContext):
        raise ValueError("an explicit populated path context is required")
    empty = EmptyPathContext(context.stride, (0,) * context.stride**2)
    result = find_empty_replay_path(
        empty,
        start,
        goal,
        radius,
        target_extents=target_extents,
        range_q22=range_q22,
        heuristic_mode=heuristic_mode,
        length_bits=length_bits,
        clock_bits=clock_bits,
    )
    maximum = _s32(context.stride * _Q - radius - 1)
    bounds = (
        max(radius, _s32(min(start[0], goal[0]) - 4 * _Q)),
        max(radius, _s32(min(start[1], goal[1]) - 4 * _Q)),
        min(maximum, _s32(max(start[0], goal[0]) + 4 * _Q)),
        min(maximum, _s32(max(start[1], goal[1]) + 4 * _Q)),
    )
    if _outcode(start, bounds):
        return result
    clipped = _clip_window(start, goal, bounds)
    if clipped is None:
        return result
    selected = context.selector_mask & ((1 << 64) - 1)
    for y in range(bounds[1] // _Q, bounds[3] // _Q + 1):
        for x in range(bounds[0] // _Q, bounds[2] // _Q + 1):
            if context.cell_masks[y * context.stride + x] & selected:
                raise UnsupportedClearCorridor("terrain rectangle insertion/search is not ported")
    indices = tuple(range(len(context.obstacles)))
    margin = _Q // 2 - radius
    if (
        first_containing_path_obstacle(start, context.obstacles, indices, context.ignored, margin)
        != -1
    ):
        raise UnsupportedClearCorridor("start relocation from an obstacle is not ported")
    expanded = tuple(radius + extent if extent else 0 for extent in target_extents)
    extents: Q22Point = expanded[0], expanded[1]
    if _distance_squared(start, clipped, extents) <= (range_q22 * range_q22 >> 22):
        return result
    if _heuristic(start, clipped, extents, heuristic_mode) < range_q22:
        return result
    rectangle = (
        _s32(clipped[0] - extents[0] + margin),
        _s32(clipped[1] - extents[1] + margin),
        _s32(clipped[0] + extents[0] - margin),
        _s32(clipped[1] + extents[1] - margin),
    )
    contact = intersect_path_rectangle(start, clipped, rectangle)
    endpoint = clipped
    if contact.result:
        endpoint = (
            _s32(start[0] + (_s32(clipped[0] - start[0]) * contact.fraction >> 22)),
            _s32(start[1] + (_s32(clipped[1] - start[1]) * contact.fraction >> 22)),
        )
    endpoint = _range_endpoint(start, endpoint, range_q22)
    if path_cell_contacts(
        start, endpoint, context.obstacles, indices, context.ignored, margin
    ).result:
        raise UnsupportedClearCorridor("obstructed route search is not ported")
    return result
