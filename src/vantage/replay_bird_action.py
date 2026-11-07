"""DE54800 bird-action activation callbacks and entry to waiting state3.

These components do not select/install default actions, update flight paths,
execute position setters or own child-action lists. The caller must perform
the returned callbacks in order; entering state3 first clears child actions.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from vantage.replay_random import ReplayRandomState, draw_replay_random_i15


@dataclass(frozen=True, slots=True)
class ReplayBirdCallback:
    kind: str
    arguments: tuple[int, ...]


def replay_bird_activation(
    x_bits: int,
    y_bits: int,
    *,
    enabled: int,
    elevation_mode: int,
    task_flag: int,
    owner_index: int,
) -> tuple[ReplayBirdCallback, ...]:
    """Original140b74900; position arguments are raw binary32 words, ordered XYZ."""
    for value in (x_bits, y_bits, owner_index):
        if not isinstance(value, int) or not 0 <= value <= 0xFFFFFFFF:
            raise ValueError("bird position words and owner index must be u32")
    for value in (enabled, elevation_mode, task_flag):
        if not isinstance(value, int) or not 0 <= value <= 255:
            raise ValueError("bird activation flags must be bytes")
    callbacks = []
    if enabled and task_flag and owner_index:
        callbacks.append(ReplayBirdCallback("state", (1,)))
    if enabled and elevation_mode == 1:
        callbacks.append(ReplayBirdCallback("position", (x_bits, y_bits, 0x41100000)))
    callbacks.append(ReplayBirdCallback("state", (3,)))
    return tuple(callbacks)


@dataclass(frozen=True, slots=True)
class ReplayBirdWait:
    timer_bits: int
    random_state: ReplayRandomState


def enter_replay_bird_wait(random_state: ReplayRandomState) -> ReplayBirdWait:
    """Original140b74a50 state3, after clearing the child action manager.

    This consumes exactly one masked draw from the Action stream. The native
    integer division happens before float conversion, producing5..15 seconds.
    Caller owns storing state3 and clearing children, including their effects.
    """
    draw = draw_replay_random_i15(random_state)
    seconds = draw.value * 10 // 32767 + 5
    return ReplayBirdWait(struct.unpack("<I", struct.pack("<f", seconds))[0], draw.state)
