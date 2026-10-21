"""Decoder for the game's SMX sprite files (the older DE sprite format; ``SMPX``).

Layout, as read from the files themselves (all little-endian):

* header (32 bytes): ``"SMPX"``, version u16 (2), frame count u16, compressed
  size u32, source size u32, 16-byte comment (the exporter's name);
* frames follow back to back (no offsets): a 6-byte header -- ``frame_type`` u8,
  palette number u8, source size u32 -- then one record per layer present, in
  the order main, shadow, outline. ``frame_type`` bits: 0x01 main graphic,
  0x02 shadow, 0x04 outline, 0x08 main pixels are 8to5-packed (else 4plus1);
* a layer record is a 16-byte header (width, height u16; hotspot x, y i16;
  body length u32 -- unreliable on empty layers, see ``SMX.__init__`` -- and
  one unused u32) and the body;
* the body starts with ``height`` row edges (left, right u16 transparent
  columns; ``0xFFFF`` left = row has no pixels and no commands), then:
  main graphic: command-array length u32, pixel-array length u32, the commands,
  the pixels; shadow / outline: one length u32 and one array of inline commands;
* commands: low 2 bits opcode, upper 6 bits ``count - 1``: 0 skip, 1 draw,
  2 player-colour draw, 3 end of row. Main draws take their pixels from the
  separate pixel array, consumed in order across the whole layer; shadow draws
  carry ``count`` alpha bytes inline; outline draws carry nothing;
* main pixels come in 5-byte chunks, 4 pixels (4plus1: four palette indices,
  then four 2-bit palette sections, pixel 0 in the low bits) or 2 pixels (8to5,
  see :func:`_unpack_8to5`).
  A pixel's colour is ``palette[section * 256 + index]``; the palette (a 1024
  entry ``.pal``) is chosen by the frame's palette number through
  ``resources/_common/palettes/palettes.conf``.

Player-colour pixels (opcode 2) do not use the frame's palette: their index
addresses a player-colour ramp (see :func:`_player_ramp`) that ``render`` colours
with the player's RGB. The
outline layer is parsed past but not drawn. There is no damage layer.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

FRAME_MAIN = 0x01
FRAME_SHADOW = 0x02
FRAME_OUTLINE = 0x04
FRAME_8TO5 = 0x08

_EMPTY_ROW = 0xFFFF
_OP_SKIP, _OP_DRAW, _OP_PLAYER, _OP_END = 0, 1, 2, 3

Palette = list[tuple[int, int, int, int]]


class SMXError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class FrameInfo:
    width: int
    height: int
    hotspot_x: int
    hotspot_y: int
    frame_type: int
    palette: int
    offset: int  # byte offset of the frame header


@dataclass(slots=True)
class Frame:
    """A decoded frame: row-major, ``width * height`` entries per layer."""

    #: RGBA per pixel (alpha 0 = transparent), palette already applied.
    main: list[tuple[int, int, int, int] | None]
    #: Player-colour ramp index (0-255) where the pixel is a player-colour draw, else -1.
    #: The ``main`` entry of such a pixel is a placeholder; see :func:`_player_ramp`.
    player: list[int]
    #: Shadow alpha per pixel (0 = none); empty without a shadow layer.
    shadow: list[int]


def _parse_pal(text: str) -> Palette:
    # JASC-PAL, version, count, then ``r g b [a]`` per entry (3 or 4 numbers).
    # ``.palx`` files add a ``$ALPHA n`` directive line, not interpreted here.
    lines = [ln for ln in text.splitlines() if ln.strip() and not ln.startswith("$")]
    out: Palette = []
    for ln in lines[3 : 3 + int(lines[2])]:
        e = [int(v) for v in ln.split()]
        out.append((e[0], e[1], e[2], e[3] if len(e) > 3 else 255))
    return out


@lru_cache(maxsize=64)
def load_palette(palettes_dir: Path, name: str) -> Palette:
    """One palette file (``.pal`` / ``.palx``) from ``palettes_dir``."""
    return _parse_pal((palettes_dir / name).read_text(encoding="ascii", errors="replace"))


@lru_cache(maxsize=8)
def palette_files(palettes_dir: Path) -> dict[int, str]:
    """``palettes.conf``: palette number -> file name."""
    out: dict[int, str] = {}
    conf = palettes_dir / "palettes.conf"
    if not conf.is_file():
        return out
    for line in conf.read_text(encoding="ascii", errors="replace").splitlines():
        line = line.split("//", 1)[0].strip()
        num, _, name = line.partition(",")
        if name.strip() and num.strip().isdigit():
            out[int(num)] = name.strip()
    return out


@lru_cache(maxsize=8)
def _player_ramp(palettes: Path) -> tuple[tuple[float, float], ...]:
    """Per player-colour index, ``(base weight, white weight)``.

    A player-colour pixel's index selects an entry of a ``playercolor_*.pal`` (a
    16x16 table: columns darken the colour, rows blend it towards white). The
    pure-blue palette tells how: entry = ``(w, w, kb + w)`` in 0..1 units, i.e.
    ``kb`` of the base colour plus ``w`` of white, so any colour is
    ``base * kb + 255 * w``.
    """
    pal = load_palette(palettes, "playercolor_blue.pal")
    return tuple(((b - r) / 255.0, r / 255.0) for r, _g, b, _a in pal)


def palettes_dir(game_dir: Path) -> Path:
    return game_dir / "resources" / "_common" / "palettes"


def _unpack_8to5(chunk: bytes) -> list[tuple[int, int]]:
    """Two ``(index, section)`` pixels from a 5-byte (40-bit, little-endian) chunk.

    Measured, not taken from the public description (whose bit table does not
    decode real files): the low 20 bits are two 10-bit pixels, pixel 0 in bits
    0-9 and pixel 1 in bits 10-19, each ``index | section << 8``. The high 20
    bits are the damage modifiers, which this renderer does not use. The layout
    is the unique bit assignment that makes a real 8to5 sprite spatially smooth.
    """
    v = int.from_bytes(chunk, "little")
    return [(v & 0xFF, (v >> 8) & 3), ((v >> 10) & 0xFF, (v >> 18) & 3)]


def _unpack_pixels(data: bytes, packed_8to5: bool) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    for i in range(0, len(data) - 4, 5):
        if packed_8to5:
            out.extend(_unpack_8to5(data[i : i + 5]))
        else:
            sec = data[i + 4]
            out.extend((data[i + k], (sec >> (2 * k)) & 3) for k in range(4))
    return out


class SMX:
    """One sprite file. Frames decode lazily."""

    def __init__(self, data: bytes, palettes: Path | None = None) -> None:
        if data[:4] != b"SMPX":
            raise SMXError("not an SMX file")
        self.data = data
        self.palettes = palettes
        self.version, self.count = struct.unpack_from("<HH", data, 4)
        self.comment = data[16:32].split(b"\0", 1)[0].decode("ascii", "replace")
        self.frames: list[FrameInfo] = []
        self._layers: list[dict[int, tuple[int, int, int, int, int]]] = []
        pos = 32
        for _ in range(self.count):
            ftype, pal = struct.unpack_from("<BB", data, pos)
            start = pos
            pos += 6
            layers: dict[int, tuple[int, int, int, int, int]] = {}
            for bit in (FRAME_MAIN, FRAME_SHADOW, FRAME_OUTLINE):
                if not ftype & bit:
                    continue
                w, h, hx, hy = struct.unpack_from("<HHhh", data, pos)
                layers[bit] = (w, h, hx, hy, pos + 16)
                # The header's length field is not trusted: an empty (0x0) shadow
                # or outline layer copies a neighbour's length but its body is just
                # the array length, so the size is derived from the body itself.
                body = pos + 16 + 4 * h
                if bit == FRAME_MAIN:
                    ncmd, npix = struct.unpack_from("<II", data, body)
                    pos = body + 8 + ncmd + npix
                else:
                    (n,) = struct.unpack_from("<I", data, body)
                    pos = body + 4 + n
            if pos > len(data):
                raise SMXError("truncated SMX file")
            # Layers have their own size and hotspot (a shadow is wider than its
            # sprite): the frame canvas is their union, aligned on the hotspots.
            drawn = [layers[b][:4] for b in (FRAME_MAIN, FRAME_SHADOW) if b in layers]
            hx = max((q[2] for q in drawn), default=0)
            hy = max((q[3] for q in drawn), default=0)
            w = max((q[0] - q[2] for q in drawn), default=0) + hx
            h = max((q[1] - q[3] for q in drawn), default=0) + hy
            self.frames.append(FrameInfo(w, h, hx, hy, ftype, pal, start))
            self._layers.append(layers)
        self._cache: dict[int, Frame] = {}

    @classmethod
    def open(cls, path: Path, game_dir: Path | None = None) -> SMX:
        return cls(path.read_bytes(), palettes_dir(game_dir) if game_dir else None)

    def palette(self, number: int) -> Palette:
        if self.palettes is None:
            raise SMXError("no game directory: cannot load palettes")
        name = palette_files(self.palettes).get(number)
        if name is None:
            raise SMXError(f"palette {number} is not in palettes.conf")
        return load_palette(self.palettes, name)

    def frame(self, index: int) -> Frame:
        got = self._cache.get(index)
        if got is None:
            if len(self._cache) > 64:
                self._cache.clear()
            got = self._cache[index] = self._decode(index)
        return got

    def _decode(self, index: int) -> Frame:
        fr = self.frames[index]
        layers = self._layers[index]
        w, h = fr.width, fr.height
        main: list[tuple[int, int, int, int] | None] = [None] * (w * h)
        player = [-1] * (w * h)
        shadow: list[int] = []
        if FRAME_MAIN in layers:
            self._decode_main(fr, layers[FRAME_MAIN], main, player)
        if FRAME_SHADOW in layers:
            shadow = [0] * (w * h)
            self._decode_shadow(fr, layers[FRAME_SHADOW], shadow)
        return Frame(main, player, shadow)

    def _edges(self, pos: int, h: int) -> list[tuple[int, int]]:
        return [struct.unpack_from("<HH", self.data, pos + 4 * y) for y in range(h)]

    def _decode_main(
        self,
        fr: FrameInfo,
        layer: tuple[int, int, int, int, int],
        out: list[tuple[int, int, int, int] | None],
        player: list[int],
    ) -> None:
        data = self.data
        lw, lh, lhx, lhy, pos = layer
        w = fr.width
        ox, oy = fr.hotspot_x - lhx, fr.hotspot_y - lhy  # layer origin in the canvas
        edges = self._edges(pos, lh)
        pos += 4 * lh
        ncmd, npix = struct.unpack_from("<II", data, pos)
        pos += 8
        cmds = data[pos : pos + ncmd]
        pixels = _unpack_pixels(data[pos + ncmd : pos + ncmd + npix], bool(fr.frame_type & 8))
        pal = self.palette(fr.palette)
        c = 0
        n = 0  # next pixel
        for y, (left, _right) in enumerate(edges):
            if left == _EMPTY_ROW:
                continue
            x = left
            row = (y + oy) * w + ox
            while c < len(cmds):
                b = cmds[c]
                c += 1
                op, cnt = b & 3, (b >> 2) + 1
                if op == _OP_END:
                    break
                if op == _OP_SKIP:
                    x += cnt
                    continue
                for _ in range(cnt):
                    if n >= len(pixels):
                        raise SMXError("pixel array exhausted")
                    idx, sec = pixels[n]
                    n += 1
                    if 0 <= x < lw:
                        if op == _OP_PLAYER:
                            out[row + x] = (0, 0, 0, 255)
                            player[row + x] = idx
                        else:
                            out[row + x] = pal[sec * 256 + idx]
                    x += 1

    def _decode_shadow(
        self, fr: FrameInfo, layer: tuple[int, int, int, int, int], out: list[int]
    ) -> None:
        data = self.data
        lw, lh, lhx, lhy, pos = layer
        w = fr.width
        ox, oy = fr.hotspot_x - lhx, fr.hotspot_y - lhy
        edges = self._edges(pos, lh)
        pos += 4 * lh
        (length,) = struct.unpack_from("<I", data, pos)
        pos += 4
        end = pos + length
        for y, (left, _right) in enumerate(edges):
            if left == _EMPTY_ROW:
                continue
            x = left
            row = (y + oy) * w + ox
            while pos < end:
                b = data[pos]
                pos += 1
                op, cnt = b & 3, (b >> 2) + 1
                if op == _OP_END:
                    break
                if op == _OP_SKIP:
                    x += cnt
                    continue
                for k in range(cnt):
                    if 0 <= x + k < lw:
                        out[row + x + k] = data[pos + k]
                pos += cnt
                x += cnt


def render(
    smx: SMX,
    index: int,
    player_rgb: tuple[int, int, int] | None = None,
    shadow: bool = True,
    *,
    main: bool = True,
    damage: float = 0.0,
) -> tuple[int, int, int, int, bytearray]:
    """RGBA pixels of one frame: ``(width, height, hotspot_x, hotspot_y, rgba)``.

    Same contract as :func:`vantage.sld.render`: ``player_rgb`` tints the
    player-colour pixels (multiplicative over their luminance), ``shadow`` /
    ``main`` select the layers, ``damage`` is ignored (SMX has no damage layer).
    """
    del damage
    fr = smx.frames[index]
    w, h = fr.width, fr.height
    out = bytearray(w * h * 4)
    fd = smx.frame(index)
    if shadow and fd.shadow:
        for i, a in enumerate(fd.shadow):
            if a:
                out[i * 4 + 3] = a // 2
    if main:
        pr, pg, pb = player_rgb or (0, 0, 255)  # the table's own colour: blue
        ramp = (
            _player_ramp(smx.palettes)
            if smx.palettes is not None and any(v >= 0 for v in fd.player)
            else ()
        )
        for i, px in enumerate(fd.main):
            if px is None or not px[3]:
                continue
            r, g, b, a = px
            if fd.player[i] >= 0:
                kb, white = ramp[fd.player[i]]
                r, g, b = (min(255, max(0, round(c * kb + 255 * white))) for c in (pr, pg, pb))
            out[i * 4 : i * 4 + 4] = bytes((r, g, b, a))
    return w, h, fr.hotspot_x, fr.hotspot_y, out
