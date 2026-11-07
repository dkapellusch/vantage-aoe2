"""Complete ordered player-AI wrapper for native DE save68.9.

This composes ten native decision modules and their enclosing trailer. It
does not execute AI planners or read the following WorldPlayer/XS state.
"""

from __future__ import annotations

from dataclasses import dataclass

from vantage.replay_ai_modules import SavedSimpleAI, read_simple_ai
from vantage.replay_binary import SaveDecodeError, SaveReader
from vantage.replay_build_ai import SavedBuildAI, read_build_ai
from vantage.replay_con_ai import SavedConAI, read_con_ai
from vantage.replay_info_ai import SavedInfoAI, read_info_ai
from vantage.replay_tactical_ai import SavedTacticalAI, read_tactical_ai


@dataclass(frozen=True, slots=True)
class SavedPlayerAITrailer:
    fields: dict[int, int]
    player_words: tuple[int, ...]
    raw: bytes


@dataclass(frozen=True, slots=True)
class SavedPlayerAI:
    offset: int
    end_offset: int
    num_players: int
    main: SavedSimpleAI
    build: SavedBuildAI
    construction: SavedConAI
    diplomacy: SavedSimpleAI
    emotional: SavedSimpleAI
    information: SavedInfoAI
    resource: SavedSimpleAI
    strategy: SavedSimpleAI
    tactical: SavedTacticalAI
    trade: SavedSimpleAI
    trailer: SavedPlayerAITrailer
    raw: bytes


def _marker(r: SaveReader, expected: int) -> None:
    at = r.pos
    value = r.u16()
    if value != expected:
        raise SaveDecodeError(f"expected player-AI marker {expected:#x}, found {value:#x}", at)


def _trailer(r: SaveReader, num_players: int) -> SavedPlayerAITrailer:
    # Native0x140c7ebe0 after all module constructors: 90+4*N bytes.
    start = r.pos
    _marker(r, 0xA10)
    fields = {offset: r.u32() for offset in range(0x28F50, 0x28F7C, 4)}
    # +0x28f80 is a vector pointer, not an inline array whose elements
    # overwrite the following +0x28f98 scalar block in native memory.
    words = tuple(r.u32() for _ in range(num_players))
    _marker(r, 0xAA0)
    fields.update({offset: r.u32() for offset in range(0x28F98, 0x28FC0, 4)})
    _marker(r, 0xA20)
    return SavedPlayerAITrailer(fields, words, r.data[start : r.pos])


def read_player_ai(reader: SaveReader, num_players: int) -> SavedPlayerAI:
    """Read the entire wrapper; failure rolls back all earlier modules.

    ``num_players`` is the restored world player-vector length, including
    Gaia. It controls uncounted arrays in InfoAI, TacticalAI and the trailer.
    A successful return leaves the following WorldPlayer byte untouched.
    """
    start = reader.pos
    try:
        if reader.version != 0x44E666:
            raise SaveDecodeError(f"unsupported player-AI save version {reader.version:#x}", start)
        if not 1 <= num_players <= reader.remaining // 32:
            raise SaveDecodeError(f"invalid player-AI world player count {num_players}", start)
        main = read_simple_ai(reader, "main")
        build = read_build_ai(reader)
        construction = read_con_ai(reader)
        diplomacy = read_simple_ai(reader, "diplomacy")
        emotional = read_simple_ai(reader, "emotional")
        information = read_info_ai(reader, num_players)
        resource = read_simple_ai(reader, "resource")
        strategy = read_simple_ai(reader, "strategy")
        tactical = read_tactical_ai(reader, num_players)
        trade = read_simple_ai(reader, "trade")
        trailer = _trailer(reader, num_players)
        return SavedPlayerAI(
            start,
            reader.pos,
            num_players,
            main,
            build,
            construction,
            diplomacy,
            emotional,
            information,
            resource,
            strategy,
            tactical,
            trade,
            trailer,
            reader.data[start : reader.pos],
        )
    except SaveDecodeError:
        reader.pos = start
        raise
