"""Original DE stream framing, including saved chapters and resumed clocks."""

from __future__ import annotations

import gzip
import struct
from pathlib import Path

import pytest

from vantage.replay_stream import ReplayStreamError, iter_replay_operations

META = struct.pack("<8I", 5, 500, 0, 1, 1, 0, 0, 0)


def _action(time: int, payload: bytes = b"\x0b\x02\x01\0\0") -> bytes:
    return struct.pack("<II", 1, len(payload)) + payload + struct.pack("<I", time)


def _file(tmp_path: Path, body: bytes, chapter: int = 0) -> Path:
    path = tmp_path / "test.aoe2record"
    path.write_bytes(struct.pack("<II", 9, chapter) + b"x" + META + body)
    return path


def test_raw_records_preserve_bytes_order_and_resumed_time(tmp_path: Path) -> None:
    command = b"\xfe\x01\x03\0abc"  # Unknown command id is preserved.
    lock = struct.pack("<ffI", 12.5, 33.0, 1)
    chat = b'{"message":"hello"}'
    body = (
        struct.pack("<II", 2, 28)
        + struct.pack("<I", 3)
        + lock
        + struct.pack("<IiI", 4, -1, len(chat))
        + chat
        + _action(100028, command)
        + struct.pack("<II", 2, 10)
        + struct.pack("<II", 6, 100038)
        + b"trailer"
    )
    records = list(iter_replay_operations(_file(tmp_path, body)))
    assert [r.kind for r in records] == ["sync", "viewlock", "chat", "action", "sync", "postgame"]
    assert [r.time_ms for r in records] == [100028] * 4 + [100038] * 2
    assert records[1].payload == lock
    assert records[2].payload == struct.pack("<i", -1) + chat
    assert records[3].payload == command
    assert records[-1].payload == struct.pack("<I", 100038) + b"trailer"
    assert records[0].offset == 41


def test_checksum_stays_attached_to_its_sync(tmp_path: Path) -> None:
    checksum = bytes(4) + bytes(range(178)) * 2
    path = _file(tmp_path, struct.pack("<II", 2, 28) + checksum + _action(28))
    records = list(iter_replay_operations(path))
    assert len(records) == 2
    assert records[0].payload == struct.pack("<I", 28) + checksum
    assert records[1].offset == 41 + 8 + 360


def test_saved_chapter_skips_compressed_world_without_changing_clock(tmp_path: Path) -> None:
    first = struct.pack("<II", 2, 28) + _action(28)
    at = 41 + len(first)
    saved = b"a saved compressed world, not operation bytes"
    resume = at + 8 + len(saved)
    body = first + struct.pack("<II", resume, 0) + saved + struct.pack("<II", 2, 20) + _action(48)
    records = list(iter_replay_operations(_file(tmp_path, body, at)))
    assert [r.kind for r in records] == ["sync", "action", "chapter", "sync", "action"]
    assert records[2].offset == at
    assert records[3].offset == resume
    assert records[-1].time_ms == 48


@pytest.mark.parametrize(
    "body,match",
    [
        (struct.pack("<I", 97), "unknown operation 97"),
        (b"\x01", "truncated"),
        (struct.pack("<II", 1, 1000), "truncated"),
        (struct.pack("<II", 1, 0) + bytes(4), "empty action"),
        (struct.pack("<II", 2, 28) + _action(20), "negative clock origin"),
        (struct.pack("<II", 1, 0xFFFFFFFF), "invalid record length"),
        (struct.pack("<II", 2, 28) + bytes(20), "truncated"),
    ],
)
def test_corruption_is_reported_with_original_offset(
    tmp_path: Path, body: bytes, match: str
) -> None:
    with pytest.raises(ReplayStreamError, match=match) as caught:
        list(iter_replay_operations(_file(tmp_path, body)))
    assert caught.value.offset >= 41


def test_chapter_cannot_jump_backwards(tmp_path: Path) -> None:
    path = _file(tmp_path, struct.pack("<II", 41, 41), 41)
    with pytest.raises(ReplayStreamError, match="resume pointer"):
        list(iter_replay_operations(path))


def test_chapter_cannot_split_an_operation(tmp_path: Path) -> None:
    path = _file(tmp_path, _action(28) + bytes(20), 50)
    with pytest.raises(ReplayStreamError, match="inside a record"):
        list(iter_replay_operations(path))


def test_no_action_uses_final_clock_to_anchor_syncs(tmp_path: Path) -> None:
    records = list(iter_replay_operations(_file(tmp_path, struct.pack("<4I", 2, 28, 6, 100028))))
    assert [r.time_ms for r in records] == [100028, 100028]


@pytest.mark.parametrize("players", [3, 6])
def test_real_trimmed_replay_fixture(tmp_path: Path, players: int) -> None:
    fixture = Path(__file__).parent / "fixtures" / f"replay_{players}p_54800.aoe2record.gz"
    path = tmp_path / "real.aoe2record"
    path.write_bytes(gzip.decompress(fixture.read_bytes()))
    records = list(iter_replay_operations(path))
    assert records[-1].kind == "postgame"
    assert any(r.kind == "action" for r in records)
    assert records[-1].time_ms > 1_000_000
