"""Immutable local engine snapshots with isolated legacy-path aliases.

This prototype preserves exact historical validator contracts. It is a content
snapshot plus a private namespace compatibility layer, not a rewritten portable
worker recipe. Host toolchain/runtime dependencies remain explicit.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .native_conversion import pin

if TYPE_CHECKING:
    from typing import TYPE_CHECKING


SCHEMA = "vantage_native_engine_package_v1"


class EnginePackageError(ValueError):
    pass


def _digest(
    value: Any,
) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _package_id(document: dict[Any, Any]) -> str:
    return _digest(
        {
            "profiles": {name: row["sha256"] for name, row in document["profiles"].items()},
            "payloads": sorted({(row["blob"], row["bytes"]) for row in document["mappings"]}),
            "mapping_contract": [
                (row["logical_path"], row["sha256"]) for row in document["mappings"]
            ],
            "host_files": document["host_files"],
        }
    )


def _pins(value: Any) -> Any:
    if isinstance(value, dict):
        if {"path", "bytes", "sha256"} <= value.keys():
            yield {key: value[key] for key in ("path", "bytes", "sha256")}
        for item in value.values():
            yield from _pins(item)
    elif isinstance(value, list):
        for item in value:
            yield from _pins(item)


def export_engine_package(
    source_profile: Path,
    runtime_profile: Path,
    encoder_config: Path,
    destination: Path,
    *,
    replays: tuple[Path, ...] = (),
    repository: Path | None = None,
    disk_floor_bytes: int = 5 << 30,
) -> dict[Any, Any]:
    repository = (repository or Path(__file__).resolve().parents[2]).resolve(strict=True)
    profiles = {
        name: Path(path).resolve(strict=True)
        for name, path in (
            ("source", source_profile),
            ("runtime", runtime_profile),
            ("encoder", encoder_config),
        )
    }
    documents = {name: json.loads(path.read_bytes()) for name, path in profiles.items()}
    parent_path = Path(documents["encoder"]["parent_profile"]["path"])
    parent = json.loads(parent_path.read_bytes())
    overlays = {row["target"]: row["source"] for row in documents["encoder"]["overlays"]}
    desired: dict[str, dict[Any, Any]] = {}
    for document in (*documents.values(), parent):
        for row in _pins(document):
            key = row["path"]
            expected = overlays.get(key, row)
            if key in desired and (desired[key]["bytes"], desired[key]["sha256"]) != (
                expected["bytes"],
                expected["sha256"],
            ):
                raise EnginePackageError(f"Conflicting source pin: {key}")
            desired[key] = dict(expected, logical_path=key)
    discovered_inputs = []
    from .native_engine_manifest import inspect_engine_profiles

    inventory = inspect_engine_profiles(
        profiles["source"], profiles["runtime"], profiles["encoder"]
    )
    for candidate in inventory["files"]:
        key = candidate["path"]
        if key not in desired and candidate["status"] in {"verified", "observed_unpinned"}:
            row = {name: candidate[name] for name in ("path", "bytes", "sha256")}
            discovered_inputs.append(dict(row, role="static_dependency_candidate"))
            desired[key] = dict(row, logical_path=key)
    image_parent = (
        Path(documents["runtime"]["assets"]["image"]["path"]).parent
        if "assets" in documents["runtime"]
        else None
    )
    if image_parent is not None:
        for path in sorted(image_parent.rglob("*")):
            if path.is_file():
                row = pin(path)
                if row["path"] not in desired:
                    discovered_inputs.append(dict(row, role="adjacent_image_support_candidate"))
                    desired[row["path"]] = dict(row, logical_path=row["path"])
    for path in profiles.values():
        desired[str(path)] = dict(pin(path), logical_path=str(path))
    for path in replays:
        row = pin(Path(path))
        desired[row["path"]] = dict(row, logical_path=row["path"])
    # Capture maintained Python/browser source, then restore historical codec
    # overlays over it. No user files are changed.
    for base in (repository / "src" / "vantage", repository / "tools"):
        for path in sorted(base.rglob("*")):
            if (
                path.is_file()
                and "__pycache__" not in path.parts
                and path.suffix in {".py", ".js", ".html", ".css", ".json"}
            ):
                key = str(path.resolve())
                if key not in desired:
                    desired[key] = dict(pin(path), logical_path=key)
    destination = destination.absolute()
    if destination.exists():
        raise EnginePackageError("Package destination already exists")
    destination.parent.mkdir(parents=True, exist_ok=True)
    expected_bytes = sum(row["bytes"] for row in desired.values())
    if shutil.disk_usage(destination.parent).free - expected_bytes < disk_floor_bytes:
        raise EnginePackageError("Insufficient space for package plus disk reserve")
    destination.mkdir(mode=0o700)
    blobs = destination / "blobs"
    blobs.mkdir()
    mappings, host = [], []
    for logical, row in sorted(desired.items()):
        actual = pin(Path(row["path"]))
        if (actual["bytes"], actual["sha256"]) != (row["bytes"], row["sha256"]):
            raise EnginePackageError(f"Pinned input differs: {logical}")
        if (
            logical.startswith(("/usr/", "/bin/", "/lib/", "/lib64/"))
            or logical == documents["encoder"]["python_target"]["path"]
        ):
            host.append(dict(actual, role="verified_host_toolchain"))
            continue
        target = blobs / row["sha256"]
        if not target.exists():
            with Path(row["path"]).open("rb") as source, target.open("xb") as output:
                shutil.copyfileobj(source, output, length=1 << 20)
            target.chmod(
                stat.S_IRUSR | stat.S_IXUSR if os.access(row["path"], os.X_OK) else stat.S_IRUSR
            )
        copied = pin(target)
        if (copied["bytes"], copied["sha256"]) != (row["bytes"], row["sha256"]):
            raise EnginePackageError(f"Source mutated while copying: {logical}")
        if pin(Path(row["path"])) != actual:
            raise EnginePackageError(f"Source changed while copying: {logical}")
        mappings.append(
            {
                "logical_path": logical,
                "blob": "blobs/" + row["sha256"],
                "bytes": row["bytes"],
                "sha256": row["sha256"],
            }
        )
    mask_roots = [str(repository), "/mnt/nvme/vantage-native-research", "/mnt/nvme/SteamLibrary"]
    content = {
        "schema": SCHEMA,
        "profiles": {name: pin(path) for name, path in profiles.items()},
        "mappings": mappings,
        "host_files": host,
        "host_directories": [str(repository / ".venv")],
        "masked_roots": mask_roots,
        "repository_alias": str(repository),
        "namespace_strategy": "private legacy logical aliases backed exclusively by content-addressed package blobs",
        "runtime_closure_proven": False,
        "discovered_inputs": discovered_inputs,
        "static_inventory_summary": inventory["summary"],
        "limitations": [
            "Host Python environment, compiler support files and system libraries remain external.",
            "Legacy profile paths are preserved inside a private mount namespace.",
            "Runtime closure requires successful masked conversion plus access tracing.",
        ],
    }
    content["package_content_id"] = _package_id(content)
    manifest_path = destination / "package.json"
    manifest_path.write_text(json.dumps(content, indent=2) + "\n")
    manifest_path.chmod(stat.S_IRUSR)
    return content


def verify_engine_package(package: Path) -> dict[Any, Any]:
    package = package.resolve(strict=True)
    document: dict[Any, Any] = json.loads((package / "package.json").read_bytes())
    if document.get("schema") != SCHEMA:
        raise EnginePackageError("Unsupported engine package")
    if document.get("package_content_id") != _package_id(document):
        raise EnginePackageError("Package manifest content identity differs")
    if len({row["logical_path"] for row in document["mappings"]}) != len(document["mappings"]):
        raise EnginePackageError("Duplicate logical package aliases")
    for row in document["mappings"]:
        relative = Path(row["blob"])
        if relative.is_absolute() or relative.parts != ("blobs", row["sha256"]):
            raise EnginePackageError("Invalid content-addressed blob path")
        target = package / relative
        if target.is_symlink() or target.resolve() != target:
            raise EnginePackageError("Symlink package blob rejected")
        actual = pin(target)
        if (actual["bytes"], actual["sha256"]) != (row["bytes"], row["sha256"]):
            raise EnginePackageError(f"Package blob differs: {row['logical_path']}")
    for row in document["host_files"]:
        actual = pin(Path(row["path"]))
        if (actual["bytes"], actual["sha256"]) != (row["bytes"], row["sha256"]):
            raise EnginePackageError(f"Host dependency differs: {row['path']}")
    return document


def package_command(
    package: Path, argv: list[str], *, writable_roots: tuple[Path, ...] = ()
) -> tuple[list[str], dict[Any, Any]]:
    package = package.resolve(strict=True)
    document = verify_engine_package(package)
    command = [
        "/usr/bin/bwrap",
        "--die-with-parent",
        "--unshare-net",
        "--ro-bind",
        "/",
        "/",
        "--proc",
        "/proc",
        "--dev",
        "/dev",
    ]
    for root in document["masked_roots"]:
        command += ["--tmpfs", root]
    # Bind sources are opened in bwrap's original namespace; old research roots
    # are never restored as directory mounts.
    for root in document["host_directories"]:
        if not Path(root).is_dir():
            raise EnginePackageError(f"Host Python environment missing: {root}")
        command += ["--ro-bind", root, root]
    suppressed_host_aliases = []
    for row in document["mappings"]:
        target = row["logical_path"]
        if any(Path(target).is_relative_to(Path(root)) for root in document["host_directories"]):
            suppressed_host_aliases.append(
                {"path": target, "reason": "provided by explicit host runtime directory"}
            )
            continue
        if not Path(target).is_absolute() or ".." in Path(target).parts:
            raise EnginePackageError("Invalid logical alias path")
        command += ["--ro-bind", str(package / row["blob"]), target]
    for root in writable_roots:
        path = root.resolve(strict=True)
        if not path.is_dir() or any(
            path.is_relative_to(Path(mask)) or Path(mask).is_relative_to(path)
            for mask in document["masked_roots"]
        ):
            raise EnginePackageError("Invalid writable output root")
        command += ["--bind", str(path), str(path)]
    command += [
        "--setenv",
        "PYTHONDONTWRITEBYTECODE",
        "1",
        "--setenv",
        "PYTHONNOUSERSITE",
        "1",
        "--chdir",
        document["repository_alias"],
        "--",
        *argv,
    ]
    receipt = {
        "package_content_id": document["package_content_id"],
        "package_root": str(package),
        "masked_roots": document["masked_roots"],
        "file_alias_count": len(document["mappings"]) - len(suppressed_host_aliases),
        "suppressed_host_aliases": suppressed_host_aliases,
        "host_dependencies": document["host_files"],
        "host_directories": document["host_directories"],
        "command": command,
        "runtime_closure_proven": False,
    }
    return command, receipt


def revalidate_relocated_job(package: Path, job: Path, *, logical_job: Path) -> dict[Any, Any]:
    """Reuse a moved accepted job through its original private logical alias.

    The existing V32 validator rechecks raw capture, original checksums, source
    pins, encoder process and recording bytes. No worker or encoder is launched.
    Compatibility is tied to this package's exact source/runtime/encoder pins.
    """
    import subprocess

    package = package.resolve(strict=True)
    job = job.resolve(strict=True)
    logical_job = logical_job.absolute()
    document = verify_engine_package(package)
    if any(
        logical_job == Path(root) or Path(root).is_relative_to(logical_job)
        for root in document["masked_roots"]
    ):
        raise EnginePackageError("Invalid retained job alias")
    profiles = document["profiles"]
    code = (
        "import json; from pathlib import Path; "
        "from vantage.native_v32_reuse import verified_recording; "
        f"j=Path({str(logical_job)!r}); "
        "r=json.loads((j/'pipeline-result.json').read_bytes()); "
        "out=verified_recording(j,r,"
        f"runtime_profile=Path({profiles['runtime']['path']!r}),"
        f"runtime_profile_sha256={profiles['runtime']['sha256']!r},"
        f"encoder_config=Path({profiles['encoder']['path']!r}),"
        f"encoder_config_sha256={profiles['encoder']['sha256']!r}); "
        "print(json.dumps(out))"
    )
    python = str(Path(document["repository_alias"]) / ".venv/bin/python")
    command, _receipt = package_command(package, [python, "-c", code])
    separator = command.index("--")
    command[separator:separator] = [
        "--tmpfs",
        str(logical_job),
        "--ro-bind",
        str(job),
        str(logical_job),
    ]
    process = subprocess.run(command, capture_output=True, text=True, check=False)
    verify_engine_package(package)
    if process.returncode != 0:
        raise EnginePackageError(f"Retained job rejected: {process.stderr[-6000:]}")
    result = json.loads(process.stdout)
    recording_alias = Path(result["recording"]["path"])
    if not recording_alias.is_relative_to(logical_job):
        raise EnginePackageError("Retained recording escaped job alias")
    physical = job / recording_alias.relative_to(logical_job)
    actual = pin(physical)
    if (actual["bytes"], actual["sha256"]) != (
        result["recording"]["bytes"],
        result["recording"]["sha256"],
    ):
        raise EnginePackageError("Retained recording differs outside namespace")
    return {
        "schema": "vantage_relocated_recording_reuse_v1",
        "package_content_id": document["package_content_id"],
        "logical_job_alias": str(logical_job),
        "physical_job_root": str(job),
        "recording": actual,
        "admission": result,
        "namespace_command": command,
        "worker_launched": False,
        "encoder_launched": False,
        "package_reverified_after_run": True,
    }
