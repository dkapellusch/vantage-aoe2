"""Conservative direct-healing attribution and replacement-value estimates.

The stream has HP, heal targets and healer counts, but no heal-amount event.
Observe restoration between frames, add back reported concurrent damage, and
credit it once across the known healers. Regeneration, repair, upgrades, missing
healers and stream discontinuities are excluded rather than credited to a monk.
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from math import hypot, isfinite
from typing import Any

from vantage import world as W
from vantage.patch import Node

RESOURCES = ("food", "wood", "stone", "gold")
HEAL_ACTION = 105
NUM_HEALERS = W._fid("CombatEntity", "numHealers")
MONK_CLASSES = (18, 43)
MAX_INTERVAL_MS = 2000
EPSILON = 0.001


@dataclass(frozen=True, slots=True)
class Health:
    owner: int
    master: int
    hp: float
    maximum: float
    healers: int
    cost: tuple[float, ...] | None
    eligible: bool


# time, cumulative HP, cumulative per-resource value, unpriced HP, shared HP
HealingSample = tuple[int, float, tuple[float, ...], float, float]
EMPTY: HealingSample = (-1, 0.0, (0.0, 0.0, 0.0, 0.0), 0.0, 0.0)


class HealingHistory:
    def __init__(self, kill_groups: Callable[[int], list[int]] | None = None) -> None:
        self.kill_groups = kill_groups
        self.log: dict[int, list[HealingSample]] = defaultdict(list)
        self.healers: dict[int, int] = {}
        self.previous: dict[int, Health] = {}
        self.links: dict[int, tuple[int, int]] = {}  # healer -> (owner, target)
        self.start: int | None = None
        self.last: int | None = None
        self.gaps: list[tuple[int, int]] = []

    def sample(
        self,
        world: Node | None,
        t: int,
        events: list[dict[str, Any]],
        *,
        discontinuity: bool = False,
    ) -> None:
        if world is None:
            return
        first = self.last is None
        if first:
            self.start = t
        gap = self.last is not None and (discontinuity or not 0 < t - self.last <= MAX_INTERVAL_MS)
        if gap and self.last is not None and t > self.last:
            self.gaps.append((self.last, t))
        entities, players = W.entities_of(world), W.players_of(world)
        links: dict[int, tuple[int, int]] = {}
        repairs: set[int] = set()
        for eid, entity in entities.items():
            f = entity.fields
            owner = int(f.get(W.E_OWNER, 0) or 0)
            if owner <= 0 or f.get(W.E_STATE, 2) > W.ENTITY_ALIVE:
                continue
            master = W.master_node(entity, players)
            if master is None:
                continue
            action = W._action_node(entity, W.E_ACTION)
            af = action.fields if action else {}
            if int(master.fields.get(W.M_CLASS, -1)) in MONK_CLASSES:
                self.healers.setdefault(eid, t)
            if af.get(W.A_TYPE) == W._REPAIR_ACTION:
                repairs.add(int(af.get(W.A_TARGET, -1)))
            if (
                af.get(W.A_TYPE) != HEAL_ACTION
                or af.get(W.A_STATE) != 7
                or int(f.get(W.E_INSIDE, -1) or -1) > 0
            ):
                continue
            self.healers.setdefault(eid, t)
            target_id = int(af.get(W.A_TARGET, -1))
            target_node = entities.get(target_id)
            if target_node is None:
                continue
            tf = target_node.fields
            target_owner = int(tf.get(W.E_OWNER, 0) or 0)
            if (
                target_owner != owner
                and W.diplomacy(players[owner]).get(str(target_owner)) != "ally"
            ):
                continue
            reach = W.attr(players[owner], "healRange")
            if reach > 0:
                target_master = W.master_node(target_node, players)
                radius = (
                    float(target_master.fields.get(W.M_RADIUS_X, 0) or 0) if target_master else 0
                )
                distance = hypot(
                    float(f.get(W.E_X, 0)) - float(tf.get(W.E_X, 0)),
                    float(f.get(W.E_Y, 0)) - float(tf.get(W.E_Y, 0)),
                )
                if distance > reach + radius + 0.5:
                    continue
            links[eid] = (owner, target_id)
        targets = {target for _, target in (*links.values(), *self.links.values())}
        current: dict[int, Health] = {}
        ctx = W.ModContext(entities, players, self.kill_groups)
        for target_id in targets:
            patient = entities.get(target_id)
            master = W.master_node(patient, players) if patient else None
            if patient is None or master is None:
                continue
            f, mf = patient.fields, master.fields
            owner, mid = int(f.get(W.E_OWNER, 0) or 0), int(f.get(W.E_MASTER, -1))
            if owner <= 0 or owner not in players:
                continue
            hp = float(f.get(W.E_HP, 0) or 0)
            mods, hp_bonus, max_bonus = W.entity_mods(
                patient,
                mf,
                W.master_rules(mf),
                ctx,
                players[owner].fields.get(W.P_MASTERS) or {},
                mid,
            )
            maximum = float(mf.get(W.M_HP, 0) or 0) + max_bonus
            cost = W.master_cost(mf) if W.M_COST in mf else None
            eligible = (
                owner > 0
                and f.get(W.E_STATE, 2) <= W.ENTITY_ALIVE
                and int(f.get(W.E_INSIDE, -1) or -1) <= 0
                and int(mf.get(W.M_TYPE, 0)) != 80
                and target_id not in repairs
                and abs(float(mods.get("regen", W.regen_display(mf, mid)))) < EPSILON
                and isfinite(hp)
                and maximum > 0
                and 0 < hp <= maximum + EPSILON
            )
            current[target_id] = Health(
                owner,
                mid,
                hp + hp_bonus,
                maximum,
                int(f.get(NUM_HEALERS, 0) or 0),
                tuple(cost.get(r, 0) for r in RESOURCES) if cost is not None else None,
                eligible,
            )
        if not first and not gap:
            damage: dict[int, float] = defaultdict(float)
            for event in events:
                if event.get("kind") == "damage":
                    amount = float(event.get("damage", 0) or 0)
                    if isfinite(amount) and amount > 0:
                        damage[int(event.get("entityid", -1))] += amount
            by_target: dict[int, list[int]] = defaultdict(list)
            for healer, previous_link in self.links.items():
                _, target = previous_link
                now, before = current.get(target), self.previous.get(target)
                source = entities.get(healer)
                if source is None or source.fields.get(W.E_STATE, 2) > W.ENTITY_ALIVE:
                    continue
                if int(source.fields.get(W.E_OWNER, 0) or 0) != previous_link[0]:
                    continue
                # Include the last partial tick that finishes a heal, even though
                # the monk has already returned to idle in the new frame.
                finished = now is not None and now.hp >= now.maximum - EPSILON
                if before is not None and (links.get(healer) == previous_link or finished):
                    by_target[target].append(healer)
            for target, ids in by_target.items():
                before, now = self.previous.get(target), current.get(target)
                if (
                    before is None
                    or now is None
                    or not before.eligible
                    or not now.eligible
                    or (before.owner, before.master, before.maximum)
                    != (now.owner, now.master, now.maximum)
                    or before.healers != len(ids)
                    or now.healers not in (len(ids), 0)
                    or (now.healers == 0 and now.hp < now.maximum - EPSILON)
                ):
                    continue
                restored = now.hp - before.hp + damage.get(target, 0.0)
                if restored <= EPSILON:
                    continue
                for healer in ids:
                    hp = restored / len(ids)
                    previous = self.log[healer][-1] if self.log[healer] else EMPTY
                    priced = now.cost is not None
                    value = tuple(
                        previous[2][i]
                        + (hp / now.maximum * now.cost[i] if now.cost is not None else 0)
                        for i in range(4)
                    )
                    self.log[healer].append(
                        (
                            t,
                            previous[1] + hp,
                            value,
                            previous[3] + (0 if priced else hp),
                            previous[4] + (hp if len(ids) > 1 else 0),
                        )
                    )
        self.previous, self.links, self.last = current, links, t

    def query_state(self) -> dict[str, Any]:
        """What totals() reads, for the playback index (restore_query_state)."""
        return {"log": self.log, "healers": self.healers, "start": self.start, "gaps": self.gaps}

    def restore_query_state(self, state: dict[str, Any]) -> None:
        self.log = defaultdict(
            list, {k: [tuple(row) for row in v] for k, v in state["log"].items()}
        )
        self.healers = dict(state["healers"])
        self.start = state["start"]
        self.gaps = [tuple(gap) for gap in state["gaps"]]

    def totals(self, ids: Iterable[int], end: int, since: int | None = None) -> dict[str, Any]:
        hp = unknown = shared = 0.0
        resources = [0.0] * 4
        healers = {eid for eid in ids if self.healers.get(eid, end + 1) <= end}
        for eid in healers:
            log = self.log.get(eid, [])
            right = bisect_right(log, end, key=lambda row: row[0]) - 1
            left = (
                bisect_left(log, min(since, end + 1), key=lambda row: row[0]) - 1
                if since is not None
                else -1
            )
            last, first = log[right] if right >= 0 else EMPTY, log[left] if left >= 0 else EMPTY
            hp += last[1] - first[1]
            unknown += last[3] - first[3]
            shared += last[4] - first[4]
            resources = [resources[i] + last[2][i] - first[2][i] for i in range(4)]
        known = round(sum(resources), 2)
        return {
            "healer_count": len(healers),
            "hp": round(hp, 2),
            "resources": {r: round(v, 2) for r, v in zip(RESOURCES, resources, strict=True)},
            "value": known if unknown < EPSILON else None,
            "known_value": known,
            "unpriced_hp": round(unknown, 2),
            "shared_hp": round(shared, 2),
            "estimated": True,
            "method": "observed_direct_healing",
            "partial": bool(
                (self.start or 0) > (since or 0)
                or any(a < end and b > (since or 0) for a, b in self.gaps)
            ),
            "observed_from_ms": self.start,
        }
