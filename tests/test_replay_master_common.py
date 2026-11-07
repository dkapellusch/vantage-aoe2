"""Original common-copy bytes and independently captured t0 scalar regressions."""

from __future__ import annotations

import copy
import gzip
import hashlib
import json
from collections.abc import Iterator, Mapping
from dataclasses import replace
from functools import lru_cache
from pathlib import Path
from typing import Any

import pytest

from vantage import replay_master_common as module
from vantage.replay_binary import SaveReader
from vantage.replay_game_data import GameDataGraphic, GameDataMaster, read_game_data_master
from vantage.replay_master_combat import (
    restore_replay_master_combat,
    restore_replay_master_unit,
)
from vantage.replay_master_common import (
    ReplayMasterCommonError,
    restore_replay_master_common,
    restore_replay_master_components,
)
from vantage.replay_master_movement import restore_replay_master_movement
from vantage.replay_master_tasks import ReplayMasterTasksError, restore_replay_master_tasks
from vantage.replay_masters import SavedMaster, read_master

FIXTURES = Path(__file__).parent / "fixtures"


@lru_cache(maxsize=1)
def _paired() -> dict[str, Any]:
    return json.loads(
        gzip.decompress((FIXTURES / "native_saved_common_master_54800.json.gz").read_bytes())
    )


@lru_cache(maxsize=1)
def _native() -> dict[str, Any]:
    return json.loads(
        gzip.decompress((FIXTURES / "native_common_master_copy_295.json.gz").read_bytes())
    )


def _decode(case: dict[str, Any]) -> tuple[SavedMaster, GameDataMaster]:
    raw = bytes.fromhex(case["saved_hex"])
    assert hashlib.sha256(raw).hexdigest() == case["saved_sha256"]
    reader = SaveReader(raw)
    saved = read_master(reader, master_id=case["master_id"], type_group=case["saved_type"])
    assert reader.remaining == 0
    raw = bytes.fromhex(case["baseline_hex"])
    assert hashlib.sha256(raw).hexdigest() == case["baseline_sha256"]
    reader = SaveReader(raw, version=0x43E666)
    baseline = read_game_data_master(reader)
    assert reader.remaining == 0
    return saved, baseline


def _prototype() -> tuple[SavedMaster, GameDataMaster]:
    return _decode(_paired()["cases"][0])


@pytest.mark.parametrize(
    "case", _paired()["cases"], ids=lambda c: f"{c['sample']}-p{c['owner']}-master{c['master_id']}"
)
def test_original_paired_common_scalar_expectations(case: dict[str, Any]) -> None:
    saved, baseline = _decode(case)
    selected = {case["baseline_index"]: baseline}
    before = copy.deepcopy((saved, selected))
    result = restore_replay_master_common(saved, selected)
    assert result.saved is saved.base and result.baseline is baseline
    assert result.baseline_index == case["baseline_index"]
    for field, offset, representation in _paired()["scalar_bindings"]:
        value = saved.type_group if representation == "type" else result.fields[offset]
        if representation == "bool":
            value = bool(value)
        expected = next(row["value"] for row in case["native_expected"] if row["field"] == field)
        assert value == expected, (field, offset, representation)
    assert result.inherited_fields == {int(o, 16): v for o, v in case["inherited_fields"].items()}
    assert result.descriptor_fc_bits == case["descriptor_fc_bits"]
    assert result.fields[0x14] == saved.base.fields[0xC]
    assert result.fields[0x28] == {768: 420, 770: 691}.get(
        saved.base.fields[0x28], saved.base.fields[0x28]
    )
    assert len(result.fields) == 69
    assert {0x40, 0x48, 0x50, 0x58, 0x13C, 0x158, 0x170, 0x188, 0x1A0, 0xFC}.isdisjoint(
        result.fields
    )
    assert (saved, selected) == before


