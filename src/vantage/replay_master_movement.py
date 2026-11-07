"""Restore the save68.9 moving-master scalar component and turn caches.

The selected baseline supplies its moving sprite before saved references
replace it. Cached turn fields are reset, then computed from saved1f8 and
that baseline sprite. Baseline20c..21c values are never inherited here.
The caller supplies the same baseline and sprite tables as native restoration.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from .replay_game_data import GameDataGraphic, GameDataMaster
from .replay_masters import SavedMaster
from .replay_movement_geometry import _bits, _float, _op, _word


class ReplayMasterMovementError(ValueError):
    """The supplied saved component or baseline context is incomplete."""


@dataclass(frozen=True, slots=True)
class ReplayMasterMovement:
    """Restored scalar words, with graphic references separate from pointers.

    ``fields`` includes the seven saved moving scalars and five computed turn
    words. ``sprite_ids`` represents the final native pointer resolution as
    IDs orNone. ``baseline_sprite_id`` records the sprite present at the early
    rotation calculation; replacing it afterward does not recalculate caches.
    Original wire values remain in the caller's SavedMaster unchanged.
    """

    baseline_index: int
    fields: dict[int, int]
    sprite_ids: tuple[int | None, int | None]
    baseline_sprite_id: int | None


def restore_replay_moving_turn_fields(
    rotation_bits: int, baseline_sprite_facets: int | None
) -> dict[int, int]:
    """Original Moving30 read/reset/virtual80 stage, as raw member-offset words.

    The signed i16 facet count is read from baseline sprite+a. None means
    null baseline moving-sprite pointer. Native uses f32(2*pi),0x40c90fdb,
    divided by f32(facetCount*savedRotation), or+FLT_MAX for an ordered zero
    product. NaN/Inf/subnormal operation order follows the original SSE code.
    """
    _word(rotation_bits)
    if baseline_sprite_facets is not None and (
        not isinstance(baseline_sprite_facets, int)
        or not -0x8000 <= baseline_sprite_facets <= 0x7FFF
    ):
        raise ReplayMasterMovementError("baseline sprite facets must be a signed i16 or None")
    fields = {0x20C: 0, 0x210: 0x7F7FFFFF, 0x214: 0x7F7FFFFF, 0x218: 0, 0x21C: 0x7F7FFFFF}
    if _float(rotation_bits) != 0.0 and baseline_sprite_facets is not None:
        product = _op(_bits(float(baseline_sprite_facets)), rotation_bits, "*")
        period = 0x7F7FFFFF if _float(product) == 0.0 else _op(0x40C90FDB, product, "/")
        fields[0x214], fields[0x218], fields[0x21C] = period, product, period
    return fields


def _field(fields: Mapping[int, int], offset: int, low: int, high: int) -> int:
    if offset not in fields:
        raise ReplayMasterMovementError(f"missing moving master member{offset:#x}")
    value = fields[offset]
    if not isinstance(value, int) or not low <= value <= high:
        raise ReplayMasterMovementError(f"invalid moving master member{offset:#x}")
    return value


def restore_replay_master_movement(
    saved: SavedMaster,
    selected_baseline: Mapping[int, GameDataMaster | None],
    graphics: Mapping[int, GameDataGraphic | None],
) -> ReplayMasterMovement:
    """Restore this component of a strictly decoded save68.9 master.

    ``selected_baseline`` must contain its native-remapped selector; an
    explicitNone denotes a null slot. A missing entry is incomplete input.
    ``graphics`` must describe the native sprite table used during restoration;
    missing/null graphic entries resolve to null pointers. This function does
    not select civilizations, load tables or apply later native effects.
    Baseline sprite IDs accept signed i16 values or the DAT parser's raw u16
    words. Original DAT1411aa0c0 sign-extends the word before its negative/null
    test; decoding here preserves the caller's original baseline unchanged.
    """
    if saved.type_group not in {30, 40, 50, 60, 70, 80}:
        raise ReplayMasterMovementError("saved master has no supported moving component")
    if not isinstance(saved.base.baseline_id, int) or not 0 <= saved.base.baseline_id <= 0x7FFF:
        raise ReplayMasterMovementError("baseline selector is outside the supported native table")
    index = {768: 420, 770: 691}.get(saved.base.baseline_id, saved.base.baseline_id)
    if index not in selected_baseline:
        raise ReplayMasterMovementError(f"missing baseline slot at master index{index}")
    fields = {
        offset: _field(saved.fields, offset, 0, 0xFFFFFFFF) for offset in (0x1F8, 0x204, 0x220)
    }
    fields.update(
        {offset: _field(saved.fields, offset, 0, 255) for offset in (0x1FC, 0x200, 0x208)}
    )
    fields[0x1FE] = _field(saved.fields, 0x1FE, -0x8000, 0x7FFF)
    baseline = selected_baseline[index]
    baseline_id = None
    if baseline is not None and baseline.type_group >= 30:
        baseline_id = _field(baseline.fields, 0x1E8, -0x8000, 0xFFFF)
        if baseline_id >= 0x8000:
            baseline_id -= 0x10000
    baseline_sprite = (
        graphics.get(baseline_id) if baseline_id is not None and baseline_id >= 0 else None
    )
    if baseline_sprite is None:
        baseline_id = None
    facets = None
    if _float(fields[0x1F8]) != 0.0 and baseline_sprite is not None:
        word = _field(baseline_sprite.fields, 0xA, 0, 0xFFFF)
        facets = word if word < 0x8000 else word - 0x10000
    fields.update(restore_replay_moving_turn_fields(fields[0x1F8], facets))
    raw_ids = tuple(_field(saved.fields, offset, -0x8000, 0x7FFF) for offset in (0x1E8, 0x1F0))
    first, second = (
        graphic_id if graphic_id >= 0 and graphics.get(graphic_id) is not None else None
        for graphic_id in raw_ids
    )
    return ReplayMasterMovement(index, fields, (first, second), baseline_id)
