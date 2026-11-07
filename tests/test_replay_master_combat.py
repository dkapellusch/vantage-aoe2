"""Independent native projections and original Unit70 clamp outputs."""

from __future__ import annotations

import copy
import gzip
import hashlib
import json
import struct
from dataclasses import replace
from functools import lru_cache
from pathlib import Path
from typing import Any

import pytest

from vantage.replay_binary import SaveReader
from vantage.replay_game_data import GameDataMaster, read_game_data_master
from vantage.replay_master_combat import (
    ReplayMasterCombatError,
    normalize_replay_training_index,
    restore_replay_master_combat,
    restore_replay_master_unit,
)
from vantage.replay_masters import SavedMaster, read_master

FIXTURES = Path(__file__).parent / "fixtures"


@lru_cache(maxsize=1)
def _paired() -> dict[str, Any]:
    return json.loads(
        gzip.decompress((FIXTURES / "native_saved_combat_unit_master_54800.json.gz").read_bytes())
    )


def _decode(case: dict[str, Any]) -> tuple[SavedMaster, GameDataMaster]:
    reader = SaveReader(bytes.fromhex(case["saved_hex"]))
    saved = read_master(reader, master_id=case["master_id"], type_group=case["saved_type"])
    assert reader.remaining == 0
    reader = SaveReader(bytes.fromhex(case["baseline_hex"]), version=0x43E666)
    baseline = read_game_data_master(reader)
    assert reader.remaining == 0 and baseline.type_group == case["baseline_type"]
    return saved, baseline


def _prototype() -> tuple[SavedMaster, GameDataMaster]:
    return _decode(next(case for case in _paired()["cases"] if case["saved_type"] == 70))


def _training(saved: SavedMaster, count: int, rows: tuple, index: int) -> SavedMaster:
    return replace(
        saved,
        fields={**saved.fields, 0x3E0: index},
        vectors={**saved.vectors, 0x338: rows},
        sections={**saved.sections, "train_locations.count": struct.pack("<h", count)},
    )


@pytest.mark.parametrize(
    "case", _paired()["cases"], ids=lambda c: f"{c['sample']}-p{c['owner']}-master{c['master_id']}"
)
def test_original_native_paired_combat_unit_numeric_values(case: dict[str, Any]) -> None:
    saved, baseline = _decode(case)
    table = {case["baseline_index"]: baseline}
    before = copy.deepcopy((saved, table))
    combat = restore_replay_master_combat(saved, table)
    unit = restore_replay_master_unit(saved, table) if saved.type_group >= 70 else None
    expected = {row["field"]: row["value"] for row in case["native_expected"]}
    for fid, offset, representation, family, _inherited in _paired()["bindings"]:
        if saved.type_group < family:
            continue
        component = combat if family == 50 else unit
        assert component is not None
        actual = component.fields[offset]
        if representation == "i32" and actual >= 0x80000000:
            actual -= 1 << 32
        assert actual == expected[fid], (fid, offset)
    for fid, rows in case["native_vectors"].items():
        if fid in {"30", "31"}:
            assert (combat.armor if fid == "30" else combat.weapons) == tuple(map(tuple, rows))
        else:
            assert unit is not None
            if fid == "40":
                assert tuple(row[:3] for row in unit.costs) == tuple(map(tuple, rows))
            else:
                assert fid == "94"
                assert tuple(row[1] for row in unit.training) == tuple(rows)
    assert len(combat.fields) == 27
    assert combat.saved is saved and combat.baseline is baseline
    assert set(combat.saved_graphic_ids) == {0x298, 0x318}
    assert set(combat.saved_graphic_ids).isdisjoint(combat.fields)
    if unit is not None:
        assert len(unit.fields) == 28 and unit.saved is saved and unit.baseline is baseline
        assert (unit.training[0][0] if unit.training else 0) == expected[38]
        assert (unit.training[0][1] if unit.training else -1) == expected[39]
        assert set(unit.saved_graphic_ids) == {0x388, 0x390, 0x398, 0x3A0, 0x3A8, 0x3B0}
        assert set(unit.saved_graphic_ids).isdisjoint(unit.fields)
        assert all(len(raw) == 6 for raw in unit.cost_bytes)
    for component in (combat, unit):
        if component is not None:
            assert component.baseline_index == case["baseline_index"]
    assert (saved, table) == before


