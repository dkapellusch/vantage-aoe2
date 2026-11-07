"""Bounded native build54800 terrain-class and selector scalar operations.

The caller supplies initialized TerrainType flags; the on-disk executable's
zero-filled global table is not a substitute. These helpers do not populate
object rectangles, infer occupancy, select a backend, or declare a route clear.
Sources:1414c4270,141627650,141076a60/141081970 and141121150.
"""

from __future__ import annotations

import struct
from collections.abc import Sequence


def _word(value: int, bits: int) -> None:
    if not isinstance(value, int) or not 0 <= value < 1 << bits:
        raise ValueError(f"path terrain requires an unsigned{bits} word")


def path_terrain_class(initialized_flags: int) -> int:
    """Original1414c4270: collapse TerrainType+0x2c flags to0,1,2 or4."""
    _word(initialized_flags, 32)
    if initialized_flags & 7:
        return 1
    if initialized_flags & 0x18:
        return 2
    return (initialized_flags >> 3) & 4


def build_path_terrain_selector(
    terrain_speed_words: Sequence[int], initialized_class_flags: Sequence[int]
) -> int:
    """OR class bits for each strictly positive native binary32 speed word.

    The parallel inputs are indexed by terrain ID. This bounded API supports
    at most256 terrain IDs, the full domain of native1414c4140's u8 lookup.
    NaNs, negative values and both zeros fail the original positive comparison.
    Class flags must come from the caller's build/mode-matched initialized
    table; a replay's restriction index alone does not determine this selector.
    """
    if len(terrain_speed_words) != len(initialized_class_flags) or len(terrain_speed_words) > 256:
        raise ValueError("path terrain arrays must have equal lengths of at most256")
    selector = 0
    for word, flags in zip(terrain_speed_words, initialized_class_flags, strict=True):
        _word(word, 32)
        _word(flags, 32)
        if struct.unpack("<f", struct.pack("<I", word))[0] > 0:
            selector |= path_terrain_class(flags)
    return selector


def path_terrain_query_mask(selector_word: int) -> int:
    """Original141076a60/141081970: XOR low8 bits, then sign-extend i32."""
    _word(selector_word, 32)
    value = selector_word ^ 0xFF
    return value - (1 << 32) if value & (1 << 31) else value


def replace_path_terrain_class(cell_word: int, initialized_flags: int) -> int:
    """Original141121150's scalar assignment, preserving all high56 cell bits.

    The caller owns the native World+0x88==0 applicability gate, terrain-cell
    selection, refresh callbacks and object occupancy. This operation only
    replaces the low byte; it does not clear any object ownership/status bits.
    """
    _word(cell_word, 64)
    return (cell_word & 0xFFFFFFFFFFFFFF00) | path_terrain_class(initialized_flags)
