"""Prepare an explicitly incomplete replay prefix ending at a recorded checksum.

The output is an experimental input for the V32 worker. It is not a completed
match or a claim that the selected checksum will pass when simulated.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
from pathlib import Path
from typing import Any

from vantage.native_conversion import pin
from vantage.replay_stream import iter_replay_operations


class PreviewError(ValueError):
    """A safe checksum-bounded preview could not be prepared."""


def checkpoint_before(source: Path, before_ms: int) -> tuple[int, dict[Any, Any]]:
    """Find the latest recorded checksum strictly before a given game clock.

    This examines replay framing only; it does not establish that the checksum
    passes in the simulator.
    """
    if type(before_ms) is not int or before_ms <= 0:
        raise PreviewError("Cutoff clock must be a positive integer in milliseconds")
    source = source.expanduser().resolve(strict=True)
    source_pin = pin(source)
    ordinal = 0
    selected = None
    for operation in iter_replay_operations(source):
        if operation.kind == "chapter":
            raise PreviewError("Saved chapters are not supported for preview input")
        if operation.kind == "sync":
            ordinal += 1
            if operation.time_ms >= before_ms:
                break
            if len(operation.payload) == 364:
                selected = ordinal
    if pin(source) != source_pin:
        raise PreviewError("Source replay changed while locating the checksum")
    if selected is None:
        raise PreviewError("No recorded checksum precedes the requested clock")
    return selected, source_pin


def prepare_preview(
    source: Path,
    output_dir: Path,
    *,
    through_sync: int,
    expected_source: dict[Any, Any] | None = None,
) -> dict[Any, Any]:
    """Copy a source prefix and append a clearly identified, synthetic early EOF.

    The numbered sync must contain a recorded checksum. The last checksum is
    read before that sync's update, so the update's delta is explicitly
    reported as not covered by a subsequent checksum. The native worker must
    still execute the preview and validate all its original checksums.
    """
    if type(through_sync) is not int or through_sync < 1:
        raise PreviewError("Sync ordinal must be a positive integer")
    source = source.expanduser().resolve(strict=True)
    if source.suffix.lower() != ".aoe2record":
        raise PreviewError("Expected an .aoe2record file")
    source_pin = pin(source)
    if expected_source is not None and source_pin != expected_source:
        raise PreviewError("Source replay changed after locating the checksum")
    with source.open("rb") as stream:
        header = stream.read(8)
    if len(header) != 8 or struct.unpack("<II", header)[1] != 0:
        raise PreviewError("Saved chapters are not supported for preview input")

    count = 0
    selected = cutoff = None
    for operation in iter_replay_operations(source):
        if operation.kind == "chapter":
            raise PreviewError("Saved chapters are not supported for preview input")
        if selected is not None and (
            operation.kind in {"sync", "postgame"} or operation.time_ms > selected.time_ms
        ):
            cutoff = operation.offset
            break
        if operation.kind == "sync":
            count += 1
            if count == through_sync:
                selected = operation
                if len(selected.payload) != 364:
                    raise PreviewError("Selected sync does not contain a recorded checksum")
                delta = struct.unpack_from("<I", selected.payload)[0]
                if not 0 < delta <= selected.time_ms:
                    raise PreviewError("Selected checksum has an unsupported clock")
    if selected is None or cutoff is None:
        raise PreviewError("Selected checksum or following replay boundary was not found")
    if pin(source) != source_pin:
        raise PreviewError("Source replay changed during preview preparation")

    output_dir = output_dir.expanduser().resolve()
    output_dir.mkdir(mode=0o700, parents=True, exist_ok=False)
    preview = output_dir / "INCOMPLETE-checksum-prefix.aoe2record"
    pending = output_dir / ".preview.partial"
    digest = hashlib.sha256()
    with source.open("rb") as original, pending.open("xb") as output:
        remaining = cutoff
        while remaining:
            chunk = original.read(min(remaining, 1024 * 1024))
            if not chunk:
                raise PreviewError("Source replay was truncated during copying")
            digest.update(chunk)
            output.write(chunk)
            remaining -= len(chunk)
        output.write(struct.pack("<II", 6, selected.time_ms))
    if pin(source) != source_pin:
        raise PreviewError("Source replay changed during preview copying")
    with pending.open("rb") as check:
        remaining = cutoff
        readback = hashlib.sha256()
        while remaining:
            chunk = check.read(min(remaining, 1024 * 1024))
            if not chunk:
                raise PreviewError("Preview was truncated during verification")
            readback.update(chunk)
            remaining -= len(chunk)
        if readback.digest() != digest.digest() or check.read() != struct.pack(
            "<II", 6, selected.time_ms
        ):
            raise PreviewError("Preview does not match its source prefix and synthetic ending")
    if pin(source) != source_pin:
        raise PreviewError("Source replay changed during preview verification")
    pending.rename(preview)
    preview_pin = pin(preview)
    result = {
        "kind": "incomplete_checksum_prefix",
        "source": source_pin,
        "preview": preview_pin,
        "original_prefix_bytes": cutoff,
        "original_prefix_sha256": digest.hexdigest(),
        "original_syncs": through_sync,
        "last_checksum_offset": selected.offset,
        "last_checksum_state_ms": selected.time_ms - delta,
        "preview_end_ms": selected.time_ms,
        "after_last_checksum_ms": delta,
        "synthetic_eof": True,
        "checksum_verified_by_preparation": False,
        "original_full_match_completed": False,
    }
    with (output_dir / "preview.json").open("x", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2)
        stream.write("\n")
    return result


def prepare_preview_before(source: Path, output_dir: Path, before_ms: int) -> dict[str, Any]:
    """Prepare the preview ending at the last recorded checksum before ``before_ms``.

    Used when a conversion stops at a failing checksum: the prefix up to the
    previous passing checksum is converted instead, and stays labelled incomplete.
    """
    ordinal, source_pin = checkpoint_before(source, before_ms)
    return prepare_preview(source, output_dir, through_sync=ordinal, expected_source=source_pin)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("replay", type=Path)
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--through-sync", type=int, help="one-based recorded sync ordinal")
    selection.add_argument(
        "--before-ms", type=int, help="use the last recorded checksum before this game clock"
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.before_ms is None:
        result = prepare_preview(args.replay, args.output_dir, through_sync=args.through_sync)
    else:
        result = prepare_preview_before(args.replay, args.output_dir, args.before_ms)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
