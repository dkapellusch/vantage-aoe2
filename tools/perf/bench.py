"""Playback, panning, zooming and seeking benchmark for the viewer. See README.md.

    uv run --with playwright python tools/perf/bench.py \
        --base http://127.0.0.1:8792 --spots spots.json --label before --out before.json

Each scenario runs in a fresh browser (cold sprite cache in memory; the HTTP
cache is per browser too), at the camera spots find_spots.py chose.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path

from common import Viewer, background_load, load_spots, measured, summarize
from playwright.sync_api import sync_playwright

ZOOM_OUT = 1.0  # icons (sprites off below the game-art threshold) or small sprites
ZOOM_IN = 3.5  # game art


def spot(spots, where):
    """'late.fight' -> (t, x, y)."""
    phase, kind = where.split(".")
    s = spots[phase]
    p = s.get(kind) or s["base"]
    return s["t"], p["x"], p["y"]


def open_at(pw, args, hud, where, zoom, lead_ms=0):
    t, x, y = spot(args.spots_data, where)
    v = Viewer(
        pw,
        args.base,
        gpu=args.gpu,
        hud=hud,
        size=tuple(args.size),
        headless=not args.headed,
        web=args.web,
    )
    v.camera(x, y, zoom)
    v.seek(max(args.spots_data["start"], t - lead_ms))
    v.camera(x, y, zoom)
    v.settle()
    v.t, v.x, v.y = t, x, y
    return v


def playback(pw, args, hud, where, zoom, speed):
    """Play at `speed` with the camera held on the spot, starting before its moment."""
    # Start so that the spot's moment falls in the middle of the run at 1x..8x.
    lead = min(60000, int(args.seconds * 1000 * speed * 1.7 / 2))
    v = open_at(pw, args, hud, where, zoom, lead)
    v.speed(speed)
    v.ev("() => { window.vantage.S.playing = true; }")
    v.page.wait_for_timeout(args.warmup * 1000)
    r = measured(v, args.seconds)
    r["realtime_factor"] = round(r["game_s"] / r["seconds"], 2)
    return v, r


PAN_DRIVER = "([speed, radius]) => window.__perf.pan(speed, radius)"


def pan_sweep(pw, args, hud, where, zoom, playing=False):
    """Continuous panning, driven once per frame through world.pan (what a drag calls)."""
    v = open_at(pw, args, hud, where, zoom)
    if playing:
        v.speed(1)
        v.ev("() => { window.vantage.S.playing = true; }")
    v.page.wait_for_timeout(500)
    r = measured(v, args.pan_seconds, before=lambda: v.ev(PAN_DRIVER, [1500, 900]))
    v.ev("() => { window.__perf.driver = null; }")
    r["settle_after"] = v.settle()
    return v, r


def pan_mouse(pw, args, hud, where, zoom):
    """A real right-button drag, back and forth, through the browser's input path."""
    v = open_at(pw, args, hud, where, zoom)
    w, h = args.size
    m = v.page.mouse
    m.move(w / 2, h / 2)
    m.down(button="right")

    def drag():
        t0 = time.time()
        while time.time() - t0 < args.pan_seconds:
            k = (time.time() - t0) * 2.2
            m.move(w / 2 + math.cos(k) * w * 0.35, h / 2 + math.sin(2 * k) * h * 0.3)

    r = measured(v, 0, before=drag)
    m.up(button="right")
    r["settle_after"] = v.settle()
    return v, r


def pan_edge(pw, args, hud, where, zoom):
    """Edge scrolling: the pointer held at the left edge, then the right."""
    v = open_at(pw, args, hud, where, zoom)
    v.ev("() => { window.vantage.settings.edgeScroll = true; }")
    w, h = args.size
    m = v.page.mouse

    def scroll():
        half = args.pan_seconds / 2
        m.move(w / 2, h / 2)
        m.move(1, h / 2)
        v.page.wait_for_timeout(half * 1000)
        m.move(w - 2, h / 2)
        v.page.wait_for_timeout(half * 1000)
        m.move(w / 2, h / 2)

    r = measured(v, 0, before=scroll)
    r["settle_after"] = v.settle()
    return v, r


