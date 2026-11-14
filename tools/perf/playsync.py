"""Is fast playback in sync? Plays at a speed with the camera on a busy spot and
checks every drawn frame for the faults a viewer sees as "units teleport" and
"units run in place". See README.md ("Playback sync").

    uv run --with playwright python tools/perf/playsync.py --base http://127.0.0.1:8820 \
        --spots spots.json --where late.fight --speeds 8,4 --seconds 45 --out sync.json

Per frame, after the viewer's own frame callback, the page-side sampler reads the
rows the world just drew (world.currentRows()) and the clock:

- teleport: a unit's drawn position moved further in one frame than any unit
  can walk in the game time that frame covered (`MAX_TILES_PER_S` plus slack);
- run in place: a unit drawn in its walking pose (activity 1) whose drawn
  position did not move while the clock advanced;
- no bracket: the clock advanced but there was no pair of keyframes around it
  to interpolate between (no next view, or the clock already past it): every
  unit holds still while its animation runs on;
- order: the clock went backwards while playing forwards, the view in use went
  back in time, or the next view was not after the view.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from common import Viewer, background_load, load_spots
from playwright.sync_api import sync_playwright

# Faster than any land unit or ship walks, in tiles per game second (a Hussar with
# every upgrade is ~1.9 tiles/s).
MAX_TILES_PER_S = 3.0
SLACK_TILES = 0.15

SAMPLER = (Path(__file__).parent / "playsync.js").read_text()

COLLECT = """
() => {
  const st = window.__perf.sync;
  window.__perf.watch = null;
  return { ...st, teleportUnits: st.teleportUnits.size };
}
"""


def spot(spots, where):
    phase, kind = where.split(".")
    s = spots[phase]
    p = s.get(kind) or s["base"]
    return s["t"], p["x"], p["y"]


def per_minute(n, ms):
    return round(n * 60000 / ms, 1) if ms else None


def run(pw, args, speed):
    t, x, y = spot(args.spots_data, args.where)
    lead = min(90000, int(args.seconds * 1000 * speed * 1.7 / 2))
    v = Viewer(
        pw,
        args.base,
        gpu=args.gpu,
        hud=args.hud,
        size=tuple(args.size),
        headless=True,
        web=args.web,
        path=args.path,
        dpr=args.dpr,
        cpu=args.cpu,
    )
    try:
        v.camera(x, y, args.zoom)
        v.seek(max(args.spots_data["start"], t - lead))
        v.camera(x, y, args.zoom)
        v.settle()
        v.speed(speed)
        v.ev(SAMPLER, [MAX_TILES_PER_S, SLACK_TILES])
        v.ev("() => { window.vantage.S.playing = true; }")
        t0 = time.time()
        v.page.wait_for_timeout(args.seconds * 1000)
        st = v.ev(COLLECT)
        wall = time.time() - t0
        timeline = st.pop("timeline")
        out = {
            "speed": speed,
            "wall_s": round(wall, 1),
            "game_s": round(st["gameMs"] / 1000, 1),
            "real_speed": round(st["gameMs"] / max(1, st["wallMs"]), 2),
            "target_speed": round(speed * 1.7, 2),
            **{k: st[k] for k in st if k not in ("examples",)},
            "per_min": {
                k: per_minute(st[k], st["wallMs"])
                for k in (
                    "teleports",
                    "teleportFrames",
                    "bigJumps",
                    "runInPlace",
                    "runInPlaceFrames",
                    "noBracket",
                    "staleView",
                    "backwards",
                    "viewBack",
                    "badPair",
                    "gfxWait",
                    "dataWait",
                )
            },
            "run_in_place_unsynced_per_min": per_minute(
                st["ripWhy"]["noBracket"] + st["ripWhy"]["interpolated"], st["wallMs"]
            ),
            "no_bracket_game_pct": round(100 * st["noBracketGameMs"] / max(1, st["gameMs"]), 1),
            "run_in_place_pct_of_walking": round(
                100 * st["runInPlace"] / max(1, st["walkingUnitFrames"]), 2
            ),
            "examples": st["examples"],
            "errors": v.errors[:10],
        }
        if args.timeline:
            Path(args.timeline).parent.mkdir(parents=True, exist_ok=True)
            with open(f"{args.timeline}-{speed}x.json", "w") as f:
                json.dump(timeline, f)
        return out
    finally:
        v.close()


def summary_line(r):
    pm = r["per_min"]
    return " ".join(
        [
            f"{r['label']} {r['speed']}x: real {r['real_speed']}/{r['target_speed']}",
            f"teleports/min {pm['teleports']} (frames {pm['teleportFrames']},",
            f">6 tiles {pm['bigJumps']})",
            f"run-in-place/min {pm['runInPlace']}",
            f"(unsynced {r['run_in_place_unsynced_per_min']}, why {r['ripWhy']})",
            f"no-bracket/min {pm['noBracket']} ({r['no_bracket_game_pct']}% of game time)",
            f"stale/min {pm['staleView']} back {r['backwards']} viewBack {r['viewBack']}",
            f"badPair {r['badPair']} gfxWait/min {pm['gfxWait']} dataWait/min {pm['dataWait']}",
            f"errors {len(r['errors'])}",
        ]
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    ap.add_argument("--spots", required=True)
    ap.add_argument("--where", default="late.fight")
    ap.add_argument("--label", default="run")
    ap.add_argument("--out", required=True)
    ap.add_argument("--gpu", default="vulkan", choices=["swiftshader", "vulkan", "egl"])
    ap.add_argument("--hud", default="minimal")
    ap.add_argument("--web", help="a src/vantage/web folder to serve the front end from")
    ap.add_argument("--size", type=int, nargs=2, default=[1920, 1080])
    ap.add_argument("--path", default="/")
    ap.add_argument("--dpr", type=float, default=1)
    ap.add_argument("--cpu", type=float, default=1)
    ap.add_argument("--zoom", type=float, default=1.5)
    ap.add_argument("--speeds", default="8,4")
    ap.add_argument("--seconds", type=float, default=45)
    ap.add_argument("--timeline", help="write the per-frame timeline to <this>-<speed>x.json")
    args = ap.parse_args()
    args.spots_data = load_spots(args.spots)
    results = []
    with sync_playwright() as pw:
        for sp in [float(s) if "." in s else int(s) for s in args.speeds.split(",")]:
            load = background_load()
            r = run(pw, args, sp)
            r.update(label=args.label, web=args.web, cpu=args.cpu, load=load, where=args.where)
            results.append(r)
            print(summary_line(r), flush=True)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    prev = json.loads(Path(args.out).read_text()) if Path(args.out).exists() else []
    Path(args.out).write_text(json.dumps(prev + results, indent=1))


if __name__ == "__main__":
    sys.exit(main())
