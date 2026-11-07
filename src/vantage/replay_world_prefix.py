"""Saved BaseWorld prefix through the native map-reader call, for save68.9.

Reader0x14160d710 consumes74 fixed bytes and one word per world player.
Member offsets identify words whose full semantics have not been established;
the clock's floating-point word retains its exact bits. The caller must
already have consumed the outer World rule-system state.
"""

from __future__ import annotations

from dataclasses import dataclass

from vantage.replay_binary import SaveDecodeError, SaveReader


@dataclass(frozen=True, slots=True)
class SavedWorldPrefix:
    offset: int
    end_offset: int
    fields: dict[int, int]
    clock_fields: dict[int, int]
    discarded_byte: int
    srand_seed: int
    local_player_index: int
    num_players: int
    option_flag: int
    scenario_flag: int
    game_state: int
    campaign_indices: tuple[int, int, int]
    campaign_section: int
    campaign_sub_index: int
    scenario_sub_index: int
    player_words: tuple[int, ...]
    raw: bytes


def read_world_prefix(reader: SaveReader) -> SavedWorldPrefix:
    """Read up to the map's DEADDEAD/format header, without consuming it.

    The saved player count includes Gaia. Failure restores the starting
    cursor; no search, resynchronization, or runtime constructor fixup occurs.
    """
    start = reader.pos
    try:
        return _read_world_prefix(reader)
    except SaveDecodeError:
        reader.pos = start
        raise


def _read_world_prefix(r: SaveReader) -> SavedWorldPrefix:
    start = r.pos
    if r.version != 0x44E666:
        raise SaveDecodeError(f"unsupported BaseWorld save version {r.version:#x}", start)
    fields = {0x84: r.u32()}
    # Setter0x140e68fa0 writes clock18;0x140e69740 writes float clock10.
    clock_fields = {0x18: r.u32()}
    for offset in (0x78, 0x7C, 0x164, 0x80):
        fields[offset] = r.u32()
    clock_fields[0x10] = r.u32()
    discarded_byte = r.u8()
    fields[0x6C0], fields[0x14C] = r.u32(), r.u32()
    srand_seed = r.u32()  # Restored through native0x140fddbf0, indexed as Srand.
    fields[0x7D0] = r.u32()  # Native diagnostic: mCurrentFrameRandomSeed.
    # Template0x1415e5b20 reads2 bytes despite the native enum's wider storage.
    local_player_index, num_players = r.u16(), r.u16()
    fields[0x6B0] = local_player_index
    option_flag, scenario_flag, game_state = r.u8(), r.u8(), r.u8()
    campaign_indices = (r.u32(), r.u32(), r.u32())
    campaign_section = r.u32()
    campaign_sub_index, scenario_sub_index = r.u8(), r.u8()
    fields[0x188] = r.u32()
    if num_players > r.remaining // 4:
        raise SaveDecodeError(f"truncated BaseWorld player words for {num_players} players", r.pos)
    player_words = tuple(r.u32() for _ in range(num_players))
    return SavedWorldPrefix(
        start,
        r.pos,
        fields,
        clock_fields,
        discarded_byte,
        srand_seed,
        local_player_index,
        num_players,
        option_flag,
        scenario_flag,
        game_state,
        campaign_indices,
        campaign_section,
        campaign_sub_index,
        scenario_sub_index,
        player_words,
        r.data[start : r.pos],
    )