def test_all_295_original_copy_span_outputs_keep_every_inherited_raw_bit() -> None:
    oracle = _native()
    assert oracle["evidence_id"] == (
        "ev_0d676592ec449c2fc6ad73d49c7710c8044dde32ffaf0dcef38dff386b668ed4"
    )
    assert oracle["original_instructions"] == 96 and oracle["original_bytes"] == 671
    assert oracle["helper_calls"] == 0 and len(oracle["cases"]) == 295
    widths = {int(offset, 16): width for offset, width in oracle["inherited_members"].items()}
    saved, original = _prototype()
    for case in oracle["cases"]:
        source, native = bytes.fromhex(case["source_hex"]), bytes.fromhex(case["output_hex"])
        fields = {
            **original.common.fields,
            **{
                offset: int.from_bytes(source[offset : offset + width], "little")
                for offset, width in widths.items()
            },
        }
        # Derived .fields deliberately disagrees: source must be .common.fields.
        baseline = replace(
            original,
            common=replace(original.common, fields=fields),
            fields={offset: value ^ 0xFF for offset, value in fields.items()},
        )
        result = restore_replay_master_common(saved, {saved.base.baseline_id: baseline})
        expected = {
            offset: int.from_bytes(native[offset : offset + width], "little")
            for offset, width in widths.items()
        }
        assert result.inherited_fields == expected, case["label"]
        assert result.descriptor_fc_bits == original.common.fields[0xFC]
        assert result.saved.raw == saved.base.raw


@pytest.mark.parametrize("selector,index", [(0, 0), (768, 420), (770, 691)])
@pytest.mark.parametrize("other_id", [-1, 768, 770])
def test_runtime_selector_aliases_preserve_original_saved_ids(
    selector: int, index: int, other_id: int
) -> None:
    saved, baseline = _prototype()
    fields = {**saved.base.fields, 0x20: selector, 0x28: other_id, 0xC: -2147483648}
    saved = replace(saved, base=replace(saved.base, baseline_id=selector, fields=fields))
    result = restore_replay_master_common(saved, {index: baseline})
    assert result.baseline_index == result.fields[0x20] == index
    assert result.fields[0x28] == {768: 420, 770: 691}.get(other_id, other_id)
    assert result.fields[0x14] == -2147483648
    assert saved.base.baseline_id == saved.base.fields[0x20] == selector
    assert saved.base.fields[0x28] == other_id and 0x14 not in saved.base.fields


@pytest.mark.parametrize("selector", [-1, 32768, True])
def test_invalid_native_baseline_index_is_rejected(selector: int) -> None:
    saved, baseline = _prototype()
    saved = replace(saved, base=replace(saved.base, baseline_id=selector))
    with pytest.raises(ReplayMasterCommonError, match="nonnegative i16"):
        restore_replay_master_common(saved, {0: baseline})


@pytest.mark.parametrize("selected", [{}, {0: None}, {1: None}])
def test_missing_or_null_reached_baseline_is_rejected(selected: Mapping) -> None:
    saved, _ = _prototype()
    with pytest.raises(ReplayMasterCommonError, match="missing or null"):
        restore_replay_master_common(saved, selected)


@pytest.mark.parametrize(
    "offset", [0x60, 0x88, 0xC0, 0xC4, 0xD0, 0xD1, 0xD2, 0x118, 0x120, 0x124, 0x125, 0xFC]
)
def test_required_inherited_common_scalar_is_not_guessed(offset: int) -> None:
    saved, baseline = _prototype()
    fields = dict(baseline.common.fields)
    del fields[offset]
    baseline = replace(baseline, common=replace(baseline.common, fields=fields))
    with pytest.raises(ReplayMasterCommonError, match="missing baseline"):
        restore_replay_master_common(saved, {0: baseline})


