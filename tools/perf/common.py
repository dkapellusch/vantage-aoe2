"""Shared pieces of the viewer benchmark: the browser, the page and the measurement.

The page-side half is probe.js, injected before the viewer's own scripts.
"""

from __future__ import annotations

import contextlib
import itertools
import json
import mimetypes
import os
import re
import statistics
import subprocess
import time
import urllib.request
from pathlib import Path

SETTINGS_KEY = "vantage.settings.v1"
SEEN = {"seenTutorial": True, "seenRorTutorial": True}
SPEEDS = [-8, -4, -2, -1, -0.5, 0.5, 1, 2, 4, 8]  # state.js SPEEDS

# How Chromium renders WebGL. `swiftshader` is software (CPU): the "weak machine"
# profile, and all that CI has. `vulkan` and `egl` use the real GPU; check the
# reported renderer in the output before trusting a GPU number.
GPU_ARGS = {
    "swiftshader": ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"],
    "vulkan": [
        "--ignore-gpu-blocklist",
        "--use-angle=vulkan",
        "--enable-features=Vulkan",
        "--use-vulkan=native",
        "--enable-gpu",
    ],
    "egl": ["--ignore-gpu-blocklist", "--use-gl=angle", "--use-angle=gl-egl", "--enable-gpu"],
}
COMMON_ARGS = [
    "--enable-precise-memory-info",
    "--js-flags=--expose-gc",
    "--disable-background-timer-throttling",
    "--disable-renderer-backgrounding",
    "--disable-backgrounding-occluded-windows",
]

STATIC_RE = re.compile(r"/static/[0-9a-f]{16}/([^?#]+)")

PROBE_JS = (Path(__file__).parent / "probe.js").read_text()


def pct(xs, p):
    if not xs:
        return None
    s = sorted(xs)
    return s[min(len(s) - 1, int(p * len(s)))]


def summarize(xs, digits=2):
    """Percentiles of a list of milliseconds."""
    if not xs:
        return {"n": 0}
    return {
        "n": len(xs),
        "mean": round(statistics.fmean(xs), digits),
        "p50": round(pct(xs, 0.5), digits),
        "p95": round(pct(xs, 0.95), digits),
        "p99": round(pct(xs, 0.99), digits),
        "max": round(max(xs), digits),
    }


def frame_stats(frames, work):
    """Frame intervals (from rAF timestamps) and the work inside each frame callback."""
    dts = [b - a for a, b in itertools.pairwise(frames)]
    out = {"interval": summarize(dts), "work": summarize(work)}
    if dts:
        out["over16_pct"] = round(100 * sum(d > 16.7 * 1.25 for d in dts) / len(dts), 2)
        out["over33_pct"] = round(100 * sum(d > 33.4 for d in dts) / len(dts), 2)
        out["fps"] = round(1000 * len(dts) / max(1e-9, frames[-1] - frames[0]), 1)
    if work:
        out["work_over16_pct"] = round(100 * sum(w > 16.7 for w in work) / len(work), 2)
        out["work_over33_pct"] = round(100 * sum(w > 33.4 for w in work) / len(work), 2)
    return out


def background_load():
    """What else the machine is doing (reported with every run)."""
    out = {"loadavg": os.getloadavg()[0], "cpus": os.cpu_count()}
    try:
        q = (
            subprocess.run(
                [
                    "nvidia-smi",
                    "--query-gpu=utilization.gpu,memory.used",
                    "--format=csv,noheader,nounits",
                ],
                capture_output=True,
                text=True,
                timeout=5,
            )
            .stdout.strip()
            .split(",")
        )
        out["gpu_util_pct"] = int(q[0])
        out["gpu_mem_mb"] = int(q[1])
    except Exception:
        pass
    return out


def wait_loaded(base, timeout=1800):
    """Block until the server has the whole recording."""
    end = time.time() + timeout
    while time.time() < end:
        try:
            with urllib.request.urlopen(base + "/api/session", timeout=10) as r:
                d = json.load(r)
            if d["timeline"]["complete"]:
                return d
        except OSError:
            pass
        time.sleep(2)
    raise TimeoutError(f"{base} did not finish loading")


