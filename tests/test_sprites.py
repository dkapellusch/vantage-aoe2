"""vantage.sprites: per-facing sprite strips with caching."""

from __future__ import annotations

import struct
import zlib
from pathlib import Path
from typing import Any

from tests.test_sld import FULL, GREY, RED, _layer, _sld
from vantage.patch import Node
from vantage.schema import SCHEMA
from vantage.sld import LAYER_DAMAGE, LAYER_MAIN, LAYER_PLAYER, LAYER_SHADOW
from vantage.sprites import (
    RENDER_VERSION,
    SpriteInfo,
    SpriteStore,
    damage_graphics,
    has_picture,
    strip_options,
)


def _install(tmp_path: Path, frames: int) -> Path:
    gfx = tmp_path / "game" / "resources" / "_common" / "drs" / "graphics"
    gfx.mkdir(parents=True)
    rect = (0, 0, 4, 4)
    layers = [(LAYER_MAIN, [_layer(rect, 0, [(0, 1)], [RED])]) for _ in range(frames)]
    (gfx / "u_test_idle_x1.sld").write_bytes(_sld(layers))
    return tmp_path / "game"


def test_strip_metadata_and_cache(tmp_path: Path) -> None:
    store = SpriteStore(_install(tmp_path, 4), tmp_path / "cache")
    assert store.resolve("u_test_idle_x2") is not None  # x2 name falls back to the x1 file
    assert store.resolve("missing_x2") is None
    info = SpriteInfo(7, "u_test_idle_x2", frames=2, facets=2, duration=0.1)
    got = store.strip(info, 1, (0, 0, 255), "0")
    assert got is not None
    png, meta = got
    assert png.startswith(b"\x89PNG")
    assert struct.unpack(">II", png[16:24]) == (8, 4)  # two 4x4 cells side by side
    assert meta == {
        "cw": 4,
        "ch": 4,
        "ax": 4,
        "ay": 6,
        "n": 2,
        "step": 1,
        "per": 2,
        "duration": 0.1,
        "pc": False,  # no player-colour layer: one copy serves every player
    }
    # Keyed by SLD name too: Return of Rome reuses AoE2's sprite ids.
    cached = tmp_path / "cache" / "sprites" / f"r{RENDER_VERSION}_u_test_idle_x2_7_1_0.png"
    assert cached.is_file()
    assert store.strip(info, 1, (0, 0, 255), "0") == got  # served from the cache


def test_thinning_and_short_files(tmp_path: Path) -> None:
    store = SpriteStore(_install(tmp_path, 3), tmp_path / "cache")
    # The table claims 60 frames x 2 facings but the file has 3: one facing.
    got = store.strip(SpriteInfo(1, "u_test_idle", 60, 2, 0.05), 1, None, "-1")
    assert got is not None and got[1]["per"] == 3 and got[1]["n"] == 3
    assert SpriteStore(None, tmp_path).resolve("u_test_idle") is None


def test_active_mode_graphics_win(tmp_path: Path) -> None:
    game = _install(tmp_path, 1)
    base = game / "resources" / "_common" / "drs" / "graphics" / "u_test_idle_x1.sld"
    for mode in ("Antiquity", "Pompeii"):
        gfx = game / "modes" / mode / "resources" / "_common" / "drs" / "graphics"
        gfx.mkdir(parents=True)
        (gfx / "u_test_idle_x1.sld").write_bytes(base.read_bytes())
        (gfx / "only_here_x1.sld").write_bytes(base.read_bytes())
    pompeii = game / "modes" / "Pompeii" / "resources" / "_common" / "drs" / "graphics"
    assert SpriteStore(game, tmp_path / "c").resolve("u_test_idle") == base
    rome = SpriteStore(game, tmp_path / "c", mode="Pompeii")
    assert rome.resolve("u_test_idle") == pompeii / "u_test_idle_x1.sld"
    assert rome.resolve("only_here") == pompeii / "only_here_x1.sld"


