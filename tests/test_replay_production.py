"""Original queue-entry phase stopped immediately after population reservation."""

from __future__ import annotations

import gzip
import json
from pathlib import Path

import pytest

from vantage.replay_population import ReplayPopulationAttribute, ReplayPopulationMaster
from vantage.replay_production import charge_replay_production_selection
from vantage.replay_production_resources import ReplayProductionMaster, ReplayUnitCost


def _costs() -> list[ReplayProductionMaster | None]:
    master = ReplayProductionMaster(
        70, (ReplayUnitCost(0, 50, 1), ReplayUnitCost(-1, 0, 0), ReplayUnitCost(-1, 0, 0))
    )
    return [master] * 4


def _population(word: int = 0xBF800000) -> list[ReplayPopulationMaster | None]:
    master = ReplayPopulationMaster(
        70,
        (
            ReplayPopulationAttribute(4, word),
            ReplayPopulationAttribute(-1, 0),
            ReplayPopulationAttribute(-1, 0),
        ),
    )
    return [master] * 4


def test_original_queue_charge_and_reservation_phase() -> None:
    path = Path(__file__).parent / "fixtures/native_replay_production_phase_54800.json.gz"
    data = json.loads(gzip.decompress(path.read_bytes()))
    assert len(data["rows"]) == 2250
    accepted = 0
    for row, expected in data["rows"]:
        requested, queued, food, demand, reserved = row
        resources = [0x42550000 + i for i in range(576)]
        resources[0], resources[80] = food, reserved
        before = tuple(resources)
        result = charge_replay_production_selection(
            _costs(), _population(demand), 1, requested, queued, resources
        )
        assert bool(result.accepted_quantity) == bool(expected[0]), row
        assert [result.accepted_quantity, result.resources[0], result.resources[80]] == expected[
            1:4
        ], row
        assert expected[4] == (1 if expected[0] else 2) and expected[5] == 1
        assert all(
            a == b
            for i, (a, b) in enumerate(zip(before, result.resources, strict=True))
            if i not in (0, 80)
        )
        assert tuple(resources) == before
        accepted += int(bool(result.accepted_quantity))
    assert accepted == 1575


def test_affordability_retries_before_reserving_only_accepted_count() -> None:
    resources = [0] * 81
    resources[0] = 0x43020000  # 130 food; request5, accept2.
    result = charge_replay_production_selection(_costs(), _population(), 1, 5, 0, resources)
    assert result.accepted_quantity == 2
    assert (result.resources[0], result.resources[80]) == (0x41F00000, 0x40000000)


def test_full_capacity_retains_resources_without_master_dereference() -> None:
    resources = (0x7F801234, 0x80000000)
    result = charge_replay_production_selection([], [], 1, 5, 15, resources)
    assert result.accepted_quantity == 0 and result.resources == resources


def test_failed_charge_does_not_read_population_or_reservation_storage() -> None:
    result = charge_replay_production_selection(_costs(), [], 1, 5, 0, (0,))
    assert result.accepted_quantity == 0 and result.resources == (0,)


def test_successful_charge_requires_population_storage_without_input_mutation() -> None:
    resources = [0x43480000]
    with pytest.raises(ValueError, match="resource80"):
        charge_replay_production_selection(_costs(), _population(), 1, 1, 0, resources)
    assert resources == [0x43480000]


def test_successful_charge_requires_explicit_current_population_master() -> None:
    resources = [0] * 81
    resources[0] = 0x43480000
    with pytest.raises(ValueError, match="master index"):
        charge_replay_production_selection(_costs(), [], 1, 1, 0, resources)
    assert resources[0] == 0x43480000 and resources[80] == 0


@pytest.mark.parametrize("quantity", (-1, 0, 32768))
def test_unproved_quantity_range_fails(quantity: int) -> None:
    with pytest.raises(ValueError, match="quantity"):
        charge_replay_production_selection(_costs(), _population(), 1, quantity, 0, ())


@pytest.mark.parametrize("queued", (-1, 16))
def test_unproved_queue_count_fails(queued: int) -> None:
    with pytest.raises(ValueError, match="queued"):
        charge_replay_production_selection(_costs(), _population(), 1, 1, queued, ())
