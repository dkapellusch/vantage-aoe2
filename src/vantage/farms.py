"""Farm facts and Folwark grants observed on consecutive decoded stream frames.

The stream's farm heldAttributeAmount is a <=15-food production buffer, NOT
remaining food. farmDeathRate is the owner's new-farm supply. Neither exposes
an existing farm's hidden lifetime supply (including partial upgrade top-ups).
"""

from __future__ import annotations

from bisect import bisect_right
from collections import defaultdict
from typing import Any

from vantage import world as W
from vantage.patch import Node

# Installed-build technology effects: common farm supply upgrades, Chinese team
# supply, Sicilian upgrade multiplier, Teuton reseeding cost. Query actual states;
# never grant a technology merely because of the owner's civilisation.
FARM_TECHS = (14, 13, 12)
FARM_BONUSES = {
    232: (None, "Chinese team farm food"),
    772: (37, "Sicilian farm upgrades"),
    314: (4, "Teuton farm reseeding cost"),
}


class FarmHistory:
    def __init__(self) -> None:
        self.rules: dict[int, list[tuple[int, dict[str, Any]]]] = defaultdict(list)
        self.farms: dict[int, list[tuple[int, dict[str, Any]]]] = defaultdict(list)
        self.grants: list[dict[str, Any]] = []
        self.previous: dict[int, tuple[int, bool]] = {}
        self.research_times: dict[tuple[int, int], int | None] = {}

    @staticmethod
    def at(log: list[Any], t: int) -> Any:
        i = bisect_right(log, t, key=lambda row: row[0]) - 1
        return log[i][1] if i >= 0 else None

    def sample(self, world: Node, t: int, *, baseline: bool) -> list[dict[str, Any]]:
        players = W.players_of(world)
        entities = W.entities_of(world)
        for pid, player in players.items():
            if pid <= 0:
                continue
            states = player.fields.get(W.P_RESEARCH) or {}
            upgrades = []
            for tid in (*FARM_TECHS, *FARM_BONUSES):
                state = states.get(tid)
                done = isinstance(state, Node) and state.fields.get(W.R_STATE) == W.RESEARCH_DONE
                if tid in FARM_BONUSES:
                    civ, _ = FARM_BONUSES[tid]
                    if not done and (civ is None or player.fields.get(W.P_CIV) != civ):
                        continue
                key = (pid, tid)
                if done and key not in self.research_times:
                    self.research_times[key] = None if baseline else t
                upgrades.append(
                    {
                        "tech": tid,
                        "done": done,
                        "researched_ms": self.research_times.get(key),
                        "label": FARM_BONUSES[tid][1] if tid in FARM_BONUSES else None,
                    }
                )
            rule = {
                "capacity": W.attr(player, "farmDeathRate"),
                "upgrades": upgrades,
                "auto_reseed": player.fields.get(W._fid("Player", "autoFarmQueue")),
                "folwark_resource": int(W.attr(player, "folwarkCollectAttributeType")),
                **W.folwark(player),
            }
            log = self.rules[pid]
            if not log or log[-1][1] != rule:
                log.append((t, rule))
        sites: dict[int, list[tuple[int, Node]]] = defaultdict(list)
        farms = {}
        for eid, entity in entities.items():
            f = entity.fields
            owner = int(f.get(W.E_OWNER, 0) or 0)
            if owner <= 0 or f.get(W.E_DOPPLE) or f.get(W.E_STATE, 2) != W.ENTITY_ALIVE:
                continue
            owner_rules = self.rules.get(owner)
            if not owner_rules:
                continue
            if f.get(W.E_MASTER) == owner_rules[-1][1]["folwark_building"] and f.get(W.B_BUILT):
                sites[owner].append((eid, entity))
            master = W.master_node(entity, players)
            if master is not None and master.fields.get(W.M_CLASS) == 49:
                farms[eid] = entity
        new_grants = []
        current = {}
        for eid, farm in farms.items():
            f = farm.fields
            owner = int(f[W.E_OWNER])
            built = bool(f.get(W.B_BUILT))
            current[eid] = (owner, built)
            previous = self.previous.get(eid)
            log = self.farms[eid]
            if not log or log[-1][1]["owner"] != owner:
                log.append((t, {"owner": owner, "completed_ms": None, "capacity_at_build": None}))
            if baseline or not built or previous != (owner, False):
                continue
            rule = self.rules[owner][-1][1]
            log.append(
                (t, {"owner": owner, "completed_ms": t, "capacity_at_build": rule["capacity"]})
            )
            near = [
                sid
                for sid, site in sites[owner]
                if max(
                    abs(float(site.fields.get(W.E_X, 0)) - float(f.get(W.E_X, 0))),
                    abs(float(site.fields.get(W.E_Y, 0)) - float(f.get(W.E_Y, 0))),
                )
                <= W.FOLWARK_REACH
            ]
            amount = rule["folwark_food"]
            if near and amount is not None and amount > 0 and rule["folwark_resource"] == 0:
                new_grants.append(
                    {
                        "time": t,
                        "farm": eid,
                        "owner": owner,
                        "food": amount,
                        "folwarks": sorted(near),
                    }
                )
        self.previous = current
        return new_grants

    def confirm(self, grants: list[dict[str, Any]], receipts: dict[int, float]) -> None:
        """Require the recorded food receipt to cover every grant in the frame."""
        totals: dict[int, float] = defaultdict(float)
        for grant in grants:
            totals[grant["owner"]] += grant["food"]
        for grant in grants:
            if receipts.get(grant["owner"], 0) + 0.01 >= totals[grant["owner"]]:
                self.grants.append(grant)

    def bonus(self, owner: int, t: int) -> float:
        return float(sum(g["food"] for g in self.grants if g["owner"] == owner and g["time"] <= t))

    def entity(self, eid: int, owner: int, master: int, t: int) -> dict[str, Any]:
        rule = self.at(self.rules.get(owner, []), t)
        if not rule:
            return {}
        farm = self.at(self.farms.get(eid, []), t)
        if farm and farm["owner"] == owner:
            return {
                "farm": {
                    **farm,
                    **rule,
                    "remaining": None,
                    "age_ms": t - farm["completed_ms"]
                    if farm["completed_ms"] is not None
                    else None,
                    "grants": [g for g in self.grants if g["farm"] == eid and g["time"] <= t],
                }
            }
        if master == rule["folwark_building"]:
            grants = [g for g in self.grants if eid in g["folwarks"] and g["time"] <= t]
            exact = [g for g in grants if len(g["folwarks"]) == 1]
            return {
                "folwark": {
                    "food": sum(g["food"] for g in exact),
                    "farms": len(exact),
                    "shared_food": sum(g["food"] for g in grants if len(g["folwarks"]) > 1),
                    "grants": grants,
                    "next_food": rule["folwark_food"],
                    "reach": rule["folwark_reach"],
                }
            }
        return {}
