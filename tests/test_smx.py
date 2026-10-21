"""SMX sprite decoder: synthetic files in both pixel packings, palettes, resolution."""

from __future__ import annotations

import struct
from pathlib import Path

import pytest

from vantage.smx import SMX, SMXError, render
from vantage.sprites import SpriteInfo, SpriteStore

EMPTY = 0xFFFF


def _cmd(op: int, count: int = 1) -> int:
    return ((count - 1) << 2) | op


def _edges(rows: list[tuple[int, int]]) -> bytes:
    return b"".join(struct.pack("<HH", left, right) for left, right in rows)


def _layer(w: int, h: int, hx: int, hy: int, body: bytes, length: int | None = None) -> bytes:
    return struct.pack("<HHhhII", w, h, hx, hy, len(body) if length is None else length, 0) + body


def _main(
    w: int,
    h: int,
    hx: int,
    hy: int,
    rows: list[tuple[int, int]],
    cmds: list[int],
    pixels: bytes,
) -> bytes:
    cb = bytes(cmds)
    body = _edges(rows) + struct.pack("<II", len(cb), len(pixels)) + cb + pixels
    return _layer(w, h, hx, hy, body)


def _unified(w: int, h: int, hx: int, hy: int, rows: list[tuple[int, int]], arr: bytes) -> bytes:
    return _layer(w, h, hx, hy, _edges(rows) + struct.pack("<I", len(arr)) + arr)


def _smx(frames: list[tuple[int, int, bytes]]) -> bytes:
    body = b"".join(struct.pack("<BBI", t, pal, 0) + layers for t, pal, layers in frames)
    return (
        b"SMPX"
        + struct.pack("<HHII", 2, len(frames), len(body), 0)
        + b"test".ljust(16, b"\0")
        + body
    )


def _chunk_4plus1(pixels: list[tuple[int, int]]) -> bytes:
    assert len(pixels) == 4
    sec = 0
    for k, (_, s) in enumerate(pixels):
        sec |= s << (2 * k)  # pixel 0 in the low bits (measured on real files)
    return bytes([p[0] for p in pixels]) + bytes([sec])


def _chunk_8to5(a: tuple[int, int], b: tuple[int, int]) -> bytes:
    v = a[0] | a[1] << 8 | b[0] << 10 | b[1] << 18 | 0x20 << 24 | 0x80 << 32
    return v.to_bytes(5, "little")


def _game(tmp_path: Path) -> Path:
    pal = tmp_path / "game" / "resources" / "_common" / "palettes"
    pal.mkdir(parents=True)
    (pal / "palettes.conf").write_text("// comment\n0,test.pal\n28,other.pal\n")
    # Entry n: red = index, green = 60 * section, blue = 7.
    rows = [f"{n % 256} {60 * (n // 256)} 7 255" for n in range(1024)]
    # Player-colour ramp: entry n = (n // 2, n // 2, 255): white weight n/510.
    ramp = [f"{n // 2} {n // 2} 255" for n in range(256)]
    (pal / "playercolor_blue.pal").write_text(
        "JASC-PAL\r\n0100\r\n256\r\n" + "\r\n".join(ramp) + "\r\n"
    )
    (pal / "test.pal").write_text("JASC-PAL\r\n0100\r\n1024\r\n" + "\r\n".join(rows) + "\r\n")
    (pal / "other.pal").write_text(
        "JASC-PAL\r\n0100\r\n1024\r\n$ALPHA 9\r\n" + "\r\n".join(rows) + "\r\n"
    )
    return tmp_path / "game"


def _px(img: bytearray, w: int, x: int, y: int) -> tuple[int, ...]:
    o = (y * w + x) * 4
    return tuple(img[o : o + 4])


# Rows: 0 empty; 1 starts at x=1 (left edge), draws 2 normal + 1 player pixel;
# 2 draws 4. Commands begin at the left edge: the edge table is the leading skip.
ROWS = [(EMPTY, EMPTY), (1, 0), (0, 0)]
CMDS = [_cmd(1, 2), _cmd(2, 1), _cmd(3), _cmd(1, 4), _cmd(3)]
PIX = [(10, 0), (20, 1), (30, 0), (40, 2), (50, 3), (60, 0), (70, 1)]


def _frame_4plus1() -> bytes:
    pixels = _chunk_4plus1(PIX[:4]) + _chunk_4plus1([*PIX[4:], (0, 0)])
    return _main(4, 3, 1, 2, ROWS, CMDS, pixels)


