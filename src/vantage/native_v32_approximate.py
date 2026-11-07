"""Derive the explicit approximate-checksum variant of the pinned V32 host.

Original build-54800 multiplayer checksums can diverge from the recovered engine (see
docs/design/native-replay-quickstart.md). The strict host stops there with native error 207.
This variant is the opt-in alternative: it sets the game's own ignore-checksum byte, lets the
simulation run to the end of the recording, and is labelled approximate everywhere it is used.

The strict host template is never edited; the variant is derived from it by exact, counted text
substitutions so a drifted template fails loudly instead of silently producing a different host.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import struct
from pathlib import Path
from typing import Any

IGNORE_BYTE = "base[0x42d96b0]"
# The image's static constructor FUN_140297fa0 initializes this critical section, but the strict
# host's table of reproduced constructors omits it. Entering the all-zero section blocks forever
# (first reached at 22:14 of the public 1v1), so the variant initializes it before stepping.
MISSING_CRITICAL_SECTION_RVA = "0x4c84708"

_LOOP = (
    "    while (advanced_time < INPUT_FINAL_CLOCK_MS && completed_updates < INPUT_UPDATE_CAP) {\n"
    "        DWORD delta = 0xffffffff;"
)
_START = (
    f"    {IGNORE_BYTE} = 1; // approximate-checksum mode\n"
    "    InitializeCriticalSection(reinterpret_cast<CRITICAL_SECTION*>("
    f"base + {MISSING_CRITICAL_SECTION_RVA}));\n"
)


def _replace(text: str, old: str, new: str, count: int) -> str:
    if text.count(old) != count:
        raise ValueError(f"host template drifted: {old[:60]!r} x{text.count(old)} != {count}")
    return text.replace(old, new)


def approximate_host(template: str) -> str:
    """Return the approximate-checksum host derived from the strict one."""
    text = _replace(template, _LOOP, _START + _LOOP, 1)
    # The strict terminal contract demands the ignore byte be 0; here it must be exactly 1.
    text = _replace(text, f"{IGNORE_BYTE}!=0", f"{IGNORE_BYTE}!=1", 2)
    closed = '\\"native_replay_closed\\":true,\\"checksum_ignore_global\\":'
    text = _replace(text, closed + "0,", closed + "1,", 1)
    status = '\\"checksum_ignore_global\\":%s,\\"host_native_status_write\\"'
    return _replace(text, status % 0, status % 1, 1)


def _pin(path: Path) -> dict[str, Any]:
    data = path.read_bytes()
    return {"path": str(path), "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def build_profiles(
    source_profile: Path, runtime_profile: Path, out_dir: Path
) -> dict[str, Path | str]:
    """Write the variant host and re-pinned profiles; return their paths and sha256 values."""
    out_dir.mkdir(parents=True, exist_ok=True)
    source = json.loads(source_profile.read_bytes())
    host_path = out_dir / "host-approximate-checksums.cpp.in"
    host_path.write_text(approximate_host(Path(source["host"]["path"]).read_text()))
    source["host"] = _pin(host_path)
    source["approximate_checksums"] = True
    source_path = out_dir / "source-profile.json"
    source_path.write_text(json.dumps(source, indent=1) + "\n")
    runtime = json.loads(runtime_profile.read_bytes())
    runtime["staging_profile"] = _pin(source_path)
    runtime_path = out_dir / "runtime-profile.json"
    runtime_path.write_text(json.dumps(runtime, indent=1) + "\n")
    return {
        "source_profile": source_path,
        "source_sha256": hashlib.sha256(source_path.read_bytes()).hexdigest(),
        "runtime_profile": runtime_path,
        "runtime_sha256": hashlib.sha256(runtime_path.read_bytes()).hexdigest(),
    }


#: The portable label: it lives in the recording header, so it survives copy and rename.
FIDELITY: dict[str, Any] = {
    "simulation": "approximate",
    "checksum_policy": "ignored",
    "interventions": ["game_checksum_ignore_byte"],
    "host_repairs": ["critical_section_0x4c84708"],
    "note": "Replay checksums were ignored; state after the first divergence may differ "
    "from the original game.",
}
_MAGIC = b"VREC\x01"
_CHUNK = 1024 * 1024


def is_approximate(header: dict[str, Any]) -> bool:
    fidelity = header.get("fidelity")
    return isinstance(fidelity, dict) and fidelity.get("simulation") == "approximate"


def stamp_recording(source: Path, output: Path) -> dict[str, Any]:
    """Copy a verified VREC with FIDELITY in its header and byte-identical frames."""
    temporary = output.with_name(output.name + ".tmp")
    try:
        with gzip.open(source, "rb") as reader:
            if reader.read(len(_MAGIC)) != _MAGIC:
                raise ValueError("not a .vrec recording")
            size = struct.unpack("<I", reader.read(4))[0]
            header = json.loads(reader.read(size))
            stamped = json.dumps({**header, "fidelity": FIDELITY}).encode()
            # mtime=0 keeps repeated stamps of the same input byte-identical.
            with (
                open(temporary, "wb") as raw,
                gzip.GzipFile(fileobj=raw, mode="wb", compresslevel=5, mtime=0) as writer,
            ):
                writer.write(_MAGIC + struct.pack("<I", len(stamped)) + stamped)
                while chunk := reader.read(_CHUNK):
                    writer.write(chunk)
        os.replace(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)
    return _pin(output)