def test_all_2186_actual_original_outputs_match_complete_destination_images() -> None:
    oracle = json.loads(
        gzip.decompress((FIXTURES / "native_unit_training_index_2186.json.gz").read_bytes())
    )
    assert oracle["evidence_id"] == (
        "ev_9139e5879d52adda31c1b884494b50e7639cb3fc2db838615d9d4116e5759ffd"
    )
    assert oracle["source_output"]["sha256"] == (
        "51a3703feeb3d2ae6085264313bce858457b647547a05cb2d7988db6e84486d2"
    )
    assert oracle["original_bytes"] == 70 and oracle["original_instructions"] == 18
    assert oracle["helper_calls"] == 0 and len(oracle["cases"]) == 2186
    assert oracle["observed_terminal_events"] == 2186 and oracle["exact_negative_controls"] == 6
    for case in oracle["cases"]:
        before = bytearray.fromhex(case["before_hex"])
        observed = bytes.fromhex(case["output_hex"])
        assert len(before) == len(observed) == 1024
        assert struct.unpack_from("<h", before, 0x3E0)[0] == case["saved_index"]
        value = normalize_replay_training_index(case["saved_index"], case["count"])
        assert value == case["observed_index"] == struct.unpack_from("<h", observed, 0x3E0)[0]
        struct.pack_into("<h", before, 0x3E0, value)
        assert bytes(before) == observed, case["id"]


@pytest.mark.parametrize("kind", [50, 60, 70, 80])
def test_supported_combat_factory_families(kind: int) -> None:
    saved, baseline = _prototype()
    saved = replace(saved, type_group=kind, base=replace(saved.base, type_group=kind))
    assert restore_replay_master_combat(saved, {0: baseline}).saved is saved
    if kind < 70:
        with pytest.raises(ReplayMasterCombatError, match="saved master family"):
            restore_replay_master_unit(saved, {0: baseline})


@pytest.mark.parametrize("kind", [10, 40, 90, True, 70.0])
def test_untyped_or_unsupported_saved_family_fails(kind: Any) -> None:
    saved, baseline = _prototype()
    saved = replace(saved, type_group=kind, base=replace(saved.base, type_group=kind))
    with pytest.raises(ReplayMasterCombatError, match="saved master family"):
        restore_replay_master_combat(saved, {0: baseline})


@pytest.mark.parametrize("kind", [10, 40, 50, 60, 70, 80])
def test_incompatible_baseline_facets_keep_constructor_zero_only(kind: int) -> None:
    saved, baseline = _prototype()
    fields = {**baseline.fields, 0x2FC: 0x80000000, 0x358: 0x7FC12345}
    if kind < 50:
        del fields[0x2FC]
    if kind < 70:
        del fields[0x358]
    baseline = replace(baseline, type_group=kind, fields=fields)
    combat = restore_replay_master_combat(saved, {0: baseline})
    unit = restore_replay_master_unit(saved, {0: baseline})
    assert combat.fields[0x2FC] == (0x80000000 if kind >= 50 else 0)
    assert unit.fields[0x358] == (0x7FC12345 if kind >= 70 else 0)


@pytest.mark.parametrize("word", [0, 0x80000000, 0x7F800000, 0x7FC12345, 0xFFFFFFFF])
def test_inherited_words_and_saved_overrides_keep_all_raw_bits(word: int) -> None:
    saved, baseline = _prototype()
    baseline = replace(
        baseline,
        fields={
            **baseline.fields,
            0x2FC: word,
            0x358: word,
            0x2D8: 0xBADB00B5,
            0x354: 0xBADB00B5,
            0x999: 7,
        },
    )
    saved = replace(saved, fields={**saved.fields, 0x2D8: word, 0x354: word})
    before = copy.deepcopy((saved, baseline))
    combat = restore_replay_master_combat(saved, {0: baseline})
    unit = restore_replay_master_unit(saved, {0: baseline})
    assert combat.fields[0x2FC] == combat.fields[0x2D8] == word
    assert unit.fields[0x358] == unit.fields[0x354] == word
    assert 0x999 not in combat.fields and 0x999 not in unit.fields
    assert (saved, baseline) == before


