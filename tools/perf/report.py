"""Before/after table from two bench.py result files.

    python tools/perf/report.py before.json after.json [--md]

Runs are matched by (scenario, hud, where, zoom, speed); repeats are reduced to
their median.
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
    ("HUD p50", "hud_render.p50"),
    ("HUD max", "hud_render.max"),
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
    before, after = load(sys.argv[1]), load(sys.argv[2])
    for key in sorted(set(before) & set(after), key=str):
        b, a = before[key], after[key]
        load_b = statistics.median(r["load"]["loadavg"] for r in b)
        load_a = statistics.median(r["load"]["loadavg"] for r in a)
        speed = f" · {key[4]:g}x" if key[4] != "" else ""
        print(f"\n### {key[0]} · {key[2]} · zoom {key[3]:g}{speed} · {key[1]} HUD")
        print(f"\nruns {len(b)}/{len(a)}, load average {load_b:.0f}/{load_a:.0f}\n")
        print("| metric | before | after |\n|---|---|---|")
        for name, path in COLUMNS:
            x, y = med(b, path), med(a, path)
            if x is None and y is None:
                continue
            print(f"| {name} | {fmt(x)} | {fmt(y)} |")


if __name__ == "__main__":
    main()
