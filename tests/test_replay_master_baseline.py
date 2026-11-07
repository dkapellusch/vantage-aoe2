"""Native Gaia selector branches and preserved master-pointer overlay values."""

from __future__ import annotations

import gzip
import json
import struct
from pathlib import Path
from typing import Any

import pytest

from vantage.replay_binary import SaveReader
from vantage.replay_game_data import (
    GameDataMaster,
    GameDataMasterCommon,
    read_game_data_master,
)
from vantage.replay_master_baseline import ReplayGaiaMasterCache, ReplayMasterBaselineError
from vantage.replay_master_tasks import ReplayMasterTask, restore_replay_master_tasks
from vantage.replay_masters import read_master


def _master(marker: int) -> GameDataMaster:
    common = GameDataMasterCommon(0, 0, {}, 0, b"", (), (), {}, {}, b"", {}, b"")
    return GameDataMaster(
        0, 0, 70, common, {0x230: marker}, {}, {}, {}, (), (), {}, (), (), (), {}, b""
    )


def test_nonnull_overlay_preserves_base_holes_and_extends_with_null_slots() -> None:
    base0, base1, overlay1, overlay3 = (_master(n) for n in range(4))
    base = (base0, base1, None)
    overlay = (None, overlay1, None, overlay3, None)
    cache = ReplayGaiaMasterCache()
    result = cache.select(base, {11: overlay}, selector_word=11, civilization_count=63)
    assert result == (base0, overlay1, None, overlay3, None)
    assert result[0] is base0 and result[1] is overlay1 and result[3] is overlay3
    assert cache.entries is result and cache.selected_index == 11
    assert base == (base0, base1, None) and overlay == (None, overlay1, None, overlay3, None)


def test_short_overlay_preserves_remaining_base_entries() -> None:
    first, second, overlay = (_master(n) for n in range(3))
    result = ReplayGaiaMasterCache().select(
        (first, second), {13: (overlay,)}, selector_word=13, civilization_count=63
    )
    assert result == (overlay, second)


def test_invalid_selector_returns_base_before_nonempty_cache_and_preserves_cache() -> None:
    base, cached = _master(0), _master(1)
    cache = ReplayGaiaMasterCache((cached,), 11)
    assert cache.select((base,), {}, selector_word=0, civilization_count=63) == (base,)
    assert cache.entries == (cached,) and cache.selected_index == 11
    # A subsequent different valid selector still returns the old cache and
    # does not require the caller to have loaded its new civilization table.
    assert cache.select((), {}, selector_word=13, civilization_count=63) is cache.entries
    assert cache.selected_index == 11


def test_zero_length_cached_result_rebuilds_on_next_valid_call() -> None:
    cache = ReplayGaiaMasterCache()
    assert cache.select((), {11: ()}, selector_word=11, civilization_count=63) == ()
    assert cache.selected_index == 11
    replacement = _master(0)
    assert cache.select((), {13: (replacement,)}, selector_word=13, civilization_count=63) == (
        replacement,
    )
    assert cache.selected_index == 13


@pytest.mark.parametrize("selector", [65537, 65539])
def test_special_selectors_alias_one_even_beyond_ordinary_count(selector: int) -> None:
    master = _master(1)
    cache = ReplayGaiaMasterCache()
    assert cache.select((), {1: (master,)}, selector_word=selector, civilization_count=0) == (
        master,
    )
    assert cache.selected_index == 1


def test_special_selector_in_ordinary_range_retains_its_own_index() -> None:
    master = _master(1)
    cache = ReplayGaiaMasterCache()
    assert cache.select((), {65537: (master,)}, selector_word=65537, civilization_count=65538) == (
        master,
    )
    assert cache.selected_index == 65537


@pytest.mark.parametrize(
    "selector", [0, 63, 65536, 65538, 65540, 0x7FFFFFFF, 0x80000000, 0xFFFFFFFF]
)
def test_invalid_and_signed_negative_words_fall_back_without_cache_write(selector: int) -> None:
    master = _master(0)
    cache = ReplayGaiaMasterCache()
    assert cache.select((master,), {}, selector_word=selector, civilization_count=63) == (master,)
    assert cache.entries == () and cache.selected_index == -1


def test_valid_selector_requires_selected_table_without_modifying_cache_on_failure() -> None:
    cache = ReplayGaiaMasterCache()
    with pytest.raises(ReplayMasterBaselineError, match="missing civilization"):
        cache.select((), {}, selector_word=11, civilization_count=63)
    assert cache.entries == () and cache.selected_index == -1


@pytest.mark.parametrize("selector", [-1, 0x100000000, True])
def test_non_u32_selector_is_rejected(selector: int) -> None:
    with pytest.raises(ReplayMasterBaselineError, match="u32"):
        ReplayGaiaMasterCache().select((), {}, selector_word=selector, civilization_count=63)


