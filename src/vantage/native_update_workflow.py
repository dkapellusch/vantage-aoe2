"""Stage update discovery and experimental replay checks without activation.

All inputs are explicit. Component reuse requires an exact, nonempty dependency
closure. Runtime receipts record experiments, not snapshot-bound support.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import TYPE_CHECKING

from .native_conversion import pin
from .native_engine_bindings import discover, generate_header
from .native_engine_protocol import ConversionRequest, content_digest
from .native_engine_registry import EngineRegistry
from .native_engine_update import assess_update, snapshot_installation, validate_snapshot

if TYPE_CHECKING:
    from pathlib import Path
    from typing import TYPE_CHECKING, Any


class UpdateWorkflowError(ValueError):
    pass


def require(condition: Any, message: str) -> None:
    if not condition:
        raise UpdateWorkflowError(message)


def load_pin(
    expected: Any,
) -> Any:
    require(
        type(expected) is dict and set(expected) == {"path", "bytes", "sha256"},
        "An exact input pin is required",
    )
    path = Path(expected["path"])
    require(
        path.is_absolute() and path.resolve(strict=True) == path, "Canonical input path required"
    )
    require(pin(path) == expected, "Workflow input changed")
    raw = path.read_bytes()
    require(pin(path) == expected, "Workflow input changed during read")
    return json.loads(raw)


def plan_component_reuse(
    previous: Any,
    candidate: Any,
    components: Any,
) -> Any:
    """A component may be reused only with the same complete declared inputs.

    Completeness itself remains an explicit package-author assertion. Unknown
    dependencies cannot be converted into an empty, vacuously passing closure.
    """
    validate_snapshot(previous)
    validate_snapshot(candidate)
    require(type(components) is list, "Components must be a list")
    before, after = ({r["name"]: r for r in doc["files"]} for doc in (previous, candidate))
    seen, result = set(), []
    for component in components:
        require(
            type(component) is dict
            and set(component)
            == {"name", "component_id", "dependency_closure_complete", "dependencies"},
            "Explicit component identity and dependency closure required",
        )
        name, deps = component["name"], component["dependencies"]
        require(
            type(name) is str and name and name not in seen, "Distinct component names required"
        )
        require(
            type(component["component_id"]) is str and component["component_id"],
            "Component identity required",
        )
        require(
            type(component["dependency_closure_complete"]) is bool,
            "Closure completeness must be boolean",
        )
        require(
            type(deps) is list
            and all(type(d) is str for d in deps)
            and len(set(deps)) == len(deps),
            "Distinct dependency names required",
        )
        seen.add(name)
        reasons = []
        if not deps or not component["dependency_closure_complete"]:
            reasons.append("dependency_closure_unproven")
        for dep in deps:
            left, right = before.get(dep), after.get(dep)
            if left is None or right is None:
                reasons.append(f"dependency_not_in_both_snapshots:{dep}")
            elif any(left[k] != right[k] for k in ("bytes", "sha256", "roles")):
                reasons.append(f"dependency_changed:{dep}")
        result.append(
            {
                "name": name,
                "component_id": component["component_id"],
                "decision": "rebuild_or_review" if reasons else "reuse_exact_inputs",
                "reasons": reasons,
                "dependencies": deps,
                "closure_basis": "explicit_package_declaration",
            }
        )
    return result


def _write(path: Path, value: dict[Any, Any]) -> None:
    with path.open("x") as output:
        json.dump(value, output, sort_keys=True, indent=2, allow_nan=False)
        output.write("\n")


def run_workflow(
    recipe: dict[Any, Any], output_dir: Path, *, execute: Any = False
) -> dict[Any, Any]:
    """Acquire, assess, discover, then run explicit experimental cases in order.

    Failed discovery prevents native worker construction. No report produced by
    this command can promote a registry entry or declare supported mode.
    """
    require(recipe.get("kind") == "vantage_native_update_workflow_recipe_v1", "Unsupported recipe")
    require(type(execute) is bool, "Execution opt-in must be boolean")
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=False)
    previous = load_pin(recipe["previous_snapshot"])
    selection = load_pin(recipe["selection"])
    candidate = snapshot_installation(
        Path(recipe["installation_root"]), selection, blob_store=Path(recipe["blob_store"])
    )
    _write(output_dir / "snapshot.json", candidate)
    assessment = assess_update(previous, candidate)
    _write(output_dir / "assessment.json", assessment)
    result = {
        "kind": "vantage_native_update_workflow_result_v1",
        "recipe_id": content_digest(recipe),
        "previous_snapshot_id": previous["snapshot_id"],
        "candidate_snapshot_id": candidate["snapshot_id"],
        "assessment": assessment["assessment"],
        "component_reuse": plan_component_reuse(previous, candidate, recipe.get("components", [])),
        "stages": [{"stage": "inventory", "status": "passed"}],
        "discovery": "not_requested",
        "replay_experiments": [],
        "candidate_qualified": False,
        "supported": False,
        "activation_performed": False,
        "registry_selection_changed": False,
        "qualification_limit": (
            "No snapshot-bound engine/corpus/reference attestation validator exists"
        ),
        "rollback": {
            "action": "retain_previous_selection",
            "previous_snapshot_id": previous["snapshot_id"],
        },
    }
    if assessment["assessment"] == "no_work":
        result["stages"].append({"stage": "discovery", "status": "unnecessary_exact_snapshot"})
        _write(output_dir / "result.json", result)
        return result
    binding = recipe.get("bindings")
    if binding:
        manifest = load_pin(binding["manifest"])
        image_pin = binding["image"]
        require(pin(Path(image_pin["path"])) == image_pin, "Candidate image changed")
        try:
            candidates = discover(manifest, image_pin["path"])
            _write(output_dir / "bindings.json", candidates)
            result["discovery"] = candidates["status"]
            if candidates["status"] == "static_candidate_table_ready":
                (output_dir / "generated_bindings.h").write_text(generate_header(candidates))
        except ValueError as error:
            result["discovery"] = "rejected"
            result["discovery_error"] = str(error)
        ready = result["discovery"] == "static_candidate_table_ready"
        result["stages"].append(
            {"stage": "discovery", "status": "passed_static_only" if ready else "rejected"}
        )
    else:
        ready = not any(role != "presentation" for role in assessment["impact_classes"])
        result["stages"].append(
            {
                "stage": "discovery",
                "status": "presentation_only_no_native_discovery"
                if ready
                else "missing_native_discovery",
            }
        )
    cases = recipe.get("cases", [])
    require(type(cases) is list, "Replay cases must be a list")
    if cases and execute and ready:
        registry_pin = recipe["registry"]
        load_pin(registry_pin)
        registry = EngineRegistry.load(Path(registry_pin["path"]), registry_pin["sha256"])
        from .native_engine_v32 import V32Engine

        names = set()
        for case in cases:
            name = case["name"]
            require(
                type(name) is str and name.isidentifier() and name not in names,
                "Distinct identifier case names required",
            )
            names.add(name)
            replay_pin = case["replay"]
            require(pin(Path(replay_pin["path"])) == replay_pin, "Replay case changed")
            request = ConversionRequest(
                Path(replay_pin["path"]),
                required_capabilities=tuple(case.get("capabilities", [])),
                allow_experimental=True,
            )
            try:
                engine = V32Engine(registry, cache_dir=output_dir / "cache" / name)
                record = engine.convert(request).to_json()
            except ValueError as error:
                record = {"status": "validation_failed", "message": str(error)}
            _write(output_dir / f"case_{name}.json", record)
            result["replay_experiments"].append(
                {
                    "name": name,
                    "status": record["status"],
                    "result": pin(output_dir / f"case_{name}.json"),
                    "snapshot_bound_support_proven": False,
                }
            )
            if record["status"] != "ready":
                break
        status = (
            "experimental_cases_ready"
            if all(r["status"] == "ready" for r in result["replay_experiments"])
            else "rejected"
        )
    else:
        status = "blocked_by_discovery" if not ready else "not_executed"
    result["stages"].append({"stage": "replay_experiments", "status": status})
    _write(output_dir / "result.json", result)
    return result


def main(argv: Any = None) -> Any:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--recipe", type=Path, required=True)
    parser.add_argument("--recipe-sha256", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--execute-experimental", action="store_true")
    args = parser.parse_args(argv)
    expected = pin(args.recipe.resolve(strict=True))
    require(expected["sha256"] == args.recipe_sha256, "Recipe hash differs")
    recipe = load_pin(expected)
    result = run_workflow(recipe, args.output_dir, execute=args.execute_experimental)
    print(json.dumps(result, indent=2))
    return (
        1
        if any(
            s["status"] in {"rejected", "missing_native_discovery", "blocked_by_discovery"}
            for s in result["stages"]
        )
        else 0
    )
