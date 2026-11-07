"""Fresh owned engine Game/World roles for build54800 save68.9 restoration.

This is Vantage's authored session bootstrap. It executes no original Game or
World constructor, UI startup, loader wrapper or synchronization entry. The
source-backed selector and Player-vector bodies remain real required calls.
Unmodeled fields stay undefined; this alone does not restore a runnable World.
"""

from __future__ import annotations

from dataclasses import dataclass

from .replay_memory import ReplayMemory
from .replay_task_rebuild import ReplayTaskRebuildCalls, _call
from .replay_world_prefix import SavedWorldPrefix

_GAME_GLOBAL = 0x144353698


@dataclass(frozen=True, slots=True)
class ReplayEngineSession:
    """Chosen engine identities and initial inputs, not cached current state.

    Current callbacks can change globals, links, family or vector headers.
    Consumers must still perform their source reads rather than use this record
    as a replacement for current Game/World/count providers. No Player is
    constructed or published by this bootstrap.
    """

    game: int
    world: int
    wire_player_count: int
    family: int


def create_replay_engine_session(
    memory: ReplayMemory,
    prefix: SavedWorldPrefix,
    *,
    version: int,
    family_descriptor: bytes,
    calls: ReplayTaskRebuildCalls,
) -> ReplayEngineSession:
    """Allocate a fresh shared session, then source-resize its pending slots.

    The engine chooses one World for Game+5c0 and subsequent Player constructor
    arguments. This is a fresh lifecycle: the current-Game global must be
    unmapped. Native allocation extents15d0/9e8 are backing capacities only;
    neither native vtable nor a completed native class is manufactured.

    The raw numPlayers WORD at prefix+47 is signed by native1415e5b20 before
    its DWORD result is captured in ESI. This engine admits1..32767, including
    Gaia, and rejects other encodings before any effects. It does not clamp.
    The descriptor's eight explicit bytes are an engine input, not inferred
    from game mode. Actual140fa36a0 selects World+6b4. Actual14161dbe0 receives
    a live zero pair; all its reached children remain mandatory. Its return
    register is ignored. Reached errors retain prior allocations/publication.

    Source: game-world-link-source-v1 and game-world-engine-context-review-v1.
    Data tables, viewer policy, full Player factory, World fixups and simulation
    are subsequent operations; this function does not clear pending flags.
    """
    if not isinstance(memory, ReplayMemory) or not isinstance(prefix, SavedWorldPrefix):
        raise ValueError("owned replay memory and parsed World prefix required")
    if not isinstance(calls, ReplayTaskRebuildCalls):
        raise ValueError("actual engine bootstrap helper calls required")
    if type(version) is not int or version != 0x44E666:
        raise ValueError("engine session requires save68.9 version44e666")
    if type(family_descriptor) is not bytes or len(family_descriptor) != 8:
        raise ValueError("explicit eight-byte family descriptor required")
    count = prefix.num_players
    if (
        type(count) is not int
        or not 1 <= count <= 0x7FFF
        or type(prefix.raw) is not bytes
        or len(prefix.raw) != 74 + count * 4
        or int.from_bytes(prefix.raw[47:49], "little") != count
        or prefix.end_offset - prefix.offset != len(prefix.raw)
        or len(prefix.player_words) != count
    ):
        raise ValueError("supported signed WORD count and coherent raw World prefix required")

    game = memory.allocate(0x15D0)
    world = memory.allocate(0x9E8)
    memory.write_bytes(game + 0x680, family_descriptor)
    family = _call(calls, 0x140FA36A0, (game + 0x680,), width=4)
    memory.write(world + 0x6B4, 4, family)
    # These three source-proved ancestor stores initialize only the row header.
    for offset in (0x768, 0x770, 0x778):
        memory.write(world + offset, 8, 0)
    memory.write(game + 0x5C0, 8, world)
    memory.map_bytes(_GAME_GLOBAL, game.to_bytes(8, "little"))
    with memory.bind_local(memoryview(bytearray(16))) as zero_pair:
        _call(calls, 0x14161DBE0, (world + 0x768, count, zero_pair))
    return ReplayEngineSession(game, world, count, family)