@pytest.mark.parametrize("count", [-(1 << 31) - 1, 1 << 31, True])
def test_non_i32_civilization_count_is_rejected(count: int) -> None:
    with pytest.raises(ReplayMasterBaselineError, match="i32"):
        ReplayGaiaMasterCache().select((), {}, selector_word=0, civilization_count=count)


def test_unreachable_overlay_is_not_loaded_but_oversized_reached_tables_fail() -> None:
    cache = ReplayGaiaMasterCache()
    too_large = (None,) * 32768
    assert cache.select((), {11: too_large}, selector_word=0, civilization_count=63) == ()
    for base, civilizations, selector in [(too_large, {}, 0), ((), {11: too_large}, 11)]:
        with pytest.raises(ReplayMasterBaselineError, match="nonnegative i16"):
            cache.select(base, civilizations, selector_word=selector, civilization_count=63)
    assert cache.entries == () and cache.selected_index == -1


_FIXTURE_PATH = Path(__file__).parent / "fixtures/native_gaia_master_selection_13.json.gz"
_NATIVE_CASES: list[dict[str, Any]] = json.loads(gzip.decompress(_FIXTURE_PATH.read_bytes()))[
    "cases"
]


def _native_task_values(task: ReplayMasterTask) -> dict[str, int | float]:
    """Project retained scalar offsets to the capture's original30 field IDs."""
    members = {
        1: 0xA,
        2: 0xC,
        3: 0xE,
        4: 0x10,
        5: 0x12,
        6: 0x14,
        7: 0x15,
        8: 0x16,
        9: 0x18,
        10: 0x19,
        11: 0x1A,
        12: 0x20,
        13: 0x22,
        14: 0x24,
        15: 0x26,
        16: 0x28,
        17: 0x2C,
        18: 0x30,
        19: 0x1B,
        20: 0x1C,
        21: 0x34,
        22: 0x36,
        27: 0x60,
        28: 0x78,
        29: 0x38,
    }
    result: dict[str, int | float] = {"0": task.type_id}
    for field, offset in members.items():
        value = task.fields[offset]
        result[str(field)] = (
            struct.unpack("<f", struct.pack("<I", value))[0] if field in (16, 17, 18, 20) else value
        )
    result.update({str(23 + i): value for i, value in enumerate(task.sprite_ids)})
    return result


@pytest.mark.parametrize(
    "case",
    _NATIVE_CASES,
    ids=[f"{case['sample']}-master{case['master_id']}" for case in _NATIVE_CASES],
)
def test_selected_dat_baseline_resolves_original_native_task_counterexamples(
    case: dict[str, Any],
) -> None:
    masters = []
    for section in ("base", "overlay"):
        raw = bytes.fromhex(case[section]["raw_hex"])
        reader = SaveReader(raw, version=0x43E666)
        masters.append(read_game_data_master(reader))
        assert reader.pos == len(raw)
    base, overlay = masters
    saved_raw = bytes.fromhex(case["saved"]["raw_hex"])
    reader = SaveReader(saved_raw)
    saved = read_master(reader, master_id=case["master_id"], type_group=case["saved"]["type_group"])
    assert reader.pos == len(saved_raw) and saved.task_count is None
    index = case["baseline_index"]
    # Only this slot is retained here. These sparse controlled input tables do
    # not assert that the unexported slots of either real civilization are null.
    base_table: list[GameDataMaster | None] = [None] * case["base_table_count"]
    overlay_table: list[GameDataMaster | None] = [None] * case["overlay_table_count"]
    base_table[index], overlay_table[index] = base, overlay
    cache = ReplayGaiaMasterCache()
    entries = cache.select(
        base_table,
        {case["selector_word"]: overlay_table},
        selector_word=case["selector_word"],
        civilization_count=case["selector_requires_civilization_count_at_least"],
    )
    selected = {ordinal: master for ordinal, master in enumerate(entries) if master is not None}
    actual = restore_replay_master_tasks(saved, selected)
    assert [_native_task_values(task) for task in actual.tasks] == case["expected_tasks"]
    old = restore_replay_master_tasks(saved, {index: base})
    assert [_native_task_values(task) for task in old.tasks] == case["previous_base_only_tasks"]
    assert case["previous_base_only_tasks"] != case["expected_tasks"]


def test_native_fixture_preserves_every_prior_difference_and_both_saved_selectors() -> None:
    assert len(_NATIVE_CASES) == 13
    assert sum(len(case["changed_fields"]) for case in _NATIVE_CASES) == 33
    assert {(case["sample"], case["selector_word"]) for case in _NATIVE_CASES} == {
        ("3p", 13),
        ("6p", 11),
    }
