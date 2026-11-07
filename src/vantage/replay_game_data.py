"""Bounded envelope reader for the installed game's own binary DAT archive.

The owned build 54800 base and Pompeii archives are single raw-DEFLATE streams
whose inflated bytes begin with the eight-byte version tag ``VER 8.9\0``.
The sequential native-derived readers cover terrain restrictions,
colors, sounds, graphics, map/terrain definitions, effects, global task lists
complete civilization/master records and the research/configuration tail.
Saved override merging, runtime initialization and build/mode identity remain
separate work.
"""

from __future__ import annotations

import hashlib
import zlib
from dataclasses import dataclass

from vantage.replay_binary import SaveDecodeError, SaveReader
from vantage.replay_masters import SavedMasterTask, read_master_task

_VERSION = b"VER 8.9\0"
_MAX_INFLATED_BYTES = 128 * 1024 * 1024


class GameDataDecodeError(ValueError):
    """Invalid, unsupported or oversized compressed game-data envelope."""


@dataclass(frozen=True, slots=True)
class GameDataEnvelope:
    version_bytes: bytes
    data: bytes
    compressed_size: int
    compressed_sha256: str
    data_sha256: str

    @property
    def definition_offset(self) -> int:
        """The first byte after the native eight-byte version tag."""
        return len(self.version_bytes)


@dataclass(frozen=True, slots=True)
class GameDataTerrainRestriction:
    offset: int
    end_offset: int
    terrain_words: tuple[int, ...]
    records_16: tuple[bytes, ...]
    raw: bytes


@dataclass(frozen=True, slots=True)
class GameDataTerrainRestrictions:
    offset: int
    end_offset: int
    restriction_count: int
    terrain_count: int
    first_placeholders: tuple[int, ...]
    second_placeholders: tuple[int, ...]
    restrictions: tuple[GameDataTerrainRestriction, ...]
    sections: dict[str, bytes]
    raw: bytes


@dataclass(frozen=True, slots=True)
class GameDataColor:
    offset: int
    end_offset: int
    fields: dict[int, int]
    raw: bytes


@dataclass(frozen=True, slots=True)
class GameDataColors:
    offset: int
    end_offset: int
    count: int
    colors: tuple[GameDataColor, ...]
    raw: bytes


@dataclass(frozen=True, slots=True)
class GameDataSoundItem:
    offset: int
    end_offset: int
    filename_bytes: bytes
    word32: int
    words16: tuple[int, int, int]
    raw: bytes


@dataclass(frozen=True, slots=True)
class GameDataSound:
    offset: int
    end_offset: int
    id_bits: int
    word16: int
    item_count: int
    word32: int
    total_probability_bits: int
    items: tuple[GameDataSoundItem, ...]
    raw: bytes


@dataclass(frozen=True, slots=True)
class GameDataSounds:
    offset: int
    end_offset: int
    count: int
    sounds: tuple[GameDataSound, ...]
    raw: bytes


@dataclass(frozen=True, slots=True)
class GameDataGraphicSound:
    offset: int
    end_offset: int
    words: tuple[int, int, int]
    raw: bytes


@dataclass(frozen=True, slots=True)
class GameDataGraphic:
    offset: int
    end_offset: int
    strings: tuple[bytes, bytes, bytes]
    fields: dict[int, int]
    sound_id_bits: int
    deltas_16: tuple[bytes, ...]
    sound_rows: tuple[tuple[GameDataGraphicSound, ...], ...]
    raw: bytes


@dataclass(frozen=True, slots=True)
class GameDataGraphics:
    offset: int
    end_offset: int
    body_offset: int
    count: int
    placeholders: tuple[int, ...]
    graphics: dict[int, GameDataGraphic]
    sections: dict[str, bytes]
    raw: bytes


@dataclass(frozen=True, slots=True)
class GameDataTileSet:
    offset: int
    end_offset: int
    string_bytes: tuple[bytes, bytes, bytes]
    fields: dict[int, int]
    ptr32_bits: int
    tile_geometry: bytes
    object_arrays16: dict[int, tuple[int, ...]]
    object_placement: tuple[int, ...]
    padding: bytes
    raw: bytes


@dataclass(frozen=True, slots=True)
class GameDataMap:
    """DAT map defaults; this is separate from the replay's initial tile grid."""

    offset: int
    end_offset: int
    ignored_prefix: bytes
    dimension_words: tuple[int, ...]
    tile_size_bytes: bytes
    header_padding: bytes
    terrain_sets: tuple[GameDataTileSet, ...]
    bounds_words: tuple[int, ...]
    valid_terrain_count: int
    tail_words16: tuple[int, ...]
    tail_padding: bytes
    tail_flags: tuple[int, int, int]
    derived_bytes: bytes
    sections: dict[str, bytes]
    raw: bytes


@dataclass(frozen=True, slots=True)
class GameDataEffectCommand:
    offset: int
    end_offset: int
    kind: int
    words16: tuple[int, int, int]
    value_bits: int
    raw: bytes


@dataclass(frozen=True, slots=True)
class GameDataEffect:
    offset: int
    end_offset: int
    name_bytes: bytes
    command_count: int
    commands: tuple[GameDataEffectCommand, ...]
    raw: bytes


@dataclass(frozen=True, slots=True)
class GameDataEffects:
    offset: int
    end_offset: int
    count: int
    effects: tuple[GameDataEffect, ...]
    raw: bytes


@dataclass(frozen=True, slots=True)
class GameDataTaskList:
    offset: int
    end_offset: int
    task_count: int
    tasks: tuple[SavedMasterTask, ...]
    raw: bytes


@dataclass(frozen=True, slots=True)
class GameDataTasks:
    offset: int
    end_offset: int
    count: int
    presence: tuple[int, ...]
    task_lists: dict[int, GameDataTaskList]
    raw: bytes


@dataclass(frozen=True, slots=True)
class GameDataCivilizationPrefix:
    """One civilization's header and presence table, before any master body."""

    offset: int
    end_offset: int
    type_id: int
    name_bytes: bytes
    resource_count: int
    fields16: dict[int, int]
    resource_words: tuple[int, ...]
    field40_bits: int
    master_count: int
    placeholders: tuple[int, ...]
    sections: dict[str, bytes]
    raw: bytes


