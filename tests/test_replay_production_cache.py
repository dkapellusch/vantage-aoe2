"""Unchanged original cost/cache output and focused semantic regressions."""

from __future__ import annotations

import gzip
import json
from pathlib import Path

import pytest

from vantage.replay_production_cache import (
    ReplayProductionCacheSlot,
    ReplayUnitCostOutput,
    cache_replay_building_unit_costs,
    cache_replay_queue_unit_costs,
    calculate_replay_unit_costs,
)
from vantage.replay_production_resources import ReplayProductionMaster, ReplayUnitCost


def _master(
    *costs: tuple[int, int, int], kind: int = 70, annex: int = -1, head: int = -1
) -> ReplayProductionMaster:
    padded = [ReplayUnitCost(*cost) for cost in costs]
    padded.extend([ReplayUnitCost(-1, 0, 0)] * (3 - len(padded)))
    return ReplayProductionMaster(kind, (padded[0], padded[1], padded[2]), annex, head)


def _linked(*costs: tuple[int, int, int]) -> list[ReplayProductionMaster]:
    return [_master(*costs, kind=80, annex=1), _master(kind=80, head=2), _master(kind=80)]


@pytest.mark.parametrize("operation", (0, 1, 2))
def test_complete_original_native_cost_and_cache_bodies(operation: int) -> None:
    path = Path(__file__).parent / "fixtures/native_replay_production_cache_54800.json.gz"
    data = json.loads(gzip.decompress(path.read_bytes()))
    checked = unsupported = 0
    for row, expected in data["rows"]:
        if row[0] != operation:
            continue
        masters: list[ReplayProductionMaster | None] = []
        for index in range(3):
            raw = row[5 + 13 * index : 5 + 13 * (index + 1)]
            masters.append(
                _master(
                    *(tuple(raw[i : i + 3]) for i in (4, 7, 10)),
                    kind=raw[1],
                    annex=raw[2],
                    head=raw[3],
                )
                if raw[0]
                else None
            )
        resources = [0x42550000 + index for index in range(576)]
        for resource_id, word in zip(data["resource_ids"], row[44:53], strict=True):
            resources[resource_id] = word
        previous = (
            ReplayProductionCacheSlot(row[53], row[54]),
            ReplayProductionCacheSlot(row[55], row[56]),
            ReplayProductionCacheSlot(row[57], row[58]),
        )
        selected = ((row[1] + 32768) & 0xFFFF) - 32768
        sentinel = operation != 0 and row[1] == -1
        before = tuple(resources)
        if not sentinel and not 0 <= selected < len(masters):
            # Original oracle explicitly backs every negative/out-of-length
            # index with null memory. Portable API does not invent that storage.
            with pytest.raises(ValueError, match="backed master-table"):
                calculate_replay_unit_costs(masters, selected, resources, row[2])
            unsupported += 1
            continue
        if operation == 0:
            output = calculate_replay_unit_costs(masters, selected, resources, row[2])
            result = [
                word & 0xFFFFFFFF for slot in output for word in (slot.resource_id, slot.amount)
            ]
        else:
            cache = (
                cache_replay_building_unit_costs(masters, row[1], resources)
                if operation == 1
                else cache_replay_queue_unit_costs(masters, row[1], resources, previous)
            )
            result = [
                word & 0xFFFFFFFF for slot in cache for word in (slot.resource_id, slot.amount_bits)
            ]
        assert result == expected[1:], row
        assert tuple(resources) == before
        checked += 1
    assert checked == (1631, 1804, 1829)[operation]
    assert unsupported == (857, 684, 659)[operation]


def test_original_costs_survive_annex_selected_checker_and_inactive_flags() -> None:
    masters = _linked((0, 50, 0), (1, 60, 0), (-1, 0, 0))
    assert calculate_replay_unit_costs(masters, 0, [0x41200000] * 4) == (
        ReplayUnitCostOutput(0, 10),
        ReplayUnitCostOutput(1, 10),
        ReplayUnitCostOutput(3, 90),
    )


def test_checker_quantity_one_is_independent_of_output_scaling() -> None:
    # One food cost is affordable; output two is capped at50 and moved to gold.
    assert calculate_replay_unit_costs([_master((0, 50, 1))], 0, [0x42480000], 0x40000000) == (
        ReplayUnitCostOutput(0, 50),
        ReplayUnitCostOutput(3, 50),
        ReplayUnitCostOutput(-1, 0),
    )
    # An unaffordable original check suppresses capping, even for scaled output.
    assert calculate_replay_unit_costs([_master((0, 50, 1))], 0, [0x41200000], 0x40000000)[
        0
    ] == ReplayUnitCostOutput(0, 100)


