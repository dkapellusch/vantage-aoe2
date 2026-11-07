"""Sequential initial-player restoration within the native saved world.

The outer world supplies the player count and factory boundary. This composes
the native-derived sections without scanning for markers or object prefixes.
It preserves serialized state; baseline master defaults and native restoration
fixups still need to be applied before this becomes a simulated player.
"""

from __future__ import annotations

from dataclasses import dataclass

from vantage.replay_binary import SaveDecodeError, SaveReader
from vantage.replay_masters import SavedMasterTable, read_master_table
from vantage.replay_object_lists import SavedPlayerObjectLists, read_player_object_lists
from vantage.replay_player_ai import SavedPlayerAI, read_player_ai
from vantage.replay_players import (
    SavedGaiaExtension,
    SavedPlayer,
    SavedPlayerAIContinuation,
    SavedPlayerPrefix,
    read_gaia_extension,
    read_player_ai_continuation,
    read_player_header,
    read_player_prefix,
)
from vantage.replay_visibility import SavedVisibility, read_visibility


@dataclass(frozen=True, slots=True)
class SavedInitialPlayer:
    offset: int
    end_offset: int
    header: SavedPlayer
    prefix: SavedPlayerPrefix
    gaia_extension: SavedGaiaExtension | None
    masters: SavedMasterTable
    visibility: SavedVisibility
    object_lists: SavedPlayerObjectLists
    raw: bytes
    player_ai: SavedPlayerAI | None = None
    ai_continuation: SavedPlayerAIContinuation | None = None


def read_initial_player(
    reader: SaveReader, num_players: int, *, player_id: int | None = None
) -> SavedInitialPlayer:
    """Read one initial player from its factory byte through the final marker.

    ``num_players`` includes Gaia. Computer players include their saved decision
    modules and WorldPlayer continuation. No game, external service, baseline
    data, or spectator capture is accessed by this reader. Any unsupported or
    malformed nested state restores the entire player's cursor.
    """
    start = reader.pos
    try:
        header = read_player_header(reader, num_players, player_id=player_id)
        prefix = read_player_prefix(reader, header, num_players)
        ai = continuation = None
        if prefix.next_section == "saved_ai":
            ai = read_player_ai(reader, num_players)
            continuation = read_player_ai_continuation(reader)
        gaia = read_gaia_extension(reader) if header.factory_type == 2 else None
        masters = read_master_table(reader)
        reader.marker(11)
        visibility = read_visibility(reader)
        objects = read_player_object_lists(reader)
        return SavedInitialPlayer(
            start,
            reader.pos,
            header,
            prefix,
            gaia,
            masters,
            visibility,
            objects,
            reader.data[start : reader.pos],
            ai,
            continuation,
        )
    except SaveDecodeError:
        reader.pos = start
        raise
