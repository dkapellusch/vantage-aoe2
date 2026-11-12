"""Game sprites for the world view: SLD files rendered to per-facing PNG strips.

The browser asks for ``(sprite, facing, player colour)``; the answer is one PNG
holding that facing's animation frames side by side, every cell sharing the
sprite's hotspot, plus a small JSON description. Strips are cached on disk, so
each combination is decoded once per machine.

Variants the browser may ask for (parsed by :func:`strip_options`): a damage
level (the SLD damage mask at 25/50/75 % of hit points lost), a single layer
(``main`` without the shadow, or ``shadow`` alone) so the shadow can be filtered
separately, and the player mask (``pm``: the strip uncoloured, its player-colour
mask below it, for a browser that applies the colour itself). Mod graphics
folders (``extra_dirs``) are searched before the game's own; the cache key
carries a hash of the mod set.
"""

from __future__ import annotations

import hashlib
import json
import multiprocessing
import re
import threading
from collections.abc import Mapping, Sequence
from concurrent.futures import Future, ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from vantage import smx as smx_mod
from vantage.assetcache import SingleFlight, atomic_write
from vantage.gamedata import _png
from vantage.patch import Node
from vantage.schema import SCHEMA
from vantage.sld import LAYER_PLAYER, SLD, player_mask, render
from vantage.smx import SMX

#: Long animations are thinned to at most this many frames per strip.
MAX_FRAMES = 30

#: Damage levels the browser asks for: hit points lost, as a fraction.
#: Damage amounts (fraction of hit points lost) strips are shaded at; the browser
#: asks for the nearest by index (``&dmg=``).
DAMAGE_LEVELS = (0.0, 0.2, 0.4, 0.6, 0.8, 1.0)
#: Single-layer strips: everything (default), the graphic alone, the shadow alone.
LAYERS = ("all", "main", "shadow")


def strip_options(query: Mapping[str, str]) -> dict[str, Any]:
    """Keyword arguments for :meth:`SpriteStore.strip` from a sprite URL's query.

    ``dmg`` is a damage level index into :data:`DAMAGE_LEVELS`, ``layer`` one of
    :data:`LAYERS`. Unknown or malformed values fall back to the plain strip.
    """
    out: dict[str, Any] = {}
    dmg = str(query.get("dmg", "") or "")
    if dmg.isdigit() and 0 < int(dmg) < len(DAMAGE_LEVELS):
        out["damage"] = int(dmg)
    layer = str(query.get("layer", "") or "")
    if layer in LAYERS[1:]:
        out["layer"] = layer
    if query.get("dir") == "1":
        out["directional"] = True
    if query.get("pm") == "1":
        out["player_mask"] = True
    return out


def _graphics_dirs(root: Path) -> list[Path]:
    """Graphics folders inside a mod root (or the folder itself)."""
    cands = (
        root / "resources" / "_common" / "drs" / "graphics",
        root / "drs" / "graphics",
        root / "graphics",
        root,
    )
    return [c for c in cands if c.is_dir()]


@dataclass(frozen=True, slots=True)
class SpriteInfo:
    id: int
    name: str
    frames: int  # frames per facing
    facets: int
    duration: float  # seconds per frame (game time)


#: Bumped whenever decoding changes what a strip looks like, so strips cached
#: on disk by an older version are rendered again (3: degenerate SLD blocks filled;
#: 4: inter-frame reuse across differing rectangles; 5: shadow parts as shade;
#: 6: damage shading as the game's shader; 7: inter-frame reuse within a facing;
#: 8: meta "pc", whether a strip has any player colour; 9: a facing's first frame
#: with no pixels of its own repeats the frame before it).
RENDER_VERSION = 9


#: Worker processes rendering strips (shared by every store in the process). A
#: strip is ~30 ms of pure-Python SLD decoding; one at a time, the first view of a
#: busy battle took ~10 s to fill in. Spawned (not forked: the server has threads).
_POOL: ProcessPoolExecutor | None = None
_POOL_LOCK = threading.Lock()
#: Sprite files (SLD or SMX) opened by this (worker) process, by path.
_WORKER_SLDS: dict[str, SLD | SMX] = {}


