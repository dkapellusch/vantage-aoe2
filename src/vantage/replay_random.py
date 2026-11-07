"""DE54800 random-stream arithmetic, derived from the original native routines.

This is one stream's state, not a global seed or a simulation scheduler.
Reseeding replaces only the sixteen engine words and their index. Native
call counts and the last masked result survive reseeding and checkpoints.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

_MASK = 0xFFFFFFFF


def _u32(value: int, name: str) -> None:
    if not isinstance(value, int) or not 0 <= value <= _MASK:
        raise ValueError(f"{name} must be a u32")


@dataclass(frozen=True, slots=True)
class ReplayRandomState:
    words: tuple[int, ...]
    index: int = 0
    calls: int = 0
    last_masked: int = 0xFFFFFFFF

    def __post_init__(self) -> None:
        if not isinstance(self.words, tuple) or len(self.words) != 16:
            raise ValueError("random state must contain sixteen words")
        for word in self.words:
            _u32(word, "random state word")
        if not isinstance(self.index, int) or not 0 <= self.index < 16:
            raise ValueError("random state index must be in 0..15")
        _u32(self.calls, "random call count")
        _u32(self.last_masked, "last masked result")


@dataclass(frozen=True, slots=True)
class ReplayRandomDraw:
    value: int
    state: ReplayRandomState


def seed_replay_random(
    seed: int, *, previous: ReplayRandomState | None = None
) -> ReplayRandomState:
    """Apply native140904060; retain metadata when reseeding an existing stream."""
    _u32(seed, "random seed")
    mixed = int.from_bytes(seed.to_bytes(4, "little"), "big") ^ 0xAAC29377
    words = []
    for _ in range(16):
        mixed = (mixed ^ (mixed << 17)) & _MASK
        mixed ^= mixed >> 13
        mixed = (mixed ^ (mixed << 5)) & _MASK
        seed = (seed * 0x1001 + 0x7ED55D16) & _MASK
        intermediate = ((seed >> 19 ^ seed ^ 0xC761C23C) * 0x21) & _MASK
        seed = (
            (((intermediate + 0x165667B1) << 9) ^ (intermediate + 0xE9F8CC1D)) * 9 + 0xFD7046C5
        ) & _MASK
        seed = seed >> 16 ^ seed ^ 0xB55A4F09
        words.append(seed ^ mixed)
    return ReplayRandomState(
        tuple(words),
        calls=0 if previous is None else previous.calls,
        last_masked=0xFFFFFFFF if previous is None else previous.last_masked,
    )


def _advance(state: ReplayRandomState) -> tuple[int, ReplayRandomState]:
    words = list(state.words)
    index = state.index
    a, offset3, offset7 = words[index], words[(index - 3) & 15], words[(index - 7) & 15]
    b = ((((a << 1) ^ offset3) << 15) ^ offset3 ^ a) & _MASK
    c = (offset7 >> 11) ^ offset7
    d = b ^ c
    words[index] = d
    index = (index - 1) & 15
    old = words[index]
    value = ((((((c << 10) ^ b) << 13) ^ (d & 0xFED22169)) << 3 ^ old) << 2 ^ old ^ d ^ b) & _MASK
    words[index] = value
    return value, ReplayRandomState(
        tuple(words), index, (state.calls + 1) & _MASK, state.last_masked
    )


def draw_replay_random_u32(state: ReplayRandomState) -> ReplayRandomDraw:
    """Native140903af0: advance and return the full word, leaving last_masked."""
    value, after = _advance(state)
    return ReplayRandomDraw(value, after)


def draw_replay_random_u64(state: ReplayRandomState) -> ReplayRandomDraw:
    """Native140903bc0: two engine steps, first word high, one counted call.

    Production uses this wrapper when selecting the villager variant. The
    last masked result remains unchanged despite consuming two engine words.
    """
    high, after = _advance(state)
    low, after = _advance(after)
    return ReplayRandomDraw((high << 32) | low, replace(after, calls=(state.calls + 1) & _MASK))


def draw_replay_random_i15(state: ReplayRandomState) -> ReplayRandomDraw:
    """Native140903e40: advance and retain the low fifteen bits at stream+88."""
    value, after = _advance(state)
    value &= 0x7FFF
    return ReplayRandomDraw(value, replace(after, last_masked=value))


def draw_replay_random_range(state: ReplayRandomState, limit: int) -> ReplayRandomDraw:
    """Native140903a00: multiply-high into [0, limit); zero only counts a call."""
    _u32(limit, "random range limit")
    if limit == 0:
        return ReplayRandomDraw(0, replace(state, calls=(state.calls + 1) & _MASK))
    value, after = _advance(state)
    return ReplayRandomDraw((value * limit) >> 32, after)
