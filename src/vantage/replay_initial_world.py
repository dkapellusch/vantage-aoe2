"""Sequential BaseWorld first pass through all initial players (save68.9).

The caller starts after the outer World rule-system state. This reader ends
before second-pass restoration/fixups; it does not yet produce a runnable
world or locate this section in an arbitrary recording's file header.
"""

from __future__ import annotations

from dataclasses import dataclass

from vantage.replay_binary import SaveDecodeError, SaveReader
from vantage.replay_initial_player import SavedInitialPlayer, read_initial_player
from vantage.replay_saved_map import (
    SavedMap,
    SavedPostMapWorld,
    read_post_map_world,
    read_saved_map,
)
from vantage.replay_world_prefix import SavedWorldPrefix, read_world_prefix


@dataclass(frozen=True, slots=True)
class SavedInitialWorld:
    offset: int
    end_offset: int
    prefix: SavedWorldPrefix
    map: SavedMap
    post_map: SavedPostMapWorld
    players: tuple[SavedInitialPlayer, ...]
    raw: bytes


def read_initial_world(reader: SaveReader, *, load_flag: int = 0) -> SavedInitialWorld:
    """Read the first pass using its own saved player count, without scans.

    ``load_flag`` is native World14160d710's fourth argument, controlling one
    post-map word. Both paired recordings use zero. Failure in any nested
    player, including saved AI/XS, restores the entire world's starting cursor.
    """
    start = reader.pos
    try:
        prefix = read_world_prefix(reader)
        if prefix.num_players < 1:
            raise SaveDecodeError("initial replay world has no players", start + 47)
        saved_map = read_saved_map(reader)
        post_map = read_post_map_world(reader, load_flag=load_flag)
        players = tuple(
            read_initial_player(reader, prefix.num_players, player_id=player_id)
            for player_id in range(prefix.num_players)
        )
        return SavedInitialWorld(
            start,
            reader.pos,
            prefix,
            saved_map,
            post_map,
            players,
            reader.data[start : reader.pos],
        )
    except SaveDecodeError:
        reader.pos = start
        raise
