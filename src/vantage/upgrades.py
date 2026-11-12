"""Relevance from installed Genie effects, independent of tech-tree layout.

The parser stays an unmodified external dependency; only compact facts are cached.
Attribute numbers are the game's effect-command ABI, not UI row assignments.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

ATTRIBUTE_TYPES = {0, 4, 5, 10, 14, 15}
UPGRADE_TYPES = {3, 13}
ATTRIBUTES = {0, 5, 8, 9, 10, 11, 12, 13, 19, 20, 23, 101, 109}
# Resource flags cannot be matched to an object ID/class. These IDs are stable
# research IDs; their availability is still checked against the selected civ.
CONVERTER_TECHS = {
    316: "Redemption: permits conversion of buildings and siege",
    319: "Atonement: permits conversion of other converters",
    438: "Theocracy: changes group conversion faith consumption",
    439: "Heresy: converted units die instead of changing allegiance",
    45: "Faith: increases resistance to conversion",
    233: "Illumination: improves faith recovery",
    230: "Block Printing: increases conversion range",
    231: "Sanctity: increases converter HP",
    252: "Fervor: increases converter movement speed",
    46: "Devotion: increases resistance to conversion (when present)",
}
# The owner's resource flags protect units whose game help explicitly recommends
# Monastery conversion resistance; do not infer this from all military classes.
RESISTANCE_TECHS = {45: "Faith", 439: "Heresy"}
ATTACK = [67, 68, 75, 199, 200, 201]
ARMOR = [211, 212, 219, 74, 76, 77, 81, 82, 80]


def read_effects(path: str) -> dict[str, Any]:
    """Parse once, release the large dat tree, retain only query facts."""
    from genieutils.datfile import DatFile

    dat = DatFile.parse(path)
    return {
        "techs": [
            {
                "name": t.name,
                "sid": t.language_dll_name,
                "icon": t.icon_id,
                "civ": t.civ,
                "effect": t.effect_id,
                "locations": [r.location_id for r in t.research_locations],
                "required": list(t.required_techs),
            }
            for t in dat.techs
        ],
        "effects": [[[c.type, c.a, c.b, c.c, c.d] for c in e.effect_commands] for e in dat.effects],
        "units": [
            {
                str(i): {
                    "class": u.class_,
                    "name": u.name,
                    "type": u.type,
                    "sid": u.language_dll_name,
                    "help": u.language_dll_help,
                    "attack": bool(u.type_50 and any(a.amount > 0 for a in u.type_50.attacks)),
                    "converter": any(t.action_type == 104 for t in (u.bird.tasks if u.bird else []))
                    or (
                        i < len(dat.unit_headers)
                        and any(t.action_type == 104 for t in (dat.unit_headers[i].task_list or []))
                    ),
                }
                for i, u in enumerate(c.units)
                if u is not None
            }
            for c in dat.civs
        ],
    }


def commands(data: dict[str, Any], tid: int) -> list[list[Any]]:
    eid = data["techs"][tid]["effect"]
    return data["effects"][eid] if 0 <= eid < len(data["effects"]) else []


def relevance(
    data: dict[str, Any],
    civ: int,
    available: set[int],
    unique: set[int],
    descriptions: dict[int, str],
    town_centers: set[int],
) -> tuple[dict[str, list[int]], dict[int, tuple[int, int]], dict[int, list[int]]]:
    """Return object -> ordered research IDs, plus sort keys for group unions.

    Civ availability is authoritative; effects of unavailable research never
    connect lines or leak another civilisation's unique technology.
    """
    if not 0 <= civ < len(data["units"]):
        return {}, {}, {}
    available = {
        t for t in available if 0 <= t < len(data["techs"]) and data["techs"][t]["civ"] in (-1, civ)
    }
    parents: dict[int, int] = {}

    def root(x: int) -> int:
        while x in parents and x != parents[x]:
            x = parents[x]
        return x

    edges: dict[int, list[tuple[int, int]]] = defaultdict(list)
    for tid in sorted(available):
        for kind, a, b, _, _ in commands(data, tid):
            if kind in UPGRADE_TYPES and a >= 0 and b >= 0:
                parents[root(a)] = root(b)
                edges[tid].append((a, b))
    line_techs: dict[int, set[int]] = defaultdict(set)
    for tid, pairs in edges.items():
        for a, _ in pairs:
            line_techs[root(a)].add(tid)
    by_id: dict[int, set[int]] = defaultdict(set)
    by_class: dict[int, set[int]] = defaultdict(set)
    for tid in available:
        for kind, a, b, attr, _ in commands(data, tid):
            if kind not in ATTRIBUTE_TYPES or attr not in ATTRIBUTES | {1}:
                continue
            (by_id[a] if a >= 0 else by_class[b]).add(tid)

    def depth(tid: int, seen: frozenset[int] = frozenset()) -> int:
        if tid in seen:
            return 0
        parents = [t for t in data["techs"][tid]["required"] if t in available]
        return 1 + max((depth(t, seen | {tid}) for t in parents), default=0)

    order: dict[int, tuple[int, int]] = {}
    line_units: dict[int, list[int]] = defaultdict(list)
    for tid in available:
        # Order follows the existing chip groups, never their tree position.
        category = 4 if tid in unique else 1 if tid in ATTACK else 2 if tid in ARMOR else 3
        rank = (
            ATTACK.index(tid)
            if tid in ATTACK
            else ARMOR.index(tid)
            if tid in ARMOR
            else depth(tid) * 10000 + tid
        )
        order[tid] = (category, rank)

    result = {}
    for key, unit in data["units"][civ].items():
        uid, cls = int(key), unit["class"]
        line_hits = set(line_techs.get(root(uid), ()))
        hits = set(line_hits)
        for tid in line_hits:
            line_units[tid].append(uid)
        for tid in by_id[uid] | by_class[cls]:
            changes: dict[tuple[int, int], float] = defaultdict(float)
            for kind, a, b, attr, amount in commands(data, tid):
                if kind not in ATTRIBUTE_TYPES or not (a == uid or (a == -1 and b == cls)):
                    continue
                if attr not in ATTRIBUTES | {1}:
                    continue
                # LOS only for a principally LOS tech (Town Watch/Patrol).
                # Those two are intentionally shown only on Town Centers.
                if attr == 1:
                    attrs = {
                        c[3]
                        for c in commands(data, tid)
                        if c[0] in ATTRIBUTE_TYPES and c[3] in ATTRIBUTES | {1}
                    }
                    if attrs != {1} or (tid in (8, 280) and uid not in town_centers):
                        continue
                # Attack/range upgrades on non-attacking buildings are noise.
                if unit["type"] == 80 and not unit["attack"] and attr in (9, 12, 19, 20, 23):
                    continue
                mode = kind % 10
                if mode == 4:
                    # Packed armor/attack class+amount: combine class effects
                    # and unit-specific counter-effects before deciding relevance.
                    channel = int(abs(amount)) // 256 if attr in (8, 9) else -1
                    delta = (
                        (abs(amount) % 256) * (-1 if amount < 0 else 1)
                        if attr in (8, 9)
                        else amount
                    )
                    changes[(attr, channel)] += delta
                elif mode == 5:
                    if abs(amount - 1) > 1e-6:
                        changes[(attr, -2)] += 1
                else:
                    changes[(attr, -3)] += 1
            if any(abs(v) > 1e-6 for v in changes.values()):
                hits.add(tid)
        if unit["converter"]:
            hits.update(set(CONVERTER_TECHS) & available)
        text = descriptions.get(uid, "").lower()
        if "more resistant to monks" in text:
            hits.update(set(RESISTANCE_TECHS) & available)
        if hits:
            result[key] = sorted(
                hits, key=lambda t: (0, order[t][1]) if t in line_hits else order[t]
            )
    return result, order, line_units
