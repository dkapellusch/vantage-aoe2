"""Bounded update acquisition and impact assessment; no engine activation.

Snapshots cover only explicitly selected ordinary files beneath the supplied
root. Content identity and discovery are separate from replay qualification.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import tempfile
import time
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any

from .native_conversion import pin
from .native_engine_manifest import classify_dependency

if TYPE_CHECKING:
    from typing import TYPE_CHECKING


SNAPSHOT_KIND = "vantage_selected_install_snapshot_v1"
ASSESSMENT_KIND = "vantage_native_update_assessment_v1"
ROLES = {
    "presentation",
    "simulation_data",
    "native_code",
    "input_schema",
    "runtime_toolchain",
    "adapter_source",
    "encoder",
    "recipe",
    "verification",
    "unknown",
}
QUALIFICATION_LEVELS = (
    "inventoried",
    "startup_verified",
    "short_replay_verified",
    "complete_corpus_verified",
)


class UpdateAssessmentError(ValueError):
    pass


def _digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def _relative(value: Any) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise UpdateAssessmentError("Selected paths must be nonempty relative POSIX paths")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in ("", ".", "..") for part in value.split("/")):
        raise UpdateAssessmentError("Selected path escapes its supplied root or is noncanonical")
    return value


def _safe_path(root: Path, relative: str) -> Path:
    current = root
    for component in PurePosixPath(_relative(relative)).parts:
        current = current / component
        if current.is_symlink():
            raise UpdateAssessmentError(f"Selected input uses a symlink: {current}")
    if not current.is_relative_to(root):
        raise UpdateAssessmentError("Selected input is outside supplied root")
    return current


def _state(info: os.stat_result) -> tuple[Any, ...]:
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _open_selected(root: Path, relative: str) -> int:
    parts = PurePosixPath(_relative(relative)).parts
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    directory = os.open(root, flags | os.O_DIRECTORY)
    try:
        for component in parts[:-1]:
            child = os.open(component, flags | os.O_DIRECTORY, dir_fd=directory)
            os.close(directory)
            directory = child
        return os.open(parts[-1], flags, dir_fd=directory)
    finally:
        os.close(directory)


def _read_selected(
    root: Path,
    relative: str,
    destination: Any = None,
    *,
    max_bytes: int | None = None,
) -> tuple[dict[Any, Any], tuple[Any, ...]]:
    _safe_path(root, relative)  # validates the relative path before opening it
    fd = _open_selected(root, relative)
    with os.fdopen(fd, "rb") as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode):
            raise UpdateAssessmentError(f"Selected input is not an ordinary file: {relative}")
        if max_bytes is not None and before.st_size > max_bytes:
            raise UpdateAssessmentError("Selected inputs exceed max_total_bytes")
        digest = hashlib.sha256()
        size = 0
        while block := stream.read(1024 * 1024):
            digest.update(block)
            size += len(block)
            if destination is not None:
                destination.write(block)
        after = os.fstat(stream.fileno())
        if _state(before) != _state(after) or size != before.st_size:
            raise UpdateAssessmentError(f"Selected input mutated during acquisition: {relative}")
    # Recheck the path binding as well as the held descriptor.
    if _state(_safe_path(root, relative).stat()) != _state(before):
        raise UpdateAssessmentError(f"Selected path was replaced during acquisition: {relative}")
    return {"bytes": size, "sha256": digest.hexdigest()}, _state(before)


def _roles(path: str, declared: list[Any] | None) -> list[str]:
    if declared is None:
        role = classify_dependency(path)
        role = {"native_image_or_derivation": "native_code", "unclassified": "unknown"}.get(
            role, role
        )
        return [role]
    if (
        not isinstance(declared, list)
        or not declared
        or len(set(declared)) != len(declared)
        or any(role not in ROLES for role in declared)
    ):
        raise UpdateAssessmentError("Selected roles must be distinct known role names")
    return sorted(declared)


def _content_rows(rows: list[dict[Any, Any]]) -> list[dict[Any, Any]]:
    return sorted(
        ({key: row[key] for key in ("name", "roles", "bytes", "sha256")} for row in rows),
        key=lambda row: row["name"],
    )


def snapshot_installation(
    root: Path,
    selection: dict[Any, Any],
    *,
    blob_store: Path,
    max_files: int = 10000,
    max_total_bytes: int = 16 << 30,
) -> dict[Any, Any]:
    """Hash before and after acquisition, with immutable, deduplicated blob copies."""
    if max_files <= 0 or max_total_bytes <= 0:
        raise UpdateAssessmentError("Acquisition bounds must be positive")
    root = root.resolve(strict=True)
    if not root.is_dir():
        raise UpdateAssessmentError("Snapshot root must be a directory")
    chosen = selection.get("files")
    if not isinstance(chosen, list) or not chosen or len(chosen) > max_files:
        raise UpdateAssessmentError("Explicit selected files are required within max_files")
    rows: list[dict[str, Any]] = []
    paths, names = set(), set()
    for selected in chosen:
        if not isinstance(selected, dict):
            raise UpdateAssessmentError("Each selected file must be an object")
        relative = _relative(selected.get("path"))
        name = _relative(selected.get("name", relative))
        if relative in paths or name in names:
            raise UpdateAssessmentError("Duplicate selected path or logical name")
        paths.add(relative)
        names.add(name)
        rows.append(
            {
                "path": relative,
                "name": name,
                "roles": _roles(name, selected.get("roles")),
                "expected": selected.get("expected"),
            }
        )
    started = time.monotonic()
    observed = {}
    total = 0
    for row in rows:
        value, state = _read_selected(root, row["path"], max_bytes=max_total_bytes - total)
        total += value["bytes"]
        if total > max_total_bytes:
            raise UpdateAssessmentError("Selected inputs exceed max_total_bytes")
        if row["expected"] is not None and row["expected"] != value:
            raise UpdateAssessmentError(f"Selected input differs from supplied pin: {row['path']}")
        observed[row["path"]] = (value, state)
        row.update(value)
        row.pop("expected")
    blob_store.mkdir(parents=True, exist_ok=True)
    blob_store = blob_store.resolve(strict=True)
    new_bytes, reused_bytes = 0, 0
    for row in rows:
        blob = blob_store / row["sha256"]
        if blob.exists() or blob.is_symlink():
            if blob.is_symlink() or not blob.is_file() or pin(blob)["sha256"] != row["sha256"]:
                raise UpdateAssessmentError(f"Existing content blob is corrupt: {blob.name}")
            reused_bytes += row["bytes"]
        else:
            descriptor, temporary_name = tempfile.mkstemp(prefix=".acquire-", dir=blob_store)
            temporary = Path(temporary_name)
            try:
                with os.fdopen(descriptor, "wb") as output:
                    acquired, state = _read_selected(root, row["path"], output)
                    output.flush()
                    os.fsync(output.fileno())
                if (acquired, state) != observed[row["path"]]:
                    raise UpdateAssessmentError(
                        f"Selected input changed between acquisition passes: {row['path']}"
                    )
                temporary.chmod(0o444)
                try:
                    os.link(temporary, blob)
                    new_bytes += row["bytes"]
                except FileExistsError:
                    if (
                        blob.is_symlink()
                        or not blob.is_file()
                        or pin(blob)["sha256"] != row["sha256"]
                    ):
                        raise UpdateAssessmentError("Concurrent content blob differs") from None
                    reused_bytes += row["bytes"]
            finally:
                temporary.unlink(missing_ok=True)
        row["blob"] = {"path": str(blob), "bytes": row["bytes"], "sha256": row["sha256"]}
    for row in rows:
        if _read_selected(root, row["path"]) != observed[row["path"]]:
            raise UpdateAssessmentError(
                f"Selected installation changed during snapshot: {row['path']}"
            )
    for row in rows:
        blob_value, _ = _read_selected(blob_store, row["sha256"], max_bytes=row["bytes"])
        if blob_value != {key: row[key] for key in ("bytes", "sha256")}:
            raise UpdateAssessmentError("Acquired content blob changed during snapshot")
    content = _content_rows(rows)
    return {
        "kind": SNAPSHOT_KIND,
        "snapshot_id": _digest(content),
        "root": str(root),
        "files": rows,
        "selected_scope_only": True,
        "full_dependency_closure_claimed": False,
        "acquisition": {
            "all_selected_inputs_hashed_before_and_after": True,
            "new_blob_bytes": new_bytes,
            "reused_blob_bytes": reused_bytes,
            "seconds": time.monotonic() - started,
        },
        "declared_metadata": selection.get("declared_metadata", {}),
        "native_execution_performed": False,
        "engine_activated": False,
    }


def validate_snapshot(doc: dict[Any, Any]) -> dict[Any, Any]:
    if (
        not isinstance(doc, dict)
        or doc.get("kind") != SNAPSHOT_KIND
        or not isinstance(doc.get("files"), list)
        or not doc["files"]
    ):
        raise UpdateAssessmentError("Unsupported or empty selected-file snapshot")
    names = set()
    for row in doc["files"]:
        name = _relative(row["name"])
        _relative(row["path"])
        if name in names:
            raise UpdateAssessmentError("Duplicate snapshot logical name")
        names.add(name)
        _roles(name, row["roles"])
        if (
            type(row["bytes"]) is not int
            or row["bytes"] < 0
            or not isinstance(row["sha256"], str)
            or re.fullmatch(r"[0-9a-f]{64}", row["sha256"]) is None
        ):
            raise UpdateAssessmentError("Malformed snapshot file content identity")
    if doc.get("snapshot_id") != _digest(_content_rows(doc["files"])):
        raise UpdateAssessmentError("Snapshot content identity differs")
    return doc


def assess_update(
    previous: dict[Any, Any],
    candidate: dict[Any, Any],
    *,
    result_records: list[dict[Any, Any]] | None = None,
) -> dict[Any, Any]:
    """Compare exact selected bytes; unattested reports cannot promote a candidate."""
    validate_snapshot(previous)
    validate_snapshot(candidate)
    left, right = ({row["name"]: row for row in doc["files"]} for doc in (previous, candidate))
    changes = []
    impacts = set()
    for name in sorted(left.keys() | right.keys()):
        before, after = left.get(name), right.get(name)
        if (
            before
            and after
            and all(before[key] == after[key] for key in ("bytes", "sha256", "roles"))
        ):
            continue
        roles = sorted(set((before or {}).get("roles", []) + (after or {}).get("roles", [])))
        impacts.update(roles)
        change = (
            "modified"
            if before and after
            else "not_in_previous_selection"
            if after
            else "not_in_candidate_selection"
        )
        changes.append(
            {
                "name": name,
                "change": change,
                "roles": roles,
                "previous": {k: before[k] for k in ("bytes", "sha256")} if before else None,
                "candidate": {k: after[k] for k in ("bytes", "sha256")} if after else None,
            }
        )
    # The current registry admits experimental engines only. A supported attestation
    # must bind snapshot -> engine -> replay scope -> original receipts and references.
    # Until that validator exists, even a truthful ready-result is provenance only.
    evidence = []
    for record in result_records or []:
        if not isinstance(record, dict):
            raise UpdateAssessmentError("Result records must be JSON objects")
        evidence.append(
            {
                "record_identity": _digest(record),
                "claimed_kind": record.get("kind", record.get("schema")),
                "status": "not_authoritative_for_candidate",
                "reason": "No snapshot-bound engine/corpus qualification attestation validator exists",
            }
        )
    return {
        "kind": ASSESSMENT_KIND,
        "previous_snapshot_id": previous["snapshot_id"],
        "candidate_snapshot_id": candidate["snapshot_id"],
        "assessment": "no_work" if not changes else "unqualified_candidate",
        "changed_files": changes,
        "impact_classes": sorted(impacts),
        "discovery_work_required": bool(changes),
        "replay_qualification_required": bool(changes),
        "qualification": {
            "level": "unqualified",
            "inventory_status": "selected_files_inventoried",
            "available_levels": list(QUALIFICATION_LEVELS),
            "supported": False,
            "candidate_qualified": False,
            "missing_gates": list(QUALIFICATION_LEVELS),
            "result_records": evidence,
        },
        "old_package_preserved": True,
        "activation_performed": False,
        "rollback": {
            "previous_snapshot_id": previous["snapshot_id"],
            "registry_selection_changed": False,
            "action": "Keep the previously selected engine; this command changes no registry",
        },
        "scope": [
            "Only explicitly selected file identities were compared.",
            "A selection-only addition or removal does not prove a file was added to or deleted from the installation.",
            "Discovery candidates and ready-result booleans are not replay qualification.",
            "Second real build qualification and automatic binding/qualification orchestration remain incomplete.",
        ],
    }


def _write(path: Path, result: dict[Any, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x") as stream:
        json.dump(result, stream, indent=2, allow_nan=False)
        stream.write("\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    snapshot = commands.add_parser(
        "snapshot", help="Acquire only selected files into immutable content blobs"
    )
    snapshot.add_argument("--root", type=Path, required=True)
    snapshot.add_argument("--selection", type=Path, required=True)
    snapshot.add_argument("--blob-store", type=Path, required=True)
    snapshot.add_argument("--output", type=Path, required=True)
    assess = commands.add_parser(
        "assess", help="Compare two exact selected-file manifests without activation"
    )
    assess.add_argument("--previous", type=Path, required=True)
    assess.add_argument("--candidate", type=Path, required=True)
    assess.add_argument("--result-record", type=Path, action="append", default=[])
    assess.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "snapshot":
            selection_pin = pin(args.selection.resolve(strict=True))
            result = snapshot_installation(
                args.root, json.loads(args.selection.read_bytes()), blob_store=args.blob_store
            )
            if pin(args.selection.resolve()) != selection_pin:
                raise UpdateAssessmentError("Selection manifest changed during acquisition")
            result["selection_manifest"] = selection_pin
        else:
            inputs = [args.previous, args.candidate, *args.result_record]
            before = [pin(path.resolve(strict=True)) for path in inputs]
            previous, candidate, *records = [json.loads(path.read_bytes()) for path in inputs]
            result = assess_update(previous, candidate, result_records=records)
            if before != [pin(path.resolve()) for path in inputs]:
                raise UpdateAssessmentError("Assessment input manifest changed")
            result["input_manifests"] = before
        result["assessment_tool"] = pin(Path(__file__).resolve())
        _write(args.output, result)
    except (OSError, ValueError, KeyError, TypeError) as error:
        result = {
            "kind": "vantage_native_update_rejected_v1",
            "error": f"{type(error).__name__}: {error}",
            "activation_performed": False,
            "old_package_preserved": True,
        }
        _write(args.output, result)
        print(json.dumps(result))
        raise SystemExit(1) from None
    print(
        json.dumps(
            {
                "output": str(args.output),
                "snapshot_id": result.get("snapshot_id"),
                "assessment": result.get("assessment"),
                "activation_performed": False,
            }
        )
    )


if __name__ == "__main__":
    main()
