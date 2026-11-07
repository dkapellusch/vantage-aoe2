"""Conditional fresh modern registry from typed saved-world bindings.

This composes initial add then enabled refresh before regular updates. It
computes both native quantizers; it does not execute position/reference/legacy
callbacks or establish an observed registration history. Source pending flags
remain unchanged. The stationary action-end refresh API is a separate profile.
"""

from __future__ import annotations

import math
import struct
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal

from .replay_movement_geometry import _float, _op
from .replay_object_order import (
    RuntimePlayerObjectLists,
    restore_runtime_object_lists,
    signed_object_id,
)
from .replay_objects import SavedActionState, SavedMovement
from .replay_occupancy import OccupancyRegistry
from .replay_path_geometry import Q22Rectangle
from .replay_world_assembly import (
    ReplayInitialObjectBinding,
    ReplayInitialPlayerAssembly,
    ReplayInitialWorldAssembly,
    ReplayWorldAssemblyError,
)

_NONE, _HALF, _SCALE = 0xFFFFFFFF, 0x3F000000, 0x4A800000


class ReplayInitialOccupancyError(ReplayWorldAssemblyError):
    """An initialization premise, typed binding or geometry is unsupported."""


@dataclass(frozen=True, slots=True)
class ReplayInitialModernOccupancy:
    registry: OccupancyRegistry
    indices_by_raw_id: Mapping[int, int]
    source: ReplayInitialWorldAssembly
    conditional_saved_input_recipe: Literal[True] = True


def _integer(value: int, maximum: int, label: str) -> None:
    if type(value) is not int or not 0 <= value <= maximum:
        raise ValueError(f"{label} has an invalid integer type or width")


def _s32(value: int) -> int:
    return ((value + (1 << 31)) & _NONE) - (1 << 31)


def _registration_rectangles(
    position: tuple[int, int], radii: tuple[int, int], stride: int
) -> tuple[Q22Rectangle, Q22Rectangle]:
    """Original141122240 then141120e80 numerical inputs, in bounded finite XY.

    Initial modern geometry uses normal master78/7c even for kind11. The first
    builder profile admits kinds2/5 only, whose later refresh uses those same
    radius fields. All binary32 arithmetic is rounded in original SSE order.
    """
    if type(stride) is not int or not 1 <= stride <= 200:
        raise ValueError("stride must be an integer1..200")
    for pair in (position, radii):
        if type(pair) is not tuple or len(pair) != 2:
            raise ValueError("two raw binary32 coordinate/radius words are required")
        for word in pair:
            _integer(word, _NONE, "geometry word")
    if any(
        not math.isfinite(_float(word)) or not -1 <= _float(word) <= stride + 1 for word in position
    ):
        raise ValueError("finite centers must lie in[-1,stride+1]")
    if any(
        not math.isfinite(_float(word)) or not 0 <= _float(word) <= stride + 1 for word in radii
    ):
        raise ValueError("finite radii must lie in[0,stride+1]")
    x, y = position
    rx, ry = radii

    def initial(center: int, radius: int, operation: str) -> int:
        rounded = _op(_op(center, radius, operation), _HALF, operation)
        return _s32(int(_float(_op(rounded, _SCALE, "*"))))

    first = (initial(x, rx, "-"), initial(y, ry, "-"), initial(x, rx, "+"), initial(y, ry, "+"))
    ix, iy, irx, iry = (int(_float(_op(word, _SCALE, "*"))) for word in (x, y, rx, ry))
    second = (
        _s32(ix - irx - (1 << 21)),
        _s32(iy - iry - (1 << 21)),
        _s32(ix + irx + (1 << 21)),
        _s32(iy + iry + (1 << 21)),
    )
    # In this finite domain all CVTTSS2SI64 inputs are safely representable.
    # Retain low32 wrapping explicitly, then admit the existing registry profile.
    validator = OccupancyRegistry(stride)
    validator._rectangle(first)
    validator._rectangle(second)
    return first, second


def _position(binding: ReplayInitialObjectBinding) -> tuple[int, int]:
    position = binding.saved.position
    if type(position) is not tuple or len(position) != 3:
        raise ValueError("position must contain three exact parsed binary32 values")
    words = []
    for value in position:
        if type(value) is not float or not math.isfinite(value):
            raise ValueError("position must contain finite binary32 floats")
        try:
            word = struct.unpack("<I", struct.pack("<f", value))[0]
        except OverflowError as error:
            raise ValueError("position exceeds binary32") from error
        if _float(word) != value:
            raise ValueError("position is not an exact parsed binary32 value")
        words.append(word)
    return words[0], words[1]


