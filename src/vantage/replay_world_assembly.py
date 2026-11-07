"""Logical initial-world bindings with explicit, still-pending native fixups.

The caller supplies the selected baseline tables and graphics context. Saved
records and native effective list order are retained; this does not construct
runtime spatial indexes, execute lifecycle callbacks or advance a simulation.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal

from vantage.replay_game_data import GameDataGraphic, GameDataMaster
from vantage.replay_initial_player import SavedInitialPlayer
from vantage.replay_master_common import (
    ReplayMasterComponents,
    restore_replay_master_components,
)
from vantage.replay_object_order import (
    RuntimePlayerObjectLists,
    restore_runtime_object_lists,
    runtime_object_list_name,
    signed_object_id,
)
from vantage.replay_objects import SavedObject
from vantage.replay_saved_world import SavedReplayWorld


class ReplayWorldAssemblyError(ValueError):
    """A logical binding cannot be made, with its original index/ID context."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        player_index: int | None = None,
        object_id: int | None = None,
        master_index: int | None = None,
    ) -> None:
        self.code = code
        self.player_index = player_index
        self.object_id = object_id
        self.master_index = master_index
        context = ", ".join(
            f"{name}={value}"
            for name, value in (
                ("player", player_index),
                ("raw_object_id", object_id),
                ("master", master_index),
            )
            if value is not None
        )
        super().__init__(f"{code}: {message}" + (f" ({context})" if context else ""))


@dataclass(frozen=True, slots=True)
class ReplayInitialWorldPending:
    """Unexecuted initialization, independent of whether saved lists are empty."""

    reference_callbacks: Literal[True] = True
    lifecycle_updates: Literal[True] = True
    spatial_registries: Literal[True] = True


@dataclass(frozen=True, slots=True)
class ReplayInitialObjectBinding:
    saved: SavedObject
    player_index: int
    master: ReplayMasterComponents
    # Signed interpretations of all five Building slots; None means no Building
    # extension. Exact u32 words remain at saved.building.linked_references.
    building_reference_ids: tuple[int, ...] | None
    building_links: tuple[SavedObject | None, ...] | None
    # Common+148 is an encoded object reference, never an Action serial. Even
    # when its target exists, this view does not resolve or invoke its callback.
    unresolved_common_reference_id: int | None


@dataclass(frozen=True, slots=True)
class ReplayInitialPlayerAssembly:
    saved: SavedInitialPlayer
    selected_baseline: Mapping[int, GameDataMaster | None]
    masters: tuple[ReplayMasterComponents | None, ...]
    objects: RuntimePlayerObjectLists
    bindings: tuple[ReplayInitialObjectBinding, ...]


@dataclass(frozen=True, slots=True)
class ReplayInitialWorldAssembly:
    """A provenance-preserving logical view, before runtime initialization.

    Container views do not make the original records' nested dictionaries
    deeply immutable. Raw IDs include zero; no spectator alias is substituted.
    The index is a logical join, not the native World's allocated lookup table.
    """

    saved: SavedReplayWorld
    players: tuple[ReplayInitialPlayerAssembly, ...]
    graphics: Mapping[int, GameDataGraphic | None]
    objects_by_raw_id: Mapping[int, ReplayInitialObjectBinding]
    pending: ReplayInitialWorldPending


def _master_slots(
    player: SavedInitialPlayer,
    owner: int,
    selected: Mapping[int, GameDataMaster | None],
    graphics: Mapping[int, GameDataGraphic | None],
) -> tuple[ReplayMasterComponents | None, ...]:
    table = player.masters
    if (
        type(table.count) is not int
        or not 0 <= table.count <= 0x7FFFFFFF
        or len(table.presence) != table.count
        or any(type(v) is not int or not -(1 << 31) <= v < 1 << 31 for v in table.presence)
    ):
        raise ReplayWorldAssemblyError("master_table", "invalid count/presence", player_index=owner)
    if any(type(key) is not int or not 0 <= key < table.count for key in table.masters):
        raise ReplayWorldAssemblyError("master_table", "invalid slot index", player_index=owner)
    if set(table.masters) != {i for i, present in enumerate(table.presence) if present}:
        raise ReplayWorldAssemblyError(
            "master_table", "presence and saved definitions disagree", player_index=owner
        )
    slots: list[ReplayMasterComponents | None] = [None] * table.count
    for index, master in table.masters.items():
        if master.master_id is not None and (
            type(master.master_id) is not int or master.master_id != index
        ):
            raise ReplayWorldAssemblyError(
                "master_index",
                "saved definition disagrees with slot",
                player_index=owner,
                master_index=index,
            )
        try:
            slots[index] = restore_replay_master_components(master, selected, graphics=graphics)
        except ValueError as error:
            raise ReplayWorldAssemblyError(
                "master_restore", str(error), player_index=owner, master_index=index
            ) from error
    return tuple(slots)


