"""Saved player visibility and visible-resource records for DE save68.9.

Native readers: 0x141350ad0, 0x141355980 and 0x141356f30. These store
visibility state, not the world terrain. Outer player markers are left to
the caller. Unknown scalar meanings retain their exact saved bits.
"""

from __future__ import annotations

from dataclasses import dataclass

from vantage.replay_binary import SaveDecodeError, SaveReader


@dataclass(frozen=True, slots=True)
class SavedVisibleResource:
    fields: dict[int, int]
    raw: bytes


@dataclass(frozen=True, slots=True)
class SavedVisibleSlot:
    capacity: int
    entries: tuple[SavedVisibleResource, ...]


@dataclass(frozen=True, slots=True)
class SavedVisibility:
    offset: int
    end_offset: int
    width: int
    height: int
    word_28: int
    player_id: int
    cells_i16_le: bytes
    slots: tuple[SavedVisibleSlot, ...]
    raw: bytes


def _visible_resource(r: SaveReader) -> SavedVisibleResource:
    start = r.pos
    if r.u32() != 0x56524543:
        raise SaveDecodeError("invalid visible-resource magic", start)
    at = r.pos
    if r.u32() != 1:
        raise SaveDecodeError("unsupported visible-resource version", at)
    fields = {0xC: r.u32(), 0x10: r.u32(), 0x14: r.u8(), 0x18: r.u32(), 0x1C: r.u32()}
    return SavedVisibleResource(fields, r.data[start : r.pos])


def read_visibility(reader: SaveReader) -> SavedVisibility:
    """Read a map and manager, starting after their external PlayerMarker1.

    Slot allocation metadata is read for *all* slots before any entry data.
    A failed or unsupported read restores the original caller cursor.
    """
    start = reader.pos
    try:
        return _read_visibility(reader)
    except SaveDecodeError:
        reader.pos = start
        raise


def _read_visibility(r: SaveReader) -> SavedVisibility:
    start = r.pos
    if r.version != 0x44E666:
        raise SaveDecodeError(f"unsupported visibility save version {r.version:#x}", start)
    width, height, word, player = r.i32(), r.i32(), r.u32(), r.i16()
    if width < 0 or height < 0 or width * height > r.remaining // 2:
        raise SaveDecodeError(f"invalid visibility dimensions {width}x{height}", start)
    cells = r.take(width * height * 2)
    slot_count = r.count(item_size=8)
    headers = []
    total_used = 0
    for _ in range(slot_count):
        at = r.pos
        capacity, used = r.i32(), r.i32()
        if not 0 <= used <= capacity:
            raise SaveDecodeError(f"invalid visible slot capacity/used {capacity}/{used}", at)
        headers.append((capacity, used))
        total_used += used
    if total_used > r.remaining // 25:
        raise SaveDecodeError("truncated visible-resource entries", r.pos)
    slots = tuple(
        SavedVisibleSlot(capacity, tuple(_visible_resource(r) for _ in range(used)))
        for capacity, used in headers
    )
    return SavedVisibility(
        start, r.pos, width, height, word, player, cells, slots, r.data[start : r.pos]
    )
