"""Original classifier observations and source-bound missing-context frontiers."""

from __future__ import annotations

import gzip
import json
from collections.abc import MutableMapping
from pathlib import Path
from typing import Any, cast

import pytest

from vantage.replay_owner_classification import (
    ReplayOwnerClassificationContext,
    ReplayOwnerMasterClassificationInput,
    UnresolvedReplayOwnerClassification,
    classify_replay_owner_master,
)
from vantage.replay_owner_promotion import ReplayOwnerClassification

FIXTURE = Path(__file__).parent / "fixtures/native_owner_classification_54800.json.gz"


def _cases() -> list[dict[str, Any]]:
    return cast(list[dict[str, Any]], json.loads(gzip.decompress(FIXTURE.read_bytes()))["cases"])


def _actual_context(before: dict[str, Any]) -> ReplayOwnerClassificationContext:
    regions = {
        region["region"]: ReplayOwnerMasterClassificationInput(
            region["type_byte_8"],
            region["decoded_class_i16"],
            region["annex_i16_426"],
            region["training_i16_458"],
            region["flag_i16_430"],
        )
        for region in before["master_regions"]
    }
    slots = {
        slot["index"]: None if slot["region"] is None else regions[slot["region"]]
        for slot in before["owner_slots"]
    }
    tokens = before["global_pointer_tokens"]
    return ReplayOwnerClassificationContext(
        slots,
        before["row_count_qword"],
        before["selection_count_qword"],
        None
        if tokens["row_pointer"] == "null"
        else {row["index"]: row["group_i32"] for row in before["group_rows"]},
        None
        if tokens["selection_pointer"] == "null"
        else dict(enumerate(before["selections_i32"])),
    )


@pytest.mark.parametrize("case", _cases(), ids=lambda case: case["name"])
def test_original_whole_classifier_entry(case: dict[str, Any]) -> None:
    result = classify_replay_owner_master(_actual_context(case["before"]), case["requested_id"])
    assert [result.master_id & 0xFFFFFFFF, result.class_id & 0xFFFFFFFF, result.flags] == (
        case["result_words"]
    )


def _context(
    master: ReplayOwnerMasterClassificationInput,
    *,
    row_count: int = 0,
    groups: dict[int, int] | None = None,
    selections: dict[int, int] | None = None,
) -> ReplayOwnerClassificationContext:
    return ReplayOwnerClassificationContext({2: master}, row_count, 200, groups, selections)


def test_missing_initial_slot_is_unknown_instead_of_an_invented_null() -> None:
    context = ReplayOwnerClassificationContext({}, 0, 0, None, None)
    with pytest.raises(UnresolvedReplayOwnerClassification, match="slot 2"):
        classify_replay_owner_master(context, 2)


def test_annex_slot_read_precedes_numeric_rejection() -> None:
    context = _context(ReplayOwnerMasterClassificationInput(80, member_426=-2))
    with pytest.raises(UnresolvedReplayOwnerClassification, match="slot -2"):
        classify_replay_owner_master(context, 2)


def test_final_slot_read_precedes_numeric_rejection() -> None:
    context = _context(ReplayOwnerMasterClassificationInput(70, 3), row_count=16, groups={2: 0})
    with pytest.raises(UnresolvedReplayOwnerClassification, match="slot -1"):
        classify_replay_owner_master(context, 2)


def test_suppressed_class_is_not_required() -> None:
    context = _context(ReplayOwnerMasterClassificationInput(80, None, -1, 619, -1))
    assert classify_replay_owner_master(context, 2) == ReplayOwnerClassification(2, -1, 1)


def test_member430_is_not_read_when458_is_minus_one() -> None:
    context = _context(ReplayOwnerMasterClassificationInput(80, 3, -1, -1, None))
    assert classify_replay_owner_master(context, 2) == ReplayOwnerClassification(2, 3, 1)


def test_nonbuilding_does_not_require_building_fields() -> None:
    context = _context(ReplayOwnerMasterClassificationInput(70, 3))
    assert classify_replay_owner_master(context, 2) == ReplayOwnerClassification(2, 3, 0)


@pytest.mark.parametrize("count", [0, 0xFFFFFFFFFFFFFFFF, 0xABCDEF0000000000])
def test_inactive_row_table_does_not_require_payloads(count: int) -> None:
    context = _context(ReplayOwnerMasterClassificationInput(70, 3), row_count=count)
    assert classify_replay_owner_master(context, 2) == ReplayOwnerClassification(2, 3, 0)


def test_admitted_row_requires_known_group() -> None:
    context = _context(ReplayOwnerMasterClassificationInput(70, 3), row_count=16)
    with pytest.raises(UnresolvedReplayOwnerClassification, match="variant group"):
        classify_replay_owner_master(context, 2)


def test_admitted_line_requires_known_selection() -> None:
    context = _context(ReplayOwnerMasterClassificationInput(70, 3), row_count=16, groups={2: -399})
    with pytest.raises(UnresolvedReplayOwnerClassification, match="canonical selection"):
        classify_replay_owner_master(context, 2)


def test_enabled_class_read_requires_known_decoded_class() -> None:
    context = _context(ReplayOwnerMasterClassificationInput(70))
    with pytest.raises(UnresolvedReplayOwnerClassification, match="decoded_class"):
        classify_replay_owner_master(context, 2)


@pytest.mark.parametrize("value", [9000, 0xFFFFFFFF])
def test_early_numeric_rejection_does_not_need_context(value: int) -> None:
    assert classify_replay_owner_master(cast(Any, None), value) == (
        ReplayOwnerClassification(-1, -1, 0)
    )


def test_context_retains_its_explicit_snapshot() -> None:
    slots: dict[int, ReplayOwnerMasterClassificationInput | None] = {
        2: ReplayOwnerMasterClassificationInput(70, 3)
    }
    groups, selections = {2: -1}, {0: 3}
    context = ReplayOwnerClassificationContext(slots, 16, 200, groups, selections)
    slots[2], groups[2], selections[0] = None, -399, 2
    assert classify_replay_owner_master(context, 2) == ReplayOwnerClassification(2, 3, 0)
    with pytest.raises(TypeError):
        cast(MutableMapping[int, int], context.groups)[2] = -399
