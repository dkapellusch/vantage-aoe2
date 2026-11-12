"""Installed-build regression cases plus effect semantics without a game install."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from vantage.gamedata import GameData
from vantage.upgrades import CONVERTER_TECHS, relevance


@pytest.fixture
def game() -> GameData:
    raw = json.loads((Path(__file__).parent / "fixtures/upgrade-effects-57257.json").read_text())
    data = GameData(None)
    data._upgrade_facts = raw["facts"]
    data._all_trees = {int(c): nodes for c, nodes in raw["trees"].items()}
    data.unique_tech_ids = {int(c): techs for c, techs in raw["unique"].items()}
    data._lang_strings = {"en": {int(k): v for k, v in raw["strings"].items()}}
    return data


def test_monk_gets_all_obtainable_monastery_overrides(game: GameData) -> None:
    assert set(game.relevant_upgrades(15)["125"]) == set(CONVERTER_TECHS)


def test_longbowman_nine_effect_upgrades_plus_explicit_faith(game: GameData) -> None:
    assert game.relevant_upgrades(1)["8"] == [360, 199, 200, 201, 211, 212, 219, 45, 47, 3]
    assert 439 not in game.relevant_upgrades(1)["8"]  # Britons lack Heresy.


def test_elite_mangudai_armor_is_gated_by_mongol_availability(game: GameData) -> None:
    upgrades = game.relevant_upgrades(12)["561"]
    assert upgrades[0] == 371  # Keep the whole line, including the elite upgrade.
    assert {211, 212, 435, 39, 436, 437, 45, 439} <= set(upgrades)
    assert 219 not in upgrades  # Class matches, but Mongols lack Ring Archer Armor.


def test_shared_knight_only_gets_its_owners_unique_technology(game: GameData) -> None:
    malians = game.relevant_upgrades(26)["38"]
    sicilians = game.relevant_upgrades(37)["38"]
    assert malians[-1] == 577 and 757 not in malians  # Farimba, not Hauberk.
    assert sicilians[-1] == 757 and 577 not in sicilians


def test_watch_tower_line_blacksmith_and_other_upgrades(game: GameData) -> None:
    ids = game.relevant_upgrades(1)["79"]
    assert ids[:5] == [140, 63, 199, 200, 201]  # Guard Tower, Keep, ranged attack.
    assert {50, 51, 322, 380, 47, 608, 3} <= set(ids)
    assert 8 not in ids and 280 not in ids  # Not a Town Center.
    assert 825 not in ids  # Other civ's tower UT cannot leak into Britons.


def test_town_center_variants_and_fortified_church_share_no_layout_inference(
    game: GameData,
) -> None:
    assert {8, 280, 101, 102, 103, 50, 51} <= set(game.relevant_upgrades(1)["109"])
    assert set(game.relevant_upgrades(1)["621"]) == {8, 280, 101, 102, 103, 50, 51}
    # What a church researches is not an effect on that building. Its class is
    # also 3, but that does not make it a Town Center for LOS-only research.
    assert set(game.relevant_upgrades(44)["1806"]) == {50, 322, 380}
    assert set(game.relevant_upgrades(45)["1806"]) == {50, 51, 322}
    assert not set(CONVERTER_TECHS) & set(game.relevant_upgrades(44)["1806"])


def test_class_effects_counter_effects_team_variants_and_neutral_commands() -> None:
    effects = [
        [[4, -1, 6, 0, 10], [4, 10, -1, 0, -10]],  # exact cancellation
        [[14, -1, 6, 5, 0.1]],  # team speed effect
        [[5, 10, -1, 10, 1]],  # neutral reload multiplier
        [[4, 10, -1, 104, -20]],  # cost-only, excluded
        [[4, 10, -1, 1, 3], [4, 10, -1, 104, -20]],  # LOS is main attribute
        [[4, 10, -1, 1, 3], [4, 11, -1, 8, 257]],  # incidental LOS
        [[4, -1, 6, 8, 770], [4, 10, -1, 8, -770]],  # packed armor cancellation
        [[4, 10, -1, 101, -5]],  # train time
    ]
    facts = {
        "techs": [{"effect": i, "civ": -1, "required": []} for i in range(8)],
        "effects": effects,
        "units": [{"10": {"class": 6, "type": 70, "converter": False, "attack": True}}],
    }
    result, _, _ = relevance(facts, 0, set(range(8)), set(), {}, set())
    assert set(result["10"]) == {1, 4, 7}


def test_missing_effect_data_has_no_layout_fallback() -> None:
    assert GameData(None).relevant_upgrades(1) == {}


def test_unique_classification_cannot_reenable_a_disabled_civ_technology(game: GameData) -> None:
    game._all_trees[15]["tech:45"]["Node Status"] = "NotAvailable"
    game.unique_tech_ids[15]["castle"].append(45)
    assert 45 not in game.relevant_upgrades(15)["125"]


def test_healing_only_warrior_priest_is_not_given_conversion_overrides(game: GameData) -> None:
    ids = set(game.relevant_upgrades(44)["1811"])
    assert {231, 252} <= ids  # Actual unit-targeted Sanctity/Fervor effects.
    assert not {316, 319, 230, 438} & ids  # No conversion task on this unit.


def test_effect_cache_uses_dat_content_and_survives_a_new_instance(tmp_path, monkeypatch) -> None:
    import vantage.upgrades as upgrades

    path = tmp_path / "empires2_x2_p1.dat"
    path.write_bytes(b"installed version one")
    calls = []

    def read(name):
        calls.append(name)
        return {"marker": Path(name).read_text()}

    monkeypatch.setattr(upgrades, "read_effects", read)
    monkeypatch.setattr(GameData, "dat_path", lambda *_: path)
    one = GameData(None, cache_dir=tmp_path / "cache")._upgrade_facts
    two = GameData(None, cache_dir=tmp_path / "cache")._upgrade_facts
    assert one == two and len(calls) == 1
    path.write_bytes(b"installed version two")
    three = GameData(None, cache_dir=tmp_path / "cache")._upgrade_facts
    assert three != one and len(calls) == 2


def test_unsupported_dat_returns_unavailable_without_layout_guesses(tmp_path, monkeypatch) -> None:
    import vantage.upgrades as upgrades

    path = tmp_path / "empires2_x2_p1.dat"
    path.write_bytes(b"unsupported")

    def read(_):
        raise ValueError("Unsupported dat version")

    monkeypatch.setattr(upgrades, "read_effects", read)
    monkeypatch.setattr(GameData, "dat_path", lambda *_: path)
    game = GameData(None, cache_dir=tmp_path / "cache")
    assert game._upgrade_facts is None
    assert game.relevant_upgrades(15) == {}
