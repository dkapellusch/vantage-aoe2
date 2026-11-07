"""Complete sequential saved-world wire reader for DE build54800/save68.9.

Reading every saved field does not apply native reference/terrain fixups or
advance a simulation. Unsupported native variants fail with a precise offset.
No game process or connected game API is required by this module.
"""

from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass
from pathlib import Path

from vantage.replay_binary import SaveDecodeError, SaveReader
from vantage.replay_restore_prefix import (
    SavedReplayRestorePrefix,
    read_replay_restore_prefix,
)
from vantage.replay_scenario_extension import SavedScenario, read_scenario
from vantage.replay_stream import ReplayStreamError
from vantage.replay_world_tail import SavedWorldTail, read_world_tail


@dataclass(frozen=True, slots=True)
class SavedReplayWorld:
    offset: int
    end_offset: int
    prefix: SavedReplayRestorePrefix
    scenario: SavedScenario
    tail: SavedWorldTail
    raw: bytes


def read_saved_world(reader: SaveReader) -> SavedReplayWorld:
    """Read the full native world, preserving the caller's cursor on any failure."""
    start = reader.pos
    try:
        prefix = read_replay_restore_prefix(reader)
        scenario = read_scenario(reader)
        tail = read_world_tail(reader)
        return SavedReplayWorld(
            start, reader.pos, prefix, scenario, tail, reader.data[start : reader.pos]
        )
    except SaveDecodeError:
        reader.pos = start
        raise


def load_replay_world(
    path: str | Path,
    *,
    max_inflated_bytes: int = 256 << 20,
    max_compressed_bytes: int = 64 << 20,
) -> SavedReplayWorld:
    """Read the initial compressed world directly from an ordinary recording.

    Limits bound input allocation and decompression independently of claimed lengths.
    Body commands and saved chapters are read separately by replay_stream.
    Any unexplained bytes after the world in this initial header are rejected.
    """
    if max_inflated_bytes < 1 or max_compressed_bytes < 1:
        raise ValueError("saved-world byte limits must be positive")
    with Path(path).open("rb") as stream:
        stream.seek(0, 2)
        size = stream.tell()
        stream.seek(0)
        envelope = stream.read(8)
        if len(envelope) != 8:
            raise ReplayStreamError("truncated saved-world envelope", 0)
        header_end, chapter = struct.unpack("<II", envelope)
        if not 8 < header_end <= size - 32:
            raise ReplayStreamError("invalid saved-world header end", 0)
        if chapter and not header_end + 32 <= chapter <= size - 8:
            raise ReplayStreamError("invalid saved-world chapter pointer", 4)
        if header_end - 8 > max_compressed_bytes:
            raise ReplayStreamError("compressed saved world exceeds configured limit", 8)
        compressed = stream.read(header_end - 8)
    inflater = zlib.decompressobj(-15)
    try:
        data = inflater.decompress(compressed, max_inflated_bytes + 1)
    except zlib.error as error:
        raise ReplayStreamError(f"invalid compressed saved world: {error}", 8) from error
    if len(data) > max_inflated_bytes or inflater.unconsumed_tail:
        raise ReplayStreamError("inflated saved world exceeds configured limit", 8)
    if not inflater.eof:
        raise ReplayStreamError("truncated compressed saved world", 8)
    if inflater.unused_data:
        raise ReplayStreamError("unexpected bytes after compressed saved world", header_end)
    reader = SaveReader(data)
    saved = read_saved_world(reader)
    if reader.remaining:
        raise SaveDecodeError("unconsumed bytes after complete saved world", reader.pos)
    return saved
