"""Numeric Combat50/Unit70 restoration from an explicitly selected baseline.

Original14118f0c0 retains only scalar2fc from its Combat baseline;
141330030 retains scalar358 and normalizes the saved training index3e0.
Saved raw graphics IDs remain deferred references. No asset lifetime,
technology effect, missile/building extension or combat execution runs here.
"""

from __future__ import annotations

import struct
from collections.abc import Mapping
from dataclasses import dataclass

from vantage.replay_game_data import GameDataMaster
from vantage.replay_masters import SavedMaster

_TYPES = {10, 15, 20, 25, 30, 40, 50, 60, 70, 80}
_COMBAT_I16 = (0x2A0, 0x2B0, 0x2A2, 0x2DE, 0x2DC, 0x2C0, 0x2E2, 0x2F4, 0x2F6, 0x30C)
_COMBAT_U8 = (0x2D0, 0x2E0)
_COMBAT_U32 = (
    0x2D8,
    0x2C8,
    0x2C4,
    0x2CC,
    0x2F0,
    0x2F8,
    0x300,
    0x2D4,
    0x304,
    0x308,
    0x310,
    0x2E4,
    0x2E8,
    0x2EC,
)
_UNIT_I16 = (0x350, 0x3C0, 0x3C2, 0x3C4, 0x37A, 0x384, 0x3E0)
_UNIT_U8 = (0x364, 0x379, 0x3CC, 0x35C, 0x378)
_UNIT_U32 = (
    0x360,
    0x354,
    0x3B8,
    0x3BC,
    0x3C8,
    0x3D0,
    0x37C,
    0x380,
    0x3D4,
    0x3D8,
    0x3DC,
    0x374,
    0x368,
    0x36C,
    0x370,
)


class ReplayMasterCombatError(ValueError):
    """Combat50/Unit70 numeric state or its selected source is incomplete."""


@dataclass(frozen=True, slots=True)
class ReplayMasterCombat:
    """26 saved scalar members plus inherited2fc, with ordered signed pairs.

    The saved signed counts remain in ``fields`` even when nonpositive.
    Four-byte values remain raw u32 bits. ``saved_graphic_ids`` holds the
    original i16 references298/318; it does not describe resolved pointers.
    Original parsed save and selected DAT definitions retain their identities.
    """

    baseline_index: int
    fields: dict[int, int]
    weapons: tuple[tuple[int, int], ...]
    armor: tuple[tuple[int, int], ...]
    saved_graphic_ids: dict[int, int]
    saved: SavedMaster
    baseline: GameDataMaster


@dataclass(frozen=True, slots=True)
class ReplayMasterUnit:
    """27 saved numeric members plus inherited358, with normalized3e0.

    ``costs`` contains(type,amount,flag,padding) for each six-byte slot after
    current saved overrides. ``training`` keeps wire order(time,building,
    button,hotkey), rather than inventing runtime padding. Its first two
    words swap in the native12B entry. ``training_count`` preserves the raw
    signed count, while ``fields[0x3e0]`` indexes the actual restored tuple.
    Raw3e0 and initial cost bytes remain in the untouched ``saved`` record.
    Six raw graphic IDs are deferred; asset resolution/lifetime is separate.
    """

    baseline_index: int
    fields: dict[int, int]
    costs: tuple[tuple[int, int, int, int], ...]
    training_count: int
    training: tuple[tuple[int, int, int, int], ...]
    saved_graphic_ids: dict[int, int]
    saved: SavedMaster
    baseline: GameDataMaster

    @property
    def cost_bytes(self) -> tuple[bytes, ...]:
        """Restored six-byte member images, including original padding bytes."""
        return tuple(struct.pack("<hhBB", *slot) for slot in self.costs)

    @property
    def training_index(self) -> int:
        return self.fields[0x3E0]


def _integer(value: int, low: int, high: int, label: str) -> int:
    if type(value) is not int or not low <= value <= high:
        raise ReplayMasterCombatError(f"invalid {label}")
    return value


def _member(fields: Mapping[int, int], offset: int, low: int, high: int, origin: str) -> int:
    if offset not in fields:
        raise ReplayMasterCombatError(f"missing {origin} member{offset:#x}")
    return _integer(fields[offset], low, high, f"{origin} member{offset:#x}")


def _selected(
    saved: SavedMaster, table: Mapping[int, GameDataMaster | None], minimum: int
) -> tuple[int, GameDataMaster]:
    allowed = {50, 60, 70, 80} if minimum == 50 else {70, 80}
    if (
        type(saved.type_group) is not int
        or saved.type_group not in allowed
        or type(saved.base.type_group) is not int
        or saved.base.type_group != saved.type_group
    ):
        raise ReplayMasterCombatError("unsupported or inconsistent saved master family")
    selector = _integer(saved.base.baseline_id, 0, 32767, "nonnegative i16 baseline selector")
    if _member(saved.base.fields, 0x20, 0, 32767, "saved selector") != selector:
        raise ReplayMasterCombatError("saved selector disagrees with baseline_id")
    index = {768: 420, 770: 691}.get(selector, selector)
    baseline = table.get(index)
    if baseline is None:
        raise ReplayMasterCombatError(f"missing or null baseline at master index{index}")
    if type(baseline.type_group) is not int or baseline.type_group not in _TYPES:
        raise ReplayMasterCombatError("unsupported baseline master family")
    return index, baseline


