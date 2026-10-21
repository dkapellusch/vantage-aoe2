"""BC7 (BPTC) texture block decoder, pure Python, stdlib only.

Written from the BC7/BPTC format description. The partition tables below are
format-spec data (subset id per pixel, and the anchor pixel of each subset whose
index loses its top bit).
"""

from __future__ import annotations

# Per-mode layout: (subsets, partition bits, rotation bits, index-select bits,
# colour bits, alpha bits, p-bit kind (0 none, 1 per endpoint, 2 per subset),
# index bits, secondary index bits).
_MODES: tuple[tuple[int, int, int, int, int, int, int, int, int], ...] = (
    (3, 4, 0, 0, 4, 0, 1, 3, 0),
    (2, 6, 0, 0, 6, 0, 2, 3, 0),
    (3, 6, 0, 0, 5, 0, 0, 2, 0),
    (2, 6, 0, 0, 7, 0, 1, 2, 0),
    (1, 0, 2, 1, 5, 6, 0, 2, 3),
    (1, 0, 2, 0, 7, 8, 0, 2, 2),
    (1, 0, 0, 0, 7, 7, 1, 4, 0),
    (2, 6, 0, 0, 5, 5, 1, 2, 0),
)

_W2 = (0, 21, 43, 64)
_W3 = (0, 9, 18, 27, 37, 46, 55, 64)
_W4 = (0, 4, 9, 13, 17, 21, 26, 30, 34, 38, 43, 47, 51, 55, 60, 64)
_WEIGHTS = {2: _W2, 3: _W3, 4: _W4}

_P2_SUBSETS = (
    "0011001100110011",
    "0001000100010001",
    "0111011101110111",
    "0001001100110111",
    "0000000100010011",
    "0011011101111111",
    "0001001101111111",
    "0000000100110111",
    "0000000000010011",
    "0011011111111111",
    "0000000101111111",
    "0000000000010111",
    "0001011111111111",
    "0000000011111111",
    "0000111111111111",
    "0000000000001111",
    "0000100011101111",
    "0111000100000000",
    "0000000010001110",
    "0111001100010000",
    "0011000100000000",
    "0000100011001110",
    "0000000010001100",
    "0111001100110001",
    "0011000100010000",
    "0000100010001100",
    "0110011001100110",
    "0011011001101100",
    "0001011111101000",
    "0000111111110000",
    "0111000110001110",
    "0011100110011100",
    "0101010101010101",
    "0000111100001111",
    "0101101001011010",
    "0011001111001100",
    "0011110000111100",
    "0101010110101010",
    "0110100101101001",
    "0101101010100101",
    "0111001111001110",
    "0001001111001000",
    "0011001001001100",
    "0011101111011100",
    "0110100110010110",
    "0011110011000011",
    "0110011010011001",
    "0000011001100000",
    "0100111001000000",
    "0010011100100000",
    "0000001001110010",
    "0000010011100100",
    "0110110010010011",
    "0011011011001001",
    "0110001110011100",
    "0011100111000110",
    "0110110011001001",
    "0110001100111001",
    "0111111010000001",
    "0001100011100111",
    "0000111100110011",
    "0011001111110000",
    "0010001011101110",
    "0100010001110111",
)
_P2_ANCHORS = (
    (0, 15),
    (0, 15),
    (0, 15),
    (0, 15),
    (0, 15),
    (0, 15),
    (0, 15),
    (0, 15),
    (0, 15),
    (0, 15),
    (0, 15),
    (0, 15),
    (0, 15),
    (0, 15),
    (0, 15),
    (0, 15),
    (0, 15),
    (0, 2),
    (0, 8),
    (0, 2),
    (0, 2),
    (0, 8),
    (0, 8),
    (0, 15),
    (0, 2),
    (0, 8),
    (0, 2),
    (0, 2),
    (0, 8),
    (0, 8),
    (0, 2),
    (0, 2),
    (0, 15),
    (0, 15),
    (0, 6),
    (0, 8),
    (0, 2),
    (0, 8),
    (0, 15),
    (0, 15),
    (0, 2),
    (0, 8),
    (0, 2),
    (0, 2),
    (0, 2),
    (0, 15),
    (0, 15),
    (0, 6),
    (0, 6),
    (0, 2),
    (0, 6),
    (0, 8),
    (0, 15),
    (0, 15),
    (0, 2),
    (0, 2),
    (0, 15),
    (0, 15),
    (0, 15),
    (0, 15),
    (0, 15),
    (0, 2),
    (0, 2),
    (0, 15),
)