def _plan(
    binding: ReplayInitialObjectBinding, stride: int
) -> tuple[Q22Rectangle, Q22Rectangle] | None:
    obj = binding.saved
    if type(obj.type_group) is not int or obj.type_group not in {
        10,
        20,
        25,
        30,
        40,
        50,
        60,
        70,
        80,
    }:
        raise ValueError("unsupported saved object family")
    if obj.reference_id != -1 or type(obj.reference_id) is not int:
        raise ValueError("nonnull common148 reference callbacks are unsupported")
    if binding.unresolved_common_reference_id is not None:
        raise ValueError("the logical common148 binding must also be absent")
    if obj.type_group >= 30:
        movement = obj.movement
        if (
            type(movement) is not SavedMovement
            or type(movement.endpoint_flag) is not int
            or movement.endpoint_flag != 0
            or movement.endpoints is not None
            or type(movement.paths_wire_order) is not tuple
            or movement.paths_wire_order
            or type(movement.secondary_path_flag) is not int
            or movement.secondary_path_flag != 0
            or movement.secondary_path is not None
            or type(movement.waypoints) is not tuple
            or movement.waypoints
        ):
            raise ValueError("nonempty saved motion/controller/path state is unsupported")
    elif obj.movement is not None:
        raise ValueError("a nonmoving object cannot carry a moving facet")
    if obj.type_group >= 40 and (
        type(obj.action) is not SavedActionState
        or type(obj.action.raw) is not bytes
        or len(obj.action.raw) < 2
        or obj.action.raw[-2:] != b"\0\0"
    ):
        raise ValueError("a parser-proven empty saved Action behavior list is required")
    if obj.type_group < 40 and obj.action is not None:
        raise ValueError("a nonaction object cannot carry an Action facet")
    fields = binding.master.common.fields
    if not isinstance(fields, Mapping) or not isinstance(obj.fields, Mapping):
        raise ValueError("object and current master fields must be mappings")
    values = {}
    for offset in (0xF1, 0xF2, 0x78, 0x7C, 0x80, 0x128, 0x12C):
        if offset not in fields:
            raise ValueError(f"missing restored current master member{offset:#x}")
        value = fields[offset]
        _integer(value, 255 if offset in (0xF1, 0xF2) else _NONE, "master member")
        values[offset] = value
    if type(obj.flags) is not tuple or len(obj.flags) != 4:
        raise ValueError("four saved object flags are required")
    for flag in obj.flags:
        _integer(flag, 255, "object flag")
    if 0x1C6 not in obj.fields:
        raise ValueError("missing object1c6 admission member")
    _integer(obj.fields[0x1C6], 255, "object1c6")
    position = _position(binding)
    admitted = (
        obj.flags[0] < 7
        and obj.fields[0x1C6] != 1
        and _float(values[0x80]) > 0
        and values[0xF1] not in (0, 12)
        and values[0xF2] != 0
    )
    if not admitted:
        return None
    if values[0xF1] not in (2, 5):
        raise ValueError("admitted kinds other than2/5 require a different restore recipe")
    if not math.isfinite(_float(values[0x80])):
        raise ValueError("infinite admitted radiusZ is outside the finite profile")
    return _registration_rectangles(position, (values[0x78], values[0x7C]), stride)


