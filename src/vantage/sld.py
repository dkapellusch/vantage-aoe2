"""Decoder for the game's SLD sprite files (``resources/_common/drs/graphics``).

Layout, as read from the files themselves (all little-endian):

* header: ``"SLDX"``, version u16, frame count u16, u16, header size u16
  (16 or 14 -- frames start there), then unknown fields;
* per frame, a 12-byte header: canvas width/height u16, hotspot x/y u16,
  ``frame_type`` u8 (which layers follow), u8, frame index u16;
* then one record per present layer, in bit order -- 0x01 main graphic,
  0x02 shadow, 0x04 (unknown), 0x08 damage mask, 0x10 player-colour mask. Each
  starts with its byte length (u32, includes itself); records are 4-byte aligned;
* main and shadow layers carry a rectangle (x1, y1, x2, y2 u16) and a flag byte;
  the mask layers carry only the flag and reuse the main rectangle;
* the body is ``u16 n`` command pairs ``(skip, draw)`` counting 4x4 blocks in
  row-major order over the rectangle, followed by the drawn blocks: BC1 for the
  main graphic and damage mask, BC4 for shadow and player-colour mask
  (8 bytes per block in every case);
* flag bit 0x80: blocks *skipped* in this frame repeat the previous frame's
  blocks of the same layer (inter-frame compression).

Only what the spectator draws is decoded: the main graphic, the shadow, the
damage mask and the player-colour mask. Frames are produced as RGBA with the
player colour applied.

The damage mask (buildings) is a BC1 texture over the main rectangle: three
darkening weights, one per channel, that the game's sprite shader
(``shaders/d3d11/SpritesSLD_ps.so``, disassembled) phases in as the damage
amount ``d`` (0..1) grows -- red over d 0-0.5, green over 0.25-0.75, blue over
0.5-1 -- and applies as ``rgb *= 1 - min(0.65, w)``: damage only darkens the
picture, never adds pixels or colour (see :func:`_darken`).
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

LAYER_MAIN = 0x01
LAYER_SHADOW = 0x02
LAYER_UNKNOWN = 0x04
LAYER_DAMAGE = 0x08
LAYER_PLAYER = 0x10
_LAYER_ORDER = (LAYER_MAIN, LAYER_SHADOW, LAYER_UNKNOWN, LAYER_DAMAGE, LAYER_PLAYER)
_RECT_LAYERS = (LAYER_MAIN, LAYER_SHADOW)


@dataclass(frozen=True, slots=True)
class FrameInfo:
    width: int
    height: int
    hotspot_x: int
    hotspot_y: int
    layers: int
    offset: int  # byte offset of the frame header


@dataclass(slots=True)
class Layer:
    rect: tuple[int, int, int, int]
    flag: int
    blocks: list[bytes | None]  # one entry per 4x4 block, None = transparent


def _only_repeats(layers: dict[int, Layer]) -> bool:
    """True for a frame whose main layer sets the reuse flag and draws no block."""
    main = layers.get(LAYER_MAIN)
    return (
        main is not None and bool(main.flag & 0x80) and all(block is None for block in main.blocks)
    )


class SLDError(ValueError):
    pass


class SLD:
    """One sprite file. Frames decode lazily and in order (inter-frame reuse)."""

    def __init__(self, data: bytes) -> None:
        if data[:4] != b"SLDX":
            raise SLDError("not an SLD file")
        self.data = data
        self.version, self.count = struct.unpack_from("<HH", data, 4)
        self.frames: list[FrameInfo] = []
        # The u16 at offset 10 is the header size: 16 in most files, 14 in some.
        (pos,) = struct.unpack_from("<H", data, 10)
        if not 12 <= pos <= 64:
            pos = 16
        for _ in range(self.count):
            w, h, hx, hy, ftype = struct.unpack_from("<HHHHB", data, pos)
            self.frames.append(FrameInfo(w, h, hx, hy, ftype, pos))
            pos += 12
            for bit in _LAYER_ORDER:
                if ftype & bit:
                    (length,) = struct.unpack_from("<I", data, pos)
                    pos += (length + 3) & ~3
        self._prev: dict[int, Layer] = {}
        self._decoded_upto = -1
        self._cache: dict[int, dict[int, Layer]] = {}
        #: Frames per facing (0: unknown). Inter-frame reuse continues an
        #: animation within one facing; the first frame of a facing starts afresh
        #: (a one-frame-per-facing idle reused the previous facing's blocks and
        #: drew a trebuchet's arm several times over).
        self.per_facing = 0

    def set_frames_per_facing(self, per: int) -> None:
        """How many frames each facing has (from the game's sprite table)."""
        if per != self.per_facing:
            self.per_facing = per
            self._cache.clear()
            self._decoded_upto = -1
            self._prev = {}

    @classmethod
    def open(cls, path: Path) -> SLD:
        return cls(path.read_bytes())

    def layers(self, index: int) -> dict[int, Layer]:
        """Decoded layers of frame ``index`` (decodes earlier frames if needed)."""
        if index in self._cache:
            return self._cache[index]
        start = 0 if index < self._decoded_upto else self._decoded_upto + 1
        if start == 0:
            self._prev = {}
        out: dict[int, Layer] = {}
        for i in range(start, index + 1):
            out = self._decode(i)
        self._decoded_upto = index
        if len(self._cache) > 64:
            self._cache.clear()
        self._cache[index] = out
        return out

    def _decode(self, index: int) -> dict[int, Layer]:
        previous = self._prev
        starts_facing = self.per_facing > 0 and index % self.per_facing == 0
        if starts_facing:
            self._prev = {}
        out = self._decode_layers(index)
        if starts_facing and previous and _only_repeats(out):
            # No pixels of its own: the frame is a plain repeat of the one before it
            # (reeds stored as variants), not a new facing's picture. Left empty, it
            # would not be drawn at all.
            self._prev = previous
            out = self._decode_layers(index)
        _fill_zero_blocks(out)
        self._prev.update(out)
        return out

    def _decode_layers(self, index: int) -> dict[int, Layer]:
        fr = self.frames[index]
        data = self.data
        pos = fr.offset + 12
        main_rect: tuple[int, int, int, int] | None = None
        out: dict[int, Layer] = {}
        for bit in _LAYER_ORDER:
            if not fr.layers & bit:
                continue
            (length,) = struct.unpack_from("<I", data, pos)
            end = pos + length
            nxt = pos + ((length + 3) & ~3)
            p = pos + 4
            if bit in _RECT_LAYERS:
                rect = struct.unpack_from("<HHHH", data, p)
                flag = data[p + 8]
                p += 10
                if bit == LAYER_MAIN:
                    main_rect = rect
            else:
                flag = data[p]
                p += 2
                rect = main_rect or (0, 0, 0, 0)
            if bit in (LAYER_MAIN, LAYER_SHADOW, LAYER_DAMAGE, LAYER_PLAYER):
                out[bit] = self._blocks(data, p, end, rect, flag, self._prev.get(bit))
            pos = nxt
        return out

    @staticmethod
    def _blocks(
        data: bytes,
        p: int,
        end: int,
        rect: tuple[int, int, int, int],
        flag: int,
        prev: Layer | None,
    ) -> Layer:
        x1, y1, x2, y2 = rect
        total = ((x2 - x1 + 3) // 4) * ((y2 - y1 + 3) // 4)
        (ncmd,) = struct.unpack_from("<H", data, p)
        p += 2
        cmds = data[p : p + 2 * ncmd]
        p += 2 * ncmd
        bw = (x2 - x1 + 3) // 4
        reuse = bool(flag & 0x80) and prev is not None
        same = reuse and prev is not None and prev.rect == rect
        blocks: list[bytes | None] = [None] * total
        k = 0
        for c in range(ncmd):
            skip, draw = cmds[2 * c], cmds[2 * c + 1]
            if same:
                assert prev is not None
                blocks[k : k + skip] = prev.blocks[k : k + skip]
            elif reuse:
                # The previous frame covers another rectangle: a skipped block repeats
                # whatever the previous frame had at the same pixels (an unpacking
                # trebuchet's frames grow and shrink; left empty they were confetti).
                assert prev is not None
                for j in range(k, min(k + skip, total)):
                    blocks[j] = _block_at(prev, x1 + 4 * (j % bw), y1 + 4 * (j // bw))
            k += skip
            for _ in range(draw):
                if k < total and p + 8 <= end:
                    blocks[k] = data[p : p + 8]
                p += 8
                k += 1
        return Layer(rect, flag, blocks)


def _degenerate(block: bytes | None) -> bool:
    """A BC1 block whose two colours are both 0: black or transparent pixels only."""
    return block is not None and block[:4] == b"\0\0\0\0"


def _fill_zero_blocks(layers: dict[int, Layer], reach: int = 8) -> None:
    """Replace degenerate main-graphic blocks (both colours 0) with their nearest
    neighbour in the row.

    A few files carry these where the picture continues (the Khmer town centre's
    walls: some 70 blocks in ``b_seas_town_center_age3_main_x1``; scattered blocks
    in some destruction animations). Decoded as BC1 they are black wedges and
    stripes; the game shows the wall carrying on. The nearest drawn block in the same row
    (with its player-colour and damage masks) stands in for each; with none
    within ``reach`` blocks the block is left out (transparent), never black.
    """
    main = layers.get(LAYER_MAIN)
    if main is None or not any(_degenerate(b) for b in main.blocks):
        return
    x1, _, x2, _ = main.rect
    bw = max(1, (x2 - x1 + 3) // 4)
    blocks = main.blocks
    masks = [m for b, m in layers.items() if b != LAYER_MAIN and m.rect == main.rect]
    for k, blk in enumerate(blocks):
        if not _degenerate(blk):
            continue
        row, col = divmod(k, bw)
        src = None
        for d in range(1, reach + 1):
            for c in (col - d, col + d):
                j = row * bw + c
                if 0 <= c < bw and blocks[j] is not None and not _degenerate(blocks[j]):
                    src = j
                    break
            if src is not None:
                break
        blocks[k] = blocks[src] if src is not None else None
        for m in masks:
            if k < len(m.blocks):
                m.blocks[k] = m.blocks[src] if src is not None and src < len(m.blocks) else None


def _block_at(layer: Layer, x: int, y: int) -> bytes | None:
    """The block of ``layer`` covering canvas pixel (x, y), if it is block-aligned."""
    lx1, ly1, lx2, ly2 = layer.rect
    dx, dy = x - lx1, y - ly1
    if dx < 0 or dy < 0 or dx % 4 or dy % 4 or x >= lx2 or y >= ly2:
        return None
    j = (dy // 4) * ((lx2 - lx1 + 3) // 4) + dx // 4
    return layer.blocks[j] if j < len(layer.blocks) else None


# -- block decoding -----------------------------------------------------------------


def _rgb565(c: int) -> tuple[int, int, int]:
    r, g, b = (c >> 11) & 31, (c >> 5) & 63, c & 31
    return (r << 3 | r >> 2, g << 2 | g >> 4, b << 3 | b >> 2)


@lru_cache(maxsize=65536)
def bc1(block: bytes) -> tuple[tuple[int, int, int, int], ...]:
    c0, c1, bits = struct.unpack("<HHI", block)
    p0, p1 = _rgb565(c0), _rgb565(c1)
    r0, g0, b0 = p0
    r1, g1, b1 = p1
    pal: tuple[tuple[int, int, int, int], ...]
    if c0 > c1:
        pal = (
            (r0, g0, b0, 255),
            (r1, g1, b1, 255),
            ((2 * r0 + r1) // 3, (2 * g0 + g1) // 3, (2 * b0 + b1) // 3, 255),
            ((r0 + 2 * r1) // 3, (g0 + 2 * g1) // 3, (b0 + 2 * b1) // 3, 255),
        )
    else:
        pal = (
            (r0, g0, b0, 255),
            (r1, g1, b1, 255),
            ((r0 + r1) // 2, (g0 + g1) // 2, (b0 + b1) // 2, 255),
            (0, 0, 0, 0),
        )
    return tuple(pal[(bits >> (2 * i)) & 3] for i in range(16))


@lru_cache(maxsize=65536)
def bc4(block: bytes) -> tuple[int, ...]:
    a0, a1 = block[0], block[1]
    bits = int.from_bytes(block[2:8], "little")
    if a0 > a1:
        pal = [a0, a1] + [((7 - i) * a0 + i * a1) // 7 for i in range(1, 7)]
    else:
        pal = [a0, a1] + [((5 - i) * a0 + i * a1) // 5 for i in range(1, 5)] + [0, 255]
    return tuple(pal[(bits >> (3 * i)) & 7] for i in range(16))


def render(
    sld: SLD,
    index: int,
    player_rgb: tuple[int, int, int] | None = None,
    shadow: bool = True,
    *,
    main: bool = True,
    damage: float = 0.0,
) -> tuple[int, int, int, int, bytearray]:
    """RGBA pixels of one frame: ``(width, height, hotspot_x, hotspot_y, rgba)``.

    ``player_rgb`` tints the player-colour mask (multiplicative over the
    graphic's luminance, which is how the game shades team colours).
    ``shadow`` / ``main`` select the layers drawn (a shadow-only frame lets the
    browser filter the shadow separately). ``damage`` (0..1, the fraction of
    hit points lost) applies the damage mask, see the module docstring.
    """
    fr = sld.frames[index]
    w, h = fr.width, fr.height
    out = bytearray(w * h * 4)
    layers = sld.layers(index)
    if shadow and LAYER_SHADOW in layers:
        _paint(out, w, h, layers[LAYER_SHADOW], lambda blk: [(0, 0, 0, a // 2) for a in bc4(blk)])
    body = layers.get(LAYER_MAIN)
    if main and body is not None:
        _paint(out, w, h, body, bc1)
        pmask = layers.get(LAYER_PLAYER)
        if player_rgb is not None and pmask is not None:
            _tint(out, w, h, pmask, player_rgb)
        dmask = layers.get(LAYER_DAMAGE)
        if damage > 0 and dmask is not None:
            _darken(out, w, h, dmask, damage)
    return w, h, fr.hotspot_x, fr.hotspot_y, out


def player_mask(sld: SLD, index: int) -> bytearray:
    """One frame's player-colour mask, a byte per pixel (0 where none): what
    :func:`render`'s ``player_rgb`` tint weighs the colour by, for a browser that
    tints on the GPU (one strip then serves every player)."""
    fr = sld.frames[index]
    w, h = fr.width, fr.height
    out = bytearray(w * h)
    layer = sld.layers(index).get(LAYER_PLAYER)
    if layer is None:
        return out
    x1, y1, x2, _ = layer.rect
    bw = (x2 - x1 + 3) // 4
    for k, blk in enumerate(layer.blocks):
        if blk is None:
            continue
        m = bc4(blk)
        bx = x1 + (k % bw) * 4
        by = y1 + (k // bw) * 4
        for i in range(16):
            x, y = bx + (i & 3), by + (i >> 2)
            if x < w and y < h:
                out[y * w + x] = m[i]
    return out


def _paint(out: bytearray, w: int, h: int, layer: Layer, decode: object) -> None:
    x1, y1, x2, _ = layer.rect
    bw = (x2 - x1 + 3) // 4
    fn = decode  # (bytes) -> sequence of 16 RGBA tuples
    for k, blk in enumerate(layer.blocks):
        if blk is None:
            continue
        px = fn(blk)  # type: ignore[operator]  # callable passed in by render()
        bx = x1 + (k % bw) * 4
        by = y1 + (k // bw) * 4
        for i in range(16):
            r, g, b, a = px[i]
            if not a:
                continue
            x, y = bx + (i & 3), by + (i >> 2)
            if x >= w or y >= h:
                continue
            o = (y * w + x) * 4
            if a == 255 or not out[o + 3]:
                out[o : o + 4] = bytes((r, g, b, a))


def _tint(out: bytearray, w: int, h: int, layer: Layer, rgb: tuple[int, int, int]) -> None:
    x1, y1, x2, _ = layer.rect
    bw = (x2 - x1 + 3) // 4
    pr, pg, pb = rgb
    for k, blk in enumerate(layer.blocks):
        if blk is None:
            continue
        m = bc4(blk)
        bx = x1 + (k % bw) * 4
        by = y1 + (k // bw) * 4
        for i in range(16):
            a = m[i]
            if not a:
                continue
            x, y = bx + (i & 3), by + (i >> 2)
            if x >= w or y >= h:
                continue
            o = (y * w + x) * 4
            if not out[o + 3]:
                continue
            lum = (out[o] * 3 + out[o + 1] * 6 + out[o + 2]) / 2550.0 * 1.6
            f = a / 255.0
            for c, pc in ((0, pr), (1, pg), (2, pb)):
                out[o + c] = min(255, int(out[o + c] * (1 - f) + pc * lum * f))


def _darken(out: bytearray, w: int, h: int, layer: Layer, damage: float) -> None:
    """The game's damage shading (``SpritesSLD_ps``): per pixel
    ``w = R*sat(2d) + G*sat(2(d - .25)) + B*sat(2(d - .5))``, capped at 0.65,
    and ``rgb *= 1 - w``. Only drawn pixels change (the game discards the rest)."""
    x1, y1, x2, _ = layer.rect
    bw = (x2 - x1 + 3) // 4
    d = max(0.0, min(1.0, damage))
    kr = min(1.0, 2 * d)
    kg = min(1.0, max(0.0, 2 * (d - 0.25)))
    kb = min(1.0, max(0.0, 2 * (d - 0.5)))
    for k, blk in enumerate(layer.blocks):
        if blk is None:
            continue
        m = bc1(blk)
        bx = x1 + (k % bw) * 4
        by = y1 + (k // bw) * 4
        for i in range(16):
            r, g, b, a = m[i]
            if not a:
                continue
            f = min(0.65, (r * kr + g * kg + b * kb) / 255.0)
            if f <= 0.0:
                continue
            x, y = bx + (i & 3), by + (i >> 2)
            if x >= w or y >= h:
                continue
            o = (y * w + x) * 4
            if out[o + 3] < 128:
                continue
            for c in range(3):
                out[o + c] = int(out[o + c] * (1.0 - f))
