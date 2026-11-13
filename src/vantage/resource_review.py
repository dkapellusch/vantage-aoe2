"""Observed resource history, with conservative, explicit income attribution.

Every resource a player receives is in exactly one of these (docs/resources.md):

* **Collected**: gathered by villagers and fishing ships. The game's
  ``<resource>Total`` counters minus everything below that those counters
  also include.
* **Bonus**: civilization, technology and event grants. Some arrive inside
  the counters (relics, kill rewards, trickles, Folwark), some are paid
  straight into the stockpile (age-up grants, building completion grants,
  the starting bonus).
* **Trade** and **Market / Tribute**: trade profit and exchanges.
* **Starting**: the stockpile at the start, split into the lobby's starting
  resources and the civilization's starting bonus (which is listed in Bonus).

Whatever the stockpile then still gains or loses is spending, a refund
(cancelled or lost queues and foundations) or, when nothing explains it,
an "Unexplained gain" row: a missing source stays visible.

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
from vantage.farms import FarmHistory
from vantage.patch import Node

RES = ("food", "wood", "stone", "gold")
RINDEX = {r: i for i, r in enumerate(RES)}
TARGET2 = W._fid("Action", "target2Id")
EPS = 0.001
FLAG = W._fid("AttributeValue", "flag")
STARTING_BONUS = "Starting bonus"
UNEXPLAINED = "Unexplained gain"
#: Grants paid straight into the stockpile: the game's collected counters
#: (``foodTotal`` ...) never see them. Building completion grants are too.
DIRECT_SOURCES = frozenset({"Age advancement", "Technology research", STARTING_BONUS})
#: A recording that begins later than this has no observed starting stockpile.
START_WINDOW_MS = 5000
#: Stockpile changes below this are float noise, not a flow.
FLOW_EPS = 0.05
#: Frames (about half a second each) a refund may trail its cause by.
REFUND_FRAMES = 3
#: Commands after which the game hands resources back.
REFUND_COMMANDS = frozenset(
    {"cancelbuild", "unitorder", "resign", "deleteobjects", "buildingcommandqueue"}
)
#: The hidden Town Center annex that carries the Lithuanian +100 food.
TC_FOOD_ANNEX = 888
LITHUANIANS = 35
FLOWS = ("spent", "refunds", "unexplained", "direct", "not_gathered", "trade")


def is_direct(source: str) -> bool:
    """True for a source the collected counters do not include."""
    return source in DIRECT_SOURCES or source.endswith("construction")


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
        self.farms = FarmHistory()
        #: Per player: cumulative vectors named in FLOWS. ``direct`` is what was
        #: paid past the counters, ``not_gathered`` what the counters include
        #: that no worker gathered; the rest is the stockpile's other movement.
        self.flows: dict[int, dict[str, list[float]]] = defaultdict(
            lambda: {name: vector() for name in FLOWS}
        )
        self.flow_log: dict[int, list[tuple[int, dict[str, list[float]]]]] = defaultdict(list)
        self._dirty_flow: set[int] = set()
        #: Per player: the observed starting stockpile and the civilization's share.
        self.start: dict[int, dict[str, list[float]]] = {}
        self._frame_direct: dict[int, list[float]] = defaultdict(vector)
        self._starting_attrs: dict[int, list[float]] = {}
        self._researching: dict[int, set[int]] = {}
        self._refund_evidence: list[set[int]] = []
        self._market_legs: dict[int, list[float]] = defaultdict(vector)
        self.exchanges: dict[int, dict[str, dict[str, Any]]] = defaultdict(dict)
        self.exchange_log: dict[int, list[tuple[int, list[dict[str, Any]]]]] = defaultdict(list)
        self._dirty_exchange: set[int] = set()

    @property
    def direct(self) -> dict[int, list[float]]:
        """Per player, everything credited so far that bypassed the counters."""
        return {owner: flows["direct"] for owner, flows in self.flows.items()}

    def _flow(self, owner: int, name: str, index: int, amount: float) -> None:
        self.flows[owner][name][index] += amount
        self._dirty_flow.add(owner)

    def _tribute(self, events: list[dict[str, Any]]) -> dict[int, list[float]]:
        """Tribute rows; returns what each player received, per resource."""
        received: dict[int, list[float]] = defaultdict(vector)
        for event in events:
            if event.get("kind") != "tribute":
                continue
            index = int(event.get("attributetype", 0) or 0)
            if not 0 <= index < 4:
                continue
            sent = abs(float(event.get("sendervaluechange", 0) or 0))
            got = abs(float(event.get("receivervaluechange", 0) or 0))
            for owner, name, amount, column in (
                (int(event.get("senderid", 0) or 0), "Tribute sent", sent, "spent"),
                (int(event.get("receiverid", 0) or 0), "Tribute received", got, "resources"),
            ):
                if owner <= 0 or amount <= 0:
                    continue
                row = self.exchanges[owner].setdefault(
                    name,
                    {
                        "source": name,
                        "category": "tribute",
                        "resources": vector(),
                        "spent": vector(),
                        "count": 0,
                    },
                )
                row[column][index] += amount
                row["count"] += 1
                self._dirty_exchange.add(owner)
                if column == "resources":
                    received[owner][index] += amount
                else:
                    self._market_legs[owner][index] -= amount
        return received

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
            # The stockpile moves the collected counters do not show: both
            # legs of a purchase, and the resource a sale gives away.
            self._market_legs[owner][index] += amount
            if selling:
                # Gold collected includes sales. Purchased food/wood/stone are
                # not in the gathering counters; do not subtract them there.
                sale_gold[owner] += gold
            else:
                self._market_legs[owner][3] -= gold
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
        index = RINDEX[resource]
        self.income[owner][source][index] += amount
        self.source_entities[owner][source].update(entities)
        self._dirty_income.add(owner)
        if is_direct(source):
            self._frame_direct[owner][index] += amount
            self._flow(owner, "direct", index, amount)
        elif source not in ("villagers", "fishing", "Unattributed", UNEXPLAINED):
            # Inside the game's collected counter, but no worker gathered it.
            self._flow(owner, "not_gathered", index, amount)

    @staticmethod
    def _completion_storage(master: Node | None) -> list[float]:
        """Resources a building's master pays on completion (storage flag 8)."""
        out = vector()
        if master is None:
            return out
        for held in master.fields.get(W.M_HELD) or ():
            if not isinstance(held, Node):
                continue
            index = int(held.fields.get(W.AV_TYPE, 0))
            if held.fields.get(FLAG) == 8 and 0 <= index < 4:
                out[index] += float(held.fields.get(W.AV_AMOUNT, 0))
        return out

    def _observe_start(self, players: dict[int, Node], entities: dict[int, Node], t: int) -> None:
        """Split each starting stockpile into the lobby's share and the civilization's.

        The civilization's share is what the game itself records: the
        ``starting<Resource>`` attributes (Persians +50 food and wood, Chinese
        -200 food ...), and the Lithuanian +100 food of the starting Town
        Center's annex. The annex share is kept only when it makes the players'
        lobby shares agree at least as well as leaving it out does.
        """
        stock = {
            pid: [W.attr(p, r) for r in RES] for pid, p in players.items() if pid > 0
        }
        attrs = {
            pid: [W.attr(p, "starting" + r.title()) for r in RES]
            for pid, p in players.items()
            if pid > 0
        }
        self._starting_attrs = {pid: list(values) for pid, values in attrs.items()}
        if t > START_WINDOW_MS:
            return
        annex = {pid: vector() for pid in stock}
        for e in entities.values():
            owner = int(e.fields.get(W.E_OWNER, 0) or 0)
            if (
                owner in annex
                and int(players[owner].fields.get(W.P_CIV, -1)) == LITHUANIANS
                and int(e.fields.get(W.E_MASTER, -1)) in W.TOWN_CENTER_MASTERS
                and e.fields.get(W.B_BUILT, False)
            ):
                grant = self._completion_storage(
                    (players[owner].fields.get(W.P_MASTERS) or {}).get(TC_FOOD_ANNEX)
                )
                annex[owner] = [a + b for a, b in zip(annex[owner], grant, strict=True)]

        def spread(with_annex: bool) -> float:
            return sum(
                max(values) - min(values)
                for values in zip(
                    *(
                        [
                            stock[pid][i] - attrs[pid][i] - (annex[pid][i] if with_annex else 0)
                            for i in range(4)
                        ]
                        for pid in stock
                    ),
                    strict=True,
                )
            )

        use_annex = bool(stock) and spread(True) <= spread(False) + EPS
        for pid in stock:
            bonus = [
                attrs[pid][i] + (annex[pid][i] if use_annex else 0) for i in range(4)
            ]
            self.start[pid] = {"stock": stock[pid], "bonus": bonus}
            if any(abs(value) > EPS for value in bonus):
                # Already inside the starting stockpile: a Bonus row, not a flow.
                self.income[pid][STARTING_BONUS] = list(bonus)
                self._dirty_income.add(pid)

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
        owned: dict[int, Node] | None = None,
    ) -> None:
        if world is None:
            return
        players = W.players_of(world)
        entities = W.entities_of(world)
        first = self._last_t is None
        baseline = first or discontinuity or t < (self._last_t or 0)
        self._market_legs = defaultdict(vector)
        self._frame_direct = defaultdict(vector)
        sale_gold = self._market(raw_events or []) if not baseline else {}
        tribute_in = self._tribute(raw_events or []) if not baseline else {}
        if first:
            self._observe_start(players, entities, t)
        if baseline:
            self._refund_evidence = []
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
        farm_grants = self.farms.sample(world, t, baseline=baseline, owned=owned)
        farm_receipts = {
            pid: max(0.0, W.attr(p, "foodTotal") - self.players[pid][0][0])
            for pid, p in players.items()
            if pid in self.players and not baseline
        }
        before_grants = len(self.farms.grants)
        self.farms.confirm(farm_grants, farm_receipts)
        confirmed = self.farms.grants[before_grants:]
        for grant in confirmed:
            self._credit(grant["owner"], "Poles Folwark bonus food", "food", grant["food"])
        done: dict[int, set[int]] = {}
        built: dict[int, tuple[int, int, bool]] = {}
        civs = {pid: int(p.fields.get(W.P_CIV, -1)) for pid, p in players.items()}
        #: Players the game may be refunding this frame (see REFUND_COMMANDS).
        evidence: set[int] = set()
        #: Lithuanian Town Centers that appeared finished this frame.
        annex_grants: dict[int, list[float]] = defaultdict(vector)
        researching: dict[int, set[int]] = {}
        for pid, p in players.items():
            research = p.fields.get(W.P_RESEARCH) or {}
            done[pid] = {
                tid
                for tid, rs in research.items()
                if isinstance(rs, Node) and rs.fields.get(W.R_STATE) == W.RESEARCH_DONE
            }
            researching[pid] = {
                tid
                for tid, rs in research.items()
                if isinstance(rs, Node) and rs.fields.get(W.R_STATE) == 2
            }
            if self._researching.get(pid, set()) - researching[pid] - done[pid]:
                evidence.add(pid)  # a cancelled research is refunded
        self._researching = researching
        # Sites first: a worker's action may no longer retain its last drop target.
        for eid, e in (entities if owned is None else owned).items():
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
                if (
                    not baseline
                    and complete
                    and old_building is None
                    and eid not in self._known_entities
                    and mid in W.TOWN_CENTER_MASTERS
                    and civs.get(owner) == LITHUANIANS
                ):
                    # A finished Town Center replaces its foundation as a new
                    # object; its hidden annex pays the grant.
                    grant = self._completion_storage(
                        (players[owner].fields.get(W.P_MASTERS) or {}).get(TC_FOOD_ANNEX)
                    )
                    annex_grants[owner] = [
                        a + b for a, b in zip(annex_grants[owner], grant, strict=True)
                    ]
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
        if not baseline:
            finished = {
                owner
                for eid, (owner, _, complete) in built.items()
                if complete and eid not in self._built
            }
            for eid, (owner, _, complete) in self._built.items():
                # A lost building or foundation refunds its queue or its cost. A
                # Town Center foundation is instead replaced by the finished one.
                if eid not in built and (complete or owner not in finished):
                    evidence.add(owner)
            for command in commands or ():
                if command.get("kind") not in REFUND_COMMANDS:
                    continue
                for key in ("playerid", "unitplayerid", "commplayerid"):
                    if isinstance(command.get(key), int):
                        evidence.add(int(command[key]))
                for eid in (
                    command.get("targetid"),
                    command.get("unitid"),
                    *(command.get("unitids") or ()),
                ):
                    if eid in self._built:
                        evidence.add(self._built[eid][0])
            self._refund_evidence = [*self._refund_evidence[-(REFUND_FRAMES - 1) :], evidence]
        refundable = set().union(*self._refund_evidence) if self._refund_evidence else set()
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
            stock = [W.attr(p, r) for r in RES]
            starting = [W.attr(p, "starting" + r.title()) for r in RES]
            old_starting = self._starting_attrs.get(pid, starting)
            self._starting_attrs[pid] = starting
            self.players[pid] = (totals, relic, trade, stock)
            if baseline or previous is None:
                continue
            receipts = [max(0.0, totals[i] - previous[0][i]) for i in range(4)]
            # What the stockpile gained beyond the collected counters and the
            # market: grants paid directly, refunds, minus whatever was spent.
            gain = [
                stock[i]
                - previous[3][i]
                - (totals[i] - previous[0][i])
                - self._market_legs[pid][i]
                - self._frame_direct[pid][i]
                for i in range(4)
            ]
            for i, res in enumerate(RES):
                # Receipt-gated grants: credited only when the stockpile shows them.
                # A civilization's starting bonus that arrives with the first
                # Town Center (Nomad starts) raises its starting attribute.
                for source, amount in (
                    (STARTING_BONUS, starting[i] - old_starting[i]),
                    ("Town Center construction", annex_grants[pid][i]),
                ):
                    if amount > EPS and gain[i] + FLOW_EPS >= amount:
                        self._credit(pid, source, res, amount)
                        gain[i] -= amount
                got = tribute_in.get(pid, vector())[i]
                if got > EPS:
                    direct = min(got, max(0.0, gain[i]))
                    gain[i] -= direct
                    counted = min(got - direct, receipts[i])
                    receipts[i] -= counted
                    self._flow(pid, "not_gathered", i, counted)
                if gain[i] < -FLOW_EPS:
                    self._flow(pid, "spent", i, -gain[i])
                elif gain[i] > FLOW_EPS and pid in refundable:
                    self._flow(pid, "refunds", i, gain[i])
                elif gain[i] > FLOW_EPS:
                    self._flow(pid, "unexplained", i, gain[i])
                    self._credit(pid, UNEXPLAINED, res, gain[i])
            # Folwark grants enter foodTotal but are not villager gathering.
            receipts[0] = max(
                0.0, receipts[0] - sum(g["food"] for g in confirmed if g["owner"] == pid)
            )
            relic_delta = max(0.0, relic - previous[1])
            trade_delta = [max(0.0, trade[i] - previous[2][i]) for i in range(4)]
            self._credit(pid, "Relics", "gold", relic_delta)
            for i in range(4):
                self._flow(pid, "trade", i, min(receipts[i], trade_delta[i]))
            # Trade gold and sale gold are in goldTotal; neither is gathered.
            self._flow(pid, "not_gathered", 3, min(receipts[3], trade_delta[3]))
            receipts = [max(0.0, receipts[i] - trade_delta[i]) for i in range(4)]
            receipts[3] = max(0.0, receipts[3] - relic_delta)
            self._flow(pid, "not_gathered", 3, min(receipts[3], sale_gold.get(pid, 0)))
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
        for owner in self._dirty_flow:
            self.flow_log[owner].append(
                (t, {name: list(values) for name, values in self.flows[owner].items()})
            )
        self._dirty_flow.clear()

    #: The logs entity() and player() read. The playback index stores them
    #: (query_state) and a read-only timeline restores them without replaying frames.
    QUERY_LOGS = (
        "gather_log",
        "deposit_log",
        "credit_log",
        "source_log",
        "exchange_log",
        "flow_log",
        "ambiguous_sites",
    )

    def query_state(self) -> dict[str, Any]:
        state: dict[str, Any] = {name: getattr(self, name) for name in self.QUERY_LOGS}
        state["sites"] = self._sites
        state["coverage"] = self.coverage
        state["benefit_logs"] = self.benefits.logs
        state["start"] = self.start
        state["farm_history"] = {
            "rules": self.farms.rules,
            "farms": self.farms.farms,
            "grants": self.farms.grants,
        }
        return state

    def restore_query_state(self, state: dict[str, Any]) -> None:
        for name in self.QUERY_LOGS:
            setattr(self, name, defaultdict(list, state.get(name, {})))
        self.start = dict(state.get("start", {}))
        self._sites = set(state["sites"])
        self.coverage = [tuple(row) for row in state["coverage"]]
        self.benefits.logs = defaultdict(list, state["benefit_logs"])
        farm_state = state.get("farm_history", {})
        self.farms.rules = defaultdict(list, farm_state.get("rules", {}))
        self.farms.farms = defaultdict(list, farm_state.get("farms", {}))
        self.farms.grants = farm_state.get("grants", [])

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
                else "unexplained"
                if name == UNEXPLAINED
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
                    "estimated": name not in ("Relics", STARTING_BONUS, UNEXPLAINED),
                }
            )
        exchanges = self._at(self.exchange_log.get(owner, []), t, [])
        flows = self._at(self.flow_log.get(owner, []), t, {})
        start = self.start.get(owner)
        start_bonus = start["bonus"] if start else vector()

        def flow(name: str) -> list[float]:
            return list(flows.get(name, vector()))

        def moved(column: str, *categories: str) -> list[float]:
            return [
                sum(
                    row[column][i]
                    for row in exchanges
                    if row.get("category", "exchange") in categories
                )
                for i in range(4)
            ]

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
                for row in exchanges
            ],
            **self.benefits.player(owner, t),
            "bonus": resource_dict(bonus),
            "total": round(sum(bonus), 1),
            # The starting stockpile: the lobby's resources plus the
            # civilization's starting bonus (also a Bonus row). None when the
            # recording does not begin at the start of the game.
            "starting": resource_dict(
                [a - b for a, b in zip(start["stock"], start_bonus, strict=True)]
            )
            if start
            else None,
            "starting_bonus": resource_dict(start_bonus),
            "trade": resource_dict(flow("trade")),
            # Inside the game's collected counters without being gathered:
            # Collected = counter - not_gathered (see timeline._keyframe).
            "not_gathered": resource_dict(flow("not_gathered")),
            "market_in": resource_dict(moved("resources", "exchange")),
            "market_out": resource_dict(moved("spent", "exchange")),
            "tribute_in": resource_dict(moved("resources", "tribute")),
            "tribute_out": resource_dict(moved("spent", "tribute")),
            "spent": resource_dict(flow("spent")),
            "refunds": resource_dict(flow("refunds")),
            "unexplained": resource_dict(flow("unexplained")),
            "observed_from_ms": self.coverage[0][0] if self.coverage else None,
            "has_gaps": any(start <= t for start, _ in self.coverage[1:]),
        }
