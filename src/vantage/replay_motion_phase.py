"""One native motion phase: update velocity and produce intended setter inputs.

Original141075310 writes motion+8 before invoking virtual5f8 translation.
The caller supplies the current cap and explicit null-formation admission.
No position, terrain, index, action or world state is committed here.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from .replay_movement_controller import (
    advance_unformed_replay_velocity,
    replay_translation_setter_inputs,
)
from .replay_movement_geometry import Float32Vector, _op


class UnsupportedReplayMotionPhase(ValueError):
    """The current formation context requires an unported velocity branch."""


@dataclass(frozen=True, slots=True)
class ReplayMotionPhaseResult:
    motion_record: bytes
    intended_setter_position: Float32Vector | None


def advance_replay_motion_phase(
    motion_record: bytes,
    stored_position: Float32Vector,
    stored_direction: Float32Vector,
    elapsed_bits: int,
    multiplier414_bits: int,
    speed_cap_bits: int,
    *,
    formation_id: int,
) -> ReplayMotionPhaseResult:
    """Return updated 24B motion and optional intended x,height,y coordinates.

    Only velocity word+8 changes; the other 20 bytes retain their original bits.
    Acceleration is word+0x14. Original141604060 returns null for formation ID-1;
    other IDs need world/formation behavior outside this phase. The resolved
    cap must come from current state. Scalars and vectors use raw binary32.

    The native-rounded elapsed*newVelocity is supplied to translation, which
    applies member414 and its setter threshold. A None result still preserves
    the velocity update. The caller separately performs an admitted position
    commit and subsequent action/world phases. Native default MXCSR is required.
    """
    if type(motion_record) is not bytes or len(motion_record) != 24:
        raise ValueError("explicit 24-byte immutable current motion record required")
    if type(formation_id) is not int or formation_id != -1:
        raise UnsupportedReplayMotionPhase("explicit formation_id=-1 is required")
    velocity = advance_unformed_replay_velocity(
        struct.unpack_from("<I", motion_record, 8)[0],
        struct.unpack_from("<I", motion_record, 20)[0],
        elapsed_bits,
        speed_cap_bits,
    )
    updated = motion_record[:8] + struct.pack("<I", velocity) + motion_record[12:]
    position = replay_translation_setter_inputs(
        stored_position,
        stored_direction,
        _op(elapsed_bits, velocity, "*"),
        multiplier414_bits,
    )
    return ReplayMotionPhaseResult(updated, position)
