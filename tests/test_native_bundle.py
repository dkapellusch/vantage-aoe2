"""Tiny authored bundle fixtures; no native code, compiler or real capsule scan."""

from __future__ import annotations

import argparse
import hashlib
import importlib.machinery
import importlib.util
import json
import os
import py_compile
import signal
import subprocess
import sys
from pathlib import Path

import pytest

from tests.test_native import setup_worker
from vantage import native_bundle as bundle
from vantage.native import NativeWorker


@pytest.fixture(autouse=True)
def isolated_bootstrap_namespace():
    yield
    for key in list(sys.modules):
        if key.startswith("_vantage_owned_engine_bootstrap"):
            del sys.modules[key]


def write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True))


def prepare(tmp_path: Path, *, link: bool = False) -> argparse.Namespace:
    worker_dir = tmp_path / "worker"
    worker_dir.mkdir()
    jobs, _, descriptor = setup_worker(worker_dir)
    jobs.close()
    worker = json.loads(descriptor.read_text())
    registry = json.loads(Path(worker["registry"]["path"]).read_text())
    pkg = tmp_path / "input-package"
    cap = tmp_path / "input-capsule"
    for root in (pkg, cap):
        payload = b"authored tiny fixture; not a native engine"
        digest = hashlib.sha256(payload).hexdigest()
        row = {"blob": "blobs/" + digest, "bytes": len(payload), "sha256": digest}
        target = root / row["blob"]
        target.parent.mkdir(parents=True)
        target.write_bytes(payload)
    write(
        pkg / "package.json",
        {
            "package_content_id": "a" * 64,
            "repository_alias": "/authored-captured-repo",
            "profiles": registry["engines"][0]["profiles"],
            "mappings": [row],
        },
    )
    write(
        cap / "runtime.json",
        {
            "capsule_content_id": "b" * 64,
            "package_content_id": "a" * 64,
            "files": [row],
            "bootstrap": {"libraries": []},
        },
    )
    source = tmp_path / "authored-bootstrap"
    source.mkdir()
    for name in bundle.MODULES:
        (source / (name + ".py")).write_text("# Authored empty bootstrap fixture\n")
    (source / "native_engine_runtime.py").write_text("""
import json, sys
from pathlib import Path
def verify_runtime_capsule(capsule, package):
    return json.loads((Path(capsule)/'runtime.json').read_text())
def capsule_command(capsule, package, command, writable_roots):
    cache = writable_roots[0]
    result = Path(command[command.index('--output')+1])
    assert '--experimental' in command
    assert command[0] == '/authored-captured-repo/.venv/bin/python'
    for flag in ('--registry', '--replay'):
        path = Path(command[command.index(flag)+1])
        assert path.is_relative_to(cache) and path.is_file()
    script = "import pathlib;pathlib.Path("+repr(str(result))+").write_text('fixture only')"
    return [sys.executable, '-c', script], [], {
        'capsule_content_id': 'b'*64, 'package_content_id': 'a'*64,
        'captured_filesystem_view_bind': 'authored-fixture',
        'captured_view': {'authored': True, 'not_real_verification': True},
        'empty_namespace_root': True, 'host_root_bound': False, 'host_directory_binds': [],
        'fixture_not_native_or_isolation': True,
    }
def _package_document(package):
    return package, json.loads((Path(package)/'package.json').read_text())
def _view_spec(*args):
    return {'authored': True}
def verify_captured_view(view, spec):
    return {'authored': True, 'not_real_verification': True}
""")
    ticket = tmp_path / "ticket.json"
    write(
        ticket,
        {
            "kind": "vantage_native_bootstrap_sources",
            "version": 1,
            "modules": {name: bundle.pin(source / (name + ".py")) for name in bundle.MODULES},
        },
    )
    return argparse.Namespace(
        bootstrap_sources=ticket,
        bootstrap_sha256=bundle.pin(ticket)["sha256"],
        package=pkg,
        capsule=cap,
        registry=Path(worker["registry"]["path"]),
        registry_sha256=worker["registry"]["sha256"],
        package_id="a" * 64,
        capsule_id="b" * 64,
        destination=tmp_path / "imported",
        link=link,
    )


