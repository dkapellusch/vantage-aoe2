"""Pinned replay scorecards; imported observations never imply a fresh run.

The manifest describes local research inputs, not distributed game assets or a
compatibility registry. Result identities exclude local paths and attempt times.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
import uuid
from itertools import zip_longest
from pathlib import Path
from typing import Any

from .native_conversion import pin

SCHEMA = "vantage_native_corpus_report_v1"
TIERS = ("metadata", "short", "checksum-only", "full")
OUTCOMES = (
    "native_game_end",
    "recording_eof",
    "checksum_rejection",
    "unsupported_input",
    "crash",
    "timeout",
    "cancelled",
    "unverified",
)


def identity(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def compare_frame_payloads(
    candidate: Path, reference: Path, *, expected_frames: int
) -> dict[Any, Any]:
    """Compare every envelope and payload using the existing VREC reader, excluding headers."""
    from .frames import read_frames

    before = [pin(candidate.resolve(strict=True)), pin(reference.resolve(strict=True))]
    count = 0
    last = None
    digest = hashlib.sha256()
    first_difference = None
    for index, (left, right) in enumerate(
        zip_longest(read_frames(candidate), read_frames(reference))
    ):
        if left != right and first_difference is None:
            first_difference = {
                "frame_index": index,
                "candidate_time_ms": left.time if left else None,
                "reference_time_ms": right.time if right else None,
            }
        if left is not None:
            count += 1
            last = left.time
            digest.update(
                bytes.fromhex(
                    identity(
                        [
                            left.time,
                            left.skipped,
                            left.patch.hex(),
                            left.reverse.hex(),
                            left.events,
                            left.commands,
                        ]
                    )
                )
            )
    if [pin(candidate.resolve()), pin(reference.resolve())] != before:
        raise ValueError("Recording changed during frame comparison")
    equal = first_difference is None and count == expected_frames
    return {
        "candidate": before[0],
        "reference": before[1],
        "frames": count,
        "end_ms": last,
        "expected_frames": expected_frames,
        "all_frame_envelopes_and_payloads_equal": equal,
        "first_difference": first_difference,
        "frame_payload_identity": digest.hexdigest(),
        "headers_compared": False,
        "general_simulation_parity_claimed": False,
    }


def check_pin(row: dict[Any, Any], root: Path) -> Path:
    if not isinstance(row, dict) or not {"path", "bytes", "sha256"} <= row.keys():
        raise ValueError("Invalid corpus input pin")
    path = Path(row["path"])
    path = path if path.is_absolute() else root / path
    actual = pin(path.resolve(strict=True))
    if (actual["bytes"], actual["sha256"]) != (row["bytes"], row["sha256"]):
        raise ValueError(f"Pinned input changed: {path}")
    return path.resolve(strict=True)


def load_manifest(path: Path) -> tuple[dict[Any, Any], Path]:
    doc = json.loads(path.read_bytes())
    if doc.get("kind") != "vantage_native_replay_corpus" or doc.get("version") != 1:
        raise ValueError("Unsupported corpus manifest")
    ids = [row["id"] for row in doc["entries"]]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate corpus entry identity")
    root = (path.parent / doc.get("root", ".")).resolve()
    for row in doc["entries"]:
        if row["expected"]["outcome"] not in OUTCOMES or row["evidence_kind"] not in (
            "native_worker_baseline",
            "source_game_reference",
        ):
            raise ValueError("Invalid corpus entry outcome or producer kind")
    return doc, root


def classify_process(
    receipt: dict[Any, Any],
    *,
    stop: dict[Any, Any] | None = None,
    failure: dict[Any, Any] | None = None,
    terminal: dict[Any, Any] | None = None,
) -> str:
    """A terminal event cannot overrule cancellation, timeout or nonzero exit."""
    if any(key in receipt and type(receipt[key]) is not bool for key in ("timed_out", "cancelled")):
        return "unverified"
    if type(receipt.get("exit_code")) is not int:
        return "unverified"
    if receipt.get("cancelled") is True:
        return "cancelled"
    if receipt.get("timed_out") is True:
        return "timeout"
    if (
        receipt.get("exit_code") == 1
        and stop
        and failure
        and type(stop.get("status")) is int
        and stop["status"] == 3
        and type(stop.get("ignore_checksum_global")) is int
        and stop["ignore_checksum_global"] == 0
        and failure.get("stage") == "native_prefix_sync"
        and type(failure.get("error")) is int
        and failure["error"] == 207
        and failure.get("ok") is False
    ):
        return "checksum_rejection"
    if receipt.get("exit_code") != 0:
        return "crash"
    if terminal:
        event = terminal.get("original_terminal_event", {})
        if (
            type(event.get("checksum_ignore_global")) is not int
            or event["checksum_ignore_global"] != 0
        ):
            return "unverified"
        reason = terminal.get("recording_end_reason")
        if reason == "native_game_end" and terminal.get("game_ended") is True:
            return "native_game_end"
        if reason == "recording_eof" and terminal.get("game_ended") is False:
            return "recording_eof"
    return "unverified"


def checksum_tail(capture: Path) -> tuple[dict[Any, Any] | None, dict[Any, Any] | None]:
    """Same bounded closed-log observation as the pipeline's checksum gate."""
    with capture.open("rb") as stream:
        stream.seek(0, 2)
        stream.seek(max(0, stream.tell() - 1024 * 1024))
        lines = stream.read().splitlines()
    stops, failures = [], []
    for line in lines:
        try:
            event = json.loads(line)
        except (ValueError, UnicodeError):
            continue
        if not isinstance(event, dict):
            continue
        if event.get("stage") == "native_sync_stopped":
            stops.append(event)
        if event.get("stage") == "native_prefix_sync" and event.get("error") == 207:
            failures.append(event)
    return (stops[0] if len(stops) == 1 else None, failures[0] if len(failures) == 1 else None)