def _open_sprite(path: Path, game_dir: Path | None) -> SLD | SMX:
    """Open a sprite by extension; SMX frames need the game's palettes."""
    return SMX.open(path, game_dir) if path.suffix.lower() == ".smx" else SLD.open(path)


def _render_frame(
    sprite: SLD | SMX,
    index: int,
    rgb: tuple[int, int, int] | None,
    shadow: bool,
    main: bool,
    damage: float,
) -> tuple[int, int, int, int, bytearray]:
    if isinstance(sprite, SMX):
        return smx_mod.render(sprite, index, rgb, shadow, main=main, damage=damage)
    return render(sprite, index, rgb, shadow, main=main, damage=damage)


def _pool(workers: int) -> ProcessPoolExecutor:
    global _POOL
    with _POOL_LOCK:
        if _POOL is None:
            _POOL = ProcessPoolExecutor(
                max_workers=workers, mp_context=multiprocessing.get_context("spawn")
            )
            # Start every worker now (each takes about a second to import): a pool
            # spawns one per job submitted while none is idle, so these do.
            for _ in range(workers):
                _POOL.submit(_noop)
        return _POOL


def _noop() -> None:
    """A job that only makes the pool start a worker."""


def _drop_pool() -> None:
    global _POOL
    with _POOL_LOCK:
        if _POOL is not None:
            _POOL.shutdown(wait=False, cancel_futures=True)
        _POOL = None


def _soften_black(px: bytearray, alpha: int = 110) -> None:
    """Turn pure-black opaque pixels into translucent shade (in place)."""
    for k in range(0, len(px), 4):
        if px[k + 3] > alpha and px[k] < 10 and px[k + 1] < 10 and px[k + 2] < 10:
            px[k + 3] = alpha


def _render_job(
    path: str,
    info: SpriteInfo,
    facet: int,
    rgb: tuple[int, int, int] | None,
    damage: float,
    layer: str,
    game_dir: str | None = None,
    with_mask: bool = False,
) -> tuple[bytes, dict[str, Any]] | None:
    """One strip, in a worker process (see :meth:`SpriteStore.strip`)."""
    sld = _WORKER_SLDS.get(path)
    if sld is None:
        if len(_WORKER_SLDS) > 32:
            _WORKER_SLDS.clear()
        sld = _WORKER_SLDS[path] = _open_sprite(Path(path), Path(game_dir) if game_dir else None)
    return SpriteStore._render_strip(sld, info, facet, rgb, damage, layer, with_mask)


