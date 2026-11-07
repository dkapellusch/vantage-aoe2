"""Native WorldPlayer second-pass saved records, before reference fixups.

WorldPlayer slot+0x318 reaches 0x1416fe460 -> 0x141545b40 -> 0x1415c5540
and installs this subsystem at player+0x68. Only the measured save 68.9 /
subsystem float 2.1 profile is supported. Native field offsets and serialized
reference IDs remain separate; no pointer resolution or simulation is applied.
Evidence lives in artifacts/game-internals/2026-10-18-world-envelope/player-restore.
"""

from __future__ import annotations

from dataclasses import dataclass

from vantage.replay_binary import SaveDecodeError, SaveReader


@dataclass(frozen=True, slots=True)
class SavedPlayerRestoreFirstEntry:
    """One 44-byte entry, retaining fields before native reference resolution.

    ``reference_ids`` keys identify native pointer destinations, not wire
    offsets. Their signed saved IDs are preserved without resolving them or
    applying the native fallback changes to field+0x3a.
    """

    offset: int
    end_offset: int
    fields: dict[int, int]
    reference_ids: dict[int, int]
    raw: bytes


@dataclass(frozen=True, slots=True)
class SavedPlayerRestoreSecondEntry:
    """One 32-byte current-profile entry, with fields keyed by native offsets.

    The initial 24 wire bytes are followed by native+0x0c and+0x20 words since
    subsystem version 2.0. Runtime allocation stride is not the wire length.
    """

    offset: int
    end_offset: int
    fields: dict[int, int]
    raw: bytes


@dataclass(frozen=True, slots=True)
class SavedPlayerRestore:
    offset: int
    end_offset: int
    version_bits: int
    first_count: int
    first_records: tuple[SavedPlayerRestoreFirstEntry, ...]
    second_count: int
    second_records: tuple[SavedPlayerRestoreSecondEntry, ...]
    fields: dict[int, int]
    sections: dict[str, bytes]
    raw: bytes


def _first_entry(reader: SaveReader) -> SavedPlayerRestoreFirstEntry:
    start = reader.pos
    fields = {0: reader.u8(), 4: reader.u32()}
    references = {8: reader.i32()}
    for offset in (0x10, 0x14, 0x18, 0x1C, 0x20, 0x24):
        fields[offset] = reader.u32()
    references[0x28], references[0x30] = reader.i32(), reader.i32()
    for offset in (0x38, 0x39, 0x3A):
        fields[offset] = reader.u8()
    return SavedPlayerRestoreFirstEntry(
        start, reader.pos, fields, references, reader.data[start : reader.pos]
    )


def _second_entry(reader: SaveReader) -> SavedPlayerRestoreSecondEntry:
    start = reader.pos
    fields = {0: reader.u8(), 1: reader.u8()}
    for offset in (8, 0x10, 0x14, 0x18):
        fields[offset] = reader.u32()
    fields[2], fields[4] = reader.u8(), reader.u8()
    # 0x1415c5540 reads these final two words for version>=2.0; omitting
    # them would silently misalign every following current-profile entry.
    for offset in (0x1C, 0xC, 0x20):
        fields[offset] = reader.u32()
    return SavedPlayerRestoreSecondEntry(start, reader.pos, fields, reader.data[start : reader.pos])


def read_player_restore(reader: SaveReader) -> SavedPlayerRestore:
    """Read one sequential player second-pass record, restoring the cursor on failure.

    Unsigned field values preserve their saved bits. Header field+0x38 is the
    serialized counter word, before the native runtime's additive encoding.
    Negative counts are rejected explicitly, even though native positive-count
    loops can skip them. Following world sections remain untouched.
    """
    start = reader.pos
    try:
        if reader.version != 0x44E666:
            raise SaveDecodeError(
                f"unsupported player restore save version {reader.version:#x}", start
            )
        version = reader.u32()
        if version != 0x40066666:
            raise SaveDecodeError(f"unsupported player restore version bits {version:#x}", start)
        first_count = reader.count(item_size=44)
        fields = {0x10: first_count, 0x20: reader.u8()}
        sections = {"header": reader.data[start : reader.pos]}
        at = reader.pos
        first = tuple(_first_entry(reader) for _ in range(first_count))
        sections["first_records"] = reader.data[at : reader.pos]
        at = reader.pos
        fields[0x38] = reader.u32()
        second_count = reader.count(item_size=32)
        fields[0x40], fields[0x44] = reader.u32(), reader.u32()
        sections["second_header"] = reader.data[at : reader.pos]
        at = reader.pos
        second = tuple(_second_entry(reader) for _ in range(second_count))
        sections["second_records"] = reader.data[at : reader.pos]
        return SavedPlayerRestore(
            start,
            reader.pos,
            version,
            first_count,
            first,
            second_count,
            second,
            fields,
            sections,
            reader.data[start : reader.pos],
        )
    except SaveDecodeError:
        reader.pos = start
        raise