_P3_SUBSETS = (
    "0011001102212222",
    "0001001122112221",
    "0000200122112211",
    "0222002200110111",
    "0000000011221122",
    "0011001100220022",
    "0022002211111111",
    "0011001122112211",
    "0000000011112222",
    "0000111111112222",
    "0000111122222222",
    "0012001200120012",
    "0112011201120112",
    "0122012201220122",
    "0011011211221222",
    "0011200122002220",
    "0001001101121122",
    "0111001120012200",
    "0000112211221122",
    "0022002200221111",
    "0111011102220222",
    "0001000122212221",
    "0000001101220122",
    "0000110022102210",
    "0122012200110000",
    "0012001211222222",
    "0110122112210110",
    "0000011012211221",
    "0022110211020022",
    "0110011020022222",
    "0011012201220011",
    "0000200022112221",
    "0000000211221222",
    "0222002200120011",
    "0011001200220222",
    "0120012001200120",
    "0000111122220000",
    "0120120120120120",
    "0120201212010120",
    "0011220011220011",
    "0011112222000011",
    "0101010122222222",
    "0000000021212121",
    "0022112200221122",
    "0022001100220011",
    "0220122102201221",
    "0101222222220101",
    "0000212121212121",
    "0101010101012222",
    "0222011102220111",
    "0002111200021112",
    "0000211221122112",
    "0222011101110222",
    "0002111211120002",
    "0110011001102222",
    "0000000021122112",
    "0110011022222222",
    "0022001100110022",
    "0022112211220022",
    "0000000000002112",
    "0002000100020001",
    "0222122202221222",
    "0101222222222222",
    "0111201122012220",
)
_P3_ANCHORS = (
    (0, 3, 15),
    (0, 3, 8),
    (0, 15, 8),
    (0, 15, 3),
    (0, 8, 15),
    (0, 3, 15),
    (0, 15, 3),
    (0, 15, 8),
    (0, 8, 15),
    (0, 8, 15),
    (0, 6, 15),
    (0, 6, 15),
    (0, 6, 15),
    (0, 5, 15),
    (0, 3, 15),
    (0, 3, 8),
    (0, 3, 15),
    (0, 3, 8),
    (0, 8, 15),
    (0, 15, 3),
    (0, 3, 15),
    (0, 3, 8),
    (0, 6, 15),
    (0, 10, 8),
    (0, 5, 3),
    (0, 8, 15),
    (0, 8, 6),
    (0, 6, 10),
    (0, 8, 15),
    (0, 5, 15),
    (0, 15, 10),
    (0, 15, 8),
    (0, 8, 15),
    (0, 15, 3),
    (0, 3, 15),
    (0, 5, 10),
    (0, 6, 10),
    (0, 10, 8),
    (0, 8, 9),
    (0, 15, 10),
    (0, 15, 6),
    (0, 3, 15),
    (0, 15, 8),
    (0, 5, 15),
    (0, 15, 3),
    (0, 15, 6),
    (0, 15, 6),
    (0, 15, 8),
    (0, 3, 15),
    (0, 15, 3),
    (0, 5, 15),
    (0, 5, 15),
    (0, 5, 15),
    (0, 8, 15),
    (0, 5, 15),
    (0, 10, 15),
    (0, 5, 15),
    (0, 10, 15),
    (0, 8, 15),
    (0, 13, 15),
    (0, 15, 3),
    (0, 12, 15),
    (0, 3, 15),
    (0, 3, 8),
)

_SUBSETS_BY_COUNT = {
    1: (tuple([0] * 16),),
    2: tuple(tuple(int(c) for c in s) for s in _P2_SUBSETS),
    3: tuple(tuple(int(c) for c in s) for s in _P3_SUBSETS),
}
_ANCHORS_BY_COUNT = {
    1: ((0,),),
    2: _P2_ANCHORS,
    3: _P3_ANCHORS,
}
_ZERO_PIXEL = (0, 0, 0, 0)


def _expand(value: int, bits: int) -> int:
    """Unquantise a `bits`-wide endpoint value to 8 bits."""
    if bits >= 8:
        return value
    return (value << (8 - bits)) | (value >> (2 * bits - 8))


