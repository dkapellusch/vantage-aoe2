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

from common import Viewer, background_load, frame_stats, load_spots, measured, summarize
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
        path=args.path,
        dpr=args.dpr,
        cpu=args.cpu,
    )
    v.camera(x, y, zoom)
    v.seek(max(args.spots_data["start"], t - lead_ms))
    v.camera(x, y, zoom)
    v.settle()
    if getattr(args, "pack_wait", 0):
        v.pack_wait(args.pack_wait)
        # and a moment at rest, as a viewer has before the next click: what the
        # page fetches ahead for it (in any build) has started
        v.page.wait_for_timeout(1500)
    v.t, v.x, v.y = t, x, y
    return v


def waited(jumps):
    """What the picture waited for after the jumps: frames each thing was missing for."""
    total = {}
    for j in jumps:
        for k, n in (j.get("waited") or {}).items():
            total[k] = total.get(k, 0) + n
    return dict(sorted(total.items(), key=lambda kv: -kv[1]))


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


def spin_wheel(v, size, seconds):
    """Wheel in twelve notches, pause, wheel out twelve notches, pause, and again."""
    w, h = size
    m = v.page.mouse
    m.move(w / 2, h / 2)
    t0 = time.time()
    direction = -1
    while time.time() - t0 < seconds:
        for _ in range(12):
            wheel_event(v, w / 2, h / 2, 0, direction * 100)  # a mouse wheel's notch
            v.page.wait_for_timeout(40)
        v.page.wait_for_timeout(700)
        direction = -direction


def wheel_zoom(pw, args, hud, where, zoom):
    """Wheel zoom in to game art and back out, repeatedly."""
    v = open_at(pw, args, hud, where, ZOOM_OUT)
    r = measured(v, 0, before=lambda: spin_wheel(v, args.size, args.pan_seconds))
    r["settle_after"] = v.settle()
    return v, r


def wheel_event(v, x, y, dx, dy, ctrl=False):
    """One wheel event in CSS pixels (ctrl set without a key down: a trackpad's pinch).
    With an emulated pixel density the browser divides synthetic deltas by it."""
    v.cdp.send(
        "Input.dispatchMouseEvent",
        {
            "type": "mouseWheel",
            "x": x,
            "y": y,
            "deltaX": dx * v.dpr,
            "deltaY": dy * v.dpr,
            "modifiers": 2 if ctrl else 0,
        },
    )


CAMERA = "() => { const c = window.vantage.S.camera; return [c.x, c.y, c.zoom]; }"


def trackpad_pan(pw, args, hud, where, zoom):
    """Two fingers on a trackpad: a stream of small wheel events, right and down, then back."""
    v = open_at(pw, args, hud, where, zoom)
    w, h = args.size
    x0, y0, z0 = v.ev(CAMERA)
    sent = [0.0, 0.0]

    def scroll():
        t0 = time.time()
        while time.time() - t0 < args.pan_seconds:
            k = (time.time() - t0) * 1.6
            dx, dy = round(math.cos(k) * 22, 2), round(math.sin(2 * k) * 14, 2)
            wheel_event(v, w / 2, h / 2, dx, dy)
            sent[0] += dx
            sent[1] += dy
            v.page.wait_for_timeout(8)

    r = measured(v, 0, before=scroll)
    v.page.wait_for_timeout(1500)  # an eased zoom, if that is what the events did, has ended
    x1, y1, z1 = v.ev(CAMERA)
    # The camera's move in screen px (the viewer's isometric projection, 32 x 16 px tiles).
    moved = [((x1 + y1) - (x0 + y0)) * 16 * z1, ((y1 - x1) - (y0 - x0)) * 8 * z1]
    r["trackpad"] = {
        "scrolled_px": [round(sent[0]), round(sent[1])],
        "camera_moved_px": [round(moved[0]), round(moved[1])],
        "zoom_before": round(z0, 3),
        "zoom_after": round(z1, 3),
        "pans": abs(z1 - z0) < 1e-6 and abs(moved[0] - sent[0]) < 3 and abs(moved[1] - sent[1]) < 3,
    }
    r["settle_after"] = v.settle()
    return v, r