def test_third_gold_slot_replaces_existing_amount() -> None:
    masters = _linked((0, 50, 1), (1, 60, 1), (3, 20, 1))
    # Native replaces third gold amount20 with shortage90, instead of adding110.
    assert calculate_replay_unit_costs(masters, 0, [0x41200000] * 3 + [0x42C80000]) == (
        ReplayUnitCostOutput(0, 10),
        ReplayUnitCostOutput(1, 10),
        ReplayUnitCostOutput(3, 90),
    )


def test_signed16_shortfall_wrap_prevents_gold_substitution() -> None:
    masters = _linked((0, 30000, 1), (1, 30000, 1), (-1, 0, 0))
    assert calculate_replay_unit_costs(masters, 0, [0, 0]) == (
        ReplayUnitCostOutput(-1, 0),
        ReplayUnitCostOutput(-1, 0),
        ReplayUnitCostOutput(-1, 0),
    )


def test_nonpositive_outputs_clear_ids_and_preserve_amounts() -> None:
    master = _master((0, -2, 1), (1, 0, 1), (-2, 999, 1))
    assert calculate_replay_unit_costs([master], 0, [0, 0]) == (
        ReplayUnitCostOutput(-1, -2),
        ReplayUnitCostOutput(-1, 0),
        ReplayUnitCostOutput(-1, 0),
    )


@pytest.mark.parametrize("quantity", (0x7F800000, 0xFF800000, 0x7F801234, 0x4F000000))
def test_invalid_native_integer_conversion_truncates_low16_to_zero(quantity: int) -> None:
    assert calculate_replay_unit_costs([_master((0, 1, 1))], 0, [0], quantity)[0] == (
        ReplayUnitCostOutput(-1, 0)
    )


def test_building_resets_while_queue_adds_and_preserves_sentinel_bits() -> None:
    previous = (
        ReplayProductionCacheSlot(77, 0x3F000000),
        ReplayProductionCacheSlot(-123, 0x80000000),
        ReplayProductionCacheSlot(42, 0x7F801234),
    )
    masters = [_master((0, 50, 1))]
    assert (
        cache_replay_building_unit_costs(masters, -1, []) == (ReplayProductionCacheSlot(-1, 0),) * 3
    )
    assert cache_replay_queue_unit_costs([], 0xFFFFFFFF, [], previous) is previous
    assert cache_replay_queue_unit_costs([], -1, [], previous) is previous
    cache = cache_replay_queue_unit_costs(masters, 0, [0x42480000], previous)
    assert cache == (
        ReplayProductionCacheSlot(0, 0x424A0000),
        ReplayProductionCacheSlot(-1, 0),
        ReplayProductionCacheSlot(-1, 0x7FC01234),
    )
    assert cache_replay_building_unit_costs(masters, 65536, [0x42480000]) == (
        ReplayProductionCacheSlot(0, 0x42480000),
        ReplayProductionCacheSlot(-1, 0),
        ReplayProductionCacheSlot(-1, 0),
    )


@pytest.mark.parametrize("master", (None, _master(kind=69)))
def test_explicit_null_and_low_type_master_return_empty(
    master: ReplayProductionMaster | None,
) -> None:
    assert calculate_replay_unit_costs([master], 0, []) == (ReplayUnitCostOutput(-1, 0),) * 3


def test_missing_native_storage_and_unsupported_research_fail_explicitly() -> None:
    for master_id in (-1, 3):
        with pytest.raises(ValueError, match="backed master-table"):
            calculate_replay_unit_costs([_master()], master_id, [])
    with pytest.raises(ValueError, match="outside"):
        calculate_replay_unit_costs([], 32768, [])
    with pytest.raises(ValueError, match="absent"):
        calculate_replay_unit_costs([_master((571, 50, 1))], 0, [])
    for function in (cache_replay_building_unit_costs, cache_replay_queue_unit_costs):
        with pytest.raises(ValueError, match="research"):
            if function is cache_replay_building_unit_costs:
                function([], -1, [], research_id=0)
            else:
                cache_replay_queue_unit_costs(
                    [], -1, [], (ReplayProductionCacheSlot(-1, 0),) * 3, research_id=0
                )


@pytest.mark.parametrize(
    "factory,args",
    (
        (ReplayUnitCostOutput, (32768, 0)),
        (ReplayUnitCostOutput, (0, -32769)),
        (ReplayProductionCacheSlot, (2147483648, 0)),
        (ReplayProductionCacheSlot, (0, -1)),
    ),
)
def test_raw_field_ranges(factory: type, args: tuple[int, int]) -> None:
    with pytest.raises(ValueError):
        factory(*args)