class Viewer:
    """One browser with one viewer page on `base`, paused at `t`."""

    def __init__(
        self,
        pw,
        base,
        gpu="swiftshader",
        size=(1920, 1080),
        hud="full",
        settings=None,
        headless=True,
        extra_args=(),
        web=None,
        path="/",
        dpr=1,
        cpu=1,
    ):
        """`web`: a src/vantage/web folder to take the viewer's scripts and styles from
        instead of the server's own (the server reads its copy once, at start): one
        loaded recording then serves any checkout's front end, for A/B runs.
        `path`: the viewer's page on `base` (a hub match is at /v/<id>/). `dpr`: device
        pixels per CSS pixel (2 on a Retina display). `cpu`: slow the page's main thread
        down this many times, once it has loaded (a laptop against this desktop)."""
        self.base = base
        self.dpr = dpr
        secure = base.startswith("https:")
        self.browser = pw.chromium.launch(
            headless=headless,
            args=[
                *GPU_ARGS[gpu],
                *COMMON_ARGS,
                *(["--ignore-certificate-errors"] if secure else []),
                *extra_args,
            ],
        )
        self.ctx = self.browser.new_context(
            viewport={"width": size[0], "height": size[1]},
            device_scale_factor=dpr,
            ignore_https_errors=secure,
        )
        saved = {**SEEN, "hud": {"preset": hud, "hintSeen": True}, **(settings or {})}
        self.ctx.add_init_script(
            f"window.__perfSettings = [{json.dumps(SETTINGS_KEY)}, {json.dumps(json.dumps(saved))}]"
        )
        self.ctx.add_init_script(PROBE_JS)
        if web:
            self.ctx.route(STATIC_RE, lambda route: self._from_folder(route, Path(web)))
        self.page = self.ctx.new_page()
        self.errors = []
        self.page.on("pageerror", lambda e: self.errors.append(str(e)))
        # A sprite the game has no picture for answers 404: expected, counted apart.
        self.not_found = 0
        self.page.on("console", self._on_console)
        self.cdp = self.ctx.new_cdp_session(self.page)
        self.net = {"sprites": 0, "bytes": 0, "cached": 0, "ms": [], "again": 0}
        self._req = {}
        self._seen = set()
        self._again = (
            set()
        )  # strips fetched since the page opened: a second fetch is one the cache dropped
        self.cdp.send("Network.enable")
        self.cdp.on("Network.responseReceived", self._on_response)
        self.cdp.on("Network.loadingFinished", self._on_finished)
        self.page.set_default_timeout(180000)
        t0 = time.time()
        self.page.goto(base + path)
        ready = (
            "document.body.dataset.startup === 'ready' && window.vantage && window.vantage.S.view"
        )
        while True:
            try:
                self.page.wait_for_function(ready, timeout=180000)
                break
            except Exception as e:
                # A hub match first loads a page that registers its service worker and reloads.
                if "context was destroyed" not in str(e) or time.time() - t0 > 180:
                    raise
        self.load_s = round(time.time() - t0, 2)
        if cpu and cpu != 1:
            self.cdp.send("Emulation.setCPUThrottlingRate", {"rate": cpu})

    @staticmethod
    def _from_folder(route, folder):
        name = STATIC_RE.search(route.request.url).group(1)
        path = folder / name
        if ".." in name or not path.is_file():
            return route.continue_()
        route.fulfill(
            status=200,
            body=path.read_bytes(),
            headers={
                "Content-Type": mimetypes.guess_type(name)[0] or "application/octet-stream",
                "Cache-Control": "no-store",
            },
        )

    def _on_console(self, m):
        if m.type != "error":
            return
        if "status of 404" in m.text:
            self.not_found += 1
        else:
            self.errors.append(m.text)

    # -- network (sprite strips) -------------------------------------------------
    def _on_response(self, ev):
        r = ev["response"]
        if "/sprite/" not in r["url"]:
            return
        self._req[ev["requestId"]] = (
            ev["timestamp"],
            bool(r.get("fromDiskCache")),
            r.get("timing"),
        )
        key = r["url"].split("/sprite/", 1)[1]
        if key in self._seen:
            self._again.add(ev["requestId"])
        self._seen.add(key)

    def _on_finished(self, ev):
        got = self._req.pop(ev["requestId"], None)
        if not got:
            return
        _, cached, timing = got
        self.net["sprites"] += 1
        self.net["again"] += ev["requestId"] in self._again
        self._again.discard(ev["requestId"])
        self.net["bytes"] += int(ev.get("encodedDataLength", 0))
        self.net["cached"] += cached
        if timing and timing.get("requestTime"):
            self.net["ms"].append((ev["timestamp"] - timing["requestTime"]) * 1000)

    def net_reset(self):
        self.net = {"sprites": 0, "bytes": 0, "cached": 0, "ms": [], "again": 0}

    def net_summary(self, seconds):
        n = self.net
        return {
            "requests": n["sprites"],
            "requests_per_s": round(n["sprites"] / max(1e-9, seconds), 1),
            "bytes": n["bytes"],
            "http_cache_hits": n["cached"],
            "refetched": n["again"],
            "fetch_ms": summarize(n["ms"], 1),
        }

    # -- page helpers --------------------------------------------------------------
    def ev(self, js, arg=None):
        return self.page.evaluate(js, arg)

    def renderer(self):
        return self.ev("() => window.__perf.renderer()")

    def camera(self, x, y, zoom):
        self.ev("([x, y, z]) => window.vantage.world.setCamera(x, y, z)", [x, y, zoom])

    def seek(self, t, playing=False, settle=True, timeout=60000):
        """Jump to game time t; returns the times to the right frame and to a complete picture."""
        r = self.ev(
            "([t, playing, ms]) => window.__perf.seek(t, playing, ms)", [t, playing, timeout]
        )
        if settle:
            self.page.wait_for_timeout(300)
        return r

    def settle(self, timeout=30000):
        """Wait for a complete picture where the camera and clock now are."""
        return self.ev("(timeout) => window.__perf.afterJump(null, 3, timeout)", timeout)

    def pack_wait(self, seconds):
        """Wait until the browser holds the match's pack (builds that have one, and
        matches that have one: it is asked for once the first picture is up)."""
        if not self.ev("() => !!window.vantage.packStatus"):
            return
        try:
            self.page.wait_for_function(
                "() => window.vantage.packStatus.state !== 'off'", timeout=20000
            )
        except Exception:
            return  # no pack here
        # A long match may not be whole in that time: measured with what arrived (`views`).
        with contextlib.suppress(Exception):
            self.page.wait_for_function(
                "() => ['complete', 'stopped'].includes(window.vantage.packStatus.state)",
                timeout=seconds * 1000,
            )

    def view_stats(self):
        """View requests so far: how many, how many answered from the pack, their mean ms,
        and the pack's state."""
        return self.ev(
            "() => { const v = window.vantage, s = v.viewStats; return { requests: s.requests,"
            " local: s.local || 0, mean_ms: s.requests ? +(s.ms / s.requests).toFixed(1) : null,"
            " recent_ms: v.viewTimings.slice(-40), pack: v.packStatus || null }; }"
        )

    def speed(self, x):
        self.ev("(i) => window.__perf.speed(i)", SPEEDS.index(x))

    def collect(self):
        """Everything the probe recorded since the last reset, plus the viewer's counters."""
        return self.ev("() => window.__perf.collect()")

    def close(self):
        self.browser.close()


