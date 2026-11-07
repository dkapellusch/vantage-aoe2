"""Native population demand for current per-player master definitions.

Native1417102a0 subtracts attribute4 slots, then includes action156 linked
masters once, in task-vector order. Binary32 words preserve SSE operation
order. This computes demand only; it does not reserve it, create units,
modify a production queue or apply effects. Evidence:
world-envelope/production-population/README.md.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from vantage.replay_master_tasks import ReplayMasterTasks
from vantage.replay_masters import SavedMaster
from vantage.replay_movement_geometry import _float, _op, _word


def _integer(value: int, low: int, high: int, label: str) -> None:
    if not isinstance(value, int) or not low <= value <= high:
        raise ValueError(f"{label} is outside its native integer range")


@dataclass(frozen=True, slots=True)
class ReplayPopulationAttribute:
    type_id: int
    amount_bits: int

    def __post_init__(self) -> None:
        _integer(self.type_id, -32768, 32767, "attribute type")
        _word(self.amount_bits)


@dataclass(frozen=True, slots=True)
class ReplayPopulationTask:
    action: int
    master_id_bits: int
    quantity_bits: int

    def __post_init__(self) -> None:
        _integer(self.action, -32768, 32767, "task action")
        _word(self.master_id_bits)
        _word(self.quantity_bits)


@dataclass(frozen=True, slots=True)
class ReplayPopulationMaster:
    type_group: int
    attributes: tuple[
        ReplayPopulationAttribute, ReplayPopulationAttribute, ReplayPopulationAttribute
    ]
    tasks: tuple[ReplayPopulationTask, ...] = ()

    def __post_init__(self) -> None:
        _integer(self.type_group, 0, 255, "master type")
        if len(self.attributes) != 3 or any(
            not isinstance(value, ReplayPopulationAttribute) for value in self.attributes
        ):
            raise ValueError("a population master must contain three native attribute slots")
        if any(not isinstance(value, ReplayPopulationTask) for value in self.tasks):
            raise ValueError("population tasks must be ordered native task entries")


def restore_replay_population_master(
    saved: SavedMaster, tasks: ReplayMasterTasks | None = None
) -> ReplayPopulationMaster:
    """Extract saved attributes and an explicitly restored task list.

    Attribute IDs and amounts use the parser's final values; flags are not
    read by the native demand helper. Types70+ require the caller's resolved
    task list, including inherited baseline tasks. Later runtime edits remain
    the caller's responsibility. Types below70 never inspect tasks here.
    """
    if saved.type_group >= 70 and tasks is None:
        raise ValueError("population restoration requires the resolved native task list")
    try:
        attributes = [
            ReplayPopulationAttribute(saved.fields[0xAA + 2 * i], saved.fields[0xB0 + 4 * i])
            for i in range(3)
        ]
        resolved = (
            tuple(
                ReplayPopulationTask(t.fields[0xE], t.fields[0x28], t.fields[0x2C])
                for t in tasks.tasks
            )
            if saved.type_group >= 70 and tasks is not None
            else ()
        )
    except KeyError as exc:
        raise ValueError(f"population member {exc.args[0]:#x} is missing") from exc
    return ReplayPopulationMaster(
        saved.type_group, (attributes[0], attributes[1], attributes[2]), resolved
    )


def _master(
    masters: Sequence[ReplayPopulationMaster | None], master_id: int
) -> ReplayPopulationMaster | None:
    # Native dereferences the indexed slot without a bounds check. Reject
    # unavailable storage instead of treating it as an explicit null pointer.
    if not 0 <= master_id < len(masters):
        raise ValueError("population master index is outside the supplied native table")
    return masters[master_id]


def _attribute_demand(master: ReplayPopulationMaster | None) -> int:
    result = 0
    if master is not None:
        for attribute in master.attributes:
            if attribute.type_id == 4:
                result = _op(result, attribute.amount_bits, "-")
    return result


def replay_unit_population(
    masters: Sequence[ReplayPopulationMaster | None],
    master_id: int,
    *,
    include_tasks: bool = True,
) -> int:
    """Return native1417102a0 demand as a binary32 word, without mutation.

    An explicit null master returns positive zero. Action156 converts field28
    to an int32 by truncation, reads that master's attributes without visiting
    its tasks, multiplies by field2c, and adds in vector order. Even zero
    quantities perform the native multiplication. Invalid/missing indexed
    storage raises ValueError; no substitute master or demand is invented.
    """
    _integer(master_id, -2147483648, 2147483647, "population master ID")
    if not isinstance(include_tasks, bool):
        raise ValueError("include_tasks must be a bool")
    master = _master(masters, master_id)
    result = _attribute_demand(master)
    if master is None or master.type_group < 70 or not include_tasks:
        return result
    for task in master.tasks:
        if task.action != 156:
            continue
        value = _float(task.master_id_bits)
        if not math.isfinite(value) or not -2147483648 <= value < 2147483648:
            raise ValueError("population task cannot address a valid int32 master index")
        linked = _master(masters, math.trunc(value))
        contribution = _op(_attribute_demand(linked), task.quantity_bits, "*")
        result = _op(result, contribution, "+")
    return result
