"""Common terrain height from held XY fractions and explicit current tile data.

Build54800,141266c9c..141266f50; see world-tile-terrain-height-source-v1.
The slope byte belongs to the retained selected tile after collision work;
the unsigned base byte is separately read from the then-current object tile.
Neither this pure calculation nor its projection flag commits object height,
dispatches virtual68, executes callbacks or establishes tile backing.
Default masked nearest-even MXCSR, DAZ/FTZ off; FP status is excluded.
"""

from __future__ import annotations

from dataclasses import dataclass

from .replay_movement_geometry import _bits, _float, _op

_ONE = 0x3F800000


@dataclass(frozen=True, slots=True)
class ReplayWorldTileHeight:
    """Raw slope offset, virtual68 height argument and separate projection flag."""

    slope_bits: int
    height_bits: int
    projection_flag_bits: int


def replay_world_tile_height(
    fraction_bits: tuple[int, int], *, slope_shape: int, base_elevation: int
) -> ReplayWorldTileHeight:
    """Evaluate all 17 native slopes without merging distinct phase inputs.

    X/Y are the earlier held fractions, not new coordinate or tile reads.
    Both bytes are supplied explicitly; selected and current tiles may differ
    after callbacks. Shapes17..255 keep slope/flag+0. All binary32 words are
    admitted, preserving source operand order, unordered branches, signaling
    payloads and signed zero. MINSS/MAXSS return their exact second source on
    equality or unordered comparison. Base+offset is one rounded ADDSS.

    The projection flag is raw0.0/1.0 for the later projection continuation;
    it is not a height multiplier. The result supplies virtual68's argument,
    not the final Z of arbitrary object families or complete position setup.
    """
    if type(fraction_bits) is not tuple or len(fraction_bits) != 2:
        raise ValueError("terrain height requires two immutable binary32 fraction words")
    if any(type(word) is not int or not 0 <= word <= 0xFFFFFFFF for word in fraction_bits):
        raise ValueError("terrain fractions must be binary32 u32 words")
    if any(type(byte) is not int or not 0 <= byte <= 255 for byte in (slope_shape, base_elevation)):
        raise ValueError("slope shape and base elevation must be unsigned bytes")
    x, y = fraction_bits
    slope = 0
    match slope_shape:
        case 1 | 2 | 11 | 12 | 13 | 14:
            total = _op(y, x, "+")
            below = _float(total) < 1.0
            match slope_shape:
                case 1:
                    slope = y if below else _op(_ONE, x, "-")
                case 2:
                    slope = x if below else _op(_ONE, y, "-")
                case 11:
                    slope = _op(_ONE, total, "-") if below else 0
                case 12:
                    slope = _op(total, _ONE, "-") if _float(total) > 1.0 else 0
                case 13:
                    slope = _op(_ONE, x, "-") if below else y
                case 14:
                    slope = _op(_ONE, y, "-") if below else x
        case 3:
            slope = _op(_ONE, x if _float(x) > _float(y) else y, "-")
        case 4:
            slope = y if _float(y) < _float(x) else x
        case 5:
            slope = _op(_ONE, x, "-")
        case 6:
            slope = _op(_ONE, y, "-")
        case 7:
            slope = y
        case 8:
            slope = x
        case 9 | 10:
            delta = _op(x, y, "-")
            if slope_shape == 9:
                slope = delta ^ 0x80000000 if _float(delta) < 0.0 else 0
            else:
                slope = delta if _float(delta) > 0.0 else 0
        case 15:
            slope = x if _float(x) > _float(y) else y
        case 16:
            slope = _op(_ONE, y if _float(x) > _float(y) else x, "-")
    return ReplayWorldTileHeight(
        slope,
        _op(_bits(float(base_elevation)), slope, "+"),
        _ONE if slope_shape in (2, 6, 8, 10, 14, 15, 16) else 0,
    )
