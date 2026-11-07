"""Bounded content identity for GameData metadata used by completed playback queries.

Derived from current world.match_info/map_layer/Catalog and GameData methods.
Does not hash independent rendered texture/audio/particle payloads or main .dat.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import TYPE_CHECKING, cast

from vantage.gamedata import PLAYER_COLOR_FILES, GameData, ModConfig

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path
    from typing import TYPE_CHECKING, Any


def file_fact(path: Path) -> Any:
    path = Path(path).absolute()
    if not path.exists():
        return dict(path=str(path), kind="missing")
    if not path.is_file():
        return dict(path=str(path), kind="not-file")
    with path.open("rb") as stream:
        value = hashlib.file_digest(stream, "sha256").hexdigest()
        size = os.fstat(stream.fileno()).st_size
    return dict(path=str(path), kind="file", bytes=size, sha256=value)


class FrozenModConfig(ModConfig):
    """Freeze this job's lookup, retaining UI/config inputs for the next job."""

    def __init__(self, config: ModConfig, resolved: Any) -> None:
        super().__init__(
            enabled=dict(config.enabled),
            profiles=list(config.profiles),
            live_mods=None if config.live_mods is None else list(config.live_mods),
            extra=list(config.extra),
        )
        self._resolved = tuple(resolved)

    def mod_folders(self) -> Any:
        return list(self._resolved)


def fresh_data(data: GameData) -> GameData:
    if type(data) is not GameData:
        raise ValueError("custom GameData subclasses need their own explicit semantic manifest")
    # Resolve from original configuration fields, not a previous job's frozen
    # result. Otherwise installing a cached Timeline would freeze profile mods
    # forever and fail to observe mod-status.json changes on the next open.
    config = ModConfig(
        enabled=dict(data.mods.enabled),
        profiles=list(data.mods.profiles),
        live_mods=None if data.mods.live_mods is None else list(data.mods.live_mods),
        extra=list(data.mods.extra),
    )
    mods = FrozenModConfig(config, config.mod_folders())
    result: Any = GameData(data.game_dir, data.cache_dir, data.mode, mods)
    result._index_fresh_metadata = True
    return cast(GameData, result)


def content_manifest(data: GameData, check: Callable[..., Any] = lambda: None) -> dict[Any, Any]:
    if type(data) is not GameData or not getattr(data, "_index_fresh_metadata", False):
        raise ValueError("cache needs fresh_data(), not Session's shared lazy GameData")
    roots = data.roots()
    facts, folders, material_presence = {}, [], []

    def add(path: Any) -> None:
        check()
        row = file_fact(path)
        facts[row["path"]] = row

    def members(directory: Any, predicate: Any, ordered: Any = False) -> Any:
        check()
        names = [p for p in directory.iterdir() if predicate(p)] if directory.is_dir() else []
        if not ordered:
            names.sort()
        folders.append(
            dict(
                path=str(directory.absolute()),
                exists=directory.is_dir(),
                selected_names=[p.name for p in names],
                order_matters=ordered,
            )
        )
        return names

    for root in roots:
        dat = root / "resources/_common/dat"
        for name in ("civilizations.json", "eras.json", "unitlines.json", "unitLines.json"):
            add(dat / name)
        for path in members(dat / "CivTechTrees", lambda p: p.suffix == ".json"):
            add(path)
        langs = members(root / "resources", lambda p: bool(re.fullmatch("[a-z]{2}", p.name)))
        # English baked master/civ/tech names must include missing→present changes.
        lang_names = sorted({"en", *(p.name for p in langs)})
        for lang in lang_names:
            kv = root / "resources" / lang / "strings/key-value"
            for fixed in ("key-value-strings-utf8.txt", "key-value-modded-strings-utf8.txt"):
                add(kv / fixed)
            for path in members(kv, lambda p: p.suffix == ".txt"):
                add(path)
        materials = root / "widgetui/materials.json"
        add(materials)
        try:
            raw = json.loads(materials.read_text())
        except (OSError, ValueError):
            raw = {}
        if isinstance(raw, dict):
            # These are the only texture references _material_files can inspect.
            textures = [
                t
                for atlas in raw.get("AtlasTextures", [])
                for t in (atlas.get("AtlasDef") or {}).get("Textures", [])
            ]
            textures += [
                t.get("TextureDef") for t in raw.get("GlobalTextures", []) if isinstance(t, dict)
            ]
            for texture in textures:
                if isinstance(texture, dict) and texture.get("FileName"):
                    path = root / "widgetui" / str(texture["FileName"])
                    if path.suffix.lower() == ".png":
                        material_presence.append(
                            dict(path=str(path.absolute()), is_file=path.is_file())
                        )
    # CivTechTrees can use a referenced filename, including a relative subfolder.
    tree_dir = data.dat_path("CivTechTrees")
    civ_path = data.dat_path("civilizations.json")
    try:
        civs = json.loads(civ_path.read_text()).get("civilization_list", []) if civ_path else []
    except (OSError, ValueError):
        civs = []
    for civ in civs:
        if isinstance(civ, dict) and civ.get("tech_tree_name") and tree_dir is not None:
            add(tree_dir / f"{civ['tech_tree_name']}.json")
    mod_folders = data.mods.mod_folders()
    if data.game_dir is not None:
        common = data.game_dir / "resources/_common"
        palettes = common / "palettes"
        for name in ("original.pal", *(f"playercolor_{n}.pal" for n in PLAYER_COLOR_FILES)):
            add(palettes / name)
        add(common / "terrain/colorcorrection_json/colorcorrection.json")
        add(common / "drs/gamedata_x2/random_map.def")
        map_dirs = [common / "drs/gamedata_x2", common / "random-map-scripts"]
        map_dirs += [m / "resources/_common/random-map-scripts" for m in mod_folders]
        for directory in map_dirs:
            # _map_script picks case-insensitively in actual directory order.
            for path in members(directory, lambda p: p.suffix.lower() == ".rms", ordered=True):
                add(path)
    return dict(
        schema=1,
        game_dir=str(data.game_dir) if data.game_dir else None,
        mode=data.mode,
        game=data.game,
        roots=[str(p.absolute()) for p in roots],
        effective_mod_order=[str(p.absolute()) for p in mod_folders],
        files=sorted(facts.values(), key=lambda r: r["path"]),
        enumerated_directories=folders,
        material_png_presence=material_presence,
        independent_payloads="renderer texture/audio/particle bytes and main engine DAT",
    )