@dataclass(frozen=True, slots=True)
class GameDataMasterResource:
    offset: int
    end_offset: int
    type_bits: int
    amount_bits: int
    flag: int
    raw: bytes


@dataclass(frozen=True, slots=True)
class GameDataMasterDamageSprite:
    offset: int
    end_offset: int
    sprite_bits: int
    threshold: int
    word8: int
    flag: int
    raw: bytes


@dataclass(frozen=True, slots=True)
class GameDataMasterCommon:
    """Serialized common DAT body, before any type-specific additions."""

    offset: int
    end_offset: int
    fields: dict[int, int]
    string_word32: int
    string_bytes: bytes
    resources: tuple[GameDataMasterResource, ...]
    damage_sprites: tuple[GameDataMasterDamageSprite, ...]
    sound_numbers: dict[int, int]
    sound_events: dict[int, int]
    name_bytes: bytes
    sections: dict[str, bytes]
    raw: bytes


@dataclass(frozen=True, slots=True)
class GameDataMaster:
    """One complete DAT master before runtime reference and task installation."""

    offset: int
    end_offset: int
    type_group: int
    common: GameDataMasterCommon
    fields: dict[int, int]
    sprite_id_bits: dict[int, int]
    sound_numbers: dict[int, int]
    sound_events: dict[int, int]
    action_sprite_bits: tuple[int, ...]
    tasks: tuple[SavedMasterTask, ...]
    combat_pairs: dict[int, tuple[tuple[int, int], ...]]
    cost_records_6: tuple[bytes, ...]
    definition_records_9: tuple[bytes, ...]
    building_piece_records_10: tuple[bytes, ...]
    sections: dict[str, bytes]
    raw: bytes


@dataclass(frozen=True, slots=True)
class GameDataCivilization:
    offset: int
    end_offset: int
    prefix: GameDataCivilizationPrefix
    masters: dict[int, GameDataMaster]
    raw: bytes


@dataclass(frozen=True, slots=True)
class GameDataResearchCost:
    offset: int
    end_offset: int
    type_bits: int
    amount_bits: int
    flag: int
    raw: bytes


@dataclass(frozen=True, slots=True)
class GameDataResearchLocation:
    offset: int
    end_offset: int
    first16_bits: int
    second16_bits: int
    word8: int
    word32: int
    raw: bytes


@dataclass(frozen=True, slots=True)
class GameDataResearchDefinition:
    offset: int
    end_offset: int
    prerequisite_bits: tuple[int, ...]
    costs: tuple[GameDataResearchCost, ...]
    fields: dict[int, int]
    name_bytes: bytes
    locations: tuple[GameDataResearchLocation, ...]
    sections: dict[str, bytes]
    raw: bytes


@dataclass(frozen=True, slots=True)
class GameDataResearchCatalog:
    offset: int
    end_offset: int
    count: int
    definitions: tuple[GameDataResearchDefinition, ...]
    raw: bytes


@dataclass(frozen=True, slots=True)
class GameDataConfigurationRecord:
    offset: int
    end_offset: int
    group: int
    header_bytes: bytes
    array_words: tuple[tuple[int, ...], ...]
    tail_bytes: bytes
    raw: bytes


@dataclass(frozen=True, slots=True)
class GameDataConfiguration:
    offset: int
    end_offset: int
    counts: tuple[int, int, int, int]
    extra_bits: int
    groups: tuple[tuple[GameDataConfigurationRecord, ...], ...]
    raw: bytes


@dataclass(frozen=True, slots=True)
class GameDataTail:
    offset: int
    end_offset: int
    research: GameDataResearchCatalog
    world_words: tuple[int, ...]
    configuration: GameDataConfiguration
    sections: dict[str, bytes]
    raw: bytes


def _data_research_definition(reader: SaveReader) -> GameDataResearchDefinition:
    start = reader.pos
    prerequisites = tuple(reader.u16() for _ in range(6))
    sections = {"prerequisites": reader.data[start : reader.pos]}
    at = reader.pos
    costs = []
    for _ in range(3):
        cost_at = reader.pos
        type_bits, amount_bits, flag = reader.u16(), reader.u16(), reader.u8()
        costs.append(
            GameDataResearchCost(
                cost_at, reader.pos, type_bits, amount_bits, flag, reader.data[cost_at : reader.pos]
            )
        )
    sections["costs"] = reader.data[at : reader.pos]
    at = reader.pos
    fields = {offset: reader.u16() for offset in (0x24, 0x26, 0x28)}
    fields.update({offset: reader.u32() for offset in (0x40, 0x44)})
    fields.update({offset: reader.u16() for offset in (0x3A, 0x3C, 0x3E)})
    fields.update({offset: reader.u32() for offset in (0x4C, 0x68)})
    sections["scalar_words"] = reader.data[at : reader.pos]
    at = reader.pos
    name = reader.de_bytes()
    fields[0x6C] = reader.u8()
    sections["name_and_flag"] = reader.data[at : reader.pos]
    at = reader.pos
    count = reader.i16()
    if not 0 <= count <= reader.remaining // 9:
        raise SaveDecodeError(f"invalid data research location count {count}", at)
    locations = []
    for _ in range(count):
        location_at = reader.pos
        first, second, byte, word = reader.u16(), reader.u16(), reader.u8(), reader.u32()
        locations.append(
            GameDataResearchLocation(
                location_at,
                reader.pos,
                first,
                second,
                byte,
                word,
                reader.data[location_at : reader.pos],
            )
        )
    sections["locations"] = reader.data[at : reader.pos]
    return GameDataResearchDefinition(
        start,
        reader.pos,
        prerequisites,
        tuple(costs),
        fields,
        name,
        tuple(locations),
        sections,
        reader.data[start : reader.pos],
    )