def test_header_and_4plus1_pixels(tmp_path: Path) -> None:
    game = _game(tmp_path)
    path = tmp_path / "a.smx"
    path.write_bytes(_smx([(0x01, 0, _frame_4plus1())]))
    s = SMX.open(path, game)
    assert (s.version, s.count, s.comment) == (2, 1, "test")
    fr = s.frames[0]
    assert (fr.width, fr.height, fr.hotspot_x, fr.hotspot_y) == (4, 3, 1, 2)
    w, h, hx, hy, img = render(s, 0)
    assert (w, h, hx, hy) == (4, 3, 1, 2)
    assert all(_px(img, w, x, 0)[3] == 0 for x in range(4))  # empty row
    assert _px(img, w, 0, 1)[3] == 0  # left of the row's left edge
    assert _px(img, w, 1, 1) == (10, 0, 7, 255)
    assert _px(img, w, 2, 1) == (20, 60, 7, 255)  # palette section 1
    assert _px(img, w, 3, 1) == (15, 15, 255, 255)  # player-colour draw: ramp, default blue
    assert [_px(img, w, x, 2) for x in range(4)] == [
        (40, 120, 7, 255),
        (50, 180, 7, 255),
        (60, 0, 7, 255),
        (70, 60, 7, 255),
    ]


def test_player_colour_pixels_use_the_ramp_not_the_frame_palette(tmp_path: Path) -> None:
    game = _game(tmp_path)
    s = SMX(_smx([(0x01, 0, _frame_4plus1())]), game / "resources" / "_common" / "palettes")
    assert s.frame(0).player[1 * 4 + 3] == 30  # index kept, row 1 x 3
    _, _, _, _, img = render(s, 0, (200, 100, 0))
    assert _px(img, 4, 1, 1) == (10, 0, 7, 255)  # normal pixel untouched
    # Index 30 -> ramp entry (15, 15, 255): 240/255 of the colour plus 15 of white.
    assert _px(img, 4, 3, 1) == (203, 109, 15, 255)
    # No colour given: the ramp's own (blue) colour.
    assert _px(render(s, 0)[4], 4, 3, 1) == (15, 15, 255, 255)


def test_4plus1_section_bits_are_pixel_0_low(tmp_path: Path) -> None:
    game = _game(tmp_path)
    # One row of 4 pixels, same index, sections 0,1,2,3 in the fifth byte 0b11_10_01_00.
    chunk = bytes([9, 9, 9, 9, 0b11100100])
    frame = _main(4, 1, 0, 0, [(0, 0)], [_cmd(1, 4), _cmd(3)], chunk)
    s = SMX(_smx([(0x01, 0, frame)]), game / "resources" / "_common" / "palettes")
    img = render(s, 0)[4]
    assert [_px(img, 4, x, 0)[1] for x in range(4)] == [0, 60, 120, 180]


def test_8to5_pixels(tmp_path: Path) -> None:
    game = _game(tmp_path)
    pixels = _chunk_8to5(PIX[0], PIX[1]) + _chunk_8to5(PIX[2], PIX[3]) + _chunk_8to5(PIX[4], PIX[5])
    pixels += _chunk_8to5(PIX[6], (0, 0))
    frame = _main(4, 3, 1, 2, ROWS, CMDS, pixels)
    path = tmp_path / "b.smx"
    path.write_bytes(_smx([(0x09, 0, frame)]))  # 0x08: 8to5
    _, _, _, _, img = render(SMX.open(path, game), 0)
    assert _px(img, 4, 1, 1) == (10, 0, 7, 255)
    assert _px(img, 4, 2, 1) == (20, 60, 7, 255)
    assert [_px(img, 4, x, 2)[:2] for x in range(4)] == [(40, 120), (50, 180), (60, 0), (70, 60)]


def test_shadow_layer_has_its_own_box_and_alpha(tmp_path: Path) -> None:
    game = _game(tmp_path)
    # Shadow 6x1 with hotspot (3, 0): one row, skip 1, draw 3 alpha bytes.
    shadow = _unified(6, 1, 3, 0, [(0, 0)], bytes([_cmd(0, 1), _cmd(1, 3), 100, 200, 255, _cmd(3)]))
    main = _main(
        2, 1, 0, 0, [(0, 0)], [_cmd(1, 2), _cmd(3)], _chunk_4plus1([(5, 0), (6, 0), (0, 0), (0, 0)])
    )
    path = tmp_path / "c.smx"
    path.write_bytes(_smx([(0x03, 0, main + shadow)]))
    s = SMX.open(path, game)
    fr = s.frames[0]
    # Canvas = union aligned on the hotspots: shadow reaches 3 left and 3 right.
    assert (fr.width, fr.height, fr.hotspot_x, fr.hotspot_y) == (6, 1, 3, 0)
    w, _, _, _, img = render(s, 0)
    # Main sits at x 3..4 (hotspot 3 minus its own 0); shadow pixels at 1..3.
    assert _px(img, w, 3, 0) == (5, 0, 7, 255)  # main over shadow
    assert _px(img, w, 4, 0) == (6, 0, 7, 255)
    assert _px(img, w, 1, 0) == (0, 0, 0, 50)
    assert _px(img, w, 2, 0) == (0, 0, 0, 100)
    _, _, _, _, only_main = render(s, 0, shadow=False)
    assert _px(only_main, w, 2, 0)[3] == 0
    _, _, _, _, only_shadow = render(s, 0, main=False)
    assert _px(only_shadow, w, 3, 0) == (0, 0, 0, 127) and _px(only_shadow, w, 4, 0)[3] == 0


