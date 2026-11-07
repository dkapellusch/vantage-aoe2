"""Native DE save-68.9 master definitions and complete per-player tables.

The common grammar comes from 0x1411f2ec0 and its scalar/string helpers;
derived native readers extend it through factory type 80. Each body starts
after the external type byte. Native restoration also copies defaults from
a baseline game-data master: saved fields are not a complete data file.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from vantage.replay_binary import SaveDecodeError, SaveReader


@dataclass(frozen=True, slots=True)
class SavedMasterAttribute:
    type_id: int
    amount: float
    amount_word: int
    flags: int


@dataclass(frozen=True, slots=True)
class SavedDamageSprite:
    sprite_id: int
    damage_percent: int
    flags: int


@dataclass(frozen=True, slots=True)
class SavedMasterTask:
    """A tagged TaskList entry and its common 67-byte native task body."""

    offset: int
    end_offset: int
    type_id: int
    fields: dict[int, int]
    sprite_ids: tuple[int, ...]
    sound_numbers: tuple[int, ...]
    raw: bytes


@dataclass(frozen=True, slots=True)
class SavedMasterBase:
    """The common saved fields, with exact bytes and final scalar values.

    ``master_id`` is the caller's table index; ``saved_id`` and ``baseline_id``
    come from the body. ``fields`` uses native member offsets, storing floats
    as their unsigned bit patterns. The save's final 44-byte block overwrites
    some earlier members; ``sections`` retains both serialized occurrences.
    ``attributes`` reflects those final type/flag overrides. No baseline-only
    field or restored runtime pointer is invented here.
    """

    offset: int
    end_offset: int
    master_id: int | None
    type_group: int
    saved_id: int
    baseline_id: int
    object_group: int
    hp: int
    string_id: int
    help_string_id: int
    icon_id: int
    radius_x: float
    radius_y: float
    sprite_ids: tuple[int, ...]
    attributes: tuple[SavedMasterAttribute, ...]
    resource_id: int
    resource_string_bytes: bytes
    sound_numbers: tuple[int, ...]
    sound_event_ids: tuple[int, ...]
    damage_sprites: tuple[SavedDamageSprite, ...]
    name: str
    name_bytes: bytes
    fields: dict[int, int]
    sections: dict[str, bytes]
    raw: bytes


@dataclass(frozen=True, slots=True)
class SavedMaster:
    """A complete supported factory body, excluding its external type byte.

    ``base`` retains the common static record separately. ``fields`` and
    ``sections`` add the derived wire values, including graphic references
    before native pointer resolution. No unsaved baseline defaults or runtime
    fixups are substituted for the original serialized values. ``vectors``
    contains weapon/armor pairs at 2b8/2a8, final cost slots at 320, and modern
    training entries at 338 (time, building ID, button byte, hotkey u32).
    ``tasks`` includes serialized overrides only; ``task_count=None`` means
    the native game inherits its task list from baseline data instead.
    """

    offset: int
    end_offset: int
    master_id: int | None
    type_group: int
    base: SavedMasterBase
    speed: float | None
    task_count: int | None
    tasks: tuple[SavedMasterTask, ...]
    action_sound_numbers: tuple[int, ...]
    fields: dict[int, int]
    vectors: dict[int, tuple[tuple[int, ...], ...]]
    sections: dict[str, bytes]
    raw: bytes


@dataclass(frozen=True, slots=True)
class SavedMasterTable:
    """A framed master table, ending before the outer visibility marker.

    Presence values are preserved as signed native i32s; every nonzero value
    has a master body, matching the native branch. Dictionary keys are table
    indices, which are supplied separately to each saved master record.
    """

    offset: int
    end_offset: int
    count: int
    presence: tuple[int, ...]
    masters: dict[int, SavedMaster]
    raw: bytes


def read_master_table(reader: SaveReader) -> SavedMasterTable:
    """Read Marker1/count/presence and every Marker2/type/body/Marker3.

    Both initial Marker1 bytes belong to the table; the following visibility
    Marker1 remains untouched. Any unsupported record or malformed framing
    restores the table's starting cursor without scanning for a later marker.
    """
    start = reader.pos
    try:
        if reader.version != 0x44E666:
            raise SaveDecodeError(f"unsupported master save version {reader.version:#x}", start)
        reader.marker(11)
        count = reader.count(item_size=4)
        presence = tuple(reader.i32() for _ in range(count))
        reader.marker(11)
        masters: dict[int, SavedMaster] = {}
        for master_id, present in enumerate(presence):
            if present:
                reader.marker(22)
                kind = reader.u8()
                masters[master_id] = read_master(reader, master_id=master_id, type_group=kind)
                reader.marker(33)
        return SavedMasterTable(
            start, reader.pos, count, presence, masters, reader.data[start : reader.pos]
        )
    except SaveDecodeError:
        reader.pos = start
        raise


def read_master(
    reader: SaveReader, *, master_id: int | None = None, type_group: int = 10
) -> SavedMaster:
    """Read a proven complete master body; restore the cursor on failure.

    Factory coverage follows the native hierarchy from static 10/15 through
    building 80. Use ``read_master_base`` when only the static common prefix
    is required. The external type byte and player markers belong to callers.
    """
    start = reader.pos
    try:
        return _read_master(reader, master_id, type_group)
    except SaveDecodeError:
        reader.pos = start
        raise


def _read_master(r: SaveReader, master_id: int | None, type_group: int) -> SavedMaster:
    start = r.pos
    if type_group not in {10, 15, 20, 25, 30, 40, 50, 60, 70, 80}:
        raise SaveDecodeError(f"unsupported complete master type group {type_group}", start)
    base = read_master_base(r, master_id=master_id, type_group=type_group)
    fields = dict(base.fields)
    sections = dict(base.sections)
    vectors: dict[int, tuple[tuple[int, ...], ...]] = {}

    def member(offset: int, fmt: str, *, suffix: str = "") -> int:
        raw = r.take(struct.calcsize(fmt))
        sections[f"member_{offset:x}{suffix}"] = raw
        value = int(struct.unpack("<" + fmt, raw)[0])
        fields[offset] = value
        return value

    def vector(label: str, fmt: str, count: int) -> tuple[tuple[int, ...], ...]:
        size = struct.calcsize("<" + fmt)
        if count > r.remaining // size:
            raise SaveDecodeError(f"invalid {label} count {count}", r.pos)
        raw = r.take(max(count, 0) * size)
        sections[label] = raw
        return tuple(
            tuple(int(value) for value in row) for row in struct.iter_unpack("<" + fmt, raw)
        )

    speed = None
    if type_group not in {10, 15}:
        word = member(0x1E0, "I")
        speed = float(struct.unpack("<f", struct.pack("<I", word))[0])
    # Doppel 0x141198bd0 adds runtime assignments, not more wire fields.
    if type_group >= 30:
        for offset, fmt in (
            (0x1F8, "I"),
            (0x1E8, "h"),
            (0x1F0, "h"),
            (0x1FE, "h"),
            (0x200, "B"),
            (0x204, "I"),
            (0x1FC, "B"),
            (0x208, "B"),
            (0x220, "I"),
        ):
            member(offset, fmt)
    task_count = None
    tasks: tuple[SavedMasterTask, ...] = ()
    sound_numbers: tuple[int, ...] = ()
    if type_group >= 40:
        for offset in (0x234, 0x238, 0x23C):
            member(offset, "I")
        task_flags = member(0x290, "B")
        if task_flags & 1:
            at = r.pos
            task_count = r.i16()
            sections["tasks.count"] = r.data[at : r.pos]
            # Native treats nonpositive signed counts as empty lists.
            if task_count > r.remaining // 69:
                raise SaveDecodeError(f"invalid master task count {task_count}", at)
            entries: list[SavedMasterTask] = []
            for i in range(max(0, task_count)):
                task = _read_task(r)
                sections[f"task_{i}"] = task.raw
                entries.append(task)
            tasks = tuple(entries)
        at = r.pos
        sound_numbers = (r.i16(), r.i16())
        sections["action_sound_numbers"] = r.data[at : r.pos]
        for offset in (0x260, 0x278):
            member(offset, "I")
        member(0x259, "B")
        member(0x258, "B")
    if type_group >= 50:
        member(0x2A0, "h")
        weapons = member(0x2B0, "h")
        vectors[0x2B8] = vector("weapons", "hh", weapons)
        armor = member(0x2A2, "h")
        vectors[0x2A8] = vector("armor", "hh", armor)
        for offset, fmt in (
            (0x2D8, "I"),
            (0x2C8, "I"),
            (0x2DE, "h"),
            (0x2DC, "h"),
            (0x2C0, "h"),
            (0x2C4, "I"),
            (0x2CC, "I"),
            (0x2F0, "I"),
            (0x2E2, "h"),
            (0x2D0, "B"),
            (0x2F4, "h"),
            (0x2F6, "h"),
            (0x2F8, "I"),
            (0x2E0, "B"),
            (0x300, "I"),
            (0x298, "h"),
            (0x2D4, "I"),
            (0x304, "I"),
            (0x308, "I"),
            (0x30C, "h"),
            (0x310, "I"),
            (0x318, "h"),
            (0x2E4, "I"),
            (0x2E8, "I"),
            (0x2EC, "I"),
        ):
            member(offset, fmt)
    if type_group == 60:
        for offset, fmt in ((0x321, "B"), (0x322, "B"), (0x323, "B"), (0x328, "I")):
            member(offset, fmt)
    if type_group in {70, 80}:
        # The first cost records are six raw native bytes, including padding.
        # A modern final block overwrites their amounts, types and flags.
        for i in range(3):
            offset = 0x320 + i * 6
            for delta, fmt in ((0, "h"), (2, "h"), (4, "B"), (5, "B")):
                member(offset + delta, fmt, suffix=".initial")
        at = r.pos
        train_count = r.i16()
        sections["train_locations.count"] = r.data[at : r.pos]
        vectors[0x338] = vector("train_locations", "hhBI", train_count)
        for offset, fmt in (
            (0x360, "I"),
            (0x364, "B"),
            (0x379, "B"),
            (0x350, "h"),
            (0x354, "I"),
            (0x3B8, "I"),
            (0x3BC, "I"),
            (0x3C0, "h"),
            (0x3C2, "h"),
            (0x3C4, "h"),
            (0x3C8, "I"),
            (0x3CC, "B"),
            (0x3D0, "I"),
            (0x37A, "h"),
            (0x37C, "I"),
            (0x380, "I"),
            (0x384, "h"),
            (0x3D4, "I"),
            (0x3D8, "I"),
            (0x3DC, "I"),
            (0x374, "I"),
            (0x35C, "B"),
            (0x388, "h"),
            (0x378, "B"),
            (0x3B0, "h"),
            (0x3A8, "h"),
            (0x390, "h"),
            (0x368, "I"),
            (0x36C, "I"),
            (0x370, "I"),
            (0x3E0, "h"),
        ):
            member(offset, fmt)
        for offset in (0x322, 0x328, 0x32E, 0x320, 0x326, 0x32C):
            member(offset, "h")
        for offset in (0x324, 0x32A, 0x330):
            member(offset, "B")
        member(0x398, "h")
        member(0x3A0, "h")
        vectors[0x320] = tuple(
            tuple(fields[0x320 + i * 6 + delta] for delta in (0, 2, 4, 5)) for i in range(3)
        )
    if type_group == 80:
        for offset, fmt in (
            (0x422, "h"),
            (0x460, "I"),
            (0x464, "I"),
            (0x45C, "B"),
            (0x428, "h"),
            (0x3F0, "h"),
            (0x3F8, "h"),
            (0x400, "h"),
            (0x408, "h"),
            (0x410, "h"),
            (0x418, "h"),
        ):
            member(offset, fmt)
        at = r.pos
        r.take(4)
        sections["building_sound_numbers"] = r.data[at : r.pos]
        for offset, fmt in (
            (0x470, "I"),
            (0x488, "I"),
            (0x424, "B"),
            (0x42C, "h"),
            (0x426, "h"),
            (0x458, "h"),
            (0x45A, "h"),
            (0x468, "h"),
            (0x430, "h"),
            (0x432, "h"),
            (0x434, "h"),
            (0x436, "h"),
            (0x438, "I"),
            (0x448, "I"),
            (0x43C, "I"),
            (0x44C, "I"),
            (0x440, "I"),
            (0x450, "I"),
            (0x444, "I"),
            (0x454, "I"),
            (0x42E, "B"),
        ):
            member(offset, fmt)
    return SavedMaster(
        start,
        r.pos,
        master_id,
        type_group,
        base,
        speed,
        task_count,
        tasks,
        sound_numbers,
        fields,
        vectors,
        sections,
        r.data[start : r.pos],
    )


def read_master_task(reader: SaveReader) -> SavedMasterTask:
    """Read one externally tagged task in the measured save/DAT profiles.

    Native TaskList141269730 delegates its common body to14112f920. Both
    historical body gates are taken at save68.9 and internal DAT67.9, giving
    the same 69-byte wire record. This does not read the list count or infer
    a master/task association. Failure restores the caller's cursor.
    """
    start = reader.pos
    try:
        if reader.version not in {0x43E666, 0x44E666}:
            raise SaveDecodeError("unsupported master-task version", start)
        return _read_task(reader)
    except SaveDecodeError:
        reader.pos = start
        raise


def _read_task(r: SaveReader) -> SavedMasterTask:
    start = r.pos
    kind = r.u16()
    fields: dict[int, int] = {}

    def member(offset: int, fmt: str) -> int:
        value = int(struct.unpack("<" + fmt, r.take(struct.calcsize(fmt)))[0])
        fields[offset] = value
        return value

    # 0x14112f920 reads this common grammar regardless of the external
    # TaskList factory tag. Both historical version gates are taken at 68.9.
    for offset, fmt in (
        (0xA, "h"),
        (0xC, "B"),
        (0xE, "h"),
        (0x10, "h"),
        (0x12, "h"),
        (0x16, "h"),
        (0x20, "h"),
        (0x22, "h"),
        (0x24, "h"),
        (0x26, "h"),
        (0x28, "I"),
        (0x2C, "I"),
        (0x30, "I"),
        (0x1B, "B"),
        (0x1C, "I"),
        (0x14, "B"),
        (0x15, "B"),
        (0x34, "h"),
        (0x36, "h"),
        (0x18, "B"),
        (0x19, "B"),
        (0x1A, "B"),
    ):
        member(offset, fmt)
    sprites = tuple(member(offset, "h") for offset in (0x40, 0x48, 0x50, 0x58))
    sounds = (r.i16(), r.i16())
    member(0x60, "I")
    member(0x78, "I")
    member(0x38, "h")
    return SavedMasterTask(start, r.pos, kind, fields, sprites, sounds, r.data[start : r.pos])


def read_master_base(
    reader: SaveReader, *, master_id: int | None = None, type_group: int = 10
) -> SavedMasterBase:
    """Read the common body transactionally, leaving derived data untouched.

    Only the proven save 68.9 grammar is accepted. The external type byte and
    surrounding player markers belong to the caller. A failed read restores
    the starting cursor; no boundary is guessed or recovered by scanning.
    """
    start = reader.pos
    try:
        return _read_master_base(reader, master_id, type_group)
    except SaveDecodeError:
        reader.pos = start
        raise


def _read_master_base(r: SaveReader, master_id: int | None, type_group: int) -> SavedMasterBase:
    start = r.pos
    if r.version != 0x44E666:
        raise SaveDecodeError(f"unsupported master save version {r.version:#x}", start)
    if type_group not in {10, 15, 20, 25, 30, 40, 50, 60, 70, 80}:
        raise SaveDecodeError(f"unsupported master type group {type_group}", start)
    fields: dict[int, int] = {}
    sections: dict[str, bytes] = {}

    def scalar(label: str, fmt: str, member: int | None = None) -> int:
        raw = r.take(struct.calcsize(fmt))
        sections[label] = raw
        value = int(struct.unpack("<" + fmt, raw)[0])
        if member is not None:
            fields[member] = value
        return value

    def member(offset: int, fmt: str, *, suffix: str = "") -> int:
        return scalar(f"member_{offset:x}{suffix}", fmt, offset)

    def float_member(offset: int) -> float:
        word = fields[offset]
        return float(struct.unpack("<f", struct.pack("<I", word))[0])

    # Native's first five values are i16 on the wire, even though their
    # obfuscated runtime storage occupies eight bytes per member.
    for offset in (0x18, 0x20, 0x28, 0x30, 0x38):
        member(offset, "h")
    for offset, fmt in (
        (0x90, "B"),
        (0x8C, "B"),
        (0x68, "h"),
        (0x70, "I"),
        (0x74, "B"),
        (0x78, "I"),
        (0x7C, "I"),
        (0xBC, "h"),
    ):
        member(offset, fmt)
    amount_words: list[int] = []
    for i in range(3):
        member(0xAA + i * 2, "h", suffix=".initial")
        amount_words.append(member(0xB0 + i * 4, "I"))
        member(0xC8 + i, "B", suffix=".initial")
    for offset, fmt in (
        (0x91, "B"),
        (0xC, "i"),
        (0x10, "i"),
        (0xA6, "h"),
        (0x84, "h"),
        (0x8A, "h"),
        (0xCB, "B"),
        (0xA5, "B"),
        (0xF0, "B"),
        (0xF4, "I"),
        (0x86, "h"),
        (0x80, "I"),
        (0xF1, "B"),
        (0xF2, "B"),
        (0x89, "B"),
    ):
        member(offset, fmt)
    sprite_ids = tuple(member(offset, "h") for offset in (0x40, 0x48, 0x50, 0x58))

    # 0x1411df8a0 always reads the resource ID and the following string,
    # including when the ID is not -2. Its 0x140a1cf00 helper uses u32 length,
    # including a wire NUL, not the separate DE marker/length string format.
    resource_id = scalar("resource_id", "i", 0x13C)
    at = r.pos
    size = scalar("resource_string.length", "I")
    if size > 0x2800:
        raise SaveDecodeError(f"invalid resource string length {size}", at)
    resource_string = r.take(size)
    sections["resource_string"] = resource_string
    sound_numbers = tuple(scalar(f"sound_number_{i}", "h") for i in range(4))
    sound_events = tuple(member(offset, "I") for offset in (0x188, 0x170, 0x158, 0x1A0))
    for offset in (0xCF, 0xCC, 0xCD, 0xCE, 0x1D1):
        member(offset, "B")
    at = r.pos
    damage_count = scalar("damage_sprites.count", "B")
    if damage_count > r.remaining // 4:
        raise SaveDecodeError(f"invalid damage sprite count {damage_count}", at)
    damage_sprites = tuple(
        SavedDamageSprite(
            scalar(f"damage_sprite_{i}.id", "h"),
            scalar(f"damage_sprite_{i}.percent", "B"),
            scalar(f"damage_sprite_{i}.flags", "B"),
        )
        for i in range(damage_count)
    )
    at = r.pos
    name = r.de_bytes()
    sections["name"] = r.data[at : r.pos]

    # Version >= 0x44e666 adds this 44-byte tail. Several members duplicate
    # the preceding attribute triples; the native reader's final values win.
    for offset in (0xAA, 0xAC, 0xAE):
        member(offset, "h", suffix=".final")
    for offset in (0xC8, 0xC9, 0xCA):
        member(offset, "B", suffix=".final")
    for offset in (0xA8, 0x121, 0xA4, 0x122, 0x123):
        member(offset, "B")
    for offset in (0x92, 0x94, 0x96, 0x98):
        member(offset, "h")
    for offset in (0x128, 0x12C, 0x130, 0x9C, 0xA0):
        member(offset, "I")
    member(0x8E, "h")
    attributes = tuple(
        SavedMasterAttribute(
            fields[0xAA + i * 2], float_member(0xB0 + i * 4), word, fields[0xC8 + i]
        )
        for i, word in enumerate(amount_words)
    )
    return SavedMasterBase(
        start,
        r.pos,
        master_id,
        type_group,
        fields[0x18],
        fields[0x20],
        fields[0x38],
        fields[0x68],
        fields[0xC],
        fields[0x10],
        fields[0x8A],
        float_member(0x78),
        float_member(0x7C),
        sprite_ids,
        attributes,
        resource_id,
        resource_string,
        sound_numbers,
        sound_events,
        damage_sprites,
        name.decode("utf-8", "replace"),
        name,
        fields,
        sections,
        r.data[start : r.pos],
    )
