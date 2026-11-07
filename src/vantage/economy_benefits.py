"""Observed economic benefits, kept separate from stockpile income.

Savings compare completed production/research with the neutral same-game cost.
Yield estimates allocate the gathered share due to the player's yield multiplier.
Neither represents an extra stockpile transaction.
"""

from __future__ import annotations

from bisect import bisect_right
from collections import defaultdict
from typing import Any

from vantage import world as W
from vantage.patch import Node

RES = ("food", "wood", "stone", "gold")
ADJUST = [W._fid("ResearchState", f"costAdjustment{i}") for i in range(3)]


class EconomyBenefits:
    def __init__(self, data: Any) -> None:
        self.data = data
        self.effects: dict[int, dict[str, dict[str, Any]]] = defaultdict(dict)
        self.logs: dict[int, list[tuple[int, dict[str, Any]]]] = defaultdict(list)
        self.gathered: dict[int, list[float]] = {}
        self.dirty: set[int] = set()
        self.research_prices: dict[tuple[int, int], list[float]] = {}

    def _add(self, owner: int, source: str, category: str, amounts: list[float]) -> None:
        if sum(amounts) < 0.001:
            return
        row = self.effects[owner].setdefault(
            source,
            {
                "source": source,
                "category": category,
                "resources": [0.0] * 4,
                "count": 0,
            },
        )
        row["resources"] = [a + b for a, b in zip(row["resources"], amounts, strict=True)]
        row["count"] += 1
        self.dirty.add(owner)

    @staticmethod
    def _cost(master: Node | None) -> dict[str, float] | None:
        return (
            W.master_cost(master.fields)
            if isinstance(master, Node) and W.M_COST in master.fields
            else None
        )

    def sample(
        self,
        world: Node,
        events: list[dict[str, Any]],
        *,
        handicaps: dict[int, int] | None = None,
        baseline: bool,
        collected: dict[int, list[float]],
        changed_collected: set[int],
        workers: dict[int, Any],
        done: dict[int, set[int]],
        previous_done: dict[int, set[int]],
        built: dict[int, tuple[int, int, bool]],
        previous_built: dict[int, tuple[int, int, bool]],
        new_workers: dict[int, Any],
    ) -> None:
        players = W.players_of(world)
        neutral = players.get(0)
        bases = (neutral.fields.get(W.P_MASTERS) or {}) if neutral else {}
        techs = world.fields.get(W.W_TECHS) or {}

        def production(owner: int, mid: int, kind: str) -> None:
            player = players.get(owner)
            if player is None:
                return
            node = (player.fields.get(W.P_MASTERS) or {}).get(mid)
            if not isinstance(node, Node):
                return
            actual = self._cost(node)
            base = self._cost(bases.get(mid))
            if actual is None or base is None:
                return
            name = self.data.string(node.fields.get(W.M_STRING), str(mid))
            saved = [max(0.0, base.get(r, 0) - actual.get(r, 0)) for r in RES]
            self._add(owner, f"{kind} discount · {name}", "savings", saved)

        if not baseline:
            for event in events:
                if event.get("kind") == "trained" and event.get("player", 0) > 0:
                    production(int(event["player"]), int(event.get("master", -1)), "Unit")
            for eid, (owner, mid, complete) in built.items():
                previous_building = previous_built.get(eid)
                if (
                    complete
                    and previous_building
                    and previous_building[:2] == (owner, mid)
                    and not previous_building[2]
                ):
                    production(owner, mid, "Building")

        for owner, player in players.items():
            if owner <= 0:
                continue
            research = player.fields.get(W.P_RESEARCH) or {}
            completed = (
                done.get(owner, set()) - previous_done.get(owner, set()) if not baseline else set()
            )
            if player.fields.get(W.P_CIV) == 51:
                # The automatic Wei bonus techs identify which upgrades really
                # executed a villager grant (not Loom, ages, or every eco-looking
                # technology). Also require a new civilian, excluding recorded
                # training and conversions. Never value an unobserved spawn.
                newborn = [
                    worker
                    for worker in new_workers.values()
                    if worker.owner == owner and worker.kind == "villagers"
                ]
                for tid in sorted(completed & set(range(1039, 1055))):
                    if not newborn:
                        break
                    worker = newborn.pop()
                    value = self._cost(bases.get(worker.master)) or self._cost(
                        (player.fields.get(W.P_MASTERS) or {}).get(worker.master)
                    )
                    if value is None:
                        continue
                    bonus_tech = techs.get(tid)
                    prerequisites = (
                        bonus_tech.fields.get(W._fid("Technology", "techPrerequisites"), [])
                        if isinstance(bonus_tech, Node)
                        else []
                    )
                    upgrade = next(
                        (
                            techs.get(int(ref.fields.get(0, -1)))
                            for ref in prerequisites
                            if isinstance(ref, Node) and ref.fields.get(0) != 639
                        ),
                        None,
                    )
                    name = (
                        self.data.string(
                            upgrade.fields.get(W.T_STRING), str(upgrade.fields.get(W.T_NAME, tid))
                        )
                        if isinstance(upgrade, Node)
                        else str(tid)
                    )
                    self._add(
                        owner, f"Free villager · {name}", "assets", [value.get(r, 0) for r in RES]
                    )
            # Freeze a paid research's price while it is in progress. Automatic
            # free technologies instead use the adjustment at completion.
            active = {
                tid
                for tid, state in research.items()
                if isinstance(state, Node) and state.fields.get(W.R_STATE) == 2
            }
            for key in list(self.research_prices):
                if key[0] == owner and key[1] not in active | completed:
                    del self.research_prices[key]  # cancelled research can be queued at a new price
            for tid in active | completed:
                tech, state = techs.get(tid), research.get(tid)
                if not isinstance(tech, Node) or not isinstance(state, Node):
                    continue
                cost_rows = tech.fields.get(W.T_COST) or []
                base, actual = [0.0] * 4, [0.0] * 4
                for slot, value in enumerate(cost_rows[:3]):
                    if not isinstance(value, Node):
                        continue
                    resource_index = int(value.fields.get(W.AV_TYPE, 0) or 0)
                    if not 0 <= resource_index < 4:
                        continue
                    cost = max(0.0, float(value.fields.get(W.AV_AMOUNT, 0) or 0))
                    base[resource_index] += cost
                    actual[resource_index] += max(
                        0.0, cost + float(state.fields.get(ADJUST[slot], 0) or 0)
                    )
                if tid in active:
                    self.research_prices.setdefault((owner, tid), actual)
                if tid in completed:
                    actual = self.research_prices.pop((owner, tid), actual)
                    if abs(W.attr(player, "researchCostMod")) > 0.001:
                        continue  # undefined global modifier semantics: do not guess
                    saved = [max(0.0, a - b) for a, b in zip(base, actual, strict=True)]
                    label = "Free tech" if sum(actual) < 0.001 else "Tech discount"
                    name = self.data.string(
                        tech.fields.get(W.T_STRING), str(tech.fields.get(W.T_NAME, tid))
                    )
                    self._add(owner, f"{label} · {name}", "savings", saved)

        # Read each multiplier once per player rather than once per worker.
        factors = {}
        for owner, player in players.items():
            factors[owner] = [
                max(1.0, W.attr(player, r + "Bonus") / W.attr(neutral, r + "Bonus"))
                if neutral and W.attr(neutral, r + "Bonus") > 0
                else 1.0
                for r in RES
            ]
        for eid in set(collected) if baseline else changed_collected:
            amounts = collected[eid]
            old = self.gathered.get(eid, [0.0] * 4)
            self.gathered[eid] = list(amounts)
            worker = workers.get(eid)
            if baseline or worker is None or worker.owner not in players:
                continue
            player = players[worker.owner]
            maya, handicap = [], []
            is_maya = player.fields.get(W.P_CIV) == 16
            percent = (handicaps or {}).get(worker.owner, 100)
            handicap_factor = max(1.0, percent / 100)
            for i, factor in enumerate(factors[worker.owner]):
                gathered = max(0.0, amounts[i] - old[i])
                # A global multiplier alone proves no civilization bonus. Name
                # only the confirmed Maya component and an explicit lobby
                # handicap that is also present in the observed multiplier.
                applied_handicap = handicap_factor if factor + 0.0001 >= handicap_factor else 1.0
                longevity = min(1.15, max(1.0, factor / applied_handicap)) if is_maya else 1.0
                maya.append(gathered * (1 - 1 / longevity))
                handicap.append(gathered / longevity * (1 - 1 / applied_handicap))
            self._add(worker.owner, "Maya resource longevity", "yield", maya)
            if percent > 100:
                self._add(worker.owner, f"Handicap · {percent}%", "handicap", handicap)

    def checkpoint(self, t: int) -> None:
        for owner in self.dirty:
            snapshot = {
                name: {**row, "resources": list(row["resources"])}
                for name, row in self.effects[owner].items()
            }
            self.logs[owner].append((t, snapshot))
        self.dirty.clear()

    def player(self, owner: int, t: int) -> dict[str, Any]:
        log = self.logs.get(owner, [])
        index = bisect_right(log, t, key=lambda row: row[0]) - 1
        values = log[index][1] if index >= 0 else {}

        def resources(amounts: list[float]) -> dict[str, float]:
            return {r: round(n, 1) for r, n in zip(RES, amounts, strict=True)}

        rows = [
            {
                **row,
                "resources": resources(row["resources"]),
                "total": round(sum(row["resources"]), 1),
                "estimated": True,
            }
            for row in values.values()
        ]
        return {
            "effects": rows,
            **{
                key: resources(
                    [
                        sum(
                            row["resources"][i]
                            for row in values.values()
                            if row["category"] == category
                        )
                        for i in range(4)
                    ]
                )
                for key, category in [
                    ("savings", "savings"),
                    ("extra_yield", "yield"),
                    ("handicap_yield", "handicap"),
                ]
            },
        }
