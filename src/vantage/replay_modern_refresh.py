"""Validated logical occupancy import and bounded original action-end refresh.

The refresh represents141121110, not the combined141122240 updater. Its first
profile supports stationary normalized geometry, an existing non-tail slot and
no allocation. The caller supplies the actual modern gate and virtual610 mode.
Snapshots retain local original contour consistency and order; import does not
prove a global registration chronology or reconstruct unused heap payload.
"""

from __future__ import annotations

import math
import struct
from dataclasses import dataclass

from .replay_occupancy import (
    OccupancyCell,
    OccupancyEdge,
    OccupancyRegistry,
    OccupancySlot,
    OccupancySnapshot,
    UnsupportedOccupancy,
    _associations,
    _CellVector,
    _EdgeVector,
)
from .replay_path_geometry import Q22Rectangle

_Q = 1 << 22
_NONE = 0xFFFFFFFF
_MAX_BYTES = 64 << 20
_MAX_ENTRIES = 1000000
_MAX_PAIR_VISITS = 2000000
type _Contours = dict[tuple[int, int], list[OccupancyEdge]]


class UnsupportedModernRefresh(UnsupportedOccupancy):
    """The supplied state or operation exceeds the proved refresh profile."""


@dataclass(frozen=True, slots=True)
class ModernRefreshResult:
    """Logical wrapper result; registry_changed marks the remove/reinsert branch.

    That branch can leave an identical snapshot when all touched vectors have
    only the subject. It does not mean a world position or legacy record changed.
    """

    native_index: int
    legacy_flag3: int | None
    enabled: bool
    raw_rectangle: Q22Rectangle | None
    registry_changed: bool


def _integer(value: int, minimum: int, maximum: int, label: str) -> None:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(f"{label} has an invalid integer type or width")


def _tuple(value: object, size: int | None, label: str) -> None:
    if type(value) is not tuple or (size is not None and len(value) != size):
        raise ValueError(f"{label} must be an immutable tuple of the declared length")


def _budget(value: int) -> None:
    if value > _MAX_BYTES:
        raise UnsupportedModernRefresh("snapshot logical capacity exceeds64 MiB")


def _contours(a: Q22Rectangle, b: Q22Rectangle, ai: int, bi: int) -> _Contours:
    result: _Contours = {}
    for owner, side, edge in _associations(a, b, ai, bi):
        result.setdefault((owner, side), []).append(edge)
    return result