def read_game_data_research_catalog(reader: SaveReader) -> GameDataResearchCatalog:
    """Read native0x14148ed00 research definitions after the civilizations.

    Current DAT67.9 uses six prerequisites, three5-byte cost records, u32
    language words, a DE name, one flag and counted9-byte location records.
    The old single-location fields are absent at version>=0x41b333.
    Each record occupies62+name_length+9*location_count serialized bytes.
    """
    start = reader.pos
    try:
        if reader.version != 0x43E666:
            raise SaveDecodeError(f"unsupported research data version {reader.version:#x}", start)
        count = reader.i16()
        if not 0 <= count <= reader.remaining // 62:
            raise SaveDecodeError(f"invalid data research count {count}", start)
        definitions = tuple(_data_research_definition(reader) for _ in range(count))
        return GameDataResearchCatalog(
            start, reader.pos, count, definitions, reader.data[start : reader.pos]
        )
    except SaveDecodeError:
        reader.pos = start
        raise


def read_game_data_configuration(reader: SaveReader) -> GameDataConfiguration:
    """Read the final four-group native0x1414aea70 configuration table.

    The DAT version global selects its modern branches at internal67.9.
    Counts are u8,u8,u16,u8, followed by one u32 word. Record headers,
    counted word arrays and fixed tails remain raw rather than acquiring
    unverified meanings from the runtime's derived configuration structures.
    """
    start = reader.pos
    try:
        if reader.version != 0x43E666:
            raise SaveDecodeError(
                f"unsupported configuration data version {reader.version:#x}", start
            )
        counts = (reader.u8(), reader.u8(), reader.u16(), reader.u8())
        extra = reader.u32()
        minimum_sizes = (118, 111, 114, 108)
        if (
            sum(count * size for count, size in zip(counts, minimum_sizes, strict=True))
            > reader.remaining
        ):
            raise SaveDecodeError(f"invalid data configuration counts {counts}", start)
        groups = []
        for group, count in enumerate(counts):
            records = []
            for _ in range(count):
                at = reader.pos
                header = reader.take((5, 5, 97, 9)[group])
                arrays = []
                for _ in range(1 if group == 2 else 3):
                    count_at = reader.pos
                    words = reader.u8()
                    if words > reader.remaining // 4:
                        raise SaveDecodeError(
                            f"invalid data configuration word count {words}", count_at
                        )
                    arrays.append(tuple(reader.u32() for _ in range(words)))
                tail = reader.take((110, 103, 16, 96)[group])
                records.append(
                    GameDataConfigurationRecord(
                        at,
                        reader.pos,
                        group,
                        header,
                        tuple(arrays),
                        tail,
                        reader.data[at : reader.pos],
                    )
                )
            groups.append(tuple(records))
        return GameDataConfiguration(
            start, reader.pos, counts, extra, tuple(groups), reader.data[start : reader.pos]
        )
    except SaveDecodeError:
        reader.pos = start
        raise


def read_game_data_tail(reader: SaveReader) -> GameDataTail:
    """Read the complete current DAT suffix and require exact inflated EOF.

    Start immediately after the last civilization. Native0x141699240 reads
    the research catalog, seven u32 world words and the configuration table.
    No effects, derived runtime initialization or replay-default merging run.
    """
    start = reader.pos
    try:
        research = read_game_data_research_catalog(reader)
        at = reader.pos
        words = tuple(reader.u32() for _ in range(7))
        words_raw = reader.data[at : reader.pos]
        configuration = read_game_data_configuration(reader)
        if reader.remaining:
            raise SaveDecodeError("trailing bytes after data tail", reader.pos)
        return GameDataTail(
            start,
            reader.pos,
            research,
            words,
            configuration,
            {
                "research": research.raw,
                "world_words": words_raw,
                "configuration": configuration.raw,
            },
            reader.data[start : reader.pos],
        )
    except SaveDecodeError:
        reader.pos = start
        raise


_MASTER_MOVING_SCALARS = (
    (0x1E8, 2),
    (0x1F0, 2),
    (0x1F8, 4),
    (0x1FC, 1),
    (0x1FE, 2),
    (0x200, 1),
    (0x204, 4),
    (0x208, 1),
    (0x20C, 4),
    (0x210, 4),
    (0x214, 4),
    (0x218, 4),
    (0x21C, 4),
    (0x220, 4),
)
_MASTER_COMBAT_SCALARS = (
    (0x2C0, 2),
    (0x2C4, 4),
    (0x2C8, 4),
    (0x2CC, 4),
    (0x2D8, 4),
    (0x2DC, 2),
    (0x2DE, 2),
    (0x2E0, 1),
    (0x2E2, 2),
    (0x2E4, 4),
    (0x2E8, 4),
    (0x2EC, 4),
    (0x2D0, 1),
    (0x2F0, 4),
    (0x300, 4),
    (0x298, 2),
    (0x2F4, 2),
    (0x2F6, 2),
    (0x2F8, 4),
    (0x2FC, 4),
    (0x2D4, 4),
    (0x304, 4),
    (0x308, 4),
    (0x30C, 2),
    (0x310, 4),
    (0x318, 2),
)
_MASTER_UNIT_SCALARS = (
    (0x354, 4),
    (0x358, 4),
    (0x35C, 1),
    (0x379, 1),
    (0x390, 4),
    (0x398, 2),
    (0x3A0, 2),
    (0x3A8, 2),
    (0x3B0, 2),
    (0x3B8, 4),
    (0x3BC, 4),
    (0x3C0, 2),
    (0x3C2, 2),
    (0x3C4, 2),
    (0x3C8, 4),
    (0x3CC, 1),
    (0x3D0, 4),
    (0x37A, 2),
    (0x37C, 4),
    (0x380, 4),
    (0x384, 2),
    (0x3D4, 4),
    (0x3D8, 4),
    (0x3DC, 4),
    (0x360, 4),
    (0x364, 1),
    (0x368, 4),
    (0x36C, 4),
    (0x370, 4),
    (0x374, 4),
    (0x388, 4),
    (0x378, 1),
    (0x350, 2),
)


