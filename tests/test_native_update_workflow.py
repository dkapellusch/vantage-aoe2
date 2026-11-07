"""The update runner preserves candidates, failure evidence and old selection."""

import copy
import json

import pytest

from vantage.native_conversion import pin
from vantage.native_engine_update import snapshot_installation
from vantage.native_update_workflow import (
    UpdateWorkflowError,
    load_pin,
    plan_component_reuse,
    run_workflow,
)


def write(path, value):
    path.write_text(json.dumps(value))
    return pin(path)


def setup_recipe(tmp_path, role="native_code"):
    install = tmp_path / "install"
    install.mkdir()
    (install / "input.bin").write_bytes(b"before")
    selection = {"files": [{"path": "input.bin", "roles": [role]}]}
    previous = snapshot_installation(install, selection, blob_store=tmp_path / "blobs")
    recipe = {
        "kind": "vantage_native_update_workflow_recipe_v1",
        "previous_snapshot": write(tmp_path / "previous.json", previous),
        "selection": write(tmp_path / "selection.json", selection),
        "installation_root": str(install),
        "blob_store": str(tmp_path / "blobs"),
    }
    return recipe, previous, install


def component(**updates):
    return {
        "name": "engine",
        "component_id": "engine-identity",
        "dependency_closure_complete": True,
        "dependencies": ["input.bin"],
        **updates,
    }


def test_unchanged_runs_inventory_without_discovery_or_activation(tmp_path):
    recipe, previous, _ = setup_recipe(tmp_path)
    recipe["components"] = [component()]
    result = run_workflow(recipe, tmp_path / "output", execute=True)
    assert result["assessment"] == "no_work"
    assert result["candidate_snapshot_id"] == previous["snapshot_id"]
    assert result["component_reuse"][0]["decision"] == "reuse_exact_inputs"
    assert not result["candidate_qualified"] and not result["supported"]
    assert not result["activation_performed"] and not result["registry_selection_changed"]
    assert (
        json.loads((tmp_path / "output/snapshot.json").read_text())["acquisition"]["new_blob_bytes"]
        == 0
    )


@pytest.mark.parametrize(
    "updates",
    [{"dependencies": []}, {"dependency_closure_complete": False}, {"dependencies": ["missing"]}],
)
def test_unproven_or_missing_closure_cannot_reuse(tmp_path, updates):
    _, previous, _ = setup_recipe(tmp_path)
    result = plan_component_reuse(previous, previous, [component(**updates)])
    assert result[0]["decision"] == "rebuild_or_review"


def test_changed_dependency_requires_work(tmp_path):
    recipe, previous, install = setup_recipe(tmp_path)
    (install / "input.bin").write_bytes(b"after")
    selection = load_pin(recipe["selection"])
    candidate = snapshot_installation(install, selection, blob_store=tmp_path / "blobs")
    result = plan_component_reuse(previous, candidate, [component()])
    assert result[0]["reasons"] == ["dependency_changed:input.bin"]


def test_native_update_without_discovery_blocks_even_with_execute(tmp_path):
    recipe, _, install = setup_recipe(tmp_path)
    (install / "input.bin").write_bytes(b"after")
    recipe["cases"] = [{"name": "must_not_run"}]
    result = run_workflow(recipe, tmp_path / "output", execute=True)
    assert result["stages"][-1]["status"] == "blocked_by_discovery"
    assert result["replay_experiments"] == []
    assert not (tmp_path / "output/cache").exists()


def test_presentation_change_skips_native_discovery_but_not_qualification(tmp_path):
    recipe, _, install = setup_recipe(tmp_path, "presentation")
    (install / "input.bin").write_bytes(b"after")
    result = run_workflow(recipe, tmp_path / "output")
    assert result["stages"][1]["status"] == "presentation_only_no_native_discovery"
    assert not result["supported"] and not result["candidate_qualified"]


def test_binding_discovery_failure_captures_rejection_without_worker(tmp_path, monkeypatch):
    recipe, _, install = setup_recipe(tmp_path)
    (install / "input.bin").write_bytes(b"after")
    manifest = write(tmp_path / "manifest.json", {"not": "a manifest"})
    recipe["bindings"] = {"manifest": manifest, "image": pin(install / "input.bin")}
    result = run_workflow(recipe, tmp_path / "output", execute=True)
    assert result["discovery"] == "rejected"
    assert result["discovery_error"] == "Unknown binding manifest"
    assert not (tmp_path / "output/generated_bindings.h").exists()
    assert not (tmp_path / "output/cache").exists()


def test_input_mutation_rejected(tmp_path):
    recipe, _, _ = setup_recipe(tmp_path)
    (tmp_path / "selection.json").write_text("{}")
    with pytest.raises(UpdateWorkflowError, match="changed"):
        run_workflow(recipe, tmp_path / "output")


def test_evidence_directory_cannot_be_overwritten(tmp_path):
    recipe, _, _ = setup_recipe(tmp_path)
    run_workflow(recipe, tmp_path / "output")
    before = (tmp_path / "output/result.json").read_bytes()
    with pytest.raises(FileExistsError):
        run_workflow(recipe, tmp_path / "output")
    assert (tmp_path / "output/result.json").read_bytes() == before


@pytest.mark.parametrize(
    "updates", [{"dependency_closure_complete": 1}, {"dependencies": ["input.bin", "input.bin"]}]
)
def test_rejects_ambiguous_component_contract(tmp_path, updates):
    _, previous, _ = setup_recipe(tmp_path)
    with pytest.raises(UpdateWorkflowError):
        plan_component_reuse(previous, previous, [component(**updates)])


def test_result_claims_cannot_promote_or_activate(tmp_path):
    recipe, _, install = setup_recipe(tmp_path, "presentation")
    (install / "input.bin").write_bytes(b"after")
    recipe.update(supported=True, candidate_qualified=True, activate=True)
    result = run_workflow(copy.deepcopy(recipe), tmp_path / "output")
    assert not result["supported"]
    assert not result["candidate_qualified"]
    assert not result["activation_performed"]


@pytest.mark.parametrize("outcome", ["ready", "failed", "validation_error"])
def test_experimental_case_receipts_do_not_promote(tmp_path, monkeypatch, outcome):
    from vantage import native_engine_v32, native_update_workflow

    recipe, _, install = setup_recipe(tmp_path, "presentation")
    (install / "input.bin").write_bytes(b"after")
    recipe["registry"] = write(tmp_path / "registry.json", {})
    recipe["cases"] = [{"name": "control", "replay": pin(install / "input.bin")}]
    monkeypatch.setattr(native_update_workflow.EngineRegistry, "load", lambda *args: object())

    class Result:
        def to_json(self):
            return {"status": outcome}

    class FakeEngine:
        def __init__(self, *args, **kwargs):
            pass

        def convert(self, request):
            if outcome == "validation_error":
                raise ValueError("changed during post-worker validation")
            return Result()

    monkeypatch.setattr(native_engine_v32, "V32Engine", FakeEngine)
    result = run_workflow(recipe, tmp_path / "output", execute=True)
    expected = "validation_failed" if outcome == "validation_error" else outcome
    assert result["replay_experiments"][0]["status"] == expected
    assert not result["candidate_qualified"] and not result["supported"]
    assert not result["activation_performed"]
    assert json.loads((tmp_path / "output/case_control.json").read_text())["status"] == expected
