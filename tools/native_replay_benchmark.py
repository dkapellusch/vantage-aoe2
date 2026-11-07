#!/usr/bin/env python3
"""Alternate full, terminal-admitted baseline/candidate encodes on one fixed capture.

No simulation worker, partial recording, index or browser is run. Each encode
retains its original admission and complete serialized-frame readback gates.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import resource
import statistics
import struct
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from vantage.native_conversion import pin  # noqa: E402  (after the sys.path line)
from vantage.native_v32_encode import V32Encoder, verify_encoder_config  # noqa: E402

ORDER = ("A", "B", "B", "A")
U32 = struct.Struct("<I")


def checked(row: dict) -> Path:
    path = Path(row["path"])
    if pin(path) != row:
        raise ValueError(f"Benchmark pinned input changed: {path}")
    return path


def write_new(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x") as stream:
        json.dump(value, stream, indent=2, allow_nan=False)
        stream.write("\n")


def _exact(stream, size: int) -> bytes:
    value = stream.read(size)
    if len(value) != size:
        raise ValueError("Truncated serialized recording")
    return value


def scan_serialized_frames(path: Path) -> dict:
    """Hash the exact eight-byte envelope and four length-prefixed raw payloads."""
    before = pin(path.resolve(strict=True))
    digest = hashlib.sha256()
    count, last = 0, None
    with gzip.open(path, "rb") as stream:
        if _exact(stream, 5) != b"VREC\x01":
            raise ValueError("Unsupported recording magic")
        size = U32.unpack(_exact(stream, 4))[0]
        if size > 16 << 20:
            raise ValueError("Recording header exceeds benchmark bound")
        json.loads(_exact(stream, size))
        while True:
            envelope = stream.read(8)
            if not envelope:
                break
            if len(envelope) != 8:
                raise ValueError("Truncated frame envelope")
            digest.update(envelope)
            last, _ = struct.unpack("<II", envelope)
            for _ in range(4):
                length = _exact(stream, 4)
                size = U32.unpack(length)[0]
                if size > 1 << 30:
                    raise ValueError("Recording payload exceeds benchmark bound")
                digest.update(length)
                digest.update(_exact(stream, size))
            count += 1
    if pin(path.resolve()) != before:
        raise ValueError("Recording changed during complete frame scan")
    return {
        "recording": before,
        "frames": count,
        "end_ms": last,
        "serialized_frame_payload_sha256": digest.hexdigest(),
        "headers_compared": False,
        "all_frames_consumed": True,
    }


def evaluate_runs(runs: list[dict], *, minimum_improvement: float) -> dict:
    """Two samples per variant are evidence for this run, not a confidence interval."""
    if not 0 <= minimum_improvement < 1:
        raise ValueError("Improvement target must be between zero and one")
    if len(runs) != 4 or tuple(row["label"] for row in runs) != ORDER:
        raise ValueError("Complete A/B/B/A results are required")
    frames = [row["frames"] for row in runs]
    matching = all(
        (row["frames"], row["end_ms"], row["serialized_frame_payload_sha256"])
        == (frames[0]["frames"], frames[0]["end_ms"], frames[0]["serialized_frame_payload_sha256"])
        for row in frames
    )
    times = {}
    for metric in ("encoder_child_seconds", "admission_and_encoding_seconds"):
        baseline = [row["timings"][metric] for row in runs if row["label"] == "A"]
        candidate = [row["timings"][metric] for row in runs if row["label"] == "B"]
        if any(type(value) not in (int, float) or value <= 0 for value in baseline + candidate):
            raise ValueError("Positive measured run timings are required")
        mean_a, mean_b = statistics.mean(baseline), statistics.mean(candidate)
        improvement = 1 - mean_b / mean_a
        times[metric] = {
            "baseline": baseline,
            "candidate": candidate,
            "baseline_mean": mean_a,
            "candidate_mean": mean_b,
            "mean_fraction_lower": improvement,
            "both_candidate_runs_faster_than_both_baselines": max(candidate) < min(baseline),
            "target_met": improvement >= minimum_improvement,
        }
    repeatable = all(
        row["target_met"] and row["both_candidate_runs_faster_than_both_baselines"]
        for row in times.values()
    )
    return {
        "all_exact_frame_envelopes_and_four_payloads_equal": matching,
        "timings": times,
        "minimum_mean_fraction_lower_target": minimum_improvement,
        "repeatable_encoder_component_improvement_observed": matching and repeatable,
        "complete_simulation_conversion_speedup_claimed": False,
        "index_or_browser_speedup_claimed": False,
        "statistical_confidence_interval_claimed": False,
    }


def once(request_path: Path, request_sha256: str, label: str, index: int, output: Path) -> None:
    request_pin = pin(request_path.resolve(strict=True))
    if request_pin["sha256"] != request_sha256:
        raise ValueError("Benchmark request differs")
    request = json.loads(request_path.read_bytes())
    checked(request["benchmark_tool"])
    stage_path = checked(request["stage"])
    run_path = checked(request["simulation_result"])
    runtime = checked(request["runtime_profile"])
    config = checked(request["configs"][label])
    run = json.loads(run_path.read_bytes())
    before_load = os.getloadavg()
    started = time.monotonic()
    encoding = V32Encoder(
        timeout=request["encoder_timeout"], disk_floor_bytes=request["disk_floor_bytes"]
    ).encode(
        stage_path.parent,
        run,
        stage_sha256=request["stage"]["sha256"],
        runtime_profile=runtime,
        runtime_profile_sha256=request["runtime_profile"]["sha256"],
        encoder_config=config,
        encoder_config_sha256=request["configs"][label]["sha256"],
    )
    elapsed = time.monotonic() - started
    process = json.loads(checked(encoding["process_receipt"]).read_bytes())
    terminal = json.loads(checked(encoding["terminal"]).read_bytes())
    child_usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    self_usage = resource.getrusage(resource.RUSAGE_SELF)
    scan_started = time.monotonic()
    frames = scan_serialized_frames(checked(encoding["recording"]))
    scan_seconds = time.monotonic() - scan_started
    if (frames["frames"], frames["end_ms"]) != (
        terminal["expected_frames"],
        terminal["expected_end_ms"],
    ):
        raise ValueError("Complete recording extent differs from admitted terminal")
    multiplier = 1 if sys.platform == "darwin" else 1024
    if (
        type(terminal["original_terminal_event"]["checksum_ignore_global"]) is not int
        or terminal["original_terminal_event"]["checksum_ignore_global"] != 0
    ):
        raise ValueError("Original checksum enforcement required")
    checked(request["stage"])
    checked(request["simulation_result"])
    checked(request["runtime_profile"])
    checked(request["configs"][label])
    checked(request["benchmark_tool"])
    write_new(
        output,
        {
            "kind": "vantage_native_encoder_benchmark_run_v1",
            "label": label,
            "index": index,
            "fixed_capture": run["capture"],
            "encoding": encoding,
            "frames": frames,
            "timings": {
                "encoder_child_seconds": process["seconds"],
                "admission_and_encoding_seconds": elapsed,
                "admission_and_wrapper_validation_seconds": elapsed - process["seconds"],
                "independent_exact_frame_scan_seconds": scan_seconds,
                "simulation_seconds": None,
                "index_seconds": None,
                "browser_seconds": None,
            },
            "resources": {
                "sandbox_launcher_rusage_peak_rss_bytes": child_usage.ru_maxrss * multiplier,
                "wrapper_peak_rss_bytes": self_usage.ru_maxrss * multiplier,
                "sandbox_launcher_user_seconds": child_usage.ru_utime,
                "sandbox_launcher_system_seconds": child_usage.ru_stime,
                "actual_encoder_ram_or_cpu_measured_by_rusage": False,
            },
            "terminal": {
                "game_ended": terminal["game_ended"],
                "reason": terminal["recording_end_reason"],
                "clock_ms": terminal["expected_end_ms"],
                "original_checksum_enforced": True,
            },
            "host_load_before": list(before_load),
            "host_load_after": list(os.getloadavg()),
            "no_native_simulation_worker_launched": True,
        },
    )


def _new_output_bytes(job: Path, before: set[Path]) -> int:
    total = 0
    encodes = job / "encodes"
    if encodes.is_dir():
        for directory in encodes.iterdir():
            if directory in before or directory.is_symlink() or not directory.is_dir():
                continue
            for path in directory.rglob("*"):
                try:
                    if path.is_file() and not path.is_symlink():
                        total += path.stat().st_size
                except FileNotFoundError:
                    continue
    return total


def benchmark(args) -> dict:
    if not 0 <= args.minimum_improvement < 1:
        raise ValueError("Improvement target must be between zero and one")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    job = args.job.resolve(strict=True)
    stage_pin, run_pin = pin(job / "stage.json"), pin(job / "simulation-result.json")
    if stage_pin["sha256"] != args.stage_sha256:
        raise ValueError("Selected stage hash differs")
    configs = {
        "A": pin(args.baseline_config.resolve(strict=True)),
        "B": pin(args.candidate_config.resolve(strict=True)),
    }
    runtime = pin(args.runtime_profile.resolve(strict=True))
    if runtime["sha256"] != args.runtime_profile_sha256:
        raise ValueError("Runtime profile hash differs")
    for label, expected in (
        ("A", args.baseline_config_sha256),
        ("B", args.candidate_config_sha256),
    ):
        if configs[label]["sha256"] != expected:
            raise ValueError("Selected encoder configuration hash differs")
        verify_encoder_config(Path(configs[label]["path"]), expected, stage_dir=job)
    run = json.loads(checked(run_pin).read_bytes())
    checked(run["capture"])
    checked(run["receipt"])
    request = {
        "kind": "vantage_native_encoder_benchmark_request_v1",
        "stage": stage_pin,
        "simulation_result": run_pin,
        "runtime_profile": runtime,
        "configs": configs,
        "encoder_timeout": args.encoder_timeout,
        "disk_floor_bytes": args.disk_floor_bytes,
        "order": list(ORDER),
        "benchmark_tool": pin(Path(__file__).resolve()),
        "minimum_improvement": args.minimum_improvement,
    }
    request_path = output / "request.json"
    write_new(request_path, request)
    request_pin = pin(request_path)
    records = []
    started = time.monotonic()
    before_directories = set((job / "encodes").iterdir()) if (job / "encodes").is_dir() else set()
    observed_peak = 0
    try:
        for index, label in enumerate(ORDER):
            record_path = output / f"{index}-{label}.json"
            command = [
                sys.executable,
                str(Path(__file__).resolve()),
                "_once",
                "--request",
                str(request_path),
                "--request-sha256",
                request_pin["sha256"],
                "--label",
                label,
                "--index",
                str(index),
                "--output",
                str(record_path),
            ]
            write_new(output / f"{index}-{label}-invocation.json", {"command": command})
            print(
                json.dumps({"stage": "encoding_start", "index": index, "label": label}), flush=True
            )
            with (
                (output / f"{index}-{label}.stdout").open("xb") as stdout,
                (output / f"{index}-{label}.stderr").open("xb") as stderr,
            ):
                child = subprocess.Popen(
                    command, stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr
                )
                write_new(
                    output / f"{index}-{label}-process-start.json",
                    {"pid": child.pid, "command": command},
                )
                try:
                    while child.poll() is None:
                        observed_peak = max(
                            observed_peak, _new_output_bytes(job, before_directories)
                        )
                        time.sleep(0.25)
                finally:
                    if child.poll() is None:
                        child.terminate()
                        child.wait(timeout=10)
            write_new(
                output / f"{index}-{label}-process-exit.json",
                {"pid": child.pid, "exit_code": child.returncode},
            )
            if child.returncode != 0:
                raise RuntimeError(f"Encoder benchmark run failed: {index}-{label}; see its stderr")
            record = json.loads(record_path.read_bytes())
            records.append(record)
            observed_peak = max(observed_peak, _new_output_bytes(job, before_directories))
            print(
                json.dumps(
                    {
                        "stage": "encoding_complete",
                        "index": index,
                        "label": label,
                        "timings": record["timings"],
                    }
                ),
                flush=True,
            )
        evaluation = evaluate_runs(records, minimum_improvement=args.minimum_improvement)
        checked(request["benchmark_tool"])
        checked(stage_pin)
        checked(run_pin)
        checked(run["capture"])
        report = {
            "kind": "vantage_native_encoder_benchmark_v1",
            "benchmark_completed": True,
            "request": request_pin,
            "runs": [pin(output / f"{index}-{label}.json") for index, label in enumerate(ORDER)],
            "evaluation": evaluation,
            "seconds": time.monotonic() - started,
            "storage": {
                "new_encode_outputs_observed_peak_bytes": observed_peak,
                "new_encode_outputs_final_bytes": _new_output_bytes(job, before_directories),
                "sampling_interval_seconds": 0.25,
                "fixed_capture_bytes": run["capture"]["bytes"],
                "disk_floor_bytes": args.disk_floor_bytes,
            },
            "all_runs_full_native_game_end": all(
                row["terminal"]["game_ended"] is True for row in records
            ),
            "all_original_checksum_gates_enforced": all(
                row["terminal"]["original_checksum_enforced"] is True for row in records
            ),
            "shared_host": True,
            "poc10_complete": False,
            "limitations": [
                "Two samples per variant; polling quantization is 0.25 seconds.",
                "Host was shared; no cache flushing, CPU pinning or exclusive performance claim.",
                "This benchmarks exact encoder output from a fixed capture; no simulation, index or browser timing.",
                "Observed storage peak is sampled; RUSAGE_CHILDREN describes launcher accounting only. Use the external process-tree observer for actual encoder RAM/CPU.",
                "No new capture transport is adopted and full end-to-end conversion improvement is unproven.",
            ],
        }
    except BaseException as error:
        report = {
            "kind": "vantage_native_encoder_benchmark_v1",
            "benchmark_completed": False,
            "request": request_pin,
            "completed_runs": len(records),
            "error": f"{type(error).__name__}: {error}",
            "poc10_complete": False,
        }
        write_new(output / "report.json", report)
        raise
    write_new(output / "report.json", report)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run")
    run.add_argument("--job", type=Path, required=True)
    run.add_argument("--stage-sha256", required=True)
    run.add_argument("--runtime-profile", type=Path, required=True)
    run.add_argument("--runtime-profile-sha256", required=True)
    for name in ("baseline-config", "candidate-config"):
        run.add_argument("--" + name, type=Path, required=True)
        run.add_argument("--" + name + "-sha256", required=True)
    run.add_argument("--output", type=Path, required=True)
    run.add_argument("--encoder-timeout", type=float, default=1800)
    run.add_argument("--disk-floor-bytes", type=int, default=5 << 30)
    run.add_argument("--minimum-improvement", type=float, default=0.05)
    child = commands.add_parser("_once", help=argparse.SUPPRESS)
    child.add_argument("--request", type=Path, required=True)
    child.add_argument("--request-sha256", required=True)
    child.add_argument("--label", choices=("A", "B"), required=True)
    child.add_argument("--index", type=int, required=True)
    child.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "_once":
        once(args.request, args.request_sha256, args.label, args.index, args.output)
    else:
        result = benchmark(args)
        print(
            json.dumps(
                {"report": str(args.output / "report.json"), "evaluation": result["evaluation"]}
            ),
            flush=True,
        )


if __name__ == "__main__":
    main()