@pytest.mark.parametrize("link", [False, True])
def test_import_makes_self_contained_pinned_client(tmp_path: Path, link: bool) -> None:
    args = prepare(tmp_path, link=link)
    result = bundle.import_bundle(args)
    root = args.destination
    assert result["all_declared_import_bytes_verified"] is True
    assert result["native_conversion_executed"] is False
    assert result["hardlinks"] is link
    client = NativeWorker(root / "client.json", result["descriptor"]["sha256"])
    assert client.describe()["builds"] == [54800]
    assert "forge" not in sys.modules
    metadata = json.loads((root / "bundle.json").read_text())
    assert set(metadata["files"]) == {
        *bundle.FILES,
        "registry.json",
        "package/package.json",
        "capsule/runtime.json",
    }
    old_blob = next((args.package / "blobs").iterdir())
    new_blob = root / "package/blobs" / old_blob.name
    assert (old_blob.stat().st_ino == new_blob.stat().st_ino) is link
    (root / "bootstrap/native_conversion.py").chmod(0o600)
    (root / "bootstrap/native_conversion.py").write_text("changed")
    with pytest.raises(Exception, match="changed"):
        client.verify()


@pytest.mark.parametrize(
    "change", ["ticket-sha", "source", "registry", "package", "capsule", "blob"]
)
def test_import_rejects_changed_inputs(tmp_path: Path, change: str) -> None:
    args = prepare(tmp_path)
    if change == "ticket-sha":
        args.bootstrap_sha256 = "0" * 64
    elif change == "source":
        source = json.loads(args.bootstrap_sources.read_text())["modules"]["native_conversion"][
            "path"
        ]
        Path(source).write_text("changed")
    elif change == "registry":
        args.registry.write_text("{}")
    elif change == "package":
        args.package_id = "c" * 64
    elif change == "capsule":
        args.capsule_id = "c" * 64
    else:
        next((args.package / "blobs").iterdir()).write_bytes(b"changed")
    with pytest.raises(ValueError):
        bundle.import_bundle(args)
    assert not (args.destination / "client.json").exists()


def test_stage_preserves_raw_identity_reuses_bytes_and_rejects_mutation(tmp_path: Path) -> None:
    replay = tmp_path / "input.aoe2record"
    replay.write_bytes(b"authored raw replay bytes")
    folder = tmp_path / "cache/requests"
    first = bundle.stage_file(replay, folder, ".aoe2record")
    second = bundle.stage_file(replay, folder, ".aoe2record")
    assert first == second
    assert first["sha256"] == bundle.pin(replay)["sha256"]
    Path(first["path"]).chmod(0o600)
    Path(first["path"]).write_bytes(b"changed")
    with pytest.raises(ValueError, match="Staged input differs"):
        bundle.stage_file(replay, folder, ".aoe2record")


def test_symlink_staging_rejects(tmp_path: Path) -> None:
    replay = tmp_path / "input.aoe2record"
    replay.write_bytes(b"raw")
    outside = tmp_path / "outside"
    outside.mkdir()
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "requests").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink ancestry"):
        bundle.stage_file(replay, cache / "requests", ".aoe2record")


@pytest.mark.parametrize("conflicting", [False, True])
def test_repeated_bootstrap_alias_requires_identical_bytes(
    tmp_path: Path, conflicting: bool
) -> None:
    args = prepare(tmp_path)
    library = args.capsule / "bootstrap/fixture.so"
    library.parent.mkdir()
    library.write_bytes(b"authored library bytes")
    row = {
        "name": "fixture.so",
        **{key: value for key, value in bundle.pin(library).items() if key != "path"},
    }
    repeated = dict(row)
    if conflicting:
        repeated["sha256"] = "f" * 64
    metadata = json.loads((args.capsule / "runtime.json").read_text())
    metadata["bootstrap"]["libraries"] = [row, repeated]
    write(args.capsule / "runtime.json", metadata)
    if conflicting:
        with pytest.raises(ValueError, match="Conflicting bootstrap library identities"):
            bundle.import_bundle(args)
        assert not (args.destination / "client.json").exists()
    else:
        assert bundle.import_bundle(args)["all_declared_import_bytes_verified"] is True
        assert (
            args.destination / "capsule/bootstrap/fixture.so"
        ).read_bytes() == library.read_bytes()