@pytest.mark.parametrize(
    "offset,bad",
    [
        (0x60, -1),
        (0x60, 256),
        (0x60, True),
        (0xC0, -1),
        (0xC0, 0x100000000),
        (0xC0, True),
        (0xFC, -1),
        (0xFC, 0x100000000),
        (0xFC, True),
    ],
)
def test_inherited_u8_u32_and_separate_descriptor_bounds(offset: int, bad: int) -> None:
    saved, baseline = _prototype()
    baseline = replace(
        baseline, common=replace(baseline.common, fields={**baseline.common.fields, offset: bad})
    )
    with pytest.raises(ReplayMasterCommonError, match="invalid baseline"):
        restore_replay_master_common(saved, {0: baseline})


@pytest.mark.parametrize(
    "offset,bad",
    [(0x74, 256), (0x68, -32769), (0xC, 2147483648), (0x78, 0x100000000), (0x90, True)],
)
def test_invalid_saved_scalar_bounds_are_rejected(offset: int, bad: int) -> None:
    saved, baseline = _prototype()
    saved = replace(saved, base=replace(saved.base, fields={**saved.base.fields, offset: bad}))
    with pytest.raises(ReplayMasterCommonError, match="invalid saved"):
        restore_replay_master_common(saved, {0: baseline})


def test_inconsistent_saved_alias_and_missing_saved_scalar_fail_without_mutation() -> None:
    saved, baseline = _prototype()
    with pytest.raises(ReplayMasterCommonError, match="selector disagrees"):
        restore_replay_master_common(
            replace(saved, base=replace(saved.base, baseline_id=1)), {1: baseline}
        )
    fields = dict(saved.base.fields)
    del fields[0x128]
    broken = replace(saved, base=replace(saved.base, fields=fields))
    before = copy.deepcopy(broken)
    with pytest.raises(ReplayMasterCommonError, match="missing saved"):
        restore_replay_master_common(broken, {0: baseline})
    assert broken == before


def test_saved_overrides_and_unrelated_dat_values_are_not_blanket_merged() -> None:
    saved, baseline = _prototype()
    baseline = replace(
        baseline,
        common=replace(
            baseline.common,
            fields={
                **baseline.common.fields,
                0x68: 7,
                0x78: 0x7FC12345,
                0xAA: 5,
                0xB0: 0xFFFFFFFF,
                0x128: 0x7F800000,
                0x777: 123,
            },
        ),
    )
    result = restore_replay_master_common(saved, {0: baseline})
    assert all(result.fields[o] == saved.base.fields[o] for o in (0x68, 0x78, 0xAA, 0xB0, 0x128))
    assert 0x777 not in result.fields
    assert result.saved.attributes is saved.base.attributes
    original = saved.base.fields[0x78]
    result.fields[0x78] ^= 0xFFFFFFFF
    assert saved.base.fields[0x78] == original
    assert baseline.common.fields[0x78] == 0x7FC12345


@pytest.mark.parametrize("kind", [10, 15, 20, 25, 30, 40, 50, 60, 70, 80])
def test_composition_adds_only_family_applicable_components(kind: int) -> None:
    saved, baseline = _prototype()
    saved = replace(saved, type_group=kind, base=replace(saved.base, type_group=kind))
    result = restore_replay_master_components(saved, {0: baseline}, graphics={})
    assert result.saved is saved and result.common.saved is saved.base
    assert (result.movement is not None) == (kind >= 30)
    assert (result.tasks is not None) == (kind >= 40)
    assert (result.combat is not None) == (kind >= 50)
    assert (result.unit is not None) == (kind >= 70)
    assert result.baseline_index == 0
    if result.movement is not None:
        assert result.movement.baseline_index == result.baseline_index
    if result.tasks is not None:
        assert result.tasks.baseline_index == result.baseline_index
    for component in (result.combat, result.unit):
        if component is not None:
            assert component.baseline_index == result.baseline_index
            assert component.baseline is baseline


