"""Common saved-master scalars and explicit task/movement composition.

Original1411f2ec0 copies selected baseline values before applying saved68.9
overrides. Eleven direct scalar copies survive; descriptor IDfc is inherited
through a separate descriptor helper. Native pointers, encoded storage and
string/asset lifetime are not represented by these logical scalar values.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import cast

from vantage.replay_game_data import GameDataGraphic, GameDataMaster
from vantage.replay_master_combat import (
    ReplayMasterCombat,
    ReplayMasterUnit,
    restore_replay_master_combat,
    restore_replay_master_unit,
)
from vantage.replay_master_movement import (
    ReplayMasterMovement,
    restore_replay_master_movement,
)
from vantage.replay_master_tasks import ReplayMasterTasks, restore_replay_master_tasks
from vantage.replay_masters import SavedMaster, SavedMasterBase

_TYPES = {10, 15, 20, 25, 30, 40, 50, 60, 70, 80}
_INHERITED_WIDTHS = {
    0x60: 1,
    0x88: 1,
    0xC0: 4,
    0xC4: 4,
    0xD0: 1,
    0xD1: 1,
    0xD2: 1,
    0x118: 4,
    0x120: 1,
    0x124: 1,
    0x125: 1,
}
_SAVED_I16 = (
    0x18,
    0x20,
    0x28,
    0x30,
    0x38,
    0x68,
    0xBC,
    0xAA,
    0xAC,
    0xAE,
    0xA6,
    0x84,
    0x8A,
    0x86,
    0x92,
    0x94,
    0x96,
    0x98,
    0x8E,
)
_SAVED_I32 = (0xC, 0x10)
_SAVED_U32 = (0x70, 0x78, 0x7C, 0xB0, 0xB4, 0xB8, 0xF4, 0x80, 0x128, 0x12C, 0x130, 0x9C, 0xA0)
_SAVED_U8 = (
    0x90,
    0x8C,
    0x74,
    0xC8,
    0xC9,
    0xCA,
    0x91,
    0xCB,
    0xA5,
    0xF0,
    0xF1,
    0xF2,
    0x89,
    0xCF,
    0xCC,
    0xCD,
    0xCE,
    0x1D1,
    0xA8,
    0x121,
    0xA4,
    0x122,
    0x123,
)


class ReplayMasterCommonError(ValueError):
    """The saved common component or caller-selected baseline is incomplete."""


@dataclass(frozen=True, slots=True)
class ReplayMasterCommon:
    """Restored logical common scalars with untouched wire/source provenance.

    ``fields`` holds57 saved scalar members, eleven inherited direct scalars,
    and the final14<-c alias. Selectors20/28 use the native768/770 remaps.
    Four-byte float values remain raw u32 bits. Saved graphic/sound references
    and descriptor138 are retained in ``saved`` rather than relabeled pointers.
    ``descriptor_fc_bits`` is a separate inherited descriptor ID; its static
    copy contract is outside the executed direct-scalar span oracle.
    """

    baseline_index: int
    fields: dict[int, int]
    descriptor_fc_bits: int
    saved: SavedMasterBase
    baseline: GameDataMaster

    @property
    def inherited_fields(self) -> dict[int, int]:
        return {offset: self.fields[offset] for offset in _INHERITED_WIDTHS}


@dataclass(frozen=True, slots=True)
class ReplayMasterComponents:
    """Numeric/task/movement components using one explicitly selected table.

    This carries the original complete saved definition as provenance. Other
    derived restoration, references and later world effects remain separate.
    None denotes a component absent from this factory family. No civilization
    selection or Gaia cache reset occurs in this composition.
    """

    saved: SavedMaster
    common: ReplayMasterCommon
    movement: ReplayMasterMovement | None
    tasks: ReplayMasterTasks | None
    combat: ReplayMasterCombat | None = None
    unit: ReplayMasterUnit | None = None

    @property
    def baseline_index(self) -> int:
        return self.common.baseline_index


def _member(fields: Mapping[int, int], offset: int, low: int, high: int, origin: str) -> int:
    if offset not in fields:
        raise ReplayMasterCommonError(f"missing {origin} common member{offset:#x}")
    value = fields[offset]
    if type(value) is not int or not low <= value <= high:
        raise ReplayMasterCommonError(f"invalid {origin} common member{offset:#x}")
    return value


def _remap(value: int) -> int:
    return {768: 420, 770: 691}.get(value, value)


def restore_replay_master_common(
    saved: SavedMaster, selected_baseline: Mapping[int, GameDataMaster | None]
) -> ReplayMasterCommon:
    """Restore this scalar component of a strictly parsed save68.9 master.

    The same caller-selected table must also supply any task/movement restore.
    Missing/null source slots fail, matching the successful native reader's
    nonnull-baseline prerequisite; native stream failure timing is not modeled.
    Source family differences do not suppress its common scalar copies.
    No arbitrary DAT fields or unsaved pointer values are merged into the save.
    """
    if (
        type(saved.type_group) is not int
        or type(saved.base.type_group) is not int
        or saved.type_group not in _TYPES
        or saved.base.type_group != saved.type_group
    ):
        raise ReplayMasterCommonError("unsupported or inconsistent saved master family")
    selector = saved.base.baseline_id
    if type(selector) is not int or not 0 <= selector <= 32767:
        raise ReplayMasterCommonError("baseline selector must be a nonnegative i16")
    index = _remap(selector)
    baseline = selected_baseline.get(index)
    if baseline is None:
        raise ReplayMasterCommonError(f"missing or null common baseline at master index{index}")
    fields = {}
    for offsets, low, high in (
        (_SAVED_I16, -32768, 32767),
        (_SAVED_I32, -(1 << 31), (1 << 31) - 1),
        (_SAVED_U32, 0, 0xFFFFFFFF),
        (_SAVED_U8, 0, 255),
    ):
        for offset in offsets:
            fields[offset] = _member(saved.base.fields, offset, low, high, "saved")
    if fields[0x20] != selector:
        raise ReplayMasterCommonError("saved common selector disagrees with baseline_id")
    for offset, width in _INHERITED_WIDTHS.items():
        fields[offset] = _member(
            baseline.common.fields, offset, 0, (1 << (width * 8)) - 1, "baseline"
        )
    descriptor = _member(baseline.common.fields, 0xFC, 0, 0xFFFFFFFF, "baseline descriptor")
    fields[0x20], fields[0x28] = index, _remap(fields[0x28])
    fields[0x14] = fields[0xC]
    return ReplayMasterCommon(index, fields, descriptor, saved.base, baseline)


def restore_replay_master_components(
    saved: SavedMaster,
    selected_baseline: Mapping[int, GameDataMaster | None],
    *,
    graphics: Mapping[int, GameDataGraphic | None] | None = None,
) -> ReplayMasterComponents:
    """Compose supported components with the identical caller-selected table.

    Moving families30..80 require an explicit graphics table, including an
    explicit empty table when all reached native graphic entries are null.
    Action families40..80 add task/default-index restoration,50..80 add the
    numeric Combat facet, and70/80 add Unit costs/training plus its index fixup.
    Graphics IDs in the latter two components remain deferred references.
    Component source/facet/default-task validation remains in those APIs.
    This returns a partial restored-master value, not a native object image.
    """
    common = restore_replay_master_common(saved, selected_baseline)
    movement = None
    tasks = None
    combat = None
    unit = None
    if saved.type_group >= 30:
        if graphics is None:
            raise ReplayMasterCommonError("moving component requires an explicit graphics table")
        movement = restore_replay_master_movement(saved, selected_baseline, graphics)
    if saved.type_group >= 40:
        # The existing task reader reaches only this source slot, already
        # proved nonnull above. Preserve the identical mapping at runtime;
        # other unreachable slots may remain explicitNone for other APIs.
        tasks = restore_replay_master_tasks(
            saved, cast(Mapping[int, GameDataMaster], selected_baseline)
        )
    if saved.type_group >= 50:
        combat = restore_replay_master_combat(saved, selected_baseline)
    if saved.type_group >= 70:
        unit = restore_replay_master_unit(saved, selected_baseline)
    for component in (movement, tasks, combat, unit):
        if component is not None and component.baseline_index != common.baseline_index:
            raise ReplayMasterCommonError("restored component baseline indices disagree")
    return ReplayMasterComponents(saved, common, movement, tasks, combat, unit)