def _data_master(reader: SaveReader) -> GameDataMaster:
    start = reader.pos
    kind = reader.u8()
    if kind not in (10, 15, 20, 25, 30, 40, 50, 60, 70, 80):
        raise SaveDecodeError(f"unsupported data master type {kind}", start)
    common = _master_common(reader)
    fields: dict[int, int] = {}
    sprites: dict[int, int] = {}
    numbers: dict[int, int] = {}
    events: dict[int, int] = {}
    action_sprites: tuple[int, ...] = ()
    tasks: tuple[SavedMasterTask, ...] = ()
    pairs: dict[int, tuple[tuple[int, int], ...]] = {}
    costs: tuple[bytes, ...] = ()
    definitions: tuple[bytes, ...] = ()
    pieces: tuple[bytes, ...] = ()
    sections = {"factory_type": reader.data[start : start + 1], "common": common.raw}

    def scalars(layout: tuple[tuple[int, int], ...]) -> None:
        for offset, size in layout:
            fields[offset] = int.from_bytes(reader.take(size), "little")

    def count(item_size: int, label: str) -> int:
        at = reader.pos
        value = reader.i16()
        if not 0 <= value <= reader.remaining // item_size:
            raise SaveDecodeError(f"invalid data master {label} count {value}", at)
        return value

    if kind not in (10, 15):
        at = reader.pos
        scalars(((0x1E0, 4),))
        sections["animated20"] = reader.data[at : reader.pos]
    if kind in (30, 40, 50, 60, 70, 80):
        at = reader.pos
        scalars(_MASTER_MOVING_SCALARS)
        sprites.update({offset: fields[offset] for offset in (0x1E8, 0x1F0)})
        sections["moving30"] = reader.data[at : reader.pos]
    if kind in (40, 50, 60, 70, 80):
        at = reader.pos
        scalars(((0x230, 2), (0x234, 4), (0x238, 4)))
        action_sprites = tuple(reader.u16() for _ in range(count(2, "action sprite")))
        scalars(((0x258, 1),))
        numbers.update({offset: reader.u16() for offset in (0x260, 0x278)})
        events.update({offset: reader.u32() for offset in (0x260, 0x278)})
        scalars(((0x259, 1),))
        tasks = tuple(read_master_task(reader) for _ in range(count(69, "task")))
        sections["action40"] = reader.data[at : reader.pos]
    if kind in (50, 60, 70, 80):
        at = reader.pos
        scalars(((0x2A0, 2),))
        for offset in (0x2B0, 0x2A2):
            pairs[offset] = tuple(
                (reader.u16(), reader.u16()) for _ in range(count(4, "combat pair"))
            )
        scalars(_MASTER_COMBAT_SCALARS)
        sprites.update({offset: fields[offset] for offset in (0x298, 0x318)})
        sections["combat50"] = reader.data[at : reader.pos]
    if kind == 60:
        at = reader.pos
        scalars(((0x320, 1), (0x321, 1), (0x322, 1), (0x323, 1), (0x324, 1), (0x328, 4)))
        sections["projectile60"] = reader.data[at : reader.pos]
    if kind in (70, 80):
        at = reader.pos
        costs = tuple(reader.take(6) for _ in range(3))
        definitions = tuple(reader.take(9) for _ in range(count(9, "definition")))
        scalars(_MASTER_UNIT_SCALARS)
        sprites.update(
            {offset: fields[offset] for offset in (0x390, 0x398, 0x3A0, 0x3A8, 0x3B0, 0x388)}
        )
        sections["unit70"] = reader.data[at : reader.pos]
    if kind == 80:
        at = reader.pos
        graphics = (0x3F0, 0x3F8, 0x400, 0x408, 0x410, 0x418)
        scalars(tuple((offset, 2) for offset in graphics))
        sprites.update({offset: fields[offset] for offset in graphics})
        scalars(
            (
                (0x420, 1),
                (0x422, 2),
                (0x424, 1),
                (0x426, 2),
                (0x428, 2),
                (0x42A, 2),
                (0x42C, 2),
                (0x42E, 1),
            )
        )
        pieces_list = []
        for index in range(4):
            piece_at = reader.pos
            scalars(((0x430 + 2 * index, 2), (0x438 + 4 * index, 4), (0x448 + 4 * index, 4)))
            pieces_list.append(reader.data[piece_at : reader.pos])
        pieces = tuple(pieces_list)
        scalars(((0x458, 2), (0x45A, 2)))
        numbers.update({offset: reader.u16() for offset in (0x488, 0x470)})
        events.update({offset: reader.u32() for offset in (0x488, 0x470)})
        scalars(((0x45C, 1), (0x460, 4), (0x464, 4), (0x468, 2)))
        scalars(tuple((offset, 1) for offset in range(0x46A, 0x470)))
        sections["building80"] = reader.data[at : reader.pos]
    return GameDataMaster(
        start,
        reader.pos,
        kind,
        common,
        fields,
        sprites,
        numbers,
        events,
        action_sprites,
        tasks,
        pairs,
        costs,
        definitions,
        pieces,
        sections,
        reader.data[start : reader.pos],
    )


def read_game_data_master(reader: SaveReader) -> GameDataMaster:
    """Read one complete native DAT master, including its u8 factory type.

    Only internal67.9 is established. The supported factory groups are
    10,15,20,25,30,40,50,60,70,80. Modern action masters serialize their own
    TaskList; these records remain separate from the earlier global task table.
    No sprite/sound lookup, default-task installation or other runtime fixup runs.
    """
    start = reader.pos
    try:
        if reader.version != 0x43E666:
            raise SaveDecodeError(f"unsupported master data version {reader.version:#x}", start)
        return _data_master(reader)
    except SaveDecodeError:
        reader.pos = start
        raise


def read_game_data_civilization(reader: SaveReader) -> GameDataCivilization:
    """Read one complete civilization after the outer u16 civilization count.

    Keys retain their presence-table index even if a serialized ID differs.
    This can be called sequentially without retaining every civilization at once.
    """
    start = reader.pos
    try:
        prefix = read_game_data_civilization_prefix(reader)
        masters = {}
        for index, value in enumerate(prefix.placeholders):
            if value:
                at = reader.pos
                if prefix.type_id == 0 and reader.remaining and reader.data[at] in (15, 70, 80):
                    raise SaveDecodeError("unsupported master group in base civilization", at)
                masters[index] = read_game_data_master(reader)
        return GameDataCivilization(
            start, reader.pos, prefix, masters, reader.data[start : reader.pos]
        )
    except SaveDecodeError:
        reader.pos = start
        raise


