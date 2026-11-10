"""Observed resource history, with conservative, explicit income attribution.

Collection is observed on every stream frame, not on the rendered keyframes.
There is no per-worker deposit event in cade_api. A carry reset is a delivery
only when it is corroborated by player income and a compatible nearby dropsite.
Ambiguous recipients and unexplained income are retained, never silently guessed.
"""

from __future__ import annotations

from bisect import bisect_right
from collections import defaultdict
from dataclasses import dataclass
from math import hypot
from typing import Any

from vantage import world as W
from vantage.economy_benefits import EconomyBenefits
from vantage.patch import Node

RES = ("food", "wood", "stone", "gold")
RINDEX = {r: i for i, r in enumerate(RES)}
TARGET2 = W._fid("Action", "target2Id")
EPS = 0.001


def vector() -> list[float]:
    return [0.0] * 4


def resource_dict(values: list[float]) -> dict[str, float]:
    return {r: round(values[i], 1) for i, r in enumerate(RES)}


@dataclass(slots=True)
class Worker:
    owner: int
    master: int
    resource: str | None
    amount: float
    x: float
    y: float
    targets: tuple[int, int]
    gathering: bool
    kind: str
    bonus: tuple[tuple[str, float], ...]
    direct_farm: int | None = None
    direct_gold: str | None = None


