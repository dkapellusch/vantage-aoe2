"""Lossless, streaming input log for modern DE recordings (``VER 9.4``).

This is input to replay simulation, not simulated world state. Action bytes
are preserved even when their command is unknown. See
``docs/design/native-replay-playback.md`` for measured layout and coverage.
No game, gRPC, or third-party replay parser is needed.
"""

from __future__ import annotations

import struct
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Literal

OperationKind = Literal["action", "sync", "viewlock", "chat", "chapter", "postgame"]
_META_SIZE = 32
_CHECKSUM_SIZE = 360
_MAX_RECORD_SIZE = 64 << 20
_U32 = struct.Struct("<I")


class ReplayStreamError(ValueError):
    """An unsupported or damaged record, with its original file offset."""

    def __init__(self, message: str, offset: int) -> None:
        self.offset = offset
        super().__init__(f"replay at {offset:#x}: {message}")


@dataclass(frozen=True, slots=True)
class ReplayOperation:
    """One input record in file order, with absolute game time in milliseconds.

    ``payload`` excludes operation framing. For actions it contains the entire
    command, including its DE command header; for syncs it includes the delta
    and optional checksum block. A chapter payload is its two file pointers;
    the compressed saved world between the pointers is skipped, not decoded.
    Postgame payload includes the final clock and remaining trailer bytes.
    View locks and chats carry the latest sync clock, not a separate timestamp.
    """

    kind: OperationKind
    offset: int
    time_ms: int
    payload: bytes


class _Stream:
    def __init__(self, fh: BinaryIO, size: int, next_chapter: int) -> None:
        self.fh = fh
        self.size = size
        self.next_chapter = next_chapter

    def read(self, size: int) -> bytes:
        at = self.fh.tell()
        if not 0 <= size <= _MAX_RECORD_SIZE:
            raise ReplayStreamError(f"invalid record length {size}", at)
        if self.next_chapter and at < self.next_chapter < at + size:
            raise ReplayStreamError("chapter pointer falls inside a record", at)
        raw = self.fh.read(size)
        if len(raw) != size:
            raise ReplayStreamError("truncated record", at)
        return raw

    def u32(self) -> int:
        return int(_U32.unpack(self.read(4))[0])

    def records(self) -> Iterator[ReplayOperation]:
        elapsed = 0
        while self.fh.tell() < self.size:
            at = self.fh.tell()
            if self.next_chapter and at == self.next_chapter:
                raw = self.read(8)
                resume, following = struct.unpack("<II", raw)
                if not at + 8 <= resume <= self.size:
                    raise ReplayStreamError("invalid chapter resume pointer", at)
                if following and not resume <= following <= self.size - 8:
                    raise ReplayStreamError("invalid next chapter pointer", at)
                self.next_chapter = following
                self.fh.seek(resume)
                yield ReplayOperation("chapter", at, elapsed, raw)
                continue
            op = self.u32()
            if op == 1:
                payload = self.read(self.u32())
                if not payload:
                    raise ReplayStreamError("empty action", at)
                clock = self.u32()
                yield ReplayOperation("action", at, clock, payload)
            elif op == 2:
                raw = self.read(4)
                elapsed += _U32.unpack(raw)[0]
                # A zero word cannot start an operation. It marks the fixed
                # checksum block; the marker is part of its 360 bytes.
                peek_at = self.fh.tell()
                if peek_at + 4 <= self.size:
                    peek = self.read(4)
                    self.fh.seek(peek_at)
                    if peek == b"\0\0\0\0":
                        raw += self.read(_CHECKSUM_SIZE)
                yield ReplayOperation("sync", at, elapsed, raw)
            elif op == 3:
                yield ReplayOperation("viewlock", at, elapsed, self.read(12))
            elif op == 4:
                marker = self.read(4)
                payload = self.read(self.u32())
                yield ReplayOperation("chat", at, elapsed, marker + payload)
            elif op == 6:
                clock_bytes = self.read(4)
                trailer = self.read(self.size - self.fh.tell())
                yield ReplayOperation(
                    "postgame", at, _U32.unpack(clock_bytes)[0], clock_bytes + trailer
                )
                return
            else:
                raise ReplayStreamError(f"unknown operation {op}", at)


def iter_replay_operations(path: str | Path) -> Iterator[ReplayOperation]:
    """Read a modern DE input log, preserving order, unknown actions and bytes.

    Resumed recordings have a nonzero clock origin. Find that origin from the
    first action's absolute clock minus the preceding sync deltas, then rewind
    the short prefix. This also timestamps sync/view/chat records before that
    action correctly without retaining the whole replay in memory. Corruption
    raises :class:`ReplayStreamError`; it is never silently skipped.
    """
    with Path(path).open("rb") as fh:
        fh.seek(0, 2)
        size = fh.tell()
        fh.seek(0)
        stream = _Stream(fh, size, 0)
        header_end, chapter = struct.unpack("<II", stream.read(8))
        if not 8 < header_end <= size - _META_SIZE:
            raise ReplayStreamError("invalid header end", 0)
        start = header_end + _META_SIZE
        if chapter and not start <= chapter <= size - 8:
            raise ReplayStreamError("invalid chapter pointer", 4)
        fh.seek(header_end)
        meta = stream.read(_META_SIZE)
        if struct.unpack_from("<II", meta) != (5, 500):
            raise ReplayStreamError("unsupported DE body metadata", header_end)
        stream.next_chapter = chapter
        elapsed = origin = 0
        for record in stream.records():
            if record.kind == "sync":
                elapsed = record.time_ms
            elif record.kind == "action":
                origin = record.time_ms - elapsed
                if origin < 0:
                    raise ReplayStreamError("negative clock origin", record.offset)
                break
            elif record.kind == "postgame":
                origin = max(0, record.time_ms - elapsed)
                break
        fh.seek(start)
        stream.next_chapter = chapter
        for record in stream.records():
            if record.kind in {"action", "postgame"}:
                yield record
            else:
                yield ReplayOperation(
                    record.kind, record.offset, origin + record.time_ms, record.payload
                )
