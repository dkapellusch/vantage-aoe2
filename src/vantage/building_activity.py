"""Building work/idle history sampled at stream resolution, before keyframes.

Queue handoffs can fall entirely between HUD samples. Defer an empty queue for
one second after work; if work resumes sooner, bridge the handoff. A longer
pause is counted in full, including its first second, rather than discounting
one second from every real idle period.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from vantage import world as W
from vantage.patch import Node

HANDOFF_MS = 1000
_WORK = {W.ACT_PRODUCING, W.ACT_RESEARCHING}


@dataclass
class _Building:
    owner: int
    master: int
    activity: int
    since: int
    pending: int | None = None


class BuildingHistory:
    def __init__(self) -> None:
        self.states: dict[int, _Building] = {}
        self.logs: dict[int, list[tuple[int, int]]] = defaultdict(list)
        self.ended: dict[int, int] = {}
        self._idle: dict[int, list[tuple[int, int]]] = defaultdict(list)
        self._breaks: list[tuple[int, int]] = []
        self.time: int | None = None

    def _change(self, eid: int, state: _Building, activity: int, t: int) -> None:
        if state.activity == activity:
            return
        if state.activity == W.ACT_IDLE and state.master in W.TOWN_CENTER_MASTERS:
            self._idle[state.owner].append((state.since, t))
        state.activity, state.since = activity, t
        self.logs[eid].append((t, activity))

    def _resolve(self, eid: int, state: _Building, t: int, *, final: bool = False) -> None:
        if state.pending is not None and (final or t - state.pending >= HANDOFF_MS):
            self._change(eid, state, W.ACT_IDLE, state.pending)
            state.pending = None

    def _end(self, eid: int, t: int) -> None:
        state = self.states[eid]
        self._resolve(eid, state, t, final=True)
        if state.activity == W.ACT_IDLE and state.master in W.TOWN_CENTER_MASTERS:
            self._idle[state.owner].append((state.since, t))
        self.ended[eid] = t
        del self.states[eid]

    def sample(self, world: Node | None, t: int, *, discontinuity: bool = False) -> None:
        if world is None:
            return
        if discontinuity and self.time is not None:
            # Unknown time is neither working nor idle. Do not bridge a stream
            # skip or resync, or carry a pending handoff through it.
            self._breaks.append((self.time, t))
            for eid in list(self.states):
                self._end(eid, self.time)
        self.time = t
        players = W.players_of(world)
        production: dict[int, list[dict[str, Any]]] = defaultdict(list)
        buildings: dict[int, tuple[Node, dict[str, Any] | None]] = {}
        for e in W.live_entities(world):
            f = e.fields
            owner = int(f.get(W.E_OWNER, 0) or 0)
            if owner not in players or owner == 0:
                continue
            mnode = W.master_node(e, players)
            if mnode is None or mnode.fields.get(W.M_TYPE) != W.TYPE_BUILDING:
                continue
            prod = W.production_state(e) if f.get(W.B_BUILT) else None
            if prod is not None:
                production[owner].append(prod)
            buildings[int(f.get(W.E_ID, 0))] = e, prod
        blocked = {
            pid: W.population_state(player, production[pid])[1]
            for pid, player in players.items()
            if pid > 0
        }
        for eid in set(self.states) - buildings.keys():
            self._end(eid, t)
        for eid, (e, prod) in buildings.items():
            owner = int(e.fields[W.E_OWNER])
            master = int(e.fields.get(W.E_MASTER, -1))
            activity = (
                W.building_activity(prod, blocked[owner])
                if e.fields.get(W.B_BUILT)
                else W.ACT_BUILDING
            )
            state = self.states.get(eid)
            if state is not None and (state.owner, state.master) != (owner, master):
                self._end(eid, t)
                state = None
            if state is None:
                self.states[eid] = _Building(owner, master, activity, t)
                self.logs[eid].append((t, activity))
                self.ended.pop(eid, None)
                continue
            self._resolve(eid, state, t)
            if activity == W.ACT_IDLE and state.activity in _WORK:
                if state.pending is None:
                    state.pending = t
            else:
                state.pending = None
                self._change(eid, state, activity, t)

    def finish(self) -> None:
        if self.time is not None:
            for eid, state in self.states.items():
                # A trailing empty interval has no following queue item.
                self._resolve(eid, state, self.time, final=True)

    def tc_idle(self, owner: int, t: int) -> float:
        intervals: Iterable[tuple[int, int]] = [
            *self._idle[owner],
            *(
                (s.since, t)
                for s in self.states.values()
                if s.owner == owner
                and s.master in W.TOWN_CENTER_MASTERS
                and s.activity == W.ACT_IDLE
            ),
        ]
        # Union, not TC-seconds: two idle TCs for one minute still mean one minute.
        merged: list[tuple[int, int]] = []
        for a, b in sorted(intervals):
            b = min(b, t)
            if b <= a:
                continue
            if merged and a <= merged[-1][1]:
                merged[-1] = merged[-1][0], max(b, merged[-1][1])
            else:
                merged.append((a, b))
        return (
            sum(
                b - a - sum(max(0, min(b, y) - max(a, x)) for x, y in self._breaks)
                for a, b in merged
            )
            / 1000
        )
