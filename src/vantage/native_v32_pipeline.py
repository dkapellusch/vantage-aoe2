"""Experimental local recording-to-VREC pipeline using a private V32 worker.

Profiles are explicit, machine-specific research inputs. A successful VREC is
not a claim that every replay or multiplayer simulation is compatible.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import signal
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from vantage.native_conversion import pin
from vantage.native_v32_encode import V32Encoder, verify_encoder_config
from vantage.native_v32_prepare import prepare_v32_worker
from vantage.native_v32_reuse import verified_recording
from vantage.native_v32_runtime import V32Runtime, V32RuntimeError

_UPDATE_CLOCK = re.compile(
    rb'\{"stage":"native_world_update_returned",[^\n]*?"world_time_ms":(\d+)[^\n]*\}\r?\n'
)


def _clock_text(milliseconds: int) -> str:
    seconds = milliseconds // 1000
    return f"{seconds // 60}:{seconds % 60:02d}"


def _report_simulation_progress(job: Path, stop: threading.Event) -> None:
    """Read only the end of this job's output; never attach to a process."""
    try:
        final = json.loads((job / "source/descriptor.json").read_bytes())["final_clock_ms"]
        if type(final) is not int or final <= 0:
            return
        last = -1
        while not stop.wait(5):
            paths = list((job / "runs").glob("*/native.stdout.log"))
            if len(paths) != 1:
                continue
            with paths[0].open("rb") as stream:
                stream.seek(0, os.SEEK_END)
                size = stream.tell()
                stream.seek(max(0, size - 65536))
                tail = stream.read(65536)
            clocks = list(_UPDATE_CLOCK.finditer(tail))
            if not clocks:
                continue
            current = int(clocks[-1].group(1))
            if last < current <= final:
                print(
                    f"Simulated {_clock_text(current)} of {_clock_text(final)}…",
                    file=sys.stderr,
                    flush=True,
                )
                last = current
    except (OSError, KeyError, TypeError, ValueError):
        # Progress is optional and cannot change the success or failure gate.
        return


def _checksum_stop(job: Path) -> dict[Any, Any] | None:
    """Read a bounded tail of this job's log after the worker has stopped."""
    try:
        paths = list((job / "runs").glob("*/native.stdout.log"))
        if len(paths) != 1:
            return None
        with paths[0].open("rb") as stream:
            stream.seek(0, os.SEEK_END)
            stream.seek(max(0, stream.tell() - 1024 * 1024))
            lines = stream.read().splitlines()
        stops = []
        checksum_failures = []
        for line in lines:
            try:
                event = json.loads(line)
            except (ValueError, UnicodeError):
                continue
            if isinstance(event, dict) and event.get("stage") == "native_sync_stopped":
                stops.append(event)
            if (
                isinstance(event, dict)
                and event.get("ok") is False
                and event.get("stage") == "native_prefix_sync"
                and type(event.get("error")) is int
                and event["error"] == 207
            ):
                checksum_failures.append(event)
        if len(stops) != 1 or len(checksum_failures) != 1:
            return None
        stop = stops[0]
        if (
            type(stop.get("status")) is int
            and stop["status"] == 3
            and type(stop.get("world_time_ms")) is int
            and stop["world_time_ms"] >= 0
            and type(stop.get("ignore_checksum_global")) is int
            and stop["ignore_checksum_global"] == 0
        ):
            return stop
    except OSError:
        return None
    return None


_FALLBACK_FLAGS = (
    "--preview-on-checksum-failure",
    "--approximate-on-checksum-failure",
    "--approximate-checksums",
)


def preview_rerun_argv(argv: list[str], *, replay: Path, job: Path) -> list[str]:
    """Rebuild this command for the checksum-bounded preview of a failed replay.

    Swaps ``--replay`` and ``--job`` and drops the fallback flag so a preview that
    itself stops at a checksum is reported rather than retried forever.
    """
    out: list[str] = []
    skip = False
    for item in argv:
        if skip:
            skip = False
            continue
        if item in ("--replay", "--job"):
            skip = True
            continue
        if item.startswith(("--replay=", "--job=")) or item in _FALLBACK_FLAGS:
            continue
        out.append(item)
    return [*out, "--replay", str(replay), "--job", str(job)]


