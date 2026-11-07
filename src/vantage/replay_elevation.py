"""Native elevation policy and grounded flag for one object update.

Build54800 routines141252780 and141218df0 consume an already calculated
terrain height. Computing that height, committing XY/tile membership and
running the complete movement/action update are separate operations.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ReplayElevationUpdate:
    height_bits: int
    grounded: bool


def update_replay_elevation(
    height_bits: int,
    terrain_height_bits: int,
    elevation_mode: int,
    *,
    has_tile: bool,
) -> ReplayElevationUpdate:
    """Apply master+0xa8 policy and moving-object+0x390 grounded update.

    Mode0 replaces height. Mode1 raises it only on an ordered, strict float
    comparison. Every other byte preserves it. Grounded means the resulting
    height compares equal to terrain height and the object has a tile.
    Raw binary32 words preserve signed zero and NaN payloads; native unordered
    comparisons neither raise mode1 height nor report a grounded object.

    This is an isolated component of SetElevation, not a complete position
    setter or a saved-world fixup. In particular it cannot explain or invent
    an initial airborne height from a master category.
    """
    if not isinstance(height_bits, int) or not 0 <= height_bits <= 0xFFFFFFFF:
        raise ValueError("object height must be a binary32 u32 word")
    if not isinstance(terrain_height_bits, int) or not 0 <= terrain_height_bits <= 0xFFFFFFFF:
        raise ValueError("terrain height must be a binary32 u32 word")
    if not isinstance(elevation_mode, int) or not 0 <= elevation_mode <= 255:
        raise ValueError("elevation mode must fit a native byte")
    if not isinstance(has_tile, bool):
        raise ValueError("has_tile must be a bool")
    height = struct.unpack("<f", struct.pack("<I", height_bits))[0]
    terrain = struct.unpack("<f", struct.pack("<I", terrain_height_bits))[0]
    if elevation_mode == 0 or (elevation_mode == 1 and terrain > height):
        result_bits, result = terrain_height_bits, terrain
    else:
        result_bits, result = height_bits, height
    return ReplayElevationUpdate(result_bits, has_tile and result == terrain)