def test_mod_dirs_searched_first_and_keyed(tmp_path: Path) -> None:
    game = _install(tmp_path, 2)
    mod = tmp_path / "mods" / "blue" / "resources" / "_common" / "drs" / "graphics"
    mod.mkdir(parents=True)
    loose = tmp_path / "loose"
    loose.mkdir()
    base = game / "resources" / "_common" / "drs" / "graphics" / "u_test_idle_x1.sld"
    (mod / "u_test_idle_x1.sld").write_bytes(base.read_bytes())
    (loose / "only_loose_x1.sld").write_bytes(base.read_bytes())
    store = SpriteStore(game, tmp_path / "cache", extra_dirs=[tmp_path / "mods" / "blue", loose])
    assert store.resolve("u_test_idle") == mod / "u_test_idle_x1.sld"
    assert store.resolve("only_loose") == loose / "only_loose_x1.sld"
    assert SpriteStore(game, tmp_path / "cache").resolve("only_loose") is None
    # A different mod set never reads another set's cached strips.
    assert store.strip(SpriteInfo(3, "u_test_idle", 2, 1, 0.1), 0, None, "-1") is not None
    cache = tmp_path / "cache" / "sprites"
    assert len(list(cache.glob(f"r{RENDER_VERSION}_u_test_idle_3_0_-1_m*.png"))) == 1
    assert not (cache / f"r{RENDER_VERSION}_u_test_idle_3_0_-1.png").exists()
    # Mods alone (no game install) still resolve.
    assert SpriteStore(None, tmp_path / "c2", extra_dirs=[loose]).resolve("only_loose") is not None


def test_damage_and_layer_variants(tmp_path: Path) -> None:
    gfx = tmp_path / "game" / "resources" / "_common" / "drs" / "graphics"
    gfx.mkdir(parents=True)
    rect = (0, 0, 4, 4)
    frame = [
        _layer(rect, 0, [(0, 1)], [GREY]),
        _layer((0, 4, 4, 8), 0, [(0, 1)], [FULL]),
        _layer(None, 0, [(0, 1)], [RED]),
    ]
    (gfx / "b_test_x1.sld").write_bytes(_sld([(LAYER_MAIN | LAYER_SHADOW | LAYER_DAMAGE, frame)]))
    store = SpriteStore(tmp_path / "game", tmp_path / "cache")
    info = SpriteInfo(9, "b_test", 1, 1, 0.0)
    plain = store.strip(info, 0, None, "-1")
    worn = store.strip(info, 0, None, "-1", damage=3)
    shadow = store.strip(info, 0, None, "-1", layer="shadow")
    main = store.strip(info, 0, None, "-1", layer="main")
    assert plain and worn and shadow and main
    assert worn[0] != plain[0] and worn[1]["damage"] == 3 and "damage" not in plain[1]
    assert shadow[1]["layer"] == "shadow" and main[1]["layer"] == "main"
    assert (shadow[1]["ch"], main[1]["ch"]) == (4, 4)  # each crops to its own layer
    assert (tmp_path / "cache" / "sprites" / f"r{RENDER_VERSION}_b_test_9_0_-1_d3.png").is_file()
    # Out-of-range variants fall back to the plain strip.
    assert store.strip(info, 0, None, "-1", damage=9, layer="bogus") == plain


def _pixels(png: bytes) -> tuple[int, int, bytes]:
    """(width, height, RGBA) of a strip PNG (sprites write filter-0 rows)."""
    w, h = struct.unpack(">II", png[16:24])
    raw = zlib.decompress(png[png.index(b"IDAT") + 4 :])
    stride = w * 4
    return w, h, b"".join(raw[y * (stride + 1) + 1 : (y + 1) * (stride + 1)] for y in range(h))


def test_player_mask_strip_reproduces_the_server_tint(tmp_path: Path) -> None:
    """``pm``: the uncoloured strip with its player mask in a band below; the
    browser's GPU tint (sprite-gl.js) applied to them gives the coloured strip."""
    gfx = tmp_path / "game" / "resources" / "_common" / "drs" / "graphics"
    gfx.mkdir(parents=True)
    rect = (0, 0, 8, 4)  # a red block, then a grey one
    half = bytes([128, 0]) + b"\x00" * 6  # BC4: every pixel 128
    frame = [_layer(rect, 0, [(0, 2)], [RED, GREY]), _layer(None, 0, [(0, 2)], [half, FULL])]
    (gfx / "u_pm_x1.sld").write_bytes(_sld([(LAYER_MAIN | LAYER_PLAYER, frame)]))
    store = SpriteStore(tmp_path / "game", tmp_path / "cache")
    info = SpriteInfo(11, "u_pm", 1, 1, 0.0)
    rgb = (40, 90, 230)
    coloured = store.strip(info, 0, rgb, "3")
    masked = store.strip(info, 0, rgb, "-1", player_mask=True)
    assert coloured and masked
    assert masked[1]["pm"] is True and "pm" not in coloured[1]
    assert masked[1]["ch"] == coloured[1]["ch"] == 4
    w, h, want = _pixels(coloured[0])
    mw, mh, got = _pixels(masked[0])
    assert (mw, mh) == (w, 2 * h)  # the mask band doubles the height
    for k in range(0, w * h * 4, 4):
        base, m = got[k : k + 4], got[w * h * 4 + k] / 255
        lum = (0.3 * base[0] + 0.6 * base[1] + 0.1 * base[2]) / 255 * 1.6
        for c in range(3):
            tinted = min(255.0, base[c] * (1 - m) + rgb[c] * lum * m)
            assert abs(tinted - want[k + c]) <= 1.5
        assert base[3] == want[k + 3]
    # Cached apart from the coloured strips.
    assert (tmp_path / "cache" / "sprites" / f"r{RENDER_VERSION}_u_pm_11_0_-1_pm.png").is_file()


