"""Native unit-production affordability and resource charging for build54800.

Inputs are already restored, current per-player master costs and resource
binary32 words. This does not apply orders, manage queues, reserve population,
advance training or resolve baseline/effect data. Native operation order and
masked default SSE comparisons are preserved, including unordered operands.
Evidence: world-envelope/production-resources/README.md.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from vantage.replay_masters import SavedMaster
from vantage.replay_movement_geometry import _bits, _float, _op, _word


def _integer(value: int, low: int, high: int, label: str) -> None:
    if not isinstance(value, int) or not low <= value <= high:
        raise ValueError(f"{label} is outside its native integer range")


@dataclass(frozen=True, slots=True)
class ReplayUnitCost:
    resource_id: int
    amount: int
    enabled: int

    def __post_init__(self) -> None:
        _integer(self.resource_id, -32768, 32767, "cost resource ID")
        _integer(self.amount, -32768, 32767, "cost amount")
        _integer(self.enabled, 0, 255, "cost flag")


@dataclass(frozen=True, slots=True)
class ReplayProductionMaster:
    """Only members read by native1416e59e0/1417015d0, supplied after effects."""

    type_group: int
    costs: tuple[ReplayUnitCost, ReplayUnitCost, ReplayUnitCost]
    annex_id: int = -1
    head_id: int = -1

    def __post_init__(self) -> None:
        _integer(self.type_group, 0, 255, "master type")
        _integer(self.annex_id, -32768, 32767, "master annex ID")
        _integer(self.head_id, -32768, 32767, "master head ID")
        if len(self.costs) != 3 or any(not isinstance(c, ReplayUnitCost) for c in self.costs):
            raise ValueError("a production master must contain exactly three native cost slots")


@dataclass(frozen=True, slots=True)
class ReplayResourceCheck:
    affordable: bool
    missing_resource: int


@dataclass(frozen=True, slots=True)
class ReplayResourceCharge:
    accepted: bool
    resources: tuple[int, ...]


def restore_replay_production_master(saved: SavedMaster) -> ReplayProductionMaster:
    """Extract the production cost/link members completely serialized at68.9.

    Use the parser's final values: modern trailing cost members overwrite the
    earlier six-byte cost records. This is the saved-reader stage, before any
    subsequent runtime effects, and does not restore the rest of the master.
    No baseline cost or default is substituted for missing serialized data.
    """
    if saved.type_group not in (70, 80):
        raise ValueError("saved master has no supported unit-production cost component")
    try:
        costs = [
            ReplayUnitCost(*(saved.fields[0x320 + 6 * slot + d] for d in (0, 2, 4)))
            for slot in range(3)
        ]
        return ReplayProductionMaster(
            saved.type_group,
            (costs[0], costs[1], costs[2]),
            saved.fields[0x458] if saved.type_group == 80 else -1,
            saved.fields[0x426] if saved.type_group == 80 else -1,
        )
    except KeyError as exc:
        raise ValueError(f"saved production member {exc.args[0]:#x} is missing") from exc


def _get_master(
    masters: Sequence[ReplayProductionMaster | None], index: int, *, reference: bool = False
) -> ReplayProductionMaster | None:
    if not 0 <= index < len(masters):
        if reference:
            raise ValueError("linked master reference is outside the supplied native table")
        return None
    return masters[index]


def _cost_master(
    masters: Sequence[ReplayProductionMaster | None], master: ReplayProductionMaster
) -> tuple[ReplayProductionMaster, bool]:
    # A present annex becomes the cost source even when its head is absent.
    # Only successfully following both links enables the inactive-slot filter.
    if master.type_group == 80 and master.annex_id != -1:
        annex = _get_master(masters, master.annex_id, reference=True)
        if annex is not None:
            if annex.head_id != -1:
                head = _get_master(masters, annex.head_id, reference=True)
                if head is not None:
                    return head, True
            return annex, False
    return master, False


def _resource(resources: Sequence[int], index: int) -> int:
    if index >= len(resources):
        raise ValueError(f"resource {index} is absent from the supplied native resource array")
    return resources[index]


def _validate(
    master_id: int,
    resources: Sequence[int],
    quantity_bits: int,
    skip_population: bool,
    reserve_a: tuple[int, int, int, int] | None,
    reserve_b: tuple[int, int, int, int] | None,
) -> None:
    _integer(master_id, -32768, 32767, "production master ID")
    _word(quantity_bits)
    if not isinstance(skip_population, bool):
        raise ValueError("skip_population must be a bool")
    for value in resources:
        _word(value)
    for reserved in (reserve_a, reserve_b):
        if reserved is not None:
            if len(reserved) != 4:
                raise ValueError("a native resource reservation must have four binary32 words")
            for value in reserved:
                _word(value)


def _population_missing(resources: Sequence[int], cost: int) -> int:
    current = _resource(resources, 11)
    maximum = _resource(resources, 32)
    if _float(current) >= _float(maximum):
        return 32
    provided = _op(_resource(resources, 4), current, "+")
    # MINSS selects its source (maximum) for equality or unordered operands.
    limit = provided if _float(provided) < _float(maximum) else maximum
    needed = _op(_op(_resource(resources, 80), current, "+"), cost, "+")
    # Native JBE accepts unordered here; a Python <= comparison would reject it.
    if not _float(needed) > _float(limit):
        return -1
    return 4 if _float(maximum) > _float(provided) else 32


def check_replay_unit_resources(
    masters: Sequence[ReplayProductionMaster | None],
    master_id: int,
    resources: Sequence[int],
    quantity_bits: int,
    *,
    skip_population: bool = False,
    reserve_a: tuple[int, int, int, int] | None = None,
    reserve_b: tuple[int, int, int, int] | None = None,
) -> ReplayResourceCheck:
    """Native1416e59e0: inspect three current costs without mutating resources.

    Missing/invalid requested masters return false/missing=-1. Linked references
    outside the supplied table and missing resource cells raise ValueError;
    native callers require valid storage there. Cost resource571 is skipped.
    Ordinary master costs are checked even when their flag is zero. Both linked
    building references must resolve before inactive costs are skipped.
    Reservation arrays affect resource IDs0..3 only and are subtracted in order.
    Repeated costs are checked separately against the same original resources.
    """
    _validate(master_id, resources, quantity_bits, skip_population, reserve_a, reserve_b)
    master = _get_master(masters, master_id)
    if master is None or master.type_group < 70:
        return ReplayResourceCheck(False, -1)
    source, filter_inactive = _cost_master(masters, master)
    for slot in source.costs:
        resource_id = slot.resource_id
        if resource_id < 0 or resource_id == 571 or (filter_inactive and not slot.enabled):
            continue
        cost = _op(_bits(float(slot.amount)), quantity_bits, "*")
        if _float(cost) == 0.0:
            continue
        if resource_id == 4:
            if not skip_population:
                missing = _population_missing(resources, cost)
                if missing != -1:
                    return ReplayResourceCheck(False, missing)
        else:
            available = _resource(resources, resource_id)
            if resource_id < 4:
                for reserved in (reserve_a, reserve_b):
                    if reserved is not None:
                        available = _op(available, reserved[resource_id], "-")
            if _float(cost) > _float(available):
                return ReplayResourceCheck(False, resource_id)
    return ReplayResourceCheck(True, -1)


def charge_replay_unit_resources(
    masters: Sequence[ReplayProductionMaster | None],
    master_id: int,
    resources: Sequence[int],
    quantity_bits: int,
    *,
    skip_population: bool = True,
) -> ReplayResourceCharge:
    """Native1417015d0: check, then subtract the requested master's active costs.

    The affordability call has no reservation-array flags. Failed checks leave
    every resource word unchanged. Successful checks charge the requested
    master's slots, even if linked masters supplied the affordability costs.
    Duplicate resource slots deduct sequentially with binary32 rounding. This
    returns gameplay resource values; native storage obfuscation, UI/telemetry,
    population reservations and queue mutation are outside this helper.
    """
    before = tuple(resources)
    check = check_replay_unit_resources(
        masters, master_id, before, quantity_bits, skip_population=skip_population
    )
    if not check.affordable:
        return ReplayResourceCharge(False, before)
    master = _get_master(masters, master_id)
    assert master is not None
    after = list(before)
    for slot in master.costs:
        if slot.resource_id >= 0 and slot.enabled:
            original = _resource(after, slot.resource_id)
            cost = _op(_bits(float(slot.amount)), quantity_bits, "*")
            after[slot.resource_id] = _op(original, cost, "-")
    return ReplayResourceCharge(True, tuple(after))
