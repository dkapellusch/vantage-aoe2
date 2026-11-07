"""Coordinate stages used by Common/Moving World tile placement (build54800).

These are the numerical blocks of1412665c0 and141225790, not full setters.
The caller supplies Common arguments and Map5b40/44 bounds. Moving retains its
original requested XY; its radii/map/virtual220 result are post-callback inputs.
Common's reference148 early return must be handled before its numerical stage;
it does not skip Moving's preceding work. No object or registry is mutated.
All APIs assume masked nearest-even MXCSR, with DAZ/FTZ off; FP status is omitted.
See world-tile-initial-chronology-v1 and world-tile-geometry-source-review-v1.
"""

from __future__ import annotations

from dataclasses import dataclass

from .replay_movement_geometry import _bits, _float, _nan, _op

_MASK = 0xFFFFFFFF
_INDEFINITE = -(1 << 31)
_COMMON_MARGIN = 0x3A83126F
_MOVING_MARGIN = 0x3C23D70A
_EPSILON = 0x33D6BF95


def _word(value: int) -> None:
    if type(value) is not int or not 0 <= value <= _MASK:
        raise ValueError("tile geometry requires binary32 u32 words")


def _pair(value: tuple[int, int]) -> None:
    if type(value) is not tuple or len(value) != 2:
        raise ValueError("tile geometry requires two immutable binary32 words")
    for component in value:
        _word(component)


def _dimension(value: int) -> None:
    if type(value) is not int or not 1 <= value < 1 << 31:
        raise ValueError("tile geometry dimensions must be positive signed32 integers")


def _cvtt32(word: int) -> int:
    # Masked CVTTSS2SI32 writes the integer indefinite for NaN, infinity or
    # overflow. Python int alone would raise or retain an unbounded integer.
    if word & 0x7F800000 == 0x7F800000:
        return _INDEFINITE
    value = _float(word)
    return int(value) if _INDEFINITE <= value < 1 << 31 else _INDEFINITE


def replay_world_tile_plane_coordinates(xy_bits: tuple[int, int]) -> tuple[int, int]:
    """Convert current XY exactly as the old-tile removal's two CVTTSS2SI32s.

    No coordinate or map clamp is applied. The returned signed32 pair also
    represents the pre-integer-clamp target conversions used by append. The
    registry separately checks whether the wrapped plane address is backed.
    """
    _pair(xy_bits)
    return _cvtt32(xy_bits[0]), _cvtt32(xy_bits[1])


@dataclass(frozen=True, slots=True)
class ReplayWorldTileCoordinates:
    """A Common numerical-stage result, before any tile-list operation.

    XY is native map XY, not renderer XYZ. Fractions retain the original
    binary32 subtraction from the unclamped signed32 conversion, including
    NaN/overflow. A bounded tile index does not establish actual backing or
    imply that the independent plane address is safe.
    """

    xy_bits: tuple[int, int]
    fraction_bits: tuple[int, int]
    plane_coordinates: tuple[int, int]
    tile_coordinates: tuple[int, int]
    tile_index: int
    plane_index: int


def replay_world_tile_coordinates(
    xy_bits: tuple[int, int],
    *,
    width: int,
    height: int,
    upper_bounds_bits: tuple[int, int],
) -> ReplayWorldTileCoordinates:
    """Common141266631..141266803: clamp, convert and compute a tile index.

    Map width/height and float bounds are independent supplied fields. The
    numerical profile covers all binary32 words; storage is bounded to2**24
    cells, matching the logical tile registry. Default masked nearest-even
    MXCSR with DAZ/FTZ off is required; FP status is not modeled.
    Integration must establish actual Map8 backing: native null storage yields
    a null Tile*, whereas this pure function computes only the logical index.

    MAXSS(0,input) selects its exact second operand on equality/unordered,
    preserving negative zero and even signaling NaNs. The ordered upper test
    substitutes binary32(bound-.001). Only tile selection integer-clamps the
    conversions. Plane addressing keeps the earlier signed32 words and wraps
    the multiply/add to32 bits, as the append/remove helpers do.
    """
    _pair(xy_bits)
    _pair(upper_bounds_bits)
    _dimension(width)
    _dimension(height)
    if width * height > 1 << 24:
        raise ValueError("logical tile backing is limited to2**24 cells")
    clamped = []
    for value, bound in zip(xy_bits, upper_bounds_bits, strict=True):
        current = value if _nan(value) or _float(value) >= 0.0 else 0
        if not (_nan(current) or _nan(bound)) and _float(current) >= _float(bound):
            current = _op(bound, _COMMON_MARGIN, "-")
        clamped.append(current)
    position = clamped[0], clamped[1]
    ix, iy = replay_world_tile_plane_coordinates(position)
    fractions = (
        _op(position[0], _bits(float(ix)), "-"),
        _op(position[1], _bits(float(iy)), "-"),
    )
    tx, ty = min(max(ix, 0), width - 1), min(max(iy, 0), height - 1)
    plane_word = (iy * width + ix) & _MASK
    plane_index = plane_word if plane_word < 1 << 31 else plane_word - (1 << 32)
    return ReplayWorldTileCoordinates(
        position, fractions, (ix, iy), (tx, ty), ty * width + tx, plane_index
    )


def clamp_replay_moving_tile_xy(
    xy_bits: tuple[int, int],
    *,
    map_width: int,
    radius_bits: tuple[int, int],
    gate_bits: int,
) -> tuple[int, int]:
    """Moving141225e49..141226054, immediately before its Common call.

    The explicit virtual220 result must compare ordered>1e-7. Both axes use
    signed Map width30, including on rectangular maps. A lower-bound branch
    assigns radius+.01 and skips that axis's upper test. Otherwise compare to
    width-(radius+.01), but assign (width-radius)-.01: the rounding differs.

    Requested XY remains in XMM10/9 across earlier trail/graphic work and the
    virtual220 call. Current master/radii/map inputs must reflect those calls;
    this function neither executes nor skips them. It preserves untouched NaN
    words and excludes FP exception-status effects.
    """
    _pair(xy_bits)
    _pair(radius_bits)
    _word(gate_bits)
    _dimension(map_width)
    if _nan(gate_bits) or _float(gate_bits) <= _float(_EPSILON):
        return xy_bits
    width_bits = _bits(float(map_width))
    result = []
    for coordinate, radius in zip(xy_bits, radius_bits, strict=True):
        lower = _op(radius, _MOVING_MARGIN, "+")
        if not (_nan(lower) or _nan(coordinate)) and _float(lower) > _float(coordinate):
            result.append(lower)
            continue
        upper = _op(width_bits, lower, "-")
        if not (_nan(coordinate) or _nan(upper)) and _float(coordinate) > _float(upper):
            coordinate = _op(_op(width_bits, radius, "-"), _MOVING_MARGIN, "-")
        result.append(coordinate)
    return result[0], result[1]
