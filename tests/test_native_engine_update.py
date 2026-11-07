"""Update acquisition detects file changes and never invents qualification."""

import copy
from pathlib import Path

import pytest

from vantage import native_engine_update as update


def selected(root, name="AoE2DE_s.exe", content=b"code1", roles=None):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    row = {"path": name}
    if roles:
        row["roles"] = roles
    return {"files": [row]}


def snap(tmp_path, name="AoE2DE_s.exe", content=b"code1", roles=None):
    root = tmp_path / "install"
    root.mkdir(parents=True)
    selection = selected(root, name, content, roles)
    return update.snapshot_installation(root, selection, blob_store=tmp_path / "blobs")


def test_unchanged_is_no_work_and_deduplicates_without_changing_install(tmp_path):
    root = tmp_path / "install"
    root.mkdir()
    selection = selected(root)
    first = update.snapshot_installation(root, selection, blob_store=tmp_path / "blobs")
    second = update.snapshot_installation(root, selection, blob_store=tmp_path / "blobs")
    assert first["snapshot_id"] == second["snapshot_id"]
    assert first["acquisition"]["new_blob_bytes"] == 5
    assert second["acquisition"]["new_blob_bytes"] == 0
    assert second["acquisition"]["reused_blob_bytes"] == 5
    assessment = update.assess_update(first, second)
    assert assessment["assessment"] == "no_work"
    assert not assessment["discovery_work_required"]
    assert not assessment["activation_performed"]
    assert not assessment["qualification"]["supported"]
    assert (root / "AoE2DE_s.exe").read_bytes() == b"code1"


@pytest.mark.parametrize(
    "name,role",
    [
        ("resources/_common/dat/empires2_x2_p1.dat", "simulation_data"),
        ("graphics/unit.png", "presentation"),
        ("AoE2DE_s.exe", "native_code"),
        ("runtime/wine", "runtime_toolchain"),
        ("input/replay-format.json", "input_schema"),
    ],
)
def test_changed_role_requires_qualification_and_retains_previous(tmp_path, name, role):
    first = snap(tmp_path / "a", name, b"before", [role])
    second = snap(tmp_path / "b", name, b"after", [role])
    assessment = update.assess_update(first, second)
    assert assessment["impact_classes"] == [role]
    assert assessment["assessment"] == "unqualified_candidate"
    assert assessment["replay_qualification_required"]
    assert assessment["old_package_preserved"]
    assert not assessment["activation_performed"]
    assert assessment["qualification"]["level"] == "unqualified"


def test_multiple_change_impacts_and_unknown_executable_do_not_promote(tmp_path):
    first = snap(tmp_path / "a", roles=["native_code", "simulation_data"])
    second = snap(tmp_path / "b", content=b"new code", roles=["native_code", "simulation_data"])
    report = update.assess_update(
        first,
        second,
        result_records=[
            {
                "status": "ready",
                "supported": True,
                "all_checksums_passed": True,
                "qualification": "complete_corpus_verified",
            }
        ],
    )
    assert report["impact_classes"] == ["native_code", "simulation_data"]
    assert not report["qualification"]["supported"]
    assert report["qualification"]["level"] == "unqualified"
    assert (
        report["qualification"]["result_records"][0]["status"] == "not_authoritative_for_candidate"
    )
    assert report["rollback"]["previous_snapshot_id"] == first["snapshot_id"]


def test_mutation_between_hash_copy_and_final_recheck_rejects(tmp_path, monkeypatch):
    root = tmp_path / "install"
    root.mkdir()
    selection = selected(root)
    original = update._read_selected
    calls = 0

    def changing(*args, **kwargs):
        nonlocal calls
        calls += 1
        result = original(*args, **kwargs)
        if calls == 2:
            (root / "AoE2DE_s.exe").write_bytes(b"code2")
        return result

    monkeypatch.setattr(update, "_read_selected", changing)
    with pytest.raises(update.UpdateAssessmentError, match="changed during snapshot"):
        update.snapshot_installation(root, selection, blob_store=tmp_path / "blobs")


def test_mutation_between_pre_hash_and_copy_rejects(tmp_path, monkeypatch):
    root = tmp_path / "install"
    root.mkdir()
    selection = selected(root)
    original = update._read_selected
    calls = 0

    def changing(*args, **kwargs):
        nonlocal calls
        calls += 1
        result = original(*args, **kwargs)
        if calls == 1:
            (root / "AoE2DE_s.exe").write_bytes(b"newcode")
        return result

    monkeypatch.setattr(update, "_read_selected", changing)
    with pytest.raises(update.UpdateAssessmentError, match="changed between acquisition passes"):
        update.snapshot_installation(root, selection, blob_store=tmp_path / "blobs")