def _observation(
    outcome: str,
    *,
    terminal: dict[Any, Any] | None = None,
    stop: dict[Any, Any] | None = None,
    frames: int | None = None,
) -> dict[Any, Any]:
    result: dict[str, Any] = {"outcome": outcome}
    if terminal:
        result.update(
            {
                "world_time_ms": terminal.get("expected_end_ms"),
                "frames": terminal.get("expected_frames"),
                "game_ended": terminal.get("game_ended"),
                "original_checksum_enforced": terminal.get("original_terminal_event", {}).get(
                    "checksum_ignore_global"
                )
                == 0
                and type(terminal.get("original_terminal_event", {}).get("checksum_ignore_global"))
                is int,
            }
        )
    if stop:
        result.update(
            {
                "world_time_ms": stop.get("world_time_ms"),
                "stop": stop,
                "original_checksum_enforced": type(stop.get("ignore_checksum_global")) is int
                and stop["ignore_checksum_global"] == 0,
            }
        )
    if frames is not None:
        result["frames"] = frames
    return result


def _expected_matches(observation: dict[Any, Any], expected: dict[Any, Any]) -> bool:
    return all(observation.get(key) == value for key, value in expected.items())


def _producer(
    entry: dict[Any, Any], root: Path, overrides: dict[Any, Any] | None = None
) -> tuple[dict[Any, Any], dict[Any, Any]]:
    source = dict(entry["producer"])
    source.update(overrides or {})
    for _name, row in source.get("pins", {}).items():
        check_pin(row, root)
    content = {
        "name": source["name"],
        "pins": {
            name: {key: row[key] for key in ("bytes", "sha256")}
            for name, row in source.get("pins", {}).items()
        },
    }
    return source, {**content, "identity": identity(content)}


