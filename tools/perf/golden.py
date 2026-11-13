"""Golden screenshots: what the viewer shows, paused at fixed moments, before and after a change.

    golden.py capture --base http://127.0.0.1:8792 --spots spots.json --name 4v4 --out golden/before
    golden.py compare golden/before golden/after [--out diff]

Shots: icons (zoom 0.5), small game art (zoom 1) and large game art (zoom 3.5)
over a base and over the fight, with the Full and the Minimal HUD. Two captures
of the same build measure the noise floor (particles and banners that run on
the wall clock); compare a change against that.
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
from pathlib import Path

ZOOMS = (0.5, 1.0, 3.5)


def capture(args):
    from common import Viewer, load_spots
    from playwright.sync_api import sync_playwright

    spots = load_spots(args.spots)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    report = {}
    with sync_playwright() as pw:
        for hud in args.hud.split(","):
            v = Viewer(pw, args.base, gpu=args.gpu, hud=hud, size=tuple(args.size), web=args.web)
            # Nothing that moves on its own clock: the picture is a function of (t, camera).
            v.ev("() => window.__perf.still()")
            for where in ("early.base", "late.base", "late.fight"):
                phase, kind = where.split(".")
                s = spots[phase]
                p = s.get(kind) or s["base"]
                for zoom in ZOOMS:
                    v.camera(p["x"], p["y"], zoom)
                    v.seek(s["t"])
                    v.camera(p["x"], p["y"], zoom)
                    r = v.settle(timeout=45000)
                    v.page.wait_for_timeout(
                        600
                    )  # the 250 ms HUD render and the minimap layers catch up
                    name = f"{args.name}-{where}-z{zoom}-{hud}"
                    v.page.screenshot(path=str(out / f"{name}.png"))
                    # The world alone (three stacked canvases), without the HUD over it.
                    world = v.ev("() => window.__perf.worldPng()")
                    (out / f"{name}.world.png").write_bytes(
                        base64.b64decode(world.split(",", 1)[1])
                    )
                    st = v.ev("() => window.__perf.shown()")
                    report[name] = {"settle": r, **st}
                    print(name, r, st, flush=True)
            report[f"errors-{hud}"] = [e for e in v.errors if "404" not in e]
            report["renderer"] = v.renderer()
            v.close()
    (out / f"{args.name}.json").write_text(json.dumps(report, indent=1))
    bad = [k for k, r in report.items() if k.startswith("errors-") and r]
    if bad:
        print("PAGE ERRORS", {k: report[k] for k in bad})
        return 1
    return 0


def compare(args):
    import numpy as np
    from PIL import Image

    a_dir, b_dir = Path(args.a), Path(args.b)
    out = Path(args.out) if args.out else None
    if out:
        out.mkdir(parents=True, exist_ok=True)
    rows, worst = [], 0.0
    for a_path in sorted(a_dir.glob("*.png")):
        b_path = b_dir / a_path.name
        if not b_path.exists():
            rows.append((a_path.name, "missing", "", ""))
            worst = 100.0
            continue
        a = np.asarray(Image.open(a_path).convert("RGB"), dtype=np.int16)
        b = np.asarray(Image.open(b_path).convert("RGB"), dtype=np.int16)
        if a.shape != b.shape:
            rows.append((a_path.name, f"size {a.shape} vs {b.shape}", "", ""))
            worst = 100.0
            continue
        d = np.abs(a - b).max(axis=2)
        changed = 100.0 * float((d > args.tolerance).mean())
        rows.append((a_path.name, f"{changed:.4f}", int(d.max()), f"{float(d.mean()):.4f}"))
        worst = max(worst, changed)
        if out and changed > 0:
            Image.fromarray((np.minimum(255, d * 8)).astype(np.uint8)).save(out / a_path.name)
    print(f"{'image':60} {'% px >' + str(args.tolerance):>10} {'max':>4} {'mean':>8}")
    for r in rows:
        print(f"{r[0]:60} {r[1]:>10} {r[2]:>4} {r[3]:>8}")
    print(f"worst: {worst:.4f} % of pixels differ by more than {args.tolerance}/255")
    if out:
        (out / "summary.json").write_text(
            json.dumps({"rows": rows, "worst_pct": worst, "tolerance": args.tolerance}, indent=1)
        )
    return 1 if worst > args.max_pct else 0


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("capture")
    c.add_argument("--base", required=True)
    c.add_argument("--spots", required=True)
    c.add_argument("--name", required=True)
    c.add_argument("--out", required=True)
    c.add_argument("--gpu", default="swiftshader")
    c.add_argument("--web", help="take the viewer's front end from this src/vantage/web folder")
    c.add_argument("--hud", default="full,minimal")
    c.add_argument("--size", type=int, nargs=2, default=[1920, 1080])
    d = sub.add_parser("compare")
    d.add_argument("a")
    d.add_argument("b")
    d.add_argument("--out")
    d.add_argument(
        "--tolerance", type=int, default=2, help="per-channel difference (of 255) that counts"
    )
    d.add_argument(
        "--max-pct", type=float, default=0.05, help="fail above this share of differing pixels"
    )
    args = ap.parse_args()
    return capture(args) if args.cmd == "capture" else compare(args)


if __name__ == "__main__":
    sys.exit(main())
