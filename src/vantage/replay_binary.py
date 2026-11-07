"""Bounded native save-stream primitives shared by DE world restoration.

Unlike an input command's time stamp, ``version`` is the native unsigned
16.16 save-version word. No record scan or resynchronization is performed.
"""

from __future__ import annotations

import struct


class SaveDecodeError(ValueError):
    """Invalid or unsupported data at an exact inflated-header offset."""

    def __init__(self, message: str, offset: int) -> None:
        self.offset = offset
        super().__init__(f"saved world at {offset:#x}: {message}")


class SaveReader:
    """A checked cursor over a decompressed saved-world byte stream."""

    def __init__(self, data: bytes, pos: int = 0, *, version: int = 0x44E666) -> None:
        if not 0 <= pos <= len(data):
            raise SaveDecodeError("cursor outside saved world", pos)
        self.data = data
        self.pos = pos
        self.version = version

    @property
    def remaining(self) -> int:
        return len(self.data) - self.pos

    def take(self, count: int) -> bytes:
        at = self.pos
        if not 0 <= count <= self.remaining:
            raise SaveDecodeError(f"invalid or truncated read of {count} bytes", at)
        self.pos += count
        return self.data[at : self.pos]

    def skip(self, count: int) -> None:
        if not 0 <= count <= self.remaining:
            raise SaveDecodeError(f"invalid or truncated skip of {count} bytes", self.pos)
        self.pos += count

    def _int(self, size: int, signed: bool = False) -> int:
        return int.from_bytes(self.take(size), "little", signed=signed)

    def u8(self) -> int:
        return self._int(1)

    def i8(self) -> int:
        return self._int(1, True)

    def u16(self) -> int:
        return self._int(2)

    def i16(self) -> int:
        return self._int(2, True)

    def u32(self) -> int:
        return self._int(4)

    def i32(self) -> int:
        return self._int(4, True)

    def f32(self) -> float:
        return float(struct.unpack("<f", self.take(4))[0])

    def count(self, *, item_size: int, signed: bool = True) -> int:
        """Read a count and prove its minimum-sized array fits before looping."""
        at = self.pos
        value = self.i32() if signed else self.u32()
        if item_size <= 0 or not 0 <= value <= self.remaining // item_size:
            raise SaveDecodeError(f"invalid array count {value}", at)
        return value

    def marker(self, expected: int) -> None:
        """Native PlayerMarker1/2/3 are single bytes 11/22/33."""
        at = self.pos
        actual = self.u8()
        if actual != expected:
            raise SaveDecodeError(f"expected marker {expected}, found {actual}", at)

    def de_bytes(self) -> bytes:
        """Native DE string: u16 marker/length, accepting either field order.

        The current native helper accepts ``0x0a60,length`` and
        ``length,0x0a60``. Length does not require a trailing wire NUL.
        """
        at = self.pos
        first, second = self.u16(), self.u16()
        if first == 0x0A60:
            length = second
        elif second == 0x0A60:
            length = first
        else:
            raise SaveDecodeError("invalid DE string marker", at)
        return self.take(length)

    def de_string(self) -> str:
        return self.de_bytes().decode("utf-8", "replace")
