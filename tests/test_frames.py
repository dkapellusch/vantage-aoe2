"""vantage.frames: Frame and the .vrec recording format."""

from __future__ import annotations

import gzip
from pathlib import Path

import pytest

from vantage.frames import (
    MAGIC,
    Frame,
    RecordingWriter,
    from_proto,
    read_frames,
    read_header,
)


def _frames() -> list[Frame]:
    return [
        Frame(time=0, patch=b"\x04\x00\x01\x01", reverse=b"\x00\x01"),
        Frame(time=100, patch=b"\x03\x00\x01", events=[{"kind": "playerchat", "text": "hi ✓"}]),
        Frame(time=200, patch=b"", commands=[{"kind": "move", "commplayerid": 1}], skipped=3),
    ]


def test_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "r.vrec"
    with RecordingWriter(path, {"source": "test"}) as w:
        for f in _frames():
            w.write(f)
        w.flush()
        assert w.frames == 3
    assert read_header(path)["source"] == "test"
    back = list(read_frames(path))
    assert back == _frames()
    assert back[0].is_snapshot and not back[1].is_snapshot and not back[2].is_snapshot


def test_torn_recording_yields_complete_frames(tmp_path: Path) -> None:
    path = tmp_path / "r.vrec"
    with RecordingWriter(path) as w:
        for f in _frames():
            w.write(f)
    data = gzip.decompress(path.read_bytes())
    torn = tmp_path / "torn.vrec"
    torn.write_bytes(gzip.compress(data[:-5]))
    assert [f.time for f in read_frames(torn)] == [0, 100]
    cut = tmp_path / "cut.vrec"
    cut.write_bytes(path.read_bytes()[:-12])  # gzip stream itself truncated
    assert [f.time for f in read_frames(cut)][:2] == [0, 100]


def test_rejects_other_files(tmp_path: Path) -> None:
    bad = tmp_path / "bad.vrec"
    bad.write_bytes(gzip.compress(b"NOPE" + b"\x00" * 10))
    with pytest.raises(ValueError, match=r"not a \.vrec"):
        read_header(bad)
    assert gzip.decompress(gzip.compress(MAGIC))[:4] == b"VREC"


def test_from_proto() -> None:
    pytest.importorskip("google.protobuf")
    from vantage.rpc import cade_pb2 as pb

    fr = pb.Frame(time=0, patch=b"\x03", reversepatch=b"\x00", timestepsskipped=2)
    ev = fr.event.add()
    ev.damage.entityid = 7
    ev.damage.iskillingblow = True
    cmd = fr.command.add()
    cmd.move.commplayerid = 2
    f = from_proto(fr, world_time=55)
    assert f.time == 55 and f.patch == b"\x03" and f.reverse == b"\x00" and f.skipped == 2
    assert f.events == [{"kind": "damage", "entityid": 7, "iskillingblow": True}]
    assert f.commands == [{"kind": "move", "commplayerid": 2}]
