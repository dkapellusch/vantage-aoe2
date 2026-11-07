"""Sequential replay restoration prefix for DE build54800/save68.9.

This joins the file header, outer rule systems, BaseWorld first pass and
per-player second-pass records. It stops before the saved scenario section.
It preserves wire state; native reference fixups and simulation remain separate.
"""

from __future__ import annotations

from dataclasses import dataclass

from vantage.replay_binary import SaveDecodeError, SaveReader
from vantage.replay_file_header import SavedReplayFileHeader, read_file_header
from vantage.replay_initial_world import SavedInitialWorld, read_initial_world
from vantage.replay_player_restore import SavedPlayerRestore, read_player_restore
from vantage.replay_world_rules import SavedWorldRules, read_world_rules


@dataclass(frozen=True, slots=True)
class SavedReplayRestorePrefix:
    offset: int
    end_offset: int
    header: SavedReplayFileHeader
    rules: SavedWorldRules
    world: SavedInitialWorld
    player_restores: tuple[SavedPlayerRestore, ...]
    raw: bytes


def read_replay_restore_prefix(reader: SaveReader) -> SavedReplayRestorePrefix:
    """Read from a replay's inflated header, leaving the scenario untouched.

    Native header140fbe670 hands the stream to World14169bd10. Its BaseWorld
    first pass14160d710 then calls1417367c0 for each saved player. The player
    count comes from that world, including Gaia. A nested failure restores the
    caller's starting position, even after all first-pass players were read.
    """
    start = reader.pos
    try:
        header = read_file_header(reader)
        rules = read_world_rules(reader)
        world = read_initial_world(reader)
        restores = tuple(read_player_restore(reader) for _ in world.players)
        return SavedReplayRestorePrefix(
            start, reader.pos, header, rules, world, restores, reader.data[start : reader.pos]
        )
    except SaveDecodeError:
        reader.pos = start
        raise
