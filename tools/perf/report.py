"""Before/after table from two bench.py result files.

    python tools/perf/report.py before.json after.json [more.json ...]

Runs are matched by (scenario, hud, where, zoom, speed); repeats are reduced to
their median. One column per file.
"""

from __future__ import annotations

import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path


def get(d, path):
    for k in path.split("."):
        if not isinstance(d, dict) or k not in d:
            return None
        d = d[k]
    return d


COLUMNS = [
    ("work p50", "work.p50"),
    ("work p95", "work.p95"),
    ("work p99", "work.p99"),
    ("work max", "work.max"),
    ("frame p99", "interval.p99"),
    (">16.7ms %", "over16_pct"),
    (">33ms %", "over33_pct"),
    ("long tasks ms", "long_tasks.total_ms"),
    ("HUD task p50", "hud_render.p50"),
    ("HUD task max", "hud_render.max"),
    ("uploads/frame", "gpu.uploads_per_frame"),
    ("fetches/s", "sprite_net.requests_per_s"),
    ("refetched", "sprite_net.refetched"),
    ("real speed", "realtime_factor"),
    ("heap MB", "memory.heap_mb"),
    ("first ms p50", "first_ms.p50"),
    ("full ms p50", "full_ms.p50"),
    ("full ms max", "full_ms.max"),
    ("jump full p50", "first_visit.full_ms.p50"),
    ("revisit p50", "revisit.full_ms.p50"),
    ("settle ms", "settle_after.full"),
    ("scrub work p95", "scrub_work.p95"),
]


def load(path):
    rows = defaultdict(list)
    for r in json.loads(Path(path).read_text())["runs"]:
        if "failed" in r["result"]:
            continue
        rows[(r["scenario"], r["hud"], r["where"], r["zoom"], r.get("speed", ""))].append(r)
    return rows


def med(runs, path):
    xs = [get(r["result"], path) for r in runs]
    xs = [x for x in xs if isinstance(x, (int, float))]
    return statistics.median(xs) if xs else None


def fmt(x):
    return "-" if x is None else f"{x:.1f}" if abs(x) >= 10 else f"{x:.2f}"


def main():
    files = [a for a in sys.argv[1:] if not a.startswith("--")]
    sets = [load(f) for f in files]
    labels = [json.loads(Path(f).read_text()).get("label", Path(f).stem) for f in files]
    keys = set(sets[0])
    for rows in sets[1:]:
        keys &= set(rows)
    for key in sorted(keys, key=str):
        runs = [rows[key] for rows in sets]
        loads = "/".join(
            f"{statistics.median(r['load']['loadavg'] for r in rs):.0f}" for rs in runs
        )
        speed = f" · {key[4]:g}x" if key[4] != "" else ""
        print(f"\n### {key[0]} · {key[2]} · zoom {key[3]:g}{speed} · {key[1]} HUD")
        print(f"\nruns {'/'.join(str(len(rs)) for rs in runs)}, load average {loads}\n")
        print("| metric | " + " | ".join(labels) + " |\n|---|" + "---|" * len(labels))
        for name, path in COLUMNS:
            vals = [med(rs, path) for rs in runs]
            if all(v is None for v in vals):
                continue
            print(f"| {name} | " + " | ".join(fmt(v) for v in vals) + " |")


if __name__ == "__main__":
    main()
