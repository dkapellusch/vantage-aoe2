"""Structural save68.9 / format3 map and following world-state readers.

Native map141042c40 calls ZoneMap1414eaef0/1414ea680, additional141041fe0,
and visibility141352df0. World14160d710 then reads research141489430 and a
global word before its first player. See player-ai/saved-map artifacts.
Saved layer/mask fields remain raw: later native terrain rebuilds are separate.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from vantage.replay_binary import SaveDecodeError, SaveReader
from vantage.replay_map import slope_shapes


@dataclass(frozen=True, slots=True)
class SavedMapZone:
    offset: int
    end_offset: int
    counters: tuple[int, ...]
    grid_u16: bytes
    values: tuple[int, ...]
    zone_count_word: int
    raw: bytes


@dataclass(frozen=True, slots=True)
class SavedMapTile:
    terrain_type: int
    restore_terrain_type: int
    previous_terrain_type: int
    elevation: int
    mask_type: int
    layer: int
    previous_layer: int


@dataclass(frozen=True, slots=True)
class SavedMapAdditional:
    offset: int
    end_offset: int
    count: int
    capacity: int
    ids: tuple[int, ...]
    vectors: tuple[tuple[tuple[int, int], ...], ...]
    raw: bytes


@dataclass(frozen=True, slots=True)
class SavedMapVisibility:
    offset: int
    end_offset: int
    width: int
    height: int
    cells_u64: bytes
    raw: bytes


@dataclass(frozen=True, slots=True)
class SavedMap:
    offset: int
    end_offset: int
    format_version: int
    width: int
    height: int
    zones: tuple[SavedMapZone, ...]
    visible_flag: int
    fog_flag: int
    tile_offset: int
    tiles: tuple[SavedMapTile, ...]
    tile_bytes: bytes
    slopes: tuple[int, ...]
    additional: SavedMapAdditional
    visibility: SavedMapVisibility
    raw: bytes


@dataclass(frozen=True, slots=True)
class SavedPostMapWorld:
    offset: int
    end_offset: int
    load_flag: int
    conditional_word: int | None
    research_word: int
    research_count: int
    research_records_27: tuple[bytes, ...]
    global_word: int
    raw: bytes


def read_saved_map(reader: SaveReader) -> SavedMap:
    """Read the complete map starting at its DEADDEAD / format3 header.

    This leaves the following world research state untouched. Unsupported or
    truncated records restore the caller's cursor. No record scan is used.
    """
    start = reader.pos
    try:
        return _read_saved_map(reader)
    except SaveDecodeError:
        reader.pos = start
        raise


def _version(reader: SaveReader) -> None:
    if reader.version != 0x44E666:
        raise SaveDecodeError(f"unsupported map save version {reader.version:#x}", reader.pos)


def _zone(reader: SaveReader, cells: int) -> SavedMapZone:
    start = reader.pos
    # 1414ea680 modern >=0xbeb85:512 u32 counters and two bytes per map cell.
    counters = tuple(v[0] for v in struct.iter_unpack("<I", reader.take(512 * 4)))
    grid = reader.take(cells * 2)
    values = tuple(reader.u32() for _ in range(reader.count(item_size=4)))
    count_word = reader.u32()
    return SavedMapZone(
        start, reader.pos, counters, grid, values, count_word, reader.data[start : reader.pos]
    )


def _additional(reader: SaveReader) -> SavedMapAdditional:
    start = reader.pos
    count = reader.count(item_size=8)
    at = reader.pos
    capacity = reader.i32()
    if capacity < count:
        raise SaveDecodeError(f"map array capacity {capacity} below count {count}", at)
    ids = tuple(reader.u32() for _ in range(count))
    vectors = tuple(
        tuple((reader.u32(), reader.u32()) for _ in range(reader.count(item_size=8)))
        for _ in range(count)
    )
    return SavedMapAdditional(
        start, reader.pos, count, capacity, ids, vectors, reader.data[start : reader.pos]
    )


def _visibility(reader: SaveReader) -> SavedMapVisibility:
    start = reader.pos
    width, height = reader.i32(), reader.i32()
    if width < 0 or height < 0 or width * height > reader.remaining // 8:
        raise SaveDecodeError(f"invalid unified visibility size {width}x{height}", start)
    cells = reader.take(width * height * 8)
    return SavedMapVisibility(
        start, reader.pos, width, height, cells, reader.data[start : reader.pos]
    )


def _read_saved_map(reader: SaveReader) -> SavedMap:
    start = reader.pos
    _version(reader)
    magic, version = reader.u32(), reader.i32()
    if magic != 0xDEADDEAD or version != 3:
        raise SaveDecodeError(f"unsupported saved-map header {magic:#x}/format{version}", start)
    width, height = reader.i32(), reader.i32()
    cells = width * height
    if width <= 0 or height <= 0 or cells > reader.remaining // 10:
        raise SaveDecodeError(f"invalid saved-map size {width}x{height}", start + 8)
    zone_count = reader.count(item_size=2056 + 2 * cells)
    zones = tuple(_zone(reader, cells) for _ in range(zone_count))
    visible, fog = reader.u8(), reader.u8()
    tile_offset = reader.pos
    tile_bytes = reader.take(cells * 10)
    tiles = tuple(SavedMapTile(*values) for values in struct.iter_unpack("<BBBBhhh", tile_bytes))
    additional = _additional(reader)
    visibility = _visibility(reader)
    slopes = slope_shapes(tuple(t.elevation for t in tiles), width, height)
    return SavedMap(
        start,
        reader.pos,
        version,
        width,
        height,
        zones,
        visible,
        fog,
        tile_offset,
        tiles,
        tile_bytes,
        slopes,
        additional,
        visibility,
        reader.data[start : reader.pos],
    )


def read_post_map_world(reader: SaveReader, *, load_flag: int = 0) -> SavedPostMapWorld:
    """Read world state between the map and the first player factory byte.

    ``load_flag`` is the native World14160d710 fourth argument. A nonzero
    flag adds one u32 before research state. Both paired recordings use zero.
    Modern research entries are27 saved bytes, including their final flag.
    """
    start = reader.pos
    try:
        _version(reader)
        conditional = reader.u32() if load_flag != 0 else None
        research_word = reader.u32()
        at = reader.pos
        count = reader.i32()
        if count > reader.remaining // 27:
            raise SaveDecodeError(f"invalid saved world research count {count}", at)
        records = tuple(reader.take(27) for _ in range(max(0, count)))
        global_word = reader.u32()
        return SavedPostMapWorld(
            start,
            reader.pos,
            load_flag,
            conditional,
            research_word,
            count,
            records,
            global_word,
            reader.data[start : reader.pos],
        )
    except SaveDecodeError:
        reader.pos = start
        raise