def import_retained(
    entry: dict[Any, Any], root: Path, *, verify: bool
) -> tuple[dict[Any, Any], dict[Any, Any]]:
    """Read pinned historical observations; optionally revalidate their raw evidence."""
    evidence_path = check_pin(entry["evidence"], root)
    doc = json.loads(evidence_path.read_bytes())
    kind = entry["import_format"]
    details = {"evidence": pin(evidence_path), "raw_evidence_revalidated": False}
    if kind == "v32_pipeline":
        stage_path = check_pin(doc["stage"], root)
        stage = json.loads(stage_path.read_bytes())
        if stage["recording"]["sha256"] != entry["replay"]["sha256"]:
            raise ValueError("Retained stage replay differs from corpus")
        expected_source = entry["producer"]["pins"].get("source_profile")
        if expected_source and stage["profile"]["sha256"] != expected_source["sha256"]:
            raise ValueError("Retained stage producer differs from corpus")
        details["worker"] = stage["worker"]
        terminal_path = check_pin(doc["encoding"]["terminal"], root)
        terminal = json.loads(terminal_path.read_bytes())
        receipt_path = check_pin(doc["run"]["receipt"], root)
        receipt = json.loads(receipt_path.read_bytes())
        if verify:
            from .native_v32_reuse import verified_recording

            profiles = entry["producer"]["pins"]
            verified_recording(
                stage_path.parent,
                doc,
                runtime_profile=check_pin(profiles["runtime_profile"], root),
                runtime_profile_sha256=profiles["runtime_profile"]["sha256"],
                encoder_config=check_pin(profiles["encoder_config"], root),
                encoder_config_sha256=profiles["encoder_config"]["sha256"],
            )
            details["raw_evidence_revalidated"] = True
        return _observation(
            classify_process(receipt, terminal=terminal), terminal=terminal
        ), details
    if kind == "checksum_report":
        receipt_pin = doc.get("process_receipt", doc.get("receipt"))
        receipt = json.loads(check_pin(receipt_pin, root).read_bytes())
        if "stage" in receipt:
            stage_doc = json.loads(check_pin(receipt["stage"], root).read_bytes())
            details["worker"] = stage_doc["worker"]
            retained_worker = entry.get("retained_producer_worker")
            if retained_worker and stage_doc["worker"] != retained_worker:
                raise ValueError("Retained checksum worker differs from corpus")
            if stage_doc["recording"]["sha256"] != entry["replay"]["sha256"]:
                raise ValueError("Checksum receipt replay differs from corpus")
        if "descriptor" in doc:
            descriptor = json.loads(check_pin(doc["descriptor"], root).read_bytes())
            if descriptor["recording_sha256"] != entry["replay"]["sha256"]:
                raise ValueError("Checksum descriptor replay differs from corpus")
        stop = doc.get("stop", doc.get("original_stop"))
        failure = doc.get("failure")
        if verify:
            capture = check_pin(doc["capture"], root)
            actual_stop, failure = checksum_tail(capture)
            if actual_stop != stop:
                raise ValueError("Retained checksum stop differs from closed capture")
            if receipt.get("stdout_sha256") != doc["capture"]["sha256"]:
                raise ValueError("Checksum capture differs from process receipt")
            # A failed attempt must never have produced an accepted pipeline result.
            stage = (
                capture.parent.parent.parent
                if capture.parent.parent.name == "runs"
                else capture.parent
            )
            if (stage / "pipeline-result.json").exists():
                raise ValueError("Checksum rejection has an accepted pipeline result")
            details["raw_evidence_revalidated"] = True
        return _observation(
            classify_process(receipt, stop=stop, failure=failure), stop=stop
        ), details
    if kind == "legacy_terminal_inspection":
        # Historical producer: do not feed its output to V32 admission or claim a new run.
        if verify:
            for row in doc["inputs"]:
                check_pin(row, root)
            check_pin(doc["recording"], root)
            details["raw_evidence_revalidated"] = True
        outcome = (
            "native_game_end"
            if doc.get("native_game_ended") is True
            and doc.get("cursor_reached_postgame_marker") is True
            else "unverified"
        )
        return {"outcome": outcome}, details
    raise ValueError(f"Unsupported retained import format: {kind}")