class ResourceHistory:
    def __init__(self, data: Any) -> None:
        self.data = data
        self.workers: dict[int, Worker] = {}
        self.players: dict[int, tuple[list[float], float, list[float]]] = {}
        self.collected: dict[int, list[float]] = defaultdict(vector)
        self.delivered: dict[int, list[float]] = defaultdict(vector)
        self.credited: dict[int, list[float]] = defaultdict(vector)
        self.gather_log: dict[int, list[tuple[int, list[float]]]] = defaultdict(list)
        self.deposit_log: dict[int, list[tuple[int, list[float]]]] = defaultdict(list)
        self.credit_log: dict[int, list[tuple[int, list[float]]]] = defaultdict(list)
        self.income: dict[int, dict[str, list[float]]] = defaultdict(lambda: defaultdict(vector))
        self.source_entities: dict[int, dict[str, set[int]]] = defaultdict(lambda: defaultdict(set))
        self.source_log: dict[int, list[tuple[int, dict[str, list[float]]]]] = defaultdict(list)
        self.coverage: list[tuple[int, int | None]] = []
        self._dirty_gather: set[int] = set()
        self._dirty_deposit: set[int] = set()
        self._dirty_credit: set[int] = set()
        self._dirty_income: set[int] = set()
        self._seen_at: dict[int, int] = {}
        self._sites: set[int] = set()
        self.ambiguous_sites: dict[int, list[int]] = defaultdict(list)
        self._site_civs: dict[int, set[int]] = {}
        self._site_rules = self._load_sites()
        self._last_t: int | None = None
        self._built: dict[int, tuple[int, int, bool]] = {}
        self._research: dict[int, set[int]] = {}
        self._known_entities: set[int] = set()
        self.benefits = EconomyBenefits(data)
        self.exchanges: dict[int, dict[str, dict[str, Any]]] = defaultdict(dict)
        self.exchange_log: dict[int, list[tuple[int, list[dict[str, Any]]]]] = defaultdict(list)
        self._dirty_exchange: set[int] = set()

    def _market(self, events: list[dict[str, Any]]) -> dict[int, float]:
        """Keep raw transactions separate from gathered income and merged UI events."""
        sale_gold: dict[int, float] = defaultdict(float)
        for event in events:
            if event.get("kind") != "markettransaction":
                continue
            owner = int(event.get("playerid", 0) or 0)
            index = int(event.get("attributetype", 0) or 0)
            amount = float(event.get("attributeexchanged", 0) or 0)
            gold = abs(float(event.get("goldexchanged", 0) or 0))
            if owner <= 0 or index not in (0, 1, 2) or not amount or not gold:
                continue
            selling = amount < 0
            name = "Market sales" if selling else "Market purchases"
            row = self.exchanges[owner].setdefault(
                name,
                {
                    "source": name,
                    "resources": vector(),
                    "spent": vector(),
                    "count": 0,
                },
            )
            row["resources"][3 if selling else index] += gold if selling else amount
            row["spent"][index if selling else 3] += -amount if selling else gold
            row["count"] += 1
            self._dirty_exchange.add(owner)
            if selling:
                # Gold collected includes sales. Purchased food/wood/stone are
                # not in the gathering counters; do not subtract them there.
                sale_gold[owner] += gold
        return sale_gold

    def _returned_cargo(
        self,
        owner: int,
        entities: dict[int, Node],
        commands: list[dict[str, Any]],
        receipts: list[float],
    ) -> None:
        """Deleted workers return cargo; this is neither bonus income nor a camp delivery."""
        deleted = {
            int(eid)
            for command in commands
            if command.get("kind") == "deleteobjects" and command.get("playerid") == owner
            for eid in command.get("unitids", [])
        }
        loads: dict[str, list[tuple[int, float]]] = defaultdict(list)
        for eid in deleted:
            old = self.workers.get(eid)
            entity = entities.get(eid)
            if old is None or old.owner != owner or not old.resource or old.amount <= EPS:
                continue
            if entity is not None and (
                entity.fields.get(W.E_OWNER) != owner
                or entity.fields.get(W.E_STATE, 2) <= W.ENTITY_ALIVE
                or float(entity.fields.get(W.E_HELD_AMT, 0)) > EPS
            ):
                continue
            loads[old.resource].append((eid, old.amount))
        for resource, workers in loads.items():
            i = RINDEX[resource]
            amount = sum(load for _, load in workers)
            # A delete request alone proves no refund. Require the actual
            # collected-counter receipt to cover the complete returned cargo.
            if receipts[i] + EPS < amount:
                continue
            row = self.exchanges[owner].setdefault(
                "Returned cargo",
                {
                    "source": "Returned cargo",
                    "category": "return",
                    "resources": vector(),
                    "spent": vector(),
                    "count": 0,
                },
            )
            row["resources"][i] += amount
            row["count"] += len(workers)
            receipts[i] = max(0.0, receipts[i] - amount)
            self._dirty_exchange.add(owner)
            for eid, load in workers:
                self.credited[eid][i] += load
                self._dirty_credit.add(eid)

    @staticmethod
    def _relic_total(player: Node) -> float:
        attrs = player.fields.get(W.P_ATTR)
        if isinstance(attrs, Node) and W._ATTR["relicIncomeCostSummation"] in attrs.fields:
            return W.attr(player, "relicIncomeCostSummation")
        return W.vp_amount(player, W.VP_RELIC_GOLD)

    def _load_sites(self) -> dict[int, set[str]]:
        import json

        path = self.data.dat_path("dropsites.json")
        if path is None:
            return {}
        try:
            rows = json.loads(path.read_text()).get("drop_site_list", [])
            sites: dict[int, set[str]] = defaultdict(set)
            for row in rows:
                mid = int(row["building_id"])
                sites[mid].update(
                    {
                        W._HELD_RESOURCE[int(target.get("attribute_type", -1))]
                        for target in row.get("target_list", [])
                        if int(target.get("attribute_type", -1)) in W._HELD_RESOURCE
                    }
                )
                if row.get("target_civs"):
                    self._site_civs[mid] = set(row["target_civs"])
            for mid in (2558, 2560):
                sites[mid].update(sites.get(2556, set()))
            return dict(sites)
        except (OSError, ValueError, KeyError, TypeError):
            return {}

    def _credit(
        self, owner: int, source: str, resource: str, amount: float, entities: tuple[int, ...] = ()
    ) -> None:
        if amount <= EPS:
            return
        self.income[owner][source][RINDEX[resource]] += amount
        self.source_entities[owner][source].update(entities)
        self._dirty_income.add(owner)

    def sample(
        self,
        world: Node | None,
        t: int,
        events: list[dict[str, Any]],
        *,
        discontinuity: bool = False,
        handicaps: dict[int, int] | None = None,
        raw_events: list[dict[str, Any]] | None = None,
        commands: list[dict[str, Any]] | None = None,
    ) -> None:
        if world is None:
            return
        players = W.players_of(world)
        entities = W.entities_of(world)
        first = self._last_t is None
        baseline = first or discontinuity or t < (self._last_t or 0)
        sale_gold = self._market(raw_events or []) if not baseline else {}
        if first:
            self.coverage.append((t, None))
        elif discontinuity and self._last_t is not None and t > self._last_t:
            self.coverage.append((t, self._last_t))
        dt = max(0, t - (self._last_t if self._last_t is not None else t)) / 1000
        self._last_t = t
        current: dict[int, Worker] = {}
        sites: dict[int, tuple[int, set[str], float, float, float]] = {}
        candidates: dict[tuple[int, str], dict[str, set[int]]] = defaultdict(
            lambda: defaultdict(set)
        )
        resets: dict[tuple[int, str], list[tuple[int, Worker, float, int | None]]] = defaultdict(
            list
        )
        masters: dict[tuple[int, int], Node | None] = {}
        rules: dict[tuple[int, int], W.MasterRules] = {}
        done: dict[int, set[int]] = {}
        built: dict[int, tuple[int, int, bool]] = {}
        civs = {pid: int(p.fields.get(W.P_CIV, -1)) for pid, p in players.items()}
        for pid, p in players.items():
            research = p.fields.get(W.P_RESEARCH) or {}
            done[pid] = {
                tid
                for tid, rs in research.items()
                if isinstance(rs, Node) and rs.fields.get(W.R_STATE) == W.RESEARCH_DONE
            }
        # Sites first: a worker's action may no longer retain its last drop target.
        for eid, e in entities.items():
            f = e.fields
            owner = int(f.get(W.E_OWNER, 0) or 0)
            if owner <= 0 or f.get(W.E_STATE, 2) > W.ENTITY_ALIVE:
                continue
            mid = int(f.get(W.E_MASTER, -1))
            master = W.master_node(e, players)
            masters[(owner, mid)] = master
            if master is None:
                continue
            mf = master.fields
            is_building = int(mf.get(W.M_TYPE, 0)) == 80
            if is_building:
                complete = bool(f.get(W.B_BUILT, False))
                built[eid] = (owner, mid, complete)
                old_building = self._built.get(eid)
                just_built = (
                    not baseline
                    and complete
                    and old_building is not None
                    and old_building[:2] == (owner, mid)
                    and not old_building[2]
                )
                if just_built:
                    # Flag 8 storage is paid at completion directly to the
                    # stockpile, WITHOUT entering the collected counters. Read
                    # the actual owner's master, including replay/mod changes.
                    # Population storage (resource 4) is deliberately excluded.
                    source = {
                        60: "Camp construction",
                        35: "Town Center construction",
                        50: "Production-building construction",
                    }.get(civs.get(owner, -1), "Building construction")
                    for held in mf.get(W.M_HELD) or ():
                        if not isinstance(held, Node):
                            continue
                        hf = held.fields
                        index = int(hf.get(W.AV_TYPE, 0))
                        if hf.get(W._fid("AttributeValue", "flag")) == 8 and 0 <= index < 4:
                            self._credit(
                                owner, source, RES[index], float(hf.get(W.AV_AMOUNT, 0)), (eid,)
                            )
            accepted = self._site_rules.get(mid)
            if mid in self._site_civs and civs.get(owner) not in self._site_civs[mid]:
                accepted = None
            if (
                int(mf.get(W.M_CLASS, -1)) == 49
                and W.attr(players[owner], "noDropsiteFarmers") <= 0
            ):
                accepted = None
            if accepted and (not is_building or f.get(W.B_BUILT, False)):
                sites[eid] = (
                    owner,
                    accepted,
                    float(f.get(W.E_X, 0)),
                    float(f.get(W.E_Y, 0)),
                    float(mf.get(W.M_RADIUS_X, 0) or 0),
                )
                self._sites.add(eid)
            cls = int(mf.get(W.M_CLASS, -1))
            if cls in (W.CLASS_CIVILIAN, W.CLASS_FISHING_BOAT):
                action = W._action_node(e, W.E_ACTION)
                af = action.fields if action else {}
                resource = W._HELD_RESOURCE.get(int(f.get(W.E_HELD_TYPE, 0)))
                amount = max(0.0, float(f.get(W.E_HELD_AMT, 0) or 0))
                key = (owner, mid)
                if key not in rules:
                    rules[key] = W.master_rules(mf)
                # A unit's carry-bonus tasks may synthesize a secondary resource.
                bonus: dict[str, float] = defaultdict(float)
                raw_type = int(f.get(W.E_HELD_TYPE, 0))
                second_type = int(f.get(W.E_TRANSIENT_TYPE, -1))
                second_amount = float(f.get(W.E_TRANSIENT_AMT, 0) or 0)
                if second_type in W._HELD_RESOURCE and second_amount > 0 and amount > EPS:
                    bonus[W._HELD_RESOURCE[second_type]] = second_amount / amount
                elif second_type == -1:
                    for primary, multiplier, secondary, factor in rules[key].carry:
                        if (
                            multiplier == 266
                            and W.attr(players[owner], "choppingGoldProductivity") > 0
                        ):
                            continue  # Paper Money trickles while chopping, not on drop-off.
                        configured = W.CARRY_BONUS.get(civs.get(owner, -1), {}).get(multiplier)
                        if primary not in (-1, raw_type) or configured is None:
                            continue
                        value, tech = configured
                        if secondary in W._HELD_RESOURCE and (tech is None or tech in done[owner]):
                            bonus[W._HELD_RESOURCE[secondary]] += factor * value
                    old_load = self.workers.get(eid)
                    if (
                        old_load is not None
                        and old_load.owner == owner
                        and old_load.resource == resource
                        and old_load.amount > EPS
                        and amount >= old_load.amount
                    ):
                        # A forager can become a builder/farmer before delivering
                        # the berries already carried. Preserve that load's
                        # earned secondary yield; new non-foraging food dilutes
                        # it rather than erasing it or earning more bonus wood.
                        previous_bonus = dict(old_load.bonus)
                        for secondary_res in bonus.keys() | previous_bonus.keys():
                            if secondary_res == resource:
                                continue
                            bonus[secondary_res] = (
                                old_load.amount * previous_bonus.get(secondary_res, 0)
                                + (amount - old_load.amount) * bonus.get(secondary_res, 0)
                            ) / amount
                worker = Worker(
                    owner,
                    mid,
                    resource,
                    amount,
                    float(f.get(W.E_X, 0)),
                    float(f.get(W.E_Y, 0)),
                    (int(af.get(W.A_TARGET, -1)), int(af.get(TARGET2, -1))),
                    af.get(W.A_TYPE) in W._GATHER_ACTIONS and af.get(W.A_STATE) == 7,
                    "villagers" if cls == W.CLASS_CIVILIAN else "fishing",
                    tuple(bonus.items()),
                )
                current[eid] = worker
                self._seen_at.setdefault(eid, t)
                if worker.gathering:
                    target = entities.get(worker.targets[0])
                    target_master = W.master_node(target, players) if target else None
                    group = int(target_master.fields.get(W.M_CLASS, -1)) if target_master else -1
                    if (
                        civs.get(owner) == 31
                        and 629 in done[owner]
                        and worker.resource == "wood"
                        and group == W.CLASS_TREE
                        and W.attr(players[owner], "choppingGoldProductivity") > 0
                    ):
                        worker.direct_gold = "Paper Money"
                        candidates[(owner, "gold")][worker.direct_gold].add(eid)
                    if civs.get(owner) == 61 and group in (9, 10, 31, 33, 58):
                        candidates[(owner, "gold")]["Animal gathering"].add(eid)
                    if civs.get(owner) == 56 and worker.resource == "stone":
                        candidates[(owner, "food")]["Stone mining food"].add(eid)
                    if (
                        cls == W.CLASS_CIVILIAN
                        and (
                            civs.get(owner) == 28 or W.attr(players[owner], "noDropsiteFarmers") > 0
                        )
                        and group == 49
                        and amount <= EPS
                        and target is not None
                        and target.fields.get(W.E_OWNER) == owner
                        and target.fields.get(W.B_BUILT, False)
                    ):
                        worker.direct_farm = worker.targets[0]
                        candidates[(owner, "food")]["villagers"].add(eid)
            if (
                civs.get(owner) == 51
                and 1061 in done[owner]
                and cls not in W._ECO_CLASSES
                and not is_building
            ):
                candidates[(owner, "food")]["Tuntian"].add(eid)
            inside = int(f.get(W.E_INSIDE, -1) or -1)
            if civs.get(owner) == 42 and cls == 58 and inside in entities:
                candidates[(owner, "food")]["Garrisoned livestock"].add(inside)
            if (
                civs.get(owner) == 48
                and 1133 in done[owner]
                and mid in (82, 2418)
                and f.get(W.B_BUILT, False)
            ):
                candidates[(owner, "gold")]["Peloponnesian League"].add(eid)
            if mid in (826, 1647) and (not is_building or f.get(W.B_BUILT, False)):
                for res in RES:
                    candidates[(owner, res)]["Monument / Trade Workshop"].add(eid)
            # Only instantiated, completed producers; unused master tasks do not count.
            if mid == 1021 and f.get(W.B_BUILT, False):
                for resource in RES:
                    candidates[(owner, resource)]["Feitoria"].add(eid)
            action = W._action_node(e, W.E_ACTION)
            af = action.fields if action else {}
            if mid in (1228, 1230, 2703, 2704) and af.get(W.A_TYPE) in W._ATTACK_ACTIONS:
                target = entities.get(int(af.get(W.A_TARGET, -1)))
                target_master = W.master_node(target, players) if target else None
                if (
                    target is not None
                    and target_master is not None
                    and target.fields.get(W.E_OWNER) != owner
                ):
                    group = int(target_master.fields.get(W.M_CLASS, -1))
                    if group not in (3, 27, 39, 49, 52):
                        name = "Keshik" if mid in (1228, 1230) else "Varangian Gold Generation"
                        candidates[(owner, "gold")][name].add(eid)
        # Frame-correlated grants use receipts, never theoretical cost percentages.
        for event in events:
            if event.get("kind") != "kill":
                continue
            victim, killer = event.get("victim") or {}, event.get("killer") or {}
            ko, vo = int(killer.get("owner", 0)), int(victim.get("owner", 0))

            # Timeline kill events carry compact {id, owner, master} references,
            # not the kind/class fields on raw resolved objects. The victim may
            # already have disappeared from the post-patch entity collection.
            def event_master(ref: dict[str, Any]) -> dict[int, Any]:
                player = players.get(int(ref.get("owner", 0)))
                master = (
                    (player.fields.get(W.P_MASTERS) or {}).get(ref.get("master"))
                    if player
                    else None
                )
                return master.fields if isinstance(master, Node) else {}

            vm, km = event_master(victim), event_master(killer)
            victim_kind = (
                "building"
                if vm.get(W.M_TYPE) == 80
                else "unit"
                if vm.get(W.M_TYPE) == 70
                else victim.get("kind")
            )
            killer_class = km.get(W.M_CLASS, killer.get("cls"))
            if civs.get(ko) == 62 and victim_kind == "building" and not event.get("friendly"):
                for resource in RES:
                    candidates[(ko, resource)]["Building loot"].add(int(killer["id"]))
            if civs.get(vo) == 59 and victim_kind == "unit":
                for resource in RES:
                    candidates[(vo, resource)]["Fallen units"].add(int(victim["id"]))
            victim_eco = vm.get(W.M_CLASS) in W._ECO_CLASSES if vm else victim.get("eco")
            if civs.get(ko) == 58 and killer_class in (12, 36, 47) and not victim_eco:
                candidates[(ko, "gold")]["Mounted-unit kills"].add(int(killer["id"]))
            if (
                killer.get("master") in (1228, 1230, 2703, 2704)
                and victim_kind == "unit"
                and not event.get("friendly")
                and vm.get(W.M_CLASS) not in (3, 27, 39, 49, 52)
            ):
                name = "Keshik" if killer["master"] in (1228, 1230) else "Varangian Gold Generation"
                candidates[(ko, "gold")][name].add(int(killer["id"]))
        for eid, worker in current.items():
            old = self.workers.get(eid)
            if baseline or old is None or old.owner != worker.owner:
                continue
            if old.direct_gold and not worker.direct_gold and dt <= 2:
                candidates[(worker.owner, "gold")][old.direct_gold].add(eid)
            if (
                old.direct_farm is not None
                and worker.direct_farm is None
                and dt <= 2
                and worker.amount <= EPS
            ):
                farm = entities.get(old.direct_farm)
                if farm is not None and farm.fields.get(W.E_OWNER) == worker.owner:
                    # Include the final credit when a farmer stops this frame,
                    # but never retain it into subsequent idle frames.
                    candidates[(worker.owner, "food")]["villagers"].add(eid)
            if worker.resource == old.resource and worker.amount >= old.amount:
                if worker.resource and (worker.gathering or old.gathering):
                    self.collected[eid][RINDEX[worker.resource]] += worker.amount - old.amount
                    self._dirty_gather.add(eid)
            elif old.resource and old.amount > EPS:
                site = self._recipient(old, worker, sites)
                # Reset alone can mean death, conversion or resource switching.
                # A nearby real recipient is required before calling it a drop-off.
                resets[(worker.owner, old.resource)].append((eid, old, old.amount, site))
                if worker.gathering and worker.resource:
                    self.collected[eid][RINDEX[worker.resource]] += worker.amount
                    self._dirty_gather.add(eid)
        for pid, p in players.items():
            if pid <= 0:
                continue
            if not baseline:
                completed = done[pid] - self._research.get(pid, done[pid])
                # These automatic bonus technologies are the executed grant,
                # not an assumption from current age or an unspent balance.
                # Include the additional starting-age grant used by Empire Wars.
                if civs.get(pid) == 40:
                    count = len(completed & {851, 852, 853, 872})
                    self._credit(pid, "Age advancement", "wood", 200 * count)
                elif civs.get(pid) == 25:
                    count = len(completed & {587, 588, 589, 871})
                    for res in ("food", "gold"):
                        self._credit(pid, "Age advancement", res, 100 * count)
                elif civs.get(pid) == 14:
                    # Hidden/automatic technologies and ages do not trigger the
                    # Spanish research reward. Use actual research notifications.
                    researched = {
                        int(e.get("tech", -1))
                        for e in events
                        if e.get("kind") == "researched" and e.get("player") == pid
                    } - set(W.AGE_TECHS)
                    self._credit(pid, "Technology research", "gold", 20 * len(researched - {-1}))
            totals = [W.attr(p, r + "Total") for r in RES]
            relic = self._relic_total(p)
            trade = [
                float(p.fields.get(W._fid("Player", f"trade{r.title()}Received"), 0) or 0)
                for r in RES
            ]
            previous = self.players.get(pid)
            if previous is not None and not baseline:
                relic = max(relic, previous[1])
            self.players[pid] = (totals, relic, trade)
            if baseline or previous is None:
                continue
            receipts = [max(0.0, totals[i] - previous[0][i]) for i in range(4)]
            relic_delta = max(0.0, relic - previous[1])
            trade_delta = [max(0.0, trade[i] - previous[2][i]) for i in range(4)]
            self._credit(pid, "Relics", "gold", relic_delta)
            receipts = [max(0.0, receipts[i] - trade_delta[i]) for i in range(4)]
            receipts[3] = max(0.0, receipts[3] - relic_delta)
            receipts[3] = max(0.0, receipts[3] - sale_gold.get(pid, 0))
            self._returned_cargo(pid, entities, commands or [], receipts)
            for i, res in enumerate(RES):
                if res != "gold":
                    self._credit(pid, "Trade bonus", res, trade_delta[i])
            for resource in RES:
                i = RINDEX[resource]
                drops = resets.get((pid, resource), [])
                available = receipts[i]
                if drops and available > EPS:
                    # Recover the unobserved tail of one load from the game's
                    # actual receipt. Multiple simultaneous loads are proportional
                    # estimates. Refuse large unexplained windfalls.
                    expected = sum(
                        amount * (1 + dict(w.bonus).get(resource, 0)) for _, w, amount, _ in drops
                    )
                    ceiling = expected + len(drops) * max(1.0, dt * 3)
                    credit = available if available <= ceiling else min(available, expected)
                    for eid, old, amount, site in drops:
                        ratio = 1 + dict(old.bonus).get(resource, 0)
                        paid = credit * amount * ratio / expected
                        base = paid / ratio
                        self.credited[eid][i] += paid
                        self._dirty_credit.add(eid)
                        # Carry increments already counted before this deposit.
                        tail = max(0.0, base - amount)
                        self.collected[eid][i] += tail
                        self._dirty_gather.add(eid)
                        # Exact camp credit is possible only for an unambiguous
                        # recipient and no simultaneous non-worker source. Do not
                        # split a player's actual receipt between guessed camps.
                        certain_site = (
                            site is not None
                            and all(d[3] == site for d in drops)
                            and not candidates.get((pid, resource))
                            and available <= ceiling
                        )
                        if certain_site and site is not None:
                            self.delivered[site][i] += paid
                            self._dirty_deposit.add(site)
                        elif site is not None:
                            self.ambiguous_sites[site].append(t)
                        else:
                            for possible_site, site_info in sites.items():
                                if (
                                    self._recipient(old, current[eid], {possible_site: site_info})
                                    is not None
                                ):
                                    log = self.ambiguous_sites[possible_site]
                                    if not log or log[-1] != t:
                                        log.append(t)
                        extra = paid - base
                        self._credit(pid, old.kind, resource, base, (eid,))
                        self._credit(pid, f"Extra {resource} drop-off", resource, extra, (eid,))
                        for secondary_res, fraction in old.bonus:
                            if secondary_res == resource:
                                continue
                            secondary_credit = min(receipts[RINDEX[secondary_res]], base * fraction)
                            source = {
                                24: "Foraging wood",
                                31: "Paper Money",
                                36: "Burgundian Vineyards",
                                38: "Stone mining gold",
                                47: "Lumberjack food",
                                49: "Lumberjack food",
                                55: "Animal gathering",
                                56: "Stone mining food",
                                61: "Animal gathering",
                            }.get(civs.get(pid, -1), "Secondary gathering")
                            self._credit(pid, source, secondary_res, secondary_credit, (eid,))
                            # The last gather tick between frames can change
                            # the secondary/primary ratio of a mixed load. Keep
                            # its proven delivery source eligible for the tail
                            # after ordinary deliveries have been reconciled.
                            candidates[(pid, secondary_res)][source].add(eid)
                            if certain_site and site is not None:
                                self.delivered[site][RINDEX[secondary_res]] += secondary_credit
                            self.credited[eid][RINDEX[secondary_res]] += secondary_credit
                            receipts[RINDEX[secondary_res]] -= secondary_credit
                    receipts[i] = max(0.0, available - credit)
            for resource in RES:
                i = RINDEX[resource]
                remaining = receipts[i]
                possible = candidates.get((pid, resource), {})
                if remaining > EPS:
                    if len(possible) == 1:
                        source, ids = next(iter(possible.items()))
                        self._credit(pid, source, resource, remaining, tuple(ids))
                        if source == "villagers" and resource == "food":
                            # The receipt is observed; each farmer's share is an
                            # estimate. Direct farming is credited immediately,
                            # never to a nearby camp or a fictitious carried load.
                            for eid in ids:
                                self.collected[eid][i] += remaining / len(ids)
                                self.credited[eid][i] += remaining / len(ids)
                                self._dirty_gather.add(eid)
                                self._dirty_credit.add(eid)
                        elif source in {
                            "Foraging wood",
                            "Paper Money",
                            "Burgundian Vineyards",
                            "Stone mining gold",
                            "Lumberjack food",
                            "Animal gathering",
                            "Stone mining food",
                            "Secondary gathering",
                        }:
                            for eid in ids:
                                if eid in current:
                                    self.credited[eid][i] += remaining / len(ids)
                                    self._dirty_credit.add(eid)
                    else:
                        self._credit(pid, "Unattributed", resource, remaining)
        self.benefits.sample(
            world,
            events,
            handicaps=handicaps,
            baseline=baseline,
            collected=self.collected,
            changed_collected=self._dirty_gather,
            workers=current,
            done=done,
            previous_done=self._research,
            built=built,
            previous_built=self._built,
            new_workers={
                eid: worker
                for eid, worker in current.items()
                if not baseline
                and eid not in self._known_entities
                and eid
                not in {
                    int(e.get("objid", -1))
                    for e in raw_events or []
                    if e.get("kind") == "notificationtraindone"
                }
            },
        )
        self.workers = current
        self._built = built
        self._research = done
        self._known_entities.update(entities)

    @staticmethod
    def _recipient(
        old: Worker, current: Worker, sites: dict[int, tuple[int, set[str], float, float, float]]
    ) -> int | None:
        def accepts(eid: int) -> bool:
            site = sites.get(eid)
            return bool(
                site
                and site[0] == old.owner
                and old.resource in site[1]
                and min(hypot(w.x - site[2], w.y - site[3]) for w in (old, current))
                <= site[4] * 1.42 + 1.25
            )

        explicit = {eid for eid in (*old.targets, *current.targets) if accepts(eid)}
        if len(explicit) == 1:
            return next(iter(explicit))
        nearby = [eid for eid in sites if accepts(eid)]
        return nearby[0] if len(nearby) == 1 else None

    def checkpoint(self, t: int) -> None:
        self.benefits.checkpoint(t)
        for dirty, values, log in (
            (self._dirty_gather, self.collected, self.gather_log),
            (self._dirty_deposit, self.delivered, self.deposit_log),
            (self._dirty_credit, self.credited, self.credit_log),
        ):
            for eid in dirty:
                log[eid].append((t, list(values[eid])))
            dirty.clear()
        for owner in self._dirty_income:
            self.source_log[owner].append((t, {k: list(v) for k, v in self.income[owner].items()}))
        self._dirty_income.clear()
        for owner in self._dirty_exchange:
            self.exchange_log[owner].append(
                (
                    t,
                    [
                        {**row, "resources": list(row["resources"]), "spent": list(row["spent"])}
                        for row in self.exchanges[owner].values()
                    ],
                )
            )
        self._dirty_exchange.clear()

    #: The logs entity() and player() read. The playback index stores them
    #: (query_state) and a read-only timeline restores them without replaying frames.
    QUERY_LOGS = (
        "gather_log",
        "deposit_log",
        "credit_log",
        "source_log",
        "exchange_log",
        "ambiguous_sites",
    )

    def query_state(self) -> dict[str, Any]:
        state: dict[str, Any] = {name: getattr(self, name) for name in self.QUERY_LOGS}
        state["sites"] = self._sites
        state["coverage"] = self.coverage
        state["benefit_logs"] = self.benefits.logs
        return state

    def restore_query_state(self, state: dict[str, Any]) -> None:
        for name in self.QUERY_LOGS:
            setattr(self, name, defaultdict(list, state[name]))
        self._sites = set(state["sites"])
        self.coverage = [tuple(row) for row in state["coverage"]]
        self.benefits.logs = defaultdict(list, state["benefit_logs"])

    @staticmethod
    def _at(log: list[Any], t: int, default: Any) -> Any:
        i = bisect_right(log, t, key=lambda row: row[0]) - 1
        return log[i][1] if i >= 0 else default

    def entity(self, eid: int, t: int) -> dict[str, Any]:
        return {
            "collected": resource_dict(self._at(self.gather_log.get(eid, []), t, vector())),
            "dropped_off": resource_dict(self._at(self.deposit_log.get(eid, []), t, vector())),
            "credited": resource_dict(self._at(self.credit_log.get(eid, []), t, vector())),
            "is_drop_site": eid in self._sites,
            "estimated": True,
            "observed_from_ms": self.coverage[0][0] if self.coverage else None,
            "has_gaps": any(start <= t for start, _ in self.coverage[1:]),
            "ambiguous_dropoffs": bisect_right(self.ambiguous_sites.get(eid, []), t),
        }

    def player(self, owner: int, t: int) -> dict[str, Any]:
        sources = self._at(self.source_log.get(owner, []), t, {})
        bonus = vector()
        rows = []
        for name, values in sources.items():
            category = (
                "regular"
                if name in ("villagers", "fishing")
                else "unattributed"
                if name == "Unattributed"
                else "bonus"
            )
            if category == "bonus":
                bonus = [a + b for a, b in zip(bonus, values, strict=True)]
            rows.append(
                {
                    "source": name,
                    "category": category,
                    "resources": resource_dict(values),
                    "total": round(sum(values), 1),
                    "estimated": name != "Relics",
                }
            )
        return {
            "sources": rows,
            "exchanges": [
                {
                    **row,
                    "category": row.get("category", "exchange"),
                    "resources": resource_dict(row["resources"]),
                    "spent": resource_dict(row["spent"]),
                    "total": round(sum(row["resources"]), 1),
                    "estimated": row.get("category") == "return",
                }
                for row in self._at(self.exchange_log.get(owner, []), t, [])
            ],
            **self.benefits.player(owner, t),
            "bonus": resource_dict(bonus),
            "total": round(sum(bonus), 1),
            "observed_from_ms": self.coverage[0][0] if self.coverage else None,
            "has_gaps": any(start <= t for start, _ in self.coverage[1:]),
        }