def test_empty_outline_layer_with_bogus_length_does_not_desync(tmp_path: Path) -> None:
    game = _game(tmp_path)
    main = _main(1, 1, 0, 0, [(0, 0)], [_cmd(1, 1), _cmd(3)], _chunk_4plus1([(9, 0)] * 4))
    # A 0x0 outline whose header length is copied from a neighbour (196) while the
    # body is only the 4-byte array length -- seen in real mod files.
    outline = _layer(0, 0, 0, 0, struct.pack("<I", 0), length=196)
    f2 = _main(1, 1, 0, 0, [(0, 0)], [_cmd(1, 1), _cmd(3)], _chunk_4plus1([(77, 0)] * 4))
    path = tmp_path / "d.smx"
    path.write_bytes(_smx([(0x05, 0, main + outline), (0x01, 0, f2)]))
    s = SMX.open(path, game)
    assert s.count == 2
    assert _px(render(s, 1)[4], 1, 0, 0) == (77, 0, 7, 255)


def test_palette_number_selects_file_and_errors(tmp_path: Path) -> None:
    game = _game(tmp_path)
    data = _smx([(0x01, 28, _frame_4plus1()), (0x01, 99, _frame_4plus1())])
    s = SMX(data, game / "resources" / "_common" / "palettes")
    assert _px(render(s, 0)[4], 4, 1, 1) == (10, 0, 7, 255)  # .palx-style $ALPHA line skipped
    with pytest.raises(SMXError, match="palette 99"):
        render(s, 1)
    with pytest.raises(SMXError, match="no game directory"):
        render(SMX(data), 0)
    with pytest.raises(SMXError, match="not an SMX"):
        SMX(b"SLDX" + bytes(40))


def _gfx(root: Path) -> Path:
    d = root / "resources" / "_common" / "drs" / "graphics"
    d.mkdir(parents=True)
    return d


def test_resolve_prefers_mod_smx_over_game_sld_and_sld_within_folder(tmp_path: Path) -> None:
    game = _game(tmp_path)
    gfx = _gfx(game)
    (gfx / "u_x_idle_x1.sld").write_bytes(b"SLDX")
    mod = tmp_path / "mods" / "m"
    mgfx = _gfx(mod)
    (mgfx / "u_x_idle_x1.smx").write_bytes(_smx([(0x01, 0, _frame_4plus1())]))
    store = SpriteStore(game, tmp_path / "cache", extra_dirs=[mod])
    assert store.resolve("u_x_idle") == mgfx / "u_x_idle_x1.smx"
    assert SpriteStore(game, tmp_path / "cache").resolve("u_x_idle") == gfx / "u_x_idle_x1.sld"
    (mgfx / "u_x_idle_x1.sld").write_bytes(b"SLDX")
    assert store.resolve("u_x_idle") == mgfx / "u_x_idle_x1.sld"  # same folder: .sld first
    # An SMX-only name resolves in the game folder too, and hd falls back to x1.
    (gfx / "n_only_x1.smx").write_bytes(b"SMPX")
    assert store.resolve("n_only", hd=True) == gfx / "n_only_x1.smx"


def test_strip_renders_an_smx_with_game_palettes(tmp_path: Path) -> None:
    game = _game(tmp_path)
    gfx = _gfx(game)
    frames = [(0x01, 0, _frame_4plus1()) for _ in range(2)]
    (gfx / "u_s_idle_x1.smx").write_bytes(_smx(frames))
    store = SpriteStore(game, tmp_path / "cache")
    got = store.strip(
        SpriteInfo(1, "u_s_idle", frames=2, facets=1, duration=0.1), 0, (0, 0, 255), "0"
    )
    assert got is not None
    png, meta = got
    assert png.startswith(b"\x89PNG")
    assert meta["n"] == 2 and meta["cw"] == 4 and meta["ch"] == 2  # empty top row cropped
