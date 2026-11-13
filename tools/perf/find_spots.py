"""Pick the benchmark's camera spots in a recording served on a port.

    python tools/perf/find_spots.py http://127.0.0.1:8792 spots.json

Writes { early: {t, base}, late: {t, base, fight} }: `base` is the centre of the
densest 10x10-tile cell of one player's buildings, `fight` the densest cell of
fighting units at the busiest sampled minute of the last 60 % of the game.
"""

from __future__ import annotations

import json
import sys
import urllib.request
from collections import Counter

from common import wait_loaded

CELL = 10
ACT_FIGHTING = 8


def view(base, t):
    with urllib.request.urlopen(f"{base}/api/view?t={int(t)}", timeout=60) as r:
        return json.load(r)


def densest(rows):
    cells = Counter((int(r[3]) // CELL, int(r[4]) // CELL) for r in rows)
    if not cells:
        return None
    (cx, cy), n = cells.most_common(1)[0]
    inside = [r for r in rows if (int(r[3]) // CELL, int(r[4]) // CELL) == (cx, cy)]
    return {
        "x": round(sum(r[3] for r in inside) / n, 1),
        "y": round(sum(r[4] for r in inside) / n, 1),
        "n": n,
    }


def base_of(v):
    owners = Counter(r[1] for r in v["entities"] if r[1] > 0 and r[6] & 1)
    if not owners:
        return None
    pid = owners.most_common(1)[0][0]
    return densest([r for r in v["entities"] if r[1] == pid and r[6] & 1])


def main():
    base, out = sys.argv[1].rstrip("/"), sys.argv[2]
    tl = wait_loaded(base)["timeline"]
    start, end = tl["start"], tl["end"]
    early_t = start + min(180000, (end - start) // 6)
    best = None
    t = start + (end - start) * 0.4
    while t < end - 30000:
        v = view(base, t)
        fighting = [
            r
            for r in v["entities"]
            if r[1] > 0 and not r[6] & 1 and len(r) > 9 and r[9] == ACT_FIGHTING
        ]
        d = densest(fighting)
        if d and (best is None or d["n"] > best[1]["n"]):
            best = (v["time"], d, len(v["entities"]), v)
        t += 20000
    spots = {
        "start": start,
        "end": end,
        "early": {"t": early_t, "base": base_of(view(base, early_t))},
    }
    if best:
        spots["late"] = {
            "t": best[0],
            "fight": best[1],
            "base": base_of(best[3]),
            "entities": best[2],
        }
    with open(out, "w") as f:
        json.dump(spots, f, indent=1)
    print(json.dumps(spots, indent=1))


if __name__ == "__main__":
    main()