def wheel_zoom(pw, args, hud, where, zoom):
    """Wheel zoom in to game art and back out, repeatedly."""
    v = open_at(pw, args, hud, where, ZOOM_OUT)
    w, h = args.size
    m = v.page.mouse
    m.move(w / 2, h / 2)

    def spin():
        t0 = time.time()
        direction = -1
        while time.time() - t0 < args.pan_seconds:
            for _ in range(12):
                m.wheel(0, direction * 100)
                v.page.wait_for_timeout(40)
            v.page.wait_for_timeout(700)
            direction = -direction

    r = measured(v, 0, before=spin)
    r["settle_after"] = v.settle()
    return v, r


def camera_jumps(pw, args, hud, where, zoom):
    """Minimap-style jumps between far-apart places: time to a complete picture."""
    v = open_at(pw, args, hud, where, zoom)
    s = args.spots_data
    places = [
        p for p in (s["late"].get("fight"), s["late"].get("base"), s["early"].get("base")) if p
    ]
    size = v.ev("() => [window.vantage.S.map.width, window.vantage.S.map.height]")
    places += [
        {"x": size[0] * fx, "y": size[1] * fy}
        for fx, fy in ((0.25, 0.25), (0.75, 0.3), (0.3, 0.75), (0.7, 0.7), (0.5, 0.5))
    ]
    jumps = []
    v.ev("() => window.__perf.start()")
    for rnd in range(2):  # the second round returns to places already seen
        for p in places:
            r = v.ev("([x, y, z]) => window.__perf.jump(x, y, z)", [p["x"], p["y"], zoom])
            r["round"] = rnd
            jumps.append(r)
            v.page.wait_for_timeout(150)
    v.ev("() => { window.__perf.on = false; }")
    c = v.collect()
    out = {"jumps": jumps}
    for rnd, name in ((0, "first_visit"), (1, "revisit")):
        got = [j for j in jumps if j["round"] == rnd]
        out[name] = {
            "full_ms": summarize([j["full"] for j in got if j["full"] is not None], 1),
            "timeouts": sum(j["full"] is None for j in got),
            "incomplete_frames": sum(j["incomplete"] for j in got),
        }
    out["work"] = summarize(c["work"])
    return v, out


def seeks(pw, args, hud, where, zoom):
    """+-30 s skips and a scrub: time to the first right frame and to a complete picture."""
    v = open_at(pw, args, hud, where, zoom)
    t = v.t
    v.ev("() => window.__perf.start()")
    skips = []
    for target in [t + 30000, t + 60000, t + 30000, t, t - 30000, t - 60000, t - 30000, t]:
        target = max(args.spots_data["start"], min(args.spots_data["end"] - 5000, target))
        skips.append(v.seek(target, settle=False, timeout=30000))
        v.page.wait_for_timeout(200)
    # A scrub: a seek every 80 ms across 4 minutes, as dragging the time bar does.
    lo = max(args.spots_data["start"], t - 240000)
    n = 40
    v.ev("() => { window.__perf.scrubWork0 = window.__perf.work.length; }")
    for i in range(n):
        v.ev("(t) => window.vantage.seek(t)", lo + (t - lo) * i / n)
        v.page.wait_for_timeout(80)
    release = v.seek(t, settle=False, timeout=30000)
    v.ev("() => { window.__perf.on = false; }")
    c = v.collect()
    k = v.ev("() => window.__perf.scrubWork0")
    out = {
        "skips": skips,
        "first_ms": summarize([s["first"] for s in skips if s["first"] is not None], 1),
        "full_ms": summarize([s["full"] for s in skips if s["full"] is not None], 1),
        "timeouts": sum(s["full"] is None for s in skips),
        "incomplete_frames": sum(s["incomplete"] for s in skips),
        "scrub_work": summarize(c["work"][k:]),
        "scrub_release": release,
        "work": summarize(c["work"]),
    }
    return v, out