@pytest.mark.parametrize("kind", [9, 31, 90, True, 30.0])
def test_unsupported_or_untyped_saved_family_is_rejected(kind: Any) -> None:
    saved, baseline = _prototype()
    saved = replace(saved, type_group=kind, base=replace(saved.base, type_group=kind))
    with pytest.raises(ReplayMasterCommonError, match="saved master family"):
        restore_replay_master_components(saved, {0: baseline}, graphics={})


def test_inconsistent_base_family_is_rejected() -> None:
    saved, baseline = _prototype()
    with pytest.raises(ReplayMasterCommonError, match="inconsistent"):
        restore_replay_master_common(
            replace(saved, base=replace(saved.base, type_group=10)), {0: baseline}
        )


def test_composition_requires_explicit_graphic_context_and_action_compatible_source() -> None:
    saved, baseline = _prototype()
    with pytest.raises(ReplayMasterCommonError, match="explicit graphics"):
        restore_replay_master_components(saved, {0: baseline})
    low_family = replace(baseline, type_group=10)
    assert restore_replay_master_common(saved, {0: low_family}).baseline is low_family
    with pytest.raises(ReplayMasterTasksError, match="missing action baseline"):
        restore_replay_master_components(saved, {0: low_family}, graphics={})


class _SameTable(Mapping[int, GameDataMaster | None]):
    def __init__(self, index: int, baseline: GameDataMaster):
        self.values = {index: baseline, 333: None}
        self.reads: list[int] = []

    def __getitem__(self, index: int) -> GameDataMaster | None:
        self.reads.append(index)
        return self.values[index]

    def __len__(self) -> int:
        return len(self.values)

    def __iter__(self) -> Iterator[int]:
        raise AssertionError("composition must use the selected table without copying it")


def test_same_selected_table_drives_all_components_and_matches_existing_ports() -> None:
    saved, baseline = _prototype()
    saved = replace(
        saved, base=replace(saved.base, baseline_id=768, fields={**saved.base.fields, 0x20: 768})
    )
    graphics = {
        baseline.fields[0x1E8]: GameDataGraphic(0, 0, (b"", b"", b""), {0xA: 16}, 0, (), (), b"")
    }
    table = _SameTable(420, baseline)
    result = restore_replay_master_components(saved, table, graphics=graphics)
    assert result.baseline_index == 420 and len(table.reads) >= 4
    assert set(table.reads) == {420}
    assert result.common.baseline is baseline
    assert result.movement == restore_replay_master_movement(saved, {420: baseline}, graphics)
    assert result.tasks == restore_replay_master_tasks(saved, {420: baseline})
    assert result.combat == restore_replay_master_combat(saved, {420: baseline})
    assert result.unit == restore_replay_master_unit(saved, {420: baseline})


def test_mismatched_component_source_index_is_explicitly_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    saved, baseline = _prototype()
    original = restore_replay_master_movement(saved, {0: baseline}, {})
    monkeypatch.setattr(
        module,
        "restore_replay_master_movement",
        lambda *_args, **_kwargs: replace(original, baseline_index=1),
    )
    with pytest.raises(ReplayMasterCommonError, match="indices disagree"):
        restore_replay_master_components(saved, {0: baseline}, graphics={})


@pytest.mark.parametrize("name", ["restore_replay_master_combat", "restore_replay_master_unit"])
def test_new_numeric_components_reject_mismatched_indices(
    name: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    saved, baseline = _prototype()
    original = getattr(module, name)(saved, {0: baseline})
    monkeypatch.setattr(module, name, lambda *_args, **_kwargs: replace(original, baseline_index=1))
    with pytest.raises(ReplayMasterCommonError, match="indices disagree"):
        restore_replay_master_components(saved, {0: baseline}, graphics={})


def test_existing_four_positional_component_constructor_keeps_optional_defaults() -> None:
    saved, baseline = _prototype()
    common = restore_replay_master_common(saved, {0: baseline})
    result = module.ReplayMasterComponents(saved, common, None, None)
    assert result.combat is None and result.unit is None
