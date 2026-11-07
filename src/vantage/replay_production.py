"""Native selected-unit affordability, charging and population reservation phase.

The selected master/quantity are supplied after any variant-RNG recursion.
This phase ends before cached costs, object tracking, allocation and queue
insertion. A returned charge does not mean a unit was queued or created.
Evidence: world-envelope/production-accepted-phase/README.md.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from vantage.replay_movement_geometry import _bits, _op, _word
from vantage.replay_population import ReplayPopulationMaster, replay_unit_population
from vantage.replay_production_resources import (
    ReplayProductionMaster,
    charge_replay_unit_resources,
)


@dataclass(frozen=True, slots=True)
class ReplayProductionCharge:
    selected_master_id: int
    accepted_quantity: int
    resources: tuple[int, ...]


def charge_replay_production_selection(
    cost_masters: Sequence[ReplayProductionMaster | None],
    population_masters: Sequence[ReplayPopulationMaster | None],
    selected_master_id: int,
    quantity: int,
    queued_units: int,
    resources: Sequence[int],
) -> ReplayProductionCharge:
    """Native1412846b0 unit branch through the virtual resource80 update.

    Clamp to15 queued units, then retry affordability with decreasing counts.
    A successful charge subtracts active costs and adds binary32 population
    demand times the accepted integer quantity to resource80. Failed checks
    and full capacity retain all original resource words. Population capacity
    is not checked in this phase (the native charger receives skip=true).

    Both master tables are explicit current per-player data. The caller must
    already resolve1810/83 variant requests and their recursive order; those
    choices and RNG are not performed here. Only positive i16 quantities are
    supported. No queue, cache, tracking, UI or entity changes are published.
    """
    for value, low, high, label in (
        (selected_master_id, -32768, 32767, "selected master ID"),
        (quantity, 1, 32767, "selected quantity"),
        (queued_units, 0, 15, "queued unit count"),
    ):
        if not isinstance(value, int) or not low <= value <= high:
            raise ValueError(f"{label} is outside the supported native range")
    before = tuple(resources)
    for word in before:
        _word(word)
    accepted = min(quantity, 15 - queued_units)
    while accepted > 0:
        quantity_bits = _bits(float(accepted))
        charge = charge_replay_unit_resources(
            cost_masters, selected_master_id, before, quantity_bits, skip_population=True
        )
        if charge.accepted:
            if len(charge.resources) <= 80:
                raise ValueError("population reservation resource80 is absent")
            demand = replay_unit_population(population_masters, selected_master_id)
            amount = _op(demand, quantity_bits, "*")
            after = list(charge.resources)
            after[80] = _op(after[80], amount, "+")
            return ReplayProductionCharge(selected_master_id, accepted, tuple(after))
        accepted -= 1
    return ReplayProductionCharge(selected_master_id, 0, before)
