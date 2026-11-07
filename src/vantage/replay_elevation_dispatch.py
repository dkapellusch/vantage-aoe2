"""Logical effects of three established virtual68 elevation implementations.

Build54800: base141252780, Moving141218df0, Projectile141202fa0.
See world-tile-elevation-dispatch-source-v1 for constructor/vtable bindings.
Callers select the actual current target, not an inferred saved family tag.
Encoded qword high bits, FP status and complete position setup are excluded.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .replay_elevation import update_replay_elevation

ReplayElevationTarget = Literal["base", "moving", "projectile"]


@dataclass(frozen=True, slots=True)
class ReplayElevationDispatch:
    """Logical Z, actual XMM0 return word and optional grounded390 write.

    None means the target does not write grounded; it must preserve any prior
    field value. The Projectile sentinel is a return value, not stored Z.
    """

    height_bits: int
    return_bits: int
    grounded_write: bool | None


def dispatch_replay_elevation(
    height_bits: int,
    terrain_height_bits: int,
    *,
    target: ReplayElevationTarget,
    elevation_mode: int | None,
    has_tile: bool | None,
    projectile_state61c: int | None = None,
) -> ReplayElevationDispatch:
    """Apply the selected target's logical effect using current phase inputs.

    Base updates height and returns it, without writing grounded or reading
    tile presence. Moving also writes grounded using ordered equality and
    current tile nullness. Projectile reads its current byte61c first: nonzero
    preserves height, clears grounded and returns rawc2c7cccd. Zero tail-calls
    Moving. Unread mode/tile inputs may be None on the nonzero branch; do not
    invent current master/tile context from a saved reader's earlier defaults.

    Raw stores preserve signaling NaN and signed-zero words. The shared
    comparison profile assumes default masked MXCSR with DAZ/FTZ off. This
    neither invokes callbacks nor recreates encoded qword high-word stores.
    """
    if target not in ("base", "moving", "projectile"):
        raise ValueError("elevation target must be base, moving or projectile")
    for word in (height_bits, terrain_height_bits):
        if type(word) is not int or not 0 <= word <= 0xFFFFFFFF:
            raise ValueError("elevation arguments must be binary32 u32 words")
    if target == "projectile":
        if type(projectile_state61c) is not int or not 0 <= projectile_state61c <= 255:
            raise ValueError("Projectile requires its current unsigned byte61c")
        if projectile_state61c:
            return ReplayElevationDispatch(height_bits, 0xC2C7CCCD, False)
    if type(elevation_mode) is not int or not 0 <= elevation_mode <= 255:
        raise ValueError("elevation mode must be a current unsigned byte")
    if target == "base":
        # Base never reads138 or writes390. The policy helper's grounded
        # output is deliberately discarded, not committed as object state.
        result = update_replay_elevation(
            height_bits,
            terrain_height_bits,
            elevation_mode,
            has_tile=False,
        )
        return ReplayElevationDispatch(result.height_bits, result.height_bits, None)
    if type(has_tile) is not bool:
        raise ValueError("Moving elevation requires current tile nullness as a bool")
    result = update_replay_elevation(
        height_bits,
        terrain_height_bits,
        elevation_mode,
        has_tile=has_tile,
    )
    return ReplayElevationDispatch(result.height_bits, result.height_bits, result.grounded)
