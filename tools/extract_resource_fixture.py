"""Extract what resource accounting reads from a window of a real recording.

The result replays the exact calls the timeline makes to
``ResourceHistory.sample`` (see tests/test_resource_reconcile.py), with each
world pruned to the players' economy: attributes, research states, workers,
buildings and their masters. Values are copied unmodified.

    uv run python tools/extract_resource_fixture.py RECORDING.vrec OUT.json.gz \
        --start 0 --end 170 [--players 3]
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from pathlib import Path
from typing import Any

from vantage import world as W
from vantage.frames import read_frames
from vantage.gamedata import GameData, find_game_dir
from vantage.patch import Node
from vantage.resource_review import TARGET2
from vantage.schema import SCHEMA
from vantage.timeline import Timeline

ATTRS = (
    *W.RESOURCE_NAMES,
    *(r + "Total" for r in W.RESOURCE_NAMES),
    *("starting" + r.title() for r in W.RESOURCE_NAMES),
    *(r + "Bonus" for r in W.RESOURCE_NAMES),
    "relicIncomeCostSummation",
    "noDropsiteFarmers",
    "choppingGoldProductivity",
    "researchCostMod",
    "folwarkCollectAmount",
    "folwarkCollectAttributeType",
    "folwarkBuildingId",
)
PLAYER_FIELDS = (
    W.P_CIV,
    *(W._fid("Player", f"trade{r.title()}Received") for r in W.RESOURCE_NAMES),
)
MASTER_FIELDS = (W.M_CLASS, W.M_TYPE, W.M_HELD, W.M_RADIUS_X, W.M_TASKS, W.M_STRING, W.M_COST)
ACTION_FIELDS = (W.A_TYPE, W.A_STATE, W.A_TARGET, TARGET2)
EVENTS = {"markettransaction", "tribute", "notificationtraindone"}
ALWAYS_MASTERS = (109, 888)


def encode(value: Any) -> Any:
    if isinstance(value, Node):
        return {"$": value.model, "f": {str(k): encode(v) for k, v in value.fields.items()}}
    if isinstance(value, dict):
        return {"#": {str(k): encode(v) for k, v in value.items()}}
    if isinstance(value, (list, tuple)):
        return [encode(v) for v in value]
    return value


def decode(value: Any) -> Any:
    if isinstance(value, dict) and "$" in value:
        return Node(value["$"], {int(k): decode(v) for k, v in value["f"].items()})
    if isinstance(value, dict) and "#" in value:
        return {int(k): decode(v) for k, v in value["#"].items()}
    if isinstance(value, list):
        return [decode(v) for v in value]
    return value


def pick(node: Node, fids: tuple[int, ...]) -> Node:
    return Node(node.model, {fid: node.fields[fid] for fid in fids if fid in node.fields})


class Pool:
    """Identical subtrees (masters, research lists) are stored once."""

    def __init__(self) -> None:
        self.items: list[Any] = []
        self._index: dict[str, int] = {}

    def add(self, encoded: Any) -> int:
        key = hashlib.sha1(json.dumps(encoded, sort_keys=True).encode()).hexdigest()
        if key not in self._index:
            self._index[key] = len(self.items)
            self.items.append(encoded)
        return self._index[key]


def prune(world: Node, keep: set[int] | None, pool: Pool) -> dict[str, Any]:
    players = W.players_of(world)
    entities: dict[str, Any] = {}
    used: dict[int, set[int]] = {pid: set(ALWAYS_MASTERS) for pid in players}
    for eid, e in W.entities_of(world).items():
        owner = int(e.fields.get(W.E_OWNER, 0) or 0)
        if owner <= 0 or (keep is not None and owner not in keep):
            continue
        master = W.master_node(e, players)
        if master is None:
            continue
        cls = int(master.fields.get(W.M_CLASS, -1))
        if int(master.fields.get(W.M_TYPE, 0)) != 80 and cls not in (
            W.CLASS_CIVILIAN,
            W.CLASS_FISHING_BOAT,
        ):
            continue
        fields = {
            k: v
            for k, v in e.fields.items()
            if not isinstance(v, (Node, dict, list)) and k != W.E_SPRITE
        }
        action = W._action_node(e, W.E_ACTION)
        if action is not None:
            fields[W.E_ACTION] = pick(action, ACTION_FIELDS)
        entities[str(eid)] = encode(Node(e.model, fields))
        used[owner].add(int(e.fields.get(W.E_MASTER, -1)))
    out_players: dict[str, Any] = {}
    for pid, p in players.items():
        if pid <= 0 or (keep is not None and pid not in keep):
            continue
        attrs = p.fields.get(W.P_ATTR)
        research = p.fields.get(W.P_RESEARCH) or {}
        masters = p.fields.get(W.P_MASTERS) or {}
        out_players[str(pid)] = {
            "fields": encode(pick(p, PLAYER_FIELDS)),
            "attrs": {
                name: attrs.fields[W._ATTR[name]]
                for name in ATTRS
                if isinstance(attrs, Node) and W._ATTR[name] in attrs.fields
            },
            "research": pool.add(
                {
                    str(state): sorted(
                        tid
                        for tid, rs in research.items()
                        if isinstance(rs, Node) and rs.fields.get(W.R_STATE) == state
                    )
                    for state in (2, W.RESEARCH_DONE)
                }
            ),
            "masters": {
                str(mid): pool.add(encode(pick(masters[mid], MASTER_FIELDS)))
                for mid in sorted(used[pid])
                if isinstance(masters.get(mid), Node)
            },
        }
    return {"players": out_players, "entities": entities}


def restore(frame: dict[str, Any], pool: list[Any], cache: dict[int, Any]) -> Node:
    """The pruned world of one fixture frame, as the Node tree it was read from."""

    def pooled(index: int) -> Any:
        if index not in cache:
            cache[index] = decode(pool[index])
        return cache[index]

    players: dict[int, Node] = {}
    for key, row in frame["players"].items():
        player = decode(row["fields"])
        player.fields[W.P_ATTR] = Node(
            SCHEMA.model_id("PlayerAttributes"),
            {W._ATTR[name]: value for name, value in row["attrs"].items()},
        )
        research = pool[row["research"]]
        player.fields[W.P_RESEARCH] = {
            tid: Node(SCHEMA.model_id("ResearchState"), {W.R_STATE: int(state)})
            for state, tids in research.items()
            for tid in tids
        }
        player.fields[W.P_MASTERS] = {int(mid): pooled(i) for mid, i in row["masters"].items()}
        players[int(key)] = player
    return Node(
        SCHEMA.model_id("World"),
        {
            W.W_PLAYERS: players,
            W.W_ENTITIES: {int(eid): decode(e) for eid, e in frame["entities"].items()},
        },
    )


def extract(path: Path, start: int, end: int, keep: set[int] | None) -> dict[str, Any]:
    data = GameData(find_game_dir())
    tl = Timeline(data)
    pool = Pool()
    frames: list[dict[str, Any]] = []
    original = tl.resource_history.sample

    def capture(world: Node | None, t: int, events: list[dict[str, Any]], **kwargs: Any) -> None:
        original(world, t, events, **kwargs)
        if world is None or not start <= t <= end:
            return
        frames.append(
            {
                "t": t,
                "events": events,
                "raw_events": [
                    e for e in kwargs.get("raw_events") or [] if e.get("kind") in EVENTS
                ],
                "commands": [
                    {k: v for k, v in c.items() if k != "raw"} for c in kwargs.get("commands") or []
                ],
                "discontinuity": bool(kwargs.get("discontinuity")),
                **prune(world, keep, pool),
            }
        )

    tl.resource_history.sample = capture  # type: ignore[method-assign]
    for frame in read_frames(path):
        if frame.time > end:
            break
        tl.feed(frame)
    return {
        "source": {
            "recording_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "window_ms": [start, end],
            "players": sorted(keep) if keep else "all",
        },
        "pool": pool.items,
        "frames": frames,
    }


def load(path: Path) -> dict[str, Any]:
    with gzip.open(path, "rt") as fh:
        return json.load(fh)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("recording", type=Path)
    ap.add_argument("output", type=Path)
    ap.add_argument("--start", type=float, default=0, help="seconds")
    ap.add_argument("--end", type=float, required=True, help="seconds")
    ap.add_argument("--players", type=int, nargs="*", help="keep only these player ids")
    args = ap.parse_args()
    result = extract(
        args.recording,
        int(args.start * 1000),
        int(args.end * 1000),
        set(args.players) if args.players else None,
    )
    with gzip.GzipFile(args.output, "w", mtime=0) as fh:
        fh.write(json.dumps(result, separators=(",", ":")).encode())
    print(f"{len(result['frames'])} frames, {args.output.stat().st_size} bytes")


if __name__ == "__main__":
    main()