def test_strip_options() -> None:
    assert strip_options({"pm": "1", "dir": "1"}) == {"player_mask": True, "directional": True}
    assert strip_options({}) == {}
    assert strip_options({"dmg": "2", "layer": "shadow"}) == {"damage": 2, "layer": "shadow"}
    assert strip_options({"dmg": "0", "layer": "all"}) == {}
    assert strip_options({"dmg": "7", "layer": "x"}) == {}
    assert strip_options({"dmg": "-1"}) == {}


def _node(model: str, **values: object) -> Node:
    mid = SCHEMA.model_id(model)
    return Node(mid, {SCHEMA.fid(mid, k): v for k, v in values.items()})


def test_damage_graphics() -> None:
    sprites: list[Node | None] = [None] * 10
    sprites[1] = _node(
        "Sprite",
        pictName="FLM1B_NN_x2",
        particleEffectName="fire_small_left",
        mainSoundEvent=_node("SoundEvent", eventId=77),
    )
    sprites[2] = _node(
        "Sprite",
        pictName="F",
        drawList=[
            _node("DeltaSprite", spriteId=1, offsetX=-41, offsetY=-29),
            _node("DeltaSprite", spriteId=1, offsetX=5),
            _node("DeltaSprite", spriteId=8),  # missing sprite: skipped
        ],
    )
    sprites[3] = _node("Sprite", pictName="b_wall_destr_25_x1")
    sprites[4] = _node("Sprite", pictName="None")  # nothing to draw: dropped
    master = _node(
        "MasterBuildingEntity",
        damageSprites=[
            _node("DamageSpriteInfo", spriteId=3, damagePercent=50, flag=2),
            _node("DamageSpriteInfo", spriteId=2, damagePercent=25),
            _node("DamageSpriteInfo", spriteId=4, damagePercent=75),
            _node("DamageSpriteInfo", spriteId=-1, damagePercent=90),
        ],
    )
    assert damage_graphics(master, sprites) == [
        {
            "pct": 25,
            "mode": 0,
            "sprite": -1,
            "sound": 77,
            "parts": [[1, "fire_small_left", -41, -29], [1, "fire_small_left", 5, 0]],
        },
        {"pct": 50, "mode": 2, "sprite": 3, "sound": 0, "parts": []},
    ]
    assert damage_graphics(_node("MasterEntity"), sprites) == []
    assert has_picture(sprites[3]) and not has_picture(sprites[2])
    assert not has_picture(_node("Sprite", pictName="None_x2"))


def test_unit_heading_indexes_the_sld_facing(tmp_path: Path) -> None:
    """A unit heading is the SLD facing (with the map in the game's orientation),
    cached apart from the same number used as a building variant."""
    import zlib

    gfx = tmp_path / "game" / "resources" / "_common" / "drs" / "graphics"
    gfx.mkdir(parents=True)
    rect = (0, 0, 4, 4)
    colours = [GREY, GREY, GREY, RED]  # only SLD facing 3 is red
    layers = [(LAYER_MAIN, [_layer(rect, 0, [(0, 1)], [c])]) for c in colours]
    (gfx / "u_turn_x1.sld").write_bytes(_sld(layers))
    store = SpriteStore(tmp_path / "game", tmp_path / "cache")

    def first_pixel(facing: int, directional: bool = True) -> tuple[int, int, int]:
        info = SpriteInfo(9, "u_turn", frames=1, facets=4, duration=0.1)
        got = store.strip(info, facing, None, "-1", directional=directional)
        assert got is not None
        png = got[0]
        at, idat = 8, b""
        while at < len(png):
            n, kind = struct.unpack(">I4s", png[at : at + 8])
            if kind == b"IDAT":
                idat += png[at + 8 : at + 8 + n]
            at += 12 + n
        raw = zlib.decompress(idat)
        return raw[1], raw[2], raw[3]  # row 0: filter byte, then RGBA

    red, grey = first_pixel(3), first_pixel(1)
    assert red[0] > 200 and red[1] < 60  # heading 3 -> SLD facing 3 (red)
    assert abs(grey[0] - grey[1]) < 30  # heading 1 -> SLD facing 1 (grey)
    variant = first_pixel(3, directional=False)
    assert variant[0] > 200 and variant[1] < 60  # building facing 3 is SLD facing 3
    assert strip_options({"dir": "1"}) == {"directional": True}


