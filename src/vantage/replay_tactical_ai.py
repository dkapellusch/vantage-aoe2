"""Native Tactical AI saved state for independent DE world restoration.

Save 68.9 grammar: Tactical AI 0x140c92170, group 0x140cab4b0, and shared
path 0x14106e770. Member offsets label raw saved values, not reconstructed
runtime defaults. See artifacts/game-internals/2026-10-18-player-ai/tactical.
"""

from __future__ import annotations

from dataclasses import dataclass

from vantage.replay_binary import SaveDecodeError, SaveReader
from vantage.replay_unit_ai import SavedUnitAIPath, _read_path


@dataclass(frozen=True, slots=True)
class SavedTacticalGroup:
    offset: int
    end_offset: int
    fields: dict[int, int]
    unit_count: int
    vectors: dict[int, tuple[int, ...]]
    path: SavedUnitAIPath
    raw: bytes


@dataclass(frozen=True, slots=True)
class SavedTacticalAI:
    offset: int
    end_offset: int
    num_players: int
    fields: dict[int, int]
    counts: dict[int, int]
    vectors: dict[int, tuple[int, ...]]
    static_records_24: tuple[bytes, ...]
    discarded_count: int
    discarded_records_24: tuple[bytes, ...]
    group_count: int
    groups: tuple[SavedTacticalGroup, ...]
    pair_count: int
    pairs: tuple[tuple[int, int], ...]
    final_words: tuple[int, ...]
    raw: bytes


def read_tactical_ai(reader: SaveReader, num_players: int) -> SavedTacticalAI:
    """Read Tactical AI using the native world player count, including Gaia.

    This is an exact version decoder and restores the cursor on failure.
    Counted vectors, map pairs and set words preserve original wire order and
    duplicates even where native containers sort, replace or deduplicate them.
    """
    start = reader.pos
    try:
        return _read_tactical_ai(reader, num_players)
    except SaveDecodeError:
        reader.pos = start
        raise


def _marker(reader: SaveReader, expected: int) -> None:
    at = reader.pos
    actual = reader.u16()
    if actual != expected:
        raise SaveDecodeError(f"expected AI marker {expected:#x}, found {actual:#x}", at)


def _count(reader: SaveReader, item_size: int) -> int:
    at = reader.pos
    count = reader.i32()
    if count > reader.remaining // item_size:
        raise SaveDecodeError(f"invalid Tactical AI count {count}", at)
    return count


def _bounded_count(reader: SaveReader, limit: int) -> int:
    at = reader.pos
    count = reader.i32()
    if not 0 <= count <= limit:
        raise SaveDecodeError(f"invalid Tactical AI fixed-array count {count}", at)
    return count


def _words(reader: SaveReader, count: int) -> tuple[int, ...]:
    # Prove the whole array fits before allocating an output tuple.
    if count > reader.remaining // 4:
        raise SaveDecodeError(f"truncated Tactical AI word array of {count}", reader.pos)
    return tuple(reader.u32() for _ in range(max(0, count)))


def _fields(reader: SaveReader, target: dict[int, int], offsets: tuple[int, ...]) -> None:
    for offset in offsets:
        target[offset] = reader.u32()


def _read_group(reader: SaveReader) -> SavedTacticalGroup:
    start = reader.pos
    fields: dict[int, int] = {}
    _fields(reader, fields, (0x560, 0x564))
    # 0x140cab4b0 has a native 60-word array at +0x570, filled with -1 after
    # the saved entries. +0x714 uses the same count and no second prefix.
    unit_count = _bounded_count(reader, 60)
    vectors = {0x570: _words(reader, unit_count)}
    _fields(reader, fields, (0x660, 0x664, 0x668, 0x66C, 0x670))
    _fields(reader, fields, tuple(range(0x674, 0x694, 4)))
    _fields(reader, fields, (0x694, 0x698, 0x69C, 0x568, 0x56C, 0x6A0))
    fields[0x6A4] = reader.u8()
    fields[0x6A8] = reader.u32()
    _fields(reader, fields, tuple(range(0x6AC, 0x700, 4)))
    _fields(reader, fields, tuple(range(0x700, 0x714, 4)))
    vectors[0x714] = _words(reader, unit_count)
    _fields(reader, fields, (0x804, 0x808, 0x80C, 0x810, 0x818))
    # The group invokes exactly the same 0x14106e770 path reader used by
    # UnitAI. Reuse its proven wire grammar and raw-bit representation.
    path = _read_path(reader)
    return SavedTacticalGroup(
        start, reader.pos, fields, unit_count, vectors, path, reader.data[start : reader.pos]
    )


