"""Gaia's native master-table overlay before saved master construction.

Gaia virtual+118 (141752240) differs from the ordinary Player getter: member57c
can select a nonnull overlay over the member6a0 civilization's master pointers.
The first result is cached. Saved master cloning and later edits are separate.
Evidence: artifacts/game-internals/2026-10-18-world-envelope/gaia-task-source-selection/.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from vantage.replay_game_data import GameDataMaster


class ReplayMasterBaselineError(ValueError):
    """A supplied native table or selector is outside the supported profile."""


def _table(entries: Sequence[GameDataMaster | None]) -> tuple[GameDataMaster | None, ...]:
    if len(entries) > 32767:
        raise ReplayMasterBaselineError("master table count must be a nonnegative i16")
    return tuple(entries)


@dataclass(slots=True)
class ReplayGaiaMasterCache:
    """Value counterpart of Gaia members16bc and16c0/16c8.

    Construction starts empty with selected_index=-1. The native getter reuses
    a nonempty cache even after the selector changes to another valid value.
    Invalid selectors still return the base table first. Keeping this state is
    necessary when restoring or seeking; changing the selector does not reset it.
    Pointer allocation, capacities and source-object lifetime are not modeled.
    """

    entries: tuple[GameDataMaster | None, ...] = ()
    selected_index: int = -1

    def select(
        self,
        base: Sequence[GameDataMaster | None],
        civilizations: Mapping[int, Sequence[GameDataMaster | None]],
        *,
        selector_word: int,
        civilization_count: int,
    ) -> tuple[GameDataMaster | None, ...]:
        """Return the effective table for one Gaia virtual+118 call.

        selector_word preserves the saved u32 member57c bits, interpreted as a
        signed int by native code. civilization_count is the mode-dependent
        result of140f6ad30, supplied explicitly rather than inferred from which
        DAT tables the caller loaded.65537/65539 select civilization1 when the
        ordinary range test fails. Nonnull overlay entries replace base entries;
        null entries preserve the base or newly extended null slot.

        Only tables reached by the original branch are required. The supported
        DAT table counts are nonnegative signed16 values. This does not choose
        the base civilization or apply the result to saved/runtime masters.
        """
        if type(selector_word) is not int or not 0 <= selector_word <= 0xFFFFFFFF:
            raise ReplayMasterBaselineError("selector word must be a u32")
        if type(civilization_count) is not int or not -(1 << 31) <= civilization_count < 1 << 31:
            raise ReplayMasterBaselineError("civilization count must be an i32")
        index = selector_word if selector_word < 0x80000000 else selector_word - 0x100000000
        if not 1 <= index < civilization_count:
            if index not in (65537, 65539):
                return _table(base)
            index = 1
        if self.entries:
            return self.entries
        selected = civilizations.get(index)
        if selected is None:
            raise ReplayMasterBaselineError(f"missing civilization master table at index {index}")
        base_table, overlay = _table(base), _table(selected)
        merged = list(base_table) + [None] * max(0, len(overlay) - len(base_table))
        for ordinal, master in enumerate(overlay):
            if master is not None:
                merged[ordinal] = master
        self.entries = tuple(merged)
        self.selected_index = index
        return self.entries