def _validate_object(
    obj: SavedObject, owner: int, masters: tuple[ReplayMasterComponents | None, ...]
) -> ReplayMasterComponents:
    context = dict(player_index=owner, object_id=obj.object_id, master_index=obj.master_id)
    try:
        signed_object_id(obj.object_id)
        runtime_object_list_name(obj)
    except ValueError as error:
        raise ReplayWorldAssemblyError("object", str(error), **context) from error
    if type(obj.owner) is not int or obj.owner != owner:
        raise ReplayWorldAssemblyError(
            "owner", "object disagrees with containing player", **context
        )
    index = obj.master_id
    if type(index) is not int or not 0 <= index < len(masters):
        raise ReplayWorldAssemblyError("master_index", "object index is out of range", **context)
    master = masters[index]
    if master is None:
        raise ReplayWorldAssemblyError("current_master", "object selects a null slot", **context)
    if type(obj.type_group) is not int or obj.type_group != master.saved.type_group:
        raise ReplayWorldAssemblyError("family", "object and current master disagree", **context)
    if type(obj.reference_id) is not int or not -(1 << 31) <= obj.reference_id < 1 << 31:
        raise ReplayWorldAssemblyError("common_reference", "reference148 is not an i32", **context)
    if obj.type_group == 80 and obj.building is None:
        raise ReplayWorldAssemblyError(
            "building_reference", "missing Building extension", **context
        )
    if obj.building is not None:
        if obj.type_group != 80 or len(obj.building.linked_references) != 5:
            raise ReplayWorldAssemblyError(
                "building_reference", "expected five Building slots", **context
            )
        for raw in obj.building.linked_references:
            try:
                signed_object_id(raw)
            except ValueError as error:
                raise ReplayWorldAssemblyError(
                    "building_reference", str(error), **context
                ) from error
    return master


def assemble_replay_initial_world(
    saved: SavedReplayWorld,
    selected_baselines: Sequence[Mapping[int, GameDataMaster | None]],
    *,
    graphics: Mapping[int, GameDataGraphic | None],
) -> ReplayInitialWorldAssembly:
    """Bind parsed initial state without modifying it or performing external IO.

    Explicit baseline and graphics mappings retain their identities. Dense
    current null slots are never filled from baseline data. Duplicate IDs are
    suppressed only by the proven per-list restorer; any ambiguity remaining
    across effective lists/players is rejected in this bounded logical profile.
    Building links are value joins, not execution of native reference callbacks.
    Nonnull common148 references remain explicitly unresolved.
    """
    world = saved.prefix.world
    if not isinstance(selected_baselines, Sequence):
        raise ReplayWorldAssemblyError("players", "ordered baseline mappings are required")
    if (
        type(world.prefix.num_players) is not int
        or world.prefix.num_players < 1
        or world.prefix.num_players != len(world.players)
        or len(selected_baselines) != len(world.players)
    ):
        raise ReplayWorldAssemblyError("players", "player vector and baseline count disagree")
    if not isinstance(graphics, Mapping):
        raise ReplayWorldAssemblyError("graphics", "explicit graphics mapping is required")
    prepared = []
    raw_objects: dict[int, SavedObject] = {}
    for owner, (player, selected) in enumerate(zip(world.players, selected_baselines, strict=True)):
        if player.header.player_id is not None and (
            type(player.header.player_id) is not int or player.header.player_id != owner
        ):
            raise ReplayWorldAssemblyError(
                "player_index", "saved header disagrees with vector", player_index=owner
            )
        if not isinstance(selected, Mapping):
            raise ReplayWorldAssemblyError(
                "baseline", "selected table must be a mapping", player_index=owner
            )
        masters = _master_slots(player, owner, selected, graphics)
        for wire in (
            player.object_lists.ordinary,
            player.object_lists.sleeping,
            player.object_lists.dopple,
        ):
            for obj in wire.objects:
                _validate_object(obj, owner, masters)
        runtime = restore_runtime_object_lists(player.object_lists)
        for obj in runtime.update_order:
            if obj.object_id in raw_objects:
                raise ReplayWorldAssemblyError(
                    "duplicate_id",
                    "raw ID is ambiguous across effective lists/players",
                    player_index=owner,
                    object_id=obj.object_id,
                    master_index=obj.master_id,
                )
            raw_objects[obj.object_id] = obj
        prepared.append((player, selected, masters, runtime))
    players = []
    by_id = {}
    for owner, (player, selected, masters, runtime) in enumerate(prepared):
        bindings = []
        for obj in runtime.update_order:
            ids = links = None
            if obj.building is not None:
                ids = tuple(signed_object_id(raw) for raw in obj.building.linked_references)
                targets = []
                for slot, reference in enumerate(ids):
                    target = None if reference == -1 else raw_objects.get(reference & 0xFFFFFFFF)
                    if reference != -1 and target is None:
                        raise ReplayWorldAssemblyError(
                            "building_reference",
                            f"slot{slot} target {reference} is absent",
                            player_index=owner,
                            object_id=obj.object_id,
                            master_index=obj.master_id,
                        )
                    targets.append(target)
                links = tuple(targets)
            master = masters[obj.master_id]
            assert master is not None  # All wire objects were checked before list restoration.
            binding = ReplayInitialObjectBinding(
                obj,
                owner,
                master,
                ids,
                links,
                None if obj.reference_id == -1 else obj.reference_id,
            )
            bindings.append(binding)
            by_id[obj.object_id] = binding
        players.append(
            ReplayInitialPlayerAssembly(player, selected, masters, runtime, tuple(bindings))
        )
    return ReplayInitialWorldAssembly(
        saved, tuple(players), graphics, MappingProxyType(by_id), ReplayInitialWorldPending()
    )
