"""V32 input staging is input-bound and never claims a completed conversion."""

from __future__ import annotations

import hashlib
import json
import struct
from pathlib import Path

import pytest
from replay_fixtures import complete_world_case
from test_native_input import BODY, _replay

from vantage import native_v32_input
from vantage.native_input import NativeInputError

EXTRA_SYNC_BODY = BODY[:-8] + struct.pack("<4I", 2, 13, 6, 68)


@pytest.fixture
def config_template(tmp_path: Path) -> Path:
    path = tmp_path / "template.h"
    path.write_text('static constexpr const char* PREPARED_SAVED_SHA256 = "' + "0" * 64 + '";\n')
    return path


def test_stages_actual_saved_world_and_refuses_to_replace_output(
    tmp_path: Path, config_template: Path
) -> None:
    raw, _ = complete_world_case("3p")
    replay = _replay(tmp_path, raw, body=EXTRA_SYNC_BODY)
    out = tmp_path / "bundle"
    result = native_v32_input.prepare_v32_input(replay, out, config_template=config_template)
    descriptor = json.loads((out / "descriptor.json").read_text())
    assert (out / "input-save.inflated.bin").read_bytes() == raw
    assert descriptor["recording_sha256"] == hashlib.sha256(replay.read_bytes()).hexdigest()
    assert descriptor["inflated_save_sha256"] in (out / "prepared_config.h").read_text()
    header = (out / "native_input_profile.h").read_text()
    assert "#define INPUT_FIRST_SYNC_DELTA 0\n" in header
    assert (
        f'#define INPUT_DESCRIPTOR_IDENTITY_SHA256 "{result["descriptor_identity_sha256"]}"'
        in header
    )
    assert not result["native_compatibility_verified"]
    before = {p.name: p.read_bytes() for p in out.iterdir()}
    with pytest.raises(FileExistsError):
        native_v32_input.prepare_v32_input(replay, out, config_template=config_template)
    assert {p.name: p.read_bytes() for p in out.iterdir()} == before


def test_positive_first_sync_is_retained(tmp_path: Path, config_template: Path) -> None:
    raw, _ = complete_world_case("3p")
    body = (
        struct.pack("<4I", 2, 13, 2, 28)
        + struct.pack("<II", 1, 5)
        + b"\x0b\x02\x01\0\0"
        + struct.pack("<I", 41)
        + struct.pack("<6I", 2, 27, 2, 13, 6, 81)
    )
    replay = _replay(tmp_path, raw, body=body)
    out = tmp_path / "positive"
    result = native_v32_input.prepare_v32_input(replay, out, config_template=config_template)
    header = (out / "native_input_profile.h").read_text()
    assert result["first_sync_delta_ms"] == 13
    assert "#define INPUT_FIRST_SYNC_DELTA 13\n" in header
    assert "#define INPUT_FIRST_SYNC_TIME 13\n" in header


def test_invalid_cap_and_template_fail_before_creating_output(
    tmp_path: Path, config_template: Path
) -> None:
    raw, _ = complete_world_case("3p")
    replay = _replay(tmp_path, raw, body=EXTRA_SYNC_BODY)
    out = tmp_path / "rejected"
    with pytest.raises(NativeInputError) as error:
        native_v32_input.prepare_v32_input(
            replay, out, config_template=config_template, update_cap=3
        )
    assert error.value.code == "INVALID_UPDATE_CAP" and not out.exists()
    config_template.write_text("no saved world identity")
    with pytest.raises(NativeInputError) as error:
        native_v32_input.prepare_v32_input(replay, out, config_template=config_template)
    assert error.value.code == "INVALID_CONFIG_TEMPLATE" and not out.exists()


def test_recording_changed_after_descriptor_is_rejected(
    tmp_path: Path, config_template: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw, _ = complete_world_case("3p")
    replay = _replay(tmp_path, raw, body=EXTRA_SYNC_BODY)
    out = tmp_path / "changed"
    original = native_v32_input.load_replay_world

    def load_then_mutate(path):
        saved = original(path)
        with path.open("r+b") as stream:
            stream.seek(-1, 2)
            stream.write(b"!")
        return saved

    monkeypatch.setattr(native_v32_input, "load_replay_world", load_then_mutate)
    with pytest.raises(NativeInputError) as error:
        native_v32_input.prepare_v32_input(replay, out, config_template=config_template)
    assert error.value.code == "INPUT_CHANGED" and not out.exists()
