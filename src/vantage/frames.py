"""Frames: the unit of the spectator stream, plus the ``.vrec`` recording format.

A :class:`Frame` is one ``cade_api.rpc.Frame`` reduced to plain data: game time,
the forward patch, the reverse patch, and the frame's events and commands as
dicts. Everything downstream (the patcher, the timeline, the server) consumes
these, so a live gRPC stream and a recording on disk are interchangeable.

``.vrec`` layout (gzip-compressed stream)::

    b"VREC\\x01"  u32 header_len  header_json
    repeat:  u32 time  u32 skipped  u32 len  patch
             u32 len  reverse_patch  u32 len  events_json  u32 len  commands_json

``header_json`` carries ``{"version", "created", "source", "game_version", ...}``.
Frames are appended as they arrive, so a recording interrupted mid-game is still
readable up to its last complete frame.
"""

from __future__ import annotations

import base64
import gzip
import json
import struct
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

MAGIC = b"VREC\x01"
_U32 = struct.Struct("<I")


@dataclass(slots=True)
class Frame:
    """One step of game time."""

    time: int
    patch: bytes
    reverse: bytes = b""
    events: list[dict[str, Any]] = field(default_factory=list)
    commands: list[dict[str, Any]] = field(default_factory=list)
    skipped: int = 0

    @property
    def is_snapshot(self) -> bool:
        """True for a frame that builds the world from nothing (PUSH_CREATE root)."""
        return len(self.patch) > 0 and self.patch[0] == 4


class RecordingWriter:
    """Append frames to a ``.vrec`` file."""

    def __init__(self, path: str | Path, header: dict[str, Any] | None = None) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        meta = {"version": 1, "created": time.time(), **(header or {})}
        raw = json.dumps(meta).encode()
        # Held open for the recording's lifetime; closed by close()/__exit__.
        self._fh: gzip.GzipFile = gzip.open(self.path, "wb", compresslevel=5)  # noqa: SIM115
        self._fh.write(MAGIC + _U32.pack(len(raw)) + raw)
        self.frames = 0

    def write(self, f: Frame) -> None:
        ev = json.dumps(f.events, separators=(",", ":")).encode() if f.events else b""
        cm = json.dumps(f.commands, separators=(",", ":")).encode() if f.commands else b""
        w = self._fh.write
        w(_U32.pack(f.time) + _U32.pack(f.skipped))
        for blob in (f.patch, f.reverse, ev, cm):
            w(_U32.pack(len(blob)))
            w(blob)
        self.frames += 1

    def flush(self) -> None:
        self._fh.flush()

    def close(self) -> None:
        self._fh.close()

    def __enter__(self) -> RecordingWriter:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def _read_exact(fh: gzip.GzipFile, n: int) -> bytes | None:
    buf = fh.read(n)
    return buf if len(buf) == n else None


def read_header(path: str | Path) -> dict[str, Any]:
    with gzip.open(path, "rb") as fh:
        return _header(fh)


def _header(fh: gzip.GzipFile) -> dict[str, Any]:
    if fh.read(len(MAGIC)) != MAGIC:
        raise ValueError("not a .vrec recording")
    head = _read_exact(fh, 4)
    if head is None:
        raise ValueError("truncated .vrec header")
    raw = _read_exact(fh, _U32.unpack(head)[0])
    if raw is None:
        raise ValueError("truncated .vrec header")
    meta: dict[str, Any] = json.loads(raw)
    return meta


def read_frames(path: str | Path) -> Iterator[Frame]:
    """Yield every complete frame in a recording (a torn tail is ignored)."""
    with gzip.open(path, "rb") as fh:
        _header(fh)
        while True:
            try:
                head = _read_exact(fh, 8)
            except EOFError:  # gzip stream cut mid-member: recording was interrupted
                return
            if head is None:
                return
            t, skipped = struct.unpack("<II", head)
            blobs: list[bytes] = []
            for _ in range(4):
                try:
                    ln = _read_exact(fh, 4)
                    blob = _read_exact(fh, _U32.unpack(ln)[0]) if ln is not None else None
                except EOFError:
                    return
                if blob is None:
                    return
                blobs.append(blob)
            patch, rev, ev, cm = blobs
            yield Frame(
                time=t,
                patch=patch,
                reverse=rev,
                events=json.loads(ev) if ev else [],
                commands=json.loads(cm) if cm else [],
                skipped=skipped,
            )


def from_proto(frame: Any, world_time: int = 0) -> Frame:
    """Convert a ``Frame`` from :mod:`vantage.rpc.cade_pb2` (needs ``protobuf``)."""
    from google.protobuf.json_format import MessageToDict

    def _oneofs(items: Any, oneof: str) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for item in items:
            if not item.DESCRIPTOR.oneofs_by_name.get(oneof):
                # Shape not declared in rpc/cade.proto: keep the wire bytes verbatim.
                out.append(
                    {"kind": "raw", "b64": base64.b64encode(item.SerializeToString()).decode()}
                )
                continue
            which = item.WhichOneof(oneof)
            if which is None:
                continue
            payload = MessageToDict(getattr(item, which), preserving_proto_field_name=True)
            out.append({"kind": which, **payload})
        return out

    return Frame(
        time=int(frame.time) or world_time,
        patch=bytes(frame.patch),
        reverse=bytes(frame.reversepatch),
        events=_oneofs(frame.event, "event"),
        commands=_oneofs(frame.command, "command"),
        skipped=int(frame.timestepsskipped),
    )
