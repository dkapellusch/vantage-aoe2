"""Full original Moving30 reader oracle and saved PIG restoration regression."""

from __future__ import annotations

import gzip
import hashlib
import json
from dataclasses import replace
from functools import lru_cache
from pathlib import Path

import pytest

from vantage.replay_binary import SaveReader
from vantage.replay_game_data import (
    GameDataGraphic,
    GameDataMaster,
    GameDataMasterCommon,
    read_game_data_master,
)
from vantage.replay_master_movement import (
    ReplayMasterMovementError,
    restore_replay_master_movement,
    restore_replay_moving_turn_fields,
)
from vantage.replay_masters import SavedMaster, read_master

PATH = Path(__file__).parent / "fixtures/native_saved_moving_master_54800.json.gz"
OFFSETS = (0x20C, 0x210, 0x214, 0x218, 0x21C)
DEFAULTS = [0, 0x7F7FFFFF, 0x7F7FFFFF, 0, 0x7F7FFFFF]


@lru_cache(maxsize=1)
def _fixture() -> dict:
    return json.loads(gzip.decompress(PATH.read_bytes()))


@lru_cache(maxsize=1)
def _saved() -> SavedMaster:
    sample = _fixture()["saved_sample"]
    raw = bytes.fromhex(sample["raw_hex"])
    assert hashlib.sha256(raw).hexdigest() == sample["raw_sha256"]
    reader = SaveReader(raw)
    saved = read_master(reader, master_id=sample["master_id"], type_group=sample["type_group"])
    assert reader.pos == len(raw)
    return saved


def _baseline(kind: int = 70, sprite: int = 4, poison: int = 0x7FC12345) -> GameDataMaster:
    common = GameDataMasterCommon(0, 0, {}, 0, b"", (), (), {}, {}, b"", {}, b"")
    return GameDataMaster(
        0,
        0,
        kind,
        common,
        {0x1E8: sprite, **dict.fromkeys(OFFSETS, poison)},
        {},
        {},
        {},
        (),
        (),
        {},
        (),
        (),
        (),
        {},
        b"",
    )


def _graphic(facets: int = 16) -> GameDataGraphic:
    return GameDataGraphic(0, 0, (b"", b"", b""), {0xA: facets}, 0, (), (), b"")


def _signed(word: int) -> int:
    return word if word < 0x8000 else word - 0x10000


def _profile(rotation: int = 0x3F800000, first: int = 2, second: int = -1) -> SavedMaster:
    return replace(
        _saved(),
        base=replace(_saved().base, baseline_id=0),
        fields={**_saved().fields, 0x1F8: rotation, 0x1E8: first, 0x1F0: second},
    )


def test_original_full_reader_all_7408_cases_and_read_order() -> None:
    report = _fixture()
    assert len(report["cases"]) == 7408
    assert report["retained_evidence"] == [
        "ev_1546b8dc9b1814ec0974ffeebdc4d760012ed19944811a3dde112dfae447acce"
    ]
    assert report["original_reader_instructions_changed"] is False
    assert report["original_imports_executed"] is False
    assert "1411768c0" in report["controlled_dependencies"]
    prototype = _profile()
    for index, (row, output) in enumerate(report["cases"]):
        (
            kind,
            sprite,
            facets,
            rotation,
            first,
            second,
            trail,
            pathing,
            spacing,
            size,
            algo,
            poison,
        ) = row
        fields = {
            **prototype.fields,
            0x1F8: rotation,
            0x1E8: _signed(first),
            0x1F0: _signed(second),
            0x1FE: _signed(trail),
            0x200: pathing,
            0x204: spacing,
            0x1FC: size,
            0x208: algo,
            0x220: 0x3F000000,
        }
        baseline = _baseline(kind, 4 if sprite else -1, poison ^ 0xFFFFFFFF) if kind else None
        graphics = {0: _graphic(1), 2: _graphic(7), 4: _graphic(facets)}
        restored = restore_replay_master_movement(
            replace(prototype, fields=fields), {0: baseline}, graphics
        )
        actual = [
            rotation,
            *(restored.fields[o] for o in OFFSETS),
            *(sid if sid is not None else -1 for sid in restored.sprite_ids),
            restored.fields[0x1FE] & 0xFFFF,
            *(restored.fields[o] for o in (0x200, 0x204, 0x1FC, 0x208, 0x220)),
        ]
        assert actual == output[:14], (index, row)
        snapshot = [output[14 + i * 8 : 22 + i * 8] for i in range(9)]
        assert [s[0] for s in snapshot] == [4, 2, 2, 2, 1, 4, 1, 1, 4]
        assert snapshot[0][2:7] == DEFAULTS
        # The second read still sees the baseline sprite, with its turn caches already calculated.
        assert snapshot[1][2:7] == actual[1:6]
        assert snapshot[1][7] == int(kind >= 30 and sprite != 0)
        pure = restore_replay_moving_turn_fields(
            rotation,
            _signed(facets) if kind >= 30 and sprite else None,
        )
        assert [pure[o] for o in OFFSETS] == actual[1:6]


