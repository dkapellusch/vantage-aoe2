"""Diff the six external reviews against installed effects, with per-claim reasons.

Reviews are an oracle to investigate, not input to the production algorithm.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

from vantage.gamedata import GameData, find_game_dir
from vantage.upgrades import CONVERTER_TECHS, RESISTANCE_TECHS, commands


def normal(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


def audit(root: Path) -> dict[str, Any]:
    game = GameData(find_game_dir())
    facts = game._upgrade_facts
    assert facts is not None
    report = json.loads((root / "report.json").read_text())
    contexts = {r["id"]: [] for r in report}
    for row in report:
        contexts[row["id"]].append(row)
    slices = {r["id"]: r for f in root.glob("slice-*.json") for r in json.loads(f.read_text())}
    trees = {cid: game.tech_tree(cid) for cid in {r["civ_id"] for r in report}}
    obtainable = {}
    for cid in trees:
        obtainable[cid] = {
            int(tid)
            for n in game._all_trees[cid].values()
            if n.get("Node Status") != "NotAvailable"
            and (
                tid := (
                    n.get("Node ID") if n.get("Use Type") == "Tech" else n.get("Trigger Tech ID")
                )
            )
            is not None
            and int(tid) >= 0
        }
    names: dict[str, set[int]] = {}
    for tid, tech in enumerate(facts["techs"]):
        for name in (tech["name"], game.string(tech["sid"])):
            names.setdefault(normal(name), set()).add(tid)
    display_names: dict[str, set[int]] = {}
    for tid, tech in enumerate(facts["techs"]):
        name = game.string(tech["sid"])
        if name:
            display_names.setdefault(normal(name), set()).add(tid)
    rows = []
    counts = {
        "entities": 0,
        "add_accepted": 0,
        "add_rejected": 0,
        "remove_accepted": 0,
        "remove_rejected": 0,
        "fixed_beyond_should_show": 0,
        "attributions_added": 0,
        "attributions_removed": 0,
        "unresolved_names": 0,
    }
    for file in sorted(root.glob("review-*.json")):
        for review in json.loads(file.read_text()):
            uid = review["id"]
            context_names: dict[str, set[int]] = {}
            sl = slices[uid]
            for tid, tech in sl["expected_by_effects"].items():
                context_names.setdefault(normal(tech["name"]), set()).add(int(tid))
            for tid, name in sl["currently_shown"].items():
                context_names.setdefault(normal(name), set()).add(int(tid))

            def resolve(name: str, local=context_names) -> set[int]:
                return display_names.get(
                    normal(name), local.get(normal(name), names.get(normal(name), set()))
                )

            actual: dict[int, list[int]] = {}
            for r in contexts[uid]:
                tree = trees[r["civ_id"]]
                for tid in tree["relevant_upgrades"].get(str(uid), []):
                    actual.setdefault(tid, []).append(r["civ_id"])
            claims = []
            for action in ("add", "remove", "should_show", "resource_techs_to_add"):
                for name in review.get(action, []):
                    tids = resolve(name)
                    present = sorted(tids & actual.keys())
                    accepted = bool(present) if action != "remove" else not present
                    if action in ("add", "remove"):
                        counts[f"{action}_{'accepted' if accepted else 'rejected'}"] += 1
                    if not tids:
                        counts["unresolved_names"] += 1
                    witness_ids = present or sorted(tids)
                    witnesses = []
                    for tid in witness_ids:
                        tech = facts["techs"][tid]
                        matches = []
                        for r in contexts[uid]:
                            unit = facts["units"][r["civ_id"]].get(str(uid))
                            if unit is None:
                                continue
                            for c in commands(facts, tid):
                                if (
                                    c[1] == uid or (c[1] == -1 and c[2] == unit["class"])
                                ) and c not in matches:
                                    matches.append(c)
                        witnesses.append(
                            {
                                "tech": tid,
                                "effect": tech["effect"],
                                "attributed_civs": sorted(set(actual.get(tid, []))),
                                "obtainable_in_context": sorted(
                                    {
                                        r["civ_id"]
                                        for r in contexts[uid]
                                        if tid in obtainable[r["civ_id"]]
                                    }
                                ),
                                "line_civs": sorted(
                                    {
                                        cid
                                        for cid in actual.get(tid, [])
                                        if uid in trees[cid]["upgrade_techs"][tid]["line_units"]
                                    }
                                ),
                                "matching_commands": matches,
                                "all_command_types": sorted({c[0] for c in commands(facts, tid)}),
                                "upgrade_edges": [
                                    c[1:3] for c in commands(facts, tid) if c[0] in (3, 13)
                                ],
                                "override": CONVERTER_TECHS.get(tid) or RESISTANCE_TECHS.get(tid),
                            }
                        )
                    if present:
                        reason = (
                            "Installed effects/override apply in the listed civs; "
                            "retained regardless of review wording."
                        )
                    elif not tids:
                        reason = "Unresolved review label; requires manual ID reconciliation."
                    else:
                        available = any(
                            tid in obtainable[r["civ_id"]] for tid in tids for r in contexts[uid]
                        )
                        reason = (
                            "No effective object/class/line change or applicable resource override "
                            "after filtering LOS, "
                            "non-attacking buildings and counter-effects; "
                            "research-at-building is not relevance."
                            if available
                            else "Not obtainable by the civs in the audited context "
                            "(or non-research setup tech)."
                        )
                    claims.append(
                        {
                            "action": action,
                            "name": name,
                            "ids": sorted(tids),
                            "accepted": accepted,
                            "reason": reason,
                            "witnesses": witnesses,
                        }
                    )
            desired = set().union(
                *(
                    resolve(n)
                    for n in review["should_show"] + review.get("resource_techs_to_add", [])
                )
            )
            fixed = sorted(actual.keys() - desired)
            prior = {int(tid) for r in contexts[uid] for tid in r["shown"]}
            added = sorted(actual.keys() - prior)
            removed = sorted(prior - actual.keys())
            counts["attributions_added"] += len(added)
            counts["attributions_removed"] += len(removed)
            counts["fixed_beyond_should_show"] += len(fixed)
            rows.append(
                {
                    "review": file.name,
                    "id": uid,
                    "name": review["name"],
                    "actual_union": sorted(actual),
                    "added_vs_layout": added,
                    "removed_vs_layout": removed,
                    "fixed_beyond_should_show": fixed,
                    "fixed_witnesses": {
                        tid: {
                            "civs": sorted(set(actual[tid])),
                            "effect": facts["techs"][tid]["effect"],
                            "name": game.string(facts["techs"][tid]["sid"]),
                        }
                        for tid in fixed
                    },
                    "claims": claims,
                }
            )
    counts["entities"] = len(rows)
    path = game.dat_path("empires2_x2_p1.dat")
    assert path is not None
    return {
        "dat_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "parser": "genieutils-py==0.1.2",
        "counts": counts,
        "entities": rows,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reviews", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    result = audit(args.reviews)
    args.output.write_text(json.dumps(result, indent=1) + "\n")
    print(json.dumps(result["counts"]))