def test_bootstrap_pin_and_unknown_files_reject_before_import(tmp_path: Path) -> None:
    args = prepare(tmp_path)
    bundle.import_bundle(args)
    for name in list(sys.modules):
        if name.startswith("_vantage_owned_engine_bootstrap"):
            del sys.modules[name]
    (args.destination / "bootstrap/native_conversion.py").chmod(0o600)
    (args.destination / "bootstrap/native_conversion.py").write_text(
        "raise RuntimeError('must not execute')"
    )
    with pytest.raises(ValueError, match="changed"):
        bundle.load_bundle(args.destination)
    assert "_vantage_owned_engine_bootstrap" not in sys.modules


def test_authored_controller_stages_inputs_and_records_postverification(tmp_path: Path) -> None:
    args = prepare(tmp_path)
    bundle.import_bundle(args)
    for name in list(sys.modules):
        if name.startswith("_vantage_owned_engine_bootstrap"):
            del sys.modules[name]
    replay = tmp_path / "replay.aoe2record"
    replay.write_bytes(b"authored request bytes")
    cache = tmp_path / "cache"
    output = cache / "client-jobs/fixture/result.json"
    run = argparse.Namespace(
        bundle=args.destination,
        experimental=True,
        runtime_timeout=10,
        encoder_timeout=10,
        cache_dir=cache,
        output=output,
        registry=args.registry,
        registry_sha256=args.registry_sha256,
        replay=replay,
        require_capability=["world_frames"],
        reuse_job=None,
    )
    assert bundle.run_bundle(run) == 0
    assert output.read_text() == "fixture only"
    receipt = json.loads(output.with_name(output.name + ".capsule-receipt.json").read_text())
    assert receipt["fixture_not_native_or_isolation"] is True
    assert receipt["postverification_complete"] is True
    assert receipt["original_replay"]["sha256"] == receipt["staged_replay"]["sha256"]
    assert receipt["staged_replay"]["path"] != str(replay)


def forget_bootstrap() -> None:
    for name in list(sys.modules):
        if name.startswith("_vantage_owned_engine_bootstrap"):
            del sys.modules[name]


def run_options(tmp_path: Path, args: argparse.Namespace) -> argparse.Namespace:
    replay = tmp_path / "request.aoe2record"
    replay.write_bytes(b"authored original request")
    cache = tmp_path / "run-cache"
    return argparse.Namespace(
        bundle=args.destination,
        experimental=True,
        runtime_timeout=10,
        encoder_timeout=10,
        cache_dir=cache,
        output=cache / "client-jobs/fixture/result.json",
        registry=args.registry,
        registry_sha256=args.registry_sha256,
        replay=replay,
        require_capability=["world_frames"],
        reuse_job=None,
    )


@pytest.mark.parametrize("shadow", ["pycache", "package", "extension", "extra-file"])
def test_untracked_bootstrap_code_rejects_before_execution(tmp_path: Path, shadow: str) -> None:
    args = prepare(tmp_path)
    bundle.import_bundle(args)
    forget_bootstrap()
    root = args.destination / "bootstrap"
    if shadow == "pycache":
        poison = tmp_path / "poison.py"
        poison.write_text("raise RuntimeError('untracked bytecode executed')")
        cache = Path(importlib.util.cache_from_source(str(root / "native_conversion.py")))
        cache.parent.mkdir()
        py_compile.compile(
            str(poison),
            cfile=str(cache),
            doraise=True,
            invalidation_mode=py_compile.PycInvalidationMode.UNCHECKED_HASH,
        )
    elif shadow == "package":
        package = root / "native_conversion"
        package.mkdir()
        (package / "__init__.py").write_text("raise RuntimeError('untracked package executed')")
    elif shadow == "extension":
        (root / ("native_conversion" + importlib.machinery.EXTENSION_SUFFIXES[0])).write_bytes(
            b"not native code"
        )
    else:
        (root / "untracked.py").write_text("raise RuntimeError('untracked code executed')")
    with pytest.raises(ValueError, match="Unexpected bootstrap"):
        bundle.load_bundle(args.destination)
    assert "_vantage_owned_engine_bootstrap" not in sys.modules