_MASTER_COMMON_SCALARS = (
    (0x18, 2),
    (0x0C, 4),
    (0x10, 4),
    (0x38, 2),
    (0x40, 2),
    (0x48, 2),
    (0x50, 2),
    (0x58, 2),
    (0x60, 1),
    (0x68, 2),
    (0x70, 4),
    (0x74, 1),
    (0x78, 4),
    (0x7C, 4),
    (0x80, 4),
    (0x158, 2),
    (0x1A0, 2),
    (0x84, 2),
    (0x86, 2),
    (0x88, 1),
    (0x89, 1),
    (0x8A, 2),
    (0x8C, 1),
    (0x8E, 2),
    (0x90, 1),
    (0x91, 1),
    (0x92, 2),
    (0x94, 2),
    (0x96, 2),
    (0x98, 2),
    (0x9C, 4),
    (0xA0, 4),
    (0xA4, 1),
    (0xA5, 1),
    (0xA6, 2),
    (0xA8, 1),
    (0xBC, 2),
    (0xC0, 4),
    (0xCB, 1),
    (0xCC, 1),
    (0xCD, 1),
    (0xCE, 1),
    (0xCF, 1),
    (0xC4, 4),
    (0xD0, 1),
    (0xFC, 4),
    (0x118, 4),
    (0x120, 1),
    (0x121, 1),
    (0x122, 1),
    (0x123, 1),
    (0xF0, 1),
    (0xF1, 1),
    (0xF2, 1),
    (0xF4, 4),
    (0x124, 1),
    (0x125, 1),
    (0x128, 4),
    (0x12C, 4),
    (0x130, 4),
)


def _master_common(reader: SaveReader) -> GameDataMasterCommon:
    start = reader.pos
    fields = {
        offset: int.from_bytes(reader.take(size), "little")
        for offset, size in _MASTER_COMMON_SCALARS
    }
    sections = {"scalar_prefix": reader.data[start : reader.pos]}
    at = reader.pos
    word = reader.u32()
    size_offset = reader.pos
    size = reader.u32()
    if size > 0x2800 or size > reader.remaining:
        raise SaveDecodeError(f"invalid data master string size {size}", size_offset)
    string = reader.take(size)
    if string and string[-1] != 0:
        raise SaveDecodeError("unterminated data master string", size_offset)
    sections["string"] = reader.data[at : reader.pos]
    at = reader.pos
    resources = []
    for _ in range(3):
        resource_at = reader.pos
        type_bits, amount, flag = reader.u16(), reader.u32(), reader.u8()
        resources.append(
            GameDataMasterResource(
                resource_at,
                reader.pos,
                type_bits,
                amount,
                flag,
                reader.data[resource_at : reader.pos],
            )
        )
    sections["resources"] = reader.data[at : reader.pos]
    at = reader.pos
    count_offset = reader.pos
    count = reader.u8()
    if count > reader.remaining // 5:
        raise SaveDecodeError(f"invalid data damage sprite count {count}", count_offset)
    sprites = []
    for _ in range(count):
        sprite_at = reader.pos
        sprite, threshold, word8, flag = reader.u16(), reader.u8(), reader.u8(), reader.u8()
        sprites.append(
            GameDataMasterDamageSprite(
                sprite_at,
                reader.pos,
                sprite,
                threshold,
                word8,
                flag,
                reader.data[sprite_at : reader.pos],
            )
        )
    sections["damage_sprites"] = reader.data[at : reader.pos]
    at = reader.pos
    numbers = {offset: fields[offset] for offset in (0x158, 0x1A0)}
    numbers.update({offset: reader.u16() for offset in (0x188, 0x170)})
    events = {offset: reader.u32() for offset in (0x158, 0x1A0, 0x188, 0x170)}
    fields.update({offset: reader.u8() for offset in (0xD1, 0xD2)})
    sections["sound_and_flags"] = reader.data[at : reader.pos]
    at = reader.pos
    name = reader.de_bytes()
    fields.update({offset: reader.u16() for offset in (0x20, 0x28)})
    sections["name_and_ids"] = reader.data[at : reader.pos]
    return GameDataMasterCommon(
        start,
        reader.pos,
        fields,
        word,
        string,
        tuple(resources),
        tuple(sprites),
        numbers,
        events,
        name,
        sections,
        reader.data[start : reader.pos],
    )


def read_game_data_master_common(reader: SaveReader) -> GameDataMasterCommon:
    """Read the complete native0x1411ec5a0 common DAT master body.

    Start after the external u8 master type. This consumes only the common
    part; derived readers may follow. Raw destination bits precede runtime
    obfuscation, clamping, string normalization and graphic/sound resolution.
    DAT67.9 skips the old native+0x11c float and uses a DE name, two u32
    language words and four u32 sound-event words.
    """
    start = reader.pos
    try:
        if reader.version != 0x43E666:
            raise SaveDecodeError(
                f"unsupported common master data version {reader.version:#x}", start
            )
        return _master_common(reader)
    except SaveDecodeError:
        reader.pos = start
        raise


def read_game_data_civilization_prefix(reader: SaveReader) -> GameDataCivilizationPrefix:
    """Read one DAT civilization prefix after the outer u16 civilization count.

    Native0x141340e20 reads the name, signed resource count, two u16 fields,
    resource words and one u8 field.0x141342610 then reads a signed master
    count and its up-front u32 presence table. This stops before the first
    present master body; callers must parse those bodies before another prefix.
    Types0/1 share these readers; their later master dispatch differs.
    """
    start = reader.pos
    try:
        if reader.version != 0x43E666:
            raise SaveDecodeError(
                f"unsupported civilization data version {reader.version:#x}", start
            )
        type_id = reader.u8()
        if type_id not in (0, 1):
            raise SaveDecodeError(f"unsupported data civilization type {type_id}", start)
        name = reader.de_bytes()
        count_offset = reader.pos
        resource_count = reader.i16()
        fields = {0x42: reader.u16(), 0x44: reader.u16()}
        if not 0 <= resource_count <= reader.remaining // 4:
            raise SaveDecodeError(f"invalid data resource count {resource_count}", count_offset)
        resource_start = reader.pos
        words = tuple(reader.u32() for _ in range(resource_count))
        resource_end = reader.pos
        field40 = reader.u8()
        header_end = reader.pos
        count_offset = reader.pos
        master_count = reader.i16()
        if not 0 <= master_count <= reader.remaining // 4:
            raise SaveDecodeError(
                f"invalid data civilization master count {master_count}", count_offset
            )
        placeholders = tuple(reader.u32() for _ in range(master_count))
        return GameDataCivilizationPrefix(
            start,
            reader.pos,
            type_id,
            name,
            resource_count,
            fields,
            words,
            field40,
            master_count,
            placeholders,
            {
                "header": reader.data[start:header_end],
                "resource_words": reader.data[resource_start:resource_end],
                "master_presence": reader.data[header_end : reader.pos],
            },
            reader.data[start : reader.pos],
        )
    except SaveDecodeError:
        reader.pos = start
        raise


