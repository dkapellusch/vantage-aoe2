"""What the browser itself does during playback: a Chrome trace of one scenario.

    uv run --with playwright python tools/perf/trace.py --base http://127.0.0.1:8792 \
        --spots spots.json --gpu vulkan --speed 8 --zoom 3.5 --out trace.json

The CPU profile (profile.py) sees script. This sees the rest of the main
thread as well: style recalculation, layout (and which script line forced
it), paint, garbage collection, image decodes, and how long each task ran.
Prints main-thread time per event kind and per frame, the forced layouts by
call site, and the longest tasks with what was inside them.
"""

from __future__ import annotations

import argparse
import bisect
import json
from collections import defaultdict
from pathlib import Path

from bench import PAN_DRIVER, open_at, spin_wheel
from common import background_load, load_spots
from playwright.sync_api import sync_playwright

CATEGORIES = [
    "devtools.timeline",
    "disabled-by-default-devtools.timeline",
    "disabled-by-default-devtools.timeline.stack",
    "v8",
    "blink.user_timing",
    "toplevel",
]
# Leaf-ish events worth a line each (self time is not computed: these nest little).
KINDS = {
    "UpdateLayoutTree": "style recalculation",
    "Layout": "layout",
    "PrePaint": "pre-paint",
    "Paint": "paint",
    "Layerize": "layerize",
    "Commit": "commit",
    "MajorGC": "GC (major)",
    "MinorGC": "GC (minor)",
    "V8.GC_MC_INCREMENTAL": "GC (incremental marking)",
    "ParseHTML": "parse HTML",
    "FireAnimationFrame": "frame callback (script)",
    "TimerFire": "timers (script, incl. the HUD render)",
    "EventDispatch": "input and message events",
    "HandlePostMessage": "message tasks (the view worker's answers, the HUD's parts)",
    "RunMicrotasks": "microtasks (promises)",
    "Decode Image": "image decode (main thread)",
    "HitTest": "hit test",
}


