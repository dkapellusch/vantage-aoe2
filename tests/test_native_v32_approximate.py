from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from vantage import native_sdk_admission
from vantage.frames import Frame, RecordingWriter, read_frames, read_header
from vantage.native_v32_approximate import (
    FIDELITY,
    approximate_host,
    build_profiles,
    is_approximate,
    stamp_recording,
)
from vantage.native_v32_pipeline import approximate_rerun_argv

_TEMPLATE = (
    "void run() {\n"
    "    while (advanced_time < INPUT_FINAL_CLOCK_MS && completed_updates < INPUT_UPDATE_CAP) {\n"
    "        DWORD delta = 0xffffffff;\n"
    "        if (base[0x42d96b0]!=0) a; if (base[0x42d96b0]!=0) b;\n"
    '        x = "\\"native_replay_closed\\":true,\\"checksum_ignore_global\\":0,";\n'
    '        y = "\\"checksum_ignore_global\\":0,\\"host_native_status_write\\"";\n'
    "    }\n"
    "}\n"
)


def test_approximate_host_sets_ignore_byte_and_relaxes_the_terminal_contract() -> None:
    host = approximate_host(_TEMPLATE)
    assert host.index("base[0x42d96b0] = 1;") < host.index("while (advanced_time")
    init = "InitializeCriticalSection(reinterpret_cast<CRITICAL_SECTION*>(base + 0x4c84708));"
    assert host.index(init) < host.index("while (advanced_time")
    assert "watchdog" not in host
    assert host.count("base[0x42d96b0]!=1") == 2 and "base[0x42d96b0]!=0" not in host
    assert host.count('checksum_ignore_global\\":1,') == 2


def test_approximate_host_rejects_a_drifted_template() -> None:
    with pytest.raises(ValueError, match="drifted"):
        approximate_host(_TEMPLATE.replace("base[0x42d96b0]!=0", "base[0x42d96b0]!=2", 1))


def test_build_profiles_repins_host_source_and_runtime(tmp_path: Path) -> None:
    host = tmp_path / "host.cpp.in"
    host.write_text(_TEMPLATE)
    pin = {
        "path": str(host),
        "bytes": host.stat().st_size,
        "sha256": hashlib.sha256(host.read_bytes()).hexdigest(),
    }
    source = tmp_path / "source.json"
    source.write_text(json.dumps({"host": pin}))
    runtime = tmp_path / "runtime.json"
    runtime.write_text(json.dumps({"staging_profile": {"path": str(source)}, "kind": "k"}))
    built = build_profiles(source, runtime, tmp_path / "out")
    new_source = json.loads(Path(built["source_profile"]).read_bytes())
    assert new_source["approximate_checksums"] is True
    new_host = Path(new_source["host"]["path"])
    assert new_host.read_text() == approximate_host(_TEMPLATE)
    assert new_source["host"]["sha256"] == hashlib.sha256(new_host.read_bytes()).hexdigest()
    new_runtime = json.loads(Path(built["runtime_profile"]).read_bytes())
    staged = new_runtime["staging_profile"]
    assert staged["sha256"] == built["source_sha256"]
    assert (
        hashlib.sha256(Path(built["runtime_profile"]).read_bytes()).hexdigest()
        == (built["runtime_sha256"])
    )
    assert host.read_text() == _TEMPLATE  # the strict template is never edited


def test_approximate_rerun_argv_keeps_the_original_replay_and_drops_fallback_flags() -> None:
    argv = [
        "--replay",
        "/r/a.aoe2record",
        "--job",
        "/j/one",
        "--approximate-on-checksum-failure",
        "--preview-on-checksum-failure",
        "--runtime-timeout",
        "9",
    ]
    out = approximate_rerun_argv(argv, job=Path("/j/one-approximate"))
    assert out == [
        "--runtime-timeout",
        "9",
        "--replay",
        "/r/a.aoe2record",
        "--job",
        "/j/one-approximate",
        "--approximate-checksums",
    ]


def test_admission_expects_ignore_zero_unless_explicitly_approximate(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    seen: list[int] = []

    def check(_capture: object, _receipt: object, _descriptor: object, *, expected_ignore: int):
        seen.append(expected_ignore)
        return {}

    monkeypatch.setattr(native_sdk_admission, "_positive_terminal_evidence", check)
    capture, receipt = tmp_path / "capture", tmp_path / "receipt"
    capture.write_bytes(b"c")
    receipt.write_bytes(b"r")
    descriptor = {"recording_sha256": "x"}
    strict = native_sdk_admission.positive_terminal_evidence(capture, receipt, descriptor)
    approximate = native_sdk_admission.positive_terminal_evidence(
        capture, receipt, descriptor, approximate_checksums=True
    )
    assert seen == [0, 1]
    assert "approximate_checksums" not in strict
    assert approximate["approximate_checksums"] is True
    assert descriptor == {"recording_sha256": "x"}  # descriptor identity stays untouched


def test_stamp_labels_the_header_keeps_frames_and_survives_a_rename(tmp_path: Path) -> None:
    source = tmp_path / "recording.vrec"
    with RecordingWriter(source, {"title": "match", "end_ms": 5}) as writer:
        writer.write(Frame(time=5, patch=b"state", reverse=b"more"))
    stamped = tmp_path / "stamped.vrec"
    stamp_recording(source, stamped)
    renamed = tmp_path / "copied-elsewhere.vrec"
    renamed.write_bytes(stamped.read_bytes())
    header = read_header(renamed)
    assert is_approximate(header) and header["fidelity"] == FIDELITY
    assert header["title"] == "match" and header["end_ms"] == 5
    assert list(read_frames(renamed)) == list(read_frames(source))
    assert not is_approximate(read_header(source))
    first = stamped.read_bytes()
    stamp_recording(source, stamped)
    assert stamped.read_bytes() == first
    assert not list(tmp_path.glob("*.tmp"))