def _decode_block(block: bytes) -> list[tuple[int, int, int, int]]:
    """Decode one 16-byte BC7 block to 16 RGBA tuples in raster order."""
    v = int.from_bytes(block, "little")
    if not v & 0xFF:
        return [_ZERO_PIXEL] * 16  # mode 8+: reserved, decodes to transparent black
    mode = ((v & -v).bit_length()) - 1
    ns, pbits, rotbits, selbits, cb, ab, pkind, ib, ib2 = _MODES[mode]
    pos = mode + 1
    part = (v >> pos) & ((1 << pbits) - 1)
    pos += pbits
    rot = (v >> pos) & ((1 << rotbits) - 1)
    pos += rotbits
    sel = (v >> pos) & ((1 << selbits) - 1)
    pos += selbits

    ne = ns * 2
    cmask = (1 << cb) - 1
    ch: list[list[int]] = []
    for _ in range(3):
        ch.append([(v >> (pos + k * cb)) & cmask for k in range(ne)])
        pos += ne * cb
    if ab:
        amask = (1 << ab) - 1
        alpha = [(v >> (pos + k * ab)) & amask for k in range(ne)]
        pos += ne * ab
    else:
        alpha = []
    cbits = cb
    abits = ab
    if pkind == 1:
        pb = [(v >> (pos + k)) & 1 for k in range(ne)]
        pos += ne
    elif pkind == 2:
        pb = [(v >> (pos + k // 2)) & 1 for k in range(ne)]
        pos += ns
    else:
        pb = []
    if pb:
        cbits += 1
        ch = [[(c[k] << 1) | pb[k] for k in range(ne)] for c in ch]
        if ab:
            abits += 1
            alpha = [(alpha[k] << 1) | pb[k] for k in range(ne)]
    ep_r = [_expand(x, cbits) for x in ch[0]]
    ep_g = [_expand(x, cbits) for x in ch[1]]
    ep_b = [_expand(x, cbits) for x in ch[2]]
    ep_a = [_expand(x, abits) for x in alpha] if ab else [255] * ne

    subsets = _SUBSETS_BY_COUNT[ns][part]
    anchors = _ANCHORS_BY_COUNT[ns][part]

    col_idx: list[int]
    al_idx: list[int] | None
    # Primary indices, in pixel order; anchor pixels lose their top bit.
    idx1 = [0] * 16
    for i in range(16):
        s = subsets[i]
        n = ib - 1 if i == anchors[s] else ib
        idx1[i] = (v >> pos) & ((1 << n) - 1)
        pos += n
    if ib2:
        idx2 = [0] * 16
        for i in range(16):
            n = ib2 - 1 if i == 0 else ib2
            idx2[i] = (v >> pos) & ((1 << n) - 1)
            pos += n
        if sel:  # index-select: colour uses the 3-bit set, alpha the 2-bit set
            col_idx, col_w, al_idx, al_w = idx2, _WEIGHTS[ib2], idx1, _WEIGHTS[ib]
        else:
            col_idx, col_w, al_idx, al_w = idx1, _WEIGHTS[ib], idx2, _WEIGHTS[ib2]
    else:
        col_idx, col_w, al_idx, al_w = idx1, _WEIGHTS[ib], idx1, _WEIGHTS[ib]
        if not ab:
            al_idx = None  # modes 0-3 are opaque

    px: list[tuple[int, int, int, int]] = []
    for i in range(16):
        s = subsets[i]
        e0 = s * 2
        e1 = e0 + 1
        w = col_w[col_idx[i]]
        r = ((64 - w) * ep_r[e0] + w * ep_r[e1] + 32) >> 6
        g = ((64 - w) * ep_g[e0] + w * ep_g[e1] + 32) >> 6
        b = ((64 - w) * ep_b[e0] + w * ep_b[e1] + 32) >> 6
        if al_idx is None:
            a = 255
        else:
            w = al_w[al_idx[i]]
            a = ((64 - w) * ep_a[e0] + w * ep_a[e1] + 32) >> 6
        if rot == 1:
            r, a = a, r
        elif rot == 2:
            g, a = a, g
        elif rot == 3:
            b, a = a, b
        px.append((r, g, b, a))
    return px


def decode_bc7(data: bytes, width: int, height: int) -> bytes:
    """Decode BC7 block data to row-major RGBA8 of `width` x `height` pixels."""
    bw = (width + 3) // 4
    bh = (height + 3) // 4
    if len(data) < bw * bh * 16:
        raise ValueError("truncated BC7 data")
    out = bytearray(width * height * 4)
    for by in range(bh):
        y0 = by * 4
        rows = min(4, height - y0)
        for bx in range(bw):
            x0 = bx * 4
            cols = min(4, width - x0)
            o = (by * bw + bx) * 16
            px = _decode_block(data[o : o + 16])
            for dy in range(rows):
                dst = ((y0 + dy) * width + x0) * 4
                row = px[dy * 4 : dy * 4 + cols]
                out[dst : dst + cols * 4] = bytes([c for p in row for c in p])
    return bytes(out)
