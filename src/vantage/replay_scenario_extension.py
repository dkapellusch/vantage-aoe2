"""TribeScenario's native extension for save68.9/scenario1.59.

BaseScenario is read separately. This preserves serialized fields before
runtime conversions, pointer fixups and trigger execution. Native reader
0x140dc3480 follows BaseScenario0x140d86730 in vtable143260ca8 slot+0x10.
"""

from __future__ import annotations

from dataclasses import dataclass

from vantage.replay_binary import SaveDecodeError, SaveReader
from vantage.replay_scenario_base import SavedScenarioBase, read_scenario_base


@dataclass(frozen=True, slots=True)
class SavedScenarioDisabled:
    counts: tuple[int, ...]
    rows: tuple[tuple[int, ...], ...]
    raw: bytes


@dataclass(frozen=True, slots=True)
class SavedScenarioExtension:
    offset: int
    end_offset: int
    max_players: int
    player_info: tuple[tuple[int, ...], ...]
    checksums: tuple[int, int, int]
    fields: dict[int, int]
    word_arrays: dict[int, tuple[int, ...]]
    opponent_attitudes: tuple[tuple[int, ...], ...]
    raw_player_records: tuple[bytes, ...]
    disabled: dict[int, SavedScenarioDisabled]
    byte_arrays: dict[int, bytes]
    player_info_final_words: tuple[int, ...]
    sections: dict[str, bytes]
    raw: bytes


@dataclass(frozen=True, slots=True)
class SavedScenario:
    offset: int
    end_offset: int
    base: SavedScenarioBase
    extension: SavedScenarioExtension
    raw: bytes


def read_scenario(reader: SaveReader) -> SavedScenario:
    """Read native TribeScenario's complete base and current derived extension."""
    start = reader.pos
    try:
        base = read_scenario_base(reader)
        extension = read_scenario_extension(
            reader, version_bits=base.version_bits, max_players=base.max_players
        )
        return SavedScenario(start, reader.pos, base, extension, reader.data[start : reader.pos])
    except SaveDecodeError:
        reader.pos = start
        raise


def _words(r: SaveReader, count: int) -> tuple[int, ...]:
    if not 0 <= count <= r.remaining // 4:
        raise SaveDecodeError(f"invalid scenario word count {count}", r.pos)
    return tuple(r.u32() for _ in range(count))


def _disabled(r: SaveReader, players: int) -> SavedScenarioDisabled:
    start = r.pos
    counts = tuple(
        value if value < 0x80000000 else value - 0x100000000 for value in _words(r, players)
    )
    rows = []
    for count in counts:
        if count < 0:
            raise SaveDecodeError(f"negative disabled scenario count {count}", start)
        # Native current-version branch reads entries only for counts<0x7fff.
        # Preserve other count words with empty rows; no candidate semantics
        # are assigned to that native branch here.
        rows.append(_words(r, count) if count < 0x7FFF else ())
    return SavedScenarioDisabled(counts, tuple(rows), r.data[start : r.pos])


def read_scenario_extension(
    reader: SaveReader, *, version_bits: int, max_players: int
) -> SavedScenarioExtension:
    """Read the current extension using BaseScenario's version/player capacity.

    Arrays use that saved capacity, which is distinct from the world player
    count. Fields are keyed by native member offsets. Anonymous checksums and
    fixed wire records remain raw; they are never interpreted as pointers.
    """
    start = reader.pos
    try:
        if reader.version != 0x44E666 or version_bits != 0x3FCB851F:
            raise SaveDecodeError("unsupported scenario extension version", start)
        if not 0 <= max_players <= reader.remaining // (28 + 0x2D0):
            raise SaveDecodeError(f"invalid scenario player capacity {max_players}", start)
        sections: dict[str, bytes] = {}

        def section(name: str, at: int) -> None:
            sections[name] = reader.data[at : reader.pos]

        at = reader.pos
        player_info = tuple(_words(reader, 7) for _ in range(max_players))
        checksum1 = reader.u32()
        words = {0x3A0: _words(reader, 6)}
        fields = {offset: reader.u32() for offset in (0x400, 0x458, 0x45C, 0x460)}
        section("player_info_and_victory", at)
        at = reader.pos
        if max_players * max_players > reader.remaining // 4:
            raise SaveDecodeError("truncated scenario opponent matrix", reader.pos)
        attitudes = tuple(_words(reader, max_players) for _ in range(max_players))
        section("opponent_attitudes", at)
        at = reader.pos
        raw_records = tuple(reader.take(0x2D0) for _ in range(max_players))
        checksum2 = reader.u32()
        words[0x3E8] = _words(reader, max_players)
        fields.update((offset, reader.u8()) for offset in (0x40C, 0x40D, 0x40E, 0x40F))
        section("player_records_allied_victory_and_flags", at)
        disabled = {}
        for offset in (0x2D8, 0x308, 0x338):
            at = reader.pos
            disabled[offset] = _disabled(reader, max_players)
            section(f"disabled_{offset:x}", at)
        at = reader.pos
        words[0x430] = _words(reader, 3)
        words[0x440] = _words(reader, max_players)
        checksum3 = reader.u32()
        fields.update((offset, reader.u32()) for offset in (0x380, 0x384, 0x464))
        byte_arrays = {0x350: reader.take(max_players)}
        fields[0x410] = reader.u32()
        section("options_ages_priorities_and_trigger_count", at)
        at = reader.pos
        for offset in (0x468, 0x480, 0x498):
            byte_arrays[offset] = reader.de_bytes()
        fields[0x4B0], fields[0x4B1] = reader.u8(), reader.u8()
        words[0x368] = _words(reader, max_players * 2)
        fields[0x4B2] = reader.u8()
        final_words = _words(reader, max_players)
        fields[0x4B4] = reader.u32()
        section("strings_flags_player_words_and_secondary_modes", at)
        return SavedScenarioExtension(
            start,
            reader.pos,
            max_players,
            player_info,
            (checksum1, checksum2, checksum3),
            fields,
            words,
            attitudes,
            raw_records,
            disabled,
            byte_arrays,
            final_words,
            sections,
            reader.data[start : reader.pos],
        )
    except SaveDecodeError:
        reader.pos = start
        raise
