"""Import and launch a pinned experimental engine without a research checkout.

Only the three reviewed runtime-bootstrap modules execute on the host. The
worker, compiler, Wine and engine execute in the captured empty-root namespace.
This controller is also copied into each imported bundle and uses only stdlib.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
import types
import uuid
from pathlib import Path
from typing import Any

MODULES = ("native_conversion", "native_engine_package", "native_engine_runtime")
FILES = ("controller.py", "bootstrap/__init__.py", *(f"bootstrap/{m}.py" for m in MODULES))


def require(condition: Any, message: str) -> None:
    if not condition:
        raise ValueError(message)


def pin(path: Path) -> dict[str, Any]:
    path = path.resolve(strict=True)
    before = path.stat()
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    after = path.stat()
    require(
        (before.st_ino, before.st_size, before.st_mtime_ns)
        == (after.st_ino, after.st_size, after.st_mtime_ns),
        "Bundle input changed during reading",
    )
    return {"path": str(path), "bytes": after.st_size, "sha256": digest.hexdigest()}


def checked(row: dict[str, Any]) -> Path:
    require(
        type(row) is dict
        and set(row) == {"path", "bytes", "sha256"}
        and type(row["path"]) is str
        and Path(row["path"]).is_absolute()
        and type(row["bytes"]) is int
        and row["bytes"] >= 0
        and type(row["sha256"]) is str
        and re.fullmatch("[0-9a-f]{64}", row["sha256"]),
        "Invalid bundle input identity",
    )
    path = Path(row["path"])
    require(pin(path) == row, "Bundle input changed: " + str(path))
    return path


def read_json(path: Path, limit: int = 32 << 20) -> Any:
    def unique(rows: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in rows:
            require(key not in result, "Duplicate bundle metadata key")
            result[key] = value
        return result

    def invalid(_value: str) -> Any:
        raise ValueError("Nonfinite bundle metadata")

    with path.open("rb") as stream:
        raw = stream.read(limit + 1)
    require(len(raw) <= limit, "Bundle metadata exceeds its size bound")
    return json.loads(raw, object_pairs_hook=unique, parse_constant=invalid)


def write_new(path: Path, value: Any) -> None:
    with path.open("x") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")


def schedule() -> None:
    require(hasattr(os, "sched_getaffinity"), "Captured engines require Linux")
    os.sched_setaffinity(0, {min(os.sched_getaffinity(0))})
    priority = os.getpriority(os.PRIO_PROCESS, 0)
    if priority < 19:
        os.nice(19 - priority)


def relative_file(root: Path, name: str) -> Path:
    relative = Path(name)
    require(
        not relative.is_absolute() and ".." not in relative.parts and str(relative) == name,
        "Invalid bundle-relative path",
    )
    path = root / relative
    require(
        path.resolve(strict=True) == path and path.is_file() and not path.is_symlink(),
        "Bundle file has symlink ancestry or is missing",
    )
    return path


def runtime_module(root: Path, expected_sources: dict[str, dict[str, Any]]) -> Any:
    """Execute the authenticated bytes directly; no import cache or file search."""
    name = "_vantage_owned_engine_bootstrap"
    require(name not in sys.modules, "Runtime bootstrap already imported")
    expected_names = {"__init__.py", *(module + ".py" for module in MODULES)}
    require(
        {path.name for path in (root / "bootstrap").iterdir()} == expected_names,
        "Unexpected bootstrap file, package, extension or bytecode cache",
    )
    require(
        relative_file(root, "bootstrap/__init__.py").read_bytes() == b"",
        "Nonempty bootstrap initializer",
    )
    require(set(expected_sources) == set(MODULES), "Bootstrap source identities missing")
    compiled = {}
    for module in MODULES:
        path = relative_file(root, "bootstrap/" + module + ".py")
        with path.open("rb") as stream:
            raw = stream.read((2 << 20) + 1)
        expected = expected_sources[module]
        require(
            len(raw) <= 2 << 20
            and len(raw) == expected["bytes"]
            and hashlib.sha256(raw).hexdigest() == expected["sha256"],
            "Bootstrap source bytes differ: " + module,
        )
        compiled[module] = compile(raw, str(path), "exec", dont_inherit=True)
    package = types.ModuleType(name)
    package.__path__ = []  # Relative imports resolve only preloaded module identities.
    package.__package__ = name
    package.__spec__ = importlib.util.spec_from_loader(name, loader=None, is_package=True)
    sys.modules[name] = package
    try:
        for module in MODULES:
            full_name = name + "." + module
            loaded = types.ModuleType(full_name)
            loaded.__package__ = name
            loaded.__file__ = str(root / "bootstrap" / (module + ".py"))
            loaded.__spec__ = importlib.util.spec_from_loader(full_name, loader=None)
            sys.modules[full_name] = loaded
            setattr(package, module, loaded)
            exec(compiled[module], loaded.__dict__)
    except BaseException:
        for key in list(sys.modules):
            if key == name or key.startswith(name + "."):
                del sys.modules[key]
        raise
    return sys.modules[name + ".native_engine_runtime"]


def copy_pinned(source: Path, target: Path, expected: dict[str, Any], *, link: bool) -> None:
    require(source.resolve(strict=True) == source and not source.is_symlink(), "Symlink source")
    target.parent.mkdir(parents=True, exist_ok=True)
    require(not target.exists() and not target.is_symlink(), "Import target already exists")
    before = source.stat()
    require(before.st_size == expected["bytes"], "Import source size differs")
    if link:
        os.link(source, target)
    else:
        with source.open("rb") as old, target.open("xb") as new:
            shutil.copyfileobj(old, new, length=1 << 20)
        target.chmod(0o500)
    actual = pin(target)
    after = source.stat()
    require(
        (before.st_ino, before.st_size, before.st_mtime_ns)
        == (after.st_ino, after.st_size, after.st_mtime_ns)
        and all(actual[key] == expected[key] for key in ("bytes", "sha256")),
        "Import source bytes changed or differ",
    )


def import_bundle(args: argparse.Namespace) -> dict[str, Any]:
    schedule()
    ticket_pin = pin(args.bootstrap_sources)
    require(ticket_pin["sha256"] == args.bootstrap_sha256, "Bootstrap source ticket changed")
    ticket = read_json(args.bootstrap_sources)
    require(
        ticket.get("kind") == "vantage_native_bootstrap_sources"
        and type(ticket.get("version")) is int
        and ticket["version"] == 1
        and type(ticket.get("modules")) is dict
        and set(ticket["modules"]) == set(MODULES),
        "Unsupported bootstrap source ticket",
    )
    sources = {name: checked(row) for name, row in ticket["modules"].items()}
    package = args.package.resolve(strict=True)
    capsule = args.capsule.resolve(strict=True)
    pkg_pin, cap_pin, registry_pin = (
        pin(package / "package.json"),
        pin(capsule / "runtime.json"),
        pin(args.registry),
    )
    require(registry_pin["sha256"] == args.registry_sha256, "Engine registry changed")
    pkg, cap, registry = (
        read_json(package / "package.json"),
        read_json(capsule / "runtime.json"),
        read_json(args.registry),
    )
    require(
        pkg.get("package_content_id") == args.package_id
        and cap.get("capsule_content_id") == args.capsule_id
        and cap.get("package_content_id") == args.package_id,
        "Selected engine and captured runtime identities differ",
    )
    require(
        registry.get("kind") == "vantage_native_engine_registry"
        and registry.get("version") == 1
        and type(registry.get("engines")) is list
        and registry["engines"]
        and all(engine.get("profiles") == pkg.get("profiles") for engine in registry["engines"]),
        "Registry does not describe this package",
    )
    destination = args.destination.absolute()
    require(not destination.exists(), "Keep prior imports; destination already exists")
    destination.parent.mkdir(parents=True, exist_ok=True)
    require(destination.parent.resolve(strict=True) == destination.parent, "Symlink destination")
    require(shutil.disk_usage(destination.parent).free >= 5 << 30, "Five GiB disk reserve required")
    destination.mkdir(mode=0o700)
    bootstrap = destination / "bootstrap"
    bootstrap.mkdir()
    (bootstrap / "__init__.py").write_bytes(b"")
    for name, source in sources.items():
        copy_pinned(source, bootstrap / (name + ".py"), ticket["modules"][name], link=False)
    controller = Path(__file__).resolve(strict=True)
    copy_pinned(controller, destination / "controller.py", pin(controller), link=False)
    copied: set[Path] = set()
    for source_root, document, rows, manifest_name, expected in (
        (package, pkg, pkg["mappings"], "package.json", pkg_pin),
        (capsule, cap, cap["files"], "runtime.json", cap_pin),
    ):
        target_root = destination / ("package" if manifest_name == "package.json" else "capsule")
        for row in rows:
            require(row["blob"] == "blobs/" + row["sha256"], "Invalid content blob alias")
            target = target_root / row["blob"]
            if target not in copied:
                if not args.link:
                    require(
                        shutil.disk_usage(destination).free - row["bytes"] >= 5 << 30,
                        "Import would violate disk reserve",
                    )
                copy_pinned(source_root / row["blob"], target, row, link=args.link)
                copied.add(target)
        if manifest_name == "runtime.json":
            library_identities: dict[str, tuple[Any, Any]] = {}
            for row in document["bootstrap"]["libraries"]:
                require(Path(row["name"]).name == row["name"], "Invalid bootstrap alias")
                identity = (row["bytes"], row["sha256"])
                if row["name"] in library_identities:
                    require(
                        library_identities[row["name"]] == identity,
                        "Conflicting bootstrap library identities",
                    )
                    continue
                library_identities[row["name"]] = identity
                copy_pinned(
                    source_root / "bootstrap" / row["name"],
                    target_root / "bootstrap" / row["name"],
                    row,
                    link=args.link,
                )
        copy_pinned(source_root / manifest_name, target_root / manifest_name, expected, link=False)
    copy_pinned(Path(registry_pin["path"]), destination / "registry.json", registry_pin, link=False)
    runtime = runtime_module(destination, ticket["modules"])
    verified = runtime.verify_runtime_capsule(destination / "capsule", destination / "package")
    require(verified["capsule_content_id"] == args.capsule_id, "Imported runtime differs")
    for row in (ticket_pin, pkg_pin, cap_pin, registry_pin, *ticket["modules"].values()):
        checked(row)
    files = {
        name: pin(destination / name)
        for name in (*FILES, "package/package.json", "capsule/runtime.json", "registry.json")
    }
    bundle_identity: dict[str, Any] = {
        "package_content_id": args.package_id,
        "capsule_content_id": args.capsule_id,
        "files": {name: row["sha256"] for name, row in files.items()},
    }
    bundle_id = hashlib.sha256(json.dumps(bundle_identity, sort_keys=True).encode()).hexdigest()
    metadata = {
        "kind": "vantage_native_engine_bundle",
        "version": 1,
        "bundle_id": bundle_id,
        **bundle_identity,
        "files": files,
        "qualification": "experimental",
        "source_ticket": ticket_pin,
        "import_uses_hardlinks": args.link,
    }
    write_new(destination / "bundle.json", metadata)
    inputs = [pin(Path(sys.executable)), pin(destination / "bundle.json"), *files.values()]
    descriptor = {
        "kind": "vantage_native_worker_client",
        "version": 1,
        "command": [
            str(Path(sys.executable).resolve()),
            "-I",
            "-S",
            "-B",
            str(destination / "controller.py"),
            "run",
            "--bundle",
            str(destination),
        ],
        "inputs": inputs,
        "registry": files["registry.json"],
        "runtime_timeout_seconds": 3600,
        "encoder_timeout_seconds": 3600,
        "timeout_seconds": 7500,
    }
    write_new(destination / "client.json", descriptor)
    # Reuse the standalone client's contract validation without importing Forge.
    from vantage.native import NativeWorker

    descriptor_pin = pin(destination / "client.json")
    NativeWorker(destination / "client.json", descriptor_pin["sha256"])
    result = {
        "kind": "vantage_native_engine_bundle_import",
        "version": 1,
        "bundle_id": bundle_id,
        "descriptor": descriptor_pin,
        "package_content_id": args.package_id,
        "capsule_content_id": args.capsule_id,
        "all_declared_import_bytes_verified": True,
        "qualification": "experimental",
        "native_conversion_executed": False,
        "game_api_used": False,
        "maximum_cpus": 1,
        "nice": 19,
        "hardlinks": args.link,
    }
    write_new(destination / "import-receipt.json", result)
    return result


def load_bundle(root: Path) -> tuple[dict[str, Any], Any]:
    metadata = read_json(relative_file(root, "bundle.json"))
    require(
        metadata.get("kind") == "vantage_native_engine_bundle"
        and type(metadata.get("version")) is int
        and metadata["version"] == 1
        and metadata.get("qualification") == "experimental",
        "Unsupported engine bundle",
    )
    expected_names = {*FILES, "package/package.json", "capsule/runtime.json", "registry.json"}
    require(set(metadata["files"]) == expected_names, "Bundle bootstrap file set differs")
    for name, row in metadata["files"].items():
        require(str(relative_file(root, name)) == row["path"], "Bundle root or alias changed")
        checked(row)
    identity = {
        "package_content_id": metadata["package_content_id"],
        "capsule_content_id": metadata["capsule_content_id"],
        "files": {name: row["sha256"] for name, row in metadata["files"].items()},
    }
    require(
        hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
        == metadata["bundle_id"],
        "Bundle content identity differs",
    )
    return metadata, runtime_module(
        root, {module: metadata["files"]["bootstrap/" + module + ".py"] for module in MODULES}
    )


def stage_file(
    source: Path, folder: Path, suffix: str, expected_sha: str | None = None
) -> dict[str, Any]:
    identity = pin(source)
    if expected_sha is not None:
        require(identity["sha256"] == expected_sha, "Request input identity differs")
    folder.mkdir(parents=True, exist_ok=True)
    require(folder.resolve(strict=True) == folder, "Request staging has symlink ancestry")
    target = folder / (identity["sha256"] + suffix)
    if target.exists():
        require(not target.is_symlink(), "Symlink staged input")
        actual = pin(target)
        require(all(actual[k] == identity[k] for k in ("bytes", "sha256")), "Staged input differs")
    else:
        temporary = folder / (uuid.uuid4().hex + ".partial")
        copy_pinned(source.resolve(strict=True), temporary, identity, link=False)
        os.link(temporary, target)
        temporary.unlink()
    checked(identity)
    return pin(target)


def _run_bundle(args: argparse.Namespace) -> int:
    schedule()
    cancelled: int | None = None

    def stop(signum: int, _frame: Any) -> None:
        nonlocal cancelled
        cancelled = signum

    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, stop)
    root = args.bundle.resolve(strict=True)
    metadata, runtime = load_bundle(root)
    require(args.experimental, "Imported engine requires experimental opt-in")
    require(
        0 < args.runtime_timeout <= 86400 and 0 < args.encoder_timeout <= 86400,
        "Invalid time limits",
    )
    cache = args.cache_dir.resolve()
    cache.mkdir(parents=True, exist_ok=True)
    output = args.output.resolve()
    require(
        output.is_relative_to(cache) and not output.exists(),
        "Result must be new and inside the cache",
    )
    require(
        args.registry_sha256 == metadata["files"]["registry.json"]["sha256"],
        "Registry differs from bundle",
    )
    original_replay = pin(args.replay)
    replay = stage_file(args.replay, cache / "requests", ".aoe2record", original_replay["sha256"])
    require(
        all(replay[key] == original_replay[key] for key in ("bytes", "sha256")),
        "Staged replay differs from the original request",
    )
    registry = stage_file(args.registry, cache / "requests", ".registry.json", args.registry_sha256)
    package_doc = read_json(root / "package/package.json")
    require(package_doc["package_content_id"] == metadata["package_content_id"], "Package differs")
    alias = package_doc["repository_alias"]
    command = [
        alias + "/.venv/bin/python",
        alias + "/tools/native_engine_convert.py",
        "--registry",
        registry["path"],
        "--registry-sha256",
        registry["sha256"],
        "--replay",
        replay["path"],
        "--cache-dir",
        str(cache),
        "--output",
        str(output),
        "--experimental",
        "--runtime-timeout",
        str(args.runtime_timeout),
        "--encoder-timeout",
        str(args.encoder_timeout),
    ]
    for cap in args.require_capability:
        command.extend(("--require-capability", cap))
    if args.reuse_job is not None:
        saved = args.reuse_job.resolve(strict=True)
        require(saved.is_relative_to(cache), "Retained job is outside the selected cache")
        command.extend(("--reuse-job", str(saved)))
    started = time.monotonic()
    bootstrap, argv, receipt = runtime.capsule_command(
        root / "capsule", root / "package", command, writable_roots=[cache]
    )
    require(
        receipt["capsule_content_id"] == metadata["capsule_content_id"]
        and receipt["package_content_id"] == metadata["package_content_id"]
        and receipt.get("empty_namespace_root") is True
        and receipt.get("host_root_bound") is False
        and receipt.get("host_directory_binds") == [],
        "Runtime identity or namespace boundary differs",
    )
    record = output.parent / (output.name + ".capsule-receipt.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    require(not record.exists(), "Keep prior capsule receipt")
    if cancelled is not None:
        receipt.update(exit_code=130, cancelled=True, native_launch_occurred=False)
        write_new(record, receipt)
        return 130
    process = subprocess.Popen(
        [*bootstrap, *argv],
        stdin=subprocess.DEVNULL,
        env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"},
    )
    cancel_at = None
    try:
        write_new(
            output.parent / (output.name + ".capsule-start.json"),
            {
                "pid": process.pid,
                "command": [*bootstrap, *argv],
                "bundle_id": metadata["bundle_id"],
                "original_replay": original_replay,
                "staged_replay": replay,
                "staged_registry": registry,
                "maximum_cpus": 1,
                "nice": 19,
            },
        )
        while process.poll() is None:
            if cancelled is not None:
                if cancel_at is None:
                    cancel_at = time.monotonic()
                    process.send_signal(signal.SIGINT)
                elif time.monotonic() - cancel_at >= 2:
                    process.kill()
            time.sleep(0.05)
    finally:
        if process.poll() is None:
            process.kill()
        process.wait()
    receipt.update(
        exit_code=process.returncode,
        cancelled=cancelled is not None,
        seconds=time.monotonic() - started,
        bundle_id=metadata["bundle_id"],
        original_replay=original_replay,
        staged_replay=replay,
        staged_registry=registry,
    )
    if cancelled is not None:
        receipt["postverification_complete"] = False
        write_new(record, receipt)
        return 130
    # Preserve original full postverification; no ready result is exposed by
    # NativeJobs before this controller exits successfully.
    try:
        doc = runtime.verify_runtime_capsule(root / "capsule", root / "package")
        package_root, pkg = runtime._package_document(root / "package")
        spec = runtime._view_spec(root / "capsule", package_root, doc, pkg, [cache])
        receipt["captured_view_reverified_after_run"] = runtime.verify_captured_view(
            receipt["captured_filesystem_view_bind"], spec
        )
        require(
            receipt["captured_view_reverified_after_run"] == receipt["captured_view"],
            "Captured runtime view changed",
        )
        receipt["package_and_capsule_reverified_after_run"] = True
        for row in (original_replay, replay, registry, *metadata["files"].values()):
            checked(row)
    except Exception as error:
        receipt.update(postverification_complete=False, postverification_error=str(error))
        write_new(record, receipt)
        raise
    if cancelled is not None:
        receipt.update(cancelled=True, postverification_complete=False)
        write_new(record, receipt)
        return 130
    receipt["postverification_complete"] = True
    write_new(record, receipt)
    return process.returncode


def run_bundle(args: argparse.Namespace) -> int:
    previous = {sig: signal.getsignal(sig) for sig in (signal.SIGINT, signal.SIGTERM)}
    try:
        return _run_bundle(args)
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    importer = commands.add_parser("import", help="import exact local engine and captured runtime")
    for name in ("package", "capsule", "registry", "bootstrap-sources", "destination"):
        importer.add_argument("--" + name, required=True, type=Path)
    for name in ("package-id", "capsule-id", "registry-sha256", "bootstrap-sha256"):
        importer.add_argument("--" + name, required=True)
    importer.add_argument(
        "--link",
        action="store_true",
        help="explicitly share immutable payload inodes on this filesystem",
    )
    runner = commands.add_parser("run", help="owned worker protocol entrypoint")
    for name in ("bundle", "registry", "replay", "cache-dir", "output"):
        runner.add_argument("--" + name, required=True, type=Path)
    runner.add_argument("--registry-sha256", required=True)
    runner.add_argument("--experimental", action="store_true")
    runner.add_argument("--require-capability", action="append", default=[])
    runner.add_argument("--reuse-job", type=Path)
    runner.add_argument("--runtime-timeout", type=int, default=3600)
    runner.add_argument("--encoder-timeout", type=int, default=3600)
    args = parser.parse_args()
    if args.command == "import":
        print(json.dumps(import_bundle(args), indent=2))
    else:
        raise SystemExit(run_bundle(args))


if __name__ == "__main__":
    main()