def read_game_data_tasks(reader: SaveReader) -> GameDataTasks:
    """Read the baseline TaskList table after effects, without runtime fixups.

    Native0x141608330 interleaves each u8 presence value with its list body.
    0x141269730 reads an i16 task count; each entry has a u16 factory tag and
    the common0x14112f920 body. Internal DAT67.9 takes both historical gates,
    so the established69-byte task primitive applies to this exact profile.
    """
    start = reader.pos
    try:
        if reader.version != 0x43E666:
            raise SaveDecodeError(f"unsupported task data version {reader.version:#x}", start)
        count = reader.i32()
        if not 0 <= count <= reader.remaining:
            raise SaveDecodeError(f"invalid data task table count {count}", start)
        presence = []
        lists = {}
        for index in range(count):
            value = reader.u8()
            presence.append(value)
            if value:
                at = reader.pos
                task_count = reader.i16()
                if not 0 <= task_count <= reader.remaining // 69:
                    raise SaveDecodeError(f"invalid data task list count {task_count}", at)
                tasks = tuple(read_master_task(reader) for _ in range(task_count))
                lists[index] = GameDataTaskList(
                    at, reader.pos, task_count, tasks, reader.data[at : reader.pos]
                )
        return GameDataTasks(
            start, reader.pos, count, tuple(presence), lists, reader.data[start : reader.pos]
        )
    except SaveDecodeError:
        reader.pos = start
        raise


def _effect_command(reader: SaveReader) -> GameDataEffectCommand:
    start = reader.pos
    kind = reader.u8()
    words = (reader.u16(), reader.u16(), reader.u16())
    value = reader.u32()
    return GameDataEffectCommand(
        start, reader.pos, kind, words, value, reader.data[start : reader.pos]
    )


def _effect(reader: SaveReader) -> GameDataEffect:
    start = reader.pos
    name = reader.de_bytes()
    count = reader.i16()
    if not 0 <= count <= reader.remaining // 11:
        raise SaveDecodeError(f"invalid data effect command count {count}", reader.pos - 2)
    commands = tuple(_effect_command(reader) for _ in range(count))
    return GameDataEffect(start, reader.pos, name, count, commands, reader.data[start : reader.pos])


def read_game_data_effects(reader: SaveReader) -> GameDataEffects:
    """Read the native0x140fa3870 effect table after the DAT map definitions.

    The table has an i32 count, then DE names and i16 command counts.
    Each command has11 serialized bytes, despite12-byte native allocation:
    u8 kind, three u16 words and one u32 value. Effects are preserved without
    assigning unverified command meanings or applying any balance changes.
    """
    start = reader.pos
    try:
        if reader.version != 0x43E666:
            raise SaveDecodeError(f"unsupported effect data version {reader.version:#x}", start)
        count = reader.i32()
        if not 0 <= count <= reader.remaining // 6:
            raise SaveDecodeError(f"invalid data effect count {count}", start)
        effects = tuple(_effect(reader) for _ in range(count))
        return GameDataEffects(start, reader.pos, count, effects, reader.data[start : reader.pos])
    except SaveDecodeError:
        reader.pos = start
        raise


_TILE_SET_SCALARS = (
    (0x68, 1),
    (0x69, 1),
    (0x6A, 1),
    (0x6B, 1),
    (0x6C, 1),
    (0x6D, 1),
    (0x6E, 1),
    (0x6F, 1),
    (0x70, 2),
    (0x72, 2),
    (0x74, 4),
    (0x78, 4),
    (0x7C, 2),
    (0x7E, 2),
    (0x80, 4),
    (0x84, 1),
    (0x85, 1),
)


def _terrain_set(reader: SaveReader) -> GameDataTileSet:
    start = reader.pos
    fields = {offset: reader.u8() for offset in range(4)}
    fields[4] = reader.u32()
    name, resource = reader.de_bytes(), reader.de_bytes()
    fields[0x50] = reader.u32()
    pointer = reader.u32()
    fields.update((offset, reader.u32()) for offset in (0x5C, 0x54, 0x58, 0x60, 0x64))
    overlay = reader.de_bytes()
    fields.update(
        (offset, int.from_bytes(reader.take(width), "little"))
        for offset, width in _TILE_SET_SCALARS
    )
    geometry = reader.take(0x72)
    fields.update((offset, reader.u16()) for offset in (0xF8, 0xFA, 0xFC))
    arrays = {offset: tuple(reader.u16() for _ in range(30)) for offset in (0x190, 0x118, 0x154)}
    placement = tuple(reader.u8() for _ in range(30))
    fields[0x1EA] = reader.u16()
    padding = reader.take(2)
    return GameDataTileSet(
        start,
        reader.pos,
        (name, resource, overlay),
        fields,
        pointer,
        geometry,
        arrays,
        placement,
        padding,
        reader.data[start : reader.pos],
    )


def read_game_data_terrain_set(reader: SaveReader) -> GameDataTileSet:
    """Read one native0x1414e59d0 TileSet under the exact current DAT profile.

    All current records have400 fixed bytes and three DE strings. The modern
    branch reads30 mask-density shorts instead of the legacy border array.
    Loaded/editor flags do not omit the rest of the serialized record.
    """
    start = reader.pos
    try:
        if reader.version != 0x43E666:
            raise SaveDecodeError(
                f"unsupported terrain set data version {reader.version:#x}", start
            )
        return _terrain_set(reader)
    except SaveDecodeError:
        reader.pos = start
        raise