def _scalars(
    saved: SavedMaster, i16: tuple[int, ...], u8: tuple[int, ...], u32: tuple[int, ...]
) -> dict[int, int]:
    fields = {}
    for offsets, low, high in ((i16, -32768, 32767), (u8, 0, 255), (u32, 0, 0xFFFFFFFF)):
        for offset in offsets:
            fields[offset] = _member(saved.fields, offset, low, high, "saved")
    return fields


def _rows(
    saved: SavedMaster, member: int, size: int, limits: tuple[tuple[int, int], ...]
) -> tuple[tuple[int, ...], ...]:
    if member not in saved.vectors:
        raise ReplayMasterCombatError(f"missing saved vector{member:#x}")
    rows = saved.vectors[member]
    if not isinstance(rows, tuple):
        raise ReplayMasterCombatError(f"invalid saved vector{member:#x}")
    for row in rows:
        if not isinstance(row, tuple) or len(row) != size:
            raise ReplayMasterCombatError(f"invalid saved vector{member:#x} entry")
        for value, (low, high) in zip(row, limits, strict=True):
            _integer(value, low, high, f"saved vector{member:#x} entry")
    return rows


def normalize_replay_training_index(saved_index: int, count: int) -> int:
    """Original14133494b..141334991, with coherent signed-i16 vector count.

    This integer-only interval preserves0<=index<count and otherwise writes
    count-1. Counts above32767 are unsupported because native compares DX as
    signed i16. No vector allocation, pointer validation or reader is modeled.
    """
    _integer(saved_index, -32768, 32767, "saved training index i16")
    _integer(count, 0, 32767, "training count0..32767")
    return saved_index if 0 <= saved_index < count else count - 1


def restore_replay_master_combat(
    saved: SavedMaster, selected_baseline: Mapping[int, GameDataMaster | None]
) -> ReplayMasterCombat:
    """Restore the numeric Combat50 facet of a parsed save68.9 definition.

    The source table must be the same explicit selection used by other master
    components. Source families below50 retain constructor-zero2fc; other
    saved values override the baseline. Raw graphics IDs are kept separately.
    """
    index, baseline = _selected(saved, selected_baseline, 50)
    fields = _scalars(saved, _COMBAT_I16, _COMBAT_U8, _COMBAT_U32)
    fields[0x2FC] = (
        _member(baseline.fields, 0x2FC, 0, 0xFFFFFFFF, "baseline")
        if baseline.type_group >= 50
        else 0
    )
    pairs = []
    for count_offset, data_offset in ((0x2B0, 0x2B8), (0x2A2, 0x2A8)):
        rows = _rows(saved, data_offset, 2, ((-32768, 32767), (-32768, 32767)))
        if len(rows) != max(0, fields[count_offset]):
            raise ReplayMasterCombatError(f"saved count disagrees with vector{data_offset:#x}")
        pairs.append(tuple((row[0], row[1]) for row in rows))
    graphics = {
        offset: _member(saved.fields, offset, -32768, 32767, "saved graphic")
        for offset in (0x298, 0x318)
    }
    return ReplayMasterCombat(index, fields, pairs[0], pairs[1], graphics, saved, baseline)


def restore_replay_master_unit(
    saved: SavedMaster, selected_baseline: Mapping[int, GameDataMaster | None]
) -> ReplayMasterUnit:
    """Restore Unit70 scalars/costs/training, preserving original wire state.

    Modern68.9 training is supplied by the save, not inherited. A source below
    family70 supplies constructor-zero358. This does not restore Building80
    extension fields, apply research, or resolve any graphics IDs.
    """
    index, baseline = _selected(saved, selected_baseline, 70)
    fields = _scalars(saved, _UNIT_I16, _UNIT_U8, _UNIT_U32)
    fields[0x358] = (
        _member(baseline.fields, 0x358, 0, 0xFFFFFFFF, "baseline")
        if baseline.type_group >= 70
        else 0
    )
    costs = _rows(saved, 0x320, 4, ((-32768, 32767), (-32768, 32767), (0, 255), (0, 255)))
    if len(costs) != 3:
        raise ReplayMasterCombatError("saved cost vector must contain three slots")
    for number, row in enumerate(costs):
        for value, delta, (low, high) in zip(
            row, (0, 2, 4, 5), ((-32768, 32767), (-32768, 32767), (0, 255), (0, 255)), strict=True
        ):
            member = 0x320 + number * 6 + delta
            if _member(saved.fields, member, low, high, "saved cost") != value:
                raise ReplayMasterCombatError("saved cost members disagree with vector")
    raw_count = saved.sections.get("train_locations.count")
    if type(raw_count) is not bytes or len(raw_count) != 2:
        raise ReplayMasterCombatError("missing or invalid saved training count bytes")
    count = int.from_bytes(raw_count, "little", signed=True)
    training = _rows(saved, 0x338, 4, ((-32768, 32767), (-32768, 32767), (0, 255), (0, 0xFFFFFFFF)))
    if len(training) != max(0, count):
        raise ReplayMasterCombatError("saved training count disagrees with vector")
    fields[0x3E0] = normalize_replay_training_index(fields[0x3E0], len(training))
    graphics = {
        offset: _member(saved.fields, offset, -32768, 32767, "saved graphic")
        for offset in (0x388, 0x390, 0x398, 0x3A0, 0x3A8, 0x3B0)
    }
    return ReplayMasterUnit(
        index,
        fields,
        tuple((r[0], r[1], r[2], r[3]) for r in costs),
        count,
        tuple((r[0], r[1], r[2], r[3]) for r in training),
        graphics,
        saved,
        baseline,
    )