class SpriteStore:
    def __init__(
        self,
        game_dir: Path | None,
        cache_dir: Path,
        mode: str | None = None,
        extra_dirs: Sequence[Path] = (),
        workers: int = 0,
    ) -> None:
        self.mode = mode
        self.game_dir = game_dir
        #: Render strips in this many worker processes (0: in this process).
        self.workers = workers
        #: Sprite-mod roots, searched before the game (first wins). Each may be
        #: a mod folder (``<mod>/resources/_common/drs/graphics``) or a folder
        #: of ``.sld`` files.
        self.extra_dirs = [Path(d) for d in extra_dirs]
        self.mod_graphics = [g for d in self.extra_dirs for g in _graphics_dirs(d)]
        self.mod_key = (
            hashlib.sha1("\n".join(str(d) for d in self.extra_dirs).encode()).hexdigest()[:8]
            if self.extra_dirs
            else ""
        )
        self.graphics = (
            game_dir / "resources" / "_common" / "drs" / "graphics" if game_dir else None
        )
        #: Game modes (Return of Rome = modes/Pompeii) ship their own graphics;
        #: the active mode's folder is searched first.
        self.mode_graphics = (
            sorted(
                game_dir.glob("modes/*/resources/_common/drs/graphics"),
                key=lambda p: (p.parents[3].name != mode, str(p)),
            )
            if game_dir
            else []
        )
        self.cache = cache_dir / "sprites"
        self._open: dict[str, SLD | SMX] = {}
        self._lock = threading.Lock()
        #: Strips being rendered, by cache key: a second request waits for the first.
        self._rendering: SingleFlight[tuple[bytes, dict[str, Any]] | None] = SingleFlight()

    def resolve(self, name: str, hd: bool = False) -> Path | None:
        """The SLD (or SMX) for a sprite-table name: standard resolution, or UHD (x2)
        when ``hd``. A mod's file wins over the game's; within one folder and name
        ``.sld`` wins over ``.smx``."""
        if (self.graphics is None and not self.mod_graphics) or not name:
            return None
        base = name[:-3] if name[-3:] in ("_x1", "_x2") else name
        order = (
            (f"{base}_x2", f"{name}", f"{base}_x1", f"{base}")
            if hd
            else (f"{base}_x1", f"{name}", f"{base}_x2", f"{base}")
        )
        game = [self.graphics] if self.graphics is not None else []
        folders = [*self.mode_graphics, *game] if self.mode else [*game, *self.mode_graphics]
        for folder in (*self.mod_graphics, *folders):
            for stem in order:
                for ext in (".sld", ".smx"):
                    p = folder / (stem + ext)
                    if p.is_file():
                        return p
        return None

    def strip(
        self,
        info: SpriteInfo,
        facet: int,
        rgb: tuple[int, int, int] | None,
        color_key: str,
        hd: bool = False,
        damage: int = 0,
        layer: str = "all",
        directional: bool = False,
        player_mask: bool = False,
    ) -> tuple[bytes, dict[str, Any]] | None:
        """One facing's animation strip: ``(png, meta)``, or None without an SLD.

        ``player_mask``: no colour (``rgb`` is ignored); the strip is twice as tall,
        each frame's player-colour mask (grey levels) under it, and meta ``pm`` says
        so. SMX sprites have no mask to give: they come coloured as asked.

        ``directional``: ``facet`` is a unit's heading (cached apart from the same
        number used as a building variant: a wall piece, a house style).

        ``damage`` indexes :data:`DAMAGE_LEVELS`; ``layer`` is one of :data:`LAYERS`.
        """
        # The engine uses "None" sprites as effect/draw-list containers. Their
        # missing file is intentional, so answer a settled transparent strip.
        base = info.name.removesuffix("_x1").removesuffix("_x2").lower()
        if base in _NO_PICTURE:
            return _png(1, 1, bytes(4)), {
                "cw": 1,
                "ch": 1,
                "ax": 0,
                "ay": 0,
                "n": 1,
                "step": 1,
                "per": 1,
                "duration": 0,
                "pc": False,
                "empty": True,
            }
        damage = damage if 0 <= damage < len(DAMAGE_LEVELS) else 0
        layer = layer if layer in LAYERS else "all"
        # Sprite ids are per game (Return of Rome reuses them), so the SLD name
        # is part of the key; so are the variant and the mod set.
        name = re.sub(r"[^\w-]", "_", info.name)
        # "_dir": a unit heading (mapped to the SLD's facing order), never sharing a
        # cache file with the same number used as a building variant.
        heading = "_hdg" if directional else ""
        hd_tag = "_hd" if hd else ""
        key = f"r{RENDER_VERSION}_{name}_{info.id}_{facet}{heading}_{color_key}{hd_tag}"
        if damage:
            key += f"_d{damage}"
        if layer != "all":
            key += f"_{layer}"
        if player_mask:
            key += "_pm"
        if self.mod_key:
            key += f"_m{self.mod_key}"
        png_path = self.cache / f"{key}.png"
        meta_path = self.cache / f"{key}.json"
        if png_path.is_file() and meta_path.is_file():
            return png_path.read_bytes(), json.loads(meta_path.read_text(encoding="utf-8"))
        return self._rendering.run(
            key,
            lambda: self._render_and_cache(
                info, facet, rgb, hd, damage, layer, player_mask, png_path, meta_path
            ),
        )

    def _render_and_cache(
        self,
        info: SpriteInfo,
        facet: int,
        rgb: tuple[int, int, int] | None,
        hd: bool,
        damage: int,
        layer: str,
        player_mask: bool,
        png_path: Path,
        meta_path: Path,
    ) -> tuple[bytes, dict[str, Any]] | None:
        """Render one strip and store it (:meth:`strip` once per key at a time)."""
        if png_path.is_file() and meta_path.is_file():  # finished just before this call
            return png_path.read_bytes(), json.loads(meta_path.read_text(encoding="utf-8"))
        path = self.resolve(info.name, hd)
        if path is None:
            return None
        mask = player_mask and path.suffix.lower() == ".sld"
        if mask:
            rgb = None
        level = DAMAGE_LEVELS[damage]
        pooled, got = self._render_pooled(path, info, facet, rgb, level, layer, mask)
        if not pooled:
            with self._lock:
                sld = self._open.get(str(path))
                if sld is None:
                    sld = _open_sprite(path, self.game_dir)
                    if len(self._open) > 48:
                        self._open.clear()
                    self._open[str(path)] = sld
                got = self._render_strip(sld, info, facet, rgb, DAMAGE_LEVELS[damage], layer, mask)
        if got is None:
            return None
        png, meta = got
        if layer != "all":
            meta["layer"] = layer
        if damage:
            meta["damage"] = damage
        # The PNG first: a strip counts as cached once its meta file exists.
        if atomic_write(png_path, png):
            atomic_write(meta_path, json.dumps(meta).encode())
        return png, meta

    def _render_pooled(
        self,
        path: Path,
        info: SpriteInfo,
        facet: int,
        rgb: tuple[int, int, int] | None,
        damage: float,
        layer: str,
        with_mask: bool = False,
    ) -> tuple[bool, tuple[bytes, dict[str, Any]] | None]:
        """Render in the worker pool: (rendered there, strip); not rendered when
        there is no pool or it broke."""
        if self.workers <= 0:
            return False, None
        try:
            fut: Future[tuple[bytes, dict[str, Any]] | None] = _pool(self.workers).submit(
                _render_job,
                str(path),
                info,
                facet,
                rgb,
                damage,
                layer,
                str(self.game_dir) if self.game_dir else None,
                with_mask,
            )
            return True, fut.result(timeout=120)
        except (BrokenProcessPool, RuntimeError, OSError):
            _drop_pool()  # the next strip starts a fresh pool; this one renders here
            return False, None

    @staticmethod
    def _render_strip(
        sld: SLD | SMX,
        info: SpriteInfo,
        facet: int,
        rgb: tuple[int, int, int] | None,
        damage: float = 0.0,
        layer: str = "all",
        with_mask: bool = False,
    ) -> tuple[bytes, dict[str, Any]] | None:
        per = max(1, info.frames)
        facets = max(1, info.facets)
        if sld.count < per * facets:
            # Fewer frames than the table claims: treat the file as one facing.
            per, facets = sld.count, 1
        if isinstance(sld, SLD):
            sld.set_frames_per_facing(per)
        # A unit's heading indexes the SLD's facings directly (verified against the
        # game's own view, with the map in the game's orientation: screen y grows
        # with tile y - x). An earlier ``-g`` here compensated for a mirrored map.
        facet = facet % facets
        step = max(1, -(-per // MAX_FRAMES))
        indices = [facet * per + i for i in range(0, per, step) if facet * per + i < sld.count]
        if not indices:
            return None
        rendered = [
            _render_frame(sld, i, rgb, layer != "main", layer != "shadow", damage) for i in indices
        ]
        if "_shadow" in info.name:
            # A "<building>_shadow" part (a town centre's floor piece) paints its cast
            # shadow as opaque black in the main layer; the game shows it as shade.
            for _, _, _, _, px in rendered:
                _soften_black(px)
        # Union of every frame's opaque box, relative to its hotspot.
        left = top = 1 << 30
        right = bottom = -(1 << 30)
        boxes = []
        for w, h, hx, hy, px in rendered:
            bx0, by0, bx1, by1 = _bbox(w, h, px)
            boxes.append((bx0, by0, bx1, by1))
            if bx1 > bx0:
                left, top = min(left, bx0 - hx), min(top, by0 - hy)
                right, bottom = max(right, bx1 - hx), max(bottom, by1 - hy)
        if right <= left:
            return None
        cw, ch = right - left, bottom - top
        # With the player mask, a second band of the same frames below: grey levels
        # (opaque, so premultiplying never touches them).
        masks = None
        if with_mask and isinstance(sld, SLD):
            masks = [player_mask(sld, i) for i in indices]
        sheet = bytearray(cw * len(rendered) * ch * 4 * (2 if masks else 1))
        stride = cw * len(rendered) * 4
        for n, ((w, _h, hx, hy, px), (bx0, by0, bx1, by1)) in enumerate(
            zip(rendered, boxes, strict=True)
        ):
            if bx1 <= bx0:
                continue
            for y in range(by0, by1):
                src = (y * w + bx0) * 4
                row = px[src : src + (bx1 - bx0) * 4]
                dy = y - hy - top
                dx = n * cw + (bx0 - hx - left)
                o = dy * stride + dx * 4
                sheet[o : o + len(row)] = row
                if masks is not None:
                    # Grey levels: each mask byte to R, G and B, alpha opaque, by
                    # strided slices rather than a Python loop per pixel.
                    mrow = masks[n][y * w + bx0 : y * w + bx1]
                    mo = o + ch * stride
                    end = mo + len(mrow) * 4
                    sheet[mo:end:4] = mrow
                    sheet[mo + 1 : end : 4] = mrow
                    sheet[mo + 2 : end : 4] = mrow
                    sheet[mo + 3 : end : 4] = b"\xff" * len(mrow)
        meta = {
            "cw": cw,
            "ch": ch,
            "ax": -left,
            "ay": -top,
            "n": len(rendered),
            "step": step,
            "per": per,
            "duration": info.duration,
            # Any player colour in these frames? A strip without (most projectiles)
            # looks the same for every player: the browser asks for one copy.
            "pc": not isinstance(sld, SLD)
            or any(sld.frames[i].layers & LAYER_PLAYER for i in indices),
        }
        if masks is not None:
            meta["pm"] = True
        return _png(cw * len(rendered), ch * (2 if masks else 1), bytes(sheet)), meta


def _bbox(w: int, h: int, px: bytearray) -> tuple[int, int, int, int]:
    x0, y0, x1, y1 = w, h, 0, 0
    for y in range(h):
        row = px[y * w * 4 : (y + 1) * w * 4]
        alpha = row[3::4]
        if not any(alpha):
            continue
        xs = [i for i, a in enumerate(alpha) if a]
        x0, x1 = min(x0, xs[0]), max(x1, xs[-1] + 1)
        y0, y1 = min(y0, y), max(y1, y + 1)
    return x0, y0, x1, y1


# -- damage graphics ---------------------------------------------------------------
# A master's ``damageSprites`` lists (sprite, damage percent, apply mode) rows.
# Mode 2 replaces the entity's graphic (walls: ``*_destr_25``); 0 and 1 draw on
# top. Building fires are not SLDs: the damage sprite is an empty container
# ("F", "X", "None") whose ``drawList`` places flame sprites, and each flame
# sprite names the particle effect the game draws (``fire_medium_left``...) and
# carries the burning loop as its main sound event.

_DS_SPRITE = SCHEMA.fid(SCHEMA.model_id("DamageSpriteInfo"), "spriteId")
_DS_PCT = SCHEMA.fid(SCHEMA.model_id("DamageSpriteInfo"), "damagePercent")
_DS_FLAG = SCHEMA.fid(SCHEMA.model_id("DamageSpriteInfo"), "flag")
_M_DAMAGE = SCHEMA.fid(SCHEMA.model_id("MasterEntity"), "damageSprites")
_SP_NAME = SCHEMA.fid(SCHEMA.model_id("Sprite"), "pictName")
_SP_DRAW = SCHEMA.fid(SCHEMA.model_id("Sprite"), "drawList")
_SP_PARTICLE = SCHEMA.fid(SCHEMA.model_id("Sprite"), "particleEffectName")
_SP_SOUND = SCHEMA.fid(SCHEMA.model_id("Sprite"), "mainSoundEvent")
_SD_SPRITE = SCHEMA.fid(SCHEMA.model_id("DeltaSprite"), "spriteId")
_SD_OX = SCHEMA.fid(SCHEMA.model_id("DeltaSprite"), "offsetX")
_SD_OY = SCHEMA.fid(SCHEMA.model_id("DeltaSprite"), "offsetY")
_SE_ID = SCHEMA.fid(SCHEMA.model_id("SoundEvent"), "eventId")
#: Placeholder picture names of sprites that only carry a draw list.
_NO_PICTURE = frozenset({"", "none", "f", "x"})


def _sprite_node(sprites: Sequence[Node | None], sid: int) -> Node | None:
    if 0 <= sid < len(sprites):
        node = sprites[sid]
        return node if isinstance(node, Node) else None
    return None


def has_picture(sprite: Node) -> bool:
    """True when a sprite names a real graphic (not a draw-list container)."""
    name = str(sprite.fields.get(_SP_NAME, "") or "")
    base = name[:-3] if name[-3:] in ("_x1", "_x2") else name
    return base.lower() not in _NO_PICTURE


def damage_graphics(master: Node, sprites: Sequence[Node | None]) -> list[dict[str, Any]]:
    """A master's damage graphics, by increasing damage percent.

    Each entry: ``pct`` (shown once this share of hit points is lost), ``mode``
    (2 = replaces the graphic), ``sprite`` (an SLD sprite id, or -1), ``sound``
    (a looping Wwise event while shown, 0 = none) and ``parts``: flames as
    ``[sprite id, particle effect name or "", offset_x, offset_y]`` in x1 pixels.
    ``sprites`` is ``World.sprites`` (indexed by sprite id).
    """
    out: list[dict[str, Any]] = []
    for ds in master.fields.get(_M_DAMAGE) or ():
        if not isinstance(ds, Node):
            continue
        sid = int(ds.fields.get(_DS_SPRITE, -1))
        sp = _sprite_node(sprites, sid)
        if sp is None:
            continue
        parts: list[list[Any]] = []
        sound = 0
        for d in sp.fields.get(_SP_DRAW) or ():
            if not isinstance(d, Node):
                continue
            psid = int(d.fields.get(_SD_SPRITE, -1))
            part = _sprite_node(sprites, psid)
            if part is None or psid == sid:
                continue
            particle = str(part.fields.get(_SP_PARTICLE, "") or "")
            if not particle and not has_picture(part):
                continue
            parts.append(
                [psid, particle, int(d.fields.get(_SD_OX, 0)), int(d.fields.get(_SD_OY, 0))]
            )
            sound = sound or _event(part)
        own = has_picture(sp)
        if not parts and not own:
            continue
        out.append(
            {
                "pct": int(ds.fields.get(_DS_PCT, 0)),
                "mode": int(ds.fields.get(_DS_FLAG, 0)),
                "sprite": sid if own else -1,
                "sound": _event(sp) or sound,
                "parts": parts,
            }
        )
    out.sort(key=lambda e: e["pct"])
    return out


def _event(sprite: Node) -> int:
    se = sprite.fields.get(_SP_SOUND)
    return int(se.fields.get(_SE_ID, 0) or 0) if isinstance(se, Node) else 0


def _delta_row(p: Node) -> list[int]:
    f = p.fields
    return [int(f.get(_SD_SPRITE, -1)), int(f.get(_SD_OX) or 0), int(f.get(_SD_OY) or 0)]


def sprite_deltas(world_sprites: Sequence[Node | None]) -> dict[int, list[list[int]]]:
    """Composite sprites: sprite id -> its ``drawList`` parts ``[sprite, dx, dy]``.

    The game streams a building's root sprite only; a palisade wall's root is
    its flag, whose draw list adds the wall body (the piece shape follows the
    facing) below it. Parts are drawn in list order, a part naming the sprite
    itself standing for its own frames. Sprites whose list is only themselves
    are left out.
    """
    out: dict[int, list[list[int]]] = {}
    for sid, sp in enumerate(world_sprites):
        if not isinstance(sp, Node):
            continue
        parts = sp.fields.get(_SP_DRAW)
        if not parts:
            continue
        rows = [_delta_row(p) for p in parts if isinstance(p, Node)]
        rows = [r for r in rows if r[0] >= 0]
        if any(r[0] != sid for r in rows):
            out[sid] = rows
    return out
