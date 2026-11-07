"""Build54800 terrain-effect filters and ordered desired-definition selection.

Sources1414ccc20,1414cc7e0,1414d3c50 and1412475d0, retained in
terrain-effect-context-review-v1. Inputs describe current, stable definitions,
object/master bindings and system contents; saved values alone do not establish
those bindings. This pure stage neither reconciles active records nor executes
effects, ownership callbacks or allocation. Empty output is a desired selection,
not evidence that removing existing effects would be a no-op.
"""

from __future__ import annotations

from dataclasses import dataclass


class UnresolvedReplayTerrainEffectContext(ValueError):
    """Selection reached an object filter without an available current master."""


def _integer(value: int, low: int, high: int, name: str) -> None:
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f"{name} must be an integer in [{low}, {high}]")


def _members(values: frozenset[int], low: int, high: int, name: str) -> None:
    if type(values) is not frozenset:
        raise ValueError(f"{name} must be an explicit frozenset")
    for value in values:
        _integer(value, low, high, name)


@dataclass(frozen=True, slots=True, kw_only=True)
class ReplayTerrainEffectDefinition:
    """One current native definition identity and its exact filter contents.

    Identity is a nonzero u64 pointer token; it is not a master or effect ID.
    All memberships are explicit. Terrain keys are u8. The six object sets
    store canonical signed-i32 keys: raw native0xffffffff is represented as-1.
    Unreachable keys are retained, rather than truncated into matching keys.
    Flags retain every bit; only bit1 affects terrain and bit0 affects objects.
    No effect implementation or ownership-control pointer is fabricated here.
    """

    identity: int
    flags: int
    allow_terrain: frozenset[int]
    deny_terrain: frozenset[int]
    allow_saved_ids: frozenset[int]
    deny_saved_ids: frozenset[int]
    allow_object_groups: frozenset[int]
    deny_object_groups: frozenset[int]
    allow_families: frozenset[int]
    deny_families: frozenset[int]

    def __post_init__(self) -> None:
        _integer(self.identity, 1, (1 << 64) - 1, "definition identity")
        _integer(self.flags, 0, 255, "definition flags")
        for name in ("allow_terrain", "deny_terrain"):
            _members(getattr(self, name), 0, 255, name)
        for name in (
            "allow_saved_ids",
            "deny_saved_ids",
            "allow_object_groups",
            "deny_object_groups",
            "allow_families",
            "deny_families",
        ):
            _members(getattr(self, name), -(1 << 31), (1 << 31) - 1, name)


@dataclass(frozen=True, slots=True)
class ReplayTerrainEffectMasterInput:
    """Normalized current master+18i16,+38i16,+8u8, in that order.

    saved_id is the protected field decoded from master+18; the caller's
    master-table index is a different value. This class does not decode raw
    protected words or establish preservation from a saved master.
    """

    saved_id: int
    object_group: int
    family: int

    def __post_init__(self) -> None:
        _integer(self.saved_id, -32768, 32767, "current master saved_id")
        _integer(self.object_group, -32768, 32767, "current master object_group")
        _integer(self.family, 0, 255, "current master family")


@dataclass(frozen=True, slots=True)
class ReplayTerrainEffectObjectContext:
    """Current object188, tile terrain and optional available current master.

    terrain_id=None explicitly means object138 is known null, giving native
    terrain255. It never means unknown terrain. master=None means unavailable:
    selection raises only when an accepted terrain reaches the object filter.
    Provided values are validated on import even if a later gate skips them.
    No initial pending flag is read or cleared by this context.
    """

    object_188: int
    terrain_id: int | None
    master: ReplayTerrainEffectMasterInput | None

    def __post_init__(self) -> None:
        _integer(self.object_188, 0, 255, "current object188")
        if self.terrain_id is not None:
            _integer(self.terrain_id, 0, 255, "current tile terrain")
        if self.master is not None and not isinstance(self.master, ReplayTerrainEffectMasterInput):
            raise ValueError("current master must be an explicit input or unavailable")


