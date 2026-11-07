"""Original resource-check/charge oracle and observable production boundaries."""

from __future__ import annotations

import gzip
import json
from dataclasses import replace
from functools import lru_cache
from pathlib import Path

import pytest

from vantage.replay_binary import SaveReader
from vantage.replay_masters import SavedMaster, read_master_table
from vantage.replay_production_resources import (
    ReplayProductionMaster,
    ReplayResourceCheck,
    ReplayUnitCost,
    charge_replay_unit_resources,
    check_replay_unit_resources,
    restore_replay_production_master,
)

_ZERO = ReplayUnitCost(-1, 0, 0)


@lru_cache(maxsize=1)
def _saved_masters() -> dict[int, SavedMaster]:
    fixture = Path(__file__).parent / "fixtures/native_saved_master_tables_54800.json.gz"
    data = json.loads(gzip.decompress(fixture.read_bytes()))
    raw = bytes.fromhex(data["table_blobs_by_sha256"][data["samples"][0]["raw_sha256"]])
    return read_master_table(SaveReader(raw)).masters


def _master(*costs: ReplayUnitCost, **kwargs: int) -> ReplayProductionMaster:
    padded = (*costs, *([_ZERO] * (3 - len(costs))))
    return ReplayProductionMaster(
        kwargs.get("type_group", 70),
        (padded[0], padded[1], padded[2]),
        kwargs.get("annex_id", -1),
        kwargs.get("head_id", -1),
    )


def _four(row: list[int], offset: int) -> tuple[int, int, int, int]:
    return row[offset], row[offset + 1], row[offset + 2], row[offset + 3]


@pytest.mark.parametrize("operation", (0, 1))
def test_complete_original_native_resource_bodies(operation: int) -> None:
    path = Path(__file__).parent / "fixtures/native_replay_production_resources_54800.json.gz"
    data = json.loads(gzip.decompress(path.read_bytes()))
    checked = 0
    for row, expected in data["rows"]:
        if row[0] != operation:
            continue
        masters: list[ReplayProductionMaster | None] = []
        for index in range(3):
            raw = row[6 + 13 * index : 6 + 13 * (index + 1)]
            masters.append(
                _master(
                    *(ReplayUnitCost(*raw[i : i + 3]) for i in (4, 7, 10)),
                    type_group=raw[1],
                    annex_id=raw[2],
                    head_id=raw[3],
                )
                if raw[0]
                else None
            )
        resources = [0x42550000 + i for i in range(576)]
        for resource_id, word in zip(data["resource_ids"], row[45:54], strict=True):
            resources[resource_id] = word
        before = tuple(resources)
        if operation == 0:
            check = check_replay_unit_resources(
                masters,
                row[1],
                resources,
                row[2],
                skip_population=bool(row[3]),
                reserve_a=_four(row, 54) if row[4] else None,
                reserve_b=_four(row, 58) if row[5] else None,
            )
            result = [int(check.affordable), check.missing_resource & 0xFFFF]
            after = before
        else:
            charge = charge_replay_unit_resources(
                masters, row[1], resources, row[2], skip_population=bool(row[3])
            )
            result = [int(charge.accepted), 0xFFFF]
            after = charge.resources
        result.extend(after[resource_id] for resource_id in data["resource_ids"])
        assert result == expected, row
        assert resources == list(before)
        touched = set(data["resource_ids"])
        assert all(
            a == b for i, (a, b) in enumerate(zip(before, after, strict=True)) if i not in touched
        )
        checked += 1
    assert checked == 8552


def test_duplicate_slots_check_separately_and_charge_sequentially() -> None:
    masters = [_master(ReplayUnitCost(0, 50, 1), ReplayUnitCost(0, 50, 1))]
    resources = (0x42480000,)  # 50
    assert check_replay_unit_resources(masters, 0, resources, 0x3F800000).affordable
    charged = charge_replay_unit_resources(masters, 0, resources, 0x3F800000)
    assert charged.accepted
    assert charged.resources == (0xC2480000,)  # -50


def test_inactive_normal_cost_still_blocks_but_is_not_deducted() -> None:
    masters = [_master(ReplayUnitCost(0, 50, 0))]
    assert check_replay_unit_resources(masters, 0, (0,), 0x3F800000) == ReplayResourceCheck(
        False, 0
    )
    result = charge_replay_unit_resources(masters, 0, (0x42480000,), 0x3F800000)
    assert result.accepted and result.resources == (0x42480000,)


def test_annex_is_cost_source_even_without_resolving_its_head() -> None:
    masters = [
        _master(ReplayUnitCost(0, 100, 1), type_group=80, annex_id=1),
        _master(ReplayUnitCost(1, 50, 0)),
    ]
    assert check_replay_unit_resources(masters, 0, (0x43480000, 0), 0x3F800000) == (
        ReplayResourceCheck(False, 1)
    )


def test_both_links_enable_flag_filter_but_charge_uses_requested_master() -> None:
    masters = [
        _master(ReplayUnitCost(0, 100, 1), type_group=80, annex_id=1),
        _master(head_id=2),
        _master(ReplayUnitCost(1, 100, 0)),
    ]
    result = charge_replay_unit_resources(masters, 0, (0x42480000, 0), 0x3F800000)
    assert result.accepted and result.resources == (0xC2480000, 0)


