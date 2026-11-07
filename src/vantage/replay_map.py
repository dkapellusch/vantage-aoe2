"""Reconstruct derived map fields from saved DE terrain.

Slope selection follows the native restore helper at ``0x1410416e0`` in the
build-54800 memory-derived executable. See ``native-replay-playback.md`` for
REA evidence and independent comparisons. Layer rebuilding and the structural
map loader are separate, unfinished parts of restoring the whole world.
"""

from __future__ import annotations

from collections.abc import Sequence


def slope_shapes(elevations: Sequence[int], width: int, height: int) -> tuple[int, ...]:
    """Return row-major native slope shapes (0..16) for a saved elevation grid.

    An absent border neighbour uses the current cell's elevation. Cardinal
    pairs take priority over single edges, then diagonal corners. Corner
    variants also depend on opposite neighbours being one level lower.
    """
    if width <= 0 or height <= 0 or len(elevations) != width * height:
        raise ValueError("elevation grid dimensions do not match")
    if any(not 0 <= level <= 255 for level in elevations):
        raise ValueError("elevation must fit a native unsigned byte")
    result = []
    for y in range(height):
        for x in range(width):
            at = y * width + x
            level = elevations[at]
            north = elevations[at - width] if y else level
            south = elevations[at + width] if y + 1 < height else level
            west = elevations[at - 1] if x else level
            east = elevations[at + 1] if x + 1 < width else level
            ne = elevations[at - width + 1] if y and x + 1 < width else level
            sw = elevations[at + width - 1] if x and y + 1 < height else level
            nw = elevations[at - width - 1] if x and y else level
            se = elevations[at + width + 1] if x + 1 < width and y + 1 < height else level
            high, low = level + 1, level - 1
            if north == high and east == high:
                shape = 14
            elif west == high and south == high:
                shape = 13
            elif north == high and west == high:
                shape = 16
            elif east == high and south == high:
                shape = 15
            elif north == high:
                shape = 6
            elif east == high:
                shape = 8
            elif west == high:
                shape = 5
            elif south == high:
                shape = 7
            elif ne == high:
                shape = 2 if west == low and south == low else 10
            elif sw == high:
                shape = 1 if north == low and east == low else 9
            elif nw == high:
                shape = 3 if east == low and south == low else 11
            elif se == high:
                shape = 4 if north == low and west == low else 12
            else:
                shape = 0
            result.append(shape)
    return tuple(result)
