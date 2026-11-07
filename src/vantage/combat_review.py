"""Time-scoped destruction values and conservative attack-linked worker downtime.

The estimate measures observed nonproductive worker time after a direct attack.
It does not infer intent, unseen threats or unhit workers fleeing nearby.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from math import hypot
from typing import Any

RESOURCES = ("food", "wood", "stone", "gold")
THREAT_MS = 15_000
THREAT_TILES = 12
CombatEntry = tuple[int, str, float, int]
PressureInterval = tuple[int, int, int, int]  # attacker, start, end, worker


def military_review(
    log: Iterable[CombatEntry], end: int, since: int | None = None
) -> dict[str, Any]:
    """Aggregate frozen kill costs and clip pressure intervals to the query range."""
    start = max(0, since) if since is not None else -1
    resources = dict.fromkeys(RESOURCES, 0.0)
    unknown = 0
    pressure = 0.0
    for when, kind, amount, _other in log:
        if kind == "forced_idle":
            # Entries carry an interval ending at `when`, not a point event.
            a, b = max(start, when - amount * 1000), min(end, when)
            pressure += max(0, b - a) / 1000
        elif start <= when <= end:
            if kind == "destroyed_unknown":
                unknown += int(amount)
            elif kind.startswith("destroyed_") and kind[10:] in resources:
                resources[kind[10:]] += amount
    known = round(sum(resources.values()), 1)
    return {
        "resources_destroyed": {k: round(v, 1) for k, v in resources.items()},
        "destroyed_value": known if not unknown else None,
        "destroyed_known_value": known,
        "destroyed_unknown": unknown,
        "forced_idle_seconds": round(pressure, 2),
        "forced_idle_estimated": True,
        "forced_idle_method": "directly_attacked_workers",
    }


@dataclass(frozen=True)
class PressureWorker:
    working: bool
    alive: bool
    x: float
    y: float


@dataclass
class _Credit:
    attacker: int
    hit: int
    sampled: int
    disrupted: bool = False


class PressureTracker:
    """Assign each attacked worker's observed downtime to at most one attacker."""

    def __init__(self) -> None:
        self.active: dict[int, _Credit] = {}

    def hit(
        self, worker: int, attacker: int, when: int, *, working: bool
    ) -> list[PressureInterval]:
        previous = self.active.get(worker)
        if previous is not None and when > previous.hit + THREAT_MS:
            self.active.pop(worker, None)
            previous = None
        intervals: list[PressureInterval] = []
        if previous is not None:
            end = min(when, previous.hit + THREAT_MS)
            if previous.disrupted and end > previous.sampled:
                intervals.append((previous.attacker, previous.sampled, end, worker))
        if working or previous is not None:
            self.active[worker] = _Credit(
                attacker,
                when,
                when,
                previous.disrupted if previous is not None and not working else False,
            )
        return intervals

    def sample(
        self,
        when: int,
        workers: Mapping[int, PressureWorker],
        attackers: Mapping[int, tuple[float, float]],
    ) -> list[PressureInterval]:
        intervals: list[PressureInterval] = []
        for worker, credit in list(self.active.items()):
            state, origin = workers.get(worker), attackers.get(credit.attacker)
            if (
                state is None
                or not state.alive
                or state.working
                or origin is None
                or hypot(state.x - origin[0], state.y - origin[1]) > THREAT_TILES
            ):
                del self.active[worker]
                continue
            end = min(when, credit.hit + THREAT_MS)
            if credit.disrupted and end > credit.sampled:
                intervals.append((credit.attacker, credit.sampled, end, worker))
            credit.sampled, credit.disrupted = when, True
            if when >= credit.hit + THREAT_MS:
                del self.active[worker]
        return intervals