def approximate_rerun_argv(argv: list[str], *, job: Path) -> list[str]:
    """Rebuild this command as an explicit approximate-checksum run in a fresh job."""
    replay = Path(_option_value(argv, "--replay"))
    return [*preview_rerun_argv(argv, replay=replay, job=job), "--approximate-checksums"]


def _option_value(argv: list[str], name: str) -> str:
    for index, item in enumerate(argv):
        if item == name:
            return argv[index + 1]
        if item.startswith(name + "="):
            return item.split("=", 1)[1]
    raise ValueError(f"{name} is missing")


def verify_profiles(args: argparse.Namespace) -> None:
    """Reject mismatched profiles before creating or simulating a job."""
    source, runtime = pin(args.source_profile), pin(args.runtime_profile)
    if source["sha256"] != args.source_profile_sha256:
        raise ValueError("Source profile hash differs")
    if runtime["sha256"] != args.runtime_profile_sha256:
        raise ValueError("Runtime profile hash differs")
    runtime_doc = json.loads(args.runtime_profile.read_bytes())
    if pin(args.runtime_profile) != runtime or runtime_doc.get("staging_profile") != source:
        raise ValueError("Runtime profile does not match the source profile")
    verify_encoder_config(
        args.encoder_config, args.encoder_config_sha256, stage_dir=args.job.expanduser().resolve()
    )


def _convert_preview_after_stop(args: argparse.Namespace, stop_ms: int) -> None:
    """Prepare and convert the preview before a failing checksum; never returns on success."""
    from vantage.native_v32_preview import prepare_preview_before

    job = args.job.resolve()
    # The worker sandbox replaces /tmp with an empty tmpfs, so the preview input must
    # live elsewhere (the replay itself is read from its real path inside it).
    cache = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache")
    result = prepare_preview_before(
        args.replay,
        cache / "vantage-native" / "previews" / f"{job.name}-{uuid.uuid4().hex[:8]}",
        stop_ms,
    )
    preview = Path(result["preview"]["path"])
    print(
        f"Converting the incomplete preview ending at {_clock_text(result['preview_end_ms'])} "
        "(the last passing checksum); the rest of the match is not simulated.",
        file=sys.stderr,
        flush=True,
    )
    argv = preview_rerun_argv(
        sys.argv[1:], replay=preview, job=job.with_name(job.name + "-preview")
    )
    os.execv(sys.executable, [sys.executable, "-m", "vantage.native_v32_pipeline", *argv])


def _use_approximate_profiles(args: argparse.Namespace) -> None:
    """Swap the strict profiles for the derived approximate-checksum ones."""
    from vantage.native_v32_approximate import build_profiles

    job = args.job.expanduser().resolve()
    built = build_profiles(
        args.source_profile, args.runtime_profile, job.with_name(job.name + "-profiles")
    )
    args.source_profile = Path(built["source_profile"])
    args.source_profile_sha256 = str(built["source_sha256"])
    args.runtime_profile = Path(built["runtime_profile"])
    args.runtime_profile_sha256 = str(built["runtime_sha256"])