def build_replay_initial_modern_occupancy(
    assembly: ReplayInitialWorldAssembly, *, modern_gate: bool, before_regular_updates: bool
) -> ReplayInitialModernOccupancy:
    """Build a fresh conditional index using typed current-master/object bindings.

    Both explicit premises must be true. Square maps1..200, null common148,
    empty saved motion/path/action state and admitted kinds2/5 are supported.
    Native callbacks that could change saved XY are not executed; this is the
    saved-input construction component, not complete native restore/history.
    All bindings and geometry are checked before a registry is published. Every
    raw ID receives an immutable binding, including0 and rejected UINT32_MAX.
    The source assembly, its pending flags and all old registries remain intact.
    """
    if type(assembly) is not ReplayInitialWorldAssembly:
        raise ReplayInitialOccupancyError("assembly", "a typed initial assembly is required")
    if type(modern_gate) is not bool or not modern_gate:
        raise ReplayInitialOccupancyError("modern_gate", "actual modern gate must be true")
    if type(before_regular_updates) is not bool or not before_regular_updates:
        raise ReplayInitialOccupancyError("phase", "before-regular-updates premise must be true")
    world = assembly.saved.prefix.world
    width, height = world.map.width, world.map.height
    if (
        type(width) is not int
        or type(height) is not int
        or width != height
        or not 1 <= width <= 200
    ):
        raise ReplayInitialOccupancyError("map", "a square saved map with stride1..200 is required")
    if (
        type(assembly.players) is not tuple
        or len(assembly.players) != len(world.players)
        or type(world.prefix.num_players) is not int
        or world.prefix.num_players < 1
        or len(assembly.players) != world.prefix.num_players
    ):
        raise ReplayInitialOccupancyError("players", "assembly player vector is inconsistent")
    if not isinstance(assembly.objects_by_raw_id, Mapping):
        raise ReplayInitialOccupancyError("bindings", "raw-ID bindings must be a mapping")
    if any(type(key) is not int or not 0 <= key <= _NONE for key in assembly.objects_by_raw_id):
        raise ReplayInitialOccupancyError("bindings", "raw-ID mapping keys must be u32 words")
    plans: list[tuple[int, tuple[Q22Rectangle, Q22Rectangle] | None]] = []
    seen: set[int] = set()
    admitted = 0
    for owner, player in enumerate(assembly.players):
        if (
            type(player) is not ReplayInitialPlayerAssembly
            or type(player.objects) is not RuntimePlayerObjectLists
            or type(player.masters) is not tuple
            or not isinstance(player.selected_baseline, Mapping)
            or any(
                type(group) is not tuple
                for group in (
                    player.objects.ordinary,
                    player.objects.sleeping,
                    player.objects.dopple,
                )
            )
        ):
            raise ReplayInitialOccupancyError(
                "players", "typed immutable player views required", player_index=owner
            )
        if player.saved is not world.players[owner]:
            raise ReplayInitialOccupancyError(
                "players", "saved player identity differs", player_index=owner
            )
        try:
            expected = restore_runtime_object_lists(player.saved.object_lists)
        except ValueError as error:
            raise ReplayInitialOccupancyError("order", str(error), player_index=owner) from error
        if any(
            len(a) != len(b) or any(x is not y for x, y in zip(a, b, strict=True))
            for a, b in zip(
                (expected.ordinary, expected.sleeping, expected.dopple),
                (player.objects.ordinary, player.objects.sleeping, player.objects.dopple),
                strict=True,
            )
        ):
            raise ReplayInitialOccupancyError(
                "order", "effective object order/identity differs", player_index=owner
            )
        objects = player.objects.update_order
        if type(player.bindings) is not tuple or len(player.bindings) != len(objects):
            raise ReplayInitialOccupancyError(
                "bindings", "ordered binding extent differs", player_index=owner
            )
        if len(player.masters) != player.saved.masters.count:
            raise ReplayInitialOccupancyError(
                "masters", "current master extent differs", player_index=owner
            )
        for obj, binding in zip(objects, player.bindings, strict=True):
            context = dict(player_index=owner, object_id=obj.object_id, master_index=obj.master_id)
            try:
                if type(binding) is not ReplayInitialObjectBinding:
                    raise ValueError("a typed object binding is required")
                signed_object_id(obj.object_id)
                _integer(obj.owner, len(assembly.players) - 1, "object owner")
                _integer(binding.player_index, len(assembly.players) - 1, "binding owner")
                _integer(obj.master_id, len(player.masters) - 1, "current master index")
                master = player.masters[obj.master_id]
                if (
                    binding.saved is not obj
                    or binding.player_index != owner
                    or obj.owner != owner
                    or assembly.objects_by_raw_id.get(obj.object_id) is not binding
                    or obj.object_id in seen
                    or master is None
                    or binding.master is not master
                    or master.saved is not player.saved.masters.masters.get(obj.master_id)
                    or master.common.saved is not master.saved.base
                    or master.saved.type_group != obj.type_group
                    or master.common.baseline
                    is not player.selected_baseline.get(master.common.baseline_index)
                ):
                    raise ValueError("object/current-master/baseline identity join differs")
                seen.add(obj.object_id)
                geometry = _plan(binding, width)
            except ValueError as error:
                raise ReplayInitialOccupancyError("object", str(error), **context) from error
            admitted += geometry is not None
            if admitted > 8192:
                raise ReplayInitialOccupancyError(
                    "slots", "more than8192 registered objects", **context
                )
            plans.append((obj.object_id, geometry))
    if set(assembly.objects_by_raw_id) != seen:
        raise ReplayInitialOccupancyError("bindings", "raw-ID index contains extra/missing keys")
    registry = OccupancyRegistry(width)
    indices = {}
    for raw_id, geometry in plans:
        if geometry is None:
            indices[raw_id] = _NONE
        else:
            initial, refresh = geometry
            index = registry.add(initial)
            indices[raw_id] = registry.change(index, refresh)
    return ReplayInitialModernOccupancy(registry, MappingProxyType(indices), assembly)
