"""Fresh modern paths around one isolated registered rectangle.

This bounded port preserves the original search queue, defined backing-node
fields, contour costs and final binary32 path. Callers supply ordered cells,
ignore bytes and empty obstacle-edge vectors. Terrain insertion, associated or
second obstacles, clipped contours and unsupported ray branches fail explicitly.
"""

from __future__ import annotations

from dataclasses import dataclass

from .replay_clear_path import _distance_squared, _float_point, _heuristic, _outcode, _point, _s32
from .replay_movement_geometry import Float32Vector
from .replay_path_geometry import Q22Point, Q22Rectangle, first_containing_path_obstacle
from .replay_path_search import (
    PathSearchGrid,
    UnsupportedPathSearch,
    initialize_path_search_first_hit,
    inset_path_search_corner,
    snap_path_search_point,
    trace_path_search_segment,
)

Q = 1 << 22
U = 0xFFFFFFFF


class UnsupportedIsolatedPath(ValueError):
    """The request requires a search branch outside the proved isolated profile."""


@dataclass(frozen=True, slots=True)
class IsolatedPathRuntime:
    """Explicit initialized runtime globals and four raw edge-vector payloads per obstacle."""

    cost_sentinel: int
    contour_budget: int
    obstacle_edges: tuple[tuple[bytes, bytes, bytes, bytes], ...]


@dataclass(frozen=True, slots=True)
class IsolatedPathNode:
    """Defined native48-byte node fields; unspecified copied padding is omitted."""

    cost_bits: int
    priority_bits: int
    index: int
    parent_index: int
    point: Q22Point
    flag: int
    obstacle_index: int | None = None
    side: int | None = None
    direction: int | None = None
    left_index: int | None = None
    right_index: int | None = None
    contour_index: int | None = None
    previous_side: int | None = None
    current_side: int | None = None


@dataclass(frozen=True, slots=True)
class IsolatedPathContour:
    points: tuple[Q22Point, ...]
    sides: tuple[int, ...]
    obstacle_indices: tuple[int, ...]
    cost_bits: tuple[int, ...]
    closed: bool


@dataclass(frozen=True, slots=True)
class IsolatedPathResult:
    status: int
    points: tuple[Float32Vector, ...]
    length_bits: int
    clock_bits: int
    nodes: tuple[IsolatedPathNode, ...]
    contours: tuple[IsolatedPathContour, ...]
    queue_indices: tuple[int, ...]
    reconstruction: tuple[Q22Point, ...]


@dataclass
class _Node:
    g: int
    f: int
    index: int
    parent: int
    point: tuple[int, int]
    flag: int
    obstacle: int = -1
    side: int = 0
    direction: int = 0
    left: int = -1
    right: int = -1
    contour: int = -1
    side0: int = 0
    side1: int = 0

    def words(self) -> tuple[int, ...]:
        a = [v & U for v in (self.g, self.f, self.index, self.parent, *self.point)]
        a.append(self.flag)
        if self.flag == 2:
            a += [self.obstacle & U, self.side]
        if self.flag == 3:
            a += [
                self.direction,
                self.left & U,
                self.right & U,
                self.contour & U,
                self.side0,
                self.side1,
            ]
        return tuple(a)


@dataclass
class _Contour:
    points: list[tuple[int, int]]
    sides: list[int]
    obstacle: int
    costs: list[int]
    closed: int = 0

    def words(self) -> tuple[int, ...]:
        result = [len(self.points), self.closed]
        for p, side, cost in zip(self.points, self.sides, self.costs, strict=True):
            result += [*p, side, self.obstacle, cost & U]
        return tuple(result)


