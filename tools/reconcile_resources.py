"""Reconcile the viewer's resource accounting with a recording's stockpiles.

For each player and resource, at several game times::

    stockpile = starting stockpile + collected + bonus + trade + market bought
                + refunds - spent

The stream has no spending counter, so this tool builds its own ground truth
from every frame, independently of :mod:`vantage.resource_review`:

* ``counter``: the game's ``<resource>Total`` attributes (all income the game
  itself counts: gathering, relics, trade, kill rewards, trickles ...).
* a stockpile change the counter does not explain is, per frame, a market
  transaction (events), a direct grant the viewer credited in that frame (a
  grant that bypasses the counters, such as an age-up bonus), a refund (a
  cancel/delete/resign command, a lost building or a cancelled research by
  that player within about a second), spending (any decrease), or else an
  **unexplained** increase.
* a direct grant the viewer credited without the stockpile rising by as much,
  in a frame where the player bought nothing, is **unsupported**.

``residual = ground-truth income - income the viewer reports``, where the
ground truth is counter + supported direct grants + unexplained increases +
market purchases. Positive: a source the viewer misses. Negative: something
counted twice or credited without a receipt.

Run from a checkout, also an older one (keys it lacks read as absent)::

    uv run python tools/reconcile_resources.py RECORDING.vrec [--every 300] [--json OUT]
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict, deque
from pathlib import Path
from typing import Any

from vantage import world as W
from vantage.frames import read_frames
from vantage.gamedata import GameData, find_game_dir
from vantage.patch import Node
from vantage.timeline import Timeline, _decode_raw_command

RES = ("food", "wood", "stone", "gold")
EPS = 0.05
REFUND_COMMANDS = {"cancelbuild", "unitorder", "resign", "deleteobjects", "buildingcommandqueue"}
PURCHASE_COMMANDS = {"multiqueue", "build", "buildwall", "research", "buycommodity", "repair"}
#: Sources an older checkout pays straight into the stockpile (no counter).
LEGACY_DIRECT = {"Age advancement", "Technology research"}
#: Frames (about half a second each) a refund may trail its cause by.
REFUND_WINDOW = 3


def vec() -> list[float]:
    return [0.0] * 4


class GroundTruth:
    """Frame-by-frame classification of every stockpile change."""

    def __init__(self) -> None:
        self.prev: dict[int, tuple[list[float], list[float]]] = {}
        self.start: dict[int, list[float]] = {}
        self.counter: dict[int, list[float]] = defaultdict(vec)
        self.direct: dict[int, list[float]] = defaultdict(vec)
        self.unexplained: dict[int, list[float]] = defaultdict(vec)
        self.refunds: dict[int, list[float]] = defaultdict(vec)
        self.spent: dict[int, list[float]] = defaultdict(vec)
        self.market_in: dict[int, list[float]] = defaultdict(vec)
        self.market_out: dict[int, list[float]] = defaultdict(vec)
        self.unsupported: dict[int, list[float]] = defaultdict(vec)
        self.grants: list[dict[str, Any]] = []
        self._claimed: dict[int, list[float]] = defaultdict(vec)
        self._buildings: dict[int, tuple[int, int, bool, float, float]] = {}
        self._research: dict[int, set[int]] = {}
        self._evidence: deque[set[int]] = deque(maxlen=REFUND_WINDOW)

    def sample(
        self,
        world: Node,
        t: int,
        events: list[dict],
        commands: list[dict],
        claimed_direct: dict[int, list[float]],
    ) -> None:
        players = W.players_of(world)
        entities = W.entities_of(world)
        evidence: set[int] = set()
        buildings: dict[int, tuple[int, int, bool, float, float]] = {}
        for eid, e in entities.items():
            owner = int(e.fields.get(W.E_OWNER, 0) or 0)
            if owner <= 0:
                continue
            master = W.master_node(e, players)
            if master is not None and int(master.fields.get(W.M_TYPE, 0)) == 80:
                buildings[eid] = (
                    owner,
                    int(e.fields.get(W.E_STATE, 2)),
                    bool(e.fields.get(W.B_BUILT, False)),
                    float(e.fields.get(W.E_X, 0)),
                    float(e.fields.get(W.E_Y, 0)),
                )
        finished = [b for eid, b in buildings.items() if eid not in self._buildings and b[2]]
        for eid, (owner, state, built, x, y) in self._buildings.items():
            now = buildings.get(eid)
            if now is not None and not (now[1] > W.ENTITY_ALIVE >= state):
                continue
            # A Town Center foundation is replaced by a new, finished building.
            replaced = not built and any(
                b[0] == owner and abs(b[3] - x) < 1 and abs(b[4] - y) < 1 for b in finished
            )
            if not replaced:
                evidence.add(owner)
        self._buildings = buildings
        for c in commands:
            if c.get("kind") not in REFUND_COMMANDS:
                continue
            for key in ("playerid", "unitplayerid", "commplayerid"):
                if isinstance(c.get(key), int):
                    evidence.add(int(c[key]))
            for eid in (c.get("targetid"), c.get("unitid"), *(c.get("unitids") or ())):
                if eid in buildings:
                    evidence.add(buildings[eid][0])
        research: dict[int, set[int]] = {}
        for pid, p in players.items():
            states = p.fields.get(W.P_RESEARCH) or {}
            research[pid] = {
                tid
                for tid, rs in states.items()
                if isinstance(rs, Node) and rs.fields.get(W.R_STATE) == 2
            }
            for tid in self._research.get(pid, set()) - research[pid]:
                rs = states.get(tid)
                if not isinstance(rs, Node) or rs.fields.get(W.R_STATE) != W.RESEARCH_DONE:
                    evidence.add(pid)
        self._research = research
        self._evidence.append(evidence)
        recent = set().union(*self._evidence)
        market: dict[int, list[float]] = defaultdict(vec)
        for ev in events:
            if ev.get("kind") != "markettransaction":
                continue
            pid = int(ev.get("playerid", 0) or 0)
            index = int(ev.get("attributetype", 0) or 0)
            amount = float(ev.get("attributeexchanged", 0) or 0)
            gold = abs(float(ev.get("goldexchanged", 0) or 0))
            if pid <= 0 or index not in (0, 1, 2):
                continue
            market[pid][index] += amount
            if amount > 0:  # sale gold is counted by the game's goldTotal
                market[pid][3] -= gold
        buying = any(c.get("kind") in PURCHASE_COMMANDS for c in commands)
        for pid, p in players.items():
            if pid <= 0:
                continue
            stock = [W.attr(p, r) for r in RES]
            total = [W.attr(p, r + "Total") for r in RES]
            if pid not in self.prev:
                self.start[pid] = list(stock)
                self.prev[pid] = (stock, total)
                continue
            old_stock, old_total = self.prev[pid]
            self.prev[pid] = (stock, total)
            for i in range(4):
                counted = total[i] - old_total[i]
                self.counter[pid][i] += counted
                moved = market[pid][i]
                if moved > 0:
                    self.market_in[pid][i] += moved
                elif moved < 0:
                    self.market_out[pid][i] -= moved
                credit = claimed_direct.get(pid, vec())[i] - self._claimed[pid][i]
                self._claimed[pid][i] += credit
                other = stock[i] - old_stock[i] - counted - moved - credit
                if other < -EPS and credit > EPS and not buying:
                    # Credited, yet the stockpile did not rise and nothing was bought.
                    self.unsupported[pid][i] += min(credit, -other)
                    self.spent[pid][i] += max(0.0, -other - credit)
                    self.direct[pid][i] += max(0.0, credit + other)
                    continue
                self.direct[pid][i] += credit
                if other < -EPS:
                    self.spent[pid][i] -= other
                elif other > EPS and pid in recent:
                    self.refunds[pid][i] += other
                elif other > EPS:
                    self.unexplained[pid][i] += other
                    self.grants.append(
                        {"t": t, "player": pid, "resource": RES[i], "amount": round(other, 1)}
                    )


def claimed(stats: dict[str, Any]) -> dict[str, list[float]]:
    """What the viewer reports for one player (an older checkout lacks some keys)."""
    income = stats.get("resource_income") or {}
    collected = stats.get("collected") or {}
    bonus = income.get("bonus") or {}
    start_bonus = income.get("starting_bonus") or {}
    trade = income.get("trade") or {}
    bought, paid = vec(), vec()
    for row in income.get("exchanges") or ():
        if row.get("category") != "exchange":
            continue
        if row.get("source") == "Market purchases":
            for i, r in enumerate(RES):
                bought[i] += row["resources"].get(r, 0)
                paid[i] += row["spent"].get(r, 0)
        else:
            for i, r in enumerate(RES):
                paid[i] += row["spent"].get(r, 0)
    return {
        "collected": [float(collected.get(r, 0)) for r in RES],
        # A starting bonus is already inside the starting stockpile.
        "bonus": [float(bonus.get(r, 0)) - float(start_bonus.get(r, 0)) for r in RES],
        "starting_bonus": [float(start_bonus.get(r, 0)) for r in RES],
        "trade": [float(trade.get(r, 0)) for r in RES],
        "market_in": bought,
        "market_out": paid,
        "stock": [float((stats.get("resources") or {}).get(r, 0)) for r in RES],
    }


def direct_credits(tl: Timeline) -> dict[int, list[float]]:
    """Grants the viewer has paid straight into each stockpile so far."""
    history = tl.resource_history
    if hasattr(history, "direct"):
        return {pid: list(values) for pid, values in history.direct.items()}
    out: dict[int, list[float]] = {}
    for pid, sources in history.income.items():
        total = vec()
        for name, values in sources.items():
            if name in LEGACY_DIRECT or name.endswith("construction"):
                total = [a + b for a, b in zip(total, values, strict=True)]
        out[pid] = total
    return out


def reconcile(path: Path, data: GameData, every: int) -> dict[str, Any]:
    tl = Timeline(data)
    truth = GroundTruth()
    rows: list[dict[str, Any]] = []
    names: dict[int, str] = {}
    next_sample = every * 1000
    last_t = 0
    keyframes = 0

    def snapshot(t: int) -> None:
        view = tl._last_view or {}
        for key, stats in (view.get("players") or {}).items():
            pid = int(key)
            if pid not in truth.start:
                continue
            c = claimed(stats)
            for i, r in enumerate(RES):
                gt_income = (
                    truth.counter[pid][i]
                    + truth.direct[pid][i]
                    + truth.unexplained[pid][i]
                    + truth.market_in[pid][i]
                )
                reported = c["collected"][i] + c["bonus"][i] + c["trade"][i] + c["market_in"][i]
                out = truth.spent[pid][i] + truth.market_out[pid][i]
                computed = truth.start[pid][i] + reported + truth.refunds[pid][i] - out
                rows.append(
                    {
                        "t": t,
                        "player": pid,
                        "name": names.get(pid, str(pid)),
                        "resource": r,
                        "start": round(truth.start[pid][i], 1),
                        "starting_bonus": round(c["starting_bonus"][i], 1),
                        "collected": round(c["collected"][i], 1),
                        "bonus": round(c["bonus"][i], 1),
                        "trade": round(c["trade"][i], 1),
                        "market_in": round(c["market_in"][i], 1),
                        "refunds": round(truth.refunds[pid][i], 1),
                        "spent": round(out, 1),
                        "computed": round(computed, 1),
                        "stock": round(truth.prev[pid][0][i], 1),
                        "residual": round(gt_income - reported, 1),
                        "counter": round(truth.counter[pid][i], 1),
                        "direct": round(truth.direct[pid][i], 1),
                        "unexplained": round(truth.unexplained[pid][i], 1),
                        "unsupported": round(truth.unsupported[pid][i], 1),
                    }
                )

    for frame in read_frames(path):
        if not tl.feed(frame):
            continue
        world = W.world_of(tl.patcher.root)
        if world is None:
            continue
        if not names:
            for pid, p in W.players_of(world).items():
                if pid > 0:
                    names[pid] = data.civ_name(int(p.fields.get(W.P_CIV, -1)))
        commands = [_decode_raw_command(c) if c.get("kind") == "raw" else c for c in frame.commands]
        truth.sample(world, frame.time, frame.events, commands, direct_credits(tl))
        last_t = frame.time
        # The viewer's numbers are read where it publishes them: at a keyframe.
        if frame.time >= next_sample and len(tl.keyframes) > keyframes:
            snapshot(frame.time)
            next_sample += every * 1000
        keyframes = len(tl.keyframes)
    tl.finish()
    snapshot(last_t)
    return {"recording": str(path), "rows": rows, "grants": truth.grants}


def markdown(result: dict[str, Any], *, final_only: bool = False) -> str:
    rows = result["rows"]
    if final_only and rows:
        last = max(row["t"] for row in rows)
        rows = [row for row in rows if row["t"] == last]
    head = (
        "| t | player | res | start | collected | bonus | trade | bought | refunds | spent |"
        " computed | stock | residual |\n|---|---|---|---|---|---|---|---|---|---|---|---|---|\n"
    )
    body = "".join(
        f"| {row['t'] // 60000}:{row['t'] // 1000 % 60:02d} | {row['player']} {row['name']} |"
        f" {row['resource']} | {row['start']:g} | {row['collected']:g} | {row['bonus']:g} |"
        f" {row['trade']:g} | {row['market_in']:g} | {row['refunds']:g} | {row['spent']:g} |"
        f" {row['computed']:g} | {row['stock']:g} | **{row['residual']:g}** |\n"
        for row in rows
    )
    return head + body


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("recording", type=Path)
    ap.add_argument("--every", type=int, default=300, help="seconds between reconciliations")
    ap.add_argument("--json", type=Path, help="write the full result here")
    ap.add_argument("--final", action="store_true", help="print only the last reconciliation")
    args = ap.parse_args()
    result = reconcile(args.recording, GameData(find_game_dir()), args.every)
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(result, indent=1))
    print(markdown(result, final_only=args.final))
    worst = max((abs(row["residual"]) for row in result["rows"]), default=0)
    print(f"largest |residual|: {worst:g}")
    print("unexplained increases:", json.dumps(result["grants"][:40]))


if __name__ == "__main__":
    main()
