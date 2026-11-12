"""Precompute the recording's first-frame game artwork before an import is ready."""

from __future__ import annotations

import contextlib
import time
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING, Any

from vantage.sprites import SpriteInfo, SpriteStore

if TYPE_CHECKING:
    from vantage.timeline import Timeline


def first_sprite_jobs(
    view: dict[str, Any], players: dict[int, Any], limit: int = 256
) -> list[tuple[Any, ...]]:
    jobs: set[tuple[Any, ...]] = set()
    # Player objects first. Terrain/resources still warm, but cannot crowd out
    # the starting TC and villagers in a large map's graphics manifest.
    rows = sorted(view.get("entities", []), key=lambda row: row[1] <= 0)
    for row in rows:
        owner, facet = row[1], row[7]
        color = int((players.get(owner) or {}).get("color_id", owner - 1)) if owner > 0 else -1
        variants = [(color, False), (-1, True)] if owner > 0 else [(-1, False)]
        for sid, *_ in row[8]:
            for shade, mask in variants:
                for layer in ("all", "main", "shadow"):
                    job = sid, facet, shade, mask, not bool(row[6] & 1), layer
                    if len(jobs) < limit:
                        jobs.add(job)
    return sorted(jobs)


def warm_assets(timeline: Timeline, *, workers: int = 2) -> dict[str, Any]:
    data = timeline.data
    if data.game_dir is None:
        return {"prepared": 0, "missing": 0, "seconds": 0}
    started = time.monotonic()
    view = timeline.keyframe_at(timeline.start) or {}
    jobs = first_sprite_jobs(view, timeline.match.get("players", {}))
    mods = list(dict.fromkeys(data.mod_roots("graphics") + data.mod_roots("sprites")))
    store = SpriteStore(data.game_dir, data.cache_dir, data.mode, extra_dirs=mods, workers=workers)

    def render(job: tuple[Any, ...]) -> bool:
        sid, facet, color, mask, directional, layer = job
        entry = timeline.sprites.get(sid)
        if entry is None:
            return False
        rgb = data.player_colors[color % 8] if color >= 0 else None
        try:
            return (
                store.strip(
                    SpriteInfo(sid, *entry),
                    facet,
                    rgb,
                    str(color),
                    player_mask=mask,
                    directional=directional,
                    layer=layer,
                )
                is not None
            )
        except Exception:
            return False

    with ThreadPoolExecutor(max_workers=workers) as executor:
        ready = list(executor.map(render, jobs))
    icons = 0
    for mid in {row[2] for row in view.get("entities", []) if row[1] > 0}:
        info = timeline.catalog.masters.get(mid)
        if info and info.kind in ("unit", "building"):
            with contextlib.suppress(OSError, ValueError):
                icons += data.icon_png(info.kind, info.icon) is not None
    for player in timeline.match.get("players", {}).values():
        civ = player.get("civ")
        if isinstance(civ, int) and civ > 0:
            with contextlib.suppress(OSError, ValueError):
                data.emblem_png(civ)
    return {
        "prepared": sum(ready),
        "missing": len(ready) - sum(ready),
        "icons": icons,
        "seconds": round(time.monotonic() - started, 3),
    }
