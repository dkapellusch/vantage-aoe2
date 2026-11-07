"""Small native player-AI modules in DE save68.9.

These are serialized player decision modules, distinct from per-object UnitAI.
The native readers and marker globals are preserved in the player-ai evidence.
No planner updates or native postload string rewriting are performed here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from vantage.replay_binary import SaveDecodeError, SaveReader

SimpleAIKind = Literal["main", "diplomacy", "emotional", "resource", "strategy", "trade"]


@dataclass(frozen=True, slots=True)
class SavedSimpleAI:
    offset: int
    end_offset: int
    kind: SimpleAIKind
    fields: dict[int, int]
    vectors: dict[int, bytes]
    lists: dict[int, tuple[int, ...]]
    strings: dict[int, bytes]
    raw: bytes


def _marker(r: SaveReader, expected: int) -> None:
    at = r.pos
    actual = r.u16()
    if actual != expected:
        raise SaveDecodeError(f"expected AI marker {expected:#x}, found {actual:#x}", at)


def _words(r: SaveReader) -> tuple[int, ...]:
    at = r.pos
    count = r.i32()
    # These native loops run only for positive signed counts. Preserve
    # nonpositive-count bytes in raw while producing their empty collection.
    if count > r.remaining // 4:
        raise SaveDecodeError(f"invalid AI word-list count {count}", at)
    return tuple(r.u32() for _ in range(max(count, 0)))


def read_simple_ai(reader: SaveReader, kind: SimpleAIKind) -> SavedSimpleAI:
    """Read one named module, restoring the cursor on any decode failure.

    AI markers are u16 values0xa10/0xaa0/0xa20. They are not the one-byte
    player markers, and a matching marker alone is not a section boundary.
    """
    start = reader.pos
    try:
        return _read_simple_ai(reader, kind)
    except SaveDecodeError:
        reader.pos = start
        raise


def _read_simple_ai(r: SaveReader, kind: SimpleAIKind) -> SavedSimpleAI:
    start = r.pos
    if r.version != 0x44E666:
        raise SaveDecodeError(f"unsupported player-AI save version {r.version:#x}", start)
    if kind not in {"main", "diplomacy", "emotional", "resource", "strategy", "trade"}:
        raise SaveDecodeError(f"unsupported player-AI module {kind}", start)
    fields: dict[int, int] = {}
    vectors: dict[int, bytes] = {}
    lists: dict[int, tuple[int, ...]] = {}
    strings: dict[int, bytes] = {}
    _marker(r, 0xA10)
    if kind == "main":
        # 0x140c26b80, after its init-only Main Decision AI base constructor.
        lists[0xB8] = _words(r)
    elif kind == "diplomacy":
        # 0x140c23fe0: ten interleaved word/word/byte triples.
        for i in range(10):
            fields[0xB8 + i * 4] = r.u32()
            fields[0xE0 + i * 4] = r.u32()
            fields[0x108 + i] = r.u8()
    elif kind == "emotional":
        # 0x140c25fc0: native emotion-name strings are initialized, not saved.
        fields = {offset: r.u32() for offset in range(0xB8, 0xD0, 4)}
    elif kind == "resource":
        fields[0xB8] = r.u32()  # 0x140c871d0
    elif kind == "strategy":
        # 0x140c88110, after init-only 0x140c2a930.
        for offset in (0xB8, 0xD8, 0xE0, 0xE4):
            fields[offset] = r.u32()
        vectors = {offset: r.take(16) for offset in (0xE8, 0xF8)}
        for offset in (0x108, 0x10C, 0x110, 0x968):
            fields[offset] = r.u32()
        _marker(r, 0xAA0)
        # 0x140a1c660 ->0x140a150f0: u32 length, then exactly that many
        # bytes (maximum10MiB), without an implicit extra wire terminator.
        at = r.pos
        size = r.u32()
        if size > 0xA00000:
            raise SaveDecodeError(f"invalid AI strategy string length {size}", at)
        strings[0xC0] = r.take(size)
        for offset in (0x118, 0x130, 0x148):
            lists[offset] = _words(r)
        fields[0x978] = r.u32()
    # TradeAI0x140c2aa90 contains only its two markers.
    _marker(r, 0xA20)
    return SavedSimpleAI(start, r.pos, kind, fields, vectors, lists, strings, r.data[start : r.pos])