def test_real_first_pig_turn_words_are_reset_not_inherited() -> None:
    saved = _saved()
    assert saved.master_id == 1245 and saved.type_group == 70 and saved.fields[0x1F8] == 0
    baseline = _baseline(sprite=10418)
    restored = restore_replay_master_movement(
        saved,
        {saved.base.baseline_id: baseline},
        {10418: _graphic()},
    )
    assert [restored.fields[o] for o in OFFSETS] == DEFAULTS
    assert restored.sprite_ids == (10418, None)
    assert all(baseline.fields[o] == 0x7FC12345 for o in OFFSETS)
    assert all(o not in saved.fields for o in OFFSETS)


def test_rotation_uses_baseline_sprite_before_saved_replacement() -> None:
    saved = _profile()
    result = restore_replay_master_movement(
        saved, {0: _baseline()}, {4: _graphic(16), 2: _graphic(1)}
    )
    assert result.baseline_sprite_id == 4 and result.sprite_ids == (2, None)
    assert [result.fields[o] for o in OFFSETS] == [
        0,
        0x7F7FFFFF,
        0x3EC90FDB,
        0x41800000,
        0x3EC90FDB,
    ]


def test_clearing_final_sprite_does_not_clear_earlier_cache() -> None:
    result = restore_replay_master_movement(_profile(first=-1), {0: _baseline()}, {4: _graphic(16)})
    assert result.sprite_ids == (None, None) and result.fields[0x218] == 0x41800000


@pytest.mark.parametrize("baseline", [None, _baseline(kind=29), _baseline(sprite=-1)])
def test_absent_or_incompatible_baseline_does_not_use_final_sprite(
    baseline: GameDataMaster | None,
) -> None:
    result = restore_replay_master_movement(_profile(), {0: baseline}, {2: _graphic(16)})
    assert result.sprite_ids == (2, None) and result.baseline_sprite_id is None
    assert [result.fields[o] for o in OFFSETS] == DEFAULTS


@pytest.mark.parametrize("raw,index", [(768, 420), (770, 691), (1245, 1245)])
def test_baseline_selector_remap_leaves_saved_definition_unchanged(raw: int, index: int) -> None:
    saved = replace(_profile(), base=replace(_saved().base, baseline_id=raw))
    result = restore_replay_master_movement(saved, {index: _baseline()}, {4: _graphic(16)})
    assert result.baseline_index == index and saved.base.baseline_id == raw


@pytest.mark.parametrize("rotation", [0, 0x80000000])
def test_ordered_zero_rotation_does_not_need_sprite_facet_field(rotation: int) -> None:
    graphic = replace(_graphic(), fields={})
    result = restore_replay_master_movement(_profile(rotation), {0: _baseline()}, {4: graphic})
    assert [result.fields[o] for o in OFFSETS] == DEFAULTS


def test_zero_product_preserves_its_sign_but_uses_max_sentinel() -> None:
    fields = restore_replay_moving_turn_fields(0xBF800000, 0)
    assert fields[0x218] == 0x80000000
    assert fields[0x214] == fields[0x21C] == 0x7F7FFFFF


def test_restored_fields_are_independent_of_saved_and_baseline_dicts() -> None:
    saved, baseline = _profile(), _baseline()
    result = restore_replay_master_movement(saved, {0: baseline}, {4: _graphic()})
    result.fields[0x1F8] = result.fields[0x20C] = 123
    assert saved.fields[0x1F8] == 0x3F800000 and baseline.fields[0x20C] == 0x7FC12345


@pytest.mark.parametrize("kind", [10, 15, 20, 25, 99])
def test_nonmoving_saved_type_rejected(kind: int) -> None:
    with pytest.raises(ReplayMasterMovementError, match="moving component"):
        restore_replay_master_movement(replace(_profile(), type_group=kind), {}, {})


