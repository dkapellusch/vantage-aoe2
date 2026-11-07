"""Native replay-clock arithmetic, independent of playback/render scheduling.

CommCommandLog140dec770 reads operation2's u32 delta into log+0x94.
BaseWorld141628bf0 adds that delta to its entry clock as a wrapping u32,
then writes f32(u32(delta))/1000.0f into World+0x164. Recorded syncs provide
the cadence; sampled spectator frames and wall/replay speed do not define it.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass


def _f32(value: float) -> float:
    return float(struct.unpack("<f", struct.pack("<f", value))[0])


@dataclass(frozen=True, slots=True)
class ReplayClockStep:
    previous_ms: int
    time_ms: int
    delta_ms: int
    seconds_bits: int

    @property
    def seconds(self) -> float:
        """Exact binary32 value stored at native World+0x164."""
        return float(struct.unpack("<f", struct.pack("<I", self.seconds_bits))[0])


def advance_replay_clock(clock_ms: int, delta_ms: int) -> ReplayClockStep:
    """Apply one recorded sync delta using native u32 and binary32 arithmetic.

    Inputs are serialized u32 game milliseconds. A zero delta is retained;
    callers decide when to run updates from the original operation order.
    Pause/speed controls govern scheduling and do not rescale this log delta.
    This function neither advances objects nor claims simulation fidelity.
    """
    if not isinstance(clock_ms, int) or not 0 <= clock_ms <= 0xFFFFFFFF:
        raise ValueError("replay clock must be a u32 millisecond value")
    if not isinstance(delta_ms, int) or not 0 <= delta_ms <= 0xFFFFFFFF:
        raise ValueError("replay delta must be a u32 millisecond value")
    # Native CVTSI2SS converts zero-extended u32 to f32 before DIVSS. Rounding
    # just the final quotient loses this first conversion for large deltas.
    seconds = _f32(_f32(float(delta_ms)) / 1000.0)
    seconds_bits = int(struct.unpack("<I", struct.pack("<f", seconds))[0])
    return ReplayClockStep(clock_ms, (clock_ms + delta_ms) & 0xFFFFFFFF, delta_ms, seconds_bits)
