"""Inventory resource-income clues in an installed AoE2 build, without copying assets.

Run with the repository on PYTHONPATH. Full localized text stays in the ignored
artifact directory; a manifest binds the audit to the actual installed data.
This discovers advertised mechanics, not arbitrary scenario-trigger behavior.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

from vantage.gamedata import CIV_DESCRIPTION_BASE, GameData, installed_build

INCOME = re.compile(
    r"(?:generat|refund|loot|receiv|return|yield|provid|earn|gain|drop off|collect|convert)"
    r".{0,100}(?:gold|wood|food|stone|resource)|"
    r"(?:gold|wood|food|stone|resource).{0,100}"
    r"(?:generat|refund|loot|receiv|return|yield|earn|gain)",
    re.IGNORECASE,
)

# Income-only searches miss longevity, free upgrades, discounts and time bonuses.
# These are discovery categories, not assertions that the viewer measures them.
ECO_PATTERNS = {
    "income": INCOME,
    "longevity": re.compile(
        r"\b(?:resources?|mines?|animals?|sources?)\b.{0,60}\b(?:last|longer)|\bdecay\b", re.I
    ),
    "drop_off": re.compile(r"\bdrop[ -]?off\b|\bdropsites?\b", re.I),
    "cost": re.compile(r"\bcosts?\b|\btrading fee\b", re.I),
    "free": re.compile(r"\bfree\b|\bspawn\b|\breceive.{0,35}\bvillagers?\b", re.I),
    "work_and_time": re.compile(
        r"\b(?:work ?rates?|work|gather|build|repair|research|train|advancing)\b.{0,70}"
        r"(?:faster|slower|speed|rate|\+\d)|\b(?:increase|improve).{0,35}\bwork ?rate",
        re.I,
    ),
    "capacity_and_supply": re.compile(
        r"\b(?:carry|carries|population|capacity|houses|pastures?)\b|"
        r"\bfarms?\b.{0,55}\bfood\b|\bfish traps?\b",
        re.I,
    ),
    "trade_and_relics": re.compile(r"\b(?:trade|trading|relics?|market)\b", re.I),
    "starting": re.compile(r"\bstart with\b|\bstarting (?:resources|balance)\b", re.I),
    "economic_mechanics": re.compile(
        r"\b(?:loom|caravan|wheelbarrow|hand cart|mule cart|folwark|"
        r"recruitment doctrines?|economic policy)\b|"
        r"\bresearch(?:ed)? instantly\b",
        re.I,
    ),
}


def economy_categories(text: str) -> list[str]:
    return [name for name, pattern in ECO_PATTERNS.items() if pattern.search(text)]


def economy_clauses(description: str) -> list[dict[str, object]]:
    """Retain wrapped bullet clauses and unbulleted team bonuses for review."""
    clauses: list[str] = []
    current = ""
    for raw in re.sub(r"<[^>]*>", "", description).splitlines():
        line = raw.strip()
        if not line or line.endswith(":"):
            if current:
                clauses.append(current)
                current = ""
            continue
        if line.startswith("•"):
            if current:
                clauses.append(current)
            current = line.lstrip("•").strip()
        elif current:
            current += " " + line
        else:
            clauses.append(line)
    if current:
        clauses.append(current)
    return [
        {"text": text, "categories": categories}
        for text in clauses
        if (categories := economy_categories(text))
    ]


def audit(game_dir: Path, output: Path, recording: Path | None = None) -> dict[str, object]:
    data = GameData(game_dir)
    output.mkdir(parents=True, exist_ok=True)
    civs = []
    for cid, civ in enumerate(data.civs):
        sid = civ.get("tech_tree_description_string_id", cid + CIV_DESCRIPTION_BASE)
        civs.append(
            {
                "id": cid,
                "name": data.civ_name(cid),
                "era": civ.get("era"),
                "string_id": sid,
                "description": data.string(sid),
            }
        )
    strings = [
        {"string_id": sid, "text": text}
        for sid, text in data.strings.items()
        if INCOME.search(text)
    ]
    economy = [
        {
            "id": civ["id"],
            "name": civ["name"],
            "string_id": civ["string_id"],
            "clauses": economy_clauses(str(civ["description"])),
        }
        for civ in civs
    ]
    economy_strings = [
        {"string_id": sid, "categories": categories, "text": text}
        for sid, text in data.strings.items()
        if (categories := economy_categories(text))
    ]
    files = []
    for name in ("civilizations.json", "dropsites.json", "empires2_x2_p1.dat"):
        path = data.dat_path(name)
        if path:
            files.append(
                {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
            )
    manifest: dict[str, object] = {
        "executable_resource_build": installed_build(game_dir),
        "civ_entries": len(civs),
        "strings_scanned": len(data.strings),
        "candidate_strings": len(strings),
        "economy_candidate_strings": len(economy_strings),
        "economy_clauses": sum(len(civ["clauses"]) for civ in economy),
        "files": files,
        "mode": data.mode,
        "limits": "Advertised mechanics only; campaign triggers, executable behavior, "
        "unadvertised effects and user mods require independent verification.",
    }
    if recording:
        from vantage import world as W
        from vantage.frames import read_frames, read_header
        from vantage.patch import Node, Patcher
        from vantage.schema import SCHEMA

        patcher = Patcher()
        snapshot = next(frame for frame in read_frames(recording) if frame.is_snapshot)
        patcher.apply(snapshot.patch)
        world = W.world_of(patcher.root)
        tasks = []
        if world is not None:
            field_names = {
                fid: field.name for fid, field in SCHEMA.fields(SCHEMA.model_id("Task")).items()
            }
            for pid, player in W.players_of(world).items():
                for mid, master in (player.fields.get(W.P_MASTERS) or {}).items():
                    for task in W._tasks(master.fields):
                        if task.get(W.TASK_ACTION) not in (151, 164):
                            continue
                        tasks.append(
                            {
                                "player": pid,
                                "master": mid,
                                "name": data.string(master.fields.get(W.M_STRING)),
                                "task": {
                                    field_names.get(k, str(k)): v
                                    for k, v in task.items()
                                    if not isinstance(v, Node)
                                },
                            }
                        )
        (output / "tasks.json").write_text(json.dumps(tasks, indent=2) + "\n")
        manifest["recording"] = {
            "path": str(recording),
            "header": read_header(recording),
            "snapshot_ms": snapshot.time,
            "task_rows": len(tasks),
            "snapshot_sha256": hashlib.sha256(snapshot.patch).hexdigest(),
        }
    for name, value in (
        ("manifest", manifest),
        ("civilizations", civs),
        ("strings", strings),
        ("economy-civilizations", economy),
        ("economy-strings", economy_strings),
    ):
        (output / f"{name}.json").write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--game-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--recording", type=Path)
    args = parser.parse_args()
    print(json.dumps(audit(args.game_dir, args.output, args.recording), indent=2))