def read_game_data_map(reader: SaveReader) -> GameDataMap:
    """Read the current DAT map defaults and all200 serialized terrain sets.

    Native0x141038c60 reads a140-byte prefix,200 TileSets and63-byte tail;
    derived0x14103f130 adds eight bytes. Four named dimensions and six bounds
    are four-byte words despite misleading short-pointer decompiler types.
    Native runtime resizing/fixups are not applied to the preserved records.
    """
    start = reader.pos
    try:
        if reader.version != 0x43E666:
            raise SaveDecodeError(f"unsupported map data version {reader.version:#x}", start)
        ignored = reader.take(8)
        dimensions = tuple(reader.u32() for _ in range(4))
        geometry, padding = reader.take(0x72), reader.take(2)
        body = reader.pos
        if reader.remaining < 200 * 412 + 71:
            raise SaveDecodeError("truncated game data map definitions", body)
        terrain_sets = tuple(_terrain_set(reader) for _ in range(200))
        tail = reader.pos
        bounds = tuple(reader.u32() for _ in range(6))
        valid = reader.i16()
        if not 0 <= valid <= 200:
            raise SaveDecodeError(f"unsupported valid terrain count {valid}", reader.pos - 2)
        words = tuple(reader.u16() for _ in range(13))
        tail_padding = reader.take(8)
        flags = (reader.u8(), reader.u8(), reader.u8())
        extension_start = reader.pos
        extension = reader.take(8)
        sections = {
            "header": reader.data[start:body],
            "terrain_sets": reader.data[body:tail],
            "tail": reader.data[tail:extension_start],
            "extension": extension,
        }
        return GameDataMap(
            start,
            reader.pos,
            ignored,
            dimensions,
            geometry,
            padding,
            terrain_sets,
            bounds,
            valid,
            words,
            tail_padding,
            flags,
            extension,
            sections,
            reader.data[start : reader.pos],
        )
    except SaveDecodeError:
        reader.pos = start
        raise


_GRAPHIC_BEFORE_SOUND = (
    (0x78, 4),
    (0x7F, 1),
    (0x7C, 1),
    (0x7D, 1),
    (0x82, 2),
    (0x7E, 1),
    (0x84, 2),
    (0x86, 2),
    (0x88, 2),
    (0x8A, 2),
    (0x8C, 2),
)
_GRAPHIC_AFTER_SOUND = (
    (0xA0, 4),
    (0x80, 1),
    (8, 2),
    (0xA, 2),
    (0xC, 4),
    (0x10, 4),
    (0x14, 4),
    (0x1A, 1),
    (0x18, 2),
    (0x1B, 1),
    (0x1C, 1),
)


def _graphic_sound(reader: SaveReader) -> GameDataGraphicSound:
    at = reader.pos
    words = (reader.u16(), reader.u16(), reader.u32())
    return GameDataGraphicSound(at, reader.pos, words, reader.data[at : reader.pos])


def _graphic(reader: SaveReader) -> GameDataGraphic:
    start = reader.pos
    strings = (reader.de_bytes(), reader.de_bytes(), reader.de_bytes())
    fields = {
        offset: int.from_bytes(reader.take(width), "little")
        for offset, width in _GRAPHIC_BEFORE_SOUND
    }
    sound = reader.u16()
    fields.update(
        (offset, int.from_bytes(reader.take(width), "little"))
        for offset, width in _GRAPHIC_AFTER_SOUND
    )
    count = (fields[0x8C] ^ 0x8000) - 0x8000
    if not 0 <= count <= reader.remaining // 16:
        raise SaveDecodeError(f"invalid graphic delta count {count}", reader.pos)
    deltas = tuple(reader.take(16) for _ in range(count))
    rows = (fields[0xA] ^ 0x8000) - 0x8000 if fields[0x80] else 0
    if not 0 <= rows <= reader.remaining // 24:
        raise SaveDecodeError(f"invalid graphic sound row count {rows}", reader.pos)
    sound_rows = tuple(tuple(_graphic_sound(reader) for _ in range(3)) for _ in range(rows))
    return GameDataGraphic(
        start,
        reader.pos,
        strings,
        fields,
        sound,
        deltas,
        sound_rows,
        reader.data[start : reader.pos],
    )


def read_game_data_graphics(reader: SaveReader) -> GameDataGraphics:
    """Read current DAT graphics, preserving links and sound references as wire values.

    The recovered0x1416074c0 body reads an i16 count and u32 presence table;
    0x1409cbff0 reads each nonzero entry. Its current profile has three DE
    strings,48 fixed bytes,16-byte deltas and optional rows of three sound
    entries (u16,u16,u32). The native0x1409ce780 second pass resolves runtime
    references without consuming stream bytes; no such fixups are applied here.
    """
    start = reader.pos
    try:
        if reader.version != 0x43E666:
            raise SaveDecodeError(f"unsupported graphic data version {reader.version:#x}", start)
        count = reader.i16()
        if not 0 <= count <= reader.remaining // 4:
            raise SaveDecodeError(f"invalid game data graphic count {count}", start)
        placeholders = tuple(reader.u32() for _ in range(count))
        body = reader.pos
        if sum(bool(value) for value in placeholders) > reader.remaining // 60:
            raise SaveDecodeError("truncated graphic bodies", body)
        graphics = {
            index: _graphic(reader) for index, present in enumerate(placeholders) if present
        }
        sections = {
            "index": reader.data[start:body],
            "bodies": reader.data[body : reader.pos],
        }
        return GameDataGraphics(
            start,
            reader.pos,
            body,
            count,
            placeholders,
            graphics,
            sections,
            reader.data[start : reader.pos],
        )
    except SaveDecodeError:
        reader.pos = start
        raise


