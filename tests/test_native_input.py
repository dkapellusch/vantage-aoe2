"""Input facts use complete native save fixtures and independent body framing."""

from __future__ import annotations

import hashlib
import struct
import zlib
from dataclasses import FrozenInstanceError, replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from replay_fixtures import complete_world_case
from test_replay_object_order import _object, _saved

from vantage import native_input
from vantage.native_input import NativeInputError, describe_native_input
from vantage.replay_binary import SaveReader
from vantage.replay_file_header import read_file_header

META = struct.pack("<8I", 5, 500, 0, 1, 1, 0, 0, 0)
BODY = (
    struct.pack("<4I", 2, 0, 2, 28)
    + struct.pack("<II", 1, 5)
    + b"\x0b\x02\x01\0\0"
    + struct.pack("<I", 28)
    + struct.pack("<4I", 2, 27, 6, 55)
)


def _replay(tmp_path: Path, raw: bytes, *, body: bytes = BODY, trailer: bytes = b"end") -> Path:
    compressor = zlib.compressobj(level=1, wbits=-15)
    compressed = compressor.compress(raw) + compressor.flush()
    path = tmp_path / "input.aoe2record"
    path.write_bytes(
        struct.pack("<II", len(compressed) + 8, 0) + compressed + META + body + trailer
    )
    return path


@pytest.mark.parametrize("sample,players", [("3p", 4), ("6p", 7)])
def test_descriptor_uses_each_real_save_and_variable_body_boundaries(
    tmp_path: Path, sample: str, players: int
) -> None:
    raw, expected = complete_world_case(sample)
    path = _replay(tmp_path, raw, trailer=bytes(58 if sample == "3p" else 80))
    plan = describe_native_input(path)
    assert plan.recording_sha256 == hashlib.sha256(path.read_bytes()).hexdigest()
    assert plan.inflated_save_sha256 == expected["inflated_sha256"]
    assert plan.inflated_save_bytes == expected["inflated_bytes"]
    assert plan.world_player_count == players
    assert plan.world_handoff_offset == (2321 if sample == "3p" else 2482)
    assert plan.options_offset == 24 and plan.options_end_offset == plan.world_handoff_offset - 20
    assert plan.body_offset == plan.first_operation_offset == plan.compressed_header_end + 32
    assert plan.postgame_offset == plan.body_offset + len(BODY) - 8
    assert plan.final_clock_ms == 55
    assert plan.postgame_marker_end + plan.postgame_remaining_bytes == plan.recording_bytes
    assert plan.postgame_remaining_bytes == (62 if sample == "3p" else 84)
    assert dict(plan.operation_counts) == {"action": 1, "postgame": 1, "sync": 3}
    assert dict(plan.sync_deltas_ms) == {0: 1, 27: 1, 28: 1}
    assert plan.body_metadata_words == (5, 500, 0, 1, 1, 0, 0, 0)
    assert plan.body_clock_origin_ms == plan.initial_clock_ms == 0
    assert plan.map_tile_bytes == 10 * plan.map_width * plan.map_height
    assert plan.checksum_sync_count == 0
    assert not plan.native_compatibility_verified
    assert len(plan.wire_lists) == len(plan.runtime_lists) == players * 3
    assert {p.world_player_index for p in plan.player_slots if p.humanity in (2, 4)} == set(
        range(1, players)
    )
    first = plan.wire_lists[0].entities[0]
    assert first.object_id == first.owner == first.saved_owner == 0
    assert (first.master_id, first.family) == (1362 if sample == "3p" else 1359, 10)
    assert first.hp_bits == 0
    with pytest.raises(FrozenInstanceError):
        plan.final_clock_ms = 1


def test_partial_or_corrupt_body_never_yields_a_completed_descriptor(tmp_path: Path) -> None:
    # No inflated save is needed to establish missing/corrupt terminal input.
    path = _replay(tmp_path, b"not a saved world", body=struct.pack("<II", 2, 28), trailer=b"")
    with pytest.raises(NativeInputError) as error:
        describe_native_input(path)
    assert error.value.code == "PARTIAL_INPUT"
    path = _replay(tmp_path, b"not a saved world", body=struct.pack("<I", 97), trailer=b"")
    with pytest.raises(NativeInputError) as error:
        describe_native_input(path)
    assert error.value.code == "INVALID_BODY" and error.value.offset_space == "file"


def test_chapters_and_resource_limits_fail_before_save_decoding(tmp_path: Path) -> None:
    path = _replay(tmp_path, b"not a saved world")
    wire = path.read_bytes()
    path.write_bytes(wire[:4] + struct.pack("<I", len(wire) - 8) + wire[8:])
    with pytest.raises(NativeInputError) as error:
        describe_native_input(path)
    assert error.value.code == "UNSUPPORTED_CHAPTER" and error.value.offset == 4
    path.write_bytes(wire)
    with pytest.raises(NativeInputError) as error:
        describe_native_input(path, max_recording_bytes=1)
    assert error.value.code == "INPUT_LIMIT"
    with pytest.raises(NativeInputError) as error:
        describe_native_input(path, max_operations=1)
    assert error.value.code == "INPUT_LIMIT"