@pytest.mark.parametrize("selector", [-1, -32768, 32768])
def test_unsafe_baseline_selectors_rejected(selector: int) -> None:
    saved = replace(_profile(), base=replace(_saved().base, baseline_id=selector))
    with pytest.raises(ReplayMasterMovementError, match="selector"):
        restore_replay_master_movement(saved, {selector: None}, {})


def test_omitted_baseline_slot_is_incomplete_not_an_explicit_null() -> None:
    with pytest.raises(ReplayMasterMovementError, match="missing baseline slot"):
        restore_replay_master_movement(_profile(), {}, {})


@pytest.mark.parametrize(
    "offset,value",
    [(0x1F8, -1), (0x220, 0x100000000), (0x1FC, 256), (0x1FE, 32768), (0x1E8, -32769)],
)
def test_invalid_saved_fields_rejected(offset: int, value: int) -> None:
    saved = replace(_profile(), fields={**_profile().fields, offset: value})
    with pytest.raises(ReplayMasterMovementError):
        restore_replay_master_movement(saved, {0: _baseline()}, {4: _graphic()})


def test_missing_saved_field_rejected() -> None:
    fields = dict(_profile().fields)
    del fields[0x208]
    with pytest.raises(ReplayMasterMovementError, match="missing moving"):
        restore_replay_master_movement(replace(_profile(), fields=fields), {0: None}, {})


@pytest.mark.parametrize("facets", [-32769, 32768, 1.0])
def test_invalid_signed_facet_input_rejected(facets: int) -> None:
    with pytest.raises(ReplayMasterMovementError, match="facets"):
        restore_replay_moving_turn_fields(0, facets)


def test_invalid_graphic_facet_word_rejected_when_it_is_read() -> None:
    with pytest.raises(ReplayMasterMovementError, match="member0xa"):
        restore_replay_master_movement(_profile(), {0: _baseline()}, {4: _graphic(0x10000)})


@pytest.mark.parametrize("word,signed", [(0xFFFF, -1), (0x8000, -32768), (0x8001, -32767)])
def test_baseline_raw_u16_graphic_word_uses_native_signed_negative_null_branch(
    word: int, signed: int
) -> None:
    # Both raw/signed keys deliberately contain sprites: negative IDs must not
    # look them up. Native DAT MOVSX1411ab206/TEST+JS1411ab20f..212 proves this.
    graphics = {word: _graphic(), signed: _graphic()}
    raw_baseline = _baseline(sprite=word)
    actual = restore_replay_master_movement(_profile(), {0: raw_baseline}, graphics)
    logical = restore_replay_master_movement(_profile(), {0: _baseline(sprite=signed)}, graphics)
    assert actual == logical and actual.baseline_sprite_id is None
    assert [actual.fields[o] for o in OFFSETS] == DEFAULTS
    assert raw_baseline.fields[0x1E8] == word


def test_largest_positive_baseline_graphic_id_is_not_mistaken_for_null() -> None:
    result = restore_replay_master_movement(
        _profile(), {0: _baseline(sprite=0x7FFF)}, {0x7FFF: _graphic(16)}
    )
    assert result.baseline_sprite_id == 0x7FFF and result.fields[0x218] == 0x41800000


@pytest.mark.parametrize("value", [-32769, 65536])
def test_baseline_graphic_value_outside_signed_or_raw_word_range_fails(value: int) -> None:
    with pytest.raises(ReplayMasterMovementError, match="member0x1e8"):
        restore_replay_master_movement(_profile(), {0: _baseline(sprite=value)}, {})


def test_real_dat_raw_ffff_baseline_sprite_composes_without_rewriting_its_table() -> None:
    fixture_path = Path(__file__).parent / "fixtures/native_saved_common_master_54800.json.gz"
    case = json.loads(gzip.decompress(fixture_path.read_bytes()))["cases"][0]
    reader = SaveReader(bytes.fromhex(case["baseline_hex"]), version=0x43E666)
    baseline = read_game_data_master(reader)
    assert reader.remaining == 0 and baseline.fields[0x1E8] == 0xFFFF
    assert baseline.sprite_id_bits[0x1E8] == 0xFFFF
    reader = SaveReader(bytes.fromhex(case["saved_hex"]))
    saved = read_master(reader, master_id=case["master_id"], type_group=case["saved_type"])
    assert reader.remaining == 0
    result = restore_replay_master_movement(
        saved, {case["baseline_index"]: baseline}, {0xFFFF: _graphic(16)}
    )
    assert result.baseline_sprite_id is None and baseline.fields[0x1E8] == 0xFFFF