def _axis_contact(
    start: Q22Point, end: Q22Point, rectangle: Q22Rectangle, margin: int, direction: int
) -> tuple[Q22Point, int] | None:
    sx, sy = start
    ex, ey = end
    a, b, c, d = rectangle
    lo_x, lo_y, hi_x, hi_y = (a + margin, b + margin, c - margin, d - margin)
    if direction == 0 and lo_x < sx < hi_x and ey < hi_y <= sy:
        return (sx, hi_y), 2
    if direction == 1 and lo_y < sy < hi_y and sx <= lo_x < ex:
        return (lo_x, sy), 3
    if direction == 2 and lo_x < sx < hi_x and sy <= lo_y < ey:
        return (sx, lo_y), 0
    if direction == 3 and lo_y < sy < hi_y and ex < hi_x <= sx:
        return (hi_x, sy), 1
    return None


def _axis_trace(
    grid: PathSearchGrid, start: Q22Point, end: Q22Point, margin: int, direction: int
) -> tuple[bool, Q22Point, int, int]:
    stride = grid.occupancy.stride
    sx, sy = start[0] // Q, start[1] // Q
    ex, ey = end[0] // Q, end[1] // Q
    if direction == 0:
        cells = [y * stride + sx for y in range(sy, ey - 1, -1)]
    elif direction == 1:
        cells = [sy * stride + x for x in range(sx, ex + 1)]
    elif direction == 2:
        cells = [y * stride + sx for y in range(sy, ey + 1)]
    else:
        cells = [sy * stride + x for x in range(sx, ex - 1, -1)]
    point, obstacle, side = end, -1, -1
    for cell in cells:
        for i in grid.cell_indices[cell]:
            if grid.occupancy.ignored[i] == 1:
                continue
            rect = grid.occupancy.obstacles[i]
            hit = _axis_contact(start, point, rect, margin, direction)
            if hit is None:
                continue
            if hit[0] == start and point == end:
                reverse = _axis_contact(point, start, rect, margin, (direction - 2) & 3)
                if reverse and reverse[0] == start:
                    continue
            point, side = hit
            obstacle = i
    return obstacle != -1, point, obstacle, side


def _allows_corner(previous: int, current: int, point: Q22Point, goal: Q22Point) -> bool:
    x, y = point
    gx, gy = goal
    if previous == 0:
        return gx <= x and gy <= y if current == 3 else gx > x or gy < y
    if previous == 1:
        return gx >= x and gy <= y if current == 0 else gx > x or gy > y
    if previous == 2:
        return gx >= x and gy >= y if current == 1 else gx < x or gy > y
    if previous == 3:
        return gx <= x and gy >= y if current == 2 else gx < x or gy < y
    return False


