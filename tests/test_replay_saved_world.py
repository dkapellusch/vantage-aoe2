"""Portable full native headers and bounded direct file imports without DE."""

from __future__ import annotations

import hashlib
import struct
import zlib
from pathlib import Path

import pytest
from replay_fixtures import complete_world_case

from vantage.replay_binary import SaveDecodeError, SaveReader
from vantage.replay_saved_world import load_replay_world, read_saved_world
from vantage.replay_stream import ReplayStreamError


def _file(path: Path, data: bytes, *, chapter: int = 0, suffix: bytes = b"") -> Path:
    compressor = zlib.compressobj(level=1, wbits=-15)
    compressed = compressor.compress(data) + compressor.flush() + suffix
    path.write_bytes(struct.pack("<II", len(compressed) + 8, chapter) + compressed + bytes(32))
    return path


@pytest.mark.parametrize("sample", ["3p", "6p"])
def test_full_native_world_reads_to_exact_original_eof_and_reconstructs_all_bytes(
    sample: str,
) -> None:
    raw, expected = complete_world_case(sample)
    assert hashlib.sha256(raw).hexdigest() == expected["inflated_sha256"]
    reader = SaveReader(b"before" + raw + b"after", 6)
    saved = read_saved_world(reader)
    assert saved.offset == 6 and saved.end_offset == reader.pos == len(raw) + 6
    assert reader.data[reader.pos :] == b"after"
    assert saved.raw == raw == saved.prefix.raw + saved.scenario.raw + saved.tail.raw
    assert saved.prefix.end_offset == saved.scenario.offset
    assert saved.scenario.end_offset == saved.tail.offset
    assert saved.tail.end_offset - 6 == expected["inflated_bytes"]
    assert saved.scenario.base.max_players == saved.scenario.extension.max_players == 16
    assert saved.tail.base.saved_player_count == len(saved.prefix.world.players) - 1
    assert saved.tail.outer.xs1 is not None
    assert len(saved.tail.outer.xs1.raw) == 351061


def test_truncation_at_the_final_world_field_rolls_back_the_entire_import() -> None:
    raw, _ = complete_world_case("3p")
    reader = SaveReader(b"before" + raw[:-1], 6)
    with pytest.raises(SaveDecodeError):
        read_saved_world(reader)
    assert reader.pos == 6


def test_file_import_decodes_native_envelope_and_full_world(tmp_path: Path) -> None:
    raw, _ = complete_world_case("3p")
    path = _file(tmp_path / "native.aoe2record", raw)
    saved = load_replay_world(path)
    assert saved.offset == 0 and saved.end_offset == len(raw)
    assert saved.raw == raw and saved.prefix.header.build == 54800


def test_file_import_rejects_unexplained_inflated_trailing_bytes(tmp_path: Path) -> None:
    raw, _ = complete_world_case("3p")
    path = _file(tmp_path / "trailing.aoe2record", raw + b"unexpected")
    with pytest.raises(SaveDecodeError, match="unconsumed bytes") as error:
        load_replay_world(path)
    assert error.value.offset == len(raw)


@pytest.mark.parametrize("kind", ["invalid", "truncated", "trailing", "over_limit", "input_limit"])
def test_invalid_or_oversized_deflate_is_rejected_before_world_parsing(
    tmp_path: Path, kind: str
) -> None:
    path = _file(tmp_path / "bad.aoe2record", b"a" * 10000)
    if kind == "invalid":
        wire = path.read_bytes()
        path.write_bytes(wire[:8] + b"\xff" * (len(wire) - 40) + wire[-32:])
    elif kind == "truncated":
        wire = path.read_bytes()
        header_end = int.from_bytes(wire[:4], "little")
        path.write_bytes(
            struct.pack("<II", header_end - 1, 0) + wire[8 : header_end - 1] + bytes(32)
        )
    elif kind == "trailing":
        _file(path, b"a", suffix=b"unused")
    kwargs = {"max_inflated_bytes": 10} if kind == "over_limit" else {}
    if kind == "input_limit":
        kwargs = {"max_compressed_bytes": 1}
    with pytest.raises(ReplayStreamError):
        load_replay_world(path, **kwargs)


@pytest.mark.parametrize("wire", [b"", b"1234567", struct.pack("<II", 8, 0) + bytes(32)])
def test_invalid_file_envelopes_report_file_offset(tmp_path: Path, wire: bytes) -> None:
    path = tmp_path / "bad.aoe2record"
    path.write_bytes(wire)
    with pytest.raises(ReplayStreamError) as error:
        load_replay_world(path)
    assert error.value.offset == 0


def test_invalid_chapter_pointer_is_rejected(tmp_path: Path) -> None:
    path = _file(tmp_path / "bad.aoe2record", b"a", chapter=9)
    with pytest.raises(ReplayStreamError, match="chapter pointer") as error:
        load_replay_world(path)
    assert error.value.offset == 4


@pytest.mark.parametrize("kwargs", [{"max_inflated_bytes": 0}, {"max_compressed_bytes": -1}])
def test_byte_limits_must_be_positive_before_opening_file(tmp_path: Path, kwargs) -> None:
    with pytest.raises(ValueError, match="limits must be positive"):
        load_replay_world(tmp_path / "absent", **kwargs)
