"""Where the main thread's time goes: a sampled CPU profile of one scenario.

    uv run --with playwright python tools/perf/profile.py --base http://127.0.0.1:8792 \
        --spots spots.json --mode playback --speed 8 --zoom 3.5 --where late.fight --out prof.json

Prints self time by bucket (view update, interpolation, entity pass, sprite
batch, ground, minimap, HUD, GC, idle), by entry point (the frame callback, the
HUD timer, ...), what long tasks are made of, and the top functions. A browser
built-in (drawImage, texSubImage3D, ...) is charged to the script function that
called it. JavaScript self time does not depend on the WebGL backend, so this
is meaningful under SwiftShader too; time inside WebGL and canvas calls is not.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

from bench import PAN_DRIVER, open_at
from common import background_load, load_spots
from playwright.sync_api import sync_playwright

HUD_MODULES = (
    "panels overlays dom hud-model layout pulse story team-board widgets selection-panel "
    "focus-slot player-review resource-review metrics i18n compare-table pulse-model "
    "story-model review-workspace"
)
HUD_FILES = {f"{name}.js" for name in HUD_MODULES.split()}
PSEUDO = {"(garbage collector)": "gc", "(idle)": "idle", "(program)": "program (native)"}
# file -> bucket, first match wins
BUCKETS = [
    ("sprite batch (sprite-gl.js)", lambda f, u: u == "sprite-gl.js"),
    ("terrain GL (terrain-gl.js)", lambda f, u: u == "terrain-gl.js"),
    ("interpolation (playback.js)", lambda f, u: u == "playback.js"),
    ("view update / state (state.js)", lambda f, u: u == "state.js"),
    ("minimap", lambda f, u: u == "world.js" and "mini" in f.lower()),
    ("world.js", lambda f, u: u == "world.js"),
    ("HUD / panels / DOM", lambda f, u: u in HUD_FILES),
    ("app.js", lambda f, u: u == "app.js"),
    ("audio", lambda f, u: "audio" in u),
]


def short(url):
    return url.rsplit("/", 1)[-1].split("?")[0]


class Profile:
    def __init__(self, prof):
        self.nodes = {n["id"]: n for n in prof["nodes"]}
        self.parent = {c: n["id"] for n in prof["nodes"] for c in n.get("children", [])}
        self.samples = list(zip(prof["samples"], prof["timeDeltas"], strict=False))
        self.self_us = defaultdict(float)
        for nid, dt in self.samples:
            self.self_us[nid] += dt
        self.total = sum(self.self_us.values())

    def frame(self, nid):
        cf = self.nodes[nid]["callFrame"]
        return cf["functionName"] or "(anonymous)", cf["url"], cf["lineNumber"] + 1

    def owner(self, nid):
        """The node itself, or for a browser built-in the script function that called it."""
        fn, url, _ = self.frame(nid)
        if url or fn.startswith("("):
            return nid, None
        up = nid
        while up in self.parent and not self.frame(up)[1]:
            up = self.parent[up]
        return (up, fn) if self.frame(up)[1] else (nid, None)

    def label(self, nid):
        up, builtin = self.owner(nid)
        fn, url, line = self.frame(up)
        return f"{builtin + ' <- ' if builtin else ''}{fn} {short(url)}:{line}"

    def bucket(self, nid):
        up, _ = self.owner(nid)
        fn, url, _ = self.frame(up)
        if fn in PSEUDO:
            return PSEUDO[fn]
        for name, test in BUCKETS:
            if test(fn, short(url)):
                return name
        return "other: " + (short(url) or fn)

    def entry(self, nid):
        """The outermost script function of the stack: which entry point this is."""
        chain = []
        while nid in self.parent:
            chain.append(nid)
            nid = self.parent[nid]
        for n in reversed(chain):
            if self.frame(n)[1]:
                fn, url, line = self.frame(n)
                return f"{fn} {short(url)}:{line}"
        return self.label(chain[-1]) if chain else "?"

    def long_tasks(self, over_us=50000):
        """Runs of samples with no idle sample between them, longer than 50 ms."""
        tasks, by_fn, by_entry = [], defaultdict(float), defaultdict(float)
        run, run_us = [], 0.0
        for nid, dt in [*self.samples, (None, 0)]:
            if nid is not None and self.frame(nid)[0] != "(idle)":
                run.append((nid, dt))
                run_us += dt
                continue
            if run_us > over_us:
                tasks.append(run_us / 1000)
                for n, d in run:
                    by_fn[self.label(n)] += d
                    by_entry[self.entry(n)] += d
            run, run_us = [], 0.0
        return tasks, by_fn, by_entry


def top(d, n, scale=1000.0, digits=1):
    return {k: round(us / scale, digits) for k, us in sorted(d.items(), key=lambda kv: -kv[1])[:n]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    ap.add_argument("--spots", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--gpu", default="swiftshader")
    ap.add_argument("--headed", action="store_true")
    ap.add_argument("--web", help="take the viewer's front end from this src/vantage/web folder")
    ap.add_argument("--size", type=int, nargs=2, default=[1920, 1080])
    ap.add_argument("--mode", default="playback", choices=["playback", "pan", "paused"])
    ap.add_argument("--hud", default="full")
    ap.add_argument("--where", default="late.fight")
    ap.add_argument("--zoom", type=float, default=3.5)
    ap.add_argument("--speed", type=float, default=8)
    ap.add_argument("--seconds", type=float, default=15)
    ap.add_argument("--top", type=int, default=45)
    ap.add_argument("--entries", type=int, default=3, help="entry points to break down")
    ap.add_argument("--entry-top", type=int, default=25)
    ap.add_argument("--warmup", type=float, default=3, help="seconds of playback before profiling")
    args = ap.parse_args()
    args.spots_data = load_spots(args.spots)
    with sync_playwright() as pw:
        lead = 0
        if args.mode == "playback":
            lead = min(60000, int(args.seconds * 1000 * args.speed * 1.7 / 2))
        v = open_at(pw, args, args.hud, args.where, args.zoom, lead)
        if args.mode == "playback":
            v.speed(args.speed)
            v.ev("() => { window.vantage.S.playing = true; }")
            v.page.wait_for_timeout(args.warmup * 1000)
        elif args.mode == "pan":
            v.ev(PAN_DRIVER, [1500, 900])
            v.page.wait_for_timeout(1000)
        load = background_load()
        v.cdp.send("Profiler.enable")
        v.cdp.send("Profiler.setSamplingInterval", {"interval": 200})
        v.ev("() => window.__perf.start()")
        v.cdp.send("Profiler.start")
        v.page.wait_for_timeout(args.seconds * 1000)
        prof = Profile(v.cdp.send("Profiler.stop")["profile"])
        c = v.collect()
        renderer = v.renderer()
        errors = v.errors[:5]
        v.close()
    frames = max(1, len(c["frames"]))
    by_fn, by_bucket = defaultdict(float), defaultdict(float)
    by_entry = defaultdict(lambda: defaultdict(float))
    for nid, us in prof.self_us.items():
        by_fn[prof.label(nid)] += us
        by_bucket[prof.bucket(nid)] += us
        if prof.frame(nid)[0] not in PSEUDO and prof.frame(nid)[0] != "(root)":
            by_entry[prof.entry(nid)][prof.label(nid)] += us
    tasks, long_fn, long_entry = prof.long_tasks()
    entries = sorted(by_entry.items(), key=lambda kv: -sum(kv[1].values()))[: args.entries]
    out = {
        "args": {k: a for k, a in vars(args).items() if k != "spots_data"},
        "renderer": renderer,
        "load": load,
        "page_errors": errors,
        "frames": frames,
        "seconds": round(prof.total / 1e6, 2),
        "work_ms_mean": round(sum(c["work"]) / frames, 3),
        "buckets_ms_per_frame": top(by_bucket, 40, 1000.0 * frames, 3),
        "entries": [
            {
                "entry": k,
                "ms_per_frame": round(sum(fns.values()) / 1000 / frames, 3),
                "top_ms_per_frame": top(fns, args.entry_top, 1000.0 * frames, 4),
            }
            for k, fns in entries
        ],
        "long_tasks": {
            "n": len(tasks),
            "total_ms": round(sum(tasks), 1),
            "max_ms": round(max(tasks, default=0), 1),
            "by_entry_ms": top(long_entry, 12),
            "by_function_ms": top(long_fn, 30),
        },
        "top_ms_per_frame": top(by_fn, args.top, 1000.0 * frames, 4),
    }
    Path(args.out).write_text(json.dumps(out, indent=1))
    print(f"{renderer}\nframes {frames}, work {out['work_ms_mean']} ms/frame (mean), load {load}")
    for k, ms in out["buckets_ms_per_frame"].items():
        if not k.startswith("other:") or ms >= 0.02:
            print(f"  {ms:8.3f} ms/frame  {k}")
    for e in out["entries"]:
        print(f"entry {e['entry']}: {e['ms_per_frame']} ms/frame")
        for f, ms in e["top_ms_per_frame"].items():
            print(f"  {ms:8.4f}  {f}")
    lt = out["long_tasks"]
    print(f"long tasks (>50 ms busy): {lt['n']}, {lt['total_ms']} ms, longest {lt['max_ms']} ms")
    for k, ms in lt["by_entry_ms"].items():
        print(f"  {ms:9.1f} ms  entry  {k}")
    for k, ms in lt["by_function_ms"].items():
        print(f"  {ms:9.1f} ms  self   {k}")
    print("top functions, ms/frame:")
    for f, ms in out["top_ms_per_frame"].items():
        print(f"  {ms:8.4f}  {f}")


if __name__ == "__main__":
    main()