def memory(pw, args, hud, where, zoom, speed=8):
    """A long playback: heap, decoded strips and the GPU atlas, sampled every 15 s."""
    v = open_at(pw, args, hud, where, zoom, lead_ms=60000)
    t = v.t
    v.speed(speed)
    v.ev("() => { window.vantage.S.playing = true; }")
    samples = []
    t0 = time.time()
    while time.time() - t0 < args.memory_seconds:
        v.page.wait_for_timeout(15000)
        # Loop inside the recording: a long run at 8x would otherwise reach the end.
        v.ev(
            "([lo, hi]) => window.__perf.loop(lo, hi)",
            [max(args.spots_data["start"], t - 600000), args.spots_data["end"] - 20000],
        )
        v.ev("() => { if (window.gc) window.gc(); }")
        c = v.collect()
        samples.append(
            {
                "s": round(time.time() - t0),
                "heap_mb": round(c["heap"] / 1048576, 1),
                "strips": c["sprites"]["strips"],
                "strip_mb": round(c["sprites"]["bytes"] / 1048576, 1),
                "atlas_mb": round(c["gpu"]["memory"]["bytes"] / 1048576),
                "atlas_used": c["gpu"]["memory"]["used"],
                "evictions": c["gpu"]["evictions"],
                "game_t": round(c["t"] / 1000),
            }
        )
    half = samples[len(samples) // 2 :]
    out = {
        "samples": samples,
        "heap_growth_mb_second_half": round(half[-1]["heap_mb"] - half[0]["heap_mb"], 1)
        if len(half) > 1
        else None,
        "heap_max_mb": max(s["heap_mb"] for s in samples),
    }
    return v, out


SCENARIOS = {
    "playback": lambda pw, a, hud, where, zoom, **k: playback(
        pw, a, hud, where, zoom, k.get("speed", 1)
    ),
    "pan": pan_sweep,
    "pan_playing": lambda pw, a, hud, where, zoom, **k: pan_sweep(
        pw, a, hud, where, zoom, playing=True
    ),
    "pan_mouse": pan_mouse,
    "pan_edge": pan_edge,
    "wheel": wheel_zoom,
    "jumps": camera_jumps,
    "seek": seeks,
    "memory": memory,
}


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--base", required=True)
    ap.add_argument("--spots", required=True, help="find_spots.py output for this recording")
    ap.add_argument("--label", default="run")
    ap.add_argument("--out", required=True)
    ap.add_argument("--gpu", default="swiftshader", choices=["swiftshader", "vulkan", "egl"])
    ap.add_argument("--headed", action="store_true")
    ap.add_argument(
        "--web",
        help="take the viewer's front end from this src/vantage/web folder (A/B on one server)",
    )
    ap.add_argument("--size", type=int, nargs=2, default=[1920, 1080])
    ap.add_argument("--scenarios", default="playback,pan,pan_mouse,pan_edge,wheel,jumps,seek")
    ap.add_argument("--hud", default="full,minimal")
    ap.add_argument(
        "--where", default="late.fight", help="comma list of early.base, late.base, late.fight"
    )
    ap.add_argument("--zooms", default=f"{ZOOM_OUT},{ZOOM_IN}")
    ap.add_argument("--speeds", default="1,4,8")
    ap.add_argument("--seconds", type=float, default=60, help="playback measurement")
    ap.add_argument("--pan-seconds", type=float, default=15)
    ap.add_argument("--memory-seconds", type=float, default=600)
    ap.add_argument("--warmup", type=float, default=4)
    ap.add_argument("--repeat", type=int, default=1)
    args = ap.parse_args()
    args.spots_data = load_spots(args.spots)
    out_path = Path(args.out)
    doc = (
        json.loads(out_path.read_text())
        if out_path.exists()
        else {"label": args.label, "base": args.base, "runs": []}
    )
    with sync_playwright() as pw:
        for name in args.scenarios.split(","):
            for hud in args.hud.split(","):
                for where in args.where.split(","):
                    for zoom in [float(z) for z in args.zooms.split(",")]:
                        variants = (
                            [{"speed": float(s)} for s in args.speeds.split(",")]
                            if name == "playback"
                            else [{}]
                        )
                        for kw in variants:
                            for rep in range(args.repeat):
                                load = background_load()
                                v = None
                                try:
                                    v, r = SCENARIOS[name](pw, args, hud, where, zoom, **kw)
                                    r["renderer"] = v.renderer()
                                    r["page_errors"] = v.errors[:5]
                                except Exception as e:
                                    r = {"failed": repr(e)[:300]}
                                finally:
                                    if v:
                                        v.close()
                                row = {
                                    "scenario": name,
                                    "hud": hud,
                                    "where": where,
                                    "zoom": zoom,
                                    **kw,
                                    "rep": rep,
                                    "gpu": args.gpu,
                                    "load": load,
                                    "result": r,
                                }
                                doc["runs"].append(row)
                                out_path.write_text(json.dumps(doc, indent=1))
                                brief = r.get("work") or r.get("full_ms") or r.get("failed") or ""
                                print(
                                    name,
                                    hud,
                                    where,
                                    zoom,
                                    kw,
                                    "load",
                                    round(load["loadavg"], 1),
                                    brief,
                                    r.get("page_errors") or "",
                                    flush=True,
                                )
    return 0


if __name__ == "__main__":
    sys.exit(main())
