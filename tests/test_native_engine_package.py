from __future__ import annotations

import json
from pathlib import Path

import pytest

from vantage.native_conversion import pin
from vantage.native_engine_package import (
    EnginePackageError,
    export_engine_package,
    package_command,
    verify_engine_package,
)


def _setup(root):
    repository = root / "repo"
    (repository / "src" / "vantage").mkdir(parents=True)
    (repository / "tools").mkdir()
    (repository / ".venv").mkdir()
    source = repository / "source.json"
    header = repository / "header.h"
    header.write_text("pinned source")
    source.write_text(json.dumps({"sources": [{"relative": "header.h", "pin": pin(header)}]}))
    runtime = repository / "runtime.json"
    runtime.write_text(json.dumps({"staging_profile": pin(source)}))
    current = repository / "src/vantage/module.py"
    current.write_text("user modifications")
    retained = repository / "old-module.py"
    retained.write_text("historical contract")
    parent = repository / "parent.json"
    expected = dict(pin(retained), path=str(current))
    parent.write_text(
        json.dumps(
            {"codec_pins": [expected], "source_contracts": [], "source_evidence": pin(header)}
        )
    )
    encoder = repository / "encoder.json"
    encoder.write_text(
        json.dumps(
            {
                "parent_profile": pin(parent),
                "python_target": pin(Path("/usr/bin/python3").resolve()),
                "overlays": [{"target": str(current), "source": pin(retained)}],
            }
        )
    )
    return repository, source, runtime, encoder, current


def test_export_preserves_historical_overlays_and_relocation_identity(tmp_path):
    repository, source, runtime, encoder, current = _setup(tmp_path)
    original = current.read_text()
    first = tmp_path / "first-package"
    manifest = export_engine_package(
        source, runtime, encoder, first, repository=repository, disk_floor_bytes=1
    )
    mapping = next(row for row in manifest["mappings"] if row["logical_path"] == str(current))
    assert (first / mapping["blob"]).read_text() == "historical contract"
    assert current.read_text() == original
    assert not manifest["runtime_closure_proven"]
    moved = tmp_path / "moved-package"
    first.rename(moved)
    assert verify_engine_package(moved)["package_content_id"] == manifest["package_content_id"]
    output = tmp_path / "runs"
    output.mkdir()
    command, receipt = package_command(moved, ["/bin/true"], writable_roots=(output,))
    with pytest.raises(EnginePackageError, match="writable"):
        package_command(moved, ["/bin/true"], writable_roots=(tmp_path,))
    assert str(moved / mapping["blob"]) in command
    assert "--tmpfs" in command and "--unshare-net" in command
    assert all(row["path"] != str(current) for row in receipt["host_dependencies"])


def test_modified_missing_or_symlink_blob_rejected(tmp_path):
    repository, source, runtime, encoder, _ = _setup(tmp_path)
    package = tmp_path / "package"
    manifest = export_engine_package(
        source, runtime, encoder, package, repository=repository, disk_floor_bytes=1
    )
    blob = package / manifest["mappings"][0]["blob"]
    blob.chmod(0o600)
    blob.write_text("modified")
    with pytest.raises(EnginePackageError, match="differs"):
        verify_engine_package(package)
    blob.unlink()
    blob.symlink_to(source)
    with pytest.raises(EnginePackageError, match="Symlink"):
        verify_engine_package(package)
    blob.unlink()
    with pytest.raises(FileNotFoundError):
        verify_engine_package(package)


def test_changed_source_fails_before_success_manifest(tmp_path):
    repository, source, runtime, encoder, _ = _setup(tmp_path)
    (repository / "header.h").write_text("mutated after pinning")
    package = tmp_path / "package"
    with pytest.raises(EnginePackageError, match="differs"):
        export_engine_package(
            source, runtime, encoder, package, repository=repository, disk_floor_bytes=1
        )
    assert not (package / "package.json").exists()


def test_namespace_uses_packaged_bytes_and_hides_unlisted_original_files(tmp_path):
    import shutil
    import subprocess

    if shutil.which("bwrap") is None:
        pytest.skip("bubblewrap is unavailable")
    repository, source, runtime, encoder, current = _setup(tmp_path)
    hidden = repository / "not-in-package.secret"
    hidden.write_text("must stay hidden")
    package = tmp_path / "package"
    export_engine_package(
        source, runtime, encoder, package, repository=repository, disk_floor_bytes=1
    )
    script = (
        "from pathlib import Path; "
        f"assert Path({str(current)!r}).read_text() == 'historical contract'; "
        f"assert not Path({str(hidden)!r}).exists()"
    )
    command, _ = package_command(package, ["/usr/bin/python3", "-c", script])
    result = subprocess.run(command, text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
    assert current.read_text() == "user modifications" and hidden.exists()
