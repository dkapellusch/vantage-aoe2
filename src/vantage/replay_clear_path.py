"""Original modern path requests in explicitly empty occupancy.

This implements14107eaa0's empty-map branch for a fresh, empty output path.
It preserves Q22 clipping/range arithmetic, AL statuses and raw output points.
It does not construct occupancy, select a backend, search blocked terrain,
update an existing controller or finalize path length/timestamps.
"""

from __future__ import annotations

import math
import struct
from dataclasses import dataclass

from .replay_movement_geometry import Float32Vector
from .replay_path_geometry import Q22Point, Q22Rectangle, intersect_path_rectangle

_Q = 1 << 22


@dataclass(frozen=True, slots=True)
class EmptyPathContext:
    stride: int
    cell_masks: tuple[int, ...]
    obstacles: tuple[Q22Rectangle, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.stride, int) or not 1 <= self.stride <= 512:
            raise ValueError("empty path context stride must be between1 and512")
        if not isinstance(self.cell_masks, tuple) or len(self.cell_masks) != self.stride**2:
            raise ValueError("empty path context requires one qword mask per cell")
        if not isinstance(self.obstacles, tuple):
            raise ValueError("empty path obstacles must be an immutable tuple")
        if self.obstacles or any(self.cell_masks):
            raise ValueError("clear path requests require empty occupancy and zero cell masks")
        if any(not isinstance(mask, int) for mask in self.cell_masks):
            raise ValueError("path cell masks must be integer words")


@dataclass(frozen=True, slots=True)
class ClearPathResult:
    status: int
    points: tuple[Float32Vector, ...]
    length_bits: int
    clock_bits: int
    heuristic_bits: int | None


def _s32(value: int) -> int:
    return ((value + (1 << 31)) & 0xFFFFFFFF) - (1 << 31)


def _signed_word(value: int) -> None:
    if not isinstance(value, int) or not -(1 << 31) <= value < (1 << 31):
        raise ValueError("path request requires signed32 integer words")


def _unsigned_word(value: int) -> None:
    if not isinstance(value, int) or not 0 <= value < (1 << 32):
        raise ValueError("saved path metadata requires u32 words")


def _point(value: Q22Point) -> None:
    if not isinstance(value, tuple) or len(value) != 2:
        raise ValueError("path coordinate must contain two signed32 Q22 words")
    for word in value:
        _signed_word(word)


def _divide(numerator: int, denominator: int) -> int:
    quotient = abs(numerator) // abs(denominator)
    return -quotient if (numerator < 0) != (denominator < 0) else quotient


def _outcode(point: Q22Point, bounds: Q22Rectangle) -> int:
    x, y = point
    left, bottom, right, top = bounds
    return (1 if x < left else 2 if x > right else 0) | (4 if y < bottom else 8 if y > top else 0)


def _clip_window(start: Q22Point, goal: Q22Point, bounds: Q22Rectangle) -> Q22Point | None:
    """Original14107a8b0, including Q22 rounding before integer division."""
    a, b = start, goal
    ca, cb = _outcode(a, bounds), _outcode(b, bounds)
    while ca or cb:
        if ca & cb:
            return None
        code = ca or cb
        sx, sy = a
        gx, gy = b
        dx, dy = _s32(gx - sx), _s32(gy - sy)
        if code & 3:
            x = bounds[0] if code & 1 else bounds[2]
            product = _s32((_s32(x - sx) * dy) >> 22)
            y = _s32(sy + _divide(product << 22, dx))
        else:
            y = bounds[1] if code & 4 else bounds[3]
            product = _s32((_s32(y - sy) * dx) >> 22)
            x = _s32(sx + _divide(product << 22, dy))
        if code == ca:
            a = x, y
            ca = _outcode(a, bounds)
        else:
            b = x, y
            cb = _outcode(b, bounds)
    return b


def _f32(value: float) -> float:
    return float(struct.unpack("<f", struct.pack("<f", value))[0])


def _float_point(point: Q22Point) -> Float32Vector:
    words = tuple(struct.unpack("<I", struct.pack("<f", word / _Q))[0] for word in point)
    return words[0], 0, words[1]


def _distance_squared(start: Q22Point, goal: Q22Point, extents: Q22Point) -> int:
    x = max(abs(goal[0] - start[0]) - extents[0], 0)
    y = max(abs(goal[1] - start[1]) - extents[1], 0)
    return (x * x >> 22) + (y * y >> 22)


def _heuristic(start: Q22Point, goal: Q22Point, extents: Q22Point, mode: bool) -> int:
    if mode:
        return _s32(math.isqrt(_distance_squared(start, goal, extents) << 22))
    x = _f32((goal[0] - start[0]) / _Q)
    y = _f32((goal[1] - start[1]) / _Q)
    squared = _f32(_f32(y * y) + _f32(x * x))
    length = _f32(math.sqrt(squared))
    return _s32(int(_f32(length * _Q)))


def _range_endpoint(start: Q22Point, endpoint: Q22Point, reach: int) -> Q22Point:
    if reach == 0:
        return endpoint
    x, y = _s32(start[0] - endpoint[0]), _s32(start[1] - endpoint[1])
    divisor = _s32(math.isqrt((x * x & -_Q) + (y * y & -_Q)))
    if divisor == 0:
        raise ValueError("native range adjustment would divide by zero")
    nx, ny = _s32(_divide(x << 22, divisor)), _s32(_divide(y << 22, divisor))
    return _s32(endpoint[0] + (nx * reach >> 22)), _s32(endpoint[1] + (ny * reach >> 22))


