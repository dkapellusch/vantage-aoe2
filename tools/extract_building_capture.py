#!/usr/bin/env python3
"""Extract genuine stream fields for repeatable farm/desktop building parity tests."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from pathlib import Path
from typing import Any

from vantage import world as W
from vantage.frames import read_frames
from vantage.patch import Node, Patcher
from vantage.schema import SCHEMA


def extract(recording: Path, output: Path, owner: int, until: int) -> None:
    patcher = Patcher()
    nodes: list[dict[str, Any]] = []
    identities: dict[str, int] = {}

    def pack(value: Any) -> Any:
        if isinstance(value, Node):
            item = {
                "model": SCHEMA.name(value.model),
                "fields": {
                    SCHEMA.fields(value.model)[k].name: pack(v) for k, v in value.fields.items()
                },
            }
            key = json.dumps(item, separators=(",", ":"), sort_keys=True)
            if key not in identities:
                identities[key] = len(nodes)
                nodes.append(item)
            return {"$": identities[key]}
        if isinstance(value, dict):
            return {str(k): pack(v) for k, v in value.items()}
        return [pack(v) for v in value] if isinstance(value, list) else value

    samples = []
    for frame in read_frames(recording):
        if frame.time > until:
            break
        patcher.apply(frame.patch)
        world = W.world_of(patcher.root)
        assert world is not None
        player = W.players_of(world)[owner]
        masters: dict[int, Node] = {}
        entities: dict[int, Node] = {}
        for entity in W.live_entities(world):
            f = entity.fields
            if f.get(W.E_OWNER) != owner:
                continue
            master = W.master_node(entity, {owner: player})
            if master is None:
                continue
            if master.fields.get(W.M_TYPE) != W.TYPE_BUILDING and master.fields.get(W.M_CLASS) != 4:
                continue
            mid = int(f[W.E_MASTER])
            masters[mid] = Node(
                master.model, {k: v for k, v in master.fields.items() if k in (W.M_TYPE, W.M_CLASS)}
            )
            entities[int(f[W.E_ID])] = Node(
                entity.model,
                {
                    k: v
                    for k, v in f.items()
                    if k
                    in (
                        W.E_ID,
                        W.E_OWNER,
                        W.E_MASTER,
                        W.B_BUILT,
                        W.B_QUEUE,
                        W.B_QUEUE_ACTION,
                    )
                },
            )
        minimal = Node(
            world.model,
            {
                W.W_PLAYERS: {
                    owner: Node(
                        player.model,
                        {
                            W.P_MASTERS: masters,
                            W.P_ATTR: player.fields[W.P_ATTR],
                        },
                    )
                },
                W.W_ENTITIES: entities,
            },
        )
        samples.append({"time": frame.time, "skipped": bool(frame.skipped), "world": pack(minimal)})
    data = {
        "source": recording.name,
        "sha256": hashlib.sha256(recording.read_bytes()).hexdigest(),
        "owner": owner,
        "samples": samples,
        "nodes": nodes,
    }
    output.write_bytes(gzip.compress(json.dumps(data, separators=(",", ":")).encode(), mtime=0))
    print(output, len(samples), output.stat().st_size, flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("recording", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--owner", type=int, default=1)
    parser.add_argument("--until", type=int, default=2**31 - 1)
    args = parser.parse_args()
    extract(args.recording, args.output, args.owner, args.until)


if __name__ == "__main__":
    main()
