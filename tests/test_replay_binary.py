"""Native save-string variants, boundaries and corruption behavior."""

from __future__ import annotations

import struct

import pytest

from vantage.replay_binary import SaveDecodeError, SaveReader


@pytest.mark.parametrize("reversed_order", [False, True])
@pytest.mark.parametrize("text", [b"", b"gaia", "文明".encode(), b"a\0b"])
def test_native_de_string_orders_and_exact_payload(text: bytes, reversed_order: bool) -> None:
    words = (len(text), 0x0A60) if reversed_order else (0x0A60, len(text))
    reader = SaveReader(struct.pack("<HH", *words) + text + b"tail")
    assert reader.de_bytes() == text
    assert reader.take(4) == b"tail"


@pytest.mark.parametrize("payload", [b"", b"\x60\x0a", b"\x60\x0a\x10\0short", bytes(4)])
def test_bad_strings_raise_a_located_error(payload: bytes) -> None:
    with pytest.raises(SaveDecodeError) as caught:
        SaveReader(payload).de_bytes()
    assert caught.value.offset in {0, 2, 4}


def test_signed_native_values_and_float_bits_are_preserved() -> None:
    reader = SaveReader(struct.pack("<bhHiIf", -1, -123, 65535, -10, 0xFFFFFFFF, -1.25))
    assert (reader.i8(), reader.i16(), reader.u16(), reader.i32(), reader.u32(), reader.f32()) == (
        -1,
        -123,
        65535,
        -10,
        0xFFFFFFFF,
        -1.25,
    )
    assert reader.remaining == 0


@pytest.mark.parametrize("size", [-1, 4, 0xFFFFFFFF])
def test_untrusted_length_cannot_move_past_data(size: int) -> None:
    reader = SaveReader(b"abc", 1)
    with pytest.raises(SaveDecodeError):
        reader.take(size)
    assert reader.pos == 1
    with pytest.raises(SaveDecodeError):
        reader.skip(size)
    assert reader.pos == 1


@pytest.mark.parametrize("count", [-1, 3, 0x7FFFFFFF])
def test_array_count_is_checked_before_looping(count: int) -> None:
    reader = SaveReader(struct.pack("<i", count) + bytes(8))
    with pytest.raises(SaveDecodeError, match="array count"):
        reader.count(item_size=4)


def test_native_markers_are_single_bytes() -> None:
    reader = SaveReader(bytes([11, 22, 33]))
    for marker in (11, 22, 33):
        reader.marker(marker)
    assert reader.remaining == 0
    with pytest.raises(SaveDecodeError, match="expected marker 11"):
        SaveReader(b"\x16").marker(11)


@pytest.mark.parametrize("pos", [-1, 4])
def test_cursor_must_start_inside_data(pos: int) -> None:
    with pytest.raises(SaveDecodeError):
        SaveReader(b"abc", pos)
