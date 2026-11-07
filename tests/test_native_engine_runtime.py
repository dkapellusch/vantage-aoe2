"""Captured runtime identity/namespace controls; no game PE target execution."""

import hashlib
import json
import os
import shutil
from pathlib import Path

import pytest

from vantage import native_engine_runtime as N
from vantage.native_engine_package import _package_id


@pytest.fixture(autouse=True)
def unlock_owned_test_directories(tmp_path):
    yield
    # Captured views are intentionally readonly. Restore only owned temporary
    # directory permissions so pytest can clean them without following links.
    for current, _, _ in os.walk(tmp_path, followlinks=False):
        Path(current).chmod(0o700)


def fixture(tmp_path):
    package = tmp_path / "package"
    capsule = tmp_path / "capsule"
    for root in (package, capsule):
        (root / "blobs").mkdir(parents=True)
    (capsule / "bootstrap").mkdir()
    raw = b"retained trusted runtime fixture"
    sha = hashlib.sha256(raw).hexdigest()
    for root in (package, capsule):
        (root / "blobs" / sha).write_bytes(raw)
    (capsule / "bootstrap/libfixture.so").write_bytes(raw)
    expected = {"path": "/host-install-no-longer-present/python", "sha256": sha, "bytes": len(raw)}
    pkg = {
        "schema": N.PACKAGE_SCHEMA,
        "profiles": {"source": expected},
        "mappings": [
            {
                "logical_path": "/old/repo/.venv/bin/python3",
                "blob": "blobs/" + sha,
                "sha256": sha,
                "bytes": len(raw),
            }
        ],
        "host_files": [expected],
        "host_directories": ["/old/repo/.venv"],
        "masked_roots": ["/old/repo"],
        "repository_alias": "/old/repo",
    }
    pkg["package_content_id"] = _package_id(pkg)
    (package / "package.json").write_text(json.dumps(pkg))
    doc = {
        "schema": N.SCHEMA,
        "package_content_id": pkg["package_content_id"],
        "files": [
            {**expected, "blob": "blobs/" + sha, "source_mode": 0o755, "reasons": ["fixture"]}
        ],
        "symlinks": [
            {"path": "/old/repo/.venv/bin/python3", "target": "/old/repo/.venv/bin/python"},
            {"path": "/old/repo/.venv/bin/python", "target": expected["path"]},
            {"path": "/bin", "target": "usr/bin"},
        ],
        "directories": ["/usr/bin", "/old/repo/.venv/bin", "/host-install-no-longer-present"],
        "bootstrap": {
            "loader": "blobs/" + sha,
            "bwrap": "blobs/" + sha,
            "libraries": [
                {"name": "libfixture.so", "blob": "blobs/" + sha, "sha256": sha, "bytes": len(raw)}
            ],
        },
        "platform_outside_capsule": ["kernel", "proc", "dev"],
    }
    doc["capsule_content_id"] = N.identity(doc)
    (capsule / "runtime.json").write_text(json.dumps(doc))
    return capsule, package, doc


def write(capsule, doc):
    doc["capsule_content_id"] = N.identity(doc)
    (capsule / "runtime.json").write_text(json.dumps(doc))


def test_captured_host_pin_and_python_symlink_resolve_without_original_installation(tmp_path):
    capsule, package, doc = fixture(tmp_path)
    assert not Path("/host-install-no-longer-present/python").exists()
    assert (
        N.verify_runtime_capsule(capsule, package)["capsule_content_id"]
        == doc["capsule_content_id"]
    )
    assert (
        N._resolve(doc, "/old/repo/.venv/bin/python3") == "/host-install-no-longer-present/python"
    )


def test_empty_root_command_uses_captured_view_and_owned_output(tmp_path):
    capsule, package, doc = fixture(tmp_path)
    out = tmp_path / "owned-output"
    out.mkdir()
    bootstrap, args, receipt = N.capsule_command(
        capsule, package, ["/bin/sh"], writable_roots=(out,)
    )
    assert args[args.index("--tmpfs") + 1] == "/"
    assert not any(args[i : i + 3] == ["--ro-bind", "/", "/"] for i in range(len(args)))
    assert receipt["host_directory_binds"] == [] and receipt["host_root_bound"] is False
    assert receipt["suppressed_package_runtime_aliases"] == ["/old/repo/.venv/bin/python3"]
    assert bootstrap[0] == str(capsule / doc["bootstrap"]["loader"])
    assert "--inhibit-cache" in bootstrap
    for i, arg in enumerate(args):
        if arg == "--ro-bind":
            assert Path(args[i + 1]) == Path(receipt["captured_filesystem_view_bind"])
            assert args[i + 2] == "/"
    assert receipt["captured_view"]["all_file_bytes_and_links_verified"] is True


@pytest.mark.parametrize("change", ["missing", "corrupt", "link"])
def test_materialized_view_tampering_is_rejected(tmp_path, change):
    capsule, package, doc = fixture(tmp_path)
    _, _, receipt = N.capsule_command(capsule, package, ["/bin/sh"])
    view = Path(receipt["captured_filesystem_view_bind"])
    spec = json.loads((view.parent / "view.json").read_text())
    target = view / doc["files"][0]["path"].lstrip("/")
    target.parent.chmod(0o700)
    if change == "missing":
        target.unlink()
    elif change == "corrupt":
        # Break the hardlink before corrupting; the capsule's own bytes survive.
        target.unlink()
        target.write_bytes(b"changed view bytes")
    else:
        link = view / "old/repo/.venv/bin/python"
        link.parent.chmod(0o700)
        link.unlink()
        link.symlink_to("/different/runtime")
    N.verify_runtime_capsule(capsule, package)
    with pytest.raises(N.RuntimeCapsuleError):
        N.verify_captured_view(view, spec)