@pytest.mark.parametrize("selector,index", [(0, 0), (768, 420), (770, 691)])
def test_selector_remaps_do_not_rewrite_saved_ids(selector: int, index: int) -> None:
    saved, baseline = _prototype()
    saved = replace(
        saved,
        base=replace(
            saved.base, baseline_id=selector, fields={**saved.base.fields, 0x20: selector}
        ),
    )
    assert restore_replay_master_combat(saved, {index: baseline}).baseline_index == index
    assert restore_replay_master_unit(saved, {index: baseline}).baseline_index == index
    assert saved.base.baseline_id == saved.base.fields[0x20] == selector


@pytest.mark.parametrize("selector", [-1, 32768, True])
def test_out_of_profile_selector_is_rejected(selector: int) -> None:
    saved, baseline = _prototype()
    saved = replace(saved, base=replace(saved.base, baseline_id=selector))
    with pytest.raises(ReplayMasterCombatError, match="baseline selector"):
        restore_replay_master_combat(saved, {0: baseline})


@pytest.mark.parametrize("table", [{}, {0: None}, {1: None}])
def test_missing_and_null_selected_source_are_not_guessed(table: dict) -> None:
    saved, _ = _prototype()
    for function in (restore_replay_master_combat, restore_replay_master_unit):
        with pytest.raises(ReplayMasterCombatError, match="missing or null"):
            function(saved, table)


def test_alias_family_and_required_inherited_members_are_validated() -> None:
    saved, baseline = _prototype()
    for broken in (
        replace(saved, base=replace(saved.base, type_group=50)),
        replace(saved, base=replace(saved.base, baseline_id=1)),
    ):
        with pytest.raises(ReplayMasterCombatError):
            restore_replay_master_combat(broken, {0: baseline, 1: baseline})
    for function, offset in (
        (restore_replay_master_combat, 0x2FC),
        (restore_replay_master_unit, 0x358),
    ):
        fields = dict(baseline.fields)
        del fields[offset]
        with pytest.raises(ReplayMasterCombatError, match="missing baseline"):
            function(saved, {0: replace(baseline, fields=fields)})


@pytest.mark.parametrize(
    "offset,bad",
    [(0x2A0, -32769), (0x2A0, 32768), (0x2D0, 256), (0x2D0, True), (0x2D8, -1), (0x2D8, 1 << 32)],
)
def test_combat_saved_scalar_bounds(offset: int, bad: int) -> None:
    saved, baseline = _prototype()
    saved = replace(saved, fields={**saved.fields, offset: bad})
    with pytest.raises(ReplayMasterCombatError, match="invalid saved"):
        restore_replay_master_combat(saved, {0: baseline})


@pytest.mark.parametrize(
    "offset,bad",
    [(0x3E0, -32769), (0x3C0, 32768), (0x35C, 256), (0x35C, True), (0x354, -1), (0x354, 1 << 32)],
)
def test_unit_saved_scalar_bounds(offset: int, bad: int) -> None:
    saved, baseline = _prototype()
    saved = replace(saved, fields={**saved.fields, offset: bad})
    with pytest.raises(ReplayMasterCombatError, match="invalid saved"):
        restore_replay_master_unit(saved, {0: baseline})


@pytest.mark.parametrize("bad", [-1, 1 << 32, True])
def test_inherited_u32_bounds(bad: int) -> None:
    saved, baseline = _prototype()
    baseline = replace(baseline, fields={**baseline.fields, 0x2FC: bad, 0x358: bad})
    for function in (restore_replay_master_combat, restore_replay_master_unit):
        with pytest.raises(ReplayMasterCombatError, match="invalid baseline"):
            function(saved, {0: baseline})


