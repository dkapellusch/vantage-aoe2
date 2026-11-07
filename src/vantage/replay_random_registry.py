"""DE54800 ordered random-stream reseeding and engine-only checkpoints.

These transitions model valid stream buffers and successful checkpoint
allocation. Registry slots retain their supplied order; null slots are skipped.
They do not choose World phases, replay cadence or random draws for callers.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from vantage.replay_random import (
    ReplayRandomState,
    draw_replay_random_u32,
    seed_replay_random,
)

# Original initializer slots14319f6a8..14319f6f8, under the CRT table-walk
# contract. Historical module heap membership/order was not captured.
REPLAY_RANDOM_STREAM_NAMES = (
    "Action RNG",
    "Random Map RNG",
    "Sprite RNG",
    "World RNG",
    "AI RNG",
    "Object RNG",
    "Player RNG",
    "Editor RNG",
    "Unsynced RNG",
    "Comm RNG",
    "UI RNG",
)
REPLAY_RANDOM_STREAM_ADDRESSES = (
    0x144352EB0,
    0x144352F40,
    0x144352FD0,
    0x144353060,
    0x1443530F0,
    0x144353180,
    0x144353210,
    0x1443532A0,
    0x144353330,
    0x1443533C0,
    0x144353450,
)


@dataclass(frozen=True, slots=True)
class ReplayRandomCheckpoint:
    words: tuple[int, ...]
    index: int

    def __post_init__(self) -> None:
        # The checkpoint has precisely the same engine validity requirements.
        ReplayRandomState(self.words, self.index)


@dataclass(frozen=True, slots=True)
class ReplayRandomRegistry:
    streams: tuple[ReplayRandomState | None, ...]
    checkpoints: tuple[tuple[ReplayRandomCheckpoint, ...], ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.streams, tuple) or any(
            state is not None and not isinstance(state, ReplayRandomState) for state in self.streams
        ):
            raise ValueError("random registry streams must be a tuple of states or null slots")
        if not isinstance(self.checkpoints, tuple):
            raise ValueError("random checkpoint stacks must be a tuple")
        if not self.checkpoints:
            object.__setattr__(self, "checkpoints", tuple(() for _ in self.streams))
        if len(self.checkpoints) != len(self.streams):
            raise ValueError("random checkpoint stacks must match registry slots")
        for state, stack in zip(self.streams, self.checkpoints, strict=True):
            if not isinstance(stack, tuple) or any(
                not isinstance(checkpoint, ReplayRandomCheckpoint) for checkpoint in stack
            ):
                raise ValueError("each random checkpoint stack must be a tuple of checkpoints")
            if state is None and stack:
                raise ValueError("null registry slots cannot carry checkpoints")


def seed_replay_random_registry(registry: ReplayRandomRegistry, seed: int) -> ReplayRandomRegistry:
    """Native Srand140fddbf0: seed each stream, draw its full next-stream seed."""
    if not isinstance(seed, int) or not 0 <= seed <= 0xFFFFFFFF:
        raise ValueError("random registry seed must be a u32")
    streams: list[ReplayRandomState | None] = []
    for state in registry.streams:
        if state is None:
            streams.append(None)
            continue
        draw = draw_replay_random_u32(seed_replay_random(seed, previous=state))
        streams.append(draw.state)
        seed = draw.value
    return ReplayRandomRegistry(tuple(streams), registry.checkpoints)


def push_replay_random_registry(registry: ReplayRandomRegistry) -> ReplayRandomRegistry:
    """Native140fddba0/140902f10: push words and index on each active stream."""
    stacks = tuple(
        stack if state is None else (*stack, ReplayRandomCheckpoint(state.words, state.index))
        for state, stack in zip(registry.streams, registry.checkpoints, strict=True)
    )
    return ReplayRandomRegistry(registry.streams, stacks)


def pop_replay_random_registry(registry: ReplayRandomRegistry) -> ReplayRandomRegistry:
    """Native140fddb50/140902dd0: pop engine bits; keep live calls and last result.

    An active stream with an empty stack is unchanged. Stack depths are
    independent, as they are in the native per-stream checkpoint buffers.
    """
    streams: list[ReplayRandomState | None] = []
    stacks = []
    for state, stack in zip(registry.streams, registry.checkpoints, strict=True):
        if state is None or not stack:
            streams.append(state)
            stacks.append(stack)
        else:
            checkpoint = stack[-1]
            streams.append(replace(state, words=checkpoint.words, index=checkpoint.index))
            stacks.append(stack[:-1])
    return ReplayRandomRegistry(tuple(streams), tuple(stacks))