def import_occupancy_snapshot(
    snapshot: OccupancySnapshot, *, visited_words: tuple[int, ...]
) -> OccupancyRegistry:
    """Import defined logical state after structural and geometric validation.

    Explicit used visited words must all be zero. Every unordered neighboring
    pair's contours must match one of the two original insertion orientations;
    their retained interleaving is preserved, without inferring global history.
    At most8192 slots, one million used edges/cell entries and64 MiB of native
    logical capacity are admitted. A new registry is published only on success.
    """
    if type(snapshot) is not OccupancySnapshot:
        raise ValueError("an OccupancySnapshot is required")
    registry = OccupancyRegistry(snapshot.stride)
    _tuple(snapshot.slots, None, "slots")
    _tuple(snapshot.cells, None, "cells")
    _tuple(visited_words, None, "visited words")
    n = len(snapshot.slots)
    if n > 8192:
        raise UnsupportedModernRefresh("snapshot exceeds8192 allocated slots")
    _integer(snapshot.visited_bit_count, n, 0x7FFFFFFF, "visited bit count")
    for value, minimum, label in (
        (snapshot.rectangle_capacity, n, "rectangle capacity"),
        (snapshot.edge_group_capacity, n, "edge-group capacity"),
        (snapshot.visited_word_capacity, snapshot.visited_word_count, "visited capacity"),
    ):
        _integer(value, minimum, 0x7FFFFFFF, label)
    _integer(snapshot.free_head, 0, _NONE, "free head")
    if len(visited_words) != snapshot.visited_word_count:
        raise ValueError("used visited-word extent does not match bit count")
    for word in visited_words:
        _integer(word, 0, _NONE, "visited word")
        if word:
            raise UnsupportedModernRefresh("nonzero visited scratch state is unsupported")
    budget = (
        snapshot.rectangle_capacity * 16
        + snapshot.edge_group_capacity * 96
        + snapshot.visited_word_capacity * 4
        + snapshot.stride**2 * 24
    )
    _budget(budget)
    rectangles: list[Q22Rectangle] = []
    active: set[int] = set()
    incoming: dict[tuple[int, int], _Contours] = {}
    edge_total = 0
    # Validate all slot declarations before following any cross-slot references.
    for index, slot in enumerate(snapshot.slots):
        if type(slot) is not OccupancySlot or type(slot.active) is not bool:
            raise ValueError("slots require typed records and Boolean active fields")
        _tuple(slot.words, 4, "slot words")
        _tuple(slot.edges, 4, "slot edge vectors")
        _tuple(slot.edge_capacities, 4, "slot edge capacities")
        if slot.active:
            active.add(index)
            if registry._rectangle(slot.words) != slot.words:
                raise ValueError("active snapshot rectangles must already be normalized")
        else:
            for word in slot.words:
                _integer(word, 0, _NONE, "free slot word")
            if slot.words[1:] != (0, 0, 0):
                raise ValueError("free slots require next-free followed by three zeros")
        rectangles.append(slot.words)
        for edges, capacity in zip(slot.edges, slot.edge_capacities, strict=True):
            _tuple(edges, None, "edge vector")
            _integer(capacity, len(edges), 0x7FFFFFFF, "edge capacity")
            if not slot.active and edges:
                raise ValueError("free slots cannot retain used edges")
            budget += capacity * 28
            edge_total += len(edges)
            _budget(budget)
            if edge_total > _MAX_ENTRIES:
                raise UnsupportedModernRefresh("snapshot exceeds one million used edges")
    free, holes = snapshot.free_head, set(range(n)) - active
    linked: set[int] = set()
    while free != _NONE:
        if free not in holes or free in linked:
            raise ValueError("free chain is cyclic or names an active/out-of-range slot")
        linked.add(free)
        free = rectangles[free][0]
    if linked != holes:
        raise ValueError("every inactive slot must occur exactly once in the free chain")
    expected_cells: dict[int, set[int]] = {}
    memberships = 0
    for index in active:
        for cell_index in registry._membership(rectangles[index]):
            memberships += 1
            if memberships > _MAX_ENTRIES:
                raise UnsupportedModernRefresh("snapshot exceeds one million cell memberships")
            expected_cells.setdefault(cell_index, set()).add(index)
    pairs: set[tuple[int, int]] = set()
    previous_cell = -1
    pair_visits = cell_total = 0
    for cell in snapshot.cells:
        if type(cell) is not OccupancyCell:
            raise ValueError("typed cell headers are required")
        _integer(cell.index, 0, snapshot.stride**2 - 1, "cell index")
        if cell.index <= previous_cell:
            raise ValueError("cell headers must be unique and ordered by index")
        previous_cell = cell.index
        _tuple(cell.indices, None, "cell indices")
        _integer(cell.capacity, len(cell.indices), 0x7FFFFFFF, "cell capacity")
        budget += cell.capacity * 4
        _budget(budget)
        cell_total += len(cell.indices)
        if cell_total > _MAX_ENTRIES:
            raise UnsupportedModernRefresh("snapshot exceeds one million used cell entries")
        for index in cell.indices:
            _integer(index, 0, n - 1, "cell slot index")
        if len(set(cell.indices)) != len(cell.indices):
            raise ValueError("a cell cannot contain duplicate slot indices")
        if set(cell.indices) != expected_cells.pop(cell.index, set()):
            raise ValueError("cell membership must exactly match active rectangles")
        pair_visits += len(cell.indices) * (len(cell.indices) - 1) // 2
        if pair_visits > _MAX_PAIR_VISITS:
            raise UnsupportedModernRefresh("snapshot contour validation exceeds pair budget")
        for ordinal, a in enumerate(cell.indices):
            for b in cell.indices[ordinal + 1 :]:
                pairs.add((min(a, b), max(a, b)))
    if expected_cells:
        raise ValueError("required cell memberships are missing")
    for owner, slot in enumerate(snapshot.slots):
        for side, edges in enumerate(slot.edges):
            for edge in edges:
                if type(edge) is not OccupancyEdge:
                    raise ValueError("typed contour edges are required")
                _integer(edge.other_index, 0, n - 1, "edge other index")
                _integer(edge.other_side, 0, 3, "edge other side")
                _integer(edge.flag, 0, 1, "edge flag")
                _tuple(edge.point, 2, "edge point")
                for word in (*edge.point, edge.axis, edge.halfspan):
                    _integer(word, -0x80000000, 0x7FFFFFFF, "edge coordinate")
                pair = min(owner, edge.other_index), max(owner, edge.other_index)
                if owner == edge.other_index or edge.other_index not in active or pair not in pairs:
                    raise ValueError("edges must join distinct active slots sharing cells")
                incoming.setdefault(pair, {}).setdefault((owner, side), []).append(edge)
    # Exact per-pair contours reject missing, extra, dangling and impossible edges.
    # One of the two insertion orientations must explain the entire pair, including
    # point/side/axis/halfspan/flag and each owner's per-side edge order.
    for a, b in pairs:
        actual = incoming.get((a, b), {})
        if actual != _contours(rectangles[a], rectangles[b], a, b) and actual != _contours(
            rectangles[b], rectangles[a], b, a
        ):
            raise ValueError("contours cannot arise from either original pair insertion order")
    registry._rectangles = rectangles
    registry._active = [index in active for index in range(n)]
    registry._edges = [
        [
            _EdgeVector(list(edges), capacity)
            for edges, capacity in zip(slot.edges, slot.edge_capacities, strict=True)
        ]
        for slot in snapshot.slots
    ]
    registry._cells = {
        cell.index: _CellVector(list(cell.indices), cell.capacity) for cell in snapshot.cells
    }
    registry._rectangle_capacity = snapshot.rectangle_capacity
    registry._edge_group_capacity = snapshot.edge_group_capacity
    registry._visited_bit_count = snapshot.visited_bit_count
    registry._visited_word_capacity = snapshot.visited_word_capacity
    registry._free_head = snapshot.free_head
    return registry


