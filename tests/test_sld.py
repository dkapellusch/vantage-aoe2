"""vantage.sld: the SLD sprite decoder, on synthetic files."""

from __future__ import annotations

import struct

import pytest

from vantage.sld import (
    LAYER_DAMAGE,
    LAYER_MAIN,
    LAYER_PLAYER,
    LAYER_SHADOW,
    SLD,
    SLDError,
    bc1,
    bc4,
    render,
)

RED = struct.pack("<HHI", 0xF800, 0x0000, 0)  # BC1: every pixel colour 0 = red
BLACK = struct.pack("<HHI", 0x0000, 0x0001, 0)  # BC1 colour 0 = black (opaque)
GREY = struct.pack("<HHI", 0x8410, 0x0000, 0)  # mid grey
FULL = bytes([255, 0]) + b"\x00" * 6  # BC4: every pixel 255


def _layer(
    rect: tuple[int, int, int, int] | None,
    flag: int,
    cmds: list[tuple[int, int]],
    blocks: list[bytes],
) -> bytes:
    head = struct.pack("<HHHHBB", *rect, flag, 0) if rect else bytes([flag, 0])
    body = head + struct.pack("<H", len(cmds)) + b"".join(bytes(c) for c in cmds) + b"".join(blocks)
    rec = struct.pack("<I", 4 + len(body)) + body
    return rec + b"\x00" * (-len(rec) % 4)


def _sld(frames: list[tuple[int, list[bytes]]], header_size: int = 16) -> bytes:
    head = b"SLDX" + struct.pack("<HHHH", 4, len(frames), 0, header_size)
    head += b"\xff\x00" + (b"\x00\x00" if header_size == 16 else b"")
    out = head[:header_size]
    for layers_bits, layers in frames:
        out += struct.pack("<HHHHBBH", 8, 8, 4, 6, layers_bits, 0, 0) + b"".join(layers)
    return out


def test_blocks_decode() -> None:
    assert bc1(RED)[0] == (255, 0, 0, 255)
    assert bc4(FULL) == (255,) * 16


@pytest.mark.parametrize("header_size", [16, 14])
def test_frames_layers_and_tint(header_size: int) -> None:
    rect = (0, 0, 8, 4)  # 2 blocks wide, 1 high
    f0 = _layer(rect, 0, [(0, 2)], [RED, GREY])
    p0 = _layer(None, 0, [(1, 1)], [FULL])  # player mask over the grey block only
    f1 = _layer(rect, 0x80, [(1, 1)], [GREY])  # reuse block 0 from frame 0
    data = _sld([(LAYER_MAIN | LAYER_PLAYER, [f0, p0]), (LAYER_MAIN, [f1])], header_size)
    sld = SLD(data)
    assert sld.count == 2 and (sld.frames[0].hotspot_x, sld.frames[0].hotspot_y) == (4, 6)
    w, h, hx, hy, px = render(sld, 0, (0, 0, 255))
    assert (w, h, hx, hy) == (8, 8, 4, 6)
    assert px[0:4] == bytes([255, 0, 0, 255])  # red block untouched
    o = (0 * 8 + 4) * 4
    assert px[o + 2] > px[o] and px[o + 3] == 255  # grey block tinted blue
    assert px[(5 * 8) * 4 + 3] == 0  # below the rectangle: transparent
    _, _, _, _, px1 = render(sld, 1)
    assert px1[0:4] == bytes([255, 0, 0, 255])  # reused from frame 0
    # Decoding frame 1 first still replays frame 0 for the reuse.
    assert render(SLD(data), 1)[4][0:4] == bytes([255, 0, 0, 255])


def test_not_an_sld() -> None:
    with pytest.raises(SLDError):
        SLD(b"NOPE" + b"\x00" * 20)


def test_damage_darkens_like_the_game_shader() -> None:
    """SpritesSLD_ps: w = R*sat(2d) + G*sat(2(d-.25)) + B*sat(2(d-.5)), capped at
    0.65, and rgb *= 1 - w (red phases in first; a black mask never darkens)."""
    rect = (0, 0, 8, 4)
    main = _layer(rect, 0, [(0, 2)], [GREY, GREY])
    dmg = _layer(None, 0, [(0, 2)], [RED, BLACK])
    sld = SLD(_sld([(LAYER_MAIN | LAYER_DAMAGE, [main, dmg])]))
    clean = render(sld, 0)[4]
    assert render(sld, 0, damage=0.0)[4] == clean
    quarter = render(sld, 0, damage=0.25)[4]  # red at half strength: w = 0.5
    full = render(sld, 0, damage=1.0)[4]  # red at full strength, capped: w = 0.65
    assert quarter[0] == int(clean[0] * 0.5) and quarter[3] == 255
    assert full[0] == int(clean[0] * 0.35)
    o = 4 * 4  # first pixel of the right block (black mask)
    assert full[o : o + 4] == clean[o : o + 4]


