"""Modern occupancy registry from explicit, ordered Q22 rectangle operations.

This ports1410b7340/1410b78a0/1410b8320/1410b8830 for map-intersecting
rectangles within one extra tile and at most 8,192 allocated slots. It preserves native index
reuse, cell order, contour associations and vector capacities. It does not
infer entity registration chronology, query ignore bytes or a restored heap.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .replay_path_geometry import Q22Point, Q22Rectangle

_Q = 1 << 22
_NONE = 0xFFFFFFFF
_MAX_SLOTS = 8192


class UnsupportedOccupancy(ValueError):
    """An operation exceeds the proved registry profile."""


@dataclass(frozen=True, slots=True)
class OccupancyEdge:
    other_index: int
    other_side: int
    point: Q22Point
    axis: int
    flag: int
    halfspan: int


@dataclass(frozen=True, slots=True)
class OccupancyCell:
    index: int
    capacity: int
    indices: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class OccupancySlot:
    # Active slots contain signed normalized Q22 rectangle words.
    # Free slots retain raw u32 next-free words; they are not geometric rectangles.
    words: tuple[int, int, int, int]
    active: bool
    edges: tuple[tuple[OccupancyEdge, ...], ...]
    edge_capacities: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class OccupancySnapshot:
    stride: int
    slots: tuple[OccupancySlot, ...]
    cells: tuple[OccupancyCell, ...]
    free_head: int
    rectangle_capacity: int
    edge_group_capacity: int
    visited_bit_count: int
    visited_word_capacity: int

    @property
    def visited_word_count(self) -> int:
        return (self.visited_bit_count + 31) // 32


@dataclass(slots=True)
class _CellVector:
    values: list[int] = field(default_factory=list)
    capacity: int = 0

    def append(self, index: int) -> None:
        self.capacity = _capacity(self.capacity, len(self.values) + 1)
        self.values.append(index)


@dataclass(slots=True)
class _EdgeVector:
    values: list[OccupancyEdge] = field(default_factory=list)
    capacity: int = 0

    def append(self, edge: OccupancyEdge) -> None:
        self.capacity = _capacity(self.capacity, len(self.values) + 1)
        self.values.append(edge)


def _capacity(current: int, required: int) -> int:
    return max(required, current + current // 2) if required > current else current


def _corners(rect: Q22Rectangle) -> tuple[Q22Point, ...]:
    return (
        (rect[0], rect[1]),
        (rect[2], rect[1]),
        (rect[2], rect[3]),
        (rect[0], rect[3]),
    )


def _associations(
    a: Q22Rectangle, b: Q22Rectangle, ai: int, bi: int
) -> tuple[tuple[int, int, OccupancyEdge], ...]:
    overlap = max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])
    if overlap[0] >= overlap[2] or overlap[1] >= overlap[3]:
        return ()
    half = min(overlap[2] - overlap[0], overlap[3] - overlap[1]) // 2
    result: list[tuple[int, int, OccupancyEdge]] = []
    for x, y in _corners(overlap):
        shared = False
        # Preserve native X-first side choice, including equality/corner precedence.
        if x == a[0]:
            sa = 3
            if x == b[0]:
                sb, shared = 3, True
            elif y == b[1]:
                sb = 0
                if y == a[1]:
                    sa, shared = 0, True
            elif y == b[3]:
                sb = 2
                if y == a[3]:
                    sa, shared = 2, True
            else:
                continue
        elif x == a[2]:
            sa = 1
            if x == b[2]:
                sb, shared = 1, True
            elif y == b[1]:
                sb = 0
                if y == a[1]:
                    sa, shared = 0, True
            elif y == b[3]:
                sb = 2
                if y == a[3]:
                    sa, shared = 2, True
            else:
                continue
        elif x == b[0]:
            sb = 3
            if y == a[1]:
                sa = 0
                if y == b[1]:
                    sb, shared = 0, True
            elif y == a[3]:
                sa = 2
                if y == b[3]:
                    sb, shared = 2, True
            else:
                continue
        elif x == b[2]:
            sb = 1
            if y == a[1]:
                sa = 0
                if y == b[1]:
                    sb, shared = 0, True
            elif y == a[3]:
                sa = 2
                if y == b[3]:
                    sb, shared = 2, True
            else:
                continue
        else:
            continue
        if shared:
            owner, other = ai, bi
            # Ordinal-first, old rectangle before new at each matching ordinal.
            for ac, bc in zip(_corners(a), _corners(b), strict=True):
                if (x, y) == ac:
                    break
                if (x, y) == bc:
                    owner, other = bi, ai
                    break
            side, other_side = sa, sb
            flag = int(
                (
                    x in (a[0], b[0]),
                    y in (a[1], b[1]),
                    x in (a[2], b[2]),
                    y in (a[3], b[3]),
                )[side]
            )
        elif (sb + 1) & 3 == sa:
            owner, other, side, other_side, flag = ai, bi, sa, sb, 0
        elif (sb - 1) & 3 == sa:
            owner, other, side, other_side, flag = bi, ai, sb, sa, 0
        else:
            continue
        edge = OccupancyEdge(other, other_side, (x, y), x if side % 2 == 0 else y, flag, half)
        result.append((owner, side, edge))
    return tuple(result)


class OccupancyRegistry:
    """Mutable bounded native registry; the caller supplies registration chronology.

    Inputs are four signed32 Q22 words, ordered with positive width/height.
    Raw bounds may extend one tile beyond the map and must intersect its closed
    box, with lower bounds strictly below its upper edge. Signed rectangle
    endpoints survive normalization; only cell membership is clipped. At most 8,192
    allocated slots are supported, including free holes. Failed validation leaves
    the registry untouched. Snapshots and accessors return immutable data.
    """

    def __init__(self, stride: int) -> None:
        if type(stride) is not int or not 1 <= stride <= 200:
            raise ValueError("registry stride must be an integer between1 and200")
        self._stride = stride
        self._rectangles: list[Q22Rectangle] = []
        self._active: list[bool] = []
        self._edges: list[list[_EdgeVector]] = []
        self._cells: dict[int, _CellVector] = {}
        self._rectangle_capacity = 0
        self._edge_group_capacity = 0
        self._visited_word_capacity = 0
        self._visited_bit_count = 0
        self._free_head = _NONE

    @property
    def stride(self) -> int:
        return self._stride

    @property
    def active_indices(self) -> tuple[int, ...]:
        return tuple(i for i, active in enumerate(self._active) if active)

    def _rectangle(self, rectangle: Q22Rectangle) -> Q22Rectangle:
        if not isinstance(rectangle, tuple) or len(rectangle) != 4:
            raise ValueError("rectangle must be an immutable tuple of four Q22 words")
        if any(
            type(word) is not int or not -_Q <= word <= (self.stride + 1) * _Q for word in rectangle
        ):
            raise UnsupportedOccupancy("rectangle words exceed the proved one-tile map margin")
        if rectangle[0] >= rectangle[2] or rectangle[1] >= rectangle[3]:
            raise ValueError("rectangle must have positive ordered width and height")
        if (
            rectangle[0] >= self.stride * _Q
            or rectangle[1] >= self.stride * _Q
            or rectangle[2] < 0
            or rectangle[3] < 0
        ):
            raise UnsupportedOccupancy("rectangle must intersect the proved closed map box")
        return (
            rectangle[0] & ~1,
            rectangle[1] & ~1,
            (rectangle[2] + 1) & ~1,
            (rectangle[3] + 1) & ~1,
        )

    def _index(self, index: int) -> None:
        if type(index) is not int or not 0 <= index < len(self._active) or not self._active[index]:
            raise ValueError("an active native registry index is required")

    def _membership(self, rectangle: Q22Rectangle) -> tuple[int, ...]:
        x0, y0, x1, y1 = (min(self.stride - 1, max(0, word // _Q)) for word in rectangle)
        return tuple(y * self.stride + x for y in range(y0, y1 + 1) for x in range(x0, x1 + 1))

    def add(self, rectangle: Q22Rectangle) -> int:
        """Normalize, then append or consume the LIFO free head and register cells."""
        normalized = self._rectangle(rectangle)
        if self._free_head == _NONE:
            index = len(self._rectangles)
            if index == _MAX_SLOTS:
                raise UnsupportedOccupancy("the proved registry profile has at most 8,192 slots")
            self._rectangle_capacity = _capacity(self._rectangle_capacity, index + 1)
            self._edge_group_capacity = _capacity(self._edge_group_capacity, index + 1)
            self._visited_bit_count += 1
            words = (self._visited_bit_count + 31) // 32
            self._visited_word_capacity = _capacity(self._visited_word_capacity, words)
            self._rectangles.append(normalized)
            self._active.append(True)
            self._edges.append([_EdgeVector() for _ in range(4)])
        else:
            index = self._free_head
            self._free_head = self._rectangles[index][0]
            self._rectangles[index] = normalized
            self._active[index] = True
        visited: set[int] = set()
        for cell in self._membership(normalized):
            vector = self._cells.setdefault(cell, _CellVector())
            for previous in vector.values:
                if previous in visited:
                    continue
                visited.add(previous)
                for owner, side, edge in _associations(
                    self._rectangles[previous], normalized, previous, index
                ):
                    self._edges[owner][side].append(edge)
            vector.append(index)
        return index

    def remove(self, index: int) -> None:
        """Stable-filter cells/associations; shrink one tail slot or push a free hole."""
        self._index(index)
        visited: set[int] = set()
        for cell in self._membership(self._rectangles[index]):
            vector = self._cells[cell]
            for previous in vector.values:
                if previous in visited:
                    continue
                visited.add(previous)
                for edges in self._edges[previous]:
                    edges.values[:] = [e for e in edges.values if e.other_index != index]
            vector.values.remove(index)
        if index == len(self._rectangles) - 1:
            self._rectangles.pop()
            self._active.pop()
            self._edges.pop()
        else:
            self._rectangles[index] = self._free_head, 0, 0, 0
            self._free_head = index
            self._active[index] = False
            for edges in self._edges[index]:
                edges.values.clear()

    def change(self, index: int, rectangle: Q22Rectangle) -> int:
        """Compare raw input to stored normalized words before remove/reinsert."""
        self._index(index)
        self._rectangle(rectangle)
        if rectangle == self._rectangles[index]:
            return index
        self.remove(index)
        return self.add(rectangle)

    def registered_rectangle(self, index: int) -> Q22Rectangle:
        self._index(index)
        return self._rectangles[index]

    def cell_indices(self, x: int, y: int) -> tuple[int, ...]:
        if any(type(word) is not int or not 0 <= word < self.stride for word in (x, y)):
            raise ValueError("integer cell coordinates must be inside the registry")
        vector = self._cells.get(y * self.stride + x)
        return () if vector is None else tuple(vector.values)

    def edge_associations(self, index: int, side: int) -> tuple[OccupancyEdge, ...]:
        self._index(index)
        if type(side) is not int or not 0 <= side < 4:
            raise ValueError("side must be0 bottom,1 right,2 top or3 left")
        return tuple(self._edges[index][side].values)

    def snapshot(self) -> OccupancySnapshot:
        return OccupancySnapshot(
            self.stride,
            tuple(
                OccupancySlot(
                    rectangle,
                    active,
                    tuple(tuple(v.values) for v in row),
                    tuple(v.capacity for v in row),
                )
                for rectangle, active, row in zip(
                    self._rectangles, self._active, self._edges, strict=True
                )
            ),
            tuple(
                OccupancyCell(cell, vector.capacity, tuple(vector.values))
                for cell, vector in sorted(self._cells.items())
            ),
            self._free_head,
            self._rectangle_capacity,
            self._edge_group_capacity,
            self._visited_bit_count,
            self._visited_word_capacity,
        )
