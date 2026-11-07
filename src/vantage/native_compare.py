"""Compare closed native replay captures; never launch a worker or accept a VREC.

Only emitted projections, schemas, updates and terminal observations are compared.
Readability counters and two host timers are reported separately. This cannot
establish equality of unobserved simulation state or correctness of a replay.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from collections import Counter
from itertools import zip_longest
from pathlib import Path
from typing import TYPE_CHECKING

from .native_bootstrap_policy import FRAME_STAGES, NORMALIZE, is_positive_first, positive_plan
from .native_conversion import pin, terminal_evidence_for_input

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path
    from typing import TYPE_CHECKING, Any


TERMINAL_STAGES = {
    "native_sync_stopped",
    "native_player_checksum_projection",
    "native_prefix_sync",
    "native_recording_eof_admitted",
    "native_original_terminal_status_admitted",
    "native_replay_terminal_state",
    "native_simulation_prefix_complete",
    "owned_recording_postgame_close",
}
DIAGNOSTICS: dict[Any, Any] = {
    "native_research_frame": ("readability_queries", "readability_regions"),
    "native_simulation_prefix_complete": (
        "native_update_seconds",
        "loop_and_projection_seconds",
    ),
}
SCHEMAS = {
    name.replace("_frame", "_projection_schema")
    for name in FRAME_STAGES
    if name not in {"native_entity_frame", "native_entity_presentation_frame"}
}
INITIAL_DATA = {
    "native_technology_catalog_schema",
    "native_sprite_catalog",
    "native_entity_saved_projection",
    "native_saved_map_projection",
}


class CaptureError(ValueError):
    """Invalid, incomplete, changed or differing capture evidence."""


def require(condition: Any, message: str) -> None:
    if not condition:
        raise CaptureError(message)


def unique_object(pairs: list[Any]) -> dict[Any, Any]:
    result = {}
    for key, value in pairs:
        require(key not in result, f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def reject_constant(value: str) -> None:
    raise CaptureError(f"Nonfinite JSON constant: {value}")


def decode(raw: Any) -> Any:
    return json.loads(raw, object_pairs_hook=unique_object, parse_constant=reject_constant)


def canonical(value: Any) -> bytes:
    # Preserves boolean/integer distinctions and every encoded float-bit integer.
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def difference(left: Any, right: Any, path: str = "$") -> Any:
    if type(left) is not type(right):
        return dict(path=path, left=repr(left)[:200], right=repr(right)[:200])
    if isinstance(left, dict):
        if left.keys() != right.keys():
            return dict(path=path, left_keys=sorted(left), right_keys=sorted(right))
        for key in left:
            result = difference(left[key], right[key], f"{path}.{key}")
            if result:
                return result
    elif isinstance(left, list):
        if len(left) != len(right):
            return dict(path=path, left_length=len(left), right_length=len(right))
        for index, (old, new) in enumerate(zip(left, right, strict=True)):
            result = difference(old, new, f"{path}[{index}]")
            if result:
                return result
    elif left != right:
        return dict(path=path, left=repr(left)[:200], right=repr(right)[:200])
    return None


class Capture:
    def __init__(self, job: Path, *, allow_failed_process_receipt: Any = False) -> None:
        self.job = Path(job).resolve(strict=True)
        self.log = self.job / "native.stdout.log"
        self.receipt_path = self.job / "execution.json"
        self.diagnostic_process_receipt = False
        if not self.receipt_path.exists() and allow_failed_process_receipt:
            self.receipt_path = self.job / "native.process-exit.json"
            self.diagnostic_process_receipt = True
        self.descriptor_path = self.job / "source/descriptor.json"
        self.inputs = [pin(path) for path in (self.log, self.receipt_path, self.descriptor_path)]
        self.receipt = decode(self.receipt_path.read_bytes())
        self.descriptor = decode(self.descriptor_path.read_bytes())
        require(
            type(self.receipt) is dict and type(self.descriptor) is dict,
            "Receipt and descriptor must be objects",
        )
        require(
            self.receipt.get("receipt_kind") == "ordinary_owned_subprocess"
            and type(self.receipt.get("exit_code")) is int
            and self.receipt["exit_code"] in (0, 1)
            and self.receipt.get("timed_out") is False
            and self.receipt.get("cancelled") is False
            and self.receipt.get("stdout_sha256") == self.inputs[0]["sha256"],
            "Closed native receipt rejected",
        )
        if self.diagnostic_process_receipt:
            require(
                self.receipt["exit_code"] == 1
                and (
                    self.receipt.get("all_input_pins_unchanged") is None
                    or self.receipt.get("all_input_pins_unchanged") is True
                ),
                "Diagnostic-only failed process receipt rejected",
            )
        else:
            require(
                self.receipt.get("all_input_pins_unchanged") is True,
                "Input stability receipt rejected",
            )
        self.positive = is_positive_first(self.descriptor)
        self.plan = positive_plan(self.descriptor) if self.positive else None
        for key in ("recording_sha256", "inflated_save_sha256"):
            require(
                type(self.descriptor.get(key)) is str
                and re.fullmatch(r"[0-9a-f]{64}", self.descriptor[key]),
                f"Descriptor identity missing: {key}",
            )
        require(
            type(self.descriptor.get("recording_bytes")) is int
            and self.descriptor["recording_bytes"] > 0,
            "Recording byte length rejected",
        )
        self.counts: Counter[Any] = Counter()
        self.ignored: Counter[Any] = Counter()
        self.diagnostics: dict[Any, Any] = {}
        self.terminal: dict[Any, Any] = {}
        self.recoveries: list[Any] = []
        self.updates, self.boundaries, self.pending = 0, 0, 0
        self.clock: Any = 0
        self.digest = hashlib.sha256()
        self.checksums: list[Any] = []
        self.complete = False
        self.technology_catalogs, self.success_rows = 0, 0
        self.last_status = 0
        self.preferred_base = None

    def _diagnostics(self, event: dict[Any, Any]) -> None:
        stage = event.get("stage")
        for field in DIAGNOSTICS.get(stage, ()):
            require(field in event, f"Missing diagnostic: {stage}.{field}")
            value = event.pop(field)
            require(
                type(value) in (int, float) and math.isfinite(value) and value >= 0,
                f"Invalid diagnostic: {stage}.{field}",
            )
            if stage == "native_research_frame":
                require(type(value) is int, "Readability counter must be an integer")
            key = f"{stage}.{field}"
            stats = self.diagnostics.setdefault(
                key, dict(count=0, minimum=value, maximum=value, total=0, digest=hashlib.sha256())
            )
            stats["count"] += 1
            stats["minimum"] = min(stats["minimum"], value)
            stats["maximum"] = max(stats["maximum"], value)
            stats["total"] += value
            stats["digest"].update(canonical(value) + b"\n")

    def _accept(self, event: dict[Any, Any]) -> None:
        stage = event.get("stage")
        if stage == "native_replay_bootstrap_policy":
            require(
                self.plan is not None
                and self.updates == self.boundaries == self.pending == 0
                and self.counts[stage] == 0
                and canonical(event) == canonical(self.plan.declaration()),
                "Descriptor-bound bootstrap declaration rejected",
            )
        if self.positive and stage in (*FRAME_STAGES, "native_world_update_returned"):
            require(
                self.counts["native_replay_bootstrap_policy"] == 1,
                "Missing preceding bootstrap declaration",
            )
        require(
            "native_sync_stopped" not in self.terminal or stage not in FRAME_STAGES,
            "Frame after sync stop",
        )
        if stage == "native_world_update_returned":
            preceding = 1 if self.updates == 0 else self.updates + int(self.positive)
            require(
                not self.pending and self.boundaries == preceding,
                "Missing initial or preceding projection boundary",
            )
            require("native_sync_stopped" not in self.terminal, "Update after sync stop")
            require(self.last_status == 0, "Update after game terminal status")
            require(
                type(event.get("ordinal")) is int and event["ordinal"] == self.updates + 1,
                "Update ordinal gap or duplicate",
            )
            clock, delta = event.get("world_time_ms"), event.get("recorded_delta_ms")
            if not self.positive and self.updates < 2:
                # Legacy printf omits delta on its first two returned updates.
                require("recorded_delta_ms" not in event, "Unexpected legacy delta field")
                delta = self.descriptor["bootstrap_syncs"][self.updates].get("delta_ms")
            if self.updates < 2:
                require(
                    clock == self.descriptor["bootstrap_syncs"][self.updates].get("time_ms"),
                    "Bootstrap update differs from descriptor clock",
                )
                if self.plan is not None:
                    expected_cursor = (
                        self.plan.first_update_cursor
                        if self.updates == 0
                        else self.plan.second_update_cursor
                    )
                    require(
                        event.get("file_position") == expected_cursor,
                        "Bootstrap update cursor differs from descriptor",
                    )
            require(
                type(clock) is int
                and type(delta) is int
                and clock == self.clock + delta
                and (delta > 0 or (not self.positive and self.updates == 0 and delta == 0))
                and clock <= self.descriptor["final_clock_ms"],
                "Update clock/delta rejected",
            )
            require(
                type(event.get("status")) is int and event["status"] in (0, 1),
                "Update status rejected",
            )
            require(
                type(event.get("native_log_ms")) is int
                and event["native_log_ms"] == clock
                and all(
                    type(event.get(key)) is int and 0 <= event[key] <= 0xFFFFFFFF
                    for key in ("file_position", "clock_cycles")
                ),
                "Update diagnostic carriers rejected",
            )
            require(
                event["status"] == 0 or clock == self.descriptor["final_clock_ms"],
                "Early game terminal status",
            )
            self.updates, self.clock = self.updates + 1, clock
            self.last_status = event["status"]
        elif stage in FRAME_STAGES:
            schema = stage.replace("_frame", "_projection_schema")
            if schema in SCHEMAS:
                require(self.counts[schema] == 1, f"Missing preceding schema: {schema}")
            require(stage == FRAME_STAGES[self.pending], "Projection stream order differs")
            require(
                type(event.get("time_ms")) is int and event["time_ms"] == self.clock,
                "Projection clock differs from actual update",
            )
            require(
                event.get("kind") == ("snapshot" if self.boundaries == 0 else "delta"),
                "Projection snapshot/delta kind differs",
            )
            if self.pending == 0:
                preceding = 0 if self.updates == 0 else self.updates - 1 + int(self.positive)
                require(self.boundaries == preceding, "Extra projection boundary")
            self.pending += 1
            if self.pending == len(FRAME_STAGES):
                self.boundaries, self.pending = self.boundaries + 1, 0
        elif stage == "native_technology_catalog":
            require(
                self.boundaries == 0 and self.counts["native_technology_catalog_schema"] == 1,
                "Late technology catalog or absent schema",
            )
            self.technology_catalogs += 1
        elif stage in INITIAL_DATA or stage in SCHEMAS:
            require(
                self.updates == 0 and self.boundaries == 0,
                "Late schema or initial projection/catalog",
            )
        elif stage == "native_player_checksum_projection":
            require("native_sync_stopped" in self.terminal, "Checksum row before sync stop")
            require("native_prefix_sync" not in self.terminal, "Checksum row after failure")
            index, fields = event.get("world_index"), event.get("fields")
            require(
                type(index) is int
                and index == len(self.checksums)
                and type(fields) is list
                and len(fields) == 11
                and all(type(value) is int and 0 <= value <= 0xFFFFFFFF for value in fields),
                "Checksum row index or fields rejected",
            )
            self.checksums.append(event)
        elif stage in TERMINAL_STAGES:
            require(stage not in self.terminal, f"Duplicate terminal observation: {stage}")
            if stage == "native_prefix_sync":
                require(
                    "native_sync_stopped" in self.terminal
                    and len(self.checksums) == self.descriptor["world_player_count"],
                    "Failure before stop or complete checksum rows",
                )
            self.terminal[stage] = event.copy()

    def records(self) -> Iterator[Any]:
        with self.log.open("rb") as stream:
            for number, raw in enumerate(stream, 1):
                text = raw.decode("utf-8")
                match = NORMALIZE.match(text)
                if match:
                    self.recoveries.append(dict(line=number, prefix=match[0]))
                    text = text[match.end() :]
                if not text.strip():
                    continue
                try:
                    event = decode(text)
                    require(type(event) is dict, "Non-object native event")
                    stage = event.get("stage", "")
                    require(type(stage) is str, "Invalid stage")
                    # Encode even ignored rows to reject overflowed/nonfinite JSON numbers.
                    canonical(event)
                except (ValueError, TypeError) as error:
                    raise CaptureError(f"{self.log}:{number}: {error}") from error
                failure = "error" in event or event.get("ok") is False
                require(
                    not failure or (stage == "native_prefix_sync" and event.get("error") == 207),
                    f"Unexpected native failure at line {number}",
                )
                success = event.get("ok") is True and event.get("scope") == (
                    "native_simulation_prefix_and_entity_projection"
                )
                selected = (
                    stage in FRAME_STAGES
                    or stage in TERMINAL_STAGES
                    or stage == "native_world_update_returned"
                    or stage == "native_technology_catalog"
                    or stage == "native_replay_bootstrap_policy"
                    or stage in INITIAL_DATA
                    or stage.endswith("_projection_schema")
                    or success
                )
                require(
                    selected
                    or not (
                        stage.startswith("native_")
                        and stage.endswith(("_frame", "_catalog", "_schema", "_projection"))
                    ),
                    f"Unrecognized output stream: {stage}",
                )
                if not selected:
                    self.ignored[stage] += 1
                    continue
                if success:
                    self.success_rows += 1
                    # ASLR admission is unrelated to observable replay data.
                    require(
                        type(event.get("preferred_base")) is bool,
                        "Preferred-base diagnostic rejected",
                    )
                    self.preferred_base = event.pop("preferred_base")
                self._accept(event)
                self._diagnostics(event)
                payload = canonical(event)
                self.digest.update(payload + b"\n")
                self.counts[stage or "terminal_success"] += 1
                yield number, event, payload
        self._finish()

    def _finish(self) -> None:
        require(
            self.updates > 0
            and not self.pending
            and self.boundaries == self.updates + int(self.positive),
            "Incomplete projection boundary or absent updates",
        )
        require(self.technology_catalogs == 1, "Missing or duplicate technology catalog")
        require(
            all(self.counts[name] == 1 for name in SCHEMAS | INITIAL_DATA),
            "Missing or duplicate schema/initial projection/catalog",
        )
        if self.receipt["exit_code"] == 0:
            terminal_evidence_for_input(self.log, self.receipt_path, self.descriptor)
            require(self.success_rows == 1, "Successful terminal row absent or duplicate")
            self.outcome = "closed_successful_capture"
        else:
            stop = self.terminal.get("native_sync_stopped", {})
            failure = self.terminal.get("native_prefix_sync", {})
            require(
                type(stop.get("status")) is int
                and stop["status"] == 3
                and type(stop.get("world_time_ms")) is int
                and stop["world_time_ms"] == self.clock
                and self.last_status == 0
                and type(stop.get("ignore_checksum_global")) is int
                and stop["ignore_checksum_global"] == 0
                and type(failure.get("error")) is int
                and failure["error"] == 207
                and failure.get("ok") is False
                and len(self.checksums) == self.descriptor["world_player_count"]
                and set(self.terminal) == {"native_sync_stopped", "native_prefix_sync"}
                and self.success_rows == 0,
                "Checksum failure closure rejected",
            )
            self.outcome = "closed_checksum_failure_not_playback_success"
        require(
            [pin(Path(row["path"])) for row in self.inputs] == self.inputs,
            "Capture inputs changed during comparison",
        )
        self.complete = True

    def summary(self) -> dict[Any, Any]:
        require(self.complete, "Capture scan did not reach validated closure")
        return dict(
            inputs=self.inputs,
            outcome=self.outcome,
            returned_updates=self.updates,
            boundaries=self.boundaries,
            end_ms=self.clock,
            counts=dict(self.counts),
            observed_data_sha256=self.digest.hexdigest(),
            ignored_stages=dict(self.ignored),
            diagnostics={
                key: dict(value, digest=value["digest"].hexdigest())
                for key, value in self.diagnostics.items()
            },
            preferred_base_diagnostic=self.preferred_base,
            process_receipt_only=self.diagnostic_process_receipt,
            receipt_claims_source_input_stability=(
                self.receipt.get("all_input_pins_unchanged") is True
            ),
            recovered_known_resign_prefixes=self.recoveries,
        )


def compare_jobs(
    left_job: Path, right_job: Path, *, allow_failed_process_receipt: Any = False
) -> Any:
    sources = [
        pin(Path(__file__).with_name(name))
        for name in (
            "native_compare.py",
            "native_conversion.py",
            "native_bootstrap_policy.py",
            "native_bootstrap_admission.py",
        )
    ]
    left, right = (
        Capture(job, allow_failed_process_receipt=allow_failed_process_receipt)
        for job in (left_job, right_job)
    )
    require(
        canonical(left.descriptor) == canonical(right.descriptor),
        "Input descriptor identity differs",
    )
    absent: Any = object()
    for before, after in zip_longest(left.records(), right.records(), fillvalue=absent):
        require(before is not absent and after is not absent, "Selected record count differs")
        if before[2] != after[2]:
            detail = dict(
                left_line=before[0],
                right_line=after[0],
                stage=before[1].get("stage"),
                difference=difference(before[1], after[1]),
            )
            raise CaptureError(json.dumps(detail))
    require(
        [pin(Path(row["path"])) for row in sources] == sources,
        "Comparator sources changed during comparison",
    )
    return dict(
        status="equal_emitted_replay_data_and_terminal_observations",
        source_pins=sources,
        independent_capture_paths=left.log != right.log,
        left=left.summary(),
        right=right.summary(),
        checksum_failure_is_success=False,
        conversion_accepted=False,
        source_bundle_profile_engine_compatibility_proved=False,
        private_simulation_state_equivalence_proved=False,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--left-job", type=Path, required=True)
    parser.add_argument("--right-job", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument(
        "--allow-closed-failure-receipt",
        action="store_true",
        help="Allow a failed process receipt without input-stability proof; "
        "diagnostic-only comparison",
    )
    args = parser.parse_args()
    try:
        result = compare_jobs(
            args.left_job,
            args.right_job,
            allow_failed_process_receipt=args.allow_closed_failure_receipt,
        )
        code = 0
    except ValueError as error:
        result = dict(status="comparison_rejected", error=str(error), conversion_accepted=False)
        code = 1
    with args.out.open("x") as stream:
        json.dump(result, stream, indent=2)
        stream.write("\n")
    print(json.dumps(pin(args.out)))
    raise SystemExit(code)


if __name__ == "__main__":
    main()
