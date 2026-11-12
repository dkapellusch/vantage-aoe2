"""Extract minimal, unmodified farm/receipt facts from a real recording window."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from vantage import world as W
from vantage.frames import read_frames
from vantage.patch import Node, Patcher


def extract(path: Path, start: int, end: int) -> dict:
    patcher = Patcher()
    frames = []
    for frame in read_frames(path):
        patcher.apply(frame.patch)
        if frame.time < start:
            continue
        if frame.time > end:
            break
        world = W.world_of(patcher.root)
        player = W.players_of(world)[2]
        entities = W.entities_of(world)
        selected = []
        for eid, entity in entities.items():
            f = entity.fields
            if f.get(W.E_OWNER) != 2 or f.get(W.E_MASTER) not in (50, 68):
                continue
            m = W.master_node(entity, W.players_of(world))
            if not isinstance(m, Node):
                continue
            selected.append(
                {
                    "id": eid,
                    "fields": {
                        k: f[k]
                        for k in (
                            W.E_MASTER,
                            W.E_OWNER,
                            W.E_X,
                            W.E_Y,
                            W.E_STATE,
                            W.B_BUILT,
                            W.E_HELD_AMT,
                            W.E_HELD_TYPE,
                            W.E_DOPPLE,
                        )
                        if k in f
                    },
                    "master": {k: m.fields[k] for k in (W.M_CLASS, W.M_TYPE) if k in m.fields},
                }
            )
        frames.append(
            {
                "time": frame.time,
                "attributes": {
                    x: W.attr(player, x)
                    for x in (
                        "food",
                        "foodTotal",
                        "farmDeathRate",
                        "folwarkCollectAmount",
                        "folwarkBuildingId",
                    )
                },
                "done": [
                    tid
                    for tid in (12, 13, 14)
                    if (
                        player.fields.get(W.P_RESEARCH, {}).get(tid, Node(0)).fields.get(W.R_STATE)
                        == W.RESEARCH_DONE
                    )
                ],
                "entities": selected,
            }
        )
    return {
        "source": path.name,
        "sha256": hashlib.file_digest(path.open("rb"), "sha256").hexdigest(),
        "player": 2,
        "civ": 38,
        "frames": frames,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("recording", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.write_text(json.dumps(extract(args.recording, 1470000, 1484000), indent=2) + "\n")
