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

# 5. the picture did not change: screenshots at fixed moments, then a pixel diff
uv run --with playwright --with pillow --with numpy python tools/perf/golden.py capture \
    --base http://127.0.0.1:8792 --spots spots.json --name 4v4 --out golden/after
uv run --with pillow --with numpy python tools/perf/golden.py compare golden/before golden/after

# 6. before/after table
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
standing in, no upload deferred, and the ground and trees current.

Frame `interval` is the time between frame callbacks (what the eye sees; 16.7 ms
is the display's limit). Frame `work` is the time inside the viewer's own frame
callback: the number to compare between builds, because it is not clamped by
the display.