def _read_tactical_ai(reader: SaveReader, num_players: int) -> SavedTacticalAI:
    start = reader.pos
    if reader.version != 0x44E666:
        raise SaveDecodeError(f"unsupported Tactical AI save version {reader.version:#x}", start)
    if not 1 <= num_players <= reader.remaining // 4:
        raise SaveDecodeError(f"invalid native player count {num_players}", start)
    fields: dict[int, int] = {}
    counts: dict[int, int] = {}
    vectors: dict[int, tuple[int, ...]] = {}

    def vector(offset: int) -> None:
        counts[offset] = _count(reader, 4)
        vectors[offset] = _words(reader, counts[offset])

    _marker(reader, 0xA10)
    vector(0xC0)
    vector(0xD8)
    _fields(reader, fields, (0x2164, 0x2168))
    # Native modern gates select exactly 250 six-word records, not the
    # 100-entry or 16/20-byte legacy formats in adjacent branches.
    raw_records = reader.take(250 * 24)
    records = tuple(raw_records[i : i + 24] for i in range(0, len(raw_records), 24))
    _marker(reader, 0xAA0)
    for offset in (0xF0, 0x108, 0x120, 0x138, 0x150, 0x168, 0x180, 0x198, 0x1B0):
        vector(offset)
    _marker(reader, 0xAA0)
    counts[0x1F8] = _bounded_count(reader, 511)
    vectors[0x1F8] = _words(reader, counts[0x1F8])
    _marker(reader, 0xAA0)
    for offset in (0x29C0, 0x29D8, 0x29F0):
        vector(offset)
    discarded_count = _count(reader, 24)
    discarded = tuple(reader.take(24) for _ in range(max(0, discarded_count)))
    _marker(reader, 0xAA0)
    for offset in (0x2AD0, 0x2AE0, 0x2AC0, 0x2AF8, 0x2B08):
        _fields(reader, fields, tuple(range(offset, offset + 16, 4)))
    _marker(reader, 0xAA0)
    fields[0x2998] = reader.u32()
    group_count = _count(reader, 245)
    fields[0x299C] = group_count & 0xFFFFFFFF
    groups = tuple(_read_group(reader) for _ in range(max(0, group_count)))
    _fields(
        reader,
        fields,
        (0x29A0, 0x29A4, 0x29A8, 0x29AC, 0x29B0, 0x29B4, 0x29B8, 0x2AF0, 0x2AF4, 0x2B18, 0x2B1C),
    )
    _marker(reader, 0xAA0)
    _fields(
        reader,
        fields,
        (
            0x2C90,
            0x2C94,
            0x2C98,
            0x2C9C,
            0x2CA0,
            0x2CA4,
            0x2CA8,
            0x2CAC,
            0x2CB0,
            0x2CB8,
            0x2CB4,
            0x2CBC,
        ),
    )
    _marker(reader, 0xAA0)
    _fields(reader, fields, tuple(range(0x2CC0, 0x2CEC, 4)))
    # Native >=61 uses the actual world player count. No count is on wire.
    vectors[0x2CF0] = _words(reader, num_players)
    _fields(reader, fields, tuple(range(0x2E78, 0x2E9C, 4)))
    _fields(reader, fields, (0x2EA4, 0x2EA8, 0x2EAC))
    at = reader.pos
    pair_count = reader.i16()
    if pair_count > reader.remaining // 4:
        raise SaveDecodeError(f"invalid Tactical AI pair count {pair_count}", at)
    pairs = tuple((reader.u16(), reader.u16()) for _ in range(max(0, pair_count)))
    vector(0x1C8)
    vector(0x1E0)
    _fields(reader, fields, (0x216C, 0x2170))
    at = reader.pos
    final_count = int.from_bytes(reader.take(8), "little")
    if final_count > reader.remaining // 4:
        raise SaveDecodeError(f"invalid Tactical AI final count {final_count}", at)
    final_words = _words(reader, final_count)
    _marker(reader, 0xA20)
    return SavedTacticalAI(
        start,
        reader.pos,
        num_players,
        fields,
        counts,
        vectors,
        records,
        discarded_count,
        discarded,
        group_count,
        groups,
        pair_count,
        pairs,
        final_words,
        reader.data[start : reader.pos],
    )