def execute_v32(
    entry: dict[Any, Any],
    root: Path,
    *,
    work_root: Path,
    tier: str,
    producer: dict[Any, Any],
    runtime_timeout: float,
    encoder_timeout: float,
) -> tuple[dict[Any, Any], dict[Any, Any]]:
    """Run existing preparation/admission/encoding; no alternate success validator."""
    from .native_input import NativeInputError
    from .native_v32_admission import admit_v32_capture
    from .native_v32_encode import V32Encoder
    from .native_v32_prepare import prepare_v32_worker
    from .native_v32_runtime import V32Runtime, V32RuntimeError

    profiles = producer["pins"]
    required = ("source_profile", "runtime_profile", "encoder_config")
    paths = {name: check_pin(profiles[name], root) for name in required}
    work_root.mkdir(parents=True, exist_ok=True)
    job = work_root / f"{entry['id']}-{uuid.uuid4().hex}"
    details = {"job": str(job), "raw_evidence_revalidated": True}
    try:
        stage = prepare_v32_worker(
            check_pin(entry["replay"], root),
            job,
            profile=paths["source_profile"],
            profile_sha256=profiles["source_profile"]["sha256"],
            update_cap=entry.get("update_cap", 262144),
        )
    except NativeInputError as error:
        return {"outcome": "unsupported_input", "code": error.code}, details
    stage_pin = pin(job / "stage.json")
    details["stage"] = stage_pin
    details["worker"] = stage["worker"]
    try:
        run = V32Runtime(timeout=runtime_timeout).run(
            job,
            stage_sha256=stage_pin["sha256"],
            profile=paths["runtime_profile"],
            profile_sha256=profiles["runtime_profile"]["sha256"],
        )
    except V32RuntimeError:
        runs = list((job / "runs").glob("*/native.process-exit.json"))
        if len(runs) != 1:
            raise
        receipt = json.loads(runs[0].read_bytes())
        stop, failure = checksum_tail(runs[0].with_name("native.stdout.log"))
        details["process_receipt"] = pin(runs[0])
        return _observation(
            classify_process(receipt, stop=stop, failure=failure), stop=stop
        ), details
    (job / "simulation-result.json").write_text(json.dumps(run, indent=2) + "\n")
    terminal = admit_v32_capture(
        job,
        run,
        stage_sha256=stage_pin["sha256"],
        runtime_profile=paths["runtime_profile"],
        runtime_profile_sha256=profiles["runtime_profile"]["sha256"],
    )
    details["run"] = run
    if tier != "checksum-only":
        encoding = V32Encoder(timeout=encoder_timeout).encode(
            job,
            run,
            stage_sha256=stage_pin["sha256"],
            runtime_profile=paths["runtime_profile"],
            runtime_profile_sha256=profiles["runtime_profile"]["sha256"],
            encoder_config=paths["encoder_config"],
            encoder_config_sha256=profiles["encoder_config"]["sha256"],
        )
        result = {
            "status": "experimental_v32_recording_verified",
            "recording": encoding["recording"],
            "stage": stage_pin,
            "worker": stage["worker"],
            "run": run,
            "encoding": encoding,
            "shipping_cache_published": False,
            "general_game_parity_verified": False,
        }
        (job / "pipeline-result.json").write_text(json.dumps(result, indent=2) + "\n")
        details["recording"] = encoding["recording"]
    receipt = json.loads(Path(run["receipt"]["path"]).read_bytes())
    return _observation(classify_process(receipt, terminal=terminal), terminal=terminal), details