def test_special_resource571_skips_check_but_active_cost_is_charged() -> None:
    masters = [_master(ReplayUnitCost(571, 50, 1))]
    resources = (0,) * 572
    result = charge_replay_unit_resources(masters, 0, resources, 0x3F800000)
    assert result.accepted and result.resources == (*resources[:-1], 0xC2480000)


@pytest.mark.parametrize("master_id", (-32768, -1, 1, 32767))
def test_missing_requested_master_rejects_without_mutation(master_id: int) -> None:
    resources = (0x7F801234, 0x80000000)
    result = charge_replay_unit_resources([None], master_id, resources, 0x3F800000)
    assert not result.accepted and result.resources == resources


@pytest.mark.parametrize("kind", (0, 10, 60, 69))
def test_nonproduction_master_type_rejects(kind: int) -> None:
    assert check_replay_unit_resources([_master(type_group=kind)], 0, (), 0x3F800000) == (
        ReplayResourceCheck(False, -1)
    )


def test_reservations_subtract_in_order_only_for_first_four_resources() -> None:
    masters = [_master(ReplayUnitCost(0, 50, 1))]
    assert check_replay_unit_resources(masters, 0, (0x42C80000,), 0x3F800000).affordable
    assert check_replay_unit_resources(
        masters,
        0,
        (0x42C80000,),
        0x3F800000,
        reserve_a=(0x42480000, 0, 0, 0),
        reserve_b=(0x3F800000, 0, 0, 0),
    ) == ReplayResourceCheck(False, 0)


@pytest.mark.parametrize(
    ("provided", "maximum", "reserved", "expected"),
    ((10.0, 20.0, 0.0, -1), (0.0, 20.0, 0.0, 4), (10.0, 5.0, 0.0, 32), (10.0, 20.0, 10.0, 4)),
)
def test_population_capacity_maximum_and_queued_reservation(
    provided: float, maximum: float, reserved: float, expected: int
) -> None:
    import struct

    resources = [0] * 81
    for index, value in ((4, provided), (11, 5.0), (32, maximum), (80, reserved)):
        resources[index] = int.from_bytes(struct.pack("<f", value), "little")
    masters = [_master(ReplayUnitCost(4, 1, 0))]
    result = check_replay_unit_resources(masters, 0, resources, 0x3F800000)
    assert result == ReplayResourceCheck(expected == -1, expected)
    assert check_replay_unit_resources(
        masters, 0, resources, 0x3F800000, skip_population=True
    ).affordable


def test_unordered_population_accepts_native_jbe_branch() -> None:
    masters = [_master(ReplayUnitCost(4, 1, 0))]
    resources = [0] * 81
    resources[32] = 0x7FC01234
    assert check_replay_unit_resources(masters, 0, resources, 0x3F800000).affordable


def test_out_of_bounds_link_and_missing_resource_fail_explicitly() -> None:
    with pytest.raises(ValueError, match="linked master reference"):
        check_replay_unit_resources([_master(type_group=80, annex_id=2)], 0, (), 0x3F800000)
    with pytest.raises(ValueError, match="resource 1 is absent"):
        check_replay_unit_resources([_master(ReplayUnitCost(1, 50, 0))], 0, (), 0x3F800000)


@pytest.mark.parametrize(
    ("resource", "cost", "flag"), ((32768, 0, 0), (-32769, 0, 0), (0, 32768, 0), (0, 0, 256))
)
def test_invalid_native_cost_inputs_raise(resource: int, cost: int, flag: int) -> None:
    with pytest.raises(ValueError):
        ReplayUnitCost(resource, cost, flag)


@pytest.mark.parametrize("master_id", (83, 293, 109))
def test_saved_costs_supply_unit_resource_transition(master_id: int) -> None:
    saved = _saved_masters()[master_id]
    master = restore_replay_production_master(saved)
    assert master.type_group == saved.type_group
    assert tuple((c.resource_id, c.amount, c.enabled) for c in master.costs) == (
        tuple(row[:3] for row in saved.vectors[0x320])
    )
    if saved.type_group == 80:
        assert (master.annex_id, master.head_id) == (saved.fields[0x458], saved.fields[0x426])
    else:
        assert master.costs == (ReplayUnitCost(0, 50, 1), _ZERO, ReplayUnitCost(4, 1, 0))
        result = charge_replay_unit_resources([master], 0, (0x42C80000,), 0x3F800000)
        assert result.accepted and result.resources == (0x42480000,)


def test_restoration_uses_final_costs_and_rejects_missing_fields() -> None:
    saved = _saved_masters()[83]
    modified = replace(saved, fields={**saved.fields, 0x322: 51})
    assert restore_replay_production_master(modified).costs[0].amount == 51
    incomplete = dict(saved.fields)
    del incomplete[0x322]
    with pytest.raises(ValueError, match="saved production member 0x322 is missing"):
        restore_replay_production_master(replace(saved, fields=incomplete))
    with pytest.raises(ValueError, match="no supported unit-production cost"):
        restore_replay_production_master(replace(saved, type_group=50))
