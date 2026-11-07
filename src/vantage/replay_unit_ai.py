"""Native saved UnitAI records used by independent DE world restoration.

This is the save 68.9 read contract from native UnitAIModule and its three
specialized readers. Scalar words retain their exact bits and native member
offsets; counted records retain wire order. See the world-restore unit-layout
contracts for addresses and evidence. This module does not simulate AI updates.
"""

from __future__ import annotations

from dataclasses import dataclass

from vantage.replay_binary import SaveDecodeError, SaveReader


class UnsupportedSavedUnitAI(SaveDecodeError):
    """A native AI variant whose complete saved grammar is not decoded."""


@dataclass(frozen=True, slots=True)
class SavedUnitAIPath:
    fields: dict[int, int]
    points: tuple[tuple[int, int, int], ...]
    reference_words: tuple[int, ...]
    raw: bytes


@dataclass(frozen=True, slots=True)
class SavedUnitAI:
    offset: int
    end_offset: int
    ai_type: int
    fields: dict[int, int]
    records_52: tuple[bytes, ...]
    records_24: tuple[bytes, ...]
    ids: tuple[int, ...]
    path_flag: int
    path: SavedUnitAIPath | None
    records_44: tuple[bytes, ...]
    pairs: tuple[tuple[int, int], ...]
    spawn_flag: int
    spawn_data: bytes | None
    variant_records_52: tuple[bytes, ...]
    raw: bytes


def read_unit_ai(reader: SaveReader, ai_type: int) -> SavedUnitAI:
    """Read AI payload after its owning unit's signed32 AI type.

    A failure restores the caller's cursor. Type 0 denotes no AI object and is
    handled by the unit reader. Native types 1 through 19 use a shared base;
    types 4, 15 and 17 add their documented derived tails.
    """
    start = reader.pos
    try:
        return _read_unit_ai(reader, ai_type)
    except SaveDecodeError:
        reader.pos = start
        raise


def _records(r: SaveReader, width: int) -> tuple[bytes, ...]:
    return tuple(r.take(width) for _ in range(r.count(item_size=width)))


def _read_path(r: SaveReader) -> SavedUnitAIPath:
    # Native 0x14106e770: path vectors are 12 bytes, followed by four scalar
    # members and counted reference words. ASM at 0x14106f5a3 confirms count*4.
    start = r.pos
    fields = {0: r.u32()}
    points = tuple((r.u32(), r.u32(), r.u32()) for _ in range(r.count(item_size=12)))
    for offset in (4, 8, 0xC, 0x10):
        fields[offset] = r.u32()
    references = tuple(r.u32() for _ in range(r.count(item_size=4)))
    return SavedUnitAIPath(fields, points, references, r.data[start : r.pos])


def _read_unit_ai(r: SaveReader, ai_type: int) -> SavedUnitAI:
    start = r.pos
    if r.version != 0x44E666:
        raise UnsupportedSavedUnitAI(f"unsupported UnitAI save version {r.version:#x}", start)
    if not 1 <= ai_type <= 19:
        raise UnsupportedSavedUnitAI(f"unsupported UnitAI type {ai_type}", start)
    # Native 0x140d267d0: the order deliberately differs from member order.
    fields = {
        offset: r.u32()
        for offset in (
            0x10,
            0x3C,
            0x40,
            0x44,
            0x48,
            0x4C,
            0x50,
            0x54,
            0x58,
            0x5C,
            0x68,
            0x64,
            0x6C,
            0x70,
            0x164,
            0x168,
            0x170,
            0x16C,
            0x174,
            0x178,
            0x17C,
            0x60,
            0x194,
            0x184,
            0x188,
            0x18C,
            0x190,
        )
    }
    # Older saves use 36/48-byte versions of the first record list. Modern
    # saves use 52 bytes; none of these are runtime allocation sizes.
    records_52 = _records(r, 52)
    records_24 = _records(r, 24)
    ids = tuple(r.u32() for _ in range(r.count(item_size=4)))
    fields[0x1B0], fields[0x1B1] = r.u8(), r.u8()
    for offset in (0x1B4, 0x1B8, 0x1BC):
        fields[offset] = r.u32()
    fields[0x1C0], fields[0x1C4] = r.u8(), r.u32()
    path_flag = r.i32()
    path = _read_path(r) if path_flag == 1 else None
    fields[0x1D0] = r.u32()
    records_44 = _records(r, 44)
    fields[0xBC], fields[0x1D4] = r.u32(), r.u32()
    pairs = tuple((r.u32(), r.u32()) for _ in range(r.count(item_size=8)))
    fields[0x1D8], fields[0x1DC] = r.u32(), r.u8()
    fields[0x180], fields[0x1DE] = r.u32(), r.u8()
    spawn_flag = r.u8()
    # Native 0x140c29890: three 4-byte members then one 2-byte member.
    spawn = r.take(14) if spawn_flag else None
    variant: tuple[bytes, ...] = ()
    if ai_type == 4:
        for offset in (0x1F8, 0x1FC, 0x200):
            fields[offset] = r.u32()
        fields[0x204] = r.u8()
    elif ai_type in (15, 17):
        variant = _records(r, 52)
    return SavedUnitAI(
        start,
        r.pos,
        ai_type,
        fields,
        records_52,
        records_24,
        ids,
        path_flag,
        path,
        records_44,
        pairs,
        spawn_flag,
        spawn,
        variant,
        r.data[start : r.pos],
    )