@dataclass(frozen=True, slots=True)
class ReplayTerrainEffectSystem:
    """Explicit current system80..88 vector, preserving order and duplicates.

    An empty tuple means a known empty vector. No default system is inferred.
    Consistent contents for repeated native identities are checked when the
    selection gate consumes this system. Storage and inputs must remain stable
    across this pure stage; native ownership/allocator reentrancy is excluded.
    """

    definitions: tuple[ReplayTerrainEffectDefinition, ...]

    def __post_init__(self) -> None:
        if type(self.definitions) is not tuple or any(
            not isinstance(definition, ReplayTerrainEffectDefinition)
            for definition in self.definitions
        ):
            raise ValueError("system definitions must be an explicit immutable tuple")


def replay_terrain_effect_accepts_terrain(
    definition: ReplayTerrainEffectDefinition, terrain_id: int
) -> bool:
    """1414ccc20: terrain denial precedes flagbit1 and allow membership."""
    if not isinstance(definition, ReplayTerrainEffectDefinition):
        raise ValueError("an explicit current terrain-effect definition is required")
    _integer(terrain_id, 0, 255, "terrain key")
    if terrain_id in definition.deny_terrain:
        return False
    return bool(definition.flags & 2) or terrain_id in definition.allow_terrain


def replay_terrain_effect_accepts_object(
    definition: ReplayTerrainEffectDefinition, master: ReplayTerrainEffectMasterInput
) -> bool:
    """1414cc7e0: deny saved_id/group/family before flagbit0 or any allow.

    There are no owner, resource, position, elevation or status predicates in
    this filter. Native A/B sign-extension is already reflected in the inputs.
    """
    if not isinstance(definition, ReplayTerrainEffectDefinition):
        raise ValueError("an explicit current terrain-effect definition is required")
    if not isinstance(master, ReplayTerrainEffectMasterInput):
        raise ValueError("an explicit current terrain-effect master is required")
    if master.saved_id in definition.deny_saved_ids:
        return False
    if master.object_group in definition.deny_object_groups:
        return False
    if master.family in definition.deny_families:
        return False
    if definition.flags & 1:
        return True
    if master.saved_id in definition.allow_saved_ids:
        return True
    if master.object_group in definition.allow_object_groups:
        return True
    return master.family in definition.allow_families


def select_replay_terrain_effects(
    context: ReplayTerrainEffectObjectContext, system: ReplayTerrainEffectSystem | None
) -> tuple[ReplayTerrainEffectDefinition, ...]:
    """Return original definitions accepted by the current selection stage.

    system=None explicitly means the current lookup is known null; unavailable
    system state must not be supplied as None. Both context and system arguments
    are required. Object188!=2 or known-null system yields an empty desired
    tuple. Otherwise capture one terrain key (255 for known-null tile), then
    process the supplied vector in order, terrain first and object second.

    Duplicate occurrences survive. Conflicting contents at one identity are
    refused before filtering a consumed system. This admission policy assumes
    stable current bindings rather than reproducing native partial faults,
    ownership-pair increments, capacity growth or effects of reentrant code.
    An empty desired tuple does not reconcile/clear existing active effects.
    """
    if not isinstance(context, ReplayTerrainEffectObjectContext):
        raise ValueError("an explicit current terrain-effect object context is required")
    if system is not None and not isinstance(system, ReplayTerrainEffectSystem):
        raise ValueError("an explicit current system or known-null lookup is required")
    if context.object_188 != 2 or system is None:
        return ()
    definitions: dict[int, ReplayTerrainEffectDefinition] = {}
    for definition in system.definitions:
        if definition.identity in definitions and definitions[definition.identity] != definition:
            raise ValueError("one current definition identity has conflicting filter contents")
        definitions[definition.identity] = definition
    terrain_id = 255 if context.terrain_id is None else context.terrain_id
    desired = []
    for definition in system.definitions:
        if not replay_terrain_effect_accepts_terrain(definition, terrain_id):
            continue
        if context.master is None:
            raise UnresolvedReplayTerrainEffectContext(
                "current master unavailable for object filter"
            )
        if replay_terrain_effect_accepts_object(definition, context.master):
            desired.append(definition)
    return tuple(desired)
