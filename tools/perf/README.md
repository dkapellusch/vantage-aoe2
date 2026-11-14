# Viewer performance benchmark

Measures playback, panning, zooming and seeking in a real browser, against a
recording served by `vantage serve`. Nothing here ships with the package.

```sh
# 1. serve a recording (a big late team game is the stress case)
VANTAGE_NO_LAUNCH=1 uv run vantage serve --port 8792 game.vrec

# 2. pick the camera spots once per recording (a base, the biggest fight)
uv run python tools/perf/find_spots.py http://127.0.0.1:8792 spots.json

# 3. run scenarios; results are appended to the JSON file
uv run --with playwright python tools/perf/bench.py --base http://127.0.0.1:8792 \
    --spots spots.json --gpu vulkan --label after --out after.json

# 4. where the main thread's time goes (a CPU profile of one scenario)
uv run --with playwright python tools/perf/profile.py --base http://127.0.0.1:8792 \
    --spots spots.json --gpu vulkan --mode playback --speed 8 --zoom 3.5 --out prof.json

# 4b. what the browser does besides script: style, layout (and the line that forced
#     it), paint, GC, main-thread image decodes, the longest tasks
uv run --with playwright python tools/perf/trace.py --base http://127.0.0.1:8792 \
    --spots spots.json --gpu vulkan --mode playback --speed 8 --zoom 3.5 --out trace.json

# 5. the picture did not change: screenshots at fixed moments, then a pixel diff
uv run --with playwright --with pillow --with numpy python tools/perf/golden.py capture \
    --base http://127.0.0.1:8792 --spots spots.json --name 4v4 --out golden/after
uv run --with pillow --with numpy python tools/perf/golden.py compare golden/before golden/after

# 6. before/after table (one column per file; repeats reduced to their median)
uv run python tools/perf/report.py before.json after.json
```

## A/B without restarting the server

The server reads its front end once, at start, and a big recording takes
minutes to load. `--web <checkout>/src/vantage/web` (bench, profile, golden)
serves the viewer's scripts and styles from that folder instead, through the
browser's request interception: one loaded recording then runs any checkout's
front end. Python-side changes still need a restart.

## Which GPU

`--gpu swiftshader` (default) is software rendering: it works anywhere, and is
the "weak machine" profile, but time inside WebGL and canvas calls is CPU time
there and says little about a real GPU. `--gpu vulkan` or `--gpu egl` run
headless Chromium on the real GPU; every result records the renderer string
(`ANGLE (NVIDIA, Vulkan ...)`), so check it. Every result also records the load
average and the GPU's utilisation when it started: repeat runs (`--repeat`) and
compare medians when the machine is shared.

## Scenarios (`--scenarios`)

| name | what it does | main numbers |
|---|---|---|
| `playback` | plays at each `--speeds` for `--seconds` with the camera on the spot | frame interval and work percentiles, % of frames over 16.7 / 33 ms, long tasks, HUD render, sprite fetches and decodes, atlas uploads, real speed reached |
| `pan` | figure-of-eight panning at 1500 px/s through `world.pan` (what a drag calls), paused | the same, plus ground repaints and time to a complete picture when it stops |
| `pan_playing` | the same while playing at 1x | |
| `pan_mouse`, `pan_edge` | a real right-button drag; the pointer held at a screen edge | |
| `wheel` | wheel zoom in to game art and back out | |
| `jumps` | minimap-style camera jumps between far places, twice | ms to a complete picture, first visit and revisit |
| `seek` | +-30 s skips, then a scrub (a seek every 80 ms) | ms to the first frame of the right moment and to a complete picture |
| `memory` | `--memory-seconds` of 8x playback, sampled every 15 s after a forced GC | JS heap, decoded strips, atlas size; heap growth over the second half |

`--zooms 1,3.5` covers small game art and large game art; add `0.5` for icons.
`--hud full,minimal` covers both HUD presets. `--where early.base,late.base,late.fight`.

"Complete picture": three consecutive frames with every strip of the view
loaded, no pose held over from an earlier frame, no neighbouring facing
standing in, no upload deferred, and the ground and trees current. The seek
and jump results also say what the picture waited for, in frames
(`waited_frames`: sprites, trees, terrain, ground and why), from
`world.framePending()`.

`profile.py` and `trace.py` take `--mode playback|pan|wheel`. "HUD task" is one
task of the HUD refresh: the whole refresh in builds that do it in one go, one
of its parts in builds that spread it over frames.

On a shared machine the tails are noise: run each build several times,
interleaved (`for i in 1 2 3; do bench --web A ...; bench --web B ...; done`),
and compare medians. `work p50` and the counters (uploads, fetches, repaints,
ms to a complete picture) are the stable numbers.

Frame `interval` is the time between frame callbacks (what the eye sees; 16.7 ms
is the display's limit). Frame `work` is the time inside the viewer's own frame
callback: the number to compare between builds, because it is not clamped by
the display.

## Playback sync (`playsync.py`)

Is fast playback drawn from the right data? It plays at `--speeds` with the
camera on a busy spot and checks every frame the world draws
(`world.currentRows()`, after the viewer's frame callback) against the clock:

| count | what it is |
|---|---|
| teleports | a unit's drawn position moved further in one frame than any unit walks in the game time the frame covered (3 tiles per game second plus 0.15). `>6 tiles` are mostly the game's own (a villager leaving a building) |
| run in place | a unit in its walking activity whose drawn position did not move while the clock advanced; `why` splits it: `noBracket` (no pair of keyframes around the clock), `interpolated` (the interpolation stopped it), `standsInData`/`notInNext` (the game's own) |
| no bracket | frames where the clock advanced without a next view, or past it: every unit holds still while its animation runs on, then jumps when the view lands |
| stale, back, viewBack, badPair | the view more than 1.5 s behind the clock; the clock, or the view in use, going backwards; a next view not after the view |
| gfxWait, dataWait | frames held for graphics (graphics buffering) or slowed for keyframes (data buffering) |

```sh
uv run --with playwright python tools/perf/playsync.py --base http://127.0.0.1:8792 \
    --spots spots.json --where late.fight --speeds 8,4 --seconds 30 --out sync.json \
    [--web <checkout>/src/vantage/web] [--timeline tl/run]   # per-frame [wall, t, view, next, waits, ...]
# the laptop-through-a-hub profile: through remote_proxy.py, Retina, CPU 4x slower
uv run --with playwright python tools/perf/playsync.py --base https://localhost:8797 \
    --spots spots.json --dpr 2 --size 1440 900 --cpu 4 --hud full --out sync-mac.json
```

A slow link (`remote_proxy.py --rtt 250 --mbps 10`) is the stress case for the
clock against the views: before the views were paced, 8x there flipped between
two outcomes per run, either graphics buffering happened to hold the clock (in
step, slow) or the clock outran the views for good (99 % of the game time
without a pair of keyframes, thousands of teleports a minute).
