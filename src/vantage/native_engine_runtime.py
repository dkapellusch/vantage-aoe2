"""Optional captured host runtime for an engine package in an empty namespace.

Only explicit host trees and successful retained trace paths are imported. ldd
is used exclusively on trusted host ELF files, never on game PE/code. Platform
kernel, user namespaces, proc/dev and the caller-owned output filesystem remain
external. A bounded successful workload is evidence, not universal closure.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any

from .native_conversion import pin
from .native_engine_package import SCHEMA as PACKAGE_SCHEMA
from .native_engine_package import _package_id

if TYPE_CHECKING:
    from pathlib import Path
    from typing import TYPE_CHECKING


SCHEMA = "vantage_native_runtime_capsule_v1"


class RuntimeCapsuleError(ValueError):
    pass


def require(condition: Any, message: str) -> None:
    if not condition:
        raise RuntimeCapsuleError(message)


def logical(path: str) -> str:
    value = str(path)
    p = PurePosixPath(value)
    require(
        p.is_absolute() and ".." not in p.parts and str(p) == value and value != "/",
        f"Invalid runtime logical path: {value}",
    )
    return value


def identity(
    document: Any,
) -> str:
    keys = ("schema", "files", "symlinks", "directories", "bootstrap", "package_content_id")
    raw = json.dumps({k: document[k] for k in keys}, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()


def _resolve(
    document: Any,
    path: str,
) -> str:
    """Resolve captured logical links without consulting the host filesystem."""
    links = {row["path"]: row["target"] for row in document["symlinks"]}
    value = logical(path)
    for _ in range(48):
        parts = PurePosixPath(value).parts
        for index in range(1, len(parts)):
            prefix = str(PurePosixPath(*parts[: index + 1]))
            if prefix in links:
                target = links[prefix]
                joined = (
                    target if target.startswith("/") else str(PurePosixPath(prefix).parent / target)
                )
                value = os.path.normpath(str(PurePosixPath(joined).joinpath(*parts[index + 1 :])))
                break
        else:
            return value
    raise RuntimeCapsuleError("Captured symlink cycle or excessive chain")


def _package_document(
    package: Path,
) -> Any:
    package = Path(package).resolve(strict=True)
    doc = json.loads((package / "package.json").read_bytes())
    require(
        doc.get("schema") == PACKAGE_SCHEMA and doc.get("package_content_id") == _package_id(doc),
        "Engine package identity rejected",
    )
    seen = set()
    for row in doc["mappings"]:
        name = logical(row["logical_path"])
        require(name not in seen, "Duplicate package alias")
        seen.add(name)
        require(row["blob"] == "blobs/" + row["sha256"], "Package blob path rejected")
        target = package / row["blob"]
        require(
            not target.is_symlink() and target.resolve(strict=True) == target,
            "Symlink package blob rejected",
        )
        actual = pin(target)
        require(
            (actual["bytes"], actual["sha256"]) == (row["bytes"], row["sha256"]),
            f"Engine package blob differs: {name}",
        )
    return package, doc


def trace_paths(trace: Path) -> tuple[Any, ...]:
    """Successful absolute-path observations only; failed accesses stay explicit."""
    opener = gzip.open if str(trace).endswith(".gz") else open
    success: set[Any] = set()
    failed: set[Any] = set()
    with opener(trace, "rt", errors="replace") as stream:
        for line in stream:
            if " = " not in line:
                continue
            target = failed if re.search(r" = -1\b", line) else success
            for match in re.finditer(r'"(/(?:[^"\\]|\\.)*)"', line):
                quoted = match.group(1)
                if "..." in quoted or "\\" in quoted or line[match.end() :].startswith("..."):
                    continue
                if quoted != "/":
                    target.add(quoted)
    return sorted(success), sorted(failed)


def export_runtime_capsule(
    package: Path,
    destination: Path,
    *,
    trees: Any = (),
    files: Any = (),
    trace: Any = None,
    trusted_roots: Any = (),
    max_source_bytes: Any = 4 << 30,
    disk_floor_bytes: Any = 5 << 30,
) -> Any:
    package, package_doc = _package_document(package)
    destination = Path(destination).absolute()
    require(not destination.exists(), "Runtime capsule destination exists")
    require(max_source_bytes > 0 and disk_floor_bytes >= 5 << 30, "Invalid resource bounds")
    destination.parent.mkdir(parents=True, exist_ok=True)
    require(
        shutil.disk_usage(destination.parent).free >= disk_floor_bytes, "Disk reserve unavailable"
    )
    destination.mkdir(mode=0o700)
    (destination / "blobs").mkdir()
    records: dict[Any, Any] = {}
    links: dict[Any, Any] = {}
    directories: set[Any] = set()
    visited_dirs, queue, elf_seen = set(), [], set()
    issues, dependencies, observed = [], [], []
    total, unique = 0, 0
    trusted = [Path(p).resolve(strict=True) for p in trusted_roots]
    package_aliases = {row["logical_path"] for row in package_doc["mappings"]}

    def canon(path: Any) -> Any:
        path = Path(os.path.abspath(path))
        for _ in range(48):
            parts = path.parts
            for index in range(1, len(parts)):
                prefix = Path(*parts[: index + 1])
                if prefix.is_symlink():
                    target = os.readlink(prefix)
                    links[str(prefix)] = {"path": str(prefix), "target": target}
                    replacement = Path(target) if target.startswith("/") else prefix.parent / target
                    path = Path(os.path.normpath(str(replacement.joinpath(*parts[index + 1 :]))))
                    break
            else:
                return path
        raise RuntimeCapsuleError("Host symlink cycle or excessive chain")

    def add(path: Any, reason: Any, recurse: Any = False) -> None:
        nonlocal total, unique
        name = logical(os.path.abspath(path))
        try:
            source = canon(name)
            mode = source.stat().st_mode
        except (OSError, RuntimeCapsuleError) as error:
            issues.append({"path": name, "reason": reason, "error": str(error)})
            return
        if stat.S_ISDIR(mode):
            directories.add(str(source))
            if recurse and str(source) not in visited_dirs:
                visited_dirs.add(str(source))
                for child in sorted(source.iterdir()):
                    add(child, reason, recurse=True)
            return
        if not stat.S_ISREG(mode):
            issues.append({"path": name, "reason": reason, "error": "Nonregular source excluded"})
            return
        key = str(source)
        if key in records:
            records[key]["reasons"] = sorted(set(records[key]["reasons"] + [reason]))
            return
        before = pin(source)
        total += before["bytes"]
        require(total <= max_source_bytes, "Runtime source byte limit exceeded")
        require(
            shutil.disk_usage(destination).free - before["bytes"] >= disk_floor_bytes,
            "Runtime export would violate disk reserve",
        )
        target = destination / "blobs" / before["sha256"]
        if not target.exists():
            with source.open("rb") as old, target.open("xb") as new:
                shutil.copyfileobj(old, new, length=1 << 20)
            target.chmod(0o500)
            unique += before["bytes"]
        actual = pin(target)
        require(
            (actual["bytes"], actual["sha256"]) == (before["bytes"], before["sha256"]),
            f"Runtime source mutated during copy: {source}",
        )
        require(pin(source) == before, f"Runtime source changed: {source}")
        records[key] = {
            "path": key,
            "blob": "blobs/" + before["sha256"],
            "bytes": before["bytes"],
            "sha256": before["sha256"],
            "source_mode": stat.S_IMODE(mode),
            "reasons": [reason],
        }
        with source.open("rb") as stream:
            is_elf = stream.read(4) == b"\x7fELF"
        if is_elf:
            if any(source.is_relative_to(root) for root in trusted):
                queue.append(key)
            else:
                issues.append(
                    {
                        "path": key,
                        "reason": reason,
                        "error": "ELF dependency probing excluded outside trusted host roots",
                    }
                )

    for path in trees:
        add(path, "explicit_runtime_tree", recurse=True)
    for path in (*files, *(row["path"] for row in package_doc["host_files"])):
        add(path, "explicit_runtime_file")
    # Preserve top-level aliases without recursively importing all /usr/lib.
    for path in ("/bin", "/lib", "/lib64"):
        if Path(path).is_symlink():
            canon(path)
    successes, failures = trace_paths(trace) if trace else ([], [])
    for name in successes:
        if name in package_aliases or name.startswith(
            ("/proc/", "/dev/", "/tmp/", "/mnt/nvme/vantage-native-pocs/")
        ):
            continue
        if name.startswith(("/usr/", "/lib/", "/lib64/", "/bin/", "/etc/")) or any(
            Path(name).is_relative_to(root) for root in trusted
        ):
            add(name, "successful_retained_trace_access")
            observed.append(name)
        elif name not in records:
            issues.append(
                {
                    "path": name,
                    "reason": "successful_retained_trace_access",
                    "error": "Outside explicit runtime admission roots",
                }
            )
    while queue:
        path = queue.pop()
        if path in elf_seen:
            continue
        elf_seen.add(path)
        process = subprocess.run(
            ["/usr/bin/ldd", path],
            capture_output=True,
            text=True,
            env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"},
            timeout=20,
        )
        text = process.stdout + process.stderr
        deps = sorted(set(re.findall(r"(?<!\S)(/[^\s()]+)", text)))
        missing = [line.strip() for line in text.splitlines() if "not found" in line]
        dependencies.append(
            {
                "trusted_host_ELF": path,
                "exit_code": process.returncode,
                "dependencies": deps,
                "missing": missing,
            }
        )
        for dep in deps:
            add(dep, "trusted_host_ELF_ldd_dependency")
        if missing or (
            process.returncode
            and "not a dynamic executable" not in text
            and "statically linked" not in text
        ):
            issues.append(
                {"path": path, "reason": "trusted_host_ELF_ldd_dependency", "error": text[-1000:]}
            )
    # Bootstrap bwrap through captured ld.so and its captured shared libraries.
    bwrap = canon("/usr/bin/bwrap")
    bwrap_deps: Any = next(
        (row["dependencies"] for row in dependencies if row["trusted_host_ELF"] == str(bwrap)), None
    )
    require(bwrap_deps is not None, "Captured bwrap ELF dependencies unavailable")
    loader_name = next((p for p in bwrap_deps if "ld-linux" in p), None)
    require(loader_name is not None, "Captured ELF loader unavailable")
    loader = str(canon(loader_name))
    bootstrap = {
        "loader": records[loader]["blob"],
        "bwrap": records[str(bwrap)]["blob"],
        "libraries": [],
    }
    bootstrap_dir = destination / "bootstrap"
    bootstrap_dir.mkdir()
    for dep in bwrap_deps:
        path = str(canon(dep))
        row = records[path]
        name = Path(dep).name
        target = bootstrap_dir / name
        if target.exists():
            require(pin(target)["sha256"] == row["sha256"], "Bootstrap library basename collision")
        else:
            os.link(destination / row["blob"], target)
        bootstrap["libraries"].append(
            {"name": name, "blob": row["blob"], "sha256": row["sha256"], "bytes": row["bytes"]}
        )
    doc = {
        "schema": SCHEMA,
        "package_content_id": package_doc["package_content_id"],
        "files": [records[key] for key in sorted(records)],
        "symlinks": [links[key] for key in sorted(links)],
        "directories": sorted(directories),
        "bootstrap": bootstrap,
        "seeds": {"trees": list(map(str, trees)), "files": list(map(str, files))},
        "trusted_host_ELF_roots": list(map(str, trusted)),
        "ldd_observations": dependencies,
        "trace": pin(Path(trace)) if trace else None,
        "successful_trace_paths_considered": observed,
        "retained_failed_access_paths": failures,
        "issues": issues,
        "source_bytes": total,
        "unique_blob_bytes": unique,
        "runtime_closure_proven": False,
        "platform_outside_capsule": [
            "Linux kernel/user namespace support",
            "proc filesystem",
            "minimal dev filesystem",
            "caller-owned writable output filesystem",
            "isolated network namespace",
        ],
    }
    doc["capsule_content_id"] = identity(doc)
    (destination / "runtime.json").write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n")
    return doc


def verify_runtime_capsule(capsule: Path, package: Any = None) -> Any:
    capsule = Path(capsule).resolve(strict=True)
    doc = json.loads((capsule / "runtime.json").read_bytes())
    require(
        doc.get("schema") == SCHEMA and doc.get("capsule_content_id") == identity(doc),
        "Runtime capsule content identity differs",
    )
    names = set()
    for row in doc["files"]:
        name = logical(row["path"])
        require(
            name not in names and row["blob"] == "blobs/" + row["sha256"], "Invalid runtime mapping"
        )
        names.add(name)
        target = capsule / row["blob"]
        require(
            not target.is_symlink() and target.resolve(strict=True) == target,
            "Symlink runtime blob rejected",
        )
        actual = pin(target)
        require(
            (actual["bytes"], actual["sha256"]) == (row["bytes"], row["sha256"]),
            f"Runtime blob differs: {name}",
        )
    for row in doc["symlinks"]:
        name = logical(row["path"])
        require(
            name not in names and type(row["target"]) is str and row["target"],
            "Invalid runtime symlink",
        )
        names.add(name)
        _resolve(doc, name)
    for directory in doc["directories"]:
        logical(directory)
    blob_names = {row["blob"] for row in doc["files"]}
    require(
        doc["bootstrap"]["loader"] in blob_names and doc["bootstrap"]["bwrap"] in blob_names,
        "Bootstrap executable is not a verified captured blob",
    )
    bootstrap_root = capsule / "bootstrap"
    require(
        bootstrap_root.resolve(strict=True) == bootstrap_root
        and {p.name for p in bootstrap_root.iterdir()}
        == {row["name"] for row in doc["bootstrap"]["libraries"]},
        "Bootstrap contains unverified aliases",
    )
    for row in doc["bootstrap"]["libraries"]:
        target = capsule / "bootstrap" / row["name"]
        require(
            Path(row["name"]).name == row["name"] and not target.is_symlink(),
            "Invalid bootstrap alias",
        )
        actual = pin(target)
        require(
            (actual["bytes"], actual["sha256"]) == (row["bytes"], row["sha256"]),
            "Bootstrap library differs",
        )
    if package is not None:
        _, pkg = _package_document(package)
        require(
            pkg["package_content_id"] == doc["package_content_id"],
            "Capsule package identity differs",
        )
        records = {row["path"]: row for row in doc["files"]}
        for expected in pkg["host_files"]:
            row = records.get(_resolve(doc, expected["path"]))
            require(
                row is not None
                and (row["bytes"], row["sha256"]) == (expected["bytes"], expected["sha256"]),
                f"Captured host identity missing: {expected['path']}",
            )
    return doc


def _view_spec(
    capsule: Path,
    package: Path,
    doc: Any,
    pkg: Any,
    writable_roots: Any,
) -> Any:
    records = {row["path"]: row for row in doc["files"]}
    files = {
        name: {
            "path": name,
            "source": str(capsule / row["blob"]),
            "sha256": row["sha256"],
            "bytes": row["bytes"],
        }
        for name, row in records.items()
    }
    links = {row["path"]: row["target"] for row in doc["symlinks"]}
    suppressed = []
    for row in pkg["mappings"]:
        original = logical(row["logical_path"])
        name = _resolve(doc, original)
        runtime = records.get(name)
        if runtime:
            require(
                (runtime["bytes"], runtime["sha256"]) == (row["bytes"], row["sha256"]),
                f"Runtime/package alias conflict: {original}",
            )
            suppressed.append(original)
        else:
            require(name not in links, "Package mapping would replace runtime symlink")
            files[name] = {
                "path": name,
                "source": str(package / row["blob"]),
                "sha256": row["sha256"],
                "bytes": row["bytes"],
            }
    roots = []
    for root in writable_roots:
        path = Path(root).resolve(strict=True)
        require(
            path.is_dir()
            and not any(
                path.is_relative_to(Path(mask)) or Path(mask).is_relative_to(path)
                for mask in pkg["masked_roots"]
            ),
            "Invalid owned writable root",
        )
        require(
            not any(Path(name).is_relative_to(path) or path == Path(name) for name in files),
            "Writable root would replace captured runtime/package inputs",
        )
        roots.append(str(path))
    directories = set(doc["directories"]) | {"/proc", "/dev", "/tmp", "/run"} | set(roots)
    for name in (*files, *links, *roots):
        directories.update(str(p) for p in Path(name).parents if str(p) not in ("/", "."))
    directories.difference_update(links)
    spec: dict[str, Any] = {
        "files": [files[name] for name in sorted(files)],
        "symlinks": [{"path": name, "target": links[name]} for name in sorted(links)],
        "directories": sorted(directories),
        "writable_roots": roots,
        "suppressed_package_runtime_aliases": suppressed,
    }
    identity_data = {
        **spec,
        "files": [{k: v for k, v in row.items() if k != "source"} for row in spec["files"]],
    }
    spec["view_content_id"] = hashlib.sha256(
        json.dumps(identity_data, sort_keys=True).encode()
    ).hexdigest()
    return spec


def verify_captured_view(
    view: Any,
    spec: Any,
) -> Any:
    """Hash every materialized file and check all links before/after execution."""
    view = Path(view)
    require(view.resolve(strict=True) == view.absolute(), "Captured view has symlink ancestry")
    expected_files = {row["path"]: row for row in spec["files"]}
    expected_links = {row["path"]: row["target"] for row in spec["symlinks"]}
    observed_files, observed_links = set(), set()
    for current, directories, files in os.walk(view, followlinks=False):
        for name in [*directories, *files]:
            path = Path(current) / name
            alias = "/" + str(path.relative_to(view))
            if path.is_symlink():
                require(
                    alias in expected_links and os.readlink(path) == expected_links[alias],
                    f"Captured view symlink differs: {alias}",
                )
                observed_links.add(alias)
            elif path.is_file():
                require(alias in expected_files, f"Unexpected captured view file: {alias}")
                observed_files.add(alias)
            else:
                require(path.is_dir(), f"Unexpected captured view node: {alias}")
    require(
        observed_files == expected_files.keys() and observed_links == expected_links.keys(),
        "Captured view files/links are missing",
    )
    for name, expected in expected_files.items():
        actual = pin(view / name.lstrip("/"))
        require(
            (actual["bytes"], actual["sha256"]) == (expected["bytes"], expected["sha256"]),
            f"Captured view file differs: {name}",
        )
    return {
        "view_content_id": spec["view_content_id"],
        "files_verified": len(expected_files),
        "symlinks_verified": len(expected_links),
        "all_file_bytes_and_links_verified": True,
    }


def materialize_captured_view(
    capsule: Path,
    package: Path,
    doc: Any,
    pkg: Any,
    writable_roots: Any = (),
) -> Any:
    spec = _view_spec(capsule, package, doc, pkg, writable_roots)
    parent = capsule / "views" / spec["view_content_id"]
    view = parent / "root"
    if not parent.exists():
        parent.mkdir(parents=True)
        view.mkdir()
        for name in sorted(spec["directories"], key=lambda p: (len(Path(p).parts), p)):
            logical(name)
            (view / name.lstrip("/")).mkdir(parents=True, exist_ok=True)
        # All regular bytes precede symlink creation to avoid following absolute
        # logical aliases in the outside host namespace during materialization.
        for row in spec["files"]:
            target = view / row["path"].lstrip("/")
            target.parent.mkdir(parents=True, exist_ok=True)
            try:
                os.link(row["source"], target)
            except OSError as error:
                import errno

                if error.errno != errno.EXDEV:
                    raise
                require(
                    shutil.disk_usage(parent).free - row["bytes"] >= 5 << 30,
                    "Materialized view would violate disk reserve",
                )
                shutil.copyfile(row["source"], target)
                target.chmod(0o500)
        for row in sorted(spec["symlinks"], key=lambda r: (len(Path(r["path"]).parts), r["path"])):
            target = view / row["path"].lstrip("/")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.symlink_to(row["target"])
        for current, _, _ in os.walk(view, followlinks=False):
            Path(current).chmod(0o500)
        (parent / "view.json").write_text(json.dumps(spec, indent=2, sort_keys=True) + "\n")
    verification = verify_captured_view(view, spec)
    return view, spec, verification


def capsule_command(
    capsule: Path, package: Path, argv: list[Any], *, writable_roots: Any = ()
) -> Any:
    """Mount a verified captured view over tmpfs /; no live host runtime binds."""
    capsule = Path(capsule).resolve(strict=True)
    package, pkg = _package_document(package)
    doc = verify_runtime_capsule(capsule, package)
    view, spec, verified = materialize_captured_view(capsule, package, doc, pkg, writable_roots)
    args = [
        "--die-with-parent",
        "--unshare-all",
        "--unshare-user",
        "--cap-drop",
        "ALL",
        "--clearenv",
        "--tmpfs",
        "/",
        "--ro-bind",
        str(view),
        "/",
        "--proc",
        "/proc",
        "--dev",
        "/dev",
        "--tmpfs",
        "/tmp",
    ]
    for root in spec["writable_roots"]:
        args += ["--bind", root, root]
    args += [
        "--setenv",
        "PATH",
        "/usr/bin:/bin",
        "--setenv",
        "LANG",
        "C.UTF-8",
        "--setenv",
        "PYTHONDONTWRITEBYTECODE",
        "1",
        "--setenv",
        "PYTHONNOUSERSITE",
        "1",
        "--setenv",
        "PYTHONPATH",
        pkg["repository_alias"],
        "--setenv",
        "HOME",
        "/tmp",
        "--chdir",
        pkg["repository_alias"],
        "--",
        *map(str, argv),
    ]
    bootstrap = [
        str(capsule / doc["bootstrap"]["loader"]),
        "--inhibit-cache",
        "--library-path",
        str(capsule / "bootstrap"),
        str(capsule / doc["bootstrap"]["bwrap"]),
    ]
    receipt = {
        "capsule_content_id": doc["capsule_content_id"],
        "package_content_id": pkg["package_content_id"],
        "empty_namespace_root": True,
        "host_directory_binds": [],
        "host_root_bound": False,
        "captured_filesystem_view_bind": str(view),
        "captured_view": verified,
        "captured_file_count": len(doc["files"]),
        "suppressed_package_runtime_aliases": spec["suppressed_package_runtime_aliases"],
        "writable_roots": spec["writable_roots"],
        "bootstrap_command": bootstrap,
        "bwrap_arguments": args,
        "runtime_closure_proven": False,
        "platform_outside_capsule": doc["platform_outside_capsule"],
    }
    return bootstrap, args, receipt


def run_capsule(
    capsule: Path,
    package: Path,
    argv: list[Any],
    *,
    writable_roots: Any = (),
    stdout: Any = None,
    stderr: Any = None,
    timeout: Any = None,
) -> Any:
    bootstrap, args, receipt = capsule_command(
        capsule, package, argv, writable_roots=writable_roots
    )
    try:
        process = subprocess.run(
            [*bootstrap, *args],
            stdin=subprocess.DEVNULL,
            stdout=stdout,
            stderr=stderr,
            timeout=timeout,
            check=False,
            env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"},
        )
        receipt["exit_code"] = process.returncode
    except subprocess.TimeoutExpired:
        receipt.update(exit_code=124, timeout_expired=True, timeout_seconds=timeout)
    except OSError as error:
        receipt.update(exit_code=127, launch_error=str(error))
    doc = verify_runtime_capsule(capsule, package)
    package_root, pkg = _package_document(package)
    spec = _view_spec(Path(capsule).resolve(strict=True), package_root, doc, pkg, writable_roots)
    receipt["captured_view_reverified_after_run"] = verify_captured_view(
        receipt["captured_filesystem_view_bind"], spec
    )
    receipt["package_and_capsule_reverified_after_run"] = True
    return receipt