def test_layer_selection() -> None:
    rect = (0, 0, 4, 4)
    main = _layer(rect, 0, [(0, 1)], [RED])
    shadow = _layer((0, 4, 4, 8), 0, [(0, 1)], [FULL])
    sld = SLD(_sld([(LAYER_MAIN | LAYER_SHADOW, [main, shadow])]))
    both = render(sld, 0)[4]
    assert both[0:4] == bytes([255, 0, 0, 255]) and both[(4 * 8) * 4 + 3] == 127
    only_main = render(sld, 0, shadow=False)[4]
    assert only_main[0:4] == bytes([255, 0, 0, 255]) and only_main[(4 * 8) * 4 + 3] == 0
    only_shadow = render(sld, 0, main=False)[4]
    assert only_shadow[3] == 0 and only_shadow[(4 * 8) * 4 + 3] == 127


def test_all_zero_main_blocks_take_their_row_neighbour() -> None:
    """An all-zero BC1 block decodes to opaque black; the game shows the picture
    carrying on there, so the decoder fills it from the nearest block in its row
    (and leaves it transparent when the row has none)."""
    from vantage.sld import LAYER_MAIN, Layer, _fill_zero_blocks

    grey = bytes([0x10, 0x84, 0x10, 0x84, 0, 0, 0, 0])
    zero = b"\0" * 8
    stripes = b"\0\0\0\0\x03\x03\x03\x03"  # both colours 0: black or transparent pixels
    main = Layer((0, 0, 12, 8), 0, [grey, zero, None, zero, stripes, zero])  # 3x2 blocks
    _fill_zero_blocks({LAYER_MAIN: main}, reach=2)
    assert main.blocks[:3] == [grey, grey, None]
    assert main.blocks[3:] == [None, None, None]  # a row with nothing to borrow


def test_reused_blocks_follow_the_canvas_when_the_rectangle_moves() -> None:
    """Inter-frame reuse (flag 0x80) repeats the previous frame's block at the same
    canvas pixels, also when the two frames' rectangles differ."""
    from vantage.sld import Layer, _block_at

    a, b = bytes([1] * 8), bytes([2] * 8)
    prev = Layer((8, 4, 16, 8), 0, [a, b])  # blocks at x 8 and 12, y 4
    assert _block_at(prev, 12, 4) == b and _block_at(prev, 8, 4) == a
    assert _block_at(prev, 4, 4) is None  # left of the old rectangle
    assert _block_at(prev, 10, 4) is None  # not block-aligned
    assert _block_at(prev, 12, 8) is None  # below it


def test_reuse_continues_an_animation_only_within_one_facing() -> None:
    """Frame 1 skips its first block with the reuse flag: within a facing it repeats
    frame 0's block; as the first frame of the next facing it is left empty."""
    rect = (0, 0, 8, 4)
    first = _layer(rect, 0, [(0, 2)], [RED, GREY])
    second = _layer(rect, 0x80, [(1, 1)], [GREY])  # skip block 0, draw block 1
    data = _sld([(LAYER_MAIN, [first]), (LAYER_MAIN, [second])])
    one_facing = SLD(data)
    one_facing.set_frames_per_facing(2)
    assert one_facing.layers(1)[LAYER_MAIN].blocks[0] == RED
    per_frame = SLD(data)
    per_frame.set_frames_per_facing(1)  # frame 1 is another facing
    assert per_frame.layers(1)[LAYER_MAIN].blocks[0] is None


def test_a_facing_with_no_pixels_of_its_own_repeats_the_frame_before_it() -> None:
    rect = (0, 0, 8, 4)
    first = _layer(rect, 0, [(0, 2)], [RED, GREY])
    repeat = _layer(rect, 0x80, [(2, 0)], [])  # reuse flag, skips everything, draws nothing
    data = _sld([(LAYER_MAIN, [first]), (LAYER_MAIN, [repeat])])
    per_frame = SLD(data)
    per_frame.set_frames_per_facing(1)
    assert per_frame.layers(1)[LAYER_MAIN].blocks == [RED, GREY]
    # Frames with their own pixels still start afresh at a facing (the trebuchet fix).
    drawn = _layer(rect, 0x80, [(1, 1)], [GREY])
    own = SLD(_sld([(LAYER_MAIN, [first]), (LAYER_MAIN, [drawn])]))
    own.set_frames_per_facing(1)
    assert own.layers(1)[LAYER_MAIN].blocks[0] is None
