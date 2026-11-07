"""Checksum-bound preview input remains visibly incomplete and source-bound."""

from __future__ import annotations

import json
import struct
from pathlib import Path

import pytest
from test_replay_stream import _action, _file

from vantage import native_v32_preview as preview
from vantage.replay_stream import iter_replay_operations


def test_preview_preserves_original_operations_through_checksum(tmp_path: Path) -> None:
    first_sync = struct.pack("<II", 2, 20)
    checked_sync = struct.pack("<II", 2, 15) + bytes(360)
    action = _action(35)
    tail_sync = struct.pack("<II", 2, 25)
    source = _file(
        tmp_path, first_sync + checked_sync + action + tail_sync + struct.pack("<II", 6, 60)
    )
    original = source.read_bytes()
    result = preview.prepare_preview(source, tmp_path / "preview", through_sync=2)
    path = Path(result["preview"]["path"])
    operations = list(iter_replay_operations(path))
    assert path.name.startswith("INCOMPLETE-")
    assert [op.kind for op in operations] == ["sync", "sync", "action", "postgame"]
    assert [op.time_ms for op in operations] == [20, 35, 35, 35]
    cutoff = result["original_prefix_bytes"]
    assert path.read_bytes() == original[:cutoff] + struct.pack("<II", 6, 35)
    assert source.read_bytes() == original
    assert result["last_checksum_state_ms"] == 20 and result["after_last_checksum_ms"] == 15
    assert result["synthetic_eof"] and not result["checksum_verified_by_preparation"]
    assert not result["original_full_match_completed"]
    assert json.loads((path.parent / "preview.json").read_text()) == result
    with pytest.raises(FileExistsError):
        preview.prepare_preview(source, path.parent, through_sync=2)


def test_preview_cuts_before_a_future_timed_action(tmp_path: Path) -> None:
    checked_sync = struct.pack("<II", 2, 10) + bytes(360)
    source = _file(
        tmp_path,
        struct.pack("<II", 2, 10)
        + _action(10)
        + checked_sync
        + _action(25)
        + struct.pack("<II", 6, 25),
    )
    result = preview.prepare_preview(source, tmp_path / "preview", through_sync=2)
    assert [op.kind for op in iter_replay_operations(result["preview"]["path"])] == [
        "sync",
        "action",
        "sync",
        "postgame",
    ]


@pytest.mark.parametrize("ordinal", [0, -1, True])
def test_invalid_ordinal_does_not_create_output(tmp_path: Path, ordinal: int) -> None:
    source = _file(tmp_path, struct.pack("<4I", 2, 20, 6, 20))
    with pytest.raises(preview.PreviewError, match="positive integer"):
        preview.prepare_preview(source, tmp_path / "preview", through_sync=ordinal)
    assert not (tmp_path / "preview").exists()


def test_requires_checksum_and_following_boundary(tmp_path: Path) -> None:
    source = _file(tmp_path, struct.pack("<4I", 2, 20, 6, 20))
    with pytest.raises(preview.PreviewError, match="does not contain"):
        preview.prepare_preview(source, tmp_path / "unchecked", through_sync=1)
    assert not (tmp_path / "unchecked").exists()
    source = _file(tmp_path, struct.pack("<II", 2, 20) + bytes(360))
    with pytest.raises(preview.PreviewError, match="following replay boundary"):
        preview.prepare_preview(source, tmp_path / "no-end", through_sync=1)
    assert not (tmp_path / "no-end").exists()


def test_rejects_chapter_inputs_without_modifying_them(tmp_path: Path) -> None:
    body = struct.pack("<II", 49, 0) + struct.pack("<II", 2, 20)
    source = _file(tmp_path, body, chapter=41)
    original = source.read_bytes()
    with pytest.raises(preview.PreviewError, match="chapters"):
        preview.prepare_preview(source, tmp_path / "preview", through_sync=1)
    assert source.read_bytes() == original and not (tmp_path / "preview").exists()


