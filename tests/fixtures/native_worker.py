"""Authored subprocess contract fixture. This is never a native engine."""

import argparse
import gzip
import hashlib
import json
import os
import struct
import sys
import time
from pathlib import Path


def pin(path):
    data = path.read_bytes()
    return {
        "path": str(path.resolve()),
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    }


p = argparse.ArgumentParser()
p.add_argument("--fixture-template", type=Path, required=True)
p.add_argument("--fixture-mode", default="good")
for name in (
    "registry",
    "registry-sha256",
    "replay",
    "cache-dir",
    "output",
    "runtime-timeout",
    "encoder-timeout",
):
    p.add_argument("--" + name, required=True)
p.add_argument("--experimental", action="store_true")
p.add_argument("--require-capability", action="append")
a = p.parse_args()
cache = Path(a.cache_dir)
cache.mkdir(parents=True, exist_ok=True)
(cache / "fixture-resource.json").write_text(
    json.dumps(
        {
            "affinity": sorted(os.sched_getaffinity(0)),
            "nice": os.getpriority(os.PRIO_PROCESS, 0),
            "fixture_not_native": True,
        }
    )
)
if a.fixture_mode == "wait":
    while True:
        time.sleep(0.1)
engine = json.loads(Path(a.registry).read_text())["engines"][0]
replay = pin(Path(a.replay))
identity = {**engine["families"][0], **{k: replay[k] for k in ("bytes", "sha256")}}
if a.fixture_mode == "wrong-replay":
    identity["sha256"] = "0" * 64
if a.fixture_mode == "wrong-family":
    identity["game_mode"] = 99
result = {
    "status": "ready",
    "engine_id": engine["engine_id"],
    "replay": identity,
    "recording": None,
    "conversion_report": None,
    "capabilities": ["world_frames"],
    "message": None,
    "protocol_version": 1,
    "capture_protocol": "v32-streams-1",
}
if a.fixture_mode == "failed":
    result.update(status="failed", message="Authored checksum rejection")
    Path(a.output).write_text(json.dumps(result))
    sys.exit(1)
data = gzip.decompress(a.fixture_template.read_bytes())
length = struct.unpack("<I", data[5:9])[0]
header = json.loads(data[9 : 9 + length])
complete = a.fixture_mode != "eof"
header["recording_end_reason"] = "native_game_end" if complete else "recording_eof"
raw = json.dumps(header).encode()
recording = cache / "fixture-recording.vrec"
recording.write_bytes(
    gzip.compress(data[:5] + struct.pack("<I", len(raw)) + raw + data[9 + length :], mtime=0)
)
if a.fixture_mode == "corrupt-recording":
    recording.write_bytes(b"authored bad recording")
recording_pin = pin(recording)
terminal = {
    "expected_frames": header["expected_frames"],
    "expected_end_ms": header["end_ms"],
    "recording_end_reason": header["recording_end_reason"],
    "game_ended": complete,
    "native_terminal_state": {"checksum_ignore_global": 0},
    "original_terminal_event": {
        "returned_status": 1,
        "world_status": 1,
        "checksum_ignore_global": 0,
        "host_native_status_write": False,
    },
}
if a.fixture_mode == "ignored-checksum":
    terminal["native_terminal_state"]["checksum_ignore_global"] = 1
if a.fixture_mode == "forced-status":
    terminal["original_terminal_event"]["host_native_status_write"] = True
report = {
    "status": "conversion_verified",
    "capture_frames": header["expected_frames"],
    "capture_end_ms": header["end_ms"],
    "game_ended": complete,
    "recording_end_reason": header["recording_end_reason"],
    "recording": recording_pin,
    "all_serialized_Frame_bytes_readback_digest_checked": True,
    "recording_ingestion_complete": True,
    "native_receipt_preserved": {
        "receipt_kind": "ordinary_owned_subprocess",
        "exit_code": 0,
        "timed_out": False,
        "cancelled": False,
        "private_namespace": True,
        "private_xvfb": True,
        "all_input_pins_unchanged": True,
        "runtime_profile": engine["profiles"]["runtime"],
    },
    "terminal_evidence": terminal,
    "authored_fixture_not_native": True,
}
report_path = cache / "fixture-conversion.json"
report_path.write_text(json.dumps(report))
result.update(recording=recording_pin, conversion_report=pin(report_path))
if a.fixture_mode == "wrong-protocol":
    result["protocol_version"] = 99
if a.fixture_mode == "no-report":
    result["conversion_report"] = None
if a.fixture_mode == "wrong-digest":
    result["recording"]["sha256"] = "0" * 64
if a.fixture_mode == "changed-worker":
    Path(__file__).write_text("# authored mutated fixture\n")
Path(a.output).write_text(json.dumps(result))
