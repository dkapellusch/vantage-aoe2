"""Bounded native legacy segment/shape geometry; no spatial-index collector.

Inputs are finite binary32 words with absolute coordinates<=65,536 and expansion
between0 and4,096. Default native MXCSR is nearest-even without FTZ/DAZ. Native
emitted NaN/Inf words survive; no MXCSR sticky-flag or callback effect is modeled.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Literal

from .replay_movement_geometry import _float, _op

LegacySegment = tuple[int, int, int, int]


@dataclass(frozen=True, slots=True)
class LegacySegmentContactResult:
    hit: bool
    contact_count: int
    contact_buffer: bytes


def _finite(value: int, limit: float = 65536) -> None:
    if type(value) is not int or not 0 <= value <= 0xFFFFFFFF:
        raise ValueError("legacy geometry scalar must be a binary32 u32 word")
    if value & 0x7F800000 == 0x7F800000 or abs(_float(value)) > limit:
        raise ValueError("legacy geometry requires bounded finite binary32 inputs")


def _segment(value: LegacySegment) -> None:
    if not isinstance(value, tuple) or len(value) != 4:
        raise ValueError("legacy segment must contain four immutable binary32 words")
    for component in value:
        _finite(component)


def _orientation(a: tuple[int, int], b: tuple[int, int], c: tuple[int, int]) -> int:
    cx, cy = _op(c[0], a[0], "-"), _op(c[1], a[1], "-")
    bx, by = _op(b[0], a[0], "-"), _op(b[1], a[1], "-")
    cross_a, cross_b = _op(cx, by, "*"), _op(cy, bx, "*")
    if _float(cross_b) > _float(cross_a):
        return 1
    if _float(cross_a) > _float(cross_b):
        return -1
    if _float(_op(cx, bx, "*")) < 0 or _float(_op(cy, by, "*")) < 0:
        return -1
    b_length = _op(_op(by, by, "*"), _op(bx, bx, "*"), "+")
    c_length = _op(_op(cy, cy, "*"), _op(cx, cx, "*"), "+")
    return int(_float(c_length) > _float(b_length))


def _intersects(a: LegacySegment, b: LegacySegment) -> bool:
    a0, a1, b0, b1 = a[:2], a[2:], b[:2], b[2:]
    if _orientation(a0, a1, b1) * _orientation(a0, a1, b0) > 0:
        return False
    return _orientation(b0, b1, a1) * _orientation(b0, b1, a0) <= 0


def legacy_segments_intersect(segment: LegacySegment, edge: LegacySegment) -> bool:
    """Native141120d50/1411233a0, including projected collinear endpoint rules."""
    _segment(segment)
    _segment(edge)
    return _intersects(segment, edge)


def _point(bounds: LegacySegment, segment: LegacySegment) -> tuple[int, int]:
    x0, y0, x1, y1 = segment
    dx, dy = _op(x1, x0, "-"), _op(y1, y0, "-")
    rx, ry = _op(bounds[2], bounds[0], "-"), _op(bounds[3], bounds[1], "-")
    p = _op(_op(y0, bounds[1], "-"), rx, "*")
    q = _op(_op(x0, bounds[0], "-"), ry, "*")
    numerator = _op(p, q, "-")
    denominator = _op(_op(dx, ry, "*"), _op(dy, rx, "*"), "-")
    fraction = _op(numerator, denominator, "/")
    return _op(_op(fraction, dx, "*"), x0, "+"), _op(_op(fraction, dy, "*"), y0, "+")


def _edge(
    bounds: LegacySegment,
    segment: LegacySegment,
    edge: LegacySegment,
    emit: bool,
    entry_token: int,
    object_id: int,
    output: bytearray,
    count: int,
) -> tuple[bool, int]:
    hit = _intersects(segment, edge)
    if hit and emit:
        # Original uses the entry's complete raw bounds, regardless of the edge
        # that hit. It can append duplicate points and nonfinite coordinates.
        x, y = _point(bounds, segment)
        if count < len(output) // 24:
            struct.pack_into("<QiII", output, count * 24, entry_token, object_id, x, y)
            count += 1
    return hit, count


def legacy_segment_contacts(
    bounds: LegacySegment,
    segment: LegacySegment,
    *,
    shape: Literal["rectangle", "type5"] = "rectangle",
    expand: bool = False,
    expansion_bits: int = 0,
    emit_contacts: bool = False,
    entry_token: int = 0,
    object_id: int = 0,
    contact_buffer: bytes = b"",
    contact_count: int = 0,
) -> LegacySegmentContactResult:
    """Native14111cdc0/14111d100 with bounded14111e780 contact writes.

    All four ordered edges are tested, even after a hit. Each hit can append one
    24-byte record: opaque caller token, signed objectID and raw XY words. The
    last four record bytes and all preexisting/unwritten bytes survive exactly.
    An inside endpoint can return hit without appending any record. Expansion
    mode remains separate from radius zero to preserve native signed-zero math.
    """
    _segment(bounds)
    _segment(segment)
    _finite(expansion_bits, 4096)
    if _float(expansion_bits) < 0:
        raise ValueError("legacy expansion must be nonnegative")
    if (
        shape not in ("rectangle", "type5")
        or type(expand) is not bool
        or type(emit_contacts) is not bool
    ):
        raise ValueError("unsupported legacy shape/expansion/contact mode")
    if type(entry_token) is not int or not 0 <= entry_token <= 0xFFFFFFFFFFFFFFFF:
        raise ValueError("entry token must be a raw u64")
    if type(object_id) is not int or not -(1 << 31) <= object_id < (1 << 31):
        raise ValueError("legacy object ID must be signedi32")
    if (
        not isinstance(contact_buffer, bytes)
        or len(contact_buffer) % 24
        or len(contact_buffer) > 64 * 24
    ):
        raise ValueError("contact buffer must contain at most64 complete24-byte records")
    if type(contact_count) is not int or not 0 <= contact_count <= len(contact_buffer) // 24:
        raise ValueError("contact count must be inside the supplied capacity")
    left, bottom, right, top = bounds
    if expand:
        edge_left, edge_bottom = _op(left, expansion_bits, "-"), _op(bottom, expansion_bits, "-")
        edge_right, edge_top = _op(expansion_bits, right, "+"), _op(expansion_bits, top, "+")
    else:
        edge_left, edge_bottom, edge_right, edge_top = bounds
    edges = (
        (edge_left, edge_bottom, edge_right, edge_bottom),
        (edge_right, edge_bottom, edge_right, edge_top),
        (edge_right, edge_top, edge_left, edge_top),
        (edge_left, edge_top, edge_left, edge_bottom),
    )
    output, count, hit = bytearray(contact_buffer), contact_count, False
    for edge in edges:
        edge_hit, count = _edge(
            bounds, segment, edge, emit_contacts, entry_token, object_id, output, count
        )
        hit |= edge_hit
    if not hit:
        if shape == "rectangle":
            lo_x = right if _float(right) < _float(left) else left
            hi_x = right if _float(left) < _float(right) else left
            lo_y = top if _float(top) < _float(bottom) else bottom
            hi_y = top if _float(bottom) < _float(top) else bottom
            if expand:
                lo_x, lo_y = _op(lo_x, expansion_bits, "-"), _op(lo_y, expansion_bits, "-")
                hi_x, hi_y = _op(expansion_bits, hi_x, "+"), _op(expansion_bits, hi_y, "+")
        else:
            lo_x, lo_y, hi_x, hi_y = edge_left, edge_bottom, edge_right, edge_top
        hit = any(
            _float(lo_x) <= _float(x) <= _float(hi_x) and _float(lo_y) <= _float(y) <= _float(hi_y)
            for x, y in (segment[:2], segment[2:])
        )
    return LegacySegmentContactResult(hit, count, bytes(output))