def test_pairs_keep_order_duplicates_and_signed_nonpositive_counts() -> None:
    saved, baseline = _prototype()
    rows = ((32767, -32768), (-1, 7), (-1, 7))
    saved = replace(
        saved,
        fields={**saved.fields, 0x2B0: 3, 0x2A2: -32768},
        vectors={**saved.vectors, 0x2B8: rows, 0x2A8: ()},
    )
    result = restore_replay_master_combat(saved, {0: baseline})
    assert result.weapons == rows and result.armor == ()
    assert result.fields[0x2A2] == -32768
    broken = replace(saved, fields={**saved.fields, 0x2B0: -1})
    with pytest.raises(ReplayMasterCombatError, match="count disagrees"):
        restore_replay_master_combat(broken, {0: baseline})


@pytest.mark.parametrize("rows", [((1,),), ((1, 32768),), ((True, 0),), ((0, 0, 0),)])
def test_invalid_pair_entries_are_rejected(rows: tuple) -> None:
    saved, baseline = _prototype()
    saved = replace(
        saved, fields={**saved.fields, 0x2B0: 1}, vectors={**saved.vectors, 0x2B8: rows}
    )
    with pytest.raises(ReplayMasterCombatError, match="invalid saved vector"):
        restore_replay_master_combat(saved, {0: baseline})


def test_costs_preserve_final_values_and_every_initial_padding_byte() -> None:
    saved, baseline = _prototype()
    slots = ((-32768, 32767, 255, 1), (0, -1, 0, 128), (32767, -32768, 7, 255))
    fields = dict(saved.fields)
    for number, row in enumerate(slots):
        fields.update(
            {
                0x320 + number * 6 + delta: value
                for delta, value in zip((0, 2, 4, 5), row, strict=True)
            }
        )
    saved = replace(saved, fields=fields, vectors={**saved.vectors, 0x320: slots})
    before = copy.deepcopy(saved)
    result = restore_replay_master_unit(saved, {0: baseline})
    assert result.costs == slots
    assert result.cost_bytes == tuple(struct.pack("<hhBB", *row) for row in slots)
    assert result.saved is saved and saved == before
    broken = replace(saved, fields={**saved.fields, 0x325: 2})
    with pytest.raises(ReplayMasterCombatError, match="cost members disagree"):
        restore_replay_master_unit(broken, {0: baseline})


@pytest.mark.parametrize("count", [0, 2, 4])
def test_unit_costs_require_exactly_three_slots(count: int) -> None:
    saved, baseline = _prototype()
    saved = replace(saved, vectors={**saved.vectors, 0x320: ((0, 0, 0, 0),) * count})
    with pytest.raises(ReplayMasterCombatError, match="three slots"):
        restore_replay_master_unit(saved, {0: baseline})


@pytest.mark.parametrize("index", [-32768, -2, -1, 0, 1, 2, 32767])
def test_unit_training_keeps_wire_order_and_normalizes_without_mutating_raw(index: int) -> None:
    saved, baseline = _prototype()
    rows = ((23, 109, 4, 0xFFFFFFFF), (-32768, -1, 255, 0))
    saved = _training(saved, 2, rows, index)
    result = restore_replay_master_unit(saved, {0: baseline})
    assert result.training == rows and result.training_count == 2
    assert result.training_index == (index if index in (0, 1) else 1)
    assert saved.fields[0x3E0] == index and saved.vectors[0x338] is rows
    assert result.saved is saved


@pytest.mark.parametrize("count", [-32768, -1, 0])
def test_nonpositive_training_count_overrides_nonempty_baseline_with_empty(count: int) -> None:
    saved, baseline = _prototype()
    saved = _training(saved, count, (), 0)
    baseline = replace(baseline, definition_records_9=(b"baseline-does-not-win",))
    result = restore_replay_master_unit(saved, {0: baseline})
    assert result.training == () and result.training_count == count
    assert result.training_index == -1 and saved.fields[0x3E0] == 0


def test_malformed_training_count_or_values_fail_without_mutation() -> None:
    saved, baseline = _prototype()
    failures = [
        _training(saved, 1, (), 0),
        _training(saved, -1, ((0, -1, 0, 0),), 0),
        _training(saved, 1, ((0, -1, 256, 0),), 0),
        _training(saved, 1, ((0, -1, 0, 1 << 32),), 0),
        replace(saved, sections={**saved.sections, "train_locations.count": b"\x00"}),
    ]
    for broken in failures:
        before = copy.deepcopy(broken)
        with pytest.raises(ReplayMasterCombatError, match=r"training|vector"):
            restore_replay_master_unit(broken, {0: baseline})
        assert broken == before


