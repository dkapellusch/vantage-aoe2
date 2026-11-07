"""Per-owner UnitAI elapsed banks for a completed native BaseWorld pass.

BaseWorld141628bf0 adds World+0x7c to each owner's word at+0x18c immediately
before that player's phase. After the later dopple/resource phases it clears
the selected owner's word and rotates World+0x188, including Gaia. This is
separate from recorded game-clock advancement and strategic player AI.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ReplayAIClock:
    """A valid selected owner and the saved raw u32 elapsed words, Gaia first.

    Native reads and writes do not validate the selected index. This model
    rejects invalid indices instead of reproducing out-of-bank memory access.
    Its player count comes from the bank length, including Gaia.
    """

    selected_owner: int
    elapsed_words: tuple[int, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.elapsed_words, tuple) or not self.elapsed_words:
            raise ValueError("UnitAI elapsed bank must be a nonempty tuple of u32 words")
        if any(
            not isinstance(word, int) or not 0 <= word <= 0xFFFFFFFF for word in self.elapsed_words
        ):
            raise ValueError("UnitAI elapsed bank must contain only u32 words")
        if not isinstance(self.selected_owner, int) or not 0 <= self.selected_owner < len(
            self.elapsed_words
        ):
            raise ValueError("UnitAI selected owner must index the elapsed bank")

    def is_selected_owner(self, owner: int) -> bool:
        """The exact word equality used by native141608320, without indexing."""
        if not isinstance(owner, int) or not 0 <= owner <= 0xFFFFFFFF:
            raise ValueError("UnitAI owner comparison requires a u32 word")
        return owner == self.selected_owner

    def elapsed_i32(self, owner: int) -> int:
        """Signed i32 view of native141604210's returned word bits.

        The common UnitAI callback takes these same bits as u32. Keep the
        original words when passing that argument or serializing state.
        """
        if not isinstance(owner, int) or not 0 <= owner < len(self.elapsed_words):
            raise ValueError("UnitAI elapsed owner must index the elapsed bank")
        word = self.elapsed_words[owner]
        return word - 0x100000000 if word >= 0x80000000 else word


@dataclass(frozen=True, slots=True)
class ReplayAIClockPhase:
    """Bank state just after one player's addition and before its callbacks."""

    player_index: int
    clock: ReplayAIClock


@dataclass(frozen=True, slots=True)
class ReplayAIClockStep:
    previous: ReplayAIClock
    delta_ms: int
    phases: tuple[ReplayAIClockPhase, ...]
    after: ReplayAIClock


def advance_replay_ai_clock(clock: ReplayAIClock, delta_ms: int) -> ReplayAIClockStep:
    """Model one entered BaseWorld player pass using its raw u32 delta.

    Each phase retains the ordered bank state, so later owners have not yet
    received this delta when earlier players run. The final state follows
    the later all-player dopple/resource phases, selected-bank clear and
    rotation, before the victory callback. Arithmetic wraps at32 bits.

    Even zero delta rotates on a completed pass. The caller must establish
    that the native pass runs: paused/skipped updates, parsed sync records
    and spectator samples do not by themselves request this transition.
    This function runs no callbacks and models no other engine behavior.
    """
    if not isinstance(delta_ms, int) or not 0 <= delta_ms <= 0xFFFFFFFF:
        raise ValueError("UnitAI pass delta must be a u32 millisecond value")
    words = list(clock.elapsed_words)
    phases = []
    for player_index, elapsed in enumerate(clock.elapsed_words):
        words[player_index] = (elapsed + delta_ms) & 0xFFFFFFFF
        phase_clock = ReplayAIClock(clock.selected_owner, tuple(words))
        phases.append(ReplayAIClockPhase(player_index, phase_clock))
    words[clock.selected_owner] = 0
    next_owner = clock.selected_owner + 1
    if next_owner >= len(words):
        next_owner = 0
    after = ReplayAIClock(next_owner, tuple(words))
    return ReplayAIClockStep(clock, delta_ms, tuple(phases), after)
