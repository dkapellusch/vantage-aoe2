"""Native Con AI save records for independent DE world restoration.

The stream grammar comes from 0x140c18830, reached by the short forwarding
constructor 0x140c2f540. AI markers are two bytes, unlike player markers.
Original evidence and paired boundaries live in the player-ai/con artifacts.
This preserves saved state; it does not implement Con AI updates.
"""

from __future__ import annotations

from dataclasses import dataclass

from vantage.replay_binary import SaveDecodeError, SaveReader


@dataclass(frozen=True, slots=True)
class SavedConAIEntry:
    """One named list entry, retaining all thirteen words in wire order.

    The two lists serialize their words in different orders. No unsupported
    correspondence or gameplay meaning is imposed on these raw words.
    """

    offset: int
    end_offset: int
    name_bytes: bytes
    words: tuple[int, ...]
    raw: bytes

    @property
    def name(self) -> str:
        return self.name_bytes.decode("utf-8", "replace")


@dataclass(frozen=True, slots=True)
class SavedConAI:
    offset: int
    end_offset: int
    fields: dict[int, int]
    text_bytes: bytes
    first_list_count: int
    first_list: tuple[SavedConAIEntry, ...]
    second_list_count: int
    second_list: tuple[SavedConAIEntry, ...]
    raw: bytes

    @property
    def text(self) -> str:
        return self.text_bytes.decode("utf-8", "replace")


def read_con_ai(reader: SaveReader) -> SavedConAI:
    """Read the Con AI record immediately after Build AI.

    Fields use native byte offsets; their unsigned words preserve float and
    integer bits alike. Native signed list counts at or below zero mean no
    entries and remain available separately. Failure restores the cursor.
    """
    start = reader.pos
    try:
        return _read_con_ai(reader)
    except SaveDecodeError:
        reader.pos = start
        raise


def _marker(reader: SaveReader, expected: int) -> None:
    # 0x140c0d4a0 reads two bytes; constants are in DAT_143dadfcc/fd0/fd4.
    at = reader.pos
    actual = reader.u16()
    if actual != expected:
        raise SaveDecodeError(f"expected AI marker {expected:#x}, found {actual:#x}", at)


def _list_count(reader: SaveReader) -> int:
    at = reader.pos
    count = reader.i32()
    # Each entry requires i32 name length and thirteen u32 words, even when
    # its name is empty. Native loops test count > 0 rather than count != 0.
    if count > reader.remaining // 56:
        raise SaveDecodeError(f"invalid Con AI list count {count}", at)
    return count


def _entry(reader: SaveReader) -> SavedConAIEntry:
    start = reader.pos
    length = reader.i32()
    # Both native loops append a local NUL after these bytes and enforce the
    # same 256-byte limit. That appended NUL is not another stream read.
    if not 0 <= length <= 0x100:
        raise SaveDecodeError(f"invalid Con AI entry name length {length}", start)
    name = reader.take(length)
    words = tuple(reader.u32() for _ in range(13))
    return SavedConAIEntry(start, reader.pos, name, words, reader.data[start : reader.pos])


def _read_con_ai(reader: SaveReader) -> SavedConAI:
    start = reader.pos
    if reader.version != 0x44E666:
        raise SaveDecodeError(f"unsupported Con AI save version {reader.version:#x}", start)
    _marker(reader, 0xA10)
    first_count = _list_count(reader)
    text_length = reader.count(item_size=1)
    text = reader.take(text_length)
    fields = {0xB0: first_count & 0xFFFFFFFF}
    for offset in (0x1F8, 0x1FC, 0x200, 0x204, 0x208):
        fields[offset] = reader.u32()
    _marker(reader, 0xAA0)
    first = tuple(_entry(reader) for _ in range(max(0, first_count)))
    _marker(reader, 0xAA0)
    second_count = _list_count(reader)
    fields[0x148] = second_count & 0xFFFFFFFF
    second = tuple(_entry(reader) for _ in range(max(0, second_count)))
    _marker(reader, 0xA20)
    return SavedConAI(
        start,
        reader.pos,
        fields,
        text,
        first_count,
        first,
        second_count,
        second,
        reader.data[start : reader.pos],
    )
