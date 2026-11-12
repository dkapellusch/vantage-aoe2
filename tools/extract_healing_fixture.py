"""Extract raw monk/Knight state from Dan's November 11 recording (no inferred HP/cost)."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from vantage import world as W
from vantage.frames import read_frames
from vantage.healing_review import NUM_HEALERS
from vantage.patch import Node, Patcher


def encode(value: Any) -> Any:
    if isinstance(value, Node):
        return {"model": value.model, "fields": encode(value.fields)}
    if isinstance(value, dict):
        return {k: encode(v) for k, v in value.items()}
    if isinstance(value, list):
        return [encode(v) for v in value]
    return value


def extract(path: Path) -> dict[str, Any]:
    patcher = Patcher()
    frames = []
    masters: dict[str, Any] = {}
    fields = {
        W.E_ID,
        W.E_OWNER,
        W.E_MASTER,
        W.E_HP,
        W.E_STATE,
        W.E_X,
        W.E_Y,
        W.E_INSIDE,
        W.E_ACTION,
        NUM_HEALERS,
        *W._MOD_FIDS,
    }
    for frame in read_frames(path):
        patcher.apply(frame.patch)
        if frame.time < 1277500:
            continue
        if frame.time > 1289000:
            break
        world = W.world_of(patcher.root)
        players = W.players_of(world)
        entities = W.entities_of(world)
        selected = {}
        for eid in (13156, 12971):
            entity = entities[eid]
            master = W.master_node(entity, players)
            assert master is not None
            raw = encode(master)
            key = hashlib.sha256(json.dumps(raw, sort_keys=True).encode()).hexdigest()[:16]
            masters[key] = raw
            selected[eid] = {
                "master": key,
                "node": encode(
                    Node(entity.model, {k: v for k, v in entity.fields.items() if k in fields})
                ),
            }
        frames.append(
            {
                "time": frame.time,
                "skipped": frame.skipped,
                "events": [e for e in frame.events if e.get("entityid") == 12971],
                "entities": selected,
                "players": {
                    pid: encode(
                        Node(
                            player.model,
                            {k: v for k, v in player.fields.items() if k in (W.P_ID, W.P_RELATIONS)}
                            | {
                                W.P_ATTR: Node(
                                    player.fields[W.P_ATTR].model,
                                    {
                                        W._fid("PlayerAttributes", "healRange"): W.attr(
                                            player, "healRange"
                                        )
                                    },
                                )
                            },
                        )
                    )
                    for pid, player in players.items()
                    if pid > 0
                },
            }
        )
    return {
        "source": path.name,
        "sha256": hashlib.file_digest(path.open("rb"), "sha256").hexdigest(),
        "healer": 13156,
        "patient": 12971,
        "masters": masters,
        "frames": frames,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("recording", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.write_text(json.dumps(extract(args.recording), indent=2) + "\n")
