"""Native DE player object-list framing at save version 68.9.

The two allocation fields are capacity and growth increment, not a record
count. Records end at a zero type tag. This module starts after visibility
restoration and retains the final player trailer without normalizing it.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from vantage.replay_binary import SaveDecodeError, SaveReader
from vantage.replay_objects import SavedObject, read_saved_object

STAT_MODIFIER_NAMES = (
    "work_rate",
    "carry_capacity",
    "starting_resources",
    "villager_hp",
    "building_hp",
    "counter_unit_damage",
    "military_building_work_rate",
    "armor",
    "hero_regeneration_rate",
    "monk_convert_rate",
)


@dataclass(frozen=True, slots=True)
class SavedObjectList:
    offset: int
    end_offset: int
    capacity: int
    growth_increment: int
    objects: tuple[SavedObject, ...]
    terminator_offset: int
    raw: bytes


@dataclass(frozen=True, slots=True)
class SavedPlayerObjectTrailer:
    """Native WorldPlayer trailer; resource fields belong to its preset.

    These four resource integers are not the player's bank. Modifier words
    preserve their exact IEEE-754 bits, including non-finite representations.
    The raw presence and auto-farm bytes are retained rather than coerced.
    """

    offset: int
    end_offset: int
    have_stat_modifiers: int
    stat_modifier_bits: tuple[int, ...]
    preset_mask: int
    active_preset: int
    auto_farms: int
    wood: int
    food: int
    gold: int
    stone: int
    raw: bytes

    @property
    def stat_modifiers(self) -> tuple[float, ...]:
        return tuple(
            struct.unpack("<f", struct.pack("<I", word))[0] for word in self.stat_modifier_bits
        )


@dataclass(frozen=True, slots=True)
class SavedPlayerObjectLists:
    offset: int
    end_offset: int
    ordinary: SavedObjectList
    sleeping: SavedObjectList
    dopple: SavedObjectList
    trailer: SavedPlayerObjectTrailer
    raw: bytes


def _check_version(reader: SaveReader) -> None:
    if reader.version != 0x44E666:
        raise SaveDecodeError(
            f"unsupported object-list save version {reader.version:#x}", reader.pos
        )


def read_object_list(reader: SaveReader) -> SavedObjectList:
    """Read the allocation header, tagged objects and zero terminator.

    Native 0x14122b360 stores the first two i32s at list +0x14/+0x18.
    Neither value drives Python allocation or determines how many records
    are read. Unsupported object variants and truncations restore the cursor.
    The leading PlayerMarker1 belongs to the caller.
    """
    start = reader.pos
    try:
        _check_version(reader)
        capacity, growth = reader.i32(), reader.i32()
        objects: list[SavedObject] = []
        while True:
            at = reader.pos
            if reader.u8() == 0:
                break
            reader.pos = at
            objects.append(read_saved_object(reader))
        return SavedObjectList(
            start, reader.pos, capacity, growth, tuple(objects), at, reader.data[start : reader.pos]
        )
    except SaveDecodeError:
        reader.pos = start
        raise


def _read_trailer(reader: SaveReader) -> SavedPlayerObjectTrailer:
    # Native 0x1416f7980: >=25.21 modifier branch, >=26.21 extra three
    # modifier words, >=26.33 preset fields. All gates are true at 68.9.
    start = reader.pos
    reader.marker(11)
    present = reader.u8()
    modifiers = tuple(reader.u32() for _ in range(10)) if present else ()
    reader.marker(11)
    preset, active, farms = reader.i32(), reader.i32(), reader.u8()
    wood, food, gold, stone = reader.i32(), reader.i32(), reader.i32(), reader.i32()
    reader.marker(11)
    return SavedPlayerObjectTrailer(
        start,
        reader.pos,
        present,
        modifiers,
        preset,
        active,
        farms,
        wood,
        food,
        gold,
        stone,
        reader.data[start : reader.pos],
    )


def read_player_object_lists(reader: SaveReader) -> SavedPlayerObjectLists:
    """Read all three lists and the trailer from the initial marker11.

    Native 0x1416f7980 orders ordinary, sleeping and dopple lists, each with
    its own preceding marker. The final marker ends the trailer and leaves
    the following player factory byte untouched. Failure rolls back the
    entire group, including successfully decoded earlier lists.
    """
    start = reader.pos
    try:
        _check_version(reader)
        reader.marker(11)
        ordinary = read_object_list(reader)
        reader.marker(11)
        sleeping = read_object_list(reader)
        reader.marker(11)
        dopple = read_object_list(reader)
        trailer = _read_trailer(reader)
        return SavedPlayerObjectLists(
            start,
            reader.pos,
            ordinary,
            sleeping,
            dopple,
            trailer,
            reader.data[start : reader.pos],
        )
    except SaveDecodeError:
        reader.pos = start
        raise