def site(ev):
    """The script line that forced a layout or style recalculation, if any."""
    for key in ("beginData", "data"):
        stack = (ev.get("args", {}).get(key) or {}).get("stackTrace")
        if stack:
            f = stack[0]
            name = f.get("url", "").rsplit("/", 1)[-1].split("?")[0]
            return f"{f.get('functionName') or '(anonymous)'} {name}:{f.get('lineNumber')}"
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    ap.add_argument("--spots", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--gpu", default="swiftshader")
    ap.add_argument("--headed", action="store_true")
    ap.add_argument("--web", help="take the viewer's front end from this src/vantage/web folder")
    ap.add_argument("--size", type=int, nargs=2, default=[1920, 1080])
    ap.add_argument("--path", default="/", help="the viewer's page (a hub match: /v/<id>/)")
    ap.add_argument("--dpr", type=float, default=1, help="device pixels per CSS pixel")
    ap.add_argument("--cpu", type=float, default=1, help="CPU slowdown factor for the page")
    ap.add_argument("--mode", default="playback", choices=["playback", "pan", "wheel"])
    ap.add_argument("--hud", default="full")
    ap.add_argument("--where", default="late.fight")
    ap.add_argument("--zoom", type=float, default=3.5)
    ap.add_argument("--speed", type=float, default=8)
    ap.add_argument("--seconds", type=float, default=15)
    ap.add_argument("--warmup", type=float, default=3)
    ap.add_argument("--keep", help="also write the raw trace here (opens in chrome://tracing)")
    args = ap.parse_args()
    args.spots_data = load_spots(args.spots)
    with sync_playwright() as pw:
        playing = args.mode == "playback"
        lead = min(60000, int(args.seconds * 1000 * args.speed * 1.7 / 2)) if playing else 0
        v = open_at(pw, args, args.hud, args.where, args.zoom, lead)
        if playing:
            v.speed(args.speed)
            v.ev("() => { window.vantage.S.playing = true; }")
            v.page.wait_for_timeout(args.warmup * 1000)
        elif args.mode == "pan":
            v.ev(PAN_DRIVER, [1500, 900])
        load = background_load()
        v.browser.start_tracing(page=v.page, categories=CATEGORIES)
        v.ev("() => window.__perf.start()")
        if args.mode == "wheel":
            spin_wheel(v, args.size, args.seconds)
        else:
            v.page.wait_for_timeout(args.seconds * 1000)
        c = v.collect()
        raw = json.loads(v.browser.stop_tracing())
        renderer = v.renderer()
        v.close()
    if args.keep:
        Path(args.keep).write_text(json.dumps(raw))
    events = raw["traceEvents"] if isinstance(raw, dict) else raw
    # The renderer's main thread: the one that runs the frame callbacks.
    threads = defaultdict(int)
    for e in events:
        if e.get("name") == "FireAnimationFrame":
            threads[(e["pid"], e["tid"])] += 1
    main_thread = max(threads, key=threads.get)
    mine = [
        e
        for e in events
        if (e.get("pid"), e.get("tid")) == main_thread and e.get("ph") == "X" and "dur" in e
    ]
    frames = max(1, len(c["frames"]))
    by_kind, forced, counts = defaultdict(float), defaultdict(lambda: [0, 0.0]), defaultdict(int)
    for e in mine:
        kind = KINDS.get(e["name"])
        if kind:
            by_kind[kind] += e["dur"]
            counts[kind] += 1
        if e["name"] in ("Layout", "UpdateLayoutTree", "ParseHTML"):
            where = site(e)
            if where:
                f = forced[f"{e['name']} from {where}"]
                f[0] += 1
                f[1] += e["dur"]
        if e["name"] == "Paint" and e["dur"] > 2000:
            d = e.get("args", {}).get("data", {})
            f = forced[
                f"Paint over 2 ms of {d.get('nodeName', '?')} (layer {d.get('layerId', '?')})"
            ]
            f[0] += 1
            f[1] += e["dur"]
        if e["name"] == "Decode Image":
            f = forced[f"Decode Image {json.dumps(e.get('args', {}))[:160]}"]
            f[0] += 1
            f[1] += e["dur"]
    tasks = sorted(
        (e for e in mine if e["name"] in ("RunTask", "ThreadControllerImpl::RunTask")),
        key=lambda e: -e["dur"],
    )
    longest = []
    for t in tasks[:8]:
        inside = defaultdict(float)
        end = t["ts"] + t["dur"]
        for e in mine:
            # Everything inside the task, by name (events nest, so these overlap).
            if e is not t and t["ts"] <= e["ts"] and e["ts"] + e["dur"] <= end and e["dur"] > 1000:
                inside[KINDS.get(e["name"], e["name"])] += e["dur"]
        longest.append(
            {
                "ms": round(t["dur"] / 1000, 1),
                "inside_ms": {
                    k: round(us / 1000, 1)
                    for k, us in sorted(inside.items(), key=lambda kv: -kv[1])
                },
            }
        )
    long_tasks = [t["dur"] / 1000 for t in tasks if t["dur"] > 50000]
    # The whole main-thread frame: the task that runs the frame callback, then
    # style, layout, observers and paint. What decides whether a frame is on
    # time (the frame callback alone leaves the browser's own share out).
    starts = sorted(e["ts"] for e in mine if e["name"] == "FireAnimationFrame")
    whole = []
    for t in mine:
        if t["name"] != "RunTask":
            continue
        i = bisect.bisect_left(starts, t["ts"])
        if i < len(starts) and starts[i] <= t["ts"] + t["dur"]:
            whole.append(t["dur"] / 1000)
    whole.sort()
    out = {
        "frame_tasks": {
            "n": len(whole),
            "p50": round(whole[len(whole) // 2], 2) if whole else None,
            "p95": round(whole[int(len(whole) * 0.95)], 2) if whole else None,
            "p99": round(whole[int(len(whole) * 0.99)], 2) if whole else None,
            "max": round(whole[-1], 2) if whole else None,
            "over_8ms": sum(w > 8.3 for w in whole),
            "over_12ms": sum(w > 12 for w in whole),
            "over_16ms": sum(w > 16.7 for w in whole),
        },
        "args": {k: a for k, a in vars(args).items() if k != "spots_data"},
        "renderer": renderer,
        "load": load,
        "frames": frames,
        "ms_per_frame": {
            k: round(us / 1000 / frames, 3)
            for k, us in sorted(by_kind.items(), key=lambda kv: -kv[1])
        },
        "events": dict(counts),
        "forced": {
            k: {"n": n, "ms": round(us / 1000, 1)}
            for k, (n, us) in sorted(forced.items(), key=lambda kv: -kv[1][1])[:20]
        },
        "long_tasks": {"n": len(long_tasks), "total_ms": round(sum(long_tasks), 1)},
        "longest_tasks": longest,
    }
    Path(args.out).write_text(json.dumps(out, indent=1))
    print(f"{renderer}\nframes {frames}, load {load}")
    ft = out["frame_tasks"]
    print(
        f"whole main-thread frames (callback, style, layout, paint): p50 {ft['p50']} "
        f"p95 {ft['p95']} p99 {ft['p99']} max {ft['max']} ms; over 8.3 ms: {ft['over_8ms']}, "
        f"over 12 ms: {ft['over_12ms']}, over 16.7 ms: {ft['over_16ms']} of {ft['n']}"
    )
    for k, ms in out["ms_per_frame"].items():
        print(f"  {ms:8.3f} ms/frame  {counts[k]:6d} x  {k}")
    print(
        "layout, style and HTML parsing by the script line that caused them; big paints; decodes:"
    )
    for k, f in out["forced"].items():
        print(f"  {f['ms']:8.1f} ms  {f['n']:5d} x  {k}")
    print(f"long tasks: {out['long_tasks']}")
    for t in longest:
        print(f"  {t['ms']:8.1f} ms  {t['inside_ms']}")


if __name__ == "__main__":
    main()