def test_existing_corrupt_or_symlink_blob_is_rejected(tmp_path):
    root = tmp_path / "install"
    root.mkdir()
    selection = selected(root)
    first = update.snapshot_installation(root, selection, blob_store=tmp_path / "blobs")
    blob = Path(first["files"][0]["blob"]["path"])
    blob.chmod(0o644)
    blob.write_bytes(b"wrong")
    with pytest.raises(update.UpdateAssessmentError, match="corrupt"):
        update.snapshot_installation(root, selection, blob_store=tmp_path / "blobs")
    blob.unlink()
    blob.symlink_to(root / "AoE2DE_s.exe")
    with pytest.raises(update.UpdateAssessmentError, match="corrupt"):
        update.snapshot_installation(root, selection, blob_store=tmp_path / "blobs")


@pytest.mark.parametrize(
    "relative", ["../outside", "/outside", "a/../outside", "a//b", "a\\b", "."]
)
def test_selection_cannot_escape_supplied_root(tmp_path, relative):
    with pytest.raises(update.UpdateAssessmentError, match=r"relative|root|noncanonical"):
        update.snapshot_installation(
            tmp_path, {"files": [{"path": relative}]}, blob_store=tmp_path / "blobs"
        )


def test_selected_file_and_parent_directory_symlinks_rejected(tmp_path):
    root = tmp_path / "install"
    root.mkdir()
    external = tmp_path / "outside"
    external.mkdir()
    (external / "game.exe").write_bytes(b"external")
    (root / "link").symlink_to(external, target_is_directory=True)
    with pytest.raises(update.UpdateAssessmentError, match="symlink"):
        update.snapshot_installation(
            root, {"files": [{"path": "link/game.exe"}]}, blob_store=tmp_path / "blobs"
        )
    (root / "game.exe").symlink_to(external / "game.exe")
    with pytest.raises(update.UpdateAssessmentError, match="symlink"):
        update.snapshot_installation(
            root, {"files": [{"path": "game.exe"}]}, blob_store=tmp_path / "blobs"
        )


def test_snapshot_root_move_does_not_change_content_identity(tmp_path):
    first = snap(tmp_path / "a")
    second = snap(tmp_path / "b")
    assert first["snapshot_id"] == second["snapshot_id"]


def test_tampered_snapshot_manifest_rejected(tmp_path):
    first = snap(tmp_path)
    bad = copy.deepcopy(first)
    bad["files"][0]["sha256"] = "0" * 64
    with pytest.raises(update.UpdateAssessmentError, match="identity differs"):
        update.assess_update(first, bad)


def test_added_selection_is_not_claimed_to_be_newly_installed(tmp_path):
    first = snap(tmp_path / "a")
    root = tmp_path / "b"
    root.mkdir()
    selected(root)
    selection = selected(root, "new.dat", b"data")
    selection["files"].append({"path": "AoE2DE_s.exe"})
    second = update.snapshot_installation(root, selection, blob_store=tmp_path / "blobs")
    changes = update.assess_update(first, second)["changed_files"]
    assert changes[0]["change"] == "not_in_previous_selection"


def test_bounds_and_expected_pin_enforced_before_reading_large_file(tmp_path):
    root = tmp_path / "install"
    root.mkdir()
    selection = selected(root)
    with pytest.raises(update.UpdateAssessmentError, match="max_total_bytes"):
        update.snapshot_installation(
            root, selection, blob_store=tmp_path / "blobs", max_total_bytes=1
        )
    selection["files"][0]["expected"] = {"bytes": 5, "sha256": "0" * 64}
    with pytest.raises(update.UpdateAssessmentError, match="supplied pin"):
        update.snapshot_installation(root, selection, blob_store=tmp_path / "blobs")


def test_acquired_blob_tampering_before_publication_rejected(tmp_path, monkeypatch):
    root = tmp_path / "install"
    root.mkdir()
    selection = selected(root)
    blobs = tmp_path / "blobs"
    original = update._read_selected
    reads = 0

    def corrupt(*args, **kwargs):
        nonlocal reads
        result = original(*args, **kwargs)
        if Path(args[0]) == root:
            reads += 1
            if reads == 3:
                blob = next(path for path in blobs.iterdir() if not path.name.startswith("."))
                blob.chmod(0o644)
                blob.write_bytes(b"wrong")
        return result

    monkeypatch.setattr(update, "_read_selected", corrupt)
    with pytest.raises(update.UpdateAssessmentError, match="blob changed"):
        update.snapshot_installation(root, selection, blob_store=blobs)