def _cell(word: int) -> int:
    return (word + (_Q - 1 if word < 0 else 0)) >> 22


def _validate_traversal(start: Q22Point, endpoint: Q22Point, stride: int) -> None:
    """Preserve141083a70 enumeration; reject native unsafe cell dereferences."""
    sx, sy = start
    ex, ey = endpoint
    dx, dy = _s32(ex - sx), _s32(ey - sy)
    ax, ay = abs(dx), abs(dy)
    x, y = _cell(sx), _cell(sy)
    step_x, step_y = (dx > 0) - (dx < 0), (dy > 0) - (dy < 0)
    count = abs(_cell(ex) - x) + abs(_cell(ey) - y) + 1
    distance_x = (x + 1) * _Q - sx if dx > 0 else sx - x * _Q
    distance_y = (y + 1) * _Q - sy if dy > 0 else sy - y * _Q
    error = (distance_x * ay) >> 22 if dx else 0x7FC00000
    error = _s32(error - (distance_y * ax >> 22)) if dy else -(1 << 31)
    while count > 0:
        index = (y * stride + x) & 0xFFFFFFFF
        if index >= stride * stride:
            raise ValueError("native cell traversal would dereference an invalid cell")
        count -= 1
        if error <= 0:
            x += step_x
            error = _s32(error + ay)
        else:
            y += step_y
            error = _s32(error - ax)


def find_empty_replay_path(
    context: EmptyPathContext,
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
    """Native modern fresh-path request in empty occupancy, with raw AL result.

    Status0 means already in range,1 returns raw binary32 point words, and5
    rejects the working rectangle. Incoming length and clock words are copied
    unchanged. Radius must fit the modern0..0.5 branch; target extents/range
    are nonnegative and expanded extents must fit signed32. The caller must
    explicitly provide an empty context. Unsafe native cell accesses or zero
    divisors are rejected instead of inventing a route.
    """
    if not isinstance(context, EmptyPathContext):
        raise ValueError("an explicit empty path context is required")
    for point in (start, goal, target_extents):
        _point(point)
    for word in (radius, range_q22):
        _signed_word(word)
    if not 0 <= radius <= _Q // 2:
        raise ValueError("modern empty path radius must be in0..0.5 Q22 tiles")
    if range_q22 < 0 or any(
        extent < 0 or extent + radius >= (1 << 31) for extent in target_extents
    ):
        raise ValueError("path range/extents must be nonnegative and fit signed32")
    if not isinstance(heuristic_mode, bool):
        raise ValueError("path heuristic mode must be a Boolean")
    _unsigned_word(length_bits)
    _unsigned_word(clock_bits)

    def result(
        status: int, points: tuple[Float32Vector, ...] = (), heuristic: int | None = None
    ) -> ClearPathResult:
        bits = heuristic & 0xFFFFFFFF if heuristic is not None else None
        return ClearPathResult(status, points, length_bits, clock_bits, bits)

    maximum = _s32(context.stride * _Q - radius - 1)
    bounds = (
        max(radius, _s32(min(start[0], goal[0]) - 4 * _Q)),
        max(radius, _s32(min(start[1], goal[1]) - 4 * _Q)),
        min(maximum, _s32(max(start[0], goal[0]) + 4 * _Q)),
        min(maximum, _s32(max(start[1], goal[1]) + 4 * _Q)),
    )
    if _outcode(start, bounds):
        return result(5)
    clipped_goal = _clip_window(start, goal, bounds)
    if clipped_goal is None:
        return result(5)
    expanded = tuple(radius + extent if extent else 0 for extent in target_extents)
    extents: Q22Point = expanded[0], expanded[1]
    if _distance_squared(start, clipped_goal, extents) <= (range_q22 * range_q22 >> 22):
        return result(0)
    heuristic = _heuristic(start, clipped_goal, extents, heuristic_mode)
    first = _float_point(start)
    if heuristic < range_q22:
        # 14107c1a0 accepts the initial node. Its parent is-1, so native empty
        # reconstruction appends only the original start and returns AL1.
        return result(1, (first,), heuristic)
    margin = _Q // 2 - radius
    rectangle = (
        _s32(clipped_goal[0] - extents[0] + margin),
        _s32(clipped_goal[1] - extents[1] + margin),
        _s32(clipped_goal[0] + extents[0] - margin),
        _s32(clipped_goal[1] + extents[1] - margin),
    )
    contact = intersect_path_rectangle(start, clipped_goal, rectangle)
    endpoint = clipped_goal
    if contact.result:
        endpoint = (
            _s32(start[0] + (_s32(clipped_goal[0] - start[0]) * contact.fraction >> 22)),
            _s32(start[1] + (_s32(clipped_goal[1] - start[1]) * contact.fraction >> 22)),
        )
    endpoint = _range_endpoint(start, endpoint, range_q22)
    _validate_traversal(start, endpoint, context.stride)
    last = _float_point(endpoint)
    return result(1, (first,) if first == last else (first, last), heuristic)