def _rerun_approximate(args: argparse.Namespace) -> None:
    """Rerun the whole replay with checksums ignored; never returns."""
    job = args.job.resolve()
    print(
        "Rerunning the whole replay in APPROXIMATE mode: checksums are ignored, so the "
        "recording is labelled approximate.",
        file=sys.stderr,
        flush=True,
    )
    argv = approximate_rerun_argv(sys.argv[1:], job=job.with_name(job.name + "-approximate"))
    os.execv(sys.executable, [sys.executable, "-m", "vantage.native_v32_pipeline", *argv])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--replay", type=Path, help="recording to simulate")
    source.add_argument("--resume", action="store_true", help="reuse a completed capture")
    parser.add_argument("--job", type=Path, required=True, help="private job directory")
    for name in ("source-profile", "runtime-profile", "encoder-config"):
        parser.add_argument("--" + name, type=Path, required=True)
        parser.add_argument("--" + name + "-sha256", required=True)
    parser.add_argument(
        "--preview-on-checksum-failure",
        action="store_true",
        help="after a checksum stop, convert the incomplete preview up to the last passing "
        "checksum (labelled incomplete) instead of failing with no recording",
    )
    parser.add_argument(
        "--approximate-checksums",
        action="store_true",
        help="run past replay checksum divergence (the game's own ignore byte) and convert the "
        "whole match; the recording is labelled APPROXIMATE because later state may differ "
        "from the original game",
    )
    parser.add_argument(
        "--approximate-on-checksum-failure",
        action="store_true",
        help="after a checksum stop, rerun the whole replay in approximate mode",
    )
    parser.add_argument("--update-cap", type=int, default=262144)
    parser.add_argument("--runtime-timeout", type=float, default=2400)
    parser.add_argument("--encoder-timeout", type=float, default=1800)
    parser.add_argument("--compile-timeout", type=float, default=180)
    parser.add_argument("--serve", action="store_true", help="serve the completed VREC in Vantage")
    parser.add_argument(
        "--indexed", action="store_true", help="use a persistent playback index with --serve"
    )
    parser.add_argument("--port", type=int, default=8740, help="Vantage port when using --serve")
    parser.add_argument("--game-dir", type=Path, help="game assets for Vantage when using --serve")
    parser.add_argument(
        "--recordings-dir", type=Path, help="Vantage recording directory for --serve"
    )
    args = parser.parse_args()
    if args.serve and not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535 when using --serve")
    if args.indexed and not args.serve:
        parser.error("--indexed requires --serve")
    if args.approximate_checksums:
        _use_approximate_profiles(args)
    verify_profiles(args)
    started = time.monotonic()
    runtime = V32Runtime(timeout=args.runtime_timeout)
    encoder = V32Encoder(timeout=args.encoder_timeout)

    def terminate(_signum: Any, _frame: Any) -> None:
        # The active component's exception cleanup owns its child process group.
        raise KeyboardInterrupt

    previous = signal.signal(signal.SIGTERM, terminate)
    try:
        reused = None
        if args.resume:
            job = args.job.resolve(strict=True)
            stage_path = job / "stage.json"
            stage = json.loads(stage_path.read_bytes())
            source_profile = pin(args.source_profile)
            if (
                source_profile["sha256"] != args.source_profile_sha256
                or stage["profile"] != source_profile
            ):
                raise ValueError("Resume source profile differs from the staged worker")
            stage_pin = pin(stage_path)
            run = json.loads((job / "simulation-result.json").read_bytes())
            result_path = job / "pipeline-result.json"
            if result_path.exists():
                print("Checking the completed recording…", file=sys.stderr, flush=True)
                reused = verified_recording(
                    job,
                    json.loads(result_path.read_bytes()),
                    runtime_profile=args.runtime_profile,
                    runtime_profile_sha256=args.runtime_profile_sha256,
                    encoder_config=args.encoder_config,
                    encoder_config_sha256=args.encoder_config_sha256,
                )
            else:
                print("Reusing the completed private capture…", file=sys.stderr, flush=True)
        else:
            print("Preparing the private worker…", file=sys.stderr, flush=True)
            stage = prepare_v32_worker(
                args.replay,
                args.job,
                profile=args.source_profile,
                profile_sha256=args.source_profile_sha256,
                update_cap=args.update_cap,
                compile_timeout=args.compile_timeout,
            )
            stage_path = args.job.resolve(strict=True) / "stage.json"
            stage_pin = pin(stage_path)
            print("Simulating the replay in the private worker…", file=sys.stderr, flush=True)
            progress_stop = threading.Event()
            progress = threading.Thread(
                target=_report_simulation_progress,
                args=(stage_path.parent, progress_stop),
                daemon=True,
            )
            progress.start()
            try:
                try:
                    run = runtime.run(
                        stage_path.parent,
                        stage_sha256=stage_pin["sha256"],
                        profile=args.runtime_profile,
                        profile_sha256=args.runtime_profile_sha256,
                    )
                except V32RuntimeError:
                    stop = _checksum_stop(stage_path.parent)
                    if stop is not None:
                        clock = _clock_text(stop["world_time_ms"])
                        print(
                            f"Replay checksum check stopped at {clock} "
                            f"({stop['world_time_ms']} ms); no recording was produced.",
                            file=sys.stderr,
                            flush=True,
                        )
                        if args.approximate_on_checksum_failure and args.replay is not None:
                            _rerun_approximate(args)
                        if args.preview_on_checksum_failure and args.replay is not None:
                            _convert_preview_after_stop(args, stop["world_time_ms"])
                    raise
            finally:
                progress_stop.set()
                progress.join()
            temporary = stage_path.parent / f".simulation-result-{uuid.uuid4().hex}.tmp"
            try:
                with temporary.open("x", encoding="utf-8") as stream:
                    json.dump(run, stream, indent=2, allow_nan=False)
                    stream.write("\n")
                os.replace(temporary, stage_path.parent / "simulation-result.json")
            finally:
                temporary.unlink(missing_ok=True)
        if reused is not None:
            result = {"recording": reused["recording"]}
            output = {
                "status": "experimental_v32_recording_reused",
                **reused,
                "seconds": time.monotonic() - started,
            }
        else:
            print("Checking the ending and encoding the recording…", file=sys.stderr, flush=True)
            result = encoder.encode(
                stage_path.parent,
                run,
                stage_sha256=stage_pin["sha256"],
                runtime_profile=args.runtime_profile,
                runtime_profile_sha256=args.runtime_profile_sha256,
                encoder_config=args.encoder_config,
                encoder_config_sha256=args.encoder_config_sha256,
            )
            output = {
                "status": "experimental_v32_recording_verified",
                "recording": result["recording"],
                "stage": stage_pin,
                "worker": stage["worker"],
                "run": run,
                "encoding": result,
                "seconds": time.monotonic() - started,
                "resumed_capture": args.resume,
                "shipping_cache_published": False,
                "general_game_parity_verified": False,
            }
            with (stage_path.parent / "pipeline-result.json").open("x", encoding="utf-8") as stream:
                json.dump(output, stream, indent=2, allow_nan=False)
                stream.write("\n")
        if args.approximate_checksums:
            from vantage.native_v32_approximate import stamp_recording

            # The verified encoder output stays pinned; viewers get the labelled copy.
            verified = Path(result["recording"]["path"])
            result = {
                **result,
                "recording": stamp_recording(
                    verified, verified.with_name(verified.stem + ".approximate.vrec")
                ),
            }
            output["approximate_recording"] = result["recording"]
        print(json.dumps(output, indent=2), flush=True)
    finally:
        signal.signal(signal.SIGTERM, previous)
    if args.serve:
        if args.indexed:
            command = [
                sys.executable,
                "-m",
                "vantage.native_v32_indexed_serve",
                "--recording",
                result["recording"]["path"],
                "--index-root",
                str(stage_path.parent / "playback-index-v2"),
                "--port",
                str(args.port),
            ]
        else:
            command = [
                sys.executable,
                "-m",
                "vantage",
                "serve",
                "--recording",
                result["recording"]["path"],
                "--host",
                "127.0.0.1",
                "--port",
                str(args.port),
            ]
        if args.game_dir is not None:
            command.extend(["--game-dir", str(args.game_dir)])
        if args.recordings_dir is not None:
            command.extend(["--recordings-dir", str(args.recordings_dir)])
        os.execv(sys.executable, command)


if __name__ == "__main__":
    main()