def measured(viewer, seconds, before=None):
    """Record for `seconds` and return the summary. `before`: called once recording is on."""
    v = viewer
    start = v.collect()
    v.net_reset()
    v.ev("() => window.__perf.start()")
    t0 = time.time()
    if before:
        before()
    remaining = seconds - (time.time() - t0)
    if remaining > 0:
        v.page.wait_for_timeout(remaining * 1000)
    v.ev("() => { window.__perf.on = false; }")
    wall = time.time() - t0
    end = v.collect()
    out = frame_stats(end["frames"], end["work"])
    out["seconds"] = round(wall, 1)
    out["long_tasks"] = {
        "n": len(end["long"]),
        "total_ms": round(sum(d for _, d in end["long"]), 1),
        "max_ms": round(max((d for _, d in end["long"]), default=0), 1),
    }
    out["hud_render"] = summarize(end["hud"])
    out["decode"] = summarize(end["decode"], 1)
    n = max(1, end["drawTimes"]["n"] - start["drawTimes"]["n"])
    out["draw_ms_per_frame"] = {
        k: round((end["drawTimes"][k] - start["drawTimes"][k]) / n, 3)
        for k in (
            "ground",
            "entities",
            "outlines",
            "effects",
            "post",
            "masks",
            "readAhead",
            "missiles",
        )
    }
    out["ground_repaints"] = end["drawTimes"]["paints"] - start["drawTimes"]["paints"]
    g0, g1 = start["gpu"], end["gpu"]
    frames = max(1, len(end["frames"]))
    out["gpu"] = {
        "instances_per_frame": round((g1["instances"] - g0["instances"]) / frames, 1),
        "uploads": g1["uploads"] - g0["uploads"],
        "uploads_per_frame": round((g1["uploads"] - g0["uploads"]) / frames, 2),
        "deferred": g1["deferred"] - g0["deferred"],
        "evictions": g1["evictions"] - g0["evictions"],
        "grows": g1["grows"] - g0["grows"],
        "atlas_mb": round(g1["memory"]["bytes"] / 1048576),
        "atlas_layers_used": g1["memory"]["used"],
        "on": g1["on"],
    }
    st = end["state"]
    out["incomplete"] = {
        "frames_with_placeholder": sum(1 for s in st if s[0] > 0),
        "frames_with_stale": sum(1 for s in st if s[1] > 0),
        "frames_with_stand_in": sum(1 for s in st if s[2] > 0),
        "placeholders": sum(s[0] for s in st),
        "stale": sum(s[1] for s in st),
        "stand_ins": sum(s[2] for s in st),
    }
    out["sprite_net"] = v.net_summary(wall)
    out["memory"] = {
        "heap_mb": round(end["heap"] / 1048576, 1),
        "strips": end["sprites"]["strips"],
        "strip_mb": round(end["sprites"]["bytes"] / 1048576, 1),
    }
    out["game_s"] = round((end["t"] - start["t"]) / 1000, 1)
    out["entities"] = end["entities"]
    out["slow_frames"] = end.get("slow") or []
    out["probe_errors"] = end["errors"]
    return out


def load_spots(path):
    return json.loads(Path(path).read_text())
