"""Structural saved-object records for native DE world restoration.

The shared static record and the animated/dopple extensions are decoded from
the native readers, not by searching for the next plausible object prefix.
Unsupported derived/embedded records stop at an explicit boundary. See
``docs/design/native-replay-playback.md`` and the world-restore evidence.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from vantage.replay_binary import SaveDecodeError, SaveReader
from vantage.replay_unit_ai import SavedUnitAI, read_unit_ai


class UnsupportedSavedObject(SaveDecodeError):
    """A valid-looking native variant whose complete contract is not decoded."""


@dataclass(frozen=True, slots=True)
class SavedAttribute:
    type_id: int
    amount: float


@dataclass(frozen=True, slots=True)
class SavedSound:
    name_bytes: bytes
    words: tuple[int, ...]
    player: int | None


@dataclass(frozen=True, slots=True)
class SavedSprite:
    type_tag: int
    sprite_id: int
    body: bytes
    wrapper_flags: bytes


@dataclass(frozen=True, slots=True)
class SavedMovement:
    fields: dict[int, int]
    vectors: dict[int, bytes]
    paths_wire_order: tuple[bytes, ...]
    secondary_path_flag: int
    secondary_path: bytes | None
    endpoint_flag: int
    endpoints: bytes | None
    waypoints: tuple[bytes, ...]
    raw: bytes


@dataclass(frozen=True, slots=True)
class SavedActionState:
    fields: dict[int, int]
    object_map: tuple[tuple[int, int], ...]
    raw: bytes


@dataclass(frozen=True, slots=True)
class SavedCombatState:
    fields: dict[int, int]
    recharge_map_wire_order: tuple[tuple[int, int, int], ...]
    transform_back_master_id: int
    raw: bytes


@dataclass(frozen=True, slots=True)
class SavedStinger:
    fields: dict[int, int]
    sprite_id: int
    raw: bytes


@dataclass(frozen=True, slots=True)
class SavedUnit:
    fields: dict[int, int]
    ai_type: int
    ai: SavedUnitAI | None
    stingers: tuple[SavedStinger, ...]
    powerup_map_wire_order: tuple[tuple[int, int], ...]
    unpack_timer_flag: int
    unpack_timer: tuple[int, int] | None
    raw: bytes


@dataclass(frozen=True, slots=True)
class SavedBuilding:
    fields: dict[int, int]
    linked_references: tuple[int, ...]
    production_queue: tuple[bytes, ...]
    vectors_914_wire_order: tuple[bytes, bytes]
    flags_wire_order: tuple[int, int]
    arrays: dict[int, tuple[int, ...]]
    raw: bytes


@dataclass(frozen=True, slots=True)
class SavedObject:
    """A saved entity, including its original complete record bytes.

    ``flags`` and ``facet`` are saved values. Native restoration and the Cade
    serializer can change their presentation; these are not spectator states.
    ``fields`` retains less-understood scalar members by native member offset,
    preserving their bits rather than guessing their meaning. Object ID zero
    is valid serialized data; a spectator may assign it a synthetic negative
    map key. No border, master-ID ceiling or positive-HP filter is applied.
    """

    offset: int
    end_offset: int
    type_group: int
    owner: int
    master_id: int
    sprite_id: int
    reference_id: int
    hp: float
    flags: tuple[int, ...]
    object_id: int
    facet: int
    position: tuple[float, float, float]
    screen_shadow_offsets: tuple[int, ...]
    held_resource_type: int
    held_resource_amount: float
    attributes: tuple[SavedAttribute, ...]
    related_ids: tuple[int, ...]
    sprites: tuple[SavedSprite, ...]
    unique_sprite_nodes: int | None
    sounds: tuple[tuple[SavedSound, ...], ...]
    strings: tuple[str, str]
    name_bytes: bytes
    fields: dict[int, int]
    movement: SavedMovement | None
    action: SavedActionState | None
    combat: SavedCombatState | None
    projectile: bytes | None
    unit: SavedUnit | None
    building: SavedBuilding | None
    raw: bytes


def _unsupported(reader: SaveReader, what: str) -> None:
    raise UnsupportedSavedObject(f"unsupported {what}", reader.pos)


def _sound(reader: SaveReader) -> SavedSound:
    # Native 0x1409bda80: an empty name has no body; otherwise eight
    # four-byte fields and, on modern saves, a signed player reference.
    name = reader.de_bytes()
    if not name:
        return SavedSound(name, (), None)
    return SavedSound(name, tuple(reader.u32() for _ in range(8)), reader.i16())


def _moving(r: SaveReader) -> SavedMovement:
    """Native 0x14121f910 plus 45-byte path nodes from 0x14106fc40."""
    start = r.pos
    fields = {offset: r.u32() for offset in (0x370, 0x374, 0x378, 0x37C, 0x380, 0x384)}
    fields.update({offset: r.u8() for offset in (0x391, 0x392, 0x390, 0x393)})
    paths = tuple(r.take(45) for _ in range(r.count(item_size=45)))
    secondary_flag = r.i32()
    secondary = r.take(45) if secondary_flag == 1 else None
    endpoint_flag = r.i32()
    endpoints = r.take(24) if endpoint_flag == 1 else None
    vectors = {offset: r.take(12) for offset in (0x3BC, 0x3C8, 0x3D4)}
    fields.update({offset: r.u32() for offset in (0x408, 0x40C)})
    waypoints = tuple(r.take(12) for _ in range(r.count(item_size=12)))
    fields[0x3B9], vectors[0x3E0], fields[0x410] = r.u8(), r.take(12), r.u32()
    for offset in (0x358, 0x35C, 0x360, 0x364, 0x3A0, 0x3A4):
        fields[offset] = r.u32()
    return SavedMovement(
        fields,
        vectors,
        paths,
        secondary_flag,
        secondary,
        endpoint_flag,
        endpoints,
        waypoints,
        r.data[start : r.pos],
    )


def _action(r: SaveReader) -> SavedActionState:
    """Native 0x14113e920; nonempty behavior lists need their real factory."""
    start = r.pos
    fields = {0x428: r.u8()}
    for offset in (0x42C, 0x430, 0x434):
        fields[offset] = r.u32()
    at = r.pos
    count = int.from_bytes(r.take(8), "little")
    if count > r.remaining // 8:
        raise SaveDecodeError(f"invalid action-map count {count}", at)
    entries = tuple((r.u32(), r.u32()) for _ in range(count))
    tag = r.u16()
    if tag:
        _unsupported(r, f"object behavior tag {tag}")
    return SavedActionState(fields, entries, r.data[start : r.pos])


def _combat(r: SaveReader) -> SavedCombatState:
    """Native 0x1411587a0: 50 fixed bytes plus 12 per recharge-map entry."""
    start = r.pos
    fields = {offset: r.u8() for offset in (0x51D, 0x51E, 0x51F)}
    fields.update({offset: r.u32() for offset in (0x514, 0x518)})
    fields.update({offset: r.u8() for offset in (0x51C, 0x4FC, 0x4FD)})
    fields[0x4F8], fields[0x4A0] = r.u32(), r.u8()
    entries = tuple((r.u32(), r.u32(), r.u32()) for _ in range(r.count(item_size=12)))
    fields[0x590] = r.u32()
    master = r.i16()
    fields.update({offset: r.u32() for offset in (0x508, 0x50C, 0x510)})
    fields[0x594] = r.u8()
    fields.update({offset: r.u32() for offset in (0x59C, 0x5A0)})
    return SavedCombatState(fields, entries, master, r.data[start : r.pos])


def _stinger(r: SaveReader) -> SavedStinger:
    """Native 0x1411281d0; 42 wire bytes at save 68.9, runtime size 56."""
    start = r.pos
    fields = {offset: r.u32() for offset in (0, 4, 0xC, 0x10, 0x14, 0x18, 0x1C, 0x20, 0x24)}
    sprite = r.i16()
    fields[8] = r.u32()
    return SavedStinger(fields, sprite, r.data[start : r.pos])


def _unit(r: SaveReader) -> SavedUnit:
    """Modern success path of 0x1412d4f50, after the combat parent."""
    start = r.pos
    fields = {0x68C: r.u8(), 0x68D: r.u8()}
    fields.update({offset: r.u16() for offset in (0x618, 0x61A, 0x61C, 0x61E, 0x620, 0x622, 0x624)})
    fields.update({offset: r.u32() for offset in (0x628, 0x690)})
    fields[0x630] = r.u8()
    ai_type = r.i32()
    ai = read_unit_ai(r, ai_type) if ai_type else None
    fields[0x664] = r.u8()
    fields.update(
        {
            offset: r.u32()
            for offset in (
                0x634,
                0x644,
                0x648,
                0x640,
                0x638,
                0x63C,
                0x64C,
                0x65C,
                0x660,
                0x658,
                0x650,
                0x654,
                0x698,
            )
        }
    )
    fields[0x670], fields[0x671], fields[0x668] = r.u8(), r.u8(), r.u32()
    fields[0x66C], fields[0x66E] = r.u16(), r.u16()
    fields.update(
        {
            offset: r.u32()
            for offset in (0x62C, 0x6AC, 0x6B0, 0x6DC, 0x6B4, 0x6B8, 0x6BC, 0x7C0, 0x7C4, 0x7C8)
        }
    )
    stingers = tuple(_stinger(r) for _ in range(r.count(item_size=42)))
    fields.update({offset: r.u32() for offset in (0x6C0, 0x6C4, 0x6C8, 0x6D0, 0x6D4)})
    powerups = tuple((r.u16(), r.u32()) for _ in range(r.count(item_size=6, signed=False)))
    fields[0x6D8], fields[0x808] = r.u32(), r.u8()
    timer_flag = r.u8()
    timer = (r.u16(), r.u32()) if timer_flag else None
    return SavedUnit(
        fields, ai_type, ai, stingers, powerups, timer_flag, timer, r.data[start : r.pos]
    )


def _empty_behavior_list(r: SaveReader) -> None:
    tag = r.u16()
    if tag:
        _unsupported(r, f"building behavior tag {tag}")


def _building(r: SaveReader) -> SavedBuilding:
    """Native 0x141297f00, modern branch after the complete unit parent."""
    start = r.pos
    fields = {0x951: r.u8(), 0x900: r.u32(), 0x94C: r.u32()}
    fields.update({offset: r.u8() for offset in (0x950, 0x844)})
    fields.update(
        {
            offset: r.u32()
            for offset in (0x848, 0x890, 0x8D0, 0x8D4, 0x8E0, 0x8E4, 0x8E8, 0x8EC, 0x8F0)
        }
    )
    fields[0x8F4], fields[0x910] = r.u16(), r.u8()
    # Linked owner plus four object IDs; runtime allocation size is 20 bytes.
    linked = tuple(r.u32() for _ in range(5))
    fields[0x84D] = r.u8()
    _empty_behavior_list(r)
    at = r.pos
    count = r.i16()
    if not 0 <= count <= r.remaining // 36:
        raise SaveDecodeError(f"invalid production-queue count {count}", at)
    # Four i16s, one four-byte member, then three eight-byte costs. These
    # are 36 wire bytes; the corresponding runtime entries occupy 48 bytes.
    queue = tuple(r.take(36) for _ in range(count))
    fields[0x8A2], fields[0x8A4], fields[0x8A6] = r.u16(), r.u16(), r.u8()
    _empty_behavior_list(r)
    # The native reader writes both vectors to +0x914; retain both wire
    # occurrences so restoration/normalization can be investigated separately.
    vectors = (r.take(12), r.take(12))
    fields.update({offset: r.u32() for offset in (0x92C, 0x930, 0x934)})
    flags = (r.u8(), r.u8())
    fields[0x911], fields[0x938], fields[0x940], fields[0x8D8] = (r.u8(), r.u8(), r.u16(), r.u32())
    arrays = {
        offset: tuple(r.u32() for _ in range(r.count(item_size=4))) for offset in (0x828, 0x968)
    }
    if r.u8():
        _unsupported(r, "embedded building master")
    arrays[0x990] = tuple(r.u32() for _ in range(r.count(item_size=4)))
    for offset in (0x9B0, 0x9E0, 0x9C8):
        arrays[offset] = tuple(r.u16() for _ in range(r.count(item_size=2, signed=False)))
    fields[0x980] = r.u8()
    return SavedBuilding(fields, linked, queue, vectors, flags, arrays, r.data[start : r.pos])


def read_saved_object(reader: SaveReader) -> SavedObject:
    """Read one tagged record; a failure leaves the caller's cursor unchanged.

    Initial coverage is save 68.9 static (10), animated (20), dopple (25),
    moving (30), action (40), combat (50), projectile (60), unit (70), and building (80)
    records without embedded masters or nonempty behavior lists.
    These limits are checked, never bypassed by scanning/resynchronization.
    """
    start = reader.pos
    try:
        return _read_saved_object(reader)
    except SaveDecodeError:
        reader.pos = start
        raise


def _read_saved_object(r: SaveReader) -> SavedObject:
    start = r.pos
    if r.version != 0x44E666:
        _unsupported(r, f"save version word {r.version:#x}")
    kind = r.u8()
    if kind not in {10, 20, 25, 30, 40, 50, 60, 70, 80}:
        _unsupported(r, f"object type group {kind}")
    owner, master, sprite, reference = r.u8(), r.i16(), r.i16(), r.i32()
    hp = r.f32()
    flags = tuple(r.take(4))
    object_id, facet = r.u32(), r.u8()
    position = (r.f32(), r.f32(), r.f32())
    screen = tuple(r.i16() for _ in range(4))
    # The old selected-group byte is present only before save 11.58.
    # Modern held type/amount/count therefore start at +43/+45/+49.
    held_type, held_amount = r.i16(), r.f32()
    count = r.u16()
    if count > r.remaining // 6:
        raise SaveDecodeError("truncated saved attribute vector", r.pos - 2)
    attributes = tuple(SavedAttribute(r.i16(), r.f32()) for _ in range(count))
    fields: dict[int, int] = {0x18C: r.u32(), 0xD: r.u8(), 0x165: r.u8(), 0x1C0: r.u16()}
    fields[0x190], fields[0x1C5] = r.u32(), r.u8()
    related = tuple(r.i32() for _ in range(r.count(item_size=4)))
    fields[0x210], fields[0x214] = r.u32(), r.u32()
    fields[0x1C7], fields[0x1C6] = r.u8(), r.u8()
    own_master, other_master = r.u8(), r.u8()
    if own_master or other_master:
        _unsupported(r, "embedded object master")
    controller = r.u8()
    sprites: list[SavedSprite] = []
    unique_nodes = None
    if controller:
        # Native ActiveSpriteList::read: node body, then three factory
        # wrapper bytes, repeat until zero. Modern controller adds its own
        # mHasUniqueSpriteNodes byte after the list (save > 68.2).
        while tag := r.u8():
            if tag not in {1, 2}:
                _unsupported(r, f"sprite-controller type {tag}")
            body = r.take(13 if tag == 1 else 30)
            sprites.append(SavedSprite(tag, struct.unpack_from("<h", body)[0], body, r.take(3)))
        unique_nodes = r.u8()
    primary = (_sound(r),) if r.u16() else ()
    sound_groups: list[tuple[SavedSound, ...]] = [primary]
    for _ in range(2):
        count = r.u16()
        if count > r.remaining // 4:
            raise SaveDecodeError("truncated saved sound array", r.pos - 2)
        sound_groups.append(tuple(_sound(r) for _ in range(count)))
    fields[0x198] = r.u32()
    fields[0x294], fields[0x290] = r.u8(), r.u32()
    fields[0x2C8], fields[0x1E8] = r.u16(), r.u16()
    strings = (r.de_string(), r.de_string())
    for member in (0x1C9, 0x1CA, 0x1CB, 0x295):
        fields[member] = r.u8()
    for member in (0x2D0, 0x2D4):
        fields[member] = r.u32()
    fields[0x162], fields[0x16C], fields[0x30] = r.u16(), r.u32(), r.u32()
    name = r.take(r.count(item_size=1, signed=False))
    if kind != 10:
        fields[0x350] = r.u32()
    movement = _moving(r) if kind in {30, 40, 50, 60, 70, 80} else None
    action = _action(r) if kind in {40, 50, 60, 70, 80} else None
    combat = _combat(r) if kind in {50, 60, 70, 80} else None
    # Native 0x141204d20 skips the legacy embedded-master branch at 68.9;
    # only two four-byte members and one byte remain after combat50.
    projectile = r.take(9) if kind == 60 else None
    unit = _unit(r) if kind in {70, 80} else None
    building = _building(r) if kind == 80 else None
    return SavedObject(
        start,
        r.pos,
        kind,
        owner,
        master,
        sprite,
        reference,
        hp,
        flags,
        object_id,
        facet,
        position,
        screen,
        held_type,
        held_amount,
        attributes,
        related,
        tuple(sprites),
        unique_nodes,
        tuple(sound_groups),
        strings,
        name,
        fields,
        movement,
        action,
        combat,
        projectile,
        unit,
        building,
        r.data[start : r.pos],
    )