class _Search:
    def __init__(
        self,
        grid: PathSearchGrid,
        start: Q22Point,
        goal: Q22Point,
        radius: int,
        mode: bool,
        sentinel: int,
        bounds: Q22Rectangle,
        obstacle: int,
    ) -> None:
        self.grid, self.start, self.goal = grid, start, goal
        self.radius, self.margin, self.mode = radius, Q // 2 - radius, mode
        self.nodes: list[_Node] = []
        self.queue: list[int] = []
        self.contours: list[_Contour] = []
        self.best, self.fallback = -1, 0
        self.sentinel = sentinel
        self.bounds, self.obstacle = bounds, obstacle

    def append(self, g: int, parent: int, point: Q22Point, flag: int, **fields: int) -> _Node:
        if len(self.nodes) >= 256:
            raise UnsupportedIsolatedPath("search exceeds the proved preallocated node capacity")
        g = _s32(g)
        node = _Node(
            g,
            _s32(g + _heuristic(point, self.goal, (0, 0), self.mode)),
            len(self.nodes),
            parent,
            point,
            flag,
            **fields,
        )
        self.nodes.append(node)
        return node

    def push(self, node: _Node) -> None:
        # Native vector descending, insertion before equal: minimum popped FIFO.
        at = 0
        while at < len(self.queue) and self.nodes[self.queue[at]].f > node.f:
            at += 1
        self.queue.insert(at, node.index)

    def check(self, node: _Node) -> bool:
        h = _s32(node.f - node.g)
        fallback = self.nodes[self.fallback]
        if h < _s32(fallback.f - fallback.g):
            self.fallback = node.index
        if h >= 0 and _distance_squared(node.point, self.goal, (0, 0)) > 0:
            return self.best != -1 and self.nodes[self.best].g <= node.g
        if self.best == -1 or node.g < self.nodes[self.best].g:
            self.best = node.index
            return True
        return self.nodes[self.best].g <= node.g

    def offer(
        self,
        g: int,
        parent: int,
        direction: int,
        ranges: tuple[int, int],
        contour: int,
        point: Q22Point,
    ) -> bool:
        dx, dy = (_s32(point[i] - self.goal[i]) for i in range(2))
        squared = (dx * dx >> 22) + (dy * dy >> 22)
        if not self.mode:
            squared = _s32(squared)
        fields = dict(direction=direction, left=ranges[0], right=ranges[1], contour=contour)
        if squared <= 0 and (self.best == -1 or g < self.nodes[self.best].g):
            self.best = self.append(g, parent, point, 3, **fields).index
            return True
        fallback = self.nodes[self.fallback]
        h = _s32(fallback.f - fallback.g)
        if squared < (h * h >> 22):
            self.fallback = self.append(g, parent, point, 3, **fields).index
        return False

    def axis(
        self,
        a: Q22Point,
        b: Q22Point,
        g: int,
        parent: int,
        direction: int,
        ranges: tuple[int, int],
        contour: int,
    ) -> None:
        axis = 0 if a[0] != b[0] else 1
        low, high = min(a[axis], b[axis]), max(a[axis], b[axis])
        center = self.goal[axis]
        # Extents are zero; both strict boundary calls are still performed.
        for value in (center, center):
            if low < value < high:
                p = (value, a[1]) if axis == 0 else (a[0], value)
                if self.offer(
                    _s32(g + abs(value - a[axis])), parent, direction, ranges, contour, p
                ):
                    return
        if low <= center <= high:
            p = (center, a[1]) if axis == 0 else (a[0], center)
            self.offer(_s32(g + abs(center - a[axis])), parent, direction, ranges, contour, p)

    def expand(self, ci: int, node: _Node) -> None:
        contour = self.contours[ci]
        p, sides = contour.points, contour.sides
        f, r = 0, len(p) - 1

        def cheby(a: Q22Point, b: Q22Point) -> int:
            return max(abs(a[0] - b[0]), abs(a[1] - b[1]))

        self.axis(node.point, p[r], node.g, node.index, 1, (0, 0), ci)
        self.axis(node.point, p[0], node.g, node.index, 0, (0, 0), ci)
        gf, gr = _s32(node.g + cheby(node.point, p[0])), _s32(node.g + cheby(node.point, p[r]))
        while f < r:
            direction = 1 if gr < gf else 0
            if direction:
                i, j, ranges, g = r, r - 1, (r, 0), gr
                previous = sides[j]
            else:
                i, j, ranges, g = f, f + 1, (0, f + 1), gf
                f = j
                previous = sides[(i + len(p) - 1) % len(p)]
            accepted = self.offer(g, node.index, direction, ranges, ci, p[i])
            if (
                not accepted
                and previous != sides[i]
                and _allows_corner(previous, sides[i], p[i], self.goal)
            ):
                n = self.append(
                    g,
                    node.index,
                    p[i],
                    3,
                    direction=direction,
                    left=ranges[0],
                    right=ranges[1],
                    contour=ci,
                    side0=previous,
                    side1=sides[i],
                )
                self.push(n)
                contour.closed = 1
                contour.costs[i] = g
            self.axis(p[i], p[j], g, node.index, direction, ranges, ci)
            if direction:
                r, gr = j, _s32(gr + cheby(p[i], p[j]))
            else:
                gf = _s32(gf + cheby(p[i], p[j]))

    def containing(self, point: Q22Point) -> int:
        cell = point[1] // Q * self.grid.occupancy.stride + point[0] // Q
        return first_containing_path_obstacle(
            point,
            self.grid.occupancy.obstacles,
            self.grid.cell_indices[cell],
            self.grid.occupancy.ignored,
            self.margin,
        )

    def strict_hit(
        self, node: _Node, endpoint: Q22Point, fraction: int, obstacle: int, side: int
    ) -> None:
        if obstacle != self.obstacle:
            raise UnsupportedIsolatedPath("route encounters a second obstacle")
        point = (
            _s32(node.point[0] + (_s32(endpoint[0] - node.point[0]) * fraction >> 22)),
            _s32(node.point[1] + (_s32(endpoint[1] - node.point[1]) * fraction >> 22)),
        )
        point = snap_path_search_point(
            point, self.grid.occupancy.obstacles[obstacle], side, self.margin
        )
        if self.containing(point) != -1:
            raise UnsupportedIsolatedPath("resnap")
        if point == node.point and node.flag == 3:
            return
        cost = _s32(node.g + _heuristic(node.point, point, (0, 0), False))
        self.push(self.append(cost, node.index, point, 2, obstacle=obstacle, side=side))

    def tolerant_hit(self, node: _Node, endpoint: Q22Point, fraction: int, obstacle: int) -> None:
        if obstacle != self.obstacle:
            raise UnsupportedIsolatedPath("route encounters a second obstacle")
        fraction -= 0x66666
        while fraction > 0:
            point = (
                _s32(node.point[0] + (_s32(endpoint[0] - node.point[0]) * fraction >> 22)),
                _s32(node.point[1] + (_s32(endpoint[1] - node.point[1]) * fraction >> 22)),
            )
            if self.containing(point) == -1:
                node = self.append(
                    _s32(node.g + _heuristic(node.point, point, (0, 0), False)),
                    node.index,
                    point,
                    1,
                )
                break
            fraction -= 0x66666
        rect = self.grid.occupancy.obstacles[obstacle]
        center = ((rect[0] + rect[2]) // 2, (rect[1] + rect[3]) // 2)
        dx, dy = (1 if center[0] > node.point[0] else 3), (2 if center[1] > node.point[1] else 0)
        for direction, other in ((dx, dy), (dy, dx)):
            endpoint1 = (
                (center[0], node.point[1]) if direction in (1, 3) else (node.point[0], center[1])
            )
            hit, point, oi, side = _axis_trace(
                self.grid, node.point, endpoint1, self.margin, direction
            )
            if hit:
                g = node.g + max(abs(point[i] - node.point[i]) for i in range(2))
                parent = node.index
            else:
                intermediate = self.append(
                    node.g + max(abs(endpoint1[i] - node.point[i]) for i in range(2)),
                    node.index,
                    endpoint1,
                    1,
                )
                hit, point, oi, side = _axis_trace(self.grid, endpoint1, center, self.margin, other)
                if not hit:
                    raise UnsupportedIsolatedPath("axis second no hit")
                parent = intermediate.index
                g = intermediate.g + max(abs(point[i] - endpoint1[i]) for i in range(2))
            self.push(self.append(g, parent, point, 2, obstacle=oi, side=side))

    def cache_find(self, contour: _Contour, node: _Node) -> int:
        for i, point in enumerate(contour.points):
            if node.point == point:
                return i
            end = contour.points[(i + 1) % len(contour.points)]
            if contour.sides[i] == node.side and (
                (
                    point[0] == end[0] == node.point[0]
                    and min(point[1], end[1]) <= node.point[1] <= max(point[1], end[1])
                )
                or (
                    point[1] == end[1] == node.point[1]
                    and min(point[0], end[0]) <= node.point[0] <= max(point[0], end[0])
                )
            ):
                return i
        return -1

    def revisit(self, ci: int, node: _Node, found: int) -> None:
        contour = self.contours[ci]
        p, sides, costs = contour.points, contour.sides, contour.costs
        count = len(p)
        left, right = found, (found + 1) % count
        initial_left, initial_right = left, right

        def distance(a: Q22Point, b: Q22Point) -> int:
            return max(abs(a[0] - b[0]), abs(a[1] - b[1]))

        gl = _s32(node.g + distance(node.point, p[left]))
        gr = _s32(node.g + distance(node.point, p[right]))
        enable_l = gl < costs[left] or costs[left] == self.sentinel
        enable_r = gr < costs[right] or costs[right] == self.sentinel
        iterations = 0
        while enable_l or enable_r:
            iterations += 1
            if iterations > 2 * count:
                raise UnsupportedIsolatedPath("cached contour iteration budget")
            direction = 0 if enable_r and (gr <= gl or not enable_l) else 1
            i, g = (left, gl) if direction else (right, gr)
            ranges = (i, initial_right) if direction else (initial_left, i)
            if costs[i] != self.sentinel:
                accepted = self.offer(g, node.index, direction, ranges, ci, p[i])
                previous, current = sides[(i - 1) % count], sides[i]
                if (
                    not accepted
                    and previous != current
                    and _allows_corner(previous, current, p[i], self.goal)
                ):
                    self.push(
                        self.append(
                            g,
                            node.index,
                            p[i],
                            3,
                            direction=direction,
                            left=ranges[0],
                            right=ranges[1],
                            contour=ci,
                            side0=previous,
                            side1=current,
                        )
                    )
                    costs[i] = g
            while True:
                j = (i - 1 if direction else i + 1) % count
                g = _s32(g + distance(p[i], p[j]))
                i = j
                enabled = g < costs[i]
                if costs[i] != self.sentinel:
                    break
                ranges = (i, initial_right) if direction else (initial_left, i)
                if self.offer(g, node.index, direction, ranges, ci, p[i]):
                    break
            if direction:
                left, gl, enable_l = i, g, enabled
            else:
                right, gr, enable_r = i, g, enabled

    def run(self) -> tuple[Q22Point, ...]:
        self.push(self.append(0, -1, self.start, 0))
        while self.queue:
            node = self.nodes[self.queue.pop()]
            if self.check(node):
                continue
            if node.flag == 1:
                continue
            if node.flag in (0, 3):
                if (
                    node.flag == 3
                    and self.best != -1
                    and node.g + _heuristic(node.point, self.goal, (0, 0), False)
                    >= self.nodes[self.best].g
                ):
                    continue
                if node.flag == 3 and (
                    node.point[0] == self.goal[0] or node.point[1] == self.goal[1]
                ):
                    direction = (
                        (1 if self.goal[0] > node.point[0] else 3)
                        if node.point[1] == self.goal[1]
                        else (2 if self.goal[1] > node.point[1] else 0)
                    )
                    hit, _point, _oi, side = _axis_trace(
                        self.grid, node.point, self.goal, self.margin, direction
                    )
                    if hit:
                        raise UnsupportedIsolatedPath("axial flag3 hit fraction")
                    result, fraction, obstacle, side = 0, 0x466666, -1, -1
                else:
                    ray = trace_path_search_segment(self.grid, node.point, self.goal, self.margin)
                    result, fraction, obstacle, side = (
                        ray.result,
                        ray.fraction,
                        ray.obstacle_index,
                        ray.side,
                    )
                if result == 1:
                    self.strict_hit(node, self.goal, fraction, obstacle, side)
                elif result == 2:
                    self.tolerant_hit(node, self.goal, fraction, obstacle)
                elif node.flag == 3:
                    n = self.append(
                        node.g + _heuristic(node.point, self.goal, (0, 0), False),
                        node.index,
                        self.goal,
                        3,
                        left=-1,
                        right=-1,
                        contour=-1,
                        side0=255,
                        side1=255,
                    )
                    if self.best == -1 or n.g < self.nodes[self.best].g:
                        self.best = n.index
                else:
                    raise UnsupportedIsolatedPath("clear initial request")
            elif node.flag == 2:
                for ci in range(len(self.contours)):
                    contour = self.contours[ci]
                    found = self.cache_find(contour, node)
                    if found != -1:
                        break
                else:
                    if self.contours:
                        raise UnsupportedIsolatedPath("second or unrecognized contour")
                    ci = len(self.contours)
                    sides = [(node.side + 1 + i) & 3 for i in range(4)]
                    points = [
                        inset_path_search_corner(
                            self.grid.occupancy.obstacles[node.obstacle], i, self.margin
                        )
                        for i in sides
                    ]
                    if any(_outcode(p, self.bounds) for p in points):
                        raise UnsupportedIsolatedPath("contour requires working-window traversal")
                    self.contours.append(
                        _Contour(points, sides, node.obstacle, [self.sentinel] * 4)
                    )
                    self.expand(ci, node)
                    continue
                if self.mode and contour.closed:
                    self.revisit(ci, node, found)
        if self.best == -1:
            raise UnsupportedIsolatedPath("no accepted route")
        reverse: list[Q22Point] = []

        def append_point(p: Q22Point) -> None:
            if not reverse or reverse[-1] != p:
                reverse.append(p)

        n = self.nodes[self.best]
        while n.parent != -1:
            append_point(n.point)
            if n.flag == 3 and n.contour != -1:
                contour = self.contours[n.contour]
                i = n.left if n.direction else n.right
                while i != (n.right if n.direction else n.left):
                    if not n.direction:
                        i = (i - 1) % len(contour.points)
                    append_point(contour.points[i])
                    if n.direction:
                        i = (i + 1) % len(contour.points)
            n = self.nodes[n.parent]
        append_point(self.start)
        margin = Q // 2 - self.radius // 2
        a = 0
        while a < len(reverse):
            b = a + 2
            while b < len(reverse):
                p, q = reverse[b], reverse[a]
                if p[0] == q[0] or p[1] == q[1]:
                    direction = (
                        (1 if q[0] > p[0] else 3) if p[1] == q[1] else (2 if q[1] > p[1] else 0)
                    )
                    hit = _axis_trace(self.grid, p, q, margin, direction)[0]
                else:
                    hit = trace_path_search_segment(self.grid, p, q, margin).result != 0
                if not hit:
                    del reverse[a + 1 : b]
                    b = a + 1
                b += 1
            a += 1
        return tuple(reverse)


def find_isolated_replay_path(
    grid: PathSearchGrid,
    start: Q22Point,
    goal: Q22Point,
    radius: int,
    *,
    runtime: IsolatedPathRuntime,
    heuristic_mode: bool = False,
    length_bits: int = 0,
    clock_bits: int = 0,
) -> IsolatedPathResult:
    """Complete a fresh zero-range/zero-extents isolated-wall request.

    The supported runtime profile supplies sentinel -4194304, budget2000 and
    four empty raw edge-vector payloads for every registered rectangle. These
    initialized globals are caller inputs, not inferred from a DAT or save.
    Ordered grid cells and ignore bytes are retained. The result includes every
    defined backing-node field and the final reverse reconstruction after
    native smoothing; length/timestamp words retain their incoming bits.

    Unsupported branches raise before returning a path. Inputs are immutable
    and no partial cache or queue is published on failure.
    """
    if not isinstance(grid, PathSearchGrid) or not isinstance(runtime, IsolatedPathRuntime):
        raise ValueError("isolated paths require an explicit grid and runtime profile")
    _point(start)
    _point(goal)
    if not isinstance(radius, int) or not 0 <= radius <= Q // 2:
        raise ValueError("modern isolated radius must be in0..0.5 Q22 tiles")
    if not isinstance(heuristic_mode, bool):
        raise ValueError("path heuristic mode must be Boolean")
    for word in (length_bits, clock_bits):
        if not isinstance(word, int) or not 0 <= word <= U:
            raise ValueError("path metadata requires u32 words")
    context = grid.occupancy
    edges = runtime.obstacle_edges
    if not isinstance(edges, tuple) or len(edges) != len(context.obstacles):
        raise ValueError("each obstacle requires four explicit edge-vector payloads")
    if any(
        not isinstance(sides, tuple)
        or len(sides) != 4
        or any(not isinstance(payload, bytes) for payload in sides)
        for sides in edges
    ):
        raise ValueError("obstacle edge vectors require four immutable byte payloads")
    if any(payload for sides in edges for payload in sides):
        raise UnsupportedIsolatedPath("associated obstacle contours are not ported")
    if (runtime.cost_sentinel, runtime.contour_budget) != (-Q, 2000):
        raise UnsupportedIsolatedPath("unverified initialized contour globals")
    if context.stride > 128:
        raise UnsupportedIsolatedPath("isolated geometry is bounded to128-tile grids")
    if any(value not in (0, 1) for value in context.ignored):
        raise UnsupportedIsolatedPath("this registered profile requires Boolean ignore bytes")
    limit = context.stride * Q
    for rectangle in context.obstacles:
        left, bottom, right, top = rectangle
        if (
            min(rectangle) < 0
            or right >= limit
            or top >= limit
            or left >= right
            or bottom >= top
            or any(word & 1 for word in rectangle)
        ):
            raise UnsupportedIsolatedPath(
                "registered rectangles require positive even in-map bounds"
            )
    for i, a in enumerate(context.obstacles):
        for b in context.obstacles[i + 1 :]:
            if max(a[0], b[0]) <= min(a[2], b[2]) and max(a[1], b[1]) <= min(a[3], b[3]):
                raise UnsupportedIsolatedPath(
                    "touching or overlapping rectangles need associated contours"
                )
    goal_cell = goal[1] // Q * context.stride + goal[0] // Q
    if (
        0 <= goal_cell < context.stride**2
        and first_containing_path_obstacle(
            goal,
            context.obstacles,
            grid.cell_indices[goal_cell],
            context.ignored,
            Q // 2 - radius,
        )
        != -1
    ):
        raise UnsupportedIsolatedPath("goal lies inside a registered obstacle")
    try:
        initial = initialize_path_search_first_hit(
            grid, start, goal, radius, heuristic_mode=heuristic_mode
        )
    except UnsupportedPathSearch as exc:
        raise UnsupportedIsolatedPath(str(exc)) from exc
    maximum = context.stride * Q - radius - 1
    bounds = (
        max(radius, min(start[0], goal[0]) - 4 * Q),
        max(radius, min(start[1], goal[1]) - 4 * Q),
        min(maximum, max(start[0], goal[0]) + 4 * Q),
        min(maximum, max(start[1], goal[1]) + 4 * Q),
    )
    margin = Q // 2 - radius
    rectangle = context.obstacles[initial.ray.obstacle_index]
    if rectangle[2] - rectangle[0] <= margin * 2 or rectangle[3] - rectangle[1] <= margin * 2:
        raise UnsupportedIsolatedPath("degenerate inset contours are not ported")
    if any(
        _outcode(inset_path_search_corner(rectangle, corner, margin), bounds) for corner in range(4)
    ):
        raise UnsupportedIsolatedPath("contour requires working-window traversal")
    search = _Search(
        grid,
        start,
        goal,
        radius,
        heuristic_mode,
        runtime.cost_sentinel,
        bounds,
        initial.ray.obstacle_index,
    )
    if search.containing(goal) != -1:
        raise UnsupportedIsolatedPath("goal lies inside a registered obstacle")
    reverse = search.run()
    nodes = tuple(
        IsolatedPathNode(
            node.g & U,
            node.f & U,
            node.index,
            node.parent & U,
            node.point,
            node.flag,
            node.obstacle & U if node.flag == 2 else None,
            node.side if node.flag == 2 else None,
            node.direction if node.flag == 3 else None,
            node.left & U if node.flag == 3 else None,
            node.right & U if node.flag == 3 else None,
            node.contour & U if node.flag == 3 else None,
            node.side0 if node.flag == 3 else None,
            node.side1 if node.flag == 3 else None,
        )
        for node in search.nodes
    )
    contours = tuple(
        IsolatedPathContour(
            tuple(contour.points),
            tuple(contour.sides),
            (contour.obstacle,) * len(contour.points),
            tuple(word & U for word in contour.costs),
            bool(contour.closed),
        )
        for contour in search.contours
    )
    return IsolatedPathResult(
        1,
        tuple(_float_point(point) for point in reversed(reverse)),
        length_bits,
        clock_bits,
        nodes,
        contours,
        tuple(search.queue),
        reverse,
    )