def test_execution_rechecks_view_and_uses_bounded_direct_argv(tmp_path, monkeypatch):
    capsule, package, _ = fixture(tmp_path)
    calls = []

    def execute(argv, **kwargs):
        calls.append(argv)
        return type("Completed", (), {"returncode": 0})()

    monkeypatch.setattr(N.subprocess, "run", execute)
    receipt = N.run_capsule(capsule, package, ["/bin/sh", "-c", "true"])
    assert calls[0][-4:] == ["--", "/bin/sh", "-c", "true"]
    assert receipt["captured_view_reverified_after_run"]["all_file_bytes_and_links_verified"]


def test_timeout_preserves_receipt_and_rechecks_view(tmp_path, monkeypatch):
    capsule, package, _ = fixture(tmp_path)

    def execute(argv, **kwargs):
        raise N.subprocess.TimeoutExpired(argv, 1)

    monkeypatch.setattr(N.subprocess, "run", execute)
    receipt = N.run_capsule(capsule, package, ["/bin/sh"], timeout=1)
    assert receipt["exit_code"] == 124 and receipt["timeout_expired"]
    assert receipt["captured_view_reverified_after_run"]["all_file_bytes_and_links_verified"]


def test_capsule_root_move_preserves_identity_and_uses_new_blob_sources(tmp_path):
    capsule, package, doc = fixture(tmp_path)
    moved = tmp_path / "moved-capsule"
    shutil.copytree(capsule, moved)
    bootstrap, args, receipt = N.capsule_command(moved, package, ["/bin/sh"])
    assert receipt["capsule_content_id"] == doc["capsule_content_id"]
    assert all(str(capsule) not in arg for arg in bootstrap + args)
    assert str(moved / "views") in receipt["captured_filesystem_view_bind"]


@pytest.mark.parametrize(
    "change",
    [
        "blob",
        "bootstrap",
        "extra_bootstrap",
        "symlink_blob",
        "escaping_bootstrap",
        "bad_directory",
        "cycle",
    ],
)
def test_tampering_and_unsafe_aliases_rejected(tmp_path, change):
    capsule, package, doc = fixture(tmp_path)
    target = capsule / doc["files"][0]["blob"]
    if change == "blob":
        target.write_bytes(b"tampered")
    if change == "bootstrap":
        (capsule / "bootstrap/libfixture.so").write_bytes(b"tampered")
    if change == "extra_bootstrap":
        (capsule / "bootstrap/unverified.so").write_bytes(b"unverified")
    if change == "symlink_blob":
        outside = tmp_path / "outside"
        outside.write_bytes(target.read_bytes())
        target.unlink()
        target.symlink_to(outside)
    if change == "escaping_bootstrap":
        doc["bootstrap"]["loader"] = "../../usr/bin/bwrap"
        write(capsule, doc)
    if change == "bad_directory":
        doc["directories"].append("/../../etc")
        write(capsule, doc)
    if change == "cycle":
        doc["symlinks"].append(
            {
                "path": "/host-install-no-longer-present/python",
                "target": "/old/repo/.venv/bin/python",
            }
        )
        write(capsule, doc)
    with pytest.raises(N.RuntimeCapsuleError):
        N.verify_runtime_capsule(capsule, package)


def test_package_host_hash_must_match_captured_bytes(tmp_path):
    capsule, package, doc = fixture(tmp_path)
    pkg = json.loads((package / "package.json").read_text())
    pkg["host_files"][0]["sha256"] = "f" * 64
    pkg["package_content_id"] = _package_id(pkg)
    (package / "package.json").write_text(json.dumps(pkg))
    doc["package_content_id"] = pkg["package_content_id"]
    write(capsule, doc)
    with pytest.raises(N.RuntimeCapsuleError, match="Captured host identity"):
        N.verify_runtime_capsule(capsule, package)


def test_trace_success_and_failed_paths_stay_distinct(tmp_path):
    trace = tmp_path / "trace"
    trace.write_text(
        '1 openat(AT_FDCWD, "/usr/lib/a.so", O_RDONLY) = 3\n'
        '1 openat(AT_FDCWD, "/usr/lib/missing.so", O_RDONLY) = -1 ENOENT\n'
        '1 openat(AT_FDCWD, "/usr/lib/trunc"..., O_RDONLY) = 3\n'
    )
    assert N.trace_paths(trace) == (["/usr/lib/a.so"], ["/usr/lib/missing.so"])


def test_game_PE_is_never_passed_to_ldd(tmp_path, monkeypatch):
    _, package, _ = fixture(tmp_path)
    pe = tmp_path / "untrusted-game.exe"
    pe.write_bytes(b"MZ" + b"\0" * 128)
    calls = []
    monkeypatch.setattr(N.subprocess, "run", lambda *a, **k: calls.append(a))
    with pytest.raises(N.RuntimeCapsuleError, match="bwrap ELF dependencies"):
        N.export_runtime_capsule(package, tmp_path / "export", files=[pe], trusted_roots=[tmp_path])
    assert calls == []
