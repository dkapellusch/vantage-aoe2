"""Dependency audit is recursive, conservative and never executes its inputs."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from vantage.native_engine_manifest import (
    classify_dependency,
    inspect_engine_profiles,
    inspect_replay_identity,
)


def _pin(path: Path) -> dict:
    return {
        "path": str(path),
        "bytes": path.stat().st_size,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def _profiles(root: Path):
    root.mkdir(parents=True)
    header = root / "header.h"
    header.write_text("constexpr auto WORLD_OFFSET = 0x0188;\n")
    host = root / "host.cpp"
    host.write_text(
        '#include "header.h"\n#include "missing.h"\n'
        'auto native = 0x140123456;\nfopen(variable_path, "rb");\n'
        'auto generated = "output/%s.json";\n'
    )
    dangerous = root / "loader.py"
    dangerous.write_text('raise AssertionError("inspector must not execute this")\n')
    nested = root / "nested.json"
    nested.write_text(
        json.dumps(
            {
                "codec_pins": [_pin(dangerous)],
                "missing": {"path": str(root / "lost.dat"), "bytes": 42, "sha256": "0" * 64},
            }
        )
    )
    source = root / "source.json"
    source.write_text(
        json.dumps(
            {"source_root": str(root), "sources": [{"relative": "host.cpp", "pin": _pin(host)}]}
        )
    )
    runtime = root / "runtime.json"
    runtime.write_text(json.dumps({"source_profile": _pin(source), "asset": _pin(header)}))
    encoder = root / "encoder.json"
    encoder.write_text(json.dumps({"parent_profile": _pin(nested)}))
    return source, runtime, encoder


def test_recursive_pins_source_includes_dynamic_uncertainty_and_binding_locations(tmp_path):
    profiles = _profiles(tmp_path / "tree")
    result = inspect_engine_profiles(*profiles)
    rows = {Path(row["path"]).name: row for row in result["files"]}
    assert rows["loader.py"]["status"] == "verified"
    assert rows["host.cpp"]["logical_name"] == "sources/host.cpp"
    assert rows["header.h"]["status"] == "verified"
    assert rows["lost.dat"]["status"] == "missing"
    codes = {row["code"] for row in result["issues"]}
    assert {
        "DYNAMIC_ACCESS_REVIEW",
        "DYNAMIC_PATH",
        "SOURCE_INCLUDE_UNRESOLVED",
        "MISSING_FILE",
    } <= codes
    assert any(row["relation"] == "source_include" for row in result["edges"])
    assert any(
        row["values"] == ["0x140123456"] and row["line"] == 3
        for row in result["binding_candidates"]
    )
    assert not result["native_execution"] and not result["dependency_closure_proven"]
    assert all(not row["semantics_verified"] for row in result["binding_candidates"])


def test_changed_dependency_has_role_and_all_conflicting_pins_are_reported(tmp_path):
    source, runtime, encoder = _profiles(tmp_path / "tree")
    header = source.parent / "header.h"
    header.write_text("changed contents")
    result = inspect_engine_profiles(source, runtime, encoder)
    row = next(row for row in result["files"] if row["path"] == str(header))
    assert row["status"] == "changed"
    assert "adapter_source" in row["roles"]
    assert any(
        issue["code"] == "PIN_MISMATCH" and issue["path"] == str(header)
        for issue in result["issues"]
    )


def test_identity_excludes_relocated_roots_and_pin_json_bytes(tmp_path):
    first = inspect_engine_profiles(*_profiles(tmp_path / "first"))
    second = inspect_engine_profiles(*_profiles(tmp_path / "a-longer-location"))
    assert first["inventory_content_id"] == second["inventory_content_id"]
    header = tmp_path / "a-longer-location/header.h"
    header.write_text("new content")
    changed = inspect_engine_profiles(
        tmp_path / "a-longer-location/source.json",
        tmp_path / "a-longer-location/runtime.json",
        tmp_path / "a-longer-location/encoder.json",
    )
    assert changed["inventory_content_id"] != second["inventory_content_id"]


def test_limits_explicitly_prevent_claiming_closure(tmp_path):
    profiles = _profiles(tmp_path / "tree")
    limited = inspect_engine_profiles(*profiles, max_files=3)
    assert "FILE_LIMIT" in limited["summary"]["issues"]
    limited = inspect_engine_profiles(*profiles, max_total_bytes=1)
    assert "BYTE_LIMIT" in limited["summary"]["issues"]
    limited = inspect_engine_profiles(*profiles, max_text_bytes=1)
    assert "TEXT_LIMIT" in limited["summary"]["issues"]
    with pytest.raises(ValueError, match="positive"):
        inspect_engine_profiles(*profiles, max_files=0)


def test_symlink_target_is_explicit_not_hidden(tmp_path):
    profiles = _profiles(tmp_path / "tree")
    header = profiles[0].parent / "header.h"
    real = header.with_name("real.h")
    header.rename(real)
    header.symlink_to(real)
    result = inspect_engine_profiles(*profiles)
    assert any(
        issue["code"] == "SYMLINK_DEPENDENCY" and issue["path"] == str(header)
        for issue in result["issues"]
    )


def test_unknown_replay_does_not_choose_54800_or_confuse_steam_identity(tmp_path, monkeypatch):
    from vantage import native_input, replay

    path = tmp_path / "filename-v101.103.54800.aoe2record"
    path.write_bytes(b"not loaded by mocked header reader")
    monkeypatch.setattr(
        replay,
        "read_replay",
        lambda _: SimpleNamespace(
            build=123456,
            game_version="101.103.54800",
            save_version=68.9,
            chapters=0,
            version="VER 9.4",
        ),
    )
    monkeypatch.setattr(
        native_input,
        "describe_native_input",
        lambda _: pytest.fail("unknown build must not select native descriptor"),
    )
    result = inspect_replay_identity(path)
    assert result["status"] == "unsupported_identity"
    assert result["replay_build"] == 123456
    assert result["steam_build_id"] is None and result["engine_selected"] is None


@pytest.mark.parametrize(
    ("path", "context", "role"),
    [
        ("image.dll", "assets.image", "native_image_or_derivation"),
        ("empires2.dat", "raw_dat", "simulation_data"),
        ("header.h", "sources", "adapter_source"),
        ("python3", "system.python_target", "runtime_toolchain"),
        ("source-profile.json", "", "recipe"),
        ("audit.json", "", "verification"),
    ],
)
def test_role_classifier(path, context, role):
    assert classify_dependency(path, context) == role


def test_relative_imports_and_from_package_import_scan_without_execution(tmp_path):
    source, runtime, encoder = _profiles(tmp_path / "tree")
    (source.parent / "loader.py").write_text("from . import sibling\nfrom .nested import child\n")
    (source.parent / "sibling.py").write_text("value = 1\n")
    nested = source.parent / "nested"
    nested.mkdir()
    (nested / "__init__.py").write_text("")
    (nested / "child.py").write_text("value = 2\n")
    # Refresh the nested pin after changing loader.py.
    parent_profile = source.parent / "nested.json"
    obj = json.loads(parent_profile.read_text())
    obj["codec_pins"] = [_pin(source.parent / "loader.py")]
    parent_profile.write_text(json.dumps(obj))
    encoder.write_text(json.dumps({"parent_profile": _pin(parent_profile)}))
    result = inspect_engine_profiles(source, runtime, encoder)
    names = {Path(row["path"]).name for row in result["files"]}
    assert {"sibling.py", "child.py", "__init__.py"} <= names
    assert "PYTHON_PARSE_ERROR" not in result["summary"]["issues"]


def test_data_and_historical_contracts_explicitly_stop_provenance_graph(tmp_path):
    source, runtime, encoder = _profiles(tmp_path / "tree")
    contract = source.parent / "contract.json"
    contract.write_text(
        json.dumps(
            {"old_inputs": [{"path": "/missing/old-research.dat", "bytes": 1, "sha256": "0" * 64}]}
        )
    )
    parent = source.parent / "nested.json"
    parent.write_text(json.dumps({"source_contracts": [_pin(contract)]}))
    encoder.write_text(json.dumps({"parent_profile": _pin(parent)}))
    result = inspect_engine_profiles(source, runtime, encoder)
    row = next(row for row in result["files"] if row["path"] == str(contract))
    assert row["status"] == "verified" and not row["expand_dependencies"]
    assert any(issue["code"] == "PROVENANCE_CONTRACT_LEAF" for issue in result["issues"])
    assert not result["dependency_closure_proven"]


def test_generated_relative_literal_is_not_resolved_against_historical_source_root(tmp_path):
    source, runtime, encoder = _profiles(tmp_path / "tree")
    generated = source.parent / "prepared.json"
    generated.write_text('{"old_data": "not an encoder input"}')
    child = source.parent / "codec"
    child.mkdir()
    script = child / "reader.py"
    script.write_text('path = "prepared.json"\n')
    encoder.write_text(json.dumps({"encoder": _pin(script)}))
    result = inspect_engine_profiles(source, runtime, encoder)
    assert not any(row["path"] == str(generated) for row in result["files"])
    assert any(
        issue.get("reference") == "prepared.json" and issue["code"] == "SOURCE_LITERAL_UNRESOLVED"
        for issue in result["issues"]
    )


def test_adjacent_native_libraries_are_candidates_not_assumed_imports(tmp_path):
    source, runtime, encoder = _profiles(tmp_path / "tree")
    image = source.parent / "image.dll"
    image.write_bytes(b"not loaded")
    companion = source.parent / "companion.dll"
    companion.write_bytes(b"also not loaded")
    runtime.write_text(json.dumps({"assets": {"image": _pin(image)}}))
    result = inspect_engine_profiles(source, runtime, encoder)
    assert any(row["path"] == str(companion) for row in result["files"])
    assert any(edge["relation"] == "adjacent_library_candidate" for edge in result["edges"])
    assert not result["native_execution"] and not result["dependency_closure_proven"]


def test_wine_z_drive_literal_resolves_to_declared_unix_input(tmp_path):
    source, runtime, encoder = _profiles(tmp_path / "tree")
    bank = source.parent / "audio.bnk"
    bank.write_bytes(b"not loaded")
    host = source.parent / "host.cpp"
    windows = "Z:" + str(bank).replace("/", "\\\\")
    host.write_text('auto bank = L"' + windows + '";\n')
    profile = json.loads(source.read_text())
    profile["sources"][0]["pin"] = _pin(host)
    source.write_text(json.dumps(profile))
    result = inspect_engine_profiles(source, runtime, encoder)
    assert any(
        row["path"] == str(bank) and row["status"] == "observed_unpinned" for row in result["files"]
    )
