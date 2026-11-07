"""Bounded native unit-cost output and production caches for build54800.

This is the stage after charging, with current resource words and restored
master costs supplied by the caller. It does not charge, insert a queue item,
reserve population or support research costs. Native141700980 is distinct
from the affordability checker's annex-selected cost source.
Evidence: world-envelope/production-cost-cache/README.md.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from vantage.replay_movement_geometry import _bits, _float, _op, _word
from vantage.replay_production_resources import (
    ReplayProductionMaster,
    _integer,
    check_replay_unit_resources,
)


def _short(value: int) -> int:
    return ((value + 0x8000) & 0xFFFF) - 0x8000


def _truncate(value: int) -> int:
    real = _float(value)
    if not math.isfinite(real) or real < -2147483648 or real >= 2147483648:
        return -2147483648
    return math.trunc(real)


@dataclass(frozen=True, slots=True)
class ReplayUnitCostOutput:
    """The signed16 output pair, including an amount whose ID was cleared."""

    resource_id: int
    amount: int

    def __post_init__(self) -> None:
        _integer(self.resource_id, -32768, 32767, "output resource ID")
        _integer(self.amount, -32768, 32767, "output amount")


@dataclass(frozen=True, slots=True)
class ReplayProductionCacheSlot:
    """A native i32 resource ID followed by an unmodified binary32 word."""

    resource_id: int
    amount_bits: int

    def __post_init__(self) -> None:
        _integer(self.resource_id, -2147483648, 2147483647, "cached resource ID")
        _word(self.amount_bits)


UnitCostOutputs = tuple[ReplayUnitCostOutput, ReplayUnitCostOutput, ReplayUnitCostOutput]
ProductionCache = tuple[
    ReplayProductionCacheSlot, ReplayProductionCacheSlot, ReplayProductionCacheSlot
]


def calculate_replay_unit_costs(
    masters: Sequence[ReplayProductionMaster | None],
    master_id: int,
    resources: Sequence[int],
    quantity_bits: int = 0x3F800000,
) -> UnitCostOutputs:
    """Native141700980 with the optional name-output pointer absent.

    Affordability always checks quantity1 with population enabled. Output
    amounts independently scale the requested master's own costs, irrespective
    of cost flags. Only a successful check permits capping a slot to available
    resources and accumulating its signed16 shortfall. A positive final
    shortfall goes into the first ID3/-1 slot; the third slot replaces its
    amount whereas the first two add. Nonpositive amounts then clear IDs.

    Unlike the checker, native code unconditionally indexes the master table
    after checking. Negative/out-of-table IDs are unsupported storage states
    here and raise rather than inventing a null entry. An explicit None entry
    or a type below70 returns three (-1,0) pairs. Resources are read only.
    """
    _integer(master_id, -32768, 32767, "cost output master ID")
    _word(quantity_bits)
    if not 0 <= master_id < len(masters):
        raise ValueError("native cost output requires a backed master-table entry")
    checked = check_replay_unit_resources(masters, master_id, resources, 0x3F800000)
    master = masters[master_id]
    if master is None or master.type_group < 70:
        empty = ReplayUnitCostOutput(-1, 0)
        return empty, empty, empty
    ids = [cost.resource_id for cost in master.costs]
    amounts = [0, 0, 0]
    shortage = 0
    for index, cost in enumerate(master.costs):
        if cost.resource_id < 0:
            continue
        if cost.resource_id >= len(resources):
            raise ValueError(f"resource {cost.resource_id} is absent from the supplied array")
        scaled = _op(_bits(float(cost.amount)), quantity_bits, "*")
        amounts[index] = _short(_truncate(scaled))
        available = resources[cost.resource_id]
        if _float(available) < amounts[index] and checked.affordable:
            clipped = _short(_truncate(available))
            shortage = _short(shortage + amounts[index] - clipped)
            amounts[index] = clipped
    if shortage > 0:
        for index in range(3):
            if ids[index] in (3, -1):
                ids[index] = 3
                amounts[index] = shortage if index == 2 else _short(amounts[index] + shortage)
                break
    outputs = [
        ReplayUnitCostOutput(resource_id if amount > 0 else -1, amount)
        for resource_id, amount in zip(ids, amounts, strict=True)
    ]
    return outputs[0], outputs[1], outputs[2]


def _research(research_id: int) -> None:
    _integer(research_id, -2147483648, 2147483647, "research ID")
    if research_id != -1:
        raise ValueError("research cost caching is outside the proven unit-only branch")


def cache_replay_building_unit_costs(
    masters: Sequence[ReplayProductionMaster | None],
    unit_id: int,
    resources: Sequence[int],
    *,
    research_id: int = -1,
) -> ProductionCache:
    """Native1412806d0: reset all three cache slots, then write unit costs.

    The raw ID is signed32: only -1 skips output. Other values truncate to
    signed16 at the helper call. Existing building cache contents are discarded.
    Research remains unsupported even if a unit ID is also present.
    """
    _research(research_id)
    _integer(unit_id, -2147483648, 2147483647, "building unit ID")
    if unit_id == -1:
        empty = ReplayProductionCacheSlot(-1, 0)
        return empty, empty, empty
    outputs = calculate_replay_unit_costs(masters, _short(unit_id), resources)
    result = [
        ReplayProductionCacheSlot(o.resource_id, _op(_bits(float(o.amount)), 0, "+"))
        for o in outputs
    ]
    return result[0], result[1], result[2]


def cache_replay_queue_unit_costs(
    masters: Sequence[ReplayProductionMaster | None],
    unit_id: int,
    resources: Sequence[int],
    previous: ProductionCache,
    *,
    research_id: int = -1,
) -> ProductionCache:
    """Native14127c410's researchID=-1 unit branch for one selected queue slot.

    This pure result applies equally to the building's buffer or an explicit
    override buffer. The raw unit ID is u32 (with -1 accepted as its sentinel).
    A sentinel returns exact existing bits. Otherwise IDs are overwritten and
    each signed16 output amount is converted to f32, then added to that slot's
    existing f32 amount in native operand order. Pre-branch pointer/resource
    reads with no effect on this unit result are outside the pure API.
    """
    _research(research_id)
    _integer(unit_id, -1, 0xFFFFFFFF, "queue unit ID")
    if (
        not isinstance(previous, tuple)
        or len(previous) != 3
        or any(not isinstance(slot, ReplayProductionCacheSlot) for slot in previous)
    ):
        raise ValueError("previous cache must contain three native cache slots")
    if unit_id in (-1, 0xFFFFFFFF):
        return previous
    outputs = calculate_replay_unit_costs(masters, _short(unit_id), resources)
    result = [
        ReplayProductionCacheSlot(o.resource_id, _op(_bits(float(o.amount)), old.amount_bits, "+"))
        for o, old in zip(outputs, previous, strict=True)
    ]
    return result[0], result[1], result[2]