@pytest.mark.parametrize(
    "index,count",
    [(32768, 1), (-32769, 1), (True, 1), (0, -1), (0, 32768), (0, 65535), (0, True), (0, 1.0)],
)
def test_training_clamp_rejects_values_outside_closed_native_profile(
    index: Any, count: Any
) -> None:
    with pytest.raises(ReplayMasterCombatError, match="training"):
        normalize_replay_training_index(index, count)


def test_graphics_remain_unresolved_raw_ids_and_outputs_do_not_alias_inputs() -> None:
    saved, baseline = _prototype()
    offsets = (0x298, 0x318, 0x388, 0x390, 0x398, 0x3A0, 0x3A8, 0x3B0)
    saved = replace(saved, fields={**saved.fields, **{offset: -1 for offset in offsets}})
    combat = restore_replay_master_combat(saved, {0: baseline})
    unit = restore_replay_master_unit(saved, {0: baseline})
    assert set(combat.saved_graphic_ids.values()) == set(unit.saved_graphic_ids.values()) == {-1}
    assert all(offset not in combat.fields and offset not in unit.fields for offset in offsets)
    combat.fields[0x2FC] = 0xFFFFFFFF
    unit.fields[0x358] = 0xFFFFFFFF
    combat.saved_graphic_ids[0x298] = 7
    assert saved.fields[0x298] == -1
    assert baseline.fields[0x2FC] != combat.fields[0x2FC]
    assert baseline.fields[0x358] != unit.fields[0x358]


def test_original_paired_corpus_contains_all_players_and_inherited_patterns() -> None:
    fixture = _paired()
    assert len(fixture["cases"]) == 70
    assert len({(c["sample"], c["owner"]) for c in fixture["cases"]}) == 11
    patterns = {
        (row["member"], row["value"])
        for case in fixture["cases"]
        for row in case["native_expected"]
        if row.get("member") in {"0x2fc", "0x358"}
    }
    assert len(patterns) == 41
    assert (
        hashlib.sha256(
            (FIXTURES / "native_saved_combat_unit_master_54800.json.gz").read_bytes()
        ).hexdigest()
        == "c0ecc0f16b22ee8f0f633800a3ca9eaedf657db1b3ec2a7fdb93e543f478477b"
    )


@pytest.mark.parametrize(
    "function,offset",
    [
        (restore_replay_master_combat, 0x2E4),
        (restore_replay_master_combat, 0x2A2),
        (restore_replay_master_unit, 0x37C),
        (restore_replay_master_unit, 0x3D0),
    ],
)
def test_unpublished_required_saved_members_are_not_filled_from_dat(
    function: Any, offset: int
) -> None:
    saved, baseline = _prototype()
    fields = dict(saved.fields)
    del fields[offset]
    broken = replace(saved, fields=fields)
    before = copy.deepcopy(broken)
    with pytest.raises(ReplayMasterCombatError, match="missing saved"):
        function(broken, {0: baseline})
    assert broken == before


@pytest.mark.parametrize("kind", [True, 70.0, 9])
def test_untyped_unknown_baseline_family_is_rejected(kind: Any) -> None:
    saved, baseline = _prototype()
    with pytest.raises(ReplayMasterCombatError, match="baseline master family"):
        restore_replay_master_combat(saved, {0: replace(baseline, type_group=kind)})


@pytest.mark.parametrize(
    "function,member",
    [
        (restore_replay_master_combat, 0x2A8),
        (restore_replay_master_unit, 0x338),
    ],
)
def test_missing_saved_vectors_are_not_inherited(function: Any, member: int) -> None:
    saved, baseline = _prototype()
    vectors = dict(saved.vectors)
    del vectors[member]
    with pytest.raises(ReplayMasterCombatError, match="missing saved vector"):
        function(replace(saved, vectors=vectors), {0: baseline})