def read_game_data_colors(reader: SaveReader) -> GameDataColors:
    """Read the color section after terrain restrictions, without loading assets.

    0x141602be0 reads the i16 count; 0x140de3c70 reads nine u32 words in
    native destination order0,10,14,18,1c,20,24,28,4 (hex byte offsets).
    Its later shadow.col loading changes runtime state without more DAT reads.
    """
    start = reader.pos
    try:
        if reader.version != 0x43E666:
            raise SaveDecodeError(f"unsupported color data version {reader.version:#x}", start)
        count = reader.i16()
        if not 0 <= count <= reader.remaining // 36:
            raise SaveDecodeError(f"invalid game data color count {count}", start)
        colors = []
        for _ in range(count):
            at = reader.pos
            fields = {
                offset: reader.u32() for offset in (0, 0x10, 0x14, 0x18, 0x1C, 0x20, 0x24, 0x28, 4)
            }
            colors.append(GameDataColor(at, reader.pos, fields, reader.data[at : reader.pos]))
        return GameDataColors(
            start, reader.pos, count, tuple(colors), reader.data[start : reader.pos]
        )
    except SaveDecodeError:
        reader.pos = start
        raise


def _sound_item(reader: SaveReader) -> GameDataSoundItem:
    start = reader.pos
    name = reader.de_bytes()
    word = reader.u32()
    shorts = (reader.u16(), reader.u16(), reader.u16())
    return GameDataSoundItem(start, reader.pos, name, word, shorts, reader.data[start : reader.pos])


def _sound(reader: SaveReader) -> GameDataSound:
    start = reader.pos
    ident, word16, count = reader.u16(), reader.u16(), reader.i16()
    word32, probability = reader.u32(), reader.u16()
    # Each item has a four-byte DE string header plus one word and three
    # shorts even when its filename is empty. The legacy13-byte filename
    # branch is not used by the supported data version.
    if not 0 <= count <= reader.remaining // 14:
        raise SaveDecodeError(f"invalid game data sound item count {count}", start + 4)
    items = tuple(_sound_item(reader) for _ in range(count))
    return GameDataSound(
        start,
        reader.pos,
        ident,
        word16,
        count,
        word32,
        probability,
        items,
        reader.data[start : reader.pos],
    )


def read_game_data_sounds(reader: SaveReader) -> GameDataSounds:
    """Read native0x141606c50/0x14147a250 sound definitions after colors.

    This preserves filenames and all numeric words before native filename
    normalization, loading and aggregation. TotalProbability is the named
    native two-byte field; other unverified header/item meanings stay raw.
    """
    start = reader.pos
    try:
        if reader.version != 0x43E666:
            raise SaveDecodeError(f"unsupported sound data version {reader.version:#x}", start)
        count = reader.i16()
        if not 0 <= count <= reader.remaining // 12:
            raise SaveDecodeError(f"invalid game data sound count {count}", start)
        sounds = tuple(_sound(reader) for _ in range(count))
        return GameDataSounds(start, reader.pos, count, sounds, reader.data[start : reader.pos])
    except SaveDecodeError:
        reader.pos = start
        raise


def read_terrain_restrictions(reader: SaveReader) -> GameDataTerrainRestrictions:
    """Read the first DAT definition section from its existing cursor.

    Native 0x141627650 is the first body reader after the eight-byte version
    tag. VER 8.9 sets internal version word0x43e666, independently of a replay's
    save version. The two discarded native placeholder arrays and all terrain
    float bits/16-byte records are preserved. Failure restores the cursor.
    """
    start = reader.pos
    try:
        if reader.version != 0x43E666:
            raise SaveDecodeError(f"unsupported terrain data version {reader.version:#x}", start)
        count, terrains = reader.i16(), reader.i16()
        if count < 0 or terrains < 0:
            raise SaveDecodeError("negative terrain restriction count", start)
        sections = {"counts": reader.data[start : reader.pos]}
        first: tuple[int, ...] = ()
        second: tuple[int, ...] = ()
        entries = []
        # Native reads the arrays only when both signed counts are positive.
        if count and terrains:
            required = count * 8 + count * terrains * 20
            if required > reader.remaining:
                raise SaveDecodeError("truncated terrain restrictions", reader.pos)
            at = reader.pos
            first = tuple(reader.u32() for _ in range(count))
            second = tuple(reader.u32() for _ in range(count))
            sections["placeholders"] = reader.data[at : reader.pos]
            for index in range(count):
                at = reader.pos
                words = tuple(reader.u32() for _ in range(terrains))
                records = tuple(reader.take(16) for _ in range(terrains))
                raw = reader.data[at : reader.pos]
                entries.append(GameDataTerrainRestriction(at, reader.pos, words, records, raw))
                sections[f"restriction_{index}"] = raw
        return GameDataTerrainRestrictions(
            start,
            reader.pos,
            count,
            terrains,
            first,
            second,
            tuple(entries),
            sections,
            reader.data[start : reader.pos],
        )
    except SaveDecodeError:
        reader.pos = start
        raise


def read_game_data(
    raw: bytes, *, max_inflated_bytes: int = _MAX_INFLATED_BYTES
) -> GameDataEnvelope:
    """Inflate one current-format DAT envelope without executing the game.

    The size limit is checked during decompression, before hashing or exposing
    output. EOF and absence of trailing compressed bytes are both required.
    Callers must establish build/mode identity separately; ``VER 8.9`` alone
    is a format version, not evidence of matching balance data.
    """
    if max_inflated_bytes < len(_VERSION):
        raise ValueError("game data inflate limit must allow the eight-byte version tag")
    decoder = zlib.decompressobj(-15)
    try:
        data = decoder.decompress(raw, max_inflated_bytes + 1)
    except zlib.error as exc:
        raise GameDataDecodeError("invalid raw-DEFLATE game data") from exc
    if len(data) > max_inflated_bytes:
        raise GameDataDecodeError(f"game data exceeds inflate limit {max_inflated_bytes}")
    if not decoder.eof:
        raise GameDataDecodeError("truncated raw-DEFLATE game data")
    if decoder.unused_data or decoder.unconsumed_tail:
        raise GameDataDecodeError("trailing bytes after compressed game data")
    if len(data) < len(_VERSION):
        raise GameDataDecodeError("truncated game data version tag")
    version = data[: len(_VERSION)]
    if version != _VERSION:
        raise GameDataDecodeError(f"unsupported game data version tag {version!r}")
    return GameDataEnvelope(
        version,
        data,
        len(raw),
        hashlib.sha256(raw).hexdigest(),
        hashlib.sha256(data).hexdigest(),
    )