def test_sprite_deltas_list_composite_parts() -> None:
    from vantage.sprites import sprite_deltas

    def sprite(name: str, *parts: tuple[int, int, int]) -> Node:
        fields: dict[int, object] = {SCHEMA.fid(SCHEMA.model_id("Sprite"), "pictName"): name}
        if parts:
            d_model = SCHEMA.model_id("DeltaSprite")
            fields[SCHEMA.fid(SCHEMA.model_id("Sprite"), "drawList")] = [
                Node(d_model, {
                    SCHEMA.fid(d_model, "spriteId"): s,
                    SCHEMA.fid(d_model, "offsetX"): x,
                    SCHEMA.fid(d_model, "offsetY"): y,
                })
                for s, x, y in parts
            ]  # fmt: skip
        return Node(SCHEMA.model_id("Sprite"), fields)

    flag = sprite("flag", (1, 0, 0), (2, 0, -40))
    table = [None, sprite("body"), flag, sprite("solo", (3, 0, 0))]
    # The wall's flag draws the body under itself; a list of only itself is no composite.
    assert sprite_deltas(table) == {2: [[1, 0, 0], [2, 0, -40]]}


def test_worker_processes_render_the_same_strip(tmp_path: Path) -> None:
    from vantage import sprites as SP

    game = _install(tmp_path, 4)
    info = SpriteInfo(7, "u_test_idle_x2", frames=2, facets=2, duration=0.1)
    here = SpriteStore(game, tmp_path / "c1").strip(info, 1, (0, 0, 255), "0")
    try:
        pooled = SpriteStore(game, tmp_path / "c2", workers=1).strip(info, 1, (0, 0, 255), "0")
    finally:
        SP._drop_pool()
    assert here is not None and pooled == here


def test_concurrent_requests_for_one_strip_render_it_once(tmp_path: Path, monkeypatch: Any) -> None:
    import threading
    import time

    store = SpriteStore(_install(tmp_path, 4), tmp_path / "cache")
    real = SpriteStore._render_strip
    renders: list[int] = []

    def slow(*args: Any, **kw: Any) -> Any:
        renders.append(1)
        time.sleep(0.2)  # long enough for every request to arrive meanwhile
        return real(*args, **kw)

    monkeypatch.setattr(SpriteStore, "_render_strip", staticmethod(slow))
    info = SpriteInfo(7, "u_test_idle", frames=2, facets=2, duration=0.1)
    got: list[Any] = []
    threads = [
        threading.Thread(target=lambda: got.append(store.strip(info, 1, (0, 0, 255), "0")))
        for _ in range(4)
    ]
    for th in threads:
        th.start()
    for th in threads:
        th.join(5)
    assert len(renders) == 1 and len(got) == 4 and got[0] is not None
    assert all(g == got[0] for g in got)
    # Written whole: no temporary files left beside the cached strip.
    assert sorted(p.suffix for p in (tmp_path / "cache" / "sprites").iterdir()) == [".json", ".png"]


def test_engine_none_graphics_are_settled_transparent_strips(tmp_path: Path) -> None:
    store = SpriteStore(None, tmp_path)
    for sid, name in [(12268, "None"), (12276, "None"), (1751, "None_x1")]:
        result = store.strip(SpriteInfo(sid, name, 15, 16, 0.15), 2, None, "-1")
        assert result is not None
        png, meta = result
        assert png.startswith(b"\x89PNG") and meta["empty"]
        assert meta["cw"] == meta["ch"] == meta["n"] == 1
    # A real missing filename remains an error, so the client can identify it
    # and draw its entity placeholder rather than silently hiding the unit.
    assert store.strip(SpriteInfo(999, "missing_knight", 1, 1, 0), 0, None, "-1") is None