def revalidate_completed_job(
    entry: dict[Any, Any], root: Path, job: Path, producer: dict[Any, Any]
) -> tuple[dict[Any, Any], dict[Any, Any]]:
    """Read an explicitly selected closed attempt, without claiming a newly launched run."""
    job = job.resolve(strict=True)
    path = job / "pipeline-result.json"
    if path.is_file():
        imported = {
            **entry,
            "producer": producer,
            "import_format": "v32_pipeline",
            "evidence": pin(path),
        }
        observation, details = import_retained(imported, root, verify=True)
        details["job"] = str(job)
        return observation, details
    from .native_v32_runtime import _verify

    runs = list((job / "runs").glob("*/native.process-exit.json"))
    if len(runs) != 1:
        raise ValueError("Completed job needs exactly one closed process receipt")
    receipt_path = runs[0]
    receipt = json.loads(receipt_path.read_bytes())
    stage = json.loads(check_pin(receipt["stage"], root).read_bytes())
    profiles = producer["pins"]
    runtime_path = check_pin(profiles["runtime_profile"], root)
    if receipt["runtime_profile"] != pin(runtime_path):
        raise ValueError("Closed job runtime producer differs")
    runtime = json.loads(runtime_path.read_bytes())
    if (
        stage["recording"]["sha256"] != entry["replay"]["sha256"]
        or stage["profile"] != runtime["staging_profile"]
    ):
        raise ValueError("Closed job replay or source producer differs")
    if stage["profile"]["sha256"] != profiles["source_profile"]["sha256"]:
        raise ValueError("Closed job source profile differs")
    for row in [
        runtime["staging_profile"],
        runtime["raw_dat"],
        *runtime["system"].values(),
        *runtime["assets"].values(),
        *runtime["technology_assets"],
        stage["profile"],
        stage["recording"],
        stage["host"],
        stage["worker"],
        *stage["stager_sources"],
        *stage["copied_sources"],
        *stage["generated"],
    ]:
        _verify(row)
    capture = receipt_path.with_name("native.stdout.log")
    if pin(capture)["sha256"] != receipt["stdout_sha256"]:
        raise ValueError("Closed job capture differs")
    if pin(receipt_path.with_name("native.stderr.log"))["sha256"] != receipt["stderr_sha256"]:
        raise ValueError("Closed job stderr differs")
    stop, failure = checksum_tail(capture)
    return _observation(classify_process(receipt, stop=stop, failure=failure), stop=stop), {
        "job": str(job),
        "raw_evidence_revalidated": True,
        "process_receipt": pin(receipt_path),
        "capture": pin(capture),
        "worker": stage["worker"],
    }