def trackpad_pinch(pw, args, hud, where, zoom):
    """A pinch: ctrl + wheel events with small deltas, out and back in. How far the
    zoom has got when the fingers stop, and how long until it is where it ends."""
    v = open_at(pw, args, hud, where, zoom)
    w, h = args.size
    pinches = []
    v.ev("() => window.__perf.start()")
    for direction in (1, -1, 1, -1):  # zoom out, in, out, in
        z0 = v.ev(CAMERA)[2]
        for _ in range(40):
            wheel_event(v, w / 2, h / 2, 0, direction * 2.5, ctrl=True)
            v.page.wait_for_timeout(8)
        at_stop = v.ev(CAMERA)[2]
        t0 = time.time()
        z, settled_ms = at_stop, 0.0
        while time.time() - t0 < 3:
            v.page.wait_for_timeout(30)
            z_now = v.ev(CAMERA)[2]
            if abs(z_now - z) > 1e-4 * z:
                settled_ms = (time.time() - t0) * 1000
            z = z_now
        total = abs(math.log(z / z0)) or 1e-9
        pinches.append(
            {
                "zoom": [round(z0, 3), round(at_stop, 3), round(z, 3)],
                "done_when_fingers_stop_pct": round(100 * abs(math.log(at_stop / z0)) / total),
                "still_moving_ms": round(settled_ms),
            }
        )
    v.ev("() => { window.__perf.on = false; }")
    c = v.collect()
    out = frame_stats(c["frames"], c["work"])
    out["pinches"] = pinches
    out["done_when_fingers_stop_pct"] = min(p["done_when_fingers_stop_pct"] for p in pinches)
    out["still_moving_ms"] = max(p["still_moving_ms"] for p in pinches)
    return v, out


def link_stats(args):
    """What crossed tools/perf/remote_proxy.py since the last call (None without it)."""
    import ssl
    import urllib.request

    try:
        ctx = ssl._create_unverified_context()
        with urllib.request.urlopen(args.base + "/__stats", timeout=5, context=ctx) as r:
            got = json.load(r)
            return got if "sprites" in got else None
    except Exception:
        return None


def second_match(pw, args, hud, where, zoom):
    """Open a match, watch a little, then open another (--path2) of the same game
    build: how much of the first one's graphics the second fetches again."""
    link_stats(args)
    v = open_at(pw, args, hud, where, zoom, lead_ms=30000)
    v.speed(8)
    v.ev("() => { window.vantage.S.playing = true; }")
    v.page.wait_for_timeout(12000)
    v.ev("() => { window.vantage.S.playing = false; }")
    v.page.wait_for_timeout(1500)
    first = link_stats(args)
    t0 = time.time()
    v.page.goto(args.base + args.path2)
    ready = "document.body.dataset.startup === 'ready' && window.vantage && window.vantage.S.view"
    while True:
        try:
            v.page.wait_for_function(ready, timeout=180000)
            break
        except Exception as e:
            if "context was destroyed" not in str(e):
                raise
    load_s = round(time.time() - t0, 2)
    v.camera(v.x, v.y, zoom)
    jump = v.seek(max(args.spots_data["start"], v.t - 30000), settle=False, timeout=30000)
    v.speed(8)
    v.ev("() => { window.vantage.S.playing = true; }")
    r = measured(v, 12)
    out = {
        "first_match_link": first,
        "second_match_load_s": load_s,
        "second_match_seek": jump,
        "second_match_link": link_stats(args),
        "second_match_playback": {k: r[k] for k in ("work", "over16_pct", "incomplete", "game_s")},
    }
    return v, out


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
    out = {"jumps": jumps, "waited_frames": waited(jumps)}
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
    v.ev("() => { window.vantage.S.scrubbing = true; }")  # as the time bar's drag sets it
    for i in range(n):
        v.ev("(t) => window.vantage.seek(t)", lo + (t - lo) * i / n)
        v.page.wait_for_timeout(80)
    v.ev("() => { window.vantage.S.scrubbing = false; }")
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
        "waited_frames": waited(skips),
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
    "trackpad_pan": trackpad_pan,
    "trackpad_pinch": trackpad_pinch,
    "second_match": second_match,
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
    ap.add_argument("--path", default="/", help="the viewer's page (a hub match: /v/<id>/)")
    ap.add_argument("--path2", help="another match's page, for the second_match scenario")
    ap.add_argument("--dpr", type=float, default=1, help="device pixels per CSS pixel")
    ap.add_argument("--cpu", type=float, default=1, help="CPU slowdown factor for the page")
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
    ap.add_argument(
        "--pack-wait",
        type=float,
        default=0,
        help="wait up to this many seconds for the match's pack to be held by the browser "
        "before measuring (a match opened a while ago, or opened before): 0 measures at once",
    )
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
                                link_stats(args)  # start counting from here
                                v = None
                                try:
                                    v, r = SCENARIOS[name](pw, args, hud, where, zoom, **kw)
                                    link = link_stats(args)
                                    if link and "link" not in r:
                                        r["link"] = link
                                    r["renderer"] = v.renderer()
                                    r["views"] = v.view_stats()
                                    r["load_s"] = v.load_s
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
                                    "profile": {
                                        "dpr": args.dpr,
                                        "cpu": args.cpu,
                                        "size": args.size,
                                    },
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
