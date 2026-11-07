"""Bound runs of published-field differences in normalized retained observations.

Persistence means consecutive comparable published samples. It does not imply
persistent native state, authenticated cross-run identity or checksum causation.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .native_compare import canonical
from .native_reference_compare import Observations, require

if TYPE_CHECKING:
    from pathlib import Path
    from typing import TYPE_CHECKING, Any


def difference_runs(
    reference: Path, native: Path, *, minimum_samples: Any = 2, example_limit: Any = 12
) -> dict[Any, Any]:
    require(type(minimum_samples) is int and minimum_samples >= 2, "Invalid persistence bound")
    require(type(example_limit) is int and 1 <= example_limit <= 100, "Invalid example bound")
    left, right = Observations(reference), Observations(native)
    require(
        left.header["replay_sha256"] == right.header["replay_sha256"], "Replay identity differs"
    )
    fields = sorted(
        k for k, v in left.header["fields"].items() if right.header["fields"].get(k) == v
    )
    require(fields, "No comparable fields")
    active: dict[Any, Any] = {}
    completed: list[Any] = []
    samples, compared, uncertain = 0, 0, 0
    first_persistent = None
    total_runs = 0

    def close(key: Any, reason: Any, at: Any = None) -> None:
        nonlocal total_runs, first_persistent
        run = active.pop(key)
        run.update(
            end_reason=reason,
            next_observation_ms=at,
            persistent_at_sample_cadence=run["samples"] >= minimum_samples,
        )
        total_runs += 1
        if run["persistent_at_sample_cadence"] and (
            first_persistent is None
            or (run["first_ms"], run["entity_id"], run["field"])
            < (
                first_persistent["first_ms"],
                first_persistent["entity_id"],
                first_persistent["field"],
            )
        ):
            first_persistent = run
        if len(completed) < example_limit:
            completed.append(run)

    li, ri = iter(left), iter(right)
    a, b = next(li, None), next(ri, None)
    while a is not None and b is not None:
        if a["time_ms"] != b["time_ms"]:
            for key in list(active):
                close(
                    key, "unjoined_clock_interrupts_comparability", min(a["time_ms"], b["time_ms"])
                )
            if a["time_ms"] < b["time_ms"]:
                a = next(li, None)
            else:
                b = next(ri, None)
            continue
        samples += 1
        uncertain += int(a["phase"] != b["phase"] or a["phase"] == "unknown")
        available, mismatches = set(), set()
        for eid in sorted(a["entities"].keys() & b["entities"].keys(), key=int):
            ae, be = a["entities"][eid], b["entities"][eid]
            for field in fields:
                if field not in ae or field not in be:
                    continue
                key = (eid, field)
                compared += 1
                available.add(key)
                if canonical(ae[field]) == canonical(be[field]):
                    continue
                mismatches.add(key)
                if key not in active:
                    active[key] = dict(
                        entity_id=int(eid),
                        field=field,
                        first_ms=a["time_ms"],
                        last_ms=a["time_ms"],
                        samples=0,
                        first_reference=ae[field],
                        first_native=be[field],
                    )
                active[key]["samples"] += 1
                active[key]["last_ms"] = a["time_ms"]
                active[key]["last_reference"] = ae[field]
                active[key]["last_native"] = be[field]
        for key in list(active.keys() - mismatches):
            close(
                key,
                "shared_field_matches" if key in available else "field_or_entity_unavailable",
                a["time_ms"],
            )
        a, b = next(li, None), next(ri, None)
    for key in list(active):
        close(key, "window_or_stream_end")
    # Validate remaining input rows and close file handles even when no clocks join.
    for _ in li:
        pass
    for _ in ri:
        pass
    left.unchanged()
    right.unchanged()
    return {
        "schema": "vantage-reference-difference-runs-v1",
        "shared_samples": samples,
        "field_comparisons": compared,
        "phase_uncertain_samples": uncertain,
        "minimum_samples_for_persistence": minimum_samples,
        "total_field_difference_runs": total_runs,
        "bounded_run_examples": completed,
        "first_persistent_field_difference": first_persistent,
        "reference": left.pin,
        "native": right.pin,
        "simulation_cause_proven": False,
        "limits": [
            "Persistence is measured only at consecutive comparable published samples",
            "Unavailable fields and unjoined clocks interrupt comparability",
            "One sample can cover multiple native changes; a transient difference may matter",
            "Publication phase, historical replay authentication and allocation identity "
            "remain separate",
        ],
    }
