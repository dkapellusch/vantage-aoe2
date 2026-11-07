"""Pinned V32 source staging never treats compilation as replay success."""

from __future__ import annotations

import hashlib
import json
import struct
import subprocess
from pathlib import Path

import pytest
from replay_fixtures import complete_world_case
from test_native_input import BODY, _replay

from vantage import native_v32_prepare
from vantage.native_conversion import pin
from vantage.native_v32_prepare import V32PreparationError, prepare_v32_worker


@pytest.fixture
def staging_profile(tmp_path: Path) -> tuple[Path, str, Path]:
    compiler = Path("/usr/bin/x86_64-w64-mingw32-g++")
    if not compiler.is_file():
        pytest.skip("V32 staging requires the Windows cross compiler")
    source = tmp_path / "template"
    source.mkdir()
    header = source / "sample.h"
    header.write_text("#pragma once\n")
    raw = source / "resources/_common/dat/empires2_x2_p1.dat"
    raw.parent.mkdir(parents=True)
    raw.write_bytes(b"")
    host = tmp_path / "host.cpp.in"
    host.write_text(
        '#include <windows.h>\n#include "sample.h"\n#include "native_input_profile.h"\n'
        "int wmain() { return INPUT_FIRST_SYNC_DELTA == 0 ? 0 : 1; }\n"
    )
    config = tmp_path / "config.h"
    config.write_text('static constexpr const char* PREPARED_SAVED_SHA256 = "' + "0" * 64 + '";\n')
    rows = [{"relative": str(path.relative_to(source)), "pin": pin(path)} for path in (header, raw)]
    profile = tmp_path / "profile.json"
    profile.write_text(
        json.dumps(
            {
                "kind": "vantage_experimental_v32_source",
                "version": 1,
                "source_root": str(source),
                "host": pin(host),
                "config_template": pin(config),
                "compiler": pin(compiler),
                "sources": rows,
                "raw_dat_placeholder": str(raw.relative_to(source)),
            }
        )
    )
    return profile, hashlib.sha256(profile.read_bytes()).hexdigest(), header


def test_stages_and_compiles_without_claiming_native_execution(
    tmp_path: Path, staging_profile: tuple[Path, str, Path]
) -> None:
    profile, digest, _ = staging_profile
    raw, _ = complete_world_case("3p")
    body = BODY[:-8] + struct.pack("<4I", 2, 13, 6, 68)
    replay = _replay(tmp_path, raw, body=body)
    out = tmp_path / "job"
    result = prepare_v32_worker(replay, out, profile=profile, profile_sha256=digest)
    assert result["worker"] == pin(out / "source/vantage-native-input-derived.exe")
    assert result["host"]["sha256"] == pin(tmp_path / "host.cpp.in")["sha256"]
    assert (out / "source/input-save.inflated.bin").read_bytes() == raw
    assert not result["native_execution"] and not result["native_compatibility_verified"]
    assert json.loads((out / "stage.json").read_text()) == result
    with pytest.raises(V32PreparationError, match="already exists"):
        prepare_v32_worker(replay, out, profile=profile, profile_sha256=digest)


def test_profile_and_sources_must_match_before_output(
    tmp_path: Path, staging_profile: tuple[Path, str, Path]
) -> None:
    profile, digest, header = staging_profile
    replay = tmp_path / "input.aoe2record"
    replay.write_bytes(b"not read before profile validation")
    with pytest.raises(V32PreparationError, match="profile hash"):
        prepare_v32_worker(
            replay, tmp_path / "bad-profile", profile=profile, profile_sha256="0" * 64
        )
    header.write_text("changed")
    with pytest.raises(V32PreparationError, match="Pinned source changed"):
        prepare_v32_worker(replay, tmp_path / "bad-source", profile=profile, profile_sha256=digest)
    assert not (tmp_path / "bad-profile").exists() and not (tmp_path / "bad-source").exists()


def test_timed_out_compiler_stops_only_its_owned_group_and_publishes_no_receipt(
    tmp_path: Path, staging_profile: tuple[Path, str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    profile, digest, _ = staging_profile
    raw, _ = complete_world_case("3p")
    replay = _replay(tmp_path, raw, body=BODY[:-8] + struct.pack("<4I", 2, 13, 6, 68))
    out = tmp_path / "timed-out"
    signals = []

    class TimedOutChild:
        pid = 424242
        returncode = -15

        def __init__(self, command, **kwargs):
            assert kwargs["start_new_session"] is True
            self.command = command
            self.calls = 0

        def communicate(self, timeout=None):
            self.calls += 1
            if self.calls == 1:
                raise subprocess.TimeoutExpired(self.command, timeout)
            return b"", b"terminated"

        def poll(self):
            return self.returncode

    monkeypatch.setattr(native_v32_prepare.subprocess, "Popen", TimedOutChild)
    monkeypatch.setattr(
        native_v32_prepare.os, "killpg", lambda pid, sig: signals.append((pid, sig))
    )
    with pytest.raises(V32PreparationError, match="Compiler timed out"):
        prepare_v32_worker(replay, out, profile=profile, profile_sha256=digest, compile_timeout=1)
    assert len(signals) == 1 and signals[0][0] == 424242
    assert (out / "compile.stderr").read_bytes() == b"terminated"
    assert not (out / "stage.json").exists()