def _bits_pair(value: tuple[int, int] | None, label: str) -> None:
    if value is not None:
        _tuple(value, 2, label)
        for word in value:
            _integer(word, 0, _NONE, label)


def _raw_rectangle(
    registry: OccupancyRegistry, position: tuple[int, int], radii: tuple[int, int]
) -> Q22Rectangle:
    xy = tuple(struct.unpack("<f", struct.pack("<I", word))[0] for word in position)
    radius = tuple(struct.unpack("<f", struct.pack("<I", word))[0] for word in radii)
    if any(not math.isfinite(v) or not -1 <= v <= registry.stride + 1 for v in xy) or any(
        not math.isfinite(v) or not 0 <= v <= registry.stride + 1 for v in radius
    ):
        raise UnsupportedModernRefresh("finite centers/radii must lie in the bounded map domain")
    # Power-of-two scaling is exact binary32 in this finite domain (including
    # subnormals); all scaled values fit signed64. Truncation precedes low32
    # wrapping integer center +/- radius +/- half-tile arithmetic.
    x, y = (int(value * _Q) for value in xy)
    rx, ry = (int(value * _Q) for value in radius)

    def s32(value: int) -> int:
        return ((value + (1 << 31)) & _NONE) - (1 << 31)

    return (
        s32(x - rx - _Q // 2),
        s32(y - ry - _Q // 2),
        s32(x + rx + _Q // 2),
        s32(y + ry + _Q // 2),
    )


def _preflight(registry: OccupancyRegistry, index: int, normalized: Q22Rectangle) -> None:
    neighbors: list[int] = []
    seen: set[int] = set()
    for cell in registry._membership(normalized):
        for neighbor in registry._cells[cell].values:
            if neighbor not in seen:
                seen.add(neighbor)
                neighbors.append(neighbor)
                if len(neighbors) > 128:
                    raise UnsupportedModernRefresh("refresh exceeds128 local scratch candidates")
    counts = {
        (owner, side): (
            0 if owner == index else sum(edge.other_index != index for edge in vector.values)
        )
        for owner in neighbors
        for side, vector in enumerate(registry._edges[owner])
    }
    # Removal only reduces counts. Check every actual append in native order,
    # rather than assuming equal final geometry implies allocation cannot occur.
    for neighbor in neighbors:
        if neighbor == index:
            continue
        for owner, side, _ in _associations(
            registry._rectangles[neighbor], normalized, neighbor, index
        ):
            counts[owner, side] += 1
            if counts[owner, side] > registry._edges[owner][side].capacity:
                raise UnsupportedModernRefresh("refresh would grow an edge vector")


def refresh_action_end(
    registry: OccupancyRegistry,
    *,
    native_index: int,
    modern_gate: bool,
    mode: int,
    legacy_flag3: int | None,
    position_xy_bits: tuple[int, int] | None = None,
    effective_radius_xy_bits: tuple[int, int] | None = None,
) -> ModernRefreshResult:
    """Original141121110 logical result, with stationary non-tail no-growth refresh.

    A missing legacy record skips both modern work and flag store. A false
    actual gate skips modern work but preserves the wrapper's later flag result.
    Gate-true mode16/removal, new slots, tail slots and changed normalized bounds
    are unsupported. Radius selection and the actual610 decision remain inputs.
    Supported-profile rejection precedes mutation; no native allocation-failure
    rollback or complete object/tick/position-commit behavior is claimed.
    """
    if type(registry) is not OccupancyRegistry or type(modern_gate) is not bool:
        raise ValueError("a registry and explicit Boolean modern gate are required")
    _integer(native_index, 0, _NONE, "native index")
    if type(mode) is not int or mode not in (0, 0x10):
        raise UnsupportedModernRefresh("only explicit virtual610 modes0 and16 are supported")
    if legacy_flag3 is not None:
        _integer(legacy_flag3, 0, 255, "legacy flag")
    _bits_pair(position_xy_bits, "position bits")
    _bits_pair(effective_radius_xy_bits, "effective radius bits")
    enabled = mode != 0x10
    if legacy_flag3 is None:
        return ModernRefreshResult(native_index, None, enabled, None, False)
    flags = (legacy_flag3 & 0x0F) | mode
    if not modern_gate:
        return ModernRefreshResult(native_index, flags, enabled, None, False)
    if not enabled:
        raise UnsupportedModernRefresh("gate-true removal is outside the first refresh profile")
    registry._index(native_index)
    if native_index == len(registry._rectangles) - 1:
        raise UnsupportedModernRefresh("tail-slot refresh is outside the first profile")
    if position_xy_bits is None or effective_radius_xy_bits is None:
        raise ValueError("enabled refresh requires explicit position and selected radius bits")
    raw = _raw_rectangle(registry, position_xy_bits, effective_radius_xy_bits)
    normalized = registry._rectangle(raw)
    if normalized != registry._rectangles[native_index]:
        raise UnsupportedModernRefresh("refresh requires unchanged normalized geometry")
    changed = raw != registry._rectangles[native_index]
    if changed:
        _preflight(registry, native_index, normalized)
        returned = registry.change(native_index, raw)
        assert returned == native_index  # The immediately created non-tail hole is reused.
    return ModernRefreshResult(native_index, flags, enabled, raw, changed)