def test_imported_controller_ignores_python_startup_injection(tmp_path: Path) -> None:
    args = prepare(tmp_path)
    bundle.import_bundle(args)
    descriptor = json.loads((args.destination / "client.json").read_text())
    marker = tmp_path / "startup-executed"
    poison = tmp_path / "poison"
    poison.mkdir()
    code = "from pathlib import Path;Path(" + repr(str(marker)) + ").write_text('executed')\n"
    (poison / "sitecustomize.py").write_text(code)
    (poison / "json.py").write_text(code + "raise RuntimeError('untracked json')\n")
    command = [*descriptor["command"], "--help"]
    assert all(flag in command for flag in ("-I", "-S", "-B"))
    child = subprocess.run(
        command,
        cwd=poison,
        env=dict(os.environ, PYTHONPATH=str(poison)),
        capture_output=True,
        timeout=10,
    )
    assert child.returncode == 0, child.stderr
    assert not marker.exists()


def test_changed_replay_between_identification_and_staging_rejects(
    tmp_path: Path, monkeypatch
) -> None:
    args = prepare(tmp_path)
    bundle.import_bundle(args)
    forget_bootstrap()
    run = run_options(tmp_path, args)
    original = bundle.pin(run.replay)
    stage = bundle.stage_file

    def race(source, folder, suffix, expected_sha=None):
        if suffix == ".aoe2record":
            assert expected_sha == original["sha256"]
            source.write_bytes(b"different replay bytes")
        return stage(source, folder, suffix, expected_sha)

    monkeypatch.setattr(bundle, "stage_file", race)
    with pytest.raises(ValueError, match="Request input identity differs"):
        bundle.run_bundle(run)
    assert not run.output.exists()


def test_cancellation_during_postverification_cannot_return_success(
    tmp_path: Path, monkeypatch
) -> None:
    args = prepare(tmp_path)
    bundle.import_bundle(args)
    forget_bootstrap()
    run = run_options(tmp_path, args)
    original = bundle.runtime_module
    previous_signal = signal.getsignal(signal.SIGINT)

    def interrupted(root, expected):
        module = original(root, expected)
        verify = module.verify_captured_view

        def after(*values):
            result = verify(*values)
            os.kill(os.getpid(), signal.SIGINT)
            return result

        module.verify_captured_view = after
        return module

    monkeypatch.setattr(bundle, "runtime_module", interrupted)
    assert bundle.run_bundle(run) == 130
    receipt = json.loads(
        run.output.with_name(run.output.name + ".capsule-receipt.json").read_text()
    )
    assert receipt["cancelled"] is True and receipt["postverification_complete"] is False
    assert signal.getsignal(signal.SIGINT) == previous_signal


def test_failure_writing_start_receipt_stops_owned_child(tmp_path: Path, monkeypatch) -> None:
    args = prepare(tmp_path)
    bundle.import_bundle(args)
    forget_bootstrap()
    run = run_options(tmp_path, args)
    original_popen, original_write = subprocess.Popen, bundle.write_new
    children = []

    def child(_command, **kwargs):
        process = original_popen(
            [sys.executable, "-I", "-S", "-c", "import time;time.sleep(60)"], **kwargs
        )
        children.append(process)
        return process

    def fail(path, value):
        if path.name.endswith(".capsule-start.json"):
            raise OSError("authored start-receipt failure")
        return original_write(path, value)

    monkeypatch.setattr(bundle.subprocess, "Popen", child)
    monkeypatch.setattr(bundle, "write_new", fail)
    with pytest.raises(OSError, match="authored start-receipt failure"):
        bundle.run_bundle(run)
    assert len(children) == 1 and children[0].poll() is not None


def test_failed_postverification_has_failure_receipt(tmp_path: Path, monkeypatch) -> None:
    args = prepare(tmp_path)
    bundle.import_bundle(args)
    forget_bootstrap()
    run = run_options(tmp_path, args)
    original = bundle.runtime_module

    def changed(root, expected):
        module = original(root, expected)

        def fail(*_values):
            raise ValueError("authored captured-view mutation")

        module.verify_captured_view = fail
        return module

    monkeypatch.setattr(bundle, "runtime_module", changed)
    with pytest.raises(ValueError, match="authored captured-view mutation"):
        bundle.run_bundle(run)
    receipt = json.loads(
        run.output.with_name(run.output.name + ".capsule-receipt.json").read_text()
    )
    assert receipt["postverification_complete"] is False
    assert receipt["postverification_error"] == "authored captured-view mutation"