@pytest.mark.parametrize(
    "field,value,code",
    [
        ("dlc_options.dataset", 2, "UNSUPPORTED_MODE"),
        ("mGameMode", 3, "UNSUPPORTED_MODE"),
        ("mModdedDatasetWorkshopId", 123, "UNSUPPORTED_DATASET"),
    ],
)
def test_known_unproven_mode_and_dataset_selectors_are_explicit_errors(
    tmp_path: Path, field: str, value: int, code: str
) -> None:
    raw, _ = complete_world_case("3p")
    header = read_file_header(SaveReader(raw))
    span = header.options.fields[field]
    changed = raw[: span.offset] + value.to_bytes(len(span.raw), "little") + raw[span.end_offset :]
    with pytest.raises(NativeInputError) as error:
        describe_native_input(_replay(tmp_path, changed))
    assert error.value.code == code


def test_changed_input_cannot_publish_a_descriptor(tmp_path: Path, monkeypatch) -> None:
    raw, _ = complete_world_case("3p")
    path = _replay(tmp_path, raw)
    loader = native_input.load_replay_world

    def mutate_after_load(*args, **kwargs):
        saved = loader(*args, **kwargs)
        with path.open("r+b") as stream:
            stream.seek(-1, 2)
            stream.write(b"!")
        return saved

    monkeypatch.setattr(native_input, "load_replay_world", mutate_after_load)
    with pytest.raises(NativeInputError) as error:
        describe_native_input(path)
    assert error.value.code == "INPUT_CHANGED"


def test_unsupported_save_version_reports_inflated_offset(tmp_path: Path) -> None:
    raw, _ = complete_world_case("3p")
    changed = raw[:12] + struct.pack("<I", 0x123456) + raw[16:]
    with pytest.raises(NativeInputError) as error:
        describe_native_input(_replay(tmp_path, changed))
    assert error.value.code == "UNSUPPORTED_SAVE_PROFILE"
    assert error.value.offset_space == "inflated_save" and error.value.offset == 12


def test_resumed_body_and_backwards_postgame_are_rejected(tmp_path: Path) -> None:
    resumed = struct.pack("<II", 2, 28) + struct.pack("<II", 6, 100028)
    path = _replay(tmp_path, b"not a save", body=resumed, trailer=b"")
    with pytest.raises(NativeInputError) as error:
        describe_native_input(path)
    assert error.value.code == "UNSUPPORTED_RESUME"
    backwards = struct.pack("<II", 2, 28) + struct.pack("<II", 1, 5)
    backwards += b"\x0b\x02\x01\0\0" + struct.pack("<3I", 28, 6, 1)
    path = _replay(tmp_path, b"not a save", body=backwards, trailer=b"")
    with pytest.raises(NativeInputError) as error:
        describe_native_input(path)
    assert error.value.code == "INVALID_BODY"


def test_bootstrap_sync_boundaries_keep_native_delta_cursor_separate_from_checksum(
    tmp_path: Path,
) -> None:
    raw, _ = complete_world_case("3p")
    checksum = bytes(4) + b"c" * 356
    body = BODY[:8] + checksum + BODY[8:]
    plan = describe_native_input(_replay(tmp_path, raw, body=body))
    first, second, third = plan.bootstrap_syncs
    assert first.offset == plan.body_offset and first.delta_ms == first.time_ms == 0
    assert first.cursor_after_delta == first.checksum_offset == plan.body_offset + 8
    assert first.payload_bytes == 364
    assert second.offset == first.checksum_offset + 360
    assert second.delta_ms == second.time_ms == 28 and second.checksum_offset is None
    assert third.time_ms == 55 and third.delta_ms == 27
    assert plan.checksum_sync_count == 1


def test_wire_lists_and_effective_runtime_lists_remain_distinct() -> None:
    first = _object(2)
    moved = _object(0xFFFFFFFF, (2, 1, 0, 1))  # Override cancels sleeping.
    sleeper = _object(0, (2, 1, 0, 0))
    duplicate = replace(first, raw=first.raw[:10] + struct.pack("<I", 0x42F60000) + first.raw[14:])
    lists = _saved((first, sleeper), (moved, duplicate), ())
    saved = SimpleNamespace(
        prefix=SimpleNamespace(
            world=SimpleNamespace(
                players=(SimpleNamespace(header=SimpleNamespace(player_id=0), object_lists=lists),)
            )
        )
    )
    wire = native_input._lists(saved, runtime=False)
    runtime = native_input._lists(saved, runtime=True)
    assert [[e.object_id for e in group.entities] for group in wire] == [
        [2, 0],
        [0xFFFFFFFF, 2],
        [],
    ]
    assert [[e.object_id for e in group.entities] for group in runtime] == [
        [0xFFFFFFFF, 2],
        [0],
        [],
    ]
    assert runtime[0].entities[1].hp_bits == wire[0].entities[0].hp_bits
    assert wire[1].entities[1].hp_bits == 0x42F60000
