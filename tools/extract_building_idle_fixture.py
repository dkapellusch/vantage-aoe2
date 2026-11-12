#!/usr/bin/env python3
"""Extract authentic, minimal building/queue samples from a real .vrec window.

Keeps all queued building heads for the player, so housing classification is
not changed by trimming the world. No timings, queues or progress are invented.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from pathlib import Path
from typing import Any

from vantage import world as W
from vantage.frames import read_frames, read_header
from vantage.gamedata import GameData
from vantage.patch import Node, Patcher
from vantage.schema import SCHEMA


def encode(value: Any) -> Any:
    if isinstance(value, Node):
        return {
            "model": SCHEMA.name(value.model),
            "fields": {
                SCHEMA.fields(value.model)[fid].name: encode(v) for fid, v in value.fields.items()
            },
        }
    if isinstance(value, dict):
        return {str(k): encode(v) for k, v in value.items()}
    if isinstance(value, list):
        return [encode(v) for v in value]
    return value


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("recording", type=Path)
    parser.add_argument("--start", type=int, required=True, help="Game milliseconds")
    parser.add_argument("--end", type=int, required=True, help="Game milliseconds")
    parser.add_argument("--player", default="Shazama")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    patcher = Patcher()
    catalog = W.Catalog(GameData(None))
    samples = []
    techs: dict[int, Any] = {}
    kept = {
        W.E_ID,
        W.E_MASTER,
        W.E_OWNER,
        W.E_STATE,
        W.E_X,
        W.E_Y,
        W.B_BUILT,
        W.B_QUEUE,
        W.B_QUEUE_ACTION,
        W.E_ACTION,
    }
    for frame in read_frames(args.recording):
        patcher.apply(frame.patch)
        if frame.time < args.start:
            continue
        if frame.time > args.end:
            break
        world = W.world_of(patcher.root)
        assert world is not None
        players = W.players_of(world)
        pid, player = next(
            (pid, p) for pid, p in players.items() if p.fields.get(W.P_NAME) == args.player
        )
        catalog.load_techs(world)
        masters = player.fields.get(W.P_MASTERS) or {}
        entities = {}
        master_ids = set()
        for e in W.live_entities(world):
            if e.fields.get(W.E_OWNER) != pid:
                continue
            master = W.master_node(e, players)
            if master is None or master.fields.get(W.M_TYPE) != W.TYPE_BUILDING:
                continue
            mid = int(e.fields.get(W.E_MASTER, -1))
            prod = W.production_state(e)
            if mid not in W.TOWN_CENTER_MASTERS and prod is None:
                continue
            entities[int(e.fields[W.E_ID])] = Node(
                e.model, {k: v for k, v in e.fields.items() if k in kept}
            )
            master_ids.add(mid)
            if prod:
                for q in [*(prod["queue"] or []), prod["current"] or {}]:
                    if int(q.get("unit", -1)) >= 0:
                        master_ids.add(q["unit"])
                    if int(q.get("tech", -1)) >= 0:
                        techs[q["tech"]] = catalog.techs.get(q["tech"])
        rs = player.fields.get(W.P_RESEARCH) or {}
        minimal_player = Node(
            player.model,
            {
                k: v
                for k, v in player.fields.items()
                if k in {W.P_ID, W.P_NAME, W.P_STATUS, W.P_RESIGNED, W.P_DROPPED, W.P_ATTR}
            },
        )
        minimal_player.fields[W.P_RESEARCH] = {
            tid: state
            for tid, state in rs.items()
            if tid in techs or state.fields.get(W.R_STATE) == W.RESEARCH_ACTIVE
        }
        attrs = player.fields[W.P_ATTR]
        attr_ids = {SCHEMA.fid(attrs.model, name) for name in ("population", "maxPop", "unitLimit")}
        minimal_player.fields[W.P_ATTR] = Node(
            attrs.model, {fid: value for fid, value in attrs.fields.items() if fid in attr_ids}
        )
        minimal_player.fields[W.P_MASTERS] = {
            mid: Node(
                masters[mid].model,
                {
                    k: v
                    for k, v in masters[mid].fields.items()
                    if k in {W.M_TYPE, W.M_CLASS, W.M_BUILD_TIME}
                },
            )
            for mid in master_ids
            if mid in masters
        }
        samples.append(
            {
                "time": frame.time,
                "world": encode(
                    Node(
                        world.model,
                        {
                            W.W_TIME: frame.time,
                            W.W_PLAYERS: {pid: minimal_player},
                            W.W_ENTITIES: entities,
                        },
                    )
                ),
                "villagers_created": W.attr(player, "villagersCreatedTotal"),
                "research_done": [
                    tid
                    for tid, state in rs.items()
                    if state.fields.get(W.R_STATE) == W.RESEARCH_DONE
                    and tid in {22, 101, 102, 103, 8, 213, 249}
                ],
            }
        )
    assert samples
    with args.recording.open("rb") as source:
        digest = hashlib.file_digest(source, "sha256").hexdigest()
    result = {
        "source": args.recording.name,
        "sha256": digest,
        "recording_header": read_header(args.recording),
        "player": args.player,
        "techs": techs,
        "samples": samples,
        "note": "Decoded source fields only; unrelated entities/master fields removed.",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    # Stable bytes: no current timestamp in the compressed fixture.
    args.output.write_bytes(gzip.compress(json.dumps(result).encode(), mtime=0))
    print(
        json.dumps(
            {
                "output": str(args.output),
                "samples": len(samples),
                "from": samples[0]["time"],
                "to": samples[-1]["time"],
                "bytes": args.output.stat().st_size,
            }
        )
    )


if __name__ == "__main__":
    main()
