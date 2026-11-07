"""Exact saved Build AI base/derived wire grammar for native DE save68.9.

Native readers 0x140c0db80 and 0x140c2aff0 serialize counted strings/build
records followed by two fixed arrays. This decodes saved state, without
executing AI logic or reproducing the native constructor's record filtering.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from vantage.replay_binary import SaveDecodeError, SaveReader

# Labels identify the native decompiler locals in their actual wire order.
# They are not native memory offsets or claims about gameplay semantics.
BUILD_ENTRY_WORD_LOCALS = (
    "local_234",
    "local_1e4",
    "local_20c",
    "local_1e0",
    "local_1dc",
    "local_1d8",
    "local_214",
    "local_218",
    "local_21c",
    "local_1e8",
    "local_230",
    "local_1f0",
    "local_1f8",
    "local_1ec",
    "local_210",
    "local_220",
    "local_224",
    "local_228",
    "local_22c",
    "local_1d4",
    "local_1fc",
    "local_1d0",
)


@dataclass(frozen=True, slots=True)
class SavedBuildListEntry:
    """A complete serialized entry, retained even if native loading discards it.

    The modern wire order after its name is 22 words, two bytes, another word,
    and two bytes. The four flags are local_205/208/206/207 respectively; the
    intervening extra word is local_200. Original words preserve scalar bits.
    """

    offset: int
    end_offset: int
    name_bytes: bytes
    words: tuple[int, ...]
    flags: tuple[int, int, int, int]
    extra_word: int
    raw: bytes


@dataclass(frozen=True, slots=True)
class SavedBuildAI:
    offset: int
    end_offset: int
    base_end_offset: int
    fields: dict[int, int]
    strings: tuple[bytes, bytes, bytes, bytes]
    entries: tuple[SavedBuildListEntry, ...]
    words_5c8: tuple[int, ...]
    bytes_9270: bytes
    sections: dict[str, bytes]
    raw: bytes


def _marker(reader: SaveReader, expected: int) -> None:
    at = reader.pos
    actual = reader.u16()
    if actual != expected:
        raise SaveDecodeError(f"expected AI marker {expected:#x}, found {actual:#x}", at)


def _string(reader: SaveReader) -> bytes:
    at = reader.pos
    length = reader.i32()
    if not 0 <= length <= 256:
        raise SaveDecodeError(f"invalid Build AI string length {length}", at)
    # Native char buffers have room for 256 wire bytes plus an appended NUL.
    # The appended terminator is not an extra stream byte.
    return reader.take(length)


def _entry(reader: SaveReader) -> SavedBuildListEntry:
    start = reader.pos
    _marker(reader, 0x0AA0)
    name = _string(reader)
    words = struct.unpack("<22I", reader.take(88))
    first, second = reader.u8(), reader.u8()
    extra = reader.u32()
    third, fourth = reader.u8(), reader.u8()
    return SavedBuildListEntry(
        start,
        reader.pos,
        name,
        words,
        (first, second, third, fourth),
        extra,
        reader.data[start : reader.pos],
    )


def read_build_ai(reader: SaveReader) -> SavedBuildAI:
    """Read the whole base plus derived module; roll back on any failure.

    Start immediately after MainDecisionAI's closing marker0x0a20. The following
    ConAI marker remains unread. No boundary search or measured-gap skip runs.
    Native derived counts are 9000 at save>=0x0ca666; all 68.9 gates are fixed
    explicitly rather than claiming compatibility with other save versions.
    """
    start = reader.pos
    try:
        if reader.version != 0x44E666:
            raise SaveDecodeError(f"unsupported Build AI save version {reader.version:#x}", start)
        _marker(reader, 0x0A10)
        fields = {0x170: reader.u32()}
        strings = (_string(reader), _string(reader), _string(reader), _string(reader))
        _marker(reader, 0x0AA0)
        fields[0x578] = reader.u32()
        # >=0x0b051f saves carry an explicit wire count separate from +0x170.
        entries = tuple(_entry(reader) for _ in range(reader.count(item_size=102)))
        _marker(reader, 0x0A20)
        base_end = reader.pos
        _marker(reader, 0x0A10)
        words_5c8 = struct.unpack("<9000I", reader.take(36000))
        # >=0x0bfae1 carries these bytes, after the word array and before
        # the two scalar members; runtime member order differs from wire order.
        bytes_9270 = reader.take(9000)
        fields[0x9268], fields[0x926C] = reader.u32(), reader.u32()
        _marker(reader, 0x0A20)
        sections = {
            "base": reader.data[start:base_end],
            "derived": reader.data[base_end : reader.pos],
        }
        return SavedBuildAI(
            start,
            reader.pos,
            base_end,
            fields,
            strings,
            entries,
            words_5c8,
            bytes_9270,
            sections,
            reader.data[start : reader.pos],
        )
    except SaveDecodeError:
        reader.pos = start
        raise