def test_source_change_is_rejected_before_output(tmp_path: Path, monkeypatch) -> None:
    body = struct.pack("<II", 2, 20) + bytes(360) + struct.pack("<II", 6, 20)
    source = _file(tmp_path, body)
    original_iter = preview.iter_replay_operations

    def mutate_after_sync(path):
        for operation in original_iter(path):
            yield operation
            if operation.kind == "sync":
                with source.open("r+b") as stream:
                    stream.seek(-1, 2)
                    old = stream.read(1)
                    stream.seek(-1, 2)
                    stream.write(bytes([old[0] ^ 1]))

    monkeypatch.setattr(preview, "iter_replay_operations", mutate_after_sync)
    with pytest.raises(preview.PreviewError, match="changed during preview preparation"):
        preview.prepare_preview(source, tmp_path / "preview", through_sync=1)
    assert not (tmp_path / "preview").exists()


def test_selects_latest_checksum_strictly_before_failure_clock(tmp_path: Path) -> None:
    checked = struct.pack("<II", 2, 10) + bytes(360)
    body = checked + _action(10) + struct.pack("<II", 2, 10) + checked + struct.pack("<II", 6, 30)
    source = _file(tmp_path, body)
    ordinal, source_pin = preview.checkpoint_before(source, 30)
    assert ordinal == 1
    result = preview.prepare_preview(
        source, tmp_path / "preview", through_sync=ordinal, expected_source=source_pin
    )
    assert result["preview_end_ms"] == 10
    assert preview.checkpoint_before(source, 31)[0] == 3
    with pytest.raises(preview.PreviewError, match="No recorded checksum"):
        preview.checkpoint_before(source, 10)


def test_selection_and_preparation_bind_same_source(tmp_path: Path) -> None:
    source = _file(tmp_path, struct.pack("<II", 2, 20) + bytes(360) + struct.pack("<II", 6, 20))
    ordinal, source_pin = preview.checkpoint_before(source, 21)
    with source.open("ab") as stream:
        stream.write(b"changed")
    with pytest.raises(preview.PreviewError, match="after locating"):
        preview.prepare_preview(
            source, tmp_path / "preview", through_sync=ordinal, expected_source=source_pin
        )
    assert not (tmp_path / "preview").exists()


def test_source_change_during_copy_does_not_publish_replay(tmp_path: Path, monkeypatch) -> None:
    source = _file(tmp_path, struct.pack("<II", 2, 20) + bytes(360) + struct.pack("<II", 6, 20))
    original_pin = preview.pin
    calls = 0

    def change_before_copy_check(path):
        nonlocal calls
        if path == source.resolve():
            calls += 1
            if calls == 3:
                with source.open("ab") as stream:
                    stream.write(b"changed")
        return original_pin(path)

    monkeypatch.setattr(preview, "pin", change_before_copy_check)
    out = tmp_path / "preview"
    with pytest.raises(preview.PreviewError, match="changed during preview copying"):
        preview.prepare_preview(source, out, through_sync=1)
    assert not (out / "INCOMPLETE-checksum-prefix.aoe2record").exists()
    assert not (out / "preview.json").exists()


def test_prepare_preview_before_uses_last_checksum_before_the_stop(tmp_path: Path) -> None:
    source = _file(
        tmp_path,
        struct.pack("<II", 2, 10)
        + struct.pack("<II", 2, 15)
        + bytes(360)  # checksum sync at clock 25
        + struct.pack("<II", 2, 20)
        + struct.pack("<II", 2, 5)
        + bytes(360)  # checksum sync at clock 50, at or after the stop
        + struct.pack("<II", 6, 60),
    )
    result = preview.prepare_preview_before(source, tmp_path / "before", 40)
    assert result["original_syncs"] == 2 and result["after_last_checksum_ms"] == 15
    assert result["synthetic_eof"] and not result["original_full_match_completed"]
    with pytest.raises(preview.PreviewError):
        preview.prepare_preview_before(source, tmp_path / "none", 1)
