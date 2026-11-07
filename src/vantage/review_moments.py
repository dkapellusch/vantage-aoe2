"""Validated, replay-local review moments, separate from legacy bookmarks."""

from __future__ import annotations

import math
from typing import Any


def normalize_moments(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list) or len(value) > 500:
        raise ValueError("Expected at most 500 review moments")

    def number(v: Any, low: float = 0, high: float = 1e12) -> float:
        if (
            isinstance(v, bool)
            or not isinstance(v, (int, float))
            or not math.isfinite(v)
            or not low <= v <= high
        ):
            raise ValueError("Invalid review coordinate or time")
        return v

    out = []
    for item in value:
        if not isinstance(item, dict):
            raise ValueError("Invalid review moment")
        camera = item.get("camera", {})
        if not isinstance(camera, dict):
            raise ValueError("Invalid review camera")
        ids = item.get("selection", [])
        if not isinstance(ids, list) or len(ids) > 600:
            raise ValueError("Invalid review selection")
        selection = list(dict.fromkeys(int(number(i, -(2**31), 2**31 - 1)) for i in ids))
        if any(-2_000_000_000 < eid < 0 for eid in selection):
            raise ValueError("Invalid review entity ID")
        row: dict[str, Any] = dict(
            id=str(item.get("id", ""))[:80],
            name=str(item.get("name", ""))[:120],
            note=str(item.get("note", ""))[:2000],
            time=int(number(item.get("time"))),
            player=int(number(item.get("player", 0), 0, 255)),
            fog=item.get("fog") if item.get("fog") in ("off", "standard", "explored") else "off",
            camera={
                key: number(camera.get(key, default), 0.001 if key == "zoom" else -10000, high)
                for key, default, high in (("x", 0, 10000), ("y", 0, 10000), ("zoom", 1, 100))
            },
            selection=selection,
        )
        selection_info = item.get("selection_info")
        if selection_info is not None:
            if not isinstance(selection_info, dict) or len(selection_info) > 600:
                raise ValueError("Invalid review selection metadata")
            row["selection_info"] = {
                str(eid): {
                    "mid": int(number(info.get("mid"), 0, 2**31 - 1)),
                    "owner": int(number(info.get("owner"), 0, 255)),
                }
                for eid, info in selection_info.items()
                if isinstance(info, dict) and str(eid) in {str(i) for i in row["selection"]}
            }
        interval = item.get("range")
        if interval is not None:
            if not isinstance(interval, dict):
                raise ValueError("Invalid review interval")
            a, b = int(number(interval.get("from"))), int(number(interval.get("to")))
            if b < a:
                raise ValueError("Review interval ends before its start")
            row["range"] = {"from": a, "to": b}
        out.append(row)
    return out