def scorecard(
    manifest_path: Path,
    *,
    tier: str = "metadata",
    entries: list[str] | None = None,
    execute: bool = False,
    verify_retained: bool = False,
    work_root: Path | None = None,
    encoder_config: dict[Any, Any] | None = None,
    runtime_timeout: float = 2400,
    encoder_timeout: float = 1800,
    completed_jobs: dict[str, Path] | None = None,
) -> dict[Any, Any]:
    if tier not in TIERS or (execute and (tier == "metadata" or work_root is None)):
        raise ValueError("Execution needs a non-metadata tier and explicit work root")
    tooling_pin = pin(Path(__file__).resolve())
    manifest_pin = pin(manifest_path.resolve(strict=True))
    manifest, root = load_manifest(manifest_path)
    if pin(manifest_path.resolve()) != manifest_pin:
        raise ValueError("Manifest changed while reading")
    completed_jobs = completed_jobs or {}
    available = {row["id"] for row in manifest["entries"]}
    if set(completed_jobs) - available:
        raise ValueError("Unknown completed-job corpus entry")
    if entries and set(entries) - available:
        raise ValueError("Unknown corpus entry")
    rows = []
    started = time.monotonic()
    for entry in manifest["entries"]:
        if entries and entry["id"] not in entries:
            continue
        row = {
            "id": entry["id"],
            "scope": entry["scope"],
            "evidence_kind": entry["evidence_kind"],
            "origin": (
                "completed_job_revalidation"
                if entry["id"] in completed_jobs
                else "fresh_execution"
                if execute
                else "retained_import"
            ),
            "status": "skipped",
            "baseline_reproduced": False,
            "expected": entry["expected"],
            "replay_sha256": entry["replay"]["sha256"],
        }
        rows.append(row)
        if (
            execute
            and entry["id"] not in completed_jobs
            and tier not in entry.get("execution_tiers", [])
        ):
            row["skip_reason"] = f"No {tier} execution recipe for this exact producer"
            continue
        try:
            check_pin(entry["replay"], root)
            original = entry["producer"]
            override = None
            if (execute or entry["id"] in completed_jobs) and encoder_config:
                override = {"pins": {**original["pins"], "encoder_config": encoder_config}}
            producer, producer_info = _producer(entry, root, override)
            row["producer"] = producer_info
            if entry["id"] in completed_jobs:
                observation, details = revalidate_completed_job(
                    entry, root, completed_jobs[entry["id"]], producer
                )
            elif execute:
                assert work_root is not None  # checked with the tier on entry
                observation, details = execute_v32(
                    entry,
                    root,
                    work_root=work_root,
                    tier=tier,
                    producer=producer,
                    runtime_timeout=runtime_timeout,
                    encoder_timeout=encoder_timeout,
                )
            else:
                observation, details = import_retained(entry, root, verify=verify_retained)
            row.update({"observation": observation, "evidence": details})
            row["expectation_matches"] = _expected_matches(observation, entry["expected"])
            row["baseline_reproduced"] = (
                row["origin"] == "fresh_execution" and row["expectation_matches"]
            )
            row["status"] = (
                ("passed" if row["expectation_matches"] else "failed")
                if (execute or verify_retained or entry["id"] in completed_jobs)
                else ("metadata_verified" if row["expectation_matches"] else "failed")
            )
            row["result_identity"] = identity(
                {
                    "replay": row["replay_sha256"],
                    "producer": producer_info["identity"],
                    "observation": observation,
                }
            )
        except FileNotFoundError as error:
            row["skip_reason"] = f"Required local input unavailable: {error}"
        except (OSError, ValueError, RuntimeError, KeyError, TypeError) as error:
            row.update({"status": "failed", "error": f"{type(error).__name__}: {error}"})
    required = {"synthetic-short", "public-1v1"}
    fresh_passes = {row["id"] for row in rows if row["baseline_reproduced"]}
    runtime_observations = {
        row["id"]
        for row in rows
        if row["status"] == "passed"
        and row["origin"] in ("fresh_execution", "completed_job_revalidation")
    }
    if pin(manifest_path.resolve()) != manifest_pin:
        raise ValueError("Manifest changed during corpus run")
    return {
        "schema": SCHEMA,
        "manifest": manifest_pin,
        "scorecard_tool": tooling_pin,
        "tool_source_unchanged_during_run": pin(Path(__file__).resolve()) == tooling_pin,
        "tier": tier,
        "execution_requested": execute,
        "retained_revalidation_requested": verify_retained,
        "seconds": time.monotonic() - started,
        "entries": rows,
        "summary": {
            name: sum(row["status"] == name for row in rows)
            for name in ("passed", "failed", "skipped", "metadata_verified")
        },
        "fresh_poc0_runtime_gate_satisfied": required <= fresh_passes,
        "poc0_selected_runtime_evidence_gate_satisfied": required <= runtime_observations,
        "general_compatibility_claimed": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest", type=Path, default=Path("docs/design/native-replay-corpus.json")
    )
    parser.add_argument("--tier", choices=TIERS, default="metadata")
    parser.add_argument("--entry", action="append")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--verify-retained", action="store_true")
    parser.add_argument("--work-root", type=Path)
    parser.add_argument(
        "--completed-job",
        action="append",
        default=[],
        metavar="ENTRY=PATH",
        help="Revalidate one closed attempt; does not launch a worker",
    )
    parser.add_argument("--encoder-config", type=Path)
    parser.add_argument("--encoder-config-sha256")
    parser.add_argument("--runtime-timeout", type=float, default=2400)
    parser.add_argument("--encoder-timeout", type=float, default=1800)
    args = parser.parse_args()
    override = None
    if args.encoder_config:
        override = pin(args.encoder_config.resolve(strict=True))
        if override["sha256"] != args.encoder_config_sha256:
            parser.error("Encoder override requires its matching --encoder-config-sha256")
    elif args.encoder_config_sha256:
        parser.error("Encoder digest needs --encoder-config")
    completed_jobs = {}
    for assignment in args.completed_job:
        name, separator, value = assignment.partition("=")
        if not separator or not value or name in completed_jobs:
            parser.error("Completed jobs require distinct ENTRY=PATH assignments")
        completed_jobs[name] = Path(value)
    result = scorecard(
        args.manifest,
        tier=args.tier,
        entries=args.entry,
        execute=args.execute,
        verify_retained=args.verify_retained,
        work_root=args.work_root,
        encoder_config=override,
        runtime_timeout=args.runtime_timeout,
        encoder_timeout=args.encoder_timeout,
        completed_jobs=completed_jobs,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as stream:
        json.dump(result, stream, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps({"report": str(args.output), "summary": result["summary"]}))
    if result["summary"]["failed"] or result["summary"]["skipped"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
