"""Logical same-tile position setters for the explicit Unit70 backing profile.

Original Common1412665c0, Moving141225790 and Unit7014115bb20 are separately
selected entries. Whole original entries produced96 independent output rows;
48 modern-disabled rows admit this port. Rendering, host clocks, protected
cipher high words, tile migration and combined modern mutation are excluded.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .replay_elevation import update_replay_elevation
from .replay_legacy_mutation import LegacyContactRegistry
from .replay_movement_geometry import Float32Vector, _bits, _float, _op

ReplayPositionEntry = Literal["common", "moving", "unit70"]
_EPSILON = 0x33D6BF95
_RADII = (0x3E99999A, 0x3E99999A, 0x40000000)


class UnsupportedPositionCommit(ValueError):
    """Position commit needs a branch outside the declared logical profile."""


def _u32(value: int, label: str) -> None:
    if type(value) is not int or not 0 <= value <= 0xFFFFFFFF:
        raise ValueError(f"{label} must be a u32 word")


def _vector(value: Float32Vector) -> None:
    if not isinstance(value, tuple) or len(value) != 3:
        raise ValueError("position requires three immutable binary32 words")
    for word in value:
        _u32(word, "position component")
        if word & 0x7F800000 == 0x7F800000 or abs(_float(word)) > 4096:
            raise UnsupportedPositionCommit("position must be finite with magnitude<=4096")


@dataclass(frozen=True, slots=True)
class ReplayLogicalPosition:
    """Decoded logical state; vector order is x,height,y for both vectors."""

    position_bits: Float32Vector
    grounded: bool
    stored_position_bits: Float32Vector
    clock408: int
    counter40c: int

    def __post_init__(self) -> None:
        _vector(self.position_bits)
        _vector(self.stored_position_bits)
        if type(self.grounded) is not bool:
            raise ValueError("grounded390 must be a boolean")
        _u32(self.clock408, "clock408")
        _u32(self.counter40c, "counter40c")


@dataclass(frozen=True, slots=True)
class ReplaySameTileCommitProfile:
    """Explicit current fields and absence gates; no saved-state inference.

    This first profile fixes the independently executed branch: modern disabled,
    kind5, F2=2, radii(.3,.3,2), state2, positive.7 cap and flat cached terrain.
    All three entries use the Unit70 backing vtable, including virtual+68.
    """

    modern_enabled: bool
    master_kind: int
    master_index_field: int
    radius_bits: Float32Vector
    object_state188: int
    collision_disable1c6: int
    parent148_present: bool
    attachment_count: int
    damage_controller_count: int
    master_trail_mode: int
    master_terrain_effect: int
    terrain_effect_count: int
    terrain_cache_matches: bool
    tile_slope: int
    tile_height: int
    elevation_mode: int
    speed_cap_bits: int

    def __post_init__(self) -> None:
        for value in (self.modern_enabled, self.parent148_present, self.terrain_cache_matches):
            if type(value) is not bool:
                raise ValueError("position profile flags must be explicit booleans")
        values = (
            self.master_kind,
            self.master_index_field,
            self.object_state188,
            self.collision_disable1c6,
            self.attachment_count,
            self.damage_controller_count,
            self.master_trail_mode,
            self.master_terrain_effect,
            self.terrain_effect_count,
            self.tile_slope,
            self.tile_height,
            self.elevation_mode,
            self.speed_cap_bits,
        )
        for word in values:
            _u32(word, "position profile field")
        _vector(self.radius_bits)
        if self.modern_enabled:
            raise UnsupportedPositionCommit("combined modern position mutation is not supported")
        if (self.master_kind, self.master_index_field, self.radius_bits) != (5, 2, _RADII):
            raise UnsupportedPositionCommit("position requires the declared kind5/radius profile")
        if self.object_state188 != 2 or self.collision_disable1c6 != 0:
            raise UnsupportedPositionCommit("position index-admission fields are outside profile")
        if self.parent148_present or self.attachment_count or self.damage_controller_count:
            raise UnsupportedPositionCommit("position requires no parent/attachments/damage links")
        if (self.master_trail_mode, self.master_terrain_effect, self.terrain_effect_count) != (
            0,
            7,
            0,
        ):
            raise UnsupportedPositionCommit("position requires the declared empty effect branches")
        if not self.terrain_cache_matches or self.tile_slope != 0:
            raise UnsupportedPositionCommit("position requires a matching cached flat tile")
        if self.tile_height not in (0, 2) or self.elevation_mode not in (0, 1, 2):
            raise UnsupportedPositionCommit("position terrain/elevation profile is unsupported")
        if self.speed_cap_bits != 0x3F333333:
            raise UnsupportedPositionCommit("position requires explicit effective cap.7")


@dataclass(frozen=True, slots=True)
class ReplayLogicalPositionCommit:
    state: ReplayLogicalPosition
    terrain_return_bits: int
    legacy_refreshed: bool


class ReplayPositionCommitter:
    """Bind one mutable legacy registry, with explicit one-time snapshot cost.

    The registry must be initialized on the200x200 modern-disabled map. Commit
    checks all arguments and constructs the immutable result before refresh.
    The existing registry rejects unported growth/allocation before mutating.
    This supported-profile rejection policy does not promise native allocation
    failure would roll back coordinate writes performed before the native index.
    """

    def __init__(self, registry: LegacyContactRegistry) -> None:
        if not isinstance(registry, LegacyContactRegistry):
            raise ValueError("position commit requires a legacy registry")
        initial = registry.snapshot()
        if initial.modern_enabled or (initial.width, initial.height) != (200, 200):
            raise UnsupportedPositionCommit("position requires the200x200 modern-disabled index")
        self._registry = registry
        self._object_ids = {obj.token: obj.object_id for obj in initial.objects}

    def commit(
        self,
        entry: ReplayPositionEntry,
        state: ReplayLogicalPosition,
        target_bits: Float32Vector,
        *,
        profile: ReplaySameTileCommitProfile,
        game_clock: int,
        object_token: int,
    ) -> ReplayLogicalPositionCommit:
        """Return logical setter state and mutate only the admitted legacy index.

        Common preserves stored3bc/c0/c4 and clock408/counter40c. Moving/Unit70 copy
        the full stored vector and set(clock408,counter40c)=(game_clock,0) only when
        an ordered native rounded difference is strictly greater than1e-7.
        Terrain return is the flat tile height, separately from final elevation.

        Old/target horizontal coordinates must lie strictly in(1,199) and truncate
        to the same tile. Other finite inputs in this branch are source-selected
        generalization; the whole-entry corpus samples two horizontal positions,
        four height profiles and clock6388. No presentation fields are synthesized.
        """
        if entry not in ("common", "moving", "unit70"):
            raise UnsupportedPositionCommit("position entry must be common, moving or unit70")
        if not isinstance(state, ReplayLogicalPosition):
            raise ValueError("position commit requires typed logical state")
        if not isinstance(profile, ReplaySameTileCommitProfile):
            raise ValueError("position commit requires an explicit admitted profile")
        _vector(target_bits)
        _u32(game_clock, "explicit gameplay clock")
        if type(object_token) is not int or object_token not in self._object_ids:
            raise ValueError("position commit requires an explicitly registered object token")
        if self._object_ids[object_token] < 0:
            raise UnsupportedPositionCommit("position requires a nonnegative Unit70 object ID")
        for axis in (0, 2):
            old, target = _float(state.position_bits[axis]), _float(target_bits[axis])
            if not (1 < old < 199 and 1 < target < 199):
                raise UnsupportedPositionCommit("position would require unported map/radius clamp")
            if int(old) != int(target):
                raise UnsupportedPositionCommit("position would require unported tile migration")
        terrain = _bits(float(profile.tile_height))
        elevation = update_replay_elevation(
            target_bits[1],
            terrain,
            profile.elevation_mode,
            has_tile=True,
        )
        position = target_bits[0], elevation.height_bits, target_bits[2]
        stored, clock, counter = state.stored_position_bits, state.clock408, state.counter40c
        if entry != "common" and any(
            _float(_op(position[axis], stored[axis], "-") & 0x7FFFFFFF) > _float(_EPSILON)
            for axis in (0, 2, 1)
        ):
            stored, clock, counter = position, game_clock, 0
        result = ReplayLogicalPositionCommit(
            ReplayLogicalPosition(position, elevation.grounded, stored, clock, counter),
            terrain,
            True,
        )
        self._registry.refresh(
            object_token,
            kind=5,
            enabled=True,
            position_bits=(position[0], position[2]),
            radius_bits=(profile.radius_bits[0], profile.radius_bits[1]),
        )
        return result
