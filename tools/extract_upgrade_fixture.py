"""Extract installed effects, civ availability and English help for regression cases."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from vantage.gamedata import GameData, find_game_dir

CASES = {
    1: [8, 79, 109, 621],
    12: [561],
    15: [125],
    26: [38],
    37: [38],
    44: [1806, 1811],
    45: [1806],
}


def extract() -> dict:
    game = GameData(find_game_dir())
    facts = game._upgrade_facts
    assert facts is not None
    selected = set()
    for cid in CASES:
        for node in game._all_trees[cid].values():
            tid = (
                node.get("Node ID")
                if node.get("Use Type") == "Tech"
                else node.get("Trigger Tech ID")
            )
            if tid is not None and tid >= 0:
                selected.add(tid)
        selected.update(t for ids in game.unique_tech_ids[cid].values() for t in ids)
    selected_effects = {facts["techs"][t]["effect"] for t in selected}
    units = [
        {uid: u for uid, u in civ.items() if int(uid) in CASES.get(cid, [])}
        for cid, civ in enumerate(facts["units"])
    ]
    strings = {}
    for t in selected:
        sid = facts["techs"][t]["sid"]
        strings[sid] = game.string(sid)
    for civ in units:
        for u in civ.values():
            for sid in (u["sid"], u["help"] - 79000):
                strings[sid] = game.string(sid)
    path = game.dat_path("empires2_x2_p1.dat")
    assert path is not None
    return {
        "source": path.name,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "parser": "genieutils-py==0.1.2",
        "build": game.build,
        "facts": {
            "techs": [t if i in selected else {} for i, t in enumerate(facts["techs"])],
            "effects": [e if i in selected_effects else [] for i, e in enumerate(facts["effects"])],
            "units": units,
        },
        "trees": {c: game._all_trees[c] for c in CASES},
        "unique": {c: game.unique_tech_ids[c] for c in CASES},
        "strings": strings,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.write_text(json.dumps(extract(), separators=(",", ":")) + "\n")
